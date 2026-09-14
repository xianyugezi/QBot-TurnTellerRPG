"""冻结集合：模板表占位符允许名 + 宽度 WARN 豁免清单（门禁锚点，手工维护）。

T6/T7 复核修复（2026-09-12）：原门禁「表值占位符 ⊆ 自动派生白名单」恒真——白名单由
同一份表值 `setdefault` 派生（`templates/__init__.py`），测的是「表值 ⊆ 表值」。本文件
改为**手工冻结**的期望集合，作为独立第三方对照：

- ``FROZEN_PLACEHOLDERS``：全表允许出现的占位符名全集。表内新增/拼错占位符名（如
  ``{naem}``）→ 门禁失败，必须在本文件显式登记（改表时同步更新）。
- ``WIDTH_WARN_ALLOWLIST``：当前允许的宽度 WARN 记录 ``(key, 行号, 估算半角宽)`` 显式
  清单。新增 WARN → 门禁失败：要么把行改窄，要么走 ``template_table.json`` 的
  ``meta.prose_keys`` 显式登记豁免（登记后扫描器跳过该键、不再计入 WARN）。

本文件不以 ``test_`` 开头（不被 pytest 收集），由 ``test_template_table.py`` /
``test_template_table_final.py`` 经 importlib 按路径加载。
"""

from __future__ import annotations

# 全表占位符允许名（2026-09-12 定格；新增占位符名必须在此登记）。
FROZEN_PLACEHOLDERS = frozenset("""
a action actor aid amount amt ann assistant atk attacker attr attr_name b base blocks bonus boss
brief budget candidates cap card caught chain change child cmd cn cnt coin_text coins_have
coins_need command cond core_text cost count cr crits cur cur_rank currency current damage day
days deficit deficits desc dfn diff dir discount dist done down effect effect_desc effect_level
effects elapsed elem_cn element element_cn elems endpoint enemy enhance example exp exp_next
fields fragment g gap gem gold golden_line grants group have head heal_total hint hours hp
hp_cur hp_max i idx imprints index item item_name items job k key kill kind kind_cn king label
level level_ups limit list lit loc location luck main_score map_name mark marks mat mats
mats_text max max_hit max_hp message mention missing month_days monster_name mp msg mult n name names need need_chain
need_elem need_rank new nm normal_used note npc_name old op out output_name page pages paid_text
param params part pct period periods pos pp pp_budget pp_used prefix preview progress qq qty quality
rarity rarity_cn rate reason rec recipe_name recipes ref remain remark req resource_text rest
result reveal_text round rumor scales score season secs seen seg segments seq shield signed
skill skill_name slot slots source sp spot spot_name src stage_name state status statuses stone_have stones
streak successes summary tail target tasks temp text th tier tier_note time title title_id tname to total
total_pages traits traits_max traits_used ts turn turns turns_suffix type unit units usage used
v val value var weak weather when window_sec word world
""".split())

# 允许的宽度 WARN（key, 行号, 估算半角宽）——超出即新增 WARN，门禁失败。
# 逐条口径：占位符按 PLACEHOLDER_ESTIMATES 估算后仍 >28 半角（14 全角）的行；
# 这些行均为**数值/自由文本占位符**，小数值场景实机不折行，暂按现状冻结。
WIDTH_WARN_ALLOWLIST = frozenset({
    ("already_registered", 2, 31),
    ("enhance_ambiguous_line", 1, 31),
    ("enhance_fail_high", 2, 36),
    ("checkin_month_hit", 1, 32),
    ("log_sys_header", 1, 29),
    ("log_sys_line", 1, 39),
    ("alchemy_scale_item", 1, 29),
    ("battle_enemy_position_miss", 2, 30),
    ("battle_part_broken", 1, 30),
    ("battle_part_broken_no_knock", 1, 32),
    ("battle_fatigue_stagger", 1, 32),
    ("battle_parry_success", 1, 29),
    ("battle_counter_hit", 1, 31),
    ("battle_summary_item", 1, 31),
    ("battle_windup_unknown", 1, 34),
    ("battle_windup_ready", 1, 46),
    ("battle_merge_summary", 1, 37),
})
