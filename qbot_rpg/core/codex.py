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
    "item_craft_relation",
    "mark_killed",
    "mark_seen",
    "sync_lore_unlocks",
    "unlock_lore",
]

# 分册 → registry kind 映射（4d D-01 四册：monster/fish/item/craft；M11 批2 路2A 收敛）
CATEGORIES: Mapping[str, Tuple[str, ...]] = {
    "monster": ("enemy",),
    "item": ("item",),
    # M11 批2 路2A（4d D-04）：craft 册 = forge 树节点产物 ∪ 炼金 recipe 产物，
    # 无专属 registry kind——分母由 _craft_ids 数据驱动计算（归属判定器）。
    "craft": ("craft",),
    # M10 钓鱼批4·路4A（T13）：鱼册分册——fishing.json 顶层 obj 非条目表，registry
    # 不索引 fish kind（摸底 §三），分母从 ctx["fishing"]["species"] + king 读。
    "fish": ("fish",),
}

# 展示组序（4d D-01：怪物→鱼→物品→制造）
CATEGORY_ORDER: Tuple[str, ...] = ("monster", "fish", "item", "craft")

_CATEGORY_LABELS: Mapping[str, str] = {
    "monster": "怪物图鉴",
    "fish": "鱼图鉴",
    "item": "物品图鉴",
    "craft": "制造品图鉴",
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


def _is_dummy_enemy(reg, iid: str) -> bool:
    """木桩判定（本地复刻 validator.is_dummy_enemy 语义：tier=training 或 type=dummy）。

    core 层不可 import content 层（G0 依赖矩阵），故本地判据。registry resolve 失败
    → False（不排除，保守保留分母）。
    """
    resolve = getattr(reg, "resolve", None)
    if not callable(resolve):
        return False
    try:
        d = resolve(iid, "enemy")
    except Exception:
        return False
    raw = None
    if isinstance(d, Mapping):
        raw = d
    else:
        raw = getattr(d, "raw", None)
    if not isinstance(raw, Mapping):
        return False
    tier = raw.get("tier")
    typ = raw.get("type")
    return tier == "training" or typ == "dummy"


def _craft_ids(ctx: Mapping[str, Any]) -> list:
    """craft 册分母：forge 树节点产物 item 引用 ∪ 炼金 recipe 产物（4d D-04）。

    数据源：ctx[\"registry\"].modules_raw[\"forge\"].trees[].nodes[].item +
    registry all_ids(\"recipe\") resolve 读 output.item。全 try/except fail-safe 空。
    """
    ids: list = []
    reg = _registry_of(ctx)
    if reg is None:
        return []
    # forge 节点 item 引用
    try:
        raw = getattr(reg, "modules_raw", None)
        forge = raw.get("forge") if isinstance(raw, Mapping) else None
        if isinstance(forge, Mapping):
            trees_raw = forge.get("trees")
            trees = trees_raw if isinstance(trees_raw, list) else []
            for tree in trees:
                if not isinstance(tree, Mapping):
                    continue
                nodes_raw = tree.get("nodes")
                nodes = nodes_raw if isinstance(nodes_raw, list) else []
                for n in nodes:
                    if isinstance(n, Mapping) and isinstance(n.get("item"), str) and n["item"]:
                        ids.append(n["item"])
    except Exception:
        pass
    # 炼金 recipe 产物
    try:
        for rid in reg.all_ids("recipe"):
            resolve = getattr(reg, "resolve", None)
            if not callable(resolve):
                break
            d = resolve(rid, "recipe")
            raw = d if isinstance(d, Mapping) else getattr(d, "raw", None)
            if isinstance(raw, Mapping):
                out = raw.get("output")
                if isinstance(out, Mapping) and isinstance(out.get("item"), str) and out["item"]:
                    ids.append(out["item"])
    except Exception:
        pass
    return list(dict.fromkeys(ids))


def _fish_ids(ctx: Mapping[str, Any]) -> list:
    """fish 册分母：ctx[\"fishing\"][\"species\"].id + king[].id（4d TC-02 21 条口径）。"""
    ids: list = []
    fishing = ctx.get("fishing")
    if isinstance(fishing, Mapping):
        species = fishing.get("species")
        if isinstance(species, list):
            for s in species:
                if isinstance(s, Mapping) and isinstance(s.get("id"), str) and s["id"]:
                    ids.append(s["id"])
        king = fishing.get("king")
        if isinstance(king, list):
            for k in king:
                if isinstance(k, Mapping) and isinstance(k.get("id"), str) and k["id"]:
                    ids.append(k["id"])
    return list(dict.fromkeys(ids))


def _category_ids(ctx: Mapping[str, Any], category: str) -> list:
    """分册可收集条目 id 全量（registry 派生 + 数据驱动归属）。

    4d D-01/D-04（M11 批2 路2A）：
      - monster：registry enemy ids，剔除木桩（tier=training/type=dummy，COD-05）。
      - item：registry item ids − craft_ids（归属反向减除防双计）。
      - craft：_craft_ids（forge 节点 ∪ 炼金 recipe 产物）。
      - fish：_fish_ids（fishing.json species + king）。
    """
    reg = _registry_of(ctx)
    if reg is None:
        return []
    ids: list = []
    if category == "monster":
        try:
            for iid in reg.all_ids("enemy"):
                sid = str(iid)
                if not _is_dummy_enemy(reg, iid):
                    ids.append(sid)
        except Exception:
            pass
    elif category == "item":
        try:
            craft = set(_craft_ids(ctx))
            for iid in reg.all_ids("item"):
                sid = str(iid)
                if sid not in craft:
                    ids.append(sid)
        except Exception:
            pass
    elif category == "craft":
        ids = _craft_ids(ctx)
    elif category == "fish":
        ids = _fish_ids(ctx)
    return list(dict.fromkeys(ids))


def item_craft_relation(ctx: Mapping[str, Any], item_id: str) -> str:
    """物品归属判定（4d D-04，M11 批2 路2A）：制造源命中 → craft；否则 → item。

    入参 ctx/context；item_id 物品 id。出参 str：\"craft\" / \"item\"。
    判据：forge 树节点 item 引用 ∪ 炼金 recipe output.item 命中 → craft；其余 → item。
    """
    if not isinstance(item_id, str) or not item_id:
        return "item"
    if item_id in _craft_ids(ctx):
        return "craft"
    return "item"


def _total_of(ctx: Mapping[str, Any], category: str) -> int:
    """分册可收集总数（_category_ids 长度；补白 3：无 registry → 0 fail-safe）。"""
    return len(_category_ids(ctx, category))


def _refresh_projection(ctx: MutableMapping[str, Any]) -> None:
    """刷新全局完成度投影 ctx["codex"]（未取整等权分册均值，补白 2）。"""
    pct = codex_progress(ctx).get("pct", 0.0)
    ctx["codex"] = float(pct)


# 四册加权（4d §2.1，M11 批2 路2B）：默认等权 1:1:1:1
CODEX_BOOKS: Tuple[str, ...] = ("monster", "fish", "item", "craft")
_DEFAULT_WEIGHTS: Tuple[float, ...] = (1.0, 1.0, 1.0, 1.0)


def _codex_weights(ctx: Mapping[str, Any]) -> Tuple[float, ...]:
    """权重配置读取（4d §2.1 L162-167，G-16）：settings.codex.weights 四键。

    逐键校验：缺失/负数/非数值/布尔 → 回落该键默认 1；全 0 → 整体回落等权。
    """
    weights = list(_DEFAULT_WEIGHTS)
    settings = ctx.get("settings")
    if isinstance(settings, Mapping):
        codex_cfg = settings.get("codex")
        if isinstance(codex_cfg, Mapping):
            raw = codex_cfg.get("weights")
            if isinstance(raw, Mapping):
                for i, book in enumerate(CODEX_BOOKS):
                    v = raw.get(book)
                    if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0:
                        weights[i] = float(v)
    if all(w == 0 for w in weights):
        weights = list(_DEFAULT_WEIGHTS)
    return tuple(weights)


def codex_progress(
    ctx: MutableMapping[str, Any], category: Optional[str] = None
) -> dict:
    """完成度计算（4d COD-08 / R-19）：{total, seen, killed, pct}。

    入参 ctx: 上下文（codex_state/registry）；category: 分册名或 None=全局。
    出参 dict: total 分母 / seen 已见数 / killed 击杀数 / pct 完成度（未取整 0-100）。
    核心逻辑: 单册 pct=seen/total×100；全局=四册加权 T=Σ(wi·Vi)/Σwi（4d §2.2，
    交集核算悬空 ID 不计入 COD-01/TC-10）；total=0 → pct=0。
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
    # 全局：四册加权 T=Σ(wi·Vi)/Σwi（4d §2.2 L173-178；M11 批2 路2B）
    # 交集核算（COD-01/TC-10）：每册 seen/killed 与 _category_ids 求交，悬空 ID 不计
    weights = _codex_weights(ctx)
    total = seen = killed = 0
    pct_sum = 0.0
    w_sum = 0.0
    for i, cat_name in enumerate(CODEX_BOOKS):
        w = weights[i] if i < len(weights) else 1.0
        w_sum += w
        ids = set(_category_ids(ctx, cat_name))
        cat = _cat_state(ctx, cat_name)
        cat_seen = sum(1 for rid, e in cat.items()
                       if isinstance(e, Mapping) and e.get("seen") and rid in ids)
        cat_killed = sum(1 for rid, e in cat.items()
                         if isinstance(e, Mapping) and e.get("killed") and rid in ids)
        v = (cat_seen / len(ids) * 100.0) if ids else 0.0
        total += len(ids)
        seen += cat_seen
        killed += cat_killed
        pct_sum += w * v
    pct = pct_sum / w_sum if w_sum else 0.0
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
    # 木桩拦截（COD-05，M11 批2 路2A）：monster 册木桩不入图鉴
    if category == "monster":
        reg = _registry_of(ctx)
        if reg is not None and _is_dummy_enemy(reg, str(ref_id)):
            return {"ok": False, "reason": "dummy_excluded", "first_seen": False}
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
    # M11 批2 路2C（4d D-05 + L149-150 结算点链）：点亮 → lore 行级重判
    # （里程碑检查不放这里——codex_milestones 惰性 import codex 构成静态环，
    #  由装配层/结算点接线方在 mark_seen 后调 check_milestones）
    try:
        sync_lore_unlocks(ctx)
    except Exception:
        pass
    # M11 批4 A1 P0-1 修复：图鉴点亮结算点 → 成就达成检测（4c D-07 授予时机）。
    # 惰性 import 防环（achievements 不 import codex，codex → achievements 单向 OK）；
    # try/except 防成就异常吞图鉴点亮。
    if first_seen:
        try:
            from qbot_rpg.core.achievements import check_achievements

            check_achievements(ctx, sources=["codex"])
        except Exception:
            pass
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
    """传闻解锁（F-16 定向线索，BCH-09 接线）：条目 lore_unlocked=true。

    M11 批2 路2C（4d D-05 行级）：lore 行级状态 unlocked_lore 行数——按全局完成度
    T（未取整）≥ unlock 逐行解锁；本函数保留条目级布尔兼容（environment_lore
    lore_view 依赖），行级状态由 sync_lore_unlocks 维护。
    """
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


def _lore_thresholds(ctx: Mapping[str, Any], category: str, ref_id: str) -> list:
    """条目 lore unlock 阈值列表（enemies.json lore[].unlock；无 → []）。

    数据源：registry resolve(category kind) 读 raw lore[].unlock（1-100 递增）。
    """
    reg = _registry_of(ctx)
    if reg is None:
        return []
    kind = (CATEGORIES.get(category) or ("enemy",))[0]
    resolve = getattr(reg, "resolve", None)
    if not callable(resolve):
        return []
    try:
        d = resolve(ref_id, kind)
    except Exception:
        return []
    raw = d if isinstance(d, Mapping) else getattr(d, "raw", None)
    if not isinstance(raw, Mapping):
        return []
    lore = raw.get("lore")
    if not isinstance(lore, list):
        return []
    out = []
    for row in lore:
        if isinstance(row, Mapping) and isinstance(row.get("unlock"), (int, float)):
            out.append(int(row["unlock"]))
    return out


def sync_lore_unlocks(ctx: MutableMapping[str, Any]) -> dict:
    """lore 行级解锁同步（4d D-05，M11 批2 路2C）：按全局完成度 T 未取整 ≥ unlock
    逐行解锁已见条目。

    判据=全局 pct（未取整）≥ unlock（COD-08）；已见条目写 unlocked_lore 行数；
    隐藏要素发现后 lore 全集一次性解锁（unlock 全 100 + 传闻段，4d §5 L356）。
    """
    # 全局完成度：ctx["codex"] 投影优先（装配层算好的 T，测试可注入）；
    # 缺省 → codex_progress 现算（裸 ctx 兜底）。
    pct = ctx.get("codex")
    if not isinstance(pct, (int, float)) or isinstance(pct, bool):
        pct = codex_progress(ctx).get("pct", 0.0)
    pct = float(pct)
    st = ctx.get("codex_state")
    if not isinstance(st, Mapping):
        return {"ok": True, "updated": 0}
    updated = 0
    for cat_name, cat in st.items():
        if not isinstance(cat, MutableMapping):
            continue
        for rid, raw in list(cat.items()):
            if not isinstance(raw, Mapping) or not raw.get("seen") or rid == "__meta__":
                continue
            thresholds = _lore_thresholds(ctx, cat_name, str(rid))
            if not thresholds:
                continue
            unlocked_rows = sum(1 for t in thresholds if pct >= t)
            cur = int(raw.get("unlocked_lore", 0) or 0)
            if unlocked_rows > cur:
                entry = dict(raw)
                entry["unlocked_lore"] = unlocked_rows
                cat[rid] = entry
                updated += 1
    return {"ok": True, "updated": updated}


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
