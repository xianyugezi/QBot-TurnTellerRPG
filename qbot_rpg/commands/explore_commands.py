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

# 指令名（对齐 parsers 白名单：进入/休息 已在 DEFAULT_WHITELIST）
ENTER_CMD = "进入"
REST_CMD = "休息"
POSITION_CMD = "位置"  # M9 实机反馈修复（2026-08-30）：帮助/Tip 引导「位置」但从未实现 → 静默空回
MAP_CMD = "地图"  # 实机反馈修复（2026-08-30）：白名单引导「地图」但从未实现 → 静默空回

# RUL-08 注册门槛（对齐 basic_commands：未注册玩家使用游玩指令 → 统一拦截）
TPL_REGISTER_GATE = "❌ 请先 /注册 创建角色（/注册 名字 职业）"

__all__ = [
    "ENTER_CMD", "REST_CMD",
    "cmd_enter", "cmd_rest", "register_explore_commands",
]


def _fragment(parsed: Any) -> str:
    """原始指令片段（错误回显，对齐 basic_commands._fragment）。"""
    return str(getattr(parsed, "raw", None) or getattr(parsed, "text", "") or "").strip()


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """RUL-08 注册门槛：registered is False → 拦截文案（缺省视为已注册，对齐 basic）。"""
    if ctx.get("registered", True) is False:
        return TPL_REGISTER_GATE
    return None


# =====================================================================================
# /进入 move（通道行走）丰富渲染 —— CakeGame 模板 28 风格（用户 2026-08-27 拍板）：
#   ✅ 你来到了「name」+ 地图介绍 + 活动怪物（序号.名称×数量）+ 通道（上/下/左/右：目标名）+ Tip
# 区域角色（NPC）行省略：maps 节点无 npcs 字段——登记 DELAYED（NPC 数据源待 M6 数据框架）
# =====================================================================================

# 通道方向 → 中文标签（对齐 movement.DIRECTION_ALIASES：up=上/down=下/left=左/right=右）
_EXIT_DIR_LABELS: Dict[str, str] = {"up": "上", "down": "下", "left": "左", "right": "右"}
_EXIT_DIR_ORDER: Tuple[str, ...] = ("up", "down", "left", "right")

# /进入 Tip（对齐 /背包 尾段 Tip 句式：无斜杠）
_ENTER_TIP = "Tip:发送'位置'即可查询当前位置信息"

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
    """活动怪物行：`活动怪物：1.岩皮鼬×3 2.石甲蜥×1`（对齐 /背包 行格式 ×数量）。

    数据源 = maps 目标图 monsters 行（{enemy, count, ...}）；enemy id → 怪物名经
    ctx["monsters"]/ctx["enemies"] 解析，拿不到直接显示 enemy id；>5 只截断折叠（铁律 11）。
    无怪物 → None（行省略）。
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
        parts.append(f"{i}.{nm}×{cnt}")
    line = "活动怪物：" + " ".join(parts)
    if len(rows) > _MONSTER_SHOW_LIMIT:
        line += " …"
    return line


def _channel_lines(index: Mapping[str, Any], target: Any) -> List[str]:
    """通道行：`上：{目标地图名}`…（仅渲染已配置方向；缺省方向=死路，行省略）。"""
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
            lines.append(f"{_EXIT_DIR_LABELS.get(d, d)}：{_map_name(index, str(ex.get('to')))}")
        return lines
    for d in _EXIT_DIR_ORDER:
        ex = target.exit(d)
        if ex is None or not ex.to:
            continue
        lines.append(f"{_EXIT_DIR_LABELS.get(d, d)}：{_map_name(index, str(ex.to))}")
    return lines


def _render_enter(result: Mapping[str, Any],
                  ctx: Optional[Mapping[str, Any]] = None) -> str:
    """/进入 结果 → 1 条消息文本（move / dungeon / 失败）。

    move（通道行走）按 CakeGame 模板 28 风格：✅ 你来到了「name」+ 地图介绍 + 活动怪物
    （序号.名称×数量）+ 通道（上/下/左/右：目标地图名）+ Tip；区域角色（NPC）行省略
    （maps 节点无 npcs 字段——登记 DELAYED，NPC 数据源待 M6 数据框架）。
    """
    if not result.get("ok"):
        return f"❌ {result.get('reason') or '无法进入'}"
    kind = result.get("type")
    if kind == "dungeon":
        name = result.get("name") or result.get("dungeon_id") or ""
        return f"✅ 你进入了「{name}」（副本）"
    # move：通道行走 → 新地图信息（CakeGame 模板 28 风格丰富）
    name = result.get("name") or ""
    lines = [f"✅ 你来到了「{name}」"]
    desc = result.get("desc") or ""
    if desc:
        lines.append(f"地图介绍：{desc}")
    lore = result.get("lore") or ""
    if lore:
        lines.append(str(lore))
    index = _maps_index_for(ctx)
    target = index.get(str(result.get("to"))) if result.get("to") else None
    mline = _monster_line(ctx, target)
    if mline:
        lines.append(mline)
    # 区域角色（NPC）行省略：maps 节点无 npcs 字段（登记 DELAYED，NPC 数据源待 M6 数据框架）
    lines.extend(_channel_lines(index, target))
    lines.append(_ENTER_TIP)
    return "\n".join(lines)


def _render_rest(result: Mapping[str, Any]) -> str:
    """/休息 结果 → 1 条消息文本（成功 / 拒绝）。"""
    if not result.get("rested"):
        msg = result.get("message") or result.get("reason") or "无法休息"
        return f"❌ {msg}"
    hp = int(result.get("hp_restored", 0) or 0)
    mp = int(result.get("mp_restored", 0) or 0)
    cr = int(result.get("cooldown_reduction", 0) or 0)
    line = f"✅ 你休息了一会，回复 {hp} 点 HP、{mp} 点 MP"
    if cr:
        line += f"（冷却缩减 {cr}）"
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
        return "❌ 当前没有可探索的地图（/进入 尝试）"
    lines = ["【地图】"]
    for mid in list(index.keys()):
        entry = index[mid]
        if not entry:
            continue
        name = entry.get("name") if isinstance(entry, Mapping) else getattr(entry, "name", None) or mid
        lines.append(f"{mid}：{name}")
    return "\n".join(lines) + "\nTip:发送'进入 <地图id>'前往"


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
        return f"❌ 当前位置未知：{loc or '无'}（/进入 探索地图）"
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


def cmd_enter(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/进入 <方向|序号|名称>：通道行走 / 副本入口 → 1 条结果消息。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if not args:
        return "❌ /进入：输入方向（上/下/左/右）或副本入口（序号/名称）"
    arg = str(args[0])
    try:
        from qbot_rpg.world.movement import enter_context_route  # noqa: PLC0415
    except ImportError:
        return "❌ 进入功能未接线（引擎未加载）"
    player = _player_ctx(ctx)
    result = enter_context_route(
        dict(player), arg,
        maps=ctx.get("maps"), dungeons=ctx.get("dungeons"),
    )
    if not isinstance(result, Mapping):
        return "❌ 进入失败（引擎返回异常）"
    return _render_enter(result, ctx)


def cmd_rest(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/休息：副本安全区休息 → 1 条结果消息。"""
    g = _gate(ctx)
    if g is not None:
        return g
    if parsed.error:
        return format_tpl12(_fragment(parsed))
    args = list(getattr(parsed, "args", None) or [])
    if len(args) > 1:
        return "❌ 指令不正确：/休息 不需要参数。输入 /帮助 查看可用指令。"
    try:
        from qbot_rpg.world.rest import rest_in_dungeon  # noqa: PLC0415
    except ImportError:
        return "❌ 休息功能未接线（引擎未加载）"
    session = ctx.get("dungeon_session")
    result = rest_in_dungeon(
        session, _player_ctx(ctx),
        cfg=ctx.get("rest_cfg"),
    )
    if not isinstance(result, Mapping):
        return "❌ 休息失败（引擎返回异常）"
    return _render_rest(result)


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
    return router
