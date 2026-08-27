"""故障注入脚本⑥：掉线重连 → 玩家数据完好（M6 批5·路C · tests/fault/fault_inject_netdrop.py）。

依据：
  - docs/细化/细化_M6_故障注入.md（D5）§七（FLT-30~34 + TC-FLT-17/18 + ADR-D5-02 可测边界收敛）
  - docs/细化/细化_4a_存储层契约.md（IDEM-3 L290 会话 version 幂等防陈旧 / TC-12 存档 round-trip）
  - docs/细化/细化_M6_幂等事务三件套.md（D2）§九 SES-08（会话 version 随 payload 读写，断线
    重连脚本断言 FLT-32 消费）
  - 开发规则文档.md §4.5 L324（掉线重连）
  - docs/细化/细化_3a（引擎零网络铁律，见 D5 §〇 术语表「掉线重连可测边界」）

故障点 = 【规则】L324 掉线重连。引擎零网络（细化_3a 铁律）→ 断线/重连无生产抽象 →
可测边界**收敛到 storage load/save 边界**（ADR-D5-02）：模拟断线 = 写路径一次性失败（OSError）
+ 读路径挂起（hang）；重连 = 还原边界 mock 后重读。

断言粒度收敛（FLT-34 / 批5A P1-4 修复建议）：该类可测边界显式声明 = 数据完好 + 会话 version
不变；禁「静默恢复或广播『我回来了』」模糊断言偷渡（【规则】L326 禁「不崩就行」）。

工程决策（对齐批5·路C 任务书）：
  - 注入点 = storage load/save 边界 mock OSError/挂起（**不造网络层抽象**——引擎零网络）。
  - 断言 = 重连后 load_player 与断线前**逐字段一致**（round-trip，TC-12 / 1g3 快照 schema）+
    会话 payload 与断线前一致（FLT-31）+ sessions.version 断线前后一致（FLT-32 / IDEM-3）。
  - 挂起期间不写脏数据；恢复后事务重放完成、服务不崩（FLT-33）。
  - 每用例三要素注释（注入点/断言对象/恢复路径）+ ≥1 断言 + finally 恢复；独立 :memory:。

注入隔离（FLT-04 / 细化_5d L205-208）：monkeypatch 仅作用于**测试实例 repo**（storage 边界），
禁黑入生产模块全局 patch；每用例独立 fixture 起独立 :memory: 库互不串扰；零 NoneBot、纯 asyncio。
"""

from __future__ import annotations

import asyncio

import pytest

from qbot_rpg.data import EquipmentSlot, ItemInstance, Player, PlayerAttributes
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import (
    Repository,
    SessionRow,
    player_to_row,
    row_to_player,
)


def make_player(qid, *, name="阿伟", coins=350, gems=8) -> Player:
    """玩家主档（对齐 tests/conftest.py make_player 子集：全字段 round-trip 基线）。"""
    return Player(
        qid=qid, name=name, job_id="warrior", level=35, exp=1200, hp=220, mp=60,
        currencies={"gold": coins, "gem": gems},
        inventory=(
            ItemInstance("potion", "药水", 5, "normal", False),
            ItemInstance("iron_sword", "铁剑", 1, "rare", True),
        ),
        equipment={"weapon": EquipmentSlot("iron_sword", "铁剑", 3, True, ("ruby",))},
        attributes=PlayerAttributes(
            base={"hp": 100.0, "mp": 50.0, "str": 15.0, "lck": 10.0},
            bonus={"flat": {"str": 5.0}, "pct": {"hp": 10.0}},
            temp={"pct": {"atk": 20.0}, "flat": {"atk": 3.0}},
            cond={"str": 2.0},
        ),
        achievement_state=("ach_first_blood",),
        title_state={"current": "斩龙者"},
        persistent_state={"checkin_count": 3},
        longline_counters={"battle_wins": 12},
        reputation_state={"commercial": 2},
        codex_state={"monster": {"slime": {"unlocked": True}}},
        content_pack_id="legal",
        content_pack_version="1.0.0",
        schema_version=4,
        last_seen_group="10001",
        created_at="2026-08-01T00:00:00Z",
        last_active_at="2026-08-18T12:00:00Z",
    )


@pytest.fixture
async def repo():
    """独立 :memory: 库（FLT-04 注入隔离：每用例独立库互不串扰）。"""
    db = Database(":memory:")
    r = Repository(db)
    yield r
    await r.close()


async def _seed_battle_session(repo, qid, *, payload, version=1) -> None:
    """落一条战斗会话（sessions 表，payload + version，对齐 1g3 快照 schema / 4a IDEM-3）。"""
    async with repo.tx() as tx:
        await tx.upsert_session(SessionRow(
            player_qid=qid, session_type="battle", payload=payload, random_seed=7,
            version=version,
        ))


async def _codec_player(repo, qid) -> dict:
    """读库真相（绕过 60s 缓存）→ player_to_row 归一化 dict（round-trip 逐字段一致基线）。

    存什么读什么完全一致（4a TC-12）：序列化（player_to_row）→ 反序列化（row_to_player）→
    再归一化比对，作为「断线前后逐字段一致」的权威基线。
    """
    row = await repo.db.fetchone_read("SELECT * FROM players WHERE player_qid=?", (qid,))
    if row is None:
        raise AssertionError(f"玩家 {qid} 不在库中")
    return player_to_row(row_to_player(row))


# ---------------------------------------------------------------------------
# TC-FLT-17：断线重连数据逐字段一致（FLT-30/31）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_flt_17_reconnect_data_field_identical(repo, monkeypatch):
    """TC-FLT-17 断线重连数据逐字段一致（FLT-30/31 / 4a TC-12 round-trip）。

    注入点=mock **测试实例 repo** 的 storage load/save 边界（FLT-04 禁黑入生产模块）：
    repo.save_player 抛 OSError（模拟断线=写路径一次性失败）+ repo.load_player 挂起
    （模拟断线=读路径挂起）；断言对象=重连（finally 还原 mock）后 load_player 与断线前
    逐字段一致（player_to_row 归一化比对，round-trip）+ 会话 payload 与断线前一致，断线期
    写失败/读挂起被识别且未落脏数据；恢复路径=finally 还原边界 mock + 清理独立 :memory: 库。
    """
    await repo.save_player(make_player("u1", name="阿伟", coins=350))
    await _seed_battle_session(repo, "u1", payload={"turn": 3, "hp": 120}, version=1)
    before = await _codec_player(repo, "u1")            # 断线前快照（数据完好基线）
    sess_before = await repo.load_session("u1")
    assert sess_before is not None
    assert sess_before[1] == {"turn": 3, "hp": 120}     # 会话 payload 前置基线

    async def _oserror_save(player):                    # 写边界：断线一次性失败（OSError）
        raise OSError("disk/network drop: save failed")

    async def _hang_load(qid):                          # 读边界：断线挂起（hang）
        await asyncio.sleep(3600)
        return None

    try:
        monkeypatch.setattr(repo, "save_player", _oserror_save)   # 注入：仅作用于测试实例
        monkeypatch.setattr(repo, "load_player", _hang_load)      # 注入：仅作用于测试实例
        # 断线期：写路径一次性失败 + 读路径挂起（都被识别，服务不崩）
        with pytest.raises(OSError):
            await repo.save_player(make_player("u1", name="改坏数据", coins=999))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(repo.load_player("u1"), timeout=0.05)  # 读挂起被超时识别
    finally:
        # 恢复路径①：还原 storage 边界 mock（= 重连）
        monkeypatch.undo()
        # 恢复路径②：重连断言（数据完好）——关库前完成
        try:
            p = await repo.load_player("u1")            # 重连后走 public API
            assert p is not None
            assert player_to_row(p) == before           # 逐字段一致（round-trip，FLT-31）
            sess_after = await repo.load_session("u1")
            assert sess_after is not None
            assert sess_after[1] == sess_before[1]      # 会话 payload 与断线前一致（FLT-31）
            assert sess_after[3] == sess_before[3]      # 会话 version 与断线前一致（FLT-32）
        finally:
            await repo.close()                          # 恢复路径：清理独立 :memory: 库


# ---------------------------------------------------------------------------
# TC-FLT-18：会话 version 未变 + 挂起恢复（FLT-32/33）
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tc_flt_18_session_version_unchanged_and_hang_recovery(repo, monkeypatch):
    """TC-FLT-18 会话 version 未变 + 挂起恢复（FLT-32/33 / 4a IDEM-3）。

    注入点=mock **测试实例 repo** 的 storage 写边界 repo.save_player 挂起（模拟断线=写路径
    挂起，asyncio.sleep 常挂）；断言对象=挂起期间 sessions.version 与断线前一致（IDEM-3 防
    陈旧指令双扣，未递增/未重置）+ 挂起期间不写脏数据（players 行 = 断线前）+ 恢复（还原 mock）
    后事务重放完成、服务不崩、version 仍不变；恢复路径=finally 还原写边界 mock + 重放真实
    save_player + 清理独立 :memory: 库。
    """
    await repo.save_player(make_player("u1", name="阿伟", coins=350))
    await _seed_battle_session(repo, "u1", payload={"turn": 1, "hp": 100}, version=3)
    before_row = await _codec_player(repo, "u1")
    sess_before = await repo.load_session("u1")
    assert sess_before is not None and sess_before[3] == 3   # 断线前 version=3

    async def _hang_save(player):                           # 写边界：断线挂起（hang）
        await asyncio.sleep(3600)
        return None

    task = None
    try:
        monkeypatch.setattr(repo, "save_player", _hang_save)  # 注入：仅作用于测试实例
        task = asyncio.create_task(
            repo.save_player(make_player("u1", name="重放后名字", coins=999)))
        await asyncio.sleep(0.05)                           # 让挂起写进入
        assert not task.done()                              # 写仍在挂起（断线未恢复）
        task.cancel()                                       # 挂起被取消（超时兜底，服务不崩）
        with pytest.raises(asyncio.CancelledError):
            await task
        # 挂起期间不写脏数据（FLT-33）：库内玩家行 = 断线前
        assert await _codec_player(repo, "u1") == before_row
        assert (await repo.load_session("u1"))[3] == 3      # version 未变（FLT-32）
    finally:
        monkeypatch.undo()                                  # 恢复路径①：还原写边界 mock（= 重连）
        # 恢复路径②：恢复后事务重放完成（FLT-33）——关库前完成
        try:
            await repo.save_player(make_player("u1", name="重放后名字", coins=999))
            p = await repo.load_player("u1")
            assert p is not None and p.name == "重放后名字"  # 重放完成、服务不崩
            assert p.currencies["gold"] == 999
            sess_after = await repo.load_session("u1")
            assert sess_after is not None
            assert sess_after[3] == 3                       # version 断线前后一致（FLT-32）
            assert sess_after[1] == sess_before[1]          # 会话 payload 未变
        finally:
            await repo.close()                              # 恢复路径：清理独立 :memory: 库
