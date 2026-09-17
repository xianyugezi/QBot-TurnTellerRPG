"""批30 · X9 回归：GM `/编辑`（5b G13）已删除（2026-09-16 · 主 agent 依用户授权）。

背景：旧 Web 内容编辑器 2026-09-13 整体删除、链接源 `settings.editor_url` 已清空，
`/编辑` 退化为「暂未配置链接」空壳（`docs/消息模板重构/02_遗留登记.md` #87）→ 按奥卡姆
删除；GM 指令属 5b 契约，故同步删除契约条目（见 `docs/细化/细化_5b_GM指令契约.md`）。

本文件为**「已移除」回归断言**（不是行为测试）：任何一处把 `/编辑` 加回来即红。
"""

from __future__ import annotations

import qbot_rpg.commands.gm_commands as gc
from qbot_rpg.commands.basic_commands import GM_HELP_GROUP
from qbot_rpg.commands.gm_commands import (
    GM_COMMANDS,
    GM_COMMAND_INDEX,
    GM_COMMAND_LEVEL,
    GmBackend,
    is_gm_command_name,
    register_gm_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_GM_COMMANDS, DEFAULT_WHITELIST
from qbot_rpg.commands.router import Router
from qbot_rpg.content.permission_store import (
    GM_COMMANDS_ALL,
    GM_DEFAULT_GRANT,
    GM_OWNER_ONLY,
)

_REMOVED = "编辑"


def test_gm_constants_removed():
    """常量层：清单/序号/权限表都不含 `/编辑`。"""
    assert _REMOVED not in GM_COMMANDS
    assert _REMOVED not in GM_COMMAND_INDEX
    assert _REMOVED not in GM_COMMAND_LEVEL
    assert not hasattr(gc, "GM_CMD_EDIT")


def test_parser_whitelist_removed():
    """解析层：白名单/强制前缀集不再含 `/编辑`（避免「白名单有但未注册」噪音）。"""
    assert _REMOVED not in DEFAULT_GM_COMMANDS
    assert _REMOVED not in DEFAULT_WHITELIST


def test_permission_sets_removed():
    """权限存储层：GM 全集/默认授予集都不含 `/编辑`（旧库授权串自然失效为 False）。"""
    assert _REMOVED not in GM_COMMANDS_ALL
    assert _REMOVED not in GM_DEFAULT_GRANT
    assert _REMOVED not in GM_OWNER_ONLY


def test_router_no_edit_spec():
    """注册层：`register_gm_commands` 不再产出 `/编辑` spec，且不是 GM 指令名。"""
    r = Router()
    register_gm_commands(r)
    assert r.get(_REMOVED) is None
    assert set(r.gm_commands()) == set(GM_COMMANDS)
    assert not is_gm_command_name(_REMOVED)
    assert not is_gm_command_name("/" + _REMOVED)


def test_backend_and_handler_removed():
    """后端/处理器层：空壳 `editor_link` 与 `cmd_gm_edit` 均不存在。"""
    assert not hasattr(GmBackend, "editor_link")
    assert not hasattr(gc, "cmd_gm_edit")


def test_help_group_removed():
    """帮助层：GM 组条目不再渲染 `/编辑`；其余 GM 条目保持。"""
    names = [name for name, _desc in GM_HELP_GROUP[1]]
    assert _REMOVED not in names
    assert names == ["重载", "封禁", "日志", "设置"]


def test_other_gm_commands_unchanged():
    """GM 其它指令行为不变：默认授予集与最低权限逐条对齐（删除未波及）。"""
    from qbot_rpg.commands.gm_commands import ROLE_ADMIN, ROLE_MANAGER

    assert GM_COMMAND_LEVEL["设置"] == ROLE_ADMIN
    assert GM_COMMAND_LEVEL["存档导出"] == ROLE_ADMIN
    for cmd in ("重载", "封禁", "日志", "备份", "恢复", "封禁列表"):
        assert GM_COMMAND_LEVEL[cmd] == ROLE_MANAGER
        assert cmd in GM_DEFAULT_GRANT
