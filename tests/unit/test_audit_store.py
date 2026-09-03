"""GM 审计存储层单测（M12 编辑器里程碑·批2·路2C · qbot_rpg/content/audit_store.py）。

依据：docs/细化/细化_5b_GM指令契约.md §4 审计：
  - §4.1 事件类 E1-E6（L227-234）：E1 内容操作 / E2 数据导出 / E3 广播 /
    E4 封禁闭环 / E5 权限变更 / E6 系统事件；
  - §4.2 记录字段（L239-250）：id UUID / ts / qq / group_id（私聊=0）/ command /
    params 截断 200 / target_qq / result 三态 / detail / ref / audit_ts_hmac；
  - §4.3 L260 不可删（类不提供 delete/clear）、L261 轮转（保留最新 N 份）。

口径：AuditStore 为纯逻辑层（零 NoneBot、SQLite 鸭子 conn）；本测试按 2B 路并入
schema.py 之前的独立自建表口径驱动——:memory: sqlite3 + store.ensure_table 建表
（两路 DDL 同口径，IF NOT EXISTS 幂等，2B 落盘后断言不破）。
"""

from __future__ import annotations

import sqlite3

import pytest

from qbot_rpg.content.audit_store import (
    AUDIT_COLUMNS,
    DEFAULT_LIST_LIMIT,
    EVENT_E1,
    EVENT_E2,
    EVENT_E3,
    EVENT_E4,
    EVENT_E5,
    EVENT_E6,
    PARAMS_MAX_LEN,
    RESULT_ALLOWED,
    AuditStore,
    classify,
)

TS = "2026-09-03T12:00:00Z"  # 用例统一时间戳（ts 由调用方注入，确定性）


@pytest.fixture()
def conn() -> sqlite3.Connection:
    """:memory: 连接 + AuditStore 自建 audit_log 表（每用例独立，幂等原则）。"""
    c = sqlite3.connect(":memory:")
    AuditStore().ensure_table(c)
    return c


def _append(store: AuditStore, c: sqlite3.Connection, *, i: int = 0,
            qq: str = "10001", command: str = "重载",
            result: str = "success", **kw: object) -> str:
    """辅助追加：按 i 生成确定性的 ts / params / detail，简化多行场景构造。"""
    return store.append(
        c,
        ts=f"2026-09-03T12:{i // 60:02d}:{i % 60:02d}Z",
        qq=qq,
        group_id="20001",
        command=command,
        params=f"内容包X-{i}",
        target_qq=None,
        result=result,
        detail=f"摘要-{i}",
        ref=None,
        **kw,
    )


# ---------------------------------------------------------------------------
# ensure_table / append：追加写成功（§4.2 字段全 + id 非空）
# ---------------------------------------------------------------------------


class TestAppend:
    def test_ensure_table_idempotent(self, conn: sqlite3.Connection) -> None:
        """ensure_table 幂等：重复执行不报错（IF NOT EXISTS；两路 DDL 同口径不冲突）。"""
        store = AuditStore()
        store.ensure_table(conn)  # 第二次执行
        store.ensure_table(conn)  # 第三次执行

    def test_append_full_fields_and_uuid_id(self, conn: sqlite3.Connection) -> None:
        """追加写成功：全字段落库 + 返回 id 非空 UUID 形态（§4.2 L239-250）。"""
        store = AuditStore()
        row_id = store.append(
            conn,
            ts=TS,
            qq="10001",
            group_id="20001",
            command="重载",
            params="内容包X",
            target_qq="",
            result="success",
            detail="✅ 已重载【内容包X】：技能 12 条",
            ref="backup_20260903.zip",
            audit_ts_hmac="a" * 64,
        )
        assert row_id and len(row_id) == 32  # uuid4().hex：32 位十六进制
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        assert len(rows) == 1
        row = dict(zip(AUDIT_COLUMNS, rows[0]))
        assert row["id"] == row_id
        assert row["ts"] == TS
        assert row["qq"] == "10001"
        assert row["group_id"] == "20001"
        assert row["command"] == "重载"
        assert row["params"] == "内容包X"
        assert row["target_qq"] == ""   # 显式传空串 → 原文存储
        assert row["result"] == "success"
        assert row["detail"] == "✅ 已重载【内容包X】：技能 12 条"
        assert row["ref"] == "backup_20260903.zip"
        assert row["audit_ts_hmac"] == "a" * 64

    def test_append_defaults_system_and_private(self, conn: sqlite3.Connection) -> None:
        """E6 无操作者（qq 缺省=系统）+ 私聊 group_id=0（§4.2 L242-243）。"""
        row_id = AuditStore().append(
            conn, ts=TS, command="system", result="failed", detail="备份失败"
        )
        row = dict(zip(AUDIT_COLUMNS, conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (row_id,)).fetchone()))
        assert row["qq"] == ""          # E6 无操作者 = 系统
        assert row["group_id"] == "0"   # 私聊=0
        assert row["target_qq"] is None
        assert row["ref"] is None
        assert row["params"] == ""
        assert row["audit_ts_hmac"] == ""

    def test_append_multiple_rows(self, conn: sqlite3.Connection) -> None:
        """多次追加写互不覆盖（追加语义）；id 唯一。"""
        store = AuditStore()
        ids = [_append(store, conn, i=i) for i in range(5)]
        assert len(set(ids)) == 5
        assert store.count(conn) == 5

    def test_append_params_truncated_at_200(self, conn: sqlite3.Connection) -> None:
        """params 超 200 字截断：前 200 字 + "…"，总长 201（§4.2 L245 防爆）。"""
        row_id = AuditStore().append(
            conn, ts=TS, command="封禁", result="success",
            params="原" * 500, target_qq="123456",
        )
        row = dict(zip(AUDIT_COLUMNS, conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (row_id,)).fetchone()))
        assert len(row["params"]) == PARAMS_MAX_LEN + 1
        assert row["params"][:PARAMS_MAX_LEN] == "原" * PARAMS_MAX_LEN
        assert row["params"].endswith("…")

    def test_append_params_exact_200_no_truncate(self, conn: sqlite3.Connection) -> None:
        """params 恰好 200 字不截断（边界不误伤）。"""
        row_id = AuditStore().append(
            conn, ts=TS, command="重载", result="success", params="x" * 200,
        )
        row = dict(zip(AUDIT_COLUMNS, conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (row_id,)).fetchone()))
        assert row["params"] == "x" * 200

    @pytest.mark.parametrize("bad", ["ok", "SUCCESS", "denied", ""])
    def test_append_rejects_invalid_result(self, conn: sqlite3.Connection,
                                           bad: str) -> None:
        """result 非法值逻辑拒绝（ValueError；DDL CHECK 为第二道保险，§4.2 L247）。"""
        store = AuditStore()
        with pytest.raises(ValueError):
            store.append(conn, ts=TS, command="重载", result=bad)

    @pytest.mark.parametrize("ok", ["success", "failed", "rejected"])
    def test_append_accepts_all_three_results(self, conn: sqlite3.Connection,
                                              ok: str) -> None:
        """result 三态全收（成败皆写 L253：success/failed/rejected 都落库）。"""
        store = AuditStore()
        assert ok in RESULT_ALLOWED
        row_id = store.append(conn, ts=TS, command="重载", result=ok)
        row = dict(zip(AUDIT_COLUMNS, conn.execute(
            "SELECT * FROM audit_log WHERE id = ?", (row_id,)).fetchone()))
        assert row["result"] == ok


# ---------------------------------------------------------------------------
# list_recent：/日志 展示源（倒序 ts 新→旧；可选 command/qq 过滤；limit 上限）
# ---------------------------------------------------------------------------


class TestListRecent:
    def test_list_recent_desc_order(self, conn: sqlite3.Connection) -> None:
        """倒序：最新（ts 最大）在前；limit 生效截断。"""
        store = AuditStore()
        for i in range(10):
            _append(store, conn, i=i)
        rows = store.list_recent(conn, limit=3)
        assert [r["detail"] for r in rows] == ["摘要-9", "摘要-8", "摘要-7"]
        assert [r["ts"] for r in rows] == sorted(
            (r["ts"] for r in rows), reverse=True)

    def test_list_recent_all_columns(self, conn: sqlite3.Connection) -> None:
        """行 dict 键 = 12 列全字段（§4.2 展示源字段完整，含 target_qq/ref/hmac）。"""
        _append(store := AuditStore(), conn, i=0)
        row = store.list_recent(conn, limit=1)[0]
        assert list(row.keys()) == list(AUDIT_COLUMNS)

    def test_list_recent_filter_command(self, conn: sqlite3.Connection) -> None:
        """command 过滤：只返回该指令的记录。"""
        store = AuditStore()
        for i in range(3):
            _append(store, conn, i=i, command="重载")
        for i in range(2):
            _append(store, conn, i=i + 10, command="封禁")
        rows = store.list_recent(conn, limit=50, command="封禁")
        assert len(rows) == 2
        assert all(r["command"] == "封禁" for r in rows)
        rows = store.list_recent(conn, limit=50, command="重载")
        assert len(rows) == 3

    def test_list_recent_filter_qq(self, conn: sqlite3.Connection) -> None:
        """qq 过滤：只返回该操作者的记录。"""
        store = AuditStore()
        for i in range(3):
            _append(store, conn, i=i, qq="10001")
        _append(store, conn, i=5, qq="10002")
        rows = store.list_recent(conn, limit=50, qq="10002")
        assert len(rows) == 1 and rows[0]["qq"] == "10002"
        rows = store.list_recent(conn, limit=50, qq="10001")
        assert len(rows) == 3

    def test_list_recent_combined_filters(self, conn: sqlite3.Connection) -> None:
        """command + qq 组合过滤（AND 语义）。"""
        store = AuditStore()
        _append(store, conn, i=1, qq="10001", command="重载")
        _append(store, conn, i=2, qq="10001", command="封禁")
        _append(store, conn, i=3, qq="10002", command="重载")
        rows = store.list_recent(conn, limit=50, command="重载", qq="10001")
        assert len(rows) == 1 and rows[0]["detail"] == "摘要-1"

    def test_list_recent_empty_and_zero_limit(self, conn: sqlite3.Connection) -> None:
        """空表 → []；limit<=0 → []（不查库直接返回）。"""
        store = AuditStore()
        assert store.list_recent(conn) == []
        assert store.list_recent(conn, limit=0) == []
        assert store.list_recent(conn, limit=-5) == []

    def test_list_recent_default_limit(self, conn: sqlite3.Connection) -> None:
        """默认 limit = 50（DEFAULT_LIST_LIMIT，/日志 上限口径）。"""
        assert DEFAULT_LIST_LIMIT == 50
        store = AuditStore()
        for i in range(60):
            _append(store, conn, i=i)
        assert len(store.list_recent(conn)) == DEFAULT_LIST_LIMIT
        assert len(store.list_recent(conn, limit=200)) == 60  # 显式放大不截


# ---------------------------------------------------------------------------
# count / rotate：轮转（§4.3 L261 保留最新 N 份；keep_n<=0 不轮转）
# ---------------------------------------------------------------------------


class TestRotate:
    def test_rotate_keeps_newest_n(self, conn: sqlite3.Connection) -> None:
        """轮转保留最新 keep_n 条，按 ts 删最旧；返回删除行数。"""
        store = AuditStore()
        for i in range(10):
            _append(store, conn, i=i)
        deleted = store.rotate(conn, keep_n=3)
        assert deleted == 7
        assert store.count(conn) == 3
        rows = store.list_recent(conn, limit=50)
        assert [r["detail"] for r in rows] == ["摘要-9", "摘要-8", "摘要-7"]

    def test_rotate_keep_n_equal_count_no_delete(self, conn: sqlite3.Connection) -> None:
        """keep_n >= 总行数 → 不删任何行（保留全部）。"""
        store = AuditStore()
        for i in range(5):
            _append(store, conn, i=i)
        assert store.rotate(conn, keep_n=5) == 0
        assert store.count(conn) == 5
        assert store.rotate(conn, keep_n=99) == 0
        assert store.count(conn) == 5

    def test_rotate_zero_or_negative_disabled(self, conn: sqlite3.Connection) -> None:
        """keep_n <= 0 → 不轮转（返回 0，调用方显式关闭轮转口径）。"""
        store = AuditStore()
        for i in range(3):
            _append(store, conn, i=i)
        assert store.rotate(conn, keep_n=0) == 0
        assert store.rotate(conn, keep_n=-1) == 0
        assert store.count(conn) == 3

    def test_rotate_empty_table(self, conn: sqlite3.Connection) -> None:
        """空表轮转：不报错返回 0。"""
        assert AuditStore().rotate(conn, keep_n=3) == 0
        assert AuditStore().count(conn) == 0


# ---------------------------------------------------------------------------
# 事件分类（§4.1 L227-234：E1-E6 映射）
# ---------------------------------------------------------------------------


class TestClassify:
    @pytest.mark.parametrize(
        ("command", "expected"),
        [
            ("reload", EVENT_E1),
            ("backup", EVENT_E1),
            ("restore", EVENT_E1),
            ("重载", EVENT_E1),
            ("备份", EVENT_E1),
            ("恢复", EVENT_E1),
            ("export", EVENT_E2),
            ("存档导出", EVENT_E2),
            ("broadcast", EVENT_E3),
            ("广播", EVENT_E3),
            ("ban", EVENT_E4),
            ("unban", EVENT_E4),
            ("封禁", EVENT_E4),
            ("解封", EVENT_E4),
            ("grant", EVENT_E5),
            ("revoke", EVENT_E5),
            ("授权", EVENT_E5),
            ("撤销", EVENT_E5),
            ("system", EVENT_E6),
            ("kick", EVENT_E6),
            ("磁盘预警", EVENT_E6),
            ("未知指令xyz", EVENT_E6),  # 未命中兜底 E6（系统事件口径）
            ("", EVENT_E6),            # 空指令兜底 E6
            ("/重载", EVENT_E1),        # 前导 / 剥离后归一（GM 指令裸名口径）
        ],
    )
    def test_classify_mapping(self, command: str, expected: str) -> None:
        """E1-E6 关键词映射全表（中英文指令名 + 前导 / + 兜底）。"""
        assert classify(command) == expected


# ---------------------------------------------------------------------------
# 不可删语义（§4.3 L260：任何 GM 指令不可删审计表；类不提供删除入口）
# ---------------------------------------------------------------------------


class TestNoDeleteApi:
    def test_no_delete_or_clear_method(self) -> None:
        """AuditStore 无 delete/clear/truncate/drop 方法（代码层不可删契约 L260）。"""
        public = {name for name in dir(AuditStore) if not name.startswith("_")}
        assert not {"delete", "clear", "truncate", "drop"} & public
        # 明确列出的允许面（防未来误加删除入口时的回归哨兵）
        assert {"ensure_table", "append", "list_recent", "count", "rotate"} <= public

    def test_no_sql_delete_reachable_via_api(self, conn: sqlite3.Connection) -> None:
        """追加写只增不减：删除只能经 rotate（轮转 L261 唯一删除通道）。"""
        store = AuditStore()
        for i in range(4):
            _append(store, conn, i=i)
        # 直接 SQL 删除是被禁止的（轮转外无删除通道）；此处仅佐证 API 面不含删除
        assert store.count(conn) == 4
        assert store.list_recent(conn, limit=50)[0]["detail"] == "摘要-3"
