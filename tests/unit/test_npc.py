"""NPC 发牌员核心单测（M4 批次2·路C2 · qbot_rpg/core/npc.py）。

依据：m4_shared_contract.md §3.1（NPC/对话 B1-B6）+ 细化_2b1_NPC数据与发牌员.md
（§二 三策略 DS01-04 / 抽牌状态机 SM01-07 / §三 10 类动作 AC01-10 / §四 一次一物 O01-O08）+
审查参考/NPC系统设计定稿.md（发牌员 L401-415 / 10 类动作 L126-137 / 一次一物 L83-92 / 事件计数 L289）+
2026-08-27 裁决④（保留 rotate/random/condition，first_match→condition、weighted→random 等权、
random→random 兼容映射）。

覆盖：策略归一（裁决④）· 牌池构建（条件/once/quest 去重）· 三策略抽牌（rotate 轮转/random 加权/
condition 顺序）· available_quests 三表去重 · deal 状态机（抽中/孤寂卡/once 出池/rotate 持久化）·
10 类动作分发（quest/shop/heal/give_item/buff/repair/teleport/intel/tutorial/reply）·
give_item 经 reward 解析器统一入账 + repeat once/daily · 一次一物（intel 置灰已听/落 npc_delivered/
写图鉴）· 条件统一（公共 condition 求值）· 纯函数（rng 注入确定性）。

"""
from __future__ import annotations

import random

from qbot_rpg.core.npc import (
    ACTIONS,
    DEGRADED_ACTIONS,
    FUNCTIONAL_ACTIONS,
    INFO_ACTIONS,
    LEGACY_STRATEGY_MAP,
    STRATEGIES,
    available_quests,
    build_pool,
    deal,
    dispatch_action,
    draw_card,
    is_delivered,
    mark_delivered,
    normalize_strategy,
    resolve_heal,
)

# ---------------------------------------------------------------------------
# 基础夹具
# ---------------------------------------------------------------------------

ITEMS = {"药水": {"id": "药水", "name": "药水"}, "铁矿": {"id": "铁矿", "name": "铁矿"}}
SETTINGS = {"currencies": [{"id": "coins"}, {"id": "gem"}]}


def make_ctx(**overrides) -> dict:
    """默认 ctx：货币/属性/物品注册表/npc_delivered/active_effects/codex_state/入包 hook。"""
    ctx = {
        "settings": SETTINGS,
        "currencies": {"coins": 100, "gem": 0},
        "exp": 0,
        "reputation_state": {},
        "items": ITEMS,
        "add_item": lambda item_id, count, bound: True,
        "hp": 10, "max_hp": 100,
        "mp": 5, "max_mp": 50,
        "level": 10,
        "map_id": "新手村",
        "npc_delivered": {},
        "active_effects": {},
        "codex_state": {},
        **overrides,
    }
    return ctx


def reply_card(cid: str, text: str = "你好", **kw) -> dict:
    return {"id": cid, "deliver": {"action": "reply", "text": [text]}, **kw}


# ---------------------------------------------------------------------------
# 策略归一（裁决④ / DS04）
# ---------------------------------------------------------------------------

def test_normalize_strategy_refined_values_passthrough():
    for s in STRATEGIES:
        r = normalize_strategy(s)
        assert r["strategy"] == s
        assert r["legacy"] is False
        assert r["migrate_hint"] is None


def test_normalize_strategy_legacy_mapping():
    """裁决④：first_match→condition、weighted→random 等权；random 两枚举同名（既兼容又规范，无迁移提示）。"""
    assert normalize_strategy("first_match")["strategy"] == "condition"
    assert normalize_strategy("weighted")["strategy"] == "random"
    # first_match/weighted 为新枚举非法值 → 必须带迁移提示
    for s in ("first_match", "weighted"):
        r = normalize_strategy(s)
        assert r["legacy"] is True
        assert "迁移" in (r["migrate_hint"] or "")
    # "random" 在新旧枚举中同名：直接按规范策略通过（无需迁移，兼容语义=等权纯随机）
    r = normalize_strategy("random")
    assert r["strategy"] == "random" and r["legacy"] is False
    # 大写/空白容忍
    assert normalize_strategy("  First_Match ")["strategy"] == "condition"


def test_normalize_strategy_default_and_unknown():
    """缺省/未知 → condition（DR01 承接定稿 first_match 默认态）。"""
    for bad in (None, "", "bogus", 42):
        r = normalize_strategy(bad)
        assert r["strategy"] == "condition"
        assert r["legacy"] is False


# ---------------------------------------------------------------------------
# 牌池构建（SM02：条件 / once 出池 / quest 去重）
# ---------------------------------------------------------------------------

def test_build_pool_condition_filter():
    """SM02：不满足条件的牌剔除；无 condition = 恒真保留；保留原始顺序。"""
    pool = [
        reply_card("A", condition={"var": "level", "op": "ge", "value": 50}),
        reply_card("B"),
        reply_card("C", condition={"var": "level", "op": "ge", "value": 5}),
    ]
    out = build_pool(pool, make_ctx(level=10))
    assert [c["id"] for c in out] == ["B", "C"]
    # 无 condition 恒真（保留）；A/C 条件不满足被剔除
    out = build_pool(pool, make_ctx(level=3))
    assert [c["id"] for c in out] == ["B"]
    # 全牌条件不满足 → 空池
    pool_all = [
        reply_card("A", condition={"var": "level", "op": "ge", "value": 50}),
        reply_card("C", condition={"var": "level", "op": "ge", "value": 5}),
    ]
    assert build_pool(pool_all, make_ctx(level=3)) == []


def test_build_pool_once_card_out_after_delivered():
    """P05：once 牌已交付（落 npc_delivered["card:<id>"]）→ 出池。"""
    ctx = make_ctx(npc_id="npc1")
    ctx["npc_delivered"] = {"npc1": {"card:c2": True}}
    pool = [reply_card("c1"), {"id": "c2", "once": True, "deliver": {"action": "reply", "text": ["x"]}}]
    out = build_pool(pool, ctx, npc_id="npc1")
    assert [c["id"] for c in out] == ["c1"]
    # 无 npc_id → 不判定 once（无法定位存档）
    assert len(build_pool(pool, ctx)) == 2


def test_build_pool_quest_card_no_available_excluded():
    """SM06：quest 卡无可交付候选（活跃/今日已发/已完成）→ 不出池。"""
    ctx = make_ctx(npc_id="npc1", quest_active={"q_a": {}})
    pool = [
        {"id": "q1", "deliver": {"action": "quest", "quests": [{"quest_id": "q_a"}]}},
        reply_card("B"),
    ]
    out = build_pool(pool, ctx)
    assert [c["id"] for c in out] == ["B"]


def test_build_pool_invalid_cards_skipped():
    assert build_pool([None, {}, {"id": "x"}], make_ctx()) == []
    assert build_pool("not-a-list", make_ctx()) == []


# ---------------------------------------------------------------------------
# 抽牌（SM03）：三策略
# ---------------------------------------------------------------------------

def test_draw_condition_first_eligible():
    """DS01 condition：按候选池顺序取第一个（顺序即优先级）。"""
    cards = [reply_card("A"), reply_card("B"), reply_card("C")]
    assert draw_card(cards, "condition")["id"] == "A"
    assert draw_card(cards, "first_match")["id"] == "A"  # 旧枚举兼容


def test_draw_rotate_cyclic_pointer():
    """DS03 rotate：轮转指针环形推进，抽过的牌本轮不重复（连抽 4 次 A→B→C→A）。"""
    cards = [reply_card("A"), reply_card("B"), reply_card("C")]
    st = {"index": 0}
    seq = [draw_card(cards, "rotate", state=st)["id"] for _ in range(4)]
    assert seq == ["A", "B", "C", "A"]
    assert st["index"] == 4  # 指针原地持久化（调用方存档）


def test_draw_random_weighted():
    """DS02 random：weight 归一化加权随机（TC-10 口径：X:Y ≈ 1:3）。"""
    cards = [reply_card("X", weight=1), reply_card("Y", weight=3)]
    rng = random.Random(12345)
    hits = {"X": 0, "Y": 0}
    for _ in range(4000):
        hits[draw_card(cards, "random", rng=rng)["id"]] += 1
    ratio = hits["Y"] / hits["X"]
    assert 2.4 < ratio < 3.6, hits  # 1:3 加权（宽松边界防偶发抖动）


def test_draw_random_uniform_when_all_zero_or_equal():
    """DS02：全 weight=0 或等权 → 纯随机等概率（TC-10）。"""
    rng = random.Random(7)
    cards = [reply_card("A", weight=0), reply_card("B", weight=0)]
    seen = {draw_card(cards, "random", rng=rng)["id"] for _ in range(200)}
    assert seen == {"A", "B"}
    cards_eq = [reply_card("A"), reply_card("B"), reply_card("C")]
    seen = {draw_card(cards_eq, "random", rng=rng)["id"] for _ in range(300)}
    assert seen == {"A", "B", "C"}


def test_draw_random_zero_weight_excluded_from_weighted_pool():
    """P03：weight=0 不入加权随机池（但全 0 时纯随机兜底）。"""
    rng = random.Random(1)
    cards = [reply_card("Z", weight=0), reply_card("A", weight=1)]
    hits = {"Z": 0, "A": 0}
    for _ in range(500):
        hits[draw_card(cards, "random", rng=rng)["id"]] += 1
    assert hits["Z"] == 0, hits


def test_draw_card_empty_pool():
    assert draw_card([], "condition") is None
    assert draw_card(None, "rotate") is None


# ---------------------------------------------------------------------------
# available_quests（SM06 三表去重 + 候选条件）
# ---------------------------------------------------------------------------

def test_available_quests_dedup_three_tables():
    """SM06：quest_active / quest_daily（扁平+嵌套）/ quest_completed 命中 → 不重发。"""
    deliver = {"quests": [
        {"quest_id": "q_active"},
        {"quest_id": "q_daily_flat"},
        {"quest_id": "q_daily_nested"},
        {"quest_id": "q_done"},
        {"quest_id": "q_ok"},
    ]}
    ctx = {
        "quest_active": {"q_active": {}},
        "quest_daily": {"q_daily_flat": {"done": 1}, "2026-08-26": {"q_daily_nested": {"done": 1}}},
        "quest_completed": {"q_done": True},
    }
    out = available_quests(deliver, ctx)
    assert [q["quest_id"] for q in out] == ["q_ok"]
    # 三表缺失 = 不去重（fail-safe）
    assert [q["quest_id"] for q in available_quests(deliver, {})] == [
        "q_active", "q_daily_flat", "q_daily_nested", "q_done", "q_ok",
    ]


def test_available_quests_condition_gate():
    """候选条目自带 condition 不满足 → 剔除；顺序即优先级。"""
    deliver = {"quests": [
        {"quest_id": "q1", "condition": {"var": "level", "op": "ge", "value": 50}},
        {"quest_id": "q2", "condition": {"var": "level", "op": "ge", "value": 5}},
    ]}
    assert [q["quest_id"] for q in available_quests(deliver, make_ctx(level=10))] == ["q2"]


# ---------------------------------------------------------------------------
# deal 状态机（SM02-05）
# ---------------------------------------------------------------------------

def test_deal_condition_picks_first_eligible_and_delivers():
    """condition 策略：跳过条件不满足的牌，按顺序交付首个满足者（TC-09）。"""
    ctx = make_ctx(npc_id="npc1")
    dealer = {
        "strategy": "condition",
        "pool": [
            {"id": "c1", "condition": {"var": "level", "op": "ge", "value": 50},
             "deliver": {"action": "reply", "text": ["高等级专属"]}},
            reply_card("c2"),
            reply_card("c3"),
        ],
    }
    r = deal("npc1", dealer, ctx)
    assert r["ok"] and r["card"]["id"] == "c2"
    assert r["action"] == "reply" and r["strategy"] == "condition"


def test_deal_lonely_card_empty_pool():
    """SM05 孤寂卡：池空/条件全不满足 → 普通问候（greeting 兜底），不交付（TC-12）。"""
    ctx = make_ctx(npc_id="npc1", level=1)
    dealer = {"strategy": "condition", "pool": [
        {"id": "x", "condition": {"var": "level", "op": "ge", "value": 99},
         "deliver": {"action": "reply", "text": ["x"]}},
    ]}
    r = deal("npc1", dealer, ctx, greeting="炉火正旺")
    assert r["lonely"] is True and r["card"] is None and r["ok"] is True
    assert r["message"] == "炉火正旺"
    # dealer 缺失 / 池缺失 → 孤寂卡兜底
    assert deal("npc1", None, ctx, greeting="g")["lonely"] is True
    assert deal("npc1", {"strategy": "rotate", "pool": []}, ctx)["lonely"] is True


def test_deal_once_card_removed_after_delivery():
    """P05：once 牌交付成功 → 落 npc_delivered（出池，后续不再发）。"""
    ctx = make_ctx(npc_id="npc1")
    dealer = {"strategy": "condition", "pool": [
        {"id": "gift", "once": True, "deliver": {"action": "give_item", "items": [{"id": "药水", "count": 2}], "repeat": "once"}},
        reply_card("c2"),
    ]}
    r1 = deal("npc1", dealer, ctx)
    assert r1["card"]["id"] == "gift" and r1["ok"]
    assert is_delivered(ctx, "npc1", "card:gift") is True
    r2 = deal("npc1", dealer, ctx)
    assert r2["card"]["id"] == "c2"  # gift 已出池


def test_deal_quest_card_dedup():
    """SM06：发牌员不重复发已完成/活跃任务（活跃任务卡 → 孤寂卡/跳过）。"""
    ctx = make_ctx(npc_id="npc1", quest_active={"q_a": {}})
    dealer = {"strategy": "condition", "pool": [
        {"id": "q1", "deliver": {"action": "quest", "quests": [{"quest_id": "q_a"}]}},
    ]}
    assert deal("npc1", dealer, ctx)["lonely"] is True
    # 有可用任务时正常发
    ctx2 = make_ctx(npc_id="npc1")
    r = deal("npc1", dealer, ctx2)
    assert r["ok"] and r["data"]["quest_id"] == "q_a"


def test_deal_rotate_persistent_state():
    """rotate：deal 复用调用方 rotate_state → 指针持续轮转（TC-11 连抽 4 次 A→B→C→A）。"""
    ctx = make_ctx(npc_id="npc1")
    dealer = {"strategy": "rotate", "pool": [reply_card("A"), reply_card("B"), reply_card("C")]}
    st = {"index": 0}
    seq = [deal("npc1", dealer, ctx, rotate_state=st)["card"]["id"] for _ in range(4)]
    assert seq == ["A", "B", "C", "A"]


def test_deal_random_strategy():
    """random：发牌员加权随机（确定性 rng 注入，同种子同结果）。"""
    ctx = make_ctx(npc_id="npc1")
    dealer = {"strategy": "random", "pool": [reply_card("A", weight=1), reply_card("B", weight=1)]}
    ids1 = [deal("npc1", dealer, ctx, rng=random.Random(9))["card"]["id"] for _ in range(50)]
    ids2 = [deal("npc1", dealer, ctx, rng=random.Random(9))["card"]["id"] for _ in range(50)]
    assert ids1 == ids2  # 同种子确定性


# ---------------------------------------------------------------------------
# dispatch_action：10 类动作
# ---------------------------------------------------------------------------

def test_dispatch_all_actions_registered():
    """10 类动作齐全（AC01-AC10 / L126-137）。"""
    assert set(ACTIONS) == {
        "quest", "shop", "heal", "give_item", "buff", "repair",
        "teleport", "intel", "tutorial", "reply",
    }
    assert set(INFO_ACTIONS) == {"intel", "tutorial"}
    assert "quest" in FUNCTIONAL_ACTIONS and "shop" in FUNCTIONAL_ACTIONS
    assert "repair" in DEGRADED_ACTIONS


def test_dispatch_unknown_and_invalid():
    assert dispatch_action(None, make_ctx())["reason"] == "invalid_entry"
    r = dispatch_action({"action": "nope"}, make_ctx())
    assert not r["ok"] and r["reason"] == "unknown_action"


def test_dispatch_public_condition_gate():
    """公共 condition（AC 全列共用）：不满足 → 不执行（reason=condition_not_met）。"""
    ctx = make_ctx(level=3)
    entry = {"action": "shop", "shop_refs": ["s1"], "condition": {"var": "level", "op": "ge", "value": 5}}
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "condition_not_met"
    assert "current_shop_ref" not in ctx  # 不满足 → 未执行
    # 满足 → 正常执行
    ctx_ok = make_ctx(level=7)
    r = dispatch_action(entry, ctx_ok, npc_id="npc1")
    assert r["ok"] and ctx_ok["current_shop_ref"] == "s1"


def test_dispatch_quest_returns_first_available():
    """AC01 quest：返回匹配候选任务（去重 + 顺序即优先级）。"""
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "quest", "quests": [
        {"quest_id": "q1", "condition": {"var": "level", "op": "ge", "value": 50}},
        {"quest_id": "q2"},
    ]}, ctx, npc_id="npc1")
    assert r["ok"] and r["data"]["quest_id"] == "q2"
    # 全部不可用 → 不发（不置灰，但无任务可给）
    r = dispatch_action({"action": "quest", "quests": [{"quest_id": "q_active"}]},
                        {"quest_active": {"q_active": {}}}, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "no_available_quest"


def test_dispatch_shop_sets_current_shop_ref():
    """AC02 shop：打开后 = 当前商店（地图级状态）。"""
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "shop", "shop_refs": ["blacksmith_shop"]}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["current_shop_ref"] == "blacksmith_shop"
    assert r["data"]["shop_ref"] == "blacksmith_shop"
    r = dispatch_action({"action": "shop", "shop_refs": []}, ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "no_shop_ref"


def test_dispatch_heal_flat_and_percent():
    """AC03 heal：int 直量 + "N%" 按上限；扣费；封顶。"""
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "heal", "cost": {"coins": 50}, "heal": {"hp": "100%", "mp": 10}},
                        ctx, npc_id="npc1")
    assert r["ok"]
    assert ctx["hp"] == 100 and ctx["mp"] == 15
    assert ctx["currencies"]["coins"] == 50
    assert r["data"]["cost"] == 50 and r["data"]["heal"] == {"hp": 100, "mp": 10}
    # 免费治疗（cost 省略）
    ctx = make_ctx(npc_id="npc1", hp=90)
    dispatch_action({"action": "heal", "heal": {"hp": 20}}, ctx, npc_id="npc1")
    assert ctx["hp"] == 100 and ctx["currencies"]["coins"] == 100  # 免费


def test_dispatch_heal_insufficient_funds():
    """heal 金币不足 → 不执行不扣费。"""
    ctx = make_ctx(npc_id="npc1", currencies={"coins": 10})
    r = dispatch_action({"action": "heal", "cost": {"coins": 50}, "heal": {"hp": 10}},
                        ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "insufficient_funds"
    assert ctx["currencies"]["coins"] == 10 and ctx["hp"] == 10


def test_resolve_heal_forms():
    assert resolve_heal({"hp": 30, "mp": "50%"}, make_ctx(max_mp=50)) == {"hp": 30, "mp": 25}
    assert resolve_heal({"hp": "abc%"}, make_ctx()) == {}
    assert resolve_heal(None, make_ctx()) == {}
    assert resolve_heal({"hp": -5}, make_ctx()) == {}


def test_dispatch_give_item_via_reward_parser():
    """AC04：give_item 经 reward 解析器统一入账（L153/A1），once 仅一次。"""
    calls = []
    ctx = make_ctx(npc_id="npc1")
    ctx["add_item"] = lambda i, c, b: (calls.append((i, c, b)) or True)
    entry = {"action": "give_item", "items": [{"id": "药水", "count": 3}], "repeat": "once"}
    r1 = dispatch_action(entry, ctx, npc_id="npc1")
    assert r1["ok"] and calls == [("药水", 3, True)]
    assert r1["granted"][0]["item"] == "药水" and r1["granted"][0]["applied"] is True
    # 第二次 → once 已领
    r2 = dispatch_action(entry, ctx, npc_id="npc1")
    assert not r2["ok"] and r2["already"] is True and r2["reason"] == "once_claimed"
    assert len(calls) == 1  # 不重复入账
    # 无 npc_id → 不记账照发（工程补白⑨）
    r3 = dispatch_action({"action": "give_item", "items": [{"id": "药水", "count": 1}], "repeat": "once"},
                         make_ctx())
    assert r3["ok"]


def test_dispatch_give_item_daily_reset():
    """give_item repeat=daily：当日已领拦截，次日（日期键变化）重新可领（TC-16）。"""
    ctx = make_ctx(npc_id="npc1", today="2026-08-26")
    entry = {"action": "give_item", "items": [{"id": "药水", "count": 1}], "repeat": "daily"}
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"]
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "daily_claimed" and r["already"]
    # 次日
    ctx["today"] = "2026-08-27"
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"]
    # 存档值 = 最后领取日
    assert ctx["npc_delivered"]["npc1"]["give_item:药水"] == "2026-08-27"


def test_dispatch_give_item_default_once_and_skipped_entries():
    """缺省 repeat=once；物品不存在 → reward 逐条目跳过（P1-2）不影响批次。"""
    ctx = make_ctx(npc_id="npc1")
    entry = {"action": "give_item", "items": [{"id": "不存在之物", "count": 1}, {"id": "药水", "count": 2}]}
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert r["ok"] and len(r["granted"]) == 1
    assert r["skipped"][0]["reason"] == "item_not_found"


def test_dispatch_buff_records_active_effects():
    """AC05 buff：effects[] 入 ctx["active_effects"]；同 buff 重触发仅刷新回合（补白⑥）。"""
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "buff", "effects": ["atk_up"], "turns": 3}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["active_effects"]["atk_up"]["turns"] == 3
    dispatch_action({"action": "buff", "effects": ["atk_up"], "turns": 5}, ctx, npc_id="npc1")
    assert ctx["active_effects"]["atk_up"]["turns"] == 5
    assert ctx["active_effects"]["atk_up"]["refreshed"] is True
    # 缺 active_effects 桶 → 不崩
    ctx_no_bucket = make_ctx(npc_id="npc1")
    del ctx_no_bucket["active_effects"]
    r = dispatch_action({"action": "buff", "effects": ["x"]}, ctx_no_bucket, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "no_effect_bucket"


def test_dispatch_repair_degraded():
    """AC06 repair：依赖装备耐久系统（框架未实现）→ 当前降级不可用+友好提示（S4/L139/TC-18）。"""
    r = dispatch_action({"action": "repair", "cost": {"coins": 10}}, make_ctx(), npc_id="npc1")
    assert not r["ok"] and r["kind"] == "degraded"
    assert r["reason"] == "repair_unavailable"
    assert "修理" in r["message"]


def test_dispatch_teleport_pays_and_moves():
    """AC07 teleport：扣传送费 + 改写 ctx["map_id"]。"""
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "teleport", "map": "主城", "cost": {"coins": 30}}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["map_id"] == "主城" and ctx["currencies"]["coins"] == 70
    # 免费 + 缺目标
    ctx = make_ctx(npc_id="npc1")
    r = dispatch_action({"action": "teleport", "map": "主城"}, ctx, npc_id="npc1")
    assert r["ok"] and ctx["currencies"]["coins"] == 100
    r = dispatch_action({"action": "teleport"}, ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "no_target"


def test_dispatch_teleport_insufficient_funds():
    ctx = make_ctx(npc_id="npc1", currencies={"coins": 5})
    r = dispatch_action({"action": "teleport", "map": "主城", "cost": {"coins": 30}}, ctx, npc_id="npc1")
    assert not r["ok"] and r["reason"] == "insufficient_funds"
    assert ctx["map_id"] == "新手村"  # 未移动


def test_dispatch_intel_once_item_greyed():
    """AC08 intel 一次一物：交付后置灰"已听"（落 npc_delivered + 写图鉴 codex_state，O01/O07/L89）。"""
    ctx = make_ctx(npc_id="npc1")
    entry = {"action": "intel", "intel_refs": ["beetle_lore"]}
    r1 = dispatch_action(entry, ctx, npc_id="npc1")
    assert r1["ok"] and r1["delivered"] is True and r1["kind"] == "info"
    assert is_delivered(ctx, "npc1", "intel:beetle_lore") is True
    assert ctx["codex_state"].get("beetle_lore") is True  # 图鉴可回看（不死胡同）
    # 再选 → "你已经听过了"
    r2 = dispatch_action(entry, ctx, npc_id="npc1")
    assert not r2["ok"] and r2["already"] is True and r2["reason"] == "already_heard"


def test_dispatch_tutorial_once_first_meet():
    """AC09 tutorial：first_meet 仅首见触发；首见即一次，可回看。"""
    ctx = make_ctx(npc_id="npc1")
    entry = {"action": "tutorial", "tutorials": ["pv_break_tut"]}
    assert dispatch_action(entry, ctx, npc_id="npc1")["ok"]
    assert is_delivered(ctx, "npc1", "tutorial:pv_break_tut") is True
    r = dispatch_action(entry, ctx, npc_id="npc1")
    assert not r["ok"] and r["already"] is True and r["reason"] == "already_taught"


def test_dispatch_reply_random_and_cycle():
    """AC10 reply：text[] 随机（rng 注入）/ 循环（state 指针）取一条。"""
    rng = random.Random(0)
    texts = ["你好", "再见", "幸会"]
    r = dispatch_action({"action": "reply", "text": texts}, make_ctx(), rng=rng, npc_id="npc1")
    assert r["ok"] and r["data"]["text"] in texts
    # cycle 模式
    st = {"reply_index": 0}
    seq = [dispatch_action({"action": "reply", "text": ["a", "b"], "mode": "cycle"},
                           make_ctx(), state=st, npc_id="npc1")["data"]["text"] for _ in range(4)]
    assert seq == ["a", "b", "a", "b"]


# ---------------------------------------------------------------------------
# 一次一物存档（npc_delivered，O03/O07）
# ---------------------------------------------------------------------------

def test_npc_delivered_per_npc_isolation():
    """已交付标记按 NPC 隔离（O07：NPC ID → 已交付键集合）。"""
    ctx = make_ctx()
    assert mark_delivered(ctx, "npc1", "intel:x") is True
    assert mark_delivered(ctx, "npc2", "intel:y") is True
    assert is_delivered(ctx, "npc1", "intel:x") is True
    assert is_delivered(ctx, "npc1", "intel:y") is False
    assert is_delivered(ctx, "npc2", "intel:y") is True
    # 缺节点 → fail-safe False / 落盘 False
    assert is_delivered({}, "npc1", "intel:x") is False
    assert mark_delivered({}, "npc1", "intel:x") is False
    assert is_delivered(ctx, "", "k") is False
    # 值语义：daily 存日期键
    mark_delivered(ctx, "npc3", "give_item:药水", "2026-08-26")
    assert ctx["npc_delivered"]["npc3"]["give_item:药水"] == "2026-08-26"
    assert is_delivered(ctx, "npc3", "give_item:药水")


def test_mark_delivered_creates_node_lazily():
    ctx = make_ctx()
    mark_delivered(ctx, "npc1", "card:c1")
    assert ctx["npc_delivered"] == {"npc1": {"card:c1": True}}
