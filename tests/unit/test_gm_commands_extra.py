"""M12 批3 路3A：GM 4 新指令接线单测（/备份 G2 /恢复 G3 /存档导出 G4 /封禁列表 G12）。

依据：docs/细化/细化_5b_GM指令契约.md §2（G2 备份 L90/L114-116；G3 恢复 L91/L118-120；
G4 存档导出 L92/L122-125；G12 封禁列表 L100/L164-165）+ WIR-08（/备份 /恢复 真实后端
M12 批3 路3A 实装：zip + backups 表登记 / 先备份当前再覆盖）。

覆盖：
  - 常量与注册：GM_COMMANDS 含 4 新指令 / GM_COMMAND_INDEX G2/G3/G4/G12 /
    GM_COMMAND_LEVEL（备份/恢复/封禁列表=manager，存档导出=admin）/ _HANDLERS 注册存在
  - 权限：player 调用静默（零审计）；gm 调备份/恢复放行；存档导出需 admin
  - 降级：ctx 无 gm_backend → 人话 failed 不崩（旧 5 条是 RuntimeError 防御，新 4 条降级）
  - 假后端调通：注入假 GmBackend → cmd_gm_backup/restore/banlist 调后端 + 审计 success
  - GmBackend.backup_content 真实 zip（tmp content 目录 → zip 含 .json + backups 登记）
  - GmBackend.restore_content 真实恢复（先备份当前再覆盖）
  - parsers 白名单含 4 新指令（parse_command 能识别）

铁律：零 NoneBot import；纯 pytest；全中文注释；无 emoji（✅ 功能性标记豁免已有先例，
     新测试尽量纯文本）。
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from typing import Any

import qbot_rpg.commands.gm_commands as gc
from qbot_rpg.commands.gm_commands import (
    GM_CMD_BACKUP,
    GM_CMD_BANLIST,
    GM_CMD_EXPORT,
    GM_CMD_RESTORE,
    GM_COMMANDS,
    GM_COMMAND_INDEX,
    GM_COMMAND_LEVEL,
    ROLE_ADMIN,
    ROLE_MANAGER,
    ROLE_PLAYER,
    GmBackend,
    cmd_gm_backup,
    cmd_gm_banlist,
    cmd_gm_export,
    cmd_gm_restore,
    handle_gm_command,
    silent_result,
)
from qbot_rpg.commands.parsers import DEFAULT_GM_COMMANDS, DEFAULT_WHITELIST, parse_command

# =============================================================================
# 常量与注册
# =============================================================================
def test_new_commands_in_lists() -> None:
    """4 新指令在 GM_COMMANDS/INDEX/LEVEL/parsers 白名单。"""
    assert {GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST} <= GM_COMMANDS
    assert GM_COMMAND_INDEX[GM_CMD_BACKUP] == "G2"
    assert GM_COMMAND_INDEX[GM_CMD_RESTORE] == "G3"
    assert GM_COMMAND_INDEX[GM_CMD_EXPORT] == "G4"
    assert GM_COMMAND_INDEX[GM_CMD_BANLIST] == "G12"
    assert GM_COMMAND_LEVEL[GM_CMD_BACKUP] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_RESTORE] == ROLE_MANAGER
    assert GM_COMMAND_LEVEL[GM_CMD_EXPORT] == ROLE_ADMIN
    assert GM_COMMAND_LEVEL[GM_CMD_BANLIST] == ROLE_MANAGER
    # parsers
    assert {GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST} <= DEFAULT_WHITELIST
    assert {GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST} <= DEFAULT_GM_COMMANDS


def test_handlers_registered() -> None:
    """_HANDLERS 含 4 新指令处理器（handle_gm_command 能分派）。"""
    assert gc._HANDLERS[GM_CMD_BACKUP] is cmd_gm_backup
    assert gc._HANDLERS[GM_CMD_RESTORE] is cmd_gm_restore
    assert gc._HANDLERS[GM_CMD_EXPORT] is cmd_gm_export
    assert gc._HANDLERS[GM_CMD_BANLIST] is cmd_gm_banlist


def test_parse_command_recognizes_new() -> None:
    """parse_command 识别 4 新指令（白名单生效）。"""
    for raw in ("/备份", "/恢复 abc", "/存档导出 csv", "/封禁列表 2"):
        cmd = raw.lstrip("/").split(" ", 1)[0]
        parsed = parse_command(raw)
        assert parsed.command == cmd, f"{raw} → {parsed.command}"


# =============================================================================
# 权限与降级
# =============================================================================
def _parsed(raw: str) -> Any:
    return parse_command(raw)


def _ctx(player_role: str = ROLE_PLAYER, backend: Any = None) -> dict:
    """GM 处理器 ctx（player 无 gm_backend → 降级路径；gm 注入假后端可选）。"""
    return {
        "qq_id": "10001", "group_id": "20001",
        "role": player_role, "audit_log": [],
        "gm_backend": backend,
        "now": "2026-09-03T12:00:00Z",
    }


def test_player_no_perm_silent() -> None:
    """普通玩家调 4 新指令 → 静默（零审计零消息，TC-01 静默边界）。"""
    from qbot_rpg.commands.gm_commands import GmUser, check_gm_permission

    user = GmUser(qq_id="10001", role=ROLE_PLAYER, granted_commands=())
    for cmd in (GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST):
        perm = check_gm_permission(user, cmd)
        assert not perm.ok, f"{cmd} player 应无权限"
    # handle_gm_command 静默
    for raw in ("/备份", "/封禁列表"):
        r = handle_gm_command(_parsed(raw), _ctx(ROLE_PLAYER))
        assert r == silent_result() or not r.ok


def test_no_backend_degrades_gracefully() -> None:
    """GM 角色 + 无 gm_backend → 人话 failed 不崩（新 4 条降级语义）。"""
    # manager 默认集 3 条（备份/恢复/封禁列表）+ admin 的存档导出
    for cmd, raw, role in (
        (GM_CMD_BACKUP, "/备份", ROLE_MANAGER),
        (GM_CMD_RESTORE, "/恢复 x", ROLE_MANAGER),
        (GM_CMD_BANLIST, "/封禁列表", ROLE_MANAGER),
        (GM_CMD_EXPORT, "/存档导出", ROLE_ADMIN),
    ):
        ctx = _ctx(role)  # 无 backend
        r = handle_gm_command(_parsed(raw), ctx)
        assert not r.ok, f"{cmd} 无后端应 failed"
        assert (r.audit or {}).get("result") == "failed"
        assert ctx["audit_log"], f"{cmd} 失败应留痕"


def test_gm_export_as_manager_silent() -> None:
    """manager 调 /存档导出（admin 专属未下授）→ 静默零审计（TC-04 口径）。"""
    from qbot_rpg.commands.gm_commands import GmUser, check_gm_permission

    gm = GmUser(qq_id="10001", role=ROLE_MANAGER, granted_commands=())
    perm = check_gm_permission(gm, GM_CMD_EXPORT)
    assert not perm.ok and perm.silent
    ctx = _ctx(ROLE_MANAGER)
    r = handle_gm_command(_parsed("/存档导出"), ctx)
    assert r.silent and not r.ok and r.audit is None
    assert ctx["audit_log"] == []


def test_gm_backup_with_fake_backend() -> None:
    """gm + 假后端 backup_content → 成功 + 审计 success + ref=backup_id。"""
    class FakeBackend:
        def backup_content(self, pack=None, ctx=None):
            return {"ok": True, "backup_id": "content_pack_1", "message": "已备份 3 个模块"}

    ctx = _ctx(ROLE_MANAGER, backend=FakeBackend())
    r = handle_gm_command(_parsed("/备份"), ctx)
    assert r.ok
    assert ctx["audit_log"][-1]["command"] == GM_CMD_BACKUP
    assert ctx["audit_log"][-1]["result"] == "success"
    assert ctx["audit_log"][-1]["ref"] == "content_pack_1"


def test_gm_export_requires_admin() -> None:
    """存档导出 = admin（机主）；manager 默认无权限（静默），admin 放行。"""
    from qbot_rpg.commands.gm_commands import GmUser, check_gm_permission

    gm = GmUser(qq_id="10001", role=ROLE_MANAGER, granted_commands=())
    assert not check_gm_permission(gm, GM_CMD_EXPORT).ok  # 默认授予集不含
    owner = GmUser(qq_id="10001", role=ROLE_ADMIN, granted_commands=())
    assert check_gm_permission(owner, GM_CMD_EXPORT).ok


# =============================================================================
# GmBackend 真实实现（zip 备份 / 恢复）
# =============================================================================
def _make_content_dir(tmp_path: Path) -> Path:
    """tmp content 目录（3 个 json + 1 个非 json）。"""
    cd = tmp_path / "content"
    cd.mkdir()
    (cd / "enemies.json").write_text(json.dumps(
        [{"id": "wolf", "name": "风狼", "hp": 90}], ensure_ascii=False), encoding="utf-8")
    (cd / "skills.json").write_text(json.dumps([{"id": "s1"}]), encoding="utf-8")
    (cd / "maps.json").write_text(json.dumps([{"id": "m1"}]), encoding="utf-8")
    (cd / "notes.txt").write_text("not json", encoding="utf-8")
    return cd


def test_backup_content_zip_real(tmp_path: Path) -> None:
    """GmBackend.backup_content：content → zip（含 json 不含 txt）+ backups 登记。"""
    cd = _make_content_dir(tmp_path)
    # 假 db（鸭子 execute 登记 backups）
    class FakeDb:
        def __init__(self):
            self.rows = []

        def execute(self, sql, params=None):
            self.rows.append((sql, params))

    db = FakeDb()
    backend = GmBackend()
    res = backend.backup_content("testpack", {"content_dir": str(cd), "db": db,
                                              "backup_dir": str(tmp_path / "baks")})
    assert res.get("ok"), res
    bid = res["backup_id"]
    zip_path = tmp_path / "baks" / f"{bid}.zip"
    assert zip_path.exists()
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        assert "enemies.json" in names and "skills.json" in names and "maps.json" in names
        assert "notes.txt" not in names
    # backups 登记（db.execute 被调用）
    assert any("INSERT INTO backups" in r[0] for r in db.rows)


def test_backup_content_no_dir_degrades(tmp_path: Path) -> None:
    """无 content_dir → {ok: False, message: 人话}（装配前降级）。"""
    backend = GmBackend()
    res = backend.backup_content(ctx={})
    assert res.get("ok") is False
    assert "content_dir" in str(res.get("message") or "")


def test_restore_content_real(tmp_path: Path) -> None:
    """GmBackend.restore_content：先备份当前 → 从 zip 覆盖 content（含 .json 替换）。"""
    cd = _make_content_dir(tmp_path)
    backup_dir = tmp_path / "baks"
    backend = GmBackend()
    # 先备份
    res = backend.backup_content("testpack", {"content_dir": str(cd),
                                              "backup_dir": str(backup_dir)})
    assert res.get("ok")
    bid = res["backup_id"]
    # 改坏 content（模拟丢失 enemies.json）
    (cd / "enemies.json").unlink()
    (cd / "skills.json").write_text("corrupt", encoding="utf-8")
    # 恢复
    res = backend.restore_content(bid, {"content_dir": str(cd),
                                        "backup_dir": str(backup_dir)})
    assert res.get("ok"), res
    # enemies.json 回来了 + skills.json 恢复合法 JSON
    data = json.loads((cd / "enemies.json").read_text(encoding="utf-8"))
    assert data[0]["id"] == "wolf"
    data2 = json.loads((cd / "skills.json").read_text(encoding="utf-8"))
    assert data2[0]["id"] == "s1"
    # 无 .tmp 残留
    assert list(cd.glob("*.tmp")) == []


def test_restore_missing_backup_degrades(tmp_path: Path) -> None:
    """备份不存在 → {ok: False, message: 人话}。"""
    cd = _make_content_dir(tmp_path)
    backend = GmBackend()
    res = backend.restore_content("ghost_id", {"content_dir": str(cd),
                                               "backup_dir": str(tmp_path / "baks")})
    assert res.get("ok") is False
    assert "ghost_id" in str(res.get("message") or "")
