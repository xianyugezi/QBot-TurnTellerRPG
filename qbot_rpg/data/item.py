"""物品实例领域类型 ItemInstance。

依据：细化_3a_架构分层契约 §3.2（ItemInstance 字段要点：item_id+name 冗余、
quality 四档、bound、count、装备槽位/词条 stats_bonus、冷却计时）；
细化_4a_存储层契约 §1.2（inventory JSON：{item_id, name, count, stack_max,
bound, quality, traits...}，ID+名称冗余 SCHEMA-5）；细化_4b_物品与背包契约
（物品实例语义：绑定不可赠送/掉落、品质、词条、冷却）。

frozen=True：实例一经构造不可变，防战斗/结算中被误改（细化_3a §3.2，U3）。
"""

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from qbot_rpg.data.types import ItemID

__all__ = ["ItemInstance"]


@dataclass(frozen=True)
class ItemInstance:
    """玩家持有的物品实例（运行时实例，非内容包配置 ItemDef）。

    item_id+name 冗余存储（SCHEMA-5 / MIG-3：引用按 ID 存储、显示按名字，
    换包后旧条目仍可按旧名显示）。
    """

    item_id: ItemID
    name: str                                  # 冗余名称（MIG-3）
    count: int                                 # 堆叠数量
    quality: str                               # 品质（四档枚举，细化_3a §3.2）
    bound: bool                                # 绑定物品不可赠送/掉落
    slot: Optional[str] = None                 # 装备槽位（可装备时）
    stats_bonus: Dict[str, float] = field(default_factory=dict)  # 装备词条/虚拟属性键（细化_3b §4.1 ele_atk_*）
    traits: Tuple[str, ...] = ()               # 特性（tuple 保证冻结语义）
    cooldown_until: Optional[str] = None       # 冷却计时（ISO-8601 UTC）
