"""世界移动处理层 —— M3 批次3·路K（M05 隐藏通道条件 + M06 /进入 <方向> 接线 + 地图切换钩子）。

依据：
  - 细化_2a1b_通道规则与刷怪.md §1.3（通道与移动/换区/副本状态衔接 R11-R13；
    隐藏判定 §1.2 R7-R9 条件打开；TC-01~TC-06）
  - 细化_2a1c_地图副本衔接.md §3（/进入 参数解析 R14-R18：方向字面量 → 纯数字序号 →
    名称匹配逐级；R20 上下文路由；R22 切换图双钩子）
  - m3_shared_contract.md §2.4（地图行走判定接口 can_move → MoveResult
    {ok, to, mode, hidden_ok, blocked_reason?}；§5.3 IF11 map_weather_seen）
  - world_time_persist.mark_map_seen（M35 / IF11 数据契约：map_weather_seen 惰性增长）

职责（world 层处理器，纯数据：ctx dict 进出，无 IO）：
  resolve_move        /进入 <方向> 通道行走（M05 隐藏通道条件门 + M06 行走接线）
  move_to_map         地图切换钩子（位置原地改 + map_weather_seen 记录 + R22 双钩子）
  enter_context_route /进入 参数路由（方向 → 通道行走；入口名/序号 → 进副本信号）

铁律：零 NoneBot import（契约 §八 4）；纯函数；失败不改变 ctx；隐藏通道条件由
conditions callable 注入（未注入/求值失败 = 不可走，fail-safe，2a1d LC-D）。

【工程补白】（显式标注，不冒充定稿）：
  1. 副本进入：本路仅返回命中信号 {type:"dungeon", dungeon_id}（入口存在性检查 +
     入口名/序号匹配）；入场校验（entry_item/entry_limit）、外部锚点记录、副本身份
     激活、落位 safe_zone 由**批次 5**（M16/M20）实装接线。
  2. core/map_graph.py（批次3·路J）已落盘：非隐藏通道判定优先调
     map_graph.can_move(map_id, direction, ctx)，ctx 约定键与路J 对齐：
     maps（**list**，见 _maps_list）/ conditions（callable(cond)->bool 单参形态；
     本路 _hidden_ok 双兼容单参/双参）。map_graph 未落盘时按契约 §2.4 本地实现
     _contract_can_move 兜底（收口对齐）。M05 隐藏通道判定属本路（K）交付：
     hidden 门以本路 conditions 注入为准（resolve_move 先于 can_move 把关）。
  3. map_weather_seen 记录落点 ctx["time_state"]（world_time_persist 契约形态）；
     存储层真实存档（SQLite/WorldState）由 M4 路3 A4 接线。
  4. R22 切换图「离开+进入」双钩子承载点 ctx["move_hooks"] = {on_leave, on_enter}；
     时段边界怪物移除/补刷/天气池刷新由**批次 4**（刷怪 M08-M10）接线。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple, Union, cast

from qbot_rpg.content.map_models import MapDef, parse_maps
from qbot_rpg.data.world_time_persist import mark_map_seen

__all__ = [
    "DIRECTION_ALIASES",
    "resolve_move",
    "move_to_map",
    "enter_context_route",
]

# 方向字面量（2a1c §3.1 R15：「上/下/左/右（别名 北/南/东/西 可选）」）→ 配置键
# 北=up / 南=down / 东=right / 西=left（对齐 legal 包地图语义：北通=up、南入=down、东侧=right）
DIRECTION_ALIASES: Dict[str, str] = {
    "up": "up", "down": "down", "left": "left", "right": "right",
    "上": "up", "下": "down", "左": "left", "右": "right",
    "北": "up", "南": "down", "东": "right", "西": "left",
}

# 契约 §2.4 / 2a1b TC-02·TC-03 / 2a1c TC-02·TC-05 提示口径
_REASON_NO_EXIT = "此方向没有通道"          # 未配置方向 = 死路 / 单向反方向（2a1c TC-05、R18）
_REASON_HIDDEN = "此处无通道"               # hidden 条件未满足（契约 §2.4）
_REASON_BLOCKED = "此路不通"                # 兜底拦截（契约 §2.4 单向反向拦截口径）
_REASON_NO_ENTRANCE = "此处没有副本入口"     # 非入口节点（2a1c TC-14）
_REASON_INVALID_ENTRANCE = "入口序号无效"     # M3 审查 P1-3：Unicode 数字/越界序号
_REASON_NOT_FOUND = "没有这个入口/方向"      # 名称/序号未命中（任务口径）
_REASON_NO_ARG = "/进入 需要参数：方向 / 序号 / 入口名（便捷指令未开放）"  # 2a1c TC-23


# =====================================================================================
# 数据归一（纯函数，无 IO）
# =====================================================================================
def _maps_index(maps: object) -> Dict[str, MapDef]:
    """maps 入参归一 → {map_id: MapDef}。

    接受：modules 容器（{"maps": [...]}）/ MapDef 列表 / 原始节点 dict 列表 /
    单个节点 dict / None（空）。零失败（形态异常 → 空索引）。
    """
    if maps is None:
        return {}
    if isinstance(maps, Mapping):
        if "maps" in maps:  # modules 容器（content 装载形态）
            entries = maps.get("maps")
            if isinstance(entries, list):
                return {str(m.id): m for m in parse_maps(maps) if m.id}
            return {}
        if "id" in maps:  # 单个地图节点
            m = cast(MapDef, MapDef.from_entry(maps))
            return {str(m.id): m} if m.id else {}
        return {}
    if isinstance(maps, (list, tuple)):
        out: Dict[str, MapDef] = {}
        for e in maps:
            if isinstance(e, MapDef):
                m = e
            elif isinstance(e, Mapping):
                m = cast(MapDef, MapDef.from_entry(e))
            else:
                continue
            if m.id:
                out[str(m.id)] = m
        return out
    return {}


def _dungeons_index(dungeons: object, player_ctx: Optional[dict]) -> Dict[str, str]:
    """dungeons 入参归一 → {dungeon_id: name}（入口名缺省回退用，2a1c §1.2）。

    接受：modules 容器（{"dungeons": [...]}）/ 条目 dict 列表 / 单个条目 / None。
    """
    src = dungeons if dungeons is not None else (
        player_ctx.get("dungeons") if isinstance(player_ctx, Mapping) else None)
    entries: List[Mapping[str, object]] = []
    if isinstance(src, Mapping):
        if "dungeons" in src:
            v = src.get("dungeons")
            if isinstance(v, list):
                entries = [e for e in v if isinstance(e, Mapping)]
        elif "id" in src:
            entries = [src]
    elif isinstance(src, (list, tuple)):
        entries = [e for e in src if isinstance(e, Mapping)]
    out: Dict[str, str] = {}
    for e in entries:
        did = e.get("id")
        name = e.get("name")
        if isinstance(did, str) and did:
            out[did] = name if isinstance(name, str) and name else did
    return out


def _current_map_id(player_ctx: Mapping[str, Any]) -> Optional[str]:
    """当前地图 ID：ctx["map_id"]（会话上下文）→ 兜底 ctx["player"]["map_id"]。

    M7 部署接线：位置存储于 persistent_state["location"] / ctx["location"]，
    movement 侧统一兜底读取（R14 通道行走消费当前图）。
    """
    cur = player_ctx.get("map_id")
    if isinstance(cur, str) and cur:
        return cur
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        pcur = player.get("map_id")
        if isinstance(pcur, str) and pcur:
            return pcur
    loc = player_ctx.get("location")
    if isinstance(loc, str) and loc:
        return loc
    ps = player_ctx.get("persistent_state")
    if isinstance(ps, Mapping):
        ploc = ps.get("location")
        if isinstance(ploc, str) and ploc:
            return ploc
    return None


def _persistent_state_of(player_ctx: Mapping[str, Any]) -> Optional[MutableMapping[str, Any]]:
    """persistent_state 可变容器定位（对齐 investigate_commands._persistent_state_of）。

    读序：ctx["persistent_state"] → ctx["player"]["persistent_state"]（dict 形态）→
    ctx["player"].persistent_state（Player dataclass 属性）→ ctx 自身（裸 ctx 兜底）。

    Player 是 frozen dataclass 且无 map_id 字段——位置落点在 persistent_state["location"]
    （可变 dict 子结构，就地改 = 改 player → 落档保留，对齐 currencies/title_state 挂回方案）。
    """
    if not isinstance(player_ctx, Mapping):
        return None
    ps = player_ctx.get("persistent_state")
    if isinstance(ps, MutableMapping):
        return ps
    player = player_ctx.get("player")
    if isinstance(player, Mapping):
        ps2 = player.get("persistent_state")
        if isinstance(ps2, MutableMapping):
            return ps2
    # Player dataclass（frozen）：persistent_state 为可变 dict 属性，就地改可落档
    ps3 = getattr(player, "persistent_state", None)
    if isinstance(ps3, MutableMapping):
        return ps3
    if isinstance(player_ctx, MutableMapping):
        return player_ctx
    return None


def _current_entrances(index: Dict[str, MapDef], map_id: Optional[str]) -> Tuple[Mapping[str, object], ...]:
    """当前地图节点的副本入口列表（2a1c §1.1：世界图节点挂载；空 = 非入口节点）。"""
    if not map_id:
        return ()
    md = index.get(map_id)
    return md.dungeon_entrances if md is not None else ()


def _hidden_ok(condition: object, conditions: Optional[Callable[[Mapping[str, object], dict], bool]],
               ctx: dict) -> bool:
    """M05 隐藏通道条件门（2a1b R7-R9 / 契约 §2.4 hidden_ok）。

    conditions callable 注入；未注入 / 条件缺失 / 求值抛错 → False（不可走，
    fail-safe，2a1d LC-D「求值失败默认不满足」）。
    调用形态双兼容：先单参 conditions(cond)（对齐路J map_graph ctx 契约：
    callable(cond)->bool），TypeError（形参不匹配，函数体未执行）→ 回退双参
    conditions(cond, ctx)（本路注入形态，供玩家进度类条件如 R9 子任务解锁取值）。
    """
    cond = condition if isinstance(condition, Mapping) else None
    if cond is None or not callable(conditions):
        return False
    try:
        # 单参形态（路J 契约）；形参不匹配 → TypeError（函数体未执行）→ 回退双参
        single = cast(Callable[[Mapping[str, object]], bool], conditions)
        return bool(single(cond))
    except TypeError:
        try:
            double = cast(Callable[[Mapping[str, object], dict], bool], conditions)  # type: ignore[redundant-cast]
            return bool(double(cond, ctx))
        except Exception:
            return False
    except Exception:
        return False


def _maps_list(maps_src: object, index: Dict[str, MapDef]) -> list:
    """路J map_graph ctx 契约：ctx["maps"] 须为 list（其 _map_index 仅收 list）。

    原样是 list/tuple → 原样透传（raw dict 形态，lore 可读）；容器（modules）/
    单节点/None → 用归一索引值（MapDef 对象，_entry_id/_entry_exits 兼容）重建。
    """
    if isinstance(maps_src, (list, tuple)):
        return list(maps_src)
    return list(index.values())


def _exit_lore(index: Dict[str, MapDef], from_map_id: Optional[str], to_map_id: str) -> Optional[str]:
    """通道介绍文本（契约 §2.2「lore：通道介绍文本」，挂 exits.<方向> 上）。

    从旧图 exits 中找 to == 目标图的通道带回 lore；无 → None。
    """
    if not from_map_id:
        return None
    md = index.get(from_map_id)
    if md is None:
        return None
    raw_exits = md.raw.get("exits")
    if not isinstance(raw_exits, Mapping):
        return None
    for v in raw_exits.values():
        if isinstance(v, Mapping) and v.get("to") == to_map_id:
            lore = v.get("lore")
            if isinstance(lore, str) and lore:
                return lore
    return None


# =====================================================================================
# 行走判定（契约 §2.4：map_graph.can_move —— 路J 落盘优先，未落盘本地契约实现兜底）
# =====================================================================================
def _can_move(map_id: str, direction: str, ctx: dict) -> dict:
    """调 core/map_graph.can_move(map_id, direction, ctx)（契约 §2.4）。

    路J（批次3 同步）未落盘 → 本地契约实现 _contract_can_move 兜底；返回形态统一：
    MoveResult = {ok, to, mode, hidden_ok, blocked_reason?}。ctx 约定键：
    maps（地图源）/ conditions（条件求值 callable）——收口对齐。
    """
    try:
        from qbot_rpg.content.map_graph import can_move  # 路J：批次3 同步落盘
    except Exception:
        return _contract_can_move(map_id, direction, ctx)
    res = can_move(map_id, direction, ctx)
    if isinstance(res, Mapping) and "ok" in res:
        return res
    return {"ok": False, "to": None, "mode": None, "hidden_ok": False,
            "blocked_reason": _REASON_BLOCKED}


def _contract_can_move(map_id: str, direction: str, ctx: dict) -> dict:
    """契约 §2.4 本地实现（map_graph 未落盘兜底，收口时对齐路J）。

    双向直接可走；单向（当前图该方向即前向）可走、反方向在目标图侧自然无通道；
    hidden 条件经 ctx["conditions"] 注入求值，未满足 → 拦截「此处无通道」。
    """
    index = _maps_index(ctx.get("maps"))
    md = index.get(map_id)
    if md is None:
        return {"ok": False, "to": None, "mode": None, "hidden_ok": False,
                "blocked_reason": "找不到地图"}
    ex = md.exit(direction)
    if ex is None or not ex.to:
        return {"ok": False, "to": None, "mode": None, "hidden_ok": False,
                "blocked_reason": _REASON_NO_EXIT}
    mode = ex.mode if ex.mode in ("bidirectional", "one_way", "hidden") else "bidirectional"
    if mode == "hidden":
        if not _hidden_ok(ex.condition, ctx.get("conditions"), ctx):
            return {"ok": False, "to": None, "mode": mode, "hidden_ok": False,
                    "blocked_reason": _REASON_HIDDEN}
        return {"ok": True, "to": ex.to, "mode": mode, "hidden_ok": True}
    return {"ok": True, "to": ex.to, "mode": mode, "hidden_ok": True}


# =====================================================================================
# 对外接口
# =====================================================================================
def resolve_move(player_ctx: dict, direction: str,
                 maps: Optional[object] = None,
                 conditions: Optional[Callable[[Mapping[str, object], dict], bool]] = None) -> dict:
    """/进入 <方向> 通道行走（M05 隐藏通道 + M06 接线；2a1b R11/R12、2a1c R15/R18/R20）。

    读玩家当前地图（ctx["map_id"]）exits 对应方向 → 调 map_graph.can_move（隐藏通道
    条件由 conditions callable 注入：未注入/未满足 = 不可走「此处无通道」）→ 成功则
    经 move_to_map 钩子更新位置（map_weather_seen 记录 + R22 双钩子）。

    返回：
      成功 {"ok": True, "to", "name", "desc"?, "lore"?}（新图信息供指令层拼文案）
      失败 {"ok": False, "reason"}（不改变 ctx；方向非法 / 死路 / hidden 未满足 / 单向反向）
    """
    raw_dir = "" if direction is None else str(direction).strip().lower()
    d = DIRECTION_ALIASES.get(raw_dir)
    if d is None:
        return {"ok": False, "reason": f"『{raw_dir}』不是方向（上/下/左/右），也没有叫这个名字的入口"}
    maps_src = maps if maps is not None else player_ctx.get("maps")
    index = _maps_index(maps_src)
    cur = _current_map_id(player_ctx)
    if cur is None:
        return {"ok": False, "reason": "当前地图未知"}
    md = index.get(cur)
    if md is None:
        return {"ok": False, "reason": "找不到当前地图"}
    ex = md.exit(d)
    if ex is None or not ex.to:
        return {"ok": False, "reason": _REASON_NO_EXIT}
    if ex.mode == "hidden":
        # M05 隐藏通道：条件门本路判定（conditions 注入；未注入/未满足/抛错 → 不可走）
        if not _hidden_ok(ex.condition, conditions, player_ctx):
            return {"ok": False, "reason": _REASON_HIDDEN}
        result: dict = {"ok": True, "to": ex.to, "mode": "hidden", "hidden_ok": True}
    else:
        gctx = dict(player_ctx)
        gctx["maps"] = _maps_list(maps_src, index)   # 路J 契约：maps 须为 list
        gctx["conditions"] = conditions
        result = _can_move(cur, d, gctx)
        if not result.get("ok"):
            return {"ok": False, "reason": result.get("blocked_reason") or _REASON_BLOCKED}
    moved = move_to_map(player_ctx, result["to"], maps=maps_src)
    return {"ok": True, "to": result["to"],
            "name": moved.get("name"), "desc": moved.get("desc"), "lore": moved.get("lore")}


def move_to_map(player_ctx: dict, map_id: str, maps: Optional[object] = None) -> dict:
    """地图切换钩子（2a1b R13 位置变更 / R22 双钩子 / IF11 map_weather_seen）。

    1. R22 离开钩子（ctx["move_hooks"]["on_leave"](old_map_id, ctx)——批次 4 刷怪接线【工程补白】）；
    2. 更新玩家位置：ctx["player"]["map_id"] = map_id（原地改），并同步 ctx["map_id"]；
    3. 记录 map_weather_seen：world_time_persist.mark_map_seen（惰性增长，
       ctx["time_state"] 落点；存储层 M4 路3 A4 接线【工程补白】）；
    4. R22 进入钩子（ctx["move_hooks"]["on_enter"](new_map_id, ctx)）；
    5. 返回新图信息 {"ok", "map_id", "name", "desc"?, "lore"?}（供指令层拼文案）。

    零 IO 纯数据：只改入参 ctx 的 player/map_id/time_state 三个键，不触任何存储。
    """
    maps_src = maps if maps is not None else player_ctx.get("maps")
    index = _maps_index(maps_src)
    old_map = _current_map_id(player_ctx)
    target = "" if map_id is None else str(map_id)

    raw_hooks = player_ctx.get("move_hooks")
    hooks = raw_hooks if isinstance(raw_hooks, Mapping) else {}
    on_leave = hooks.get("on_leave")
    if callable(on_leave):
        on_leave(old_map, player_ctx)  # 【工程补白】R22 离开钩子：时段边界怪物移除/补刷 → 批次 4

    player = player_ctx.get("player")
    # P1-5 修复（QA 黑盒·位置不持久）：Player 是 frozen dataclass 且无 map_id 字段，
    # 位置真落点位 = persistent_state["location"]（可变 dict 子结构，就地改可落档）。
    # 旧契约写 player["map_id"] 是死键（Player 无此字段），且 cmd_enter 传 dict(player)
    # 副本时写副本直接丢写回——统一改走 _persistent_state_of 定位的真实 ps。
    ps = _persistent_state_of(player_ctx)
    if ps is not None:
        ps["location"] = target  # 玩家位置持久落点（重启后仍保持）
    if isinstance(player, MutableMapping):
        player["map_id"] = target  # dict 形态（旧测试/纯 dict ctx）兼容：原地改
    player_ctx["map_id"] = target  # 同步会话上下文当前图（_current_map_id 兜底读序第 1 位）
    player_ctx["location"] = target  # 同步会话上下文位置（/位置 渲染读 ctx["location"]）

    ts = player_ctx.get("time_state")
    # mark_map_seen 签名收 dict，但防御性接受 None（非 dict 按默认规整）——此处显式 cast
    ts_arg = dict(ts) if isinstance(ts, Mapping) else None
    player_ctx["time_state"] = mark_map_seen(cast(dict, ts_arg), target)

    on_enter = hooks.get("on_enter")
    if callable(on_enter):
        on_enter(target, player_ctx)  # 【工程补白】R22 进入钩子：天气池刷新等 → 批次 4

    md = index.get(target)
    lore = _exit_lore(index, old_map, target)
    return {"ok": True, "map_id": target,
            "name": md.name if md is not None else None,
            "desc": md.desc if md is not None else None,
            "lore": lore}


def enter_context_route(player_ctx: dict, arg: Optional[str],
                        maps: Optional[object] = None,
                        dungeons: Optional[object] = None) -> dict:
    """/进入 参数路由（2a1c §3 R14-R20：方向字面量 → 纯数字序号 → 名称匹配）。

    方向（上/下/左/右 + 别名 北/南/东/西 + 英文键）→ resolve_move 走通道；
    纯数字序号（R16 不带 *；1 起始）→ 当前图入口列表序号；
    名称（R17 入口名 → 副本名逐级）→ 当前图 dungeon_entrances 匹配；
    命中入口 → 返回进副本信号：{"ok", "type": "dungeon", "dungeon_id", "name"}
    —— 副本入场校验/副本身份激活由**批次 5** 实装接线【工程补白】，本路仅登记待接线。
    未命中 → {"ok": False, "reason": "没有这个入口/方向"}（或「此处没有副本入口」）。
    """
    maps_src = maps if maps is not None else player_ctx.get("maps")
    index = _maps_index(maps_src)
    cur = _current_map_id(player_ctx)
    arg_s = "" if arg is None else str(arg).strip()

    if not arg_s:  # 便捷指令无参（R19 P1 预留，2a1c TC-23）
        return {"ok": False, "reason": _REASON_NO_ARG}

    # 1. 方向字面量（R14 优先级 1）→ 通道行走
    if arg_s in DIRECTION_ALIASES:
        res = resolve_move(player_ctx, arg_s, maps=maps_src)
        return {"type": "move", **res}

    # 2. 纯数字序号（R14 优先级 2 / R16）→ 当前图入口列表（1 起始）
    # M3 审查 P1-3 修复：isdigit() 对 ¹/② 等 Unicode 数字返回 True 但 int() 抛 ValueError
    # → try/except 拦截，防用户输入 /进入 ² 崩溃（指令路由是用户直触面）
    if arg_s.isascii() and arg_s.isdigit():
        entries = _current_entrances(index, cur)
        if not entries:
            return {"ok": False, "reason": _REASON_NO_ENTRANCE}
        try:
            idx = int(arg_s)
        except ValueError:
            return {"ok": False, "reason": _REASON_INVALID_ENTRANCE}
        if 1 <= idx <= len(entries):
            return _dungeon_signal(entries[idx - 1], dungeons, player_ctx)
        return {"ok": False, "reason": f"序号 {arg_s} 无效/不存在"}

    # 3. 保留字符 *（数量语义，/进入 无数量位 → 拒绝，2a1c TC-25）
    if "*" in arg_s:
        return {"ok": False, "reason": f"/进入 不支持数量 *：{arg_s} 无法解析"}

    # 4. 名称匹配（R14 优先级 3 / R17：入口名 → 副本名；地图名移动不在本路 scope【工程补白】）
    entries = _current_entrances(index, cur)
    if not entries:
        return {"ok": False, "reason": _REASON_NO_ENTRANCE}
    hit = _match_entrance(entries, arg_s, dungeons, player_ctx)
    if hit is not None:
        return _dungeon_signal(hit, dungeons, player_ctx)
    return {"ok": False, "reason": _REASON_NOT_FOUND}


def _match_entrance(entries: Tuple[Mapping[str, object], ...], arg: str,
                    dungeons: object, player_ctx: dict) -> Optional[Mapping[str, object]]:
    """入口匹配（2a1c R17 名称逐级）：入口名 → 入口缺省名（副本名）→ 副本 id。"""
    dindex = _dungeons_index(dungeons, player_ctx)
    for ent in entries:
        name = ent.get("name")
        if isinstance(name, str) and name == arg:
            return ent
    for ent in entries:
        did = ent.get("dungeon")
        if isinstance(did, str):
            fallback = dindex.get(did, did)
            if fallback == arg:
                return ent
            if did == arg:  # 副本 id 直配
                return ent
    return None


def _dungeon_signal(entrance: Mapping[str, object], dungeons: object,
                    player_ctx: dict) -> dict:
    """进副本信号（结构化登记；入场校验/副本身份激活批次 5 接线【工程补白】）。"""
    did = entrance.get("dungeon")
    dungeon_id = did if isinstance(did, str) and did else None
    name = entrance.get("name")
    if not isinstance(name, str) or not name:
        dindex = _dungeons_index(dungeons, player_ctx)
        name = dindex.get(str(dungeon_id)) if dungeon_id else None
        if not name:
            name = dungeon_id
    return {
        "ok": True,
        "type": "dungeon",
        "dungeon_id": dungeon_id,
        "name": name,
        "note": "副本进入由批次 5 接线（入场校验/外部锚点/副本身份激活/落位 safe_zone），本路仅登记入口命中",
    }