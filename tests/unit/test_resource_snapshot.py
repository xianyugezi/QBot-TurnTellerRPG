"""6c resource_state 快照单测（tests/unit/test_resource_snapshot.py · M13 批9 路9A）。

覆盖（细化_6c §1.4 机制 M4 · RS-1~6 / D-04，对齐 TC-07）：
  A. lifecycle 快照引擎（数值型单键 + 子池型池级展开 D-04 + 降级 RS-5 + 池级原子 RS-6）
  1. 数值型单键快照导出（rage 当前值原样）
  2. 子池型池级展开快照导出（D-04：{axis: {pool: v}}）
  3. 快照深拷贝隔离（改快照/改战斗状态互不影响）
  4. round-trip 恢复：数值型 + 子池型完全一致（RS-2）
  5. 恢复惰性建段（新战斗快照无 resource_state 段 → 自动建）
  6. 快照缺轴降级：快照缺该轴 → 不写入（RS-5 精神）
  7. 已删注册轴恢复降级 → 不报错不悬空（RS-5，TC-07④）
  8. 子池型缺池补 base 防御（恢复时缺失池 → base）
  9. 池级原子性：单池增减不整段覆盖（RS-6）
  10. 快照内非数值值防御跳过（不抛异常）
  11. battle_start 型轴恢复后重置为 base（F-R1 + RS-2 合并口径）
  12. 快照全量 round-trip：battle/keep 型随快照携带（RS-3）
  B. battle 快照接线（start 骨架 + to_snapshot/from_snapshot 携带恢复）
  13. start() 建 resource_state 常态骨架
  14. to_snapshot 携带 resource_state（深拷贝自动携带）
  15. from_snapshot 恢复 resource_state（RS-2）
  16. 旧档缺 resource_state 段 → from_snapshot 降级不报错（RS-5）
  17. _settle 战斗结束按 reset 策略清零（battle 型）/保留（keep 型，RS-3）
  18. end_turn tick 后 resource_state 保留（F-R1 tick 幂等钩子）

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；不碰兄弟文件。
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping

import pytest

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.resource_lifecycle import (
    RESET_BATTLE,
    RESOURCE_STATE_KEY,
    ResourceLifecycle,
)

# ---------------------------------------------------------------------------
# fixture：注册表（数值型 rage + 子池型 element_energy + keep/battle_start 型）
# ---------------------------------------------------------------------------

REGISTRY: Dict[str, Dict[str, Any]] = {
    "rage": {
        "name": "怒气", "type": "resource", "icon": "💢",
        "base": 0, "max": 100, "reset": "battle", "display": "status_line",
    },
    "element_energy": {
        "name": "元素能量", "type": "resource_custom",  # D-01b 兼容别名
        "base": 0, "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
        "display": "status_line",
    },
    "heat": {
        "name": "热量", "type": "resource", "base": 0, "max": 100,
        "reset": "keep", "display": "status_line",
    },
    "focus": {
        "name": "专注", "type": "resource", "base": 5, "max": 100,
        "reset": "battle_start", "display": "status_line",
    },
}


@pytest.fixture()
def lc() -> ResourceLifecycle:
    """生命周期引擎（注入注册表）。"""
    return ResourceLifecycle(REGISTRY)


@pytest.fixture()
def battle_state() -> Dict[str, Any]:
    """战斗快照骨架（per-side 容器）。"""
    return {"status": "active", "turn": 1, "player": {"hp": 500}, "enemy": {"hp": 500}}


def _side(bs: MutableMapping[str, Any], side: str = "player") -> MutableMapping[str, Any]:
    return bs[RESOURCE_STATE_KEY][side]


def _filled(lc: ResourceLifecycle, bs: MutableMapping[str, Any]) -> None:
    """战斗开始初始化 + 写入典型中间态（rage 72 / element_energy 2-1-0）。"""
    lc.battle_start_init(bs, "player")
    _side(bs)["rage"] = 72
    _side(bs)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    _side(bs)["heat"] = 30
    _side(bs)["focus"] = 8


# ---------------------------------------------------------------------------
# A. lifecycle 快照引擎（RS-1~6 / D-04）
# ---------------------------------------------------------------------------


def test_snapshot_numeric_single_key(lc: ResourceLifecycle, battle_state: Dict[str, Any]) -> None:
    """数值型单键快照导出：rage 当前值原样（TC-07①）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    assert snap["player"]["rage"] == 72
    assert isinstance(snap["player"]["rage"], int)


def test_snapshot_pool_level_expansion_d04(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """子池型池级展开快照导出（D-04）：{element_energy: {fire:2, water:1, wind:0}}。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    assert snap["player"]["element_energy"] == {"fire": 2, "water": 1, "wind": 0}


def test_snapshot_deep_copy_isolation(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """快照深拷贝隔离：改快照 / 改战斗状态互不影响（RS-1 落盘不串改）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    snap["player"]["rage"] = 999
    snap["player"]["element_energy"]["fire"] = 999  # 子池内层也隔离
    assert _side(battle_state)["rage"] == 72
    assert _side(battle_state)["element_energy"]["fire"] == 2


def test_snapshot_restore_roundtrip(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """round-trip 恢复：数值型 + 子池型完全一致（RS-2，TC-07②）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["rage"] == 72
    assert _side(bs2)["element_energy"] == {"fire": 2, "water": 1, "wind": 0}
    assert _side(bs2)["heat"] == 30
    assert _side(bs2)["focus"] == 5  # battle_start 型恢复后置 base


def test_restore_lazy_builds_section(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """恢复惰性建段：新战斗快照无 resource_state 段 → 自动建（不抛异常）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}}
    assert RESOURCE_STATE_KEY not in bs2
    lc.restore_resource_state(bs2, snap)
    assert RESOURCE_STATE_KEY in bs2
    assert _side(bs2)["rage"] == 72


def test_restore_missing_axis_in_snapshot_skipped(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """快照缺轴降级：快照内无该轴 → 不写入（RS-5 精神，不悬空）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    del snap["player"]["rage"]
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert "rage" not in _side(bs2)  # 缺轴不写入
    assert _side(bs2)["element_energy"] == {"fire": 2, "water": 1, "wind": 0}


def test_restore_deleted_axis_degrades(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """已删注册轴恢复 → 字段缺失降级（RS-5，TC-07④）：不报错不悬空。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    lc2 = ResourceLifecycle({"rage": REGISTRY["rage"]})  # 旧注册删掉 element_energy
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc2.restore_resource_state(bs2, snap)  # 不抛异常
    assert _side(bs2)["rage"] == 72
    assert "element_energy" not in _side(bs2)  # 降级：不写入


def test_restore_pool_missing_pool_fills_base(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """子池型恢复缺池 → 补 base 防御（快照缺池不整段丢弃）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    snap["player"]["element_energy"] = {"fire": 1}  # 旧档缺 water/wind
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["element_energy"] == {"fire": 1, "water": 0, "wind": 0}


def test_pool_atomicity_rs6(lc: ResourceLifecycle, battle_state: Dict[str, Any]) -> None:
    """池级原子性（RS-6）：单池增减不整段覆盖。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    lc.apply_gain(battle_state, "player", {"fire": 1})
    assert _side(battle_state)["element_energy"] == {"fire": 3, "water": 1, "wind": 0}
    # 快照恢复同样以池为原子粒度：单池值恢复不丢其他池
    snap = lc.snapshot_resource_state(battle_state)
    snap["player"]["element_energy"]["water"] = 5
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["element_energy"] == {"fire": 3, "water": 5, "wind": 0}


def test_snapshot_non_numeric_value_defensive(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """快照内非数值值防御跳过：恢复不抛异常（畸形档降级）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    snap["player"]["rage"] = "abc"  # 畸形值
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)  # 不抛异常
    assert "rage" not in _side(bs2)  # 非数值 → 不写入
    assert _side(bs2)["element_energy"] == {"fire": 2, "water": 1, "wind": 0}


def test_restore_battle_start_resets_to_base(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """恢复后 battle_start 型轴重置为 base（F-R1 + RS-2 合并口径）。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["focus"] == 5  # 重置为 base（battle_start 型）


def test_snapshot_keep_axis_carried_rs3(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """keep 型跨战斗保留（RS-3）：快照携带 + 恢复原样。"""
    _filled(lc, battle_state)
    snap = lc.snapshot_resource_state(battle_state)
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["heat"] == 30  # keep 型随快照携带
    # 战斗结束 battle 策略：keep 型不清零
    lc.battle_end_reset(battle_state, RESET_BATTLE)
    assert _side(battle_state)["heat"] == 30
    assert _side(battle_state)["rage"] == 0


def test_snapshot_no_section_empty_skeleton(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """无 resource_state 段 → 快照导出返回 per-side 空骨架（结构稳定）。"""
    snap = lc.snapshot_resource_state(battle_state)
    assert snap == {"player": {}, "enemy": {}}


# ---------------------------------------------------------------------------
# B. battle 快照接线（start 骨架 + to_snapshot/from_snapshot 携带恢复）
# ---------------------------------------------------------------------------


def _battle_engine() -> BattleEngine:
    eng = BattleEngine()
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def _write_resource_state(eng: BattleEngine) -> None:
    """直接写引擎内 resource_state（绕过装配层，测快照携带/恢复接线）。"""
    eng._snap[RESOURCE_STATE_KEY] = {
        "player": {"rage": 72, "element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {"rage": 5, "element_energy": {"fire": 1, "water": 0, "wind": 0}},
    }


def test_battle_start_builds_resource_state_skeleton() -> None:
    """start() 建 resource_state 常态骨架（per-side dict）。"""
    eng = _battle_engine()
    rs = eng.battle_state()[RESOURCE_STATE_KEY]
    assert rs == {"player": {}, "enemy": {}}


def test_battle_to_snapshot_carries_resource_state() -> None:
    """to_snapshot 携带 resource_state（深拷贝自动携带，RS-1 同批落快照）。"""
    eng = _battle_engine()
    _write_resource_state(eng)
    snap = eng.to_snapshot()
    assert snap[RESOURCE_STATE_KEY]["player"]["rage"] == 72
    assert snap[RESOURCE_STATE_KEY]["player"]["element_energy"] == {
        "fire": 2, "water": 1, "wind": 0,
    }
    # 快照与引擎状态隔离（深拷贝）
    snap[RESOURCE_STATE_KEY]["player"]["rage"] = 999
    assert eng.battle_state()[RESOURCE_STATE_KEY]["player"]["rage"] == 72


def test_battle_from_snapshot_restores_resource_state() -> None:
    """from_snapshot 恢复 resource_state（RS-2：续战从该值起算）。"""
    eng = _battle_engine()
    _write_resource_state(eng)
    eng._resource_registry = REGISTRY
    snap = eng.to_snapshot()
    eng2 = BattleEngine().from_snapshot(snap, resource_registry=REGISTRY)
    rs2 = eng2.battle_state()[RESOURCE_STATE_KEY]
    assert rs2["player"]["rage"] == 72
    assert rs2["player"]["element_energy"] == {"fire": 2, "water": 1, "wind": 0}
    assert rs2["enemy"]["rage"] == 5


def test_battle_from_snapshot_legacy_missing_section_degrades() -> None:
    """旧档缺 resource_state 段 → from_snapshot 降级不报错（RS-5）。"""
    eng = _battle_engine()
    snap = eng.to_snapshot()
    snap.pop(RESOURCE_STATE_KEY, None)  # 模拟旧档无该段
    eng2 = BattleEngine().from_snapshot(snap, resource_registry=REGISTRY)
    rs2 = eng2.battle_state().get(RESOURCE_STATE_KEY, {})
    assert rs2.get("player", {}) == {}  # 缺段 → 不写入，不悬空
    assert eng2.battle_state()["turn"] == snap["turn"]  # 续战其余状态不受影响


def test_battle_from_snapshot_old_axes_degrade_rs5() -> None:
    """旧档含已删注册轴 → 恢复降级不报错（RS-5，TC-07④ battle 级）。"""
    eng = _battle_engine()
    _write_resource_state(eng)
    snap = eng.to_snapshot()
    snap[RESOURCE_STATE_KEY]["player"]["element_energy"]["wind"] = 99  # 旧配置遗留池
    eng2 = BattleEngine().from_snapshot(
        snap, resource_registry={"rage": REGISTRY["rage"]},
    )
    rs2 = eng2.battle_state()[RESOURCE_STATE_KEY]
    assert rs2["player"]["rage"] == 72
    assert "element_energy" not in rs2["player"]  # 已删轴 → 不写入


def test_battle_settle_resets_battle_axis_keeps_keep_axis() -> None:
    """_settle 战斗结束：battle 型清零 / keep 型保留（RS-3，F-R1 终段）。"""
    eng = _battle_engine()
    eng._resource_registry = REGISTRY
    eng._snap[RESOURCE_STATE_KEY] = {
        "player": {"rage": 72, "heat": 30, "focus": 8,
                   "element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {"rage": 5},
    }
    eng._snap["enemy"]["hp"] = 0  # 杀敌触发战斗结束
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    rs = eng.battle_state()[RESOURCE_STATE_KEY]
    assert eng.battle_state()["status"] == "win"
    assert rs["player"]["rage"] == 0           # battle → 清零
    assert rs["player"]["element_energy"] == {"fire": 0, "water": 0, "wind": 0}
    assert rs["player"]["heat"] == 30          # keep → 保留
    assert rs["player"]["focus"] == 8          # battle_start → 战斗内保留


def test_battle_end_turn_tick_preserves_resource_state() -> None:
    """end_turn tick 后 resource_state 保留（F-R1 tick 幂等钩子，零增减）。"""
    eng = _battle_engine()
    _write_resource_state(eng)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    rs = eng.battle_state()[RESOURCE_STATE_KEY]
    assert rs["player"]["rage"] == 72
    assert rs["player"]["element_energy"] == {"fire": 2, "water": 1, "wind": 0}


def test_battle_no_registry_degrades_gracefully() -> None:
    """未注入资源注册表 → 接线零操作降级不报错（RS-5 精神）。"""
    eng = _battle_engine()  # _resource_registry = None
    _write_resource_state(eng)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()  # tick 降级
    eng2 = BattleEngine().from_snapshot(eng.to_snapshot())  # 恢复降级（无注册表）
    assert eng2.battle_state()[RESOURCE_STATE_KEY]["player"]["rage"] == 72
    # 战斗结束 _settle 降级：直接杀敌
    eng2._snap["enemy"]["hp"] = 0
    eng2.do_action("player", {"type": "normal"})
    eng2.enemy_act()
    eng2.end_turn()
    assert eng2.battle_state()["status"] == "win"
    # 无注册表 → battle 型轴未知，保留原值（降级不清零）
    assert eng2.battle_state()[RESOURCE_STATE_KEY]["player"]["rage"] == 72
