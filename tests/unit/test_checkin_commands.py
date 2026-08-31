"""签到指令接线单测（M4 批次5·路F3 · qbot_rpg/commands/checkin_commands.py）。

依据：m4_shared_contract.md §2.3+§3.4（/签到 结算/状态/补签；多表 loop/monthly/activity 并存一次
结算；连签独立计数 + 补签只计不补发裁决⑦；[签到:*] 表名限定键裁决⑧）+ docs/细化/细化_2b5_签到
引擎契约.md（§2.1 入口 /签到 /签到 补签；§2.3 结算管线；§2.4 汇总单条消息 + 5 条/页上限；§四
补签；§五 幂等 D-02「今天已签到」仍附进度）+ 细化_3d（TPL-08/TPL-12、5 条/页、页码夹取）+
2026-08-27 用户裁决②（页码夹取最后一页；0/负数/非数字 → TPL-12）+ 裁决⑦⑧。

集成口径：审查_M4实现_批次2_jspace.md P0-1/P1-1 修复——本测试**注入真实 core/checkin 引擎**
（对齐 test_quest_commands 模式，删除原「契约忠实替身」FakeCheckinEngine：替身接口与真实引擎
不可互换、曾掩盖 P0-1），断言命令层解析/渲染/路由/装配/错误全链路消费真实引擎输出。
命令层正文按 checkin_do/checkin_state 的 tables 重建（纯文本，去 📅/⚠ 装饰 emoji）。

覆盖：/签到 无参（多表各表奖励 + 连签/月累计进度 + 5 条/页 + TPL-08 页脚）· 页码翻页 · 超页夹取 +
已到最后一页（裁决②）· 0/负数/非数字 → TPL-12 · 幂等「今天已签到」仍附进度（D-02）· /签到 状态
（连签/本月累计/今日已签 + 可翻页）· 补签（表 id/类型名/序号/名称/缺省=主表 loop/未开启/月上限/
表不存在值域文案；裁决⑦ 只计不补发提示透传）· 注册与解析接线 · 懒加载/待接线防御 · 页脚 TPL-08
逐字 · 无装饰 emoji · 渲染/扁平化工具纯函数。
"""

from __future__ import annotations

import datetime

import pytest

import qbot_rpg.commands.checkin_commands as cc
import qbot_rpg.core.checkin as real_checkin
from qbot_rpg.commands.checkin_commands import (
    CHECKIN_CMD,
    SUB_MAKEUP,
    SUB_STATUS,
    TPL_NO_TABLE,
    cmd_checkin,
    flatten_sections,
    register_checkin_commands,
    render_summary,
    table_arg_of,
)
from qbot_rpg.commands.parsers import ParsedCommand, parse_command
from qbot_rpg.commands.router import Router

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))
NOW = int(datetime.datetime(2026, 8, 26, 12, 0, 0, tzinfo=_TZ_UTC8).timestamp())  # 2026-08-26 12:00 UTC+8

# ---------------------------------------------------------------------------
# 真实引擎驱动：表定义 + 玩家 ctx（对齐 core/checkin.py 契约；注入真实引擎模块）
# ---------------------------------------------------------------------------

ITEMS = {
    "药水": {"id": "药水", "name": "药水", "quality": "normal"},
    "钻石": {"id": "钻石", "name": "钻石", "quality": "rare"},
    "强化石": {"id": "强化石", "name": "强化石", "quality": "rare"},
}

SETTINGS = {"refresh_time": "05:00", "currencies": [{"id": "coins"}, {"id": "gem"}]}

TABLES = {
    "loop": {"id": "loop", "name": "常驻循环", "type": "loop",
             "period": {"cycle_days": 7, "reset_on_break": True},
             "rewards": {"daily": [{"day": 1, "items": [{"id": "药水", "count": 2}],
                                    "coins": 50, "exp": 20}],
                          "streak": [{"days": 7, "items": [{"id": "钻石", "count": 1}], "gem": 3}]},
             "makeup": {"enabled": True, "cost": {"coins": 100}, "max_per_month": 3},
             "bonus": None},
    "monthly": {"id": "monthly", "name": "月度签到", "type": "monthly",
                "period": {"reset_on_break": True},
                "rewards": {"daily": [{"day": 1, "coins": 60, "exp": 25}],
                             "monthly_total": [{"days": 15, "items": [{"id": "强化石", "count": 3}]}]},
                "makeup": {"enabled": False}},
    "activity": {"id": "activity", "name": "xx庆典", "type": "activity",
                 "period": {"start": "2026-08-01 00:00", "end": "2026-08-31 23:59",
                            "cycle_days": 14},
                 "rewards": {"daily": [{"day": 1, "items": [{"id": "药水", "count": 4}],
                                        "coins": 30}]},
                 "makeup": {"enabled": False}},
}


def make_ctx(**over):
    """全字段玩家签到 ctx（注入真实 core/checkin 模块；每场景新造避免互污染）。"""
    base = {
        "name": "阿伟",
        "level": 5,
        "settings": SETTINGS,
        "checkin_tables": {k: dict(v) for k, v in TABLES.items()},
        "checkin_state": {},
        "longline_counters": {},
        "event_counts": {},
        "inventory": {},
        "currencies": {"coins": 1000, "gem": 5},
        "exp": 0,
        "reputation_state": {},
        "items": ITEMS,
        "add_item": lambda item_id, count, bound=True: True,
        "remove_item": lambda item_id, count: True,
        "count_item": lambda item_id: 0,
        "now": NOW,
        "checkin_engine": real_checkin,  # 审查批次2 P0-1：真实引擎注入，替身已删
    }
    base.update(over)
    return base


def parse(raw: str) -> ParsedCommand:
    """parse_command 封装（默认白名单已含 签到，parsers.DEFAULT_WHITELIST）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# /签到 无参：今日结算汇总（多表 + 5 条/页 + TPL-08 页脚）
# ---------------------------------------------------------------------------

def test_checkin_noarg_today_page1():
    """/签到 → 多表结算汇总：各表奖励 + 连签进度；5 条/页 + TPL-08 页脚（审查批次2 P0-1 真实引擎）。"""
    out = cmd_checkin(parse("/签到"), make_ctx())
    assert out.startswith("✅ 今日签到完成")
    # 常驻循环表（表段头 + 今日奖励 + 连签进度）
    assert "━━ 常驻循环（常驻循环） ━━" in out
    assert "今日奖励：药水×2、50 coins、exp20" in out
    assert "连签天数：1 天 ｜ 进度 1/7" in out
    # 月度表（页 1 为 rows 4-5：今日奖励 + 兜底提示 + 连签进度）
    assert "━━ 月度签到（月度签到） ━━" in out
    assert "今日奖励：60 coins、exp25" in out
    # 5 条/页（m4 §2.2）：第 1 页 5 条 + TPL-08 页脚
    assert "当前页：1/2" in out
    # 活动表在页 2（8 条流水 → 2 页），页 1 不出现
    assert "━━ xx庆典（活动） ━━" not in out


def test_checkin_today_page2():
    """/签到 2 → 第 2 页：活动表段头 + 活动表流水 + 页脚。"""
    out = cmd_checkin(parse("/签到 2"), make_ctx())
    assert "━━ xx庆典（活动） ━━" in out
    assert "今日奖励：药水×4、30 coins" in out
    assert "连签天数：1 天 ｜ 进度 26/14" in out
    assert "当前页：2/2" in out


def test_checkin_noarg_command_equivalence():
    """/签到（第 1 页）与 /签到 1 输出一致。"""
    assert cmd_checkin(parse("/签到"), make_ctx()) == cmd_checkin(parse("/签到 1"), make_ctx())


def test_checkin_clamp_last_page():
    """裁决②：/签到 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_checkin(parse("/签到 9"), make_ctx())
    assert "━━ xx庆典（活动） ━━" in out
    assert "连签天数：1 天 ｜ 进度 26/14" in out
    assert "（已到最后一页）" in out
    assert "当前页：2/2" in out


@pytest.mark.parametrize("raw, fragment", [
    ("/签到 0", "/签到 0"),
    ("/签到 -1", "/签到 -1"),
    ("/签到 abc", "/签到 abc"),
    ("/签到 列表", "/签到 列表"),  # 非子词亦非页码 → TPL-12
])
def test_checkin_invalid_input_tpl12(raw, fragment):
    """裁决② + 3d §5.1：0/负数/非数字/未知子词 → TPL-12 统一报错。"""
    out = cmd_checkin(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{fragment}。输入 /帮助 查看可用指令。"


def test_checkin_idempotent_still_shows_progress():
    """2b5 §五 D-02：同日重复 /签到 → 「今天已签到」，不重复发奖但仍附各表当前连签+进度。"""
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    out = cmd_checkin(parse("/签到"), ctx)
    assert out.startswith("今天已签到（重复指令，未重复发放）")
    assert "连签天数：1 天 ｜ 进度 1/7" in out   # 附进度
    assert "今天已签到（不重复发奖）" in out    # 各表幂等行（不重复发奖语义由引擎保证）
    assert "当前页：1/2" in out


def test_checkin_today_engine_fail_message():
    """引擎 ok=False → 失败文案透传（如无生效签到表），不渲染段。"""
    class Boom:
        def checkin_do(self, ctx):
            return {"ok": False, "message": "❌ 今日无生效签到表"}
    out = cmd_checkin(parse("/签到"), make_ctx(checkin_engine=Boom()))
    assert out == "❌ 今日无生效签到表"


def test_checkin_today_message_only_no_rows():
    """引擎返回空流水 → 只输出 message（幂等且无流水边界）。"""
    class Empty:
        def checkin_do(self, ctx):
            return {"ok": True, "tables": []}
    out = cmd_checkin(parse("/签到"), make_ctx(checkin_engine=Empty()))
    assert out == "✅ 今日签到完成"


# ---------------------------------------------------------------------------
# /签到 状态：连签/本月累计/今日已签（可翻页）
# ---------------------------------------------------------------------------

def test_checkin_status_page1():
    """/签到 状态 → 连签/本月累计/今日已签 + 5 条/页 + TPL-08 页脚（指令名=签到 状态）。"""
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    out = cmd_checkin(parse("/签到 状态"), ctx)
    assert out.startswith("✅ 签到状态")
    assert "━━ 常驻循环（常驻循环） ━━" in out
    assert "连签天数：1 天" in out
    assert "本月累计：1 天" in out
    assert "今日已签：是" in out
    assert "补签：0/3" in out
    assert "━━ 月度签到（月度签到） ━━" in out
    # 页脚指令名 = 签到 状态（TPL-08 引导翻页）
    assert "当前页：1/2" in out
    assert "━━ xx庆典（活动） ━━" not in out


def test_checkin_status_page2():
    """/签到 状态 2 → 活动表段头 + 活动表状态流水 + 页脚。"""
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    out = cmd_checkin(parse("/签到 状态 2"), ctx)
    assert "━━ xx庆典（活动） ━━" in out
    assert "今日已签：是" in out
    assert "当前页：2/2" in out


def test_checkin_status_clamp():
    """裁决②：/签到 状态 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    out = cmd_checkin(parse("/签到 状态 9"), ctx)
    assert "━━ xx庆典（活动） ━━" in out
    assert "（已到最后一页）" in out


@pytest.mark.parametrize("raw", ["/签到 状态 0", "/签到 状态 -2", "/签到 状态 abc"])
def test_checkin_status_invalid_page_tpl12(raw):
    """裁决②：状态页码 0/负数/非数字 → TPL-12。"""
    out = cmd_checkin(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：/签到 状态 ")


# ---------------------------------------------------------------------------
# /签到 补签 <表名>（裁决⑦ 只计不补发提示透传；缺省=主表 loop）
# ---------------------------------------------------------------------------

def test_checkin_makeup_by_table_id():
    """/签到 补签 loop → 类型名解析 → 引擎消息透传（裁决⑦：只计不补发）。"""
    out = cmd_checkin(parse("/签到 补签 loop"), make_ctx())
    assert out == "✅ 补签成功（currency）· 只计不补发"
    assert "不补发" in out  # 裁决⑦ 只计不补发提示由引擎合成、命令层透传


def test_checkin_makeup_by_table_name():
    """/签到 补签 月度签到 → 名称解析 → 月度表（makeup 未开启 → 引擎文案透传）。"""
    out = cmd_checkin(parse("/签到 补签 月度签到"), make_ctx())
    assert out == "❌ 当前未开启补签"


def test_checkin_makeup_default_main_loop():
    """/签到 补签（无表名）→ 缺省 = 主表 loop（裁决⑧ 缺省口径，工程补白 4；P0-1：直接传 None 引擎解析）。"""
    out = cmd_checkin(parse("/签到 补签"), make_ctx())
    assert out == "✅ 补签成功（currency）· 只计不补发"


def test_checkin_makeup_by_seq():
    """/签到 补签 2 → 序号解析 → 第 2 表（月度，makeup 未开启）。"""
    out = cmd_checkin(parse("/签到 补签 2"), make_ctx())
    assert out == "❌ 当前未开启补签"


def test_checkin_makeup_disabled():
    """2b5 §四 4.3：makeup 未开启 → 引擎「❌ 当前未开启补签」透传（不扣任何资源）。"""
    out = cmd_checkin(parse("/签到 补签 monthly"), make_ctx())
    assert out == "❌ 当前未开启补签"


def test_checkin_makeup_monthly_limit():
    """2b5 §四 4.3：本月已补 ≥ max_per_month → 拒绝补签（跨月归一口径引擎侧单测覆盖）。"""
    ctx = make_ctx(checkin_state={
        "loop": {"makeup_month": "2026-08", "makeup_used": 3, "signed_days": []},
    })
    out = cmd_checkin(parse("/签到 补签 loop"), ctx)
    assert out == "❌ 本月补签已达上限 3 次"


def test_checkin_makeup_no_table_value_domain():
    """/签到 补签 不存在 → 「❌ 没有这个签到表」（值域问题，命令合法，不走 TPL-12，工程补白 7）。"""
    out = cmd_checkin(parse("/签到 补签 不存在"), make_ctx())
    assert out == TPL_NO_TABLE
    assert "输入 /帮助" not in out


def test_checkin_makeup_compact():
    """紧凑双认：/签到补签loop / 签到补签 → 子词经紧凑解析仍正确路由。"""
    assert cmd_checkin(parse("/签到补签loop"), make_ctx()) == "✅ 补签成功（currency）· 只计不补发"
    assert cmd_checkin(parse("/签到补签"), make_ctx()) == "✅ 补签成功（currency）· 只计不补发"
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    assert cmd_checkin(parse("/签到状态"), ctx).startswith("✅ 签到状态")


# ---------------------------------------------------------------------------
# 缺参 / 超参 / 解析错误 → TPL-12
# ---------------------------------------------------------------------------

def test_checkin_parse_error_tpl12():
    """超参（3 个位置参数）→ 解析 error → TPL-12。"""
    out = cmd_checkin(parse("/签到 状态 1 2"), make_ctx())
    assert out.startswith("❌ 指令不正确：")
    assert "输入 /帮助 查看可用指令。" in out


# ---------------------------------------------------------------------------
# 渲染 / 工具（纯函数）
# ---------------------------------------------------------------------------

def test_render_summary_pagination():
    """"5 条/页边界：8 条 → 页 1 五条 + 页脚，页 2 三条 + 段头 + 页脚（裁决② 夹取已单测）。"""
    res = real_checkin.checkin_do(make_ctx())
    p1 = render_summary(res, 1)
    headers1 = sum(1 for line in p1.splitlines() if line.startswith("━━"))
    assert headers1 == 2                   # 常驻循环 + 月度签到 两个段头
    assert "━━ 常驻循环（常驻循环） ━━" in p1
    assert "当前页：1/2" in p1
    p2 = render_summary(res, 2)
    headers2 = sum(1 for line in p2.splitlines() if line.startswith("━━"))
    assert headers2 == 1                   # 活动 段头（页 2 仅活动流水）
    assert "━━ xx庆典（活动） ━━" in p2
    assert "当前页：2/2" in p2


def test_render_summary_invalid_page_raises():
    """非法页码（0/负数/非数字）→ render_summary 抛 ValueError（壳层应先判 TPL-12）。"""
    res = real_checkin.checkin_do(make_ctx())
    for bad in (0, -1, "abc"):
        with pytest.raises(ValueError):
            render_summary(res, bad)


def test_flatten_sections_pure():
    """"flatten_sections：sections → (标题, 行) 有序对（空/空白行跳过；非段条目忽略）。"""
    res = {"sections": [
        {"title": "A", "rows": ["r1", "r2"]},
        {"title": "", "rows": ["x"]},
        {"title": "B", "rows": ["", "  "]},
        {"rows": ["z"]},
        "junk",
    ]}
    pairs = flatten_sections(res)
    assert pairs == [("A", "r1"), ("A", "r2"), ("", "x"), ("", "z")]
    # 空白行跳过（B 段两行均空白 → 不产出）；非 Mapping 段忽略
    assert all(isinstance(p, tuple) and len(p) == 2 for p in pairs)
    assert ("B", "") not in pairs and ("B", "  ") not in pairs


def test_table_arg_of():
    """table_arg_of：取第 index 位置参数（补签表名）；越界 → None = 缺省主表 loop。"""
    assert table_arg_of(parse("/签到 补签 loop")) == "loop"
    assert table_arg_of(parse("/签到 补签")) is None
    assert table_arg_of(parse("/签到 状态 2"), 0) == "状态"


def test_resolve_checkin_table_arg():
    """resolve_checkin_table_arg：表 id / 类型名 / 名称 / 序号 → 表 id；None=找不到；
    arg=None → None（缺省主表由引擎按 None 解析，审查批次2 P0-1）。"""
    ctx = make_ctx()
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, None) is None
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "loop") == "loop"
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "monthly") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "月度签到") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "2") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "不存在") is None
    assert cc.resolve_checkin_table_arg(ctx, real_checkin, "99") is None


# ---------------------------------------------------------------------------
# 接线：Router 注册 / 解析集成 / 懒加载 / 待接线防御
# ---------------------------------------------------------------------------

def test_register_checkin_commands():
    """批次6/7 装配入口：注册 签到 一条 CommandSpec（可快捷白名单）。"""
    router = Router()
    register_checkin_commands(router, make_context=lambda p: make_ctx())
    assert router.has(CHECKIN_CMD)
    assert router.get(CHECKIN_CMD).whitelisted


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入的显式错误）。"""
    router = Router()
    register_checkin_commands(router)
    with pytest.raises(RuntimeError):
        router.get(CHECKIN_CMD).handler(parse("/签到"))


def test_lazy_import_engine_fallback(monkeypatch):
    """懒加载回退：ctx 未注入 checkin_engine → import_module('qbot_rpg.core.checkin') 真实模块。"""
    ctx = make_ctx()
    ctx.pop("checkin_engine")
    out = cmd_checkin(parse("/签到"), ctx)
    assert out.startswith("✅ 今日签到完成")
    assert "今日奖励：药水×2、50 coins、exp20" in out


def test_engine_missing_raises_wiring_pending(monkeypatch):
    """【待接线】防御：引擎缺失（core.checkin 不可导入 + 未注入）→ RuntimeError 显式标注。"""
    def boom(name):
        raise ImportError(f"no module {name}")
    monkeypatch.setattr(cc.importlib, "import_module", boom)
    with pytest.raises(RuntimeError) as ei:
        cmd_checkin(parse("/签到"), make_ctx(checkin_engine=None))
    assert "【待接线】" in str(ei.value)
    assert "core/checkin.py" in str(ei.value)


def test_parse_command_integration():
    """解析接线：/签到 各形态经 parsers.parse_command 产出结构化字段。"""
    p = parse("/签到")
    assert p.command == "签到" and p.args == []
    p = parse("/签到 状态")
    assert p.command == "签到" and p.args == ["状态"]
    p = parse("/签到 状态 2")
    assert p.command == "签到" and p.args == ["状态", "2"]
    p = parse("/签到 补签 loop")
    assert p.command == "签到" and p.args == ["补签", "loop"]
    p = parse("/签到补签loop")
    assert p.command == "签到" and p.args == ["补签loop"] and p.compact is True
    p = parse("/签到 2")
    assert p.command == "签到" and p.args == ["2"]


def test_subword_constants():
    """子词常量与缺省表名语义（裁决⑧ 缺省=主表 loop）。"""
    assert SUB_STATUS == "状态" and SUB_MAKEUP == "补签"
    assert cc.SUBWORDS == (SUB_STATUS, SUB_MAKEUP)


def test_footer_tpl08_exact():
    """3d TC-12：页脚 TPL-08 逐字（无自造变体）。"""
    ctx = make_ctx()
    out = cmd_checkin(parse("/签到"), ctx)
    assert "当前页：1/2" in out
    out2 = cmd_checkin(parse("/签到 状态"), ctx)
    assert "当前页：1/2" in out2


def test_no_decorative_emoji():
    """3d §四 D-01：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记允许；━━ 段头为排版符非 emoji）。
    审查批次2 P0-1：引擎 message 的 📅/⚠ 不再透传为正文（正文按 tables 纯文本重建）。"""
    ctx = make_ctx()
    cmd_checkin(parse("/签到"), ctx)
    outputs = [
        cmd_checkin(parse("/签到"), make_ctx()),
        cmd_checkin(parse("/签到 2"), make_ctx()),
        cmd_checkin(parse("/签到 9"), make_ctx()),
        cmd_checkin(parse("/签到 状态"), ctx),
        cmd_checkin(parse("/签到 状态 2"), ctx),
        cmd_checkin(parse("/签到 补签 loop"), ctx),
        cmd_checkin(parse("/签到 0"), ctx),
    ]
    banned = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")
    for text in outputs:
        for ch in text:
            assert ch not in banned, f"命中禁用装饰 emoji：{ch} in {text!r}"
            assert ch in ("✅", "❌") or not (0x1F000 <= ord(ch) <= 0x1FAFF), \
                f"命中未登记 emoji：{ch} in {text!r}"


# ---------------------------------------------------------------------------
# 模板配置化（2026-08-31 用户拍板：消息模板配置化，不写死代码）
# ---------------------------------------------------------------------------

def test_checkin_templates_override_via_ctx():
    """内容包覆盖：ctx['templates'] 覆盖 checkin_tpl 默认模板 → 渲染处 tpl_of 生效。"""
    over = {
        "checkin_today_done": "✅ 签到完成（自定义）",
        "checkin_section_header": "══ {title} ══",
        "checkin_section_title": "{name}｜{type}",
        "checkin_progress_line": "连签：{streak} 天（进度 {cur}/{total}）",
    }
    out = cmd_checkin(parse("/签到"), make_ctx(templates=over))
    assert out.startswith("✅ 签到完成（自定义）")
    assert "══ 常驻循环｜常驻循环 ══" in out
    assert "连签：1 天（进度 1/7）" in out


def test_checkin_templates_default_when_no_ctx_templates():
    """无 ctx['templates'] → tpl_of 回落内置默认（逐字对齐既有输出）。"""
    out = cmd_checkin(parse("/签到"), make_ctx())
    assert "━━ 常驻循环（常驻循环） ━━" in out
    assert "连签天数：1 天 ｜ 进度 1/7" in out


def test_checkin_tpl_placeholder_whitelist_coverage():
    """checkin_tpl 白名单：默认模板占位符 ⊆ 白名单（防内容包拼错 key 引入缺键不替换）。"""
    import re
    from qbot_rpg.core.templates.checkin_tpl import (
        DEFAULT_TEMPLATES as _CHK_TPL,
        PLACEHOLDER_WHITELIST as _CHK_WH,
    )
    pat = re.compile(r"\{([a-zA-Z0-9_]+)\}")
    for key, tpl in _CHK_TPL.items():
        used = set(pat.findall(str(tpl)))
        assert used <= _CHK_WH.get(key, set()), f"{key}: 占位符 {used} 超出白名单"
