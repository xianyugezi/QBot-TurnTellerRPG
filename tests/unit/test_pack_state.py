"""player_pack_state 内容包通用状态格子（批 D）单测。

覆盖：读缺省 / 写读一致 / 玩家×包互不干扰 / 覆盖与浅合并 / 非对象·不可序列化·NaN 拒绝 /
体积上限 / 清空与列举 / 损坏行兜底 / 序列化往返（中文·嵌套·大数组）/ 真实建库迁移
（v1 旧库 → v1→v2）/ 新库直接具备且版本正确。

纪律：零 NoneBot；迁移用 tmp_path 真实文件库（真实 sqlite3 建 v1 旧库 + 真跑
migrate_database），**绝不触碰真实玩家库**。
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

import qbot_rpg.storage.pack_state as ps
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.migrations import DB_SCHEMA_VERSION, migrate_database
from qbot_rpg.storage.pack_state import (
    PACK_STATE_MAX_BYTES,
    PackStateTooLargeError,
    PackStateValidationError,
    clear_pack_state,
    get_pack_state,
    list_pack_states,
    patch_pack_state,
    set_pack_state,
)
from qbot_rpg.storage.repository import Repository
from qbot_rpg.storage.schema import CREATE_TABLE_META, CREATE_TABLE_PLAYERS

# players 表冻结列集（批 D 纪律：不改 players 表列；任何内容包字段只进
# player_pack_state 的 state 格里，绝不给核心表加列）
PLAYERS_COLUMNS_FROZEN = {
    "player_qid", "nickname", "level", "exp", "hp", "mp", "currencies", "inventory",
    "equipment", "stats", "persistent_state", "longline_counters", "reputation_state",
    "codex_state", "achievement_state", "title_state", "content_pack_id",
    "content_pack_version", "schema_version", "last_seen_group", "created_at",
    "last_active_at",
}


@pytest.fixture
async def db():
    database = Database(":memory:")
    try:
        yield database
    finally:
        await database.close()


def _encoded_size(state: object) -> int:
    return len(
        json.dumps(
            state, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    )


# ---------------------------------------------------------------------------
# 读写基本语义
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_get_missing_returns_empty_dict(db):
    assert await get_pack_state(db, "p1", "packA") == {}


@pytest.mark.asyncio
async def test_set_then_get_serialization_roundtrip(db):
    state = {
        "名称": "云海",
        "nested": {"列表": [1, 2, {"中文键": True}], "空": None},
        "大数组": list(range(1000)),
        "浮点": 3.5,
    }
    await set_pack_state(db, "p1", "packA", state)
    assert await get_pack_state(db, "p1", "packA") == state


@pytest.mark.asyncio
async def test_packs_and_players_are_isolated(db):
    await set_pack_state(db, "p1", "packA", {"who": "p1A"})
    await set_pack_state(db, "p1", "packB", {"who": "p1B"})
    await set_pack_state(db, "p2", "packA", {"who": "p2A"})

    assert await get_pack_state(db, "p1", "packA") == {"who": "p1A"}
    assert await get_pack_state(db, "p1", "packB") == {"who": "p1B"}
    assert await get_pack_state(db, "p2", "packA") == {"who": "p2A"}
    assert await list_pack_states(db, "p1") == {
        "packA": {"who": "p1A"}, "packB": {"who": "p1B"},
    }
    assert await list_pack_states(db, "p2") == {"packA": {"who": "p2A"}}
    assert await list_pack_states(db, "p3") == {}

    await clear_pack_state(db, "p1", "packA")
    assert await get_pack_state(db, "p1", "packA") == {}
    assert await get_pack_state(db, "p2", "packA") == {"who": "p2A"}   # 他人不受影响
    assert await get_pack_state(db, "p1", "packB") == {"who": "p1B"}   # 他包不受影响


@pytest.mark.asyncio
async def test_overwrite_replaces_whole_cell(db):
    await set_pack_state(db, "p1", "packA", {"a": 1, "b": 2, "nest": {"x": 1}})
    await set_pack_state(db, "p1", "packA", {"a": 9})
    assert await get_pack_state(db, "p1", "packA") == {"a": 9}


@pytest.mark.asyncio
async def test_patch_is_shallow_merge(db):
    await set_pack_state(db, "p1", "packA", {"a": 1, "nest": {"x": 1, "y": 2}})
    merged = await patch_pack_state(db, "p1", "packA", {"b": 3, "nest": {"x": 9}})
    assert merged == {"a": 1, "b": 3, "nest": {"x": 9}}       # 仅顶层合并，嵌套整体替换
    assert await get_pack_state(db, "p1", "packA") == merged   # 返回值 = 落库值

    assert await patch_pack_state(db, "p1", "packNew", {"k": 1}) == {"k": 1}  # 不存在 = 新建
    assert await get_pack_state(db, "p1", "packNew") == {"k": 1}


@pytest.mark.asyncio
async def test_clear_is_idempotent(db):
    await clear_pack_state(db, "p1", "packA")     # 不存在也成功
    await set_pack_state(db, "p1", "packA", {"a": 1})
    await clear_pack_state(db, "p1", "packA")
    assert await get_pack_state(db, "p1", "packA") == {}
    await clear_pack_state(db, "p1", "packA")
    assert await list_pack_states(db, "p1") == {}


@pytest.mark.asyncio
async def test_updated_at_recorded(db):
    await set_pack_state(db, "p1", "packA", {"a": 1})
    row = await db.fetchone_read(
        "SELECT updated_at FROM player_pack_state WHERE player_id=? AND pack_id=?",
        ("p1", "packA"),
    )
    assert row["updated_at"] and str(row["updated_at"]).endswith("Z")
    await patch_pack_state(db, "p1", "packA", {"b": 2})
    row2 = await db.fetchone_read(
        "SELECT updated_at FROM player_pack_state WHERE player_id=? AND pack_id=?",
        ("p1", "packA"),
    )
    assert row2["updated_at"] and str(row2["updated_at"]).endswith("Z")


@pytest.mark.asyncio
async def test_get_returns_independent_copy(db):
    await set_pack_state(db, "p1", "packA", {"a": {"deep": 1}})
    first = await get_pack_state(db, "p1", "packA")
    first["a"]["deep"] = 999          # 改内存副本
    assert await get_pack_state(db, "p1", "packA") == {"a": {"deep": 1}}


# ---------------------------------------------------------------------------
# 边界拒绝：非对象 / 不可序列化 / 非法键 / 超限
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
@pytest.mark.parametrize("bad", [[1, 2], "text", 3, 3.5, True, None])
async def test_non_object_state_rejected(db, bad):
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", "packA", bad)
    assert await get_pack_state(db, "p1", "packA") == {}


@pytest.mark.asyncio
async def test_unserializable_and_non_finite_rejected(db):
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", "packA", {"ok": 1, "bad": object()})
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", "packA", {"nan": float("nan")})
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", "packA", {"inf": float("inf")})
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", "packA", {1: "int-key"})   # 顶层键非字符串
    assert await get_pack_state(db, "p1", "packA") == {}          # 全部未写入


@pytest.mark.asyncio
async def test_patch_non_object_rejected(db):
    with pytest.raises(PackStateValidationError):
        await patch_pack_state(db, "p1", "packA", [1, 2])


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_player_id", ["", None, 7])
async def test_invalid_player_id_rejected(db, bad_player_id):
    with pytest.raises(PackStateValidationError):
        await get_pack_state(db, bad_player_id, "packA")
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, bad_player_id, "packA", {"a": 1})
    with pytest.raises(PackStateValidationError):
        await clear_pack_state(db, bad_player_id, "packA")
    with pytest.raises(PackStateValidationError):
        await list_pack_states(db, bad_player_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_pack_id", ["", None, 7])
async def test_invalid_pack_id_rejected(db, bad_pack_id):
    with pytest.raises(PackStateValidationError):
        await get_pack_state(db, "p1", bad_pack_id)
    with pytest.raises(PackStateValidationError):
        await set_pack_state(db, "p1", bad_pack_id, {"a": 1})
    with pytest.raises(PackStateValidationError):
        await clear_pack_state(db, "p1", bad_pack_id)
    assert await list_pack_states(db, "p1") == {}   # list 无 pack_id 参数，不受影响


@pytest.mark.asyncio
async def test_size_limit_enforced(db):
    just_under = {"pad": "x" * (PACK_STATE_MAX_BYTES - 32)}
    assert _encoded_size(just_under) <= PACK_STATE_MAX_BYTES
    await set_pack_state(db, "p1", "packA", just_under)
    assert await get_pack_state(db, "p1", "packA") == just_under

    over = {"pad": "x" * PACK_STATE_MAX_BYTES}
    assert _encoded_size(over) > PACK_STATE_MAX_BYTES
    with pytest.raises(PackStateTooLargeError):
        await set_pack_state(db, "p1", "packB", over)
    assert await get_pack_state(db, "p1", "packB") == {}
    assert await get_pack_state(db, "p1", "packA") == just_under   # 既有格子不受影响


@pytest.mark.asyncio
async def test_patch_overflow_does_not_write(db):
    await set_pack_state(db, "p1", "packA", {"keep": 1})
    with pytest.raises(PackStateTooLargeError):
        await patch_pack_state(db, "p1", "packA", {"pad": "x" * PACK_STATE_MAX_BYTES})
    assert await get_pack_state(db, "p1", "packA") == {"keep": 1}


@pytest.mark.asyncio
async def test_corrupt_rows_read_as_empty(db):
    await db.execute(
        "INSERT INTO player_pack_state (player_id, pack_id, state, updated_at)"
        " VALUES (?,?,?,?)", ("p1", "bad_json", "not-json", None))
    await db.execute(
        "INSERT INTO player_pack_state (player_id, pack_id, state, updated_at)"
        " VALUES (?,?,?,?)", ("p1", "bad_type", "[1,2]", None))
    assert await get_pack_state(db, "p1", "bad_json") == {}
    assert await get_pack_state(db, "p1", "bad_type") == {}
    assert await list_pack_states(db, "p1") == {"bad_json": {}, "bad_type": {}}


# ---------------------------------------------------------------------------
# 结构与迁移（真实建库）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_new_db_has_table_and_version_without_migration(db):
    """新库直接具备 player_pack_state（不经迁移步），版本收敛到当前值。"""
    rows = await db.fetchall_read(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='player_pack_state'"
    )
    assert [r["name"] for r in rows] == ["player_pack_state"]

    result = await migrate_database(db)
    assert result.state == "up_to_date"
    meta = await db.fetchone_read("SELECT db_schema_version FROM meta WHERE key='global'")
    assert int(meta["db_schema_version"]) == DB_SCHEMA_VERSION == 2


@pytest.mark.asyncio
async def test_players_table_columns_frozen(db):
    """批 D 纪律：不加 players 列（内容包字段一律进 pack 格子，不在核心表生根）。"""
    await db.fetchall_read("SELECT 1 FROM players LIMIT 1")
    cols = {r["name"] for r in await db.fetchall_read("PRAGMA table_info(players)")}
    assert cols == PLAYERS_COLUMNS_FROZEN


def test_pack_state_module_has_zero_content_dependency():
    """纯存储层：不 import content/bridge 层，也不内置任何内容包名。"""
    src = Path(ps.__file__).read_text(encoding="utf-8")
    assert "qbot_rpg.content" not in src
    assert "qbot_rpg_bridge" not in src


@pytest.mark.asyncio
async def test_migration_step_creates_table_when_absent(db):
    """v1 库缺表 + meta 版本 1 → v1→v2 步真实补建（幂等）。"""
    await db.fetchall_read("SELECT 1 FROM meta LIMIT 1")     # 先建库
    await db.execute("DROP TABLE player_pack_state")
    await db.execute(
        "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
        " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    missing = await db.fetchall_read(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='player_pack_state'"
    )
    assert missing == []

    result = await migrate_database(db)
    assert result.state == "migrated"
    assert (1, 2) in result.applied_steps
    present = await db.fetchall_read(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='player_pack_state'"
    )
    assert [r["name"] for r in present] == ["player_pack_state"]


@pytest.mark.asyncio
async def test_migration_preserves_existing_pack_state_rows(db):
    await set_pack_state(db, "p1", "packA", {"keep": [1, 2, 3]})
    await db.execute(
        "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
        " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    result = await migrate_database(db)
    assert result.state == "migrated"
    assert await get_pack_state(db, "p1", "packA") == {"keep": [1, 2, 3]}


def _make_v1_old_db(path: Path) -> None:
    """原生 sqlite3 造 v1 旧库：真实 players 行 + meta 版本 1，且没有新表。"""
    conn = sqlite3.connect(str(path))
    try:
        conn.executescript(
            CREATE_TABLE_PLAYERS.strip() + ";\n" + CREATE_TABLE_META.strip() + ";"
        )
        conn.execute(
            "INSERT INTO players (player_qid, nickname, level, exp, hp, mp, currencies,"
            " content_pack_id, content_pack_version, schema_version, created_at, last_active_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            ("10086", "旧档玩家", 7, 1234, 88, 42, '{"gold": 999}', "oldpack", "1.0", 4,
             "2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
            " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        conn.commit()
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_migrate_v1_old_db_end_to_end(tmp_path):
    """v1 旧库 → migrate_database → v2 + 表存在 + 既有 players 数据无损。"""
    path = tmp_path / "old_v1.db"
    _make_v1_old_db(path)

    conn = sqlite3.connect(str(path))
    try:
        before = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_pack_state'"
        )]
    finally:
        conn.close()
    assert before == [], "旧库不应已有 player_pack_state"

    database = Database(str(path))
    try:
        result = await migrate_database(database)
        assert result.state == "migrated"
        assert (1, 2) in result.applied_steps
        assert result.to_version == DB_SCHEMA_VERSION == 2
        assert result.backup_id, "真实文件库迁移必须产生 .bak 快照"

        meta = await database.fetchone_read(
            "SELECT db_schema_version, migration_log FROM meta WHERE key='global'"
        )
        assert int(meta["db_schema_version"]) == 2
        logs = json.loads(meta["migration_log"])
        assert logs[-1]["from"] == 1 and logs[-1]["to"] == 2 and logs[-1]["result"] == "ok"

        cols = {
            r["name"]: r
            for r in await database.fetchall_read("PRAGMA table_info(player_pack_state)")
        }
        assert set(cols) == {"player_id", "pack_id", "state", "updated_at"}
        assert int(cols["player_id"]["pk"]) == 1 and int(cols["pack_id"]["pk"]) == 2
        assert int(cols["player_id"]["notnull"]) == 1
        assert int(cols["pack_id"]["notnull"]) == 1
        assert int(cols["state"]["notnull"]) == 1
        assert "{}" in str(cols["state"]["dflt_value"])

        row = await database.fetchone_read("SELECT * FROM players WHERE player_qid='10086'")
        assert row["nickname"] == "旧档玩家"
        assert (int(row["level"]), int(row["exp"]), int(row["hp"]), int(row["mp"])) == (
            7, 1234, 88, 42,
        )
        assert json.loads(row["currencies"]) == {"gold": 999}
        assert row["content_pack_id"] == "oldpack"
        assert int(row["schema_version"]) == 4

        await set_pack_state(database, "10086", "packX", {"k": "v"})
        assert await get_pack_state(database, "10086", "packX") == {"k": "v"}

        again = await migrate_database(database)
        assert again.state == "up_to_date"
    finally:
        await database.close()


@pytest.mark.asyncio
async def test_repository_bootstrap_exposes_pack_state():
    """Repository 懒迁移路径（D-06）下新库同样具备该表且版本正确。"""
    repo = Repository(Database(":memory:"))
    try:
        await repo.player_exists("no-such-player")     # 触发 _bootstrap
        rows = await repo.db.fetchall_read(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='player_pack_state'"
        )
        assert [r["name"] for r in rows] == ["player_pack_state"]
        meta = await repo.db.fetchone_read(
            "SELECT db_schema_version FROM meta WHERE key='global'"
        )
        assert int(meta["db_schema_version"]) == DB_SCHEMA_VERSION == 2
        await set_pack_state(repo.db, "p1", "packA", {"via": "repo.db"})
        assert await get_pack_state(repo.db, "p1", "packA") == {"via": "repo.db"}
    finally:
        await repo.close()
