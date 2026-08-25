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

from qbot_rpg.core.monster_intent import (
    build_intent,
    chain_preview_text,
    resume_broadcast,
    reveal_satisfied,
)
from qbot_rpg.core.monster_phases import (
    PhaseTable,
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
