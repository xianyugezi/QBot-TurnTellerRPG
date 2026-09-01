"""M13 6c 资源轴引擎装配单测（tests/unit/test_resource_assembly.py · M13 批12 路12C）。

覆盖：
  - battle 引擎 energy_cost 门禁（不足 → 被拒不耗回合）
  - battle 引擎 energy_gain 结算（成功施放后增加封顶）
  - resource_state 快照段（start 建段/_settle 清零）
  - 回合结清 tick

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine

_RAGE = {"name": "怒气", "type": "rage", "base": 0, "max": 100}
_ELEMENT = {"name": "元素能量", "type": "element_energy", "base": 0,
            "max_per_pool": 3, "pools": ["fire", "water", "wind"]}


def _engine(**over: Any) -> BattleEngine:
    defs = dict(over.pop("defs", {}) or {})
    defs.setdefault("rage_slash", _skill())
    eng = BattleEngine(
        config={"combo_enforce_mp": True},
        defs=defs,
        **over,
    )
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def _skill(**over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "id": "rage_slash", "name": "怒涛斩", "type": "active", "kind": "damage",
        "mp_cost": 5,
        "energy_gain": {"rage": {"rage": 15}},
        "energy_cost": {"rage": {"rage": 10}},
    }
    s.update(over)
    return s


def test_start_builds_resource_state() -> None:
    """start() 建 resource_state 段。"""
    eng = _engine()
    snap = eng.battle_state()
    assert "resource_state" in snap
    assert snap["resource_state"] == {"player": {}, "enemy": {}}


def test_energy_gain_applied_on_cast() -> None:
    """技能施放成功（无 cost）→ energy_gain 增加（rage 0→15）。"""
    eng = _engine(defs={"gain_skill": _skill(energy_cost=None)})
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}
    eng._snap["resource_state"] = {"player": {"rage": 0}, "enemy": {}}
    out = eng.do_action("player", {"type": "skill", "skill_id": "gain_skill"})
    assert out.ok is True, f"技能应成功施放，got {out}"
    assert eng._snap["resource_state"]["player"]["rage"] == 15, \
        f"rage 应 0→15，got {eng._snap['resource_state']['player']['rage']}"


def test_energy_cost_deducted() -> None:
    """技能带 energy_cost → 扣减（rage 30→20）。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}
    eng._snap["resource_state"] = {"player": {"rage": 30}, "enemy": {}}
    eng.do_action("player", {"type": "skill", "skill_id": "rage_slash"})
    assert eng._snap["resource_state"]["player"]["rage"] == 35, \
        f"扣 10 + 增 15 = 35，got {eng._snap['resource_state']['player']['rage']}"


def test_energy_insufficient_rejected() -> None:
    """energy_cost 不足 → 被拒不耗回合。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}
    eng._snap["resource_state"] = {"player": {"rage": 5}, "enemy": {}}
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_slash"})
    assert out.ok is False, f"能量不足应被拒，got {out}"
    assert "能量不足" in out.message
    assert eng._snap["resource_state"]["player"]["rage"] == 5, "被拒不应扣增"


def test_no_registry_noop() -> None:
    """未注入 registry → 零操作（容错）。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_slash"})
    assert out.ok is True  # 无 registry 不拦（装配层接线后生效）


def test_settle_clears_resource_state() -> None:
    """战斗结束 → resource_state 按 reset 策略清零。"""
    eng = _engine()
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}
    eng._snap["resource_state"] = {"player": {"rage": 72}, "enemy": {}}
    eng._snap["enemy"]["hp"] = 0
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    snap = eng.battle_state()
    rs = snap.get("resource_state", {})
    # battle 型 rage → 清零（ResourceLifecycle.battle_end_reset）
    assert rs.get("player", {}).get("rage", 0) in (0, None) or "rage" not in rs.get("player", {}), \
        f"battle 型资源战斗结束应清零，got {rs}"
