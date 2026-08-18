"""升级引擎（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_2c5a_职业等级与SP / 细化_3b_玩家属性三层 §0.1 白值层定义
（白值 = 基础 base + 职业成长 growth×等级 + 自由加点，详见细化_3b §1.1 L136/L168/L174）；
换职业不重算（L174）。升级触发属性重算入口（免费加点落白值层）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1），
Player 领域类型唯一落点 data/player.py（3a D-03）。
"""
from __future__ import annotations

from typing import Any

__all__ = ["LevelUpEngine"]

_NOT_IMPL_MSG = "M1 实装：升级/加点引擎（细化_2c5a / 细化_3b §1.1）"


class LevelUpEngine:
    """等级/经验/自由加点引擎。M1 实装，本里程碑仅签名。"""

    def gain_exp(self, player: Any, amount: int) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def allocate_point(self, player: Any, attr_id: str, amount: int) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)
