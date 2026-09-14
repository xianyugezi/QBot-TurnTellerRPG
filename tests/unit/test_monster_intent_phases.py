"""M2 怪物意图预告 + 阶段系统（B3 路）单元测试：固化 /tmp/smoke_m2_b3.py 的全部断言。

依据：细化_1f_怪物AI状态机.md §③（意图分级 L1/L2/L3：charge/stance 类别三值、进度、
name_revealed / chain_preview / reveal_condition；phases 阶段表：100-60/60-30/30-0 边界、
enter_action / broadcast 占位替换、detect_transition、phase_changed 联动事件、TC-12 中断
恢复播报）＋ docs/m2_shared_contract.md §五（intent 契约字段）。

原 /tmp/smoke_m2_b3.py 已全绿（ALL PASS），此处按 pytest 惯例固化：断言逻辑原样保留
不改语义（铁律：临时脚本删除 ≠ 丢弃用例）。分组：
  build_intent 三级分级（charge 未解锁 level=1 / 解锁 level=3 + 文案 / 类别三值 /
  蓄力起始进度 / preview.category 显式声明）
  reveal_satisfied 多形态（字符串表达式 / lore:N / 直接键 / 缺省 / dict / list AND）
  resolve_phase 三阶段边界（100-60/60-30/30-0 + hp/max_hp 换算 + 夹取）
  PhaseTable 配置解析（降序排序 / actions_for / enter_action_for / broadcast_for /
  走配置表 resolve_phase）
  phase_changed 联动事件（1→2 事件 / 同阶段 None / 模块级 / detect_transition 命中与未切换）
  resume_broadcast 中断恢复播报（TC-12：段高亮 + 缺省 action_lib 回退 id + 无在途链空串）

确定性：纯规则/纯字符串函数，无随机依赖（铁律 8）。
"""
from __future__ import annotations

from typing import Any

import pytest

from qbot_rpg.core.monster_intent import (
    build_intent,
    chain_preview_text,
    resume_broadcast,
    reveal_satisfied,
)
from qbot_rpg.core.monster_phases import (
    PhaseTable,
    inherit_boss_state,
    phase_changed_event,
    resolve_phase,
)

# ---------------------------------------------------------------- 熔岩霸王龙式配置（细化_1f §九）
ACTION_LIB = {
    "fire_ball": {"id": "fire_ball", "name": "火球", "kind": "active", "power": 1.0,
                  "tags": ["attack"], "intent": "伤害"},
    "tail_sweep": {"id": "tail_sweep", "name": "尾扫", "kind": "active", "power": 1.4,
                   "tags": ["attack"], "intent": "伤害"},
    "roar": {"id": "roar", "name": "吼叫", "kind": "active", "power": 0.2,
             "tags": ["defense"], "intent": "防御"},
    "doomsday_breath": {"id": "doomsday_breath", "name": "灭世龙息", "kind": "active",
                        "power": 3.0, "charge_turns": 2,
                        "preview_chain": ["tail_sweep"],
                        "reveal_condition": "codex>=3"},
    "guard_stance": {"id": "guard_stance", "name": "铁壁架势", "kind": "active",
                     "power": 0.0, "intent": "防御"},
    "magma_charge": {"id": "magma_charge", "name": "熔岩蓄能", "kind": "active",
                     "power": 0.0, "intent": "蓄力"},
}

ai_idle = {
    "state": "normal", "exec_state": "idle", "phase": 1, "chain_pos": 0,
    "chain_queue": [], "charge": None, "intent": {},
}
ai_charging = {
    "state": "normal", "exec_state": "charging", "phase": 1, "chain_pos": 0,
    "chain_queue": [], "charge": {"action_id": "doomsday_breath", "total": 2,
                                  "shown": 1, "remaining_turns": 2, "armor": True},
    "intent": {},
}


# ================================================================== 1. build_intent 三级分级

def test_build_intent_l1_charge_unrevealed():
    """L1 永远公开：蓄力中、图鉴未解锁 —— 类别 charge + 进度 1/2 + 招名???。"""
    r = build_intent("doomsday_breath", ACTION_LIB["doomsday_breath"],
                     ai_charging, codex_state={"codex": 0})
    assert r["level"] == 1, r["level"]
    assert r["category"] == "charge", r["category"]
    assert r["progress"] == "1/2", r["progress"]
    assert r["name_revealed"] is False
    assert r["chain_preview"] == [], r["chain_preview"]


def test_build_intent_l2_l3_codex_unlocked():
    """L2+L3 图鉴解锁后：level=3、招名揭示、连锁预演显现 + 文案。"""
    r = build_intent("doomsday_breath", ACTION_LIB["doomsday_breath"],
                     ai_charging, codex_state={"codex": 5})
    assert r["level"] == 3, r["level"]
    assert r["name_revealed"] is True
    assert r["chain_preview"] == ["tail_sweep"], r["chain_preview"]
    assert chain_preview_text(r["chain_preview"], ACTION_LIB) == "似乎要接【尾扫】"


def test_build_intent_category_three_values():
    """L1 类别三值：蓄力 → charge / 防御 → stance / 伤害 → None 无 L1。"""
    r = build_intent("magma_charge", ACTION_LIB["magma_charge"], ai_idle)
    assert r["category"] == "charge", r["category"]
    r = build_intent("guard_stance", ACTION_LIB["guard_stance"], ai_idle)
    assert r["category"] == "stance", r["category"]
    r = build_intent("fire_ball", ACTION_LIB["fire_ball"], ai_idle)
    assert r["category"] is None, r["category"]


def test_build_intent_charge_start_progress():
    """蓄力起始进度（无进行中 charge，读 charge_turns → 1/2）。"""
    r = build_intent("doomsday_breath", ACTION_LIB["doomsday_breath"], ai_idle)
    assert r["progress"] == "1/2", r["progress"]


def test_build_intent_preview_category_explicit():
    """preview 显式声明 category（P2-7 裁决：经 preview 字段显式声明）。"""
    preview_gather = dict(ACTION_LIB["fire_ball"], preview={"category": "gather"})
    r = build_intent("fire_ball", preview_gather, ai_idle)
    assert r["category"] == "gather", r["category"]


# ================================================================== 2. reveal_condition 多形态

def test_reveal_satisfied_forms():
    assert reveal_satisfied("codex>=3", {"codex": 2}) is False
    assert reveal_satisfied("codex>=3", {"codex": 3}) is True
    assert reveal_satisfied("lore:2", {"lore": 2}) is True
    assert reveal_satisfied("tail_sweep", {"tail_sweep": True}) is True
    assert reveal_satisfied(None) is True
    assert reveal_satisfied({"type": "lore_gte", "key": "lore", "value": 5},
                            {"lore": 6}) is True
    assert reveal_satisfied(["codex>=3", "lore:2"], {"codex": 5, "lore": 2}) is True
    assert reveal_satisfied(["codex>=3", "lore:2"], {"codex": 5, "lore": 1}) is False


# ================================================================== 3. resolve_phase 三阶段边界

def test_resolve_phase_boundaries():
    """monster_phases：resolve_phase 三阶段边界 100-60/60-30/30-0。"""
    assert resolve_phase(100) == 1
    assert resolve_phase(61) == 1
    assert resolve_phase(60) == 2, "阈值归下阶段"
    assert resolve_phase(31) == 2
    assert resolve_phase(30) == 3
    assert resolve_phase(0) == 3
    assert resolve_phase(-5) == 3, "夹取"
    assert resolve_phase(120, 200) == 2, "hp/max_hp 换算 60%"


# ================================================================== 4. PhaseTable 配置解析

PHASES = [
    {"threshold": 100, "name": "p1", "actions": [{"action": "claw", "weight": 40},
                                                 {"action": "tail_sweep", "weight": 20}],
     "broadcast": "🔥 {monster} 露出了獠牙！"},
    {"threshold": 60, "name": "p2", "actions": [{"action": "fire_ball", "weight": 30}],
     "enter_action": "roar", "broadcast": "🔥 {monster} 狂暴化！！"},
    {"threshold": 30, "name": "p3", "actions": [{"action": "doomsday_breath", "weight": 10}],
     "enter_action": "death_rattle", "broadcast": "💀 {monster} 开始最后的挣扎…"},
]


def test_phase_table_parsing():
    pt = PhaseTable(PHASES, monster_name="熔岩霸王龙")
    assert pt.count == 3, pt.count
    assert [p["threshold"] for p in pt.phases] == [100, 60, 30], "排序降序"
    assert len(pt.actions_for(1)) == 2, len(pt.actions_for(1))
    assert len(pt.actions_for(2)) == 1
    assert pt.actions_for(4) == [], "越界"
    assert pt.enter_action_for(2) == "roar"
    assert pt.enter_action_for(1) is None
    assert pt.broadcast_for(2) == "🔥 熔岩霸王龙 狂暴化！！", pt.broadcast_for(2)


def test_phase_table_resolve_phase():
    """resolve_phase 走配置表。"""
    pt = PhaseTable(PHASES, monster_name="熔岩霸王龙")
    assert pt.resolve_phase(45) == 2, pt.resolve_phase(45)
    assert pt.resolve_phase(450, 1000) == 2, "45%"


# ================================================================== 5. phase_changed 联动事件

def test_phase_changed_event():
    pt = PhaseTable(PHASES, monster_name="熔岩霸王龙")
    ev = pt.phase_changed_event(1, 2)
    assert ev is not None
    assert ev["type"] == "phase_changed", ev
    assert ev["value"] == 2 and ev["phase"] == 2 and ev["from"] == 1, ev
    assert pt.phase_changed_event(2, 2) is None, "同阶段 → None"
    assert phase_changed_event(1, 3)["value"] == 3, "模块级"
    assert 2 >= ev["value"], "monster_ai 兼容: phase>=value 语义"


def test_detect_transition():
    pt = PhaseTable(PHASES, monster_name="熔岩霸王龙")
    tr = pt.detect_transition(50, prev_phase=1)
    assert tr["changed"] is True, tr
    assert tr["phase"] == 2, tr["phase"]
    assert tr["event"]["value"] == 2, tr["event"]
    assert tr["enter_action"] == "roar", tr["enter_action"]
    assert "狂暴化" in (tr["broadcast"] or ""), tr["broadcast"]
    tr2 = pt.detect_transition(80, prev_phase=1)
    assert tr2["changed"] is False and tr2["event"] is None, tr2
    assert tr2["phase"] == 1, tr2["phase"]


# ================================================================== 6. resume_broadcast 中断恢复播报（TC-12）

def test_resume_broadcast():
    text = resume_broadcast({"chain_pos": 2, "chain_queue": ["fire_ball", "tail_sweep", "roar"]},
                            action_lib=ACTION_LIB)
    assert text == "连招 火球→【尾扫】→吼叫（2/3 段）", text
    text = resume_broadcast({"chain_pos": 1, "chain_queue": ["fire_ball", "tail_sweep", "roar"]},
                            action_lib=ACTION_LIB)
    assert text == "连招 【火球】→尾扫→吼叫（1/3 段）", text
    assert resume_broadcast({"chain_pos": 1, "chain_queue": ["a"]}) == "连招 【a】（1/1 段）", \
        "缺省 action_lib: 回退显示 id"
    assert resume_broadcast({"chain_pos": 0, "chain_queue": []}) == "", "无在途链 → 空串"


# ================================================================== 7. inherit_boss_state
# 云海九期（cloudsea-pack）207 移植：阶段切换 boss_state（break_slots/stamina/
# ailment_buildup 三键）携带纯函数。以下定向断言规则缺省透传/比例携带/边界四类。

BOSS_STATE = {
    "ailment_buildup": {"mark_a": 4.0, "mark_b": 3},
    "stamina": {"wing": 8.0},
    "break_slots": {"horn": 2.0},
}


def test_inherit_boss_state_default_passthrough():
    """rules 缺省 / None / 无比例键 → 三键原值透传，且不改动入参。"""
    before = {
        "ailment_buildup": {"mark_a": 4.0, "mark_b": 3},
        "stamina": {"wing": 8.0},
        "break_slots": {"horn": 2.0},
    }
    for rules in (None, {}, {"unrelated": 0.1}):
        out = inherit_boss_state(BOSS_STATE, rules) if rules is not None \
            else inherit_boss_state(BOSS_STATE)
        assert out["ailment_buildup"] == {"mark_a": 4.0, "mark_b": 3}, out
        assert out["stamina"] == {"wing": 8.0}, out
        assert out["break_slots"] == {"horn": 2.0}, out
    assert BOSS_STATE == before, "原值透传路径零副作用"


def test_inherit_boss_state_returns_copy():
    """返回值为深一层副本：改 out 不影响入参 prev。"""
    out = inherit_boss_state(BOSS_STATE, {"stack_retain": 0.5})
    out["ailment_buildup"]["mark_a"] = 99.0
    out["stamina"]["wing"] = 99.0
    assert BOSS_STATE["ailment_buildup"]["mark_a"] == 4.0
    assert BOSS_STATE["stamina"]["wing"] == 8.0


def test_inherit_boss_state_skeleton_keys_added():
    """三键约定缺省的键补空 dict（骨架齐备）。"""
    out = inherit_boss_state({"ailment_buildup": {"x": 1}})
    assert out["stamina"] == {} and out["break_slots"] == {}
    assert out["ailment_buildup"] == {"x": 1}


def test_inherit_boss_state_ratio_carry():
    """stack_retain 作用于积蓄/耐力，control_mult 作用于部位槽。"""
    out = inherit_boss_state(BOSS_STATE, {"stack_retain": 0.5, "control_mult": 0.5})
    assert out["ailment_buildup"] == {"mark_a": 2.0, "mark_b": 1.5}
    assert out["stamina"] == {"wing": 4.0}
    assert out["break_slots"] == {"horn": 1.0}
    # 单给一路比例时另一路原值
    only_stack = inherit_boss_state(BOSS_STATE, {"stack_retain": 0.5})
    assert only_stack["break_slots"] == {"horn": 2.0}
    only_ctrl = inherit_boss_state(BOSS_STATE, {"control_mult": 0.5})
    assert only_ctrl["ailment_buildup"] == {"mark_a": 4.0, "mark_b": 3}
    assert only_ctrl["break_slots"] == {"horn": 1.0}


def test_inherit_boss_state_bounds():
    """边界：0 → 清零；1 → 原值；超界 >1 → 按比例放大（不夹取）。"""
    zero = inherit_boss_state(BOSS_STATE, {"stack_retain": 0, "control_mult": 0})
    assert zero["ailment_buildup"] == {"mark_a": 0.0, "mark_b": 0}
    assert zero["stamina"] == {"wing": 0.0}
    assert zero["break_slots"] == {"horn": 0.0}
    one = inherit_boss_state(BOSS_STATE, {"stack_retain": 1, "control_mult": 1})
    assert one["ailment_buildup"] == {"mark_a": 4.0, "mark_b": 3}
    over = inherit_boss_state(BOSS_STATE, {"stack_retain": 3, "control_mult": 4})
    assert over["ailment_buildup"] == {"mark_a": 12.0, "mark_b": 9}
    assert over["stamina"] == {"wing": 24.0}
    assert over["break_slots"] == {"horn": 8.0}


def test_inherit_boss_state_invalid_inputs():
    """非法比例/非法 prev/非数值叶：原值或空骨架，不抛异常。"""
    assert inherit_boss_state({"ailment_buildup": {"a": 4.0}}, {"stack_retain": "0.5"})[
        "ailment_buildup"] == {"a": 4.0}, "非数值比例忽略"
    assert inherit_boss_state({"ailment_buildup": {"a": "keep"}},
                              {"stack_retain": 0.5})["ailment_buildup"] == {"a": "keep"}
    assert inherit_boss_state({"ailment_buildup": {"a": True}},
                              {"stack_retain": 0.5})["ailment_buildup"] == {"a": True}, \
        "bool 不参与缩放"
    for bad in (None, "x", 3, ["a"]):
        assert inherit_boss_state(bad) == {
            "break_slots": {}, "stamina": {}, "ailment_buildup": {}}, bad


# ================================================================== 8. build_intent 扩展字段
# 云海九期（cloudsea-pack）215 移植：stage_shift/windup/target_ref/damage_tier
# 四关键字扩展——缺省 None 不入 dict，既有调用形态零变化。

EXT_KEYS = ("stage_shift", "windup", "target_ref", "damage_tier")


def test_build_intent_ext_default_absent():
    """action_def 无四键且未传 kwarg → 四键均不入 dict（向后兼容）。"""
    r = build_intent("fire_ball", ACTION_LIB["fire_ball"], ai_idle)
    for k in EXT_KEYS:
        assert k not in r, (k, r)


def test_build_intent_ext_from_action_def():
    """action_def 携带四键 → 落入 intent（缺省 kwarg 走 action_def 回退）。"""
    adef = dict(ACTION_LIB["fire_ball"], stage_shift=2, windup="windup_a",
                target_ref="player", damage_tier=3)
    r = build_intent("fire_ball", adef, ai_idle)
    assert r["stage_shift"] == 2
    assert r["windup"] == "windup_a"
    assert r["target_ref"] == "player"
    assert r["damage_tier"] == 3


def test_build_intent_ext_kwarg_override():
    """显式 kwarg 覆盖 action_def 同名键。"""
    adef = dict(ACTION_LIB["fire_ball"], stage_shift=2, damage_tier=1)
    r = build_intent("fire_ball", adef, ai_idle, stage_shift=9, damage_tier=8)
    assert r["stage_shift"] == 9
    assert r["damage_tier"] == 8
    assert "windup" not in r, "action_def 无且 kwarg 缺省 → 仍不入"


def test_build_intent_ext_none_not_entered():
    """action_def 显式 None 或 kwarg 显式 None → 键不入 dict（判据是 None，非真值）。"""
    adef = dict(ACTION_LIB["fire_ball"], stage_shift=None, windup="w")
    r = build_intent("fire_ball", adef, ai_idle, target_ref=None)
    assert "stage_shift" not in r
    assert "target_ref" not in r
    assert r["windup"] == "w"


def test_build_intent_ext_falsy_non_none_kept():
    """0 / "" / False 非 None → 照常入 dict（避免真值判断误吞合法值）。"""
    adef = dict(ACTION_LIB["fire_ball"], stage_shift=0, target_ref="", damage_tier=False)
    r = build_intent("fire_ball", adef, ai_idle)
    assert r["stage_shift"] == 0
    assert r["target_ref"] == ""
    assert r["damage_tier"] is False


def test_build_intent_ext_keyword_only():
    """四扩展字段为 keyword-only：既有 4 位置参数调用不受影响，第 5 位置参数报错。"""
    basis = build_intent("fire_ball", ACTION_LIB["fire_ball"], ai_idle, {"codex": 5})
    assert basis["level"] == 2
    flexible: Any = build_intent
    with pytest.raises(TypeError):
        flexible("fire_ball", ACTION_LIB["fire_ball"], ai_idle, None, 1)
