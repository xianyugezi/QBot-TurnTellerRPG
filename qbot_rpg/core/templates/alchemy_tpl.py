"""
模板分区：alchemy_tpl（炼金指令（alchemy_commands）；2026-08-31 模板配置化包拆分）。

2026-09-12 消息模板重构批7·路T：本分区剩余 39 条模板已全部迁入全量模板表
（qbot_rpg/core/templates/template_table.json）——即时调合 6 键 / 种植收获收取 8 键 /
代工助手与协力 7 键 / 技能面板 SP 11 键 / 炼金图鉴 7 键（按新规范全新重写：14 全角拆行、
免斜杠、错误行 ❌+原因、少 ｜ 多换行）；默认表与占位符白名单清空。
迁出键清单见批7·路T fragment（docs/消息模板重构/_fragments/b7t.json）。
渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。
本空壳文件待死键清扫批随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
