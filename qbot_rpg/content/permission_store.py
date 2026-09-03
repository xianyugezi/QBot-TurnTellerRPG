"""GM 权限存储层（M12 批2 路2B · 细化_5b_GM指令契约 §1 权限模型）。

文件：qbot_rpg/content/permission_store.py
创建时间：2026-09-03

职责（对齐 docs/细化/细化_5b_GM指令契约.md，行号 = 契约行号）：
  - 权限唯一事实来源 = 数据库系统配置区 admin_users 表（L56/L58/L61）：
    {qq_id, role: owner|gm, granted_commands[], granted_by, granted_at, revoke_log}
  - 权限缓存 = 进程内存 {qq_id: role}（L57）：启动全量加载（load_cache），
    热重载**不**重建（权限不受内容包热重载影响——本类不感知热重载，缓存仅
    由本类显式失效）；权限变更即时生效（L62：变更后主动失效对应缓存项）
  - 三级权限（L35-43）：机主(owner) > GM(gm) > 普通玩家（非表内成员）；
    判定优先级同人命中高级别；GM 不自动授予群管理（L44/L66，映射 2C 路）
  - 默认授予集（L49 裁决：全部指令表标注 GM 的指令）+ 机主专属可 per-command
    下授（granted_commands 列，L49）——集合定义见下方常量（5 条 L160 清单 +
    备份/恢复/解封/封禁列表按 G2/G3/G11/G12 登记，接入后 GM_DEFAULT_GRANT 推导
    自动含）
  - 机主初始写入（L60）：安装向导直接写库，不经任何指令；仅无 owner 时可写，
    已存在拒绝（机主身份变更仅编辑器/数据库操作）
  - 权限变更写审计 E5（L62/L233）：本层只留 hook 接口 notify_audit_hook
    （回调注入；实际 audit_store 落库归 2C 路实现，本路不写 audit_log）

工程补白 · 显式标注：
  1) 本类为**纯逻辑 + SQLite 鸭子存储**（execute/fetchone/fetchall/commit 四方法
     即可），不依赖 qbot_rpg.storage 具体类（connection.py 是 aiosqlite 封装，
     单测用 sqlite3 :memory: 自建表驱动）；零 NoneBot import（3a R1）。
  2) 写入方法全部同步 + 自带 conn.commit()（自动提交语义，同 repository 层
     管理写口径）；数据库写异常原样上抛 sqlite3.Error，由装配/调用方裁决。
  3) 审计 hook 为**尽力而为**：回调异常捕获吞掉并置 None 输出（不阻断权限
     变更本身；2C 路 audit_store 落库前不应因审计失败卡权限）。
  4) 本文件不 import qbot_rpg.commands.gm_commands（commands 层被依赖方向
     禁止——见细化_3a 分层），角色/指令清单常量本地定义并注明对齐锚点；
     content 层依赖方向仅 ↓ data（U2 铁律），本文件零 content/data import。

角色/权限常量与 commands 层对齐锚点：
  - gm_commands.py L173-175：ROLE_ADMIN="admin"（机主）/ ROLE_MANAGER="manager"（GM）
    / ROLE_PLAYER="player"（普通玩家）；L196-198 GM_DEFAULT_GRANT 由 GM_COMMAND_LEVEL
    推导。本文件 admin_users 落库角色取 ROLE_OWNER_DB="owner" / ROLE_GM_DB="gm"
    （契约 L56 原文字面），对外判定接口（is_gm/user_of）输出 commands 层归一角色
    （admin/manager），与 runner.py L245-270 消费口径一致。
  - runner.py L245-270：装配层消费 is_gm(qid) / user_of(qid)（user_of 输出
    GmUser 或 (role, granted_commands) 元组均可，见 gm_commands._user_of L575-581）。
"""

from __future__ import annotations

import json
from typing import Any, Callable, Dict, FrozenSet, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# 角色常量（契约 L37-42 三级 + L56 role 枚举 owner|gm）
# ---------------------------------------------------------------------------
ROLE_OWNER_DB: str = "owner"      # admin_users.role 落库值（契约 L56 字面）
ROLE_GM_DB: str = "gm"            # admin_users.role 落库值（契约 L56 字面）

# 对外判定接口输出角色（commands 层口径，gm_commands L173-175）
ROLE_ADMIN_OUT: str = "admin"     # 机主
ROLE_MANAGER_OUT: str = "manager"  # GM
ROLE_PLAYER_OUT: str = "player"   # 普通玩家（非表内成员）

# 数据库角色 → 对外归一角色（owner→admin / gm→manager；未知 → player 安全失败）
_ROLE_TO_OUT: Mapping[str, str] = {
    ROLE_OWNER_DB: ROLE_ADMIN_OUT,
    ROLE_GM_DB: ROLE_MANAGER_OUT,
}


# ---------------------------------------------------------------------------
# GM 指令清单与默认授予集（契约 L49/L56/L82 总表）
# ---------------------------------------------------------------------------
# GM 指令全集（14 条 G1-G14 名，5b §2.1 总表）：判定用白名单——
# has_permission 只认本集内的 command 名，集外一律 False（防任意串注入授权表）
GM_COMMANDS_ALL: FrozenSet[str] = frozenset({
    # G1-G14（契约 §2.1 L85-104）
    "重载", "备份", "恢复", "存档导出", "调试", "测试", "广播", "日志",
    "玩家查询", "封禁", "解封", "封禁列表", "编辑", "设置",
})

# 默认授予集（契约 L49 裁决 = 全部指令表标注 GM 的指令）：
# 重载 G1 / 备份 G2 / 恢复 G3 / 日志 G8 / 封禁 G10 / 解封 G11 / 封禁列表 G12 /
# 编辑 G13；「机主专属可下授」= 存档导出 G4 / 调试 G5 / 测试 G6 / 广播 G7 /
# 玩家查询 G9 / 设置 G14（不进默认集，GM 需 per-command 下授）
GM_DEFAULT_GRANT: FrozenSet[str] = frozenset({
    "重载", "备份", "恢复", "日志", "封禁", "解封", "封禁列表", "编辑",
})

# 机主专属（可下授）指令集（契约 L49；仅供文档/校验对照，判定逻辑不依赖）
GM_OWNER_ONLY: FrozenSet[str] = frozenset({
    "存档导出", "调试", "测试", "广播", "玩家查询", "设置",
})


# ---------------------------------------------------------------------------
# 审计 hook 类型（E5 权限变更审计，契约 L233；2C 路 audit_store 实现）
# ---------------------------------------------------------------------------
# 变更摘要 dict：{action, grantor, grantee, role_before, role_after,
#                 commands_before: [], commands_after: []}
PermissionAuditHook = Callable[[Mapping[str, Any]], None]


def _as_list(raw: Any) -> List[str]:
    """JSON 列读解（SCHEMA-6 兜底）：[]/空/非法 → []；仅收 str 元素。"""
    if raw is None:
        return []
    if isinstance(raw, (list, tuple, set, frozenset)):
        items = list(raw)
    else:
        try:
            items = json.loads(str(raw))
        except (TypeError, ValueError):
            return []
        if not isinstance(items, list):
            return []
    return [str(x) for x in items if isinstance(x, (str, int)) and str(x)]


class PermissionStore:
    """GM 权限存储（admin_users 表唯一事实来源 + 进程内存角色缓存）。

    存储连接为 SQLite 鸭子类型（execute/fetchone/fetchall/commit），单测以
    sqlite3 :memory: 自建表驱动（schema.CREATE_TABLE_ADMIN_USERS 等两条）。

    缓存纪律（契约 L57/L62）：
      - 启动全量加载：load_cache(conn) 建 {qq_id: role} 内存快照；
      - 权限变更即时生效：grant/revoke 写库成功后**主动失效**该 qq 缓存项
        （_invalidate），下一次读取直查 DB 并回填缓存；不存在「陈旧缓存放行」
        窗口；进程内其他持有者经同一实例读写，无跨进程缓存一致性问题。
      - 热重载不重建：本类不监听内容包热重载（权限与内容包解耦），缓存只随
        权限变更失效；2C 路群管理映射如需感知群事件另建映射层，不混入本类。
    """

    __slots__ = ("_cache", "_audit_hook")

    def __init__(self, audit_hook: Optional[PermissionAuditHook] = None) -> None:
        # 进程内存缓存 {qq_id: 对外归一角色 admin|manager}（L57：仅角色映射）
        self._cache: Dict[str, str] = {}
        # E5 审计 hook（2C 路注入 audit_store 包装；None = 不落审计）
        self._audit_hook: Optional[PermissionAuditHook] = audit_hook

    # ------------------------------------------------------------------
    # 机主初始写入（契约 L60：安装向导直接写库，不经任何指令）
    # ------------------------------------------------------------------
    def init_owner(self, conn: Any, qq_id: Any, *, now: Optional[str] = None) -> bool:
        """首次写入机主 owner（仅当表内无 owner 时成功）。

        入参 conn: 鸭子连接；qq_id: 机主 QQ。出参 bool：True=写入成功；
        False=已存在 owner（机主身份变更仅编辑器/数据库操作，本层拒绝）。
        """
        qq = str(qq_id or "").strip()
        if not qq:
            raise ValueError("机主 QQ 号为空")
        row = conn.execute(
            "SELECT qq_id, role FROM admin_users WHERE role = ?", (ROLE_OWNER_DB,)
        ).fetchone()
        if row is not None:
            return False
        ts = now or _utcnow()
        conn.execute(
            "INSERT INTO admin_users (qq_id, role, granted_commands, granted_by,"
            " granted_at, revoke_log) VALUES (?,?,'[]',NULL,?, '[]')",
            (qq, ROLE_OWNER_DB, ts),
        )
        conn.commit()
        self._cache[qq] = ROLE_ADMIN_OUT
        return True

    # ------------------------------------------------------------------
    # 权限缓存（契约 L57：启动全量加载 {qq_id: role}；热重载不重建）
    # ------------------------------------------------------------------
    def load_cache(self, conn: Any) -> Dict[str, str]:
        """启动全量加载：admin_users 全表 → {qq_id: 对外归一角色}。

        出参: {qq_id: 'admin'|'manager'}（owner→admin / gm→manager）。
        缓存由 grant/revoke 显式失效，热重载不重建（L57）。
        """
        loaded: Dict[str, str] = {}
        rows = conn.execute(
            "SELECT qq_id, role FROM admin_users ORDER BY qq_id"
        ).fetchall()
        for r in rows:
            qq = str(r["qq_id"] if hasattr(r, "keys") else r[0])
            role = str(r["role"] if hasattr(r, "keys") else r[1])
            out = _ROLE_TO_OUT.get(role, ROLE_PLAYER_OUT)
            if out != ROLE_PLAYER_OUT:
                loaded[qq] = out
        self._cache = loaded
        return dict(loaded)

    # ------------------------------------------------------------------
    # 只读判定（三级：owner > gm > 普通玩家，契约 L35-43）
    # ------------------------------------------------------------------
    def get_role(self, conn: Any, qq_id: Any) -> str:
        """取 qq 权限角色（对外归一 admin/manager/player；L43 单角色不并存）。

        缓存命中直接返回；未命中直查 DB 并回填缓存（读写同源即时生效）。
        """
        qq = str(qq_id or "")
        if not qq:
            return ROLE_PLAYER_OUT
        cached = self._cache.get(qq)
        if cached is not None:
            return cached
        row = conn.execute(
            "SELECT role FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        if row is None:
            self._cache[qq] = ROLE_PLAYER_OUT
            return ROLE_PLAYER_OUT
        role_raw = str(row["role"] if hasattr(row, "keys") else row[0])
        out = _ROLE_TO_OUT.get(role_raw, ROLE_PLAYER_OUT)
        self._cache[qq] = out
        return out

    def is_owner(self, conn: Any, qq_id: Any) -> bool:
        """机主判定（owner/admin → True；非表内/未知 → False 安全失败）。"""
        return self.get_role(conn, qq_id) == ROLE_ADMIN_OUT

    def is_gm(self, conn: Any, qq_id: Any) -> bool:
        """GM 及以上判定（机主或 GM → True；普通玩家/未知 → False）。

        runner.py L245-270 装配消费口：store=None 或异常 → False（静默安全）。
        """
        return self.get_role(conn, qq_id) in (ROLE_ADMIN_OUT, ROLE_MANAGER_OUT)

    # ------------------------------------------------------------------
    # GM 授予 / 撤销（角色流转 + revoke_log 留痕，契约 L49/L56/L62）
    # ------------------------------------------------------------------
    def grant_gm(
        self,
        conn: Any,
        qq_id: Any,
        granted_by: Any = None,
        *,
        commands: Optional[Sequence[str]] = None,
        now: Optional[str] = None,
    ) -> bool:
        """授予 GM（role='gm'）。granted_by 记录授予人（机主 QQ）。

        commands=None → 授予 GM 角色 + 默认集由 has_permission 常量放行
        （默认集不下存储，契约 L49：默认授予集是 GM 角色隐含语义）；
        显式传列表 → 以传入为准写入 granted_commands 列（覆盖式写入，
        供编辑器/数据库侧精确下授）。重复授予（已是 gm）→ 幂等刷新
        granted_commands/granted_by/granted_at 并返回 True。
        机主已是 owner → 不降级、返回 True（同人命中高级别，L43）。
        """
        qq = str(qq_id or "").strip()
        if not qq:
            raise ValueError("GM QQ 号为空")
        # 列只存显式下授集：commands=None（默认授予）→ []（默认集常量侧判定）；
        # 显式列表 → 白名单过滤后的下授集
        explicit = (
            self._validate_commands(commands)
            if commands is not None else []
        )
        grantor = str(granted_by) if granted_by is not None else None
        ts = now or _utcnow()
        row = conn.execute(
            "SELECT role FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        role_before: str = ROLE_PLAYER_OUT
        if row is not None:
            role_raw = str(row["role"] if hasattr(row, "keys") else row[0])
            role_before = _ROLE_TO_OUT.get(role_raw, ROLE_PLAYER_OUT)
        if role_before == ROLE_ADMIN_OUT:
            # 机主不可被降级为 GM；授予动作对机主无操作（L43 同人命中高级别）
            self._cache[qq] = ROLE_ADMIN_OUT
            return True
        granted_json = json.dumps(explicit, ensure_ascii=False)
        if row is None:
            conn.execute(
                "INSERT INTO admin_users (qq_id, role, granted_commands, granted_by,"
                " granted_at, revoke_log) VALUES (?,?,?,?,?, '[]')",
                (qq, ROLE_GM_DB, granted_json, grantor, ts),
            )
        else:
            conn.execute(
                "UPDATE admin_users SET role = ?, granted_commands = ?,"
                " granted_by = ?, granted_at = ? WHERE qq_id = ?",
                (ROLE_GM_DB, granted_json, grantor, ts, qq),
            )
        conn.commit()
        self._invalidate(qq)
        self._notify_audit(
            action="grant_gm", grantor=grantor, grantee=qq,
            role_before=role_before, role_after=ROLE_MANAGER_OUT,
            commands_before=[], commands_after=explicit,
        )
        return True

    def revoke_gm(self, conn: Any, qq_id: Any, by: Any = None,
                  *, now: Optional[str] = None) -> bool:
        """撤销 GM：role 'gm' → 删除行（回归普通玩家 = 不在表内，契约 L61 口径）。

        仅对 gm 生效；机主（owner）拒绝撤销（机主身份变更仅编辑器/数据库，
        L60）；非 GM/无记录 → False（无操作）。返回是否实际撤销。

        【P0 修复 · 2026-09-03】旧实现 DELETE 后重插 role=owner（试图保留
        revoke_log）——admin_users CHECK 只允许 owner|gm，重插成 owner 使被撤
        者反而升级机主（is_gm/全权限恒 True，安全漏洞）。修复：只 DELETE 不
        重插；角色回普通玩家 = 不在表内。revoke_log 是行内字段，整行删除即无
        载体，历史留痕主责 audit_log E5（2C 路已交付 audit_store；本层经
        _notify_audit 输出 grantor/grantee/变更前后清单）。
        """
        qq = str(qq_id or "").strip()
        if not qq:
            raise ValueError("QQ 号为空")
        row = conn.execute(
            "SELECT role, granted_commands FROM admin_users WHERE qq_id = ?",
            (qq,),
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "keys"):
            role_raw, cmds_raw = str(row["role"]), row["granted_commands"]
        else:
            role_raw, cmds_raw = str(row[0]), row[1]
        if role_raw == ROLE_OWNER_DB:
            return False  # 机主身份变更仅编辑器/数据库操作（L60）
        revoker = str(by) if by is not None else None
        conn.execute(
            "DELETE FROM admin_users WHERE qq_id = ?", (qq,)
        )
        conn.commit()
        self._invalidate(qq)
        self._notify_audit(
            action="revoke_gm", grantor=revoker, grantee=qq,
            role_before=ROLE_MANAGER_OUT, role_after=ROLE_PLAYER_OUT,
            commands_before=_as_list(cmds_raw), commands_after=[],
        )
        return True

    # ------------------------------------------------------------------
    # per-command 下授 / 收回（契约 L49：granted_commands 列，机主操作）
    # ------------------------------------------------------------------
    def grant_command(self, conn: Any, qq_id: Any, command: Any, by: Any = None,
                      *, now: Optional[str] = None) -> bool:
        """给 GM 追加下授单条指令（granted_commands 并集；仅对 gm 生效）。

        目标非 GM（player/owner）→ False（下授只作用于 GM，契约 L49 语义）；
        指令不在 GM_COMMANDS_ALL（或已含）→ False（无操作）。
        """
        qq = str(qq_id or "").strip()
        cmd = str(command or "").strip()
        if not qq or cmd not in GM_COMMANDS_ALL:
            return False
        row = conn.execute(
            "SELECT role, granted_commands FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "keys"):
            role_raw, cmds_raw = str(row["role"]), row["granted_commands"]
        else:
            role_raw, cmds_raw = str(row[0]), row[1]
        if role_raw != ROLE_GM_DB:
            return False  # 下授只作用于 GM（owner 恒全权无需下授）
        cmds = _as_list(cmds_raw)
        if cmd in cmds:
            return False
        cmds.append(cmd)
        grantor = str(by) if by is not None else None
        conn.execute(
            "UPDATE admin_users SET granted_commands = ?, granted_by = ?"
            " WHERE qq_id = ?",
            (json.dumps(cmds, ensure_ascii=False), grantor, qq),
        )
        conn.commit()
        self._invalidate(qq)
        self._notify_audit(
            action="grant_command", grantor=grantor, grantee=qq,
            role_before=ROLE_MANAGER_OUT, role_after=ROLE_MANAGER_OUT,
            commands_before=[c for c in cmds if c != cmd], commands_after=cmds,
        )
        return True

    def revoke_command(self, conn: Any, qq_id: Any, command: Any, by: Any = None,
                       *, now: Optional[str] = None) -> bool:
        """从 GM 的 granted_commands 收回单条下授（仅对 gm 生效）。"""
        qq = str(qq_id or "").strip()
        cmd = str(command or "").strip()
        if not qq or cmd not in GM_COMMANDS_ALL:
            return False
        row = conn.execute(
            "SELECT role, granted_commands FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        if row is None:
            return False
        if hasattr(row, "keys"):
            role_raw, cmds_raw = str(row["role"]), row["granted_commands"]
        else:
            role_raw, cmds_raw = str(row[0]), row[1]
        if role_raw != ROLE_GM_DB:
            return False
        cmds = _as_list(cmds_raw)
        if cmd not in cmds:
            return False
        before = list(cmds)
        cmds.remove(cmd)
        grantor = str(by) if by is not None else None
        ts = now or _utcnow()
        # per-command 收回留痕：revoke_log 行内追加（{by, at, command}）——
        # 该列在 owner|gm CHECK 下对「活跃 GM 行的调整」留痕（整行删除的
        # GM 撤销历史主责 audit_log E5）
        rev_log = conn.execute(
            "SELECT revoke_log FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        log_entries: List[Any] = []
        if rev_log is not None:
            if hasattr(rev_log, "keys"):
                log_entries = _as_list(rev_log["revoke_log"])
            else:
                log_entries = _as_list(rev_log[0])
        log_entries.append({"by": grantor, "at": ts, "command": cmd})
        conn.execute(
            "UPDATE admin_users SET granted_commands = ?, granted_by = ?,"
            " revoke_log = ? WHERE qq_id = ?",
            (json.dumps(cmds, ensure_ascii=False), grantor,
             json.dumps(log_entries, ensure_ascii=False), qq),
        )
        conn.commit()
        self._invalidate(qq)
        self._notify_audit(
            action="revoke_command", grantor=grantor, grantee=qq,
            role_before=ROLE_MANAGER_OUT, role_after=ROLE_MANAGER_OUT,
            commands_before=before, commands_after=cmds,
        )
        return True

    # ------------------------------------------------------------------
    # 权限判定（机主恒 True；GM 查默认集+下授集；其他 False）＋ user_of 快照
    # ------------------------------------------------------------------
    def has_permission(self, conn: Any, qq_id: Any, command: Any) -> bool:
        """单条指令权限判定（契约 L35-43 + L49 口径，逐次直查 DB 即时生效）。

        - 机主（owner）→ 恒 True（全部指令 + 授予/撤销，L39）；
        - GM → command ∈ 默认授予集 ∪ granted_commands 下授集；
        - 普通玩家/未知 → False（无 GM 权限 → 指令层静默无视，L45）。
        """
        qq = str(qq_id or "")
        cmd = str(command or "").strip()
        if not qq or not cmd:
            return False
        role = self.get_role(conn, qq)
        if role == ROLE_ADMIN_OUT:
            return True
        if role != ROLE_MANAGER_OUT:
            return False
        if cmd in GM_DEFAULT_GRANT:
            return True
        row = conn.execute(
            "SELECT granted_commands FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        if row is None:
            return False
        cmds_raw = row["granted_commands"] if hasattr(row, "keys") else row[0]
        return cmd in _as_list(cmds_raw)

    def user_of(self, conn: Any, qq_id: Any) -> Any:
        """权限快照（gm_commands L53-55 消费口）：返回 GmUser 或
        (role, granted_commands) 元组（runner.py L261-267 兼容两者）。

        归一角色 admin/manager/player；granted_commands 为该 GM 下授集
        （默认集为框架常量不必随行存储，判定侧 has_permission 合并计算）。
        """
        qq = str(qq_id or "")
        if not qq:
            return (ROLE_PLAYER_OUT, ())
        role = self.get_role(conn, qq)
        row = conn.execute(
            "SELECT granted_commands FROM admin_users WHERE qq_id = ?", (qq,)
        ).fetchone()
        granted: List[str] = []
        if row is not None:
            cmds_raw = row["granted_commands"] if hasattr(row, "keys") else row[0]
            granted = _as_list(cmds_raw)
        return (role, tuple(granted))

    # ------------------------------------------------------------------
    # 内部：缓存失效 / 审计 hook / 指令校验 / 时间
    # ------------------------------------------------------------------
    def _invalidate(self, qq_id: str) -> None:
        """权限变更即时生效（L62）：变更后主动失效该 qq 缓存项。

        下一条读取经 get_role 直查 DB 回填；不整表清空（保留其他 qq 缓存）。
        """
        self._cache.pop(qq_id, None)

    def _notify_audit(self, **fields: Any) -> None:
        """E5 权限变更审计 hook（契约 L62/L233；2C 路注入 audit_store 实现）。

        变更摘要含 grantor/grantee/变更前后角色清单；尽力而为（异常吞掉）。
        """
        hook = self._audit_hook
        if hook is None:
            return
        try:
            hook(fields)
        except Exception:
            pass  # 审计失败不阻断权限变更（2C 路接管前不卡权限）

    def _validate_commands(self, commands: Optional[Sequence[str]]) -> List[str]:
        """指令集校验：None → 默认授予集；显式列表 → 去重保序 + 白名单过滤。

        集外指令（防任意串注入授权表）静默丢弃；空列表 = 授予 GM 但不给任何
        下授（仅默认集生效）。
        """
        if commands is None:
            return sorted(GM_DEFAULT_GRANT)
        seen: List[str] = []
        for c in commands:
            c = str(c or "").strip()
            if c and c in GM_COMMANDS_ALL and c not in seen:
                seen.append(c)
        return seen


def _utcnow() -> str:
    """当前 UTC 时间（ISO-8601 Z 后缀；与 storage.migrations.utcnow 同口径）。"""
    import datetime

    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
