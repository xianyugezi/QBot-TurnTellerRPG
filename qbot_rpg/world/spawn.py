"""刷怪/补刷 Spawner（M3 实装 · 本里程碑仅签名）。

职责（细化_3a §2.1；/ 细化_2a1b_通道规则与刷怪）：地图点/通道刷新、野图 BOSS 刷新、
全体限购补货；离线封顶 N 小时（【框架】L194-205：离线补刷按离线时长封顶，防挂机刷资源）。

M3 实装依据：细化_2a1b（刷新规则/通道刷怪）、细化_2a1d（字段扩展）、细化_2a4a（时间引擎联动）。
零 NoneBot import（3a R1）；空态 = 领域异常/返回约定值，不拼用户文案（R4）。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

from qbot_rpg.content.map_models import SPAWN_COUNT_DEFAULT, SpawnDef

# 现实钟点层时区（对齐引擎 worldtime：UTC+8，细化_2a4c §1.0）
_TZ_UTC8 = timezone(timedelta(hours=8))

__all__ = ["Spawner", "SpawnManager"]

_NOT_IMPL_MSG = "M3 实装：刷新/补刷（细化_2a1b / 细化_2a1d）"

# 离线补刷封顶小时数（【框架】L194-205），M3 从 content 配置读取覆盖。
DEFAULT_OFFLINE_CAP_HOURS: int = 12


class Spawner:
    """刷怪/补刷器（离线封顶 N 小时）。M3 实装，本里程碑仅签名。"""

    def __init__(self) -> None:
        self._registry = None

    def refresh_map(self, map_id: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def catch_up_offline(
        self,
        player: Any,
        since_tick: int,
        cap_hours: int = DEFAULT_OFFLINE_CAP_HOURS,
    ) -> Dict[str, Any]:
        """离线补刷：按离线时长补刷但封顶 cap_hours（防挂机）。M3 实装。"""
        raise NotImplementedError(_NOT_IMPL_MSG)

    def refill_world_stock(self, key: str) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)


# =====================================================================================
# SpawnManager —— M3 批次4·路L（M08 补刷懒计算 + M09 时段/季节出没边界）
#
# 依据：细化_2a1b §二/§三 + 2a4c §3 + m3_shared_contract §2.3
#   - 细化_2a1b §二（刷怪配置 spawn 表字段 / R14-R26）+ §三（时段联动出没判定链 R27-R30）
#   - 细化_2a4c §3（出没链路入口 E1 进入图补刷 / E2 周期边界存在性变更 / E3 刷新计时折算；
#     S1 spawn_available / S2 respawn_interval）
#   - m3_shared_contract §2.3（spawn 行七字段表 + 出没语义 R16-R22：AND 叠加、时段结束移除
#     「对方逃跑了」、天气不驱逐、max_alive 聚合）
#   - M08（补刷懒计算：按时间差折算补刷，零定时器）/ M09（时段/季节限定出没与边界移除）
#     —— docs/实现层规划文档.md L480-488
#
# 核心设计（契约「零定时器、不存历史、随时可重算」）：
#   - 所有方法为纯函数：输入 spawn 行 + now + world_state → 计算「应生成/应移除」结果；
#     不持有场上状态、不跑定时器（M43 探针口径）。
#   - worldtime 为注入的时间引擎（鸭子类型）：提供 season_now(now) / period_now(now) /
#     weather_now(map_id, now)（后两者缺省 → 对应维度退化为不限 / 权重默认 1）。不 import 引擎。
#   - spawn_rows 双形态兼容：SpawnDef 访问器（content/map_models.SpawnDef）或 raw dict。
#
# 【工程补白】（docs 未拍死、遵循「只建议不限制」总纲）：
#   1. 行 key（row_key）= spawn 行 enemy 引用（id/name，供「对方逃跑了」文案直接取怪名）；
#      同图多行引用同一 enemy 则共享 world_state 键。无 enemy 的坏行退化为行序号 str(index)。
#   2. initial_spawn 不含天气过滤（0=不刷 归 E3/refresh，与 S1 spawn_available 同口径）；
#      进入地图统一走 refresh（E1 含天气 0 拦截）。
#   3. active_time 窗口半开 [from, to)：起点含、终点不含（"20:00"-"06:00" → 20:00 起、06:00 止）。
#   4. 返回的每个 dict = 一条「应生成指令」：spawn 行七字段（index 诊断序号）+ spawn_count
#      （本次应生成数量；initial=count 上限，refresh=折算补刷量 ≤ 缺口）。
# =====================================================================================


class SpawnManager:
    """地图 spawn 行出没/补刷管理器（M08 懒补刷 + M09 时段/季节出没边界）。

    接口（对应细化_2a4c §3 出没链路）：
      - initial_spawn(now=None) -> list[dict]             初始出没（E1 前置；filter_eligible 过滤）
      - refresh(map_id, now, world_state) -> list[dict]   懒补刷（E1/E3；按时间差折算补足 count 上限）
      - filter_eligible(spawn_row, now) -> bool           S1 出没判定（active_time∩seasons∩periods AND）
      - zone_expire_removal(spawn_rows, now, world_state) -> list[str]  E2 周期边界移除（「对方逃跑了」）

    world_state 契约（调用方维护并持久化，本类只读不改）：
      {"last_kill_time": {row_key: epoch秒}, "alive_count": {row_key: n}}
    row_key 见文件头补白 1（= enemy 引用）。缺键 = 无击杀记录 / 场上 0 只。
    """

    def __init__(
        self,
        spawn_rows: Optional[Any] = None,
        worldtime: Optional[Any] = None,
    ) -> None:
        """spawn_rows：地图 spawn 行可迭代（SpawnDef 或 raw dict 混排；非法行跳过）。"""
        rows: List[SpawnDef] = []
        if spawn_rows is not None:
            for i, entry in enumerate(spawn_rows):
                row = self._coerce(entry, i)
                if row is not None:
                    rows.append(row)
        self._rows: Tuple[SpawnDef, ...] = tuple(rows)
        self._worldtime: Optional[Any] = worldtime

    # ------------------------------------------------------------------ 公开接口

    def initial_spawn(self, now: Optional[int] = None) -> List[Dict[str, Any]]:
        """初始出没（M07/M09）：当前时段/季节/钟点可出没的 spawn 行（filter_eligible 过滤）。

        返回 list[dict]：每条 = {spawn 行七字段 + spawn_count=count 上限}，调用方按 spawn_count 生成。
        天气过滤不在此（0=不刷 归 E3/refresh，见文件头补白 2）。
        """
        out: List[Dict[str, Any]] = []
        for row in self._rows:
            if not self.filter_eligible(row, now):
                continue  # M09：非限定季节/时段/钟点不刷该怪（TC-10/11/16）
            out.append(self._as_dict(row, spawn_count=self._row_cap(row)))
        return out

    def refresh(
        self,
        map_id: str,
        now: Optional[int],
        world_state: Any,
    ) -> List[Dict[str, Any]]:
        """懒补刷（E1/M08，零定时器纯计算）：比较 last_kill_time + respawn_interval vs now，补足 count 上限。

        每行（需 filter_eligible 出没满足）：
          - 场上存活 == count 上限 → 不补（TC-08）；
          - 距上次击杀 < 有效刷新间隔 → 不补（懒计算：当下才结算，M08「不存刷新历史」）；
          - 否则补刷量 = floor(时间差 / 有效间隔)，截断到缺口（count−存活）；
          - 无击杀记录（缺 last_kill_time）→ 全量补足缺口（首次进入/初始态）。
        有效刷新间隔 = respawn_minutes×60 ÷ weather_weights[当前天气]（E3/S2：weight≥1 更快、
        0<w<1 更慢、0=该天气不刷；未配权重/无天气源默认 1）。
        返回 list[dict]：每条 = {spawn 行七字段 + spawn_count=本次应生成数量}。
        """
        state = world_state if isinstance(world_state, Mapping) else {}
        last_raw = state.get("last_kill_time")
        last_kill: Mapping[object, object] = last_raw if isinstance(last_raw, Mapping) else {}
        alive_raw = state.get("alive_count")
        alive: Mapping[object, object] = alive_raw if isinstance(alive_raw, Mapping) else {}

        spawned: List[Dict[str, Any]] = []
        for row in self._rows:
            if not self.filter_eligible(row, now):
                continue  # 出没条件不满足（M09）→ 本轮不补刷
            key = self._row_key(row)
            current = alive.get(key, 0)
            if not (isinstance(current, int) and not isinstance(current, bool)):
                current = 0
            cap = self._row_cap(row)
            gap = cap - current
            if gap <= 0:
                continue  # 已满 count 上限（TC-08）→ 无需补刷
            interval = self._respawn_interval_seconds(row, map_id, now)
            if interval is None:
                continue  # 权重 0（R26/E3/TC-14）或缺 respawn_minutes → 该天气下不刷
            last = last_kill.get(key)
            if isinstance(last, (int, float)) and not isinstance(last, bool):
                elapsed = self._coerce_now(now) - int(last)
                if elapsed < 0:
                    continue  # 击杀记录在未来（时钟异常）→ 防御不补
                if elapsed < interval:
                    continue  # 未到 respawn 间隔 → 懒计算不补（M08/TC-09）
                need = int(elapsed // interval)
            else:
                need = gap  # 无击杀记录 → 全量补足缺口
            if need <= 0:
                continue
            need = min(need, gap)  # 截断到缺口（M08 验收：floor(时间差/间隔) 截断到缺口）
            spawned.append(self._as_dict(row, spawn_count=need))
        return spawned

    def filter_eligible(self, spawn_row: Any, now: Optional[int]) -> bool:
        """S1 出没判定（细化_2a4c §3.1）：active_time ∩ seasons ∩ periods 全 AND 叠加，全部满足才出没。

        - active_time：现实钟点窗口（空=全天；"20:00"-"06:00" 跨夜半开 [from,to)，见补白 3）；
        - seasons：空=全年恒真（R27）；periods：空=全天恒真（R27）；
        - 任一段不满足 → False（R16/R20/TC-16）；缺 worldtime → seasons/periods 退化为不限
          （与 IF01 总开关关「spawn 退化为仅 active_time」同口径，契约 §5.1 IF01）。
        兼容 SpawnDef 或 raw dict；非法行 → False（防御，M07 校验器红拦）。
        """
        row = self._coerce(spawn_row)
        if row is None:
            return False
        if not self._active_time_ok(row, now):
            return False
        return self._cycle_eligible(row, now)

    def zone_expire_removal(
        self,
        spawn_rows: Any,
        now: Optional[int],
        world_state: Any,
    ) -> List[str]:
        """E2 周期边界存在性变更（M09/R17/R29）：季节/时段窗口结束 → 场上该行怪物移除。

        对 spawn_rows 中「alive_count>0 且 seasons/periods 不再满足 now」的行返回行 key
        （= enemy 引用，供「对方逃跑了」文案；仅非战斗场景由调用方触发）。
        - 只认季节/时段边界（E2 由 IF09 check_changes 的 season/period 变化驱动）；
        - 天气不驱逐（R30/TC-14）：weather_weights 0 不触发移除；
        - active_time（现实钟点层）结束不触发移除（E2 明确只 seasons/periods，2a4c §1.0 保留不动）。
        spawn_rows 为 None → 回退到构造注入的 self._rows。纯函数，零副作用。
        """
        rows = self._coerce_many(spawn_rows)
        if rows is None:
            rows = self._rows
        state = world_state if isinstance(world_state, Mapping) else {}
        alive_raw = state.get("alive_count")
        alive: Mapping[object, object] = alive_raw if isinstance(alive_raw, Mapping) else {}
        removed: List[str] = []
        for row in rows:
            key = self._row_key(row)
            n = alive.get(key, 0)
            if not (isinstance(n, int) and not isinstance(n, bool)) or n <= 0:
                continue  # 场上无该行怪 → 无需移除
            if self._cycle_eligible(row, now):
                continue  # 季节/时段仍满足 → 不移除（仍在出没窗口内）
            removed.append(key)  # 周期边界结束 → 移除并交调用方拼「对方逃跑了」
        return removed

    # ------------------------------------------------------------------ 内部工具

    @staticmethod
    def _coerce(entry: Any, index: int = 0) -> Optional[SpawnDef]:
        """raw dict → SpawnDef 归一（双形态兼容）；SpawnDef 原样；非法行 → None（防御跳过）。"""
        if isinstance(entry, SpawnDef):
            return entry
        if isinstance(entry, Mapping):
            return SpawnDef.from_entry(entry, index)
        return None

    def _coerce_many(self, spawn_rows: Any) -> Optional[Tuple[SpawnDef, ...]]:
        """可迭代 spawn 行 → SpawnDef 元组；None/非法输入 → None（由调用方决定回退）。"""
        if spawn_rows is None:
            return None
        out: List[SpawnDef] = []
        for i, entry in enumerate(spawn_rows):
            row = self._coerce(entry, i)
            if row is not None:
                out.append(row)
        return tuple(out)

    @staticmethod
    def _row_key(row: SpawnDef) -> str:
        """spawn 行稳定 key = enemy 引用（「对方逃跑了」文案直接用）；无 enemy → 行序号（补白 1）。"""
        enemy = row.enemy
        if isinstance(enemy, str) and enemy:
            return enemy
        return str(row.index)

    @staticmethod
    def _row_cap(row: SpawnDef) -> int:
        """行同时在场上限 count（缺省 1【工程补白 contract §2.3】；坏值/负值 → 缺省）。"""
        c = row.count
        if isinstance(c, int) and not isinstance(c, bool) and c >= 0:
            return c
        return SPAWN_COUNT_DEFAULT

    @staticmethod
    def _coerce_now(now: Optional[int]) -> int:
        """now 归一：None → 当前 UTC+8 epoch 秒（对齐引擎 IF06 口径）。"""
        return int(time.time()) if now is None else int(now)

    @staticmethod
    def _clock_minutes(now: Optional[int]) -> int:
        """now（UTC+8 秒级时间戳）→ 当日分钟数（0..1439）；现实钟点层对齐引擎时区（2a4c §1.0）。"""
        dt = datetime.fromtimestamp(SpawnManager._coerce_now(now), tz=_TZ_UTC8)
        return dt.hour * 60 + dt.minute

    @staticmethod
    def _hhmm_to_minutes(hhmm: Optional[str]) -> Optional[int]:
        """\"HH:MM\" → 当日分钟数（0..1439）；非法/非字符串 → None。"""
        if not isinstance(hhmm, str) or ":" not in hhmm:
            return None
        hh, _, mm = hhmm.partition(":")
        try:
            h, m = int(hh), int(mm)
        except ValueError:
            return None
        if not (0 <= h <= 23 and 0 <= m <= 59):
            return None
        return h * 60 + m

    def _active_time_ok(self, row: SpawnDef, now: Optional[int]) -> bool:
        """现实钟点窗口判定（active_time，空=全天；跨夜半开 [from,to)，补白 3）。

        单向缺省（只有 from 或只有 to）→ 缺侧视为无界（补白 3）；非法钟点格式 → 忽略该侧。
        """
        f, t = row.active_from, row.active_to
        if f is None and t is None:
            return True  # 空 = 全天（contract §2.3）
        minute = self._clock_minutes(now)
        lo = self._hhmm_to_minutes(f) if f is not None else 0
        hi = self._hhmm_to_minutes(t) if t is not None else 1440
        if lo is None:
            lo = 0  # 非法 from → 无下界（防御，M07 红拦）
        if hi is None:
            hi = 1440  # 非法 to → 无上界（防御）
        if lo <= hi:
            return lo <= minute < hi  # 非跨夜：半开 [from, to)
        return minute >= lo or minute < hi  # 跨夜 "20:00"-"06:00"：20:00..24:00 ∪ 00:00..06:00

    def _cycle_eligible(self, row: SpawnDef, now: Optional[int]) -> bool:
        """季节/时段维度出没判定（不含 active_time；zone_expire_removal 用 —— E2 只认周期边界）。

        seasons/periods 空 = 恒真（R27）；缺 worldtime → 对应维度退化为不限（IF01 同口径）。
        """
        season = self._season_now(now)
        if season is not None and row.seasons and season not in row.seasons:
            return False
        period = self._period_now(now)
        if period is not None and row.periods and period not in row.periods:
            return False
        return True

    def _season_now(self, now: Optional[int]) -> Optional[str]:
        """当前季节（worldtime 注入：season_now(now) 或 season 属性；缺 → None=不限）。"""
        wt = self._worldtime
        if wt is None:
            return None
        fn = getattr(wt, "season_now", None)
        if callable(fn):
            v = fn(now)
            return v if isinstance(v, str) else None
        v = getattr(wt, "season", None)
        return v if isinstance(v, str) else None

    def _period_now(self, now: Optional[int]) -> Optional[str]:
        """当前时段（worldtime 注入：period_now(now) 或 period 属性；缺 → None=不限）。"""
        wt = self._worldtime
        if wt is None:
            return None
        fn = getattr(wt, "period_now", None)
        if callable(fn):
            v = fn(now)
            return v if isinstance(v, str) else None
        v = getattr(wt, "period", None)
        return v if isinstance(v, str) else None

    def _weather_now(self, map_id: str, now: Optional[int]) -> Optional[str]:
        """当前天气键（worldtime 注入：weather_now(map_id, now=now) / weather 属性；缺 → None）。"""
        wt = self._worldtime
        if wt is None:
            return None
        fn = getattr(wt, "weather_now", None)
        if callable(fn):
            try:
                v = fn(map_id, now=now)
            except TypeError:
                try:
                    v = fn(map_id, now)
                except TypeError:
                    v = fn(now)
            return v if isinstance(v, str) else None
        v = getattr(wt, "weather", None)
        return v if isinstance(v, str) else None

    def _weather_weight(self, row: SpawnDef, map_id: str, now: Optional[int]) -> Optional[float]:
        """当前天气权重：未配 weather_weights / 无天气源 / 未配该天气 → 1（默认）；0 → None（不刷）。"""
        ww = row.weather_weights
        if not ww:
            return 1.0  # 未配 → 默认 1（contract §2.3）
        key = self._weather_now(map_id, now)
        if key is None:
            return 1.0  # 无天气源 → 默认 1，不拦
        v = ww.get(key, 1.0)
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return 1.0  # 坏值（M07 红拦；防御 → 默认 1）
        return float(v)

    def _respawn_interval_seconds(
        self,
        row: SpawnDef,
        map_id: str,
        now: Optional[int],
    ) -> Optional[float]:
        """S2/E3 有效刷新间隔 = respawn_minutes×60 ÷ weather_weights[当前天气]（秒）。

        weight ≥ 1 刷更快、0 < w < 1 更慢、0 = 该天气不刷（→ None）；缺/坏 respawn_minutes → None。
        """
        base = row.respawn_minutes
        if not isinstance(base, int) or isinstance(base, bool) or base < 1:
            return None  # 缺/坏 respawn_minutes（M07 红拦；防御 → 不刷）
        weight = self._weather_weight(row, map_id, now)
        if weight is None or weight <= 0:
            return None  # 0 = 该天气不刷（R26/E3/TC-14）
        return base * 60.0 / weight

    @staticmethod
    def _as_dict(row: SpawnDef, spawn_count: Optional[int] = None) -> Dict[str, Any]:
        """spawn 行 → 输出 dict（SpawnDef 访问器归一；active_time 去空侧；补 spawn_count）。"""
        d: Dict[str, Any] = {
            "enemy": row.enemy,
            "count": row.count,
            "respawn_minutes": row.respawn_minutes,
            "active_time": {k: v for k, v in (("from", row.active_from), ("to", row.active_to))
                            if v is not None},
            "seasons": list(row.seasons),
            "periods": list(row.periods),
            "weather_weights": dict(row.weather_weights),
            "index": row.index,
        }
        if spawn_count is not None:
            d["spawn_count"] = spawn_count
        return d
