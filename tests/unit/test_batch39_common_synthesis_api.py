"""批39 · ④公用合成 API 单测（给定投入 → 基础产出；供打造深度层调用）。

依据：`docs/深度打造_决策记录.md` §六 落地动作 3/5（深度打造的基础合成调用公用层；
本批只就位接口 + 单测，不实现打造层）。

覆盖：base_output（标准版定义）/ requirements_of（投入总量）/ preview_base_output
（只读预演）——含边界：缺配方 / 材料不足 / 货币不足 / synth_allowed=false / mode=off /
数量非法 / 数量超上限截断 / 只读（不改玩家状态）。

测试只构造内存状态，不写真实内容包。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.synthesis import (
    DEFAULT_MAX_QTY,
    base_output,
    preview_base_output,
    requirements_of,
)

ITEMS = {
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "deep_core": {"id": "deep_core", "name": "秘银核心", "type": "material"},
}
RECIPE = {
    "id": "r1", "name": "魔力药水配方", "kind": "craft", "level": 5,
    "synth_allowed": True, "master_only": False,
    "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
    "output": {"item": "mana_potion", "count": 2},
    "cost": {"coins": 30, "gem": 0},
}
DEEP_RECIPE = {
    "id": "r2", "name": "深度秘银配方", "kind": "craft", "level": 5,
    "synth_allowed": False, "master_only": True,
    "materials": [{"id": "deep_core", "count": 1}],
    "output": {"item": "deep_core", "count": 1},
    "cost": {"coins": 0, "gem": 0},
}
TIER_MAP = {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99]}


def _ctx(mode: str = "full", **over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "proficiency": {"fishing": {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0,
                                    "unlocks": {}}},
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {"water_crystal": 20, "herb": 10, "deep_core": 1},
        "items": ITEMS, "recipe": {"r1": RECIPE, "r2": DEEP_RECIPE},
        "settings": {"alchemy": {"mode": mode, "max_qty": DEFAULT_MAX_QTY,
                                 "job_tier_map": TIER_MAP}},
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# base_output / requirements_of
# ---------------------------------------------------------------------------
def test_base_output_is_standard_version_definition() -> None:
    out = base_output(RECIPE, {"items": ITEMS})
    assert out["ok"] is True
    assert out["item_id"] == "mana_potion" and out["item_name"] == "魔力药水"
    assert out["count"] == 2  # 单份产出（配方 output.count）
    assert out["quality"] == "标准" and out["quality_fixed"] is True
    assert out["traits"] == [] and out["awaken"] is None and out["core"] is None


def test_requirements_of_scales_materials_and_cost() -> None:
    req = requirements_of(RECIPE, 3)
    assert req["count"] == 3
    assert req["materials"] == [{"item": "water_crystal", "count": 15},
                               {"item": "herb", "count": 6}]
    assert req["cost"] == {"coins": 90, "gem": 0}
    # 非法数量 → 按 1 计（与 synthesize 数量归一入口同口径）
    assert requirements_of(RECIPE, 0)["count"] == 1
    assert requirements_of(RECIPE, "x")["count"] == 1


# ---------------------------------------------------------------------------
# preview_base_output：给定投入 → 基础产出（只读）
# ---------------------------------------------------------------------------
def test_preview_ok_is_read_only_and_reports_totals() -> None:
    ctx = _ctx()
    before = dict(ctx["inventory"]), dict(ctx["currencies"])
    res = preview_base_output(ctx, "r1", 2)
    assert res["ok"] is True and res["shortfall"] is None
    assert res["requirements"]["materials"][0] == {"item": "water_crystal", "count": 10}
    assert res["base_output"]["count"] == 4  # 单份 2 × 数量 2
    assert res["recipe_level"] == 5 and res["job_id"] == "fishing"
    # 只读：玩家状态零变更
    assert (dict(ctx["inventory"]), dict(ctx["currencies"])) == before


def test_preview_missing_recipe() -> None:
    res = preview_base_output(_ctx(), "不存在的配方")
    assert res["ok"] is False and res["reason"] == "recipe_not_found"
    assert res["base_output"] is None and res["requirements"] is None


def test_preview_material_shortfall_lists_diff_but_still_shows_base_output() -> None:
    ctx = _ctx(inventory={"water_crystal": 1, "herb": 0})
    res = preview_base_output(ctx, "r1", 1)
    assert res["ok"] is False and res["reason"] == "materials"
    assert res["shortfall"]["diff"] == "水结晶×4 + 草药×2"
    assert res["base_output"]["count"] == 2  # 基础产出仍可预演
    assert ctx["inventory"] == {"water_crystal": 1, "herb": 0}  # 未扣


def test_preview_coin_shortfall() -> None:
    ctx = _ctx(currencies={"coins": 10, "gem": 0})
    res = preview_base_output(ctx, "r1", 1)
    assert res["ok"] is False
    assert res["shortfall"]["raw"]["coins"] == 20


def test_preview_synth_not_allowed_boundary() -> None:
    res = preview_base_output(_ctx(), "r2")
    assert res["ok"] is False and res["reason"] == "synth_not_allowed"
    assert res["base_output"] is None


def test_preview_mode_off_boundary() -> None:
    res = preview_base_output(_ctx(mode="off"), "r1")
    assert res["ok"] is False and res["reason"] == "mode_off"


def test_preview_invalid_count_boundary() -> None:
    for bad in (0, -3, "x"):
        res = preview_base_output(_ctx(), "r1", bad)
        assert res["ok"] is False and res["reason"] == "invalid_count"


def test_preview_count_over_cap_is_advisory_truncated() -> None:
    ctx = _ctx()
    ctx["settings"]["alchemy"]["max_qty"] = 2
    res = preview_base_output(ctx, "r1", 100)
    assert res["count"] == 2
    assert res["advisory"] == "最多一次使用 2 个"


def test_preview_level_insufficient_boundary() -> None:
    ctx = _ctx()
    ctx["proficiency"] = {"fishing": {"level": 0}}   # 见习 [1,5]，配方 level 5 可 → 改高
    ctx["recipe"]["r1"] = dict(RECIPE, level=31)
    res = preview_base_output(ctx, "r1")
    assert res["ok"] is False and res["reason"] == "level_insufficient"
