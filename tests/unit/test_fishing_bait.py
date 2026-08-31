"""M10 批1·路1A：鱼饵体系单测（qbot_rpg/core/fishing_bait.py 纯函数直测）。

文件名：tests/unit/test_fishing_bait.py
创建时间：2026-08-31
作者：Hermes 子agent-1A（M10 钓鱼实现组批1·路1A：鱼饵体系）

功能描述：qbot_rpg.core.fishing_bait 纯函数直测（零 NoneBot、确定性、零定时器/零睡眠）：
  - bait_ids_of：settings.fishing.bait_ids 读取（5 档默认兜底 / 显式覆盖 / 空/非法回退）
  - is_bait：饵档命中 / 非饵 / 非 str item 判定
  - is_preferred_bait：对口饵判定（FishDef 访问器 / raw dict / 空 preferred_bait）
  - bait_bonus_of：默认 {rare:8,gold:2} / 覆盖 / 非法回退
  - bait_available：有饵 True / 无饵 False（含 count_item hook 与 inventory 兜底）
  - consume_bait：无饵保底不扣（had_bait=False 仍 ok）/ 有饵扣 1 / 多饵择一（档序）/
    扣减 hook 失败回退后续档 / remove_item hook 优先
  - 契约要点回归：1 次 = 1 饵（L96）；无饵保底不卡死（L16）

依据：
  - docs/m10_shared_contract.md §一（settings.fishing bait_ids/bait_bonus 默认值）
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §1.2（F-12 preferred_bait）/ §五（V3 双向引用）
  - 钓鱼玩法设计定稿 v1.0.1 §1 M2（L16 无饵保底不卡死 / L96 1 次=1 饵）
  - 模式参考：tests/unit/test_fishing_settings.py（_as_dict helper + 三态容错直测）
    / tests/unit/test_fishing.py（兄弟路1B：FishDef 夹具形态）

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""

from __future__ import annotations

from typing import Any, Dict, cast

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_bait import (
    bait_available,
    bait_bonus_of,
    bait_ids_of,
    consume_bait,
    is_bait,
    is_preferred_bait,
)

# 5 档默认饵（契约 §一 / 定稿 L74）
DEFAULT_BAITS = ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫", "饵_龙涎"]

# 对口饵默认加成（契约 §一 / 定稿 L75）
DEFAULT_BONUS = {"rare": 8, "gold": 2}


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _as_dict(obj: object) -> Dict[str, Any]:
    """fishing_cfg/bait_bonus_of 返回类型收窄读取（对齐 test_fishing_settings）。"""
    return cast(Dict[str, Any], obj)


def _fish(preferred: object = None) -> FishDef:
    """FishDef 夹具（silver_carp 形态，preferred_bait 可注入）。"""
    raw: Dict[str, object] = {
        "id": "silver_carp",
        "name": "银鳞鲤",
        "rarity": "normal",
        "size_min": 10.0,
        "size_max": 60.0,
        "weight_min": 0.3,
        "weight_max": 5.0,
        "spots": ["gp_moon_grass"],
    }
    if preferred is not None:
        raw["preferred_bait"] = preferred
    return cast(FishDef, FishDef.from_entry(raw))


def _ctx(inventory: Dict[str, int] | None = None,
         with_hooks: bool = True) -> Dict[str, Any]:
    """ctx 夹具：inventory 计数映射 + count_item/remove_item hooks（M9 _inventory_hooks 形态）。"""
    inv: Dict[str, int] = dict(inventory or {})
    ctx: Dict[str, Any] = {"inventory": inv}

    def count_item(item_id: str) -> int:
        return int(inv.get(item_id, 0))

    def remove_item(item_id: str, count: int) -> bool:
        cur = int(inv.get(item_id, 0))
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True

    if with_hooks:
        ctx["count_item"] = count_item
        ctx["remove_item"] = remove_item
    return ctx


# ---------------------------------------------------------------------------
# bait_ids_of：5 档默认 / 覆盖 / 回退
# ---------------------------------------------------------------------------
def test_bait_ids_default_full_settings() -> None:
    """settings 全量缺 fishing 段 → 5 档默认（契约 §一 缺段兜底）。"""
    got = bait_ids_of({"no_fishing_here": True})
    assert got == DEFAULT_BAITS
    assert len(got) == 5


def test_bait_ids_default_none() -> None:
    """None 入参 → 5 档默认（三态容错兜底）。"""
    assert bait_ids_of(None) == DEFAULT_BAITS


def test_bait_ids_override_section() -> None:
    """settings.fishing.bait_ids 显式覆盖（部分档生效）。"""
    cfg = {"fishing": {"bait_ids": ["饵_蚯蚓", "饵_黄金虫"]}}
    assert bait_ids_of(cfg) == ["饵_蚯蚓", "饵_黄金虫"]


def test_bait_ids_override_ctx() -> None:
    """ctx 形态（含 settings 键）→ 解包后读 bait_ids。"""
    ctx = {"settings": {"fishing": {"bait_ids": ["饵_龙涎"]}}}
    assert bait_ids_of(ctx) == ["饵_龙涎"]


def test_bait_ids_empty_falls_back_default() -> None:
    """bait_ids 显式空列表 → 5 档默认（空/非法回退，契约 §一 兜底）。"""
    cfg: dict = {"fishing": {"bait_ids": []}}
    assert bait_ids_of(cfg) == DEFAULT_BAITS


def test_bait_ids_non_list_falls_back_default() -> None:
    """bait_ids 非 list（str）→ 5 档默认。"""
    cfg = {"fishing": {"bait_ids": "饵_蚯蚓"}}
    assert bait_ids_of(cfg) == DEFAULT_BAITS


def test_bait_ids_filters_non_str() -> None:
    """bait_ids 混入非 str 元素 → 过滤后保留 str 档。"""
    cfg = {"fishing": {"bait_ids": ["饵_蚯蚓", 42, "", "饵_小鱼"]}}
    assert bait_ids_of(cfg) == ["饵_蚯蚓", "饵_小鱼"]


# ---------------------------------------------------------------------------
# is_bait：档内命中 / 非饵 / 非 str
# ---------------------------------------------------------------------------
def test_is_bait_hit() -> None:
    """饵档内条目 → True。"""
    assert is_bait({"fishing": {"bait_ids": DEFAULT_BAITS}}, "饵_蚯蚓") is True


def test_is_bait_miss() -> None:
    """非饵条目 / 不在档内 → False。"""
    assert is_bait({"fishing": {"bait_ids": DEFAULT_BAITS}}, "potion") is False


def test_is_bait_non_str() -> None:
    """item_id 非 str / 空 → False（防误判）。"""
    assert is_bait({"fishing": {"bait_ids": DEFAULT_BAITS}}, 42) is False
    assert is_bait({"fishing": {"bait_ids": DEFAULT_BAITS}}, "") is False


# ---------------------------------------------------------------------------
# is_preferred_bait：对口饵判定（FishDef / raw dict / 空）
# ---------------------------------------------------------------------------
def test_is_preferred_bait_fishdef_hit() -> None:
    """FishDef.preferred_bait 命中 → True。"""
    fish = _fish(["饵_蚯蚓"])
    assert is_preferred_bait(fish, "饵_蚯蚓") is True


def test_is_preferred_bait_fishdef_miss() -> None:
    """FishDef.preferred_bait 未命中 → False。"""
    fish = _fish(["饵_蚯蚓"])
    assert is_preferred_bait(fish, "饵_黄金虫") is False


def test_is_preferred_bait_raw_dict() -> None:
    """raw dict 形态（含 preferred_bait 键）判定。"""
    species = {"id": "silver_carp", "preferred_bait": ["饵_蚯蚓", "饵_面团"]}
    assert is_preferred_bait(species, "饵_面团") is True
    assert is_preferred_bait(species, "饵_龙涎") is False


def test_is_preferred_bait_empty() -> None:
    """preferred_bait 缺失/空 → False（任何饵都不对口）。"""
    assert is_preferred_bait(_fish(None), "饵_蚯蚓") is False
    assert is_preferred_bait(_fish([]), "饵_蚯蚓") is False


# ---------------------------------------------------------------------------
# bait_bonus_of：默认 / 覆盖 / 非法回退
# ---------------------------------------------------------------------------
def test_bait_bonus_default() -> None:
    """缺省 → {rare:8, gold:2}（定稿 L75 / 契约 §一）。"""
    assert bait_bonus_of({}) == DEFAULT_BONUS


def test_bait_bonus_override() -> None:
    """显式覆盖 rare/gold。"""
    cfg = {"fishing": {"bait_bonus": {"rare": 10, "gold": 5}}}
    assert bait_bonus_of(cfg) == {"rare": 10, "gold": 5}


def test_bait_bonus_partial_keeps_default() -> None:
    """只给 rare → gold 保留默认（逐键合并兜底）。"""
    cfg = {"fishing": {"bait_bonus": {"rare": 12}}}
    got = bait_bonus_of(cfg)
    assert got == {"rare": 12, "gold": 2}


def test_bait_bonus_invalid_falls_back() -> None:
    """bait_bonus 非法（非 Mapping / 负值 / bool）→ 默认 {rare:8,gold:2}。"""
    assert bait_bonus_of({"fishing": {"bait_bonus": "x"}}) == DEFAULT_BONUS
    assert bait_bonus_of({"fishing": {"bait_bonus": {"rare": -1, "gold": 2}}}) == DEFAULT_BONUS
    assert bait_bonus_of({"fishing": {"bait_bonus": {"rare": True, "gold": 2}}}) == DEFAULT_BONUS


# ---------------------------------------------------------------------------
# bait_available：有饵 / 无饵（含 hook 与 inventory 兜底）
# ---------------------------------------------------------------------------
def test_bait_available_true() -> None:
    """持有任一档饵 → True。"""
    ctx = _ctx({"饵_蚯蚓": 3})
    assert bait_available(ctx, "qid_1") is True


def test_bait_available_false() -> None:
    """背包无任何 bait_ids 档内条目 → False（无饵保底前置判定）。"""
    ctx = _ctx({"potion": 10})
    assert bait_available(ctx, "qid_1") is False


def test_bait_available_falls_back_inventory_without_hooks() -> None:
    """无 count_item hook 时走 inventory 计数映射兜底。"""
    ctx = _ctx({"饵_面团": 1}, with_hooks=False)
    assert bait_available(ctx, "qid_1") is True


# ---------------------------------------------------------------------------
# consume_bait：无饵保底不扣 / 有饵扣 1 / 多饵择一 / hook 失败回退
# ---------------------------------------------------------------------------
def test_consume_bait_no_bait_no_deduct() -> None:
    """无饵保底（L16 铁律）：背包无任何饵 → had_bait=False、不扣饵、仍 ok。"""
    ctx = _ctx({"potion": 10})
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res == {"ok": True, "used": None, "had_bait": False}
    # 不扣任何物品（无饵不扣）
    assert ctx["inventory"] == {"potion": 10}


def test_consume_bait_no_inventory_key() -> None:
    """ctx 无 inventory 键 → 视为无饵，不炸，仍 ok（无饵保底不卡死）。"""
    res = _as_dict(consume_bait({"qid": "qid_1"}, "qid_1"))
    assert res == {"ok": True, "used": None, "had_bait": False}


def test_consume_bait_with_bait_deduct_one() -> None:
    """有饵：按档序取持有第一档扣 1（L96：1 次 = 1 饵）。"""
    ctx = _ctx({"饵_蚯蚓": 3, "饵_龙涎": 5})
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res == {"ok": True, "used": "饵_蚯蚓", "had_bait": True}
    assert ctx["inventory"]["饵_蚯蚓"] == 2
    assert ctx["inventory"]["饵_龙涎"] == 5


def test_consume_bait_multi_bait_first_held_by_order() -> None:
    """多饵择一：档序第一持有（跳过缺货档，取第一有货档）。"""
    ctx = _ctx({"饵_黄金虫": 1})  # 档序第 4 档持有，前 3 档 0
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res == {"ok": True, "used": "饵_黄金虫", "had_bait": True}
    assert ctx["inventory"]["饵_黄金虫"] == 0


def test_consume_bait_last_bait_depletes() -> None:
    """持有 1 个饵 → 扣后为 0（档仍在但计数归零）。"""
    ctx = _ctx({"饵_面团": 1})
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res["used"] == "饵_面团" and res["had_bait"] is True
    assert ctx["inventory"]["饵_面团"] == 0


def test_consume_bait_remove_hook_failure_falls_back_next() -> None:
    """档 1 扣减 hook 失败（不足/异常）→ 回退档 2 扣减。"""
    ctx = _ctx({"饵_蚯蚓": 0, "饵_小鱼": 2})
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res == {"ok": True, "used": "饵_小鱼", "had_bait": True}
    assert ctx["inventory"]["饵_小鱼"] == 1


def test_consume_bait_inventory_without_hooks() -> None:
    """无 remove_item hook → inventory 计数映射就地扣减兜底。"""
    ctx = _ctx({"饵_蚯蚓": 2}, with_hooks=False)
    res = _as_dict(consume_bait(ctx, "qid_1"))
    assert res == {"ok": True, "used": "饵_蚯蚓", "had_bait": True}
    assert ctx["inventory"]["饵_蚯蚓"] == 1
