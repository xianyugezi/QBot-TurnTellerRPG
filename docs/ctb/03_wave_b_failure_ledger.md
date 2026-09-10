# CTB 重写 · Wave B 失败台账（Wave C 修复工单基准）

> 生成：2026-09-10 主 Agent · 命令 `.venv/bin/python -m pytest -p no:randomly`
> 全量基线：**120 failed, 6198 passed, 9 skipped**（Wave B 收尾态）
> 清零目标：**0 failed, 6318 passed, 9 skipped**

---

## 零、口径说明（为什么这 120 个失败是"预期内"）

`battle.py` 已按 D-2(b) 把三处旧时序入口改为 `NotImplementedError` 壳：

| 旧入口 | 现状 | 迁移目标 |
|---|---|---|
| `action_order()` | `NotImplementedError`（CTB 不再有整轮固定排序） | `CTBScheduler` 唯一顺序权威 |
| `enemy_act()` | `NotImplementedError`（NPC 由调度器自动推进） | `player_act` 内 `_resolve_ready_actor` |
| `end_turn()` | `NotImplementedError`（CTB 无回合边界） | `AFTER_ACTION` / `ACTOR_TURN_END` 事件位点 |

因此**所有按旧回合语义调用的测试必然失败**——它们失败在"调用了一个已被刻意删除的 API"，
而不是失败在逻辑错误。**禁止**为了让它们变绿而恢复 `enemy_act`/`end_turn`。

**唯一权威修复方向**：把这些测试的时序调用改写为 CTB 语义
（`engine.start(...)` → `engine.player_act(...)` → 读 `battle_state()["action_seq"]`）。

---

## 一、失败清单（按文件，降序）

| # | 文件 | 失败数 | 主要失败根因 | 修复批次 |
|---|---|---|---|---|
| 1 | `tests/unit/test_transform_battle_full.py` | 17 | `end_turn()` 壳 + `_tick_transform_state()` 位点迁移 | C-1 |
| 2 | `tests/unit/test_m13_battle_scenarios.py` | 11 | `enemy_act()` / `end_turn()` 壳（6a 路3C 场景） | C-2 |
| 3 | `tests/unit/test_season_battle_link.py` | 10 | `end_turn()` 壳（`_tick_season_boundary` 位点） | C-3 |
| 4 | `tests/unit/test_monster_ai_battle.py` | 9 | `enemy_act()` 壳（AI 单步 → 调度器自动） | C-2 |
| 5 | `tests/unit/test_transform_resource_link.py` | 8 | `end_turn()` 壳 + 形态资源结算 | C-1 |
| 6 | `tests/unit/test_reposition.py` | 7 | `end_turn()` 壳（`test_full_turn_advances_after_reposition`） | C-3 |
| 7 | `tests/unit/test_resource_battle_full.py` | 6 | `end_turn()` 壳（`round_end_tick` 资源轴） | C-3 |
| 8 | `tests/unit/test_position_rule.py` | 6 | 「行动槽」语义（`action_slot_consumed`）→ `action_seq` | C-4 |
| 9 | `tests/unit/test_battle_render_settlement.py` | 6 | `EnrichedTurnReport.phases` → `_phase_label`/`action_seq` | C-5 |
| 10 | `tests/unit/test_battle_render_player.py` | 6 | 同上（`phases` 字段访问） | C-5 |
| 11 | `tests/unit/test_battle_engine.py` | 6 | 旧引擎契约（`action_order`/`do_action` 直调） | C-4 |
| 12 | `tests/unit/test_transform_battle_wiring.py` | 4 | `end_turn()` 壳（`test_end_turn_decrements_remaining` 等） | C-1 |
| 13 | `tests/unit/test_resource_snapshot.py` | 3 | `end_turn()` 壳 + 快照往返 | C-3 |
| 14 | `tests/unit/test_m13_smoke.py` | 3 | `enemy_act()` 壳（6a 路3C 冒烟） | C-2 |
| 15 | `tests/unit/test_battle_render_enemy.py` | 3 | 敌方段渲染（`phases` 依赖） | C-5 |
| 16 | `tests/e2e/test_m13_fullchain_e2e.py` | 3 | e2e 全链路（回合三段） | C-6 |
| 17 | `tests/unit/test_sword_vault_dot_fix.py` | 2 | DOT tick 位点（`turn_end_tick`） | C-3 |
| 18 | `tests/unit/test_event_dispatcher_battle.py` | 2 | 事件分派位点 | C-6 |
| 19 | `tests/unit/test_counter_parry_dodge.py` | 2 | 反击/格挡/闪避窗口 = `action_seq` 窗口 | C-4 |
| 20 | `tests/unit/test_air_policy.py` | 2 | 浮空策略（"回合数"→ `action_seq`） | C-4 |
| 21 | `tests/unit/test_snapshot_resume.py` | 1 | `test_real_battle_engine_from_snapshot_factory` | C-7 |
| 22 | `tests/unit/test_resource_assembly.py` | 1 | `test_settle_clears_resource_state` | C-3 |
| 23 | `tests/unit/test_m2_review_fixes.py` | 1 | M2 复核残留 | C-7 |
| 24 | `tests/unit/test_battle_wiring.py` | 1 | 接线（`dispatch_round` 消费） | C-6 |
| — | **合计** | **120** | | |

---

## 二、修复批次划分（6 路并行，按耦合度聚簇）

| 批次 | 文件 | 失败数 | 依赖 |
|---|---|---|---|
| **C-1** 形态/变换 | `test_transform_battle_full` + `test_transform_battle_wiring` + `test_transform_resource_link` | 29 | C-3（tick 位点先冻结） |
| **C-2** 怪物 AI / M13 | `test_monster_ai_battle` + `test_m13_battle_scenarios` + `test_m13_smoke` | 23 | 无 |
| **C-3** 资源/季节/DOT | `test_season_battle_link` + `test_resource_battle_full` + `test_resource_snapshot` + `test_resource_assembly` + `test_sword_vault_dot_fix` + `test_reposition` | 29 | 无 |
| **C-4** 位姿/引擎契约 | `test_position_rule` + `test_battle_engine` + `test_counter_parry_dodge` + `test_air_policy` | 16 | 无 |
| **C-5** 渲染层 | `test_battle_render_settlement` + `test_battle_render_player` + `test_battle_render_enemy` | 15 | 无 |
| **C-6** 接线/E2E | `test_m13_fullchain_e2e` + `test_event_dispatcher_battle` + `test_battle_wiring` | 6 | C-2 |
| **C-7** 快照/复核残留 | `test_snapshot_resume` + `test_m2_review_fixes` | 2 | 无 |

**并行约束**：C-1 与 C-6 有依赖（C-1 依赖 C-3 的 tick 位点冻结；C-6 依赖 C-2 的 AI 步进语义），
其余 4 路完全独立。

---

## 三、修复铁律（对所有批次生效）

1. **禁止**恢复 `enemy_act` / `end_turn` / `action_order`——它们是刻意删除的壳。
2. **禁止**放宽断言到"能过就行"（如 `assert turn >= 0`）——必须表达 CTB 语义。
3. **禁止**修改 `qbot_rpg/` 业务代码来迁就测试；若确需改业务代码，先回报主 Agent 裁决。
4. 旧「回合数」参数一律映射到 `battle_state()["action_seq"]`（整数计数）或
   `battle_state()["battle_time"]`（浮点逻辑时间）；**不得**再用顶层 `turn` 做进度断言
   （它只是 `action_seq` 的兼容镜像）。
5. 每个改动文件必须**单元测试通过**后再提交。
6. 测试文件 emoji 禁令（D-01）与 M43 零定时器门禁（禁止 `time.sleep`/`threading`/`Timer`/
   `schedule`/`sched` **哪怕在注释里**）继续生效。

---

## 四、收口判据（Wave C 通过标准）

> **状态：全部达成（2026-09-10 收口）**

- [x] 全量 pytest：`0 failed` —— 实测 `6326 passed, 9 skipped, 0 xfailed`
- [x] G0 架构门禁：`ARCH-OK`（TC-01~04，251 文件）
- [x] M43 零定时器仓库扫描：通过（5 项）
- [x] `tests/ctb/` 全绿且**无 xfail/xpass**（含黑盒场景 1/2）
- [x] ruff / mypy：对比基线**无新增**（ruff 66→63；mypy 32→**0**）
- [x] 黑盒场景 1/2：`P→E→P→E→P` 与 `P→E→E→P`（recovery=200）均通过
- [x] `scripts/verify_ctb.py` 四门禁：`RESULT: PASS（4/4）`
