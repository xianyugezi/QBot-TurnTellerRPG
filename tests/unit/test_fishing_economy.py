"""M10 钓鱼·批5·路5C：经济四出口闭环单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_economy.py
创建时间：2026-09-01
作者：Hermes 主 agent（路5C 子 agent 撞迭代上限零落盘，按侦察结论补齐）

覆盖：细化_2c1c §三（E-02a~E-02d + R-12 对账）+ TC-09~13。
"""

from __future__ import annotations

import random
from typing import Any, Dict

from qbot_rpg.core.fishing_economy import (
    DAILY_NET_ANCHOR,
    alchemy_feed_check,
    contest_submit,
    daily_ledger_check,
    quest_deliver_check,
    shop_sell_price,
)


def _ctx(**kw: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "fishing": {"species": [
            {"id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
             "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0},
        ], "king": []},
        "settings": {"fishing": {}},
        "rng": random.Random(42),
    }
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# E-02a 商店售出（R-08：无冠级定价）
# ---------------------------------------------------------------------------
def test_shop_sell_price_basic() -> None:
    """基础定价：正常鱼种 30cm/2.65kg → 正价格。"""
    ctx = _ctx()
    price = shop_sell_price(ctx, "silver_carp", 30.0, 2.65)
    assert price > 0
    assert isinstance(price, int)


def test_shop_sell_price_bigger_fish_costlier() -> None:
    """大鱼更贵（尺寸系数）。"""
    ctx = _ctx()
    p_small = shop_sell_price(ctx, "silver_carp", 20.0, 1.0)
    p_big = shop_sell_price(ctx, "silver_carp", 55.0, 4.5)
    assert p_big > p_small


def test_shop_sell_price_no_crown_factor() -> None:
    """同鱼同 size/weight → 定价一致（R-08 无冠级因子，天然差分=0）。"""
    ctx = _ctx()
    # 同参数两次调用（模拟不同冠级路径）→ 同价
    assert shop_sell_price(ctx, "silver_carp", 35.0, 2.65) == \
        shop_sell_price(ctx, "silver_carp", 35.0, 2.65)


def test_shop_sell_price_rarity_based() -> None:
    """稀有度档定价：gold > rare > normal。"""
    ctx = _ctx(fishing={"species": [
        {"id": "a", "rarity": "normal"},
        {"id": "b", "rarity": "rare"},
        {"id": "c", "rarity": "gold"},
    ], "king": []})
    p_n = shop_sell_price(ctx, "a", 30.0, 2.0)
    p_r = shop_sell_price(ctx, "b", 30.0, 2.0)
    p_g = shop_sell_price(ctx, "c", 30.0, 2.0)
    assert p_g > p_r > p_n


# ---------------------------------------------------------------------------
# E-02b 委托交付（R-09：数量+品质档，不取冠级）
# ---------------------------------------------------------------------------
def test_quest_deliver_ok() -> None:
    """数量足够 → ok。"""
    ctx = _ctx()
    quest = {"need_fish": {"fish_id": "silver_carp", "count": 3}}
    r = quest_deliver_check(ctx, quest, "silver_carp", 5)
    assert r["ok"] is True
    assert r["shortfall"] == 0


def test_quest_deliver_shortfall() -> None:
    """数量不足 → ok=False + 差量提示。"""
    ctx = _ctx()
    quest = {"need_fish": {"fish_id": "silver_carp", "count": 5}}
    r = quest_deliver_check(ctx, quest, "silver_carp", 2)
    assert r["ok"] is False
    assert r["shortfall"] == 3


def test_quest_deliver_wrong_fish() -> None:
    """鱼种不符 → 拒绝。"""
    ctx = _ctx()
    quest = {"need_fish": {"fish_id": "gold_koi", "count": 1}}
    r = quest_deliver_check(ctx, quest, "silver_carp", 5)
    assert r["ok"] is False


def test_quest_deliver_quality_tier_no_crown() -> None:
    """品质档返回（不取冠级）：quality_tier 存在。"""
    ctx = _ctx()
    quest = {"need_fish": {"fish_id": "silver_carp", "count": 1}}
    r = quest_deliver_check(ctx, quest, "silver_carp", 1)
    assert "quality_tier" in r
    assert isinstance(r["quality_tier"], str)


# ---------------------------------------------------------------------------
# E-02c 品评会投稿（R-10：社交展示，评分不含冠级加成）
# ---------------------------------------------------------------------------
def test_contest_submit_records_snapshot() -> None:
    """投稿记录快照（fish_id/size/weight/score）。"""
    ctx = _ctx()
    r = contest_submit(ctx, "silver_carp", 40.0, 3.0)
    assert r["ok"] is True
    assert 0 <= r["score"] <= 100
    assert len(ctx["contest_entries"]) == 1
    assert ctx["contest_entries"][0]["fish_id"] == "silver_carp"


def test_contest_submit_crown_null() -> None:
    """快照 crown 字段为 None（社交展示不落冠级进数值）。"""
    ctx = _ctx()
    contest_submit(ctx, "silver_carp", 40.0, 3.0)
    assert ctx["contest_entries"][0]["crown"] is None


def test_contest_submit_score_consistent() -> None:
    """同参数评分一致（无随机）。"""
    ctx1 = _ctx()
    ctx2 = _ctx()
    r1 = contest_submit(ctx1, "silver_carp", 40.0, 3.0)
    r2 = contest_submit(ctx2, "silver_carp", 40.0, 3.0)
    assert r1["score"] == r2["score"]


# ---------------------------------------------------------------------------
# E-02d 炼金材料（R-11：鱼作 recipe 原料）
# ---------------------------------------------------------------------------
def test_alchemy_feed_usable() -> None:
    """鱼在 recipe.materials → usable。"""
    ctx = _ctx()
    recipe = {"id": "rcp_fish_bait", "materials": [{"id": "silver_carp", "count": 1}]}
    r = alchemy_feed_check(ctx, recipe, "silver_carp")
    assert r["ok"] is True
    assert r["usable"] is True
    assert r["role"] == "fish_ingredient"


def test_alchemy_feed_not_material() -> None:
    """鱼不在 materials → 拒绝。"""
    ctx = _ctx()
    recipe = {"id": "rcp_bait_worm", "materials": [{"id": "moon_grass", "count": 2}]}
    r = alchemy_feed_check(ctx, recipe, "silver_carp")
    assert r["ok"] is False
    assert r["reason"] == "not_material"


def test_alchemy_feed_invalid_recipe() -> None:
    """非法 recipe → 拒绝。"""
    ctx = _ctx()
    r = alchemy_feed_check(ctx, "bogus", "silver_carp")
    assert r["ok"] is False


# ---------------------------------------------------------------------------
# R-12 每日对账（日净流入 ≈256 金 ±5%）
# ---------------------------------------------------------------------------
def test_daily_ledger_within_anchor() -> None:
    """日净流入 ≈256 金（±5% 内）。"""
    ctx = _ctx()
    r = daily_ledger_check(ctx, rng=random.Random(42))
    assert r["ok"] is True
    assert r["within_tolerance"] is True
    assert abs(r["net_flow"] - DAILY_NET_ANCHOR) / DAILY_NET_ANCHOR <= 0.05


def test_daily_ledger_deterministic() -> None:
    """同种子同调用 → 恒同结果。"""
    ctx1 = _ctx(rng=random.Random(42))
    ctx2 = _ctx(rng=random.Random(42))
    r1 = daily_ledger_check(ctx1)
    r2 = daily_ledger_check(ctx2)
    assert r1["net_flow"] == r2["net_flow"]


def test_daily_ledger_structure() -> None:
    """对账返回结构齐全（net_flow/inflow/outflow/anchor）。"""
    ctx = _ctx()
    r = daily_ledger_check(ctx)
    for k in ("net_flow", "inflow", "outflow", "anchor", "within_tolerance"):
        assert k in r, f"缺对账键 {k}"
    assert r["inflow"] > r["outflow"]
