"""日界统一与懒计算 —— M4 批次0·路A3（A3 唯一实现：05:00 重置 + 懒补算 + 跨周/once 周期工具）。

依据：m4_shared_contract §1 A3（日界统一与懒计算：today_of 单一入口、重置时刻默认 05:00 可配、
      与 quest_daily/商店/签到共用配置键、凌晨 0-5 点归属前一天、惰性补算不依赖定时器、
      离线多天不丢不炸、跨周判定与 once 时间窗复用同一套周期工具）
      + 细化_2b5_签到引擎契约 §5.3（懒计算唯一判定 / 统一周期键默认 05:00 / 商店/任务/签到三表同刻对齐）
      + 细化_2b4_任务引擎契约 §1.3（board.refresh daily/weekly/once，每日懒计算刷新，
        重置时刻默认 05:00 可配）
      + 审查参考/商店系统设计定稿 §七（last_refresh 惰性补刷 / 时区统一 UTC+8 /
        跨周按「结束 > 开始」判定日期偏移 / once 模式 start 未到=未开门、end 已过=自动下架 /
        统一配置键 refresh_time 默认 05:00 可配）。

语义（契约 §1 A3 / 签到 §5.3 / 商店 §七）：
  - 重置时刻（默认 05:00 UTC+8，可配）之后算新一天；凌晨 0-5 点归属前一天（防凌晨断签/限购刷新骚扰）。
  - 懒计算为唯一判定：玩家操作时取存档日期键（last_key）与当前现实时间比较，跨期即补算；
    零定时器、零 NoneBot 依赖、纯函数（同刻同参必同值），服务器重启/离线多天不丢不炸。
  - 统一配置键 refresh_time（默认 "05:00"，可配）：商店/任务/签到三表同刻对齐。
  - 周期工具（days_elapsed / weeks_elapsed / advance_cycles / is_window_open）供
    商店 refresh（daily/weekly/once）与签到 activity 时间窗、任务板 refresh 复用。

【工程补白】
  - 返回形态：契约 §1 A3 一行签名写 `today_of(last_key, now=None) -> str`；本路派工
    （M4 批次0·路A3）明确「返回形态 {today, days_elapsed, refreshed}」——`today` 即契约所指的
    日期键字符串；`days_elapsed`（跨期补算的天数）与 `refreshed`（是否发生跨期需补刷）为懒补算
    消费方（签到跨天判定 / 商店 last_refresh 惰性补刷 / quest_daily 当日清零）所需，故返回完整 dict。
  - last_key 缺省（None）= 首次无先期状态：days_elapsed=0、refreshed=False
    （消费方自行区分「首启」与「同天幂等」）。
  - last_key 非法串 / 未来日期（时钟回拨）：防御性回退 days_elapsed=0、refreshed=False，不崩溃
    （对齐引擎「坏数据惰性回退不崩溃」惯例）。
  - weeks_elapsed 跨周判定按「结束 > 开始」日期偏移：日期键 d 归属的周周期 = 最近一次（≤d 的）
    配置星期边界；跨周数 = (周周期键差)//7，恰在同一周内为 0（周边界未越则不刷新）。
    weekday 约定对齐商店 §七 `{ "mode": "weekly", "weekday": 1 } // 每周一`：1=周一 .. 7=周日。
  - is_window_open 窗口闭区间 [start, end]：now < start → not_started（未开门）；now > end →
    expired（自动下架）；start/end 缺省或解析失败 → 视为常驻开放（不崩溃）。
  - advance_cycles 月推进按自然月进位并夹取目标月天数（如 2026-01-31 +1 月 → 2026-02-28）；
    非法 last_key 原样透传（防御），非法 period 抛 ValueError（编程契约，对齐
    WorldTime.cycle_tick 未知 kind 抛错惯例）。

零 NoneBot import；零定时器；时区统一 UTC+8（now = UTC+8 秒级时间戳，缺省 = 当前）。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from typing import Mapping, Optional

__all__ = [
    "DEFAULT_REFRESH_TIME",
    "PERIODS",
    "WINDOW_NOT_STARTED",
    "WINDOW_OPEN",
    "WINDOW_EXPIRED",
    "normalize_hhmm",
    "resolve_refresh_time",
    "today_of",
    "days_elapsed",
    "weeks_elapsed",
    "advance_cycles",
    "is_window_open",
]

# 时区统一 UTC+8（对齐引擎 worldtime / spawn：now = UTC+8 秒级时间戳）
_TZ_UTC8 = timezone(timedelta(hours=8))

# 统一配置键 refresh_time 默认值（商店/任务/签到三表同刻对齐；可配）
DEFAULT_REFRESH_TIME = "05:00"

# advance_cycles 支持的三类周期（商店 §七 daily/weekly + 签到 §1.4 月周期）
PERIODS: tuple = ("day", "week", "month")

# is_window_open 三态（商店 §七：start 未到=未开门 / end 已过=自动下架）
WINDOW_NOT_STARTED = "not_started"
WINDOW_OPEN = "open"
WINDOW_EXPIRED = "expired"


# -------------------------------------------------------------------------------------
# 时间基础：UTC+8 秒级时间戳 → 日期键 / 刷新时刻配置解析
# -------------------------------------------------------------------------------------
def _now(now: Optional[int]) -> int:
    """now 归一：None → 当前 epoch 秒；否则整型化（UTC+8 秒级时间戳，缺省=当前）。"""
    return int(time.time()) if now is None else int(now)


def _parse_date(key: object) -> Optional[date]:
    """日期键 "YYYY-MM-DD" → date；None/非法串 → None（防御性回退，不崩溃）。"""
    if isinstance(key, str):
        try:
            return date.fromisoformat(key.strip())
        except ValueError:
            return None
    return None


def normalize_hhmm(raw: object) -> str:
    """刷新时刻归一："HH" / "HH:MM" / int 小时 → "HH:MM"；非法 → 默认 05:00（坏配置惰性回退，不崩溃）。

    消费方（商店「下次补货：明早 ${refresh_time}」文案等）与引擎共用此归一口径。
    """
    if isinstance(raw, bool):
        return DEFAULT_REFRESH_TIME
    if isinstance(raw, int):
        h, m = raw, 0
    elif isinstance(raw, str):
        s = raw.strip()
        try:
            if ":" in s:
                h_part, m_part = s.split(":", 1)
                if ":" in m_part:
                    return DEFAULT_REFRESH_TIME
                h, m = int(h_part), int(m_part)
            else:
                h, m = int(s), 0
        except ValueError:
            return DEFAULT_REFRESH_TIME
    else:
        return DEFAULT_REFRESH_TIME
    if not (0 <= h <= 23 and 0 <= m <= 59):
        return DEFAULT_REFRESH_TIME
    return f"{h:02d}:{m:02d}"


def resolve_refresh_time(cfg: Optional[Mapping]) -> str:
    """统一配置键 refresh_time（默认 05:00，可配）：商店/任务/签到三表同刻对齐。

    读取 settings 顶层 `refresh_time`；容错嵌套 `settings.refresh_time`（防整包包裹形态）。
    配置经调用方注入（引擎不读文件、不做 IO，对齐 WorldTime 构造注入惯例）。
    """
    raw: object = None
    if isinstance(cfg, Mapping):
        raw = cfg.get("refresh_time")
        if raw is None:
            inner = cfg.get("settings")
            if isinstance(inner, Mapping):
                raw = inner.get("refresh_time")
    return normalize_hhmm(raw)


def _reset_offset(cfg: Optional[Mapping]) -> timedelta:
    """刷新时刻 → 日界偏移量（now 减去该偏移后的日期 = 归属日）。"""
    hhmm = resolve_refresh_time(cfg)
    return timedelta(hours=int(hhmm[:2]), minutes=int(hhmm[3:5]))


def _date_key(ts: int, offset: timedelta) -> str:
    """UTC+8 时刻按日界偏移 → 归属日期键 "YYYY-MM-DD"。

    重置时刻（默认 05:00）之后算新一天；凌晨 0-5 点归属前一天（签到 §5.3 / 契约 §1 A3）。
    """
    shifted = datetime.fromtimestamp(ts, tz=_TZ_UTC8) - offset
    return shifted.strftime("%Y-%m-%d")


def _days_between(last_key: object, today: str) -> int:
    """last_key 日期键 → 距 today 的日界数（None/非法/未来 → 0，防御性回退）。"""
    a = _parse_date(last_key)
    if a is None:
        return 0
    b = _parse_date(today)
    if b is None:
        return 0
    return max(0, (b - a).days)


# -------------------------------------------------------------------------------------
# A3 日界统一与懒补算（唯一实现）
# -------------------------------------------------------------------------------------
def today_of(
    last_key: object = None,
    now: Optional[int] = None,
    cfg: Optional[Mapping] = None,
) -> dict:
    """日界统一单一入口：返回 {today, days_elapsed, refreshed}（见文件头补白）。

    last_key:  存档日期键（"YYYY-MM-DD"，如签到 last_date / 商店 last_refresh / quest_daily 当日行）。
                缺省 None = 首次无先期状态（days_elapsed=0、refreshed=False，消费方自行区分首启与同天）。
    now:       UTC+8 秒级时间戳，缺省 = 当前（纯函数可测）。
    cfg:       settings dict（构造注入）；重置时刻读统一配置键 refresh_time（默认 "05:00"）。

    返回：
      today          当前归属日期键 "YYYY-MM-DD"（重置时刻之后算新一天，凌晨 0-5 点归属前一天）
      days_elapsed   last_key → today 跨过的日界数（离线多天 = 天数差；None/非法/未来 = 0）
      refreshed      是否发生跨期需补刷（last_key 存在且 days_elapsed > 0）

    懒补算语义：玩家操作时取 last_key 与当前时间比较，跨期即补算——零定时器、零 NoneBot、
    纯函数（同刻同参必同值），服务器重启/离线多天不丢不炸（签到 §5.3 / 契约 §1 A3）。
    """
    ts = _now(now)
    offset = _reset_offset(cfg)
    today = _date_key(ts, offset)
    days = _days_between(last_key, today)
    return {"today": today, "days_elapsed": days, "refreshed": bool(days > 0)}


def days_elapsed(
    last_key: object,
    now: Optional[int] = None,
    cfg: Optional[Mapping] = None,
) -> int:
    """存档日期键 → 距 today 的日界数（跨期补算天数；None/非法/未来 → 0）。

    供签到跨天判定（断签间隔 >1 天 → streak 归 1）/ 商店 daily 惰性补刷 / quest_daily 当日清零。
    """
    if last_key is None:
        return 0
    today = _date_key(_now(now), _reset_offset(cfg))
    return _days_between(last_key, today)


# -------------------------------------------------------------------------------------
# 跨周判定（结束 > 开始 日期偏移）与周期推进工具（商店 refresh / 签到周期复用）
# -------------------------------------------------------------------------------------
def _weekday_offset(weekday: object) -> int:
    """星期归一 → Python date.weekday()（0=周一..6=周日）。

    weekday 约定对齐商店 §七 `{ "mode": "weekly", "weekday": 1 } // 每周一 05:00`：
    1=周一 .. 7=周日；缺省/非法 → 1（周一）。
    """
    if isinstance(weekday, int) and not isinstance(weekday, bool) and 1 <= weekday <= 7:
        return weekday - 1
    return 0


def weeks_elapsed(
    last_key: object,
    now: Optional[int] = None,
    cfg: Optional[Mapping] = None,
    weekday: int = 1,
) -> int:
    """跨周判定（结束 > 开始 日期偏移）：日期键 d 归属的周周期 = 最近一次（≤d 的）配置星期边界；
    跨周数 = (周周期键差) // 7——恰在同一周内为 0（周边界未越则不刷新）。

    供商店 refresh weekly（§七「weekly 跨周按结束>开始判定日期偏移」）与签到周周期复用。
    weekday: 1=周一 .. 7=周日（默认 1=周一，对齐商店 §七 weekly 示例）。
    None/非法 last_key/未来 → 0。
    """
    if last_key is None:
        return 0
    a = _parse_date(last_key)
    if a is None:
        return 0
    wd = _weekday_offset(weekday)
    today = _date_key(_now(now), _reset_offset(cfg))
    b = _parse_date(today)
    if a is None or b is None:
        return 0
    if a >= b:
        return 0
    # 周周期起点 = 最近一次 ≤d 的配置星期（结束=下次边界 > 开始=本周起点 → 偏移取整）
    wa = a - timedelta(days=(a.weekday() - wd) % 7)
    wb = b - timedelta(days=(b.weekday() - wd) % 7)
    return max(0, (wb - wa).days // 7)


def _advance_month(key_date: date, cycles: int) -> date:
    """自然月进位 + 夹取目标月天数（2026-01-31 +1 月 → 2026-02-28；跨年正确进位）。"""
    total = (key_date.year - 1) * 12 + (key_date.month - 1) + cycles
    y = total // 12 + 1
    m = total % 12 + 1
    if m == 2:
        leap = y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)
        dim = 29 if leap else 28
    elif m in (4, 6, 9, 11):
        dim = 30
    else:
        dim = 31
    return date(y, m, min(key_date.day, dim))


def advance_cycles(
    last_key: object,
    cycles: int = 1,
    period: str = "day",
    cfg: Optional[Mapping] = None,  # 签名保留 cfg 与其它周期工具对齐；纯函数（ARG001 未启用）
) -> str:
    """日期键推进 N 个周期：day=+N 天 / week=+7N 天 / month=自然月进位+夹取天数。

    供 once 时间窗（签到 D-01 day 编号 / 商店周期）/ 周期推进复用。
    非法 last_key → 原样透传（防御）；非法 period → ValueError（编程契约）。
    """
    if period not in PERIODS:
        raise ValueError(f"advance_cycles: unknown period {period!r} (expect {PERIODS})")
    a = _parse_date(last_key)
    if a is None:
        return last_key  # type: ignore[return-value]  # 非法 last_key 原样透传（防御）
    if period == "day":
        b = a + timedelta(days=cycles)
    elif period == "week":
        b = a + timedelta(days=7 * cycles)
    else:
        b = _advance_month(a, cycles)
    return b.isoformat()


# -------------------------------------------------------------------------------------
# once 时间窗（未开门 / 自动下架）—— 商店 §七 / 签到 §2.2 生效表启停判定复用
# -------------------------------------------------------------------------------------
def _parse_time_str(s: object) -> Optional[int]:
    """时间串 "YYYY-MM-DD[ HH:MM]"（UTC+8）→ epoch 秒；时间缺省 = 当日 00:00；非法 → None。"""
    if not isinstance(s, str):
        return None
    t = s.strip()
    try:
        if len(t) < 10 or t[4] != "-" or t[7] != "-":
            return None
        d = date.fromisoformat(t[:10])
        rest = t[10:].strip().lstrip("T")
        h = m = 0
        if rest:
            parts = rest.split(":")
            h = int(parts[0])
            if len(parts) > 1:
                m = int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return int(datetime(d.year, d.month, d.day, h, m, 0, tzinfo=_TZ_UTC8).timestamp())
    except (ValueError, IndexError):
        return None


def is_window_open(start: object, end: object, now: Optional[int] = None) -> str:
    """once 时间窗判定（闭区间 [start, end]）：

      now < start        → "not_started"（未开门，商店「这家店还没开门」/ 签到自动停用）
      now > end          → "expired"（自动下架 / 签到过期停用）
      其余               → "open"
      start/end 缺省或解析失败 → 视为常驻开放（不崩溃）。

    start/end: 时间串 "YYYY-MM-DD[ HH:MM]"（UTC+8）；now: UTC+8 秒级时间戳，缺省=当前。
    """
    ts = _now(now)
    s = _parse_time_str(start)
    e = _parse_time_str(end)
    if s is not None and ts < s:
        return WINDOW_NOT_STARTED
    if e is not None and ts > e:
        return WINDOW_EXPIRED
    return WINDOW_OPEN
