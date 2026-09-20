# 《蚀脉猎师》纯配置转换设计（把做不出来的机制翻译成现有原语）

> 铁约束：**只填 content/veinborn/ JSON + 复用现有指令，零新增代码**。凡是框架没有的机制，全部翻译成「现有原语的组合」。本清单逐条给出「原设计 → 纯配置翻译 → 校验/先例」。
> 依据：本地框架 @ 035c973（M13 收官）真实代码与实例核验，非假设。
> 状态：2026-09-02 初稿，逐条标注 ✅ 可行 / ⚠️ 有条件可行 / 🔴 确实不行（含补偿）

---

## 〇、纯配置转换的"原语库"（框架已实证可用的积木）

| 原语 | 真实能力（已核验） | 位置 |
|---|---|---|
| **技能** | kind/type/power/attack_type/element/effects/hits/energy_cost/energy_gain/tag/cooldown/job_form/consume_marks | content/test_demo/skills.json |
| **印记 marks** | 施加必中；重复=+count **至 max_stack 封顶不溢出**；`duration:"battle"` **永续不 tick**；`duration:"turns:N"` 回合末 -1 归零；clear_marks 原子动作整组清空 | core/marks.py（apply_add L243 / evaluate L367 / resolve L415） |
| **印记条件** | 条件引擎原生：`target_marks{mark_id:{min/max}}`、`marks_single`、`marks_total/set/any` —— **按层数判定**，已 battle 接线 | core/combo.py _eval_marks_sub L372 + battle.py L1898 _marks_lookup |
| **印记消费** | 技能 `consume_marks {mark_id: count}` 读层消费 | skills.json（heavens_smash/flame_burst 先例） |
| **印记→公式** | marks `resolve()` 提供 `[我方/对方印记:名]` 公式占位符 → 按层数动态数值 | core/marks.py L415 + formula 引擎 |
| **技能链 skill_chains** | `job_scope` + `trigger_skill` + `steps[{from,to,tag,condition,priority,mode,armor,consume,variant_override}]` → **派生技/终结技**；step 可带 condition（含印记条件） | test_demo/skill_chains.json（chain_rage 先例） |
| **资源轴** | 玩家数值轴 `energy_cost/gain`；敌方轴 `resource_state.enemy` 双轨骨架 + battle_start_init("enemy")（**回合 tick +1 需代码，纯配置无**） | core/resource_axis.py / resource_lifecycle.py |
| **transform** | `duration:"battle"+revert:false` = 恒效不还原（validator 允许）；`turns:N+revert:true` 限时 | jobs.json（berserker 先例） |
| **敌方行动** | special_actions `trigger`（hp_below/battle_start/turn_count/...）+ `post_state`；enemy `actions`+权重；chain 连招 | test_demo/enemies.json（rock_ogre/ash_wraith） |
| **姿态/换阶段** | dungeon_boss `phases` 阈值 (100,60,30) 可覆盖（70/35）；zone_change 对象 | core/dungeon_boss.py + enemies.json |
| **AI 意图预告** | action.json preview/preview_chain/reveal_condition + monster_intent 整链 + BREP-12 渲染 | 全链路现成 |

> 核心洞察：**"印记层数"是纯配置里唯一的"计数器"**。一切需要计数/蓄力/进度/耐久的东西（破坏值、困斗、充能、架势层数）都翻译成「带层数的印记」。

---

## 一、逐机制转换清单

### 1. 部位破坏（原设计：独立 HP 桶+清零触发）→ ✅ **你给的方案完全可行，且更强**

**翻译（采纳你的方案 + 强化）**：

```
① 破坏值印记（每部位 1 个）：脉核印记 / 尾锤印记 / 前肢甲印记 / 脊板印记
   marks.json: {id:"break_core", name:"脉核破坏值", max_stack:120, duration:"battle",
                appliable_to:["enemy"], polarity:"negative"}
   → 攻击技能 effects 带 mark_add 打部位 → 层数累加到 120 封顶

② 满 120 → 技能链派生「部位破坏」：
   skill_chains.json: steps 里一条 from:"对脉核技", to:"脉核破坏·破", 
                      condition:{target_marks:{break_core:{min:120}}}
   → 破坏值满 → 破技解锁（派生技）→ 打出后 consume_marks 清零重来 或保留

③ 部位破坏状态 = 「破坏印记」（区别于破坏值印记）：
   {id:"core_broken", max_stack:1, duration:"battle", polarity:"negative"}
   → 破技 effects mark_add core_broken 1
   → battle 型永续、不 tick、不会被回合末消除（唯一风险：敌方 clear_marks 技能——见坑 3）

④ 增伤读取：
   A. 派生技「对已破部位重击」：steps condition target_marks:{core_broken:{min:1}} → power 高
   B. 动态增伤：公式占位符 [对方印记:core_broken] ×N（若公式引擎支持，逐层增伤）
   C. 破技本身 carry 强化：破掉尾锤后「尾锤技失效」= 敌方 special_actions 该技 trigger
      加 condition: 玩家无 core_broken 才可放？——查证：enemy special 无玩家印记条件 →
      ⚠️ 见坑 4，用 enemy 实体阶段替代
```

**逐项核验**：✅ 满栈封顶（marks.apply_add L255）✅ battle 永续（L323 tick 只碰 turns 型）✅ 层数条件（combo C-2 target_marks 已接线）✅ consume_marks 清零（heavens_smash 先例）✅ 破技解锁（chain step condition）✅ 印记层数→公式（marks.resolve L415）

> **比你原方案更强的点**：max_stack 到顶封顶**不会消失**——所以「破坏值」印记本身可以当「已满」的持久信号，不必一定转成第二个破坏印记。但为了"已破坏 vs 未破坏"的二分语义（比如破尾锤后尾锤技没了），还是建议**满后派生破技 → 破技挂 core_broken 破坏印记**，二段式更清晰。

### 2. 困斗值 surge（原：敌方资源轴每回合+1）→ ⚠️ **半可行（每回合+1 需代码，宣泄可行）**

**纯配置能做的**：
- 宣泄（困斗满大招）：enemy special_actions `trigger` 现成（hp_below/battle_start/turn_count/... 非 surge_full）
- 玩家"机动牌泄困斗" = 机动牌打敌挂「疏导」印记 → 敌方某行为被印记条件压制（若 enemy AI 条件可读玩家施加的敌侧印记——待核）
- 困斗值 = 敌侧「困斗」印记层数：玩家打机动牌 → 敌侧困斗印记 -N（mark_remove 原子动作有）……但 **敌方每回合自动 +1 没有任何现成 tick 挂点**（resource_state.enemy 有骨架但无回合自动增长接线）

**🔴 确实不行**：敌方资源轴"每回合 +1"（困斗蓄能）——纯配置无法让怪物自己涨印记。补偿：
- **改用敌方特殊行动替代**：boss 每 N 回合（turn_count trigger）放一次大招 = 周期蓄爆的近似（省掉"可被机动牌压制"的交互，但保留"每几回合来一次大的"）
- 或：**宣泄条件挂 hp_below**（血线暴走，非困斗）——完全现成
- 机动牌的价值从"泄困斗"改成"回精力 + 挂破绽/疏导印记增伤"——精力循环保留，泄压交互退化为周期性

### 3. 专精聚焦 transform → ✅ **完全现成（设计稿唯一写对的）**
- `duration:"battle"+revert:false`（恒效）或 `turns:N+revert:true` 都 validator 合法
- focus 资源轴 = stats.json + 攻击牌 energy_gain → 满 4 → transform_skill（energy_cost {focus:4}）→ 翻面
- 狂战士实例同款照抄

### 4. 四色行动卡 → ✅ **可行（但 tag 值域封闭，需借 attack_type/effects 表达）**
- 玩家技能落 **skills.json**（非 action.json）
- tag 值域锁死六枚举 → **四色不加 tag**，用 `attack_type`（斩/打/射）+ effects 差异表达（攻=伤害+focus gain，机动=回精力+挂印记，格挡/躲避=guard/evade 状态）
- 精力循环：energy_cost/energy_gain 现成
- ⚠️ 纯配置无法"未出某色牌→受威胁"（回合末无玩家出牌色判定）→ 见 §二 坑 2

### 5. 序列/连段 → ✅ **现成（按真实 schema）**
- skill_chains：trigger_skill + steps[{from,to,condition}]——把"攻→攻→机动"翻译成三个技能 id 的 from→to 链（**不是颜色词数组**）
- 派生终结技 variant_override.power 300（chain_rage 先例）

### 6. 意图预告 3 槽 → ✅ **现成**（preview 三件套 + BREP-12 整链）

### 7. 姿态 Stance I/II/III → ✅ **现成（按真实语义）**
- dungeon_boss phases 阈值覆盖 (70,35) → 同一实体换阶段行为
- 或 zone_change 对象换区/换阶段

### 8. 坚韧/创伤/受威胁/易伤/眩晕 → ✅ **现成**（stats/pv + marks + statuses）
- 易伤 = vulnerable 印记 max_stack:1 + damage_mult×2（设计稿自己写了）
- 眩晕 = stun 印记（跳行动）

### 9. 部位破坏"尾锤技失效" → ⚠️ 需 enemy 实体/阶段配合（见坑 4）

### 10. 强化 Boost/暴走 Rampage → ✅ **现成**（special_actions chain_ref + post_state）

### 11. 铁匠铺锻造 → ✅ **现成**（forge + equipment.json + 素材两档）

### 12. 倒地窗口（破坏后 ×1.5）→ ✅ **现成**（破坏印记 → 派生破技挂 toppled 状态 damage_mult×1.5）

### 13. KO/Rise、Volley 连珠、Berserker、Recycle、Stealth → ✅ **现成**（statuses/hits/transform/proc/stealth tag？——stealth 需查 enemy trigger 排除条件，多半 ⚠️ 降级）

---

## 二、🔴 确实不行清单（纯配置做不出 + 补偿）

| # | 原机制 | 为什么不行（实证） | 纯配置补偿 |
|---|---|---|---|
| **1** | 敌方资源轴每回合自动 +1（困斗蓄能/任何"怪物自己涨"） | resource_state.enemy 双轨有骨架，但无「回合 tick 自动增减」接线；无 surge_full 触发类型 | turn_count 周期大招近似；或 hp_below 血线暴走 |
| **2** | 回合末判定"玩家本回合未出某色牌→受威胁" | battle 回合收尾无玩家出牌色审计点（防御牌回精力已有，但"没出走势→负面"无挂点） | 受威胁降级为状态印记：被特定攻击挂上；或干脆不做 |
| **3** | 印记"不可被消除"（破坏印记怕敌方净化） | marks clear_marks 原子动作存在，敌方若配净化技可整组清；无"免疫消除"标记 | ① 不给敌方配 clear_marks 技能（配置选择）；② 或破坏印记用"满后派生不消费"模式（值印记满 120 后不再被任何东西消费，天然像永续状态） |
| **4** | 部位破坏后"该部位技能失效"（敌方 AI 条件读玩家印记） | monster_conditions 触发枚举**无玩家印记条件**（有 player_status 但那是玩家身上的状态）；敌方能否因玩家施加的敌侧印记改变行为需再核——大概率只能靠阶段/实体切换 | 用 enemy 实体姿态推进近似：破脉核 → zone_change 换"破核阶段"实体（该阶段无尾锤技） |
| **5** | 暴露面/扇区站位、地形标记 | 无站位概念 | condition + 战报装饰（设计稿已妥协） |
| **6** | 多人协作 Aggro/Assist/Taunt | 引擎 1v1 | 单人（设计稿已妥协） |
| **7** | stealth（不触发颜色反应） | enemy trigger 无颜色排除条件 | 降级/不做 |
| **8** | part_status 独立 HP 桶精确模拟（多部位并行受击、破坏顺序） | 印记方案是"按技能挂对应部位值"顺序破坏，非"每部位独立 HP 谁先打谁破" | 接受顺序化破坏（技能指定部位），或用多阶段实体 |

---

## 三、转换后 veinborn 的"机制成立度"总评

| 原 Primal 机制 | 纯配置后 | 成立度 |
|---|---|---|
| 四色行动 + 精力循环 | skills 能量收支 + attack_type 差异 | 🟢 高 |
| 专精聚焦 transform | battle+revert:false 恒效 | 🟢 高（原样） |
| 部位破坏 | **破坏值印记→满→破技→破坏印记→增伤**（你的方案） | 🟢 高（略顺序化） |
| 倒地窗口 | 破坏印记 → toppled 状态 ×1.5 | 🟢 高 |
| 序列连段 | skill_chains from→to 链 | 🟢 高 |
| 意图预告 | preview 整链 | 🟢 高（原样） |
| 姿态 I/II/III | dungeon_boss phases / 实体阶段 | 🟢 高 |
| 困斗蓄能+宣泄 | turn_count 周期大招（非蓄能制） | 🟡 中（失"可压制"交互） |
| 机动牌泄困斗 | 机动牌 → 回精力 + 挂破绽印记 | 🟡 中（改价值） |
| 受威胁 | 降级或不做 | 🔴 低 |
| 部位技失效 | 实体阶段近似 | 🟡 中 |
| 暴露面/地形/多人/stealth | 不做 | 🔴（设计稿已妥协） |

**净结论**：**核心体验保住 ~8 成**——四色精力循环、专精恒效、部位破坏、倒地窗口、姿态推进全部成立（后三者靠你的印记思路）。真正丢的是「困斗蓄能可被机动牌压制」这一个交互层（退化为周期大招），以及受威胁/站位等边角。对第一个预设包来说，**这个成立度足够开做**，且完全零代码。

---

## 四、开工前还需拍板/核验的 3 件事

1. **破技 consume 清零 vs 保留**：部位破坏后，破坏值印记清零（可再次破坏=多阶段）还是保留当"已破"信号？——若部位是一次性（破尾锤→尾锤没了），建议派生破技**不消费**，破坏值印记满 120 后自然封顶常驻 + 破技加 core_broken 破坏印记（二分语义）
2. **tag 四色被红拦**：确认接受「四色用 attack_type/effects 表达，不加 tag」还是「接受给 tag 枚举加四值」（后者是改 schema，非纯配置）
3. **enemy 阶段（坑 4）**：部位破坏与姿态推进是否合并成"同一实体多阶段"（破脉核=进阶段 2 同时姿态推进），避免敌方 AI 读玩家印记的不确定——待实机核 enemy 条件后定

---

*下一步建议：把本清单 + 已核验字段回写成 veinborn 的 03 schema 修正稿（真实 JSON schema），即可直接开工 content/veinborn/。*
