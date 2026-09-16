"""批26 · α2：物品最大获取数量 `max_hold`（CakeGame 装备附加Re《品质部位筛选》:54-57）。

设计口径（本批拍板，写进报告）：
  · 形态 = items/equipment 条目上的整数 `max_hold`：0=不限 / 1=唯一 / -1=禁止获取；
  · 引擎消费 = **统一获取入口拦一次**。我们唯一的入包链路是装配层
    `ctx["add_item"]` hook（掉落奖励 reward / 商店 shop / 合成 synthesis / 任务签到
    / NPC give_item 全部经此）——门禁唯一实现在 `core.inventory.max_hold_rejection`，
    hook 调用一次；不散落多处；
  · `-1`：我们**无既有「自动丢弃」语义**（全仓无 auto-discard 分支），故取
    「拒绝获取」并如实登记；
  · 拒绝人话落 `ctx["add_item_denied"]`；商店等直接交互入口透传（core/shop 已接）。

覆盖：
  - 元数据登记（items + equipment，int，中文 help）+ 编辑器可见；
  - 校验：取值非 0/1/-1（如 2/3/-2）→ IV-3 红；非整数 → 泛型 R-1；三档合法不红；
  - 引擎消费（数值/状态级）：1 且已持有 → 再获取被拒（贴提示）；-1 → 恒拒；
    0 → 不限（多次累加贴数值）；穿戴中持有同样计入「已持有」；商店购买贴人话；
  - 回归：不带 max_hold → 多次获取全部成功、计数逐字段一致。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.assembly.context import _inventory_hooks
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.inventory import max_hold_rejection
from qbot_rpg.core.shop import shop_buy
from qbot_rpg.web import api

MSG_UNIQUE = "❌ 该物品最多持有 1 个（已持有，无法再获取）"
MSG_FORBIDDEN = "❌ 该物品禁止获取"


def _ctx(items, *, inventory=None, player=None):
    ctx = {"items": dict(items), "inventory": dict(inventory or {})}
    if player is not None:
        ctx["player"] = player
    ctx.update(_inventory_hooks(ctx))
    return ctx


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a2_metadata_registered() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("max_hold")
        assert fm is not None, f"{mod} 缺 max_hold 登记"
        assert fm.type == "int"
        assert fm.range_min == -1 and fm.range_max == 1
        assert fm.label == "最大获取数量" and fm.help
    assert tbl.module("items").field_groups.get("max_hold") == "base"


def test_a2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a2", "version": "1", "schema_version": 1, "modules": ["items"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "items.json").write_text(json.dumps([
        {"id": "relic", "name": "遗物", "max_hold": 1}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_a2", "items", "relic", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "max_hold")
    assert f["present"] is True and f["type"] == "int"
    assert f["label"] == "最大获取数量"


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def test_a2_validator_enum_red() -> None:
    for bad in (2, 3, -2, 100):
        report = check_pack({"items": [{"id": "relic", "name": "遗物", "max_hold": bad}]})
        assert [e for e in report.errors
                if e.kind == "IV-3" and "max_hold" in e.field], (bad, report.errors)


def test_a2_validator_valid_values_ok() -> None:
    for ok in (0, 1, -1):
        report = check_pack({"items": [{"id": "relic", "name": "遗物", "max_hold": ok}]})
        assert not [e for e in report.errors if "max_hold" in e.field], (ok, report.errors)


def test_a2_validator_non_int_red() -> None:
    report = check_pack({"items": [{"id": "relic", "name": "遗物", "max_hold": "1"}]})
    assert [e for e in report.errors if e.kind == "R-1" and "max_hold" in e.field]


def test_a2_pure_decision_function() -> None:
    assert max_hold_rejection({}, 5) is None
    assert max_hold_rejection({"max_hold": 0}, 999) is None
    assert max_hold_rejection({"max_hold": 1}, 0) is None
    assert max_hold_rejection({"max_hold": 1}, 1) == MSG_UNIQUE
    assert max_hold_rejection({"max_hold": -1}, 0) == MSG_FORBIDDEN
    # 唯一物品批量获取（held=0 + count>1）同样拦（硬上限）
    assert max_hold_rejection({"max_hold": 1}, 0, 3) == \
        "❌ 该物品最多持有 1 个（单次获取数量超限）"
    # 非法档位（校验器已红拦）→ 引擎防御性放行
    assert max_hold_rejection({"max_hold": 7}, 3) is None


# ---------------------------------------------------------------------------
# 引擎消费：统一入包 hook
# ---------------------------------------------------------------------------
def test_a2_unique_rejected_when_held() -> None:
    ctx = _ctx({"relic": {"id": "relic", "name": "遗物", "max_hold": 1}})
    add = ctx["add_item"]
    assert add("relic", 1) is True
    assert add("relic", 1) is False
    assert ctx["inventory"]["relic"] == 1, "被拒后计数不得变化"
    assert ctx["add_item_denied"]["reason"] == "max_hold"
    assert ctx["add_item_denied"]["message"] == MSG_UNIQUE


def test_a2_forbidden_always_rejected() -> None:
    ctx = _ctx({"cursed": {"id": "cursed", "name": "禁物", "max_hold": -1}})
    add = ctx["add_item"]
    assert add("cursed", 1) is False
    assert add("cursed", 5) is False
    assert ctx["inventory"].get("cursed", 0) == 0
    assert ctx["add_item_denied"]["message"] == MSG_FORBIDDEN


def test_a2_unlimited_accumulates() -> None:
    ctx = _ctx({"stone": {"id": "stone", "name": "碎石", "max_hold": 0}})
    add = ctx["add_item"]
    for _ in range(3):
        assert add("stone", 2) is True
    assert ctx["inventory"]["stone"] == 6
    assert "add_item_denied" not in ctx


def test_a2_worn_counts_as_held() -> None:
    """穿戴中的唯一物品也算「已持有」（只数背包会漏判）。"""
    player = {"equipment": {"weapon": {"item_id": "relic", "name": "遗物"}}}
    ctx = _ctx({"relic": {"id": "relic", "name": "遗物", "max_hold": 1}},
               player=player)
    assert ctx["add_item"]("relic", 1) is False
    assert ctx["add_item_denied"]["message"] == MSG_UNIQUE


def test_a2_shop_purchase_message() -> None:
    """商店购买（直接交互入口）透传门禁人话。"""
    items = {"relic": {"id": "relic", "name": "遗物", "price": 100, "max_hold": 1}}
    shops = {"s": {"id": "s", "name": "小店", "currency": "coins",
                   "items": [{"item": "relic", "price": 100}]}}
    ctx = _ctx(items)
    ctx.update({"shops": shops, "currencies": {"coins": 1000},
                "settings": {"currencies": [{"id": "coins", "name": "金币"}]},
                "world_stock": {}, "world_sold_out": {}, "last_refresh": {},
                "personal_buys": {}, "level": 1, "name": "甲", "reputation": 1,
                "reputation_state": {"global": 0}})
    first = shop_buy("s", "relic", 1, ctx)
    assert first["ok"] is True, first
    second = shop_buy("s", "relic", 1, ctx)
    assert second["ok"] is False
    assert second["message"] == MSG_UNIQUE, second


def test_a2_regression_without_field() -> None:
    ctx = _ctx({"plain": {"id": "plain", "name": "普物"}})
    add = ctx["add_item"]
    for _ in range(4):
        assert add("plain", 1) is True
    assert ctx["inventory"]["plain"] == 4
    assert "add_item_denied" not in ctx
