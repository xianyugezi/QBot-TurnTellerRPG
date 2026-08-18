"""会话管理与并发互斥 SessionManager（M1/M4 实装 · 本里程碑仅签名）。

职责（细化_3a §2.1 / §0.1；【框架】L335-345 3.18）：单玩家 1 会话互斥、
会话挂起/恢复、跨群并发互斥——sessions 表以 player_qid 为主键即互斥约束
（细化_4a §1.3 SCHEMA-7，FK → players ON DELETE CASCADE）。
M1 接入战斗会话（对局快照 BattleSnapshot）；M4 接入其它会话（炼金/副本等）。

会话时长（快照续战/中断恢复，对齐细化_1g3）：战斗会话快照续战语义归 core/battle.py。
零 NoneBot import（3a R1）；key = 玩家 QQ 号（3a D-06），群号仅作来源记录。
"""
from __future__ import annotations

from typing import Any, Optional

__all__ = ["SessionManager", "SessionConflictError"]

_NOT_IMPL_MSG = "M1/M4 实装：会话互斥/挂起（细化_1g3 / 细化_4a §1.3 SCHEMA-7）"


class SessionConflictError(Exception):
    """单玩家已有其它会话（领域异常，壳层翻译；3a R4）。"""


class SessionManager:
    """会话互斥：单玩家 1 会话；挂起/恢复。M1/M4 实装，本里程碑仅签名。"""

    def acquire(self, player_qid: str, session_type: str) -> Any:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def release(self, player_qid: str) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def get_active(self, player_qid: str) -> Optional[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def suspend(self, player_qid: str, snapshot: Any) -> None:
        raise NotImplementedError(_NOT_IMPL_MSG)

    def restore(self, player_qid: str) -> Optional[Any]:
        raise NotImplementedError(_NOT_IMPL_MSG)
