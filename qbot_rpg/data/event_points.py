"""战斗效果事件时点权威枚举（批51 · 触发归属与事件补点）。

**唯一源**：`EVENT_POINTS`。落地在 `data` 层而不是 `core` 层，是为了让
`content` 层校验器（`content/validator.py`）能按分层契约 `content → {data}`
校验 `effects.trigger` 的取值域，而**不必**反向 import core——与批50 把面板三轴
stem（`PANEL_AXIS_STEMS`）落在 `data/gear_stats.py` 是同一取舍。

引用路径不变：`core/event_dispatcher.py` 由本模块引入并**原样再导出**，
故 `from qbot_rpg.core.event_dispatcher import EVENT_POINTS` 依旧可用。

语义（详细说明见 `core/event_dispatcher` 模块 docstring）：
  · `death`   = **任一侧死亡**，派发给死者自己；
  · `on_kill` = **我击杀敌**，派发给击杀者侧（1v1 里的另一侧）。
  两者语义相反、方向不同，不得混用。
"""
from __future__ import annotations

from typing import Tuple

__all__ = ["EVENT_POINTS", "STATUS_EVENT_POINTS"]

#: 事件时点权威枚举（effects `trigger` 字段值域）。
#: 顺序 = 既有 16 点（battle_start ... season_change）**原样保序** + 批51 补 `on_kill`
#: 插在 on_skill 与 season_change 之间（前 16 位顺序不变，避免既有断言位移）。
EVENT_POINTS: Tuple[str, ...] = (
    "battle_start", "battle_end",
    "action_start", "action_end",
    "turn_start", "turn_end",
    "status_gain", "status_lose",
    "mark_gain", "mark_lose",
    "death", "revive",
    "on_attack", "on_hit", "on_skill",
    "season_change",
    "on_kill",
)

#: 状态定义 `on_gain`/`on_lose`/`on_expire` 映射到的入口事件（与 effects trigger 共域）。
STATUS_EVENT_POINTS: Tuple[str, ...] = ("status_gain", "status_lose")
