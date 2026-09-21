"""GM 指令常量（qbot_rpg/data/gm_constants.py · M7 BCH-01 收口）。

单一事实源：GM 指令名/清单/前缀强制集。原定义于 qbot_rpg/commands/gm_commands.py，
因架构铁律「commands/web 不被依赖（R3/D-05）」——装配层（assembly）需注入
GM_COMMANDS（快捷绑定校验）却不可依赖 commands 层——下沉至 data 层（通用底层，
仅标准库），gm_commands.py 由此 re-export 保持向后兼容。

依据：指令分隔符统一规范 L160 长清单（GM 指令：重载/封禁/日志/设置）；
m4_shared_contract §2.3（GM 强制 / 前缀）；5b §2.1 G 序号。

批30（2026-09-16 · 主 agent 依用户授权）：**删除 G13 `/编辑`**——旧编辑器已整体删除
（`docs/消息模板重构/02_遗留登记.md` #86），链接源 `settings.editor_url` 已清空，
指令只剩「暂未配置链接」空壳 → 按奥卡姆删除（登记表 X9）。5b 契约 G13 条目同步删除。
"""

from __future__ import annotations

from typing import FrozenSet, Mapping

__all__ = [
    "GM_CMD_RELOAD",
    "GM_CMD_BAN",
    "GM_CMD_LOG",
    "GM_CMD_SETTINGS",
    "GM_CMD_BACKUP",
    "GM_CMD_RESTORE",
    "GM_CMD_EXPORT",
    "GM_CMD_BANLIST",
    "GM_CMD_DEBUG",
    "GM_CMD_TEST",
    "GM_COMMANDS",
    "GM_COMMAND_INDEX",
    "GM_PREFIX_REQUIRED",
]

# L160 长清单（指令分隔符统一规范 L160：绑定目标为 GM 指令 → 拒绝）
GM_CMD_RELOAD = "重载"      # G1
GM_CMD_BAN = "封禁"         # G10
GM_CMD_LOG = "日志"         # G8
# GM_CMD_EDIT = "编辑"      # G13 —— 批30（2026-09-16）删除（空壳，见文件头）
GM_CMD_SETTINGS = "设置"    # G14
# M12 批3 路3A（细化_5b §2.1 G 序号；此前 9 条待接线，本路接 4 条）
GM_CMD_BACKUP = "备份"      # G2
GM_CMD_RESTORE = "恢复"     # G3
GM_CMD_EXPORT = "存档导出"  # G4（机主专属可下授）
GM_CMD_BANLIST = "封禁列表"  # G12
# 批75 · GM 运维 5 条（细化_5b §2.1 G5/G6/G7/G9/G11；此前「登记但未实现」）
GM_CMD_DEBUG = "调试"       # G5（机主→GM，可下授）
GM_CMD_TEST = "测试"        # G6（机主→GM，可下授；只读冒烟）

# GM 指令清单（m4 §2.3：以分隔符规范 L160 长清单为准；M12 扩至 9 条；批30 G13 删除 → 8 条；
# 批75 起补 5b 运维 5 条，逐条接入）
GM_COMMANDS: FrozenSet[str] = frozenset({
    GM_CMD_RELOAD, GM_CMD_BAN, GM_CMD_LOG, GM_CMD_SETTINGS,
    GM_CMD_BACKUP, GM_CMD_RESTORE, GM_CMD_EXPORT, GM_CMD_BANLIST,
    GM_CMD_DEBUG, GM_CMD_TEST,
})

# 5b §2.1 G 序号（审计展示 /日志 行前缀用；批30 G13 编辑已删；批75 补 G5/G6/G7/G9/G11）
GM_COMMAND_INDEX: Mapping[str, str] = {
    GM_CMD_RELOAD: "G1",
    GM_CMD_BAN: "G10",
    GM_CMD_LOG: "G8",
    GM_CMD_SETTINGS: "G14",
    GM_CMD_BACKUP: "G2",
    GM_CMD_RESTORE: "G3",
    GM_CMD_EXPORT: "G4",
    GM_CMD_BANLIST: "G12",
    GM_CMD_DEBUG: "G5",
    GM_CMD_TEST: "G6",
}

# GM 强制 / 前缀指令集（L128 / W07；parsers.DEFAULT_PREFIX_REQUIRED 已含 5 条，
# 本常量供装配/校验器对照，保证单一事实源）
GM_PREFIX_REQUIRED: FrozenSet[str] = GM_COMMANDS
