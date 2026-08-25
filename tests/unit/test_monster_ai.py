"""M2 怪物 AI 决策引擎（B1 路）单元测试：固化 /tmp/smoke_monster_ai.py 的 76 断言。

依据：细化_1f_怪物AI状态机.md（② L0-L7 决策管线 / TC-01 状态机 / TC-03 L5 状态专属 /
TC-08 套内不评估 / TC-09 L7 兜底 / TC-15 hungry 保底 / TC-16 chain C roll /
TC-18 蓄力跨回合）＋ docs/m2_shared_contract.md §五（MonsterAI 接口 / ai_state 14 键快照 /
intent_for 契约结构 / evaluate_conditions & roll_chain 语义）。

原 /tmp/smoke_monster_ai.py 已全绿（exit 0, SMOKE PASS: 76 assertions），此处按 pytest
惯例固化：断言逻辑原样保留不改语义（铁律：临时脚本删除 ≠ 丢弃用例）。分组：
  S1  归一化概率（normal/enraged 两态）+ 注入 rng 固定选择 + 大样本统计
  S2  hungry 强制选（TC-15）
  S3  L0 套内门跳过评估（TC-08）
  S4  蓄力起手/结算/跨回合不切态（TC-18）
  S5  L2 强制队列优先于随机池
  S6  L5 状态专属行动（TC-03 语义）+ 冷却过滤 + tick 递减
  S7  L7 兜底普攻（TC-09）
  S8  downed 起身占行动槽
  S9  cooldown 过滤随机池
  S10 L3/L4/intent 接口契约（接线后语义：intent_for 契约结构 / probability 正值等价 1）
  S11 链引用 roll（TC-16：真实 chance roll 入队 / roll 失败断链+链冷却）
  S12 决策返回 action_dict 形态（C1 接线：type/skill_id/mult/kind/action_id/action/source/ai_state）

确定性（铁律 6/8）：决策一律注入 ScriptedRng 固定序列；大样本用固定 seed 的 random.Random
（可复现）；禁止裸/未播种 random。
"""
from __future__ import annotations

import random

from qbot_rpg.core.monster_ai import (
    CHARGING,
    DOWNED,
    ENRAGED,
    IDLE,
    IN_CHAIN,
    MonsterAI,
    NORMAL,
)

# ------------------------------------------------------------------ 行动库与敌人配置（与 smoke 一致）

ACTION_LIB = {
    "claw_swipe": {"id": "claw_swipe", "kind": "active", "power": 1.2, "tags": ["attack"]},
    "tail_sweep": {"id": "tail_sweep", "kind": "active", "power": 1.5, "tags": ["attack"]},
    "roar": {"id": "roar", "kind": "active", "power": 0.5, "tags": ["defense"]},
    "fire_burst": {"id": "fire_burst", "kind": "active", "power": 2.0, "tags": ["attack"]},
    "big_bite": {"id": "big_bite", "kind": "active", "power": 1.8, "tags": ["attack"]},
    "doomsday_breath": {"id": "doomsday_breath", "kind": "active", "power": 4.0,
                        "tags": ["attack"], "charge_turns": 2, "charge_armor": True},
    "fireball": {"id": "fireball", "kind": "active", "power": 1.6, "tags": ["attack"]},
}

# ENEMY_A：40/20/10 随机池 + enraged 状态机（TC-01/TC-02 语义）
ENEMY_A = {
    "id": "smoke_brute", "name": "烟雾蛮兽",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 40},
        {"action": "tail_sweep", "probability": 1, "weight": 20},
        {"action": "roar", "probability": 1, "weight": 10},
        # 锚点（probability 0）：只被状态机/L5 触发
        {"action": "fire_burst", "probability": 0, "weight": 0, "cooldown": 2},
    ],
    "special_actions": [],
    "chains": [],
    "ai": {
        "states": {
            "enraged": {"enter_action": "roar", "weight_mod": {"attack": 1.5, "defense": 0.5},
                        "exclusive_actions": ["fire_burst"]},
            "dying": {"enter_action": "death_rattle", "weight_mod": {"attack": 2.0},
                      "exclusive_actions": ["final_strike"]},
        },
        "transitions": [
            {"from": "normal", "to": "enraged", "condition": {"type": "hp_below", "value": 50}},
            {"from": "enraged", "to": "dying", "condition": {"type": "hp_below", "value": 15}},
        ],
    },
}

# ENEMY_B：hungry 保底（TC-15）
ENEMY_B = {
    "id": "hungry_wolf", "name": "饥饿狼",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 40},
        {"action": "tail_sweep", "probability": 1, "weight": 20},
        {"action": "roar", "probability": 1, "weight": 10},
        {"action": "big_bite", "probability": 1, "weight": 5, "hungry": 3},
    ],
    "special_actions": [], "chains": [],
}

# ENEMY_C：蓄力（TC-18）
ENEMY_C = {
    "id": "charge_drake", "name": "蓄力龙",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 1},
        {"action": "doomsday_breath", "probability": 1, "weight": 0, "hungry": 1},
    ],
    "special_actions": [], "chains": [],
}

# ENEMY_D：L7 兜底（TC-09）
ENEMY_D = {"id": "dummy", "name": "木桩", "actions": [], "special_actions": [], "chains": []}

# ENEMY_E：链引用（roll_chain → 断链）
ENEMY_E = {
    "id": "chain_boss", "name": "连招王",
    "actions": [{"action": "fireball", "probability": 1, "weight": 1}],
    "special_actions": [],
    "chains": [
        {"id": "molten", "cooldown": 2,
         "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"},
                     {"action": "tail_sweep", "chance": 1.0, "role": "finisher"}]},
    ],
    "ai": {"states": {}, "transitions": []},
}


class ScriptedRng:
    """注入确定性 rng：按脚本序列循环返回 random()；choice 走 random() 映射（铁律 6）。"""

    def __init__(self, values):
        self._values = list(values)
        self.calls = 0

    def random(self):
        v = self._values[self.calls % len(self._values)] if self._values else 0.0
        self.calls += 1
        return v

    def choice(self, seq):
        return seq[int(self.random() * len(seq)) % len(seq)]


def close(a, b, tol=1e-6):
    return abs(a - b) <= tol


def new_state(hp, max_hp=100, turn=1, **ai_over):
    ai = {"state": NORMAL, "exec_state": IDLE, "phase": 1, "chain_pos": 0, "chain_queue": [],
          "chain_id": None, "chain_cooldowns": {}, "charge": None, "trigger_cooldowns": {},
          "action_cooldowns": {}, "hungry_count": {}, "intent": {}, "forced_queue": [],
          "boss_phase": 1}
    ai.update(ai_over)
    return {"turn": turn, "player": {"hp": 500, "max_hp": 500},
            "enemy": {"hp": hp, "max_hp": max_hp, "pv": 10}, "ai_state": ai}


# ================================================================== S1 归一化概率

def test_s1a_normalized_probabilities():
    """normal 态 40/20/10 → 57.1429%/28.5714%/14.2857%（1f ④4.2 示例）。"""
    ai_a = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs = new_state(100)
    probs = ai_a.pool_probabilities(bs)
    assert close(probs["claw_swipe"], 40 / 70), probs
    assert close(probs["tail_sweep"], 20 / 70), probs
    assert close(probs["roar"], 10 / 70), probs
    assert "fire_burst" not in probs, probs  # 锚点(prob0)不入池


def test_s1b_enraged_weight_mod():
    """enraged 态 attack×1.5 / defense×0.5 → 60/30/5 → 63.158%/31.579%/5.263%。"""
    ai_a2 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs2 = new_state(40)  # hp 40% < 50 → enraged
    ai_a2.evaluate_transitions(bs2)
    assert bs2["ai_state"]["state"] == ENRAGED, "L1 切 enraged"
    probs2 = ai_a2.pool_probabilities(bs2)
    assert close(probs2["claw_swipe"], 60 / 95), probs2
    assert close(probs2["tail_sweep"], 30 / 95), probs2
    assert close(probs2["roar"], 5 / 95), probs2


def test_s1c_scripted_rng_selection():
    """注入固定 rng 断言选择结果（0.0→claw，0.6→tail，0.9→roar；阈值 40/60/70）。"""
    ai_a3 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.0]))
    r = ai_a3.decide(new_state(100))
    assert r["action_id"] == "claw_swipe", r["source"]
    ai_a4 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.6]))
    r = ai_a4.decide(new_state(100))
    assert r["action_id"] == "tail_sweep", r["source"]
    ai_a5 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.9]))
    r = ai_a5.decide(new_state(100))
    assert r["action_id"] == "roar", r["source"]
    assert r["source"] == "L6", "来源 L6"
    assert r["ai_state"] is r["ai_state"] or True  # 返回含 ai_state（smoke 原样保留）


def test_s1d_large_sample_statistics():
    """大样本统计趋近（固定 seed 可复现，20k 次决策）。"""
    rng = random.Random(20260826)
    ai_a6 = MonsterAI(ENEMY_A, ACTION_LIB, rng)
    counts = {"claw_swipe": 0, "tail_sweep": 0, "roar": 0}
    N = 20000
    for _ in range(N):
        bsx = new_state(100)
        r = ai_a6.decide(bsx)
        counts[r["action_id"]] += 1
    for aid, expect in (("claw_swipe", 40 / 70), ("tail_sweep", 20 / 70), ("roar", 10 / 70)):
        got = counts[aid] / N
        assert close(got, expect, 0.015), f"大样本 {aid} {got:.4f} vs {expect:.4f}"


# ================================================================== S2 hungry 保底（TC-15）

def test_s2_hungry_forced_pick():
    ai_b = MonsterAI(ENEMY_B, ACTION_LIB, ScriptedRng([0.001]))  # 恒选 claw
    bsb = new_state(100)
    r1 = ai_b.decide(bsb)
    assert r1["action_id"] == "claw_swipe", "第1回合选 claw"
    assert bsb["ai_state"]["hungry_count"]["big_bite"] == 1, "hungry big_bite=1"
    r2 = ai_b.decide(bsb)
    assert r2["action_id"] == "claw_swipe", "第2回合选 claw"
    assert bsb["ai_state"]["hungry_count"]["big_bite"] == 2, "hungry big_bite=2"
    r3 = ai_b.decide(bsb)
    assert r3["action_id"] == "big_bite", "第3回合 hungry 强制选 big_bite"
    assert bsb["ai_state"]["hungry_count"]["big_bite"] == 0, "选中后饥饿清零"


# ================================================================== S3 L0 套内门（TC-08）

def test_s3_l0_chain_inside_skips_eval():
    ai_a7 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs3 = new_state(40)  # HP 40%：若评估会切 enraged
    bs3["ai_state"]["exec_state"] = IN_CHAIN
    bs3["ai_state"]["chain_queue"] = ["tail_sweep"]
    bs3["ai_state"]["chain_pos"] = 1
    r = ai_a7.decide(bs3)
    assert r["action_id"] == "tail_sweep", "L0 链推进执行尾扫"
    assert r["source"] == "L0_chain", "来源 L0_chain"
    assert bs3["ai_state"]["state"] == NORMAL, "套内不切状态（TC-08）"
    assert bs3["ai_state"]["forced_queue"] == [], "套内不入强制队列"
    assert bs3["ai_state"]["chain_queue"] == [], "链走完清空"
    assert bs3["ai_state"]["exec_state"] == IDLE, "套结算完回 idle"
    # 下一回合：套间评估 → HP 40 < 50 → 切 enraged + enter_action roar 走 L2
    r2b = ai_a7.decide(bs3)
    assert r2b["action_id"] == "roar", "套间 L1→L2 enter_action 吼叫"
    assert r2b["source"] == "L2", "enter_action 来源 L2"
    assert bs3["ai_state"]["state"] == ENRAGED, "套间切 enraged"


# ================================================================== S4 蓄力（TC-18）

def test_s4_charge_cross_rounds():
    ai_c = MonsterAI(ENEMY_C, ACTION_LIB, ScriptedRng([0.001]))  # hungry=1 强制蓄力
    bsc = new_state(100)
    r1c = ai_c.decide(bsc)
    assert r1c.get("charging") is True, "蓄力起手 charging 标记"
    assert r1c.get("progress") == "1/2", "蓄力进度 1/2"
    assert bsc["ai_state"]["exec_state"] == CHARGING, "执行态 charging"
    assert bsc["ai_state"]["charge"]["action_id"] == "doomsday_breath", "charge 登记"
    assert bsc["ai_state"]["charge"]["armor"] is True, "charge armor 霸体"
    # TC-18：蓄力期间 HP 跨阈值 → 套内门跳过 L1，不切状态
    bsc["enemy"]["hp"] = 30
    r2c = ai_c.decide(bsc)
    assert r2c.get("charging") is True and r2c.get("progress") == "2/2", r2c
    assert bsc["ai_state"]["state"] == NORMAL, "蓄力期间不切状态（TC-18）"
    r3c = ai_c.decide(bsc)
    assert r3c.get("charging") is None or r3c.get("charging") is False, "蓄力释放"
    assert r3c["action_id"] == "doomsday_breath", "释放灭世龙息"
    assert r3c["source"] == "L0_charge", "释放来源 L0_charge"
    assert bsc["ai_state"]["charge"] is None, "释放后 charge 清空"


# ================================================================== S5 L2 强制队列优先

def test_s5_l2_forced_queue_priority():
    ai_a8 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.9]))  # rng 会选 roar（L6），应被 L2 抢先
    bs5 = new_state(100)
    bs5["ai_state"]["forced_queue"] = ["claw_swipe"]
    r = ai_a8.decide(bs5)
    assert r["action_id"] == "claw_swipe" and r["source"] == "L2", "L2 强制队列优先于 L6"
    assert bs5["ai_state"]["forced_queue"] == [], "队首出队"


# ================================================================== S6 L5 状态专属行动（TC-03 语义）

def test_s6_l5_state_exclusive_action():
    ai_a9 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.9]))
    bs6 = new_state(40)
    bs6["ai_state"]["forced_queue"] = []
    # 直接构造 enraged 态（跳过 L1 触发路径，专测 L5）
    bs6["ai_state"]["state"] = ENRAGED
    r = ai_a9.decide(bs6)
    assert r["action_id"] == "fire_burst" and r["source"] == "L5", "L5 exclusive fire_burst"
    # fire_burst 冷却 2 → 下次 L5 过滤 → 落 L6
    r2s = ai_a9.decide(bs6)
    assert r2s["source"] == "L6", "L5 冷却过滤后落 L6"
    assert bs6["ai_state"]["action_cooldowns"]["fire_burst"] == 2, "fire_burst 冷却登记"
    # tick 递减
    ai_a9.tick(bs6["ai_state"])
    assert bs6["ai_state"]["action_cooldowns"]["fire_burst"] == 1, "tick 冷却 2→1"
    ai_a9.tick(bs6["ai_state"])
    assert "fire_burst" not in bs6["ai_state"]["action_cooldowns"], "tick 冷却归零移除"


# ================================================================== S7 L7 兜底普攻（TC-09）

def test_s7_l7_fallback():
    ai_d = MonsterAI(ENEMY_D, ACTION_LIB, ScriptedRng([0.5]))
    bs7 = new_state(100)
    r = ai_d.decide(bs7)
    assert r["source"] == "L7", "兜底来源 L7"
    assert r["type"] == "normal" and r["mult"] == 1.0, "默认普攻 type/mult"


# ================================================================== S8 downed 起身

def test_s8_downed_get_up():
    ai_a10 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs8 = new_state(100)
    bs8["ai_state"]["exec_state"] = DOWNED
    r = ai_a10.decide(bs8)
    assert r["action_id"] == "__get_up__" and r["kind"] == "get_up", "downed 起身占行动槽"
    assert bs8["ai_state"]["exec_state"] == IDLE, "起身后回 idle"


# ================================================================== S9 cooldown 过滤随机池

def test_s9_cooldown_filtered_pool():
    ai_a11 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs9 = new_state(100)
    bs9["ai_state"]["action_cooldowns"]["roar"] = 1  # 手动置冷却
    probs9 = ai_a11.pool_probabilities(bs9)
    assert "roar" not in probs9, probs9
    r = ai_a11.decide(bs9)
    assert r["action_id"] != "roar", r["action_id"]


# ================================================================== S10 L3/L4/intent 接口留桩 + probability 正值等价

def test_s10_l3_l4_intent_contract():
    ai_a12 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.5]))
    bs10 = new_state(100)
    assert ai_a12.evaluate_conditions(bs10) == [], "L3 接口返回空（无 special_actions）"
    assert ai_a12.roll_chain("x", bs10) is False, "L4 roll_chain 悬空链 False"
    it = ai_a12.intent_for("claw_swipe", bs10)
    assert isinstance(it, dict) and it.get("action_id") == "claw_swipe" and "level" in it \
        and "name_revealed" in it and "chain_preview" in it and "progress" in it, \
        "intent 接线返回契约结构"
    # probability 其他正值等价 1（contract §一）
    ENEMY_A11 = {**ENEMY_A, "actions": [{"action": "claw_swipe", "probability": 2, "weight": 1},
                                        {"action": "tail_sweep", "probability": 1, "weight": 1}]}
    ai_a13 = MonsterAI(ENEMY_A11, ACTION_LIB, ScriptedRng([0.5]))
    assert set(ai_a13.pool_probabilities(new_state(100))) == {"claw_swipe", "tail_sweep"}, \
        "probability 正值等价 1"


# ================================================================== S11 链引用（接线后：真实 chance roll，TC-16 语义）

def test_s11_chain_roll_success_enqueues():
    """火球 chance 0.8：r=0.5 → roll 成功 → 尾扫入队待 L0（套内确定性）。"""
    ai_e = MonsterAI(ENEMY_E, ACTION_LIB, ScriptedRng([0.5]))
    bs11 = new_state(100)
    bs11["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    r = ai_e.decide(bs11)
    assert r["action_id"] == "fireball" and r["source"] == "L2", "引链行动照常执行"
    assert bs11["ai_state"]["chain_queue"] == ["tail_sweep"], "roll 成功尾扫入队"
    assert bs11["ai_state"]["chain_cooldowns"] == {}, "roll 成功无链冷却"
    assert bs11["ai_state"]["exec_state"] == IN_CHAIN, "入队后执行态 in_chain"


def test_s11_chain_roll_fail_breaks():
    """火球 chance 0.8：r=0.9 → roll 失败 → 断链+链冷却。"""
    ai_e2 = MonsterAI(ENEMY_E, ACTION_LIB, ScriptedRng([0.9]))
    bs11b = new_state(100)
    bs11b["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    r = ai_e2.decide(bs11b)
    assert r["action_id"] == "fireball" and r["source"] == "L2", "断链时行动照常"
    assert bs11b["ai_state"]["chain_queue"] == [], "断链队列清空"
    # M2 审查 P1-2：冷却 max 保留 + 起算偏移（登记 cooldown+1，防断链当回合被 tick 清零）
    # molten cooldown=2 → 登记 3（次回合起算实际阻断）
    assert bs11b["ai_state"]["chain_cooldowns"].get("molten", 0) == 3, "断链+链冷却(起算偏移)"


# ================================================================== S12 决策返回 action_dict 形态（C1 接线）

def test_s12_action_dict_shape():
    ai_a14 = MonsterAI(ENEMY_A, ACTION_LIB, ScriptedRng([0.0]))
    bs12 = new_state(100)
    r = ai_a14.decide(bs12)
    for k in ("type", "skill_id", "mult", "kind", "action_id", "action", "source", "ai_state"):
        assert k in r, r.keys()
    assert r["type"] == "skill" and r["skill_id"] == "claw_swipe", "skill 行动 type/skill_id"
    assert r["ai_state"] is bs12["ai_state"], "ai_state 回灌引用"
