"""统一 reward 解析器单测（M4 批次0·路A1 · qbot_rpg/core/reward.py）。

依据：m4_shared_contract.md §1 A1（条目形态/内联糖/幂等/返回契约）+
细化_2b4_任务引擎契约.md §三（TC-13~TC-17 奖励统一条目）+ 任务系统设计定稿 L100-126 +
NPC系统设计定稿 L153（id ≡ item 键）+ M4 设计审查裁决 P1-2（逐条目失败黄字跳过不中断整批）。

覆盖：内联串等价（D-05/TC-02）· exp 直入（TC-13）· 货币入账（TC-14）· 物品入包（TC-15）·
rep 入 reputation_state 不入货币表（TC-16）· 组合数组按序（TC-17）· 逐条目失败跳过（P1-2）·
幂等（A1）· 默认绑定 · 货币键空间校验 · id 别名 · 批级失败兜底 · 无 add_item hook 时物品条目
skip(item_add_failed)（M4 实现审查批次1 P1-1）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.reward import (
    DEFAULT_CURRENCY_IDS,
    dispatch_reward,
    expand_inline_reward,
    normalize_reward,
)

# ---------------------------------------------------------------------------
# 基础夹具
# ---------------------------------------------------------------------------

ITEMS = {"铁矿": {"id": "铁矿", "name": "铁矿", "quality": "normal"},
         "药水": {"id": "药水", "name": "药水", "quality": "normal"}}

SETTINGS = {"currencies": [{"id": "coins"}, {"id": "gem"}]}


def make_ctx(**overrides) -> dict:
    """默认 ctx：货币表 + exp + reputation_state + settings(coins/gem) + 物品注册表 + 入包 hook。"""
    ctx = {
        "settings": SETTINGS,
        "currencies": {},
        "exp": 0,
        "reputation_state": {},
        "items": ITEMS,
        "add_item": None,
        **overrides,
    }
    return ctx


def record_adds(ctx) -> list:
    """注入入包 hook 并收集调用记录，返回 [(item_id, count, bound), ...]。"""
    calls = []
    ctx["add_item"] = lambda item_id, count, bound: (calls.append((item_id, count, bound)) or True)  # type: ignore[func-returns-value]
    return calls


# ---------------------------------------------------------------------------
# 内联串序列化糖等价（D-05 / TC-02）
# ---------------------------------------------------------------------------

def test_d05_inline_equivalent_to_structured():
    """TC-02：内联串与结构化条目数组入账结果完全一致（解析器等价展开）。"""
    ctx_a = make_ctx()
    ctx_b = make_ctx()
    inline = "exp=50,coins=80,item:铁矿*3"
    structured = [{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}]
    ra = dispatch_reward(inline, ctx_a)
    rb = dispatch_reward(structured, ctx_b)
    assert ra["ok"] and rb["ok"]
    assert ra["granted"] == rb["granted"]
    assert ctx_a["currencies"] == ctx_b["currencies"] == {"coins": 80}
    assert ctx_a["exp"] == ctx_b["exp"] == 50


def test_expand_inline_reward_shapes():
    """内联串展开为结构化条目数组（含 item 缺省数量 =1、非物品键 = 键值对）。"""
    assert expand_inline_reward("exp=50,coins=80,item:铁矿*3") == [
        {"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3},
    ]
    assert expand_inline_reward("item:铁矿") == [{"item": "铁矿", "count": 1}]
    assert expand_inline_reward("gem=3") == [{"gem": 3}]


def test_inline_unknown_key_raises_for_expander():
    """内联串未知键 → expand 抛 ValueError（加载期=内容错误）。"""
    with pytest.raises(ValueError):
        expand_inline_reward("exp=1,foo=2")


def test_inline_malformed_value_raises_for_expander():
    with pytest.raises(ValueError):
        expand_inline_reward("exp=abc")
    with pytest.raises(ValueError):
        expand_inline_reward("item:铁矿*abc")


def test_dispatch_invalid_inline_skips_entry():
    """运行时收到无法解析的内联串 → 内容级失败逐条 skip（P1-2），整批 ok=True 不中断。"""
    r = dispatch_reward("exp=50,foo=2", make_ctx())
    assert r["ok"] is True and r["granted"] == []
    assert len(r["skipped"]) == 1
    assert r["skipped"][0]["type"] == "invalid"
    assert r["skipped"][0]["reason"] == "invalid_entry"


# ---------------------------------------------------------------------------
# exp 数值直入（TC-13）
# ---------------------------------------------------------------------------

def test_tc13_exp_direct():
    ctx = make_ctx(exp=100)
    r = dispatch_reward([{"exp": 50}], ctx)
    assert r["ok"] and r["granted"] == [{"type": "exp", "amount": 50}]
    assert ctx["exp"] == 150


# ---------------------------------------------------------------------------
# 货币入账（TC-14 · 键空间 settings 货币键）
# ---------------------------------------------------------------------------

def test_tc14_currency_into_table():
    ctx = make_ctx()
    r = dispatch_reward([{"coins": 80}, {"gem": 3}], ctx)
    assert r["ok"]
    assert ctx["currencies"] == {"coins": 80, "gem": 3}
    assert r["granted"] == [
        {"type": "currency", "currency": "coins", "amount": 80},
        {"type": "currency", "currency": "gem", "amount": 3},
    ]


def test_currency_accumulates_existing_balance():
    ctx = make_ctx(currencies={"coins": 20})
    dispatch_reward([{"coins": 80}], ctx)
    assert ctx["currencies"] == {"coins": 100}


def test_currency_default_space_without_settings():
    """无 settings → 默认键空间 ("coins","diamond")；coins 入账，gem 被 skip（unknown_currency）。"""
    ctx = make_ctx()
    del ctx["settings"]
    r = dispatch_reward([{"coins": 80}, {"gem": 3}], ctx)
    assert ctx["currencies"] == {"coins": 80}
    assert [s["type"] for s in r["skipped"]] == ["gem"]
    assert r["skipped"][0]["reason"] == "unknown_currency"
    assert DEFAULT_CURRENCY_IDS == ("coins", "diamond")


# ---------------------------------------------------------------------------
# 物品入包（TC-15 · 默认绑定 · id 别名）
# ---------------------------------------------------------------------------

def test_tc15_item_into_inventory_default_bound():
    ctx = make_ctx()
    calls = record_adds(ctx)
    r = dispatch_reward([{"item": "铁矿", "count": 3}], ctx)
    assert r["ok"]
    assert calls == [("铁矿", 3, True)]
    assert r["granted"] == [{"type": "item", "item": "铁矿", "count": 3,
                             "bound": True, "applied": True}]


def test_item_default_count_and_explicit_bound_false():
    ctx = make_ctx()
    calls = record_adds(ctx)
    dispatch_reward([{"item": "药水"}, {"item": "铁矿", "count": 2, "bound": False}], ctx)
    assert calls == [("药水", 1, True), ("铁矿", 2, False)]


def test_item_id_alias_npc_give_item():
    """NPC give_item items[]{id,count} 的 id ≡ item 键（NPC 定稿 L153）。"""
    ctx = make_ctx()
    calls = record_adds(ctx)
    r = dispatch_reward([{"id": "药水", "count": 3}], ctx)
    assert r["ok"] and calls == [("药水", 3, True)]
    assert r["granted"][0]["item"] == "药水"


def test_item_no_add_hook_skips_p1_1():
    """M4 实现审查批次1 P1-1：无 add_item hook → 该条 skip(item_add_failed)（不伪装 granted）。

    旧行为把"未入包"记成 granted(applied=False)（静默丢奖根源）；现改为条目级 skip 携带 reason，
    由消费方（quest.py）对 item_add_failed 整单回滚 + 不封口幂等兜底。
    """
    ctx = make_ctx()
    r = dispatch_reward([{"item": "铁矿", "count": 3}], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert len(r["skipped"]) == 1
    s = r["skipped"][0]
    assert s["type"] == "item" and s["reason"] == "item_add_failed"
    assert s["item"] == "铁矿" and s["count"] == 3


# ---------------------------------------------------------------------------
# rep 入 reputation_state，不入货币表（TC-16 / L226）
# ---------------------------------------------------------------------------

def test_tc16_rep_into_reputation_state_not_currency():
    ctx = make_ctx(currencies={"coins": 5})
    r = dispatch_reward([{"rep": 20}], ctx)
    assert r["ok"]
    assert ctx["reputation_state"] == {"global": 20}
    assert ctx["currencies"] == {"coins": 5}  # 货币表原样（rep 不入货币表）
    assert r["granted"] == [{"type": "rep", "amount": 20, "board": "global"}]


def test_rep_board_resolution():
    """板 ID 优先级：entry.board > entry.param > ctx.rep_board > "global"。"""
    ctx = make_ctx(rep_board="commercial")
    dispatch_reward([{"rep": 5}], ctx)
    assert ctx["reputation_state"] == {"commercial": 5}

    ctx = make_ctx()
    dispatch_reward([{"rep": 5, "board": "daily"}], ctx)
    assert ctx["reputation_state"] == {"daily": 5}

    ctx = make_ctx()
    dispatch_reward([{"rep": 5, "param": "weekly"}], ctx)
    assert ctx["reputation_state"] == {"weekly": 5}


def test_rep_accumulates():
    ctx = make_ctx()
    dispatch_reward([{"rep": 20}, {"rep": 10}], ctx)
    assert ctx["reputation_state"] == {"global": 30}


# ---------------------------------------------------------------------------
# 组合数组按序入账（TC-17）
# ---------------------------------------------------------------------------

def test_tc17_combination_array_in_order():
    ctx = make_ctx()
    calls = record_adds(ctx)
    r = dispatch_reward([{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}], ctx)
    assert r["ok"]
    assert [g["type"] for g in r["granted"]] == ["exp", "currency", "item"]
    assert ctx["exp"] == 50 and ctx["currencies"] == {"coins": 80}
    assert calls == [("铁矿", 3, True)]


# ---------------------------------------------------------------------------
# 逐条目失败黄字跳过、不中断整批（P1-2 裁决）
# ---------------------------------------------------------------------------

def test_p12_bad_entry_skips_rest_grants():
    """物品不存在 + 好条目混排 → 好条目照常入账，坏条目 skip，整批 ok=True 不中断。"""
    ctx = make_ctx()
    calls = record_adds(ctx)
    r = dispatch_reward([
        {"exp": 50},
        {"item": "不存在之物", "count": 1},   # 物品不存在 → skip
        {"coins": 80},
        {"item": "铁矿", "count": 2},         # 物品存在 → 入包
    ], ctx)
    assert r["ok"] is True
    assert [g["type"] for g in r["granted"]] == ["exp", "currency", "item"]
    assert ctx["exp"] == 50 and ctx["currencies"] == {"coins": 80}
    assert calls == [("铁矿", 2, True)]
    assert len(r["skipped"]) == 1
    assert r["skipped"][0]["reason"] == "item_not_found"
    assert r["skipped"][0]["item"] == "不存在之物"


def test_invalid_value_skips_entry():
    """数值非法（负数 / 非 int）→ 逐条 skip，不抛异常。"""
    ctx = make_ctx()
    r = dispatch_reward([{"exp": -5}, {"coins": "abc"}, {"exp": 10}], ctx)
    assert r["ok"] is True
    assert ctx["exp"] == 10  # 只有合法的那条入账
    reasons = [s["reason"] for s in r["skipped"]]
    assert reasons == ["invalid_value", "invalid_value"]


def test_item_invalid_count_skips():
    ctx = make_ctx()
    r = dispatch_reward([{"item": "铁矿", "count": 0}, {"item": "铁矿", "count": -2},
                         {"item": "铁矿", "count": 1.5}], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert all(s["reason"] == "invalid_value" for s in r["skipped"])


def test_item_not_found_and_registry_missing():
    """注册表缺失 → skip item_registry_missing（fail-safe，工程补白）。"""
    ctx = make_ctx()
    del ctx["items"]
    r = dispatch_reward([{"item": "铁矿", "count": 1}], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert r["skipped"][0]["reason"] == "item_registry_missing"


def test_missing_bucket_skips_entry():
    """ctx 缺入账桶（currencies/exp/reputation_state）→ 该条 skip missing_bucket。"""
    ctx = make_ctx()
    del ctx["currencies"]
    del ctx["exp"]
    del ctx["reputation_state"]
    r = dispatch_reward([{"coins": 80}, {"exp": 50}, {"rep": 20}], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert all(s["reason"] == "missing_bucket" for s in r["skipped"])


def test_add_item_hook_failure_skips():
    """入包 hook 抛异常/返回 False → 该条 skip item_add_failed。"""
    ctx = make_ctx()
    ctx["add_item"] = lambda item_id, count, bound: (_ for _ in ()).throw(RuntimeError("背包满"))
    r = dispatch_reward([{"item": "铁矿", "count": 1}], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert r["skipped"][0]["reason"] == "item_add_failed"


def test_malformed_entry_skips():
    """非法条目形态（空 dict / 多键未知 / 非映射）→ skip invalid_entry，不崩。"""
    ctx = make_ctx()
    r = dispatch_reward([{}, {"coins": 1, "gem": 2}, {"foo": 1}, 42], ctx)
    assert r["ok"] is True and r["granted"] == []
    assert all(s["reason"] == "invalid_entry" for s in r["skipped"])
    assert len(r["skipped"]) == 4


# ---------------------------------------------------------------------------
# 幂等（A1 · version/tx id 重复调用不重复入账）
# ---------------------------------------------------------------------------

def test_idempotent_same_tx_id_does_not_double_book():
    ctx = make_ctx()
    calls = record_adds(ctx)
    ctx["tx_id"] = "tx-001"
    ctx["ledger"] = set()
    r1 = dispatch_reward([{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}], ctx)
    assert r1["ok"] and len(r1["granted"]) == 3
    before = (ctx["exp"], dict(ctx["currencies"]), len(calls), ctx["reputation_state"].copy())

    r2 = dispatch_reward([{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}], ctx)
    assert r2["ok"] and r2["granted"] == [] and r2["skipped"] == []
    assert r2["idempotent"] is True
    # 不重复入账
    assert ctx["exp"] == before[0]
    assert ctx["currencies"] == before[1]
    assert len(calls) == before[2]
    assert "tx-001" in ctx["ledger"]


def test_idempotent_different_tx_id_books_twice():
    """不同 tx_id → 各自入账（互不幂等）。"""
    ctx = make_ctx()
    ctx["tx_id"] = "tx-001"
    ctx["ledger"] = set()
    dispatch_reward([{"exp": 50}], ctx)
    ctx["tx_id"] = "tx-002"
    dispatch_reward([{"exp": 50}], ctx)
    assert ctx["exp"] == 100
    assert ctx["ledger"] == {"tx-001", "tx-002"}


def test_idempotent_requires_both_tx_id_and_ledger():
    """只给 tx_id 不给 ledger → 不幂等（照常入账，不崩）。"""
    ctx = make_ctx()
    ctx["tx_id"] = "tx-001"
    r = dispatch_reward([{"exp": 50}], ctx)
    assert r["ok"] and r["granted"] == [{"type": "exp", "amount": 50}]
    assert ctx["exp"] == 50


def test_idempotent_records_ledger_even_with_skips():
    """批次含 skipped 条目也记 ledger（结算簿记原子，P1-2：条目失败不触发整单回滚）。"""
    ctx = make_ctx()
    ctx["tx_id"] = "tx-003"
    ctx["ledger"] = set()
    r = dispatch_reward([{"item": "不存在之物", "count": 1}, {"exp": 50}], ctx)
    assert r["ok"] and len(r["skipped"]) == 1
    assert "tx-003" in ctx["ledger"]
    # 重复调用 → 幂等（即使上次有 skip）
    r2 = dispatch_reward([{"item": "不存在之物", "count": 1}, {"exp": 50}], ctx)
    assert r2["idempotent"] is True and r2["granted"] == []
    assert ctx["exp"] == 50


def test_idempotent_item_add_failed_not_sealed_p1_1():
    """P1-1：批次含 item_add_failed → 不封口幂等；补接 hook 后同 tx 重试可补发。

    旧行为：批次完成（含 skipped）即记 ledger → 物品未入包也被封口，静默丢奖无法重试。
    新行为：item_add_failed 不记 ledger → 同 tx 重试补发成功后再封口。
    """
    ctx = make_ctx()
    ctx["tx_id"] = "tx-p11"
    ctx["ledger"] = set()
    r1 = dispatch_reward([{"item": "铁矿", "count": 3}], ctx)
    assert r1["ok"] and r1["granted"] == []
    assert r1["skipped"][0]["reason"] == "item_add_failed"
    assert "tx-p11" not in ctx["ledger"]  # 未封口 → 可重试

    calls = record_adds(ctx)  # 补接入包 hook
    r2 = dispatch_reward([{"item": "铁矿", "count": 3}], ctx)
    assert r2["ok"] and r2["granted"] == [{"type": "item", "item": "铁矿", "count": 3,
                                           "bound": True, "applied": True}]
    assert calls == [("铁矿", 3, True)]
    assert "tx-p11" in ctx["ledger"]  # 成功后封口

    r3 = dispatch_reward([{"item": "铁矿", "count": 3}], ctx)
    assert r3["idempotent"] is True and r3["granted"] == []
    assert len(calls) == 1  # 不二次入包


# ---------------------------------------------------------------------------
# 批级失败兜底与归一化
# ---------------------------------------------------------------------------

def test_batch_invalid_entries_type():
    r = dispatch_reward(12345, make_ctx())
    assert r["ok"] is False and r["granted"] == []
    assert r["skipped"][0]["reason"] == "invalid_entries"


def test_batch_invalid_ctx():
    r = dispatch_reward([{"exp": 1}], "not-a-dict")
    assert r["ok"] is False
    assert r["skipped"][0]["reason"] == "invalid_ctx"


def test_single_dict_entry():
    """reward 字段 = 单个 dict（非数组）也接受。"""
    ctx = make_ctx()
    r = dispatch_reward({"exp": 10}, ctx)
    assert r["ok"] and ctx["exp"] == 10


def test_mixed_list_str_and_dict_entries():
    """列表内混用内联串与结构化条目 → 各自展开。"""
    ctx = make_ctx()
    r = dispatch_reward(["exp=10", {"coins": 5}], ctx)
    assert r["ok"]
    assert ctx["exp"] == 10 and ctx["currencies"] == {"coins": 5}
    assert [g["type"] for g in r["granted"]] == ["exp", "currency"]


def test_normalize_reward_forms():
    assert normalize_reward("exp=1") == [{"exp": 1}]
    assert normalize_reward({"exp": 1}) == [{"exp": 1}]
    assert normalize_reward([{"exp": 1}, "gem=2"]) == [{"exp": 1}, {"gem": 2}]


def test_resolver_item_registry_callable():
    """resolve_item 解析器（callable）等价于 items 注册表。"""
    ctx = make_ctx()
    del ctx["items"]
    ctx["resolve_item"] = lambda iid: iid in ITEMS
    calls = record_adds(ctx)
    r = dispatch_reward([{"item": "铁矿", "count": 2}, {"item": "无", "count": 1}], ctx)
    assert r["ok"]
    assert calls == [("铁矿", 2, True)]
    assert r["skipped"][0]["reason"] == "item_not_found"
