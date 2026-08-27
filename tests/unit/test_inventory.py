"""背包引擎单测（M6 批次1·路A · qbot_rpg/core/inventory.py）——TC-INV-01~06 全量 + 规则补充。

依据：细化_M6_三引擎与基础指令（D1）§二（INV-01~INV-11 / TC-INV-01~TC-INV-06）；
【框架】L129-138（堆叠/绑定/药剂同类型回合限次）；【4b】INV-R01~R07 / ITM-07 / ITM-10。

测试风格对齐 tests/unit/test_basic_commands.py：纯 pytest、零 NoneBot、断言具体行为。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from qbot_rpg.core.inventory import (
    POTION_USE_COUNTS_KEY,
    InventoryEngine,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes


def _item(item_id, name, stack_max=99, bound=False, quality="normal", slot=None,
          stats_bonus=None, count=1):
    return ItemInstance(
        item_id=item_id, name=name, count=count, quality=quality, bound=bound,
        stack_max=stack_max, slot=slot, stats_bonus=dict(stats_bonus or {}),
    )


def make_inv_player(inventory=None, attributes=None):
    """构造 InventoryEngine 消费的玩家状态 dict（可变 list inventory）。"""
    return {
        "inventory": list(inventory or []),
        "attributes": attributes or PlayerAttributes(base={"hp": 100.0, "mp": 30.0}),
    }


@dataclass(frozen=True)
class ExpiringPotion(ItemInstance):
    """带 expires_at 的药剂行（INV-10 测试用子类；ItemInstance 领域类型暂无该字段）。"""
    expires_at: Optional[int] = None


# ---------------------------------------------------------------------------
# TC-INV-01 堆叠合并（INV-01）
# ---------------------------------------------------------------------------
def test_tc_inv_01_stack_merge():
    """TC-INV-01：背包空 + 药水 stack_max=99；add ×5 → add ×3 → 单行 count=8（无第二行）。"""
    eng = InventoryEngine()
    player = make_inv_player()
    potion = _item("potion", "药水")

    assert eng.add_item(player, potion, 5)["ok"] is True
    assert eng.add_item(player, potion, 3)["ok"] is True

    assert len(player["inventory"]) == 1
    assert player["inventory"][0].count == 8
    assert player["inventory"][0].item_id == "potion"


# ---------------------------------------------------------------------------
# TC-INV-02 超上限开新行（INV-02）
# ---------------------------------------------------------------------------
def test_tc_inv_02_split_new_row():
    """TC-INV-02：已有 药水×95（单行）→ add ×10 → 两行 99/6，不合并为 105 行。"""
    eng = InventoryEngine()
    player = make_inv_player([_item("potion", "药水", count=95)])

    r = eng.add_item(player, _item("potion", "药水"), 10)

    assert r["ok"] is True
    assert [row.count for row in player["inventory"]] == [99, 6]
    assert sum(row.count for row in player["inventory"]) == 105


# ---------------------------------------------------------------------------
# TC-INV-03 不可堆叠实例（INV-03）
# ---------------------------------------------------------------------------
def test_tc_inv_03_non_stackable_instance():
    """TC-INV-03：两件铁剑（实例化 stack_max=1）→ 两独立行各 count=1、各带独立快照，永不合并且不计数叠加。"""
    eng = InventoryEngine()
    player = make_inv_player()
    sword = _item("iron_sword", "铁剑", stack_max=1, quality="rare",
                  bound=True, slot="weapon", stats_bonus={"str": 5.0})

    assert eng.add_item(player, sword, 1)["ok"] is True
    assert eng.add_item(player, sword, 1)["ok"] is True

    assert len(player["inventory"]) == 2                      # 两独立行
    assert all(row.count == 1 for row in player["inventory"])  # 恒 count=1
    assert all(row.stats_bonus == {"str": 5.0} for row in player["inventory"])
    # 不计数叠加（count() 实例行按 1 计，INV-06）
    assert eng.count(player, "iron_sword") == 2


# ---------------------------------------------------------------------------
# TC-INV-04 remove 不足拒绝（INV-05）
# ---------------------------------------------------------------------------
def test_tc_inv_04_remove_not_enough():
    """TC-INV-04：背包 铁矿×3 → remove 铁矿×5 → 拒绝、仍 ×3、无部分扣减。"""
    eng = InventoryEngine()
    player = make_inv_player([_item("iron_ore", "铁矿", count=3)])

    r = eng.remove_item(player, "iron_ore", 5)

    assert r["ok"] is False and r["reason"] == "not_enough"
    assert eng.count(player, "iron_ore") == 3                 # 数量不变
    assert len(player["inventory"]) == 1


# ---------------------------------------------------------------------------
# TC-INV-05 绑定拒售/拒赠（INV-07）
# ---------------------------------------------------------------------------
def test_tc_inv_05_bound_reject():
    """TC-INV-05：绑定铁剑（bound=true）remove/赠送/出售 → 校验拦截、背包数量不变。"""
    eng = InventoryEngine()
    bound_sword = _item("iron_sword", "铁剑", stack_max=1, bound=True, count=1)
    player = make_inv_player([bound_sword])

    r = eng.remove_item(player, "iron_sword", 1)

    assert r["ok"] is False and r["reason"] == "bound"
    assert "绑定" in r["message"]
    assert eng.count(player, "iron_sword") == 1               # 背包数量不变
    assert len(player["inventory"]) == 1


def test_tc_inv_05b_mixed_bound_prefers_unbound():
    """补充：同 item 绑定行与未绑定行分开成行——扣减优先非绑定行，绑定行保留（INV-07）。"""
    eng = InventoryEngine()
    player = make_inv_player([
        _item("potion", "药水", bound=False, count=2),
        _item("potion", "药水", bound=True, count=5),
    ])

    r = eng.remove_item(player, "potion", 2)
    assert r["ok"] is True
    # 非绑定行（2 个）已扣光并整行清理，绑定行 5 个保留（INV-04 count=0 行清理）
    assert [(row.bound, row.count) for row in player["inventory"]] == [(True, 5)]
    assert eng.count(player, "potion") == 5

    # 再扣 1（仅余绑定行）→ 绑定拒绝（INV-07/TC-INV-05）
    r2 = eng.remove_item(player, "potion", 1)
    assert r2["ok"] is False and r2["reason"] == "bound"
    # 扣 6 > 合计 5 → 数量不足优先（INV-05，先于绑定判定）
    r3 = eng.remove_item(player, "potion", 6)
    assert r3["ok"] is False and r3["reason"] == "not_enough"


# ---------------------------------------------------------------------------
# TC-INV-06 数量上限截断（INV-08）
# ---------------------------------------------------------------------------
def test_tc_inv_06_single_add_truncate():
    """TC-INV-06：add 药水×150 → 按 99 截断执行（added=99）+ 提示「最多一次购买 99 个」。

    注（D1 TC-INV-06 数值口径）：D1 用例「99/51」与规则 INV-08「按 99 截断执行」及
    B-4 裁决（数量截断作用于单次 add 的 count 参数）不一致——本实现按 B-4 截断 count
    （150→99 实际入包），行为断言对齐 INV-08/B-4。
    """
    eng = InventoryEngine()
    player = make_inv_player()
    potion = _item("potion", "药水")

    r = eng.add_item(player, potion, 150)

    assert r["ok"] is True
    assert r["added"] == 99                                   # 截断执行
    assert r["truncated"] is True
    assert r["message"] == "最多一次购买 99 个"
    assert eng.count(player, "potion") == 99
    assert [row.count for row in player["inventory"]] == [99]


def test_tc_inv_06b_truncate_merge_existing():
    """补充（INV-08「或并入既有行」）：既有 药水×8 → add 150 截断为 99 → 并入拆行 99/8。"""
    eng = InventoryEngine()
    player = make_inv_player([_item("potion", "药水", count=8)])

    r = eng.add_item(player, _item("potion", "药水"), 150)

    assert r["ok"] is True and r["truncated"] is True
    assert [row.count for row in player["inventory"]] == [99, 8]


# ---------------------------------------------------------------------------
# 补充：INV-09 格数上限 / INV-10 到期惰性移除 / INV-11 药剂类型键与限次落点
# ---------------------------------------------------------------------------
def test_supplement_inv_09_capacity():
    """INV-09：inventory_capacity 可配；超出行数 → 整单拒绝（INV-E2 不静默丢物、不分段收）。"""
    eng = InventoryEngine(inventory_capacity=2)
    player = make_inv_player([_item("a", "甲", count=1)])

    # 第 2 行：允许
    assert eng.add_item(player, _item("b", "乙", count=1), 1)["ok"] is True
    # 第 3 行：整单拒绝
    r = eng.add_item(player, _item("c", "丙", count=1), 1)
    assert r["ok"] is False and r["reason"] == "inventory_full"
    assert len(player["inventory"]) == 2                      # 不静默丢物/不分段收

    # 默认不限（INV-09：缺省无格数饥饿）
    eng2 = InventoryEngine()
    p2 = make_inv_player()
    for i in range(10):
        assert eng2.add_item(p2, _item(f"i{i}", f"物{i}", count=1), 1)["ok"] is True
    assert len(p2["inventory"]) == 10


def test_supplement_inv_10_lazy_expire_purge(monkeypatch):
    """INV-10：任何背包操作先查 expires_at，已到期 → 惰性移除该行并重算加成层属性。"""
    recalc_calls = {"n": 0}
    real = calc_all_final_attributes
    monkeypatch.setattr(
        "qbot_rpg.core.inventory.calc_all_final_attributes",
        lambda *a, **k: recalc_calls.update(n=recalc_calls["n"] + 1) or real(*a, **k),
    )

    eng = InventoryEngine(now_fn=lambda: 2000)
    expired = ExpiringPotion(
        item_id="buff_potion", name="增补药水", count=1, quality="normal",
        bound=False, stack_max=99, expires_at=1000,
    )
    alive = ExpiringPotion(
        item_id="buff_potion", name="增补药水", count=1, quality="normal",
        bound=False, stack_max=99, expires_at=3000,
    )
    player = make_inv_player([expired, alive])

    assert eng.count(player, "buff_potion") == 1   # 到期行已惰性移除
    assert len(player["inventory"]) == 1
    assert player["inventory"][0].expires_at == 3000
    assert recalc_calls["n"] == 1                  # 触发属性重算钩子（INV-10）

    # 无 now_fn → 到期检查停用（工程补白），不误删
    eng2 = InventoryEngine()
    p2 = make_inv_player([expired])
    assert eng2.count(p2, "buff_potion") == 1
    assert len(p2["inventory"]) == 1


def test_supplement_inv_11_potion_type_hook():
    """INV-11：引擎提供 potion_type 键与回合限次计数落点（判定归战斗/使用入口）。"""
    eng = InventoryEngine()
    # potion_type 键（ITM-17，缺省 "auto"）
    assert eng.potion_type_of(_item("potion", "药水")) == "auto"

    @dataclass(frozen=True)
    class TypedPotion(ItemInstance):
        potion_type: str = "heal"

    assert eng.potion_type_of(TypedPotion("hp", "回血药", 1, "normal", False)) == "heal"

    # 计数落点：player["potion_use_counts"][potion_type]（回血/回蓝可各 1 次）
    player = make_inv_player()
    counts = eng.potion_use_counts(player)
    assert player[POTION_USE_COUNTS_KEY] is counts
    counts["heal"] = counts.get("heal", 0) + 1
    assert eng.potion_use_counts(player)["heal"] == 1
