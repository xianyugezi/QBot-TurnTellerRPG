"""领域模型唯一落点（细化_3a §3，D-03/U1）。

导出全部运行实例类型；core/world/storage/content 只 import 本包。仅标准库依赖。
"""

from qbot_rpg.data.battle import BattleSnapshot, CombatantSnapshot
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, Player, PlayerAttributes
from qbot_rpg.data.status import Duration, StatusInstance
from qbot_rpg.data.types import (
    AttrID,
    EffectID,
    ItemID,
    MarkID,
    PlayerQID,
    SkillID,
    StatusID,
    TypeAlias,
)
from qbot_rpg.data.world_state import WorldState

__all__ = [
    "Player",
    "PlayerAttributes",
    "EquipmentSlot",
    "ItemInstance",
    "StatusInstance",
    "Duration",
    "CombatantSnapshot",
    "BattleSnapshot",
    "WorldState",
    "PlayerQID",
    "ItemID",
    "StatusID",
    "MarkID",
    "EffectID",
    "SkillID",
    "AttrID",
    "TypeAlias",
]
