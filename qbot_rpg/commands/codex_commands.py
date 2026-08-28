"""图鉴指令壳（qbot_rpg/commands/codex_commands.py · M7 BCH-08 · 3f F-11/F-12 · R-17~R-20）。

/图鉴 [分册|页码]——无参=总览（三分册各自完成度 + 总完成度）；/图鉴 怪物|武器|物品
[页码] → 分册分页（5 条/页，未收集条目「???」不泄露名称）。注册「图鉴」指令
（DEFAULT_WHITELIST + DEFAULT_PREFIX_REQUIRED，可快捷绑定不可免前缀直发——参考
「对话/调查」M4 接缝裁决）。

依据：
  - docs/细化/细化_3f_单机向体验.md R-17~R-20（分册/完成度/??? 不提示原则）
  - qbot_rpg/core/codex.py（codex_progress/codex_view，BCH-08 路A 引擎）
  - qbot_rpg/core/message_format/list_render.py（render_cake_tail 尾段）

【工程补白 · 显式标注】
  1) 完成度展示用 round()（4d COD-08 展示取整口径）；条件求值用未取整（引擎侧 ctx["codex"]）。
  2) 无 registry（裸 ctx）→ 总览 pct 全 0，不崩（fail-safe）。
  3) 分册名接受「怪物/武器/物品」及别名「monster/weapon/item」。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, MutableMapping, Optional

from qbot_rpg.commands.router import CommandSpec

__all__ = ["CODEX_CMD", "cmd_codex", "register_codex_commands"]

CODEX_CMD = "图鉴"

# 分册名 → 引擎 key
_CAT_ALIASES: Mapping[str, str] = {
    "怪物": "monster", "怪物图鉴": "monster", "monster": "monster",
    "武器": "weapon", "武器图鉴": "weapon", "weapon": "weapon",
    "物品": "item", "物品图鉴": "item", "item": "item",
}

_PAGE_SIZE = 5


def _render_progress(label: str, p: Mapping[str, Any]) -> str:
    """分册进度行：{label} 完成度 {pct}%（已见/总数）。"""
    pct = round(float(p.get("pct", 0.0)))
    return f"{label}：{pct}%（{p.get('seen', 0)}/{p.get('total', 0)}）"


def _overview(ctx: MutableMapping[str, Any]) -> str:
    """总览：三分册各自完成度 + 总完成度（未收集条目仅计数不展示名称）。"""
    from qbot_rpg.core.codex import CATEGORY_ORDER, _CATEGORY_LABELS, codex_progress
    lines = ["【图鉴总览】"]
    for cat in CATEGORY_ORDER:
        p = codex_progress(ctx, cat)
        lines.append(_render_progress(_CATEGORY_LABELS.get(cat, cat), p))
    gp = codex_progress(ctx)
    lines.append(f"总完成度：{round(float(gp.get('pct', 0.0)))}%"
                 f"（{gp.get('seen', 0)}/{gp.get('total', 0)}）")
    lines.append("提示：分册页 /图鉴 怪物 2（每页 5 条）")
    return "\n".join(lines)


def _category_page(
    ctx: MutableMapping[str, Any], cat: str, page: int
) -> str:
    """分册分页展示（5 条/页，未收集「???」不泄露名称）。"""
    from qbot_rpg.core.codex import codex_view
    from qbot_rpg.core.message_format.list_render import render_cake_tail
    view = codex_view(ctx, cat, page)
    if not view.get("ok"):
        return "❌ 未知图鉴分册。"
    entries = view.get("entries", [])
    lines = [f"【{view.get('label', cat)}】"]
    if not entries:
        lines.append("（还没有收集记录）")
    else:
        for e in entries:
            mark = "✅" if e.get("seen") else "　"
            kill = "（已击杀）" if e.get("killed") else ""
            lines.append(f"{mark} {e.get('name', '???')}{kill}")
    total = int(view.get("total", 0))
    pages = int(view.get("pages", 1))
    cur = int(view.get("page", 1))
    lines.append(render_cake_tail(
        cur, pages, category_word=cat,
        tip=f"共 {total} 条记录"))
    return "\n".join(lines)


def cmd_codex(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/图鉴 指令：无参=总览；分册名[页码]=分册分页。

    入参 parsed: ParsedCommand（args 含分册/页码）；ctx: 玩家上下文。
    出参 str: 渲染回复（统一返回字符串）。
    核心逻辑: 首参命中分册别名 → 分册分页；否则总览；页码非法夹取。
    """
    args = list(getattr(parsed, "args", None) or ())
    if not args:
        return _overview(ctx)
    cat = _CAT_ALIASES.get(str(args[0]).strip())
    if cat is None:
        return _overview(ctx)
    page = 1
    if len(args) > 1:
        try:
            page = int(args[1])
        except (TypeError, ValueError):
            page = 1
    return _category_page(ctx, cat, page)


def register_codex_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /图鉴 注册进 Router（CommandSpec.handler 消费 ParsedCommand）。

    :param router: Router 实例；make_context: ParsedCommand → 玩家 ctx dict。
    :return: router（链式）。make_context 缺失时 handler 调用抛【待接线】RuntimeError。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】codex_commands.register_codex_commands 需要 "
                "make_context（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _codex(parsed: Any, *a: Any, **k: Any) -> str:
        if make_context is not None:
            return cmd_codex(parsed, _ctx(parsed))
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_codex(parsed, injected)
        return cmd_codex(parsed, _ctx(parsed))

    router.register(CommandSpec(CODEX_CMD, handler=_codex))
    return router
