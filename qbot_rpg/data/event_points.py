"""战斗效果事件时点权威枚举（批51 · 触发归属与事件补点）。

**唯一源**：`EVENT_POINTS`。落地在 `data` 层而不是 `core` 层，是为了让
`content` 层校验器（`content/validator.py`）能按分层契约 `content → {data}`
校验 `effects.trigger` 的取值域，而**不必**反向 import core——与批50 把面板三轴
stem（`PANEL_AXIS_STEMS`）落在 `data/gear_stats.py` 是同一取舍。

引用路径不变：`core/event_dispatcher.py` 由本模块引入并**原样再导出**，
故 `from qbot_rpg.core.event_dispatcher import EVENT_POINTS` 依旧可用。

批84 · B1「登记即承诺」：本模块同时是「**哪些时点真有派发点**」的**唯一源**——
`EventPoint.dispatched` 与 `EVENT_POINT_TABLE`。此前该事实只散落在代码注释与
审查文档里（作者写 `trigger` 命中"合法枚举但无派发点"的时点 → 校验器静默通过、
红黄都不给 → 写了永不触发）。现由 `content/validator.py` 读本表发**黄提示 Y-24**
（只提示、不红拦，零行为变化）；文档口径也以本表为准。

  语义（详细说明见 `core/event_dispatcher` 模块 docstring）：
    · `death`   = **任一侧死亡**，派发给死者自己；
    · `on_kill` = **我击杀敌**，派发给击杀者侧（1v1 里的另一侧）。
    两者语义相反、方向不同，不得混用。

  `dispatched` 判定口径（批84 逐点 grep `_dispatch_event` / `_dispatch_status_event`
  生产调用点核实，**以代码为准**）：
    · `True`  = 存在真实生产派发点；
    · `False` = 合法枚举但**无派发点（二期）**：写了永不触发。
"""
from __future__ import annotations

from typing import Dict, NamedTuple, Tuple

__all__ = [
    "EVENT_POINTS",
    "STATUS_EVENT_POINTS",
    "EventPoint",
    "EVENT_POINT_TABLE",
    "EVENT_POINT_INDEX",
    "is_dispatched",
    "undispatched_points",
]


class EventPoint(NamedTuple):
    """单个事件时点的权威登记项（批84 · B1 唯一源）。

    `name` = 枚举值（`effects.trigger` 取值域成员）；
    `dispatched` = 是否存在生产派发点（`False` = 二期未接，写了永不触发）；
    `note` = 派发位置/口径的一句话（**函数/文件级**，不钉行号，避免漂移）。
    """

    name: str
    dispatched: bool
    note: str = ""


#: 事件时点权威表（批84 · B1：名称 + 派发状态 + 备注 = 单一源）。
#: 顺序 = 既有 16 点（battle_start ... season_change）**原样保序** + 批51 补 `on_kill`
#: 插在 on_skill 与 season_change 之间（前 16 位顺序不变，避免既有断言位移）。
#: `dispatched` 以生产代码为准（批84 实测：12 点有派发点 / 5 点二期未接）。
EVENT_POINT_TABLE: Tuple[EventPoint, ...] = (
    EventPoint("battle_start", True, "Battle.start：两侧各一次，资源初始化后、CTB 建条前"),
    EventPoint("battle_end", True, "Battle._settle：两侧各一次，marks 清零前"),
    EventPoint("action_start", True, "Battle._do_action_inner：行动者，全动作类型"),
    EventPoint("action_end", True, "Battle 5 条返回路径：行动者（逃跑/跳过不派发）"),
    EventPoint("turn_start", True, "Battle._start_actor_turn：行动者"),
    EventPoint("turn_end", True, "Battle._end_actor_turn：行动者（批81·A1 补点）"),
    EventPoint("status_gain", True, "effects.execute_action status_apply 成功后：状态持有侧"),
    EventPoint("status_lose", True,
               "effects.py：驱散移除后 + tick 过期（衰减/持续双维归零；批84·B3 补）：状态持有侧"),
    EventPoint("mark_gain", False, "二期未接：无派发点，写了永不触发"),
    EventPoint("mark_lose", False,
               "二期未接：无派发点（battle 的 result['mark_lose'] 是战斗结果标记，同名不同物）"),
    EventPoint("death", True, "Battle._death_check_side：死者自己"),
    EventPoint("revive", True, "Battle.revive_side：复活侧"),
    EventPoint("on_attack", False, "二期未接：无派发点，写了永不触发"),
    EventPoint("on_hit", False, "二期未接：无派发点，写了永不触发"),
    EventPoint("on_skill", False,
               "二期未接：无派发点（effects 的 when=on_skill 是施放时机字段，非事件派发）"),
    EventPoint("season_change", True,
               "Battle._fire_season_event：两侧各一次（与 season_procs 双轨）"),
    EventPoint("on_kill", True, "Battle._death_check_side：击杀者侧，紧接 death"),
)

#: 事件时点权威枚举（effects `trigger` 字段值域）——由 `EVENT_POINT_TABLE` 派生，
#: 值/顺序与批51 起逐字一致（前 16 保序 + `on_kill` 第 17 位）。
EVENT_POINTS: Tuple[str, ...] = tuple(p.name for p in EVENT_POINT_TABLE)

#: 名称 → 登记项（校验器/文档共同读取派发状态的入口）。
EVENT_POINT_INDEX: Dict[str, EventPoint] = {p.name: p for p in EVENT_POINT_TABLE}

#: 状态定义 `on_gain`/`on_lose`/`on_expire` 映射到的入口事件（与 effects trigger 共域）。
STATUS_EVENT_POINTS: Tuple[str, ...] = ("status_gain", "status_lose")


def is_dispatched(point: str) -> bool:
    """该时点当前是否有生产派发点（未知时点 → `False`）。"""
    entry = EVENT_POINT_INDEX.get(point)
    return bool(entry.dispatched) if entry is not None else False


def undispatched_points() -> Tuple[str, ...]:
    """**合法枚举但无派发点（二期）**的时点，保序（批84 · B2 黄提示的数据源）。"""
    return tuple(p.name for p in EVENT_POINT_TABLE if not p.dispatched)
