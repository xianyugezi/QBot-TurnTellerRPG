"""M13 6c 资源轴校验 V5 单测（tests/unit/test_resource_axis_validator_v5.py · M13 批12 路12A）。

覆盖细化_6c §五 V5（变量引用黄提示）：
  - [我方资源:ID] / [对方资源:ID] 引用未注册轴 → 黄提示
  - 子池级 [我方资源:axis.pool] → 轴段检查
  - 已注册轴 → 零黄提示
  - V1~V4 回归

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.content.resource_axis_validator import validate_resource_axes


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


def _run(modules: Dict[str, Any]) -> _Report:
    report = _Report()
    validate_resource_axes(modules, report)
    return report


def _stats() -> Dict[str, Any]:
    return {
        "rage": {"name": "怒气", "type": "rage", "base": 0, "max": 100},
        "element_energy": {"name": "元素能量", "type": "element_energy",
                           "base": 0, "max_per_pool": 3,
                           "pools": ["fire", "water", "wind"]},
    }


def test_v5_unregistered_axis_in_condition_warns() -> None:
    """条件 [我方资源:怒气] 引用未注册轴 → V5 黄提示。"""
    modules = {
        "stats": _stats(),
        "effects": [{"id": "e1", "condition": {"var": "[我方资源:怒气]", "op": "ge", "value": 50}}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" in _rules(r, "warnings"), \
        f"未注册轴引用应黄提示，got {r.warnings}"


def test_v5_registered_axis_no_warn() -> None:
    """条件 [我方资源:rage] 引用已注册轴 → 零 V5 黄提示。"""
    modules = {
        "stats": _stats(),
        "effects": [{"id": "e1", "condition": {"var": "[我方资源:rage]", "op": "ge", "value": 50}}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" not in _rules(r, "warnings")


def test_v5_pooled_ref_checks_axis_segment() -> None:
    """子池级 [我方资源:element_energy.fire] → 轴段 element_energy 已注册 → 零黄。"""
    modules = {
        "stats": _stats(),
        "effects": [{"id": "e1", "condition": {
            "var": "[我方资源:element_energy.fire]", "op": "ge", "value": 2,
        }}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" not in _rules(r, "warnings")


def test_v5_pooled_ref_unregistered_axis_warns() -> None:
    """子池级 [我方资源:ghost.fire] → 轴段 ghost 未注册 → V5 黄提示。"""
    modules = {
        "stats": _stats(),
        "effects": [{"id": "e1", "condition": {
            "var": "[我方资源:ghost.fire]", "op": "ge", "value": 2,
        }}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" in _rules(r, "warnings")


def test_v5_enemy_side_ref_checks() -> None:
    """对方侧 [对方资源:rage] → 同检查。"""
    modules = {
        "stats": _stats(),
        "conditional": [{"id": "c1", "var": "[对方资源:ghost]", "op": "eq", "value": 1}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" in _rules(r, "warnings")


def test_v5_text_condition_scan() -> None:
    """文本形态条件含 [我方资源:X] → 扫描。"""
    modules = {
        "stats": _stats(),
        "effects": [{"id": "e1", "condition": "当 [我方资源:怒气] >= 50 时"}],
    }
    r = _run(modules)
    assert "v5_axis_ref_unregistered" in _rules(r, "warnings")


def test_v5_no_condition_modules_no_warn() -> None:
    """无 effects/conditional 模块 → 零 V5 黄提示。"""
    modules = {"stats": _stats()}
    r = _run(modules)
    assert "v5_axis_ref_unregistered" not in _rules(r, "warnings")


def test_v5_regression_v1_v4_still_work() -> None:
    """V1~V4 回归：非法 type 仍红拦。"""
    modules = {"stats": {"bogus": {"type": "bad_type"}}}
    r = _run(modules)
    assert "axis_type_invalid" in _rules(r, "errors")
