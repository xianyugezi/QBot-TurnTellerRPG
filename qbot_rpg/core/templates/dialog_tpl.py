"""
模板分区：dialog_tpl（对话指令（dialog_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移（dialog_commands 的
f-string / 中文输出拼接），默认值改动会导致现有测试断言失效——需与
dialog_commands 渲染处 tpl_of(ctx, "dialog_*", {...}) 一致。

范围说明：本分区只收 dialog_commands.py 壳层直接输出的展示文案。引擎（core/dialog.py
list/menu/叙述/恢复简报/空地图提示）输出不在此列；`f"intel:{rid}"`/`f"tutorial:{rid}"`
为 npc_delivered 数据键（机械拼键，非展示），`f"{feedback}\\n{out}"` 为机械拼接，
均不在模板范围（对齐 investigate_commands L947 同款保留口径）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 菜单层重显头行（_menu_rerender；中断恢复「菜单层重显」RN-12）——
    "dialog_menu_head": "{npc_name}：",

    # —— 动作执行安全失败（_dispatch_entry 兜底 message；TPL-12 由装配层）——
    "dialog_dispatch_error": "动作执行异常",
    "dialog_dispatch_bad_return": "动作返回异常",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "dialog_menu_head": {"npc_name"},
    "dialog_dispatch_error": set(),
    "dialog_dispatch_bad_return": set(),
}
