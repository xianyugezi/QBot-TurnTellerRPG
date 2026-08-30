"""商店指令接线单测（M4 批次3·路D3 · qbot_rpg/commands/shop_commands.py）。

依据：m4_shared_contract.md §2.3+§3.2 + docs/细化/细化_2b3_商店引擎契约.md（§2.1 入口
/商店 /购买 /出售 + 补缺漏 /商店 列表；§2.2 校验链 6 步；TC-01~42）+ 细化_3d（TPL-08/TPL-12、
5 条/页、页码夹取）+ 2026-08-27 用户裁决②（页码夹取最后一页；0/负/非数字 → TPL-12）。

集成口径：直接驱动**真实引擎** qbot_rpg/core/shop.py（批次3·路D2 已落盘），构造全字段 ctx
（items/shops/settings/currencies/inventory/personal_buys/now 注入确定性），断言命令层输出。

覆盖：/商店 无参（当前→默认 normal 兜底）· 名称/序号切换 · 页码优先翻页 · 超页夹取 + 已到最后一页
（裁决②）· 0/负数/非数字 → TPL-12 · /商店 列表（类型徽标/门槛标记/5 条页/夹取）· /购买（成功/
余额不足差额/限购/售罄/等级/声望/没商品/序号/数量截断 D-05/紧凑格式）· /出售（成功/不足/绑定/
任务关键）· 注册与解析接线 · 页脚 TPL-08 逐字 · 无装饰 emoji。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.router import Router
from qbot_rpg.commands.shop_commands import (
    BUY_CMD,
    SELL_CMD,
    SHOP_CMD,
    cmd_buy,
    cmd_sell,
    cmd_shop,
    format_number,
    register_shop_commands,
    render_shop_items,
    render_shops_overview,
)

# ---------------------------------------------------------------------------
# 夹具：全字段内容包（对齐 core/shop.py 工程补白 2 的 ctx 契约）
# ---------------------------------------------------------------------------

ITEMS = {
    "potion": {"id": "potion", "name": "药水", "price": 50},
    "heal": {"id": "heal", "name": "疗伤药", "price": 100},
    "antidote": {"id": "antidote", "name": "解毒草", "price": 30},
    "iron_sword": {"id": "iron_sword", "name": "铁剑", "price": 500, "bound": True},
    "gold_pearl": {"id": "gold_pearl", "name": "金珠", "price": 100000, "sell_price": 100000},
    "scroll": {"id": "scroll", "name": "回城卷轴", "price": 100},
    "iron_ore": {"id": "iron_ore", "name": "铁矿", "price": 10},
    "task_key": {"id": "task_key", "name": "任务钥匙", "price": 50, "sellable": False},
    "silver_sword": {"id": "silver_sword", "name": "银剑", "price": 2000},
    "dragon_scale": {"id": "dragon_scale", "name": "龙鳞", "price": 100},
    "spirit": {"id": "spirit", "name": "神性碎片", "price": 100},
    "star_dust": {"id": "star_dust", "name": "星尘", "price": 200},
}

SHOPS = {
    "grocery": {"id": "grocery", "name": "杂货铺", "type": "normal", "icon": "", "currency": "coins",
        "desc": "新手村杂货铺", "refresh": {"mode": "daily", "hour": 5},
        "items": [
            {"item": "potion", "price": 50, "stock": 0},
            {"item": "heal", "price": 100, "scope": "personal", "limit": 3, "period": "day"},
            {"item": "antidote", "price": 30, "stock": 5},
            {"item": "iron_sword", "price": 500, "min_level": 10},
            {"item": "gold_pearl", "price": 100000, "discount": 20},
            {"item": "scroll", "price": 100, "stock": 5},
        ]},
    "blacksmith": {"id": "blacksmith", "name": "铁匠铺", "type": "npc", "icon": "", "currency": "coins",
        "desc": "老周的小店", "refresh": {"mode": "none"},
        "items": [{"item": "iron_ore", "price": 80}, {"item": "silver_sword", "price": 2000}]},
    "guild": {"id": "guild", "name": "冒险者公会商店", "type": "reputation", "icon": "", "currency": "coins",
        "reputation_required": {"level": 2}, "desc": "公会专属", "refresh": {"mode": "none"},
        "items": [{"item": "silver_sword", "price": 2000, "reputation_required": {"level": 2}}]},
    "festival": {"id": "festival", "name": "丰收节集市", "type": "event", "icon": "", "currency": "tickets",
        "open_condition": {"var": "is_festival", "op": "eq", "value": True}, "desc": "限时集市",
        "refresh": {"mode": "none"}, "items": [{"item": "spirit", "price": 100}]},
    "black_market": {"id": "black_market", "name": "神秘商人", "type": "blackmarket", "icon": "", "currency": "coins",
        "desc": "深夜黑市", "refresh": {"mode": "none"}, "price_fluctuation": 0,
        "items": [{"item": "dragon_scale", "price": {"coins": 50, "gems": 5}}],
        "pool": [{"item": "dragon_scale", "price": {"coins": 50, "gems": 5}}]},
    "alchemist": {"id": "alchemist", "name": "炼金工坊", "type": "normal", "icon": "", "currency": "coins",
        "level_required": 10, "desc": "炼金材料", "refresh": {"mode": "none"},
        "items": [{"item": "star_dust", "price": 200}]},
}

# 2026-08-26 09:00 UTC+8（确定性：日界桶键=2026-08-26，个人限购计数不跨期清零）
NOW = 1787706000


def make_ctx(**over):
    """全字段玩家商店 ctx（core/shop.py 工程补白 2 契约；每场景新造避免互污染）。"""
    base = {
        "level": 5,
        "name": "阿伟",
        "reputation": 1,  # 声望等级（_player_rep_level：rep int → 等级）
        "currencies": {"coins": 1000, "gems": 5},
        "inventory": {"iron_ore": 12, "task_key": 1, "iron_sword": 1},
        "personal_buys": {"grocery": {"heal": {"count": 3, "key": "2026-08-26"}}},
        "items": ITEMS,
        "shops": SHOPS,
        "settings": {
            "currencies": [
                {"id": "coins", "name": "金币"},
                {"id": "gems", "name": "宝石"},
                {"id": "tickets", "name": "活动币"},
            ],
            "sell_ratio": 0.3,
        },
        "now": NOW,
        "current_shop_ref": None,
    }
    base.update(over)
    return base


def parse(raw: str):
    """parse_command 封装（默认白名单已含 商店/购买/出售，parsers.DEFAULT_WHITELIST）。"""
    return parse_command(raw)


# ---------------------------------------------------------------------------
# /商店 主入口：无参 / 名称 / 序号 / 页码 / 夹取 / TPL-12
# ---------------------------------------------------------------------------

def test_shop_noarg_browses_current_default_shop():
    """TC-01：无当前商店 `/商店` → 全局默认 normal 兜底商品列表第 1 页（5 条 + TPL-08 页脚）。"""
    out = cmd_shop(parse("/商店"), make_ctx())
    assert out.startswith("杂货铺 [普通商店]\n新手村杂货铺")
    assert "1. 药水\n　单价：50(金币)" in out
    assert "5. 金珠\n　单价：80000(金币) [折扣 -20%]" in out   # 意见一同步：折扣不显示原价
    # 5 条/页（m4 §2.2）：第 1 页 5 条 + TPL-08 页脚
    assert "当前页：1/2" in out
    # 条目间分隔线（2b3 TC-05）
    assert out.count("\n\n") == 4


def test_shop_noarg_current_shop_priority():
    """D-06/TC-30：地图级当前商店优先（current_shop_ref=guild → 浏览公会店）。"""
    out = cmd_shop(parse("/商店"), make_ctx(current_shop_ref="guild"))
    assert out.startswith("冒险者公会商店 [声望商店]\n公会专属")
    assert "1. 银剑\n　单价：2000(金币) 需要 熟悉" in out


def test_shop_name_switch_browse():
    """TC-02 后半段：/商店 <名称> 精确切换 → 浏览该店商品（单页无页脚）。"""
    out = cmd_shop(parse("/商店 铁匠铺"), make_ctx())
    assert out.startswith("铁匠铺 [NPC 商店]\n老周的小店")
    assert "1. 铁矿\n　单价：80(金币)" in out
    assert "2. 银剑\n　单价：2000(金币)" in out
    assert "翻页" not in out  # 单页不输出页脚（3d §2.3）


def test_shop_name_closed_shop():
    """TC-34：open_condition 未满足 → 「这家店还没开门」透传引擎消息。"""
    out = cmd_shop(parse("/商店 丰收节集市"), make_ctx())
    assert out == "❌ 这家店还没开门"


def test_shop_integer_page_flip_precedence():
    """TC-06 + 3d §2.2：/商店 2 在当前店有 ≥2 页时 = 商品列表翻页（页码优先横切）。"""
    out = cmd_shop(parse("/商店 2"), make_ctx())
    assert "6. 回城卷轴\n　单价：100(金币) 全服剩 5" in out
    assert "当前页：2/2" in out


def test_shop_integer_switch_when_page_out_of_range():
    """TC-02 前半段：/商店 3 超当前店页数且命中商店序号 → 切店浏览（第 3 家=公会店）。"""
    out = cmd_shop(parse("/商店 3"), make_ctx())
    assert out.startswith("冒险者公会商店 [声望商店]\n公会专属")
    assert "1. 银剑\n　单价：2000(金币) 需要 熟悉" in out


def test_shop_integer_clamp_last_page():
    """裁决②：/商店 9 超总页数且非商店序号 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_shop(parse("/商店 9"), make_ctx())
    assert "6. 回城卷轴\n　单价：100(金币) 全服剩 5" in out
    assert "（已到最后一页）" in out
    assert "当前页：2/2" in out


@pytest.mark.parametrize("raw, fragment", [
    ("/商店 0", "/商店 0"),
    ("/商店 -1", "/商店 -1"),
    ("/商店 abc", "/商店 abc"),
])
def test_shop_invalid_input_tpl12(raw, fragment):
    """裁决② + 3d §5.1：0/负数/未命名商店 → TPL-12 统一报错。"""
    out = cmd_shop(parse(raw), make_ctx())
    assert out == f"❌ 指令不正确：{fragment}。输入 /帮助 查看可用指令。"


def test_shop_name_with_page_arg():
    """3d §2.2「页码为最后一个整数参数」：/商店 <名称> <页码> 夹取。"""
    out = cmd_shop(parse("/商店 铁匠铺 2"), make_ctx())
    assert out.startswith("铁匠铺 [NPC 商店]\n老周的小店")
    assert "（已到最后一页）" in out  # 2 件单页 → 页码 2 夹取回第 1 页


# ---------------------------------------------------------------------------
# /商店 列表（补缺漏）：可用商店一览
# ---------------------------------------------------------------------------

def test_shop_list_overview_page1():
    """补缺漏 /商店 列表：类型徽标 + 门槛标记（置灰不隐藏）+ 5 条/页 + TPL-08 页脚。"""
    out = cmd_shop(parse("/商店 列表"), make_ctx())
    assert out.startswith("可用商店一览")
    assert "1. 杂货铺 [普通商店] 新手村杂货铺" in out
    assert "3. 冒险者公会商店 [声望商店] 公会专属 需要 熟悉" in out
    assert "5. 神秘商人 [黑市] 深夜黑市" in out
    assert "当前页：1/2" in out


def test_shop_list_overview_page2():
    """列表第 2 页（第 6 家 + 门槛标记）。"""
    out = cmd_shop(parse("/商店 列表 2"), make_ctx())
    assert "6. 炼金工坊 [普通商店] 炼金材料 需要 LV10" in out
    assert "当前页：2/2" in out


def test_shop_list_clamp_last_page():
    """裁决②：/商店 列表 9 超总页数 → 夹取最后一页 + （已到最后一页）。"""
    out = cmd_shop(parse("/商店 列表 9"), make_ctx())
    assert "6. 炼金工坊 [普通商店] 炼金材料 需要 LV10" in out
    assert "（已到最后一页）" in out


@pytest.mark.parametrize("raw", ["/商店 列表 0", "/商店 列表 abc"])
def test_shop_list_invalid_page_tpl12(raw):
    """裁决② + 3d §5.1：列表页码 0/非数字 → TPL-12。"""
    out = cmd_shop(parse(raw), make_ctx())
    assert out.startswith("❌ 指令不正确：/商店 列表 ")


def test_shop_list_single_page_no_footer():
    """3d §2.3：≤5 条商店一览单页无页脚。"""
    rows = [
        {"id": "a", "name": "甲店", "type": "normal", "icon": "", "desc": "", "markers": []},
        {"id": "b", "name": "乙店", "type": "npc", "icon": "", "desc": "", "markers": []},
    ]
    out = render_shops_overview(rows, 1)
    assert out.startswith("可用商店一览")
    assert "1. 甲店 [普通商店]" in out
    assert "2. 乙店 [NPC 商店]" in out
    assert "翻页" not in out


# ---------------------------------------------------------------------------
# /购买（引擎 6 步校验链消息透传 + 差额 + 数量截断）
# ---------------------------------------------------------------------------

def test_buy_ok():
    """定稿 L94：购买成功模板（千分位余额）。"""
    out = cmd_buy(parse("/购买 药水 3"), make_ctx())
    assert out == "✅ 购买成功：药水×3（-150 金币），剩余 850 金币"


def test_buy_default_qty1_and_compact():
    """默认数量 1 + 紧凑格式（2b3 §2.1 / TC-04）。"""
    assert cmd_buy(parse("/购买 药水"), make_ctx()) == "✅ 购买成功：药水×1（-50 金币），剩余 950 金币"
    assert cmd_buy(parse("购买+药水"), make_ctx()) == "✅ 购买成功：药水×1（-50 金币），剩余 950 金币"
    # 紧凑 + 数量：'购买+药水*5'（_target_of 收敛 连接符+ 与 *N）
    assert cmd_buy(parse("购买+药水*5"), make_ctx()) == "✅ 购买成功：药水×5（-250 金币），剩余 750 金币"


def test_buy_old_space_qty_compat():
    """规范 L238-239：`/购买 药水 5` 旧空格数量兼容。"""
    out = cmd_buy(parse("/购买 药水 5"), make_ctx())
    assert out == "✅ 购买成功：药水×5（-250 金币），剩余 750 金币"


def test_buy_insufficient_currency_show_diff():
    """任务要求「余额不足提示差额」+ 2b3 校验链⑤：`❌ 金币不足：还差 X`。"""
    out = cmd_buy(parse("/购买 金珠 1"), make_ctx())
    assert out == "❌ 金币不足：还差 79,000"


def test_buy_limit_reached():
    """2b3 TC-13/14：个人限购满 → 整单拒绝。"""
    out = cmd_buy(parse("/购买 疗伤药"), make_ctx())
    assert out == "❌ 今日限购 3 个，已买 3 个"


def test_buy_sold_out():
    """校验链④ + 定稿 L97：已售罄（daily 店含下次补货时间）。"""
    out = cmd_buy(parse("/购买 解毒草 6"), make_ctx())
    assert out == "❌ 已售罄（下次补货：明早 05:00）"


def test_buy_level_threshold():
    """校验链② + TC-37：等级门槛取更严。"""
    out = cmd_buy(parse("/购买 铁剑"), make_ctx())
    assert out == "❌ 等级不足：需要 LV10（当前 LV5）"


def test_buy_reputation_threshold():
    """校验链② + TC-38：声望门槛（引擎 5 级制：need 熟悉，have 陌生）。"""
    out = cmd_buy(parse("/购买 银剑"), make_ctx(current_shop_ref="guild"))
    assert out == "❌ 声望不足：需要 熟悉（当前 陌生）"


def test_buy_item_missing():
    """定稿 L99：没有这个商品（解析失败在①②间判定）。"""
    out = cmd_buy(parse("/购买 不存在物品"), make_ctx())
    assert out == "❌ 没有这个商品"


def test_buy_by_seq():
    """2b3 §2.1 名称优先→序号兜底：/购买 2 = 第 2 件（疗伤药→限购拦截证明序号命中）。"""
    out = cmd_buy(parse("/购买 2"), make_ctx())
    assert out == "❌ 今日限购 3 个，已买 3 个"


def test_buy_qty_over_cap_clamped():
    """2b3 D-05 / TC-03：数量超上限提示不拦截——按 99 截断执行并提示「最多一次购买 99 个」。"""
    out = cmd_buy(parse("/购买 药水*150"), make_ctx(currencies={"coins": 10000, "gems": 5}))
    assert out == "✅ 购买成功：药水×99（-4950 金币），剩余 5,050 金币；最多一次购买 99 个"


def test_buy_mixed_payment():
    """2b3 TC-19：混合支付双币同扣 + 双币均显示。"""
    out = cmd_buy(parse("/购买 龙鳞"), make_ctx(current_shop_ref="black_market"))
    assert out == "✅ 购买成功：龙鳞×1（-50 金币 5 宝石），剩余 950 金币"


def test_buy_missing_target_tpl12():
    """缺参 → TPL-12。"""
    assert cmd_buy(parse("/购买"), make_ctx()) == "❌ 指令不正确：/购买。输入 /帮助 查看可用指令。"


def test_buy_shortname_prefix_match():
    """QA P2-10：/购买 简写（名称前缀）唯一命中——「疗伤药」买「疗伤药水」。"""
    items = {
        "heal_potion": {"id": "heal_potion", "name": "疗伤药水", "price": 100},
        "iron_sword": {"id": "iron_sword", "name": "铁剑", "price": 500, "bound": True},
    }
    shops = {
        "pharmacy": {"id": "pharmacy", "name": "药铺", "type": "normal", "icon": "",
                     "currency": "coins", "refresh": {"mode": "none"},
                     "items": [
                         {"item": "heal_potion", "price": 100},
                         {"item": "iron_sword", "price": 500},
                     ]},
    }
    ctx = make_ctx(items=items, shops=shops, current_shop_ref="pharmacy")
    out = cmd_buy(parse("/购买 疗伤药"), ctx)
    assert out == "✅ 购买成功：疗伤药水×1（-100 金币），剩余 900 金币"


def test_buy_shortname_ambiguous_message():
    """QA P2-10：/购买 简写多命中 → 歧义提示（含候选商品名）。"""
    items = {
        "heal_potion": {"id": "heal_potion", "name": "疗伤药水", "price": 100},
        "heal_jelly": {"id": "heal_jelly", "name": "疗伤药剂", "price": 100},
    }
    shops = {
        "pharmacy": {"id": "pharmacy", "name": "药铺", "type": "normal", "icon": "",
                     "currency": "coins", "refresh": {"mode": "none"},
                     "items": [
                         {"item": "heal_potion", "price": 100},
                         {"item": "heal_jelly", "price": 100},
                     ]},
    }
    ctx = make_ctx(items=items, shops=shops, current_shop_ref="pharmacy")
    out = cmd_buy(parse("/购买 疗伤药"), ctx)
    assert out.startswith("❌ 商品名有歧义")
    assert "疗伤药水" in out and "疗伤药剂" in out


# ---------------------------------------------------------------------------
# /出售（立刻到账 + 拦截）
# ---------------------------------------------------------------------------

def test_sell_ok():
    """定稿 L360：出售成功模板（基准价×比率 30% 向下取整：10×0.3=3）。"""
    out = cmd_sell(parse("/出售 铁矿 5"), make_ctx())
    assert out == "✅ 出售成功：铁矿×5（+15 金币），剩余 1,015 金币"


def test_sell_insufficient_inventory():
    """定稿 L359：数量不足 → 「背包里只有 12 个铁矿」。"""
    out = cmd_sell(parse("/出售 铁矿 20"), make_ctx())
    assert out == "❌ 背包里只有 12 个铁矿"


def test_sell_bound_item():
    """定稿 L357：绑定物品拒绝出售。"""
    out = cmd_sell(parse("/出售 铁剑"), make_ctx())
    assert out == "❌ 绑定物品无法出售"


def test_sell_not_sellable():
    """定稿 L358：任务关键物品拒绝出售。"""
    out = cmd_sell(parse("/出售 任务钥匙"), make_ctx())
    assert out == "❌ 任务关键物品无法出售"


def test_sell_item_missing():
    """无此物品 → 「没有这个物品」（引擎：出售仅名称解析）。"""
    assert cmd_sell(parse("/出售 不存在"), make_ctx()) == "❌ 没有这个物品"


def test_sell_missing_target_tpl12():
    """缺参 → TPL-12。"""
    assert cmd_sell(parse("/出售"), make_ctx()) == "❌ 指令不正确：/出售。输入 /帮助 查看可用指令。"


# ---------------------------------------------------------------------------
# 接线：Router 注册 / 解析集成 / 渲染工具
# ---------------------------------------------------------------------------

def test_register_shop_commands():
    """批次6/7 装配入口：注册 商店/购买/出售 三条 CommandSpec。"""
    router = Router()
    register_shop_commands(router, make_context=lambda p: make_ctx())
    assert router.has(SHOP_CMD) and router.has(BUY_CMD) and router.has(SELL_CMD)
    names = set(router.names())
    assert {SHOP_CMD, BUY_CMD, SELL_CMD} <= names
    for n in (SHOP_CMD, BUY_CMD, SELL_CMD):
        assert router.get(n).whitelisted  # 可快捷白名单（定稿 L47）


def test_register_without_make_context_raises():
    """【待接线】无 make_context 时 handler 调用抛 RuntimeError（装配未注入的显式错误）。"""
    router = Router()
    register_shop_commands(router)
    with pytest.raises(RuntimeError):
        router.get(SHOP_CMD).handler(parse("/商店"))


def test_parse_command_integration():
    """解析接线：/商店 /购买 /出售 经 parsers.parse_command 产出结构化字段。"""
    p = parse("/商店 2")
    assert p.command == "商店" and p.args == ["2"]
    p = parse("/商店 列表")
    assert p.command == "商店" and p.args == ["列表"]
    p = parse("/购买 药水*5")
    assert p.command == "购买" and p.args == ["药水*5"] and p.qty == 5
    p = parse("购买+药水")
    # 解析器契约：紧凑 `+` 连接符留在 args（`+` 归等级分隔符）；命令层 _target_of 收敛剥离
    assert p.command == "购买" and p.args == ["+药水"] and p.compact is True
    p = parse("/出售 铁矿*20")
    assert p.command == "出售" and p.args == ["铁矿*20"] and p.qty == 20


def test_parse_error_routes_tpl12():
    """超参（3 个位置参数）→ 解析 error → TPL-12。"""
    out = cmd_shop(parse("/商店 列表 2 3"), make_ctx())
    assert out.startswith("❌ 指令不正确：")


def test_footer_tpl08_exact():
    """3d TC-12：页脚 TPL-08 逐字（无自造变体）。"""
    out = cmd_shop(parse("/商店 2"), make_ctx())
    assert "当前页：2/2" in out


def test_no_decorative_emoji():
    """3d §四 D-01：命令层渲染输出零装饰 emoji（仅 ✅/❌ 功能性标记允许）。"""
    outputs = [
        cmd_shop(parse("/商店"), make_ctx()),
        cmd_shop(parse("/商店 列表"), make_ctx()),
        cmd_buy(parse("/购买 药水 3"), make_ctx()),
        cmd_sell(parse("/出售 铁矿 5"), make_ctx()),
    ]
    banned = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")
    for text in outputs:
        for ch in text:
            assert ch not in banned, f"命中禁用装饰 emoji：{ch} in {text!r}"
            assert ch in ("✅", "❌") or not (0x1F000 <= ord(ch) <= 0x1FAFF), \
                f"命中未登记 emoji：{ch} in {text!r}"


def test_format_number():
    """千分位格式化（定稿「剩余 1,000 金币」）。"""
    assert format_number(1234567) == "1,234,567"
    assert format_number(850) == "850"
    assert format_number(0) == "0"
    assert format_number("abc") == "abc"


def test_render_shop_items_per_page_boundary():
    """5 条/页边界：6 条 → 页 1 五条 + 页脚，页 2 一条 + 页脚（裁决② 夹取分支已单测）。"""
    rows = [{"index": i, "name": f"物品{i}", "price": {"kind": "single", "unit": 10, "currency": "coins"},
             "discount": 0, "original_unit": 10, "markers": []} for i in range(1, 7)]
    ctx = make_ctx()
    p1 = render_shop_items({}, rows, 1, ctx)
    assert p1.count("\n　单价：") == 5              # 5 个商品行（Tip 行含「物品名」不计）
    assert "1. 物品1" in p1 and "5. 物品5" in p1
    assert "当前页：1/2" in p1
    p2 = render_shop_items({}, rows, 2, ctx)
    assert "6. 物品6" in p2
    assert "当前页：2/2" in p2
