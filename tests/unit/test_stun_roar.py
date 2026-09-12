"""气绝 KO + 咆哮（怪猎采纳 #2/#3）验收测试——2026-09-12 批⑦A 实装。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md 附录 C §3-4 + §四）：
  - **气绝 KO（#3）**：打击（blunt）× 命中「正」方位才积累「气绝槽」；满值 →
    眩晕倒地 = knockdown 状态（窗口 N 次行动，受击增伤）+ 起身演出吞掉怪下一次
    行动（ai_state.exec_state=downed）；阈值递增（escalation^n）+ 行动收尾衰减
    防无限控场；敌 `resistance.stun` 为阈值百分比加成。全部数值隐性、可配。
  - **咆哮（#2）**：怪招式 `roar`=1/2 → 震散玩家在途连势 + 行动条后推
    （light/heavy 分档）；「耳栓」（玩家 combatant `earplug` ≥ 招式等级）完全免疫。
  - 顺手修复 latent gap：玩家技能 `attack_type` 从未合并进伤害管线（一律 slash
    默认）→ 打类型内置破防（pierce_pct）/ effects attack_type scope 静默失效。
    本批在 `_resolve_combo_action` 补合并（显式优先），气绝 gate 依赖该字段。

铁律：零 NoneBot import；确定性（_QR 固定序列）；真跑断言；期望值由内容推导。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.battle_config import resolve_battle_settings
from qbot_rpg.core.combo import ComboEngine, ComboState
from qbot_rpg.core.message_format.battle_render import (
    _render_enemy_action,
    _render_stun_lines,
)
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
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 50, "mag": 10,
}


def _fresh(*, config=None, enemy_patch=None):
    raw, all_defs, ce = _pack()
    et = dict(next(e for e in raw["enemies"] if e["id"] == "ridge_cub"))
    if enemy_patch:
        et.update(enemy_patch)
    mob = {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": 10, "dfn": 10, "mag": 0, "spd": 20, "foc": 0, "lck": 0,
        "con": 10, "agi": 0, "name": et["name"],
    }
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.5] * 600)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    eng._snap.setdefault("ai_state", {})
    return eng, raw


def _set_side(eng, side):
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"relative_to": "enemy"})
    ent["side"] = side


def _stun_of(raw, sid):
    """技能气绝值（内容读取——期望值推导，不写死）。"""
    return float(next(s for s in raw["skills"] if s["id"] == sid).get("stun", 0))


def _stun_state(eng):
    return eng._snap.setdefault("stun_state", {"value": 0.0, "ko_count": 0, "hinted": False})


def _fx_types(out):
    return [str(e.get("type")) for e in (out.side_effects or ())]


def _spy_delay(eng):
    """包装调度器 delay_actor 记录调用（actor, extra, after, before, now）。"""
    calls = []
    orig = eng._ctb.delay_actor

    def _spy(actor_id, extra_bars=0.0):
        view = eng._ctb.get_actor(str(actor_id))
        before = float(view.next_ready) if view is not None else None
        now = float(getattr(eng._ctb, "_time", 0.0) or 0.0)
        r = orig(actor_id, extra_bars)
        after = float(view.next_ready) if view is not None else None
        calls.append((str(actor_id), float(extra_bars), after, before, now))
        return r

    eng._ctb.delay_actor = _spy  # type: ignore[method-assign]
    return calls


def _player_ready(eng):
    view = eng._ctb.get_actor("player")
    assert view is not None
    return float(view.next_ready)


def _knockdown_turns(eng):
    st = eng._snap.get("status_state")
    insts = st.get("enemy") if isinstance(st, dict) else None
    for inst in reversed(insts or []):
        if inst.get("status_id") == "knockdown":
            return int(inst.get("turns", 0))
    return None


def _spy_ko_set(eng):
    """在 `_fire_stun_ko` 返回瞬间捕获倒地窗口（实例 turns）——「写入值」精确断言。

    背景：状态 turns 在每个行动收尾由 `tick_turn_end` **双端各扣 1**（house 口径），
    动作结束后读取会少 1；故窗口断言取写入瞬间值，收尾衰减另用注释说明。
    """
    import types as _types

    cap = []
    orig = BattleEngine._fire_stun_ko

    def _spy(self, attacker, target, events):
        orig(self, attacker, target, events)
        st = self._snap.get("status_state") or {}
        for inst in reversed(st.get("enemy") or []):
            if isinstance(inst, dict) and inst.get("status_id") == "knockdown":
                cap.append(int(inst.get("turns", 0)))
                break

    eng._fire_stun_ko = _types.MethodType(_spy, eng)  # type: ignore[method-assign]
    return cap


_STUN_OFF = {"stun_decay_per_action": 0}


# =====================================================================================
# 1. 气绝槽积累：打击 × 正方位（gate / 位置倍率 / 配置）
# =====================================================================================


def test_blunt_front_accumulates_from_content():
    """打击技能正面命中 → 积累 = 内容 stun 值（衰减关）。"""
    eng, raw = _fresh(config=dict(_STUN_OFF))
    out = eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert out.ok and out.final_damage > 0
    assert _stun_state(eng)["value"] == _stun_of(raw, "vc_smash")


def test_slash_override_no_accumulate():
    """显式 attack_type=slash 的同技能 → 不积累（打击 gate 生效）。"""
    eng, _ = _fresh(config=dict(_STUN_OFF))
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash",
                             "attack_type": "slash"})
    assert _stun_state(eng)["value"] == 0.0


def test_normal_attack_no_accumulate():
    """普攻（无 stun 声明）→ 不积累。"""
    eng, _ = _fresh(config=dict(_STUN_OFF))
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert _stun_state(eng)["value"] == 0.0


def test_back_and_side_no_accumulate_default():
    """背位/侧位默认倍率 0 → 不积累（仅「正」方位）。"""
    eng_b, _ = _fresh(config=dict(_STUN_OFF))
    _set_side(eng_b, "back")
    eng_b.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng_b)["value"] == 0.0
    eng_l, _ = _fresh(config=dict(_STUN_OFF))
    _set_side(eng_l, "left")
    eng_l.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng_l)["value"] == 0.0


def test_side_back_mult_configurable():
    """stun_side_mult=0.5 / stun_back_mult=0.25 → 按倍率积累（可配）。"""
    eng_s, raw = _fresh(config={"stun_decay_per_action": 0, "stun_side_mult": 0.5})
    _set_side(eng_s, "right")
    eng_s.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng_s)["value"] == _stun_of(raw, "vc_smash") * 0.5
    eng_b, raw2 = _fresh(config={"stun_decay_per_action": 0, "stun_back_mult": 0.25})
    _set_side(eng_b, "back")
    eng_b.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng_b)["value"] == _stun_of(raw2, "vc_smash") * 0.25


def test_stun_enabled_off():
    """stun_enabled=False → 关（零积累）。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_enabled": False})
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng)["value"] == 0.0


def test_decay_applies_per_action():
    """衰减：命中后按 decay 比例衰减；无积累的行动同样衰减。"""
    eng, raw = _fresh(config={"stun_decay_per_action": 0.5})
    v0 = _stun_of(raw, "vc_smash")
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert abs(_stun_state(eng)["value"] - v0 * 0.5) < 1e-6
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    assert abs(_stun_state(eng)["value"] - v0 * 0.25) < 1e-6


# =====================================================================================
# 2. KO 触发：阈值 / 递增 / 抗性 / 窗口 / 起身吞行动
# =====================================================================================


def test_ko_at_threshold():
    """基础阈值 5 + 内容 stun 值 → 一击即 KO：窗口/状态/事件/起身态全链。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 5})
    cap = _spy_ko_set(eng)
    out = eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    fx = _fx_types(out)
    assert "stun_ko" in fx, f"应触发气绝 KO：{fx}"
    st = _stun_state(eng)
    assert st["ko_count"] == 1 and st["value"] == 0.0
    assert cap == [2], "倒地窗口写入值 = stun_ko_window 缺省 2"
    # 本动作收尾双端各扣 1 → 动作结束后读到 1（house 衰减口径，非窗口错）
    assert _knockdown_turns(eng) == 1
    assert (eng._snap.get("ai_state") or {}).get("exec_state") == "downed"


def test_ko_escalation_and_window_config():
    """escalation=2.0：二次阈值 ×2；stun_ko_window=3 → 窗口 3。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 5,
                            "stun_escalation": 2.0, "stun_ko_window": 3})
    cap = _spy_ko_set(eng)
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert eng._stun_threshold() == 10.0
    assert cap == [3], "stun_ko_window=3 应写入实例 turns=3"
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng)["ko_count"] == 2
    assert cap[-1] == 3, "二次 KO 重挂窗口同样生效"


def test_resistance_stun_scales_threshold():
    """resistance.stun=50 → 阈值 ×1.5（基准 10 → 15）：一击不 KO、两击 KO。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 10},
                    enemy_patch={"resistance": {"stun": 50}})
    assert eng._stun_threshold() == 15.0
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng)["ko_count"] == 0
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert _stun_state(eng)["ko_count"] == 1


def test_hint_before_ko():
    """软提示：跨过 hint 阈值（未满）→ stun_hint 事件一次；满值 KO 后复位。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 12,
                            "stun_hint_at": 0.5})
    out1 = eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert "stun_hint" in _fx_types(out1)
    assert _stun_state(eng)["hinted"] is True
    out2 = eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert "stun_ko" in _fx_types(out2)
    assert _stun_state(eng)["hinted"] is False


def test_ko_skip_configurable_off():
    """stun_ko_skip=False → KO 不吞怪行动（exec_state 保持非 downed）。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 5,
                            "stun_ko_skip": False})
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert (eng._snap.get("ai_state") or {}).get("exec_state") != "downed"
    assert _knockdown_turns(eng) is not None, "倒地状态本体不受 skip 开关影响（收尾扣减后仍在）"


def test_ko_interrupts_charging():
    """KO 打断在途蓄力（复用 _interrupt_enemy_ai）→ charge 清空 + 起身态。"""
    eng, _ = _fresh(config={"stun_decay_per_action": 0, "stun_base_threshold": 5})
    ai = eng._snap["ai_state"]
    ai["exec_state"] = "charging"
    ai["charge"] = {"action_id": "x", "total": 2, "shown": 1,
                    "remaining_turns": 1, "armor": False}
    eng.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    assert ai.get("charge") is None, "KO 应清空在途蓄力"
    assert ai.get("exec_state") == "downed"


# =====================================================================================
# 3. 咆哮：延迟 / 连势震散 / 耳栓 / 兼带伤害
# =====================================================================================


def test_roar_event_and_delay_default():
    """轻咆哮：行动条后推 350（缺省）+ roar 事件；ready = max(before, now)+350。"""
    eng, _ = _fresh()
    calls = _spy_delay(eng)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "gm_roar"})
    assert "roar" in _fx_types(out)
    assert len(calls) == 1 and calls[0][0] == "player"
    actor, extra, after, before, now = calls[0]
    assert extra == 350.0
    assert after == max(before, now) + 350.0
    assert _player_ready(eng) == after


def test_roar_heavy_delay():
    """大咆哮：后推 550（缺省）。"""
    eng, _ = _fresh()
    calls = _spy_delay(eng)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "sa_ancient_roar"})
    assert "roar" in _fx_types(out)
    assert calls[0][1] == 550.0


def test_roar_delays_configurable():
    """roar_light_delay / roar_heavy_delay 可配。"""
    eng, _ = _fresh(config={"roar_light_delay": 100, "roar_heavy_delay": 200})
    calls = _spy_delay(eng)
    eng.do_action("enemy", {"type": "skill", "skill_id": "gm_roar"})
    assert calls[0][1] == 100.0
    eng2, _ = _fresh(config={"roar_light_delay": 100, "roar_heavy_delay": 200})
    calls2 = _spy_delay(eng2)
    eng2.do_action("enemy", {"type": "skill", "skill_id": "ac_roar"})
    assert calls2[0][1] == 200.0


def test_roar_clears_player_combo():
    """咆哮震散玩家在途连势（combo clear 事件 reason=roar）。"""
    eng, _ = _fresh()
    ce = eng.combo_engine()
    ce.write_state(eng._snap, "player",
                   ComboState(chain_id="chain_ridge_combo", chain_name="猎势连段",
                              count=2, hold=False, step_index=1))
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "gm_roar"})
    assert ce.state_of(eng._snap, "player").count == 0
    clears = [e for e in (eng._snap.get("combo_events") or [])
              if e.get("type") == "combo_clear" and e.get("reason") == "roar"]
    assert clears, "应有 combo_clear(reason=roar) 审计"
    assert "roar" in _fx_types(out)


def test_roar_combo_clear_off():
    """roar_combo_clear=False → 连势保留（只后推）。"""
    eng, _ = _fresh(config={"roar_combo_clear": False})
    ce = eng.combo_engine()
    ce.write_state(eng._snap, "player",
                   ComboState(chain_id="chain_ridge_combo", chain_name="猎势连段",
                              count=2, hold=False, step_index=1))
    eng.do_action("enemy", {"type": "skill", "skill_id": "gm_roar"})
    assert ce.state_of(eng._snap, "player").count == 2


def test_roar_earplug_immune():
    """耳栓两级：earplug≥roar 等级 → 完全免疫（无延迟、无震散）。"""
    eng, _ = _fresh()
    eng._combat("player")["earplug"] = 1
    calls = _spy_delay(eng)
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "gm_roar"})  # L1
    assert "roar_blocked" in _fx_types(out)
    assert calls == []
    # L2 vs earplug=1 → 不免疫（大于）
    eng2, _ = _fresh()
    eng2._combat("player")["earplug"] = 1
    calls2 = _spy_delay(eng2)
    out2 = eng2.do_action("enemy", {"type": "skill", "skill_id": "sa_ancient_roar"})
    assert "roar" in _fx_types(out2) and calls2 and calls2[0][1] == 550.0
    # L2 vs earplug=2 → 免疫
    eng3, _ = _fresh()
    eng3._combat("player")["earplug"] = 2
    calls3 = _spy_delay(eng3)
    out3 = eng3.do_action("enemy", {"type": "skill", "skill_id": "sa_ancient_roar"})
    assert "roar_blocked" in _fx_types(out3) and calls3 == []


def test_roar_power_action_still_damages():
    """兼带伤害的嚎叫（群山嚎令）：伤害照常 + roar 事件同在。"""
    eng, _ = _fresh()
    out = eng.do_action("enemy", {"type": "skill", "skill_id": "hl_mountain_roar"})
    assert out.final_damage > 0
    assert "roar" in _fx_types(out)


# =====================================================================================
# 4. 渲染（占位符/分支）
# =====================================================================================


def test_render_stun_lines():
    """气绝事件行渲染：KO 行「【气绝】」/ 提示行。"""
    out = SimpleNamespace(
        side_effects=({"type": "stun_hint", "target": "enemy"},
                      {"type": "stun_ko", "target": "enemy"}),
        attacker_name="测试怪",
    )
    lines = _render_stun_lines(out)
    text = "\n".join(lines)
    assert "气息开始散乱" in text
    assert "【气绝】" in text


def test_render_roar_lines():
    """咆哮行渲染：连势震散 / 纯后推 / 耳栓三级分支。"""
    base = dict(attacker_name="测试怪", action_type="skill", hit=True, final_damage=0)
    t_combo = _render_enemy_action(SimpleNamespace(
        side_effects=({"type": "roar", "level": 1, "combo": True},), **base))
    assert "仰天咆哮" in t_combo and "连势震散" in t_combo
    t_plain = _render_enemy_action(SimpleNamespace(
        side_effects=({"type": "roar", "level": 1, "combo": False},), **base))
    assert "仰天咆哮" in t_plain and "连势震散" not in t_plain
    t_block = _render_enemy_action(SimpleNamespace(
        side_effects=({"type": "roar_blocked", "level": 2},), **base))
    assert "耳栓" in t_block


def test_templates_registered():
    """五条新模板可渲染（占位符替换）。"""
    assert tpl_of(None, "battle_stun_hint", {"name": "X"}).startswith("X的步幅一滞")
    assert "气息开始散乱" in tpl_of(None, "battle_stun_hint", {"name": "X"})
    assert "【气绝】" in tpl_of(None, "battle_stun_ko", {"name": "X"})
    assert "仰天咆哮" in tpl_of(None, "battle_roar", {"name": "X"})
    assert "仰天咆哮" in tpl_of(None, "battle_roar_plain", {"name": "X"})
    assert "耳栓" in tpl_of(None, "battle_roar_blocked", {"name": "X"})


# =====================================================================================
# 5. 配置白名单 / 内容守卫
# =====================================================================================


def test_battle_settings_sanitize():
    """settings["battle"] 段：合法键透传、坏值忽略（回落引擎默认）。"""
    good = {"stun_enabled": True, "stun_base_threshold": 88, "stun_escalation": 1.2,
            "stun_decay_per_action": 0, "stun_ko_window": 3, "stun_ko_skip": False,
            "stun_hint_at": 0.5, "stun_side_mult": 0.25, "stun_back_mult": 0.1,
            "roar_light_delay": 100, "roar_heavy_delay": 200, "roar_combo_clear": False}
    out = resolve_battle_settings({"battle": dict(good)})
    assert out == {**good, "stun_base_threshold": 88.0, "stun_escalation": 1.2,
                   "stun_decay_per_action": 0.0, "stun_side_mult": 0.25,
                   "stun_back_mult": 0.1, "roar_light_delay": 100.0,
                   "roar_heavy_delay": 200.0}
    bad = resolve_battle_settings({"battle": {
        "stun_base_threshold": 0, "stun_escalation": 0.5, "stun_ko_window": 2.5,
        "stun_enabled": "yes", "stun_hint_at": 2, "roar_light_delay": -5}})
    assert bad == {}


def test_content_blunt_skills_have_stun():
    """内容守卫：打击技（power>0）各自带气绝值（6..18）；非打击技无气绝值。"""
    raw, _, _ = _pack()
    n = 0
    for s in raw["skills"]:
        st = s.get("stun", 0)
        if st:
            n += 1
            assert s.get("attack_type") == "blunt", s["id"]
            assert 6 <= float(st) <= 18, s["id"]
        elif s.get("attack_type") == "blunt" and float(s.get("power") or 0) > 0:
            raise AssertionError(f"打击技缺气绝值：{s['id']}")
    assert n == 30, f"带气绝值技能数应为 30，got {n}"


def test_content_roar_actions_and_wiring():
    """内容守卫：8 条咆哮招（等级/恢复值）+ 5 只怪入池接线。"""
    raw, _, _ = _pack()
    actions = {a["id"]: a for a in raw["action"]}
    roar_ids = {"bb_roar", "al_roar", "sa_ancient_roar", "ac_roar", "gm_roar",
                "hl_mountain_roar", "nk_midnight_howl", "ad_roar_summon"}
    got = {aid for aid, a in actions.items() if a.get("roar")}
    assert got == roar_ids, got
    for aid in roar_ids:
        a = actions[aid]
        assert int(a["roar"]) in (1, 2), aid
        assert float(a.get("recovery") or 0) > 0, aid
    enemies = {e["id"]: e for e in raw["enemies"]}
    wiring = {"gravelcrown": "bb_roar", "wasteland_lord": "al_roar",
              "sunken_ancient_beast": "sa_ancient_roar",
              "abyss_cave_lord": "ac_roar", "black_crystal_troll": "gm_roar"}
    for mid, aid in wiring.items():
        pool = [x.get("action") for x in (enemies[mid].get("actions") or [])]
        assert aid in pool, f"{mid} 缺 {aid} 入池"


def test_attack_type_merge_fix():
    """latent gap 修复回归：默认驱动打击技能 = 显式 blunt（打类型内置破防生效）。"""
    eng_d, _ = _fresh()
    out_d = eng_d.do_action("player", {"type": "skill", "skill_id": "vc_smash"})
    eng_b, _ = _fresh()
    out_b = eng_b.do_action("player", {"type": "skill", "skill_id": "vc_smash",
                                       "attack_type": "blunt"})
    eng_s, _ = _fresh()
    out_s = eng_s.do_action("player", {"type": "skill", "skill_id": "vc_smash",
                                       "attack_type": "slash"})
    assert out_d.final_damage == out_b.final_damage
    assert out_b.final_damage > out_s.final_damage, "打类型内置破防应提高伤害"
