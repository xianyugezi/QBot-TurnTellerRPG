"""存储层连接管理：单写连接队列 + 多只读连接池 + tx 事务上下文 + 建库。

依据：细化_4a_存储层契约 §1.4（连接与 PRAGMA：WAL/busy_timeout=5000/
synchronous=NORMAL/foreign_keys=ON/auto_vacuum=INCREMENTAL；单写连接 + 多只读
连接 D-02；数据文件 600 / 目录 700；aiosqlite 连接池上限 + 泄漏自检）、
§3.2 F3 事务模板（BEGIN IMMEDIATE → 业务写 → COMMIT，异常 ROLLBACK，禁止裸
connect 事务）、RW-6（启动 PRAGMA integrity_check）、SCHEMA-1（单库单写，
禁止多连接并发写）。

Class Database 职责：
  - 建库：首个写连接打开时执行 7 表 + 索引 DDL（schema.py）、套 PRAGMA。
  - 写：唯一写连接 + asyncio 互斥锁串行化（单写连接队列），tx() 为唯一写入口
    （BEGIN IMMEDIATE；出 with COMMIT / 异常 ROLLBACK，含 CancelledError）。
  - 读：WAL 多读，有界只读连接池（max_readers 上限），池满等待。
  - 健全性：启动 integrity_check；文件/目录权限 700/600；泄漏自检 pool_stats。
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sqlite3
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Tuple

import aiosqlite

from qbot_rpg.storage.schema import (
    PRAGMA_AUTO_VACUUM,
    PRAGMA_BUSY_TIMEOUT_MS,
    PRAGMA_FOREIGN_KEYS,
    PRAGMA_JOURNAL_MODE,
    PRAGMA_SYNCHRONOUS,
    SCHEMA_DDL,
)

DB_DIR_MODE: int = 0o700      # 【框架】L1154 / 【规则】L484：目录 700
DB_FILE_MODE: int = 0o600     # 数据文件 600

Row = Any  # sqlite3.Row 兼容别名（aiosqlite 行可下标、可 .keys()


class StorageError(Exception):
    """存储层基异常（引擎层抛领域异常的存储侧对应，4a TX-6 错误可恢复）。"""


class StorageIntegrityError(StorageError):
    """启动 integrity_check 失败（4a RW-6 / D-04）。"""


class StorageTransactionNestingError(StorageError):
    """检测到嵌套/交错事务（F3 禁止；单指令单事务 TX-1）。"""


class StoragePoolExhaustedError(StorageError):
    """只读连接池耗尽且等待超时（RC-5 连接池上限）。"""


class Transaction:
    """tx() 上下文内的事务句柄：绑定唯一写连接，暴露执行原语。

    只在 async with db.tx() as tx: 体内有效；出体后 is_active=False，
    继续调用抛 StorageError（防事务外残留使用）。
    """

    __slots__ = ("_db", "_conn", "_is_active")

    def __init__(self, db: "Database", conn: aiosqlite.Connection) -> None:
        self._db = db
        self._conn = conn
        self._is_active = True

    # -- 状态 ------------------------------------------------------------
    @property
    def is_active(self) -> bool:
        return self._is_active

    def _check(self) -> None:
        if not self._is_active:
            raise StorageError("Transaction 已 COMMIT/ROLLBACK，禁止继续使用")

    def _finalize(self) -> None:
        self._is_active = False

    # -- 执行原语（全部走唯一写连接，同事务） --------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> Any:
        self._check()
        cur = await self._conn.execute(sql, params)
        return await cur.close()

    async def executemany(self, sql: str, seq: Sequence[Sequence[Any]]) -> Any:
        self._check()
        cur = await self._conn.executemany(sql, seq)
        return await cur.close()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Row]:
        self._check()
        cur = await self._conn.execute(sql, params)
        try:
            return await cur.fetchone()
        finally:
            await cur.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        self._check()
        cur = await self._conn.execute(sql, params)
        try:
            return await cur.fetchall()
        finally:
            await cur.close()


class Database:
    """SQLite 存档库（WAL + 单写连接队列 + 多只读连接池）。

    path=":memory:" 时使用进程内共享缓存唯一库（多连接共享同一内存库），
    便于宿主内多连接/并发测试与临时库使用。
    """

    def __init__(
        self,
        path: str,
        *,
        max_readers: int = 8,
        read_pool_wait_timeout: float = 10.0,
        mkdir_mode: int = DB_DIR_MODE,
        file_mode: int = DB_FILE_MODE,
    ) -> None:
        if path == ":memory:" or path.startswith("file:"):
            self._path = path
            self._is_memory = True
            if path == ":memory:":
                # 共享缓存内存库：唯一名称，避免与其它 Database 实例冲突
                self._path = f"file:qbot_rpg_mem_{uuid.uuid4().hex}?mode=memory&cache=shared"
        else:
            self._path = path
            self._is_memory = False
            parent = os.path.dirname(os.path.abspath(path))
            if parent and not os.path.isdir(parent):
                os.makedirs(parent, mode=mkdir_mode, exist_ok=True)

        self._max_readers = max(1, max_readers)
        self._pool_wait_timeout = read_pool_wait_timeout
        self._file_mode = file_mode
        self._mkdir_mode = mkdir_mode

        self._write: Optional[aiosqlite.Connection] = None
        self._write_lock: asyncio.Lock = asyncio.Lock()
        self._create_lock: asyncio.Lock = asyncio.Lock()   # 首次建表防并发竞态
        self._schema_ready: bool = False                   # 7 表 + 索引已就位
        self._tx_owner: Optional[asyncio.Task] = None

        self._read_idle: List[aiosqlite.Connection] = []
        self._read_active: int = 0
        self._read_sem: asyncio.Semaphore = asyncio.Semaphore(self._max_readers)
        self._integrity_ok: Optional[bool] = None

    # ------------------------------------------------------------------
    # 路径与元信息
    # ------------------------------------------------------------------
    @property
    def path(self) -> str:
        return self._path

    @property
    def is_memory(self) -> bool:
        return self._is_memory

    @property
    def integrity_ok(self) -> Optional[bool]:
        return self._integrity_ok

    # ------------------------------------------------------------------
    # 连接生命期
    # ------------------------------------------------------------------
    async def _open(self, writer: bool = False) -> aiosqlite.Connection:
        conn = await aiosqlite.connect(
            self._path,
            uri=True,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row  # 行支持 keys() 与按列名下标
        # 连接参数（4a §1.4 写死）
        await conn.execute(f"PRAGMA journal_mode={PRAGMA_JOURNAL_MODE}")
        await conn.execute(f"PRAGMA busy_timeout={PRAGMA_BUSY_TIMEOUT_MS}")
        await conn.execute(f"PRAGMA synchronous={PRAGMA_SYNCHRONOUS}")
        await conn.execute(f"PRAGMA foreign_keys={PRAGMA_FOREIGN_KEYS}")
        if writer or self._write is None:
            # auto_vacuum 必须在建表前设置（INCREMENTAL，RC-5）
            await conn.execute(f"PRAGMA auto_vacuum={PRAGMA_AUTO_VACUUM}")
        if writer:
            # 建库：7 表 + 索引（SCHEMA-1 / §1.1）
            await conn.executescript(SCHEMA_DDL)
            if not self._is_memory:
                # 数据文件权限 600（目录 700 已由 makedirs 确保）
                fd_path = self._path
                if fd_path.startswith("file:"):
                    fd_path = fd_path.split("?", 1)[0].removeprefix("file:")
                with contextlib.suppress(OSError):
                    os.chmod(fd_path, self._file_mode)
        return conn

    async def _writer(self) -> aiosqlite.Connection:
        if self._write is None:
            async with self._create_lock:
                if self._write is None:      # 双检：首个协程建表，其余等待后复用
                    conn = await self._open(writer=True)
                    ok = await self._check_integrity(conn)
                    if not ok:
                        # 校验失败：关闭坏连接并保持 _write=None/_schema_ready=False，
                        # 使任何复用都重新触发完整建库+校验流程，杜绝「坏连接被静默复用」。
                        # 自动 .bak 回退 + round-trip 抽样为 4a RW-6 语义，已登记
                        # contract_deviations（前批 P1-3 递延项），本轮至少做状态重置（P1-2）。
                        await conn.close()
                        raise StorageIntegrityError(
                            f"存档库 integrity_check 失败: {self.path}（4a RW-6/D-04，"
                            "应回退最近 .bak 后重试，服务不崩）"
                        )
                    self._write = conn
                    self._schema_ready = True
                    self._integrity_ok = True
        return self._write

    @staticmethod
    async def _check_integrity(conn: aiosqlite.Connection) -> bool:
        cur = await conn.execute("PRAGMA integrity_check")
        try:
            row = await cur.fetchone()
            return bool(row) and str(row[0]) == "ok"
        finally:
            await cur.close()

    # ------------------------------------------------------------------
    # 只读连接池（WAL 多读，上限 + 泄漏自检）
    # ------------------------------------------------------------------
    @contextlib.asynccontextmanager
    async def _read_conn(self) -> AsyncIterator[aiosqlite.Connection]:
        if not self._schema_ready:
            # 只读路径也确保 schema 就位（防御：任何读都不得因空库 no such table）
            await self._writer()
        try:
            await asyncio.wait_for(self._read_sem.acquire(), timeout=self._pool_wait_timeout)
        except asyncio.TimeoutError:
            # 池耗尽由 wait_for(acquire, timeout) 兜底（P2-1：原死分支已删）
            raise StoragePoolExhaustedError(
                f"只读连接池耗尽（上限 {self._max_readers}）：{self.path}（RC-5）"
            ) from None
        # acquire 成功后，任何异常路径都必须归还令牌：
        # _open(writer=False) 失败（磁盘 I/O/PRAGMA 报错）也会进入下方 finally 归还，
        # 池容量不永久缩水（P1-1：原实现在 _open 失败路径泄漏信号量）
        conn: Optional[aiosqlite.Connection] = None
        try:
            if self._read_idle:
                conn = self._read_idle.pop()
            else:
                conn = await self._open(writer=False)
            self._read_active += 1
            try:
                yield conn
            finally:
                self._read_active -= 1
                self._read_idle.append(conn)
        finally:
            self._read_sem.release()

    async def _fetch_on_read(self, sql: str, params: Sequence[Any]) -> List[Row]:
        async with self._read_conn() as conn:
            cur = await conn.execute(sql, params)
            try:
                rows = await cur.fetchall()
            finally:
                await cur.close()
            return rows

    async def fetchone_read(self, sql: str, params: Sequence[Any] = ()) -> Optional[Row]:
        rows = await self._fetch_on_read(sql, params)
        return rows[0] if rows else None

    async def fetchall_read(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        return await self._fetch_on_read(sql, params)

    # ------------------------------------------------------------------
    # 单语句管理执行（写连接自动提交，仅限管理/迁移用；业务写一律走 tx()）
    # ------------------------------------------------------------------
    async def execute(self, sql: str, params: Sequence[Any] = ()) -> None:
        conn = await self._writer()
        async with self._write_lock:
            cur = await conn.execute(sql, params)
            await cur.close()

    async def fetchone(self, sql: str, params: Sequence[Any] = ()) -> Optional[Row]:
        conn = await self._writer()
        async with self._write_lock:
            cur = await conn.execute(sql, params)
            try:
                return await cur.fetchone()
            finally:
                await cur.close()

    async def fetchall(self, sql: str, params: Sequence[Any] = ()) -> List[Row]:
        conn = await self._writer()
        async with self._write_lock:
            cur = await conn.execute(sql, params)
            try:
                return await cur.fetchall()
            finally:
                await cur.close()

    async def vacuum_into(self, target_path: str) -> None:
        """VACUUM INTO 备份快照（RW-5 / D-04：备份不动主库）。内存库不支持。"""
        if self._is_memory:
            raise StorageError("内存库不支持 VACUUM INTO 备份")
        conn = await self._writer()
        async with self._write_lock:
            cur = await conn.execute("VACUUM INTO ?", (target_path,))
            await cur.close()
        if target_path != ":memory:" and not target_path.startswith("file:"):
            with contextlib.suppress(OSError):
                os.chmod(target_path, self._file_mode)

    # ------------------------------------------------------------------
    # tx()：单事务模板（4a §3.2 F3，唯一业务写入口）
    # ------------------------------------------------------------------
    @contextlib.asynccontextmanager
    async def tx(self) -> AsyncIterator[Transaction]:
        conn = await self._writer()
        task = asyncio.current_task()
        if self._tx_owner is task and task is not None:
            # 仅拒绝「同一任务内嵌套 tx」（asyncio.Lock 不可重入，放行会卡死）。
            # 不同任务并发事务由 _write_lock 排队（4a TX-4/TC-18 单写队列串行化），
            # 不得误判为嵌套拒之门外。
            raise StorageTransactionNestingError("检测到同任务嵌套 tx（F3 单指令单事务）")
        async with self._write_lock:
            prev_owner = self._tx_owner
            self._tx_owner = task
            try:
                await conn.execute("BEGIN IMMEDIATE")
            except BaseException:
                self._tx_owner = prev_owner
                raise
            tr = Transaction(self, conn)
            try:
                yield tr
            except BaseException:
                # 任一步抛异常 → ROLLBACK（无半写状态，TX-2/TC-01~04）
                with contextlib.suppress(BaseException):
                    await conn.execute("ROLLBACK")
                tr._finalize()
                self._tx_owner = prev_owner
                raise
            else:
                try:
                    await conn.execute("COMMIT")
                except BaseException:
                    with contextlib.suppress(BaseException):
                        await conn.execute("ROLLBACK")
                    tr._finalize()
                    self._tx_owner = prev_owner
                    raise
                tr._finalize()
                self._tx_owner = prev_owner

    # ------------------------------------------------------------------
    # 连接池统计与泄漏自检（RC-5）
    # ------------------------------------------------------------------
    def pool_stats(self) -> Dict[str, int]:
        """连接池快照：{write_open, read_idle, read_active, read_cap}。"""
        return {
            "write_open": 1 if self._write is not None else 0,
            "read_idle": len(self._read_idle),
            "read_active": self._read_active,
            "read_cap": self._max_readers,
        }

    def leak_check(self) -> List[str]:
        """泄漏自检：返回未归还的只读连接清单（空 = 无泄漏）。"""
        leaks = []
        if self._read_active > 0:
            leaks.append(f"read_active={self._read_active}（有连接未归还，RC-5 泄漏自检）")
        return leaks

    async def close(self) -> None:
        """释放全部连接。内存库在全部连接关闭后自动销毁。"""
        leaks = self.leak_check()
        if leaks:
            raise StorageError("关闭前检测到连接泄漏: " + "; ".join(leaks))
        for conn in self._read_idle:
            await conn.close()
        self._read_idle.clear()
        if self._write is not None:
            await self._write.close()
            self._write = None

    async def __aenter__(self) -> "Database":
        await self._writer()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()
