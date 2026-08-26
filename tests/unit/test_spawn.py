"""M3 批次4·路L（M08 补刷懒计算 + M09 时段/季节出没边界）测试 —— qbot_rpg.world.spawn.SpawnManager。

依据：细化_2a1b §二（刷怪配置 R14-R26）/ §三（时段联动出没判定链 R27-R30）
      + 细化_2a4c §3（出没链路 E1 补刷 / E2 周期边界移除 / E3 刷新计时折算 + S1/S2）
      + m3_shared_contract §2.3（spawn 行七字段 + 出没语义 R16-R22）
      + 实现层规划 M08（补刷 = floor(时间差/间隔) 截断缺口，零定时器）/ M09（限定过滤 + 边界移除）。

测试口径（对齐 test_weather_consumers 风格）：构造输入 → 跑纯函数 → 断言结果。
  - worldtime 一律用 StubTime 注入（season_now/period_now/weather_now 可配置，记录调用）。
  - spawn_rows 双形态（raw dict / SpawnDef）各覆盖一组用例。
  - now 用 ANCHOR 偏移出的具体钟点时间戳（ANCHOR=2000-01-01 00:00:00 UTC+8）。
"""
from __future__ import annotations

import pytest

from qbot_rpg.content.map_models import SpawnDef
from qbot_rpg.engine.worldtime import ANCHOR, WorldTime
from qbot_rpg.world.spawn import SpawnManager

# ---------------------------------------------------------------------------
# 时间锚点（ANCHOR = 2000-01-01 00:00:00 UTC+8；偏移即现实钟点）
# ---------------------------------------------------------------------------
H = 3600
T_2000 = ANCHOR + 20 * H   # 20:00
T_2100 = ANCHOR + 21 * H   # 21:00
T_0500 = ANCHOR + 5 * H    # 05:00（跨夜窗口内）
T_0600 = ANCHOR + 6 * H    # 06:00（跨夜窗口结束点）
T_1200 = ANCHOR + 12 * H   # 12:00
MIN = 60

# ---------------------------------------------------------------------------
# Stub worldtime（注入桩：三周期值可配置；weather_now 记录 map_id）
# ---------------------------------------------------------------------------
class StubTime:
    def __init__(self, season: str = "summer", period: str = "noon",
                 weather: str = "clear") -> None:
        self.season = season
        self.period = period
        self.weather = weather
        self.seen_map_ids: list[str] = []

    def season_now(self, now=None) -> str:
        return self.season

    def period_now(self, now=None) -> str:
        return self.period

    def weather_now(self, map_id: str, now=None) -> str:
        self.seen_map_ids.append(map_id)
        return self.weather


# ---------------------------------------------------------------------------
# spawn 行夹具（契约 §2.3 七字段子集）
# ---------------------------------------------------------------------------
ROW_ALL_DAY = {"enemy": "野狼", "count": 3, "respawn_minutes": 10}  # 全天全年
ROW_NIGHT = {"enemy": "幽灵", "count": 5, "respawn_minutes": 20,
             "periods": ["night", "midnight"]}
ROW_AUTUMN = {"enemy": "妖狐", "count": 2, "respawn_minutes": 30,
              "seasons": ["autumn", "winter"]}
ROW_NIGHT_WINDOW = {"enemy": "夜枭", "count": 4, "respawn_minutes": 15,
                    "active_time": {"from": "20:00", "to": "06:00"},
                    "periods": ["night"]}
ROW_STACK = {"enemy": "赤目", "count": 2, "respawn_minutes": 10,
             "active_time": {"from": "20:00", "to": "06:00"},
             "seasons": ["autumn"], "periods": ["night"]}
ROW_WEATHER = {"enemy": "雷兽", "count": 2, "respawn_minutes": 10,
               "weather_weights": {"storm": 0, "rain": 2}}
ROW_FOG_WOLF = {"enemy": "雾狼", "count": 2, "respawn_minutes": 10,
                "weather_weights": {"fog": 2}}  # clear 下权重未配 → 默认 1
ROW_NO_COUNT = {"enemy": "史莱姆", "respawn_minutes": 5}  # count 缺省 → 1

_NIGHT_ALIVE = {"alive_count": {"幽灵": 2}}
_NIGHT_KILL_5M = {"last_kill_time": {"幽灵": T_1200 - 5 * MIN}}


def _mgr(rows, wt=None) -> SpawnManager:
    return SpawnManager(rows, wt)


# ===========================================================================
# filter_eligible（S1 出没判定：active_time ∩ seasons ∩ periods AND 叠加）
# ===========================================================================
def test_filter_all_day_unconstrained() -> None:
    mgr = _mgr([ROW_ALL_DAY], StubTime())
    assert mgr.filter_eligible(ROW_ALL_DAY, T_1200) is True


def test_filter_seasons_hit_and_miss() -> None:
    mgr = _mgr([ROW_AUTUMN], StubTime())
    assert mgr.filter_eligible(ROW_AUTUMN, T_1200) is False  # 夏季 → 不出没（TC-11）
    mgr2 = _mgr([ROW_AUTUMN], StubTime(season="autumn"))
    assert mgr2.filter_eligible(ROW_AUTUMN, T_1200) is True


def test_filter_periods_hit_and_miss() -> None:
    mgr = _mgr([ROW_NIGHT], StubTime())
    assert mgr.filter_eligible(ROW_NIGHT, T_1200) is False  # 午时 → 不出没（TC-10）
    mgr2 = _mgr([ROW_NIGHT], StubTime(period="night"))
    assert mgr2.filter_eligible(ROW_NIGHT, T_1200) is True


def test_filter_active_time_window_hit_and_miss() -> None:
    mgr = _mgr([ROW_NIGHT_WINDOW], StubTime(period="night"))
    assert mgr.filter_eligible(ROW_NIGHT_WINDOW, T_2100) is True   # 21:00 在 20-06 内
    assert mgr.filter_eligible(ROW_NIGHT_WINDOW, T_1200) is False  # 12:00 在窗外


def test_filter_active_time_cross_midnight_boundaries() -> None:
    # 跨夜半开 [20:00, 06:00)：from 含、to 不含（补白 3）
    mgr = _mgr([ROW_NIGHT_WINDOW], StubTime(period="night"))
    assert mgr.filter_eligible(ROW_NIGHT_WINDOW, T_2000) is True  # 起点含
    assert mgr.filter_eligible(ROW_NIGHT_WINDOW, T_0500) is True  # 跨夜段内
    assert mgr.filter_eligible(ROW_NIGHT_WINDOW, T_0600) is False  # 终点不含（窗口已结束）


def test_filter_and_stacking_tc16() -> None:
    # active_time + seasons + periods 全 AND：半满足 → 不出现（TC-16）
    mgr = _mgr([ROW_STACK], StubTime(period="night"))  # summer + night，季节不满足
    assert mgr.filter_eligible(ROW_STACK, T_2100) is False  # 季节 miss
    mgr2 = _mgr([ROW_STACK], StubTime(season="autumn"))  # autumn + noon，时段不满足
    assert mgr2.filter_eligible(ROW_STACK, T_2100) is False  # 时段 miss
    mgr3 = _mgr([ROW_STACK], StubTime(season="autumn", period="night"))
    assert mgr3.filter_eligible(ROW_STACK, T_2100) is True  # 三条件全满足


def test_filter_empty_constraints_unconstrained() -> None:
    # seasons/periods/active_time 全空 = 全年全天恒真（R27）
    mgr = _mgr([ROW_ALL_DAY], StubTime(season="winter", period="midnight"))
    assert mgr.filter_eligible(ROW_ALL_DAY, T_1200) is True


def test_filter_bad_row_failsafe() -> None:
    mgr = _mgr([ROW_ALL_DAY], StubTime())
    assert mgr.filter_eligible(None, T_1200) is False
    assert mgr.filter_eligible("junk", T_1200) is False
    assert mgr.filter_eligible(12345, T_1200) is False


def test_filter_accepts_spawndef_and_raw_dict() -> None:
    mgr = _mgr([], StubTime(period="night"))
    as_def = SpawnDef.from_entry(ROW_NIGHT, 0)
    assert mgr.filter_eligible(as_def, T_1200) is True   # SpawnDef 形态
    assert mgr.filter_eligible(ROW_NIGHT, T_1200) is True  # raw dict 同判


def test_filter_no_worldtime_degrades_to_active_time_only() -> None:
    # 缺 worldtime → seasons/periods 退化为不限（IF01 关同口径：仅 active_time）
    mgr = _mgr([ROW_NIGHT], None)
    assert mgr.filter_eligible(ROW_NIGHT, T_1200) is True
    mgr2 = _mgr([ROW_NIGHT_WINDOW], None)
    assert mgr2.filter_eligible(ROW_NIGHT_WINDOW, T_1200) is False  # 仅 active_time 拦


def test_filter_real_worldtime_integration() -> None:
    # 注入真实 WorldTime：ANCHOR 时刻 = 春季 · 晨（IF02/IF03）
    wt = WorldTime({})
    assert wt.season_now(ANCHOR) == "spring"
    assert wt.period_now(ANCHOR) == "dawn"
    mgr = _mgr([ROW_AUTUMN], wt)
    assert mgr.filter_eligible(ROW_AUTUMN, ANCHOR) is False  # 春季 → 妖狐(秋/冬)不出现
    mgr2 = _mgr([{"enemy": "x", "count": 1, "respawn_minutes": 5,
                  "seasons": ["spring"], "periods": ["dawn"]}], wt)
    assert mgr2.filter_eligible({"enemy": "x", "count": 1, "respawn_minutes": 5,
                                 "seasons": ["spring"], "periods": ["dawn"]}, ANCHOR) is True


# ===========================================================================
# initial_spawn（M07/M09：filter_eligible 过滤 → spawn_count=count 上限）
# ===========================================================================
def test_initial_spawn_filters_eligibles() -> None:
    rows = [ROW_ALL_DAY, ROW_NIGHT, ROW_AUTUMN]
    mgr = _mgr(rows, StubTime())  # summer + noon
    out = mgr.initial_spawn(T_1200)
    assert [d["enemy"] for d in out] == ["野狼"]  # 仅全天全年行出没
    assert out[0]["spawn_count"] == 3  # count 上限


def test_initial_spawn_night_rows() -> None:
    rows = [ROW_ALL_DAY, ROW_NIGHT, ROW_AUTUMN]
    mgr = _mgr(rows, StubTime(period="night"))
    out = mgr.initial_spawn(T_1200)
    assert [d["enemy"] for d in out] == ["野狼", "幽灵"]
    assert out[1]["spawn_count"] == 5


def test_initial_spawn_active_time_gate() -> None:
    mgr = _mgr([ROW_NIGHT_WINDOW], StubTime(period="night"))
    assert [d["enemy"] for d in mgr.initial_spawn(T_2100)] == ["夜枭"]
    assert mgr.initial_spawn(T_1200) == []  # 窗外 → 不出没


def test_initial_spawn_default_count() -> None:
    mgr = _mgr([ROW_NO_COUNT], StubTime())
    out = mgr.initial_spawn(T_1200)
    assert out[0]["spawn_count"] == 1  # count 缺省 1（契约 §2.3 补白）
    assert out[0]["count"] is None


def test_initial_spawn_empty_rows() -> None:
    assert _mgr([], StubTime()).initial_spawn(T_1200) == []


# ===========================================================================
# refresh（E1/M08 懒补刷：比较 last_kill_time + respawn_interval vs now 补足 count）
# ===========================================================================
def test_refresh_no_kill_fills_to_cap() -> None:
    mgr = _mgr([ROW_ALL_DAY], StubTime())
    out = mgr.refresh("map_1", T_1200, {})
    assert [d["enemy"] for d in out] == ["野狼"]
    assert out[0]["spawn_count"] == 3  # 无击杀记录 → 全量补足 count 上限


def test_refresh_after_kill_not_yet_respawn() -> None:
    # 击杀后未到 respawn 间隔 → 不补（M08/TC-09）
    state = {"last_kill_time": {"野狼": T_1200 - 5 * MIN}}
    out = _mgr([ROW_ALL_DAY], StubTime()).refresh("map_1", T_1200, state)
    assert out == []


def test_refresh_after_kill_refills_floor() -> None:
    # 25 分钟 / 10 分钟间隔 = floor 2 只（TC-09：补刷 = floor(时间差/间隔)）
    state = {"last_kill_time": {"野狼": T_1200 - 25 * MIN}}
    out = _mgr([ROW_ALL_DAY], StubTime()).refresh("map_1", T_1200, state)
    assert [d["enemy"] for d in out] == ["野狼"]
    assert out[0]["spawn_count"] == 2


def test_refresh_gap_caps_refill() -> None:
    # 缺口截断：差 25 分钟可补 2 只，但存活 2/上限 3 → 只补 1（M08「截断到缺口」）
    state = {"last_kill_time": {"野狼": T_1200 - 25 * MIN},
             "alive_count": {"野狼": 2}}
    out = _mgr([ROW_ALL_DAY], StubTime()).refresh("map_1", T_1200, state)
    assert out[0]["spawn_count"] == 1


def test_refresh_at_full_no_refill() -> None:
    # 存活 == count 上限 → 不补（TC-08 count 上限）
    state = {"alive_count": {"野狼": 3}}
    assert _mgr([ROW_ALL_DAY], StubTime()).refresh("map_1", T_1200, state) == []


def test_refresh_interval_exact_boundary() -> None:
    # elapsed == 间隔整点 → floor(1) = 1 只（补白 3 边界口径：到点即补 1）
    state = {"last_kill_time": {"野狼": T_1200 - 10 * MIN}}
    out = _mgr([ROW_ALL_DAY], StubTime()).refresh("map_1", T_1200, state)
    assert out[0]["spawn_count"] == 1


def test_refresh_weather_speedup_tc13() -> None:
    # 雨天权重 2 → 有效间隔 = 10/2 = 5 分钟；25 分钟 → floor(25/5)=5，截断到缺口 2（TC-13）
    mgr = _mgr([ROW_WEATHER], StubTime(weather="rain"))
    state = {"last_kill_time": {"雷兽": T_1200 - 25 * MIN}}
    out = mgr.refresh("map_1", T_1200, state)
    assert [d["enemy"] for d in out] == ["雷兽"]
    assert out[0]["spawn_count"] == 2


def test_refresh_weather_zero_no_refill_tc14() -> None:
    # 雷雨天权重 0 = 该天气不刷（R26/E3/TC-14）：即使离线很久也不补
    mgr = _mgr([ROW_WEATHER], StubTime(weather="storm"))
    state = {"last_kill_time": {"雷兽": T_1200 - 120 * MIN}}
    assert mgr.refresh("map_1", T_1200, state) == []


def test_refresh_weather_unconfigured_default_one() -> None:
    # 当前天气未配权重 → 默认 1：间隔 10 分钟，15 分钟 → 补 1（TC-13 缺省口径）
    mgr = _mgr([ROW_FOG_WOLF], StubTime(weather="clear"))
    state = {"last_kill_time": {"雾狼": T_1200 - 15 * MIN}}
    out = mgr.refresh("map_1", T_1200, state)
    assert out[0]["spawn_count"] == 1


def test_refresh_ineligible_row_skipped_m09() -> None:
    # 非限定时段 → 该行不补刷（M09「非限定季节/时段不刷该怪」）
    mgr = _mgr([ROW_NIGHT], StubTime())  # noon
    state = {"last_kill_time": {"幽灵": T_1200 - 60 * MIN}}
    assert mgr.refresh("map_1", T_1200, state) == []


def test_refresh_active_time_blocks_refill() -> None:
    # active_time 窗外 → 该行不补刷（现实钟点层，R20 AND 叠加）
    mgr = _mgr([ROW_NIGHT_WINDOW], StubTime(period="night"))
    state = {"last_kill_time": {"夜枭": T_1200 - 60 * MIN}}
    assert mgr.refresh("map_1", T_1200, state) == []


def test_refresh_spawndef_input_equivalent() -> None:
    # SpawnDef 输入与 raw dict 同语义（双形态兼容）
    rows_def = [SpawnDef.from_entry(ROW_ALL_DAY, 0)]
    state = {"last_kill_time": {"野狼": T_1200 - 25 * MIN}}
    out = _mgr(rows_def, StubTime()).refresh("map_1", T_1200, state)
    assert out[0]["spawn_count"] == 2


def test_refresh_world_state_garbage_failsafe() -> None:
    mgr = _mgr([ROW_ALL_DAY], StubTime())
    assert mgr.refresh("map_1", T_1200, None)[0]["spawn_count"] == 3
    assert mgr.refresh("map_1", T_1200, "junk")[0]["spawn_count"] == 3
    assert mgr.refresh("map_1", T_1200, {"last_kill_time": "junk",
                                         "alive_count": "junk"})[0]["spawn_count"] == 3


def test_refresh_passes_map_id_to_weather() -> None:
    wt = StubTime(weather="rain")
    _mgr([ROW_WEATHER], wt).refresh("map_7", T_1200, {})
    assert wt.seen_map_ids == ["map_7"]  # weather 值按玩家所在图注入（IF04 上下文绑定）


# ===========================================================================
# zone_expire_removal（E2 周期边界：季节/时段结束 → 移除「对方逃跑了」）
# ===========================================================================
def test_removal_period_ended() -> None:
    # 夜→晨：限定时段结束 → 场上该行移除（R17/TC-12）
    mgr = _mgr([ROW_NIGHT], StubTime(period="dawn"))
    removed = mgr.zone_expire_removal([ROW_NIGHT], T_1200, _NIGHT_ALIVE)
    assert removed == ["幽灵"]  # 行 key = enemy，供「幽灵逃跑了」文案


def test_removal_still_eligible_kept() -> None:
    # 仍处于限定时段 → 不移除
    mgr = _mgr([ROW_NIGHT], StubTime(period="night"))
    assert mgr.zone_expire_removal([ROW_NIGHT], T_1200, _NIGHT_ALIVE) == []


def test_removal_season_ended() -> None:
    # 秋→夏：限定季节结束 → 移除（R17 季节边界同理）
    mgr = _mgr([ROW_AUTUMN], StubTime(season="summer"))
    removed = mgr.zone_expire_removal([ROW_AUTUMN], T_1200, {"alive_count": {"妖狐": 1}})
    assert removed == ["妖狐"]


def test_removal_no_monsters_no_removal() -> None:
    # 场上无该行怪（alive_count 缺键/为 0）→ 不产出移除
    mgr = _mgr([ROW_NIGHT], StubTime(period="dawn"))
    assert mgr.zone_expire_removal([ROW_NIGHT], T_1200, {}) == []
    assert mgr.zone_expire_removal([ROW_NIGHT], T_1200,
                                   {"alive_count": {"幽灵": 0}}) == []


def test_removal_weather_zero_does_not_remove_r30() -> None:
    # 雷雨天权重 0 → 已在场怪不驱逐（R30/TC-14：天气只影响刷新，不驱逐在场）
    mgr = _mgr([ROW_WEATHER], StubTime(weather="storm"))
    assert mgr.zone_expire_removal([ROW_WEATHER], T_1200,
                                   {"alive_count": {"雷兽": 1}}) == []


def test_removal_active_time_end_does_not_remove() -> None:
    # 现实钟点窗口结束（12:00）→ 不触发移除（E2 只认季节/时段边界；2a4c §1.0 现实钟点层保留）
    mgr = _mgr([ROW_NIGHT_WINDOW], StubTime(period="night"))
    assert mgr.zone_expire_removal([ROW_NIGHT_WINDOW], T_1200,
                                   {"alive_count": {"夜枭": 1}}) == []


def test_removal_uses_passed_rows() -> None:
    # 传入行集优先于构造注入行集（调用方可按图传入全部行）
    mgr = _mgr([ROW_ALL_DAY], StubTime(period="dawn"))
    removed = mgr.zone_expire_removal([ROW_NIGHT, ROW_AUTUMN], T_1200,
                                      {"alive_count": {"幽灵": 1, "妖狐": 1}})
    assert removed == ["幽灵", "妖狐"]  # 行序输出；野狼（不在传入行）不受影响


def test_removal_uses_instance_rows_when_none() -> None:
    mgr = _mgr([ROW_NIGHT], StubTime(period="dawn"))
    assert mgr.zone_expire_removal(None, T_1200, _NIGHT_ALIVE) == ["幽灵"]


def test_removal_world_state_garbage_failsafe() -> None:
    mgr = _mgr([ROW_NIGHT], StubTime(period="dawn"))
    assert mgr.zone_expire_removal([ROW_NIGHT], T_1200, None) == []
    assert mgr.zone_expire_removal([ROW_NIGHT], T_1200, "junk") == []


def test_removal_mixed_eligible_and_expired() -> None:
    # 同图混合：仍在限定时段的不移除、已过时段的移除（一次调用给出全部「逃跑」行）
    rows = [ROW_NIGHT, ROW_AUTUMN]
    wt = StubTime(period="night")  # 幽灵(night) 仍出没；妖狐(秋/冬) 夏季已过
    removed = _mgr(rows, wt).zone_expire_removal(
        rows, T_1200, {"alive_count": {"幽灵": 2, "妖狐": 1}})
    assert removed == ["妖狐"]
