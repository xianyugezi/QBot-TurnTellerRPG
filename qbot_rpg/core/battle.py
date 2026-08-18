"""战斗引擎（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_1a_伤害公式数值 / 细化_1b_效果系统契约 / 细化_1c1a~1c2 连段 /
细化_1d 印记系统 / 细化_1e~1f（怪物 schema+AI）/ 细化_1g1a~1g4（战斗状态机/快照续战/战斗世界边界）；
1v1 回合状态机，一轮一条消息（【框架】L69/L1571）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1），
战斗快照类型唯一落点 data/battle.py（3a D-03）。
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["BattleEngine"]

_NOT_IMPL_MSG = "M1 实装：回合战斗状态机（细化_1g / 细化_1a / 细化_1b）"


class BattleEngine:
    """1v1 回合战斗状态机（锁定→攻击→反击→结算）。M1 实装，本里程碑仅签名。"""

    def start(self, player: Any, enemy: Any, random_seed: Optional[int] = None) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def player_act(self, action: str, params: Any = None) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def snapshot(self) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def resume(self, snapshot: Any) -> "BattleEngine":
        raise NotImplementedError(_NOT_IMPL_MSG)
