"""伤害构成统计：per-action 收集器聚合 + dummy_log 环形缓冲（定稿 §八）。

文件：qbot_rpg/core/damage_stats.py · 2026-09-24 · dsh（批78 · U4）
依据：`docs/审查参考/战斗数值层设计定稿.md`
  - §8.1 收集时机与记录字段 / 按来源聚合（L319-334）：同 source 求和 → 总伤害/占比
    排序；另出 通道占比（物理/元素）、最大连段段数、会心次数；
  - §8.2 展示（L337-351）：木桩战后全量，普通战斗默认不展示（渲染层已实装
    `render_battle_summary` / 模板 `battle_summary_*`，本模块只产聚合数据）；
  - §8.3 存档 dummy_log（L353-360）：玩家存档环形缓冲，最近 N 次（默认 5，0=关），
    记录字段 = 时间/木桩档位 id/回合数/总伤害/来源占比摘要/最大单段/会心/格挡次数；
  - §8.4 formula.json 落点（L362-372）：`stats_collector.{enabled,dummy_log_size,
    dummy_realtime}`。

定位：**纯函数 + 无状态**，不 import NoneBot；引擎快照的既有 `stats_collector.per_action`
是唯一数据源，本模块在其下游做聚合，**不改数值口径、不新增战斗内数值**。

口径显式标注（工程补白，定稿未写死处按最小必要推导）：
  - `enabled` 只门控**新增**的聚合/展示/dummy_log；per-action 收集是既有能力（批30 前
    已随快照写入），本批不动 → 既有内容包缺省（enabled=true）逐字段零变化。定稿
    §8.4 括注「关=不收集」与「零行为变化」冲突，登记待裁决（见 docs/矛盾与待裁决登记）。
  - 聚合结果**不回写快照**（只在读取时计算）：定稿 §8.1「统计随战斗快照保存」由既有
    `per_action` 承载；避免快照新增键造成续战/对拍形态漂移。
  - `max_hit` = 最大单段最终值；`seg_max` = 最大连段段数（供 dummy_log/审计）。
  - `dummy_log_size` 越界夹取到 [0, 20]（编辑器 range 0-20，越界黄提示）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Sequence, Tuple

__all__ = [
    "DEFAULT_STATS_COLLECTOR",
    "load_stats_collector_cfg",
    "aggregate_per_action",
    "build_dummy_log_record",
    "append_dummy_log",
    "dummy_log_of",
]

#: stats_collector 段默认值（定稿 §8.4 L366-369：enabled 默认开 / size 5 / realtime 关）
DEFAULT_STATS_COLLECTOR: Dict[str, Any] = {
    "enabled": True,
    "dummy_log_size": 5,
    "dummy_realtime": False,
}

#: dummy_log 保留次数上限（编辑器 range_max=20，越界夹取）
_DUMMY_LOG_SIZE_MAX = 20

#: 会心档（非 none 视为会心；空/缺省不臆造为会心）
_CRIT_LEVELS = frozenset({"low", "mid", "high", "super"})


def _as_int(v: Any, default: int = 0) -> int:
    """尽力转 int（bool 视为非法——避免 True 被当 1；坏值回落 default）。"""
    if v is None or isinstance(v, bool):
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def load_stats_collector_cfg(formula_raw: Any = None) -> Dict[str, Any]:
    """formula.json 顶层 dict → stats_collector 归一配置。

    - 无 formula/无 stats_collector 段 → `DEFAULT_STATS_COLLECTOR` 副本（缺省零破坏）；
    - 段值类型非法 → 逐键回落默认（不抛错）；
    - `dummy_log_size` 夹取 [0, 20]；0 = 关。
    """
    cfg = dict(DEFAULT_STATS_COLLECTOR)
    seg: Any = None
    if isinstance(formula_raw, Mapping):
        seg = formula_raw.get("stats_collector")
    if not isinstance(seg, Mapping):
        return cfg
    en = seg.get("enabled")
    if isinstance(en, bool):
        cfg["enabled"] = en
    size = seg.get("dummy_log_size")
    if size is not None and not isinstance(size, bool):
        cfg["dummy_log_size"] = max(0, min(_DUMMY_LOG_SIZE_MAX, _as_int(
            size, DEFAULT_STATS_COLLECTOR["dummy_log_size"])))
    rt = seg.get("dummy_realtime")
    if isinstance(rt, bool):
        cfg["dummy_realtime"] = rt
    return cfg


def _records(per_action: Any) -> List[Mapping[str, Any]]:
    if not isinstance(per_action, Sequence):
        return []
    return [r for r in per_action if isinstance(r, Mapping)]


def _source_of(rec: Mapping[str, Any]) -> str:
    """来源显示名：显式 `name` 优先（技能展示名），否则 `source` id，兜底 `?`。"""
    name = rec.get("name")
    if isinstance(name, str) and name:
        return name
    src = rec.get("source")
    return str(src) if src not in (None, "") else "?"


def aggregate_per_action(per_action: Any) -> Dict[str, Any]:
    """per-action 记录序列 → 聚合摘要（定稿 §8.1 L332「按来源聚合」）。

    返回键（渲染层 `render_battle_summary` 直接消费 total/max_hit/crits/blocks/items）：
      - `records` 段数 / `total` 总伤害 / `max_hit` 最大单段 / `crits` 会心次数
      - `blocks` 格挡次数 / `seg_max` 最大连段段数
      - `ch_phys` / `ch_elem` 通道值和 / `ch_phys_pct` / `ch_elem_pct` 通道占比（取整）
      - `items` = [(来源, 总伤害)]，按总伤害降序（占比降序）
    空记录 → 全零 + 空 items（不抛错）。
    """
    recs = _records(per_action)
    total = 0
    max_hit = 0
    crits = 0
    blocks = 0
    seg_max = 0
    ch_phys = 0
    ch_elem = 0
    by_source: Dict[str, int] = {}
    for rec in recs:
        final = _as_int(rec.get("final"))
        if final < 0:
            final = 0
        total += final
        if final > max_hit:
            max_hit = final
        ch_phys += _as_int(rec.get("ch_phys"))
        ch_elem += _as_int(rec.get("ch_elem"))
        seg_max = max(seg_max, _as_int(rec.get("seg")))
        if final > 0 and str(rec.get("crit") or "") in _CRIT_LEVELS:
            crits += 1
        if bool(rec.get("blocked", False)):
            blocks += 1
        src = _source_of(rec)
        by_source[src] = by_source.get(src, 0) + final
    items: List[Tuple[str, int]] = sorted(
        by_source.items(), key=lambda kv: kv[1], reverse=True)
    ch_total = ch_phys + ch_elem

    def _pct(v: int) -> int:
        return round(v / ch_total * 100) if ch_total > 0 else 0

    return {
        "records": len(recs),
        "total": total,
        "max_hit": max_hit,
        "crits": crits,
        "blocks": blocks,
        "seg_max": seg_max,
        "ch_phys": ch_phys,
        "ch_elem": ch_elem,
        "ch_phys_pct": _pct(ch_phys),
        "ch_elem_pct": _pct(ch_elem),
        "items": items,
    }


def build_dummy_log_record(
    summary: Mapping[str, Any],
    *,
    at: str,
    dummy_id: str,
    turns: int = 0,
    top_n: int = 3,
) -> Dict[str, Any]:
    """聚合摘要 → dummy_log 记录（定稿 §8.3 L357 字段：时间/档位/回合数/总伤害/
    来源占比摘要/最大单段/会心/格挡次数）。

    `top` = 来源占比摘要（结构化前 N 条 [来源, 总伤害, 占比%]，展示层按模板逐行渲染，
    不在此处拼用户可见文案）。
    """
    items = summary.get("items")
    items = list(items) if isinstance(items, Sequence) else []
    total = _as_int(summary.get("total"))
    top: List[List[Any]] = []
    for src, dmg in items[:max(0, top_n)]:
        d = _as_int(dmg)
        top.append([str(src), d, round(d / total * 100) if total > 0 else 0])
    return {
        "at": str(at or ""),
        "dummy_id": str(dummy_id or ""),
        "turns": _as_int(turns),
        "total": total,
        "top": top,
        "max_hit": _as_int(summary.get("max_hit")),
        "crits": _as_int(summary.get("crits")),
        "blocks": _as_int(summary.get("blocks")),
    }


def dummy_log_of(player_ps: Any) -> List[Any]:
    """玩家 persistent_state → dummy_log 列表（非法/缺失 → []）。"""
    if not isinstance(player_ps, Mapping):
        return []
    log = player_ps.get("dummy_log")
    return list(log) if isinstance(log, Sequence) and not isinstance(log, str) else []


def append_dummy_log(
    player_ps: MutableMapping[str, Any],
    record: Mapping[str, Any],
    size: int,
) -> List[Any]:
    """环形缓冲写入（定稿 §8.3 L354）：**最新在前**，只保留最近 `size` 条。

    - `size <= 0` → 关闭（不写、不动既有段，返回原列表）；
    - 非 MutableMapping / 坏值 → 原样返回（不抛错）。
    返回写入后的列表（便于断言）。
    """
    try:
        n = _as_int(size)
    except Exception:  # noqa: BLE001 —— 坏值按关闭处理
        n = 0
    if not isinstance(player_ps, MutableMapping) or n <= 0:
        return dummy_log_of(player_ps)
    old = dummy_log_of(player_ps)
    new_log: List[Any] = [dict(record)] + old
    del new_log[n:]
    player_ps["dummy_log"] = new_log
    return new_log
