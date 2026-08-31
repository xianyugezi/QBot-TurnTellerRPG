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
    assert "1.[铁剑]×1（精良）" in out
    assert "2.[钢剑]×1（史诗）" in out
    assert "3.[铁盔]×1" in out
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
    assert "1.[剑0]×1（精良）" in out1 and "5.[剑4]×1（精良）" in out1
    assert "6.[剑5]×1" not in out1
    assert "当前页：1/2(装备)" in out1
    out2 = cmd_bag_filter(parse("/背包筛选装备 2"), ctx)
    assert "6.[剑5]×1（精良）" in out2 and "7.[剑6]×1（精良）" in out2
    assert "当前页：2/2(装备)" in out2


def test_filter_category_consumable():
    """/背包筛选消耗品 → 药水/高级药水。"""
    out = cmd_bag_filter(parse("/背包筛选消耗品"), make_ctx())
    assert "1.[药水]×3" in out
    assert "2.[高级药水]×2（精良）" in out
    assert "铁剑" not in out


def test_filter_chain_subtype_and_quality():
    """筛选链叠加：/背包筛选装备 类型 武器 品质 史诗 → 钢剑。"""
    out = cmd_bag_filter(parse("/背包筛选装备 类型 武器 品质 史诗"), make_ctx())
    assert "1.[钢剑]×1（史诗）" in out
    assert "铁剑" not in out and "铁盔" not in out


def test_filter_bare_word_subtype():
    """裸词容错：/背包筛选装备 武器 → 子类=武器。"""
    out = cmd_bag_filter(parse("/背包筛选装备 武器"), make_ctx())
    assert "1.[铁剑]×1（精良）" in out and "2.[钢剑]×1（史诗）" in out
    assert "铁盔" not in out


def test_filter_page_clamp():
    """/背包筛选装备 9 超总页 → 夹取最后页 +（已到最后一页）。"""
    out = cmd_bag_filter(parse("/背包筛选装备 9"), make_ctx())
    assert "（已到最后一页）" in out
    assert "3.[铁盔]×1" in out


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


# ---------------------------------------------------------------------------
# /进入 move 成功：CakeGame 模板 28 风格丰富（地图介绍 + 活动怪物 + 通道 + Tip）
# ---------------------------------------------------------------------------

_ENTER_MAPS = [
    {
        "id": "start_village", "name": "起始村落", "desc": "宁静的小村",
        "monsters": [
            {"enemy": "rock_weasel", "count": 3, "respawn_minutes": 10},
        ],
        "exits": {"up": {"to": "forest_edge", "mode": "bidirectional"}},
    },
    {
        "id": "forest_edge", "name": "林间边缘", "desc": "树影幢幢的林缘",
        "monsters": [
            {"enemy": "rock_weasel", "count": 2, "respawn_minutes": 10},
            {"enemy": "stone_skink", "count": 1, "respawn_minutes": 30},
        ],
        "exits": {
            "down": {"to": "start_village", "mode": "bidirectional"},
            "right": {"to": "lava_tunnel", "mode": "bidirectional"},
        },
    },
    {
        "id": "lava_tunnel", "name": "熔岩坑道", "desc": "单向坑道",
        "monsters": [],
        "exits": {"left": {"to": "forest_edge", "mode": "bidirectional"}},
    },
]

_ENTER_MONSTERS = {
    "rock_weasel": {"name": "岩皮鼬"},
    "stone_skink": {"name": "石甲蜥"},
}


def _enter_ctx() -> dict:
    """/进入 move 成功 ctx：玩家位于起始村落 + maps + 怪物名映射。"""
    ctx = make_ctx(
        player={"map_id": "start_village", "name": "阿伟"},
        maps=[dict(m) for m in _ENTER_MAPS],  # type: ignore[call-overload]
        monsters={k: dict(v) for k, v in _ENTER_MONSTERS.items()},
    )
    ctx["map_id"] = "start_village"
    return ctx


def test_enter_move_enriched():
    """/进入 上 → move 成功：地图介绍 + 活动怪物（序号.名称×数量）+ 通道（方向：目标名）+ Tip。"""
    out = cmd_enter(parse("/进入 上"), _enter_ctx())
    assert out.startswith("✅ 你来到了「林间边缘」")
    assert "地图介绍：树影幢幢的林缘" in out
    assert "活动怪物：1.岩皮鼬×2 2.石甲蜥×1" in out
    assert "下：起始村落" in out
    assert "右：熔岩坑道" in out
    assert "左：" not in out              # 无通道方向省略
    assert "Tip:发送'位置'即可查询当前位置信息" in out
    assert "区域角色" not in out          # maps 无 npcs 字段 → 行省略（DELAYED）


def test_enter_move_unknown_monster_id_fallback():
    """/进入 目标怪物名映射缺失 → 直接显示 enemy id（拿不到映射不崩溃）。"""
    maps = [
        {
            "id": "start_village", "name": "起始村落", "desc": "宁静的小村",
            "monsters": [], "exits": {"up": {"to": "waste_plain", "mode": "bidirectional"}},
        },
        {
            "id": "waste_plain", "name": "荒原", "desc": "荒芜之地",
            "monsters": [{"enemy": "wild_beast", "count": 4, "respawn_minutes": 10}],
            "exits": {"down": {"to": "start_village", "mode": "bidirectional"}},
        },
    ]
    ctx = make_ctx(player={"map_id": "start_village", "name": "阿伟"}, maps=maps)
    ctx["map_id"] = "start_village"
    out = cmd_enter(parse("/进入 上"), ctx)
    assert out.startswith("✅ 你来到了「荒原」")
    assert "活动怪物：1.wild_beast×4" in out


def test_enter_move_no_emoji():
    """/进入 move 成功输出无装饰 emoji（仅 ✅/❌ + 排版符号）。"""
    import re
    out = cmd_enter(parse("/进入 上"), _enter_ctx())
    out_allowed = out.replace("✅", "").replace("❌", "")
    assert not re.search(r"[\U0001F000-\U0001FAFF]|[\U00002600-\U000027BF]", out_allowed)


# ---------------------------------------------------------------------------
# P1-5（QA 黑盒·位置不持久）：/进入 移动后位置写回 persistent_state["location"]
# ---------------------------------------------------------------------------

def _prod_like_ctx() -> tuple:
    """生产形态 ctx：ctx["player"] = Player frozen dataclass（无 map_id 字段），
    位置存 persistent_state["location"]；ctx["location"] 由装配层从 ps 注入。"""
    from qbot_rpg.data.player import Player

    ps: dict = {"location": "start_village"}
    player = Player(qid="2750511376", name="阿伟", persistent_state=ps)
    ctx = make_ctx(
        player=player,
        maps=[dict(m) for m in _ENTER_MAPS],  # type: ignore[call-overload]
        monsters={k: dict(v) for k, v in _ENTER_MONSTERS.items()},
        location="start_village",
    )
    return ctx, player, ps


def test_enter_move_persists_location_to_ps():
    """P1-5（黑盒回归）：/进入 上 移动后位置写回真实 persistent_state["location"]。

    旧行为：cmd_enter 传 dict(player) 一次性副本 → 位置写在副本上丢写回 → 落档丢位置。
    """
    ctx, player, ps = _prod_like_ctx()
    out = cmd_enter(parse("/进入 上"), ctx)
    assert out.startswith("✅ 你来到了「林间边缘」")
    assert ps["location"] == "forest_edge"                     # 真落档位更新（重启仍保持）
    assert player.persistent_state["location"] == "forest_edge"


def test_enter_number_persists_location_to_ps():
    """/进入 2（批1 世界地图序号）：数字传送同样写回 persistent_state["location"]。"""
    ctx, player, ps = _prod_like_ctx()
    out = cmd_enter(parse("/进入 2"), ctx)
    assert "林间边缘" in out
    assert ps["location"] == "forest_edge"


# ---------------------------------------------------------------------------
# 模板配置化（2026-08-31 用户拍板：消息模板不写死代码 → explore_tpl 分区 + tpl_of）
# ---------------------------------------------------------------------------

def test_explore_template_custom_override():
    """覆盖测试：ctx["templates"]（内容包覆盖，resolve_templates 合并）→ 输出用自定义模板。

    未覆盖 key 仍走默认模板（explore_monster_line / explore_channel_row），零破坏。
    """
    from qbot_rpg.core.templates import resolve_templates

    ctx = _enter_ctx()
    ctx["templates"] = resolve_templates({
        "explore_enter_ok": "✅ 抵达「{name}」",
        "explore_map_desc": "地图简介：{desc}",
        "explore_tip": "Tip:发送'位置'看当前位置",
    })
    out = cmd_enter(parse("/进入 上"), ctx)
    assert out.startswith("✅ 抵达「林间边缘」")
    assert "地图简介：树影幢幢的林缘" in out
    assert "Tip:发送'位置'看当前位置" in out
    # 未覆盖 key 用默认 → 活动怪物行 / 通道行 / 怪物名映射不受影响
    assert "活动怪物：1.岩皮鼬×2 2.石甲蜥×1" in out
    assert "下：起始村落" in out
    assert "右：熔岩坑道" in out
    assert "✅ 你来到了「林间边缘」" not in out


def test_explore_template_rest_custom_override():
    """/休息 覆盖测试：explore_rest_ok / explore_rest_cooldown 自定义 → 输出用自定义。"""
    from qbot_rpg.core.templates import resolve_templates

    ctx = make_ctx(
        player={"map_id": "a_zone", "name": "阿伟", "hp": 30, "mp": 20, "max_hp": 100, "max_mp": 50},
        dungeon_session={"zone": "a_zone", "safe_zone": True, "current_map": "a_zone",
                         "dungeon_def": {"maps": ["a_zone"]}},
        rest_cfg={"restore_pct": 0.2},
        templates=resolve_templates({
            "explore_rest_ok": "✅ 休整完毕：HP+{hp} MP+{mp}",
            "explore_rest_cooldown": "（CD-{cr}）",
        }),
    )
    out = cmd_rest(parse("/休息"), ctx)
    assert out.startswith("✅ 休整完毕：")
    assert "CD-" in out
    assert "点 HP" not in out and "冷却缩减" not in out


def test_explore_template_unknown_placeholder_preserved():
    """白名单外占位符（未登记/缺键）→ 渲染原样保留不崩（缺键保留原文）。"""
    from qbot_rpg.core.templates import resolve_templates

    ctx = _enter_ctx()
    ctx["templates"] = resolve_templates({
        "explore_enter_ok": "✅ 你来到了「{name}」{unknown_marker}",
    })
    out = cmd_enter(parse("/进入 上"), ctx)
    # {unknown_marker} 不在渲染数据（且非白名单）→ 原样保留，不抛异常
    assert out.startswith("✅ 你来到了「林间边缘」{unknown_marker}")


def test_explore_register_gate_templated():
    """RUL-08 门槛走 explore_register_gate 模板：内容包可覆盖门槛文案。"""
    from qbot_rpg.core.templates import resolve_templates

    ctx = make_ctx(registered=False, templates=resolve_templates({
        "explore_register_gate": "❌ 尚未创建角色，请先 /注册",
    }))
    out = cmd_enter(parse("/进入 上"), ctx)
    assert out == "❌ 尚未创建角色，请先 /注册"
