"""批25 · H1：NPC 功能次数上限 `daily_limit` / `total_limit`。

依据 CakeGame `Ext_NPC_Info与Function.md:150-151`（`Day_number`/`User_number`）。

设计口径（本批拍板，写进报告）：
  · 形态 = `npc.interactions[]` 条目上的两个可选整数（int ≥1；缺省 = 不限）；
  · **进度存哪**：复用既有玩家态口径 `ctx["npc_delivered"]`（NPC 一次一物存档域，
    装配层挂回 `player.persistent_state` 并随事务落档）——键 `limit_day:<功能名>` /
    `limit_day_n:<功能名>` / `limit_total:<功能名>`。**不用** 批 D 的 `player_pack_state`
    （独立异步 DB 表，而 `dispatch_action` 是纯函数，不能引入 IO）；
  · **每日重置**：日期键取 dayroll 日界（settings.refresh_time 缺省 05:00，与
    give_item daily / quest / 签到同刻）——存档 `limit_day` ≠ 当前日期键即视为新一天从 0 起；
  · 与既有 `repeat`（give_item 行为级 once/daily）分工：repeat 管行为、本组管**额度**。

覆盖：
  - 元数据登记（interactions 元素子键）+ 编辑器接口可见；
  - 校验：非整数/<1 的额度 → R-2 红；合法/缺省不红；
  - 引擎消费（数值/状态级）：调用 N 次后被拒（贴提示原文）+ 跨日重置（时间注入）；
  - 累计上限独立于每日上限；
  - 回归：不带额度字段 → 行为与既有逐字段一致（无额度键写入、调用不被拒）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.npc import dispatch_action
from qbot_rpg.web import api

ITEMS = {"药水": {"id": "药水", "name": "药水"}}
SETTINGS = {"currencies": [{"id": "coins"}, {"id": "gem"}]}


def make_ctx(**over: Any) -> dict:
    ctx: Dict[str, Any] = {
        "settings": SETTINGS,
        "currencies": {"coins": 100, "gem": 5},
        "items": ITEMS,
        "hp": 10, "max_hp": 100, "mp": 5, "max_mp": 50,
        "npc_delivered": {},
        "today": "2026-09-16",
    }
    ctx.update(over)
    return ctx


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_h1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    kids = tbl.module("npc").fields["interactions"].element.children
    for k in ("daily_limit", "total_limit", "key"):
        assert k in kids, f"npc.interactions 缺 {k} 登记"
    assert kids["daily_limit"].type == "int"
    assert kids["daily_limit"].label == "每日次数上限"
    assert kids["daily_limit"].help, "daily_limit 缺中文说明"
    assert kids["total_limit"].type == "int" and kids["total_limit"].label == "累计次数上限"
    # 与既有 repeat（give_item 行为级）不是同一键，互不覆盖
    assert "repeat" in kids


def test_h1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_h1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_h1", "version": "1", "schema_version": 1, "modules": ["npc"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "npc.json").write_text(json.dumps([{
        "id": "n1", "name": "甲",
        "interactions": [{"action": "heal", "text": "治疗", "daily_limit": 2,
                          "total_limit": 5, "heal": {"hp": 1}}],
    }], ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_h1", "npc", "n1", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "interactions")
    kids = {c["key"]: c for c in (f["element"]["children"] or [])}
    assert kids["daily_limit"]["present"] is True
    assert kids["daily_limit"]["type"] == "int"
    assert kids["daily_limit"]["label"] == "每日次数上限"
    assert kids["total_limit"]["present"] is True


# ---------------------------------------------------------------------------
# 校验：额度非法 → R-2 红；合法/缺省不红
# ---------------------------------------------------------------------------
def test_h1_validator_invalid_red() -> None:
    for bad in (0, -1, "3", 2.5, True):
        report = check_pack({"npc": [{
            "id": "n1", "name": "甲",
            "interactions": [{"action": "heal", "text": "治疗", "daily_limit": bad,
                              "heal": {"hp": 1}}]}]})
        assert [e for e in report.errors
                if e.kind == "R-2" and "daily_limit" in e.field], (bad, report.errors)
    report = check_pack({"npc": [{
        "id": "n1", "name": "甲",
        "interactions": [{"action": "heal", "text": "治疗", "total_limit": 0,
                          "heal": {"hp": 1}}]}]})
    assert [e for e in report.errors if e.kind == "R-2" and "total_limit" in e.field]


def test_h1_validator_valid_and_missing_ok() -> None:
    report = check_pack({"npc": [{
        "id": "n1", "name": "甲",
        "interactions": [
            {"action": "heal", "text": "治疗", "daily_limit": 1, "total_limit": 3,
             "heal": {"hp": 1}},
            {"action": "reply", "text": "闲聊"},
        ]}]})
    assert not [e for e in report.errors if "limit" in e.field], report.errors


# ---------------------------------------------------------------------------
# 引擎消费：调用 N 次后被拒（贴提示原文）
# ---------------------------------------------------------------------------
def test_h1_daily_limit_rejected_after_n() -> None:
    ctx = make_ctx()
    entry = {"action": "reply", "text": "每日一问", "daily_limit": 2}
    r1 = dispatch_action(entry, ctx, npc_id="npc1")
    r2 = dispatch_action(entry, ctx, npc_id="npc1")
    r3 = dispatch_action(entry, ctx, npc_id="npc1")
    assert r1["ok"] and r2["ok"], (r1, r2)
    assert r3["ok"] is False and r3["reason"] == "daily_limit_reached"
    assert r3["message"] == "每日一问今日已达上限，明天再来", r3["message"]
    # 进度落既有 npc_delivered 域（数值级）
    sub = ctx["npc_delivered"]["npc1"]
    assert sub["limit_day:reply|每日一问|"] == "2026-09-16"
    assert sub["limit_day_n:reply|每日一问|"] == 2


def test_h1_daily_reset_next_day() -> None:
    """跨日重置（时间注入）：改 ctx["today"] → 计数从 0 起，额度恢复。"""
    ctx = make_ctx()
    entry = {"action": "reply", "text": "每日一问", "daily_limit": 1}
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is True
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is False
    ctx["today"] = "2026-09-17"
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert r["ok"] is True, r
    assert ctx["npc_delivered"]["npc1"]["limit_day:reply|每日一问|"] == "2026-09-17"
    assert ctx["npc_delivered"]["npc1"]["limit_day_n:reply|每日一问|"] == 1


def test_h1_total_limit_independent_of_daily() -> None:
    ctx = make_ctx()
    entry = {"action": "reply", "text": "限量兑换", "total_limit": 2}
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is True
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is True
    # 换新的一天也不恢复累计额度
    ctx["today"] = "2026-09-17"
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert r["ok"] is False and r["reason"] == "total_limit_reached"
    assert r["message"] == "限量兑换累计已达上限"


def test_h1_failed_call_does_not_consume_quota() -> None:
    """失败调用（如金币不足）不消耗额度——条件/资源不满足不算「调用成功」。"""
    ctx = make_ctx(currencies={"coins": 0, "gem": 0})
    entry = {"action": "heal", "text": "付费治疗", "heal": {"hp": 10},
             "cost": {"coins": 50}, "daily_limit": 1}
    bad = dispatch_action(entry, ctx, npc_id="npc1")
    assert bad["ok"] is False and bad["reason"] == "insufficient_funds"
    assert "limit_day_n:heal|付费治疗|" not in ctx["npc_delivered"].get("npc1", {})
    ctx["currencies"]["coins"] = 100
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is True


def test_h1_explicit_key_used_as_identity() -> None:
    ctx = make_ctx()
    entry = {"action": "reply", "text": "一问", "key": "daily_quiz", "daily_limit": 1}
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"] is True
    assert "limit_day:daily_quiz" in ctx["npc_delivered"]["npc1"]


# ---------------------------------------------------------------------------
# 回归：不带额度字段 → 行为与既有逐字段一致
# ---------------------------------------------------------------------------
def test_h1_regression_without_fields_identical() -> None:
    ctx = make_ctx()
    entry = {"action": "reply", "text": "闲聊"}
    out = [dispatch_action(entry, ctx, npc_id="npc1") for _ in range(5)]
    assert all(r["ok"] for r in out)
    # 不写任何额度键（npc_delivered 域不被额度逻辑触碰）
    assert ctx["npc_delivered"] == {}
