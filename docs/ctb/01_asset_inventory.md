# 战斗资产三分类清点表（CTB 重写 · 事实基础）

> **文档编号**：`docs/ctb/01_asset_inventory.md`
> **产出 Agent**：Agent 1 · 时序考古（Archaeologist）
> **仓库基线**：`9ef3ce2`（tag `pre-ctb-rewrite`）
> **主要档案**：`qbot_rpg/core/battle.py`（3734 行，`BattleEngine` 共 **107 个方法**）
> **硬约束**：本文档**不含任何业务代码改动**；所有行号以 `9ef3ce2` 为准。
> **下游消费者**：Agent 3（引擎重写）——本文档是唯一资产事实来源。

---

## 0. 阅读指引与分类口径

### 0.1 三分类定义

| 分类 | 判定标准 | 处置 |
|---|---|---|
| **【平移】** | 与「回合」概念**无关**的业务逻辑/纯函数/效果通道接线。CTB 下语义不变。 | 原样搬进新引擎，零改动或近零改动 |
| **【重写】** | 含**回合/时序假设**（回合计数器、固定出手序、回合边界、回合内 tick），CTB 下必须重新实现。 | 语义等价重写；对应用 CTB 事件位点承载 |
| **【删除】** | **纯回合制产物**，CTB 下**无对应物**（如「整轮」概念、固定先手/后手对）。 | 按项目决策保留为**抛 `NotImplementedError` 的壳**（暴露误用） |

> 说明：`NotImplementedError` 壳由硬约束要求（`end_turn`/`enemy_act`/`action_order`）——它们在本文档中归类为**【删除】**，但**保留同名签名壳**，不物理移除。

### 0.2 CTB 事件位点词典（需求文档给定，本文档全部映射以此为词表）

```
BATTLE_START / ACTOR_READY / BEFORE_ACTION / ACTION_RESOLVE / AFTER_ACTION
ACTOR_TURN_START / ACTOR_TURN_END / BATTLE_TIME_ADVANCE / ACTOR_DEATH / BATTLE_END
```

**映射规则（套用来源：需求文档）**：

| 原回合制语义 | CTB 等价物 |
|---|---|
| 回合开始 DOT | 目标自身 `actor_turn_start` |
| 回合结束 DOT | 行动者 `actor_action_end`（= `AFTER_ACTION` 尾部） |
| N 回合状态衰减 | N 次**该状态持有者**行动 |
| AI 行动冷却 | N 次**该 AI 自身**行动 |
| 全局战斗时间效果 | `battle_time`（= `BATTLE_TIME_ADVANCE` 累积） |
| 单次 after_action | 当前 action 结束事件（`AFTER_ACTION`） |

### 0.3 关于「不允许待定」

本文档**无空白/待定条目**。凡拿不准者，一律给出判断 + 依据，并显式标记为「**存疑但倾向 X**」。

---

## 1. 三分类总表（107 方法逐行）

> 行号格式：`起-止`（AST 实测）；「分类」列见 §0.1；「回合耦合」列标出该行是否触碰回合数值语义（详见 §4 标红表）。

### 1.1 构造 / 状态字段 / 状态机（311–508）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 311-388 | `__init__` | 【平移】 | 依赖注入装配（pipeline/runtime/registry/enemy_ai）；无回合逻辑 | — |
| 390-410 | `_formula_params_from_registry` | 【平移】 | 读 `registry.modules_raw["formula"]` 装配公式参数，纯配置 | — |
| 414-439 | `_reset_state` | 【重写】 | 初始化含回合态字段：`_phase=PHASE_TURN_START`、`_turn_acted`、`_transform_dispel_pending`、`_transform_revert_pending`、`_guard_active`。CTB 须换为行动条/`_ready`/`_recovery` 态 | 是 |
| 444-446 | `state`（property） | 【平移】 | 状态访问器 | — |
| 449-451 | `phase`（property） | 【重写】 | `_phase` 承载「回合相位」，CTB 无回合相位 | 是 |
| 454-456 | `finished`（property） | 【平移】 | 终局访问器 | — |
| 458-472 | `_to_state` | 【重写】 | 8 态状态机 + `_LEGAL_EDGES`（含 `ACT↔RES` 的 T8「下一行动者」、`PREP→SNP` 回合边界中断）。CTB 须重建合法迁移集 | 是 |
| 476-486 | `_new_runtime` | 【平移】 | 五块效果快照 → `EffectRuntime`，与回合无关 | — |
| 488-491 | `_absorb_runtime` | 【平移】 | runtime 五块回灌快照 | — |
| 493-508 | `_player_stance` | 【重写】 | **回合数语义**：`_tn == int(self._snap.get("turn",0))` 姿态窗口=「当回合」。CTB 须改为「持有者本次行动内」/action 窗口 | **是（标红）** |
| 510-518 | `_action_tags` | 【平移】 | 从 action/skill def 读可防反/可闪反标签 | — |
| 520-535 | `_run_counter` | 【平移】 | 反击技执行（不占行动/无消耗），与回合无关 | — |

### 1.2 变量/公式/效果聚合（537–703）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 537-554 | `_refresh_defenses` | 【平移】 | `prepare_defense` 归一化防御行；每次结算前刷新，与回合无关 | — |
| 556-566 | `marks_manager` | 【平移】 | 印记管理器访问器（绑 `marks_state`） | — |
| 568-571 | `combo_engine` | 【平移】 | 连段引擎访问器 | — |
| 574-576 | `armor_active`（property） | 【平移】 | 霸体瞬态读写 | — |
| 578-580 | `_combat` | 【平移】 | 取 combatant 映射 | — |
| 582-583 | `_opposite` | 【平移】 | 对侧解析 | — |
| 585-587 | `_alive` | 【平移】 | 存活判定 | — |
| 589-590 | `_dead` | 【平移】 | 死亡判定 | — |
| 592-594 | `_roll` | 【平移】 | 确定性随机 | — |
| 598-611 | `_combat_map` | 【平移】 | 公式求值 combatant 映射（补派生键 + 印记视图） | — |
| 613-642 | `_make_eval_formula` | 【平移】 | 公式引擎接线。**含 `"round": int(self._snap.get("turn"))`（:627）**——公式变量 `round` 须在 CTB 映射为 `battle_time`，但方法结构本身不变 | **是（标红 :627）** |
| 644-659 | `_base_variables` | 【平移】 | DamageCtx.variables 装配。**含 `"battle":{"round": int(turn)}`（:657）**——同 `round` 映射 | **是（标红 :657）** |
| 663-668 | `_status_raw` | 【平移】 | 状态 def 解析 | — |
| 670-698 | `_aggregate_boost` | 【平移】 | F-23 效果值聚合 + S6/S7 封顶，纯数值 | — |
| 700-703 | `_apply_boost_to_mult` | 【平移】 | 加成并入技能倍率，纯数值 | — |

### 1.3 行动记录 / 死亡判定（707–855）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 707-745 | `_record_action` | 【平移】 | 按段写 action_record。**`entry["turn"]`（:721）**记录归属回合——CTB 下改记 `action_seq`/`time` | **是（标红 :721）** |
| 749-772 | `_mark_dead` | 【平移】 | 死亡登记 + `mark_win/mark_lose`。**`{"trigger","turn","seq"}`（:771）** | **是（标红 :771）** |
| 774-789 | `_death_check_side` | 【平移】 | 死亡判定两触发点之一（扣血后）。CTB 映射到 `ACTOR_DEATH` 事件 | — |
| 791-799 | `_boss_immediate_win` | 【平移】 | BOSS/最后目标即时结束判定 | — |
| 801-855 | `_resolve_battle_end` | 【平移】 | 终局裁决（互杀 order/hp_ratio、BOSS 立即胜）。CTB 映射 `BATTLE_END` | — |

### 1.4 资源门禁 / 组合门禁 / 冷却 tick（857–1373）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 857-904 | `_apply_skill_energy` | 【平移】 | energy_cost 门禁 + gain。**含 R-6 语义空洞（:862/:896「不耗回合」）** | **是（R-6）** |
| 906-977 | `_apply_consume_marks_gate` | 【平移】 | consume_marks 门禁 + 扣除。**「被拒不耗回合」（:911/:963）** | **是（R-6）** |
| 979-987 | `_resource_ctx` | 【平移】 | 资源轴 ctx 构造 | — |
| 991-1018 | `_job_transform_segment` | 【平移】 | transform 段惰性解析 | — |
| 1020-1057 | `_transform_ctx` | 【平移】 | trigger_transform ctx 构造（含 `skip_check` 注 `skip_turn`） | — |
| 1059-1080 | `_transform_apply_status` | 【平移】 | 形态状态施加（effects 通道） | — |
| 1082-1085 | `_transform_skip_check` | 【重写】 | 读 `control_state.skip_turn>0`——被控判定源含「回合数」语义（控制由 N 回合驱动） | 是 |
| 1087-1092 | `set_transform_def` | 【平移】 | 装配注入 | — |
| 1094-1098 | `set_job_id` | 【平移】 | 装配注入 | — |
| 1100-1102 | `_transform_policy_report` | 【平移】 | transform 事件审计 | — |
| 1104-1156 | `_apply_transform_revert` | 【平移】 | 还原结算（自然/主动/dispel 三路归一），与回合无关 | — |
| 1158-1164 | `_transform_combo_clear` | 【平移】 | combo 清空注入通道 | — |
| 1166-1170 | `_transform_marks_clear` | 【平移】 | 印记清空注入通道 | — |
| 1172-1180 | `_transform_buff_remove` | 【平移】 | 形态状态移除注入通道 | — |
| **1182-1204** | **`_transform_dispel_tick`** | **【重写】** | **强制项 #8**：D-05「驱散命中登记 → **下一回合结束 tick**还原」。CTB 无「回合结束 tick」，须挂 `AFTER_ACTION`/`ACTOR_TURN_END` | **是** |
| 1206-1293 | `_resolve_combo_table_gate` | 【平移】 | combo_table 组合门禁 + F-C2 双耗。**「被拒不耗回合」（:1214/:1240/:1242/:1278）** | **是（R-6）** |
| 1295-1302 | `_energy_check_ok` | 【平移】 | 能量池检查 | — |
| 1304-1311 | `_energy_pay` | 【平移】 | 能量池扣减 | — |
| **1313-1326** | **`_tick_skill_cooldowns`** | **【重写】** | **强制项 #9**：技能冷却「每回合 -1」（:1314）。CTB 须改为「该侧每 N 次行动 -1」 | **是** |
| **1328-1373** | **`_tick_transform_state`** | **【重写】** | **强制项 #10**：transform 形态 `remaining-1`/`cooldown-1` 全按回合（:1329/1332）。同上改按持有者行动次数 | **是** |

### 1.5 赛季联动（1377–1512）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 1377-1410 | `_init_season_state` | 【平移】 | 进战懒加载换季状态段（`BATTLE_START` 时点） | — |
| 1412-1417 | `_season_ctx` | 【平移】 | 换季数据源 ctx | — |
| 1419-1453 | `_check_season_action` | 【重写】 | 非当季技能「被拒不耗回合」（:1424/1442），且「当前季节**每回合现读**」（:1425）。须改为 action 级校验 + R-6 代价重定义 | **是（R-6）** |
| **1455-1469** | **`_tick_season_boundary`** | **【重写】** | **强制项 #11**：挂 `end_turn ⑥ tick 后`（:1456），「本回合行动阶段已结束」的边界语义。CTB 须挂 `BATTLE_TIME_ADVANCE`/行动边界 | **是** |
| 1471-1512 | `_fire_season_event` | 【平移】 | on_season_change 事件触发（幂等 + proc 容器） | — |

### 1.6 事件分派 / 收尾 / 伤害管线公开 API（1514–1660）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 1514-1529 | `_dispatch_event` | 【平移】 | 统一效果事件分派（`BATTLE_START`/`BATTLE_END`/`death` 等已按事件名调用） | — |
| 1531-1597 | `_settle` | 【平移】 | 统一收尾（连段清零 + 资源 reset + BATTLE_END 事件）。**`BattleOutcome.turn`（:1592）** | **是（标红 :1592）** |
| 1601-1639 | `resolve_damage` | 【平移】 | 8 阶段拦截链执行器（保留旧签名）。核心战斗数学，零回合依赖 | — |
| 1641-1660 | `_minimal_snapshot` | 【平移】 | 最小快照骨架（含 `"turn":0` 占位，测试用） | 轻微 |

### 1.7 战斗生命周期主循环（1664–2050）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 1664-1839 | `start` | 【重写】 | 建 `battle_state`（`turn:0`/`round_phase`），收尾调 `start_turn()`（:1838）。CTB 须建行动条并挂 `BATTLE_START` | **是** |
| 1841-1847 | `set_effect_ids` | 【平移】 | 装配效果 ID + 刷新防御 | — |
| **1849-1911** | **`start_turn`** | **【重写】** | **强制项 #1**：回合开始（①回合开始 DOT 结算 :1867-1887 + 控制回合递减 :1888-1894 + ②即死判定）。CTB 须拆为 `ACTOR_TURN_START`（按持有者） | **是（标红 :1885）** |
| **1913-1925** | **`action_order`** | **【删除】** | **强制项 #2（重写头号目标）**：固定/伪速度排序，排一次固定整回合。CTB 无「行动顺序表」概念——由行动条动态决定 | **是** |
| 1927-1939 | `_is_dummy_enemy_def` | 【平移】 | 木桩判定（读快照标记/敌人 def） | — |
| **1941-1953** | **`next_action_owner`** | **【重写】** | **强制项 #3**：按 `action_order` + `_turn_acted` 找「下一个可行动者」（先手/后手判定）。CTB 须换为「下一个 ready actor」（ACTOR_READY） | **是** |
| 1955-1982 | `do_action` | 【平移】 | 行动入口（状态门禁 + `_current_actor` 上下文）。CTB 保留为「提交一次行动」入口 | — |
| 1984-2016 | `_do_action_inner` | 【重写】 | 动作分派；置 `_turn_acted[attacker]=True`（:1991），控制裁决按 `control_state.turns` | **是** |
| 2020-2037 | `_guard_actor` | 【重写】 | 防御：`_guard_active` 于「本回合」受击 ×0.5，回合结束清零（:2037 文案）。CTB 须定义防御的持续窗口 = 到下次该 actor 行动 / 固定时间 | **是** |
| **2039-2050** | **`_skip_turn`** | **【重写】** | **强制项 #6**：被控制跳过行动（硬直）。CTB 语义应 = 该 actor 本次 ready 被消费但不产出 action，仍推进时间 | **是** |
| 2052-2095 | `_flee_actor` | 【重写】 | 逃跑「仅回合边界」（:2053，T6）；CTB 无回合边界，须定义为「任意 ready 时点」 | **是** |
| 2097-2129 | `_resolve_item_action` | 【平移】 | 道具行动（L0 执行器）。docstring 注「不耗回合」（R-6 同型） | **是（R-6）** |

### 1.8 连段/伤害结算（2131–2649）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 2131-2484 | `_resolve_combo_action` | 【重写】 | 主干伤害/效果/派生逻辑=平移，但**强回合耦合**：`_turn_acted` 回滚（:2234/:2316/:2336）、技能冷却读取（:2177-2184）、`counter_stance.turn` 写入（:2288-2290）。CTB 须保留主体、替换时序。**存疑但倾向【重写】**：其伤害核心（:2140-2147、:2244-2277）应平移；仅门禁回滚/冷却/姿态窗口重写 | **是** |
| 2486-2499 | `_face_enemy` | 【平移】 | 行动前方位复位（「每轮」实为「每次行动前」，CTB 语义不变） | — |
| 2501-2530 | `_settle_air_landing` | 【重写】 | 空中姿态「**回合**到期自动落地」（:2502），依赖状态的回合 duration 归零。CTB 须按持有者行动次数/N 次时间推进 | **是** |
| 2532-2576 | `_trigger_on_dodge` | 【平移】 | 闪避回馈（status def `on_dodge_effects`），effects 通道 | — |
| 2578-2620 | `_position_miss_outcome` | 【平移】 | 方位 miss 收口（完整行动收尾），与回合无关 | — |
| 2624-2649 | `_settle_air_policy` | 【平移】 | air_policy 行动收尾（`action_end` 时点），与回合无关 | — |

### 1.9 部位破坏 / 方位（2653–2800）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 2653-2663 | `_enemy_parts_defs` | 【平移】 | 敌方部位配置读取 | — |
| 2665-2680 | `_init_parts_state` | 【平移】 | parts_state 实例化 | — |
| 2682-2690 | `_part_state_of` | 【平移】 | 部位实例态读取 | — |
| 2692-2725 | `_resolve_part_target` | 【平移】 | 部位 resolve（位置 + 优先级随机） | — |
| 2727-2749 | `_status_damage_mult` | 【平移】 | 受击增伤乘区（status `damage_mult`） | — |
| **2751-2800** | **`_fire_part_break`** | **【平移】** | 破位事件收口（走 effects 通道）。**但含强制登记项 `2790` 倒地窗口覆写**：`inst["turns"] = kd` 直接把 `on_break.knockdown` 当**回合数**写入状态实例 | **是（标红 :2790）** |

### 1.10 核心伤害闭环（2802–3257）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| 2802-3143 | `_resolve_damage_action` | 【平移】 | **引擎核心**：命中→会心→格挡→双通道→总伤害→拦截链→扣血→死亡判定→反射回注→`tick_after_action`。零回合依赖；`_phase` 仅作流水标注。CTB 下 `tick_after_action` 即 `AFTER_ACTION` | — |
| 3145-3164 | `_deliver_reflect` | 【平移】 | F-22 反弹回注 | — |
| 3166-3187 | `_action_outcome` | 【平移】 | ActionOutcome 构造 | — |
| 3189-3197 | `_after_actor_action` | 【重写】 | 行动者完成后推进：调 `next_action_owner()`（:3195）+ `RES→ACT` 迁移（:3197）。CTB 须换为「推进行动条 / 触发 ACTOR_READY」 | **是** |
| 3199-3202 | `_normalize_attack_type` | 【平移】 | 中文 attack_type → 伤害通道 token | — |
| 3204-3257 | `_ai_action_dict` | 【平移】 | MonsterAI 决策产出 action_dict（PVP 恒 guard 分支）。**注：AI 冷却在 `end_turn` 侧递减，本方法不递减** | — |
| 3259-3302 | `_interrupt_enemy_ai` | 【平移】 | 打断怪物连招/蓄力（`combo_broken` 一次性标记）。**存疑但倾向【平移】**：注释「下一回合走随机流程」→ CTB 应理解为「该 AI 下一次行动」，AI 状态机本身无需改 | （注释性） |

### 1.11 时序壳 / 报告 / 快照 / 查询（3304–3734）

| 行号 | 方法 | 分类 | 理由 | 回合耦合 |
|---|---|---|---|---|
| **3304-3331** | **`enemy_act`** | **【删除】** | **强制项 #5**：⑤ 后手行动 hook（固定后手）。CTB 无先手/后手对。保留为抛 `NotImplementedError` 的壳 | **是** |
| **3333-3426** | **`end_turn`** | **【删除】** | **强制项 #4**：⑥⑦⑧⑨ 回合收尾（tick→互杀→结束→下一回合）。CTB 无「整轮收尾」。保留为抛 `NotImplementedError` 的壳 | **是** |
| 3428-3441 | `_snapshot_pos` | 【平移】 | 快照方位读取（HUD） | — |
| **3443-3454** | **`_turn_report`** | **【重写】** | **强制项 #7**：构造 `TurnReport`（含 `turn`/`phases`）。CTB 须换为「行动报告」，去掉回合相位 | **是** |
| 3456-3505 | `player_act` | 【重写】 | **公开主入口**（`battle_commands.py:1016` 调用，签名须零改动）。语义从「整轮：先手→后手→tick→结算」改为「提交一次玩家行动并推进到下一个 ready actor」。被拒分支（:3474-3487）须按 R-6 新语义重定义 | **是** |
| 3507-3523 | `_normalize_action` | 【平移】 | 玩家指令归一化（normal/guard/flee/skill:id/dict） | — |
| 3527-3566 | `to_snapshot` | 【重写】 | 快照落点约束「**只落回合边界**」（:3536-3547，boundary=turn_start/turn_end）。CTB 无回合边界，须定义新落点（如 `AFTER_ACTION`/ready 边界） | **是** |
| 3568-3570 | `snapshot` | 【平移】 | `to_snapshot` 别名（旧名兼容） | — |
| 3572-3586 | `record_alchemy_used` | 【平移】 | 战斗即时调合计数 | — |
| 3588-3592 | `interrupt_snapshot` | 【重写】 | 中断落快照「等待回合边界」（:3589）。CTB 须定义新边界等待 | **是** |
| 3594-3707 | `from_snapshot` | 【重写】 | T7 恢复：`bnd=="turn_end"→PREP`、`turn_start→ACT`（:3661-3676）。CTB 须重建 ready 态恢复 | **是** |
| 3709-3718 | `resume` | 【平移】 | `from_snapshot` 别名（旧名兼容透传） | — |
| 3722-3724 | `battle_state` | 【平移】 | 快照查询（深拷贝） | — |
| 3726-3728 | `result` | 【平移】 | 结果标记查询 | — |
| 3732-3734 | `_json_roundtrip`（static） | 【平移】 | JSON 往返测试辅助 | — |

### 1.12 三分类汇总

> 计数口径：**1 个方法 = 1 行**（上表实测 107 数据行，与 AST 提取的 107 个 `BattleEngine` 方法一一对应，无遗漏无重复）。

| 分类 | 方法数 | 占比 | 备注 |
|---|---|---|---|
| 【平移】 | **79** | 73.8% | 伤害数学层主体 + 效果/印记/连段/资源/部位/方位/公式/快照查询接线 |
| 【重写】 | **25** | 23.4% | 含 4 个隐藏 tick + 主循环骨架 + 快照/报告/姿态窗口/控制裁决 |
| 【删除】 | **3** | 2.8% | `action_order`(1913) / `enemy_act`(3304) / `end_turn`(3333) |
| **合计** | **107** | 100% | — |

**【删除】3 个方法 = 物理壳保留清单**（硬约束要求：抛 `NotImplementedError`）：

| 行号 | 方法 | 为何无可对应物 |
|---|---|---|
| 1913 | `action_order` | 「一次性固定整回合行动顺序」在 CTB 不存在（由行动条动态决定） |
| 3304 | `enemy_act` | 「固定后手反击」在 CTB 不存在（怪物与玩家同走 ACTOR_READY 通道） |
| 3333 | `end_turn` | 「整轮收尾」在 CTB 不存在（各 tick 拆到各自事件位点） |

> **口径澄清（重要）**：`start_turn`(1849)、`_skip_turn`(2039)、`_turn_report`(3443)、`_transform_dispel_tick`(1182) 等虽含强烈回合语义，但 CTB 下**确有对应物**（`ACTOR_TURN_START` / skip-ready / 行动报告 / 延迟还原位点），故归【重写】，**不得抛错**。**只有语义上无对应物的 3 个才允许物理抛错**——否则会丢掉必要业务能力。

---

## 2. 外部影响面清单（`battle.py` 之外）

> 搜索表达式：`turn|tick|round|回合|start_turn|end_turn|action_order|next_action_owner`，全仓符号级。
> 结论：**外部有 12 个文件假设回合制**。按耦合强度分三级。

### 2.1 A 级 · 直接依赖旧时序 API（编译期/运行期必断）

| # | 文件:行 | 符号 | 影响 | CTB 处置 |
|---|---|---|---|---|
| A1 | `core/pvp.py:332-352` | `BattleEngine().start(...)` → `battle.player_act(...)` → `battle.enemy_act({"type":"guard"})`（:350） | **调用 `enemy_act`——CTB 下将抛 `NotImplementedError`**。PVP 模式 `free`/`turn_based`（:345-352）二分支皆依赖后手语义 | 必改：PVP 须走 CTB 行动推进；`enemy_act` 调用点须替换为 CTB「防守方 ready」注入 |
| A2 | `commands/battle_commands.py:1016` | `report = engine.player_act(action)` | 主入口；`player_act` 重写后签名不变，但**返回值语义从「整轮报告」变为「单次行动报告」** | 兼容（签名零改动）；但下游渲染须理解新语义 |
| A3 | `commands/battle_commands.py:695-851` | `dispatch_round(...)` 整体 | 「一轮派发」：`player_act→enemy_act→end_turn` 的产物合并 1 条（军规3 单回合单条） | 必改：回合叙述→CTB 行动叙述；`_build_segments` 的 turn 过滤（A4） |
| A4 | `commands/battle_commands.py:470-498` | `_build_segments(snap, turn)` → `entry.get("turn") != turn`（:483） | **按 `turn` 过滤 action_record**——CTB 无 turn 字段则**所有段被过滤 → 连段段行静默消失** | 必改：改用 `action_seq`/`actor` 过滤 |
| A5 | `commands/battle_commands.py:229-279` | `enrich_round_report(...)` | 承载 `turn`/`phases` 字段透传（:262-263） | 兼容但要清 `phases` 回合语义 |
| A6 | `core/battle_season.py:442-497` | `tick_season_boundary(snap, season)` docstring 明写「battle.end_turn ⑥ tick 之后」「回合结束 tick 之后、下一回合开始之前」（:266/:452） | 契约时点绑 `end_turn` | 必改：契约时点改挂 `BATTLE_TIME_ADVANCE`；函数体纯（仅读写 `battle_season` 段），可直接复用 |
| A7 | `core/battle_reward.py:21` | 注释「触发判定在指令层（`dispatch_round` win 分支…）」 | 奖励触发绑 `dispatch_round` | 随 A3 调整；函数体纯 |
| A8 | `world/snapshot_resume.py:43-44, 104-105, 146-156, 367` | `_SNAPSHOT_REQUIRED_KEYS=("ai_state","combo_state","turn")`；`_snapshot_turn()` 读 `turn`/`snapshot_at.turn` | **完整性校验强依赖 `turn` 键**——CTB 快照无 `turn` → `missing_fields=["turn"] → reason="incomplete_snapshot"`，**续战全断** | 必改：契约键改（如 `action_seq`/`battle_time`），双写规则重定义 |

### 2.2 B 级 · 渲染/展示层假设回合叙述

| # | 文件:行 | 符号 | 影响 | CTB 处置 |
|---|---|---|---|---|
| B1 | `core/message_format/battle_render.py:110-176` | `render_battle_round(round_result)` | 行序 = 「回合死亡判定顺序：先手→击杀→后手→结算」（:135）；玩家防御中受击分发（:154） | 必改：行序改按 outcome 时序（本就按 outcomes 顺序，注释/守卫需改） |
| B2 | `core/message_format/battle_render.py:204-231` | `BREP-24` 汇总行 `战斗结束：{结果}｜回合数 N｜…`；`_battle_turns(player,enemy,summary)` | **渲染「回合数 N」直接取 `turns|turn`** | 必改：`回合数`→`行动数`/`战斗时长`；取数改 `battle_time` |
| B3 | `core/message_format/battle_render.py:513-521` | `battle_player_defend`「本回合受到伤害减半」 | 防御文案绑回合 | 必改文案（防御窗口重定义，见 §1.7 `_guard_actor`） |
| B4 | `core/message_format/battle_render.py:932` | 注释「先手击杀的怪物不产出本行——由引擎 `enemy_act` 保证」 | 叙述依赖后手 | 注释级；随 A3 |
| B5 | `commands/battle_commands.py:309-313` | `_enemy_ns(enemy, turn=...)` 注入 `turn` 属性 | BREP-24 回合数取数源 | 随 B2 |

### 2.3 C 级 · 快照/会话/装配/其他（弱耦合或仅注释）

| # | 文件:行 | 符号 | 影响 | CTB 处置 |
|---|---|---|---|---|
| C1 | `world/session.py:41-42, 320-327` | 注释「读 payload 字段（target/turn）」；`SessionView` 透传 | 会话层**只透传 payload**，不解析回合语义 | 兼容（payload 形态随快照契约变，session 无需改） |
| C2 | `assembly/context.py:1586-1645` | 引擎恢复：`BattleEngine.from_snapshot(payload,…)` + `set_job_id` + `_resource_registry` 注入 | **恢复入口**，依赖 `from_snapshot` 的回合边界恢复逻辑 | 随 §1.11 `from_snapshot` 重写调整 |
| C3 | `assembly/context.py:1815` | 注释「升级信息回挂 ctx（`dispatch_round` win 分支 send_end 渲染升级行）」 | 注释级 | 随 A3 |
| C4 | `commands/battle_launch_commands.py:326, 377-409` | `BattleEngine.from_snapshot(payload,…)`；`BattleEngine(...)` + `eng.start(...)` + `to_snapshot()` | **开战入口**；`start` 重写须保持签名 | 随 §1.7 `start` 重写调整 |
| C5 | `core/fishing_king.py` | 无 `turn/round` 命中（仅 `return` 假阳性） | 无耦合 | 无需改 |
| C6 | `core/battle_boundary.py:70, 79, 176` | `assert_turn_no_timeout`；`LOST_RESOLVE_NORMAL="① 目标仍在场 → 正常结算本回合"` | **世界边界**：仅文案/断言名含「回合」，函数体为丢失挂起状态机 | 文案级；`assert_turn_no_timeout` 需确认是否被外部消费（见下 C6 存疑） |
| C7 | `core/monster_ai.py:128-136, 429` | 注释「交给 battle._do_action/enemy_act 执行」；AI 默认动作与 `enemy_act` 缺省同构 | **注释级**；`MonsterAI.decide/tick` 无回合依赖（tick 由引擎调用，语义=AI 自身行动计数，符合 CTB） | 注释级；`tick` 语义已兼容 CTB |
| C8 | `core/transform_revert.py:9, 161` | `tick_remaining/tick_cooldown` + 注释「挂 end_turn ⑥ 之后」 | 纯函数按「次数」递减，**函数体已兼容 CTB**，仅注释绑 end_turn | 注释级 + 调用点改挂 `AFTER_ACTION` |

> **C6 存疑但倾向「需人工确认」**：`battle_boundary.assert_turn_no_timeout`（:70）名称含 `turn`，本轮全仓搜索结果仅出现在 `__all__`。**倾向**：其为导出断言名，语义=「回合内不得超时」；CTB 下应改名或保留（若外部测试消费）。**建议 Agent 3 落地前 `grep -rn assert_turn_no_timeout` 复核**——本 Agent 未在 `qbot_rpg/` 内发现调用点。

### 2.4 测试/脚本影响面（不计入业务影响，但重写后必然红灯）

以下 25 个测试/脚本直接依赖旧时序 API（`start_turn|end_turn|action_order|next_action_owner|enemy_act(|player_act(`）：
`tests/unit/test_monster_ai_battle.py(18)`、`test_season_battle_link.py(26)`、`test_transform_resource_link.py(21)`、`test_transform_battle_wiring.py(14)`、`test_battle_engine.py(11)`、`test_resource_snapshot.py(11)`、`test_reposition.py(10)`、`test_position_rule.py(9)`、`test_event_dispatcher_battle.py(8)`、`test_resource_battle_full.py(8)`、`test_transform_battle_full.py(7)`、`test_m13_battle_scenarios.py(6)`、`test_m43_regression.py(6)`、`test_air_policy.py(4)`、`test_counter_parry_dodge.py(3)`、`test_battle_wiring.py(3)`、`test_sword_vault_dot_fix.py(3)`、`test_m2_review_fixes.py(2)`、`test_m13_smoke.py(2)`、`test_snapshot_resume.py(2)`、`test_resource_assembly.py(2)`、`test_skill_slots_battle.py(1)`；脚本 `scripts/verify/verify_m1.py`、`verify_m3.py`、`verify_m5.py`、`scripts/verify_veinborn_smoke.py`、`scripts/e2e_m6_smoke.py`。
**处置**：测试数据库会重建（项目已决策删档），这些用例须随 Agent 3 一并改写；**不在本文档范围内逐条展开**（Agent 3 落地时按上面的文件清单处理）。

---

## 3. 11 个强制登记项（原位置 → CTB 目标事件位点 → 语义等价性论证）

> 强制项 = 任务书显式列出的 7 个 + 4 个隐藏 tick。

### M1. `battle.py:1849 start_turn()`

| 维度 | 内容 |
|---|---|
| **原位置** | `1849-1911`；核心：①回合开始 DOT 结算 `1867-1887`（`if int(dot.get("turns",0)) <= 0` @ **1885**）；控制回合递减 `1888-1894`；②即死判定 `1896-1902` |
| **CTB 目标位点** | DOT（`tick=="turn_start"`，:1876）→ **目标自身 `ACTOR_TURN_START`**；控制递减 → 持有者 `ACTOR_TURN_START`；即死判定 → `ACTOR_DEATH` |
| **语义等价性论证** | 原语义 = 「**每个回合开始时**，所有单位的回合开始 DOT/控制计数各结算一次」。CTB 下同一语义 = 「**每个单位的行动开始时**，仅该单位自身的 DOT/控制计数各结算一次」。差异边界：原为**全员同步**（1v1 即双方各一次），CTB 为**按行动条先后异步**。等价成立的前提：DOT/控制本应绑「持有者的时间推进」——这正是 CTB 的设计意图（映射规则「回合开始 DOT → 目标自身 `actor_turn_start`」）。**数值等价**：同一场战斗内，每个 actor 的 `actor_turn_start` 触发次数 = 原回合数（当双方每回合各行动一次时）；但行动条可能导致一方行动更多次 → **这属于 CTB 有意的机制差异，非资产丢失**。 |

### M2. `battle.py:1913 action_order()`

| 维度 | 内容 |
|---|---|
| **原位置** | `1913-1925`：`order=["player","enemy"]`，`actor_order=="speed"` 时按 `spd` 降序 + 玩家平局优先（:1920-1924） |
| **CTB 目标位点** | **无对应位点（删除）**；由 `ACTOR_READY` + 行动条 `battle_time` 动态产出 |
| **语义等价性论证** | 原语义 = 「一次性排出整回合的固定出手序」（伪速度：排一次即固定，与 spd 无持续关系）。**这是重写要消灭的头号目标**——CTB 的行动顺序是「每单位独立累计行动条，谁先满谁先动」，不可能用静态 tuple 表达。**判定：纯回合制产物，CTB 无对应物 → 【删除】**（保留抛错壳）。 |

### M3. `battle.py:1941 next_action_owner()`

| 维度 | 内容 |
|---|---|
| **原位置** | `1941-1953`：遍历 `action_order()`，返回首个未 `_turn_acted` 的侧；木桩 enemy 永不出手（:1949-1951） |
| **CTB 目标位点** | **`ACTOR_READY`**（下一个行动条满的单位） |
| **语义等价性论证** | 原语义 = 「本回合内下一个还没行动的单位」。CTB 等价 = 「行动条率先到达阈值的单位」。两者皆为「谁下一个动」，**抽象语义一致**，但实现必须由行动条驱动而非 `_turn_acted` 布尔表。**木桩特例（enemy 永不出手）须保留** → CTB 下等价为「木桩单位不参与 ready 队列」。**判定：【重写】**。 |

### M4. `battle.py:3333 end_turn()`

| 维度 | 内容 |
|---|---|
| **原位置** | `3333-3426`：⑥`tick_turn_end`（:3346）+ 落地（:3350）+ turn_end 事件（:3353）+ DOT 致死判定（:3359-3361）+ AI 冷却递减（:3367-3368）+ transform tick（:3374）+ 技能冷却（:3376）+ 资源 tick（:3387）+ 换季 tick（:3397）+ ⑦⑧终局（:3417-3424）+ ⑨下一回合 `start_turn()`（:3426） |
| **CTB 目标位点** | **无「整轮收尾」对应物（删除）**。其内部各 tick 须**逐项拆到各自位点**：`tick_turn_end`→`AFTER_ACTION`；AI 冷却→AI 自身行动后；transform/技能冷却→持有者行动后；换季→`BATTLE_TIME_ADVANCE`；终局→`BATTLE_END` |
| **语义等价性论证** | 原语义 = 「一整轮结束后集中结算所有衰减/冷却/资源/换季」。CTB 无「一轮」边界，**集中结算点不存在** → 不能平移。**判定：【删除】**（抛错壳）。**但内部 5 类 tick 不可丢**——必须逐项重挂（见 M8~M11），否则冷却永不减、形态永不结束。**这是重写最大风险点**。 |

### M5. `battle.py:3304 enemy_act()`

| 维度 | 内容 |
|---|---|
| **原位置** | `3304-3331`：⑤ 后手行动；被先手击杀不反击（:3314-3315）；木桩跳过（:3319-3320）；`_ai_action_dict` 产出（:3322）；无目标兜底 skip/fallback（:3325-3330） |
| **CTB 目标位点** | **无「后手」对应物（删除）**。怪物行动应走**与玩家同一**的 `ACTOR_READY → BEFORE_ACTION → ACTION_RESOLVE` 通道 |
| **语义等价性论证** | 原语义 = 「玩家先手后，怪物固定后手反击」。CTB 无先/后手对——怪物与玩家由行动条竞争 ready。**判定：【删除】**（抛错壳）。**须保留的资产**：`_ai_action_dict`（MonsterAI 决策，已独立为 :3204，归【平移】）与「被击杀不行动」（CTB 下天然由 `_alive` 门禁保证）。 |

### M6. `battle.py:2039 _skip_turn()`

| 维度 | 内容 |
|---|---|
| **原位置** | `2039-2050`：被控制跳过行动，连段保留（:2040），记 `skip` 流水（:2042-2046） |
| **CTB 目标位点** | **该 actor 的 `ACTOR_READY` 被「消费」但不产出 action**；随后仍 `BATTLE_TIME_ADVANCE` |
| **语义等价性论证** | 原语义 = 「该单位本回合行动被剥夺，但回合仍占位（连段不清、时间仍走）」。CTB 等价 = 「该单位本次 ready 被硬直吞掉，行动条重置并继续累计」。**关键不变量**：①连段保留（`combo_state` 不动）；②时间必须推进（否则硬直导致死锁）。**判定：【重写】**，且**必须显式定义**硬直是否重置行动条（本期倾向于「重置并重新累计」，与「跳过行动」语义一致，但属实现细节，Agent 3 决定时须保证不死锁）。 |

### M7. `battle.py:3443 _turn_report()`

| 维度 | 内容 |
|---|---|
| **原位置** | `3443-3454`：构造 `TurnReport(turn, phases, player, enemy, ended, status, log, pos)` |
| **CTB 目标位点** | **行动报告**（替代 `TurnReport`）；`turn`→`action_seq`/`battle_time`，`phases`→去掉回合相位或改 action 生命周期 |
| **语义等价性论证** | 原语义 = 「一轮（先手→后手→tick→结算）的报告」。返回结构被展示层消费（`battle_render.render_battle_round`）。CTB 下「一次 API 调用产出一份报告」仍成立——**报告容器可保留**，但字段语义须改。**判定：【重写】**，且**须与 §2 的 B 级渲染层协同改**（BREP-24 回合数）。 |

### M8. `battle.py:1182 _transform_dispel_tick()`（隐藏 tick 1）

| 维度 | 内容 |
|---|---|
| **原位置** | `1182-1204`：读 `_transform_dispel_pending` 或 `dispel_triggered` 持久标记 → 「**下一回合结束 tick**」执行 `_apply_transform_revert(REVERT_DISPEL)`（:1195/:1199） |
| **CTB 目标位点** | 持有者**下一次** `AFTER_ACTION` / `ACTOR_TURN_END` |
| **语义等价性论证** | 原语义 = 「驱散当回合不立即还原，延迟到**下一个回合结束 tick**」（D-05：给玩家一个回合的反应窗口）。CTB 等价 = 「延迟到持有者**下一次行动结束**」。**等价性成立**：映射规则「单次 after_action → 当前 action 结束事件」+「N 回合 → N 次持有者行动」。**注意**：原实现含 `_transform_dispel_pending` 瞬态缓存（同回合内驱散立即在 end_turn 还原）；CTB 下该缓存语义变为「同一次行动窗口内」→ Agent 3 须确认窗口边界。 |

### M9. `battle.py:1313 _tick_skill_cooldowns()`（隐藏 tick 2）

| 维度 | 内容 |
|---|---|
| **原位置** | `1313-1326`：遍历 `skill_cooldowns = {side:{skill_id:remaining}}`，每项 `-1`，归零删除（:1322-1326）；docstring「**每回合 -1**」（:1314） |
| **CTB 目标位点** | **该 side 每 N 次行动** `AFTER_ACTION` 后 -1 |
| **语义等价性论证** | 映射规则「AI 行动冷却 → N 次该 AI 自身行动」同理适用于技能冷却（技能属施放者）。原「施放后存 `cooldown+1`，回合边界递减」（见 `_resolve_combo_action:2352-2355` 口径）→ CTB 等价为「施放后存 `cooldown+1`，**该施放者每次行动后**递减」。**数值等价**：同一施放者连续行动 N 次的代价窗口一致。**跨方差异**：原回合制下「玩家技能冷却」与「怪物行动」同步；CTB 下玩家行动更频繁则冷却更快 → **CTB 有意的机制差异**。 |

### M10. `battle.py:1328 _tick_transform_state()`（隐藏 tick 3）

| 维度 | 内容 |
|---|---|
| **原位置** | `1328-1373`：形态 `remaining-1`（`tick_remaining`）、自然结束还原、`cooldown-1`（`tick_cooldown`）；docstring「**回合** tick（end_turn ⑥ 后）」（:1329） |
| **CTB 目标位点** | 持有者**每次** `AFTER_ACTION` / `ACTOR_TURN_END` |
| **语义等价性论证** | 原语义 = 「transform 形态按**回合**计时（remaining=N 回合；冷却 N 回合）」。CTB 等价 = 「按**持有者行动次数**计时」。**这里存在语义风险**：形态 `remaining` 是「玩家的 N 回合」还是「全局 N 回合」？定稿口径为玩家视角（形态属玩家）→ CTB 下 = 玩家 N 次行动，**等价成立**。内部委托的 `transform_revert.tick_remaining/tick_cooldown` 为纯函数（`transform_revert.py:161`），**函数体可原样复用**，仅调用时机改变。 |

### M11. `battle.py:1455 _tick_season_boundary()`（隐藏 tick 4）

| 维度 | 内容 |
|---|---|
| **原位置** | `1455-1469`：委托 `battle_season.tick_season_boundary`；docstring「**回合结束 tick 后调用（⑥⑦ 之间挂点）**」（:1456）；「本回合行动阶段已结束，旧组校验已完成 D-05」（:1459） |
| **CTB 目标位点** | **`BATTLE_TIME_ADVANCE`**（全局战斗时间推进位点） |
| **语义等价性论证** | 原语义 = 「换季检测在**回合结束 tick 后、下一回合开始前**切换，保证当回合行动按旧组校验、新季节次回合生效」。这是**全局战斗时间效果**（季节是世界时间，不属任何 actor）→ 映射规则「全局战斗时间效果 → `battle_time`」。CTB 等价 = 「季节边界在**全局时间推进位点**结算」。**关键不变量**：①切换必须发生在「当前行动校验完成之后」；②幂等（同季节不重复触发，`battle_season` 已保证）。`battle_season.py` 函数体纯（仅读写 `battle_season`/`season_event_state` 段），**可直接复用**，仅接线点改变。 |

---

## 4. 回合数语义标红表

> **标红定义**：「回合数」**直接参与数值计算或状态机判定**（而非仅日志/展示）的位置。这些是 CTB 下最易**静默产生数值偏差**的点，Agent 3 必须逐个替换。

| # | 位置 | 代码语义 | 参与计算？ | CTB 等价物 | 风险等级 |
|---|---|---|---|---|---|
| **R1** | `battle.py:1885`（`start_turn` 内） | `if int(dot.get("turns",0)) <= 0: dots.pop(...)`——DOT 剩余回合归零则移除 | **是**（决定 DOT 生命周期） | 目标自身 `actor_turn_start` 的触发次数计数 | **高** |
| **R2** | `battle.py:1883-1884` | `dot["turns"] -= 1`（回合开始 DOT 倒数） | **是** | 同上，按目标行动次数递减 | **高** |
| **R3** | `battle.py:1888-1894` | `control_state["turns"] -= 1`；归零 `pop("control_state")` | **是**（决定控制时长） | 持有者 `actor_turn_start` 按行动次数递减 | **高** |
| **R4** | `battle.py:2006-2009`（`_do_action_inner`） | `int(ctrl.get("turns",0)) > 0` 才判 skip_turn/混乱 | **是**（控制裁决门禁） | 控制状态剩余次数（与 R3 同源，须同拍递减） | **高** |
| **R5** | **`battle.py:2790-2799`**（`_fire_part_break`） | **`inst["turns"] = kd`**——倒地窗口覆写为 `on_break.knockdown` 的**回合数** | **是**（倒地持续时长直接写实例） | 该状态持有者的 **N 次行动**；`knockdown` 值语义由「回合数」改「次数」 | **高（强制登记项）** |
| **R6** | `battle.py:721`（`_record_action`） | `entry["turn"] = int(self._snap.get("turn",0))` | 否（审计字段），但**被 `_build_segments:483` 用于过滤** | 改 `action_seq`/`battle_time` | **中**（见 §2 A4） |
| **R7** | `battle.py:771`（`_mark_dead`） | `{"trigger","turn","seq"}` 死亡审计 | 否 | 同 R6 | 低 |
| **R8** | `battle.py:627`（`_make_eval_formula`） | 公式变量 `battle["round"] = int(turn)` | **是**（内容包公式可读 `[战斗:round]`） | `battle_time` / 行动计数 | **高**（公式层静默偏差） |
| **R9** | `battle.py:657`（`_base_variables`） | `variables["battle"]["round"] = int(turn)` | **是**（同上，effects 层读） | 同 R8 | **高** |
| **R10** | `battle.py:496-504`（`_player_stance`） | `_tn == int(self._snap.get("turn",0))`——姿态窗口=「当回合」 | **是**（决定防反/闪反是否生效） | 姿态窗口 = 持有者本次行动窗口 | **高** |
| **R11** | `battle.py:2288-2290`（`_resolve_combo_action`） | 写 `counter_stance["turn"] = int(turn)`（与 R10 成对） | **是** | 同 R10（须与消费侧同改，否则姿态恒失效） | **高** |
| **R12** | `battle.py:1592`（`_settle`） | `BattleOutcome.turn = int(turn)` | 否（终局审计） | `action_seq`/`battle_time` | 低 |
| **R13** | `battle.py:1314-1326`（`_tick_skill_cooldowns`） | 冷却**每回合**-1 | **是**（决定技能可用性） | 施放者每 N 次行动 -1 | **高（M9）** |
| **R14** | `battle.py:1329-1373`（`_tick_transform_state`） | 形态 `remaining`/`cooldown` 按**回合**-1 | **是** | 持有者行动次数 | **高（M10）** |
| **R15** | `battle.py:2352-2367`（`_resolve_combo_action` 冷却起算） | `_cds[_sid] = max(old, cooldown+1)`，「施放后 N 回合不可用」 | **是** | 与 R13 同源（存 `N+1`，按行动递减） | **高** |
| **R16** | `battle.py:2502-2521`（`_settle_air_landing`） | 空中姿态「**回合**到期」判定（依赖状态回合 duration 归零） | **是**（决定落地时机） | 持有者行动次数（与 R5/R14 同族） | **中** |
| **R17** | `battle.py:1858`（`start_turn`） | `self._snap["turn"] += 1` | 是（上述所有 R 的**计数源**） | 须整体替换为 `battle_time`/`action_seq` 双计数 | **高** |
| **R18** | `battle.py:1905` / `3445` / `3477` / `3500` | `TurnReport.turn` 透传 | 否（报告字段） | 行动/时间标识 | 低 |
| **R19** | `render:229-231` / `battle_commands.py:309-313` | BREP-24 渲染「回合数 N」 | 否（展示） | 文案改「行动数」；取数改 `battle_time` | 低（但用户可感知） |
| **R20** | `battle.py:3536-3549` / `3589`（`to_snapshot`/`interrupt_snapshot`） | 快照仅落「回合边界」；boundary ∈ {turn_start,turn_end} | **是**（决定快照可否落） | 新边界定义（`AFTER_ACTION`/ready 边界） | **中** |

> **标红合计 20 处**（R1–R20），其中**高**风险 **13** 处（R1–R5、R8–R11、R13–R15、R17）、**中**风险 3 处（R6、R16、R20）、低风险 4 处（R7、R12、R18、R19）。**R8/R9（公式变量 `round`）最危险**——它让内容包公式静默读到错误的时间维度，测试极难覆盖。

---

## 5. R-6 语义空洞（待用户决策）

### 5.1 空洞描述

**位置**：`battle.py:2306`（`_resolve_combo_action` 内 energy_cost 门禁注释区），关联实现 `_apply_skill_energy:857-904`。

**原文**（`:861-862`）：
> `- energy_cost：施放前检查（不足 → 被拒不耗回合，返回被拒 ActionOutcome）；`

同族表述散布于：
- `:896` `f"能量不足（{axis_id}），技能被拒（不耗回合）"`
- `:911` / `:963` `consume_marks` 门禁「被拒不耗回合」
- `:1214` / `:1240` / `:1242` / `:1278` `combo_table` 门禁「被拒不耗回合」
- `:1424` / `:1453` `_check_season_action` 「被拒不耗回合」
- `:2098` 道具行动「不耗回合」
- `:3474-3487` `player_act` 被拒分支（不推进敌行动/不 tick）

**空洞本质**：

> 原回合制下，「**不耗回合**」是一个**明确的时间惩罚单位**——被拒 = 玩家这一「回合」的出手权**保留**（`_turn_acted` 回滚，`:2234/:2316/:2336`），可立即重试；代价是这次操作**零时间成本**（白嫖一次决策）。
>
> **CTB 下不存在「回合」这个惩罚单位**。那么「被拒」的**时间代价**必须重新定义：是「消耗 0 行动（完全免费、可无限重试）」，还是「仍占用 recovery（被拒也需重新累计行动条）」？

### 5.2 为什么这不是小事

1. **平衡性**：若被拒 = 0 时间成本，玩家可在行动条满的同一时点无限次试错（改技能/换目标）→ action bar 的「时间即资源」设计被架空。
2. **死锁风险**：若把「被拒」实现为「占用 ready 但不产出 action」，且行动条重置逻辑有误，可能形成「拒绝→重置→拒绝」循环。
3. **与 `_turn_acted` 回滚的强耦合**：现有三处 `_turn_acted[attacker]=False`（`:2234`、`:2316`、`:2336`）是「不耗回合」的实现载体；CTB 下这三处须整体重设计。
4. **多门禁叠加**：energy / consume_marks / combo_table / season 四类门禁共用同一「被拒」管道（`combo_rejected` + `rejected` outcome），**必须统一口径**，不可分类决策。

### 5.3 可选方案（**不拍板，待用户裁决**）

| 方案 | 语义 | 时间代价 | 优点 | 缺点 |
|---|---|---|---|---|
| **方案 A：零时间成本** | 被拒 = 没发生，行动条不变，立即可重试 | 0 | 与旧「不耗回合」最接近；玩家体验友好 | action bar 时间价值被稀释；可无限试错 |
| **方案 B：占用 recovery** | 被拒也触发该 actor 的 `AFTER_ACTION` 并重置/扣减行动条 | = 一次行动的时间 | 时间即资源，制衡试错 | 与旧语义差异大；玩家可能因误操作被惩罚 |
| **方案 C：部分代价（轻 recovery）** | 被拒不消耗资源，但扣一个较小固定时间片 | 固定小值 | 折中 | 数值需新调参；规则复杂 |
| **方案 D：仅首次免费** | 同一次 ready 内首次被拒免费，之后计入 recovery | 首次 0，后续 >0 | 兼顾体验与制衡 | 需额外状态位；实现复杂 |

### 5.4 R-6 决策依赖链（供用户决策时参考）

- 影响 `_turn_acted` 回滚三处（`:2234/:2316/:2336`）的存废 → 影响 `next_action_owner`（M3）重写 → 影响行动条推进（§1.7）。
- 影响 `player_act`（:3456）被拒分支 → 影响 `battle_commands.py:1016` 的调用结果形态 → 影响渲染层（B 级）。
- 影响四类门禁的统一被拒管道口径（energy/consume_marks/combo_table/season）。

> **⚠️ 待用户决策项（Agent 1 不拍板）**：请用户在方案 A/B/C/D 中裁决，或给出新方案。**在裁决前，Agent 3 不得实现任一被拒路径的时间代价**。

---

## 6. 存疑项清单（已给判断，非待定）

| # | 存疑对象 | 判断 | 依据 |
|---|---|---|---|
| S1 | `_resolve_combo_action`（2131-2484）整体归属 | **倾向【重写】** | 方法体约 60% 是伤害/效果/派生/组合（应平移），但：`_turn_acted` 回滚（:2234/:2316/:2336）、技能冷却读取（:2177-2184）、`counter_stance.turn` 写入（:2288-2290）三处为回合强耦合，且它们嵌入主干控制流，无法只改局部 → 整体重写、内层数值逻辑平移 |
| S2 | `_interrupt_enemy_ai`（3259-3302） | **倾向【平移】** | 仅注释含「下一回合」；`ai_state` 机与 `on_chain_broken` 是纯状态机，CTB 下「下一回合」= 「该 AI 下一次行动」，语义自洽 |
| S3 | `_guard_actor`（2020-2037）归属 | **倾向【重写】** | `_guard_active` 的生命周期绑「本回合」（:2037 文案 + `end_turn`/`start_turn` 清位）；CTB 须重定义防御窗口（= 到该 actor 下次行动前？固定时间片？），属时序决策 |
| S4 | `_settle_air_landing`（2501-2530）归属 | **倾向【重写】** | 依赖「空中姿态状态回合 duration 归零」；若状态 duration 按行动次数（R5/R14 同族）则逻辑须同改 |
| S5 | `battle_boundary.assert_turn_no_timeout`（:70）是否有外部调用 | **倾向「仅导出，无内部调用」** | 本轮全仓 `qbot_rpg/` 未发现调用点（仅 `__all__`）。建议 Agent 3 落地前 `grep -rn assert_turn_no_timeout` 复核（含 tests/scripts） |
| S6 | `_minimal_snapshot` 的 `"turn":0`（:1645） | **倾向【平移】** | 测试兜底骨架的占位键；CTB 下保留占位或改 `battle_time:0`，不影响业务 |
| S7 | `_face_enemy`（2486-2499）归属 | **倾向【平移】** | 注释写「每轮行动开始」，实际语义=「每次行动前复位方位」，CTB 逐次行动仍成立 |
| S8 | `to_snapshot` boundary 取值（turn_start/turn_end，:3547） | **倾向需重定义新枚举** | CTB 无回合边界；但「快照只能落在确定性边界」的不变量必须保留，须由用户/Agent 3 定义新边界名 |

---

## 7. 交付自检

- [x] 三分类覆盖 `battle.py` 全部 **107** 个方法（§1 总表逐行；实测 **平移 79 / 重写 25 / 删除 3**，无遗漏无重复）
- [x] 每个方法带**准确行号**（AST 实测起止）
- [x] 外部影响面：**12 个文件**（A 级 8 / B 级 5 / C 级 8，含重叠文件）+ 测试脚本清单
- [x] **11 个强制登记项**齐备（M1–M11，每项含「原位置→CTB 位点→等价性论证」）
- [x] 回合数语义标红：**20 处**（R1–R20，含 `2790` 倒地窗口、`2306` energy 门禁）
- [x] R-6 语义空洞：描述 + 4 方案 + 依赖链 + **显式标记待用户决策**
- [x] 无「待定」条目（§6 存疑项全部给出倾向 + 依据）
- [x] 未修改任何业务代码
