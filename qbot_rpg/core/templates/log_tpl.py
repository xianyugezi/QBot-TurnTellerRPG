"""
模板分区：log_tpl（日志指令（log_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在各命令模块的逐字文案迁移，默认值改动会导致
现有测试断言失效——需与 log_commands 渲染处 tpl_of(ctx, "log_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 权限 / 空态 ——
    "log_permission_denied": "❌ 没有 GM 权限，无法查看系统日志。",
    "log_adventure_empty": "（暂无冒险日志）",
    "log_bio_empty": "（暂无传记）",
    "log_sys_empty": "（暂无系统日志）",

    # —— CakeGame 式尾段 Tip（2026-08-27 用户拍板：列表尾段统一当前页 + Tip）——
    "log_adv_tail_tip": "发送'日志 传记'回溯冒险规律",
    "log_bio_tail_tip": "发送'日志 传记 N'翻看更早的段落",
    "log_sys_tail_tip": "发送'日志 条数=50'扩大查看窗口",

    # —— 冒险日志视图（3f R-03：页头/分组标题/条目行/首见标记）——
    "log_adventure_header": "【冒险日志】",
    "log_group_header": "■ {name}",
    "log_adventure_line": "[日志] {time} {weather} · {text}",
    "log_first_seen_mark": "【首见】",

    # —— 六类条目文本（3f R-02 表逐类模板渲染，D-01 不落自由文本）——
    # 带值变体（{name}/{pct}）；*_none = 无值兜底变体（逐字对齐既有输出）
    "log_entry_first_kill": "首次击败 {name}",
    "log_entry_first_kill_none": "首次击败 未知目标",
    "log_entry_first_crown": "首次钓获金冠 {name}",
    "log_entry_first_crown_none": "首次钓获金冠",
    "log_entry_story_node": "剧情节点：{name}",
    "log_entry_story_node_none": "剧情节点推进",
    "log_entry_hidden_find": "首次发现隐藏要素『{name}』",
    "log_entry_hidden_find_none": "首次发现隐藏要素",
    "log_entry_milestone": "图鉴完成度达到 {pct}%",
    "log_entry_milestone_none": "图鉴里程碑达成",
    "log_entry_codex_new": "图鉴新增：{name}",
    "log_entry_codex_new_none": "图鉴新增",
    "log_entry_fallback": "冒险记录",   # 非六类（防御路径，正常不进冒险日志分组）

    # —— 传记视图（3f R-04：段头/段日行/快照统计）——
    "log_bio_header": "【传记】第 {page} 段 / 共 {total} 段",
    "log_bio_day": "■ {day} · {group}",
    "log_bio_stats": "[传记] {group} {count} 条 · {weather}",

    # —— GM 系统日志视图（3f R-06：页头/本地兜底事件行格式）——
    "log_sys_header": "【系统日志】第 {page} 页 / 共 {pages} 页",
    "log_sys_line": "[{ts}] /{cmd}{params} {result} by {qq}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "log_permission_denied": set(),
    "log_adventure_empty": set(),
    "log_bio_empty": set(),
    "log_sys_empty": set(),
    "log_adv_tail_tip": set(),
    "log_bio_tail_tip": set(),
    "log_sys_tail_tip": set(),
    "log_adventure_header": set(),
    "log_group_header": {"name"},
    "log_adventure_line": {"time", "weather", "text"},
    "log_first_seen_mark": set(),
    "log_entry_first_kill": {"name"},
    "log_entry_first_kill_none": set(),
    "log_entry_first_crown": {"name"},
    "log_entry_first_crown_none": set(),
    "log_entry_story_node": {"name"},
    "log_entry_story_node_none": set(),
    "log_entry_hidden_find": {"name"},
    "log_entry_hidden_find_none": set(),
    "log_entry_milestone": {"pct"},
    "log_entry_milestone_none": set(),
    "log_entry_codex_new": {"name"},
    "log_entry_codex_new_none": set(),
    "log_entry_fallback": set(),
    "log_bio_header": {"page", "total"},
    "log_bio_day": {"day", "group"},
    "log_bio_stats": {"group", "count", "weather"},
    "log_sys_header": {"page", "pages"},
    "log_sys_line": {"ts", "cmd", "params", "result", "qq"},
}
