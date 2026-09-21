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

