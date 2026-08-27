"""故障注入脚本①：回复前崩溃 → 不双结算（M6 批5·路A · D5 §二 crash 脚本）——TC-FLT-04~06。

依据：
  - docs/细化/细化_M6_故障注入.md（D5）§二（FLT-06~10 / TC-FLT-04~06）：
      FLT-06（注入点 = mock 发送出口抛异常，发送出口仅是崩溃注入点、非幂等键载体，
        总纲 ADR-05 / 批5B P1-4）
      FLT-07（断言对象 = 业务已提交（players 行已变）+ 幂等键已落（idempotency_keys 含
        该 (message_id, group_id, qid) 三元组行）——消费 D2 IDEM-4/5、4a TC-06）
      FLT-08（同键重发幂等返回：业务零执行/零发送，不双结算不双扣）
      FLT-09（settle_exit_idempotent 实装前置：同 (qid, kind, message_id) 二次结算 → False）
      FLT-10（恢复路径：finally 还原发送回调 → 同 message_id 重发验证幂等 → 清理测试库）
  - docs/细化/细化_M6_幂等事务三件套.md（D2）IDEM-4/5/8（幂等键载体/命中幂等返回/
    settle_exit_idempotent 实装语义——批2 已实装，本脚本消费不重定义）
  - 细化_4a_存储层契约.md TC-06 L384（回复前崩溃不双结算）/ F4 L276（命中幂等返回）
  - 定稿《开发规则文档.md》L319（回复前崩溃 → 不双结算，断言对象 = 键已落）

覆盖（复用批2 process_message / settle_exit_idempotent 真实实现，不 mock 引擎）：
  TC-FLT-04 发送出口抛异常 → 业务已提交 + 键已落 + 发送异常被捕获
  TC-FLT-05 同 message_id 重发 → 幂等返回（业务零执行、零发送、不双结算不双扣）
  TC-FLT-06 settle_exit_idempotent 同 (qid, kind, message_id) 二次结算 → False 不双结算

【工程补白】注入隔离（D5 §一 1.2/FLT-04）：发送出口 = process_message 注入的 sender 回调
（测试构造），非生产模块全局 patch；每用例独立文件库（WAL，crash_env）互不串扰。
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Awaitable, Callable, Dict, List, Optional

import pytest

from qbot_rpg.commands.processing import PerPlayerQueue, process_message
from qbot_rpg.commands.sender import SenderSendError
from qbot_rpg.storage.repository import Repository, SessionRow, row_to_player
from qbot_rpg.world.battle_boundary import settle_exit_idempotent

from conftest import make_player

import pytest
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository


@pytest.fixture
async def crash_env(tmp_path):
    """crash 脚本环境：文件库（WAL，tmp_path）——与批2 test_idem_processing 同型。

    process_message 的入口只读查重（idem_claim）与队列消费者写事务会并发，:memory:
    共享缓存库为表级锁（写事务污染表 → 读侧 SQLITE_LOCKED 不重试）；文件库 WAL 下
    读者永不阻塞 = 生产等价（细化_5d §3.2 允许 :memory: 或 tmp_path）。
    """
    db = Database(str(tmp_path / "crash.db"))
    repo = Repository(db, pending_dir=str(tmp_path))
    # 收口修复（M6 批5 主 agent）：先建玩家 10001（make_player 默认 gold=350）——
    # ① make_bump_handler 事务内读玩家需存在（否则 row_to_player(None) 抛错）
    # ② sessions 外键引用 players（_seed_battle_session 需先有玩家记录）
    await repo.save_player(make_player("10001"))
    yield repo
    await repo.close()


# ---------------------------------------------------------------------------
# 业务/观测闭包（与批2 test_idem_processing 同构：真实 handler 走 repo.tx()）
# ---------------------------------------------------------------------------
async def _gold(repo: Repository, qid: str) -> int:
    """players.currencies.gold（断言业务已提交/不双结算）。"""
    row = await repo.db.fetchone_read(
        "SELECT currencies FROM players WHERE player_qid = ?", (qid,))
    if row is None:
        return 0
    return int(json.loads(row["currencies"]).get("gold", 0))


def make_bump_handler(
    qid: str,
    amount: int = 100,
    *,
    record: Optional[List[str]] = None,
) -> Callable[[Any], Awaitable[Dict[str, Any]]]:
    """业务闭包：事务内读玩家 → 金币 +amount → 写回（模拟扣发/购买）。

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
        return {"ok": True, "message": f"金币 +{amount}"}

    return handler


async def _send_counter() -> tuple:
    """正常发送出口：记录已发送结果 + 完成事件（P2-7 修复：事件同步替代 sleep 等发送出口）。"""
    sent: List[Dict[str, Any]] = []
    done = asyncio.Event()

    async def sender(result: Dict[str, Any]) -> None:
        sent.append(result)
        done.set()

    return sent, sender, done


# ---------------------------------------------------------------------------
# settle_exit_idempotent 辅助（与批2 test_idem_processing 同构）
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


# ---------------------------------------------------------------------------
# TC-FLT-04/05：发送出口崩溃 → 业务已提交 + 键已落 + 同键重发幂等
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flt_04_crash_sender_business_committed_and_key_written(crash_env):
    """TC-FLT-04 发送出口抛异常 → 业务已提交 + 键已落（D5 FLT-06/07 / 4a TC-06）。

    三要素注释：
      注入点 = process_message 的 sender 回调抛 SenderSendError（mock 发送出口抛异常，
        模拟回复前崩溃；发送出口仅是崩溃注入点、非幂等键载体，总纲 ADR-05 / FLT-06）；
      断言对象 = ① players 行已变（业务已提交：gold 350+100=450）② idempotency_keys 含
        (m1, g1, 10001) 三元组行（键已落，D2 IDEM-4 / 4a TC-06）③ process_message 返回
        ok=True（发送异常被捕获，不阻断队列）；
      恢复路径 = finally 还原发送回调（正常 sender）→ 以同 message_id 重发 → 断言幂等返回
        （业务零执行、gold 不变 450）→ 关闭队列与 repo（FLT-10 / 5d L205-208）。
    """
    repo = crash_env  # fixture 直接返回 Repository（收口修正：无 .repo 属性）
    queue = PerPlayerQueue(repo)
    try:
        crash_done = asyncio.Event()

        async def crash_sender(result: Dict[str, Any]) -> None:
            crash_done.set()
            raise SenderSendError("发送出口崩溃（回复前崩溃注入，FLT-06）")

        res1 = await process_message(
            repo, queue,
            message_id="m1", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100), sender=crash_sender,
        )
        await asyncio.wait_for(crash_done.wait(), timeout=5.0)  # 等发送出口（异常被捕获）
        assert res1["ok"] is True                    # ③ 发送异常被捕获，不阻断（FLT-07）
        assert await _gold(repo, "10001") == 450     # ① 业务已提交（350+100，FLT-07）
        found = await repo.idem_find("m1", "g1", "10001")
        assert found is not None                     # ② 幂等键已落（FLT-07 / D2 IDEM-4）
        assert found.command == "/签到"
    finally:
        # 恢复路径（FLT-10）：还原发送回调 → 同 message_id 重发 → 幂等返回 → 清理
        # （幂等重发 send=False 不调 sender——等待 sended 会超时，收口修正）
        calls: List[str] = []
        sent, sender, _ = await _send_counter()
        res2 = await process_message(
            repo, queue,
            message_id="m1", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100, record=calls), sender=sender,
        )
        assert res2["idempotent"] is True            # 重发幂等返回（FLT-08）
        assert calls == []                           # 业务零执行（IDEM-5）
        assert sent == []                            # 零发送（幂等重放 send=False）
        assert await _gold(repo, "10001") == 450     # 不双结算不双扣
        await queue.close()


@pytest.mark.asyncio
async def test_flt_05_resend_same_message_id_idempotent(crash_env):
    """TC-FLT-05 同 message_id 重发幂等返回：不双结算不双扣（D5 FLT-08 / 4a F4 L276/TC-08）。

    三要素注释：
      注入点 = 同 TC-FLT-04：先以 crash sender（抛 SenderSendError）处理一次（键已落），
        随后**恢复发送出口**（正常 sender）——「同 message_id 重发」即故障后重试路径；
      断言对象 = 重发返回 idempotent=True（ok=False，未入队即幂等返回）、业务零执行
        （record 为空）、零发送（sent 为空）、gold 仍 450（不双结算不双扣）；
      恢复路径 = finally 关闭队列与 repo（FLT-10）。
    """
    repo = crash_env  # fixture 直接返回 Repository（收口修正：无 .repo 属性）
    queue = PerPlayerQueue(repo)
    try:
        # 前置：发送出口崩溃一次（TC-FLT-04 状态：键已落）
        async def crash_sender(result: Dict[str, Any]) -> None:
            raise SenderSendError("发送出口崩溃（前置落键，FLT-06）")

        res1 = await process_message(
            repo, queue,
            message_id="m2", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100), sender=crash_sender,
        )
        assert res1["ok"] is True
        assert await repo.idem_find("m2", "g1", "10001") is not None  # 键已落（前置）
        assert await _gold(repo, "10001") == 450

        # 恢复发送出口 → 同 message_id 重发 → 幂等返回（FLT-08）
        calls: List[str] = []
        sent, sender, _ = await _send_counter()
        res2 = await process_message(
            repo, queue,
            message_id="m2", group_id="g1", player_qid="10001", command="/签到",
            handler=make_bump_handler("10001", 100, record=calls), sender=sender,
        )
        assert res2["idempotent"] is True            # 幂等返回（入口查重命中，未入队）
        assert res2["ok"] is False
        assert res2["queued"] is False               # 未入队直接幂等返回（IDEM-5）
        assert calls == []                           # 业务零执行
        assert sent == []                            # 零发送（幂等重放不发送）
        assert await _gold(repo, "10001") == 450     # 不双结算不双扣（FLT-08）
    finally:
        await queue.close()


# ---------------------------------------------------------------------------
# TC-FLT-06：settle_exit_idempotent 同键二次结算 → False（D2 IDEM-8 已实装）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_flt_06_settle_exit_idempotent_no_double(crash_env):
    """TC-FLT-06 settle_exit 幂等不双结算（D5 FLT-09 / D2 IDEM-8 / battle_boundary L782-801）。

    三要素注释：
      注入点 = settle_exit_idempotent 实装函数真实调用（D2 IDEM-8 批2 已实装，无 mock）；
      断言对象 = 首次结算返回 True + 战斗会话已删（连段/资源随会话清零，退出战场回地图）
        + 幂等键已落（command 含 settle:flee，IDEM-8）；再次以同 (qid, kind, message_id)
        调 settle_exit_idempotent → 返回 False（不双结算：资源不重复返还/连段不重复清零）；
      恢复路径 = finally 关闭 repo（FLT-10）。
    """
    repo = crash_env  # fixture 直接返回 Repository（收口修正：无 .repo 属性）
    try:
        await _seed_battle_session(repo)
        ok1 = await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf1",
            repository=repo,
        )
        assert ok1 is True                                       # 首次结算成功
        assert await repo.load_session("10001") is None          # 会话已删（连段清零）
        found = await repo.idem_find("sf1", "g_battle", "10001")
        assert found is not None and found.command == "settle:flee"  # kind 并入 command
        # 同 (qid, kind, message_id) 二次结算 → False（FLT-09 / IDEM-8）
        ok2 = await settle_exit_idempotent(
            session=_fake_session(), settlement_kind="flee", message_id="sf1",
            repository=repo,
        )
        assert ok2 is False                                      # 不双结算
        assert await repo.load_session("10001") is None          # 会话不重复删/重建
    finally:
        await repo.close()
