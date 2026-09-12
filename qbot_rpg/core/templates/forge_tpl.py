"""
模板分区：forge_tpl（锻造指令（forge_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 forge_commands.py（守卫/成功/失败/预览/图纸/
锻造树/套装/客制 等 f-string 与模块常量）的逐字文案迁移，默认值改动会导致现有测试
断言失效——需与 forge_commands.py 渲染处 tpl_of(ctx, "forge_*", {...}) 一致。

2026-09-12 消息模板重构（批3·路I）：执行流 33 键（系统/守卫/解析错误 + 批量/成功路径 +
forge_redflag_suffix）迁至全量表 qbot_rpg/core/templates/template_table.json，按
手机QQ 14 全角新规范重写；同名 key 由新表在聚合时覆盖本分区。

key 命名：forge_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样
保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → × / ■ 等）。

分区（段落）：
- 系统/守卫/解析错误（2026-09-12 批3·路I 迁全量表 template_table.json）：
  forge_system_disabled / forge_tree_no_root / forge_err_* / forge_not_found /
  forge_ambiguous* / forge_redflag_reject / forge_prereq* / forge_material_* /
  forge_level_gate / forge_king_gate*（forge_atomic/_forge_once/parse_forge_target）
- 批量与成功路径（2026-09-12 批3·路I 迁全量表）：forge_batch_* / forge_success* /
  forge_coin_short 等（_execute）
- 预览卡片与确认窗：forge_preview_* / forge_req_line / forge_element_summary /
  forge_atk_summary / forge_slots* / forge_continue* / forge_confirm_none /
  forge_preview_expired（_render_preview / cmd_confirm）
- /图纸：forge_blueprint_* / forge_terminal_element / forge_branch*（forge_redflag_suffix
  已迁全量表 · 批3·路I）
- /锻造树：forge_tree_*（cmd_forge_tree 分页 + _tree_row_line 状态）
- /套装 /客制：forge_sets_* / forge_augments_*（cmd_sets / cmd_augments）

注意：模块级常量（TREE_EMPTY_PAGE / TREE_TAIL_TIP / SETS_LOCKED_MSG 等）在
forge_commands.py 中保留为向后兼容导出（值 = 本分区默认文案），渲染一律走 tpl_of。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # 2026-09-12 批3·路I：系统/守卫/解析错误 + 批量与成功路径 33 键已迁全量表
    #（template_table.json 同名 key 聚合覆盖；含 forge_redflag_suffix）。

    # —— 预览卡片与确认窗（_render_preview / cmd_confirm）——
    "forge_preview_occupied": "已有待确认的锻造预览，请先 /确认 或等待超时\n{card}",
    "forge_preview_title": "{name}（{summary}）",
    "forge_preview_material_line": "素材：{mats} | {req}",
    "forge_req_line": "需求：铸造 {tier} 级",
    "forge_element_summary": "{element_cn}属性{value}",
    "forge_atk_summary": "攻击+{atk}",
    "forge_slots_item": "{level} 级槽 ×{count}",
    "forge_slots_line": "孔位：{seg}",
    "forge_continue": "可继续锻造：{child}",
    "forge_continue_endpoint": "可继续锻造：{child} → {endpoint}",
    "forge_confirm_none": "当前无可确认的锻造预览",
    "forge_preview_expired": "预览已过期，请重新 /锻造 <节点> 预览",

    # —— /图纸（cmd_blueprint / _render_blueprint / _node_display_name / 分支行）——
    "forge_blueprint_not_found": "未找到「{name}」相关锻造链",
    "forge_blueprint_title": "{name}派生链：",
    "forge_terminal_element": "{name}（{element}）",
    "forge_branch_seg": "{name} ← {mat}",
    "forge_branch_line": "{prefix} 分支：{seg}",

    # —— /锻造树（cmd_forge_tree 分页 + _tree_row_line 状态）——
    "forge_tree_row": "{name}（{level}级/{tier}）",
    "forge_tree_status_prereq": "需前置",
    "forge_tree_status_level": "需等级",
    "forge_tree_status_ok": "可锻",
    "forge_tree_empty_page": "该页暂无锻造装备（/锻造树 共 {total_pages} 页）",
    "forge_tree_tail_tip": "发送'/锻造 装备名'即可锻造",

    # —— /套装 /客制（cmd_sets / cmd_augments）——
    "forge_sets_locked": "未解锁 套装（消耗 1 SP 在 技能面板 解锁）",
    "forge_augments_locked": "未解锁 客制（消耗 1 SP 在 技能面板 解锁）",
    "forge_sets_empty": "当前没有可组成的锻造套装（集齐同系列锻造装备即可组成；套装目录待内容配置后开放）",
    "forge_augments_empty": "当前没有可用的客制项（内容包 forge.json 未配置 augments 段）",
    "forge_sets_seg": "{name}（{have}/{total} 件）",
    "forge_sets_row": "{index}. {value}",
    "forge_augments_seg": "{name}（{kind}：{effect}）",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    # 2026-09-12 批3·路I：系统/守卫/解析错误 + 批量与成功路径 共 32 键已迁全量表
    #（白名单由表文本自动派生；forge_redflag_suffix 见 /图纸 段注）。

    # —— 预览卡片与确认窗 ——
    "forge_preview_occupied": {"card"},
    "forge_preview_title": {"name", "summary"},
    "forge_preview_material_line": {"mats", "req"},
    "forge_req_line": {"tier"},
    "forge_element_summary": {"element_cn", "value"},
    "forge_atk_summary": {"atk"},
    "forge_slots_item": {"level", "count"},
    "forge_slots_line": {"seg"},
    "forge_continue": {"child"},
    "forge_continue_endpoint": {"child", "endpoint"},
    "forge_confirm_none": set(),
    "forge_preview_expired": set(),

    # —— /图纸 ——
    "forge_blueprint_not_found": {"name"},
    "forge_blueprint_title": {"name"},
    "forge_terminal_element": {"name", "element"},
    "forge_branch_seg": {"name", "mat"},
    "forge_branch_line": {"prefix", "seg"},
    # forge_redflag_suffix：已迁全量表（批3·路I；白名单自动派生）。

    # —— /锻造树 ——
    "forge_tree_row": {"name", "level", "tier"},
    "forge_tree_status_prereq": set(),
    "forge_tree_status_level": set(),
    "forge_tree_status_ok": set(),
    "forge_tree_empty_page": {"total_pages"},
    "forge_tree_tail_tip": set(),

    # —— /套装 /客制 ——
    "forge_sets_locked": set(),
    "forge_augments_locked": set(),
    "forge_sets_empty": set(),
    "forge_augments_empty": set(),
    "forge_sets_seg": {"name", "have", "total"},
    "forge_sets_row": {"index", "value"},
    "forge_augments_seg": {"name", "kind", "effect"},
}
