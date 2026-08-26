"""商店引擎单测（M4 批次3·路D2 · qbot_rpg/core/shop.py）——浏览/购买原子防双扣/出售/刷新四模式/当前商店。

依据：m4_shared_contract.md §3.2（C1-C6：stock 0=无限 / sold_out_once 永久下架 / 库存+限购同条目并存
裁决⑤ / 限购清零以条目 period 独立驱动 / 不配置=永不刷新 裁决⑥ / 原子防双扣 / 当前商店机制）
+ 细化_2b3_商店引擎契约.md（6 步校验链 D-01 / 原子结算 D-03 / 混合支付整单原子 D-02 / 数量上限
D-05 / 出售 D-04 / 当前商店 D-06 / 刷新三件事 / TC-01~TC-42）
+ 审查参考/商店系统设计定稿.md（L281-292 刷新三件事 + L345-348 原子结算 + L338-344 校验链 +
L305-327 当前商店 + L193 混合支付 + 声望 5 级制）
+ 2026-08-27 裁决⑤⑥（P1-3 限购清零以 period 为准 / P1-4 默认 refresh=none）。

覆盖：浏览（无限库存/分页/标记/置灰/未开门）· 购买（校验链顺序/限购/库存/货币/混合支付原子/
数量截断/幂等/回滚/永久下架）· 出售（比率向下取整/sell_price 覆盖/拦截/不计限购/上限）·
刷新（daily 惰性补刷/weekly/none 永不/once 时间窗/黑市重抽确定性/离线多天）· 当前商店（记录/清除/
序号/名称切换）· /商店 列表。
"""

from __future__ import annotations

import copy
import datetime
import random

import pytest

from qbot_rpg.core.shop import (
    DEFAULT_BUY_CAP,
    DEFAULT_SELL_RATIO,
    REFRESH_MODES,
    REPUTATION_NAMES,
    SHOP_TYPES,
    clear_current_shop,
    current_shop_id,
    default_shop_id,
    next_stock_message,
    personal_limit_state,
    price_for,
    resolve_shop_arg,
    resolve_refresh,
    set_current_shop,
    shop_apply_refresh,
    shop_browse,
    shop_buy,
    shop_lazy_refresh,
    shop_list,
    shop_open_state,
    shop_refresh_due,
    shop_sell,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
ITEMS = {
    "药水": {"id": "药水", "name": "药水", "price": 100},
    "疗伤药": {"id": "疗伤药", "name": "疗伤药", "price": 100},
    "铁矿": {"id": "铁矿", "name": "铁矿", "price": 12},
    "金珠": {"id": "金珠", "name": "金珠", "price": 500000, "sell_price": 100000},
    "绑定剑": {"id": "绑定剑", "name": "绑定剑", "price": 1000, "bound": True},
    "任务道具": {"id": "x_任务道具", "name": "任务道具", "price": 10, "sellable": False},
    "稀有宝箱": {"id": "稀有宝箱", "name": "稀有宝箱", "price": 3000},
    "限定时装": {"id": "限定时装", "name": "限定时装", "price": 100},
    "神性碎片": {"id": "神性碎片", "name": "神性碎片", "price": 10000},
    "铁剑": {"id": "铁剑", "name": "铁剑", "price": 500},
    "银剑": {"id": "银剑", "name": "银剑", "price": 2000},
    "龙鳞": {"id": "龙鳞", "name": "龙鳞", "price": 5000},
    "星尘": {"id": "星尘", "name": "星尘", "price": 800},
    "节日礼花": {"id": "节日礼花", "name": "节日礼花", "price": 10},
    "折扣品": {"id": "折扣品", "name": "折扣品", "price": 10000},
}

SETTINGS = {"currencies": [
    {"id": "coins", "name": "金币"},
    {"id": "gem", "name": "宝石"},
    {"id": "tickets", "name": "活动币"},
]}

SHOPS = {
    "grocery": {
        "id": "grocery", "name": "杂货铺", "icon": "🏪", "type": "normal",
        "currency": "coins", "refresh": {"mode": "daily", "hour": 5},
        "items": [
            {"item": "药水", "price": 100},
            {"item": "疗伤药", "price": 100, "limit": 3, "period": "day"},
            {"item": "铁矿", "price": 12},
            {"item": "稀有宝箱", "price": 3000, "stock": 5},
            {"item": "限定时装", "price": 100, "stock": 1, "sold_out_once": True},
            {"item": "神性碎片", "price": 10000, "stock": 2, "limit": 1, "period": "day"},
            {"item": "折扣品", "price": 10000, "discount": 20},
        ],
    },
    "blacksmith": {
        "id": "blacksmith", "name": "铁匠铺", "type": "npc", "currency": "coins",
        "items": [{"item": "铁剑", "price": 500}],
    },
    "guild": {
        "id": "guild", "name": "冒险者公会", "type": "reputation",
        "reputation_required": {"level": 3}, "currency": "coins",
        "items": [{"item": "银剑", "price": 2000, "reputation_required": {"level": 3}}],
    },
    "black_market": {
        "id": "black_market", "name": "神秘商人", "type": "blackmarket",
        "currency": "coins", "refresh": {"mode": "daily", "hour": 20},
        "price_fluctuation": 20, "items": [],
        "pool": [
            {"item": "龙鳞", "price": 5000, "limit": 1, "period": "week"},
            {"item": "星尘", "price": 800},
            {"item": "稀有宝箱", "price": 3000, "stock": 5},
        ],
    },
    "festival": {
        "id": "festival", "name": "丰收节集市", "type": "event", "currency": "tickets",
        "refresh": {"mode": "once", "start": "2026-09-01 00:00", "end": "2026-09-07 23:59"},
        "items": [{"item": "节日礼花", "price": 10}],
    },
    "night_market": {
        "id": "night_market", "name": "夜市", "type": "blackmarket",
        "open_condition": {"var": "is_night", "op": "is", "value": True},
        "pool": [{"item": "星尘", "price": 800}], "items": [],
    },
    "nostock": {
        "id": "nostock", "name": "不补货店", "type": "normal", "currency": "coins",
        "items": [{"item": "药水", "price": 100, "stock": 3}],
    },
    "weekly_shop": {
        "id": "weekly_shop", "name": "周更店", "type": "normal", "currency": "coins",
        "refresh": {"mode": "weekly", "weekday": 1, "hour": 5},
        "items": [{"item": "药水", "price": 100, "stock": 5}],
    },
    "mixed_shop": {
        "id": "mixed_shop", "name": "混合支付店", "type": "normal", "currency": "coins",
        "items": [{"item": "神性碎片", "price": {"coins": 50, "gem": 5}}],
    },
    "chain_shop1": {
        "id": "chain_shop1", "name": "链序一店", "type": "normal", "currency": "coins",
        "items": [{"item": "药水", "price": 5000, "stock": 1, "limit": 1, "period": "day"}],
    },
    "chain_shop2": {
        "id": "chain_shop2", "name": "链序二店", "type": "normal", "currency": "coins",
        "items": [{"item": "神性碎片", "price": 10000, "stock": 1}],
    },
    "big_shop": {
        "id": "big_shop", "name": "大货架店", "type": "normal", "currency": "coins",
        "items": [{"item": "药水", "price": 100} for _ in range(12)],
    },
}


def make_ctx(**overrides) -> dict:
    """默认 ctx：货币/背包(in-memory)/物品+商店注册表/等级/声望/rng 种子/固定 now。"""
    ctx = {
        "settings": SETTINGS,
        "shops": SHOPS,
        "items": ITEMS,
        "currencies": {"coins": 10000, "gem": 5, "tickets": 50},
        "inventory": {"铁矿": 12, "药水": 2},
        "level": 10,
        "name": "阿明",
        "reputation": 1,
        "reputation_state": {"global": 0},
        "rng": random.Random(42),
        "now": _ts(2026, 8, 26, 10, 0, 0),
        "personal_buys": {},
        "world_stock": {},
        "world_sold_out": {},
        "last_refresh": {},
        "blackmarket_goods": {},
        **overrides,
    }
    return ctx


# ===========================================================================
# ① 浏览：默认商店 / 无限库存 / 分页 / 标记 / 置灰 / 未开门
# ===========================================================================
def test_tc01_browse_default_normal_shop():
    """TC-01：无当前商店 /商店 → 全局默认商店（normal 兜底）商品列表。"""
    ctx = make_ctx()
    sid = resolve_shop_arg(None, ctx)
    assert sid == "grocery"
    r = shop_browse(sid, ctx)
    assert r["ok"] is True
    assert r["shop"]["type"] == "normal"
    assert r["title"].startswith("LV10.")


def test_tc08_browse_stock0_infinite_no_soldout():
    """TC-08：stock 0 = 无限库存——无论买多少次不售罄、列表无售罄标记。"""
    ctx = make_ctx()
    r = shop_browse("grocery", ctx)
    row = next(x for x in r["rows"] if x["item_id"] == "药水")
    assert row["stock_remaining"] is None
    assert "已售罄" not in row["markers"]
    assert row["can_buy"] is True
    for _ in range(3):
        b = shop_buy("grocery", "药水", 20, ctx)
        assert b["ok"] is True


def test_tc06_browse_pagination_and_clamp():
    """TC-06/裁决②：≤10 条一屏；页码越界夹取最后一页。"""
    ctx = make_ctx()
    r1 = shop_browse("big_shop", ctx, page=1)
    assert r1["ok"] and r1["pages"] == 2 and len(r1["rows"]) == 10
    r2 = shop_browse("big_shop", ctx, page=2)
    assert len(r2["rows"]) == 2 and r2["page"] == 2
    r3 = shop_browse("big_shop", ctx, page=99)
    assert r3["page"] == 2 and len(r3["rows"]) == 2
    r4 = shop_browse("big_shop", ctx, page=0)
    assert r4["page"] == 1


def test_tc07_browse_markers_greyed_not_hidden():
    """TC-07：置灰不隐藏——限购/全服库存/门槛/折扣标记均显示。"""
    ctx = make_ctx()
    r = shop_browse("grocery", ctx)
    by_id = {x["item_id"]: x for x in r["rows"]}
    assert any("每日限购 3" == m for m in by_id["疗伤药"]["markers"])
    assert any("全服剩 5" == m for m in by_id["稀有宝箱"]["markers"])
    assert any(m.startswith("全服剩 1") for m in by_id["限定时装"]["markers"])
    disc = by_id["折扣品"]
    assert disc["discount"] == 20 and disc["original_unit"] == 10000


def test_tc37_browse_shop_level_gate_greyed_not_blocked():
    """TC-37：商店级门槛不挡浏览（商品置灰带需求标记）。"""
    ctx = make_ctx(reputation=1)
    r = shop_browse("guild", ctx)
    assert r["ok"] is True
    row = r["rows"][0]
    assert any(m == "需要 信赖" for m in row["markers"])
    assert row["greyed"] is True


def test_tc34_browse_once_window_gate():
    """TC-34：once 时间窗——start 前/end 后整店未开门，窗口内开放。"""
    before = make_ctx(now=_ts(2026, 8, 26, 10, 0, 0))
    assert shop_browse("festival", before)["reason"] == "window_not_started"
    inside = make_ctx(now=_ts(2026, 9, 3, 12, 0, 0))
    assert shop_browse("festival", inside)["ok"] is True
    after = make_ctx(now=_ts(2026, 9, 10, 12, 0, 0))
    assert shop_browse("festival", after)["reason"] == "window_expired"


def test_tc42_open_condition_failsafe():
    """TC-42：open_condition 不满足 → 未开门；满足 → 开放（安全失败不崩）。"""
    ctx_day = make_ctx(now=_ts(2026, 8, 26, 12, 0, 0))
    r = shop_browse("night_market", ctx_day)
    assert r["ok"] is False and r["reason"] == "condition"
    assert r["message"] == "❌ 这家店还没开门"
    ctx_night = make_ctx(now=_ts(2026, 8, 26, 12, 0, 0), is_night=True)
    assert shop_browse("night_market", ctx_night)["ok"] is True


def test_browse_no_shop():
    """①：商店不存在 → 「❌ 商店不存在」。"""
    r = shop_browse("ghost", make_ctx())
    assert r["ok"] is False and r["reason"] == "no_shop"


def test_blackmarket_browse_initial_listing():
    """TC-41 前奏：黑市首次访问惰性上架（pool→goods），价格在 ±20% 内浮动；同一套购买引擎。"""
    ctx = make_ctx(now=_ts(2026, 8, 26, 21, 0, 0))
    r = shop_browse("black_market", ctx)
    assert r["ok"] is True and r["total"] == 3
    base = {"龙鳞": 5000, "星尘": 800, "稀有宝箱": 3000}
    for row in r["rows"]:
        lo, hi = int(base[row["item_id"]] * 0.8), int(base[row["item_id"]] * 1.2)
        assert lo <= row["price"]["unit"] <= hi
    # 引擎统一：从黑市货架购买（按浮动后上架价扣款）
    first = r["rows"][0]
    coins_before = ctx["currencies"]["coins"]
    b = shop_buy("black_market", first["item_id"], 1, ctx)
    assert b["ok"] is True
    assert ctx["currencies"]["coins"] == coins_before - first["price"]["unit"]


# ===========================================================================
# ② 购买：校验链顺序 / 限购 / 库存 / 货币 / 混合支付 / 截断 / 幂等 / 回滚
# ===========================================================================
def test_tc09_buy_stock_decrement_then_soldout():
    """TC-09：global 库存逐次递减，售罄后再买 → 已售罄。"""
    ctx = make_ctx(currencies={"coins": 50000})
    for _ in range(4):
        assert shop_buy("grocery", "稀有宝箱", 1, ctx)["ok"] is True
    r = shop_browse("grocery", ctx)
    row = next(x for x in r["rows"] if x["item_id"] == "稀有宝箱")
    assert any(m == "全服剩 1" for m in row["markers"])
    assert shop_buy("grocery", "稀有宝箱", 1, ctx)["ok"] is True
    b = shop_buy("grocery", "稀有宝箱", 1, ctx)
    assert b["ok"] is False and b["reason"] == "stock"
    assert "已售罄（下次补货：明早 05:00）" in b["message"]


def test_tc13_buy_personal_limit():
    """TC-13：personal 限购计数 0→3，第 4 次拒绝。"""
    ctx = make_ctx()
    for _ in range(3):
        assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True
    b = shop_buy("grocery", "疗伤药", 1, ctx)
    assert b["ok"] is False and b["reason"] == "limit"
    assert b["message"] == "❌ 今日限购 3 个，已买 3 个"


def test_tc14_buy_limit_full_whole_order_rejected():
    """TC-14：限购满再买超额 → 整单拒绝无部分扣款。"""
    ctx = make_ctx()
    assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True
    b = shop_buy("grocery", "疗伤药", 3, ctx)  # 1 + 3 > 3 → 整单拒绝
    assert b["ok"] is False and b["reason"] == "limit"
    assert ctx["currencies"]["coins"] == 10000 - 100  # 只扣了第一次


def test_tc15_period_reset_day_next_day():
    """TC-15：day 周期隔天（>05:00 UTC+8）惰性清零可再买。"""
    ctx = make_ctx()
    for _ in range(3):
        assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True
    assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is False
    ctx["now"] = _ts(2026, 8, 27, 10, 0, 0)  # 次日
    assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True
    assert ctx["personal_buys"]["grocery"]["疗伤药"]["count"] == 1


def test_personal_limit_week_period_reset():
    """裁决⑤：week 周期以周界独立清零（本周买满，下周可再买）。"""
    ctx = make_ctx()
    ctx["shops"]["week_shop"] = {"id": "week_shop", "name": "周限店", "type": "normal",
                                 "currency": "coins",
                                 "items": [{"item": "药水", "price": 100, "limit": 2, "period": "week"}]}
    assert shop_buy("week_shop", "药水", 2, ctx)["ok"] is True
    assert shop_buy("week_shop", "药水", 1, ctx)["ok"] is False
    ctx["now"] = _ts(2026, 8, 31, 10, 0, 0)  # 下周一
    assert shop_buy("week_shop", "药水", 1, ctx)["ok"] is True


def test_tc16_sell_not_count_limit():
    """TC-16：出售不计限购（卖回再买逃课被防）；购买共享计数桶。"""
    ctx = make_ctx()
    assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True
    assert ctx["inventory"]["疗伤药"] == 1
    s = shop_sell("疗伤药", 1, ctx)
    assert s["ok"] is True
    assert ctx["personal_buys"]["grocery"]["疗伤药"]["count"] == 1  # 出售不计
    assert shop_buy("grocery", "疗伤药", 1, ctx)["ok"] is True  # 计数 2，仍可买
    assert ctx["personal_buys"]["grocery"]["疗伤药"]["count"] == 2


def test_tc39_chain_order_limit_before_stock_before_funds():
    """TC-39：限购(③)先于库存(④)先于货币(⑤)，命中即返回该文案不跳级。"""
    ctx = make_ctx(currencies={"coins": 6000})
    # ③ before ④/⑤
    assert shop_buy("chain_shop1", "药水", 1, ctx)["ok"] is True
    b = shop_buy("chain_shop1", "药水", 1, ctx)
    assert b["ok"] is False and b["reason"] == "limit"
    assert "限购" in b["message"]
    # ④ before ⑤（无限购条目：库存先耗尽）
    ctx2 = make_ctx(currencies={"coins": 10000})
    assert shop_buy("chain_shop2", "神性碎片", 1, ctx2)["ok"] is True
    b2 = shop_buy("chain_shop2", "神性碎片", 1, ctx2)
    assert b2["ok"] is False and b2["reason"] == "stock"


def test_tc17_buy_funds_insufficient():
    """TC-17：余额不足拒绝并提示差额；不扣款不入包。"""
    ctx = make_ctx(currencies={"coins": 100})
    b = shop_buy("grocery", "药水", 2, ctx)
    assert b["ok"] is False and b["reason"] == "funds"
    assert "金币不足：还差 100" in b["message"]
    assert ctx["currencies"]["coins"] == 100
    assert ctx["inventory"].get("药水", 0) == 2  # 初始 2 个，未入包


def test_tc19_tc20_mixed_payment_atomic():
    """TC-19/20：混合支付两币同扣；任一不足整单原子拒绝不部分扣款。"""
    ctx = make_ctx()
    b = shop_buy("mixed_shop", "神性碎片", 1, ctx)
    assert b["ok"] is True
    assert b["paid"] == {"coins": 50, "gem": 5}
    assert ctx["currencies"]["coins"] == 9950 and ctx["currencies"]["gem"] == 0
    b2 = shop_buy("mixed_shop", "神性碎片", 1, ctx)
    assert b2["ok"] is False and b2["reason"] == "funds"
    assert "宝石不足：还差 5" in b2["message"]
    assert ctx["currencies"]["coins"] == 9950  # coins 未被部分扣


def test_tc03_buy_cap_truncate():
    """TC-03：数量上限默认 99，超量提示不拦截——按 99 截断执行。"""
    ctx = make_ctx()
    b = shop_buy("grocery", "药水", 150, ctx)
    assert b["ok"] is True
    assert b["truncated"] is True and b["bought"]["count"] == DEFAULT_BUY_CAP
    assert b["advisory"] == "最多一次购买 99 个"
    assert ctx["currencies"]["coins"] == 10000 - 100 * DEFAULT_BUY_CAP


def test_tc11_sold_out_once_permanent():
    """TC-11：sold_out_once 售罄后刷新不恢复（永久下架）。"""
    ctx = make_ctx()
    assert shop_buy("grocery", "限定时装", 1, ctx)["ok"] is True
    assert shop_buy("grocery", "限定时装", 1, ctx)["ok"] is False
    # 到刷新时刻惰性补刷
    ctx["last_refresh"] = {"grocery": "2026-08-25"}
    ctx["now"] = _ts(2026, 8, 26, 10, 0, 0)
    assert shop_lazy_refresh("grocery", ctx)["refreshed"] is True
    b = shop_buy("grocery", "限定时装", 1, ctx)
    assert b["ok"] is False and b["reason"] == "stock"


def test_stock_limit_coexist_ruling5():
    """裁决⑤：stock（global）+ limit（personal）同条目并存——两者同时扣减。"""
    ctx = make_ctx()
    b = shop_buy("grocery", "神性碎片", 1, ctx)
    assert b["ok"] is True
    assert ctx["world_stock"]["grocery"]["神性碎片"] == 1
    assert ctx["personal_buys"]["grocery"]["神性碎片"]["count"] == 1
    b2 = shop_buy("grocery", "神性碎片", 1, ctx)
    assert b2["ok"] is False and b2["reason"] == "limit"  # 限购先拦截


def test_tc22_buy_rollback_on_add_failure():
    """TC-22：入包步骤失败 → 整单回滚（货币/库存/限购全恢复）。"""
    ctx = make_ctx(add_item=lambda item_id, count, bound: False)
    b = shop_buy("grocery", "稀有宝箱", 1, ctx)
    assert b["ok"] is False and b["reason"] == "item_add_failed"
    assert ctx["currencies"]["coins"] == 10000
    assert ctx.get("world_stock", {}) == {}
    assert ctx.get("personal_buys", {}) == {}
    assert ctx["inventory"].get("稀有宝箱", 0) == 0


def test_tc23_buy_idempotent_tx():
    """TC-23：同一会话快照 tx_id 重发 → 幂等不双扣。"""
    ctx = make_ctx(tx_id="T1", ledger=set())
    b1 = shop_buy("grocery", "药水", 5, ctx)
    assert b1["ok"] is True and b1["idempotent"] is False
    coins_after = ctx["currencies"]["coins"]
    b2 = shop_buy("grocery", "药水", 5, ctx)
    assert b2["ok"] is True and b2["idempotent"] is True
    assert ctx["currencies"]["coins"] == coins_after
    assert ctx["inventory"].get("药水", 0) == 2 + 5  # 只入一次


def test_buy_no_item_and_not_open():
    """校验链①/解析：商店不存在/未开门/没有这个商品。"""
    assert shop_buy("ghost", "药水", 1, make_ctx())["reason"] == "no_shop"
    ctx = make_ctx(now=_ts(2026, 8, 26, 12, 0, 0))
    assert shop_buy("night_market", "星尘", 1, ctx)["reason"] == "condition"
    assert shop_buy("grocery", "不存在物品", 1, make_ctx())["reason"] == "no_item"


def test_tc38_buy_reputation_requirement():
    """TC-38：条目声望门槛不足 → 「❌ 声望不足：需要 信赖（当前 陌生）」。"""
    ctx = make_ctx(reputation=1)
    b = shop_buy("guild", "银剑", 1, ctx)
    assert b["ok"] is False and b["reason"] == "requirement"
    assert b["message"] == "❌ 声望不足：需要 信赖（当前 陌生）"
    ctx2 = make_ctx(reputation=3)  # 信赖
    assert shop_buy("guild", "银剑", 1, ctx2)["ok"] is True


# ===========================================================================
# ③ 出售：比率向下取整 / sell_price 覆盖 / 拦截 / 不计限购 / 上限
# ===========================================================================
def test_tc25_sell_ratio_floor():
    """TC-25：基准价 12 × 30% = 3.6 向下取整 = 3；立刻到账。"""
    ctx = make_ctx(inventory={"铁矿": 20})
    s = shop_sell("铁矿", 20, ctx)
    assert s["ok"] is True
    assert s["unit"] == 3 and s["total"] == 60
    assert "铁矿×20（+60 金币）" in s["message"]
    assert ctx["currencies"]["coins"] == 10000 + 60
    assert ctx["inventory"]["铁矿"] == 0


def test_tc25b_sell_ratio_floor_partial():
    """TC-25 变体：背包 12 个卖 10 → 到账 30 金币。"""
    ctx = make_ctx()
    s = shop_sell("铁矿", 10, ctx)
    assert s["ok"] is True and s["total"] == 30
    assert ctx["inventory"]["铁矿"] == 2


def test_tc26_sell_price_override():
    """TC-26：sell_price 单条覆盖（忽略通用比率）。"""
    ctx = make_ctx(inventory={"金珠": 1})
    s = shop_sell("金珠", 1, ctx)
    assert s["ok"] is True and s["unit"] == 100000 and s["total"] == 100000


def test_tc27_sell_blocked_items():
    """TC-27：绑定物品 / 任务关键物品（sellable:false + x_ 标记）拒绝出售。"""
    ctx = make_ctx(inventory={"绑定剑": 1, "任务道具": 2})
    assert shop_sell("绑定剑", 1, ctx)["reason"] == "bound"
    assert shop_sell("任务道具", 1, ctx)["reason"] == "unsellable"


def test_tc28_sell_insufficient():
    """TC-28：数量不足 → 「背包里只有 12 个铁矿」。"""
    s = shop_sell("铁矿", 20, make_ctx())
    assert s["ok"] is False and s["reason"] == "insufficient"
    assert s["message"] == "❌ 背包里只有 12 个铁矿"


def test_sell_currency_cap_when_configured():
    """5.1 持有上限：货币 cap 配置后出售到顶 → 拒绝「已满无法再获得」。"""
    settings = {"currencies": [{"id": "coins", "name": "金币", "cap": 10000}],
                "sell_ratio": 0.3}
    ctx = make_ctx(settings=settings, currencies={"coins": 9950}, inventory={"铁矿": 20})
    for _ in range(16):  # 9950 + 16×3 = 9998
        assert shop_sell("铁矿", 1, ctx)["ok"] is True
    assert ctx["currencies"]["coins"] == 9998
    s = shop_sell("铁矿", 1, ctx)  # 9998 + 3 = 10001 > 10000 → 拒
    assert s["ok"] is False and s["reason"] == "currency_cap"
    assert ctx["currencies"]["coins"] == 9998  # 未到账
    assert ctx["inventory"]["铁矿"] == 4  # 20 - 16（被拒的 1 个未扣）= 4


def test_sell_large_confirm_when_configured():
    """定稿 L355：大额确认（可配默认关）；阈值开启时超额先确认不成交。"""
    settings = {"currencies": [{"id": "coins", "name": "金币"}],
                "sell_confirm_threshold": 100}
    ctx = make_ctx(settings=settings, currencies={"coins": 1000}, inventory={"金珠": 1})
    s = shop_sell("金珠", 1, ctx)  # +100000 > 100
    assert s["ok"] is False and s["reason"] == "need_confirm"
    assert ctx["currencies"]["coins"] == 1000 and ctx["inventory"]["金珠"] == 1


def test_sell_idempotent_tx():
    """出售幂等：同 tx_id 重发不重复到账/不重复扣包。"""
    ctx = make_ctx(tx_id="S1", ledger=set())
    assert shop_sell("铁矿", 10, ctx)["ok"] is True
    coins_after = ctx["currencies"]["coins"]
    s2 = shop_sell("铁矿", 10, ctx)
    assert s2["idempotent"] is True
    assert ctx["currencies"]["coins"] == coins_after


# ===========================================================================
# ④ 刷新：daily 惰性补刷 / weekly / none 永不 / once / 黑市重抽 / 离线多天
# ===========================================================================
def test_tc33_daily_lazy_refresh_refill_and_not_soldout_once():
    """TC-33：daily 跨日惰性补刷——库存回满；sold_out_once 不恢复。"""
    ctx = make_ctx()
    ctx["world_stock"] = {"grocery": {"稀有宝箱": 0, "神性碎片": 0}}
    ctx["world_sold_out"] = {"grocery": {"限定时装": True}}
    ctx["last_refresh"] = {"grocery": "2026-08-25"}
    r = shop_lazy_refresh("grocery", ctx)
    assert r["refreshed"] is True
    assert ctx["world_stock"]["grocery"]["稀有宝箱"] == 5
    assert ctx["world_stock"]["grocery"]["神性碎片"] == 2
    assert "限定时装" not in ctx["world_stock"]["grocery"]  # 永久下架
    assert ctx["last_refresh"]["grocery"] == "2026-08-26"


def test_tc35_offline_multiple_days_refresh_once():
    """TC-35：离线跨 3 个刷新周期 → 一次性补到当前（不逐周期重放）。"""
    ctx = make_ctx()
    ctx["world_stock"] = {"grocery": {"稀有宝箱": 0}}
    ctx["last_refresh"] = {"grocery": "2026-08-20"}
    ctx["now"] = _ts(2026, 8, 26, 10, 0, 0)
    r = shop_lazy_refresh("grocery", ctx)
    assert r["refreshed"] is True
    assert ctx["world_stock"]["grocery"]["稀有宝箱"] == 5


def test_tc36_none_never_refresh():
    """TC-36（裁决⑥）：不配置 refresh = none = 永不刷新（库存耗尽即止）。"""
    ctx = make_ctx()
    assert resolve_refresh(None, ctx)["mode"] == "none"
    assert resolve_refresh({}, ctx)["mode"] == "none"
    for _ in range(3):
        assert shop_buy("nostock", "药水", 1, ctx)["ok"] is True
    assert shop_buy("nostock", "药水", 1, ctx)["ok"] is False
    ctx["now"] = _ts(2026, 8, 30, 10, 0, 0)
    assert shop_lazy_refresh("nostock", ctx)["refreshed"] is False
    assert shop_buy("nostock", "药水", 1, ctx)["ok"] is False


def test_refresh_weekly_due():
    """weekly：同周不刷、跨周边界后补刷。"""
    ctx = make_ctx()
    ctx["last_refresh"] = {"weekly_shop": "2026-08-24"}  # 周一
    ctx["world_stock"] = {"weekly_shop": {"药水": 0}}
    ctx["now"] = _ts(2026, 8, 26, 10, 0, 0)  # 周三同周
    assert shop_refresh_due(resolve_shop_by_id(ctx, "weekly_shop"), ctx) is False
    ctx["now"] = _ts(2026, 8, 31, 10, 0, 0)  # 下周一
    assert shop_refresh_due(resolve_shop_by_id(ctx, "weekly_shop"), ctx) is True
    assert shop_lazy_refresh("weekly_shop", ctx)["refreshed"] is True
    assert ctx["world_stock"]["weekly_shop"]["药水"] == 5


def resolve_shop_by_id(ctx, shop_id):
    return ctx["shops"][shop_id]


def test_tc41_blackmarket_redraw_deterministic():
    """TC-41：黑市次日惰性重抽（pool→上架 N 件、价格浮动、货架保持打开）；rng 注入确定性。"""
    ctx_a = make_ctx(now=_ts(2026, 8, 26, 21, 0, 0))
    ctx_b = make_ctx(now=_ts(2026, 8, 26, 21, 0, 0))
    assert shop_browse("black_market", ctx_a)["ok"] is True
    assert shop_browse("black_market", ctx_b)["ok"] is True
    g_a = ctx_a["blackmarket_goods"]["black_market"]
    g_b = ctx_b["blackmarket_goods"]["black_market"]
    assert g_a == g_b  # 同种子同刻 → 同货架（确定性）
    assert len(g_a) == 3
    # 次日 20:00 后重抽
    ctx_a["now"] = _ts(2026, 8, 27, 21, 0, 0)
    assert shop_lazy_refresh("black_market", ctx_a)["refreshed"] is True
    g2 = ctx_a["blackmarket_goods"]["black_market"]
    assert len(g2) == 3 and ctx_a["last_refresh"]["black_market"] == "2026-08-27"


def test_blackmarket_listing_count_engine_consumed():
    """审查_M4实现_批次4 P1-1：引擎 _redraw_blackmarket 读取 listing_count
    （配 listing_count:1 → 首次与次日重抽均只上架 1 件；listing_count 超池 → 夹取 len(pool)）。"""
    # listing_count:1（items=[] pool=3 正典形态）→ 只上架 1 件
    shops = copy.deepcopy(SHOPS)
    shops["black_market"]["listing_count"] = 1
    ctx = make_ctx(shops=shops, now=_ts(2026, 8, 26, 21, 0, 0))
    r = shop_browse("black_market", ctx)
    assert r["ok"] is True and r["total"] == 1
    assert len(ctx["blackmarket_goods"]["black_market"]) == 1
    # 次日重抽同样受 listing_count 约束（rng 注入确定性，同一 ctx 同序列）
    ctx["now"] = _ts(2026, 8, 27, 21, 0, 0)
    assert shop_lazy_refresh("black_market", ctx)["refreshed"] is True
    assert len(ctx["blackmarket_goods"]["black_market"]) == 1
    # listing_count 超池 → 夹取 len(pool)=3（不多抽）
    shops = copy.deepcopy(SHOPS)
    shops["black_market"]["listing_count"] = 99
    ctx = make_ctx(shops=shops, now=_ts(2026, 8, 26, 21, 0, 0))
    r = shop_browse("black_market", ctx)
    assert r["ok"] is True and r["total"] == 3
    assert len(ctx["blackmarket_goods"]["black_market"]) == 3


def test_next_stock_message():
    """「下次补货」文案：daily 明早 HH:MM / weekly 下周一 / none 无。"""
    grocery = SHOPS["grocery"]
    weekly = SHOPS["weekly_shop"]
    nostock = SHOPS["nostock"]
    ctx = make_ctx()
    assert next_stock_message(grocery, ctx) == "明早 05:00"
    assert next_stock_message(weekly, ctx) == "下周一 05:00"
    assert next_stock_message(nostock, ctx) is None


# ===========================================================================
# ⑤ 当前商店机制（地图级状态机）
# ===========================================================================
def test_tc29_30_31_current_shop_set_recover_clear():
    """TC-29/30/31：打开记录→同图 /商店 直达→离图清除回退默认。"""
    ctx = make_ctx()
    assert default_shop_id(ctx) == "grocery"
    set_current_shop(ctx, "blacksmith")
    assert current_shop_id(ctx) == "blacksmith"
    assert resolve_shop_arg(None, ctx) == "blacksmith"  # 中断续购不丢
    clear_current_shop(ctx)
    assert current_shop_id(ctx) is None
    assert resolve_shop_arg(None, ctx) == "grocery"  # 回退全局默认


def test_tc02_32_current_shop_index_and_name_switch():
    """TC-02/32：多店挂载 /商店 2 与 /商店 名称 切换。"""
    ctx = make_ctx(current_shop_refs=["blacksmith", "guild"], current_shop_ref="blacksmith")
    assert resolve_shop_arg(2, ctx) == "guild"
    assert resolve_shop_arg(1, ctx) == "blacksmith"
    assert resolve_shop_arg("铁匠铺", ctx) == "blacksmith"
    assert resolve_shop_arg("冒险者公会", ctx) == "guild"
    assert resolve_shop_arg(5, ctx) is None  # 越界


def test_current_shop_invalid_ref_falls_back():
    """current_shop_ref 失效（引用不存在）→ 回退默认商店。"""
    ctx = make_ctx(current_shop_ref="ghost")
    assert current_shop_id(ctx) is None
    assert resolve_shop_arg(None, ctx) == "grocery"


# ===========================================================================
# ⑥ /商店 列表 + 常量 + 价格工具
# ===========================================================================
def test_shop_list_rows_and_gate_markers():
    """/商店 列表：可见商店全列、声望门槛置灰标记不隐藏。"""
    ctx = make_ctx(reputation=1)
    r = shop_list(ctx)
    ids = {row["id"] for row in r["rows"]}
    assert "grocery" in ids and "guild" in ids and "black_market" in ids
    guild = next(row for row in r["rows"] if row["id"] == "guild")
    assert any("需要 信赖" == m for m in guild["markers"])
    assert guild["greyed"] is True
    assert r["tip"] == "/商店 序号 切换商店"


def test_constants():
    """常量契约：五类型/四模式/三周期/默认上限与比率。"""
    assert SHOP_TYPES == ("normal", "npc", "reputation", "event", "blackmarket")
    assert REFRESH_MODES == ("daily", "weekly", "once", "none")
    assert DEFAULT_BUY_CAP == 99
    assert abs(DEFAULT_SELL_RATIO - 0.30) < 1e-9
    assert REPUTATION_NAMES == ("陌生", "熟悉", "信赖", "崇敬", "传说")


def test_price_for_single_mixed_discount():
    """价格工具：单货币（条目覆盖/基准价兜底）/ 混合支付 / 折扣。"""
    ctx = make_ctx()
    p1 = price_for({"item": "药水", "price": 100}, SHOPS["grocery"], ctx)
    assert p1["kind"] == "single" and p1["unit"] == 100 and p1["currency"] == "coins"
    p2 = price_for({"item": "药水"}, SHOPS["grocery"], ctx)  # 缺省=基准价
    assert p2["unit"] == 100
    p3 = price_for({"item": "神性碎片", "price": {"coins": 50, "gem": 5}},
                   SHOPS["mixed_shop"], ctx)
    assert p3["kind"] == "mixed" and p3["parts"] == {"coins": 50, "gem": 5}
    p4 = price_for({"item": "折扣品", "price": 10000, "discount": 20}, SHOPS["grocery"], ctx)
    assert p4["unit"] == 8000
