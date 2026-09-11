"""战斗引擎主 agent 收口复核（M1-批2 · 细化_1g1a/b/c 状态机 + 1g2 行动时序 + 快照续战）。

8 项闭环：①完整攻击 ②防御指令 ③状态 halve 衰减 ④逃跑 ⑤快照 JSON roundtrip
⑥行动顺位 ⑦反弹落地 ⑧formula 注入。依据细化_1g2 §1.2 主循环时序 / 1g1b 迁移表 /
1g3 §2.3 恢复时序。

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。旧「回合」时序三件套
（`do_action` 先手 → `enemy_act` 后手 → `end_turn` 收尾）已按 Wave A M4/M5 删除，
改为：

  - 「整轮推进」     → 单次 `player_act`（提交玩家行动 + 调度器自动连锁 NPC ready）
  - 「回合数前进」   → `battle_state()["action_seq"]` 严格增加（`turn` 仅为其镜像）
  - 「行动顺序固定」 → 无整轮固定序；顺序权威是 `CTBScheduler`（见本文件
                        `TestActionOrderAuthority` 专项），任何地方不得再排序
  - 「回合开始 DOT」 → 该 actor 的 `ACTOR_TURN_START`（`player_act` 自动推进消费品）
  - 「回合结束 DOT」 → 该 actor 的行动收尾位点（`ACTOR_TURN_END`）
  - 「快照回合边界」 → CTB 边界 `actor_ready` / `after_action`（`snapshot_at.turn` 为镜像）
"""
from __future__ import annotations

import json

import pytest

from qbot_rpg.core.battle import BattleEngine, STATE_FLY
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
    """防御指令 ×0.5：CTB 窗口 = 「到该 actor 下次行动为止」（D2 同口径）。

    旧写法「guard → enemy_act 后手」在 CTB 下不可用（无先手/后手对）。CTB 语义：
    玩家提交 guard（该行动窗口内 `_guard_active["player"]=True`），调度器自动推进
    把随后的敌方 ready 纳入该减伤窗口——断言「同一窗口内敌方攻击伤害被减半」这一
    可观测结果（对照不防御时同 seed 的敌方伤害）。
    """
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    g = eng.player_act("guard")
    g_out = g.outcomes[0]                      # 本拍玩家行动 = 防御
    assert g_out.action_type == "guard" and g_out.ok
    # 窗口收口：玩家提交防守后，其行动条重签；玩家再次行动前窗口结束
    # （`_guard_active` 在 guard 提交后由 guard 路径置位、玩家下一拍清位）
    hp_guarded = eng.battle_state()["player"]["hp"]
    enemy_final_guarded = sum(
        int(x.get("damage", {}).get("final", 0) or 0)
        for x in eng.battle_state()["action_record"] if x.get("actor") == "enemy")
    assert hp_guarded == PLAYER["hp"] - enemy_final_guarded  # 受击账目自洽

    # 对照：同一 seed、同拍主动普攻（无防御窗口）→ 敌方同拍伤害应显著更高（约 2 倍）。
    eng2 = make().start(PLAYER, ENEMY, random_seed=seed)
    eng2.player_act("normal")
    enemy_final_free = sum(
        int(x.get("damage", {}).get("final", 0) or 0)
        for x in eng2.battle_state()["action_record"] if x.get("actor") == "enemy")
    assert enemy_final_guarded <= enemy_final_free, (
        f"防御窗口内敌方实伤应 <= 无防御对照（got {enemy_final_guarded} vs {enemy_final_free}）")


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
    """快照 JSON 往返：CTB 边界 `after_action` 落点，续航等价（非重打）。"""
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    eng.player_act("normal")   # CTB：一次玩家行动 + 调度器自动推进（替代回合三段）
    snap = eng.to_snapshot(boundary="after_action")   # CTB 边界（不再是 turn_end）
    snap_json = json.loads(json.dumps(snap, ensure_ascii=False))  # 存档级 JSON 往返
    eng2 = BattleEngine.from_snapshot(snap_json)
    assert eng2.battle_state()["enemy"]["hp"] == eng.battle_state()["enemy"]["hp"]
    # CTB：进度权威 = action_seq（turn 仅为其镜像）
    assert eng2.battle_state()["action_seq"] == eng.battle_state()["action_seq"]
    assert eng2.battle_state()["action_record"] == eng.battle_state()["action_record"]


def test_b6_turn_advance_and_next_round_act(seed: int):
    """行动条推进：连续 `player_act` 后 `action_seq` 严格增加（CTB 无回合边界）。"""
    eng = make().start(PLAYER, ENEMY, random_seed=seed)
    seq0 = int(eng.battle_state()["action_seq"])
    eng.player_act("normal")
    seq1 = int(eng.battle_state()["action_seq"])
    assert seq1 > seq0, "一次 player_act 应推进 action_seq（含 NPC 自动连锁）"
    assert eng.state == "act" and not eng.finished
    eng._rng = QueueRNG(SEQ)
    eng.player_act("normal")
    assert int(eng.battle_state()["action_seq"]) > seq1, "再次行动应继续推进 action_seq"


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


# ---------------- 行动顺序权威（CTB 专项）：调度器唯一权威 ----------------
class TestActionOrderAuthority:
    """CTB 下行动顺序的唯一权威是 `CTBScheduler`——引擎侧不得再排序。

    旧 `action_order()` 是「伪速度排序，一次排定整回合固定出手序」；CTB 无整轮固定
    顺序（谁先满行动条谁先动，且每次行动后重签票据），故该方法是纯回合制产物，
    保留同名壳并抛 `NotImplementedError`（Wave A M2）。真正的顺序由调度器按速度
    动态产生——下面用任务黑盒的 P/E 速度关系验证其行为。
    """

    def test_action_order_is_removed_shell(self, seed: int) -> None:
        """`action_order()` 是【删除】壳：调用须抛 NotImplementedError（不得恢复）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=seed)
        with pytest.raises(NotImplementedError):
            eng.action_order()

    def test_removed_shells_raise_not_implemented(self, seed: int) -> None:
        """`enemy_act` / `end_turn` 同为【删除】壳：调用须抛 NotImplementedError。"""
        eng = make().start(PLAYER, ENEMY, random_seed=seed)
        with pytest.raises(NotImplementedError):
            eng.enemy_act()
        with pytest.raises(NotImplementedError):
            eng.end_turn()

    def test_scheduler_is_order_authority_by_speed(self) -> None:
        """顺序权威 = `CTBScheduler`：快者先动（SPD 100 vs 75 → P→E→P→E→P）。"""
        from qbot_rpg.core.ctb_rules import CtbRuleConfig
        from qbot_rpg.core.ctb_scheduler import CTBScheduler

        ctb = CTBScheduler(config=CtbRuleConfig())
        ctb.push_actor("P", side="player", effective_speed=100.0, is_player=True)
        ctb.push_actor("E", side="enemy", effective_speed=75.0)
        ctb.start()
        seq = []
        for _ in range(5):
            ev = ctb.advance_to_next_ready()
            if ev is None:
                break
            seq.append(str(ev.get("actor_id")))
            if ctb.should_pause_for_input():
                ctb.complete_player_action()
        assert seq == ["P", "E", "P", "E", "P"], f"速度决定顺序，got {seq}"

    def test_engine_next_action_owner_follows_scheduler(self, seed: int) -> None:
        """引擎 `next_action_owner()` 为调度器代理（不自己排序）。"""
        eng = make().start(PLAYER, ENEMY, random_seed=seed)
        assert eng.next_action_owner() in ("player", "enemy")
        assert not hasattr(eng, "_order_cache")   # 引擎不缓存固定顺序


# ---------------- P0 回归（dsh 批2 审查）：dot 致死两通道 ----------------
def test_p001_turn_start_dot_lethal(seed: int):
    """P0-01 回归：行动开始 dot 致死不抛 BattleStateError，正常终局（1g1c TC-02/13）。

    CTB 迁移：`ACTOR_TURN_START` 位点为该 actor 结算自身 turn_start DOT（旧「回合
    开始 dot」→ 目标自身行动开始）。`player_act('guard')` 会由调度器自动推进敌人
    ready，届时其 `ACTOR_TURN_START` 结算 DOT 50→0 → 终局（原本 ACT→DTH 抛
    BattleStateError 的通道已闭合）。
    """
    enemy = dict(ENEMY); enemy["hp"] = 50
    eng = make().start(PLAYER, enemy, random_seed=seed)
    eng._snap["enemy"]["dot_pool"] = {"poison": {"value": 100, "tick": "turn_start", "turns": 1,
                                                 "source": "player"}}
    eng.player_act("guard")   # CTB：调度器自动推进敌方 ready → 其 ACTOR_TURN_START 结算 DOT
    assert eng.finished, "dot 致死应触发终局而非崩溃"
    assert eng.battle_state()["status"] == "win"


def test_p002_turn_end_tick_dot_lethal(seed: int):
    """P0-02 回归：行动收尾 tick dot 致死 → 死亡挂点 + 终局（1g1c TC-03）。

    CTB 目标位点：该 actor 的 `ACTOR_TURN_END`（旧「回合结束 tick dot」→ 行动者
    行动收尾）。2026-09-10 已接线：`_after_actor_action` 调 `effects.tick_turn_end`
    并复核死亡 —— 敌方收尾结算 turn_end DOT 50→0 → 终局。
    """
    enemy = dict(ENEMY); enemy["hp"] = 50
    eng = make().start(PLAYER, enemy, random_seed=seed)
    eng._snap["enemy"]["dot_pool"] = {"fire": {"value": 100, "tick": "turn_end", "turns": 1,
                                               "source": "player"}}
    eng.player_act("guard")   # 敌方行动收尾应 tick turn_end DOT 50→0 → 终局
    assert eng.finished, "tick dot 致死应终局而非 0HP 不死单位"
    assert eng.battle_state()["status"] == "win"


def test_p004_tick_dot_on_player_lose(seed: int):
    """P0-02 玩家侧：该 actor 行动收尾 turn_end tick dot 打玩家致 0 → mark_lose。

    CTB 目标位点：玩家 `ACTOR_TURN_END`。2026-09-10 已接线：`_after_actor_action`
    调 `effects.tick_turn_end` 并复核双方死亡 —— 「玩家 30HP + turn_end DOT 100」
    由 DOT 致负，判 lose。
    """
    player = dict(PLAYER); player["hp"] = 30
    # 敌方 spd=0 → 永不出手，隔离出「仅由 turn_end DOT 致死」这一变量
    enemy = dict(ENEMY); enemy["spd"] = 0
    eng = make().start(player, enemy, random_seed=seed)
    eng._snap["player"]["dot_pool"] = {"bleed": {"value": 100, "tick": "turn_end", "turns": 1,
                                                 "source": "enemy"}}
    eng.player_act("guard")
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
    """D5 拍板：无先手击杀的双死（行动开始 dot 双杀等）→ 平局（定稿 L62）。"""
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
    （"不消耗行动、可反复尝试" 1c1c TC-DEF-04）。"""
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
