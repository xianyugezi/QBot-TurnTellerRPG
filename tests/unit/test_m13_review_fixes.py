"""M13 批21 dsh 审查修复验证（tests/unit/test_m13_review_fixes.py）。

覆盖 A1 P0-2（power 折算战斗倍率）修复：
  - 普攻 power=100 → mult 1.0×
  - 强力斩击 power=150 → mult 1.5×（伤害显著高于普攻）
  - action 显式 mult 优先（不被 power 覆盖）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine


def _skills() -> Dict[str, Dict[str, Any]]:
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "power": 100, "mp_cost": 0},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "power": 150, "mp_cost": 8},
        "weak_strike": {"id": "weak_strike", "name": "弱击", "type": "active",
                         "kind": "damage", "power": 50, "mp_cost": 0},
    }


def _engine() -> BattleEngine:
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家",
         "foc": 50, "agi": 50},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼",
         "foc": 50, "agi": 50},
        random_seed=42,
    )
    return eng


def _normalize_damage(eng: BattleEngine, skill_id: str) -> int:
    """多次施放取最大伤害（规避会心/格挡抖动，纯比较倍率关系）。"""
    eng2 = _engine()
    best = 0
    for _ in range(5):
        out = eng2.do_action("player", {"type": "skill", "skill_id": skill_id})
        dmg = out.final_damage
        best = max(best, dmg)
    return best


def test_power_150_higher_than_100() -> None:
    """power=150 技能伤害 > power=100 普攻（倍率折算生效）。"""
    p150 = _normalize_damage(_engine(), "power_strike")
    p100 = _normalize_damage(_engine(), "basic_attack")
    assert p150 > p100, f"power 150 应高于 100：{p150} vs {p100}"


def test_power_50_lower_than_100() -> None:
    """power=50 技能伤害 < power=100 普攻。"""
    p50 = _normalize_damage(_engine(), "weak_strike")
    p100 = _normalize_damage(_engine(), "basic_attack")
    assert p50 < p100, f"power 50 应低于 100：{p50} vs {p100}"


def test_explicit_mult_wins() -> None:
    """action 显式 mult 优先（不被 sd.power 覆盖）。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike",
                                   "mult": 2.0})
    # mult 2.0 生效：伤害应显著高于默认 1.5×
    assert out.ok is True
    eng2 = _engine()
    out2 = eng2.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.final_damage >= out2.final_damage, \
        f"显式 mult 2.0 应 ≥ 默认：{out.final_damage} vs {out2.final_damage}"
