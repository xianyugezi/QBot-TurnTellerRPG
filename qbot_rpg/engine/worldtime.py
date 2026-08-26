"""世界时间引擎 —— M3 批次0·路C（M31）时间引擎骨架。

依据：细化_2a4a_时间引擎（§1 三周期注册表 / §1.3 可配项 / §二 锚点整除公式）
      + m3_shared_contract §5（5.1 周期注册表 / 5.2 time_cycle 配置段 / 5.3 IF01~IF07 接口 / 锚点公式）。
本文件 = 细化_2a4c §1.1 公开接口 IF01~IF07 的「游戏周期层」纯函数骨架（本批次交付）：

  IF01 is_enabled()             系统总开关（读 settings.time_cycle.enabled，缺省 true）
  IF02 season_now(now)          季节查询（spring/summer/autumn/winter；0 基 0春 1夏 2秋 3冬）
  IF03 period_now(now)          时段查询（dawn/noon/dusk/night/midnight；0 基 0晨 1午 2昏 3夜 4午夜）
  IF06 cycle_tick(kind, now)    周期索引/节拍（season/period/weather 整除公式，纯函数）
  IF07 time_remaining(kind,now) 距下次变化秒数（/时间 数据源）

锚点（契约 §5.3）：ANCHOR = 2000-01-01 00:00:00 UTC+8；now = UTC+8 秒级时间戳（Unix epoch 秒，
缺省=当前）。season_idx=floor((now−ANCHOR)/(season_days×86400))%4、period_idx=…%5、
weather_tick=…不取模。零定时器、不存历史、随时可重算。

【工程补白】
  - 配置经构造注入：WorldTime(cfg) 接收调用方传入的 settings dict（懒加载，引擎不读文件、不做 IO）；
    周期值一律由锚点公式重算（契约「零定时器、不存历史、随时可重算」）。
  - 配置缺省 = 细化_2a4a §1.3 拍板值：enabled=true / season_days=7 / period_minutes=60 /
    weather_minutes=60；weather.default_pool 默认「5 种」的具体键（clear/cloudy/rain/storm/fog）
    为 2a4a §1.1「如 …」示例落值（定稿未拍死具体键，故标注补白）。
  - 类型/下限合法性交 validate_time_cycle()（本模块）在 load 阶段红拦；引擎对坏配置惰性回退默认
    不崩溃（与契约 IF11 存档「缺补默认多忽略」同口径，字段级缺省）。
  - 校验器收口：validate_time_cycle(settings, report) 供主 agent 接入 check_pack —— report 兼容
    content/validator.py `_Checker._err(module, field, kind, **detail)` 同签名收集器，或带
    `.errors` 列表的收集器（二选一）。

零 NoneBot import（3a R1）；本模块仅标准库。
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import List, Mapping, Optional

__all__ = [
    "ANCHOR",
    "SEASONS",
    "PERIODS",
    "DEFAULT_POOL",
    "WorldTime",
    "validate_time_cycle",
]

# -------------------------------------------------------------------------------------
# 锚点与固定枚举（契约 §5.3 / 细化_2a4a §1.2：季节/时段枚举固定写死，防碎片化）
# -------------------------------------------------------------------------------------
_TZ_UTC8 = timezone(timedelta(hours=8))


def _anchor_epoch() -> int:
    """2000-01-01 00:00:00 UTC+8 → Unix epoch 秒（946656000）。纯算术，无 IO。"""
    return int(datetime(2000, 1, 1, 0, 0, 0, tzinfo=_TZ_UTC8).timestamp())


ANCHOR: int = _anchor_epoch()  # 世界起点 = 春季 · 晨 · 天气第 0 抽

# 季节 4 值固定枚举（0 基索引：0春 1夏 2秋 3冬）
SEASONS: tuple = ("spring", "summer", "autumn", "winter")
# 时段 5 值固定枚举（0 基索引：0晨 1午 2昏 3夜 4午夜）
PERIODS: tuple = ("dawn", "noon", "dusk", "night", "midnight")
# 默认天气池（细化_2a4a §1.1「如 clear/cloudy/rain/storm/fog」示例落值，§1.3 默认 5 种）
DEFAULT_POOL: tuple = ("clear", "cloudy", "rain", "storm", "fog")

# 可配项缺省（细化_2a4a §1.3：enabled true / season_days 7 / period_minutes 60 / weather_minutes 60）
_DEFAULT_ENABLED = True
_DEFAULT_SEASON_DAYS = 7
_DEFAULT_PERIOD_MINUTES = 60
_DEFAULT_WEATHER_MINUTES = 60


# -------------------------------------------------------------------------------------
# 时间引擎（IF01~IF07 纯函数骨架；配置构造注入）
# -------------------------------------------------------------------------------------
class WorldTime:
    """时间引擎：三周期（季节/时段/天气）懒计算时钟。

    配置经构造注入（cfg = 调用方 settings dict），引擎不读文件、不跑定时器；
    任何时刻周期值均可由锚点公式重算（契约 §5.3「零定时器、不存历史、随时可重算」）。
    所有读取接口为纯函数（同刻同参必同值）；now 为 UTC+8 秒级时间戳（缺省=当前）。
    """

    def __init__(self, cfg: Optional[Mapping[str, object]] = None) -> None:
        tc = cfg.get("time_cycle") if isinstance(cfg, Mapping) else None
        self._tc: Mapping[str, object] = tc if isinstance(tc, Mapping) else {}

    # ---- 配置解析（字段级缺省；坏配置惰性回退默认，不崩溃） ----
    def is_enabled(self) -> bool:
        """IF01 系统总开关：读 time_cycle.enabled（缺省 true）。false → 查询提示未启用、条件键失效。"""
        v = self._tc.get("enabled", _DEFAULT_ENABLED)
        return v if isinstance(v, bool) else _DEFAULT_ENABLED

    def _int_field(self, section_key: str, field: str, default: int, minimum: int) -> int:
        sec = self._tc.get(section_key)
        if not isinstance(sec, Mapping):
            return default
        v = sec.get(field, default)
        if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
            return default  # 坏配置（validator 会红拦）→ 惰性回退默认
        return v

    def season_days(self) -> int:
        """季节天数（整数 ≥1，缺省 7）。"""
        return self._int_field("season", "season_days", _DEFAULT_SEASON_DAYS, 1)

    def period_minutes(self) -> int:
        """时段分钟（整数 ≥30，缺省 60）。"""
        return self._int_field("period", "period_minutes", _DEFAULT_PERIOD_MINUTES, 30)

    def weather_minutes(self) -> int:
        """天气变化分钟（整数 ≥30，缺省 60）。"""
        return self._int_field("weather", "weather_minutes", _DEFAULT_WEATHER_MINUTES, 30)

    def default_pool(self) -> List[str]:
        """默认天气池（非空键唯一；缺省 5 种【工程补白】示例键）。"""
        sec = self._tc.get("weather")
        if isinstance(sec, Mapping):
            p = sec.get("default_pool")
            if isinstance(p, (list, tuple)) and p:
                return [str(k) for k in p]
        return list(DEFAULT_POOL)

    # ---- 锚点基础 ----
    @staticmethod
    def _coerce_now(now: Optional[int]) -> int:
        """now 归一：None → 当前 epoch 秒；否则整型化（UTC+8 秒级时间戳）。"""
        return int(time.time()) if now is None else int(now)

    def _diff(self, now: Optional[int]) -> int:
        return self._coerce_now(now) - ANCHOR

    def _cycle_len(self, kind: str) -> int:
        """周期长（秒）：season=season_days×86400 / period=period_minutes×60 / weather=weather_minutes×60。"""
        if kind == "season":
            return self.season_days() * 86400
        if kind == "period":
            return self.period_minutes() * 60
        if kind == "weather":
            return self.weather_minutes() * 60
        raise ValueError(f"未知周期 kind={kind!r}（可选 season/period/weather）")

    # ---- IF06 周期索引/节拍（纯函数） ----
    def cycle_tick(self, kind: str, now: Optional[int] = None) -> int:
        """IF06 周期索引/节拍：season_idx=floor((now−ANCHOR)/(days×86400))%4；period_idx %5；
        weather_tick 不取模（只增不循环）。now 可为负数 diff（大时间戳/锚点前）——Python floor 除法
        与 % 语义与契约 floor(...)%N 逐字一致。"""
        diff = self._diff(now)
        length = self._cycle_len(kind)
        tick = diff // length
        if kind == "season":
            return tick % len(SEASONS)
        if kind == "period":
            return tick % len(PERIODS)
        return tick  # weather：不取模

    # ---- IF02/IF03 查询（纯函数） ----
    def season_now(self, now: Optional[int] = None) -> str:
        """IF02 季节查询（spring/summer/autumn/winter）。"""
        return SEASONS[self.cycle_tick("season", now)]

    def period_now(self, now: Optional[int] = None) -> str:
        """IF03 时段查询（dawn/noon/dusk/night/midnight）。"""
        return PERIODS[self.cycle_tick("period", now)]

    # ---- IF07 倒计时（纯函数） ----
    def time_remaining(self, kind: str, now: Optional[int] = None) -> int:
        """IF07 距下次变化秒数：ANCHOR+(floor(diff/周期长)+1)×周期长−now = 周期长−(diff%周期长)。
        边界整点（diff%周期长==0）→ 返回完整一个周期长；diff<0 也按公式正确（Python % 非负）。"""
        diff = self._diff(now)
        length = self._cycle_len(kind)
        return length - (diff % length)


# -------------------------------------------------------------------------------------
# time_cycle 段校验（M31 · V1-V3 + enabled bool + default_pool 非空键唯一）
# 供主 agent 收口接入 check_pack：report 兼容 _Checker._err 同签名或 .errors 列表。
# -------------------------------------------------------------------------------------
def _emit(report: object, module: str, field: str, kind: str, **detail: object) -> None:
    """向 report 追加一条红拦：优先 _err(module, field, kind, **detail)；否则 `.errors` 列表 append dict。

    兼容三种收集器形态：① 带 `_err` 方法（content/validator.py `_Checker` 同签名）；
    ② 带 `.errors` 列表属性；③ 带 `errors` 键的 Mapping（如 {"errors": []}）。"""
    if report is None:
        return
    err = getattr(report, "_err", None)
    if callable(err):
        err(module, field, kind, **detail)
        return
    errors = getattr(report, "errors", None)
    if isinstance(errors, list):
        errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})
        return
    if isinstance(report, Mapping):
        errors = report.get("errors")
        if isinstance(errors, list):
            errors.append({"module": module, "field": field, "kind": kind, "detail": dict(detail)})


def validate_time_cycle(settings: Mapping[str, object], report: object) -> None:
    """time_cycle 段校验（M31 · 契约 §6.2 V1~V4 + enabled 类型）。

    settings: 完整 settings dict（可含可选 time_cycle 段；缺省整段 = 全默认，零红拦）。
    report:   收集器（二选一）——
              a) 提供 `_err(module, field, kind, **detail)`（与 content/validator.py `_Checker` 同签名）；
              b) 提供 `errors: list`（追加 {"module","field","kind","detail"} dict）。
    红拦均带人话报错 detail["msg"]（如「季节天数要填整数，最少 1 天」），供命令层直接拼用户文案。
    """
    if not isinstance(settings, Mapping):
        return
    tc = settings.get("time_cycle")
    if not isinstance(tc, Mapping):
        return  # 缺省整段 = 全默认，零红拦

    # enabled 布尔类型（契约 §5.2 / 细化_2a4a §1.3）
    if "enabled" in tc and not isinstance(tc["enabled"], bool):
        _emit(report, "settings", "time_cycle.enabled", "enabled_type",
              rule="enabled_type", got=tc["enabled"],
              msg="time_cycle.enabled 要填 true 或 false")

    # V1 季节天数 ≥1 整数
    season = tc.get("season")
    if isinstance(season, Mapping) and "season_days" in season:
        v = season["season_days"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            _emit(report, "settings", "time_cycle.season.season_days", "V1",
                  rule="season_days_min", minimum=1, got=v,
                  msg="季节天数要填整数，最少 1 天")

    # V2 时段分钟 ≥30 整数
    period = tc.get("period")
    if isinstance(period, Mapping) and "period_minutes" in period:
        v = period["period_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 30:
            _emit(report, "settings", "time_cycle.period.period_minutes", "V2",
                  rule="period_minutes_min", minimum=30, got=v,
                  msg="时段分钟要填整数，最少 30 分钟")

    # V3 天气分钟 ≥30 整数
    weather = tc.get("weather")
    if isinstance(weather, Mapping) and "weather_minutes" in weather:
        v = weather["weather_minutes"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 30:
            _emit(report, "settings", "time_cycle.weather.weather_minutes", "V3",
                  rule="weather_minutes_min", minimum=30, got=v,
                  msg="天气分钟要填整数，最少 30 分钟")

    # V4 默认天气池：非空数组 + 键唯一
    if isinstance(weather, Mapping) and "default_pool" in weather:
        pool = weather["default_pool"]
        if not isinstance(pool, (list, tuple)):
            _emit(report, "settings", "time_cycle.weather.default_pool", "V4",
                  rule="pool_type", got=pool,
                  msg="默认天气池要填数组")
        elif len(pool) == 0:
            _emit(report, "settings", "time_cycle.weather.default_pool", "V4",
                  rule="pool_empty", got=pool,
                  msg="默认天气池至少要 1 种天气")
        else:
            seen: dict = {}
            for i, k in enumerate(pool):
                if not isinstance(k, str):
                    _emit(report, "settings", f"time_cycle.weather.default_pool.{i}", "V4",
                          rule="pool_key_type", got=k,
                          msg="默认天气池的天气键要填字符串")
                elif k in seen:
                    _emit(report, "settings", f"time_cycle.weather.default_pool.{i}", "V4",
                          rule="pool_key_dup", key=k,
                          msg=f"默认天气池天气键重复了：{k}")
                else:
                    seen[k] = i
