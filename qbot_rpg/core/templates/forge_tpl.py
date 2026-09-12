"""
模板分区：forge_tpl（锻造指令（forge_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批3·路I：执行流 33 键（系统/守卫/解析错误 + 批量/成功路径 + forge_redflag_suffix）
  迁至全量表 qbot_rpg/core/templates/template_table.json；
- 批6·路R：本批收尾 30 键（预览卡片 forge_preview_* / forge_req_line /
  forge_element_summary / forge_atk_summary / forge_slots* / forge_continue* /
  forge_confirm_none / forge_preview_expired / 图纸链 forge_blueprint_* /
  forge_terminal_element / forge_branch_* / 锻造树 forge_tree_* / 套装与客制
  forge_sets_* / forge_augments_*）全部迁入全量表，按手机QQ 14 全角新规范重写
  （含 forge_sets_empty 存量 E501 消除）；本分区默认表与占位符白名单清空。
  本路无死键清除（30 键全仓均有代码/内容包引用）。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → × / ■ 等）。

注意：forge_commands.py 模块级常量（TREE_EMPTY_PAGE / TREE_TAIL_TIP /
SETS_LOCKED_MSG / AUGMENTS_LOCKED_MSG / SETS_EMPTY / AUGMENTS_EMPTY）为向后兼容
导出——已改指全量表别名（_ALL_TPL），渲染一律走 tpl_of。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
