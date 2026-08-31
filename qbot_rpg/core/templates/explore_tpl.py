"""
模板分区：explore_tpl（探索指令（explore_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移（explore_commands 的
f-string / TPL 常量 / 中文输出拼接），默认值改动会导致现有测试断言失效——需与
explore_commands 渲染处 tpl_of(ctx, "explore_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— RUL-08 注册门槛（对齐 basic_commands；explore_commands 本地常量的模板化）——
    "explore_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",

    # —— /进入 move（通道行走）成功：CakeGame 模板 28 风格（用户 2026-08-27 拍板）——
    "explore_enter_ok": "✅ 你来到了「{name}」",
    "explore_map_desc": "地图介绍：{desc}",
    "explore_monster_line": "活动怪物：{items}",
    "explore_monster_row": "{i}.{nm}×{cnt}",
    "explore_monster_overflow": " …",
    "explore_channel_row": "{dir}：{name}",
    "explore_tip": "Tip:发送'位置'即可查询当前位置信息",

    # —— /进入 副本入口 / 失败 ——
    "explore_enter_dungeon": "✅ 你进入了「{name}」（副本）",
    "explore_enter_fail": "❌ {reason}",
    "explore_enter_fail_reason": "无法进入",
    "explore_enter_noarg": "❌ /进入：输入方向（上/下/左/右）或副本入口（序号/名称）",
    "explore_enter_not_wired": "❌ 进入功能未接线（引擎未加载）",
    "explore_enter_engine_error": "❌ 进入失败（引擎返回异常）",

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

    # —— /位置 ——
    "explore_position_unknown": "❌ 当前位置未知：{loc}（/进入 探索地图）",
    "explore_position_unknown_none": "无",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "explore_register_gate": set(),
    "explore_enter_ok": {"name"},
    "explore_map_desc": {"desc"},
    "explore_monster_line": {"items"},
    "explore_monster_row": {"i", "nm", "cnt"},
    "explore_monster_overflow": set(),
    "explore_channel_row": {"dir", "name"},
    "explore_tip": set(),
    "explore_enter_dungeon": {"name"},
    "explore_enter_fail": {"reason"},
    "explore_enter_fail_reason": set(),
    "explore_enter_noarg": set(),
    "explore_enter_not_wired": set(),
    "explore_enter_engine_error": set(),
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
    "explore_position_unknown": {"loc"},
    "explore_position_unknown_none": set(),
}
