"""message_format 纯字符串契约（细化_3a §5 / 细化_3d 部分 TC）。

P1-4（M0 复查）：原 docstring 声称覆盖 TC-12~19 过度声明——本文件实际断言：
  - 渲染结果恒 str、无 [CQ:、无 at 占位（S1/S2/S3，TC-07/08/11 条数语义）
  - 无装饰 emoji 扫描（TC-18 部分：M0 样本集 4 个输出，非全量管线）
未达 TC（页脚 TPL-08、折叠 TPL-09、✅❌ 标记 TPL-10/11、截断黄提示）依赖
壳层/后续里程碑，显式归入 defer（不冒充已覆盖）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.message_format.panel_render import (
    render_panel, render_stats_line, paginate, DEFAULT_PAGE_SIZE,
)
from qbot_rpg.core.message_format.prefix_render import render_prefix

# 3d §4.2 装饰性 emoji 禁用清单（程序化扫描锚点）
BANNED = "🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸"
ALLOWED = "✅❌"


# 3a S1/S2/S3：纯 str + 无 CQ 码 + 无平台占位
def test_render_is_plain_string(player):
    s = render_panel(player)
    assert isinstance(s, str)
    assert "[CQ:" not in s
    # P0（M0 复查）：原 `or True` 恒真空洞断言已修——首行不应含裸 @（at 占位）。
    # at 若需要由壳层构造，应显式注入而非出现在渲染产物；此处断言渲染产物纯净。
    assert "@" not in s.split("\n")[0]


def test_prefix_no_emoji():
    for out in (render_prefix(35, "阿伟", "斩龙者"), render_prefix(35, "阿伟", None)):
        assert not any(ch in out for ch in BANNED)
        assert "✅" not in out and "❌" not in out  # 前缀区禁止任何 emoji（3d §4.1）


def test_panel_no_banned_emoji(player):
    for out in (render_panel(player), render_stats_line(player.attributes)):
        assert not any(ch in out for ch in BANNED)


# 3d TC-07/08/11：5 条/页分页 + 页脚语义
def test_paginate_five_per_page():
    items = list(range(12))
    page1, pages, total = paginate(items, 1, per_page=5)
    assert total == 12 and pages == 3
    assert len(page1) == 5
    page2, _, _ = paginate(items, 2, per_page=5)
    assert len(page2) == 5
    page3, _, _ = paginate(items, 3, per_page=5)
    assert len(page3) == 2


def test_paginate_single_page_no_paging():
    items = list(range(3))
    _, pages, total = paginate(items, 1, per_page=5)
    assert pages == 1 and total == 3


def test_default_page_size_is_five():
    assert DEFAULT_PAGE_SIZE == 5  # 3d D-02 5 条/页上限
