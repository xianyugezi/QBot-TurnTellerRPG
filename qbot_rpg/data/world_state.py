"""世界状态领域类型 WorldState。

依据：细化_3a_架构分层契约 §3.2（WorldState 字段要点：地图怪物实例池、野图
BOSS、全体限购计数、last_spawn_time、dummy_override；key=全局不区分群）；
细化_4a_存储层契约 §1.3 world_state 表（'map_boss'/'world_stock'/'spawn_timers'/
'dummy_override' 等 key 语义，常驻不回收）；细化_2a1d（dummy_override 落点）。

frozen=True：状态快照不可变（U3）；写入走 storage 层 world_state 单行事务 + 
version CAS（4a TX-3）。
"""

from dataclasses import dataclass, field
from typing import Dict

__all__ = ["WorldState"]


@dataclass(frozen=True)
class WorldState:
    """全局世界状态（map_boss/world_stock/spawn_timers/dummy_override）。

    持久化到 world_state 表多行 key-value（每字段一行），逐行带 version 做
    CAS 比对（4a §1.3 / TX-3）。key=全局，不区分群（3a D-06）。
    """

    map_boss: Dict[str, object] = field(default_factory=dict)       # 野图 BOSS 实例池
    world_stock: Dict[str, int] = field(default_factory=dict)       # 全体限购库存（key→剩余量）
    spawn_timers: Dict[str, object] = field(default_factory=dict)   # 刷新计时器
    dummy_override: Dict[str, object] = field(default_factory=dict) # 训练木桩覆盖配置
    last_spawn_time: str = ""                                       # 最近一次刷新时间（ISO-8601 UTC）
