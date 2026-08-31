"""M10 钓鱼·批4·路4B：鱼王事件单测（主 agent 收口补齐）。

文件名：tests/unit/test_fishing_king.py
创建时间：2026-08-31
作者：Hermes 主 agent（路4B 子 agent 撞迭代上限零落盘，按侦察结论补齐）

覆盖：细化_2c1a §三（TC-12/13/14）+ 细化_2c1c §一（TC-01~04）。
"""

from __future__ import annotations

import random
from typing import Any, Dict

from qbot_rpg.core.fishing_king import (
    king_event_available,
    king_trigger_count,
    king_victory_record,
)

# 基准时钟（UTC+8 epoch 秒，远离 dayroll 05:00 日界）
BASE_NOW = 1_800_000_000

_KING_ROW = {
    "id": "king_carp",
    "species_id": "silver_carp",
    "enemy_id": "lake_leech",
    "hint": "金闪",
    "window_daily": 2,
    "chance": 0.3,
    "enabled": True,
}


def _ctx(**kw: Any) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "now": BASE_NOW,
        "settings": {"fishing": {
            "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
        }},
        "fishing": {"species": [], "king": [dict(_KING_ROW)]},
        "codex_state": {},
        "rng": random.Random(2026),
    }
    ctx.update(kw)
    return ctx


class _FixedRng:
    """固定序列 rng（触发判定消费 1 次 random()——chance roll）。"""

    def __init__(self, values: tuple) -> None:
        self._values = list(values)

    def random(self) -> float:
        if not self._values:
            raise AssertionError("rng 序列耗尽（触发判定恰消费 1 次）")
        return self._values.pop(0)


# ---------------------------------------------------------------------------
# 触发判定（R-01）
# ---------------------------------------------------------------------------
def test_trigger_hit() -> None:
    """chance roll 命中 → ok + king_row + hint + triggered。"""
    ctx = _ctx(rng=_FixedRng((0.1,)))  # 0.1 < 0.3 命中
    r = king_event_available(ctx, "silver_carp")
    assert r["ok"] is True
    assert r["triggered"] is True
    assert r["king_row"]["enemy_id"] == "lake_leech"
    assert r["hint"] == "金闪"


def test_trigger_chance_miss() -> None:
    """chance roll 未命中 → reason=chance_miss。"""
    ctx = _ctx(rng=_FixedRng((0.9,)))  # 0.9 >= 0.3 未命中
    r = king_event_available(ctx, "silver_carp")
    assert r["ok"] is False
    assert r["reason"] == "chance_miss"
    assert r["triggered"] is False


def test_trigger_disabled() -> None:
    """enabled=false → reason=disabled（不 roll 不计数）。"""
    ctx = _ctx(settings={"fishing": {"king_event": {"enabled": False}}})
    r = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert r["ok"] is False
    assert r["reason"] == "disabled"
    assert king_trigger_count(ctx) == 0


def test_trigger_no_king_row() -> None:
    """无 king 行 → reason=no_king_row。"""
    ctx = _ctx(fishing={"species": [], "king": []})
    r = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert r["ok"] is False
    assert r["reason"] == "no_king_row"


def test_trigger_window_exhausted() -> None:
    """当日已触发 2 次（window_daily=2）→ 第 3 次拦截 reason=window_exhausted（TC-13/R-02）。"""
    ctx = _ctx()
    # 触发 2 次（都命中）
    king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert king_trigger_count(ctx) == 2
    # 第 3 次被拦
    r = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert r["ok"] is False
    assert r["reason"] == "window_exhausted"


def test_trigger_count_increments_on_miss() -> None:
    """未命中也计数（R-02 门控用尝试计，无论胜负）。"""
    ctx = _ctx()
    king_event_available(ctx, "silver_carp", rng=_FixedRng((0.9,)))
    assert king_trigger_count(ctx) == 1


def test_row_override_window_and_chance() -> None:
    """行级覆写 window_daily/chance > settings（K-2）。"""
    row = dict(_KING_ROW)
    row["window_daily"] = 1
    row["chance"] = 0.9
    ctx = _ctx(fishing={"species": [], "king": [row]})
    r = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.5,)))  # 0.5 < 0.9 命中
    assert r["ok"] is True
    # 第 2 次被 window=1 拦
    r2 = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.5,)))
    assert r2["ok"] is False
    assert r2["reason"] == "window_exhausted"


# ---------------------------------------------------------------------------
# 每日窗口跨日重置（R-02）
# ---------------------------------------------------------------------------
def test_window_reset_next_day() -> None:
    """跨日（now 隔天）→ 触发计数清零（king_victory_count 不随日清零）。"""
    ctx = _ctx()
    king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert king_trigger_count(ctx) == 2
    # 次日（+1 天）
    ctx["now"] = BASE_NOW + 86400
    assert king_trigger_count(ctx) == 0
    # 重新可触发
    r = king_event_available(ctx, "silver_carp", rng=_FixedRng((0.1,)))
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# 胜利计次（R-03：供图鉴补全）
# ---------------------------------------------------------------------------
def test_victory_record_increments() -> None:
    """讨伐胜利计 1 次：king_victory_count+1（图鉴补全 R-07 读取）。"""
    ctx = _ctx()
    r = king_victory_record(ctx)
    assert r["ok"] is True
    assert r["king_victory_count"] == 1
    r2 = king_victory_record(ctx)
    assert r2["king_victory_count"] == 2


def test_victory_count_survives_day_rollover() -> None:
    """胜利计数跨日不清零（累计，供补全判定）。"""
    ctx = _ctx()
    king_victory_record(ctx)
    king_victory_record(ctx)
    ctx["now"] = BASE_NOW + 86400
    king_trigger_count(ctx)  # 触发窗口重置
    assert king_victory_record(ctx)["king_victory_count"] == 3


# ---------------------------------------------------------------------------
# 确定性（种子 42/2026）
# ---------------------------------------------------------------------------
def test_deterministic_same_seed() -> None:
    """同种子同调用序 → 恒同结果。"""
    ctx1 = _ctx(rng=random.Random(42))
    ctx2 = _ctx(rng=random.Random(42))
    r1 = [king_event_available(ctx1, "silver_carp")["triggered"] for _ in range(10)]
    r2 = [king_event_available(ctx2, "silver_carp")["triggered"] for _ in range(10)]
    assert r1 == r2
