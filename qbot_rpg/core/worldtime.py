"""世界时间引擎（M1 实装 · 本里程碑仅骨架）。

M1 实装依据：细化_2a4a_时间引擎（白天/夜晚轮转、时刻换算、驳接 weather/period；
dummy_override 时间拨动落 data/world_state.py）；细化_2a4c_时间天气接口
（content 消费统一接口）。WorldState 唯一落点 data/world_state.py（3a D-03）。

本里程碑（M0）仅定义模块职责与占位签名，不写业务逻辑；零 NoneBot import（3a R1）。
"""
from __future__ import annotations

from typing import Optional

__all__ = ["WorldTime"]

_NOT_IMPL_MSG = "M1 实装：世界时间引擎（细化_2a4a / 细化_2a4c）"


class WorldTime:
    """时间引擎：刻度换算/昼夜轮替/时间快进。M1 实装，本里程碑仅签名。"""

    def now(self) -> str:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def is_daytime(self, tick: Optional[int] = None) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def tick_forward(self, amount: int, units: str = "min") -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)
