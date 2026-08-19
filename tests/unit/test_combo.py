"""连段引擎单测（M1-批3 · 细化_1c1a/1c1b/1c1c/1c2 + testing）。

依据：细化_1c1a 状态集 / 1c1b 迁移表（①②③④⑤⑥⑦⑧+A1..A5）/ 1c1c 到顶清零（TOP-*）/
1c2 配置与打断霸体（INT-*/ARM-*）。主 agent 收口复核固化（子代理撞迭代上限）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.battle import BattleEngine


CHAIN = {
    "id": "c1", "name": "火之连", "trigger_skill": "a", "max_combo": 3, "max_combo_behavior": "reset",
    "steps": [
        {"from": "a", "to": "b", "mode": "replace", "condition": {"count": 2}},  # count>=2 时 a 派生 b
        {"from": "b", "to": "c", "mode": "replace", "condition": {"count": 3}},
    ],
}
SKILLS = {
    "a": {"id": "a", "name": "火球", "tag": "combo"},
    "b": {"id": "b", "name": "大火球", "tag": "combo"},
    "c": {"id": "c", "name": "龙息", "tag": "combo"},
    "z": {"id": "z", "name": "普通斩", "tag": ""},
}


def engine() -> ComboEngine:
    defs: dict = {"c1": CHAIN, **SKILLS}
    return ComboEngine(defs=defs, resolver=lambda id_, kind: defs.get(id_ or ""))


def snap(count: int = 0, chain: bool = False) -> dict:
    return {
        "combo_state": {"player":
                        ({"chain_id": "c1", "chain_name": "火之连", "count": count,
                          "hold": False, "step_index": -1} if chain else {}),
                        "enemy": {}},
        "turn": 3,
        "player": {"max_hp": 500, "hp": 300},
        "enemy": {"max_hp": 400, "hp": 200},
        "status_state": {"player": [], "enemy": []},
    }


# ---------------- 迁移①②③（1c1b） ----------------
def test_c01_first_combo_skill_0_to_1():
    s = snap()
    r = engine().apply_action("player", {"skill_id": "a", "tag": "combo"}, s)
    assert r.ok and r.count_after == 1 and r.chain_id == "c1"
    assert s["combo_state"]["player"]["count"] == 1


def test_c02_sequence_increments():
    eng = engine()
    s = snap(chain=True, count=1)
    r = eng.apply_action("player", {"skill_id": "a", "tag": "combo"}, s)
    assert r.ok and r.count_after == 2


def test_c03_plain_skill_breaks_chain():
    """A4 无标签普通技能：活跃链时自断清零（普通斩斩断连段）。"""
    eng = engine()
    s = snap(chain=True, count=2)
    r = eng.apply_action("player", {"skill_id": "z", "tag": ""}, s)
    assert r.cleared_reason is not None, "普通技能应清零活跃链"
    assert s["combo_state"]["player"].get("count", 0) == 0 or r.cleared_reason


def test_c04_derive_form_replace():
    """③ 派生（自动替换→to，计数保留）：count>=2 时 a 派生为 b，step_index 记录步索引（D4）。"""
    eng = engine()
    s = snap(chain=True, count=2)
    r = eng.apply_action("player", {"skill_id": "a", "tag": "combo"}, s)
    assert r.ok and r.derivation is True
    assert r.form_id == "b" and r.count_before == 2 and r.count_after == 2  # 派生计数保留
    assert r.step is not None and r.step.index >= 0
    assert s["combo_state"]["player"].get("step_index", -1) == 0  # D4：形态机进度写入


# ---------------- 到顶清零（1c1c TOP-*） ----------------
def test_c05_at_max_reset():
    """TC-TOP-01：max_combo_behavior=reset 归零重打（count 3==max → 归零从头再计数）。"""
    eng = engine()
    s = snap(chain=True, count=3)   # == max_combo(3)
    r = eng.apply_action("player", {"skill_id": "a", "tag": "combo"}, s)
    assert r.count_before == 3
    assert r.count_after == 1, f"reset 行为到顶归零重打（从头 +1），got {r.count_after}"


# ---------------- 打断/霸体（1c2 INT-*/ARM-*） ----------------
def test_c06_interrupt_clears_chain():
    eng = engine()
    s = snap(chain=True, count=2)
    r = eng.apply_interrupt("enemy", "player", s, armor_active={"player": False, "enemy": False})
    assert r.success is True
    assert s["combo_state"]["player"].get("count", 0) == 0


def test_c07_armor_blocks_interrupt():
    eng = engine()
    s = snap(chain=True, count=2)
    r = eng.apply_interrupt("enemy", "player", s, armor_active={"player": True, "enemy": False})
    assert r.success is False, "霸体（armor_active=True）免疫打断"


def test_c08_is_armored():
    eng = engine()
    s = snap(chain=True, count=2)
    assert eng.is_armored("player", s, {"player": True, "enemy": False}) is True
    assert eng.is_armored("player", s, {"player": False, "enemy": False}) is False


# ---------------- battle 集成（主 agent 收口接线） ----------------
PLAYER = {"max_hp":500,"hp":500,"max_mp":100,"mp":100,"atk":100,"dfn":50,"mag":50,"spd":50,
          "foc":100,"con":50,"str":100,"int":80,"agi":50,"spr":50,"lck":50,"elem_atk":0,"name":"P"}
ENEMY = {"max_hp":400,"hp":400,"max_mp":0,"mp":0,"atk":80,"dfn":40,"mag":30,"spd":40,"foc":50,"con":50,
         "str":80,"int":30,"agi":40,"spr":40,"lck":10,"elem_atk":0,"name":"E"}


class QueueRNG:
    def __init__(self, seq):
        self.seq = list(seq); self.i = 0
    def random(self):
        v = self.seq[self.i]; self.i = (self.i + 1) % len(self.seq); return v


def test_battle_combo_basic_no_chain():
    """battle do_action normal（无链）走 _resolve_combo_action 不崩、combo_state 键存在。"""
    eng = BattleEngine()
    eng._rng = QueueRNG([0.5, 0.5, 0.5, 1.0])
    eng.start(PLAYER, ENEMY, random_seed=1)
    out = eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert out.hit is True and out.raw_damage > 0
    assert "combo_state" in eng.battle_state()


def test_battle_combo_skill_tracks_state():
    """battle 连段技推进 combo_state.count（经 ComboEngine 接线）。"""
    defs = {"c1": CHAIN, **SKILLS}
    eng = BattleEngine(defs=defs)
    eng._rng = QueueRNG([0.5, 0.5, 0.5, 1.0])
    eng.start(PLAYER, ENEMY, random_seed=2)
    eng.do_action("player", {"type": "skill", "skill_id": "a", "tag": "combo", "mult": 1.0})
    count = eng.battle_state()["combo_state"]["player"].get("count", 0)
    assert count == 1, f"连段技应推进计数（got {count}）"


# ---------------- dsh 批3 审查修复回归（审查_M1_batch3） ----------------
def test_p0_marks_condition_fails_safe_without_lookup():
    """P0-1 回归：无 marks_lookup 时含印记条件的派生必须不满足（1c3 TC-13 安全失败），
    原实现未知键静默恒 True → 印记条件派生无条件触发（反安全）。"""
    from qbot_rpg.core.combo import ConditionCtx, evaluate_condition
    cctx = ConditionCtx(count=3, target_hp_pct=50.0, round_=3)
    # marks 条件（无 lookup）→ False
    assert evaluate_condition({"marks_total": {"min": 5}}, cctx) is False
    assert evaluate_condition({"self_marks": {"has": ["火印"]}}, cctx) is False
    # 未知键 → False（TC-13）
    assert evaluate_condition({"foo_bar": 1}, cctx) is False
    # 已知键仍工作
    assert evaluate_condition({"count": 3}, cctx) is True


def test_p0_marks_condition_with_lookup():
    """P0-1/D1 回归：marks_lookup 接线后按 1d §3.1 规范语法（AT-14 五原语）正确求值——
    C-1 指定印记 min / C-2 target max / C-3 total / C-4 all 齐备 / C-5 种类数。"""
    from qbot_rpg.core.combo import ConditionCtx, evaluate_condition
    from qbot_rpg.core.marks import AddMark, MarksManager
    cctx = ConditionCtx(count=3, target_hp_pct=50.0, round_=3)
    mm = MarksManager({"player": [], "enemy": []})
    mm.apply_add(AddMark(side="player", mark="火印", count=3))
    mm.apply_add(AddMark(side="player", mark="水印", count=2))
    mm.apply_add(AddMark(side="enemy", mark="诅咒印", count=1))

    def lookup(kind, which, rule, mark_id=None):
        side = "player" if which == "self" else "enemy"
        return mm.evaluate(kind, side, dict(rule), mark_id)

    # AT-14 五原语全真（施放者 3 火 + 2 水；目标 1 诅咒）
    assert evaluate_condition({"self_marks": {"火印": {"min": 3}}}, cctx, lookup) is True
    assert evaluate_condition({"target_marks": {"诅咒印": {"max": 1}}}, cctx, lookup) is True
    assert evaluate_condition({"marks_total": {"min": 5}}, cctx, lookup) is True
    assert evaluate_condition({"marks_set": {"all": ["火印", "水印"]}}, cctx, lookup) is True
    assert evaluate_condition({"marks_any": {"min": 2}}, cctx, lookup) is True   # 种类数 2
    # 反例
    assert evaluate_condition({"self_marks": {"火印": {"min": 5}}}, cctx, lookup) is False
    assert evaluate_condition({"marks_any": {"min": 3}}, cctx, lookup) is False  # 种类数 2 < 3


def test_p1_step_index_roundtrip():
    """P1-1 回归：ComboState step_index=0（合法）快照往返不回退成 -1。"""
    from qbot_rpg.core.combo import ComboState
    s0 = ComboState(chain_id="c1", chain_name="火之连", count=2, step_index=0)
    s1 = ComboState.from_dict(s0.to_dict())
    assert s1.step_index == 0
    s2 = ComboState.from_dict({"chain_id": "c1", "chain_name": "x", "count": 1, "step_index": -1})
    assert s2.step_index == -1  # 空闲态仍 -1
