"""
模板分区：gift_tpl（赠送指令 gift_commands；2026-09-06 指令缺口补全批2路1）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批10·路B：本分区全部 13 键（注册门槛 gift_register_gate，参数错误
  gift_err_empty / gift_err_qty / gift_err_missing_player，物品查找
  gift_not_found / gift_bound / gift_no_item，目标寻址 gift_target_not_found /
  gift_self，系统开关 gift_no_system / gift_system_disabled，成功与接收
  gift_ok / gift_receive）全部迁入全量表
  qbot_rpg/core/templates/template_table.json，按手机QQ 14 全角新规范重写
  （错误行 ❌+原因(+下一步)、成功行每行一字段拆行、免斜杠指令写法、
  去括号/｜挤宽）。
  本路无死键清除（13 键全仓均有定义；gift_receive / gift_system_disabled 为
  待接线候选，登记见 02_全量审计表）。
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
