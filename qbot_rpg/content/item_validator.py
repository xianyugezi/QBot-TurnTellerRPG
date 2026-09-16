"""items / equipment 专项校验（批22 · A2 使用等级 + 批26 · α组装备侧）。

依据：
  - 批22 · A2：`CakeGame字段差距分析.md` §三 A2「使用/穿戴等级门槛，使用时校验」——
    `use_level` 硬口径 int ≥ 1（IV-1）。
  - 批26 · α组（装备侧）：`CakeGame字段差距_补漏.md` §一 组 α——
      α1 `grant_skills`   level ≥ 1（IV-2 红拦；skill 引用缺失走泛型 R-4）
      α2 `max_hold`       取值仅 0 / 1 / -1（IV-3 红拦）
      α3 `skill_amp`      type 枚举 + value 在 settings.forge.skill_amp_bounds 内
                          （IV-4 红拦；上下限读 content/forge_settings，不硬编码）
      α5 `attack_override` 替换技能须由本件 grant_skills 赋予（Y-9 黄提示，不硬拦）

为什么需要专项（而不是纯元数据）：泛型校验器 `_check_number` 只做「非整数 → R-1 /
负数 → R-2」，`range_min` 仅产生 Y-1 黄提示（`validator.py:_hint_number`）。
`FieldMeta` 没有「硬下界/硬枚举」属性（models.py），而 grant level 0、max_hold=2、
增幅超限按契约是**非法值**（不是「常见区间外」），故在此补红拦。

超限口径（本批拍板，二选一）：**红拦**（非钳制）。依据：门禁只严不宽；钳制会静默
改写作者填写的数值，让「超限」在包加载期不可见（与 §一 α3「全局上下限」护栏意图
相悖）。引擎侧不再二次钳制。

口径：
  - 字段缺失 → 不判；
  - 非整数（含 bool）/ 非数值 → 交给泛型 R-1，本项不重复报（避免双红）；
  - `max_hold` 非法取值 → IV-3；`grant_skills[].level` < 1 → IV-2；
  - `skill_amp[].type` 越界 → 泛型 enum R-1；`value` 越上下限 → IV-4；
  - 引用类字段（skill/job）存在性走元数据 `ref_target` 的泛型 R-4，本文件不重复。

鸭子类型 `report`（`_Checker` 或测试收集器）：只要求 `_err(module, field, kind, **detail)`
与 `_warn(module, field, kind, **detail)`。
"""
from __future__ import annotations

from typing import Any, Mapping, Optional, Set, Tuple

from qbot_rpg.content.forge_settings import read_skill_amp_bounds

__all__ = ["validate_items", "validate_equipment"]

_USE_LEVEL_MIN = 1
_GRANT_LEVEL_MIN = 1
_MAX_HOLD_VALUES: Tuple[int, ...] = (0, 1, -1)
_AMP_TYPE_BOUND_KEYS = {
    "damage": ("damage_min", "damage_max"),
    "cooldown": ("cooldown_min", "cooldown_max"),
}


def _is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


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


def _grant_skill_ids(entry: Mapping[str, Any]) -> Set[str]:
    """条目 `grant_skills` 内的技能 id 集（清洗后；供 α5 Y-9 与测试复用）。"""
    rows = entry.get("grant_skills")
    if not isinstance(rows, list):
        return set()
    out: Set[str] = set()
    for row in rows:
        if isinstance(row, Mapping) and isinstance(row.get("skill"), str) and row["skill"]:
            out.add(str(row["skill"]))
    return out


def _check_grant_skills(module: str, report: Any, entries: Any) -> None:
    """α1：`grant_skills[].level` ≥ 1（IV-2 红拦；skill 引用走泛型 R-4）。"""
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        rows = entry.get("grant_skills")
        if not isinstance(rows, list):
            continue
        for j, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            lv = row.get("level")
            if not _is_int(lv):
                continue  # 非整数 → 泛型 R-1
            if lv < _GRANT_LEVEL_MIN:
                report._err(
                    module, f"{module}.{idx}.grant_skills.{j}.level", "IV-2",
                    rule="grant_skill_level_min", value=lv, minimum=_GRANT_LEVEL_MIN,
                    msg="grant_skills 的 level 必须 ≥ 1",
                )


def _check_max_hold(module: str, report: Any, entries: Any) -> None:
    """α2：`max_hold` 仅允许 0 / 1 / -1（IV-3 红拦）。"""
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping) or "max_hold" not in entry:
            continue
        v = entry.get("max_hold")
        if not _is_int(v):
            continue  # 非整数 → 泛型 R-1
        if v not in _MAX_HOLD_VALUES:
            report._err(
                module, f"{module}.{idx}.max_hold", "IV-3", rule="max_hold_enum",
                value=v, allowed=list(_MAX_HOLD_VALUES),
                msg="max_hold 仅允许 0（不限）/ 1（唯一）/ -1（禁止获取）",
            )


def _amp_bound(bounds: Mapping[str, Any], amp_type: str, which: int) -> Optional[int]:
    keys = _AMP_TYPE_BOUND_KEYS.get(amp_type)
    if keys is None:
        return None
    v = bounds.get(keys[which])
    return int(v) if _is_int(v) else None


def _check_skill_amp(
    module: str,
    report: Any,
    entries: Any,
    bounds: Mapping[str, Any],
) -> None:
    """α3：`skill_amp[].value` 在配置上下限内（IV-4 红拦，不钳制）。

    type 越界 → 泛型 enum R-1（本项不重复）；value 非整数 → 泛型 R-1。
    """
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        rows = entry.get("skill_amp")
        if not isinstance(rows, list):
            continue
        for j, row in enumerate(rows):
            if not isinstance(row, Mapping):
                continue
            kind = row.get("type")
            val = row.get("value")
            if not isinstance(kind, str) or kind not in _AMP_TYPE_BOUND_KEYS:
                continue  # 枚举越界 → 泛型 R-1
            if not _is_int(val):
                continue  # 非整数 → 泛型 R-1
            lo = _amp_bound(bounds, kind, 0)
            hi = _amp_bound(bounds, kind, 1)
            if lo is not None and val < lo:
                report._err(
                    module, f"{module}.{idx}.skill_amp.{j}.value", "IV-4",
                    rule="skill_amp_below_min", value=val, amp_type=kind,
                    bound=lo, bound_key=f"skill_amp_bounds.{_AMP_TYPE_BOUND_KEYS[kind][0]}",
                    msg=f"skill_amp({kind}) 增幅值低于配置下限 {lo}",
                )
            elif hi is not None and val > hi:
                report._err(
                    module, f"{module}.{idx}.skill_amp.{j}.value", "IV-4",
                    rule="skill_amp_above_max", value=val, amp_type=kind,
                    bound=hi, bound_key=f"skill_amp_bounds.{_AMP_TYPE_BOUND_KEYS[kind][1]}",
                    msg=f"skill_amp({kind}) 增幅值超过配置上限 {hi}",
                )


def _check_attack_override(module: str, report: Any, entries: Any) -> None:
    """α5：`attack_override.skill` 须由本件 `grant_skills` 赋予（Y-9 黄提示，不硬拦）。

    「只有装备赋予技能才可选」是他们的约束；我们按「建议不拦截」给黄提示
    （缺 grant_skills 时引擎不替换，行为安全）。引用存在性仍走泛型 R-4。
    """
    if not isinstance(entries, list):
        return
    for idx, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            continue
        node = entry.get("attack_override")
        if not isinstance(node, Mapping):
            continue
        skill = node.get("skill")
        if not isinstance(skill, str) or not skill:
            continue
        if skill in _grant_skill_ids(entry):
            continue
        report._warn(
            module, f"{module}.{idx}.attack_override.skill", "Y-9",
            rule="attack_override_not_granted", skill=skill,
            msg="attack_override 的替换技能未在本件 grant_skills 中赋予"
                "（引擎不会替换；请补 grant_skills）",
        )


def _validate(module: str, modules: Mapping[str, Any], report: Any) -> None:
    entries = modules.get(module)
    _check_use_level(module, report, entries)
    _check_grant_skills(module, report, entries)
    _check_max_hold(module, report, entries)
    bounds = read_skill_amp_bounds(modules.get("settings"))
    _check_skill_amp(module, report, entries, bounds)
    _check_attack_override(module, report, entries)


def validate_items(modules: Mapping[str, Any], report: Any) -> None:
    """items 模块专项（IV-1 使用等级 / IV-2 赋予技能等级 / IV-3 max_hold / IV-4 增幅上下限）。"""
    _validate("items", modules, report)


def validate_equipment(modules: Mapping[str, Any], report: Any) -> None:
    """equipment 模块专项（与 items 同口径；items∪equipment 同库 item_lib）。"""
    _validate("equipment", modules, report)
