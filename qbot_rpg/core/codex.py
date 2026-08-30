"""图鉴分册引擎（qbot_rpg/core/codex.py · M7 BCH-08 · 3f F-11/F-12 · R-17~R-20/E-04）。

三分册图鉴（monster 怪物 / weapon 武器 / item 物品）+ 完成度计算 + 展示数据源
（未收集条目「???」不泄露名称）+ 全局完成度投影（ctx["codex"] 供 [图鉴完成度]
条件键 var:codex 实时读取）。

依据：
  - docs/细化/细化_3f_单机向体验.md R-17~R-20（分册/完成度/???/里程碑联动）/ E-04 codex 结构
  - docs/细化/细化_4d_图鉴系统.md（COD-08：展示取整、条件未取整；总册=等权分册均值）
  - qbot_rpg/engine/condition_engine.py（L531-532：var=="codex" 读 ctx["codex"] 标量）
  - qbot_rpg/core/adventure_log.py（log_codex_new：图鉴新增日志）

【工程补白 · 显式标注】
  1) 分册 key 映射：monster→registry kind "enemy"、weapon→"equipment"、item→"item"
     （仓库无独立 weapons 表，武器册用 equipment；木桩 training_dummy 等
     tier=training/type=dummy 不计入分母——由调用方不 mark 或本引擎登记补白）。
  2) 完成度口径（4d COD-08）：pct 全程未取整（浮点），展示层由调用方 round()；
     ctx["codex"] 投影 = 全局未取整等权分册均值（condition_engine 精确比较）。
  3) 分母 = registry.all_ids(kind) 全量（当前内容包可收集数）；已见 = state 中
     seen=true 与分母的交集。无 registry（裸 ctx）→ total=0、pct=0（fail-safe）。
  4) mark_seen 首见写 state + log_codex_new（[事件:图鉴新增:ID] nested，现有引擎
     first_seen 恒 False 口径）+ 刷新 ctx["codex"] 投影；重复 mark 仅补 killed。
  5) 未见条目展示「???」不显示名称（R-19 不提示原则）；已见名称取 state 缓存
     （旧局快照口径，registry resolve_name 兜底）。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping, Optional, Tuple

__all__ = [
    "CATEGORIES",
    "CATEGORY_ORDER",
    "codex_progress",
    "codex_view",
    "mark_killed",
    "mark_seen",
    "unlock_lore",
]

# 分册 → registry kind 映射（补白 1：weapon 用 equipment 表）
CATEGORIES: Mapping[str, Tuple[str, ...]] = {
    "monster": ("enemy",),
    "weapon": ("equipment",),
    "item": ("item",),
    # M8 收口裁决·/图鉴 双注册合并（批11-2）：炼金分册并入 codex 分册体系——
    # 分册页渲染由 codex_commands 对 alchemy 特判调 alchemy_commands.render_alchemy_codex
    # （F-19 炼金图鉴：点亮进度/成长奖励/王称号 TTL-01）；这里登记 kinds 供总览计数。
    "alchemy": ("recipe", "item"),
}

# 展示组序（3f R-17：怪物→武器→物品；M8 收口裁决加炼金分册于末尾）
CATEGORY_ORDER: Tuple[str, ...] = ("monster", "weapon", "item", "alchemy")

_CATEGORY_LABELS: Mapping[str, str] = {
    "monster": "怪物图鉴",
    "weapon": "武器图鉴",
    "item": "物品图鉴",
    "alchemy": "炼金图鉴",
}

# ??? 占位（未收集不泄露名称，R-19）
_UNKNOWN_NAME = "???"


def _state_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """codex_state 可变引用（ctx 直键，缺省创建）。"""
    st = ctx.get("codex_state")
    if not isinstance(st, MutableMapping):
        st = {}
        ctx["codex_state"] = st
    return st


def _cat_state(ctx: MutableMapping[str, Any], category: str) -> MutableMapping[str, Any]:
    """分册 state 可变引用（缺省创建）。"""
    st = _state_of(ctx)
    cat = st.get(category)
    if not isinstance(cat, MutableMapping):
        cat = {}
        st[category] = cat
    return cat


def _registry_of(ctx: Mapping[str, Any]):
    """内容注册表（ctx["registry"]，缺省 None）。"""
    reg = ctx.get("registry")
    return reg if hasattr(reg, "all_ids") else None


def _item_def_type(reg, iid: str) -> object:
    """条目 type（items 表 Def.raw.get / Mapping.get，查无 → None）。"""
    resolve = getattr(reg, "resolve", None)
    if not callable(resolve):
        return None
    try:
        d = resolve(iid, "item")
    except Exception:
        return None
    if isinstance(d, Mapping):
        return d.get("type")
    raw = getattr(d, "raw", None)
    if isinstance(raw, Mapping):
        return raw.get("type")
    get = getattr(d, "get", None)
    if callable(get):
        try:
            return get("type")
        except Exception:
            return None
    return None


def _category_ids(ctx: Mapping[str, Any], category: str) -> list:
    """分册可收集条目 id 全量（registry 派生；weapon 分册补 items type=weapon）。

    补白 1 修正（QA P2-9）：内容包把武器配置在 items.json（type=weapon）而
    equipment.json 可为空（test_demo 即此）——weapon 分册分母须含 items
    type=weapon 的条目，否则分母恒 0、已见 9 条却显示 0%（9/0）。
    """
    reg = _registry_of(ctx)
    if reg is None:
        return []
    ids: list = []
    for kind in CATEGORIES.get(category, ()):
        try:
            ids.extend(str(x) for x in reg.all_ids(kind))
        except Exception:
            continue
    if category == "weapon":
        try:
            for iid in reg.all_ids("item"):
                sid = str(iid)
                if sid in ids:
                    continue
                if _item_def_type(reg, iid) == "weapon":
                    ids.append(sid)
        except Exception:
            pass
    return list(dict.fromkeys(ids))


def _total_of(ctx: Mapping[str, Any], category: str) -> int:
    """分册可收集总数（_category_ids 长度；补白 3：无 registry → 0 fail-safe）。"""
    return len(_category_ids(ctx, category))


def _refresh_projection(ctx: MutableMapping[str, Any]) -> None:
    """刷新全局完成度投影 ctx["codex"]（未取整等权分册均值，补白 2）。"""
    pct = codex_progress(ctx).get("pct", 0.0)
    ctx["codex"] = float(pct)


def codex_progress(
    ctx: MutableMapping[str, Any], category: Optional[str] = None
) -> dict:
    """完成度计算（4d COD-08 / R-19）：{total, seen, killed, pct}。

    入参 ctx: 上下文（codex_state/registry）；category: 分册名或 None=全局。
    出参 dict: total 分母 / seen 已见数 / killed 击杀数 / pct 完成度（未取整 0-100）。
    核心逻辑: 单册 pct=seen/total×100；全局=三分册等权均值；total=0 → pct=0。
    """
    if category is not None:
        total = _total_of(ctx, category)
        cat = _cat_state(ctx, category)
        seen = sum(1 for e in cat.values()
                   if isinstance(e, Mapping) and e.get("seen"))
        killed = sum(1 for e in cat.values()
                     if isinstance(e, Mapping) and e.get("killed"))
        pct = (seen / total * 100.0) if total else 0.0
        return {"total": total, "seen": seen, "killed": killed, "pct": float(pct)}
    # 全局：三分册等权均值
    total = seen = killed = 0
    pct_sum = 0.0
    for cat_name in CATEGORY_ORDER:
        p = codex_progress(ctx, cat_name)
        total += p["total"]
        seen += p["seen"]
        killed += p["killed"]
        pct_sum += p["pct"]
    pct = pct_sum / len(CATEGORY_ORDER) if CATEGORY_ORDER else 0.0
    return {"total": total, "seen": seen, "killed": killed, "pct": float(pct)}


def mark_seen(
    ctx: MutableMapping[str, Any],
    category: str,
    ref_id: str,
    name: str,
    *,
    killed: bool = False,
) -> dict:
    """图鉴记录（R-17/R-18）：首次遭遇/获得 → seen + 图鉴新增日志 + 事件计数。

    入参 ctx/context；category 分册名；ref_id 条目 id；name 显示名；killed 是否伴随击杀。
    出参 dict: {ok, first_seen, category, ref_id}（first_seen=本次是否首次）。
    核心逻辑: 首见写 state（name/seen/killed/lore_unlocked）+ log_codex_new（冒险日志
    [事件:图鉴新增:ID]）+ [事件:图鉴新增] nested 计数 + 刷新 ctx["codex"] 投影；
    重复 mark 仅补 killed，不重复日志。
    """
    if category not in CATEGORIES:
        return {"ok": False, "reason": "unknown_category", "first_seen": False}
    if not str(ref_id or ""):
        return {"ok": False, "reason": "empty_ref", "first_seen": False}
    cat = _cat_state(ctx, category)
    rid = str(ref_id)
    existing = cat.get(rid)
    first_seen = not (isinstance(existing, Mapping) and existing.get("seen"))
    entry = {
        "name": str(name or rid),
        "seen": True,
        "killed": bool(killed) or bool(
            isinstance(existing, Mapping) and existing.get("killed")),
        "lore_unlocked": bool(
            isinstance(existing, Mapping) and existing.get("lore_unlocked")),
    }
    cat[rid] = entry
    if first_seen:
        try:
            from qbot_rpg.core.adventure_log import log_codex_new
            log_codex_new(ctx, rid)
        except Exception:
            pass
        try:
            from qbot_rpg.core.event_bus import bump_event
            bump_event(ctx, "[事件:图鉴新增]",
                       instance={"tag": "codex_new", "target": rid})
        except Exception:
            pass
    _refresh_projection(ctx)
    return {"ok": True, "first_seen": first_seen, "category": category, "ref_id": rid}


def mark_killed(ctx: MutableMapping[str, Any], category: str, ref_id: str) -> dict:
    """补记击杀（R-17）：已见条目补 killed=true（不触发首见日志）。"""
    if category not in CATEGORIES:
        return {"ok": False, "reason": "unknown_category"}
    cat = _cat_state(ctx, category)
    rid = str(ref_id)
    existing = cat.get(rid)
    if not (isinstance(existing, Mapping) and existing.get("seen")):
        return {"ok": False, "reason": "not_seen_yet"}
    entry = dict(existing)
    entry["killed"] = True
    cat[rid] = entry
    return {"ok": True, "category": category, "ref_id": rid}


def unlock_lore(ctx: MutableMapping[str, Any], category: str, ref_id: str) -> dict:
    """传闻解锁（F-16 定向线索，BCH-09 接线）：条目 lore_unlocked=true。"""
    if category not in CATEGORIES:
        return {"ok": False, "reason": "unknown_category"}
    cat = _cat_state(ctx, category)
    rid = str(ref_id)
    existing = cat.get(rid)
    if not (isinstance(existing, Mapping) and existing.get("seen")):
        return {"ok": False, "reason": "not_seen_yet"}
    entry = dict(existing)
    entry["lore_unlocked"] = True
    cat[rid] = entry
    return {"ok": True, "category": category, "ref_id": rid}


def _display_name(reg, rid: str, entry: Mapping[str, Any]) -> str:
    """展示名：state 缓存优先，registry resolve_name 兜底，缺失 → ???。"""
    name = entry.get("name")
    if isinstance(name, str) and name:
        return name
    if reg is not None:
        try:
            rn = reg.resolve_name(rid)
            if isinstance(rn, str) and rn:
                return rn
        except Exception:
            pass
    return _UNKNOWN_NAME


def codex_view(
    ctx: Mapping[str, Any], category: str, page: int = 1
) -> dict:
    """分册展示数据源（R-19/3d）：{entries, order, page, pages, total, page_size}。

    未收集条目名称「???」（不泄露名称）；组内按 state 插入序；每页 5 条。
    """
    if category not in CATEGORIES:
        return {"entries": [], "order": [], "page": 1, "pages": 1,
                "total": 0, "page_size": 5, "ok": False,
                "reason": "unknown_category"}
    reg = _registry_of(ctx)
    st = ctx.get("codex_state")
    cat = st.get(category) if isinstance(st, Mapping) else None
    cat = cat if isinstance(cat, Mapping) else {}
    # 已见条目映射（state 中 seen=true）
    seen_map: dict = {}
    for rid, raw in cat.items():
        if isinstance(raw, Mapping) and raw.get("seen"):
            seen_map[str(rid)] = raw
    # 全量可收集条目（registry 派生；weapon 分册含 items type=weapon，补白 1 修正）
    # + 旧局存档中不在 registry 的已见条目
    reg_ids = _category_ids(ctx, category)
    all_ids = list(dict.fromkeys([*reg_ids, *seen_map.keys()]))
    entries: list = []
    for rid in all_ids:
        raw = seen_map.get(rid) or {}
        seen = rid in seen_map
        entries.append({
            "ref_id": rid,
            "name": _display_name(reg, rid, raw) if seen else _UNKNOWN_NAME,
            "seen": seen,
            "killed": bool(raw.get("killed")),
            "lore_unlocked": bool(raw.get("lore_unlocked")),
        })
    entries.sort(key=lambda e: e["ref_id"])  # 确定性组序
    page_size = 5
    total = len(entries)
    pages = max(1, -(-total // page_size)) if total else 1
    page = max(1, min(int(page) if page and page > 0 else 1, pages))
    start = (page - 1) * page_size
    chunk = entries[start:start + page_size]
    return {
        "entries": chunk,
        "order": [e["ref_id"] for e in chunk],
        "page": page,
        "pages": pages,
        "total": total,
        "page_size": page_size,
        "category": category,
        "label": _CATEGORY_LABELS.get(category, category),
        "ok": True,
    }
