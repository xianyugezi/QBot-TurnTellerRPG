"""内容包通用状态格子：每（玩家 × 内容包）一格的纯存储层读写 API。

依据：批 D（2026-09-14）用户拍板「给核心存档表硬加内容包列（云海做法）可以做通用版」。
反面教材（云海分支审计 R2）：① 给核心 players 表加列 cloudsea_state（把具体内容包名
写进框架存档结构）；② 新库直写 schema 版本 2 → 迁移步不执行 → 新库反而没有该列（潜在
线上 bug）。本模块两条都绕开：

- **框架零内容包名 / 零业务键**：``pack_id`` 是运行时不透明字符串，框架不解释其含义，
  不 import 任何 content/ 模块，也不内置任何包名列表；
- **新库与旧库都有结构**：新库由 schema.py 的 SCHEMA_DDL 直接建表（新库直接具备），
  旧库由 migrations v1→v2 幂等补建（见 schema.py / migrations.py）。

存储形态：``player_pack_state(player_id, pack_id, state JSON, updated_at)``，主键
``(player_id, pack_id)``；state 以 JSON 对象文本存储，默认 ``'{}'``。

事务口径（4a F3）：写操作（set/patch/clear）一律 ``async with db.tx()``，绝不裸连；
同任务内嵌套调用并入外层事务（connection.py 批14 语义），跨任务由单写队列串行。
读操作走只读连接池（``db.fetchone_read`` / ``db.fetchall_read``）。

体积上限：单格状态序列化后 UTF-8 字节数不得超过 ``PACK_STATE_MAX_BYTES``，超限抛
``PackStateTooLargeError``，避免内容包把玩家存档写爆。
"""

from __future__ import annotations

import json
from collections.abc import Mapping as MappingABC
from typing import Any, Dict, Final, Mapping, Optional

from qbot_rpg.data.logging_utils import get_logger
from qbot_rpg.storage.connection import Database, StorageError
from qbot_rpg.storage.migrations import utcnow

_logger = get_logger("storage.pack_state")

# 单格状态序列化后上限（UTF-8 字节）。64 KiB 远大于单包进度量级，又能兜住失控写入。
PACK_STATE_MAX_BYTES: Final[int] = 64 * 1024

_SQL_SELECT_ONE: Final[str] = (
    "SELECT state FROM player_pack_state WHERE player_id = ? AND pack_id = ?"
)
_SQL_SELECT_ALL: Final[str] = (
    "SELECT pack_id, state FROM player_pack_state WHERE player_id = ? ORDER BY pack_id"
)
_SQL_UPSERT: Final[str] = (
    "INSERT INTO player_pack_state (player_id, pack_id, state, updated_at)"
    " VALUES (?,?,?,?)"
    " ON CONFLICT(player_id, pack_id) DO UPDATE SET"
    " state = excluded.state, updated_at = excluded.updated_at"
)
_SQL_DELETE: Final[str] = (
    "DELETE FROM player_pack_state WHERE player_id = ? AND pack_id = ?"
)


class PackStateError(StorageError):
    """内容包状态格子读写异常基类（4a TX-6 错误可恢复）。"""


class PackStateValidationError(PackStateError):
    """入参非法：键为空/非字符串、状态不是 JSON 对象、含不可序列化值（含 NaN/Inf）。"""


class PackStateTooLargeError(PackStateError):
    """单格状态序列化后超过 ``PACK_STATE_MAX_BYTES``。"""


def _require_key(name: str, value: object) -> str:
    """键校验：非空字符串（空的玩家/包键会写出无主格子，属调用方 bug）。"""
    if not isinstance(value, str) or not value:
        raise PackStateValidationError(f"{name} 必须是非空字符串，实际 {value!r}")
    return value


def _encode_state(state: Mapping[str, Any]) -> str:
    """校验 + 序列化：必须是 JSON 对象且不超体积上限，返回存储文本。"""
    if not isinstance(state, MappingABC):
        raise PackStateValidationError(
            f"pack state 必须是 JSON 对象（Mapping），实际 {type(state).__name__}"
        )
    data = dict(state)
    for key in data:
        if not isinstance(key, str):
            raise PackStateValidationError(
                f"pack state 顶层键必须是字符串，实际 {key!r}（防 JSON 静默改写键类型）"
            )
    try:
        payload = json.dumps(
            data, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise PackStateValidationError(f"pack state 必须可 JSON 序列化: {exc}") from exc
    size = len(payload.encode("utf-8"))
    if size > PACK_STATE_MAX_BYTES:
        raise PackStateTooLargeError(
            f"pack state 序列化后 {size} 字节，超过单格上限 {PACK_STATE_MAX_BYTES} 字节"
        )
    return payload


def _decode_state(raw: Optional[str]) -> Dict[str, Any]:
    """读解：缺失 / 空 / 非法 JSON / 非对象 → {}（不抛，SCHEMA-6 缺省兜底）。"""
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except (TypeError, ValueError):
        _logger.warning("player_pack_state 存了非法 JSON，按空格子读: %r", raw[:64])
        return {}
    if not isinstance(value, dict):
        _logger.warning("player_pack_state 存了非对象 JSON，按空格子读: %r", raw[:64])
        return {}
    return value


async def get_pack_state(db: Database, player_id: str, pack_id: str) -> Dict[str, Any]:
    """读单格状态：不存在 / 空 / 损坏 → ``{}``（不抛）。

    返回反序列化出的独立副本，调用方原地改动不会影响存档。
    """
    pid = _require_key("player_id", player_id)
    pkg = _require_key("pack_id", pack_id)
    row = await db.fetchone_read(_SQL_SELECT_ONE, (pid, pkg))
    if row is None:
        return {}
    return _decode_state(row["state"])


async def set_pack_state(
    db: Database, player_id: str, pack_id: str, state: Mapping[str, Any]
) -> None:
    """覆盖写单格状态（格子不存在则新建）。

    ``state`` 必须是 JSON 对象（Mapping，顶层键为字符串）；非对象 / 含不可序列化值
    （含 NaN/Infinity）→ :class:`PackStateValidationError`；序列化后超
    ``PACK_STATE_MAX_BYTES`` → :class:`PackStateTooLargeError`。写与校验同一事务，
    失败不留半写。
    """
    pid = _require_key("player_id", player_id)
    pkg = _require_key("pack_id", pack_id)
    payload = _encode_state(state)
    async with db.tx() as tx:
        await tx.execute(_SQL_UPSERT, (pid, pkg, payload, utcnow()))


async def patch_pack_state(
    db: Database, player_id: str, pack_id: str, patch: Mapping[str, Any]
) -> Dict[str, Any]:
    """浅合并写单格状态并返回合并结果。

    语义：``new = {**old, **patch}``——**仅顶层键合并**，同名顶层键整体替换（嵌套
    对象不递归合并）；格子不存在时等价于 set。读-改-写在同一事务内完成（单写队列
    串行，不丢更新）。``patch`` 与合并结果同样受「JSON 对象 + 体积上限」约束，任一
    不满足即报错且不写入。
    """
    pid = _require_key("player_id", player_id)
    pkg = _require_key("pack_id", pack_id)
    if not isinstance(patch, MappingABC):
        raise PackStateValidationError(
            f"patch 必须是 JSON 对象（Mapping），实际 {type(patch).__name__}"
        )
    async with db.tx() as tx:
        row = await tx.fetchone(_SQL_SELECT_ONE, (pid, pkg))
        current = _decode_state(row["state"]) if row is not None else {}
        merged: Dict[str, Any] = {**current, **dict(patch)}
        payload = _encode_state(merged)
        await tx.execute(_SQL_UPSERT, (pid, pkg, payload, utcnow()))
    return merged


async def clear_pack_state(db: Database, player_id: str, pack_id: str) -> None:
    """清空单格状态（删行）；格子本就不存在时同样成功（幂等）。"""
    pid = _require_key("player_id", player_id)
    pkg = _require_key("pack_id", pack_id)
    async with db.tx() as tx:
        await tx.execute(_SQL_DELETE, (pid, pkg))


async def list_pack_states(db: Database, player_id: str) -> Dict[str, Dict[str, Any]]:
    """列出该玩家全部格子：``{pack_id: state}``；无任何格子 → ``{}``（按 pack_id 升序）。"""
    pid = _require_key("player_id", player_id)
    rows = await db.fetchall_read(_SQL_SELECT_ALL, (pid,))
    return {str(row["pack_id"]): _decode_state(row["state"]) for row in rows}


__all__ = [
    "PACK_STATE_MAX_BYTES",
    "PackStateError",
    "PackStateValidationError",
    "PackStateTooLargeError",
    "get_pack_state",
    "set_pack_state",
    "patch_pack_state",
    "clear_pack_state",
    "list_pack_states",
]
