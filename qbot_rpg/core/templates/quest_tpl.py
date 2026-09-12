"""
模板分区：quest_tpl（任务指令（quest_commands 剩余行）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构：
- 批7·路U：本分区全部 25 键（任务板 quest_board_* 7 / 任务信息 quest_info_* 5 /
  三原语进度 quest_progress_* 4 / 接取·放弃·交付 quest_accept_failed /
  quest_abandon_failed / quest_deliver_failed / quest_deliver_skipped* /
  quest_deliver_seq_shift_note 6 / 空态门禁 quest_no_board / quest_no_quest /
  quest_empty_board 3）全部迁入全量表 qbot_rpg/core/templates/template_table.json，
  按手机QQ 14 全角新规范重写（段头改【title】、进度改独立行、❌ + 下一步、免斜杠、
  信息行标记前置）；本分区默认表与占位符白名单清空。
  本路无死键清除（25 键全仓均有渲染调用点）。

渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）；
渲染零装饰 emoji（仅 ✅/❌ 功能性标记）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}
PLACEHOLDER_WHITELIST: Dict[str, set] = {}
