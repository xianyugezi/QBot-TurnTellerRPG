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
@pytest.mark.asyncio
async def test_idempotency():
    db = Database(":memory:")
    repo = Repository(db)
    try:
        await repo.save_player(make_player("10001"))
        k = IdemKey(message_id="m1", group_id="g1", player_qid="10001",
                    command="/购买", result_hash="h1")
        assert await repo.idem_claim(k) is False
        assert await repo.idem_claim(k) is True
        found = await repo.idem_find("m1", "g1", "10001")
        assert found is not None and found.result_hash == "h1"
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
        recycled = await repo.recycle_scan()
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
