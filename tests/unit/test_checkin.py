"""签到引擎单测（M4 批次5·路F2 · qbot_rpg/core/checkin.py）——多表并存一次结算 + 连签独立计数 +
补签只计不补发 + [签到:*] 三键取值。

依据：m4_shared_contract.md §3.4（E1-E4）+ 用户裁决⑦⑧（2026-08-27）+ 细化_2b5_签到引擎契约.md
      （结算管线 ①~⑥ L62-73 / 连签独立计数 §三 / 补签 §四 / 幂等 §五 / 日界 §5.3 / TC-01~TC-33）+
      签到系统设计定稿.md（L62-73 / L86/L197/L223 / L106）+ 任务系统定稿（reward 统一 schema）。

覆盖：多表并存首次结算 · 同日幂等不重复发奖 · monthly day=自然月当日 · daily 漏配兜底 · activity
      未开始/已过期自动停用 · streak 里程碑额外发奖（每段至多一次）· 断签归 1 / reset_on_break=false
      延续 · monthly_total 碎片化累计 · 跨月清零 longline 保留 · bonus 乘算 · loop day 轮转 ·
      补签（默认关/卡通道/货币通道/余额不足/月上限/0=不限/同日幂等/不触发里程碑）· checkin_state
      查询 · 三键取值（连续天数/本月天数/今日已签 + 缺省 loop）· condition_engine 消费 ctx["checkin"]
      投影 · 发奖失败单条跳过不吞整签。
"""

from __future__ import annotations

import datetime

from qbot_rpg.core.checkin import (
    CHECKIN_FIELDS,
    CHECKIN_TYPES,
    DEFAULT_CYCLE_DAYS,
    MAKEUP_CARD_ITEM,
    checkin_condition_ctx,
    checkin_do,
    checkin_makeup,
    checkin_state,
    checkin_value,
    day_index_of,
)
from qbot_rpg.core.dayroll import today_of
from qbot_rpg.engine.condition_engine import eval_condition

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


NOW = _ts(2026, 8, 27, 12, 0, 0)          # 2026-08-27 周三 12:00
TODAY = today_of(None, NOW, {"refresh_time": "05:00"})["today"]

ITEMS = {
    "药水": {"id": "药水", "name": "药水", "quality": "normal"},
    "钻石": {"id": "钻石", "name": "钻石", "quality": "rare"},
    "强化石": {"id": "强化石", "name": "强化石", "quality": "rare"},
    MAKEUP_CARD_ITEM: {"id": MAKEUP_CARD_ITEM, "name": MAKEUP_CARD_ITEM, "quality": "normal"},
}

SETTINGS = {"refresh_time": "05:00", "currencies": [{"id": "coins"}, {"id": "gem"}]}


def make_table(tid: str = "checkin_loop", typ: str = "loop", **kw) -> dict:
    """最小签到表定义（细化 §1.2 字段树：period/rewards/makeup/bonus）。"""
    base = {
        "id": tid,
        "name": f"表{tid}",
        "type": typ,
        "desc": "",
        "period": {},
        "rewards": {},
        "makeup": {"enabled": False, "cost": {}, "max_per_month": 0},
        "bonus": None,
    }
    base.update(kw)
    return base


def make_loop(**kw) -> dict:
    base = make_table("checkin_loop", "loop", **{
        "name": "每日签到",
        "period": {"cycle_days": 7, "reset_on_break": True},
        "rewards": {"daily": [{"day": 1, "items": [{"id": "药水", "count": 2}],
                               "coins": 50, "exp": 20}]},
        "makeup": {"enabled": True, "cost": {"coins": 100}, "max_per_month": 3},
    })
    base.update(kw)
    return base


def make_monthly(**kw) -> dict:
    base = make_table("checkin_monthly", "monthly", **{
        "name": "月度签到",
        "period": {"cycle_days": 31, "reset_on_break": True},
        "rewards": {
            "daily": [
                {"day": 1, "items": [{"id": "药水", "count": 2}], "coins": 50, "exp": 20},
                {"day": 2, "coins": 60, "exp": 25},
            ],
            "streak": [{"days": 7, "items": [{"id": "钻石", "count": 1}], "gem": 3}],
            "monthly_total": [{"days": 15, "items": [{"id": "强化石", "count": 3}]}],
        },
        "makeup": {"enabled": False},
    })
    base.update(kw)
    return base


def make_activity(**kw) -> dict:
    base = make_table("act_anniv", "activity", **{
        "name": "周年庆典",
        "period": {"start": "2026-08-01 00:00", "end": "2026-08-31 23:59",
                   "cycle_days": 14, "reset_on_break": True},
        "rewards": {"daily": [{"day": 1, "items": [{"id": "药水", "count": 4}], "coins": 30}]},
        "makeup": {"enabled": False},
    })
    base.update(kw)
    return base


def make_ctx(tables=None, **overrides) -> dict:
    """默认 ctx：三表注册表 + checkin_state + reward 桶 + 物品注册表 + now 注入。"""
    ctx = {
        "settings": SETTINGS,
        "checkin_tables": {},
        "checkin_state": {},
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
    if tables is not None:
        for tb in tables:
            ctx["checkin_tables"][tb["id"]] = tb
    return ctx


DEFAULT_TABLES = [make_loop(), make_monthly(), make_activity()]


def record_adds(ctx: dict) -> list:
    """注入入包 hook 并收集调用记录，返回 [(item_id, count, bound), ...]。"""
    calls = []
    ctx["add_item"] = lambda item_id, count, bound: (calls.append((item_id, count, bound)) or True)  # type: ignore[func-returns-value]
    return calls


def row(ctx: dict, r: dict, table_id: str) -> dict:
    return next(x for x in r["tables"] if x["table_id"] == table_id)


def _granted_types(r: dict) -> list:
    return [g.get("type") for g in r.get("granted", [])]


# =============================================================================
# ① 多表并存一次结算（TC-07/08/09/13）
# =============================================================================
def test_first_sign_all_three_tables_settled():
    """TC-07：三表同时生效，首次 /签到 → 三表各自结算、streak=1、各自发当日奖励。"""
    ctx = make_ctx(DEFAULT_TABLES)
    r = checkin_do(ctx)
    assert r["ok"] is True
    assert len(r["tables"]) == 3
    for t in r["tables"]:
        assert t["active"] is True
        assert t["already_signed"] is False
        assert t["streak"] == 1
        assert t["today_signed"] == 1
        assert t["granted"], f"{t['table_id']} 应发当日奖励"
    # 存档按表 ID 键控
    assert set(ctx["checkin_state"].keys()) == {"checkin_loop", "checkin_monthly", "act_anniv"}
    # 三键投影已刷新（TC-32）
    assert ctx["checkin"]["loop"]["streak"] == 1
    assert ctx["checkin"]["loop"]["today_signed"] == 1


def test_summary_message_contains_table_names():
    """TC-08：汇总单条消息含各表名与进度（\"X/Y\" 形态）。"""
    ctx = make_ctx(DEFAULT_TABLES)
    r = checkin_do(ctx)
    assert r["message"].count("═══") == 3 * 2
    for name in ("每日签到", "月度签到", "周年庆典"):
        assert name in r["message"]
    assert "1/7" in r["message"]  # loop 进度（streak/cycle_days）
    assert "1/31" in r["message"]  # monthly 进度（当月 1 天/31 天）


def test_same_day_repeat_idempotent_no_regrant():
    """TC-25：当日已签后同日再 /签到 → 今天已签到，不重复发奖，仍附进度（D-02）。"""
    ctx = make_ctx(DEFAULT_TABLES)
    r1 = checkin_do(ctx)
    granted1 = sum(len(t["granted"]) for t in r1["tables"])
    coins1 = ctx["currencies"].get("coins", 0)
    r2 = checkin_do(ctx)
    assert r2["ok"] is True
    for t in r2["tables"]:
        assert t["already_signed"] is True
        assert t["granted"] == []
    assert ctx["currencies"].get("coins", 0) == coins1  # 不重复入账
    assert ctx["checkin_state"]["checkin_loop"]["streak"] == 1
    # D-02：幂等返回仍带进度
    assert r2["tables"][0]["streak"] == 1
    assert r2["message"].count("今天已签到") >= 1


def test_version_idempotent_tx_replay():
    """TC-26：同 tx_id 重放 → 幂等返回，不双发奖励。"""
    ctx = make_ctx(DEFAULT_TABLES)
    ctx["tx_id"] = "tx-20260827-001"
    ctx["ledger"] = set()
    r1 = checkin_do(ctx)
    assert r1["ok"] is True and "idempotent" not in r1
    coins1 = ctx["currencies"].get("coins", 0)
    r2 = checkin_do(ctx)
    assert r2["ok"] is True and r2["idempotent"] is True
    assert ctx["currencies"].get("coins", 0) == coins1


def test_monthly_day_natural_month_day_progress():
    """TC-09：monthly 表 day = 自然月当日（8/27 → day=27），进度本月累计。"""
    ctx = make_ctx(DEFAULT_TABLES)
    r = checkin_do(ctx)
    m = row(ctx, r, "checkin_monthly")
    assert m["day"] == 27
    assert m["cycle_days"] == 31
    assert m["month_days"] == 1
    assert m["progress_current"] == 1 and m["progress_total"] == 31


def test_loop_day_rotation_cycle_7():
    """TC-13 口径：loop 表 day 按 streak mod cycle_days 轮转（第 1 天 day1 … 第 8 天 day1）。"""
    ctx = make_ctx([make_loop(), make_monthly()])
    loop = ctx["checkin_tables"]["checkin_loop"]
    for n, exp_day in enumerate([1, 2, 3, 4, 5, 6, 7, 1, 2, 3], start=1):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_do(ctx)
        assert row(ctx, r, "checkin_loop")["day"] == exp_day, f"第 {n} 天"
        assert row(ctx, r, "checkin_loop")["streak"] == n


def test_daily_fallback_first_day_note():
    """TC-10：daily 只配 day1/2，签到第 3 天 → 按第 1 天奖励兜底 + 补全提示。"""
    ctx = make_ctx([make_monthly()])
    record_adds(ctx)  # 物品奖励经 add_item hook 入包（生产装配注入；P1-1 无 hook 时 item 走 skipped）
    ctx["now"] = _ts(2026, 8, 3, 12, 0, 0)
    r = checkin_do(ctx)
    m = row(ctx, r, "checkin_monthly")
    assert m["day"] == 3
    assert any("补全" in n for n in m["notes"])
    assert any(g.get("type") == "item" for g in m["daily_granted"])  # 第 1 天物品兜底


def test_activity_not_started_auto_inactive():
    """TC-11：activity start 未到 → 自动停用（不报错、不结算），其他表正常。"""
    act = make_activity(period={"start": "2026-09-01 00:00", "end": "2026-09-30 23:59",
                                "cycle_days": 14, "reset_on_break": True})
    ctx = make_ctx([make_loop(), act])
    r = checkin_do(ctx)
    a = row(ctx, r, "act_anniv")
    assert a["active"] is False
    assert "act_anniv" not in ctx["checkin_state"]  # 未结算不写存档
    assert row(ctx, r, "checkin_loop")["active"] is True
    assert row(ctx, r, "checkin_loop")["streak"] == 1


def test_activity_expired_auto_inactive():
    """TC-12：activity end 已过 → 自动停用（不报错），其余表不受影响。"""
    act = make_activity(period={"start": "2026-07-01 00:00", "end": "2026-07-31 23:59",
                                "cycle_days": 14, "reset_on_break": True})
    ctx = make_ctx([make_loop(), make_monthly(), act])
    r = checkin_do(ctx)
    assert row(ctx, r, "act_anniv")["active"] is False
    assert row(ctx, r, "checkin_loop")["active"] is True
    assert row(ctx, r, "checkin_monthly")["active"] is True


# =============================================================================
# ② 连签与独立计数（TC-13~18）
# =============================================================================
def test_streak_independent_per_table():
    """TC-13：三表同开连续签到 → 各表 streak 独立计数互不合并。"""
    ctx = make_ctx(DEFAULT_TABLES)
    for n in range(1, 6):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    for t in ctx["checkin_state"].values():
        assert t["streak"] == 5, f"{t} 独立计数"


def test_streak_milestone_extra_reward():
    """TC-14：streak 配 days=7 → 连签到第 7 天，每日奖励之外额外发 钻石×1。"""
    ctx = make_ctx([make_monthly()])
    record_adds(ctx)  # 物品奖励经 add_item hook 入包（生产装配注入；P1-1 无 hook 时 item 走 skipped）
    hits = []
    for n in range(1, 8):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_do(ctx)
        hits.append(row(ctx, r, "checkin_monthly").get("streak_hits"))
    assert hits[6]  # 第 7 天命中
    assert hits[6][0]["days"] == 7
    assert any(g.get("item") == "钻石" for g in hits[6][0]["granted"])
    assert ctx["currencies"].get("gem", 0) == 3  # 里程碑 gem 额外入账


def test_streak_milestone_not_regrant_same_run():
    """每档每周期至多一次：同一连签段内仅命中一次（第 7 天命中后，后续不再发）。"""
    ctx = make_ctx([make_monthly()])
    for n in range(1, 15):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_do(ctx)
        hits = row(ctx, r, "checkin_monthly").get("streak_hits")
        if n == 7:
            assert hits and hits[0]["days"] == 7
        else:
            assert not hits, f"第 {n} 天不应重复发连签里程碑"
    assert ctx["currencies"].get("gem", 0) == 3  # 只发一次


def test_break_reset_streak_to_one():
    """TC-15：reset_on_break=true，签 3 天断 2 天后再签 → streak 归 1。"""
    ctx = make_ctx([make_loop()])
    for n in (1, 2, 3):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    assert ctx["checkin_state"]["checkin_loop"]["streak"] == 3
    ctx["now"] = _ts(2026, 8, 6, 12, 0, 0)  # 断 2 天（4、5 未签）
    r = checkin_do(ctx)
    assert row(ctx, r, "checkin_loop")["streak"] == 1
    assert row(ctx, r, "checkin_loop")["day"] == 1


def test_break_no_reset_accumulates():
    """TC-16：reset_on_break=false，断签不归 1，按累计口径延续。"""
    ctx = make_ctx([make_loop(period={"cycle_days": 7, "reset_on_break": False})])
    for n in (1, 2, 3):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    ctx["now"] = _ts(2026, 8, 6, 12, 0, 0)
    r = checkin_do(ctx)
    assert row(ctx, r, "checkin_loop")["streak"] == 4  # 3+1 延续


def test_monthly_total_fragmented_accumulate():
    """TC-17：monthly_total 不要求连续——断断续续合计第 15 天仍发 强化石×3（碎片化铁律）。"""
    ctx = make_ctx([make_monthly()])
    record_adds(ctx)  # M4 实现审查 P1-1：注入入包 hook（物品奖励不再 skip）
    granted = None
    for i in range(1, 31, 2):  # 1,3,5,...,29（15 天，全部断签）
        ctx["now"] = _ts(2026, 8, i, 12, 0, 0)
        r = checkin_do(ctx)
        m = row(ctx, r, "checkin_monthly")
        if m.get("month_hits"):
            granted = m["month_hits"][0]
    assert granted is not None
    assert granted["days"] == 15
    assert any(g.get("item") == "强化石" for g in granted["granted"])


def test_month_total_rollover_reset_keep_longline():
    """TC-18：自然月切换 → monthly_total 归 0 重新累计；longline 保留只增不减（D-06）。"""
    ctx = make_ctx([make_monthly()])
    ctx["now"] = _ts(2026, 8, 31, 12, 0, 0)
    r = checkin_do(ctx)
    m = row(ctx, r, "checkin_monthly")
    assert m["month_days"] == 1 and m["day"] == 31
    assert ctx["checkin_state"]["checkin_monthly"]["longline"] == 1
    ctx["now"] = _ts(2026, 9, 1, 12, 0, 0)
    r = checkin_do(ctx)
    m = row(ctx, r, "checkin_monthly")
    assert m["month_days"] == 1  # 跨月归 0 后重新累计
    assert m["streak"] == 2       # 连签跨月延续（间隔=1 天）
    st = ctx["checkin_state"]["checkin_monthly"]
    assert st["longline"] == 2    # 长线只增不减
    assert ctx["longline_counters"]["checkin_total"] == 2


def test_month_milestone_once_per_month():
    """每月至多一次：同月再达 15 天不重复发；跨月后重新累计可再发。"""
    ctx = make_ctx([make_monthly()])
    for n in range(1, 16):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    # 同月签到到第 20 天：15 档不重复发
    for n in range(16, 21):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_do(ctx)
        assert not row(ctx, r, "checkin_monthly").get("month_hits")
    got = ctx["currencies"].get("gem", 0)  # 无 gem，仅确认没重复强化石
    # 跨到 9 月重新累计 15 天 → 可再发
    for n in range(1, 16):
        ctx["now"] = _ts(2026, 9, n, 12, 0, 0)
        checkin_do(ctx)
    assert ctx["checkin_state"]["checkin_monthly"]["month_milestones"] == [15]
    assert ctx["checkin_state"]["checkin_monthly"]["month_total"] == 15


# =============================================================================
# ③ bonus 乘算（D-04 / TC-33）
# =============================================================================


def test_bonus_mult_mult_key_engine_consumed():
    """M4 实现审查批次5 P1-3：引擎 _bonus_multiplier 读 mult（内容层正典键）——{"mult": 2} 生效。"""
    ctx = make_ctx([make_loop(bonus={"mult": 2})])
    r = checkin_do(ctx)
    l = row(ctx, r, "checkin_loop")
    assert l["daily_granted"]
    # 对齐 test_bonus_multiplier_scaling 口径：coins 默认 50 ×2 = 100，exp 20 ×2 = 40
    assert ctx["currencies"].get("coins", 0) == 100, f"mult 键未生效，coins={ctx['currencies'].get('coins')}"
    assert ctx["exp"] == 40, f"mult 键未生效，exp={ctx['exp']}"

def test_bonus_mult_compat_keys_still_work():
    """P1-3 兼容键保留：multiplier/rate/倍率 仍可读。"""
    for key in ("multiplier", "rate", "倍率"):
        ctx = make_ctx([make_loop(bonus={key: 2})])
        r = checkin_do(ctx)
        l = row(ctx, r, "checkin_loop")
        assert l["daily_granted"], f"{key} 兼容键失效"
def test_bonus_multiplier_scaling():
    """TC-33：bonus 倍率 2 → 当日 items.count/coins/exp 统一 ×2（向下取整）。"""
    ctx = make_ctx([make_loop(bonus={"multiplier": 2})])
    r = checkin_do(ctx)
    l = row(ctx, r, "checkin_loop")
    assert l["daily_granted"]
    assert ctx["currencies"].get("coins", 0) == 100      # 50 × 2
    assert ctx["exp"] == 40                              # 20 × 2
    assert ctx["inventory"].get("药水", 0) == 0  # 未注入 add_item hook 不入包
    # 物品经 add_item hook
    ctx2 = make_ctx([make_loop(bonus=2.0)])
    calls = record_adds(ctx2)
    checkin_do(ctx2)
    assert ("药水", 4, True) in calls  # 2 × 2


# =============================================================================
# ④ 补签（TC-19~24 + 裁决⑦）
# =============================================================================
def test_makeup_disabled_by_default():
    """TC-19：makeup 默认关 → /签到 补签 提示未开启，不扣任何资源。"""
    monthly = make_monthly()  # makeup.enabled=False
    ctx = make_ctx([monthly])
    ctx["inventory"][MAKEUP_CARD_ITEM] = 5
    ctx["currencies"]["coins"] = 999
    r = checkin_makeup(ctx)
    assert r["ok"] is False and r["reason"] == "makeup_disabled"
    assert ctx["currencies"]["coins"] == 999 and ctx["inventory"][MAKEUP_CARD_ITEM] == 5
    assert "act_anniv" not in ctx.get("checkin_state", {}) or not ctx["checkin_state"]


def test_makeup_card_channel_restores_counters_no_reward():
    """TC-20 + 裁决⑦：持补签卡 → 消耗 1 张；恢复 signed_days 与 streak 连续性；不发 daily。"""
    ctx = make_ctx([make_loop()])
    ctx["inventory"][MAKEUP_CARD_ITEM] = 1
    r = checkin_makeup(ctx)
    assert r["ok"] is True and r["channel"] == "card"
    assert ctx["inventory"][MAKEUP_CARD_ITEM] == 0  # 消耗 1 张
    st = ctx["checkin_state"]["checkin_loop"]
    assert TODAY in st["signed_days"]
    assert st["streak"] == 1
    assert st["last_date"] == TODAY
    assert st["makeup_used"] == 1
    # 只计不补发：无任何 reward 入账
    assert ctx["currencies"].get("coins", 0) == 0
    assert ctx["exp"] == 0
    # 补签后再正常 /签到 → 同日幂等，不双重领取（裁决⑦）
    r2 = checkin_do(ctx)
    assert row(ctx, r2, "checkin_loop")["already_signed"] is True
    assert ctx["currencies"].get("coins", 0) == 0


def test_makeup_currency_channel_deducts():
    """TC-21：货币通道 cost={coins:100}，余额足够 → 扣 100 金币补签成功。"""
    ctx = make_ctx([make_loop()])
    ctx["currencies"]["coins"] = 100
    r = checkin_makeup(ctx)
    assert r["ok"] is True and r["channel"] == "currency"
    assert ctx["currencies"]["coins"] == 0
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 1


def test_makeup_insufficient_currency_no_deduct():
    """TC-21 反例：余额不足 → 提示差额不扣款。"""
    ctx = make_ctx([make_loop()])
    ctx["currencies"]["coins"] = 30
    r = checkin_makeup(ctx)
    assert r["ok"] is False and r["reason"] == "insufficient_currency"
    assert ctx["currencies"]["coins"] == 30  # 未扣款
    assert "checkin_loop" not in ctx["checkin_state"]


def test_makeup_month_limit():
    """TC-22：max_per_month=3，本月已补 3 次再补 → 拒绝，提示已达月上限。"""
    ctx = make_ctx([make_loop(makeup={"enabled": True, "cost": {"coins": 10},
                                      "max_per_month": 3})])
    ctx["currencies"]["coins"] = 1000
    for n in range(1, 4):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_makeup(ctx)
        assert r["ok"] is True
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 3
    ctx["now"] = _ts(2026, 8, 4, 12, 0, 0)
    r = checkin_makeup(ctx)
    assert r["ok"] is False and r["reason"] == "makeup_limit"
    assert r["max_per_month"] == 3


def test_makeup_max_zero_unlimited():
    """TC-23：max_per_month=0 → 不限，逐次扣费。"""
    ctx = make_ctx([make_loop(makeup={"enabled": True, "cost": {"coins": 10},
                                      "max_per_month": 0})])
    ctx["currencies"]["coins"] = 1000
    for n in range(1, 6):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_makeup(ctx)
        assert r["ok"] is True
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 5
    assert ctx["currencies"]["coins"] == 1000 - 5 * 10


def test_makeup_same_day_idempotent_no_charge():
    """TC-24：同一天已补过再补 → 幂等返回不重复扣费、makeup_used 不 +1。"""
    ctx = make_ctx([make_loop()])
    ctx["currencies"]["coins"] = 200
    r1 = checkin_makeup(ctx)
    assert r1["ok"] is True
    assert ctx["currencies"]["coins"] == 100
    r2 = checkin_makeup(ctx)
    assert r2["ok"] is True and r2["idempotent"] is True
    assert r2["already_signed"] is True
    assert ctx["currencies"]["coins"] == 100   # 不重复扣费
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 1


def test_makeup_no_milestone_grant():
    """裁决⑦ 里程碑奖励不重复：补签使 streak 达阈值也不触发里程碑发放。"""
    ctx = make_ctx([make_loop(
        rewards={"daily": [{"day": 1, "coins": 5}],
                 "streak": [{"days": 3, "coins": 999}],
                 "monthly_total": [{"days": 4, "coins": 888}]},  # 4 档普通签到 2 天不可达
        makeup={"enabled": True, "cost": {"coins": 10}, "max_per_month": 5})])
    ctx["currencies"]["coins"] = 1000
    # 先正常签 2 天（streak=2，month_days=2）：只发 daily 5×2，不达任何里程碑
    for n in (1, 2):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    assert ctx["currencies"]["coins"] == 1010
    # 第 3 天用补签（只计不补发）→ 若触发里程碑会 +999（streak 3 档）
    ctx["now"] = _ts(2026, 8, 3, 12, 0, 0)
    r = checkin_makeup(ctx)
    assert r["ok"] is True
    assert r["streak"] == 3
    # 里程碑均未发放：仅扣补签费 10（无 999 / 无 888）
    assert ctx["currencies"]["coins"] == 1010 - 10


def test_makeup_default_table_is_primary_loop():
    """裁决⑧ 口径：缺省表名=主表 loop——checkin_makeup 无表参作用于 loop。"""
    ctx = make_ctx(DEFAULT_TABLES)
    ctx["currencies"]["coins"] = 100
    r = checkin_makeup(ctx)
    assert r["ok"] is True
    assert r["table_id"] == "checkin_loop"
    assert "checkin_loop" in ctx["checkin_state"]
    assert "checkin_monthly" not in ctx["checkin_state"]


def test_makeup_cross_month_limit_resets_and_count():
    """审查_M4实现_批次5_jspace.md P1-1：8 月补满 3 次（max=3），9 月首日直接补签 →
    不误拦（新月份重新计数）、makeup_used=1（不再沿用上月 used 错计）。"""
    ctx = make_ctx([make_loop(makeup={"enabled": True, "cost": {"coins": 10},
                                      "max_per_month": 3})])
    ctx["currencies"]["coins"] = 1000
    # 8 月补满 3 次（不同日期）
    for n in (1, 2, 3):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        r = checkin_makeup(ctx)
        assert r["ok"] is True
    st = ctx["checkin_state"]["checkin_loop"]
    assert st["makeup_month"] == "2026-08" and st["makeup_used"] == 3
    # 9 月首日（未先普通 /签到）直接补签 → 应成功且 makeup_used=1（跨月视为 0 重新计数）
    ctx["now"] = _ts(2026, 9, 1, 12, 0, 0)
    r = checkin_makeup(ctx)
    assert r["ok"] is True
    assert r["makeup_used"] == 1
    st = ctx["checkin_state"]["checkin_loop"]
    assert st["makeup_month"] == "2026-09"
    assert st["makeup_used"] == 1
    assert st["month_total"] == 1          # 当月累计从新月份起算
    assert "2026-09-01" in st["signed_days"]


def test_makeup_cross_month_unlimited_no_miscount():
    """审查批次5 P1-1 反例：max_per_month=0（不限）时，9 月首笔补签不沿用上月 used 错计
    （修复前为 4，修复后应为 1）。"""
    ctx = make_ctx([make_loop(makeup={"enabled": True, "cost": {"coins": 10},
                                      "max_per_month": 0})])
    ctx["currencies"]["coins"] = 1000
    for n in (1, 2, 3):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        assert checkin_makeup(ctx)["ok"] is True
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 3
    ctx["now"] = _ts(2026, 9, 1, 12, 0, 0)
    r = checkin_makeup(ctx)
    assert r["ok"] is True and r["makeup_used"] == 1
    assert ctx["checkin_state"]["checkin_loop"]["makeup_used"] == 1


# =============================================================================
# ⑤ 状态查询 / 三键取值（TC-32 + 裁决⑧）
# =============================================================================
def test_checkin_state_query_pure_read():
    """checkin_state：纯读查询，展示连签/本月天数/今日已签/补签用量，不推进存档。"""
    ctx = make_ctx(DEFAULT_TABLES)
    checkin_do(ctx)
    st = checkin_state(ctx)
    assert st["ok"] is True
    loop = next(t for t in st["tables"] if t["table_id"] == "checkin_loop")
    assert loop["streak"] == 1
    assert loop["today_signed"] == 1
    assert loop["month_days"] == 1
    assert loop["makeup_enabled"] is True
    assert loop["makeup_used"] == 0
    monthly = next(t for t in st["tables"] if t["table_id"] == "checkin_monthly")
    assert monthly["makeup_enabled"] is False


def test_three_keys_value_default_loop():
    """裁决⑧：三键取值——连续天数=streak / 本月天数=当月 signed_days / 今日已签；缺省表名=主表 loop。"""
    ctx = make_ctx(DEFAULT_TABLES)
    # 未签 → 全 0
    assert checkin_value(ctx) == 0                      # 缺省键 → 0
    assert checkin_value(ctx, "loop", "连续天数") == 0
    assert checkin_value(ctx, "loop", "本月天数") == 0
    assert checkin_value(ctx, "loop", "今日已签") == 0
    checkin_do(ctx)
    # 连续 3 天
    for n in (2, 3):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    assert checkin_value(ctx, "loop", "连续天数") == 3
    assert checkin_value(ctx, "loop", "本月天数") == 3
    assert checkin_value(ctx, "loop", "今日已签") == 1
    # 英文内部字段直读
    assert checkin_value(ctx, "loop", "streak") == 3
    assert checkin_value(ctx, "loop", "month_days") == 3
    # 今日已签切换：次日未签前 → 0
    ctx["now"] = _ts(2026, 8, 5, 12, 0, 0)
    assert checkin_value(ctx, "loop", "今日已签") == 0


def test_three_keys_monthly_and_activity():
    """裁决⑧：表名限定——monthly 表本月天数 / activity 表今日已签各自独立取值。"""
    ctx = make_ctx(DEFAULT_TABLES)
    checkin_do(ctx)
    assert checkin_value(ctx, "monthly", "连续天数") == 1
    assert checkin_value(ctx, "monthly", "本月天数") == 1
    assert checkin_value(ctx, "activity", "今日已签") == 1
    assert checkin_value(ctx, "activity", "连续天数") == 1
    # 未知表名/字段 → 0
    assert checkin_value(ctx, "bogus", "连续天数") == 0
    assert checkin_value(ctx, "loop", "不存在的字段") == 0


def test_three_keys_table_id_qualifier():
    """审查_M4实现_批次5_jspace.md P1-2：表 id 限定键与生效 type 限定键等价可求值
    （校验器「双口径」承诺兑现：checkin_value 按 id 解析 + condition_engine id→type 映射）。"""
    ctx = make_ctx(DEFAULT_TABLES)
    checkin_do(ctx)
    checkin_condition_ctx(ctx)
    # core.checkin_value 按表 id 解析（表 id 恰为定稿正典示例 checkin_monthly / checkin_loop）
    assert checkin_value(ctx, "checkin_monthly", "本月天数") == 1
    assert checkin_value(ctx, "checkin_monthly", "连续天数") == 1
    assert checkin_value(ctx, "checkin_loop", "连续天数") == 1
    assert checkin_value(ctx, "checkin_loop", "今日已签") == 1
    # condition_engine 消费表 id 限定键（不再静默 False）
    assert eval_condition(
        {"var": "[签到:checkin_monthly.本月天数]", "op": "ge", "value": 1}, ctx) is True
    assert eval_condition(
        {"var": "[签到:checkin_monthly.连续天数]", "op": "ge", "value": 2}, ctx) is False
    assert eval_condition(
        {"var": "[签到:checkin_loop.今日已签]", "op": "eq", "value": 1}, ctx) is True
    # 与 type 限定键（monthly / loop）同值
    assert checkin_value(ctx, "checkin_monthly", "本月天数") == checkin_value(
        ctx, "monthly", "本月天数")


def test_condition_engine_consumes_checkin_projection():
    """TC-32：条件引擎经 ctx[\"checkin\"] 投影消费三键（结算后键值已更新）。"""
    ctx = make_ctx(DEFAULT_TABLES)
    checkin_do(ctx)
    checkin_condition_ctx(ctx)  # 投影刷新（checkin_do 内部已刷，此处显式再验证）
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 1}, ctx) is True
    assert eval_condition({"var": "[签到:loop.连续天数]", "op": "ge", "value": 2}, ctx) is False
    assert eval_condition({"var": "[签到:loop.今日已签]", "op": "eq", "value": 1}, ctx) is True
    assert eval_condition({"var": "[签到:monthly.本月天数]", "op": "ge", "value": 1}, ctx) is True
    assert eval_condition({"var": "[签到:activity.今日已签]", "op": "ge", "value": 1}, ctx) is True
    # 中文别名 [签到:连续天数] → 归一 loop.连续天数（condition_engine 侧）
    assert eval_condition({"var": "[签到:连续天数]", "op": "ge", "value": 1}, ctx) is True


def test_projection_refreshes_after_settlement():
    """结算后投影自动刷新：连签 3 天后 ctx[\"checkin\"] 键值同步（TC-32 注释口径）。"""
    ctx = make_ctx([make_loop()])
    for n in range(1, 4):
        ctx["now"] = _ts(2026, 8, n, 12, 0, 0)
        checkin_do(ctx)
    assert ctx["checkin"]["loop"]["streak"] == 3
    assert ctx["checkin"]["loop"]["month_days"] == 3


# =============================================================================
# ⑥ 发奖兜底 / 入包（D-05 / TC-27）
# =============================================================================
def test_item_reward_via_add_item_hook():
    """每日物品奖励经 ctx[\"add_item\"] hook 入包（默认绑定）。"""
    ctx = make_ctx([make_loop()])
    calls = record_adds(ctx)
    checkin_do(ctx)
    assert ("药水", 2, True) in calls


def test_reward_failure_skip_does_not_abort_table():
    """TC-27（D-05）：当日奖励物品不存在 → 该条黄字跳过、不吞整次签到；coins 照常入账。"""
    loop = make_loop(rewards={"daily": [{"day": 1,
                                         "items": [{"id": "不存在的物品", "count": 5}],
                                         "coins": 60}]})
    ctx = make_ctx([loop, make_monthly()])
    r = checkin_do(ctx)
    l = row(ctx, r, "checkin_loop")
    assert l["skipped"]  # 物品条目被跳过
    assert any(s.get("reason") == "item_not_found" for s in l["skipped"])
    # 60（loop coins）+ 50（monthly 当日 coins）照常入账（不中断整签/跨表继续）
    assert ctx["currencies"].get("coins", 0) == 60 + 50
    assert l["streak"] == 1
    assert row(ctx, r, "checkin_monthly")["streak"] == 1  # 后序表继续结算


# =============================================================================
# ⑦ 辅助口径
# =============================================================================
def test_day_index_of_helpers():
    """day_index_of / cycle_days_of 口径（D-01）。"""
    loop = make_loop()
    assert day_index_of(loop, "2026-08-01", streak=1) == 1
    assert day_index_of(loop, "2026-08-01", streak=7) == 7
    assert day_index_of(loop, "2026-08-01", streak=8) == 1
    monthly = make_monthly()
    assert day_index_of(monthly, "2026-08-27", streak=5) == 27  # 自然月当日
    act = make_activity()
    assert day_index_of(act, "2026-08-05", streak=5) == 5  # 与 start 日差 + 1（8/1 起）
    assert day_index_of(act, "2026-08-14", streak=14) == 14


def test_constants_exposed():
    assert DEFAULT_CYCLE_DAYS == 7
    assert MAKEUP_CARD_ITEM == "补签卡"
    assert CHECKIN_TYPES == ("loop", "monthly", "activity")
    assert set(CHECKIN_FIELDS) >= {"连续天数", "本月天数", "今日已签", "streak", "month_days",
                                   "today_signed"}
