"""天气权重刷新装配（M3 批次4·路M · M10 天气权重刷新 + 在场不驱逐 + GameWorld 集成）。

依据：
  - 细化_2a1b_通道规则与刷怪.md §二（R14-R15 刷怪归属地图级；R18 天气权重只影响刷新/补刷
    不驱逐已在场怪物；R21 地图级 max_alive 聚合上限【工程补白 默认 10】；R26 权重值非负
    0=该天气不刷；R27 出没判定链含 weather_weights≠0；R28 有效刷新间隔 = respawn_minutes/weight）
  - 规划_路2a_地图副本.md M10（天气权重刷新：weight ≥1 同时间差补刷更快 / weight=0 不补刷
    但已在场怪保留不驱逐；只影响补刷结算，零定时器懒计算）
  - m3_shared_contract §2.3（Spawn 行字段：weather_weights 默认 1 / 0=该天气不刷 /
    只影响刷新不驱逐在场；地图级 max_alive 聚合上限默认 10）

纯逻辑装配：零 NoneBot import（3a R1）；零定时器（懒计算：按 now 与 last_refresh 差值折算，
不存刷新历史、随时可重算，对齐契约 §八 铁律 1/3）。本模块只做「天气变速补刷结算 +
出没过滤」纯函数，不落地存储——world_state 落盘、SpawnManager.refresh_map 接线、
alive_monsters 在场面查询由 M4/M6 后续【工程补白】。

world_state 契约（地图级刷怪状态切片；收口时由调用方传入 WorldState.spawn_timers 的地图维
切片，对齐路L SpawnManager）：
    {<row_key>: {"alive": int, "last_refresh": int(UTC+8 epoch 秒)}}
    row_key 缺省 = spawn 行序号 str(index)；缺省行记录 → alive=0、last_refresh=now
    （初始刷怪归 M07 / 路L initial_spawn，本模块只做补刷不做首刷）。
    world_state 为可变 dict 时懒计算写回 last_refresh/alive（同 IF09 缓存索引语义）；
    非可变（如 frozen WorldState 快照）→ 不写回，仅返回补刷产物，由调用方落盘。
"""

from __future__ import annotations

import math
import time
from collections.abc import MutableMapping
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, List, Mapping, Optional, Tuple

from qbot_rpg.content.map_models import SPAWN_COUNT_DEFAULT, SpawnDef

__all__ = [
    "DEFAULT_MAX_ALIVE",
    "DEFAULT_WEATHER_WEIGHT",
    "weather_weighted_refresh",
    "max_alive_guard",
    "spawn_eligible",
    "filter_eligible_rows",
    "active_time_ok",
]

# 【工程补白】地图级在场总数上限（2a1b R21，默认 10 可配；aggregate 所有 spawn 行）
DEFAULT_MAX_ALIVE: int = 10
# weather_weights 缺省倍率（contract §2.3：默认 1；0 = 该天气不刷）
DEFAULT_WEATHER_WEIGHT: float = 1.0

# 现实钟点层（3.6 语义）按 UTC+8 墙钟折算（引擎 now = UTC+8 epoch 秒，契约 §5.3 锚点口径）
_UTC8 = timezone(timedelta(hours=8))


# -------------------------------------------------------------------------------------
# 行访问小工具（spawn_rows 兼容 raw dict 与 SpawnDef 双形态；收口可直传 路L 行结构）
# -------------------------------------------------------------------------------------
def _row_get(row: object, key: str, default: object = None) -> object:
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _int_or(v: object, default: int) -> int:
    if isinstance(v, int) and not isinstance(v, bool):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return default


def _weight_of(row: object, weather: Optional[str]) -> float:
    """当前天气的 weather_weights 倍率（R26/R28）：缺省权重表 / 天气缺省 → 默认 1；
    0 = 该天气不刷；非法（负/非数）防御回默认 1（不静默禁刷，校验器已红拦非法值）。"""
    ww = _row_get(row, "weather_weights")
    if not isinstance(ww, Mapping) or weather is None:
        return DEFAULT_WEATHER_WEIGHT
    v = ww.get(weather)
    if v is None or isinstance(v, bool):
        return DEFAULT_WEATHER_WEIGHT
    try:
        f = float(v)
    except (TypeError, ValueError):
        return DEFAULT_WEATHER_WEIGHT
    return f if f >= 0 else DEFAULT_WEATHER_WEIGHT


# -------------------------------------------------------------------------------------
# 地图级在场总数上限（2a1b R21【工程补白 默认 10】）
# -------------------------------------------------------------------------------------
def max_alive_guard(
    alive_count: int,
    max_alive: int = DEFAULT_MAX_ALIVE,
    requested: int = 1,
) -> int:
    """地图级在场总数上限（聚合所有 spawn 行）。

    返回本次实际允许补刷数（≤ requested 且 ≤ max_alive - alive_count）；超限不补刷返回 0。
    负数/异常入参防御钳制。纯函数，零副作用。
    """
    alive = max(0, alive_count)
    cap = max(0, max_alive)
    req = max(0, requested)
    if alive >= cap:
        return 0
    return min(req, cap - alive)


# -------------------------------------------------------------------------------------
# 天气变速补刷（M10 · R28：有效刷新间隔 = respawn_minutes / weight；R18/R30 不驱逐在场）
# -------------------------------------------------------------------------------------
def weather_weighted_refresh(
    spawn_rows: Iterable[object],
    weather: Optional[str],
    now: int,
    world_state: Optional[MutableMapping] = None,
    max_alive: int = DEFAULT_MAX_ALIVE,
) -> List[Mapping[str, object]]:
    """按当前天气 weather_weights 倍率变速补刷（M10）。

    每行：
      - weight = weather_weights.get(weather, 1.0)（R26/R28）；weight=0 → 该天气不刷：
        跳过该行、**不驱逐已在场怪**、且计时不推进（该天气下无刷新发生，R18/R30）；
      - 有效刷新间隔 interval = respawn_minutes / weight → 应补刷数
        due = floor((now - last_refresh) / interval) 截断到缺口 count - alive；
      - 地图级 max_alive 聚合上限（R21）逐行收口（顺序结算，先前行已批准数计入在场）；
      - 返回补刷产物（调用方据此落地在场怪物实例）。

    在场怪物不驱逐：本函数只增不删；天气变化只影响后续刷新计时，已在场（含战斗中）
    怪物保留（R18/R19/R30 对齐 TC-14/TC-15）。

    懒计算写回（world_state 为可变 dict 时）：last_refresh += 已消耗间隔数 × interval
    （消耗全部已流逝间隔，防重复补刷；0 权重行不推进）；alive += 实际补刷数。
    被地图级 max_alive 聚合上限拦截的行（allowed==0 且 due>0，requested>0）**冻结计时**
    （欠账保留，下次让位后补刷）——审查_M3_批次4 P1-1 修复：此前被拦行仍推进 last_refresh，
    已流逝间隔被消耗，补刷欠账永久丢失。
    零定时器、不存刷新历史、随时可重算。

    返回：补刷产物列表 [{enemy, count, row_index, weather, weight}, ...]。
    """
    rows: List[object] = list(spawn_rows)
    state: dict = dict(world_state) if isinstance(world_state, Mapping) else {}

    def _row_state(i: int) -> dict:
        st = state.get(str(i), {})
        return dict(st) if isinstance(st, Mapping) else {}

    # 地图级在场总数（聚合所有 spawn 行，R21）——作为顺序结算的起点
    total_alive: int = 0
    for i, _row in enumerate(rows):
        total_alive += max(0, _int_or(_row_state(i).get("alive"), 0))

    products: List[Mapping[str, object]] = []
    for i, row in enumerate(rows):
        respawn = _row_get(row, "respawn_minutes")
        if not isinstance(respawn, int) or isinstance(respawn, bool) or respawn < 1:
            continue  # R26：respawn_minutes 必填 ≥1；非法行不参与补刷
        weight = _weight_of(row, weather)
        if weight <= 0:
            continue  # R18/R26：该天气不刷；已在场怪保留；计时不推进
        interval_min: float = respawn / weight  # R28：有效刷新间隔 = respawn_minutes / weight
        count = max(0, _int_or(_row_get(row, "count"), SPAWN_COUNT_DEFAULT))
        st = _row_state(i)
        alive = max(0, _int_or(st.get("alive"), 0))
        last_refresh = _int_or(st.get("last_refresh"), now)  # 缺省行 → 首刷归 M07，本模块不首刷
        elapsed_min = max(0.0, (now - last_refresh) / 60.0)
        due = int(math.floor(elapsed_min / interval_min)) if interval_min > 0 else 0
        gap = max(0, count - alive)
        requested = max(0, min(due, gap))
        allowed = max_alive_guard(total_alive, max_alive, requested)  # R21 地图级聚合上限
        if allowed > 0:
            products.append({
                "enemy": _row_get(row, "enemy"),
                "count": allowed,
                "row_index": i,
                "weather": weather,
                "weight": weight,
            })
            total_alive += allowed
        # 懒计算写回：仅当 ① 行已满/无欠账（requested==0，计时随自然流逝推进）或 ② 本次实际
        # 获批（allowed>0）时才消耗已流逝的刷新间隔（防重复补刷）；被地图级 max_alive 上限
        # 拦截（allowed==0 且 due>0 且 requested>0）时**冻结计时**——欠账保留，下次让位后补刷
        # （审查_M3_批次4 P1-1）。0 权重行（weight<=0 已 continue）不推进计时。
        if due > 0 and (requested == 0 or allowed > 0):
            st_new = dict(st)
            st_new["alive"] = alive + allowed
            st_new["last_refresh"] = min(
                now, last_refresh + int(due * interval_min * 60)
            )
            state[str(i)] = st_new

    if isinstance(world_state, MutableMapping):
        world_state.clear()
        world_state.update(state)
    return products


# -------------------------------------------------------------------------------------
# 出没判定链（2a1b R27 全 AND，缺一不出）——供 GameWorld.monster_pool 过滤可出没行
# -------------------------------------------------------------------------------------
def _clock_minutes(now: int) -> int:
    """UTC+8 墙钟 → 分钟（0-1439；现实钟点层 3.6 语义）。"""
    dt = datetime.fromtimestamp(now, tz=_UTC8)
    return dt.hour * 60 + dt.minute


def _hhmm(s: str) -> Optional[int]:
    """\"HH:MM\" → 分钟；非法返回 None（调用方缺省全天【工程补白】）。"""
    try:
        hh, mm = s.split(":")
        return int(hh) * 60 + int(mm)
    except (ValueError, TypeError):
        return None


def active_time_ok(active_time: object, now: Optional[int] = None) -> bool:
    """现实钟点出没窗口（3.6 语义保留）：空/缺省 = 全天；\"20:00\"-\"06:00\" 跨夜写法沿用。"""
    if not isinstance(active_time, Mapping):
        return True
    f = active_time.get("from")
    t = active_time.get("to")
    if not isinstance(f, str) or not isinstance(t, str) or not f or not t:
        return True  # 半配/非法 → 缺省全天【工程补白】
    if now is None:
        now = int(time.time())
    cur = _clock_minutes(now)
    lo = _hhmm(f)
    hi = _hhmm(t)
    if lo is None or hi is None:
        return True
    if lo <= hi:
        return lo <= cur <= hi
    return cur >= lo or cur <= hi  # 跨夜（f > t）


def spawn_eligible(
    row: object,
    ctx: Optional[Mapping[str, object]] = None,
    now: Optional[int] = None,
) -> bool:
    """出没判定（R27 全 AND，缺一不出）：active_time ∧ seasons ∧ periods ∧ weather_weights≠0。

    ctx: {"season": 四季, "period": 五时段, "weather": 当前图天气键}——季节/时段全局值、
    天气按玩家当前所在图（R31/R32 上下文绑定）。ctx 字段缺省/None → 恒真（空=全年/全天，
    contract §2.3）。weather_weights 0 = 该天气不刷（R18/R26 链尾）。
    now: 现实钟点层 UTC+8 epoch 秒（active_time 判定用；缺省=当前）。
    """
    ctx_map = dict(ctx) if isinstance(ctx, Mapping) else {}
    if not active_time_ok(_row_get(row, "active_time"), now):
        return False
    seasons_raw = _row_get(row, "seasons")
    seasons: Tuple[str, ...] = (
        tuple(s for s in seasons_raw if isinstance(s, str))
        if isinstance(seasons_raw, (list, tuple))
        else ()
    )
    season = ctx_map.get("season")
    if seasons and (not isinstance(season, str) or season not in seasons):
        return False
    periods_raw = _row_get(row, "periods")
    periods: Tuple[str, ...] = (
        tuple(p for p in periods_raw if isinstance(p, str))
        if isinstance(periods_raw, (list, tuple))
        else ()
    )
    period = ctx_map.get("period")
    if periods and (not isinstance(period, str) or period not in periods):
        return False
    weather = ctx_map.get("weather")
    return _weight_of(row, weather if isinstance(weather, str) else None) > 0


def filter_eligible_rows(
    spawn_rows: Iterable[object],
    ctx: Optional[Mapping[str, object]] = None,
    now: Optional[int] = None,
) -> List[object]:
    """过滤当前可出没 spawn 行（R27 全 AND）。

    契约对齐：路L SpawnManager.filter_eligible(spawn_rows, ctx) 落盘前由本函数承载
    （收口时 GameWorld.monster_pool 优先调用注入管理器的 filter_eligible）。
    """
    return [r for r in spawn_rows if spawn_eligible(r, ctx, now)]


# 供 GameWorld / 测试引用的稳定行访问入口
def _enemy_of(row: object) -> Any:
    if isinstance(row, Mapping):
        return row.get("enemy")
    return getattr(row, "enemy", None)
