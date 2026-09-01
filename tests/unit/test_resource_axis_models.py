"""M13 6c 资源轴注册段模型/校验单测（tests/unit/test_resource_axis_models.py · M13 批8 路8A）。

覆盖细化_6c §1.1/§1.5：
  - ResourceAxisDef 10 字段默认值兜底 / 两型判别（D-01）
  - resource_axis_fields() 10 键登记表
  - validate_resource_axes V1~V4（红黄分级）
  - stats.json 扩展（rage 数值型 + element_energy 子池型）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from qbot_rpg.content.resource_axis_models import (
    AXIS_TYPES,
    RESET_VALUES,
    ResourceAxisDef,
    resource_axis_fields,
)
from qbot_rpg.content.resource_axis_validator import validate_resource_axes


# ---------------------------------------------------------------------------
# 收集器 / 夹具
# ---------------------------------------------------------------------------
class _Report:
    def __init__(self) -> None:
        self.errors: List[Dict[str, Any]] = []
        self.warnings: List[Dict[str, Any]] = []

    def _err(self, module: str, field: str, kind: str, **detail: Any) -> None:
        self.errors.append({"field": field, "kind": kind, "detail": detail})

    def _warn(self, module: str, field: str, kind: str, **detail: Any) -> None:
        self.warnings.append({"field": field, "kind": kind, "detail": detail})


def _rules(report: _Report, level: str) -> set:
    return {e["detail"].get("rule", "") for e in getattr(report, level)}


def _run(stats: Mapping[str, Any]) -> _Report:
    report = _Report()
    validate_resource_axes({"stats": stats}, report)
    return report


def _numeric_axis(**over: Any) -> Dict[str, Any]:
    a: Dict[str, Any] = {"name": "怒气", "type": "rage", "base": 0, "max": 100}
    a.update(over)
    return a


def _pooled_axis(**over: Any) -> Dict[str, Any]:
    a: Dict[str, Any] = {
        "name": "元素能量", "type": "element_energy",
        "base": 0, "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
    }
    a.update(over)
    return a


# ---------------------------------------------------------------------------
# ResourceAxisDef 模型
# ---------------------------------------------------------------------------
def test_def_defaults() -> None:
    d = ResourceAxisDef({})
    assert d.name == "" and d.type == "resource"
    assert d.base == 0 and d.max == 100
    assert d.reset == "battle"
    assert d.is_pooled is False


def test_def_numeric() -> None:
    d = ResourceAxisDef(_numeric_axis())
    assert d.name == "怒气" and d.type == "rage"
    assert d.base == 0 and d.max == 100
    assert d.is_pooled is False


def test_def_pooled() -> None:
    d = ResourceAxisDef(_pooled_axis())
    assert d.type == "element_energy"
    assert d.is_pooled is True
    assert d.pools == ("fire", "water", "wind")
    assert d.max_per_pool == 3
    assert d.pool_icons["fire"] == "🔥"


def test_def_type_normalize_resource_custom() -> None:
    """resource_custom → element_energy 归一（D-01b/P-1）。"""
    d = ResourceAxisDef({"type": "resource_custom", "pools": ["a", "b"]})
    assert d.type == "element_energy"
    assert d.is_pooled is True


def test_def_fields_table_10_keys() -> None:
    """resource_axis_fields() 恰好 10 键（M1 注册段）。"""
    f = resource_axis_fields()
    assert set(f.keys()) == {
        "name", "type", "icon", "base", "max", "reset",
        "display", "max_per_pool", "pools", "pool_icons",
    }


def test_def_fields_enum_consistency() -> None:
    """登记表枚举与常量一致。"""
    f = resource_axis_fields()
    assert set(f["type"].enum) == set(AXIS_TYPES)
    assert set(f["reset"].enum) == set(RESET_VALUES)


# ---------------------------------------------------------------------------
# validate_resource_axes V1~V4
# ---------------------------------------------------------------------------
def test_v1_type_invalid_red() -> None:
    r = _run({"rage": _numeric_axis(type="bogus")})
    assert "axis_type_invalid" in _rules(r, "errors")


def test_v1_pooled_missing_pools_red() -> None:
    r = _run({"ee": _pooled_axis(pools=None)})
    assert "pooled_missing_pools" in _rules(r, "errors")


def test_v1_pooled_missing_max_per_pool_red() -> None:
    r = _run({"ee": _pooled_axis(max_per_pool=None)})
    assert "pooled_missing_max_per_pool" in _rules(r, "errors")


def test_v2_base_negative_warn() -> None:
    r = _run({"rage": _numeric_axis(base=-1)})
    assert "base_negative" in _rules(r, "warnings")
    assert r.errors == []


def test_v2_max_not_above_base_warn() -> None:
    r = _run({"rage": _numeric_axis(base=50, max=50)})
    assert "max_not_above_base" in _rules(r, "warnings")


def test_v3_reset_enum_red() -> None:
    r = _run({"rage": _numeric_axis(reset="bogus")})
    assert "reset_enum_invalid" in _rules(r, "errors")


def test_v3_reset_valid_ok() -> None:
    for v in RESET_VALUES:
        r = _run({"rage": _numeric_axis(reset=v)})
        assert "reset_enum_invalid" not in _rules(r, "errors")


def test_v4_display_icon_missing_warn() -> None:
    r = _run({"rage": _numeric_axis()})
    assert "display_missing" in _rules(r, "warnings")
    assert "icon_missing" in _rules(r, "warnings")


def test_legal_numeric_zero_red_zero_warn() -> None:
    """完整数值型（含 icon/display）→ 零红零黄。"""
    r = _run({"rage": _numeric_axis(icon="💢", display="status_line", reset="battle")})
    assert r.errors == [], f"合法数值型应零红，got {r.errors}"
    assert r.warnings == [], f"合法数值型应零黄，got {r.warnings}"


def test_legal_pooled_zero_red() -> None:
    """完整子池型 → 零红（V4 黄提示可容忍）。"""
    r = _run({"element_energy": _pooled_axis(icon="✨", display="pool_line")})
    assert r.errors == [], f"合法子池型应零红，got {r.errors}"


def test_combat_stats_skipped() -> None:
    """combat 属性条目跳过（P-2：注册段只约束资源轴）。"""
    r = _run({"str": {"name": "力量", "type": "combat", "base": 10, "growth": 2}})
    assert r.errors == [] and r.warnings == []


def test_stats_missing_skips() -> None:
    report = _Report()
    validate_resource_axes({}, report)
    assert report.errors == [] and report.warnings == []


# ---------------------------------------------------------------------------
# stats.json 扩展（test_demo 真实数据）
# ---------------------------------------------------------------------------
def test_demo_stats_rage_and_element_energy() -> None:
    """test_demo stats.json 含 rage（数值型）+ element_energy（子池型）注册段。"""
    import json
    from pathlib import Path

    p = Path(__file__).resolve().parents[2] / "content" / "test_demo" / "stats.json"
    stats = json.loads(p.read_text(encoding="utf-8"))
    rage = ResourceAxisDef(stats["rage"])
    assert rage.type == "rage" and rage.max == 100
    assert rage.is_pooled is False
    ee = stats.get("element_energy")
    if ee:
        d = ResourceAxisDef(ee)
        assert d.is_pooled is True
        assert d.pools
