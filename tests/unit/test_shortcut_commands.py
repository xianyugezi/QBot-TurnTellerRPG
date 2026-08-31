"""快捷指令单测（M6 批次1·路B · qbot_rpg/commands/shortcut_commands.py）——TC-SHC-01~03 全量。

依据：细化_M6_三引擎与基础指令（D1）§六（SHC-01~SHC-05 / TC-SHC-01~03，承接 4f
TC-22/23/17）+ 细化_4f §五（CMD-07/CMD-08 / RUL-30/31 / TPL-4F-10/11）+ 细化_3d
（TPL-12 / emoji 纪律 / 5 条/页 + CakeGame 式尾段）。

测试风格对齐 tests/unit/test_basic_commands.py：make_ctx 模式、纯 pytest、零 NoneBot、
断言具体输出字符串。渲染仅 ✅/❌ 功能性标记（M5 裁决「不用 emoji」）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.basic_commands import TPL_REGISTER_GATE
from qbot_rpg.commands.parsers import ParsedCommand, parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.shortcut_commands import (
    DEFAULT_SHORTCUT_MAX,
    SHORTCUT_LIST_CMD,
    SHORTCUT_UNBIND_CMD,
    cmd_shortcut_list,
    cmd_shortcut_unbind,
    register_shortcut_commands,
)
from qbot_rpg.core.templates.shortcut_tpl import DEFAULT_TEMPLATES as SHORTCUT_TPL

# 3d §4.2 装饰性 emoji 禁用清单（渲染输出扫描锚点）
BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")


def make_ctx(**over):
    """全字段快捷 ctx（每场景新造；shortcuts 为可变 dict，就地改写）。"""
    base = {
        "registered": True,
        "shortcuts": {"1": "攻击", "火球": "攻击3"},
        "shortcut_max": DEFAULT_SHORTCUT_MAX,
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（parsers.DEFAULT_WHITELIST 已含 快捷解绑/快捷列表）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# TC-SHC-01 覆盖/解绑边界（承接 4f TC-22）
# ---------------------------------------------------------------------------

def test_tc_shc_01_unbind_ok():
    """TC-SHC-01：`快捷解绑 1`（已绑定）→ ✅ 已解绑『1』，就地改写 ctx["shortcuts"]。"""
    ctx = make_ctx()
    out = cmd_shortcut_unbind(parse("/快捷解绑 1"), ctx)
    assert out == "✅ 已解绑『1』"
    assert ctx["shortcuts"] == {"火球": "攻击3"}          # 就地改写（装配层落档 SHC-03）


def test_tc_shc_01_unbind_missing():
    """TC-SHC-01：`快捷解绑 不存在` → ❌ 没有绑定『不存在』，表不变。"""
    ctx = make_ctx()
    out = cmd_shortcut_unbind(parse("/快捷解绑 不存在"), ctx)
    assert out == "❌ 没有绑定『不存在』"
    assert ctx["shortcuts"] == {"1": "攻击", "火球": "攻击3"}


def test_shc_unbind_syntax_tpl12():
    """工程补白 1：解绑必须恰好 1 参数；0 参/超参/解析错误 → TPL-12。"""
    ctx = make_ctx()
    assert cmd_shortcut_unbind(parse("/快捷解绑"), ctx).startswith("❌ 指令不正确：/快捷解绑")
    assert cmd_shortcut_unbind(parse("/快捷解绑 1 2"), ctx).startswith("❌ 指令不正确：/快捷解绑 1 2")


def test_shc_unbind_unregistered_gate():
    """RUL-08：未注册 → 注册门槛拦截（快捷指令非豁免）。"""
    ctx = make_ctx(registered=False)
    assert cmd_shortcut_unbind(parse("/快捷解绑 1"), ctx) == TPL_REGISTER_GATE


# ---------------------------------------------------------------------------
# TC-SHC-02 列表与持久化（承接 4f TC-23）
# ---------------------------------------------------------------------------

def test_tc_shc_02_list():
    """TC-SHC-02：`快捷列表` → 头部【快捷（N/20）】+ 每行 `快捷名 → 指令串`。"""
    ctx = make_ctx()
    out = cmd_shortcut_list(parse("/快捷列表"), ctx)
    lines = out.splitlines()
    assert lines[0] == "【快捷（2/20）】"
    assert "1 → 攻击" in lines
    assert "火球 → 攻击3" in lines


def test_tc_shc_02_list_empty():
    """TC-SHC-02：空表 → ❌ 还没有快捷绑定，试试 /快捷绑定 1 攻击（shortcut_empty 模板）。"""
    ctx = make_ctx(shortcuts={})
    assert cmd_shortcut_list(parse("/快捷列表"), ctx) == SHORTCUT_TPL["shortcut_empty"]


def test_shc_list_persist_in_ctx():
    """TC-SHC-02 后半：列表读 ctx["shortcuts"]（随玩家存档持久化，装配层落档）——
    解绑后重启语义 = 同一 ctx["shortcuts"] 引用，表内容就地保留/更新。"""
    ctx = make_ctx()
    cmd_shortcut_unbind(parse("/快捷解绑 火球"), ctx)
    # 「重启后」：装配层以持久化表重建 ctx["shortcuts"]，内容应与解绑后一致
    ctx2 = make_ctx(shortcuts=dict(ctx["shortcuts"]))
    out = cmd_shortcut_list(parse("/快捷列表"), ctx2)
    assert "【快捷（1/20）】" in out
    assert "火球" not in out


def test_shc_list_paging_clamp():
    """工程补白 2：列表支持页码 + 5 条/页 + 裁决② 夹取；0/负数/非数字 → TPL-12。"""
    ctx = make_ctx(shortcuts={f"s{i}": f"攻击{i}" for i in range(1, 8)})  # 7 条 → 2 页
    out1 = cmd_shortcut_list(parse("/快捷列表"), ctx)
    assert "s1 → 攻击1" in out1 and "s6 → 攻击6" not in out1      # 第 1 页 5 条
    out2 = cmd_shortcut_list(parse("/快捷列表 2"), ctx)
    assert "s6 → 攻击6" in out2 and "s1 → 攻击1" not in out2      # 第 2 页 2 条
    out3 = cmd_shortcut_list(parse("/快捷列表 99"), ctx)          # 夹取最后一页
    assert "s6 → 攻击6" in out3
    assert cmd_shortcut_list(parse("/快捷列表 0"), ctx).startswith("❌ 指令不正确：/快捷列表 0")
    assert cmd_shortcut_list(parse("/快捷列表 abc"), ctx).startswith("❌ 指令不正确：/快捷列表 abc")


def test_shc_list_no_decorative_emoji():
    """M5 裁决：渲染输出仅 ✅/❌，无装饰 emoji。"""
    ctx = make_ctx()
    out = cmd_shortcut_list(parse("/快捷列表"), ctx) + cmd_shortcut_unbind(parse("/快捷解绑 1"), ctx)
    assert not any(ch in BANNED_EMOJI for ch in out)


# ---------------------------------------------------------------------------
# TC-SHC-03 帮助别名显示替换（承接 4f TC-17 → basic_commands.cmd_help 消费）
# ---------------------------------------------------------------------------

def test_tc_shc_03_help_alias_display():
    """TC-SHC-03：内容包配 `炼金→炼丹`（keep_original:false）→ 制造生活组仅显示 `炼丹`，
    不显示 `炼金`；发 `炼丹` 正常触发（解析走 parsers 别名机制，既有）。"""
    import qbot_rpg.commands.basic_commands as bc
    ctx = _make_help_ctx()
    out = bc.cmd_help(parse("/帮助 制造生活"), ctx)
    # 指令名已替换为别名（描述文本「炼金制作」保留，别名只作用于指令名列，TC-17）
    assert "炼丹 —— 炼金制作" in out
    assert "炼金 —— 炼金制作" not in out
    # keep_original 缺省 true → 双名并显
    ctx2 = _make_help_ctx(aliases={"锻造": "炼器"})
    out2 = bc.cmd_help(parse("/帮助 制造生活"), ctx2)
    assert "锻造/炼器" in out2


def _make_help_ctx(aliases=None):
    """cmd_help 消费 ctx（对齐 test_basic_commands.make_ctx 精简版 + command_aliases）。"""
    from qbot_rpg.data.player import PlayerAttributes
    return {
        "name": "阿伟", "level": 3, "exp": 320, "job_id": "warrior", "job_name": "战士",
        "hp": 30, "mp": 8, "exp_next": 1000, "registered": True, "is_gm": False,
        "stats": {"str": {"name": "力量"}},
        "attr_layers": {"base": {}, "bonus": {"flat": {}, "pct": {}}, "temp": {"pct": {}, "flat": {}}},
        "items": {}, "inventory": [], "equipment": {},
        "skills": {}, "skill_chains": {},
        "jobs": {"warrior": {"name": "战士"}},
        "settings": {
            "command_aliases": aliases or {
                "炼金": {"alias": "炼丹", "keep_original": False},
            },
        },
        "equip_engine": None,
    }


# ---------------------------------------------------------------------------
# 装配：register_shortcut_commands
# ---------------------------------------------------------------------------

def test_register_shortcut_commands():
    """SHC-05 ①：两个 CommandSpec（快捷解绑/快捷列表）注册进 Router。"""
    router = Router()
    register_shortcut_commands(router, make_context=lambda p: make_ctx())
    assert router.get(SHORTCUT_UNBIND_CMD) is not None
    assert router.get(SHORTCUT_LIST_CMD) is not None


def test_shortcut_without_make_context_raises():
    """make_context 缺省 → handler 调用抛 RuntimeError（【待接线】）。"""
    router = Router()
    register_shortcut_commands(router)
    with pytest.raises(RuntimeError):
        router.get(SHORTCUT_LIST_CMD).handler(parse("/快捷列表"))


def test_router_parse_integration():
    """/快捷解绑 /快捷列表 经 parse_command + 注册后 handler 可执行（完整链路，共享 ctx）。"""
    router = Router()
    ctx = make_ctx()
    register_shortcut_commands(router, make_context=lambda p: ctx)
    out = router.get(SHORTCUT_UNBIND_CMD).handler(parse("/快捷解绑 1"))
    assert out == "✅ 已解绑『1』"
    out2 = router.get(SHORTCUT_LIST_CMD).handler(parse("/快捷列表"))
    assert "【快捷（1/20）】" in out2


def test_regress_p2_5_list_fixed_subword_tpl12():
    """P2-5 回归（M6 批1B 审查）：`/快捷列表 自动` 固定子词被解析器抽走 → TPL-12，
    不静默渲染第 1 页。"""
    ctx = make_ctx()
    out = cmd_shortcut_list(parse("/快捷列表 自动"), ctx)
    assert out.startswith("❌ 指令不正确：/快捷列表 自动")


def test_regress_p2_4_shortcut_max_zero_unlimited():
    """P2-4 回归（M6 批1B 审查）：shortcut_max=0（不限，RUL-26）→ 列表头分母「不限」。"""
    ctx = make_ctx(shortcut_max=0)
    out = cmd_shortcut_list(parse("/快捷列表"), ctx)
    assert "【快捷（2/不限）】" in out


# ---------------------------------------------------------------------------
# 模板配置化（2026-08-31 用户拍板：消息模板不写死代码，走 shortcut_tpl 分区）
# ---------------------------------------------------------------------------

def test_shortcut_custom_templates_override():
    """覆盖：ctx[\"templates\"] 注入自定义模板 → 渲染用自定义（解绑成功/空表/列表行）。"""
    ctx = make_ctx(templates={
        "shortcut_unbind_ok": "✅ 已解绑自定义：{name}",
        "shortcut_list_row": "▶ {name} ← {command}",
    })
    # 解绑成功 → 自定义模板
    out = cmd_shortcut_unbind(parse("/快捷解绑 1"), ctx)
    assert out == "✅ 已解绑自定义：1"
    # 列表行 → 自定义模板
    out2 = cmd_shortcut_list(parse("/快捷列表"), ctx)
    assert "▶ 火球 ← 攻击3" in out2
    # 空表 → 自定义模板
    ctx2 = make_ctx(shortcuts={}, templates={"shortcut_empty": "暂无快捷，快去绑定吧"})
    assert cmd_shortcut_list(parse("/快捷列表"), ctx2) == "暂无快捷，快去绑定吧"


def test_shortcut_template_unknown_placeholder_kept():
    """白名单外占位符：模板含未登记占位符 → 渲染原样保留（不替换、不崩）。"""
    ctx = make_ctx(templates={
        "shortcut_unbind_missing": "❌ 没有绑定『{name}』{hint}",
    })
    out = cmd_shortcut_unbind(parse("/快捷解绑 不存在"), ctx)
    assert out == "❌ 没有绑定『不存在』{hint}"
