"""M7 图鉴引擎测试（tests/unit/test_codex.py · F-11/F-12 · R-17~R-20/E-04）。

覆盖：mark_seen 首见/重复 · mark_killed · unlock_lore · 完成度计算（单册/全局）·
ctx["codex"] 投影 · ??? 不泄露 · registry 分母 · 去重。
"""

from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.codex import (
    CATEGORIES,
    codex_progress,
    codex_view,
    mark_killed,
    mark_seen,
    unlock_lore,
)


class _FakeRegistry:
    """内容注册表替身（all_ids/resolve_name）。"""

    def __init__(self, tables: Mapping[str, tuple]) -> None:
        self._tables = tables

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        for kind_ids in self._tables.values():
            if rid in kind_ids:
                return rid.upper()
        return None


def _reg() -> _FakeRegistry:
    return _FakeRegistry({
        "enemy": ("rock_weasel", "wood_wolf", "moon_wolf"),
        "equipment": ("iron_sword", "iron_shield", "steel_blade"),
        "item": ("potion", "hi_potion"),
    })


def _ctx() -> MutableMapping[str, Any]:
    return {
        "registry": _reg(),
        "codex_state": {},
        "event_counts": {},
        "longline_counters": {},
        "persistent_state": {"event_log": []},
        "settings": {},
    }


# ---------------------------------------------------------------------------
# mark_seen 首见/重复
# ---------------------------------------------------------------------------
def test_mark_seen_first_and_duplicate() -> None:
    """首见写 state + 事件/日志；重复 mark 不重复日志。"""
    ctx = _ctx()
    r1 = mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    assert r1["first_seen"] is True
    assert ctx["codex_state"]["monster"]["rock_weasel"]["seen"] is True
    r2 = mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    assert r2["first_seen"] is False


def test_mark_seen_unknown_category() -> None:
    """未知分册 → ok=False 不崩。"""
    ctx = _ctx()
    assert mark_seen(ctx, "fossil", "x", "X")["ok"] is False


# ---------------------------------------------------------------------------
# mark_killed / unlock_lore
# ---------------------------------------------------------------------------
def test_mark_killed_after_seen() -> None:
    """已见后补记击杀。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "wood_wolf", "林狼")
    assert mark_killed(ctx, "monster", "wood_wolf")["ok"] is True
    assert ctx["codex_state"]["monster"]["wood_wolf"]["killed"] is True


def test_mark_killed_not_seen() -> None:
    """未见不能补击杀。"""
    ctx = _ctx()
    assert mark_killed(ctx, "monster", "moon_wolf")["ok"] is False


def test_unlock_lore() -> None:
    """传闻解锁（F-16 定向线索接口）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "moon_wolf", "蚀月之狼")
    assert unlock_lore(ctx, "monster", "moon_wolf")["ok"] is True
    assert ctx["codex_state"]["monster"]["moon_wolf"]["lore_unlocked"] is True


# ---------------------------------------------------------------------------
# 完成度计算
# ---------------------------------------------------------------------------
def test_progress_single_and_global() -> None:
    """单册 pct（seen/total）与全局（等权分册均值）。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")   # monster 1/3
    p = codex_progress(ctx, "monster")
    assert p["seen"] == 1 and p["total"] == 3
    assert abs(p["pct"] - 100 / 3) < 0.001
    mark_seen(ctx, "item", "potion", "药水")            # item 1/2
    gp = codex_progress(ctx)
    # 单册 pct: monster=33.33, weapon=0, item=50, alchemy=0, fish=0 → 均值 ≈ 16.67
    # （M8 批11-2 收口：/图鉴 合并 alchemy 分册入总览；M10 批4：fish 分册入总览）
    assert abs(gp["pct"] - (100 / 3 + 0 + 50 + 0 + 0) / 5) < 0.01


class _WeaponFakeRegistry:
    """registry 替身（all_ids + resolve 返回带 type 的 items 定义）。

    QA P2-9 修复验证：内容包把武器配置在 items.json（type=weapon）而
    equipment.json 可为空——weapon 分册分母应含 items type=weapon 条目。
    """

    def __init__(self, tables: Mapping[str, tuple],
                 item_types: Mapping[str, str] | None = None) -> None:
        self._tables = tables
        self._item_types: Mapping[str, str] = item_types or {}

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        return rid.upper()

    def resolve(self, rid: str, kind: str):
        # items 表条目 → {id, name, type}
        if kind == "item":
            return {"id": rid, "name": rid,
                    "type": self._item_types.get(rid, "material")}
        return None


def test_weapon_progress_total_from_items_type_weapon() -> None:
    """QA P2-9：weapon 分册分母 = equipment 表 ∪ items type=weapon（equipment 空时非 0）。"""
    reg = _WeaponFakeRegistry(
        {"equipment": (), "item": ("potion", "iron_sword", "flame_sword", "leaf_vest")},
        {"iron_sword": "weapon", "flame_sword": "weapon", "leaf_vest": "armor"},
    )
    ctx = dict(_ctx())
    ctx["registry"] = reg
    p = codex_progress(ctx, "weapon")
    assert p["total"] == 2  # 仅 type=weapon 计入（armor/药水不计）
    mark_seen(ctx, "weapon", "iron_sword", "铁剑")
    p2 = codex_progress(ctx, "weapon")
    assert p2["seen"] == 1 and p2["total"] == 2
    # 旧行为（仅 equipment 表）不回归：equipment 表非空时仍计数
    reg2 = _WeaponFakeRegistry({"equipment": ("iron_sword", "steel_blade"), "item": ("potion",)})
    ctx2 = dict(_ctx())
    ctx2["registry"] = reg2
    assert codex_progress(ctx2, "weapon")["total"] == 2


def test_weapon_codex_view_lists_type_weapon_items() -> None:
    """QA P2-9：weapon 分册页展示 items type=weapon 条目（未收集显示 ???）。"""
    reg = _WeaponFakeRegistry(
        {"equipment": (), "item": ("iron_sword", "flame_sword")},
        {"iron_sword": "weapon", "flame_sword": "weapon"},
    )
    ctx = dict(_ctx())
    ctx["registry"] = reg
    mark_seen(ctx, "weapon", "iron_sword", "铁剑")
    view = codex_view(ctx, "weapon")
    names = {e["name"] for e in view["entries"]}
    assert view["total"] == 2
    assert "铁剑" in names and "???" in names  # flame_sword 未收集 → ???



def test_progress_empty_registry() -> None:
    """无 registry → total=0 pct=0（fail-safe）。"""
    ctx = _ctx()
    ctx.pop("registry")
    assert codex_progress(ctx)["pct"] == 0.0


def test_codex_projection_updated() -> None:
    """ctx["codex"] 投影随 mark 刷新（未取整，条件引擎精确比较）。"""
    ctx = _ctx()
    assert ctx.get("codex", 0.0) == 0.0
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    # 5 册均值（M8 批11-2 收口：alchemy 分册入总览；M10 批4：fish 分册入总览，pct=0）
    assert abs(float(ctx["codex"]) - (100 / 3 + 0 + 0 + 0 + 0) / 5) < 0.01


# ---------------------------------------------------------------------------
# 展示数据源（??? 不泄露）
# ---------------------------------------------------------------------------
def test_codex_view_unknown_hidden() -> None:
    """未见条目名称「???」不泄露。"""
    ctx = _ctx()
    mark_seen(ctx, "monster", "rock_weasel", "岩鼬")
    view = codex_view(ctx, "monster")
    names = {e["name"] for e in view["entries"]}
    assert "岩鼬" in names
    assert "???" in names          # wood_wolf/moon_wolf 未见 → ???
    assert "木狼" not in names      # 未收集名称不泄露


def test_codex_view_pagination() -> None:
    """分册分页 5 条/页 + 夹取。"""
    ctx = _ctx()
    for rid in ("rock_weasel", "wood_wolf", "moon_wolf"):
        mark_seen(ctx, "monster", rid, rid)
    view = codex_view(ctx, "monster", page=1)
    assert len(view["entries"]) == 3
    assert view["pages"] == 1
    v2 = codex_view(ctx, "monster", page=99)
    assert v2["page"] == 1  # 夹取


def test_codex_view_unknown_category() -> None:
    """未知分册 → ok=False。"""
    ctx = _ctx()
    assert codex_view(ctx, "fossil")["ok"] is False


# ---------------------------------------------------------------------------
# 契约常量
# ---------------------------------------------------------------------------
def test_categories_contract() -> None:
    """三分册 key 映射（monster→enemy / weapon→equipment / item→item）。"""
    assert CATEGORIES["monster"] == ("enemy",)
    assert CATEGORIES["weapon"] == ("equipment",)
    assert CATEGORIES["item"] == ("item",)
