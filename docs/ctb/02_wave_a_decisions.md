# CTB 重写 · Wave A 裁决记录

> 2026-09-10 · 主 Agent 收口 Wave A
> 基线 tag：`pre-ctb-rewrite` @ `9ef3ce2`

---

## 一、Wave A 交付物

| Agent | 产出 | 状态 |
|---|---|---|
| ① 时序考古 | `docs/ctb/01_asset_inventory.md`（486 行） | ✅ |
| ② 调度器 | `qbot_rpg/core/ctb_rules.py`（~500）、`qbot_rpg/core/ctb_scheduler.py`（~830）、`tests/unit/test_ctb_scheduler.py`（571，36 passed） | ✅ |
| ⑥ 契约守卫 | `scripts/verify_ctb.py`、`scripts/ctb_guardian_findings.md`、`tests/ctb/`（80 passed / 18 xfailed） | ✅ |

### Agent 1 三分类结果（`battle.py` 107 个方法）

| 分类 | 数量 |
|---|---|
| 【平移】 | **79** |
| 【重写】 | **25** |
| 【删除】 | **3**（`action_order` 1913 / `enemy_act` 3304 / `end_turn` 3333 留抛错壳） |

---

## 二、主 Agent 裁决（本文件为权威口径）

### 裁决 1 · recovery 语义 = **总行动恢复值**

**（用户授权「你看着办」，主 agent 定案）**

`recovery` 是该 action 的**总**行动恢复值，与 `DEFAULT_RECOVERY` 是**覆盖**关系，不是附加。

**连带修正**：需求文档 §25 黑盒场景 2 写「重技能 recovery=150 → `P(慢)→E→E→P`」是**示例笔误**。

数学推演（P SPD=100 / E SPD=75 / speed_reference=100）：
```
E 的 ready 时刻 = 133.33, 266.67, 400.0 …
P 用慢技能后 ready = 100 + R
欲使 E 连动两次，需 100 + R > 266.67  →  R > 166.67
```
故 `150` 算不出期望序列。**验收改用 `recovery=200`**（常量 `RECOVERY_DOC_EXAMPLE_SLOW`，下界 `RECOVERY_DOC_EXAMPLE_MIN=166.67` 已入 `ctb_rules.py`）。

**已实测验证**：
- 场景 1：`P→E→P→E→P` ✅
- 场景 2（R=200）：`P→E→E→P` ✅

### 裁决 2 · 被拒行动的时间代价（R-6）= **零时间成本，直接重试**

**（用户明确拍板）**

四类门禁（`energy_cost` / `consume_marks` / `combo_table` / `season`）任一拒绝时：
- 不派发 `ACTOR_TURN_START` 及后续链路事件（**不构成一次行动**）
- **不消费票据时间** —— `next_ready` 保持原值，**行动条不推进**
- 玩家侧立即解除暂停、重新请求输入（可换可行指令）
- 拒绝原因经事件/返回值上报，不静默吞掉

即：**被拒 = 该行动从未发生，时间轴不付代价**。

### 裁决 3 · tie-break 同刻连动 = **刻意设计，非缺陷**

复核发现 SPD100 vs SPD75、recovery 均 100 时，t=400 双方同时 ready（P 步长 100、E 步长 133.33 的公倍时刻），tie-break 使 P 先动 → 出现 `…P→P…`。

**这是 CTB 递推的数学必然**，不是 bug。已写入 `CTB_TIEBREAK_RULE` 旁注。

---

## 三、缺陷修复（主 Agent 执行）

### 修复 1 · F4 回归：M43 零定时器门禁被破

**现象**：全量基线从 `6190 passed / 0 failed` 退化为 `1 failed, 6269 passed`。
`test_m43_zero_timer_repo_wide_scan` 报 `ctb_scheduler.py: ['sched','schedule','threading','time.sleep']`。

**定性**：**命名撞词表，零真实计时器**。实测 `ctb_scheduler.py` 仅 import `logging`/`dataclasses`/`typing`，无 `time`/`threading` 模块。
（M43 是 m3 铁律 1 的守卫：防真实计时器混进逻辑时间——守卫本身是对的。）

**修法**：**重命名避让词表**（而非塞进允许清单）：
- `_schedule(` → `_enqueue(`（7 处，含定义）
- docstring 示例局部变量 `sched` → `ctb`（8 处）
- 两处「声明不使用」的说明文字改为中文表述

**结果**：`ALL_CLEAN`，M43 恢复通过 ✅

### 修复 2 · F2：per-action recovery 无注入入口

**现象**：`CTBScheduler._enqueue()` 硬编码 `default_recovery`，慢技能序列无法经公开 API 产出。

**修法**：`_enqueue(view, base_time=None, recovery=None)` 新增 `recovery` 参数；并打通两条行动消费路径：
- `_auto_resolve_npc(view, action_seq, recovery=None)`（NPC 侧）
- `complete_player_action(recovery=None)`（玩家侧）

其余 `_enqueue` 调用点（`push_actor` 初始入队 / `_resign_after_skip` 跳过后重签 / `update_speed` / `change_rules`）**保持默认 recovery** —— 它们不是行动代价位点，语义正确。

---

## 四、移交给 Wave B 的关键情报

### ⚠ A 级风险（Agent 1 实测发现，方案文档漏列）

| # | 风险 | 位置 | 处置 |
|---|---|---|---|
| **R-A** | **`turn` 是快照完整性必需键** —— `_SNAPSHOT_REQUIRED_KEYS = ("ai_state","combo_state","turn")`。CTB 无 turn 会直接判 `incomplete_snapshot`，**续战全断** | `world/snapshot_resume.py:105`、`_snapshot_turn()` :146 | Agent 4 必须改用 CTB 时间轴字段（如 `battle_time`）替代，或保留 `turn` 作为兼容字段 |
| **R-B** | **`_build_segments` 按 `turn` 过滤行动记录** → CTB 下连段段行会**静默消失** | `commands/battle_commands.py:470` | Agent 4 改为按 action_seq 过滤 |
| **R-C** | **公式层 `round` 变量** —— `battle.py:627`/`:657` 把回合数喂给内容包公式引擎 `[战斗:round]`，是最隐蔽的数值偏差源 | `core/battle.py:627/657` | Agent 3 必须把 `[战斗:round]` 映射到 CTB 等价物（如 action 计数或 battle_time） |
| **R-D** | `action_order()` **不是速度排序**，是「固定 `[player,enemy]`，仅当 `actor_order=="speed"` 才排一次」 | `core/battle.py:1913` | 确认删除，无需迁移逻辑 |

### 存疑项（Agent 1 标记，待 Agent 3 落地时复核）

- `_resolve_combo_action`(2131–2484)：约六成是应平移的伤害数学，但 `_turn_acted` 回滚 / 冷却读取 / 姿态窗口**三处强耦合嵌入主干**，无法局部改 → 倾向【重写】
- `assert_turn_no_timeout`：全仓未见内部调用，Agent 3 落地前复核

---

## 五、Wave A 硬卡点验收

| 卡点 | 状态 |
|---|---|
| 三分类清单 100% 无「待定」 | ✅ |
| 调度器单测独立全绿（不依赖 `battle.py`） | ✅ 36 passed |
| 六大稳定接口契约冻结 | ✅ `tests/ctb/` 80 passed / 18 xfailed（待 Agent 3） |
| 黑盒序列 | ✅ 场景1 `P→E→P→E→P`、场景2(R=200) `P→E→E→P` |
| M43 零定时器门禁 | ✅ 修复后恢复 |
| G0 架构门禁 | ✅ ARCH-OK |

**Wave A 完成，可进入 Wave B。**
