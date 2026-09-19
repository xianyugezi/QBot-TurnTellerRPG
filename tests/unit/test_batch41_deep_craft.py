"""批41 · 深度打造：图纸 / 材料 / 打造主流程（等级·cost·品质经验·品质抽取）单测。

依据：`docs/深度打造_决策记录.md` §一 H1/H2/H6、§二 N1~N4/N6、§六；
`打造系统_原案_20260919.md` §5/§6/§12/§13；`打造系统_B_数值与经验规划.md` §1~§3。

覆盖：
  · **等级公式**：全同级材料 → 该级装备（数值断言）；主材料占比生效；
  · **品质经验 / 品质等级**：确定性输入 → 经验累计与等级；**每次独立**（不跨件累计）；
  · **品质抽取**：13 行概率表逐行验证（权重和=100、红仅行 10+、铜行10=5%、银/金/彩上移
    1/2/3 行）；注入随机源 → 确定性落桶；
  · **cost**：超限拒绝；图纸档缩放生效；下限可配；
  · **防退化 N2**：等级带拦截「低阶材料堆满预算」；主材料槽缺失拒绝；
  · **校验器**：引用存在性 / 枚举 / 范围（材料等级·成本·品质，图纸档/产出/部位/配方，
    等级带、随机条数、概率阶梯顶档行）。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

import pytest

from qbot_rpg.content.deep_craft_settings import (
    DEFAULT_BLUEPRINT_GRADES,
    DEFAULT_QUALITY_DRAW_TABLE,
    DEFAULT_QUALITY_EXP_BY_COLOR,
    read_deep_craft_settings,
)
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.deep_craft import (
    REJECT_COST_OVER,
    REJECT_LEVEL_BAND,
    REJECT_MAIN_MATERIAL,
    REJECT_NOT_LEARNED,
    REJECT_PER_KIND,
    craft_cost,
    draw_quality,
    equipment_level,
    plan_craft,
    quality_exp,
    quality_level_of,
)

RULES = read_deep_craft_settings({})["craft_rules"]


# ---------------------------------------------------------------------------
# 脚手架（不写任何真实内容包：id 全为测试自造）
# ---------------------------------------------------------------------------
class _FakeRng:
    """确定性单值随机源（返回预置 [0,1)；用于落桶边界断言）。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.value


def _blueprint(**over: Any) -> Dict[str, Any]:
    bp: Dict[str, Any] = {
        "id": "bp1",
        "name": "测试图纸",
        "blueprint_output": "gear_out",
        "blueprint_slot": "weapon",
        "blueprint_grade": "铜",
        "blueprint_level_band": {"min": 2, "max": 35},
        "blueprint_material_slots": [{"role": "main", "item": "m_main", "count": 1}],
        "blueprint_fixed_stats": [{"stat": "atk", "value": 10}],
        "affinities": {"aff_a": 1.0},
    }
    bp.update(over)
    return bp


def _mdef(level: int, quality: str = "白", cost: int = 10,
          affinities: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    return {"material_level": level, "material_quality": quality, "craft_cost": cost,
            "affinities": affinities or {}}


def _plan(materials: List[Dict[str, Any]], defs: Dict[str, Any],
          bp: Optional[Dict[str, Any]] = None, *, learned: bool = True,
          rng: Any = None, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return plan_craft(
        blueprint=bp or _blueprint(),
        config=config or read_deep_craft_settings({}),
        materials=materials,
        material_defs=defs,
        learned=learned,
        rng=rng if rng is not None else random.Random(7),
        affinity_reactions=(),
    )


# ---------------------------------------------------------------------------
# 1) 等级公式（原案 §5）
# ---------------------------------------------------------------------------
def test_same_level_materials_yield_that_level() -> None:
    """**完全同级材料 → 该级装备**（原案 §5 明文；数值断言 1/15/35 级）。"""
    for lv in (1, 7, 15, 35):
        got = equipment_level(
            [{"level": lv, "count": 2, "role": "main"},
             {"level": lv, "count": 6, "role": "free"}],
            RULES["material_level_weight"], RULES["level_rounding"])
        assert got == lv


def test_main_material_weight_dominates() -> None:
    """主材料占比大 → 换主材料能拉动整件等级（0.6 vs 0.4）。"""
    low_main = equipment_level(
        [{"level": 5, "count": 1, "role": "main"},
         {"level": 35, "count": 1, "role": "free"}],
        RULES["material_level_weight"], "floor")
    high_main = equipment_level(
        [{"level": 35, "count": 1, "role": "main"},
         {"level": 5, "count": 1, "role": "free"}],
        RULES["material_level_weight"], "floor")
    assert low_main == 17      # 5×0.6 + 35×0.4 = 17.0
    assert high_main == 23     # 35×0.6 + 5×0.4 = 23.0
    assert high_main > low_main


@pytest.mark.parametrize("mode,expect", [("floor", 29), ("round", 30), ("ceil", 30)])
def test_level_rounding_modes(mode: str, expect: int) -> None:
    # 主 35（0.6）+ 自由 20/22/23（0.4 三件均分）= 21 + 8.667 = 29.667
    got = equipment_level(
        [{"level": 35, "count": 1, "role": "main"},
         {"level": 20, "count": 1, "role": "free"},
         {"level": 22, "count": 1, "role": "free"},
         {"level": 23, "count": 1, "role": "free"}],
        RULES["material_level_weight"], mode)
    assert got == expect


# ---------------------------------------------------------------------------
# 2) 品质经验 / 品质等级（原案 §6/§12）
# ---------------------------------------------------------------------------
def test_quality_exp_formula_and_affinity_bonus() -> None:
    """品阶基数 × 相性系数 × 件数边际；同相性 ×1.5；件数边际递减。"""
    plain = quality_exp([{"quality": "白", "count": 1, "same_affinity": False}],
                        RULES, DEFAULT_QUALITY_EXP_BY_COLOR)
    same = quality_exp([{"quality": "白", "count": 1, "same_affinity": True}],
                       RULES, DEFAULT_QUALITY_EXP_BY_COLOR)
    assert plain["exp"] == pytest.approx(1.0)
    assert same["exp"] == pytest.approx(1.5)           # 与图纸同相性 ×1.5（原案 §6）

    multi = quality_exp([{"quality": "紫", "count": 3, "same_affinity": False}],
                        RULES, DEFAULT_QUALITY_EXP_BY_COLOR)
    # 件数边际：1 + 0.75 + 0.5 = 2.25（slot_decay=0.25）
    assert multi["exp"] == pytest.approx(4.2 * 2.25)

    fifth = quality_exp([{"quality": "白", "count": 5, "same_affinity": False}],
                        RULES, DEFAULT_QUALITY_EXP_BY_COLOR)
    assert fifth["exp"] == pytest.approx(1 + 0.75 + 0.5 + 0.25 + 0.0)

    kinds = quality_exp(
        [{"quality": "白", "count": 1, "same_affinity": False},
         {"quality": "白", "count": 1, "same_affinity": False}],
        RULES, DEFAULT_QUALITY_EXP_BY_COLOR)
    assert kinds["exp"] == pytest.approx(2.0 * 1.03)   # 每多 1 种 ×1.03


def test_quality_level_thresholds() -> None:
    th = RULES["quality_level_thresholds"]
    assert [quality_level_of(v, th) for v in (0, 24, 25, 59, 60, 1080, 9999)] == \
        [1, 1, 2, 2, 3, 10, 10]
    assert quality_level_of("bad", th) == 0


def test_quality_exp_is_per_craft_independent() -> None:
    """**每次打造独立**（原案 §12）：连续两次同投入 → 经验相同（不跨件累计）。"""
    defs = {"m_main": _mdef(15, "紫", 30)}
    mats = [{"id": "m_main", "count": 2}]
    first = _plan(mats, defs, rng=random.Random(1))
    second = _plan(mats, defs, rng=random.Random(1))
    assert first["ok"] and second["ok"]
    assert first["quality_exp"] == second["quality_exp"]
    # 经验不因「已经打造过一次」而叠加（若跨件累计，第二次会翻倍）
    one = quality_exp([{"quality": "紫", "count": 2, "same_affinity": False}],
                      RULES, DEFAULT_QUALITY_EXP_BY_COLOR)["exp"]
    assert first["quality_exp"] == pytest.approx(one)


# ---------------------------------------------------------------------------
# 3) 品质抽取：13 行概率表逐行验证（原案 §13 + B 路 §3）
# ---------------------------------------------------------------------------
def test_probability_ladder_13_rows_sum_to_100() -> None:
    ladder = DEFAULT_QUALITY_DRAW_TABLE["ladder"]
    assert sorted(int(k) for k in ladder) == list(range(1, 14))
    for row, weights in ladder.items():
        assert sum(weights.values()) == 100, f"第 {row} 行权重和 != 100"


def test_red_only_from_row_10_and_copper_row10_is_5() -> None:
    """红品质仅第 10 行起出现；**铜行10 = 5%**（原案 §6）。"""
    ladder = DEFAULT_QUALITY_DRAW_TABLE["ladder"]
    for row in range(1, 10):
        assert "红" not in ladder[str(row)], f"第 {row} 行不应有红"
    assert ladder["10"]["红"] == 5
    assert ladder["11"]["红"] == 10
    assert ladder["12"]["红"] == 20
    assert ladder["13"]["红"] == 40


@pytest.mark.parametrize("grade,offset,row,red", [
    ("铜", 0, 10, 5), ("银", 1, 11, 10), ("金", 2, 12, 20), ("彩", 3, 13, 40)])
def test_grade_shifts_ladder_by_offset(grade: str, offset: int, row: int, red: int) -> None:
    """银/金/彩 = 铜表上移 1/2/3 行（品质等级 10 → 行 10+offset）。"""
    grades = {g["id"]: g for g in DEFAULT_BLUEPRINT_GRADES}
    assert grades[grade]["level_offset"] == offset
    table = DEFAULT_QUALITY_DRAW_TABLE
    color = draw_quality(_FakeRng(0.999), table, 10, offset)   # 落最后一项
    assert color == "红"
    assert table["ladder"][str(row)]["红"] == red


def test_draw_quality_bucket_boundaries_are_deterministic() -> None:
    """注入随机源 → 确定性落桶（铜行1：白 75 / 绿 25）。"""
    table = DEFAULT_QUALITY_DRAW_TABLE
    assert draw_quality(_FakeRng(0.0), table, 1, 0) == "白"
    assert draw_quality(_FakeRng(0.7499), table, 1, 0) == "白"
    assert draw_quality(_FakeRng(0.75), table, 1, 0) == "绿"
    assert draw_quality(_FakeRng(0.9999), table, 1, 0) == "绿"
    # 铜 10 级：蓝5 紫40 橙50 红5 → 0.95 起红（累计 5/40/50 → 红在 [0.95,1)）
    assert draw_quality(_FakeRng(0.9499), table, 10, 0) == "橙"
    assert draw_quality(_FakeRng(0.95), table, 10, 0) == "红"
    # 行缺失（超出阶梯）→ None
    assert draw_quality(_FakeRng(0.5), table, 10, 4) is None


def test_plan_uses_injected_rng_for_quality() -> None:
    """主流程品质色由注入 rng 决定（同 rng 同结果；不同 rng 可不同）。"""
    # 自定义阈值 → 保证品质等级 = 10（行 10；铜表 = 蓝5/紫40/橙50/红5）
    cfg = read_deep_craft_settings({"deep_craft": {"craft_rules": {
        "quality_level_thresholds": [0] * 10}}})
    defs = {"m_main": _mdef(15, "红", 30)}
    mats = [{"id": "m_main", "count": 5}]
    a = _plan(mats, defs, rng=_FakeRng(0.0), config=cfg)
    b = _plan(mats, defs, rng=_FakeRng(0.0), config=cfg)
    c = _plan(mats, defs, rng=_FakeRng(0.9999), config=cfg)
    assert a["quality_level"] == b["quality_level"] == c["quality_level"] == 10
    assert a["color_row"] == 10
    assert a["quality"] == b["quality"] == "蓝"      # 铜 10 行首桶 = 蓝
    assert c["quality"] == "红"                       # 末桶 = 红（5%）


# ---------------------------------------------------------------------------
# 4) cost 约束（N1/N3；按图纸档缩放）
# ---------------------------------------------------------------------------
def test_cost_formula() -> None:
    cc = craft_cost([{"cost": 100, "count": 2}, {"cost": 50, "count": 1}], RULES)
    assert cc["kinds"] == 2
    assert cc["material"] == 250
    assert cc["cost"] == 60 + 20 * 2 + 250


def test_cost_over_cap_rejected_with_grade_scaling() -> None:
    """超限拒绝；同一投入在低档被拒、在高档放行（图纸档缩放生效）。"""
    defs = {"m_main": _mdef(30, "蓝", 400), "m_free": _mdef(30, "蓝", 400)}
    mats = [{"id": "m_main", "count": 1}, {"id": "m_free", "count": 3}]
    cheap = _blueprint(blueprint_grade="铜")
    rich = _blueprint(blueprint_grade="彩")
    low = _plan(mats, defs, cheap)
    high = _plan(mats, defs, rich)
    total = craft_cost([{"cost": 400, "count": 1}, {"cost": 400, "count": 3}], RULES)["cost"]
    assert low["ok"] is False and low["reason"] == REJECT_COST_OVER
    assert low["cap"] == 600                              # 铜档上限
    assert high["ok"] is True and high["cost"] == total   # 彩档上限 86000 → 放行
    assert total > 600


def test_cost_cap_override_per_blueprint() -> None:
    defs = {"m_main": _mdef(10, "白", 100)}
    bp = _blueprint(blueprint_grade="彩", blueprint_cost_cap=150)
    got = _plan([{"id": "m_main", "count": 1}], defs, bp)
    assert got["ok"] is False and got["reason"] == REJECT_COST_OVER
    assert got["cap"] == 150


# ---------------------------------------------------------------------------
# 5) 防退化 N2
# ---------------------------------------------------------------------------
def test_level_band_blocks_low_tier_budget_stuffing() -> None:
    """**低阶便宜材料堆满预算**的路径被等级带拦住（N2 ①；贴证据）。"""
    bp = _blueprint(blueprint_level_band={"min": 27, "max": 35})
    # 30 件 5 级便宜材料：cost 足够高，但等级只有 5 → 等级带拒绝
    defs = {"m_main": _mdef(5, "白", 5)}
    got = _plan([{"id": "m_main", "count": 5}], defs, bp)
    assert got["ok"] is False and got["reason"] == REJECT_LEVEL_BAND
    assert got["level"] == 5 and got["band"] == [27, 35]


def test_main_material_slot_missing_rejected() -> None:
    """图纸声明主材料槽 → 投入里没有材料填它 → 拒绝（N2 ①）。"""
    bp = _blueprint(blueprint_material_slots=[{"role": "main", "item": "m_main", "count": 1}])
    defs = {"m_free": _mdef(20, "蓝", 10)}
    got = _plan([{"id": "m_free", "count": 1}], defs, bp)
    assert got["ok"] is False and got["reason"] == REJECT_MAIN_MATERIAL


def test_not_learned_and_per_kind_and_no_materials() -> None:
    defs = {"m_main": _mdef(15, "蓝", 10)}
    assert _plan([{"id": "m_main", "count": 1}], defs, learned=False)["reason"] \
        == REJECT_NOT_LEARNED
    got = _plan([{"id": "m_main", "count": 6}], defs)
    assert got["ok"] is False and got["reason"] == REJECT_PER_KIND and got["limit"] == 5


# ---------------------------------------------------------------------------
# 6) 校验器：引用存在性 / 枚举 / 范围（A 节）
# ---------------------------------------------------------------------------
def _check(modules: Dict[str, Any]) -> Any:
    return check_pack(modules, default_field_meta_table())


def _settings(**dc: Any) -> Dict[str, Any]:
    return {"settings": {"deep_craft": dc, "slot_defs": {"weapon": {}}}}


def test_validator_refs_and_enums_and_ranges() -> None:
    mods = _settings(
        blueprint_grades=[{"id": "铜", "level_offset": 0, "cost_cap": 600}],
        quality_colors=[{"id": "白"}, {"id": "红"}],
    )
    mods["items"] = [
        {"id": "bp_ok", "name": "图", "blueprint_grade": "铜", "blueprint_output": "g1",
         "blueprint_slot": "weapon", "blueprint_recipe": "r1",
         "blueprint_level_band": {"min": 2, "max": 8},
         "blueprint_material_slots": [{"role": "main", "item": "m1"}],
         "blueprint_random_stat_count": {"min": 0, "max": 2}},
        {"id": "m1", "name": "料", "material_level": 3, "material_quality": "白",
         "craft_cost": 5},
    ]
    mods["equipment"] = [{"id": "g1", "name": "装备"}]
    mods["recipe"] = [{"id": "r1", "name": "配方", "kind": "craft", "level": 1,
                       "materials": [{"id": "m1", "count": 1}],
                       "output": {"item": "g1", "count": 1}}]
    rep = _check(mods)
    assert not [e for e in rep.errors if e.module in ("items", "equipment")], \
        [(e.field, e.kind, dict(e.detail)) for e in rep.errors]

    bad = dict(mods)
    bad["items"] = [
        {"id": "bp_bad", "name": "图", "blueprint_grade": "不存在",
         "blueprint_output": "不存在", "blueprint_slot": "不存在",
         "blueprint_recipe": "不存在",
         "blueprint_level_band": {"min": 9, "max": 2},
         "material_level": 0, "material_quality": "不存在", "craft_cost": -1},
    ]
    rep2 = _check(bad)
    rules = {e.detail.get("rule") for e in rep2.errors}
    assert "grade_ref_missing" in rules
    assert "item_ref_missing" in rules
    assert "slot_ref_missing" in rules
    assert "recipe_ref_missing" in rules
    assert "band_reversed" in rules
    assert "range" in rules
    assert "color_ref_missing" in rules


def test_validator_rejects_top_color_before_row_10() -> None:
    """顶档颜色（按 quality_colors 顺序最后一项）出现在第 10 行之前 → 红拦。"""
    mods = _settings(
        quality_colors=[{"id": "白"}, {"id": "红"}],
        quality_draw_table={"ladder": {"1": {"白": 90, "红": 10}}})
    rep = _check(mods)
    assert any(e.detail.get("rule") == "top_color_row" for e in rep.errors)


def test_validator_ladder_row_sum_warns() -> None:
    mods = _settings(
        quality_colors=[{"id": "白"}, {"id": "红"}],
        quality_draw_table={"ladder": {"10": {"白": 50, "红": 20}}})
    rep = _check(mods)
    assert any(w.detail.get("rule") == "row_sum" for w in rep.warnings)


# ---------------------------------------------------------------------------
# 7) 字段元数据可见性（一号原则：中文名/类型/枚举/范围/引用/必填）
# ---------------------------------------------------------------------------
def test_fields_are_editor_visible() -> None:
    table = default_field_meta_table()
    items = table.module("items")
    assert items is not None and items.fields
    for key in ("material_level", "material_quality", "craft_cost",
                "blueprint_grade", "blueprint_output", "blueprint_slot",
                "blueprint_recipe", "blueprint_level_band", "blueprint_material_slots",
                "blueprint_fixed_stats", "blueprint_random_stat_count",
                "blueprint_random_set_affix_count", "blueprint_passive",
                "blueprint_learn", "blueprint_cost_cap"):
        fm = items.fields.get(key)
        assert fm is not None, f"items 缺字段元数据：{key}"
        assert fm.label, f"{key} 缺中文名"
    assert items.fields["material_level"].range_min == 1
    assert items.fields["blueprint_output"].ref_target == "item"
    assert items.fields["blueprint_recipe"].ref_target == "recipe"
    assert items.fields["blueprint_material_slots"].type == "list"

    settings = table.module("settings")
    assert settings is not None and settings.fields
    dc = settings.fields.get("deep_craft")
    assert dc is not None and dc.label
    for key in ("craft_rules", "quality_colors", "blueprint_grades",
                "quality_draw_table", "quality_exp_by_color"):
        assert key in dc.children, f"settings.deep_craft 缺字段：{key}"
        assert dc.children[key].label
    grade = dc.children["blueprint_grades"].element
    assert grade is not None and set(grade.children) >= {"id", "name", "level_offset",
                                                        "cost_cap"}
    assert grade.children["id"].required is True
