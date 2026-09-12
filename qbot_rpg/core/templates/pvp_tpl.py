"""
模板分区：pvp_tpl（PVP 指令（pvp_commands）；M11 批3 路3B）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批8·路A：本分区全部 20 键（解析错误 4 类 pvp_err_* / 引擎入口 2 类
  pvp_engine_* / 锁定玩家 9 键 pvp_lock_* / 攻击玩家 3 键 pvp_attack_* /
  门禁兜底 pvp_registered_gate / pvp_not_registered）全部迁入全量表
  qbot_rpg/core/templates/template_table.json，按手机QQ 14 全角新规范重写
  （❌ 原因 + 免斜杠下一步、每行一字段拆行、错误行两行化、攻击伤害行拆两行）；
  本分区默认表与占位符白名单清空。
  本路无死键清除：pvp_lock_no_target / pvp_not_registered 全仓无消费方
  （docs/审查报告/审查_M11_A3_jspace.md P2-5），按信息要素等价重做后留待批18 死键清扫复核。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
