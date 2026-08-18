"""存档结构版本迁移：db_schema_version 检测 + 字段级迁移 + 迁移前 .bak。

依据：细化_4a_存储层契约 §六 存档兼容迁移（MIG-1~5 / D-06）——
  - 两层版本模型 §6.1：meta.db_schema_version（存档结构版本，初始 1）
  - 迁移管线 F5 §6.2：检测（启动 + 首次访问懒迁移）→ 迁移前强制 .bak
    （VACUUM INTO）→ 逐级迁移（每级单事务）→ round-trip 校验 → 写
    meta.migration_log → 提交；失败整体回滚，服务携带旧版 schema 继续运行。
  - MIG-1 字段级迁移：缺补默认 / 多忽略，不重排业务语义。

字段级实现：
  - 列级：add_column_if_missing() 用 PRAGMA table_info 检测 + ALTER TABLE
    ADD COLUMN ... DEFAULT（MIG-1 缺补默认）。
  - JSON 级：read 路径的 row_to_player 天然「缺补默认 / 多忽略」（repository）。
  本模块只收敛 schema 结构断言（SCHEMA-2：结构断言一律收敛 storage 层）。
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from qbot_rpg.storage.connection import Database, StorageError
from qbot_rpg.storage.schema import CREATE_INDEXES, CREATE_TABLE_META, SCHEMA_TABLES

# ---------------------------------------------------------------------------
# 存档结构版本常量（初始 1；未来结构变更时递增并追加 MIGRATION_STEPS）
# ---------------------------------------------------------------------------
DB_SCHEMA_VERSION: int = 1
META_KEY: str = "global"

# 迁移步注册表：[(from_version, to_version, coro_fn)]，from < to。
# v1 为初始版本，无迁移步；后续结构变更（如新增列）在此追加步，形如：
#   (1, 2, migrate_v1_to_v2)
MIGRATION_STEPS: List[Tuple[int, int, Callable[..., Any]]] = []

BACKUP_DIR_MODE: int = 0o700


class MigrationError(StorageError):
    """迁移失败（整体回滚后仍可由旧版 schema 继续服务，D-06）。"""


@dataclass(frozen=True)
class MigrationResult:
    """一次迁移调用的结果。"""

    from_version: int
    to_version: int
    applied_steps: Tuple[Tuple[int, int], ...] = ()
    state: str = "up_to_date"          # up_to_date | migrated | failed
    backup_id: Optional[str] = None
    note: str = ""


# ---------------------------------------------------------------------------
# meta 元信息行管理（单行 key='global'，§1.3 / SCHEMA-8）
# ---------------------------------------------------------------------------
async def ensure_meta(db: Database, now: Optional[str] = None) -> int:
    """确保 meta 单行存在并返回当前 db_schema_version。

    版本回填策略（D-06 懒迁移）：
      - 全新库（players 无数据）→ 直接写 CURRENT 版本；
      - 有 players 数据但 meta 缺失（老库升级）→ 回填 1，触发迁移链。
    """
    row = await db.fetchone("SELECT * FROM meta WHERE key = ?", (META_KEY,))
    if row is not None:
        return int(row["db_schema_version"])
    has_players = bool((await db.fetchone("SELECT 1 FROM players LIMIT 1")) is not None)
    version = 1 if has_players else DB_SCHEMA_VERSION
    ts = now or utcnow()
    await db.execute(
        "INSERT INTO meta (key, db_schema_version, current_pack_id, current_pack_version,"
        " last_migration_at, migration_log, created_at, updated_at)"
        " VALUES (?,?,NULL,NULL,NULL,'[]',?,?)",
        (META_KEY, version, ts, ts),
    )
    return version


def utcnow() -> str:
    """当前 UTC 时间（ISO-8601，Z 后缀；全存储层共用时间戳口径）。"""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# 字段级迁移工具（MIG-1）
# ---------------------------------------------------------------------------
async def add_column_if_missing(
    db: Database, table: str, column: str, ddl: str
) -> bool:
    """列级字段迁移：缺补默认（ADD COLUMN ... DEFAULT）/ 多忽略（已存在跳过）。

    返回是否实际加了列。调用方负责包进单事务（MIG-5 每级单事务）。
    """
    cols = set()
    for row in await db.fetchall(f"PRAGMA table_info({table})"):
        cols.add(str(row["name"]))
    if column in cols:
        return False
    await db.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
    return True


async def normalize_json_column(raw: str, default_any: Any) -> Any:
    """JSON 列读解：缺非法/空 → 兜底默认（SCHEMA-6 字段缺省=默认值）。"""
    if not raw:
        return default_any
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return default_any


# ---------------------------------------------------------------------------
# 迁移前强制 .bak（VACUUM INTO 不动主库，RW-5 / D-06）+ backups 表登记
# ---------------------------------------------------------------------------
async def pre_migration_backup(db: Database, now: Optional[str] = None) -> Optional[str]:
    """迁移前强制 .bak 快照并登记 backups 表（backup_type='pre_migration'）。

    内存库不支持 VACUUM INTO → 返回 None（仅日志语义，无实体备份）。
    """
    if db.is_memory:
        return None
    base = os.path.dirname(os.path.abspath(db.path))
    bdir = os.path.join(base, "backups")
    os.makedirs(bdir, mode=BACKUP_DIR_MODE, exist_ok=True)
    backup_id = str(uuid.uuid4())
    target = os.path.join(bdir, f"{backup_id}.bak")
    await db.vacuum_into(target)
    size = 0
    with open(target, "rb") as f:  # noqa: SIM115 文件大小统计
        f.seek(0, os.SEEK_END)
        size = f.tell()
    ts = now or utcnow()
    await db.execute(
        "INSERT INTO backups (backup_id, file_path, backup_type, size_bytes, created_at)"
        " VALUES (?,?,?,?,?)",
        (backup_id, target, "pre_migration", size, ts),
    )
    return backup_id


# ---------------------------------------------------------------------------
# 迁移履历（meta.migration_log，SCHEMA-8 / MIG-5 迁移链完整）
# ---------------------------------------------------------------------------
async def append_migration_log(
    db: Database, entry: Dict[str, object], now: Optional[str] = None
) -> None:
    row = await db.fetchone(
        "SELECT migration_log, updated_at FROM meta WHERE key = ?", (META_KEY,)
    )
    logs: List[object] = []
    if row is not None and row["migration_log"]:
        try:
            logs = json.loads(row["migration_log"])
            if not isinstance(logs, list):
                logs = []
        except (TypeError, ValueError):
            logs = []
    logs.append(entry)
    ts = now or utcnow()
    await db.execute(
        "UPDATE meta SET migration_log = ?, last_migration_at = ?, updated_at = ? WHERE key = ?",
        (json.dumps(logs, ensure_ascii=False), ts, ts, META_KEY),
    )


# ---------------------------------------------------------------------------
# 迁移管线（F5 / D-06 / MIG-5）
# ---------------------------------------------------------------------------
async def migrate_database(
    db: Database,
    *,
    force_backup: bool = True,
    now: Optional[str] = None,
) -> MigrationResult:
    """启动/首次访问懒迁移：检测 → 备份 → 逐级单事务 → 履历 → 提交。

    任一级失败：该级事务回滚，服务继续跑旧版 schema（绝不因迁移起不来）。
    """
    version = await ensure_meta(db, now=now)
    if version >= DB_SCHEMA_VERSION:
        return MigrationResult(version, DB_SCHEMA_VERSION, note="schema 已是最新")

    ordered = sorted(
        (s for s in MIGRATION_STEPS if s[0] >= version and s[1] <= DB_SCHEMA_VERSION),
        key=lambda s: s[0],
    )
    backup_id: Optional[str] = None
    if force_backup:
        backup_id = await pre_migration_backup(db, now=now)

    applied: List[Tuple[int, int]] = []
    for from_v, to_v, fn in ordered:
        try:
            async with db.tx() as tx:
                await fn(tx, db, now=now)
                entry: Dict[str, object] = {
                    "from": from_v,
                    "to": to_v,
                    "at": now or utcnow(),
                    "result": "ok",
                }
                await tx.execute(
                    "UPDATE meta SET db_schema_version = ?, updated_at = ? WHERE key = ?",
                    (to_v, now or utcnow(), META_KEY),
                )
                row = await tx.fetchone(
                    "SELECT migration_log FROM meta WHERE key = ?", (META_KEY,)
                )
                logs: List[object] = []
                if row is not None and row["migration_log"]:
                    try:
                        logs = json.loads(row["migration_log"])
                        if not isinstance(logs, list):
                            logs = []
                    except (TypeError, ValueError):
                        logs = []
                logs.append(entry)
                await tx.execute(
                    "UPDATE meta SET migration_log = ?, last_migration_at = ? WHERE key = ?",
                    (json.dumps(logs, ensure_ascii=False), entry["at"], META_KEY),
                )
            applied.append((from_v, to_v))
        except BaseException as exc:  # noqa: BLE001 — 失败回滚后整体交接
            try:
                await append_migration_log(
                    db,
                    {"from": from_v, "to": to_v, "at": now or utcnow(), "result": "failed",
                     "error": f"{type(exc).__name__}: {exc}"},
                    now=now,
                )
            except BaseException:
                pass
            return MigrationResult(
                version, version, applied_steps=tuple(applied), state="failed",
                backup_id=backup_id, note=str(exc),
            )

    return MigrationResult(
        version, DB_SCHEMA_VERSION, applied_steps=tuple(applied),
        state="migrated", backup_id=backup_id,
    )


__all__ = [
    "DB_SCHEMA_VERSION",
    "META_KEY",
    "MIGRATION_STEPS",
    "MigrationError",
    "MigrationResult",
    "ensure_meta",
    "add_column_if_missing",
    "normalize_json_column",
    "pre_migration_backup",
    "append_migration_log",
    "migrate_database",
    "utcnow",
]
