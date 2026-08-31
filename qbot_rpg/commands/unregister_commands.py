"""注销指令接线 unregister_commands.py（2026-08-28 用户拍板新增 /注销）。

依据：用户拍板「增加注销（重新开始）」；设计契约见 记录.md 需求池 + 部署会话设计契约。
职责：/注销 二次确认删档——无参 = 确认提示（不删档）；`/注销 确认` = 二次确认后删档。
删档落库由装配层 runner._plain_handler 检测 ctx["unregister_player"] 同事务调
tx.delete_player（ctx["player"]=None → upsert 分支自然跳过）；并发竞态（事务执行时行已删）
→ 返回「你没有可注销的角色」。

本 handler 只生成数据（零 IO、零 NoneBot、纯函数确定性）：校验已注册 → 确认参数判定 →
置删档标记 + 渲染模板。零装饰 emoji（仅 ✅/❌ +「」排版符）。
"""
from __future__ import annotations

from typing import Any, Callable, MutableMapping, Optional

from .router import CommandSpec

UNREGISTER_CMD = "注销"

# 二次确认固定子词（parsers.FIXED_SUBWORDS 含「确认」，/注销 确认 → fixed_subword 抽取）
CONFIRM_SUBWORD = "确认"

# 模板（D-04 文案唯一源本模块；仅 ✅/❌ +「」排版符）
# 2026-08-31 用户拍板：主句与「确认请发」分两行
TPL_UNREG_CONFIRM = (
    "注销将删除角色「{name}」所有数据（等级/装备/背包/图鉴/成就/日志）且不可恢复！\n"
    "确认请发：/注销 确认"
)
TPL_UNREG_OK = "✅ 已注销角色「{name}」，数据已删除。想再玩随时 /注册 重新开始"
TPL_UNREG_NONE = "❌ 你还没有注册角色"
TPL_UNREG_AGAIN = "❌ 你没有可注销的角色"

__all__ = [
    "UNREGISTER_CMD",
    "TPL_UNREG_CONFIRM", "TPL_UNREG_OK", "TPL_UNREG_NONE", "TPL_UNREG_AGAIN",
    "cmd_unregister", "register_unregister_commands",
]


def cmd_unregister(parsed: Any, ctx: MutableMapping[str, Any]) -> str:
    """/注销 指令壳：无参 → 确认提示；固定子词「确认」→ 置删档标记 + 成功模板。

    入参 parsed: ParsedCommand（fixed_subword/args 消费）；ctx: 玩家上下文
    （registered/player/unregister_player 消费/写入）。出参 str——回复正文。
    核心逻辑: 未注册 → TPL_UNREG_NONE；已注册但未二次确认 → TPL_UNREG_CONFIRM；
    已注册且确认 → 置 ctx["unregister_player"]=True + ctx["player"]=None +
    ctx["registered"]=False（装配层 runner 检测后同事务删档），返回 TPL_UNREG_OK。
    注意: parsers 把「确认」抽为 fixed_subword（args 为空）——确认判定必须
    fixed_subword == "确认" 或 args 含「确认」（防御快捷展开路径）。
    """
    if not bool(ctx.get("registered")):
        return TPL_UNREG_NONE
    player = ctx.get("player")
    name = ""
    if isinstance(player, MutableMapping):
        name = str(player.get("name") or "")
    else:
        name = str(getattr(player, "name", "") or "")
    fs = getattr(parsed, "fixed_subword", None)
    args = list(getattr(parsed, "args", None) or [])
    confirmed = (fs == CONFIRM_SUBWORD) or (CONFIRM_SUBWORD in args)
    if not confirmed:
        return TPL_UNREG_CONFIRM.format(name=name)
    # 置删档标记（装配层 runner._plain_handler 检测后调 tx.delete_player 同事务删档）
    ctx["unregister_player"] = True
    ctx["player"] = None
    ctx["registered"] = False
    return TPL_UNREG_OK.format(name=name)


def register_unregister_commands(
    router: Any, *, make_context: Optional[Callable[[Any], dict]] = None
) -> Any:
    """把 /注销 注册进 Router（同 register_commands 模式；make_context 由装配层注入）。

    入参 router: Router；make_context: ParsedCommand → 玩家 ctx（None 时 handler
    调用抛 RuntimeError【待接线】）。出参 router。
    核心逻辑: _ctx 抛待接线 / 注入 ctx 优先（同 register_commands L494-518 模式）。
    """
    def _ctx(parsed: Any) -> dict:
        if make_context is None:
            raise RuntimeError(
                "【待接线】unregister_commands.register_unregister_commands 需要 make_context"
                "（玩家上下文工厂，由装配层注入）"
            )
        return make_context(parsed)

    def _unregister(parsed: Any, *a: Any, **k: Any) -> str:
        injected = k.get("ctx") if isinstance(k, dict) else None
        if isinstance(injected, MutableMapping):
            return cmd_unregister(parsed, injected)
        return cmd_unregister(parsed, _ctx(parsed))

    router.register(CommandSpec(UNREGISTER_CMD, handler=_unregister))
    return router
