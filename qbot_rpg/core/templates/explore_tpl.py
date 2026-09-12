"""
模板分区：explore_tpl（探索指令（explore_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批1·路C：位置/进入/移动/到达 17 键迁入全量表
  qbot_rpg/core/templates/template_table.json（批1·路C 报告）。
- 批10·路A：本分区余下全部 16 键（时间/天气 3 键 worldtime_now·weather_now·
  worldtime_disabled / 怪物段头与空态 2 键 explore_monster_header·empty /
  休息 7 键 explore_rest_ok·cooldown·fail·fail_reason·extra_arg·not_wired·
  engine_error / 地图列表 4 键 explore_map_title·row·tail·empty）全部迁入
  全量表，按手机QQ 14 全角新规范重写（免斜杠指令书写、每行一字段、
  大数值独立行、错误行 ❌ 原因 + 下一步拆行）；本分区默认表与占位符白名单清空。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
