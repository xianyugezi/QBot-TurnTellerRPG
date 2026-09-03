"""GM 审计存储层 audit_store.py（M12 编辑器里程碑·批2·路2C · qbot_rpg/content/audit_store.py）。

依据：docs/细化/细化_5b_GM指令契约.md §4 审计（L223-264）：
  - §4.1 事件类 E1-E6（L227-234）：E1 内容操作（重载/备份/恢复）/ E2 数据导出 /
    E3 广播 / E4 封禁闭环 / E5 权限变更 / E6 系统事件；
  - §4.2 记录字段（L239-250）：audit_log 追加写 11 字段（id UUID / ts 服务端时间戳 /
    qq 操作者（E6 无操作者=系统）/ group_id（私聊=0）/ command / params 参数摘要
    （截断 200 字）/ target_qq / result（success|failed|rejected）/ detail / ref /
    audit_ts_hmac 审计行校验值）+ L253-254（成败皆写、result 区分；/日志（GM 版）
    展示源 = 本表）；
  - §4.3 生命周期与安全约束（L256-264）：L260 不可删（任何 GM 指令（含机主）
    不可删除/清空审计表，清理仅编辑器运维页手动操作）；L261 轮转（大小+保留份数，
    默认保留 N 份，随磁盘水位预警联动）；L263 幂等（审计写入与业务写入同事务）；
    L264 展示（GM /日志 展示本表，普通玩家永远看不到）。

对齐：qbot_rpg/commands/gm_commands.py 留痕语义（gm_commands L381-406 build_audit_record）：
  - params 截断口径一致：>200 字 → 前 200 字 + "…"（gm L389-390）；
  - result 三态 success|failed|rejected（gm L399）→ 本层逻辑校验 + DDL CHECK 双保险；
  - group_id 私聊=0（gm L395）；
  - id = uuid4().hex（gm L392）；
  - audit_ts_hmac：由调用方（gm.audit_hmac L365-378 / 批 3 接线）先行计算后传入，
    本层仅存储不校验（开关由批 3 接线时定）；默认空串 = 校验值未启用。

约束：
  - **零 NoneBot import**、纯逻辑 + SQLite 鸭子 conn（同步 sqlite3.Connection 协议，
    连接/事务由调用方提供——幂等契约 L263 要求审计写入与业务写入同事务，故本层
    方法一律显式收 conn 不持有连接）；
  - 不 import qbot_rpg/storage/schema.py：audit_log + admin_users 两张表的建表 SQL
    由 2B 路并入 storage/schema.py（schema.py 2B 独占）；本文件自带同口径 DDL 常量
    （CREATE TABLE IF NOT EXISTS 幂等——两路 DDL 相同，先执行者建表后执行者跳过，
    不冲突），保证本层可脱离 2B 独立单测（:memory: 自建表）；
  - 本文件只承载 audit_log 一张表（admin_users 归 2B 路权限存储，不属审计存储）。

不可删语义（L260）：本类**不提供** delete/clear/truncate 等任何删除方法——代码层
无审计表删除入口；清理仅编辑器运维页手动操作（GM 指令不可删审计表，审计可信前提）。
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, Final, List, Mapping, Sequence, Tuple

# ---------------------------------------------------------------------------
# 表与列常量（5b §4.2 L239-250 字段级；DDL 与 2B 路并入 schema.py 的口径一致，
# 本文件副本仅供本层独立自建表单测/脱离 2B 使用；IF NOT EXISTS 幂等不冲突）
# ---------------------------------------------------------------------------

AUDIT_TABLE: Final[str] = "audit_log"

# 记录字段顺序（L240-250；list_recent 行 → dict 的列名唯一来源）
AUDIT_COLUMNS: Final[Tuple[str, ...]] = (
    "id",
    "ts",
    "qq",
    "group_id",
    "command",
    "params",
    "target_qq",
    "result",
    "detail",
    "ref",
    "audit_ts_hmac",
)

# result 三态（L247；逻辑校验 + DDL CHECK 双保险）
RESULT_ALLOWED: Final[Tuple[str, ...]] = ("success", "failed", "rejected")

# params 参数摘要截断上限（L245：截断 200 字；对齐 gm_commands L389-390 前 200 字 + "…"）
PARAMS_MAX_LEN: Final[int] = 200

# list_recent 默认展示条数（L254 /日志 展示源；gm LOG_MAX_ENTRIES=50 由调用方限）
DEFAULT_LIST_LIMIT: Final[int] = 50

CREATE_TABLE_AUDIT_LOG: Final[str] = """\
CREATE TABLE IF NOT EXISTS audit_log (
    id            TEXT PRIMARY KEY,
    ts            TEXT NOT NULL,
    qq            TEXT,
    group_id      TEXT,
    command       TEXT NOT NULL,
    params        TEXT NOT NULL DEFAULT '',
    target_qq     TEXT,
    result        TEXT NOT NULL CHECK (result IN ('success','failed','rejected')),
    detail        TEXT NOT NULL DEFAULT '',
    ref           TEXT,
    audit_ts_hmac TEXT
)
"""

# ---------------------------------------------------------------------------
# 审计事件类（5b §4.1 L227-234：E1 内容操作 / E2 数据导出 / E3 广播 /
# E4 封禁闭环 / E5 权限变更 / E6 系统事件）
# ---------------------------------------------------------------------------

EVENT_E1: Final[str] = "E1"   # 内容操作：重载 / 备份 / 恢复（G1-G3，L229）
EVENT_E2: Final[str] = "E2"   # 数据导出：存档导出（G4，L230）
EVENT_E3: Final[str] = "E3"   # 广播（G7，L231）
EVENT_E4: Final[str] = "E4"   # 封禁闭环：封禁 / 解封（G10/G11，L232）
EVENT_E5: Final[str] = "E5"   # 权限变更：授予/撤销 GM、per-command 授权调整（L233）
EVENT_E6: Final[str] = "E6"   # 系统事件：踢群/磁盘预警/封禁提示/备份失败（L234）

# command → 事件类映射关键词（规范化后匹配：小写、去前导 /；中英文指令名/事件名
# 双覆盖；未命中 → E6 系统事件兜底——E6 语义即「系统侧/未分类事件名」）
_EVENT_KEYWORDS: Final[Mapping[str, Tuple[str, ...]]] = {
    EVENT_E1: ("reload", "backup", "restore", "重载", "备份", "恢复"),
    EVENT_E2: ("export", "导出", "存档导出"),
    EVENT_E3: ("broadcast", "广播"),
    EVENT_E4: ("ban", "unban", "封禁", "解封"),
    EVENT_E5: ("grant", "revoke", "granted", "授权", "授予", "撤销", "下授"),
    EVENT_E6: ("system", "系统", "kick", "踢群"),
}


def classify(command: Any) -> str:
    """审计事件分类（5b §4.1 L227-234）：command → E1-E6。

    规范化（小写 + 去前导 / + 去首尾空白）后按 _EVENT_KEYWORDS 精确匹配；
    未命中/空 → E6（系统事件兜底，L234 事件名/摘要口径）。
    """
    name = str(command or "").strip().lstrip("/").lower()
    for event, keywords in _EVENT_KEYWORDS.items():
        if name in keywords:
            return event
    return EVENT_E6


# ---------------------------------------------------------------------------
# AuditStore：审计日志存储逻辑层（追加写不可删；无 delete/clear/truncate 方法）
# ---------------------------------------------------------------------------


class AuditStore:
    """GM 审计日志存储（5b §4：追加写、不可删、轮转、/日志 展示源）。

    纯逻辑层：所有方法显式收 SQLite 鸭子 conn（同步 sqlite3.Connection 协议），
    不持有连接、不开事务——连接与事务（含与业务写入同事务的幂等口径 L263）由
    调用方（装配层/批 3 接线）提供与编排。

    不可删（L260）：本类只有 append/list_recent/count/rotate 四个操作，**没有**
    delete/clear/truncate 方法；审计表清理仅编辑器运维页手动操作。
    """

    def ensure_table(self, conn: Any) -> None:
        """建表（幂等）：CREATE TABLE IF NOT EXISTS audit_log。

        与 2B 路并入 storage/schema.py 的 DDL 同口径（列集/约束一致），
        双执行因 IF NOT EXISTS 幂等不冲突（schema.py 2B 独占，本文件不改它）。
        """
        conn.execute(CREATE_TABLE_AUDIT_LOG)

    def append(
        self,
        conn: Any,
        *,
        ts: str,
        command: str,
        result: str,
        qq: Any = "",
        group_id: Any = "0",
        params: Any = "",
        target_qq: Any = None,
        detail: Any = "",
        ref: Any = None,
        audit_ts_hmac: Any = "",
    ) -> str:
        """追加写一条审计记录（L239 追加写 / L253 成败皆写），返回记录 id。

        - ts/command/result 必填（keyword-only）；ts = 服务端 ISO-8601 UTC 字符串
          （确定性由调用方保证，对齐 gm_commands now 注入口径）；
        - qq = 操作者 QQ（E6 无操作者 → 传 "" = 系统）；group_id 私聊默认 "0"（L243）；
        - params 截断：>200 字 → 前 200 字 + "…"（L245，防参数摘要撑爆）；
        - result 非法值（非 success|failed|rejected）→ ValueError 逻辑拒绝
          （DDL CHECK 为第二道保险）；
        - id 自动生成 UUID（uuid4().hex，对齐 gm_commands L392）；
        - audit_ts_hmac：审计行校验值预留（L250），调用方先算好传入，默认空 =
          校验值未启用（开关由批 3 接线时定，本层仅存不验）。
        """
        if str(result) not in RESULT_ALLOWED:
            raise ValueError(
                f"result 非法：{result!r}（限 {'|'.join(RESULT_ALLOWED)}，5b §4.2 L247）"
            )
        params_text = str(params or "")
        if len(params_text) > PARAMS_MAX_LEN:
            params_text = params_text[:PARAMS_MAX_LEN] + "…"  # L245 截断 200 字
        row_id: str = uuid.uuid4().hex
        conn.execute(
            "INSERT INTO audit_log (id, ts, qq, group_id, command, params,"
            " target_qq, result, detail, ref, audit_ts_hmac)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                row_id,
                str(ts),
                str(qq or ""),
                str(group_id or "0"),
                str(command),
                params_text,
                str(target_qq) if target_qq is not None else None,
                str(result),
                str(detail or ""),
                str(ref) if ref is not None else None,
                str(audit_ts_hmac or ""),
            ),
        )
        return row_id

    def list_recent(
        self,
        conn: Any,
        *,
        limit: int = DEFAULT_LIST_LIMIT,
        command: Any = None,
        qq: Any = None,
    ) -> List[Dict[str, Any]]:
        """最近审计记录（倒序 ts 新→旧；/日志（GM 版）展示源，L254）。

        - limit：返回条数上限，默认 50（DEFAULT_LIST_LIMIT；gm /日志 上限 50）；
          limit <= 0 → 空列表；
        - command：按指令名/事件名过滤（可选）；qq：按操作者 QQ 过滤（可选，
          普通玩家永远看不到本表由调用层权限门控，L264）；
        - 行 → dict：键 = AUDIT_COLUMNS 列名；倒序键 ts DESC（ts 为定长 ISO-8601
          UTC 字符串可字典序），同 ts 按 rowid（写入序）倒序保证稳定。
        """
        if limit <= 0:
            return []
        where: List[str] = []
        params: List[Any] = []
        if command is not None:
            where.append("command = ?")
            params.append(str(command))
        if qq is not None:
            where.append("qq = ?")
            params.append(str(qq))
        sql = (
            "SELECT " + ", ".join(AUDIT_COLUMNS) + " FROM audit_log"
            + (" WHERE " + " AND ".join(where) if where else "")
            + " ORDER BY ts DESC, rowid DESC LIMIT ?"
        )
        cur = conn.execute(sql, (*params, int(limit)))
        rows: Sequence[Any] = cur.fetchall()
        return [dict(zip(AUDIT_COLUMNS, row)) for row in rows]

    def count(self, conn: Any) -> int:
        """审计表总行数（轮转/水位联动统计口径，L261）。"""
        cur = conn.execute("SELECT COUNT(*) FROM audit_log")
        return int(cur.fetchone()[0])

    def rotate(self, conn: Any, keep_n: int) -> int:
        """轮转（L261）：按 ts 删除最旧记录，保留最新 keep_n 条；返回删除行数。

        - keep_n <= 0 → 不轮转（返回 0，调用方显式关闭轮转的口径）；
        - 保留判定同 list_recent 倒序口径（ts DESC, rowid DESC 取前 keep_n）；
        - 默认保留份数 N / 磁盘水位联动由装配层（批 3）按设置传入，本层不持有配置。
        """
        if keep_n <= 0:
            return 0
        cur = conn.execute(
            "DELETE FROM audit_log WHERE id IN ("
            " SELECT id FROM audit_log ORDER BY ts DESC, rowid DESC LIMIT -1 OFFSET ?"
            ")",
            (int(keep_n),),
        )
        return int(getattr(cur, "rowcount", 0) or 0)


__all__ = [
    "AUDIT_TABLE",
    "AUDIT_COLUMNS",
    "RESULT_ALLOWED",
    "PARAMS_MAX_LEN",
    "DEFAULT_LIST_LIMIT",
    "CREATE_TABLE_AUDIT_LOG",
    "EVENT_E1",
    "EVENT_E2",
    "EVENT_E3",
    "EVENT_E4",
    "EVENT_E5",
    "EVENT_E6",
    "classify",
    "AuditStore",
]
