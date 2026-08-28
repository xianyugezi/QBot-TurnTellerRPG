"""GM 指令常量（qbot_rpg/data/gm_constants.py · M7 BCH-01 收口）。

单一事实源：GM 指令名/清单/前缀强制集。原定义于 qbot_rpg/commands/gm_commands.py，
因架构铁律「commands/web 不被依赖（R3/D-05）」——装配层（assembly）需注入
GM_COMMANDS（快捷绑定校验）却不可依赖 commands 层——下沉至 data 层（通用底层，
仅标准库），gm_commands.py 由此 re-export 保持向后兼容。

依据：指令分隔符统一规范 L160 长清单（GM 指令：重载/封禁/日志/编辑/设置）；
m4_shared_contract §2.3（GM 强制 / 前缀）；5b §2.1 G 序号。
"""

from __future__ import annotations

from typing import FrozenSet, Mapping

__all__ = [
    "GM_CMD_RELOAD",
    "GM_CMD_BAN",
    "GM_CMD_LOG",
    "GM_CMD_EDIT",
    "GM_CMD_SETTINGS",
    "GM_COMMANDS",
    "GM_COMMAND_INDEX",
    "GM_PREFIX_REQUIRED",
]

# L160 长清单（指令分隔符统一规范 L160：绑定目标为 GM 指令 → 拒绝）
GM_CMD_RELOAD = "重载"      # G1
GM_CMD_BAN = "封禁"         # G10
GM_CMD_LOG = "日志"         # G8
GM_CMD_EDIT = "编辑"        # G13
GM_CMD_SETTINGS = "设置"    # G14

# GM 指令清单（m4 §2.3：以分隔符规范 L160 长清单为准）
GM_COMMANDS: FrozenSet[str] = frozenset({
    GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG, GM_CMD_EDIT, GM_CMD_SETTINGS,
})

# 5b §2.1 G 序号（审计展示 /日志 行前缀用）
GM_COMMAND_INDEX: Mapping[str, str] = {
    GM_CMD_RELOAD: "G1",
    GM_CMD_BAN: "G10",
    GM_CMD_LOG: "G8",
    GM_CMD_EDIT: "G13",
    GM_CMD_SETTINGS: "G14",
}

# GM 强制 / 前缀指令集（L128 / W07；parsers.DEFAULT_PREFIX_REQUIRED 已含 5 条，
# 本常量供装配/校验器对照，保证单一事实源）
GM_PREFIX_REQUIRED: FrozenSet[str] = GM_COMMANDS
