"""
模板分区：investigate_tpl（调查指令（investigate_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批8·路B：本分区全部 18 键（注册门槛 investigate_register_gate / 无位置兜底
  investigate_no_map / 环境快照头 investigate_env_header / 泛化环境文本池
  investigate_ambient_1..5 / 去重简短确认 investigate_eggshell_done /
  investigate_hunt_done / investigate_hidden_map_done / 蹲点默认演出
  investigate_hunt_intro / investigate_hunt_signal / 隐藏地图入口兜底介绍
  investigate_hidden_map_text / 发现卡片 investigate_discover_card /
  图鉴传闻引用 investigate_codex_ref / 发现标签 investigate_discover_label_boss /
  investigate_discover_label_map）全部迁入全量表
  qbot_rpg/core/templates/template_table.json，按手机QQ 14 全角新规范重写
  （免斜杠下一步、去重确认两行、蹲点信号两行、图鉴引用拆行；风味环境文本 /
  蹲点演出 / 隐藏地图介绍登记 meta.prose_keys 允许自然折行）；
  本分区默认表与占位符白名单清空。
  本路无死键清除（18 键全仓均有渲染调用点）。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
