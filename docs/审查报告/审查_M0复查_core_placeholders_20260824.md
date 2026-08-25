# 审查_M0复查_core_placeholders_20260824

> 审查者：QBot-TurnTellerRPG 代码审查 Agent（审查角色_初始化.md 固定人格）
> 场景：M0 复查·批3-路4「core 占位骨架核对」。**本环境无 bash 沙箱，全程仅 read/glob/grep 静态文件检索，未运行任何命令/脚本/验证；凡涉及"运行后会如何"的判断一律标注【静态推导】。**
> 审查对象（8 文件，标注「M1 实装 · 本里程碑仅骨架」）：`qbot_rpg/core/levelup.py`、`inventory.py`、`equipment.py`、`worldtime.py`、`core/__init__.py`、`world/__init__.py`、`commands/__init__.py`、`web/__init__.py`。
> 核对基准：占位合规四要件——① docstring 引用真实 ② 签名占位不写业务 ③ 零 NoneBot import（3a R1/R2）④ 不越界实现后续里程碑；维度 ①错误（占位泄露业务/越界）②缺漏（骨架签名与细化文档接口对齐）③幻觉（声称的实装依据/行号真实性/冒充已实现）。

## 一、审查对象

| 文件 | 行数 | 内容 | 对照细化 |
|---|---|---|---|
| `core/levelup.py` | 26 | LevelUpEngine：gain_exp / allocate_point，均 raise NotImplementedError | 细化_2c5a / 细化_3b §0.1/§1.1 / 规划_路3 B4 |
| `core/inventory.py` | 28 | InventoryEngine：add_item / remove_item / count，均 raise | 细化_4b / 细化_3b §1.1 |
| `core/equipment.py` | 34 | EquipmentEngine：equip / unequip / aggregate_bonus / equip_search，均 raise | 细化_3b §1.1 / 细化_2c2d / 2c3a-c / 细化_4a §1.2 / 细化_5a |
| `core/worldtime.py` | 28 | WorldTime：now / is_daytime / tick_forward，均 raise | 细化_2a4a / 细化_2a4c |
| `core/__init__.py` | 1 | 纯 docstring | 细化_3a §2.1 / 细化_3b |
| `world/__init__.py` | 1 | 纯 docstring | 细化_3a §2.1 |
| `commands/__init__.py` | 6 | 纯 docstring | 细化_3a §1.3 / D-02 / R1/R2 / 【规则】L35 |
| `web/__init__.py` | 1 | 纯 docstring | 细化_3a D-05 |

## 二、对照基准

- 细化_2a4a_时间引擎.md / 细化_2a4c_时间天气接口.md（worldtime 接口 IF01~IF12、S1、现实钟点层）
- 细化_2c5a_职业等级与SP.md、细化_3b_玩家属性三层.md（levelup 依据 + 行号 L136/L168/L174/L111-112/L127、TC-07）
- 细化_4b_物品与背包契约.md（inventory/equipment 数据结构 INV/INS/EQP/规则）
- 细化_4a_存储层契约.md §1.2（equipment 字段）、细化_5a_编辑器契约.md（equip_search 声称）
- 细化_3a_架构分层契约.md（R1/R2/D-02/D-03/D-05/§1.3/§2.1/§3.2）
- 实现层启动手册.md §三（里程碑计划 M0~M6）、实现层规划文档.md（路3 B4 / 模块树 / dummy_override）
- 兄弟复查报告：审查_M0复查_架构分层_20260824.md、审查_M0复查_data_types_20260824.md、审查_M0_coredata_20260818.md

## 三、结果表

| 级别 | 数量 | 说明 |
|---|---|---|
| 🔴 P0（必改） | 0 | 无占位泄露业务、无越界实现、无冒充已实现 |
| 🟡 P1（应改） | 1 | P1-1：worldtime 骨架签名与细化接口完全不对齐 |
| 🟡 P2（建议） | 6 | P2-1~P2-6（worldtime 2 项、equipment 1 项、levelup 1 项、core/__init__ 1 项、inventory 1 项建议） |

## 四、P1（应改）明细

### P1-1｜worldtime.py:21-27 骨架签名与细化_2a4a/2a4c 接口契约完全不对齐（维度②）
- **文件:行号**：`core/worldtime.py:21-27`（`now() -> str`、`is_daytime(tick=None) -> bool`、`tick_forward(amount, units="min") -> int`）；docstring L3-5 声称以 细化_2a4a/2a4c 为 M1 实装依据。
- **对照**：细化_2a4c §1.1 定义 worldtime 公开接口 **IF01~IF12**（`is_enabled / season_now / period_now / weather_now / map_pool / cycle_tick / time_remaining / map_weather / check_changes / maybe_broadcast / load_time_state / save_time_state / recalc_on_config_change`，L58-69）；骨架 3 个方法**无一命中**。现实钟点层文档化接口亦为 `spawn_available(row, now)`（2a4c S1）与 `today_of(last_key)`（规划 A3），同样不含这三个方法。且 2a4c L54 明示「`now` 一律为 UTC+8 **秒级时间戳参数**（缺省=当前）」——骨架把 `now` 做成返回 `str` 的方法，语义方向相反。
- **实际（静态推导）**：占位未按细化接口预留；若保留，M1/M3 实装需整组重写签名，骨架"接口占位"目的落空；测试侧 `tests/` 无任何文件引用这三个方法（仅 data 类型），即签名无既有锚点。
- **应有**：骨架应预留 IF01~IF12（至少 12 个占位签名），或在 docstring 显式注明「M1/M3 落细化_2a4c IF01~IF12，当前 3 个方法为临时占位」。
- **修复建议**：按细化_2a4c §1.1 表逐项生成 `def is_enabled(...) / season_now(...) / ... / recalc_on_config_change(...)` 占位；删除/改名 `now`（与接口 `now` 参数语义冲突）；`tick_forward` 如确需保留为测试拨钟工具，标注【工程补白】并说明其不违背 2a4a「零定时器」约束的用途。

## 五、P2（建议）明细

### P2-1｜worldtime.py:4「dummy_override 时间拨动落 data/world_state.py」为无依据表述（维度③）
- **实际**：全仓文档中 `dummy_override` 的唯一语义 = **木桩（训练假人）配置覆盖**（细化_3a §3.2 L215、细化_4a §1.2、细化_1e L188、实现层规划 L357/3363），与时间拨动无关；「时间拨动/快进/推进」概念全仓 **0 命中**，且 2a4a 明文「零定时器、不存历史、不跑定时器」（L61/L113）。`data/world_state.py` 存在且存 `dummy_override` 属实（3a §3.2 引【框架】L228），但那是木桩配置，不是时间引擎的拨钟机制。
- **修复建议**：删除「dummy_override 时间拨动」表述；如需预留测试拨钟，改用未占用名（如 `debug_set_now`）并标【工程补白】。

### P2-2｜worldtime.py:1 「M1 实装」里程碑标注不符 + 描述不准确（维度③）
- **实际**：实现层启动手册 §三（L39）里程碑 **M3 = 地图副本时间（2a 系 9 份，含 2a4a/2a4c）**；实现层规划文档 L3169 亦注明 worldtime「**后续路挂接**」，不在路3 M1 范围。本文件标「M1 实装」与两处文档不一致。另 docstring L3「白天/夜晚轮转、时刻换算」是对 2a4a「季节/时段/天气三周期（含五时段 dawn/noon/dusk/night/midnight）」的不准确简化，不存在「白天/夜晚」二元轮转设计。
- **修复建议**：标注改为「M3 实装 · 本里程碑（M0）仅骨架」；描述改为「三周期（季节/时段/天气）整除懒计算 + 变化检测/懒广播 + 现实钟点层」。

### P2-3｜equipment.py:32-33 equip_search「编辑器器物检索（细化_5a 编辑器接管，M-y 实装）」自创术语/里程碑（维度③ + 架构边界）
- **实际**：①「器物」一词全仓 md **0 命中**，细化_5a 中编辑器的相关能力为通用「搜索框/分页 `q=`」（P-08 L82、C-05 L98、API L176），无「器物检索」专名；②「M-y」非既有里程碑——启动手册里程碑为 M0~M6，本仓库亦无任何文档使用「M-y」（全仓 0 命中）；③ 按 3a R6/§1.5（放错层判定），编辑器检索属 web 层职责（web → content/core/storage），在 core 装备引擎预留一个「编辑器接管」的签名，架构归属模糊。
- **修复建议**：改为「编辑器装备检索（web 层接管，细化_5a P-08/C-05 搜索框语义；后续里程碑 M5/M6 实装）」，或直接删除该预留签名并在 web 侧登记。

### P2-4｜levelup.py:3 docstring 将 2c5a（职业熟练等级）引为本引擎依据，与角色成长引擎语义含混（维度③）
- **实际**：本引擎类 docstring 为「等级/经验/自由加点引擎」——自由加点/换职业不重算属**角色等级**白值层（细化_3b §0.1/§1.1、规划_路3 B4）；而 细化_2c5a 是**职业熟练度等级（proficiency）**，两套独立尺子（2c5a LVL-04 双尺独立）。docstring「M1 实装依据：细化_2c5a / 细化_3b §0.1」把两条等级体系并列为依据，`gain_exp` 的归属（角色经验 or 熟练经验）未界定，M1 实现时易混尺。
- **修复建议**：docstring 注明「角色等级成长（规划_路3 B4）为引擎主责；职业熟练经验归 2c5a 接口，另行承接」；或改引 B4 依据为第一来源。

### P2-5｜core/__init__.py:1 模块清单与引用依据不严格对应（维度③ 低）
- **实际**：职责句列「battle/damage/levelup/inventory/equipment/worldtime/**formula_engine** + **属性三层管线**（细化_3a §2.1 / 细化_3b）」。细化_3a §2.1 目录树仅列前六个模块（L118-125，无 formula_engine）；`formula_engine` 实为 M1 模块、依据为细化_1a/1b（审查_M1_formula_定稿对照 已核）；「属性三层管线」= player_attributes 属 3b 正确。引用集与所列模块集存在一处不对应。
- **修复建议**：补注「formula_engine 依据细化_1a/1b（M1 扩展）」或把 formula_engine 从 §2.1 依据句中拆出。

### P2-6｜inventory.py:21-27 签名未体现 4b row_key 聚合键语义（维度② 前瞻建议）
- **实际**：细化_4b INV-R01/INV-01 定义背包行为 **row_key = item_id + 实例键 + 品质 + 绑定态** 聚合键（堆叠合并/幂等定位），实例行按 instance_id 定位；骨架 `remove_item(player, item_id, count)` 与 `count(player, item_id)` 以 `item_id` 为键，无法区分同 item_id 的实例行（多件铁剑）或不同绑定/品质行。4b 未定义方法级接口，签名属合理工程补白、无文档冲突，但 M1 实现前建议对齐聚合键语义（改 `row_key`/`instance_id` 定位）。
- **修复建议**：占位阶段可将 `remove_item/count` 的定位参数名标注为 `row_key: str`，并在 docstring 注明「对齐 4b INV-01 row_key」。

## 六、维度确认（无问题项亦明确确认）

### ① 错误（占位泄露业务实现 / 越界实现后续里程碑）——✅ 零违规
- 四个引擎文件全部方法体为 `raise NotImplementedError(_NOT_IMPL_MSG)`，无任何业务假实现、无返回值伪造、无常量/公式/配置预埋；`__all__`/类 docstring 均未冒充已实现。
- 四个 `__init__.py` 为纯 docstring（1~6 行），零代码、零 import、零越界。
- equip_search 属"预留后续里程碑签名"而非实现，不构成越界（问题仅在其标注真实性，见 P2-3）。

### ② 缺漏（骨架签名与细化文档接口对齐）——✅ levelup/inventory/equipment 无冲突；⚠️ worldtime 不对齐（P1-1）
- levelup：无文档定义方法级接口；gain_exp/allocate_point 与路3 B4 契约（经验入账/自由加点）语义吻合，占位合理。
- inventory：4b 为数据结构+规则层，无方法级接口；add_item/remove_item/count 与 INV/INS 结构无冲突（聚合键细节见 P2-6）。
- equipment：equip/unequip/aggregate_bonus 与 4b §3（EQP-R01~R08：穿戴/脱卸/加成聚合）语义吻合；equip_search 为预留（P2-3）。
- worldtime：签名与 2a4c IF01~IF12 **完全不对齐**（P1-1）。

### ③ 幻觉（声称的实装依据 / 行号真实性 / 冒充已实现）——✅ 大部分真实，2 处待修（P2-1/P2-3），1 处依据语义含混（P2-4）
- **细化文件引用真实性**：全部真实存在——2c5a/3b/4b/2a4a/2a4c/2c2d/2c3a/2c3b/2c3c/4a/5a/3a（glob 逐文件命中）。
- **行号真实性**：levelup「§0.1 白值定义 / §1.1 L136/L168/L174 / 换职业不重算 L174」经细化_3b §0.1（L18）与 §1.1（L63）核对属实；equipment「L111-112/L127 装备词条承载」经 3b §1.1（L64）核对属实；「细化_3b TC-07 卸装即时重算」= 3b §6.1 TC-07（L337）属实；「细化_4a §1.2 equipment{item_id,name,slot_level,locked,gems}」与 4a §1.2（L86）及 data/player.py EquipmentSlot（L65-69）**逐字段匹配**；「WorldState 唯一落点 data/world_state.py（3a D-03）」= 3a §3.2（L215）属实；commands「M4 起装配 / 拉起 Router/Parsers/Errors/Sender + web 子进程 / 【规则】L35 / 3a R1/R2 / D-02」= 3a D-02（L43）、§1.3（L76-84）、R1/R2（L57-58）、启动手册 M4 指令系统 全部属实；world「3a §2.1 地图/怪物池/野图 BOSS/全体限购/刷新补刷+会话互斥」= 3a §2.1 world 树（L126-129）属实；web「D-05 读写 content/core 模拟试玩/storage 运营页」= 3a D-05（L46）+ §1.4（L91）属实。
- **待修项**：worldtime「dummy_override 时间拨动」（P2-1，无依据）；equip_search「器物 / M-y」（P2-3，自创术语/里程碑）；levelup「2c5a 依据语义含混」（P2-4）。

### 3a R1/R2 零 NoneBot import——✅ 合规
- 8 文件 import 仅 `__future__` / `typing`（Any/Dict/Optional），无任何 `nonebot` 字样（含 `from nonebot` / 动态 import）；`core/world/commands/web` 四 `__init__.py` 为纯 docstring。commands/__init__ 提及 nonebot 均为说明性文字（「零 nonebot import」「唯一 NoneBot 接触点」），非 import。R1/R2 静态成立。
- **占位纪律**：无一处把占位写成"已实现"；`_NOT_IMPL_MSG` 均标注「M1 实装」+ 细化依据，格式统一。

## 七、结论

**可合入（无 P0 拦截）**。本批 8 个占位文件零业务泄露、零越界实现、零 NoneBot import（R1/R2），docstring 引用与行号绝大多数真实可回查（levelup/inventory/equipment 的细化依据、EquipmentSlot 字段、D-02/D-05、里程碑 M4/M0 标注均核对无误）。
**须在实装前修复的 P1（1 项）**：worldtime 骨架签名与细化_2a4c IF01~IF12 接口完全不对齐（P1-1），应按接口预留 12 个占位签名并消除 `now` 语义冲突。
**建议随文修正的 P2（6 项）**：worldtime「dummy_override 时间拨动」无依据表述（P2-1）、「M1 实装」应改 M3 且描述不准确（P2-2）；equip_search「器物/M-y」自创术语（P2-3）；levelup 2c5a 依据双尺含混（P2-4）；core/__init__ formula_engine 引用不对应（P2-5）；inventory 聚合键前瞻建议（P2-6）。
