# 细化_1e：怪物八段数据 Schema（enemies.json）

> 版本：v1.0（细化交付）· 依据：《怪物模块设计定稿 v1.0.3》（下文简称**定稿**，行号以 `/root/docs_archive/RPG框架项目/怪物模块设计定稿.md` 为准；辅助引用《BOSS战编排设计定稿》= AI 定稿）
> 范围：① enemies.json 字段级 schema（八段：tier/9 属性/PV/双维弱点/行动表/特殊行动/掉落三类/图鉴 lore）② 难度模板默认值 ③ 掉落条目扩展 ④ 木桩特例 ⑤ 校验器规则 ⑥ 验收测试用例
> 覆盖声明（本细化的裁决范围）：仅对定稿**已有**语义做字段化定型；凡定稿标"以 XX 定稿为准"或"待定"处，本表只登记接口不发明实现。每字段、每规则均带定稿行号引用。
> 标注约定：**定稿既有**=定稿原文明确；**细化定型**=定稿仅给区间/单例/方向，本表取点定型（如 PV 档默认值 10/75/300 取区间中值；`pv_recover` 枚举在样本 `battle_end` 外补 `none`）——取点可改，裁决边界透明。

## 0 定稿版本并缝裁决（先读本节，解决定稿内部三处新旧写法并存）

| # | 接缝 | 定稿内并存写法 | 本 schema 裁决 | 依据 |
|---|---|---|---|---|
| S1 | 行动概率语义 | ① action.json `probability` 注释"入池开关（0=锚点/1=入池，数值不参与概率计算）"；② §6.2 "weight 归一化：普攻 50/重击 30/蓄力 20，probability=1 入池"；③ §十二 enemies 条目同含 probability+weight | **probability ∈ {0,1} 纯入池开关；概率=weight 归一化，仅 probability=1 条目参与随机池；probability=0 只被链/条件/状态机触发**（三处一致，无歧义，只做字段化） | L138、L145、L279 |
| S2 | 连招载体 | ① action.json 内嵌 `chain`（历史写法）；② "新配置连招一律走 enemies 顶层 `chains` 表" | **顶层 `chains` 为唯一新配置载体（可选字段，见 1.1-F14）；旧 action.json `chain` 保留读兼容，校验器提示迁移** | L137、L269；AI 定稿 L502、L512-515 |
| S3 | 特殊行动触发类 | ① §7.1 面向示例 5 类；② 权威枚举=怪物行动AI定稿 §二 13 类（hp_below/pv_broken/get_up/battle_start/after_action/player_status/player_hp_below/turn_count/phase_changed/zone_changed/ally_dead/combo_broken/script，x_ 前缀可扩展）；旧枚举为兼容别名（R-01 裁决） | **以 AI 定稿权威 13 类枚举为准**（细化_0 R-01）；§7.1 的 5 类为其语义缩略，映射见 1.4-表 | L156-161 vs L296 |
| S4 | 触发示例别名 | §七示例 JSON 用 `pv_broken`/`get_up`/`battle_start`，校验器枚举为 `broken`/`revive`/`enter_phase` | **canonical = 枚举名；示例名为别名，校验器接受并提示规范化（不拦截）** | L178-183 vs L296 |
| S5 | 木桩与八段结构 | §一结构示例 `pv:30` 等为普通怪占位；§十五另立 training 特例 | **木桩判定优先：tier:"training" 或 type:"dummy" 任一命中即按木桩特例处理（pv 强制 0 等）**，普通怪八段字段照常 | L15-33 vs L325-392 |

引用约定：`[Lxx]` = 定稿行号；`[AI Lxx]` = BOSS战编排设计定稿行号；"派生" = 由定稿语义直接推出的防呆规则（标注推出来源）。

---

## ① enemies.json 完整字段级 schema

### 1.1 顶层字段（18 个）

| # | 字段 | 类型 | 必填 | 默认值 | 约束 / 枚举 | 来源 |
|---|---|---|---|---|---|---|
| F01 | `id` | string | 必填 | — | 全文件唯一；建议 snake_case（样本 `rock_weasel`）；非空 | L19、L274 |
| F02 | `name` | string | 必填 | — | 显示名（样本 `岩皮鼬`）；非空 | L20、L274 |
| F03 | `tier` | enum | 必填 | `normal` | `normal` / `elite` / `boss` / `training`（第四档=木桩，仅战斗外 /木桩 可进入） | L21、L336 |
| F04 | `type` | enum | 选填 | 无 | `"dummy"`（标记式，tier 保持 normal 也可）；与 `tier: training` **至少其一**构成木桩 | L337 |
| F05 | `area` | string | 选填 | 无 | 出没地图名；木桩不在地图内，不配 | L22、L370 |
| F06 | `desc` | string | 选填 | 无 | 一句话描述（样本"岩石皮肤的小型野兽…"） | L23 |
| F07 | `stats` | object | 必填（可漏键） | 按难度模板补全 | 9 键见 1.2；漏配键由模板自动补全并提示 | L24、L40-45、L42 |
| F08 | `weakness` | object | 必填 | 无（空对象） | `types` + `elements` 双维，见 1.3；建议 ≥1 弱点（校验器警告，木桩豁免） | L25、L55-62、L363 |
| F09 | `pv` | number | 必填（普通怪） | 按档默认（见②） | ≥0；档区间仅提示：普通 0-20 / 精英 50-100 / BOSS 200-500；**木桩强制 0** | L26、L101、L237-239、L350 |
| F10 | `pv_recover` | enum | 选填 | `battle_end` | `battle_end` / `none`（战斗结束 PV 是否重置）；**换区恢复一半为运行时规则**（残血换区→PV 恢复一半向下取整），不由本字段表达 | L277、L93-100 |
| F11 | `resistance` | object | 选填 | 空（无天然抗性） | 初始抗性 map（0-100）+ `immune` 数组，见 1.3 | L27、L106-118 |
| F12 | `actions` | array | 必填（普通怪） | 无 | 条目见 1.4；行动表规模按档：普通 1-2 招 / 精英 2-4 招 / BOSS 4-6 招 | L28、L237-239 |
| F13 | `special_actions` | array | 选填 | `[]` | 条目见 1.4；数量按档：普通 0 / 精英 1 / BOSS 2-4 | L29、L237-239 |
| F14 | `chains` | array | 选填 | `[]` | **顶层连招表（新配置唯一载体）**；节点结构以 AI 定稿 §七为准（本表只登记不展开）；旧 action.json 内嵌 `chain` 读兼容+迁移提示 | L137、L269；AI L502、L512-515 |
| F15 | `drops` | object | 必填（普通怪） | 三类均 `[]` | `battle` / `special` / `death` 三类容器，见 1.5 | L30、L189-212 |
| F16 | `lore` | array | 选填 | `[]` | 条目 `{unlock, desc}`；unlock 1-100 递增；**解锁状态落玩家存档 codex_state，本文件不存状态** | L31、L216-230、L230 |
| F17 | `def_base` | number | 选填（木桩向） | 无 | ≥0；防御基准直读代入 或 映射 stats 体质，**二选一**（同配提示一致性） | L339 |
| F18 | `elem_res` | object | 选填（木桩向） | 无 | 元素 ID ∈ 注册表；值正=减伤 / 负=增伤（相对 formula.json 元素减伤系数） | L340 |

### 1.2 stats —— 9 属性（与玩家同源，无"气势"）

键名规范（本细化定型）：英文缩写键，固定 9 键（样本键 `hp`/`str` 佐证；玩家 9 属性同源）。

| # | 键 | 属性 | 类型 | 必填 | 默认（按模板） | 约束 | 来源 |
|---|---|---|---|---|---|---|---|
| S01 | `hp` | 生命 | number | 必填 | 模板基准 | ≥0；木桩=极大值（≥目标斩杀回合总输出上限） | L40、L338 |
| S02 | `mp` | 魔法 | number | 选填 | 模板基准 | ≥0 | L40 |
| S03 | `str` | 力量 | number | 选填 | 模板基准 | ≥0 | L40、L275 |
| S04 | `int` | 智力 | number | 选填 | 模板基准 | ≥0 | L40 |
| S05 | `con` | 体质 | number | 选填 | 模板基准 | ≥0 | L40 |
| S06 | `spr` | 精神 | number | 选填 | 模板基准 | ≥0 | L40 |
| S07 | `foc` | 专注 | number | 选填 | 模板基准 | ≥0 | L40 |
| S08 | `agi` | 敏捷 | number | 选填 | 模板基准 | ≥0 | L40 |
| S09 | `luk` | 幸运 | number | 选填 | 模板基准 | ≥0 | L40 |

### 1.3 weakness / resistance —— 双维弱点与天然抗性

| # | 路径 | 类型 | 必填 | 约束 | 来源 |
|---|---|---|---|---|---|
| W01 | `weakness.types` | string[] | 选填 | 伤害类型弱点（斩/打/突/魔），**数量不设限**；建议倾向：小怪 1 类 / 精英 2 类 / BOSS 2-3 类 | L55、L61 |
| W02 | `weakness.elements` | object | 选填 | 键=元素 ID（**8 元素注册表引用检查**，不硬编码清单；示例 `fire`/`water`）；值=增伤倍率，**×1.3 默认**；双维独立判定、同中叠乘（参考伊甸 ×2×2） | L56、L60、L297 |
| W03 | `resistance`（初始抗性键） | object（键=负面效果 ID） | 选填 | 值 0-100（初始层数/概率门槛）；示例键 `stun`/`shock`/`shadow_seal`，负面效果 ID 键可扩展 | L111、L116 |
| W04 | `resistance.immune` | string[] | 选填 | 完全免疫的负面效果列表（示例 `["poison"]`）；施加前拦截 | L112、L250 |

门禁管线顺序（效果系统联动，只读引用）：免疫判定 → 抗性初始层数 → PV 减半（PV>0 时数值减半、层数照常）→ 破防全量 [L250]。

### 1.4 actions / special_actions / chains —— 行动表、特殊行动、连招载体

**actions 条目**（3 字段）：

| # | 字段 | 类型 | 必填 | 约束 | 来源 |
|---|---|---|---|---|---|
| A01 | `actions[].action` | string | 必填 | 引用 action.json 的行动 ID，**引用必须存在**（校验器） | L279、L295 |
| A02 | `actions[].probability` | number | 必填 | **∈ {0,1}**：1=入池（参与随机池）、0=锚点（只被链/条件/状态机触发）；数值不参与概率计算 | L138、L145、L279 |
| A03 | `actions[].weight` | number | 必填 | ≥0；随机池内归一化权重（例：普攻 50/重击 30/蓄力 20 → 5/8、3/8、2/8）；**至少一个 probability=1 且 weight>0 的条目**（防空随机池，派生自归一化语义） | L145、L279 |

**special_actions 条目**（2 字段 + trigger 5 参数）：

| # | 字段 | 类型 | 必填 | 约束 | 来源 |
|---|---|---|---|---|---|
| A04 | `special_actions[].action` | string | 必填 | 引用 action.json 的行动 ID，引用存在 | L178、L296 |
| A05 | `special_actions[].trigger.type` | enum | 必填 | **13 类枚举**：`hp_below`/`pv_broken`/`get_up`/`battle_start`/`after_action`/`player_status`/`player_hp_below`/`turn_count`/`phase_changed`/`zone_changed`/`ally_dead`/`combo_broken`/`script`（权威=怪物行动AI定稿 §二）；`x_` 前缀可自定义扩展；旧枚举（phase_below/cooldown_ready/turn_elapsed/chain_complete/broken/revive/tag_trigger/enter_phase/delayed）为兼容别名可写不拦截 | L296 |
| A06 | `trigger.value` | number | 按类型 | 阈值类必带（`hp_below` 示例 value:30） | L178 |
| A07 | `trigger.timing` | enum | 按类型 | `current_turn`（当前回合）/ `next_turn`（下一回合）/ `first_turn`（第一回合） | L178-182 |
| A08 | `trigger.action` + `trigger.chance` | string + number | 按类型 | `after_action` 必带：action=衔接的行动 ID、chance 0-100（示例 80） | L182 |

§7.1 面向示例 5 类 ↔ 13 类枚举映射（S3 裁决落地）：

| §7.1 语义 | 示例写法（L178-183） | canonical 枚举 | timing 示例 |
|---|---|---|---|
| ① 血量低于 xx%（狂暴/残血大招） | `hp_below` | `hp_below` | current_turn |
| ② 防护崩溃后（破防反扑） | `pv_broken`（别名） | `broken` | next_turn |
| ③ 起身后（被击倒/控制恢复） | `get_up`（别名） | `revive` | next_turn |
| ④ 进入战斗时（开场技：第一回合、**换区后第一回合**） | `battle_start`（别名） | `enter_phase` | first_turn |
| ⑤ xx 行动后（固定连招锚点） | `after_action` | `after_action` | next_turn |

**chains 顶层表**（F14）：节点 `{action, chance 0-100, role: opener/anchor/mid/finisher, armor?, condition?}`，结构以 AI 定稿 §七为准 [AI L502、L512-515]；校验：action 引用存在 + chance 0-100 + role 枚举（拦截），链不成环（提示不拦截）[AI L524-525]。

### 1.5 drops —— 三类容器与掉落条目

**三类容器**（3 个）：`battle`（战斗掉落：战斗中触发，如行动后掉落）/ `special`（特殊掉落：条件结算）/ `death`（死亡掉落：死亡时结算）[L193-206、L208-210]。

**掉落条目 = 概率化 reward 条目**（4 字段，与任务系统定稿 §2.1 统一 reward 条目同键 `item`/`count`；命中后经框架 reward 解析器统一入账，怪物不另立发放逻辑）：

| # | 字段 | 类型 | 必填 | 默认值 | 约束 | 来源 |
|---|---|---|---|---|---|---|
| D01 | `drops.*[].item` | string | 必填 | — | 物品 ID，**引用存在**（对齐 reward 条目同键） | L212、L299 |
| D02 | `drops.*[].chance` | number | 必填 | — | **概率 0-100**（整数） | L212、L299 |
| D03 | `drops.*[].condition` | string | 选填 | 无 | 条件触发（special 类使用）：`pv_broken`（破防）/ `no_damage`（无伤）/ `after_action:<action_id>`（特定行动后，参照特殊行动条件） | L199、L209、L307 |
| D04 | `drops.*[].count` | number \| [min,max] | 必填 | 1 | 数量（示例 count:1）或**闭区间 [min,max]**（示例 [1,3]）；min≤max、非负整数 | L196、L202、L212 |

示例与定稿 L195-204 逐条同构：`{"item":"岩皮","chance":60,"count":[1,3]}`（battle）、`{"item":"破防晶","condition":"pv_broken","chance":100,"count":1}`（special）、`{"item":"兽骨","chance":100,"count":[1,2]}`（death）。

### 1.6 lore —— 图鉴情报

| # | 字段 | 类型 | 必填 | 约束 | 来源 |
|---|---|---|---|---|---|
| L01 | `lore[].unlock` | number | 必填 | **1-100**，条目间**递增**（10/50/100…）；解锁需求=图鉴进度阈值 | L221-227、L300 |
| L02 | `lore[].desc` | string | 必填 | 策略提示文本（弱点/机制/掉落情报），数量自由 | L221-228 |

存储边界：每怪 lore 解锁状态 + 图鉴完成度**存玩家存档 codex_state**（框架 3.7 持久化语义总表）；怪物模块只声明解锁需求与描述，不另立存储 [L230]。

### 1.7 字段计数

- **顶层 18**（F01-F18）；**全量 50** = 顶层 18 + stats 9 + weakness 2 + resistance 2 + actions 条目 3 + special_actions 条目 2 + trigger 参数 5 + drops 三类 3 + 掉落条 4 + lore 条 2。
- 不展开计数：`chains` 节点结构（按 AI 定稿 §七）、BOSS 编排扩展 `phases`/`zone_change`/`teach_map`/`pressure`（AI 定稿 §七，不在八段范围）。

---

## ② 难度模板（低/中/高）默认值表

映射裁决（S-模板）：**低=普通 normal / 中=精英 elite / 高=BOSS boss**（依据：L42-45 模板乘区按普通/精英/BOSS 叙述；L362"对齐内容包怪物难度模板（普通/精英/BOSS 三档取值）"）。模板数 = **3**。

| 模板 | 对应 tier | 属性默认（基准=玩家同级 [L43]） | PV 默认值 / 常见区间 | 行动表规模 | 特殊行动数 | 弱点倾向 | 斩杀节奏 | 来源 |
|---|---|---|---|---|---|---|---|---|
| 低 | normal | 全部属性 1×（同玩家同级基准） | 默认 10* / 0-20 | 1-2 招 | 0 | 1 类 | 3-8 回合 | L43、L101、L237-238、L61 |
| 中 | elite | **HP×2.5 / 攻击×1.2 / 防御×1.3**，其余 1× | 默认 75* / 50-100 | 2-4 招 | 1 | 2 类 | 10-15 回合 | L44、L101、L238、L61 |
| 高 | boss | **HP×10+ / 攻击×1.3 / 防御×1.5**（×10 为下限，可上调），其余 1× | 默认 300* / 200-500 | 4-6 招 | 2-4（阶段机制） | 2-3 类 | 15 分钟+（模拟器 40-60 回合参考） | L45、L101、L239、L61、AI L529 |

*细化定型：定稿仅给区间（L101），默认取区间中值（10/75/300），可改。

默认值落地语义：
- stats 漏配键 → 按所在档模板自动补全 + 校验器提示（防配装负担）[L42、L318]。
- pv 缺省 → 取档默认值（10/75/300）；显式配置仅做区间提示不拦截 [L298]。
- 木桩不套模板（HP 极大、防御/元素抗性自配，可对齐三档取值作参考）[L338、L362]。
- 模板仅作用于属性/PV 兜底；行动表、特殊行动、掉落、lore 无模板默认，按档规模建议（上表）配置 [L237-239]。

---

## ③ 掉落条目扩展（chance / condition / count 扩展域）

对齐统一 reward 条目（`item`/`count` 同键）+ 掉落特有扩展三件套：

| 扩展字段 | 类型 | 必填 | 约束 | 与 reward 条目关系 | 来源 |
|---|---|---|---|---|---|
| `chance` | number | 必填 | **0-100**（整数） | 掉落特有（概率化） | L212、L299 |
| `condition` | string | 选填 | 枚举：`pv_broken` / `no_damage` / `after_action:<action_id>`（破防/无伤/特定行动后） | 掉落特有（条件结算，special 类） | L199、L209、L307 |
| `count` | number \| [min,max] | 必填 | 数量或**闭区间 [min,max]**，min≤max、非负整数 | **与 reward 条目同键**（同 schema） | L196、L202、L212 |
| `item` | string | 必填 | 物品 ID 引用存在 | **与 reward 条目同键** | L212、L299 |

入账管线：掉落条目命中后 → 框架 reward 解析器统一入账（与任务/签到/NPC 同管线）；**怪物只配条目不另立发放逻辑** [L212]。经济联动：金币=等级×基准（战斗数值层 4.6）[L211]。

---

## ④ 木桩特例（tier: training / type: dummy）

**判定**：`tier: "training"` 或 `type: "dummy"` **至少其一**命中即按木桩处理 [L330、L336-337]。

| 类别 | 项目 | 规则 | 来源 |
|---|---|---|---|
| 忽略项（配置了也忽略，**黄提示不拦截**） | `drops` | 无掉落：忽略 drops；无金币、无经验、不计击杀类任务进度 | L349、L301 |
| | `lore` | 不入图鉴：无 lore 解锁，不占 codex_state 进度 | L351、L301 |
| | `pv` | **强制 0**（防 debuff 门禁干扰伤害测量）；配置了也忽略+黄提示 | L350、L301 |
| | `actions` / `special_actions` | **不可反击**：木桩不行动，忽略行动表/特殊行动/AI 状态机（配置了也忽略+黄提示） | L348 |
| 可配项 | `stats.hp` | HP 极大（≥ 目标斩杀回合总输出上限，防打死中断测量） | L338 |
| | `def_base` | 防御基准 ≥0：直读代入 或 映射 stats 体质，**二选一**（同配提示一致性） | L339 |
| | `elem_res` | 元素抗性基准：正=减伤 / 负=增伤（相对 formula.json） | L340 |
| | `weakness` | 可选：模拟目标怪弱点，测元素/类型配装；**豁免"每怪 ≥1 弱点"约束** | L341、L363 |
| 运行期 | 战斗规则 | 与普通战斗共用引擎（命中/会心/格挡/双通道/拦截链全量生效）；战败→无损退出（可配 0=按普通战败处理）；/撤退（=/逃跑）中断快照续玩 | L352-354 |
| | 入口 | /木桩 → 档位列表；/木桩 <序号或名称> → 进入；不在地图内，锁定/进入地图流程不适用 | L366-370 |
| | 调整木桩 | /调整木桩 <怪物名> 复制该怪 def_base/elem_res/弱点/抗性（HP 仍极大，不复制攻击/行动）；无参=重置；覆盖存 **dummy_override（settings/世界状态）**，**不落 enemies 文件** | L379-382 |
| 多档 | 档位建模 | 档位=一只木桩（独立 id），作者按需建 N 只（低防脆皮/高防重甲/高元素抗/高敏捷/全抗…）；数值建议对齐三档难度模板 | L357-362 |
| 校验 | 数值 | HP/防御/元素抗性基准**非负**（拦截）；弱点 ≥1 约束**不适用** | L363 |

---

## ⑤ 校验器规则

级别：**拦截**（结构错误，拒绝入库）/ **警告**（黄，不拦截）/ **提示**（信息）。定稿原条 7 条（R1-R7，对应定稿 L295-301 校验 1-7）+ 派生规则 8 条（R8-R15，语义直接推出）。

| # | 规则 | 级别 | 来源 |
|---|---|---|---|
| R1 | 行动 ID 引用存在（actions[].action ∈ action.json） | 拦截 | L295（校验 1） |
| R2 | 特殊行动触发条件合法：trigger.type ∈ 权威 13 类枚举（怪物行动AI定稿 §二，`x_` 前缀可扩展自定义）+ action 引用存在；旧枚举经别名归一表接受（黄提示迁移不拦截）| 拦截 | L296（校验 2）+ 细化_0 R-01 |
| R3 | 弱点允许 0 → 警告"该怪无弱点"；元素 ID ∈ 元素注册表（引用检查） | 警告 / 拦截 | L297（校验 3） |
| R4 | PV 非负（<0 拦截）；难度档常见区间仅提示"PV 超出该档常见区间，确认？" | 拦截 / 提示 | L298（校验 4） |
| R5 | 掉落 item 引用存在（条目结构对齐统一 reward 条目 schema，item/count 同键）+ chance 0-100 | 拦截 | L299（校验 5） |
| R6 | 图鉴情报 unlock 1-100 且递增 | 拦截 | L300（校验 6） |
| R7 | 木桩（tier:training / type:dummy）：drops/lore/pv 若配置 → 黄提示"木桩忽略掉落/图鉴/PV"（不拦截）；防御/元素抗性基准非负 | 警告 / 拦截 | L301（校验 7） |
| R8 | 必填与枚举：id/name 非空、id 唯一；tier ∈ {normal,elite,boss,training}；木桩标记至少其一（派生自结构定义） | 拦截 | L19-21、L336-337 |
| R9 | stats 键合法：9 键 ∈ 固定键集、数值≥0；漏配键按难度模板补全并提示（派生自模板语义） | 拦截 / 提示 | L40-45、L42、L318 |
| R10 | 概率语义：probability ∈ {0,1}；weight ≥0；随机池=probability=1 条目按 weight 归一化；**至少一个入池条目 weight>0**（防空随机池） | 拦截 | L138、L145、L279 |
| R11 | 触发参数完整性：按 type 校验必带参数（hp_below→value；after_action→action+chance）；chance 0-100；timing ∈ {current_turn,next_turn,first_turn} | 拦截 | L178-183 |
| R12 | 触发别名规范化：pv_broken/get_up/battle_start 接受（兼容 §七 示例），提示归一为 broken/revive/enter_phase | 提示 | L178-181 vs L296 |
| R13 | 掉落扩展域：condition ∈ {pv_broken, no_damage, after_action:<action_id>}；count 为 number 或 [min,max] 且 min≤max、非负 | 拦截 | L198-199、L212、L307 |
| R14 | 木桩数值与一致性：HP/def_base/elem_res 非负；def_base 直读与 stats 体质映射**二选一**（同配提示一致性）；木桩豁免 ≥1 弱点约束 | 拦截 / 提示 | L339、L363 |
| R15 | chains（若配置）：节点 action 引用存在 + chance 0-100 + role ∈ {opener,anchor,mid,finisher}（拦截）；链不成环（成环提示不拦截——环形链=有意的循环连招时放行）；旧 action.json 内嵌 chain 读兼容并提示迁移顶层 chains | 拦截 / 提示 | AI L524-525；L137、L269 |

编辑器联动（只读引用）：怪物页 9 标签页；勾选木桩后折叠为"属性+木桩"表单（dummy 开关 + 多档防御/元素抗性基准）；特殊行动条件表单=13 类触发下拉+参数；掉落条件下拉=破防/无伤/特定行动 [L303-307]。

---

## ⑥ 验收测试用例（14 条）

约定：输入为 enemies.json 片段；预期标注校验级别（拦截=拒绝 / 警告=黄不拦截 / 提示=信息）。

| # | 场景 | 输入要点 | 预期 |
|---|---|---|---|
| TC-01 | 合法普通怪全量 | 八段齐全：tier normal、stats 9 键、weakness、pv 20、resistance、actions×2、special_actions×1、drops 三类、lore[10,50,100] | 校验通过：无拦截、无警告 |
| TC-02 | stats 漏键模板补全 | normal 怪缺 `agi`/`luk` | 提示"按低档模板补全 agi/luk" + 自动补全模板基准值 |
| TC-03 | 无弱点怪 | `weakness: {}` | 警告"该怪无弱点"（不拦截） |
| TC-04 | 元素 ID 非法 | `elements: {"thunder": 1.3}`（thunder 未注册） | 拦截（元素注册表引用检查） |
| TC-05 | PV 约束 | ① `pv: -1`；② normal 怪 `pv: 80` | ① 拦截"PV 非负"；② 提示"PV 超出该档常见区间，确认？"（不拦截） |
| TC-06 | 行动引用缺失 | `actions: [{"action":"clawX",...}]` | 拦截（action.json 无 clawX） |
| TC-07 | 概率归一化语义 | `{claw,p=1,w=50}`、`{rock_roll,p=1,w=30}`、`{hard_body,p=0,w=100}` | 随机池=前两招：概率 50/80、30/80；hard_body 不入池（只被锚点/链触发）；p∉{0,1} → 拦截 |
| TC-08 | 触发类型与别名 | ① `type:"hp_above"`；② after_action 缺 chance；③ `type:"pv_broken"`（旧枚举别名）；④ `type:"player_status"`（权威枚举） | ① 拦截（非 13 类）；② 拦截（参数不完整）；③ 通过 + 黄提示归一为权威名；④ 通过（权威枚举，R-01） |
| TC-09 | 掉落扩展域 | ① `chance:150`；② `count:[3,1]`；③ `condition:"random"` | ① 拦截（0-100）；② 拦截（min>max）；③ 拦截（非枚举） |
| TC-10 | lore 递增 | `unlock:[10,50,40]`；`unlock:0` | 拦截（非递增）；拦截（超出 1-100） |
| TC-11 | 木桩忽略项 | `tier:"training"` 且配 drops/lore/`pv:30` | 三条黄提示"木桩忽略掉落/图鉴/PV"（不拦截）；运行期 pv 强制 0 |
| TC-12 | 木桩数值 | `stats.hp:-5`；`def_base:-1`；无 weakness | hp/def_base 负 → 拦截；无弱点 → 通过（豁免 ≥1 约束） |
| TC-13 | 三档模板默认值抽查 | ① 精英缺省 stats 仅配 hp；② boss 缺省 pv；③ normal 缺省 pv | ① 补全 HP×2.5/攻击×1.2/防御×1.3 基准；② 默认 300；③ 默认 10 |
| TC-14 | 换区/开场技行为验收（运行期） | 残血换区（/进入 通道）后续战 | 血量保持残血、PV 恢复一半（向下取整）、换区后第一回合触发开场技（enter_phase）；玩家离开副本 → 下次满状态重打 |

---

## 附录 A：行号索引（字段/规则 ↔ 定稿）

| 主题 | 行号 |
|---|---|
| 八段结构总览 | L15-33 |
| 9 属性 / 模板乘区 | L40-45 |
| 双维弱点 / ≥1 校验 / 双向 | L52-63 |
| PV 规则 / 恢复 / 档区间 | L67-102 |
| 天然抗性 / 门禁管线 | L106-118、L250 |
| 行动数据库 / 概率语义 | L122-148 |
| 特殊行动 5 类示例 / 13 类枚举 | L152-185、L296 |
| 掉落三类 / reward 条目扩展 | L189-212 |
| 图鉴 lore / codex_state | L216-230 |
| 难度分层数值 | L234-242 |
| 校验器 / 编辑器 | L291-308 |
| 训练木桩全节 | L325-392 |
| chains 载体 / 节点 / 校验 | 定稿 L137、L269；AI L502、L512-515、L524-525 |
