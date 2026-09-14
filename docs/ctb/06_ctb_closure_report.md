# CTB 重写 · 最终收口报告

> 交付日：2026-09-10
> 范围：`QBot-TurnTellerRPG` 战斗系统由「旧回合制」**全量重写**为 **CTB（Charge/Conditional Time Battle）**
> 依据：`ctb重做方案.md`（1582 行）+ `docs/ctb/01~05`（资产清单 / 裁决 / 失败台账 / 接线 / 迁移收口）
> 性质：**重写**（非渐进迁移）——用户在会话中明确「我比较希望重写」+「测试库会直接删档，不管旧战斗迁移」

---

## 一、最终验收（全绿）

| 门禁 | 命令 | 结果 |
|---|---|---|
| 全量回归 | `.venv/bin/python -m pytest tests/ -p no:randomly` | **`6326 passed, 9 skipped, 0 failed, 0 xfailed`** |
| 架构门禁 G0 | `.venv/bin/python scripts/check_architecture.py` | **`ARCH-OK`**（TC-01~04，扫描 251 文件） |
| M43 零定时器 | `tests/unit/test_m43_regression.py` | **5 项通过**（仓库级词边界扫描 + 白名单自证） |
| CTB 专项 | `tests/ctb/` | **65 项全绿、无 xfail**（含黑盒场景 1/2） |
| 冒烟 E2E | `scripts/e2e_m6_smoke.py` | **34 断言全绿**，重放摘要逐字一致 |
| CTB 门禁脚本 | `scripts/verify_ctb.py` | **`RESULT: PASS（4/4）`** |
| mypy | `.venv/bin/python -m mypy qbot_rpg` | **`Success: no issues found in 251 source files`**（基线 32 → **0**） |
| ruff | `.venv/bin/ruff check .` | **63**（基线 66；净减 3，仅余 production 既有 E501/F401/E741/E402 债务） |

**失败数轨迹**：`120 → 91 → 38 → 3 → 0`。

---

## 二、交付物

### 2.1 新增业务模块（4 文件 · 1776 行）

| 文件 | 行数 | 职责 | 分层约束 |
|---|---|---|---|
| `qbot_rpg/data/ctb.py` | 112 | **纯数据**：行动种类常量、恢复值表、CTB 默认设置、`ActionRecoveryTable` | 依赖集 = `set()`（**零依赖**，TC-03 硬约束） |
| `qbot_rpg/core/ctb_config.py` | 293 | **配置解析**：恢复值归一出入口（`resolve_action_recovery` 支持裸数值/字典/表）、设置解析、`_assert_no_value_drift()` 防漂移 | 仅依赖 `data` |
| `qbot_rpg/core/ctb_rules.py` | 514 | **规则层**：`ActionBatchReport`、事件常量、边界名校验等 | `core` 内部 |
| `qbot_rpg/core/ctb_scheduler.py` | 857 | **调度器**：行动条推进、ready 队列、暂停语义、代数票据失效、`npc_resolver` 注入 | `core` 内部 |

另外 `qbot_rpg/core/battle.py` 从 1131 增 / 487 删完成引擎侧 CTB 改造（净 +644 行）。

### 2.2 新增测试（6 文件 · 2084 行）

| 文件 | 行数 | 覆盖 |
|---|---|---|
| `tests/ctb/test_ctb_contract_interfaces.py` | 431 | 接口契约 |
| `tests/ctb/test_ctb_blackbox_sequences.py` | 267 | **黑盒验收**：`P→E→P→E→P` / `P→E→E→P` |
| `tests/ctb/test_ctb_contract_events.py` | 251 | 10 事件位点契约 |
| `tests/ctb/test_ctb_contract_seed.py` | 218 | 确定性种子 |
| `tests/unit/test_ctb_scheduler.py` | 571 | 调度器行为 |
| `tests/unit/test_ctb_render.py` | 399 | 数据/配置层渲染 + 依赖自由性静态扫描 |

### 2.3 文档（6 份 · `docs/ctb/`）

`01_asset_inventory.md`（486 行资产清单与分类）/ `02_wave_a_decisions.md`（裁决 1/2/3 + R-A~R-D）/
`03_wave_b_failure_ledger.md`（失败台账 + 6 铁律）/ `04_wave_b_integration.md`（接线）/
`05_wave_c_migration.md`（测试迁移收口）/ `06_ctb_closure_report.md`（本文件）。

---

## 三、核心设计落地

### 3.1 CTB 公式与双计数

```
next_ready = current_time + recovery(action) × speed_reference / max(effective_speed, min_speed) + action_delay
```

- **双计数**：`battle_time`（float 逻辑时间，权威）+ `action_seq`（int 已结算行动数，权威）
- **顶层 `turn`**：**仅兼容镜像**（= `action_seq`），**不参与任何数值计算**（R1–R20 已全部改由双计数承载）

### 3.2 三条裁决（`02_wave_a_decisions.md`）

1. **recovery = 总恢复值（覆盖语义，非加算）**。文档中「重技能 recovery=150」为示例笔误——
   连动阈值需 `>166.67`，150 达不到；验收改用 **200**（→ `300.0 > 266.667` → `P→E→E→P` ✓）。
2. **R-6 被拒行动 = 零时间成本、立即重试**（不推进行动条）。
3. **同刻连动为刻意设计**（`SIDE_PRIORITY = {"player": 0, "enemy": 1}`）。

### 3.3 「可暂停输入式 CTB」

- NPC 连锁**自动推进**；在**玩家 Ready** 处暂停等待输入
- 多个 NPC 行动合并为一份 `ActionBatchReport`，经渲染层合并为**一条消息**（铁律 2）
- 玩家提交行动 → 单次 `player_act` 内完成「玩家行动 + NPC 连锁」，恰 1 条消息

### 3.4 架构分层（TC-03 依赖矩阵）

- `data/ctb.py` 依赖集 = `set()` —— **零 `qbot_rpg` import**（有静态扫描测试守住）
- 逻辑从 `data` 拆出至 `core/ctb_config.py`，修复原 TC-03 违规

---

## 四、收口阶段修复的真实缺陷（业务代码 · 报备后执行）

按铁律 3「不得改业务代码迁就测试」，以下 6 处为**真实引擎缺陷**（非测试迁就）：

| # | 缺陷 | 影响 | 修复 |
|---|---|---|---|
| 1 | `_tick_transform_state(actor=None)` actor 作用域 | 敌方每次行动也扣减**玩家**形态剩余/冷却 | 加 `if actor is not None and actor != "player": return` |
| 2 | `_after_actor_action` 的 `_to_state` 非幂等 | `skip`/`guard` 路径触发非法迁移 `act→act` | 加 `and self._state != STATE_ACT` 幂等守卫 |
| 3 | **NPC 行动从未真实执行**（A1 级） | `_ai_action_dict()` **零调用点** → NPC 只发事件不结算（无伤害、无 `action_record`） | 新增 `CTBScheduler.npc_resolver` 回调 + `BattleEngine._resolve_npc_action()`（MonsterAI decide → `do_action` → 回传 recovery） |
| 4 | `tick="turn_end"` DOT 未接线 | 回合尾 DOT 永不结算 | `_after_actor_action` 内按序补 `tick_turn_end` → 双侧 `_death_check_side(..., "turn_end_dot")` → `_sync_scheduler_deaths()` |
| 5 | R10 姿态窗口用 `==` 判等 | 写入发生在 `action_seq` 推进**之前** → 端到端防反姿态**恒过期** | 记 `_stance_owner_seq`，消费侧改 `>=`（「自写入起、至持有者再次行动止」） |
| 6 | `_resolve_ready_actor` 暂停分支无条件 `break` | 跳过 ready 时刻**早于**玩家的 NPC（实测 t=250 / t=2000 两拍被漏） | 改由 `_next_player_ready()` / `_has_earlier_npc_ready()` 判定 |

另修复 **玩家可见文案 CTB 化**（`01_asset_inventory.md` B2/B3 + R19 明确登记项）：
`回合数`→`行动数`、`第 N 回合`→`第 N 行动`、`本回合受到伤害减半`→`本次行动受到伤害减半`、
`下回合发动`→`下次行动发动`、连段鞭尸备注去回合叙述。连带更新 12 项逐字断言测试。

---

## 五、xfail 清零

迁移中期曾出现 **4 项 `strict=True` xfail**，全部锁定业务代码缺口。
收口阶段**逐一修复业务代码并摘除 xfail 标记**——不留静默吸收、不留长期豁免：

- `test_battle_engine.py::test_p002/p004`（turn_end DOT）→ **已修复摘除**
- `test_sword_vault_dot_fix.py::test_dot_part_break_per_tick`（同缺口）→ **已修复摘除**
- `test_counter_parry_dodge.py` 端到端防反（R10 窗口）→ **已修复摘除**

当前 `0 xfailed`，`--runxfail` 不再是回归前置条件。

---

## 六、假绿修复（重要）

`scripts/e2e_m6_smoke.py` 的④结算步在 CTB 化前是**假绿**：

```python
for _ in range(50):
    if eng.finished: break
    eng.do_action("player", ...)
    if not eng.finished:
        eng.enemy_act()      # ← NotImplementedError 壳
        eng.end_turn()       # ← NotImplementedError 壳
```

`enemy_act()` 抛 `NotImplementedError` → 被循环所在函数的裸 `except` 吞掉 →
**循环首轮即退出**，其后 3 条快照 round-trip 断言**从未执行**（总数恰好卡在下限之上，未被察觉）。

**已 CTB 化**：三段式 → `player_act` 单调用；启动断言 `turn=1` → `action_seq≥1` + `battle_time>0`；
快照往返比对 `action_seq`。实测现在真实执行：1 次玩家行动 → `action_seq=2`、`enemy hp=0`、
`flag=win`、`records=2`、恢复后 HP 一致。

---

## 七、遗留与非目标

### 7.1 已归零的 xfail

无（4 → 0）。

### 7.2 保留的历史命名（语义已对齐，仅名不换）

- `assert_turn_no_timeout()`（`world/battle_boundary.py:757`）—— 空实现语义锚点，
  docstring 已注明 CTB 口径（无回合，玩家在 `actor_ready` 边界静置等待）。
- `_battle_turns()`（`message_format/battle_render.py:1318`）—— 取数链 `turns|turn` 保留；
  CTB 下 `turn` 即 `action_seq` 镜像，数值正确。

以上二者属**刻意保留**（改动收益 < 回归风险），非遗留缺陷。

### 7.3 非目标（用户明示排除）

- 旧战斗会话迁移 / `from_snapshot` 兼容 —— **测试库将重建并删档**，无需 drain。
  快照仍写 **V2**（`schema_version=2`），旧版本（`<2`）读入时硬拦 `incompatible_snapshot`。

### 7.4 待办（非阻塞）

- 三个 GitHub token 的吊销 + 已验证补丁推送（当前网络受限）。
- `qa_ctb_baseline_ruff.txt` / `qa_ctb_baseline_mypy.txt` 已按收口后状态重采。

---

## 八、变更规模

```
47 files changed, 4014 insertions(+), 1480 deletions(-)   # 已跟踪文件
+ docs/ctb/（6 份文档）、tests/ctb/（6 文件）、4 个新业务模块、2 份质量基线
```

**结论：CTB 重写达成全部收口判据——全量回归 0 失败、四道门禁全绿、mypy 清零、
xfail 归零、黑盒场景通过、假绿修复。可交付。**
