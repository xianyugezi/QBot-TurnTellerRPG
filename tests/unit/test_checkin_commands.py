"""签到指令接线单测（M4 批次5·路F3 · qbot_rpg/commands/checkin_commands.py）。

依据：m4_shared_contract.md §2.3+§3.4（/签到 结算/状态/补签；多表 loop/monthly/activity 并存一次
结算；连签独立计数 + 补签只计不补发裁决⑦；[签到:*] 表名限定键裁决⑧）+ docs/细化/细化_2b5_签到
引擎契约.md（§2.1 入口 /签到 /签到 补签；§2.3 结算管线；§2.4 汇总单条消息 + 5 条/页上限；§四
补签；§五 幂等 D-02「今天已签到」仍附进度）+ 细化_3d（TPL-08/TPL-12、5 条/页、页码夹取）+
2026-08-27 用户裁决②（页码夹取最后一页；0/负数/非数字 → TPL-12）+ 裁决⑦⑧。

集成口径：core/checkin.py（路F2 同批并行）尚未落盘，本测试以**契约忠实替身**驱动——注入
ctx["checkin_engine"] = FakeCheckinEngine（实现本层文件头声明的消费接口 checkin_today /
checkin_status / checkin_makeup / resolve_checkin_table，输出对齐 2b5 §2.3/§2.4/§四 口径），
断言命令层解析/渲染/路由/装配/错误全链路输出。路F2 落盘后替身可整体替换为真实引擎，断言不破。

覆盖：/签到 无参（多表各表奖励 + 连签/月累计进度 + 里程碑提示 + 5 条/页 + TPL-08 页脚）· 页码翻页 ·
超页夹取 + 已到最后一页（裁决②）· 0/负数/非数字 → TPL-12 · 幂等「今天已签到」仍附进度（D-02）·
/签到 状态（连签/月累计/本月已签日期列表 + 可翻页）· 补签（表名/序号/缺省=主表 loop/未开启/月上限/
表不存在值域文案；裁决⑦ 只计不补发提示透传）· 注册与解析接线 · 懒加载/待接线防御 · 页脚 TPL-08 逐字 ·
无装饰 emoji · 渲染/扁平化工具纯函数。
"""

from __future__ import annotations

import pytest

import qbot_rpg.commands.checkin_commands as cc
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

# ---------------------------------------------------------------------------
# 契约忠实替身：实现 core/checkin.py（路F2）消费接口，输出对齐 2b5 口径
# ---------------------------------------------------------------------------

TABLES = {
    "loop": {"id": "loop", "name": "常驻循环", "type": "loop"},
    "monthly": {"id": "monthly", "name": "月度签到", "type": "monthly"},
    "activity": {"id": "activity", "name": "xx庆典", "type": "activity"},
}

# 各表结算流水（2b5 §2.4：今日奖励 / 连签天数+进度 / 里程碑提示）
_TODAY_ROWS = {
    "loop": ["今日奖励：药水×2、金币+50、exp+20",
             "连签天数：8 天 ｜ 进度 8/31",
             "[连签里程碑达成] 钻石×1（连签 7 天）"],
    "monthly": ["今日奖励：金币+60、exp+25",
                "连签天数：3 天 ｜ 本月进度 15/31",
                "[月度累计达成] 强化石×3（本月签满 15 天）"],
    "activity": ["今日奖励（活动）×2 倍：药水×4",
                 "连签天数：5 天 ｜ 进度 5/14"],
}

# 各表状态流水（连签 / 月度累计（不要求连续）/ 本月已签日期列表）
_STATUS_ROWS = {
    "loop": ["连签天数：8 天",
             "本月已签：2026-08-01、2026-08-02、2026-08-03、2026-08-04、2026-08-05"],
    "monthly": ["连签天数：3 天",
                "月度累计：15/31 天",
                "本月已签：2026-08-01～2026-08-15"],
    "activity": ["连签天数：5 天",
                 "本月已签：2026-08-16～2026-08-20"],
}


class FakeCheckinEngine:
    """core/checkin.py 契约替身（见 checkin_commands.py 文件头消费接口）。"""

    def __init__(self, tables=None):
        self.tables = {k: dict(v) for k, v in (tables if tables is not None else TABLES).items()}

    def resolve_checkin_table(self, ctx, arg):
        """表名/序号/缺省(None=主表 loop，裁决⑧) → 表 id；找不到 → None。"""
        if not self.tables:
            return None
        if arg is None:
            return "loop" if "loop" in self.tables else next(iter(self.tables))
        s = str(arg)
        if s in self.tables:
            return s
        for tid, t in self.tables.items():
            if t.get("name") == s:
                return tid
        try:
            idx = int(s)
        except ValueError:
            return None
        if 1 <= idx <= len(self.tables):
            return list(self.tables)[idx - 1]
        return None

    def _sections(self, rows_map):
        """段标题 = 表名 + 类型标注（2b5 §2.4 活动表「xx庆典（活动）」口径）。"""
        out = []
        for tid, t in self.tables.items():
            title = t["name"]
            if t.get("type") == "activity":
                title = f"{title}（活动）"
            out.append({"title": title, "rows": rows_map[tid]})
        return out

    def checkin_today(self, ctx):
        """结算：跨天 → 发奖；同天 → 幂等「今天已签到」仍附进度（D-02，不重复发奖）。"""
        if ctx.get("checkin_idempotent"):
            return {"ok": True, "message": "今天已签到", "total": 8,
                    "sections": self._sections(_TODAY_ROWS)}
        return {"ok": True, "message": "✅ 今日签到完成", "total": 8,
                "sections": self._sections(_TODAY_ROWS)}

    def checkin_status(self, ctx):
        return {"ok": True, "message": "✅ 签到状态", "total": 7,
                "sections": self._sections(_STATUS_ROWS)}

    def checkin_makeup(self, table_id, ctx):
        """裁决⑦：只恢复 signed_days/streak，不补发所补日期 daily 奖励；里程碑不重复。"""
        t = self.tables.get(table_id)
        if t is None:
            return {"ok": False, "message": TPL_NO_TABLE}
        if ctx.get("checkin_makeup_enabled") is False:
            return {"ok": False, "message": "❌ 当前未开启补签"}
        if ctx.get("checkin_makeup_limit_hit"):
            return {"ok": False, "message": "❌ 本月补签已达上限"}
        return {"ok": True,
                "message": f"✅ 补签成功：{t['name']}（只恢复签到记录，不补发当日奖励，里程碑不重复）"}


def make_ctx(**over):
    """全字段玩家签到 ctx（checkin_engine 注入替身；每场景新造避免互污染）。"""
    base = {
        "name": "阿伟",
        "level": 5,
        "currencies": {"coins": 1000, "gems": 5},
        "inventory": {},
        "items": {},
        "settings": {},
        "now": 1787706000,  # 2026-08-26 09:00 UTC+8（确定性）
        "checkin_tables": {k: dict(v) for k, v in TABLES.items()},
        "checkin_state": {},
        "checkin_engine": FakeCheckinEngine(),
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
    """/签到 → 多表结算汇总：各表奖励 + 连签/月累计进度 + 里程碑提示；5 条/页 + TPL-08 页脚。"""
    out = cmd_checkin(parse("/签到"), make_ctx())
    assert out.startswith("✅ 今日签到完成")
    # 常驻循环表（表段头 + 今日奖励 + 连签进度 + 里程碑提示）
    assert "━━ 常驻循环 ━━" in out
    assert "今日奖励：药水×2、金币+50、exp+20" in out
    assert "连签天数：8 天 ｜ 进度 8/31" in out
    assert "[连签里程碑达成] 钻石×1（连签 7 天）" in out
    # 月度表（页 1 为 rows 4-5：今日奖励 + 连签进度；[月度累计达成] 在页 2）
    assert "━━ 月度签到 ━━" in out
    assert "今日奖励：金币+60、exp+25" in out
    assert "本月进度 15/31" in out
    # 5 条/页（m4 §2.2）：第 1 页 5 条 + TPL-08 页脚
    assert "— 第 1/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in out
    # 活动表在页 2（8 条流水 → 2 页），页 1 不出现
    assert "━━ xx庆典（活动） ━━" not in out


def test_checkin_today_page2():
    """/签到 2 → 第 2 页：月度表尾行 + 活动表段头 + 活动表流水 + 页脚。"""
    out = cmd_checkin(parse("/签到 2"), make_ctx())
    assert "[月度累计达成] 强化石×3（本月签满 15 天）" in out
    assert "━━ xx庆典（活动） ━━" in out
    assert "今日奖励（活动）×2 倍：药水×4" in out
    assert "连签天数：5 天 ｜ 进度 5/14" in out
    assert "— 第 2/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in out


def test_checkin_noarg_command_equivalence():
    """/签到（第 1 页）与 /签到 1 输出一致。"""
    assert cmd_checkin(parse("/签到"), make_ctx()) == cmd_checkin(parse("/签到 1"), make_ctx())


def test_checkin_clamp_last_page():
    """裁决②：/签到 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_checkin(parse("/签到 9"), make_ctx())
    assert "━━ xx庆典（活动） ━━" in out
    assert "连签天数：5 天 ｜ 进度 5/14" in out
    assert "（已到最后一页）" in out
    assert "— 第 2/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in out


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
    out = cmd_checkin(parse("/签到"), make_ctx(checkin_idempotent=True))
    assert out.startswith("今天已签到")
    assert "连签天数：8 天 ｜ 进度 8/31" in out   # 附进度
    assert "今日奖励：药水×2、金币+50、exp+20" in out  # 附流水（不重复发奖语义由引擎保证）
    assert "— 第 1/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in out


def test_checkin_today_engine_fail_message():
    """引擎 ok=False → 失败文案透传（如无生效签到表），不渲染段。"""
    class Boom:
        def checkin_today(self, ctx):
            return {"ok": False, "message": "❌ 今日无生效签到表"}
    out = cmd_checkin(parse("/签到"), make_ctx(checkin_engine=Boom()))
    assert out == "❌ 今日无生效签到表"


def test_checkin_today_message_only_no_rows():
    """引擎返回空流水 → 只输出 message（幂等且无流水边界）。"""
    class Empty:
        def checkin_today(self, ctx):
            return {"ok": True, "message": "✅ 今日签到完成", "total": 0, "sections": []}
    out = cmd_checkin(parse("/签到"), make_ctx(checkin_engine=Empty()))
    assert out == "✅ 今日签到完成"


# ---------------------------------------------------------------------------
# /签到 状态：连签/月累计/本月已签日期列表（可翻页）
# ---------------------------------------------------------------------------

def test_checkin_status_page1():
    """/签到 状态 → 连签/月累计/本月已签日期列表 + 5 条/页 + TPL-08 页脚（指令名=签到 状态）。"""
    out = cmd_checkin(parse("/签到 状态"), make_ctx())
    assert out.startswith("✅ 签到状态")
    assert "━━ 常驻循环 ━━" in out
    assert "连签天数：8 天" in out
    assert "本月已签：2026-08-01、2026-08-02、2026-08-03、2026-08-04、2026-08-05" in out
    assert "━━ 月度签到 ━━" in out
    assert "月度累计：15/31 天" in out
    # 页脚指令名 = 签到 状态（TPL-08 引导翻页）
    assert "— 第 1/2 页 · 共 7 条 · 输入 /签到 状态 页码 翻页 —" in out
    assert "━━ xx庆典（活动） ━━" not in out


def test_checkin_status_page2():
    """/签到 状态 2 → 活动表段头 + 活动表状态流水 + 页脚。"""
    out = cmd_checkin(parse("/签到 状态 2"), make_ctx())
    assert "━━ xx庆典（活动） ━━" in out
    assert "本月已签：2026-08-16～2026-08-20" in out
    assert "— 第 2/2 页 · 共 7 条 · 输入 /签到 状态 页码 翻页 —" in out


def test_checkin_status_clamp():
    """裁决②：/签到 状态 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_checkin(parse("/签到 状态 9"), make_ctx())
    assert "本月已签：2026-08-16～2026-08-20" in out
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
    """/签到 补签 loop → 引擎消息透传（裁决⑦：只恢复记录、不补发当日奖励、里程碑不重复）。"""
    out = cmd_checkin(parse("/签到 补签 loop"), make_ctx())
    assert out == "✅ 补签成功：常驻循环（只恢复签到记录，不补发当日奖励，里程碑不重复）"
    assert "不补发" in out  # 裁决⑦ 只计不补发提示由引擎合成、命令层透传


def test_checkin_makeup_by_table_name():
    """/签到 补签 月度签到 → 名称解析 → 月度表。"""
    out = cmd_checkin(parse("/签到 补签 月度签到"), make_ctx())
    assert out.startswith("✅ 补签成功：月度签到")


def test_checkin_makeup_default_main_loop():
    """/签到 补签（无表名）→ 缺省 = 主表 loop（裁决⑧ 缺省口径，工程补白 4）。"""
    out = cmd_checkin(parse("/签到 补签"), make_ctx())
    assert out == "✅ 补签成功：常驻循环（只恢复签到记录，不补发当日奖励，里程碑不重复）"


def test_checkin_makeup_by_seq():
    """/签到 补签 2 → 序号解析 → 第 2 表（月度）。"""
    out = cmd_checkin(parse("/签到 补签 2"), make_ctx())
    assert out.startswith("✅ 补签成功：月度签到")


def test_checkin_makeup_disabled():
    """2b5 §四 4.3：makeup 未开启 → 引擎「❌ 当前未开启补签」透传（不扣任何资源）。"""
    out = cmd_checkin(parse("/签到 补签 loop"), make_ctx(checkin_makeup_enabled=False))
    assert out == "❌ 当前未开启补签"


def test_checkin_makeup_monthly_limit():
    """2b5 §四 4.3：本月已补 ≥ max_per_month → 拒绝补签。"""
    out = cmd_checkin(parse("/签到 补签 loop"), make_ctx(checkin_makeup_limit_hit=True))
    assert out == "❌ 本月补签已达上限"


def test_checkin_makeup_no_table_value_domain():
    """/签到 补签 不存在 → 「❌ 没有这个签到表」（值域问题，命令合法，不走 TPL-12，工程补白 7）。"""
    out = cmd_checkin(parse("/签到 补签 不存在"), make_ctx())
    assert out == TPL_NO_TABLE
    assert "输入 /帮助" not in out


def test_checkin_makeup_compact():
    """紧凑双认：/签到补签loop / 签到补签 → 子词经紧凑解析仍正确路由。"""
    assert cmd_checkin(parse("/签到补签loop"), make_ctx()).startswith("✅ 补签成功：常驻循环")
    assert cmd_checkin(parse("/签到补签"), make_ctx()).startswith("✅ 补签成功：常驻循环")
    assert cmd_checkin(parse("/签到状态"), make_ctx()).startswith("✅ 签到状态")


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
    res = FakeCheckinEngine().checkin_today(make_ctx())
    p1 = render_summary(res, 1)
    headers1 = sum(1 for line in p1.splitlines() if line.startswith("━━"))
    assert headers1 == 2                   # 常驻循环 + 月度签到 两个段头
    assert "━━ 常驻循环 ━━" in p1
    assert "— 第 1/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in p1
    p2 = render_summary(res, 2)
    headers2 = sum(1 for line in p2.splitlines() if line.startswith("━━"))
    assert headers2 == 2                   # 月度（跨页重现）+ 活动 段头
    assert "━━ xx庆典（活动） ━━" in p2
    assert "— 第 2/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in p2


def test_render_summary_invalid_page_raises():
    """非法页码（0/负数/非数字）→ render_summary 抛 ValueError（壳层应先判 TPL-12）。"""
    res = FakeCheckinEngine().checkin_today(make_ctx())
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
    """resolve_checkin_table_arg：表 id / 名称 / 序号 / 缺省 → 表 id；None=找不到。"""
    eng = FakeCheckinEngine()
    ctx = make_ctx()
    assert cc.resolve_checkin_table_arg(ctx, eng, None) == "loop"
    assert cc.resolve_checkin_table_arg(ctx, eng, "monthly") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, eng, "月度签到") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, eng, "2") == "monthly"
    assert cc.resolve_checkin_table_arg(ctx, eng, "不存在") is None
    assert cc.resolve_checkin_table_arg(ctx, eng, "99") is None


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
    """懒加载回退：ctx 未注入 checkin_engine → import_module('qbot_rpg.core.checkin')（路F2 落盘后）。"""
    fake = FakeCheckinEngine()
    real_import = cc.importlib.import_module

    def fake_import(name):
        if name == "qbot_rpg.core.checkin":
            return fake
        return real_import(name)

    monkeypatch.setattr(cc.importlib, "import_module", fake_import)
    ctx = make_ctx()
    ctx.pop("checkin_engine")
    out = cmd_checkin(parse("/签到"), ctx)
    assert out.startswith("✅ 今日签到完成")


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
    out = cmd_checkin(parse("/签到"), make_ctx())
    assert "— 第 1/2 页 · 共 8 条 · 输入 /签到 页码 翻页 —" in out
    out2 = cmd_checkin(parse("/签到 状态"), make_ctx())
    assert "— 第 1/2 页 · 共 7 条 · 输入 /签到 状态 页码 翻页 —" in out2


def test_no_decorative_emoji():
    """3d §四 D-01：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记允许；━━ 段头为排版符非 emoji）。"""
    ctx = make_ctx()
    outputs = [
        cmd_checkin(parse("/签到"), ctx),
        cmd_checkin(parse("/签到 2"), ctx),
        cmd_checkin(parse("/签到 9"), ctx),
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
