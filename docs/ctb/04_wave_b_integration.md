# 04 · Wave B 接线集成（Agent 4 · Integration）交付报告

> 归属：Agent 4 · 接线集成（Integration），CTB 重写 Wave B（方案文档 P0-4，标注「最容易低估的一块」）。
> 依据：Wave A 定稿（调度器/规则/渲染/快照 V2）+ `docs/ctb/02_wave_a_decisions.md`（R-6/R-A/R-B 裁决）
> + `docs/ctb/03_wave_b_failure_ledger.md`。
> 范围：把已完成的 CTB 引擎接到**指令层**与**世界层**——4 个任务文件。
> 结论：**四项任务全部完成**；`tests/ctb/` 65 项全绿、ARCH-OK、M43 零定时器门禁通过，
> 我负责文件的 ruff 全绿；无新增基线错误。

---

## 一、改动文件清单（含行号）

### 任务 1 · `qbot_rpg/commands/battle_commands.py`（1374 → 1623 行）

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| L1–L80 模块 docstring | 改写 | 增「归属：Agent 4 · 接线集成（Integration），CTB 重写 Wave B（P0-4）」+ CTB 变更说明 |
| L85 | 新增 import | `logging`；L108 `_LOGGER = logging.getLogger(__name__)` |
| L97–L104 | 调整 import | 新增 `render_battle_action_batch`（`render_battle_action` 引入后未用，已移除避免 F401） |
| L118–L122 `__all__` | 新增 `"dispatch_batch"` | 注释改「CTB 派发（NPC 连锁批量 + 玩家单行动薄壳）」 |
| L219–L220 `EnrichedTurnReport` | **新增 2 字段** | `action_seq: int = 0` / `battle_time: float = 0.0`，**置于 `status_changes` 之后**（位置参数兼容） |
| L250 / L320 `from_report` / `enrich_round_report` | 透传双计数 | `action_seq=int(getattr(report,...))` / `battle_time=float(...)`，缺失走默认值 |
| L529 `_entry_progress` | **新增** | `action_record` 条目进度键读取：`action_seq` 优先、`turn` 次要回退 |
| L546 `_build_segments(snap, action_seq)` | **重写（R-A 修复）** | 按 `_entry_progress(entry) != action_seq` 过滤（旧按 `entry["turn"]`）；**参数名改 `action_seq`** |
| L591 `_latest_player_action_seq` | 新增 | 取 `action_record` 中最后一条玩家行动的 `action_seq`（过滤键兜底） |
| L611 `_enemy_action_name_of` | 新增 | 取最近一条 enemy 行动展示名（技能名注入） |
| L769 `send_round` | docstring 更新 | 语义：CTB 单行动渲染；"round" 为历史命名 |
| L778 `send_action_batch(report, *, to=None)` | **新增** | 委托 `render_battle_action_batch`（多 NPC 行动合并 1 条） |
| L825 `_send_item_round` | docstring 更新 | 语义更新为 CTB；道具行 + 连锁合并 1 条 |
| L850 `_skill_name_of` | 新增 | 技能展示名解析（玩家 skill 行动注入） |
| L884 `dispatch_batch(...)` | **新增（职责 1）** | 处理 report 内**非玩家** outcome → `render_battle_action_batch`；**无 NPC 行动则 `return []` 不发空消息**；异常 `_LOGGER.exception` + `return []` |
| L935 `dispatch_round(...)` | **重写为薄兼容外壳（职责 2）** | 保留 `__all__` 导出 + 既有测试引用；内部只做玩家单行动渲染（flee/item/其他）+ 终局收尾；整体 try-except 兜底 |
| L1019 `_dispatch_battle_end(...)` | **新增** | 集中击杀接线（`bump_event` / `log_first_kill` / `mark_seen` / `check_milestones`）+ `pipeline.send_end(...)`（`turn=int(report.action_seq)`） |
| L1245 `_run_battle_action` | **改为合并模型** | 先 `dispatch_batch`（NPC 连锁，无则静默）→ 后 `dispatch_round`（玩家行动/终局），`sent` 列表合并 → 普通攻击恰 **1 条** |

### 任务 2 · `qbot_rpg/commands/battle_launch_commands.py`（500 → 504 行）

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| L388 `eng.start(...)` 上方 | **补 CTB 路径注释** | 明确「开战 = 初始化行动条；**无需 rule_version 分派**；CTB 唯一实现；玩家行动经 `player_act` 单入口」 |
| L326 `BattleEngine.from_snapshot` | 核查（不改） | 正当用途（残留战斗会话终局探测），非 `enemy_act` 残留 |
| 全文件 | 核查结论 | **无** `enemy_act` / `end_turn` / `action_order` 残留（grep 零命中） |

### 任务 3 · `qbot_rpg/world/snapshot_resume.py`（533 → 609 行）+ `session.py` 核查

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| L39–L43 模块 docstring | 新增补白 0 | 声明 CTB V2 门禁 + `action_seq` 优先读取 |
| L105 `_SNAPSHOT_REQUIRED_KEYS` | 保持 `("ai_state","combo_state","turn")` | `turn` 保留（V2 写 `turn=action_seq` 兼容镜像，R-A）→ 校验不断裂 |
| L116 `_CTB_MIN_SCHEMA_VERSION: int = 2` | **新增常量** | CTB 最低 schema 版本（硬门禁阈值） |
| L157 `_snapshot_turn` | **重写** | 读取顺序：`snapshot_at.action_seq` → 顶层 `action_seq` → 顶层 `turn` → `snapshot_at.turn`（V2 权威优先，旧形态兜底） |
| L186 `_snapshot_schema_version` | **新增** | 读 `schema_version`（缺失/畸形 → 1） |
| L366–L371 docstring | 更新 Returns | 新增 `reason="incompatible_snapshot"` / `detail` / `schema_version` |
| L415 `resume_from_snapshot` V2 门禁 | **新增** | `schema_version < 2` → 早退 `resumed=False`、`reason="incompatible_snapshot"`、`detail="旧回合制快照（schema_version=1）已随 CTB 重写废弃，需 schema_version>=2（用户已删档，不提供迁移）"`，**不调用工厂** |
| L423 `base` dict | 新增 `schema_version` | 所有返回分支统一透出 |
| `qbot_rpg/world/session.py` | 核查结论 | 纯会话 CRUD；`turn` 仅经 `_bs_field` 兜底读取（缺失安全），**无 round 假设**，无需改动 |

### 任务 4 · `qbot_rpg/world/battle_boundary.py`（884 → 886 行）

| 位置 | 改动 | 说明 |
| --- | --- | --- |
| L757 `assert_turn_no_timeout()` | **docstring 重写** | 函数体仍是空实现（声明语义）；文案对齐 CTB：无「回合」，玩家在 `actor_ready` 边界暂停（`CTBScheduler.paused`），NPC 连锁仅在玩家提交行动后由调度器一次性走完，**不依赖任何时钟**；函数名保留历史命名 |
| 全文件 | 核查结论 | **无** `end_turn` / `enemy_act` / `action_order` 残留；`assert_turn_no_timeout` 空实现天然契合 CTB（零定时器） |

### 配套测试（仅修正由本次语义变更直接导致的不一致，未越界改其它批次）

| 文件 | 改动 |
| --- | --- |
| `tests/unit/test_battle_wiring.py` | `test_round_one_message_attack_merged`：旧「怪物反击合并」断言 → CTB「单次操作 1 条 + 玩家行动行 + 提示行」；`test_combo_segments_injection_renders_seg_lines`：`_build_segments(snap, turn=2)` → `action_seq=2` + 夹具补 `action_seq` 键 |
| `tests/unit/test_snapshot_resume.py` | `_snapshot()` 夹具升为 V2（`schema_version=2` / `snapshot_at.action_seq` / 顶层 `action_seq`）；`test_turn_from_snapshot_at_fallback` 改测 action_seq 优先级；新增 `test_legacy_v1_snapshot_rejected` 验证门禁 |
| `tests/unit/test_snapshot_resume_rebind.py` | `_snap_dict()` 夹具补 `schema_version=2` / `action_seq`（同模块 V2 门禁） |

---

## 二、「旧语义 → CTB 语义」逐处对照

| # | 位置 | 旧语义（round loop） | CTB 语义 |
| --- | --- | --- | --- |
| 1 | `_build_segments` 过滤键 | `entry["turn"] != turn`（回合号匹配） | `_entry_progress(entry) != action_seq`（**action_seq 优先**，`turn` 回退）；`turn` 已退化为镜像，旧写法一旦镜像键移除即静默失配 |
| 2 | `dispatch_round` 职责 | 整轮派发（玩家 + 怪物反击合并 1 条） | **薄兼容外壳**：玩家单行动 + 终局收尾；"round" 仅历史命名 |
| 3 | `dispatch_batch`（新） | 无此概念 | NPC 连锁行动批量渲染 1 条；**无 NPC 行动 → 返回 `[]` 不发空消息** |
| 4 | `_run_battle_action` 调用序 | `sent = dispatch_round(...)`（单次调用） | `sent = dispatch_batch(...) + dispatch_round(...)`（先批量、后玩家，合并 ≤1-2 条） |
| 5 | `EnrichedTurnReport.turn` | 回合数（唯一进度） | `action_seq` / `battle_time` 双计数为权威；`turn` = `action_seq` 兼容镜像 |
| 6 | `BattlePipeline.send_round` | 整轮渲染 | CTB 单行动渲染；新增 `send_action_batch` 承接批量 |
| 7 | `_dispatch_battle_end` 的 `turn` | `report.turn`（回合数） | `int(report.action_seq)`（已结算行动计数） |
| 8 | `_snapshot_turn` 读取序 | 顶层 `turn` 优先 | `snapshot_at.action_seq` → 顶层 `action_seq` → `turn` 兜底 |
| 9 | `resume_from_snapshot` 兼容性 | 接受任意快照 | **V2 硬门禁**：`schema_version < 2` 拒绝（`incompatible_snapshot`），不兼容不迁移 |
| 10 | `assert_turn_no_timeout` 语义 | 「玩家回合无超时」 | 「玩家 `actor_ready` 边界暂停等待无超时」（无回合概念） |
| 11 | 开战路径 | 需 rule_version 分派 | CTB 唯一实现，**无需分派**；玩家行动经 `player_act` 单入口 |

---

## 三、`action_record` 实际字段核查结论（R-A 实证）

**读源码**：`qbot_rpg/core/battle.py::_record_action`（L869 附近）写入每条 entry 的键为：

```
seq / action_seq / battle_time / turn（= action_seq 镜像）/ phase /
actor / action / name / target / rating / damage / ts
```

**实测探针**（`.venv/bin/python`，`BattleEngine().start(P, E, seed)` → `player_act("normal")` → `battle_state()`）：

```
# 玩家 spd 50 > 敌 spd 40（首拍玩家 ready）
action_record len: 1
  rec: {'seq': 1, 'action_seq': 1, 'turn': 1, 'actor': 'player', 'action': 'normal', 'battle_time': 200.0}

# 玩家 spd 10 < 敌 spd 200（玩家慢，敌连走 20 拍）
before act, record len: 0
after act, record len: 1
  rec: {'seq': 1, 'action_seq': 21, 'turn': 21, 'actor': 'player', 'action': 'normal', 'battle_time': 1000.0}
```

**结论**：`action_record` 确实每条都写 `action_seq`（且 `turn` 与其同值，为镜像）——**R-A 修复成立**。玩家慢时 `action_seq` 跳号（1 → 21），证明按**最终** `report.turn` 过滤会与本次玩家行动条目失配；按 `action_seq` 匹配才正确。

### ⚠️ 关键发现（遗留风险，见第五节）

实测**NPC 连锁不在 `report.outcomes` 中**：`player_act` 返回的 `outcomes` 恒只含玩家自身一条（`actor="player"`），无论敌我速度。即使注入 `MonsterAI`，敌方也**不产出 `ActionOutcome`、不掉玩家血**——`_resolve_ready_actor` → `_auto_resolve_npc` 只派发事件位点，引擎侧 NPC 行动内容通道未在此 build 打通。
另：`CTBScheduler.current_batch` 的 `ActionBatchReport` **跨 `player_act` 累积且从不 drain**，条目仅含 `{actor_id, side, event, time, action_seq}`（无伤害/HP），不可作渲染数据源。
→ 故 `dispatch_batch` 在 **Wave B build** 中**恒静默退化**（返回 `[]`），但**契约仍正确**（"无 NPC 行动 → 不发空消息"），待引擎侧 NPC 行动通道补齐后自动生效，无需再改接线层。

> **Wave C 更新（2026-09-10）**：引擎侧 NPC 行动内容通道已补齐（见 §五.1 收口记录），
> `dispatch_batch` **已自动生效**——一次 `/攻击` 现产出 2 条（NPC 连锁段 + 玩家行动段）。

---

## 四、验收命令真实输出

```
$ .venv/bin/python -m pytest tests/ctb/ -q
.................................................................        [100%]
65 passed in 0.10s                                    # 65 项全绿、无 xfail

$ .venv/bin/python -m pytest tests/unit/test_battle_wiring.py tests/unit/test_snapshot_resume.py -q
1 failed, 33 passed in 0.24s
# 唯一失败：test_real_battle_engine_from_snapshot_factory
#   → 调 eng.enemy_act() + eng.end_turn()（CTB 刻意删除的壳，抛 NotImplementedError）
#   → 属 C-7 批次（旧回合语义测试，另一路 Agent 负责迁移），非本次接线缺陷

$ .venv/bin/python scripts/check_architecture.py
ARCH-OK  TC-01/TC-02/TC-03/TC-04 全部通过（细化_3a 分层契约满足）

$ .venv/bin/ruff check qbot_rpg/commands/battle_commands.py qbot_rpg/world/
All checks passed!
```

**M43 零定时器门禁**（词边界正则 `time\.sleep|\bthreading\b|\bTimer\b|\bschedule\b|\bsched\b`）：

```
$ grep -nE "time\.sleep|\bthreading\b|\bTimer\b|\bschedule\b|\bsched\b" \
    qbot_rpg/commands/battle_commands.py qbot_rpg/commands/battle_launch_commands.py \
    qbot_rpg/world/snapshot_resume.py qbot_rpg/world/battle_boundary.py qbot_rpg/world/session.py
（无输出，exit=1）
$ .venv/bin/python -m pytest tests/unit/test_m43_regression.py -q
.....                                                                     [100%]
```

**全仓回归**（对照修改前基线 `107 failed, 6210 passed`，其余差异来自并行 Agent 的测试迁移）：

```
$ .venv/bin/python -m pytest tests/ -p no:cacheprovider
72 failed, 6245 passed, 9 skipped, 2 xfailed, 1 warning in 42.42s
```

**G0 架构门禁 TC-01~04**：ARCH-OK（本报告所有改动均未引入新的跨层边；`commands → core/world` 为矩阵允许方向）。
**ruff 基线对比**：我文件零错误；`battle_launch_commands.py` / `job_commands.py` 的 8 个既有基线错误（E501/F401）**未新增**（不属本次范围）。

---

## 五、遗留风险与未决项

1. **【已收口 · 2026-09-10 Wave C】** NPC 连锁行动不产出 `ActionOutcome`（引擎侧缺口）
   实测：`player_act` 后 `report.outcomes` 恒只含玩家一条；NPC 行动不结算伤害（玩家 hp 不变）、不落 `action_record`、不进 `outcomes`。
   影响：`dispatch_batch` 恒静默；战斗实机为「玩家单方面输出、怪不反击」。
   归属：**Agent 1/2（core/battle.py 的 NPC 行动内容通道）**，非接线层。
   接线层已按契约就绪，引擎补齐后 `dispatch_batch` 自动生效（**无需再改**）。

   **收口记录（Agent 4 · Wave C）**：引擎侧已补齐 NPC 行动内容通道
   （`_resolve_npc_action` → `do_action` → `_npc_outcomes` 缓冲 → `player_act` 汇总进
   `TurnReport.outcomes`）。实测 `report.outcomes = [('player','normal',87),
   ('enemy','skill',60)]`，怪物行动既结算伤害也落 `action_record`。
   → `dispatch_batch` **契约自动生效**（正如上文预告「无需再改接线层」）：一次
   `/攻击` 现产出 **2 条**（NPC 连锁段 1 条 + 玩家行动段 1 条），仍在「单次操作
   ≤1-2 条」军规内。`test_battle_wiring.py` 断言已同步（1 条 → 2 条）。

2. **【中】`CTBScheduler.ActionBatchReport` 跨调用累积、从不 drain**
   `current_batch` 在连续 `player_act` 间持续累积（实测第二次 act 后含 41 条），且条目无伤害数据。若后续要用它做战斗日志，需引擎在 `player_act` 出口调 `take_batch()` 消费清空；当前不消费 → 内存单调增长（长战斗）。
   归属：**Agent 1/2（引擎消费点）**。

3. **【中】`battle_target_head` 仍显示「第 N 回合」**
   `qbot_rpg/core/templates/battle_tpl.py:24` = `"【目标】{name}（第 {round} 回合）"`；`cmd_battle_target`（`battle_commands.py:1507`）取 `state["turn"]`（= `action_seq` 镜像）填入 → 展示为「第 N 回合」。
   数据本身正确（就是 action_seq），仅**文案称"回合"**与 CTB 不符。改模板会波及 `tests/unit/test_status_commands.py` 4 处断言（非我批次），故**未改**，登记为待办：统一 CTB 文案时同步改模板 + 该测试。

4. **【低】`test_battle_wiring.py::test_round_one_message_mock_sender_call_count` 依赖 `dispatch_round` 薄壳**
   该测试直接调 `dispatch_round` 断言 `send.call_count == 1`。薄壳保留故当前通过；若未来彻底删除 `dispatch_round`，需迁移此测试（已登记）。

5. **【低】`_build_segments` 参数名变更的调用方**
   全仓仅 `battle_commands.py` 内部与 `test_battle_wiring.py` 调用；后者已同步。无外部调用方。

6. **未决：V2 门禁对「非战斗类」快照的影响**
   `resume_from_snapshot` 现硬拒 `schema_version < 2`。若世界层其它入口复用该函数读取**非 CTB** 快照（实测仅战斗续玩路径调用），需评估；当前 grep 未见其它调用方。

---

## 六、硬约束自检

| 约束 | 状态 |
| --- | --- |
| ① M43 零定时器门禁（含注释/docstring，禁用 `sched` 作局部名） | ✅ 5 文件零命中；`test_m43_regression.py` 5 项通过 |
| ② G0 架构门禁 TC-01~04（data 零依赖 / 五层零 nonebot / commands 才可 nonebot） | ✅ ARCH-OK；未新增跨层边 |
| ③ 代码规范（模块 docstring 归属/依据/职责/硬约束、`:param:`/`:return:`、`logging.getLogger`、try-except 兜底不向上抛） | ✅ 新增/改动函数均满足；`dispatch_batch` / `dispatch_round` / `_dispatch_battle_end` 均有 try-except + `_LOGGER.exception` |
| ④ 禁止恢复 `enemy_act` / `end_turn` / `action_order` | ✅ 未触碰；`battle_launch_commands.py` 核查零残留 |
| ⑤ 禁止改动 `ctb_rules.py` / `ctb_scheduler.py` / `ctb_config.py` / `data/ctb.py` / `core/battle.py` 既有 CTB 语义 | ✅ 上述 5 文件**只读核查，零改动** |
| 铁律：单次用户操作 ≤1-2 条消息 | ✅ 实测普通攻击 1 条、击杀 2 条（当轮 1 + 结束 1） |
