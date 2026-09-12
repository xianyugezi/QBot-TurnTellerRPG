"""
模板分区：basic_rem（基础指令剩余：装备/技能/货币等；2026-08-31 模板配置化包拆分）。

2026-09-12 消息模板重构批5·路O：本分区剩余 25 键（装备栏 basic_equip_*、装备穿卸适配器
消息与 reason_*、basic_register_gate、basic_register_guide、basic_help_group_header）已
全部迁入全量模板表（qbot_rpg/core/templates/template_table.json）；默认表与占位符白名单清空。
其中 basic_equip_wear_fail 经死键复核后清除（全仓零引用，与 basic_equip_fail +
basic_equip_fail_wear 组合重复），内容包同 key 一并移除。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
