"""任务引擎单测（M4 批次4·路E2 · qbot_rpg/core/quest.py）——三原语求值 + 接取/交付/防刷 + 主线置顶 + 双板。

依据：m4_shared_contract.md §3.3（D1-D5）+ 细化_2b4_任务引擎契约.md（三原语 §二 / 统一 reward §三 /
防刷 §四 F-1~F-5 / 任务板 §五 / TC-01~TC-31）+ 任务系统设计定稿.md（L19-36 三原语 / L183-187 防刷 /
L108-126 统一 reward / L138 main 常驻）+ M4 设计审查批次4（P2-1 主线计入 accept_limit 行数 /
P3-2 接取数记录供面板）。

覆盖：三原语求值（值型/累计型/事件型/op 双写/全与/失败降级）· 接取（accept_limit≤5/0=不限/主线计入/
unlock_chain/已完成拦截/每日接取计数）· 进度（逐条件 current/target/met + 交付判定）· 完成结算
（reward 发放 exp/货币/物品/rep / 完成即移出 / daily_limit≤10/0=不限 / main_progress / consume 扣物 /
重复衰减 / 幂等 / 条目失败跳过 / 物品未入包整单回滚不封口幂等 P1-1）· 任务板（主线置顶/板槽/NPC 支线/
序号/active 标记/zone 排除）· quest_daily 懒计算（05:00 重置）· 放弃。
"""

from __future__ import annotations

import datetime

import pytest

from qbot_rpg.core.dayroll import today_of
from qbot_rpg.core.quest import (
    DEFAULT_ACCEPT_LIMIT,
    DEFAULT_BOARD,
    DEFAULT_DAILY_LIMIT,
    quest_abandon,
    quest_accept,
    quest_available,
    quest_board,
    quest_complete,
    quest_daily_reset,
    quest_daily_state,
    quest_progress,
    resolve_board_index,
    resolve_quest,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


NOW = _ts(2026, 8, 27, 12, 0, 0)
TODAY = today_of(None, NOW, {"refresh_time": "05:00"})["today"]

ITEMS = {
    "铁矿": {"id": "铁矿", "name": "铁矿", "quality": "normal"},
    "铁矿石": {"id": "铁矿石", "name": "铁矿石", "quality": "normal"},
    "药水": {"id": "药水", "name": "药水", "quality": "normal"},
}

SETTINGS = {"refresh_time": "05:00", "currencies": [{"id": "coins"}, {"id": "gem"}]}


def make_quest(qid: str = "q1", **kw) -> dict:
    """最小 quest 定义（2b4 §1.2 默认值兜底 D-07 之外的引擎消费字段显式给出）。"""
    base = {
        "id": qid,
        "name": f"任务{qid}",
        "desc": "",
        "type": "collect",
        "conditions": [],
        "consume": False,
        "reward": "",
        "board": None,
        "timed": None,
        "unlock_chain": None,
        "zone": None,
        "filter": None,
        "bonus": None,
        "npc": None,
        "main": False,
        "daily": False,
        "repeatable": False,
    }
    base.update(kw)
    return base


def make_ctx(**overrides) -> dict:
    """默认 ctx：任务注册表 + active/completed/daily + 计数器 + reward 桶 + 物品注册表 + now。"""
    ctx = {
        "settings": SETTINGS,
        "quests": {},
        "quest_active": {},
        "quest_completed": set(),
        "quest_daily": {"key": TODAY, "completed": 0, "accepted": 0, "decay": {}},
        "longline_counters": {},
        "event_counts": {},
        "inventory": {},
        "currencies": {},
        "exp": 0,
        "reputation_state": {},
        "items": ITEMS,
        "add_item": None,
        "remove_item": None,
        "count_item": None,
        "now": NOW,
        **overrides,
    }
    return ctx


def add_quests(ctx: dict, *quests) -> None:
    for q in quests:
        ctx["quests"][q["id"]] = q


def record_adds(ctx: dict) -> list:
    """注入入包 hook 并收集调用记录，返回 [(item_id, count, bound), ...]。"""
    calls = []
    ctx["add_item"] = lambda item_id, count, bound: (calls.append((item_id, count, bound)) or True)  # type: ignore[func-returns-value]
    return calls


# ===========================================================================
# ① 三原语求值（quest_available / quest_conditions_met）
# ===========================================================================

def test_value_primitive_level_tc06():
    """TC-06：值型 {var:level,op:ge,value:10}：LV10 满足、LV9 不满足；读当前状态快照。"""
    q = make_quest(conditions=[{"var": "level", "op": "ge", "value": 10}])
    assert quest_available(q, make_ctx(level=10)) is True
    assert quest_available(q, make_ctx(level=9)) is False


def test_value_primitive_item_count_exact_tc07():
    """TC-07：值型 item_count+param 精确目标：铁矿 20 满足；铁矿石 20 不算。"""
    q = make_quest(conditions=[{"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"}])
    assert quest_available(q, make_ctx(inventory={"铁矿": 20})) is True
    assert quest_available(q, make_ctx(inventory={"铁矿石": 20})) is False


def test_accum_gain_count_longline_tc08():
    """TC-08：累计型 gain_count 读 longline_counters（跨任务复用，任务只读不重复计数）。"""
    q = make_quest(conditions=[{"var": "gain_count", "op": "ge", "value": 30, "param": "铁矿"}])
    nested = make_ctx(longline_counters={"gain_count": {"铁矿": 30}})
    flat = make_ctx(longline_counters={"gain_count:铁矿": 30})
    assert quest_available(q, nested) is True
    assert quest_available(q, flat) is True
    assert quest_available(q, make_ctx(longline_counters={"gain_count": {"铁矿": 29}})) is False


def test_accum_kill_count_tc09():
    """TC-09：累计型 kill_count 击杀计数读 longline_counters，与击杀累计共享计数。"""
    q = make_quest(conditions=[{"var": "kill_count", "op": "ge", "value": 3, "param": "熔岩甲虫"}])
    assert quest_available(q, make_ctx(longline_counters={"kill_count": {"熔岩甲虫": 3}})) is True
    assert quest_available(q, make_ctx(longline_counters={"kill_count": {"熔岩甲虫": 2}})) is False


def test_event_primitive_tc10():
    """TC-10：事件型 [事件:dungeon_clear] 触发计数 ≥1（param 目标）满足；未通关不满足。"""
    q = make_quest(conditions=[
        {"var": "[事件:dungeon_clear]", "op": "ge", "value": 1, "param": "熔岩洞窟"}])
    ctx = make_ctx(event_counts={"[事件:dungeon_clear]": {"熔岩洞窟": 1}})
    assert quest_available(q, ctx) is True
    assert quest_available(q, make_ctx(event_counts={})) is False


def test_op_symbol_equivalent_tc11():
    """TC-11：op 双写等价：`>=` ≡ ge（同参同结果）。"""
    a = make_quest(conditions=[{"var": "level", "op": ">=", "value": 10}])
    b = make_quest(conditions=[{"var": "level", "op": "ge", "value": 10}])
    for lv in (9, 10, 11):
        ctx = make_ctx(level=lv)
        assert quest_available(a, ctx) == quest_available(b, ctx)


def test_conditions_all_and_tc12():
    """TC-12：conditions 数组全与（D-02）：仅满足其一 → 不完成。"""
    q = make_quest(conditions=[
        {"var": "level", "op": "ge", "value": 10},
        {"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"},
    ])
    assert quest_available(q, make_ctx(level=10, inventory={"铁矿": 5})) is False
    assert quest_available(q, make_ctx(level=5, inventory={"铁矿": 20})) is False
    assert quest_available(q, make_ctx(level=10, inventory={"铁矿": 20})) is True


def test_fail_safe_unknown_event_tc31():
    """TC-31：条件引用未注册事件 → 求值失败默认不满足（D-03），不崩溃不阻塞。"""
    q = make_quest(conditions=[{"var": "[事件:future_patch]", "op": "ge", "value": 1}])
    assert quest_available(q, make_ctx(event_counts={})) is False
    # 未知 var 同样 fail-safe
    q2 = make_quest(conditions=[{"var": "totally_unknown_var", "op": "ge", "value": 1}])
    assert quest_available(q2, make_ctx()) is False


def test_empty_conditions_accept_ready():
    """定稿 L98：conditions 数组为空 = 接取即完成（available 恒真）。"""
    q = make_quest(conditions=[])
    assert quest_available(q, make_ctx()) is True


def test_quest_available_bare_conditions_for_npc():
    """quest_available 可对裸条件数组求值（NPC 发任务条件/候选命中，2b4 §1.4）。"""
    npc_conds = [{"var": "prof_level", "op": "lt", "value": 3, "param": "采集"}]
    assert quest_available(npc_conds, make_ctx(prof_level={"采集": 2})) is True
    assert quest_available(npc_conds, make_ctx(prof_level={"采集": 3})) is False


# ===========================================================================
# ② 接取（quest_accept）
# ===========================================================================

def test_accept_success_records_active_and_daily():
    """接取成功：入 quest_active（ID+名称冗余）、quest_daily.accepted +1。"""
    ctx = make_ctx()
    add_quests(ctx, make_quest("q1", conditions=[]))
    out = quest_accept("q1", ctx)
    assert out["ok"] is True
    assert ctx["quest_active"]["q1"]["name"] == "任务q1"
    assert ctx["quest_daily"]["accepted"] == 1
    assert ctx["quest_daily"]["key"] == TODAY


def test_accept_no_quest():
    ctx = make_ctx()
    out = quest_accept("nope", ctx)
    assert out["ok"] is False and out["reason"] == "no_quest"


def test_accept_already_active():
    ctx = make_ctx(quest_active={"q1": {"name": "任务q1"}})
    add_quests(ctx, make_quest("q1"))
    out = quest_accept("q1", ctx)
    assert out["ok"] is False and out["reason"] == "already_active"


def test_accept_completed_non_repeatable_rejected_tc21():
    """TC-21：完成即移出 active，非 repeatable 不可再接（提示「任务已完成」）。"""
    ctx = make_ctx(quest_completed={"q1"})
    add_quests(ctx, make_quest("q1", conditions=[]))
    out = quest_accept("q1", ctx)
    assert out["ok"] is False and out["reason"] == "already_completed"
    assert "任务已完成" in out["message"]


def test_accept_completed_repeatable_allowed():
    ctx = make_ctx(quest_completed={"q1"})
    add_quests(ctx, make_quest("q1", repeatable=True, conditions=[]))
    out = quest_accept("q1", ctx)
    assert out["ok"] is True


def test_accept_limit_reject_tc20():
    """TC-20：默认 accept_limit=5：同时进行中 5 个再接第 6 个 → 拒绝；quest_active 保持 5。"""
    ctx = make_ctx()
    quests = [make_quest(f"q{i}", conditions=[]) for i in range(1, 7)]
    add_quests(ctx, *quests)
    for i in range(1, 6):
        assert quest_accept(f"q{i}", ctx)["ok"] is True
    assert len(ctx["quest_active"]) == 5
    out = quest_accept("q6", ctx)
    assert out["ok"] is False and out["reason"] == "accept_limit"
    assert "同时最多进行 5 个任务" in out["message"]
    assert len(ctx["quest_active"]) == 5


def test_accept_limit_zero_unlimited():
    ctx = make_ctx()
    add_quests(ctx, *[make_quest(f"q{i}", conditions=[], board={"daily_limit": 10, "accept_limit": 0})
                      for i in range(8)])
    for i in range(1, 8):
        assert quest_accept(f"q{i}", ctx)["ok"] is True
    assert len(ctx["quest_active"]) == 7


def test_accept_main_counts_toward_limit_p2_1():
    """P2-1 裁决：主线计入 accept_limit 行数（不引入主线豁免）——5 行（含主线）已满再拒绝。"""
    ctx = make_ctx()
    quests = [
        make_quest("main1", conditions=[], main=True),
        *[make_quest(f"q{i}", conditions=[]) for i in range(1, 6)],
    ]
    add_quests(ctx, *quests)
    assert quest_accept("main1", ctx)["ok"] is True        # 主线占 1 行
    for i in range(1, 5):
        assert quest_accept(f"q{i}", ctx)["ok"] is True    # 共 5 行
    out = quest_accept("q5", ctx)
    assert out["ok"] is False and out["reason"] == "accept_limit"


def test_accept_chain_locked():
    """unlock_chain：前置未完成 → 拒绝；前置完成后 → 可接。"""
    ctx = make_ctx()
    add_quests(ctx,
               make_quest("q_prev", conditions=[], reward="exp=10"),
               make_quest("q_next", conditions=[], unlock_chain="q_prev"))
    out = quest_accept("q_next", ctx)
    assert out["ok"] is False and out["reason"] == "chain_locked"
    assert quest_accept("q_prev", ctx)["ok"] is True
    assert quest_complete("q_prev", ctx)["ok"] is True
    out2 = quest_accept("q_next", ctx)
    assert out2["ok"] is True


# ===========================================================================
# ③ 进度 / 交付判定（quest_progress）
# ===========================================================================

def test_progress_three_primitives_display():
    """quest_progress：值型/累计型/事件型 current/target/met 逐条显示 + 总判定。"""
    ctx = make_ctx(
        level=10,
        inventory={"铁矿": 12},
        longline_counters={"gain_count": {"铁矿": 30}},
        event_counts={"[事件:map_enter]": {"熔岩回廊": 1}},
    )
    q = make_quest(conditions=[
        {"var": "level", "op": "ge", "value": 10},
        {"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"},
    ])
    add_quests(ctx, q)
    out = quest_progress("q1", ctx)
    assert out["ok"] is True
    by_var = {c["var"]: c for c in out["conditions"]}
    assert by_var["level"]["current"] == 10 and by_var["level"]["met"] is True
    assert by_var["item_count"]["current"] == 12 and by_var["item_count"]["met"] is False
    assert out["met"] is False  # 全与（D-02）


def test_progress_met_when_deliverable():
    ctx = make_ctx(level=10, inventory={"铁矿": 20})
    q = make_quest(conditions=[{"var": "item_count", "op": "ge", "value": 20, "param": "铁矿"}])
    add_quests(ctx, q)
    out = quest_progress("q1", ctx)
    assert out["met"] is True
    assert out["required_items"] == {}


def test_progress_required_items_for_consume():
    ctx = make_ctx(inventory={"铁矿": 5})
    q = make_quest(consume=True, conditions=[
        {"var": "item_count", "op": "ge", "value": 3, "param": "铁矿"}])
    add_quests(ctx, q)
    out = quest_progress("q1", ctx)
    assert out["consume"] is True
    assert out["required_items"] == {"铁矿": 3}


# ===========================================================================
# ④ 完成结算（quest_complete）
# ===========================================================================

def _prepare_complete(reward, *, conditions=None, qid="q1", **qkw) -> dict:
    ctx = make_ctx()
    conds = conditions if conditions is not None else [{"var": "level", "op": "ge", "value": 1}]
    add_quests(ctx, make_quest(qid, conditions=conds, reward=reward, **qkw))
    assert quest_accept(qid, ctx)["ok"] is True
    return ctx


def test_complete_reward_exp_coin_item_tc13_15():
    """TC-13/14/15：组合 reward [exp,coins,item] 按序入账（exp 直入/货币/物品入包）。"""
    ctx = _prepare_complete([{"exp": 50}, {"coins": 80}, {"item": "铁矿", "count": 3}],
                            conditions=[])
    adds = record_adds(ctx)
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["exp"] == 50
    assert ctx["currencies"]["coins"] == 80
    assert ("铁矿", 3, True) in adds  # 物品入包默认绑定


def test_complete_rep_into_reputation_state_tc16():
    """TC-16：rep 入 reputation_state（不入货币表）。"""
    ctx = _prepare_complete([{"rep": 20}], conditions=[])
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["reputation_state"]["global"] == 20
    assert ctx["currencies"] == {}


def test_complete_inline_reward_sugar_d05():
    """D-05：内联串 reward 与结构化数组等价（经 reward.normalize 展开）。"""
    ctx = _prepare_complete("exp=50,coins=80,item:铁矿*3", conditions=[])
    adds = record_adds(ctx)
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["exp"] == 50 and ctx["currencies"]["coins"] == 80
    assert ("铁矿", 3, True) in adds


def test_complete_removes_active_counts_daily_tc21():
    """TC-21：完成即移出 active + quest_daily.completed +1 + quest_completed 登记。"""
    ctx = _prepare_complete([{"exp": 50}], conditions=[])
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert "q1" not in ctx["quest_active"]
    assert "q1" in ctx["quest_completed"]
    assert ctx["quest_daily"]["completed"] == 1
    assert out["completed_today"] == 1
    # 不可再接
    assert quest_accept("q1", ctx)["ok"] is False


def test_complete_not_active_rejected():
    ctx = make_ctx()
    add_quests(ctx, make_quest("q1", conditions=[]))
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "not_active"


def test_complete_not_met_rejected():
    ctx = make_ctx(level=9)
    add_quests(ctx, make_quest("q1", conditions=[{"var": "level", "op": "ge", "value": 10}]))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "not_met"


def test_complete_daily_limit_reject_tc18():
    """TC-18：默认 daily_limit=10：今日已完成 10 个再交付第 11 个 → 拒绝，计数不再增。"""
    ctx = make_ctx(quest_daily={"key": TODAY, "completed": 10, "accepted": 0, "decay": {}})
    add_quests(ctx, make_quest("q1", conditions=[]))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "daily_limit"
    assert "今日任务已完成 10/10，明早 5 点刷新" in out["message"]
    assert ctx["quest_daily"]["completed"] == 10


def test_complete_daily_limit_zero_unlimited_tc19():
    """TC-19：daily_limit:0 = 不限，防刷闸关闭。"""
    ctx = make_ctx(quest_daily={"key": TODAY, "completed": 10, "accepted": 0, "decay": {}})
    add_quests(ctx, make_quest("q1", conditions=[], board={"daily_limit": 0}))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["quest_daily"]["completed"] == 11


def test_complete_main_progress_and_stays_on_board_tc22():
    """TC-22：主线完成 → main_progress +1；/任务 仍置顶常驻显示；主线不可再接（防无限领奖）。"""
    ctx = make_ctx()
    add_quests(ctx, make_quest("m1", conditions=[], main=True, reward="exp=100"))
    assert quest_accept("m1", ctx)["ok"] is True
    out = quest_complete("m1", ctx)
    assert out["ok"] is True
    assert ctx["longline_counters"]["main_progress"] == 1
    assert out["main_progress"] == 1
    board = quest_board(ctx)
    main_rows = [s for s in board["sections"] if s["slot"] == "main"][0]["rows"]
    assert len(main_rows) == 1 and main_rows[0]["quest_id"] == "m1"
    assert main_rows[0]["marked"] is False  # 主线置顶不标 *
    assert quest_accept("m1", ctx)["ok"] is False  # 非 repeatable 主线完成不可再接


def test_complete_consume_deducts_items():
    """consume=true：交付扣物出包（item_count 条件推导应扣数量）；不够 → 条件不满足拒绝交付。"""
    ctx = make_ctx(inventory={"铁矿": 5})
    add_quests(ctx, make_quest("q1", consume=True,
                               conditions=[{"var": "item_count", "op": "ge", "value": 3,
                                            "param": "铁矿"}],
                               reward="exp=50"))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["inventory"]["铁矿"] == 2
    assert ctx["exp"] == 50

    # 背包不够 → 交付条件本身不满足（③ not_met，扣物校验链在条件达成之后）
    ctx2 = make_ctx(inventory={"铁矿": 2})
    add_quests(ctx2, make_quest("q1", consume=True,
                                conditions=[{"var": "item_count", "op": "ge", "value": 3,
                                             "param": "铁矿"}]))
    assert quest_accept("q1", ctx2)["ok"] is True
    out2 = quest_complete("q1", ctx2)
    assert out2["ok"] is False and out2["reason"] == "not_met"


def test_complete_consume_insufficient_items_branch():
    """consume=true ⑤ 扣物校验：条件达成但可扣数不足（count hook 权威）→ insufficient_items。"""
    ctx = make_ctx(inventory={"铁矿": 3})
    ctx["count_item"] = lambda item_id: 1  # hook 权威与实际背包不一致（扣物校验走 hook）
    add_quests(ctx, make_quest("q1", consume=True,
                               conditions=[{"var": "item_count", "op": "ge", "value": 3,
                                            "param": "铁矿"}]))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "insufficient_items"


def test_complete_repeatable_decay_tc23():
    """TC-23：repeatable={decay:0.5,cap:1} 同一任务重复完成：2 次 ×0.5、3 次 ×0.25 至 cap。"""
    ctx = make_ctx()
    add_quests(ctx, make_quest("q1", conditions=[],
                               repeatable={"decay": 0.5, "cap": 1}, reward="exp=100"))
    gained = []
    for i in range(3):
        assert quest_accept("q1", ctx)["ok"] is True
        out = quest_complete("q1", ctx)
        assert out["ok"] is True
        gained.append(ctx["exp"])
    assert gained == [100, 150, 175]  # +100 / +50 / +25
    assert ctx["quest_daily"]["decay"]["q1"] == 3


def test_complete_idempotent_d04():
    """D-04：同 tx_id 重复调用 → idempotent，不二次发放。"""
    ctx = make_ctx(tx_id="tx-1", ledger=set())
    add_quests(ctx, make_quest("q1", conditions=[], reward="exp=50"))
    assert quest_accept("q1", ctx)["ok"] is True
    out1 = quest_complete("q1", ctx)
    assert out1["ok"] is True and ctx["exp"] == 50
    out2 = quest_complete("q1", ctx)
    assert out2["ok"] is True and out2["idempotent"] is True
    assert ctx["exp"] == 50  # 不二次发放
    assert "q1" not in ctx["quest_active"]  # 幂等不再改动


def test_complete_entry_failure_skips_p1_2():
    """P1-2：reward 逐条目失败黄字跳过、不中断整批（物品不存在 → skip，exp/coins 照常入账）。"""
    ctx = _prepare_complete([{"exp": 50}, {"item": "不存在的物品", "count": 3}, {"coins": 80}],
                            conditions=[])
    out = quest_complete("q1", ctx)
    assert out["ok"] is True
    assert ctx["exp"] == 50 and ctx["currencies"]["coins"] == 80
    assert out["skipped"] and out["skipped"][0]["reason"] in ("item_not_found", "item_registry_missing")
    # 结算簿记仍完成（单事务=簿记原子性，条目失败不触发整单回滚）
    assert "q1" not in ctx["quest_active"]
    assert ctx["quest_daily"]["completed"] == 1


def test_complete_item_no_add_hook_rolls_back_retryable_p1_1():
    """M4 实现审查批次1 P1-1：无 add_item hook → 物品奖励未入包 → 整单回滚 + 黄字提示 + 可重试。

    旧行为：物品条目 granted(applied=False) 且幂等封口 → 静默丢奖无法补救。
    新行为：reward 层 skip(item_add_failed)，本引擎结算后判定 → 整单回滚（exp/coins 也回滚、
    quest 仍在 active、daily 不计）、ledger 不封口、message 提示"物品未入包"。
    """
    ctx = _prepare_complete([{"exp": 50}, {"item": "铁矿", "count": 3}], conditions=[])
    ctx["tx_id"] = "tx-p11"
    ctx["ledger"] = set()
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "item_add_failed"
    assert out["retryable"] is True
    assert "物品未入包" in out["message"]
    # 整单回滚：exp 未入账、任务仍在进行中、daily 不计、幂等 ledger 未封口
    assert ctx["exp"] == 0 and ctx["currencies"] == {}
    assert "q1" in ctx["quest_active"]
    assert ctx["quest_daily"]["completed"] == 0
    assert "tx-p11" not in ctx["ledger"]


def test_complete_item_no_hook_retry_after_wire_succeeds_p1_1():
    """P1-1：物品未入包回滚且不封口幂等 → 补接 add_item hook 后同 tx 重试成功，且可再次幂等。"""
    ctx = _prepare_complete([{"exp": 50}, {"item": "铁矿", "count": 3}], conditions=[])
    ctx["tx_id"] = "tx-p11"
    ctx["ledger"] = set()
    out1 = quest_complete("q1", ctx)
    assert out1["ok"] is False and out1["reason"] == "item_add_failed"
    assert "tx-p11" not in ctx["ledger"]  # 未封口 → 可重试

    adds = record_adds(ctx)  # 装配补接入包 hook（批次 7 make_context 注入 add_item）
    out2 = quest_complete("q1", ctx)
    assert out2["ok"] is True
    assert ctx["exp"] == 50 and ("铁矿", 3, True) in adds  # 奖励完整入账
    assert "tx-p11" in ctx["ledger"]  # 成功后封口

    out3 = quest_complete("q1", ctx)
    assert out3["idempotent"] is True and ctx["exp"] == 50  # 不二次发放


def test_complete_item_hook_returns_false_rolls_back_p1_1():
    """P1-1：add_item hook 存在但返回 False（背包拒绝）→ 同样整单回滚 + 不封口幂等。"""
    ctx = _prepare_complete([{"item": "铁矿", "count": 3}], conditions=[])
    ctx["add_item"] = lambda item_id, count, bound: False
    ctx["tx_id"] = "tx-p11"
    ctx["ledger"] = set()
    out = quest_complete("q1", ctx)
    assert out["ok"] is False and out["reason"] == "item_add_failed"
    assert "物品未入包" in out["message"]
    assert "q1" in ctx["quest_active"]
    assert "tx-p11" not in ctx["ledger"]


# ===========================================================================
# ⑤ 任务板（quest_board / resolve_board_index）
# ===========================================================================

def test_board_main_pinned_ordering_tc24():
    """TC-24：/任务 = 主线置顶 + 板槽任务 + NPC 支线，全局展示序号连续。"""
    ctx = make_ctx()
    add_quests(ctx,
               make_quest("m1", conditions=[], main=True),
               make_quest("m2", conditions=[], main=True),
               make_quest("d1", conditions=[]),
               make_quest("d2", conditions=[]),
               make_quest("n1", conditions=[], npc={"id": "铁匠"}),
               )
    board = quest_board(ctx)
    slots = [s["slot"] for s in board["sections"]]
    assert slots == ["main", "daily", "npc"]
    main_rows = board["sections"][0]["rows"]
    assert [r["quest_id"] for r in main_rows] == ["m1", "m2"]
    daily_rows = board["sections"][1]["rows"]
    assert [r["quest_id"] for r in daily_rows] == ["d1", "d2"]
    assert board["sections"][2]["slot"] == "npc"
    # 全局序号 1..5
    all_idx = [r["index"] for s in board["sections"] for r in s["rows"]]
    assert all_idx == [1, 2, 3, 4, 5]
    assert board["total"] == 5


def test_board_active_marker_tc25():
    """TC-25：已接取任务列表标 *（active），主线不标 *。"""
    ctx = make_ctx(quest_active={"d1": {"name": "任务d1"}})
    add_quests(ctx, make_quest("d1", conditions=[]), make_quest("m1", conditions=[], main=True))
    board = quest_board(ctx)
    rows = {r["quest_id"]: r for s in board["sections"] for r in s["rows"]}
    assert rows["d1"]["marked"] is True and rows["d1"]["active"] is True
    assert rows["m1"]["marked"] is False


def test_board_zone_excluded():
    """zone 限定副本子任务不占板槽位（2b4 §1.2 字段 12）。"""
    ctx = make_ctx()
    add_quests(ctx, make_quest("zone_q", conditions=[], zone="molten_dungeon"))
    board = quest_board(ctx)
    assert board["sections"] == [] or all(
        r["quest_id"] != "zone_q" for s in board["sections"] for r in s["rows"])


def test_board_weekly_event_slots():
    ctx = make_ctx()
    add_quests(ctx,
               make_quest("w1", conditions=[], board={"slot": "weekly", "refresh": "weekly"}),
               make_quest("e1", conditions=[], board={"slot": "event", "refresh": "once"}),
               )
    board = quest_board(ctx)
    slots = [s["slot"] for s in board["sections"]]
    assert slots == ["weekly", "event"]


def test_resolve_board_index():
    ctx = make_ctx()
    add_quests(ctx,
               make_quest("m1", conditions=[], main=True),
               make_quest("d1", conditions=[]),
               make_quest("n1", conditions=[], npc={"id": "铁匠"}),
               )
    assert resolve_board_index(ctx, 1) == "m1"
    assert resolve_board_index(ctx, 2) == "d1"
    assert resolve_board_index(ctx, 3) == "n1"
    assert resolve_board_index(ctx, 4) is None
    assert resolve_board_index(ctx, 0) is None


# ===========================================================================
# ⑥ quest_daily 懒计算（05:00 重置）
# ===========================================================================

def test_daily_lazy_reset_tc30():
    """TC-30：跨天首个操作惰性补算重置（昨日完成 3 / 接取 2 → 清零可再刷）。"""
    yesterday = today_of(None, _ts(2026, 8, 26, 12, 0, 0), SETTINGS)["today"]
    ctx = make_ctx(quest_daily={"key": yesterday, "completed": 3, "accepted": 2, "decay": {}})
    st = quest_daily_state(ctx)
    assert st["today"] == TODAY
    assert st["completed"] == 0 and st["accepted"] == 0
    assert ctx["quest_daily"]["key"] == TODAY
    # 同天幂等：再次查询不清零
    st2 = quest_daily_state(ctx)
    assert st2["completed"] == 0


def test_daily_no_reset_same_day():
    ctx = make_ctx(quest_daily={"key": TODAY, "completed": 2, "accepted": 1, "decay": {}})
    st = quest_daily_state(ctx)
    assert st["completed"] == 2 and st["accepted"] == 1


def test_daily_first_use_initializes():
    ctx = make_ctx(quest_daily=None)
    st = quest_daily_state(ctx)
    assert st["today"] == TODAY and st["completed"] == 0
    assert ctx["quest_daily"]["key"] == TODAY


def test_daily_reset_explicit_alias():
    ctx = make_ctx(quest_daily={"key": TODAY, "completed": 4, "accepted": 1, "decay": {}})
    out = quest_daily_reset(ctx)
    assert out["ok"] is True and out["completed"] == 4  # 同天不重置


# ===========================================================================
# ⑦ 放弃（quest_abandon）
# ===========================================================================

def test_abandon_removes_active_tc27():
    """TC-27：/放弃 N 从 quest_active 移除；默认无惩罚。"""
    ctx = make_ctx()
    add_quests(ctx, make_quest("q1", conditions=[]))
    assert quest_accept("q1", ctx)["ok"] is True
    out = quest_abandon("q1", ctx)
    assert out["ok"] is True
    assert "q1" not in ctx["quest_active"]
    assert out["penalty"] is None


def test_abandon_not_active():
    ctx = make_ctx()
    add_quests(ctx, make_quest("q1", conditions=[]))
    out = quest_abandon("q1", ctx)
    assert out["ok"] is False and out["reason"] == "not_active"


# ===========================================================================
# ⑧ 防刷限额配置层（settings 全局覆盖）
# ===========================================================================

def test_limits_settings_override():
    ctx = make_ctx(settings={"refresh_time": "05:00", "quest_accept_limit": 2,
                             "quest_daily_limit": 3})
    add_quests(ctx,
               make_quest("q1", conditions=[]),
               make_quest("q2", conditions=[]),
               make_quest("q3", conditions=[]),
               )
    assert quest_accept("q1", ctx)["ok"] is True
    assert quest_accept("q2", ctx)["ok"] is True
    out = quest_accept("q3", ctx)
    assert out["ok"] is False and out["reason"] == "accept_limit"
    # 每日完成上限 3
    for i, qid in enumerate(("q1", "q2")):
        assert quest_complete(qid, ctx)["ok"] is True
    ctx["quest_active"]["q3"] = {"name": "任务q3"}  # 手工放行（绕过接取闸，聚焦 daily_limit）
    out3 = quest_complete("q3", ctx)
    assert out3["ok"] is True
    ctx["quest_active"]["q1"] = {"name": "任务q1"}  # 第 4 个完成 → 拒绝
    out4 = quest_complete("q1", ctx)
    assert out4["ok"] is False and out4["reason"] == "daily_limit"


def test_defaults_constants():
    assert DEFAULT_ACCEPT_LIMIT == 5 and DEFAULT_DAILY_LIMIT == 10
    assert DEFAULT_BOARD["slot"] == "daily"
    assert DEFAULT_BOARD["accept_limit"] == 5
    assert DEFAULT_BOARD["daily_limit"] == 10
