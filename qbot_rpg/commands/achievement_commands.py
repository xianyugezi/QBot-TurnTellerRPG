"""成就指令壳（qbot_rpg/commands/achievement_commands.py · M11 批1 路1C）。

指令（对齐 4c 契约 §七 L404）：
  /成就 [页数]        5 条/页、locked 锁定行「？？？」占序号、hide 完全隐藏、
                      已达成置顶（引擎 list_achievements 已做排序）
  /成就信息 <N>       锁定态只显「？？？」不渲染明文
  /称号 查看          当前佩戴 + 已拥有列表（ProficiencyEngine.owned_titles）
  /称号 佩戴 <N>      按序号从 owned_titles 映射到 title_id（equip_title 1 槽替换）

依据：
  - docs/细化/细化_4c_成就系统契约.md §七（指令表）/ §五（隐藏成就展示纪律）
  - docs/m11_成就摸底.md §2.6-2.7（注册先例 + 模板分区）
  - qbot_rpg/commands/codex_commands.py（注册模式先例）
  - qbot_rpg/commands/forge_commands.py（_fragment + CommandSpec 先例）

【工程补白 · 显式标注】
  F-1  引擎 list_achievements 已实现「已达成置顶 + ？？？占位 + hide 过滤」，
       壳层只消费不重复实现。
  F-2  揭示卡片（隐藏成就达成瞬间）由引擎 check_achievements 返回 reveals 字段，
       壳层渲染走 ach_reveal_card 模板；正常指令流不主动触发。
  F-3  /称号 无参默认即查看（对齐契约「/称号」与「/称号 查看」双写）。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    PageResolution,
    render_cake_tail,
    resolve_page,
)
from qbot_rpg.core.templates import tpl_of

CMD_ACH = "成就"
CMD_ACH_INFO = "成就信息"
CMD_TITLE = "称号"

# 占位兜底（tpl_of 缺省走 achievement_tpl 分区，此处为兼容旧测试/裸 ctx）
_DEF_EMPTY = "【成就】暂无成就"
_DEF_VIEW_NOT_FOUND = "❌ 成就不存在：{aid}"


def _gate(ctx: Mapping[str, Any]) -> Optional[str]:
    """注册门槛（RUL-08）：未注册玩家 → 统一拒绝文案。"""
    if ctx.get("registered", True) is False:
        return tpl_of(ctx, "register_gate", {})
    return None


def _fragment(parsed: Any) -> str:
    """解析错误片段（对齐 forge_commands._fragment）。"""
    frag = getattr(parsed, "fragment", None)
    if isinstance(frag, str) and frag:
        return frag
    return getattr(parsed, "raw", "") or ""


def _player_of(ctx: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    """玩家 ctx：ctx["player"] 优先，回退 ctx 自身（对齐 shell 先例）。"""
    p = ctx.get("player")
    if isinstance(p, MutableMapping):
        return p
    return ctx


def _titles_of(ctx: MutableMapping[str, Any]):
    """称号注册表（装配注入 ctx["titles"]；缺省空 dict）。"""
    titles = ctx.get("titles")
    if isinstance(titles, Mapping):
        return titles
    return {}


def _owned_titles(ctx: MutableMapping[str, Any]) -> list:
    """已拥有称号列表（ProficiencyEngine.owned_titles）。"""
    player = _player_of(ctx)
    try:
        from qbot_rpg.core.proficiency import ProficiencyEngine

        eng = ProficiencyEngine()
        owned = eng.owned_titles(player)
        if isinstance(owned, (list, tuple)):
            return list(owned)
    except Exception:  # noqa: BLE001 —— 引擎缺失 → 空列表（容错）
        pass
    ts = player.get("title_state") if isinstance(player, Mapping) else None
    if isinstance(ts, Mapping):
        return list(ts.get("owned", ()) or ())
    return []


def _current_title(ctx: MutableMapping[str, Any]) -> str:
    """当前佩戴称号（title_state.equipped；缺省 '无'）。"""
    player = _player_of(ctx)
    ts = player.get("title_state") if isinstance(player, Mapping) else None
    if isinstance(ts, Mapping):
        cur = ts.get("equipped") or ts.get("current") or ts.get("title")
        if isinstance(cur, str) and cur:
            return cur
    return "无"


# ---------------------------------------------------------------------------
# /成就 列表
# ---------------------------------------------------------------------------
def cmd_achievements(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/成就 [页数]：成就墙分页列表（5 条/页）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    args = list(getattr(parsed, "args", None) or ())
    try:
        from qbot_rpg.core.achievements import list_achievements
    except ImportError:
        return tpl_of(ctx, "ach_empty", {})
    entries = list_achievements(ctx)
    # hide 未达成 → 壳层过滤（不占序号，TC-15；引擎返回全部带 mode，过滤归展示层）
    entries = [e for e in entries if not (e.get("mode") == "hide" and not e.get("unlocked"))]
    if not entries:
        return tpl_of(ctx, "ach_empty", {})
    done = sum(1 for e in entries if e.get("unlocked"))
    total = len(entries)

    page_raw = args[0] if args else 1
    res: PageResolution = resolve_page(page_raw, total, DEFAULT_PAGE_SIZE)
    if res.invalid:
        from qbot_rpg.commands.sender import page_error_tpl12
        return page_error_tpl12("成就", CMD_ACH, res.total_pages, total)
    page = res.page if res.page is not None else 1
    start = (page - 1) * DEFAULT_PAGE_SIZE
    slice_ = entries[start:start + DEFAULT_PAGE_SIZE]

    lines = [tpl_of(ctx, "ach_list_header", {
        "page": page, "pages": res.total_pages, "done": done, "total": total})]
    for i, e in enumerate(slice_, start=start + 1):
        if e.get("locked") and not e.get("unlocked"):
            lines.append(tpl_of(ctx, "ach_list_locked", {"index": i}))
        else:
            state = "✅" if e.get("unlocked") else "未达成"
            lines.append(tpl_of(ctx, "ach_list_line", {
                "index": i, "name": e.get("name", "？"), "state": state}))
    lines.append(render_cake_tail(page, res.total_pages, category_word="成就",
                                  tip="输入 /成就信息 <N> 查看详情"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /成就信息 <N>
# ---------------------------------------------------------------------------
def cmd_achievement_info(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/成就信息 <N>：单条成就详情（锁定态只显「？？？」）。"""
    g = _gate(ctx)
    if g is not None:
        return g
    args = list(getattr(parsed, "args", None) or ())
    if not args:
        return tpl_of(ctx, "ach_view_not_found", {"aid": "?"})
    try:
        idx = int(args[0])
    except (TypeError, ValueError):
        return tpl_of(ctx, "ach_view_not_found", {"aid": str(args[0])})
    try:
        from qbot_rpg.core.achievements import list_achievements
    except ImportError:
        return tpl_of(ctx, "ach_view_not_found", {"aid": str(idx)})
    entries = list_achievements(ctx)
    if not (1 <= idx <= len(entries)):
        return tpl_of(ctx, "ach_view_not_found", {"aid": str(idx)})
    e = entries[idx - 1]
    if e.get("locked") and not e.get("unlocked"):
        return tpl_of(ctx, "ach_view_hidden", {})
    name = e.get("name", "？")
    desc = e.get("desc", "")
    lines = [tpl_of(ctx, "ach_view_header", {"name": name})]
    if desc:
        lines.append(tpl_of(ctx, "ach_view_desc", {"desc": desc}))
    lines.append("状态：" + ("✅ 已达成" if e.get("unlocked") else "未达成"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# /称号 查看 / 佩戴
# ---------------------------------------------------------------------------
def cmd_title(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/称号 [查看|佩戴 <N>]：当前佩戴 + 已拥有列表 / 佩戴称号。"""
    g = _gate(ctx)
    if g is not None:
        return g
    args = list(getattr(parsed, "args", None) or ())
    owned = _owned_titles(ctx)
    if not owned:
        return tpl_of(ctx, "ach_title_empty", {})

    # 佩戴分支（第二个参数是数字序号）
    if len(args) >= 2:
        try:
            n = int(args[1])
        except (TypeError, ValueError):
            return tpl_of(ctx, "ach_title_help", {})
        if not (1 <= n <= len(owned)):
            return tpl_of(ctx, "ach_title_equip_fail", {"title_id": str(args[1])})
        title_id = owned[n - 1]
        return _equip_title(ctx, title_id)

    # 查看分支
    current = _current_title(ctx)
    lines = [tpl_of(ctx, "ach_title_header", {"current": current})]
    for i, tid in enumerate(owned, start=1):
        lines.append(tpl_of(ctx, "ach_title_line", {"index": i, "title_id": tid}))
    return "\n".join(lines)


def _equip_title(ctx: MutableMapping[str, Any], title_id: str) -> str:
    """佩戴称号（ProficiencyEngine.equip_title，1 槽替换）。"""
    player = _player_of(ctx)
    try:
        from qbot_rpg.core.proficiency import ProficiencyEngine

        eng = ProficiencyEngine()
        r = eng.equip_title(player, title_id)
        if isinstance(r, Mapping) and r.get("ok"):
            return tpl_of(ctx, "ach_title_equip_ok", {"title_id": title_id})
    except Exception:  # noqa: BLE001 —— 引擎异常 → 失败提示（容错）
        pass
    return tpl_of(ctx, "ach_title_equip_fail", {"title_id": title_id})


# ---------------------------------------------------------------------------
# 注册
# ---------------------------------------------------------------------------
def register_achievement_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /成就 /成就信息 /称号 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。"""

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】achievement_commands.register_achievement_commands 需要 "
                "make_context（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _wrap(fn: Callable[[Any, MutableMapping[str, Any]], str]) -> Callable[..., str]:
        def handler(parsed: Any, *a: Any, **k: Any) -> str:
            injected = k.get("ctx") if isinstance(k, dict) else None
            if isinstance(injected, MutableMapping):
                return fn(parsed, injected)
            return fn(parsed, _ctx(parsed))
        return handler

    from qbot_rpg.commands.router import CommandSpec

    router.register(CommandSpec(CMD_ACH, handler=_wrap(cmd_achievements)))
    router.register(CommandSpec(CMD_ACH_INFO, handler=_wrap(cmd_achievement_info)))
    router.register(CommandSpec(CMD_TITLE, handler=_wrap(cmd_title)))
    return router
