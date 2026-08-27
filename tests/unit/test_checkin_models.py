"""M4 批次5·路F1：checkin.json 签到数据模型（CheckinDef 多表 loop/monthly/activity + 奖励三通道
+ 补签 + 里程碑 + [签到:*] 三键）+ validate_checkins 专项校验测试。

依据：m4_shared_contract §3.4（签到 E1-E4）+ 细化_2b5_签到引擎契约.md（checkin.json 字段级
schema §1.2~1.8 / 连签 §三 / 补签 §四 / 验收 TC-01~TC-33）
+ 签到系统设计定稿.md（字段元数据表 L127-137 / 奖励四通道 L51-58 / 校验器 §八 L139-151）
+ 2026-08-27 M4 设计审查裁决：P2-4（裁决⑧ [签到:*] 三键表名限定）/ P2-5（裁决⑦ 补签只计不补发）。

测试目标：qbot_rpg.content.checkin_models.validate_checkins（独立模块专项校验，供主 agent 收口接 check_pack）。

测试口径（对齐 test_npc_models / test_shop_models / test_quest_models）：
  - validate_checkins(modules, report, now=None) 为纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含真实 _Checker 收口兼容测试）。
  - 断言级别：errors=拦截（硬拦）/ warnings=黄提示（不拦截）。
  - 合法全量 schema（loop/monthly/activity 三表，TC-01）零红拦零黄。
"""
from __future__ import annotations

import copy

from qbot_rpg.content.checkin_models import (
    CHECKIN_CYCLE_DAYS_DEFAULT,
    CHECKIN_DEFAULT_TABLE,
    CHECKIN_KEY_FIELDS,
    CHECKIN_KEY_MONTHLY,
    CHECKIN_KEY_PREFIX,
    CHECKIN_KEY_STREAK,
    CHECKIN_KEY_TODAY,
    CHECKIN_MAKEUP_COST_WARN_MAX,
    CHECKIN_MAX_MONTH_DAYS,
    CHECKIN_MODULE,
    CHECKIN_NAME_MAX_LEN,
    CHECKIN_RESET_TIME_DEFAULT,
    CHECKIN_RESET_TIME_KEY,
    CHECKIN_TYPES,
    CHECKIN_TYPE_DEFAULT,
    CheckinDef,
    MakeupDef,
    PeriodDef,
    RewardEntryDef,
    RewardsDef,
    parse_checkin_key,
    parse_checkins,
    validate_checkins,
)
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import _Checker

# ---------------------------------------------------------------------------
# 夹具辅助：构造输入 → 跑校验器
# ---------------------------------------------------------------------------
class _Report:
    """validate_checkins 收集器（鸭子类型：error/warning 与 validator._Checker._err/_warn 签名一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def note(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.notes.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _base_modules() -> dict:
    """标准模块上下文：引用靶齐全（items 物品键空间 + settings 货币键空间）。"""
    return {
        "items": [{"id": "药水"}, {"id": "钻石"}, {"id": "强化石"}, {"id": "宝箱"}, {"id": "补签卡"}],
        "settings": {"currencies": [{"id": "coins"}, {"id": "gem"}, {"id": "diamond"}]},
    }


def _legal_checkins() -> list:
    """合法全量三表（TC-01：loop/monthly/activity 多表并存，id 各唯一，零红拦零黄）。"""
    return [
        {
            "id": "checkin_loop",
            "name": "常驻循环签到",
            "type": "loop",
            "desc": "每日签到领好礼",
            "period": {"start": None, "end": None, "cycle_days": 7, "reset_on_break": True},
            "rewards": {
                "daily": [
                    {"day": 1, "items": [{"id": "药水", "count": 2}], "coins": 50, "exp": 20},
                    {"day": 2, "items": [{"id": "药水", "count": 1}], "coins": 60, "exp": 25},
                ],
                "streak": [
                    {"days": 3, "items": [{"id": "钻石", "count": 1}], "gem": 3},
                    {"days": 7, "items": [{"id": "宝箱", "count": 1}]},
                ],
                "monthly_total": [],
            },
            "makeup": {"enabled": False, "cost": {"coins": 100}, "max_per_month": 3},
            "bonus": None,
        },
        {
            "id": "checkin_monthly",
            "name": "月度签到",
            "type": "monthly",
            "period": {"cycle_days": 31, "reset_on_break": True},
            "rewards": {
                "daily": [
                    {"day": 1, "items": [{"id": "药水", "count": 2}], "coins": 50, "exp": 20},
                    {"day": 2, "coins": 60, "exp": 25},
                ],
                "streak": [{"days": 7, "items": [{"id": "钻石", "count": 1}], "gem": 3}],
                "monthly_total": [
                    {"days": 15, "items": [{"id": "强化石", "count": 3}]},
                    {"days": 31, "items": [{"id": "宝箱", "count": 1}], "gem": 10},
                ],
            },
            "makeup": {"enabled": False},
        },
        {
            "id": "act_anniv",
            "name": "周年庆典",
            "type": "activity",
            "period": {"start": "2026-09-01 00:00", "end": "2026-09-30 23:59", "cycle_days": 14},
            "rewards": {
                "daily": [{"day": 1, "items": [{"id": "药水", "count": 4}], "coins": 100}],
                "streak": [],
                "monthly_total": [],
            },
            "makeup": {"enabled": True, "cost": {"coins": 200}, "max_per_month": 0},
            "bonus": {"mult": 2},
        },
    ]


def _check(checkins: object, now: object = None, **extra_modules: object):
    """跑 validate_checkins；默认带齐全引用靶模块。extra_modules 可覆盖 items/settings 等。"""
    modules: dict = _base_modules()
    modules[CHECKIN_MODULE] = checkins
    modules.update(extra_modules)
    rep = _Report()
    validate_checkins(modules, rep, now=now)
    return rep


def _errs(rep, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


def _table_by_id(checkins: list, cid: str) -> dict:
    for t in checkins:
        if t.get("id") == cid:
            return t
    raise AssertionError(f"checkin 缺少 {cid}")


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 访问器 + parse_checkins
# ---------------------------------------------------------------------------
def test_legal_checkin_full_green() -> None:
    """TC-01：loop/monthly/activity 三表同文件并存（id 各唯一）→ 零红拦零黄。"""
    rep = _check(_legal_checkins())
    assert not rep.errors, f"合法 checkin 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 checkin 应为零黄提示：{rep.warnings}"


def test_legal_checkin_checker_integration() -> None:
    """收口兼容：validate_checkins 直传真实 validator._Checker（_err/_warn 鸭子路径）零红拦零黄。"""
    modules = _base_modules()
    modules[CHECKIN_MODULE] = _legal_checkins()
    checker = _Checker(modules, default_field_meta_table())
    validate_checkins(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"


def test_parse_checkins() -> None:
    """parse_checkins 提取 checkin 模块 → CheckinDef 元组（非 list/非对象条目跳过）。"""
    checkins = _legal_checkins()
    defs = parse_checkins({CHECKIN_MODULE: checkins})
    assert [d.id for d in defs] == ["checkin_loop", "checkin_monthly", "act_anniv"]
    assert parse_checkins({CHECKIN_MODULE: "nope"}) == ()
    assert parse_checkins({}) == ()


def test_checkindef_accessors() -> None:
    """CheckinDef 顶层字段 + 子表访问器（type/desc/period/rewards/makeup/bonus）。"""
    entry = _table_by_id(_legal_checkins(), "checkin_monthly")
    d = CheckinDef.from_entry(entry)
    assert d.id == "checkin_monthly"
    assert d.name == "月度签到"
    assert d.type == "monthly"
    assert d.effective_type == "monthly"
    assert d.is_activity is False
    assert d.desc is None  # monthly 未配 desc
    assert isinstance(d.period, PeriodDef)
    assert d.period.cycle_days == 31
    assert d.period.reset_on_break is True
    assert d.period.start is None
    assert d.period.effective_reset_on_break() is True
    assert isinstance(d.rewards, RewardsDef)
    assert len(d.rewards.daily) == 2
    assert len(d.rewards.streak) == 1
    assert len(d.rewards.monthly_total) == 2
    assert d.rewards.daily[0].day == 1
    assert d.rewards.daily[0].items[0]["id"] == "药水"
    assert d.rewards.streak[0].days == 7
    assert isinstance(d.makeup, MakeupDef)
    assert d.makeup.enabled is False
    assert d.makeup.cost == {}
    assert d.makeup.effective_max_per_month() == 0
    assert d.bonus == {}
    assert d.effective_cycle_days() == 31
    assert d.streak_thresholds() == (7,)
    assert d.monthly_total_thresholds() == (15, 31)


def test_checkindef_activity_accessors() -> None:
    """活动表访问器：is_activity / 生效周期 / makeup 两通道 / bonus.mult。"""
    entry = _table_by_id(_legal_checkins(), "act_anniv")
    d = CheckinDef.from_entry(entry)
    assert d.is_activity is True
    assert d.effective_cycle_days() == 14
    assert d.makeup.enabled is True
    assert d.makeup.cost == {"coins": 200}
    assert d.makeup.has_cost_channel() is True
    assert d.makeup.effective_max_per_month() == 0  # 0=不限
    assert d.bonus.get("mult") == 2


def test_checkindef_defaults() -> None:
    """缺省兜底（D-07）：最小配置 {id,name} 绝不报错；type 缺省 loop / cycle 7 / makeup 关。"""
    d = CheckinDef.from_entry({"id": "checkin_min", "name": "最小签到"})
    assert d.type is None  # raw 未写 type（默认 loop 为 effective_type 兜底）
    assert d.effective_type == CHECKIN_TYPE_DEFAULT == "loop"
    assert d.is_activity is False
    assert d.period.cycle_days is None
    assert d.period.effective_cycle_days("loop") == CHECKIN_CYCLE_DAYS_DEFAULT == 7
    assert d.period.effective_reset_on_break() is True
    assert d.rewards.daily == ()
    assert d.rewards.streak == ()
    assert d.rewards.monthly_total == ()
    assert d.makeup.enabled is False
    assert d.makeup.cost == {}
    assert d.makeup.effective_max_per_month() == 0
    assert d.bonus == {}
    # 最小配置跑校验器：零红拦（黄提示仅 loop 缺 cycle_days 默认 7 补全，不拦）
    rep = _check([{"id": "checkin_min", "name": "最小签到"}])
    assert not rep.errors, f"最小配置不应红拦：{rep.errors}"
    assert len(_warns(rep, "checkin_cycle_days_default")) == 1


# ---------------------------------------------------------------------------
# 三表类型（TC-01 / 定稿 L129）
# ---------------------------------------------------------------------------
def test_three_types_enum() -> None:
    """三表类型 loop/monthly/activity 合法；非法 type → 红拦；缺省 loop 不拦。"""
    assert set(CHECKIN_TYPES) == {"loop", "monthly", "activity"}
    for t in CHECKIN_TYPES:
        entry = {"id": f"c_{t}", "name": t, "type": t}
        if t == "activity":  # 活动表必有时间窗（定稿 L130）
            entry["period"] = {"start": "2026-09-01 00:00", "end": "2026-09-30 23:59"}  # type: ignore[assignment]
        rep = _check([entry])
        assert not rep.errors, f"type={t} 不应红拦：{rep.errors}"
    rep = _check([{"id": "c_bad", "name": "坏", "type": "weekly"}])
    assert len(_errs(rep, "checkin_type_invalid")) == 1
    # 缺省 type → loop
    d = CheckinDef.from_entry({"id": "c_no", "name": "无类型"})
    assert d.effective_type == "loop"


def test_activity_requires_window() -> None:
    """定稿 L130：活动表必填 start/end；缺省 → 红拦；loop/monthly 不要求。"""
    rep = _check([{"id": "act_x", "name": "活动", "type": "activity"}])
    assert len(_errs(rep, "checkin_activity_start_required")) == 1
    assert len(_errs(rep, "checkin_activity_end_required")) == 1
    rep = _check([{"id": "act_x", "name": "活动", "type": "activity",
                   "period": {"start": "2026-09-01 00:00"}}])
    assert len(_errs(rep, "checkin_activity_end_required")) == 1
    assert not _errs(rep, "checkin_activity_start_required")
    # loop/monthly 无窗口 → 不报错
    rep = _check([{"id": "c_loop", "name": "循环", "type": "loop"}])
    assert not _errs(rep, "checkin_activity_start_required")
    # loop/monthly 配了窗口 → 黄提示（常驻=null）
    rep = _check([{"id": "c_loop", "name": "循环", "type": "loop",
                   "period": {"start": "2026-09-01 00:00", "end": "2026-09-30 23:59"}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_resident_window")) == 1


# ---------------------------------------------------------------------------
# 周期（TC-02/TC-03 + 定稿 L130-132）
# ---------------------------------------------------------------------------
def test_loop_missing_cycle_days_warning() -> None:
    """TC-03：loop 缺 cycle_days → 不报错，黄提示「已按默认 7 补全」；生效周期 7。"""
    rep = _check([{"id": "c_loop", "name": "循环", "type": "loop"}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_cycle_days_default")) == 1
    d = CheckinDef.from_entry({"id": "c_loop", "name": "循环", "type": "loop"})
    assert d.effective_cycle_days() == CHECKIN_CYCLE_DAYS_DEFAULT == 7


def test_monthly_no_cycle_days() -> None:
    """TC-02：monthly 不配 cycle_days → 不报错（自动=当月天数，运行期 D-01）；校验口径 31。"""
    rep = _check([{"id": "c_m", "name": "月度", "type": "monthly"}])
    assert not rep.errors
    assert not _warns(rep, "checkin_cycle_days_default")  # 仅 loop 触发该提示
    d = CheckinDef.from_entry({"id": "c_m", "name": "月度", "type": "monthly"})
    assert d.effective_cycle_days() == CHECKIN_MAX_MONTH_DAYS == 31


def test_cycle_days_and_reset_on_break_invalid() -> None:
    """period.cycle_days 非 ≥1 整数 / reset_on_break 非 bool → 红拦。"""
    for cd in (0, -3, "7", 7.0, True):
        rep = _check([{"id": "c_p", "name": "周期", "period": {"cycle_days": cd}}])
        assert len(_errs(rep, "checkin_cycle_days_invalid")) == 1, f"cycle_days={cd!r}"
    rep = _check([{"id": "c_p", "name": "周期", "period": {"reset_on_break": "yes"}}])
    assert len(_errs(rep, "checkin_reset_on_break_invalid")) == 1
    rep = _check([{"id": "c_p", "name": "周期", "period": "nope"}])
    assert len(_errs(rep, "checkin_period_not_object")) == 1


# ---------------------------------------------------------------------------
# 奖励条目结构（items[] / 标量键值，定稿 L60/L133-135）
# ---------------------------------------------------------------------------
def test_reward_entry_structure_ok() -> None:
    """合法奖励条目：items[]{id,count} + coins/exp 并存（定稿 L42 样例）；streak/monthly_total 同理。"""
    rep = _check([{
        "id": "c_r", "name": "奖励", "period": {"cycle_days": 7}, "rewards": {
            "daily": [{"day": 1, "items": [{"id": "药水", "count": 2}], "coins": 50, "exp": 20}],
            "streak": [{"days": 7, "items": [{"id": "钻石", "count": 1}], "gem": 3}],
            "monthly_total": [{"days": 15, "items": [{"id": "强化石", "count": 3}]}],
        }}])
    assert not rep.errors, f"合法奖励条目不应红拦：{rep.errors}"
    assert not rep.warnings


def test_item_ref_missing() -> None:
    """TC-04：奖励物品引用不存在 → 红拦（R-4）；items 模块未声明 → 跳过。"""
    rep = _check([{"id": "c_r", "name": "奖励",
                   "rewards": {"daily": [{"day": 1, "items": [{"id": "不存在之物", "count": 1}]}]}}])
    assert len(_errs(rep, "checkin_item_ref_missing")) == 1
    rep = _check([{"id": "c_r", "name": "奖励",
                   "rewards": {"daily": [{"day": 1, "items": [{"id": "不存在之物", "count": 1}]}]}}],
                 items=None)
    assert not _errs(rep, "checkin_item_ref_missing")


def test_negative_values_hard_block() -> None:
    """TC-05：奖励数/补签费负数 → 红拦「奖励数量不能是负数哦」（定稿 L143）。"""
    rep = _check([{"id": "c_r", "name": "奖励", "rewards": {
        "daily": [{"day": 1, "items": [{"id": "药水", "count": -1}]}],
        "streak": [{"days": 7, "gem": -3}],
    }}])
    assert len(_errs(rep, "checkin_item_count_invalid")) == 1
    assert len(_errs(rep, "checkin_reward_value_invalid")) == 1
    rep = _check([{"id": "c_r", "name": "奖励", "makeup": {"enabled": True, "cost": {"coins": -100}}}])
    assert len(_errs(rep, "checkin_makeup_cost_negative")) == 1


def test_reward_entry_structure_errors() -> None:
    """奖励条目结构硬拦：条目非对象 / 缺 day / day 非法 / items 非数组 / 物品条目缺 id / 未知键。"""
    rep = _check([{"id": "c_r", "name": "奖励", "rewards": {
        "daily": [
            "not_an_object",
            {"coins": 50},                      # 缺 day
            {"day": 0},                         # day 非法（非 ≥1）
            {"day": 1, "items": "nope"},        # items 非数组
            {"day": 1, "items": [{"count": 2}]},  # 物品条目缺 id
            {"day": 1, "foo": 1},               # 未知键
        ],
    }}])
    assert len(_errs(rep, "checkin_entry_not_object")) == 1
    assert len(_errs(rep, "checkin_wrapper_missing")) == 1
    assert len(_errs(rep, "checkin_wrapper_invalid")) == 1
    assert len(_errs(rep, "checkin_items_not_list")) == 1
    assert len(_errs(rep, "checkin_item_missing_id")) == 1
    assert len(_errs(rep, "checkin_entry_unknown_key")) == 1


def test_currency_unregistered() -> None:
    """coins/gem 货币键未注册（settings 存在时）→ 红拦；奖励与补签费两处。"""
    rep = _check([{"id": "c_c", "name": "货币",
                   "rewards": {"daily": [{"day": 1, "gem": 3}]},
                   "makeup": {"enabled": True, "cost": {"gem": 50}}}],
                 settings={"currencies": [{"id": "coins"}]})
    assert len(_errs(rep, "checkin_reward_currency_unregistered")) == 1
    assert len(_errs(rep, "checkin_makeup_cost_currency_unregistered")) == 1
    # settings 缺省 → 默认模板兜底（coins/diamond），不误拦
    rep = _check([{"id": "c_c", "name": "货币",
                   "rewards": {"daily": [{"day": 1, "coins": 50}]}}], settings=None)
    assert not rep.errors


def test_daily_day_over_cycle_warning() -> None:
    """定稿 L55：每日 day 超周期 → 黄提示（该档永远不会被轮到，不拦）。"""
    rep = _check([{"id": "c_d", "name": "每日", "period": {"cycle_days": 7},
                   "rewards": {"daily": [{"day": 8, "coins": 50}]}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_daily_day_over_cycle")) == 1
    # day 在周期内 → 零黄
    rep = _check([{"id": "c_d", "name": "每日", "period": {"cycle_days": 7},
                   "rewards": {"daily": [{"day": 7, "coins": 50}]}}])
    assert not _warns(rep, "checkin_daily_day_over_cycle")


def test_daily_day_duplicate_warning() -> None:
    """【工程补白】8：每日 day 重复 → 黄提示（后条目遮蔽前条目）。"""
    rep = _check([{"id": "c_d", "name": "每日",
                   "rewards": {"daily": [{"day": 1, "coins": 50}, {"day": 1, "exp": 20}]}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_daily_day_duplicate")) == 1
    # 不同 day → 零黄
    rep = _check([{"id": "c_d", "name": "每日",
                   "rewards": {"daily": [{"day": 1, "coins": 50}, {"day": 2, "exp": 20}]}}])
    assert not _warns(rep, "checkin_daily_day_duplicate")


# ---------------------------------------------------------------------------
# 里程碑阈值（定稿 L56/L57 + 【工程补白】3：严格递增）
# ---------------------------------------------------------------------------
def test_milestone_thresholds_increasing() -> None:
    """连签/月度累计阈值严格递增合法；倒挂/重复 → 红拦。"""
    rep = _check([{"id": "c_m", "name": "里程碑",
                   "rewards": {"streak": [{"days": 7}, {"days": 14}, {"days": 30}],
                               "monthly_total": [{"days": 15}, {"days": 31}]}}])
    assert not rep.errors, f"递增阈值不应红拦：{rep.errors}"
    # 连签倒挂
    rep = _check([{"id": "c_m", "name": "里程碑",
                   "rewards": {"streak": [{"days": 14}, {"days": 7}]}}])
    assert len(_errs(rep, "checkin_milestone_not_increasing")) == 1
    # 连签重复（不递增）
    rep = _check([{"id": "c_m", "name": "里程碑",
                   "rewards": {"streak": [{"days": 7}, {"days": 7}]}}])
    assert len(_errs(rep, "checkin_milestone_not_increasing")) == 1
    # 月度累计倒挂
    rep = _check([{"id": "c_m", "name": "里程碑",
                   "rewards": {"monthly_total": [{"days": 31}, {"days": 15}]}}])
    assert len(_errs(rep, "checkin_milestone_not_increasing")) == 1


def test_milestone_missing_days() -> None:
    """里程碑条目缺 days / days 非法 → 红拦。"""
    rep = _check([{"id": "c_m", "name": "里程碑",
                   "rewards": {"streak": [{"items": [{"id": "钻石", "count": 1}]}],
                               "monthly_total": [{"days": 0}]}}])
    assert len(_errs(rep, "checkin_wrapper_missing")) == 1
    assert len(_errs(rep, "checkin_wrapper_invalid")) == 1


def test_streak_over_cycle_warning() -> None:
    """TC-06：streak.days=30 而 cycle_days=7 → 黄提示「连签 30 天才给，但周期只有 7 天」不拦。"""
    rep = _check([{"id": "c_s", "name": "连签", "period": {"cycle_days": 7},
                   "rewards": {"streak": [{"days": 30, "items": [{"id": "钻石", "count": 1}]}]}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_streak_over_cycle")) == 1
    # 阈值在周期内 → 零黄
    rep = _check([{"id": "c_s", "name": "连签", "period": {"cycle_days": 7},
                   "rewards": {"streak": [{"days": 7}]}}])
    assert not _warns(rep, "checkin_streak_over_cycle")
    # monthly 未配 cycle_days：31 内阈值不误伤
    rep = _check([{"id": "c_s", "name": "连签", "type": "monthly",
                   "rewards": {"streak": [{"days": 30}]}}])
    assert not _warns(rep, "checkin_streak_over_cycle")


def test_rewards_structure_errors() -> None:
    """rewards 非对象 / 通道非数组 → 红拦。"""
    rep = _check([{"id": "c_r", "name": "奖励", "rewards": "nope"}])
    assert len(_errs(rep, "checkin_rewards_not_object")) == 1
    rep = _check([{"id": "c_r", "name": "奖励", "rewards": {"daily": {"day": 1}}}])
    assert len(_errs(rep, "checkin_channel_not_list")) == 1


# ---------------------------------------------------------------------------
# makeup 补签（定稿 L58/L136 + TC-19~24 配置侧）
# ---------------------------------------------------------------------------
def test_makeup_structure_errors() -> None:
    """makeup：非对象 / enabled 非 bool / cost 非对象 / max_per_month 负数 → 红拦。"""
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": "nope"}])
    assert len(_errs(rep, "checkin_makeup_not_object")) == 1
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"enabled": "yes"}}])
    assert len(_errs(rep, "checkin_makeup_enabled_invalid")) == 1
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"cost": 100}}])
    assert len(_errs(rep, "checkin_makeup_cost_not_object")) == 1
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"max_per_month": -1}}])
    assert len(_errs(rep, "checkin_makeup_max_per_month_invalid")) == 1
    # 0=不限 合法
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"max_per_month": 0}}])
    assert not _errs(rep, "checkin_makeup_max_per_month_invalid")


def test_makeup_no_cost_warning() -> None:
    """TC-06 侧/定稿 L149：补签开启但无任何费用通道 → 黄提示「补签不花钱？确认」。"""
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"enabled": True}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_makeup_no_cost")) == 1
    # 有 cost → 不提示
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"enabled": True, "cost": {"coins": 100}}}])
    assert not _warns(rep, "checkin_makeup_no_cost")
    # 默认关（enabled=false）→ 不提示
    rep = _check([{"id": "c_mk", "name": "补签", "makeup": {"enabled": False}}])
    assert not _warns(rep, "checkin_makeup_no_cost")


def test_makeup_cost_high_warning() -> None:
    """定稿 L149：补签费超常见区间 → 黄提示（不拦）。"""
    rep = _check([{"id": "c_mk", "name": "补签",
                   "makeup": {"enabled": True, "cost": {"coins": CHECKIN_MAKEUP_COST_WARN_MAX + 1}}}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_makeup_cost_high")) == 1
    # 区间内 → 零黄
    rep = _check([{"id": "c_mk", "name": "补签",
                   "makeup": {"enabled": True, "cost": {"coins": 100}}}])
    assert not _warns(rep, "checkin_makeup_cost_high")


# ---------------------------------------------------------------------------
# id / name / type / 其它结构
# ---------------------------------------------------------------------------
def test_id_required_and_duplicate() -> None:
    """id 缺失 → 红拦；两个表同 id → 红拦（唯一性，定稿 L142）。"""
    checkins = _legal_checkins()
    checkins[0]["id"] = ""
    rep = _check(checkins)
    assert len(_errs(rep, "checkin_id_required")) == 1
    checkins = _legal_checkins()
    checkins[1]["id"] = "checkin_loop"  # 与 checkins[0] 同 id
    rep = _check(checkins)
    assert len(_errs(rep, "checkin_id_duplicate")) == 1


def test_name_required_and_length() -> None:
    """name 必填 → 红拦；name >20 字 → 黄提示（定稿 L128）。"""
    checkins = [_legal_checkins()[0]]
    del checkins[0]["name"]
    rep = _check(checkins)
    assert len(_errs(rep, "checkin_name_required")) == 1
    rep = _check([{"id": "c_n", "name": "超" * (CHECKIN_NAME_MAX_LEN + 1)}])
    assert not rep.errors
    assert len(_warns(rep, "checkin_name_too_long")) == 1
    # 恰 20 字 → 零黄
    rep = _check([{"id": "c_n", "name": "签" * CHECKIN_NAME_MAX_LEN}])
    assert not _warns(rep, "checkin_name_too_long")


def test_desc_and_entry_not_object() -> None:
    """desc 非字符串 / 表条目非对象 → 红拦。"""
    rep = _check([{"id": "c_d", "name": "描述", "desc": 123}])
    assert len(_errs(rep, "checkin_desc_invalid")) == 1
    rep = _check([{"id": "c_d", "name": "描述"}, "not_an_object"])
    assert len(_errs(rep, "checkin_not_object")) == 1


def test_bonus_structure() -> None:
    """bonus：非对象 / mult 非法 → 红拦；缺省/合法对象不拦。"""
    rep = _check([{"id": "c_b", "name": "加成", "bonus": "nope"}])
    assert len(_errs(rep, "checkin_bonus_not_object")) == 1
    rep = _check([{"id": "c_b", "name": "加成", "bonus": {"mult": -1}}])
    assert len(_errs(rep, "checkin_bonus_mult_invalid")) == 1
    rep = _check([{"id": "c_b", "name": "加成", "bonus": {"mult": 2}}])
    assert not rep.errors


# ---------------------------------------------------------------------------
# 活动表时间窗（定稿 L147 未开始/已过期；【工程补白】4：now 显式注入）
# ---------------------------------------------------------------------------
def test_activity_window_status() -> None:
    """now 提供时：活动表 start 未到 → 黄提示未开始；end 已过 → 黄提示已过期；窗口内 → 零黄。"""
    act = {"id": "act_w", "name": "窗口", "type": "activity",
           "period": {"start": "2026-09-01 00:00", "end": "2026-09-30 23:59"}}
    # now = 2026-08-31 00:00 UTC+8（秒级，start 之前）
    before = 1788105600  # 2026-08-31 00:00:00 UTC+8
    rep = _check([act], now=before)
    assert not rep.errors
    assert len(_warns(rep, "checkin_activity_not_started")) == 1
    assert not _warns(rep, "checkin_activity_expired")
    # now = 2026-10-01 00:00 UTC+8（end 之后）
    after = 1790784000  # 2026-10-01 00:00:00 UTC+8
    rep = _check([act], now=after)
    assert len(_warns(rep, "checkin_activity_expired")) == 1
    assert not _warns(rep, "checkin_activity_not_started")
    # now = 2026-09-15 00:00 UTC+8（窗口内）
    inside = 1789401600  # 2026-09-15 00:00:00 UTC+8
    rep = _check([act], now=inside)
    assert not _warns(rep, "checkin_activity_not_started")
    assert not _warns(rep, "checkin_activity_expired")
    # now 缺省 → 跳过（确定性）
    rep = _check([act])
    assert not _warns(rep, "checkin_activity_not_started")
    assert not _warns(rep, "checkin_activity_expired")


# ---------------------------------------------------------------------------
# [签到:*] 三键（裁决⑧：表名限定 / 缺省表名=主表 loop）+ 引用校验（定稿 L150）
# ---------------------------------------------------------------------------
def test_checkin_key_parsing() -> None:
    """裁决⑧：三键解析（缺省表名=主表 loop / 表名限定 / 未知字段/坏格式 → None）。"""
    assert parse_checkin_key("[签到:连续天数]") == ("loop", CHECKIN_KEY_STREAK)
    assert parse_checkin_key("[签到:monthly.本月天数]") == ("monthly", CHECKIN_KEY_MONTHLY)
    assert parse_checkin_key("[签到:activity.今日已签]") == ("activity", CHECKIN_KEY_TODAY)
    assert parse_checkin_key("[签到:loop.连续天数]") == ("loop", CHECKIN_KEY_STREAK)
    assert parse_checkin_key("[签到: 连续天数 ]") == ("loop", CHECKIN_KEY_STREAK)  # 空白容忍
    assert parse_checkin_key("[签到:loop.随便]") is None          # 未知字段
    assert parse_checkin_key("[签到:loop]") is None               # 缺字段
    assert parse_checkin_key("[签到:loop..今日已签]") is None       # 空表名
    assert parse_checkin_key("签到:loop.连续天数") is None          # 缺方括号
    assert parse_checkin_key("") is None
    assert parse_checkin_key(123) is None


def test_checkin_key_field_constants() -> None:
    """裁决⑧ 三键常量与缺省表名。"""
    assert CHECKIN_DEFAULT_TABLE == "loop"
    assert set(CHECKIN_KEY_FIELDS) == {CHECKIN_KEY_STREAK, CHECKIN_KEY_MONTHLY, CHECKIN_KEY_TODAY}
    assert CHECKIN_KEY_STREAK == "连续天数"
    assert CHECKIN_KEY_MONTHLY == "本月天数"
    assert CHECKIN_KEY_TODAY == "今日已签"
    assert CHECKIN_KEY_PREFIX == "[签到:"


def test_checkin_key_table_ref_missing() -> None:
    """条件键引用不存在的签到表 → 黄提示（表名限定引用悬空，裁决⑧）。"""
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"var": "[签到:ghost.连续天数]", "op": "ge", "value": 3}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not rep.errors
    assert len(_warns(rep, "checkin_key_table_ref_missing")) == 1
    # 引用的表存在 → 零黄
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"var": "[签到:monthly.本月天数]", "op": "ge", "value": 15}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not _warns(rep, "checkin_key_table_ref_missing")


def test_checkin_key_fallback_loop_ref() -> None:
    """缺省表名=loop：条件键无表名引用 loop；包内无 loop 表 → 黄提示引用不存在。"""
    checkins = [_table_by_id(_legal_checkins(), "checkin_monthly")]  # 只有 monthly，无 loop
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"var": "[签到:连续天数]", "op": "ge", "value": 3}]}]
    rep = _check(checkins, quest=quests)
    assert len(_warns(rep, "checkin_key_table_ref_missing")) == 1
    assert _warns(rep, "checkin_key_table_ref_missing")[0]["detail"]["table"] == "loop"


def test_checkin_table_unreferenced_warning() -> None:
    """定稿 L150：接线机制启用（包内存在 [签到:*] 键）时，非 loop 表未被引用 → 黄提示「无人引用」；
    loop 主表默认入口豁免。"""
    # 接线启用：quest 只引用 loop；monthly/activity 未被引用 → 各一条黄提示
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"var": "[签到:loop.连续天数]", "op": "ge", "value": 3}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not rep.errors
    rules = [w["detail"]["rule"] for w in rep.warnings]
    assert "checkin_table_unreferenced" in rules
    unreferenced = {w["detail"]["table"] for w in _warns(rep, "checkin_table_unreferenced")}
    assert "checkin_monthly" in unreferenced and "act_anniv" in unreferenced
    assert "checkin_loop" not in unreferenced  # loop 默认入口豁免
    # 表被引用 → 不提示
    quests = [{"id": "q_2", "name": "任务", "conditions": [
        {"var": "[签到:monthly.本月天数]", "op": "ge", "value": 15},
        {"var": "[签到:activity.今日已签]", "op": "eq", "value": 1}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not _warns(rep, "checkin_table_unreferenced")
    # 无接线（包内无 [签到:*] 键）→ 不提示（【工程补白】6 保守口径）
    rep = _check(_legal_checkins())
    assert not _warns(rep, "checkin_table_unreferenced")
    # 单表包 → 不提示
    rep = _check([_table_by_id(_legal_checkins(), "checkin_monthly")], quest=quests)
    assert not _warns(rep, "checkin_table_unreferenced")


def test_checkin_key_malformed_warning() -> None:
    """条件键字段不认识 → 黄提示（裁决⑧ 三值枚举外）。"""
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"var": "[签到:loop.签到天数]", "op": "ge", "value": 3}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not rep.errors
    assert len(_warns(rep, "checkin_key_format_invalid")) == 1
    # 嵌套（any/all/not）也能被扫到
    quests = [{"id": "q_1", "name": "任务", "conditions": [
        {"all": [{"var": "[签到:monthly.本月天数]", "op": "ge", "value": 15}]}]}]
    rep = _check(_legal_checkins(), quest=quests)
    assert not _warns(rep, "checkin_key_format_invalid")
    assert not _warns(rep, "checkin_key_table_ref_missing")


# ---------------------------------------------------------------------------
# 结算管线语义落点（裁决⑦：补签只计不补发 / 里程碑不重复 —— 模型侧承载配置结构，运行期在 core/checkin.py）
# ---------------------------------------------------------------------------
def test_contract_semantics_constants() -> None:
    """重置时刻统一 05:00 不落数据：模型只导出 settings 引用键与默认值（运行期权威 = A3 core/dayroll）。"""
    assert CHECKIN_RESET_TIME_KEY == "refresh_time"
    assert CHECKIN_RESET_TIME_DEFAULT == "05:00"
    # 三表类型/默认值常量
    assert CHECKIN_TYPE_DEFAULT == "loop"
    assert CHECKIN_CYCLE_DAYS_DEFAULT == 7
    assert CHECKIN_DEFAULT_TABLE == "loop"


def test_reward_entry_def_accessors() -> None:
    """RewardEntryDef 访问器：day/days/items/item_ids/标量键值。"""
    entry = _legal_checkins()[0]["rewards"]["daily"][0]
    r = RewardEntryDef.from_entry(entry)
    assert r.day == 1
    assert r.days is None
    assert r.item_ids() == ("药水",)
    assert r.coins == 50
    assert r.exp == 20
    assert r.gem is None
    assert r.has_reward() is True
    s = RewardsDef.from_entry(_legal_checkins()[1]["rewards"])
    assert len(s.daily) == 2
    assert len(s.channel("monthly_total")) == 2
    assert s.channel("nope") == ()
    empty = RewardEntryDef.from_entry({"day": 1})
    assert empty.has_reward() is False


def test_reward_entry_def_mixed_channels() -> None:
    """定稿 L42 样例：同日 items+coins+exp 并存（与 quest reward 单条互斥不同）。"""
    entry = {"day": 1, "items": [{"id": "药水", "count": 2}], "coins": 50, "exp": 20}
    r = RewardEntryDef.from_entry(entry)
    assert r.item_ids() == ("药水",)
    assert r.coins == 50
    assert r.exp == 20
    rep = _check([{"id": "c_r", "name": "奖励", "period": {"cycle_days": 7},
                   "rewards": {"daily": [entry]}}])
    assert not rep.errors, f"并存条目不应红拦：{rep.errors}"
    assert not rep.warnings
