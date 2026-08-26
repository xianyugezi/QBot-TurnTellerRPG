# NPC 系统设计定稿 v1.3.1（npc.json · 发牌员网络）

> 版本：v1.3.1 · 2026-08-16
> v1.3 变更：退出词统一（离开/再见/退出）+ 对话恢复简报（2.4）+ 已听回看图鉴 + 菜单 ≤6 折叠 + 条件 schema 补 param + op 符号双写 + event 原语兼容 + repeat 枚举定 once/daily + heal formula 类型 + buff 三表引用 + 字段计数 14
> v1.3.1 变更：repair 交互标注「依赖装备耐久系统（框架未实现）」——当前降级为不可用/友好提示，编辑器表单同步标注（审查 C1）
> v1.2 变更：条件统一 {var,op,value} 三要素（全系统复用）/ 会话路由规则（对话优先于快捷表）/ 当前商店机制（中断恢复）/ 一次一物置灰 / interactions 子字段表补齐
> 定位：RPG 框架 npc.json 模块转正——NPC 定义/对话/交互/地图挂点/发任务/商店/情报/教学
> 核心一句话：**NPC = 世界里的发牌员网络——玩家只记一个指令（/对话），NPC 用单轮交付把世界递到玩家面前，条件驱动决定给什么、不给什么**
> 整合：Agent A 盘点（P0 缺失修正）+ Agent B 体验设计 + Agent C 数据结构 + 3 子 agent 缺漏检查（P0：解析冲突/中断恢复/一次一物；H：条件语法/挂点漂移/子字段/登记）
> 用户拍板：/对话 指令 / 单轮+对话树深度可配（settings max_dialog_depth） / 送礼好感度=可选模块默认关 / 条件统一 A / 一次一物自决 / 会话路由不冲突 / 当前商店机制
> 硬约束：1v1 回合制 / QQ 文字 / 碎片化 / 小白优先 / 编辑器零代码 / 只建议不限制

---

## 一、核心哲学：NPC = 发牌员网络

```
玩家三问（多想一步=体验失败）：
  ① 这人是谁？——名字/身份/位置（一眼认出）
  ② 他能给我什么？——货物/任务/情报/教学（一眼看懂）
  ③ 我怎么拿？——一个指令，数字选项（一步到位）

发牌员世界观（羊蹄山之魂启示）：
  世界的 NPC 是发牌员网络——玩家与任何 NPC 交互，NPC 从事件牌组抽牌
  决定"这次给你什么"。系统层面：事件牌组靠发牌员密度运转。

五条体验铁律：
  ① 只建议不限制：不交互 NPC 也玩得下去（主线任务板兜底）
  ② 默认值兜底：NPC 配置漏字段 = 合理默认，绝不报错
  ③ 记住最少：玩家只需记一个主指令（/对话）
  ④ 一次一物：每次交互最多交付一条新线索（告知有成本）
  ⑤ 断了能续：任何时刻中断，回来从断点继续
```

---

## 二、指令设计（用户拍板：/对话 + NPC 列表序号）

```
/对话             查看当前地图 NPC 列表（序号+名字+类型图标）
  · "这里的人：1.🔨铁匠·老周 2.🧺杂货商人·林 3.📖学者·杜"
/对话 1           序号快捷对话（名称优先，失败按序号）
/对话 铁匠·老周    名称对话（禁空格，允许 ·/Ⅱ）
/查看 [NPC名]     查看信息/携带物（可选）
/送礼 [NPC名] [物品*数量]  好感度（可选模块，默认关）
对话中：选择 1     选交互功能（见三）
对话中：继续/退出   翻下一段/结束

- 命名铁律：NPC 名禁空格（防解析歧义），允许 ·/Ⅱ（铁匠·老周）
- 无 NPC 地图：/对话 → "当前地图没有可对话的人"
- 快捷：/对话 高频，可快捷绑定/免前缀
- 指令别名：内容包世界观定制（修仙世界可别名"拜访"）
```

### 2.1 会话路由规则（v1.2，用户拍板：P0-1 解析冲突修复）

```
【对话会话激活时，解析路由（写死）】：
  纯数字（1/2/3）/ 继续 / 离开/再见/退出 / 选择 N  → 送对话状态机（选交互/翻页/结束）
  "攻击1" / "使用1" / "背包2" 等【带指令词】 → 正常指令解析（不冲突）
  "快捷绑定 1=攻击" 后对话中发"1" → 会话路由优先（选选项，不触发攻击）
  → 快捷表仅在无会话上下文生效（对话会话激活时跳过快捷表纯数字匹配）
  【结束词统一】：离开 / 再见 / 退出 三词同义（玩家学哪个都能结束）
  【菜单固定】：菜单末尾按钮固定"N. 离开"（N=选项数+1，与路由词严格一致）

【为什么不会冲突】：
- 对话中"1" = 选交互选项（会话子词）
- 战斗中"1" = 快捷绑定（无会话上下文，快捷表生效）
- "使用1"（背包物品）/ "攻击1"（技能）= 带指令词，永远正常解析
→ 玩家在对话中也能"使用1"吃药补状态，再"继续"对话
```

### 2.2 当前商店机制（v1.2，用户拍板：P0-2 商店中断恢复）

```
- 打开 NPC 商店后：记录【当前商店】= 该 NPC 的 shop_refs（地图级状态）
- 玩家处于该地图：/商店 → 进入当前商店（NPC 商店，随时可回）
  · 商店选购中退出 → 在地图内 /商店 直接回来（不用重找 NPC）
- 离开该地图：当前商店状态清除 → /商店 → 默认全局商店
- 说明：商店选购中断 = 不丢（当前商店机制兜底），无需子界面快照
```

### 2.3 一次一物落地（v1.2：交付后置灰"已听"）

```
- 信息类交互（intel/线索/情报/教学）交付后：该选项标记"已听"（置灰）
  · 下次可选但无新内容（"你已经听过了"）
  · 【已交付标记落玩家存档（3.7），不落会话快照（会话快照按 settings lifecycle.recycle_days 回收，见开发规则 §7.4）】
  · 【回看出口】：情报/线索交付同时写入图鉴（图鉴可回看，置灰不死胡同）
- 功能类交互（quest/shop/heal/give_item）：不置灰（可重复使用）
- 效果：菜单层一次一物（信息不重复喂），功能照常用
```

### 2.4 对话恢复简报（v1.3：碎片化恢复模板）

```
【续·对话】铁匠·老周
  · 菜单层中断 → 恢复重显菜单（上次未选，直接选）
  · 子界面层中断（heal 确认/任务交付确认/领取中）→ 简报注明：
    "上次的『领取补给』未完成，请重新选择"（防误以为操作已完成）
  · 长叙述分段位置入快照（page 索引，恢复从断段继续）
```

---

## 三、NPC 交互层（用户拍板：对话 → 选择 N 功能菜单）

### 3.0 菜单上限（≤6 选项，超屏折叠）
```
- 交互菜单最多显示 6 个选项（+固定 N.离开）
- 超过 6 个：折叠为"7.更多…"（二级菜单）
- 条件提示一行（"需要：等级 ≥10"），不展开长文本
```

### 3.1 交互流程
```
/对话 1 → NPC 交互菜单（显示可用交互选项）：
  铁匠·老周：1.接任务 2.打开商店 3.帮忙治疗 4.打听消息
选择 1 → 条件判定 → 执行交互
  · 条件满足：执行（发任务/开商店/治疗...）
  · 条件不满足：提示（"需要先完成【铁矿收集】任务"）
  · 条件选项可隐藏/置灰（作者可配）
```

### 3.2 交互动作枚举（丰富）
| action | 说明 | 示例 |
|---|---|---|
| quest | 接任务（候选任务+条件） | 接点活儿 |
| shop | 打开商店（shop_refs） | 看看货物 |
| heal | 治疗（付费/免费，恢复 HP/MP） | 帮忙治疗 |
| give_item | 获得道具（一次性/每日/条件） | 领取补给 |
| buff | 临时增益（效果引用） | 祝福一下 |
| repair* | 修理装备（可选） | 修修装备 |
| teleport | 传送（地图引用） | 送我去 X |
| intel | 情报（图鉴解锁） | 打听消息 |
| tutorial | 教学（first_meet） | 教教我 |
| reply | 聊天（纯回复） | 随便聊聊 |

> \* repair：依赖装备耐久系统（框架未实现——items 无 durability 字段、装备引擎无磨损）。内容包启用耐久时开放；当前降级：交互选项不可用，触发给友好提示（"没有需要修理的装备"）。

### 3.3 交互配置（npc.json interactions 数组）
```json
"interactions": [
  { "action": "quest", "text": "接点活儿", "quests": [...], "condition": {...} },
  { "action": "shop", "text": "看看货物", "shop_refs": ["blacksmith_shop"], "condition": { "var": "level", "op": "ge", "value": 5 } },
  { "action": "heal", "text": "帮忙治疗", "cost": { "coins": 50 }, "heal": { "hp": "100%", "mp": "100%" },
    "condition": { "var": "item_count", "op": "ge", "value": 50, "item": "金币" } },
  { "action": "give_item", "text": "领取补给", "items": [{ "id": "药水", "count": 3 }],  // items[] = 统一 reward 条目 schema（任务系统定稿 §2.1；id ≡ item 键）
    "repeat": "daily" }   // repeat 语义不变（once/daily）
]
```

> 统一入账：give_item 经框架 reward 解析器入账（物品入包，与任务/签到同管线）——发放器唯一实现 = 框架 reward 解析器，NPC 只配条目 + repeat 规则
>
> repair 暂无可配置示例——依赖装备耐久系统（框架未实现），启用后按 3.4 子字段表配置（cost 可选，免费=省略）

### 3.4 interactions 子字段表（v1.2 补齐，逐 action）
| action | 子字段 | 类型/引用 | 说明 |
|---|---|---|---|
| quest | quests[] | ref quest.json | 候选任务+条件 |
| shop | shop_refs[] | ref shop.json | 商店引用（打开后=当前商店，2.2） |
| heal | cost{coins} | settings 货币键 | 治疗费（免费=省略） |
| | heal{hp,mp} | int 或 "N%" | 恢复量（百分比串=按上限） |
| give_item | items[]{id,count} | ref items.json | 发放道具（items[] 元素 = 统一 reward 条目 schema，任务系统定稿 §2.1；id ≡ item 键，同一框架 reward 解析器入账） |
| | repeat | once/daily | 重复规则（默认 once；daily=每日重置；条件语义并入公共 condition） |
| buff | effects[] | ref 效果注册表 | 临时增益（effects/statuses/marks 三表统一注册，ID 跨表唯一） |
| | turns | int | 持续回合（效果自带可省） |
| repair* | cost | settings 货币键 | 修理费（可选，按装备耐久计价）——依赖装备耐久系统（框架未实现，见 3.2 注），内容包启用耐久时开放；当前降级：表单/选项置灰，触发给友好提示 |
| teleport | map | ref maps.json | 传送目标地图 |
| | cost | settings 货币键 | 传送费（免费=省略） |
| intel | intel_refs[] | ref enemies lore | 图鉴情报（交付后置灰"已听"） |
| tutorial | tutorials[] | ref 教学模板 | 机制教学（first_meet 首见） |
| reply | text[] | str | 聊天回复（随机/循环） |
| 公共 | text | str | 菜单显示文案 |
| | condition | 条件（四章） | 触发条件（不满足=提示/隐藏/置灰） |

---

## 四、条件触发（用户拍板：统一三要素 {var, op, value} + 全系统复用）

### 4.0 统一条件语法（v1.2：与任务系统/派生条件共用一套引擎）
```
条件 = { var: 键, op: 运算符, value: 值, param?: 参数 }
- var 键空间（统一注册表）：level/job/job_level/prof_level/has_item/
  not_has_item/item_count/has_quest/quest_completed/reputation/
  main_progress/codex/time/is_day/is_night/affection + x_ 扩展
  [签到:连续天数] / [签到:本月天数] / [签到:今日已签]（签到定稿 v2.13 登记，2026-08-16 补入互译表）
- op 运算符（9 种）：gt/ge/lt/le/eq/ne/between/is/not
  【符号双写等价】：>= = ge ｜ > = gt ｜ <= = le ｜ < = lt ｜ = = eq ｜ != = ne
- param：可选第 4 键（参数化 var 的指定目标，如 item_count 指定物品）
  { var: "item_count", op: "ge", value: 50, param: "金币" }
- 任务系统 conditions（v1.0 起全文统一本引擎四要素）：
  · 规范写法即 {var,op,value,param}——任务定稿 v1.0.1 已全文迁移；中文变量键经 §4.3 互译表映射英文条件键
  · 迁移期兼容：旧 {type,var,op,value} 结构仍接受——type 忽略（var 归一），导入器/校验器黄提示"旧格式，建议迁移"
  · event 原语（{type:"event", event:"map_enter", target, count}）等价映射（两种写法同义，规范用后者）：
    { var: "[事件:map_enter]", op: "ge", value: count, param: target }
- 派生条件原语集：兼容（连段/印记原语映射 var 键空间）
→ 一套条件引擎，任务/NPC/派生全系统复用，零重复
```

### 4.1 比较运算符（全量 9 种）
```json
// 数值比较
{ "var": "level", "op": "gt", "value": 10 }         // 等级 > 10
{ "var": "level", "op": "ge", "value": 10 }         // 等级 ≥ 10
{ "var": "level", "op": "lt", "value": 10 }         // 等级 < 10
{ "var": "level", "op": "le", "value": 10 }         // 等级 ≤ 10
{ "var": "level", "op": "eq", "value": 10 }         // 等级 = 10
{ "var": "level", "op": "ne", "value": 10 }         // 等级 ≠ 10
{ "var": "level", "op": "between", "value": [5, 10] }  // 等级 5~10

// 布尔/枚举
{ "var": "has_item", "op": "is", "value": "铁矿" }         // 是否持有铁矿
{ "var": "not_has_item", "op": "is", "value": "铁矿" }     // 是否不持有
{ "var": "is_night", "op": "is", "value": true }            // 是否夜晚
{ "var": "has_quest", "op": "is", "value": "q_ore_20" }    // 是否已接取
{ "var": "quest_completed", "op": "is", "value": "q_ore_20" }  // 是否已完成
{ "var": "job", "op": "eq", "value": "剑士" }               // 职业=剑士
{ "var": "job", "op": "ne", "value": "元素法师" }            // 职业≠元素法师
{ "var": "time", "op": "eq", "value": "night" }             // 时间段=夜晚
```

### 4.2 运算符总表（编辑器下拉）
| 运算符 | 含义 | 适用 |
|---|---|---|
| gt | 大于 > | 数值 |
| ge | 大于等于 ≥ | 数值 |
| lt | 小于 < | 数值 |
| le | 小于等于 ≤ | 数值 |
| eq | 等于 = | 数值/枚举 |
| ne | 不等于 ≠ | 数值/枚举 |
| between | 区间 [a,b] | 数值 |
| is | 是否有（布尔） | has_item/is_night/has_quest... |
| not | 是否不（布尔取反） | not_has_item/not_job... |

> 兼容：旧 min/max 简写自动映射（min=ge、max=le）；任务系统旧 {type,var,op,value} 结构 type 字段忽略（var 归一）——迁移期兼容，任务定稿 v1.0.1 起新配置一律 {var,op,value,param}

### 4.3 var 键空间总表（条件可引用）
| 类 | var 键 | 说明 |
|---|---|---|
| 任务类 | has_quest / quest_completed / quest_state | 是否接取/完成/状态枚举 |
| 物品类 | has_item / not_has_item / item_count | 是否持有/数量 |
| 职业类 | job / job_level | 职业/职业等级 |
| 熟练类 | prof_level | 熟练度 |
| 状态类 | level / reputation / main_progress / codex | 等级/声望/主线/图鉴 |
| 累计类 | gain_count / kill_count | 累计获得/累计击杀（longline_counters 长线计数表，任务系统新登记 v1.0） |
| 副本类 | dungeon_clear | 副本通关次数（param=副本 ID） |
| 事件类 | [事件:xxx] | 事件触发计数（var 固定前缀 [事件:]，事件名必先在事件注册表登记——预置清单见 4.3.2，内容包扩展须登记；param=事件目标） |
| 时间类 | time / is_day / is_night / season / period / weather | 时间段/是否白天夜晚；season/period/weather = 时间天气系统设计定稿 v1.0 新登记键（2026-08-16，取值见 4.3.1） |
| 关系类 | affection | 好感度（可选模块） |
| 组合 | any / all / not | OR/AND/取反（嵌套） |

### 4.3.1 中文变量键 ↔ 英文条件键 互译表（别名映射 · 唯一权威）
```
- 变量体系中文键（效果表达式变量体系定稿 v1.2）与条件引擎英文键的显式别名映射；
  校验器/编辑器按本表互译（编辑面板显示中文变量键，配置存储与校验一律用英文条件键）
- 任务系统侧速查：任务系统设计定稿 §一「条件键别名映射」（字段口径以本节为准）
```

| 中文变量键（变量体系 v1.2） | 英文条件键 {var, op, value, param} | 说明 |
|---|---|---|
| [当前等级] | { var: "level" } | 玩家等级 |
| [背包:X] | { var: "item_count", param: X } | 背包物品数量（泛化引用） |
| [累计获得:X] | { var: "gain_count", param: X } | 累计获得（longline_counters，任务新登记） |
| [累计击杀:X] | { var: "kill_count", param: X } | 累计击杀（longline_counters，任务新登记） |
| [副本通关:X] | { var: "dungeon_clear", param: X } | 副本通关次数 |
| [图鉴完成度] | { var: "codex" } | 图鉴解锁百分比 |
| [主线进度] | { var: "main_progress" } | 主线进度 |
| [熟练度:X] | { var: "prof_level", param: X } | 熟练等级（7 级体系） |
| [声望:板] | { var: "reputation", param: 板ID } | 声望等级（5 级制；param 缺省=全局声望） |
| [职业] | { var: "job" } | 职业 |
| [季节:X] | { var: "season", param: X } | 当前季节 == X（X ∈ 四季枚举；时间天气定稿 §4.0 登记） |
| [时段:X] | { var: "period", param: X } | 当前时段 == X（X ∈ 五时段枚举；时间天气定稿 §4.0 登记） |
| [天气:X] | { var: "weather", param: X } | 玩家当前所在图当前天气 == X（X ∈ 注册天气集；时间天气定稿 §4.0 登记） |
| 事件原语 on_*("目标") / {type:event, event, target, count} | { var: "[事件:事件名]", op: "ge", value: count, param: 目标 } | 事件型（4.0 映射）；事件名必先在事件注册表登记（4.3.2），未登记=校验器黄提示 |

### 4.3.2 事件注册表（事件型条件的事件名登记 · 建议 + 提示）
```
- 背景：事件型条件 { var: "[事件:落石]" } 的事件名是自由字符串——拼错一个字条件永假，
  校验器无从区分"未登记事件"与"自定义事件"，小白作者必踩。
- 机制：事件 ID 由框架登记（预置事件清单见下），条件引擎/校验器/编辑器按注册表识别事件名；
  内容包可扩展自定义事件，但扩展事件必须先登记进内容包 events 注册表
  （如 events.json / content.json 的 events 段：登记 事件ID + 触发时机 + 说明，触发时统一入事件计数）
- 预置事件清单（框架登记，可直接引用；文档各处示例已引用的事件名如 map_enter 视同已登记）：
  · [事件:副本通关:ID]  副本通关（:ID=副本 ID）
  · [事件:任务完成:ID]  任务完成（:ID=任务 ID）
  · [事件:签到]         每日签到
  · [事件:怪物击杀:ID]  击杀怪物（:ID=怪物 ID）
  · [事件:等级提升]     玩家升级
  · [事件:NPC对话:ID]   与 NPC 完成一次对话（:ID=NPC ID）
  （:ID 写在事件名内，便于校验器对目标 ID 做引用存在性检查；也可沿用 4.0 映射把目标写进 param）
- 校验器（只建议不限制，不硬拦）：事件名未在注册表 → 黄色提示"事件未登记，确认拼写或先登记"；
  事件名已登记但 :ID 目标不存在 → 黄色提示引用检查
- 编辑器：事件条件下拉 = 注册表事件列表（预置 + 内容包已登记事件），另留"自定义（未登记）"入口
```

### 4.4 组合（any/all/not 嵌套）
```json
{ "all": [
    { "var": "level", "op": "ge", "value": 10 },
    { "var": "has_item", "op": "is", "value": "铁矿" }
] }
{ "any": [ { "var": "job", "op": "eq", "value": "剑士" },
           { "var": "job_level", "op": "ge", "value": 2 } ] }
```

### 4.5 条件反馈
```
- 满足：正常显示交互选项
- 不满足：默认显示但提示（"需要：等级 ≥10 且 持有 铁矿"）——作者可配隐藏/置灰
- 只建议不限制：条件永假仅黄色提示（"这个交互永远触发不了？确认"）
```

---

## 三、对话结构（用户拍板：单轮交付 + 对话树深度可配）

```
【单轮交付（默认，零配置）】
- greeting：NPC 见面语（"欢迎光临，需要点什么？"）
- 交付：一次交互最多一条新线索（告知有成本）
- 已交付标记持久化（不重发）

【简单对话树（深度取 settings max_dialog_depth，默认 2，0=不限）】
- 选项级 conditions 条件对话（满足条件才显示该选项）
- action 枚举：shop（开商店）/ quest（发任务）/ tutorial（教学）/
              intel（情报）/ reply（纯回复）
- 分支超 max_dialog_depth → 校验器软拦/提示"对话太深，拆成多 NPC 或事件牌组"（0=不限不拦）

【对话示例】
铁匠·老周：
  greeting: "炉火正旺，要打造点什么吗？"
  选项1: "看看货物" → action: shop
  选项2: "接点活儿" → action: quest（条件匹配候选任务）
  选项3: "打听消息" → action: intel（图鉴情报解锁）
```

---

## 四、NPC 类型

| 类型 | 交互 | 说明 |
|---|---|---|
| 商人 | /对话 → shop | 商店引用（shop_refs），声望折扣可选 |
| 任务发放者 | /对话 → quest | 候选任务+条件（差异化支线 3.2） |
| 情报员 | /对话 → intel | 图鉴情报/线索（告知有成本） |
| 教学导师 | /对话 → tutorial | 机制教学（first_meet 仅首见触发） |
| 世界观叙述者 | /对话 → reply | 剧情/世界观（沉浸感） |
| 发牌员 | /对话 → dealer | 事件牌组抽牌交付（见六） |

---

## 五、npc.json 数据结构（与 enemies.json 同构）

```json
{
  "id": "blacksmith_lao",
  "name": "铁匠·老周",
  "icon": "🔨",
  "map": "新手村",                // 地图挂点（maps.json npcs 引用）
  "type": "quest_giver",         // 商人/任务发放者/情报员/教学导师/叙述者/发牌员
  "desc": "村里的老铁匠，手艺远近闻名",
  "visible": true,               // 是否可见（false=隐藏 NPC，条件解锁）
  "dialogues": {
    "greeting": "炉火正旺，要打造点什么吗？"
  },
  "interactions": [              // 功能菜单（选择 N，见三）
    { "action": "quest", "text": "接点活儿", "quests": [...] },
    { "action": "shop", "text": "看看货物", "shop_refs": ["blacksmith_shop"] },
    { "action": "heal", "text": "帮忙治疗", "cost": { "coins": 50 } }
  ],
  "quests": [                    // 候选任务+条件（差异化支线）
    { "quest_id": "q_ore_20", "condition": { "prof_level": { "mining": 3 } } },
    { "quest_id": "q_sword", "condition": { "level": { "min": 10 } } }
  ],
  "shop_refs": ["blacksmith_shop"],
  "intel": [...],                // 情报（与 enemies lore 同构）
  "intel_refs": [...],           // 图鉴引用
  "tutorials": [...],            // 教学（first_meet 触发）
  "dealer": null                 // 发牌员配置（见六）
}
```

| 顶层字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| id/name/icon | str | 必填 | 唯一/名称（禁空格）/图标 |
| map | ref | null | 地图挂点 |
| type | enum | 商人 | 6 类 |
| desc | str | 空 | 描述 |
| visible | bool | true | 隐藏 NPC（条件解锁） |
| dialogues | obj | greeting 兜底 | 见面语（回复树可并入 interactions） |
| **interactions** | list | [] | **功能菜单（选择 N）：quest/shop/heal/give_item/buff/repair*/teleport/intel/tutorial/reply + 条件（*repair：依赖装备耐久系统，框架未实现，见 §3.2 注）** |
| quests | list | [] | 候选任务+条件 |
| shop_refs | list | [] | 商店引用 |
| intel/intel_refs | list | [] | 情报/图鉴 |
| tutorials | list | [] | 教学（first_meet） |
| dealer | obj | null | 发牌员配置 |

---

## 六、发牌员配置（NPC = 事件牌组发牌员）

```
dealer 三策略（用户可选）：
  first_match（默认）：按顺序匹配第一个满足条件的牌（顺序即优先级）
  weighted：加权随机（多样性）
  random：纯随机（少见）

抽牌状态机 5 步：
  visible（可交互）→ 牌池构建（候选事件按条件过滤）
  → 抽牌（策略选一）→ 事件交付（对话/物品/任务）
  → 孤寂卡（无牌可抽 = 普通问候，不交付）

去重：复用 quest_active/quest_daily 三表（不重复发已完成任务）
```

---

## 七、系统衔接

```
任务系统：quests 候选任务+条件（差异化支线 3.2）——NPC 是发任务的载体
商店：shop_refs + 对话 action: shop（商人 NPC 挂商店）
图鉴：intel 情报 + intel_refs（情报员解锁图鉴条目）
教学：tutorials first_meet（教学导师首见教学，可回看）
事件牌组：dealer 发牌员（NPC 密度 = 牌组运转保障）
地图：maps.json npcs 引用数组（NPC 挂点，编辑器地图页 [NPC] 标签）
```

---

## 八、4.2 元数据 + 4.5 校验器

### 4.2 npc.json 元数据（顶层 14 字段 + 6 子表）
```
顶层：id/name/icon/map/type/desc/visible/dialogues/interactions/quests/
      shop_refs/intel/intel_refs/tutorials/dealer
子表：dialogues（greeting）
     interactions（10 action 子字段，见 3.4）｜ quests（quest_id/condition）
     shop_refs（ref）｜ intel/intel_refs（同 enemies lore）
     tutorials（tutorial_id/condition）｜ dealer（strategy/牌池）
```

### 4.5 校验器（15 行）
```
硬拦：NPC 引用不存在 / 类型错误 / 负数 / 结构错误
黄提示：条件永假 / 候选互斥无牌可发 / 未使用 NPC / 地图无 NPC 提示"这个世界有点空？" / 对话树死循环或超深（分支>max_dialog_depth，0=不限不拦，软拦提示）
```

---

## 九、编辑器（NPC 页 8 标签，零代码）

```
基础（名称/图标/类型/描述/可见性）→ 地图挂点（下拉选地图）
对话（greeting + 选项树拖拽，层数随 max_dialog_depth）→ 条件（选项级条件下拉）
交互 action 下拉（10 类）：repair 标注「未实现依赖·装备耐久系统」——默认禁用/灰显（内容包启用耐久后自动开放）
任务（候选任务勾选 + 条件）→ 商店（商店下拉勾选）
情报（图鉴条目勾选）→ 教学（教学模板）
发牌（发牌员策略下拉 + 牌池配置）
级联删除 + 未使用角标 + CSV 通道
```

---

## 十、示例

```json
// 商人 NPC
{ "id": "shopkeep_lin", "name": "杂货商人·林", "icon": "🧺",
  "map": "新手村", "type": "merchant",
  "dialogues": { "greeting": "物美价廉，童叟无欺！",
    "options": [{ "text": "买东西", "action": "shop", "shop_refs": ["village_shop"] }] } }

// 铁匠 NPC（3 候选任务条件牌组）
{ "id": "blacksmith_lao", "name": "铁匠·老周", "icon": "🔨",
  "map": "新手村", "type": "quest_giver",
  "dialogues": { "greeting": "炉火正旺！", "options": [
    { "text": "接点活儿", "action": "quest" } ] },
  "quests": [
    { "quest_id": "q_ore_20", "condition": { "prof_level": { "mining": { "min": 3 } } } },
    { "quest_id": "q_sword",  "condition": { "level": { "min": 10 } } },
    { "quest_id": "q_master", "condition": { "main_progress": { "min": 3 } } }
  ] }

// 情报员 NPC（图鉴情报 + 教学）
{ "id": "scholar_du", "name": "学者·杜", "icon": "📖",
  "map": "熔岩洞窟入口", "type": "intel_giver",
  "dialogues": { "greeting": "年轻人，想了解这里的怪物吗？",
    "options": [
      { "text": "熔岩甲虫情报", "action": "intel", "intel_refs": ["beetle_lore"] },
      { "text": "教我破防", "action": "tutorial", "tutorials": ["pv_break_tut"] }
    ] } }
```

---

## 十一、风险与对策

| 风险 | 对策 |
|---|---|
| 告知有成本难落实 | 一次一物铁律 + 已交付标记持久化 |
| 发牌员太少/太多 | 密度建议（每地区 ≥3 交互点）+ 孤寂卡节奏 |
| NPC 文案成本 | 成本梯度（90% 单段对话）+ 环境 NPC 生成技巧 |
| 小白不会指令 | 自动提示 + 免前缀 + 数字选项 + 温柔纠错 |
| 碎片化丢失 | 对话快照 + 续谈入口 + 已交付不重发 |
| 移动 NPC 找不到 | 默认挂节点（移动/隐现默认关，作者显式开+线索预告） |
| 送礼破坏节奏 | 默认关（可选模块，开启才显示喜好） |
| 对话过多厌烦 | 多形态交付（物品/图鉴/悬赏令不依赖对话）+ 孤寂卡留白 |

---

*设计依据：Agent A 盘点（P0：npc.json 缺失/地图挂点/指令冲突）+ Agent B 体验（发牌员网络/单轮交付/告知有成本）+ Agent C 数据结构（npc.json 同构 enemies/对话树深度可配 max_dialog_depth/dealer 策略）+ 用户拍板（/对话/单轮+树深度可配/送礼默认关）+ 任务系统 3.2/羊蹄山之魂/指令分隔规范衔接*
