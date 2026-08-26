"""dayroll 日界统一与懒计算单测 —— M4 批次0·路A3（A3 唯一实现）。

依据：m4_shared_contract §1 A3（today_of 单一入口 / 05:00 重置可配 / 凌晨 0-5 点归属前一天 /
      惰性补算不依赖定时器 / 离线多天补算正确 / 返回形态 {today, days_elapsed, refreshed} /
      跨周判定与 once 时间窗复用周期工具）
      + 细化_2b5_签到引擎契约 §5.3（懒计算唯一判定 / 统一周期键 05:00 / 三表同刻对齐）+ §六
        TC-28/TC-29/TC-30/TC-31（凌晨不推进 / 05:00 后跨天 / 离线 7 天断签 / 重启不丢不炸）
      + 细化_2b4_任务引擎契约 §1.3（board.refresh daily/weekly/once）
      + 审查参考/商店系统设计定稿 §七（last_refresh 惰性补刷 / UTC+8 / 跨周按结束>开始判定 /
        once 未开门=not_started、已过=expired）。

手算基准（UTC+8 墙钟，见下方 _ts）：2026-08-26 = 周三；2026-08-25 = 周二；2026-08-24 = 周一；
  2026-08-17 = 周一；2026-08-18 = 周二；2026-08-16 = 周日；2026-08-12 = 周三；2026-08-11 = 周二。
"""

from __future__ import annotations

import datetime
from typing import Optional

import pytest

from qbot_rpg.core.dayroll import (
    DEFAULT_REFRESH_TIME,
    PERIODS,
    WINDOW_EXPIRED,
    WINDOW_NOT_STARTED,
    WINDOW_OPEN,
    advance_cycles,
    days_elapsed,
    is_window_open,
    normalize_hhmm,
    resolve_refresh_time,
    today_of,
    weeks_elapsed,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


# =====================================================================================
# ① 日期归属 / 重置时刻（默认 05:00 UTC+8：凌晨 0-5 点归属前一天）
# =====================================================================================
def test_today_default_reset_05_before_dawn_belongs_previous_day():
    # TC-28 口径：03:30 凌晨仍算前一天
    assert today_of(now=_ts(2026, 8, 26, 3, 30))["today"] == "2026-08-25"


def test_today_default_reset_05_at_0459_still_previous_day():
    assert today_of(now=_ts(2026, 8, 26, 4, 59, 59))["today"] == "2026-08-25"


def test_today_default_reset_05_exactly_0500_new_day():
    # TC-29 口径：05:00 整 = 重置时刻之后，算新一天
    assert today_of(now=_ts(2026, 8, 26, 5, 0, 0))["today"] == "2026-08-26"


def test_today_default_reset_05_midnight_belongs_previous_day():
    # 00:00 整也归属前一天（凌晨 0-5 点）
    assert today_of(now=_ts(2026, 8, 26, 0, 0))["today"] == "2026-08-25"


def test_today_default_reset_05_late_night_same_day():
    assert today_of(now=_ts(2026, 8, 26, 23, 59, 59))["today"] == "2026-08-26"


def test_today_custom_reset_1200():
    # 可配重置时刻 12:00：11:59 归属前一天，12:00 归属当天
    cfg = {"refresh_time": "12:00"}
    assert today_of(now=_ts(2026, 8, 26, 11, 59), cfg=cfg)["today"] == "2026-08-25"
    assert today_of(now=_ts(2026, 8, 26, 12, 0), cfg=cfg)["today"] == "2026-08-26"


def test_today_custom_reset_int_hour():
    # int 小时形态（对齐商店 refresh.hour）：5 → 05:00
    cfg = {"refresh_time": 5}
    assert today_of(now=_ts(2026, 8, 26, 4, 59), cfg=cfg)["today"] == "2026-08-25"
    assert today_of(now=_ts(2026, 8, 26, 5, 0), cfg=cfg)["today"] == "2026-08-26"


def test_today_custom_reset_with_minutes():
    # 分钟粒度重置 05:30：05:29 前一天、05:30 当天
    cfg = {"refresh_time": "5:30"}
    assert today_of(now=_ts(2026, 8, 26, 5, 29), cfg=cfg)["today"] == "2026-08-25"
    assert today_of(now=_ts(2026, 8, 26, 5, 30), cfg=cfg)["today"] == "2026-08-26"


def test_today_reset_0000_is_calendar_day():
    # 00:00 重置 = 自然日（无偏移）：凌晨 3 点归属当天
    cfg = {"refresh_time": "00:00"}
    assert today_of(now=_ts(2026, 8, 26, 3, 0), cfg=cfg)["today"] == "2026-08-26"


def test_today_bad_config_falls_back_default_0500():
    # 坏配置（校验器红拦）→ 引擎惰性回退默认 05:00，不崩溃（对齐 WorldTime 惯例）
    for bad in ("25:00", "abc", "05:99", True, 5.5, ["05:00"], -1):
        assert resolve_refresh_time({"refresh_time": bad}) == DEFAULT_REFRESH_TIME
    # 回退后按 05:00 判定
    assert today_of(now=_ts(2026, 8, 26, 4, 59), cfg={"refresh_time": "25:00"})["today"] == "2026-08-25"


def test_today_nested_settings_key():
    # 容错嵌套 settings.refresh_time（防整包包裹形态）
    cfg = {"settings": {"refresh_time": "12:00"}}
    assert resolve_refresh_time(cfg) == "12:00"
    assert today_of(now=_ts(2026, 8, 26, 11, 59), cfg=cfg)["today"] == "2026-08-25"


def test_today_pure_function_same_args_same_result():
    now = _ts(2026, 8, 26, 12, 0)
    assert today_of("2026-08-25", now) == today_of("2026-08-25", now)
    assert today_of("2026-08-25", now) == {"today": "2026-08-26", "days_elapsed": 1, "refreshed": True}


# =====================================================================================
# ② today_of 返回形态 {today, days_elapsed, refreshed}（懒补算）
# =====================================================================================
def test_today_of_first_ever_no_last_key():
    r = today_of(None, now=_ts(2026, 8, 26, 12, 0))
    assert r == {"today": "2026-08-26", "days_elapsed": 0, "refreshed": False}


def test_today_of_same_day_idempotent():
    r = today_of("2026-08-26", now=_ts(2026, 8, 26, 12, 0))
    assert r == {"today": "2026-08-26", "days_elapsed": 0, "refreshed": False}


def test_today_of_next_day_one_rollover():
    # 昨日签到、今日 05:00 后操作 → 跨 1 天补算（TC-29：streak+1）
    r = today_of("2026-08-25", now=_ts(2026, 8, 26, 5, 0, 0))
    assert r == {"today": "2026-08-26", "days_elapsed": 1, "refreshed": True}


def test_today_of_offline_multiple_days():
    # 离线 7 天后首次操作 → days_elapsed=7（TC-30：断签间隔>1 天；不丢不炸）
    r = today_of("2026-08-19", now=_ts(2026, 8, 26, 12, 0))
    assert r == {"today": "2026-08-26", "days_elapsed": 7, "refreshed": True}


def test_today_of_still_same_day_at_0300():
    # 凌晨 0-5 点操作不推进新一天（TC-28：last_date 不变更语义，防凌晨断签）
    r = today_of("2026-08-25", now=_ts(2026, 8, 26, 3, 30))
    assert r == {"today": "2026-08-25", "days_elapsed": 0, "refreshed": False}


def test_today_of_future_last_key_clock_skew():
    # 时钟回拨（last_key 在未来）→ 防御性 days_elapsed=0、refreshed=False（工程补白）
    r = today_of("2026-08-27", now=_ts(2026, 8, 26, 12, 0))
    assert r["days_elapsed"] == 0
    assert r["refreshed"] is False


def test_today_of_invalid_last_key_defensive():
    # 非法存档日期键 → 防御性回退 0/False，不崩溃（工程补白）
    for bad in ("garbage", "2026/08/26", "", "2026-13-40", 12345, None):
        r = today_of(bad, now=_ts(2026, 8, 26, 12, 0))
        assert r["today"] == "2026-08-26"
        assert r["days_elapsed"] == 0
        assert r["refreshed"] is False


# =====================================================================================
# ③ days_elapsed（跨期补算天数）
# =====================================================================================
def test_days_elapsed_none_zero():
    assert days_elapsed(None, now=_ts(2026, 8, 26, 12, 0)) == 0


def test_days_elapsed_same_day_zero():
    assert days_elapsed("2026-08-26", now=_ts(2026, 8, 26, 12, 0)) == 0


def test_days_elapsed_three_days():
    assert days_elapsed("2026-08-23", now=_ts(2026, 8, 26, 12, 0)) == 3


def test_days_elapsed_month_boundary():
    assert days_elapsed("2026-08-31", now=_ts(2026, 9, 7, 12, 0)) == 7
    assert days_elapsed("2026-07-31", now=_ts(2026, 8, 1, 12, 0)) == 1


def test_days_elapsed_future_zero():
    assert days_elapsed("2026-08-27", now=_ts(2026, 8, 26, 12, 0)) == 0


def test_days_elapsed_custom_reset_boundary():
    # 重置 12:00：last=08-25，now=08-26 11:00 → 仍同日（0）；12:00 → 跨 1 天
    cfg = {"refresh_time": "12:00"}
    assert days_elapsed("2026-08-25", now=_ts(2026, 8, 26, 11, 0), cfg=cfg) == 0
    assert days_elapsed("2026-08-25", now=_ts(2026, 8, 26, 12, 0), cfg=cfg) == 1


def test_days_elapsed_invalid_zero():
    assert days_elapsed("not-a-date", now=_ts(2026, 8, 26, 12, 0)) == 0


# =====================================================================================
# ④ weeks_elapsed 跨周判定（结束 > 开始 日期偏移；默认周一，1=周一..7=周日）
# =====================================================================================
def test_weeks_elapsed_none_or_invalid_zero():
    assert weeks_elapsed(None, now=_ts(2026, 8, 26, 12, 0)) == 0
    assert weeks_elapsed("garbage", now=_ts(2026, 8, 26, 12, 0)) == 0
    assert weeks_elapsed("2026-08-27", now=_ts(2026, 8, 26, 12, 0)) == 0


def test_weeks_elapsed_same_week_zero():
    # 周二(08-11) → 周四(08-13)：同一周内，周边界未越 → 0
    assert weeks_elapsed("2026-08-11", now=_ts(2026, 8, 13, 12, 0)) == 0
    # 周日(08-16) → 同日 0；周一(08-17) → 周一(08-17) 0
    assert weeks_elapsed("2026-08-16", now=_ts(2026, 8, 16, 12, 0)) == 0
    assert weeks_elapsed("2026-08-17", now=_ts(2026, 8, 17, 12, 0)) == 0


def test_weeks_elapsed_cross_monday_boundary():
    # 周三(08-12) → 周一(08-17)：跨周边界（结束 08-17 > 开始 08-10）→ 1
    assert weeks_elapsed("2026-08-12", now=_ts(2026, 8, 17, 12, 0)) == 1
    # 周日(08-16) → 周一(08-17)：周日晚→下周一晨 05:00 已过 → 1
    assert weeks_elapsed("2026-08-16", now=_ts(2026, 8, 17, 12, 0)) == 1
    # 周日(08-16) 08-16 05:00 后 → 跨 1
    assert weeks_elapsed("2026-08-16", now=_ts(2026, 8, 17, 5, 0)) == 1


def test_weeks_elapsed_two_weeks():
    # 周一(08-17) → 周一(08-31)：两周边界 → 2
    assert weeks_elapsed("2026-08-17", now=_ts(2026, 8, 31, 12, 0)) == 2
    # 周一(08-17) → 周一(08-24)：→ 1
    assert weeks_elapsed("2026-08-17", now=_ts(2026, 8, 24, 12, 0)) == 1


def test_weeks_elapsed_sunday_anchor():
    # weekday=7（周日边界）：周三(08-12) → 周日(08-16) 跨 1
    assert weeks_elapsed("2026-08-12", now=_ts(2026, 8, 16, 12, 0), weekday=7) == 1
    # 周三(08-12) → 周四(08-13)：同一周 0
    assert weeks_elapsed("2026-08-12", now=_ts(2026, 8, 13, 12, 0), weekday=7) == 0
    # 周日(08-16) → 周日(08-23) → 1
    assert weeks_elapsed("2026-08-16", now=_ts(2026, 8, 23, 12, 0), weekday=7) == 1


def test_weeks_elapsed_invalid_weekday_defaults_monday():
    # 非法 weekday → 默认周一（对齐商店 weekly 示例 weekday:1）
    assert weeks_elapsed("2026-08-12", now=_ts(2026, 8, 17, 12, 0), weekday=99) == 1


# =====================================================================================
# ⑤ advance_cycles（周期推进：day/week/month）
# =====================================================================================
def test_advance_cycles_day():
    assert advance_cycles("2026-08-26", 1, "day") == "2026-08-27"
    assert advance_cycles("2026-08-26", 7, "day") == "2026-09-02"
    assert advance_cycles("2026-08-26", 0, "day") == "2026-08-26"


def test_advance_cycles_week():
    assert advance_cycles("2026-08-26", 1, "week") == "2026-09-02"
    assert advance_cycles("2026-08-26", 2, "week") == "2026-09-09"


def test_advance_cycles_month_clamp():
    # 自然月进位 + 夹取目标月天数（工程补白口径）
    assert advance_cycles("2026-01-31", 1, "month") == "2026-02-28"
    assert advance_cycles("2026-02-28", 1, "month") == "2026-03-28"
    assert advance_cycles("2025-12-31", 1, "month") == "2026-01-31"  # 跨年
    assert advance_cycles("2026-01-31", 2, "month") == "2026-03-31"
    assert advance_cycles("2026-01-15", 1, "month") == "2026-02-15"


def test_advance_cycles_invalid_last_key_passthrough():
    # 非法 last_key → 原样透传（防御）
    assert advance_cycles("garbage", 1, "day") == "garbage"
    assert advance_cycles(None, 1, "day") is None


def test_advance_cycles_unknown_period_raises():
    with pytest.raises(ValueError):
        advance_cycles("2026-08-26", 1, "hour")
    assert PERIODS == ("day", "week", "month")


# =====================================================================================
# ⑥ is_window_open once 时间窗（未开门 / 自动下架；商店 §七 / 签到 §2.2）
# =====================================================================================
def test_window_open_mid_window():
    start, end = "2026-09-01 00:00", "2026-09-07 23:59"
    assert is_window_open(start, end, now=_ts(2026, 9, 4, 12, 0)) == WINDOW_OPEN


def test_window_not_started():
    # start 未到 → 未开门（商店「这家店还没开门」/ 签到自动停用）
    start, end = "2026-09-01 00:00", "2026-09-07 23:59"
    assert is_window_open(start, end, now=_ts(2026, 8, 31, 23, 59, 59)) == WINDOW_NOT_STARTED


def test_window_start_inclusive():
    assert is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=_ts(2026, 9, 1, 0, 0)) == WINDOW_OPEN


def test_window_expired():
    # end 已过 → 自动下架（签到过期停用）
    start, end = "2026-09-01 00:00", "2026-09-07 23:59"
    assert is_window_open(start, end, now=_ts(2026, 9, 8, 0, 0)) == WINDOW_EXPIRED


def test_window_end_inclusive():
    assert is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=_ts(2026, 9, 7, 23, 59)) == WINDOW_OPEN
    assert is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=_ts(2026, 9, 7, 23, 59) + 1) == WINDOW_EXPIRED


def test_window_date_only_string():
    # 日期串缺省时间 = 当日 00:00（闭区间 [start, end]）
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 8, 31, 23, 59)) == WINDOW_NOT_STARTED
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 9, 1, 0, 0)) == WINDOW_OPEN
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 9, 6, 23, 59)) == WINDOW_OPEN
    # end 为日期串 → 截止于当日 00:00：09-07 00:00 整仍 open，其后 expired
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 9, 7, 0, 0)) == WINDOW_OPEN
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 9, 7, 0, 0, 1)) == WINDOW_EXPIRED
    assert is_window_open("2026-09-01", "2026-09-07", now=_ts(2026, 9, 8)) == WINDOW_EXPIRED


def test_window_missing_bounds_always_open():
    # start/end 缺省 → 常驻开放（不崩溃）
    assert is_window_open(None, None, now=_ts(2026, 8, 26, 12, 0)) == WINDOW_OPEN
    assert is_window_open("2026-09-01 00:00", None, now=_ts(2026, 9, 4, 12, 0)) == WINDOW_OPEN
    assert is_window_open(None, "2026-09-07 23:59", now=_ts(2026, 9, 4, 12, 0)) == WINDOW_OPEN
    # 单边窗口：只有 start → 未开门/开放两态
    assert is_window_open("2026-09-01 00:00", None, now=_ts(2026, 8, 26, 12, 0)) == WINDOW_NOT_STARTED


def test_window_invalid_bounds_always_open():
    # 非法时间串 → 视为常驻开放（防御，不崩溃）
    assert is_window_open("not-a-time", "also-bad", now=_ts(2026, 8, 26, 12, 0)) == WINDOW_OPEN
    assert is_window_open("2026-13-99 25:00", "2026-09-07 23:59", now=_ts(2026, 8, 26, 12, 0)) == WINDOW_OPEN


def test_window_requires_int_or_none_now():
    # now 缺省 = 当前（纯函数：注入相同 now 必同值）
    now = _ts(2026, 9, 4, 12, 0)
    assert is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=now) == WINDOW_OPEN
    assert is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=now) == \
        is_window_open("2026-09-01 00:00", "2026-09-07 23:59", now=now)


# =====================================================================================
# ⑦ normalize_hhmm / resolve_refresh_time 配置口径
# =====================================================================================
def test_normalize_hhmm_variants():
    assert normalize_hhmm("05:00") == "05:00"
    assert normalize_hhmm("5") == "05:00"
    assert normalize_hhmm("5:30") == "05:30"
    assert normalize_hhmm(5) == "05:00"
    assert normalize_hhmm(23) == "23:00"
    assert normalize_hhmm(0) == "00:00"
    assert normalize_hhmm(None) == DEFAULT_REFRESH_TIME
    assert normalize_hhmm("05:30:00") == DEFAULT_REFRESH_TIME  # 秒级非法
    assert normalize_hhmm(" 07 : 15 ") == "07:15"


def test_resolve_refresh_time_default_and_custom():
    assert resolve_refresh_time(None) == DEFAULT_REFRESH_TIME
    assert resolve_refresh_time({}) == DEFAULT_REFRESH_TIME
    assert resolve_refresh_time({"refresh_time": "12:00"}) == "12:00"
    assert resolve_refresh_time({"refresh_time": 20}) == "20:00"


def test_today_of_cfg_none_default():
    # cfg 缺省 → 默认 05:00（消费方零配置调用不崩溃）
    assert today_of(now=_ts(2026, 8, 26, 3, 30))["today"] == "2026-08-25"
    assert today_of(now=_ts(2026, 8, 26, 5, 0))["today"] == "2026-08-26"
