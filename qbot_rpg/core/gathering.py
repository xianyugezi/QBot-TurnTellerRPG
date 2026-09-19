"""批36 · X2 采集/挖掘引擎（核心纯函数）——qbot_rpg/core/gathering.py。

定位：把 `maps.gather_points`（细化_2a1d §一 GP-01~GP-11）的**采集结算**做成纯函数，
供 `/采集` 指令壳（`qbot_rpg/commands/gather_commands.py`）消费。本模块**零 IO、零
NoneBot import、零定时器/零睡眠**；rng / now / weather / state 全部可注入 → 确定性可测。

依据（逐条对得上定稿/细化，见 docs/采集挖掘_实现口径.md）：
  · 【总纲】L1280 `/采集`：在当前地图采集；怪物数量为 0=无限资源的地图可无限采集；
  · 【总纲】L1085「数量填 0 = 无限资源，无限刷」（无限资源图判定来源）；
  · 【总纲】L1086-1090 采集点配置（物品/概率）+ 稀有度标记（普通/稀有/金色，✨觉醒）；
  · 【时间天气】L204-207 / 2a4b R25：weather_mods rate_mult 乘出率（0=不出）+
    rarity_shift 平移档位（clamp 4 档）——**复用** core/weather_consumers.apply_weather_mods；
  · 2a1d §一 GP-01~GP-11：字段语义；L72 判定时序（季节/时段白名单 → 天气修正 →
    概率判定 → 入包）；GP-07 采空后 respawn_minutes 计时刷新；
  · 2a1d §五 V-1Z~V-5Z：结构/枚举/区间校验（落点 = content/map_models.validate_maps）；
  · 2a1d TC-01~TC-04：基础入包 / 天气联动 / 季节时段门控 / 刷新边界；
  · 【锻造】L151-158：挖掘/采集/垂钓/怪物掉落/商店 五路——**挖掘与采集是来源通道/产物族
    之分，定稿无独立 `/挖掘` 指令、gather_points schema 亦无通道字段**（审计四方 L405），
    故本引擎对**任意**采集点统一生效（矿石系「挖掘」与草药系「采集」同引擎）。

【工程补白 · 显式标注】（定稿/细化未显式定义处的实现口径；见口径文档 §五）
  P-1  无限资源图判定 = 地图任一刷怪行 `count == 0`（【总纲】L1280 与 L1085 的对应）。
  P-2  季节/时段归一：本模块自带中英双形态词表（与 commands/fishing_commands.py:
       237/248 同口径，但**不 import commands 层**——core 保持分层与纯函数）。
  P-3  冷却状态 = `state["<map_id>:<point_id>"] = ready_at(epoch 秒)`（懒计算；对齐
       core/alchemy_harvest.py 的 harvest_at 形态）。
  P-4  有效出率 = clamp(base_rate × rate_mult, 0, 1)（rate_mult 可 >1 → 乘积越界要收口）；
       `rate <= 0` 视为**该天气不出**（GP-10），不计入「落空」、不消耗 rng。
  P-5  季节/时段**缺失或不可识别**（ctx 未注入 / 引擎未加载）→ 视为不限（不误杀，与
       钓鱼 list_fishable_spots F-2 同口径；白名单只在「当前值可识别且不在名单」时拦截）。
  P-6  「采空」= **命中产出**才进冷却（GP-07 原文「采空后计时刷新」）；概率落空不消耗点
       （见口径文档 GA-6，待用户裁决，一句话可改）。
  P-7  rng 注入单源：参数 rng 优先 → 兜底 random 模块（生产由装配层注入 ctx["rng"]，
       测试一律注入；同 rng 同调用序必同结果）。
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.map_models import PERIODS_ENUM, SEASONS_ENUM
from qbot_rpg.core.weather_consumers import apply_weather_mods

__all__ = [
    "DEFAULT_RESPAWN_MINUTES",
    "GATHER_STATE_KEY",
    "GatherPoint",
    "parse_gather_points",
    "normalize_season",
    "normalize_period",
    "is_unlimited_map",
    "season_ok",
    "period_ok",
    "effective_rate_rarity",
    "state_key",
    "remaining_sec",
    "gather",
    "rarity_tiers",
]

# GP-07：respawn_minutes 缺省 10 分钟（校验器下限 1；引擎对缺省/坏值兜底）
DEFAULT_RESPAWN_MINUTES: float = 10.0

# 冷却状态落点（P-3）：player["gather_state"] = {"<map_id>:<point_id>": ready_at}
GATHER_STATE_KEY: str = "gather_state"

# 四季 / 五时段中文别名 → 英文枚举（P-2；同 fishing_commands._CN_SEASON / _CN_PERIOD）
_CN_SEASON: Mapping[str, str] = {
    "春": "spring", "夏": "summer", "秋": "autumn", "冬": "winter",
}
_CN_PERIOD: Mapping[str, str] = {
    "晨": "dawn", "午": "noon", "昏": "dusk", "夜": "night", "午夜": "midnight",
    "黎明": "dawn", "黄昏": "dusk", "昼": "noon",
}


# -------------------------------------------------------------------------------------
# 采集点解析（GP-01~GP-11）
# -------------------------------------------------------------------------------------
@dataclass(frozen=True)
class GatherPoint:
    """一个采集点的引擎视图（GP-01~GP-11 归一；坏值防御性兜底，校验归 map_models）。"""

    id: str
    item: str
    rate: float
    rarity: str
    name: str
    periods: Tuple[str, ...] = ()
    seasons: Tuple[str, ...] = ()
    respawn_minutes: float = DEFAULT_RESPAWN_MINUTES
    weather_mods: Any = ()


def _num(value: object, default: float) -> float:
    """数值兜底（bool 不算数值）；坏值 → default。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return float(value)


def _strlist(value: object) -> Tuple[str, ...]:
    """字符串列表归一（非 list / 含非串项 → 仅收合法串；缺省 → 空元组 = 不限）。"""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(v) for v in value if isinstance(v, str) and v)


def parse_gather_points(map_node: object) -> Tuple[GatherPoint, ...]:
    """地图节点 → 采集点元组（按 gather_points 原序；缺 id/item 的坏行跳过）。

    出参顺序 = 配置顺序（确定性；消息渲染与 rng 消费序都按此序）。
    """
    if not isinstance(map_node, Mapping):
        return ()
    raw = map_node.get("gather_points")
    if not isinstance(raw, list):
        return ()
    out: List[GatherPoint] = []
    for entry in raw:
        if not isinstance(entry, Mapping):
            continue
        gid = entry.get("id")
        item = entry.get("item")
        if not isinstance(gid, str) or not gid or not isinstance(item, str) or not item:
            continue
        name = entry.get("name")
        rarity = entry.get("rarity")
        out.append(GatherPoint(
            id=gid,
            item=item,
            rate=max(0.0, min(1.0, _num(entry.get("rate"), 0.0))),
            rarity=rarity if isinstance(rarity, str) and rarity else "normal",
            name=name if isinstance(name, str) and name else gid,
            periods=_strlist(entry.get("periods")),
            seasons=_strlist(entry.get("seasons")),
            respawn_minutes=max(0.0, _num(entry.get("respawn_minutes"),
                                          DEFAULT_RESPAWN_MINUTES)),
            weather_mods=entry.get("weather_mods") or (),
        ))
    return tuple(out)


# -------------------------------------------------------------------------------------
# 季节 / 时段归一与白名单（GP-05 / GP-06；P-2 / P-5）
# -------------------------------------------------------------------------------------
def normalize_season(value: object) -> Optional[str]:
    """季节双形态归一：英文枚举原样；中文名（春/…）→ 英文；不可识别 → None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    if v in SEASONS_ENUM:
        return v
    return _CN_SEASON.get(v)


def normalize_period(value: object) -> Optional[str]:
    """时段双形态归一：英文枚举原样；中文名（晨/午/昏/夜/午夜）→ 英文；不可识别 → None。"""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    if v in PERIODS_ENUM:
        return v
    return _CN_PERIOD.get(v)


def season_ok(point: GatherPoint, season: Optional[str]) -> bool:
    """季节白名单（GP-06）：名单空 = 全年不限；当前季不可识别（None）= 不限（P-5）。"""
    if not point.seasons or season is None:
        return True
    return season in point.seasons


def period_ok(point: GatherPoint, period: Optional[str]) -> bool:
    """时段白名单（GP-05）：名单空 = 全天不限；当前时段不可识别（None）= 不限（P-5）。"""
    if not point.periods or period is None:
        return True
    return period in point.periods


# -------------------------------------------------------------------------------------
# 无限资源图（【总纲】L1280 / L1085；P-1）
# -------------------------------------------------------------------------------------
def is_unlimited_map(map_node: object) -> bool:
    """无限资源图判定：地图任一刷怪行 `count == 0` → True（该图采集点不消耗/不进冷却）。"""
    if not isinstance(map_node, Mapping):
        return False
    spawns = map_node.get("monsters")
    if not isinstance(spawns, list):
        return False
    for row in spawns:
        if not isinstance(row, Mapping):
            continue
        cnt = row.get("count")
        if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt == 0:
            return True
    return False


# -------------------------------------------------------------------------------------
# 出率 / 稀有度（GP-03 / GP-04 / GP-08~GP-11；复用 weather_consumers）
# -------------------------------------------------------------------------------------
def effective_rate_rarity(point: GatherPoint, weather: object) -> Tuple[float, str]:
    """当前天气下的有效出率与稀有度（复用 2a4b R25 已实装 apply_weather_mods）。

    返回 (rate, rarity)：rate = clamp(base_rate × rate_mult, 0, 1)（P-4）；
    rarity 按 rarity_shift 平移并 clamp 4 档（normal/rare/gold/awakened）。
    无天气 / 无匹配修正 → 原值返回（GP-08 向后兼容）。
    """
    rate, rarity = apply_weather_mods(point.rate, point.rarity, point.weather_mods, weather)
    return max(0.0, min(1.0, rate)), rarity


def rarity_tiers() -> Tuple[str, ...]:
    """稀有度档位（4 档；供指令壳稀有度中文名映射，避免两处各自写档位表）。"""
    from qbot_rpg.core.weather_consumers import RARITY_TIERS  # noqa: PLC0415

    return tuple(RARITY_TIERS)


# -------------------------------------------------------------------------------------
# 冷却（GP-07 / TC-04；P-3）
# -------------------------------------------------------------------------------------
def state_key(map_id: object, point_id: object) -> str:
    """冷却状态键：`<map_id>:<point_id>`（P-3）。"""
    return f"{map_id}:{point_id}"


def _ready_at(state: object, key: str) -> float:
    """从 state 取 ready_at（兼容数值形态与 {"ready_at": ts} 形态；坏值 → 0）。"""
    if not isinstance(state, Mapping):
        return 0.0
    raw = state.get(key)
    if isinstance(raw, Mapping):
        raw = raw.get("ready_at")
    return _num(raw, 0.0)


def remaining_sec(state: object, map_id: object, point_id: object, now: float) -> float:
    """剩余冷却秒数（>0 = 冷却中；<=0 = 可采）。纯函数。"""
    left = _ready_at(state, state_key(map_id, point_id)) - float(now)
    return left if left > 0 else 0.0


# -------------------------------------------------------------------------------------
# 采集结算（GP-01~GP-11 全链）
# -------------------------------------------------------------------------------------
def _resolve_rng(rng: Any) -> Any:
    """rng 注入单源（P-7）：有 random() 的注入源优先；缺省 → random 模块。"""
    if rng is not None and callable(getattr(rng, "random", None)):
        return rng
    return random


def gather(
    map_node: object,
    map_id: object,
    *,
    season: object = None,
    period: object = None,
    weather: object = None,
    state: object = None,
    rng: Any = None,
    now: object = None,
) -> Dict[str, Any]:
    """一次 `/采集` 的完整结算（纯函数；不改入参 state，冷却增量经 state_updates 回传）。

    判定顺序（2a1d L72 写死）：季节/时段白名单 → 冷却 → 天气修正 → 概率判定 → 产出。

    出参 dict：
      ok            bool            True = 地图有采集点（不代表一定采到）
      reason        str             "no_points"（无采集点）/ ""（正常）
      map_id        str
      unlimited     bool            无限资源图（P-1；不消耗点）
      now           float           本次结算时钟（秒）
      produced      list[dict]      命中产出：{point_id,name,item,rarity,base_rarity,
                                    rate,base_rate}
      cooling       list[dict]      冷却中：{point_id,name,remaining_sec,respawn_minutes}
      gated         list[dict]      季节/时段不满足：{point_id,name,seasons,periods}
      blocked       list[dict]      该天气不出：{point_id,name,weather}
      missed        list[dict]      概率落空：{point_id,name,rate}
      state_updates dict            耗点增量：{<map>:<point>: ready_at 秒}
    """
    points = parse_gather_points(map_node)
    if not points:
        return {"ok": False, "reason": "no_points", "map_id": str(map_id),
                "unlimited": False, "now": _num(now, 0.0), "produced": [], "cooling": [],
                "gated": [], "blocked": [], "missed": [], "state_updates": {}}

    season_key = normalize_season(season)
    period_key = normalize_period(period)
    unlimited = is_unlimited_map(map_node)
    now_ts = _num(now, time.time())
    rng_obj = _resolve_rng(rng)

    produced: List[Dict[str, Any]] = []
    cooling: List[Dict[str, Any]] = []
    gated: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    missed: List[Dict[str, Any]] = []
    updates: Dict[str, float] = {}

    for point in points:
        # ① 季节 / 时段白名单（GP-05/GP-06；不命中 → 动作不可用，空态文案）
        if not season_ok(point, season_key) or not period_ok(point, period_key):
            gated.append({"point_id": point.id, "name": point.name,
                          "seasons": list(point.seasons), "periods": list(point.periods)})
            continue
        # ② 冷却（GP-07；无限资源图跳过）
        if not unlimited:
            left = remaining_sec(state, map_id, point.id, now_ts)
            if left > 0:
                cooling.append({"point_id": point.id, "name": point.name,
                                "remaining_sec": left,
                                "respawn_minutes": point.respawn_minutes})
                continue
        # ③ 天气修正（GP-08~GP-11）
        rate, rarity = effective_rate_rarity(point, weather)
        if rate <= 0:
            # GP-10：rate_mult 0 = 该天气不出（不消耗 rng、不计落空）
            blocked.append({"point_id": point.id, "name": point.name, "weather": weather})
            continue
        # ④ 概率判定（GP-03）
        if float(rng_obj.random()) >= rate:
            missed.append({"point_id": point.id, "name": point.name, "rate": rate})
            continue
        # ⑤ 产出（P-6：命中才采空进冷却）
        produced.append({
            "point_id": point.id, "name": point.name, "item": point.item,
            "rarity": rarity, "base_rarity": point.rarity,
            "rate": rate, "base_rate": point.rate,
        })
        if not unlimited:
            updates[state_key(map_id, point.id)] = now_ts + point.respawn_minutes * 60.0

    return {
        "ok": True,
        "reason": "",
        "map_id": str(map_id),
        "unlimited": unlimited,
        "now": now_ts,
        "produced": produced,
        "cooling": cooling,
        "gated": gated,
        "blocked": blocked,
        "missed": missed,
        "state_updates": updates,
    }
