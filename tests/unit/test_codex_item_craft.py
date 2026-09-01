"""图鉴归属判定单测（tests/unit/test_codex_item_craft.py · M11 批2 路2A）。

覆盖细化_4d 契约 TC-03/04（item/craft 数据驱动归属 + 隐藏要素归册）。
"""
from __future__ import annotations

from typing import Any, Mapping, MutableMapping

from qbot_rpg.core.codex import item_craft_relation


class _FakeRegistry:
    """registry 替身（all_ids + resolve + modules_raw）。"""

    def __init__(self, tables: Mapping[str, tuple],
                 forge_items: list | None = None,
                 recipe_outputs: Mapping[str, str] | None = None) -> None:
        self._tables = tables
        self._recipe_outputs = dict(recipe_outputs or {})
        self.modules_raw: dict = {}
        if forge_items:
            self.modules_raw["forge"] = {"trees": [
                {"nodes": [{"item": i} for i in forge_items]}]}

    def all_ids(self, kind: str) -> tuple:
        return self._tables.get(kind, ())

    def resolve_name(self, rid: str):
        return rid.upper()

    def resolve(self, rid: str, kind: str):
        if kind == "recipe":
            out = self._recipe_outputs.get(rid)
            return {"id": rid, "output": {"item": out}} if out else None
        return None


def _ctx(forge_items: list | None = None,
         recipe_outputs: Mapping[str, str] | None = None) -> MutableMapping[str, Any]:
    reg = _FakeRegistry(
        {"item": ("dagger", "fire_potion", "iron_ore", "world_book"),
         "recipe": tuple(recipe_outputs or {})},
        forge_items=forge_items, recipe_outputs=recipe_outputs,
    )
    return {"registry": reg, "codex_state": {}, "settings": {}}


# ---------------------------------------------------------------------------
# TC-03 item/craft 归属判定
# ---------------------------------------------------------------------------
def test_tc03_item_craft_relation():
    """匕首/火伤药→craft（制造源）；矿铁/世界之书→item（无制造路径）。"""
    ctx = _ctx(forge_items=["dagger"],
               recipe_outputs={"rcp_fire": "fire_potion"})
    # forge 树节点产物 → craft
    assert item_craft_relation(ctx, "dagger") == "craft"
    # 炼金 recipe 产物 → craft
    assert item_craft_relation(ctx, "fire_potion") == "craft"
    # 无制造路径 → item
    assert item_craft_relation(ctx, "iron_ore") == "item"
    assert item_craft_relation(ctx, "world_book") == "item"


def test_tc03_no_manufacture_source_fallback():
    """无 forge/recipe 数据 → 全部回落 item（fail-safe）。"""
    ctx = _ctx()
    assert item_craft_relation(ctx, "dagger") == "item"
    assert item_craft_relation(ctx, "iron_ore") == "item"


def test_tc03_empty_or_bad_id():
    """空/非法 id → item（fail-safe）。"""
    ctx = _ctx(forge_items=["dagger"])
    assert item_craft_relation(ctx, "") == "item"
    assert item_craft_relation(ctx, "??") == "item"


# ---------------------------------------------------------------------------
# TC-04 隐藏要素归册（数据驱动：隐藏 BOSS→monster / 鱼王→fish / 彩蛋→item /
# 隐藏配方→craft——归册由各系统 mark_seen 的 category 参数承载，本测试验证
# item_craft_relation 对隐藏配方产物的判定）
# ---------------------------------------------------------------------------
def test_tc04_hidden_recipe_product_craft():
    """隐藏配方产物（秘传配方·龙涎饵）→ craft（recipe output 命中）。"""
    ctx = _ctx(recipe_outputs={"rcp_dragon_bait": "dragon_bait"})
    assert item_craft_relation(ctx, "dragon_bait") == "craft"


def test_tc04_hidden_quest_item_item():
    """彩蛋物品（码头旧怀表，无制造路径）→ item。"""
    ctx = _ctx()
    assert item_craft_relation(ctx, "old_watch") == "item"


# ---------------------------------------------------------------------------
# 归属判定器导出
# ---------------------------------------------------------------------------
def test_item_craft_relation_exported():
    """归属判定器在 __all__ 中公开导出。"""
    import qbot_rpg.core.codex as codex_mod

    assert "item_craft_relation" in codex_mod.__all__
