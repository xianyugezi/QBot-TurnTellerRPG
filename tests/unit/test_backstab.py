"""背击闭环（B5）验收测试——2026-09-11 批④实装。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md §B-5 + 附录 A）：
  - **背击加成**：玩家攻击**结算时**位于怪背面（combat_position.player.side == "back"）
    → 伤害加成 `backstab_bonus`（缺省 +10%、可配、0=关）；乘区挂在物理侧（元素不吃，
    闇討ち「属性伤害不计」口径）；命中行出「（背击）」附注（零数值）。
  - **时序修订**（v1 §三「玩家行动前转回面向」→ 批④「行动结算后」）：玩家绕背/侧移后
    本次行动**于捕获侧位结算**（吃到背击），结算后怪才转身（事件 + turn_cost）——
    否则背击永远没有成立时机。重定位类行动（行动前=front）不触发转向；被拒行动
    （R-6 零成本）不触发。
  - **内容守卫**：每只攻击怪 ≥1 招可打背（反制「绕背=无风险区」的退化玩法）。

铁律：零 NoneBot import；纯逻辑断言；确定性（_QR 固定序列）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import ActionOutcome, BattleEngine
from qbot_rpg.core.battle_config import resolve_battle_settings
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.message_format.battle_render import _render_crit_block_note

# 玩家 spd=50（首拍 t=200）；怪 spd=20（首拍 t=500）——玩家行动收尾后怪尚未出手，
# 便于对「转向延迟前/后」做干净的 ready 断言（不含怪自身行动的重签噪声）。
_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 50, "mag": 10,
}


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


def _fresh(*, config=None):
    raw, all_defs, ce = _pack()
    et = next(e for e in raw["enemies"] if e["id"] == "ridge_cub")
    mob = {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": 10, "dfn": 10, "mag": 0, "spd": 20, "foc": 0, "lck": 0,
        "con": 10, "agi": 0, "name": et["name"],
    }
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.5] * 400)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7, config=config)
    return eng


def _set_side(eng: BattleEngine, side: str) -> None:
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"relative_to": "enemy"})
    ent["side"] = side


def _side_of(eng: BattleEngine) -> str:
    cp = eng._snap.get("combat_position") or {}
    return str((cp.get("player") or {}).get("side") or "front")


def _enemy_ready(eng: BattleEngine) -> float:
    view = eng._ctb.get_actor("enemy") if eng._ctb is not None else None
    assert view is not None
    return float(view.next_ready)


def _turn_events(effects) -> list:
    out = []
    for e in effects or ():
        if isinstance(e, dict) and e.get("type") == "enemy_turned":
            out.append(e)
    return out


def _player_outcome(rep):
    for o in rep.outcomes:
        if getattr(o, "actor", "") == "player":
            return o
    raise AssertionError("无玩家 outcome")


# =====================================================================================
# 1. 引擎：背击乘区（物理通道 + 可配）
# =====================================================================================


class TestBackstabBonus:
    def test_back_attack_gets_bonus(self) -> None:
        """背后结算 → 伤害高于正面（同种子对照）；outcome.backstab=True。"""
        eng_f = _fresh()
        out_f = eng_f.do_action("player", {"type": "normal", "mult": 1.0})
        eng_b = _fresh()
        _set_side(eng_b, "back")
        out_b = eng_b.do_action("player", {"type": "normal", "mult": 1.0})
        assert out_b.final_damage > out_f.final_damage
        ratio = out_b.final_damage / out_f.final_damage
        assert 1.05 <= ratio <= 1.15, f"背击比率异常：{ratio:.3f}"
        assert bool(getattr(out_b, "backstab", False)) is True
        assert bool(getattr(out_f, "backstab", False)) is False

    def test_bonus_zero_disables(self) -> None:
        """backstab_bonus=0 → 背后与正面对照伤害相等（机制关闭）。"""
        eng_f = _fresh(config={"backstab_bonus": 0})
        out_f = eng_f.do_action("player", {"type": "normal", "mult": 1.0})
        eng_b = _fresh(config={"backstab_bonus": 0})
        _set_side(eng_b, "back")
        out_b = eng_b.do_action("player", {"type": "normal", "mult": 1.0})
        assert out_b.final_damage == out_f.final_damage
        assert bool(getattr(out_b, "backstab", False)) is False

    def test_bonus_configurable(self) -> None:
        """backstab_bonus 可配（0.25 → 高于缺省 0.10 档）。"""
        eng_d = _fresh()
        _set_side(eng_d, "back")
        out_d = eng_d.do_action("player", {"type": "normal", "mult": 1.0})
        eng_c = _fresh(config={"backstab_bonus": 0.25})
        _set_side(eng_c, "back")
        out_c = eng_c.do_action("player", {"type": "normal", "mult": 1.0})
        assert out_c.final_damage > out_d.final_damage

    def test_skill_rewrap_keeps_flag(self) -> None:
        """技能+effects 回包路径（_resolve_combo_action）不丢背击旗标。

        批④ 黑盒实证的回归点：回包曾用字段手抄构造，漏抄 backstab → 已改
        dataclasses.replace 整包复制。
        """
        eng_f = _fresh()
        out_f = eng_f.do_action("player", {"type": "skill", "skill_id": "vg_key"})
        eng_b = _fresh()
        _set_side(eng_b, "back")
        out_b = eng_b.do_action("player", {"type": "skill", "skill_id": "vg_key"})
        assert bool(getattr(out_b, "backstab", False)) is True
        assert bool(getattr(out_f, "backstab", False)) is False
        assert out_b.final_damage > out_f.final_damage

    def test_side_left_right_no_bonus(self) -> None:
        """侧面（left/right）不吃背击（仅背面——闇討ち口径）。"""
        for side in ("left", "right"):
            eng_f = _fresh()
            out_f = eng_f.do_action("player", {"type": "normal", "mult": 1.0})
            eng_s = _fresh()
            _set_side(eng_s, side)
            out_s = eng_s.do_action("player", {"type": "normal", "mult": 1.0})
            assert out_s.final_damage == out_f.final_damage, side
            assert bool(getattr(out_s, "backstab", False)) is False


# =====================================================================================
# 2. 时序修订：行动结算后转身（背击窗口成立）
# =====================================================================================


class TestTimingRevision:
    def test_attack_resolves_from_back_then_turn(self) -> None:
        """行动前=back：本次攻击按背面结算（加成 + backstab 旗标）→ 结算后转身。"""
        eng = _fresh()
        _set_side(eng, "back")
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        out = _player_outcome(rep)
        assert bool(getattr(out, "backstab", False)) is True     # 攻击吃背击
        assert _side_of(eng) == "front"                          # 结算后归位
        assert _enemy_ready(eng) == before + 400.0               # 转向成本
        assert len(_turn_events(out.side_effects)) == 1

    def test_reposition_capture_front_no_turn(self) -> None:
        """重定位类行动：行动前=front（捕获）→ 不转向；行动后 side=back 保持。"""
        eng = _fresh()
        before = _enemy_ready(eng)
        # 模拟重定位：行动结算把 side 移到 back，但捕获方位=front（行动前）
        _set_side(eng, "back")
        ev = eng._face_enemy("front")
        assert ev is None
        assert _side_of(eng) == "back"
        assert _enemy_ready(eng) == before

    def test_front_no_turn_no_cost(self) -> None:
        """行动前=front 常规行：不转向、零消耗、无事件。"""
        eng = _fresh()
        before = _enemy_ready(eng)
        rep = eng.player_act({"type": "normal", "mult": 1.0})
        out = _player_outcome(rep)
        assert _side_of(eng) == "front"
        assert _enemy_ready(eng) == before
        assert _turn_events(out.side_effects) == []

    def test_turn_uses_captured_side(self) -> None:
        """_face_enemy 判定基准=捕获侧位（直调防御性：缺省读当前）。"""
        eng = _fresh()
        # 当前 side=back，传入 pre_side=front → 不转向（捕获口径优先）
        _set_side(eng, "back")
        assert eng._face_enemy("front") is None
        # 无参直调 → 读当前 side=back → 转向
        ev = eng._face_enemy()
        assert isinstance(ev, dict) and ev.get("type") == "enemy_turned"
        assert _side_of(eng) == "front"


# =====================================================================================
# 3. 配置管道：settings["battle"] 段（battle_config）
# =====================================================================================


class TestBattleSettingsPipeline:
    def test_resolve_battle_settings(self) -> None:
        assert resolve_battle_settings({"battle": {"backstab_bonus": 0.25}}) == {
            "backstab_bonus": 0.25}
        assert resolve_battle_settings({"battle": {}}) == {}
        assert resolve_battle_settings({}) == {}
        assert resolve_battle_settings(None) == {}
        # 非法值忽略（回落引擎默认）
        assert resolve_battle_settings({"battle": {"backstab_bonus": -1}}) == {}
        assert resolve_battle_settings({"battle": {"backstab_bonus": "x"}}) == {}
        assert resolve_battle_settings({"battle": {"backstab_bonus": True}}) == {}
        # 白名单外键不透传
        assert resolve_battle_settings({"battle": {"air_drop_turns": 99}}) == {}

    def test_pipeline_into_engine(self) -> None:
        """settings 段解析值 → 引擎 config → 乘区生效（端到端）。"""
        seg = resolve_battle_settings({"battle": {"backstab_bonus": 0}})
        eng = _fresh(config=seg)
        _set_side(eng, "back")
        out_off = eng.do_action("player", {"type": "normal", "mult": 1.0})
        assert bool(getattr(out_off, "backstab", False)) is False
        eng2 = _fresh(config=resolve_battle_settings(
            {"battle": {"backstab_bonus": 0.2}}))
        _set_side(eng2, "back")
        out_on = eng2.do_action("player", {"type": "normal", "mult": 1.0})
        assert bool(getattr(out_on, "backstab", False)) is True


# =====================================================================================
# 4. 渲染：「（背击）」附注 + 模板登记
# =====================================================================================


class TestBackstabRender:
    def test_note_appended(self) -> None:
        out = SimpleNamespace(crit="low", blocked=False, backstab=True)
        assert "（背击）" in _render_crit_block_note(out)
        out0 = SimpleNamespace(crit="low", blocked=False, backstab=False)
        assert "（背击）" not in _render_crit_block_note(out0)

    def test_template_and_whitelist_registered(self) -> None:
        from qbot_rpg.core.templates import (  # noqa: PLC0415
            DEFAULT_TEMPLATES,
            PLACEHOLDER_WHITELIST,
        )

        assert DEFAULT_TEMPLATES["battle_backstab_note"] == "（背击）"
        assert PLACEHOLDER_WHITELIST["battle_backstab_note"] == set()


class TestDisplayPipeline:
    def test_outcome_fields_include_backstab(self) -> None:
        """接线层副本清单含 backstab（批④ 实证回归点：桥接层 _outcome_copy 曾丢字段）。"""
        from qbot_rpg.commands.battle_commands import (  # noqa: PLC0415
            _OUTCOME_FIELDS,
            _outcome_copy,
        )

        assert "backstab" in _OUTCOME_FIELDS
        oc = ActionOutcome(
            ok=True, seq=1, actor="player", action_type="normal", target="enemy",
            hit=True, crit="low", blocked=False, raw_damage=10, final_damage=10,
            target_hp=5, side_effects=(), message="", backstab=True,
        )
        ns = _outcome_copy(oc)
        assert bool(getattr(ns, "backstab", False)) is True


# =====================================================================================
# 5. 内容守卫：每只攻击怪 ≥1 招可打背（B5 反制绕背）
# =====================================================================================


class TestContentBackCoverage:
    def _scan(self):
        raw, _, _ = _pack()
        acts = {a["id"]: a for a in raw["action"]}
        out = []
        for e in raw["enemies"]:
            seen = []
            for ph in e.get("phases", []):
                for a in ph.get("actions", []):
                    if a.get("action") not in seen:
                        seen.append(a.get("action"))
            for a in e.get("actions", []):
                if a.get("action") not in seen:
                    seen.append(a.get("action"))
            dmg = [x for x in seen if x in acts and float(acts[x].get("power", 0) or 0) > 0]
            back = [x for x in dmg
                    if not (acts[x].get("position_rule") or {}).get("side")
                    or "back" in ((acts[x].get("position_rule") or {}).get("side") or [])]
            out.append((e["id"], dmg, back))
        return acts, out

    def test_monster_back_coverage(self) -> None:
        """每只攻击怪：≥1 招可打背（否则绕背=零风险安全区）。"""
        acts, rows = self._scan()
        for mid, dmg, back in rows:
            if not dmg:
                continue  # 木桩/无攻击怪
            assert back, f"{mid} 无打背手段（绕背将成无风险区）"

    def test_new_sweeps_registered(self) -> None:
        """批④ 新增两招（幼兽甩尾/砾壳翻滚）在位且为全侧攻击。"""
        acts, rows = self._scan()
        assert acts["bb_cub_tail"]["name"] == "幼兽甩尾"
        assert acts["gt_shell_roll"]["name"] == "砾壳翻滚"
        for aid in ("bb_cub_tail", "gt_shell_roll"):
            pr = acts[aid].get("position_rule") or {}
            assert not pr.get("side"), f"{aid} 应全侧（无 side 限定）"
            assert float(acts[aid].get("power", 0) or 0) > 0
        for mid, dmg, back in rows:
            if mid == "ridge_cub":
                assert "bb_cub_tail" in back
            if mid == "gravel_tortoise":
                assert "gt_shell_roll" in back

    def test_extended_moves_cover_back(self) -> None:
        """批④ 13 招扩全侧清单（删 side 限定；height 保留）。"""
        acts, _ = self._scan()
        for aid in ("wp_pounce", "gj_shard_spray", "rw_gust_pounce", "wr_rebound",
                    "cm_spike_volley", "ea_vein_spray", "cf_mist_spray", "zb_death_roll",
                    "ym_blade_flurry", "dw_backstab", "ad_tail", "bb_paw_swipe",
                    "sb_shadow_flurry"):
            pr = acts[aid].get("position_rule") or {}
            assert not pr.get("side"), f"{aid} 仍有限定：{pr.get('side')}"
            assert pr.get("height"), f"{aid} height 丢失"
