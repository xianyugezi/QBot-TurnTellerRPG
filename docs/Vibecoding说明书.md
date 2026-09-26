# Vibecoding 说明书 · 用 AI 做出你的内容包与新机制

> **给谁看**：不写代码、但想把内容/玩法做出来的人（策划、作者、服主）
> **它解决什么**：**你不用会编程**——90% 的内容工作靠**配置文件**就够了；剩下 10%（框架里没有的新机制）**交给 AI**，而这份说明书就是教你怎么跟 AI 配合、怎么验收它。
> **一句话**：**配置能做的别写代码；动手前先查「能力地图（§二）」和「别重复造（§三）」；真没有的再交给 AI，但你得会下订单和验收。**

---

## 目录（可跳转）

> 节号 + 一句。**第二批新增** = §十二（12.1~12.10）。

- [一、先分清三条路](#一先分清三条路决定你要不要-vibecoding) — 配置 / 推荐组合 / vibecoding，先判你走哪条。
- [二、框架能力地图](#二框架能力地图有什么谁负责动了会影响谁) — 常量·变量·事件·状态机·互相影响的索引。
- [三、「别重复造」对照表](#三别重复造对照表) — 想做 X 该用哪个现成 Y；避免重复实现。
- [四、开工前要准备的三样东西](#四开工前要准备的三样东西) — 编辑器、四份文档、一条铁律。
- [五、怎么跟 AI 说话](#五怎么跟-ai-说话4-个可复制模板) — 4 个可复制模板 A~D。
- [六、你必须让 AI 遵守的 7 条规矩](#六你必须让-ai-遵守的-7-条规矩写进每一单) — 写进每一单。
- [七、怎么验收 AI 的活](#七怎么验收-ai-的活5-问照问就行) — 5 问 + 不合格的样子。
- [八、常见坑与报错对照](#八常见坑与报错对照) — 编辑器 / 跟 AI 协作两类现象。
- [九、安全与回滚](#九安全与回滚务必看) — 密钥、打点、回滚三招。
- [十、进阶](#十进阶什么时候你可以自己动手不用惊动-ai) — 什么时候你自己动手。
- [十一、一页速查](#十一一页速查贴墙版) — 贴墙版总纲。
- [十二、新手实操（P0）与协作速查（P1）](#十二新手实操p0与协作速查p1) — 第二批新增。
  - [12.1 你的第一个内容包（15 分钟实操）](#121-你的第一个内容包15-分钟实操) — 走到导出 `.ttrpack`。
  - [12.2 动手前 AI 自查 5 问（防重复造硬门槛）](#122-动手前-ai-自查-5-问防重复造硬门槛) — 5 问没答完不许动手。
  - [12.3 同义反复与别名归并表（防写了旧键以为生效）](#123-同义反复与别名归并表防写了旧键以为生效) — 旧键 → 新轴，防双计。
  - [12.4 登记即承诺原则与「写了没用」怎么报](#124-登记即承诺原则与写了没用怎么报) — 无消费者不许登记。
  - [12.5 示例包导览（跟着 content/zz_craft_demo 学）](#125-示例包导览跟着-contentzz_craft_demo-学) — 跟着示例包学。
  - [12.6 成本与额度管理（少烧 token 清单）](#126-成本与额度管理少烧-token-清单) — 少烧 token。
  - [12.7 整页开工单模板（复制即用）](#127-整页开工单模板复制即用) — 复制即用。
  - [12.8 AI 跑偏了怎么纠正（话术表）](#128-ai-跑偏了怎么纠正话术表) — 一句纠正话术。
  - [12.9 可打勾的验收清单（附命令）](#129-可打勾的验收清单附命令) — 命令 + 通过标准。
  - [12.10 指令速查（含 GM 5 条）](#1210-指令速查含-gm-5-条) — 玩家向 + GM 5 条。

---

## 一、先分清三条路（决定你要不要 vibecoding）

| 你想做的事 | 走哪条 | 要写代码吗 |
|---|---|---|
| 加**物品 / 装备 / 怪物 / 技能 / 地图 / 任务 / NPC / 商店 / 配方**…… | **纯配置**：编辑器里点出来（存成 JSON） | ❌ **不用** |
| 调数值、加词条、改**公式写法**（公式就是配置里的表达式，例：`[技能等级:fireball] * 8 + 100`） | **纯配置** | ❌ **不用** |
| 用**已有机制**拼新玩法（例：回合制战斗 ＋ 生活玩法：炼金/打造/采集/钓鱼） | **纯配置 + 模块"推荐组合"** | ❌ **不用** |
| 想要一个**框架里没有的新机制**（例：自创"天气影响采集"的系统） | **vibecoding**（让 AI 扩展框架） | ✅ **交给 AI** |

> **判据**：**先在编辑器里找有没有现成模块/字段/声明段**。有 → 配置；真没有 → vibecoding。
> **"加新机制"才需要 vibecoding** —— 这是这套框架的设计目标之一。

---

## 二、框架能力地图（有什么、谁负责、动了会影响谁）

> **怎么读**：这一章是"框架已经给了什么"的索引。每条只写四件事——**是什么 → 谁拥有 → 作者能改哪里 → 改了会影响谁**；**深度细节一律指向《手册·X》§Y**，不在这里搬运。
> **三层权责一句话**（详见《手册·3》§1）：**框架 `qbot_rpg/**` 定机制**（"怎么算"）· **内容包 `content/<包>/**` 定内容**（"有什么"，纯 JSON）· **包自持代码 `ext/`** 只能接指令/渲染/测试（**双闸默认关**）。
> **路径约定**：`file:line` 相对仓库根；`gear_stats.py` 是 `qbot_rpg/data/gear_stats.py` 的简写。
> **行号口径**：`file:line` 以本次写入时的 HEAD（`9903c40`）为准；框架后续改动会使行号漂移，**权威口径以《手册·X》§Y 为准**（手册在漂移时会登记修正）。

### 2.1 常量（可直接引用的）

#### A. 装备键族——`items.json`/`equipment.json` 的 `stats_bonus` 里能写哪些键

| 键族 | 数量 / 内容 | 唯一源 file:line | 作者写在哪 | 改了会影响谁 |
|---|---|---|---|---|
| 平值 `GEAR_FLAT_KEYS` | 13：atk/dfn/hp/mp/str/con/agi/foc/spr/lck/spd | `gear_stats.py:175` | 装备/物品词条 `stats_bonus` | 聚合进 `attributes.bonus.flat`（面板白值） |
| 百分比 `GEAR_PCT_KEYS` | 8：`…_pct` | `gear_stats.py:180` | 同上 | 聚合进 `bonus.pct`；**后 4 键同时是特效轴别名源** |
| 战斗直读 `GEAR_COMBAT_KEYS` | 10：crit/absorb_hp/pierce_*… | `gear_stats.py:186` | 同上 | 经 `COMBAT_TO_COMBATANT:505` 桥进 combatant（**封顶值写死在此**） |
| 占位 `GEAR_PLACEHOLDER_KEYS` | 1：`cooldown_reduction_pct` | `gear_stats.py:198` | 同上 | **形似死代码、实为兼容设计**：只在一处换算（防双计） |
| 特效键 `GEAR_EFFECT_KEYS` | 17（由轴表派生，**不可手改**） | `gear_stats.py:464`（源 `:230`） | 同上 | **键空间唯一源**；手改派生表会被 import 覆盖 |

> **谁拥有**：键空间 = 框架 `data` 层（唯一源）；**内容包只能"用键"，不能"加键"**。**别名归并** `EFFECT_LEGACY_ALIASES`（6 条，`gear_stats.py:589`）：旧键→轴、**只换算一次**；旧键与轴符号相反**不是写错**（详见《手册·1》§1.2.4、《手册·3》§3.1 样例②）。

#### B. 特效轴全集（17 轴 = **16 已接线** + 1 哨兵）

**列义**：**双向** = 一条轴既能增强也能削弱（范围含负侧），**一条轴两方向**；默认全 `0.0`（= `×1.0`，未配置零变化）。

| # | 轴 | 范围 min~max | 双向 | 消费点（实调点 file:line） |
|---|---|---|---|---|
| 1 | `healing_received_pct` | −200~300 | ✅ | `effects.py:1872`（heal_apply 内） |
| 2 | `healing_done_pct` | −100~300 | ✅ | `effects.py:1878` |
| 3 | `damage_taken_pct` | −100~300 | ✅ | `battle.py:4310` |
| 4 | `damage_dealt_pct` | −100~1000 | ✅ | `battle.py:4283` |
| 5 | `cooldown_pct` | −80~200 | ✅ | `battle.py:3496` |
| 6 | `status_chance_pct` | −100~不限 | ✅ | `effects.py:531` |
| 7 | `stack_gain_pct` | −100~不限 | ✅ | `effects.py:533` |
| 8 | `stack_cap_delta` | 不限（加算差值） | ✅ | `effects.py:534`（**marks 半边未接**） |
| 9 | `status_duration_pct` | −80~300 | ✅ | `effects.py:537` |
| 10 | `status_duration_taken_pct` | −100~300 | ✅ | `effects.py:538` |
| 11 | `status_resist_pct` | −100~不限 | ✅ | `effects.py:532` |
| 12 | `action_bar_shift` | 不限（加算差值） | ✅ | `battle.py:5253` |
| 13 | `resource_cost_pct` | −100~200 | ✅ | `battle.py:1337` |
| 14 | `resource_gain_pct` | −100~不限 | ✅ | `battle.py:1339` |
| 15 | `crit_damage_pct` | −100~300 | ✅ | `battle.py:4782` |
| 16 | `action_speed_pct` | −80~400 | ✅ | `battle.py:2633` |
| 17 | `reward_mult_pct` | 0~400 | ⛔ 单向（下钳 0） | **未接线**——哨兵 `EFFECT_CONSUMER_PENDING`（`gear_stats.py:428`），配了不生效 |

> **三条口径**：① 常说"16 条"= 上表**已接线的 16 条**（第 17 条是登记未实现的哨兵）；② 轴是否生效，**唯一判据是 grep 实调点**，不能只看 `consumer_note` 的措辞；③ 攻防"两侧配对"（治疗/伤害/时长/命中抵抗，一轴两键）**别合并**——那是"装 build 能分别配两侧"的设计。**作者改哪**：要调范围写 `settings.effect_axes.<轴>.{min,max}`（引擎不写死）；**改 `EFFECT_AXIS_SPECS` 字面量属框架级评审**。详见《手册·1》§1.2。

#### C. 枚举 / 时点（值域封闭，作者**不能**加值）

| 常量 | 值域 / 数量 | 唯一源 file:line | 作者能改吗 |
|---|---|---|---|
| `EVENT_POINTS` | **17 时点**（前 16 保序） | `data/event_points.py:25` | ❌ 值域固定（见 §2.3） |
| `STATUS_EVENT_POINTS` | `status_gain`/`status_lose` | `data/event_points.py:38` | ❌ |
| `POOL_KINDS`/`REACTION_KINDS` | 3/3（常见/专属/联动；冲突/增幅/反转） | `data/affinity_keys.py:37`/`:43` | ❌ |
| `AFFINITY_KEYS` | 4（settings 四个段名，**不是"6 个相性键"**） | `data/affinity_keys.py:46` | ❌ |
| `RUNE_TIERS` | (1,2,3) 珠阶 | `data/runes.py:41` | ❌ |
| `QUALITY_KEYS`/`DEFAULT_QUALITY_TIERS` | 四档；边界可经 settings 覆盖 | `core/quality.py:80`/`:56` | ✅ 边界可覆盖 |
| `ABSOLUTE_QUALITY_MAX` | 100 | `core/quality.py:84` | ❌ **硬顶、无 settings 旁路（有意写死）** |
| `MODE_*`/`CRAFT_PATHS` | full/simple/off；四条路径（含 forge） | `core/craft_paths.py:72-88` | ❌；**`MODE_*` 只描述炼金三层漏斗，别套 forge** |
| `TEMPER_VALUE_TYPES`/`TEMPER_ROUNDINGS`/`ESSENCE_V_BASES`/`ESSENCE_SCOPES` | flat/pct；floor/round/ceil；…；… | `data/temper_stats.py:55/58/62/65` | ❌ |

#### D. 阈值 / 默认值表——**作者用 `settings.*` 覆盖，别改框架 `DEFAULT_*` 常量**

| 表 | 默认（节选） | 覆盖段名 | 唯一源 file:line | 改了会影响谁 |
|---|---|---|---|---|
| 面板预算 | white 7.0 / equip 8.0 / buff 5.0 | `settings.panel_budget` | `core/panel_budget.py:102` | 装备/白值/增益占比 → **"斩回"校准与面板占比** |
| 怪物缩放 | hp_mult/atk_mult/def_factor/def_k 100 | `settings.monster_scaling` | `core/panel_budget.py:109` | 怪物面板强度（面板预算的配套） |
| 深度打造 `craft_rules` | 16 键 | `settings.deep_craft.craft_rules` | `content/deep_craft_settings.py:110` | 打造成本预算/品质经验/词条数（**两件套须同步增删**） |
| 淬炼 `temper` | 15 键（`cap_per_level=6`…） | `settings.forge.temper` | `data/temper_stats.py:70` | 淬炼上限/点数；**优先链**：`total_cap` > `total_cap_by_level[等级]` > `等级×cap_per_level`（`core/temper.py:136-167`） |
| 精华产出 `essence_rate` | 15 键、默认 **关** | `settings.forge.essence_rate` | `data/temper_stats.py:106` | 分解回收的经济闭环 |
| 特效强度预算 `effect_budget` | `cap_equiv_pct=8.0`、gate 默认 `warn` | `settings.effect_budget` | `data/gear_stats.py:899` | 特效等效占比与黄/红提示（默认只提示） |
| 过量治疗 `overheal` | 默认关、`mode=discard` | `settings.overheal` | `data/gear_stats.py:1141` | **它不是特效轴**（E5 布尔开关），别搬进轴表 |
| 模块目录 / 推荐组合 | 36 条目 / 3 组合 | **框架不覆盖**（目录不可改；预设包可整体覆盖同 id） | `content/module_catalog.py:70`、`content/module_presets.py:58` | 编辑器模块勾选树与"推荐组合"一键勾 |

> **改常量的通用铁律**：**"未配置 = 既有行为"** 靠每张默认表配套的 `normalize_*()` 归一函数保证；改 `DEFAULT_*` 会让所有没配该段的包**静默变行为**。要加一条特效轴：只改 `EFFECT_AXIS_SPECS` 唯一源，六张派生表自动跟随——**要手改派生表说明走错了**。逐条安全改法见《手册·1》§1.6 / §4.1~§4.9。

### 2.2 变量（作者可以"引用"的东西）

#### A. 公式 / 效果里能引用的变量

| 变量（写法） | 谁提供 | 什么时候能读到 | 改了会影响谁 |
|---|---|---|---|
| **`[技能等级:<技能ID>]`** | 装配层进战注入 `skill_levels`（`core/battle.py`） | **施放该技能时**求值 → 取 `attacker.skill_level[ID]` | 值是**三源并集**（装备赋予/套装档位/`skill_slots` 行 level），**同技能多源取最大**；纯读、不写存档（`core/skill_slots_battle.py`）。**无来源 → 等级 1**；公式不引用它 → 结果逐字节与改前一致。改了会**同步改所有引用该占位符的技能公式** |
| combatant 基础键（18） | 框架默认表 `_DEFAULT_STATS`（`core/battle.py:319`） | 战斗中公式直读 | 是战斗契约；**加键 = 改战斗**（须同时改 ≥4 处构造点） |
| combatant 开战追加键 | 敌方 `battle_launch_commands.py:146`、玩家 `core/pvp.py:92` | 同上 | `enemies.json stats` 里**未映射的键原样透传**进 combatant——作者可借此带自定义数据 |
| `marks` / `marks_total` | `MarksManager.formula_view`（`core/marks.py:421`） | 战斗公式视图 | 只读聚合；改它不影响层数本体 |
| 条件引擎变量 / 运算符 | `core/condition_engine.py:154`（`VAR_ALIASES`）、`:96-123` | 任务/NPC/成就条件求值 | 旧运算符 `min→ge`/`max→le` 与中英别名是**兼容层，别删**（《手册·3》C12） |

> **声明侧（技能等级）**：`skills[].level = {max, growth[]}`——**`max ≥ 2` 才进等级线**，`growth` 长度须 `= max` 且 `growth[0]=1.0`（非法红拦）；旧标量 `level: 1` 兼容。**用什么曲线由作者定**，框架故意不内置"等级→伤害/冷却"映射（**勿当 bug 修**）。详见 `docs/框架扩展开发手册.md` §七 · 技能等级变量。

#### B. 战斗 / 玩家数据对象（**运行期是 dict 还是 dataclass，本框架最大的坑**）

| 对象 | 字段 / 形状 | 谁提供 | 什么时候能读到 | 改它的影响面 |
|---|---|---|---|---|
| **`ItemInstance`** | **20 字段**（`data/item.py:40-102`，frozen） | 框架 | 背包/装备/商店/打造成品行 | **实例级数据优先塞 `stats_bonus` 或 `persistent_state`**；非要加字段要走 9 条清单（读 codec/两条归一链路/迁移补缺…），**漏一条就静默丢字段** |
| **`EquipmentSlot`** | 6 字段（`data/player.py:57-75`） | 框架 | 穿戴槽 | `uid` **回指 `ItemInstance.uid`**，不是自生成 id |
| **`Player`** | 23 字段（`data/player.py:79-113`） | 框架（SQLite 落档） | 玩家主档 | **包自持代码不得直接改**：落档走 `storage.save_player`，运行期改 `ctx`；**7 个字段名 ≠ 列名**是历史设计，别"修正" |
| 状态实例 dict | 14 键，**唯一构造源** `_new_instance`（`core/effects.py:735-763`） | 框架 effects | 状态生效期间 | `decay` 运行期是 **str**（契约 spec 写 float，属**已登记双轨**，不是 bug） |
| 印记实例 dict | 6 键，权威键元组 `_MARK_INSTANCE_KEYS`（`core/marks.py:53-60`） | 框架 marks | 印记存在期间 | `remaining_turns` **条件存在**，代码必须 `.get()` |
| combatant / 战斗快照 | dict，**无单一源**（默认/归一/敌方/玩家 ≥4 处构造） | 框架 core | 战斗全程 | **加一个 combatant 键必须同时改全部构造点**，否则只在部分路径生效 |

> 契约 dataclass 与运行期 dict **同名不同形**（`CombatantSnapshot`/`StatusInstance` 等已自登记"双轨未收敛"）——**别按 dataclass 去 grep 运行期字段，也别"顺手统一"**。详见《手册·1》§2.0~§2.8 / §3 / §4.3。

#### C. `ctx`（指令上下文）——**数量级 + 如实标注**

| 项 | 事实 | 唯一源 file:line |
|---|---|---|
| 内部 `ctx` dict 键数 | **注册态 162~166 / 未注册态 134~138**（随包内模块数浮动；仅注册态多 **28** 键恒定） | `assembly/context.py:1256` `make_context`；详见《手册·1》§2.7.3 |
| 两个"ctx"别混 | **`ExtContext`** = 包扩展收到的**稳定面**（`EXT_API_VERSION="1"`）；**内部 `ctx` dict** = 框架指令壳用，**非扩展契约** | `ext_api.py:125`；`assembly/context.py:1256` |
| ⚠️ 3 个键**当前无框架消费方** | `monster_pool`（注入 `context.py:1670`，未实装→`[]`）· `shop_engine`（注入 `:1348`，**恒 `None` · 准死键**）· `worn_refs`（`:1449`/`:1634`） | 《手册·1》§2.7.3 逐键表（批83 标注）；**登记待收敛，不删键** |

> **作者能改哪**：内部 `ctx` **不是**给作者的接口——包自持代码请用 `ExtContext` + `get_state/set_state`（本包状态格子）。**未注册态缺键**（③ 有而 ④ 没有）：消费方必须 `ctx.get` 兜底。3 个零消费键若将来确有包经 ctx 读取，则改判为"仅供包自持代码读取"，仍须按 `ExtContext` 口径收敛。

### 2.3 事件

**唯一源**：`data/event_points.py:25`（17 时点，值域固定、**前 16 保序**）；**派发唯一出口**：`core/battle.py:2092` `Battle._dispatch_event`。**写效果时 `trigger` 只能取这 17 个值。**

#### A. 17 个时点（名称 / 一句语义 / 何时派发 / 谁收 / 态）

| # | 时点 | 一句语义 | 何时派发（file:line） | 谁收 | 态 |
|---|---|---|---|---|---|
| 1 | `battle_start` | 战斗开始、资源已初始化、CTB 还没建条 | `battle.py:2522`/`:2523` | 两侧各一次 | ✅ |
| 2 | `battle_end` | 战斗收尾（**marks 尚未清零**，效果仍可读印记/状态） | `battle.py:2227`/`:2228` | 两侧各一次 | ✅ |
| 3 | `action_start` | 一次行动开始，在动作分派**之前**（**覆盖全部动作类型**） | `battle.py:3016` | 行动者 | ✅ |
| 4 | `action_end` | 一次行动收尾 | `battle.py:3075`/`:3176`/`:4115`/`:4692`/`:5101`（5 条路径） | 行动者 | ✅（**逃跑/跳过不派发**） |
| 5 | `turn_start` | 该 actor 轮到自己 | `battle.py:2894` | **行动者**（不是双方） | ✅ |
| 6 | `turn_end` | 该 actor 行动收尾（与 `turn_start` 对称） | `battle.py:5228` | 行动者 | ✅（**批81·A1 补点**，见下注） |
| 7 | `status_gain` | 状态**施加成功后**（`res.applied` 为真） | `effects.py:2254` | **状态持有侧** | ✅ |
| 8 | `status_lose` | 状态**被驱散移除后** | `effects.py:2276` | 状态持有侧 | ⚠️ 驱散已接 / **tick 过期未接** |
| 9 | `mark_gain` | —— | **无** | 印记持有侧 | ⛔ 二期未接 |
| 10 | `mark_lose` | —— | **无**（`battle.py:1159` 的 `result["mark_lose"]` 是**战斗结果标记，同名不同物**） | 印记持有侧 | ⛔ 二期未接 |
| 11 | `death` | 死亡标记后 | `battle.py:1190` | **死者自己** | ✅ |
| 12 | `revive` | 复活成功后 | `battle.py:1245` | 复活侧 | ✅ |
| 13 | `on_attack` | —— | **无** | 攻击方 | ⛔ 二期未接 |
| 14 | `on_hit` | —— | **无** | 攻击方 | ⛔ 二期未接 |
| 15 | `on_skill` | —— | **无** | 攻击方 | ⛔ 二期未接 |
| 16 | `season_change` | 季节事件结算之后 | `battle.py:2088`/`:2089` | 两侧各一次 | ✅ |
| 17 | `on_kill` | 击杀（与 `death` **同一判定点**、紧接其后） | `battle.py:1202` | **击杀者侧**（1v1 的另一侧） | ✅ |

> **计数**：已接 **12**（#1–8,11,12,16,17）/ 二期未接 **5**（#9,10,13,14,15）= 17 ✅。
> **⚠️ 与《手册·2》§2.2 的差异（如实标）**：该章仍写"`turn_end` 故意不派发、17 点只有 11 点会派发"（**批81 之前的口径**）；实际 **批81·A1 已补 `turn_end` 派发点**（`battle.py:5228`，为恢复 veinborn `surge_tick`），故现为 **12 点**。**以代码为准**；此处按素材纪律如实标注差异。

#### B. 易混对（照口诀写，别写反）

| 别混 | 一句话口诀 / 区别 | 判据 |
|---|---|---|
| `death` vs `on_kill` | **"我想在谁身上发生什么？"** 动作对象是**死者**→`death`，是**击杀者**→`on_kill`；`target` 相对各自派发侧。**同归于尽/战斗已结束 → `on_kill` 不派发**（故意，不是漏判） | 《手册·2》§3.1 |
| `status_gain` vs `mark_gain` | **状态与印记是两套独立容器**：状态有增益/减益、可被驱散；印记**非增益非减益、天然不吃 dispel**。`mark_gain`/`mark_lose` **无派发点**，写了永不触发 | 《手册·2》§3.2 |
| `turn_start` vs `action_start` | 轮到自己 **1 次** vs 每次行动 **1 次**；`turn_end` **已在行动者收尾派发**（批81·A1 补点，见 #6） | 《手册·2》§3.3（**批81 前口径已过时**） |
| `EVENT_POINTS` vs `[事件:XXX]` | **两套体系、互不派发**：写 `effects.json` 的 `trigger` 查 `EVENT_POINTS`；写条件/任务里的 `[事件:…]` 查 `EVENT_KEY_DEFAULTS`（`core/event_bus.py:66`，13 类） | 《手册·2》§1.1/§3.4 |
| 状态 `on_gain`/`on_lose`/`on_expire` | **三字段两时点**：`on_expire` 与 `on_lose` **共用 `status_lose`**；状态事件默认作用在持有侧 | 《手册·2》§2.5（**稳定契约**） |

#### C. owner 归属——**"谁的效果只能由谁触发"**

| 环节 | 事实 | file:line |
|---|---|---|
| 归属键 | `owned_effect_ids`（`OWNED_EFFECT_IDS_KEY`） | `data/gear_stats.py:494` |
| 谁写 | **装配层**从装备 `passives` + traits `effects` 推导 id 集 | `core/equip_mods.py:319` |
| 谁读 / 过滤 | 战斗侧 `_owner_scope` → 分派器判定式 | `core/battle.py:2124`、`core/event_dispatcher.py:146-151` |
| 三态（**零变化**是灵魂） | ① 两侧都没声明 → **全库扫描**（= 本机制引入前的旧行为）；② 任一侧声明 → 该侧候选 = **自己拥有的 ∪ 未被任何一侧认领的全局效果**；③ 声明为空列表 → 该侧**零候选** | `event_dispatcher.py:100-102`、`:144-151` |
| 判定式 | **`eid ∈ owner` 或 `eid ∉ claimed`**（`claimed=None` 视为无全局豁免）；用的是 effects 注册 id | 同上 |
| 例外 | **状态 `on_*` 事件不受归属过滤**（按 `status_id` 精确定位）；**符文**走 `extra_candidates`（另一条"只对持侧生效"的路） | `event_dispatcher.py:104-105`、`battle.py:2164` |

> **作者能改哪**：**包不写 `owned_effect_ids`**——只写装备的 `passives` / traits 的 `effects`，框架自己推导。**勿当 bug 修**：让"缺省也启用过滤"= 打破零变化（旧包效果集体失效）；改判定式为纯白名单 = 静默吞掉全局效果。去重/上限/chance 全部复用 `EffectRuntime`（`max_triggers_per_turn=10` 等），**别在分派器里另造一套**。详见《手册·2》§4。

#### D. **哪些时点当前没有派发点（如实标，别踩）**

- **静默死效果**（合法枚举 + 无派发点 → 校验器**静默通过**，最危险）：`mark_gain` / `mark_lose` / `on_attack` / `on_hit` / `on_skill`。**唯一可靠判据是本节 A 表**，不是校验输出。（`turn_end` **不在**此列——批81·A1 已补派发点，见 A 表 #6。）
- `status_lose` 的 **tick 过期路径未接**；`on_expire` 声明的效果**当前不会触发**（标**待查 P-1**：只有源码结构、无裁决文本）。
- **未入枚举的未来位**（写了会命中 **Y-19 黄提示**，比上面安全）：`on_struck`/`on_block`/`on_crit`/`on_interrupt`/`on_cc`/`on_synergy`/`on_tick`。
- **自查口径**：`trigger` 拼错或写未来时点 → Y-19 黄提示；写**合法枚举但无派发点** → **静默通过**；非字符串 → R-1 红拦。详见《手册·2》§2.2/§3.5。

### 2.4 状态机

> **共同的规矩**：状态机**本体归框架引擎**，内容只能"声明输入/读取状态"，不能自己写一套推进逻辑。**每台机器的权威状态都在战斗快照里**，续战/落档以它为准。

**① 战斗推进 · CTB 行动条（Charge Time Battle）**
- **谁推进**：调度器 `CTBScheduler`（`core/ctb_scheduler.py:128`）；**逻辑时间唯一推进源** = `advance_to_next_ready()`（`:467`，单调递增）。作战链固定为 `ACTOR_READY → ACTOR_TURN_START → BEFORE_ACTION → ACTION_RESOLVE → AFTER_ACTION → ACTOR_TURN_END`（`core/battle.py:542-544`），全部由行动条推进决定，**不再有"回合"单位**。
- **内容能声明**：CTB 规则参数 `settings.battle.ctb`（`default_recovery`/`speed_reference`/`min_speed`/`action_delay`；经 `battle.py:255-261` 透传给 `CtbRuleConfig`，作者段登记见 `field_meta.py:3112`/`:3123`）；各 action 的 `recovery`（键名兼容中英，缺省取 `default_recovery`）；行动快慢走 `action_speed_pct`/`action_bar_shift` 轴。
- **作者改哪安全**：要"更快/更慢"用特效轴，别碰引擎时序。**改 CTB 时序属框架级评审**（核心契约）。
- **与数值/事件衔接**：快照边界枚举 `CTB_BOUNDARIES = (actor_ready, after_action)`（`battle.py:212`）；相位标注 `PHASE_ACTOR_READY`（`:191`）；关键点 `_resolve_ready_actor`:2724 / `_start_actor_turn`:2878 / `_do_action_inner`:3013 / `_settle`:2199。事件见 §2.3；**`turn` 是兼容镜像 = `action_seq`，不参与计算**（`battle.py:1083`，别当冗余删）。

**② 状态效果（status）：施加 → 层数 → 时长 → 到期/驱散**
- **谁推进**：`core/effects.py`——`apply_status`（`:495`）→ **唯一构造源 `_new_instance`（`:735-763`，14 键）** → `tick_turns`（`:849`）逐行动递减 → `_remove_status`（`:313`）或 `dispel` 分支（`:2257-2277`）。
- **内容能声明**：`statuses.json` 的 `category`（buff/debuff/weak…）、`level`、叠加上限、`value`/`turns`/`charges`（**双维时长**）、`decay`（衰减方式，运行期是字符串）、`on_gain`/`on_lose`/`on_expire`。
- **作者改哪安全**：全在 `statuses.json`；数值作用由 `effects` 动作声明。**改 effects 管线阶段顺序 = 评审**。
- **与数值/事件衔接**：事件 `status_gain`/`status_lose`（§2.3）；层数/时长轴 `stack_gain_pct`/`stack_cap_delta`/`status_duration_pct`/`status_duration_taken_pct`（§2.1 B）；`decay` 类型双轨（契约 float / 运行期 str）是**已登记双轨，不是 bug**。

**③ 印记（mark）**
- **谁推进**：`MarksManager`（`core/marks.py`）——实例构造 `new_inst`（`:254-268`）→ `apply_add`（`:239`，**必中**，重复 +count 至 `max_stack`，到顶不再涨）→ `tick_turn`（`:319`，仅 `duration="turns:N"` 才有 `remaining_turns`）→ `apply_remove`/`apply_clear`（`:271`/`:297`）。容器 `marks_state = {"player":[…], "enemy":[…]}`。
- **内容能声明**：`marks.json` 的 `max_stack`/`polarity`（正/负，`POLARITIES` `marks.py:50`）/`duration`；动作 `mark_add`/`mark_remove`。
- **作者改哪安全**：包内 `marks.json` 与动作。**键元组 `_MARK_INSTANCE_KEYS`（`:53-60`）是权威声明**，加键须与 `new_inst` 两处同步。
- **与数值/事件衔接**：`marks`/`marks_total` 是公式可读聚合（`formula_view` `:421`）；**`mark_gain`/`mark_lose` 无派发点（二期）→ 印记不能用事件触发**，只能用动作。印记**非增益非减益、天然不吃 dispel**（`effects.py:2259`）。

**④ 形态 / 姿态（transform / `stance: air`）**
- **谁推进**：变换引擎三件套——触发 `core/transform.py`（触发闸 C1~C4 于 `can_transform`；`remaining`/`cooldown_remaining` 从触发起算，行动收尾 tick 递减）、还原 `core/transform_revert.py`、快照 `core/transform_snapshot.py`。**跃空姿态**权威来源 = 包 `statuses.json` 的 `"stance": "air"` 声明（`_declared_air_stance_ids` `battle.py:348`）。
- **内容能声明**：job 的 `transform` 段（`transform_skill`/`transform_to`/`duration`/`turns`/`cooldown`/`form_status_id`…）；`statuses[].stance=="air"`；被击落倒地 status id 可配 `air_drop_status_id`（`battle.py` 引擎配置）。
- **作者改哪安全**：**新姿态/新跃空只需在包内声明，不要再改框架表**。无声明时框架回退 legacy 集合（`_LEGACY_AIR_STATUS_IDS` `battle.py:342`）——**`or` 不是 union，勿动**（《手册·3》样例③）。
- **与数值/事件衔接**：`transform_state`（7 字段）入快照（`battle.py:2445`）；`form_status_id` 落 `transform_state` + `status_state` **双写**（双轨挂载）；形态 `cooldown_remaining` 与道具/技能冷却**不同对象**（《手册·3》R9）。

**⑤ 连段（combo）**
- **谁推进**：`core/combo.py`——6 态（`idle`/`in_combo`/`derivable`/`deriving`/`at_max_reset`/`at_max_hold`，`:109-111`），主迁移 8 条；**权威状态 = 战斗快照 `combo_state`**（引擎只读写 `snap["combo_state"][side]`，`:5`）。打断走 `effects.interrupt`；`_settle` 清零 `combo_state={}`。
- **内容能声明**：`skill_chains.json`、技能连段标签六值（`combo`/`combo_preserve`/`combo_push`/`interrupt`…，`:126-129`）、派生条件；侧内五字段 `chain_id`/`chain_name`/`count`/`hold`/`step_index`（`:157`）。
- **作者改哪安全**：包内连段链与标签；**成环是"有意的循环连招"，校验器只提示不拦**（《手册·3》C5）。
- **与数值/事件衔接**：连段计数印记有 legacy 兜底（包声明 `role=="combo_counter"` 优先，`basic_commands.py:1903-1922`）；**`combo.py`（连段状态机）≠ `combo_table.py`（元素组合技）**，同名词不同事、是依赖不是重复（《手册·3》R8）。

**⑥ 资源（法力 `mp` / 能量轴 / 炼金调合能量条）**
- **谁推进**：法力 = combatant 的 `max_mp`/`mp`（默认 100，`_DEFAULT_STATS` `battle.py:319`）；战斗资源轴 = `ResourceAxisEngine`（`core/resource_axis.py:1048`；`get/set/add_value` `:416`/`:445`/`:481`，`check_cost`/`pay_cost` `:574`/`:696`，`gain_energy`/`apply_gain` `:760`/`:815`，技能侧 `:956`/`:990`）+ 生命周期 `ResourceLifecycle`（`core/resource_lifecycle.py:83`，**时点结清**）；炼金调合能量条 = `EnergyBar`（`core/energy_bar.py:82`，懒计算补格）。
- **内容能声明**：资源轴定义/`energy_gain`/`energy_cost`；炼金能量开关 `settings.alchemy.energy_enabled`（**`proficiency.energy` 是兜底源**，`energy_bar.py:114`/`:178`；契约优先级 = settings 为准）。旧类型 `resource_custom` 加载时归一为 `resource`（`resource_axis.py:121`）。
- **作者改哪安全**：包内资源轴/开关声明。**双源优先级已定，别把某一路当真源直接改**（《手册·3》B12 / 核清 C2）。
- **与数值/事件衔接**：`resource_cost_pct`/`resource_gain_pct` 轴消费点 `battle.py:1337`/`:1339`；资源段 `resource_state` 入快照 `battle.py:2451`；**`energy_bar`（调合能量条）≠ `resource_axis`（战斗资源轴）**，不同系统（《手册·3》R7）。

### 2.5 互相影响关系（一张"流转图"）

```
内容声明/配置（content/<包>/** 纯 JSON）
      │  谁拥有：内容包层 · 改哪：编辑器改包内 JSON · 被谁影响：校验器 / manifest 声明顺序
      ▼
装配装载（assembly/**：loader → registry → GameWorld + 装配层计算）
      │  谁拥有：框架装配层 · 改哪：框架级（包不能改） · 被谁影响：manifest.modules、各 settings 段
      ▼
战斗事件派发（battle.py `_dispatch_event` → event_dispatcher.py）
      │  谁拥有：框架 core（派发唯一出口 battle.py:2092） · 改哪：加时点=框架评审 · 被谁影响：owner 归属 / EffectRuntime 上限
      ▼
状态与层数变更（effects.py / marks.py / combo.py / transform.py / resource_axis.py）
      │  谁拥有：各引擎 · 改哪：包内 statuses/marks/skill_chains 声明 · 被谁影响：施加成功(applied)/层数上限/时长
      ▼
数值轴 / 公式求值（gear_stats 特效轴 · combatant · condition_engine）
      │  谁拥有：data 层轴表（唯一源） · 改哪：settings.effect_axes 调范围 · 被谁影响：三层属性管线、条件加成
      ▼
伤害 / 治疗结算（battle.py 乘区 → effects.py 管线）
      │  谁拥有：core（`DEFAULT_PIPELINE_ORDER` effects.py:129-138） · 改哪：⚠️ 阶段顺序=稳定契约勿动 · 被谁影响：输出/承伤/暴击/护盾/保底
      ▼
战报与日志（message_format 渲染 · event_bus 计数 · battle 快照）
         谁拥有：core 渲染层/事件计数 · 改哪：优先 E2b `templates.json` 改文案 · 被谁影响：模板宽度门禁、任务/成就条件
```

| 步骤 | 谁拥有（权威源） | 你改哪里 | 会被谁影响 |
|---|---|---|---|
| ① 内容声明/配置 | 内容包层（纯 JSON） | 编辑器改包内 JSON；**未在 `manifest.modules` 声明的文件不加载** | 红拦 5 类 → 整包拒绝；加载顺序 = 声明顺序 |
| ② 装配装载 | 框架 `assembly/**` | 框架级（**包不能改**） | `manifest.modules`、各 `settings` 段；装配层把装备 `passives`/traits 推导成 `owned_effect_ids`、把技能三源合并成 `skill_levels` |
| ③ 事件派发 | 框架 core（唯一出口 `battle.py:2092`） | 加时点 = 框架评审（枚举+派发点+数值影响+批次） | owner 归属过滤、符文 `extra_candidates`、`EffectRuntime` 的每回合/每场上限与递归深度 |
| ④ 状态与层数变更 | 各引擎（effects/marks/combo/transform/resource_axis） | 包内 `statuses`/`marks`/`skill_chains` JSON 声明 | 施加是否成功（`applied`）、层数上限、时长/charges；结果进战斗快照 |
| ⑤ 数值轴/公式求值 | `data/gear_stats.py` 轴表（**唯一源**） | `settings.effect_axes` 调范围、`settings.*` 调阈值、公式写 `[技能等级:ID]` | 三层属性管线（白值→flat→pct→临时层→条件）；**未配置 = 零变化** |
| ⑥ 伤害/治疗结算 | core 乘区 + effects 管线 | ⚠️ **改阶段顺序/合并阶段 = 稳定契约，勿动**；承伤走 `damage_taken_pct`、减免走 `defense.mitigation`（**叠乘、互不替代**） | 输出轴 × 承伤轴 × 暴击 × 护盾/保底伤害（`min_damage`） |
| ⑦ 战报与日志 | core 渲染层 / `event_bus` 计数 / 战斗快照 | 改文案**优先 E2b `templates.json`**；渲染层新增分支必须兜底不抛 | 模板宽度门禁（手机单行不折行）；计数被任务/成就条件消费 |

> **一句话记法**：**声明归包、装配归框架、事件归分派器、状态归引擎、数值归轴表、结算归管线、呈现归渲染。** 改上游会顺流影响下游；**动任一步前先问"这一步的权威源在哪"**——权威源在框架的，就写声明而不是改代码。

---

## 三、「别重复造」对照表

> **这一节是你来查"到底有没有现成机制"的地方。** 顺序：先看表 1 有没有对上你的心愿；再看表 2 有没有踩到"重复实现"的反例；最后按表 3 三步自查。

### 表 1 · 想做 X → 该用 Y（已有机制）→ 别造 Z

| 你的心愿（想做 X） | 用现成机制 Y | 别造 Z |
|---|---|---|
| 给技能加成长 | **技能等级变量** `[技能等级:<技能ID>]`（`core/skill_slots_battle.py`；手册§七） | 自建成长线/等级→数值映射表 |
| 加增伤/减伤/增疗/减疗 | **双向修正轴**（一条轴两方向）：`damage_dealt_pct`/`damage_taken_pct`/`healing_done_pct`/`healing_received_pct`（《手册·1》§1.2.2 轴表） | 新增"减X/增X"两套机制 |
| 让装备有特效 | **特效轴 + 事件时点 + 归属过滤**（`gear_stats.py:230` 轴表唯一源；《手册·2》§4） | 改战斗引擎 |
| 新玩法模块 | 先查 **模块目录/推荐组合**（`module_catalog.py:70`、`module_presets.py:58`） | 新造模块 |
| 加货币/材料 | 既有 `items` + `Player.currencies`（`player.py:93`） | 自建经济系统 |
| 任务/任务板 | 既有 `quest`/`quest_board` 模块（`module_catalog.py:70`） | 自建任务系统 |
| 商店/库存/限购 | 既有 `shop` 模块（`shop.json`；`shop_models.py:5` 库存+个人限购并存） | 自建商店 |
| 副本/地图探索 | 既有 `dungeon`/`maps` 模块（`module_catalog.py:70`） | 自建副本 |
| 加一套冷却 | **`cooldown_pct` 轴**（《手册·1》§1.2.2）/ 道具 `cooldown_of` / 技能冷却管线（`battle.py:3496`） | 又造一套冷却（会双计） |
| 状态命中率 | `status_chance_pct` 轴（消费点 `effects.py:531`，对 buff/debuff 一视同仁） | 新增命中字段 / 按 scope 分治 |
| 状态/增益时长 | `status_duration_pct` / `status_duration_taken_pct`（`effects.py:537`/`:538`） | 自建计时器 |
| 层数叠加/上限 | `stack_gain_pct` / `stack_cap_delta`（`effects.py:533`/`:534`） | 自建层数逻辑 |
| 出手快慢/行动条 | `action_speed_pct` / `action_bar_shift`（`battle.py:2633`/`:5253`） | 自建速度公式 |
| 资源消耗/回复 | `resource_cost_pct` / `resource_gain_pct`（`battle.py:1337`/`:1339`）+ `core/resource_axis.py` | 自建资源系统 |
| 暴击伤害 | `crit_damage_pct`（消费点 `battle.py:4782`） | 新增暴击系统 |
| 击杀时触发 | **`on_kill`**（`battle.py:1202`；《手册·2》§3.1） | 监听 `death` 反向实现 |
| 死亡时触发 | **`death`**（`battle.py:1190`） | 用 `on_kill` 顶替 |
| 状态被驱散时触发 | `statuses[].on_lose`（`effects.py:2276`） | `mark_lose`/`mark_gain`（**无派发点**） |
| 每回合/每次行动触发 | `turn_start` / `action_start`（`battle.py:2894`/`:3016`） | 新造 hook |
| 只对装备者生效 | **`owned_effect_ids` 归属 + 装备 `passives`**（`equip_mods.py:319`） | 自建过滤逻辑 |
| 包自定义指令 | **E1** `commands.json` + `ext/commands.py`（`pack_ext.py:481`；手册2 §5.2） | 改框架指令（重名一律拒绝） |
| 改文案/提示模板 | **E2b** `templates.json`（手册2 §5.4） | 改框架模板 |
| 包私有状态存档 | **`ExtContext.set_state` 包状态格子**（`ext_api.py:291`；手册3 §1.4） | 给 `players` 表加包专属列 |
| 包内测试/构建 | **E3** `content/<包>/tests/` + `scripts/build.py`（手册2 §5.5） | 塞进主套件 |
| 品质分级 | 四档 `core/quality.py:80`（`quality_level` 1~10 是**正交维度**；手册3 R1） | 再定一套品质口径 |
| 强化 vs 淬炼 | `enhance_level` 与 `temper_alloc` **状态分账**（`core/temper.py:19-20`） | 合成一套 |
| 打造失败/随机 | `forge` 确定性（手册3 A1）/ 随机归**炼金与强化** | 给 forge 加成功率 |
| 天气变化 | **确定性抽签**（手册3 A3） | 改真随机 |
| 调数值范围/阈值 | 写 `settings.*` 段（手册1 §1.6） | 改框架 `DEFAULT_*` 常量 |
| 新增一条特效轴 | 改 **`EFFECT_AXIS_SPECS` 唯一源**（`gear_stats.py:230` 轴表唯一源；《手册·1》§4.1） | 手改派生表 |
| 地图双向边 | `bidirectional` 声明（`map_models.py:694`，**允许刻意不对称**） | 写死对称检查 |

> **表 1 用法**：只要这里能对上你的心愿，**就写声明/配置，不要写代码**——每行"Y"都是框架已接线的唯一源。没对上，再看表 2 是否踩了反例，仍没有才走本节表 3 的三步。

### 表 2 · 常见"重复实现"反例（**这样造会怎样**）

| # | 重复实现 | 这样造会怎样 | 判据来源 |
|---|---|---|---|
| 1 | 又造一套品质口径 | **面板占比与"斩回"校准失效**；与 `quality` 四档、`quality_level` 1~10 的正交关系冲突 | 《手册·3》R1；批45/批55 测量报告 |
| 2 | 又造一套冷却 | 与 `cooldown_pct` 轴**双计**（同一冷却被算两次，数值翻倍） | 《手册·3》R9；《手册·1》S4 |
| 3 | 给 `forge` 加成功率/失败分支 | 违背用户拍板铁律；TC-04"确定性差分=0"与素材经济崩 | 《手册·3》A1/样例① |
| 4 | 把承伤/易伤并进 `mitigation` 阶段 | 与护盾/保底伤害交织、结算顺序改变，红线对拍崩 | 《手册·3》样例④/C4 |
| 5 | 手改特效轴派生表（`GEAR_EFFECT_KEYS`/`GEAR_LABELS_ZH`…） | 下次 `import` **覆盖**手改，唯一源断裂 | 《手册·1》S1/§4.1 |
| 6 | 新增 `ItemInstance` 字段只改 dataclass | 两条归一链路**静默丢字段**（不报错） | 《手册·1》§4.3 / N2·N3（批83 已收敛为 `data/item.py::item_instance_from_mapping`） |
| 7 | 在别处自己生成 `uid` | 与迁移补发 uuid 冲突/重复 → **符文镶嵌挂错物品** | 《手册·1》S13/S15 |
| 8 | 包写 `owned_effect_ids` / 让归属"缺省也启用" | 打破零变化承诺，**旧包效果集体失效**或全局效果被静默吞掉 | 《手册·2》§4.3 |
| 9 | 文件放进 `content/` 但不写 `manifest.modules` | **不加载**（`settings.json` 是唯一双通道例外） | 《手册·3》§1.3；《手册·2》§7.3.1 |
| 10 | 拿 `mark_lose`/`on_hit` 当 `trigger` | 合法枚举但**无派发点**，效果永不触发且校验器静默通过 | 《手册·2》§2.2/§3.5（**注意 `turn_end` 已有派发点**，见《说明》§2.3 #6） |

### 表 3 · "先查再动手"三步（**三步都没命中，才轮到 vibecoding**）

| 步 | 查什么 | 去哪查 | 命中就怎么办 |
|---|---|---|---|
| ① | **模块目录 / 字段元数据**（有没有现成模块、字段、校验） | `content/module_catalog.py:70`、`content/field_meta.py`、编辑器"推荐组合"与字段气泡 | 写声明 / 在编辑器点出来 |
| ② | **《手册·1》常量与数据结构表**（键族 / 17 特效轴 / 阈值表 / `ctx`·`ItemInstance` 等字段） | `docs/审查/审计与方案/API手册_1_常量与数据结构.md` §1~§4 | 用现成键 / 写 `settings.*` |
| ③ | **《手册·2》事件与扩展点**（17 时点三态表 / owner 归属 / 93 条包声明段 / E1·E2·E3） | `docs/审查/审计与方案/API手册_2_事件与扩展点.md` §2~§7 | 接现成时点 / 写声明段 / 用扩展点 |

> **三步的产出**：若能指出"用哪个模块/字段/时点/声明段 + `file:line`"→ **纯配置**；若三步都确实没有、且新机制**非代码不可**→ 才走 **vibecoding（§五·模板 B）**，并在订单里写明"已查 ①②③、均无命中"。

---

## 四、开工前要准备的三样东西

1. **编辑器**（本地跑或连服务器，见《编辑器使用说明》）；
2. **四份关键文档**——**让 AI 先读，别让它凭记忆干**：
   - `docs/框架扩展开发手册.md` ← **最重要**（框架能做什么、谁负责什么、**哪些"像 bug 其实是设计"**）
   - `docs/编辑器使用说明.md`（怎么操作）
   - 相关系统的《*_实现口径》/《*_实现说明》（某个系统的具体口径）
   - `docs/矛盾与待裁决登记.md`（**哪些是"已经拍板不做"，不是缺口**）
3. **一条铁律**：**先让 AI 读文档 → 出方案 → 你拍板 → 再动手**。
   ⚠️ 一上来就说"帮我实现 X"，它容易乱改、也容易把"故意的设计"当 bug 修掉。

---

## 五、怎么跟 AI 说话（4 个可复制模板）

### 模板 A · 加内容（纯配置，最常用）
```
读 docs/框架扩展开发手册.md 和 content/<我的包>/ 的现状。
我要在 <模块> 里加 <N> 条 <东西>，设计意图是：<一两句>。
请先告诉我：① 放哪个文件/字段 ② 有没有同类先例可抄 ③ 有没有校验陷阱。
我先看方案，确认后你再改。
```

### 模板 B · 加新机制（vibecoding）
```
先读 docs/框架扩展开发手册.md（尤其"稳定契约"与"勿当 bug 修"两节）+ 相关《*_实现口径》。
我要加一个新机制：<一句话>。要求：
① 能不做成"配置声明"就不加代码；非加不可时说明理由
② 不许新造与既有系统重复的口径（先查有没有能复用的）
③ 零行为变化：不启用/不配置时，旧内容必须逐字段与改前一致
④ 给我：改动点 file:line + 实跑输出 + 对拍证据 + 全量测试结果
先出方案（分 2~3 步，每步可独立停下验收），我拍板后再动第一步。
```

### 模板 C · 报问题
```
现象：<我做了什么> → <看到什么>
期望：<应该是什么>
复现：<第 1 步、第 2 步…>
证据：<截图/原文/报错>
先复现再定性：是真 bug，还是手册里写过的"故意设计"？定性后给我最小修法。
```

### 模板 D · 让它体检/审计（只读）
```
只读，不要改任何东西。
按 <某个原则> 审计 <范围>，逐条给 file:line 证据；
判不准的标"待查"，宁少勿误；最后给我"必须修/建议修/可接受"三档清单。
```

---

## 六、你必须让 AI 遵守的 7 条规矩（写进每一单）

1. **先读文档再动手**——尤其是《框架扩展开发手册》
2. **零行为变化**：不启用新东西时，旧内容必须**逐字段与改前一致**（要它给"对拍"证据）
3. **不重复造**：同一件事只允许一个源；先查有没有能复用的
4. **不许改"护栏测试"**：它若说"护栏红了"→ 让它**停下、还原、报告**，不许改测试糊过去
5. **不许自动上传**：让它**不要 `push`、不要动主干**——你审完自己决定合不合
6. **每步都要证据**：`file:line` + **实跑输出**（不是"应该没问题"）
7. **"故意的设计"不许当 bug 修**——让它先查手册里那张「勿当 bug 修」清单

---

## 七、怎么验收 AI 的活（5 问，照问就行）

| # | 问它 | 不合格的样子 |
|---|---|---|
| 1 | **改动点在哪个文件第几行？** | 只说"改好了"，给不出位置 |
| 2 | **有实跑输出吗？** | 只说"应该能行"、"理论上" |
| 3 | **对拍了吗？**（不启用时与原来是否一致） | 说"我改的是新增，没影响"但没跑 |
| 4 | **全量测试绿吗？工作树干净吗？** | 有红灯还说"那是老问题" |
| 5 | **有没有顺手改了别的？** | 改动清单里有你没要求的东西 |

> **一条经验**：AI 的**自我报告不等于事实**。让它给**能复现的证据**（命令 + 输出），你再抽查一两条。

---

## 八、常见坑与报错对照

### 编辑器
| 现象 | 原因 / 对策 |
|---|---|
| 浏览器打不开 / 页面空白 | 服务没起来（`127.0.0.1:8090` 先自测）· 端口被占用（换端口） |
| 中文乱码（Windows 脚本） | `.bat` 必须 **GBK 编码 + CRLF**；文本文件用 UTF-8-BOM |
| 改完不生效 | 编辑器有自己的"保存"；服务器上跑的机器人**改完内容要重启服务**（无热重载） |
| 数据写坏了 | 用编辑器「**回退到上一份备份**」；改动前先导出 `.ttrpack` 留底 |

### 跟 AI 协作
| 现象 | 原因 / 对策 |
|---|---|
| **它跑一半没产出** | 通常是**额度/中断**（不是逻辑问题）。让它**先写骨架**、**每节写完立刻落盘**，再重试 |
| **它自报"已修"但你没看到证据** | 一律要求 `file:line` + 实跑输出；**自己去跑一遍** |
| **它把"故意的设计"改掉了** | 让它读手册 §四「勿当 bug 修」；**能给出文档/注释/变更记录判据的，不许动** |
| **它一次改太多** | 要求**分步 + 每步可独立验收**；一单一事 |
| **它说"全绿"但有红灯** | 让它贴**原始输出**；红灯要么修，要么**明确解释为什么不是这次造成的** |

---

## 九、安全与回滚（务必看）

- **别把密钥/账号发进聊天或提交进仓库**（私钥、token、密码）；分享配置时先删敏感字段
- **改动前打点**：让 AI **每完成一小步就提交一次**（出问题能精确回退）
- **留底**：内容包定期导出 `.ttrpack`；关键文件另存一份
- **回滚三招**：① 编辑器「回退到上一份备份」② `git checkout` 单文件 ③ 整包换回你留的 `.ttrpack`
- **不确定就先别合**：让 AI 的改动停在分支上，你自己试过再合

---

## 十、进阶：什么时候你可以自己动手（不用惊动 AI）

当你已经能：
① 看懂 JSON 里的字段名（编辑器有**中文名 + 说明气泡**）
② 会用编辑器的「**校验**」（红拦必修、黄提示按需）
③ 会用「**导出/导入**」和「**回退备份**」

→ 恭喜，**90% 的内容工作你已经能独立完成**；剩下需要动框架的，再按上面模板找 AI。

---

## 十一、一页速查（贴墙版）

```
配置能做的：物品/装备/怪物/技能/地图/任务/商店/配方/数值/公式  → 编辑器里点
要写代码的：框架里没有的新机制                                  → 找 AI（模板 B）

先查再动手：先查「能力地图（§二）」+「别重复造（§三·三步）」
            ① 模块目录/字段元数据 ② 手册·1 常量表 ③ 手册·2 事件表
            三步都没命中，才考虑 vibecoding；能写声明就不加代码

下单必带：① 让它先读文档 ② 零行为变化对拍 ③ 不许改护栏 ④ 不许自动上传
         ⑤ 每步给 file:line + 实跑输出 ⑥ 分步、一单一事

验收 5 问：改动在哪？跑了没？对拍了吗？全绿+工作树干净？有没有顺手改别的？

出事三招：编辑器回退备份 → git checkout → 换回 .ttrpack
绝不外传：私钥 / token / 密码
```

---

## 十二、新手实操（P0）与协作速查（P1）

> **第二批新增**：12.1~12.5（P0）是「先做一遍 + 防重复造」的硬门槛；12.6~12.10（P1）是跟 AI 协作的省钱、开单、纠偏、验收与指令速查。
> **行号口径**：同 §二——`file:line` 以本次写入时的 HEAD 为准，框架后续改动会漂移，权威口径以《手册·X》§Y 为准。
> **简写**：本章 `index.html` = `qbot_rpg/web/static/index.html`（编辑器前端）；`《编辑器使用说明》` = `docs/编辑器使用说明.md`。

### 12.1 你的第一个内容包（15 分钟实操）

**目标**：从空包走到导出 `.ttrpack`。**每步三列**：你做什么 → 你会看到什么 → 不对时看哪里。

| # | 你做什么 | 你会看到什么 | 不对时看哪里 |
|---|---|---|---|
| 1 | 起编辑器：本地 `bash scripts/editor_start.sh`（默认 `127.0.0.1:8090`，`scripts/editor_host.py:310`；可用 `--port` 改）。**服务器**：服务常驻 `127.0.0.1:8090`，本地开 SSH 隧道 `ssh -N -L 8090:127.0.0.1:8090 用户@服务器` | 终端打印「访问地址 http://127.0.0.1:8090/」；浏览器打开该地址 | 缺依赖/端口占用 → 脚本打印人话原因+处理办法（《编辑器使用说明》§一·1）；服务器模式见 §一·2/§一·6。**待查**：口述的本地 `8930` 在本仓库检索不到出处，此处按默认 `8090` 写 |
| 2 | 准备一个**空包**并选中它：顶栏 `pkg=` 选包；空包可用导入一份最小 `.ttrpack` 新建（`index.html:1172`），或复制 `content/demo_blank/` 起步 | 第 1 栏为空、中栏显示空态 | 包不出现 → 看 `content/<包>/manifest.json` 在不在；显示名来自 `manifest.json` |
| 3 | 看空态卡 | 中栏显示「这个包还没启用任何模块」+「打开模块开关」（`index.html:4493`，文案 `:4496`） | 若显示「这个模块还没有条目」→ 已有模块，直接跳到第 5 步 |
| 4 | 点「推荐组合」：右上角 **⚙ 模块**（`index.html:975`）→ 面板顶部「推荐组合」（`:1079`/`:4631`）→ 选一组 | 模块被**累加**勾上，提示「已自动带上：…」 | 数据源 `qbot_rpg/content/module_presets.py:58`；实测生效数 **基础 RPG 包 12 / 生活冒险包 13 / 故事探索包 12**（多出的 = 依赖自动补勾：生活包补 `maps`+`effects`，`preset_modules_with_deps` `:158`）。点错 → 面板底部「回退最近一次模块变更」 |
| 5 | 点左栏模块 → 点 **+ 新建条目**（`index.html:1011`） | 第 3 栏出现表单（字段中文名来自包内 `field_meta.json`） | 按钮灰 → 模块没选中，再点一次左栏模块（批66：一键启用后会自动选中，`:3963`） |
| 6 | 填字段（ID/名称等）；可悬停字段看气泡说明 | 改动进入草稿、出现「未保存」标记 | 字段含义看《编辑器使用说明》§三·7；拿不准就先只填 ID+名称 |
| 7 | 点 **校验**（`index.html:1041`） | 只检查不写盘；列出「哪一项·为什么·怎么改」 | 没改动时按钮是灰的（§四·1） |
| 8 | 处理提示：🔴 红拦必修、🟡 黄提示按需 | 红拦存在 → 保存**一个字节都不写**；黄提示（如引用目标不存在）仍可保存 | 颜色含义见《编辑器使用说明》§四·4 |
| 9 | 点 **保存** | 校验→备份→原子写→回读复核，顶栏「已保存」（§四·2） | 失败提示见 §四·5；救回点「回退到上一份备份」（§四·3） |
| 10 | 导出 **.ttrpack**：📦 导出/导入（`index.html:978`）→「导出此包」（`:1167`） | 下载文件名形如「包名-日期.ttrpack」（`:1158`） | 只读身份也能导出；导入才会新建包（`:1182`） |

> **做完这 10 步，你已经会做 90% 的内容工作了**。下一步：拿你的心愿去 §三 表 1「想做 X → 用现成 Y」对一遍；**要写代码前先过 12.2 的 5 问**。

### 12.2 动手前 AI 自查 5 问（防重复造硬门槛）

**规则**：这 5 问**没回答完，不许动手**（写代码 / 加字段 / 加时点 / 加轴）。每问都要给 `file:line`，判不准就标「待查」——**不许猜**。

| # | 自查 | 去哪查 | 合格的样子 |
|---|---|---|---|
| ① | 框架里有没有**同类机制**？ | 《手册·1》常量表（`docs/审查/审计与方案/API手册_1_常量与数据结构.md` §1，尤其 §1.2 特效轴全表）；《手册·2》事件表（`API手册_2_事件与扩展点.md` §2）；本说明书 §二 能力地图 | 指出现成的轴 / 模块 / 时点 / 字段名 |
| ② | 它**在哪个文件**（file:line）？ | 唯一源纪律（《手册·1》§1.2）：键空间只有一处定义 | 给出 `file:line`；判不准标「待查」 |
| ③ | **消费点在哪**（谁真的读它）？ | `grep -rn "<键/字段>" qbot_rpg/` 找实调点 | 指出实调点 `file:line`；**轴是否生效的唯一判据是 grep 实调点**（本文 §2.1 B 口径②），不看 `consumer_note` 措辞 |
| ④ | 有没有**现成声明段**可用？ | 《手册·2》§7 的 93 条包声明段（**行数口径** = manifest 9 + settings 41 + 模块 json 30 + `field_meta.json` 12 + `commands.json` 1，`API手册_2_事件与扩展点.md:830`） | 能写声明段 → **写配置，不加代码** |
| ⑤ | **有没有被测过**？ | `tests/` 里搜键名 / 模块名（例：登记纪律 `tests/unit/test_batch50_effect_axes.py:140`） | 指出测试文件；没测过 → 先补测再谈接线 |

**合格回答示例**
> `cooldown_pct` 是现成轴（唯一源 `qbot_rpg/data/gear_stats.py:280`），消费点 `qbot_rpg/core/battle.py:3496`，可写声明段 `settings.effect_axes.cooldown_pct`（《手册·1》§1.2.2），已有测试 `tests/unit/test_batch50_effect_axes.py`。→ 走配置，不写代码。

**不合格回答示例**
> 「框架里没有，我新加一个 `cd_reduce` 字段。」——没查 ①②③，给不出 `file:line`，也没提测试；**打回，不许动手**。

### 12.3 同义反复与别名归并表（防写了旧键以为生效）

> **一句话**：旧键不是「另一个键」，是**同一个轴**的别名，**只换算一次**（不双计）。唯一源 `EFFECT_LEGACY_ALIASES`（**6 条**，`qbot_rpg/data/gear_stats.py:589`），每条由轴表的 `legacy_alias: ((旧键, sign), …)` 声明（`:248`/`:259`/`:272`/`:286`/`:298`）；换算式 `pct = sign × 旧键值`。

| 旧写法 | 归并到（新轴） | 关系 | 换算 / 备注（来源） |
|---|---|---|---|
| `cooldown_reduction_pct` | `cooldown_pct` | 归并·**不双计** | `sign = -1`：旧值 30 → `cooldown_pct = -30`（= 冷却 ×0.7）。唯一写入点 `route_legacy_aliases_into_flat`（`gear_stats.py:759`），`route_bonus_into` 对该键仍显式跳过。批53（`CHANGELOG.md:478-480`） |
| `immune_dmg` | `damage_taken_pct` | 归并·**不双计** | `sign = -1`，作**负半轴**别名（减免）；经 `combatant_updates`（`gear_stats.py:797`）`axis += sign × 旧值`。批52（旧编号批50，`CHANGELOG.md:504-507`） |
| `heal_amp_pct` | `healing_done_pct` | 归并·**不双计** | `sign = +1`；同上。批52（旧编号批50，`CHANGELOG.md:502-504`） |
| `weakness_dmg_pct` | `damage_dealt_pct` | 归并·**不双计** | `sign = +1`；经战斗桥 pct 层归入本轴。批70（`CHANGELOG.md:274-276`） |
| `debuff_chance_pct` | `status_chance_pct` | 归并·**不双计** | `sign = +1`；**通用命中，当前不分 buff/debuff**（批53 有意，批82 复核确认，`CHANGELOG.md:482`、`:22`） |
| `buff_chance_pct` | `status_chance_pct` | 归并·**不双计** | `sign = +1`；同上 |

**其它自查**：拿不准某个旧键还有没有用，跑 `grep -rn "旧键名" qbot_rpg/ tests/`——若只出现在 `EFFECT_LEGACY_ALIASES` 与测试里，说明它**只是兼容别名**，不是可用来「新增」的键。

> **结论**：**新写法优先；旧写法仍可用，但不要用来「新增」效果**。旧键与新键是**两个不同键**，同时写会被各算一次（双计）；新增请只写新轴。

### 12.4 登记即承诺原则与「写了没用」怎么报

**原则**：**没有消费者的登记不许存在**——一条轴 / 字段 / 开关「登记进编辑器或常量表」= 对作者承诺「它可以配、配了会生效」。原文见《手册·1》§1.2.1（`docs/审查/审计与方案/API手册_1_常量与数据结构.md:68`）；三条硬规则在 `qbot_rpg/data/gear_stats.py:56-59`、`:207-210`、`:224`：

| 规则 | 含义 | 违规形态 |
|---|---|---|
| **无消费点的轴不得登记** | 登记必须写 `consumer` | `consumer` 留空（测试钉死：`tests/unit/test_batch50_effect_axes.py:140`） |
| **有方向但无唯一收口 → 写哨兵** | `consumer = EFFECT_CONSUMER_PENDING` + `consumer_note` 写明候选点 | 把候选点之一**伪造成**唯一消费点 |
| **登记即承诺「配置生效」** | 不能只登记、留待以后 | 确实不生效却不说；必须在 `display.help` 明说「当前未实现，配置不生效」（范例 `reward_mult_pct`，`gear_stats.py:432-434`） |

**发现问题后，只有三选一**（不许「先登记着」）：① **接线**（补唯一消费点）② **删除**（登记项 + `field_meta` + help 一起）③ **明确标「未实现」**（help 明说 + 预设不发售）。批70 与 `审计4_勿增实体_死实体与空转.md:183-189` 对 R23~R25 等零消费字段给的就是「接线或删」。

**报告模板（复制即用）**
```
我在 <字段/键/开关> 写了 X，游戏里没反应。
复现：第 1 步… 第 2 步…（哪个包、哪场战斗/哪个界面）
期望：<_>；实际：<_>
证据：<截图 / 日志原文 / file:line>
```

**AI 应如何处置**（按顺序、不许跳）：① `grep -rn "<字段>" qbot_rpg/` 找消费点 → ② 定性：真有消费只是没配 / 无消费 / **故意未实现**（先查《手册·3》§3「勿当 bug 修」）→ ③ 按上面三选一 → ④ 给证据（`file:line` + 实跑输出）。

### 12.5 示例包导览（跟着 content/zz_craft_demo 学）

> `content/zz_craft_demo/` 是**教学示例包**（`manifest.json:1`）；**只用于教学，不碰你的真实包**——要动手就复制成你自己的包再改。

| 模块（文件） | 一条真实数据要点 | 你照着改什么 |
|---|---|---|
| **相性四段**（`settings.json`） | `affinities` **4**（lunar/frost/ember/verdant，`:27`）· `affinity_pools` **11**（通用池 + 4 专属池 + link/set 池）· `affinity_linkage` **1** · `affinity_reactions` **3** | 词条池写 `requires_affinity`；联动/反应照抄段名；**别在代码里写相性**（段名见 `data/affinity_keys.py:46`） |
| **材料与图纸**（`items.json`） | **36** 条材料，带 `material_level`/`material_quality`/`affinities`/`material_tags`（如 `vein_shard`、`mossvein_herb`） | 照抄字段结构填你的材料；图纸走 `recipe.json` |
| **特效预设**（`effects.json` + `traits.json`） | `effects` **8** 条原子动作；`traits` **8** 条被动，含 `affinity_variants`（月蚀/炎脉变体，`traits.json:11`） | 被动用 traits 引用 effects；变体靠 `affinity_variants`，**别新建机制** |
| **强化与淬炼**（`enhance.json`） | `max_by_quality_level`（1:3…6:18）· `temper.cap_per_level=6` · `cost_per_point.essence=1593` | 只改数值；覆盖段 `settings.forge.temper`（《说明》§2.1 D），**别改框架 `DEFAULT_*`** |
| **基础合成**（`recipe.json`） | **6** 条 `kind=craft`（1 材料 → 1 件 `*_a_mid` 基装），字段 `materials`/`output`/`cost` | 照抄配方结构；`synth_allowed=true` 才进合成 |
| **分解取材**（`forge.json`） | **1** 棵树（`tree_zz_demo_weapon`），节点 `materials` 决定分解取材 | 照抄树/节点；`parent` 决定前置 |

> **读法**：先在 §三 表 1 找到你要做的机制 → 回本表找最接近的示例文件 → 复制结构改内容。**示例包不改框架，你也不该改示例包**。

### 12.6 成本与额度管理（少烧 token 清单）

| 做法 | 怎么落 |
|---|---|
| **先写骨架再补** | 开头就让它把本节/本章的**小节标题 + 要点清单先落盘**，再逐节填；跑一半也有可续的半成品 |
| **一次一事** | 一份订单只做一节 / 一个模块，别把「加内容 + 改机制 + 顺手重构」混在一起（§五 模板 B） |
| **能只读就别改** | 审计 / 查问题用 §五 模板 D（**只读、不改**），避免误改 |
| **明确「不做清单」** | 订单里写死「这次**不改** X / Y / Z」，防止顺手扩散 |
| **让 AI 每步落盘** | 每完成一小节立刻写文件并单独提交；聊天里说「改好了」不算（§九「每完成一小步就提交一次」） |
| **避免重复跑全量** | 改动面小时按《手册·3》§③表跑**子集**门禁（`API手册_3_权责与勿当bug修.md:688`）；只有发布前 / 大改才 `python scripts/run_all_tests.py` |
| **长任务分批** | 拆成 2~3 步、每步可独立验收（§五 模板 B ④）；断点处写明「已完成到哪」 |

**「跑一半没产出」怎么识别 / 怎么重试**

- **识别**：多半是**额度/中断**（不是逻辑问题）——表现 = 没有最终报告、日志**没有正常收尾**（没有「全绿 / 已完成」总结），只留半截改动。见 §八「它跑一半没产出」行。
- **重试姿势**：① 让它**先写骨架**、并说清**已完成到哪一步**；② 从断点续，一次只推进一小节；③ 每节写完**立刻落盘 + 单独 commit**；④ 大任务分几次做，别一次要它交整章。

### 12.7 整页开工单模板（复制即用）

```
【读哪些文档】先读，别凭记忆：
  docs/框架扩展开发手册.md（稳定契约 / 勿当 bug 修）
  docs/编辑器使用说明.md
  相关《*_实现口径》/《*_实现说明》
  docs/矛盾与待裁决登记.md（哪些是已拍板不做）
  本说明书 §二 能力地图 + §三 别重复造 + §十二 12.2 五问

【7 条规矩】① 先读文档再动手 ② 零行为变化对拍 ③ 不重复造 ④ 不许改护栏测试
  ⑤ 不许 push、不许动主干 ⑥ 每步给 file:line + 实跑输出 ⑦ 故意的设计不许当 bug 修

【5 问自查】动手前先答完（答不出就标「待查」，不许猜）：
  ① 有没有同类机制（手册·1 / 手册·2 / §二）？② 在哪个文件 file:line？
  ③ 消费点在哪（谁真的读它）？④ 有没有现成声明段（手册·2 §7）？⑤ 被测过没有（tests/）？

【证据要求】每条结论都要 file:line + 实跑输出；不接受「应该没问题 / 理论上」。

【分步要求】分 2~3 步，每步可独立停下验收；我先看方案，拍板后你才动第一步。
  每完成一小步：立刻落盘 + 单独 commit。

【验收 5 问】改动在哪（file:line）？跑了吗（原始输出）？对拍了吗（不启用 = 零变化）？
  全绿 + 工作树干净吗？有没有顺手改别的？
```

> 用法：把上面整段贴进给 AI 的第一条消息，再在末尾加一句「**本次任务**：<一句话>」。

### 12.8 AI 跑偏了怎么纠正（话术表）

| 现象 | 一句纠正话术 |
|---|---|
| **改太多**（顺手改了别的） | 「停。只保留 `<目标文件>` 的改动，其余 `git checkout -- <文件>` 还原；重新按**一单一事**做。」 |
| **自报不实**（说改好了、没证据） | 「给我 `file:line` + 实跑命令和**原始输出**；没有证据不算完成，别用『应该没问题』。」 |
| **把「故意的设计」当 bug 修** | 「先读《手册·3》§3『勿当 bug 修』；能给出文档 / 注释 / 变更记录判据的，**先还原再报告**，不许改。」 |
| **不落盘**（只在聊天里说） | 「每完成一小节**立刻写文件**并单独 commit；给我 `git status --porcelain` 看干净，不许攒到最后。」 |
| **说全绿但有红灯** | 「贴全量 `pytest tests/ -q -o addopts=""` 的**尾部原始输出**；红灯要么修，要么用基线对照证明不是你这次引入的。」 |
| **动了护栏测试 / 上传 / 碰主干** | 「立刻停下、还原护栏与无关改动；**不许改测试糊过去，不许 push、不许动 main**。」 |

> 通用句式：**「停 → 还原 → 给证据 → 只做我要求的那一步」**。它一开始辩解，就先要**原始输出**，再谈结论。

### 12.9 可打勾的验收清单（附命令）

| 勾 | 检查 | 命令 | 看到什么算通过 |
|---|---|---|---|
| [ ] | 全量测试 | `pytest tests/ -q -o addopts=""` | 看到 `0 failed`（本批基线 **9147 passed**） |
| [ ] | 工作树干净 | `git status --porcelain` | **无输出**（硬纪律） |
| [ ] | 架构门禁 | `python scripts/check_architecture.py` | 末行 `ARCH-OK` |
| [ ] | 内容包门禁 | `python scripts/check_m7_content.py --path content/<包>` | 无红项（**缺省只查一个包**） |
| [ ] | 字段元数据对拍 | `python scripts/compare_field_meta_migration.py` | 硬差异 `diff = 0` |
| [ ] | 换包通用性 | `python scripts/editor_verify_packs.py` | 12 包全 PASS |
| [ ] | 冒烟 | `python scripts/verify_veinborn_smoke.py` | PASS（SKIP 须写明原因） |
| [ ] | 全链门禁 | `python scripts/check_all.py`（发布前再 `python scripts/run_all_tests.py`） | 静态 + 架构 + 内容包 + 单测全过 |
| [ ] | 只改了该改的 | `git diff --stat <基线>..HEAD` | 文件清单 = 你要求的那几个（对照 §七 第 5 问） |

> 门禁选择口径见《手册·3》§③（`docs/审查/审计与方案/API手册_3_权责与勿当bug修.md:688`）：**按改动面选，宁多勿少**；护栏测试**不许动**（同处 `:703`）。

---

> **配套文档**：`docs/框架扩展开发手册.md`（框架能力与权责 · 稳定契约 · 勿当 bug 修）
> · `docs/编辑器使用说明.md` · `docs/玩家指令手册.md` · `docs/深度打造_实现说明.md`
> **本说明书随框架版本更新**；若与实现冲突，**以代码与门禁脚本为准**，并请把偏差登记回文档。
