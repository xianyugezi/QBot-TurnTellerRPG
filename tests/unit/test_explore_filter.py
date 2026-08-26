"""M5-09 探索合并 + 背包筛选链测试（tests/unit/test_explore_filter.py）。

依据：m5_shared_contract §三 / 4f RUL-16 / TC-14 / 框架 §7.4 L1336-1344。
覆盖：/背包筛选 类型→子类→品质叠加、分页、空文案、无效类型；/进入 /休息 1 条消息壳。
"""
from __future__ import annotations

import pytest

from qbot_rpg.commands.basic_commands import (
    BAG_FILTER_CMD,
    TPL_EMPTY_BAG,
    cmd_bag_filter,
)
from qbot_rpg.commands.explore_commands import cmd_enter, cmd_rest
from qbot_rpg.commands.parsers import parse_command

# ---------------------------------------------------------------------------
# /背包筛选 夹具
# ---------------------------------------------------------------------------

_FILTER_ITEMS = {
    "iron_sword": {"id": "iron_sword", "name": "铁剑", "type": "weapon", "quality": "fine"},
    "steel_sword": {"id": "steel_sword", "name": "钢剑", "type": "weapon", "quality": "epic"},
    "iron_helm": {"id": "iron_helm", "name": "铁盔", "type": "armor_head", "quality": "normal"},
    "potion": {"id": "potion", "name": "药水", "type": "consumable", "quality": "normal"},
    "hi_potion": {"id": "hi_potion", "name": "高级药水", "type": "consumable", "quality": "fine"},
    "iron_ore": {"id": "iron_ore", "name": "铁矿", "type": "material", "quality": "normal"},
    "quest_seal": {"id": "quest_seal", "name": "任务印章", "type": "quest", "quality": "legendary"},
}
_FILTER_INV = [
    {"item_id": "iron_sword", "name": "铁剑", "quality": "fine", "count": 1, "acquired_at": 7},
    {"item_id": "steel_sword", "name": "钢剑", "quality": "epic", "count": 1, "acquired_at": 6},
    {"item_id": "iron_helm", "name": "铁盔", "quality": "normal", "count": 1, "acquired_at": 5},
    {"item_id": "potion", "name": "药水", "quality": "normal", "count": 3, "acquired_at": 4},
    {"item_id": "hi_potion", "name": "高级药水", "quality": "fine", "count": 2, "acquired_at": 3},
    {"item_id": "iron_ore", "name": "铁矿", "quality": "normal", "count": 9, "acquired_at": 2},
    {"item_id": "quest_seal", "name": "任务印章", "quality": "legendary", "count": 1, "acquired_at": 1},
]


def parse(raw: str):
    return parse_command(raw)


def make_ctx(**over):
    base = {
        "registered": True,
        "is_gm": False,
        "items": {k: dict(v) for k, v in _FILTER_ITEMS.items()},
        "inventory": [dict(r) for r in _FILTER_INV],
        "settings": {},
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# /背包筛选：类型 → 子类 → 品质 叠加
# ---------------------------------------------------------------------------

def test_filter_by_category():
    """/背包筛选装备 → 只显示装备（铁剑/钢剑/铁盔，acquired_at 倒序）；单页无页脚（D-02）。"""
    out = cmd_bag_filter(parse("/背包筛选装备"), make_ctx())
    assert "1. 铁剑（精良）" in out
    assert "2. 钢剑（史诗）" in out
    assert "3. 铁盔" in out
    assert "药水" not in out and "铁矿" not in out and "任务印章" not in out
    assert "页脚" not in out and "—" not in out


def test_filter_many_pages():
    """>5 条筛选结果 → 5 条/页 + TPL-08 页脚；第 2 页剩 2 条。"""
    inv = [{"item_id": f"sword{i}", "name": f"剑{i}", "quality": "fine",
            "count": 1, "acquired_at": 20 - i} for i in range(7)]
    items = {f"sword{i}": {"id": f"sword{i}", "name": f"剑{i}",
                           "type": "weapon", "quality": "fine"} for i in range(7)}
    ctx = make_ctx(inventory=inv, items=items)
    out1 = cmd_bag_filter(parse("/背包筛选装备"), ctx)
    assert "1. 剑0（精良）" in out1 and "5. 剑4（精良）" in out1
    assert "6. 剑5" not in out1
    assert "— 第 1/2 页 · 共 7 条 · 输入 /背包筛选 页码 翻页 —" in out1
    out2 = cmd_bag_filter(parse("/背包筛选装备 2"), ctx)
    assert "6. 剑5（精良）" in out2 and "7. 剑6（精良）" in out2
    assert "— 第 2/2 页 · 共 7 条 · 输入 /背包筛选 页码 翻页 —" in out2


def test_filter_category_consumable():
    """/背包筛选消耗品 → 药水/高级药水。"""
    out = cmd_bag_filter(parse("/背包筛选消耗品"), make_ctx())
    assert "1. 药水 ×3" in out
    assert "2. 高级药水 ×2（精良）" in out
    assert "铁剑" not in out


def test_filter_chain_subtype_and_quality():
    """筛选链叠加：/背包筛选装备 类型 武器 品质 史诗 → 钢剑。"""
    out = cmd_bag_filter(parse("/背包筛选装备 类型 武器 品质 史诗"), make_ctx())
    assert "钢剑（史诗）" in out
    assert "铁剑" not in out and "铁盔" not in out


def test_filter_bare_word_subtype():
    """裸词容错：/背包筛选装备 武器 → 子类=武器。"""
    out = cmd_bag_filter(parse("/背包筛选装备 武器"), make_ctx())
    assert "铁剑（精良）" in out and "钢剑（史诗）" in out
    assert "铁盔" not in out


def test_filter_page_clamp():
    """/背包筛选装备 9 超总页 → 夹取最后页 +（已到最后一页）。"""
    out = cmd_bag_filter(parse("/背包筛选装备 9"), make_ctx())
    assert "（已到最后一页）" in out
    assert "3. 铁盔" in out


def test_filter_empty_result():
    """筛选无结果 → 空背包文案。"""
    out = cmd_bag_filter(parse("/背包筛选装备 品质 传说"), make_ctx())
    assert out == TPL_EMPTY_BAG


def test_filter_invalid_category():
    """无效物品类型词 → ❌ 提示（非 TPL-12，值域问题）。"""
    out = cmd_bag_filter(parse("/背包筛选 传说"), make_ctx())
    assert "没有「传说」这个物品类型" in out


def test_filter_page_invalid_tpl12():
    """裁决②：/背包筛选装备 0/-1/负数 页码 → TPL-12（不崩溃、不当筛选词）。"""
    for raw in ["/背包筛选装备 0", "/背包筛选装备 -1", "/背包筛选装备 -3"]:
        out = cmd_bag_filter(parse(raw), make_ctx())
        assert out == f"❌ 指令不正确：{raw}。输入 /帮助 查看可用指令。", raw


def test_filter_missing_category():
    """缺物品类型词 → ❌ 用法提示。"""
    out = cmd_bag_filter(parse("/背包筛选"), make_ctx())
    assert "背包筛选：输入物品类型" in out


def test_filter_no_emoji():
    """筛选输出无装饰 emoji（仅 ✅/❌ + 排版符号）。"""
    import re
    out = cmd_bag_filter(parse("/背包筛选装备"), make_ctx())
    assert not re.search(r"[\U0001F000-\U0001FAFF]|[\U00002600-\U000027BF]", out)


# ---------------------------------------------------------------------------
# /进入 /休息：探索结果合并 1 条
# ---------------------------------------------------------------------------

def test_enter_noarg_hint():
    """/进入 无参 → ❌ 用法提示（1 条）。"""
    out = cmd_enter(parse("/进入"), make_ctx())
    assert out.startswith("❌ ") and "/进入" in out
    assert "\n" not in out


def test_enter_invalid_direction_fail_reason():
    """/进入 无效方向 → 引擎 reason 1 条（不崩溃）。"""
    out = cmd_enter(parse("/进入 斜上方"), make_ctx())
    assert out.startswith("❌ ")


def test_rest_no_session_rejected():
    """/休息 无副本会话 → not_safe_zone 拒绝 1 条。"""
    out = cmd_rest(parse("/休息"), make_ctx())
    assert out.startswith("❌ ")


def test_rest_extra_arg_tpl12():
    """/休息 超参 → 提示（1 条）。"""
    out = cmd_rest(parse("/休息 1 2"), make_ctx())
    assert "不需要参数" in out


def test_explore_shell_single_message():
    """/进入 /休息 输出均为单条消息（无裸多段，合并 1 条语义）。"""
    for raw, handler, ctx in [
        ("/进入", cmd_enter, make_ctx()),
        ("/休息", cmd_rest, make_ctx()),
    ]:
        out = handler(parse(raw), ctx)
        assert isinstance(out, str) and out
