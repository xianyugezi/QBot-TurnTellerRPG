#!/usr/bin/env python3
"""M4 交互系统里程碑门禁（依据：m4_shared_contract §5 + 细化_5d §2.1 L93/§6 G5，G5 门禁）。

覆盖口径（诚实化覆盖声明原则，对齐 verify_m3）：
- m4_shared_contract 为实现层唯一权威，重定义 M4 范围 = 交互系统（公共基础 A1-A3 + 指令解析
  2.1-2.4 + NPC/商店/任务/签到 3.1-3.4 + 批次7 端到端冒烟）。细化_5d L93 旧表 M4=176 TC
  （3c/4a/4b/4c/4d/4e/4f 旧范围）已由契约 §0-§4 覆盖（契约 §5「TC 矩阵随实现补充」），
  本门禁按契约新范围逐条声明，不沿用旧 176 计数（诚实化：不冒充未实现的 4a-4e 系统覆盖）。
- COVERAGE 每条 = 契约 §1/§2/§3 的子功能点，承载位置「pytest:<测试文件>::<用例>」逐条核对
  tests/unit 真实落盘用例名（613 个函数引用全数核验存在）；未覆盖项标 DELAYED 注明理由。
- 诚实化约束（自洽断言 ③ 内嵌核验）：
    * 每条只允许 pytest: 承载或 DELAYED 注明理由；
    * 声明的 pytest 测试文件必须落盘（可核验性）；
    * 声明的 测试函数名 必须存在于对应文件 def 列表（比 verify_m3 更严：函数级核验，
      防止「文件在但用例名对不上」的虚假承载）。
- DELAYED 项（0 条）：批次7-01 端到端冒烟已翻转（D8 DLY-08 立即翻转）——test_e2e_m4_smoke.py
  已落盘（pytest 固化，包装 scripts/e2e_m4_smoke.py）且已入 PYTEST_FILES；原 DELAYED 声明
  失真，由 verify_m6 段二到期扫描复核收口（TC-DLY-01）。
- 机制：脚本内核心断言（① 关键模块可导入 ② M4 关键函数存在 ③ COVERAGE 自洽 83 条计数）
  + 子进程跑 M4 相关 pytest 测试文件（PYTEST_FILES 全绿；缺失文件黄提示不判失败）。

用法：.venv/bin/python scripts/verify/verify_m4.py
门禁语义：脚本断言全过 + 已落盘 pytest 文件全绿 → 0；任一 FAIL → 1。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

_PASS: list = []
_FAIL: list = []

# ----------------------------------------------------------------------------------
# 覆盖声明：83 条 M4 覆盖点逐条承载位置（依据：m4_shared_contract §1/§2/§3 + 细化_2b1~2b5/3c/3d/4f/5b；
# 载体用例名 grep tests/unit 全数核验）
# ----------------------------------------------------------------------------------
COVERAGE: dict = {
    # ── A1 统一 reward 解析器（contract §1 A1；细化_2b4 reward + 细化_2b1 give_item）──
    "A1-01 内联键值串展开等价（D05 序列化糖）": "pytest:test_reward.py::test_d05_inline_equivalent_to_structured + test_reward.py::test_expand_inline_reward_shapes + test_reward.py::test_inline_unknown_key_raises_for_expander",
    "A1-02 exp 数值直入 / coins/gem 入货币表（键空间=settings）": "pytest:test_reward.py::test_tc13_exp_direct + test_reward.py::test_tc14_currency_into_table + test_reward.py::test_currency_accumulates_existing_balance + test_reward.py::test_currency_default_space_without_settings",
    "A1-03 item 入包默认绑定（count 默认/显式 bound=false）": "pytest:test_reward.py::test_tc15_item_into_inventory_default_bound + test_reward.py::test_item_default_count_and_explicit_bound_false + test_reward.py::test_item_id_alias_npc_give_item + test_reward.py::test_item_no_add_hook_skips_p1_1",
    "A1-04 rep 入 reputation_state（不入货币表）": "pytest:test_reward.py::test_tc16_rep_into_reputation_state_not_currency + test_reward.py::test_rep_board_resolution + test_reward.py::test_rep_accumulates",
    "A1-05 组合数组按序 + 失败策略逐条黄字跳过不中断整批": "pytest:test_reward.py::test_tc17_combination_array_in_order + test_reward.py::test_p12_bad_entry_skips_rest_grants + test_reward.py::test_invalid_value_skips_entry + test_reward.py::test_item_invalid_count_skips + test_reward.py::test_item_not_found_and_registry_missing + test_reward.py::test_missing_bucket_skips_entry + test_reward.py::test_add_item_hook_failure_skips + test_reward.py::test_malformed_entry_skips",
    "A1-06 幂等（tx id 防双发防双扣 / ledger 记录）": "pytest:test_reward.py::test_idempotent_same_tx_id_does_not_double_book + test_reward.py::test_idempotent_different_tx_id_books_twice + test_reward.py::test_idempotent_requires_both_tx_id_and_ledger + test_reward.py::test_idempotent_records_ledger_even_with_skips",
    "A1-07 normalize 形态（dict/list/str 混合 + 非法入参防护）": "pytest:test_reward.py::test_normalize_reward_forms + test_reward.py::test_single_dict_entry + test_reward.py::test_mixed_list_str_and_dict_entries + test_reward.py::test_batch_invalid_entries_type + test_reward.py::test_batch_invalid_ctx + test_reward.py::test_resolver_item_registry_callable",
    # ── A2 统一条件引擎（contract §1 A2；细化_2b1 §4.3 互译表 + 2b4 D-02/D-03）──
    "A2-01 9 运算符 gt/ge/lt/le/eq/ne/between/is/not": "pytest:test_condition_engine.py::test_operators_9_present + test_condition_engine.py::test_gt_ge_lt_le + test_condition_engine.py::test_eq_ne + test_condition_engine.py::test_between + test_condition_engine.py::test_is_not_semantics + test_condition_engine.py::test_is_night_bool",
    "A2-02 符号双写 >= > <= < = != 归一": "pytest:test_condition_engine.py::test_op_symbol_dual_write_normalize + test_condition_engine.py::test_symbol_dual_write_equivalent",
    "A2-03 值型三原语（level/item_count 读当前值）": "pytest:test_condition_engine.py::test_value_primitive_level + test_condition_engine.py::test_value_primitive_item_count_exact",
    "A2-04 累计型（kill_count/gain_count 读 longline_counters）": "pytest:test_condition_engine.py::test_cumulative_gain_count_flat_and_nested + test_condition_engine.py::test_cumulative_kill_count + test_condition_engine.py::test_cumulative_missing_counter_is_zero + test_condition_engine.py::test_dungeon_clear_and_main_progress",
    "A2-05 事件型（var 前缀 [事件:xxx]，param=目标，读事件计数）": "pytest:test_condition_engine.py::test_event_primitive + test_condition_engine.py::test_event_default_op_and_value + test_condition_engine.py::test_event_embedded_target_in_name + test_condition_engine.py::test_event_not_registered_false + test_condition_engine.py::test_legacy_event_format_normalized",
    "A2-06 组合 any/all/not 嵌套递归 + conditions 数组全与（D-02）": "pytest:test_condition_engine.py::test_combination_all + test_condition_engine.py::test_combination_any + test_condition_engine.py::test_combination_not_nested + test_condition_engine.py::test_conditions_array_all_and",
    "A2-07 旧格式 type 忽略（var 归一）+ 中英文互译表": "pytest:test_condition_engine.py::test_old_format_type_ignored + test_condition_engine.py::test_old_format_chinese_var_normalized + test_condition_engine.py::test_op_legacy_min_max_compat + test_condition_engine.py::test_op_invalid_or_non_string + test_condition_engine.py::test_var_aliases_chinese_to_english + test_condition_engine.py::test_var_alias_eval_chinese + test_condition_engine.py::test_normalize_var_unknown",
    "A2-08 求值失败默认 False 不抛错（D-03 工程补白）": "pytest:test_condition_engine.py::test_fail_safe_unknown_var + test_condition_engine.py::test_fail_safe_illegal_op + test_condition_engine.py::test_fail_safe_malformed_cond + test_condition_engine.py::test_fail_safe_ctx_missing_value",
    "A2-09 var 键空间注册表（任务/物品/状态/职业/累计/时间/关系/事件 + X 扩展）": "pytest:test_condition_engine.py::test_registered_vars_categories + test_condition_engine.py::test_job_joblevel_prof_reputation_affection + test_condition_engine.py::test_quest_predicates + test_condition_engine.py::test_season_period_weather_alias + test_condition_engine.py::test_time_derived_from_period + test_condition_engine.py::test_event_presets + test_condition_engine.py::test_x_extension",
    "A2-10 [签到:<表名>.<字段>] 三键消费（用户裁决⑧）": "pytest:test_condition_engine.py::test_checkin_nested_ctx + test_condition_engine.py::test_checkin_flat_ctx_and_fail + test_condition_engine.py::test_checkin_constants",
    "A2-11 validate_condition 校验器（OK/红拦/黄提示）": "pytest:test_condition_engine.py::test_validate_condition_ok + test_condition_engine.py::test_validate_condition_unknown_var_red + test_condition_engine.py::test_validate_condition_illegal_op_red + test_condition_engine.py::test_validate_condition_legacy_format_yellow + test_condition_engine.py::test_validate_condition_event_not_registered_yellow + test_condition_engine.py::test_validate_condition_nested_and_bad_shape",
    # ── A3 日界统一与懒计算（contract §1 A3；细化_2a4a 时间锚点复用）──
    "A3-01 today_of 重置时刻默认 05:00（凌晨 0-5 归属前一天）": "pytest:test_dayroll.py::test_today_default_reset_05_before_dawn_belongs_previous_day + test_dayroll.py::test_today_default_reset_05_at_0459_still_previous_day + test_dayroll.py::test_today_default_reset_05_exactly_0500_new_day + test_dayroll.py::test_today_default_reset_05_midnight_belongs_previous_day + test_dayroll.py::test_today_default_reset_05_late_night_same_day",
    "A3-02 自定义重置时刻（可配键/整点/带分钟/坏配置回退 05:00）": "pytest:test_dayroll.py::test_today_custom_reset_1200 + test_dayroll.py::test_today_custom_reset_int_hour + test_dayroll.py::test_today_custom_reset_with_minutes + test_dayroll.py::test_today_reset_0000_is_calendar_day + test_dayroll.py::test_today_bad_config_falls_back_default_0500 + test_dayroll.py::test_today_nested_settings_key + test_dayroll.py::test_today_of_cfg_none_default",
    "A3-03 纯函数懒计算（同参同果/惰性补刷/离线多天不丢不炸）": "pytest:test_dayroll.py::test_today_pure_function_same_args_same_result + test_dayroll.py::test_today_of_first_ever_no_last_key + test_dayroll.py::test_today_of_same_day_idempotent + test_dayroll.py::test_today_of_next_day_one_rollover + test_dayroll.py::test_today_of_offline_multiple_days + test_dayroll.py::test_today_of_still_same_day_at_0300 + test_dayroll.py::test_today_of_future_last_key_clock_skew + test_dayroll.py::test_today_of_invalid_last_key_defensive",
    "A3-04 days/weeks elapsed 周期工具（月边界/跨周判定）": "pytest:test_dayroll.py::test_days_elapsed_none_zero + test_dayroll.py::test_days_elapsed_same_day_zero + test_dayroll.py::test_days_elapsed_three_days + test_dayroll.py::test_days_elapsed_month_boundary + test_dayroll.py::test_days_elapsed_future_zero + test_dayroll.py::test_days_elapsed_custom_reset_boundary + test_dayroll.py::test_days_elapsed_invalid_zero + test_dayroll.py::test_weeks_elapsed_none_or_invalid_zero + test_dayroll.py::test_weeks_elapsed_same_week_zero + test_dayroll.py::test_weeks_elapsed_cross_monday_boundary + test_dayroll.py::test_weeks_elapsed_two_weeks + test_dayroll.py::test_weeks_elapsed_sunday_anchor + test_dayroll.py::test_weeks_elapsed_invalid_weekday_defaults_monday",
    "A3-05 advance_cycles（日/周/月 clamp + 非法防御）": "pytest:test_dayroll.py::test_advance_cycles_day + test_dayroll.py::test_advance_cycles_week + test_dayroll.py::test_advance_cycles_month_clamp + test_dayroll.py::test_advance_cycles_invalid_last_key_passthrough + test_dayroll.py::test_advance_cycles_unknown_period_raises",
    "A3-06 once 时间窗（未开门/自动下架）+ 刷新时刻解析": "pytest:test_dayroll.py::test_window_open_mid_window + test_dayroll.py::test_window_not_started + test_dayroll.py::test_window_start_inclusive + test_dayroll.py::test_window_expired + test_dayroll.py::test_window_end_inclusive + test_dayroll.py::test_window_date_only_string + test_dayroll.py::test_window_missing_bounds_always_open + test_dayroll.py::test_window_invalid_bounds_always_open + test_dayroll.py::test_normalize_hhmm_variants + test_dayroll.py::test_resolve_refresh_time_default_and_custom",
    # ── 2.1 指令解析管线（contract §2.1；细化_3c 45 TC）──
    "2.1-01 分隔符五类（空格/星号/逗号/等号/等级连招路径）": "pytest:test_parsers.py::test_two_positional_args + test_parsers.py::test_single_arg + test_parsers.py::test_raw_preserved + test_parsers.py::test_star_quantity + test_parsers.py::test_star_quantity_buy + test_parsers.py::test_no_star_is_sequence_not_quantity + test_parsers.py::test_comma_list + test_parsers.py::test_kv_plain + test_parsers.py::test_level_suffix + test_parsers.py::test_seq_chain + test_parsers.py::test_path_forge",
    "2.1-02 紧凑 + 空格双认（三模式 command_mode 默认 global 免前缀 + require_at 默认关）": "pytest:test_parsers.py::test_compact_digit + test_parsers.py::test_space_equivalent + test_parsers.py::test_compact_digit_enter + test_parsers.py::test_global_default_unprefixed_ok + test_parsers.py::test_prefix_only_requires_slash + test_parsers.py::test_require_at_default_off",
    "2.1-03 物品名禁空格/保留字提示不拦截": "pytest:test_parsers.py::test_name_with_dash_not_seq + test_parsers.py::test_reserved_char_hint_not_block + test_parsers.py::test_reserved_char_hint_space + test_parsers.py::test_reserved_char_hint_allowed_name",
    "2.1-04 快捷绑定（个人上限 20 / GM 禁绑 / 冲突动态注册表）": "pytest:test_parsers.py::test_bind_with_arg + test_parsers.py::test_bind_full_command_str + test_parsers.py::test_exact_match_only + test_parsers.py::test_shortcut_expand_session_active_not_routed + test_parsers.py::test_shortcut_none + test_router.py::test_tc29_gm_forbidden_binding_c02 + test_router.py::test_tc28_shortcut_name_conflict_c01 + test_router.py::test_tc30_shortcut_limit_e03 + test_router.py::test_shortcut_binding_ok_and_format_hint_c03",
    "2.1-05 指令别名（keep_original 显示层全替换）": "pytest:test_parsers.py::test_alias_resolves + test_parsers.py::test_alias_with_args + test_parsers.py::test_hidden_original_guides + test_parsers.py::test_keep_original_true_keeps_both + test_router.py::test_tc33_alias_executes_original + test_router.py::test_tc33_keep_original_false_hides_original + test_router.py::test_tc35_keep_original_true_original_still_works_display_replaced + test_router.py::test_alias_compact_form",
    "2.1-06 会话路由（对话激活时纯数字/继续/退出/选择N 送状态机，跳过快捷表纯数字）": "pytest:test_parsers.py::test_dialog_digit_routes + test_parsers.py::test_dialog_continue_routes + test_parsers.py::test_dialog_exit_words + test_parsers.py::test_dialog_select_n + test_parsers.py::test_session_priority_over_shortcut + test_parsers.py::test_command_word_normal_parse_in_dialog + test_parsers.py::test_no_session_shortcut_active + test_router.py::test_tc36_dialog_pure_digit_to_session + test_router.py::test_tc38_session_wins_over_shortcut_r3",
    "2.1-07 战斗中裸数字 = 快捷表（用户裁决①；带指令词照常解析）": "pytest:test_parsers.py::test_battle_naked_digit_bound_shortcut + test_parsers.py::test_battle_naked_digit_unbound_ignored + test_parsers.py::test_battle_continue_exit_not_session + test_parsers.py::test_battle_command_word_parses + test_parsers.py::test_battle_session_active_defensive + test_router.py::test_ruling1_battle_bare_digit_goes_shortcut_not_session + test_router.py::test_battle_command_word_parses_normally",
    "2.1-08 ParsedCommand 形态 + 参数解析 + 路由管线（注册/白名单/GM 集）": "pytest:test_parsers.py::test_valid + test_parsers.py::test_invalid + test_parsers.py::test_arg_accessor + test_parsers.py::test_equality + test_parsers.py::test_is_command + test_parsers.py::test_explicit_slash_always_allowed + test_parsers.py::test_too_many + test_parsers.py::test_missing_arg + test_router.py::test_router_register_duplicate_conflict + test_router.py::test_router_whitelist_and_gm_sets + test_router.py::test_router_dispatch_uses_self_registry + test_router.py::test_shortcut_before_alias_before_whitelist_priority",
    "2.1-09 路由忽略规则 + 白名单前缀最长匹配": "pytest:test_router.py::test_ignore_non_command_message_w06 + test_router.py::test_longest_whitelist_prefix_wins + test_router.py::test_non_whitelisted_command_bare_ignored + test_router.py::test_route_result_display_name_fallbacks + test_router.py::test_whitelist_space_and_compact_dual",
    # ── 2.2 消息模板（contract §2.2；细化_3d）──
    "2.2-01 列表 5 条/页 + TPL-08 页脚固定（禁止自造页脚）": "pytest:test_list_render.py::test_footer_tpl08_exact + test_list_render.py::test_footer_single_page_empty + test_list_render.py::test_footer_uses_command_verbatim + test_list_render.py::test_page_items_five_per_page + test_list_render.py::test_render_list_page_first_page + test_list_render.py::test_render_list_page_single_page_no_footer",
    "2.2-02 页码越界夹取最后一页 + 已到最后一页（用户裁决②）": "pytest:test_list_render.py::test_resolve_page_clamp_over_total + test_list_render.py::test_render_list_page_clamped_with_hint + test_list_render.py::test_render_list_page_text_composition",
    "2.2-03 0/负数/非数字 → TPL-12 报错（唯一文案源）": "pytest:test_list_render.py::test_resolve_page_invalid_zero_negative_nonnum + test_list_render.py::test_resolve_page_str_digits_ok + test_list_render.py::test_resolve_page_bool_rejected + test_list_render.py::test_resolve_page_empty_list_single_page + test_list_render.py::test_resolve_page_per_page_zero_rejected + test_sender.py::test_page_error_tpl12_invalid_page + test_sender.py::test_page_error_tpl12_uses_canonical_source",
    "2.2-04 错误模板 TPL-12/13/14（D-04 唯一文案源）": "pytest:test_sender.py::test_tpl12_exact_text + test_sender.py::test_tpl12_truncate_20_chars + test_sender.py::test_tpl13_exact_text + test_sender.py::test_tpl14_exact_text",
    "2.2-05 分段发送（QQ 4000 预算）+ CQ 转义 + emoji 纪律": "pytest:test_sender.py::test_default_budget_is_qq_4000 + test_sender.py::test_segment_short_text_single + test_sender.py::test_segment_long_text_no_loss + test_sender.py::test_segment_three_chunks + test_sender.py::test_segment_empty + test_sender.py::test_cq_escape_basic + test_sender.py::test_cq_escape_blocks_cq_injection + test_sender.py::test_send_segments_and_escape + test_sender.py::test_send_escapes_cq_injection_before_send + test_sender.py::test_send_retry_then_success_with_backoff + test_sender.py::test_send_retry_exhausted_raises + test_sender.py::test_error_templates_emoji_discipline + test_list_render.py::test_no_banned_decorative_emoji",
    # ── 2.3 基础指令组（contract §2.3；细化_4f RUL-01~34）──
    "2.3-01 /查看 属性面板分页 + 页码夹取": "pytest:test_basic_commands.py::test_view_noarg_page1 + test_basic_commands.py::test_view_page2 + test_basic_commands.py::test_view_clamp_last_page + test_basic_commands.py::test_view_invalid_tpl12 + test_basic_commands.py::test_view_noarg_equiv_page1 + test_basic_commands.py::test_view_max_level_header + test_basic_commands.py::test_attr_line_pure",
    "2.3-02 /背包 列表分页 + 物品行": "pytest:test_basic_commands.py::test_bag_page1_rows_and_footer + test_basic_commands.py::test_bag_page2 + test_basic_commands.py::test_bag_clamp_last_page + test_basic_commands.py::test_bag_invalid_tpl12 + test_basic_commands.py::test_bag_empty + test_basic_commands.py::test_bag_single_page_no_footer + test_basic_commands.py::test_bag_iteminstance_dataclass_support + test_basic_commands.py::test_bag_line_pure",
    "2.3-03 /装备 穿戴/卸下（按 id/中文名/序号）": "pytest:test_basic_commands.py::test_equip_view_page1 + test_basic_commands.py::test_equip_view_clamp + test_basic_commands.py::test_equip_invalid_page_tpl12 + test_basic_commands.py::test_equip_wear + test_basic_commands.py::test_equip_wear_compact + test_basic_commands.py::test_equip_wear_invalid + test_basic_commands.py::test_equip_remove_by_id + test_basic_commands.py::test_equip_remove_by_chinese_name + test_basic_commands.py::test_equip_remove_by_seq + test_basic_commands.py::test_equip_remove_missing_arg + test_basic_commands.py::test_resolve_equip_slot",
    "2.3-04 /技能 列表 + 职业过滤 + 派生名": "pytest:test_basic_commands.py::test_skill_page1 + test_basic_commands.py::test_skill_page2 + test_basic_commands.py::test_skill_job_filter + test_basic_commands.py::test_skill_derived_names_pure + test_basic_commands.py::test_skill_rows_order + test_basic_commands.py::test_skill_invalid_tpl12 + test_basic_commands.py::test_skill_empty",
    "2.3-05 /帮助 目录 + 分组翻页": "pytest:test_basic_commands.py::test_help_directory_normal + test_basic_commands.py::test_help_directory_gm_two_pages + test_basic_commands.py::test_help_group_page + test_basic_commands.py::test_help_group_page2 + test_basic_commands.py::test_help_group_single_page_no_footer + test_basic_commands.py::test_help_unknown_group_tpl12 + test_basic_commands.py::test_help_invalid_page_tpl12 + test_basic_commands.py::test_help_directory_clamp_normal + test_basic_commands.py::test_help_unregistered_guide",
    "2.3-06 页码夹取口径统一（RUL-01~34）+ 注册门 RUL-08 + 零 NoneBot 铁律": "pytest:test_basic_commands.py::test_group_page_line_pure + test_basic_commands.py::test_register_gate_rul08 + test_basic_commands.py::test_help_exempt_gate + test_basic_commands.py::test_register_basic_commands + test_basic_commands.py::test_router_parse_integration + test_basic_commands.py::test_pure_helpers_no_nonebot",
    # ── 2.4 GM 指令（contract §2.3 GM；细化_5b 34 TC）──
    "2.4-01 GM 权限三级 + 默认授予": "pytest:test_gm_commands.py::test_gm_command_level_default_grant + test_gm_commands.py::test_permission_admin_all + test_gm_commands.py::test_permission_manager_default_grant + test_gm_commands.py::test_permission_manager_granted_settings + test_gm_commands.py::test_permission_player_silent + test_gm_commands.py::test_permission_priority_admin_over_manager + test_gm_commands.py::test_permission_non_gm_command",
    "2.4-02 静默（成功无声/无权限全静默）+ 留痕审计（HMAC 防篡改）": "pytest:test_gm_commands.py::test_authorized_success_silent_no_echo + test_gm_commands.py::test_no_permission_total_silent + test_gm_commands.py::test_silent_result_factory + test_gm_commands.py::test_build_audit_record_fields + test_gm_commands.py::test_audit_hmac_deterministic_and_tamper + test_gm_commands.py::test_record_audit_collect_and_store + test_gm_commands.py::test_success_and_failure_both_audited",
    "2.4-03 GM 禁绑（防权限绕过）": "pytest:test_gm_commands.py::test_binding_guard_rejects_gm_command + test_gm_commands.py::test_binding_guard_allows_player_shortcut + test_gm_commands.py::test_execution_layer_second_check_bypass + test_gm_commands.py::test_router_bare_gm_ignored_prefix_required + test_gm_commands.py::test_router_prefixed_gm_recognized_and_is_gm + test_gm_commands.py::test_router_shortcut_never_triggers_gm_bare",
    "2.4-04 GM 指令清单（L160 长清单 + 设置）+ 前缀门": "pytest:test_gm_commands.py::test_gm_commands_long_list + test_gm_commands.py::test_gm_prefix_required_wiring + test_gm_commands.py::test_is_gm_command_name + test_gm_commands.py::test_register_gm_commands_specs",
    "2.4-05 /gm 子指令（重载/封禁/日志/编辑/设置）": "pytest:test_gm_commands.py::test_reload_success_silent + test_gm_commands.py::test_reload_failures_listed_in_detail + test_gm_commands.py::test_reload_missing_arg_tpl12 + test_gm_commands.py::test_ban_success_audit_e4 + test_gm_commands.py::test_ban_default_permanent + test_gm_commands.py::test_ban_invalid_qq_tpl12 + test_gm_commands.py::test_log_gm_view_default_page + test_gm_commands.py::test_log_page_2 + test_gm_commands.py::test_log_window_kv_default_and_max + test_gm_commands.py::test_log_page_clamped_last_page + test_gm_commands.py::test_settings_admin_switch + test_gm_commands.py::test_settings_owner_only_silent_for_manager + test_gm_commands.py::test_edit_returns_link_with_role_hint",
    # ── 3.1 NPC/对话（contract §3.1；细化_2b1 + 2b2）──
    "3.1-01 NPCDef 14 顶层字段 + 子表访问器": "pytest:test_npc_models.py::test_npcdef_accessors_top_level + test_npc_models.py::test_npcdef_accessors_dealer + test_npc_models.py::test_npcdef_defaults + test_npc_models.py::test_parse_npcs",
    "3.1-02 validate_npcs 结构校验（OK/红拦/黄警告）": "pytest:test_npc_models.py::test_legal_npc_full_green + test_npc_models.py::test_legal_npc_checker_integration + test_npc_models.py::test_id_required_and_duplicate + test_npc_models.py::test_name_space_forbidden + test_npc_models.py::test_type_enum + test_npc_models.py::test_map_ref_dangling + test_npc_models.py::test_action_specific_refs_missing + test_npc_models.py::test_unused_npc_warning + test_npc_models.py::test_interaction_action_enum + test_npc_models.py::test_condition_structure_errors + test_npc_models.py::test_condition_soft_warnings",
    "3.1-03 发牌员三策略 rotate/random/condition（用户裁决④ legacy 兼容映射）": "pytest:test_npc.py::test_normalize_strategy_refined_values_passthrough + test_npc.py::test_normalize_strategy_legacy_mapping + test_npc.py::test_normalize_strategy_default_and_unknown + test_npc.py::test_draw_rotate_cyclic_pointer + test_npc.py::test_draw_random_weighted + test_npc.py::test_draw_random_uniform_when_all_zero_or_equal + test_npc.py::test_draw_random_zero_weight_excluded_from_weighted_pool + test_npc.py::test_draw_condition_first_eligible + test_npc.py::test_draw_card_empty_pool",
    "3.1-04 不重复发已完成任务 / 一次一物交付后置灰已听": "pytest:test_npc.py::test_build_pool_once_card_out_after_delivered + test_npc.py::test_build_pool_quest_card_no_available_excluded + test_npc.py::test_build_pool_invalid_cards_skipped + test_npc.py::test_deal_once_card_removed_after_delivery + test_npc.py::test_deal_quest_card_dedup + test_npc.py::test_npc_delivered_per_npc_isolation + test_npc.py::test_mark_delivered_creates_node_lazily",
    "3.1-05 deal 入口（condition 优先/轮转持久状态/随机 + 空池）": "pytest:test_npc.py::test_deal_condition_picks_first_eligible_and_delivers + test_npc.py::test_deal_lonely_card_empty_pool + test_npc.py::test_deal_rotate_persistent_state + test_npc.py::test_deal_random_strategy + test_npc.py::test_available_quests_dedup_three_tables + test_npc.py::test_available_quests_condition_gate + test_npc.py::test_build_pool_condition_filter",
    "3.1-06 10 类动作分发（quest/shop/heal/give_item/buff/repair/teleport/intel/tutorial/reply）": "pytest:test_npc.py::test_dispatch_all_actions_registered + test_npc.py::test_dispatch_unknown_and_invalid + test_npc.py::test_dispatch_public_condition_gate + test_npc.py::test_dispatch_quest_returns_first_available + test_npc.py::test_dispatch_shop_sets_current_shop_ref + test_npc.py::test_dispatch_heal_flat_and_percent + test_npc.py::test_dispatch_heal_insufficient_funds + test_npc.py::test_dispatch_give_item_via_reward_parser + test_npc.py::test_dispatch_give_item_daily_reset + test_npc.py::test_dispatch_give_item_default_once_and_skipped_entries + test_npc.py::test_dispatch_buff_records_active_effects + test_npc.py::test_dispatch_repair_degraded + test_npc.py::test_dispatch_teleport_pays_and_moves + test_npc.py::test_dispatch_intel_once_item_greyed + test_npc.py::test_dispatch_tutorial_once_first_meet + test_npc.py::test_dispatch_reply_random_and_cycle",
    "3.1-07 会话状态机 15 迁移全遍历 + 快照 JSON 往返 + 中断恢复": "pytest:test_dialog.py::test_grand_tour_covers_all_15_transitions + test_dialog.py::test_transition_table_has_exactly_15 + test_dialog.py::test_snapshot_roundtrip_json_serializable + test_dialog.py::test_interrupt_does_not_migrate_state + test_dialog.py::test_resume_brief_idle_end_none + test_dialog.py::test_resume_brief_menu_layer + test_dialog.py::test_resume_brief_exec_page_index + test_dialog.py::test_resume_brief_subui_label + test_dialog.py::test_current_shop_ref_reported_via_handoff_only + test_dialog.py::test_end_fires_event_count_once",
    "3.1-08 对话树 max_dialog_depth（默认 2，0=不限）超深软拦（用户裁决③）": "pytest:test_dialog.py::test_resolve_max_dialog_depth_default_and_config + test_dialog.py::test_is_depth_blocked_zero_unlimited + test_dialog.py::test_authored_node_depth_flat_and_nested + test_dialog.py::test_depth_soft_block_at_default_2 + test_dialog.py::test_depth_zero_unlimited_no_block + test_dialog.py::test_flat_interactions_never_depth_blocked",
    "3.1-09 退出词三词同义 + 菜单 ≤6 折叠 + 已听置灰 + 条件一行": "pytest:test_dialog.py::test_tc13_exit_words_synonym + test_dialog.py::test_tc13_exit_from_list_t04 + test_dialog.py::test_render_menu_six_options_exact_tc19 + test_dialog.py::test_render_menu_fold_over_six_tc20 + test_dialog.py::test_render_menu_condition_one_line_tc21 + test_dialog.py::test_render_menu_heard_gray + test_dialog.py::test_tc11_heard_gray_and_reselect + test_dialog.py::test_condition_hint_one_line + test_dialog.py::test_render_npc_list_icon_and_name",
    "3.1-10 NPC 对话主链路（列表→菜单→执行→子界面中断恢复 + /对话 接缝裁决）": "pytest:test_dialog.py::test_tc01_no_args_list_enters_s1 + test_dialog.py::test_tc02_index_shortcut_to_menu + test_dialog.py::test_tc09_full_main_chain_shop + test_dialog.py::test_tc09_select_N_equivalent_to_digit + test_dialog.py::test_tc10_condition_unmet_stays_menu + test_dialog.py::test_tc14_subui_interrupt_resume + test_dialog.py::test_t14_exit_from_subui + test_dialog.py::test_t04_t06_via_list_pick + test_dialog.py::test_parse_dialog_no_args_list",
    # ── 3.2 商店（contract §3.2；细化_2b3 42 TC）──
    "3.2-01 ShopDef/ShopItemDef 12 字段访问器 + legacy 侧": "pytest:test_shop_models.py::test_shopdef_accessors_top_level + test_shop_models.py::test_shopdef_refresh_subobject + test_shop_models.py::test_shopitemdef_accessors_12_fields + test_shop_models.py::test_shopitemdef_legacy_and_sides + test_shop_models.py::test_shopdef_defaults",
    "3.2-02 validate_shops（五类型/价格/刷新/等级声望门/黑市）": "pytest:test_shop_models.py::test_legal_shop_full_green + test_shop_models.py::test_legal_shop_checker_integration + test_shop_models.py::test_id_required_and_duplicate + test_shop_models.py::test_type_enum + test_shop_models.py::test_refresh_mode_enum + test_shop_models.py::test_price_invalid_values + test_shop_models.py::test_price_mixed_payment_keys + test_shop_models.py::test_stock_limit_discount_negative + test_shop_models.py::test_level_gates_negative + test_shop_models.py::test_reputation_required_validation + test_shop_models.py::test_blackmarket_pool_and_listing + test_shop_models.py::test_blackmarket_listing_n_resolution",
    "3.2-03 stock(global) + per_player(personal) 同条目并存（用户裁决⑤）": "pytest:test_shop_models.py::test_ruling5_stock_and_per_player_coexist + test_shop.py::test_stock_limit_coexist_ruling5 + test_shop_models.py::test_scope_and_period_enum + test_shop.py::test_tc13_buy_personal_limit",
    "3.2-04 refresh 四模式 + 不配置=永不刷新（用户裁决⑥）+ 刷新三件事同刻发生": "pytest:test_shop_models.py::test_ruling6_refresh_default_none + test_shop.py::test_tc36_none_never_refresh + test_shop.py::test_refresh_weekly_due + test_shop.py::test_tc33_daily_lazy_refresh_refill_and_not_soldout_once + test_shop.py::test_tc35_offline_multiple_days_refresh_once + test_shop.py::test_tc34_browse_once_window_gate + test_shop.py::test_tc41_blackmarket_redraw_deterministic + test_shop.py::test_next_stock_message",
    "3.2-05 原子防双扣（SQLite 事务回滚 / 会话快照幂等 tx）": "pytest:test_shop.py::test_tc22_buy_rollback_on_add_failure + test_shop.py::test_tc23_buy_idempotent_tx + test_shop.py::test_sell_idempotent_tx + test_shop.py::test_tc19_tc20_mixed_payment_atomic + test_shop.py::test_tc39_chain_order_limit_before_stock_before_funds",
    "3.2-06 shop_buy（库存扣减/个人限购周期/资金/等级声望门/售罄永久下架）": "pytest:test_shop.py::test_tc09_buy_stock_decrement_then_soldout + test_shop.py::test_tc08_browse_stock0_infinite_no_soldout + test_shop.py::test_tc14_buy_limit_full_whole_order_rejected + test_shop.py::test_tc15_period_reset_day_next_day + test_shop.py::test_personal_limit_week_period_reset + test_shop.py::test_tc17_buy_funds_insufficient + test_shop.py::test_tc03_buy_cap_truncate + test_shop.py::test_tc11_sold_out_once_permanent + test_shop.py::test_tc38_buy_reputation_requirement + test_shop.py::test_tc37_browse_shop_level_gate_greyed_not_blocked",
    "3.2-07 shop_sell（折算比例/价格覆盖/禁售/资金上限/大额确认）": "pytest:test_shop.py::test_tc25_sell_ratio_floor + test_shop.py::test_tc25b_sell_ratio_floor_partial + test_shop.py::test_tc26_sell_price_override + test_shop.py::test_tc27_sell_blocked_items + test_shop.py::test_tc28_sell_insufficient + test_shop.py::test_tc16_sell_not_count_limit + test_shop.py::test_sell_currency_cap_when_configured + test_shop.py::test_sell_large_confirm_when_configured",
    "3.2-08 当前商店机制（地图级状态兜底 / 商店中断恢复）": "pytest:test_shop.py::test_tc29_30_31_current_shop_set_recover_clear + test_shop.py::test_tc02_32_current_shop_index_and_name_switch + test_shop.py::test_current_shop_invalid_ref_falls_back + test_shop.py::test_shop_list_rows_and_gate_markers + test_shop.py::test_browse_no_shop",
    "3.2-09 /商店 /购买 /出售 指令接线（页码夹取 / TPL-12 / TPL-08 页脚）": "pytest:test_shop_commands.py::test_shop_noarg_browses_current_default_shop + test_shop_commands.py::test_shop_name_switch_browse + test_shop_commands.py::test_shop_integer_clamp_last_page + test_shop_commands.py::test_shop_invalid_input_tpl12 + test_shop_commands.py::test_shop_list_overview_page1 + test_shop_commands.py::test_buy_ok + test_shop_commands.py::test_buy_default_qty1_and_compact + test_shop_commands.py::test_buy_old_space_qty_compat + test_shop_commands.py::test_buy_insufficient_currency_show_diff + test_shop_commands.py::test_buy_limit_reached + test_shop_commands.py::test_buy_sold_out + test_shop_commands.py::test_buy_missing_target_tpl12 + test_shop_commands.py::test_sell_ok + test_shop_commands.py::test_sell_insufficient_inventory + test_shop_commands.py::test_sell_bound_item + test_shop_commands.py::test_sell_missing_target_tpl12 + test_shop_commands.py::test_parse_command_integration + test_shop_commands.py::test_register_shop_commands + test_shop_commands.py::test_footer_tpl08_exact",
    # ── 3.3 任务（contract §3.3；细化_2b4 31 TC）──
    "3.3-01 QuestDef 字段访问器 + validate_quests（main 定稿 L138 命名）": "pytest:test_quest_models.py::test_questdef_accessors_top_level + test_quest_models.py::test_questdef_board_accessors + test_quest_models.py::test_questdef_npc_conditions + test_quest_models.py::test_questdef_defaults + test_quest_models.py::test_legal_quest_full_green + test_quest_models.py::test_id_required_and_duplicate + test_quest_models.py::test_name_required + test_quest_models.py::test_main_field_naming + test_quest_models.py::test_zone_ref_missing + test_quest_models.py::test_unlock_chain_dead",
    "3.3-02 任务三原语引擎（值/累计/事件 + 符号双写 + conditions 全与）": "pytest:test_quest.py::test_value_primitive_level_tc06 + test_quest.py::test_value_primitive_item_count_exact_tc07 + test_quest.py::test_accum_gain_count_longline_tc08 + test_quest.py::test_accum_kill_count_tc09 + test_quest.py::test_event_primitive_tc10 + test_quest.py::test_op_symbol_equivalent_tc11 + test_quest.py::test_conditions_all_and_tc12 + test_quest.py::test_fail_safe_unknown_event_tc31 + test_quest.py::test_empty_conditions_accept_ready",
    "3.3-03 统一 reward 结算（exp/coin/item/rep/内联糖/失败跳过）": "pytest:test_quest.py::test_complete_reward_exp_coin_item_tc13_15 + test_quest.py::test_complete_rep_into_reputation_state_tc16 + test_quest.py::test_complete_inline_reward_sugar_d05 + test_quest.py::test_complete_entry_failure_skips_p1_2",
    "3.3-04 每日防刷（daily_limit≤10 / accept_limit≤5 / quest_daily 懒重置）": "pytest:test_quest.py::test_accept_limit_reject_tc20 + test_quest.py::test_accept_limit_zero_unlimited + test_quest.py::test_complete_daily_limit_reject_tc18 + test_quest.py::test_complete_daily_limit_zero_unlimited_tc19 + test_quest.py::test_daily_lazy_reset_tc30 + test_quest.py::test_daily_no_reset_same_day + test_quest.py::test_daily_first_use_initializes + test_quest.py::test_daily_reset_explicit_alias + test_quest.py::test_limits_settings_override",
    "3.3-05 完成即移出 + 主线置顶常驻（main:true）+ 双板仲裁": "pytest:test_quest.py::test_complete_removes_active_counts_daily_tc21 + test_quest.py::test_complete_main_progress_and_stays_on_board_tc22 + test_quest.py::test_board_main_pinned_ordering_tc24 + test_quest.py::test_board_active_marker_tc25 + test_quest.py::test_board_zone_excluded + test_quest.py::test_board_weekly_event_slots + test_quest.py::test_resolve_board_index",
    "3.3-06 quest_accept/quest_complete/quest_abandon（幂等/消耗扣除/repeatable 衰减）": "pytest:test_quest.py::test_accept_success_records_active_and_daily + test_quest.py::test_accept_no_quest + test_quest.py::test_accept_already_active + test_quest.py::test_accept_completed_non_repeatable_rejected_tc21 + test_quest.py::test_accept_completed_repeatable_allowed + test_quest.py::test_accept_main_counts_toward_limit_p2_1 + test_quest.py::test_accept_chain_locked + test_quest.py::test_complete_consume_deducts_items + test_quest.py::test_complete_consume_insufficient_items_branch + test_quest.py::test_complete_repeatable_decay_tc23 + test_quest.py::test_complete_idempotent_d04 + test_quest.py::test_abandon_removes_active_tc27 + test_quest.py::test_abandon_not_active + test_quest.py::test_progress_three_primitives_display",
    "3.3-07 /任务 指令接线（接取/交付/信息/放弃 + 页码夹取 + TPL-12）": "pytest:test_quest_commands.py::test_quest_noarg_board_page1 + test_quest_commands.py::test_quest_board_npc_section_page2 + test_quest_commands.py::test_quest_clamp_last_page + test_quest_commands.py::test_quest_invalid_input_tpl12 + test_quest_commands.py::test_quest_accept_seq + test_quest_commands.py::test_quest_accept_compact_forms + test_quest_commands.py::test_quest_deliver_reward_result_prompt + test_quest_commands.py::test_quest_deliver_consume_removes_items + test_quest_commands.py::test_quest_deliver_condition_not_met + test_quest_commands.py::test_quest_info + test_quest_commands.py::test_quest_abandon_fixed_subword + test_quest_commands.py::test_quest_missing_seq_tpl12 + test_quest_commands.py::test_parse_command_integration + test_quest_commands.py::test_register_quest_commands",
    # ── 3.4 签到（contract §3.4；细化_2b5 33 TC）──
    "3.4-01 CheckinDef 多表结构 + validate_checkins（三键/里程碑/奖励结构）": "pytest:test_checkin_models.py::test_checkindef_accessors + test_checkin_models.py::test_checkindef_activity_accessors + test_checkin_models.py::test_checkindef_defaults + test_checkin_models.py::test_three_types_enum + test_checkin_models.py::test_activity_requires_window + test_checkin_models.py::test_legal_checkin_full_green + test_checkin_models.py::test_id_required_and_duplicate + test_checkin_models.py::test_loop_missing_cycle_days_warning + test_checkin_models.py::test_monthly_no_cycle_days + test_checkin_models.py::test_milestone_thresholds_increasing + test_checkin_models.py::test_streak_over_cycle_warning",
    "3.4-02 多表（loop/monthly/activity）并存一次结算": "pytest:test_checkin.py::test_first_sign_all_three_tables_settled + test_checkin.py::test_summary_message_contains_table_names + test_checkin.py::test_monthly_day_natural_month_day_progress + test_checkin.py::test_loop_day_rotation_cycle_7 + test_checkin.py::test_daily_fallback_first_day_note + test_checkin.py::test_activity_not_started_auto_inactive + test_checkin.py::test_activity_expired_auto_inactive",
    "3.4-03 连签独立计数（streak）+ 里程碑不重复 + bonus 倍率": "pytest:test_checkin.py::test_streak_independent_per_table + test_checkin.py::test_streak_milestone_extra_reward + test_checkin.py::test_streak_milestone_not_regrant_same_run + test_checkin.py::test_break_reset_streak_to_one + test_checkin.py::test_break_no_reset_accumulates + test_checkin.py::test_month_milestone_once_per_month + test_checkin.py::test_bonus_multiplier_scaling + test_checkin.py::test_monthly_total_fragmented_accumulate + test_checkin.py::test_month_total_rollover_reset_keep_longline",
    "3.4-04 补签只计不补发（用户裁决⑦）+ 两通道 + 月上限": "pytest:test_checkin.py::test_makeup_disabled_by_default + test_checkin.py::test_makeup_card_channel_restores_counters_no_reward + test_checkin.py::test_makeup_currency_channel_deducts + test_checkin.py::test_makeup_insufficient_currency_no_deduct + test_checkin.py::test_makeup_month_limit + test_checkin.py::test_makeup_max_zero_unlimited + test_checkin.py::test_makeup_same_day_idempotent_no_charge + test_checkin.py::test_makeup_no_milestone_grant + test_checkin.py::test_makeup_default_table_is_primary_loop",
    "3.4-05 [签到:<表名>.<字段>] 三键（用户裁决⑧ + 缺省表名=主表 loop）": "pytest:test_checkin.py::test_three_keys_value_default_loop + test_checkin.py::test_three_keys_monthly_and_activity + test_checkin_models.py::test_checkin_key_parsing + test_checkin_models.py::test_checkin_key_field_constants + test_checkin_models.py::test_checkin_key_table_ref_missing + test_checkin_models.py::test_checkin_key_fallback_loop_ref + test_checkin.py::test_condition_engine_consumes_checkin_projection + test_checkin.py::test_projection_refreshes_after_settlement",
    "3.4-06 checkin_do（幂等防重/版本 tx/失败跳过不中断表结算）": "pytest:test_checkin.py::test_same_day_repeat_idempotent_no_regrant + test_checkin.py::test_version_idempotent_tx_replay + test_checkin.py::test_reward_failure_skip_does_not_abort_table + test_checkin.py::test_checkin_state_query_pure_read + test_checkin.py::test_item_reward_via_add_item_hook + test_checkin.py::test_constants_exposed + test_checkin.py::test_day_index_of_helpers",
    "3.4-07 /签到 指令接线（今日/状态/补签 + 页码夹取 + TPL-12）": "pytest:test_checkin_commands.py::test_checkin_noarg_today_page1 + test_checkin_commands.py::test_checkin_today_page2 + test_checkin_commands.py::test_checkin_clamp_last_page + test_checkin_commands.py::test_checkin_invalid_input_tpl12 + test_checkin_commands.py::test_checkin_idempotent_still_shows_progress + test_checkin_commands.py::test_checkin_status_page1 + test_checkin_commands.py::test_checkin_makeup_by_table_id + test_checkin_commands.py::test_checkin_makeup_by_table_name + test_checkin_commands.py::test_checkin_makeup_default_main_loop + test_checkin_commands.py::test_checkin_makeup_compact + test_checkin_commands.py::test_parse_command_integration + test_checkin_commands.py::test_register_checkin_commands",
    # ── 批次7 集成（contract §4 批次7 / §5 端到端冒烟）──
    "批次7-01 端到端冒烟（NPC 对话→商店购买→任务接取/交付→签到 全链路）": "pytest:test_e2e_m4_smoke.py::test_smoke_subprocess_exit0_and_green_line + test_e2e_m4_smoke.py::test_run_smoke_green_and_deterministic + test_e2e_m4_smoke.py::test_path_assertion_counts + test_e2e_m4_smoke.py::test_smoke_core_run_green",
}

# 子进程 pytest 目标文件：实际落盘 M4 相关测试（全绿要求；缺失文件黄提示跳过不判失败）
PYTEST_FILES: list = [
    # ── A1/A2/A3 公共基础 ──
    "tests/unit/test_reward.py",              # A1 dispatch_reward（内联/货币/物品/rep/幂等/失败跳过）
    "tests/unit/test_condition_engine.py",    # A2 eval_condition（9 运算符/三原语/组合/互译/校验）
    "tests/unit/test_dayroll.py",             # A3 today_of（重置时刻/懒补刷/跨周/时间窗）
    # ── 2.x 指令解析层 ──
    "tests/unit/test_parsers.py",             # 2.1 分隔符五类/紧凑双认/快捷/别名/会话路由
    "tests/unit/test_router.py",              # 2.1 路由管线/白名单/GM 集/快捷注册表
    "tests/unit/test_sender.py",              # 2.2 分段发送/CQ 转义/TPL-12/13/14
    "tests/unit/test_list_render.py",         # 2.2 列表渲染/TPL-08/页码夹取
    "tests/unit/test_basic_commands.py",      # 2.3 /查看 /背包 /装备 /技能 /帮助
    "tests/unit/test_gm_commands.py",         # 2.4 /gm 权限三级/静默/留痕/禁绑
    # ── 3.1 NPC/对话 ──
    "tests/unit/test_npc_models.py",          # 3.1 NPCDef/validate_npcs
    "tests/unit/test_npc.py",                 # 3.1 发牌员三策略/10 类动作/deal
    "tests/unit/test_dialog.py",              # 3.1 会话状态机/深度软拦/菜单折叠
    # ── 3.2 商店 ──
    "tests/unit/test_shop_models.py",         # 3.2 ShopDef/validate_shops/裁决⑤⑥
    "tests/unit/test_shop.py",                # 3.2 shop_buy/sell/刷新/防双扣
    "tests/unit/test_shop_commands.py",       # 3.2 /商店 /购买 /出售
    # ── 3.3 任务 ──
    "tests/unit/test_quest_models.py",        # 3.3 QuestDef/validate_quests
    "tests/unit/test_quest.py",               # 3.3 quest_accept/complete/abandon/防刷
    "tests/unit/test_quest_commands.py",      # 3.3 /任务 接取/交付/信息/放弃
    # ── 3.4 签到 ──
    "tests/unit/test_checkin_models.py",      # 3.4 CheckinDef/validate_checkins/三键
    "tests/unit/test_checkin.py",             # 3.4 checkin_do/makeup/里程碑
    "tests/unit/test_checkin_commands.py",    # 3.4 /签到 今日/状态/补签
    # ── 批次7 端到端冒烟（DLY-08 已翻转；缺失 → 黄提示,verify_m6 复核按失败）──
    "tests/unit/test_e2e_m4_smoke.py",        # 批次7-01 全链路冒烟（契约 §4 批次7 / §5）
]


def check(name: str, fn) -> None:
    try:
        fn()
        _PASS.append(name)
        print(f"  ✓ {name}")
    except Exception as e:  # noqa: BLE001
        _FAIL.append((name, str(e)))
        print(f"  ✗ {name}: {e}")


def _yellow(text: str) -> None:
    print(f"  [黄] {text}")


# ==============================================================================
# 核心断言 ①：关键模块可导入（M4 全部新增/改动模块）
# ==============================================================================
_MODULES: dict = {
    # 公共基础 A1-A3
    "reward": "qbot_rpg.core.reward",
    "condition_engine": "qbot_rpg.engine.condition_engine",
    "dayroll": "qbot_rpg.core.dayroll",
    # 指令解析层 2.x
    "parsers": "qbot_rpg.commands.parsers",
    "sender": "qbot_rpg.commands.sender",
    "router": "qbot_rpg.commands.router",
    "list_render": "qbot_rpg.core.message_format.list_render",
    "basic_commands": "qbot_rpg.commands.basic_commands",
    "gm_commands": "qbot_rpg.commands.gm_commands",
    # 交互系统 3.x
    "npc_models": "qbot_rpg.content.npc_models",
    "npc": "qbot_rpg.core.npc",
    "dialog": "qbot_rpg.core.dialog",
    "shop_models": "qbot_rpg.content.shop_models",
    "shop": "qbot_rpg.core.shop",
    "shop_commands": "qbot_rpg.commands.shop_commands",
    "quest_models": "qbot_rpg.content.quest_models",
    "quest": "qbot_rpg.core.quest",
    "quest_commands": "qbot_rpg.commands.quest_commands",
    "checkin_models": "qbot_rpg.content.checkin_models",
    "checkin": "qbot_rpg.core.checkin",
    "checkin_commands": "qbot_rpg.commands.checkin_commands",
}


def t_module_imports() -> None:
    import importlib

    for label, dotted in _MODULES.items():
        importlib.import_module(dotted)
    # 关键类可引用/冒烟（不触发有副作用构造；Router/Sender 无参可实例化）
    from qbot_rpg.commands.parsers import ParsedCommand  # noqa: F401
    from qbot_rpg.commands.router import CommandSpec, Router, RoutingContext, RouteResult  # noqa: F401
    from qbot_rpg.commands.sender import Sender  # noqa: F401
    from qbot_rpg.core.dialog import DialogSession  # noqa: F401
    from qbot_rpg.content.npc_models import NPCDef  # noqa: F401
    from qbot_rpg.content.shop_models import ShopDef, ShopItemDef  # noqa: F401
    from qbot_rpg.content.quest_models import QuestDef  # noqa: F401
    from qbot_rpg.content.checkin_models import CheckinDef  # noqa: F401
    Router()
    Sender()
    Router().register(CommandSpec(name="ping", whitelisted=True))


# ==============================================================================
# 核心断言 ②：M4 关键函数存在（dispatch_reward/eval_condition/today_of/parse_command/
# deal/checkin_do/quest_accept/shop_buy 等）
# ==============================================================================
_KEY_FUNCS: list = [
    # (模块键, 类名或 None, 成员/函数名)
    # A1-A3 公共基础
    ("reward", None, "dispatch_reward"),
    ("reward", None, "expand_inline_reward"),
    ("reward", None, "normalize_reward"),
    ("condition_engine", None, "eval_condition"),
    ("condition_engine", None, "validate_condition"),
    ("dayroll", None, "today_of"),
    ("dayroll", None, "days_elapsed"),
    ("dayroll", None, "weeks_elapsed"),
    ("dayroll", None, "advance_cycles"),
    ("dayroll", None, "is_window_open"),
    ("dayroll", None, "resolve_refresh_time"),
    # 2.1 解析层
    ("parsers", None, "parse_command"),
    ("parsers", "ParsedCommand", "positional"),
    ("parsers", "ParsedCommand", "is_command"),
    ("parsers", None, "is_session_subword"),
    ("router", "Router", "register"),
    ("router", "Router", "dispatch"),
    ("router", None, "route_message"),
    ("router", None, "route_and_expand"),
    ("router", None, "check_shortcut_binding"),
    ("router", None, "check_shortcut_limit"),
    ("router", None, "resolve_command_word"),
    ("router", None, "register_command"),
    # 2.2 模板
    ("sender", "Sender", "send"),
    ("sender", None, "format_tpl12"),
    ("sender", None, "format_tpl13"),
    ("sender", None, "format_tpl14"),
    ("sender", None, "segment_by_length"),
    ("sender", None, "cq_escape"),
    ("list_render", None, "resolve_page"),
    ("list_render", None, "page_items"),
    ("list_render", None, "render_list_page"),
    ("list_render", None, "render_footer"),
    # 2.3 基础指令组
    ("basic_commands", None, "register_basic_commands"),
    ("basic_commands", None, "cmd_view"),
    ("basic_commands", None, "cmd_help"),
    ("basic_commands", None, "resolve_equip_slot"),
    # 2.4 GM 指令
    ("gm_commands", None, "handle_gm_command"),
    ("gm_commands", None, "register_gm_commands"),
    ("gm_commands", None, "check_gm_permission"),
    ("gm_commands", None, "audit_hmac"),
    ("gm_commands", None, "build_audit_record"),
    ("gm_commands", None, "gm_binding_guard"),
    ("gm_commands", None, "is_gm_command_name"),
    # 3.1 NPC/对话
    ("npc_models", None, "parse_npcs"),
    ("npc_models", None, "validate_npcs"),
    ("npc_models", "NPCDef", "icon"),
    ("npc_models", "NPCDef", "dialogues"),
    ("npc", None, "deal"),
    ("npc", None, "dispatch_action"),
    ("npc", None, "draw_card"),
    ("npc", None, "build_pool"),
    ("npc", None, "available_quests"),
    ("npc", None, "normalize_strategy"),
    ("dialog", "DialogSession", "step"),
    ("dialog", "DialogSession", "to_snapshot"),
    ("dialog", "DialogSession", "from_snapshot"),
    ("dialog", None, "route_session_input"),
    ("dialog", None, "resolve_max_dialog_depth"),
    ("dialog", None, "is_depth_blocked"),
    # 3.2 商店
    ("shop_models", None, "parse_shops"),
    ("shop_models", None, "validate_shops"),
    ("shop_models", "ShopDef", "items"),
    ("shop_models", "ShopItemDef", "price"),
    ("shop", None, "shop_buy"),
    ("shop", None, "shop_sell"),
    ("shop", None, "shop_browse"),
    ("shop", None, "shop_apply_refresh"),
    ("shop", None, "shop_lazy_refresh"),
    ("shop", None, "resolve_shop_arg"),
    ("shop", None, "set_current_shop"),
    ("shop", None, "shop_open_state"),
    # 3.3 任务
    ("quest_models", None, "parse_quests"),
    ("quest_models", None, "validate_quests"),
    ("quest_models", "QuestDef", "is_main"),
    ("quest", None, "quest_accept"),
    ("quest", None, "quest_complete"),
    ("quest", None, "quest_abandon"),
    ("quest", None, "quest_board"),
    ("quest", None, "quest_daily_reset"),
    ("quest", None, "quest_conditions_met"),
    ("quest", None, "resolve_board_index"),
    # 3.4 签到
    ("checkin_models", None, "parse_checkins"),
    ("checkin_models", None, "validate_checkins"),
    ("checkin_models", None, "parse_checkin_key"),
    ("checkin_models", "CheckinDef", "effective_type"),
    ("checkin", None, "checkin_do"),
    ("checkin", None, "checkin_makeup"),
    ("checkin", None, "checkin_value"),
    ("checkin", None, "checkin_state"),
    ("checkin", None, "resolve_checkin_table"),
]


def t_key_functions() -> None:
    import importlib
    import re as _re

    for label, cls_name, member in _KEY_FUNCS:
        mod = importlib.import_module(_MODULES[label])
        obj = getattr(mod, cls_name) if cls_name else mod
        # 类属性（property 访问器，如 ParsedCommand.positional/name/is_command）按「存在」核验，
        # 可调用方法按 callable 核验——两者均算关键成员存在
        attr = getattr(obj, member, None)
        assert attr is not None, f"{label}.{cls_name or ''}.{member} 缺失"
        assert callable(attr) or isinstance(attr, property), \
            f"{label}.{cls_name or ''}.{member} 既非可调用亦非属性"
    # M4 铁律 ① 零 NoneBot import（commands/ 层除外）：探针扫解析核心模块源码（对齐 verify_m3 零定时器探针口径）
    import re as _re
    for label, dotted in _MODULES.items():
        if label in ("parsers", "router", "sender", "basic_commands", "gm_commands",
                     "shop_commands", "quest_commands", "checkin_commands"):
            continue  # commands/ 层为 NoneBot 接线豁免层
        mod = importlib.import_module(dotted)
        assert mod.__file__, f"{dotted} 无源文件（namespace 包），无法探针"
        src = open(mod.__file__, encoding="utf-8").read()
        # 只拦实际 import 语句（import nonebot / from nonebot …），注释/文档字符串声明铁律本身不算
        assert not _re.search(r"^\s*(?:from nonebot|import nonebot)", src, _re.M), \
            f"{dotted} 含 nonebot import（违反 M4 铁律 ①）"


# ==============================================================================
# 核心断言 ③：COVERAGE 自洽（83 条覆盖点 = 83 已承载 + 0 DELAYED；批次7-01 已翻转，D8 DLY-08）
# ==============================================================================
_SECTION_COUNTS = {
    "A1": 7, "A2": 11, "A3": 6,        # §1 公共基础
    "2.1": 9, "2.2": 5, "2.3": 6, "2.4": 5,  # §2 指令解析层
    "3.1": 10, "3.2": 9, "3.3": 7, "3.4": 7,  # §3 交互系统
    "批次7": 1,                        # §4 批次7 集成（端到端冒烟，DLY-08 已翻转）
}


def t_coverage_self_consistent() -> None:
    from collections import Counter
    import re

    assert len(COVERAGE) == 83, f"COVERAGE 应为 83 条覆盖点，实际 {len(COVERAGE)}"
    sec = Counter(k.split("-")[0] for k in COVERAGE)
    for name, want in _SECTION_COUNTS.items():
        assert sec.get(name, 0) == want, \
            f"{name} 段应为 {want} 条，实际 {sec.get(name, 0)}"
    # 诚实化声明格式自洽：每条只允许 pytest: 承载或 DELAYED 注明理由
    for k, v in COVERAGE.items():
        assert v.startswith("pytest:") or v.startswith("DELAYED"), \
            f"{k} 承载格式非法（须 pytest: 或 DELAYED）：{v[:60]}"
    # 声明的 pytest 承载文件必须落盘 + 声明的 测试函数名 必须存在于对应文件 def 列表
    # （函数级核验：比 verify_m3 仅查文件更严，防止「文件在但用例名对不上」的虚假承载）
    unit_dir = REPO / "tests" / "unit"
    fn_cache: dict = {}
    for v in COVERAGE.values():
        if not v.startswith("pytest:"):
            continue
        for chunk in v[len("pytest:"):].split(" + "):
            m = re.match(r"^(test_[A-Za-z0-9_]+\.py)::(test_[A-Za-z0-9_]+)$", chunk.strip())
            assert m, f"承载引用格式非法：{chunk[:80]}"
            fname, fn = m.group(1), m.group(2)
            path = unit_dir / fname
            assert path.exists(), f"COVERAGE 声明引用缺失测试文件：{fname}"
            if fname not in fn_cache:
                src = path.read_text(encoding="utf-8")
                fn_cache[fname] = set(re.findall(r"^\s*def (test_[A-Za-z0-9_]+)\s*\(", src, re.M))
            assert fn in fn_cache[fname], f"{fname} 中不存在用例 {fn}（虚假承载，禁止）"
    # 承载/DELAYED 计数自洽
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    carried = len(COVERAGE) - len(delayed)
    assert carried + len(delayed) == 83
    print(f"    COVERAGE 核算：83 覆盖点 = {carried} 已承载 + {len(delayed)} DELAYED"
          f"（{sum(len(c.split(' + ')) for c in (v for v in COVERAGE.values() if v.startswith('pytest:')))} 条 pytest 用例引用全数核验存在）")
    print(f"    DELAYED（{len(delayed)}）：" + ", ".join(k.split(" ")[0] for k in delayed))


# ==============================================================================
# 汇总与子进程 pytest 门禁
# ==============================================================================
def main() -> int:
    print("== verify_m4 脚本核心断言（M4 交互系统里程碑，依据 m4_shared_contract §5 + 细化_5d）==")
    checks = [
        ("① 关键模块可导入（reward/condition_engine/dayroll/parsers/sender/router/list_render/"
         "basic_commands/gm_commands/npc_models/npc/dialog/shop_models/shop/shop_commands/"
         "quest_models/quest/quest_commands/checkin_models/checkin/checkin_commands，共 21 模块）",
         t_module_imports),
        ("② M4 关键函数存在（dispatch_reward/eval_condition/today_of/parse_command/deal/"
         "checkin_do/quest_accept/quest_complete/shop_buy/shop_sell/checkin_makeup/route_message/"
         "Sender.send 等 91 项 + 零 NoneBot 铁律探针）",
         t_key_functions),
        ("③ COVERAGE 自洽（83 覆盖点：A1 7 + A2 11 + A3 6 + 2.1 9 + 2.2 5 + 2.3 6 + 2.4 5 + "
         "3.1 10 + 3.2 9 + 3.3 7 + 3.4 7 + 批次7 1）",
         t_coverage_self_consistent),
    ]
    for name, fn in checks:
        check(name, fn)

    print("\n== 子进程 pytest（M4 相关测试文件；文件缺失（异常）→ 黄提示跳过）==")
    existing = [f for f in PYTEST_FILES if (REPO / f).exists()]
    missing = [f for f in PYTEST_FILES if not (REPO / f).exists()]
    for f in missing:
        _yellow(f"{f} 缺失（DLY-09 起 missing 按失败由 verify_m6 复核）→ 跳过；对应组件级覆盖已由拆分测试文件落盘生效")
    pytest_ok = False
    if existing:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *existing, "-q", "--tb=short", "-rN",
             "--disable-warnings"],
            cwd=str(REPO), capture_output=True, text=True, timeout=600,
        )
        tail = "\n".join((proc.stdout or "").splitlines()[-4:])
        print(tail)
        if proc.returncode != 0:
            print((proc.stdout or "")[-3000:])
        pytest_ok = proc.returncode == 0
    else:
        _yellow("无已落盘 pytest 文件，跳过子进程段（本脚本核心断言仍执行）")

    print("\n== 覆盖声明（m4_shared_contract §1/§2/§3 + §5；83 条覆盖点诚实化逐条标注）==")
    for tc, carrier in COVERAGE.items():
        print(f"  {tc} → {carrier}")
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    carried = len(COVERAGE) - len(delayed)
    print(f"\n  DELAYED 项（{len(delayed)}/83）：{', '.join(k.split(' ')[0] for k in delayed)}")

    n_fail = len(_FAIL)
    print(f"\n结果：脚本断言 {len(_PASS)} 通过 / {n_fail} 失败；pytest {'✔' if pytest_ok else '✘'}"
          f"{'（缺失文件黄提示不判失败）' if missing else ''}")
    if n_fail or not pytest_ok:
        for name, err in _FAIL:
            print(f"  FAIL {name}: {err}")
        print("M4 门禁：verify_m4 未通过 ✘（失败回溯：m4_shared_contract §5 + 断言原文见上；D8 VG-20 统一「M<N> 门禁」输出）")
        return 1
    print(f"M4 门禁：verify_m4 全绿 ✔（83 覆盖点中 {carried} 已承载 + {len(delayed)} DELAYED；"
          f"子进程 pytest {len(existing)} 文件全绿{'，' + str(len(missing)) + ' 文件缺失黄提示' if missing else ''}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
