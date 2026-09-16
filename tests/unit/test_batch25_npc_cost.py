"""批25 · H2：NPC 功能收费多通道（`interactions[].cost` 扩展：金币 / 钻石 / 物品）。

依据 CakeGame `Ext_NPC_Info与Function.md:93`（`consume_gold / consume_diamond /
consume_goods`「选用该功能需支付的代价」）。设计口径（本批拍板，写进报告）：
  · **沿用既有 `cost` 对象扩展子键**（不新开平行字段）：`coins` 保留；任意 int > 0 的
    货币键（`gem`/`diamond` 及 settings.currencies[].id 任意已配置币）走 `ctx["currencies"]`；
    `items:[{item/id,count}]` 走物品出入库 hook（缺 hook 回退 `inventory` count-map）；
  · **原子性**：`_check_cost` 先全量校验（货币余额 + 物品持有），不足 → 人话拒绝且**不扣任何一项**；
    通过后 `_apply_cost` 一次扣除（物品删除异常回滚）。
  · 既有 `cost:{coins:N}` 行为逐字段不变（回归断言）。

覆盖：元数据登记 + 编辑器可见 / 校验 / 三通道各扣对（数值级）/ 不足拒绝 + 原子性 / 回归。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.npc import dispatch_action
from qbot_rpg.web import api

ITEMS = {"药水": {"id": "药水", "name": "药水"}, "铁矿": {"id": "铁矿", "name": "铁矿"}}
SETTINGS = {"currencies": [{"id": "coins", "name": "金币"}, {"id": "gem", "name": "宝石"},
                           {"id": "diamond", "name": "钻石"}]}


def make_ctx(**over: Any) -> dict:
    inv: Dict[str, int] = {"药水": 3, "铁矿": 1}

    def count_item(iid: str) -> int:
        return inv.get(iid, 0)

    def remove_item(iid: str, n: int) -> bool:
        if inv.get(iid, 0) < n:
            return False
        inv[iid] = inv[iid] - n
        return True

    def add_item(iid: str, n: int, bound: bool = False) -> bool:
        inv[iid] = inv.get(iid, 0) + n
        return True

    ctx: Dict[str, Any] = {
        "settings": SETTINGS,
        "currencies": {"coins": 100, "gem": 10, "diamond": 7},
        "items": ITEMS,
        "inventory": inv,
        "count_item": count_item,
        "remove_item": remove_item,
        "add_item": add_item,
        "hp": 10, "max_hp": 100, "mp": 5, "max_mp": 50,
        "npc_delivered": {},
        "today": "2026-09-16",
    }
    ctx.update(over)
    return ctx


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_h2_metadata_registered() -> None:
    tbl = default_field_meta_table()
    cost = tbl.module("npc").fields["interactions"].element.children["cost"]
    assert cost.type == "obj"
    for k in ("coins", "gem", "diamond", "items"):
        assert k in cost.children, f"cost 缺 {k} 子键登记"
    assert cost.children["coins"].type == "int"
    assert cost.children["diamond"].label == "钻石"
    assert cost.children["items"].type == "list"
    assert cost.children["items"].element.children["count"].type == "int"


def test_h2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_h2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_h2", "version": "1", "schema_version": 1, "modules": ["npc"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "npc.json").write_text(json.dumps([{
        "id": "n1", "name": "甲",
        "interactions": [{"action": "teleport", "text": "传送", "map": "town",
                          "cost": {"coins": 10, "diamond": 2,
                                   "items": [{"item": "药水", "count": 1}]}}],
    }], ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_h2", "npc", "n1", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "interactions")
    cost = next(c for c in (f["element"]["children"] or []) if c["key"] == "cost")
    kids = {c["key"]: c for c in (cost.get("children") or [])}
    assert kids["diamond"]["present"] is True and kids["diamond"]["type"] == "int"
    assert kids["items"]["present"] is True


# ---------------------------------------------------------------------------
# 校验：货币/物品形态非法 → 红
# ---------------------------------------------------------------------------
def test_h2_validator_invalid_red() -> None:
    cases = [
        ({"action": "heal", "text": "t", "heal": {"hp": 1}, "cost": {"gem": -1}},
         "R-2", "gem"),
        ({"action": "heal", "text": "t", "heal": {"hp": 1}, "cost": {"diamond": "2"}},
         "R-2", "diamond"),
        ({"action": "heal", "text": "t", "heal": {"hp": 1}, "cost": {"items": {"item": "药水"}}},
         "R-1", "items"),
        ({"action": "heal", "text": "t", "heal": {"hp": 1},
          "cost": {"items": [{"item": "药水", "count": 0}]}}, "R-2", "count"),
        ({"action": "heal", "text": "t", "heal": {"hp": 1},
          "cost": {"items": [{"count": 1}]}}, "R-5", "item"),
    ]
    for action_entry, kind, frag in cases:
        report = check_pack({"npc": [{"id": "n1", "name": "甲",
                                      "interactions": [action_entry]}]})
        assert [e for e in report.errors
                if e.kind == kind and frag in e.field], (frag, report.errors)


def test_h2_validator_valid_and_legacy_coins_ok() -> None:
    report = check_pack({"npc": [{
        "id": "n1", "name": "甲",
        "interactions": [
            {"action": "heal", "text": "t", "heal": {"hp": 1},
             "cost": {"coins": 50, "gem": 2, "diamond": 1,
                      "items": [{"item": "药水", "count": 2}]}},
            {"action": "teleport", "text": "传送", "map": "m1", "cost": {"coins": 1.5}},
        ]}]})
    assert not [e for e in report.errors if "cost" in e.field], report.errors


# ---------------------------------------------------------------------------
# 引擎消费：三种通道各扣对（数值级）
# ---------------------------------------------------------------------------
def test_h2_coins_channel() -> None:
    ctx = make_ctx()
    r = dispatch_action({"action": "teleport", "text": "传送", "map": "主城",
                         "cost": {"coins": 30}}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["currencies"]["coins"] == 70
    assert r["data"]["cost"] == 30


def test_h2_diamond_channel() -> None:
    ctx = make_ctx()
    r = dispatch_action({"action": "heal", "text": "钻石治疗", "heal": {"hp": 10},
                         "cost": {"diamond": 2}}, ctx, npc_id="npc1")
    assert r["ok"], r
    assert ctx["currencies"]["diamond"] == 5, ctx["currencies"]
    assert ctx["currencies"]["coins"] == 100  # 其它通道不受影响


def test_h2_item_channel() -> None:
    ctx = make_ctx()
    r = dispatch_action({"action": "teleport", "text": "信物传送", "map": "主城",
                         "cost": {"items": [{"item": "药水", "count": 2}]}}, ctx, npc_id="npc1")
    assert r["ok"], r
    assert ctx["inventory"]["药水"] == 1, ctx["inventory"]


def test_h2_all_three_channels_atomically() -> None:
    ctx = make_ctx()
    r = dispatch_action({"action": "heal", "text": "全套", "heal": {"hp": 5},
                         "cost": {"coins": 10, "diamond": 2,
                                  "items": [{"item": "铁矿", "count": 1}]}}, ctx, npc_id="npc1")
    assert r["ok"], r
    assert ctx["currencies"]["coins"] == 90
    assert ctx["currencies"]["diamond"] == 5
    assert ctx["inventory"]["铁矿"] == 0


def test_h2_disabled_channel_zero_is_free() -> None:
    """0/缺省通道不扣（与既有 cost 省略一致）。"""
    ctx = make_ctx()
    r = dispatch_action({"action": "heal", "text": "免费", "heal": {"hp": 5},
                         "cost": {"diamond": 0, "items": []}}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["currencies"]["diamond"] == 7 and ctx["inventory"]["药水"] == 3


# ---------------------------------------------------------------------------
# 不足 → 人话拒绝 + 原子性（不扣任何一项）
# ---------------------------------------------------------------------------
def test_h2_insufficient_currency_rejected_message() -> None:
    ctx = make_ctx(currencies={"coins": 100, "gem": 1, "diamond": 0})
    r = dispatch_action({"action": "heal", "text": "昂贵治疗", "heal": {"hp": 10},
                         "cost": {"coins": 10, "diamond": 2}}, ctx, npc_id="npc1")
    assert r["ok"] is False and r["reason"] == "insufficient_funds"
    assert r["message"] == "钻石不足，无法治疗", r["message"]
    assert ctx["currencies"]["coins"] == 100, "校验失败不得扣其它通道"
    assert ctx["hp"] == 10, "校验失败不得治疗"


def test_h2_insufficient_item_rejected_message_and_atomic() -> None:
    ctx = make_ctx()
    r = dispatch_action({"action": "heal", "text": "物品治疗", "heal": {"hp": 10},
                         "cost": {"coins": 10, "items": [{"item": "药水", "count": 9}]}},
                        ctx, npc_id="npc1")
    assert r["ok"] is False and r["reason"] == "insufficient_items"
    assert r["message"] == "物品不足，无法治疗（需要 药水×9，当前 3）", r["message"]
    assert ctx["currencies"]["coins"] == 100, "物品不足不得扣货币（原子性）"
    assert ctx["inventory"]["药水"] == 3


# ---------------------------------------------------------------------------
# 回归：既有 cost:{coins:N} 行为逐字段不变
# ---------------------------------------------------------------------------
def test_h2_regression_legacy_coins_identical() -> None:
    ctx = make_ctx(currencies={"coins": 10, "gem": 10, "diamond": 10})
    r = dispatch_action({"action": "heal", "text": "旧费", "heal": {"hp": 10},
                         "cost": {"coins": 50}}, ctx, npc_id="npc1")
    assert r["ok"] is False and r["reason"] == "insufficient_funds"
    assert ctx["currencies"]["coins"] == 10 and ctx["hp"] == 10
    ctx2 = make_ctx()
    r2 = dispatch_action({"action": "heal", "text": "旧费", "cost": {"coins": 50},
                          "heal": {"hp": 10}}, ctx2, npc_id="npc1")
    assert r2["ok"] and ctx2["currencies"]["coins"] == 50
    assert r2["data"]["cost"] == 50
