"""批36 · X2 采集点校验器单测（tests/unit/test_gather_points_validation.py）。

覆盖 `qbot_rpg/content/map_models.py::validate_maps` 的采集点专项：
  · V-1Z  gather_points.id 全库唯一（图内 + 跨图）
  · V-2Z  item 引用 items.json 存在（items 未声明 → 跳过，默认放行口径）
  · V-3Z  weather_mods[].weather ∈ 注册天气集（R27）
  · V-4Z  seasons ∈ 四季 / periods ∈ 五时段 / rarity ∈ {normal,rare,gold}
  · V-5Z  rate ∈ [0,1] / respawn_minutes ≥ 1 / rate_mult ≥ 0 / rarity_shift 整数
  · 黄提示（非硬）rate < 0.01 → 「几乎采不出」
  · 结构：gather_points 非 list / 行非对象 / 必填缺失

依据：细化_2a1d §一 GP-01~GP-11 + §五（V-1Z~V-5Z）+ L250（黄提示）。
不写真实内容包（纯内存 modules 字典）。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

from qbot_rpg.content.map_models import (
    GATHER_RARITY_ENUM,
    GATHER_RATE_MIN_YELLOW,
    GATHER_RESPAWN_MIN,
    validate_maps,
)


class _Report:
    """validate_maps 收集器（鸭子类型，对齐 tests/unit/test_maps_schema.py）。"""

    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []
        self.notes: List[Dict[str, Any]] = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


_SETTINGS = {"time_cycle": {"weather": {"default_pool": ["clear", "rain"]}}}
_ITEMS = [{"id": "herb"}, {"id": "ore"}]
_ENEMIES = [{"id": "slime", "name": "史莱姆"}]


def _pack(*maps: Dict[str, Any], items: Optional[object] = None) -> Dict[str, Any]:
    mods: Dict[str, Any] = {"maps": list(maps), "settings": copy.deepcopy(_SETTINGS),
                            "enemies": copy.deepcopy(_ENEMIES)}
    if items is not False:
        mods["items"] = copy.deepcopy(_ITEMS) if items is None else items
    return mods


def _run(mods: Dict[str, Any]) -> _Report:
    rep = _Report()
    validate_maps(mods, rep)
    return rep


def _rules(rep: _Report) -> List[str]:
    return [str(e["detail"].get("rule")) for e in rep.errors]


def _warn_rules(rep: _Report) -> List[str]:
    return [str(e["detail"].get("rule")) for e in rep.warnings]


def _node(mid: str, gps: object) -> Dict[str, Any]:
    return {"id": mid, "name": mid, "monsters": [], "gather_points": gps}


_VALID_GP = {"id": "gp1", "item": "herb", "rate": 0.3, "rarity": "rare",
             "periods": ["dawn", "dusk"], "seasons": ["spring"],
             "respawn_minutes": 10,
             "weather_mods": [{"weather": "rain", "rate_mult": 1.5, "rarity_shift": 1}]}


# ---------------------------------------------------------------------------
# 正例
# ---------------------------------------------------------------------------
def test_valid_gather_point_passes_clean() -> None:
    rep = _run(_pack(_node("m1", [copy.deepcopy(_VALID_GP)])))
    assert rep.errors == [] and rep.warnings == []


def test_no_gather_points_is_legal() -> None:
    rep = _run(_pack(_node("m1", None)))
    assert rep.errors == [] and rep.warnings == []


def test_missing_optional_fields_use_defaults_no_error() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 0.5}])))
    assert rep.errors == [] and rep.warnings == []


# ---------------------------------------------------------------------------
# V-1Z id 唯一
# ---------------------------------------------------------------------------
def test_v1z_duplicate_id_within_one_map() -> None:
    gp = {"id": "dup", "item": "herb", "rate": 0.5}
    rep = _run(_pack(_node("m1", [dict(gp), dict(gp)])))
    assert "map_gather_point_id_duplicate" in _rules(rep)


def test_v1z_duplicate_id_across_maps() -> None:
    gp = {"id": "dup", "item": "herb", "rate": 0.5}
    rep = _run(_pack(_node("m1", [dict(gp)]), _node("m2", [dict(gp)])))
    assert "map_gather_point_id_duplicate" in _rules(rep)


def test_v1z_missing_id_is_red() -> None:
    rep = _run(_pack(_node("m1", [{"item": "herb", "rate": 0.5}])))
    assert "map_gather_point_id_required" in _rules(rep)


# ---------------------------------------------------------------------------
# V-2Z item 引用
# ---------------------------------------------------------------------------
def test_v2z_item_must_exist_in_items_module() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "ghost", "rate": 0.5}])))
    assert "map_gather_point_item_missing" in _rules(rep)


def test_v2z_items_module_absent_skips_reference_check() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "ghost", "rate": 0.5}]),
                     items=False))
    assert "map_gather_point_item_missing" not in _rules(rep)


def test_v2z_missing_item_is_red() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "rate": 0.5}])))
    assert "map_gather_point_item_required" in _rules(rep)


# ---------------------------------------------------------------------------
# V-3Z 天气键 ∈ 注册集
# ---------------------------------------------------------------------------
def test_v3z_unregistered_weather_key_is_red() -> None:
    gp = {"id": "gp1", "item": "herb", "rate": 0.5,
          "weather_mods": [{"weather": "snow", "rate_mult": 2}]}
    rep = _run(_pack(_node("m1", [gp])))
    assert "map_gather_point_weather_key_not_registered" in _rules(rep)


def test_v3z_registered_weather_key_passes() -> None:
    gp = {"id": "gp1", "item": "herb", "rate": 0.5,
          "weather_mods": [{"weather": "rain", "rate_mult": 2}]}
    rep = _run(_pack(_node("m1", [gp])))
    assert "map_gather_point_weather_key_not_registered" not in _rules(rep)


def test_v3z_missing_weather_key_is_red() -> None:
    gp = {"id": "gp1", "item": "herb", "rate": 0.5, "weather_mods": [{"rate_mult": 2}]}
    rep = _run(_pack(_node("m1", [gp])))
    assert "map_gather_point_weather_required" in _rules(rep)


# ---------------------------------------------------------------------------
# V-4Z 枚举
# ---------------------------------------------------------------------------
def test_v4z_invalid_season_period_rarity() -> None:
    gp = {"id": "gp1", "item": "herb", "rate": 0.5, "rarity": "epic",
          "seasons": ["旱季"], "periods": ["中午"]}
    rep = _run(_pack(_node("m1", [gp])))
    rules = _rules(rep)
    assert "map_gather_point_rarity_invalid" in rules
    assert "map_gather_point_seasons_invalid" in rules
    assert "map_gather_point_periods_invalid" in rules


def test_v4z_enums_anchored_to_spec() -> None:
    assert GATHER_RARITY_ENUM == ("normal", "rare", "gold")
    assert GATHER_RESPAWN_MIN == 1
    assert GATHER_RATE_MIN_YELLOW == 0.01


# ---------------------------------------------------------------------------
# V-5Z 区间 / 类型
# ---------------------------------------------------------------------------
def test_v5z_rate_out_of_unit_range() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 2}])))
    assert "map_gather_point_rate_range" in _rules(rep)


def test_v5z_respawn_minutes_below_one() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 0.5,
                                  "respawn_minutes": 0}])))
    assert "map_gather_point_respawn_invalid" in _rules(rep)


def test_v5z_negative_rate_mult_and_non_int_rarity_shift() -> None:
    gp = {"id": "gp1", "item": "herb", "rate": 0.5,
          "weather_mods": [{"weather": "rain", "rate_mult": -1, "rarity_shift": "x"}]}
    rep = _run(_pack(_node("m1", [gp])))
    rules = _rules(rep)
    assert "map_gather_point_rate_mult_invalid" in rules
    assert "map_gather_point_rarity_shift_invalid" in rules


def test_rate_required_when_missing() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb"}])))
    assert "map_gather_point_rate_required" in _rules(rep)


# ---------------------------------------------------------------------------
# 结构 + 黄提示
# ---------------------------------------------------------------------------
def test_gather_points_not_list_and_row_not_object() -> None:
    rep = _run(_pack(_node("m1", "oops")))
    assert "map_gather_points_not_list" in _rules(rep)
    rep2 = _run(_pack(_node("m1", ["oops"])))
    assert "map_gather_point_not_object" in _rules(rep2)


def test_yellow_hint_when_rate_near_zero() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 0.005}])))
    assert rep.errors == []
    assert "map_gather_point_rate_near_zero" in _warn_rules(rep)
    # 0.01 及以上不再黄提示
    rep2 = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 0.01}])))
    assert _warn_rules(rep2) == []


def test_weather_mods_not_list_is_red() -> None:
    rep = _run(_pack(_node("m1", [{"id": "gp1", "item": "herb", "rate": 0.5,
                                  "weather_mods": {"rain": 2}}])))
    assert "map_gather_point_weather_mods_not_list" in _rules(rep)
