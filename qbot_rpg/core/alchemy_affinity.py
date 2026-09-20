"""深炼金 · 相性 → 药剂效果（口径 A 强度型）· 炼金侧解释层（批60）。

定位：把**通用层**相性事实（`core/affinity.py` 的四接口）翻译成**炼金侧的轴取值**
（`data/gear_stats.EFFECT_AXIS_SPECS` 的既有特效轴键）。本模块只做两件事：

  · `main_sub_of(aff_values, settings)` —— 相性累计值 → 主/副（`rank_affinities` 同口径）；
  · `axis_pct(aff_values, settings, axis)` —— 相性 → 某特效轴的**百分点**（查
    `settings.alchemy.affinity_effects`，经 `normalize_effect_axes` 按声明区间钳制）。

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
    → 返回 0.0（= 不生效）。

铁律：零 NoneBot import；纯函数确定性（同参必同值）；不抛异常（防御降级返回 0.0）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional

from qbot_rpg.core.affinity import (
    normalize_affinity_config,
    rank_affinities,
    resolve_affinity_effect,
)
from qbot_rpg.data.gear_stats import GEAR_EFFECT_KEYS, normalize_effect_axes

__all__ = ["main_sub_of", "axis_pct"]


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
