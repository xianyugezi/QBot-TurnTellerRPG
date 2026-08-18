"""背包引擎（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_4b_物品与背包契约（物品实例语义：堆叠/绑定/品质/词条/冷却）；
细化_3b_玩家属性三层 §1.1 加成层来源（装备 stats_bonus flat/pct 进入属性管线）。
Inventory 领域类型唯一落点 data/item.py（ItemInstance，3a D-03）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1）。
"""
from __future__ import annotations

from typing import Any

__all__ = ["InventoryEngine"]

_NOT_IMPL_MSG = "M1 实装：背包引擎（细化_4b）"


class InventoryEngine:
    """背包增删查/堆叠/绑定校验。M1 实装，本里程碑仅签名。"""

    def add_item(self, player: Any, item: Any, count: int = 1) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def remove_item(self, player: Any, item_id: str, count: int = 1) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def count(self, player: Any, item_id: str) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)
