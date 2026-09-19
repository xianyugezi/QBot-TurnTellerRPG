"""批44 · 投入概率暴击：两条路径 / 概率统计 / 逐档不同 / 封顶 / 回归对拍 / 编辑器可见。

依据：`docs/深度打造_决策记录.md` §七（用户裁定「投入概率暴击」解彩档 q10 可达性，
不拉高 cap、不强制扩材料表）；`打造_材料表与图纸表_草案v2.md` §3。

覆盖：
  · **两条路径**（注入 RNG 强制暴击 / 强制不暴击）→ 逐数值断言品质经验与最终品质等级；
  · **可复现**（同种子同结果；不同注入值不同结果）；
  · **概率统计**（1000 次实际触发率 ≈ 声明概率；固定种子 → 不 flaky）；
  · **按档不同**（铜 15% / 银 10% / 金 7% / 彩 5%；确定性边界 + 逐档统计）；
  · **适用档 / 开关 / 作用目标**：不生效时**不消耗随机数**（回归零影响）；
  · **经验封顶**（none / last_threshold / 数值）；
  · **回归对拍**：不暴击（缺省关 + 强制不命中）路径逐字段等于现状（预批44 键集）；
  · **编辑器可见**：中文名 + 说明卡（写清「替代拉高 cap 实现彩档 q10」）；
  · **校验器**：结构/类型/范围/枚举红拦 + Y-17 黄提示。

纪律：不写任何真实内容包（id 全为测试自造）；概率/倍率/档位全部测试内声明。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from qbot_rpg.content.deep_craft_settings import read_deep_craft_settings
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.deep_craft import plan_craft, quality_exp

THRESHOLDS = [0, 25, 60, 110, 180, 275, 400, 560, 780, 1080]
EXP_BY_COLOR = {"红": 100.0, "白": 1.0}
MATS: List[Dict[str, Any]] = [{"quality": "红", "count": 1, "same_affinity": False}]


class _FakeRng:
    """确定性单值随机源（返回预置 [0,1)）。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.value


class _SeqRng:
    """确定性序列随机源（按序弹出；用尽 → 0.0）。"""

    def __init__(self, values: List[float]) -> None:
        self.values = list(values)
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.values.pop(0) if self.values else 0.0


def _rules(**crit: Any) -> Dict[str, Any]:
    """仅在包声明里写 quality_exp_crit（其余取框架默认）。"""
    return read_deep_craft_settings(
        {"deep_craft": {"craft_rules": {"quality_exp_crit": crit}}})["craft_rules"]


def _cfg(crit: Optional[Dict[str, Any]] = None, **rules: Any) -> Dict[str, Any]:
    seg: Dict[str, Any] = {"quality_exp_by_color": dict(EXP_BY_COLOR),
                           "craft_rules": dict(rules)}
    if crit is not None:
        seg["craft_rules"]["quality_exp_crit"] = dict(crit)
    return read_deep_craft_settings({"deep_craft": seg})


def _blueprint(**over: Any) -> Dict[str, Any]:
    bp: Dict[str, Any] = {
        "id": "bp_t", "name": "测试图纸", "blueprint_output": "g_out",
        "blueprint_slot": "weapon", "blueprint_grade": "铜",
        "blueprint_level_band": {"min": 1, "max": 99},
        "blueprint_material_slots": [{"role": "main", "item": "m_main"}],
        "affinities": {},
    }
    bp.update(over)
    return bp


def _plan(config: Dict[str, Any], rng: Any) -> Dict[str, Any]:
    return plan_craft(
        blueprint=_blueprint(), config=config,
        materials=[{"id": "m_main", "count": 1}],
        material_defs={"m_main": {"material_level": 10, "material_quality": "红",
                                  "craft_cost": 10, "affinities": {}}},
        learned=True, rng=rng, affinity_reactions=())


# 预批44 的计划键集（回归对拍用；新增键 = 附加，不改变旧字段口径）。
BASELINE_PLAN_KEYS = (
    "ok", "reason", "lesson", "level", "quality_exp", "quality_exp_breakdown",
    "quality_level", "quality", "grade", "color_row", "cost", "cost_cap", "kinds",
    "main_level", "materials", "affinity", "fixed_stats", "random_stats", "stats_bonus",
    "fixed_set_affixes", "random_set_affixes", "set_affixes", "passives",
    "random_stat_count", "random_set_affix_count",
)
BASELINE_BREAKDOWN_KEYS = ("exp", "base_sum", "type_factor", "interaction", "kinds")
NEW_PLAN_KEYS = ("quality_exp_base", "crit", "crit_mult", "crit_chance")


# ---------------------------------------------------------------------------
# 1) 两条路径（注入 RNG 强制暴击 / 强制不暴击）——逐数值断言
# ---------------------------------------------------------------------------
def test_two_paths_forced_crit_and_no_crit() -> None:
    """品质经验：不暴击 = 100（等级 3）；暴击 ×2 = 200（等级 5）。"""
    rules = _rules(enabled=True, grades=["铜"], chance_by_grade={"铜": 0.15},
                   mult_by_grade={"铜": 2.0}, exp_cap="none")

    miss_rng = _FakeRng(0.999)
    miss = quality_exp(MATS, rules, EXP_BY_COLOR, rng=miss_rng, grade="铜",
                       thresholds=THRESHOLDS)
    assert miss["crit"] is False
    assert miss["crit_mult"] == 1.0
    assert miss["exp"] == pytest.approx(100.0)
    assert miss["exp_before_crit"] == pytest.approx(100.0)
    assert miss_rng.calls == 1

    hit_rng = _FakeRng(0.0)
    hit = quality_exp(MATS, rules, EXP_BY_COLOR, rng=hit_rng, grade="铜",
                      thresholds=THRESHOLDS)
    assert hit["crit"] is True
    assert hit["crit_mult"] == 2.0
    assert hit["exp"] == pytest.approx(200.0)
    assert hit["exp_before_crit"] == pytest.approx(100.0)
    assert hit_rng.calls == 1
    # 最终品质等级：不暴击 3 级 / 暴击 5 级（阈值 [0,25,60,110,180,275,…]）。
    from qbot_rpg.core.deep_craft import quality_level_of
    assert quality_level_of(miss["exp_for_level"], THRESHOLDS) == 3
    assert quality_level_of(hit["exp_for_level"], THRESHOLDS) == 5


def test_plan_two_paths_quality_level() -> None:
    """主流程两条路径：暴击 → 品质等级 5；不暴击 → 3（贴数值）。"""
    crit = {"enabled": True, "grades": ["铜"], "chance_by_grade": {"铜": 0.15},
            "mult_by_grade": {"铜": 2.0}, "exp_cap": "none"}
    hit = _plan(_cfg(crit), _FakeRng(0.0))
    miss = _plan(_cfg(crit), _FakeRng(0.999))
    assert hit["ok"] and miss["ok"]
    assert (hit["crit"], hit["quality_exp"], hit["quality_level"]) == (True, 200.0, 5)
    assert (miss["crit"], miss["quality_exp"], miss["quality_level"]) == (False, 100.0, 3)
    assert hit["quality_exp_base"] == miss["quality_exp_base"] == 100.0


# ---------------------------------------------------------------------------
# 2) 可复现（同种子同结果）
# ---------------------------------------------------------------------------
def test_reproducible_same_seed_and_injection() -> None:
    rules = _rules(enabled=True, mult_by_grade={"铜": 2.0}, exp_cap="none")
    out = []
    for _ in range(2):
        q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=random.Random(20260919),
                        grade="铜", thresholds=THRESHOLDS)
        out.append((q["crit"], q["exp"]))
    assert out[0] == out[1], "同种子必须同结果"
    # 注入不同流 → 结果由注入流决定（非全局 random）。
    assert quality_exp(MATS, rules, EXP_BY_COLOR, rng=_FakeRng(0.0), grade="铜",
                       thresholds=THRESHOLDS)["crit"] is True
    assert quality_exp(MATS, rules, EXP_BY_COLOR, rng=_FakeRng(0.9), grade="铜",
                       thresholds=THRESHOLDS)["crit"] is False


# ---------------------------------------------------------------------------
# 3) 概率统计 + 按档不同
# ---------------------------------------------------------------------------
PER_GRADE = {"铜": 0.15, "银": 0.10, "金": 0.07, "彩": 0.05}


def test_per_grade_chances_are_declared_values() -> None:
    rules = _rules(enabled=True, mult_by_grade={"铜": 2.0}, exp_cap="none")
    got = {}
    for g in PER_GRADE:
        rng = _FakeRng(0.999)
        q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=rng, grade=g, thresholds=THRESHOLDS)
        got[g] = q["crit_chance"]
    assert got == PER_GRADE, got


@pytest.mark.parametrize("value,expect_hit", [
    (0.04, ["铜", "银", "金", "彩"]),   # 0.04 < 0.05/0.07/0.10/0.15 → 全中
    (0.06, ["铜", "银", "金"]),         # 0.06 < 0.07 边界：彩（0.05）不中
    (0.08, ["铜", "银"]),               # 0.08 < 0.10 边界：金（0.07）不中
    (0.12, ["铜"]),                     # 0.12 < 0.15 边界：银（0.10）不中
    (0.20, []),                         # 高于全部
])
def test_per_grade_deterministic_boundaries(value: float, expect_hit: List[str]) -> None:
    """同一注入值在不同图纸档命中的档位不同（**按档不同概率**的确定性证据）。"""
    rules = _rules(enabled=True, mult_by_grade={g: 2.0 for g in PER_GRADE},
                   exp_cap="none")
    hits = []
    for g in PER_GRADE:
        q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=_FakeRng(value), grade=g,
                        thresholds=THRESHOLDS)
        if q["crit"]:
            hits.append(g)
    assert hits == expect_hit, (value, hits)


@pytest.mark.parametrize("grade", ["铜", "银", "金", "彩"])
def test_probability_statistics_match_declared(grade: str) -> None:
    """1000 次实际触发率 ≈ 声明概率（固定种子 → 确定性、不 flaky；容差 ±0.03）。"""
    declared = PER_GRADE[grade]
    rules = _rules(enabled=True, grades=[grade], chance_by_grade={grade: declared},
                   mult_by_grade={grade: 2.0}, exp_cap="none")
    rng = random.Random(44)
    hits = sum(
        1 for _ in range(1000)
        if quality_exp(MATS, rules, EXP_BY_COLOR, rng=rng, grade=grade,
                       thresholds=THRESHOLDS)["crit"])
    rate = hits / 1000.0
    assert abs(rate - declared) <= 0.03, f"{grade}: 实际 {rate} vs 声明 {declared}"


# ---------------------------------------------------------------------------
# 4) 不生效路径：不掷、不消耗随机数（回归零影响）
# ---------------------------------------------------------------------------
def test_inactive_paths_consume_no_rng() -> None:
    cases = {
        "缺省关": _rules(),                                     # enabled 缺省 false
        "显式关": _rules(enabled=False),
        "档不适用": _rules(enabled=True, grades=["金"], chance_by_grade={"金": 0.5}),
        "概率 0": _rules(enabled=True, chance_by_grade={"铜": 0.0}, chance_default=0.0),
        "目标非品质经验": _rules(enabled=True, applies_to="cost",
                                 chance_by_grade={"铜": 0.5}),
    }
    for label, rules in cases.items():
        rng = _FakeRng(0.0)
        q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=rng, grade="铜",
                        thresholds=THRESHOLDS)
        assert q["crit"] is False, label
        assert rng.calls == 0, f"{label}：不应消耗随机数"
        assert q["exp"] == q["exp_before_crit"] == q["exp_for_level"] == 100.0, label


def test_rolls_per_craft_consumption_is_deterministic() -> None:
    """rolls=2 → 消费 2 个随机数；任一命中即暴击。"""
    rules = _rules(enabled=True, chance_by_grade={"铜": 0.5}, mult_by_grade={"铜": 2.0},
                   rolls_per_craft=2, exp_cap="none")
    # 第一个不中、第二个中 → 暴击，消费 2
    rng = _SeqRng([0.9, 0.1])
    q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=rng, grade="铜", thresholds=THRESHOLDS)
    assert q["crit"] is True and rng.calls == 2 and q["exp"] == 200.0
    # 两次都不中 → 不暴击，仍消费 2
    rng2 = _SeqRng([0.9, 0.8])
    q2 = quality_exp(MATS, rules, EXP_BY_COLOR, rng=rng2, grade="铜", thresholds=THRESHOLDS)
    assert q2["crit"] is False and rng2.calls == 2 and q2["exp"] == 100.0


# ---------------------------------------------------------------------------
# 5) 倍率 / 固定加项 / 封顶
# ---------------------------------------------------------------------------
def test_multiplier_additive_and_cap_variants() -> None:
    base = 700.0
    mats = [{"quality": "红", "count": 7, "same_affinity": False}]
    exp_by_color = {"红": 280.0}          # 280 × S(7)=2.5 → 700
    # 7 件边际 = 1+0.75+0.5+0.25+0+0+0 = 2.5 → 700
    plain = quality_exp(mats, _rules(), exp_by_color, thresholds=THRESHOLDS)
    assert plain["exp"] == pytest.approx(base)

    # 自定义倍率 + 固定加项：700×3 + 50 = 2150 → none 不封顶
    r = _rules(enabled=True, mult_by_grade={"铜": 3.0}, additive_exp=50.0,
               exp_cap="none")
    q = quality_exp(mats, r, exp_by_color, rng=_FakeRng(0.0), grade="铜",
                    thresholds=THRESHOLDS)
    assert q["exp"] == pytest.approx(2150.0) and q["crit_mult"] == 3.0

    # last_threshold 封顶到阈值末项（1080）
    r2 = _rules(enabled=True, mult_by_grade={"铜": 3.0}, additive_exp=50.0,
                exp_cap="last_threshold")
    q2 = quality_exp(mats, r2, exp_by_color, rng=_FakeRng(0.0), grade="铜",
                     thresholds=THRESHOLDS)
    assert q2["exp"] == pytest.approx(1080.0) and q2["exp_cap"] == pytest.approx(1080.0)

    # 数值封顶
    r3 = _rules(enabled=True, mult_by_grade={"铜": 3.0}, exp_cap=900)
    q3 = quality_exp(mats, r3, exp_by_color, rng=_FakeRng(0.0), grade="铜",
                     thresholds=THRESHOLDS)
    assert q3["exp"] == pytest.approx(900.0)


def test_affects_quality_level_false_keeps_base_for_level() -> None:
    rules = _rules(enabled=True, chance_by_grade={"铜": 1.0}, mult_by_grade={"铜": 5.0},
                   affects_quality_level=False, exp_cap="none")
    q = quality_exp(MATS, rules, EXP_BY_COLOR, rng=_FakeRng(0.0), grade="铜",
                    thresholds=THRESHOLDS)
    assert q["crit"] is True and q["exp"] == pytest.approx(500.0)
    assert q["exp_for_level"] == pytest.approx(100.0)      # 等级仍按暴击前经验


# ---------------------------------------------------------------------------
# 6) 回归对拍：不暴击路径逐字段等于现状
# ---------------------------------------------------------------------------
def test_explicit_off_equals_default_config() -> None:
    """显式 `enabled=false` 与「缺省（无该键）」配置产出**完全相同**的计划。"""
    p_default = _plan(_cfg(None, quality_level_thresholds=list(THRESHOLDS)),
                      random.Random(3))
    p_explicit_off = _plan(
        _cfg({"enabled": False}, quality_level_thresholds=list(THRESHOLDS)),
        random.Random(3))
    assert p_default["ok"] and p_explicit_off["ok"]
    # 逐字段（含新增键）全等 —— 缺省关不引入任何差异。
    assert p_default == p_explicit_off


def test_forced_miss_fieldwise_equals_baseline() -> None:
    """**强制不暴击**（启用但掷不中）：预批44 键集逐字段等于未启用路径。

    随机序列构造：启用路径 = [掷失(0.999)] + TAIL；未启用路径 = TAIL。
    因不暴击时品质经验不变、且消费后剩余序列一致 → 全部旧字段逐字段相等。
    """
    tail = [0.5, 0.0, 0.0]                       # 品质抽取 + 随机属性条数 + 套装条数
    off = _plan(_cfg(None, quality_level_thresholds=list(THRESHOLDS)),
                _SeqRng(list(tail)))
    on = _plan(_cfg({"enabled": True, "grades": ["铜"], "chance_by_grade": {"铜": 0.15},
                     "mult_by_grade": {"铜": 2.0}},
                    quality_level_thresholds=list(THRESHOLDS)),
               _SeqRng([0.999] + list(tail)))
    assert off["ok"] and on["ok"] and on["crit"] is False
    for key in BASELINE_PLAN_KEYS:
        if key == "quality_exp_breakdown":
            continue          # 拆解字典含新增暴击键，逐子键对拍见下
        assert on[key] == off[key], f"旧字段漂移：{key}"
    for key in BASELINE_BREAKDOWN_KEYS:
        assert on["quality_exp_breakdown"][key] == off["quality_exp_breakdown"][key], key
    # 新增键 = 附加（不改旧字段口径）
    assert set(on) == set(BASELINE_PLAN_KEYS) | set(NEW_PLAN_KEYS)
    assert set(on["quality_exp_breakdown"]) == set(BASELINE_BREAKDOWN_KEYS) | {
        "crit", "crit_active", "crit_chance", "crit_mult", "crit_rolls",
        "exp_before_crit", "exp_for_level", "exp_cap"}
    assert on["quality_exp"] == on["quality_exp_base"] == off["quality_exp"] == 100.0
    assert off["quality_exp_breakdown"]["crit"] is False


def test_breakdown_formula_unchanged() -> None:
    """暴击前经验 = 既有算式（Σ 品阶基数 × 件数边际 × 种类奖励）。"""
    q = quality_exp(MATS, _rules(), EXP_BY_COLOR)
    assert q["base_sum"] == pytest.approx(100.0)
    assert q["type_factor"] == pytest.approx(1.0)
    assert q["interaction"] == pytest.approx(1.0)
    assert q["kinds"] == 1
    assert q["exp"] == q["exp_before_crit"] == q["exp_for_level"] == pytest.approx(100.0)
    assert q["exp_cap"] is None


# ---------------------------------------------------------------------------
# 7) 编辑器可见 + 校验器
# ---------------------------------------------------------------------------
def test_editor_field_visible_with_design_intent() -> None:
    table = default_field_meta_table()
    dc = table.module("settings").fields["deep_craft"]
    rules = dc.children["craft_rules"]
    assert rules.children["quality_exp_crit"].label, "缺中文名"
    crit = rules.children["quality_exp_crit"]
    for key in ("enabled", "grades", "chance_by_grade", "chance_default", "mult_by_grade",
                "mult_default", "additive_exp", "applies_to", "affects_quality_level",
                "rolls_per_craft", "exp_cap", "rng_stream"):
        assert key in crit.children, f"缺子字段：{key}"
        assert crit.children[key].label, f"{key} 缺中文名"
    # 说明卡写清设计意图（替代拉高 cap 实现彩档 q10）
    assert "品质 10" in crit.help and "cap" in crit.help
    assert crit.children["enabled"].default is False
    assert crit.children["chance_default"].range_min == 0.0
    assert crit.children["chance_default"].range_max == 1.0


def _crit_settings(crit: Any) -> Dict[str, Any]:
    return {"settings": {"alchemy": {"mode": "simple"},
                         "deep_craft": {"enabled": True,
                                        "craft_rules": {"quality_exp_crit": crit}}}}


def test_validator_accepts_valid_and_flags_invalid() -> None:
    ok = check_pack(_crit_settings({
        "enabled": True, "grades": ["铜"],
        "chance_by_grade": {"铜": 0.15}, "mult_by_grade": {"铜": 2.0},
        "rolls_per_craft": 1, "exp_cap": "last_threshold"}),
        default_field_meta_table())
    assert not [e for e in ok.errors if "quality_exp_crit" in e.field], \
        [(e.field, e.kind) for e in ok.errors]

    bad = check_pack(_crit_settings({
        "enabled": "yes", "grades": "铜", "chance_by_grade": {"铜": 1.5},
        "mult_by_grade": {"金": -1}, "chance_default": 2, "applies_to": "cost",
        "affects_quality_level": 1, "rolls_per_craft": 9, "exp_cap": "bogus",
        "rng_stream": "global"}), default_field_meta_table())
    rules = {e.detail.get("rule") for e in bad.errors if "quality_exp_crit" in e.field}
    assert {"type", "range", "enum_invalid"} <= rules, rules


def test_validator_warns_when_enabled_but_never_triggers() -> None:
    rep = check_pack(_crit_settings({"enabled": True, "chance_by_grade": {"铜": 0.0},
                                     "chance_default": 0.0}),
                     default_field_meta_table())
    assert any(w.detail.get("rule") == "crit_never_triggers" for w in rep.warnings)
