"""M36 /时间 /天气 查询数据组装单测（M3 批次1·路F）。

依据：细化_2a4a_时间引擎（§1.1 周期注册表 4+5 枚举 / §1.3 可配项 / §2.4 倒计时展示）
      + 规划_路2a_地图副本.md M36（/时间 /天气：季节距下次 X 天 / 时段距下次 X 分钟 /
      天气距下次 X 分钟；生效池标注覆盖/默认）
      + m3_shared_contract §5.3（IF07 倒计时数据源）。

手算基准（默认配置 7 天/季 · 60 分/段 · 60 分/抽，ANCHOR=2000-01-01 00:00 UTC+8=946656000）：
  2026-08-16 00:00 UTC+8 → diff=840153600s=9724 天整：season=summer、remaining=518400s=6 天、
  next=autumn；period=noon、remaining=3600s=60 分钟（整点边界）、next=dusk；weather_tick=233376、
  天气 remaining=60 分钟。
"""
from __future__ import annotations

import datetime
from typing import List, Mapping

from qbot_rpg.engine.time_query import (
    DEFAULT_WEATHER_NAMES,
    PERIOD_NAMES,
    SEASON_NAMES,
    period_status,
    season_status,
    weather_name,
    weather_status,
)
from qbot_rpg.engine.worldtime import DEFAULT_POOL, PERIODS, SEASONS

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0, ss: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（与引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, ss, tzinfo=_TZ_UTC8).timestamp())


def default_cfg() -> dict:
    """默认 time_cycle 配置（细化_2a4a §1.3 拍板值；对齐 test_time_cycle_config）。"""
    return {"time_cycle": {
        "enabled": True,
        "season": {"season_days": 7},
        "period": {"period_minutes": 60},
        "weather": {"weather_minutes": 60, "default_pool": list(DEFAULT_POOL)},
        "broadcast": {"enabled": False, "mode": "lazy"},
    }}


# -------------------------------------------------------------------------------------
# 中文名映射（季节 4 值 + 时段 5 值固定枚举，细化_2a4a §1.1）
# -------------------------------------------------------------------------------------
def test_season_names_map_all_four_seasons():
    assert set(SEASON_NAMES.keys()) == set(SEASONS)
    assert set(SEASON_NAMES.values()) == {"春", "夏", "秋", "冬"}
    assert SEASON_NAMES == {"spring": "春", "summer": "夏", "autumn": "秋", "winter": "冬"}


def test_period_names_map_all_five_periods():
    assert set(PERIOD_NAMES.keys()) == set(PERIODS)
    assert set(PERIOD_NAMES.values()) == {"晨", "午", "昏", "夜", "午夜"}
    assert PERIOD_NAMES["dawn"] == "晨" and PERIOD_NAMES["midnight"] == "午夜"


def test_weather_name_registered_and_fallback():
    # 已登记默认键 → 中文；内容包自定义未登记键 → 回退原键（不崩溃）
    assert weather_name("clear") == "晴"
    assert weather_name("storm") == "雷雨"
    assert weather_name("snow") == "snow"
    assert weather_name(None) is None
    assert set(DEFAULT_WEATHER_NAMES.keys()) == set(DEFAULT_POOL)


# -------------------------------------------------------------------------------------
# season_status：倒计时按天折算（跨日/整点边界）
# -------------------------------------------------------------------------------------
def test_season_status_20260816_hand_calc():
    # 换季次日：剩 518400s = 6 天整；summer → autumn
    st = season_status(_ts(2026, 8, 16), default_cfg())
    assert st == {"key": "summer", "name": "夏", "remaining_days": 6, "next_key": "autumn"}


def test_season_status_anchor_full_seven_days():
    # 锚点零点：整一个季节周期 7 天；spring → summer
    st = season_status(_ts(2000, 1, 1), default_cfg())
    assert st == {"key": "spring", "name": "春", "remaining_days": 7, "next_key": "summer"}


def test_season_status_cross_day_boundary():
    # 锚点 +3 天 12 小时 → 剩 3 天 12 小时 → 整天下取 3 天（小时余量本层丢弃）
    st = season_status(_ts(2000, 1, 1) + 3 * 86400 + 12 * 3600, default_cfg())
    assert st["key"] == "spring" and st["remaining_days"] == 3


def test_season_status_just_before_boundary_zero_days():
    # 换季前 1 秒：剩 1s → 折算 0 天（仍在 spring，下一秒才变 summer）
    st = season_status(_ts(2000, 1, 1) + 7 * 86400 - 1, default_cfg())
    assert st == {"key": "spring", "name": "春", "remaining_days": 0, "next_key": "summer"}


def test_season_status_rollover_winter_to_spring():
    # 2000-01-22 00:00 = 21 天 → winter（floor(21/7)%4=3），next=spring，剩 7 天
    st = season_status(_ts(2000, 1, 22), default_cfg())
    assert st == {"key": "winter", "name": "冬", "remaining_days": 7, "next_key": "spring"}


# -------------------------------------------------------------------------------------
# period_status：倒计时按分钟折算（整点/跨小时边界）
# -------------------------------------------------------------------------------------
def test_period_status_20260816_hand_calc():
    # 恰逢整点边界：剩 3600s = 60 分钟；noon → dusk
    st = period_status(_ts(2026, 8, 16), default_cfg())
    assert st == {"key": "noon", "name": "午", "remaining_minutes": 60, "next_key": "dusk"}


def test_period_status_mid_period():
    # 锚点 +30 分 → 剩 30 分钟；dawn → noon
    st = period_status(_ts(2000, 1, 1, 0, 30), default_cfg())
    assert st == {"key": "dawn", "name": "晨", "remaining_minutes": 30, "next_key": "noon"}


def test_period_status_midnight_rollover_to_dawn():
    # 04:00 → midnight（floor(240/60)%5=4），next=dawn，剩整一个周期 60 分钟
    st = period_status(_ts(2000, 1, 1, 4), default_cfg())
    assert st == {"key": "midnight", "name": "午夜", "remaining_minutes": 60, "next_key": "dawn"}


def test_period_status_cross_hour_boundary():
    # 锚点 +90 分：diff=5400 → noon（floor(5400/3600)%5=1），剩 3600−1800=1800s=30 分钟
    st = period_status(_ts(2000, 1, 1, 1, 30), default_cfg())
    assert st == {"key": "noon", "name": "午", "remaining_minutes": 30, "next_key": "dusk"}


# -------------------------------------------------------------------------------------
# weather_status：pool_label 两种 + key 取值 + 倒计时
# -------------------------------------------------------------------------------------
def test_weather_status_coverage_pool_label():
    # 覆盖池（≠ 默认池）→ 「使用本图天气池」；key 按 pool_keys[0]（IF08 抽签落地前补白）
    st = weather_status("mist_forest", ["fog", "rain"], _ts(2026, 8, 16), default_cfg())
    assert st == {"key": "fog", "name": "雾", "remaining_minutes": 60, "pool_label": "使用本图天气池"}


def test_weather_status_default_pool_label():
    # 生效池 == 配置默认池 → 「默认池」；key=clear、中文=晴
    st = weather_status("plains", list(DEFAULT_POOL), _ts(2026, 8, 16), default_cfg())
    assert st == {"key": "clear", "name": "晴", "remaining_minutes": 60, "pool_label": "默认池"}


def test_weather_status_unknown_key_fallback_name():
    # 内容包自定义键（未登记）→ 中文名回退原键，仍判为覆盖池
    st = weather_status("snow_map", ["snow", "blizzard"], _ts(2026, 8, 16), default_cfg())
    assert st["key"] == "snow" and st["name"] == "snow"
    assert st["pool_label"] == "使用本图天气池"


def test_weather_status_empty_pool_falls_back_default():
    # 空/缺省生效池（IF05 map_pool 语义）→ 回退默认池：key=默认池首键、label=默认池
    st = weather_status("plains", [], _ts(2026, 8, 16), default_cfg())
    assert st["key"] == "clear" and st["pool_label"] == "默认池"
    assert weather_status("plains", None, _ts(2026, 8, 16), default_cfg()) == st


def test_weather_status_pool_source_override():
    # 显式来源标注覆盖比较推导（指令层已知地图字段存在性时的精确标注）
    st = weather_status("m1", list(DEFAULT_POOL), _ts(2026, 8, 16), default_cfg(),
                        pool_source="coverage")
    assert st["pool_label"] == "使用本图天气池"
    st2 = weather_status("m2", ["fog"], _ts(2026, 8, 16), default_cfg(), pool_source="default")
    assert st2["pool_label"] == "默认池"


def test_weather_status_remaining_minutes_mid_period():
    # 锚点 +30 分 → 天气剩 30 分钟
    st = weather_status("plains", list(DEFAULT_POOL), _ts(2000, 1, 1, 0, 30), default_cfg())
    assert st["remaining_minutes"] == 30


# -------------------------------------------------------------------------------------
# 配置注入生效（WorldTime(cfg) 构造注入：配置即重排）
# -------------------------------------------------------------------------------------
def test_season_status_cfg_season_days_reconfig():
    # season_days=3：2000-01-13 = 12 天 = 3 天/季×4 季整轮 → 回 spring（默认 7 天配置为 summer）
    cfg = default_cfg()
    cfg["time_cycle"]["season"]["season_days"] = 3
    st = season_status(_ts(2000, 1, 13), cfg)
    assert st == {"key": "spring", "name": "春", "remaining_days": 3, "next_key": "summer"}
    # 同刻默认配置 = summer，证明确实由配置驱动
    assert season_status(_ts(2000, 1, 13), default_cfg())["key"] == "summer"


def test_period_status_cfg_period_minutes_reconfig():
    # period_minutes=45：00:45 = 一个 45 分段 → noon（默认 60 分配置为 dawn）
    cfg = default_cfg()
    cfg["time_cycle"]["period"]["period_minutes"] = 45
    st = period_status(_ts(2000, 1, 1, 0, 45), cfg)
    assert st == {"key": "noon", "name": "午", "remaining_minutes": 45, "next_key": "dusk"}
    assert period_status(_ts(2000, 1, 1, 0, 45), default_cfg())["key"] == "dawn"


def test_weather_status_cfg_default_pool_reconfig():
    # 自定义 default_pool=["fog","rain"]：同键生效池 → 判为默认池、key=fog
    cfg = default_cfg()
    cfg["time_cycle"]["weather"]["default_pool"] = ["fog", "rain"]
    st = weather_status("plains", ["fog", "rain"], _ts(2026, 8, 16), cfg)
    assert st == {"key": "fog", "name": "雾", "remaining_minutes": 60, "pool_label": "默认池"}
    # 同一池在默认配置（默认池=5 键）下应判为覆盖池
    assert weather_status("plains", ["fog", "rain"], _ts(2026, 8, 16),
                          default_cfg())["pool_label"] == "使用本图天气池"


def test_season_period_status_no_cfg_defaults():
    # cfg=None 走默认配置（细化_2a4a §1.3 拍板值），与显式默认配置同值
    assert season_status(_ts(2026, 8, 16)) == season_status(_ts(2026, 8, 16), default_cfg())
    assert period_status(_ts(2026, 8, 16)) == period_status(_ts(2026, 8, 16), default_cfg())


def test_query_functions_are_pure():
    # 纯函数：同刻同参两次调用返回相同 dict（M43 确定性精神）
    now = _ts(2026, 8, 16)
    assert season_status(now, default_cfg()) == season_status(now, default_cfg())
    assert period_status(now, default_cfg()) == period_status(now, default_cfg())
    assert weather_status("plains", list(DEFAULT_POOL), now, default_cfg()) == \
        weather_status("plains", list(DEFAULT_POOL), now, default_cfg())