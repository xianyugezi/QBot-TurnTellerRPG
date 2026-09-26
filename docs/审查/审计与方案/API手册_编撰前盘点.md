# 框架扩展开发手册 · 编撰前盘点

> **性质**：只读盘点（编撰铺底）。本文件不改动仓库任何文件。
> **仓库**：`/root/QBot-TurnTellerRPG`（HEAD = `d86d9dd`，2026-09-20）
> **服务对象**：① 外部扩展开发者（要照着写包/写扩展）；② 未来框架维护者（改框架前先看，避免把"故意设计"当 bug 修）。
> **上游依据**：`docs/深度打造_决策记录.md:1565-1571`（§十六「框架扩展开发手册（API 总结）」三路编撰计划，登记于 HEAD 提交）。
> **阅读约定**：所有 `file:line` 均指 HEAD 状态；"唯一源"= 该信息只有一处定义（改它必须改这里）；"别名/兼容键"= 同一语义有多个可接受写法。

## 目录

- [§0 盘点总览](#0-盘点总览)
- [§1 常量](#1-常量)
- [§2 变量与数据结构](#2-变量与数据结构)
- [§3 事件](#3-事件)
- [§4 扩展点](#4-扩展点)
- [§5 权责边界与门禁](#5-权责边界与门禁)
- [§6 缺口标注](#6-缺口标注)
- [§7 「形似 bug 实为设计」初选清单](#7-形似-bug-实为设计初选清单)
- [§8 三路编撰建议](#8-三路编撰建议)

---

## §0 盘点总览

**一句话结论**：五类素材**都够写手册**，且大部分有明确的"唯一源"；真正的风险不在"没素材"，而在**三类"看起来像唯一源其实不是"的地方**——① 声明了但没接线的扩展位（`EVENT_POINTS` 5 个无派发点）；② 同一语义两个落点（`settings.json` 双通道、`slot_defs` vs `slots.json`、`module_labels` 双声明）；③ 注释与实现不同步（特效轴 docstring 15 vs 实际 17）。这三类正是手册要用"稳定契约章节 + 明确标注"的方法论去固化的对象（详见 §6）。

| 类别 | 规模 | 主唯一源文件（file:line） | 备注 |
|---|---|---|---|
| **§1 常量** | 4 族 + 约 30 个顶层常量 / 17 特效轴 / 36 模块目录条目 / 3 推荐组合 | qbot_rpg/data/gear_stats.py（1206 行）；qbot_rpg/data/event_points.py:25；qbot_rpg/content/module_catalog.py:68；module_presets.py:58 | 键族/范围/默认值总体唯一源清晰；`settings.*` 可覆盖的项已逐条标注 |
| **§2 变量/数据结构** | 15 个对象（含 `Player` 23 字段 / `ItemInstance` 20 / `EquipmentSlot` 6 / `ctx` **约 170 键**） | qbot_rpg/data/player.py:79；data/item.py:40；data/battle.py:33；content/registry.py:44；assembly/context.py:1256 | 契约 dataclass 与运行期 dict **双轨**；`ctx` 四段散落、无单一源（最大缺口） |
| **§3 事件** | **2 套体系** / `EVENT_POINTS` **17 点**（11 点有派发点） | qbot_rpg/data/event_points.py:25；派发 core/battle.py:2038 + core/effects.py:2040 | `death` vs `on_kill`、`status_gain` vs `mark_gain` 易混对已列；5 点属"二期" |
| **§4 扩展点** | **E1 + E2（render/templates）+ E3**；包声明段 **93 条** | E1 assembly/pack_ext.py:481；E2 assembly/pack_render.py:319；E3 scripts/run_pack_tests.py:168 / run_pack_build.py:39；稳定面 qbot_rpg/ext_api.py（`EXT_API_VERSION="1"`:59） | manifest 9 + settings 41 + 模块 json 30 + field_meta.json 12 + commands.json 1 |
| **§5 权责边界/门禁** | 10 个子目录（9 框架 + 外层 bridge）+ **28 条门禁** | 权责 web/editor_ops.py:671；架构门禁 scripts/check_architecture.py:319；字段迁移 scripts/compare_field_meta_migration.py:320；最硬红线 content/loader.py:239 → validator.py | 三层权责：框架 `qbot_rpg/**` / 内容包 `content/<包>/**` JSON / 包自持代码 `ext/`+`tests/`+`scripts/`（双闸默认关） |

**盘点的"最大三个发现"**（编撰时优先处理）：
1. **`EVENT_POINTS` 声明 ≠ 可用**：17 个时点里只有 11 个在生产代码有派发点；`mark_gain`/`mark_lose`/`on_attack`/`on_hit`/`on_skill` 是"二期"（`记录.md:842`），`turn_end` 是故意不派发（`docs/深度打造_实现说明.md:735`）。手册必须给一张"**已接线 / 未接线 / 故意不派发**"三态表，否则外部开发者会照枚举写出永不触发的效果。
2. **`data/affinity_keys.py` 没有 aliases 表**（用户样例②的假设不成立）：真正的别名归并在 `gear_stats.py:584`（`EFFECT_LEGACY_ALIASES`）与 `core/condition_engine.py:96-120`。相性文件的唯一源是"池类型/反应类型/载荷键"三组常量。
3. **包声明的"入口双通道"**：`settings.json` 既能被 loader 校验（在 `manifest.modules` 里时），也能被 `qbot_rpg_bridge/assemble.py:89` 无条件直读——"声明了才生效"这条规则有例外，手册须写明。

---

## §1 常量

> 口径：**唯一源** = 该常量只有一处定义、其它模块必须 import 它（不得写死字面量）。
> **可被包覆盖** = 内容包通过 `settings.json` 某段能改；"引擎侧只读声明、不写死"是本框架的通用设计口径。

### 1.1 装备键族（唯一源：`qbot_rpg/data/gear_stats.py`）

| 常量 | file:line | 数量 | 内容 | 唯一源 | 可被包覆盖 | 备注 |
|---|---|---|---|---|---|---|
| `GEAR_FLAT_KEYS` | qbot_rpg/data/gear_stats.py:175 | 13 | atk/def/dfn/hp/mp/str/con/agi/foc/spr/lck/spd/mag | ✅ | ❌（键空间固定） | `def` 与 `dfn` **等价双兼容**（同一中文"防御"，见 `GEAR_LABELS_ZH:518-519`）——这是故意的别名，不是冗余 bug |
| `GEAR_PCT_KEYS` | qbot_rpg/data/gear_stats.py:180 | 8 | atk_pct/dfn_pct/hp_pct/mp_pct/heal_amp_pct/debuff_chance_pct/buff_chance_pct/weakness_dmg_pct | ✅ | ❌ | 后 4 键（批43 追加强化词条）**已被特效轴归并**：`heal_amp_pct`→`healing_done_pct`、`weakness_dmg_pct`→`damage_dealt_pct`、`debuff/buff_chance_pct`→`status_chance_pct`（见 §1.2 legacy_alias）——旧键**保留**（双轨），不是遗留 bug |
| `GEAR_COMBAT_KEYS` | qbot_rpg/data/gear_stats.py:186 | 10 | crit/earplug/super_crit_lv/elem_crit_lv/absorb_hp/immune_dmg/pierce_val/pierce_pct/mag_pierce_val/mag_pierce_pct | ✅ | ❌ | 战斗直读键（经 `COMBAT_TO_COMBATANT:502` 桥到 combatant） |
| `GEAR_COMBAT_PCT_KEYS` | qbot_rpg/data/gear_stats.py:192 | 4 | absorb_hp/immune_dmg/pierce_pct/mag_pierce_pct | ✅ | ❌ | COMBAT 键内部再分"显示口径"（仅编辑器提示用） |
| `GEAR_COMBAT_VALUE_KEYS` | qbot_rpg/data/gear_stats.py:195 | 2 | pierce_val/mag_pierce_val | ✅ | ❌ | 穿值不封顶（引擎按 `max(0, def-val)`） |
| `GEAR_PLACEHOLDER_KEYS` | qbot_rpg/data/gear_stats.py:198 | 1 | `cooldown_reduction_pct` | ✅ | ❌ | **占位键 → 批53 起作为 `cooldown_pct` 的兼容别名"激活"**；`route_bonus_into` 仍显式跳过，换算只在 `route_legacy_aliases_into_flat` 一处（防双计）。典型的"形似死代码，实为兼容设计" |
| `GEAR_EFFECT_KEYS` | qbot_rpg/data/gear_stats.py:461 | 17 | 由 `EFFECT_AXIS_SPECS` 派生 | ✅（派生） | ❌ | **grep 可枚举**的轴键名元组；不可手改，改 `EFFECT_AXIS_SPECS` |
| `GEAR_NUMERIC_KEYS` | qbot_rpg/data/gear_stats.py:494 | 48 | FLAT+PCT+COMBAT+EFFECT 拼接 | ✅（派生） | ❌ | 实例化转换/展示/编辑器遍历用 |
| `GEAR_DISPLAY_KEYS` | qbot_rpg/data/gear_stats.py:499 | 49 | NUMERIC + PLACEHOLDER | ✅（派生） | ❌ | 占位键要能被提取/展示，但不接引擎 |
| `COMBAT_TO_COMBATANT` | qbot_rpg/data/gear_stats.py:502 | 10 | (聚合键, combatant 键, 封顶) 三元组 | ✅ | ❌ | 战斗桥非特效部分；封顶写死在此（如 absorb_hp=100） |
| `GEAR_LABELS_ZH` | qbot_rpg/data/gear_stats.py:517 | — | 键→中文 label | ✅ | ❌ | 展示/编辑器共用 |
| `GEAR_HELP_ZH` | qbot_rpg/data/gear_stats.py:536 | — | 键→帮助文案 | ✅ | ❌ | 编辑器字段提示 |
| `EFFECT_LEGACY_ALIASES` | qbot_rpg/data/gear_stats.py:584 | 6 | 旧键→(新轴, 系数) | ✅ | ❌ | **别名归并唯一源**（`DEFAULT_EFFECT_AXES` 等多处派生自它） |
| `PCT_SUFFIX` | qbot_rpg/data/gear_stats.py:172 | — | `"_pct"` | ✅ | ❌ | 聚合端按此后缀拆层 |
| `PANEL_AXIS_STEMS` | qbot_rpg/data/gear_stats.py:205 | 3 | atk/dfn/hp | ✅ | ❌ | **落在 data 层是为了让 content 校验器能拦"特效轴键名撞面板轴"而不反向依赖 core**；`core/panel_budget.PANEL_AXIS_KEYS:97` 由它派生 |

### 1.2 特效轴（EFFECT_AXIS_SPECS）—— 轴清单与范围

| 项 | file:line | 数量 | 唯一源 | 可被包覆盖 | 备注 |
|---|---|---|---|---|---|
| `EFFECT_AXIS_SPECS` | qbot_rpg/data/gear_stats.py:230-447 | **17 轴**（P0 8 + P1 9） | ✅ | `min/max` 可由 `settings.effect_axes` 覆盖（`EFFECT_AXES_KEY:477`） | 每轴字段：`axis/doc_id/priority/min/max/default/stack/display/legacy_alias/consumer/consumer_note`（+可选 `bridge/scope`） |
| `EFFECT_TO_COMBATANT` | qbot_rpg/data/gear_stats.py:470 | 16 | ✅（派生） | ❌ | `bridge="settlement"` 的轴（`reward_mult_pct`）**不进战斗桥** |
| `DEPRECATED_EFFECT_AXES` | qbot_rpg/data/gear_stats.py:452 | 1 | ✅ | ❌ | `action_recovery_pct`→`action_speed_pct`；校验器**黄提示不硬拦**（不得登记/不得实现） |
| `EFFECT_CONSUMER_PENDING` | qbot_rpg/data/gear_stats.py:211 | — | ✅ | ❌ | **待接哨兵**"（消费点待接）"：有方向但无唯一消费点时必须如实写哨兵，**禁止伪造成唯一点，也禁止留空** |

**17 轴全表**（键 / 优先级 / 范围 / 消费点）：

| # | axis | 优先级 | min–max | 消费点(consumer) | 接线批次 | file:line |
|---|---|---|---|---|---|---|
| 1 | healing_received_pct | P0 | -200 ~ 300 | effects.heal_apply | **待接** | gear_stats.py:232 |
| 2 | healing_done_pct | P0 | -100 ~ 300 | effects.heal_apply | 归并 heal_amp_pct，待接 | :243 |
| 3 | damage_taken_pct | P0 | -100 ~ 300 | battle.damage_taken_mult | 归并 immune_dmg | :253 |
| 4 | damage_dealt_pct | P0 | -100 ~ 1000 | battle.damage_dealt_mult | 批70 已接线 | :266 |
| 5 | cooldown_pct | P0 | -80 ~ 200 | battle.skill_cooldown | 批53 | :280 |
| 6 | status_chance_pct | P0 | -100 ~ 不限 | effects.status_apply_chance | 批53 | :292 |
| 7 | stack_gain_pct | P0 | -100 ~ 不限 | effects.stack_gain | 批53 | :305 |
| 8 | stack_cap_delta | P0 | 不限 ~ 不限 | effects.stack_cap | 批53（marks 半边未接） | :317 |
| 9 | status_duration_pct | P1 | -80 ~ 300 | effects.apply_status_duration | 批70 | :329 |
| 10 | status_duration_taken_pct | P1 | -100 ~ 300 | effects.apply_status_duration | 批70 | :340 |
| 11 | status_resist_pct | P1 | -100 ~ 不限 | effects.resist_roll | 批53 | :351 |
| 12 | action_bar_shift | P1 | 不限 ~ 不限 | ctb_scheduler.action_bar_shift | 批53 | :362 |
| 13 | resource_cost_pct | P1 | -100 ~ 200 | resource_axis.pay_cost | 批53 | :374 |
| 14 | resource_gain_pct | P1 | -100 ~ 不限 | resource_axis.apply_gain | 批53 | :386 |
| 15 | crit_damage_pct | P1 | -100 ~ 300 | damage.crit_multiplier | 批53 | :396 |
| 16 | action_speed_pct | P1 | -80 ~ 400 | ctb.effective_speed | 批56 | :408 |
| 17 | reward_mult_pct | P1 | 0 ~ 400 | **`EFFECT_CONSUMER_PENDING`** | **未接**（D5 登记） | :424 |

> 缺口：`EFFECT_AXIS_SPECS` 的 docstring 说"登记范围 = 15 条（P0 8 + P1 7）"，实际现有 **17 条（P0 8 + P1 9）**——差额来自后续批次追加（`action_speed_pct` 等）与批59 的 `reward_mult_pct`，**注释未随追加同步**（详见 §6）。

### 1.3 枚举 / 时点

| 常量 | file:line | 数量 | 唯一源 | 可被包覆盖 | 备注 |
|---|---|---|---|---|---|
| `EVENT_POINTS` | qbot_rpg/data/event_points.py:25 | **17** | ✅（`core/event_dispatcher.py:69` **原样再导出**，兼容旧 import 路径） | ❌（值域固定；effects/status 的 `trigger` 从中取值） | 16 个既有 + `on_kill`（插在 `on_skill` 与 `season_change` 之间，**前 16 位保序**避免既有断言位移） |
| `STATUS_EVENT_POINTS` | qbot_rpg/data/event_points.py:38 | 2 | ✅ | ❌ | status_gain/status_lose |
| `FRAMEWORK_MODULE_CATALOG` | qbot_rpg/content/module_catalog.py:68 | **36** 条目 | ✅ | ❌（框架能力全集，包不能改目录；一号原则：框架设计了但未实装的也让作者看得见） | 条目形状 `ModuleCatalogEntry`（module/label/purpose/entry_type/requires/implemented/settings_section/overlap_with/overlap_note，见 :19-52） |
| `CATALOG_BY_MODULE` | qbot_rpg/content/module_catalog.py:154 | 36 | ✅（派生） | ❌ | module→entry 索引 |
| `FRAMEWORK_MODULE_PRESETS` | qbot_rpg/content/module_presets.py:58 | **3**（basic_rpg / life_adventure / story_exploration） | ✅ | ✅ 同 id 整体覆盖；可追加；`manifest.json.module_presets_disable` 可关闭（:27-31） | 生效 = 框架默认 ∪ 包声明 |
| `POOL_KINDS` | qbot_rpg/data/affinity_keys.py:37 | 3 | ✅ | ❌ | common/exclusive/linkage |
| `REACTION_KINDS` | qbot_rpg/data/affinity_keys.py:43 | 3 | ✅ | ❌ | conflict/amplify/reverse |
| `AFFINITY_KEYS` | qbot_rpg/data/affinity_keys.py:46 | 6 | ✅ | ❌ | 相性键 |
| `ENTRY_PAYLOAD_KEYS` | qbot_rpg/data/affinity_keys.py:62 | 4 | ✅ | ❌ | stat/set_affix/effect_ref/enhance_affix |
| `AFFINITY_EFFECT_QUALITY_CAP` | qbot_rpg/data/affinity_keys.py:73 | — | ✅ | ❌ | `quality_cap_delta` |
| `RUNE_TIERS` | qbot_rpg/data/runes.py:41 | (1,2,3) | ✅ | ❌ | `MIN_RUNE_TIER:39` / `MAX_RUNE_TIER:40` |
| `RUNE_UPGRADE_COUNT` | qbot_rpg/data/runes.py:44 | 3 | ✅ | ❌ | 每阶强化次数 |
| `DEFAULT_SOCKET_COUNT` | qbot_rpg/data/runes.py:50 | 3 | ✅ | 孔位数组随 `slots` 定义 | 镶嵌状态挂 `ItemInstance.uid` |
| `RUNES_STATE_KEY` | qbot_rpg/data/runes.py:47 | — | ✅ | ❌ | `player.persistent_state.rune_sockets` |
| `QUALITY_KEYS` | qbot_rpg/core/quality.py:80 | 4 | ✅ | 档位边界可经 settings 覆盖（`_tiers` 来自 raw） | common/uncommon/rare/legendary |
| `DEFAULT_QUALITY_TIERS` | qbot_rpg/core/quality.py:56 | 4 | ✅ | ✅ | {common:(0,39), uncommon:(40,59), rare:(60,79), legendary:(80,100)} |
| `DEFAULT_QUALITY_COEF` | qbot_rpg/core/quality.py:64 | 4 | ✅ | ✅ | 0.8 / 1.0 / 1.2 / 1.5 |
| `DEFAULT_TIER_LABELS` | qbot_rpg/core/quality.py:72 | — | ✅ | — | 档位中文标签 |
| `ABSOLUTE_QUALITY_MAX` | qbot_rpg/core/quality.py:84 | 100 | ✅ | ❌（硬上限） | 品质绝对上限，"故意写死" |

### 1.4 阈值 / 默认值表

| 常量 | file:line | 唯一源 | 可被包覆盖（段名） | 备注 |
|---|---|---|---|---|
| `PANEL_BUDGET_KEY` | qbot_rpg/core/panel_budget.py:90 | ✅ | `settings.panel_budget` | |
| `DEFAULT_PANEL_BUDGET` | qbot_rpg/core/panel_budget.py:102 | ✅ | ✅（`panel_budget.py:148-152` 归一） | {white:7, equip:8, buff:5, equip_stat_mult:1} |
| `MONSTER_SCALING_KEY` | qbot_rpg/core/panel_budget.py:91 | ✅ | `settings.monster_scaling` | 消费处 `assembly/context.py:1874` |
| `DEFAULT_MONSTER_SCALING` | qbot_rpg/core/panel_budget.py:109 | ✅ | ✅（:159-163 归一，各值下钳 0） | hp_mult/atk_mult/def_factor/def_k/effect_hp_mult/effect_atk_mult |
| `DEFAULT_DEF_K` | qbot_rpg/core/panel_budget.py:100 | ✅ | ✅（经 monster_scaling.def_k） | 100.0 |
| `DEFAULT_DEEP_CRAFT_RULES` | qbot_rpg/content/deep_craft_settings.py:110 | ✅ | `settings.deep_craft.craft_rules` | 用户说的 `craft_rules` = 此默认表 + `DEEP_CRAFT_RULE_FIELDS:155`（子字段元数据）；消费/校验 `core/deep_craft.py:733,861`、`content/validator.py:2647` |
| `DEFAULT_TEMPER` | qbot_rpg/data/temper_stats.py:70 | ✅ | `settings.forge.temper`（经 `normalize_temper_config`） | 14 键：enabled/cap_per_level/total_cap/total_cap_by_level/per_stat_cap_ratio/per_stat_cap/allowed_stats/value_type/value_per_point/cost_per_point/cost_growth/stat_weight/points_per_action/default_level/reset_allowed |
| `DEFAULT_ESSENCE_RATE` | qbot_rpg/data/temper_stats.py:106 | ✅ | `settings.forge.essence_rate` | 出参同构；`content/forge_settings.py:81` 落地 |
| `TEMPER_VALUE_TYPES` / `TEMPER_ROUNDINGS` | qbot_rpg/data/temper_stats.py:55 / :58 | ✅ | ❌（值域固定） | flat/pct；floor/round/ceil |
| `ESSENCE_V_BASES` / `ESSENCE_SCOPES` | qbot_rpg/data/temper_stats.py:62 / :65 | ✅ | ❌ | node_materials/item_price/fixed/level_scaled；crafted_equipment/all_equipment |
| `EFFECT_BUDGET_KEY` | qbot_rpg/data/gear_stats.py:858 | ✅ | `settings.effect_budget` | |
| `DEFAULT_EFFECT_BUDGET` | qbot_rpg/data/gear_stats.py:894 | ✅ | ✅（`normalize_effect_budget`，:921-946） | enabled/aggregate/cap_equiv_pct/tier_mult/gate_mode/unknown_axis/report_effective_share/axis_weights |
| `EFFECT_AGGREGATES` | qbot_rpg/data/gear_stats.py:861 | ✅ | ❌ | geometric/product/max |
| `EFFECT_GATE_MODES` | qbot_rpg/data/gear_stats.py:863 | ✅ | ❌ | off/warn/red |
| `EFFECT_UNKNOWN_MODES` | qbot_rpg/data/gear_stats.py:865 | ✅ | ❌ | ignore/warn/red |
| `EFFECT_AXIS_WEIGHTS` | qbot_rpg/data/gear_stats.py:873 | ✅ | ✅（axis_weights） | |
| `DEFAULT_EFFECT_AXES` | qbot_rpg/data/gear_stats.py:593 | ✅ | — | 旧特效轴表（`EFFECT_LEGACY_ALIASES` 的目标之一） |
| `OVERHEAL_KEY` / `OVERHEAL_MODES` / `OVERHEAL_MODE_RESERVED` / `DEFAULT_OVERHEAL` | qbot_rpg/data/gear_stats.py:1122 / :1125 / :1129 / :1136 | ✅ | `settings.overheal` | keep/discard；`overheal_cap` |
| `MODE_*` / `CRAFT_PATHS` | qbot_rpg/core/craft_paths.py:72-91 | ✅ | `settings.*.mode` | full/simple/off；synthesis/alchemy/deep_alchemy/forge 四条路径 |
| `REJECT_*` 拒绝码 | qbot_rpg/core/deep_craft.py:85-94 | ✅ | ❌ | 蓝图拒绝原因码值域 |

---

## §2 变量与数据结构

> 本节由只读盘点子任务产出（字段级清单）。行号已抽样核验（Player/ItemInstance/Registry/make_context 等）。

### 变量与数据结构字段级清单（《框架扩展开发手册》素材 · part2）

> 盘点方式：只读。所有 `file:line` 均经 `grep -n` / 逐行读源确认；未确认者不写。
> 仓库根：`/root/QBot-TurnTellerRPG`。本文不含实现代码，只做字段登记。
> 列含义：**必填?** = 构造时无默认值即必填；dict 形态记「注入态」。**默认** = dataclass 默认值 / 注入兜底值。

---

#### 0. 总览

| 对象 | 定义 file:line | 字段数 | 唯一源? | 备注 |
|---|---|---|---|---|
| `Player` | `qbot_rpg/data/player.py:79`（`@dataclass` :78） | 23 | 是（dataclass 唯一声明；序列化另有 codec） | frozen；存档列名与字段名不同名（`qid→player_qid`、`name→nickname`、`attributes→stats`、`job_id→persistent_state["job_id"]`） |
| `PlayerAttributes` | `qbot_rpg/data/player.py:23`（`@dataclass` :22） | 4 | 是 | 四子层：base / bonus{flat,pct} / temp{pct,flat} / cond |
| `EquipmentSlot` | `qbot_rpg/data/player.py:57`（`@dataclass` :56） | 6 | 是 | frozen；`uid` 回指 `ItemInstance.uid` |
| `ItemInstance` | `qbot_rpg/data/item.py:40`（`@dataclass` :39） | 20 | dataclass 是唯一声明；读写 codec 各一处 | `uid` 为空时 `__post_init__` 自动补发（item.py:95） |
| `CombatantSnapshot` | `qbot_rpg/data/battle.py:33`（`@dataclass` :32） | 7 | 契约 spec 类型，**不是运行期形态** | 运行期 combatant 为 dict（见 §3） |
| `BattleSnapshot` | `qbot_rpg/data/battle.py:46`（`@dataclass` :45） | 13 | 契约 spec 类型，**与运行期 dict 快照结构不同** | 文件头 data/battle.py:13-20 已登记双轨 |
| combatant 运行期 dict | `qbot_rpg/core/battle.py:317`（默认键）+ `:2318`（归一）+ launch/pvp 构造 | 基础 17 + 语义键 + 动态透传 + 运行期追加 | **否，多源**（见 §3 与 §8） | 公式/效果直读的活对象 |
| `StatusInstance` | `qbot_rpg/data/status.py:33`（`@dataclass` :32） | 7 | 契约 spec 类型，**不是运行期形态** | 运行期状态实例为 dict（见 §6） |
| `Duration` | `qbot_rpg/data/status.py:25`（`@dataclass` :24） | 2 | 契约 spec 类型 | turns / charges 双形 |
| 状态实例（effects 运行期 dict） | `qbot_rpg/core/effects.py:749` | 14 | codec 唯一构造源 `_new_instance` | 另有 DOT 池实例（shape 不同，见 §6.3） |
| 印记实例（marks 运行期 dict） | `qbot_rpg/core/marks.py:53`（键元组）/ `:258`（构造） | 6 | 是 | `remaining_turns` 条件存在 |
| `Registry` | `qbot_rpg/content/registry.py:44` | 8 slots / 6 公共属性 | 是 | `__slots__` 私有存储；读经 property |
| `RegistrySnapshot` | `qbot_rpg/content/registry.py:28`（`@dataclass` :27） | 7 | 是 | frozen；热重载回退对象 |
| `modules_raw` | `qbot_rpg/content/registry.py:106`（属性）；构建 `qbot_rpg/content/loader.py:126`,`:314` | map：模块名 → 原始解析结果 | 是（loader 一次性构建并深拷贝） | 键 = `manifest.modules` 声明名 + 恒有 `"manifest"` |
| `ctx` 指令上下文（dict） | `qbot_rpg/assembly/context.py:1256`（`make_context`） | 约 170 个键（逐键列出，见 §5.2） | **否，四段散落注入** | 基础/注册态/未注册态/注册无关；部分键重复注入 |
| `ExtContext`（内容包稳定面） | `qbot_rpg/ext_api.py:125` | 21 只读属性 + 4 包状态方法 | 是 | 稳定 API；author doc `docs/内容包扩展_指令.md`（ext_api.py:22 引用） |

---

#### 1. `Player` 及配套（`qbot_rpg/data/player.py`）

##### 1.1 `Player`（player.py:79-113，`@dataclass(frozen=True)`，23 字段）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注(别名/兼容/派生) |
|---|---|---|---|---|---|
| `qid` | `PlayerQID`（=str） | 必填 | — | `qbot_rpg/data/player.py:86` | 存档键；序列化列名 `player_qid`（repository.py:160/319） |
| `name` | str | 必填 | — | `player.py:87` | 序列化列名 `nickname`（repository.py:161/320）；docstring 限 ≤20 字 |
| `job_id` | str | 可选 | `"novice"` | `player.py:88` | **无独立列**：折入 `persistent_state["job_id"]`（repository.py:94,147,150,316）；读档 `pop` 后由 Player 字段承载 |
| `level` | int | 可选 | `1` | `player.py:89` | |
| `exp` | int | 可选 | `0` | `player.py:90` | |
| `hp` | int | 可选 | `1` | `player.py:91` | 读档 0 合法、仅 None 兜底（repository.py:324-325） |
| `mp` | int | 可选 | `1` | `player.py:92` | 同上 |
| `currencies` | `Dict[str,int]` | 可选 | `{}` | `player.py:93` | 货币 ID→数量 |
| `inventory` | `Tuple[ItemInstance,...]` | 可选 | `()` | `player.py:94` | 落档为 JSON list（repository.py:167） |
| `equipment` | `Dict[str,EquipmentSlot]` | 可选 | `{}` | `player.py:95` | 槽位→槽实例 |
| `attributes` | `PlayerAttributes` | 可选 | `PlayerAttributes()` | `player.py:96` | 序列化列名 `stats`（repository.py:169/330） |
| `achievement_state` | `Any`（旧 tuple / 新 dict） | 可选 | `{}` | `player.py:102` | **兼容键双形态**；docstring 声明新形态 `{unlocked,repeat_count}`，但 codec 仍按 tuple/list 处理（见 §8 不一致） |
| `title_state` | `Dict[str,str]` | 可选 | `{}` | `player.py:103` | 当前佩戴称号 |
| `persistent_state` | `Dict[str,object]` | 可选 | `{}` | `player.py:104` | 自由 dict；checkin/shop/resource/time/dummy_log 等落此 |
| `longline_counters` | `Dict[str,int]` | 可选 | `{}` | `player.py:105` | 只增不减 |
| `reputation_state` | `Dict[str,int]` | 可选 | `{}` | `player.py:106` | 按板独立 |
| `codex_state` | `Dict[str,object]` | 可选 | `{}` | `player.py:107` | 图鉴解锁+完成度 |
| `content_pack_id` | str | 可选 | `""` | `player.py:108` | |
| `content_pack_version` | str | 可选 | `""` | `player.py:109` | |
| `schema_version` | int | 可选 | `4` | `player.py:110` | 注释「当前 5，默认 4 兼容」；DB 列默认 4（schema.py:67） |
| `last_seen_group` | `Optional[str]` | 可选 | `None` | `player.py:111` | 仅来源记录，非存档键 |
| `created_at` | str | 可选 | `""` | `player.py:112` | ISO-8601 UTC |
| `last_active_at` | str | 可选 | `""` | `player.py:113` | 30 天回收判据 |

序列化 codec：写 `player_to_row`（`qbot_rpg/storage/repository.py:144-182`）；读 `row_to_player`（`repository.py:289-343`）；建表列 `qbot_rpg/storage/schema.py:47-70`。

##### 1.2 `PlayerAttributes`（player.py:23-53，4 字段，全部有默认）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `base` | `Dict[str,float]` | 可选 | `{}` | `player.py:34` | ① 白值层，永久落档 |
| `bonus` | `Dict[str,Dict[str,float]]` | 可选 | `{"flat":{},"pct":{}}` | `player.py:35` | ② 加成层，**子键固定 `flat`/`pct`**；便捷法 `flat_bonus`/`pct_bonus`（:39,:43） |
| `temp` | `Dict[str,Dict[str,float]]` | 可选 | `{"pct":{},"flat":{}}` | `player.py:36` | ③ 临时层（战斗 buff），子键固定 `pct`/`flat`；便捷法 `temp_pct`/`temp_flat`（:47,:51） |
| `cond` | `Dict[str,float]` | 可选 | `{}` | `player.py:37` | 条件加成（flat 终值桶） |

读侧归一 `_attrs_from_dict`（repository.py:264-276，缺子键补空）。

##### 1.3 `EquipmentSlot`（player.py:57-75，6 字段）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `item_id` | `ItemID`（=str） | 必填 | — | `player.py:70` | |
| `name` | str | 必填 | — | `player.py:71` | 冗余名称（MIG-3） |
| `slot_level` | int | 可选 | `0` | `player.py:72` | 强化等级 |
| `locked` | bool | 可选 | `False` | `player.py:73` | 强化锁定概率持久化 |
| `gems` | `Tuple[str,...]` | 可选 | `()` | `player.py:74` | 镶嵌宝石 ID（tuple 冻结语义） |
| `uid` | str | 可选 | `""`（`compare=False`） | `player.py:75` | **回指 `ItemInstance.uid`**；空串=旧档→回退 `item_id` 首匹配（注释 :64-67） |

读 codec `_equip_from_dict`（repository.py:246-255）。

---

#### 2. `ItemInstance`（`qbot_rpg/data/item.py`）

##### 2.1 `ItemInstance`（item.py:40-102，`@dataclass(frozen=True)`，20 字段）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注(别名/兼容/派生) |
|---|---|---|---|---|---|
| `item_id` | `ItemID` | 必填 | — | `item.py:53` | 读侧缺省 `""`（repository.py:214） |
| `name` | str | 必填 | — | `item.py:54` | 冗余名称（MIG-3） |
| `count` | int | 必填 | — | `item.py:55` | 堆叠数量；读侧缺省 1（repository.py:216） |
| `quality` | str | 必填 | — | `item.py:56` | 四档枚举；读侧缺省 `"normal"`（repository.py:217） |
| `bound` | bool | 必填 | — | `item.py:57` | 绑定不可赠送/掉落；读侧缺省 False（repository.py:218） |
| `stack_max` | int | 可选 | `99` | `item.py:58` | 读侧缺省 99（repository.py:222，批40 补读漏字段） |
| `slot` | `Optional[str]` | 可选 | `None` | `item.py:59` | 装备槽位 |
| `stats_bonus` | `Dict[str,float]` | 可选 | `{}` | `item.py:60` | 装备词条/虚拟属性键 |
| `traits` | `Tuple[str,...]` | 可选 | `()` | `item.py:61` | tuple 冻结语义 |
| `cooldown_until` | `Optional[str]` | 可选 | `None` | `item.py:62` | ISO-8601 UTC |
| `enhance_level` | int | 可选 | `0` | `item.py:63` | 强化 +N；穿装同步 `EquipmentSlot.slot_level` |
| `uid` | str | 可选 | `""`（`compare=False`） | `item.py:65` | **实例唯一键**；`__post_init__` 空则 `new_item_uid()`（item.py:95-102；生成器 item.py:25-36） |
| `affinities` | `Dict[str,float]` | 可选 | `{}` | `item.py:69` | 批42 打造相性结算值 |
| `set_affixes` | `Tuple[str,...]` | 可选 | `()` | `item.py:71` | 套装词条 |
| `passives` | `Tuple[str,...]` | 可选 | `()` | `item.py:73` | 装备被动 id |
| `quality_level` | int | 可选 | `0` | `item.py:76` | 品质等级 1~10；0=旧档桥接 |
| `enhance_affixes` | `Tuple[str,...]` | 可选 | `()` | `item.py:79` | 强化特殊词条键序列 |
| `required_level` | int | 可选 | `0` | `item.py:84` | 装备等级（淬炼上限输入） |
| `temper_alloc` | `Dict[str,int]` | 可选 | `{}` | `item.py:88` | 淬炼分配；分账于 `enhance_level` |
| `effect_refs` | `Tuple[str,...]` | 可选 | `()` | `item.py:93` | 批61 附加效果/状态引用 |

读写 codec：`_item_from_dict`（repository.py:196-243，逐字段缺省补全）；写侧 `dataclasses.asdict`（repository.py:154-157,167）。旧档补发：`backfill_instance_uids` / `migrate_v2_to_v3`（`qbot_rpg/storage/migrations.py:92-176`）；淬炼缺补 `backfill_instance_temper`（migrations.py:206-234，读时 `repository.py:300-303` 调用）。

---

#### 3. combatant 快照（战斗参战者）

##### 3.1 契约 spec 类型 `CombatantSnapshot`（data/battle.py:33-42，7 字段，全必填）

| 字段 | 类型 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `max_hp` | int | 必填 | — | `qbot_rpg/data/battle.py:36` | |
| `hp` | int | 必填 | — | `data/battle.py:37` | |
| `atk` | int | 必填 | — | `data/battle.py:38` | |
| `dfn` | int | 必填 | — | `data/battle.py:39` | |
| `mag` | int | 必填 | — | `data/battle.py:40` | |
| `spd` | int | 必填 | — | `data/battle.py:41` | |
| `name` | str | 必填 | — | `data/battle.py:42` | 冗余名称（MIG-3） |

`BattleSnapshot`（data/battle.py:45-75，13 字段）：`session_type` :59（必填）、`player`/`enemy` :60-61（必填 `CombatantSnapshot`）、`turn` :62（必填）、`combo_state` :63、`ai_state` :64、`status_state` :65、`marks_state` :66、`resist_table` :67、`effect_triggers` :68、`effect_cooldowns` :69、`formula_state` :70（均 `Dict` 默认 `{}`，formula_state 注释必含 `random_seed`）、`lost_pending` :75（`Optional[Dict]` 默认 `None`，形状 `{target_ref:{id,name}, map_id, pending_since}` 见 :72）。**⚠️ 文件头 :13-20 明示：运行期实际快照是 dict 形态，与本 dataclass 不同，双轨未收敛。**

##### 3.2 运行期 combatant dict —— 基础键（`_DEFAULT_STATS`，core/battle.py:317-322）

| 键 | 默认 | 定义 file:line | 备注 |
|---|---|---|---|
| `max_hp` | 500 | `qbot_rpg/core/battle.py:318` | |
| `hp` | 500 | `core/battle.py:318` | |
| `max_mp` | 100 | `core/battle.py:318` | |
| `mp` | 100 | `core/battle.py:318` | |
| `atk` | 50 | `core/battle.py:319` | |
| `dfn` | 50 | `core/battle.py:319` | |
| `mag` | 30 | `core/battle.py:319` | |
| `spd` | 50 | `core/battle.py:319` | |
| `foc` | 50 | `core/battle.py:320` | |
| `con` | 50 | `core/battle.py:320` | |
| `str` | 50 | `core/battle.py:320` | |
| `int` | 50 | `core/battle.py:320` | |
| `agi` | 50 | `core/battle.py:320` | |
| `spr` | 50 | `core/battle.py:320` | |
| `lck` | 50 | `core/battle.py:320` | |
| `elem_atk` | 0 | `core/battle.py:321` | |
| `elem_res` | 0 | `core/battle.py:321` | |
| `name` | `""` | `core/battle.py:321` | |

`_combatant()` 归一时追加/兜底（core/battle.py:2318-2327）：`max_hp` 缺省 500、`hp` 夹到 ≤max_hp、`name` 缺省 `"unit"`、`dead_mark=False`（:2324）、`skip_turn=False`（:2325）、`defenses={}`（:2326）。

##### 3.3 运行期 combatant dict —— 开战构造追加键

敌方 `_enemy_combatant`（`qbot_rpg/commands/battle_launch_commands.py:146-220`）固定写入：`id` :184、`hp` :185、`max_hp` :186、`mp` :187、`atk` :188、`dfn` :189、`mag` :190、`spd` :191、`foc` :192、`lck` :193、`con` :194、`agi` :195、`name` :196；**动态透传**：`enemies.json stats` 中未映射的剩余键原样进 combatant（:203-208）；战斗词条经 `combatant_updates` 桥入（:212-213，源 `qbot_rpg/data/gear_stats.py:792`，映射表 `COMBAT_TO_COMBATANT` :502）；`parts`（有配置时）:217-219。
玩家 `_player_combatant`（battle_launch_commands.py:223-257）→ 委托 `core/pvp._combatant_of`（`qbot_rpg/core/pvp.py:91-203`）固定键：`id` :155、`name` :156、`level` :157、`hp` :158、`max_hp` :161、`mp` :162、`max_mp` :163、`atk` :166、`dfn` :170、`con` :173、`mag` :174、`spd` :176、`foc` :177、`int` :178、`lck` :179；再透传 `attributes.base` 全部键（:185-192）、装备战斗桥键（:198-202）。launch 侧条件追加：`job` :239-240、`quest_active`/`quest_completed` :241-243、`rune_effects` :247-249、`owned_effect_ids`（值源 `qbot_rpg/data/gear_stats.py:491`）:254-256。

##### 3.4 运行期 combatant dict —— 运行期新增/派生键

| 键 | 形状 | 定义 file:line | 备注 |
|---|---|---|---|
| `shield` | int（派生） | `qbot_rpg/core/battle.py:937` | 由 `defenses.shield.remaining` 派生 |
| `mitigation` | int（派生） | `core/battle.py:938` | 由 `defenses.mitigation` 长度派生 |
| `pv` | 0 | `core/battle.py:939` | 派生默认 |
| `level` | 0 | `core/battle.py:940` | 派生默认 |
| `hit_streak` | 0 | `core/battle.py:941` | 派生默认 |
| `miss_streak` | 0 | `core/battle.py:942` | 派生默认 |
| `marks` / `marks_total` | dict / int | `core/battle.py:946`（`MarksManager.formula_view`，marks.py:428-430） | 公式视图，不另存 |
| `defenses` | dict（子弹结构，见下） | `qbot_rpg/core/effects.py:1035-1045` | 状态/效果写入 |
| `dot_pool` | `{status_id: DOT 实例}` | `effects.py:2229-2235` | DOT 实例形状见 §6.3 |

`defenses` 子结构（effects.py:1035-1045，缺省骨架）：`mitigation` `[]` :1036（元素 `{value,scope}` :1074-1076）、`shield` `{value,remaining,turns,max}` :1037（写点 :2291-2295）、`reflect` `{value,pct,active}` :1038、`absorb` `{value,pct,record,active}` :1039、`fatal_immune` `{count,max}` :1040、`non_fatal_immune` `{active,count}` :1041、`guts` `{count,max}` :1042、`immune` `{status,damage,interrupt,all,block_debuff}` :1043、`mount` `{remaining}` :1044。

##### 3.5 战斗快照顶层 dict 键（运行期）

`_minimal_snapshot`（core/battle.py:2258-2283）与 `start`（core/battle.py:2332-2433）定义顶层键：`session_type` :2333、`battle_id` :2334、`battle_type` :2335、`is_dummy_battle` :2338、`status` :2344、`rule_version` :2345、`registry_generation` :2350、`action_seq` :2360、`battle_time` :2361、`turn` :2362（**兼容镜像 = action_seq，不参与计算**，注释 :2357-2359）、`round_phase` :2363、`player`/`enemy` :2364-2365、`action_record` :2366、`result` :2367（`{flag,mark_win,mark_lose,mark_escape,mutual_kill}`）、`combo_state` :2369、`combo_zeroed_at` :2370、`ai_state` :2371、`lost_pending` :2374、`battle_alchemy_used` :2378（段内权威 `battle_resources.battle_alchemy_used` :2431，注释 :2375-2377）、`stats_collector` :2379、`formula_state` :2380、`timestamps` :2381、`status_state` :2383、`marks_state` :2384、`resist_table` :2385、`effect_triggers` :2386、`effect_cooldowns` :2388、`transform_state`（7 字段）:2391-2393、`resource_state` :2397、`battle_season` :2402、`season_event_state` :2405、`combat_position` :2410-2415、`parts_state` :2419、`battle_resources` :2425-2432、`equip_skill_amp`（条件注入）:2437-2439。
`to_snapshot`（core/battle.py:5537-5613）追加：`schema_version=2` :5560、`rule_version` :5561、`snapshot_id` :5562、`saved_at` :5563、`snapshot_at{boundary,battle_time,action_seq,turn}` :5565-5572、`snapshot_context{mode,map_id,zone}` :5573-5577、`_engine_state` :5578、`_guard_active` :5579、`_death_order` :5580、`ctb_state` :5585-5600、`random_seed` :5604、`rng_state` :5606、`formula_state{random_seed,rng_state}` :5609-5612。旧名别名 `snapshot()` = `to_snapshot()`（:5615-5617）。

---

#### 4. registry / `modules_raw`（`qbot_rpg/content/`）

##### 4.1 `Registry`（content/registry.py:44-224）

非 dataclass，`__slots__` 私有存储（registry.py:51-60）：`_pack_id` :52、`_generation` :53、`_tables` :54、`_names` :55、`_modules_raw` :56、`_manifest` :57、`_schema_version` :58、`_lock` :59。公共只读属性：`pack_id` :93、`generation` :97、`schema_version` :101、`modules_raw` :105-108、`manifest` :110；读方法 `resolve(id,kind)` :82、`resolve_name(id)` :86、`all_ids(kind)` :90、`contains(id)` :114；快照 `snapshot()` :122、`restore(snap)` :135、`from_snapshot` :152、`build` :167、`integrity_check` :189。

##### 4.2 `RegistrySnapshot`（registry.py:28-41，`@dataclass(frozen=True)`，7 字段）

| 字段 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `pack_id` | str | 必填 | — | `content/registry.py:35` | |
| `generation` | int | 必填 | — | `registry.py:36` | 世代号（RSM 续战重绑定） |
| `tables` | `Mapping[str, Mapping[str, AnyDef]]` | 必填 | — | `registry.py:37` | kind → id → Def |
| `names` | `Mapping[str, str]` | 必填 | — | `registry.py:38` | id → 显示名（名称冗余） |
| `modules_raw` | `Mapping[str, object]` | 必填 | — | `registry.py:39` | 各模块原始解析数据 |
| `manifest` | `Optional[Manifest]` | 可选 | `None` | `registry.py:40` | |
| `schema_version` | `Optional[int]` | 可选 | `None` | `registry.py:41` | `build` 时取 `manifest.schema_version` :185 |

##### 4.3 `modules_raw` 形状

- **类型**：`Mapping[模块名:str, object]`（顶层 dict，深拷贝；registry.py:39/56/106-108，构建 `loader.py:126`）。
- **键来源**：`manifest.modules` 声明顺序去重（loader.py:87-93 `_ordered_declared`）+ 恒有 `"manifest"` 键（loader.py:314 `modules["manifest"]=manifest_raw`；`integrity_check` 断言时排除，registry.py:204）。
- **值形态**：list 形态（条目表，如 skills/items/enemies）；`stats`/`formula` 为 map 形态（键=ID，loader.py:117-120）；`forge`/`enhance`/`fishing` 为顶层 obj 模块（context.py:1347-1361 注释）。
- **已知模块名注册表**：`FIXED_REGISTER_ORDER` = effects/statuses/marks/skill_chains/action（loader.py:46）；`_KIND_FOR_MODULE` 另登记 **28** 个（批82 · Q7/NEW-5 更正：原写 29；loader.py:146-198）：effects、statuses、marks、skill_chains、action、skills、jobs、items、equipment、traits、recipe、proficiency、slots、runes、forge、enhance、fishing、achievements、enemies、maps、dungeon、stats、npc、formula、conditional、shop、quest、checkin。
- **kind 映射**（`_KIND_FOR_MODULE`，loader.py:150-202）：模块名→kind，如 effects→effect、statuses→status、marks→mark、enemies→enemy 等。
- **对照自检**：`check_register_table_consistency`（loader.py:205-218）与 `check_manifest_modules_registered`（loader.py:221-233）。
- **框架模块目录**（编辑器面板，非运行时必读）：`FRAMEWORK_MODULE_CATALOG`（`qbot_rpg/content/module_catalog.py:68` 起）；条目类型 `ModuleCatalogEntry`（module_catalog.py:31，`@dataclass` :30，字段 module/label/purpose/entry_type/requires/implemented/settings_section/overlap_with/overlap_note）。

##### 4.4 相关容器

`Manifest`（`qbot_rpg/content/models.py:728-749`）：`name` :729、`version` :730、`schema_version` :731、`author` :732、`modules: Tuple[str,...]` :733、`raw` :734（默认 `{}`）；`from_dict` :736-749。`Pack`（models.py:762-774，frozen）：`pack_id` :766、`manifest` :767、`modules` :768、`report` :769、`registry` :770。

---

#### 5. `ctx` 指令上下文

手册存在两个不同对象，务必区分：
- **`ExtContext`**（`qbot_rpg/ext_api.py:125`）：内容包扩展 handler 收到的稳定面对象（`handler(ctx, parsed)`）。
- **内部 `ctx` dict**（`qbot_rpg/assembly/context.py:1256` `make_context`）：框架指令壳的上下文，键极多、四段拼装。

##### 5.1 `ExtContext`（ext_api.py:125-304）

构造参数（仅框架装载层调用，ext_api.py:146-157）：`pack_id` :149（必填）、`pack_version` :150（默认 `""`）、`ctx` :151（默认 `None`→`{}`）、`parsed` :152（默认 `None`）。

| 成员 | 类型/形状 | 必填? | 默认 | 定义 file:line | 备注(别名/兼容/派生) |
|---|---|---|---|---|---|
| `pack_id` | str | 必填（构造） | `""` | `ext_api.py:160-163` | 属性 |
| `pack_version` | str | 可选 | `""` | `ext_api.py:165-168` | |
| `player_id` | str | 可选 | `""` | `ext_api.py:170-174` | **兼容键**：`qq_id` or `qid` or `user_id` |
| `group_id` | str | 可选 | `""` | `ext_api.py:176-178` | |
| `user_id` | str | 可选 | `""` | `ext_api.py:180-182` | |
| `channel` | str | 可选 | `""` | `ext_api.py:184-186` | |
| `message` | str | 可选 | `""` | `ext_api.py:188-190` | |
| `registered` | bool | 可选 | `False` | `ext_api.py:192-194` | |
| `is_gm` | bool | 可选 | `False` | `ext_api.py:196-198` | |
| `player` | `Optional[Mapping]` | 可选 | `None`（未注册） | `ext_api.py:201-204` | 只读快照；`_player_view` 用 `dataclasses.asdict` 深拷贝（:84-100） |
| `settings` | Mapping | 可选 | `{}` | `ext_api.py:206-209` | 只读映射 |
| `templates` | Mapping | 可选 | `DEFAULT_TEMPLATES` | `ext_api.py:211-215` | 本包覆盖表 |
| `parsed` | Any（`ParsedCommand`） | 可选 | `None` | `ext_api.py:217-220` | |
| `command` | str | 派生 | `""` | `ext_api.py:222-225` | = `parsed.command` |
| `args` | tuple[str,...] | 派生 | `()` | `ext_api.py:227-236` | |
| `args_text` | str | 派生 | `""` | `ext_api.py:238-241` | 空格连接 |
| `registry` | Any | 可选 | `None` | `ext_api.py:243-245` | 不承诺稳定 |
| `repo` | Any | 可选 | `None` | `ext_api.py:247-249` | |
| `db` | Any | 派生 | `None` | `ext_api.py:251-254` | = `repo.db` |
| `tpl(key,data)` | 方法→str | — | — | `ext_api.py:257-259` | 带本包覆盖 |
| `rng` | `random.Random` | 派生 | — | `ext_api.py:261-264` | 按（包,玩家）定种；`rng()` :103-110 |
| `log` | Logger | 派生 | — | `ext_api.py:266-269` | `content.ext.<pack_id>` |
| `_state_keys()` | 方法→tuple | — | — | `ext_api.py:272-281` | 缺则抛 `ExtApiUnavailable` |
| `get_state` / `set_state` / `patch_state` / `clear_state` | async 方法 | — | — | `ext_api.py:283`,`:291`,`:296`,`:301` | 仅本包格子（`player_pack_state`） |

`__all__`（ext_api.py:42-56）与稳定面版本 `EXT_API_VERSION="1"` :59。
（`parsed` 原对象字段见 `qbot_rpg/commands/parsers.py:249-294`：`raw/tokens/command/args/mode/session_candidate` + 扩展 16 字段，`__slots__` :266-271。）

##### 5.2 内部 `ctx` dict（`make_context`，context.py:1256-2034）

###### (a) 基础段（无论是否注册都注入，context.py:1295-1373）

| 键 | 形状 | 注入态 | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `registered` | bool | 恒有 | `False` | `assembly/context.py:1296` | |
| `player` | `Optional[Player]` | 恒有 | `None` | `context.py:1297` | 活对象，落档依据 |
| `settings` | Mapping | 恒有 | `{}` | `context.py:1298` | |
| `default_map` | Any | 恒有 | `settings.get("default_map")` | `context.py:1299` | |
| `group_id` | Any | 恒有 | event 值 | `context.py:1301` | |
| `user_id` | Any | 恒有 | event 值 | `context.py:1302` | |
| `message` | Any | 恒有 | event 值 | `context.py:1303` | |
| `channel` | Any | 恒有 | event 值 | `context.py:1304` | |
| `group_name` | Any | 恒有 | event 值 | `context.py:1305` | |
| `per_channel` | Any | 恒有 | event 值 | `context.py:1306` | |
| `to` | Any | 恒有 | event 值 | `context.py:1307` | |
| `qq_id` | `str|None` | 恒有 | `None` | `context.py:1308` | 平台身份键 |
| `qid` | `str|None` | 恒有 | `None` | `context.py:1309` | **兼容别名**（会话主键 MUT-02；注释 :1309-1310） |
| `is_gm` | bool | 恒有 | `False` | `context.py:1311` | |
| `registered_cmds` | set | 恒有 | 空集 | `context.py:1315` | 非 stub 指令名 |
| `message_id` | str | 恒有 | `""` | `context.py:1319` | 终态结算依赖 |
| `quest_engine` | Any | 恒有 | `None` | `context.py:1321` | |
| `shop_engine` | Any | 恒有 | `None` | `context.py:1322` | |
| `checkin_engine` | Any | 恒有 | `None` | `context.py:1323` | |
| `battle_engine` | Any | 恒有 | `None`（后段 :1687/:1749 覆盖） | `context.py:1324` | |
| `battle_reward_fn` | Any | 恒有 | `None`（后段 :1973 覆盖） | `context.py:1325` | |
| `battle_rewards` | dict | 恒有 | `{}` | `context.py:1326` | |
| `battle_hint` | Any | 恒有 | `None` | `context.py:1327` | |
| `battle_status_changes` | list | 恒有 | `[]` | `context.py:1328` | |
| `current_shop_ref` | list | 恒有 | `[]` | `context.py:1329` | |
| `registry` | `Registry` | 恒有 | `deps.registry` | `context.py:1331` | |
| `templates` | Mapping | 恒有 | 注册表模板表 | `context.py:1336` | |
| `repo` | Any | 恒有 | `deps.repo` | `context.py:1339` | |
| `session_mgr` | Any | 恒有 | `deps.session_mgr` | `context.py:1340` | |
| `items` | dict | 恒有 | `_table_from_registry` | `context.py:1341` | 后段 :1777 重注（合并 equipment） |
| `recipe` | dict | 恒有 | 同上 | `context.py:1342` | |
| `traits` | dict | 恒有 | 同上 | `context.py:1343` | |
| `runes` | dict | 恒有 | kind=rune 表 | `context.py:1346` | |
| `forge` | dict | 恒有 | `modules_raw["forge"]` | `context.py:1352` | 顶层 obj |
| `enhance` | dict | 恒有 | `modules_raw["enhance"]` | `context.py:1357` | 顶层 obj |
| `fishing` | dict | 恒有 | `modules_raw["fishing"]` | `context.py:1361` | 顶层 obj |
| `battle_snapshot` | Any | 恒有 | `None`（条件覆盖 :1988） | `context.py:1362` | |
| `battle_alchemy_engine` | Any | 恒有 | `None`（条件覆盖 :1990） | `context.py:1363` | |
| `upgrade_unlocks` | dict | 恒有 | `{}`（注册态 :1551 覆盖） | `context.py:1364` | |
| `learned_blueprints` | dict | 恒有 | `{}`（注册态 :1553 覆盖） | `context.py:1367` | |
| `wallet` | `GemWallet` | 恒有 | 由 settings 构造 | `context.py:1370` | |
| `prof_engine` | Any | 恒有 | 由 settings 构造 | `context.py:1371` | |
| `resolve_player_name` | Any | 恒有 | `None` | `context.py:1372` | hook 注入位 |
| `same_group` | Any | 恒有 | `None` | `context.py:1373` | hook 注入位 |

###### (b) 注册态段（`registered=True`，context.py:1398-1584）

| 键 | 形状 | 注入态 | 默认/兜底 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `name` / `job_id` / `level` / `exp` / `hp` / `mp` | 各 scalar | 仅注册 | Player 字段 | `context.py:1400-1405` | |
| `job_name` | str | 仅注册 | `job_name_override` 优先 | `context.py:1408-1409` | |
| `location` | str | 仅注册 | `ps.location`/`default_map`/`""` | `context.py:1395`,`:1410` | |
| `title` | str | 仅注册 | 当前佩戴称号 | `context.py:1411` | |
| `stats` | Mapping | 仅注册 | 注册表 stats | `context.py:1412` | |
| `attributes` | `PlayerAttributes` | 仅注册 | 新实例 | `context.py:1413` | |
| `attr_final` | dict | 仅注册 | 计算产物 | `context.py:1414` | |
| `exp_next` | int | 仅注册 | 配置推算 | `context.py:1415` | |
| `level_cap` | int | 两态均有 | `45` | `context.py:1416`（未注册 :1601） | |
| `conditional_rules` | Any | 仅注册 | `settings`/`()` | `context.py:1417` | |
| `attr_types` | Any | 仅注册 | `settings.get` | `context.py:1418` | |
| `imprints` | dict | 仅注册 | `settings`/`{}` | `context.py:1419` | |
| `inventory` | `Dict[str,int]` | 仅注册 | 由实例聚合 | `context.py:1420` | 后又由 `_inventory_hooks` 重绑 :1855 |
| `inventory_items` | `List[ItemInstance]` | 仅注册 | `player.inventory` | `context.py:1421` | |
| `equipment` | dict | 仅注册 | `player.equipment` | `context.py:1422` | |
| `worn_refs` | dict | 仅注册 | 派生 | `context.py:1423` | |
| `active_effects` | dict | 仅注册 | `ps.active_effects` | `context.py:1424` | |
| `effects` | list | 仅注册 | 派生渲染 | `context.py:1425` | |
| `quest_active` / `quest_completed` / `quest_daily` | list/dict | 仅注册 | `ps` | `context.py:1426-1428` | |
| `longline_counters` | dict | 仅注册 | 直接引用 `player.longline_counters` | `context.py:1432-1434` | 就地改=落档 |
| `event_counts` | dict | 仅注册 | `_ps_init` | `context.py:1435` | |
| `currencies` | `Dict[str,int]` | 仅注册 | 直接引用 `player.currencies` | `context.py:1439-1441` | 就地改=落档 |
| `title_state` | dict | 仅注册 | 直接引用 | `context.py:1447-1449` | |
| `reputation_state` | dict | 仅注册 | 直接引用 | `context.py:1453-1455` | |
| `quest_board_state` | dict | 仅注册 | `_ps_init` | `context.py:1457` | |
| `personal_buys` | dict | 注册/未注册 | `{}` | `context.py:1458`（未注册 :1617） | |
| `checkin_state` | dict | 仅注册 | `{}` | `context.py:1459` | |
| `shortcuts` | dict | 注册/未注册 | `{}` | `context.py:1460`（未注册 :1619） | |
| `weak_until` | Any | 仅注册 | `ps.weak_until` | `context.py:1464` | |
| `weak_remaining_sec` | int | 仅注册 | 派生 | `context.py:1465` | |
| `discovered_maps` | list | 仅注册 | 惰性挂 ps | `context.py:1469` | |
| `shortcut_max` | int | 两态均有 | `20` | `context.py:1470`（未注册 :1620） | |
| `quest_board_cfg` | dict | 两态均有 | `settings.quest_board`/`{}` | `context.py:1473`（未注册 :1623） | |
| `contest_cfg` | dict | 两态均有 | `settings.contest`/`{}` | `context.py:1475`（未注册 :1625） | |
| `npc_delivered` | dict | 注册/未注册 | `{}` | `context.py:1476`（未注册 :1626） | |
| `heard` | set | 注册/未注册 | `set()` | `context.py:1477`（未注册 :1627） | |
| `codex_state` | dict | 注册/未注册 | `{}` | `context.py:1478-1480`（未注册 :1628） | |
| `event_log` | list | 注册/未注册 | `[]` | `context.py:1481`（未注册 :1629） | |
| `dialog_active` | bool | 注册/未注册 | `False` | `context.py:1482`（未注册 :1630） | |
| `dialog_session` | Any | 注册/未注册 | `None` | `context.py:1485`（未注册 :1631） | |
| `farm_plots` / `helpers` / `proficiency` | dict | 仅注册 | `_ps_init` | `context.py:1490-1492` | 写即落档 |
| `forge_preview` | dict | 仅注册 | `_ps_init` | `context.py:1497` | |
| `forged` | list | 仅注册 | `_ps_init(ps,"forge_forged",[])` | `context.py:1505` | **键名别名**（ps 键 `forge_forged`） |
| `fish_state` | dict | 仅注册 | `_ps_init` | `context.py:1509` | |
| `consume_bait` / `mode` / `king_event` / `king_victory_record` | callable | 仅注册 | 薄委托 hook | `context.py:1510-1513` | |
| `achievement_state` | `{unlocked,repeat_count}` | 仅注册（未注册给空壳） | `{"unlocked":{},"repeat_count":{}}` | `context.py:1522-1524`（未注册 :1634） | |
| `achievements` | list | 两态均有 | `modules_raw["achievements"]` | `context.py:1525`（未注册 :1635） | |
| `titles` | dict | 两态均有 | 注册表 titles | `context.py:1526`（未注册 :1636） | |
| `codex_categories` | dict | 注册/未注册 | `{}` | `context.py:1527`（未注册 :1637） | |
| `prof_level` | dict | 仅注册 | 派生 `{job_id:level}` | `context.py:1531` | |
| `pvp_target` | str | 仅注册 | `_ps_init(...,"")` | `context.py:1537` | |
| `pvp_daily` | `{rewards,pairs}` | 仅注册 | `{"rewards":0,"pairs":{}}` | `context.py:1538` | |
| `respawn_hook` | callable | 仅注册 | 薄委托 | `context.py:1539` | |
| `players` | dict | 仅注册 | 空表兜底 | `context.py:1540` | |
| `active_sessions` | dict | 仅注册 | 会话表 | `context.py:1541` | |
| `skills` | dict | 仅注册（另 :1655 覆盖全域） | kind=skill 表 | `context.py:1546` | |
| `upgrade_unlocks` / `learned_blueprints` | dict | 仅注册 | `_ps_init` | `context.py:1551`,`:1553` | 覆盖基础段空 `{}` |
| `skill_slots` | 接口 dict | 仅注册 | `assemble/save/load` | `context.py:1557` | |
| `skill_slots_state` | dict | 仅注册 | `_ps_init(ps,"skill_slots",{})` | `context.py:1558` | |
| `set_tracker` / `set_skills` | dict | 仅注册 | `_ps_init` | `context.py:1562-1563` | |
| `equip_skills` | dict | 仅注册 | `_ps_init` | `context.py:1567` | |
| `rune_sockets` | dict | 仅注册 | `_ps_init` | `context.py:1571` | 键=`ItemInstance.uid` |
| `max_hp` / `max_mp` | int | 仅注册（条件） | `attr_final` 出口 | `context.py:1582`,`:1584` | 仅当 attr_final>0 |

###### (c) 未注册态段（`registered=False`，context.py:1586-1639）

与 (b) 同名键的安全空值：`name`/`job_id`/`level`/`exp`/`hp`/`mp`/`job_name`/`location`/`title` = `None`（:1588-1596）；`stats`/`imprints`/`quest_board_cfg`/`contest_cfg` 由 settings（:1597,:1604,:1623,:1625）；`attributes=None` :1598；`attr_final={}` :1599；`exp_next=None` :1600；`inventory={}`/`inventory_items=[]`/`equipment={}`/`worn_refs={}`/`active_effects={}`/`effects=[]` :1605-1610；`quest_active=[]`/`quest_completed=[]`/`quest_daily={}` :1611-1613；`longline_counters={}`/`event_counts={}`/`currencies={}` :1614-1616；`personal_buys={}`/`checkin_state={}`/`shortcuts={}` :1617-1619；`npc_delivered={}`/`heard=set()`/`codex_state={}`/`event_log=[]`/`dialog_active=False`/`dialog_session=None` :1626-1631；`achievement_state` 空壳 :1634；`achievements`/`titles` 注册表 :1635-1636；`codex_categories={}` :1637；`level_cap`/`shortcut_max` 同 (b)。
**未注册态不含** `weak_until`/`weak_remaining_sec`/`discovered_maps`/`farm_plots`/`helpers`/`proficiency`/`forge_preview`/`forged`/`fish_state`/`consume_bait`/`mode`/`king_event`/`king_victory_record`/`prof_level`/`pvp_*`/`respawn_hook`/`players`/`active_sessions`/`skill_slots*`/`set_*`/`equip_skills`/`rune_sockets`/`max_hp`/`max_mp` —— 指令壳需自行兜底。

###### (d) 注册无关段（context.py:1642-2034）

| 键 | 形状 | 注入态 | 定义 file:line | 备注 |
|---|---|---|---|---|
| `game_world` | Any | 恒有 | `context.py:1642` | |
| `map_def` | Any | 恒有 | `context.py:1643` | |
| `monster_pool` | Any | 恒有 | `context.py:1644` | |
| `npcs` | list | 恒有 | `context.py:1645` | |
| `skills` | dict | 恒有 | `context.py:1655` | 覆盖注册态值 |
| `jobs` | dict | 恒有 | `context.py:1656` | |
| `skill_chains` | dict | 恒有 | `context.py:1658` | |
| `marks` | dict | 恒有 | `context.py:1659` | kind=mark |
| `statuses` | dict | 恒有 | `context.py:1660` | kind=status |
| `npc_interactions` | callable | 恒有 | `context.py:1663` | |
| `world_stock` | `{shop_id:{item_id:int}}` | 恒有 | `context.py:1664` | 初始 `{}` |
| `world_sold_out` | `{shop_id:{item_id:True}}` | 恒有 | `context.py:1665` | |
| `last_refresh` | `{shop_id:"YYYY-MM-DD"}` | 恒有 | `context.py:1666` | |
| `blackmarket_goods` | `{shop_id:[goods]}` | 恒有 | `context.py:1667` | |
| `battle_session` | Any | 恒有 | `context.py:1670` | |
| `target` | Any | 恒有 | `context.py:1671` | 取自 battle_session.target |
| `turn` | Any | 恒有 | `context.py:1672` | 取自 battle_session.turn（与快照镜像 `turn` 不同源） |
| `in_battle` | bool | 恒有 | `context.py:1676-1680` | |
| `battle_engine` | Any | 条件 | `context.py:1687`,`:1749` | 有活跃战斗时 from_snapshot 恢复 |
| `start_battle` | Any | 恒有 | `context.py:1754` | 初始 `None` |
| `rng` | 玩家级 RNG | 恒有 | `context.py:1766` | `player_rng(ps, ...)` |
| `_rng_initial_state` | Any | 恒有 | `context.py:1768` | 落档门控基准，下划线内部键 |
| `now` | str | 恒有 | `context.py:1770` | UTC+8 |
| `today` | str | 恒有 | `context.py:1771` | |
| `season` / `period` | Any | 恒有 | `context.py:1772` | |
| `weather` | Any | 恒有 | `context.py:1773` | |
| `gm_commands` | Any | 恒有 | `context.py:1776` | |
| `items` | dict | 恒有 | `context.py:1777` | 覆盖；:1782-1787 合并 equipment 表 |
| `effect_table` | dict | 恒有 | `context.py:1788` | |
| `quests` | dict | 恒有 | `context.py:1792-1796` | Def→raw |
| `quest_ids` | list | 恒有 | `context.py:1797` | |
| `shops` | dict | 恒有 | `context.py:1802-1806` | |
| `checkin_tables` | dict | 恒有 | `context.py:1813-1817` | |
| `maps` | list | 恒有 | `context.py:1825-1835` | **list 形态**（非 dict） |
| `dungeons` | dict | 恒有 | `context.py:1825-1837` | |
| `enemies` | dict | 恒有 | `context.py:1825-1837` | |
| `resolve_item` | callable | 恒有 | `context.py:1848` | 单参包装绑定 kind |
| `resolve_shop` | callable | 恒有 | `context.py:1849` | |
| `resolve_recipe` | callable | 恒有 | `context.py:1850` | |
| `resolve_trait` | callable | 恒有 | `context.py:1851` | |
| `bump_event` | callable | 恒有 | `context.py:1854` | |
| `add_item` / `remove_item` / `count_item` | callable | 恒有 | `context.py:1855` → `_inventory_hooks`（:1106-1239，返回 :1239） | 签名见 :1132（add_item）、:1213（remove_item）、:1235（count_item） |
| `inventory` / `inventory_instances` | dict / list | 恒有 | `context.py:1121`,`:1127` | 闭包重绑 |
| `_m8_dirty_inventory` | bool | 条件（写时） | `context.py:1130` | 落档合并标记 |
| `add_item_denied` | `{item,reason,message}` | 条件（拒绝时） | `context.py:1162-1163` | max_hold 门禁人话 |
| `equipment_offhand` | Mapping | 条件（settings 有） | `context.py:1867` | 未注入则不改既有键集 |
| `panel_budget` | Mapping | 条件 | `context.py:1872` | |
| `monster_scaling` | Mapping | 条件 | `context.py:1876` | |
| `effect_axes` | Mapping | 条件 | `context.py:1881` | |
| `slots` | `{"slots":{...}}` | 条件 | `context.py:1887` | settings.slot_defs |
| `equip_engine` | `EquipmentEngineAdapter` | 条件 | `context.py:1894-1897` | |
| `resolve_attr_final` | callable | 恒有 | `context.py:1901` | |
| `battle_reward_fn` | callable | 恒有 | `context.py:1973` | 覆盖基础段 |
| `battle_snapshot` / `battle_alchemy_engine` | dict / engine | 条件（战斗中） | `context.py:1988`,`:1990` | |
| `count_item` / `remove_item` | callable | 条件（战斗中覆写） | `context.py:2029`,`:2030` | 绑 battle_resources.materials |

---

#### 6. 状态实例与印记实例

##### 6.1 契约 spec 类型 `StatusInstance` / `Duration`（`qbot_rpg/data/status.py`）

`Duration`（status.py:25-29，2 字段）：`turns` :28（必填）、`charges` :29（必填）。
`StatusInstance`（status.py:33-45，7 字段，全必填）：

| 字段 | 类型 | 必填? | 定义 file:line | 备注 |
|---|---|---|---|---|
| `status_id` | `StatusID` | 必填 | `qbot_rpg/data/status.py:39` | 引用键 |
| `name` | str | 必填 | `status.py:40` | 冗余名称（MIG-3） |
| `level` | int | 必填 | `status.py:41` | |
| `stacks` | int | 必填 | `status.py:42` | |
| `duration` | `Duration` | 必填 | `status.py:43` | `{turns,charges}` 双形 |
| `decay` | float | 必填 | `status.py:44` | **⚠️ 与 effects 运行期 str 衰减类型不一致**（status.py:7-12 文件头登记） |
| `source` | str | 必填 | `status.py:45` | |

##### 6.2 运行期状态实例 dict（`core/effects.py`）

**唯一构造源** `_new_instance`（`qbot_rpg/core/effects.py:735-763`）：

| 键 | 形状 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `status_id` | str | 必填 | — | `effects.py:749` | |
| `name` | str | 必填 | — | `effects.py:750` | |
| `category` | str | 可选 | `"other"` | `effects.py:751`；写点 :781 | dispel 寻址 |
| `level` | int | 可选 | `1` | `effects.py:752`；重置点 :695,:703,:727 | |
| `stacks` | int | 可选 | `1` | `effects.py:753`；叠加点 :641,:678,:717,:728 | |
| `value` | int | 必填 | — | `effects.py:754` | 衰减主体数值（halve/decrement 作用对象；衰减时改写 :818,:821,:840） |
| `turns` | int | 必填 | — | `effects.py:755` | 剩余行动数；重置 :768；扣减 :863 |
| `charges` | int | 必填 | — | `effects.py:756` | 剩余触发次数；重置 :769；扣减 :843 |
| `decay` | str | 必填 | — | `effects.py:757` | 取 `raw.decay`，缺省 `"none"`（:546）；**与 spec dataclass 的 float 不一致** |
| `decay_subject` | str | 必填 | — | `effects.py:758` | 缺省 `"carrier"`（:547） |
| `source` | str | 必填 | — | `effects.py:759` | |
| `immune_uses` | int | 可选 | `0` | `effects.py:760`；扣减 :797 | |
| `trigger_halve` | bool | 可选 | `False` | `effects.py:761`；刷新 :784 | D4 trigger 衰减 |
| `_uid` | str | 必填（内部派生） | `self._next_uid()` | `effects.py:762` | 内部实例身份，比对 :318 |

运行期另可被写：`name`（DOT 展示名覆写 :2232）、`part_break_per_tick`（:2235）。

##### 6.3 DOT 池实例（combatant 子结构，shape 不同）

写入点 `effects.py:2229-2235`：`status_id` :2229、`value` :2229、`tick` :2230、`turns` :2230、`source` :2230、`name`（条件）:2232、`part_break_per_tick`（条件）:2235；容器 = combatant `dot_pool`（`{status_id: inst}`，:2229）。

##### 6.4 印记实例 dict（`qbot_rpg/core/marks.py`）

**权威键元组** `_MARK_INSTANCE_KEYS`（marks.py:53-60）：`mark_id`、`name`、`count`、`applier`、`polarity`、`remaining_turns`。
**构造点** `MarksManager.apply_add` 的 `new_inst`（marks.py:258-264）：

| 键 | 形状 | 必填? | 默认 | 定义 file:line | 备注 |
|---|---|---|---|---|---|
| `mark_id` | str | 必填 | — | `marks.py:259` | 定义引用键 |
| `name` | str | 必填 | 回退 `mark_id` | `marks.py:260`（`_def_name` :208-212） | 冗余名（热重载降级） |
| `count` | int | 必填 | 1，夹到 `max_stack` | `marks.py:261` | 叠加/饱和减法 :255,:288-294 |
| `applier` | str | 必填 | `"player"`（None→默认） | `marks.py:262` | D-05 |
| `polarity` | str | 必填 | `"positive"` | `marks.py:263`（`polarity_of` :226-232） | 枚举 `POLARITIES`（:50） |
| `remaining_turns` | int | 可选 | 仅 `duration="turns:N"` 时写入 | `marks.py:265-271` | 生命周期 tick :323-339 |

容器形状：`marks_state = {"player": [实例], "enemy": [实例]}`（`BATTLE_SIDES` :47；构造 :166-177；快照 :434-459）。

---

#### 7. 对象间引用与兼容键速查

| 关系 | 出处 |
|---|---|
| `EquipmentSlot.uid` → `ItemInstance.uid` | `data/player.py:75`（注释 :64-67）；迁移补回指 `storage/migrations.py:107-133` |
| `Player.job_id` → `persistent_state["job_id"]` | `storage/repository.py:94,150,316` |
| `Player.name` → 列 `nickname`；`attributes` → 列 `stats` | `storage/repository.py:161,169`；`storage/schema.py:50,58` |
| `ctx["qid"]` / `ctx["qq_id"]` / `user_id` 同源 | `assembly/context.py:1277,1308-1310`；`ext_api.py:173-174` |
| 战斗快照 `turn` = `action_seq` 镜像（不参与计算） | `core/battle.py:2357-2362,5569-5571` |
| 玩家 combatant 防御键 `dfn`/`con`/旧 `def` 三路兼容 | `core/pvp.py:170-173` |
| `ctx["forged"]` ↔ ps 键 `forge_forged` | `assembly/context.py:1505` |
| `ItemInstance.stack_max` 读侧缺省 99（批40 补漏） | `storage/repository.py:219-222` |

---

#### 8. 缺口与不一致（供手册单独标注）

1. **`Player.achievement_state` 注释与实现不一致（兼容键双形态未收敛）**
   - docstring 声明已迁移为持久化段 `{unlocked, repeat_count}`：`data/player.py:97-102`。
   - 但写 codec 仍 `list(player.achievement_state)`（dict 会被转成键列表）：`storage/repository.py:174`；读 codec 仍 `tuple(...)`：`repository.py:331`；DB 列默认 `'[]'`：`storage/schema.py:63`。运行期真值实际挂在 `ctx["achievement_state"]`→`persistent_state`（`assembly/context.py:1522-1524`），Player 字段退化为旧档兼容读。**字段散落 3 处、单一源缺失。**

2. **combatant / battle 快照双轨未收敛**
   - 契约类型 `CombatantSnapshot`/`BattleSnapshot`（`data/battle.py:32-75`）与运行期 dict 结构不同，文件头 `data/battle.py:13-20` 自登记「收敛前 U3 对真实 dict 快照未生效」。
   - combatant 字段实际散落 ≥4 处：默认键 `core/battle.py:317-322`、归一 `core/battle.py:2318-2327`、敌方构造 `commands/battle_launch_commands.py:182-220`、玩家构造 `core/pvp.py:154-203`，再加运行期 `core/battle.py:937-942` 与 `effects.py:2229-2235`。**无单一源。**

3. **`StatusInstance`/`Duration` 契约类型与运行期 dict 不一致**
   - 文件头自登记：`data/status.py:7-12`；实测运行期字段在 `core/effects.py:749-762`（多出 `category/value/decay_subject/immune_uses/trigger_halve/_uid`，且 `decay` 为 str 非 float）。**dataclass 只有代码声明、无运行期接线。**

4. **`ctx` 键无单一源、四段散落且重复注入**
   - 基础段 `assembly/context.py:1295-1373`、注册态 `:1398-1584`、未注册态 `:1586-1639`、注册无关 `:1642-2034`。
   - 重复注入示例：`items`（:1341 vs :1777）、`skills`（:1546 vs :1655）、`battle_engine`（:1324 vs :1687/:1749）、`battle_reward_fn`（:1325 vs :1973）、`upgrade_unlocks`/`learned_blueprints`（:1364/:1367 vs :1551/:1553）、`inventory`（:1420 vs :1855）、`count_item`/`remove_item`（:1855 vs :2029/:2030 条件覆写）。
   - 未注册态缺键（见 §5.2(c)），指令壳只能靠 `ctx.get` 兜底——手册需列出「哪些键仅注册态存在」。

5. **`modules_raw` 无字段级 schema，只有代码登记**
   - 形状由 `loader.py:96-128` 构建、模块名由 `_KIND_FOR_MODULE`（loader.py:150-202）＋ `FRAMEWORK_MODULE_CATALOG`（module_catalog.py:68 起）两处登记，**两处需人工保持一致**；一致性只有单向自检（loader.py:205-233）。

6. **运行期战斗快照顶层键只有代码、无 dataclass 文档**
   - 如 `combat_position`/`parts_state`/`battle_resources`/`transform_state`/`resource_state` 等段（`core/battle.py:2389-2432`）及各 `setdefault` 运行期键（`core/battle.py:3449,3696,3860,4131,4353-4355,4475-4478,5161,5248`）均无契约类型声明。

7. **战斗期派生键未在数据模型登记**
   - `shield`/`mitigation`/`pv`/`level`/`hit_streak`/`miss_streak`（`core/battle.py:937-942`）为公式视图派生，改变 `_combat_map` 即改变扩展可见变量，手册需标注「派生、非落档字段」。

---

## §3 事件

### 3.0 先分清**两套"事件"**（外部开发者最容易混的第一坑）

| 体系 | 唯一源 | 用途 | 存储 | 消费方 |
|---|---|---|---|---|
| **A. 战斗效果时点 `EVENT_POINTS`** | qbot_rpg/data/event_points.py:25 | effects `trigger` / statuses `on_gain/on_lose/on_expire` 在战斗时点触发动作 | 不存储，即时分派 | `core/event_dispatcher.dispatch_event`（:325-332 由 effects 注入） |
| **B. 计数事件键 `[事件:XXX]`** | qbot_rpg/core/event_bus.py:53 `EVENT_KEY` + :66 `EVENT_KEY_DEFAULTS` | 进阶/成就/任务条件的**计数触发**（签到/击杀/图鉴/副本通关…） | `event_counts` + `event_log` 环形（:46 `EVENT_LOG_KEY`, :49 `DEFAULT_EVENT_LOG_CAP=300`） | `condition_engine` / `quest.py` / 成就校验器 |

两套**同名不同物**（都有"事件"字样、都可配置），但**互不派发**。全审计见 `docs/m125_事件键审计.md`（写点 13+2、键 14 类；settings `events` 段可配 name 段、外壳 `[事件:` 必须硬编码，:44-53）。

### 3.1 `EVENT_POINTS` 逐时点（17 点）

> 语义权威 doc：`docs/深度打造_实现说明.md:728-752`（14.3 表 + death/on_kill 对照表）；
> 时点唯一源：`qbot_rpg/data/event_points.py:25`；再导出：`qbot_rpg/core/event_dispatcher.py:69`；
> 派发封装：`qbot_rpg/core/battle.py:2038 _dispatch_event`；归属作用域：`battle.py:2070 _owner_scope`。

| # | 时点 | 语义 | 何时派发（file:line） | 谁收（side） | 状态 |
|---|---|---|---|---|---|
| 1 | `battle_start` | 开战 | battle.py:2468(player) / :2469(enemy) | 两侧各一次 | ✅ 已接 |
| 2 | `battle_end` | 收尾（在 marks 清零前） | battle.py:2173 / :2174 | 两侧各一次 | ✅ 已接 |
| 3 | `action_start` | 一次行动开始 | battle.py:2962 | 行动者 | ✅ 已接 |
| 4 | `action_end` | 一次行动收尾 | battle.py:3021 / :3122 / :4061 / :4638 / :5047 | 行动者 | ✅ 已接（**多返回路径各自派发**，改战斗流程时勿漏） |
| 5 | `turn_start` | 行动者回合开始 | battle.py:2840 | 行动者 | ✅ 已接 |
| 6 | `turn_end` | 回合结束 | **无派发点** | — | ⛔ **故意不派发**：CTB 已删除"回合单位"（`docs/深度打造_实现说明.md:735`）；枚举保留仅为兼容 |
| 7 | `status_gain` | 状态施加成功 | effects.py:2257（`_dispatch_status_event`，def :2040） | 状态**持有侧** | ✅ 已接（status_apply 成功后） |
| 8 | `status_lose` | 状态消失/被驱散 | effects.py:2279（dispel 移除后） | 状态持有侧 | ⚠️ **部分**：驱散已接；**tick 过期 on_lose 待 snapshot 通道**（`记录.md:842`）；`on_expire` 映射到本事件（`event_dispatcher.py:74-76`） |
| 9 | `mark_gain` | 印记获得 | **无派发点** | 印记持有侧 | ⛔ 二期（`记录.md:842`）——`docs/框架_功能三…设计.md:120` 曾列为批3，实际未落 |
| 10 | `mark_lose` | 印记消失 | **无派发点** | 印记持有侧 | ⛔ 二期（同上） |
| 11 | `death` | **任一侧死亡** | battle.py:1133 | **死者自己** | ✅ 已接（唯一死亡判定点 `_death_check_side` battle.py:1114） |
| 12 | `revive` | 复活 | battle.py:1188 | 复活侧 | ✅ 已接（此前"无人派发"，现补） |
| 13 | `on_attack` | 普攻（伤害链） | **无派发点** | 攻击方 | ⛔ 二期（`记录.md:842`） |
| 14 | `on_hit` | 命中 | **无派发点** | 攻击方 | ⛔ 二期（同上）；设计意图见 `docs/审查参考/效果系统设计定稿.md:157`（特效伤害不进 on_attack，需 on_hit 显式配置） |
| 15 | `on_skill` | 技能 | **无派发点** | 攻击方 | ⛔ 二期（同上） |
| 16 | `season_change` | 换季 | battle.py:2034 / :2035 | 两侧 | ✅ 已接（`season_procs` 与 effects 通道**双轨**） |
| 17 | `on_kill` | **我击杀敌** | battle.py:1145 | **击杀者侧**（1v1 的另一侧） | ✅ 已接（批51 新增；`dead_mark` 门控，每次击杀恰好一次） |

**易混对（手册必须各给一个正/反例）**：

| 易混对 | 区别 | 判据来源 |
|---|---|---|
| `death` vs `on_kill` | `death` 派给**死者自己**（副作用的 target 相对死者侧）；`on_kill` 派给**击杀者**。"击杀回血/叠层/免冷却"写 `on_kill`；写 `death` 会挂到死者身上 | data/event_points.py:11-14；core/event_dispatcher.py:39-43；docs/深度打造_实现说明.md:744-752 |
| `status_gain` vs `mark_gain` | 状态（statuses）与印记（marks）是**两套容器**、两套动作（`status_apply` vs `mark_add`）；印记非增益/减益，驱散天然不命中印记（effects.py:2265-2267 注释） | effects.py:2265；`EFFECT_AXIS_SPECS.stack_cap_delta` consumer_note（gear_stats.py:325-326："marks.max_stack_of 半边未接，印记与状态两套容器"） |
| `turn_start` vs `action_start` | CTB 下单次"回合"被行动单位取代；`turn_end` 已废弃不派发，`action_end` 才有收尾 | docs/深度打造_实现说明.md:735；tests/ctb/test_ctb_contract_interfaces.py:285（断言 boundary ≠ turn_end） |
| `EVENT_POINTS` vs `[事件:XXX]` | 见 §3.0，两套体系 | core/event_bus.py:53；data/event_points.py:1-14 |

**尚未登记、已登记为后续批的时点**（手册的"未来扩展位"章节素材）：
`on_struck` / `on_block` / `on_crit` / `on_interrupt` / `on_cc` / `on_synergy`（`docs/深度打造_实现说明.md:794-796`：各自需要新派发点=行为改动，须单独批次测量）；`on_tick`（`core/event_dispatcher.py:30` 注明"二期收编，本期不接"）。

### 3.2 派发与归属规则

| 规则 | 内容 | file:line |
|---|---|---|
| 数据源 A | effects 条目 `trigger` 字段（值 ∈ EVENT_POINTS） | event_dispatcher.py:8-20, `TRIGGER_KEY:57` |
| 数据源 B | statuses 条目 `on_gain`/`on_lose`/`on_expire`（→ status_gain/status_lose） | event_dispatcher.py:21-27, `_STATUS_EVENT_KEYS:72-76` |
| 数据源 C | 装配注入 procs（`ctx_vars.procs`，可选） | event_dispatcher.py:28-29 |
| 符文候选 | `battle._rune_candidates(event, side)` 与该侧注册表候选合并（符文只对穿戴者生效） | battle.py:2043-2046, :2115-2142 |
| 归属过滤 | 两侧都无 `owned_effect_ids` → **全库扫描**（旧行为，逐字段零变化）；任一侧声明 → 该侧候选 = **自己拥有的 ∪ 未被任何一侧认领的（全局效果）** | battle.py:2048-2053, `_owner_scope:2070`；event_dispatcher.py:100-127 |
| 归属键 | combatant 键 `owned_effect_ids`（由装配层写：装备实例 `passives`→traits `effects`→id 集） | gear_stats.py:482-491 `OWNED_EFFECT_IDS_KEY`；docs/深度打造_实现说明.md:725-726, :754-763 |
| 安全失败 | 未注入 registry / 分派异常 → `[]`，不阻断战斗主流程 | battle.py:2065-2069；effects.py:2068 |
| 校验 | `trigger` 值 ∉ EVENT_POINTS → **黄提示 Y-19**（允许先行声明未来时点，但永不触发）；非字符串 → **红拦 R-1**；缺 trigger/空串 → 放行 | validator.py:3335-3380（覆盖 `effects.<idx>.trigger` 与 `runes.<idx>.effects.<j>.trigger`） |
| 去重/上限 | chance 三态 / 每行动每场上限 / 递归深度全部复用 `EffectRuntime`（`trigger_counts` 等），不另造 | event_dispatcher.py:30-33 |

---

## §4 扩展点

> 本节由只读盘点子任务产出（E1/E2/E3 + 包声明段）。行号已抽样核验（pack_ext.py:69/81/115/141/304/481、pack_render.py:319、ext_api.py:125、qbot_rpg_bridge/assemble.py:181/185）。

### 《框架扩展开发手册》盘点 · Part 4：扩展点 + 包声明段

> 仓库：`/root/QBot-TurnTellerRPG`（QQ 群文字 RPG 框架 `qbot_rpg` + 内容包 `content/`）。
> 本文为**只读盘点**，所有行号均经 `grep -n` / 读文件亲眼核实，未修改仓库任何文件。
> 权威方案文档：`docs/游戏包扩展点_方案_E.md`；作者文档：`docs/内容包扩展_指令.md`。

---

#### 0. 结论速览

| 入口 | 声明形状 | 框架装载入口 | 是否在 manifest 声明 |
|---|---|---|---|
| **E1 指令** | `content/<pack>/commands.json`（`commands[]`） | `load_pack_extensions()` @ `qbot_rpg/assembly/pack_ext.py:481`；装配接线 `qbot_rpg_bridge/assemble.py:181` | 否（独立于 `manifest.modules`） |
| **E2 渲染** | `content/<pack>/ext/render.py`（`EVENTS` + `render`） | `load_pack_render_hook()` @ `qbot_rpg/assembly/pack_render.py:319`；装配接线 `qbot_rpg_bridge/assemble.py:185` | 否 |
| **E2 文案覆盖** | `content/<pack>/templates.json`（key→模板串） | `resolve_templates()` @ `qbot_rpg/core/templates/__init__.py:101`；经 `assembly/context.py:727` | **是**（须声明 `templates` 模块，否则不加载） |
| **E3 测试** | `content/<pack>/tests/` | `scripts/run_pack_tests.py:168` → pytest + `qbot_rpg/testing/pytest_plugin.py` | 否 |
| **E3 构建** | `content/<pack>/scripts/build.py` | `scripts/run_pack_build.py:39,99` | 否 |

内容包扩展示例实证：`content/zz_probe_ext/`（E1+E2+E3 全量探针）、`content/zz_probe_packmeta/`（包声明段/展示元数据探针）、`content/veinborn/`（settings/templates/field_meta 真实大包）。

---

#### §A 扩展点契约

##### A.1 E1 指令（内容包自定义指令）

###### A.1.1 声明形状

- 声明文件固定名：`commands.json`（常量 `DECL_FILE = "commands.json"` @ `qbot_rpg/assembly/pack_ext.py:69`）。
- 顶层形态：`{"commands": [ … ]}`，由 `parse_declarations()` 解析（`pack_ext.py:304-328`）：顶层必须是对象（`:310`），`commands` 必须是数组（`:317`），缺省/空数组 = 无指令（`:314-316`）。
- 单条声明字段（允许键闭集 `_ALLOWED_KEYS` @ `pack_ext.py:81`）：

| 字段 | 类型 | 必填 | 约束（校验处 file:line） |
|---|---|---|---|
| `name` | str | 是 | 非空、无空白、无 `/`（`_is_token` @ `pack_ext.py:240`；校验 `:260`） |
| `handler` | str | 是 | 合法 Python 标识符（`:263-267`） |
| `aliases` | str[] | 否 | 每项同 `name` 约束（`:268-280`） |
| `usage` | str | 否 | 必须字符串（`:281-283`） |
| `help` | str | 否 | 必须字符串（`:284-286`） |
| `gm_only` | bool | 否 | 必须布尔（`:287-289`） |

未知字段 = 拼错，报错拒绝（`_validate_one` @ `pack_ext.py:257-259`），防静默失效。

实证：`content/zz_probe_ext/commands.json:2-11`（指令 `探针`，别名 `zzprobe`，handler `probe`，`gm_only:false`）。

###### A.1.2 装载路径（file:line）

| 环节 | 位置 |
|---|---|
| 常量：声明文件 / 实现目录 / 实现文件 | `pack_ext.py:69-71`（`commands.json` / `ext` / `commands.py`） |
| 双闸判定 | `pack_ext.py:115`（`settings.ext.enabled`）、`:125`（`--enable-pack-ext` / `QBotRPG_ENABLE_PACK_EXT`）、`:141`（合取） |
| 主入口（承诺不抛，失败降级） | `pack_ext.py:481-534` |
| 启用路径：读声明 | `pack_ext.py:570-580`（路径校验后读 `commands.json`） |
| 冲突预检 | `pack_ext.py:331-388`（对框架名/别名、包内自冲突） |
| 动态 import 实现 | `pack_ext.py:591-597`（`ext/commands.py`），import 函数 `:394-418` |
| handler 齐备性预检 | `pack_ext.py:599-604` |
| 构造 `CommandSpec` + 权限 | `pack_ext.py:606-620` |
| 原子注册 + 失败回滚 | `pack_ext.py:622-646` |
| 生产装配接线 | `qbot_rpg_bridge/assemble.py:180-183` |
| 测试辅助接线 | `qbot_rpg/assembly/testing_support.py:218-219` |
| 稳定 API 面（包代码唯一可 import） | `qbot_rpg/ext_api.py`（`__all__` @ `:42-56`；版本 `EXT_API_VERSION="1"` @ `:59`；未知名拒绝 `:307-312`） |
| handler 上下文 `ExtContext` | `ext_api.py:125-304`（工厂适配 `_make_handler` @ `pack_ext.py:430-464`） |

包内实现示例：`content/zz_probe_ext/ext/commands.py:11-22`（`def probe(ctx, parsed)`，只 `from qbot_rpg import ext_api`）。

###### A.1.3 约束

- **命名**：指令名/别名非空、无空白、无 `/`（`pack_ext.py:240-248`）；handler 必须为标识符（`:263`）。
- **分隔符**：包指令进入既有 `Router`，沿用框架指令解析器 `qbot_rpg/commands/parsers.py` 的全部分隔符/前缀模式（无包专属分隔符）。`CommandSpec(..., whitelisted=True)` @ `pack_ext.py:616`，故无需改 `parsers.DEFAULT_WHITELIST`。
- **权限**：`gm_only:true` → `PERM_GM`，否则 `PERM_USER`（`pack_ext.py:618`）。
- **可见性**：注册进 Router，帮助自动动态列出（`assembly/context.py` 注入 `registered_cmds`）。
- **重名一律拒绝**：与框架指令/别名、或包内自冲突 → **整包扩展降级不生效**，不做 `replace=True`（`pack_ext.py:331-388`、`:644`；方案 §五.1）。
- **路径安全**：禁 `..`、禁符号链接、解析后必须在包目录内（`_resolve_within` @ `pack_ext.py:185-213`）；只允许固定文件名（`resolve_ext_file` @ `:216`）。
- **双闸**：`settings.ext.enabled` **且** 启动参数/环境变量，缺省全关；未启用时**零文件访问**（`pack_ext.py:513-519`）。
- **失败隔离**：声明非法/路径非法/import 失败/handler 异常均不抛到顶层（`:453-461`、`:499-534`），handler 异常回退模板键 `ext_command_unavailable`（`:78`）。
- **能力最小 / 不热加载 / 不跨包互调 / 不改结算**：见 `ext_api.py:11-20`、`pack_ext.py:27`。

###### A.1.4 唯一源与备注

- 声明唯一源：包内 `commands.json`（无框架默认、无 registry 登记，`_ALLOWED_KEYS` 是唯一校验源 @ `pack_ext.py:81`）。
- 备注：`commands.json` **不在** `manifest.modules` 里；由 `load_pack_extensions` 独立读取。包声明与实现分离（声明纯数据 + `ext/commands.py` 代码）。

---

##### A.2 E2 渲染（战报/消息渲染扩展）

E2 有两条独立通道：**(2a) 渲染钩子 `ext/render.py`** 与 **(2b) 文案模板覆盖 `templates.json`**。

###### A.2.1 E2a：渲染钩子（`ext/render.py`）

**声明形状**（`pack_render.py:9-15`）：

```python
EVENTS = ("command.reply",)                 # 可选：事件白名单；缺省 = 全部已知事件
def render(event, data, default_text): ...  # 返回 None/"" = 用框架默认；返回 str = 替换
```

| 契约项 | 位置 |
|---|---|
| 实现文件固定名 `render.py` | `pack_render.py:73`（在 `ext/` 下） |
| 已知事件 `command.reply` / `battle.round` | `pack_render.py:83-85` |
| 事件白名单解析（未知事件警告+忽略，形态非法整包不装） | `pack_render.py:289-313` |
| 主入口 `load_pack_render_hook` | `pack_render.py:319-367` |
| 启用路径（路径校验→import→校验 `render`→解析 `EVENTS`） | `pack_render.py:370-404` |
| 钩子调用隔离（异常/超时/非 str → 默认文本） | `pack_render.py:181-266`（`RenderHook.apply` @ `:240`） |
| 软超时 0.5s（不做线程抢占） | `pack_render.py:75-80`；`_invoke` @ `:222-238` |
| 只读快照构造 `build_render_data` | `pack_render.py:134-175`（字段表 `:146-158`） |
| `ctx["sender"]` 直发代理 `RenderSender` | `pack_render.py:410-446` |
| `command.reply` 出口 | `qbot_rpg/assembly/runner.py:894-905`（前缀注入后、`Sender.send` 前） |
| `battle.round` 出口（仅声明该事件才代理） | `runner.py:841-852` |
| 生产装配接线 | `qbot_rpg_bridge/assemble.py:184-188` |

**覆盖优先级**：钩子拿到的是框架渲染好的**最终文本**（前缀注入之后），返回 str 替换、None/空用默认；异常/超时/非 str 一律落默认（`pack_render.py:240-266`）；只读快照不含活对象（`pack_render.py:102-131`）。

实证：`content/zz_probe_ext/ext/render.py:11-23`（`EVENTS=("command.reply",)`，后缀改写）。

###### A.2.2 E2b：模板覆盖（`templates.json`）

- 全量表唯一存储：`qbot_rpg/core/templates/template_table.json`（由 `core/templates/__init__.py:77-85` 加载，`DEFAULT_TEMPLATES` 见 `:36`）。
- 覆盖入口：`resolve_templates(content_overrides)` @ `core/templates/__init__.py:101-125`；只合并**已存在 key**，未知 key 逐键 warning（`strict=True` 抛错，运行时 `strict=False`）。
- 装配侧读取：`assembly/context.py:727-738`（`registry.modules_raw["templates"]` 覆盖），注入 `ctx["templates"]` @ `context.py:1336`（**无条件注入**）。
- 渲染统一入口：`render_template` @ `core/templates/__init__.py:128-141`（局部覆盖缺 key 回落默认表）；`tpl_of` @ `:144-152`。
- 运行时再次兜底：`ext_api.tpl` @ `qbot_rpg/ext_api.py:113-122`；`ExtContext.tpl` @ `:257-259`。
- 模块登记：`field_meta.py:3435-3442`（`ModuleMeta(entry_type="map", kind="templates", namespace="template_lib")`）。
- 目录澄清：`qbot_rpg/core/message_format/`（`battle_render.py` / `list_render.py` / `panel_render.py` / `prefix_render.py`）是**框架渲染器实现**，不是覆盖目录；渲染器统一经 `tpl_of(ctx, …)` 读模板（如 `battle_render.py:34`）。

**关键约束（易踩坑）**：`templates.json` 只有在该包 `manifest.modules` **声明了 `templates` 模块**时才被 loader 加载（`loader.py:286-311`），否则静默不生效。实测仅 `content/test_demo`、`content/veinborn` 声明了 `templates`。实证：`content/veinborn/templates.json`（4 个覆盖键）。

**覆盖优先级**：`包 templates.json` > `DEFAULT_TEMPLATES`（`template_table.json ∪ base`）。

---

##### A.3 E3 测试脚本（包内测试脚本）

###### A.3.1 包内测试 `content/<pack>/tests/`

| 环节 | 位置 |
|---|---|
| 测试目录发现 | `scripts/run_pack_tests.py:168`（`tests_dir = pack_dir / "tests"`） |
| pytest 命令构造（显式只收该包 tests/） | `run_pack_tests.py:78-101`（`--rootdir`、`-c pytest.ini`、`-p qbot_rpg.testing.pytest_plugin`、`--pack-root`） |
| 主入口 `run_pack_tests` | `run_pack_tests.py:140-200`（先 collect 取数，再真跑取退出码） |
| CLI | `run_pack_tests.py:221`（`main`；`--pack` / `--content-root` / `--` 透传） |
| pytest 插件 `--pack-root` | `qbot_rpg/testing/pytest_plugin.py:27-36`；`pack_root` fixture @ `:39-52`；`pack_deps` fixture @ `:55-62` |
| 框架测试辅助公开面 | `qbot_rpg/testing/__init__.py`（`pack_root_from` / `pack_app` / `send_command` / `load_pack_ext` / `load_pack_render` / `validate_pack_data`） |
| 辅助实现 | `qbot_rpg/assembly/testing_support.py`（`pack_root_from` @ `:78`，`MANIFEST_FILE` @ `:69`） |

隔离：主套件 `pytest.ini:3`（`testpaths = tests`）**不会自动收集**包测试；`run_pack_tests.py` 显式只收该包 `tests/`（`run_pack_tests.py:78-101`），并设 `PYTHONDONTWRITEBYTECODE=1` / 关 cacheprovider（`:62-75`）。

实证：`content/zz_probe_ext/tests/test_probe_ext.py:1-45`。

###### A.3.2 包内构建 `content/<pack>/scripts/build.py`

| 环节 | 位置 |
|---|---|
| 构建入口固定名 `build.py` | `scripts/run_pack_build.py:39`（`BUILD_ENTRY = "build.py"`） |
| 入口路径拼接 | `run_pack_build.py:99`（`pack_dir / "scripts" / BUILD_ENTRY`） |
| 主入口 `run_pack_build` | `run_pack_build.py:73` （cwd=包目录、PYTHONPATH 含仓库根、退出码如实转发） |
| CLI | `run_pack_build.py`（`--pack` / `--content-root` / `--check` / `--` 透传） |

实证：`content/zz_probe_ext/scripts/build.py:1-`（`--check` 只读校验 manifest/数据模块/commands.json handler 齐备 + 复用框架整包校验）。

---

##### A.4 hooks / 回调注册点全清单

> 说明：框架存在**两类** hook。①面向内容包作者的**扩展钩子**（E1/E2/`schema_ext`/`field_meta.json`）；②框架内部引擎间的**注入式回调/上下文钩子**（`ctx[...]`），内容包不直接注册，但构成包数据被消费的落点。以下逐一列出。

###### A.4.1 面向内容包的扩展钩子

| hook / 注册点 | file:line | 用途 | 谁调用 |
|---|---|---|---|
| E1 `load_pack_extensions(router, …)` | `qbot_rpg/assembly/pack_ext.py:481` | 把包 `commands.json` 声明注册进 Router | `qbot_rpg_bridge/assemble.py:181`、`assembly/testing_support.py:218` |
| E1 `Router.register(spec, replace=False)` | `qbot_rpg/commands/router.py:205` | 实际登记号；重名 `ValueError` | `pack_ext.py:630` |
| E1 `Router.unregister(name)` | `qbot_rpg/commands/router.py:215` | 失败回滚 | `pack_ext.py:643` |
| E1 `AliasTable.add/remove` | `qbot_rpg/commands/router.py:732` / `:741` | 包指令别名登记/回滚 | `pack_ext.py:634` / `:641` |
| E1 `qbot_rpg.ext_api` 稳定面 | `qbot_rpg/ext_api.py:42`（`__all__`）、`:59`（版本） | 包代码唯一允许 import 的面 | 包内 `ext/commands.py` |
| E1 `ExtContext.get_state/set_state/patch_state/clear_state` | `ext_api.py:283/291/296/301` | 包 × 玩家状态格子读写 | 包 handler |
| E2 `load_pack_render_hook(pack_dir, …)` | `qbot_rpg/assembly/pack_render.py:319` | 装载 `ext/render.py` | `qbot_rpg_bridge/assemble.py:185`、`testing_support.py:221` |
| E2 `RenderHook.apply(event, data, default)` | `pack_render.py:240` | 单出口文本替换+隔离 | `runner.py:895`、`pack_render.py:441`（RenderSender） |
| E2 `RenderSender`（`ctx["sender"]` 代理） | `pack_render.py:410` | 战斗正文直发也过钩子 | `runner.py:846-849` |
| E2b `resolve_templates(overrides)` | `qbot_rpg/core/templates/__init__.py:101` | 包 `templates.json` 覆盖全量表 | `assembly/context.py:738` |
| E2b `_templates_table(registry)` | `qbot_rpg/assembly/context.py:727` | 读 `registry.modules_raw["templates"]` → 合并 | `context.py:1336`（注入 `ctx["templates"]`） |
| 包自持校验 `settings.schema_ext` | `qbot_rpg/content/validator.py:429`（解析）、`:543-549`（接线 R-5） | 包声明 `allow_keys/type/enum/required` 扩展校验 | `_Checker.__init__` / `_check_module` 各字段点 |
| 包展示元数据 `field_meta.json` | `qbot_rpg/content/field_meta_pack.py:783`（`load_field_meta`）、`:700`（`parse_field_meta`） | 包覆盖字段 label/help/模块树/分组等展示层 | `qbot_rpg/web/api.py:239`（`_pack_declaration`）→ `_pack_meta_table` |
| 包模板键来源 | `field_meta.py:3435`（`key_source="templates"`）、`web/framework_keys.py` | 编辑器列出包模板键 ∪ 框架全量键 | 编辑器 `/api/meta` |

###### A.4.2 框架内部 hook / 回调注册点（引擎↔引擎）

| hook | file:line | 用途 | 谁调用 |
|---|---|---|---|
| `register_event_dispatcher(fn)`（effects 回调槽） | `qbot_rpg/core/effects.py:2025` | 注册状态事件分派回调（破循环依赖） | `qbot_rpg/core/event_dispatcher.py:332`（模块加载末尾） |
| `bump_event`（事件计数/环形日志） | `qbot_rpg/core/event_bus.py:196` | 事件打点：`longline_counters`+`event_counts`+`event_log` | `ctx["bump_event"]`（`context.py:1852`，`_resolve_bump_event` @ `:908`；dialog `_bump_events` 消费） |
| `ctx["add_item"] / remove_item / count_item` | `context.py:1106`（`_inventory_hooks`），返回键 `:1239` | 背包增/删/计（reward/shop 契约） | `context.py:1560` 展开注入；各引擎 |
| `ctx["resolve_item"] / resolve_shop / resolve_recipe / resolve_trait` | `context.py:1848-1851`（`_kind_resolver`）、`:1901`（`resolve_attr_final`） | registry 引用解析闭包 | 指令壳/引擎 |
| `ctx["consume_bait"] / mode / king_event / king_victory_record` | `context.py:1510-1513`（薄委托 `:623/:651/:665/:679`） | 钓鱼引擎回调 | `core/fishing.py` |
| `ctx["respawn_hook"]` | `context.py:1539`（`_respawn_hook_of` @ `:693`） | PVP 击杀惩罚回城 | `core/pvp.py` |
| `ctx["npc_interactions"]` | `context.py:1663` | NPC 交互菜单解析 | `core/dialog.py` |
| `ctx["start_battle"]` | `context.py:1754` | 调查遭遇开战 | `core/investigate.py` / `battle_launch_commands` |
| `ctx["sender"]`（统一发送出口） | `runner.py:845-852` | 战斗管线直发正文 | `battle_commands` / `BattlePipeline` |
| `ctx["resolve_player_name"] / same_group` | `context.py:1372-1373` | `/协力` 注入位（当前 None） | 协力指令 |
| `Router` 框架指令注册元组 `REGISTER_GROUPS` | `qbot_rpg/assembly/router_setup.py:96`（`build_router` @ `:225`） | 框架 40 组内置指令登记 | 装配 `build_router` |

---

#### §B 包声明段总清单

##### B.1 `manifest.json`（包清单，每包必有）

读取/校验：`qbot_rpg/content/loader.py:259`（文件定位）→ `:266`（JSON）→ `:282`（`Manifest.from_dict`）→ `:286-311`（按 `modules` 声明加载）；`validator.py:590-591` 把 `manifest` 当受检模块；框架 schema 唯一源 `qbot_rpg/content/field_meta.py:2154-2167`（字段表）+ `:3239-3242`（`ModuleMeta`）。

| 段名 | 用途 | 唯一源 file:line | 读取处 file:line | 可否被包覆盖 |
|---|---|---|---|---|
| `manifest.name` | 包显示名 | `field_meta.py:2155`；`models.py:743` | `loader.py:282`→`models.py:737-749` | 包自声明（该文件即包） |
| `manifest.version` | 包版本（供 `ctx.pack_version`） | `field_meta.py:2156`；`models.py:744` | `models.py:737-749`；`pack_ext.py:467-475` | 包自声明 |
| `manifest.schema_version` | 数据 schema 版本 | `field_meta.py:2157`；`models.py:740-741` | `models.py:737-749`；`registry.py:209` | 包自声明 |
| `manifest.author` | 作者 | `field_meta.py:2158`；`models.py:746` | `models.py:737-749` | 包自声明 |
| `manifest.modules` | **启用模块清单**（= `<module>.json` 文件名去后缀，决定 loader 加载哪些） | `field_meta.py:2159`；`models.py:738-739` | `loader.py:286-311`（未声明文件不加载；声明但缺失 → Y-6 黄提示继续） | 包自声明（换包零改动） |
| `manifest.module_tree` | 模块层级（编辑器左栏父子关系） | `field_meta.py:2162` | `field_meta_pack.py:715,287`；`web/api.py:300` | 可被 `field_meta.json.module_tree` **整体覆盖**（`field_meta_pack.py:35-37`） |
| `manifest.module_groups` | `module_tree` 别名 | `field_meta.py:2164` | 同上（`field_meta_pack.py:36-37`） | 可被 field_meta.json 覆盖 |
| `manifest.module_labels` | 模块中文名 | `field_meta.py:2166` | `field_meta_pack.py:713`；`web/api.py` | 可被 `field_meta.json.module_labels` **逐键覆盖**（`field_meta_pack.py:35-36`） |
| （扩展）`manifest.raw` | 原样保留整份 manifest | `models.py:734,748` | `registry.modules_raw["manifest"]`（`loader.py:314`） | 包自声明 |

> `module_labels` / `module_tree` 的字段定义位于 `field_meta.py:2162-2166`（在 `_module_table()` 内的 `manifest_fields`）。

##### B.2 `settings.json`（包设置）

**双通道读取**：① 作为普通模块被 loader 加载/校验（前提：`manifest.modules` 含 `settings`；实测除 `zz_probe_packmeta` 外所有包都声明）；② `qbot_rpg_bridge/assemble.py:89-98`（`_load_settings`）**无视 manifest 直接读 `settings.json`** 注入 `deps.settings`/`ctx["settings"]`。

框架 schema 唯一源：`qbot_rpg/content/field_meta.py:378`（`SETTINGS_FIELDS`）+ 各专项 `*_settings.py`；校验分派 `validator.py:864-898`（`_check_settings_1g4` @ `:1884` + 各专项）。

实测各包 settings 顶层段并集（`python3 -c` 枚举 `content/*/settings.json`）：

| 段名 | 用途 | 唯一源 file:line | 读取处 file:line | 可否被包覆盖 |
|---|---|---|---|---|
| `currencies` | 货币定义表 | `field_meta.py:384` | `validator.py:1905`（`_settings_currency_ids`）；`commands/alchemy_commands.py:448` | 包配置 |
| `death_penalty` | 死亡惩罚 | `field_meta.py:385` | `world/battle_boundary.py:356`；`commands/battle_commands.py:1370`；`validator.py:1898` | 包配置 |
| `default_map` | 默认地图 | `field_meta.py:382` | `assembly/context.py:1396`；`commands/register_commands.py:277`；`battle_commands.py:1387` | 包配置 |
| `world_name` | 世界名 | `field_meta.py:383` | `commands/register_commands.py:371` | 包配置 |
| `level_cap` | 等级上限 | `field_meta.py:3084` | `assembly/context.py:467,1416`；`register_commands.py:298` | 包配置 |
| `exp_curve` | 经验曲线 | `field_meta.py:3083` | `context.py:468`；`core/battle_reward.py:372` | 包配置 |
| `ctb` | 行动条（CTB）参数 | `field_meta.py:3081` | `commands/battle_launch_commands.py:491-493`；`dummy_commands.py:215-217`（`core/ctb_config.resolve_ctb_settings`） | 包配置 |
| `battle` | 战斗参数（`min_damage` 等） | `field_meta.py:3073-3078` | `core/battle_config.py:70`（`resolve_battle_settings`）；`battle_launch_commands.py:501` | 包配置（白名单键） |
| `alchemy` | 炼金/合成设置 | `field_meta.py:3047`；`content/alchemy_settings.py` | `commands/alchemy_commands.py:491,500`；`validator.py:897-898` | 包配置 |
| `forge` | 锻造设置 | `field_meta.py:3050`；`content/forge_settings.py` | `context.py`（`_forge_module_raw`→`ctx["forge"]`）；`forges_models` 校验 | 包配置 |
| `fishing` | 钓鱼设置 | `field_meta.py:3064`；`content/fishing_settings.py` | `content/fishing_models.py:271`；`commands/fishing_commands.py:229`；`core/fishing_settings.fishing_cfg` | 包配置 |
| `deep_craft` | 深度打造 | `field_meta.py:3056-3061` | `commands/alchemy_commands.py:1788`；`core/upgrade.py:144`；`core/craft_paths.py:95`；`core/jewel.py:396` | 包配置 |
| `affinities` | 相性定义 | `field_meta.py:618`（type=list） | `core/affinity.py`（`src.get(...)`）；`validator.py:3061-` | 包配置 |
| `affinity_pools` | 相性池 | `field_meta.py:628` | `core/affinity.py:118`；`validator.py:2945,3176` | 包配置 |
| `affinity_linkage` | 相性联动 | `field_meta.py:651` | `core/affinity.py:131`；`validator.py:3176` | 包配置 |
| `affinity_reactions` | 相性反应 | `field_meta.py`（相性段） | `core/affinity.py:133`；`deep_craft_commands.py:395`；`alchemy_core.py:853` | 包配置 |
| `effect_axes` | 特效轴声明 | `field_meta.py`（`effect_axes`） | `context.py:1879-1881`；`battle_launch_commands.py:510`；`data/gear_stats.py:477` | 包配置 |
| `slot_defs` | 装备部位定义 | `field_meta.py:391`（`slot_defs`） | `context.py:1862`；`commands/alchemy_commands.py:2090`；`core/jewel.py` | 包配置 |
| `command_aliases` | 指令别名 | `field_meta.py:3079`（软）/`ALIAS_CONFIG_KEY` @ `:84` | `assembly/router_setup.py:274`；`assembly/runner.py:177`；`basic_commands.py:2499` | 包配置 |
| `quest_board` | 委托板配置 | `field_meta.py:3085`（软） | `context.py:1473,1623`（`ctx["quest_board_cfg"]`） | 包配置 |
| `contest` | 品评会配置 | `field_meta.py:3080`（软） | `context.py:1475,1625`（`ctx["contest_cfg"]`） | 包配置 |
| `assistant` | 代工助手 | `field_meta.py:3069`（软） | `core/alchemy_helper.py:212-217` | 包配置 |
| `panel_budget` | 装备面板预算 | `field_meta.py:424` | `context.py:1870-1872`；`core/panel_budget.py:90` | 包配置（缺省不注入） |
| `monster_scaling` | 怪物数值倍率 | `field_meta.py:570` | `context.py:1874-1876`；`battle_launch_commands.py:460`；`core/panel_budget.py:91` | 包配置 |
| `events` | 事件文案/事件段 | `field_meta.py:3082`（软） | `core/event_bus.py:83`（`_events_section`）；`resolve_event_key` @ `:100` | 包配置 |
| `ext` | **E1/E2 扩展总开关** | 无 field_meta 登记；语义源 `pack_ext.py:115` | `pack_ext.py:119`；`pack_render.py:349`（经 `pack_ext_enabled`） | 包配置（缺省 false） |
| `schema_ext` | **包自持校验扩展** | `validator.py:390-402`（约束子集） | `validator.py:429`（`_parse_schema_ext`）、`:543-549` | 包配置 |
| `message_prefix` | 消息前缀 7 字段 | `field_meta.py:3129-3140` | `commands/prefix_wiring.py:123`；`validator.py:3435` | 包配置 |
| `conditional_rules` / `attr_types` | 条件加成 / 属性类型 | `field_meta.py`（`settings` 段） | `context.py:1393-1394,1417-1418` | 包配置 |
| `imprints` | 印记展示 | `field_meta.py`（`settings` 段） | `context.py:1419`；`commands/status_commands.py:354-372` | 包配置 |
| `worldtime` / `time_cycle` | 时间天气 | `field_meta.py:3090-3127`（`time_cycle`；`worldtime` 未登记字段表） | `qbot_rpg_bridge/assemble.py:164-166`；`core/worldtime.py` | 包配置（桥梁装配读取） |
| `pvp` | PVP 8 键 | `field_meta.py:3142-3155`；`core/pvp.py:32`（`PVP_SETTINGS_KEYS`） | `core/pvp.py:62` | 包配置 |
| `post_battle_recovery` | 战后恢复 | `field_meta.py:3160-` | `commands/battle_commands.py:1270-1271`；`validator.py:1949` | 包配置 |
| `effect_budget` | 特效强度预算 | `field_meta.py:447` | `data/gear_stats.py:152`；`validator.py:2167` | 包配置 |
| `equipment_offhand` | 副手开关 | `field_meta.py:407` | `context.py:1865-1867`；`commands/basic_commands.py:1496`；`validator.py:2008` | 包配置 |
| `overheal` | 过量治疗 | `field_meta.py:505`；`data/gear_stats.py:153` | `validator.py:2459`；`data/gear_stats.py` | 包配置 |
| `message_chunk_len` | 消息分段字节预算 | `commands/sender.py:133,162` | `assembly/runner.py:192`（`_message_chunk_len`） | 包配置 |
| `shortcut_max` | 快捷上限 | `commands/shortcut_commands.py:27,117` | `context.py:1470,1620` | 包配置 |
| `command_mode` / `require_at` | 前缀模式 / @ 要求 | `commands/parsers.py:83` | `assembly/router_setup.py:246-247` | 包配置 |
| `resource_pct` | 资源按百分比显示 | `field_meta.py:3233-3235` | `commands/status_commands.py:197-198` | 包配置 |
| `forge.decompose_rate`（遗留） | 分解回收率（**已废弃**，唯一源迁到 `alchemy.decompose_rate`） | 迁移黄提示 `validator.py:2582-2601` | 已无引擎消费 | 兼容键（黄提示不阻断） |

> 注：`field_meta.py:3068-3140` 是一批 `soft_label` 软段登记（`assistant/contest/ctb/events/exp_curve/level_cap/quest_board/...`），泛型校验短路；`field_meta.py:378` 是 `SETTINGS_FIELDS` 起点。各专项段另有 `content/*_settings.py` / `*_models.py` 作为校验唯一源。

##### B.3 其它包内 JSON（模块文件）

加载机制统一：`manifest.modules` 每个名字 → `content/<pack>/<name>.json`（`loader.py:286-311`）→ 进 `modules` 字典（键 = 模块名）→ `check_pack(modules)` 校验（`loader.py:315`）→ `_build_registry` 按 `_KIND_FOR_MODULE` 登记（`loader.py:96-128,150-202`）→ 经 `ctx["..."]` 或 `registry.modules_raw` 消费。

| 模块/文件 | 顶层键/形态 | 唯一源（field_meta） | 读取处 file:line | 可否被包覆盖 |
|---|---|---|---|---|
| `effects.json` | `list` | `field_meta.py:3243`（`kind="effect"`, ns=`effect_family`） | `loader.py:288`；`context._table_from_registry` | 包数据 |
| `statuses.json` | `list` | `field_meta.py:3253`（`kind="status"`） | 同上 | 包数据 |
| `marks.json` | `list` | `field_meta.py:3262` | 同上 | 包数据 |
| `skill_chains.json` | `list` | `field_meta.py:3267`（`chain_field="next"`） | 同上 | 包数据 |
| `action.json` | `list` | `field_meta.py:3278` | 同上 | 包数据 |
| `skills.json` | `list` | `field_meta.py:3289`（`kind="skill"`, ns=`skill_lib`） | `loader.py:159`；`context.py`（`ctx["skills"]`） | 包数据 |
| `jobs.json` | `list` | `field_meta.py:3310`（`kind="job"`） | `loader.py:163`；`ctx["jobs"]` | 包数据 |
| `items.json` | `list` | `field_meta.py:3319`（+ `ITEMS_ALCHEMY_FIELDS`/`ITEMS_FORGE_FIELDS`） | `loader.py:164`；`ctx["items"]` | 包数据 |
| `equipment.json` | `list` | `field_meta.py:3325` | 同上 | 包数据 |
| `traits.json` | `list` | `field_meta.py:3332` | 同上 | 包数据 |
| `recipe.json` | `list` | `field_meta.py:3338` | `loader.py:169`；`ctx["recipe"]` | 包数据 |
| `runes.json` | `list` | `field_meta.py:3344`（`kind="rune"`） | `loader.py:175`；`ctx["runes"]` | 包数据 |
| `proficiency.json` | `list` | `field_meta.py:3348` | `loader.py:170` | 包数据 |
| `slots.json` | `list` | `field_meta.py:1530`（`kind="slots"`） | `loader.py:171`；`validate_slots` @ `alchemy_settings.py` | 包数据 |
| `enemies.json` | `list` | `field_meta.py:3369` | `loader.py:189` | 包数据 |
| `maps.json` | `list` | `field_meta.py:3376` | `loader.py:190`；`validate_maps` @ `map_models.py` | 包数据 |
| `dungeon.json` | `list` | `field_meta.py:3386` | `loader.py:191`；`validate_dungeons` | 包数据 |
| `stats.json` | `map`（键=ID） | `field_meta.py:3390`（`kind="stat"`, ns=`stat_lib`） | `loader.py:117-120`；`ctx` 属性计算 | 包数据 |
| `formula.json` | `map`（键=ID） | `field_meta.py:3318`（`kind="formula"`, ns=`formula_lib`） | `loader.py:117-120`；`core/formula_loader.py` | 包数据 |
| `npc.json` | `list` | `field_meta.py:3395` | `loader.py:193`；`validate_npcs` | 包数据 |
| `shop.json` | `list` | `field_meta.py:3402` | `loader.py:199`；`validate_shops` | 包数据 |
| `quest.json` | `list` | `field_meta.py:3409` | `loader.py:200`；`validate_quests` | 包数据 |
| `checkin.json` | `list` | `field_meta.py:3416` | `loader.py:201`；`validate_checkins` | 包数据 |
| `achievements.json` | `list` | `field_meta.py:3422` | `loader.py:188`；`validate_achievements` | 包数据 |
| `conditional.json` | `object`（`{}`） | `field_meta.py:3427`（`kind="conditional"`） | `loader.py:195`；`condition_engine` | 包数据 |
| `templates.json` | `map`（key→模板串） | `field_meta.py:3435-3442`（`kind="templates"`, ns=`template_lib`） | **须在 manifest 声明**；`context.py:727-738` | **覆盖框架默认表** |
| `forge.json` | `object`：`schema_version`,`trees`,`sets?`,`augments?`,`settings?` | `field_meta.py:3050`（`forge_settings_meta`） | `loader.py:178`；`ctx["forge"]`（`context._forge_module_raw`） | 包数据 |
| `enhance.json` | `object`：`settings`,`cost`,`success_curve`/`temper`,`values`,`protect_stone` | `content/enhance_models.py` | `loader.py:182`；`ctx["enhance"]`（`_enhance_module_raw`） | 包数据 |
| `fishing.json` | `object`：`schema_version`,`species`,`king` | `field_meta.py:3064`（`fishing_settings_meta`） | `loader.py:185`；`ctx["fishing"]`（`_fish_module_raw` @ `context.py:608`，`raw.get("fishing")` @ `:617`） | 包数据 |
| `commands.json` | `object`：`commands[]` | `pack_ext.py:81`（`_ALLOWED_KEYS`）+ `:304` | `pack_ext.py:570-582`（E1，**不**走 loader/validator） | 包扩展声明 |

> 说明：`demo_*`/`veinborn` 中 `*_data.json`（如 `zz_probe_ext_data.json`、`zz_probe_gadgets.json`）是**任意自定义模块**，只要列进 `manifest.modules` 即按 list/object 泛型校验并进 registry（`loader.py:138` 缺省 `BaseDef` 回退），是「包自定义数据段」的机制。

##### B.4 `field_meta.json`（包展示元数据，编辑器层）

读取层：`qbot_rpg/content/field_meta_pack.py`（`FIELD_META_FILENAME` @ `:80`，允许顶层键闭集 `TOP_LEVEL_KEYS` @ `:84-115`，`parse_field_meta` @ `:700`，`load_field_meta` @ `:783`）；消费方 `qbot_rpg/web/api.py:239`。**不参与运行时 loader/validator**。

| 段名 | 用途 | 唯一源 file:line | 读取处 file:line | 可否被包覆盖 |
|---|---|---|---|---|
| `schema_version` | 声明版本（须 = 1） | `field_meta_pack.py:82`、`:689` | `:689-698` | 包声明 |
| `module_labels` | 模块中文名（逐键覆盖 manifest） | `field_meta_pack.py:86`、`:713` | `:713`；`web/api.py` | **覆盖 manifest** |
| `module_tree` | 模块层级（整体替换 manifest） | `field_meta_pack.py:87`、`:715` | `:715`、`:287` | **覆盖 manifest** |
| `field_labels` / `field_help` | 字段 label/说明（覆盖框架表同键） | `field_meta_pack.py:88-89` | `:713-`；`web/api.py` | 覆盖框架默认 |
| `group_labels` | 字段分组显示名 | `field_meta_pack.py:90` | 同上 | 覆盖框架默认 |
| `subgroup_labels` | 二级分组显示名 | `field_meta_pack.py:93` | 同上 | 覆盖框架默认 |
| `entry_merge` / `entry_merge_filtered` | 展示层条目聚合 | `field_meta_pack.py:94,111` | `web/api.py` | 包声明（纯展示） |
| `segment_pages` | 对象模块合并页 | `field_meta_pack.py:97` | `web/api.py` | 包声明（纯展示） |
| `id_prefix` / `id_width` | 新建 ID 前缀/宽度 | `field_meta_pack.py:100-101` | `web/api.py:3609` | 包声明 |
| `entry_presets` / `entry_presets_disable` | 条目预设模板/关闭 | `field_meta_pack.py:102-104` | `web/api.py:3580` | 包声明 ∪ 框架默认（`entry_presets.py`） |
| `entry_tree` | 条目级层级 | `field_meta_pack.py:107` | `web/api.py` | 包声明（纯展示） |
| `entry_groups` | 中栏条目分组 | `field_meta_pack.py:114` | `web/api.py` | 包声明（纯展示） |

实证：`content/zz_probe_packmeta/field_meta.json`（`module_labels` 覆盖 manifest 同名占位、`module_tree`、`field_labels`、`field_help`、`group_labels`）。

##### B.5 `commands.json`（E1 唯一声明段）

| 段名 | 用途 | 唯一源 file:line | 读取处 file:line | 可否被包覆盖 |
|---|---|---|---|---|
| `commands` | 包自定义指令数组 | `pack_ext.py:81`（字段闭集）、`:304-328`（解析） | `pack_ext.py:570-582` | 包声明（框架无默认） |

##### B.6 声明校验位置（框架侧）

- 整包校验入口：`qbot_rpg/content/validator.py:3870`（`check_pack`）→ `_Checker.run` @ `:588-593` → `_check_module` @ `:671`（专项分派 @ `:711-898`）。
- manifest 校验：`validator.py:590-603`（`manifest` 作为受检模块）+ `field_meta.py:3239`（`ModuleMeta`）。
- settings 校验：`validator.py:864-898`（`_check_settings_1g4` @ `:1884` + `check_settings_alchemy` @ `:897` + 各专项）。
- 模块登记一致性门禁：`loader.py:205-233`（`check_register_table_consistency` / `check_manifest_modules_registered`）。
- 包展示元数据校验：`field_meta_pack.py:700`（`parse_field_meta`，非法 → `PackFieldMetaError`）。
- E1 声明校验：`pack_ext.py:304`（`parse_declarations`）。
- E2 声明校验：`pack_render.py:289`（`_parse_events`）。

---

#### 缺口标注

##### 1. 无单一源（同一语义多副本 / 双通道）

- **`settings.json` 双读取通道**：`loader.py:286-311`（作为模块，受 `check_pack` 校验）与 `qbot_rpg_bridge/assemble.py:89-98`（`_load_settings`，无条件直读、**不经校验**）。若某包 `settings.json` 未列入 `manifest.modules`，运行时仍生效但**绕过校验**（`loader.py` 不会加载它）。
- **`module_labels` / `module_tree` 双声明位**：`manifest.json`（`field_meta.py:2162,2166`）与 `field_meta.json`（`field_meta_pack.py:86-87`）。覆盖规则写在 `field_meta_pack.py:35-37`，但两个文件的“唯一源”实际是两个。
- **`slot_defs`（settings 段）vs `slots.json`（模块）**：功能重叠，`module_catalog.py:87-99` 已显式登记 `overlap_with="settings.slot_defs"`。
- **`recipes` 命名不统一**：模块文件为 `recipe.json`（单数），`module_catalog.py:83` 展示名“配方”；任务描述中的 “recipes” 在实现里不存在该键。
- **`settings.*` 段唯一源分散**：`field_meta.py`（软段/结构）与各 `content/*_settings.py`、`content/*_models.py`（专项校验）并列，无单一登记表；`settings` 模块 `fields=_decorate_field_meta(SETTINGS_FIELDS)` @ `field_meta.py:3443` 只是其中一处。

##### 2. 只有代码、无文档（或文档缺项）

- `hooks` 一节中大量 `ctx[...]` 注入式回调（`add_item`/`resolve_item`/`consume_bait`/`respawn_hook`/`npc_interactions`/`start_battle` 等，`context.py:1106/1848/1510/1539/1663/1754`）**只在代码注释/docstring 里说明**，`docs/游戏包扩展点_方案_E.md` 未列；`docs/内容包扩展_指令.md` 面向 E1，未覆盖这些内部落点。
- `settings.schema_ext`（包自持校验扩展，`validator.py:390-549`）在方案 E 文档中未提及，属“批71·D1”代码内能力。
- `field_meta.json` 的大批展示键（`entry_merge_filtered`/`segment_pages`/`entry_tree`/`entry_groups`/`id_prefix`/`id_width`/`entry_presets`，`field_meta_pack.py:94-114`）主要靠 `field_meta_pack.py` 顶部 docstring + 编辑器文档，无独立《手册》条目。
- `message_chunk_len`（`commands/sender.py:133`）、`resource_pct`（`field_meta.py:3233`）等段无专门作者文档。

##### 3. 注释与实现不一致

- `resolve_templates` 注释写“**深合并**”（`core/templates/__init__.py:102`），实现却是**逐 key 整体替换**（`:113-119`，值为字符串）；对嵌套结构无深合并语义。
- `pack_ext.py:503` 注释承诺“未启用时零文件访问”，`pack_ext.py:505-519` 实现中 `pack_path = Path(pack_dir)` 在双闸判定前执行（`Path.name` 取包名），严格说先构造了 Path 但未 stat/read，属边界表述。
- `run_pack_build.py` 模块 docstring 写入口为 `content/<pack>/scripts/build.py`（与 `BUILD_ENTRY` @ `:39` 一致），但方案 E 文档 §三 E3（`docs/游戏包扩展点_方案_E.md:50`）只写“`build.py --check`”，未写明在 `scripts/` 子目录，与实现存在文档精度差。
- `settings.json` 是否必须列入 `manifest.modules`：`field_meta.py:3443-3446` 注释称“settings.json 为常驻模块（3h D-01）…loader 常驻加载归 3h/M 接线”，但 `loader.py:286-311` 实现是**仅按 manifest.modules 加载**（未声明即不加载），二者口径不一致（`zz_probe_packmeta` 即无 `settings`）。

##### 4. 兼容 / legacy 键

- `manifest.module_groups`：`module_tree` 的**别名**（`field_meta.py:2164`），保留兼容。
- `settings.forge.decompose_rate`：已废弃，`validator.py:2582-2601` 仅发黄提示 Y-21，指向唯一源 `settings.alchemy.decompose_rate`；引擎从不读取。
- `settings.alchemy` 内部 `assistant` 子段与顶层 `settings.assistant` 双路兜底（`core/alchemy_helper.py:212-217`），legacy 兼容读取顺序。
- `settings` 软段（`soft_label`）一大批（`field_meta.py:3068-3140`）为“包实有、原表未登记”的兼容放行，泛型校验短路。
- `content/veinborn/*.json.bak`（`enemies.json.bak`/`enhance.json.bak`/`equipment.json.bak`/`manifest.json.bak`/`settings.json.bak`）：非 `.json` 后缀，**不被 loader 读取**，属遗留备份文件，建议清理以免误认。
- `content/zz_probe_packmeta/manifest.json` 只有 3 个模块且无 `settings`，是验证“包声明段可裁剪”的最小样本。

---

*盘点完毕（只读）。产出文件：`/root/deliverables/_parts/part4_extpoints.md`*

---

## §5 权责边界与门禁

> 本节由只读盘点子任务产出（目录权责 + 28 条门禁）。行号已抽样核验（check_architecture.py:319、compare_field_meta_migration.py:320、loader.py:239、context.py:1256）。
> **主 agent 校正一处**：红拦门禁的精确落点 = `content/loader.py:239 build_pack()`（docstring 明写「任一红拦抛 PackLoadError」）+ `content/validator.py:1-30`（红拦 R-1~R-5 封闭清单，见 :12）；子任务原文写 `validator.py:27` 偏松，以本条为准。

### 第五部分：权责边界 + 校验器/门禁盘点

> 面向《框架扩展开发手册》。**只读盘点**，未修改仓库任何文件。
> 每条结论均以 `grep -n` / 读文件逐行确认，`file:line` 为 2026-09 当前工作树实际行号（相对仓库根 `/root/QBot-TurnTellerRPG`）。
> 说明：仓库根另有一批 `审查_*.md`、`记录.md` 为历史过程产物，不属框架/内容包/编辑器三者任一，本部分不纳入权责表。

---

#### A. 目录分层权责

##### A.1 `qbot_rpg/` 子目录权责表（9 个子目录 + 包根 + 外层桥接）

| # | 子目录 / 包 | 权责（一句话） | 关键入口 `file:line` | 归属 |
|---|---|---|---|---|
| 1 | `qbot_rpg/`（包根） | 平台无关核心包的元信息与**唯一对外稳定面** | 分层总述 `qbot_rpg/__init__.py:3-11`；稳定面 `qbot_rpg/ext_api.py:1-23`（`__all__` `:42-56`、`EXT_API_VERSION` `:59`） | 框架 |
| 2 | `qbot_rpg/assembly/` | **装配层**（最顶层，只组装不写业务）：loader→registry→GameWorld→world_state 接线、Router 全指令注册、processing 驱动与发送出口、内容包 `ext/`（指令/渲染）通用装载、包内测试辅助面 | `assembly/__init__.py:1-5`；`assembly/bootstrap.py:40`（`bootstrap`）、`:60`（游玩门禁）、`:78`（`save_world_state`）；`assembly/router_setup.py:1-6`（`build_router`）；`assembly/runner.py:1-40`（RA-08 全链路）；`assembly/pack_ext.py:481`（`load_pack_extensions`）；`assembly/pack_render.py:1-33`（E2 渲染钩子）；`assembly/testing_support.py`（包测试辅助，经 `qbot_rpg.testing` 转出 `qbot_rpg/testing/__init__.py:28-42`）；`assembly/context.py`（`make_context` 工厂） | 框架 |
| 3 | `qbot_rpg/commands/` | **唯一 NoneBot 接触点**（壳层）：指令注册/路由/解析/权限/错误翻译/CQ 转义/分条发送、幂等与 per-player 队列 | `commands/router.py:194`（`Router`）、`:201`（`register`）；`commands/parsers.py:107`（`DEFAULT_WHITELIST`）；`commands/processing.py:252`（`process_message`）；`commands/sender.py`；`commands/errors.py` | 框架 |
| 4 | `qbot_rpg/content/` | **内容包模型与校验**：loader/validator/registry/hot_reload、字段元数据、包展示元数据读取、原子写盘、权限、包保护、包导出导入、模块目录/预设 | `content/loader.py:239`（`build_pack`）、`:349`（`load_pack`）；`content/validator.py:27`（`check_pack`）；`content/registry.py:1-12`；`content/field_meta.py:1-25`；`content/field_meta_pack.py:1-10`（包 `field_meta.json` 解析层）；`content/models.py`（`FieldMeta`/`ModuleMeta`）；`content/hot_reload.py:120`（`HotReloadWatcher`）、`:194`（`reload`）；`content/atomic_store.py:1-40`；`content/permission_store.py:1-40`；`content/pack_protection.py:27`（`enforce_play_gate`）；`content/pack_transfer.py:1-33`；`content/module_catalog.py:68`（`FRAMEWORK_MODULE_CATALOG`）；`content/entry_presets.py:52`（`FRAMEWORK_ENTRY_PRESETS`） | 框架 |
| 5 | `qbot_rpg/core/` | **纯规则引擎**：战斗/伤害/成长/背包/装备/时间/公式/效果分派 + `message_format` 纯字符串渲染 + 全量消息模板表 | `core/__init__.py:1`；`core/battle.py`；`core/damage.py`；`core/event_dispatcher.py`；`core/message_format/`；`core/templates/__init__.py:1-15`（全量表唯一存储，`content/<pack>/templates.json` 深合并覆盖 `:6`） | 框架 |
| 6 | `qbot_rpg/data/` | **领域模型唯一落点**（最底层，仅标准库）：`Player`/`BattleSnapshot`/`StatusInstance`/`ItemInstance`/`WorldState` 等；键空间常量（`gear_stats`/`event_points`/`affinity_keys`） | `data/__init__.py:1-5`；`data/player.py`；`data/battle.py`；`data/status.py`；`data/item.py`；`data/world_state.py`；`data/gear_stats.py` | 框架 |
| 7 | `qbot_rpg/storage/` | **SQLite 持久化**：连接队列/事务/迁移/幂等/回收/round-trip；玩家存档、会话、世界状态、内容包状态格子 | `storage/__init__.py:1`；`storage/repository.py:1-12`；`storage/schema.py:176`（`player_pack_state` 每 玩家×内容包 一格、框架零包名）；`storage/migrations.py`；`storage/pack_state.py`；`storage/pending.py` | 框架 |
| 8 | `qbot_rpg/testing/` | **测试基建（对外公开面）**：内容包自带测试可用的通用辅助 + pytest 插件 | `testing/__init__.py:1-24`（`pack_root_from`/`pack_app`/`send_command`/`validate_pack_data`）；`testing/pytest_plugin.py:1-11`、`:27`（注册 `--pack-root`）；实现落 `assembly/testing_support.py`（`testing/__init__.py:6`） | 框架 |
| 9 | `qbot_rpg/web/` | **编辑器外壳（只读元数据层 + 写入层）**：把包元数据翻译成界面 JSON；保存/回退/级联；CSV；框架键集合 | `web/__init__.py:1-6`；`web/api.py:1-22`（只读层，`_pack_dir` `:171`、`list_packs` `:749`、`list_modules` `:817`、`list_entries` `:1112`）；`web/editor_ops.py:1-23`（`save_entry` `:671`、`copy_framework_override` `:787`）；`web/csv_ops.py`；`web/framework_keys.py:51`（`register_key_source`） | 框架（编辑器外壳） |
| 10 | `qbot_rpg/world/` | **世界与场景**：全局世界状态（地图/怪物池/野图 BOSS/全体限购）、会话互斥、刷新、追击、副本持久化 | `world/__init__.py`；`world/game_world.py:1-18`（`GameWorld`）；`world/session.py`；`world/spawn.py`；`world/spawn_weather.py`；`world/chase.py`；`world/dungeon_persist.py` | 框架 |
| 11 | `qbot_rpg_bridge/`（仓根，**不在 `qbot_rpg/` 内**） | **NoneBot 部署桥接**：把框架装配成可运行 deps 注入插件；环境变量配置；`on_startup` 接线 | `qbot_rpg_bridge/assemble.py:1-21`；`qbot_rpg_bridge/plugin.py` | 框架（外层壳） |

> 子目录计数 = **9**（assembly/commands/content/core/data/storage/testing/web/world），另有包根与外层桥接 2 处。

##### A.2 三类角色：框架 / 内容包 / 包自持代码

**（1）框架** —— 外部开发者不应改；修改需走评审（R6「新增能力先放对层，放错层=架构缺陷」）。

- 范围 = `qbot_rpg/**`（含 `qbot_rpg_bridge/**`）、`scripts/**`、`tests/**`。
- 依据：`docs/审查参考/RPG回合制框架设计文档.md:20-33`（§1.2 框架=机制代码 / 内容包=纯 JSON 配置）；`docs/审查参考/开发规则文档.md:50-54`（分层铁律 + 依赖单向 + 放错层评审拦截）；`:129`「内容包 = 纯 JSON 配置（`content/<pack_id>/`）」。
- 框架内**禁止写死具体内容包名/业务键**：`qbot_rpg/web/api.py:20`（「本文件不得出现任何内容包的模块名或业务字段名」）、`editor_ops.py:20`（「本层零业务字段名」）、`storage/schema.py:176`（框架不认任何具体 `pack_id`）。

**（2）内容包** —— `content/<包>/**`，主体是 JSON 数据；包作者/编辑器可改。

- 形态：`manifest.json`（模块声明）+ 每模块一个 `<模块>.json` + 可选 `settings.json`/`field_meta.json`/`templates.json`。依据 `docs/审查参考/RPG回合制框架设计文档.md:370-404`（§4.1 内容包结构）、`:427-445`（manifest 模块声明规则：不声明=不加载）；`docs/编辑器使用说明.md:514-516`。
- 加载入口：`content/loader.py:239` `build_pack`（读 manifest → 按声明顺序 → 校验 → registry）。**未声明的文件存在 → 不加载**（`docs/审查参考/开发规则文档.md:135`；`docs/审查参考/RPG回合制框架设计文档.md:445`）。
- 实例：`content/veinborn/`、`content/test_demo/`、`content/zz_craft_demo/` 等均为纯 JSON 包（`content/veinborn/` 仅 `*.json` + `*.json.bak`，无 `ext/`）。

**（3）包自持代码** —— 包内 `ext/`（可执行扩展）、`tests/`（包自带测试）、`scripts/`（包自带构建管线）。**默认关闭、可选启用**。

| 形态 | 约定路径 | 装载方式 | 实证 `file:line` |
|---|---|---|---|
| 指令扩展 | `content/<pack>/commands.json` + `content/<pack>/ext/commands.py` | 装配时 `load_pack_extensions()` 读声明→校验重名→动态 import；**双闸**（`settings.ext.enabled` **且** `--enable-pack-ext`/`QBotRPG_ENABLE_PACK_EXT`）；未启用时**完全不读 ext/**、不 import 任何包内 Python | `assembly/pack_ext.py:8-11`（约定）、`:69-71`（`DECL_FILE`/`EXT_DIR`/`IMPL_FILE`）、`:141-153`（`pack_ext_enabled` 双闸）、`:481-519`（主入口/未启用直接返回）、`:185-213`（路径约束：禁 `..`/符号链接/逃逸） |
| 渲染钩子 | `content/<pack>/ext/render.py`（`EVENTS` + `render(event,data,default_text)`） | `load_pack_render()`；只许改文本、只读快照、异常落默认；**同一双闸** | `assembly/pack_render.py:1-33`（边界）、`:27-29`（双闸） |
| 包自带测试 | `content/<pack>/tests/`（pytest 风格） | `scripts/run_pack_tests.py --pack <名>` 以该包为内容根跑该目录；显式只收该目录，主套件不自动收集；只 import `qbot_rpg.ext_api` + `qbot_rpg.testing` | `scripts/run_pack_tests.py:1-23`（约定/隔离）、`:168`（`tests/` 目录判定）；`qbot_rpg/testing/__init__.py:1-23`；`qbot_rpg/testing/pytest_plugin.py:1-11` |
| 包自带构建 | `content/<pack>/scripts/build.py`（须支持 `--check`） | `scripts/run_pack_build.py --pack <名> [--check]`；框架只认入口、不规定内部结构；退出码如实转发（`exit 3`→`exit 3`） | `scripts/run_pack_build.py:1-23`（约定）、`:39`（`BUILD_ENTRY="build.py"`）、`:99`（入口判定） |

- **实际目录结构（唯一同时具备三者的包）**：`content/zz_probe_ext/` —— `content/zz_probe_ext/commands.json`、`ext/commands.py`（`probe` handler）、`ext/render.py`（`EVENTS=("command.reply",)`）、`scripts/build.py`（`--check` 只读校验）、`tests/test_probe_ext.py`（`pkt.pack_root_from` / `pkt.pack_app` / `pkt.send_command`）。对应 `content/zz_probe_ext/tests/test_probe_ext.py:1-48`、`content/zz_probe_ext/scripts/build.py:1-140`、`content/zz_probe_ext/ext/commands.py:12-20`、`content/zz_probe_ext/ext/render.py:11-22`。
- **展示元数据探针包**：`content/zz_probe_packmeta/`（`field_meta.json` + `manifest.json`，验证「新包自带中文名、编辑器/框架零改动」）。依据 `docs/编辑器重写_需求与约束.md:15`（补二·契约出处）、`docs/编辑器重写_数据包展示元数据下放方案.md:128`。
- 装载安全成文：`docs/游戏包扩展点_方案_E.md:5`（定位：框架=引擎与契约 / 内容包=数据+可选扩展代码 / 编辑器=通用工具）、`:38-39`（包代码只许 import `ext_api` 稳定面）、`:53-58`（装载安全五条：默认关闭/信任模型/路径约束/能力约束/失败隔离）、`:69-75`（明确不做：不覆盖框架指令、不改结算、不热加载、不跨包互调）。
- 稳定面声明：`qbot_rpg/ext_api.py:1-23`（「其余 `qbot_rpg.*` 都是内部实现，不承诺兼容」；不提供网络/子进程/任意文件系统/热加载/跨包互调）。

##### A.3 编辑器（web/）与框架、内容包：谁能改什么

| 角色 | 能改 | 不能改 / 硬约束 | 依据 `file:line` |
|---|---|---|---|
| **编辑器（`qbot_rpg/web/`）** | 只读遍历内容包并渲染界面；经 `save_entry` 写**内容包目录内**的 `<模块>.json`（+ `.bak`、原子写） | 不新写校验规则（复用唯一入口 `check_pack`）；不写框架代码；不写框架自有文件路径；不硬编码任何包名/模块名/业务字段；框架关键模板默认项**只读**（须「复制为包覆盖」） | `web/editor_ops.py:1-23`（唯一写入链路 + 复用校验）、`:12`（复用 `content.validator.check_pack`）、`:20`（零业务字段名）、`:70-90`（`_framework_locked` + `FRAMEWORK_LOCK_MESSAGE`）、`:671`（`save_entry` 框架锁分支）；`web/api.py:1-22`（只读层铁律）、`:164-178`（`_check_component` 防路径穿越 + `_pack_dir` 校验 manifest）；`api.py:66`（`_FRAMEWORK_DEFAULT` 哨兵）、`:1050`、`:1095`、`:1172`（框架默认键标「默认（框架）」） |
| **框架（`qbot_rpg/**`）** | 提供机制/稳定面/门禁；读内容包数据 | 不写死包名/业务键；不 import `content/` 具体包；不放错层（架构门禁） | `web/api.py:20`；`storage/schema.py:176`；`docs/审查参考/开发规则文档.md:50-54`；`docs/细化/细化_3a_架构分层契约.md:59`（R3）、`:62`（R6） |
| **内容包（`content/<包>/**`）** | JSON 数据、包声明（`manifest.json`/`settings.json`/`field_meta.json`/`templates.json`）、可选 `ext/`+`tests/`+`scripts/` | 不改框架代码；不覆盖框架指令名；包代码不改结算；不跨包互调；不得让框架给 `players` 表加包专属列 | `docs/游戏包扩展点_方案_E.md:69-75`；`docs/存档格子_内容包作者用法.md:104-109`（不要框架加专属列 / 不跨包读写）；`assembly/pack_ext.py:331-388`（重名一律拒绝、不 `replace=True`） |

**编辑器边界成文出处**：

- `docs/编辑器重写_需求与约束.md:9-16`（第〇节最高优先级原则：编辑器=通用工具，禁止把单包业务写死；判据「换成另一个包，编辑器零改动可用」）。
- `docs/编辑器重写_需求与约束.md:64`（「框架代码不得写死任何包名/业务键」）、`:172`（纪律：真实内容包内不得由测试/验收脚本写 `field_meta.json`）。
- `docs/编辑器使用说明.md:526`（「改的是 `content/<包名>/field_meta.json` 与数据文件，**不是编辑器代码**」）。
- `docs/审查参考/RPG回合制框架设计文档.md:42`（设计原则 4「编辑器即内容：编辑器直接读写 `content/` 目录，保存即生效（热重载）」）。
- `docs/编辑器重写_数据包展示元数据下放方案.md:85`（形态非法报错含包名+出错键）、`:128`（零改动证明：本批未改 `qbot_rpg/` 与 `scripts/`）。

---

#### B. 校验器 / 门禁清单

##### B.1 门禁表

> 失败后果口径：脚本类门禁「exit≠0」；pytest 类门禁「用例红」；加载/写入链路类门禁「结构化拒绝 + 人话 + 不落盘/不装载」。

| # | 门禁名 | 把关点 `file:line` | 检查什么 | 失败会怎样 | 保护什么 |
|---|---|---|---|---|---|
| 1 | **架构门禁 G0 · TC-03**（依赖方向/无环/叶子层） | `scripts/check_architecture.py:319`（`check_tc03`，主流程 `:440`）；依赖矩阵 `:31-47`；层判定 `:107-113`；边收集 `:269-316` | `qbot_rpg` 全包 import 图：① `commands`/`web` 不被任何层 import；② `core/world/storage/content/data` 之间无环（Kahn 拓扑）；③ 跨层依赖方向符合 §1.4 矩阵；④ `assembly` 顶层豁免；⑤ `TYPE_CHECKING`/常量假分支不计边 | `ARCH-FAIL` + 违规清单，`exit 1` | 分层铁律 R3 / D-05；防循环 import、防底层反向依赖 |
| 2 | **架构门禁 G0 · TC-01**（零 NoneBot 五层） | `scripts/check_architecture.py:167`（`check_tc01`）；扫描层 `:29`；nonebot 检测 `:140-164` | `core/world/storage/content/data` 全部 `.py` 无 `import nonebot`（含 `ImportFrom`、`importlib.import_module`/`__import__` 动态形态） | `exit 1` | R1「引擎层可脱离 NoneBot 单测」 |
| 3 | **架构门禁 G0 · TC-02**（commands 唯一适配器） | `scripts/check_architecture.py:189`（`check_tc02`） | 全仓 import nonebot 的文件只允许在 `qbot_rpg/commands/` 内 | `exit 1` | R2「commands 唯一 NoneBot 接触点」 |
| 4 | **架构门禁 G0 · TC-04**（领域类型唯一性） | `scripts/check_architecture.py:381`（`check_tc04`）；必需类型 `:49-51` | `Player/BattleSnapshot/StatusInstance/ItemInstance/WorldState` 各定义一次、均在 `data/`、且 `dataclass(frozen=True)` | `exit 1` | D-03 / U1 领域类型唯一落点 |
| 5 | **架构契约镜像测试** | `tests/contract/test_g0_architecture.py:24`（`test_g0_subprocess_exit0`）、`:33`（零 nonebot）、`:49`（commands 白名单） | 以 subprocess 跑 `check_architecture.py` 断言 exit 0 + `ARCH-OK`；并复用其纯函数做静态断言 | 用例红（pytest） | 让架构门禁随主测试套件被回归 |
| 6 | **字段元数据迁移门禁**（重定基线对拍） | `scripts/compare_field_meta_migration.py:320`（`DEFAULT_BASELINE_REF = "07293ee"`）、语义 `:20-31`、对拍 `_diff`/`compare_snapshots`；自证测试 `tests/unit/test_editor_pack_field_meta_migration.py:1-28` | 用 `git worktree` 检出基线树，两侧各跑 `editor_readonly_snapshot.py` 逐字段对拍：① 删除任一项→红；② 值变化→红（`control/widget/block_layout/number_step` 派生展示键记 soft）；③ 新增→允许但逐条列出；④ `label/help/group` 与模块声明 `module_labels/module_tree` **严格相等**（增/删/改全红） | `exit 1`（硬差异 > 0） | 「JSON 字段名=公共 API」的向后兼容（`docs/审查参考/开发规则文档.md:68`）；防迁移/重构静默改删字段 |
| 7 | **迁移脚本幂等门禁** | `scripts/migrate_pack_field_meta.py:46-...`（`--check` 只比对不落盘，不一致 `exit 1`）；基线 `:43` | 磁盘包 `field_meta.json` 与「基线框架表导出」逐节点一致（幂等、确定性排序） | `exit 1` | 包展示元数据下放的**可重复导出**，防手改漂移 |
| 8 | **零包名门禁（后端源码）** | `tests/unit/test_editor_batch8_modules.py:272`（`test_catalog_source_has_no_real_pack_names`）、`:279`（`test_editor_code_has_no_pack_names`：检查 `web/api.py`/`web/editor_ops.py`/`scripts/editor_host.py`） | 框架/编辑器/模块目录源码不得出现 `veinborn`/`test_demo` 等真实包名；模块目录条目只含 module/label/purpose/entry_type/requires | 用例红 | 「编辑器=通用工具、换包零改动」最高原则 |
| 9 | **零包名门禁（预设源 + 前端预设区）** | `tests/unit/test_editor_batch65_module_presets.py:357`（预设源不得含 `veinborn/test_demo/cloudsea`）、`:435`（前端 `presetCardHtml`/`renderModulePresets`/`onApplyModulePreset` 源码不得含模块键/包名） | 推荐组合后端预设源 + 前端预设渲染区源码零包名/零硬编码模块清单（数据全来自后端） | 用例红 | 换包零改动、前端不写死模块列表 |
| 10 | **零包名门禁（换包验收脚本自身）** | `tests/unit/test_editor_pack_switch.py:153`（`test_script_hardcodes_no_pack_or_business_name`） | 对 `scripts/editor_verify_packs.py` 动态发现的每个真实包 id、及禁用业务名，断言脚本源码不含其字面量 | 用例红 | 验收脚本不写死包名（否则「换包零改动」自证失真） |
| 11 | **框架零包名红线（批71 成文）** | `CHANGELOG.md:17-18`（批71「包专属残留清理…框架零包名红线」）；实现为**包声明驱动 + 框架读取 + legacy 兜底** | 框架不得内联具体包的业务文案/状态 id/面板 id/条件过滤；改由包 `templates.json`/`statuses[].stance=="air"`/`settings.*` 声明 | 无独立全局扫描脚本；由 8/9/10 三处测试 + 人工评审承载（见缺口 C.2） | 框架与内容包解耦；框架升级不绑死某个包 |
| 12 | **统一检查入口 `check_all.py`** | `scripts/check_all.py:100`（`main`）、`:123`（全量→`run_all_tests`）、`:129-136`（默认 静态+架构+内容包+单测）、`:132`、`:134`；报告 `:164` | 调度 ruff/mypy、架构门禁、`check_m7_content`、单元测试、`verify_mN`；结果归档 `docs/verify/check_report.md` | 有任一失败 → `exit 1`；报告写盘 | 单一下发点，防各门禁口径分裂 |
| 13 | **全量回归 `run_all_tests.py`** | `scripts/run_all_tests.py:1-30`（阶段定义）、`:244`（阶段0 ruff+mypy）、`:219`（阶段3 覆盖率）、`:59-63`（阶段2 严格里程碑依赖序 m0→m6） | 阶段0 lint → 阶段1 pytest 金字塔(unit/contract/e2e/fault) → 阶段2 `verify_m0~m6`(+M9 段) → 阶段3 `core`+`content` 各 ≥80% 行覆盖；阶段0 失败仅置 fail、后续继续收集 | 任一阶段失败 → `exit≠0` | 里程碑验收的唯一官方回归入口；`CI` 直接调用本入口保证本地/CI 同口径 |
| 14 | **ruff 门禁（静态，含存量基线）** | `pyproject.toml:22-29`（`line-length=100`、`select=["E","F"]`）、`:31-214`（`per-file-ignores` 存量豁免）；执行 `scripts/run_all_tests.py:251`、`scripts/check_all.py:74-85` | E/F 组规则；无全局 ignore E501；存量问题文件级豁免，**清单外新增必拦** | `ruff` 非 0 → 阶段0 fail → `exit≠0` | 代码风格/未用导入/未定义名；新增代码零豁免 |
| 15 | **mypy 门禁（静态，含存量基线）** | `pyproject.toml:216-225`（non-strict + `warn_unused_ignores`/`warn_redundant_casts` + `explicit_package_bases`/`namespace_packages`）；执行 `run_all_tests.py:251` | 全仓类型检查；存量按行内 `# type: ignore[码]` 逐处标注 | 非 0 → 阶段0 fail | 类型标注纪律（`docs/审查参考/开发规则文档.md:71-74`） |
| 16 | **lint/type 基线清单门禁** | `docs/verify/lint_baseline.md:1-15`（口径）；基线文件 `qa_ctb_baseline_ruff.txt`（66 行）、`qa_ctb_baseline_mypy.txt`（Success）；`scripts/verify_ctb.py:1-30`（集合差比对） | CTB 门禁按「(文件:行:列)→错误码」指纹化取集合差：基线有当前无=修复（允许），当前有基线无=**新增 FAIL** | `scripts/verify_ctb.py` 任一 FAIL → `exit 1` | 基线比对防「数量持平但换了位置」的假绿 |
| 17 | **CI 流水线门禁** | `.github/workflows/ci.yml:12`（name）、`:14`（push/PR 触发）、`:34-39`（建 `.venv`+依赖）、`:46-47`（调 `run_all_tests.py` 全量）、`:50-55`（归档 `docs/verify/`） | CI 直接调用本地同一全量入口（含 LNT 快速门 + COV 阈值），**不自定义第二套阈值**；任一 step 失败即 job 失败 | job 失败（GitHub Actions） | 代码合入前的强制质量门；CI/本地口径一致 |
| 18 | **内容包校验器（红/黄二分）** | `qbot_rpg/content/validator.py:1-29`（§2.1 红拦 R-1~R-5 封闭清单）、`:27`（`check_pack`）；接线 `content/loader.py:239`（`build_pack`）→ `:332`（`_raise_if_blocked`）→ `:349`（`load_pack`） | 红拦仅 5 类：类型错误/负数/非数字/引用不存在/结构错误（含死配置）；黄提示数值范围等**不阻断**；字段口径来自 `field_meta.py` 唯一数据源 | 红拦 → `PackLoadError`，**整包拒绝挂载**、registry 保持原状；黄提示 → 可加载但进 warnings | 「只建议不限制」哲学 + 防坏包半套运行 |
| 19 | **数据包保护游玩门禁** | `qbot_rpg/content/pack_protection.py:27`（`enforce_play_gate`）、`:1-13`（语义）、`:38`（`PackProtectionError`）；调用点 `assembly/bootstrap.py:60`；玩家侧拦截 `assembly/runner.py:9` | `settings.pack_protection.enabled` 开启时：进入游玩前跑既有 `build_pack` 校验；红拦拒绝；并把既有 Y-6（声明缺文件）在保护期升级为阻断 | `PackProtectionError` → 拒绝进入游玩（人话：哪个包/什么问题/去哪改）；玩家指令被拦 | 作者更新半成品包期间不破坏玩家体验；**不新增第二套校验逻辑**、不影响编辑器 |
| 20 | **内容包扩展双闸门禁** | `assembly/pack_ext.py:141-153`（`pack_ext_enabled` = 两闸合取）、`:115-122`（闸1 `settings.ext.enabled` 缺省 false）、`:125-138`（闸2 CLI/ENV）、`:514-519`（未启用直接返回、零文件访问）；渲染侧 `assembly/pack_render.py:27-29` | ① 包 `settings.ext.enabled` 且 ② `--enable-pack-ext`/`QBotRPG_ENABLE_PACK_EXT` **同时**为真才装载 `ext/`；否则完全不读包内 Python；重名/路径/import/注册失败→整包降级不生效 | 未启用=无该扩展；启用后失败=`PackExtResult(ok=False)` + 日志，机器人照常启动 | 默认安全（执行第三方代码需显式双开关）；包扩展失败不拖垮框架/其它包 |
| 21 | **编辑器框架关键模板只读门禁** | `web/editor_ops.py:70`（`_framework_locked`）、`:79-90`（`_framework_lock_error`）、`:671`（`save_entry` 命中即 red 返回、零文件改动）；哨兵 `web/api.py:66`（`_FRAMEWORK_DEFAULT`） | 框架默认模板键（包未覆盖）在编辑器**只读**；直接保存被拒，须先 `copy_framework_override` 生成包覆盖 | `level=red`、本次**未写入任何文件** | 框架默认内容保持干净；包覆盖与框架默认分离 |
| 22 | **编辑器保存原子性/回退门禁** | `web/editor_ops.py:1-19`（唯一写入链路）、`:671`（红拦不落盘→备份→原子写→回读复核）；`content/atomic_store.py:12-19`（temp+`os.replace`）、`:35-39`（`backup`）；热重载回退 `content/hot_reload.py:194` | 红拦零改动；备份失败取消写入；写入失败未改动；**回读复核失败自动回退 `.bak`**；写盘后统一热重载，校验失败回退上一份校验通过的 registry 快照 | 结构性拒绝 + 人话；复核失败 `rolled_back`；绝不假成功/半套配置 | 「永不假成功」与热重载原子性（`docs/审查参考/开发规则文档.md:178`） |
| 23 | **包展示元数据严格解析门禁** | `content/field_meta_pack.py:10`（顶层键封闭）、`:83-85`（允许键集合，未知键报错不静默）、`:199-298`（各形态 `_fail`，报错含包名+出错键） | `content/<包>/field_meta.json` 顶层只允许声明键；未知顶层键/形态非法一律明确报错 | 解析层报错（指出包名+出错键），不静默吞 | 防各家包写法漂移；包声明优先于框架兜底但形态受控 |
| 24 | **包导出/导入安全门禁** | `content/pack_transfer.py:1-33`（Zip Slip/符号链接/类型白名单/体积上限/sha256 完整性/过校验器/原子搬迁六条）；CLI `scripts/pack_transfer.py:1-23` | 导入 `.ttrpack` 时：条目路径安全、只收 `.json`/`.md`、四项体积上限、`export_meta.json` sha256 完整性、过既有 `check_pack` 红拦、失败不留半成品 | `exit 1` / `{ok:false}` + 人话，不落盘 | 防 zip slip/zip bomb/篡改；导入不可绕过内容校验器 |
| 25 | **内容包可达性/条件键/占位符校验** | `scripts/check_m7_content.py:1-26`（校验项 1/2/3）、默认路径 `:21`（`content/demo_lv15`） | ① 隐藏要素可达性（条件键必须已注册 + 引用可在 registry 解析）；② 全文 `condition` 键白名单；③ 模板 `{季节}/{时段}/{天气}/{地图}/{图鉴完成度}` 占位符合法 | `exit 1` = 有提示（**提示性不阻断**，可保存但建议修） | 防「永不可发现」的隐藏内容与未注册条件键/非法占位符 |
| 26 | **M8 炼金 fixtures 自检门禁** | `scripts/check_m8_fixtures.py:1-22`（八项断言）、包范围 `:28-31`（`test_demo` + `tests/fixtures/packs/legal`） | JSON 可解析/必填键/包内引用自洽/进化线无环/元素键 ∈ 8 元素/`manifest.modules` 与磁盘一一对应/`settings.alchemy` 类型/品质键枚举 | `exit 1`（列出 FAIL） | 炼金数据契约（REC/TRT/PRF/ALC）先行自检，无引擎依赖 |
| 27 | **消息模板宽度门禁** | `scripts/check_template_width.py:1-19`（预算 B=28 半角/14 全角）、`:30`（`BUDGET_HALF`） | 结构化行静态宽度 > 预算 → FAIL；含占位符估算超宽 → WARN；`meta.prose_keys`/`prose_placeholders` 豁免 | `exit 1`（存在 FAIL） | 手机 QQ 单行不折行；模板排版规范 |
| 28 | **CTB 专用门禁** | `scripts/verify_ctb.py:1-30`（G-LINT-RUFF/G-LINT-MYPY/G-CTB-TEST/G0-ARCH） | ruff/mypy 对基线（`qa_ctb_baseline_ruff.txt`/`_mypy.txt`）的集合差；CTB 契约/调度器测试；`check_architecture.py` 须 `ARCH-OK` | `exit 1` | CTB 重写期的「只减不增」质量护栏 |

**门禁计数 = 28 条**（其中 TC-03 主门禁见 #1；字段元数据迁移门禁见 #6；零包名门禁见 #8/#9/#10/#11）。

##### B.2 门禁成文规定位置（按任务点名的 docs）

| 门禁 | 成文规定 `file:line` |
|---|---|
| 架构门禁 TC-01~04 / 依赖矩阵 R3 | `docs/细化/细化_3a_架构分层契约.md:59`（R3 铁律）、`:46`（D-05 web 单向）、`:86-96`（§1.4 依赖方向矩阵）、`:350-356`（TC-01~05 用例，TC-03 在 `:354`） |
| 门禁工具清单与通过标准 | `docs/检查工具指南.md:9-22`（一键入口）、`:28-35`（工具清单：`check_architecture.py` 须 `ARCH-OK`）、`:37-42`（verify_mN 说明） |
| ruff/mypy 工具链 | `docs/审查参考/开发规则文档.md:119-123`（§1.7「CI 门槛：ruff+mypy+pytest 全绿」）、`:92`（结构断言收敛到 `validator.py`）；`docs/细化/细化_M6_质量门禁.md:118`（LNT-04 快速门）、`:187-188`（CI-01/02）、`:207-208`（TC-CI-01/02） |
| 字段元数据迁移门禁 | `docs/编辑器重写_数据包展示元数据下放方案.md`（§四 批B/C 对拍 diff=0，脚本 `compare_field_meta_migration.py:2-5` 引用）；`docs/深度打造_决策记录.md:813-820`（门禁命令 + soft/hard 语义）、`:521`/`:577`/`:1266`/`:1367`/`:1395`/`:1445`（各批「重定基线」记录） |
| 零包名门禁 | `docs/编辑器重写_需求与约束.md:64`（框架代码不得写死任何包名/业务键）、`:172`（纪律）、`:11-16`（第〇节判据）；`docs/编辑器重写_实现方案.md:387`（换包零改动验收脚本）、`:404`（脚本零真实包名/业务字段名字面量）；`docs/深度打造_决策记录.md:1552`（通用性护栏测试名）；`CHANGELOG.md:17-18`（批71 框架零包名红线） |
| 内容包红/黄校验 + 加载 | `docs/审查参考/RPG回合制框架设计文档.md:741`（红拦仅 5 类）、`:780-805`（§4.5 校验器人话报错）、`:765-766`（loader 流程）、`:445`（声明缺文件黄提示/未声明不加载）；`docs/审查参考/开发规则文档.md:148-159`（§2.3 红拦/黄提示清单）、`:135`（校验器规则） |
| 扩展点与装载安全 | `docs/游戏包扩展点_方案_E.md:5`（三者定位）、`:38-39`（稳定面）、`:53-58`（装载安全）、`:69-75`（边界：不做的事） |
| 编辑器只改内容包 | `docs/编辑器使用说明.md:514-516`（包=目录+模块文件+`.bak`）、`:526`（改的是包文件不是编辑器代码）；`docs/编辑器重写_需求与约束.md:9-16`、`:55`（形态非法指出包名+出错键）、`:266-268`（不写死包名/模块名/业务字段名，换包零改动） |
| CI 流水线 | `docs/细化/细化_M6_质量门禁.md:187-188`（CI-01/02 载体）、`:207-208`（TC-CI-01/02 断言） |

---

#### C. 缺口标注

##### C.1 无单一源 / 口径分散

1. **「框架零包名」没有单一全局门禁**。它被拆成至少 4 处测试（`tests/unit/test_editor_batch8_modules.py:272,279`；`tests/unit/test_editor_batch65_module_presets.py:357,435`；`tests/unit/test_editor_pack_switch.py:153`）+ `CHANGELOG.md:17` 的成文红线，覆盖的是特定文件/特定区域，**不是全仓 `qbot_rpg/**` 扫描**。框架里仍有大量 `veinborn` 字样（多为注释/排障说明，如 `qbot_rpg/commands/enhance_commands.py:275,567`、`qbot_rpg/core/equipment.py:85`、`qbot_rpg/core/battle.py:347`），现有测试不会拦。建议手册明示：零包名是**约定 + 抽样门禁 + 评审**，不是强制全局扫描。
2. **覆盖率门禁口径在文档与脚本间已分叉**（见 C.3）。
3. **门禁命令的「唯一权威清单」分散**：`docs/检查工具指南.md`（工具清单）、`docs/细化/细化_M6_质量门禁.md`（LNT/COV/CI）、`scripts/check_all.py`（调度）、`scripts/run_all_tests.py`（阶段）各自维护一份列表，无单一源。

##### C.2 只有代码、无成文规定（或文档找不到）

1. **`scripts/check_m8_fixtures.py`、`scripts/check_template_width.py`、`scripts/verify_ctb.py`** 以 `scripts/*.py` 头部 docstring 自述依据（`check_m8_fixtures.py:3-5`、`check_template_width.py:1-6`、`verify_ctb.py:1-7`），在 `docs/检查工具指南.md:28-35` 的工具清单里**未被登记**（该清单只列 `check_all`/`run_all_tests`/`check_architecture`/`check_m7_content`/`verify_mN`/`e2e_mX_smoke`）。
2. **`scripts/migrate_pack_field_meta.py` 的 `--check` 幂等门禁**只在脚本 docstring + 方案文档出现，无独立门禁条目/CI 接线。
3. **`tests/unit/test_editor_pack_field_meta_migration.py` / `tests/contract/test_g0_architecture.py`** 是把外部脚本包进 pytest 的适配层，本身无独立文档条目。
4. **批71 引用的两份依据文档在仓库内不存在**：`CHANGELOG.md:18` 引用 `批71_包专属残留_改造方案.md` 与 `框架体检报告.md`，`find`/`ls docs/` 均未找到；「未完成：71-A2…与 71-B1/B2/B3」的收尾状态仅存于 CHANGELOG。

##### C.3 文档与实现不一致

1. **覆盖率测量目录**：`docs/细化/细化_M6_质量门禁.md:73`（COV-02）写「`core + engine + content` 三目录各自 ≥80%」，但 `qbot_rpg/engine/` 已撤销、并入 `core/`；实现侧 `scripts/run_all_tests.py:117` 明确「覆盖率口径目录随之收敛为 **core + content 两目录**（engine 不再独立存在，禁新增稀释）」。文档未同步。
2. **分层/目录名**：`docs/审查参考/RPG回合制框架设计文档.md:48-76`（§2.1/§2.2）与 `docs/审查参考/开发规则文档.md:36-48` 仍写旧目录 `engine/`、`state/`、`editor/`、`utils/`；实际落点为 `qbot_rpg/{core,world,storage,content,data,commands,web}`，收敛决策见 `docs/细化/细化_3a_架构分层契约.md:42`（D-01）。三份文档并存且命名不一致。
3. **`check_architecture.py` 的 `ALLOWED_DEP` 注释自陈历史修正**：`:36-39` 记录原私设第 8 层 `engine` 已撤销；与 C.3.1 同源不同步问题。
4. **字段元数据迁移门禁基线值分散三处**：`scripts/compare_field_meta_migration.py:320`（`"07293ee"`）、`scripts/migrate_pack_field_meta.py:43`（`"995e91b"`，用于 `--gen-structure`）、测试文件注释里的重定链（`tests/unit/test_editor_pack_field_meta_migration.py:44-60+`）。三处语义不同但都叫「基线」，易误读（前者=等价性对拍基线，后者=结构导出基线）。

##### C.4 其它值得手册提示

- **`content/` 下探针包与真实包混放**：`content/zz_probe_ext/`（含可执行 `ext/`、`tests/`、`scripts/`）与 `content/zz_probe_packmeta/`、`content/zz_craft_demo/` 等探针包与真实包（`veinborn`、`test_demo`）同目录。手册应说明哪些是验证样本、可安全忽略/删除。
- **包内 Python 的执行边界**：`ext/` 只在双闸开启时装载（`assembly/pack_ext.py:513-519`），但 `.ttrpack` 导入默认**只收 `.json`/`.md`、拒绝 `.py`**（`content/pack_transfer.py:21`），即分享包不会携带 `ext/`。手册需提示包作者：扩展代码不经 `.ttrpack` 分发。
- **`check_m7_content.py` 缺省只查一个包**（`scripts/check_m7_content.py:21` 缺省 `content/demo_lv15`），`check_all.py` 默认也只跑该缺省（`scripts/check_all.py:134`），并未遍历全部内容包。

---

##### 附：关键结论 3 条

1. **边界是「三层 + 两处开关」**：框架（`qbot_rpg/**`，含 `web/`）／内容包（`content/<包>/**` JSON）／包自持代码（`ext/`+`tests/`+`scripts/`，默认关闭双闸）；编辑器只写内容包目录，框架关键模板只读（`web/editor_ops.py:671`）。
2. **门禁共 28 条**，核心为：架构门禁 TC-01~04（`scripts/check_architecture.py:319`）、字段元数据迁移门禁（`scripts/compare_field_meta_migration.py:320`）、零包名测试群（`tests/unit/test_editor_batch8_modules.py:279` 等）、`check_all.py`/`run_all_tests.py`/CI 流水线。
3. **最关键的单一红线**：`content/loader.py:239` + `content/validator.py:27` 的「红拦 5 类 → `PackLoadError` 整包拒绝挂载」，它是所有内容包数据进入运行时的唯一收口，也是「只建议不限制」哲学的硬边界；字段元数据迁移门禁（`scripts/compare_field_meta_migration.py:20-31`）则守住「JSON 字段名=公共 API」的向后兼容。二者共同构成本框架扩展安全的底座。

---

## §6 缺口标注

> 本节是**手册要重点解释**的部分：单一源缺失处、只有代码没有文档处、注释与实现不一致处。
> 分 4 组：**A 无单一源** / **B 只有代码无文档** / **C 注释与实现不一致** / **D 悬空引用（文档/依据缺失）**。
> 每条给 file:line；**主 agent 亲自核实**的条目标「✔主」，来自盘点子任务且已抽样核验的标「◇子」。

### A. 无单一源（同一语义散落多处）

| # | 缺口 | 表现 | file:line | 来源 |
|---|---|---|---|---|
| A1 | **`EVENT_POINTS` 声明 17 个，但"哪些真接了"没有单一源** | 必须全仓 grep `_dispatch_event(` 才知道：11 个有派发点；`turn_end` 故意不派发；`mark_gain`/`mark_lose`/`on_attack`/`on_hit`/`on_skill` **声明但无派发点**；`status_lose` 只接了驱散、tick 过期未接 | 声明 data/event_points.py:25；派发点 core/battle.py:1133/1145/1188/2034-2035/2173-2174/2468-2469/2840/2962/3021/3122/4061/4638/5047 + core/effects.py:2257/2279；"二期"登记 记录.md:842；turn_end 说明 docs/深度打造_实现说明.md:735 | ✔主 |
| A2 | **combatant / 战斗快照双轨未收敛** | 契约类型与运行期 dict 不同；combatant 字段散落 ≥4 处 | data/battle.py:32-75（类型）+ :13-20（自登记未生效）；core/battle.py:317-322、:2318-2327、:937-942；commands/battle_launch_commands.py:182-220；core/pvp.py:154-203；core/effects.py:2229-2235 | ◇子 |
| A3 | **`ctx` 指令上下文键无单一源、四段散落且重复注入** | 基础段/注册态/未注册态/注册无关四段；`items`/`skills`/`battle_engine` 等重复注入；未注册态缺键只能 `ctx.get` 兜底 | assembly/context.py:1295-1373、:1398-1584、:1586-1639、:1642-2034；重复示例 :1341 vs :1777、:1546 vs :1655 | ◇子 |
| A4 | **`settings.json` 双读取通道（校验 vs 直读）** | `loader` 按 `manifest.modules` 加载并校验；`qbot_rpg_bridge` 无条件直读 → 未列入 modules 的 settings.json **运行时生效但绕过校验** | content/loader.py:286-311 vs qbot_rpg_bridge/assemble.py:89-98 | ◇子 |
| A5 | **`module_labels` / `module_tree` 双声明位** | `manifest.json` 与 `field_meta.json` 都能声明，覆盖规则在第三处 | content/field_meta.py:2162/2166；content/field_meta_pack.py:35-37、:86-87 | ◇子 |
| A6 | **`slot_defs`（settings 段）vs `slots.json`（模块）功能重叠** | 两处都表达"装备部位定义"，框架已显式登记重叠并给黄提示 | content/module_catalog.py:87-108（`overlap_with`/`overlap_note`） | ✔主 |
| A7 | **`settings.*` 段无统一登记表** | 软段/结构在 `field_meta.py`，专项校验在 `content/*_settings.py`、`content/*_models.py` 并列 | content/field_meta.py:3443；content/deep_craft_settings.py:110 等 | ◇子 |
| A8 | **`modules_raw` 模块名双处登记** | `_KIND_FOR_MODULE` 与 `FRAMEWORK_MODULE_CATALOG` 各一份，需人工保持一致，只有单向自检 | content/loader.py:150-202、:205-233；content/module_catalog.py:68 | ◇子 |
| A9 | **门禁命令权威清单分散** | `docs/检查工具指南.md`、`docs/细化/细化_M6_质量门禁.md`、`scripts/check_all.py`、`scripts/run_all_tests.py` 各一份 | 见 §5 B.1/B.2 | ◇子 |
| A10 | **字段元数据迁移"基线"值分散三处、语义不同却同名** | `compare_field_meta_migration.py`（等价性对拍基线）vs `migrate_pack_field_meta.py`（结构导出基线）vs 测试注释的重定链 | scripts/compare_field_meta_migration.py:320；scripts/migrate_pack_field_meta.py:43；tests/unit/test_editor_pack_field_meta_migration.py:44-60 | ◇子 |
| A11 | **两套"事件"体系并列、无一篇对比文档** | 战斗时点 `EVENT_POINTS` 与计数事件键 `[事件:XXX]` 同名不同物；后者仅 `docs/m125_事件键审计.md` 单篇说明 | data/event_points.py:25 vs core/event_bus.py:53/66；docs/m125_事件键审计.md:1-55 | ✔主 |

### B. 只有代码、没有文档

| # | 缺口 | file:line | 来源 |
|---|---|---|---|
| B1 | 框架内部 `ctx[...]` 注入式 hook（`add_item`/`resolve_item`/`consume_bait`/`respawn_hook`/`npc_interactions`/`start_battle` 等）**只在代码 docstring 说明**，方案 E 未列 | assembly/context.py:1106/1510/1539/1663/1754/1848 | ◇子 |
| B2 | `settings.schema_ext`（包自持校验扩展）在方案 E 文档未提及，属代码内能力 | content/validator.py:390-549 | ◇子 |
| B3 | `field_meta.json` 的大批展示键（`entry_merge_filtered`/`segment_pages`/`entry_tree`/`entry_groups`/`id_prefix`/`id_width`/`entry_presets`）无独立手册条目 | content/field_meta_pack.py:94-114 | ◇子 |
| B4 | 运行期战斗快照顶层键（`combat_position`/`parts_state`/`battle_resources`/`transform_state`/`resource_state`）只有代码、无 dataclass 契约 | core/battle.py:2389-2432；各 `setdefault` :3449/3696/3860/4131/4353-4355/4475-4478/5161/5248 | ◇子 |
| B5 | 战斗期**派生键**（`shield`/`mitigation`/`pv`/`level`/`hit_streak`/`miss_streak`）是公式视图派生、不落档，未在数据模型登记 | core/battle.py:937-942 | ◇子 |
| B6 | `scripts/check_m8_fixtures.py`、`check_template_width.py`、`verify_ctb.py` 未登记进 `docs/检查工具指南.md` 工具清单 | 各自 docstring :3-5/:1-6/:1-7；docs/检查工具指南.md:28-35 | ◇子 |
| B7 | `scripts/migrate_pack_field_meta.py --check` 幂等门禁无独立门禁条目/CI 接线 | scripts/migrate_pack_field_meta.py（docstring） | ◇子 |
| B8 | `message_chunk_len`（commands/sender.py:133）、`resource_pct`（content/field_meta.py:3233）等段无专门作者文档 | 同左 | ◇子 |

### C. 注释与实现不一致

| # | 缺口 | 表现 | file:line | 来源 |
|---|---|---|---|---|
| C1 | **`EFFECT_AXIS_SPECS` docstring 说"共 15 条（P0 8 + P1 7）"，实际 17 条（P0 8 + P1 9）** | 后续批次追加轴后注释未同步 | 注释 qbot_rpg/data/gear_stats.py:227；实际表 :230-447（实测 17） | ✔主 |
| C2 | `Player.achievement_state` docstring 声明新形态 `{unlocked, repeat_count}`，codec 仍按 tuple/list 处理 | 读 `tuple(...)`、写 `list(...)`、DB 列默认 `'[]'`；真值实际在 `ctx`→`persistent_state` | data/player.py:97-102；storage/repository.py:174、:331；storage/schema.py:63；assembly/context.py:1522-1524 | ◇子 |
| C3 | `StatusInstance`/`Duration` 契约类型与运行期 dict 不一致 | 运行期多出 `category/value/decay_subject/immune_uses/trigger_halve/_uid`，且 `decay` 为 str 非 float | data/status.py:7-12（自登记）、:44；core/effects.py:749-762、:757 | ◇子 |
| C4 | `resolve_templates` 注释写"深合并"，实现是逐 key 整体替换（值为字符串） | 对嵌套结构无深合并语义 | core/templates/__init__.py:102（注释）vs :113-119（实现） | ◇子 |
| C5 | "`settings.json` 为常驻模块"注释 vs loader 仅按 `manifest.modules` 加载 | `zz_probe_packmeta` 即无 `settings` | content/field_meta.py:3443-3446（注释）vs content/loader.py:286-311（实现） | ◇子 |
| C6 | `pack_ext.py` 注释承诺"未启用时零文件访问"，实现里 `Path(pack_dir)` 在双闸判定前构造 | 仅构造 Path（取包名），未 stat/read——属边界表述，手册须给准确口径 | assembly/pack_ext.py:503（注释）vs :505-519（实现） | ◇子 |
| C7 | 覆盖率口径文档与实现分叉 | 文档写 `core + engine + content` 三目录 ≥80%，实现已收敛为 `core + content` 两目录 | docs/细化/细化_M6_质量门禁.md:73 vs scripts/run_all_tests.py:117 | ◇子 |
| C8 | 分层/目录名旧称残留 | 两份文档仍写 `engine/`/`state/`/`editor/`/`utils/`，实际落点已改 | docs/审查参考/RPG回合制框架设计文档.md:48-76；docs/审查参考/开发规则文档.md:36-48；收敛决策 docs/细化/细化_3a_架构分层契约.md:42 | ◇子 |
| C9 | `check_architecture.py` 的 `ALLOWED_DEP` 注释自陈历史修正（原第 8 层 engine 已撤销） | 与 C7/C8 同源不同步 | scripts/check_architecture.py:36-39 | ◇子 |

### D. 悬空引用 / 依据缺失（用户点名要的"唯一源"确实不存在）

| # | 缺口 | 事实 | 来源 |
|---|---|---|---|
| D1 | **"审计3 §6 合理并存清单"本体不在仓** | 全仓 `grep 合理并存` 仅 1 处转引，无独立"审计3"报告文件 | docs/深度打造_决策记录.md:1568（唯一转引） | ◇子 |
| D2 | **`data/affinity_keys.py` 没有 aliases 表**（用户样例②假设不成立） | 全文 85 行只有池类型/反应类型/载荷键/`AFFINITY_EFFECT_QUALITY_CAP`；真实"别名归并"在 `gear_stats.py`（`EFFECT_LEGACY_ALIASES`）与 `condition_engine.py`（`VAR_ALIASES`/`OP_LEGACY_ALIASES`） | qbot_rpg/data/affinity_keys.py:1-85；qbot_rpg/data/gear_stats.py:584；qbot_rpg/core/condition_engine.py:96-120 | ✔主 |
| D3 | **批71 引用的两份依据文档在仓库内不存在** | `CHANGELOG.md:18` 引 `批71_包专属残留_改造方案.md` 与 `框架体检报告.md`，`docs/` 内均无 | CHANGELOG.md:18 | ◇子 |
| D4 | **`docs/实现层规划文档.md`、`docs/审查参考/效果系统设计定稿.md` 等引用的 `on_turn_start`/`on_turn_end`/`on_death` 与现行 `EVENT_POINTS` 命名不一致** | 设计期用 `on_*` 前缀，落地枚举去前缀（`turn_start`/`death`）：外部开发者按设计文档写会永不触发（只黄提示 Y-19） | 设计枚举 docs/审查参考/效果系统设计定稿.md:83、docs/审查参考/RPG回合制框架设计文档.md:500 vs 现行 data/event_points.py:25；校验 validator.py:3378 | ✔主 |
| D5 | **"零包名"没有单一全局门禁** | 拆成 4 处定向测试 + CHANGELOG 红线，**不是全仓扫描**；框架内仍有 `veinborn` 字样（多为注释） | tests/unit/test_editor_batch8_modules.py:272,279；test_editor_batch65_module_presets.py:357,435；test_editor_pack_switch.py:153；CHANGELOG.md:17；残留例 commands/enhance_commands.py:275,567、core/equipment.py:85、core/battle.py:347 | ◇子 |
| D6 | **探针包与真实包混放** | `content/zz_probe_ext/`（含可执行 `ext/`/`tests/`/`scripts/`）等与真实包同目录；且 `.ttrpack` 分发**只收 `.json`/`.md`、拒绝 `.py`**（扩展代码不经打包分发） | content/pack_transfer.py:21；目录实况 `content/` | ◇子 |
| D7 | `check_m7_content.py` 缺省只查一个包 | 缺省 `content/demo_lv15`，`check_all.py` 默认也只跑该缺省，未遍历全部内容包 | scripts/check_m7_content.py:21；scripts/check_all.py:134 | ◇子 |

---

## §7 「形似 bug 实为设计」初选清单

> 本节 = 第三路（权责与「勿当 bug 修」）的**材料收集与定位**，由只读盘点子任务产出，主 agent 未逐条复核全部行号（已抽样核验 §1-①/②/③/④、C18、C25 等）。
> 判据类型四组：文档铁律 / 审计「合理并存」近似项 / 代码注释 / CHANGELOG 批次条目。**不作最终结论**；标「低/中」者须深挖。

### part7 · 权责与「勿当 bug 修」候选清单（形似 bug、实为故意设计）

> 用途：《框架扩展开发手册》第三路（权责与「勿当 bug 修」）**材料收集与定位**。
> 仓库：`/root/QBot-TurnTellerRPG`（只读盘点，未修改任何仓库文件；本文件为唯一产出）。
> 编制口径：每条候选均附 **file:line 依据**（文档原文 / 代码注释 / CHANGELOG 批次条目）。
> **不作最终结论**；标「低」者明确写「待查」。
> 来源背景（本路立项原文）：`docs/深度打造_决策记录.md:1568` ——「『有意设计』清单（形似 bug、实为设计，附理由与判据）——直接对应**审计3 §6 合理并存清单**与历次『铁律』（如**锻造无随机**、别名归并、legacy 兜底、声明+兜底双轨…）」。

### 0. 重要定位说明（先行风险提示，供主 agent 决策）

1. **「审计3 §6 合理并存清单」本体不在本仓库**：全仓 `grep 合理并存` 仅命中 1 处，即
   `docs/深度打造_决策记录.md:1568` 的**转引**，无独立「审计3」报告文件（`find -name '*审计*'` 无该文件）。
   本次已把仓库内可考的「并存/两轨/双源」裁决尽量摘出，归入 **§B**，作为该清单的**近似替身**。
   真正的审计3 §6 原文需由主 agent 从仓外补齐后与该节对表。**待查**。
2. **用户点名样例 2「affinity_keys.py 的 aliases 表」在本仓库不存在**：`qbot_rpg/data/affinity_keys.py`
   全文 85 行只有池类型/反应类型/载荷键/`AFFINITY_EFFECT_QUALITY_CAP` 常量，**无 aliases / 别名表**
   （已通读，见 §C-3 备注）。仓库内真实的「键族别名归并」位于
   `qbot_rpg/data/gear_stats.py`（`EFFECT_LEGACY_ALIASES` / `route_legacy_aliases_into_flat`）与
   `qbot_rpg/core/condition_engine.py`（`VAR_ALIASES` / `OP_LEGACY_ALIASES`）。**待查**：样例 2 可能
   指仓外版本、或系「键族 aliases」的泛指。
3. 置信度定义：**高** = 有明文铁律/注释直述「有意/刻意/兼容」；**中** = 有并存/两轨事实但未见「勿修」明示；
   **低** = 仅形似、意图未定，须深挖。

---

### 1. 用户点名四样例（先覆盖）

| 候选现象 | 为什么“形似 bug” | 设计意图 | 判据来源 file:line | 置信度 | 若被误修会怎样 |
|---|---|---|---|---|---|
| **① 锻造无随机（forge 100% 确定性）** | 同样输入 1000 次产出/消耗/经验/日志逐次一致，且“素材够即成功、失败零消耗”——看似“缺了成功率判定 / 没有失败分支” | 失败与随机被**刻意隔离**到炼金（品质/特性）与强化（成功率）；锻造是确定性派生树，零会话原子，素材即进度 | `docs/m9_启动包.md:75`、`docs/m9_启动包.md:95`、`docs/规划/规划_路2c2_锻造.md:142`、`docs/规划/规划_路2c2_锻造.md:146`、`docs/细化/细化_2c2b_锻造流程契约.md:14`、`docs/细化/细化_2c2b_锻造流程契约.md:250`、`docs/审查/覆盖审计_F_生活生产.md:63`（G-02）、`docs/审查/覆盖审计_F_生活生产.md:72`（G-11） | 高 | 给 forge 加随机=违背用户拍板铁律（“实现不得引入随机/会话”，`docs/m9_启动包.md:95`）；破坏 TC-04 确定性差分=0、素材经济与带孔唯一来源口径 |
| **② 别名归并（键族 aliases）** | 同一个效果可写成新键或旧键、旧键值还常与轴符号相反（如 `immune_dmg` → `damage_taken_pct` 取负），看似“重复字段/符号写错” | 旧键 → 特效轴的**唯一兼容换算**，`pct = sign × 旧键值`，且**只在聚合入口换算一次、不双计**；旧键自身链路不动 | `qbot_rpg/data/gear_stats.py:26`~`:30`、`qbot_rpg/data/gear_stats.py:60`~`:62`、`qbot_rpg/data/gear_stats.py:582`~`:588`、`qbot_rpg/data/gear_stats.py:754`~`:785`、`qbot_rpg/core/battle.py:4221`~`:4223`、`qbot_rpg/core/equipment.py:1006`~`:1008`；对照（条件引擎）：`qbot_rpg/core/condition_engine.py:96`~`:120`、`:154`、`:215`~`:227` | 高 | 删旧键别名→旧内容包数值静默失效；改成两处都换算→**双计**（同一旧键被消费两次，数值翻倍）；把 `sign=-1` 当 bug 改成正号→免伤变易伤 |
| **③ legacy 兜底 / 声明+兜底双轨** | 框架里硬编码一小撮包专属 id（`sw_vault_air`、`sword_flow`），看似“框架残留包名、该清理” | 是**降级兜底**：权威来源改为包声明（`statuses[].stance=="air"` / `marks[].role=="combo_counter"`），包不声明时回落旧集合以保**逐位一致**；实现明写 `or` 不是 union（一旦有声明就完全以声明为准） | `qbot_rpg/core/battle.py:337`~`:343`、`qbot_rpg/core/battle.py:346`~`:351`、`qbot_rpg/core/battle.py:622`~`:627`；`qbot_rpg/commands/basic_commands.py:1938`~`:1941`、`:1944`~`:1960`；CHANGELOG `CHANGELOG.md:17`~`:19`、`:25`~`:28`、`:32`~`:34`、`:39`~`:40` | 高 | 直接删兜底→无 registry 的框架单测路径与非声明旧包行为改变；把 `or` 改成 union→legacy id 泄漏进新声明包，行为污染 |
| **④ `mitigation` 阶段独立** | 承伤/易伤轴（`damage_taken_pct`）与减伤（`mitigation`）看起来是同一件事，疑似“两条减伤路径重复、该合并” | 管线阶段 ① `mitigation` **只做减伤/减免**，位于“减伤之后、护盾之前”；承伤双向轴（含易伤）另有唯一收口 `battle._damage_taken_mult`。明写「**不得**动 effects 的 mitigation 阶段（混入易伤会与护盾/保底伤害交织）」 | `qbot_rpg/core/effects.py:129`~`:130`、`qbot_rpg/core/effects.py:1160`~`:1190`、`qbot_rpg/data/gear_stats.py:261`~`:264`、`qbot_rpg/data/gear_stats.py:88`、CHANGELOG `CHANGELOG.md:277`~`:282` | 高 | 把易伤并进 mitigation→与护盾/保底伤害（`min_damage`）交织、结算顺序改变、多个既有测试与红线对拍崩；把两阶段合并→阶段顺序契约 `DEFAULT_PIPELINE_ORDER` 破坏 |

---

### A. 判据类型：文档铁律（定稿 / 用户拍板 / 验收铁律）

| 候选现象 | 为什么“形似 bug” | 设计意图 | 判据来源 file:line | 置信度 | 若被误修会怎样 |
|---|---|---|---|---|---|
| **A1 锻造 100% 确定性 / 失败随机隔离**（见 §1-①） | 无失败分支 | 失败/随机归炼金、强化；锻造无随机源 | `docs/m9_启动包.md:75`、`docs/m9_启动包.md:95`、`docs/规划/规划_路2c2_锻造.md:142`、`docs/细化/细化_2c2b_锻造流程契约.md:14`、`:250` | 高 | 见 §1-① |
| **A2 锻造 = 零会话原子（不用框架 3.18）** | `/锻造` 一条指令即时出结果、不建确认窗，看似“少了会话/确认步骤” | 明确不使用会话状态机；原子无中间态，防半成品/回滚 | `docs/细化/细化_2c2b_锻造流程契约.md:13`、`:247`；`docs/审查/覆盖审计_F_生活生产.md:64`（G-03）；`docs/m9_启动包.md:95` | 高 | 补会话会破坏“原子/零副作用”与幂等断言，引入中断恢复复杂度 |
| **A3 天气确定性抽签（seed=sha256(池键排序+tick)）** | 天气“随机”却同 tick 全世界同值、重启不重抽、序列可预测，看似“伪随机/种子写死” | 懒计算刚需：不存历史、不跑定时器，任何时刻可公式重算；v1 刻意不做真随机 | `docs/审查参考/时间天气系统设计定稿.md:58`、`:84`、`:425`；`docs/规划/规划_路2a_地图副本.md:24`、`:260` | 高 | 换真随机/随机种子→跨群/跨进程/重启不一致，懒计算与 M43 回归探针失效 |
| **A4 零定时器 / 懒计算** | 天气/周期不跑 scheduler，看似“时间系统没驱动” | 每指令前 `check_changes` 比较缓存懒推进；周期值由公式重算 | `docs/审查参考/时间天气系统设计定稿.md:61`、`:62`、`:63`；`docs/规划/规划_路2a_地图副本.md:24` | 高 | 加定时器→多群/离线/重启状态分叉，且违反仓库“零 apscheduler”工程铁律 |
| **A5 合成（第一层）产物恒标准档 / 无随机** | 合成产物品质固定、无特性、不参与品质判定，看似“品质系统没接上” | 三层漏斗的产出边界铁律：合成只产标准版，品质/特性归炼金 | `docs/细化/细化_2c4c1_品质与刻度.md:25`、`:26`；`docs/细化/细化_2c4a_炼金三层漏斗.md:19`（边界铁律） | 高 | 让合成掷品质→破坏 `synth_allowed` 边界与三层漏斗经济 |
| **A6 标准珠 = 固定 base_effects（无随机特性）** | 珠子属性固定，看起来“没做随机附魔” | 保底通道永可用；随机性隔离在炼金品质/特性 | `docs/审查参考/炼金系统设计定稿.md:117`；`docs/规划/规划_路2c4a1_三层漏斗.md:19` | 高 | 加随机→保底通道失效，经济与“无随机差分”验收崩 |
| **A7 技能库“三铁律”：漏配=合理默认 / 不拦数值（power 999 是作者自由）** | 校验器只查结构/引用/死配置，不封顶 power，看似“数值校验缺失” | 字段最少、扩展字段默认兜底；引擎不做数值预警，把平衡权交给作者 | `docs/细化/细化_6a_技能库契约.md:24`；`docs/审查/幻觉审查_6a.md:23`；`docs/审查/覆盖审计_B_战斗核心.md:70` | 高 | 给 power 加硬上限→拦死合法作者配置；把“漏配”当错误红拦→大量合法内容包加载失败 |
| **A8 未知字段默认放行（field_meta §2.3 兜底）** | 内容包写错/多写字段大多只黄提示甚至放行，看似“校验器太松” | 红拦清单封闭、黄提示开放；枚举尽量宽松避免误阻断合法包 | `qbot_rpg/content/field_meta.py:23`~`:24`；`qbot_rpg/content/validator.py:6`、`:675`、`:3573`；`docs/m13_6a摸底.md:146`、`:221` | 高 | 收紧为“未登记字段红拦”→既有内容包（含 charge_*/condition obj 等未登记键）整包被拒，方向与铁律相反 |
| **A9 签到碎片化铁律：断签不清零 / 月度累计不要求连续** | 断签后月度累计仍在、连签奖励仍可能给到，看似“断签惩罚没生效” | 断签不挫败，月底冲刺钩子；补签为可选默认关 | `docs/审查参考/签到系统设计定稿.md:15`、`:57`、`:103`、`:205` | 高 | 改成断签清零→违背用户铁律与签到经济设计 |
| **A10 商店“不配 refresh = 永不刷新”（用户拍板⑥）** | 不写刷新配置就永不下架/库存不回，看似“默认值忘了给” | 明确拍板：缺省即永不刷新（另一默认 daily 05:00 的旧口径已被收敛） | `记录.md:1522`（用户 8 项拍板⑥）；相关并存见 §B-1、`docs/细化/细化_M6_三引擎与基础指令.md:69` | 中 | 改默认刷新→商店库存/限购周期被意外重置，破坏经济与既有测试 |
| **A11 指令分隔符三铁律（数量=`*`、列表=`,`、位置参数≤2、键值=`=`）** | `/强化` 禁 `*`、序号不带 `*`、A+B 只是文档记法，看似“同一种数量语法这里不认” | 参数格式唯一口径，防解析歧义；命名禁保留字符 | `docs/审查参考/指令分隔符统一规范.md:27`~`:51`、`:55`~`:61`；`docs/审查/覆盖审计_A_框架基础.md:126`~`:129`；`docs/细化/细化_2c4c_珠与合成指令.md:79`（CMB-07） | 高 | 放开 `/强化 装备*2` 或允许物品名含 `+`→解析歧义/串参 |

---

### B. 判据类型：审计「合理并存」/ 审查裁决（对应“审计3 §6 合理并存清单”的仓库内近似项）

> 说明：审计3 §6 原文不在仓（见 §0-1）。以下为仓库内可考的“刻意并存/双轨”裁决，逐条附依据。

| 候选现象 | 为什么“形似 bug” | 设计意图 | 判据来源 file:line | 置信度 | 若被误修会怎样 |
|---|---|---|---|---|---|
| **B1 商品「库存 + 个人限购」同条目并存（用户裁决⑤）** | 同一条目既扣全局库存又扣个人限购，`scope` 还只描述默认侧，看似“互斥字段没互斥” | 裁决⑤：两制**并存**、各自独立读取、互不排他；`scope` 只管默认侧 | `qbot_rpg/content/shop_models.py:5`、`:10`、`:15`、`:206`~`:207`、`:295`、`:308`；`docs/细化/细化_2b3_商店引擎契约.md:393`；`记录.md:1522`；`tests/unit/test_shop_models.py:307`~`:317`、`:358`~`:372` | 高 | 把 scope 恢复为二选一→L450/L465 型配置无法无损表达，旧商店行为静默改变 |
| **B2 签到多表并存、一次 `/签到` 全部结算** | 一份文件里 loop/monthly/activity 三表同时生效并各自独立连签，看似“多份配置冲突没合并” | 奖励日历=多表并存；一次结算、单条汇总防刷屏；跨表互不写对方 state | `docs/审查参考/签到系统设计定稿.md:75`、`:216`；`qbot_rpg/content/checkin_models.py:4`、`:195`；`tests/unit/test_checkin.py:53` | 高 | 只取一张表/合并表→奖励与连签计数错乱 |
| **B3 dual 异框架状态“并存相加”（不是高覆盖低）** | 两个降攻/减益状态同时生效且数值相加，看似“状态覆盖逻辑写错” | 刻意机制：`single` 同类高覆盖低、`dual` 异框架并存相加、`stack` 累积 | `qbot_rpg/core/effects.py:508`、`:688`；`docs/审查参考/效果系统设计定稿.md:228`；`tests/unit/test_effects_gaps.py:118`~`:136` | 高 | 改成高覆盖→压制流/双降攻 build 失效，C-2 语义与测试崩 |
| **B4 同回合互杀：双方死亡标记同轮并存 → 平局** | 双方都死却判平局（可配玩家败），且 `player_killed_enemy` 成死标记，看似“死亡判定漏了先后” | 刻意规则：死亡标记同轮并存，判定基准 order/hp_ratio 可配；属设计内 | `docs/细化/细化_1g1a_战斗状态集.md:95`；`qbot_rpg/core/battle.py:1214`；`docs/审查/幻觉审查_1g3.md:57` | 高 | 改成“先判先手胜”→PVP/自爆流结果改变，既有断言崩 |
| **B5 门槛判定两口径并存（`tier_index_for_level` vs `level` 直比）** | 两条路径对“职业等级门槛”算法不同，看似“重复实现漂移” | 默认配置下两口径**等价**，属如实登记的并存（**批82 · C1 已收敛**） | `记录.md:1159`；`审查_M8实现_批次E2_jspace.md:25`、`:103`（**正确路径 = 仓库根**；批83 · NEW-4 改引，原写 `docs/审查报告/…` 不存在） | 中 | 贸然统一其中一条→非默认配置下职业门槛判定变化；须先查内容包实际配置 |
| **B6 背包“数量上限截断”与“格数上限”双口径并存** | 两个“上限”都叫上限、互不替代，看似“同名冲突” | 裁决：数量截断作用于单次 add 的 count；格数上限作用于总行数，两条独立校验 | `docs/细化/细化_M6_三引擎与基础指令.md:69` | 高 | 合并成一条→大额入包或满包行为改变（吞物/误拒） |
| **B7 分解 × 全物入料双回收出口并存** | 旧装备既能 `/分解` 又能当素材，两条回收链路，看似“回收入口重复” | 刻意：两条链路并存、互不覆盖（专家解锁全物入料） | `docs/细化/细化_2c4c_珠与合成指令.md:220`（EDGE-05） | 高 | 砍掉其一→回收经济闭环断裂，旧成品无处去 |
| **B8 品质档名两套并存（优秀/稀有 vs 精良/史诗）** | 同一档位两套中文名并存，看似“命名没统一/写错” | 定稿内部两套名并存，细化选边权威落点 §10.6（精良/史诗），旧名保留识别 | `docs/审查/M8设计审查_20260829/审查_M8设计_批次1A_jspace.md:62`；`docs/m8_shared_contract.md:454`（旧名「优秀/稀有」废弃） | 中 | 直接删旧名→旧包加载/迁移黄提示路径断裂；须确认旧名是否仍有内容包在用 |
| **B9 分解回收率 40%→65% 多处并存** | 同一回收率在三处写 60%/0.65/40-65%，看似“复制没同步” | 定稿自身多口径并存，细化按 settings 上限 65% 取值；属定稿内部张力非实现 bug | `docs/审查/幻觉审查_2c4a.md:36`；`docs/审查/幻觉审查_2c2c.md:69` | 中 | 按其中一处“修正数值”→经济基准偏移、红线对拍失败 |
| **B10 套装技能“多技能并存”（数组）** | 定稿只定义单技能三档结构，实现支持多技能数组，看似“超出定稿的私扩” | schema 自然延伸（`skills` 是数组），但**未显式标“本文扩展”**（审查已提示补注） | `docs/审查/幻觉审查_2c2d.md:80` | 低（待查：是否应登记为扩展） | 若判为越权而砍数组→多技能套装配置失效 |
| **B11 怪物 `battle_start` 特例两轨并存** | 战斗开始事件存在特例保留路径，看似“没被统一收编” | 已登记风险：特例保留（两轨并存），on_tick 特例二期收编 | `记录.md:843` | 中 | 立即收编特例→触发时点/事件顺序变化，须先做兼容对拍 |
| **B12 炼金能量开关双源并存（proficiency vs settings）** | 两个地方都能配开关且优先级未定，看似“双开关打架 bug” | 契约要求保留双源、但**需声明优先级**（建议 settings 为准、proficiency 兜底）——属待收口并存 | `docs/审查/M8契约审查_20260829/审查_M8契约_路C_jspace.md:84` | 中（待查：最终优先级） | 未定优先级就“修”其一→两处配置行为互相覆盖，作者预期落空 |

---

### C. 判据类型：代码注释（有意/刻意/为兼容/保持/不回退/勿修）

| 候选现象 | 为什么“形似 bug” | 设计意图 | 判据来源 file:line | 置信度 | 若被误修会怎样 |
|---|---|---|---|---|---|
| **C1 legacy 兜底 / 声明+兜底双轨（`or` 不是 union）** | 框架硬编码包专属 id，像残留包名 | 包声明驱动 + 无声明回落 legacy，保逐位一致；有声明则以声明为准，防 legacy 泄漏 | `qbot_rpg/core/battle.py:337`~`:343`、`:346`~`:351`、`:622`~`:627` | 高 | 删/改 union→行为污染或旧包失效（详见 §1-③） |
| **C2 连段计数印记 legacy 兜底（`sword_flow`）** | 框架里写死一个具体印记 id | 权威=包声明 `marks[].role=="combo_counter"`；无声明回落 `_LEGACY_COUNTER_MARKS`（fail-safe） | `qbot_rpg/commands/basic_commands.py:1938`~`:1941`、`:1944`~`:1960` | 高 | 同 C1 |
| **C3 旧键别名归并：唯一换算入口、只一次、不双计** | 同一旧键既有自身链路又在聚合入口被换算，像“两处消费” | `route_legacy_aliases_into_flat` 是占位旧键→特效轴的**唯一**兼容换算；`route_bonus_into` 显式跳过占位键防双计 | `qbot_rpg/data/gear_stats.py:26`~`:30`、`:56`~`:62`、`:582`~`:588`、`:754`~`:785`；`qbot_rpg/core/equipment.py:1006`~`:1008`；CHANGELOG `CHANGELOG.md:248`~`:253` | 高 | 见 §1-② |
| **C4 `mitigation` 阶段独立，不得混入易伤** | 减伤与承伤易伤像重复逻辑 | 阶段①只做减伤；承伤双向轴另有唯一收口；明写“不得动 mitigation 阶段” | `qbot_rpg/core/effects.py:129`~`:130`、`:1160`~`:1190`；`qbot_rpg/data/gear_stats.py:261`~`:264`、`:88` | 高 | 见 §1-④ |
| **C5 技能链成环 = 有意的循环连招，提示不拦截** | 校验器发现环却只给提示，像“环检测没硬拦” | 环形链是合法的循环连招（X-04），刻意只提示 | `qbot_rpg/content/validator.py:1654`；`qbot_rpg/core/monster_chains.py:58` | 高 | 改成红拦→合法循环连招内容包被拒载 |
| **C6 地图双向边允许一侧缺失/“刻意不对称”** | `bidirectional` 声明了却允许 A→B 有、B→A 无，像“校验漏了对称性” | 只对声明 bidirectional 的边查对侧；缺失/非双向→黄提示，允许作者刻意不对称 | `qbot_rpg/content/map_models.py:701`；`qbot_rpg/content/map_graph.py:231` | 高 | 改成红拦→单向下行/密道等地形无法配置 |
| **C7 派生行有意豁免折行（遗留 #37，用户拍板）** | 派生行整行全量显示、不折行，像“忘了走 16 行/折行门禁” | 2026-09-12 用户拍板：拆行会丢失/割裂信息，登记 `skill_info_derived` 于 `meta.prose_keys` 有意豁免 | `qbot_rpg/commands/basic_commands.py:2289`~`:2291`、`:2366` | 高 | 纳入折行→技能信息被截断，违背拍板 |
| **C8 改名后旧名悬空、校验“如实报引用不存在”** | 改名后引用方仍指旧名，校验报错，像“改名功能没级联更新” | 明确容忍：引用方**保持旧名**、校验如实报，不自动改数据 | `qbot_rpg/web/editor_ops.py:483` | 中 | 自动级联改名→可能误改跨包引用/不可控批量变更，须走专门迁移 |
| **C9 键名刻意避开 `settings.forge` 防语义混淆** | 明明有关联却故意换名，像“命名不统一” | 打造/合成层键名刻意避开既有 M9 锻造配置段，防两域语义混淆 | `qbot_rpg/content/field_meta.py:593`；`qbot_rpg/core/craft_paths.py:94` | 高 | 强行统一回 `settings.forge`→两域配置互相覆盖 |
| **C10 校验器“约束子集刻意最小”** | 校验 DSL 只支持 str/int/number/bool/list/obj + enum + required，像“能力不全” | 刻意最小子集，降低作者理解成本与误拦风险 | `qbot_rpg/content/validator.py:394` | 中 | 盲目扩展 DSL→校验语义面扩大、旧包判定变化 |
| **C11 模块目录“有意不放进可启用清单”的排除项** | 某些模块名不在可启用清单，像“清单漏登记” | 明确排除项（有意），不在清单内是设计 | `qbot_rpg/content/module_catalog.py:16` | 中 | 补进清单→暴露未完成/不应启用的模块 |
| **C12 条件引擎旧运算符/中文变量别名（`min→ge`、`max→le`、中英互译）** | 旧写法 `min/max` 语义像“取最小值”，却映射到 `>=/<=`，像“运算符写反” | 旧格式兼容别名 + 中英互译表；识别顺序精确键→别名→带 `{T}` 占位 | `qbot_rpg/core/condition_engine.py:96`~`:120`、`:154`、`:215`~`:227` | 高 | 删旧别名→旧任务/NPC/成就条件失效；按字面“修正”min/max→条件语义反转 |
| **C13 NPC 旧策略名 legacy 归一 + 迁移提示** | 旧定稿枚举 `first_match→condition`、`weighted→random` 等，像“策略名对不上” | 归一时标 `legacy=True` 并给迁移提示，不硬拒 | `qbot_rpg/core/npc.py:137`~`:149` | 高 | 删兼容→旧包 NPC 策略无法加载 |
| **C14 资源轴 `resource_custom` 兼容别名归一为 `resource`** | 同一类型两个名字，像“枚举值写错” | 契约 P-1 旧键兼容，加载归一 | `qbot_rpg/core/resource_axis.py:121`；`qbot_rpg/content/resource_axis_validator.py:175`；`qbot_rpg/content/resource_axis_models.py:38` | 高 | 删别名→旧职业资源轴红拦 |
| **C15 天气条件 `==` 为 `eq` 的兼容别名** | 同一运算符两种写法，像“op 写错” | 白名单 `eq`；`==` 为兼容别名，求值等价 | `qbot_rpg/core/weather_conditions.py:70` | 高 | 删 `==`→旧内容包天气条件失效 |
| **C16 事件键 `EVENT_KEY_DEFAULTS` 缺省回退现键（向后兼容零破坏）** | 事件键有“常量→默认键”两级回退，像“硬编码没删干净” | 零配置时回退现字面量，保证旧行为零破坏；`resolve_event_key` 集中解析 | `qbot_rpg/core/event_bus.py:27`、`:65` | 高 | 删默认回退→未声明事件映射的旧包行为变化 |
| **C17 `rng_state` V2 权威位 + `_rng_state` V1 旧键兜底读** | 快照里同时有 `rng_state` 和 `_rng_state`，像“字段冗余” | V2 权威位新键；V1 旧键保留兜底读，保证旧快照/旧代码可续 | `qbot_rpg/core/battle.py:5699`~`:5700` | 高 | 删旧键→旧存档续战随机序列/兼容读断裂 |
| **C18 hp/mp=0 合法（修复 `or 1` 致读档 0→1）** | 看到 `None 才兜底`，像“少了 `or` 兜底” | 0 是合法值（死亡/空蓝），只有 None 才兜底；`or 1` 曾是 bug 已修 | `qbot_rpg/storage/repository.py:324` | 高 | 加回 `or 1`→读档把 0 血/0 蓝变成 1，死亡/空蓝语义崩 |
| **C19 同 `item_id` 多件实例并存时只算穿戴件（防词条翻倍）** | `aggregate_bonus` 按 item_id 回查，曾把未穿戴行也聚合，像“聚合漏 filter” | 已按穿戴行精确区分（P1-1 修复），同 id 异词条互不污染 | `qbot_rpg/core/equipment.py:44`、`:198`~`:207`（`docs/审查报告/审查_M6实现_批1A_三引擎_jspace.md:83` 记录该 P1-1）；`tests/unit/test_equipment.py:276` | 高 | 回退成“遍历全部同 id 行”→未穿戴词条也加成，属性翻倍 |
| **C20 `any` 键与具名键并存时 `any` 优先（运行时防御）** | K3 本应校验器红拦互斥，运行时却“any 优先、具名忽略”，像“静默吞配置” | 运行时防御降级不抛异常；红拦归批11 V7（校验层），引擎不因坏配置崩 | `qbot_rpg/core/resource_axis.py:80`、`:587` | 中 | 改成抛异常/取具名→坏包直接崩战斗；改成叠加→资源门禁数值错 |
| **C21 渲染层“异常兜底不崩、绝不抛出”** | 多处 `except Exception: return 已装配行`，像“吞异常” | 明确铁律：渲染层任何异常→记日志并返回已装配行/空串，绝不抛出，保战斗响应可用 | `qbot_rpg/core/message_format/battle_render.py:2026`、`:78`、`:168`、`:269` | 中 | 让异常上抛→单条渲染错误导致整场战斗响应丢失 |
| **C22 素材来源确定性兜底文本“来源未知”** | 没标来源就填固定串，像“占位文案没做完” | SOUR-00 要求每条素材标来源；无标注时的**确定性兜底**，不抛不随机 | `qbot_rpg/content/forge_settings.py:35`~`:36`、`:107`~`:108`；`qbot_rpg/core/forge_material.py:150` | 中 | 改成报错/空→素材提示链路断，或输出不确定破坏确定性 |
| **C23 属性 `base/growth` 负数→黄提示、运行期按 0** | 负数被“放行”而非红拦，像“数值校验漏了” | 3b §4.2 / TC-17：负数→黄、运行期按 0（allow_negative） | `qbot_rpg/content/field_meta.py:334`；`docs/审查报告/审查_M0复查_content_field_meta_20260824.md:76` | 中 | 改红拦→旧包（含故意负成长）被拒；去掉按 0→负白值代入放大 |
| **C24 元数据未登记键走“兜底控件 + 显式标注”（不静默）** | 编辑器对未登记键仍渲染控件，像“元数据缺失没报错” | 原则：框架登记过按元数据、多出来的键走兜底但**显式标注**，不静默 | `qbot_rpg/web/api.py:2813`~`:2814`、`:2672`、`:3071` | 中 | 改成静默丢弃→作者配置被编辑器悄悄抹掉 |
| **C25 条件/组合求值“未知键→安全失败”（不静默恒真）** | 未知键直接判不满足，像“求值太保守” | P0-1 修复：原实现静默忽略未知键导致恒 True、派生无条件触发（反安全），改为安全失败 | `qbot_rpg/core/combo.py:602`、`:443`、`:530` | 高 | 回退为静默忽略→条件失效被当成立，派生技无条件触发 |
| **C26 调合终端结算幂等：hook 缺失不静默跳过扣料** | hook 缺失返回 False，像“扣料失败没兜底” | 原子防双扣：引擎不静默跳过扣料，缺 hook=不结算（宁可不做不可半做） | `qbot_rpg/core/alchemy_settle.py:339`、`:337`~`:341` | 高 | 加“跳过扣料继续结算”→白送产物、经济漏洞 |
| **C27 退出结算幂等键：同 message_id+group+qid 的不同结算类型“先到者胜”** | 不同 `kind` 却视为已结算、不双结算，像“去重键少了一维” | 明写 schema 约束：`command/kind` 不参与去重、仅落审计列；同消息视为已结算防双扣 | `qbot_rpg/world/battle_boundary.py:833`、`:840`~`:848`、`:859`、`:869`；`qbot_rpg/world/session.py:289`~`:310` | 高 | 把 kind 加进去重键→同消息重复结算/双扣风险回归 |

> 备注（样例 2 的“待查”落点）：`qbot_rpg/data/affinity_keys.py` 全文（`:1`~`:85`）**无 aliases 表**；
> 真正的“别名归并”见 C3 / C12 / C14 / C15。若手册坚持“affinity aliases”表述，需回填仓外来源。

---

### D. 判据类型：CHANGELOG 批次条目（含“刻意不修/明确排除/待裁决”）

| 候选现象 | 为什么“形似 bug” | 设计意图 | 判据来源 file:line | 置信度 | 若被误修会怎样 |
|---|---|---|---|---|---|
| **D1 批71 包专属残留清理：统一改法 = 包声明 + 框架读取 + legacy 兜底** | 框架里仍留包专属 id 兜底，像“清理没做干净” | 明确“包不声明→与现状逐字段一致”；**71-A2 删兜底被显式挂起**（框架单测无 registry 走 legacy、云海包在仓外无法确认全声明，故保留） | `CHANGELOG.md:17`~`:19`、`:25`~`:28`、`:32`~`:34`、`:39`~`:40` | 高 | 强行执行 71-A2 删兜底→框架单测/未声明包行为改变 |
| **D2 批70 旧键 `weakness_dmg_pct` 经战斗桥归并入 `damage_dealt_pct`（只算一次）** | 旧键仍可用且又新增轴，像“两份数值” | 新增唯一收口 `battle._damage_dealt_mult`；旧键经 pct 层归并、只算一次 | `CHANGELOG.md:43`~`:47`；`qbot_rpg/core/battle.py:4221`~`:4223` | 高 | 两处都算→弱点增伤翻倍 |
| **D3 批53 冷却旧占位键“激活并归并”、不双计** | `cooldown_reduction_pct` 与 `cooldown_pct` 符号相反、两键并存 | 旧键经 `route_legacy_aliases_into_flat` 换算一次 `flat["cooldown_pct"] += −旧值`；`route_bonus_into` 契约不变仍不进 flat/pct | `CHANGELOG.md:244`~`:253`；`qbot_rpg/data/gear_stats.py:26`~`:30`、`:754`~`:785` | 高 | 去重键/正负号当 bug 改→冷却减缩变增加，或双计 |
| **D4 批52 `immune_dmg` 作“负半轴别名”只乘一次；`effects` 的 mitigation 阶段按批50 不动** | `immune_dmg` 与新承伤轴并存且取负，像“符号写反 + 重复减伤” | 承伤乘区唯一求值处；旧免疫键作负半轴并入、只乘一次、沿用 [0,100] 封顶；**明示不得动 mitigation 阶段** | `CHANGELOG.md:265`~`:282`；`qbot_rpg/core/battle.py:4232`~`:4252`；`qbot_rpg/data/gear_stats.py:261`~`:264` | 高 | 见 §1-②/④：易伤变免疫、双计、或与护盾/保底交织 |
| **D5 批50 特效轴：无消费点的轴**不登记**；`legacy_alias` 只声明不改旧链路** | 登记表里有的轴“只登记不生效”，像“死配置”；旧键换算声明却不消费，像“写了没用” | 原则：无消费点不得登记（教训）；本批只登记、旧键链路不动，缺省/未配置→逐字段零变化 | `CHANGELOG.md:308`~`:319`；`qbot_rpg/data/gear_stats.py:56`~`:62`、`:582`~`:588` | 高 | 把“只登记”的轴当死代码删→后续批次接线锚点丢失；提前消费旧键→双计/行为变化 |
| **D6 批59/批56：`action_recovery_pct` 按裁决不登记、归 `DEPRECATED_EFFECT_AXES` 黄提示** | 明明有对应机制却“不实现、只黄提示”，像“功能漏做” | D2 裁决：`action_speed_mult` 与 `action_recovery_mult` 数学互为倒数、**必须二选一**，未裁决前不登记/不接线/不写测试 | `docs/深度打造_决策记录.md:1092`；`CHANGELOG.md:263`；`qbot_rpg/data/gear_stats.py:64`~`:68` | 高 | 两个都接→速度指数级加速（互为倒数并存） |
| **D7 批56 `overheal` 是布尔开关、**不是特效轴**** | 有强度/上限参数却不在特效轴表，像“登记遗漏” | D4：过量治疗是 E5 布尔开关，故不登记为轴；缺省=关闭=与现状一致 | `qbot_rpg/data/gear_stats.py:69`~`:70` | 中 | 硬塞进特效轴→与开关语义冲突，缺省行为可能改变 |

---

### 2. 未决/待查清单（供深挖，不建议直接写入手册结论）

1. **审计3 §6 合理并存清单原文缺失**：需从仓外补入，再与 §B（B1–B12）逐条对表。
2. **样例 2「affinity_keys.py 的 aliases 表」不在仓**：`docs/深度打造_决策记录.md:60` 只记「批38 相性通用层骨架」，
   是否另有相性别名/归并机制（如 `core/alchemy_affinity.py` 的 `main_sub_of`「主|副」优先）需专项 grep 确认。
3. **B5 门槛两口径、B12 能量开关双源**：属“已登记并存/待收口”，意图是“暂时并存，日后收敛”还是“永久设计”，
   需回查对应 ADR/仲裁，勿直接贴“勿修”标签。
4. **C8 改名旧名悬空**与 **B10 套装多技能**：仓库注释/审查均提示“容忍/未标注扩展”，
   是否属于“有意设计”还是“已登记待改进”，**低置信度，待查**。
5. **可能存在但本次未穷尽的模式**：`or` 默认值兜底（如 `settings.get(...) or DEFAULT`）、
   单位换算（`× 86400`、`/100` 百分点 ↔ 小数）、四舍五入 vs 向下取整（`int()`/`round()`/`floor()`）、
   上限/下限钳制（`clamp`/下钳 0/封顶 0.6）、静默跳过 vs 安全失败——建议后续按批扫描 `qbot_rpg/` 全量注释。

---

#### 附：本次最强的 3 个 file:line 依据（摘要用）
- `qbot_rpg/data/gear_stats.py:582`~`:588`（`EFFECT_LEGACY_ALIASES`：旧键→轴，`pct = sign × 旧键值`）
- `qbot_rpg/core/battle.py:337` 与 `:622`~`:627`（`@deprecated 批71` legacy 兜底 + `or` 不是 union）
- `docs/m9_启动包.md:75` 与 `docs/规划/规划_路2c2_锻造.md:142`（锻造 100% 确定性、无随机分支铁律）

---

## §8 三路编撰建议

> 目标读者两条线：**外部扩展开发者**（要照着做）与**未来维护者**（改框架前先看）。建议三路并行编撰，主 agent 汇总时按下面的"交叉引用表"接线，并把 §6 的 D 组缺口当作**必须先补的输入**（否则手册会引用不存在的唯一源）。

### 8.1 第一路《常量与数据结构》

| 章 | 内容 | 素材来源 | 建议篇幅 | 必带 |
|---|---|---|---|---|
| 1 | 阅读约定：唯一源/别名/可被包覆盖 三分口径 | §1 表头 | 0.5 页 | 术语表 |
| 2 | 装备键族（FLAT/PCT/COMBAT/PLACEHOLDER + 双兼容 `def`/`dfn`） | gear_stats.py:172-536 | 3-4 页 | 全键表 + 中文 label 列 |
| 3 | **特效轴全表**（17 轴 / 范围 / 默认 / 消费点 / 已接-待接） | gear_stats.py:230-447；§1.2 | 5-6 页（**本路最重**） | 逐轴 `consumer` + 接线状态；`EFFECT_CONSUMER_PENDING` 语义 |
| 4 | 枚举与时点（模块目录 36 / 组合 3 / 相性 / 符文 / 品质） | module_catalog.py:68；module_presets.py:58；affinity_keys.py；runes.py；quality.py | 4-5 页 | 每个枚举给"值域 + 校验处" |
| 5 | 阈值/默认值表（panel_budget / monster_scaling / craft_rules / temper / essence / effect_budget） | panel_budget.py:102,109；deep_craft_settings.py:110；temper_stats.py:70,106；gear_stats.py:894 | 3-4 页 | "默认值 + 覆盖段名 + 归一函数" |
| 6 | 数据结构字段级（Player/ItemInstance/EquipmentSlot/combatant/registry/ctx/状态与印记实例） | §2 全文 | 10-14 页 | 契约 vs 运行期双轨对照；`ctx` 约 170 键表 |
| 7 | **稳定契约与折旧**（哪些改动需评审） | §6 C 组 + §7 D 组 | 1-2 页 | 与 `docs/深度打造_决策记录.md` 互引 |

### 8.2 第二路《事件与扩展点》

| 章 | 内容 | 素材来源 | 建议篇幅 | 必带 |
|---|---|---|---|---|
| 1 | **两套"事件"体系辨析**（战斗时点 vs 计数事件键） | §3.0；core/event_bus.py:53 | 1-2 页 | 对比表 + 各自消费方 |
| 2 | `EVENT_POINTS` 逐时点（17 点） | §3.1 | 6-8 页 | **三态表：已接 / 二期未接 / 故意不派发**；每点给"何时派发 + 谁收 + file:line" |
| 3 | 易混对专章（death/on_kill、status/mark、turn_start/action_start、`on_*` 旧命名） | §3.1 易混表；D4 | 2-3 页 | 各一对正/反例 YAML |
| 4 | 归属（owner）规则 | §3.2；gear_stats.py:482-491；docs/深度打造_实现说明.md:754-763 | 2 页 | "两侧都没声明=全库扫描"的零变化口径 |
| 5 | 扩展点 E1/E2/E3 契约 | §4.1-4.3 | 6-8 页 | 声明形状 + 装载路径 + 双闸 + 失败隔离 + 安全线 |
| 6 | 稳定面 `qbot_rpg.ext_api`（唯一允许 import 的面） | ext_api.py:1-30, :42, :59, :125 | 3-4 页 | `EXT_API_VERSION` 兼容承诺边界 |
| 7 | **包声明段总清单（93 条）** | §4.5 + part4 §B | 5-8 页（可作附表） | 每条：段名 / 用途 / 读取处 / 可否覆盖 |
| 8 | hooks：对外 vs 内部（明确"哪些不是契约"） | §4.4 | 1-2 页 | 内部 hook 必须显式标"非扩展点" |

### 8.3 第三路《权责与「勿当 bug 修」》

| 章 | 内容 | 素材来源 | 建议篇幅 | 必带 |
|---|---|---|---|---|
| 1 | 三层权责（框架 / 内容包 / 包自持代码）+ 编辑器边界 | §5 A；web/editor_ops.py:671 | 3-4 页 | 每个角色"能改什么 / 改了谁负责" |
| 2 | 门禁地图（28 条） | §5 B.1 | 4-5 页 | 门禁名 / 把关点 / 失败后果 / 成文规定位置 |
| 3 | 最硬红线：红拦 5 类 → 整包拒绝 | loader.py:239；validator.py:1-30 | 1-2 页 | "只建议不限制"的边界 |
| 4 | **「勿当 bug 修」主清单**（本路最重） | §7 全文（引子任务盘点 ~40 条） | 12-20 页 | 每条：现象 / 意图 / 判据 file:line / 置信度 / 误修后果 |
| 5 | 判据体系：文档铁律 → 审计并存 → 代码注释 → CHANGELOG | §7 A/B/C/D 分组 | 2-3 页 | 置信度定义；低置信度条目标"待查" |
| 6 | 待裁决/待收口清单（不要贴"勿修"标签） | §7 未决清单 + §6 | 2 页 | 明确"并存≠永久设计"的区分 |
| 7 | 维护作业规程：改框架前 checklist | §6 + §8.4 | 1-2 页 | **本手册对维护者的核心价值** |

### 8.4 交叉引用表（三路汇总时必接的线）

| 主题 | 第一路 | 第二路 | 第三路 |
|---|---|---|---|
| 特效轴 `legacy_alias` | 轴表（§1.2） | `trigger` 无直接关系 | 别名归并"勿修"（§7 §1-② / C3 / D2/D3/D4） |
| `owned_effect_ids` | 键名常量（§1.1） | 归属规则（§3.2） | 声明+兜底双轨（§7 §1-③ / C1） |
| `EVENT_POINTS` | 枚举数量（§1.3） | 逐时点语义（§3.1） | `trigger` 未登记 → Y-19 黄提示（§7 A7/A8 哲学） |
| `settings.effect_axes` | min/max 声明（§1.2） | — | "引擎不写死、包声明钳制"（§7 相关） |
| `ext_api` 稳定面 | `ExtContext` 字段（§2.5.1） | E1/E2 契约（§4.1-4.2） | 权责"包代码不得改结算"（§5 A.2） |
| 包声明段 | `field_meta.json` 12 段（§4.5c） | 93 条清单（§4.5） | 编辑器只写包目录（§5 A.3） |
| 门禁 | 字段迁移门禁（§5 B.1） | Y-19/R-1 校验（§3.2） | 「勿当 bug 修」误修会触发的门禁（§7 各行"误修后果"） |

### 8.5 编撰前必须先补的输入（来自 §6 D 组）

1. **审计3 §6「合理并存清单」原文**——仓库内不存在（仅 `docs/深度打造_决策记录.md:1568` 转引）。要么从仓外补入，要么在手册中明写"以 §7 B 组的审计近似项为准"。
2. **批71 引用的 `批71_包专属残留_改造方案.md` / `框架体检报告.md`**——仓库内不存在（`CHANGELOG.md:18`）。第三路写"legacy 兜底勿删"时需要这两份的原始裁决。
3. **`EVENT_POINTS` 三态表**——建议编撰时**新做一次全仓 `_dispatch_event(` 扫描**并钉进手册（本盘点给的是 HEAD `d86d9dd` 的快照；批73 死代码清理后可能变化）。
4. **`on_*` 旧命名映射表**——设计文档（`on_turn_start`/`on_death`）与落地枚举（`turn_start`/`death`）不一致，需给"旧文档写法 → 现行键名"对照，否则外部开发者照设计文档写必失败（D4）。
5. **`EFFECT_AXIS_SPECS` 数量与注释同步**（C1）：要么改注释，要么在手册中直接声明"以表为准、数量随批次增长"。

### 8.6 时序与维护

- 用户已定：手册排在**批73（死代码清理）之后**编撰（`docs/深度打造_决策记录.md:1570`）。**本盘点基于 HEAD `d86d9dd`（批71 后）**；批73 若清理了 §7 中"只登记不生效"的项或 §6 的 legacy 兜底，第三路需先对表再落笔。
- 建议手册设**稳定契约章节**（改动需评审），并与 `docs/深度打造_决策记录.md` 的"落地登记"双向互引；`EVENT_POINTS`/`EFFECT_AXIS_SPECS`/`ext_api.__all__`/门禁清单四处**必须挂"唯一源 file:line + 自动校验处"**，否则下次更新仍会把故意设计当 bug 修。
