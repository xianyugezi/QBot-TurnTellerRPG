"""批75 · GM 运维 5 条指令接线单测（/调试 G5 · /测试 G6 · /广播 G7 · /玩家查询 G9 · /解封 G11）。

依据：`docs/指令清单_全量.md` G 节（逐条设计口径）+ `docs/细化/细化_5b_GM指令契约.md` §2.1
总表（G5 L93/G6 L94/G7 L95/G9 L97/G11 L99）+ §2.2 逐条契约 + `/root/deliverables/X11_未实现
指令盘点.md` §1.5（GM 运维系：5 条登记但未实现，权限门/审计码已预置）。

覆盖（逐条对齐验收口径）：
  · 常量/注册：GM_COMMANDS / GM_COMMAND_INDEX（G5/G6/G7/G9/G11）/ GM_COMMAND_LEVEL
    （4 条机主专属 admin + 解封 manager）/ _HANDLERS / parsers 白名单双向一致
  · 权限：机主放行；GM 默认集只含解封；机主专属未下授 → 静默零审计（既有权限门，TC-04）
  · /调试：开关两态（开→关）+ 状态回显；超参 TPL-12；后端缺失降级
  · /测试：只读冒烟（跑前后内容目录快照零变化）；失败 → 错误模板列首条失败项
  · /广播：正常推送（群/私聊计数）；超 200 字被拦；缺参 TPL-12；后端缺失降级
  · /玩家查询：脱敏摘要（QQ 打码、无背包/敏感明细）；不存在玩家 → 人话错误模板
  · /解封：在名单 → 解封成功 + 审计；不在名单 → 错误模板（含 /封禁列表 指引）
  · 审计：每条成败皆写（E3 广播 / E4 解封 / E6 系统事件兜底），无权限不写

铁律：零 NoneBot import；纯 pytest；临时目录/临时内容根；无 emoji。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import qbot_rpg.commands.gm_commands as gc
from qbot_rpg.commands.gm_commands import (
    GM_CMD_DEBUG,
    GM_COMMANDS,
    GM_COMMAND_INDEX,
    GM_COMMAND_LEVEL,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_PLAYER,
    GmBackend,
    GmUser,
    check_gm_permission,
    handle_gm_command,
    silent_result,
)
from qbot_rpg.commands.parsers import (
    DEFAULT_GM_COMMANDS,
    DEFAULT_WHITELIST,
    parse_command,
)

# =============================================================================
# 夹具
# =============================================================================

def _parsed(raw: str) -> Any:
    return parse_command(raw)


def _ctx(role: str = ROLE_ADMIN, backend: Any = None, **kw: Any) -> dict:
    """GM 处理器 ctx（now 确定；audit_log 收集）。"""
    ctx: dict = {
        "qq_id": "10001",
        "group_id": "20001",
        "role": role,
        "granted_commands": [],
        "gm_backend": backend,
        "audit_log": [],
        "now": "2026-09-23T12:00:00Z",
    }
    ctx.update(kw)
    return ctx


def _last(ctx: dict) -> dict:
    return (ctx.get("audit_log") or [])[-1]


def _digest_files(root: Path) -> dict:
    """目录内容快照（相对路径 → sha256），用于「只读」前后对拍。"""
    out: dict = {}
    if not root.is_dir():
        return out
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# =============================================================================
# 常量与注册（5 条）
# =============================================================================

def test_g5_constants_and_registry() -> None:
    """/调试 G5 在 GM_COMMANDS/INDEX/LEVEL/白名单/处理器表。"""
    assert GM_CMD_DEBUG in GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_DEBUG] == "G5"
    assert GM_COMMAND_LEVEL[GM_CMD_DEBUG] == ROLE_ADMIN
    assert GM_CMD_DEBUG in DEFAULT_WHITELIST
    assert GM_CMD_DEBUG in DEFAULT_GM_COMMANDS
    assert gc._HANDLERS[GM_CMD_DEBUG] is gc.cmd_gm_debug
    assert _parsed("/调试").command == GM_CMD_DEBUG


# =============================================================================
# 权限（机主专属可下授；走既有权限门）
# =============================================================================

def test_g5_permission_owner_only_grantable() -> None:
    """机主放行；GM 未下授 → 静默；GM 下授后放行（5b §1.1.1）。"""
    owner = GmUser("10001", role=ROLE_ADMIN)
    assert check_gm_permission(owner, GM_CMD_DEBUG).ok
    gm = GmUser("10002", role=ROLE_MANAGER)
    res = check_gm_permission(gm, GM_CMD_DEBUG)
    assert not res.ok and res.silent
    gm2 = GmUser("10002", role=ROLE_MANAGER, granted_commands=[GM_CMD_DEBUG])
    res2 = check_gm_permission(gm2, GM_CMD_DEBUG)
    assert res2.ok and res2.granted


def test_g5_player_silent_zero_audit() -> None:
    """普通玩家 → 静默零出站零审计（既有权限门，非自定义拒绝）。"""
    ctx = _ctx(ROLE_PLAYER, backend=GmBackend())
    r = handle_gm_command(_parsed("/调试"), ctx)
    assert r == silent_result() or (r.silent and not r.ok)
    assert r.audit is None
    assert ctx["audit_log"] == []


# =============================================================================
# /调试：开关两态 + 状态显示
# =============================================================================

def test_g5_toggle_two_states() -> None:
    """无参开关：第一次「开」、第二次「关」；审计 success + 状态入消息。"""
    backend = GmBackend()
    ctx = _ctx(ROLE_ADMIN, backend=backend)
    r1 = handle_gm_command(_parsed("/调试"), ctx)
    assert r1.ok and "调试模式：开" in r1.message
    assert "日志级别：DEBUG" in r1.message
    assert _last(ctx)["command"] == GM_CMD_DEBUG
    assert _last(ctx)["result"] == "success"
    r2 = handle_gm_command(_parsed("/调试"), ctx)
    assert r2.ok and "调试模式：关" in r2.message
    assert "日志级别：INFO" in r2.message
    assert backend._debug_enabled is False


def test_g5_extra_args_rejected() -> None:
    """超参 → TPL-12 + 审计 failed。"""
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend())
    r = handle_gm_command(_parsed("/调试 开"), ctx)
    assert not r.ok and not r.silent
    assert "指令不正确" in (r.message or "")
    assert _last(ctx)["result"] == "failed"


def test_g5_no_backend_degrades() -> None:
    """GM 后端未装配 → 人话 failed 不崩 + 审计 failed。"""
    ctx = _ctx(ROLE_ADMIN, backend=None)
    r = handle_gm_command(_parsed("/调试"), ctx)
    assert not r.ok and not r.silent
    assert _last(ctx)["result"] == "failed"
    assert "后端未装配" in _last(ctx)["detail"]


def test_g5_message_is_templated() -> None:
    """输出走模板表（禁 emoji；含 {state}/{level}/{result} 三占位）。"""
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES

    tpl = DEFAULT_TEMPLATES["gm_debug_status"]
    assert "{state}" in tpl and "{level}" in tpl and "{result}" in tpl


# =============================================================================
# /测试 G6：只读冒烟
# =============================================================================

class _FakeRouter:
    def __init__(self, names: list) -> None:
        self._names = list(names)

    def names(self) -> list:
        return list(self._names)


def test_g6_constants_and_registry() -> None:
    """/测试 G6 在 GM_COMMANDS/INDEX/LEVEL/白名单/处理器表。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_TEST

    assert GM_CMD_TEST in GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_TEST] == "G6"
    assert GM_COMMAND_LEVEL[GM_CMD_TEST] == ROLE_ADMIN
    assert GM_CMD_TEST in DEFAULT_WHITELIST
    assert GM_CMD_TEST in DEFAULT_GM_COMMANDS
    assert gc._HANDLERS[GM_CMD_TEST] is gc.cmd_gm_test
    assert _parsed("/测试").command == GM_CMD_TEST


def test_g6_smoke_passes_readonly(tmp_path: Path) -> None:
    """正常配置 → 冒烟通过；跑前后内容目录逐文件 sha256 零变化（只读铁证）。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_TEST

    cdir = tmp_path / "content"
    cdir.mkdir()
    (cdir / "enemies.json").write_text(json.dumps([{"id": "wolf"}]), encoding="utf-8")
    (cdir / "maps.json").write_text(json.dumps([{"id": "m1"}]), encoding="utf-8")
    before = _digest_files(cdir)
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(),
               content_dir=str(cdir), router=_FakeRouter(["a", "b", "c"]))
    r = handle_gm_command(_parsed("/测试"), ctx)
    after = _digest_files(cdir)
    assert before == after, "只读冒烟不得改动内容目录"
    assert r.ok and "冒烟通过" in r.message
    assert _last(ctx)["command"] == GM_CMD_TEST
    assert _last(ctx)["result"] == "success"


def test_g6_smoke_failure_lists_first(tmp_path: Path) -> None:
    """坏 JSON → 冒烟失败，错误模板列出首条失败项 + 审计 failed。（只读不改）"""
    cdir = tmp_path / "content"
    cdir.mkdir()
    (cdir / "broken.json").write_text("{not-json", encoding="utf-8")
    before = _digest_files(cdir)
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(),
               content_dir=str(cdir), router=_FakeRouter(["a"]))
    r = handle_gm_command(_parsed("/测试"), ctx)
    assert _digest_files(cdir) == before
    assert not r.ok and not r.silent
    assert "冒烟失败" in r.message and "broken.json" in r.message
    assert _last(ctx)["result"] == "failed"


def test_g6_player_silent_and_no_backend() -> None:
    """普通玩家静默零审计；机主 + 无后端 → 降级 failed。"""
    ctx_p = _ctx(ROLE_PLAYER, backend=GmBackend())
    rp = handle_gm_command(_parsed("/测试"), ctx_p)
    assert rp.silent and ctx_p["audit_log"] == []
    ctx_o = _ctx(ROLE_ADMIN, backend=None)
    ro = handle_gm_command(_parsed("/测试"), ctx_o)
    assert not ro.ok and _last(ctx_o)["result"] == "failed"


def test_g6_message_is_templated() -> None:
    """通过/失败均走模板表（禁 emoji）。"""
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES

    assert "{successes}" in DEFAULT_TEMPLATES["gm_test_pass"]
    assert "{reason}" in DEFAULT_TEMPLATES["gm_test_fail"]


# =============================================================================
# /广播 G7：≤200 字 + 定时缺口
# =============================================================================

def test_g7_constants_and_registry() -> None:
    """/广播 G7 在 GM_COMMANDS/INDEX/LEVEL/白名单/自由参数/处理器表。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_BROADCAST
    from qbot_rpg.commands.parsers import DEFAULT_FREE_ARG_COMMANDS

    assert GM_CMD_BROADCAST in GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_BROADCAST] == "G7"
    assert GM_COMMAND_LEVEL[GM_CMD_BROADCAST] == ROLE_ADMIN
    assert GM_CMD_BROADCAST in DEFAULT_WHITELIST
    assert GM_CMD_BROADCAST in DEFAULT_GM_COMMANDS
    assert GM_CMD_BROADCAST in DEFAULT_FREE_ARG_COMMANDS
    assert gc._HANDLERS[GM_CMD_BROADCAST] is gc.cmd_gm_broadcast
    assert _parsed("/广播 通知").command == GM_CMD_BROADCAST


def test_g7_push_ok_multiword() -> None:
    """正常即时广播：多词消息合并且完整送达公告通道 + 计数回显 + 审计 success。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_BROADCAST

    calls: list = []

    def _announce(text: str, schedule: Any = None, groups: Any = None) -> dict:
        calls.append((text, schedule, groups))
        return {"groups": 5, "dms": 12, "message": "ok"}

    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), announce=_announce)
    r = handle_gm_command(_parsed("/广播 系统 维护 通知"), ctx)
    assert r.ok, r
    assert calls and calls[0][0] == "系统 维护 通知"
    assert calls[0][1] is None  # 定时未接线 → schedule=None（不做假调度）
    assert "群 5" in r.message and "私聊 12" in r.message
    assert _last(ctx)["command"] == GM_CMD_BROADCAST
    assert _last(ctx)["result"] == "success"
    assert _last(ctx)["params"] == "系统 维护 通知"


def test_g7_oversize_blocked() -> None:
    """超 200 字被拦（领域错误模板 + 审计 failed + 零推送）。"""
    from qbot_rpg.commands.gm_commands import BROADCAST_MAX_CHARS

    calls: list = []
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(),
               announce=lambda *a, **k: calls.append(a) or {"groups": 1, "dms": 0})
    long_msg = "字" * (BROADCAST_MAX_CHARS + 1)
    r = handle_gm_command(_parsed("/广播 " + long_msg), ctx)
    assert not r.ok and not r.silent
    assert f"{BROADCAST_MAX_CHARS + 1}/{BROADCAST_MAX_CHARS}" in r.message
    assert calls == [], "超长不得推送"
    assert _last(ctx)["result"] == "failed"


def test_g7_schedule_registered_as_gap() -> None:
    """含 `定时=` → 只做即时广播 + 结果附「暂不支持（已登记）」缺口说明。"""
    calls: list = []
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(),
               announce=lambda text, schedule=None, groups=None: calls.append(text)
               or {"groups": 2, "dms": 3})
    r = handle_gm_command(_parsed("/广播 通知 定时=2000"), ctx)
    assert r.ok and calls == ["通知"], "定时请求仍做即时广播"
    assert "定时=暂不支持" in r.message
    assert "定时=2000" in _last(ctx)["detail"]
    assert "定时=2000" in _last(ctx)["params"]


def test_g7_colon_syntax_rejected_by_parser() -> None:
    """设计语法 `定时=HH:MM` 的 `:` 不在 token 合法字符集 → 解析层拦（诚实拒绝，不假装）。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_BROADCAST

    p = _parsed("/广播 通知 定时=20:00")
    assert p.command == GM_CMD_BROADCAST and p.error
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(),
               announce=lambda *a, **k: {"groups": 1, "dms": 0})
    r = handle_gm_command(p, ctx)
    assert not r.ok and _last(ctx)["result"] == "failed"


def test_g7_missing_arg_and_degrade() -> None:
    """缺参 → TPL-12；机主 + 无后端 → 降级 failed；普通玩家静默。"""
    ctx1 = _ctx(ROLE_ADMIN, backend=GmBackend())
    r1 = handle_gm_command(_parsed("/广播"), ctx1)
    assert not r1.ok and "指令不正确" in r1.message
    ctx2 = _ctx(ROLE_ADMIN, backend=None)
    r2 = handle_gm_command(_parsed("/广播 通知"), ctx2)
    assert not r2.ok and "后端未装配" in _last(ctx2)["detail"]
    ctx3 = _ctx(ROLE_PLAYER, backend=GmBackend())
    r3 = handle_gm_command(_parsed("/广播 通知"), ctx3)
    assert r3.silent and ctx3["audit_log"] == []


def test_g7_messages_templated() -> None:
    """广播三条模板在表内。"""
    from qbot_rpg.core.templates import DEFAULT_TEMPLATES

    for key in ("gm_broadcast_done", "gm_broadcast_too_long", "gm_broadcast_schedule_gap"):
        assert DEFAULT_TEMPLATES.get(key), key


# =============================================================================
# /玩家查询 G9：脱敏摘要
# =============================================================================

def test_g9_constants_and_registry() -> None:
    """/玩家查询 G9 在 GM_COMMANDS/INDEX/LEVEL/白名单/处理器表。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_PLAYER_QUERY

    assert GM_CMD_PLAYER_QUERY in GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_PLAYER_QUERY] == "G9"
    assert GM_COMMAND_LEVEL[GM_CMD_PLAYER_QUERY] == ROLE_ADMIN
    assert GM_CMD_PLAYER_QUERY in DEFAULT_WHITELIST
    assert GM_CMD_PLAYER_QUERY in DEFAULT_GM_COMMANDS
    assert gc._HANDLERS[GM_CMD_PLAYER_QUERY] is gc.cmd_gm_player_query
    assert _parsed("/玩家查询 123456789").command == GM_CMD_PLAYER_QUERY


def _lookup_rich(qq: str) -> dict:
    """含敏感明细的玩家数据（用于验证字段最小化/脱敏）。"""
    return {
        "name": "阿伟",
        "level": 32,
        "currencies": {"coins": 12450, "gem": 3},
        "last_active_at": "2026-09-23T11:00:00Z",
        "banned": False,
        # 以下均为敏感字段，绝不得出现在回显
        "inventory": [{"id": "secret_sword", "qty": 1}],
        "chat": "私密气泡",
    }


def test_g9_masked_summary() -> None:
    """脱敏：QQ 中段打码、无背包/聊天明细；只出等级/货币/最近在线/封禁。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_PLAYER_QUERY

    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), player_lookup=_lookup_rich)
    r = handle_gm_command(_parsed("/玩家查询 123456789"), ctx)
    assert r.ok, r
    assert "123456789" not in r.message, "明文 QQ 不得回显"
    assert "12*****89" in r.message, r.message
    assert "Lv.32" in r.message and "coins 12450" in r.message
    assert "1 小时前" in r.message and "封禁：无" in r.message
    assert "secret_sword" not in r.message and "私密气泡" not in r.message
    # 审计 target_qq 保留全号（封禁/溯源留痕）
    assert _last(ctx)["command"] == GM_CMD_PLAYER_QUERY
    assert _last(ctx)["target_qq"] == "123456789"
    assert _last(ctx)["result"] == "success"


def test_g9_not_found_error_template() -> None:
    """不存在玩家 → 人话错误模板（非静默）+ 审计 failed + target_qq 留痕。"""
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), player_lookup=lambda qq: None)
    r = handle_gm_command(_parsed("/玩家查询 123456789"), ctx)
    assert not r.ok and not r.silent
    assert "不在册" in r.message
    assert "123456789" not in r.message
    assert _last(ctx)["target_qq"] == "123456789"
    assert _last(ctx)["result"] == "failed"


def test_g9_invalid_and_missing_args() -> None:
    """QQ 非纯数字 / 缺参 → TPL-12。"""
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), player_lookup=_lookup_rich)
    r1 = handle_gm_command(_parsed("/玩家查询 abc"), ctx)
    assert not r1.ok and "指令不正确" in r1.message
    r2 = handle_gm_command(_parsed("/玩家查询"), ctx)
    assert not r2.ok and "指令不正确" in r2.message


def test_g9_player_silent_and_no_backend() -> None:
    """普通玩家静默零审计；机主 + 无后端 → 降级 failed。"""
    ctx_p = _ctx(ROLE_PLAYER, backend=GmBackend(), player_lookup=_lookup_rich)
    rp = handle_gm_command(_parsed("/玩家查询 123456789"), ctx_p)
    assert rp.silent and ctx_p["audit_log"] == []
    ctx_o = _ctx(ROLE_ADMIN, backend=None)
    ro = handle_gm_command(_parsed("/玩家查询 123456789"), ctx_o)
    assert not ro.ok and _last(ctx_o)["result"] == "failed"


def test_g9_mask_and_ago_pure() -> None:
    """脱敏与相对时间纯函数：边界（短号/未知时间）+ 模板渲染。"""
    from qbot_rpg.commands.gm_commands import humanize_ago, mask_qq

    assert mask_qq("123456789") == "12*****89"
    assert mask_qq("1234") == "1***"
    assert mask_qq("") == ""
    assert humanize_ago(None, "2026-09-23T12:00:00Z", "2026-09-23T12:00:00Z") == "刚刚"
    assert humanize_ago(None, "2026-09-23T11:00:00Z", "2026-09-23T12:00:00Z") == "1 小时前"
    assert humanize_ago(None, "2026-09-20T12:00:00Z", "2026-09-23T12:00:00Z") == "3 天前"
    assert humanize_ago(None, "bad", "2026-09-23T12:00:00Z") == "未知"


# =============================================================================
# /解封 G11：与 /封禁 /封禁列表 成对
# =============================================================================

class _FakeBanStore:
    """封禁名单鸭子存储（unban(qq) -> bool；True=确有并移除）。"""

    def __init__(self, banned: set) -> None:
        self.banned = set(banned)

    def is_banned(self, qq: str) -> bool:
        return str(qq) in self.banned

    def unban(self, qq: str) -> bool:
        qq = str(qq)
        if qq in self.banned:
            self.banned.discard(qq)
            return True
        return False


def test_g11_constants_and_registry() -> None:
    """/解封 G11 = GM 默认授予集（与 /封禁 同档）。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_UNBAN, GM_DEFAULT_GRANT

    assert GM_CMD_UNBAN in GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_UNBAN] == "G11"
    assert GM_COMMAND_LEVEL[GM_CMD_UNBAN] == ROLE_MANAGER
    assert GM_CMD_UNBAN in GM_DEFAULT_GRANT
    assert GM_CMD_UNBAN in DEFAULT_WHITELIST
    assert GM_CMD_UNBAN in DEFAULT_GM_COMMANDS
    assert gc._HANDLERS[GM_CMD_UNBAN] is gc.cmd_gm_unban
    assert _parsed("/解封 123456789").command == GM_CMD_UNBAN


def test_g11_manager_default_grant() -> None:
    """GM（manager）默认授予集即可解封（无需下授）。"""
    gm = GmUser("10002", role=ROLE_MANAGER)
    res = check_gm_permission(gm, "解封")
    assert res.ok and not res.granted


def test_g11_unban_success() -> None:
    """在名单 → 解封成功 + 名单确实移除 + 审计 success（target_qq 留痕）。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_UNBAN

    store = _FakeBanStore({"123456789"})
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), ban_store=store)
    r = handle_gm_command(_parsed("/解封 123456789"), ctx)
    assert r.ok, r
    assert "已解封 123456789" in r.message
    assert store.banned == set()
    assert _last(ctx)["command"] == GM_CMD_UNBAN
    assert _last(ctx)["result"] == "success"
    assert _last(ctx)["target_qq"] == "123456789"


def test_g11_not_in_list_error_template() -> None:
    """不在名单 → 错误模板（含 /封禁列表 指引）+ 审计 failed + 名单不变。"""
    from qbot_rpg.commands.gm_commands import GM_CMD_UNBAN

    store = _FakeBanStore(set())
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), ban_store=store)
    r = handle_gm_command(_parsed("/解封 123456789"), ctx)
    assert not r.ok and not r.silent
    assert "不在封禁名单" in r.message and "/封禁列表" in r.message
    assert store.banned == set()
    assert _last(ctx)["command"] == GM_CMD_UNBAN
    assert _last(ctx)["result"] == "failed"
    assert _last(ctx)["target_qq"] == "123456789"


def test_g11_invalid_and_missing_args() -> None:
    """QQ 非纯数字 / 缺参 → TPL-12（不触后端）。"""
    store = _FakeBanStore({"123456789"})
    ctx = _ctx(ROLE_ADMIN, backend=GmBackend(), ban_store=store)
    for raw in ("/解封 abc", "/解封"):
        r = handle_gm_command(_parsed(raw), ctx)
        assert not r.ok and "指令不正确" in r.message, raw
    assert store.banned == {"123456789"}


def test_g11_player_silent_and_no_backend() -> None:
    """普通玩家静默零审计；机主 + 无后端 → 降级 failed（不解封）。"""
    store = _FakeBanStore({"123456789"})
    ctx_p = _ctx(ROLE_PLAYER, backend=GmBackend(), ban_store=store)
    rp = handle_gm_command(_parsed("/解封 123456789"), ctx_p)
    assert rp.silent and ctx_p["audit_log"] == [] and store.banned == {"123456789"}
    ctx_o = _ctx(ROLE_ADMIN, backend=None, ban_store=store)
    ro = handle_gm_command(_parsed("/解封 123456789"), ctx_o)
    assert not ro.ok and _last(ctx_o)["result"] == "failed"




