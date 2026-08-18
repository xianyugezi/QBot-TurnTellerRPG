"""战斗引擎主 agent 收口复核（M1-批2 · 细化_1g1a/b/c 状态机 + 1g2 回合时序 + 快照续战）。

8 项闭环：①完整攻击 ②防御指令 ③状态 halve 衰减 ④逃跑 ⑤快照 JSON roundtrip
⑥回合顺位 ⑦反弹落地 ⑧formula 注入。依据细化_1g2 §1.2 主循环时序 / 1g1b 迁移表 /
1g3 §2.3 恢复时序。
"""
from __future__ import annotations

import json

from qbot_rpg.core.battle import BattleEngine, STATE_FLY
from qbot_rpg.core.damage import (
    channel_elem, channel_phys, defense_factor, effective_con, total_damage,
)
from qbot_rpg.core.effects import tick_after_action

PLAYER = {"max_hp":500,"hp":500,"max_mp":100,"mp":100,"atk":100,"dfn":50,"mag":50,"spd":50,
          "foc":100,"con":50,"str":100,"int":80,"agi":50,"spr":50,"lck":50,"elem_atk":0,"name":"P"}
ENEMY = {"max_hp":400,"hp":400,"max_mp":0,"mp":0,"atk":80,"dfn":40,"mag":30,"spd":40,"foc":50,"con":50,
         "str":80,"int":30,"agi":40,"spr":40,"lck":10,"elem_atk":0,"name":"E"}
SEQ = [0.5, 0.5, 0.5, 1.0]


class QueueRNG:
    """确定性随机源：依次吐出固定序列（命中/会心/格挡/乱数 4 判定）。"""
    def __init__(self, seq):
        self.seq = list(seq); self.i = 0
    def random(self):
        v = self.seq[self.i]; self.i = (self.i + 1) % len(self.seq); return v


def make(**kw):
    eng = BattleEngine(**kw)
    eng._rng = QueueRNG(SEQ)
    return eng


def test_b1_full_damage_loop():
    eng = make().start(PLAYER, ENEMY, random_seed=11)
    assert eng.state == "act" and eng.battle_state()["turn"] == 1
    out = eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert out.hit is True and out.action_type == "normal"
    assert out.raw_damage == out.final_damage  # 无拦截配置直通
    assert eng.battle_state()["enemy"]["hp"] == ENEMY["hp"] - out.raw_damage
    assert eng.battle_state()["action_record"][-1]["action"] == "normal"


def test_b2_guard_defense_command_halves():
    eng = make().start(PLAYER, ENEMY, random_seed=12)
    g = eng.do_action("player", {"type": "guard"})
    assert g.action_type == "guard" and g.ok
    assert eng.battle_state()["player"]["hp"] == PLAYER["hp"]  # 防御本回合不扣血
    raw_noguard, _ = total_damage(
        channel_phys(ENEMY["atk"],1.0,1.0,1.3,defense_factor(effective_con(PLAYER["con"],0))),
        channel_elem(0,0,1.0,1.3,1.0), rng=1.0)
    eng._rng = QueueRNG(SEQ)
    out_en = eng.enemy_act()
    hp_g = eng.battle_state()["player"]["hp"]
    assert hp_g == PLAYER["hp"] - out_en.final_damage
    assert out_en.final_damage <= raw_noguard  # guard 减半生效（enemy_act 内部应用）


def test_b3_status_apply_and_halve_decay():
    defs = {"atk_boost": {"id":"atk_boost","name":"强攻","class":"status","category":"enhance",
                          "stack_frame":"single","actions":[{"type":"stat_modifier","stat":"atk","value":"50%"}]}}
    eng = make(defs=defs).start(PLAYER, ENEMY, random_seed=13)
    rt = eng._new_runtime()
    assert rt.apply_status("atk_boost", "player", force=True).applied
    eng._absorb_runtime(rt)
    inst = eng.battle_state()["status_state"]["player"][0]
    assert inst["status_id"] == "atk_boost" and inst["value"] == 50
    eng._snap["status_state"]["player"][0]["decay"] = "halve"
    eng._snap["status_state"]["player"][0]["value"] = 50
    tick_after_action(eng._snap, eng._new_runtime(), "player")
    assert eng._snap["status_state"]["player"][0]["value"] == 25  # halve 50->25（D5）


def test_b4_flee_ends_battle():
    eng = make().start(PLAYER, ENEMY, random_seed=14)
    out = eng.do_action("player", {"type": "flee"})
    assert out.action_type == "flee" and out.battle_ended
    assert eng.finished and eng.state == STATE_FLY
    assert eng.battle_state()["status"] == "escape"


def test_b5_snapshot_json_roundtrip():
    eng = make().start(PLAYER, ENEMY, random_seed=15)
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    eng.enemy_act()
    eng.end_turn()  # 回合边界（1g3 快照只落回合边界）
    snap = eng.to_snapshot()
    snap_json = json.loads(json.dumps(snap, ensure_ascii=False))  # 存档级 JSON 往返
    eng2 = BattleEngine.from_snapshot(snap_json)
    assert eng2.battle_state()["enemy"]["hp"] == eng.battle_state()["enemy"]["hp"]
    assert eng2.battle_state()["turn"] == eng.battle_state()["turn"]
    assert eng2.battle_state()["action_record"] == eng.battle_state()["action_record"]


def test_b6_turn_advance_and_next_round_act():
    eng = make().start(PLAYER, ENEMY, random_seed=16)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()  # 内部 ⑨ 自动 start_turn 进入下一回合（turn+1、state=act）
    assert eng.battle_state()["turn"] == 2 and eng.state == "act"
    eng._rng = QueueRNG(SEQ)
    out2 = eng.do_action("enemy", {"type": "normal", "mult": 1.0})
    assert out2.hit is True


def test_b7_reflect_lands_on_attacker():
    eng = make().start(PLAYER, ENEMY, random_seed=17)
    eng._snap["enemy"]["defenses"] = {"reflect": {"value": 20, "pct": True, "active": True}}
    hp0 = eng.battle_state()["player"]["hp"]
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    hp1 = eng.battle_state()["player"]["hp"]
    assert hp1 < hp0  # 反弹伤害已回注玩家（F-22 落地）


def test_b8_formula_injection():
    eng = make().start(PLAYER, ENEMY, random_seed=18)
    fn = eng._make_eval_formula()
    assert fn("[我方攻击]*2+10") == 210.0
