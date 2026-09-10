"""同 id 多品质行保真——P0 修复复现测试（tests/unit/test_inventory_quality_rows.py）。

背景（2026-09-06 黑盒发现 → 2026-09-11 修复）：同一物品存在多品质实例行时
（如普通药剂×6 + 传说药剂×1），任意一次背包扣减/产出（赠送/使用/战斗用药/
炼金产出）后，runner 落档 merge（shop_tx._ctx_inventory_to_player）把同 id
全部行并入首实例、其余行清空 → 附加品质行被静默吞掉（实测两行传说物品全消失）。

修复口径（2026-09-11）：ctx 计数（去品质扁平总数）与旧行总数的差值按
「加 → 并入普通行（无则新建）；扣 → 非绑定优先、低品质优先、行序」分摊；
各行 quality/bound/slot/stats 原样保留。

依据：
  - docs/细化/细化_4b_物品与背包契约.md（row_key = item_id + 实例键 + 品质 +
    绑定态聚合键语义）
  - qbot_rpg/assembly/runner.py 落档 merge 段（M8 批12 收口：_m8_dirty_inventory
    → _ctx_inventory_to_player）

铁律：零 IO 纯函数（直接驱动 shop_tx._ctx_inventory_to_player / _player_after_buy）。
"""

from __future__ import annotations

from qbot_rpg.commands.shop_tx import _ctx_inventory_to_player, _player_after_buy
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player

ITEMS = {"potion": {"id": "potion", "name": "药剂"}}


def _inst(item_id="potion", name="药剂", count=1, quality="normal", bound=False):
    """构造背包实例行（测试夹具）。"""
    return ItemInstance(item_id=item_id, name=name, count=count, quality=quality, bound=bound)


class TestQualityRowPreservation:
    """merge 保真：同 id 多品质行不被吞（P0 核心断言）。"""

    def test_reproducer_legendary_row_survives_deduct(self):
        """P0 复现：普通×6 + 传说×1，操作后（ctx n=6）→ 传说行保留、普通减 1。"""
        old = (_inst(count=6), _inst(count=1, quality="legendary"))
        out = _ctx_inventory_to_player({"potion": 6}, old, ITEMS)
        by = {(i.quality, int(i.count)) for i in out}
        assert ("legendary", 1) in by
        assert ("normal", 5) in by
        assert sum(int(i.count) for i in out) == 6

    def test_no_change_all_rows_kept(self):
        """无净变化（ctx n=7）→ 两行原样保留。"""
        old = (_inst(count=6), _inst(count=1, quality="legendary"))
        out = _ctx_inventory_to_player({"potion": 7}, old, ITEMS)
        assert sorted((i.quality, int(i.count)) for i in out) == [
            ("legendary", 1), ("normal", 6)]

    def test_add_merges_into_normal_row(self):
        """净入包 +1 → 并入普通行（传说行不动）。"""
        old = (_inst(count=6), _inst(count=1, quality="legendary"))
        out = _ctx_inventory_to_player({"potion": 8}, old, ITEMS)
        by = {(i.quality, int(i.count)) for i in out}
        assert ("normal", 7) in by
        assert ("legendary", 1) in by

    def test_add_creates_normal_row_when_absent(self):
        """无普通行时净入包 → 新建普通行（不并入传说行）。"""
        old = (_inst(count=1, quality="legendary"),)
        out = _ctx_inventory_to_player({"potion": 2}, old, ITEMS)
        by = {(i.quality, int(i.count)) for i in out}
        assert ("legendary", 1) in by
        assert ("normal", 1) in by

    def test_deduct_skips_bound_first(self):
        """扣减：非绑定行先扣（绑定行最后动）。"""
        old = (_inst(count=1, bound=True), _inst(count=2, quality="fine"))
        out = _ctx_inventory_to_player({"potion": 2}, old, ITEMS)
        by = {(i.quality, int(i.count), bool(i.bound)) for i in out}
        assert ("normal", 1, True) in by
        assert ("fine", 1, False) in by

    def test_deduct_lowest_quality_first(self):
        """扣减：低品质优先（普通 → 精良 → 史诗 → 传说）。"""
        old = (_inst(count=2, quality="fine"), _inst(count=1, quality="legendary"))
        out = _ctx_inventory_to_player({"potion": 2}, old, ITEMS)
        by = {(i.quality, int(i.count)) for i in out}
        assert ("fine", 1) in by
        assert ("legendary", 1) in by

    def test_remove_all_when_zero(self):
        """ctx n=0 → 该 id 全部行移除（P0 修复：0 值 = 已清空，清行）。"""
        old = (_inst(count=2), _inst(count=1, quality="legendary"))
        out = _ctx_inventory_to_player({"potion": 0}, old, ITEMS)
        assert out == ()

    def test_hooks_deduct_all_clears_rows(self):
        """扣光（hooks 扣至 0，不 pop 键）→ merge 清除该 id 全部行（相邻缺陷修复）。"""
        from qbot_rpg.assembly.context import _inventory_hooks

        old = (_inst(count=2), _inst(count=1, quality="legendary"))
        ctx = {"inventory": {"potion": 3}, "items": ITEMS}
        hooks = _inventory_hooks(ctx)
        assert hooks["remove_item"]("potion", 3) is True
        assert ctx["inventory"] == {"potion": 0}        # 置 0 保留键（不再 pop）
        out = _ctx_inventory_to_player(ctx["inventory"], old, ctx["items"])
        assert out == ()                                 # 行清除、无残留

    def test_unmentioned_id_rows_kept(self):
        """防御语义：ctx 未涉及的 id（非全量映射场景）→ 旧行原样保留。"""
        old = (_inst(count=2), _inst(item_id="herb", name="草药", count=3))
        out = _ctx_inventory_to_player({"potion": 2}, old, ITEMS)
        assert {(i.item_id, int(i.count)) for i in out} == {
            ("potion", 2), ("herb", 3)}

    def test_single_row_behavior_unchanged(self):
        """单品质行：行为与旧实现一致（数量更新、行保留）。"""
        old = (_inst(count=3),)
        out = _ctx_inventory_to_player({"potion": 2}, old, ITEMS)
        assert len(out) == 1
        assert int(out[0].count) == 2

    def test_new_item_default_fields(self):
        """旧包无该 id → 按注册表构造默认行（工程补白 5）。"""
        out = _ctx_inventory_to_player({"potion": 3}, (), ITEMS)
        assert len(out) == 1
        i = out[0]
        assert i.item_id == "potion" and i.name == "药剂"
        assert int(i.count) == 3 and i.quality == "normal"


class TestPlayerAfterBuyPreservesQuality:
    """购买路径（shop_tx._player_after_buy）同享修复（同函数消费点）。"""

    def test_buy_no_change_keeps_rows(self):
        p = Player(qid="u1", name="测试者",
                   inventory=(_inst(count=6), _inst(count=1, quality="legendary")))
        ctx = {"currencies": dict(p.currencies), "inventory": {"potion": 7},
               "personal_buys": {}}
        p2 = _player_after_buy(p, ctx, ITEMS)
        by = {(i.quality, int(i.count)) for i in p2.inventory}
        assert ("legendary", 1) in by
        assert ("normal", 6) in by

    def test_buy_increment_into_normal(self):
        p = Player(qid="u1", name="测试者",
                   inventory=(_inst(count=6), _inst(count=1, quality="legendary")))
        ctx = {"currencies": dict(p.currencies), "inventory": {"potion": 8},
               "personal_buys": {}}
        p2 = _player_after_buy(p, ctx, ITEMS)
        by = {(i.quality, int(i.count)) for i in p2.inventory}
        assert ("legendary", 1) in by
        assert ("normal", 7) in by
