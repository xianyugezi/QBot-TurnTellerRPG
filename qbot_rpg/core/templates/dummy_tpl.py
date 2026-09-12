"""
模板分区：dummy_tpl（训练木桩指令（dummy_commands）；2026-09-06 指令缺口补全批1路2）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批9·路A：本分区全部 16 键（注册门槛 dummy_register_gate / 系统开关
  dummy_system_disabled / 战斗锁 dummy_battle_lock / 档位列表 4 键
  dummy_list_header·row·tail·empty / 未找到 dummy_not_found / 开战 dummy_start /
  调整面板 4 键 dummy_adjust_ok·reset·missing·usage / 退出 3 键
  dummy_exit_no_battle·not_dummy·ok）全部迁入全量表
  qbot_rpg/core/templates/template_table.json，按手机QQ 14 全角新规范重写
  （免斜杠指令书写、❌ 原因 + 下一步拆行、档位列表每行一字段、开战段头 + 规则行）；
  本分区默认表与占位符白名单清空。
  本路无死键清除：dummy_adjust_usage 全仓无消费方，按信息要素等价重做后
  留待批18 死键清扫复核。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记 + 排版符号）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
