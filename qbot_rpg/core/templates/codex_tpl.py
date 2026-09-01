"""
模板分区：codex_tpl（图鉴指令（codex_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移，默认值改动会导致
现有测试断言失效——需与 codex_commands 渲染处 tpl_of(ctx, "codex_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 总览（无参 /图鉴；3f R-17/R-18）——
    "codex_overview_header": "【图鉴总览】",
    "codex_progress_line": "{label}：{pct}%（{seen}/{total}）",
    "codex_total_progress": "总完成度：{pct}%（{seen}/{total}）",
    "codex_next_tier": "下一档：{tier}%（还差 {gap}%）",
    "codex_tier_maxed": "已达最高档（100% 收藏家）",
    "codex_overview_hint": "提示：分册页 /图鉴 怪物 2（每页 5 条）",

    # —— 分册分页（3f R-19/R-20；??? 不泄露）——
    "codex_unknown_category": "❌ 未知图鉴分册。",
    "codex_category_header": "【{label}】",
    "codex_category_empty": "（还没有收集记录）",
    "codex_entry_line": "{mark} {name}{kill}{rumor}",
    "codex_killed_mark": "（已击杀）",
    "codex_rumor_mark": "（传闻）",
    "codex_unknown_name": "???",
    "codex_tail_tip": "共 {total} 条记录",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "codex_overview_header": set(),
    "codex_progress_line": {"label", "pct", "seen", "total"},
    "codex_total_progress": {"pct", "seen", "total"},
    "codex_next_tier": {"tier", "gap"},
    "codex_tier_maxed": set(),
    "codex_overview_hint": set(),
    "codex_unknown_category": set(),
    "codex_category_header": {"label"},
    "codex_category_empty": set(),
    "codex_entry_line": {"mark", "name", "kill", "rumor"},
    "codex_killed_mark": set(),
    "codex_rumor_mark": set(),
    "codex_unknown_name": set(),
    "codex_tail_tip": {"total"},
}
