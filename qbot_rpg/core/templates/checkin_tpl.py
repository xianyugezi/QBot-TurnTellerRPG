"""
模板分区：checkin_tpl（签到指令（checkin_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 checkin_commands.py 的逐字文案迁移（TPL_NO_CHECKIN /
TPL_NO_TABLE / 结算·状态·补签各 f-string / grant 标签），默认值改动会导致现有测试断言
失效——需与 checkin_commands 渲染处 tpl_of(ctx, "checkin_*", {...}) 一致。
"""

from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 结算/状态/补签 兜底与标题（TPL_NO_CHECKIN / TPL_NO_TABLE / 各 cmd 首行）——
    "checkin_unavailable": "❌ 签到暂不可用",
    "checkin_no_table": "❌ 没有这个签到表",
    "checkin_today_done": "✅ 今日签到完成",
    "checkin_today_idempotent": "今天已签到（重复指令，未重复发放）",
    "checkin_status_header": "✅ 签到状态",
    "checkin_makeup_failed": "❌ 补签失败",

    # —— 结算流水行（_table_rows 结算形态）——
    "checkin_already_signed_row": "今天已签到（不重复发奖）",
    "checkin_failed_fallback": "结算失败，已回滚",
    "checkin_daily_reward": "今日奖励：{grants}",
    "checkin_daily_none": "无",
    "checkin_progress_line": "连签天数：{streak} 天 ｜ 进度 {cur}/{total}",
    "checkin_streak_hit": "[连签里程碑达成] {grants}（连签 {days} 天）",
    "checkin_month_hit": "[月度累计达成] {grants}（本月签满 {days} 天）",

    # —— 状态流水行（_table_rows 状态形态）——
    "checkin_state_streak": "连签天数：{streak} 天",
    "checkin_state_month": "本月累计：{month_days} 天",
    "checkin_state_today_signed": "今日已签：{signed}",
    "checkin_state_makeup": "补签：{used}/{limit}",

    # —— 段头（_sections_from_tables / render_summary）——
    "checkin_section_title": "{name}（{type}）",
    "checkin_section_header": "━━ {title} ━━",

    # —— grant 标签片段（_grant_label 四类）——
    "checkin_grant_item": "{item}×{count}",
    "checkin_grant_currency": "{amount} {currency}",
    "checkin_grant_exp": "exp{amount}",
    "checkin_grant_rep": "声望{amount}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "checkin_unavailable": set(),
    "checkin_no_table": set(),
    "checkin_today_done": set(),
    "checkin_today_idempotent": set(),
    "checkin_status_header": set(),
    "checkin_makeup_failed": set(),
    "checkin_already_signed_row": set(),
    "checkin_failed_fallback": set(),
    "checkin_daily_reward": {"grants"},
    "checkin_daily_none": set(),
    "checkin_progress_line": {"streak", "cur", "total"},
    "checkin_streak_hit": {"grants", "days"},
    "checkin_month_hit": {"grants", "days"},
    "checkin_state_streak": {"streak"},
    "checkin_state_month": {"month_days"},
    "checkin_state_today_signed": {"signed"},
    "checkin_state_makeup": {"used", "limit"},
    "checkin_section_title": {"name", "type"},
    "checkin_section_header": {"title"},
    "checkin_grant_item": {"item", "count"},
    "checkin_grant_currency": {"amount", "currency"},
    "checkin_grant_exp": {"amount"},
    "checkin_grant_rep": {"amount"},
}
