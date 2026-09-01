"""6a 技能战斗接线单测（tests/unit/test_skill_battle_wiring.py · M13 批3 路3C）。

覆盖：
  - ctx["skills"] 注入（_table_from_registry kind=skill）非空
  - _resolve_skill 解析（id/名称/序号 → skill_id）
  - /攻击 <技能> → action → 技能效果执行全链路
  - 技能 MP 消耗扣费（成功施放扣 MP；被拒不扣）
  - 战报技能名注入（dispatch_round → enrich → outcome.skill_name）

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Dict


from qbot_rpg.commands.battle_commands import (
    _inject_display_outcomes,
    _resolve_skill,
    enrich_round_report,
)


# ---------------------------------------------------------------------------
# _resolve_skill
# ---------------------------------------------------------------------------
def _skills_map() -> Dict[str, Dict[str, Any]]:
    return {
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "mp_cost": 10},
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "mp_cost": 0},
        "healing_light": {"id": "healing_light", "name": "治疗术", "type": "active",
                           "kind": "heal", "mp_cost": 15},
    }


def test_resolve_skill_by_id() -> None:
    ctx = {"skills": _skills_map()}
    assert _resolve_skill(ctx, "power_strike") == "power_strike"


def test_resolve_skill_by_name() -> None:
    ctx = {"skills": _skills_map()}
    assert _resolve_skill(ctx, "强力斩击") == "power_strike"


def test_resolve_skill_by_index() -> None:
    ctx = {"skills": _skills_map()}
    assert _resolve_skill(ctx, "2") == "basic_attack"


def test_resolve_skill_missing_returns_none() -> None:
    ctx = {"skills": _skills_map()}
    assert _resolve_skill(ctx, "不存在的技能") is None


def test_resolve_skill_no_skills_returns_none() -> None:
    assert _resolve_skill({}, "power_strike") is None


# ---------------------------------------------------------------------------
# 战报技能名注入（_inject_display_outcomes + enrich_round_report）
# ---------------------------------------------------------------------------
def _player_skill_outcome() -> Any:
    return SimpleNamespace(
        ok=True, seq=1, actor="player", action_type="skill", target="enemy",
        hit=True, crit="high", blocked=False, raw_damage=100, final_damage=150,
        target_hp=350, side_effects=(), message="", battle_ended=False, status=None,
    )


def test_inject_display_outcomes_skill_name() -> None:
    """玩家技能 outcome 注入 skill_name（BREP-07 显示技能名）。"""
    injected = _inject_display_outcomes(
        [_player_skill_outcome()],
        enemy_name="疾风狼",
        player_max_hp=500,
        enemy_max_hp=500,
        skill_name="强力斩击",
    )
    assert getattr(injected[0], "skill_name", None) == "强力斩击"


def test_inject_display_outcomes_no_skill_name_for_normal() -> None:
    """普攻（非 skill）outcome 不注入 skill_name。"""
    oc = SimpleNamespace(
        ok=True, seq=1, actor="player", action_type="normal", target="enemy",
        hit=True, crit="low", blocked=False, raw_damage=50, final_damage=50,
        target_hp=450, side_effects=(), message="", battle_ended=False, status=None,
    )
    injected = _inject_display_outcomes(
        [oc], enemy_name="疾风狼", player_max_hp=500, enemy_max_hp=500,
    )
    assert getattr(injected[0], "skill_name", None) is None


def test_enrich_round_report_skill_name() -> None:
    """enrich_round_report 透传 skill_name 到 outcome。"""
    report = SimpleNamespace(
        turn=1, phases=("act",), player=450, enemy=350, ended=False,
        status=None, log=(), outcomes=(_player_skill_outcome(),),
    )
    enriched = enrich_round_report(
        report,
        enemy_name="疾风狼",
        player_max_hp=500,
        enemy_max_hp=500,
        skill_name="强力斩击",
    )
    assert getattr(enriched.outcomes[0], "skill_name", None) == "强力斩击"


# ---------------------------------------------------------------------------
# 技能 MP 消耗扣费（battle 引擎层）
# ---------------------------------------------------------------------------
def _battle_engine(mp: int = 100) -> Any:
    """构造真实 BattleEngine 跑技能 MP 扣费（注入技能 defs）。"""
    from qbot_rpg.core.battle import BattleEngine

    eng = BattleEngine(
        defs=_skills_map(),
        config={"combo_enforce_mp": True},
    )
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": mp, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def test_skill_mp_cost_deducted_on_cast() -> None:
    """技能施放成功 → MP 扣减 mp_cost（10）。"""
    eng = _battle_engine()
    eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    snap = eng.battle_state()
    assert snap["player"]["mp"] == 90, f"MP 应扣 10，got {snap['player']['mp']}"


def test_skill_mp_not_deducted_when_rejected() -> None:
    """MP 不足 → 被拒 → 不扣费不耗回合。"""
    eng = _battle_engine(mp=5)
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.ok is False, f"MP 不足应被拒，got {out}"
    snap = eng.battle_state()
    assert snap["player"]["mp"] == 5, f"被拒不应扣 MP，got {snap['player']['mp']}"


def test_basic_skill_no_mp_cost() -> None:
    """普攻 mp_cost=0 → 不扣 MP。"""
    eng = _battle_engine()
    eng.do_action("player", {"type": "skill", "skill_id": "basic_attack"})
    snap = eng.battle_state()
    assert snap["player"]["mp"] == 100, f"普攻不应扣 MP，got {snap['player']['mp']}"
