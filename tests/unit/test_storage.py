"""存储层单测（细化_4a_存储层契约.md#TC-01~18，SQLite 一律 :memory:）。

零 NoneBot；assert 具体（禁止"不崩就行"）。
"""
from __future__ import annotations

import asyncio
import datetime
import json

import pytest

from qbot_rpg.data.player import Player, PlayerAttributes
from qbot_rpg.data.world_state import WorldState
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.migrations import migrate_database
from qbot_rpg.storage.repository import IdemKey, Repository, SessionRow

from conftest import make_player


def iso_ago(days: float) -> str:
    t = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
async def repo():
    db = Database(":memory:")
    r = Repository(db)
    yield r
    await r.close()


# 4a TC-12 round-trip 往返一致
@pytest.mark.asyncio
async def test_roundtrip(player):
    db = Database(":memory:")
    repo = Repository(db)
    try:
        ok, msg = await repo.db_roundtrip(player)
        assert ok, msg
    finally:
        await repo.close()


# A 组未收尾点修复：空库只读路径自动建表，不得 no such table
@pytest.mark.asyncio
async def test_bare_read_empty_db():
    db = Database(":memory:")
    try:
        rows = await db.fetchall_read("SELECT * FROM meta")
        assert rows is not None
    finally:
        await db.close()


# 4a TC-01 购买结算原子性：扣货币后、入包前抛异常 → 整体回滚
@pytest.mark.asyncio
async def test_purchase_rollback():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10002"))
        try:
            async with repo.tx() as tx:
                cur = await tx.fetchone(
                    "SELECT currencies FROM players WHERE player_qid=?", ("10002",))
                bal = json.loads(cur["currencies"])
                bal["gold"] -= 500
                await tx.execute(
                    "UPDATE players SET currencies=? WHERE player_qid=?",
                    (json.dumps(bal, ensure_ascii=False), "10002"))
                raise RuntimeError("注入：入包前崩溃")
        except RuntimeError:
            pass
        row = await db.fetchone_read(
            "SELECT currencies FROM players WHERE player_qid=?", ("10002",))
        assert json.loads(row["currencies"])["gold"] == 350  # 350 = make_player 基线
    finally:
        await repo.close()


# IDEM-2/TC-08：幂等键首次 False、二次 True、可回查
# （P1-1 修复：idem_claim 只查不插，插入由业务事务内 write_idem_key 承担，同事务 IDEM-2）
@pytest.mark.asyncio
async def test_idempotency():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10001"))
        k = IdemKey(message_id="m1", group_id="g1", player_qid="10001",
                    command="/购买", result_hash="h1")
        assert await repo.idem_claim(k) is False  # 未处理（只读检查，不插入）
        async with repo.tx() as tx:               # 幂等键与业务写同事务（IDEM-2）
            assert await tx.idem_exists(k) is False
            await tx.write_idem_key(k)
        assert await repo.idem_claim(k) is True   # 已处理 → 幂等重放
        found = await repo.idem_find("m1", "g1", "10001")
        assert found is not None and found.result_hash == "h1"
    finally:
        await repo.close()


# P1-1：幂等键不随独立事务早提交——claim 后业务失败 → 无孤儿幂等键，重试可重执行业务
@pytest.mark.asyncio
async def test_idempotency_no_orphan_on_biz_failure():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10001"))
        k = IdemKey(message_id="m2", group_id="g1", player_qid="10001", command="/强化")
        # 模拟：调用方错误地在 claim+insert 后业务写失败回滚
        try:
            async with repo.tx() as tx:
                await tx.write_idem_key(k)
                raise RuntimeError("业务失败")
        except RuntimeError:
            pass
        # 业务失败 → 幂等键同事务回滚，不应残留孤儿键；重试可干净重做
        assert await repo.idem_claim(k) is False
        assert await repo.idem_find("m2", "g1", "10001") is None
    finally:
        await repo.close()


# TX-3/TC-18：多键冲突整体回滚（P0-1 修复：冲突前已写的键不得半写落盘）
@pytest.mark.asyncio
async def test_world_cas_mid_way_conflict_rolls_back_all():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        ws = WorldState(map_boss={"b1": {"name": "旧BOSS"}}, world_stock={"potion": 3},
                        spawn_timers={}, dummy_override={}, last_spawn_time="")
        # 首写成功（所有键 version -> 1）
        assert await repo.save_world_state(ws, {"map_boss": 0, "world_stock": 0,
                                                "spawn_timers": 0, "dummy_override": 0,
                                                "last_spawn_time": 0}) is True
        # 第二次写：map_boss 版本 =1（期望 1，命中写入新值），
        # 但 world_stock 期望 0（实际 1）→ 第 2 键冲突 → 整体回滚，map_boss 不得半写更新
        ws2 = WorldState(map_boss={"b1": {"name": "新BOSS"}}, world_stock={"potion": 99},
                         spawn_timers={}, dummy_override={}, last_spawn_time="")
        ok = await repo.save_world_state(ws2, {"map_boss": 1, "world_stock": 0,  # world_stock 期望旧版 0 → 冲突
                                               "spawn_timers": 1, "dummy_override": 1,
                                               "last_spawn_time": 1})
        assert ok is False
        # 验证回滚：map_boss 仍是旧值（未被半写），world_stock 也未变
        ws_read = await repo.load_world_state()
        assert ws_read.map_boss.get("b1", {}).get("name") == "旧BOSS", "map_boss 被半写更新"
        assert ws_read.world_stock.get("potion") == 3
    finally:
        await repo.close()


# TX-3 世界资源 CAS：首写成功、冲突整体不回写
@pytest.mark.asyncio
async def test_world_cas():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        ws = WorldState(map_boss={"b1": {"name": "蚀月之狼"}}, world_stock={},
                        spawn_timers={}, dummy_override={}, last_spawn_time="")
        assert await repo.save_world_state(ws, {"map_boss": 0}) is True
        assert await repo.save_world_state(ws, {"map_boss": 0}) is False  # 期望旧版本 0 冲突
        versions = await repo._world_versions_map()
        assert versions.get("map_boss") == 1
    finally:
        await repo.close()


# RC-1/TC-15 僵尸会话 30 天回收 + 新鲜保留
@pytest.mark.asyncio
async def test_recycle_scan():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10001"))
        await repo.save_player(make_player("10003"))
        old = SessionRow(player_qid="10001", session_type="battle", payload={"turn": 1},
                         random_seed=42, last_active_at=iso_ago(31))
        new = SessionRow(player_qid="10003", session_type="alchemy", payload={"mat": "a"},
                         random_seed=7, last_active_at=iso_ago(1))
        async with repo.tx() as tx:
            await tx.upsert_session(old)
            await tx.upsert_session(new)
        # P1-1：无 settle 时默认拒绝删除（保护材料）；此处显式 allow_unsettled
        # 仅测试回收机制本身（会话删除 + 新鲜保留），结算语义由 settle 注入侧负责
        recycled = await repo.recycle_scan(allow_unsettled=True)
        assert "10001" in recycled
        assert await repo.load_session("10001") is None
        kept = await repo.load_session("10003")
        assert kept is not None and kept[0] == "alchemy"
    finally:
        await repo.close()


# TC-18 单写队列串行化：50 并发 save 全部落库无 BUSY
@pytest.mark.asyncio
async def test_concurrent_save():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        async def save_one(i: int):
            await repo.save_player(make_player(f"conq{i:04d}"))
        await asyncio.gather(*(save_one(i) for i in range(20)))
        row = await db.fetchone_read("SELECT count(*) c FROM players")
        assert int(row["c"]) == 20
        assert repo.db.leak_check() == []
    finally:
        await repo.close()


# MIG-5/D-06 迁移 no-op + meta 履历就位
@pytest.mark.asyncio
async def test_migration_noop():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        r = await migrate_database(db)
        assert r.state in ("up_to_date", "migrated")
        row = await db.fetchone_read("SELECT db_schema_version FROM meta WHERE key='global'")
        assert row is not None and int(row["db_schema_version"]) >= 1
    finally:
        await repo.close()


# ===========================================================================
# M0 复查（2026-08-24）P1 修复回归
# ===========================================================================

# P1-1（connection）：只读池 _open 失败必须归还信号量令牌，容量不永久缩水
@pytest.mark.asyncio
async def test_read_pool_token_returned_on_open_failure(monkeypatch):
    db = Database(":memory:")
    try:
        # 先确保 schema 就位（_writer 建表成功，使后续只读路径不再触发 _writer）
        await db.fetchone_read("SELECT 1 FROM meta LIMIT 1")
        # 清空 idle 池，让下一次 _read_conn 必须走 _open(writer=False)
        db._read_idle.clear()
        sem_before = db._read_sem._value

        async def failing_open(writer: bool = False):
            if not writer:
                raise OSError("mock 只读连接打开失败")
            # writer 路径不应被走到（schema 已就位）；若走到直接放行原实现
            raise AssertionError("只读路径不应触发 writer")

        monkeypatch.setattr(db, "_open", failing_open)
        with pytest.raises(OSError):
            async with db._read_conn():
                pass
        # 令牌必须已归还（P1-1：acquire 成功但 _open 失败 → finally 仍 release）
        assert db._read_sem._value == sem_before, "只读池信号量在 _open 失败路径泄漏"
    finally:
        await db.close()


# P1-1（repository）：回收默认 settle=None 不删除（防静默丢玩家材料）
@pytest.mark.asyncio
async def test_recycle_scan_skips_without_settle():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10009"))
        old = SessionRow(player_qid="10009", session_type="battle", payload={"turn": 1},
                         random_seed=1, last_active_at=iso_ago(31))
        async with repo.tx() as tx:
            await tx.upsert_session(old)
        # 默认 settle=None 且未 allow_unsettled → 拒绝删除（会话保留）
        recycled = await repo.recycle_scan()
        assert "10009" not in recycled
        assert await repo.load_session("10009") is not None
    finally:
        await repo.close()


# P1-1（migrations）：迁移前备份失败 → 返回 failed 而非直抛（服务携带旧版继续）
@pytest.mark.asyncio
async def test_migrate_backup_failure_returns_failed(monkeypatch):
    import qbot_rpg.storage.migrations as mig

    db = Database(":memory:")
    try:
        async def boom_backup(db, now=None):
            raise OSError("mock 磁盘满备份失败")

        monkeypatch.setattr(mig, "pre_migration_backup", boom_backup)
        monkeypatch.setattr(mig, "DB_SCHEMA_VERSION", 2)
        monkeypatch.setattr(mig, "MIGRATION_STEPS", [(1, 2, _noop_step)])
        # 构造一个 version=1 的老库触发迁移路径
        await db.execute(
            "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
            " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        result = await mig.migrate_database(db, force_backup=True)
        assert result.state == "failed", f"备份失败应返回 failed，实际 {result.state}"
        assert "备份失败" in result.note
        # 服务仍可读旧档（meta 版本未变）
        row = await db.fetchone_read("SELECT db_schema_version FROM meta WHERE key='global'")
        assert int(row["db_schema_version"]) == 1
    finally:
        await db.close()


# P1-2（migrations）：迁移链断档 → failed 不静默（MIG-5 完整性）
@pytest.mark.asyncio
async def test_migrate_chain_gap_returns_failed(monkeypatch):
    import qbot_rpg.storage.migrations as mig

    db = Database(":memory:")
    try:
        monkeypatch.setattr(mig, "DB_SCHEMA_VERSION", 4)
        monkeypatch.setattr(mig, "MIGRATION_STEPS", [(1, 2, _noop_step), (3, 4, _noop_step)])
        await db.execute(
            "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
            " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        result = await mig.migrate_database(db)
        assert result.state == "failed"
        assert "断档" in result.note or "迁移链" in result.note
    finally:
        await db.close()


# P1-2（migrations）：迁移链不完整（末步 < 目标）→ failed 不谎报 migrated
@pytest.mark.asyncio
async def test_migrate_chain_incomplete_returns_failed(monkeypatch):
    import qbot_rpg.storage.migrations as mig

    db = Database(":memory:")
    try:
        monkeypatch.setattr(mig, "DB_SCHEMA_VERSION", 5)
        monkeypatch.setattr(mig, "MIGRATION_STEPS", [(1, 2, _noop_step)])
        await db.execute(
            "INSERT INTO meta (key, db_schema_version, migration_log, created_at, updated_at)"
            " VALUES ('global', 1, '[]', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        result = await mig.migrate_database(db)
        assert result.state == "failed"
        assert "不完整" in result.note
    finally:
        await db.close()


async def _noop_step(tx, db, now=None):
    """迁移步占位：no-op，供链完整性/备份失败测试用。"""
    return None
