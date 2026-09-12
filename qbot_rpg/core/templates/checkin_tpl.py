"""
模板分区：checkin_tpl（签到指令（checkin_commands）；2026-08-31 模板配置化包拆分）。

2026-09-12 消息模板重构（批2·路E）：签到 23 键**全部迁至全量表**
`qbot_rpg/core/templates/template_table.json`（按新排版规范重做；新表同名 key
在聚合时覆盖本分区）。本分区现为**空壳**（DEFAULT_TEMPLATES / PLACEHOLDER_WHITELIST
均为空），待终态随其余分区一并删除。

原铁律（历史）：字符串 = 2026-08-31 前写死在 checkin_commands.py 的逐字文案迁移
（TPL_NO_CHECKIN / TPL_NO_TABLE / 结算·状态·补签各 f-string / grant 标签）——
迁移后默认值唯一源 = 全量表，渲染处仍为 `tpl_of(ctx, "checkin_*", {...})`。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
