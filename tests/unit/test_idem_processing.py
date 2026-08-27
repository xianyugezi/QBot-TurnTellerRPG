"""指令处理入口幂等键接线单测（M6 批2·路A · D2 §一 IDEM 件套）——TC-IDEM-01~06 + settle 补测。

依据：
  - docs/细化/细化_M6_幂等事务三件套.md §一（IDEM-1~8 / TC-IDEM-01~06 / F-IDEM-01~06）
    + §四（承接【批5B】P0-1 / 【批5A】P1-1）
  - docs/细化/细化_M6_接线闭环总纲.md §七 ADR-05（幂等载体=指令处理入口）/ ADR-12
  - 定稿《开发规则文档.md》L319（回复前崩溃 → 不双结算，断言对象=键已落）

覆盖（qbot_rpg/commands/processing.py + qbot_rpg/world/battle_boundary.py）：
  TC-IDEM-01 首次处理写入幂等键（业务生效 + 键落 1 行 + 发送出口调用一次）
  TC-IDEM-02 命中幂等返回（业务零执行、不重复扣款）
  TC-IDEM-03 键三元组区分（同 message_id 不同 player_qid 各自独立执行各自落键）
  TC-IDEM-04 失败整单回滚（业务零残留 + 无孤儿键 → 重试按全新处理）
  TC-IDEM-05 回复前崩溃不双结算（业务已提交 + 键已落，重发幂等返回）
  TC-IDEM-06 7 天清理后可再执行（未过期幂等返回；过期后重发按新处理）
  补测（IDEM-8 settle_exit_idempotent）：首结 True+删会话+落键 / 重结 False 不双结算 /
       预落键直接 False / kind 落 command 审计 + 三元组 PK 去重约束

【工程补白】本文件 DB 用 **文件库（WAL，tmp_path）**而非 :memory:：指令入口的并发
读（idem_claim）会与队列消费者的在途写事务同时发生，:memory: 共享缓存库为表级锁
（写事务污染表 → 读侧 SQLITE_LOCKED 不重试），文件库 WAL 下读者永不阻塞 = 生产等价
（细化_5d §3.2 允许 :memory: 或 tmp_path）。
"""

from __future__ import annotations

import asyncio
import datetime
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional

import pytest

from qbot_rpg.commands.processing import PerPlayerQueue, process_message
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import (
    IdemKey,
    Repository,
    SessionRow,
    row_to_player,
)
from qbot_rpg.world.battle_boundary import settle_exit_idempotent

from conftest import make_player


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


def make_bump_handler(
    qid: str,
    amount: int = 100,
    *,
    raise_after_write: Optional[str] = None,
    record: Optional[List[str]] = None,
) -> Callable[[Any], Awaitable[Dict[str, Any]]]:
    """业务闭包：事务内读玩家 → 金币 +amount → 写回（模拟扣发/购买）。

    raise_after_write：写回后抛异常（验证写已回滚 + 无孤儿键，TC-IDEM-04）。
    record：业务实际执行记录（断言命中幂等时业务零执行）。
    """

    async def handler(tx: Any) -> Dict[str, Any]:
        row = await tx.fetchone("SELECT * FROM players WHERE player_qid = ?", (qid,))
        p = row_to_player(row)
        cur = dict(p.currencies)
        cur["gold"] = cur.get("gold", 0) + amount
        await tx.upsert_player(replace(p, currencies=cur))
        if record is not None:
            record.append("bump")
        if raise_after_write:
            raise RuntimeError(raise_after_write)
        return {"ok": True, "message": f"金币 +{amount}"}

    return handler


async def _send_counter() -> tuple:
    sent: List[Dict[str, Any]] = []

    async def sender(result: Dict[str, Any]) -> None:
        sent.append(result)

    return sent, sender


@pytest.mark.asyncio
async def test_idem_01_first_process_writes_key(repo_factory):
    """TC-IDEM-01 首次处理写入幂等键：业务生效；idempotency_keys 落 1 行；发送出口调用一次。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        sent, sender = await _send_counter()
        res = await process_message(
            repo, queue,
            message_id="m1", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100), sender=sender,
        )
        await asyncio.sleep(0.01)  # 等消费者完成发送出口调用
        assert res["ok"] is True
        assert res["queued"] is True
        assert res["idempotent"] is False
        assert await _gold(repo, "10001") == 450           # 业务生效（350+100）
        found = await repo.idem_find("m1", "g1", "10001")
        assert found is not None                           # 幂等键落 1 行
        assert found.command == "/签到"
        assert found.result_hash                          # F-IDEM-05 result_hash 已填
        assert len(sent) == 1 and sent[0]["ok"] is True    # 发送出口调用一次
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_idem_02_hit_returns_idempotent(repo_factory):
    """TC-IDEM-02 命中幂等返回：业务零执行、不重复扣款/入包。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        await process_message(
            repo, queue,
            message_id="m2", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100),
        )
        # 同键重发
        calls: List[str] = []
        res = await process_message(
            repo, queue,
            message_id="m2", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100, record=calls),
        )
        assert res["ok"] is False
        assert res["idempotent"] is True
        assert res["queued"] is False            # 未入队直接幂等返回
        assert calls == []                       # 业务零执行
        assert await _gold(repo, "10001") == 450  # 不重复扣款（仍 350+100）
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_idem_03_key_triple_distinguishes_players(repo_factory):
    """TC-IDEM-03 键三元组区分：同 message_id 不同 player_qid 各自独立执行、互不幂等。"""
    repo = await repo_factory()
    await repo.save_player(make_player("10002"))
    queue = PerPlayerQueue(repo)
    try:
        r1 = await process_message(
            repo, queue,
            message_id="mX", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100),
        )
        r2 = await process_message(
            repo, queue,
            message_id="mX", group_id="g1", player_qid="10002", command="/签到",
            handler=make_bump_handler("10002", 100),
        )
        assert r1["ok"] is True and r2["ok"] is True       # 各自独立执行
        assert await repo.idem_find("mX", "g1", "10001") is not None
        assert await repo.idem_find("mX", "g1", "10002") is not None  # 各自落键
        assert await _gold(repo, "10001") == 450
        assert await _gold(repo, "10002") == 450
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_idem_04_failure_rolls_back_whole(repo_factory):
    """TC-IDEM-04 失败整单回滚：业务写已发生仍回滚（零残留）+ 幂等键不落（无孤儿键）→ 重试按全新处理。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        res = await process_message(
            repo, queue,
            message_id="m4", group_id="g1", player_qid="10001", command="/购买",
            handler=make_bump_handler("10001", 100, raise_after_write="注入：入包前崩溃"),
        )
        assert res["ok"] is False
        assert "失败" in res["message"]          # 失败原因人话消息（POOL-4）
        assert "注入" in res["message"]
        assert await _gold(repo, "10001") == 350   # 业务零残留（写已回滚）
        assert await repo.idem_find("m4", "g1", "10001") is None  # 无孤儿键
        # 重试按全新处理
        res2 = await process_message(
            repo, queue,
            message_id="m4", group_id="g1", player_qid="10001", command="/购买",
            handler=make_bump_handler("10001", 100),
        )
        assert res2["ok"] is True
        assert await _gold(repo, "10001") == 450
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_idem_05_crash_before_reply_no_double_settle(repo_factory):
    """TC-IDEM-05 回复前崩溃不双结算：业务已提交+键已落；发送出口抛异常后同 message_id 重发幂等返回。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        async def crash_sender(result: Dict[str, Any]) -> None:
            raise RuntimeError("发送出口崩溃（回复前崩溃注入）")

        res1 = await process_message(
            repo, queue,
            message_id="m5", group_id="g1", player_qid="10001", command="/逃跑",
            handler=make_bump_handler("10001", 100), sender=crash_sender,
        )
        await asyncio.sleep(0.01)  # 等消费者完成发送出口（抛异常被吞，不阻塞队列）
        assert res1["ok"] is True
        # 断言对象 = 幂等键已落（非发送出口，【批5B】P1-4 修正）
        assert await repo.idem_find("m5", "g1", "10001") is not None
        # 同 message_id 重发 → 幂等返回，不双结算不双扣
        calls: List[str] = []
        res2 = await process_message(
            repo, queue,
            message_id="m5", group_id="g1", player_qid="10001", command="/逃跑",
            handler=make_bump_handler("10001", 100, record=calls),
        )
        assert res2["idempotent"] is True
        assert calls == []
        assert await _gold(repo, "10001") == 450   # 不双扣（仍 350+100）
    finally:
        await queue.close()


@pytest.mark.asyncio
async def test_idem_06_after_7d_cleanup_can_reprocess(repo_factory):
    """TC-IDEM-06 7 天清理后可再执行：未过期幂等返回；cleanup_idem_keys(7.0) 后重发按新处理执行。"""
    repo = await repo_factory()
    queue = PerPlayerQueue(repo)
    try:
        old = (datetime.datetime.now(datetime.timezone.utc)
               - datetime.timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
        async with repo.tx() as tx:  # 造一条 created_at 超 7 天的幂等键
            await tx.write_idem_key(IdemKey(
                message_id="m6", group_id="g1", player_qid="10001",
                command="/签到", result_hash="h_old", created_at=old,
            ))
        # 未清理：键仍命中 → 幂等返回（业务零执行）
        calls: List[str] = []
        res1 = await process_message(
            repo, queue,
            message_id="m6", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100, record=calls),
        )
        assert res1["idempotent"] is True and calls == []
        # 清理后：键被删
        assert await repo.cleanup_idem_keys(7.0) >= 1
        assert await repo.idem_find("m6", "g1", "10001") is None
        # 重发按新处理执行
        res2 = await process_message(
            repo, queue,
            message_id="m6", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100),
        )
        assert res2["ok"] is True
        assert await _gold(repo, "10001") == 450
    finally:
        await queue.close()


# ---------------------------------------------------------------------------
# IDEM-8 补测：settle_exit_idempotent（battle_boundary.py 实装）
# ---------------------------------------------------------------------------
def _fake_session(*, qid: str = "10001", origin_group: str = "g_battle") -> object:
    """构造会话对象（object 形态：.player_qid + payload 含 origin_group，模拟战斗会话）。"""
    return SimpleNamespace(
        player_qid=qid,
        payload={"origin_group": origin_group, "combo_state": {"chain": 3}, "turn": 5},
    )


async def _seed_battle_session(repo: Repository, qid: str = "10001") -> None:
    """造一个战斗会话（模拟在战斗中）。"""
    async with repo.tx() as tx:
        await tx.upsert_session(SessionRow(
            player_qid=qid, session_type="battle", payload={"turn": 1}, random_seed=7,
        ))


@pytest.mark.asyncio
async def test_idem_08_settle_first_time(repo_factory):
    """IDEM-8：首次结算 → True；战斗会话被删除（连段/资源随会话清除）；幂等键已落。"""
    repo = await repo_factory()
    try:
        await _seed_battle_session(repo)
        ok = await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf1",
            repository=repo,
        )
        assert ok is True
        assert await repo.load_session("10001") is None            # 退出战场回地图（会话已删）
        found = await repo.idem_find("sf1", "g_battle", "10001")
        assert found is not None and found.command == "settle:flee"  # kind 并入 command
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_idem_08_settle_already_settled_false(repo_factory):
    """IDEM-8：同键再次结算 → False（不双结算）；会话不重复删、键不重复写。"""
    repo = await repo_factory()
    try:
        await _seed_battle_session(repo)
        assert await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf2",
            repository=repo,
        ) is True
        # 同键重结 → False（幂等键命中）
        assert await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf2",
            repository=repo,
        ) is False
        assert await repo.load_session("10001") is None
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_idem_08_settle_prewritten_key_false(repo_factory):
    """IDEM-8：幂等键已预落 → 直接 False，会话保留不误删。"""
    repo = await repo_factory()
    try:
        await _seed_battle_session(repo)
        async with repo.tx() as tx:
            await tx.write_idem_key(IdemKey(
                message_id="sf3", group_id="g_battle", player_qid="10001",
                command="settle:flee",
            ))
        ok = await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf3",
            repository=repo,
        )
        assert ok is False
        assert await repo.load_session("10001") is not None  # 已结算 → 不动会话
    finally:
        await repo.close()


@pytest.mark.asyncio
async def test_idem_08_settle_kind_recorded_in_command(repo_factory):
    """IDEM-8：settlement_kind 并入 command 字段（F-IDEM-04 审计/幂等重放识别）。

    注（schema 约束）：idempotency_keys 复合主键 = (message_id, group_id, player_qid)
    （schema.py L71-81 / 4a §1.3），command **不参与去重**——同 message_id+group+qid
    的另一种结算类型视为已结算（先到者胜，不双结算）；kind 仅落 command 列供审计。
    故断言：kind 落 command；同 message_id 跨 kind 被幂等拦截；不同 message_id 正常新结。
    """
    repo = await repo_factory()
    try:
        await _seed_battle_session(repo)
        assert await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf4",
            repository=repo,
        ) is True
        f = await repo.idem_find("sf4", "g_battle", "10001")
        assert f is not None and f.command == "settle:flee"   # kind 并入 command 字段
        # 同 message_id + group + qid 的另一种结算类型 → 幂等键命中（三元组 PK）→ 不双结算
        assert await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="zombie", message_id="sf4",
            repository=repo,
        ) is False
        f2 = await repo.idem_find("sf4", "g_battle", "10001")
        assert f2 is not None
        assert f2.command == "settle:flee"   # INSERT OR IGNORE 不覆盖已落键
        # 不同 message_id 同 kind → 新结算
        await _seed_battle_session(repo)
        assert await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf5",
            repository=repo,
        ) is True
    finally:
        await repo.close()
