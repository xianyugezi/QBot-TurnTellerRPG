"""图鉴加权完成度单测（tests/unit/test_codex_weights.py · M11 批2 路2B）。

覆盖细化_4d 契约 TC-06/07/08/10/14（加权公式/权重配置/热重载回落/悬空 ID/分册条件键）。
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.codex import codex_progress, mark_seen


class _FakeRegistry:
    """registry 替身（all_ids + resolve + modules_raw）。"""

    def __init__(self, tables: Mapping[str, tuple]) -> None:
        self._tables = tables
        self.modules_raw: dict = {}

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        return rid.upper()

    def resolve(self, rid: str, kind: str):
        return None


def _reg(monster_n: int = 29, fish_n: int = 20, item_n: int = 15,
         craft_n: int = 10) -> _FakeRegistry:
    return _FakeRegistry({
        "enemy": tuple(f"enemy_{i}" for i in range(monster_n)),
        "item": tuple(f"item_{i}" for i in range(item_n)),
    })


def _ctx(monster_n: int = 29, fish_n: int = 20, item_n: int = 15,
         craft_n: int = 10, weights: dict | None = None) -> MutableMapping[str, Any]:
    reg = _reg(monster_n, fish_n, item_n, craft_n)
    settings: dict = {}
    if weights is not None:
        settings["codex"] = {"weights": weights}
    return {
        "registry": reg,
        "codex_state": {},
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": settings,
        "fishing": {"species": [{"id": f"fish_{i}"} for i in range(fish_n)],
                    "king": [{"id": "king_carp"}]},
    }


# ---------------------------------------------------------------------------
# TC-06 默认等权
# ---------------------------------------------------------------------------
def test_tc06_default_equal_weights():
    """默认等权 1:1:1:1：monster 12/29、fish 3/21（species20+king1）、item 0/15、
    craft 0/10 → T=13.916%（4d TC-02 鱼册分母含 king 条目）。"""
    ctx = _ctx()
    # monster 12/29（enemy_0..11），fish 3/21（fish_0..2，走 fishing species+king）
    for i in range(12):
        mark_seen(ctx, "monster", f"enemy_{i}", f"怪{i}")
    for i in range(3):
        mark_seen(ctx, "fish", f"fish_{i}", f"鱼{i}")
    gp = codex_progress(ctx)
    # V=[41.379, 14.286, 0, 0] → T=(41.379+14.286)/4=13.916%（未取整）
    assert abs(gp["pct"] - 13.916) < 0.01


# ---------------------------------------------------------------------------
# TC-07 自定义权重
# ---------------------------------------------------------------------------
def test_tc07_custom_weights():
    """自定义权重 {monster:2, fish:1, item:1, craft:0} → T=24.13%（fish 3/21）。"""
    ctx = _ctx(weights={"monster": 2, "fish": 1, "item": 1, "craft": 0})
    for i in range(12):
        mark_seen(ctx, "monster", f"enemy_{i}", f"怪{i}")
    for i in range(3):
        mark_seen(ctx, "fish", f"fish_{i}", f"鱼{i}")
    gp = codex_progress(ctx)
    # T=(2×41.379+14.286+0+0)/(2+1+1+0)=97.044/4=24.26%（fish 3/21）
    assert abs(gp["pct"] - 24.26) < 0.01


# ---------------------------------------------------------------------------
# TC-08 热重载分母变化回落
# ---------------------------------------------------------------------------
def test_tc08_hot_reload_denominator_growth():
    """热重载 monster 分母 29→32 → 单册 12/32=37.5% + 全局重算回落。"""
    ctx = _ctx(monster_n=29)
    for i in range(12):
        mark_seen(ctx, "monster", f"enemy_{i}", f"怪{i}")
    ctx["registry"] = _reg(monster_n=32)
    p = codex_progress(ctx, "monster")
    assert p["total"] == 32
    assert abs(p["pct"] - 37.5) < 0.01


# ---------------------------------------------------------------------------
# TC-10 悬空 ID 不计数
# ---------------------------------------------------------------------------
def test_tc10_dangling_id_not_counted():
    """悬空 ID（state 塞未注册 ID）→ 交集核算不计数（COD-01）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "enemy_0", "怪0")
    # 塞悬空 ID 进 state（热重载删除后遗留）
    ctx["codex_state"]["monster"]["ghost_id"] = {"seen": True, "killed": True}
    gp = codex_progress(ctx)
    # monster seen 仍 1（ghost_id 不在分母交集）
    assert gp["seen"] == 1
    assert abs(gp["pct"] - (100 / 29 + 0 + 0 + 0) / 4) < 0.01


# ---------------------------------------------------------------------------
# TC-14 分册 100% 互不阻塞（param 条件键复核）
# ---------------------------------------------------------------------------
def test_tc14_category_param_independent():
    """分册条件键：monster 100% → 分册满足、总册未满不满足（互不干扰）。"""
    from qbot_rpg.engine.condition_engine import eval_condition

    ctx = _ctx(monster_n=3, fish_n=20, item_n=15, craft_n=10)
    for i in range(3):
        mark_seen(ctx, "monster", f"enemy_{i}", f"怪{i}")
    # 分册投影（装配层注入，批1 已做 codex_categories）
    ctx["codex_categories"] = {"monster": 100.0, "fish": 0.0, "item": 0.0, "craft": 0.0}
    cond_monster = {"var": "codex", "op": "ge", "value": 100, "param": "monster"}
    cond_total = {"var": "codex", "op": "ge", "value": 100}
    assert eval_condition(cond_monster, ctx) is True
    assert eval_condition(cond_total, ctx) is False  # 总册未满（3/29 等其它册）
