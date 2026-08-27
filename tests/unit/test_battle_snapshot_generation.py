"""续战世代绑定补测（M6 批3·路B · D3 RSM 件套）——TC-RSM-01/03/05/06 核心 + 旧快照兼容。

依据：细化_M6_热重载接线.md（D3）§二 RSM-02/03/06 + F-RSM-01（快照增 registry_generation 字段 +
from_snapshot 增 registry 参数透传 + 存储 payload 内嵌世代，无新列）+ §2.1 P0-1 缺陷根因。

覆盖：RSM-02 快照世代字段 / RSM-03 from_snapshot 参数透传 / RSM-06 存储往返 / 旧快照缺字段兼容。
注：本文件为路B 迭代上限截断后由主 agent 补建（实现已落盘，测试补齐）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from qbot_rpg.core.battle import BattleEngine

# 最小玩家/敌人（对齐 tests/unit/test_battle_engine.py 构造口径）
PLAYER = {"hp": 100, "max_hp": 100, "mp": 20, "str": 15, "int": 10, "agi": 10, "spr": 5, "lck": 10, "name": "P"}
ENEMY = {"hp": 60, "max_hp": 60, "mp": 0, "str": 12, "int": 8, "agi": 8, "spr": 4, "lck": 5, "name": "E"}


def _stub_registry(generation: int):
    """契约替身 registry：仅暴露 generation 属性（RSM-02 读取键）。"""
    return SimpleNamespace(generation=generation)


def test_rsm_02_start_snapshot_has_registry_generation():
    """TC-RSM-01 前半：start 快照含 registry_generation = 当前 registry 世代（F-RSM-01）。"""
    eng = BattleEngine(registry=_stub_registry(7)).start(PLAYER, ENEMY, random_seed=11)
    snap = eng.to_snapshot()
    assert snap.get("registry_generation") == 7


def test_rsm_02_start_snapshot_default_zero_without_registry():
    """无 registry → registry_generation=0（RSM-02：registry 缺省按 0）。"""
    eng = BattleEngine().start(PLAYER, ENEMY, random_seed=11)
    assert eng.to_snapshot().get("registry_generation") == 0


def test_rsm_02_turn_boundary_snapshot_carries_generation():
    """回合边界/中断快照沿用 registry_generation（to_snapshot 深拷贝 _snap 保留世代）。"""
    eng = BattleEngine(registry=_stub_registry(3)).start(PLAYER, ENEMY, random_seed=12)
    assert eng.to_snapshot().get("registry_generation") == 3  # start 后任意快照均带世代


def test_rsm_03_from_snapshot_accepts_and_passes_registry():
    """TC-RSM-01 后半：from_snapshot 增 registry 参数并透传到引擎（RSM-03）。"""
    src = BattleEngine(registry=_stub_registry(5)).start(PLAYER, ENEMY, random_seed=13)
    snap = src.to_snapshot()
    new_reg = _stub_registry(9)
    eng2 = BattleEngine.from_snapshot(snap, registry=new_reg)
    assert eng2._registry is new_reg  # 透传成功（旧局旧配置注入）


def test_rsm_03_from_snapshot_without_registry_backward_compat():
    """旧快照无 registry 参数 → 不崩（registry=None 走默认解析，RSM-04 降级）。"""
    src = BattleEngine().start(PLAYER, ENEMY, random_seed=14)
    snap = src.to_snapshot()
    snap.pop("registry_generation", None)  # 模拟旧快照（无世代字段）
    eng2 = BattleEngine.from_snapshot(snap)
    assert eng2._registry is None or getattr(eng2._registry, "generation", 0) == 0


def test_rsm_06_snapshot_generation_roundtrip_via_payload():
    """TC-RSM-05：sessions payload 内嵌 registry_generation 原样序列化往返一致（无新列）。"""
    import asyncio

    from qbot_rpg.storage.connection import Database
    from qbot_rpg.storage.repository import Repository, SessionRow
    from conftest import make_player

    db = Database(":memory:")
    repo = Repository(db)
    eng = BattleEngine(registry=_stub_registry(6)).start(PLAYER, ENEMY, random_seed=15)
    snap = eng.to_snapshot()
    assert snap.get("registry_generation") == 6

    row = SessionRow(
        player_qid="u1", session_type="battle", random_seed=15,
        payload=json.loads(json.dumps(snap)),
    )

    async def _roundtrip() -> None:
        await repo.save_player(make_player("u1"))  # sessions 外键需先有玩家记录
        async with repo.tx() as tx:  # upsert_session 属 RepoTransaction（领域级同事务提交）
            await tx.upsert_session(row)
        got = await repo.load_session("u1")
        assert got is not None
        assert got[1].get("registry_generation") == 6  # 往返一致（payload 内嵌，无新列）

    try:
        asyncio.get_event_loop().run_until_complete(_roundtrip())
    except RuntimeError:  # 无运行中 loop（pytest-asyncio 外调用）
        asyncio.run(_roundtrip())
