"""怒·三态 + 疲劳（怪猎采纳 #4/#5）验收测试——2026-09-12 批⑦B 实装。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md 附录 C §3-4 + §四）：
  - **双轴驱动**：怒值（受击积累 `rage_per_damage`）/ 耐力（打击减气 `stamina_drain_blunt`
    + 行动边界回复 `stamina_regen_per_action`）；全部数值隐性、可配。
  - **三态状态机**：常态/怒/疲劳经内容 `ai.states` + `ai.transitions` 驱动，条件类型
    `enemy_axis`（key/op/value）；怒态入场动作（咆哮演出）、权重修正（weight_mod）。
  - **怒**：敌方增伤（enrage_damage_mult）+ 提速（enrage_recovery_mult）；冷却计数器
    rage_cool（怪的行动次数）到期退出；怒态期间怒气清零（退出后重新积累）。
  - **疲劳**：耐力归零进入；拖慢（fatigue_recovery_mult）+ 行动自摔概率
    （fatigue_stagger_chance，0=关）；耐力回升到阈值（内容条件 24）退出。

铁律：零 NoneBot import；确定性（_QR 固定序列）；真跑断言；期望值由内容/配置推导。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.battle_config import resolve_battle_settings
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.message_format.battle_render import (
    _render_enemy_action,
    _render_state_lines,
)
from qbot_rpg.core.monster_ai import MonsterAI
from qbot_rpg.core.templates import tpl_of


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i % len(self.seq)]
        self.i += 1
        return v


def _pack():
    pack, _ = build_pack(Path("content/veinborn"))
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(
        defs={**all_defs, **chains},
        resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
    )
    return raw, all_defs, ce


_PLAYER = {
    "max_hp": 99999, "hp": 99999, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 100, "mag": 10,
}


def _fresh(*, config=None, enemy_id="wasteland_lord", with_ai=True):
    """荒原领主（无 special_actions 干扰）+ 隔离时间轴：怪 spd=1（拍极晚，不会自然插入）。"""
    raw, all_defs, ce = _pack()
    et = dict(next(e for e in raw["enemies"] if e["id"] == enemy_id))
    mob = {
        "id": et["id"], "hp": 99999, "max_hp": 99999, "mp": 0,
        "atk": 10, "dfn": 10, "mag": 0, "spd": 1, "foc": 0, "lck": 0,
        "con": 10, "agi": 0, "name": et["name"],
    }
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.5] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    if with_ai:
        ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                       rng=_QR([0.1] * 800))
        eng._enemy_ai = ai
    eng._snap.setdefault("ai_state", {})
    return eng, raw


def _set_state(eng, state):
    eng._snap.setdefault("ai_state", {})["state"] = state


def _fx_types(out):
    return [str(e.get("type")) for e in (out.side_effects or ())]


# =====================================================================================
# 1. 双轴积累 / 消耗 / 回复
# =====================================================================================


def test_rage_accumulates_from_damage():
    """受击怒气积累 = 伤害 × rage_per_damage（显式 1.0 便于断言）。"""
    eng, _ = _fresh(config={"rage_per_damage": 1.0})
    out = eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert out.final_damage > 0
    assert eng._enemy_axis()["rage"] == float(out.final_damage)


def test_rage_frozen_while_enraged():
    """怒态期间怒气清零且不积累（退出后从零重来）。"""
    eng, _ = _fresh(config={"rage_per_damage": 1.0})
    _set_state(eng, "enraged")
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert eng._enemy_axis()["rage"] == 0.0


def test_stamina_blunt_drain_and_regen():
    """打击命中 -stamina_drain_blunt；行动边界 +stamina_regen_per_action（含同拍）。"""
    eng, _ = _fresh()
    eng._enemy_axis()["stamina"] = 60.0
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})  # 打击
    drain = eng._cfg_float("stamina_drain_blunt", 6.0)
    regen = eng._cfg_float("stamina_regen_per_action", 1.2)
    assert abs(eng._enemy_axis()["stamina"] - (60.0 - drain + regen)) < 1e-6
    # 非打击（普攻=slash）只回不耗
    before = eng._enemy_axis()["stamina"]
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert abs(eng._enemy_axis()["stamina"] - min(60.0, before + regen)) < 1e-6


def test_stamina_regen_per_action_configurable():
    """回复率可配：2.0 → 单动作 +2。"""
    eng, _ = _fresh(config={"stamina_regen_per_action": 2.0})
    eng._enemy_axis()["stamina"] = 10.0
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert abs(eng._enemy_axis()["stamina"] - 12.0) < 1e-6


# =====================================================================================
# 2. 转场（enemy_axis 条件驱动）与怒态合奏
# =====================================================================================


def test_transition_to_enraged_with_enter_action():
    """怒值达阈值 → 转场 enraged：强制队列出咆哮（enter_action）+ 状态事件透出。"""
    eng, _ = _fresh()
    eng._enemy_axis()["rage"] = 300.0
    ad = eng._ai_action_dict()
    assert ad is not None
    assert (eng._snap.get("ai_state") or {}).get("state") == "enraged"
    assert ad.get("skill_id") == "al_roar", "怒态入场动作应为咆哮"
    ev = ad.get("enemy_state_event") or {}
    assert ev.get("state") == "enraged" and ev.get("prev") == "normal"


def test_enraged_recovery_and_damage_mult():
    """怒态提速（×0.8 恢复）+ 增伤（×1.15），均可配。

    驱动口径：怪物行动经 AI 路径时 mult=行动 def power（十进制倍率，1.3=130%）；
    测试直驱须显式带 mult（缺省会走玩家技能口径的 /100 折算）。
    """
    _raw, all_defs, _ce = _pack()
    _mult = float(all_defs["al_quake"].get("power") or 1.0)
    act = {"type": "skill", "skill_id": "al_quake", "mult": _mult}
    eng_e, _ = _fresh()
    _set_state(eng_e, "enraged")
    eng_n, _ = _fresh()
    rec_e = eng_e._action_recovery("enemy", dict(act))
    rec_n = eng_n._action_recovery("enemy", dict(act))
    assert abs(rec_e / rec_n - 0.8) < 1e-6
    out_e = eng_e.do_action("enemy", dict(act))
    out_n = eng_n.do_action("enemy", dict(act))
    ratio = out_e.final_damage / max(1, out_n.final_damage)
    assert 1.05 <= ratio <= 1.25, f"怒态增伤比率异常：{ratio:.3f}"
    # 关闭（1.0）→ 同伤害
    eng_o, _ = _fresh(config={"enrage_damage_mult": 1.0})
    _set_state(eng_o, "enraged")
    out_o = eng_o.do_action("enemy", dict(act))
    eng_p, _ = _fresh(config={"enrage_damage_mult": 1.0})
    out_p = eng_p.do_action("enemy", dict(act))
    assert out_o.final_damage == out_p.final_damage


def test_enrage_cool_countdown_and_exit():
    """怒态冷却按怪的行动次数递减 → 到期转回常态（recovered 事件）。"""
    eng, _ = _fresh(config={"rage_cool_actions": 2})
    _set_state(eng, "enraged")
    eng._tick_enemy_axis("enemy")   # 初始化 2 → 1
    assert eng._enemy_axis()["rage_cool"] == 1
    eng._tick_enemy_axis("enemy")   # 1 → 0
    assert eng._enemy_axis()["rage_cool"] == 0
    ad = eng._ai_action_dict()
    assert (eng._snap.get("ai_state") or {}).get("state") == "normal"
    ev = ad.get("enemy_state_event") or {}
    assert ev.get("state") == "normal", "退出怒态应透出 recovered 事件"


def test_enrage_not_exit_before_cool_init():
    """回归守卫：入场后冷却未初始化（None）不得被 <=0 条件误判退出。"""
    eng, _ = _fresh()
    eng._enemy_axis()["rage"] = 300.0
    eng._ai_action_dict()  # 进入怒态（cool 尚未 tick）
    ad = eng._ai_action_dict()  # 再决策一次
    assert (eng._snap.get("ai_state") or {}).get("state") == "enraged"
    assert ad is not None


# =====================================================================================
# 3. 疲劳：拖慢 / 自摔 / 恢复
# =====================================================================================


def test_transition_to_fatigued():
    """耐力归零 → 疲劳（无入场动作，weight_mod 生效）。"""
    eng, _ = _fresh()
    eng._enemy_axis()["stamina"] = 0.0
    ad = eng._ai_action_dict()
    assert (eng._snap.get("ai_state") or {}).get("state") == "fatigued"
    ev = ad.get("enemy_state_event") or {}
    assert ev.get("state") == "fatigued"


def test_fatigue_recovery_mult_and_exit():
    """疲劳拖慢（×1.25）；耐力回升到阈值（24）→ 退出。"""
    eng, _ = _fresh()
    _set_state(eng, "fatigued")
    rec_f = eng._action_recovery("enemy", {"type": "skill", "skill_id": "al_quake"})
    eng_n, _ = _fresh()
    rec_n = eng_n._action_recovery("enemy", {"type": "skill", "skill_id": "al_quake"})
    assert abs(rec_f / rec_n - 1.25) < 1e-6
    eng._tick_enemy_axis("enemy")   # 生产同款记账：让 state_seen 跟上 fatigued
    eng._enemy_axis()["stamina"] = 30.0
    ad = eng._ai_action_dict()
    assert (eng._snap.get("ai_state") or {}).get("state") == "normal"
    ev = ad.get("enemy_state_event") or {}
    assert ev.get("state") == "normal"


def test_fatigue_stagger():
    """疲劳自摔：概率命中 → 本次行动作废（事件 + 零伤害）；0=关回归正常。"""
    eng, _ = _fresh(config={"fatigue_stagger_chance": 1.0})
    _set_state(eng, "fatigued")
    hp_before = eng._combat("player").get("hp")
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "al_quake"})
    assert "fatigue_stagger" in _fx_types(out)
    assert out.final_damage == 0
    assert eng._combat("player").get("hp") == hp_before
    eng2, _ = _fresh(config={"fatigue_stagger_chance": 0.0})
    _set_state(eng2, "fatigued")
    out2 = eng2.do_action("enemy", {"type": "skill", "skill_id": "al_quake"})
    assert "fatigue_stagger" not in _fx_types(out2)
    assert out2.final_damage > 0


def test_axis_condition_handler_defaults():
    """enemy_axis 条件求值：缺省口径（stamina/rage_cool 视为未到期 → 不误触发）。"""
    _raw, all_defs, _ce = _pack()
    et = next(e for e in _raw["enemies"] if e["id"] == "wasteland_lord")
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i), rng=_QR([0.5]))
    bs = {"enemy_axis": {}}
    cond = ai._eval_condition
    assert cond({"type": "enemy_axis", "key": "stamina", "op": "<=", "value": 0}, bs) is False
    assert cond({"type": "enemy_axis", "key": "rage_cool", "op": "<=", "value": 0}, bs) is False
    assert cond({"type": "enemy_axis", "key": "rage", "op": ">=", "value": 1}, bs) is False
    bs2 = {"enemy_axis": {"stamina": 0.0, "rage": 300.0, "rage_cool": 0}}
    assert cond({"type": "enemy_axis", "key": "stamina", "op": "<=", "value": 0}, bs2) is True
    assert cond({"type": "enemy_axis", "key": "rage", "op": ">=", "value": 260}, bs2) is True
    assert cond({"type": "enemy_axis", "key": "rage_cool", "op": "<=", "value": 0}, bs2) is True
    assert cond({"type": "enemy_axis", "key": "rage", "op": ">", "value": 400}, bs2) is False


# =====================================================================================
# 4. 渲染 / 模板
# =====================================================================================


def test_render_state_lines():
    """状态切换行：被激怒 / 迟滞 / 稳住 三分支。"""
    base = dict(attacker_name="测试怪")
    t1 = "\n".join(_render_state_lines(SimpleNamespace(
        side_effects=({"type": "enemy_state", "state": "enraged", "target": "enemy"},), **base)))
    assert "被激怒了" in t1
    t2 = "\n".join(_render_state_lines(SimpleNamespace(
        side_effects=({"type": "enemy_state", "state": "fatigued", "target": "enemy"},), **base)))
    assert "迟滞" in t2
    t3 = "\n".join(_render_state_lines(SimpleNamespace(
        side_effects=({"type": "enemy_state", "state": "normal", "target": "enemy"},), **base)))
    assert "稳住" in t3


def test_render_fatigue_stagger_line():
    """自摔行渲染（替代伤害行）。"""
    out = SimpleNamespace(
        side_effects=({"type": "fatigue_stagger", "actor": "enemy"},),
        attacker_name="测试怪", action_type="skill", hit=False, final_damage=0)
    text = _render_enemy_action(out)
    assert text and "腿下一软" in text


def test_render_roar_with_damage_shows_damage_line():
    """兼带伤害的咆哮：咆哮行 + 伤害行并存（批⑦B 顺序修正回归）。"""
    out = SimpleNamespace(
        side_effects=({"type": "roar", "level": 2, "combo": False},),
        attacker_name="测试怪", action_type="skill", hit=True, final_damage=77,
        target_hp=800, player_max_hp=900)
    text = _render_enemy_action(out)
    assert "仰天咆哮" in text
    assert "77" in text, f"伤害行应并存：{text!r}"


def test_templates_registered_b():
    """四条新模板可渲染。"""
    assert "被激怒" in tpl_of(None, "battle_state_enraged", {"name": "X"})
    assert "迟滞" in tpl_of(None, "battle_state_fatigued", {"name": "X"})
    assert "稳住" in tpl_of(None, "battle_state_recovered", {"name": "X"})
    assert "腿下一软" in tpl_of(None, "battle_fatigue_stagger", {"name": "X"})


# =====================================================================================
# 5. 配置白名单 / 内容守卫
# =====================================================================================


def test_battle_settings_sanitize_b():
    """settings["battle"] 段 B 键：合法透传、坏值忽略。"""
    good = {"rage_per_damage": 0.5, "rage_cool_actions": 4, "stamina_max": 80,
            "stamina_drain_blunt": 7, "stamina_regen_per_action": 2,
            "enrage_damage_mult": 1.2, "enrage_recovery_mult": 0.9,
            "fatigue_recovery_mult": 1.4, "fatigue_stagger_chance": 0.2}
    out = resolve_battle_settings({"battle": dict(good)})
    assert out == {**good, "rage_per_damage": 0.5, "stamina_max": 80.0,
                   "stamina_drain_blunt": 7.0, "stamina_regen_per_action": 2.0,
                   "enrage_damage_mult": 1.2, "enrage_recovery_mult": 0.9,
                   "fatigue_recovery_mult": 1.4, "fatigue_stagger_chance": 0.2}
    bad = resolve_battle_settings({"battle": {
        "rage_cool_actions": 0, "enrage_damage_mult": 0.001,
        "fatigue_stagger_chance": 2, "stamina_max": -1}})
    assert bad == {}


def test_engine_defaults_b():
    """引擎缺省即带工作机制值（内容未配 ai 段时自然静默）。"""
    eng, _ = _fresh()
    assert eng._cfg_float("rage_per_damage", 0) == 0.35
    assert eng._cfg_int("rage_cool_actions", 0) == 6
    assert eng._cfg_float("stamina_max", 0) == 60.0
    assert eng._cfg_float("enrage_damage_mult", 0) == 1.15
    assert eng._cfg_float("enrage_recovery_mult", 0) == 0.8
    assert eng._cfg_float("fatigue_recovery_mult", 0) == 1.25
    assert eng._cfg_float("fatigue_stagger_chance", -1) == 0.12


def test_boss_starts_phase_1_and_phase_unit_guard():
    """回归守卫（存量 bug 修复）：相位阈值 = 百分比口径（≥2，防小数混入曾致全怪恒第 3
    阶段）；全血开战 → 阶段 1（不在开局误入末阶段）。"""
    eng, _ = _fresh()
    ad = eng._ai_action_dict()
    assert ad is not None
    assert (eng._snap.get("ai_state") or {}).get("phase") == 1
    raw, _, _ = _pack()
    for e in raw["enemies"]:
        for p in e.get("phases") or []:
            thr = p.get("threshold")
            assert isinstance(thr, (int, float)) and not isinstance(thr, bool), (e["id"], thr)
            assert thr >= 2, f"{e['id']} 相位阈值疑为小数口径：{thr}"


def test_content_guard_b():
    """内容守卫：8 怪 ai 段（states/transitions/入场动作）+ 阈值与咆哮接线一致。"""
    raw, _, _ = _pack()
    enemies = {e["id"]: e for e in raw["enemies"]}
    plan = {"gravelcrown": ("bb_roar", 260), "wasteland_lord": ("al_roar", 240),
            "abyss_marsh_dragon": ("ad_roar_summon", 280),
            "sunken_ancient_beast": ("sa_ancient_roar", 300),
            "black_crystal_troll": ("gm_roar", 250),
            "mountain_howl_lord": ("hl_mountain_roar", 280),
            "abyss_cave_lord": ("ac_roar", 280),
            "midnight_howl_king": ("nk_midnight_howl", 360)}
    actions = {a["id"]: a for a in raw["action"]}
    for mid, (aid, thr) in plan.items():
        e = enemies[mid]
        ai = e.get("ai") or {}
        states = ai.get("states") or {}
        assert "enraged" in states and "fatigued" in states, mid
        assert states["enraged"].get("enter_action") == aid, mid
        assert aid in actions and actions[aid].get("roar"), mid
        trs = ai.get("transitions") or []
        assert len(trs) == 4, mid
        first = trs[0]
        assert first["to"] == "enraged" and first["condition"]["value"] == thr, mid
    # 阈值都在合理区间（内容可调，防手滑）
    for mid, (_aid, thr) in plan.items():
        assert 100 <= thr <= 1000, mid
