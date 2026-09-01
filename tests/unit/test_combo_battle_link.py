"""M13 6c 组合技能战斗接线单测（tests/unit/test_combo_battle_link.py · M13 批15 路15C）。

覆盖：
  - 技能 combo_table 段 → F-C1 触发判定（gate_combination）
  - 命中组合行 → F-C2 结算（settle_combo 双耗）
  - 未命中 → 被拒不耗回合
  - 无组合表 → 常规技能路径

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine

_ELEMENT = {"name": "元素能量", "type": "element_energy", "base": 0,
            "max_per_pool": 3, "pools": ["fire", "water", "wind"]}


def _skill(**over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "id": "steam_blast", "name": "蒸汽爆发", "type": "active", "kind": "damage",
        "power": 100, "mp_cost": 10,
        "combo_table": [
            {"combo": ["fire", "fire", "water"], "name": "蒸汽冲击",
             "kind": "damage", "power": 200, "element": "fire", "hits": 2,
             "effects": [{"type": "damage", "power": 100}]},
        ],
    }
    s.update(over)
    return s


def _engine(**over: Any) -> BattleEngine:
    defs = dict(over.pop("defs", {}) or {})
    defs.setdefault("steam_blast", _skill())
    eng = BattleEngine(defs=defs, **over)
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def test_combo_table_skill_succeeds_with_energy() -> None:
    """组合技能 + 能量池满足 → 成功施放（组合结算双耗）。"""
    eng = _engine()
    eng._resource_registry = {"element_energy": _ELEMENT}
    eng._snap["resource_state"] = {
        "player": {"element_energy": {"fire": 3, "water": 2, "wind": 0}},
        "enemy": {},
    }
    out = eng.do_action("player", {"type": "skill", "skill_id": "steam_blast"})
    assert out.ok is True, f"组合技能应成功，got {out}"
    # 能量池扣减（fire 2 + water 1）
    rs = eng._snap["resource_state"]["player"]["element_energy"]
    assert rs["fire"] == 1 and rs["water"] == 1, f"组合扣减后应 fire1/water1，got {rs}"


def test_combo_table_insufficient_rejected() -> None:
    """组合技能 + 能量池不足 → 被拒不耗回合。"""
    eng = _engine()
    eng._resource_registry = {"element_energy": _ELEMENT}
    eng._snap["resource_state"] = {
        "player": {"element_energy": {"fire": 1, "water": 0, "wind": 0}},
        "enemy": {},
    }
    mp_before = eng.battle_state()["player"]["mp"]
    out = eng.do_action("player", {"type": "skill", "skill_id": "steam_blast"})
    assert out.ok is False, f"组合不足应被拒，got {out}"
    assert "组合未达成" in out.message
    assert eng.battle_state()["player"]["mp"] == mp_before, "被拒不应扣 MP"


def test_combo_table_no_registry_falls_back() -> None:
    """无资源注册表 → 组合门禁跳过（常规技能路径放行）。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "skill", "skill_id": "steam_blast"})
    assert out.ok is True, f"无注册表应放行常规路径，got {out}"


def test_no_combo_table_regular_skill() -> None:
    """无 combo_table 段 → 常规技能路径（不碰组合门禁）。"""
    eng = _engine(defs={"plain": {"id": "plain", "name": "普技", "type": "active",
                                   "kind": "damage", "power": 100, "mp_cost": 5}})
    out = eng.do_action("player", {"type": "skill", "skill_id": "plain"})
    assert out.ok is True, f"常规技能应成功，got {out}"
    assert eng.battle_state()["player"]["mp"] == 95
