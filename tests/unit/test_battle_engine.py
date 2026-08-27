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


def test_b1_full_damage_loop(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    assert eng.state == "act" and eng.battle_state()["turn"] == 1
    out = eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert out.hit is True and out.action_type == "normal"
    assert out.raw_damage == out.final_damage  # 无拦截配置直通
    assert eng.battle_state()["enemy"]["hp"] == ENEMY["hp"] - out.raw_damage
    assert eng.battle_state()["action_record"][-1]["action"] == "normal"


def test_b2_guard_defense_command_halves(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    g = eng.do_action("player", {"type": "guard"})
    assert g.action_type == "guard" and g.ok
    assert eng.battle_state()["player"]["hp"] == PLAYER["hp"]  # 防御本回合不扣血
    raw_noguard, _ = total_damage(
        channel_phys(ENEMY["atk"],1.0,1.0,1.3,defense_factor(effective_con(PLAYER["con"],0))),  # type: ignore[arg-type]
        channel_elem(0,0,1.0,1.3,1.0), rng=1.0)
    eng._rng = QueueRNG(SEQ)
    out_en = eng.enemy_act()
    hp_g = eng.battle_state()["player"]["hp"]
    assert hp_g == PLAYER["hp"] - out_en.final_damage
    assert out_en.final_damage <= raw_noguard  # guard 减半生效（enemy_act 内部应用）


def test_b3_status_apply_and_halve_decay(seed: int):
    defs = {"atk_boost": {"id":"atk_boost","name":"强攻","class":"status","category":"enhance",
                          "stack_frame":"single","actions":[{"type":"stat_modifier","stat":"atk","value":"50%"}]}}
    eng = make(defs=defs).start(PLAYER, ENEMY, random_seed=seed)
    rt = eng._new_runtime()
    assert rt.apply_status("atk_boost", "player", force=True).applied
    eng._absorb_runtime(rt)
    inst = eng.battle_state()["status_state"]["player"][0]
    assert inst["status_id"] == "atk_boost" and inst["value"] == 50
    eng._snap["status_state"]["player"][0]["decay"] = "halve"
    eng._snap["status_state"]["player"][0]["value"] = 50
    tick_after_action(eng._snap, eng._new_runtime(), "player")
    assert eng._snap["status_state"]["player"][0]["value"] == 25  # halve 50->25（D5）


def test_b4_flee_ends_battle(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    out = eng.do_action("player", {"type": "flee"})
    assert out.action_type == "flee" and out.battle_ended
    assert eng.finished and eng.state == STATE_FLY
    assert eng.battle_state()["status"] == "escape"


def test_b5_snapshot_json_roundtrip(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    eng.enemy_act()
    eng.end_turn()  # 回合边界（1g3 快照只落回合边界）
    snap = eng.to_snapshot()
    snap_json = json.loads(json.dumps(snap, ensure_ascii=False))  # 存档级 JSON 往返
    eng2 = BattleEngine.from_snapshot(snap_json)
    assert eng2.battle_state()["enemy"]["hp"] == eng.battle_state()["enemy"]["hp"]
    assert eng2.battle_state()["turn"] == eng.battle_state()["turn"]
    assert eng2.battle_state()["action_record"] == eng.battle_state()["action_record"]


def test_b6_turn_advance_and_next_round_act(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()  # 内部 ⑨ 自动 start_turn 进入下一回合（turn+1、state=act）
    assert eng.battle_state()["turn"] == 2 and eng.state == "act"
    eng._rng = QueueRNG(SEQ)
    out2 = eng.do_action("enemy", {"type": "normal", "mult": 1.0})
    assert out2.hit is True


def test_b7_reflect_lands_on_attacker(seed: int):
    # 走真实装配（F-21 prepare_defense）：effect type=reflect -> defenses.reflect（P1-01 后手动注入会被每段刷新洗掉）
    refl = {"id": "refl", "name": "反伤", "class": "effect", "type": "reflect",
            "actions": [{"type": "reflect", "value": 20, "pct": True}]}
    eng = make(defs={"refl": refl}).start(PLAYER, ENEMY, random_seed=seed)
    eng.set_effect_ids("enemy", ["refl"])  # 触发 _refresh_defenses 折叠
    hp0 = eng.battle_state()["player"]["hp"]
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    hp1 = eng.battle_state()["player"]["hp"]
    assert hp1 < hp0  # 反弹伤害已回注玩家（F-22 落地）


def test_b8_formula_injection(seed: int):
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    fn = eng._make_eval_formula()
    assert fn("[我方攻击]*2+10") == 210.0


# ---------------- P0 回归（dsh 批2 审查）：dot 致死两通道 ----------------
def test_p001_turn_start_dot_lethal(seed: int):
    """P0-01 回归：回合开始 dot 致死不抛 BattleStateError，正常终局（1g1c TC-02/13）。"""
    enemy = dict(ENEMY); enemy["hp"] = 50
    eng = make().start(PLAYER, enemy, random_seed=seed)   # 回合1 ACT（start_turn 已跑，无 dot）
    eng._snap["enemy"]["dot_pool"] = {"poison": {"value": 100, "tick": "turn_start", "turns": 1,
                                                 "source": "player"}}
    # 走完整一轮：guard（玩家不攻击避免打死）-> 敌后手 -> end_turn 内部 start_turn（回合2）
    # ① turn_start dot 打 enemy 50->0 -> 死亡挂点（原 ACT->DTH 抛 BattleStateError）
    eng.do_action("player", {"type": "guard"})
    eng.enemy_act()
    eng.end_turn()
    assert eng.finished, "dot 致死应触发终局而非崩溃"
    assert eng.battle_state()["status"] == "win"


def test_p002_turn_end_tick_dot_lethal(seed: int):
    """P0-02 回归：回合结束 tick dot 致死 → 死亡挂点 + 终局（1g1c TC-03，死不穿透回合边界）。"""
    enemy = dict(ENEMY); enemy["hp"] = 50
    eng = make().start(PLAYER, enemy, random_seed=seed)
    eng._snap["enemy"]["dot_pool"] = {"fire": {"value": 100, "tick": "turn_end", "turns": 1,
                                               "source": "player"}}
    rep = eng.end_turn()   # tick 内 dot -> 50 -> 0 -> 死亡挂点（原 HP=0 不死单位死锁）
    assert eng.finished, "tick dot 致死应终局而非 0HP 不死单位"
    assert eng.battle_state()["status"] == "win"


def test_p004_tick_dot_on_player_lose(seed: int):
    """P0-02 玩家侧：回合结束 tick dot 打玩家致 0 → mark_lose（原玩家死锁）。"""
    player = dict(PLAYER); player["hp"] = 30
    eng = make().start(player, ENEMY, random_seed=seed)
    eng._snap["player"]["dot_pool"] = {"bleed": {"value": 100, "tick": "turn_end", "turns": 1,
                                                 "source": "enemy"}}
    rep = eng.end_turn()
    assert eng.finished and eng.battle_state()["status"] == "lose"


def test_r09_monster_def_rate_per_monster(seed: int):
    """R-09 拍板：怪物防御率每怪可配（enemy.monster_def_rate）——0.5 时玩家伤害约减半
    （定稿 L27/L32 公式因子「× 怪物防御率」：0.5=怪物受一半伤害/防御高；默认 1.0）。"""
    enemy2 = dict(ENEMY); enemy2["monster_def_rate"] = 0.5
    eng2 = make().start(PLAYER, enemy2, random_seed=seed)
    out2 = eng2.do_action("player", {"type": "normal", "mult": 1.0})
    eng1 = make().start(PLAYER, dict(ENEMY), random_seed=seed)   # 缺省 1.0
    out1 = eng1.do_action("player", {"type": "normal", "mult": 1.0})
    # 双通道各自 floor → 总伤害约 50%（允许 floor 累计误差 ±2）
    assert abs(out2.raw_damage * 2 - out1.raw_damage) <= 2, (out1.raw_damage, out2.raw_damage)


def test_g2_flee_rate_uses_agi(seed: int):
    """G2（定稿对照）：逃跑成功率 = 敏捷比 agi/(agi+敌agi)（玩家属性定稿 L185）——
    玩家敏捷远低于敌时（20 vs 200 → ~9%）roll 0.5 失败、战斗继续。"""
    player = dict(PLAYER); player["agi"] = 20
    enemy = dict(ENEMY); enemy["agi"] = 200
    eng = make().start(player, enemy, random_seed=seed)
    out = eng.do_action("player", {"type": "flee"})
    assert out.action_type == "flee" and out.battle_ended is False
    assert eng.finished is False and eng.battle_state()["status"] != "escape"


def test_g4_mutual_kill_order_tc11_first_strike_wins(seed: int):
    """D5 拍板（用户 2026-08-19 / 1g1c TC-11）：互杀 + 先手击杀生效 → 先手胜
    （玩家先手击杀怪物即使同归于尽也判玩家胜利）。"""
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng._snap["result"]["mark_lose"] = True              # 玩家亦死（被反弹/反伤）
    eng._snap["result"]["mark_win"] = True               # 敌人死
    eng._snap["result"]["player_killed_enemy"] = True    # 先手击杀生效
    out = eng._resolve_battle_end(force=True)
    assert out is not None and out.status == "win", out


def test_g4_dot_double_kill_draw(seed: int):
    """D5 拍板：无先手击杀的双死（回合开始 dot 双杀等）→ 平局（定稿 L62）。"""
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng._snap["result"]["mark_lose"] = True
    eng._snap["result"]["mark_win"] = True
    eng._snap["result"]["player_killed_enemy"] = False
    out = eng._resolve_battle_end(force=True)
    assert out is not None and out.status == "draw", out


def test_g4_mutual_hp_ratio_higher_predeath_wins(seed: int):
    """G4：hp_ratio 基准用「致死前一刻」HP 比（定稿 L63）——致死前 HP 占比高者胜。"""
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng._snap["result"]["mark_lose"] = True
    eng._snap["result"]["mark_win"] = True
    eng._snap["player"]["_hp_before_death"] = 400        # 致死前 400/500 = 80%
    eng._snap["enemy"]["_hp_before_death"] = 100         # 致死前 100/400 = 25%
    eng._snap["_guard_active"] = {"player": False, "enemy": False}
    eng._config["mutual_kill_basis"] = "hp_ratio"
    out = eng._resolve_battle_end(force=True)
    assert out is not None and out.status == "win", out


# ---------------- dsh 批3 审查修复回归（审查_M1_batch3） ----------------
def test_p1_marks_cleared_on_battle_end(seed: int):
    """P1-2 回归：战斗结束/逃跑成功 marks_state 与连段双轴一致清零（1d §2.3/AT-07）。"""
    from qbot_rpg.core.marks import AddMark
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng.marks_manager().apply_add(AddMark(side="enemy", mark="火印", count=2))
    assert eng.marks_manager().count("enemy", "火印") == 2
    eng.do_action("player", {"type": "flee"})   # 敏捷 50 vs 40 → 55%；roll 0.5 成功
    assert eng.finished
    assert eng.battle_state()["marks_state"]["enemy"] == []


def test_p1_rejected_keeps_act_and_no_turn(seed: int):
    """P1-5 回归：指令被拒（MP 不足）→ 状态保持 ACT、不改连段、_turn_acted 回滚
    （"不耗回合、可反复尝试" 1c1c TC-DEF-04）。"""
    _chain = {"id": "c1", "name": "试链", "trigger_skill": "a", "max_combo": 3,
              "max_combo_behavior": "reset", "steps": []}
    _skill = {"a": {"id": "a", "name": "火球", "tag": "combo", "mp_cost": 100}}
    player = dict(PLAYER); player["mp"] = 0
    eng = BattleEngine(defs={"c1": _chain, **_skill}, config={"combo_enforce_mp": True})
    eng._rng = QueueRNG([0.5, 0.5, 0.5, 1.0])  # type: ignore[assignment]
    eng.start(player, ENEMY, random_seed=seed)
    out = eng.do_action("player", {"type": "skill", "skill_id": "a", "tag": "combo", "mult": 1.0})
    assert out.ok is False, "MP 不足应被拒"
    assert eng.state == "act", "被拒后状态保持 ACT（可反复尝试）"
    assert eng.battle_state()["combo_state"].get("player", {}).get("count", 0) == 0, "不改连段"
    assert eng.battle_state()["player"]["mp"] == 0, "不耗 MP"
