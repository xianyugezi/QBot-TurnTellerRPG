"""
模板分区：quest_tpl（任务指令（quest_commands 剩余行）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移，默认值改动会导致
现有测试断言失效——需与 quest_commands 渲染处 tpl_of(ctx, "quest_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 任务板（/任务 无参·页码；TPL_NO_BOARD / TPL_NO_QUEST / _EMPTY_BOARD 迁移）——
    "quest_no_board": "❌ 任务板暂不可用",
    "quest_no_quest": "❌ 任务不存在",
    "quest_empty_board": "（任务板空空如也）",
    "quest_board_section_header": "━━ {title} ━━",

    # —— 任务板条目行（board_line：主线前缀 / marked 后缀 / 序号行 / 进度摘要）——
    "quest_board_line": "{index}. {name}",
    "quest_board_main_prefix": "[主线] {name}",
    "quest_board_marked_suffix": "{name}*",
    "quest_board_progress": "  进度 {cur}/{target}",

    # —— 三原语进度串（progress_text：base + 可选 param/current 片段）——
    "quest_progress_base": "{var} {op} {target}",
    "quest_progress_base_no_target": "{var} {op}",
    "quest_progress_param": "（{param}）",
    "quest_progress_current": "，当前 {current}",

    # —— /任务 信息 N（info_text 正文）——
    "quest_info_header": "✅ 任务进度：{name}",
    "quest_info_line": "- {text} {mark}",
    "quest_info_met": "✅ 条件已满足，可交付（/任务 交付 {seq}）",
    "quest_info_not_met": "❌ 条件未达成，继续努力",

    # —— /任务 接取 N（引擎 message 透传；缺省兜底）——
    "quest_accept_failed": "❌ 接取失败",

    # —— /任务 交付 N（引擎 message 透传；缺省兜底 + P1-2 跳过注记）——
    "quest_deliver_failed": "❌ 交付失败",
    "quest_deliver_skipped": "（跳过：{reason}）",
    "quest_deliver_skipped_plain": "（跳过）",

    # —— /任务 放弃 N（引擎 message 透传；缺省兜底）——
    "quest_abandon_failed": "❌ 放弃失败",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "quest_no_board": set(),
    "quest_no_quest": set(),
    "quest_empty_board": set(),
    "quest_board_section_header": {"title"},
    "quest_board_line": {"index", "name"},
    "quest_board_main_prefix": {"name"},
    "quest_board_marked_suffix": {"name"},
    "quest_board_progress": {"cur", "target"},
    "quest_progress_base": {"var", "op", "target"},
    "quest_progress_base_no_target": {"var", "op"},
    "quest_progress_param": {"param"},
    "quest_progress_current": {"current"},
    "quest_info_header": {"name"},
    "quest_info_line": {"text", "mark"},
    "quest_info_met": {"seq"},
    "quest_info_not_met": set(),
    "quest_accept_failed": set(),
    "quest_deliver_failed": set(),
    "quest_deliver_skipped": {"reason"},
    "quest_deliver_skipped_plain": set(),
    "quest_abandon_failed": set(),
}
