"""GM 指令接线单测（M4 批次6·路G2 · qbot_rpg/commands/gm_commands.py）。

依据：m4_shared_contract.md §2.3（GM 指令：/gm 权限三级 + 静默 + 留痕 + 禁绑；GM 指令清单以
分隔符规范 L160 长清单为准（+设置））+ §2.2（列表 5 条/页上限、页脚固定 TPL-08、页码越界夹取
+「已到最后一页」2026-08-27 用户裁决②、0/负数/非数字 → TPL-12）+ docs/细化/细化_5b_GM指令契约.md
（§1 权限模型三级/静默语义/存档标记；§2 GM 指令集 G1/G8/G10/G13/G14 逐条；§3 权限分支 /日志
双分支 + 快捷禁绑 C02；§4 审计 字段/成败皆痕/无权限不写）+ docs/审查参考/指令分隔符统一规范.md
L160（GM 指令清单：重载/封禁/日志/编辑/设置）+ L128/L169-171（强制 / 前缀 + 执行层二次检查）+
2026-08-27 用户裁决②（超页夹取最后一页；0/负数/非数字 → TPL-12）。

集成口径：GM 后端引擎（批次6/7）尚未落盘，本测试以**契约忠实替身**驱动——注入
ctx["gm_backend"] = FakeGmBackend（实现本层文件头声明的消费接口 reload_content / ban_player /
recent_audit / editor_link / apply_setting / audit_store），断言命令层权限/静默/留痕/禁绑/
前缀/渲染/错误全链路输出。批次7 落盘后替身可整体替换为真实后端，断言不破。

覆盖：L160 清单常量（重载/封禁/日志/编辑/设置 + 强制前缀接线）· 权限三级（admin/manager/player
↔ 机主/GM/普通玩家 归一；判定优先级；per-command 下授）· 静默（无权限零出站零审计 TC-01/04/24；
成功静默不回显、摘要入 audit.detail）· 留痕（build_audit_record 字段 / 成败皆写 / 无权限不写 /
audit_ts_hmac / 不可删语义）· 重载（成功/缺参/超参/包不存在/失败项清单）· 封禁（成功 E4 四要素
/缺参/QQ 非法/默认永久/后端失败）· 日志（GM 版系统日志 / 5 条每页 + TPL-08 页脚 / 条数=N 窗口
上限 50 / 超页夹取裁决② / 非法页码 TPL-12）· 编辑（链接 + 权限级提示）· 设置（键值切换/缺参/
超参/未知键）· GM 禁绑（C02：『重载』是 GM 指令，不可绑定为快捷）· GM 强制前缀（路由层裸发拦截
+ 带前缀放行 + is_gm 二次检查位）· 注册与解析接线 · 待接线防御。
"""

from __future__ import annotations

import pytest

import qbot_rpg.commands.gm_commands as gc
from qbot_rpg.commands.gm_commands import (
    BAN_DEFAULT_DURATION,
    GM_CMD_BAN,
    GM_CMD_BACKUP,
    GM_CMD_BANLIST,
    GM_CMD_EDIT,
    GM_CMD_EXPORT,
    GM_CMD_LOG,
    GM_CMD_RELOAD,
    GM_CMD_RESTORE,
    GM_CMD_SETTINGS,
    GM_COMMANDS,
    GM_COMMAND_INDEX,
    GM_COMMAND_LEVEL,
    GM_DEFAULT_GRANT,
    LOG_DEFAULT_SHOW,
    LOG_MAX_ENTRIES,
    LOG_PAGE_SIZE,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_PLAYER,
    GmPermResult,
    GmResult,
    GmUser,
    audit_hmac,
    build_audit_record,
    check_gm_permission,
    cmd_gm_ban,
    cmd_gm_backup,
    cmd_gm_banlist,
    cmd_gm_edit,
    cmd_gm_export,
    cmd_gm_log,
    cmd_gm_reload,
    cmd_gm_restore,
    cmd_gm_settings,
    gm_binding_guard,
    handle_gm_command,
    is_gm_command_name,
    record_audit,
    register_gm_commands,
    render_log_line,
    render_log_page,
    role_of,
    silent_result,
)
from qbot_rpg.commands.parsers import DEFAULT_PREFIX_REQUIRED, DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import (
    PERM_GM,
    PERM_OWNER,
    ROUTE_COMMAND,
    ROUTE_IGNORED,
    Router,
)
from qbot_rpg.commands.sender import format_tpl12

# ---------------------------------------------------------------------------
# 契约忠实替身：GM 后端引擎（批次6/7 装配；消费接口见 gm_commands.py 文件头）
# ---------------------------------------------------------------------------


def _events(n: int) -> list:
    """n 条审计事件（ts 顺序：越靠后越新；/日志 展示最近 count 条）。"""
    return [
        {
            "ts": f"2026-08-26T12:{i // 60:02d}:{i % 60:02d}Z",
            "qq": "10001",
            "group_id": "20001",
            "command": GM_CMD_RELOAD,
            "params": "内容包X",
            "result": "success",
            "detail": "✅ 已重载【内容包X】：技能 12 条 / 怪物 8 条 / 地图 5 张",
        }
        for i in range(n)
    ]


class FakeGmBackend:
    """GM 后端引擎契约替身（见 gm_commands.py 文件头消费接口）。"""

    def __init__(self, log_events: list | None = None) -> None:
        self.reload_calls: list = []
        self.ban_calls: list = []
        self.audit_calls: list = []
        self.settings_calls: list = []
        self.editor_calls: list = []
        self.audit_store_calls: list = []  # append() 落库收集
        self.log_events: list = list(log_events if log_events is not None else _events(12))
        self.settings: dict = {}

    # -- G1 重载 --
    def reload_content(self, pack: str, ctx: dict) -> dict:
        self.reload_calls.append((pack, ctx))
        if pack == "坏包":
            return {"ok": False, "message": "maps.json 第3张缺 safe_zone → 已拒绝"}
        if pack == "部分失败":
            return {"ok": True, "summary": "技能 12 条 / 怪物 8 条 / 地图 5 张",
                    "failures": ["maps.json 第3张缺 safe_zone"]}
        return {"ok": True, "summary": "技能 12 条 / 怪物 8 条 / 地图 5 张", "failures": []}

    # -- G10 封禁 --
    def ban_player(self, qq_id: str, duration: str, reason: str | None, ctx: dict) -> dict:
        self.ban_calls.append((qq_id, duration, reason, ctx))
        if qq_id == "000000":
            return {"ok": False, "message": "目标不存在"}
        return {"ok": True,
                "expires": "2026-09-02 12:00" if duration != BAN_DEFAULT_DURATION else None,
                "message": "ok"}

    # -- G8 日志 --
    def recent_audit(self, count: int, ctx: dict) -> list:
        self.audit_calls.append((count, ctx))
        return self.log_events[:count]

    # -- G13 编辑 --
    def editor_link(self, level: str, ctx: dict) -> dict:
        self.editor_calls.append((level, ctx))
        hint = "机主=全功能" if level == ROLE_ADMIN else "GM=只读预览"
        return {"url": "https://editor.example.com", "hint": hint}

    # -- G14 设置 --
    def apply_setting(self, key: str, value: str, ctx: dict) -> dict:
        self.settings_calls.append((key, value, ctx))
        if key == "非法键":
            return {"ok": False, "message": "未知设置键"}
        self.settings[key] = value
        return {"ok": True, "current": value, "message": "ok"}

    # -- 审计落库（audit_store 契约）--
    def append(self, record: dict) -> None:
        self.audit_store_calls.append(record)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _backend(log_events: list | None = None) -> FakeGmBackend:
    return FakeGmBackend(log_events)


def make_ctx(**kw) -> dict:
    """默认 GM 上下文（admin / 注入替身后端 / 审计收集 / now 确定）。"""
    ctx: dict = {
        "qq_id": "10001",
        "group_id": "20001",
        "role": ROLE_ADMIN,
        "granted_commands": [],
        "gm_backend": _backend(),
        "audit_log": [],
        "now": "2026-08-26T12:00:00Z",
    }
    ctx.update(kw)
    return ctx


def p(raw: str, **kw):
    """parse_command 便捷构造。"""
    return parse_command(raw, **kw)


def audit_of(ctx: dict) -> list:
    return ctx.get("audit_log") or []


def last_audit(ctx: dict) -> dict:
    records = audit_of(ctx)
    assert records, "审计日志为空"
    return records[-1]


# ===========================================================================
# 一、L160 长清单与常量
# ===========================================================================

def test_gm_commands_long_list():
    """GM 指令清单 = L160 长清单 5 条 + M12 批3 路3A 扩展 4 条（备份/恢复/存档导出/封禁列表）。"""
    assert GM_COMMANDS == frozenset({GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG,
                                     GM_CMD_EDIT, GM_CMD_SETTINGS,
                                     GM_CMD_BACKUP, GM_CMD_RESTORE,
                                     GM_CMD_EXPORT, GM_CMD_BANLIST})
    assert set(GM_COMMAND_INDEX) == set(GM_COMMANDS)
    assert GM_COMMAND_INDEX[GM_CMD_RELOAD] == "G1"
    assert GM_COMMAND_INDEX[GM_CMD_BAN] == "G10"
    assert GM_COMMAND_INDEX[GM_CMD_LOG] == "G8"
    assert GM_COMMAND_INDEX[GM_CMD_EDIT] == "G13"
    assert GM_COMMAND_INDEX[GM_CMD_SETTINGS] == "G14"
    assert GM_COMMAND_INDEX[GM_CMD_BACKUP] == "G2"
    assert GM_COMMAND_INDEX[GM_CMD_RESTORE] == "G3"
    assert GM_COMMAND_INDEX[GM_CMD_EXPORT] == "G4"
    assert GM_COMMAND_INDEX[GM_CMD_BANLIST] == "G12"


def test_gm_command_level_default_grant():
    """每指令最低权限：重载/封禁/日志/编辑/备份/恢复/封禁列表=manager（默认授予集）；
    设置/存档导出=admin（机主专属，per-command 下授）。"""
    assert GM_COMMAND_LEVEL[GM_CMD_RELOAD] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_BAN] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_LOG] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_EDIT] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_SETTINGS] == ROLE_ADMIN
    assert GM_COMMAND_LEVEL[GM_CMD_BACKUP] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_RESTORE] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_EXPORT] == ROLE_ADMIN
    assert GM_COMMAND_LEVEL[GM_CMD_BANLIST] == ROLE_MANAGER
    assert GM_DEFAULT_GRANT == frozenset({GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG,
                                          GM_CMD_EDIT, GM_CMD_BACKUP,
                                          GM_CMD_RESTORE, GM_CMD_BANLIST})


def test_gm_prefix_required_wiring():
    """GM 前缀接线：2026-09-03 用户拍板全部指令免 / 前缀 → DEFAULT_PREFIX_REQUIRED 空集；
    GM 指令仍全在白名单（前缀后能识别）+ gm_requires_prefix() 单一事实源一致。"""
    assert set(gc.gm_requires_prefix()) == GM_COMMANDS
    # 免前缀裁决（068bcd4）：prefix_required 空集；GM 判定走 is_gm_command_name/白名单
    assert DEFAULT_PREFIX_REQUIRED == frozenset()
    assert GM_COMMANDS <= set(DEFAULT_WHITELIST)


# ===========================================================================
# 二、权限三级（5b §1.1：机主 > GM > 普通玩家；admin/manager/player 归一）
# ===========================================================================

def test_role_of_normalization():
    """角色名归一（工程补白 6）：owner/admin/机主 → admin；gm/manager → manager；
    user/player/普通玩家 → player；未知 → player（安全失败最低权限）。"""
    assert role_of("owner") == ROLE_ADMIN
    assert role_of("admin") == ROLE_ADMIN
    assert role_of("机主") == ROLE_ADMIN
    assert role_of("gm") == ROLE_MANAGER
    assert role_of("manager") == ROLE_MANAGER
    assert role_of("user") == ROLE_PLAYER
    assert role_of("player") == ROLE_PLAYER
    assert role_of("普通玩家") == ROLE_PLAYER
    assert role_of("群管理") == ROLE_PLAYER  # 未知/群管理 → 最低权限
    assert role_of(None) == ROLE_PLAYER


def test_permission_admin_all():
    """admin（机主）：全部 GM 指令放行（5b L258；TC-02 前置）。"""
    for cmd in GM_COMMANDS:
        res = check_gm_permission(GmUser("10001", role="admin"), cmd)
        assert res.ok and not res.silent and res.level == ROLE_ADMIN


def test_permission_manager_default_grant():
    """manager（GM）：默认授予集（重载/封禁/日志/编辑）放行；设置（机主专属）未下授 → 静默
    （5b §1.1.1 / TC-04）。"""
    u = GmUser("10002", role="gm")
    for cmd in (GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG, GM_CMD_EDIT):
        res = check_gm_permission(u, cmd)
        assert res.ok and res.level == ROLE_MANAGER
    res = check_gm_permission(u, GM_CMD_SETTINGS)
    assert not res.ok and res.silent  # 未下授 → 静默（TC-04）


def test_permission_manager_granted_settings():
    """manager + per-command 下授「设置」→ 放行且 granted 标记（5b §1.1.1 可另行下授）。"""
    u = GmUser("10002", role="manager", granted_commands=[GM_CMD_SETTINGS])
    res = check_gm_permission(u, GM_CMD_SETTINGS)
    assert res.ok and res.level == ROLE_MANAGER and res.granted


def test_permission_player_silent():
    """player（普通玩家）：发 GM 指令 → 静默（TC-01：零出站零审计，防暴露存在）。"""
    for cmd in GM_COMMANDS:
        res = check_gm_permission(GmUser("10003", role="user"), cmd)
        assert not res.ok and res.silent


def test_permission_priority_admin_over_manager():
    """判定优先级 机主 > GM：同一 gm 角色但 granted 空 → 设置静默；admin 同名 → 放行。"""
    gm = check_gm_permission(GmUser("10004", role="gm"), GM_CMD_SETTINGS)
    admin = check_gm_permission(GmUser("10004", role="owner"), GM_CMD_SETTINGS)
    assert not gm.ok and gm.silent
    assert admin.ok and admin.level == ROLE_ADMIN


def test_permission_non_gm_command():
    """非 GM 指令 → 静默（本模块不处理）。"""
    res = check_gm_permission(GmUser("10001", role="admin"), "攻击")
    assert not res.ok and res.silent


# ===========================================================================
# 三、静默执行（成功不回显；无权限零出站零审计）
# ===========================================================================

def test_authorized_success_silent_no_echo():
    """有权限成功 → 静默执行：message=None（不回显成功），摘要入 audit.detail
    （父任务「静默执行（不回显成功）」+ 5b §4.2 detail=成功摘要）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/重载 内容包X"), ctx)
    assert isinstance(res, GmResult)
    assert res.ok and not res.silent
    assert res.message is None  # 不回显成功
    rec = res.audit
    assert rec is not None
    assert rec["result"] == "success"
    assert "已重载【内容包X】" in rec["detail"]
    assert "技能 12 条" in rec["detail"]
    # 留痕进 ctx["audit_log"]（纯逻辑收集）
    assert last_audit(ctx) is rec


def test_no_permission_total_silent():
    """无权限（player）→ 零出站零审计：message=None、audit=None、audit_log 无新增（TC-01/24）。"""
    ctx = make_ctx(role="player")
    res = handle_gm_command(p("/重载 内容包X"), ctx)
    assert res.silent and res.message is None and res.audit is None
    assert audit_of(ctx) == []


def test_silent_result_factory():
    r = silent_result()
    assert isinstance(r, GmResult)
    assert not r.ok and r.silent and r.message is None and r.audit is None


# ===========================================================================
# 四、留痕（5b §4：审计字段 / 成败皆写 / 无权限不写 / HMAC）
# ===========================================================================

def test_build_audit_record_fields():
    """5b §4.2 审计记录字段：id/ts/qq/group_id/command/params/target_qq/result/detail/ref/
    audit_ts_hmac；params 截断 200；group_id 缺省 0（私聊）。"""
    rec = build_audit_record(qq="10001", group_id="20001", command=GM_CMD_BAN,
                             params="123456 7天 原因=刷屏", target_qq="123456",
                             result="success", detail="❌ 已封禁", ref="123456",
                             now="2026-08-26T12:00:00Z")
    assert rec["id"]
    assert rec["ts"] == "2026-08-26T12:00:00Z"
    assert rec["qq"] == "10001" and rec["group_id"] == "20001"
    assert rec["command"] == GM_CMD_BAN and rec["result"] == "success"
    assert rec["target_qq"] == "123456" and rec["ref"] == "123456"
    assert rec["params"] == "123456 7天 原因=刷屏"
    rec2 = build_audit_record(qq="10001", command=GM_CMD_RELOAD, result="failed",
                              params="x" * 250, now="t")
    assert rec2["group_id"] == "0"  # 私聊=0
    assert len(rec2["params"]) == 201 and rec2["params"].endswith("…")  # 截断 200 + …

def test_audit_hmac_deterministic_and_tamper():
    """audit_ts_hmac（防篡改）：同记录同 key 同值；改字段 → 值变；空 key → 不启用。"""
    base = {"ts": "t", "qq": "1", "group_id": "0", "command": "重载", "params": "",
            "target_qq": None, "result": "success", "detail": "d", "ref": None}
    h1 = audit_hmac(base, "secret")
    h2 = audit_hmac(base, "secret")
    assert h1 == h2 and len(h1) == 64  # SHA256 hex
    tampered = dict(base, result="failed")
    assert audit_hmac(tampered, "secret") != h1
    assert audit_hmac(base, "") == ""
    assert audit_hmac(base, "other") != h1


def test_record_audit_collect_and_store():
    """record_audit：追加 ctx["audit_log"] + 落库 ctx["audit_store"].append（追加写不可删）。"""
    store = []
    ctx = make_ctx()
    ctx["audit_store"] = store
    rec = build_audit_record(qq="1", command="重载", result="success", now="t")
    record_audit(ctx, rec)
    assert audit_of(ctx) == [rec]
    assert store == [rec]  # 落库
    # 追加写：第二条不覆盖第一条
    rec2 = build_audit_record(qq="1", command="封禁", result="failed", now="t")
    record_audit(ctx, rec2)
    assert audit_of(ctx) == [rec, rec2]
    assert store == [rec, rec2]


def test_success_and_failure_both_audited():
    """成败皆留痕（TC-28）：成功（重载）与失败（缺参）都写审计，result 正确区分。"""
    ctx = make_ctx()
    r_ok = handle_gm_command(p("/重载 内容包X"), ctx)
    r_fail = handle_gm_command(p("/重载"), ctx)
    assert r_ok.audit["result"] == "success"
    assert r_fail.audit["result"] == "failed"
    assert [a["result"] for a in audit_of(ctx)] == ["success", "failed"]


# ===========================================================================
# 五、G1 重载
# ===========================================================================

def test_reload_success_silent():
    ctx = make_ctx()
    res = handle_gm_command(p("/重载 内容包X"), ctx)
    assert res.ok and res.message is None
    assert "已重载【内容包X】" in res.audit["detail"]
    assert "技能 12 条 / 怪物 8 条 / 地图 5 张" in res.audit["detail"]
    assert ctx["gm_backend"].reload_calls[0][0] == "内容包X"


def test_reload_failures_listed_in_detail():
    """重载含失败项 → 摘要列出失败项并拒绝（5b G1 失败项逐条列出）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/重载 部分失败"), ctx)
    assert res.ok and "失败 1 项" in res.audit["detail"]
    assert "maps.json 第3张缺 safe_zone" in res.audit["detail"]


def test_reload_missing_arg_tpl12():
    """缺参 /重载 → 统一错误模板三要素 + 审计 result=failed（TC-10）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/重载"), ctx)
    assert not res.ok and not res.silent
    assert res.message == format_tpl12("/重载")
    assert "❌" in res.message and "/帮助" in res.message
    assert res.audit["result"] == "failed"
    assert "缺参" in res.audit["detail"]


def test_reload_too_many_args_tpl12():
    ctx = make_ctx()
    res = handle_gm_command(p("/重载 包A 包B"), ctx)
    assert not res.ok and "超参" in res.audit["detail"]
    assert res.message.startswith("❌")


def test_reload_bad_pack_tpl12():
    """重载不存在/坏包 → 错误模板列出失败项并拒绝；审计 failed（TC-11）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/重载 坏包"), ctx)
    assert not res.ok
    assert "safe_zone" in res.audit["detail"]
    assert res.audit["result"] == "failed"


def test_reload_parser_error_audit_failed():
    """解析错误（如未知分隔符）→ TPL-12 + 审计 failed。"""
    ctx = make_ctx()
    parsed = p("/重载 内容包&")
    assert parsed.command == GM_CMD_RELOAD
    res = handle_gm_command(parsed, ctx)
    assert not res.ok and res.audit["result"] == "failed"


# ===========================================================================
# 六、G10 封禁
# ===========================================================================

def test_ban_success_audit_e4():
    """/封禁 123456 7天 原因=刷屏（GM，默认授予集含封禁）→ 静默成功；审计 E4 行四要素：
    qq（谁封的）/ts（何时）/到期（何时到期）/原因（TC-03/TC-27）。"""
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/封禁 123456 7天 原因=刷屏"), ctx)
    assert res.ok and res.message is None  # 静默执行
    rec = res.audit
    assert rec["result"] == "success"
    assert rec["target_qq"] == "123456"
    assert rec["qq"] == "10001"  # 谁封的
    assert rec["ts"] == "2026-08-26T12:00:00Z"  # 何时
    assert "到期 2026-09-02 12:00" in rec["detail"]  # 何时到期
    assert "原因：刷屏" in rec["detail"]
    assert "（7天）" in rec["detail"]
    assert ctx["gm_backend"].ban_calls[0][:3] == ("123456", "7天", "刷屏")


def test_ban_default_permanent():
    """时长缺省 = 永久（5b G10 默认永久）。"""
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/封禁 123456"), ctx)
    assert res.ok
    assert "（永久）" in res.audit["detail"]
    assert "到期" not in res.audit["detail"]
    assert ctx["gm_backend"].ban_calls[0][1] == BAN_DEFAULT_DURATION


def test_ban_missing_arg_tpl12():
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/封禁"), ctx)
    assert not res.ok and res.message == format_tpl12("/封禁")
    assert res.audit["result"] == "failed" and "缺参" in res.audit["detail"]


def test_ban_invalid_qq_tpl12():
    """QQ 号非纯数字 → TPL-12（参数级错误，命令本身合法）。"""
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/封禁 abc"), ctx)
    assert not res.ok and "纯数字" in res.audit["detail"]
    assert res.message.startswith("❌")


def test_ban_backend_failure_tpl12():
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/封禁 000000"), ctx)
    assert not res.ok and "目标不存在" in res.audit["detail"]
    assert res.audit["result"] == "failed"


def test_ban_no_permission_silent():
    """普通玩家发 /封禁 → 静默（TC-01 口径；群管理不自动授予 TC-05 口径）。"""
    ctx = make_ctx(role="player")
    res = handle_gm_command(p("/封禁 123456"), ctx)
    assert res.silent and res.audit is None and audit_of(ctx) == []


# ===========================================================================
# 七、G8 日志（GM 版 = 系统日志；5 条/页 + TPL-08 + 裁决②）
# ===========================================================================

def test_log_gm_view_default_page():
    """/日志（GM 版）→ 系统日志最近事件：5 条/页 + TPL-08 页脚（5b G8 / m4 §2.2）。"""
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
    res = handle_gm_command(p("/日志"), ctx)
    assert res.ok and res.message is not None  # 查询类：返回请求数据（非成功回显）
    body = res.message
    assert "[12:00:00] G1 /重载" in body and "success by 10001" in body
    assert body.count("内容包X") == LOG_PAGE_SIZE  # 5 条/页
    assert "— 第 1/3 页 · 共 12 条 · 输入 /日志 页码 翻页 —" in body
    assert "系统日志" in res.audit["detail"]  # /日志 自身也写审计（5b §2）


def test_log_page_2():
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
    res = handle_gm_command(p("/日志 2"), ctx)
    assert res.ok
    assert "— 第 2/3 页 · 共 12 条 · 输入 /日志 页码 翻页 —" in res.message


def test_log_window_kv_default_and_max():
    """/日志 条数=N：默认 20；上限 50（sys_log.max_entries，细化_0 R-02）——超上限夹取 50。"""
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(30)))
    res = handle_gm_command(p("/日志 条数=30"), ctx)
    assert ctx["gm_backend"].audit_calls[0][0] == 30
    assert "共 30 条" in res.message
    ctx2 = make_ctx(role="gm", gm_backend=_backend(_events(60)))
    res2 = handle_gm_command(p("/日志 条数=100"), ctx2)
    assert ctx2["gm_backend"].audit_calls[0][0] == LOG_MAX_ENTRIES  # 50
    assert "共 50 条" in res2.message


def test_log_page_clamped_last_page():
    """页码超总页数 → 夹取最后一页 +「已到最后一页」（裁决②）。"""
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
    res = handle_gm_command(p("/日志 9"), ctx)
    assert res.ok
    assert "— 第 3/3 页 · 共 12 条" in res.message  # 夹取到最后一页
    assert "（已到最后一页）" in res.message


def test_log_invalid_page_tpl12():
    """/日志 0/负数/非数字 → TPL-12（裁决②）。"""
    for raw in ("/日志 0", "/日志 -1", "/日志 abc"):
        ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
        res = handle_gm_command(p(raw), ctx)
        assert not res.ok and res.audit["result"] == "failed"
        assert res.message.startswith("❌")


def test_log_invalid_count_tpl12():
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/日志 条数=abc"), ctx)
    assert not res.ok and "条数" in res.audit["detail"]
    assert res.message.startswith("❌")


def test_log_empty():
    ctx = make_ctx(role="gm", gm_backend=_backend([]))
    res = handle_gm_command(p("/日志"), ctx)
    assert res.ok and res.message == "（暂无系统日志）"


def test_render_log_line_format():
    """单条审计事件行（5b G8 分行）：[HH:MM:SS] G8 /日志 条数=20 成功 by 10001。"""
    rec = {"ts": "2026-08-26T12:34:56Z", "qq": "10001", "command": GM_CMD_LOG,
           "params": "条数=20", "result": "success"}
    assert render_log_line(rec) == "[12:34:56] G8 /日志 条数=20 success by 10001"


# ===========================================================================
# 八、G13 编辑 / G14 设置
# ===========================================================================

def test_edit_returns_link_with_role_hint():
    """/编辑 → 编辑器链接 + 权限级提示（5b G13：机主=全功能，GM=只读预览）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/编辑"), ctx)
    assert res.ok and "editor.example.com" in res.message
    assert "机主=全功能" in res.message
    assert res.audit["result"] == "success"
    ctx_gm = make_ctx(role="gm")
    res2 = handle_gm_command(p("/编辑"), ctx_gm)
    assert "GM=只读预览" in res2.message


def test_edit_extra_args_tpl12():
    ctx = make_ctx()
    res = handle_gm_command(p("/编辑 3"), ctx)
    assert not res.ok and "超参" in res.audit["detail"]


def test_settings_admin_switch():
    """/设置 command_mode=global_shortcut（机主）→ 静默成功，新值摘要入 audit.detail（5b G14）。"""
    ctx = make_ctx()
    res = handle_gm_command(p("/设置 command_mode=global_shortcut"), ctx)
    assert res.ok and res.message is None  # 静默执行
    assert "command_mode：global_shortcut" in res.audit["detail"]
    assert ctx["gm_backend"].settings == {"command_mode": "global_shortcut"}


def test_settings_owner_only_silent_for_manager():
    """/设置 机主专属：manager 未下授 → 静默（TC-04 口径）。"""
    ctx = make_ctx(role="gm")
    res = handle_gm_command(p("/设置 command_mode=global_shortcut"), ctx)
    assert res.silent and res.audit is None and audit_of(ctx) == []
    # manager + 下授 → 放行
    ctx2 = make_ctx(role="gm", granted_commands=[GM_CMD_SETTINGS])
    res2 = handle_gm_command(p("/设置 command_mode=prefix_only"), ctx2)
    assert res2.ok


def test_settings_missing_arg_tpl12():
    ctx = make_ctx()
    res = handle_gm_command(p("/设置"), ctx)
    assert not res.ok and "缺参" in res.audit["detail"]
    assert res.message == format_tpl12("/设置")


def test_settings_unknown_key_tpl12():
    ctx = make_ctx()
    res = handle_gm_command(p("/设置 非法键=1"), ctx)
    assert not res.ok and "未知设置键" in res.audit["detail"]


# ===========================================================================
# 九、GM 禁绑（5b §3.2 C02 / 规范 L160-161，防权限绕过）
# ===========================================================================

def test_is_gm_command_name():
    assert is_gm_command_name(GM_CMD_RELOAD)
    assert is_gm_command_name("/重载")  # 剥离 / 后判定
    assert not is_gm_command_name("攻击")
    assert not is_gm_command_name("")


def test_binding_guard_rejects_gm_command():
    """绑定目标为 GM 指令 → 绑定层拒绝（TC-23：『重载』是 GM 指令，不可绑定为快捷）。"""
    v = gm_binding_guard("R", "重载 内容包X")
    assert not v["ok"] and v["code"] == "gm_forbidden"
    assert "『重载』是 GM 指令，不可绑定为快捷" in v["message"]
    v2 = gm_binding_guard("s", "/设置 command_mode=x")
    assert not v2["ok"] and v2["code"] == "gm_forbidden"
    assert "『设置』是 GM 指令" in v2["message"]


def test_binding_guard_allows_player_shortcut():
    """绑定目标为游玩指令 → 正常放行（TC-25：快捷只对本人游玩指令）。"""
    v = gm_binding_guard("奶", "使用 治疗药水*2")
    assert v["ok"] and v["code"] == "ok"


def test_execution_layer_second_check_bypass():
    """绕过模拟（TC-24）：快捷表被写入脏数据 {r: /封禁 123456} 后发 r →
    执行层权限二次检查拦截：player 角色 → 零出站零审计零副作用。"""
    ctx = make_ctx(role="player")
    parsed = p("/封禁 123456")  # 等价于展开后的完整指令串
    res = handle_gm_command(parsed, ctx)
    assert res.silent and res.audit is None
    assert ctx["gm_backend"].ban_calls == []  # 零副作用


# ===========================================================================
# 十、GM 强制 / 前缀（路由层 W07/L128 + is_gm 二次检查位 E02）
# ===========================================================================

def test_router_bare_gm_ignored_prefix_required():
    """裸发 GM 指令（无 /）→ 路由层忽略（gm_requires_prefix，W07/L128）。"""
    r = Router()
    register_gm_commands(r)
    res = r.dispatch("重载 内容包X")
    assert res.kind == ROUTE_IGNORED and res.reason == "gm_requires_prefix"


def test_router_prefixed_gm_recognized_and_is_gm():
    """带 / 前缀 → 路由命中 + is_gm 二次检查位（E02）。"""
    r = Router()
    register_gm_commands(r)
    res = r.dispatch("/封禁 123456")
    assert res.kind == ROUTE_COMMAND and res.command == GM_CMD_BAN
    assert res.is_gm is True
    assert res.spec.permission == PERM_GM


def test_router_shortcut_never_triggers_gm_bare():
    """GM 指令即使被快捷绑定也不执行（绑定层拦截 + 执行层二次检查，TC-24/规范 L171）：
    快捷展开后目标为 GM 指令且无 / → 路由仍忽略。"""
    r = Router()
    register_gm_commands(r)
    # 直写脏快捷表：r → 重载（绕过绑定层模拟）
    res = r.dispatch("r", {"registry": r, "shortcuts": {"r": "重载 内容包X"},
                           "command_mode": "global_shortcut"})
    assert res.kind == ROUTE_IGNORED


# ===========================================================================
# 十一、注册与解析接线 / 待接线防御
# ===========================================================================

def test_register_gm_commands_specs():
    """register_gm_commands：注册 5 条 GM 指令，is_gm=True、permission 按 GM_COMMAND_LEVEL
    映射（PERM_OWNER/PERM_GM）、handler 返回 GmResult。"""
    r = Router()
    register_gm_commands(r)
    assert set(r.gm_commands()) == set(GM_COMMANDS)
    assert r.get(GM_CMD_RELOAD).permission == PERM_GM
    assert r.get(GM_CMD_SETTINGS).permission == PERM_OWNER
    assert all(s.is_gm for s in [r.get(c) for c in GM_COMMANDS])


def test_register_make_context_wiring():
    """装配接线：make_context 注入 → handler 走完整管线（权限/静默/留痕）；缺失 → 【待接线】。"""
    r = Router()
    ctx_holder = {}

    def make_context(parsed):
        ctx = make_ctx(role="admin")
        ctx_holder["parsed"] = parsed
        return ctx

    register_gm_commands(r, make_context=make_context)
    gm = r.get(GM_CMD_RELOAD).handler(parse_command("/重载 内容包X"))
    assert isinstance(gm, GmResult) and gm.ok and gm.audit is not None
    assert ctx_holder["parsed"].command == GM_CMD_RELOAD

    # make_context 缺失 → 调用抛 RuntimeError【待接线】
    r2 = Router()
    register_gm_commands(r2)
    with pytest.raises(RuntimeError, match="待接线"):
        r2.get(GM_CMD_RELOAD).handler(parse_command("/重载 内容包X"))


def test_backend_missing_todo():
    """gm_backend 未注入 → 处理器抛 RuntimeError【待接线】（防御路径，不阻塞导入）。"""
    ctx = make_ctx()
    del ctx["gm_backend"]
    with pytest.raises(RuntimeError, match="待接线"):
        cmd_gm_reload(p("/重载 内容包X"), ctx, GmPermResult(ok=True, level=ROLE_ADMIN))


def test_permission_store_injection():
    """permission_store 注入（5b §1.2 admin_users 表消费接口）：user_of(qq_id) → GmUser。"""
    class FakeStore:
        def __init__(self):
            self.map = {"10001": ("owner", [])}
        def user_of(self, qq):
            v = self.map.get(str(qq))
            return GmUser(qq, role=v[0], granted_commands=v[1]) if v else GmUser(qq)

    ctx = make_ctx(role="player")  # ctx role 故意最低；权限唯一事实来源 = store
    ctx["permission_store"] = FakeStore()
    res = handle_gm_command(p("/重载 内容包X"), ctx)
    assert res.ok  # store 判 owner → 放行（存档不内联权限，5b §1.2）


# ===========================================================================
# 十二、渲染 / emoji 纪律 / 页脚 TPL-08
# ===========================================================================

def test_log_page_footer_exact():
    """页脚固定 TPL-08 逐字：— 第 X/Y 页 · 共 N 条 · 输入 /日志 页码 翻页 —（禁止自造）。"""
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
    body = handle_gm_command(p("/日志"), ctx).message
    assert "— 第 1/3 页 · 共 12 条 · 输入 /日志 页码 翻页 —" in body
    # 单页（≤5 条）无页脚（3d D-02 防刷屏）
    ctx1 = make_ctx(role="gm", gm_backend=_backend(_events(3)))
    body1 = handle_gm_command(p("/日志"), ctx1).message
    assert "— 第" not in body1


def test_no_decorative_emoji():
    """M5 裁决不用 emoji：列表行/页脚/错误纯文本（仅 ✅/❌ 功能性标记 + 排版符号）；
    GM 结果前缀（🚫/⚙️/📝 等数据型功能图标）已降级——封禁行用 ❌，日志/编辑/设置无前缀。"""
    ctx = make_ctx(role="gm", gm_backend=_backend(_events(12)))
    body = handle_gm_command(p("/日志"), ctx).message
    assert "✅" not in body and "❌" not in body  # 列表骨架为纯文本（功能性标记不属列表）
    err = handle_gm_command(p("/重载"), make_ctx()).message
    assert "❌" in err  # 功能性标记保留
    ban = handle_gm_command(p("/封禁 123456 7天 原因=刷屏"), make_ctx(role="gm")).audit["detail"]
    assert "❌" in ban  # 封禁行降级为 ❌ 功能性标记（M5 裁决）
    assert "🚫" not in ban and "⚙️" not in ban and "📝" not in ban  # 数据型图标已降级


def test_render_log_page_plain_helpers():
    """渲染纯函数：render_log_line / render_log_page 可直接单测。"""
    events = _events(6)
    page = render_log_page(events, 1)
    assert "内容包X" in page and "— 第 1/2 页 · 共 6 条 · 输入 /日志 页码 翻页 —" in page
    assert render_log_page([], 1) == "（暂无系统日志）"
