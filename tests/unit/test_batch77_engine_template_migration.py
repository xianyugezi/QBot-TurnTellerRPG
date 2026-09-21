"""批77 · X6 引擎/跨模块渲染文案迁表验收（`core/checkin.py` + `gm_commands._EMPTY_LOG`）。

依据：`docs/消息模板重构/02_遗留登记.md` §A #1/#2；`docs/矛盾与待裁决登记.md` §A X6。
纪律：零行为变化（渲染逐字符一致）+ 内容包可覆盖同键。

覆盖：
① 新迁表键存在且逐字等于迁表前引擎硬编码值（保真锚点）；
② 引擎侧渲染走 `tpl_of`（`ctx["templates"]` 覆盖即刻生效 → 内容包可覆盖）；
③ `checkin` 引擎 `message` 默认渲染与旧值逐字符一致（`checkin_do` / `checkin_makeup`）；
④ GM `/日志` 空页复用表键 `log_sys_empty`（`render_log_page` 可被 ctx 覆盖）。
"""

from __future__ import annotations

import datetime

import qbot_rpg.core.checkin as ck
from qbot_rpg.commands.gm_commands import render_log_page
from qbot_rpg.core.templates import DEFAULT_TEMPLATES

#: 批77 迁表键 → 迁表前 `core/checkin.py` 引擎硬编码字面量（逐字保真锚点）。
_LEGACY_ENGINE_TEXT = {
    "checkin_engine_invalid_ctx": "❌ 结算上下文非法",
    "checkin_engine_do_idempotent": "今天已签到（重复指令，未重复发放）",
    "checkin_makeup_idempotent": "已补签（重复指令，未重复扣费）",
    "checkin_no_config_table": "❌ 未配置签到表",
    "checkin_table_missing": "❌ 签到表不存在",
    "checkin_table_inactive": "❌ 该签到表当前未生效",
    "checkin_makeup_disabled": "❌ 当前未开启补签",
    "checkin_makeup_already": "今日已补过/已签到，无需重复补签",
    "checkin_makeup_limit": "❌ 本月补签已达上限 {max} 次",
    "checkin_makeup_insufficient": "❌ 货币不足，补签失败",
    "checkin_makeup_no_channel": "❌ 补签需要补签卡或货币，当前无可用通道",
    "checkin_makeup_rollback": "❌ 补签失败，已回滚",
    "checkin_makeup_ok": "✅ 补签成功（{channel}）· 只计不补发",
    "checkin_settle_failed": "❌ 该表结算失败，已回滚",
    "checkin_notes_day_fallback": "第 {day} 天未配置，已按第 1 天奖励补全",
    "checkin_summary_header": "签到汇总",
    "checkin_summary_section": "═══ {name}（{type}）═══",
    "checkin_summary_progress": "连签天数：{streak} 天 ｜ 进度 {cur}/{total}",
    "checkin_summary_fail": "结算失败，已回滚",
    "checkin_summary_daily_none": "今日奖励：无",
    "checkin_summary_streak_hit": "[连签里程碑达成] {grants}（连签 {days} 天）",
    "checkin_summary_month_hit": "[月度累计达成] {grants}（本月签满 {days} 天）",
}

_TZ = datetime.timezone(datetime.timedelta(hours=8))
NOW = int(datetime.datetime(2026, 8, 26, 12, 0, 0, tzinfo=_TZ).timestamp())
SETTINGS = {"refresh_time": "05:00", "currencies": [{"id": "coins", "name": "金币"}]}
TABLES = {
    "loop": {"id": "loop", "name": "常驻循环", "type": "loop",
             "period": {"cycle_days": 7, "reset_on_break": True},
             "rewards": {"daily": [{"day": 1, "coins": 50, "exp": 20}]},
             "makeup": {"enabled": True, "cost": {"coins": 100}, "max_per_month": 3}},
}


def _ctx(**over):
    base = {
        "name": "阿伟", "level": 5, "settings": SETTINGS,
        "checkin_tables": {k: dict(v) for k, v in TABLES.items()},
        "checkin_state": {}, "longline_counters": {}, "event_counts": {},
        "inventory": {}, "currencies": {"coins": 1000}, "exp": 0,
        "reputation_state": {}, "items": {},
        "add_item": lambda item_id, count, bound=True: True,
        "remove_item": lambda item_id, count: True,
        "count_item": lambda item_id: 0,
        "now": NOW, "checkin_engine": ck,
    }
    base.update(over)
    return base


def test_legacy_engine_text_frozen_in_table():
    """① 迁表键存在且逐字等于迁表前引擎硬编码值（保真锚点）。"""
    for key, text in _LEGACY_ENGINE_TEXT.items():
        assert DEFAULT_TEMPLATES.get(key) == text, f"{key} 迁表值漂移"


def test_engine_text_is_template_driven_and_overridable():
    """② 引擎渲染走 tpl_of：ctx["templates"] 覆盖同键即刻生效（内容包可覆盖）。"""
    override = {"checkin_makeup_disabled": "❌ 覆盖后的未开启补签"}
    ctx = _ctx(checkin_tables={}, templates=override)
    # 空表 → 引擎走 no_config_table（也受覆盖机制约束）；单独验证 tpl_of 路径：
    from qbot_rpg.core.templates import tpl_of

    assert tpl_of(ctx, "checkin_makeup_disabled") == "❌ 覆盖后的未开启补签"

    tables = {k: dict(v) for k, v in TABLES.items()}
    tables["loop"]["makeup"] = {"enabled": False}
    res = ck.checkin_makeup(_ctx(checkin_tables=tables, templates=override), "loop")
    assert res["message"] == "❌ 覆盖后的未开启补签"


def test_checkin_do_message_default_matches_legacy_text():
    """③ 引擎 message 默认渲染与旧值逐字符一致（零行为变化）。"""
    ctx = _ctx()
    res = ck.checkin_do(ctx)
    assert res["message"].startswith("签到汇总\n")
    assert "今日奖励：金币×50、经验×20" in res["message"]
    assert "连签天数：1 天 ｜ 进度 1/7" in res["message"]
    # 幂等第二跑
    res2 = ck.checkin_do(ctx)
    assert res2["message"] == (
        "签到汇总\n"
        "═══ 常驻循环（常驻循环）═══\n"
        "今天已签到（不重复发奖）\n"
        "连签天数：1 天 ｜ 进度 1/7"
    )


def test_checkin_makeup_messages_default_match_legacy_text():
    """③ 补签族引擎 message 默认逐字符一致（含失败分支）。"""
    assert ck.checkin_makeup(42, None)["message"] == "❌ 结算上下文非法"
    assert ck.checkin_makeup(_ctx(checkin_tables={}), None)["message"] == "❌ 未配置签到表"
    assert ck.checkin_makeup(_ctx(), "nope")["message"] == "❌ 签到表不存在"

    tables = {k: dict(v) for k, v in TABLES.items()}
    tables["loop"]["makeup"] = {"enabled": False}
    assert ck.checkin_makeup(_ctx(checkin_tables=tables), "loop")["message"] \
        == "❌ 当前未开启补签"

    # 月上限
    state = {"loop": {"last_date": "2026-08-25", "streak": 3, "month_total": 3,
                      "signed_days": ["2026-08-25"], "makeup_used": 3,
                      "makeup_month": "2026-08", "month_milestones": [], "longline": 0}}
    assert ck.checkin_makeup(_ctx(checkin_state=state, count_item=lambda i: 0), "loop")["message"] \
        == "❌ 本月补签已达上限 3 次"

    # 成功（卡通道）
    state = {"loop": {"last_date": "2026-08-25", "streak": 3, "month_total": 3,
                      "signed_days": ["2026-08-25"], "makeup_used": 0,
                      "makeup_month": "2026-08", "month_milestones": [], "longline": 0}}
    res = ck.checkin_makeup(_ctx(checkin_state=state, count_item=lambda i: 1), "loop")
    assert res["message"] == "✅ 补签成功（card）· 只计不补发"


def test_gm_empty_log_reuses_log_sys_empty_key():
    """④ GM /日志 空页 = 表键 log_sys_empty，且可被 ctx 覆盖。"""
    assert render_log_page([], 1) == DEFAULT_TEMPLATES["log_sys_empty"]
    assert render_log_page([], 1, ctx={"templates": {"log_sys_empty": "（空）"}}) == "（空）"


def test_grant_label_uses_table_keys():
    """grant 标签复用既有 checkin_grant_* 键（内容包可覆盖）。"""
    ctx = _ctx(items={"药水": {"id": "药水", "name": "药水"}})
    assert ck._grant_label({"type": "item", "item": "药水", "count": 2}, ctx) == "药水×2"
    assert ck._grant_label({"type": "exp", "amount": 20}, ctx) == "经验×20"
    covered = _ctx(items={"药水": {"id": "药水", "name": "药水"}},
                   templates={"checkin_grant_item": "{item}*{count}"})
    assert ck._grant_label({"type": "item", "item": "药水", "count": 2}, covered) == "药水*2"
