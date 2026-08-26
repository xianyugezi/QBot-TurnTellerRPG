"""time_state 数据契约与序列化纯模块（M3 批次1·路E · M35 / IF11）。

依据：细化_2a4a §六（TC-13 world_state.time_state 重启恢复：缓存索引恢复且与公式重算
      一致、map_weather_seen 只含访问过的图、跨内容包迁移不崩）
      + 细化_2a4c_时间天气接口 §1.1 IF11（load_time_state/save_time_state：读写
      world_state.time_state（season_idx/period_idx/weather_tick/map_weather_seen）；
      字段级迁移缺补默认多忽略；去重 = 缓存与重算相等不播）
      + m3_shared_contract §5.3 IF11（world_state.time_state 存档；字段级迁移
      缺补默认多忽略，version 变更不崩）。

本文件 = IF11 的「引擎侧数据契约」纯函数层：time_state 的缺省 / 迁移 / 写回 /
惰性增长 / 缓存相等判定。world_state.time_state 字段登记（M35）：字段契约由本模块
DEFAULT_TIME_STATE 承载，world_state.py 不做修改（M3 骨架不动），M4 路3 A4 接线时
并入存储层 repository / WorldState 即可。

【工程补白】
  - store 形态约定：调用方传入 world_state 行视图 dict（形如 {"time_state": {...}}，
    key="time_state" 单行 JSON 承载，4a §1.3 world_state 表 key-value 语义）。
    存储层真实 IO（SQLite 读写、事务、CAS 比对）由 M4 路3 A4 接线，本路纯数据契约
    —— 本模块零 IO、零 NoneBot、零定时器，仅标准库。
  - save_time_state 采用「返回新 dict、不改入参」语义（纯函数）；调用方决定是否采纳
    返回值（存储层接线时替换自身 store 引用即可）。
  - load_time_state 字段级迁移：已知键缺失 → 补默认；已知键类型不合法 → 兜底默认
    （与 engine/worldtime.py 坏配置「缺补默认多忽略」同口径）；未知键 → 忽略
    （不删不崩，跨内容包字段级迁移）。
  - map_weather_seen 惰性增长：只有 mark_map_seen 显式记录的图才会进入集合
    （TC-13「只含访问过的图」）；load/save 不裁剪既有记录。值语义：value=True
    占位标记（「已见/已播」集合语义），IF10 播报去重如需「图→已播 tick」可在后续
    批次字段级升级（多忽略迁移兼容）。
  - cache_indexes_equal 供 IF09 变化检测去重：只比较三周期索引
    （season_idx/period_idx/weather_tick），map_weather_seen 与其它键不参与
    （「缓存与重算相等不播」）。
"""

from __future__ import annotations

from typing import Mapping, Optional

__all__ = [
    "DEFAULT_TIME_STATE",
    "load_time_state",
    "save_time_state",
    "mark_map_seen",
    "cache_indexes_equal",
]

# 契约字段缺省（season_idx/period_idx/weather_tick/map_weather_seen）。
# 注意：模块级常量仅供读取；获取实例请用 load_time_state()/mark_map_seen() 等
# 返回的新 dict（内部一律深拷贝，不共享可变对象）。
DEFAULT_TIME_STATE: dict = {
    "season_idx": 0,
    "period_idx": 0,
    "weather_tick": 0,
    "map_weather_seen": {},
}

# IF09 变化检测只比较的三个周期索引键（去重判定范围）
_INDEX_KEYS: tuple = ("season_idx", "period_idx", "weather_tick")


def _is_int(v: object) -> bool:
    """整型判定：int 且非 bool（bool 是 int 子类，与 worldtime 同口径拒绝）。"""
    return isinstance(v, int) and not isinstance(v, bool)


def _fresh_default() -> dict:
    """全新默认 time_state（map_weather_seen 独立实例，防共享可变状态）。"""
    return {
        "season_idx": DEFAULT_TIME_STATE["season_idx"],
        "period_idx": DEFAULT_TIME_STATE["period_idx"],
        "weather_tick": DEFAULT_TIME_STATE["weather_tick"],
        "map_weather_seen": dict(DEFAULT_TIME_STATE["map_weather_seen"]),
    }


def _normalize(raw: Mapping) -> dict:
    """把任意 Mapping 规整为契约 time_state：缺补默认 / 未知忽略 / 类型兜底。"""
    ts = _fresh_default()
    season = raw.get("season_idx")
    if _is_int(season):
        ts["season_idx"] = season
    period = raw.get("period_idx")
    if _is_int(period):
        ts["period_idx"] = period
    tick = raw.get("weather_tick")
    if _is_int(tick):
        ts["weather_tick"] = tick
    seen = raw.get("map_weather_seen")
    if isinstance(seen, Mapping):
        # 键统一 str 化（防非 JSON 可序列化键落库）；值原样透传（IF10 去重消费方定值）
        ts["map_weather_seen"] = {str(k): v for k, v in seen.items()}
    return ts


def load_time_state(store: Optional[dict]) -> dict:
    """从 world_state 行视图 store 读 time_state（缺补默认 / 未知忽略，字段级迁移）。

    store: 调用方传入的 world_state 行 dict（{"time_state": {...}}）。store 为 None、
           非 dict、或 time_state 缺失 / 非 Mapping → 返回全默认。
    返回：新 time_state dict（map_weather_seen 独立副本，不与入参共享可变状态）。
    """
    if not isinstance(store, Mapping):
        return _fresh_default()
    raw = store.get("time_state")
    if not isinstance(raw, Mapping):
        return _fresh_default()
    return _normalize(raw)


def save_time_state(store: dict, time_state: dict) -> dict:
    """写回 world_state 行视图 store["time_state"]，返回新 store（不改入参）。

    time_state 先经 _normalize 规整（缺补默认 / 未知忽略 / 类型兜底），保证落盘形态
    永远符合契约字段（load 后必然可无损读回，round-trip 稳定）。
    语义：纯函数 —— 返回 {**store, "time_state": 规范化副本}；store 非 dict →
    新建 {"time_state": ...}（防御）。调用方决定是否采纳返回值（存储层接线时替换引用）。
    """
    normalized = _normalize(time_state if isinstance(time_state, Mapping) else {})
    if not isinstance(store, Mapping):
        return {"time_state": normalized}
    return {**dict(store), "time_state": normalized}


def mark_map_seen(time_state: dict, map_id: str) -> dict:
    """map_weather_seen 惰性增长：只记录访问过的图（TC-13），返回新 state。

    不改入参；map_id 已记录 → 幂等（返回等价新 dict，不重复记录）。
    非 dict / 缺字段的 state 按默认规整后再标记（防御）。
    """
    base = _normalize(time_state) if isinstance(time_state, Mapping) else _fresh_default()
    seen = dict(base["map_weather_seen"])
    seen[str(map_id)] = True  # 值占位标记【工程补白】：IF10 按需升级「图→已播 tick」
    return {**base, "map_weather_seen": seen}


def cache_indexes_equal(cached: object, recomputed: object) -> bool:
    """缓存索引与重算值相等判定（IF09 去重基础设施：相等 → 无变化 → 不播）。

    只比较三周期索引键（season_idx/period_idx/weather_tick）；map_weather_seen 与
    其它键不参与变化检测。任一入参非 Mapping → False（不可信）。键缺失按
    「双方同缺 = 相等」处理（无缓存 = 无变化，不播）。
    """
    if not isinstance(cached, Mapping) or not isinstance(recomputed, Mapping):
        return False
    for k in _INDEX_KEYS:
        if cached.get(k) != recomputed.get(k):
            return False
    return True
