"""
模板分区：investigate_tpl（调查指令（investigate_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 investigate_commands.py 的逐字文案迁移（注册门槛 /
无地图兜底 / 环境快照头 / 泛化环境文本池 / 去重简短确认 / 蹲点默认演出与信号 / 隐藏地图
默认介绍 / 发现卡片 / 图鉴传闻引用），默认值改动会导致现有测试断言失效——需与
investigate_commands 渲染处 tpl_of(ctx, "investigate_*", {...}) 一致。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— RUL-08 注册门槛（对齐 basic_commands / explore_commands；本地常量的模板化）——
    "investigate_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",

    # —— 无当前位置调查兜底（R-07 无 map_def 场景）——
    "investigate_no_map": "❌ 无法确定当前位置，无法调查。",

    # —— 环境快照头（3f R-05 展示口径；缺失 → "--"）——
    "investigate_env_header": "（{season}·{period}·{weather}）",

    # —— 泛化环境文本池（R-22 / R-07 零暗示；rng 确定性选择，工程补白 4）——
    "investigate_ambient_1": "四下寂静，只有风声掠过旷野。",
    "investigate_ambient_2": "你仔细环顾四周，一切如常。",
    "investigate_ambient_3": "眼前景象与平日无异，只有惯常的声响。",
    "investigate_ambient_4": "雾霭缓缓流动，林间传来零星的鸟鸣。",
    "investigate_ambient_5": "风穿过林间，带起一阵沙沙声，别无他物。",

    # —— 去重简短确认（R-11 / TC-15：已 one_shot 只回简短确认，无正文无卡片）——
    "investigate_eggshell_done": "这里你已经仔细查看过了。",
    "investigate_hunt_done": "这一带你已经确认过了，没有新的发现。",
    "investigate_hidden_map_done": "这条路径你已经知晓，无需再探。",

    # —— 蹲点默认演出/信号（R-09 / 3f L101-106）——
    "investigate_hunt_intro": "你屏息凝神，远处传来低沉的狼嗥，与平时的风声不同……",
    "investigate_hunt_signal": "巨大的黑影在雾气中若隐若现——战斗即将开始！",

    # —— 隐藏地图入口揭示默认介绍（F-07 无 intro/desc 时兜底）——
    "investigate_hidden_map_text": "你拨开藤蔓，一条从未见过的路径显现在眼前。",

    # —— 发现卡片与图鉴传闻引用（R-15 / R-23 L349）——
    "investigate_discover_card": "【发现】{label}{title}",
    "investigate_codex_ref": "【图鉴-{name}（传说）】传闻中记载了它的出没之谜。",
    "investigate_discover_label_boss": "隐藏 BOSS：",
    "investigate_discover_label_map": "隐藏地图：",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "investigate_register_gate": set(),
    "investigate_no_map": set(),
    "investigate_env_header": {"season", "period", "weather"},
    "investigate_ambient_1": set(),
    "investigate_ambient_2": set(),
    "investigate_ambient_3": set(),
    "investigate_ambient_4": set(),
    "investigate_ambient_5": set(),
    "investigate_eggshell_done": set(),
    "investigate_hunt_done": set(),
    "investigate_hidden_map_done": set(),
    "investigate_hunt_intro": set(),
    "investigate_hunt_signal": set(),
    "investigate_hidden_map_text": set(),
    "investigate_discover_card": {"label", "title"},
    "investigate_codex_ref": {"name"},
    "investigate_discover_label_boss": set(),
    "investigate_discover_label_map": set(),
}
