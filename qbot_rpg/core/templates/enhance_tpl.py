"""模板分区：enhance_tpl（强化指令（enhance_commands）——2026-09-12 消息模板重构后为空壳残留）。

2026-09-12 消息模板重构（批2·路D）：原 38 键全部迁至全量表
qbot_rpg/core/templates/template_table.json（按手机QQ 14 全角新规范重写；
新表同名 key 在聚合时覆盖本分区）。死键 3 条（enhance_err_space、
enhance_roll_line_protect、enhance_info_hint）复核全仓零引用后清除。

本分区现无键；文件保留仅为过渡期 import 兼容（终态随旧分区整体删除）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
