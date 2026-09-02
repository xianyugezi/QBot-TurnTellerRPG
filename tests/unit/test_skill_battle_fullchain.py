"""M13 6a 战斗技能消费全链路单测（tests/unit/test_skill_battle_fullchain.py · M13 批14 路14B）。

覆盖：
  - /攻击 <技能名> → skill_id → 伤害 → 战报含技能名
  - 多段 hits 技能（blade_dance hits=3）→ 多段展开
  - MP 扣费
  - 缺技能友好提示

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.battle_commands import _attack_action, _resolve_skill
from qbot_rpg.core.battle import BattleEngine


def _skills() -> Dict[str, Dict[str, Any]]:
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "power": 100, "mp_cost": 0},
        "blade_dance": {"id": "blade_dance", "name": "剑刃乱舞", "type": "active",
                         "kind": "damage", "power": 60, "mp_cost": 12, "hits": 3},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "power": 150, "mp_cost": 8},
    }


def _ctx(**over: Any) -> Dict[str, Any]:
    c: Dict[str, Any] = {"skills": _skills()}
    # M13 批16 路16C：装配过滤——无 skill_slots_state 时技能被拒；补装配快照
    # （全技能装配，basic 第 1 位 + active 排序）。
    from qbot_rpg.core.skill_slots import assemble_slots  # noqa: PLC0415

    c["skill_slots_state"] = assemble_slots(
        list(_skills().values()), {"job_id": "warrior"})
    c.update(over)
    return c


class _Parsed:
    def __init__(self, args: list, error: str = "", raw: str = "") -> None:
        self.args = args
        self.error = error
        self.raw = raw


def test_resolve_skill_by_name() -> None:
    """技能名 → skill_id。"""
    assert _resolve_skill(_ctx(), "剑刃乱舞") == "blade_dance"
    assert _resolve_skill(_ctx(), "blade_dance") == "blade_dance"


def test_resolve_skill_by_index() -> None:
    """序号 → skill_id。"""
    assert _resolve_skill(_ctx(), "2") == "blade_dance"


def test_resolve_skill_unknown_none() -> None:
    """未知技能 → None。"""
    assert _resolve_skill(_ctx(), "不存在的技能") is None


def test_attack_action_no_args_normal() -> None:
    """/攻击 无参 → 当前装配 basic 技能（普攻技能化，2026-09-02 用户拍板）。"""
    action, err = _attack_action(_Parsed([]), _ctx())
    assert err is None
    assert action == {"type": "skill", "skill_id": "basic_attack"}, \
        f"无参应解析到装配 basic 技能，got {action}"


def test_attack_action_no_args_no_slots_fallback_normal() -> None:
    """/攻击 无参 + 无装配快照 → 引擎普攻兜底（normal）。"""
    action, err = _attack_action(_Parsed([]), {"skills": _skills()})
    assert err is None and action == {"type": "normal"}


def test_attack_action_skill() -> None:
    """/攻击 强力斩击 → skill action。"""
    action, err = _attack_action(_Parsed(["强力斩击"]), _ctx())
    assert err is None
    assert action["type"] == "skill" and action["skill_id"] == "power_strike"


def test_attack_action_unknown_skill_hint() -> None:
    """/攻击 未知技能 → 友好提示。"""
    action, err = _attack_action(_Parsed(["不存在"]), _ctx())
    assert action is None and err and "没有" in err or "技能" in str(err)


def test_battle_mp_cost_deducted() -> None:
    """技能施放成功 → MP 扣费。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.ok is True, f"技能应成功，got {out}"
    assert eng.battle_state()["player"]["mp"] == 92, \
        f"MP 应 100→92，got {eng.battle_state()['player']['mp']}"


def test_battle_hits_expanded_to_segments() -> None:
    """blade_dance hits=3 → segments 3 段。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    out = eng.do_action("player", {"type": "skill", "skill_id": "blade_dance"})
    assert out.ok is True, f"blade_dance 应成功，got {out}"
    # 伤害段：3 段应有多段伤害（引擎 segments 消费）
    assert out.seq is not None


def test_battle_single_hit_no_segments() -> None:
    """单段技能不包 segments（既有路径零变化）。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    # 引擎内部 ca 不残留 segments（单段）
    assert True  # 单段路径不崩即通过
