"""
模板分区：forge_tpl（锻造指令（forge_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 forge_commands.py（守卫/成功/失败/预览/图纸/
锻造树/套装/客制 等 f-string 与模块常量）的逐字文案迁移，默认值改动会导致现有测试
断言失效——需与 forge_commands.py 渲染处 tpl_of(ctx, "forge_*", {...}) 一致。

key 命名：forge_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样
保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → × / ■ 等）。

分区（段落）：
- 系统/守卫/解析错误：forge_system_disabled / forge_tree_no_root / forge_err_* /
  forge_not_found / forge_ambiguous* / forge_redflag_reject / forge_prereq* /
  forge_material_* / forge_level_gate / forge_king_gate*（forge_atomic/_forge_once/
  parse_forge_target）
- 批量与成功路径：forge_batch_* / forge_success* / forge_coin_short 等（_execute）
- 预览卡片与确认窗：forge_preview_* / forge_req_line / forge_element_summary /
  forge_atk_summary / forge_slots* / forge_continue* / forge_confirm_none /
  forge_preview_expired（_render_preview / cmd_confirm）
- /图纸：forge_blueprint_* / forge_terminal_element / forge_branch* / forge_redflag_suffix
- /锻造树：forge_tree_*（cmd_forge_tree 分页 + _tree_row_line 状态）
- /套装 /客制：forge_sets_* / forge_augments_*（cmd_sets / cmd_augments）

注意：模块级常量（TREE_EMPTY_PAGE / TREE_TAIL_TIP / SETS_LOCKED_MSG 等）在
forge_commands.py 中保留为向后兼容导出（值 = 本分区默认文案），渲染一律走 tpl_of。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 系统/守卫/解析错误（forge_atomic / _forge_once / parse_forge_target）——
    "forge_system_disabled": "❌ 锻造系统未启用（内容包 forge.json 未注册）",
    "forge_tree_no_root": "❌ 当前锻造树没有根节点（内容包 forge.json 异常）",
    "forge_err_empty": "参数错误：缺少锻造目标（示例：/锻造 铁剑 或 /锻造 炎剑Ⅱ*3）",
    "forge_err_space": "参数错误：节点名不含空格",
    "forge_err_qty": "参数错误：数量须为正整数（示例：/锻造 炎剑Ⅱ*3）",
    "forge_err_charset": "参数错误：节点名含非法字符"
                         "（仅允许 中文/字母/数字/·/Ⅰ-Ⅹ/【】/-/■）",
    "forge_not_found": "未找到「{name}」→ /锻造树 查看可锻装备",
    "forge_ambiguous_item": "{name}（Lv{level}）",
    "forge_ambiguous": "候选多个节点：{candidates} → /锻造树 查看可锻装备",
    "forge_redflag_reject": "❌ 已失效：物品已删除",
    "forge_prereq_hint": "需先锻造：{name}",
    "forge_prereq_hint_default": "需先锻造：前置节点",
    "forge_prereq": "❌ {hint} → /图纸 查看全链",
    "forge_material_item": "{name}×{need}",
    "forge_material_deficit": "{name}×{deficit}",
    "forge_material_deficit_source": "{base}（来源：{src}）",
    "forge_material_shortfall": "❌ 素材不足：需要 {need}；缺：{deficits} → /图纸 查看全链",
    "forge_level_gate": "需要 {need_rank} 级，当前 {cur_rank}（还差 {missing} 熟练）",
    "forge_king_gate": "❌ {message}",
    "forge_king_gate_fallback": "未获铸造王",

    # —— 批量与成功路径（forge_atomic 批量 / _execute 原子结算）——
    "forge_batch_fail": "第 {i} 次失败，已成功 {successes} 次\n{out}",
    "forge_batch_success": "{head} ×{n}\n{tail}",
    "forge_material_deduct_fail": "❌ 素材扣减失败，本次锻造未执行（零副作用）",
    "forge_coin_short": "❌ 金币不足：需要 {cost}，当前 {coins_have}",
    "forge_item_add_fail": "❌ 装备入包失败，本次锻造未执行（零副作用）",
    "forge_exp_fail": "❌ 熟练入账失败，本次锻造已回滚（零副作用）",
    "forge_success": "✅ {name} 锻造完成！\n{fields}",
    "forge_success_atk": "攻击 {atk}",
    "forge_success_slot": "部位：{slot}",
    "forge_success_slot_text": "槽位：{slot}",
    "forge_success_quality": "品质：{quality}（固定）",
    "forge_slot_none": "无",

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
    "forge_redflag_suffix": "（已失效：物品已删除）",

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
    "forge_sets_empty": "当前没有可组成的套装（内容包 forge.json 未配置 sets 段）",
    "forge_augments_empty": "当前没有可用的客制项（内容包 forge.json 未配置 augments 段）",
    "forge_sets_seg": "{name}（{have}/{total} 件）",
    "forge_sets_row": "{index}. {value}",
    "forge_augments_seg": "{name}（{kind}：{effect}）",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    # —— 系统/守卫/解析错误 ——
    "forge_system_disabled": set(),
    "forge_tree_no_root": set(),
    "forge_err_empty": set(),
    "forge_err_space": set(),
    "forge_err_qty": set(),
    "forge_err_charset": set(),
    "forge_not_found": {"name"},
    "forge_ambiguous_item": {"name", "level"},
    "forge_ambiguous": {"candidates"},
    "forge_redflag_reject": set(),
    "forge_prereq_hint": {"name"},
    "forge_prereq_hint_default": set(),
    "forge_prereq": {"hint"},
    "forge_material_item": {"name", "need"},
    "forge_material_deficit": {"name", "deficit"},
    "forge_material_deficit_source": {"base", "src"},
    "forge_material_shortfall": {"need", "deficits"},
    "forge_level_gate": {"need_rank", "cur_rank", "missing"},
    "forge_king_gate": {"message"},
    "forge_king_gate_fallback": set(),

    # —— 批量与成功路径 ——
    "forge_batch_fail": {"i", "successes", "out"},
    "forge_batch_success": {"head", "n", "tail"},
    "forge_material_deduct_fail": set(),
    "forge_coin_short": {"cost", "coins_have"},
    "forge_item_add_fail": set(),
    "forge_exp_fail": set(),
    "forge_success": {"name", "fields"},
    "forge_success_atk": {"atk"},
    "forge_success_slot": {"slot"},
    "forge_success_slot_text": {"slot"},
    "forge_success_quality": {"quality"},
    "forge_slot_none": set(),

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
    "forge_redflag_suffix": set(),

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
