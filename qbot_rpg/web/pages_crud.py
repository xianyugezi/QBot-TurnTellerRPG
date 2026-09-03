"""编辑器六页 CRUD + 校验 + 级联删除纯逻辑层（M12 批1 路1C · 细化_5a 编辑器契约）。

文件名：qbot_rpg/web/pages_crud.py
创建时间：2026-09-03

功能描述（对齐细化_5a §6.3 六页 CRUD 端点语义 L176-181 + SV-01~08）：
  - list_page_items(page, ctx) -> {items, total, page, size}：分页/搜索/排序
    （虚拟滚动数据源，5a L176 / 框架 L982）
  - get_page_item(page, id, ctx) -> {ok, item, refs}：单条详情 + 引用字段中文名
    （refs 供 C-05 引用芯片渲染，5a L177）
  - create_page_item(page, data, ctx) -> {ok, item}|{ok:false, errors[]}：
    新建，ID 自动生成 `类型_序号`（TC-01 例 skill_0001，5a L214）
  - update_page_item(page, id, data, base_version, ctx)：更新，版本冲突 409
    （编辑锁，5a L179）
  - delete_page_item(page, id, ctx) -> {ok, cascades[]}|404：级联清理（5a L180）
  - validate_page_item(page, data, ctx) -> {red[], yellow[]}：草稿校验不落盘

【工程补白 · 显式标注】
  1) 本层为纯逻辑：只读 registry.modules_raw，不写磁盘（原子写盘归批 2 路 2A
     SV-06）；写操作返回「待写变更」{module_file, entries, id} 由上层落盘。
  2) 模块文件名以 loader._KIND_FOR_MODULE 实际登记为准：quest.json（单数）——
     5a 契约 P-06 写 quests.json 是文档笔误（1C 勘察实测 loader L192 + test_demo
     实文件 quest.json）；skills.json/jobs.json/enemies.json/maps.json/shop.json
     与契约一致。
  3) 数据源 = Registry.modules_raw[模块名]：顶层 list 形态（真实包全部如此），
     每条目含 id/name；forge/fishing/settings 等顶层 obj 模块不属六页 CRUD
     （编辑器扩展页另行处理）。
  4) 版本簿：仓库无 base_version/编辑锁代码（m12_编辑器摸底 L96-104 全【缺】），
     本模块自带内存版本簿 {模块名: {id: version}}，create 置 0、update 自增；
     跨进程/重启失效（编辑器单进程内编辑锁语义，SV-08 旧快照续战兼容）。
  5) 校验：红拦 5 类（SV-03：类型错误/负数/非数字/引用不存在/结构错误）；
     黄提示（SV-04：数值范围/概率/组合强度/未登记引用提示）。完整校验器
     复用 content/validator（check_pack），本层 validate 端点做「草稿级」快速
     红黄分级（5a 6.3 validate L181-183：红/黄皆返回 200 供前端渲染）。
  6) 级联删除（5a L180）：
     - 删怪物 → maps[].monsters[]（键 enemy==id）条目移除、maps[].gate_guard
       ==id 清空、drops 随条目移除；
     - 删物品 → enemies[].drops.{battle,special,death}[].item==id 条目移除、
       shop[].items[].item==id 移除、quest[].reward[] item 行移除；
     - 删地图 → 其它 maps[].exits{方向:{to}} to==id 通道移除、dungeon[].maps
       数组内剔除（另 safe_zone/boss_room 字段引用——按 dungeon 形态宽容处理）；
     - 删职业 → skills[].job_restrict[] 数组剔除该 job id、jobs 自身条目移除、
       玩家转职引用（job_id）不在配置层级联范围（玩家存档运行时数据）。
     返回 cascades = [{module, item_id, removed_ref:{field, value}}...]。
  7) ID 生成：`类型_序号`，序号 = 现有 `类型_` 前缀最大序号 + 1，4 位零填充
     （TC-01 skill_0001），冲突重扫（上限重试防死循环）。

铁律：零 NoneBot import；纯函数（同刻同参必同值，零 IO 零随机零定时器）；
      web → content 正向依赖（G0 允许：web/api.py L4-5 声明方向）；
      rng/now 确定性注入；工程补白显式标注；全中文注释。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Sequence

# =============================================================================
# 六页归口表（loader._KIND_FOR_MODULE 实际登记名；契约 P-06 quests.json 笔误修正）
# =============================================================================

# page_id → 模块文件名（Registry.modules_raw 键）
PAGE_MODULE: Mapping[str, str] = {
    "skill": "skills",
    "job": "jobs",
    "monster": "enemies",
    "map": "maps",
    "quest": "quest",      # 契约 P-06 写 quests.json，loader 登记 quest.json（实测）
    "shop": "shop",
}

# page_id → 显示名前缀（ID 自动生成 `类型_序号`，TC-01 skill_0001 例：前缀=页名）
PAGE_ID_PREFIX: Mapping[str, str] = {
    "skill": "skill",
    "job": "job",
    "monster": "monster",
    "map": "map",
    "quest": "quest",
    "shop": "shop",
}

# page_id → 条目主键字段（真实内容包统一 id）
PAGE_ID_FIELD: Mapping[str, str] = {
    p: "id" for p in PAGE_MODULE
}

# =============================================================================
# 基础工具
# =============================================================================

def _entries_of(ctx: Mapping[str, Any], page: str) -> list:
    """modules_raw 该页条目数组（顶层 list；非 list/缺失 → [] 安全兜底）。"""
    module = PAGE_MODULE.get(page, "")
    if not module:
        return []
    raw = ctx.get("modules_raw")
    if not isinstance(raw, Mapping):
        return []
    data = raw.get(module)
    return data if isinstance(data, list) else []


def _num(value: Any, default: int = 0) -> int:
    """数值化（bool 不算；非法 → default）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _find_item(entries: Sequence[Any], page: str, item_id: str) -> Optional[Mapping[str, Any]]:
    """按主键查条目（宽容：dict 形态条目含 id 字段；无 id 跳过）。"""
    key = PAGE_ID_FIELD.get(page, "id")
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        if str(e.get(key) or "") == item_id:
            return e
    return None


def _item_name(e: Mapping[str, Any]) -> str:
    """条目显示名（name 字段；缺省 id）。"""
    nm = e.get("name")
    return str(nm) if isinstance(nm, str) and nm else str(e.get("id") or "")


def _ref_display(ctx: Mapping[str, Any], kind: str, ref_id: str) -> str:
    """跨表引用中文名解析（ctx 需含模块表；查无 → 原 id）。"""
    module_map: Mapping[str, str] = {
        "monster": "enemies", "enemy": "enemies", "item": "items",
        "skill": "skills", "job": "jobs", "map": "maps", "quest": "quest",
        "shop": "shop", "npc": "npc", "effect": "effects", "status": "statuses",
    }
    module = module_map.get(kind)
    if not module:
        return str(ref_id)
    raw = ctx.get("modules_raw")
    if not isinstance(raw, Mapping):
        return str(ref_id)
    data = raw.get(module)
    if not isinstance(data, list):
        return str(ref_id)
    for e in data:
        if isinstance(e, Mapping) and str(e.get("id") or "") == ref_id:
            nm = e.get("name")
            if isinstance(nm, str) and nm:
                return nm
            return ref_id
    return str(ref_id)


def _validate_scalar_red(
    errors: List[dict], field: str, value: Any, *, allow_negative: bool = False,
) -> None:
    """红拦基础校验（SV-03）：类型/负数/非数字。"""
    if isinstance(value, bool):
        errors.append({"level": "red", "code": "type_error", "field": field,
                       "message": f"「{field}」不能是布尔值"})
        return
    if isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            errors.append({"level": "red", "code": "not_number", "field": field,
                           "message": f"「{field}」不是数字：{value}"})
            return
        if not allow_negative and num < 0:
            errors.append({"level": "red", "code": "negative", "field": field,
                           "message": f"「{field}」不能为负数"})
        return
    if isinstance(value, (int, float)):
        if not allow_negative and value < 0:
            errors.append({"level": "red", "code": "negative", "field": field,
                           "message": f"「{field}」不能为负数"})
        return
    errors.append({"level": "red", "code": "type_error", "field": field,
                   "message": f"「{field}」类型错误：期望数字，收到 {type(value).__name__}"})


def _red(type_: str, field: str, msg: str) -> dict:
    """红拦条目构造。"""
    return {"level": "red", "code": type_, "field": field, "message": msg}


def _yellow(type_: str, field: str, msg: str) -> dict:
    """黄提示条目构造。"""
    return {"level": "yellow", "code": type_, "field": field, "message": msg}


# =============================================================================
# 列表 / 详情
# =============================================================================

def list_page_items(
    page: str,
    ctx: Mapping[str, Any],
    *,
    page_no: int = 1,
    size: int = 50,
    q: str = "",
    sort: str = "",
) -> Dict[str, Any]:
    """列表（分页/搜索/排序）：?page=&size=&q=&sort= 语义（5a L176）。

    搜索 q：name/id 子串匹配（大小写不敏感）；排序 sort：`字段` 或 `-字段`
    （倒序），缺省保持声明序。未知 page → {ok:false, errors:[404]}。
    """
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    entries = _entries_of(ctx, page)
    page_no = max(1, _num(page_no, 1))
    size = max(1, min(200, _num(size, 50)))
    q = str(q or "").strip().lower()
    items: List[Mapping[str, Any]] = []
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        if q:
            hay = f"{e.get('id', '')} {e.get('name', '')}".lower()
            if q not in hay:
                continue
        items.append(dict(e))
    # 排序（name/id 数值安全）
    if sort:
        desc = sort.startswith("-")
        key = sort[1:] if desc else sort
        try:
            def _sort_key(x: Mapping[str, Any]) -> Any:
                v = x.get(key)
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return (0, v)
                return (1, str(v or "").lower())

            items.sort(key=_sort_key, reverse=desc)
        except Exception:
            pass  # 排序字段非法 → 保持原序
    total = len(items)
    start = (page_no - 1) * size
    return {
        "ok": True,
        "items": items[start:start + size],
        "total": total,
        "page": page_no,
        "size": size,
    }


def get_page_item(page: str, item_id: str, ctx: Mapping[str, Any]) -> Dict[str, Any]:
    """单条详情 + 引用字段中文名（5a L177：字段值 + 引用芯片渲染所需中文名）。"""
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    entries = _entries_of(ctx, page)
    hit = _find_item(entries, page, item_id)
    if hit is None:
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}
    item = dict(hit)
    # 引用字段中文名解析（覆盖六页常见引用键；refs = {字段: {id: 中文名}}）
    refs: Dict[str, Dict[str, str]] = {}

    def _collect_ref(field: str, kind: str, rid: str) -> None:
        """收集单条引用 → refs[field][rid] = 中文名。"""
        if not isinstance(rid, str) or not rid:
            return
        refs.setdefault(field, {})[rid] = _ref_display(ctx, kind, rid)

    for field, kind in (
        ("enemy", "monster"), ("monster", "monster"), ("item", "item"),
        ("skill", "skill"), ("job", "job"), ("map", "map"), ("quest", "quest"),
        ("shop", "shop"), ("npc", "npc"), ("effect", "effect"), ("status", "status"),
    ):
        v = item.get(field)
        if isinstance(v, str) and v:
            _collect_ref(field, kind, v)
        elif isinstance(v, list):
            for x in v:
                if isinstance(x, str):
                    _collect_ref(field, kind, x)
                elif isinstance(x, Mapping):
                    rid = x.get("item") or x.get("enemy") or x.get("id") or x.get("skill")
                    if isinstance(rid, str) and rid:
                        _collect_ref(field, kind, rid)
    # 嵌套结构引用（地图 monsters[] 每行 {enemy: id} / 商店 items[] 每行 {item: id}
    # / 任务 reward[] {item: id}）——列表字段键与引用字段分离时按嵌套容器名收集
    if page in ("map", "monster"):
        monsters = item.get("monsters")
        if isinstance(monsters, list):
            for mrow in monsters:
                if isinstance(mrow, Mapping):
                    rid = mrow.get("enemy") or mrow.get("monster")
                    if isinstance(rid, str) and rid:
                        _collect_ref("monster", "monster", rid)
    if page == "shop":
        goods = item.get("items")
        if isinstance(goods, list):
            for grow in goods:
                if isinstance(grow, Mapping):
                    rid = grow.get("item") or grow.get("goods")
                    if isinstance(rid, str) and rid:
                        _collect_ref("item", "item", rid)
    if page == "quest":
        rewards = item.get("reward")
        if isinstance(rewards, list):
            for rrow in rewards:
                if isinstance(rrow, Mapping):
                    rid = rrow.get("item") or rrow.get("id")
                    if isinstance(rid, str) and rid:
                        _collect_ref("item", "item", rid)
    return {"ok": True, "item": item, "refs": refs}


# =============================================================================
# 新建 / 更新（版本簿 + ID 生成）
# =============================================================================

def _next_id(entries: Sequence[Any], page: str, ctx: Mapping[str, Any]) -> str:
    """ID 自动生成：`类型_序号`，序号 = 现有同前缀最大序号 + 1，4 位零填充。

    已用序号来源 = modules_raw 条目 ∪ 版本簿已登记 id（create 未落盘但已发号
    的条目记入版本簿——纯逻辑层不 append 原列表，靠版本簿防连续 create 重号）。
    """
    prefix = PAGE_ID_PREFIX.get(page, page)
    key = PAGE_ID_FIELD.get(page, "id")
    max_seq = 0
    seen: set = set()
    for e in entries:
        if not isinstance(e, Mapping):
            continue
        eid = str(e.get(key) or "")
        seen.add(eid)
        if eid.startswith(prefix + "_"):
            tail = eid[len(prefix) + 1:]
            if tail.isdigit():
                max_seq = max(max_seq, int(tail))
    # 版本簿已发号 id 并入 seen/序号（连续 create 不 append 原列表的补偿）
    module = PAGE_MODULE.get(page, "")
    vb = ctx.get("_page_versions")
    if isinstance(vb, Mapping) and module:
        for eid in (vb.get(module) or {}):
            if isinstance(eid, str) and eid.startswith(prefix + "_"):
                seen.add(eid)
                tail = eid[len(prefix) + 1:]
                if tail.isdigit():
                    max_seq = max(max_seq, int(tail))
    for _ in range(100):  # 冲突重扫（上限防死循环）
        max_seq += 1
        cand = f"{prefix}_{max_seq:04d}"
        if cand not in seen:
            return cand
    return f"{prefix}_{max_seq:04d}"


def _versions(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """版本簿（ctx 承载：{模块名: {id: version}}；create 置 0 / update 自增）。"""
    vb = ctx.get("_page_versions")
    if not isinstance(vb, MutableMapping):
        vb = {}
        ctx["_page_versions"] = vb
    return vb


def create_page_item(
    page: str,
    data: Mapping[str, Any],
    ctx: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """新建：ID 自动生成 `类型_序号`；返回条目（5a L178，201 语义）。"""
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    entries = _entries_of(ctx, page)
    key = PAGE_ID_FIELD.get(page, "id")
    item = dict(data)
    new_id = str(item.get(key) or "").strip()
    if new_id:
        if _find_item(entries, page, new_id) is not None:
            return {"ok": False, "errors": [
                _red("dup_id", key, f"已经有一个叫『{new_id}』的条目了，换个 id 吧")]}
    else:
        new_id = _next_id(entries, page, ctx)
        item[key] = new_id
    item.setdefault("name", new_id)
    # 版本簿：create 置 0
    module = PAGE_MODULE[page]
    _versions(ctx).setdefault(module, {})[new_id] = 0
    return {"ok": True, "item": item, "id": new_id}


def update_page_item(
    page: str,
    item_id: str,
    data: Mapping[str, Any],
    base_version: Optional[int],
    ctx: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """更新：版本冲突 409（编辑锁）；版本簿自增（5a L179）。"""
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    entries = _entries_of(ctx, page)
    key = PAGE_ID_FIELD.get(page, "id")
    hit = _find_item(entries, page, item_id)
    if hit is None:
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}
    module = PAGE_MODULE[page]
    vb = _versions(ctx).setdefault(module, {})
    cur_ver = int(vb.get(item_id, 0) or 0)
    if base_version is not None and int(base_version) != cur_ver:
        return {"ok": False, "code": 409,
                "errors": [_red("version_conflict", "base_version",
                                f"条目已被他人修改（当前版本 {cur_ver}），请刷新后重试")]}
    # 合并更新（保留未提交字段；id 不可改）
    merged = dict(hit)
    for k, v in data.items():
        if k != key:
            merged[k] = v
    vb[item_id] = cur_ver + 1
    return {"ok": True, "item": merged, "id": item_id, "version": vb[item_id]}


# =============================================================================
# 删除（级联清理 · 5a L180）
# =============================================================================

def _remove_ref_from_list(entry: MutableMapping[str, Any], field: str, ref_id: str) -> bool:
    """从条目列表字段移除含 ref_id 的项（项为 str 或 {键: ref_id} dict）。"""
    raw = entry.get(field)
    if not isinstance(raw, list):
        return False
    kept: list = []
    removed = False
    for x in raw:
        if isinstance(x, str):
            if x == ref_id:
                removed = True
                continue
        elif isinstance(x, Mapping):
            if any(str(v) == ref_id for v in x.values() if isinstance(v, (str, int))):
                removed = True
                continue
        kept.append(x)
    if removed:
        entry[field] = kept
    return removed


def delete_page_item(
    page: str,
    item_id: str,
    ctx: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """删除 + 级联清理：返回 cascades 变更清单（待写盘，5a L180）。"""
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    raw = ctx.get("modules_raw")
    if not isinstance(raw, MutableMapping):
        return {"ok": False, "errors": [_red("internal", "", "数据源不可用")]}
    module = PAGE_MODULE[page]
    entries = raw.get(module)
    if not isinstance(entries, list):
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}
    hit = _find_item(entries, page, item_id)
    if hit is None:
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}

    cascades: List[dict] = []
    removed_name = _item_name(hit)

    if page == "monster":
        # 删怪物 → maps[].monsters[]（enemy==id）移除、maps[].gate_guard==id 清空
        maps = raw.get("maps")
        if isinstance(maps, list):
            for m in maps:
                if not isinstance(m, MutableMapping):
                    continue
                if _remove_ref_from_list(m, "monsters", item_id):
                    cascades.append({"module": "maps", "item_id": m.get("id"),
                                     "removed_ref": {"field": "monsters", "value": item_id}})
                if str(m.get("gate_guard") or "") == item_id:
                    m["gate_guard"] = ""
                    cascades.append({"module": "maps", "item_id": m.get("id"),
                                     "removed_ref": {"field": "gate_guard", "value": item_id}})
        # 怪物自身 drops 随条目移除（无需额外级联）
    elif page == "shop":
        # 删商店条目本身（shop 是 list 条目）
        pass
    elif page == "quest":
        # 删任务条目本身
        pass
    elif page == "map":
        # 删地图 → 其它 maps[].exits{方向:{to}} to==id 通道移除、dungeon[].maps 剔除
        maps = raw.get("maps")
        if isinstance(maps, list):
            for m in maps:
                if not isinstance(m, MutableMapping):
                    continue
                if str(m.get("id") or "") == item_id:
                    continue  # 自身条目删除不在此级联（条目移除由写盘层做）
                exits = m.get("exits")
                if isinstance(exits, MutableMapping):
                    for direction, dest in list(exits.items()):
                        if isinstance(dest, Mapping) and str(dest.get("to") or "") == item_id:
                            exits.pop(direction, None)
                            cascades.append({"module": "maps", "item_id": m.get("id"),
                                             "removed_ref": {"field": f"exits.{direction}",
                                                             "value": item_id}})
                # respawn_point 指向被删地图 → 清空
                if str(m.get("respawn_point") or "") == item_id:
                    m["respawn_point"] = ""
                    cascades.append({"module": "maps", "item_id": m.get("id"),
                                     "removed_ref": {"field": "respawn_point", "value": item_id}})
        dg = raw.get("dungeon")
        if isinstance(dg, list):
            for d in dg:
                if not isinstance(d, MutableMapping):
                    continue
                if _remove_ref_from_list(d, "maps", item_id):
                    cascades.append({"module": "dungeon", "item_id": d.get("id"),
                                     "removed_ref": {"field": "maps", "value": item_id}})
    elif page == "job":
        # 删职业 → skills[].job_restrict[] 剔除该 job id
        skills = raw.get("skills")
        if isinstance(skills, list):
            for s in skills:
                if not isinstance(s, MutableMapping):
                    continue
                if _remove_ref_from_list(s, "job_restrict", item_id):
                    cascades.append({"module": "skills", "item_id": s.get("id"),
                                     "removed_ref": {"field": "job_restrict", "value": item_id}})
    # monster 之外六页通用物品引用（删怪物时无此）——契约要求「删物品→掉落/商店/
    # 任务奖励移除」，物品非六页（items.json 是素材/道具不是 monster），故 items 页
    # 不在六页 CRUD（P-06 六页 = skill/job/monster/map/quest/shop）。shop 页删除的
    # 商品引用自身已随条目移除。skill 页删除：契约 L180 未列技能级联（最小实现只
    # 删条目本身，job.transform 引用属扩展页语义批 4 处理）。

    # 版本簿清理
    vb = _versions(ctx).get(module, {})
    vb.pop(item_id, None)
    return {"ok": True, "id": item_id, "name": removed_name, "cascades": cascades}


# =============================================================================
# 草稿校验（validate 端点：红/黄清单不落盘 · 5a L181-183）
# =============================================================================

def validate_page_item(
    page: str,
    data: Mapping[str, Any],
    ctx: Mapping[str, Any],
) -> Dict[str, Any]:
    """草稿校验：红/黄两级清单（不落盘，200 语义）。红 = 5 类硬错；黄 = 提示。"""
    red: List[dict] = []
    yellow: List[dict] = []
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}

    # 基础字段存在性（结构错误红拦：必填 id/name）
    for f in ("id",):
        if f not in data or data[f] in (None, ""):
            red.append(_red("struct", f, f"缺少必填字段「{f}」"))
    name = data.get("name")
    if isinstance(name, str) and len(name) > 20:
        yellow.append(_yellow("range", "name", f"名字较长（{len(name)} 字），建议 ≤20 字"))

    # 数值字段类型/负数红拦（SV-03 ①②③——页面常见数值键）
    for f in ("hp", "mp", "atk", "def", "spd", "exp", "price", "cost",
              "str", "con", "agi", "foc", "spr", "lck", "weight", "chance"):
        if f in data and data[f] is not None:
            _validate_scalar_red(red, f, data[f])

    # 引用存在性（SV-03 ④引用不存在红拦——常见引用键；ctx 无对应表 → 黄提示）
    for f, kind in (("enemy", "monster"), ("item", "item"), ("skill", "skill"),
                    ("job", "job"), ("map", "map"), ("quest", "quest"),
                    ("shop", "shop"), ("npc", "npc")):
        v = data.get(f)
        if isinstance(v, str) and v and not _ref_exists(ctx, kind, v):
            yellow.append(_yellow("ref_unregistered", f,
                                  f"引用「{v}」未登记（{kind} 表查无）——保存后可能失效"))
    # 结构错误红拦（⑤）：条件 min>max 等死配置（常见 pattern）
    for lo_f, hi_f in (("min", "max"), ("min_hp", "max_hp"), ("low", "high")):
        lo, hi = data.get(lo_f), data.get(hi_f)
        if isinstance(lo, (int, float)) and isinstance(hi, (int, float)) \
                and not isinstance(lo, bool) and not isinstance(hi, bool) and lo > hi:
            red.append(_red("struct", f"{lo_f}.{hi_f}",
                            f"「{lo_f}」（{lo}）大于「{hi_f}」（{hi}），配置自相矛盾"))

    return {"ok": True, "red": red, "yellow": yellow}


def _ref_exists(ctx: Mapping[str, Any], kind: str, ref_id: str) -> bool:
    """引用存在性（跨表查 modules_raw；无表/无条目 → False）。"""
    module_map: Mapping[str, str] = {
        "monster": "enemies", "enemy": "enemies", "item": "items",
        "skill": "skills", "job": "jobs", "map": "maps", "quest": "quest",
        "shop": "shop", "npc": "npc",
    }
    module = module_map.get(kind)
    if not module:
        return False
    raw = ctx.get("modules_raw")
    if not isinstance(raw, Mapping):
        return False
    data = raw.get(module)
    if not isinstance(data, list):
        return False
    return any(
        isinstance(e, Mapping) and str(e.get("id") or "") == ref_id
        for e in data
    )


# =============================================================================
# 变更落盘辅助（批 2 原子写盘路消费：把 delete 的级联/条目移除转成「最终 entries」）
# =============================================================================

def apply_delete_to_entries(
    page: str,
    item_id: str,
    ctx: MutableMapping[str, Any],
) -> Dict[str, Any]:
    """执行删除（对 modules_raw 原地移除条目 + 级联已由 delete_page_item 完成）。

    返回 {ok, module, entries}：entries = 移除目标后的新列表（供原子写盘层
    直接写 JSON）。纯逻辑，不碰磁盘。
    """
    if page not in PAGE_MODULE:
        return {"ok": False, "errors": [_red("not_found", "page", f"页面不存在：{page}")]}
    raw = ctx.get("modules_raw")
    if not isinstance(raw, MutableMapping):
        return {"ok": False, "errors": [_red("internal", "", "数据源不可用")]}
    module = PAGE_MODULE[page]
    entries = raw.get(module)
    if not isinstance(entries, list):
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}
    key = PAGE_ID_FIELD.get(page, "id")
    kept = [e for e in entries if not (
        isinstance(e, Mapping) and str(e.get(key) or "") == item_id)]
    if len(kept) == len(entries):
        return {"ok": False, "errors": [_red("not_found", "id", f"条目不存在：{item_id}")]}
    raw[module] = kept
    return {"ok": True, "module": module, "entries": kept}


# 模块文件映射导出（上层 /api/meta、写盘层复用）
PAGE_FILE: Mapping[str, str] = {p: f"{m}.json" for p, m in PAGE_MODULE.items()}

__all__ = [
    "PAGE_MODULE",
    "PAGE_FILE",
    "PAGE_ID_PREFIX",
    "apply_delete_to_entries",
    "create_page_item",
    "delete_page_item",
    "get_page_item",
    "list_page_items",
    "update_page_item",
    "validate_page_item",
]
