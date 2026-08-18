"""存储层 Schema 唯一数据源：7 表 + 7 组索引 + CHECK 约束。

依据：细化_4a_存储层契约 §1.1 表总表（7 表 → 五类持久化语义）、§1.2 players
字段级 schema（唯一数据源）、§1.3 其余 6 表（sessions/idempotency_keys/meta/
world_state/recycle_bin/backups）、§1.4 索引与 PRAGMA（7 组索引）、SCHEMA-8
版本元信息必填。

说明：
- 全部 JSON 列 NOT NULL + DEFAULT（'{}'/'[]'），字段缺省 = 默认值不拦截加载
  （SCHEMA-6）。
- sessions.player_qid 主键即单玩家 1 会话互斥约束（SCHEMA-7，FK → players
  ON DELETE CASCADE）。
- 幂等键复合主键 (message_id, group_id, player_qid)（IDEM-1）。
- meta 单行 key='global'（§1.3）。
- world_state 每行带 version 列做 CAS（TX-3）。
- 索引 7 组：6 个显式索引 +「PK 索引自动隐含」合为 7 组（§1.4 表）。
"""

from typing import Final, Tuple

# ---------------------------------------------------------------------------
# CHECK 约束枚举（4a §1.3）
# ---------------------------------------------------------------------------
SESSION_TYPES: Final[Tuple[str, ...]] = ("battle", "alchemy", "challenge_alchemy")
RECYCLE_OBJECT_TYPES: Final[Tuple[str, ...]] = ("pack_entry", "session", "player")
BACKUP_TYPES: Final[Tuple[str, ...]] = ("auto", "manual", "pre_update", "pre_migration")

# ---------------------------------------------------------------------------
# CREATE TABLE（7 表）
# ---------------------------------------------------------------------------
CREATE_TABLE_PLAYERS: Final[str] = """
CREATE TABLE IF NOT EXISTS players (
    player_qid          TEXT PRIMARY KEY,
    nickname            TEXT NOT NULL,
    level               INTEGER NOT NULL DEFAULT 1,
    exp                 INTEGER NOT NULL DEFAULT 0,
    hp                  INTEGER NOT NULL,
    mp                  INTEGER NOT NULL,
    currencies          TEXT NOT NULL DEFAULT '{}',
    inventory           TEXT NOT NULL DEFAULT '[]',
    equipment           TEXT NOT NULL DEFAULT '{}',
    stats               TEXT NOT NULL DEFAULT '{}',
    persistent_state    TEXT NOT NULL DEFAULT '{}',
    longline_counters   TEXT NOT NULL DEFAULT '{}',
    reputation_state    TEXT NOT NULL DEFAULT '{}',
    codex_state         TEXT NOT NULL DEFAULT '{}',
    achievement_state   TEXT NOT NULL DEFAULT '[]',
    title_state         TEXT NOT NULL DEFAULT '{}',
    content_pack_id     TEXT NOT NULL,
    content_pack_version TEXT NOT NULL,
    schema_version      INTEGER NOT NULL DEFAULT 4,
    last_seen_group     TEXT,
    created_at          TEXT NOT NULL,
    last_active_at      TEXT NOT NULL
)
"""

CREATE_TABLE_SESSIONS: Final[str] = """
CREATE TABLE IF NOT EXISTS sessions (
    player_qid      TEXT PRIMARY KEY
                    REFERENCES players(player_qid) ON DELETE CASCADE,
    session_type    TEXT NOT NULL CHECK (session_type IN ('battle','alchemy','challenge_alchemy')),
    version         INTEGER NOT NULL DEFAULT 1,
    payload_json    TEXT NOT NULL,
    random_seed     INTEGER NOT NULL,
    created_at      TEXT NOT NULL,
    last_active_at  TEXT NOT NULL
)
"""

CREATE_TABLE_IDEMPOTENCY_KEYS: Final[str] = """
CREATE TABLE IF NOT EXISTS idempotency_keys (
    message_id      TEXT NOT NULL,
    group_id        TEXT NOT NULL,
    player_qid      TEXT NOT NULL,
    command         TEXT NOT NULL,
    result_hash     TEXT,
    created_at      TEXT NOT NULL,
    PRIMARY KEY (message_id, group_id, player_qid)
)
"""

CREATE_TABLE_META: Final[str] = """
CREATE TABLE IF NOT EXISTS meta (
    key                 TEXT PRIMARY KEY,
    db_schema_version   INTEGER NOT NULL,
    current_pack_id     TEXT,
    current_pack_version TEXT,
    last_migration_at   TEXT,
    migration_log       TEXT NOT NULL DEFAULT '[]',
    created_at          TEXT,
    updated_at          TEXT
)
"""

CREATE_TABLE_WORLD_STATE: Final[str] = """
CREATE TABLE IF NOT EXISTS world_state (
    key         TEXT PRIMARY KEY,
    value_json  TEXT NOT NULL,
    version     INTEGER NOT NULL DEFAULT 0,
    updated_at  TEXT
)
"""

CREATE_TABLE_RECYCLE_BIN: Final[str] = """
CREATE TABLE IF NOT EXISTS recycle_bin (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type   TEXT NOT NULL CHECK (object_type IN ('pack_entry','session','player')),
    object_key    TEXT NOT NULL,
    payload_json  TEXT NOT NULL,
    deleted_at    TEXT NOT NULL,
    expire_at     TEXT NOT NULL
)
"""

CREATE_TABLE_BACKUPS: Final[str] = """
CREATE TABLE IF NOT EXISTS backups (
    backup_id   TEXT PRIMARY KEY,
    file_path   TEXT NOT NULL,
    backup_type TEXT NOT NULL CHECK (backup_type IN ('auto','manual','pre_update','pre_migration')),
    size_bytes  INTEGER NOT NULL,
    created_at  TEXT NOT NULL
)
"""

# 7 表（§1.1）；顺序无依赖（players 先建便于 FK 引用）
SCHEMA_TABLES: Final[Tuple[str, ...]] = (
    CREATE_TABLE_PLAYERS,
    CREATE_TABLE_SESSIONS,
    CREATE_TABLE_IDEMPOTENCY_KEYS,
    CREATE_TABLE_META,
    CREATE_TABLE_WORLD_STATE,
    CREATE_TABLE_RECYCLE_BIN,
    CREATE_TABLE_BACKUPS,
)

# ---------------------------------------------------------------------------
# 索引（§1.4：6 显式索引 + PK 自动索引 = 7 组）
# ---------------------------------------------------------------------------
CREATE_INDEXES: Final[Tuple[str, ...]] = (
    "CREATE INDEX IF NOT EXISTS idx_players_last_active ON players(last_active_at)",
    "CREATE INDEX IF NOT EXISTS idx_players_pack ON players(content_pack_id, schema_version)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_active ON sessions(last_active_at)",
    "CREATE INDEX IF NOT EXISTS idx_idem_created ON idempotency_keys(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_recycle_expire ON recycle_bin(expire_at)",
    "CREATE INDEX IF NOT EXISTS idx_backup_created ON backups(created_at)",
)

# 建库一次性执行的全部 DDL（建表 + 索引；每条以分号结尾供 executescript 拆分）
SCHEMA_DDL: Final[str] = "\n".join(s.rstrip() + ";\n" for s in (*SCHEMA_TABLES, *CREATE_INDEXES))

# ---------------------------------------------------------------------------
# PRAGMA 连接参数（§1.4 写死，建库即生效）
# ---------------------------------------------------------------------------
PRAGMA_JOURNAL_MODE: Final[str] = "WAL"          # L1436 防崩溃；内存库回退 memory 不报错
PRAGMA_BUSY_TIMEOUT_MS: Final[int] = 5000         # L1613 / 【规则】L107
PRAGMA_SYNCHRONOUS: Final[str] = "NORMAL"         # WAL 下兼顾安全与写吞吐
PRAGMA_FOREIGN_KEYS: Final[str] = "ON"
PRAGMA_AUTO_VACUUM: Final[str] = "INCREMENTAL"    # 周级/超阈值 VACUUM（RC-5）

__all__ = [
    "SESSION_TYPES",
    "RECYCLE_OBJECT_TYPES",
    "BACKUP_TYPES",
    "CREATE_TABLE_PLAYERS",
    "CREATE_TABLE_SESSIONS",
    "CREATE_TABLE_IDEMPOTENCY_KEYS",
    "CREATE_TABLE_META",
    "CREATE_TABLE_WORLD_STATE",
    "CREATE_TABLE_RECYCLE_BIN",
    "CREATE_TABLE_BACKUPS",
    "SCHEMA_TABLES",
    "CREATE_INDEXES",
    "SCHEMA_DDL",
    "PRAGMA_JOURNAL_MODE",
    "PRAGMA_BUSY_TIMEOUT_MS",
    "PRAGMA_SYNCHRONOUS",
    "PRAGMA_FOREIGN_KEYS",
    "PRAGMA_AUTO_VACUUM",
]
