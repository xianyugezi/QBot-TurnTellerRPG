"""委托板指令族：/委托 查看/接取 N/交付 N 道具（2c5b CMD-01~06）。

文件名：quest_board_commands.py
创建时间：2026-09-06
作者：Hermes 主代理（指令缺口补全批2路3）

双板仲裁（CMD-02）：裸 /任务 /接取 /交付 归玩家任务板（quest_commands）；
委托板操作必须带板前缀 /委托 ——本模块独立指令名「委托」注册，不占用 /任务。

功能：
  - cmd_quest_board：/委托（缺省=查看）/ 委托 查看 → 板列表（懒刷新+惩罚结算）
  - cmd_quest_board 子词 接取 <N>：接取第 N 条可见委托
  - cmd_quest_board 子词 交付 <N> <道具>：交付进行中第 N 单
"""
from __future__ import annotations

from typing import Any, Callable, MutableMapping, Optional

from qbot_rpg.core import quest_board as qb

__all__ = [
    "DELEGATE_CMD",
    "cmd_delegate_board",
    "register_quest_board_commands",
]

DELEGATE_CMD = "委托"
_VIEW_SUBWORD = "查看"
_ACCEPT_SUBWORD = "接取"
_DELIVER_SUBWORD = "交付"


def _now_of(ctx: MutableMapping[str, Any]) -> int:
    import time  # noqa: PLC0415
    n = ctx.get("now")
    try:
        if n is None:
            raise TypeError
        return int(n)
    except (TypeError, ValueError):
        return int(time.time())


def _render_rows(ctx: MutableMapping[str, Any], view: dict) -> str:
    rows = view.get("rows") or []
    if not rows:
        base = "委托板：本周期暂无可接取的委托"
        return base + f"（声望 {view.get('rep_name')} · {view.get('rep_value')}）"
    lines: list = []
    for r in rows:
        if r.get("visible"):
            # M5 裁决（登记表 §一.3）：★(U+2605) 落 emoji 扫描范围，降级为
            # 几何图形符号 ◆(U+25C6，U+25xx 区段，非 emoji、不触扫描也不被剥离)
            star = "◆" * int(r.get("star", 1))
            lines.append(
                f"{r['index']}. {r['name']} {star}｜{r['require_txt']}"
                f"｜声望+{r.get('rep_base', 10)}")
        else:
            lines.append(
                f"{r['index']}. {r['name']}（声望需 {r.get('rep_min', 0)}）")
    lines.append(
        f"进行中 {view.get('active_count', 0)} 单｜声望 {view.get('rep_name')}"
        f"（{view.get('rep_value')}）｜{view.get('tip')}")
    return "\n".join(lines)


def cmd_delegate_board(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/委托 [查看|接取 <N>|交付 <N> <道具>]：委托板指令族（CMD-01~06）。

    缺省/查看 → 板列表；接取 N → 接取；交付 N 道具 → 交付。全部引擎透传。
    """
    if parsed.error:
        return "❌ 委托板：指令格式错误（/委托 查看｜/委托 接取 <序号>｜/委托 交付 <编号> <道具>）"
    args = list(getattr(parsed, "args", None) or [])
    sub = str(args[0]) if args else _VIEW_SUBWORD
    now = _now_of(ctx)
    if sub in (_VIEW_SUBWORD,):
        view = qb.board_view(ctx, now)
        if not view.get("ok"):
            return str(view.get("message") or "❌ 委托板：暂不可用")
        return _render_rows(ctx, view)
    if sub == _ACCEPT_SUBWORD:
        if len(args) < 2:
            return "❌ 委托板：请指定序号（/委托 接取 <序号>）"
        n = args[1]
        if not str(n).isdigit():
            return f"❌ 委托板：序号必须是整数（收到「{n}」）"
        res = qb.board_accept(ctx, int(n), now)
        return str(res.get("message") or "❌ 委托板：接取失败")
    if sub == _DELIVER_SUBWORD:
        if len(args) < 3:
            return "❌ 委托板：/委托 交付 <编号> <道具名>"
        n = args[1]
        if not str(n).isdigit():
            return f"❌ 委托板：编号必须是整数（收到「{n}」）"
        item_ref = str(args[2])
        res = qb.board_deliver(ctx, int(n), item_ref, now)
        return str(res.get("message") or "❌ 委托板：交付失败")
    return f"❌ 委托板：未知子词「{sub}」（查看/接取 <序号>/交付 <编号> <道具>）"


def register_quest_board_commands(
    router: Any,
    *,
    make_context: Optional[Callable[[Any], dict]] = None,
) -> Any:
    """把 /委托 注册进 Router。"""
    from qbot_rpg.commands.router import CommandSpec  # noqa: PLC0415

    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "quest_board_commands.register_quest_board_commands 需要 make_context")
        return make_context(parsed)

    def _h(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_delegate_board(parsed, injected)
        return cmd_delegate_board(parsed, _ctx(parsed))

    router.register(CommandSpec(DELEGATE_CMD, handler=_h))
    return router
