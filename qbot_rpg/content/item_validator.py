"""items / equipment 专项校验（批22 · A2：使用/穿戴等级 `use_level` 硬口径 int ≥ 1）。

依据：`CakeGame字段差距分析.md` §三 A2——「使用/穿戴等级门槛，使用时校验」。

为什么需要专项（而不是纯元数据）：泛型校验器 `_check_number` 只做「非整数 → R-1 /
负数 → R-2」，`range_min` 仅产生 Y-1 黄提示（`validator.py:_hint_number`）。
`FieldMeta` 没有「硬下界」属性（models.py），而 `use_level` 的 0/负数按契约是**非法值**
（不是「常见区间外」），故在此补红拦 `IV-1`。

口径：
  - `use_level` 缺失 → 不判（不限等级）；
  - 非整数（含 bool）/ 非数值 → 交给泛型 R-1，本项不重复报（避免双红）；
  - 整数 < 1（0/负数）→ `IV-1` 红拦（负数同时触发泛型 R-2，双红可接受——门禁只严不宽）；
  - 引用类字段 `job_restrict` 的存在性走元数据 `ref_target="job"` 的泛型 R-4，本文件不重复。

鸭子类型 `report`（`_Checker` 或测试收集器）：只要求 `_err(module, field, kind, **detail)`。
"""
from __future__ import annotations

from typing import Any, Mapping

__all__ = ["validate_items", "validate_equipment"]

_USE_LEVEL_MIN = 1


def _check_use_level(module: str, report: Any, entries: Any) -> None:
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or "use_level" not in entry:
            continue
        v = entry.get("use_level")
        if isinstance(v, bool) or not isinstance(v, int):
            continue  # 非整数 → 泛型 R-1（不重复报）
        if v < _USE_LEVEL_MIN:
            report._err(
                module, f"{module}.{idx}.use_level", "IV-1", rule="use_level_min",
                value=v, minimum=_USE_LEVEL_MIN,
                msg="use_level 必须 ≥ 1（0/负数非法；不设门槛请删除该字段）",
            )


def validate_items(modules: Mapping[str, Any], report: Any) -> None:
    """items 模块 `use_level` 硬口径（IV-1）。"""
    _check_use_level("items", report, modules.get("items"))


def validate_equipment(modules: Mapping[str, Any], report: Any) -> None:
    """equipment 模块 `use_level` 硬口径（IV-1）。"""
    _check_use_level("equipment", report, modules.get("equipment"))
