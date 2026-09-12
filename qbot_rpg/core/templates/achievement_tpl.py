"""
模板分区：achievement_tpl（成就指令（achievement_commands）；M11 批1 路1C）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构（批8·路C）：
- 本分区全部 16 键（列表 ach_list_header / ach_list_line / ach_list_locked / ach_list_tail、
  详情 ach_view_header / ach_view_desc / ach_view_hidden / ach_view_not_found、
  揭示 ach_reveal_card、称号 ach_title_header / ach_title_line / ach_title_equip_ok /
  ach_title_equip_fail / ach_title_empty / ach_title_help、空态 ach_empty）
  全部迁入全量表 `qbot_rpg/core/templates/template_table.json`，按手机QQ 14 全角新规范重写
  （段头【成就】/【称号】、多字段拆行、免斜杠「发 成就信息 <序号>」、❌ + 原因 + 下一步）；
  本分区默认表与占位符白名单清空（白名单由表自动派生，见 core/templates/__init__.py）。
- 本路无死键清除；但如实登记：ach_list_tail / ach_reveal_card 在代码中无 tpl_of 调用点
  （列表尾段仍走 `render_cake_tail(tip=...)` 硬编码，揭示卡属引擎 reveals 侧）——两键留表，
  待批18 死键清扫裁决；其余 14 键均有渲染调用点。
- 渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。

历史铁律：字符串 = 成就指令壳（成就/成就信息/称号）渲染文案，key 命名 ach_<用途>；
渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 ｜ → × /「」【】）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
