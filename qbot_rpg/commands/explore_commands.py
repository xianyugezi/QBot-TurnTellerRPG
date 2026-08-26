"""世界层指令壳（M5-09 探索结果合并 1 条 · 铁律 2 / 开发规则 L515）。

指令：
- /进入 <方向|序号|名称>：通道行走 / 副本入口进入（引擎 enter_context_route / resolve_move）→ 结果 1 条
- /休息：副本安全区休息（引擎 rest_in_dungeon）→ 结果 1 条
- /采集：登记 DELAYED（采集引擎未接线——M3 地图批次未产出独立采集引擎，
  采集点在地图/副本探索流程内处理；M5-09 壳层不阻断，后续批次接线）

渲染纪律：单次操作最多 1-2 条消息（本壳一律 1 条返回文本）；emoji 仅 ✅/❌ + 排版符号
（| → × / 「」【】）；前缀首行注入由装配层（M5-01 prefix_wiring）统一处理，本壳不拼前缀。

依据：docs/m5_shared_contract.md §三 / 铁律 2 / 框架 §7.3 L1279-1281（/采集 /进入）/ §7.4。
"""
from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from .router import CommandSpec

# 指令名（对齐 parsers 白名单：进入/休息 已在 DEFAULT_WHITELIST）
ENTER_CMD = "进入"
REST_CMD = "休息"

__all__ = [
    "ENTER_CMD", "REST_CMD",
    "cmd_enter", "cmd_rest", "register_explore_commands",
]


def _fragment(parsed: Any) -> str:
    """原始指令片段（错误回显，对齐 basic_commands._fragment）。"""
    return str(getattr(parsed, "raw", None) or getattr(parsed, "text", "") or "").strip()


def _tpl12(fragment: str) -> str:
    """对齐 3d §5.1 TPL-12 句式（本壳不依赖 sender 常量，字面量同源）。"""
    return f"❌ 指令不正确：{fragment}。输入 /帮助 查看可用指令。"


def _render_enter(result: Mapping[str, Any]) -> str:
    """/进入 结果 → 1 条消息文本（move / dungeon / 失败）。"""
    if not result.get("ok"):
        return f"❌ {result.get('reason') or '无法进入'}"
    kind = result.get("type")
    if kind == "dungeon":
        name = result.get("name") or result.get("dungeon_id") or ""
        return f"✅ 你进入了「{name}」（副本）"
    # move：通道行走 → 新地图信息
    name = result.get("name") or ""
    lines = [f"✅ 你来到了「{name}」"]
    desc = result.get("desc") or ""
    if desc:
        lines.append(str(desc))
    lore = result.get("lore") or ""
    if lore:
        lines.append(str(lore))
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


def cmd_enter(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/进入 <方向|序号|名称>：通道行走 / 副本入口 → 1 条结果消息。"""
    if parsed.error:
        return _tpl12(_fragment(parsed))
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
    return _render_enter(result)


def cmd_rest(parsed: Any, ctx: Mapping[str, Any]) -> str:
    """/休息：副本安全区休息 → 1 条结果消息。"""
    if parsed.error:
        return _tpl12(_fragment(parsed))
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
            return handler(parsed, _ctx(parsed))
        return _h

    router.register(CommandSpec(ENTER_CMD, handler=_wrap(cmd_enter)))
    router.register(CommandSpec(REST_CMD, handler=_wrap(cmd_rest)))
    return router
