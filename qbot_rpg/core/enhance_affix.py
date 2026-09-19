"""批43 强化：品质等级 6 档上限 + 每 N 级特殊词条（相性池抽取）。

依据：
  · `docs/深度打造_决策记录.md` §一 **H3**（用打造装备的 6 档上限 +3/+6/+9/+12/+15/+18
    **替换**既有 `max_by_rarity`；须给旧内容迁移/兼容口径）+ §二 N（数值一律包声明）；
  · 需求源头 `打造系统_原案_20260919.md` §7（品质决定上限；**每 4 级获得一个特殊词条**；
    含百分比加成与冷却缩减/回复强化/减益概率提升/增益概率提升/弱点伤害增加）+ §8（相性池）。

铁律（一号红线）：
  · 池抽取**唯一入口** = `core/affinity.resolve_available_entries`（本模块**不自己算池**、
    不本地匹配相性；与批42 打造词条同源）；
  · 随机源 = 注入的**玩家级随机流**（批40 H5 `ctx["rng"]`）；本模块不读全局 random、
    不新建第二条随机源（同刻同参必同值）；
  · 数值/档位/跨度/旧档桥接**全部由包声明注入**（本模块零硬编码档位与数值）；
  · 零内容包业务名：词条键来自 `data/gear_stats.py` 唯一源，相性池来自包声明；
  · 占位键（冷却缩减）只登记不接引擎——本模块只按 `enhance_affix` 载荷写入实例，
    不解释词条语义（语义/承载由 gear_stats 注释与批43 报告说明）。

上限口径（H3 + 工程补白，见批43 报告「旧档→新档映射」）：
  1. 实例带 `quality_level ≥ 1` → 查品质等级上限表；
  2. 实例无 `quality_level`（旧档/普通物品）→ 用 `legacy_quality_level_by_rarity`
     把旧品质（quality 枚举）桥接为品质等级，再查表（**只升不降**：桥接值满足
     新档 ≥ 旧档，旧装备既有 `enhance_level` 原样保留）；
  3. 品质等级超出已声明档位 → **顶档封顶**（不越表、不报错）；
  4. 最终上限 = `max(查表值, 当前强化等级)`——**绝不降级、绝不清零**旧档装备。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.core.affinity import (
    normalize_affinity_config,
    rank_affinities,
    resolve_available_entries,
)
from qbot_rpg.core.deep_craft import _entry_payload, _pick_weighted
from qbot_rpg.data.affinity_keys import ENTRY_PAYLOAD_ENHANCE_AFFIX

__all__ = [
    "ENTRY_ENHANCE_AFFIX",
    "normalize_cap_table",
    "normalize_legacy_map",
    "resolve_cap",
    "special_affix_count",
    "plan_special_affixes",
    "merge_affix_bonus",
]

ENTRY_ENHANCE_AFFIX: str = ENTRY_PAYLOAD_ENHANCE_AFFIX


# ---------------------------------------------------------------------------
# 小工具（纯函数；非法值由校验器红拦，引擎防御性截断）
# ---------------------------------------------------------------------------
def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


class _CallableRng:
    """可调用随机源 → `.random()` 契约适配（复用 `_pick_weighted` 的 `.random` 读取）。"""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def random(self) -> float:
        return float(self._fn())


def _as_rng(rng: Any) -> Any:
    """注入随机源归一：None / 有 `.random` / 可调用（包一层）；其余 → None（首项退化）。"""
    if rng is None:
        return None
    if callable(getattr(rng, "random", None)):
        return rng
    if callable(rng):
        return _CallableRng(rng)
    return None


# ---------------------------------------------------------------------------
# 1) 上限表（品质等级 → 上限；旧档桥接）
# ---------------------------------------------------------------------------
def normalize_cap_table(raw: Any) -> Dict[int, int]:
    """包声明上限表 → `{品质等级: 上限}`（键 int；非法键/值丢弃）。

    入参形态：JSON obj（键为字符串数字，如 `{"1": 3, ...}`）或已归一 dict。
    """
    out: Dict[int, int] = {}
    if not isinstance(raw, Mapping):
        return out
    for k, v in raw.items():
        try:
            ik = int(k)
        except (TypeError, ValueError):
            continue
        iv = _as_int(v)
        if ik <= 0 or iv is None or iv < 0:
            continue
        out[ik] = iv
    return out


def normalize_legacy_map(raw: Any) -> Dict[str, int]:
    """旧档桥接表 → `{旧品质枚举: 品质等级}`（非法项丢弃）。"""
    out: Dict[str, int] = {}
    if not isinstance(raw, Mapping):
        return out
    for k, v in raw.items():
        if not isinstance(k, str) or not k:
            continue
        iv = _as_int(v)
        if iv is None or iv < 0:
            continue
        out[k] = iv
    return out


def resolve_cap(
    *,
    cap_table: Any,
    legacy_map: Any = None,
    quality_level: int = 0,
    rarity: str = "",
    current: int = 0,
) -> int:
    """实例 → 强化上限（品质等级优先；旧档经桥接；顶档封顶；绝不低于当前等级）。

    入参：
      · cap_table / legacy_map：包声明（`settings.max_by_quality_level` /
        `settings.legacy_quality_level_by_rarity`）。
      · quality_level：实例品质等级（0/缺省 = 旧档/未知）；rarity：实例旧品质枚举。
      · current：实例既有 `enhance_level`（保底，防降级）。
    出参：上限 int（0 = 该实例不可强化）。
    """
    table = normalize_cap_table(cap_table)
    lv = _as_int(quality_level)
    if lv is None:
        lv = 0
    if lv <= 0:
        lv = normalize_legacy_map(legacy_map).get(str(rarity or ""), 0)
    cap = 0
    if lv > 0 and table:
        if lv in table:
            cap = table[lv]
        else:
            # 超出已声明档位 → 顶档封顶（不越表）；低于最小键 → 表内最小档
            keys = sorted(table)
            if lv > keys[-1]:
                cap = table[keys[-1]]
            elif lv < keys[0]:
                cap = 0
            else:
                cap = table[max(k for k in keys if k <= lv)]
    cur = _as_int(current)
    cur = 0 if cur is None or cur < 0 else cur
    return max(cap, cur)


# ---------------------------------------------------------------------------
# 2) 特殊词条（每 N 级一条；相性池抽取）
# ---------------------------------------------------------------------------
def special_affix_count(level: Any, span: Any) -> int:
    """强化等级 → 应持有的特殊词条条数 = `level // span`（跨度包声明，不写死）。

    span ≤ 0（关闭词条）→ 0；level 非法/负 → 0。
    """
    lv = _as_int(level)
    sp = _as_int(span)
    if lv is None or sp is None or sp <= 0 or lv <= 0:
        return 0
    return lv // sp


def plan_special_affixes(
    *,
    affinity_config: Any = None,
    affinity_values: Any = None,
    level: Any = 0,
    span: Any = 0,
    owned: Sequence[str] = (),
    rng: Any = None,
) -> List[Dict[str, Any]]:
    """达到门槛时从**相性池**抽取本次新增的特殊词条（原案 §7/§8）。

    入参：
      · affinity_config：settings（或已归一相性配置）——池查询唯一入口
        `affinity.resolve_available_entries` 的入参。
      · affinity_values：实例相性结算值 `{相性id: 数值}`（主/副相性从中判定）。
      · level / span：强化等级 / 词条跨度（包声明）。
      · owned：实例已持有词条键（不重复抽）。
      · rng：玩家级随机流（批40 H5）。
    出参：新增词条行列表 `[{affix, value, pool}]`（按抽取顺序；可 JSON）。

    边界口径（与批42 同口径）：
      · **无相性 → 要求相性的词条抽不出**（`resolve_available_entries` 的
        `requires_affinity ⊆ {main,sub}` 过滤；通用池中不要求相性的词条仍可抽）；
      · 联动命中（main+sub）→ 专属池被 `override_pool` 覆盖（affinity 层已实现）；
      · 候选不足应得条数 → 抽满候选为止（不补空、不臆造）；
      · 只消费载荷键 `enhance_affix` 的词条行（不重算池、不本地匹配相性）。
    """
    need = special_affix_count(level, span) - len([x for x in owned if isinstance(x, str)])
    if need <= 0:
        return []
    cfg = normalize_affinity_config(affinity_config)
    ranked = rank_affinities(affinity_values, cfg.get("affinity_list") or ())
    entries = resolve_available_entries(cfg, ranked["main"], ranked["sub"], level)
    rows = [e for e in entries if _entry_payload(e, ENTRY_ENHANCE_AFFIX)]
    picked = _pick_weighted(_as_rng(rng), rows, ENTRY_ENHANCE_AFFIX, need,
                            tuple(str(x) for x in owned if isinstance(x, str)))
    out: List[Dict[str, Any]] = []
    for row in picked:
        affix = _entry_payload(row, ENTRY_ENHANCE_AFFIX)
        if not affix:
            continue
        val = _as_float(row.get("value"))
        out.append({
            "affix": str(affix),
            "value": 0.0 if val is None else val,
            "pool": str(row.get("_pool") or ""),
        })
    return out


def merge_affix_bonus(
    current_bonus: Any,
    affixes: Sequence[Mapping[str, Any]],
) -> Tuple[Dict[str, float], Tuple[str, ...]]:
    """把新增词条值并入 `stats_bonus` → (新 stats_bonus, 新词条键序列)。

    口径：词条键写值（非数值/0 → 保留键但值不写，避免 0 值污染展示）；键序按传入顺序。
    """
    bonus: Dict[str, float] = {}
    if isinstance(current_bonus, Mapping):
        for k, v in current_bonus.items():
            fv = _as_float(v)
            if fv is not None:
                bonus[str(k)] = fv
    keys: List[str] = []
    for row in affixes:
        affix = str(_as_payload(row))
        if not affix:
            continue
        if affix not in keys:
            keys.append(affix)
        val = _as_float(_as_map(row).get("value"))
        if val:
            bonus[affix] = bonus.get(affix, 0.0) + val
    return bonus, tuple(keys)


def _as_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_payload(row: Any) -> str:
    v = _as_map(row).get("affix")
    return v if isinstance(v, str) else ""
