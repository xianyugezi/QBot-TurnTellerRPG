"""M10 钓鱼·批2·路2C：fishing_roll 种子化 roll 概率单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_roll.py
创建时间：2026-08-31
作者：Hermes 主 agent（路2C 子 agent 撞 429 半落盘，测试由主 agent 补齐）

覆盖：细化_2c1b §4.2 roll 概率锚点（TC-15/16）+ 工程补白 R-1~R-4。
"""

from __future__ import annotations

import random

from qbot_rpg.core.fishing_roll import (
    roll_rarity,
    roll_weights,
    has_matching_bait,
    pull_odds_of,
    bait_bonus_of,
    rod_full_bonus_of,
)


def _rng(seed: int = 2026) -> random.Random:
    return random.Random(seed)


def _base_ctx(**kw: object) -> dict:
    ctx: dict = {"now": 1000, "rng": _rng(2026)}
    ctx.update(kw)
    return ctx


# ---------------------------------------------------------------------------
# 权重构成（roll_weights）
# ---------------------------------------------------------------------------
def test_auto_weights_baseline() -> None:
    """AUTO 自动收杆 → 基础 70/25/5（定稿 L94 基础锚点）。"""
    ctx = _base_ctx()
    w = roll_weights("auto", {}, ctx)
    assert w == {"normal": 70, "rare": 25, "gold": 5}


def test_full_no_bait_falls_back_pull_odds() -> None:
    """FULL 无对口饵 → 插值默认 60/31/9（pull_odds 可配键，R-1）。"""
    ctx = _base_ctx(fish_state={"target_species_id": "silver_carp"},
                    fish_table={"silver_carp": {"id": "silver_carp", "preferred_bait": []}})
    w = roll_weights("full", {}, ctx)
    assert w == {"normal": 60, "rare": 31, "gold": 9}


def test_full_with_matching_bait_full_odds() -> None:
    """FULL + 对口饵 → 满配 54/37/9（定稿 L94 满配锚点，TC-15）。"""
    ctx = _base_ctx(
        fish_state={"target_species_id": "silver_carp"},
        fish_table={"silver_carp": {"id": "silver_carp",
                                    "preferred_bait": ["饵_蚯蚓"]}},
        inventory={"饵_蚯蚓": 1},
    )
    w = roll_weights("full", {}, ctx)
    assert w == {"normal": 54, "rare": 37, "gold": 9}


def test_bait_bonus_reads_cfg() -> None:
    """bait_bonus 从 settings.fishing 读取（默认 rare+8/gold+2）。"""
    b = bait_bonus_of({"fishing": {"bait_bonus": {"rare": 8, "gold": 2}}})
    assert b == {"rare": 8, "gold": 2}
    b2 = bait_bonus_of({})
    assert b2 == {"rare": 8, "gold": 2}


def test_rod_full_bonus_reads_cfg() -> None:
    """rod_full_bonus 从 settings.fishing 读取（默认 rare+4/gold+2）。"""
    r = rod_full_bonus_of({"fishing": {"rod_full_bonus": {"rare": 4, "gold": 2}}})
    assert r == {"rare": 4, "gold": 2}
    r2 = rod_full_bonus_of({})
    assert r2 == {"rare": 4, "gold": 2}


def test_pull_odds_reads_cfg() -> None:
    """pull_odds 可配键读取（R-1：settings.fishing.pull_odds）。"""
    p = pull_odds_of({"fishing": {"pull_odds": {"normal": 50, "rare": 40, "gold": 10}}})
    assert p == {"normal": 50, "rare": 40, "gold": 10}
    p2 = pull_odds_of({})
    assert p2 == {"normal": 60, "rare": 31, "gold": 9}


# ---------------------------------------------------------------------------
# roll_rarity 种子化收敛（TC-15/16）
# ---------------------------------------------------------------------------
def test_auto_rarity_distribution_seed2026() -> None:
    """AUTO 种子 2026 N=100000 → 70/25/5 收敛 ±0.5pp（TC-16）。"""
    rng = _rng(2026)
    ctx = _base_ctx(rng=rng)
    n = 100000
    cnt = {"normal": 0, "rare": 0, "gold": 0}
    for _ in range(n):
        cnt[roll_rarity("auto", {}, ctx, rng)] += 1
    assert abs(cnt["normal"] / n - 0.70) < 0.005
    assert abs(cnt["rare"] / n - 0.25) < 0.005
    assert abs(cnt["gold"] / n - 0.05) < 0.005


def test_full_matching_distribution_seed2026() -> None:
    """FULL+对口饵 种子 2026 N=100000 → 54/37/9 收敛 ±0.5pp（TC-15）。"""
    rng = _rng(2026)
    ctx = _base_ctx(
        rng=rng,
        fish_state={"target_species_id": "silver_carp"},
        fish_table={"silver_carp": {"id": "silver_carp",
                                    "preferred_bait": ["饵_蚯蚓"]}},
        inventory={"饵_蚯蚓": 1},
    )
    n = 100000
    cnt = {"normal": 0, "rare": 0, "gold": 0}
    for _ in range(n):
        cnt[roll_rarity("full", {}, ctx, rng)] += 1
    assert abs(cnt["normal"] / n - 0.54) < 0.005
    assert abs(cnt["rare"] / n - 0.37) < 0.005
    assert abs(cnt["gold"] / n - 0.09) < 0.005


def test_roll_deterministic_same_seed() -> None:
    """同种子同调用序 → 恒同结果（确定性，M43）。"""
    ctx1 = _base_ctx(rng=_rng(42))
    ctx2 = _base_ctx(rng=_rng(42))
    r1 = [roll_rarity("auto", {}, ctx1, ctx1["rng"]) for _ in range(20)]
    r2 = [roll_rarity("auto", {}, ctx2, ctx2["rng"]) for _ in range(20)]
    assert r1 == r2


def test_roll_full_no_bait_uses_pull_odds() -> None:
    """FULL 无对口饵 种子 2026 → 60/31/9 收敛（R-1 插值默认）。"""
    rng = _rng(2026)
    ctx = _base_ctx(rng=rng, fish_state={"target_species_id": "silver_carp"},
                    fish_table={"silver_carp": {"id": "silver_carp",
                                                "preferred_bait": []}})
    n = 50000
    cnt = {"normal": 0, "rare": 0, "gold": 0}
    for _ in range(n):
        cnt[roll_rarity("full", {}, ctx, rng)] += 1
    assert abs(cnt["normal"] / n - 0.60) < 0.01
    assert abs(cnt["rare"] / n - 0.31) < 0.01
    assert abs(cnt["gold"] / n - 0.09) < 0.01


def test_roll_unknown_choice_falls_auto() -> None:
    """非法 choice → 防御回落 auto（R-4）。"""
    rng = _rng(2026)
    ctx = _base_ctx(rng=rng)
    assert roll_rarity("bogus", {}, ctx, rng) in ("normal", "rare", "gold")


# ---------------------------------------------------------------------------
# has_matching_bait（对口饵判定，R-3）
# ---------------------------------------------------------------------------
def test_has_matching_bait_true() -> None:
    """目标鱼种 preferred_bait 含玩家持有饵 → True。"""
    ctx = _base_ctx(
        fish_state={"target_species_id": "silver_carp"},
        fish_table={"silver_carp": {"id": "silver_carp",
                                    "preferred_bait": ["饵_蚯蚓"]}},
        inventory={"饵_蚯蚓": 3},
    )
    assert has_matching_bait(ctx) is True


def test_has_matching_bait_no_inventory() -> None:
    """preferred_bait 但玩家无该饵 → False（吃不到 bait_bonus）。"""
    ctx = _base_ctx(
        fish_state={"target_species_id": "silver_carp"},
        fish_table={"silver_carp": {"id": "silver_carp",
                                    "preferred_bait": ["饵_蚯蚓"]}},
        inventory={},
    )
    assert has_matching_bait(ctx) is False


def test_has_matching_bait_no_target() -> None:
    """无目标鱼种 → False（R-3）。"""
    ctx = _base_ctx(fish_state={}, fish_table={})
    assert has_matching_bait(ctx) is False


def test_has_matching_bait_no_preferred() -> None:
    """目标鱼种无 preferred_bait → False。"""
    ctx = _base_ctx(
        fish_state={"target_species_id": "silver_carp"},
        fish_table={"silver_carp": {"id": "silver_carp"}},
        inventory={"饵_蚯蚓": 1},
    )
    assert has_matching_bait(ctx) is False
