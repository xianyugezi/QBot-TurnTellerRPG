"""批40 · H5 玩家级随机流可推进（rng_state 持久化 + 逐指令推进）单测。

依据：`docs/深度打造_决策记录.md` §一 H5；`打造系统_C` §二 Q6/R1（E2：按 qid 定种 +
每指令 make_context 重建同 seed → 同玩家同指令走出同一条随机序列）。机制照
`core/battle.py:5316,5409-5424` 既有实现（`rng_state` 快照 + 恢复推进）。

覆盖：
  · 连续两次同类操作（/采集 概率结算）→ 随机结果**不同**（多种子；非 flaky）；
  · 存档重载后随机流**可续**（不回到初始序列；与注入初种的重放对拍）；
  · 注入点兼容：`rng_factory` 在无落档状态时**身份不变**（既有测试注入路径可用）；
  · 落档 → JSON → 恢复往返（内层 tuple/list 归一，同 battle 死区修复口径）；
  · runner `_plain_handler` 逐指令推进落档；非 Random/不可写 no-op；
  · **战斗 AI 防回归对拍**：battle 引擎快照 rng_state 续流逐值一致（多种子），
    玩家级随机流持久化不触碰引擎 rng（battle.py 本批零改动）。

纪律：零 NoneBot；不写真实内容包（采集点用内存节点）；多玩家库用内存 Repository。
"""
from __future__ import annotations

import json
import random
from dataclasses import replace
from types import SimpleNamespace

import pytest

from conftest import make_player  # type: ignore[import-not-found]
from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.assembly.runner import _make_handler
from qbot_rpg.commands.router import CommandSpec
from qbot_rpg.core.gathering import gather
from qbot_rpg.core.rng_state import (
    RNG_STATE_KEY,
    normalize_rng_state,
    persist_player_rng,
    player_rng,
    restore_rng_state,
    snapshot_rng_state,
)
from qbot_rpg.data.player import Player
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.repository import Repository

# CTB 战斗引擎（防回归对拍用；不注入任何玩家级 rng）
from qbot_rpg.core.battle import BattleEngine

SEEDS = [1, 7, 42, 2026, 99991]

# 内存采集节点（非真实内容包）：单点 rate=0.5 → rng 概率判定
_GATHER_NODE = {
    "id": "m1",
    "name": "测试图",
    "gather_points": [
        {"id": "p1", "item": "herb", "name": "草药", "rate": 0.5, "respawn_minutes": 10},
    ],
}

_PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
           "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50,
           "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
_ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
          "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
          "lck": 10, "elem_atk": 0, "name": "E"}


def _deps(repo: Repository, seed: int) -> AssemblyDeps:
    """装配依赖：repo + 确定性 rng 工厂（既有注入点）。"""
    return AssemblyDeps(
        repo=repo, game_world=None, registry=None, settings={},
        rng_factory=lambda qid: random.Random(seed),
    )


async def _new_repo(qid: str = "10001", ps: dict | None = None) -> Repository:
    repo = Repository(Database(":memory:"))
    await repo.save_player(Player(qid=qid, name="随机流", persistent_state=ps or {}))
    return repo


# ---------------------------------------------------------------------------
# 纯函数口径
# ---------------------------------------------------------------------------
def test_snapshot_restore_json_roundtrip_continues():
    """快照 → JSON 往返（内层 tuple/list）→ 恢复 → 后续序列与原流一致。"""
    rng = random.Random(20260826)
    for _ in range(5):
        rng.random()
    snap = snapshot_rng_state(rng)
    assert isinstance(snap, list) and snap
    wire = json.loads(json.dumps(snap, ensure_ascii=False))  # 存档级往返
    resumed = random.Random()
    assert restore_rng_state(resumed, wire) is True
    assert [rng.random() for _ in range(8)] == [resumed.random() for _ in range(8)]
    # 归一函数把内层 list 转回 tuple（setstate 契约）
    norm = normalize_rng_state(wire)
    assert isinstance(norm, tuple) and isinstance(norm[1], tuple)


def test_player_rng_and_persist_helpers():
    ps: dict = {}
    fb = random.Random(42)
    assert player_rng(ps, fb) is fb              # 无落档 → 注入对象身份不变
    assert persist_player_rng(ps, fb) is True
    state = ps[RNG_STATE_KEY]
    assert isinstance(state, list) and state
    fb.random()
    persist_player_rng(ps, fb)                   # 推进后再落档
    resumed = player_rng(ps, random.Random(1))
    assert resumed is not fb and [fb.random() for _ in range(4)] == [
        resumed.random() for _ in range(4)]
    # 非法入参 no-op
    assert persist_player_rng(None, fb) is False
    assert persist_player_rng({}, "not-rng") is False
    assert restore_rng_state(random.Random(), None) is False


@pytest.mark.parametrize("seed", SEEDS)
async def test_reload_continues_stream(seed: int):
    """存档重载后随机流可续：第二次取值 = 同初种序列的**第二个**值（非重放第一个）。"""
    repo = await _new_repo()
    try:
        deps = _deps(repo, seed)
        ev = {"user_id": "10001"}
        c1 = await make_context(ev, deps)
        v1 = c1["rng"].random()
        persist_player_rng(c1["player"].persistent_state, c1["rng"])
        await repo.save_player(c1["player"])

        c2 = await make_context(ev, deps)
        v2 = c2["rng"].random()

        ref = random.Random(seed)
        assert v1 == ref.random()
        assert v2 == ref.random()                # 续流（非重放）
        assert v2 != v1
    finally:
        await repo.close()


@pytest.mark.parametrize("seed", SEEDS)
async def test_two_consecutive_gathers_use_advancing_stream(seed: int):
    """同玩家连续两次 /采集 概率结算：走推进后的流，与注入初种的手动重放对拍一致。"""
    repo = await _new_repo()
    try:
        deps = _deps(repo, seed)
        ev = {"user_id": "10001"}
        c1 = await make_context(ev, deps)
        r1 = gather(_GATHER_NODE, "m1", rng=c1["rng"], now=1000)
        persist_player_rng(c1["player"].persistent_state, c1["rng"])
        await repo.save_player(c1["player"])

        c2 = await make_context(ev, deps)
        r2 = gather(_GATHER_NODE, "m1", rng=c2["rng"], now=2000)

        # 对拍：同一 seed 初种、同一 rng 对象连续两次结算 → 结果与两次指令逐字段一致
        ref = random.Random(seed)
        ref1 = gather(_GATHER_NODE, "m1", rng=ref, now=1000)
        ref2 = gather(_GATHER_NODE, "m1", rng=ref, now=2000)
        assert r1["produced"] == ref1["produced"] and r1["missed"] == ref1["missed"]
        assert r2["produced"] == ref2["produced"] and r2["missed"] == ref2["missed"]
        # 连续两次的随机判定不同（推进证据；确定性故非 flaky）
        assert c1["rng"].random() != c2["rng"].random()
    finally:
        await repo.close()


async def test_injected_rng_factory_identity_when_no_state():
    """注入点兼容：玩家无落档 rng_state 时，ctx["rng"] 即注入工厂返回对象（身份不变）。"""
    repo = await _new_repo()
    try:
        fixed = random.Random(7)
        deps = AssemblyDeps(repo=repo, game_world=None, registry=None, settings={},
                            rng_factory=lambda qid: fixed)
        ctx = await make_context({"user_id": "10001"}, deps)
        assert ctx["rng"] is fixed
    finally:
        await repo.close()


async def test_no_state_two_contexts_same_first_value():
    """无落档（未推进）时行为与修复前一致：两次 make_context 首值同（不写档不推进）。"""
    repo = await _new_repo()
    try:
        deps = _deps(repo, 42)
        ev = {"user_id": "10001"}
        c1 = await make_context(ev, deps)
        v1 = c1["rng"].random()
        c2 = await make_context(ev, deps)   # 未 persist → 仍无状态
        assert c2["rng"].random() == v1
    finally:
        await repo.close()


# ---------------------------------------------------------------------------
# runner 逐指令推进落档
# ---------------------------------------------------------------------------
class _FakeTx:
    def __init__(self) -> None:
        self.saved = None

    async def upsert_player(self, player: object) -> None:
        self.saved = player


async def test_runner_persists_rng_state_per_command():
    """runner `_plain_handler`：指令消费 rng 后落档前写回 rng_state（逐指令推进）。"""
    p = replace(make_player(), persistent_state={})
    rng = random.Random(123)
    ctx = {"player": p, "rng": rng}

    def _handler(parsed, ctx=None):  # noqa: ANN001
        ctx["rng"].random()          # 模拟指令内随机消费
        return "ok"

    spec = CommandSpec("测试rng", handler=_handler)
    handler = _make_handler(spec, SimpleNamespace(name="测试rng"), ctx)
    tx = _FakeTx()
    await handler(tx)
    assert tx.saved is p
    assert isinstance(p.persistent_state.get(RNG_STATE_KEY), list)

    # 第二条指令：从落档状态恢复后继续推进 → 状态 = 同序列两次消费后的状态
    ctx2 = {"player": p, "rng": player_rng(p.persistent_state, random.Random(999))}
    handler2 = _make_handler(spec, SimpleNamespace(name="测试rng"), ctx2)
    await handler2(tx)
    ref = random.Random(123)
    ref.random()
    ref.random()
    assert p.persistent_state[RNG_STATE_KEY] == snapshot_rng_state(ref)


async def test_runner_does_not_write_state_when_rng_unused():
    """消费门控：指令未消费 rng → 不写 rng_state（不给存档平白加 ~7KB 状态）。"""
    p = replace(make_player(), persistent_state={})
    rng = random.Random(5)
    ctx = {"player": p, "rng": rng, "_rng_initial_state": snapshot_rng_state(rng)}

    def _handler(parsed, ctx=None):  # noqa: ANN001
        return "ok"                  # 不消费随机

    spec = CommandSpec("测试rng2", handler=_handler)
    tx = _FakeTx()
    await _make_handler(spec, SimpleNamespace(name="测试rng2"), ctx)(tx)
    assert RNG_STATE_KEY not in p.persistent_state


# ---------------------------------------------------------------------------
# 战斗 AI 防回归（对拍：battle.py 零改动；玩家级流不触碰引擎 rng）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("seed", SEEDS)
def test_battle_rng_state_resume_parity(seed: int):
    """战斗引擎 to_snapshot/from_snapshot 的 rng_state 续流逐值一致（多 seed 对拍）。"""
    eng = BattleEngine().start(dict(_PLAYER), dict(_ENEMY), random_seed=seed)
    eng.player_act("normal")
    snap = json.loads(json.dumps(eng.to_snapshot(boundary="after_action"),
                                 ensure_ascii=False))
    assert isinstance(snap.get("rng_state"), list) and snap["rng_state"], \
        "快照须带 rng_state（续战推进依据）"
    restored = BattleEngine.from_snapshot(snap)
    assert [eng._rng.random() for _ in range(10)] == [
        restored._rng.random() for _ in range(10)]


def test_player_rng_persistence_does_not_touch_battle_engine():
    """玩家级 rng 落档/推进不改变战斗引擎 rng 状态（两条流相互独立）。"""
    eng = BattleEngine().start(dict(_PLAYER), dict(_ENEMY), random_seed=20260826)
    before = list(eng._rng.getstate())
    ps: dict = {}
    prng = random.Random(42)
    for _ in range(5):
        prng.random()
    persist_player_rng(ps, prng)
    assert list(eng._rng.getstate()) == before
    assert ps[RNG_STATE_KEY] != before       # 玩家流状态是独立快照
