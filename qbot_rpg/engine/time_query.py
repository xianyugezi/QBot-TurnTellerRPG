"""查询数据组装纯模块 —— M3 批次1·路F（M36 /时间 /天气 查询数据接口，引擎侧）。

依据：细化_2a4a_时间引擎（§1.1 周期注册表 4+5 枚举 / §1.3 可配项 / §2.4 倒计时展示）
      + 规划_路2a_地图副本.md M36（/时间 /天气 查询：季节距下次 X 天 / 时段距下次 X 分钟 /
      天气距下次 X 分钟；只报状态不教规则）+ m3_shared_contract §5.3（IF07 倒计时数据源）。

本文件 = M36 查询接口的「引擎侧数据组装」纯模块：产出结构化状态 dict
（中文文案模板两用，文案拼装/未注册玩家提示属指令层 M4 接线）。
依赖 qbot_rpg/engine/worldtime.py 的 IF01~IF07：
  IF02 season_now / IF03 period_now / IF06 cycle_tick / IF07 time_remaining；
不修改 worldtime.py（零冲突），不读写任何状态。

铁律：零 NoneBot import（契约 §八 4）；纯函数（同刻同参必同值）；不跑定时器。

【工程补白】
  - 倒计时折算（M36 粒度）：IF07 返回秒，本层换算——季节 remaining_days = 秒 // 86400
    （整天下取，小时余量本层丢弃；如需定稿「X 天 Y 小时」粒度，文案层可直接调
    WorldTime.time_remaining 自取秒再拆分）；时段/天气 remaining_minutes = 秒 // 60（整分下取）。
  - 天气当前值：按 IF04 weather_now 语义（生效池确定性抽签，IF08 map_weather）。
    审查 M3 批次2 P1-1：批次 2 IF08 已落地，原「先按 pool_keys[0] 取」补白占位已替换为
    `WorldTime(cfg).weather_now(map_id, now)`（并把生效池注入 map_pools，保证 key 与
    pool_label 同源：覆盖池同图同刻可不同天气），返回结构不变。
  - 生效池标注（pool_label）：pool_source 显式传 "coverage"/"default" 时按显式来源标注；
    缺省按「生效池与配置默认池键集合相等」比较推导（集合比较顺序无关：map_pool 返回排序键、
    default_pool 为配置序，同一池两序皆判「默认池」；覆盖池=「使用本图天气池」/默认池=「默认池」）。
    空生效池（pool_keys 空/None）按 IF05 map_pool 语义回退默认池（M38 缺省/空数组 = 用默认池）。
  - DEFAULT_WEATHER_NAMES 为细化_2a4a §1.1「如 clear/cloudy/rain/storm/fog → 晴/多云/雨/雷雨/雾」
    示例落值（与 worldtime.DEFAULT_POOL 补白示例键同口径）；天气键为内容包自定义，
    未登记键中文名回退原键（不崩溃）。
"""

from __future__ import annotations

from typing import Mapping, Optional

from qbot_rpg.engine.worldtime import WorldTime

__all__ = [
    "SEASON_NAMES",
    "PERIOD_NAMES",
    "DEFAULT_WEATHER_NAMES",
    "weather_name",
    "season_status",
    "period_status",
    "weather_status",
]

# -------------------------------------------------------------------------------------
# 中文名映射表（细化_2a4a §1.1：季节 4 值 + 时段 5 值固定枚举，展示用中文名）
# -------------------------------------------------------------------------------------
SEASON_NAMES: Mapping[str, str] = {
    "spring": "春",
    "summer": "夏",
    "autumn": "秋",
    "winter": "冬",
}

PERIOD_NAMES: Mapping[str, str] = {
    "dawn": "晨",
    "noon": "午",
    "dusk": "昏",
    "night": "夜",
    "midnight": "午夜",
}

# 默认天气池中文名（【工程补白】示例落值；内容包自定义键不在表内 → weather_name 回退原键）
DEFAULT_WEATHER_NAMES: Mapping[str, str] = {
    "clear": "晴",
    "cloudy": "多云",
    "rain": "雨",
    "storm": "雷雨",
    "fog": "雾",
}

_DAY_SECONDS = 86400


def weather_name(key: Optional[str]) -> Optional[str]:
    """天气键 → 中文名：已登记返回中文；内容包自定义未登记键回退原键（不崩溃）。"""
    if key is None:
        return None
    return DEFAULT_WEATHER_NAMES.get(key, key)


# -------------------------------------------------------------------------------------
# M36 查询状态组装（纯函数；cfg = settings dict 构造注入，None = 默认配置）
# -------------------------------------------------------------------------------------
def season_status(now: Optional[int] = None, cfg: Optional[Mapping] = None) -> dict:
    """M36 /时间 · 季节行数据组装。

    返回 {key, name, remaining_days, next_key}：
      key             当前季节键（默认 spring/summer/autumn/winter；内容包 enum 可自定义）
      name            中文名（春/夏/秋/冬；自定义键回退原键，同 weather_name 口径）
      remaining_days  距下次变化天数（IF07 秒 // 86400 整天下取，见文件头补白）
      next_key        下一季节键（按注入枚举顺序循环）

    审查 M3 批次2 P1-2：原用固定 SEASONS 求 idx/next_key + SEASON_NAMES[key] 中文名——
    自定义枚举（2026-08-26 拍板可配）会 ValueError/KeyError 崩溃。改用注入 wt 的
    `_seasons` 求 idx/next_key；中文名自定义键回退原键（不崩溃）。
    """
    wt = WorldTime(cfg)
    key = wt.season_now(now)
    idx = wt._seasons.index(key)
    remaining_days = wt.time_remaining("season", now) // _DAY_SECONDS
    return {
        "key": key,
        "name": SEASON_NAMES.get(key, key),
        "remaining_days": remaining_days,
        "next_key": wt._seasons[(idx + 1) % len(wt._seasons)],
    }


def period_status(now: Optional[int] = None, cfg: Optional[Mapping] = None) -> dict:
    """M36 /时间 · 时段行数据组装。

    返回 {key, name, remaining_minutes, next_key}：
      key               当前时段键（默认 dawn/noon/dusk/night/midnight；enum 可自定义）
      name              中文名（晨/午/昏/夜/午夜；自定义键回退原键）
      remaining_minutes 距下次变化分钟数（IF07 秒 // 60 整分下取）
      next_key          下一时段键（按注入枚举顺序循环）

    审查 M3 批次2 P1-2：同 season_status —— 改用注入 wt 的 `_periods` 求 idx/next_key，
    中文名自定义键回退原键（不崩溃）。
    """
    wt = WorldTime(cfg)
    key = wt.period_now(now)
    idx = wt._periods.index(key)
    remaining_minutes = wt.time_remaining("period", now) // 60
    return {
        "key": key,
        "name": PERIOD_NAMES.get(key, key),
        "remaining_minutes": remaining_minutes,
        "next_key": wt._periods[(idx + 1) % len(wt._periods)],
    }


def weather_status(
    map_id: str,
    pool_keys: object,
    now: Optional[int] = None,
    cfg: Optional[Mapping] = None,
    pool_source: Optional[str] = None,
) -> dict:
    """M36 /天气 · 数据组装。

    返回 {key, name, remaining_minutes, pool_label}：
      key               当前天气键——IF04 weather_now 语义（IF08 确定性抽签，审查 M3 批次2 P1-1）
      name              天气中文名（内容包自定义未登记键回退原键）
      remaining_minutes 距下次变化分钟数（IF07 秒 // 60 整分下取）
      pool_label        「使用本图天气池」（覆盖池）/「默认池」

    map_id:      玩家当前所在图（IF04 上下文绑定：weather_now 按图取生效池抽签）。
    pool_keys:   生效池键列表（IF05 map_pool 语义：覆盖池 else 默认池）；空/None → 回退默认池。
                 兼容 str 键与 {key,name,emoji} 对象两种条目形态（_pool_keys 归一）。
    pool_source: 生效池来源显式标注（"coverage"/"default"）；None = 按生效池与配置默认池比较推导。
    cfg:         settings dict（WorldTime 构造注入；None = 默认配置）。
    """
    wt = WorldTime(cfg)
    default_pool = wt.default_pool()  # 对象形态 default_pool 也返回干净键（P1-4 修复后）
    pool = wt._pool_keys(pool_keys) if isinstance(pool_keys, (list, tuple)) else []
    if not pool:
        pool = default_pool  # IF05/M38：空/缺省生效池 = 用默认池
    if pool_source == "coverage":
        label = "使用本图天气池"
    elif pool_source == "default":
        label = "默认池"
    else:
        # 集合比较（顺序无关，审查 M3 批次2 P1-4）：map_pool 返回排序键、default_pool 为配置
        # 序——同一池两序皆判「默认池」，否则真实调用方（传 map_pool 排序结果）恒误判覆盖池
        label = "使用本图天气池" if set(pool) != set(default_pool) else "默认池"
    # P1-1：IF04 weather_now 确定性抽签（IF08 已落地，替换原 pool[0] 补白占位）；生效池注入
    # map_pools 使 key 与 pool_label 同源（覆盖池同图同刻可不同天气，R19/R20）
    key = wt.weather_now(map_id, now, map_pools={map_id: pool} if pool else None)
    return {
        "key": key,
        "name": weather_name(key),
        "remaining_minutes": wt.time_remaining("weather", now) // 60,
        "pool_label": label,
    }