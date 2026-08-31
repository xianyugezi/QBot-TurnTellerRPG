"""
模板分区：alchemy_tpl（炼金指令（alchemy_commands）；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 alchemy_commands.py 的逐字文案迁移（全部展示
文案，f-string 约 137 处），默认值改动会导致现有测试断言失效——需与 alchemy_commands.py
渲染处 tpl_of(ctx, "alchemy_*", {...}) 一致。机械性/纯逻辑（数值计算、状态机、列表
join/前缀拼接）不动，仅展示文案入表。

key 命名：alchemy_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样
保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 「」排版符，D-5B）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— 通用错误/守卫（多指令共用）——
    "alchemy_level_insufficient": "❌ 等级不足",
    "alchemy_recipe_not_found": "❌ 配方不存在：{target}",
    "alchemy_item_not_found": "❌ 道具不存在：{target}",
    "alchemy_equip_not_found": "❌ 装备不存在：{name}",
    "alchemy_jewel_not_found": "❌ 装饰珠不存在：{name}",
    "alchemy_trait_not_found": "❌ 特性不存在：{name}",
    "alchemy_energy_insufficient": "能量不足",
    "alchemy_materials_insufficient": "材料不足",
    "alchemy_materials_insufficient_diff": "材料不足：{diff}",
    "alchemy_materials_insufficient_mark": "❌ 材料不足",
    "alchemy_materials_insufficient_mark_diff": "❌ 材料不足：{diff}",
    "alchemy_battle_blocked": "战斗中使用 /即时调合 <配方>（不进入调合会话）",
    "alchemy_no_materials": "（无）",
    "alchemy_shortfall_item": "缺 {name}×{need}",
    "alchemy_material_entry_plain": "{name}×{count}",
    "alchemy_material_entry_elem": "{name}×{count}({cn}{val})",
    "alchemy_pp_used": "PP {used}/{budget}",

    # —— /合成 ——
    "alchemy_synth_fail": "❌ 合成失败",

    # —— /炼金 面板（M-02）+ 触媒 ——
    "alchemy_catalyst_invalid": "触媒无效",
    "alchemy_panel": "{recipe_name}（配方Lv{level}）：材料：{mats}\n"
                    "属性刻度：{scales} | 特性位 {traits_used}/{traits_max} | "
                    "PP {pp_used}/{pp_budget} | 投入次数 {units}/{slots}",
    "alchemy_scale_item": "{cn}≥{th} 显现\"{effect}\"",
    "alchemy_no_scale": "（无刻度要求）",

    # —— /炼金 批量（BATCH-01~05）——
    "alchemy_batch_no_output": "❌ 该配方无法批量调合",
    "alchemy_batch_coins": " + 金币 {coins_need}",
    "alchemy_batch_output": "✅ {output_name} ×{qty}（批量调合：消耗 {mats_text}"
                            "{coin_text}）｜平均品质 {score}·{tier}",
    "alchemy_batch_energy_suffix": "｜{note}",

    # —— /投料（M-03 反馈 + 失败透传）——
    "alchemy_feed_elem_score": "{elem_cn}+{main_score}",
    "alchemy_feed_chain": "连锁 {segments} 段",
    "alchemy_feed_trait_item": "{name}(PP{pp})",
    "alchemy_feed_trait_gold": "金色：{items}",
    "alchemy_feed_trait_awaken": "觉醒：{items}",
    "alchemy_feed_traits_header": "可继承特性：{items}",
    "alchemy_feed_chain_effect": "连锁 {segments} 段 → 效果等级 {effect_level}",
    "alchemy_feed_scale_met": "刻度达标 {cn}+{score}（刻度 {th}·{effect}）",
    "alchemy_feed_slots_overflow": "投料超槽位",
    "alchemy_feed_expert_required": "全物入料需专家级",
    "alchemy_feed_item_not_found": "材料不存在",
    "alchemy_feed_fail": "投料失败",
    "alchemy_auto_balance_fail": "❌ 自动配平失败",

    # —— /继承 /继承超（M-04 + 失败透传）——
    "alchemy_inherit_no_slot": "❌ 见习无继承位",
    "alchemy_inherit_pp": "❌ PP 不足",
    "alchemy_inherit_overflow": "❌ 继承超 {limit} 项",
    "alchemy_inherit_group_conflict": "❌ 互斥组内最多 1 项：{g}",
    "alchemy_inherit_not_repeatable": "❌ 该特性不可重复继承",
    "alchemy_inherit_gold_occupied": "❌ 第 4 位金色已占用",
    "alchemy_inherit_fail": "❌ {msg}",
    "alchemy_inherit_fail_msg": "继承失败",
    "alchemy_inherit_done": "已继承：{names}",
    "alchemy_inherit_negatives": "负面特性：{names}",
    "alchemy_inherit_slot_used": "特性位 {normal_used} 普通",
    "alchemy_inherit_gold_slot": " + 第 4 位金色（{name}）",
    "alchemy_inherit_super_single": "❌ /继承超 仅支持 1 个金色特性",

    # —— /确认 /放弃 /调合续 /分解（终态）——
    "alchemy_settle_placement_conflict": "❌ 结算校验：互斥组/repeatable 冲突",
    "alchemy_confirm_already_settled": "已结算",
    "alchemy_confirm_materials_short": "材料不足，无法确认",
    "alchemy_confirm_fail": "❌ 确认失败",
    "alchemy_abandon_fail": "❌ 放弃失败",
    "alchemy_decompose_body": "✅ {items}",
    "alchemy_decompose_empty": "✅ 分解成功",
    "alchemy_decompose_gem": " + 宝石×{gem}",
    "alchemy_decompose_rate": "（回收 {pct}%）",
    "alchemy_decompose_fail": "❌ 分解失败",
    "alchemy_decompose_remove_fail": "❌ 分解失败：道具扣减异常",

    # —— 珠与合成（/镶嵌 /拆珠 /珠升阶 /成品合成 /配方合成 /特性合成 /登记 /复制）——
    "alchemy_mount_slots_full": "❌ 装备珠槽已满，需先 /拆珠（SOCK-03 无损拆珠）",
    "alchemy_mount_fail": "❌ 镶嵌失败",
    "alchemy_slot_invalid": "❌ 槽位无效：{slot}",
    "alchemy_slot_from_one": "❌ 槽位从 1 开始",
    "alchemy_unmount_fail": "❌ 拆珠失败",
    "alchemy_jewel_up_no_recipe": "❌ 未找到 {name} 的珠升阶配方"
                                  "（BEL-12：3×同档同 ID+宝石10，禁跳级）",
    "alchemy_jewel_up_fail": "❌ 珠升阶失败",
    "alchemy_merge_no_combos": "❌ 「{a}」+「{b}」没有已知组合",
    "alchemy_product_merge_fail": "❌ 成品合成失败",
    "alchemy_formula_not_learned": "❌ 配方未全部习得：{names}",
    "alchemy_formula_merge_fail": "❌ 配方合成失败",
    "alchemy_trait_merge_no_recipe": "❌ 未配置特性合成配方",
    "alchemy_trait_merge_fail": "❌ 特性合成失败",
    "alchemy_register_master_required": "❌ 等级不足：登记复制需炼金大师（SP 面板可解锁）",
    "alchemy_register_fail": "❌ 登记失败",
    "alchemy_copy_fail": "❌ 复制失败",

    # —— 深度炼金（/深度炼金 /进化 /镶核心 /加成 /挑战）——
    "alchemy_deep_locked": "深度未解锁",
    "alchemy_deep_open_fail": "❌ 深度会话开启失败",
    "alchemy_deep_announce": "【深度炼金·解锁公告】{ann}",
    "alchemy_deep_panel_header": "{recipe_name}（配方Lv{level}）深度调合：材料：{mats}",
    "alchemy_deep_panel_meta": "属性刻度：{scales} | 槽位 {units}/{slots} | "
                               "核心槽：{core_text} | 特性位 0/{traits_max} 普通{gold} | "
                               "PP {pp_used}/{pp_budget}",
    "alchemy_deep_gold_suffix": " + 第 4 位金色",
    "alchemy_deep_evolve_line": "进化线：{source} {done}/{need} → /进化 解锁 {tname}",
    "alchemy_evolve_fail": "❌ 进化失败",
    "alchemy_core_mismatch": "核心不匹配",
    "alchemy_core_fail": "❌ 镶核心失败",
    "alchemy_buff_fail": "加成失败",
    "alchemy_buff_fail_mark": "❌ 加成失败",
    "alchemy_challenge_condition": "连锁 ≥{need_chain} {op} 刻度 ≥{need_elem}",
    "alchemy_challenge_panel": "{name} 挑战会话已开启（材料×2 已付：{paid_text}）\n"
                              "苛刻条件：{cond}\n"
                              "当前：连锁 {chain}/{need_chain}，刻度 {elems}/{need_elem} ｜ "
                              "/确认 时判定，达标 → 品质上限+10；未达标 → 品质降级+退 50% 材料",
    "alchemy_challenge_success": "挑战成功！品质上限 +10",
    "alchemy_challenge_fail": "❌ 挑战失败：条件未达标（连锁 {segments}/{need_chain}），"
                              "品质降级，退还 50% 材料",
    "alchemy_challenge_settle_fail": "❌ 挑战结算失败",
    "alchemy_challenge_in_challenge": "❌ 挑战会话内不可再开挑战",
    "alchemy_challenge_recipe_mismatch": "❌ 挑战配方与当前深度调合配方不一致",
    "alchemy_challenge_no_materials": "❌ 配方无材料可挑战",

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
    "alchemy_announce_item": "{name}：{preview}",
    "alchemy_tutorial_master_preview": "【升大师·深度炼金 6 机制预览】{ann}",
    "alchemy_tutorial_catalog": "教学目录：",
    "alchemy_tutorial_catalog_item": "- {name}：{example}",
    "alchemy_tutorial_show": "教学·{name}：{text}",
    "alchemy_tutorial_not_found": "未找到机制「{name}」，教学目录：",

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
    # —— 通用错误/守卫 ——
    "alchemy_level_insufficient": set(),
    "alchemy_recipe_not_found": {"target"},
    "alchemy_item_not_found": {"target"},
    "alchemy_equip_not_found": {"name"},
    "alchemy_jewel_not_found": {"name"},
    "alchemy_trait_not_found": {"name"},
    "alchemy_energy_insufficient": set(),
    "alchemy_materials_insufficient": set(),
    "alchemy_materials_insufficient_diff": {"diff"},
    "alchemy_materials_insufficient_mark": set(),
    "alchemy_materials_insufficient_mark_diff": {"diff"},
    "alchemy_battle_blocked": set(),
    "alchemy_no_materials": set(),
    "alchemy_shortfall_item": {"name", "need"},
    "alchemy_material_entry_plain": {"name", "count"},
    "alchemy_material_entry_elem": {"name", "count", "cn", "val"},
    "alchemy_pp_used": {"used", "budget"},

    # —— /合成 ——
    "alchemy_synth_fail": set(),

    # —— /炼金 面板 + 触媒 ——
    "alchemy_catalyst_invalid": set(),
    "alchemy_panel": {"recipe_name", "level", "mats", "scales", "traits_used",
                     "traits_max", "pp_used", "pp_budget", "units", "slots"},
    "alchemy_scale_item": {"cn", "th", "effect"},
    "alchemy_no_scale": set(),

    # —— /炼金 批量 ——
    "alchemy_batch_no_output": set(),
    "alchemy_batch_coins": {"coins_need"},
    "alchemy_batch_output": {"output_name", "qty", "mats_text", "coin_text",
                             "score", "tier"},
    "alchemy_batch_energy_suffix": {"note"},

    # —— /投料 ——
    "alchemy_feed_elem_score": {"elem_cn", "main_score"},
    "alchemy_feed_chain": {"segments"},
    "alchemy_feed_trait_item": {"name", "pp"},
    "alchemy_feed_trait_gold": {"items"},
    "alchemy_feed_trait_awaken": {"items"},
    "alchemy_feed_traits_header": {"items"},
    "alchemy_feed_chain_effect": {"segments", "effect_level"},
    "alchemy_feed_scale_met": {"cn", "score", "th", "effect"},
    "alchemy_feed_slots_overflow": set(),
    "alchemy_feed_expert_required": set(),
    "alchemy_feed_item_not_found": set(),
    "alchemy_feed_fail": set(),
    "alchemy_auto_balance_fail": set(),

    # —— /继承 /继承超 ——
    "alchemy_inherit_no_slot": set(),
    "alchemy_inherit_pp": set(),
    "alchemy_inherit_overflow": {"limit"},
    "alchemy_inherit_group_conflict": {"g"},
    "alchemy_inherit_not_repeatable": set(),
    "alchemy_inherit_gold_occupied": set(),
    "alchemy_inherit_fail": {"msg"},
    "alchemy_inherit_fail_msg": set(),
    "alchemy_inherit_done": {"names"},
    "alchemy_inherit_negatives": {"names"},
    "alchemy_inherit_slot_used": {"normal_used"},
    "alchemy_inherit_gold_slot": {"name"},
    "alchemy_inherit_super_single": set(),

    # —— /确认 /放弃 /调合续 /分解 ——
    "alchemy_settle_placement_conflict": set(),
    "alchemy_confirm_already_settled": set(),
    "alchemy_confirm_materials_short": set(),
    "alchemy_confirm_fail": set(),
    "alchemy_abandon_fail": set(),
    "alchemy_decompose_body": {"items"},
    "alchemy_decompose_empty": set(),
    "alchemy_decompose_gem": {"gem"},
    "alchemy_decompose_rate": {"pct"},
    "alchemy_decompose_fail": set(),
    "alchemy_decompose_remove_fail": set(),

    # —— 珠与合成 ——
    "alchemy_mount_slots_full": set(),
    "alchemy_mount_fail": set(),
    "alchemy_slot_invalid": {"slot"},
    "alchemy_slot_from_one": set(),
    "alchemy_unmount_fail": set(),
    "alchemy_jewel_up_no_recipe": {"name"},
    "alchemy_jewel_up_fail": set(),
    "alchemy_merge_no_combos": {"a", "b"},
    "alchemy_product_merge_fail": set(),
    "alchemy_formula_not_learned": {"names"},
    "alchemy_formula_merge_fail": set(),
    "alchemy_trait_merge_no_recipe": set(),
    "alchemy_trait_merge_fail": set(),
    "alchemy_register_master_required": set(),
    "alchemy_register_fail": set(),
    "alchemy_copy_fail": set(),

    # —— 深度炼金 ——
    "alchemy_deep_locked": set(),
    "alchemy_deep_open_fail": set(),
    "alchemy_deep_announce": {"ann"},
    "alchemy_deep_panel_header": {"recipe_name", "level", "mats"},
    "alchemy_deep_panel_meta": {"scales", "units", "slots", "core_text",
                                "traits_max", "gold", "pp_used", "pp_budget"},
    "alchemy_deep_gold_suffix": set(),
    "alchemy_deep_evolve_line": {"source", "done", "need", "tname"},
    "alchemy_evolve_fail": set(),
    "alchemy_core_mismatch": set(),
    "alchemy_core_fail": set(),
    "alchemy_buff_fail": set(),
    "alchemy_buff_fail_mark": set(),
    "alchemy_challenge_condition": {"need_chain", "op", "need_elem"},
    "alchemy_challenge_panel": {"name", "paid_text", "cond", "chain", "need_chain",
                                "elems", "need_elem"},
    "alchemy_challenge_success": set(),
    "alchemy_challenge_fail": {"segments", "need_chain"},
    "alchemy_challenge_settle_fail": set(),
    "alchemy_challenge_in_challenge": set(),
    "alchemy_challenge_recipe_mismatch": set(),
    "alchemy_challenge_no_materials": set(),

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
    "alchemy_announce_item": {"name", "preview"},
    "alchemy_tutorial_master_preview": {"ann"},
    "alchemy_tutorial_catalog": set(),
    "alchemy_tutorial_catalog_item": {"name", "example"},
    "alchemy_tutorial_show": {"name", "text"},
    "alchemy_tutorial_not_found": {"name"},

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
