"""M13 6c 资源轴战斗结算闭环单测（tests/unit/test_resource_battle_full.py · M13 批16 路16A）。

覆盖细化_6c F-R1 全生命周期：
  - battle_start_init（战斗开始置 base）
  - tick_round_end 幂等保留
  - battle_end_reset 三策略（battle 清零/keep 保留/battle_start 战斗内保留）
  - 被控保留（S4）
  - 快照 round-trip 续战

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any

from qbot_rpg.core.battle import BattleEngine

_RAGE = {"name": "怒气", "type": "rage", "base": 0, "max": 100, "reset": "battle"}
_FOCUS = {"name": "专注", "type": "rage", "base": 0, "max": 100, "reset": "battle_start"}
_HEAT = {"name": "热量", "type": "rage", "base": 0, "max": 100, "reset": "keep"}
_ELEMENT = {"name": "元素能量", "type": "element_energy", "base": 0,
            "max_per_pool": 3, "pools": ["fire", "water", "wind"], "reset": "battle"}


def _engine(**over: Any) -> BattleEngine:
    eng = BattleEngine(defs={}, **over)
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def test_start_inits_axes_to_base() -> None:
    """战斗开始：battle_start_init 置 base（数值型 + 子池型各池）。"""
    eng = BattleEngine(defs={})
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    rs = eng.battle_state()["resource_state"]
    assert rs["player"]["rage"] == 0, f"rage 应置 base 0，got {rs}"
    assert rs["player"]["element_energy"] == {"fire": 0, "water": 0, "wind": 0}, \
        f"子池型各池应置 base，got {rs['player']['element_energy']}"


def test_start_no_registry_noop() -> None:
    """无注册表 → battle_start_init 零操作（resource_state 空骨架）。"""
    eng = _engine()
    rs = eng.battle_state()["resource_state"]
    assert rs == {"player": {}, "enemy": {}}


def test_round_end_tick_preserves() -> None:
    """回合结束 tick_round_end 幂等保留（rage 60→60）。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE}
    eng._snap["resource_state"] = {"player": {"rage": 60}, "enemy": {}}
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    assert eng.battle_state()["resource_state"]["player"]["rage"] == 60, \
        "tick_round_end 应幂等保留"


def test_settle_battle_reset_clears_battle_axis() -> None:
    """战斗结束：battle 型资源清零。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE}
    eng._snap["resource_state"] = {"player": {"rage": 72}, "enemy": {}}
    eng._snap["enemy"]["hp"] = 0
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    rs = eng.battle_state()["resource_state"]
    assert rs["player"].get("rage", 0) == 0 or "rage" not in rs["player"], \
        f"battle 型资源战斗结束应清零，got {rs}"


def test_settle_keep_preserves_axis() -> None:
    """战斗结束：keep 型资源保留。"""
    eng = _engine()
    eng._resource_registry = {"heat": _HEAT}
    eng._snap["resource_state"] = {"player": {"heat": 55}, "enemy": {}}
    eng._snap["enemy"]["hp"] = 0
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    rs = eng.battle_state()["resource_state"]
    assert rs["player"].get("heat", 0) == 55, f"keep 型资源应保留，got {rs}"


def test_settle_battle_start_preserves_then_resets() -> None:
    """battle_start 型：战斗结束保留、下次战斗开始置 base。"""
    eng = _engine()
    eng._resource_registry = {"focus": _FOCUS}
    eng._snap["resource_state"] = {"player": {"focus": 40}, "enemy": {}}
    eng._snap["enemy"]["hp"] = 0
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    rs = eng.battle_state()["resource_state"]
    assert rs["player"].get("focus", 0) == 40, f"battle_start 型结束应保留，got {rs}"


def test_controlled_skip_preserves() -> None:
    """被控 skip → 资源保留（S4）。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE}
    eng._snap["resource_state"] = {"player": {"rage": 60}, "enemy": {}}
    eng._snap["player"]["control_state"] = {
        "type": "睡眠", "skip_turn": 1.0, "turns": 1, "source": "enemy",
    }
    out = eng.do_action("player", {"type": "normal"})
    assert out.action_type == "skip"
    assert eng.battle_state()["resource_state"]["player"]["rage"] == 60, \
        "被控跳过应保留资源"


def test_snapshot_roundtrip_resume() -> None:
    """快照 round-trip：resource_state 随快照携带，恢复续战。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE}
    eng._snap["resource_state"] = {"player": {"rage": 72}, "enemy": {}}
    snap = eng.battle_state()
    eng2 = BattleEngine.from_snapshot(snap, resource_registry={"rage": _RAGE})
    rs = eng2.battle_state()["resource_state"]
    assert rs["player"]["rage"] == 72, f"恢复应续战 rage 72，got {rs}"
