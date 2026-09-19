"""存档结构版本迁移：db_schema_version 检测 + 字段级迁移 + 迁移前 .bak。

依据：细化_4a_存储层契约 §六 存档兼容迁移（MIG-1~5 / D-06）——
  - 两层版本模型 §6.1：meta.db_schema_version（存档结构版本，当前 2）
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

from qbot_rpg.data.item import new_item_uid
from qbot_rpg.storage.connection import Database, StorageError, Transaction
from qbot_rpg.storage.schema import (
    CREATE_INDEXES,
    CREATE_TABLE_META,
    CREATE_TABLE_PLAYER_PACK_STATE,
    PLAYER_PACK_STATE_INDEXES,
    SCHEMA_TABLES,
)

# ---------------------------------------------------------------------------
# 存档结构版本常量（当前 3：批 D 增补 player_pack_state；批40 · H4 JSON 级
# 补发实例 uid。结构变更递增并追加迁移步）
# ---------------------------------------------------------------------------
DB_SCHEMA_VERSION: int = 3
META_KEY: str = "global"

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
# 迁移步注册表：[(from_version, to_version, coro_fn)]，from < to 且相邻步必须衔接
# （migrate_database P1-2 完整性校验）。当前链：1→2（批 D）、2→3（批40 · H4）。
# 后续结构变更在此追加步，形如 (3, 4, migrate_v3_to_v4)。
# ---------------------------------------------------------------------------
async def migrate_v1_to_v2(
    tx: "Transaction", db: Database, *, now: Optional[str] = None
) -> None:
    """v1→v2：幂等补建内容包通用状态格子表 player_pack_state（及其索引）。

    新库**不经此步**——SCHEMA_DDL 建库即含该表（新库直接具备，防「新库漏结构」）；
    旧库升级走本步：``CREATE TABLE IF NOT EXISTS`` / ``CREATE INDEX IF NOT EXISTS``
    对已存在对象为 no-op，**不触碰 players 等既有表与任何既有数据**（MIG-1 字段级
    迁移语义）。每级单事务由 migrate_database 包裹，失败自动回滚（MIG-5）。
    """
    await tx.execute(CREATE_TABLE_PLAYER_PACK_STATE)
    for index_ddl in PLAYER_PACK_STATE_INDEXES:
        await tx.execute(index_ddl)


def _loads_or(raw: Any, default: Any) -> Any:
    """JSON 列读解（缺/非法 → 深拷贝 default；迁移步内只读，不改写非法行）。"""
    if not raw:
        return default
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return default
    return v if v is not None else default


def backfill_instance_uids(inv: Any, equip: Any) -> Tuple[Any, Any, int]:
    """**纯函数**：给 inventory 行补 `uid`、给 equipment 槽补回指行 uid（批40 · H4）。

    幂等：已有非空 uid 的行/槽一律跳过 → 重复执行不再改写（第二次补发计数 = 0）。
    无损：只在缺失时新增键，不改动/不删除任何既有键与值；`inv`/`equip` 形态非法
    （非 list/dict）时原样返回、不触碰。
    补发口径：
      1) 每行缺失 uid → `new_item_uid()`（唯一生成口径单源，见 data/item.py）；
      2) 每槽缺失 uid → 指向**首个未被其它槽消费**的同 item_id 背包行 uid（对齐
         既有「item_id 首匹配」语义；同 id 多槽各绑一行、互不抢占）；无匹配行 →
         留空（读取兜底 item_id，与迁移前行为一致）。
    返回 (inv, equip, 本次补发键数)。
    """
    count = 0
    if not isinstance(inv, list):
        return inv, equip, count
    for row in inv:
        if isinstance(row, dict) and not row.get("uid"):
            row["uid"] = new_item_uid()
            count += 1
    if not isinstance(equip, dict):
        return inv, equip, count
    used: set = set()
    for slot_id in sorted(str(k) for k in equip.keys()):
        slot = equip.get(slot_id)
        if not isinstance(slot, dict) or slot.get("uid"):
            continue
        iid = str(slot.get("item_id") or "")
        if not iid:
            continue
        hit: Optional[int] = None
        for idx, row in enumerate(inv):
            if idx in used or not isinstance(row, dict):
                continue
            if str(row.get("item_id") or "") == iid:
                hit = idx
                break
        if hit is None:
            continue
        used.add(hit)
        row_uid = str(inv[hit].get("uid") or "")
        if row_uid:
            slot["uid"] = row_uid
            count += 1
    return inv, equip, count


async def migrate_v2_to_v3(
    tx: "Transaction", db: Database, *, now: Optional[str] = None
) -> None:
    """v2→v3（批40 · H4）：JSON 级补发实例 uid——inventory 行 + equipment 槽。

    - **新库不经此步**：`ensure_meta` 空库直写 DB_SCHEMA_VERSION（=3），新建实例
      由 `ItemInstance.__post_init__`/构造点经 `new_item_uid()` 天然带 uid → 新库
      直接具备（不重犯「新库漏结构」：本步只需处理存量 JSON，无 DDL 需补）。
    - **旧库升级**：逐 players 行读 inventory/equipment JSON → `backfill_instance_uids`
      幂等补发 → 仅在该行确有补发时整列回写（未变更行不写，避免无谓写放大）。
    - **无损/可回退**：只加键不改值；非法 JSON/形态的行原样跳过（MIG-1 不拦截加载）；
      失败由 migrate_database 单事务回滚 + 迁移前 .bak（pre_migration_backup）兜底。
    """
    rows = await tx.fetchall(
        "SELECT player_qid, inventory, equipment FROM players"
    )
    for row in rows:
        inv = _loads_or(row["inventory"], [])
        equip = _loads_or(row["equipment"], {})
        inv_out, equip_out, changed = backfill_instance_uids(inv, equip)
        if not changed:
            continue
        await tx.execute(
            "UPDATE players SET inventory = ?, equipment = ? WHERE player_qid = ?",
            (
                json.dumps(inv_out, ensure_ascii=False),
                json.dumps(equip_out, ensure_ascii=False),
                row["player_qid"],
            ),
        )


MIGRATION_STEPS: List[Tuple[int, int, Callable[..., Any]]] = [
    (1, 2, migrate_v1_to_v2),
    (2, 3, migrate_v2_to_v3),
]


# ---------------------------------------------------------------------------
# 批46 · 符文地基（43-A）：rune_sockets 容器缺补（纯函数）
# ---------------------------------------------------------------------------
def backfill_rune_sockets(ps: Any) -> Tuple[Any, int]:
    """**纯函数**：给 persistent_state 补符文镶嵌容器 `rune_sockets`（批46 · 43-A）。

    口径（`/root/deliverables/符文系统_实现口径.md` §二.4）：镶嵌状态挂
    `player.persistent_state["rune_sockets"]`（键 = ItemInstance.uid）——`persistent_state`
    本就是**自由 dict**，缺省空即无符文，故**无需** DB_SCHEMA_VERSION 3→4（口径明示）。
    本函数即「旧档幂等补 / 新库直具备」的**唯一补缺口径**：
      - **幂等**：键已存在（任意形态）→ 原样返回、计数 0（重复执行零改动）；
      - **无损**：只在键**缺失**时新增空 dict `{}`，不改/不删任何既有键与值；
      - 非 dict（None/list/…）→ 原样返回、计数 0（非法行不拦加载，MIG-1 口径）。
    读侧由 `storage.repository._player_from_dict` 调用（旧档读入即补、下次落档写出）；
    新建玩家的 `make_context` 经 `_ps_init(ps, "rune_sockets", {})` 惰性挂回 →
    「新库直接具备」（不重犯「新库漏结构」：本函数与版本无关，对所有存档统一生效）。
    返回 (ps, 本次新增键数 0/1)。
    """
    if not isinstance(ps, dict):
        return ps, 0
    if "rune_sockets" in ps:
        return ps, 0
    ps["rune_sockets"] = {}
    return ps, 1


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
    tx: "Transaction", table: str, column: str, ddl: str
) -> bool:
    """列级字段迁移：缺补默认（ADD COLUMN ... DEFAULT）/ 多忽略（已存在跳过）。

    返回是否实际加了列。**必须在 db.tx() 事务内调用并传事务句柄 tx**（MIG-5
    每级单事务；P1-3：传 db 会在 tx() 体内再抢 _write_lock 造成永久死锁）。
    """
    cols = set()
    for row in await tx.fetchall(f"PRAGMA table_info({table})"):
        cols.add(str(row["name"]))
    if column in cols:
        return False
    await tx.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
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
    P1-1：迁移前备份失败同样不直抛——记录失败履历返回 state=failed，
    repository._bootstrap 按既有失败路径告警并重试，绝不因备份起不来。
    P1-2：迁移链完整性校验（首步 from == 当前版本、相邻步衔接、末步 to ==
    当前目标）；全部应用后读回 meta 版本验证收敛 + round-trip 抽查，失败按
    failed 处理，不谎报 migrated。
    """
    version = await ensure_meta(db, now=now)
    if version >= DB_SCHEMA_VERSION:
        return MigrationResult(version, DB_SCHEMA_VERSION, note="schema 已是最新")

    ordered = sorted(
        (s for s in MIGRATION_STEPS if s[0] >= version and s[1] <= DB_SCHEMA_VERSION),
        key=lambda s: s[0],
    )
    # P1-2：迁移链完整性校验——断档/跳级不静默执行（MIG-5「meta.migration_log 有始有终」）
    cur = version
    for from_v, to_v, _fn in ordered:
        if from_v != cur:
            return MigrationResult(
                version, version, state="failed",
                note=f"迁移链断档: 期望 from={cur}，实际 from={from_v}（MIG-5）",
            )
        if to_v <= from_v:
            return MigrationResult(
                version, version, state="failed",
                note=f"迁移步非法: from={from_v} to={to_v}（to 必须 > from）",
            )
        cur = to_v
    if cur != DB_SCHEMA_VERSION:
        # P1-2：零步骤/链不完整时不得谎报 migrated（版本永不收敛的静默 bug）
        return MigrationResult(
            version, version, state="failed",
            note=f"迁移链不完整: 末步到 {cur}，目标 {DB_SCHEMA_VERSION}（缺迁移步）",
        )

    backup_id: Optional[str] = None
    if force_backup:
        # P1-1：备份失败不直抛——回退为 failed，由 _bootstrap 告警后携带旧版继续
        try:
            backup_id = await pre_migration_backup(db, now=now)
        except Exception as exc:  # noqa: BLE001 — 备份失败兜底（RW-4 场景：磁盘满/写失败）
            try:
                await append_migration_log(
                    db,
                    {"from": version, "to": version, "at": now or utcnow(),
                     "result": "failed", "error": f"迁移前备份失败 {type(exc).__name__}: {exc}"},
                    now=now,
                )
            except BaseException:
                pass
            return MigrationResult(
                version, version, state="failed",
                backup_id=None, note=f"迁移前备份失败: {exc}",
            )

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
        except Exception as exc:  # noqa: BLE001 — 失败回滚后整体交接；CancelledError 需重抛（P2-8）
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

    # P1-2：全部步应用后读回 meta 版本，验证收敛到目标（防版本停滞/谎报）
    final_row = await db.fetchone(
        "SELECT db_schema_version FROM meta WHERE key = ?", (META_KEY,)
    )
    if final_row is None or int(final_row["db_schema_version"]) != DB_SCHEMA_VERSION:
        return MigrationResult(
            version, version, applied_steps=tuple(applied), state="failed",
            backup_id=backup_id,
            note=f"迁移后版本未收敛: meta={final_row and final_row['db_schema_version']}, "
                 f"目标={DB_SCHEMA_VERSION}（MIG-5 round-trip）",
        )

    return MigrationResult(
        version, DB_SCHEMA_VERSION, applied_steps=tuple(applied),
        state="migrated", backup_id=backup_id,
    )


__all__ = [
    "DB_SCHEMA_VERSION",
    "META_KEY",
    "MIGRATION_STEPS",
    "migrate_v1_to_v2",
    "migrate_v2_to_v3",
    "backfill_instance_uids",
    "backfill_rune_sockets",
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
