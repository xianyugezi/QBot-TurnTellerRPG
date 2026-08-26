"""time_cycle 配置 + 时间引擎骨架单测（M3 批次0·路C · M31）。

依据：细化_2a4a_时间引擎 §1.3（可配项）/§二（锚点整除公式）/§六（TC-01~04 整除推进、TC-12/13 校验）
      + 细化_2a4c_时间天气接口 §六（TC-01/02/07/08 查询与倒计时）
      + m3_shared_contract §5（5.2 time_cycle 段 / 5.3 IF01~IF07 / 锚点公式）。

手算基准（默认配置 7 天/季 · 60 分/段 · 60 分/抽，ANCHOR=2000-01-01 00:00 UTC+8=946656000）：
  2026-08-16 00:00 UTC+8 → diff=840153600s=9724 天整 → season_idx=floor(9724/7)%4=1389%4=1 夏、
  period_idx=floor(9724×24)%5=233376%5=1 午、weather_tick=233376（不取模）、季节倒计时 518400s、
  时段/天气倒计时 3600s（恰逢整点边界）。
"""
from __future__ import annotations

import datetime
from typing import List

import pytest

from qbot_rpg.engine.worldtime import (
    ANCHOR,
    DEFAULT_POOL,
    PERIODS,
    SEASONS,
    WorldTime,
    validate_time_cycle,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


def default_cfg() -> dict:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值）。"""
    return {"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }}


class _Reporter:
    """与 content/validator.py `_Checker` 同签名的收集器（_err/_warn 风格）。"""

    def __init__(self) -> None:
        self.errors: List[dict] = []
        self.warnings: List[dict] = []

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def _warn(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


# -------------------------------------------------------------------------------------
# IF01 总开关
# -------------------------------------------------------------------------------------
def test_is_enabled_default_true():
    assert WorldTime({}).is_enabled() is True
    assert WorldTime(None).is_enabled() is True
    assert WorldTime().is_enabled() is True


def test_is_enabled_false_when_configured_off():
    wt = WorldTime({"time_cycle": {"enabled": False}})
    assert wt.is_enabled() is False


def test_is_enabled_true_when_configured_on():
    assert WorldTime(default_cfg()).is_enabled() is True


def test_is_enabled_bad_value_falls_back_true():
    # 坏配置（validator 红拦）→ 引擎惰性回退默认 true，不崩溃
    assert WorldTime({"time_cycle": {"enabled": "yes"}}).is_enabled() is True


# -------------------------------------------------------------------------------------
# IF02/IF03 查询（默认配置 · 手算值）
# -------------------------------------------------------------------------------------
def test_season_now_anchor_is_spring():
    assert WorldTime(default_cfg()).season_now(_ts(2000, 1, 1)) == "spring"


def test_season_now_20260816_is_summer():
    # 手算：diff=9724 天，floor(9724/7)%4 = 1389%4 = 1 → summer（细化_2a4c TC-01：2026-08-16 为夏）
    assert WorldTime(default_cfg()).season_now(_ts(2026, 8, 16)) == "summer"


def test_season_now_20000122_is_winter():
    # 细化_2a4a TC-02：floor(21/7)%4=3 → winter
    assert WorldTime(default_cfg()).season_now(_ts(2000, 1, 22)) == "winter"


def test_period_now_anchor_is_dawn():
    assert WorldTime(default_cfg()).period_now(_ts(2000, 1, 1)) == "dawn"


def test_period_now_20260816_is_noon():
    # 手算：floor(9724×24)%5 = 233376%5 = 1 → noon
    assert WorldTime(default_cfg()).period_now(_ts(2026, 8, 16)) == "noon"


def test_period_now_midnight_then_dawn_rollover():
    # 细化_2a4a TC-03：04:00 → floor(240/60)%5=4 midnight；05:00 归 0 → dawn
    wt = WorldTime(default_cfg())
    assert wt.period_now(_ts(2000, 1, 1, 4)) == "midnight"
    assert wt.period_now(_ts(2000, 1, 1, 5)) == "dawn"


# -------------------------------------------------------------------------------------
# IF06 cycle_tick 手算一致（含锚点前负数 diff / 大时间戳）
# -------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "now,season,period,weather",
    [
        (_ts(2000, 1, 1), 0, 0, 0),                 # 锚点零点（TC-01）
        (_ts(2000, 1, 1, 1), 0, 1, 1),              # TC-04：01:00 weather_tick=1
        (_ts(2000, 1, 1, 4), 0, 4, 4),
        (_ts(2000, 1, 1, 5), 0, 0, 5),
        (_ts(2000, 1, 22), 3, 4, 504),              # TC-02：winter（21 天边界）
        (_ts(2000, 1, 29), 0, 2, 672),              # 28 天 = 4 季整轮 → 回 spring（%4）
        (_ts(2026, 8, 16), 1, 1, 233376),           # 手算基准：夏/午/tick 233376
        (_ts(2030, 12, 31, 23, 59, 59), 1, 1, 271751),  # 大时间戳跨年不溢出（手算见下）
    ],
)
def test_cycle_tick_hand_calc(now, season, period, weather):
    wt = WorldTime(default_cfg())
    assert wt.cycle_tick("season", now) == season
    assert wt.cycle_tick("period", now) == period
    assert wt.cycle_tick("weather", now) == weather


def test_cycle_tick_2030_hand_calc_rigorous():
    # 2030-12-31 23:59:59 UTC+8：diff=978307199s，逐项与公式 floor 对照
    wt = WorldTime(default_cfg())
    now = _ts(2030, 12, 31, 23, 59, 59)
    diff = now - ANCHOR
    assert diff == 978307199
    assert wt.cycle_tick("season", now) == (diff // (7 * 86400)) % 4 == 1
    assert wt.cycle_tick("period", now) == (diff // (60 * 60)) % 5 == 1
    assert wt.cycle_tick("weather", now) == diff // (60 * 60) == 271751


def test_cycle_tick_negative_diff_matches_floor_formula():
    # 锚点前（负数 diff）：Python floor 除法 + % 与契约 floor(...)%N 逐字一致
    wt = WorldTime(default_cfg())
    now = ANCHOR - 1
    diff = now - ANCHOR
    assert wt.cycle_tick("season", now) == (diff // (7 * 86400)) % 4
    assert wt.cycle_tick("period", now) == (diff // 3600) % 5
    assert wt.cycle_tick("weather", now) == diff // 3600 == -1


def test_cycle_tick_unknown_kind_raises():
    with pytest.raises(ValueError):
        WorldTime(default_cfg()).cycle_tick("moon", _ts(2026, 8, 16))


def test_cycle_tick_custom_config_reconfig():
    # 配置即重排（细化_2a4a §3.2）：season_days=3 → 周期按新配置推进
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = 3
    wt = WorldTime(cfg)
    # diff=9724 天：floor(9724/3)%4 = 3241%4 = 1 → summer；与 7 天配置索引不同才证明重排生效
    assert wt.cycle_tick("season", _ts(2026, 8, 16)) == 1
    assert wt.season_now(_ts(2026, 8, 16)) == "summer"
    # 3 天整轮 = 12 天：2000-01-13 应回 spring
    assert wt.season_now(_ts(2000, 1, 13)) == "spring"


def test_season_period_index_to_enum_mapping():
    assert SEASONS == ("spring", "summer", "autumn", "winter")
    assert PERIODS == ("dawn", "noon", "dusk", "night", "midnight")


# -------------------------------------------------------------------------------------
# IF07 倒计时（距下次变化秒）
# -------------------------------------------------------------------------------------
def test_time_remaining_season_20260816():
    # 恰逢换季次日：diff%604800 = 86400 → 剩 604800−86400 = 518400s（6 天）
    assert WorldTime(default_cfg()).time_remaining("season", _ts(2026, 8, 16)) == 518400


def test_time_remaining_period_weather_20260816():
    # 恰逢整点边界：diff%3600=0 → 距下次变化整一个周期 3600s
    wt = WorldTime(default_cfg())
    assert wt.time_remaining("period", _ts(2026, 8, 16)) == 3600
    assert wt.time_remaining("weather", _ts(2026, 8, 16)) == 3600


def test_time_remaining_anchor_full_period():
    wt = WorldTime(default_cfg())
    assert wt.time_remaining("season", ANCHOR) == 7 * 86400
    assert wt.time_remaining("period", ANCHOR) == 3600
    assert wt.time_remaining("weather", ANCHOR) == 3600


def test_time_remaining_mid_period():
    # 锚点 +30 分 → 时段/天气剩 30 分=1800s；季节剩 7 天−30 分
    now = ANCHOR + 30 * 60
    wt = WorldTime(default_cfg())
    assert wt.time_remaining("period", now) == 1800
    assert wt.time_remaining("weather", now) == 1800
    assert wt.time_remaining("season", now) == 7 * 86400 - 1800


def test_time_remaining_just_before_anchor():
    # 锚点前 1 秒：diff=−1 → % 得 周期长−1 → 距下次变化 1s（回到锚点整点）
    wt = WorldTime(default_cfg())
    assert wt.time_remaining("season", ANCHOR - 1) == 1
    assert wt.time_remaining("period", ANCHOR - 1) == 1
    assert wt.time_remaining("weather", ANCHOR - 1) == 1


def test_time_remaining_literal_formula_consistency():
    # TC-07：与契约公式 ANCHOR+(floor(diff/周期长)+1)×周期长−now 逐字一致
    wt = WorldTime(default_cfg())
    for now in (_ts(2000, 1, 1, 3, 21), _ts(2026, 8, 16), _ts(2027, 3, 5, 12, 45)):
        diff = now - ANCHOR
        for kind, length in (("season", 7 * 86400), ("period", 3600), ("weather", 3600)):
            expected = ANCHOR + (diff // length + 1) * length - now
            assert wt.time_remaining(kind, now) == expected


# -------------------------------------------------------------------------------------
# validate_time_cycle（V1-V3 + enabled + default_pool；人话报错）
# -------------------------------------------------------------------------------------
def test_validate_valid_config_zero_errors():
    r = _Reporter()
    validate_time_cycle(default_cfg(), r)
    assert r.errors == []


def test_validate_missing_time_cycle_zero_errors():
    r = _Reporter()
    validate_time_cycle({}, r)
    validate_time_cycle({"currencies": []}, r)
    assert r.errors == []


def test_validate_v1_season_days_below_min():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = 0
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V1"
    assert r.errors[0]["detail"]["msg"] == "季节天数要填整数，最少 1 天"


@pytest.mark.parametrize("bad", [0, -3, 1.5, "7", True])
def test_validate_v1_season_days_bad_types(bad):
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = bad
    validate_time_cycle(cfg, r)
    kinds = [e["kind"] for e in r.errors]
    assert "V1" in kinds


def test_validate_v2_period_minutes_below_min():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["period"]["period_minutes"] = 29
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V2"
    assert r.errors[0]["detail"]["msg"] == "时段分钟要填整数，最少 30 分钟"


def test_validate_v2_period_minutes_boundary_30_ok():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["period"]["period_minutes"] = 30
    validate_time_cycle(cfg, r)
    assert r.errors == []


def test_validate_v3_weather_minutes_below_min():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["weather_minutes"] = 29
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V3"
    assert r.errors[0]["detail"]["msg"] == "天气分钟要填整数，最少 30 分钟"


def test_validate_v3_weather_minutes_bad_type():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["weather_minutes"] = 60.0
    validate_time_cycle(cfg, r)
    assert "V3" in [e["kind"] for e in r.errors]


def test_validate_enabled_bool():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["enabled"] = "yes"
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "enabled_type"
    assert "true 或 false" in r.errors[0]["detail"]["msg"]


def test_validate_v4_pool_empty():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["default_pool"] = []
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V4"
    assert r.errors[0]["detail"]["msg"] == "默认天气池至少要 1 种天气"


def test_validate_v4_pool_not_array():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["default_pool"] = "clear"
    validate_time_cycle(cfg, r)
    assert len(r.errors) == 1
    assert r.errors[0]["kind"] == "V4"
    assert r.errors[0]["detail"]["msg"] == "默认天气池要填数组"


def test_validate_v4_pool_dup_keys():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["default_pool"] = ["clear", "rain", "clear"]
    validate_time_cycle(cfg, r)
    dup = [e for e in r.errors if e["kind"] == "V4" and e["detail"].get("rule") == "pool_key_dup"]
    assert len(dup) == 1
    assert dup[0]["detail"]["msg"] == "默认天气池天气键重复了：clear"


def test_validate_v4_pool_non_string_key():
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["default_pool"] = ["clear", 7]
    validate_time_cycle(cfg, r)
    assert any(e["detail"].get("rule") == "pool_key_type" for e in r.errors)


def test_validate_multiple_errors_all_collected():
    # 一次给全（D-01 同口径）：V1 + V2 + V3 + enabled 四错齐发
    r = _Reporter()
    cfg = default_cfg()
    cfg["time_cycle"]["enabled"] = 1
    cfg["time_cycle"]["season"]["season_days"] = 0
    cfg["time_cycle"]["period"]["period_minutes"] = 10
    cfg["time_cycle"]["weather"]["weather_minutes"] = 5
    validate_time_cycle(cfg, r)
    kinds = sorted(e["kind"] for e in r.errors)
    assert kinds == ["V1", "V2", "V3", "enabled_type"]


def test_validate_report_fallback_errors_list():
    # 无 _err 方法的收集器：退化为 .errors 列表 append dict（主 agent 接线兼容）
    report = {"errors": []}
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = 0
    validate_time_cycle(cfg, report)
    assert len(report["errors"]) == 1
    assert report["errors"][0]["kind"] == "V1"


def test_validate_none_settings_no_crash():
    r = _Reporter()
    validate_time_cycle(None, r)  # type: ignore[arg-type]
    assert r.errors == []