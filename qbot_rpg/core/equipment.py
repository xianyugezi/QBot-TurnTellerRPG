"""装备引擎（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_3b_玩家属性三层 §1.1 加成层来源（装备 stats_bonus flat/pct、
元素攻击力 ele_atk_*、元素抗性 elem_res —— 装备词条承载，L111-112/L127）；
细化_2c2d_锻造套装 / 细化_2c3a~2c3c 强化（EquipmentSlot.slot_level / locked 随实例持久化）；
细化_4a 存储层契约 §1.2 equipment 字段（item_id/name/slot_level/locked/gems）。
装备变更 → 属性全链重算（细化_3b TC-07：卸装即时重算）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1）。
"""
from __future__ import annotations

from typing import Any, Dict

__all__ = ["EquipmentEngine"]

_NOT_IMPL_MSG = "M1 实装：装备引擎（细化_4b / 细化_2c / 细化_3b §1.1）"


class EquipmentEngine:
    """穿戴/卸下/槽位互斥/词条聚合。M1 实装，本里程碑仅签名。"""

    def equip(self, player: Any, item: Any, slot: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def unequip(self, player: Any, slot: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def aggregate_bonus(self, player: Any) -> Dict[str, float]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def equip_search(self, query: Any, encode: bool = True) -> Any:
        """编辑器器物检索（细化_5a 编辑器接管，M-y 实装；预留签名）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)
