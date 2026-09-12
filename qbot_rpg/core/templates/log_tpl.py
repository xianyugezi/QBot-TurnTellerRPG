"""
模板分区：log_tpl（日志指令（log_commands）；2026-08-31 模板配置化包拆分）。

2026-09-12 消息模板重构批2·路F：本分区 29 条 log_* 模板已全部迁入全量模板表
（qbot_rpg/core/templates/template_table.json）；默认表与占位符白名单清空。
渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。
本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
