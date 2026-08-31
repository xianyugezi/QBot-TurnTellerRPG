"""
模板分区：use_tpl（使用指令（use_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移，默认值改动会导致
现有测试断言失效——需与 use_commands 渲染处 tpl_of(ctx, "use_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 使用指令（use_commands）——
    "use_in_battle": "❌ 战斗中不能使用物品",
    "use_no_arg": "❌ /使用：需要物品序号或名称（/使用 1 或 /使用 疗伤药）",
    "use_no_item": "❌ 背包里没有这个物品",
    "use_cannot_use": "❌ 这个物品不能直接使用",
    "use_bound": "❌ 这个物品已绑定，无法使用",
    "use_ok": "✅ 使用成功：{name}（生命 +{heal_total}）",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "use_in_battle": set(),
    "use_no_arg": set(),
    "use_no_item": set(),
    "use_cannot_use": set(),
    "use_bound": set(),
    "use_ok": {"name", "heal_total"},
}
