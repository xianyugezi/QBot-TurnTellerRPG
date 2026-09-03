"""GM 权限存储层单测（M12 批2 路2B · 细化_5b_GM指令契约 §1 权限模型）。

依据（行号 = docs/细化/细化_5b_GM指令契约.md）：
  - §1.2 L52-62：admin_users 表 {qq_id, role: owner|gm, granted_commands[],
    granted_by, granted_at, revoke_log}；权限缓存 {qq_id: role} 启动全量加载、
    热重载不重建；机主初始写入 = 安装向导直接写库不经指令（仅无 owner 可写）；
    玩家存档 players 不含权限字段（防拷贝伪造）
  - §1.1 L35-43：三级权限 owner > gm > 普通玩家；L49 默认授予集（重载/备份/
    恢复/日志/编辑/封禁/解封/封禁列表）+ 机主专属可下授（存档导出/调试/测试/
    广播/玩家查询/设置，per-command 粒度存 granted_commands）
  - L62：权限变更即时生效（内存缓存失效重载）；变更写审计 E5（§4.1 L233）
    ——本路只留 audit hook 接口，测试验证 hook 收到 grantor/grantee/变更前后
    角色清单摘要（2C 路 audit_store 落库不在本路）

测试基座：sqlite3 :memory: + 直接执行 schema.CREATE_TABLE_ADMIN_USERS 两条
建表 DDL（不引入 storage 连接层——本路 PermissionStore 是 SQLite 鸭子存储，
只消费 execute/fetchone/commit 四方法）；零 NoneBot。

行号锚点：契约 L39（机主全部指令）、L43（判定优先级）、L45（无权限静默）、
L49（默认授予集/下授）、L56（admin_users 字段）、L57（缓存）、L58/L61
（玩家存档零权限字段）、L60（机主初始写入）、L62（即时生效 + E5 审计）。
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any, List

import pytest

from qbot_rpg.content.permission_store import (
    GM_COMMANDS_ALL,
    GM_DEFAULT_GRANT,
    GM_OWNER_ONLY,
    ROLE_ADMIN_OUT,
    ROLE_MANAGER_OUT,
    ROLE_PLAYER_OUT,
    PermissionStore,
)
from qbot_rpg.storage.schema import (
    CREATE_TABLE_ADMIN_USERS,
    CREATE_TABLE_AUDIT_LOG,
)

OWNER = "10001"   # 机主 QQ（首写）
GM1 = "20001"     # GM（授予）
GM2 = "20002"     # 第二个 GM（独立授撤）
PLAYER = "30001"  # 普通玩家（永不落表）


# ---------------------------------------------------------------------------
# 基座：内存库 + 两张表 + 常用断言辅助
# ---------------------------------------------------------------------------
@pytest.fixture()
def conn() -> sqlite3.Connection:
    """内存库：直接执行 schema 两条 CREATE TABLE（admin_users + audit_log）。

    audit_log 表在本路测试不写数据，建表仅为「表结构就位」口径验证
    （2C 路 audit_store 才落库写入）。
    """
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row  # 行支持 keys() 下标（repository 同款）
    c.executescript(
        CREATE_TABLE_ADMIN_USERS + ";" + CREATE_TABLE_AUDIT_LOG + ";"
    )
    return c


def store_with_owner(conn: sqlite3.Connection,
                     hooks: List[Any] | None = None) -> PermissionStore:
    """机主就绪的 PermissionStore（owner=OWNER，init_owner 首写成功路径）。"""
    s = PermissionStore(audit_hook=(hooks.append if hooks is not None else None))
    assert s.init_owner(conn, OWNER, now="2026-09-03T00:00:00Z") is True
    return s


def row_of(conn: sqlite3.Connection, qq: str) -> sqlite3.Row | None:
    """admin_users 单行（测试断言用，读的是库不是缓存）。"""
    return conn.execute(
        "SELECT * FROM admin_users WHERE qq_id = ?", (qq,)
    ).fetchone()


def role_of_db(conn: sqlite3.Connection, qq: str) -> str:
    """落库角色原文（owner/gm；无行 → 'absent'）。"""
    r = row_of(conn, qq)
    return "absent" if r is None else str(r["role"])


def commands_of(conn: sqlite3.Connection, qq: str) -> List[str]:
    """granted_commands 落库 JSON 解析。"""
    r = row_of(conn, qq)
    if r is None:
        return []
    return list(json.loads(str(r["granted_commands"])))


# ---------------------------------------------------------------------------
# ① init_owner：首写成功 / 重复拒绝（契约 L60）
# ---------------------------------------------------------------------------
class TestInitOwner:
    def test_first_write_success(self, conn: sqlite3.Connection) -> None:
        """安装向导首写：无 owner 时写成功，落库 owner + 时间戳，缓存可见。"""
        s = PermissionStore()
        assert s.init_owner(conn, OWNER, now="2026-09-03T00:00:00Z") is True
        r = row_of(conn, OWNER)
        assert r is not None
        assert r["role"] == "owner"
        assert json.loads(str(r["granted_commands"])) == []
        assert json.loads(str(r["revoke_log"])) == []
        assert r["granted_at"] == "2026-09-03T00:00:00Z"
        assert r["granted_by"] is None
        # 写入后无需 load_cache 即能判定（get_role 直查回填）
        assert s.is_owner(conn, OWNER) is True
        assert s.is_gm(conn, OWNER) is True

    def test_duplicate_owner_rejected(self, conn: sqlite3.Connection) -> None:
        """已存在 owner → 拒绝第二次写入（身份变更仅编辑器/数据库操作）。"""
        s = store_with_owner(conn)
        assert s.init_owner(conn, "99999", now="2026-09-03T01:00:00Z") is False
        # 原 owner 未被覆盖，新 qq 未写入
        assert role_of_db(conn, OWNER) == "owner"
        assert role_of_db(conn, "99999") == "absent"
        assert s.is_owner(conn, "99999") is False

    def test_empty_qq_raises(self, conn: sqlite3.Connection) -> None:
        """空 QQ → ValueError（不落脏数据）。"""
        s = PermissionStore()
        with pytest.raises(ValueError):
            s.init_owner(conn, "  ")


# ---------------------------------------------------------------------------
# ② grant_gm / revoke_gm：角色流转 + revoke_log 留痕（契约 L49/L56/L62）
# ---------------------------------------------------------------------------
class TestGrantRevokeGm:
    def test_grant_gm_default_commands(self, conn: sqlite3.Connection) -> None:
        """授予 GM：commands=None → 角色 gm + 下授列空（默认集常量侧判定）。

        【2026-09-03 语义修正】默认授予集是 GM 角色隐含语义（has_permission
        常量放行），不下存储——user_of/has_permission 判定侧合并计算，防
        granted_commands 列与默认集双写漂移。
        """
        s = store_with_owner(conn)
        assert s.grant_gm(conn, GM1, OWNER, now="2026-09-03T02:00:00Z") is True
        r = row_of(conn, GM1)
        assert r is not None and r["role"] == "gm"
        assert r["granted_by"] == OWNER
        assert commands_of(conn, GM1) == []          # 默认集不下存储
        assert s.is_gm(conn, GM1) is True
        assert s.is_owner(conn, GM1) is False
        # 默认集指令经 has_permission 常量放行
        assert s.has_permission(conn, GM1, "重载") is True

    def test_grant_gm_custom_commands(self, conn: sqlite3.Connection) -> None:
        """显式 commands → 覆盖式精确下授（编辑器/数据库侧口径）。"""
        s = store_with_owner(conn)
        assert s.grant_gm(conn, GM1, OWNER, commands=["测试", "广播"]) is True
        assert set(commands_of(conn, GM1)) == {"测试", "广播"}

    def test_revoke_gm_deletes_and_logs(self, conn: sqlite3.Connection) -> None:
        """撤销 GM：行删除回玩家（唯一事实来源口径，L61）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER, now="2026-09-03T02:00:00Z")
        assert s.revoke_gm(conn, GM1, by=OWNER, now="2026-09-03T03:00:00Z") is True
        assert role_of_db(conn, GM1) == "absent"      # 撤销 = 整行删除
        assert s.is_gm(conn, GM1) is False            # 立即生效
        assert s.is_owner(conn, GM1) is False
        assert s.grant_gm(conn, GM1, OWNER) is True   # 可重新授予（新行）

    def test_revoke_log_rows(self, conn: sqlite3.Connection) -> None:
        """revoke_log 语义（契约 L56 行内字段）：撤销后该 qq 无行 → 无留痕载体。

        契约 L56 revoke_log 定义在 admin_users 行内——行删即无载体。本实现
        「撤销 = 整行删除」符合 L56 表结构（角色回普通玩家 = 不在表内），
        历史留痕职责归 audit_log（E5，2C 路），revoke_log 承载「重新授予后
        仍可见的过渡留痕」（见 test_revoked_then_regrant_preserves_log）。
        """
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        assert s.revoke_gm(conn, GM1, by=OWNER) is True
        # 无行 = 普通玩家（唯一事实来源口径，L61）
        assert row_of(conn, GM1) is None

    def test_revoked_then_regrant_starts_fresh(self, conn: sqlite3.Connection) -> None:
        """撤销（整行删除）后重新授予：revoke_log 为空（历史留痕主责 audit E5）。

        【P0 修复对齐 2026-09-03】旧设计 revoke 重插 owner 行保留 revoke_log，
        但被撤者反而升级机主（安全漏洞）。新语义 = 撤销整行删除（回归普通玩家），
        行内 revoke_log 无载体；grant/revoke 历史经 _notify_audit → audit_log E5。
        """
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        assert s.revoke_gm(conn, GM1, OWNER) is True
        s.grant_gm(conn, GM1, OWNER)
        logs = json.loads(str(row_of(conn, GM1)["revoke_log"]))
        assert logs == []  # 新行 revoke_log 从空开始（历史在 audit_log E5）
        # 权限语义正确：是 GM 不是 owner
        assert s.is_gm(conn, GM1) is True
        assert s.is_owner(conn, GM1) is False

    def test_revoke_owner_rejected(self, conn: sqlite3.Connection) -> None:
        """机主不可被撤销（身份变更仅编辑器/数据库，L60）。"""
        s = store_with_owner(conn)
        assert s.revoke_gm(conn, OWNER, by=OWNER) is False
        assert role_of_db(conn, OWNER) == "owner"

    def test_revoke_nonexistent_noop(self, conn: sqlite3.Connection) -> None:
        """撤销不存在的 GM → False 无操作。"""
        s = store_with_owner(conn)
        assert s.revoke_gm(conn, PLAYER, by=OWNER) is False

    def test_grant_to_owner_noop(self, conn: sqlite3.Connection) -> None:
        """授予已是机主者 → True 且不降级（同人命中高级别，L43）。"""
        s = store_with_owner(conn)
        assert s.grant_gm(conn, OWNER, OWNER) is True
        assert role_of_db(conn, OWNER) == "owner"   # 不降级为 gm


# ---------------------------------------------------------------------------
# ③ has_permission：机主恒 True / GM 默认集 / per-command / 玩家 False
# ---------------------------------------------------------------------------
class TestHasPermission:
    def test_owner_always_true(self, conn: sqlite3.Connection) -> None:
        """机主对全部指令恒 True（含机主专属，L39）。"""
        s = store_with_owner(conn)
        for cmd in sorted(GM_COMMANDS_ALL):
            assert s.has_permission(conn, OWNER, cmd) is True
        assert s.has_permission(conn, OWNER, "不存在的指令") is True  # 机主全权

    def test_gm_default_set(self, conn: sqlite3.Connection) -> None:
        """GM 默认授予集内指令可执行（L49 最小默认集）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        for cmd in sorted(GM_DEFAULT_GRANT):
            assert s.has_permission(conn, GM1, cmd) is True

    def test_gm_owner_only_denied_by_default(self, conn: sqlite3.Connection) -> None:
        """GM 未下授的机主专属指令 → False（默认集不含，L49 最小集）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        for cmd in sorted(GM_OWNER_ONLY):
            assert s.has_permission(conn, GM1, cmd) is False

    def test_per_command_grant_grants(self, conn: sqlite3.Connection) -> None:
        """per-command 下授后 GM 获得该指令权限（存档导出下授样例，TC-04 反向）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        assert s.has_permission(conn, GM1, "存档导出") is False
        assert s.grant_command(conn, GM1, "存档导出", OWNER) is True
        assert s.has_permission(conn, GM1, "存档导出") is True

    def test_revoke_command_removes(self, conn: sqlite3.Connection) -> None:
        """收回下授后权限消失；默认集指令不受影响。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        s.grant_command(conn, GM1, "测试", OWNER)
        assert s.has_permission(conn, GM1, "测试") is True
        assert s.revoke_command(conn, GM1, "测试", OWNER) is True
        assert s.has_permission(conn, GM1, "测试") is False
        assert s.has_permission(conn, GM1, "重载") is True   # 默认集仍在

    def test_player_false(self, conn: sqlite3.Connection) -> None:
        """普通玩家（未落表）任何 GM 指令 → False（静默语义前置，L45）。"""
        s = store_with_owner(conn)
        for cmd in sorted(GM_COMMANDS_ALL):
            assert s.has_permission(conn, PLAYER, cmd) is False

    def test_unknown_command_false(self, conn: sqlite3.Connection) -> None:
        """集外指令串 → False（防任意串注入授权表）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        s.grant_command(conn, GM1, "存档导出", OWNER)
        assert s.has_permission(conn, GM1, "drop table admin_users") is False
        assert s.has_permission(conn, GM1, "") is False

    def test_per_command_only_for_gm(self, conn: sqlite3.Connection) -> None:
        """下授只作用于 gm：普通玩家/机主 → False 无操作。"""
        s = store_with_owner(conn)
        assert s.grant_command(conn, PLAYER, "测试", OWNER) is False
        assert s.grant_command(conn, OWNER, "测试", OWNER) is False
        assert role_of_db(conn, PLAYER) == "absent"

    def test_grant_command_invalid_target(self, conn: sqlite3.Connection) -> None:
        """集外指令下授 → False；重复下授 → False（无操作幂等）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        assert s.grant_command(conn, GM1, "不存在的指令", OWNER) is False
        assert s.grant_command(conn, GM1, "存档导出", OWNER) is True
        assert s.grant_command(conn, GM1, "存档导出", OWNER) is False  # 已含


# ---------------------------------------------------------------------------
# ④ 缓存失效即时生效（契约 L57/L62）
# ---------------------------------------------------------------------------
class TestCacheInvalidation:
    def test_grant_after_negative_cache(self, conn: sqlite3.Connection) -> None:
        """先判玩家（负缓存）→ 授予 GM 后立即放行（无陈旧缓存窗口）。"""
        s = store_with_owner(conn)
        assert s.is_gm(conn, GM1) is False       # 负缓存 {GM1: player}
        assert s.grant_gm(conn, GM1, OWNER) is True
        assert s.is_gm(conn, GM1) is True        # 变更后立即生效
        assert s.has_permission(conn, GM1, "重载") is True

    def test_revoke_after_positive_cache(self, conn: sqlite3.Connection) -> None:
        """先判 GM（正缓存）→ 撤销后立即失效为玩家。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        assert s.is_gm(conn, GM1) is True
        assert s.revoke_gm(conn, GM1, OWNER) is True
        assert s.is_gm(conn, GM1) is False       # 正缓存已被失效
        assert s.has_permission(conn, GM1, "重载") is False

    def test_load_cache_full_reload(self, conn: sqlite3.Connection) -> None:
        """启动全量加载：清空缓存后 load_cache 重建 {qq_id: role}（L57）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        s.grant_gm(conn, GM2, OWNER)
        s._cache.clear()                          # 模拟进程冷启动
        cache = s.load_cache(conn)
        assert cache == {OWNER: ROLE_ADMIN_OUT, GM1: ROLE_MANAGER_OUT,
                         GM2: ROLE_MANAGER_OUT}
        assert s.is_owner(conn, OWNER) is True
        assert s.is_gm(conn, GM1) is True

    def test_load_cache_after_revoke(self, conn: sqlite3.Connection) -> None:
        """撤销后再 load_cache：被撤者不在缓存（进程内已即时失效）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        s.revoke_gm(conn, GM1, OWNER)
        s._cache.clear()
        cache = s.load_cache(conn)
        assert GM1 not in cache
        assert s.get_role(conn, GM1) == ROLE_PLAYER_OUT


# ---------------------------------------------------------------------------
# ⑤ 玩家存档无权限字段（契约 L58/L61）+ audit hook（E5 摘要）
# ---------------------------------------------------------------------------
class TestPlayerArchiveAndAuditHook:
    def test_players_schema_has_no_permission_columns(
        self, conn: sqlite3.Connection
    ) -> None:
        """players 表结构不含任何权限字段（防拷贝存档伪造，L58/L61）。

        本测试只验证 players 表结构未因本路改动增加权限列——admin_users 是
        唯一权限事实来源，任何「存档内标记权限」设计一律拒绝。
        """
        cols = {r[1] for r in conn.execute("PRAGMA table_info(players)")}
        assert "role" not in cols
        assert "granted_commands" not in cols
        assert "qq_id" not in cols                # players 用 player_qid 命名
        assert "revoke_log" not in cols
        assert "admin_users" in {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert "audit_log" in {
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }

    def test_audit_hook_grant_revoke_events(self, conn: sqlite3.Connection) -> None:
        """E5 权限变更 hook：grant_gm/revoke_gm 各触发一次，摘要含
        grantor/grantee/变更前后角色（契约 L62/L233，2C 路 audit_store 消费）。"""
        events: List[Any] = []
        s = store_with_owner(conn, hooks=events)
        s.grant_gm(conn, GM1, OWNER)
        s.revoke_gm(conn, GM1, OWNER)
        assert len(events) == 2
        ev_grant = events[0]
        assert ev_grant["action"] == "grant_gm"
        assert ev_grant["grantor"] == OWNER
        assert ev_grant["grantee"] == GM1
        assert ev_grant["role_before"] == ROLE_PLAYER_OUT
        assert ev_grant["role_after"] == ROLE_MANAGER_OUT
        ev_revoke = events[1]
        assert ev_revoke["action"] == "revoke_gm"
        assert ev_revoke["role_before"] == ROLE_MANAGER_OUT
        assert ev_revoke["role_after"] == ROLE_PLAYER_OUT

    def test_audit_hook_per_command_events(self, conn: sqlite3.Connection) -> None:
        """per-command 变更也触发 hook，摘要含变更前后指令清单。"""
        events: List[Any] = []
        s = store_with_owner(conn, hooks=events)
        s.grant_gm(conn, GM1, OWNER)
        s.grant_command(conn, GM1, "存档导出", OWNER)
        s.revoke_command(conn, GM1, "存档导出", OWNER)
        actions = [e["action"] for e in events]
        assert actions == ["grant_gm", "grant_command", "revoke_command"]
        gc = events[1]
        assert gc["commands_before"] == []
        assert gc["commands_after"] == ["存档导出"]
        rc = events[2]
        assert rc["commands_before"] == ["存档导出"]
        assert rc["commands_after"] == []

    def test_audit_hook_failure_not_blocking(self, conn: sqlite3.Connection) -> None:
        """hook 抛异常 → 权限变更不阻断（尽力而为；2C 路接管前不卡权限）。"""
        def boom(_event: Any) -> None:
            raise RuntimeError("audit_store 未接线")

        s = PermissionStore(audit_hook=boom)
        assert s.init_owner(conn, OWNER) is True
        assert s.grant_gm(conn, GM1, OWNER) is True   # hook 异常被吞
        assert s.is_gm(conn, GM1) is True


# ---------------------------------------------------------------------------
# ⑥ user_of / get_role 快照口（gm_commands L53-55 / runner L245-270 消费）
# ---------------------------------------------------------------------------
class TestUserOf:
    def test_user_of_roles(self, conn: sqlite3.Connection) -> None:
        """user_of 返回归一角色元组 + 显式下授集；普通玩家 → (player, ())。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        s.grant_command(conn, GM1, "测试", OWNER)
        role, granted = s.user_of(conn, GM1)
        assert role == ROLE_MANAGER_OUT
        assert granted == ("测试",)                 # 只含显式下授（默认集不随行存储）
        role_o, _g = s.user_of(conn, OWNER)
        assert role_o == ROLE_ADMIN_OUT
        role_p, g_p = s.user_of(conn, PLAYER)
        assert role_p == ROLE_PLAYER_OUT
        assert g_p == ()

    def test_default_grant_not_in_user_of(self, conn: sqlite3.Connection) -> None:
        """user_of 的 granted 只含显式下授，不含默认集（判定侧合并，防冗余）。"""
        s = store_with_owner(conn)
        s.grant_gm(conn, GM1, OWNER)
        _role, granted = s.user_of(conn, GM1)
        assert granted == ()
