"""批24 · E3：进图消耗 / 门票信物 `entry_cost`（CakeGame `Config_Map.Consume`；§三 E3）。

设计口径（本批拍板，写进报告）：
  · 挂 **maps 节点**（`maps[].entry_cost`），补既有 `dungeon.entry_item` 只有副本粒度、
    单件且恒扣的缺口；
  · 形态 `{items: [{item, count}], consume: bool}`——items 支持多件；`consume` 缺省 true；
    （旧 `entry_item` 无法表达「只出示不交付」二态）；
  · 引擎落点 = `core.dungeon.DungeonStateMachine.enter`（进图入口，探索版/BOSS 版共用）：
    进图前校验**当前所在地图**的 entry_cost；`consume=true` 扣除、`false` 仅校验持有；
  · **复用既有物品出入库链路**（`count_item`/`remove_item`/`add_item` hook + count-map
    回退，与 core/quest.py 同口径），校验先于消耗、多项 all-or-nothing、后续校验失败回滚。

覆盖：
  - 元数据登记（maps `entry_cost` obj）+ 编辑器接口可见（items/consume 子字段）；
  - 校验：consume 非 bool / items 非数组 / count 非整数 → R-1 红；count 负数 → R-2 红；
  - 引擎消费（数值级）：consume=true 真扣；consume=false 只校验不扣；不足被人话拒绝；
  - 原子性：副本入场校验失败 → 地图门票回滚（背包复原、次数不增）；
  - 回归：不带 entry_cost → 进图结果与既有逐字段一致。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.dungeon import DungeonStateMachine
from qbot_rpg.web import api

_DUNGEON: Dict[str, Any] = {
    "id": "trial_cave", "name": "试炼洞窟", "type": "explore",
    "maps": ["trial_1", "trial_2"], "safe_zone": "trial_1",
}


def _ctx(entry_cost: Any = None, inv: Any = None, **over: Any) -> dict:
    gate: Dict[str, Any] = {"id": "gate", "name": "门口", "monsters": [], "exits": {}}
    if entry_cost is not None:
        gate["entry_cost"] = entry_cost
    ctx: Dict[str, Any] = {
        "map_id": "gate",
        "maps": [gate],
        "inventory": dict(inv or {}),
    }
    ctx.update(over)
    return ctx


# ---------------------------------------------------------------------------
# E3 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_e3_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("maps").fields.get("entry_cost")
    assert fm is not None, "maps 缺 entry_cost 登记"
    assert fm.type == "obj"
    assert fm.label == "进图消耗/门票"
    assert set(fm.children) >= {"items", "consume"}
    assert fm.children["consume"].type == "bool"
    assert tbl.module("maps").field_groups.get("entry_cost") == "refs"


def test_e3_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_e3"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e3", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(
        [{"id": "gate", "name": "门口", "monsters": [], "exits": {},
          "entry_cost": {"items": [{"item": "ticket", "count": 2}], "consume": False}}],
        ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_e3", "maps", "gate", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "entry_cost")
    assert f["present"] is True and f["type"] == "obj"
    kids = {c["key"]: c for c in f["children"]}
    assert {"items", "consume"} <= set(kids)
    assert kids["consume"]["type"] == "bool"


# ---------------------------------------------------------------------------
# E3 校验
# ---------------------------------------------------------------------------
def test_e3_validator_types_red() -> None:
    report = check_pack({"maps": [
        {"id": "m1", "name": "图一", "entry_cost": {"items": "ticket", "consume": True}},
        {"id": "m2", "name": "图二", "entry_cost": {"items": [], "consume": "yes"}},
        {"id": "m3", "name": "图三",
         "entry_cost": {"items": [{"item": "x", "count": "2"}], "consume": True}},
    ]})
    fields = [e.field for e in report.errors if e.kind == "R-1"]
    assert "maps.0.entry_cost.items" in fields
    assert "maps.1.entry_cost.consume" in fields
    assert "maps.2.entry_cost.items.0.count" in fields


def test_e3_validator_negative_count_red() -> None:
    report = check_pack({"maps": [
        {"id": "m1", "name": "图一",
         "entry_cost": {"items": [{"item": "x", "count": -1}], "consume": True}}]})
    assert [e for e in report.errors if e.kind == "R-2" and "count" in e.field]


def test_e3_validator_missing_ok() -> None:
    report = check_pack({"maps": [
        {"id": "m1", "name": "图一"},
        {"id": "m2", "name": "图二", "entry_cost": {"items": [{"item": "x", "count": 1}]}}]})
    assert not [e for e in report.errors if "entry_cost" in e.field]


# ---------------------------------------------------------------------------
# E3 引擎消费：真扣 / 只校验 / 不足拒绝
# ---------------------------------------------------------------------------
def test_e3_consume_true_deducts_exact() -> None:
    ctx = _ctx({"items": [{"item": "ticket", "count": 2}, {"item": "seal", "count": 1}],
                "consume": True}, inv={"ticket": 5, "seal": 3})
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is True, res
    assert res["entry_cost_consumed"] is True
    assert res["entry_cost_items"] == [["ticket", 2], ["seal", 1]]
    assert ctx["inventory"] == {"ticket": 3, "seal": 2}, ctx["inventory"]


def test_e3_consume_false_checks_only() -> None:
    ctx = _ctx({"items": [{"item": "pass", "count": 1}], "consume": False},
               inv={"pass": 1})
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is True, res
    assert res["entry_cost_consumed"] is False
    assert ctx["inventory"] == {"pass": 1}, "仅校验持有，不得扣除"


def test_e3_default_consume_is_true() -> None:
    """consume 缺省 = true（扣除，对齐旧 entry_item 语义）。"""
    ctx = _ctx({"items": [{"item": "ticket", "count": 1}]}, inv={"ticket": 2})
    DungeonStateMachine().enter(ctx, _DUNGEON)
    assert ctx["inventory"]["ticket"] == 1


def test_e3_insufficient_rejected_with_human_message() -> None:
    ctx = _ctx({"items": [{"item": "ticket", "count": 3}], "consume": True},
               inv={"ticket": 1})
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is False and res["session"] is None
    assert res["reason"] == "进入「gate」需要 ticket×3，当前只有 1 个"
    assert ctx["inventory"] == {"ticket": 1}, "被拒不得扣物"
    assert ctx["map_id"] == "gate", "被拒不得改位置"


def test_e3_insufficient_checkonly_message_mentions_no_deduct() -> None:
    ctx = _ctx({"items": [{"item": "pass", "count": 1}], "consume": False}, inv={})
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is False
    assert "仅校验持有，不扣除" in res["reason"]


# ---------------------------------------------------------------------------
# E3 原子性：副本入场校验失败 → 地图门票回滚
# ---------------------------------------------------------------------------
def test_e3_rollback_when_dungeon_entry_limit_exceeded() -> None:
    """entry_cost 已扣，但副本 entry_limit 超限 → 门票回滚、次数不增。"""
    ctx = _ctx({"items": [{"item": "ticket", "count": 2}], "consume": True},
               inv={"ticket": 5}, dungeon_entries={"trial_cave": 9})
    ddef = dict(_DUNGEON, entry_limit=1)
    res = DungeonStateMachine().enter(ctx, ddef)
    assert res["ok"] is False
    assert "上限" in res["reason"]
    assert ctx["inventory"] == {"ticket": 5}, "副本校验失败 → 地图门票必须回滚"
    assert ctx["dungeon_entries"]["trial_cave"] == 9, "不得消耗次数"


def test_e3_map_cost_insufficient_before_dungeon_item_untouched() -> None:
    """地图门票不足 → 直接拦截，副本 entry_item 不得被扣。"""
    ctx = _ctx({"items": [{"item": "ticket", "count": 1}], "consume": True},
               inv={"ticket": 0, "key": 2})
    ddef = dict(_DUNGEON, entry_item="key")
    res = DungeonStateMachine().enter(ctx, ddef)
    assert res["ok"] is False
    assert ctx["inventory"] == {"ticket": 0, "key": 2}, "副本入场道具不得被扣"


# ---------------------------------------------------------------------------
# E3 复用 hook 链路
# ---------------------------------------------------------------------------
def test_e3_uses_injected_item_hooks() -> None:
    """ctx 提供 count_item/remove_item hook → 走 hook 而非 count-map（入账口径统一）。"""
    calls: List[Any] = []
    stock = {"ticket": 4}

    def count_item(item_id: str) -> int:
        calls.append(("count", item_id))
        return stock.get(item_id, 0)

    def remove_item(item_id: str, n: int) -> bool:
        calls.append(("remove", item_id, n))
        if stock.get(item_id, 0) < n:
            return False
        stock[item_id] -= n
        return True

    ctx = _ctx({"items": [{"item": "ticket", "count": 2}], "consume": True},
               inv={"ticket": 99}, count_item=count_item, remove_item=remove_item)
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is True
    assert ("count", "ticket") in calls and ("remove", "ticket", 2) in calls
    assert stock["ticket"] == 2
    assert ctx["inventory"] == {"ticket": 99}, "hook 存在时不走 count-map"


# ---------------------------------------------------------------------------
# E3 回归：不带 entry_cost → 逐字段一致
# ---------------------------------------------------------------------------
def test_e3_regression_without_field_identical() -> None:
    a = _ctx(None, inv={})
    b = _ctx(None, inv={})
    ra = DungeonStateMachine().enter(a, _DUNGEON)
    rb = DungeonStateMachine().enter(b, _DUNGEON)
    assert ra == rb
    assert ra["entry_cost_consumed"] is False and ra["entry_cost_items"] == []
    assert a["map_id"] == b["map_id"] == "trial_1"


# ---------------------------------------------------------------------------
# E3 端到端：临时内容根建包 → 加载 → 进图真扣
# ---------------------------------------------------------------------------
def test_e3_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_e3"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_e3", "version": "1", "schema_version": 1, "modules": ["maps"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "maps.json").write_text(json.dumps(
        [{"id": "gate", "name": "门口", "monsters": [], "exits": {},
          "entry_cost": {"items": [{"item": "ticket", "count": 2}], "consume": True}}],
        ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    maps = pack.modules["maps"]
    ctx = {"map_id": "gate", "maps": maps, "inventory": {"ticket": 5}}
    res = DungeonStateMachine().enter(ctx, _DUNGEON)
    assert res["ok"] is True and res["entry_cost_consumed"] is True
    assert ctx["inventory"]["ticket"] == 3
