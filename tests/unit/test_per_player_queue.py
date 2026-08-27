"""per-player 串行队列单测（M6 批2·路A · D2 §三 POOL 件套）——TC-POOL-01~04。

依据：
  - docs/细化/细化_M6_幂等事务三件套.md §三（POOL-1~6 / TC-POOL-01~04 / F-POOL-01~05）
    + §四（承接【批5B】P0-1）
  - 细化_4a_存储层契约.md §3.2 F4 L276-277（幂等查重在入队前；命中幂等返回不入队）
  - 定稿《RPG回合制框架设计文档.md》L1606（per-player 串行队列：同一玩家指令按到达
    顺序处理，防乱序/双结算）

覆盖（qbot_rpg/commands/processing.py PerPlayerQueue + process_message）：
  TC-POOL-01 同玩家指令按序（入队后按到达顺序消费，无乱序）
  TC-POOL-02 不同玩家互不阻塞（per-player 队列隔离：B 独立消费者，不依赖 A 清空队列）
  TC-POOL-03 命中幂等不入队（幂等返回，不占队列、不二次执行业务）
  TC-POOL-04 队列失败不阻塞后续（首条抛异常 → 返回失败原因人话；第二条正常执行）
  补测（D2 §1.4 排队窗口）：同键重复入队 → 先到写键，后到 tx.idem_exists 权威命中幂等返回

【工程补白】DB 用 **文件库（WAL，tmp_path）**而非 :memory:：本件套并发读（入队前
idem_claim）与队列消费者在途写事务同时发生，:memory: 共享缓存库为表级锁（写事务污染
表 → 读侧 SQLITE_LOCKED 不重试），文件库 WAL 下读者永不阻塞 = 生产等价。

【M6 批7·路A 时序加固】忙等预算 range(5000) → range(50000)：coverage 插桩（D7 COV-03
测量运行，scripts/run_all_tests.py 阶段3）下事件循环显著变慢，5000 次 sleep(0) 偶发
在 consumer 调度前耗尽 → 门禁测量假红（实测单文件 3/3 触发）。纯等待预算放宽 10x，
不改断言语义；无 coverage 时 5000 本就充裕，放宽无副作用。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any, Awaitable, Callable, Dict, List

import pytest

from qbot_rpg.commands.processing import PerPlayerQueue, process_message
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import IdemKey, Repository, row_to_player

from conftest import make_player  # type: ignore[import-not-found]


# ---------------------------------------------------------------------------
# 夹具：每调用一个独立文件库（WAL），测试结束统一关闭
# ---------------------------------------------------------------------------
@pytest.fixture
async def repo_factory(tmp_path):
    made: List[Repository] = []
    counter = [0]

    async def factory(qid: str = "10001") -> Repository:
        counter[0] += 1
        db = Database(str(tmp_path / f"repo_{counter[0]}.db"))
        repo = Repository(db)
        await repo.save_player(make_player(qid))
        made.append(repo)
        return repo

    yield factory
    for repo in made:
        await repo.close()


async def _gold(repo: Repository, qid: str) -> int:
    row = await repo.db.fetchone_read(
        "SELECT currencies FROM players WHERE player_qid = ?", (qid,))
    if row is None:
        return 0
    return int(json.loads(row["currencies"]).get("gold", 0))


def _bump(qid: str, amount: int = 100) -> Callable[[Any], Awaitable[Dict[str, Any]]]:
    """业务闭包：事务内金币 +amount 写回。"""

    async def handler(tx: Any) -> Dict[str, Any]:
        row = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (qid,))
        p = row_to_player(row)
        cur = dict(p.currencies)
        cur["gold"] = cur.get("gold", 0) + amount
        await tx.upsert_player(replace(p, currencies=cur))
        return {"ok": True, "message": f"金币 +{amount}"}

    return handler


# ---------------------------------------------------------------------------
# TC-POOL-01 ~ 04
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pool_01_same_player_in_order(repo_factory):
    """TC-POOL-01 同玩家指令按序：a 入队先、b 后 → 消费顺序 = 到达顺序（无乱序）。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        order: List[str] = []
        b_ready = asyncio.Event()

        async def h_a(tx: Any) -> Dict[str, Any]:
            order.append("a")
            await b_ready.wait()      # a 阻塞在 handler 内，确保 b 已入队后才放行
            return {"ok": True, "message": "a"}

        async def h_b(tx: Any) -> Dict[str, Any]:
            order.append("b")
            return {"ok": True, "message": "b"}

        task_a = asyncio.create_task(process_message(
            repo, queue, message_id="pa1", group_id="g", player_qid="10001",
            command="/甲", handler=h_a,
        ))
        # 等 a 入队并进入 handler（阻塞在 b_ready）
        for _ in range(50000):
            await asyncio.sleep(0)
            if order == ["a"]:
                break
        assert order == ["a"], "a 应先入队并进入 handler"
        task_b = asyncio.create_task(process_message(
            repo, queue, message_id="pa2", group_id="g", player_qid="10001",
            command="/乙", handler=h_b,
        ))
        b_ready.set()
        res_a, res_b = await asyncio.gather(task_a, task_b)
        assert res_a["ok"] is True and res_b["ok"] is True
        assert order == ["a", "b"]    # 同玩家 FIFO，按到达顺序消费（POOL-1）
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_pool_02_different_players_parallel(repo_factory):
    """TC-POOL-02 不同玩家互不阻塞：A 队列积压时 B 独立入队并由独立消费者驱动，A 内部仍按序。

    注：SQLite 单写连接锁（SCHEMA-1）串行化事务体，故「并行」观测到的是 per-player
    队列隔离——B 不排在 A 队列之后（全局 FIFO 会被 A 堵住），独立消费者任务驱动、
    enqueue 不等待 A 消费；事务级安全由 BEGIN IMMEDIATE + 单写队列保证。
    """
    repo = await repo_factory()
    await repo.save_player(make_player("10002"))
    queue = PerPlayerQueue(repo)
    try:
        gate = asyncio.Event()
        order: List[str] = []

        async def h_a1(tx: Any) -> Dict[str, Any]:
            order.append("a1")
            await gate.wait()          # A1 持写锁阻塞（模拟长任务）
            return {"ok": True, "message": "a1"}

        async def h_a2(tx: Any) -> Dict[str, Any]:
            order.append("a2")
            return {"ok": True, "message": "a2"}

        async def h_b(tx: Any) -> Dict[str, Any]:
            order.append("b")
            return {"ok": True, "message": "b"}

        # A 提交两条：A1 阻塞（持写锁），A2 排在其后
        ta1 = asyncio.create_task(process_message(
            repo, queue, message_id="A1", group_id="g", player_qid="10001",
            command="/一", handler=h_a1,
        ))
        for _ in range(50000):
            await asyncio.sleep(0)
            if order == ["a1"]:
                break
        assert order == ["a1"], "A1 应先入队并进入 handler"
        ta2 = asyncio.create_task(process_message(
            repo, queue, message_id="A2", group_id="g", player_qid="10001",
            command="/二", handler=h_a2,
        ))
        for _ in range(50000):
            await asyncio.sleep(0)
            if queue.qsize("10001") == 1:   # A2 已入队（积压在 A1 后）
                break
        # 关键断言：A 队列积压（A2 待处理）时 B 提交 → B 独立入队并拉起独立消费者
        assert queue.qsize("10001") == 1
        tb = asyncio.create_task(process_message(
            repo, queue, message_id="B1", group_id="g", player_qid="10002",
            command="/B", handler=h_b,
        ))
        for _ in range(50000):
            await asyncio.sleep(0)
            if queue.has_consumer("10002"):
                break
        assert queue.has_consumer("10002"), "B 应有独立消费者任务（per-player 隔离）"
        assert queue.has_consumer("10001"), "A 消费者仍存活"
        gate.set()
        ra1, ra2, rb = await asyncio.gather(ta1, ta2, tb)
        assert ra1["ok"] is True and ra2["ok"] is True and rb["ok"] is True
        assert order[0] == "a1"
        assert order.index("a1") < order.index("a2")   # A 内部仍按序（POOL-1）
        assert "b" in order                            # B 独立完成，不依赖 A 清空队列
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_pool_03_idempotent_hit_not_enqueued(repo_factory):
    """TC-POOL-03 命中幂等不入队：同键已处理 → 幂等返回，不占队列、不二次执行业务。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        async with repo.tx() as tx:      # 预落键（同 message_id 已处理）
            await tx.write_idem_key(IdemKey(
                message_id="mP", group_id="g", player_qid="10001", command="/签到",
            ))
        calls: List[str] = []

        async def h_never(tx: Any) -> Dict[str, Any]:
            calls.append("exec")         # 业务零执行断言
            return {"ok": True, "message": "不该执行"}

        res = await process_message(
            repo, queue, message_id="mP", group_id="g", player_qid="10001",
            command="/签到", handler=h_never,
        )
        assert res["idempotent"] is True
        assert res["queued"] is False    # 未入队（POOL-3：命中 → 幂等返回不入队）
        assert calls == []               # 业务零执行
        assert queue.qsize("10001") == 0  # 队列未被占用
        assert await _gold(repo, "10001") == 350  # 不重复扣款
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_pool_04_failure_does_not_block_subsequent(repo_factory):
    """TC-POOL-04 队列失败不阻塞后续：首条引擎抛异常 → 返回失败原因人话；第二条正常执行。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        async def bad_handler(tx: Any) -> Dict[str, Any]:
            raise RuntimeError("模拟引擎故障")

        res1 = await process_message(
            repo, queue, message_id="fp1", group_id="g", player_qid="10001",
            command="/故障", handler=bad_handler,
        )
        assert res1["ok"] is False
        assert "失败" in res1["message"]    # 失败原因人话消息（POOL-4，绝不静默吞）
        assert "引擎故障" in res1["message"]

        res2 = await process_message(
            repo, queue, message_id="fp2", group_id="g", player_qid="10001",
            command="/正常", handler=_bump("10001", 100),
        )
        assert res2["ok"] is True           # 第二条正常执行（同玩家队列未卡死）
        assert await _gold(repo, "10001") == 450
        # 首条失败未落孤儿键 → 同键重试按全新处理
        res3 = await process_message(
            repo, queue, message_id="fp1", group_id="g", player_qid="10001",
            command="/故障", handler=_bump("10001", 50),
        )
        assert res3["ok"] is True
        assert await _gold(repo, "10001") == 500
    finally:
        await queue.close()


# ---------------------------------------------------------------------------
# 补测：排队窗口内同键重复入队 → 权威判定（D2 §1.4）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pool_queue_window_duplicate_authoritative(repo_factory):
    """D2 §1.4：同键两条同时入队 → 先到事务写键，后到 tx.idem_exists 权威命中幂等返回。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        gate = asyncio.Event()
        inside: List[str] = []

        async def h1(tx: Any) -> Dict[str, Any]:
            inside.append("h1")
            await gate.wait()             # 先到者卡在业务内，让第二条入队
            return {"ok": True, "message": "先到"}

        async def h2(tx: Any) -> Dict[str, Any]:
            inside.append("h2")
            return {"ok": True, "message": "后到"}

        t1 = asyncio.create_task(process_message(
            repo, queue, message_id="dup", group_id="g", player_qid="10001",
            command="/签到", handler=h1,
        ))
        for _ in range(50000):
            await asyncio.sleep(0)
            if inside == ["h1"]:
                break
        t2 = asyncio.create_task(process_message(
            repo, queue, message_id="dup", group_id="g", player_qid="10001",
            command="/签到", handler=h2,
        ))
        gate.set()
        r1, r2 = await asyncio.gather(t1, t2)
        assert r1["ok"] is True and r1["idempotent"] is False     # 先到执行业务
        assert r2["idempotent"] is True                           # 后到幂等重放（tx.idem_exists 权威）
        assert inside == ["h1"]                                   # 业务仅执行一次（h2 被权威判定拦下）
        assert await repo.idem_find("dup", "g", "10001") is not None
    finally:
        await queue.close()
