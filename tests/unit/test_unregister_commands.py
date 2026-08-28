"""/注销 指令测试（2026-08-28 用户拍板新增：二次确认删档）。

承接 unregister_commands.py：未注册/未确认/确认成功/重复注销 + 装配注册。
风格照 test_register_commands.py（make_ctx + parse_command + BANNED_EMOJI 扫描）。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from qbot_rpg.commands.parsers import parse_command, ParsedCommand
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.unregister_commands import (
    TPL_UNREG_AGAIN,
    TPL_UNREG_CONFIRM,
    TPL_UNREG_NONE,
    TPL_UNREG_OK,
    cmd_unregister,
    register_unregister_commands,
)

BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")


def make_ctx(**over: Any) -> dict:
    """已注册玩家基础 ctx（每场景新造）。"""
    base = {
        "registered": True,
        "player": {"name": "测试勇士", "level": 1, "job_id": "warrior"},
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（白名单已含「注销」）。"""
    return parse_command(raw)


def test_unreg_none_not_registered() -> None:
    """未注册 → TPL_UNREG_NONE。"""
    ctx = make_ctx(registered=False, player=None)
    assert cmd_unregister(parse("/注销"), ctx) == TPL_UNREG_NONE


def test_unreg_confirm_prompt_no_arg() -> None:
    """已注册无参 → 确认提示（含名字，不删档）。"""
    ctx = make_ctx()
    out = cmd_unregister(parse("/注销"), ctx)
    assert out == TPL_UNREG_CONFIRM.format(name="测试勇士")
    assert ctx.get("unregister_player") is None  # 未删档标记


def test_unreg_confirm_subword_success() -> None:
    """/注销 确认（fixed_subword）→ 成功 + 删档标记。"""
    ctx = make_ctx()
    out = cmd_unregister(parse("/注销 确认"), ctx)
    assert out == TPL_UNREG_OK.format(name="测试勇士")
    assert ctx.get("unregister_player") is True
    assert ctx.get("player") is None
    assert ctx.get("registered") is False


def test_unreg_confirm_in_args_success() -> None:
    """args 含「确认」（快捷展开路径）→ 成功。"""
    parsed = SimpleNamespace(args=["确认"], fixed_subword=None)
    ctx = make_ctx()
    out = cmd_unregister(parsed, ctx)
    assert out == TPL_UNREG_OK.format(name="测试勇士")
    assert ctx.get("unregister_player") is True


def test_unreg_again_template_defined() -> None:
    """重复注销模板存在（装配层并发竞态触发路径）。"""
    assert "你没有可注销的角色" in TPL_UNREG_AGAIN


def test_unreg_no_decorative_emoji() -> None:
    """模板零装饰 emoji（仅 ✅/❌ +「」排版符）。"""
    for tpl in (TPL_UNREG_CONFIRM, TPL_UNREG_OK, TPL_UNREG_NONE, TPL_UNREG_AGAIN):
        for ch in tpl:
            assert ch not in BANNED_EMOJI, f"命中禁用装饰 emoji：{ch} in {tpl!r}"


def test_register_unregister_commands_routes() -> None:
    """register_unregister_commands：/注销 注册进 Router 且 handler 可命中。"""
    router = Router()

    def fake_ctx(parsed: ParsedCommand) -> dict:
        return make_ctx()

    register_unregister_commands(router, make_context=fake_ctx)
    assert router.has("注销")
    spec = router.get("注销")
    assert spec is not None and spec.whitelisted
    handler = spec.handler
    assert handler is not None
    out = handler(parse("/注销 确认"))
    assert out == TPL_UNREG_OK.format(name="测试勇士")


def test_unregister_without_make_context_raises() -> None:
    """未注入 make_context → handler 调用抛 RuntimeError【待接线】。"""
    import pytest

    router = Router()
    register_unregister_commands(router)
    spec = router.get("注销")
    assert spec is not None
    handler = spec.handler
    assert handler is not None
    with pytest.raises(RuntimeError):
        handler(parse("/注销"))
