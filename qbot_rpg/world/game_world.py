"""全局世界 GameWorld（M3 实装 · 本里程碑仅结构签名）。

职责（细化_3a §2.1 / §1.2）：地图（细化_2a1a~2a1d）、怪物池（细化_1e 八段 schema）、
野图 BOSS、全体限购（world_stock，细化_4a §1.3）——key=全局，不区分群（3a D-06）。
刷新/补刷见 world/spawn.py（M3）；会话互斥见 world/session.py（M1/M4）。

M3 实装依据：细化_2a1a_地图schema字段 / 细化_2a1b_通道规则与刷怪 / 细化_2a1c_地图副本衔接 /
细化_2a1d_地图字段扩展 / 细化_2a2_换区追击流程 / 细化_2a3_副本两型流程 / 细化_2b1（发牌员）。
WorldState 唯一落点 data/world_state.py（3a D-03），本层只经 storage/repository 读写。

本里程碑（M0）仅定义接口签名 + docstring，不写业务语义；零 NoneBot import（3a R1），
不拼用户文案（R4：抛领域异常由壳层翻译）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

__all__ = ["GameWorld", "WorldNotFoundError"]

_NOT_IMPL_MSG = "M3 实装：全局世界（细化_2a / 细化_2b）"


class WorldNotFoundError(Exception):
    """地图/世界资源不存在（领域异常，壳层 errors.py 翻译人话；3a R4）。"""


class GameWorld:
    """全局世界状态（地图/怪物池/野图 BOSS/全体限购；key=全局）。M3 实装，本里程碑仅签名。"""

    def __init__(self) -> None:
        self._initialized = False

    # -- 地图 -------------------------------------------------------------
    def get_map(self, map_id: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def list_maps(self) -> List[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def move_to_map(self, player: Any, map_id: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 怪物池 / 野图 BOSS --------------------------------------------------
    def monster_pool(self, map_id: str) -> List[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def get_boss(self, map_id: str) -> Optional[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def is_boss_alive(self, map_id: str) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 全体限购（world_stock） --------------------------------------------
    def world_stock(self, key: str) -> int:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def try_consume_world_stock(self, key: str, count: int) -> bool:
        raise NotImplementedError(_NOT_IMPL_MSG)

    # -- 世界状态持久化（经 storage/repository 注入，M3） --------------------
    def load(self, world_state: Any) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def to_world_state(self) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def list_stores(self) -> List[Any]:
        """运营商店铺目录（细化_5a 编辑器/运营页只读，M-y 实装；预留签名）。"""
        raise NotImplementedError(_NOT_IMPL_MSG)
