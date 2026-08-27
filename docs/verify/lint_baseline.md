# 存量 lint/type 基线豁免清单（M6 批7·路B · D7 LNT-05/06）

> 首次扫描日期：2026-08-28
> 工具版本：ruff 0.16.5 / mypy 2.3.1（requirements.txt dev 段锁版本）
> 依据：docs/细化/细化_M6_质量门禁.md（D7）§二 LNT-05/06——存量问题一次性豁免、**清单外新增必拦**；
> 轮换规则 = 豁免项随对应文件重构消除（不得新增豁免）；本清单由 verify_m6（D8）断言存在且非空。

## 一、口径与承载

- **ruff 存量**：由 pyproject.toml `[tool.ruff.lint.per-file-ignores]` 承载（文件级，181 文件），
  规则 = E/F 组（line-length=100 已是护栏，**无全局 ignore E501**，D7 LNT-01）。
- **mypy 存量**：按 `# type: ignore[码]` **逐处标注**于源码行内（283 处，D7 LNT-06 承载方式）；
  行号即清单坐标，本表按 文件×错误码 聚合。mypy 配置 = non-strict 定档（D7 决策记录 D7-D1），
  `warn_unused_ignores` / `warn_redundant_casts` 显式启用。
- **新增代码零豁免**：清单外规则码、或未入清单文件中的任何违规 → 阶段0 快速门失败（exit≠0）。
- **技术备案（偏离 D7 处，仅实现必需）**：`mypy .` 需 `explicit_package_bases + namespace_packages`
  （tests/ 无 `__init__.py` 链，缺此二项 mypy 报 "Source file found twice" 无法运行）。

## 二、ruff 存量清单（1582 处 / 181 文件）

| 文件 | 规则码（计数） | 首次发现 |
|---|---|---|
| qbot_rpg/commands/basic_commands.py | E501×17, F401×1 | 2026-08-28 |
| qbot_rpg/commands/battle_commands.py | E501×2 | 2026-08-28 |
| qbot_rpg/commands/checkin_commands.py | E501×19 | 2026-08-28 |
| qbot_rpg/commands/explore_commands.py | E501×2, F401×1 | 2026-08-28 |
| qbot_rpg/commands/gm_commands.py | E501×1, F822×2 | 2026-08-28 |
| qbot_rpg/commands/processing.py | E501×1 | 2026-08-28 |
| qbot_rpg/commands/quest_commands.py | E501×3 | 2026-08-28 |
| qbot_rpg/commands/register_commands.py | E501×1 | 2026-08-28 |
| qbot_rpg/commands/router.py | E501×9 | 2026-08-28 |
| qbot_rpg/commands/sender.py | E501×1 | 2026-08-28 |
| qbot_rpg/commands/shop_commands.py | E501×3 | 2026-08-28 |
| qbot_rpg/commands/shop_tx.py | E501×5 | 2026-08-28 |
| qbot_rpg/commands/status_commands.py | E501×2 | 2026-08-28 |
| qbot_rpg/content/checkin_models.py | E501×45 | 2026-08-28 |
| qbot_rpg/content/dungeon_models.py | E501×31 | 2026-08-28 |
| qbot_rpg/content/field_meta.py | E501×27, F401×2 | 2026-08-28 |
| qbot_rpg/content/hot_reload.py | E402×2, E501×8, F401×2 | 2026-08-28 |
| qbot_rpg/content/loader.py | E402×3, E501×2 | 2026-08-28 |
| qbot_rpg/content/map_graph.py | E741×2, F401×1 | 2026-08-28 |
| qbot_rpg/content/map_models.py | E501×10, F401×1 | 2026-08-28 |
| qbot_rpg/content/models.py | E501×10, F401×14 | 2026-08-28 |
| qbot_rpg/content/npc_models.py | E501×18, F401×1 | 2026-08-28 |
| qbot_rpg/content/quest_models.py | E501×10, F401×1 | 2026-08-28 |
| qbot_rpg/content/registry.py | E501×3, F401×2 | 2026-08-28 |
| qbot_rpg/content/shop_models.py | E501×27, F401×1 | 2026-08-28 |
| qbot_rpg/content/time_validator.py | E501×6 | 2026-08-28 |
| qbot_rpg/content/validator.py | E501×23, E741×1, F401×1 | 2026-08-28 |
| qbot_rpg/content/weather_validator.py | E501×2, E741×1 | 2026-08-28 |
| qbot_rpg/core/__init__.py | E501×1 | 2026-08-28 |
| qbot_rpg/core/battle.py | E501×21, F401×4 | 2026-08-28 |
| qbot_rpg/core/checkin.py | E501×14, F841×1 | 2026-08-28 |
| qbot_rpg/core/combo.py | E501×17, F841×2 | 2026-08-28 |
| qbot_rpg/core/damage.py | E501×2, F401×3 | 2026-08-28 |
| qbot_rpg/core/dayroll.py | E501×6 | 2026-08-28 |
| qbot_rpg/core/dialog.py | E501×18 | 2026-08-28 |
| qbot_rpg/core/dungeon.py | E501×8 | 2026-08-28 |
| qbot_rpg/core/dungeon_boss.py | E501×1 | 2026-08-28 |
| qbot_rpg/core/effects.py | E501×63, F841×2 | 2026-08-28 |
| qbot_rpg/core/equipment.py | E501×6, F841×1 | 2026-08-28 |
| qbot_rpg/core/formula_engine.py | E501×10, F401×1 | 2026-08-28 |
| qbot_rpg/core/inventory.py | E501×1, F401×1 | 2026-08-28 |
| qbot_rpg/core/levelup.py | E501×2 | 2026-08-28 |
| qbot_rpg/core/marks.py | E501×1, F401×1 | 2026-08-28 |
| qbot_rpg/core/message_format/battle_render.py | E501×3 | 2026-08-28 |
| qbot_rpg/core/message_format/list_render.py | E501×3 | 2026-08-28 |
| qbot_rpg/core/message_format/panel_render.py | E501×3 | 2026-08-28 |
| qbot_rpg/core/message_format/prefix_render.py | E501×1, F401×1 | 2026-08-28 |
| qbot_rpg/core/monster_ai.py | E501×5 | 2026-08-28 |
| qbot_rpg/core/monster_chains.py | F401×1 | 2026-08-28 |
| qbot_rpg/core/monster_intent.py | F401×1 | 2026-08-28 |
| qbot_rpg/core/npc.py | E501×39 | 2026-08-28 |
| qbot_rpg/core/player_attributes.py | E501×3, F401×1 | 2026-08-28 |
| qbot_rpg/core/quest.py | E501×6 | 2026-08-28 |
| qbot_rpg/core/reward.py | E501×11 | 2026-08-28 |
| qbot_rpg/core/shop.py | E501×30, F401×1 | 2026-08-28 |
| qbot_rpg/data/api_response.py | F401×1 | 2026-08-28 |
| qbot_rpg/data/item.py | E501×2 | 2026-08-28 |
| qbot_rpg/data/player.py | E501×3 | 2026-08-28 |
| qbot_rpg/data/status.py | E501×1 | 2026-08-28 |
| qbot_rpg/data/world_state.py | E501×1 | 2026-08-28 |
| qbot_rpg/engine/condition_engine.py | E501×4, F401×1 | 2026-08-28 |
| qbot_rpg/engine/weather_conditions.py | E501×1 | 2026-08-28 |
| qbot_rpg/engine/weather_consumers.py | F401×1 | 2026-08-28 |
| qbot_rpg/engine/worldtime.py | E501×17 | 2026-08-28 |
| qbot_rpg/storage/connection.py | E402×1, E501×1, F401×1 | 2026-08-28 |
| qbot_rpg/storage/migrations.py | F401×4 | 2026-08-28 |
| qbot_rpg/storage/pending.py | E501×2 | 2026-08-28 |
| qbot_rpg/storage/repository.py | E501×1, F541×2 | 2026-08-28 |
| qbot_rpg/world/battle_boundary.py | E501×13, F401×1 | 2026-08-28 |
| qbot_rpg/world/dungeon_persist.py | E501×3 | 2026-08-28 |
| qbot_rpg/world/movement.py | E501×5, F401×1 | 2026-08-28 |
| qbot_rpg/world/rest.py | E501×1 | 2026-08-28 |
| qbot_rpg/world/spawn.py | E501×8 | 2026-08-28 |
| qbot_rpg/world/spawn_weather.py | F401×1 | 2026-08-28 |
| scripts/_gen_templates_full.py | E401×1, E501×2 | 2026-08-28 |
| scripts/_gen_templates_part1.py | E402×2, E501×1 | 2026-08-28 |
| scripts/_gen_templates_part2.py | E402×1 | 2026-08-28 |
| scripts/_gen_templates_part3.py | E501×1 | 2026-08-28 |
| scripts/check_architecture.py | E501×9 | 2026-08-28 |
| scripts/e2e_m3_smoke.py | E402×9, E501×6 | 2026-08-28 |
| scripts/e2e_m4_smoke.py | E402×11, E501×16, F401×5 | 2026-08-28 |
| scripts/e2e_m6_smoke.py | E501×2, F401×3 | 2026-08-28 |
| scripts/run_all_tests.py | E501×7 | 2026-08-28 |
| scripts/verify/verify_m0.py | E501×4 | 2026-08-28 |
| scripts/verify/verify_m1.py | E501×9, E702×5, F401×2 | 2026-08-28 |
| scripts/verify/verify_m2.py | E501×36 | 2026-08-28 |
| scripts/verify/verify_m3.py | E501×98 | 2026-08-28 |
| scripts/verify/verify_m4.py | E501×90, F811×1 | 2026-08-28 |
| scripts/verify/verify_m5.py | E501×73 | 2026-08-28 |
| tests/conftest.py | E501×4 | 2026-08-28 |
| tests/contract/test_g0_architecture.py | F401×2 | 2026-08-28 |
| tests/contract/test_message_format.py | F401×1 | 2026-08-28 |
| tests/fault/fault_inject_doublepay.py | E501×3, F401×1 | 2026-08-28 |
| tests/fault/fault_inject_formula.py | E501×4 | 2026-08-28 |
| tests/fault/fault_inject_reload.py | E501×4 | 2026-08-28 |
| tests/unit/test_basic_commands.py | E501×8 | 2026-08-28 |
| tests/unit/test_battle_boundary.py | E501×3 | 2026-08-28 |
| tests/unit/test_battle_engine.py | E501×2, E702×10, F841×2 | 2026-08-28 |
| tests/unit/test_battle_render_settlement.py | E501×4, F401×1, F841×1 | 2026-08-28 |
| tests/unit/test_battle_render_skill.py | E501×1 | 2026-08-28 |
| tests/unit/test_battle_render_startend.py | E501×1 | 2026-08-28 |
| tests/unit/test_battle_snapshot_generation.py | E501×2 | 2026-08-28 |
| tests/unit/test_battle_wiring.py | E501×3, F841×1 | 2026-08-28 |
| tests/unit/test_chase.py | E501×8 | 2026-08-28 |
| tests/unit/test_chase_resume.py | E501×3 | 2026-08-28 |
| tests/unit/test_checkin.py | E501×5, E741×4, F841×3 | 2026-08-28 |
| tests/unit/test_checkin_commands.py | E501×4 | 2026-08-28 |
| tests/unit/test_checkin_models.py | E501×11, F401×1 | 2026-08-28 |
| tests/unit/test_combo.py | E501×3, E702×3, F401×1 | 2026-08-28 |
| tests/unit/test_condition_engine.py | E501×36, F401×2 | 2026-08-28 |
| tests/unit/test_content.py | E501×8, F401×1 | 2026-08-28 |
| tests/unit/test_coredata_regress.py | F401×1 | 2026-08-28 |
| tests/unit/test_damage_gaps.py | E501×5 | 2026-08-28 |
| tests/unit/test_data.py | F401×2 | 2026-08-28 |
| tests/unit/test_dayroll.py | E501×9, F401×1 | 2026-08-28 |
| tests/unit/test_dialog.py | E501×2, F401×2 | 2026-08-28 |
| tests/unit/test_dsh_regress.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_dungeon_boss.py | E501×11 | 2026-08-28 |
| tests/unit/test_dungeon_flow.py | E501×4 | 2026-08-28 |
| tests/unit/test_dungeon_persist.py | E501×7, F401×3 | 2026-08-28 |
| tests/unit/test_dungeon_schema.py | E501×10 | 2026-08-28 |
| tests/unit/test_dungeon_subquest.py | E501×2 | 2026-08-28 |
| tests/unit/test_e2e_m3_smoke.py | E501×3 | 2026-08-28 |
| tests/unit/test_effects_gaps.py | E501×10, F401×1 | 2026-08-28 |
| tests/unit/test_effects_runtime.py | E501×14 | 2026-08-28 |
| tests/unit/test_emoji_discipline.py | E501×1, E741×1 | 2026-08-28 |
| tests/unit/test_enemies_schema.py | E501×8, E741×1 | 2026-08-28 |
| tests/unit/test_equip_adapter.py | F401×1 | 2026-08-28 |
| tests/unit/test_equipment.py | E501×3 | 2026-08-28 |
| tests/unit/test_explore_filter.py | E501×1, F401×2 | 2026-08-28 |
| tests/unit/test_formula_property.py | F401×12 | 2026-08-28 |
| tests/unit/test_gm_commands.py | F401×5 | 2026-08-28 |
| tests/unit/test_hot_reload_wiring.py | F401×1 | 2026-08-28 |
| tests/unit/test_idem_processing.py | E501×2 | 2026-08-28 |
| tests/unit/test_inventory.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_levelup.py | E501×1, F841×1 | 2026-08-28 |
| tests/unit/test_list_render.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_m1_review_fixes.py | E501×4, F401×1, F841×2 | 2026-08-28 |
| tests/unit/test_m2_review_fixes.py | E501×7, E702×6 | 2026-08-28 |
| tests/unit/test_map_graph.py | E501×5 | 2026-08-28 |
| tests/unit/test_maps_schema.py | E501×5 | 2026-08-28 |
| tests/unit/test_marks.py | E501×1, E702×3, F401×1 | 2026-08-28 |
| tests/unit/test_message_prefix_wiring.py | E501×7, F401×1 | 2026-08-28 |
| tests/unit/test_monster_ai.py | E501×5 | 2026-08-28 |
| tests/unit/test_monster_ai_battle.py | E501×7, E731×1 | 2026-08-28 |
| tests/unit/test_monster_conditions_chains.py | E501×2 | 2026-08-28 |
| tests/unit/test_monster_intent_phases.py | E501×1 | 2026-08-28 |
| tests/unit/test_movement.py | E501×3, F401×1 | 2026-08-28 |
| tests/unit/test_npc.py | E501×10, F401×1 | 2026-08-28 |
| tests/unit/test_npc_models.py | E501×7, F401×1, F601×6 | 2026-08-28 |
| tests/unit/test_pack_fixtures_matrix.py | E501×6 | 2026-08-28 |
| tests/unit/test_parsers.py | F401×4 | 2026-08-28 |
| tests/unit/test_pending_queue.py | E501×3 | 2026-08-28 |
| tests/unit/test_per_player_queue.py | E501×2 | 2026-08-28 |
| tests/unit/test_quest.py | E501×5, F401×2 | 2026-08-28 |
| tests/unit/test_quest_commands.py | E501×4 | 2026-08-28 |
| tests/unit/test_quest_models.py | E501×3, F401×1 | 2026-08-28 |
| tests/unit/test_register_commands.py | E501×1, F401×1, F841×1 | 2026-08-28 |
| tests/unit/test_reload_translator.py | E501×1 | 2026-08-28 |
| tests/unit/test_reward.py | E501×1 | 2026-08-28 |
| tests/unit/test_router.py | E501×4, F401×2 | 2026-08-28 |
| tests/unit/test_sender.py | E501×2 | 2026-08-28 |
| tests/unit/test_shop.py | E501×3, F401×4 | 2026-08-28 |
| tests/unit/test_shop_commands.py | E501×10 | 2026-08-28 |
| tests/unit/test_shop_double_pay.py | E501×6 | 2026-08-28 |
| tests/unit/test_shop_models.py | E501×10, F401×1 | 2026-08-28 |
| tests/unit/test_shortcut_commands.py | E501×3, F401×1 | 2026-08-28 |
| tests/unit/test_snapshot_resume.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_snapshot_resume_rebind.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_spawn.py | F401×1 | 2026-08-28 |
| tests/unit/test_spawn_weather.py | F401×2 | 2026-08-28 |
| tests/unit/test_status_commands.py | E501×3 | 2026-08-28 |
| tests/unit/test_storage.py | E501×1, F401×2 | 2026-08-28 |
| tests/unit/test_time_cycle_config.py | E501×3 | 2026-08-28 |
| tests/unit/test_time_query.py | E501×2, F401×2 | 2026-08-28 |
| tests/unit/test_time_state_persist.py | E501×1 | 2026-08-28 |
| tests/unit/test_weather_conditions.py | E501×1, F401×1 | 2026-08-28 |
| tests/unit/test_weather_consumers.py | E501×6 | 2026-08-28 |
| tests/unit/test_weather_pool.py | E501×2, F401×1 | 2026-08-28 |
| tests/unit/test_weather_validator.py | E501×1 | 2026-08-28 |
| tests/unit/test_worldtime_changes.py | E501×2 | 2026-08-28 |

## 三、mypy 存量清单（283 处逐处标注 / 58 文件）

| 文件 | 错误码（计数） | 首次发现 |
|---|---|---|
| qbot_rpg/commands/battle_commands.py | union-attr×3 | 2026-08-28 |
| qbot_rpg/commands/parsers.py | assignment×1 | 2026-08-28 |
| qbot_rpg/commands/prefix_wiring.py | index×1 | 2026-08-28 |
| qbot_rpg/content/checkin_models.py | redundant-cast×1 | 2026-08-28 |
| qbot_rpg/content/validator.py | arg-type×5, assignment×1 | 2026-08-28 |
| qbot_rpg/content/weather_validator.py | attr-defined×5 | 2026-08-28 |
| qbot_rpg/core/battle.py | no-redef×2 | 2026-08-28 |
| qbot_rpg/core/combo.py | arg-type×3 | 2026-08-28 |
| qbot_rpg/core/dialog.py | no-redef×1 | 2026-08-28 |
| qbot_rpg/core/effects.py | assignment×1, attr-defined×4 | 2026-08-28 |
| qbot_rpg/core/equipment.py | no-redef×1 | 2026-08-28 |
| qbot_rpg/core/formula_engine.py | arg-type×5, assignment×4, attr-defined×2, call-overload×1, index×2, operator×12 | 2026-08-28 |
| qbot_rpg/core/inventory.py | no-redef×1 | 2026-08-28 |
| qbot_rpg/core/monster_ai.py | arg-type×1, assignment×1 | 2026-08-28 |
| qbot_rpg/core/monster_intent.py | arg-type×1 | 2026-08-28 |
| qbot_rpg/core/npc.py | arg-type×1, union-attr×2 | 2026-08-28 |
| qbot_rpg/core/shop.py | arg-type×5, operator×5 | 2026-08-28 |
| qbot_rpg/storage/connection.py | index×1, return-value×3 | 2026-08-28 |
| qbot_rpg/storage/repository.py | arg-type×1, redundant-cast×3 | 2026-08-28 |
| qbot_rpg/world/battle_boundary.py | attr-defined×2 | 2026-08-28 |
| qbot_rpg/world/chase_resume.py | arg-type×3 | 2026-08-28 |
| qbot_rpg/world/movement.py | redundant-cast×1 | 2026-08-28 |
| scripts/_gen_templates_part1.py | var-annotated×1 | 2026-08-28 |
| scripts/_gen_templates_part2.py | var-annotated×1 | 2026-08-28 |
| scripts/_gen_templates_part3.py | var-annotated×1 | 2026-08-28 |
| scripts/e2e_m3_smoke.py | union-attr×2 | 2026-08-28 |
| scripts/e2e_m4_smoke.py | call-overload×3 | 2026-08-28 |
| scripts/e2e_m6_smoke.py | assignment×4, union-attr×1 | 2026-08-28 |
| scripts/verify/verify_m0.py | union-attr×2 | 2026-08-28 |
| tests/contract/test_e2e_smoke.py | import-not-found×1 | 2026-08-28 |
| tests/contract/test_g0_architecture.py | import-not-found×2 | 2026-08-28 |
| tests/fault/fault_inject_crash.py | import-not-found×1 | 2026-08-28 |
| tests/fault/fault_inject_save.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_api_response.py | var-annotated×2 | 2026-08-28 |
| tests/unit/test_battle_engine.py | arg-type×2, assignment×1 | 2026-08-28 |
| tests/unit/test_battle_render_enemy.py | arg-type×2 | 2026-08-28 |
| tests/unit/test_battle_render_settlement.py | arg-type×1 | 2026-08-28 |
| tests/unit/test_battle_snapshot_generation.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_chase.py | call-overload×1, operator×4 | 2026-08-28 |
| tests/unit/test_checkin.py | func-returns-value×1 | 2026-08-28 |
| tests/unit/test_checkin_models.py | assignment×1 | 2026-08-28 |
| tests/unit/test_content.py | arg-type×2, attr-defined×1, union-attr×1 | 2026-08-28 |
| tests/unit/test_data.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_dungeon_flow.py | arg-type×1 | 2026-08-28 |
| tests/unit/test_dungeon_persist.py | var-annotated×1 | 2026-08-28 |
| tests/unit/test_enemies_schema.py | var-annotated×1 | 2026-08-28 |
| tests/unit/test_explore_filter.py | call-overload×1 | 2026-08-28 |
| tests/unit/test_idem_processing.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_npc_models.py | attr-defined×29 | 2026-08-28 |
| tests/unit/test_pending_queue.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_per_player_queue.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_quest.py | func-returns-value×1 | 2026-08-28 |
| tests/unit/test_quest_models.py | attr-defined×63 | 2026-08-28 |
| tests/unit/test_reward.py | func-returns-value×1 | 2026-08-28 |
| tests/unit/test_shop_models.py | attr-defined×51 | 2026-08-28 |
| tests/unit/test_spawn_weather.py | attr-defined×1, index×1 | 2026-08-28 |
| tests/unit/test_storage.py | import-not-found×1 | 2026-08-28 |
| tests/unit/test_time_cycle_config.py | var-annotated×1 | 2026-08-28 |

## 四、统计

- ruff：**1582 处 / 181 文件** — E501×1345、F401×141、E402×29、E702×27、F841×17、E741×10、F601×6、F822×2、F541×2、E401×1、F811×1、E731×1。
- mypy：**283 处 / 58 文件** — attr-defined×158、arg-type×33、operator×21、assignment×14、union-attr×11、import-not-found×11、var-annotated×8、call-overload×6、index×5、no-redef×5、redundant-cast×5、func-returns-value×3、return-value×3。
- **顺手修正（非豁免）**：2 处非法 `# noqa` 指令（qbot_rpg/storage/repository.py:25、qbot_rpg/core/dayroll.py:275）；1 处 `# type:dummy` 注释误触发 mypy type-comment 解析（qbot_rpg/content/validator.py:604，改述不改变语义）；39 处 unused `# type: ignore` 清理（warn_unused_ignores 暴露，删除后无行为变化）；1 处反斜杠续行无法挂注释（qbot_rpg/core/shop.py:938 括号化三元式，语义不变）。

## 五、门禁现状（2026-08-28 豁免后实测）

- `ruff check .` → All checks passed！
- `mypy .` → Success: no issues found in 231 source files
- 阶段0 静态前置挂 run_all_tests.py（D7 LNT-04），`--skip-lint` 为逃生口（5d §3.2 L133）。
- **技术备案（2026-08-28 批7A 审查 P2-4）**：mypy 未设 `python_version`——默认以运行解释器（.venv 3.11）为分析目标，与 ruff `target-version="py39"` 名义语法下限不一致；存量代码未验证 3.9 语法兼容（大量 3.10+ 标注可能大量新增报错 → 门禁突变风险），本批登记为**已知口径差距**，不追平 python_version（避免门禁突变）；追平时机 = 覆盖率/依赖门禁稳定后由后续里程碑决策（D7 LNT-02 同口径）。
