"""深炼金 · 相性 → 药剂效果（口径 A 强度型 / 口径 B 附加型）· 炼金侧解释层（批60/61）。

定位：把**通用层**相性事实（`core/affinity.py` 的四接口）翻译成**炼金侧的取值**
（`data/gear_stats.EFFECT_AXIS_SPECS` 的既有特效轴键 / 相性池的 `effect_ref` 载荷）。
本模块只做三件事：

  · `main_sub_of(aff_values, settings)` —— 相性累计值 → 主/副（`rank_affinities` 同口径）；
  · `axis_pct(aff_values, settings, axis)` —— 相性 → 某特效轴的**百分点**（查
    `settings.alchemy.affinity_effects`，经 `normalize_effect_axes` 按声明区间钳制）；
  · `plan_effect_refs(aff_values, settings, ...)` —— 批61 · 口径 B 附加型求值：**池查询
    唯一入口** `core.affinity.resolve_available_entries` → 按载荷键 `effect_ref` 分流 →
    `core.deep_craft._pick_weighted` 加权抽取（与打造/强化同一实现）。

为什么**不放进** `core/affinity.py`：该模块铁律是「不做任何业务解释」（`core/affinity.py:362`）；
「相性 → 哪个轴」属炼金侧玩法解释，落点由玩法口径裁决（`深炼金相性_玩法口径_可开工版.md`
§3.3）。本模块与「结算/品质型」共用，使用链路（`commands/use_commands.py`）与结算侧
（`core/alchemy_settle.py`）都只引用它，不各自重写。

红线：
  · 相性定义/池唯一源 = `core/affinity.py` + `data/affinity_keys.py`（本模块只读接口）；
  · 数值口径唯一源 = `data/gear_stats.EFFECT_AXIS_SPECS`（轴键经 `GEAR_EFFECT_KEYS` 判定，
    区间经 `normalize_effect_axes` 取，不新造第二套、不写死区间）；
  · 框架零内容包业务名（相性 id / 轴值全由内容包声明）；
  · 缺省零变化：`settings` 缺 `alchemy.affinity_effects` / 实例 `affinities` 空 / 轴未声明
    → 返回 0.0（= 不生效）；
  · 口径 B 的池作用域**完全**由 `resolve_available_entries` 既有语义承担（`requires_affinity`
    过滤 / 专属池 / 联动覆盖），本模块**不重算池**、不新造 `scope` 字段。

铁律：零 NoneBot import；纯函数确定性（同参必同值）；不抛异常（防御降级返回 0.0 / 空集）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.core.affinity import (
    normalize_affinity_config,
    rank_affinities,
    resolve_affinity_effect,
    resolve_available_entries,
)
from qbot_rpg.core.deep_craft import _entry_payload, _pick_weighted
from qbot_rpg.data.affinity_keys import ENTRY_PAYLOAD_EFFECT_REF
from qbot_rpg.data.gear_stats import GEAR_EFFECT_KEYS, normalize_effect_axes

__all__ = ["main_sub_of", "axis_pct", "plan_effect_refs", "effect_refs_of"]


def _settings_of(settings: Any) -> Mapping[str, Any]:
    return settings if isinstance(settings, Mapping) else {}


def _effect_table(settings: Mapping[str, Any]) -> Any:
    """`settings.alchemy.affinity_effects`（炼金侧效果表；缺省 None → 不生效）。"""
    alch = settings.get("alchemy")
    if isinstance(alch, Mapping):
        return alch.get("affinity_effects")
    return None


def main_sub_of(aff_values: Any, settings: Any) -> Dict[str, Any]:
    """相性累计值 + settings → 主/副相性（复用 `core/affinity.rank_affinities`）。

    入参：`aff_values = {相性id: 数值}`；`settings`（读 `affinities[]` 声明顺序破平）。
    出参：`{main, sub, ranked}`；无正值 / 不入参 → main/sub 均 None。纯函数、确定性。
    """
    src = _settings_of(settings)
    cfg = normalize_affinity_config(src)
    ranked = rank_affinities(aff_values, cfg.get("affinity_list") or ())
    return {"main": ranked["main"], "sub": ranked["sub"], "ranked": ranked["ranked"]}


def axis_pct(aff_values: Any, settings: Any, axis: str) -> float:
    """相性 → 某特效轴的**百分点**（`axis` 必须 ∈ `GEAR_EFFECT_KEYS`；否则 0.0）。

    取值链（全部复用既有接口，不自己算池/不自己定区间）：
      `aff_values` → `rank_affinities` 主/副 → `resolve_affinity_effect`（`"主|副"` 优先 →
      `"主"`）→ 取 `axis` 数值 → `normalize_effect_axes(settings.effect_axes)` 的 `min/max` 钳制。

    缺省/非法（轴未登记 / 无相性 / 表缺失 / 值非数）→ `0.0`（= 不生效，零变化兜底）。
    """
    ax = str(axis)
    if ax not in GEAR_EFFECT_KEYS:
        return 0.0  # 键空间唯一源红线：非特效轴不生效（声明侧由校验器红拦）
    src = _settings_of(settings)
    ms = main_sub_of(aff_values, src)
    payload = resolve_affinity_effect(_effect_table(src), ms["main"], ms["sub"])
    if not isinstance(payload, Mapping):
        return 0.0
    raw = payload.get(ax)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 0.0
    value = float(raw)
    entry: Optional[Mapping[str, Any]] = normalize_effect_axes(src.get("effect_axes")).get(ax)
    if not isinstance(entry, Mapping):
        return value
    lo, hi = entry.get("min"), entry.get("max")
    if isinstance(lo, (int, float)) and not isinstance(lo, bool):
        value = max(float(lo), value)
    if isinstance(hi, (int, float)) and not isinstance(hi, bool):
        value = min(float(hi), value)
    return value


def _as_count(count: Any, fallback: int) -> int:
    """抽取条数归一：非 bool 整数且 ≥0 才生效，否则回落 `fallback`（= 候选行数）。"""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return fallback
    return count


def plan_effect_refs(
    aff_values: Any,
    settings: Any,
    *,
    rng: Any = None,
    level: Optional[int] = None,
    count: Optional[int] = None,
) -> Dict[str, Any]:
    """相性 → 追加效果/状态引用（口径 B 附加型**求值**；纯函数、确定性）。

    入参：
      · `aff_values = {相性id: 数值}`（炼金快照 `affinity_values`，批60 · G1 写入）；
      · `settings`（读顶层四段相性声明；相性定义/池**唯一源**）；
      · `rng`：`ctx["rng"]` 玩家级随机流（批40 · H5）；缺省 → `_pick_weighted` 确定性取首项；
      · `level`：`min_level` 过滤用（来源待裁决，见下）；缺省不过滤；
      · `count`：抽取条数；缺省 = **候选行数**（本批口径：声明即附加，不写死任意条数——
        「抽几条 / 谁抽」属玩法裁决 Q4，故不在此写死）。

    出参：`{main, sub, rows, picked}`；`rows` = 池返回值中带非空 `effect_ref` 的行，
    `picked` = 抽中的 `effect_ref` id 列表（去重、保序）。

    复用（红线）：
      · 池查询**唯一入口** = `core.affinity.resolve_available_entries`（通用池 ∪ 主专属池 /
        联动覆盖 / `requires_affinity` 过滤全部由它承担，本函数不重算池）；
      · 加权**不放回**抽取 = `core.deep_craft._pick_weighted`（批42 建、批43 已跨模块复用）。
    缺省零变化：无相性 / 池无 `effect_ref` 行 → `picked == []`（且**不消耗** `rng`）。
    """
    src = _settings_of(settings)
    ms = main_sub_of(aff_values, src)
    cfg = normalize_affinity_config(src)
    entries: List[Dict[str, Any]] = resolve_available_entries(
        cfg, ms["main"], ms["sub"], level)
    rows = [e for e in entries if _entry_payload(e, ENTRY_PAYLOAD_EFFECT_REF)]
    want = _as_count(count, len(rows))
    selected = _pick_weighted(rng, rows, ENTRY_PAYLOAD_EFFECT_REF, want)
    picked: List[str] = []
    for row in selected:
        ref = _entry_payload(row, ENTRY_PAYLOAD_EFFECT_REF)
        if ref and ref not in picked:
            picked.append(ref)
    return {"main": ms["main"], "sub": ms["sub"], "rows": rows, "picked": picked}


def effect_refs_of(inst: Any) -> Tuple[str, ...]:
    """实例 → 追加效果引用元组（`ItemInstance.effect_refs`；dict/对象兼容，缺省空）。

    使用链路（`commands/use_commands.py`）读取口径的唯一落点：只收非空 str，去重保序。
    """
    raw = (inst.get("effect_refs") if isinstance(inst, Mapping)
           else getattr(inst, "effect_refs", None))
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        return ()
    out: List[str] = []
    for x in raw:
        if isinstance(x, str) and x and x not in out:
            out.append(x)
    return tuple(out)
