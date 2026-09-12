"""
模板分区：explore_tpl（探索指令（explore_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移（explore_commands 的
f-string / TPL 常量 / 中文输出拼接），默认值改动会导致现有测试断言失效——需与
explore_commands 渲染处 tpl_of(ctx, "explore_*", {...}) 一致。

2026-09-12 消息模板重构（批1·路C）：位置/进入/移动/到达 17 键迁至全量表
qbot_rpg/core/templates/template_table.json（按新规范全新重写；新表同名 key
在聚合时覆盖本分区）；本分区仅保留尚未迁移的键（时间天气/怪物头/休息/地图）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 2026-09-06 时间/天气指令 ——
    "worldtime_now": "时间：{season}季 · {period}",
    "weather_now": "天气：{loc} · {weather}",
    "worldtime_disabled": "❌ 时间/天气系统未启用（内容包未配置 time_cycle）",

    # —— /怪物 列表头（条目行块 explore_monster_row/line/overflow 已迁全量表） ——
    "explore_monster_header": "【{loc}】活动怪物",
    "explore_monster_empty": "❌ 当前地图没有活动怪物",

    # —— /休息 ——
    "explore_rest_ok": "✅ 你休息了一会，回复 {hp} 点 HP、{mp} 点 MP",
    "explore_rest_cooldown": "（冷却缩减 {cr}）",
    "explore_rest_fail": "❌ {reason}",
    "explore_rest_fail_reason": "无法休息",
    "explore_rest_extra_arg": "❌ 指令不正确：/休息 不需要参数。输入 /帮助 查看可用指令。",
    "explore_rest_not_wired": "❌ 休息功能未接线（引擎未加载）",
    "explore_rest_engine_error": "❌ 休息失败（引擎返回异常）",

    # —— /地图 ——
    "explore_map_title": "【地图】",
    "explore_map_row": "{idx}. {name}",
    "explore_map_tail": "Tip:发送'进入 <序号>'前往",
    "explore_map_empty": "❌ 当前没有可探索的地图（/进入 尝试）",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "worldtime_now": {"season", "period"},
    "weather_now": {"loc", "weather"},
    "worldtime_disabled": set(),
    "explore_monster_header": {"loc"},
    "explore_monster_empty": set(),
    "explore_rest_ok": {"hp", "mp"},
    "explore_rest_cooldown": {"cr"},
    "explore_rest_fail": {"reason"},
    "explore_rest_fail_reason": set(),
    "explore_rest_extra_arg": set(),
    "explore_rest_not_wired": set(),
    "explore_rest_engine_error": set(),
    "explore_map_title": set(),
    "explore_map_row": {"idx", "name"},
    "explore_map_tail": set(),
    "explore_map_empty": set(),
}
