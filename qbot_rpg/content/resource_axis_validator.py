"""M13 6c 资源轴注册段专项校验器（细化_6c §1.1/§1.5：V1~V4）。

文件名：resource_axis_validator.py
创建时间：2026-09-02
依据：docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
  - M1 注册段 10 字段结构（V1 红拦）；
  - 数值合法（V2 黄提示：base≥0 / max>base / max_per_pool>0）；
  - reset 三枚举（V3 红拦：battle/keep/battle_start）；
  - display/icon 可选（V4 黄提示缺失）。

功能描述：
  - validate_resource_axes(modules, report) 纯函数专项校验器（对齐
    validate_skills/validate_jobs 形态：_err/_warn 三形态收集器，module 恒为
    "stats"）——stats.json 内每个 resource 型条目的注册段校验。

工程补白：
  P-1  stats 条目 type=resource 但带 pools → 子池型（D-01 以 pools 非空判别）；
  P-2  非 resource 型条目（combat 属性）跳过（注册段只约束资源轴）。

铁律：零 NoneBot import；G0：content 层零 engine/core import；零定时器/零睡眠；
纯函数确定性；不 git commit。
"""

from __future__ import annotations

from typing import Any, Mapping

from qbot_rpg.content.resource_axis_models import (
    AXIS_TYPES,
    RESET_VALUES,
    ResourceAxisDef,
)

MODULE_NAME: str = "stats"


# =====================================================================================
# 收集器发射（三形态兼容：_Checker._err/_warn → dict → list → 鸭子类型兜底）
# =====================================================================================

def _emit(report: object, level: str, field: str, kind: str, **detail: object) -> None:
    if hasattr(report, "_err") and level == "error":
        report._err(MODULE_NAME, field, kind, **detail)
        return
    if hasattr(report, "_warn") and level == "warning":
        report._warn(MODULE_NAME, field, kind, **detail)
        return
    if isinstance(report, dict):
        rec = {"field": field, "kind": kind, "level": level, **detail}
        bucket = report.setdefault("errors" if level == "error" else "warnings", [])
        bucket.append(rec)
        return
    if isinstance(report, list):
        report.append({"field": field, "kind": kind, "level": level, **detail})
        return
    if hasattr(report, "error") and level == "error":
        report.error(MODULE_NAME, field, kind, **detail)
        return
    if hasattr(report, "warning") and level == "warning":
        report.warning(MODULE_NAME, field, kind, **detail)
        return


def _err(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "error", field, kind, **detail)


def _warn(report: object, field: str, kind: str, **detail: object) -> None:
    _emit(report, "warning", field, kind, **detail)


# =====================================================================================
# 专项校验
# =====================================================================================

def _check_axis_entry(report: object, axis_id: str, raw: Mapping[str, Any]) -> None:
    """单条资源轴注册段校验（V1~V4）。"""
    base = f"{axis_id}"
    d = ResourceAxisDef(raw)

    # V1 注册结构（红拦）：type ∈ 两型；子池型必填 pools/max_per_pool
    t = raw.get("type")
    if t is not None and t not in AXIS_TYPES:
        _err(report, f"{base}.type", "V1", rule="axis_type_invalid",
             node_id=axis_id, value=t, allowed=list(AXIS_TYPES),
             msg=f"资源轴 type {t} 不在两型（rage/element_energy 兼容旧键）（V1）")
    # 子池型判定：type 归一后 element_energy，或 raw 显式 pools（D-01 以 pools 为准）
    d_type = d.type
    is_pooled = bool(raw.get("pools")) or d_type == "element_energy"
    if is_pooled:
        pools = raw.get("pools")
        if not isinstance(pools, list) or not pools:
            _err(report, f"{base}.pools", "V1", rule="pooled_missing_pools",
                 node_id=axis_id,
                 msg="子池型资源轴必填 pools 非空数组（V1：D-01 池级展开）")
        mpp = raw.get("max_per_pool")
        if mpp is None:
            _err(report, f"{base}.max_per_pool", "V1", rule="pooled_missing_max_per_pool",
                 node_id=axis_id,
                 msg="子池型资源轴必填 max_per_pool（V1：池级上限）")

    # V2 数值合法（黄提示）：base≥0 / max>base / max_per_pool>0
    base_v = d.base
    if base_v < 0:
        _warn(report, f"{base_v}.base", "V2", rule="base_negative",
              node_id=axis_id, base=base_v, msg=f"资源轴 {axis_id} base 不能为负（V2）")
    mx = raw.get("max")
    if isinstance(mx, (int, float)) and not isinstance(mx, bool):
        if mx <= base_v:
            _warn(report, f"{base_v}.max", "V2", rule="max_not_above_base",
                  node_id=axis_id, base=base_v, max=mx,
                  msg=f"资源轴 {axis_id} max 应 > base（V2）")
    mpp = raw.get("max_per_pool")
    if isinstance(mpp, (int, float)) and not isinstance(mpp, bool) and mpp <= 0:
        _warn(report, f"{base}.max_per_pool", "V2", rule="max_per_pool_nonpositive",
              node_id=axis_id, max_per_pool=mpp,
              msg=f"资源轴 {axis_id} max_per_pool 应 > 0（V2）")

    # V3 reset 枚举（红拦）
    rs = raw.get("reset")
    if rs is not None and rs not in RESET_VALUES:
        _err(report, f"{base}.reset", "V3", rule="reset_enum_invalid",
             node_id=axis_id, value=rs, allowed=list(RESET_VALUES),
             msg=f"资源轴 {axis_id} reset {rs} 不在三枚举（battle/keep/battle_start）（V3）")

    # V4 display/icon 可选（黄提示缺失）
    if not d.display:
        _warn(report, f"{base}.display", "V4", rule="display_missing",
              node_id=axis_id, msg=f"资源轴 {axis_id} 缺 display（V4：可选提示）")
    if not d.icon:
        _warn(report, f"{base}.icon", "V4", rule="icon_missing",
              node_id=axis_id, msg=f"资源轴 {axis_id} 缺 icon（V4：可选提示）")


def validate_resource_axes(modules: Mapping[str, object], report: object) -> None:
    """资源轴注册段校验主入口（stats.json 内 resource 型条目）。

    modules 含 stats（map 形态 {axis_id: {注册段}}）；stats 缺失 → 跳过。
    非 resource 型条目（combat 属性）跳过（P-2）。
    """
    stats = modules.get("stats")
    if not isinstance(stats, Mapping):
        return
    for axis_id, raw in stats.items():
        if not isinstance(raw, Mapping):
            continue
        t = raw.get("type")
        # P-2：明确 combat 型条目（属性）跳过；其余（含非法 type）进注册段校验
        # ——非法 type 由 V1 红拦，不能在入口静默放行。
        if t == "combat":
            continue
        _check_axis_entry(report, str(axis_id), raw)


__all__ = ["MODULE_NAME", "validate_resource_axes"]
