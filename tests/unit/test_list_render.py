"""列表分页渲染单测（M4 批次1·路B2 · qbot_rpg/core/message_format/list_render.py）。

依据：m4_shared_contract §2.2（5 条/页 + 页脚 TPL-08 + 页码夹取 + emoji 纪律）
     + 细化_3d_消息模板规范 §二（TC-07~TC-12 列表分页）/ §四（emoji 纪律 TC-18）
     + 2026-08-27 用户裁决②（超总页数 → 夹取最后一页 + 「已到最后一页」；0/负数/非数字 → TPL-12）
     + 细化_4f RUL-16/RUL-18（页码夹取 / 页脚）。

覆盖：5 条/页切片（TC-07）· 单页无页脚（TC-11）· 页脚逐字 TPL-08（TC-12）· 裁决② 夹取 + 提示 ·
0/负数/非数字 → invalid（壳层转 TPL-12，TC-09/10）· 空列表 · 装饰 emoji 扫描（TC-18）·
条目行 TPL-07 · 页码输入串化（TC-10 页码 abc）· per_page 非法拒绝。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.message_format.list_render import (
    DEFAULT_PAGE_SIZE,
    LAST_PAGE_HINT,
    ListPage,
    PageResolution,
    page_items,
    render_footer,
    render_item_line,
    render_list_page,
    render_list_page_text,
    resolve_page,
)

# 3d §4.2 装饰性 emoji 禁用清单（程序化扫描锚点）
BANNED = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
ALLOWED = "✅❌"

ITEMS14 = [f"物品{i}" for i in range(1, 15)]  # 14 条 → 3 页


# ---------------------------------------------------------------------------
# 页脚 TPL-08（TC-12 逐字校验 + 单页无页脚 TC-11）
# ---------------------------------------------------------------------------

def test_footer_tpl08_exact():
    """TC-12：页脚逐字 = TPL-08，无自造变体；{页码} 为固定「页码」字样。"""
    assert render_footer(2, 3, 14, "背包") == "— 第 2/3 页 · 共 14 条 · 输入 /背包 页码 翻页 —"


def test_footer_single_page_empty():
    """TC-11：单页（总页数=1）不输出页脚；无指令名也不输出（3d §2.3 防刷屏）。"""
    assert render_footer(1, 1, 3, "背包") == ""
    assert render_footer(1, 3, 14, "") == ""


def test_footer_uses_command_verbatim():
    """页脚指令名透传调用方指令（如 /商店）。"""
    assert "输入 /商店 页码 翻页" in render_footer(1, 2, 9, "商店")


# ---------------------------------------------------------------------------
# 条目行 TPL-07
# ---------------------------------------------------------------------------

def test_item_line_tpl07():
    assert render_item_line(1, "铁剑", "攻击+12") == "1. 铁剑 攻击+12"
    assert render_item_line(2, "疗伤药") == "2. 疗伤药"


# ---------------------------------------------------------------------------
# 页码解析（裁决②）
# ---------------------------------------------------------------------------

def test_resolve_page_valid():
    res = resolve_page(2, 14)  # 14 条 → 3 页
    assert res == PageResolution(page=2, total_pages=3, total=14, invalid=False, clamped=False)


def test_resolve_page_clamp_over_total():
    """裁决②：页码超总页数 → 夹取最后一页 + clamped 标记（提示「已到最后一页」）。"""
    res = resolve_page(9, 14)  # 14 条 → 3 页，请求 9
    assert res.clamped is True and res.invalid is False
    assert res.page == 3 and res.total_pages == 3 and res.total == 14


def test_resolve_page_invalid_zero_negative_nonnum():
    """裁决② + 3d §2.2：0/负数/非数字 → invalid（壳层转 TPL-12），不静默兜底。"""
    for bad in (0, -1, "0", "-3", "abc", "", "  ", 1.5):
        res = resolve_page(bad, 14)
        assert res.invalid is True, f"应判非法：{bad!r}"
        assert res.page is None


def test_resolve_page_str_digits_ok():
    """页码最后一个整数参数（3d §2.2）：字符串数字 / 空白容忍 → 合法。"""
    assert resolve_page("2", 14).page == 2
    assert resolve_page(" 2 ", 14).page == 2
    assert resolve_page("14", 14).page == 3  # 恰好超总页数 → 夹取


def test_resolve_page_bool_rejected():
    """布尔值不视为合法页码（True/False 非数字）。"""
    assert resolve_page(True, 14).invalid is True
    assert resolve_page(False, 14).invalid is True


def test_resolve_page_empty_list_single_page():
    """空列表：总页数=1（单页空列表，同 panel_render 口径），page=1 合法。"""
    res = resolve_page(1, 0)
    assert res.page == 1 and res.total_pages == 1 and res.total == 0 and not res.invalid
    # 空列表请求超大页码 → 夹取到第 1 页
    assert resolve_page(5, 0).clamped is True


def test_resolve_page_per_page_zero_rejected():
    with pytest.raises(ValueError):
        resolve_page(1, 10, per_page=0)


# ---------------------------------------------------------------------------
# 5 条/页切片（TC-07）
# ---------------------------------------------------------------------------

def test_page_items_five_per_page():
    assert DEFAULT_PAGE_SIZE == 5  # 3d D-02
    page1 = page_items(ITEMS14, 1)
    assert len(page1) == 5 and page1[0] == "物品1" and page1[-1] == "物品5"
    assert page_items(ITEMS14, 3) == ["物品11", "物品12", "物品13", "物品14"]
    # 夹取：请求超页 → 返回最后一页内容
    assert page_items(ITEMS14, 99) == page_items(ITEMS14, 3)


def test_page_items_invalid_raises():
    """非法页码（0/负数/非数字）→ 抛 ValueError（壳层应转 TPL-12，本函数不接非法页码）。"""
    for bad in (0, -1, "abc", None):
        with pytest.raises(ValueError):
            page_items(ITEMS14, bad)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 整页渲染（条目行 + 夹取提示 + 页脚）
# ---------------------------------------------------------------------------

def test_render_list_page_first_page():
    lp = render_list_page(ITEMS14, 1, "背包")
    assert isinstance(lp, ListPage)
    assert lp.page == 1 and lp.total_pages == 3 and lp.total == 14
    assert len(lp.lines) == 5
    assert lp.lines[0] == "1. 物品1" and lp.lines[-1] == "5. 物品5"
    assert lp.hint == "" and lp.clamped is False
    assert lp.footer == "— 第 1/3 页 · 共 14 条 · 输入 /背包 页码 翻页 —"


def test_render_list_page_clamped_with_hint():
    """裁决②：超页请求 → 渲染最后一页 + 「已到最后一页」提示 + 页脚页码为夹取后页码。"""
    lp = render_list_page(ITEMS14, 9, "背包")
    assert lp.clamped is True and lp.page == 3
    assert lp.hint == LAST_PAGE_HINT == "（已到最后一页）"
    assert lp.lines[0] == "1. 物品11"
    assert lp.footer == "— 第 3/3 页 · 共 14 条 · 输入 /背包 页码 翻页 —"


def test_render_list_page_text_composition():
    text = render_list_page_text(ITEMS14, 1, "商店")
    lines = text.split("\n")
    assert len(lines) == 6  # 5 条 + 页脚
    assert lines[-1] == "— 第 1/3 页 · 共 14 条 · 输入 /商店 页码 翻页 —"
    # 夹取时：条目行 + 提示 + 页脚
    clamped = render_list_page_text(ITEMS14, 99, "商店").split("\n")
    assert clamped[-2] == "（已到最后一页）" and clamped[-1] == "— 第 3/3 页 · 共 14 条 · 输入 /商店 页码 翻页 —"


def test_render_list_page_single_page_no_footer():
    lp = render_list_page(["药水", "铁剑", "粗布"], 1, "背包")
    assert lp.total_pages == 1 and lp.footer == "" and lp.hint == ""
    assert len(lp.lines) == 3


def test_render_list_page_custom_formatter():
    """系统可注入自定义条目行（TPL-07 骨架精神，各系统业务自管）。"""
    rows = [("铁剑", "攻击+12"), ("药水", "×10")]
    lp = render_list_page(rows, 1, "背包", formatter=lambda i, r: render_item_line(i, r[0], r[1]))
    assert lp.lines == ("1. 铁剑 攻击+12", "2. 药水 ×10")


def test_render_list_page_invalid_raises():
    with pytest.raises(ValueError):
        render_list_page(ITEMS14, 0, "背包")


# ---------------------------------------------------------------------------
# emoji 纪律（TC-18：装饰 emoji 扫描）
# ---------------------------------------------------------------------------

def _collect_outputs():
    outs = [
        render_footer(2, 3, 14, "背包"),
        render_item_line(1, "铁剑", "攻击+12"),
        LAST_PAGE_HINT,
        render_list_page_text(ITEMS14, 1, "背包"),
        render_list_page_text(ITEMS14, 99, "背包"),
    ]
    return outs


def test_no_banned_decorative_emoji():
    """TC-18：本模块全部渲染输出不命中装饰 emoji 禁用清单（✅/❌ 也不在列表骨架中）。"""
    for out in _collect_outputs():
        assert not any(ch in out for ch in BANNED), f"命中禁用 emoji：{out}"
        assert "✅" not in out and "❌" not in out  # 列表骨架为纯文本（功能性标记不属列表）
