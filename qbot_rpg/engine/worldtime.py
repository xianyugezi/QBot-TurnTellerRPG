"""世界时间引擎 —— M3 批次0·路C（M31）时间引擎骨架 + 批次1·路D（M33/M34）变化检测与懒广播。

依据：细化_2a4a_时间引擎（§1 三周期注册表 / §1.3 可配项 / §二 锚点整除公式 / §3.1 变化检测钩子
      / §3.2 配置即重排 / §3.3 一次 ≤3 条顺序固定 / §4.3 跨群去重）
      + m3_shared_contract §5（5.1 周期注册表 / 5.2 time_cycle 配置段 / 5.3 IF01~IF10 接口 / 锚点公式）
      + 细化_2a4c §1.1（IF09 check_changes / IF10 maybe_broadcast）/ §1.2（广播配置默认关）。
本文件 = 细化_2a4c §1.1 公开接口的「游戏周期层」纯函数骨架：
  批次0·路C 交付 IF01~IF07（锚点整除公式 / 查询 / 倒计时）；
  批次1·路D 追加 IF09/IF10（三周期独立推进的变化检测钩子 + 懒广播纯文案产出）；
  批次2·路G 追加 IF04/IF05/IF08（天气查询 / 生效池 / 等概率确定性抽签）+ validate_weather_pool：

  IF01 is_enabled()             系统总开关（读 settings.time_cycle.enabled，缺省 true）
  IF02 season_now(now)          季节查询（spring/summer/autumn/winter；0 基 0春 1夏 2秋 3冬）
  IF03 period_now(now)          时段查询（dawn/noon/dusk/night/midnight；0 基 0晨 1午 2昏 3夜 4午夜）
  IF04 weather_now(map_id, now=None, map_pools=None)  当前图当前天气键（上下文绑定；tick=cycle_tick("weather")）
  IF05 map_pool(map_id, map_pools=None)               生效池键列表：覆盖池 else 默认池（排序供种子）
  IF06 cycle_tick(kind, now)    周期索引/节拍（season/period/weather 整除公式，纯函数）
  IF07 time_remaining(kind,now) 距下次变化秒数（/时间 数据源）
  IF08 map_weather(map_id, tick, now=None, map_pools=None)  生效池等概率确定性抽签（sha256 纯函数）
  IF09 check_changes(cached, player_ctx=None)  变化检测钩子：比较缓存索引与重算值 → list[Change]
  IF10 maybe_broadcast(changes, ctx=None, seen=None)  懒广播：broadcast.enabled 缺省 false → []
      （按 template 占位符产出播报文案列表，零消息发送；去重状态由路E 持久化，本路仅读不改）

锚点（契约 §5.3）：ANCHOR = 2000-01-01 00:00:00 UTC+8；now = UTC+8 秒级时间戳（Unix epoch 秒，
缺省=当前）。season_idx=floor((now−ANCHOR)/(season_days×86400))%4、period_idx=…%5、
weather_tick=…不取模。零定时器、不存历史、随时可重算。

【工程补白】
  - 配置经构造注入：WorldTime(cfg) 接收调用方传入的 settings dict（懒加载，引擎不读文件、不做 IO）；
    周期值一律由锚点公式重算（契约「零定时器、不存历史、随时可重算」）。
  - 配置缺省 = 细化_2a4a §1.3 拍板值：enabled=true / season_days=7 / period_minutes=60 /
    weather_minutes=60；weather.default_pool 默认「5 种」的具体键（clear/cloudy/rain/storm/fog）
    为 2a4a §1.1「如 …」示例落值（定稿未拍死具体键，故标注补白）。
  - IF09/IF10 展示字段【工程补白】：季节/时段中文名（春/夏/秋/冬 · 晨/午/昏/夜/午夜）依据
    2a4a §1.1「中文名（展示用）」列；emoji 定稿未拍死具体符号，取本模块约定值（调用方可经
    Change['emoji'] 覆盖）；天气键值解析（IF04/IF08 确定性抽签）属批次2——本路天气播报文案
    需调用方取键后挂 Change['name'/'emoji']，未挂载则占位符留空（纯透传，不冒充解析）。
  - IF09 签名补白：契约伪码为 check_changes(player, map_id)；本路引擎侧收 cached 缓存索引 +
    player_ctx（可选带 now 键注入时间戳，缺省=当前，纯函数可测）；天气值解析留待批次2。
  - 批次2（IF04/IF05/IF08）补白：map_pools 为调用方注入的 {map_id: [天气键]} 覆盖池映射
    （maps.json 顶层 weather_pool 由调用方装载后传入；本模块纯函数零 IO，不读 maps.json）；
    池条目兼容两种形态——str 键（既有 IF）或 {key,name,emoji} 对象（细化_2a4b §1.2，
    validate_weather_pool 按对象形态红拦：非空 / 键唯一 / 键+中文名齐全）。
  - 抽签确定性（细化_2a4b §2.3 R11/R12）：seed = sha256(生效池键列表排序后 + str(tick))，
    同 tick + 同池 → 跨群/跨进程/重启一致、重启不重抽；等概率无权重（R10），权重为后续版本预留。
  - 类型/下限合法性交 validate_time_cycle()（本模块）在 load 阶段红拦；引擎对坏配置惰性回退默认
    不崩溃（与契约 IF11 存档「缺补默认多忽略」同口径，字段级缺省）。
  - 校验器收口：validate_time_cycle(settings, report) 供主 agent 接入 check_pack —— report 兼容
    content/validator.py `_Checker._err(module, field, kind, **detail)` 同签名收集器，或带
    `.errors` 列表的收集器（二选一）。

零 NoneBot import（3a R1）；本模块仅标准库。
"""

from __future__ import annotations

import hashlib
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
    "validate_weather_pool",
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

# -------------------------------------------------------------------------------------
# IF09/IF10 变化检测 + 懒广播（M3 批次1·路D 追加）：kind → time_state 缓存键 / 播报顺序 /
# 展示名与 emoji（工程补白见文件头）
# -------------------------------------------------------------------------------------
# kind → time_state 缓存索引键（契约 IF11 time_state 字段名：season_idx/period_idx/weather_tick）
_CHANGE_CACHE_KEY: dict = {"season": "season_idx", "period": "period_idx", "weather": "weather_tick"}
# 变化/播报固定顺序：季节→时段→天气（契约 IF09「一次 ≤3 条顺序固定 季节→时段→天气」）
_CHANGE_ORDER: tuple = ("season", "period", "weather")
# 展示中文名（细化_2a4a §1.1「中文名（展示用）」列；天气键 = 内容包自定义 → 需 IF04/IF08 解析）
_SEASON_CN: tuple = ("春", "夏", "秋", "冬")
_PERIOD_CN: tuple = ("晨", "午", "昏", "夜", "午夜")
# 展示 emoji【工程补白：定稿未拍死具体符号，取本模块约定值；调用方可经 Change['emoji'] 覆盖】
_SEASON_EMOJI: tuple = ("🌸", "☀️", "🍂", "❄️")
_PERIOD_EMOJI: tuple = ("🌅", "☀️", "🌇", "🌙", "🌌")
# 播报类型中文名（template {type} 占位符）
_TYPE_CN: dict = {"season": "季节", "period": "时段", "weather": "天气"}
# 缺省播报模板（细化_2a4a §1.3 / 细化_2a4c §1.2：`{emoji} {name}`）
_DEFAULT_BROADCAST_TEMPLATE = "{emoji} {name}"

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

    # ---- IF09 变化检测钩子（纯函数；比较缓存索引与公式重算值） ----
    def check_changes(self, cached: Optional[Mapping[str, object]],
                      player_ctx: Optional[Mapping[str, object]] = None) -> List[dict]:
        """IF09 变化检测钩子：比较 time_state 缓存索引与公式重算值 → 变化列表（list[Change]）。

        cached:      time_state 缓存索引 dict（{season_idx, period_idx, weather_tick}）；
                     缺键 / 非 Mapping = 该 kind 无历史缓存 → 报首次变化（old=None，契约「首次全变化」）。
        player_ctx:  预留上下文（契约伪码签名含 player/map_id；天气值解析 IF04/IF08 属批次2，
                     见文件头补白）。可选带 ``now`` 键注入 UTC+8 时间戳（缺省=当前，纯函数可测）。
        返回 Change = {kind, old, new}；顺序固定 季节→时段→天气，一次 ≤3 条，每条 kind 只出现一次
        （离线跨多周期只报最新值——直接比较缓存索引与当前重算值，不逐条追报；与 IF11
        「缓存与重算相等不播」同口径）。纯函数，零 IO。"""
        cache = cached if isinstance(cached, Mapping) else {}
        raw_now = player_ctx.get("now") if isinstance(player_ctx, Mapping) else None
        now: Optional[int] = raw_now if isinstance(raw_now, int) else None
        changes: List[dict] = []
        for kind in _CHANGE_ORDER:
            new = self.cycle_tick(kind, now)
            old = cache.get(_CHANGE_CACHE_KEY[kind])
            if old != new:
                changes.append({"kind": kind, "old": old, "new": new})
        return changes[:3]  # 上限 3 条（三 kind 天然 ≤3，切片兜底）

    # ---- IF10 懒广播（默认关；纯文案产出，零消息发送） ----
    def maybe_broadcast(self, changes: Optional[object], ctx: Optional[Mapping[str, object]] = None,
                        seen: Optional[Mapping[str, object]] = None) -> List[str]:
        """IF10 懒广播：broadcast.enabled 缺省 false（或 time_cycle.enabled=false）→ 不播报，返回 []。

        开启后按 template 占位符 {type,name,emoji,map} 为每条变化生成一行播报文案（缺省模板
        `{emoji} {name}`）；季节→时段→天气顺序，一次 ≤3 条；「合并一行」由调用方 join 本列表
        （本路只产出文案列表，零消息发送）。
        跨群去重：ctx/seen 传「已播索引」dict（{season_idx, period_idx, weather_tick}），
        某 kind 的新值 == 已播索引 → 该条跳过（与 IF11「缓存与重算相等不播」同口径）；
        去重状态由路E 持久化进 data/time_state，本路仅读不改（纯函数）。
        展示字段：type/name/emoji/map 优先取 Change 自带（天气需调用方经 IF04/IF08 取键后挂载），
        缺省由引擎按 kind+new 自解（季节/时段中文名 + emoji 约定值，见文件头补白）。"""
        if not self.is_enabled() or not self._broadcast_enabled():
            return []
        if not isinstance(changes, (list, tuple)):
            return []
        seen_idx: Mapping[str, object] = seen if isinstance(seen, Mapping) else {}
        if not seen_idx and isinstance(ctx, Mapping):
            ctx_seen = ctx.get("seen")
            if isinstance(ctx_seen, Mapping):
                seen_idx = ctx_seen
        template = self._broadcast_template()
        lines: List[str] = []
        for ch in changes:
            if not isinstance(ch, Mapping):
                continue
            kind = ch.get("kind")
            new = ch.get("new")
            ckey: Optional[str] = _CHANGE_CACHE_KEY.get(kind) if isinstance(kind, str) else None
            if ckey is not None and seen_idx.get(ckey) == new:
                continue  # 已播索引命中 → 跨群去重（该周期已播过，不重复）
            lines.append(self._render_broadcast(ch, template, ctx))
        return lines[:3]  # 一次 ≤3 条（季节+时段+天气）

    def _broadcast_enabled(self) -> bool:
        """广播总开关：读 broadcast.enabled（缺省 false）；坏配置（非 bool）→ false。"""
        sec = self._tc.get("broadcast")
        if not isinstance(sec, Mapping):
            return False
        v = sec.get("enabled", False)
        return v if isinstance(v, bool) else False

    def _broadcast_template(self) -> str:
        """播报模板：读 broadcast.template（缺省 `{emoji} {name}`）；空/非字符串 → 缺省。"""
        sec = self._tc.get("broadcast")
        if not isinstance(sec, Mapping):
            return _DEFAULT_BROADCAST_TEMPLATE
        v = sec.get("template")
        return v if isinstance(v, str) and v else _DEFAULT_BROADCAST_TEMPLATE

    def _render_broadcast(self, ch: Mapping[str, object], template: str,
                          ctx: Optional[Mapping[str, object]]) -> str:
        """把单条 Change 渲染进模板：{type,name,emoji,map} 占位符替换（缺省自解 + 调用方覆盖）。"""
        kind = ch.get("kind")
        new = ch.get("new")
        type_ = ch.get("type")
        if type_ is None:
            type_ = _TYPE_CN.get(kind, kind if isinstance(kind, str) else "")
        name = ch.get("name")
        if name is None:
            name = self._value_cn(kind, new)
        emoji = ch.get("emoji")
        if emoji is None:
            emoji = self._value_emoji(kind, new)
        map_ = ch.get("map")
        if map_ is None and isinstance(ctx, Mapping):
            map_ = ctx.get("map")
        if map_ is None:
            map_ = ""
        return (template.replace("{type}", str(type_))
                        .replace("{name}", str(name))
                        .replace("{emoji}", str(emoji))
                        .replace("{map}", str(map_)))

    @staticmethod
    def _value_cn(kind: object, index: object) -> str:
        """kind+index → 展示中文名：季节/时段自解；天气键需 IF04/IF08 解析 → 空（调用方挂 name）。"""
        if kind == "season" and isinstance(index, int):
            return _SEASON_CN[index % len(_SEASON_CN)]
        if kind == "period" and isinstance(index, int):
            return _PERIOD_CN[index % len(_PERIOD_CN)]
        return ""

    @staticmethod
    def _value_emoji(kind: object, index: object) -> str:
        """kind+index → 展示 emoji（本模块约定值，可被 Change['emoji'] 覆盖）；天气 → 空。"""
        if kind == "season" and isinstance(index, int):
            return _SEASON_EMOJI[index % len(_SEASON_EMOJI)]
        if kind == "period" and isinstance(index, int):
            return _PERIOD_EMOJI[index % len(_PERIOD_EMOJI)]
        return ""

    # ---- IF05 生效池 / IF08 等概率确定性抽签 / IF04 天气查询（M3 批次2·路G 追加） ----
    # 依据：细化_2a4b_天气引擎（§1.2 默认池结构 / §2.2-2.3 等概率抽签与确定性 seed /
    #      §3.1-3.2 地图 weather_pool 覆盖 / §6.1 纯函数签名）+ m3_shared_contract §6（6.1 核心规则）。
    @staticmethod
    def _pool_keys(pool: object) -> List[str]:
        """把池条目提取为天气键列表：str 键直接取；{key,...} 对象取 .key；非法条目过滤（防御）。

        兼容两种配置形态（见文件头补白）：① 字符串键列表（既有 IF）；② {key,name,emoji} 对象列表
        （细化_2a4b §1.2）。纯函数，无 IO。
        """
        if not isinstance(pool, (list, tuple)):
            return []
        keys: List[str] = []
        for entry in pool:
            if isinstance(entry, Mapping):
                k = entry.get("key")
                if isinstance(k, str) and k:
                    keys.append(k)
            elif isinstance(entry, str) and entry:
                keys.append(entry)
        return keys

    def _default_pool_raw(self) -> object:
        """cfg.weather.default_pool 原始配置（保留条目形态）；缺省/空数组 → DEFAULT_POOL（R18）。"""
        sec = self._tc.get("weather")
        if isinstance(sec, Mapping):
            p = sec.get("default_pool")
            if isinstance(p, (list, tuple)) and p:
                return p
        return list(DEFAULT_POOL)

    def map_pool(self, map_id: str, map_pools: Optional[Mapping[str, object]] = None) -> List[str]:
        """IF05 生效池：地图覆盖池 else 默认池；返回生效池键列表（排序后供种子计算）。

        map_pools: 调用方注入的 {map_id: [天气键]} 覆盖池映射（maps.json 顶层 weather_pool 由调用方
        装载后传入；本模块零 IO 不读文件）。语义（细化_2a4b §3.2 R13/R18）：
          覆盖池非空数组且提取出合法键 → 覆盖生效（R19：该图天气按覆盖池抽签）；
          缺省 / 空数组 / 键全非法 → 回退默认池（R18：空数组或未配置 = 统一用默认池）。
        覆盖池只改取值不改节拍（R20：同一 tick 不同图可不同值，变化时刻全世界一致）。
        返回列表恒排序（同池跨端一致，seed 输入与配置顺序无关，细化_2a4b §6.1）。
        """
        if isinstance(map_pools, Mapping):
            ov = map_pools.get(map_id)
            if isinstance(ov, (list, tuple)) and ov:
                keys = self._pool_keys(ov)
                if keys:
                    return sorted(keys)
        return sorted(self._pool_keys(self._default_pool_raw()))

    def map_weather(self, map_id: str, tick: int, now: Optional[int] = None,
                    map_pools: Optional[Mapping[str, object]] = None) -> str:
        """IF08 确定性抽签：生效池等概率抽一签，返回天气键。

        seed = sha256(生效池键列表排序后 + str(tick))（细化_2a4b §2.3 R11/L58）：
          idx = int(seed.hexdigest(), 16) % len(pool) → 等概率命中（每次变化 tick+1 抽一，R10）。
        确定性语义（R12）：同 tick + 同池 → 跨群/跨进程/重启一致同值、重启不重抽（懒计算刚需，
        无定时器也能重算出与上次一致的值）；池编辑（增删键改变键列表）→ 后续抽签序列整体重排（R14）。
        跨年/大 tick 稳定：weather_tick 只增不取模（IF06），tick 为大整数/负数均按公式逐字计算。
        等概率（v1 无权重）：权重倍率为后续版本预留——届时并入 seed 或改加权选择，本函数保持纯净。
        now 参数为 IF04/契约签名兼容保留（本函数以显式 tick 为准，不参与计算）。
        防御：生效池为空（调用方坏配置/条目全非法）→ 返回 ""，不抛异常。纯函数，零 IO。
        """
        pool = self.map_pool(map_id, map_pools)
        if not pool:
            return ""  # 防御：空池 → 无天气可取
        seed = hashlib.sha256(("".join(sorted(pool)) + str(tick)).encode("utf-8")).hexdigest()
        idx = int(seed, 16) % len(pool)
        return pool[idx]

    def weather_now(self, map_id: str, now: Optional[int] = None,
                    map_pools: Optional[Mapping[str, object]] = None) -> str:
        """IF04 天气查询：玩家当前所在图当前天气键（上下文绑定，细化_2a4b §5.1 R29）。

        当前 weather_tick = cycle_tick("weather", now)（IF06，只增不取模）→ 交给 IF08 map_weather
        从生效池抽签；now 缺省 = 当前 UTC+8 epoch 秒。纯函数：同刻同参必同值，随时可重算。
        """
        tick = self.cycle_tick("weather", now)
        return self.map_weather(map_id, tick, now=now, map_pools=map_pools)


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


def validate_weather_pool(cfg: Mapping[str, object], report: object) -> None:
    """默认天气池 V4 校验（细化_2a4b §1.2 R3/R4 + m3_shared_contract §6.2 V4）。

    独立入口供主 agent 收口接入 check_pack（与 validate_time_cycle 并存：后者校验「字符串池」形态的
    time_cycle 段；本函数按细化_2a4b §1.2 的 {key,name,emoji} 对象形态红拦，与 R3/R4 逐条对齐）：
      - default_pool 非空（至少 1 种天气，删到 0 硬拦，R4）；
      - 键唯一（key 全池唯一，R3）；
      - 键 + 中文名齐全（key / name 任一缺失或非字符串红拦，R3）。
    cfg:    完整 settings dict（可含 time_cycle.weather.default_pool；缺省段/缺字段 = 框架默认，零红拦）。
    report: 收集器（二选一）——a) `_err(module, field, kind, **detail)`（与 content/validator.py
            `_Checker` 同签名）；b) `errors: list`（追加 {"module","field","kind","detail"} dict）。
    红拦均带人话报错 detail["msg"]（如「天气『雪』缺中文名 name」），供命令层直接拼用户文案。
    纯函数，零 IO，零 NoneBot。
    """
    if not isinstance(cfg, Mapping):
        return
    tc = cfg.get("time_cycle")
    if not isinstance(tc, Mapping):
        return
    weather = tc.get("weather")
    if not isinstance(weather, Mapping) or "default_pool" not in weather:
        return  # 缺省段/缺字段 = 用框架默认，零红拦
    pool = weather["default_pool"]
    base = "time_cycle.weather.default_pool"
    if not isinstance(pool, (list, tuple)):
        _emit(report, "settings", base, "V4", rule="pool_type", got=pool,
              msg="默认天气池要填数组")
        return
    if len(pool) == 0:
        _emit(report, "settings", base, "V4", rule="pool_empty", got=pool,
              msg="默认天气池至少要 1 种天气")
        return
    seen: dict = {}
    for i, entry in enumerate(pool):
        field = f"{base}.{i}"
        if not isinstance(entry, Mapping):
            _emit(report, "settings", field, "V4", rule="pool_entry_type", got=entry,
                  msg=f"默认天气池第 {i} 项要填对象（含 key/name）")
            continue
        key = entry.get("key")
        if not isinstance(key, str) or not key:
            _emit(report, "settings", field, "V4", rule="pool_key_missing", got=key,
                  msg="默认天气池天气条目缺 key（英文小写机器键）")
        elif key in seen:
            _emit(report, "settings", field, "V4", rule="pool_key_dup", key=key,
                  msg=f"默认天气池天气键重复了：{key}")
        else:
            seen[key] = i
        name = entry.get("name")
        label = key if isinstance(key, str) and key else f"第 {i} 项"
        if not isinstance(name, str) or not name:
            _emit(report, "settings", field, "V4", rule="pool_name_missing", key=key,
                  msg=f"天气『{label}』缺中文名 name")
