"""模板分区：enhance_tpl（强化指令（enhance_commands）；2026-09-06 指令缺口补全批1路1）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 强化契约（细化_2c3b §1.5 模板汇总）逐字文案迁移；渲染走
tpl_of(ctx, "enhance_*", {...})。占位符白名单：每类模板允许的占位符；超出白名单
渲染时原样保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 排版符号 | → 等；
契约示例的 ⚙️/📖 图标按 forge F-1 同款裁决降级纯文本——数据型图标弃用）。

key 命名：enhance_<用途>。分区（段落）：
- 系统/守卫/解析错误：enhance_system_disabled / enhance_protect_disabled /
  enhance_err_* / enhance_not_found / enhance_ambiguous* / enhance_not_equip /
  enhance_no_enhance_slots / enhance_at_max / enhance_level_mismatch /
  enhance_material_* / enhance_protect_missing
- 成功/失败路径：enhance_roll_line / enhance_success / enhance_fail_low /
  enhance_fail_high / enhance_protect_saved / enhance_protect_flag
- /强化信息：enhance_info_* / enhance_info_at_max / enhance_info_rate_row /
  enhance_info_cost_row / enhance_info_hold
- 保护石：enhance_protect_*（复用普通强化模板 + 保护追加行）
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 系统/守卫 ——
    "enhance_system_disabled": "❌ 强化系统未启用（内容包未配置强化）",
    "enhance_protect_disabled": "❌ 强化保护未启用（未配置保护石）",
    "enhance_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",
    "enhance_battle_lock": "❌ 战斗中不可强化装备（战前强化）",

    # —— 解析错误（P-01~P-06 / §5.3）——
    "enhance_err_empty": "参数错误：缺少装备名（示例：/强化 铁剑 或 /强化 铁剑+5）",
    "enhance_err_space": "参数错误：装备名不含空格",
    "enhance_err_mark": "参数错误：等级标记须为非负整数（如 铁剑+5）",
    "enhance_err_mark_in_name": "参数错误：装备名不含 +（+ 仅作为等级标记）",
    "enhance_err_batch": "强化不支持批量强化（成功率随机，批量=连点爆装风险）",
    "enhance_err_extra": "参数错误：多余参数（示例：/强化 铁剑 或 /强化 铁剑+5）",

    # —— 装备匹配（GU-03 / P-05）——
    "enhance_not_found": "未找到「{name}」",
    "enhance_ambiguous_line": "{name}（+{level}｜上限 +{max}）",
    "enhance_ambiguous": "候选多个装备：{candidates}\n请发送完整装备名",
    "enhance_not_equippable": "「{name}」不是可强化装备（强化对象=已穿戴的装备）",
    "enhance_not_worn": "「{name}」未在装备栏（先 /使用 N 穿上再强化）",

    # —— 等级/上限（GU-04 / TC-14）——
    "enhance_at_max": "已达强化上限（+{max}）",
    "enhance_level_mismatch": "{name} 当前 +{cur}，请确认强化目标（+N 为等级标记）",

    # —— 材料（GU-05 / TC-04/05）——
    "enhance_material_short": "❌ 材料不足：需要 {need}；缺：{deficits}",
    "enhance_material_item": "{name}×{need}",
    "enhance_material_deficit": "{name}×{deficit}",
    "enhance_coin_short": "❌ 金币不足：需要 {cost}，当前 {coins_have}",
    "enhance_protect_missing": "需要 保护石 ×1（来源：炼金产出 / 商店 / 活动奖励）",

    # —— 结算行（§1.5 模板：成功率显示拆分 + 成功/失败分级）——
    "enhance_roll_line": "{name} → {name}+{to}（成功率 {rate}%"
                     "（基础 {base}% + 幸运 {luck}%）｜幸运修正已开）",
    "enhance_roll_line_luck_off": "{name} → {name}+{to}（成功率 {rate}%（幸运修正已关））",
    "enhance_roll_line_protect": "{name} → {name}+{to}（成功率 {rate}%"
                              "（基础 {base}% + 幸运 {luck}%）｜保护石生效）",
    "enhance_success": "✅ 成功！{attr} {old} → {new}",
    "enhance_fail_low": "❌ 强化失败，装备保持不变",
    "enhance_fail_high": "❌ 失败！强化等级 -1（{name}+{cur} → {name}+{down}）",
    "enhance_protect_saved": "❌ 失败！保护石抵消掉级（消耗 1 颗，{name}+{cur} 保持不变）",

    # —— /强化信息（§二 2.2 输出结构）——
    "enhance_info_title": "{name}+{cur}（品质：{quality}｜强化上限 +{max}）",
    "enhance_info_title_zero": "{name}（品质：{quality}｜强化上限 +{max}）",
    "enhance_info_rate_row": "→ +{to} 成功率：{rate}%（基础 {base}% + 幸运 {luck}%）",
    "enhance_info_rate_row_luck_off": "→ +{to} 成功率：{rate}%（幸运修正已关）",
    "enhance_info_cost_row": "→ +{to} 消耗：{stones} ｜ 持有：{stone_have} / 金币 {coins_have}",
    "enhance_info_at_max": "已达强化上限（+{max}）",
    "enhance_info_dist": "距离上限：{dist} 级",
    "enhance_info_hint": "发送 /强化 {name} 或 /强化保护 {name} 强化",

    # —— 强化保护（§三）——
    "enhance_protect_usage": "强化保护：带保护石强化"
                           "（失败有惩罚时消耗 1 颗免掉级）\n示例：/强化保护 铁剑+5",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "enhance_system_disabled": set(),
    "enhance_protect_disabled": set(),
    "enhance_register_gate": set(),
    "enhance_battle_lock": set(),
    "enhance_err_empty": set(),
    "enhance_err_space": set(),
    "enhance_err_mark": set(),
    "enhance_err_mark_in_name": set(),
    "enhance_err_batch": set(),
    "enhance_err_extra": set(),
    "enhance_not_found": {"name"},
    "enhance_ambiguous_line": {"name", "level", "max"},
    "enhance_ambiguous": {"candidates"},
    "enhance_not_equippable": {"name"},
    "enhance_not_worn": {"name"},
    "enhance_at_max": {"max"},
    "enhance_level_mismatch": {"name", "cur"},
    "enhance_material_short": {"need", "deficits"},
    "enhance_material_item": {"name", "need"},
    "enhance_material_deficit": {"name", "deficit"},
    "enhance_coin_short": {"cost", "coins_have"},
    "enhance_protect_missing": set(),
    "enhance_roll_line": {"name", "to", "rate", "base", "luck"},
    "enhance_roll_line_luck_off": {"name", "to", "rate"},
    "enhance_roll_line_protect": {"name", "to", "rate", "base", "luck"},
    "enhance_success": {"attr", "old", "new"},
    "enhance_fail_low": set(),
    "enhance_fail_high": {"name", "cur", "down"},
    "enhance_protect_saved": {"name", "cur"},
    "enhance_info_title": {"name", "cur", "quality", "max"},
    "enhance_info_title_zero": {"name", "quality", "max"},
    "enhance_info_rate_row": {"to", "rate", "base", "luck"},
    "enhance_info_rate_row_luck_off": {"to", "rate"},
    "enhance_info_cost_row": {"to", "stones", "stone_have", "coins_have"},
    "enhance_info_at_max": {"max"},
    "enhance_info_dist": {"dist"},
    "enhance_info_hint": {"name"},
    "enhance_protect_usage": set(),
}
