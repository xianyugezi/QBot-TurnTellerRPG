# 细化_2b1：NPC 数据 Schema（npc.json）与发牌员（Dealer）机制

> 版本：v1.0（细化交付）· 依据：《NPC系统设计定稿 v1.3.1》（下文简称**定稿**，行号以 `/root/docs_archive/RPG框架项目/NPC系统设计定稿.md` 为准，引用格式 `[Lxx]`）
> 范围：① npc.json 字段级 schema（id/name/greeting+对话树≤2 层/10 类动作 功能菜单/发牌员 strategy+pool/地图挂点）② 发牌员机制（候选池/抽牌状态机/轮转-随机-条件三策略/去重/孤寂卡）③ 10 类动作各自 target/param/条件/once 字段契约 ④ 一次一物（信息类置灰"已听"/存档边界/图鉴回看）⑤ 验收测试用例（TC-xx）
> 覆盖声明：仅对定稿**已有**语义做字段化定型；定稿未显式定义处一律标注**【工程补白】**，并依据定稿 ①只建议不限制 总纲（L28）扩展，不冒充定稿行号。
> 标注约定：**定稿既有**=定稿原文明确；**【工程补白】**=定稿未给字段名/取值，本表按"只建议不限制"取点定型（命名可改，裁决边界透明）。

## 〇 追溯总览与接缝裁决（先读本节）

| 主题 | 定稿落点 | 关键行号 |
|---|---|---|
| 核心一句话（NPC=发牌员网络） | §一 | L8 |
| 五条体验铁律 | §一 | L27-32 |
| /对话 指令与命名铁律 | §二 | L40-52 |
| 会话路由规则 / 当前商店 / 一次一物 / 恢复简报 | §2.1-2.4 | L58-71、L76-80、L86-91、L97-101 |
| 交互流程 / 菜单上限 / 10 类动作 / 子字段表 | §3.0-3.4 | L108-175 |
| 条件引擎（三要素+9 运算符+var 键空间） | §四 | L179-312 |
| 对话树（单轮交付 + ≤2 层） | §三 | L316-336 |
| NPC 类型 6 类 | §四 | L344-349 |
| npc.json 顶层字段表 | §五 | L355-397 |
| 发牌员配置（三策略/抽牌状态机/去重） | §六 | L401-415 |
| 系统衔接 / 元数据 / 校验器 / 编辑器 | §七-九 | L421-461 |
| 示例 / 风险对策 | §十-十一 | L468-509 |

**接缝裁决**（定稿内部口径交叉处，本细化取点）：

| # | 接缝 | 定稿内并存 | 本细化裁决 | 依据 |
|---|---|---|---|---|
| S1 | 顶层字段数 | §八标题"顶层 **14** 字段"；§五字段表罗列与 §8.2 列全 **15** 个（id/name/icon/map/type/desc/visible/dialogues/interactions/quests/shop_refs/intel/intel_refs/tutorials/dealer） | **以列全的 15 个为准**（§8.2 全文=15，系标题笔误） | L434 vs L436-437、L386-397 |
| S2 | 发牌员策略命名 | §六三策略：`first_match`（默认）/`weighted`/`random` | **字段枚举采任务口径 rotate/random/condition**（本细化 doc schema 见 §二）：`condition`=承载 first_match 语义、`random`=承载 weighted+random 语义、`rotate`=**【工程补白】新增**；旧三策略名读取兼容并提示迁移 | L404-407 |
| S3 | 动作双入口 | `dialogues.options[]`（对话树选项）与 `interactions[]`（功能菜单）并列 | **对话树 options = 3.2 枚举子集 5 类**（shop/quest/tutorial/intel/reply，L326-327）；**功能菜单 interactions = 全 10 类**（L392）。两入口共用 §3.4 子字段契约 | L326-327 vs L392、L391"回复树可并入 interactions" |
| S4 | repair 动作可用性 | 3.2 动作表列入 10 类且标注 `*`；子字段表/repair 表单同步标注 | **repair 依赖装备耐久系统（框架未实现）→ 当前降级"不可用+友好提示"**；配置不拦截但编辑器置灰 | L139、L168、L457 |
| S5 | 命名铁律细节 | NPC 名禁空格、允许 `·`/`Ⅱ`；与地图/区域字符串比对 | 解析以原文含 `·`/`Ⅱ` 精确匹配；用户输入空格则转义提示 | L49 |

引用约定：`[Lxx]` = NPC定稿行号；"派生" = 由定稿语义直接推出的防呆规则（标注推出来源）。

---

## 一、npc.json 字段级 schema（顶层 15 字段）

### 1.0 任务字段名 ↔ 定稿规范字段名 对照（父任务口径背书）

| 任务表述 | 定稿规范字段 | 说明 |
|---|---|---|
| `dialogue`（对话树≤2 层） | `dialogues` | 含 `greeting` + `options[]`（对话树，≤2 层）[L364-366、L391] |
| `actions`（10 类） | `interactions[]` | 功能菜单（选择 N），条目 `action` ∈ 10 类 [L367-371、L392] |
| `strategy`（rotate-random-condition） | `dealer.strategy` | 发牌员策略，位于顶层 `dealer` 对象内 [L397-398、L441] |
| `pool`（发牌池） | `dealer.pool` | 候选事件牌池，**【工程补白】命名**（定稿称"牌池"未给键名）[L441] |
| `location`（地图挂点） | `map` | 引用 maps.json [L360、L387、L427] |

### 1.1 顶层字段（15 个）

| # | 字段 | 类型 | 必填 | 默认 | 约束 / 枚举 | 来源 |
|---|---|---|---|---|---|---|
| F01 | `id` | string | 必填 | — | 全文件唯一；建议 snake_case（`blacksmith_lao`）；非空 | L357、L386 |
| F02 | `name` | string | 必填 | — | 显示名；**禁空格**，允许 `·`/`Ⅱ`（`铁匠·老周`） | L358、L386、L49 |
| F03 | `icon` | string | 必填 | — | 单字符图标（`🔨`），列表展示 | L359、L386 |
| F04 | `map` | string | 选填 | `null` | 地图挂点（引用 maps.json 的 map id；maps.json `npcs` 引用数组为反向引用，双向互为校验） | L360、L387、L427 |
| F05 | `type` | enum | 选填 | `merchant` | 6 类：`merchant`(商人)/`quest_giver`(任务发放者)/`intel_giver`(情报员)/`tutor`(教学导师)/`narrator`(叙述者)/`dealer`(发牌员)；**后三类英文键为【工程补白】命名**（定稿仅给中文类），前三类有定稿示例佐证 | L361、L388、L344-349、L470/476/488 |
| F06 | `desc` | string | 选填 | 空 | 一句话描述（"村里的老铁匠…"） | L362、L390 |
| F07 | `visible` | bool | 选填 | `true` | false=隐藏 NPC（条件解锁后显示，条件落于何处见 §1.4-补白） | L363、L390 |
| F08 | `dialogues` | object | 选填(简化时仅 greeting) | `{greeting:"…"}` 兜底 | 见面语 + 对话树 options（≤2 层），见 1.2 | L364-366、L391、L319 |
| F09 | `interactions` | array | 选填 | `[]` | 功能菜单（选择 N），条目见 1.3；action ∈ 全 10 类 | L367-371、L392 |
| F10 | `quests` | array | 选填 | `[]` | 候选任务+条件（差异化支线），条目 `{quest_id, condition}` | L372-375、L393 |
| F11 | `shop_refs` | array | 选填 | `[]` | 商店引用（ref shop.json；打开后=当前商店） | L376、L394、L161 |
| F12 | `intel` | array | 选填 | `[]` | 情报直接条目（与 enemies lore 同构） | L377、L395 |
| F13 | `intel_refs` | array | 选填 | `[]` | 图鉴引用（ref enemies lore；交付后置灰"已听"） | L378、L395、L171 |
| F14 | `tutorials` | array | 选填 | `[]` | 教学模板引用（first_meet 首见触发），条目 `{tutorial_id, condition}` | L379、L396、L172 |
| F15 | `dealer` | object | 选填 | `null` | 发牌员配置（strategy + pool，见 §二）；type=dealer 时必配 | L380、L397-398、L441 |

### 1.2 dialogues —— 见面语 + 对话树（≤2 层硬约束）

**子表**（定稿 §8.2 名 6 子表之"dialogues"）：

| # | 字段 | 类型 | 必填 | 默认 | 约束 | 来源 |
|---|---|---|---|---|---|---|
| D01 | `dialogues.greeting` | string | 选填 | 定稿兜底 `{"greeting":"…"}` | 见面语（"炉火正旺，要打造点什么吗？"） | L320、L365、L391 |
| D02 | `dialogues.options[]` | array | 选填 | `[]` | **对话树（回复树）**：单轮交付 + ≤2 层硬约束；节点见下注 | L324-328、L391、L473 |

**options 节点字段**（对话树节点，≤2 层，选项级 condition）：

| # | 字段 | 类型 | 必填 | 约束 | 来源 |
|---|---|---|---|---|---|
| D03 | `options[].text` | string | 必填 | 选项文案（"看看货物"） | L331-335、L473 |
| D04 | `options[].action` | enum | 必填（若该节点要交付） | 对话树 action 枚举 **5 类子集**：`shop`/`quest`/`tutorial`/`intel`/`reply`（不再多列；结构上不拦截其他类，但校验器提示"对话树建议仅用 5 类"——S3 裁决） | L326-327 |
| D05 | `options[].condition` | object | 选填 | 无 | 选项级条件（满足才显示该选项，条件引擎 §1.5） | L325、L456 |
| D06 | `options[].*` | — | 按 action | 无 | action 对应子字段（shop_refs/intel_refs/tutorials/text…），与 §3 契约一致 | L473（shop_refs 示例佐证）、L160-175 |

**深度约束**：树深 ≤2 层（greeting→选项→选项子选项）；超 2 层 → 校验器提示"对话太深，拆成多 NPC 或事件牌组"（不拦截）[L328]。

### 1.3 interactions —— 功能菜单条目（10 类动作）

**条目基字段**（公共三字段 + action 专属子字段，专属见 §三）：

| # | 字段 | 类型 | 必填 | 默认 | 约束 | 来源 |
|---|---|---|---|---|---|---|
| I01 | `interactions[].action` | enum | 必填 | — | **全 10 类**：quest/shop/heal/give_item/buff/repair/teleport/intel/tutorial/reply | L126-137、L392 |
| I02 | `interactions[].text` | string | 必填 | — | 菜单显示文案（"接点活儿"/"看看货物"） | L174、L143-148 |
| I03 | `interactions[].condition` | object | 选填 | 无 | 触发条件（不满足=提示/隐藏/置灰，作者可配） | L175、L122、L145-147 |

示例（定稿 L143-150 原样）：

```json
"interactions": [
  { "action": "quest", "text": "接点活儿", "quests": [...], "condition": {...} },
  { "action": "shop", "text": "看看货物", "shop_refs": ["blacksmith_shop"], "condition": { "var": "level", "op": "ge", "value": 5 } },
  { "action": "heal", "text": "帮忙治疗", "cost": { "coins": 50 }, "heal": { "hp": "100%", "mp": "100%" },
    "condition": { "var": "item_count", "op": "ge", "value": 50, "item": "金币" } },
  { "action": "give_item", "text": "领取补给", "items": [{ "id": "药水", "count": 3 }], "repeat": "daily" }
]
```

> 菜单上限：交互菜单最多显示 6 个选项（+固定 `N.离开`）；超 6 个折叠为"7.更多…"（二级菜单）；条件提示一行"需要：等级 ≥10"不展开长文本 [L108-113]。

### 1.4 条件引擎（interactions/quests/options/pool 通用；全系统复用）

统一条件 = `{ var, op, value, param? }` 四要素 [L183+190]：

| # | 项 | 规范 | 来源 |
|---|---|---|---|
| C01 | 三要素 | `{ var: 键, op: 运算符, value: 值, param?: 参数 }` | L183-191 |
| C02 | op 9 种 | `gt/ge/lt/le/eq/ne/between/is/not`；符号双写 `>=`=ge `>`=gt `<=`=le `<`=lt `=`=eq `!=`=ne | L188-189 |
| C03 | param | 可选第 4 键（参数化 var 的指定目标，如 item_count 指定物品：`{var:"item_count",op:"ge",value:50,param:"金币"}`） | L190-191 |
| C04 | var 键空间 | level/job/job_level/prof_level/has_item/not_has_item/item_count/has_quest/quest_completed/reputation/main_progress/codex/time/is_day/is_night/affection + `[签到:*]`/`[事件:*]`/`season`/`period`/`weather` 等登记扩展 | L184-187、L249 |
| C05 | 组合 | `any`/`all`/`not` 嵌套 | L299-304 |
| C06 | event 原语兼容 | `{type:"event",event,target,count}` 等价映射 `{var:"[事件:xxx]",op:"ge",value:count,param:target}` | L195-196 |
| C07 | 条件反馈 | 满足→正常显示；不满足→默认显示但提示（"需要：…"），可配隐藏/置灰；条件永假仅黄提示不拦 | L309-311 |
| C08 | visible 解锁条件 | **【工程补白】**：`visible:false` 的解锁条件挂 `dealer.pool` 首牌 condition 或顶层补白 `unlock_condition` 字段（二选一，编辑器条件页配置）；定稿仅言"false=隐藏 NPC，条件解锁"未给字段名 | L363 |

### 1.5 字段计数

- **顶层 15**（F01-F15，S1 裁决）。
- 全量：顶层 15 + dialogues 子表 2（greeting/options）+ options 节点 4（text/action/condition/子字段占位）+ interactions 条目 3（action/text/condition）+ quests 条目 2（quest_id/condition）+ dealer 子表 2（strategy/pool → §二）+ pool 牌条目 5（§二-补白）。
- 定稿 §8.2 列"顶层 15 + 6 子表"（dialogues/interactions/quests/shop_refs/intel+intel_refs/tutorials/dealer）对应确认 [L435-442]。

---

## 二、发牌员机制（Dealer：候选池 · 抽牌状态机 · 三策略）

定稿定位：**NPC = 世界里的发牌员网络——玩家只记一个指令（/对话），NPC 用单轮交付把世界递到玩家面前，条件驱动决定给什么、不给什么** [L8]。发牌员类型 NPC 的 `/对话 → dealer` [L349]，其交互走本机制。

### 2.0 dealer 子结构（顶层 F15）

| # | 字段 | 类型 | 必填 | 默认 | 约束 | 来源 |
|---|---|---|---|---|---|---|
| DR01 | `dealer.strategy` | enum | 选填 | `condition` | **`rotate` / `random` / `condition`**（三策略语义见 2.2；默认承接定稿 first_match 默认态） | L404-405、L441 |
| DR02 | `dealer.pool` | array | 必填（type=dealer 时） | `[]` | 候选事件牌池；**【工程补白】命名**（定稿称"牌池"）：条目为"牌"，见 2.1 | L411（牌池构建）、L441 |

### 2.1 候选牌条目（dealer.pool[]，【工程补白】字段）

| # | 字段 | 类型 | 必填 | 默认 | 约束 | 来源 |
|---|---|---|---|---|---|---|
| P01 | `pool[].id` | string | 必填 | — | 牌 ID，池内唯一 | 派生（抽牌引用需要） |
| P02 | `pool[].condition` | object | 选填 | 恒真 | 该牌出现的条件（按条件分发时用；不满足=不进入候选池） | L410-411（候选事件按条件过滤）、L405 |
| P03 | `pool[].weight` | number | 选填 | `1` | 加权随机权重（strategy=random 时归一化；weight=0=不入随机池） | L406（加权随机） |
| P04 | `pool[].deliver` | object | 必填 | — | 交付内容：`{ action, …子字段 }`（action ∈ §三 10 类；事件交付=对话/物品/任务） | L411（事件交付 L411） |
| P05 | `pool[].once` | bool | 选填 | `false` | 牌级一次性：true=交付一次后出池（落玩家存档，见 §四）；与 action 级一次一物叠加 | 派生（去重语义 L414 + 一次一物 L88） |

### 2.2 三策略（rotate / random / condition）

| # | 策略 | 语义 | 与定稿 mapping | 来源 |
|---|---|---|---|---|
| DS01 | `condition`（默认） | **按条件分发**：按候选池顺序匹配**第一个满足条件**的牌并交付；顺序即优先级 | = 定稿 `first_match`（默认，按顺序匹配第一个满足条件的牌） | L404-405 |
| DS02 | `random` | **随机**：候选池（条件过滤后）按 `weight` 归一化加权随机抽一张；全 weight=0 或等权=纯随机 | = 定稿 `weighted`（加权随机，多样性）+ `random`（纯随机，少见） | L406-407 |
| DS03 | `rotate` | **轮转**：候选池（条件过滤后）维护轮转指针，按顺序逐张抽取；抽过的牌本轮不重复（指针环形推进，全局去重语义仍生效） | **【工程补白】新增**（定稿未定义；按 ①只建议不限制 总纲 L28 扩展；编辑器"发牌策略下拉"新增一项） | L28、L440、L460 |
| DS04 | 兼容 | 旧 `first_match`/`weighted`/`random` 值仍被解析：first_match→condition、weighted/random→random；校验器提示"新枚举 rotate/random/condition，建议迁移" | — | L404-407（背书写法） |

### 2.3 抽牌状态机（5 步）与边界

```
visible（可交互）→ 牌池构建（候选事件按条件过滤 pool[]）→ 抽牌（strategy 选一）→ 事件交付（对话/物品/任务）→ 孤寂卡（无牌可抽 = 普通问候，不交付）
```

| # | 步 | 规则 | 来源 |
|---|---|---|---|
| SM01 | ① visible | type=dealer 的 NPC 处于可交互态（map 挂点内、visible=true） | L410 |
| SM02 | ② 牌池构建 | 对所有 pool[] 牌按 `condition` 过滤（不满足=剔除）；空池=无牌 | L410-411 |
| SM03 | ③ 抽牌 | 按 strategy（DS01-03）从过滤后候选池选一 | L411、L404-407 |
| SM04 | ④ 事件交付 | 命中牌的 `deliver` 内容交付（对话/物品/任务，统一管线见 §三） | L411 |
| SM05 | ⑤ 孤寂卡 | **无牌可抽 = 普通问候（greeting 兜底），不交付**；孤寂卡留白/节奏设计 | L412、L509 |
| SM06 | 去重 | 复用 `quest_active`/`quest_daily` 三表：**不重复发已完成/活跃任务**；牌级 once（P05）落存档 | L414 |
| SM07 | 密度建议 | 每地区 ≥3 交互点（发牌员密度=牌组运转保障）；孤寂卡节奏干预 | L503、L426 |

---

## 三、10 类动作字段契约（interactions[].action = interactions[] 条目 / dialogue options[] / dealer.pool[].deliver 共用）

**统一条目**：`{ action, text(菜单文案，仅列表入口), condition(触发条件), …action 专属子字段 }`。专属子字段见下表。

**统一入账管线（铁律）**：give_item 等发放类动作**经框架 reward 解析器统一入账**（物品入包，与任务/签到同管线）；发放器唯一实现=框架 reward 解析器，NPC 只配条目+repeat 规则 [L153]。consume 侧无自定义发放逻辑。

| # | action | target（作用对象） | param（专属子字段） | 条件适用性 | once 语义（重复规则） | 来源 |
|---|---|---|---|---|---|---|
| AC01 | `quest` | quest.json 任务 | `quests[]`（候选任务+条件：`{quest_id, condition}`） | 公共 condition 适用；候选条目自带 condition | 不置灰可重复；**去重由 quest_active/quest_daily 兜底**（已完成/活跃不重发） | L128、L160、L393、L414 |
| AC02 | `shop` | shop.json 商店 | `shop_refs[]`（打开后=**当前商店**，地图内 `/商店` 可随时回；离图清除回全局商店） | 公共 condition 适用（示例 level≥5） | 不置灰可重复（商店消费类自然多次） | L129、L161、L394、L76-80 |
| AC03 | `heal` | 玩家 HP/MP | `cost{coins}`（治疗费，免费=省略）+ `heal{hp,mp}`（int 或 `"N%"` 百分比串=按上限） | 公共 condition 适用（示例金币门槛 item_count≥50） | 不置灰可重复（付费/免费治疗） | L130、L162-163、L146-147 |
| AC04 | `give_item` | items.json 物品 | `items[]{id,count}`（**统一 reward 条目 schema**，任务系统定稿 §2.1；id≡item 键）+ `repeat` ∈ {once, daily} | 公共 condition 适用 | **显式 repeat**：默认 `once`（仅一次）/ `daily`（每日重置）；功能类不置灰 [L90] | L131、L148-149、L153、L164-165 |
| AC05 | `buff` | 效果注册表 | `effects[]`（临时增益，effects/statuses/marks 三表统一注册、ID 跨表唯一）+ `turns`（持续回合，效果自带可省） | 公共 condition 适用 | 不置灰可重复；**同 buff 叠加按效果系统叠加规则**【补白：持续回合内重触发不叠加新层，仅刷新剩余回合】 | L132、L166-167 |
| AC06 | `repair` | 装备耐久系统（**框架未实现**） | `cost`（修理费，可选，按装备耐久计价） | 公共 condition 适用（启用时） | **当前降级**：交互选项不可用，触发给友好提示（"没有需要修理的装备"）；内容包启用耐久时开放 | L133、L139、L168、L457 |
| AC07 | `teleport` | maps.json 目标地图 | `map`（传送目标地图引用）+ `cost`（传送费，免费=省略） | 公共 condition 适用 | 不置灰可重复 | L134、L169-170 |
| AC08 | `intel` | enemies lore（图鉴） | `intel_refs[]`（图鉴条目引用，交付后**置灰"已听"**） | 公共 condition 适用 | **一次一物**：交付后标记"已听"（置灰），可选但无新内容（"你已经听过了"）；回看走图鉴 | L135、L171、L86-89 |
| AC09 | `tutorial` | 教学模板 | `tutorials[]`（机制教学模板引用；**first_meet 仅首见触发**） | 公共 condition 适用 | **首见即一次**：首见触发后归"已教学"，可回看（图鉴/教学回看出口） | L136、L172、L347、L425 |
| AC10 | `reply` | 无（纯回复聊天） | `text[]`（聊天回复，支持随机/循环取一条） | 公共 condition 适用 | 不置灰可重复（闲聊不交付线索，不触发一次一物） | L137、L173 |

> 公共 `condition`：所有 10 类共用触发条件（不满足=提示/隐藏/置灰，作者可配 [L122、L175]）。`text`：菜单显示文案，列表入口必填（AC01-AC10 全列共用 [L174]）。

**对话树 vs 功能菜单动作口径**（S3 裁决落地）：`dialogues.options[].action` 建议用 5 类子集（shop/quest/tutorial/intel/reply）[L326-327]；`interactions[]` 与 `dealer.pool[].deliver` 用全 10 类。字段契约（本表）对两入口一致。

---

## 四、一次一物（信息类交付后置灰"已听" + 存档边界）

定稿立场：**每次交互最多交付一条新线索（告知有成本）** [L31]；交付=单轮 [L319-322]。

| # | 规则 | 内容 | 来源 |
|---|---|---|---|
| O01 | 触发范围 | **信息类**（intel/线索/情报/教学）交付后：该选项标记"已听"（置灰） | L86 |
| O02 | 二次点击 | 下次可选但无新内容（"你已经听过了"） | L87 |
| O03 | **存档边界** | 已交付标记**落玩家存档（框架 3.7 持久化语义总表）**，**不落会话快照**（30 天回收会清掉） | L88 |
| O04 | 回看出口 | 情报/线索交付**同时写入图鉴**（图鉴可回看，置灰不死胡同）；教学走教学回看 | L89、L425 |
| O05 | 功能类豁免 | quest/shop/heal/give_item **不置灰**（可重复使用） | L90 |
| O06 | 菜单层效果 | 菜单层一次一物（信息不重复喂），功能照常用 | L91 |
| O07 | 存档键【工程补白】 | 玩家存档新增节点 `npc_delivered`（NPC ID → 已交付 action 键集合，含 intel_refs/tutorials id 与池牌 once id）；intel 图鉴解锁复用既有 `codex_state`（对齐细化_1e 口径） | L88、O03 派生 |
| O08 | 断点续谈（相邻机制） | 菜单层中断→恢复重显菜单；子界面层中断（heal 确认/任务交付确认/领取中）→简报"上次的『领取补给』未完成，请重新选择"；长叙述分段位置入快照（page 索引） | L97-101、L32 |

---

## 五、验收测试用例（20 条）

约定：输入为 npc.json 片段 / 运行时指令；预期标注校验级别（拦截=拒绝 / 警告=黄提示不拦 / 提示=信息）。

| # | 场景 | 输入要点 | 预期 |
|---|---|---|---|
| TC-01 | 合法 NPC 全量 schema | 顶层 15 字段齐全：id/name/icon/map/type/desc/visible/dialogues/interactions×多项/quests/shop_refs/intel/intel_refs/tutorials/dealer | 校验通过：无拦截、无警告 |
| TC-02 | 引名与唯一性 | ① 两个 NPC 同 id；② `name:"铁匠 老周"`（含空格）；③ `name:"铁匠·老周"` | ① 拦截（id 唯一）；② 拦截（禁空格）；③ 通过（`.` 允许） |
| TC-03 | 对话树深度 | ① greeting→option→option；② 树深 3 层 | ① 通过（≤2 层）；② 警告"对话太深，拆成多 NPC 或事件牌组"（不拦截） |
| TC-04 | 无 NPC 地图 | 地图内无 visible=true 的 NPC，玩家 `/对话` | 输出"当前地图没有可对话的人"（兜底） |
| TC-05 | 会话路由 | 对话激活中：发 `1` / `攻击1` / `退出` / `再见` | `1`→选交互选项；`攻击1`→按指令解析（不冲突）；`退出`/`再见`/`离开` 三词同义结束 |
| TC-06 | 菜单上限折叠 | 某 NPC 配 8 个 interactions 选项 | 菜单显示 6 项 + `7.更多…`（二级菜单）+ 固定 `8.离开` |
| TC-07 | 交互条件满足/不满足 | ① 满足 level≥5 的 shop 项；② 不满足；③ 配置 hidden 风格 | ① 正常显示可交互；② 显示但提示"需要：等级 ≥5"（可配隐藏/置灰）；③ 选项隐藏 |
| TC-08 | 条件引擎四要素 | ① `{var:"item_count",op:"ge",value:50,param:"金币"}`；② `{var:"level",op:">=",value:10}`（符号双写）; ③ `any`/`all` 组合 | ① param 定向正确判定；② `>=` 双写等价 ge、求值正确；③ 组合嵌套正确 |
| TC-09 | 发牌员 condition 策略 | strategy=condition；pool=[A(条件假),B(条件真),C(条件真)] | 按顺序匹配 → 交付 B（顺序即优先级，跳过 A） |
| TC-10 | 发牌员 random 策略 | strategy=random；pool=[X(w=1),Y(w=3)]；抽 100 次 | X:Y 命中比 ≈1:3（加权归一化）；全 weight=0 → 纯随机等概率 |
| TC-11 | 发牌员 rotate 策略 | strategy=rotate；pool=[A,B,C]；连抽 4 次 | A→B→C→A（指针环形轮转：抽过的牌本轮不重复，且每次仍按 SM02 判条件 / SM06 去重） |
| TC-12 | 孤寂卡 | strategy=condition；pool 首牌条件全部不满足/池空 | 无牌可抽 → 普通问候（greeting 兜底），不交付任何内容 |
| TC-13 | 发牌去重 | 任务 q_ore_20 已在 quest_active / 已完成 | 复用 quest_active/quest_daily 三表：活跃/已完成任务不进候选，不发重复任务 |
| TC-14 | 一次一物：intel 置灰 | 学者·杜 intel 交付 beetle_lore 后重开菜单 | beetle_lore 项置灰"已听"；再选提示"你已经听过了"（图鉴可回看） |
| TC-15 | 一次一物：存档边界 | 交付后：① 玩家存档查 `npc_delivered`/`codex_state`；② 会话快照 30 天回收 | ① 已交付标记仍在（落玩家存档）；② 快照回收不清已交付标记、不重复投递 |
| TC-16 | 功能类重复 / repeat | ① shop/heal 连续触发；② give_item repeat=once 再触发；③ repeat=daily 次日再触发 | ① 不置灰照常；② 第二次提示已领取（once 仅一次）；③ 每日重置后重新可领 |
| TC-17 | 当前商店中断恢复 | 打开 NPC 商店→选购中退出→同地图 `/商店`→离开地图 `/商店` | 同地图回当前商店（不丢）；离图后回默认全局商店 |
| TC-18 | repair 降级 | 触发 repair 交互（框架未实现耐久） | 交互选项不可用，触发友好提示"没有需要修理的装备"；配置不拦截、编辑器表单置灰 |
| TC-19 | 对话恢复简报 | ① 菜单层中断；② heal 确认界面中断 | ① 恢复重显菜单；② 简报"上次的『帮忙治疗』未完成，请重新选择"；长叙述按 page 断点续读 |
| TC-20 | 校验器广义 | ① interactions 引用 quest/shop/id 不存在；② 地图内无 NPC；③ 某 NPC 从未被任何地图/事件方案引用 | ① 拦截（引用不存在）；② 提示"这个世界有点空？"；③ 提示"未使用 NPC"；条件永假→黄提示（不拦） |

---

## 附录 A：行号索引（字段 / 规则 ↔ 定稿）

| 主题 | 行号 |
|---|---|
| 核心一句话 / 五条体验铁律 | L8、L27-32 |
| /对话 指令 / 命名铁律 / 无 NPC 兜底 | L40-52 |
| 会话路由 / 当前商店 / 一次一物 / 恢复简报 | L58-71、L76-80、L86-91、L97-101 |
| 菜单上限 / 交互流程 | L108-113、L115-123 |
| 10 类动作枚举 / repair 降级 | L126-139 |
| interactions 配置示例 / 统一入账 | L141-153 |
| interactions 子字段表（逐 action） | L157-175 |
| 条件引擎：三要素 / 9 运算符 / var 键空间 / 组合 / 反馈 | L179-199、L201-221、L238-251、L297-312 |
| 对话树（单轮交付 / ≤2 层 / 5 类 action） | L316-336 |
| NPC 类型 6 类 | L340-349 |
| npc.json 数据结构 / 顶层字段表 | L353-397 |
| 发牌员配置（三策略 / 状态机 / 去重） | L401-415 |
| 系统衔接 / 元数据 / 校验器 / 编辑器 | L419-461 |
| 示例 / 风险与对策 | L466-509 |

> 延伸登记（不实现、仅记录）：送礼好感度=可选模块默认关 [L45、L250、L508]；行走/显隐 NPC 默认关，作者显式开+线索预告 [L507]；图鉴/教学回看落地以对应系统定稿为准（本表只登记接口，见覆盖声明）。

*设计依据：定稿 v1.3.1 全文（513 行）+ 兄弟细化文档样式（细化_1e 怪物八段 schema：接缝裁决/字段表/TC 用例/行号索引结构贴合）+ 任务口径（rotate-random-condition 策略名、10 类 action、一次一物）经 S2/S3 裁决映射定稿语义。*
