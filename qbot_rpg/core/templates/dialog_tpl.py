"""
模板分区：dialog_tpl（对话指令（dialog_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

2026-09-12 消息模板重构（批11·路A）：
- 本分区全部 3 键（dialog_menu_head / dialog_dispatch_error / dialog_dispatch_bad_return）
  全部迁入全量表 `qbot_rpg/core/templates/template_table.json`，按手机QQ 14 全角新规范重写
  （菜单头行结构模板保留；引擎异常兜底补错误行标记 ❌ + 原因，对齐
  explore_enter_engine_error / explore_rest_engine_error house 口径）；
  本分区默认表与占位符白名单清空（白名单由表自动派生，见 core/templates/__init__.py）。
- 本路无死键（3 键均有 tpl_of 调用点：dialog_commands._handle_menu_rerender L403 /
  _dispatch_entry L421、L423）。
- 渲染链 = 新表（全量默认）→ 内容包 templates.json（覆盖）→ tpl_of（接口不变）。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移（dialog_commands 的
f-string / 中文输出拼接），默认值改动会导致现有测试断言失效——需与
dialog_commands 渲染处 tpl_of(ctx, "dialog_*", {...}) 一致。

范围说明：本分区只收 dialog_commands.py 壳层直接输出的展示文案。引擎（core/dialog.py
list/menu/叙述/恢复简报/空地图提示）输出不在此列；`f"intel:{rid}"`/`f"tutorial:{rid}"`
为 npc_delivered 数据键（机械拼键，非展示），`f"{feedback}\\n{out}"` 为机械拼接，
均不在模板范围（对齐 investigate_commands L947 同款保留口径）。

本空壳文件待批18 死键清扫时随其余已迁分区一并删除（过渡期保留 import 兼容）。
"""
from __future__ import annotations

from typing import Any, Dict

# 已清空：3 键已迁全量模板表；白名单由表自动派生（见 core/templates/__init__.py）。
DEFAULT_TEMPLATES: Dict[str, Any] = {}

PLACEHOLDER_WHITELIST: Dict[str, set] = {}
