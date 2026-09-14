# Wave C · 旧回合语义测试迁移收口（Agent 4 · 接线集成）

> 交付日：2026-09-10
> 依据：`docs/ctb/03_wave_b_failure_ledger.md`（120 项台账 + 6 条铁律）、
> `docs/ctb/02_wave_a_decisions.md`（裁决 1/2/3 + R-A~R-D）、
> `docs/ctb/04_wave_b_integration.md`（Wave B 接线交付）。
> 范围：把 Wave B 台账登记的、因「调用被刻意删除的旧 API」而失败的测试，
> 按 CTB 语义重写为等价口径——**不改业务代码迁就测试**（铁律 3）。

---

## 一、总览

| 项目 | 迁移前 | 迁移后 |
|---|---|---|
| 全量 pytest | `91 failed, 6226 passed, 9 skipped, 2 xfailed` | **`0 failed, 6326 passed, 9 skipped, 0 xfailed`** |
| G0 架构门禁 | `ARCH-OK` | `ARCH-OK`（TC-01~04 全绿） |
| M43 零定时器 | 通过 | 通过（5 项） |
| `tests/ctb/` | 65 全绿 | 全绿、无 xfail |
| mypy（qbot_rpg） | 32 errors / 7 files | **0 errors / 251 files** |
| ruff（全仓） | 66 | **63**（-3：我改动文件的未用导入） |
| 黑盒场景 1/2 | 通过 | 通过 |

**净效果**：`91 failed → 0 failed`；期间出现的 4 个严格 xfail 已**全部消除**
（对应业务代码缺陷在 Wave C 收口阶段修复，见 §三.4/5）。

---

## 二、逐批次修复记录

### C-1 形态 / 变换（29 项）
- `test_transform_battle_full.py`（17 失败 → 全绿 18 passed）：`_full_turn` 三段式
  （`do_action` + `enemy_act` + `end_turn`）改写为 `player_act`；断言 `out.ok` →
  `out.outcomes[0].ok`；`remaining == 3` → `== 2`（触发当次行动 tick）。
- `test_transform_resource_link.py`（8 失败 → 全绿 15 passed）：同款 `_full_turn` 重写
  + 6 处三段式 / 11 处单行 `do_action` → `player_act`；删 3 处残留 `enemy_act()/end_turn()`。
- `test_transform_battle_wiring.py`（4 失败 → 全绿 6 passed）：无需改动；引擎侧
  `_tick_transform_state` actor 作用域修复后自动转绿。

### C-2 怪物 AI / M13（23 项，本次主体）
- `test_monster_ai_battle.py`（7 失败 → 全绿 11 passed + 4 skipped）：
  - 新增 CTB 辅助：`player_turn(eng)` → `player_act`；`enemy_ready(eng)` 循环推进至
    怪物 ready 拍；`enemy_action(eng, report)` 从 `report.outcomes` 取怪物 outcome。
  - **关键节奏发现**：玩家 spd 50 / 怪 spd 40，怪每**两次**玩家行动 ready 一次
    （旧测试假设 1:1）→ 用 `enemy_ready` 显式推进解决。
  - **TC-17 打断语义**：`player_act` 返回时 `exec_state` 已被合法覆盖为 `in_chain`
    （同一次调用内玩家行动结束后调度器推进到下一个 ready，怪物 ready 拍走 L6 随机
    流程**开新套**）；`combo_broken` 一次性标记亦被怪物决策即时消费 → 改以**持久证据**
    断言（`chain_queue==[]` + `chain_id is None` + `chain_cooldowns['molten']==1`
    + `monster_chain_broken` 事件带 `chain_id`），并新增 `_interrupt_enemy_ai()`
    **单元语义**用例锁定「套完结」的原子落点（清队列 / 回 idle / 链进冷却 / 置标记）。

### C-4 位姿 / 引擎契约（16 项）
- `test_position_rule.py`（6 失败 → 全绿 28 passed）：新增 `enemy_act_ctb()` helper
  = **`eng.do_action("enemy", action_dict)`**（旧 `enemy_act(action_dict=...)` 的 CTB
  等价：单次行动结算入口、显式指定内容、不触碰玩家位姿）。
- `test_air_policy.py`（8 失败 → 全绿 24 passed）：统一 `_set_air()`——CTB 真实语义 =
  `height=air` **且持有空中姿态状态**（R16：`_settle_air_landing()` 判「有 air 状态」
  为仍在空中，否则行动收尾即落地）；怪侧行动改 `do_action("enemy", ...)`。
- `test_counter_parry_dodge.py`（2 失败 → 全绿 3 passed）：姿态窗口 = **R10 口径**
  「写入 action_seq == 当前 action_seq」（**本次行动窗口**）；CTB 下玩家与怪物属不同
  action_seq，故在同一窗口内置 `counter_stance` + 直驱 `do_action("enemy", ...)` 验证。
- `test_position_parts.py`（3 失败 → 全绿 23 passed）：新增 `_player_segment_records()`——
  `do_action("player")` 尾段会自动推进 NPC 一拍并写 `action_record`，旧
  `action_record[-2:]` 会错取「玩家次段 + 怪物行动」；改按 `actor=="player"` 过滤。

### C-5 渲染层（15 项）
- `test_battle_render_settlement.py` + `test_battle_render_player.py` +
  `test_battle_render_enemy.py`：复查时已全绿（先行迁移完成），零改动。

### C-6 接线 / E2E（6 项）
- `test_m13_fullchain_e2e.py`（3 失败 → 全绿 9 passed）：`_full_turn` 三段式 → `player_act`。
- `test_battle_wiring.py`（2 失败 → 全绿 14 passed）：
  - `test_round_one_message_attack_merged`：断言 `1 条 → 2 条`（NPC 连锁段 + 玩家
    行动段）。**依据**：Wave B 时引擎 NPC 行动通道未补齐、`dispatch_batch` 恒静默退化
    （`04_wave_b_integration.md` L122/L173-175 登记的遗留事实）；引擎侧现已补齐
    （`_npc_outcomes` → `report.outcomes`，见 §三），`dispatch_batch` 契约自动生效。
  - `test_prefix_disabled_no_prefix`：2 条消息各自首行均无前缀（定位玩家行动段断言）。

### C-7 快照 / 复核残留（2 项）
- `test_snapshot_resume.py` + `test_m2_review_fixes.py`：复查时已全绿，零改动。

---

## 三、引擎侧修复（业务代码 · 报备后执行）

按铁律 3，以下 3 处为**真实引擎缺陷**（非测试迁就），已修复并验证：

1. **`_tick_transform_state(actor=None)` actor 作用域**：形态/冷却属玩家（transform 段
   挂玩家侧），原实现被 `_after_actor_action(actor)` 以**任意** actor 调用 → 敌方每次
   行动也扣减玩家形态剩余/冷却。修复：加 `if actor is not None and actor != "player":
   return`。修复后序列正确（`act1 rem=2 cd=5 → act2 rem=1 → act3 form=None cd=4 → …`）。
2. **`_after_actor_action` 的 `_to_state` 幂等**：`skip`/`guard` 路径**未进入 `res`**，
   本就处于 `act`，原代码触发 `非法状态迁移 act→act`。修复：加 `and self._state !=
   STATE_ACT` 幂等守卫（CTB 无回合边界，`act→act` 为合法自迁）。
3. **NPC outcome 并入报告**（收口 `04_wave_b_integration.md` §五.1 遗留风险 1）：
   新增 `_npc_outcomes` 缓冲 + `player_act` 汇总 → 渲染层得以产出「怪物行动行」。
   实测 `report.outcomes = [('player','normal',87), ('enemy','skill',60)]`。

> 上述 3 处已使 `04_wave_b_integration.md` 的遗留风险 1 转为**已收口**（同步更新该文档）。

---

## 四、xfail 清零（Wave C 收口阶段完成）

迁移中期曾出现 4 项 `strict=True` xfail，全部锁定「业务代码真实缺口」。收口阶段
**逐一修复业务代码并摘除 xfail 标记**（不留静默吸收，不留长期豁免）：

| 用例 | 缺口 | 收口处置 |
|---|---|---|
| `test_battle_engine.py::test_p002/p004` | `tick="turn_end"` 的 DOT 在 CTB 下未接线：`_after_actor_action`（ACTOR_TURN_END）只调 `tick_after_action`，**未调** `tick_turn_end` | 在 `_after_actor_action` 内补 `tick_turn_end` + 双侧死亡复核 + `_sync_scheduler_deaths()`；xfail 摘除 |
| `test_sword_vault_dot_fix.py::test_dot_part_break_per_tick` | 同上缺口 | 同上；xfail 摘除 |
| `test_counter_parry_dodge.py`（1 项） | R10 姿态窗口用 `== action_seq` 判等，但写入发生在推进**之前** → 经 `player_act` 端到端防反的姿态恒过期 | 窗口口径改为「**自写入起、至持有者再次行动止**」：`_after_actor_action` 内记 `_stance_owner_seq = action_seq`，消费侧 `_player_stance` 判 `当前 seq >= _stance_owner_seq`；xfail 摘除，端到端防反用例转正 |

> 4 项 xfail 归零，`--runxfail` 不再是回归前置条件。

---

## 四之二、收口阶段补充的引擎侧修复

除 §三 的 3 处外，收口阶段另有 3 组修复（同属「报备后执行」）：

4. **DOT 回合尾接线**（对应上表前两项）：`_after_actor_action` 现按序执行
   `tick_after_action` → `tick_turn_end` → 双侧 `_death_check_side(..., "turn_end_dot")`
   → `_sync_scheduler_deaths()`，使「回合尾 DOT 击杀」在 CTB 时间轴上真实落账。

5. **R10 姿态窗口**（对应上表第三项）+ **ready 拍暂停语义**：
   - `_stance_owner_seq` 记录姿态写入拍，消费侧改为 `>=` 判定；
   - `_resolve_ready_actor` 的暂停分支原先在 `self._ctb.paused` 时**无条件 break**，
     会跳过 ready 时刻**早于**玩家的 NPC（实测 t=250 / t=2000 两拍被漏）→ 改由
     `_next_player_ready()` / `_has_earlier_npc_ready()` 判定：仅当队头 is_player、
     或队头 ready 晚于玩家下次 ready 时才 break。

6. **玩家可见文案 CTB 化**（对应 `01_asset_inventory.md` B2/B3 + R19）：
   CTB 无「回合」，渲染层文案与取数同步改造（**此项为资产清单明确登记项，非自由发挥**）：

   | 模板 / 取数 | 改前 | 改后 |
   |---|---|---|
   | `battle_end_summary`（BREP-24） | `战斗结束：{结果}｜回合数 N｜…` | `…｜行动数 N｜…`（取数 `turns\|turn`→CTB 下权威为 action_seq，见 `_battle_turns` docstring） |
   | `battle_player_defend`（BREP-05 / B3） | `本回合受到伤害减半` | `本次行动受到伤害减半` |
   | `battle_enemy_intent`（BREP-12） | `下回合发动「X」` | `下次行动发动「X」` |
   | `battle_result_round` | `第 {turn} 回合结算` | `第 {turn} 行动结算` |
   | `battle_target_head`（/查看目标） | `（第 {round} 回合）` | `（第 {round} 行动）`，取数改读 `action_seq` |
   | `status_target`（/状态【目标】行） | `（第 {round} 回合）` | `（第 {round} 行动）`，取数优先 `action_seq` 回落 `turn` |
   | `battle_combo_remark_waste`（BREP-22） | `目标已倒下，下一回合退出战场` | `目标已倒下，该段连式为无效消耗`（去回合叙述） |

   > 连带更新 12 项逐字断言测试（`test_battle_render_enemy/player/settlement/startend`、
   > `test_battle_wiring`、`test_target_commands`、`test_status_commands`）。
   > **注**：`回合数` 的取数本身仍走 `_battle_turns` 的 `turns|turn` 兼容链——
   > CTB 下 `turn` 即 `action_seq` 镜像，故数值正确；仅文案与槽位名对齐 CTB。

---

## 五、收口判据核对（Wave C）

- [x] 全量 pytest：`0 failed`（6326 passed / 9 skipped / 0 xfailed）
- [x] G0 架构门禁：`ARCH-OK`（TC-01~04）— `.venv/bin/python scripts/check_architecture.py`
- [x] M43 零定时器仓库扫描：通过（`test_m43_regression.py` 5 项）
- [x] `tests/ctb/`：全绿且无 xfail
- [x] mypy（251 files）：`0 errors`（基线 32 → 0，战斗链路改动全部类型干净）
- [x] ruff：63（基线 66；本批次改动净减 3，仅余 production 既有债务 E501/F401/E741/E402）
- [x] 冒烟：`scripts/e2e_m6_smoke.py` 34 断言全绿（`turn=1` 旧回合断言已 CTB 化为
      `action_seq≥1` + `battle_time>0`）
- [x] 黑盒场景 1/2：通过

---

## 六、变更文件清单（Wave C 全量）

**测试文件**
`tests/unit/test_transform_battle_full.py`、`test_transform_resource_link.py`、
`test_monster_ai_battle.py`、`test_position_rule.py`、`test_air_policy.py`、
`test_counter_parry_dodge.py`、`test_position_parts.py`、`test_battle_wiring.py`、
`test_sword_vault_dot_fix.py`、`test_battle_engine.py`、
`tests/e2e/test_m13_fullchain_e2e.py`

**业务文件**
- `qbot_rpg/core/battle.py`（5 处：`_tick_transform_state` actor 作用域 / `_after_actor_action`
  幂等 + `tick_turn_end` + `_stance_owner_seq` / `_npc_outcomes` / `_resolve_ready_actor`
  暂停语义 / `_resolve_npc_action` NPC 行动真实执行）
- `qbot_rpg/core/ctb_scheduler.py`（`npc_resolver` 注入 + 死亡停用重排）
- `qbot_rpg/core/battle_reward.py`、`qbot_rpg/core/npc.py`、`qbot_rpg/commands/shop_commands.py`
  （mypy 清零的类型收敛，行为等价）
- `qbot_rpg/commands/battle_commands.py`（`sent` 重复定义 / Mapping 收窄）

**脚本**
`scripts/e2e_m6_smoke.py`（`turn=1` → CTB 口径断言）

**质量基线**
`qa_ctb_baseline_ruff.txt`、`qa_ctb_baseline_mypy.txt`（收口后重采）

**文档**
`docs/ctb/04_wave_b_integration.md`（遗留风险 1 转「已收口」）、
`docs/ctb/05_wave_c_migration.md`（本文件）
