# veinborn · 03 Schema 修正稿（回写真实引擎字段）

> 性质：veinborn 原设计稿 03（/tmp/veinborn-hunters/03_内容包与数据schema.md）→ 按 QBot-TurnTellerRPG 真实引擎 schema 回写的**落地版**。
> 依据：test_demo 实际 JSON（skills/jobs/skill_chains/marks/stats/effects/statuses/enemies）+ M13 契约（细化_6a/6b/6c）+ 框架新能力（monster_conditions enemy_mark/player_mark、effects condition 门控、event_dispatcher trigger/on_gain/on_lose）。
> 拍板：① **纯配置铁律**，四色不加 tag（tag 保持六枚举），靠 attack_type+effects+intent 表达（攻=攻击/机动=跃空/格挡=防反/躲避=闪反）；② 部位破坏=独立印记二段式，姿态=血量 zone_change，两概念独立；③ 首版范围=先 03 修正稿 → 再精简验证包 → 再完整 MVP。
> 生成：2026-09-02 ｜ 仓库基线：HEAD ee42654（工作区干净）

---

## 〇、真实 schema 总览（test_demo 实证，修正稿的字段基线）

### 0.1 玩家技能落 skills.json（非 action.json）

- **action.json = 怪物/敌方行动**（带 weight/probability/preview/intent/hungry/tags）
- **skills.json = 玩家技能**（M13 6a 契约 24 字段）

skills.json 24 字段实证：

```
id/name/type/kind/power/attack_type/element/effects/mp_cost/cooldown/tag/armor/interrupt/
chain_refs/consume_marks/job_restrict/job_form/level/hits/trigger_limit/desc/hit_mod/crit_mod/block_mode
```

type ∈ active/basic/passive/trigger；kind ∈ damage/heal/status/utility/control；
attack_type ∈ slash/blunt/pierce/magic/none（斩/打/突/魔）；element ∈ 8 元素注册表；
tag ∈ none/combo/combo_preserve/combo_push/interrupt/armor（**锁死六枚举**）；block_mode ∈ auto/normal/ignore

### 0.2 资源轴在 stats.json 顶层注册

rage（数值型）实证：

```json
"rage": {"name":"怒气","type":"rage","icon":"💢","base":0,"max":100,
         "reset":"battle","display":"status_line","growth":0}
```

element_energy（子池型）实证：`type:"element_energy"` + max_per_pool + pools[] + pool_icons{}。
**敌方资源轴无回合 tick 自动增减接线**（resource_lifecycle 只有玩家侧 energy_cost/gain），surge 每回合 +1 需靠怪每回合 mark_add 自挂（拍板方案）。

### 0.3 effects.json = 效果定义（L0 词汇表 + 引用/条件/容器）

实证 test_demo：heal/dot/shield/dispel/lifesteal/mitigation + 引用 `{effect,overrides}`。
框架新能力：效果条目可带 `condition`（combo.evaluate_condition 求值：self_marks/target_marks/marks_single/marks_total/set/any）与 `trigger`/`on_gain`/`on_lose`（event_dispatcher 三时点）。

### 0.4 statuses.json = 状态（buff/debuff，独立 HP 桶无，走 marks）

实证字段：id/name/type(buff|debuff)/max_stack/duration{turns,charges}/decay(per_turn)/effects[]/on_tick。
**无 damage_mult 字段**——增伤走派生 overrides 或 effects condition 挂增伤效果。

### 0.5 marks.json = 印记（一切计数器的唯一纯配置载体）

实证字段：id/name/icon/type(mark)/max_stack/appliable_to([self|enemy])/polarity(positive|negative)/element/duration(battle|turns:N)。
- **battle 型永续不 tick**；turns:N 回合末 -1
- 重复施加 = +count 至 max_stack **封顶不溢出**
- monster_conditions 新增：enemy_mark/player_mark 条件（battle 真正接线，可读玩家施加的敌侧印记）

### 0.6 skill_chains.json = 玩家派生链

实证一条（chain_rage）：id/name/job_scope/trigger_skill/max_combo/max_combo_behavior/steps[{from,to,tag,condition,priority,mode,armor,consume,variant_override}]。
condition 支持 count{eq} / target_marks{min} 等（combo.py）。

### 0.7 enemies.json = 敌方实体

实证：stats/weakness{types,elements}/pv/pv_recover/resistance/actions[{action,probability,weight,preview,reveal_condition}]/
special_actions[{id,action,trigger{type,value,timing},once,priority,post_state{state,turns}}]/
zone_change{enabled,hp_threshold,targets,timing}。

monster_conditions 触发 15 类（含 enemy_mark/player_mark）：

```
hp_below/pv_broken/get_up/battle_start/after_action/player_status/player_hp_below/
turn_count/phase_changed/zone_changed/ally_dead/combo_broken/script/enemy_mark/player_mark
```

**无 surge_full 触发类型**——困斗宣泄用 enemy_mark min 条件（enemy_mark 读困斗印记层数 ≥ 阈值触发宣泄技）。

### 0.8 形态/职业 = jobs.json transform

实证 berserker：transform{transform_skill/transform_to/duration(turns|battle)/turns/revert/cooldown/dispel_reverts/state_policy{combo,marks,buff}/skill_set/equip_restrict/derive_chains}。
- 专精恒效 = duration:"battle" + revert:false（validator 合法）
- derive_chains 限定形态派生链；job_form 挂技能

### 0.9 部位状态部分（原设计新增 schema parts[]）→ **不做**，改印记二段式

原 `parts:[{id,hp,on_break}]` + part_status.py ≈30 行新代码 → **零代码印记方案**（见 §四）。

---

## 一、目录结构（修正）

原设计稿列 action.json（玩家四色）→ **改 skills.json**（玩家技能库）+ action.json 保留但仅放怪物意图/敌方行动（veinborn 若有怪物动作进 action.json，参考 test_demo action.json）。

```
content/veinborn/
├── manifest.json          ← 包清单（modules 声明，类比 test_demo）
├── settings.json          ← 三币、死亡惩罚
├── stats.json             ← hp/mp + 四 combat + stamina/focus（玩家轴，stats.json 顶层）
├── formula.json           ← 伤害公式参数 + 8 元素注册表（stamina 不建子池，V6）
├── effects.json           ← 效果（guard/evade/vent_surge/topple/破绽增伤…）
├── statuses.json          ← 状态（受威胁/倒地/形态标记…）
├── marks.json             ← 印记（精力轨可留作未来；破绽/撼击/破坏值×4/部位已破×4…）
├── items.json             ← 消耗品（脉火/药水）
├── equipment.json         ← 武器（脊刃/长弓）/护甲/头盔
├── skills.json            ← ★玩家四色行动卡（攻/跃空/防反/闪反）+ 技能组
├── jobs.json              ← ★2 职业 + 专精 transform（脊剑士/脉矢手）
├── skill_chains.json      ← ★跨回合派生链（部位破坏/序列终结）
├── enemies.json           ← ★原兽（砾冕 3 姿态实体 + 困斗印记宣泄）
├── maps.json              ← 群脊荒原地图
├── dungeon.json           ← 脉堑猎场
├── npc.json               ← 龙骨驿站 NPC
├── shop.json              ← 驿站商店
├── quest.json             ← 任务（第 1 猎季）
├── checkin.json           ← 丰饶符
└── (无新增代码文件)
```

★ = 本作核心 + M13 首批真实启用。**零新增 py 文件**（批 4 part_status/surge_axis 不需要）。

---

## 二、stats.json · 资源轴（修正）

原稿三条轴 stamina/focus/surge。**surge 是敌方轴 → 敌方轴无回合 tick 自动 +1 → 移除 surge 资源轴，改困斗印记**（见 §五）。玩家两轴照 stats.json 真实注册：

```json
{
  "hp":    {"name":"生命","type":"resource","base":100,"max":9999},
  "mp":    {"name":"灵能","type":"resource","base":30,"max":9999},
  "stamina": {"name":"精力","type":"rage","icon":"⚡","base":5,"max":6,
              "reset":"battle","display":"status_line","growth":0},
  "focus":   {"name":"聚焦","type":"rage","icon":"🎯","base":0,"max":6,
              "reset":"battle","display":"status_line","growth":0},
  "str": {"name":"力量","type":"combat","base":10,"growth":2},
  "con": {"name":"体质","type":"combat","base":10,"growth":2},
  "agi": {"name":"敏捷","type":"combat","base":10,"growth":2},
  "foc": {"name":"专注","type":"combat","base":10,"growth":2}
}
```

> type 用框架实证的 `"rage"`（数值型轴）而非原稿臆造 "resource"；rage 型 base/max/reset/display 字段全部对齐 test_demo。精力=手牌（5/6 起手，攻牌耗、防御牌回）。

---

## 三、四色行动卡 → skills.json（拍板①纯配置）

**tag 不加四色值**（锁死六枚举）。语义锚定 + 引擎承载：

| 色（词） | 真实语义 | 引擎承载 |
|---|---|---|
| 🔴 攻（攻击） | 输出 | skills kind=damage + energy_cost {stamina} + energy_gain {focus} |
| 🔵 机动（跃空） | 位移/泄压 | skills kind=utility/status + energy_gain {stamina} + effect: 敌侧困斗印记 -N / 挂破绽 |
| 🟡 格挡（防反） | 减伤/预判反击 | skills kind=status + block_mode/guard 效果 + energy_gain |
| 🟢 躲避（闪反） | 闪避/反击 | skills kind=status + evade 效果（若引擎有，否则降级减伤）+ energy_gain |

**四色在战斗/链里的区分靠 attack_type + intent + kind + effects，tag 只作展示派生（保持六枚举内 none 或不用）。**

### 3.1 脊剑士（ridge_blade）技能组示例（真实字段）

```json
[
  {"id":"rb_slash","name":"脊斩","type":"basic","kind":"damage","power":120,
   "attack_type":"slash","element":null,"effects":[],
   "mp_cost":0,"cooldown":0,"tag":"none","armor":false,"interrupt":false,
   "chain_refs":{},"consume_marks":{},"job_restrict":"ridge_blade","job_form":null,
   "energy_cost":{"stamina":1},"energy_gain":{"focus":1},
   "block_mode":"auto","desc":"攻·斩：耗1精力，聚焦+1"},

  {"id":"rb_leap","name":"跃空","type":"basic","kind":"utility","power":0,
   "attack_type":"none","element":null,
   "effects":[{"type":"mark_remove","target":"enemy","mark":"surge_mark","count":1}],
   "energy_gain":{"stamina":1},"tag":"none","desc":"机动·跃空：回1精力，疏导敌方困斗1层"},

  {"id":"rb_counter","name":"防反","type":"basic","kind":"status","power":0,
   "attack_type":"none","element":null,
   "effects":[{"effect":"guard_up"}],"energy_gain":{"stamina":1},
   "desc":"格挡·防反：本回减伤，回1精力"},

  {"id":"rb_dodge","name":"闪反","type":"basic","kind":"status","power":0,
   "attack_type":"none","element":null,
   "effects":[{"effect":"evade_up"}],"energy_gain":{"stamina":1},
   "desc":"躲避·闪反：闪避本回攻击，回1精力"}
]
```

> 细节待 content 校验器红黄灯校准（guard_up/evade_up 效果词需 effects.json 定义；若 evade 引擎不支持则降级 mitigation 减伤——精简验证包时实证）。

---

## 四、部位破坏 = 独立印记二段式（拍板②，纯配置核心机制）

**设计稿原方案**（parts[] + part_status.py ≈30 行新代码）→ **废弃，改二段式印记**。每部位 2 条印记 + 派生链，全链路零代码：

### 4.1 印记定义（marks.json）

**第一段 · 破坏值印记**（每部位 1 条，耐久/进度计数器）：

```json
[
  {"id":"break_vein_core","name":"脉核破坏值","icon":"🔶","type":"mark",
   "max_stack":120,"appliable_to":["enemy"],"polarity":"negative",
   "element":null,"duration":"battle","desc":"打击脉核累积破坏值，满120触发脉核破坏"},
  {"id":"break_tail_hammer","name":"尾锤破坏值","icon":"🔷","type":"mark",
   "max_stack":90,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"打击尾锤累积破坏值，满90触发尾锤破坏"},
  {"id":"break_forelimb","name":"前肢甲破坏值","icon":"🟧","type":"mark",
   "max_stack":80,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"打击前肢甲累积破坏值，满80触发前肢甲破坏"},
  {"id":"break_ridge_plate","name":"脊板破坏值","icon":"🟩","type":"mark",
   "max_stack":100,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"打击脊板累积破坏值，满100触发脊板破坏"}
]
```

**第二段 · 已破坏印记**（每部位 1 条，二分语义「已破 vs 未破」，battle 永续）：

```json
[
  {"id":"core_broken","name":"脉核已破","icon":"💔","type":"mark",
   "max_stack":1,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"脉核已破坏：倒地窗口"},
  {"id":"tail_broken","name":"尾锤已破","icon":"🩹","type":"mark",
   "max_stack":1,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"尾锤已破坏：范围技移除"},
  {"id":"forelimb_broken","name":"前肢甲已破","icon":"🩹","type":"mark",
   "max_stack":1,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"前肢甲已破坏：攻击削弱"},
  {"id":"ridge_broken","name":"脊板已破","icon":"🩹","type":"mark",
   "max_stack":1,"appliable_to":["enemy"],"polarity":"negative",
   "duration":"battle","desc":"脊板已破坏：暴露脉核"}
]
```

### 4.2 破坏流程（skill_chains.json 派生链）

每部位一条「对部位技 → 破技」链：

```
打部位技（mark_add break_X +N）→ 破坏值印记层数涨
  → 满 max_stack（120/90/80/100）
    → skill_chains 派生破技（condition: target_marks {break_X: {min: max}}）
      → 破技打出：
        a) effects mark_add 部位已破印记 1（core_broken/tail_broken/...）
        b) 可选 consume_marks {break_X: max} 清零（重新破坏多阶段）或保留（一次性）
        c) 破技 effect 挂倒地窗口（toppled 增伤，见 4.3）
```

**skill_chains 真实形态（对齐 chain_rage）**：

```json
{
  "id":"chain_core_break","name":"脉核破坏",
  "job_scope":"ridge_blade","trigger_skill":"rb_core_strike",
  "max_combo":1,"max_combo_behavior":"reset",
  "steps":[{"from":"rb_core_strike","to":"vb_core_breaker",
            "tag":"none",
            "condition":{"target_marks":{"break_vein_core":{"min":120}}},
            "priority":1,"mode":"replace","armor":false,"consume":0,
            "variant_override":{}}]
}
```

> 部位技 rb_core_strike = skills.json 一条带 `effects:[{"type":"mark_add","target":"enemy","mark":"break_vein_core","count":20}]` 的主动技（打 6 下满 120）。破技 vb_core_breaker = 高 power + mark_add core_broken + 挂 toppled。
> **破坏值印记满后保留**（max_stack 封顶不溢出，天然像「已满」信号）；破坏性由破技的 consume_marks 决定清零重来 or 保留一次性（拍板 4.2b 留到精简包实证：破坏值印记本身不消费，已破印记管二分）。

### 4.3 破坏效果映射

| 部位 | 破技 | 破坏效果（effects/statuses） |
|---|---|---|
| 脉核 | vb_core_breaker | 挂 toppled 状态（增伤 ×1.5，用 effects condition 或派生 overrides）→ **倒地窗口** |
| 尾锤 | vb_tail_breaker | 移除敌方范围技：该技 special_actions 加 enemy_mark absent 条件（tail_broken 不存在才可放）→ **部位技失效**（框架新能力 enemy_mark 实证可行） |
| 前肢甲 | vb_forelimb_breaker | 敌方攻击技 damage 降（action power 降 or 玩家增伤）→ **攻击削弱** |
| 脊板 | vb_ridge_breaker | 暴露脉核：脉核部位技派生解锁 or 玩家对脉核增伤 → **expose_core** |

> 尾锤技失效 = enemy special_actions trigger 条件 enemy_mark {mark:"tail_broken", absent:true}（monster_conditions 实证：enemy 条件可读玩家施加的敌侧印记）。

### 4.4 部位技的「无破坏印记才可用」

对部位技加 trigger 条件 enemy_mark absent（对应部位已破 → 该部位技不可再打）——功能一 enemy_mark 的 absent 条件正是为此设计。

---

## 五、困斗 = 困斗印记（非资源轴；拍板②延伸）

**原设计 surge 资源轴每回合 +1 → 引擎无敌方轴 tick → 改困斗印记（surge_mark）**：

```
surge_mark：appliable_to:[enemy], max_stack:6, duration:"battle", polarity:"negative"
  敌方每回合开始/行动：怪行动里 mark_add self surge_mark 1（怪行动通道 effects 实证可行，替代回合自动+1）
  玩家机动牌（跃空）：effects mark_remove enemy surge_mark 1（疏导蚀脉，拍板①）
  困斗满 6 → enemy special_actions 宣泄技 trigger:{type:"enemy_mark", mark:"surge_mark", min:6}
    → 宣泄后 mark_remove surge_mark 5（回落至1）
```

> 这是「困斗蓄能 + 机动牌泄压」的纯配置化：怪物自己每回合挂困斗印记 = 蓄能；玩家跃空牌 mark_remove 泄压；满 6 触发宣泄大招（enemy_mark min 条件）。**完整保留可压制交互**（比 02 稿的 turn_count 周期大招更还原）。

---

## 六、姿态推进 = zone_change 血量触发（拍板②）

**原设计 zone_change 数组 → 真实字段对象**（test_demo 实证 ash_wraith/mirror_guardian）：

```json
{"enabled":true,"hp_threshold":0.7,"targets":["gravelcrown_stance2"],"timing":"after_action"}
{"enabled":true,"hp_threshold":0.35,"targets":["gravelcrown_stance3"],"timing":"after_action"}
```

砾冕 3 姿态 = **3 个独立 enemy 实体**（gravelcrown_stance1/2/3，不同 stats/weakness/actions/special），zone_change 目标指向下一个实体。姿态推进与部位破坏**无耦合**（部位是玩家打的，姿态是血线自动推）。

---

## 七、受威胁（原设计，拍板后处理）

原设计「回合末判定未出某色牌 → 受威胁」——引擎回合末无玩家出牌审计挂点（坑 2）。
**修正**：受威胁降级为「状态印记」——敌方特定攻击命中挂 threatened 状态（debuff，turns:N，减益 effects），或完全不做。精简验证包先不做，进完整 MVP 再定（02 §五语义妥协登记）。

---

## 八、enemies.json · 砾冕 3 姿态（真实字段草图）

```json
{
  "id":"gravelcrown_stance1","name":"脊冢兽·砾冕（姿态Ⅰ）",
  "tier":"boss",
  "stats":{"hp":3000,"str":18,"con":16,"agi":6,"def":12},
  "weakness":{"types":["pierce"],"elements":{"fire":1.3}},
  "pv":100,"pv_recover":"battle_end",
  "resistance":{"stun":30,"immune":["poison"]},
  "actions":[
    {"action":"bb_slam","probability":0.4,"weight":3,"intent":"伤害"},
    {"action":"bb_tail_sweep","probability":0.3,"weight":2,"intent":"范围","preview":{"level":2,"category":"范围"}},
    {"action":"bb_charge","probability":0.2,"weight":1,"intent":"蓄力","preview":{"level":2,"category":"蓄力"},"reveal_condition":"charge_start"}
  ],
  "special_actions":[
    {"id":"vb_unleash","action":"bb_rampage",
     "trigger":{"type":"enemy_mark","mark":"surge_mark","min":6},"once":false,"priority":30,
     "post_state":{"state":"ebbed","turns":2}},
    {"id":"vb_tail_gone","action":"bb_tail_sweep",
     "trigger":{"type":"enemy_mark","mark":"tail_broken","absent":true,"timing":"current_turn"},"once":false,"priority":25,
     "desc":"尾锤已破：范围技失效"}
  ],
  "zone_change":[
    {"enabled":true,"hp_threshold":0.7,"targets":["gravelcrown_stance2"],"timing":"after_action"},
    {"enabled":true,"hp_threshold":0.35,"targets":["gravelcrown_stance3"],"timing":"after_action"}
  ],
  "drops":{
    "battle":[{"item":"vein_shard","chance":1.0,"count":[1,2]}],
    "special":[{"item":"gravelcrown_plate","chance":1.0,"count":[1,1]}],
    "death":[{"item":"barrow_core","chance":1.0,"count":[1,1]}]
  },
  "lore":[{"unlock":10,"desc":"驮着半座骨冢行走的食脉巨兽……"}]
}
```

> 姿态实体每回合困斗蓄能（行动挂 mark_add surge_mark 1）+ 蓄满宣泄 + 玩家可跃空泄压 = **困斗闭环**；zone_change 0.7/0.35 换姿态。

---

## 九、jobs.json · 2 职业（专精 = transform 恒效）

### 9.1 脊剑士 ridge_blade

```json
{
  "id":"ridge_blade","name":"脊剑士","difficulty":"simple",
  "playstyle":"近身连段，专精不竭",
  "recommended_newbie":true,
  "resource_axes":["mp","stamina","focus"],
  "mechanic_tags":["近战","连段","专精"],
  "weapon_types":["ridgeblade"],
  "growth":{"str":2.0,"con":1.5,"foc":1.0},
  "transform":{
    "transform_skill":"rb_mastery","transform_to":"inexhaustible_form",
    "duration":"battle","revert":false,"cooldown":0,"dispel_reverts":false,
    "state_policy":{"combo":"keep","marks":"keep","buff":"keep"},
    "skill_set":"mastery_skills","derive_chains":["chain_core_break"]
  },
  "description":"猎势·不竭：聚焦满翻面，本局连段回精力"
}
```

### 9.2 脉矢手 vein_archer（长弓远程，专精贯瞳）

```json
{
  "id":"vein_archer","name":"脉矢手","difficulty":"simple",
  "playstyle":"远程狙射，专精贯瞳",
  "recommended_newbie":false,
  "resource_axes":["mp","stamina","focus"],
  "mechanic_tags":["远程","连段","专精"],
  "weapon_types":["longbow"],
  "growth":{"str":0.5,"agi":2.0,"foc":1.5},
  "transform":{
    "transform_skill":"va_mastery","transform_to":"piercing_eye_form",
    "duration":"battle","revert":false,"cooldown":0,"dispel_reverts":false,
    "state_policy":{"combo":"keep","marks":"keep","buff":"keep"},
    "skill_set":"mastery_skills","derive_chains":["chain_piercing_shot"]
  },
  "description":"猎势·贯瞳：聚焦满翻面，解锁终结技"
}
```

---

## 十、effects / statuses / marks 词表（veinborn 需要定义的）

| 对象 | id | 真实承载 |
|---|---|---|
| effect | guard_up | 格挡减伤效果（type: mitigation or shield，给 guard 技能用） |
| effect | evade_up | 闪避效果（若引擎支持；否则降级 mitigation 减伤 + 战报措辞） |
| effect | vent_surge | 泄困斗：mark_remove surge_mark（机动牌载体，直接 skills effect 写 mark_remove 原子更简单） |
| effect | topple_buff | 倒地增伤（×1.5）——用 effects condition 挂 damage 类效果 or 派生 overrides，实证定 |
| status | threatened | 受威胁（debuff，turns:N，若做） |
| status | toppled | 倒地（buff，破技挂，标记 + 增伤入口） |
| status | inexhaustible_form | 脊剑士形态标记（transform 恒效展示） |
| status | piercing_eye_form | 脉矢手形态标记 |
| mark | vulnerable | 破绽（max_stack:1 + 增伤 ×2，duration turns:2） |
| mark | stun | 撼击（max_stack:1 + 跳行动） |
| mark | surge_mark | 困斗（max_stack:6，battle） |
| mark | break_*×4 | 破坏值（120/90/80/100，battle） |
| mark | *_broken×4 | 部位已破（max_stack:1，battle） |

> 增伤表达：vulnerable ×2 / toppled ×1.5 / 破坏后增伤 = **effects condition 门控 + 派生 overrides**（功能二实证：`{effect:"smite", condition:{target_marks:{vulnerable:{min:1}}}}` 有破绽这刀才触发）。实际数值在精简验证包用 validator + 战斗冒烟校准。

---

## 十一、转译批次规划（按拍板③：先修正稿 → 精简验证包 → 完整 MVP）

### Phase 1 · 精简验证包（本次做完，战斗核心冒烟）

| 批 | 内容 | 验收 |
|---|---|---|
| 1 | stats 轴 + marks（破坏值×4/已破×4/surge/vulnerable/stun）+ effects/statuses 基础词表 | validator 零红 |
| 2 | jobs 2 职业 + transform 恒效 + skills 四色表（脊剑士组打样） | validator 零红 |
| 3 | enemies 砾冕 stance1（+2/3 简化）+ 困斗印记蓄能/宣泄 + 部位技/破技链 | 战斗冒烟：困斗满宣泄 + 部位破坏→倒地→增伤全链 |
| 4 | 精简包 verify + 冒烟 + demo_* 零回归 | verify_veinborn 绿 |

### Phase 2 · 完整 MVP（下一轮）

| 批 | 内容 |
|---|---|
| 5 | 脉矢手完整技能组 + 派生链（贯瞳终结） |
| 6 | 装备/锻造（脊刃/长弓 + 素材）+ 强化闭环 |
| 7 | 地图/猎场/第 1 猎季任务 + NPC/商店 |
| 8 | 受威胁/倒地/易伤数值校准 + 战报模板 + 丰饶符 + 全仓回归 |

---

## 十二、validator 避坑清单（转译时逐条对照）

| 坑 | 规避 |
|---|---|
| R-1 类型错 | power 用数字；int 别写 3.0 |
| R-2 负数 | energy_gain ≥0；泄困斗走 mark_remove，不写负 gain |
| R-4 引用悬空 | jobs resource_axes 必须在 stats 存在；transform_to/skill_set/derive_chains 全真实；zone_change targets 真实 |
| R-5 结构错 | 派生链不成环；manifest 顶层对象 |
| V6 子池红拦 | stamina/focus 不做 pools（rage 型），色不建子池 |
| V7 层数红拦 | 破坏值/困斗走 marks 不混 energy |
| tag 值域 | 四色不加 attack/maneuver/parry/dodge（红拦），tag 保持 none/combo 系 |
| transform V4 | battle + revert:false（恒效），battle + revert:true 红拦 |
| attack_type | 斩=slash/打=blunt/突=pierce/魔=magic（test_demo 实证，非中文） |
| element | ∈ 8 元素注册表（fire/water/wind/earth/moon/void/light? 以 formula.json 实证为准） |

---

## 十三、开放待实证（精简验证包内解决，不阻塞开工）

1. **guard_up/evade_up** 效果词：引擎 mitigation/shield 实证后定具体 type（防反/闪反语义保留在技能 name/intent，机制落到减伤/闪避）
2. **toppled 增伤载体**：effects condition 挂 damage 效果 vs 派生 overrides 二选一实证
3. **敌方每回合自挂困斗印记**：怪行动 effects mark_add self surge_mark 是否 battle 通道放行（转换设计 §一 1 实证可行，但需冒烟确认）
4. **破坏值印记清零 or 保留**：一次性 vs 可重破，精简包打一次 boss 后定
5. **vulnerable/stun 的增伤/眩晕效果**：接 effects condition（×2）或状态跳行动，冒烟验证

---

*下一篇：content/veinborn/ 精简验证包（Phase 1 批 1-4）*
