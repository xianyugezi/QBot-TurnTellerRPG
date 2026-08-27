#!/usr/bin/env python3
"""M3 地图里程碑门禁（依据：细化_5d §2.1 L92 M3 行 + m3_shared_contract §7 = 81 条 TC，G3 门禁）。

覆盖口径（诚实化覆盖声明原则，对齐 verify_m2）：
- 81 条 TC 逐条在 COVERAGE 声明承载位置——「pytest:<文件>::<用例>」或「DELAYED:依赖 X」；
  绝不允许声称覆盖实际未覆盖的 TC：
    * 2a1c-TC-06/07（紧凑「进入上」/解析双认幂等）→ DELAYED，依赖 M4（指令分隔符/解析层）
    * 2a1c-TC-22（dungeon_entrances 防嵌套红拦）→ DELAYED，依赖 M6（loader 校验器规则未接线——
      map_models 工程补白 M16 仅结构提示不校验存在）
    * 2a2-TC-10（PV>0 期间 debuff 效果减半）→ DELAYED，依赖 M4（战斗接线读换区 PV 门禁）
    * 2a2-TC-14（追击态 /进入up 无空格校验）→ DELAYED，依赖 M4（指令分隔符）
    * 2a3-TC-2a3-03（双副本并发进度独立）→ DELAYED，依赖 M4（会话容器接线；单会话持久化已承载）
- 部分承载的 TC：载明已承载的 pytest 载体 + 明确标注未承载段依赖 M4/M6（不冒充全量覆盖）。
- 落盘文件与 §7 矩阵命名差异：§7 列的 test_map_dungeon_link/test_dungeon/test_weather/test_worldtime
  未落盘，实际由 test_movement（route_* 承接副本入口）+ test_dungeon_flow/boss/subquest（2a3）+
  test_weather_pool/conditions/consumers/validator（2a4b）+ test_worldtime_changes（2a4a）等拆分承载；
  契约命名文件缺失 → 黄提示跳过（不判失败，对齐 verify_m2 缺失文件语义）。
- 机制：脚本内核心断言（① 关键模块可导入 ② M3 关键函数存在 ③ COVERAGE 自洽 81 TC 计数）
  + 子进程跑 M3 相关 pytest 测试文件（PYTEST_FILES 全绿；缺失文件黄提示不判失败）。
- 2a1a/2a1b/2a4a/2a4c 走 SUPPLEMENT 补充引擎段（worldtime 必测场景 L296 刷新补刷/离线封顶/跨天判定
  + M43 时间锚点回归：test_m43_regression + test_time_regression），不计入 81 计数。

用法：.venv/bin/python scripts/verify/verify_m3.py
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
# 覆盖声明：81 条 TC 逐条承载位置（依据：m3_shared_contract §7 矩阵 + 细化_2a1c/2a2/2a3/2a4b #TC）
# ----------------------------------------------------------------------------------
COVERAGE: dict = {
    # ── 2a1c 地图副本衔接（25 TC，细化_2a1c §⑥；路 A：test_movement route_* + test_dungeon_flow）──
    "2a1c-TC-01 双向通道来回": "pytest:test_movement.py::test_bidirectional_walk_round_trip + test_map_graph.py::test_can_move_bidirectional_forward + test_can_move_bidirectional_return_trip",
    "2a1c-TC-02 单向配置逆向拦截": "pytest:test_movement.py::test_one_way_forward_walkable + test_one_way_reverse_blocked_at_destination（test_map_graph.py::test_can_move_one_way_* 同口径）",
    "2a1c-TC-03 捷径 one_way 逆向不静默失败": "pytest:test_movement.py::test_one_way_reverse_blocked_at_destination（/进入 逆向被拦并提示）",
    "2a1c-TC-04 非 上/下/左/右 字面量": "pytest:test_movement.py::test_direction_aliases_cover_contract + test_invalid_direction_rejected",
    "2a1c-TC-05 方向合法但 exits 空": "pytest:test_movement.py::test_dead_end_direction_blocked + test_map_graph.py::test_can_move_dead_end_direction_missing（此方向没有通道，位置不变）",
    "2a1c-TC-06 紧凑「进入上」无空格双认": "DELAYED：依赖 M4（指令分隔符解析层）——movement 层仅承载方向字面量/别名（test_direction_alias_semantics），紧凑形态分割属指令解析",
    "2a1c-TC-07 /进入 上 与 进入上 幂等": "DELAYED：依赖 M4（指令解析层）——双认幂等为解析层语义，movement 层不承接",
    "2a1c-TC-08 入口显式名进入 BOSS 副本（有钥匙）": "pytest:test_movement.py::test_route_entrance_by_explicit_name（解析到 dungeon 入口）+ test_dungeon_flow.py::test_enter_boss_consumes_item_and_counts（扣 1 把/落位入口区）",
    "2a1c-TC-09 /进入 2（序号不带 *）": "pytest:test_movement.py::test_route_entrance_by_index_one_based",
    "2a1c-TC-10 无钥匙拦截": "pytest:test_dungeon_flow.py::test_enter_boss_missing_item_blocked（不入场/不扣道具/不消耗次数）",
    "2a1c-TC-11 entry_limit 超次拦截": "pytest:test_dungeon_flow.py::test_enter_boss_limit_exceeded_blocked_no_item_loss + test_enter_boss_limit_ok_at_boundary",
    "2a1c-TC-12 探索副本 entry_item=null 直接进": "pytest:test_dungeon_flow.py::test_enter_explore_lenient_no_cost + test_enter_defaults_and_lenient_variants",
    "2a1c-TC-13 副本内 4 方向推进": "pytest:test_dungeon_flow.py::test_explore_run_full_flow + test_explore_run_cleared_maps_tracked（通道层：test_movement.py::test_route_direction_walks_channel）",
    "2a1c-TC-14 非入口节点无副本入口": "pytest:test_movement.py::test_route_node_without_entrances（此处没有副本入口）",
    "2a1c-TC-15 不存在入口名回退候选": "pytest:test_movement.py::test_route_unmatched_name（没有这个入口/方向）",
    "2a1c-TC-16 主动离开回锚点+重置": "pytest:test_dungeon_flow.py::test_explore_run_full_flow（R8 回外部锚点 + 离开=重置）+ test_leave_m12_m13_m14_and_s0 + test_leave_resets_session_progress",
    "2a1c-TC-17 战斗中断恢复入口快照续玩": "pytest:test_snapshot_resume.py::TestResumeFromSnapshot（ai_state+combo_state 保留/仍在副本内/回外部坐标）+ test_chase_resume.py::TestPrepareResumeBattle",
    "2a1c-TC-18 副本安全区 /休息 不重置": "pytest:test_rest.py::TestRestInDungeon + TestRestIsNotExit + test_dungeon_flow.py::test_explore_run_rest_gate_and_after_leave",
    "2a1c-TC-19 副本内死亡复活回入口区": "pytest:test_dungeon_persist.py::TestOnDungeonDeath（复活点/BOSS death_policy keep）+ test_dungeon_flow.py::test_explore_run_death_recover_flow",
    "2a1c-TC-20 副本内 /进入 指向集合外": "pytest:test_dungeon_flow.py::test_explore_run_walk_outside_dungeon_maps_blocked（集合隔离 R5）",
    "2a1c-TC-21 子任务副本外不推进": "pytest:test_dungeon_subquest.py::test_activate_in_dungeon_progress_only（进副本自动激活；副本外无进度键）",
    "2a1c-TC-22 副本内部地图配 dungeon_entrances 红拦": "DELAYED：依赖 M6（loader 校验器防嵌套/递归规则未接线——map_models 工程补白 M16 仅结构提示不校验存在；现仅 test_maps_schema.py::test_map_def_8_field_accessors 承载 8 字段访问器）",
    "2a1c-TC-23 /进入 无参": "pytest:test_movement.py::test_route_empty_arg（P1 预留：需要参数，不自动行走）",
    "2a1c-TC-24 /进入 99 序号越界": "pytest:test_movement.py::test_route_index_out_of_range（序号无效，位置不变）",
    "2a1c-TC-25 /进入 熔岩洞窟*2（含 *）": "pytest:test_movement.py::test_route_star_rejected（不支持数量）",
    # ── 2a2 换区追击（24 TC，细化_2a2 §⑥；路 Q：test_chase + test_dungeon_boss + test_chase_resume）──
    "2a2-TC-01 血量≤30% 触发换区": "pytest:test_chase.py::TestChaseTrigger::test_threshold_hit + test_dungeon_boss.py::TestShouldZoneChange::test_threshold_hit_and_miss",
    "2a2-TC-02 血量>30% 全程不触发": "pytest:test_chase.py::TestChaseTrigger::test_threshold_boundary_and_miss + test_dungeon_boss.py::TestShouldZoneChange::test_threshold_hit_and_miss（30.1% 不触发）",
    "2a2-TC-03 血量=0 当回合击杀优先": "pytest:test_chase.py::TestChaseTrigger::test_hp_zero_kill_priority + test_dungeon_boss.py::TestShouldZoneChange::test_hp_zero_kill_priority",
    "2a2-TC-04 普通怪（无 zone_change）永不换区": "pytest:test_chase.py::TestChaseTrigger::test_no_targets_or_missing_cfg + test_dungeon_boss.py::TestShouldZoneChange::test_no_targets_or_missing_cfg（无配置/空候选不触发）",
    "2a2-TC-05 提示含目标地图名": "pytest:test_chase.py::TestBeginChase::test_hint_with_maps_name + test_unknown_map_fallback_to_id",
    "2a2-TC-06 随机候选 ∈ targets 且两目标均现": "pytest:test_chase.py::TestPickChaseTarget::test_different_rng_different + test_random_index_mapping",
    "2a2-TC-07 PV=floor(300×0.5)=150": "pytest:test_chase_resume.py::test_pv_half_value_floor_odd + test_dungeon_boss.py::TestOnChaseContinue::test_markers_and_pv_half_value",
    "2a2-TC-08 PV=floor(201×0.5)=100 向下取整": "pytest:test_chase_resume.py::test_pv_half_value_floor_odd（奇数 201→100）+ test_dungeon_boss.py::TestOnChaseContinue::test_pv_half_value_floor_odd",
    "2a2-TC-09 换区结算即时恢复 PV150": "pytest:test_dungeon_boss.py::TestOnChaseContinue::test_markers_and_pv_half_value（恢复时机=换区结算）+ test_chase_resume.py::test_pv_recover_source",
    "2a2-TC-10 PV>0 期间 debuff 减半门禁": "DELAYED：依赖 M4（战斗接线）——PV>0 期间效果减半需战斗层读换区 PV 门禁；层数保留语义已由 test_chase_resume.py::TestPrepareResumeBattle 装配承载",
    "2a2-TC-11 换区后血量=H0 不回复": "pytest:test_chase_resume.py::test_hp_kept_residual_not_reset + test_dungeon_boss.py::TestOnChaseContinue::test_boss_state_hp_passthrough",
    "2a2-TC-12 续战首回合残血 28% 保持": "pytest:test_chase_resume.py::test_hp_kept_residual_not_reset（残血原值透传不重满）",
    "2a2-TC-13 追击态走通道/无通道提示": "pytest:test_chase.py::TestPursue::test_catch_on_reaching_target + test_blocked_move_not_counted（无通道不计错/位置不变）",
    "2a2-TC-14 追击态 /进入up 无空格": "DELAYED：依赖 M4（指令分隔符校验层）",
    "2a2-TC-15 先到非目标图不遭遇": "pytest:test_chase.py::TestPursue::test_wrong_step_not_caught_and_counted + test_back_to_start_misses（错步计数/可折返）",
    "2a2-TC-16 至目标图触发续战": "pytest:test_chase.py::TestPursue::test_catch_on_reaching_target + test_caught_prepares_continue_data",
    "2a2-TC-17 续战首回合开场技": "pytest:test_chase_resume.py::test_caught_assembles_full_resume_context + test_dungeon_boss.py::TestOnChaseContinue::test_markers_and_pv_half_value（opening_skill 标记/续战装配）；battle_start 触发表命中执行依赖 M4 战斗接线",
    "2a2-TC-18 追击全程玩家四项数值不变": "pytest:test_chase.py::TestPursue（pursue 仅更新 map_id/追击上下文，零玩家战斗数值改动——结构保证）+ test_snapshot_resume.py::test_stub_factory_resumes_with_all_preserved_flags（续战全标记保留）",
    "2a2-TC-19 追击绕行血量/PV 不变": "pytest:test_chase.py::TestPursue::test_unreachable_after_wrong_move_info_flag + test_dungeon_boss.py::TestOnChaseContinue::test_boss_state_hp_passthrough（原地等待不随时间回涨）",
    "2a2-TC-20 续战退出恢复入口残血+PV150": "pytest:test_snapshot_resume.py::TestResumeFromSnapshot::test_chase_context_top_level_and_ai_state_fields + test_chase_resume.py::TestPrepareResumeBattle（快照保留换区进度）",
    "2a2-TC-21 追击态休息不重置": "pytest:test_rest.py::TestRestIsNotExit::test_rest_keeps_position_boss_subquest_chase",
    "2a2-TC-22 离开副本满状态重打+chasing 清空": "pytest:test_chase_resume.py::TestExitDungeonReset::test_non_battle_leave_resets_all + test_rest.py::test_rest_vs_leave_reset_contrast",
    "2a2-TC-23 死亡后离开触发重置": "pytest:test_chase_resume.py::TestExitDungeonReset::test_death_leave_resets_too + test_snapshot_resume.py::test_death_leave_resets_too",
    "2a2-TC-24 普通怪击杀后离开无残留": "pytest:test_chase_resume.py::TestExitDungeonReset::test_empty_fresh_session_leave + test_chase.py::TestChaseTrigger（无 zone_change 不换区）",
    # ── 2a3 副本两型（16 TC，细化_2a3 §⑥ TC-2a3-01~16；路 N：test_dungeon_flow + test_dungeon_boss + test_dungeon_subquest）──
    "2a3-TC-2a3-01 两型入口区分": "pytest:test_dungeon_flow.py::test_enter_explore_lenient_no_cost + test_enter_boss_consumes_item_and_counts + test_explore_run_rejects_boss_dungeon + test_dungeon_schema.py::test_boss_room_required_for_boss_type",
    "2a3-TC-2a3-02 地图共用": "pytest:test_dungeon_schema.py::test_legal_dungeons_zero_errors_with_maps + test_maps_empty_blocked（两型共用同组地图 ID 结构校验）；落石机制运行期触发依赖 M4 场景接线",
    "2a3-TC-2a3-03 进度独立": "DELAYED：依赖 M4（会话容器接线）——双副本并发会话进度独立验证；单会话持久化已由 test_dungeon_persist.py::TestSaveLoadSession 承载",
    "2a3-TC-2a3-04 探索版主流程": "pytest:test_dungeon_flow.py::test_explore_run_full_flow（S0→S1→精英→S5→S7）+ test_m3_m4_elite_escalate_and_done",
    "2a3-TC-2a3-05 BOSS 版完整节奏": "pytest:test_dungeon_flow.py::test_enter_boss_consumes_item_and_counts + test_dungeon_boss.py::TestPhaseFor/TestShouldZoneChange + test_chase.py::TestPursue + test_chase_resume.py::TestPrepareResumeBattle（组件级全链路）；决战击杀=通关结算依赖 M4 战斗接线",
    "2a3-TC-2a3-06 阶段机制三档": "pytest:test_dungeon_boss.py::TestPhaseFor::test_default_thresholds_boundaries + test_configurable_phases_via_boss_def（100/60/30 三档阈值/狂暴行动表）；大招循环/印记反制/连招锚点加速/阶段按钮 PV 门禁依赖 M4 战斗接线",
    "2a3-TC-2a3-07 子任务探索/收集": "pytest:test_dungeon_subquest.py::test_reach_zone_advance_and_complete + test_collect_batch_clamp + test_dungeon_flow.py::test_explore_run_full_flow",
    "2a3-TC-2a3-08 子任务清剿/机制/情报": "pytest:test_dungeon_subquest.py::test_defeat_counting_and_clamp + test_interact_complete + test_eval_condition_primitives",
    "2a3-TC-2a3-09 可选不阻塞 BOSS": "pytest:test_dungeon_subquest.py::test_optionality_incomplete_not_block_boss",
    "2a3-TC-2a3-10 死亡默认档 checkpoint 回退": "pytest:test_dungeon_persist.py::TestOnDungeonDeath::test_death_checkpoint_reached_rolls_back + test_death_default_revive_safe_zone_boss_kept + test_death_weakened_ban_and_expiry",
    "2a3-TC-2a3-11 死亡惩罚=重置档": "pytest:test_dungeon_persist.py::TestOnDungeonDeath::test_death_penalty_reset_clears_all + test_death_boss_state_reset_mode",
    "2a3-TC-2a3-12 死亡无惩罚档": "pytest:test_dungeon_persist.py::TestOnDungeonDeath::test_death_penalty_none_keeps_progress",
    "2a3-TC-2a3-13 未配 checkpoint 降级": "pytest:test_dungeon_persist.py::TestOnDungeonDeath::test_death_checkpoint_missing_config_degrades_to_reset + test_death_checkpoint_not_reached_degrades_to_reset",
    "2a3-TC-2a3-14 死亡≠离开/主动离开重置": "pytest:test_dungeon_flow.py::test_death_and_recover（S6 不重置）+ test_leave_m12_m13_m14_and_s0 + test_chase_resume.py::test_death_leave_resets_too",
    "2a3-TC-2a3-15 安全区休息≠离开": "pytest:test_rest.py::TestRestInDungeon + TestRestIsNotExit（五断言全量）+ test_dungeon_flow.py::test_rest_m15_and_state_query + test_explore_run_rest_gate_and_after_leave",
    "2a3-TC-2a3-16 战斗中断快照续玩": "pytest:test_snapshot_resume.py::TestResumeFromSnapshot + test_chase_resume.py::TestPrepareResumeBattle（ai_state+combo_state 全保留从残血/追击点继续）",
    # ── 2a4b 天气引擎（16 TC，细化_2a4b §⑥ TC-1~16；路 R：test_weather_pool + conditions + consumers + validator）──
    "2a4b-TC-1 默认池注册与键唯一": "pytest:test_weather_pool.py::test_validate_pool_dup_keys_red + test_weather_conditions.py::test_registered_keys_shape（默认 5 键注册）",
    "2a4b-TC-2 抽签确定性（同 tick 同池）": "pytest:test_weather_pool.py::test_map_weather_same_tick_same_value_across_instances + test_map_weather_matches_sha256_seed_formula",
    "2a4b-TC-3 seed 绑定 tick": "pytest:test_weather_pool.py::test_map_weather_different_ticks_reorder + test_map_weather_large_tick_and_negative_stable（tick 前进序列重排）",
    "2a4b-TC-4 weather_minutes 边界": "pytest:test_time_cycle_config.py::test_validate_v3_weather_minutes_below_min + test_validate_v3_weather_minutes_bad_type（29 拦/30·60 过）",
    "2a4b-TC-5 懒计算重启一致性": "pytest:test_weather_pool.py::test_map_weather_matches_sha256_seed_formula（确定性公式=重启不重抽）+ test_m43_regression.py::test_m43_weather_restart_no_redraw_same_value",
    "2a4b-TC-6 覆盖池取值": "pytest:test_weather_pool.py::test_map_pool_override_priority_sorted + test_map_weather_override_pool_result_in_override（覆盖池键列表做 seed）",
    "2a4b-TC-7 多图并发差异": "pytest:test_weather_pool.py::test_map_weather_override_pool_result_in_override（各图按生效池取值）+ test_weather_conditions.py::test_weather_by_map_context_binding（按图绑定）",
    "2a4b-TC-8 缺省/空数组=默认池": "pytest:test_weather_pool.py::test_map_pool_empty_override_falls_back_to_default + test_map_pool_missing_map_falls_back_to_default + test_map_weather_empty_override_uses_default",
    "2a4b-TC-9 覆盖池非法引用红拦": "pytest:test_weather_validator.py::test_v5_illegal_pool_red_block + test_weather_pool.py::test_validate_pool_missing_key_red",
    "2a4b-TC-10 怪物 weather_weights": "pytest:test_spawn_weather.py::test_refresh_weight_two_faster + test_refresh_weight_zero_no_spawn + test_spawn.py::test_refresh_weather_speedup_tc13 + test_refresh_weather_zero_no_refill_tc14（雾天 10/2=5 分/雨天 0 刷新）",
    "2a4b-TC-11 采集 weather_mods": "pytest:test_weather_consumers.py::test_mods_dict_form_rain_hit + test_mods_rarity_shift_clamp_top_and_bottom + test_mods_zero_rate_means_not_spawn（rate_mult×1.5 稀有+1 clamp 4 档/0 不出）",
    "2a4b-TC-12 战斗修正默认关+开启": "pytest:test_weather_consumers.py::test_combat_default_off_no_cfg + test_combat_enabled_true_takes_value + test_combat_bad_config_failsafe + test_weather_validator.py::test_v7_mults_key_red（非法键 V7 拦截）",
    "2a4b-TC-13 [天气:X] 条件真/假": "pytest:test_weather_conditions.py::test_weather_via_direct_weather_now + test_weather_by_map_context_binding（雨天图 rain 真 storm 假）",
    "2a4b-TC-14 上下文绑定": "pytest:test_weather_conditions.py::test_weather_by_map_context_binding（按玩家所在图取值）",
    "2a4b-TC-15 联合触发（AND）": "pytest:test_weather_consumers.py::test_lore_multi_condition_and（period midnight AND weather storm 双条件）",
    "2a4b-TC-16 消费方引用硬拦+池编辑重排": "pytest:test_weather_validator.py::test_v6_enum_red + test_v6_gather_weather_mods_red（消费方未注册引用红拦）+ test_w6_pool_config_reorder（池编辑后该 tick 起序列重排）",
}

# 补充引擎覆盖（超出 81 条具名 TC，不计入计数；与 5d §2.1 M3 行右侧「worldtime 必测场景 + M43 回归」对应）
SUPPLEMENT: dict = {
    "2a1a 地图 schema（8 字段/通道规则/隐藏门）": "pytest:test_maps_schema.py（合法零红零黄/exit·hidden·spawn·gate_guard 坏例）+ test_map_graph.py（can_move/path_exists 全量）+ test_movement.py（方向/隐藏/死路）",
    "2a1b 通道刷怪（initial_spawn/refresh/removal/天气加速）": "pytest:test_spawn.py + test_spawn_weather.py（时段/季节过滤、cap 补刷、天气权重加速）",
    "2a4a 时间引擎必测场景（刷新补刷/离线封顶/跨天判定，细化_5d L296）": "pytest:test_worldtime_changes.py（check_changes 变化检测/离线合并封顶 3 条）+ test_time_cycle_config.py（锚点公式/周期配置校验）+ test_time_query.py（跨天判定/状态查询）+ test_time_state_persist.py（懒计算状态持久化）",
    "2a4c 时间天气接口（weather_now/map_weather 对外）": "pytest:test_weather_pool.py::test_weather_now_uses_current_cycle_tick + test_time_query.py::test_weather_status_*（query 层接口）",
    "M43 时间锚点回归（零定时器/确定性/快照完整性）": "pytest:test_m43_regression.py（test_m43_zero_timer_repo_wide_scan / same_tick / restart_no_redraw / different_tick / snapshot_integrity_ai_combo_chase_field_level）+ test_time_regression.py（锚点前负差确定性；snapshot_integrity_placeholder 为 skip 占位已由 test_m43_regression 真实承载）",
}

# 子进程 pytest 目标文件：实际落盘 M3 相关测试（全绿要求）
PYTEST_FILES: list = [
    "tests/unit/test_maps_schema.py",        # 2a1a 地图 schema（8 字段/通道/隐藏门/spawn 行）
    "tests/unit/test_map_graph.py",          # 2a1a/2a1b 地图图（can_move/path_exists/双向一致）
    "tests/unit/test_movement.py",           # 2a1a/2a1b/2a1c 走通道 + 副本入口解析（route_* 承接 2a1c 多 TC）
    "tests/unit/test_chase.py",              # 2a2 换区触发/候选/追击态/pursue
    "tests/unit/test_dungeon_flow.py",       # 2a3 副本两型流程（enter/transition/explore_run/离开重置）
    "tests/unit/test_dungeon_boss.py",       # 2a3 BOSS 房/阶段三档/换区判定/追到续战
    "tests/unit/test_dungeon_subquest.py",   # 2a3 子任务五形式/可选性
    "tests/unit/test_dungeon_schema.py",     # 2a3 dungeon.json 两型 schema 校验
    "tests/unit/test_dungeon_persist.py",    # 2a3 死亡四档/会话持久化/虚弱
    "tests/unit/test_rest.py",               # 2a3/2a1c 副本内休息≠离开
    "tests/unit/test_snapshot_resume.py",    # 2a3/2a2 快照续玩/非战斗离开
    "tests/unit/test_chase_resume.py",       # 2a2 续战装配/离开重置
    "tests/unit/test_weather_pool.py",       # 2a4b 天气池/抽签/覆盖池
    "tests/unit/test_weather_conditions.py", # 2a4b 条件引擎/校验
    "tests/unit/test_weather_consumers.py",  # 2a4b 消费方（采集/战斗/事件/lore）
    "tests/unit/test_weather_validator.py",  # 2a4b 校验器（V5/V6/V7/W1-W6）
    "tests/unit/test_worldtime_changes.py",  # 补充 2a4a：check_changes 变化检测/离线封顶
    "tests/unit/test_time_cycle_config.py",  # 补充 2a4a：周期配置/锚点公式
    "tests/unit/test_time_query.py",         # 补充 2a4a/2a4c：时间状态查询
    "tests/unit/test_time_state_persist.py", # 补充 2a4a：时间状态持久化
    "tests/unit/test_time_regression.py",    # 补充 M43：时间锚点回归（4 实 1 skip 占位）
    "tests/unit/test_m43_regression.py",     # M43 三条回归（零定时器/确定性/快照完整性）
    "tests/unit/test_spawn.py",              # 补充 2a1b：通道刷怪
    "tests/unit/test_spawn_weather.py",      # 2a4b TC-10 + spawn 天气（补充）
    # ── m3_shared_contract §7 矩阵命名的归档位置（未落盘 → 黄提示跳过不判失败；实际覆盖见上拆分）──
    "tests/unit/test_map_dungeon_link.py",   # §7 列 2a1c 承载（未落盘；由 test_movement/test_dungeon_flow 承接）
    "tests/unit/test_dungeon.py",            # §7 列 2a3 承载（未落盘；由 test_dungeon_flow/boss/subquest 承接）
    "tests/unit/test_weather.py",            # §7 列 2a4b 承载（未落盘；由 test_weather_pool/conditions/consumers/validator 承接）
    "tests/unit/test_worldtime.py",          # §7 列 worldtime 承载（未落盘；由 test_worldtime_changes/test_time_* 承接）
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
# 核心断言 ①：关键模块可导入（M3 全部新增/改动模块）
# ==============================================================================
_MODULES: dict = {
    "worldtime": "qbot_rpg.engine.worldtime",
    "map_models": "qbot_rpg.content.map_models",
    "dungeon_models": "qbot_rpg.content.dungeon_models",
    "map_graph": "qbot_rpg.content.map_graph",
    "movement": "qbot_rpg.world.movement",
    "spawn": "qbot_rpg.world.spawn",
    "chase": "qbot_rpg.world.chase",
    "dungeon": "qbot_rpg.core.dungeon",
    "dungeon_boss": "qbot_rpg.core.dungeon_boss",
    "dungeon_subquest": "qbot_rpg.core.dungeon_subquest",
    "rest": "qbot_rpg.world.rest",
    "snapshot_resume": "qbot_rpg.world.snapshot_resume",
    "dungeon_persist": "qbot_rpg.world.dungeon_persist",
    "weather_conditions": "qbot_rpg.engine.weather_conditions",
    "weather_consumers": "qbot_rpg.engine.weather_consumers",
    "weather_validator": "qbot_rpg.content.weather_validator",
}


def t_module_imports() -> None:
    import importlib

    for label, dotted in _MODULES.items():
        importlib.import_module(dotted)
    # 关键类可实例化/引用（冒烟：不触发构造）
    from qbot_rpg.engine.worldtime import WorldTime  # noqa: F401
    from qbot_rpg.content.map_models import MapDef  # noqa: F401
    from qbot_rpg.content.dungeon_models import DungeonDef  # noqa: F401
    from qbot_rpg.core.dungeon import DungeonStateMachine  # noqa: F401
    from qbot_rpg.core.dungeon_boss import BossFlow  # noqa: F401
    from qbot_rpg.core.dungeon_subquest import ProgressTracker  # noqa: F401
    from qbot_rpg.world.spawn import SpawnManager  # noqa: F401


# ==============================================================================
# 核心断言 ②：M3 关键函数存在（map_weather/map_pool/check_changes/can_move/
# resolve_move/SpawnManager.refresh/DungeonStateMachine.enter/BossFlow.should_zone_change/
# chase_trigger.pursue 等）
# ==============================================================================
_KEY_FUNCS: list = [
    # (模块键, 类名或 None, 成员/函数名)
    ("worldtime", "WorldTime", "map_weather"),
    ("worldtime", "WorldTime", "map_pool"),
    ("worldtime", "WorldTime", "check_changes"),
    ("worldtime", "WorldTime", "cycle_tick"),
    ("worldtime", "WorldTime", "weather_now"),
    ("map_graph", None, "can_move"),
    ("movement", None, "resolve_move"),
    ("spawn", "SpawnManager", "refresh"),
    ("spawn", "SpawnManager", "initial_spawn"),
    ("dungeon", "DungeonStateMachine", "enter"),
    ("dungeon", "DungeonStateMachine", "transition"),
    ("dungeon_boss", "BossFlow", "should_zone_change"),
    ("dungeon_boss", "BossFlow", "enter_boss_room"),
    ("dungeon_boss", "BossFlow", "phase_for"),
    ("dungeon_boss", "BossFlow", "on_chase_continue"),
    ("chase", None, "chase_trigger"),
    ("chase", None, "pick_chase_target"),
    ("chase", None, "begin_chase"),
    ("chase", None, "pursue"),
    ("dungeon_subquest", "ProgressTracker", "record"),
    ("dungeon_subquest", "ProgressTracker", "is_complete"),
    ("rest", None, "rest_in_dungeon"),
    ("rest", None, "rest_is_not_exit"),
    ("snapshot_resume", None, "resume_from_snapshot"),
    ("snapshot_resume", None, "non_combat_exit"),
    ("dungeon_persist", None, "on_dungeon_death"),
    ("dungeon_persist", None, "save_dungeon_session"),
    ("dungeon_persist", None, "load_dungeon_session"),
    ("weather_conditions", None, "eval_condition"),
    ("weather_consumers", None, "apply_weather_mods"),
    ("weather_consumers", None, "combat_weather_mult"),
    ("weather_consumers", None, "lore_visible"),
    ("weather_validator", None, "validate_weather"),
]


def t_key_functions() -> None:
    import importlib

    for label, cls_name, member in _KEY_FUNCS:
        mod = importlib.import_module(_MODULES[label])
        obj = getattr(mod, cls_name) if cls_name else mod
        assert callable(getattr(obj, member)), f"{label}.{cls_name or ''}.{member} 缺失/不可调用"
    # M3 铁律 ① 零定时器：周期值由锚点公式得出（探针扫源码，M43 回归同口径）
    from qbot_rpg.engine.worldtime import ANCHOR, DEFAULT_POOL, WorldTime  # noqa: F401
    wt = WorldTime()
    assert callable(wt.map_weather) and callable(wt.map_pool) and callable(wt.check_changes)
    assert isinstance(ANCHOR, (int, float)) and DEFAULT_POOL, "锚点/默认池常量缺失"


# ==============================================================================
# 核心断言 ③：COVERAGE 自洽（81 TC 计数：2a1c 25 + 2a2 24 + 2a3 16 + 2a4b 16）
# ==============================================================================
_SECTION_COUNTS = {"2a1c": 25, "2a2": 24, "2a3": 16, "2a4b": 16}


def t_coverage_self_consistent() -> None:
    from collections import Counter

    assert len(COVERAGE) == 81, f"COVERAGE 应为 81 条 TC，实际 {len(COVERAGE)}"
    sec = Counter(k.split("-")[0] for k in COVERAGE)
    for name, want in _SECTION_COUNTS.items():
        assert sec.get(name, 0) == want, \
            f"{name} 段应为 {want} 条 TC，实际 {sec.get(name, 0)}"
    # 诚实化声明格式自洽：每条只允许 pytest: 承载或 DELAYED 注明理由
    for k, v in COVERAGE.items():
        assert v.startswith("pytest:") or v.startswith("DELAYED"), \
            f"{k} 承载格式非法（须 pytest: 或 DELAYED）：{v[:60]}"
    # 声明的 pytest 承载文件必须落盘（诚实化覆盖声明的可核验性）
    import re
    refs = set()
    for v in COVERAGE.values():
        if v.startswith("pytest:"):
            refs.update(re.findall(r"test_[A-Za-z0-9_]+\.py", v))
    missing_refs = sorted(r for r in refs if not (REPO / "tests" / "unit" / r).exists())
    assert not missing_refs, f"COVERAGE 声明引用了未落盘测试文件：{missing_refs}"
    # 承载/DELAYED 计数自洽
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    carried = len(COVERAGE) - len(delayed)
    assert carried + len(delayed) == 81
    print(f"    COVERAGE 核算：81 TC = {carried} 已承载 + {len(delayed)} DELAYED")
    print(f"    DELAYED（{len(delayed)}）：" + ", ".join(k.split(" ")[0] for k in delayed))


# ==============================================================================
# 汇总与子进程 pytest 门禁
# ==============================================================================
def main() -> int:
    print("== verify_m3 脚本核心断言（M3 地图里程碑）==")
    checks = [
        ("① 关键模块可导入（worldtime/map_models/dungeon_models/map_graph/movement/spawn/"
         "chase/dungeon/dungeon_boss/dungeon_subquest/rest/snapshot_resume/dungeon_persist/"
         "weather_conditions/weather_consumers/weather_validator）", t_module_imports),
        ("② M3 关键函数存在（map_weather/map_pool/check_changes/can_move/resolve_move/"
         "SpawnManager.refresh/DungeonStateMachine.enter/BossFlow.should_zone_change/"
         "chase_trigger.pursue 等 33 项）", t_key_functions),
        ("③ COVERAGE 自洽（81 TC：2a1c 25 + 2a2 24 + 2a3 16 + 2a4b 16）", t_coverage_self_consistent),
    ]
    for name, fn in checks:
        check(name, fn)

    print("\n== 子进程 pytest（M3 相关测试文件；文件缺失（异常）→ 黄提示跳过）==")
    existing = [f for f in PYTEST_FILES if (REPO / f).exists()]
    missing = [f for f in PYTEST_FILES if not (REPO / f).exists()]
    for f in missing:
        _yellow(f"{f} 缺失（契约命名归档未落盘）→ 跳过；对应 TC 承载已由拆分测试文件落盘生效")
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

    print("\n== 覆盖声明（m3_shared_contract §7：M3 地图 = 81 条 TC，诚实化逐条标注）==")
    for tc, carrier in COVERAGE.items():
        print(f"  {tc} → {carrier}")
    print("  ── 补充引擎覆盖（worldtime 必测场景 L296 + M43 回归；不计入 81 计数）──")
    for tc, carrier in SUPPLEMENT.items():
        print(f"  {tc} → {carrier}")
    delayed = [k for k, v in COVERAGE.items() if v.startswith("DELAYED")]
    carried = len(COVERAGE) - len(delayed)
    print(f"\n  DELAYED 项（{len(delayed)}/81）：{', '.join(k.split(' ')[0] for k in delayed)}")

    n_fail = len(_FAIL)
    print(f"\n结果：脚本断言 {len(_PASS)} 通过 / {n_fail} 失败；pytest {'✔' if pytest_ok else '✘'}"
          f"{'（缺失文件黄提示不判失败）' if missing else ''}")
    if n_fail or not pytest_ok:
        for name, err in _FAIL:
            print(f"  FAIL {name}: {err}")
        print("M3 门禁：verify_m3 未通过 ✘（失败回溯：m3_shared_contract §7 #TC-NN + 断言原文见上；D8 VG-20 统一「M<N> 门禁」输出）")
        return 1
    print(f"M3 门禁：verify_m3 全绿 ✔（81 TC 中 {carried} 已承载 + {len(delayed)} DELAYED；"
          f"补充引擎：worldtime 必测场景 L296 + M43 回归已纳入）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
