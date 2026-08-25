"""M2 怪物 AI × 战斗引擎集成（C1 路）集成测试。

依据：细化_1f_怪物AI状态机.md（⑥ TC-08 套内不评估 / TC-15 hungry 保底 / TC-16 chain C roll /
TC-17 打断=套完结 / TC-18 蓄力跨回合）＋ docs/m2_shared_contract.md 第六节（battle 挂接点：
enemy_act None 分支用 MonsterAI.decide 产出行动 → 走既有 _do_action/_resolve_damage_action
执行通道；决策后 ai_state 回灌快照；打断=套完结）＋ 第八节铁律（确定性注入 rng / 拦截链接线 /
零 NoneBot import）。

依赖 M3（spawn/换区）/M6（图鉴）的 TC-11/12（意图预演）、TC-19（换区）、TC-20（验收）标 skip 注明。
"""
from __future__ import annotations

import json

import pytest

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.monster_ai import MonsterAI, CHARGING, ENRAGED, IDLE, IN_CHAIN, NORMAL

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50,
          "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 1000, "hp": 1000, "max_mp": 100, "mp": 100, "atk": 80, "dfn": 40,
         "mag": 30, "int": 30, "spd": 40, "foc": 50, "con": 50, "str": 80, "agi": 40,
         "spr": 40, "lck": 10, "elem_atk": 0, "pv": 300, "name": "E", "is_boss": False}

# 行动库（action.json 条目形态，T24 ActionCore + AI 字段，m2_shared_contract §四）
ACTION_LIB = {
    "claw_swipe": {"id": "claw_swipe", "kind": "active", "power": 1.2, "attack_type": "斩",
                   "tags": ["attack"]},
    "tail_sweep": {"id": "tail_sweep", "kind": "active", "power": 0.8, "attack_type": "打",
                   "tags": ["attack"]},
    "roar": {"id": "roar", "kind": "active", "power": 0.0, "attack_type": "魔",
             "tags": ["defense"]},
    "big_bite": {"id": "big_bite", "kind": "active", "power": 1.8, "attack_type": "斩",
                 "tags": ["attack"]},
    "fireball": {"id": "fireball", "kind": "active", "power": 1.6, "attack_type": "魔",
                 "tags": ["attack"]},
    "doomsday_breath": {"id": "doomsday_breath", "kind": "active", "power": 4.0,
                        "attack_type": "魔", "tags": ["attack"], "charge_turns": 2,
                        "charge_armor": True},
}


class ScriptedRng:
    """注入确定性 rng（AI 决策用，铁律 6）：按脚本序列循环返回 random()。"""

    def __init__(self, values):
        self._values = list(values)
        self.calls = 0

    def random(self):
        v = self._values[self.calls % len(self._values)] if self._values else 0.0
        self.calls += 1
        return v

    def choice(self, seq):
        return seq[int(self.random() * len(seq)) % len(seq)]


class QueueRNG:
    """战斗 rng（命中/会心/格挡/乱数）：0.5 命中(hit_rate≥0.5)且不格挡(br≤0.4)不暴击。"""

    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


# ------------------------------------------------------------------ 敌人配置（enemies.json 八段条目）

# TC-08：套内不评估（在途链推进时不切状态/不入强制队列）
ENEMY_A = {
    "id": "brute", "name": "蛮兽",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 40},
        {"action": "tail_sweep", "probability": 1, "weight": 20, "cooldown": 1},
        {"action": "roar", "probability": 1, "weight": 10, "cooldown": 3},
    ],
    "special_actions": [], "chains": [],
    "ai": {
        "states": {"enraged": {"enter_action": "roar", "weight_mod": {"attack": 1.5, "defense": 0.5}}},
        "transitions": [{"from": "normal", "to": "enraged", "condition": {"type": "hp_below", "value": 50}}],
    },
}

# TC-15：hungry 保底（big_bite hungry=3 → 第 3 回合强制选）
ENEMY_B = {
    "id": "hungry_wolf", "name": "饥饿狼",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 40},
        {"action": "big_bite", "probability": 1, "weight": 5, "hungry": 3, "cooldown": 2},
    ],
    "special_actions": [], "chains": [],
}

# TC-16：chain C roll（熔岩连招 火球 0.8 → 尾扫 1.0；强制队列引链）
ENEMY_C = {
    "id": "chain_boss", "name": "连招王",
    "actions": [
        {"action": "fireball", "probability": 1, "weight": 1, "cooldown": 1},
        {"action": "tail_sweep", "probability": 1, "weight": 1},
    ],
    "special_actions": [],
    "chains": [
        {"id": "molten", "cooldown": 2,
         "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"},
                     {"action": "tail_sweep", "chance": 1.0, "role": "finisher"}]},
    ],
}

# TC-18：蓄力跨回合（doomsday_breath charge_turns=2，hungry=1 强制起手）
ENEMY_D = {
    "id": "charge_drake", "name": "蓄力龙",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 1},
        {"action": "doomsday_breath", "probability": 1, "weight": 0, "hungry": 1},
    ],
    "special_actions": [], "chains": [],
    "ai": {
        "states": {"enraged": {"enter_action": "roar"}},
        "transitions": [{"from": "normal", "to": "enraged", "condition": {"type": "hp_below", "value": 50}}],
    },
}

# TC-17：打断=套完结（尾扫只在连招链内，随机池无尾扫）
ENEMY_E = {
    "id": "chain_boss", "name": "连招王",
    "actions": [
        {"action": "claw_swipe", "probability": 1, "weight": 1},
        {"action": "fireball", "probability": 1, "weight": 1, "cooldown": 2},
    ],
    "special_actions": [],
    "chains": [
        {"id": "molten", "cooldown": 2,
         "actions": [{"action": "fireball", "chance": 0.8, "role": "chain"},
                     {"action": "tail_sweep", "chance": 1.0, "role": "finisher"}]},
    ],
}

_INTERRUPT = {"type": "skill", "skill_id": "shield_bash", "tag": "interrupt",
              "effects": [{"type": "interrupt"}], "mult": 0.5}


def make_battle(enemy_def, ai_rng_values, seed=11, defs=None, enemy=ENEMY):
    """构造注入 MonsterAI 的战斗引擎（确定性：AI rng + 战斗 QueueRNG 双注入）。"""
    ai = MonsterAI(enemy_def, ACTION_LIB, ScriptedRng(ai_rng_values))
    eng = BattleEngine(enemy_ai=ai, defs=defs)
    eng._rng = QueueRNG([0.5] * 16)
    eng.start(PLAYER, dict(enemy), random_seed=seed)
    return eng


def last_enemy_record(eng):
    recs = [r for r in eng.battle_state()["action_record"] if r["actor"] == "enemy"]
    return recs[-1] if recs else None


# ================================================================== TC-08 套内不评估

def test_tc08_chain_inside_skips_eval():
    eng = make_battle(ENEMY_A, [0.5], seed=101)
    # 在途链：尾扫待执行；HP 40% < 50 —— 若评估会切 enraged
    eng._snap["enemy"]["hp"] = 400  # 40%
    eng._snap["ai_state"].update(chain_queue=["tail_sweep"], chain_id="c1",
                                 chain_pos=1, exec_state=IN_CHAIN)
    rep = eng.player_act("normal")
    # 套内：L0 推进尾扫照常执行（伤害通道），不切状态（TC-08 核心断言）
    enemy_out = rep.outcomes[1]
    assert enemy_out.action_type == "skill" and enemy_out.final_damage > 0
    assert last_enemy_record(eng)["rating"]["multi"] == 0.8  # 尾扫 power 0.8
    ai = eng.battle_state()["ai_state"]
    assert ai["state"] == NORMAL, "套内不切状态（TC-08）"
    assert ai["forced_queue"] == [], "套内不入强制队列"
    assert ai["chain_queue"] == [], "链走完清空"
    assert ai["exec_state"] == IDLE, "套结算完回 idle"
    # 下一回合（套间）：L1 评估 hp_below 50 → 切 enraged → enter_action roar 走 L2
    rep2 = eng.player_act("normal")
    ai2 = eng.battle_state()["ai_state"]
    assert ai2["state"] == ENRAGED, "套间切 enraged（TC-01 语义）"
    assert ai2["forced_queue"] == [] and ai2["action_cooldowns"].get("roar", 0) >= 1
    assert rep2.outcomes[1].action_type == "skill"


# ================================================================== TC-15 hungry 保底

def test_tc15_hungry_forced_pick():
    eng = make_battle(ENEMY_B, [0.001], seed=102)  # 恒选 claw（权重首位）
    ai = lambda: eng.battle_state()["ai_state"]
    # 第 1 回合：随机选 claw，big_bite 饥饿 +1
    eng.player_act("normal")
    assert last_enemy_record(eng)["rating"]["multi"] == 1.2  # claw 1.2
    assert ai()["hungry_count"]["big_bite"] == 1
    # 第 2 回合：仍 claw，big_bite 饥饿 2
    eng.player_act("normal")
    assert ai()["hungry_count"]["big_bite"] == 2
    # 第 3 回合：hungry=3 → count+1≥3 强制选 big_bite（TC-15）
    eng.player_act("normal")
    assert ai()["hungry_count"]["big_bite"] == 0, "选中后饥饿清零"
    assert ai()["action_cooldowns"].get("big_bite", 0) >= 1, "强制选中已记账（冷却登记）"
    assert last_enemy_record(eng)["rating"]["multi"] == 1.8  # big_bite 1.8


# ================================================================== TC-16 chain C roll

def test_tc16_chain_roll_success():
    eng = make_battle(ENEMY_C, [0.5], seed=103)  # 0.5 < 0.8 → roll 成功
    eng._snap["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    # 火球=链首节点本次执行；尾扫入队待 L0（套内确定性，TC-16）
    assert last_enemy_record(eng)["rating"]["multi"] == 1.6  # 火球 1.6
    assert ai["chain_queue"] == ["tail_sweep"], "roll 成功尾扫入队"
    assert ai["chain_id"] == "molten" and ai["exec_state"] == IN_CHAIN
    assert ai["chain_cooldowns"] == {}, "自然入队不设链冷却"
    # 第 2 回合：L0 链推进尾扫必接
    eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    assert ai["chain_queue"] == [] and ai["chain_id"] is None, "套内确定性执行完"
    assert ai["exec_state"] == IDLE


def test_tc16_chain_roll_fail_breaks():
    eng = make_battle(ENEMY_C, [0.9], seed=104)  # 0.9 ≥ 0.8 → roll 失败断链
    eng._snap["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    # 触发行动照常执行（火球），尾扫不接；断链 + 链冷却（TC-16）
    assert last_enemy_record(eng)["rating"]["multi"] == 1.6
    assert ai["chain_queue"] == [], "roll 失败不接尾扫"
    assert ai["chain_cooldowns"].get("molten", 0) >= 1, "断链 + 链冷却"
    # 下一回合走随机流程（不继续原套）
    eng.player_act("normal")
    assert eng.battle_state()["ai_state"]["chain_queue"] == []
    assert eng.battle_state()["ai_state"]["chain_id"] is None


# ================================================================== TC-17 打断=套完结

def test_tc17_interrupt_breaks_chain():
    eng = make_battle(ENEMY_E, [0.999], seed=105)  # 打断后随机池选 fireball（权重末位）
    eng._snap["ai_state"].update(chain_queue=["tail_sweep"], chain_id="molten",
                                 chain_pos=1, exec_state=IN_CHAIN)
    # 玩家 interrupt 命中怪物连招 → 套完结
    eng.do_action("player", dict(_INTERRUPT))
    ai = eng.battle_state()["ai_state"]
    assert ai["chain_queue"] == [], "打断清在途队列"
    assert ai["chain_id"] is None and ai["exec_state"] == IDLE
    assert ai["chain_cooldowns"].get("molten", 0) == 1, "当前链进冷却（防同链立即重触发）"
    assert eng.battle_state().get("combo_broken") is True, "combo_broken 标记（L3 可评估）"
    assert any(e.get("type") == "monster_chain_broken"
               for e in eng.battle_state().get("combo_events", []))
    # 后手：下一回合走随机流程 L6，不继续原套（尾扫只经链触发，随机池无尾扫）
    out = eng.enemy_act()
    assert out is not None and out.action_type == "skill"
    ai = eng.battle_state()["ai_state"]
    assert ai["chain_queue"] == [], "不继续原套"
    assert ai["action_cooldowns"].get("fireball", 0) == 2, "随机池选了 fireball（非尾扫）"
    assert "tail_sweep" not in ai["chain_queue"]


# ================================================================== TC-18 蓄力跨回合

def test_tc18_charge_cross_rounds():
    eng = make_battle(ENEMY_D, [0.0], seed=106)  # hungry=1 强制蓄力起手
    # 第 1 回合：蓄力起手播报 1/2，占行动槽不造成伤害
    rep = eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    assert ai["exec_state"] == CHARGING and rep.outcomes[1].final_damage == 0
    assert ai["charge"]["action_id"] == "doomsday_breath" and ai["charge"]["total"] == 2
    assert ai["charge"]["shown"] == 1 and ai["charge"]["armor"] is True
    # 第 2 回合：HP 跨 50% 阈值；套内门开启不评估（TC-18）
    eng._snap["enemy"]["hp"] = 400  # 40%
    rep = eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    assert ai["charge"]["shown"] == 2 and ai["exec_state"] == CHARGING
    assert ai["state"] == NORMAL, "蓄力期间不切状态（TC-18）"
    assert rep.outcomes[1].final_damage == 0
    # 第 3 回合：L0 蓄力结算释放行动本体（大伤害）
    hp0 = eng.battle_state()["player"]["hp"]
    rep = eng.player_act("normal")
    ai = eng.battle_state()["ai_state"]
    assert ai["charge"] is None, "释放后 charge 清空"
    assert rep.outcomes[1].action_type == "skill" and rep.outcomes[1].final_damage > 30
    assert eng.battle_state()["player"]["hp"] < hp0


# ================================================================== ai_state 快照往返（TC-12 核心机制）

def test_ai_state_snapshot_roundtrip():
    eng = make_battle(ENEMY_C, [0.5], seed=107)
    eng._snap["ai_state"]["forced_queue"] = [{"action": "fireball", "chain_ref": "molten"}]
    eng.player_act("normal")  # 火球触发 → 尾扫入队（在途链状态就位）
    # 额外塞入各冷却/饥饿字段，验证全字段往返
    eng._snap["ai_state"]["hungry_count"]["tail_sweep"] = 3
    eng._snap["ai_state"]["action_cooldowns"]["roar"] = 2
    eng._snap["ai_state"]["chain_cooldowns"]["other"] = 1
    ai_before = eng.battle_state()["ai_state"]
    assert ai_before["chain_queue"] == ["tail_sweep"]
    snap = eng.to_snapshot()  # 回合边界（player_act 已 end_turn → start_turn）
    data = json.loads(json.dumps(snap, ensure_ascii=False))  # 存档级 JSON 往返
    eng2 = BattleEngine.from_snapshot(
        data, enemy_ai=MonsterAI(ENEMY_C, ACTION_LIB, ScriptedRng([0.5])))
    ai_after = eng2.battle_state()["ai_state"]
    assert ai_after == ai_before, "ai_state 全字段随快照往返（中断续玩不丢）"
    # 续玩：还原引擎的后手仍能推进在途链（套进度不断）
    assert eng2.enemy_act() is not None
    assert eng2.battle_state()["ai_state"]["chain_queue"] == [], "续玩 L0 推进尾扫"


# ================================================================== M1 回归 / 注入路径

def test_enemy_act_fallback_normal_without_ai():
    """无 MonsterAI 注入 → M1 默认普攻反击保留（ai_state 保持空）。"""
    eng = BattleEngine()
    eng._rng = QueueRNG([0.5] * 16)
    eng.start(PLAYER, dict(ENEMY), random_seed=9)
    rep = eng.player_act("normal")
    assert rep.outcomes[1].action_type == "normal"
    assert eng.battle_state()["ai_state"] == {}


def test_enemy_def_autobuild_injection():
    """enemy_def 自动构造 MonsterAI（ai_action_lib 显式给行动库）。"""
    eng = BattleEngine(enemy_def=ENEMY_D, ai_action_lib=ACTION_LIB,
                       ai_rng=ScriptedRng([0.0]))
    eng._rng = QueueRNG([0.5] * 16)
    eng.start(PLAYER, dict(ENEMY), random_seed=7)
    rep = eng.player_act("normal")
    assert eng.battle_state()["ai_state"]["exec_state"] == CHARGING
    assert rep.outcomes[1].final_damage == 0  # 蓄力起手占行动槽


def test_ai_action_dict_shape_and_merge():
    """decide 产出 action_dict：形态/回灌/执行侧字段合并（attack_type 归一化）。"""
    eng = make_battle(ENEMY_A, [0.0], seed=5)  # r=0 → claw_swipe
    ad = eng._ai_action_dict()
    assert ad["type"] == "skill" and ad["skill_id"] == "claw_swipe"
    assert ad["mult"] == 1.2 and ad["kind"] == "active"
    assert ad["attack_type"] == "slash", "内容层 斩 → 伤害通道 slash 归一化"
    assert ad["action_id"] == "claw_swipe" and ad["source"] == "L6"
    # 回灌生效：ai_state 就位 contract §五 14 键（B2 monster_conditions 附加 trigger_counts/
    # trigger_used_once 为 additive 扩展键，快照整体透传，不破坏 14 键基线）
    ai = eng.battle_state()["ai_state"]
    assert {"state", "exec_state", "phase", "chain_pos", "chain_queue",
            "chain_id", "chain_cooldowns", "charge", "trigger_cooldowns",
            "action_cooldowns", "hungry_count", "intent", "forced_queue",
            "boss_phase"} <= set(ai)


# ================================================================== 依赖 M3/M6 的用例（标 skip 注明）

@pytest.mark.skip(reason="依赖 M6（图鉴）：TC-11 图鉴分级预演消息需 codex_state/图鉴解锁接线")
def test_tc11_codex_preview_skipped():
    pass


@pytest.mark.skip(reason="依赖 M6（图鉴）+ M3（spawn）：TC-12 中断恢复含预演消息渲染需图鉴/世界层")
def test_tc12_interrupt_restore_message_skipped():
    pass


@pytest.mark.skip(reason="依赖 M3（换区/世界边界）：TC-19 换区流程需 spawn/zone 接线（1g4 世界边界 C2）")
def test_tc19_zone_change_skipped():
    pass


@pytest.mark.skip(reason="依赖 M3/M6（完整 BOSS 战 + 图鉴 + 换区）：TC-20 验收判据全流程")
def test_tc20_acceptance_skipped():
    pass
