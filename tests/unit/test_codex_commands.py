"""M7 /图鉴 指令测试（tests/unit/test_codex_commands.py · F-11/F-12）。

覆盖：注册与白名单 · 总览 · 分册分页 · ??? 不泄露 · 页码夹取 · 注册门槛。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

import pytest

from qbot_rpg.commands.codex_commands import CODEX_CMD, cmd_codex, register_codex_commands
from qbot_rpg.commands.parsers import DEFAULT_PREFIX_REQUIRED, DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import CommandSpec, Router
from qbot_rpg.core.codex import mark_seen


class _FakeRegistry:
    def __init__(self, tables: Mapping[str, tuple]) -> None:
        self._tables = tables

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        return rid.upper()


def _ctx() -> MutableMapping[str, Any]:
    return {
        "registry": _FakeRegistry({
            "enemy": ("rock_weasel", "wood_wolf"),
            "equipment": ("iron_sword",),
            "item": ("potion",),
        }),
        "codex_state": {},
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": {},
    }


def _parsed(raw: str) -> Any:
    return parse_command(raw)


# ---------------------------------------------------------------------------
# 白名单与注册
# ---------------------------------------------------------------------------
def test_codex_in_whitelist_and_prefix_required() -> None:
    """「图鉴」入白名单；前缀口径同步 2026-09-03 裁决（全指令免 / 前缀）。

    原断言「图鉴 ∈ DEFAULT_PREFIX_REQUIRED」随 068bcd4 裁决作废——parsers.py
    L186-193 注释：原非 GM 需前缀指令（调查/图鉴/成就/对话等）全部放行免前缀，
    DEFAULT_PREFIX_REQUIRED 收敛为空集（GM 类由 gm_commands 独立强制 '/'）。
    """
    assert CODEX_CMD in DEFAULT_WHITELIST
    assert DEFAULT_PREFIX_REQUIRED == frozenset()
    assert CODEX_CMD not in DEFAULT_PREFIX_REQUIRED


def test_register_codex_commands_no_make_context_registers() -> None:
    """未注入 make_context → 注册成功，handler 调用才抛【待接线】。"""
    router = Router()
    register_codex_commands(router)
    spec = router.get(CODEX_CMD)
    assert isinstance(spec, CommandSpec)
    with pytest.raises(RuntimeError):
        spec.handler(_parsed("/图鉴"))  # type: ignore[misc]


def test_register_codex_commands_with_make_context() -> None:
    """注入 make_context → handler 可调。"""
    router = Router()
    register_codex_commands(router, make_context=lambda parsed: _ctx())  # type: ignore[arg-type,return-value]
    assert isinstance(router.get(CODEX_CMD), CommandSpec)


# ---------------------------------------------------------------------------
# 总览 / 分册 / ??? 不泄露
# ---------------------------------------------------------------------------
def test_codex_overview() -> None:
    """无参总览：三分册各自完成度 + 总完成度（2026-09-12 批9·路C 新排版）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    reply = cmd_codex(_parsed("/图鉴"), ctx)
    assert "【图鉴】收集总览" in reply
    assert "怪物图鉴" in reply
    assert "总完成度" in reply
    # 进度行拆两行：分册名+百分比 / 已见 seen/total（大数值独立行）
    assert "怪物图鉴：50%" in reply
    assert "已见 1/2" in reply
    assert "岩鼬" not in reply  # 总览只显示完成度，不列条目


def test_codex_category_page_seen_and_hidden() -> None:
    """分册分页：已见显示名称，未见「???」不泄露。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    reply = cmd_codex(_parsed("/图鉴 怪物"), ctx)
    assert "【怪物图鉴】" in reply
    assert "岩鼬" in reply
    assert "???" in reply
    assert "木狼" not in reply  # wood_wolf 未收集不显示真实名
    assert "当前页" in reply


def test_codex_category_pagination() -> None:
    """页码翻页。"""
    ctx = _ctx()
    for rid in ("rock_weasel", "wood_wolf", "moon_wolf"):
        mark_seen(ctx, "monster", rid, rid)
    reply2 = cmd_codex(_parsed("/图鉴 怪物 2"), ctx)
    assert "当前页" in reply2


def test_codex_unknown_category_falls_back_overview() -> None:
    """未知分册 → 回落总览。"""
    ctx = _ctx()
    reply = cmd_codex(_parsed("/图鉴 化石"), ctx)
    assert "【图鉴】收集总览" in reply


def test_codex_no_emoji() -> None:
    """渲染无装饰 emoji（✅/❌ + 排版符号豁免）。"""
    import re
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    for raw in ("/图鉴", "/图鉴 怪物"):
        reply = cmd_codex(_parsed(raw), ctx)
        emoji = [e for e in re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", reply)
                 if e not in ("✅", "❌")]  # 功能性标记豁免
        assert not emoji, f"{raw} 渲染含 emoji: {emoji}"


# ---------------------------------------------------------------------------
# 2026-08-31 模板配置化：ctx["templates"] 自定义覆盖 + 占位符白名单
# ---------------------------------------------------------------------------

def test_codex_custom_templates_override() -> None:
    """模板配置化：ctx["templates"] 注入自定义 codex_* → 渲染用自定义（含占位符替换）。"""
    from qbot_rpg.core.templates import resolve_templates
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    ctx["templates"] = resolve_templates({
        "codex_overview_header": "【自定义图鉴总览】",
        "codex_category_header": "【册·{label}】",
        "codex_entry_line": "{mark}|{name}{kill}",
        "codex_killed_mark": "[已击杀]",
        "codex_tail_tip": "共 {total} 项",
    })
    reply = cmd_codex(_parsed("/图鉴 怪物"), ctx)
    assert "【册·怪物图鉴】" in reply
    assert "|岩鼬" in reply
    assert "共 2 项" in reply
    overview = cmd_codex(_parsed("/图鉴"), ctx)
    assert "【自定义图鉴总览】" in overview


def test_codex_custom_template_unknown_placeholder_kept() -> None:
    """白名单外占位符：templates 含未登记占位符 → 渲染原样保留不崩。"""
    from qbot_rpg.core.templates import resolve_templates
    ctx = _ctx()
    ctx["templates"] = resolve_templates({
        "codex_progress_line": "{label}：{pct}%（{seen}/{total}）{bonus}",
        "codex_overview_hint": "提示：/图鉴 怪物 2",
    })
    reply = cmd_codex(_parsed("/图鉴"), ctx)
    assert "怪物图鉴：0%（0/2）{bonus}" in reply


def test_codex_tpl_whitelist_registered() -> None:
    """白名单测试：图鉴 14 键已迁全量表（分区默认表清空）——表内文本、派生白名单与占位符一致。

    2026-09-12 批9·路C：分区默认表/白名单清空，断言改走 TABLE_TEMPLATES（对齐
    test_pvp_commands.test_pvp_tpl_whitelist_registered / test_investigate_commands 同款口径）。
    """
    import re

    import qbot_rpg.core.templates.codex_tpl as _codex_partition
    from qbot_rpg.core.templates import (
        DEFAULT_TEMPLATES,
        PLACEHOLDER_WHITELIST,
        TABLE_TEMPLATES,
    )
    # 分区默认表/白名单已清空（14 键全部迁全量表；空壳保留 import 兼容）
    assert not _codex_partition.DEFAULT_TEMPLATES
    assert not _codex_partition.PLACEHOLDER_WHITELIST
    codex_keys = {k for k in TABLE_TEMPLATES if k.startswith("codex_")}
    assert len(codex_keys) == 14
    pat = re.compile(r"\{([a-zA-Z0-9_]+)\}")
    for key in sorted(codex_keys):
        assert DEFAULT_TEMPLATES[key] == TABLE_TEMPLATES[key], f"聚合未走表：{key}"
        assert PLACEHOLDER_WHITELIST[key] == set(pat.findall(TABLE_TEMPLATES[key])), (
            f"白名单不一致：{key}"
        )
    # 占位符逐键核对（信息要素不丢字段）
    assert PLACEHOLDER_WHITELIST["codex_progress_line"] == {"label", "pct", "seen", "total"}
    assert PLACEHOLDER_WHITELIST["codex_total_progress"] == {"pct", "seen", "total"}
    assert PLACEHOLDER_WHITELIST["codex_next_tier"] == {"tier", "gap"}
    assert PLACEHOLDER_WHITELIST["codex_category_header"] == {"label"}
    assert PLACEHOLDER_WHITELIST["codex_entry_line"] == {"mark", "name", "kill", "rumor"}
    assert PLACEHOLDER_WHITELIST["codex_tail_tip"] == {"total"}
    # 无占位符模板：白名单空集
    for key in ("codex_overview_header", "codex_overview_hint", "codex_tier_maxed",
                "codex_unknown_category", "codex_category_empty", "codex_killed_mark",
                "codex_rumor_mark", "codex_unknown_name"):
        assert PLACEHOLDER_WHITELIST[key] == set(), f"{key} 应无占位符"