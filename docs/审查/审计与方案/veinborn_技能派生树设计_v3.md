# veinborn 阶段一技能设计 v3 —— 怪猎式武器派生树（脊剑士 = 太刀）

> 铁律：纯配置（skill_chains 现有能力，零新字段零删减）
> 参考：《太刀历代派生设计》+《太刀派生树汇总》（/root/docs_archive/派生设计/）
> 核心思想：**每个职业 = 一把怪猎武器**。技能栏只有起手式，派生靠 skill_chains
> 条件演化——玩家记「这招什么时候变成那招」= 记派生表，不记 20 个技能名。

## 〇、脊剑士 = 太刀 对应关系

| 怪猎太刀 | veinborn 脊剑士 | 引擎载体 |
|---|---|---|
| 练气槽（普通斩攒、气刃消耗） | 聚焦条（普攻+1、专精技耗） | resource_axis focus |
| 踏込斬り/縦斬り（攒气普攻） | 脊斩（basic 普攻） | skills basic |
| 突き/斬り上げ（中继回气） | 桩移（机动回精力） | skills active utility |
| 気刃斬りⅠ→Ⅱ→Ⅲ（消耗练气连段） | 不竭连斩（形态技连段） | skills + chain count |
| 気刃大回転斬り ⛔（终结+升色） | 不竭·终（300% 霸体终结） | chain count=3 replace |
| 見切り斬り（counter 成功回满） | 盾返（防反成功反击） | skills status + counter |
| 居合抜刀斬り（特殊纳刀后 counter） | 脊挡→盾返（受击转反击） | chain self_status |
| 色阶 白/黄/赤（升色增伤） | 部位破坏印记（已破→增伤） | marks target_marks |
| 練気解放円月斬り（气刃 loop 回Ⅰ） | 不竭连斩 max_combo reset（循环） | chain reset |

## 一、脊剑士派生树（ASCII，玩家可见的教学图）

```
[战斗开始] 聚焦 0/100
│
│  【攒气循环】（脊斩 普攻，无消耗，聚焦+1）
│  脊斩 ──► 脊斩 ──► 脊斩 ──► ...（连续 3 次）
│     │
│     └─ 第 4 刀 ──► ⛔ 不竭·终（300% 霸体，聚焦清空）
│
│  【部位破坏线】（打脉核/尾锤）
│  贯核击 ──► 贯核击 ──► ...（破坏值 0→120）
│     └─ 满 120 ──► ⛔ 破脉核（破坏+倒地，破坏值清零）
│
│  【防反线】（怪物狂暴时）
│  脊挡 ──► （怪物攻击被挡）──► 盾返（反击+破绽）
│
│  【回避线】（怪物宣泄大招时）
│  堑跃 ──► （大招回合）──► 完全回避
│
│  【机动回气】（任意时点，回精力）
│  桩移 ──► 泄压（怪困斗满时导走大招）
│
│  【专精形态】（聚焦满翻面）
│  不竭连斩 ──► 不竭连斩 ──► 不竭连斩 ──► ⛔ 不竭·终
│      （形态内连段，回精力，3 连出终）
```

## 二、数据表达（全 skill_chains，纯配置）

### 链 1：脊斩连段（普攻→终结，攒气循环）
```json
{
  "id": "chain_slash_combo",
  "trigger_skill": "rb_slash",       // 脊斩
  "max_combo": 3,
  "max_combo_behavior": "reset",     // 4 刀后重置回脊斩（循环）
  "steps": [{
    "from": "rb_slash", "to": "rb_form_finisher",  // 第 4 刀 → 不竭·终
    "condition": {"count": {"eq": 3}},
    "mode": "replace", "armor": true, "consume": 0,
    "variant_override": {"power": 300}
  }]
}
```

### 链 2：部位破坏线（贯核击→破脉核）
```json
{ "id": "chain_core_break", "trigger_skill": "rb_core_strike",
  "max_combo": 1, "max_combo_behavior": "reset",
  "steps": [{ "from": "rb_core_strike", "to": "vb_core_breaker",
    "condition": {"target_marks": {"break_vein_core": {"min": 120}}},
    "mode": "replace" }] }
```

### 链 3：防反线（脊挡→盾返，受击触发）
```json
{ "id": "chain_guard_counter", "trigger_skill": "rb_guard",
  "max_combo": 1, "max_combo_behavior": "reset",
  "steps": [{ "from": "rb_guard", "to": "rb_counter",
    "condition": {"self_status": {"guarding": {"min": 1}}},
    "mode": "replace" }] }
```

### 链 4：机动泄压（桩移→泄压，困斗满时）
```json
{ "id": "chain_leap_vent", "trigger_skill": "rb_leap",
  "max_combo": 1, "max_combo_behavior": "reset",
  "steps": [{ "from": "rb_leap", "to": "vb_vent",
    "condition": {"target_marks": {"surge_mark": {"min": 6}}},
    "mode": "replace" }] }
```

### 链 5：专精连段（不竭连斩→不竭终，形态内）
```json
{ "id": "chain_ridge_combo", "trigger_skill": "rb_form_strike",
  "max_combo": 3, "max_combo_behavior": "reset",
  "steps": [{ "from": "rb_form_strike", "to": "rb_form_finisher",
    "condition": {"count": {"eq": 3}},
    "mode": "replace", "armor": true,
    "variant_override": {"power": 300} }] }
```

## 三、脉矢手 = 弓（阶段一占位 → v0.2 补全派生）

| 怪猎弓 | 脉矢手 | 规则 |
|---|---|---|
| 蓄力射击 | 脉矢 | 连射 3 发第 4 变贯瞳狙击 |
| 曲射/爆破 | 贯脉矢 | 破坏值满 → 破脉核（远程破部位）|
| 滑步回避 | 后跃 | 受击后脱身回精力 |
| 麻痹/眠瓶 | 绊索 | 困斗满时绊倒 |
| 刚射 | 警戒射击 | 怪物狂暴时重击 |

## 四、阶段一落地范围

1. 脊剑士完整（现有 15 技能重组为派生树，玩家技能栏收 5 个起手式：脊斩/贯核击/脊挡/堑跃/桩移）
2. 技能栏精简：**起手式 5 + 专精 1 = 6 格**（玩家记 6 条派生规则）
3. 隐藏演化技能（不竭终/破脉核/盾返/泄压 等不进技能栏——它们是被派生出来的）
4. 战报教学：「脊斩×3 → 变化！不竭·终」显式提示演化发生

## 五、待确认

1. **演化技能要不要隐藏**（不进技能栏，只有触发时战报出现）？还是技能栏全显示（灰态提示「可派生」）？
2. 派生树教学：注册后发「教学」看自己的派生树图（ASCII）？
3. 阶段一脊剑士先落地（脉矢手 v0.2）？
