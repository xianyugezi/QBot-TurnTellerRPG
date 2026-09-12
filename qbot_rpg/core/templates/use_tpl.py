"""
模板分区：use_tpl（使用指令（use_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批11·路B：本分区全部 6 键（战斗内拒绝 use_in_battle / 缺参 use_no_arg /
  物品未命中 use_no_item / 不可直接使用 use_cannot_use / 绑定拒用 use_bound /
  使用成功 use_ok）全部迁入全量表 qbot_rpg/core/templates/template_table.json，
  按手机QQ 14 全角新规范重写（错误行 ❌+原因(+下一步)、成功行每行一字段拆行、
  免斜杠指令写法「发 使用 <序号或名称>」、去括号/冒号挤宽）。
  本路无死键清除（6 键全仓均有渲染调用）。
  本分区默认表与占位符白名单清空。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
