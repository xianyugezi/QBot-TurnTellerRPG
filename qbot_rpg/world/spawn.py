"""刷怪/补刷 Spawner（M3 实装 · 本里程碑仅签名）。

职责（细化_3a §2.1；/ 细化_2a1b_通道规则与刷怪）：地图点/通道刷新、野图 BOSS 刷新、
全体限购补货；离线封顶 N 小时（【框架】L194-205：离线补刷按离线时长封顶，防挂机刷资源）。

M3 实装依据：细化_2a1b（刷新规则/通道刷怪）、细化_2a1d（字段扩展）、细化_2a4a（时间引擎联动）。
零 NoneBot import（3a R1）；空态 = 领域异常/返回约定值，不拼用户文案（R4）。
"""
from __future__ import annotations

from typing import Any, Dict

__all__ = ["Spawner"]

_NOT_IMPL_MSG = "M3 实装：刷新/补刷（细化_2a1b / 细化_2a1d）"

# 离线补刷封顶小时数（【框架】L194-205），M3 从 content 配置读取覆盖。
DEFAULT_OFFLINE_CAP_HOURS: int = 12


class Spawner:
    """刷怪/补刷器（离线封顶 N 小时）。M3 实装，本里程碑仅签名。"""

    def __init__(self) -> None:
        self._registry = None

    def refresh_map(self, map_id: str) -> Dict[str, Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def catch_up_offline(
        self,
        player: Any,
        since_tick: int,
        cap_hours: int = DEFAULT_OFFLINE_CAP_HOURS,
    ) -> Dict[str, Any]:
        """离线补刷：按离线时长补刷但封顶 cap_hours（防挂机）。M3 实装。"""
        raise NotImplementedError(_NOT_IMPL_MSG)

    def refill_world_stock(self, key: str) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)
