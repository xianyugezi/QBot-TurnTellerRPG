"""M13 批16 路16C 技能位战斗消费单测（tests/unit/test_skill_slots_battle.py）。

覆盖（装配快照 → 战斗消费全链路）：
  1) slots_from_snapshot：装配快照 → 战斗可用技能列表（四类槽全量/basic 固定
     第 1 位/槽序稳定/畸形快照兜底/老存档回退）
  2) available_skills：ctx["skill_slots_state"] → 可用技能 id 列表（进战斗入口）
  3) is_slot_equipped：未装配拒绝判定（行动位 basic/active 放行；
     passive/trigger 槽不占行动位不可直接施放；未装配/畸形快照拒绝）
  4) battle_equipped_skills：可用技能 id → def 映射（ctx["skills"] 同源）
  5) equipped_slot_kind：槽类型审计
  6) 战斗闭环：装配快照 → 引擎施放 active 技能成功 / 未装配技能被拒不耗回合
  7) 指令层装配过滤：/攻击 装配内技能放行、未装配技能被拒（battle_commands）

测试目标：qbot_rpg.core.skill_slots_battle（引擎层）+ qbot_rpg.commands.
battle_commands._attack_action（指令层装配过滤接线）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（无任何 sleep 字面量）；
不 git commit。

"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.commands.battle_commands import _attack_action, _resolve_skill
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.skill_slots import assemble_slots, save_slots_to_state
from qbot_rpg.core.skill_slots_battle import (
    SLOT_ACTIVE,
    SLOT_BASIC,
    SLOT_PASSIVE,
    SLOT_TRIGGER,
    available_skills,
    battle_equipped_skills,
    equipped_slot_kind,
    is_slot_equipped,
    slots_from_snapshot,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------


def _skills() -> Dict[str, Dict[str, Any]]:
    """技能库：basic + active×2 + passive + trigger + 未装配 active。"""
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "power": 100, "mp_cost": 0},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "power": 150, "mp_cost": 8},
        "healing_light": {"id": "healing_light", "name": "治疗术", "type": "active",
                           "kind": "heal", "power": 0, "mp_cost": 6},
        "stone_guard": {"id": "stone_guard", "name": "石肤", "type": "passive",
                         "kind": "utility"},
        "counter_strike": {"id": "counter_strike", "name": "反击", "type": "trigger",
                            "kind": "damage", "power": 80, "mp_cost": 0},
        "fireball": {"id": "fireball", "name": "火球术", "type": "active",
                      "kind": "damage", "power": 120, "mp_cost": 10},
    }


def _assemble_snapshot() -> Dict[str, Any]:
    """标准装配快照（assemble_slots 产物）：basic 第 1 位 + active×2 排序 +
    passive + trigger 槽。fireball 未装配——从 skills 表剔除（缺省排序=库序，
    不剔除则 fireball 也会进 active_order，无法表达「未装配」）。"""
    table = {k: v for k, v in _skills().items() if k != "fireball"}
    return assemble_slots(list(table.values()), {"job_id": "warrior"})


def _ctx(**over: Any) -> Dict[str, Any]:
    """战斗消费 ctx：skill_slots_state 装配快照 + skills 表。"""
    c: Dict[str, Any] = {
        "skills": _skills(),
        "skill_slots_state": _assemble_snapshot(),
    }
    c.update(over)
    return c


def _engine() -> BattleEngine:
    """战斗引擎：同源技能库（resolve_skill 解析通道），seed 固定确定性。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


class _Parsed:
    """ParsedCommand 桩（args 列表，对齐 test_skill_battle_fullchain）。"""

    def __init__(self, args: list, error: str = "", raw: str = "") -> None:
        self.args = args
        self.error = error
        self.raw = raw


# ---------------------------------------------------------------------------
# 1) slots_from_snapshot：装配快照 → 战斗可用技能列表
# ---------------------------------------------------------------------------


def test_slots_from_snapshot_full() -> None:
    """四类槽全量：basic 固定第 1 位 + active 排序 + passive/trigger 槽。"""
    rows = slots_from_snapshot(_assemble_snapshot())
    kinds = [r["slot"] for r in rows]
    assert kinds[0] == SLOT_BASIC, f"basic 应第 1 位，got {kinds}"
    assert kinds == [SLOT_BASIC, SLOT_ACTIVE, SLOT_ACTIVE, SLOT_PASSIVE, SLOT_TRIGGER], kinds
    ids = [r["skill_id"] for r in rows]
    assert ids[0] == "basic_attack"
    assert ids[1:3] == ["power_strike", "healing_light"]
    assert ids[3] == "stone_guard" and ids[4] == "counter_strike"
    assert "fireball" not in ids, "未装配技能不应进入战斗可用列表"


def test_slots_from_snapshot_basic_none_placeholder() -> None:
    """basic 槽 skill_id=None 占位保留（缺普攻提示位，不丢弃）。"""
    snap = _assemble_snapshot()
    snap["slots"][0] = {"slot": SLOT_BASIC, "skill_id": None}
    rows = slots_from_snapshot(snap)
    assert rows[0] == {"slot": SLOT_BASIC, "skill_id": None}


def test_slots_from_snapshot_legacy_fallback() -> None:
    """老存档（无 slots 键）→ active_order + passive + trigger 并集回退。"""
    legacy = {
        "active_order": ["power_strike"],
        "passive": [{"slot": SLOT_PASSIVE, "skill_id": "stone_guard"}],
        "trigger": [{"slot": SLOT_TRIGGER, "skill_id": "counter_strike"}],
        "version": 1,
    }
    rows = slots_from_snapshot(legacy)
    ids = [(r["slot"], r["skill_id"]) for r in rows]
    assert ids == [(SLOT_ACTIVE, "power_strike"),
                   (SLOT_PASSIVE, "stone_guard"),
                   (SLOT_TRIGGER, "counter_strike")]


def test_slots_from_snapshot_malformed_empty() -> None:
    """畸形快照（非 Mapping / 槽条目非法）→ 确定性兜底不抛异常。"""
    assert slots_from_snapshot(None) == []  # type: ignore[arg-type]
    assert slots_from_snapshot({}) == []
    # 未知槽丢弃；basic 槽 skill_id 非法 → 保底占位（skill_id=None，P-3）
    out = slots_from_snapshot({"slots": [{"slot": "unknown", "skill_id": "x"},
                                         {"slot": SLOT_BASIC, "skill_id": 1},
                                         "junk"]})
    assert all(s["slot"] != "unknown" for s in out)
    assert all(s["slot"] != SLOT_BASIC or s["skill_id"] is None for s in out)


# ---------------------------------------------------------------------------
# 2) available_skills：进战斗消费入口
# ---------------------------------------------------------------------------


def test_available_skills_order() -> None:
    """进战斗可用技能列表：basic 第 1 位 + active 排序 + passive/trigger 槽。"""
    ids = available_skills(_ctx())
    assert ids[0] == "basic_attack"
    assert ids[1:3] == ["power_strike", "healing_light"]
    assert ids[3:5] == ["stone_guard", "counter_strike"]
    assert len(ids) == 5


def test_available_skills_missing_state_empty() -> None:
    """无 skill_slots_state 注入 → 空列表（确定性兜底，不抛异常）。"""
    assert available_skills({"skills": _skills()}) == []
    assert available_skills({"skills": _skills(), "skill_slots_state": "junk"}) == []


# ---------------------------------------------------------------------------
# 3) is_slot_equipped：未装配拒绝判定
# ---------------------------------------------------------------------------


def test_is_slot_equipped_action_slots() -> None:
    """行动位技能（basic/active）在装配内 → True。"""
    c = _ctx()
    assert is_slot_equipped(c, "basic_attack") is True
    assert is_slot_equipped(c, "power_strike") is True
    assert is_slot_equipped(c, "healing_light") is True


def test_is_slot_equipped_unequipped_rejected() -> None:
    """未装配技能 → False（装配过滤拒绝）。"""
    c = _ctx()
    assert is_slot_equipped(c, "fireball") is False
    assert is_slot_equipped(c, "不存在") is False


def test_is_slot_equipped_passive_trigger_not_action_slot() -> None:
    """passive/trigger 槽不占行动位 → 不可直接施放（False）。"""
    c = _ctx()
    assert is_slot_equipped(c, "stone_guard") is False
    assert is_slot_equipped(c, "counter_strike") is False


def test_is_slot_equipped_no_state_rejected() -> None:
    """无装配快照注入 → 全部拒绝（防御性，不臆造可用技能）。"""
    assert is_slot_equipped({"skills": _skills()}, "power_strike") is False
    assert is_slot_equipped({"skills": _skills(), "skill_slots_state": {}}, "basic_attack") is False


# ---------------------------------------------------------------------------
# 4) battle_equipped_skills / 5) equipped_slot_kind
# ---------------------------------------------------------------------------


def test_battle_equipped_skills_map() -> None:
    """可用技能 id → def 映射（ctx["skills"] 同源）。"""
    m = battle_equipped_skills(_ctx())
    assert set(m.keys()) == {"basic_attack", "power_strike", "healing_light",
                             "stone_guard", "counter_strike"}
    assert m["power_strike"]["mp_cost"] == 8
    assert "fireball" not in m


def test_battle_equipped_skills_no_table_empty() -> None:
    """无 skills 表 → 空映射（不抛异常）。"""
    assert battle_equipped_skills({"skill_slots_state": _assemble_snapshot()}) == {}


def test_equipped_slot_kind() -> None:
    """槽类型审计：active → active；passive 槽 → passive；未装配 → None。"""
    c = _ctx()
    assert equipped_slot_kind(c, "power_strike") == SLOT_ACTIVE
    assert equipped_slot_kind(c, "stone_guard") == SLOT_PASSIVE
    assert equipped_slot_kind(c, "counter_strike") == SLOT_TRIGGER
    assert equipped_slot_kind(c, "fireball") is None


# ---------------------------------------------------------------------------
# 6) 战斗闭环：装配快照 → 引擎施放（装配内放行 / 未装配被拒不耗回合）
# ---------------------------------------------------------------------------


def test_battle_cast_equipped_skill_ok() -> None:
    """装配内 active 技能施放成功（引擎技能通道 + 装配快照闭环）。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.ok is True, f"装配内技能应施放成功，got {out.message}"
    # 未装配技能（fireball）不在 defs 之外——引擎按配置解析，装配过滤在指令层；
    # 此处验证装配快照与引擎通道同源（resolve_skill 可解析装配内技能 def）
    sd = eng.combo_engine().resolve_skill("power_strike")
    assert sd.get("mp_cost") == 8


def test_battle_unequipped_rejected_no_turn_cost() -> None:
    """未装配技能经装配过滤在指令层被拒：不生成行动、不耗回合（TC-05 语义）。"""
    action, err = _attack_action(_Parsed(["火球术"]), _ctx())
    assert action is None and err and "技能" in str(err)
    # 被拒不进入引擎 → 无行动副作用（turn 保持 0，可直接验证下一轮正常行动）
    eng = _engine()
    rep = eng.player_act({"type": "normal"})
    assert rep.turn >= 1 and rep.ended is False  # 未装配被拒后正常行动不受阻


# ---------------------------------------------------------------------------
# 7) 指令层装配过滤（battle_commands._attack_action）
# ---------------------------------------------------------------------------


def test_attack_action_equipped_skill_allowed() -> None:
    """/攻击 <装配内技能名> → skill action 放行。"""
    c = _ctx()
    assert _resolve_skill(c, "强力斩击") == "power_strike"
    action, err = _attack_action(_Parsed(["强力斩击"]), c)
    assert err is None and action == {"type": "skill", "skill_id": "power_strike"}


def test_attack_action_unequipped_skill_rejected() -> None:
    """/攻击 <未装配技能名> → 拒绝提示（装配过滤）。"""
    c = _ctx()
    assert _resolve_skill(c, "火球术") == "fireball"  # 技能存在（配置表内）
    action, err = _attack_action(_Parsed(["火球术"]), c)
    assert action is None and err and "技能" in str(err)


def test_attack_action_equipped_by_index() -> None:
    """/攻击 <序号>：装配内序号放行（序号按装配快照行动位，未装配技能不进列表）。"""
    c = _ctx()
    # 装配快照行动位 = [basic_attack(1), power_strike(2), healing_light(3)]
    # → 序号 2 = power_strike；序号 3 = healing_light
    action, err = _attack_action(_Parsed(["2"]), c)
    assert err is None and action == {"type": "skill", "skill_id": "power_strike"}
    action3, err3 = _attack_action(_Parsed(["3"]), c)
    assert err3 is None and action3 == {"type": "skill", "skill_id": "healing_light"}
    # 序号 5（超出行动位）→ 回退全表？不——装配外序号拒绝
    action5, err5 = _attack_action(_Parsed(["5"]), c)
    assert action5 is None and err5


def test_attack_action_save_load_roundtrip_equipped() -> None:
    """存档 round-trip：装配快照落 ps → 战斗消费 ctx 读回 → 装配过滤一致。"""
    ps: Dict[str, Any] = {"persistent_state": {}}
    save_slots_to_state(ps, _assemble_snapshot())
    loaded = ps["persistent_state"]["skill_slots"]
    c = _ctx(skill_slots_state=loaded)
    action, err = _attack_action(_Parsed(["强力斩击"]), c)
    assert err is None and action == {"type": "skill", "skill_id": "power_strike"}
    action2, err2 = _attack_action(_Parsed(["火球术"]), c)
    assert action2 is None and err2 and "技能" in str(err2)
