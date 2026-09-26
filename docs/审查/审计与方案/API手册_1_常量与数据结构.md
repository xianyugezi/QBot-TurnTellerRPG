# 框架扩展开发手册 · 第 1 章 · 常量与数据结构

> **本章读者**：① 写内容包 / 写包自持代码 / 用 E 系扩展点的**外部扩展开发者**；② 改框架代码前先看它的**未来维护者**。
> **本章目标**：把"框架里有哪些常量、有哪些数据结构字段、它们各自归谁管、改动会牵动什么"一次讲清，使后续更新**不再把故意设计当 bug 修**。
> **写法**：中文说人话，先讲"这是什么 / 什么时候用 / 谁负责"；每条附 `file:line` 供查；表格优先。

## 0. 本章导读

### 0.1 三条口径（全章通用术语）

| 口径 | 定义 | 对扩展开发者意味着什么 |
|---|---|---|
| **唯一源**（single source of truth） | 该信息**只有一处定义**，其它模块必须 `import` 它，**不得写死字面量** | 你要改它，只改这一处；你要用它，从这一处取 |
| **可被包覆盖** | 内容包通过 `settings.json` 的**某一段**能改；引擎侧"只读声明、不写死" | 你能在包里调数值/开开关，而不是改框架 |
| **别名 / 兼容键** | 同一语义存在多个可接受写法（通常是旧键→新轴的换算） | **不是冗余 bug**；新旧并存是兼容设计，删旧键会让旧内容包静默失效 |

### 0.2 【稳定契约】标记说明

凡标注 **【稳定契约】** 的条目 = **改动需评审**。含义是：该名称 / 值域 / 形状已被内容包、测试或存档数据依赖；单方面改它会静默破坏（不是编译报错，而是旧包数值失效、旧档读不出、测试对拍崩）。改之前请：

1. 读该条目的 `file:line` 定义处注释（多数已写明"勿动/为什么"）；
2. 查 `docs/深度打造_决策记录.md` 是否已有落地登记 / 裁决；
3. 确认有迁移或兼容路径，再动。

### 0.3 核对基线与复核声明

- **本次核对基线**：仓库 HEAD = `62cc299`。上游盘点文档 `API手册_编撰前盘点.md` 基于 `d86d9dd`（2026-09-20），**部分行号已漂移**。
- **复核方式**：本章所有 `file:line` 均由本次**逐条重读源码**或**运行 `python3 -c` 导入常量取值**核对，不复制盘点文档的未复核结论。
- **已发现并纠正的盘点文档错误**（见 §8 复核记录）：`AFFINITY_KEYS` 实际 4 项（盘点写 6）；`DEFAULT_TEMPER` 实际 15 键（盘点写 14）；`EFFECT_AXIS_SPECS` 注释写 15 条而实际 17 条（盘点已指出，本次确认）。
- **标"待查"**：凡本章未亲手核到唯一源 / 未确认意图的，一律写"待查"，**不猜**。

## 1. 常量总表

### 1.1 装备键族 —— 唯一源 `qbot_rpg/data/gear_stats.py`

**这是什么**：装备词条 / 特效轴 / 战斗直读键的**键名空间**。内容包在 `items.json` / `equipment.json` 的装备条目里写这些键，框架按键族把它们分流到不同管线。
**谁负责**：框架 `data` 层定义键空间（唯一源）；内容包只能**使用**键，不能新增键。
**什么时候用**：写装备条目、写词条数值、写编辑器字段表时。

| 常量 | file:line | 数量 | 内容 | 唯一源 | 可被包覆盖 | 别名/兼容键 | 改它的影响面 |
|---|---|---|---|---|---|---|---|
| `PCT_SUFFIX` | gear_stats.py:172 | — | `"_pct"` | ✅ | ❌ | — | 聚合端按此后缀拆层；改它=全部百分比键失去拆层语义 |
| `GEAR_FLAT_KEYS` | gear_stats.py:175 | 13 | atk/def/dfn/hp/mp/str/con/agi/foc/spr/lck/spd/mag | ✅ | ❌（键空间固定） | **`def` ≡ `dfn`**（同一中文"防御"，见 `GEAR_LABELS_ZH:518-519`） | 聚合进 `attributes.bonus["flat"]`；删 `def` 会让旧包防御归零 |
| `GEAR_PCT_KEYS` | gear_stats.py:180 | 8 | atk_pct/dfn_pct/hp_pct/mp_pct/heal_amp_pct/debuff_chance_pct/buff_chance_pct/weakness_dmg_pct | ✅ | ❌ | 后 4 键已由特效轴 `legacy_alias` 归并（§1.2.4），**旧键保留双轨** | 聚合进 `bonus["pct"]`；后 4 键同时是轴别名源，删=旧包数值失效且别名断链 |
| `GEAR_COMBAT_KEYS` | gear_stats.py:186 | 10 | crit/earplug/super_crit_lv/elem_crit_lv/absorb_hp/immune_dmg/pierce_val/pierce_pct/mag_pierce_val/mag_pierce_pct | ✅ | ❌ | `immune_dmg` 同时是 `damage_taken_pct` 的别名源 | 经 `COMBAT_TO_COMBATANT:502` 桥进 combatant |
| `GEAR_COMBAT_PCT_KEYS` | gear_stats.py:192 | 4 | absorb_hp/immune_dmg/pierce_pct/mag_pierce_pct | ✅ | ❌ | — | **仅编辑器显示口径**（单位/范围提示），不参与聚合分流 |
| `GEAR_COMBAT_VALUE_KEYS` | gear_stats.py:195 | 2 | pierce_val/mag_pierce_val | ✅ | ❌ | — | 穿值不封顶；引擎按 `max(0, def-val)` |
| `GEAR_PLACEHOLDER_KEYS` | gear_stats.py:198 | 1 | `cooldown_reduction_pct` | ✅ | ❌ | 是 `cooldown_pct` 的别名（`sign=-1`） | **形似死代码、实为兼容设计**：`route_bonus_into` 显式跳过它，换算只在 `route_legacy_aliases_into_flat` 一处（防双计）。详见 §1.2.4 |
| `PANEL_AXIS_STEMS` | gear_stats.py:205 | 3 | atk/dfn/hp | ✅ | ❌ | — | 落在 data 层是为了让 `content` 校验器能拦"特效轴键名撞面板轴"而**不**反向依赖 core；`core/panel_budget.PANEL_AXIS_KEYS:97` 由它派生 |
| `EFFECT_CONSUMER_PENDING` | gear_stats.py:211 | — | `"（消费点待接）"` | ✅ | ❌ | — | **登记纪律哨兵**：轴有方向但无唯一消费点时必须写它，禁止伪造唯一消费点、禁止留空。见 §1.2.1 |
| `EFFECT_AXIS_SPECS` | gear_stats.py:230-447 | **17 轴** | 见 §1.2 | ✅ | 仅 `min/max` 可由 `settings.effect_axes` 覆盖 | 每轴含 `legacy_alias` | 键空间唯一源；不可手改 `GEAR_EFFECT_KEYS`，要改改本表 |
| `DEPRECATED_EFFECT_AXES` | gear_stats.py:452 | 1 | `action_recovery_pct`→`action_speed_pct` | ✅ | ❌ | — | 校验器**黄提示不硬拦**；改它=废弃裁决变化 |
| `GEAR_EFFECT_KEYS` | gear_stats.py:461 | 17 | 由 `EFFECT_AXIS_SPECS` 派生 | ✅（派生） | ❌ | — | grep 可枚举的轴键元组；**不可手改** |
| `EFFECT_TO_COMBATANT` | gear_stats.py:470 | 16 | `bridge=="combatant"` 的轴 | ✅（派生） | ❌ | — | `reward_mult_pct` 是 `bridge="settlement"`，**不进**战斗桥 |
| `EFFECT_AXES_KEY` | gear_stats.py:477 | — | `"effect_axes"` | ✅ | — | — | `settings.effect_axes` 段键名；消费点读该段做**读时钳制** |
| `OWNED_EFFECT_IDS_KEY` | gear_stats.py:491 | — | `"owned_effect_ids"` | ✅ | ❌ | — | **触发归属（owner）**键名；键缺省=不启用归属过滤（全库扫描旧行为） |
| `GEAR_NUMERIC_KEYS` | gear_stats.py:494 | 48 | FLAT+PCT+COMBAT+EFFECT | ✅（派生） | ❌ | — | 实例化转换 / 展示 / 编辑器遍历 |
| `GEAR_DISPLAY_KEYS` | gear_stats.py:499 | 49 | NUMERIC + PLACEHOLDER | ✅（派生） | ❌ | — | 占位键要能被提取/展示，但不接引擎 |
| `COMBAT_TO_COMBATANT` | gear_stats.py:502 | 10 | (聚合键, combatant 键, 封顶) 三元组 | ✅ | ❌ | — | 战斗桥**非特效部分**；封顶写死在此（如 absorb_hp=100、earplug=2、super_crit_lv=3） |
| `GEAR_LABELS_ZH` | gear_stats.py:517（+576-581 派生注入） | — | 键→中文 label | ✅ | ❌ | `def`/`dfn` 同为"防御" | 展示/编辑器共用；**特效轴 label 由 `EFFECT_AXIS_SPECS` 派生注入，勿在 517 表里重复手写** |
| `GEAR_HELP_ZH` | gear_stats.py:536（+576-581 派生注入） | — | 键→帮助文案 | ✅ | ❌ | — | 编辑器字段提示；同上由轴表派生 |
| `EFFECT_LEGACY_ALIASES` | gear_stats.py:584 | **6** | 旧键→(新轴, sign) | ✅（派生） | ❌ | 见 §1.2.4 | **别名归并唯一源**；`pct = sign × 旧键值` |

> **核对说明**：表中数量均由 `python3 -c "from qbot_rpg.data.gear_stats import ..."` 实测，见 §8。

### 1.2 特效轴全集（`EFFECT_AXIS_SPECS`）

#### 1.2.1 "登记即承诺" —— 本框架最容易被误修的一条纪律

**这是什么**：一句话——**一条轴登记进 `EFFECT_AXIS_SPECS`，就等于对作者承诺"它可以配、配了会生效"**。
**为什么重要**：`cooldown_reduction_pct` 的教训（gear_stats.py:56-58 注释原文）：*"登记了不生效 = 对作者是陷阱"*。
**三条硬规则**（源码 `gear_stats.py:56-59`、`:207-210`、`:224`）：

| 规则 | 含义 | 违规形态 |
|---|---|---|
| **无消费点的轴不得登记** | 登记必须写 `consumer` | `consumer` 留空 = 违反登记纪律（测试钉死：`tests/unit/test_batch50_effect_axes.py:140`） |
| **有方向但无唯一收口 → 写哨兵** | `consumer = EFFECT_CONSUMER_PENDING` + `consumer_note` 写明候选点 | 把候选点之一**伪造成**唯一消费点 = 禁止 |
| **登记即承诺"配置生效"** | 不能只登记、留待以后 | 若确实只登记不生效，**必须在 `display.help` 明说"当前未实现，配置不生效"**（范例：`reward_mult_pct`，`gear_stats.py:432-434`） |

**【稳定契约】**：`EFFECT_AXIS_SPECS` 是键空间唯一源；`GEAR_EFFECT_KEYS` / `EFFECT_TO_COMBATANT` / `DEFAULT_EFFECT_AXES` / `EFFECT_LEGACY_ALIASES` / `GEAR_LABELS_ZH` / `GEAR_HELP_ZH` **全部由它派生**。手改派生表会被下一次 import 覆盖，且破坏唯一源。

#### 1.2.2 17 轴全表：名称 / 范围 / 默认 / 双向 / 别名

**列含义**：**双向** = 该轴既能增强也能削弱（`min < 0` 或 `min = None`）；**单向** = 只有一侧有意义（下钳 0）。**默认**全为 `0.0`（= `×1.0` 恒等 → 未配置零变化）。

| # | axis | doc_id | 优先级 | min | max | 默认 | 双向? | legacy_alias（旧键, sign） | 定义 file:line |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `healing_received_pct` | X17 | P0 | -200 | 300 | 0.0 | 双向 | — | gear_stats.py:232 |
| 2 | `healing_done_pct` | X16 | P0 | -100 | 300 | 0.0 | 双向 | `heal_amp_pct`, +1.0 | gear_stats.py:243 |
| 3 | `damage_taken_pct` | X02 | P0 | -100 | 300 | 0.0 | 双向 | `immune_dmg`, **-1.0** | gear_stats.py:253 |
| 4 | `damage_dealt_pct` | X01 | P0 | -100 | 1000 | 0.0 | 双向 | `weakness_dmg_pct`, +1.0 | gear_stats.py:266 |
| 5 | `cooldown_pct` | X27 | P0 | -80 | 200 | 0.0 | 双向 | `cooldown_reduction_pct`, **-1.0** | gear_stats.py:280 |
| 6 | `status_chance_pct` | X21 | P0 | -100 | 不限 | 0.0 | 双向 | `debuff_chance_pct` +1.0、`buff_chance_pct` +1.0 | gear_stats.py:292 |
| 7 | `stack_gain_pct` | X23 | P0 | -100 | 不限 | 0.0 | 双向 | — | gear_stats.py:305 |
| 8 | `stack_cap_delta` | X24 | P0 | 不限 | 不限 | 0.0 | 双向（加算差值） | — | gear_stats.py:317 |
| 9 | `status_duration_pct` | X20 | P1 | -80 | 300 | 0.0 | 双向 | — | gear_stats.py:329 |
| 10 | `status_duration_taken_pct` | X20 | P1 | -100 | 300 | 0.0 | 双向 | — | gear_stats.py:340 |
| 11 | `status_resist_pct` | X22 | P1 | -100 | 不限 | 0.0 | 双向 | — | gear_stats.py:351 |
| 12 | `action_bar_shift` | X30 | P1 | 不限 | 不限 | 0.0 | 双向（加算差值） | — | gear_stats.py:362 |
| 13 | `resource_cost_pct` | X34 | P1 | -100 | 200 | 0.0 | 双向 | — | gear_stats.py:374 |
| 14 | `resource_gain_pct` | X35 | P1 | -100 | 不限 | 0.0 | 双向 | — | gear_stats.py:386 |
| 15 | `crit_damage_pct` | X03 | P1 | -100 | 300 | 0.0 | 双向 | — | gear_stats.py:396 |
| 16 | `action_speed_pct` | X28 | P1 | -80 | 400 | 0.0 | 双向 | — | gear_stats.py:408 |
| 17 | `reward_mult_pct` | X43 | P1 | **0** | 400 | 0.0 | **单向（下钳 0）** | — | gear_stats.py:424 |

**两种表示口径**（gear_stats.py:52-54、:216）：

| 口径 | 键名特征 | 语义 | 例子 |
|---|---|---|---|
| **百分点增量轴** | 以 `_pct` 结尾，默认 0 | `有效值 = 基准 × clamp(1 + pct/100, min, max)` | `damage_dealt_pct` |
| **加算差值轴** | 无 `_pct` 后缀，默认 0 | 直接加算整数（层数上限 / 行动条） | `stack_cap_delta`、`action_bar_shift` |

**反向键（`sign = -1`）不是符号写错**：`immune_dmg`（免伤比）与 `damage_taken_pct`（承伤比）语义相反，换算 `pct = -1 × immune_dmg`。把 `sign` 改成正号 = **免伤变易伤**（gear_stats.py:60-62）。

#### 1.2.3 攻防"两侧"配对轴（同一机制的两个键实例）

设计口径 R-4：**同一轴线、两个键实例**，攻防两侧分开取值、相乘一次。**这不是重复字段**。

| 机制 | 攻/施予侧 | 守/承受侧 | 两侧是否共用消费点 |
|---|---|---|---|
| 治疗 | `healing_done_pct`（施疗修正，:243） | `healing_received_pct`（受疗修正，:232） | ✅ 同为 `effects.heal_apply` |
| 伤害 | `damage_dealt_pct`（造成伤害，:266） | `damage_taken_pct`（承受伤害，:253） | ❌ 分属 battle 两个乘区 |
| 状态时长 | `status_duration_pct`（:329） | `status_duration_taken_pct`（:340） | ✅ 同为 `effects.apply_status_duration` |
| 状态命中/抵抗 | `status_chance_pct`（:292） | `status_resist_pct`（:351） | ❌ 命中判定 vs 抵抗判定 |

**【稳定契约】**：删掉任一侧、或把两侧合并成一个键，会破坏"攻防可分别配装"的设计意图与既有测试对拍。

#### 1.2.4 别名归并（`EFFECT_LEGACY_ALIASES`，6 条）

**这是什么**：旧键 → 特效轴的**唯一兼容换算**。旧键自身链路**不动**（双轨）。
**唯一换算点**：聚合入口 `route_legacy_aliases_into_flat`（gear_stats.py:754-785 区段）——**只换算一次 → 不双计**。
**为什么形似 bug**：同一个效果能写新键或旧键，旧键值还常与轴符号相反。

| 旧键 | → 轴 | sign | 换算 | 旧键本身还在哪些键族 |
|---|---|---|---|---|
| `heal_amp_pct` | `healing_done_pct` | +1.0 | `pct = +heal_amp_pct` | `GEAR_PCT_KEYS:180` |
| `immune_dmg` | `damage_taken_pct` | **-1.0** | `pct = -immune_dmg` | `GEAR_COMBAT_KEYS:186` |
| `weakness_dmg_pct` | `damage_dealt_pct` | +1.0 | `pct = +weakness_dmg_pct` | `GEAR_PCT_KEYS:180` |
| `cooldown_reduction_pct` | `cooldown_pct` | **-1.0** | `pct = -cooldown_reduction_pct` | `GEAR_PLACEHOLDER_KEYS:198` |
| `debuff_chance_pct` | `status_chance_pct` | +1.0 | `pct = +debuff_chance_pct` | `GEAR_PCT_KEYS:180` |
| `buff_chance_pct` | `status_chance_pct` | +1.0 | `pct = +buff_chance_pct` | `GEAR_PCT_KEYS:180` |

**误修后果**（三条，均为静默故障）：① 删旧键别名 → 旧内容包数值静默失效；② 改成两处都换算 → **双计**（数值翻倍）；③ 把 `sign=-1` 当 bug 改成正号 → 免伤变易伤 / 冷却缩减变冷却拉长。
**【稳定契约】**：`EFFECT_LEGACY_ALIASES` 及其 `sign` 值。

#### 1.2.5 已废弃轴（`DEPRECATED_EFFECT_AXES`）

| 废弃轴 | 替代轴 | 裁决依据 | 校验行为 |
|---|---|---|---|
| `action_recovery_pct` | `action_speed_pct` | 二者数学互为倒数，并存会指数级加速（D2 裁决只留"行动速度"） | **黄提示、不硬拦**（gear_stats.py:452 注释） |

**不得登记、不得实现**。校验器对内容声明/词条命中本表者给黄提示，提示作者改用替代轴。

#### 1.2.6 消费点接线状态（三态）—— 外部开发者最需要先看的一张表

**这是什么**：轴"能不能生效"的现状。**声明 ≠ 已接线**；按未接线的轴配装 = 数值不生效。
**消费点取值**：消费点读 `settings.effect_axes` 声明做**读时钳制**（`min/max` 由包覆盖，引擎不写死）。

| 状态 | 轴 | 说明 |
|---|---|---|
| **已接线**（**16**） | `healing_received_pct`、`healing_done_pct`（批52，收口 `effects.heal_apply` :1838-1888，实调 5 处：`battle.py:4979`、`effects.py:1363`/`:1410`/`:2120`/`:2178`）、`damage_taken_pct`（`battle.py:4253`）、`damage_dealt_pct`（批70，`battle.py:4226`）、`cooldown_pct`（`battle.py:3438`）、`status_chance_pct`（`effects.py:531`）、`stack_gain_pct`（:533）、`stack_cap_delta`（:534，**marks 半边未接**）、`status_duration_pct`（:537）、`status_duration_taken_pct`（:538）、`status_resist_pct`（:532）、`action_bar_shift`（`battle.py:5185`）、`resource_cost_pct`（:1279）、`resource_gain_pct`（:1281）、`crit_damage_pct`（:4724）、`action_speed_pct`（批56，:2575） | 本次**逐轴 grep 实调点**确认（§8）；每轴 `consumer_note` 写明唯一收口 |
| **未接（哨兵）**（**1**） | `reward_mult_pct`（`consumer=EFFECT_CONSUMER_PENDING`；奖励分散在三处，D5 登记；`display.help` 已明说"当前未实现，配置不生效"） | `grep reward_mult_pct core/ commands/` = **0**（§8）→ 哨兵属实 |

> **⚠️ 本次新发现：两条治疗轴的 `consumer_note` 是过期文案。**
> `gear_stats.py:239-241`（受疗）写"待接时须一次改全 4 处 heal 源…"，`:250-251`（施疗）写"原零消费点"——但 **批52 已接线**（`effects.heal_apply` + 常量 `HEAL_RECEIVED_AXIS`/`HEAL_DONE_AXIS` `effects.py:111-112`，测试 `tests/unit/test_batch52_heal_damage_axes.py`）。
> **以上表（实调 grep）为准，不要以 `consumer_note` 的"待接"字样判断轴是否生效。** 该过期文案未列入上游盘点 §6 C 组（属本次新增发现）。
> **口径提醒**：轴是否生效，**唯一可判定方式 = grep 该轴的实调点**（`_axis_pct(` / `effect_axis_value(`），不能只看 `consumer_note` 的措辞。
> **重要**：`action_bar_shift` / `action_speed_pct` 的 `consumer_note` 均登记了"另有既有机制未收编（`counter_refund`、`enrage/fatigue_recovery_mult`）→ 登记待裁决"，**勿把它当遗漏 bug 顺手合并**。

### 1.3 枚举 / 时点（详见第 2 章）

**这是什么**：值域封闭的枚举类常量。**与本章其余部分不同，时点/事件的语义与派发规则归第 2 章**，此处只登记"唯一源 + 数量 + 能否被包覆盖"，避免两章重复。

| 常量 | file:line | 数量 | 唯一源 | 可被包覆盖 | 备注 |
|---|---|---|---|---|---|
| `EVENT_POINTS` | data/event_points.py:25 | **17** | ✅（`core/event_dispatcher.py:51` 引入 + `:60` 原样再导出，兼容旧 import 路径） | ❌（值域固定） | 见第 2 章"已接线/未接线/故意不派发"三态表 |
| `STATUS_EVENT_POINTS` | data/event_points.py:38 | 2 | ✅ | ❌ | status_gain/status_lose |
| `POOL_KINDS` | data/affinity_keys.py:37 | 3 | ✅ | ❌ | common/exclusive/linkage |
| `REACTION_KINDS` | data/affinity_keys.py:43 | 3 | ✅ | ❌ | conflict/amplify/reverse |
| `AFFINITY_KEYS` | data/affinity_keys.py:46 | **4** | ✅ | ❌ | `affinities`/`affinity_pools`/`affinity_linkage`/`affinity_reactions`（`settings` 顶层四段） |
| `ENTRY_PAYLOAD_KEYS` | data/affinity_keys.py:62 | 4 | ✅ | ❌ | stat/set_affix/effect_ref/enhance_affix（相性池词条行载荷键） |
| `AFFINITY_EFFECT_QUALITY_CAP` | data/affinity_keys.py:73 | — | ✅ | ❌ | `"quality_cap_delta"`；**不属特效轴空间**，只并入炼金结算 |
| `RUNE_TIERS` | data/runes.py:41 | (1,2,3) | ✅ | ❌ | `MIN_RUNE_TIER:39` / `MAX_RUNE_TIER:40` |
| `RUNE_UPGRADE_COUNT` | data/runes.py:44 | 3 | ✅ | ❌ | 每阶强化次数 |
| `DEFAULT_SOCKET_COUNT` | data/runes.py:50 | 3 | ✅ | 孔位数组随 `slots` 定义 | 镶嵌状态挂 `ItemInstance.uid` |
| `RUNES_STATE_KEY` | data/runes.py:47 | — | ✅ | ❌ | `"rune_sockets"`（`player.persistent_state` 内） |
| `QUALITY_KEYS` | core/quality.py:80 | 4 | ✅ | 档位边界可经 settings 覆盖 | common/uncommon/rare/legendary |
| `DEFAULT_QUALITY_TIERS` | core/quality.py:56 | 4 | ✅ | ✅ | `{common:(0,39), uncommon:(40,59), rare:(60,79), legendary:(80,100)}` |
| `DEFAULT_QUALITY_COEF` | core/quality.py:64 | 4 | ✅ | ✅ | 0.8 / 1.0 / 1.2 / 1.5 |
| `DEFAULT_TIER_LABELS` | core/quality.py:72 | — | ✅ | — | 档位中文标签 |
| `ABSOLUTE_QUALITY_MAX` | core/quality.py:84 | 100 | ✅ | ❌（硬上限） | 品质绝对上限，**故意写死**；**无 settings 覆盖旁路**（批82 · Q8 实测：无第二写点、无 settings 键，末端 `min(...)` 无条件生效） |

> **易混提醒**：`AFFINITY_KEYS` 是 **settings 段名**（4 个），**不是**"相性键"6 个——上游盘点文档 §1.3 记作 6 项，本次实测为 4 项，以本节为准（差异见 §8）。
> **易混提醒**：`data/affinity_keys.py` **没有 aliases 表**。真正的别名归并在 `gear_stats.py:584`（`EFFECT_LEGACY_ALIASES`）与 `core/condition_engine.py:96-120`。

### 1.4 阈值 / 默认值表

**通用口径**：每张默认表都配一个 `normalize_*()` **归一函数**——读内容包 `settings.*` 段，逐项清洗/回落默认值；**整段不存在 → 全默认 → 与引入前逐字段一致**。包作者改数值只需写 `settings` 段，不必改框架。

#### 1.4.1 面板预算与怪物缩放

| 常量 | file:line | 内容 | 覆盖段名 | 归一函数 |
|---|---|---|---|---|
| `PANEL_BUDGET_KEY` | core/panel_budget.py:90 | `"panel_budget"` | — | — |
| `DEFAULT_PANEL_BUDGET` | core/panel_budget.py:102 | `{white:7.0, equip:8.0, buff:5.0, equip_stat_mult:1.0}` | `settings.panel_budget` | `normalize_panel_budget` :142（各值下钳 0） |
| `MONSTER_SCALING_KEY` | core/panel_budget.py:91 | `"monster_scaling"` | — | — |
| `DEFAULT_MONSTER_SCALING` | core/panel_budget.py:109 | `{hp_mult:1.0, atk_mult:1.0, def_factor:1.0, def_k:100.0, effect_hp_mult:1.0, effect_atk_mult:1.0}` | `settings.monster_scaling` | `normalize_monster_scaling` :156 |
| `DEFAULT_DEF_K` | core/panel_budget.py:100 | `100.0` | 经 `monster_scaling.def_k` | — |
| `PANEL_AXIS_KEYS` | core/panel_budget.py:97 | `('atk','dfn','hp')` | ❌ | 由 `gear_stats.PANEL_AXIS_STEMS:205` 派生 |

消费处：`assembly/context.py:1874`（monster_scaling）、`:1872`（panel_budget）。

#### 1.4.2 深度打造规则（用户口中的 `craft_rules`）

| 常量 | file:line | 内容 | 覆盖段名 |
|---|---|---|---|
| `DEFAULT_DEEP_CRAFT_RULES` | content/deep_craft_settings.py:110 | **16 键**：material_level_weight / level_rounding / quality_exp_affinity_bonus / quality_level_thresholds / slot_decay / max_per_kind / max_kinds / type_bonus / global_decay / cost_base / cost_per_kind / cost_floor_ratio / interaction / quality_exp_crit / random_stat_count / random_set_affix_count | `settings.deep_craft.craft_rules` |
| `DEEP_CRAFT_RULE_FIELDS` | content/deep_craft_settings.py:155 | 同 16 键的子字段元数据（`FieldMeta`） | — |

消费/校验：`core/deep_craft.py:733`、`:861`；`content/validator.py:2647`。
> **口径**：`craft_rules` = `DEFAULT_DEEP_CRAFT_RULES` + `DEEP_CRAFT_RULE_FIELDS` 两件套；**两者必须同步增删**（元数据缺项 = 编辑器不显示、校验不认）。

#### 1.4.3 淬炼（temper）

| 常量 | file:line | 内容 | 覆盖段名 |
|---|---|---|---|
| `DEFAULT_TEMPER` | data/temper_stats.py:70 | **15 键**：enabled / cap_per_level / total_cap / total_cap_by_level / per_stat_cap_ratio / per_stat_cap / allowed_stats / value_type / value_per_point / cost_per_point / cost_growth / stat_weight / points_per_action / default_level / reset_allowed | `settings.forge.temper`（经 `normalize_temper_config` :181） |
| `TEMPER_VALUE_TYPES` | data/temper_stats.py:55 | `('flat','pct')` | ❌（值域固定） |
| `TEMPER_ROUNDINGS` | data/temper_stats.py:58 | `('floor','round','ceil')` | ❌ |

关键默认值：`cap_per_level=6`、`per_stat_cap_ratio=0.5`、`value_type="flat"`、`points_per_action=1`、`reset_allowed=True`、`total_cap=None`。
> **配额（批82 · Q3 查清）**：`normalize_temper_config`（`data/temper_stats.py:181-223`）只做**逐键净化**（四键互不覆盖），**不决定优先级**；真正的优先链在**消费函数**：`total_cap_of`（`core/temper.py:136-154`）= **`total_cap`（显式绝对值） > `total_cap_by_level[等级]` > `等级 × cap_per_level`**；`per_stat_cap_of`（`core/temper.py:157-167`）= **`per_stat_cap[stat]`（逐属性覆盖） > `floor(total_cap × per_stat_cap_ratio)`**（ratio 缺省 0.5）。默认 `total_cap=None` / `total_cap_by_level={}` / `per_stat_cap={}` → 走「等级×6」与「×0.5」。

#### 1.4.4 粹灵/精华产出（essence）

| 常量 | file:line | 内容 | 覆盖段名 |
|---|---|---|---|
| `DEFAULT_ESSENCE_RATE` | data/temper_stats.py:106 | **15 键**：enabled / v_basis / v_fixed / v_per_level / k1 / k2 / grade_of / beta / color_order / rounding / temper_refund / refund_decay / scope / cap_per_item / essence_currency | `settings.forge.essence_rate`（归一 `normalize_temper_config` 后半段 :228；落地 `content/forge_settings.py:81`） |
| `ESSENCE_V_BASES` | data/temper_stats.py:62 | `('node_materials','item_price','fixed','level_scaled')` | ❌ |
| `ESSENCE_SCOPES` | data/temper_stats.py:65 | `('crafted_equipment','all_equipment')` | ❌ |

关键默认值：`enabled=False`、`v_basis="node_materials"`、`k1=0.35`、`k2=0.5`、`beta=1.2`、`temper_refund=800`、`refund_decay=0.5`、`rounding="floor"`。

#### 1.4.5 特效强度预算（effect_budget）

| 常量 | file:line | 内容 | 覆盖段名 |
|---|---|---|---|
| `EFFECT_BUDGET_KEY` | data/gear_stats.py:858 | `"effect_budget"` | — |
| `DEFAULT_EFFECT_BUDGET` | data/gear_stats.py:894 | `{enabled:False, aggregate:"geometric", cap_equiv_pct:8.0, tier_mult:{normal:1.5,elite:1.0,boss:0.625}, gate_mode:"warn", unknown_axis:"warn", report_effective_share:True, axis_weights:{...}}` | `settings.effect_budget`（归一 `normalize_effect_budget` :918） |
| `EFFECT_AGGREGATES` | data/gear_stats.py:861 | `('geometric','product','max')` | ❌ |
| `EFFECT_GATE_MODES` | data/gear_stats.py:863 | `('off','warn','red')` | ❌ |
| `EFFECT_UNKNOWN_MODES` | data/gear_stats.py:865 | `('ignore','warn','red')` | ❌ |
| `EFFECT_AXIS_WEIGHTS` | data/gear_stats.py:873 | 6 轴等效权表（cooldown_pct / damage_taken_pct / absorb_hp / healing_received_pct / damage_dealt_pct / action_speed_pct） | ✅ `axis_weights` 逐键覆盖/追加 |
| `DEFAULT_EFFECT_AXES` | data/gear_stats.py:593 | 由 `EFFECT_AXIS_SPECS` 派生的逐轴缺省声明 | — |

> **整段不存在 / `enabled != true` → 聚合器返回 0、gate 静默 → 与引入前逐字段一致**（gear_stats.py:891-893、:921-923）。这是"默认不改变既有行为"的通用设计口径。
> **注意**：`EFFECT_AXIS_WEIGHTS` 里同时出现**特效轴键**（`cooldown_pct` 等）与**旧战斗键**（`absorb_hp`）——权表坐标不是键族，别当重复项清理。

#### 1.4.6 过量治疗（overheal）

| 常量 | file:line | 内容 | 覆盖段名 |
|---|---|---|---|
| `OVERHEAL_KEY` | data/gear_stats.py:1122 | `"overheal"` | — |
| `OVERHEAL_MODES` | data/gear_stats.py:1125 | `('keep','discard')` | ✅ |
| `OVERHEAL_MODE_RESERVED` | data/gear_stats.py:1129 | 保留位（`shield` = **未实现**） | ❌ |
| `DEFAULT_OVERHEAL` | data/gear_stats.py:1136 | `{enabled:False, mode:"discard", cap_pct:None, cap_flat:None}` | `settings.overheal` |

**D4 裁决明确**：`overheal` **不是特效轴**（它是 E5 布尔开关），故**不**登记进 `EFFECT_AXIS_SPECS`（gear_stats.py:69-70）。别因为"它看起来像个轴"而搬进去。

#### 1.4.7 炼金路径与拒绝码

| 常量 | file:line | 值 | 覆盖段名 |
|---|---|---|---|
| `MODE_FULL` / `MODE_SIMPLE` / `MODE_OFF` | core/craft_paths.py:72 / :73 / :74 | `"full"` / `"simple"` / `"off"` | `settings.*.mode` |
| `MODE_LABELS` | core/craft_paths.py:76 | 模式中文标签 | ❌ |
| `CRAFT_PATHS` | core/craft_paths.py:88 | `('synthesis','alchemy','deep_alchemy','forge')` | ❌ |
| `REJECT_*` 拒绝码 | core/deep_craft.py:85-94 | no_blueprint / not_learned / no_materials / main_material / kinds / per_kind / cost_over / cost_under / level_band / draw | ❌ |

> **注意**：`CRAFT_PATHS` 是**四条**（含 `forge`），而 `MODE_*` 只描述"炼金三层漏斗"的开关——**两者维度不同**，别把 `forge` 也套 `mode`（锻造无随机、无需漏斗开关）。

### 1.5 模块目录与推荐组合

| 常量 | file:line | 数量 | 唯一源 | 可被包覆盖 | 改它的影响面 |
|---|---|---|---|---|---|
| `FRAMEWORK_MODULE_CATALOG` | content/module_catalog.py:68 | **36 条目** | ✅ | ❌（框架能力全集，包不能改目录） | 编辑器模块面板/勾选树；**一号原则：框架设计了但未实装的也让作者看得见** |
| `ModuleCatalogEntry` | content/module_catalog.py:31（`@dataclass` :30） | 9 字段 | ✅ | ❌ | module/label/purpose/entry_type/requires/implemented/settings_section/overlap_with/overlap_note |
| `CATALOG_BY_MODULE` | content/module_catalog.py:154 | 36 | ✅（派生） | ❌ | module→entry 索引 |
| `FRAMEWORK_MODULE_PRESETS` | content/module_presets.py:58 | **3** | ✅ | ✅ 同 id 整体覆盖；可追加；`manifest.json.module_presets_disable` 可关闭（:24） | 生效 = **框架默认 ∪ 包声明** |

**三个推荐组合**（实测内容）：

| id | label | 受众 | modules |
|---|---|---|---|
| `basic_rpg` | 基础 RPG 包 | 第一次做可玩内容的新作者 | items, equipment, skills, skill_chains, effects, statuses, enemies, maps, quest, npc, shop, stats |
| `life_adventure` | 生活冒险包 | 做采集/炼金/打造/钓鱼等生活线 | items, equipment, recipe, forge, fishing, farming, gathering, proficiency, runes, assistant, contest |
| `story_exploration` | 故事探索包 | 主线/任务/NPC/地图叙事 | quest, quest_board, npc, maps, enemies, dungeon, items, skills, effects, statuses, achievements, codex |

> **实测提示**：36 个目录条目的 `implemented` 字段**当前全为 `True`**（本次 `python3` 实测）。因此"让作者看得见未实装能力"目前靠的是**目录条目的存在**而非 `implemented=False` 标记；若将来新增未实装模块，请用 `implemented=False` 区分（该字段类型与用途见 module_catalog.py:19-52）。
> **重叠登记（批82 · B2 更正）**：`slot_defs`（settings 段）vs `slots.json`（模块）**不是"功能重叠"**，而是**不同数据空间**——`settings.slot_defs` = 运行时装备**部位表**，`slots.json` = **珠插槽 / 镶嵌孔位**（`core/jewel.py` 消费）；二者名字相近易误写，故框架在 `overlap_with` / `overlap_note` 显式登记并给黄提示（`module_catalog.py`），文案为「不同数据空间 / 各自单一源」。**这是"合理并存"，不是待清理的重复**。

### 1.6 常量"安全改法"速查（改它的影响面）

| 你想做的事 | 正确做法 | 禁止 |
|---|---|---|
| 调某个特效轴的数值范围 | 在包里写 `settings.effect_axes.<axis>.{min,max}` | 改 `EFFECT_AXIS_SPECS` 的 `min/max` 字面量（引擎不写死是本框架口径） |
| 新增一条特效轴 | 改 `EFFECT_AXIS_SPECS`（唯一源），并补 `consumer` + `consumer_note` + `display` + `legacy_alias`；派生表自动跟随 | 手改 `GEAR_EFFECT_KEYS` / `DEFAULT_EFFECT_AXES` / `GEAR_LABELS_ZH`（会被 import 覆盖） |
| 新增一个装备词条键（非特效轴） | 判断归属键族 → 加入对应 `GEAR_*_KEYS`，并补 `GEAR_LABELS_ZH` / `GEAR_HELP_ZH` | 只加键不加 label/help（编辑器显示裸键名） |
| 新增一个战斗桥键 | 加进 `COMBAT_TO_COMBATANT`（含封顶值），**键名常量落 data 层** | 在 core/commands 里写死字面量 |
| 调默认阈值 | 在包里写对应 `settings` 段 | 改 `DEFAULT_*` 常量（会让"未配置 = 既有行为"失效） |
| 加一条烧瓶/相性池类型 | 改 `data/affinity_keys.py` 的 `POOL_KINDS`/`REACTION_KINDS` | 在 core/validator 两处各写一套枚举 |
| 加一个模块目录条目 | 改 `FRAMEWORK_MODULE_CATALOG`；若 `_KIND_FOR_MODULE` 也需登记则**两处同步**（`modules_raw` 双处登记，见 §2.7） | 只改一处（只有单向自检 `loader.py:205-233`） |
| 废弃一条轴 | 加进 `DEPRECATED_EFFECT_AXES` 并写替代轴与依据 | 直接从 `EFFECT_AXIS_SPECS` 删除（旧包会失去提示、静默失效） |

## 2. 数据结构手册

### 2.0 先分清"契约类型"与"运行期形态"（本章最大的坑）

框架里**同一个名字有两套形状**，混用会写出"类型对但运行期拿不到字段"的代码。

| 形态 | 是什么 | 谁在用 | 典型 |
|---|---|---|---|
| **契约 dataclass**（`frozen=True`） | "契约 spec 类型"，用于分层契约与 `U3 不可变`声明 | 存档 codec、部分引擎签名 | `Player`、`ItemInstance`、`CombatantSnapshot`、`StatusInstance` |
| **运行期 dict** | 引擎实际读写、公式直读的活对象 | 战斗、效果、marks、ctx | combatant dict、状态实例 dict、印记实例 dict、`ctx` |

**关键事实（已核）**：`CombatantSnapshot` / `BattleSnapshot` / `StatusInstance` **与运行期 dict 结构不同**，且文件头已**自登记为"双轨未收敛"**（`data/battle.py:13-20`、`data/status.py:7-12`）。**它们不是文档笔误，是有意保留的契约 spec**——别按它们去 grep 运行期字段，也别"顺手统一"（会动到未收敛的设计决策，属待裁决项）。

**双轨总表**：

| 对象 | 契约类型 | 运行期形态 | 双轨状态 | 定义 file:line |
|---|---|---|---|---|
| 玩家主档 | `Player`（dataclass，23 字段） | 同名 dataclass（真运行期对象） | ✅ 已收敛 | data/player.py:79-113 |
| 玩家属性 | `PlayerAttributes`（4 字段） | 同名 dataclass | ✅ 已收敛 | data/player.py:23-53 |
| 装备槽 | `EquipmentSlot`（6 字段） | 同名 dataclass（**但适配层可传 dict**，见 `repository.py:157-159`） | ⚠️ 半收敛 | data/player.py:57-75 |
| 物品实例 | `ItemInstance`（20 字段） | 同名 dataclass（**展示层兼容 dict 行**，见 §3.1） | ⚠️ 半收敛 | data/item.py:40-102 |
| 战斗参战者 | `CombatantSnapshot`（7 字段） | **dict**（默认 18 键 + 动态透传 + 运行期追加） | ❌ 未收敛（自登记 data/battle.py:13-20） | data/battle.py:33-42 vs core/battle.py:317-322 |
| 战斗快照顶层 | `BattleSnapshot`（13 字段） | **dict**（≥30 顶层键） | ❌ 未收敛 | data/battle.py:46-75 vs core/battle.py:2332-2433 |
| 状态实例 | `StatusInstance`（7 字段）+ `Duration`（2 字段） | **dict**（14 键；`decay` 是 str 非 float） | ❌ 未收敛（自登记 data/status.py:7-12） | data/status.py:25-45 vs core/effects.py:749-762 |
| 印记实例 | 无 dataclass | **dict**（6 键，权威键元组 `_MARK_INSTANCE_KEYS`） | ✅ dict 即契约 | core/marks.py:53-60 |

### 2.1 `Player`（`qbot_rpg/data/player.py:79-113`，`@dataclass(frozen=True)`，**23 字段**）

**这是什么**：玩家主档。`qid` = 玩家数据 key = QQ 号（**全局，跨群/私聊同一角色**；群号只记在 `last_seen_group`，**绝不是存档键**）。
**什么时候用**：读玩家状态、写包自持指令要落档的数据。
**谁负责**：框架 `data` 层定义字段；**包自持代码不得直接改 `Player`**——落档走 `storage.save_player`，运行期改 `ctx`（见 §2.6）。

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 含义 / 别名 / 兼容 |
|---|---|---|---|---|---|
| `qid` | `PlayerQID`(=str) | **必填** | — | player.py:86 | 存档主键；**列名 `player_qid`**（schema.py:49） |
| `name` | str | **必填** | — | player.py:87 | 角色名（≤20 字，过滤控制字符）；**列名 `nickname`**（schema.py:50） |
| `job_id` | str | 可选 | `"novice"` | player.py:88 | **无独立列**：写时折入 `persistent_state["job_id"]`（repository.py:150）；读时 `pop` 回字段（repository.py:316） |
| `level` | int | 可选 | `1` | player.py:89 | |
| `exp` | int | 可选 | `0` | player.py:90 | |
| `hp` | int | 可选 | `1` | player.py:91 | `0` 合法（死亡）；读档仅 `None` 兜底（repository.py:324-325，P2-3 修复） |
| `mp` | int | 可选 | `1` | player.py:92 | 同上 |
| `currencies` | `Dict[str,int]` | 可选 | `{}` | player.py:93 | 货币 ID→数量 |
| `inventory` | `Tuple[ItemInstance,...]` | 可选 | `()` | player.py:94 | 背包实例数组（tuple 冻结语义）；落档为 JSON list |
| `equipment` | `Dict[str,EquipmentSlot]` | 可选 | `{}` | player.py:95 | 槽位→槽实例 |
| `attributes` | `PlayerAttributes` | 可选 | `PlayerAttributes()` | player.py:96 | **列名 `stats`**（schema.py:57） |
| `achievement_state` | `Any`（旧 tuple / 新 dict） | 可选 | `{}` | player.py:102 | ⚠️ **兼容键双形态**：docstring 声明新形态 `{unlocked,repeat_count}`，但 codec 仍按 tuple/list 处理（见下"改动风险"） |
| `title_state` | `Dict[str,str]` | 可选 | `{}` | player.py:103 | 当前佩戴称号 |
| `persistent_state` | `Dict[str,object]` | 可选 | `{}` | player.py:104 | **自由 dict**：checkin / shop / resource / time / dummy_log / rune_sockets / 成就等落此 |
| `longline_counters` | `Dict[str,int]` | 可选 | `{}` | player.py:105 | 长线计数（**只增不减**） |
| `reputation_state` | `Dict[str,int]` | 可选 | `{}` | player.py:106 | 声望（按板独立） |
| `codex_state` | `Dict[str,object]` | 可选 | `{}` | player.py:107 | 图鉴解锁+完成度 |
| `content_pack_id` | str | 可选 | `""` | player.py:108 | |
| `content_pack_version` | str | 可选 | `""` | player.py:109 | |
| `schema_version` | int | 可选 | `4` | player.py:110 | 注释"当前 5，默认 4 兼容"；DB 列默认 4（schema.py:67） |
| `last_seen_group` | `Optional[str]` | 可选 | `None` | player.py:111 | **仅来源记录，非存档键** |
| `created_at` | str | 可选 | `""` | player.py:112 | ISO-8601 UTC |
| `last_active_at` | str | 可选 | `""` | player.py:113 | ISO-8601 UTC（30 天回收判据） |

**序列化 codec**：写 `player_to_row`（`storage/repository.py:144-182`，**22 列**）；读 `row_to_player`（`repository.py:289-343`）；建表 `storage/schema.py:47-70`。

**改动风险**：
- **加字段必须三处同步**：dataclass（player.py）+ 写 codec（player_to_row）+ 读 codec（row_to_player）+ 建表列（schema.py）。漏写 codec = 字段落不了档（静默）或读不回默认值。
- 列名与字段名**不同名**是历史设计（`player_qid`/`nickname`/`stats`），**不要"修正"成同名列**——等于改存档格式。
- `job_id` 折进 `persistent_state`：直接读写 `persistent_state["job_id"]` 会让你绕过字段语义。
- `achievement_state` **字段散落 3 处、单一源缺失**（见 §6）：`player_to_row` 仍 `list(...)`（repository.py:174）、`row_to_player` 仍 `tuple(...)`（repository.py:331）、DB 列默认 `'[]'`（schema.py:63），而运行期真值挂在 `ctx["achievement_state"]`→`persistent_state`（`assembly/context.py:1522-1524`）。**Player 字段已退化为旧档兼容读**。改这里前先读 §6 A 组。

### 2.2 `PlayerAttributes`（`player.py:23-53`，4 字段，全部有默认）

**这是什么**：玩家属性三层结构，**与属性计算管线一一对应**。
**管线**（player.py:30-31）：`白值 + bonus.flat → 基础合计 ×(1+bonus.pct) → 加成后属性 ×(1+temp.pct) + temp.flat + cond → 最终属性`。

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 含义 |
|---|---|---|---|---|---|
| `base` | `Dict[str,float]` | 可选 | `{}` | player.py:34 | ① 白值层，永久落档 |
| `bonus` | `Dict[str,Dict[str,float]]` | 可选 | `{"flat":{},"pct":{}}` | player.py:35 | ② 加成层，**子键固定 `flat`/`pct`**；便捷法 `flat_bonus`/`pct_bonus`（:39/:43） |
| `temp` | `Dict[str,Dict[str,float]]` | 可选 | `{"pct":{},"flat":{}}` | player.py:36 | ③ 临时层（战斗 buff，结束清空），子键固定 `pct`/`flat`；便捷法 `temp_pct`/`temp_flat`（:47/:51） |
| `cond` | `Dict[str,float]` | 可选 | `{}` | player.py:37 | 条件加成（flat 终值桶，**防无限叠乘**） |

读侧归一 `_attrs_from_dict`（`repository.py:264-276`，缺子键补空）。
**改动风险**：子键顺序表里 `bonus` 是 `flat,pct` 而 `temp` 是 `pct,flat`（字面顺序不同但语义无别）——**别当不一致去"统一"**；真正的风险是新增第四层（会改变管线契约，属【稳定契约】）。

### 2.3 `EquipmentSlot`（`player.py:57-75`，**6 字段**）

**这是什么**：装备槽实例（**槽位 → 槽对象**），记录"这个槽穿的是哪一件"。
**唯一设计要点**：`uid` **回指 `ItemInstance.uid`**，不是自生成 id。

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 含义 / 兼容 |
|---|---|---|---|---|---|
| `item_id` | `ItemID`(=str) | **必填** | — | player.py:70 | |
| `name` | str | **必填** | — | player.py:71 | 冗余名称（MIG-3） |
| `slot_level` | int | 可选 | `0` | player.py:72 | 强化等级 |
| `locked` | bool | 可选 | `False` | player.py:73 | 强化锁定概率持久化 |
| `gems` | `Tuple[str,...]` | 可选 | `()` | player.py:74 | 镶嵌宝石 ID（tuple 冻结语义） |
| `uid` | str | 可选 | `""`（`compare=False`） | player.py:75 | **回指 `ItemInstance.uid`**；空串 = 旧档 → 回退 `item_id` 首匹配（注释 :64-67） |

读 codec `_equip_from_dict`（`repository.py:246-255`）。
**改动风险**：`uid` 的 `compare=False` 是**故意的**——保持既有 `==` 结构等价语义，实例同一性判定走显式 uid 比较。**别把 `compare=False` 当 bug 删掉**（会让旧测试的相等性语义突变）。

### 2.4 `ItemInstance`（`qbot_rpg/data/item.py:40-102`，`@dataclass(frozen=True)`，**20 字段**）

**这是什么**：玩家持有的物品实例（运行期实例，**非内容包配置 `ItemDef`**）。
**什么时候用**：读写背包/装备/商店/打造产物的行。
**谁负责**：框架定义字段；包自持代码新增"实例级数据"应优先走 `stats_bonus` / `persistent_state`，**加字段需走 §4.3 清单**。

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 含义 / 兼容 |
|---|---|---|---|---|---|
| `item_id` | `ItemID` | **必填** | — | item.py:53 | 引用键；读侧缺省 `""`（repository.py:214） |
| `name` | str | **必填** | — | item.py:54 | 冗余名称（MIG-3，换包后旧条目仍可按旧名显示） |
| `count` | int | **必填** | — | item.py:55 | 堆叠数量；读侧缺省 1 |
| `quality` | str | **必填** | — | item.py:56 | 四档枚举；读侧缺省 `"normal"` |
| `bound` | bool | **必填** | — | item.py:57 | 绑定不可赠送/掉落；读侧缺省 False |
| `stack_max` | int | 可选 | `99` | item.py:58 | 堆叠上限；读侧缺省 99（批40 补读漏字段，repository.py:222） |
| `slot` | `Optional[str]` | 可选 | `None` | item.py:59 | 装备槽位（**`/装备` 靠它判定可穿戴**） |
| `stats_bonus` | `Dict[str,float]` | 可选 | `{}` | item.py:60 | 装备词条 / 虚拟属性键（键空间见 §1.1） |
| `traits` | `Tuple[str,...]` | 可选 | `()` | item.py:61 | 特性（tuple 冻结语义） |
| `cooldown_until` | `Optional[str]` | 可选 | `None` | item.py:62 | 冷却计时（ISO-8601 UTC） |
| `enhance_level` | int | 可选 | `0` | item.py:63 | 强化 +N；穿装同步 `EquipmentSlot.slot_level` |
| `uid` | str | 可选 | `""`（`compare=False`） | item.py:65 | **实例落档唯一键**；`__post_init__` 空则 `new_item_uid()`（item.py:95-102） |
| `affinities` | `Dict[str,float]` | 可选 | `{}` | item.py:69 | 批42 打造相性结算值 |
| `set_affixes` | `Tuple[str,...]` | 可选 | `()` | item.py:71 | 套装词条 |
| `passives` | `Tuple[str,...]` | 可选 | `()` | item.py:73 | 装备被动 id |
| `quality_level` | int | 可选 | `0` | item.py:76 | 品质等级 1~10；**0 = 旧档桥接** |
| `enhance_affixes` | `Tuple[str,...]` | 可选 | `()` | item.py:79 | 强化特殊词条键序列 |
| `required_level` | int | 可选 | `0` | item.py:84 | 装备等级（**淬炼上限 `total_cap = 等级 × cap_per_level` 的唯一输入**）；0 = 缺省不可淬炼 |
| `temper_alloc` | `Dict[str,int]` | 可选 | `{}` | item.py:88 | 淬炼分配（**分账于 `enhance_level`**；数值经 `materialize_temper` 物化进 `stats_bonus`） |
| `effect_refs` | `Tuple[str,...]` | 可选 | `()` | item.py:93 | 批61 附加效果/状态引用；`/使用` 时由 `use_commands._use_consumable` 分派 |

**读写 codec**：读 `_item_from_dict`（`repository.py:196-243`，**20 字段全读**）；写 `dataclasses.asdict`（`repository.py:154-157` 经 `_asdict_row`，:167）。
**改动风险**：见 §3（构造点是本章最硬的一条警告）。

### 2.5 combatant 快照（战斗参战者）

**这是什么**：一场战斗里"我方/敌方单位"的活对象。**运行期是 dict，不是 dataclass**。
**什么时候用**：写公式、写效果触发、看扩展可见变量。
**谁负责**：框架 `core/battle.py` / `commands/battle_launch_commands.py` / `core/pvp.py` 构造；包自持代码**只能读**，不得改构造点。

#### 2.5.1 契约 spec 类型（**不是运行期形态**）

`CombatantSnapshot`（`data/battle.py:33-42`，7 字段，全必填）：`max_hp` :36、`hp` :37、`atk` :38、`dfn` :39、`mag` :40、`spd` :41、`name` :42。
`BattleSnapshot`（`data/battle.py:46-75`，13 字段）：`session_type` :59、`player`/`enemy` :60-61、`turn` :62、`combo_state` :63、`ai_state` :64、`status_state` :65、`marks_state` :66、`resist_table` :67、`effect_triggers` :68、`effect_cooldowns` :69、`formula_state` :70（**注释要求必含 `random_seed`**）、`lost_pending` :75。
**⚠️ 文件头 `data/battle.py:13-20` 明示双轨未收敛**。

#### 2.5.2 运行期 combatant dict —— 基础默认键（`_DEFAULT_STATS`，`core/battle.py:317-322`，**18 键**）

| 键 | 默认 | 键 | 默认 |
|---|---|---|---|
| `max_hp` | 500 | `foc` | 50 |
| `hp` | 500 | `con` | 50 |
| `max_mp` | 100 | `str` | 50 |
| `mp` | 100 | `int` | 50 |
| `atk` | 50 | `agi` | 50 |
| `dfn` | 50 | `spr` | 50 |
| `mag` | 30 | `lck` | 50 |
| `spd` | 50 | `elem_atk` / `elem_res` | 0 / 0 |
| `name` | `""` | | |

归一时追加/兜底（`_combatant()`，`core/battle.py:2318-2327`）：`max_hp` 缺省 500、`hp` 夹到 ≤`max_hp`、`name` 缺省 `"unit"`、`dead_mark=False`、`skip_turn=False`、`defenses={}`。

#### 2.5.3 运行期 combatant dict —— 开战构造追加键

| 来源 | 固定写入键 | file:line |
|---|---|---|
| 敌方构造 `_enemy_combatant` | `id` / `hp` / `max_hp` / `mp` / `atk` / `dfn` / `mag` / `spd` / `foc` / `lck` / `con` / `agi` / `name` | commands/battle_launch_commands.py:184-196 |
| 敌方**动态透传** | `enemies.json stats` 中**未映射的剩余键原样进 combatant** | :203-208 |
| 敌方战斗词条 | 经 `combatant_updates` 桥入（映射 `COMBAT_TO_COMBATANT:502`） | :212-213 |
| 敌方 `parts` | 有配置时 | :217-219 |
| 玩家构造 `core/pvp._combatant_of` | `id` / `name` / `level` / `hp` / `max_hp` / `mp` / `max_mp` / `atk` / `dfn` / `con` / `mag` / `spd` / `foc` / `int` / `lck` + `attributes.base` 全键 + 装备战斗桥键 | core/pvp.py:155-202 |
| 玩家 launch 侧条件追加 | `job` / `quest_active` / `quest_completed` / `rune_effects` / `owned_effect_ids`（值源 `gear_stats.py:491`） | battle_launch_commands.py:239-256 |
| 运行期派生 | `shield`/`mitigation`/`pv`/`level`/`hit_streak`/`miss_streak`（由 `defenses` 派生，**不落档**） | core/battle.py:937-942 |
| 公式视图 | `marks`/`marks_total`（`MarksManager.formula_view`，`marks.py:421`） | core/battle.py:946 |
| 状态/效果写入 | `defenses`（子弹结构）、`dot_pool` | core/effects.py:1035-1045、:2224-2232 |

`defenses` 子结构（`effects.py:1035-1045`）：`mitigation` `[]`、`shield` `{value,remaining,turns,max}`、`reflect` `{value,pct,active}`、`absorb` `{value,pct,record,active}`、`fatal_immune` `{count,max}`、`non_fatal_immune` `{active,count}`、`guts` `{count,max}`、`immune` `{status,damage,interrupt,all,block_debuff}`、`mount` `{remaining}`。

#### 2.5.4 战斗快照顶层 dict 键（运行期）

定义点 `start`（`core/battle.py:2284` 起，键写入 :2330-2436）+ `to_snapshot`（`core/battle.py:5534-5610`，**本次逐键核**；别名 `snapshot()` :5612-5614）：
`session_type` :2330、`battle_id` :2331、`battle_type` :2332、`is_dummy_battle` :2335、`status` :2341、`rule_version` :2342、`registry_generation` :2347、`action_seq` :2357、`battle_time` :2358、`turn` :2359、`round_phase` :2360、`player`/`enemy` :2361-2362、`action_record` :2363、`result` :2364、`combo_state` :2366、`combo_zeroed_at` :2367、`ai_state` :2368、`lost_pending` :2371、`battle_alchemy_used` :2375、`stats_collector` :2376、`formula_state` :2377、`timestamps` :2378、`status_state` :2380、`marks_state` :2381、`resist_table` :2382、`effect_triggers` :2383、`effect_cooldowns` :2385、`transform_state`（7 字段）:2388-2391、`resource_state` :2394、`battle_season` :2399、`season_event_state` :2402、`combat_position` :2407-2412、`parts_state` :2416、`battle_resources` :2422-2430（段内权威 `battle_alchemy_used` :2428）、`equip_skill_amp`（**仅非空时入快照**）:2436。
`to_snapshot` 追加（**CTB V2 头**）：`schema_version=2` :5557、`rule_version` :5558、`snapshot_id` :5559、`saved_at` :5560、`snapshot_at{boundary,battle_time,action_seq,turn}` :5562-5569、`snapshot_context{mode,map_id,zone}` :5570-5574、`_engine_state` :5575、`_guard_active` :5576、`_death_order` :5577、`ctb_state` :5582-5599、`random_seed` :5601、`rng_state` :5603、`formula_state{random_seed,rng_state}` :5606-5609。

**改动风险**：
- **`turn` 是兼容镜像 = `action_seq`，不参与计算**（注释 `core/battle.py:2357-2359`）。**别当冗余字段删**——外部/旧代码读它。
- **运行期 `turn` 与 `ctx["turn"]` 不同源**（ctx 取自 `battle_session.turn`，`assembly/context.py:1672`）。
- **`battle_alchemy_used` 段内权威是 `battle_resources.battle_alchemy_used`**（注释 :2375-2377）——顶层那份是镜像，**别修成两处都写**。
- combatant 字段**无单一源、≥4 处构造**（见 §6 A 组）。「加一个 combatant 键」必须**同时改构造点**，否则只在部分路径生效。

### 2.6 `registry` / `modules_raw`（`qbot_rpg/content/`）

**这是什么**：一次内容包加载后的"全部 ID → 定义"注册表，以及"各模块原始解析数据"。热重载时整体替换（引用替换即原子）。
**什么时候用**：读内容包定义；包自持代码通过 `ExtContext` 或 `ctx["registry"]` 访问。

#### 2.6.1 `Registry`（`content/registry.py:44-224`）

非 dataclass，`__slots__` 私有存储（registry.py:51-60）：`_pack_id` :52、`_generation` :53、`_tables` :54、`_names` :55、`_modules_raw` :56、`_manifest` :57、`_schema_version` :58、`_lock` :59。
公共只读属性：`pack_id` :94、`generation` :98、`schema_version` :102、`modules_raw` :106、`manifest` :111。
读方法：`resolve(id,kind)` :82、`resolve_name(id)` :86、`all_ids(kind)` :90、`contains(id)` :114；快照 `snapshot()` :122、`restore(snap)` :135、`from_snapshot` :153、`build` :168、`integrity_check` :189。

#### 2.6.2 `RegistrySnapshot`（`registry.py:28-41`，`@dataclass(frozen=True)`，7 字段）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 含义 |
|---|---|---|---|---|---|
| `pack_id` | str | **必填** | — | registry.py:35 | |
| `generation` | int | **必填** | — | registry.py:36 | 世代号（RSM 续战重绑定） |
| `tables` | `Mapping[str, Mapping[str, AnyDef]]` | **必填** | — | registry.py:37 | kind → id → Def |
| `names` | `Mapping[str, str]` | **必填** | — | registry.py:38 | id → 显示名（名称冗余） |
| `modules_raw` | `Mapping[str, object]` | **必填** | — | registry.py:39 | 各模块原始解析数据 |
| `manifest` | `Optional[Manifest]` | 可选 | `None` | registry.py:40 | |
| `schema_version` | `Optional[int]` | 可选 | `None` | registry.py:41 | `build` 时取 `manifest.schema_version` :185 |

#### 2.6.3 `modules_raw` 形状

- **类型**：`Mapping[模块名:str, object]`（顶层 dict，**深拷贝**；registry.py:39/56/106-108，构建 `loader.py:126`）。
- **键来源**：`manifest.modules` 声明顺序去重（`_ordered_declared`，loader.py:80-93，调用点 :101）+ **恒有 `"manifest"` 键**（loader.py:310；`integrity_check` 断言时排除，registry.py:204）。
- **值形态（批82 · Q6 实测全表，36 个 field_meta 模块）**：形态由 `ModuleMeta.entry_type` 决定 ——
  **list（24）**：`achievements, action, ai, checkin, dungeon, effects, enemies, equipment, hidden, items, jobs, maps, marks, npc, proficiency, quest, recipe, runes, shop, skill_chains, skills, slots, statuses, traits`（loader.py:105-115 逐条按 `id` 注册）；
  **map（3）**：`formula, stats, templates`（仅 `stats`/`formula` 走「键=ID」注册 `loader.py:117-120`；**`templates` 同形但不注册**——**属有意**（批83 · NEW-7 确认）：`templates` 的 map 键是**模板名**而非条目 ID，注册进 `tables` 无意义且会污染 ID 空间；由 `context._templates_table` 读 `modules_raw`，见 Q7）；
  **object（9）**：`conditional, editor, enhance, env_event, fishing, forge, log_card, manifest, settings`（**不进注册表 tables**，只留 `modules_raw` 供各引擎 `parse_*` 读取）。
- **已知模块名注册表**：`FIXED_REGISTER_ORDER` = effects/statuses/marks/skill_chains/action（loader.py:46）；`_KIND_FOR_MODULE` = **28 项（批82 · Q7/NEW-5 更正：原写 29）**（loader.py:146-198）：effects、statuses、marks、skill_chains、action、skills、jobs、items、equipment、traits、recipe、proficiency、slots、runes、forge、enhance、fishing、achievements、enemies、maps、dungeon、stats、npc、formula、conditional、shop、quest、checkin。
  - **`catalog − kind` 差集（8）**：`assistant / codex / contest / farming / gathering / quest_board / settings / templates`。其中 `settings`/`templates` 在 field_meta 有登记（`check_manifest_modules_registered` 豁免）；另 **6 个能力标记类条目（assistant/codex/contest/farming/gathering/quest_board）无 loader kind、无 field_meta 校验器** → `check_manifest_modules_registered` 报出这 6 个，**列 NEW-6 待查**（是否可写 manifest 未查清，不猜）。`kind − catalog = ∅`。
- **`ABSOLUTE_QUALITY_MAX`（批82 · Q8）**：`core/quality.py:84` = 100，**无任何 settings 覆盖旁路**（全仓无第二写点、无 settings 键），末端 `min(…, ABSOLUTE_QUALITY_MAX)` 无条件生效——**有意写死**（见 §1、§5 S8）。
- **对照自检**：`check_register_table_consistency`（loader.py:201-216）、`check_manifest_modules_registered`（loader.py:217-234）。

**改动风险**：模块名**双处登记**（`_KIND_FOR_MODULE` loader.py:150-202 与 `FRAMEWORK_MODULE_CATALOG` module_catalog.py:68），**需人工保持一致**，且只有**单向**自检。新增模块必须两处同步（见 §6 A 组 A8）。

#### 2.6.4 相关容器（`content/models.py`）

`Manifest`（models.py:693 起）：`modules: Tuple[str,...]` :698、`raw` :699（默认 `{}`）等。
`Pack`（models.py:728 起，frozen）：`modules` :733（模块名 → parsed JSON）等。

### 2.7 `ctx` 指令上下文 —— **无单一源**（重要）

#### 2.7.1 先分清两个"ctx"

| 对象 | 定义 | 谁收到 | 稳定性 |
|---|---|---|---|
| **`ExtContext`**（`qbot_rpg/ext_api.py:125`） | 内容包扩展 handler 收到的**稳定面**对象（`handler(ctx, parsed)`） | **包自持代码 / E1 扩展** | ✅ **稳定 API**，版本 `EXT_API_VERSION="1"`（ext_api.py:59） |
| **内部 `ctx` dict**（`assembly/context.py:1256` `make_context`） | 框架指令壳的上下文，键极多、四段拼装 | **框架自己的指令函数** | ❌ **非扩展契约**（包不得依赖） |

> **给扩展开发者的第一句话**：**用 `ExtContext`，不要依赖内部 `ctx` dict**。内部 `ctx` 的键没有单一源、会随批次增删。

#### 2.7.2 `ExtContext`（`ext_api.py:125-304`）成员表

构造参数（**仅框架装载层调用**，ext_api.py:146-157）：`pack_id` :149（必填）、`pack_version` :150（默认 `""`）、`ctx` :151（默认 `None`→`{}`）、`parsed` :152（默认 `None`）。

| 成员 | 类型/形状 | 默认 | 定义 file:line | 兼容/备注 |
|---|---|---|---|---|
| `pack_id` | str | `""` | ext_api.py:160-163 | |
| `pack_version` | str | `""` | :165-168 | |
| `player_id` | str | `""` | :170-174 | **兼容键**：`qq_id` or `qid` or `user_id` |
| `group_id` | str | `""` | :176-178 | |
| `user_id` | str | `""` | :180-182 | |
| `channel` | str | `""` | :184-186 | |
| `message` | str | `""` | :188-190 | |
| `registered` | bool | `False` | :192-194 | |
| `is_gm` | bool | `False` | :196-198 | |
| `player` | `Optional[Mapping]` | `None` | :201-204 | 只读快照（`dataclasses.asdict` 深拷贝 :84-100） |
| `settings` | Mapping | `{}` | :206-209 | 只读映射 |
| `templates` | Mapping | `DEFAULT_TEMPLATES` | :211-215 | 本包覆盖表 |
| `parsed` | `Any`（`ParsedCommand`） | `None` | :217-220 | |
| `command` | str（派生） | `""` | :222-225 | = `parsed.command` |
| `args` | `tuple[str,...]`（派生） | `()` | :227-236 | |
| `args_text` | str（派生） | `""` | :238-241 | 空格连接 |
| `registry` | Any | `None` | :243-245 | **不承诺稳定** |
| `repo` | Any | `None` | :247-249 | |
| `db` | Any（派生） | `None` | :251-254 | = `repo.db` |
| `tpl(key,data)` | 方法→str | — | :257-259 | 带本包覆盖 |
| `rng` | `random.Random`（派生） | — | :261-264 | 按（包,玩家）定种 |
| `log` | Logger（派生） | — | :266-269 | `content.ext.<pack_id>` |
| `get_state`/`set_state`/`patch_state`/`clear_state` | async 方法 | — | :283/:291/:296/:301 | 仅本包格子（`player_pack_state`） |

`__all__`（ext_api.py:42-56）；`parsed` 原对象字段见 `commands/parsers.py:249-294`。

#### 2.7.3 内部 `ctx` dict —— **明确标注：无单一源**

**为什么说"无单一源"**（三条硬证据，本次实测）：
1. **四段按代码位置切分，不按数据结构**：基础段 `assembly/context.py:1295-1373` / 注册态 `:1398-1584` / 未注册态 `:1586-1639` / 注册无关 `:1642-2034`。段与段之间没有类型或 schema 声明。
2. **重复注入 52 处**：本次对 `make_context` 做 AST 解析，发现 **52 个键被赋值 ≥2 次**（`battle_engine` 4 次；`items` 3 次；`name`/`skills`/`npcs`/`in_battle`/`rng`/`quests` 等 2 次）。**后写覆盖先写**，读序即语义。
3. **存在动态键注入**：`ctx[_key] = ...`（`context.py:1835`、`:1837`，`_key` 由 maps/dungeons/enemies 派生）——**连键名都无法静态枚举**。

**本次实测键数（批82 · Q1 定区间口径）**：AST 可静态识别 **128 个不同字面量键**（共 183 次赋值）。上游盘点估"约 170 键"，差异来自动态注入 + 模块表注入（随包模块数）+ 注册态闭包挂载。**精确总数随「包 / 注册态」浮动 ⇒ 用区间口径**（`make_context` + `len(ctx)` 实测）：

| 包 | 注册态 | 未注册态 | 仅注册态多出 |
|---|---|---|---|
| `content/test_demo` | 162 | 134 | 28 |
| `content/veinborn` | 166 | 138 | 28 |
| `content/blank` / `zz_craft_demo` | 162 / 165 | 134 / 137 | 28 |
| **区间（现行 9 包）** | **162~166** | **134~138** | **28（恒定）** |

> 可复现命令：`build_pack_deps(pack)` → `save_player` → `make_context`（注册玩家）→ `len(ctx)`；`only_reg=28` 恒定。**不要写死单一数字**（随包内模块数变化）。**3 个键框架内无生产消费方**（`monster_pool`/`shop_engine`/`worn_refs`）——登记为**结构性缺口 / 准死键**（Q2 / NEW-9，待收敛批处置，勿单删）。

**3 个零消费 `ctx` 键（逐键标注 · 批83 · Q2/NEW-9 落地）**

复核口径：框架内**仅注入、无生产读取**——全仓 `grep` 三个键名，命中只有「注入点 + `tests/unit/test_assembly_context.py` 断言（:218/:271/:452）」；**`content/**/ext/**` 包自持代码零命中**（唯一 ext 包 `content/zz_probe_ext/ext/` 不读三键）。**本次不删键**（先确认无包依赖；包经 `ExtContext` 读 ctx 的能力使"包外读取"无法静态穷举，故只标注 + 登记）。

| ctx 键 | 注入点 `file:line` | 注册态 | 现状标注 | 处置 |
|---|---|---|---|---|
| `monster_pool` | `assembly/context.py:1670`（`_monster_pool(deps.game_world, ctx.get("location"))`；未注入/未实装 → `[]`） | 有 | **当前无框架消费方**（同名 `GameWorld.monster_pool` 是**世界对象的 API**，不是本 ctx 键读点） | 登记待收敛（**不删**） |
| `shop_engine` | `assembly/context.py:1348`（引擎注入位字面 `None`） | 有（**恒 `None`**） | **恒 None · 准死键 · 待收敛**——消费口径已被 `shops` / `current_shop_ref` 取代（`core/shop.py`）；框架零读取 | 登记待收敛（**不删**） |
| `worn_refs` | 注册态 `:1449`（`_worn_refs(player.equipment)`）/ 未注册态 `:1634`（`{}`） | 有 | **当前无框架消费方**（`core/equipment.py:681` 的 `_worn_refs` 是 `EquipmentEngine` **方法**/进程态缓存，读写 `player` 自身字段，**不读** `ctx["worn_refs"]`） | 登记待收敛（**不删**） |

> 若将来确有包自持代码经 ctx 读这三键，则改判为「**仅供包自持代码经 ctx 读取**」，仍需按 S20/`ExtContext` 口径收敛为扩展面。见 `docs/矛盾与待裁决登记.md` NEW-9。


**字段分组的"现行依据"**（= 代码怎么分的，不是设计文档写的）：

| 段 | 分界依据 | file:line | 段内主题分组（示例） |
|---|---|---|---|
| ② 基础段 | "无论是否注册都注入" | context.py:1295-1373 | 身份（`registered`/`player`/`qq_id`/`qid`/`is_gm`）、事件透传（`group_id`/`user_id`/`message`/`channel`/`group_name`/`per_channel`/`to`）、引擎句柄（`quest_engine`/`shop_engine`/`checkin_engine`/`battle_engine`）、注册表（`registry`/`templates`/`repo`/`session_mgr`/`items`/`recipe`/`traits`/`runes`/`forge`/`enhance`/`fishing`）、结算暂存（`battle_rewards`/`battle_hint`/`battle_status_changes`）、hook 位（`resolve_player_name`/`same_group`） |
| ③ 注册态段 | `registered=True`（`player is not None`） | context.py:1398-1584 | 玩家标量（`name`/`job_id`/`level`/`exp`/`hp`/`mp`/`job_name`/`location`/`title`）、属性（`stats`/`attributes`/`attr_final`/`exp_next`/`level_cap`）、背包/装备（`inventory`/`inventory_items`/`equipment`/`worn_refs`）、持久段可变引用（`longline_counters`/`currencies`/`title_state`/`reputation_state`/`codex_state`/`achievement_state`）、生活线（`farm_plots`/`helpers`/`proficiency`/`forge_preview`/`forged`/`fish_state`）、技能符文（`skills`/`skill_slots*`/`set_*`/`equip_skills`/`rune_sockets`）、会话（`players`/`active_sessions`/`dialog_session`） |
| ④ 未注册态段 | `registered=False`，同名的**安全空值** | context.py:1586-1639 | 与 ③ 同名键给 `None`/`{}`/`[]`/`set()`；**不含** ③ 的 `weak_until`/`discovered_maps`/`farm_plots`/`proficiency`/`pvp_*`/`skill_slots*`/`rune_sockets`/`max_hp`/`max_mp` 等（列表见上游盘点 §5.2(c)，本次抽查一致） |
| ⑤ 注册无关段 | 世界/会话/环境/确定性源 | context.py:1642-2034 | 世界（`game_world`/`map_def`/`monster_pool`/`npcs`/`items`/`effect_table`/`quests`/`shops`/`checkin_tables`/`maps`/`dungeons`/`enemies`）、战斗（`battle_session`/`target`/`in_battle`/`battle_engine`/`battle_snapshot`）、环境（`now`/`today`/`season`/`period`/`weather`）、确定性（`rng`/`_rng_initial_state`）、结算（`battle_reward_fn`）、条件段（`panel_budget`/`monster_scaling`/`effect_axes`/`slots`/`equip_engine`/`equipment_offhand`）、背包 hook（`add_item`/`remove_item`/`count_item`/`inventory`/`add_item_denied`） |

**改动风险**：
- **未注册态缺键**：③ 有而 ④ 没有的键，在未注册玩家上**不存在**——**必须 `ctx.get` 兜底**（上游盘点 §5.2(c) 有完整列表）。
- **条件段不存在即不改键集**：`equipment_offhand`/`panel_budget`/`monster_scaling`/`effect_axes`/`slots`/`equip_engine` 只在 settings 有时注入（context.py:1867-1897）。别假设它们恒在。
- **重复注入 = 后写覆盖**：`items`（:1341 vs :1777，后者还合并 equipment 表）、`skills`（:1546 vs :1655）、`battle_engine`（:1324 vs :1687/:1749）、`count_item`/`remove_item`（:1855 vs :2029/:2030 战斗中覆写）——**改注入点必须确认覆盖顺序**。
- **不要为包新增 `ctx` 键当作扩展契约**：内部 ctx 非契约，包应走 `ExtContext` + `set_state`。

### 2.8 状态实例与印记实例

#### 2.8.1 契约 spec 类型（**不是运行期形态**）

`Duration`（`data/status.py:25-29`，2 字段）：`turns` :28、`charges` :29（**双形**）。
`StatusInstance`（`data/status.py:33-45`，7 字段全必填）：`status_id` :39、`name` :40、`level` :41、`stacks` :42、`duration` :43、`decay` :44（**⚠️ float，与运行期 str 不一致**）、`source` :45。
文件头 `data/status.py:7-12` 自登记双轨未收敛。

#### 2.8.2 运行期状态实例 dict（`core/effects.py`）—— **唯一构造源 `_new_instance`（`effects.py:735-763`）**

| 键 | 形状 | 必填? | 默认 | 定义 file:line | 含义 |
|---|---|---|---|---|---|
| `status_id` | str | **必填** | — | effects.py:749 | |
| `name` | str | **必填** | — | :750 | |
| `category` | str | 可选 | `"other"` | :751（写点 :781） | dispel 寻址 |
| `level` | int | 可选 | `1` | :752 | |
| `stacks` | int | 可选 | `1` | :753 | |
| `value` | int | **必填** | — | :754 | 衰减主体数值（halve/decrement 作用对象） |
| `turns` | int | **必填** | — | :755 | 剩余行动数 |
| `charges` | int | **必填** | — | :756 | 剩余触发次数 |
| `decay` | **str** | **必填** | — | :757 | 取 `raw.decay`，缺省 `"none"`（:546）；**与 spec dataclass 的 float 不一致** |
| `decay_subject` | str | **必填** | — | :758 | 缺省 `"carrier"`（:547） |
| `source` | str | **必填** | — | :759 | |
| `immune_uses` | int | 可选 | `0` | :760 | |
| `trigger_halve` | bool | 可选 | `False` | :761 | D4 trigger 衰减 |
| `_uid` | str（**内部派生**） | **必填** | `self._next_uid()` | :762 | 内部实例身份，比对 :318 |

运行期另可被写：`name`（DOT 展示名覆写 :2232）、`part_break_per_tick`（:2235）。
**DOT 池实例 shape 不同**（`effects.py:2224-2232`）：容器 `dot_pool`（`{status_id: inst}`）:2224；`status_id`/`value`/`tick`/`turns`/`source` :2225-2226、`name`（条件）:2229、`part_break_per_tick`（条件）:2232。
**改动风险**：`decay` 的类型分叉（spec=float / 运行期=str）**是已登记的双轨**，不是待修 bug；直接给 `effects` 灌 `StatusInstance` 会坏（status.py:11-12 明写"收敛前禁止"）。

#### 2.8.3 印记实例 dict（`core/marks.py`）—— 权威键元组 `_MARK_INSTANCE_KEYS`（`marks.py:53-60`）

| 键 | 形状 | 必填? | 默认 | 定义 file:line | 含义 |
|---|---|---|---|---|---|
| `mark_id` | str | **必填** | — | marks.py:259 | 定义引用键 |
| `name` | str | **必填** | 回退 `mark_id` | :260（`_def_name` :208-212） | 冗余名（热重载降级） |
| `count` | int | **必填** | 1，夹到 `max_stack` | :261 | 叠加/饱和减法 :255、:288-294 |
| `applier` | str | **必填** | `"player"`（None→默认） | :262 | D-05 |
| `polarity` | str | **必填** | `"positive"` | :263（`polarity_of` :226-232） | 枚举 `POLARITIES`（:50） |
| `remaining_turns` | int | 可选 | **仅 `duration="turns:N"` 时写入** | :265-271 | 生命周期 tick :323-339 |

容器形状：`marks_state = {"player": [实例], "enemy": [实例]}`（`BATTLE_SIDES` :47；构造 :166-177；快照 :434-459）。
**改动风险**：`remaining_turns` 是**条件存在**的键——代码必须 `inst.get("remaining_turns")`，不能假设恒在。

## 3. 实例生命周期：`ItemInstance` 从构造到落档

**为什么单开一章**：`ItemInstance` 是本框架里**构造点最多、最容易静默丢字段**的数据结构。frozen dataclass 一旦构造完成，字段就定型；**新增字段若漏改任一构造点，该字段会在那条路径上静默变成默认值**——不报错、不告警，只是"有时有、有时没有"。

### 3.1 构造点清单（**含"漏一处即丢字段"警告**）

| # | 构造点 | 性质 | 带过字段数 | 漏带字段 | file:line |
|---|---|---|---|---|---|
| 1 | `ItemInstance.__post_init__` | **uid 自动补发**（唯一生成口径） | — | — | data/item.py:95-102 |
| 2 | `_item_from_dict` | **读档 codec（权威、20/20）** | **20** | 无 | storage/repository.py:213-243 |
| 3 | `_new_default_instance` | 商店购买默认实例 | 6 | affinities / set_affixes / passives / quality_level / enhance_affixes / required_level / temper_alloc / effect_refs（全部取默认）| commands/shop_tx.py:168-182 |
| 4 | `_ctx_inventory_to_player` 内联构造 | **ctx（dict 行）→ Player 归一** | **18** | ⚠️ `stack_max`、`cooldown_until` | assembly/runner.py:720-754 |
| 5 | `/装备` dict→实例归一 | **展示层 dict 行 → 引擎实例** | **17** | ⚠️ `stack_max`、`cooldown_until`、**`effect_refs`** | commands/basic_commands.py:1567-1597 |
| 6 | `equipment.py` 回包行重建（带 uid） | 装备引擎重建穿戴行 | 6 | 其余取默认（`stack_max=1` **故意**） | core/equipment.py:909-913 |
| 7 | `equipment.py` 回包行重建（`TypeError` 兜底） | 旧实例字段兜底 | 5 | 同上；**无 uid**（旧档语义） | core/equipment.py:915-918 |

**字段覆盖差异（本次机器实测，见 §8）**：

```
_item_from_dict        (读档 codec)      : 20/20 —— 权威
runner.py:720          (ctx→Player 归一) : 18/20 —— 丢 stack_max, cooldown_until
basic_commands.py:1567 (/装备 dict 归一) : 17/20 —— 丢 stack_max, cooldown_until, effect_refs
```

#### ⚠️ 重点警告 1：`/装备` 归一丢 `effect_refs`，且**结果被写回背包**

`basic_commands.py:1567-1597` 的 dict→`ItemInstance` 归一**没有带过 `effect_refs`**（批61 的"相性抽中的追加效果引用"）。而同一函数在 `:1616-1618` 把归一结果**写回 `player["inventory"]`**：

```python
# basic_commands.py:1613-1618
player["inventory"] = [
    item if (r is sorted_inv[index - 1]) else r for r in player["inventory"]
]
```

**后果链**（可复现推理，非猜测）：
1. 装配层把背包转成 dict 行（`Player` dataclass → `asdict`，见 `runner.py:568-572` 注释）；
2. 该玩家对某个**炼金产物**（`effect_refs` 非空）执行 `/装备`；
3. `:1567` 归一丢弃 `effect_refs` → `:1616` 写回背包 → 该实例的附加效果引用**永久丢失**（下次落档写入 DB 即为空元组）。

**判定**：`runner.py:720` 保留了 `effect_refs`（`:751-753`，注释明写"炼金产物不丢字段"），而 `basic_commands.py:1567` 没有——**两者是同一语义的归一，行为不一致**。同段注释（basic_commands.py:1587-1596）明确逐批补过 `quality_level`/`enhance_affixes`/`required_level`/`temper_alloc`，**唯独漏了批61 的 `effect_refs`**。
**分类**：**疑似缺口**（不是"故意设计"——它没有注释依据、没有裁决登记，且与同族归一不一致）。**本章如实标注，不擅自定义为 bug**；修复方向见 §3.4。
**作用域**：仅当 `/装备` 的背包行以 **dict 形态**到达时才触发；纯 `ItemInstance` 链路（`_field` 已归一）不受影响。

#### ⚠️ 重点警告 2：`stack_max` 在两条归一链路都丢

`stack_max`（堆叠上限）在 `runner.py:720` 与 `basic_commands.py:1567` **都未带过** → 归一后一律回落默认 `99`。对 `stack_max=1` 的装备实例，归一后变成"可堆叠 99"。上游盘点已登记过同族问题（`repository.py:219-222` 注释：*"stack_max 原为读侧漏字段——实例行 stack_max=1 读回恒默认 99"*），该处已在读档 codec 修复（`:222`），但**这两条归一链路的同类问题未见修复注释**。**分类：疑似缺口（同类，未登记）**。

#### ⚠️ 重点警告 3：第 6/7 号构造点的 `stack_max=1` 是**故意的**

`core/equipment.py:909-918` 重建穿戴行时写死 `stack_max=1`（**装备实例不可堆叠**）——这与上面两条"应该带过却带丢"性质不同。**别一起"统一修"**。

### 3.2 `uid` 生成与迁移

**这是什么**：`ItemInstance.uid` = 实例落档唯一键，解「同 `item_id` 多件随机词条实例跨存档/重登后聚合错实例」。

| 环节 | 规则 | file:line |
|---|---|---|
| **生成口径（唯一源）** | `new_item_uid()` = `uuid.uuid4().hex`（32 位小写十六进制）；**全仓唯一生成口径，不得在别处另拼字符串** | data/item.py:25-36 |
| **自动补发** | `ItemInstance.__post_init__`：`uid` 为空 → `new_item_uid()`（`frozen` 下用 `object.__setattr__`） | data/item.py:95-102 |
| **显式传入** | 旧档读取 / 迁移 / 等价重建 → **原样保留** | 同上 docstring |
| **旧档补发（幂等）** | `backfill_instance_uids`：每行缺失 uid → 补发；每槽缺失 uid → 指向首个未被占用的同 `item_id` 背包行 uid；无匹配 → 留空 | storage/migrations.py:92-136 |
| **迁移步** | `migrate_v2_to_v3`（JSON 级补发，仅存量；新库由 `__post_init__` 天然带 uid） | storage/migrations.py:139-168；步表 :171-174 |
| **`compare=False`** | `uid` 不参与 `==`；实例同一性判定走**显式 uid 比较**或 `is` | data/item.py:65；`EquipmentSlot.uid` 同理 player.py:75 |
| **回指** | `EquipmentSlot.uid` → `ItemInstance.uid`；空串 = 旧档 → 回退 `item_id` 首匹配 | data/player.py:64-67 |
| **镶嵌状态挂载** | `player.persistent_state["rune_sockets"]` **以 `ItemInstance.uid` 为键** | data/runes.py:47；migrations.py:180-191 |

**【稳定契约】**：`new_item_uid()` 是唯一生成口径；`uid` 的 `compare=False`；`rune_sockets` 以 uid 为键。
**改动风险**：
- 在别处自己生成 uid（如 `f"{item_id}_{i}"`）→ 与迁移补发的 uuid 冲突/重复 → 符文镶嵌挂错物品。
- 把 `compare=False` 改成 `compare=True` → 旧调用点/旧测试的相等性语义突变（item.py:47-50 明写）。
- **`uid` 不保证跨"等价重建"稳定**：如果某条路径构造时**没带 uid**，`__post_init__` 会**补发一个新 uid**——同一件物品会被当成两件（符文镶嵌丢失、装备槽回指断开）。这正是 §3.1 表的实践意义。

### 3.3 落档 / 读档往返

```
Player.inventory (Tuple[ItemInstance])
   │  写：player_to_row → _asdict_row → dataclasses.asdict  → JSON list   repository.py:154-157,167
   ▼
players.inventory  (TEXT, JSON，schema.py:55)
   │  读：row_to_player → backfill_instance_temper(旧档缺补) → _item_from_dict(逐字段)  repository.py:289-303,196-243
   ▼
Player.inventory (Tuple[ItemInstance])
```

| 环节 | 关键点 | file:line |
|---|---|---|
| 写 | `_asdict_row`：dataclass → asdict；**dict 原样保留**（兼容适配层写入的 dict 槽/行，否则 `asdict` 崩） | repository.py:154-159 |
| 写 | `job_id` 折进 `persistent_state`；`equipment`/`inventory` 含 **ID+名称冗余** | repository.py:150,167-168 |
| 读 | 旧档缺补淬炼字段 `backfill_instance_temper`（**幂等/无损/版本无关**） | repository.py:300-303；migrations.py:206-234 |
| 读 | `_item_from_dict`：缺省补默认、**未知键多忽略**（MIG-1） | repository.py:196-243 |
| 读 | `stack_max` 缺省口径 99（**批40 修复读侧漏字段**） | repository.py:219-222 |
| 读 | `effect_refs` 只收非空 str、去重保序 | repository.py:242 + `_effect_refs_of` :185 |
| 迁移 | `MIGRATION_STEPS = [(1,2,migrate_v1_to_v2), (2,3,migrate_v2_to_v3)]` | migrations.py:171-174 |
| schema | `DB_SCHEMA_VERSION` 与 `Player.schema_version` 默认 4（注释"当前 5"） | schema.py:67；player.py:110 |

**【稳定契约】**：JSON 键名（= dataclass 字段名）；`players.inventory` 列是 JSON 文本；迁移步的幂等/无损承诺。
**改动风险**：
- **未知键多忽略**是 MIG-1 口径——**新增字段后旧代码读新档不会崩**，但会丢该字段。故新增字段必须升级 `DB_SCHEMA_VERSION` 或写幂等补缺函数（范例：`backfill_instance_temper`）。
- 读档是 `Tuple[ItemInstance,...]`，写档按 JSON list——**中间任何一环把 tuple 换成 list 都会改 `Player` 的相等性**。

### 3.4 变更（mutation）的正确姿势

`ItemInstance` 是 `frozen=True`，**不能就地改**。正确姿势只有一种：

| 姿势 | 说明 | 范例 file:line |
|---|---|---|
| ✅ **`dataclasses.replace`** | 保留**全部字段**（含未来新增字段），只改指定项 | `core/inventory.py:154-157` `_row_with()`（推荐入口，docstring 明写"保留全部字段与子类扩展字段"） |
| ✅ 重建整行 | 显式列出所有字段（见 §3.1，**必须列全**） | repository.py:213；runner.py:720 |
| ❌ 就地改字段 | frozen 会抛异常（或在 dict 行上静默不落档） | — |
| ❌ 只改 dict 行 | dict 行改动**不落档**（除非回写 `ctx["inventory"]`/`player`） | — |

**现有 replace 变更点（供参考，均为安全姿势）**：`core/inventory.py:157`、`commands/temper_commands.py:198`（`temper_alloc`+`stats_bonus`）、`commands/shop_tx.py:194`/`:224`（`count`）、`core/equipment.py:922`（`enhance_level`）、`commands/gift_commands.py:86`/`:108`/`:116`（`count`）、`commands/contest_commands.py:185`（`count`）。

**修复 §3.1 两处缺口的方向（供维护者参考，本章不代改）**：
1. **收敛而非补齐**：把 `runner.py:720` 与 `basic_commands.py:1567` 的重复内联构造，收敛为一个**公共 `_instance_from_mapping()`**（`repository._item_from_dict` 已具备 20/20 能力，且能容忍缺键）——这样以后加字段只改一处。
2. 若暂不收敛，则**至少补齐 `effect_refs` / `stack_max` / `cooldown_until`** 三键，并在两处加注释互指。
3. 补一条**断言式测试**：`asdict → 归一 → asdict` 往返对拍，字段集必须相等（可防下一个字段再漏）。

## 4. 给扩展开发者的"安全改法"清单

> **用法**：先找到你要做的那件事，按表**从上到下逐条做完**。标 ⚠️ 的行 = **漏做即静默失效**（不报错）。
> **通用铁律**：键名/字段的"唯一源"在哪，就只改哪里；**派生表不要手改**（会被 import 覆盖）。

### 4.1 新增一个**特效轴**（最常见的扩展诉求）

**先自问**：这条轴有**唯一消费点**吗？
- **有** → 按下面做；
- **没有** → 仍按下面做，但 `consumer` 必须写 `EFFECT_CONSUMER_PENDING`（哨兵）并在 `consumer_note` 写明候选点，`display.help` 必须写"当前未实现，配置不生效"。**不得伪造唯一消费点，不得留空**（§1.2.1）。

| # | 步骤 | 文件 | 说明 |
|---|---|---|---|
| 1 | 在 `EFFECT_AXIS_SPECS` 追加一条 dict | `qbot_rpg/data/gear_stats.py:230-447` | **必填字段**：`axis` / `doc_id` / `priority` / `min` / `max` / `default` / `stack` / `display{mode,label,help}` / `legacy_alias` / `consumer` / `consumer_note` |
| 2 | 若该轴是**结算期**轴 | 同处加 `"bridge": "settlement"` | 否则会被桥进 combatant（奖励类轴不该进） |
| 3 | ⚠️ 若需要实现消费点 | 消费点所在文件 | 按 `consumer_note` 一次改**全部**来源（例：heal 有 4 处源，只改 1 处必漏） |
| 4 | ⚠️ 若轴有旧键 | 在轴条目里写 `legacy_alias: ((旧键, sign),)` | 换算出口只有 `route_legacy_aliases_into_flat` 一处 → **不会双计**；`sign=-1` = 语义相反 |
| 5 | 自动派生（**无需手改**） | `GEAR_EFFECT_KEYS:461` / `EFFECT_TO_COMBATANT:470` / `DEFAULT_EFFECT_AXES:593` / `EFFECT_LEGACY_ALIASES:584` / `GEAR_LABELS_ZH`+`GEAR_HELP_ZH`（:576-581 注入） | 若你发现要手改这些，说明走错了 |
| 6 | 同步 docstring 数量 | `gear_stats.py:227` | 该注释写"15 条"而实际 17 条（**已知不一致**，见 §6 C1）；加轴时顺手更新，但**以表为准** |
| 7 | 若要进强度预算权表 | `EFFECT_AXIS_WEIGHTS:873` | 否则该轴报 `unknown_axis`（默认 `warn` 黄提示） |
| 8 | 加/改测试 | `tests/unit/test_batch50_effect_axes.py` | 「无消费点的轴不得登记」由该测试钉死（:140） |
| 9 | 登记决策 | `docs/深度打造_决策记录.md` | 本框架的落地登记惯例 |

### 4.2 新增一个**装备词条键**（非特效轴）

| # | 步骤 | 文件 | 说明 |
|---|---|---|---|
| 1 | 判断归属键族 | `gear_stats.py:175/180/186` | FLAT（加算）/ PCT（百分点）/ COMBAT（战斗直读） |
| 2 | ⚠️ 加进对应 `GEAR_*_KEYS` 元组 | 同上 | **派生表 `GEAR_NUMERIC_KEYS:494` / `GEAR_DISPLAY_KEYS:499` 自动跟随** |
| 3 | ⚠️ 加中文 label | `GEAR_LABELS_ZH:517` | 否则编辑器/详情面板显示裸键名 |
| 4 | 加中文 help | `GEAR_HELP_ZH:536` | 编辑器字段说明气泡 |
| 5 | 若是 COMBAT 键 | 加进 `COMBAT_TO_COMBATANT:502`（含封顶值 `None`=不封顶） | 否则战斗读不到 |
| 6 | 若键名以 `_pct` 结尾 | 无需额外操作 | `PCT_SUFFIX:172` 在聚合端自动拆层 |
| 7 | 编辑器字段表 | `content/field_meta.py:1898` | 已 `*GEAR_FLAT_KEYS, *GEAR_PCT_KEYS, *GEAR_COMBAT_KEYS` 展开 → **自动跟随** |
| 8 | 若要参与淬炼 | 无需改（`core/temper.py:178-187` 自动取 `GEAR_NUMERIC_KEYS`） | 或写进 `temper.allowed_stats` 白名单 |
| 9 | 若要参与符文加成 | 无需改（`core/runes.py:109` `_NUMERIC_KEY_SET` 自动跟随） | |

> **提醒**：**别把新键塞进 `GEAR_PLACEHOLDER_KEYS`**——那是"只展示、不接引擎"的占位族，当前只有 `cooldown_reduction_pct` 一个（且它是别名）。

### 4.3 新增一个 `ItemInstance` 字段 ⚠️ **最容易丢字段的一类**

| # | 步骤 | 文件 | 漏做后果 |
|---|---|---|---|
| 1 | 加 dataclass 字段（**必带默认值**，放在末尾区间） | `data/item.py:40-102` | 无默认值会让所有旧构造点 `TypeError` |
| 2 | ⚠️ 读 codec 读回 | `storage/repository.py:196-243` `_item_from_dict` | **旧档读不出新字段** |
| 3 | ⚠️ `runner.py` 归一带过 | `assembly/runner.py:720-754` | ctx→Player 路径丢字段 |
| 4 | ⚠️ `basic_commands.py` 归一带过 | `commands/basic_commands.py:1567-1597` | `/装备` 路径丢字段**且写回背包**（§3.1 实证） |
| 5 | ⚠️ 旧档幂等补缺 | `storage/migrations.py`（范例 `backfill_instance_temper:206-234`） | 旧档永远是默认值 |
| 6 | 若字段影响落档 schema | `storage/schema.py`（如新增列）+ `DB_SCHEMA_VERSION` | 迁移链断裂 |
| 7 | 写侧无需改 | `repository.py:154-157` `dataclasses.asdict` | 自动带出 |
| 8 | 若要在 `/背包` 详情展示 | `basic_commands.py:1098-1101`（遍历 `GEAR_DISPLAY_KEYS` 的是 `stats_bonus`，其他字段另加） | 不显示 |
| 9 | 若要能改它 | 用 `dataclasses.replace`（推荐经 `core/inventory.py:154-157` `_row_with`） | 就地改 frozen 会抛异常 |

> **强烈建议**：与其新增字段，**优先考虑塞进已有的自由桶** —— 数值类 → `stats_bonus`（键空间见 §1.1）；非数值/包私有 → `Player.persistent_state`。新增 `ItemInstance` 字段的维护成本 = 上表 9 条。

### 4.4 新增一个 `Player` 字段

| # | 步骤 | 文件 | 漏做后果 |
|---|---|---|---|
| 1 | 加 dataclass 字段（带默认值） | `data/player.py:79-113` | — |
| 2 | ⚠️ 写 codec | `storage/repository.py:144-182` `player_to_row` | 字段落不了档 |
| 3 | ⚠️ 读 codec | `repository.py:289-343` `row_to_player` | 读回默认值 |
| 4 | ⚠️ 建表列 | `storage/schema.py:47-70`（+ `DB_SCHEMA_VERSION`/迁移步） | 列不存在 → 写档崩或迁移失败 |
| 5 | 若是"运行期要写的玩家态" | `assembly/context.py` 注册态段（:1398-1584）注入同名 ctx 键；**并考虑未注册态段（:1586-1639）给安全空值** | 未注册态 `KeyError` |
| 6 | 若是"持久段可变引用" | 用 `_ps_init(ps, key, empty)` 惰性挂回（context.py:324-340） | 写入不落档（2026-08-29 实测过该 bug） |

> **提醒**：列名与字段名**不同名**（`player_qid`/`nickname`/`stats`）是历史设计，**不要顺手统一**。

### 4.5 新增一个**内部 `ctx` 键**

**先自问：这真的需要吗？** 内部 `ctx` **不是扩展契约**（§2.7.3）。包自持代码请用 **`ExtContext`**（`ext_player.set_state/get_state`）。
若确为框架内部需要：

| # | 步骤 | 文件 | 说明 |
|---|---|---|---|
| 1 | 选段注入 | `assembly/context.py`：基础段 :1295-1373 / 注册态 :1398-1584 / 未注册态 :1586-1639 / 注册无关 :1642-2034 | 段选择决定"哪些玩家能拿到" |
| 2 | ⚠️ 查重名 | 全文件 grep 该键名 | 已有 52 个键被重复注入（§2.7.3）——重名 = 后写覆盖先写 |
| 3 | ⚠️ 未注册态兜底 | `context.py:1586-1639` | 仅注册态的键在未注册玩家上**不存在**，消费方必须 `ctx.get` |
| 4 | 记注释 | 注入处上方 | 与既有风格一致（写清消费方） |

### 4.6 新增一个 combatant / 战斗快照键

**⚠️ 这是"无单一源"重灾区**（§6 A2）。combatant 字段散落 ≥4 处构造点：

| # | 必查构造点 | 文件 |
|---|---|---|
| 1 | 默认键 | `core/battle.py:317-322` `_DEFAULT_STATS` |
| 2 | 归一兜底 | `core/battle.py:2318-2327` `_combatant()` |
| 3 | 敌方构造 | `commands/battle_launch_commands.py:182-220` |
| 4 | 玩家构造 | `core/pvp.py:154-203` `_combatant_of` |
| 5 | 运行期派生 | `core/battle.py:937-942`（派生键，不落档） |
| 6 | 状态/效果写入 | `core/effects.py:1035-1045`（`defenses`）、:2229-2235（`dot_pool`） |
| 7 | 若需随快照往返 | `core/battle.py:2332-2433`（`start`）+ `:5537-5613`（`to_snapshot`） |

> **否则**：只在部分路径生效（例：只有敌方有、玩家没有）。

### 4.7 新增一个**状态 / 印记实例**键

| 对象 | 唯一构造源 | 必改点 |
|---|---|---|
| 状态实例 | `core/effects.py:735-763` `_new_instance`（**唯一**） | 在 `_new_instance` 加键 + 默认值；若需衰减/重置，补 `:768`/`:818` 等处理点 |
| DOT 池实例 | `core/effects.py:2229-2235` | shape 与状态实例**不同**，单独改 |
| 印记实例 | `core/marks.py:258-264` `new_inst` + **权威键元组 `_MARK_INSTANCE_KEYS:53-60`** | **两处都要改**（键元组是权威声明） |

### 4.8 新增一个**阈值 / 默认值表**（新 `settings` 段）

| # | 步骤 | 说明 |
|---|---|---|
| 1 | 定义 `*_KEY` 段名常量 + `DEFAULT_*` 默认表 | 放在**能用它的最低层**（校验器要读 → 必须落 `data`/`content` 层，因 `content -/-> core`，范例 `PANEL_AXIS_STEMS:205`、`EFFECT_BUDGET_KEY:858`） |
| 2 | 写 `normalize_*()` 归一函数 | **整段不存在 → 全默认 → 既有行为零变化**（本框架通用口径） |
| 3 | 在 `ctx` 条件注入（若指令要用） | `assembly/context.py`（范例 `panel_budget:1872`/`monster_scaling:1876`/`effect_axes:1881`）——**未注入则不改既有键集** |
| 4 | 结构登记 | `content/field_meta.py`（软段/结构）+ 专项 `content/*_settings.py` 校验 |
| 5 | 作者文档 | 至少在本手册第 2 路"包声明段总清单"登记 |

### 4.9 变更一个**已有常量**前的检查清单

| 问题 | 若"是"则 |
|---|---|
| 它被标 **【稳定契约】** 吗？ | 走评审：读定义处注释 + 查 `docs/深度打造_决策记录.md` + 确认迁移路径 |
| 它在 `__all__` 里吗？ | 说明有外部 import；改名前先 grep 调用点 |
| 它是**派生表**吗？（由别的常量算出来） | **不要改**，改它的上游 |
| 它是**别名/`sign`** 吗？ | 几乎一定是故意设计（§1.2.4），不要"修正符号" |
| 它有 `normalize_*()` 吗？ | 改默认值会让"未配置 = 既有行为"失效 |
| 它是 legacy 兜底（硬编码少量包专属常量）吗？ | **降级兜底**，删了会改无 registry 路径行为（见第 3 路） |

## 5. 【稳定契约】汇总（改动需评审）

**这一节是本章对"未来维护者"的核心价值**：以下条目已被内容包 / 测试 / 存档数据依赖，单方面改动会**静默破坏**。改之前请读定义处注释、查 `docs/深度打造_决策记录.md`、确认迁移或兼容路径。

| # | 稳定契约 | 为什么稳定 | 定义 file:line | 改动需评审的理由 |
|---|---|---|---|---|
| S1 | **`EFFECT_AXIS_SPECS` 是特效轴键空间唯一源** | 6 张派生表由它算出 | gear_stats.py:230-447 | 手改派生表会被 import 覆盖；删轴=旧包静默失效 |
| S2 | **登记即承诺**（无消费点不得登记 / 哨兵 / help 明说未实现） | 对作者的承诺；测试钉死 | gear_stats.py:56-59、:207-211、:224 | 破坏它 = 重犯 `cooldown_reduction_pct` 陷阱 |
| S3 | **攻防两侧配对轴**（治疗/伤害/状态时长/命中抵抗） | 装build 可分别配两侧 | §1.2.3 | 合并两侧 = 改玩法与既有测试对拍 |
| S4 | **`EFFECT_LEGACY_ALIASES` 的键与 `sign`** | 旧包数值依赖；换算只一次 | gear_stats.py:584-588 | 删=旧包失效；两处换算=双计；改符号=免伤变易伤 |
| S5 | **`GEAR_PLACEHOLDER_KEYS` 的"跳过聚合、只在一处换算"** | 防双计 | gear_stats.py:196-198；`route_bonus_into` 显式跳过 | 当死代码清理 = 别名断链 |
| S6 | **`COMBAT_TO_COMBATANT` 的封顶值** | 战斗数值平衡 | gear_stats.py:502-514 | 改封顶 = 平衡改动，需评审 |
| S7 | **`settings.*` 的"整段不存在 = 既有行为零变化"** | 所有 `normalize_*()` 的口径 | §1.4 | 改默认值 = 静默改所有未配置的包 |
| S8 | **`ABSOLUTE_QUALITY_MAX = 100` 硬上限** | 故意写死 | core/quality.py:84 | 放开=品质系统溢出 |
| S9 | **`Player` 7 个字段 ≠ 列名**（`player_qid`/`nickname`/`stats`；`job_id` 折入 `persistent_state`） | 存档格式 | player.py:86-96；repository.py:150,161,169 | 改列名 = 改存档格式，需迁移 |
| S10 | **`PlayerAttributes` 三层管线与固定子键** | 属性计算管线契约 | player.py:26-37 | 加第四层/改子键 = 改管线 |
| S11 | **`EquipmentSlot.uid` 的 `compare=False`** | 保持既有 `==` 语义 | player.py:75 | 改=True = 旧测试/旧调用点语义突变 |
| S12 | **`ItemInstance` 字段名 = 存档 JSON 键名** | 落档往返 | item.py:53-93；repository.py:196-243 | 改名=旧档读不出（MIG-1 多忽略→静默丢字段） |
| S13 | **`new_item_uid()` 是全仓唯一 uid 生成口径** | 唯一性 + 迁移幂等 | item.py:25-36 | 别处另生成 = uid 冲突/重复 |
| S14 | **`ItemInstance.uid` 的 `compare=False`** | 结构等价语义 | item.py:65 | 同上 |
| S15 | **`persistent_state["rune_sockets"]` 以 `ItemInstance.uid` 为键** | 镶嵌状态挂载 | runes.py:47；migrations.py:180-191 | 改键空间 = 符文镶嵌全部错位 |
| S16 | **迁移步的"幂等 / 无损 / 只加键不改值"承诺** | 旧档安全 | migrations.py:95-103、:186-189 | 破坏 = 旧档损坏或重复补发 |
| S17 | **`modules_raw` 模块名双处登记**（`_KIND_FOR_MODULE` + `FRAMEWORK_MODULE_CATALOG`） | 只有单向自检 | loader.py:150-202；module_catalog.py:68 | 只改一处 = 校验与编辑器不一致 |
| S18 | **`EVENT_POINTS` 值域固定 17 项、前 16 位保序** | effects/status `trigger` 取值；既有断言 | data/event_points.py:25（详见第 2 章） | 插/删/改序 = 既有触发与断言位移 |
| S19 | **`MANIFEST.modules` 声明顺序 = `modules_raw` 键顺序** | 加载顺序语义 | loader.py:87-93 | 改动 = 注册顺序变化 |
| S20 | **`ExtContext` 稳定面**（`EXT_API_VERSION="1"`） | 唯一允许包 import 的面 | ext_api.py:59、:125-304（详见第 2 章） | 改成员 = 破坏外部扩展兼容 |

> **与 `docs/深度打造_决策记录.md` 互引**：本框架惯例是**每次落地都登记决策记录**（含铁律与"勿修"裁决）。若某条稳定契约让你困惑"为什么必须这样"，先查该文件的落地登记与 `CHANGELOG.md` 批次条目。
> **三条上游参照**：① `框架体检报告.md` §四"可接受/别乱删"；② `审计3_勿增实体_重复机制.md` §6"合理并存清单"（R1~R13）；③ `审计3` §7"待裁决/存疑"（D1~D10）。
> **⚠️ 时效提醒**：上述审计基于较早 HEAD。本次已发现 `审计3` §7-D1 关于 `damage_dealt_pct`"目标轴无消费"的断言在**当前 HEAD 已不成立**（批70 已于 `core/battle.py:4226` 接线，§8 实证）。**引用审计结论前请先按本手册的方法复核。**

### 5.1 与本章相关的"合理并存"（**勿当重复清理**）

以下条目看似重复、实为有意设计（源自 `审计3 §6`，本次抽查相关项）：

| 看似重复 | 实际关系 | 本章相关处 |
|---|---|---|
| 品质四档（`core/quality.py`）vs 打造品质等级 1~10（`ItemInstance.quality_level`） | **正交维度**（颜色档 × 品质等级），H2 明文"不动既有品质注册表" | §1.3、§2.4 |
| 强化 `enhance_level` vs 淬炼 `temper_alloc` | **状态分账**，两引擎互不读写；`temper_alloc` 数值经 `materialize_temper` **物化进 `stats_bonus`** | §2.4 |
| `forge.essence_rate` vs `enhance.temper.cost_per_point` | **分键、语义相反、不可合键**（材料/精粹方向相反；返还必须 < 消耗否则套利） | §1.4.3、§1.4.4 |
| 别名"三个换算点"（占位 / pct / COMBAT 分流） | **唯一源 + 按层互斥换算**，是**防双计**的分层 | §1.2.4 |
| 多处"冷却"（`cooldown_pct` 轴 / 道具 `cooldown_of` / 形态 `cooldown_remaining` / 珠触发上限） | 不同对象、不同计数层 | §1.2.2 |
| `data/runes.py`（刻度常量+基础解析）vs `core/runes.py`（差异表解析） | 分层，content 校验与 core 同源引用 | §1.3 |
| `data/gear_stats.py` vs `core/panel_budget.py` 的 `PANEL_AXIS_*` | data 定义 / core 再导出（架构矩阵 `content -/-> core` 使然） | §1.1 |

---

## 6. "无单一源"与缺口汇总

**这一节是本章的诚实边界**：以下项目**本章无法给出"唯一源"**，因为框架里确实不存在。请勿把它们当作"手册没写全"。

### 6.1 无单一源（A 组）

| # | 项 | 表现 | file:line | 本章处理 |
|---|---|---|---|---|
| **A1** | **内部 `ctx` dict** | 四段按代码位置切分；**52 个键重复注入**；存在动态键（`ctx[_key]`）→ 键名无法静态枚举 | context.py:1295-1373 / :1398-1584 / :1586-1639 / :1642-2034；动态 :1835/:1837 | §2.7.3 **明确标注"无单一源"**；给出四段分组的现行依据；键数用**区间口径**（批82 · Q1：注册 162~166 / 未注册 134~138，`only_reg=28` 恒定）；3 键无消费方（Q2/NEW-9） |
| **A2** | **combatant 字段** | ≥4 处构造（默认/归一/敌方/玩家）+ 运行期派生 + 效果写入 | core/battle.py:317-322、:2318-2327、:937-942；battle_launch_commands.py:182-220；core/pvp.py:154-203；effects.py:1035-1045、:2229-2235 | §2.5 逐处列出；§4.6 给"新增 combatant 键必查清单" |
| **A3** | **运行期战斗快照顶层键** | 只有代码、无 dataclass 契约 | core/battle.py:2332-2433、:5537-5613 | §2.5.4 列出；标注"无契约类型" |
| **A4** | **`Player.achievement_state`** | 字段散落 **3 处**：docstring 声明新形态 / codec 仍 tuple-list / 真值在 `persistent_state` | player.py:97-102；repository.py:174、:331；schema.py:63；context.py:1522-1524 | §2.1 改动风险 + 本节 A4；**字段已退化为旧档兼容读** |
| **A5** | **`modules_raw` 模块名双处登记** | `_KIND_FOR_MODULE` 与 `FRAMEWORK_MODULE_CATALOG` 各一份，只单向自检 | loader.py:150-202、:205-233；module_catalog.py:68 | §2.6.3 + §5 S17 |
| **A6** | **哪些 `EVENT_POINTS` 真接了** | 声明≠可用；须全仓 grep 派发点 | data/event_points.py:25 | **归第 2 章**（本章只给数量） |
| **A7** | **`settings.*` 段无统一登记表** | 软段/结构在 `field_meta.py`，专项校验在 `content/*_settings.py` 并列 | content/field_meta.py:3443；deep_craft_settings.py:110 等 | §1.4 按表逐张给出；**无全局总表** |

### 6.2 本次新发现（**上游盘点未列**）

| # | 发现 | 性质 | 证据 | 建议 |
|---|---|---|---|---|
| **N1** | **两条治疗轴的 `consumer_note` 是过期文案** | 注释与实现不一致（同 C 组性质） | `gear_stats.py:239-241`/`:250-251` 写"待接"；实际 `effects.heal_apply:1838-1888` + `HEAL_RECEIVED_AXIS`/`HEAL_DONE_AXIS` :111-112 + 5 处实调 + `tests/unit/test_batch52_heal_damage_axes.py` | 更新 `consumer_note`（或删"待接"字样） |
| **N2** | **`/装备` dict 归一丢 `effect_refs`，且写回背包** | **真缺口（批82 · Q4：未被任何裁决认定为可接受，字段静默丢失）** | `basic_commands.py:1567-1597`（17/20）**缺 `effect_refs`** → `:1616-1618` 写回 `player["inventory"]`；对照 `runner.py:720-754`（18/20，**保留** `effect_refs` :751-753） | 收敛为公共归一函数（§3.4）；**排收敛批**（Q5 已证 `/使用` 读取侧双形态兼容、无缺口） |
| **N3** | **`stack_max` 在两条归一链路均丢** | **真缺口（批82 · Q4：未被任何裁决认定为可接受）** | `runner.py:720`、`basic_commands.py:1567` 均未带 `stack_max` → 回落 99；`stack_max=1` 的实例归一后变"可堆叠 99"（已修读档侧 `repository.py:219-222` 为同族对照） | 同上（与 N2 合并为公共归一函数） |
| **N4** | **`FRAMEWORK_MODULE_CATALOG` 36 条目 `implemented` 全为 `True`** | 口径提示（非缺口） | `python3` 实测 `sum(implemented)=36/36` | "让作者看见未实装能力"目前靠目录条目存在；将来新增未实装模块应设 `implemented=False` |
| **N5** | **两条 17/18 字段归一与读档 codec（20/20）不一致** | 结构风险 | 见 §3.1 表 | 新增 `ItemInstance` 字段时**必须同时改这两个内联归一** |

### 6.3 本章与盘点文档的口径差异（**以本章为准**）

| 项 | 上游盘点说法 | 本次实测 | 判定 |
|---|---|---|---|
| `AFFINITY_KEYS` 数量 | 6（§1.3） | **4** | 盘点错；`affinity_keys.py:46-48` 实测 4 项 |
| `DEFAULT_TEMPER` 键数 | 14（§1.4） | **15** | 盘点错；`temper_stats.py:70-104` 实测 15 键 |
| `healing_received_pct`/`healing_done_pct` 接线 | "待接"（§1.2） | **已接线（批52）** | 盘点错；见 N1 |
| `EFFECT_AXIS_SPECS` 注释数量 | 注释写 15、实际 17（§6 C1） | **证实 17**（注释仍写 15，:227） | 盘点对；本次确认 |
| 特效轴接线数 | 11 已接 | **16 已接 / 1 未接** | 盘点低估（漏计治疗轴+时长轴） |
| `AFFINITY_KEYS` 语义 | "相性键" | 是 **settings 顶层四段名** | 语义澄清 |

---

## 7. 待查清单（**不猜**）

| # | 待查项 | 为什么标待查 | 建议查法 |
|---|---|---|---|
| Q1 | **内部 `ctx` dict 的精确键总数** | AST 静态识别 128 个字面量键，但有动态注入（`ctx[_key]`）+ 闭包挂载；精确数需运行期实测 | 构造注册/未注册两种玩家各跑一次 `make_context`，`len(ctx)` + 打印 `ctx.keys()` |
| Q2 | **`ctx` 各键的"消费方"** | 只有注入点、无消费方登记（上游 §6 B1 指内部 hook 只在 docstring 说明） | 逐键 grep 全仓读点；或加运行期读点埋点 |
| Q3 | **`DEFAULT_TEMPER` 归一优先级链** | `total_cap` vs `total_cap_by_level`、`per_stat_cap_ratio` vs `per_stat_cap` 的优先顺序本次未逐行读 `normalize_temper_config:181-226` | 读 `temper_stats.py:181-226` 全文 |
| Q4 | **N2/N3 是否已在某次裁决中被认定为"可接受"** | 未找到注释依据或决策登记，但也未穷举 `docs/深度打造_决策记录.md`、`CHANGELOG.md` 全部条目 | 全仓 grep `effect_refs` / `stack_max` + 读 CHANGELOG 批61/批40 条目 |
| Q5 | **`/使用` 消耗品路径读取 `effect_refs` 的形态** | `use_commands.py:354` 用 `effect_refs_of(inst)`，`inst` 来自 `_sorted_rows`（可能 dict 或实例）；`effect_refs_of` 兼容两形态，但本次未跑端到端 | 读 `core/alchemy_affinity.effect_refs_of` + 跑一次炼金产物 `/使用` |
| Q6 | **`modules_raw` 各模块的值形态全表** | 只确认了 list/map/顶层 obj 三类与若干例子，未逐模块列全 | 读 `loader.py:96-128` 逐模块分支 |
| Q7 | **`_MERGE`/`conditional` 等模块是否在 `FRAMEWORK_MODULE_CATALOG` 中有对应** | `_KIND_FOR_MODULE` 29 项 vs catalog 36 条目，本次未做一一对照 | 两表取差集 |
| Q8 | **`ABSOLUTE_QUALITY_MAX` 是否有 settings 覆盖旁路** | 注释说"故意写死"，但未全仓验证无旁路 | grep `ABSOLUTE_QUALITY_MAX` 全部用法 |

---

## 8. 复核记录（本次核对方法、证据与结论）

### 8.1 核对基线与方法

| 项 | 值 |
|---|---|
| 仓库 | `/root/QBot-TurnTellerRPG` |
| **HEAD** | **`62cc299`**（上游盘点基于 `d86d9dd`，**行号可能漂移**） |
| 上游素材 | `/root/deliverables/API手册_编撰前盘点.md`（§0-§8）· `框架体检报告.md` · `审计3_勿增实体_重复机制.md` §6/§7 · `docs/深度打造_决策记录.md`（转引） |
| 仓库修改 | **零**（本章只读仓库；产出仅本文件） |

**三种核对手段**（本章每条 `file:line` 至少经其一）：

| 手段 | 用途 | 证据形式 |
|---|---|---|
| **A. 逐行读源** | 字段表 / 构造点 / 注释依据 | read 工具实际输出 |
| **B. 运行期导入取值** | 常量数量与内容（防"注释写 15 实际 17"类错误） | `python3 -c "from ... import ..."` |
| **C. AST / grep 实调扫描** | ctx 键数、重复注入、逐轴接线状态 | 脚本 + grep 命中行 |

### 8.2 关键实证命令与结果

```text
# B: 常量数量（值取自 import，非注释）
EFFECT_AXIS_SPECS            = 17   （P0 8 + P1 9）   ← 注释写 15（:227）
GEAR_FLAT_KEYS               = 13
GEAR_PCT_KEYS                = 8
GEAR_COMBAT_KEYS             = 10
GEAR_EFFECT_KEYS             = 17
GEAR_NUMERIC_KEYS            = 48
GEAR_DISPLAY_KEYS            = 49
EFFECT_TO_COMBATANT          = 16   （reward_mult_pct bridge="settlement" 被排除）
EFFECT_LEGACY_ALIASES        = 6
AFFINITY_KEYS                = 4    ← 上游盘点写 6
DEFAULT_TEMPER               = 15   ← 上游盘点写 14
DEFAULT_ESSENCE_RATE         = 15
DEFAULT_DEEP_CRAFT_RULES     = 16
FRAMEWORK_MODULE_CATALOG     = 36 条目（implemented 全 True）
FRAMEWORK_MODULE_PRESETS     = 3
DEFAULT_PANEL_BUDGET         = {white:7.0, equip:8.0, buff:5.0, equip_stat_mult:1.0}
DEFAULT_MONSTER_SCALING      = {hp_mult:1.0, atk_mult:1.0, def_factor:1.0, def_k:100.0,
  effect_hp_mult:1.0, effect_atk_mult:1.0}
EVENT_POINTS                 = 17

# C: 逐轴接线状态（grep 实调点，core/ + commands/，排除 data/gear_stats.py）
reward_mult_pct              : 0 命中 → 唯一未接线（哨兵属实）
其余 16 轴  : 均命中实调点（_axis_pct / effect_axis_value / 轴常量）
  healing_received_pct → effects.py:1872（heal_apply 内）
  healing_done_pct     → effects.py:1878
  damage_taken_pct     → battle.py:4253
  damage_dealt_pct     → battle.py:4226
  cooldown_pct         → battle.py:3438
  status_chance_pct    → effects.py:531     status_resist_pct  → effects.py:532
  stack_gain_pct       → effects.py:533     stack_cap_delta    → effects.py:534
  status_duration_pct  → effects.py:537     duration_taken_pct → effects.py:538
  action_bar_shift     → battle.py:5185     action_speed_pct   → battle.py:2575
  resource_cost_pct    → battle.py:1279     resource_gain_pct  → battle.py:1281
  crit_damage_pct      → battle.py:4724

# C: ctx AST 扫描（make_context，含嵌套闭包）
distinct ctx keys (字面量) = 128
total assignments          = 183
re-injected (>1)           = 52  （battle_engine×4；items×3；其余 ×2）
动态键  = ctx[_key]，context.py:1835/1837

# C: ItemInstance 构造点字段覆盖（机器比对 20 个字段名）
_item_from_dict   (repository.py:213)     = 20/20
runner.py:720  = 18/20  缺 stack_max, cooldown_until
basic_commands.py:1567  = 17/20  缺 stack_max, cooldown_until, effect_refs
write-back 确认   basic_commands.py:1616-1618  player["inventory"] = [item if ... ]
```

### 8.3 行号漂移修正记录（上游盘点 → 本次实测）

上游盘点的 `file:line` 基于 `d86d9dd`，本次在 `62cc299` 复核发现**若干处整体偏移**。以下为本章已采用修正值的位置（**维护者请以本章为准**）：

| 位置 | 上游盘点 | 本次实测（`62cc299`） | 偏移 |
|---|---|---|---|
| `Manifest` 类 | models.py:728-749 | **models.py:693 起**（`modules` :698、`raw` :699） | −35 |
| `Pack` 类 | models.py:762-774 | **models.py:728 起**（`modules` :733） | −34 |
| `event_dispatcher` 再导出 | `:69` | **`:51` 引入 + `:60` 再导出** | — |
| `loader._KIND_FOR_MODULE` | :150-202 | **:146-198** | −4 |
| `check_register_table_consistency` | :205-218 | **:201-216** | −4 |
| `check_manifest_modules_registered` | :221-233 | **:217-234** | −4 |
| `loader` `modules["manifest"]` | :314 | **:310** | −4 |
| `Registry` 属性 | :93/:97/:101/:110/:152/:167 | **:94/:98/:102/:111/:153/:168**（装饰器行/def 行之别） | +1 |
| `start()` 快照键 | :2333-2439 | **:2330-2436** | −3 |
| `to_snapshot()` 键 | :5560-5612 | **:5557-5609** | −3 |
| `snapshot()` 别名 | :5615-5617 | **:5612-5614** | −3 |
| `_minimal_snapshot` | :2258-2283 | **:2255 起** | −3 |
| DOT 池实例 | effects.py:2229-2235 | **:2224-2232** | −5 |
| `marks.formula_view` | :428-430 | **:421** | −7 |
| `module_presets_disable` 注释 | :27-31 | **:24** | −3 |
| `_effect_refs_of` | :186-193 | **:185 起** | −1 |

> **未漂移**（本次确认与上游一致）：`gear_stats.py` 全部常量行号、`player.py`/`item.py`/`status.py`/`battle.py`(data)/`registry.py` 类与字段、`panel_budget.py`、`temper_stats.py`、`quality.py`、`runes.py`、`affinity_keys.py`、`module_catalog.py`、`module_presets.py:58`、`repository.py` 各 codec、`migrations.py`、`context.py:1256`。

### 8.4 本章的诚实边界（未能确证的部分）

1. **未跑端到端运行验证**：§3.1 的字段丢失是"代码路径 + 机器字段比对"推导，**未实际构造一个炼金产物执行 `/装备` 并观察落档**。结论标注为"疑似缺口"而非"已确认 bug"（Q4/Q5）。
2. **未穷举 `docs/深度打造_决策记录.md` 与 `CHANGELOG.md`**：N2/N3/N1 是否已有裁决登记，本次未逐条查完。
3. **`ctx` 键的"消费方"未登记**：本章只给"注入点"，未给每个键的读点（Q2）。
4. **§1.2.6 接线状态基于 grep 实调点**，未逐个跑单测；若某轴实调点位于条件分支永不进入，grep 无法发现。
5. **上游盘点的行号**已随 HEAD 前进而变化；本章所有 `file:line` 以 **HEAD `62cc299`** 为准。

---

> **本章与其他两路的接口**：
> - **第 2 章《事件与扩展点》**：`EVENT_POINTS` 逐时点三态表 / `ExtContext` 稳定面 / 包声明段总清单 / E1/E2/E3 契约。
> - **第 3 章《权责与「勿当 bug 修」》**：门禁地图 / legacy 兜底"勿删" / 别名归并"勿修" / 待裁决清单。
> - **本章供其它两路复用的锚点**：§1.1 键族、§1.2 特效轴全集、§2 字段表、§3 构造点清单、§4 安全改法、§5 稳定契约编号（S1~S20）、§6 无单一源编号（A1~A7 / N1~N5）、§7 待查编号（Q1~Q8）。
