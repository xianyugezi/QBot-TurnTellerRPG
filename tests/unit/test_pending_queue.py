"""PendingQueue 单测承载（M6 批5 · D5 P2-1 补建 + P1-1 OperationalError 补测）。

依据：
  - 细化_M6_故障注入（D5）FLT-14/15/17（.pending 暂存队列：追加写/坏行跳过/重放保留）
    + 批5A 审查 P2-1（FLT-16「单元用例双承载」单测半边缺失 → 本文件补）+ P2-2
    （row_payload 完整性校验）+ P1-1（真实磁盘满 OperationalError 非 OSError）
  - qbot_rpg/storage/pending.py（PendingQueue/PendingEntry/SAVE_FAILURE_MESSAGE）
"""

from __future__ import annotations

import sqlite3

import pytest

from qbot_rpg.storage.connection import Database, StorageError
from qbot_rpg.storage.pending import (
    ACTION_PLAYER_UPSERT,
    PENDING_FILENAME,
    SAVE_FAILURE_MESSAGE,
    PendingEntry,
    PendingQueue,
)
from qbot_rpg.storage.repository import Repository

from conftest import make_player


def _entry(qid: str = "10001", payload: dict | None = None, action: str = ACTION_PLAYER_UPSERT) -> PendingEntry:
    return PendingEntry(
        player_qid=qid,
        action=action,
        row_payload=payload if payload is not None else {"player_qid": qid, "nickname": "阿伟", "level": 35},
        created_at="2026-08-27T12:00:00Z",
    )


def test_pending_entry_roundtrip():
    """PendingEntry 序列化往返一致（F-01~04 字段保留）。"""
    e = _entry()
    parsed = PendingEntry.from_line(e.to_line())
    assert parsed.player_qid == e.player_qid
    assert parsed.action == e.action
    assert parsed.row_payload == e.row_payload
    assert parsed.created_at == e.created_at


@pytest.mark.asyncio
async def test_pending_queue_append_read_clear(tmp_path):
    """追加写 → read_all 全读 → clear 清空（FLT-14/15）。"""
    q = PendingQueue(tmp_path)
    await q.append(_entry("10001"))
    await q.append(_entry("10002", payload={"player_qid": "10002", "nickname": "阿武", "level": 3}))
    entries = await q.read_all()
    assert [e.player_qid for e in entries] == ["10001", "10002"]
    assert await q.count() == 2
    await q.clear()
    assert await q.read_all() == []


@pytest.mark.asyncio
async def test_pending_queue_bad_line_skipped_not_lost(tmp_path):
    """坏行跳过且保留原文件（FLT-14：坏行不丢待人工审计）。"""
    q = PendingQueue(tmp_path)
    await q.append(_entry("10001"))
    q._path.write_text(q._path.read_text(encoding="utf-8") + "{broken json\n", encoding="utf-8")
    entries = await q.read_all()  # 不抛错
    assert [e.player_qid for e in entries] == ["10001"]  # 好行仍读；坏行跳过


@pytest.mark.asyncio
async def test_pending_queue_missing_payload_skipped(tmp_path):
    """P2-2：残缺 row_payload（非 dict/无 player_qid）跳过——防重放默认值覆盖真实玩家。"""
    q = PendingQueue(tmp_path)
    await q.append(_entry("10001"))
    await q.append(PendingEntry(player_qid="10002", action=ACTION_PLAYER_UPSERT,
                          row_payload={}, created_at="2026-08-27T12:00:00Z"))  # 残缺 payload
    await q.append(PendingEntry(player_qid="10003", action=ACTION_PLAYER_UPSERT,
                          row_payload={"nickname": "无 qid"}, created_at="2026-08-27T12:00:00Z"))  # 缺 qid
    entries = await q.read_all()
    assert [e.player_qid for e in entries] == ["10001"]  # 两条残缺都跳过


@pytest.mark.asyncio
async def test_save_player_catches_operational_error(tmp_path):
    """P1-1 补测：真实磁盘满抛 sqlite3.OperationalError（非 OSError）→ .pending 转写 + 人话。"""
    db = Database(str(tmp_path / "t.db"))
    repo = Repository(db, pending_dir=str(tmp_path))
    await repo.save_player(make_player("20001"))

    async def boom_commit(conn) -> None:  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("database or disk is full")

    repo.db._commit = boom_commit  # 注入接缝：实例遮蔽
    with pytest.raises(StorageError) as ei:
        await repo.save_player(make_player("10001"))
    assert SAVE_FAILURE_MESSAGE in str(ei.value)
    assert (tmp_path / PENDING_FILENAME).exists()
    assert repo.pending is not None
    entries = await repo.pending.read_all()
    assert len(entries) == 1 and entries[0].player_qid == "10001"
    await repo.close()


@pytest.mark.asyncio
async def test_replay_success_clears_and_keeps_new_appends(tmp_path):
    """P1-1/FLT-15：重放成功 → .replay 删除；重放后新 append 落原文件不受影响（窗口隔离）。"""
    db = Database(str(tmp_path / "t.db"))
    repo = Repository(db, pending_dir=str(tmp_path))
    await repo.save_player(make_player("20001"))
    orig_commit = repo.db._commit  # 保存原方法（恢复用，勿置 None——会破坏生产路径）

    async def boom_commit(conn) -> None:  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("database or disk is full")

    repo.db._commit = boom_commit
    try:
        with pytest.raises(StorageError):
            await repo.save_player(make_player("10001"))
    finally:
        repo.db._commit = orig_commit

    # 重放（恢复原 commit）
    n = await repo.replay_pending()
    assert n == 1
    assert not (tmp_path / ".pending.jsonl.replay").exists()  # .replay 已删
    assert await repo.load_player("10001") is not None       # 已回主库
    # 重放后新 append 原文件（隔离窗口语义：新条目不受 .replay 清理影响）
    repo.db._commit = boom_commit
    try:
        with pytest.raises(StorageError):
            await repo.save_player(make_player("10003"))
    finally:
        repo.db._commit = orig_commit
    assert (tmp_path / ".pending.jsonl").exists()
    entries = await repo.pending.read_all()
    assert [e.player_qid for e in entries] == ["10003"]  # 只剩新条目
    await repo.close()


@pytest.mark.asyncio
async def test_replay_failure_keeps_replay_file(tmp_path):
    """FLT-15 负路径：重放事务失败 → 返回 0 + .replay 保留（条目不丢）。"""
    db = Database(str(tmp_path / "t.db"))
    repo = Repository(db, pending_dir=str(tmp_path))
    await repo.save_player(make_player("20001"))
    q = repo.pending
    assert q is not None
    await q.append(PendingEntry(player_qid="10001", action=ACTION_PLAYER_UPSERT,
                                row_payload={"player_qid": "10001", "nickname": "X", "level": 1},
                                created_at="2026-08-27T12:00:00Z"))
    # 注入重放失败：_apply_pending_entry 抛错（模拟主库仍不可写）
    async def boom_apply(tx, entry):  # type: ignore[no-untyped-def]
        raise sqlite3.OperationalError("database or disk is full")

    repo._apply_pending_entry = boom_apply  # 实例遮蔽
    n = await repo.replay_pending()
    assert n == 0
    assert (tmp_path / ".pending.jsonl.replay").exists()  # 条目不丢
    assert not (tmp_path / ".pending.jsonl").exists()     # 已切分（原文件为空）
    await repo.close()
