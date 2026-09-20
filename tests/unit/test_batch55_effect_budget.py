"""批55 · 特效强度预算（`effect_budget`）验收测试：闸 + A1 度量 + 方案 C + 双尺子。

依据：`docs/特效强度预算_设计.md` §二方案 B（主闸）、§二 A1（度量式）、§三推荐
（B 主 + A1 度量 + C 备用）、§四 红线守护清单（C1 缺省对拍 / C9 特效键不进面板轴 /
C11 上下钳 / C13 越档回滚）；档位红线 = `docs/审查参考/战斗数值层设计定稿.md:139-141`
（普通 3-8 / 精英 10-15 / Boss 40-60）。

覆盖：
  A. **缺省零变化**（红线 C1）：未配置 `effect_budget` → 聚合器返回 0、gate 静默、
     `effective_equip_share == equip_share`、方案 C 两键缺省 1.0 → 怪物 combatant 逐字段一致。
  B. **越界 / 未越界两态**：按档位上限（`cap_equiv_pct × tier_mult`）判超限；
     `gate_mode` off/warn/red 三态动作；`unknown_axis` 取更严者。
  C. **A1 度量**（§1.4）：`effective_equip_share = e/(pool+u)`；0 → 退化 `equip_share`；
     典型生存 build 折出的真实占比 < 面板 60%。
  D. **旧键别名**：`immune_dmg` / `cooldown_reduction_pct` 经 `effect_values_of` 换算为轴。
  E. **校验器两态**：段结构/类型/枚举红拦；条目级 warn=Y-20 / red=R-5 / off=静默；
     只统计特效键（atk/crit 忽略）。
  F. **编辑器可见**：`settings.effect_budget` 元数据（中文名 + 子字段）。
  G. **双尺子复算**：工具尺中值逐只斩回（缺省零变化；典型 build 后 Boss Δ=−2 超公差）；
     定稿档位尺（Boss 越档；闸生效后回到档内）。

纪律：只构造内存数据（不写任何真实内容包）；匿名 id（`s_*`）；数值全由测试内声明。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.commands.battle_launch_commands import _enemy_combatant
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.panel_budget import (
    DEFAULT_MONSTER_SCALING,
    EFFECT_BUDGET_KEY,
    check_effect_budget,
    effect_cap_pct,
    effect_equiv,
    effect_values_of,
    effective_equip_share,
    equip_share,
    normalize_effect_budget,
    normalize_monster_scaling,
)
from qbot_rpg.data.gear_stats import EFFECT_AXIS_WEIGHTS, DEFAULT_EFFECT_BUDGET

REPO = Path(__file__).resolve().parents[2]

#: 典型生存 build（报告 §1：减伤 25% + 吸血 15% + 冷却 ×0.8）。
TYPICAL = {"cooldown_pct": -20.0, "damage_taken_pct": -25.0, "absorb_hp": 15.0}
ENABLED: Dict[str, Any] = {"enabled": True}
#: 面板预算（批45 校准：7:18:5 = 60%）。
BUDGET: Dict[str, Any] = {"white": 7, "equip": 8, "buff": 5, "equip_stat_mult": 2.25}


def _pack(settings: Dict[str, Any], items: Any = None) -> Dict[str, Any]:
    mods: Dict[str, Any] = {"settings": settings}
    if items is not None:
        mods["items"] = items
    return mods


def _errors(rep: Any) -> Dict[str, str]:
    return {e.field: e.kind for e in rep.errors}


def _warnings(rep: Any) -> Dict[str, str]:
    return {w.field: w.kind for w in rep.warnings}


# ---------------------------------------------------------------------------
# A. 缺省零变化（红线 C1）
# ---------------------------------------------------------------------------
def test_default_config_is_disabled_and_zero() -> None:
    """缺段/非映射/非 true → enabled=false；聚合器返回 0；gate 静默。"""
    for cfg in (None, {}, {"cap_equiv_pct": 8}, {"enabled": False}, "not-a-mapping"):
        n = normalize_effect_budget(cfg)
        assert n["enabled"] is False
        eq = effect_equiv(TYPICAL, cfg)
        assert (eq["output_pct"], eq["survival_pct"], eq["equiv_pct"]) == (0.0, 0.0, 0.0)
        assert eq["unknown"] == []
        assert check_effect_budget(TYPICAL, "boss", cfg)["action"] == "ok"
        assert effect_cap_pct("boss", cfg) == 0.0


def test_default_defaults_snapshot() -> None:
    """缺省参数与报告 §三.2 推荐一致（cap 8% / 档位 1.5·1.0·0.625 / warn）。"""
    n = normalize_effect_budget(None)
    assert n["aggregate"] == "geometric"
    assert n["cap_equiv_pct"] == 8.0
    assert n["tier_mult"] == {"normal": 1.5, "elite": 1.0, "boss": 0.625}
    assert n["gate_mode"] == "warn"
    assert n["unknown_axis"] == "warn"
    assert n["report_effective_share"] is True
    assert DEFAULT_EFFECT_BUDGET["enabled"] is False
    assert set(EFFECT_AXIS_WEIGHTS) == set(n["axis_weights"])


def test_effective_share_degrades_to_equip_share_when_off() -> None:
    """A1：未启用（effect_pct=0/非法）→ 与 `equip_share` 逐位一致。"""
    assert effective_equip_share(BUDGET, 0.0) == equip_share(BUDGET)
    assert effective_equip_share(BUDGET, -5.0) == equip_share(BUDGET)
    assert effective_equip_share(BUDGET, "x") == equip_share(BUDGET)


def test_monster_scaling_effect_keys_default_identity() -> None:
    """方案 C 两键缺省 1.0；非法回落 1.0。"""
    assert DEFAULT_MONSTER_SCALING["effect_hp_mult"] == 1.0
    assert DEFAULT_MONSTER_SCALING["effect_atk_mult"] == 1.0
    n = normalize_monster_scaling(None)
    assert n["effect_hp_mult"] == 1.0 and n["effect_atk_mult"] == 1.0


def test_scheme_c_absent_is_byte_identical() -> None:
    """方案 C 未配置 → 怪物 combatant 逐字段与引入前一致；显式配置才生效。"""
    entry = {"id": "s_m", "stats": {"hp": 1000, "str": 200, "con": 150, "agi": 10, "foc": 20}}
    scaled = {"hp_mult": 1.5, "atk_mult": 1.5, "def_factor": 1.0828}
    base = _enemy_combatant(entry, scaled)
    # 不写新键 / 显式写 1.0 → 与批45 口径逐字段一致。
    assert _enemy_combatant(entry, dict(scaled)) == base
    assert _enemy_combatant(entry, dict(scaled, effect_hp_mult=1.0, effect_atk_mult=1.0)) == base
    assert _enemy_combatant(entry, None)["hp"] == 1000
    boosted = _enemy_combatant(entry, {"hp_mult": 1.5, "effect_hp_mult": 1.2,
                                       "effect_atk_mult": 1.1})
    assert boosted["hp"] == round(1000 * 1.5 * 1.2)
    assert boosted["atk"] == round(200 * 1.1)


# ---------------------------------------------------------------------------
# B. 越界 / 未越界两态 + gate_mode 三态 + unknown_axis
# ---------------------------------------------------------------------------
def test_cap_per_tier_matches_report_defaults() -> None:
    """档位上限 = cap × tier_mult：普通 12% / 精英 8% / Boss 5%。"""
    assert effect_cap_pct("normal", ENABLED) == 12.0
    assert effect_cap_pct("elite", ENABLED) == 8.0
    assert effect_cap_pct("boss", ENABLED) == 5.0
    # 未登记档位 / 无档位（条目配额）→ 回落 ×1.0 = 8%。
    assert effect_cap_pct("unknown-tier", ENABLED) == 8.0
    assert effect_cap_pct(None, ENABLED) == 8.0


def test_over_and_within_two_states() -> None:
    """越界态（典型 build）与未越界态（小 build）都可判、可区分。"""
    over = check_effect_budget(TYPICAL, "boss", ENABLED)
    assert over["over"] is True and over["action"] == "warn"
    assert over["equiv_pct"] > over["cap_pct"]
    within = check_effect_budget({"cooldown_pct": -3}, "boss", ENABLED)
    assert within["over"] is False and within["action"] == "ok"


def test_gate_mode_off_warn_red() -> None:
    """gate_mode 三态：off 静默 / warn 黄提示 / red 拒绝。"""
    off = {"enabled": True, "gate_mode": "off"}
    assert check_effect_budget(TYPICAL, "boss", off)["action"] == "ok"
    assert check_effect_budget(TYPICAL, "boss", ENABLED)["action"] == "warn"
    red = check_effect_budget(TYPICAL, "boss", {"enabled": True, "gate_mode": "red"})
    assert red["action"] == "red" and red["over"] is True


def test_unknown_axis_behavior_takes_stricter() -> None:
    """权表未登记轴：按 unknown_axis 呈现，且与越界取更严者。"""
    vals = {"healing_done_pct": 50.0}          # 已登记轴、但缺省权表未登记
    assert effect_equiv(vals, ENABLED)["unknown"] == ["healing_done_pct"]
    assert check_effect_budget(vals, "elite", {"enabled": True,
                                               "unknown_axis": "ignore"})["action"] == "ok"
    assert check_effect_budget(vals, "elite", ENABLED)["action"] == "warn"
    assert check_effect_budget(vals, "elite", {"enabled": True,
                                               "unknown_axis": "red"})["action"] == "red"
    # 非特效键（atk/crit）完全忽略，不产生 unknown。
    assert effect_equiv({"atk": 999, "crit": 5}, ENABLED)["unknown"] == []


def test_aggregate_modes() -> None:
    """geometric / product / max 三口径都可配。"""
    g = effect_equiv(TYPICAL, {"enabled": True, "aggregate": "geometric"})["equiv_pct"]
    p = effect_equiv(TYPICAL, {"enabled": True, "aggregate": "product"})["equiv_pct"]
    m = effect_equiv(TYPICAL, {"enabled": True, "aggregate": "max"})["equiv_pct"]
    assert p > m > g
    assert m == pytest.approx(76.3, abs=1e-6)
    assert p == pytest.approx((1.068 * 1.763 - 1.0) * 100.0, rel=1e-9)


def test_axis_weights_overridable() -> None:
    """权表可逐键覆盖 / 追加（不写死）。"""
    cfg = {"enabled": True, "axis_weights": {"cooldown_pct": {"calib": -10.0, "output": 20.0}}}
    eq = effect_equiv({"cooldown_pct": -10}, cfg)
    assert eq["output_pct"] == 20.0
    assert effect_equiv({"cooldown_pct": -10}, ENABLED)["output_pct"] == 3.4


# ---------------------------------------------------------------------------
# C. A1 度量（只报数不改数）
# ---------------------------------------------------------------------------
def test_effective_equip_share_monotonic_and_off_by_default() -> None:
    """特效越强 → 真实装备占比越低；0 → 退化为 60%。"""
    s0 = effective_equip_share(BUDGET, 0.0)
    s1 = effective_equip_share(BUDGET, 10.0)
    s2 = effective_equip_share(BUDGET, 37.218220364498244)
    assert s0 == pytest.approx(0.60, abs=1e-9)
    assert s1 < s0 and s2 < s1
    # 报告 §1.4：典型 build 真实占比落在 38%~56%（本框架聚合口径 ≈43.7%）。
    assert 0.35 <= s2 <= 0.56
    # 报告 §1.4 精确值：u=(综合−1)×30 → 18/(30+u)。
    assert s2 == pytest.approx(18.0 / (30.0 + 0.37218220364498244 * 30.0), rel=1e-9)


def test_amount_formula_matches_report_section_1_4() -> None:
    """报告 §1.4：仅输出 u=2.04 → 56.2%；几何 +19.3%/+25.7% → 50.3%/47.7%。"""
    assert effective_equip_share(BUDGET, 6.8) * 100 == pytest.approx(56.2, abs=0.2)
    assert effective_equip_share(BUDGET, 19.3) * 100 == pytest.approx(50.3, abs=0.3)
    assert effective_equip_share(BUDGET, 25.7) * 100 == pytest.approx(47.7, abs=0.3)


# ---------------------------------------------------------------------------
# D. 旧键别名换算
# ---------------------------------------------------------------------------
def test_legacy_aliases_map_into_axes() -> None:
    """`immune_dmg` → damage_taken_pct（取负）；占位冷却键 → cooldown_pct（取负）。"""
    vals = effect_values_of({"immune_dmg": 25.0, "cooldown_reduction_pct": 20.0,
                             "absorb_hp": 15.0, "atk": 100.0, "crit": 5.0}, ENABLED)
    assert vals == {"damage_taken_pct": -25.0, "cooldown_pct": -20.0, "absorb_hp": 15.0}
    # 与轴形态逐字段等价。
    direct = effect_equiv({"damage_taken_pct": -25.0, "cooldown_pct": -20.0, "absorb_hp": 15.0},
                          ENABLED)
    assert effect_equiv(vals, ENABLED) == direct


# ---------------------------------------------------------------------------
# E. 校验器：段 + 条目级两态
# ---------------------------------------------------------------------------
def test_validator_absent_section_is_silent() -> None:
    rep = check_pack(_pack({}), default_field_meta_table())
    assert not rep.errors and not rep.warnings


def test_validator_over_entry_warn_and_red() -> None:
    """条目级越界：缺省 warn=Y-20；gate_mode=red → R-5；off → 静默。"""
    item = [{"id": "s_gear", "immune_dmg": 30, "cooldown_reduction_pct": 20, "absorb_hp": 40}]
    w = check_pack(_pack({"effect_budget": ENABLED}, item), default_field_meta_table())
    assert not w.errors and _warnings(w).get("items.0") == "Y-20"
    r = check_pack(_pack({"effect_budget": {"enabled": True, "gate_mode": "red"}}, item),
                   default_field_meta_table())
    assert _errors(r).get("items.0") == "R-5"
    o = check_pack(_pack({"effect_budget": {"enabled": True, "gate_mode": "off"}}, item),
                   default_field_meta_table())
    assert not o.errors and not o.warnings


def test_validator_disabled_section_is_silent() -> None:
    """enabled=false → 条目级静默（即便词条等效很大）。"""
    item = [{"id": "s_gear", "immune_dmg": 90, "absorb_hp": 90}]
    rep = check_pack(_pack({"effect_budget": {"enabled": False}}, item),
                     default_field_meta_table())
    assert not rep.errors and not rep.warnings


def test_validator_ignores_non_effect_keys() -> None:
    """条目只统计特效键：atk/crit 等普通词条不触发闸。"""
    item = [{"id": "s_gear", "atk": 100, "crit": 5, "hp_pct": 50}]
    rep = check_pack(_pack({"effect_budget": ENABLED}, item), default_field_meta_table())
    assert not rep.errors and not rep.warnings


def test_validator_structure_and_enum_errors() -> None:
    """段结构 / 类型 / 枚举 / 负值红拦；calib=0 黄提示。"""
    bad = {"enabled": "yes", "aggregate": "nope", "gate_mode": "boom",
           "unknown_axis": "x", "cap_equiv_pct": -1, "tier_mult": {"boss": "x"},
           "axis_weights": {"cooldown_pct": {"calib": 0, "output": "x"}}}
    rep = check_pack(_pack({"effect_budget": bad}), default_field_meta_table())
    e = _errors(rep)
    assert e.get("settings.effect_budget.enabled") == "R-1"
    assert e.get("settings.effect_budget.aggregate") == "R-1"
    assert e.get("settings.effect_budget.gate_mode") == "R-1"
    assert e.get("settings.effect_budget.unknown_axis") == "R-1"
    assert e.get("settings.effect_budget.cap_equiv_pct") == "R-2"
    assert e.get("settings.effect_budget.tier_mult.boss") == "R-1"
    assert e.get("settings.effect_budget.axis_weights.cooldown_pct.output") == "R-1"
    assert _warnings(rep).get("settings.effect_budget.axis_weights.cooldown_pct.calib") == "Y-20"


def test_validator_section_non_mapping_is_red() -> None:
    rep = check_pack(_pack({"effect_budget": 5}), default_field_meta_table())
    assert _errors(rep).get("settings.effect_budget") == "R-1"


def test_validator_effect_budget_key_constant() -> None:
    """段键名唯一源 = `EFFECT_BUDGET_KEY`（data 层），core 再导出同一值。"""
    assert EFFECT_BUDGET_KEY == "effect_budget"


# ---------------------------------------------------------------------------
# F. 编辑器可见
# ---------------------------------------------------------------------------
def test_field_meta_registers_effect_budget() -> None:
    m = default_field_meta_table().module("settings")
    assert "effect_budget" in m.fields
    fm = m.fields["effect_budget"]
    assert fm.label and fm.help
    kids = fm.children or {}
    for key in ("enabled", "aggregate", "cap_equiv_pct", "tier_mult", "gate_mode",
                "unknown_axis", "report_effective_share", "axis_weights"):
        assert key in kids, key


# ---------------------------------------------------------------------------
# G. 双尺子复算
# ---------------------------------------------------------------------------
def _load_dual_ruler() -> Any:
    spec = importlib.util.spec_from_file_location(
        "batch55_dual_ruler", REPO / "scripts" / "batch55_dual_ruler.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["batch55_dual_ruler"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_tool_ruler_zero_change_and_boss_over_tolerance() -> None:
    """工具尺：本批缺省逐只零变化；典型 build 后 Boss Δ=−2 超 ±1 公差。"""
    dr = _load_dual_ruler()
    m = dr._load_module("batch45_measure", dr._HERE / "batch45_measure.py")
    tr = dr.tool_ruler(m)
    assert tr["median_turns_before"] == {"normal": 7, "elite": 20, "boss": 24}
    assert tr["median_turns_after_default"] == tr["median_turns_before"]
    assert tr["delta_turns"] == {"normal": 0, "elite": -1, "boss": -2}
    assert tr["over_tolerance"] == ["boss"]
    assert tr["equip_share_budget"] == pytest.approx(0.60, abs=1e-9)
    # 精确翻转阈值：Boss 最敏感（远小于普通）。
    flips = dr.flip_thresholds(m)
    assert flips["boss"] < flips["elite"] < flips["normal"]


def test_tier_ruler_boss_over_and_gated_back_in_band() -> None:
    """定稿档位尺：典型 build 把 Boss 压到 40 下沿（越档）；闸生效后回到档内。"""
    dr = _load_dual_ruler()
    rr = dr.tier_ruler()
    assert rr["over_tier"] == ["boss"]
    boss = rr["rows"]["boss"]
    assert boss["baseline_real_turns"] == 48.0
    assert min(boss["typical_build_real_turns"]) < 40.0 <= max(boss["typical_build_real_turns"])
    assert rr["boss_gated_turns_lower_bound"] >= 40.0
    assert rr["boss_gated_within"] is True
    # 普通/精英 在档内。
    assert rr["rows"]["normal"]["within"] and rr["rows"]["elite"]["within"]
