"""M10 钓鱼·批5·路5A：钓鱼职业熟练度 + 钓鱼王授予单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_job.py
创建时间：2026-09-01
作者：Hermes 主 agent（路5A 子 agent 撞迭代上限零落盘，按侦察结论补齐）

覆盖：细化_2c1c §四（R-13/R-14）+ §二 2.4（R-07）+ TC-14~18。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.fishing_job import (
    DEFAULT_KING_BONUS_PCT,
    FISHING_JOB_ID,
    KING_MIN_VICTORIES,
    fish_king_eligible,
    grant_fishing_exp,
    grant_fishing_king,
    king_bonus,
)


def _ctx(**kw: Any) -> Dict[str, Any]:
    ps: Dict[str, Any] = {"proficiency": {}}
    ctx: Dict[str, Any] = {
        "codex_state": {},
        "fishing": {
            "species": [{"id": "silver_carp", "name": "银鳞鲤", "rarity": "normal"}],
            "king": [],
        },
        "player": {"persistent_state": ps, "proficiency": ps["proficiency"],
                   "title_state": {"owned": [], "equipped": []}},
        "settings": {"fishing": {"king_bonus_pct": 5}},
    }
    ctx.update(kw)
    return ctx


def _codex_fish(ctx: Dict[str, Any]) -> Dict[str, Any]:
    st = ctx.setdefault("codex_state", {})
    fish = st.setdefault("fish", {})
    return fish


def _light_all(ctx: Dict[str, Any], victories: int = 2) -> None:
    """图鉴全亮 + king_victory_count 达标。"""
    fish = _codex_fish(ctx)
    fish["silver_carp"] = {"seen": True, "caught_count": 1,
                           "best_crown": "normal", "reverse_crown_count": 0}
    meta = fish.setdefault("__meta__", {})
    meta["king_victory_count"] = victories


# ---------------------------------------------------------------------------
# 经验入账（R-13）
# ---------------------------------------------------------------------------
def test_grant_exp_basic() -> None:
    """经验入账：10 exp → proficiency.fishing.exp=10（source=gather 倍率 1.0）。"""
    ctx = _ctx()
    r = grant_fishing_exp(ctx, 10)
    assert r["ok"] is True
    assert r["exp_gained"] == 10
    prof = ctx["player"]["proficiency"]["fishing"]
    assert prof["exp"] == 10


def test_grant_exp_zero_or_invalid() -> None:
    """0/负数/非法 → 不报错 exp_gained=0。"""
    ctx = _ctx()
    assert grant_fishing_exp(ctx, 0)["exp_gained"] == 0
    assert grant_fishing_exp(ctx, -5)["exp_gained"] == 0
    assert grant_fishing_exp(ctx, "bogus")["exp_gained"] == 0


def test_grant_exp_accumulates_and_levels() -> None:
    """多次入账累计 + 跨阈值升级（100 → level 1，exp 扣阈值剩 20）。"""
    ctx = _ctx()
    grant_fishing_exp(ctx, 60)
    grant_fishing_exp(ctx, 60)
    prof = ctx["player"]["proficiency"]["fishing"]
    assert prof["exp"] == 20  # 120 - 100（level 1 阈值）＝ 剩余
    assert prof["level"] == 1


def test_grant_exp_no_player_fallback() -> None:
    """无 player → 直传 proficiency 形态兜底（对齐 settle）。"""
    ctx = _ctx()
    ctx.pop("player")
    ctx["proficiency"] = {}
    r = grant_fishing_exp(ctx, 10)
    assert r["ok"] is True
    assert ctx["proficiency"]["fishing"]["exp"] == 10


# ---------------------------------------------------------------------------
# 钓鱼王资格判定（R-07 + R-14）
# ---------------------------------------------------------------------------
def test_eligible_all_lit_and_victories() -> None:
    """图鉴全亮 + 讨伐≥2 → eligible。"""
    ctx = _ctx()
    _light_all(ctx, victories=2)
    r = fish_king_eligible(ctx)
    assert r["eligible"] is True
    assert r["complete"] is True
    assert r["king_victory_count"] == 2
    assert r["reason"] is None


def test_ineligible_codex_incomplete() -> None:
    """图鉴未全亮 → reason=codex_incomplete。"""
    ctx = _ctx()
    r = fish_king_eligible(ctx)  # 无任何 codex 条目
    assert r["eligible"] is False
    assert r["reason"] == "codex_incomplete"
    assert r["missing_species"] == ["silver_carp"]


def test_ineligible_victories_insufficient() -> None:
    """图鉴全亮但讨伐<2 → reason=king_victories_insufficient。"""
    ctx = _ctx()
    _light_all(ctx, victories=1)
    r = fish_king_eligible(ctx)
    assert r["eligible"] is False
    assert r["reason"] == "king_victories_insufficient"


def test_missing_species_listed() -> None:
    """部分未亮 → missing_species 列出未亮鱼种。"""
    ctx = _ctx(fishing={"species": [
        {"id": "silver_carp", "name": "银鳞鲤"},
        {"id": "gold_koi", "name": "金锦鲤"},
    ], "king": []})
    _light_all(ctx, victories=2)  # 只亮了 silver_carp
    r = fish_king_eligible(ctx)
    assert r["complete"] is False
    assert r["missing_species"] == ["gold_koi"]


# ---------------------------------------------------------------------------
# 授予（R-14：幂等）
# ---------------------------------------------------------------------------
def test_grant_king_when_eligible() -> None:
    """全亮 + 讨伐≥2 → 授予钓鱼王称号（title_state.owned 含 fishing）。"""
    ctx = _ctx()
    _light_all(ctx, victories=2)
    r = grant_fishing_king(ctx)
    assert r["ok"] is True
    assert r["granted"] is True
    assert r["title_id"] == "fishing"
    assert "fishing" in ctx["player"]["title_state"]["owned"]


def test_grant_king_idempotent() -> None:
    """已拥有 → 幂等 granted=False。"""
    ctx = _ctx()
    _light_all(ctx, victories=2)
    grant_fishing_king(ctx)
    r2 = grant_fishing_king(ctx)
    assert r2["granted"] is False


def test_grant_king_not_eligible() -> None:
    """未达标 → 不授予。"""
    ctx = _ctx()
    r = grant_fishing_king(ctx)
    assert r["ok"] is False
    assert "fishing" not in ctx["player"]["title_state"]["owned"]


# ---------------------------------------------------------------------------
# 称号加成（R-14：全属性+X%）
# ---------------------------------------------------------------------------
def test_king_bonus_default() -> None:
    """缺省 5%：{key, percent:5, pct:0.05, enabled:true}。"""
    r = king_bonus({"fishing": {}})
    assert r["key"] == "fishing_king_bonus"
    assert r["percent"] == DEFAULT_KING_BONUS_PCT
    assert r["pct"] == 0.05
    assert r["enabled"] is True


def test_king_bonus_custom() -> None:
    """自定义 10 → percent=10。"""
    r = king_bonus({"fishing": {"king_bonus_pct": 10}})
    assert r["percent"] == 10.0
    assert r["pct"] == 0.10


def test_king_bonus_disabled() -> None:
    """0 → enabled=False。"""
    r = king_bonus({"fishing": {"king_bonus_pct": 0}})
    assert r["enabled"] is False


def test_king_bonus_invalid_falls_default() -> None:
    """非法（负/非数）→ 缺省 5%。"""
    assert king_bonus({"fishing": {"king_bonus_pct": -3}})["percent"] == DEFAULT_KING_BONUS_PCT
    assert king_bonus({"fishing": {"king_bonus_pct": "x"}})["percent"] == DEFAULT_KING_BONUS_PCT
    assert king_bonus(None)["percent"] == DEFAULT_KING_BONUS_PCT


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
def test_constants() -> None:
    """常量齐全。"""
    assert FISHING_JOB_ID == "fishing"
    assert KING_MIN_VICTORIES == 2
    assert DEFAULT_KING_BONUS_PCT == 5.0
