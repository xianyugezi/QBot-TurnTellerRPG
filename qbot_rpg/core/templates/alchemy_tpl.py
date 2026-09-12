"""
模板分区：alchemy_tpl（炼金指令（alchemy_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 alchemy_commands.py 的逐字文案迁移（全部展示
文案，f-string 约 137 处），默认值改动会导致现有测试断言失效——需与 alchemy_commands.py
渲染处 tpl_of(ctx, "alchemy_*", {...}) 一致。机械性/纯逻辑（数值计算、状态机、列表
join/前缀拼接）不动，仅展示文案入表。

key 命名：alchemy_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样
保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 「」排版符，D-5B）。

2026-09-12 消息模板重构（批3·路H）：炼金主流程与材料 28 键（通用错误/守卫、/合成失败、
面板/触媒/刻度、批量、确认复核差异、缺参用法）迁至全量表 template_table.json（按新规范
全新重写；新表同名 key 在聚合时覆盖本分区）。
2026-09-12（批4·路K）：投料/继承/确认 30 键（M-03 投料反馈、M-04 继承成功/失败透传、
终态错误）迁至全量表；本分区仅保留尚未迁移的键（珠与合成/深度炼金/图鉴技能/即时调合/
资源循环/协力/分解）。
2026-09-12（批5·路N）：挑战/深度/进化/教学 26 键迁至全量表（本路收口后本分区仅剩
珠与合成/图鉴技能面板/即时调合/资源循环/协力/分解，待后续批迁移）。
2026-09-12（批6·路Q）：拆解 6 键 + 镶嵌/拆珠/珠升阶/成品合成/配方合成/特性合成/登记/复制
16 键迁至全量表（本分区仅剩图鉴技能面板/即时调合/资源循环/协力，待后续批迁移）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— /分解（终态）/ 珠与合成 ——
    # 2026-09-12（批6·路Q）：拆解 6 键 + 镶嵌/拆珠/珠升阶/成品合成/配方合成/特性合成/登记/复制 16 键
    # 迁至全量表 template_table.json（按新规范拆行压宽/免斜杠/❌+原因），本分区不再保留。

    # —— 深度炼金（/深度炼金 /进化 /镶核心 /加成 /挑战）——
    # 2026-09-12（批5·路N）：深度/挑战/进化 20 键 + 教学 6 键迁至全量表
    # template_table.json（按新规范拆行压宽/免斜杠/错误行 ❌+原因），本分区不再保留。

    # —— 图鉴 /技能面板 /教学（查看态）——
    "alchemy_codex_unavailable": "❌ 图鉴不可用（{reason}）",
    "alchemy_codex_line": "炼金图鉴：已点亮 {lit}/{total}",
    "alchemy_codex_king_hint": "（点亮 {total} → 炼金王称号）",
    "alchemy_codex_reward_exp": "成长奖励：经验 +{exp}",
    "alchemy_codex_reward": "成长奖励：",
    "alchemy_codex_reward_recipes": "，新配方：{recipes}",
    "alchemy_codex_king_granted": "✅ 已获得「炼金王」称号（图鉴全点亮）",
    "alchemy_sp_panel": "SP {sp} 点可用：{items}",
    "alchemy_sp_panel_empty": "SP {sp} 点可用",
    "alchemy_sp_item_used": "{name}（已 {n} 次）",
    "alchemy_sp_insufficient": "❌ SP 不足",
    "alchemy_sp_not_repeatable": "❌ 该技能面板项不可重复解锁",
    "alchemy_sp_max_repeat": "❌ 已达该技能面板项解锁上限",
    "alchemy_sp_not_found": "❌ 技能面板项不存在",
    "alchemy_sp_unavailable": "❌ 技能面板暂不可用",
    "alchemy_sp_unlock_fail": "❌ 解锁失败",
    "alchemy_sp_item_not_found": "❌ 技能面板项不存在：{name}",
    "alchemy_sp_panel_unavailable": "❌ 技能面板不可用（{reason}）",
    # 2026-09-12（批5·路N）：解锁公告项 + 教学 5 键迁至全量表（见上注）。

    # —— /即时调合（M-17 战斗一行）——
    "alchemy_instant_not_battle": "即时调合仅限战斗中",
    "alchemy_instant_limit": "本场战斗已使用过即时调合（限 1 次/场）",
    "alchemy_instant_fail": "❌ 即时调合失败",
    "alchemy_instant_bag": "✅ 已入包：{name}×1（本场战斗内不可再使用）",
    "alchemy_instant_damage": "{name}！造成 {damage} 伤害",
    "alchemy_instant_used": "✅ 已使用 {name}",

    # —— 资源循环（/种植 /收获 /代工 /收取）——
    "alchemy_plant_level": "❌ 等级不足：炼金职业需达到 正式（种植解锁）",
    "alchemy_plant_fail": "❌ 种植失败",
    "alchemy_plant_ok": "✅ 已种植",
    "alchemy_harvest_level": "❌ 等级不足：炼金职业需达到 正式（收获解锁）",
    "alchemy_harvest_fail": "❌ 收获失败",
    "alchemy_harvest_ok": "✅ 已收获",
    "alchemy_helper_level": "❌ 等级不足：代工助手需炼金职业 ≥ 精通",
    "alchemy_helper_task_invalid": "❌ 任务格式非法",
    "alchemy_helper_assign_fail": "❌ 代工设定失败",
    "alchemy_helper_assign_ok": "✅ 已设定代工",
    "alchemy_collect_empty": "❌ 没有待收取的代工产出",
    "alchemy_collect_ok": "✅ 已收取",

    # —— /协力（F-15/M-15）——
    "alchemy_assist_not_same_group": "❌ 对方不在当前群内",
    "alchemy_assist_materials_missing": "❌ 材料不足：缺 {diff}",
    "alchemy_assist_ok": "协力调和：{name}加入，获得随机加成：{desc}",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    # —— /分解 / 珠与合成 ——
    # 2026-09-12（批6·路Q）：拆解 6 键 + 珠与合成 16 键白名单随键迁表（表内自动派生）。

    # —— 深度炼金 ——
    # 2026-09-12（批5·路N）：深度/挑战/进化/教学 26 键白名单随键迁表（表内自动派生）。

    # —— 图鉴 /技能面板 /教学 ——
    "alchemy_codex_unavailable": {"reason"},
    "alchemy_codex_line": {"lit", "total"},
    "alchemy_codex_king_hint": {"total"},
    "alchemy_codex_reward_exp": {"exp"},
    "alchemy_codex_reward": set(),
    "alchemy_codex_reward_recipes": {"recipes"},
    "alchemy_codex_king_granted": set(),
    "alchemy_sp_panel": {"sp", "items"},
    "alchemy_sp_panel_empty": {"sp"},
    "alchemy_sp_item_used": {"name", "n"},
    "alchemy_sp_insufficient": set(),
    "alchemy_sp_not_repeatable": set(),
    "alchemy_sp_max_repeat": set(),
    "alchemy_sp_not_found": set(),
    "alchemy_sp_unavailable": set(),
    "alchemy_sp_unlock_fail": set(),
    "alchemy_sp_item_not_found": {"name"},
    "alchemy_sp_panel_unavailable": {"reason"},
    # 2026-09-12（批5·路N）：解锁公告项 + 教学 5 键白名单随键迁表（表内自动派生）。

    # —— /即时调合 ——
    "alchemy_instant_not_battle": set(),
    "alchemy_instant_limit": set(),
    "alchemy_instant_fail": set(),
    "alchemy_instant_bag": {"name"},
    "alchemy_instant_damage": {"name", "damage"},
    "alchemy_instant_used": {"name"},

    # —— 资源循环 ——
    "alchemy_plant_level": set(),
    "alchemy_plant_fail": set(),
    "alchemy_plant_ok": set(),
    "alchemy_harvest_level": set(),
    "alchemy_harvest_fail": set(),
    "alchemy_harvest_ok": set(),
    "alchemy_helper_level": set(),
    "alchemy_helper_task_invalid": set(),
    "alchemy_helper_assign_fail": set(),
    "alchemy_helper_assign_ok": set(),
    "alchemy_collect_empty": set(),
    "alchemy_collect_ok": set(),

    # —— /协力 ——
    "alchemy_assist_not_same_group": set(),
    "alchemy_assist_materials_missing": {"diff"},
    "alchemy_assist_ok": {"name", "desc"},
}
