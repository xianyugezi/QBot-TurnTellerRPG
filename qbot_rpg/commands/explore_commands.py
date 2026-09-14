"""世界层指令壳（M5-09 探索结果合并 1 条 · 铁律 2 / 开发规则 L515）。

指令：
- /进入 <方向|序号|名称>：通道行走 / 副本入口进入（引擎 enter_context_route / resolve_move）→ 结果 1 条
- /休息：副本安全区休息（引擎 rest_in_dungeon）→ 结果 1 条
- /采集：登记 DELAYED（采集引擎未接线——M3 地图批次未产出独立采集引擎，
  采集点在地图/副本探索流程内处理；M5-09 壳层不阻断，后续批次接线）

渲染纪律：单次操作最多 1-2 条消息（本壳一律 1 条返回文本）；emoji 仅 ✅/❌ + 排版符号
（| → × / 「」【】）；前缀首行注入由装配层（M5-01 prefix_wiring）统一处理，本壳不拼前缀。

/进入 move（通道行走）结果按 CakeGame 模板 28 风格丰富（用户 2026-08-27 拍板）：
  ✅ 你来到了「name」+ 地图介绍 + 活动怪物（序号.名称×数量）+ 通道（上/下/左/右：目标地图名）
  + Tip（发送'位置'查询当前位置）；区域角色（NPC）行省略——maps 节点无 npcs 字段
  （登记 DELAYED，NPC 数据源待 M6 数据框架）。

依据：docs/m5_shared_contract.md §三 / 铁律 2 / 框架 §7.3 L1279-1281（/采集 /进入）/ §7.4。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Tuple

from .router import CommandSpec
from .sender import format_tpl12
from qbot_rpg.core.templates import tpl_of  # 消息模板配置化（2026-08-31 用户拍板）

# 指令名（对齐 parsers 白名单：进入/休息 已在 DEFAULT_WHITELIST）
ENTER_CMD = "进入"
REST_CMD = "休息"
POSITION_CMD = "位置"  # M9 实机反馈修复（2026-08-30）：帮助/Tip 引导「位置」但从未实现 → 静默空回
MAP_CMD = "地图"  # 实机反馈修复（2026-08-30）：白名单引导「地图」但从未实现 → 静默空回
MONSTER_CMD = "怪物"  # 2026-09-06：stub 转真——当前地图活动怪物列表
TIME_CMD = "时间"  # 2026-09-06：游戏内时间（ctx season/period，引擎未启用 → 提示）
WEATHER_CMD = "天气"  # 2026-09-06：当前天气（ctx weather，未启用 → 提示）

__all__ = [
    "ENTER_CMD", "REST_CMD", "MONSTER_CMD",
    "cmd_enter", "cmd_rest", "cmd_monster", "register_explore_commands",
]


def _fragment(parsed: Any) -> str:
    """原始指令片段（错误回显，对齐 basic_commands._fragment）。"""
    return str(getattr(parsed, "raw", None) or getattr(parsed, "text", "") or "").strip()


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：registered is False → 拦截文案（缺省视为已注册，对齐 basic）。

    模板 key：explore_register_gate（内容包可覆盖同 key）。
    """
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, "explore_register_gate")
    return None


# =====================================================================================
# /进入 move（通道行走）丰富渲染 —— CakeGame 模板 28 风格（用户 2026-08-27 拍板）：
#   ✅ 你来到了「name」+ 地图介绍 + 活动怪物（序号.名称×数量）+ 通道（上/下/左/右：目标名）+ Tip
# 区域角色（NPC）行省略：maps 节点无 npcs 字段——登记 DELAYED（NPC 数据源待 M6 数据框架）
# =====================================================================================

# 通道方向 → 中文标签（对齐 movement.DIRECTION_ALIASES：up=上/down=下/left=左/right=右）
_EXIT_DIR_LABELS: Dict[str, str] = {"up": "上", "down": "下", "left": "左", "right": "右"}
_EXIT_DIR_ORDER: Tuple[str, ...] = ("up", "down", "left", "right")

# 活动怪物展示上限（铁律 11：单条消息 ≤16 行折叠上限；超 5 只截断折叠）
_MONSTER_SHOW_LIMIT = 5


def _maps_index_for(ctx: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """maps 索引（同 resolve_move._maps_index 口径：ctx["maps"]；缺失/引擎未加载 → 空表）。"""
    if not ctx:
        return {}
    try:
        from qbot_rpg.world.movement import _maps_index  # noqa: PLC0415
    except ImportError:
        return {}
    index = _maps_index(ctx.get("maps"))
    return dict(index) if isinstance(index, Mapping) else {}


def _known_maps_for(ctx: Optional[Mapping[str, Any]], index: Mapping[str, Any]) -> set:
    """可传送地图集（2026-09-06 zerc 反馈·三次修订：默认有怪=隐藏图）：
    default_map（驿站）+ camp_name 营地标记图 + 无怪安全图。规则 = 有怪物
    分布的地图默认隐藏（玩家不可直接传送进野外——探索靠通道行走）；
    营地（camp_name）与安全图（无怪）常显。裸 ctx（纯函数测试）→ 全量零破坏。"""
    known: set = set()
    if not ctx:
        return known
    if "discovered_maps" not in ctx and "player" not in ctx and "settings" not in ctx:
        return set(index.keys())
    dm = ctx.get("settings")
    if isinstance(dm, Mapping):
        _dmap = dm.get("default_map")
        if isinstance(_dmap, str) and _dmap:
            known.add(_dmap)
    for mid in list(index.keys()):
        entry = index[mid]
        if entry is None:
            continue
        raw = getattr(entry, "raw", None) if not isinstance(entry, Mapping) else entry
        raw = raw if isinstance(raw, Mapping) else {}
        # 营地标记 → 常显（camp_name 纯配置字段，raw 透传）
        cn = raw.get("camp_name")
        if isinstance(cn, str) and cn:
            known.add(mid)
            continue
        # 无怪安全图 → 常显（monsters 空；MapDef.spawn property / dict monsters 键）
        mobs = raw.get("monsters")
        if mobs is None and not isinstance(entry, Mapping):
            try:
                mobs = entry.spawn  # MapDef property（tuple）
            except Exception:  # noqa: BLE001
                mobs = None
        if not mobs:
            known.add(mid)
    return {m for m in known if m in index}


def _monster_names(ctx: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """enemy id → 怪物名 映射（ctx["monsters"] 优先，兜底 ctx["enemies"]；拿不到 → 空表）。

    monsters/enemies 条目形态兼容：{id: {name, ...}}（映射）或 [{id, name, ...}, ...]（列表）。
    """
    if not ctx:
        return {}
    src = ctx.get("monsters")
    if src is None:
        src = ctx.get("enemies")
    out: Dict[str, str] = {}
    if isinstance(src, Mapping):
        for eid, entry in src.items():
            if isinstance(entry, Mapping):
                nm = entry.get("name")
                if isinstance(nm, str) and nm:
                    out[str(eid)] = nm
    elif isinstance(src, (list, tuple)):
        for e in src:
            if isinstance(e, Mapping):
                eid = e.get("id")
                nm = e.get("name")
                if isinstance(eid, str) and eid and isinstance(nm, str) and nm:
                    out[eid] = nm
    return out


def _map_name(index: Mapping[str, Any], map_id: str) -> str:
    """目标地图 id → 地图名（index 项 MapDef 或 raw dict 兼容；未知 → id 兜底）。"""
    entry = index.get(map_id)
    nm = entry.get("name") if isinstance(entry, Mapping) else getattr(entry, "name", None)
    return nm if isinstance(nm, str) and nm else map_id


def _monster_line(ctx: Optional[Mapping[str, Any]], target: Any) -> Optional[str]:
    """活动怪物行块：单只 `活动怪物：1.岩皮鼬×3`；多只（≥2）首行「活动怪物：」独占、
    每条目独占一行（批1·路C 拆行防超宽；每行 ≤14 全角）。

    数据源 = maps 目标图 monsters 行（{enemy, count, ...}）；enemy id → 怪物名经
    ctx["monsters"]/ctx["enemies"] 解析，拿不到直接显示 enemy id；>5 只截断折叠（铁律 11）。
    无怪物 → None（行省略）。模板 key：explore_monster_row / explore_monster_line /
    explore_monster_overflow（内容包可覆盖同 key）。
    """
    if target is None:
        return None
    if isinstance(target, Mapping):
        raw = target.get("monsters")
        rows = tuple(e for e in raw if isinstance(e, Mapping)) if isinstance(raw, list) else ()
    else:
        rows = target.spawn or ()
    if not rows:
        return None
    names = _monster_names(ctx)
    parts: List[str] = []
    for i, row in enumerate(rows[:_MONSTER_SHOW_LIMIT], 1):
        eid = row.get("enemy")
        nm = names.get(str(eid)) or (str(eid) if eid else "?")
        cnt = row.get("count", 1)
        try:
            cnt = int(cnt)
        except (TypeError, ValueError):
            cnt = 1
        parts.append(tpl_of(ctx, "explore_monster_row", {"i": i, "nm": nm, "cnt": cnt}))
    # 批1·路C（2026-09-12）：≥2 只拆行——首行「活动怪物：」独占、每条目独占一行
    # （旧「空格 join」单行易超 14 全角）；单只怪物同行（`活动怪物：1.xxx×n`）。
    items = "\n" + "\n".join(parts) if len(parts) >= 2 else (parts[0] if parts else "")
    line = tpl_of(ctx, "explore_monster_line", {"items": items})
    if len(rows) > _MONSTER_SHOW_LIMIT:
        line += tpl_of(ctx, "explore_monster_overflow")
    return line


def _channel_lines(ctx: Optional[Mapping[str, Any]],
                   index: Mapping[str, Any], target: Any) -> List[str]:
    """通道行：`上：{目标地图名}`…（仅渲染已配置方向；缺省方向=死路，行省略）。

    模板 key：explore_channel_row（内容包可覆盖同 key）。
    """
    lines: List[str] = []
    if target is None:
        return lines
    if isinstance(target, Mapping):
        raw = target.get("exits")
        exits_map = raw if isinstance(raw, Mapping) else {}
        for d in _EXIT_DIR_ORDER:
            ex = exits_map.get(d)
            if not isinstance(ex, Mapping) or not ex.get("to"):
                continue
            lines.append(tpl_of(ctx, "explore_channel_row", {
                "dir": _EXIT_DIR_LABELS.get(d, d),
                "name": _map_name(index, str(ex.get("to"))),
            }))
        return lines
    for d in _EXIT_DIR_ORDER:
        ex = target.exit(d)
        if ex is None or not ex.to:
            continue
        lines.append(tpl_of(ctx, "explore_channel_row", {
            "dir": _EXIT_DIR_LABELS.get(d, d),
            "name": _map_name(index, str(ex.to)),
        }))
    return lines


def _render_enter(result: Mapping[str, Any],
                  ctx: Optional[Mapping[str, Any]] = None) -> str:
    """/进入 结果 → 1 条消息文本（move / dungeon / 失败）。

    move（通道行走）按 CakeGame 模板 28 风格：✅ 你来到了「name」+ 地图介绍 + 活动怪物
    （序号.名称×数量）+ 通道（上/下/左/右：目标地图名）+ Tip；区域角色（NPC）行省略
    （maps 节点无 npcs 字段——登记 DELAYED，NPC 数据源待 M6 数据框架）。
    模板 key：explore_enter_fail / explore_enter_dungeon / explore_enter_ok /
    explore_map_desc / explore_tip（内容包可覆盖同 key）。
    """
    if not result.get("ok"):
        reason = result.get("reason") or tpl_of(ctx, "explore_enter_fail_reason")
        return tpl_of(ctx, "explore_enter_fail", {"reason": reason})
    kind = result.get("type")
    if kind == "dungeon":
        name = result.get("name") or result.get("dungeon_id") or ""
        return tpl_of(ctx, "explore_enter_dungeon", {"name": name})
    # move：通道行走 → 新地图信息（CakeGame 模板 28 风格丰富）
    name = result.get("name") or ""
    lines = [tpl_of(ctx, "explore_enter_ok", {"name": name})]
    desc = result.get("desc") or ""
    if desc:
        lines.append(tpl_of(ctx, "explore_map_desc", {"desc": desc}))
    lore = result.get("lore") or ""
    if lore:
        lines.append(str(lore))
    index = _maps_index_for(ctx)
    target = index.get(str(result.get("to"))) if result.get("to") else None
    mline = _monster_line(ctx, target)
    if mline:
        lines.append(mline)
    # 区域角色（NPC）行省略：maps 节点无 npcs 字段（登记 DELAYED，NPC 数据源待 M6 数据框架）
    lines.extend(_channel_lines(ctx, index, target))
    lines.append(tpl_of(ctx, "explore_tip"))
    return "\n".join(lines)


def _apply_rest_heal(ctx: Mapping[str, Any], result: Mapping[str, Any]) -> None:
    """P2-3 配套：营地休息恢复写回 ctx player（ctx 标量 + Player/dict 同步落档）。"""
    hp = int(result.get("hp", 0) or 0)
    mp = int(result.get("mp", 0) or 0)
    if isinstance(ctx, MutableMapping):
        ctx["hp"] = hp
        ctx["mp"] = mp
    p = ctx.get("player")
    if p is None:
        return
    try:
        import dataclasses  # noqa: PLC0415
        from qbot_rpg.data import Player  # noqa: PLC0415

        if isinstance(p, Player):
            _nb = dataclasses.replace(p, hp=hp, mp=mp)
            if isinstance(ctx, MutableMapping):
                ctx["player"] = _nb
            return
    except Exception:  # noqa: BLE001 - Player 形态探测失败回落 dict
        pass
    if isinstance(p, MutableMapping):
        p["hp"] = hp
        p["mp"] = mp


def _render_rest(result: Mapping[str, Any], ctx: Optional[Mapping[str, Any]] = None) -> str:
    """/休息 结果 → 1 条消息文本（成功 / 拒绝）。

    模板 key：explore_rest_fail / explore_rest_ok / explore_rest_cooldown（内容包可覆盖）。
    """
    if not result.get("rested"):
        msg = result.get("message") or result.get("reason") \
            or tpl_of(ctx, "explore_rest_fail_reason")
        return tpl_of(ctx, "explore_rest_fail", {"reason": msg})
    hp = int(result.get("hp_restored", 0) or 0)
    mp = int(result.get("mp_restored", 0) or 0)
    cr = int(result.get("cooldown_reduction", 0) or 0)
    line = tpl_of(ctx, "explore_rest_ok", {"hp": hp, "mp": mp})
    if cr:
        # 批10·路A：冷却行独立成行（新规范「少｜多换行」；模板自身不含前导换行）
        line += "\n" + tpl_of(ctx, "explore_rest_cooldown", {"cr": cr})
    return line


def _player_ctx(ctx: Mapping[str, Any]) -> Mapping[str, Any]:
    """玩家上下文：ctx[\"player\"] 优先（引擎读 map_id/hp/mp 等），否则 ctx 本身。"""
    player = ctx.get("player")
    return player if isinstance(player, Mapping) else ctx


def cmd_map(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/地图 非隐藏地图列表（定稿 L1273：序号=进入参数；2026-08-30 实机反馈：
    白名单引导但从未实现 → 静默空回）。复用 maps index 渲染地图+通道。"""
    g = _gate(ctx)
    if g is not None:
        return g
    index = _maps_index_for(ctx)
    if not index:
        return tpl_of(ctx, "explore_map_empty")
    # 2026-09-06 实机反馈（zerc）：只显示已发现区域（discovered_maps ∪ 城镇），
    # 野外未到达不列（原全量列表泄露全图）。发现记录由 cmd_enter 移动成功写。
    known = _known_maps_for(ctx, index)
    lines = [tpl_of(ctx, "explore_map_title")]
    _shown = 0
    for mid in list(index.keys()):
        entry = index[mid]
        if not entry:
            continue
        if mid not in known:
            continue  # 未发现区域隐藏（D-05 不提示原则）
        _shown += 1
        name = entry.get("name") if isinstance(entry, Mapping) else getattr(entry, "name", None) or mid
        lines.append(tpl_of(ctx, "explore_map_row", {"idx": _shown, "name": name}))
    return "\n".join(lines) + "\n" + tpl_of(ctx, "explore_map_tail")



def cmd_monster(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """怪物：当前地图活动怪物列表（2026-09-06 stub 转真）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    loc = str(ctx.get("location") or "")
    if not loc:
        return tpl_of(ctx, "explore_monster_empty")
    maps = ctx.get("maps")
    target = None
    if isinstance(maps, list):
        for m in maps:
            if isinstance(m, Mapping) and (str(m.get("id") or "") == loc
                                           or str(m.get("name") or "") == loc):
                target = m
                break
    elif isinstance(maps, Mapping):
        target = maps.get(loc) or maps.get(str(ctx.get("location_name") or ""))
    line = _monster_line(ctx, target) if target is not None else None
    if not line:
        return tpl_of(ctx, "explore_monster_empty")
    # 头部：当前地图名（maps 表 name 优先）
    loc_name = str(ctx.get("location_name") or loc)
    if isinstance(target, Mapping):
        loc_name = str(target.get("name") or loc_name)
    head = tpl_of(ctx, "explore_monster_header", {"loc": loc_name})
    return f"{head}\n{line}"



def cmd_time(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """时间：当前游戏季节/时段（2026-09-06；中文名经 time_query 映射，缺失 → 未启用提示）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    season = str(ctx.get("season") or "--")
    period = str(ctx.get("period") or "--")
    if season == "--" and period == "--":
        return tpl_of(ctx, "worldtime_disabled")
    # 中文名（time_query 映射表；未知键回退原文）
    try:
        from qbot_rpg.core.time_query import PERIOD_NAMES, SEASON_NAMES  # noqa: PLC0415
        season = str(SEASON_NAMES.get(season, season))
        period = str(PERIOD_NAMES.get(period, period))
    except Exception:
        pass
    return tpl_of(ctx, "worldtime_now", {"season": season, "period": period})


def cmd_weather(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """天气：当前地图天气（2026-09-06；中文名经 time_query 映射，缺失 → 未启用提示）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    w = str(ctx.get("weather") or "--")
    if w == "--":
        return tpl_of(ctx, "worldtime_disabled")
    try:
        from qbot_rpg.core.time_query import weather_name  # noqa: PLC0415
        w = str(weather_name(w) or w)
    except Exception:
        pass
    loc_name = str(ctx.get("location_name") or ctx.get("location") or "当前地图")
    # 地图中文名（maps 表 name）
    maps = ctx.get("maps")
    loc = str(ctx.get("location") or "")
    if isinstance(maps, list):
        for m in maps:
            if isinstance(m, Mapping) and str(m.get("id") or "") == loc:
                loc_name = str(m.get("name") or loc_name)
                break
    return tpl_of(ctx, "weather_now", {"loc": loc_name, "weather": w})


def cmd_position(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/位置 查询当前地点（M9 实机反馈修复 2026-08-30：帮助/Tip 引导但从未实现 → 静默空回）。

    复用 _render_enter 渲染：以当前 location 构造 move 结果（name/desc/lore/to=当前
    地图），输出地图介绍 + 活动怪物 + 通道（上/下/左/右）+ Tip。未进图/未知 → 引导 /进入。
    """
    g = _gate(ctx)
    if g is not None:
        return g
    loc = ctx.get("location")
    index = _maps_index_for(ctx)
    entry = index.get(str(loc)) if loc else None
    if entry is None:
        loc_text = str(loc) if loc else tpl_of(ctx, "explore_position_unknown_none")
        return tpl_of(ctx, "explore_position_unknown", {"loc": loc_text})
    if isinstance(entry, Mapping):
        name = entry.get("name") or str(loc)
        desc = entry.get("desc") or entry.get("description") or ""
        lore = entry.get("lore") or ""
    else:
        name = getattr(entry, "name", None) or str(loc)
        desc = getattr(entry, "desc", None) or ""
        lore = getattr(entry, "lore", None) or ""
    result = {
        "ok": True, "type": "move",
        "name": name, "desc": desc, "lore": lore, "to": loc,
    }
    return _render_enter(result, ctx)


def cmd_enter(parsed: Any, ctx: Mapping[str, Any]) -> Any:
    """/进入 <方向|序号|名称>：通道行走 / 副本入口 → 1 条结果消息。

    可能返回 dict（离开锁定地图解除战斗：带 _battle_persist release，对齐
    battle 组 send 收口）或 str（普通结果）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return tpl_of(ctx, "explore_enter_noarg")
    arg = str(args[0])
    try:
        from qbot_rpg.world.movement import enter_context_route, _persistent_state_of  # noqa: PLC0415
    except ImportError:
        return tpl_of(ctx, "explore_enter_not_wired")
    player = _player_ctx(ctx)
    # P1-5 修复（QA 黑盒·位置不持久）：不传一次性 dict(player) 副本——位置写在副本上
    # 直接丢写回（落档丢位置）。改为构造引擎上下文：persistent_state 挂真实引用
    # （Player frozen dataclass 可变子结构，move_to_map 就地改 ps["location"] 即落档），
    # 会话位置键同步（_current_map_id 读序：map_id → location → ps.location）。
    pctx = dict(player)
    pctx["persistent_state"] = _persistent_state_of(ctx) or {}
    # 会话位置键：ctx 显式键优先（生产注入 location）；缺省保留 dict(player) 原有 map_id
    for _k in ("map_id", "location"):
        _v = ctx.get(_k)
        if _v is not None:
            pctx[_k] = _v
    pctx["maps"] = ctx.get("maps")
    pctx["dungeons"] = ctx.get("dungeons")
    pctx["time_state"] = ctx.get("time_state")
    pctx["move_hooks"] = ctx.get("move_hooks")
    result = enter_context_route(
        pctx, arg,
        maps=ctx.get("maps"), dungeons=ctx.get("dungeons"),
    )
    if not isinstance(result, Mapping):
        return tpl_of(ctx, "explore_enter_engine_error")
    # 2026-08-31 实机反馈：/地图 按序号展示后，「进入 N」应支持世界地图序号传送。
    # 副本入口序号不命中（无入口/序号无效）且参数为纯数字时 → 按 _maps_index 序号
    # 取地图传送（对齐 cmd_map 的 enumerate 序号；地图传送走 move_to_map 钩子）。
    if not result.get("ok") and arg.isascii() and arg.isdigit():
        index = _maps_index_for(ctx)
        known = _known_maps_for(ctx, index)
        ordered = [m for m in list(index.keys()) if index.get(m) and m in known]
        try:
            map_idx = int(arg)
        except ValueError:
            map_idx = -1
        if 1 <= map_idx <= len(ordered):
            target = ordered[map_idx - 1]
            try:
                from qbot_rpg.world.movement import move_to_map  # noqa: PLC0415
                # P1-5 修复：同方向行走——复用共享 persistent_state 的 pctx（非 dict(player) 副本）
                moved = move_to_map(pctx, target, maps=ctx.get("maps"))
                if moved.get("ok"):
                    result = {"ok": True, "to": target,
                              "name": moved.get("name"),
                              "desc": moved.get("desc"), "lore": moved.get("lore")}
            except ImportError:
                pass
    # 2026-09-06 发现记录：移动/传送成功 → 目标图写 ctx discovered_maps（就地
    # 改 persistent_state 挂回 list → runner 落档）。/地图 过滤依赖此集合。
    if isinstance(result, Mapping) and result.get("ok"):
        _dst = result.get("to")
        _dm = ctx.get("discovered_maps")
        if isinstance(_dst, str) and _dst and isinstance(_dm, list) and _dst not in _dm:
            _dm.append(_dst)
    text = _render_enter(result, ctx)
    # M12.5 离开锁定地图解除战斗（2026-09-06 拍板）：通道行走/地图传送成功
    # （type=move 且目标 ≠ 当前地图）时，若玩家处于战斗（battle session 活跃）→
    # 释放战斗会话——怪物已不在身边，战斗自然脱离（对齐 /木桩 退出 release 收口）。
    _battle_release = _leave_battle_on_move(ctx, result, text)
    if _battle_release is not None:
        return _battle_release
    return text


def _leave_battle_on_move(ctx: Mapping[str, Any], result: Mapping[str, Any],
                          text: str) -> Optional[Dict[str, Any]]:
    """移动离开当前地图 → 若在战斗则释放会话。返回带 _battle_persist 的 dict 或 None。"""
    if not result.get("ok"):
        return None
    if result.get("type") == "dungeon":
        # 进副本：副本身份激活由批次 5 接线，不在此解除（副本内是另一套锁定语义）
        return None
    to_map = result.get("to")
    if not to_map:
        return None
    cur_map = ctx.get("map_id") or ctx.get("location")
    if cur_map and str(to_map) == str(cur_map):
        return None  # 未离开（理论上 move 必换图；防御）
    engine = ctx.get("battle_engine")
    if engine is None:
        return None  # 不在战斗
    qid = str(ctx.get("qid") or ctx.get("qq_id") or "")
    if not qid:
        return None
    msg = text + "\n" + tpl_of(ctx, "explore_leave_battle_ok")
    try:
        from qbot_rpg.commands.battle_commands import BattlePipeline  # noqa: PLC0415
        BattlePipeline.from_ctx(ctx).send(msg)
        return {"ok": True, "message": msg, "send": False,
                "_battle_persist": ("release", qid)}
    except Exception:  # noqa: BLE001 —— 无 sender/前缀装配缺键（轻量 ctx）→ 回落
        return {"ok": True, "message": msg, "send": False,
                "_battle_persist": ("release", qid)}


def cmd_rest(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/休息：副本安全区休息 → 1 条结果消息。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return tpl_of(ctx, "explore_rest_extra_arg")
    try:
        from qbot_rpg.world.rest import rest_at_camp, rest_in_dungeon  # noqa: PLC0415
    except ImportError:
        return tpl_of(ctx, "explore_rest_not_wired")
    session = ctx.get("dungeon_session")
    if session is None:
        # P2-3 配套（qa_report_20260907）：无副本会话 → 野图营地休息（camp_name
        # 标记图：驿站/各区营地免费休整至满）。原实现 session=None 直落 rest_in_
        # dungeon 报「不在安全区」——玩家在龙骨驿站（camp）发休息被拒且提示
        # 「回营地再休息」自相矛盾。营地休息恢复写回 ctx player（落档）。
        from qbot_rpg.world.rest import camp_map_of  # noqa: PLC0415

        _loc = str(ctx.get("location") or ctx.get("map_id") or "")
        _maps = ctx.get("maps")
        _camp = camp_map_of(_maps, _loc)
        if _camp is not None:
            result = rest_at_camp(
                _player_ctx(ctx),
                max_hp=ctx.get("max_hp"),
                max_mp=ctx.get("max_mp"),
            )
            _apply_rest_heal(ctx, result)
            return _render_rest(result, ctx)
        return tpl_of(ctx, "explore_rest_fail",
                      {"reason": "当前不在营地或副本安全区（驿站/营地可休息，或找驿站药婆疗伤）"})
    result = rest_in_dungeon(
        session, _player_ctx(ctx),
        cfg=ctx.get("rest_cfg"),
    )
    if not isinstance(result, Mapping):
        return tpl_of(ctx, "explore_rest_engine_error")
    return _render_rest(result, ctx)


def register_explore_commands(router: Any, *,
                              make_context: Optional[Callable[[Any], Mapping[str, Any]]] = None) -> Any:
    """把 /进入 /休息 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param make_context: ParsedCommand → 玩家 ctx dict（name/level/player/maps/dungeons/
        dungeon_session/rest_cfg 等，见本模块各渲染函数消费契约）。None 时 handler 调用
        抛 RuntimeError（【待接线】装配注入，对齐 basic_commands）。
    """
    def _ctx(parsed: Any) -> Mapping[str, Any]:
        if make_context is None:
            raise RuntimeError(
                "【待接线】explore_commands.register_explore_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(handler: Callable[..., str]) -> Callable[..., str]:
        def _h(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return handler(parsed, injected)
            return handler(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(ENTER_CMD, handler=_wrap(cmd_enter)))
    router.register(CommandSpec(REST_CMD, handler=_wrap(cmd_rest)))
    router.register(CommandSpec(POSITION_CMD, handler=_wrap(cmd_position)))
    router.register(CommandSpec(MAP_CMD, handler=_wrap(cmd_map)))
    router.register(CommandSpec(MONSTER_CMD, handler=_wrap(cmd_monster)))
    router.register(CommandSpec(TIME_CMD, handler=_wrap(cmd_time)))
    router.register(CommandSpec(WEATHER_CMD, handler=_wrap(cmd_weather)))
    return router
