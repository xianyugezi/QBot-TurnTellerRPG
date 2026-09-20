# Changelog

本项目变更记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与
[语义化版本](https://semver.org/lang/zh-CN/) 约定（开发规则 §6.2 L400-417）。

- **条目口径**（细化_M6_质量门禁 D7 CHG-05 / 开发规则 §6.2 L415）：提交信息为 `feat`/`fix` 的
  变更进 Changelog（按里程碑聚合一句话，不逐 commit）；`docs` 仅文档变更不进。
- **小节约定**（D7 CHG-01）：小节分 `### Added` / `### Changed` / `### Fixed` /
  `### BREAKING`；当前无 BREAKING 变更时（D7 CHG-02）BREAKING 节不出现。
- **版本段**：M0-M6 均未发布，条目暂存 [Unreleased]（D7 §3.3「Unreleased → 发布时归档」），
  首个版本发布时按 Keep a Changelog 归档至文末版本段骨架。

## [Unreleased]

### Added

- **批65（2026-09-22）**：**编辑器「模块预设组合」（推荐组合）**。依据用户 2026-09-22 诉求 +
  一号原则（编辑器显示 = 框架能力全集）；决策记录 §二十八；使用说明 §一·5 / §十·10。
  **① 框架默认组合**（`content/module_presets.py`）：`basic_rpg` / `life_adventure` /
  `story_exploration` 三组（中文名 + 一句话说明 + 适用人群 + 模块键），模块键自检必须真实登记。
  **② 依赖闭包**：组合模块的前置按 `module_catalog.requires` **递归补勾**（如生活冒险包自动补
  `maps` / `effects`），机制不写死任何模块名 / 依赖名。**③ 生效组合 = 框架默认 ∪ 包声明 − 关闭**：
  同 id 包声明整体覆盖、新 id 追加、`manifest.module_presets_disable` 关闭；**包没声明 → 框架默认
  照旧显示**。**④ 一键应用**（`editor_ops.apply_module_preset` + `POST /module-preset/{id}/apply`）：
  **累加不覆盖**已勾模块、单次 manifest 备份 + 原子写 + 回读复核（「回退最近一次模块变更」可
  一键撤销整组）、未知/未实装模块黄提示跳过、只读身份拒绝。**⑤ 前端**：⚙ 面板顶部「推荐组合」区
  （卡片内容全部来自后端、前端零模块键；应用后提示「已自动带上：…」）+ 两处空态引导（左栏
  「未启用」分组旁一行引导；中栏 0 条区分「还没启用任何模块」/「已启用但还没条目」）。
  验收：空包一键 basic_rpg → 12 模块就位 → 可新建条目；先手勾 1 个再应用组合不覆盖；应用后
  一键回退整组撤销；不做任何操作整包逐字节不变。页脚批次串 →「批65 · 模块预设组合」。

- **批62（2026-09-22）**：**深炼金口径 C（品质型）+ `/淬炼` 独立指令壳**。依据
  `深炼金相性_玩法口径_可开工版.md` §五 + `深炼金接入_施工清单.md` 批59-B·B4；
  决策记录 §二十七；实现说明 §二十四。**① 口径 C 品质型**：新增
  `data/affinity_keys.AFFINITY_EFFECT_QUALITY_CAP`（`quality_cap_delta` 键名唯一源）+
  `core/alchemy_affinity.quality_cap_delta`（复用 `main_sub_of` + `resolve_affinity_effect`，
  `"主|副"` 优先、负值下钳 0）；`core/alchemy_settle._extra_cap` 加**第 ④ 源**，与
  SP/核心/挑战**同机制同单位可叠加**、仍 ≤100，不写快照/不新增乘区/不动管线顺序；
  `validator` 内层键空间放开 `quality_cap_delta`（其余非法键照旧红拦）+ ALC-26 help 补语义。
  验收：材料均值 70 被 `quality_cap=59` 卡住 → 相性 +10 → 69 / `rare`（档位真提升）；
  无相性 → 59 不变；四源求和 ≤100；`coef` 恒等 `coef_for(tier)`；缺省与基线 `cff0562`
  逐字段一致。**② `/淬炼` 指令壳**：批57 引擎/状态/配置/校验之上补指令——四源扫描
  **零冲突**选定 `淬炼`（沿用 `/精造` 登记流程：注册 + 白名单 + `check_consistency` 双向一致 +
  计数/契约同步）；提供查看上限/已投/剩余/每点消耗、执行单项/多项（`*` 点数 + `,` 多项、
  先全量校验再一次落账）、越限/精粹不足/未启用/守卫全部模板表人话（**禁 emoji**）；数值
  全部委托 `core/temper.py`。**端到端**（`content/zz_craft_demo` 只读临时副本）：查看
  （0/30、每点 1593）→ `atk*2`（atk 12→14、扣 3186 精粹、落档 `{atk:2}`）→ 越限
  （单项上限 15，拒绝零写）→ 未启用提示。**明确不做（规格判定）**：成功率型（§5.3——
  定稿 100% 成功、无该字段）、特性/超特性出现率型（§5.4——玩家自选改概率出现属交互模型变更）。
  **缺省零变化**：不配 `affinity_effects` / `temper.enabled=false` → 逐字段不变；双尺子复算
  逐字节一致（未改战斗数值）。页脚批次串 →「批62 · 深炼金口径C与淬炼指令」。
- **批61（2026-09-22）**：**深炼金口径 B「相性 → 追加效果 / 状态」接入**。依据
  `/root/deliverables/深炼金接入_施工清单.md`（预检 · G2/G5 已消解）+
  `深炼金相性_玩法口径_可开工版.md` §四/§六/§七/§八；决策记录 §二十六；实现说明 §二十三。
  **① 求值**：新增 `core/alchemy_affinity.plan_effect_refs`——**池查询唯一入口**
  `core.affinity.resolve_available_entries` → 按既有载荷键 `effect_ref` 分流 → **复用**
  `core.deep_craft._pick_weighted` 加权不放回抽取；不重算池、**不新增 schema / 配置键**。
  **② 写实例**：`ItemInstance` 追加 `effect_refs`（默认空元组，零迁移）；`alchemy_settle._produce`
  抽中才传 `add_item(effect_refs=…)`（空值不传 kwargs、不消耗 `ctx["rng"]`）；
  `assembly/context` + `runner` + `repository` 逐字段透传。**③ 使用链路**：
  `/道具` 把实例 `effect_refs` 并入既有效果扫描——heal/gain_currency/learn_skill 走同分支
  （追加效果），其余落**既有** `active_effects` 状态桶（`{effect,turns,refreshed}`，同
  `npc._action_buff`）。**端到端**（`content/zz_craft_demo` 只读临时副本 + 池追加 effect_ref）：
  同配方仅材料相性不同 → 产物 `effect_refs` 分别命中 moon/frost 两条附加 → `/道具` 后落两条
  状态实例（turns 3 / 5）。**缺省零变化**：池无 `effect_ref` → `picked=[]`、不消耗 rng、
  逐字段与基线 `6f858a1` 一致。**未做/待裁决**：`effect_ref` 引用存在性校验、抽几条/谁抽
  （规格 Q4，不写死数值）、非战斗状态衰减 ticker、战斗内口径（同批60）。
  页脚批次串 →「批61 · 深炼金口径B」。
- **批60（2026-09-22）**：**深炼金「相性 → 药剂效果」接入（第 1 步：G1 材料相性进快照 +
  口径 A 强度型）**。依据 `/root/deliverables/深炼金接入_施工清单.md`（预检）+
  `深炼金相性_玩法口径_可开工版.md` §三/§六/§七；决策记录 §二十五；实现说明 §二十二。
  **① G1**：`core/alchemy_core._resolve_material` 出参追加 `affinities`；
  `apply_feed` 复用 `core/affinity.accumulate_affinity` + `rank_affinities`（与打造
  `resolve_main_sub` 同口径）；`new_snapshot`/写回各加 `affinity_values`/`affinity_main`/
  `affinity_sub`（**零迁移**，缺省空 = 零行为变化）。**② 口径 A**：新增
  `core/alchemy_affinity.py`（`main_sub_of` / `axis_pct`，复用相性四接口 + `GEAR_EFFECT_KEYS`
  + `normalize_effect_axes` 钳制，**不新造 `effect_mult`/区间表**）；非战斗 `/道具` 治疗路径
  按实例相性 `heal_total = int(round(heal_total × (1 + pct/100)))`（同 `effects.heal_apply`
  同式同取整）。**③ G3/G4**：`alchemy_settle._produce` 传相性值 +
  `assembly/context.add_item` 实例通道落 `affinities`（`runner`/`repository` 批42 已透传）；
  `/道具` 读实例（不再只读物品定义）。**④ 配置**：`settings.alchemy.affinity_effects`
  （field_meta ALC-26 + 校验器键空间红拦 V1~V3）。**端到端**（`content/zz_craft_demo`
  只读临时副本）：同配方仅材料相性不同 → 产物实例 `{lunar:16}` / `{frost:11}` → 回血
  **120 / 90**。**未做**：T1 冻结疗效 / 品质型 `quality_cap_delta` / 口径 B 词条抽取
  （施工清单 C5、B4、B5-B 留后续批）；批量 `/炼金 *N` 不带相性（与丢特性同列）。
  页脚批次串 →「批60 · 深炼金相性接入」。
- **批59（2026-09-22）**：**特效体系小尾巴：奖励轴登记（D5）+ 过量治疗上限/去向（BV-1/2）+
  速度预算坐标（BV-3）+ m1 flake 根治**。依据 `docs/深度打造_决策记录.md` §十五 D5 +
  §二十一 批56 待裁决；实现说明 §二十一。**① D5 奖励轴**：登记第 17 条特效轴
  `reward_mult_pct`（X43，D1 百分点口径，**`min: 0` 下钳 0**；`bridge="settlement"`
  **不进战斗桥**）。**消费点待接**（`reward.dispatch_reward` / `battle_reward.
  settle_battle_rewards` / `roll_death_drops` 三处分散、无唯一收口）→ 只登记轴 +
  下钳语义，**不为交差硬造消费点**；编辑器可见（items/equipment 字段表）。
  **② BV-1**：`overheal` 段新增 `cap_pct`/`cap_flat`（最多超出 max_hp 的 %/点，同给取
  更小），**缺省都不给 = 无额外上限**（与批56 现状逐字段一致）。**③ BV-2**：
  `overheal.mode ∈ keep|discard` 把去向选择点**显式表达**；`shield`（转护盾）为**未实现**
  保留位（校验器 R-1 红拦 + Y-21 黄提示「未实现」）→ **不做半成品开关**。
  **④ BV-3**：`EFFECT_AXIS_WEIGHTS` 登记 `action_speed_pct`（`calib=+20 ⇔ output=+20%`，
  依据实现说明 §18.7；可配）→ 闸不再报 `unknown_axis`。**⑤ m1 flake 根治**：根因 =
  `true`/`false` 降级 Node + 30ms vm watchdog 抖动误报（实测 2%~12%）→ 公式兜底 0；
  修 `_VM_CTX_SLACK_MS` 20→90（有效 100ms；`FORMULA_TIMEOUT_MS=10` 执行预算契约不变）
  + 布尔字面量走 Python 快路径（探针 400 次 0 失败）。**零变化**：不配置新键/新段 →
  双尺子修前=修后（工具尺 7/20/24；档位尺 Boss 越档结论与批55/56 一致，非本批引入）。
  页脚批次串 →「批59 · 特效小尾巴」。
- **批58（2026-09-21）**：**深打造示例包 `content/zz_craft_demo`（内容数据落地）**。
  依据 `/root/deliverables/打造_材料表与图纸表_草案v2.md`（24 材料 / 6 图纸 / 暴击参数 /
  逐档手算）+ `深炼金相性_玩法口径_可开工版.md` §七（相性四段形状）+ 批54
  `content/effect_presets.py`（26 条取 11 条）+ 批57 淬炼/精粹默认值；
  实现说明 §二十（用户向「示例包怎么用」）。**① 包骨架**：`manifest.json` + `field_meta.json`
  （中文模块/字段名，编辑器零改动）+ `settings.json`。**② 相性四段**：4 相性 / 11 池 /
  1 联动 / 3 互动（冲突 `ember×frost`、增幅 `lunar×frost`、反转 `frost→lunar`）。
  **③ 打造参数**：`craft_rules`（等级权重 / 取整 / 阈值 / 件数边际 / 种类奖励 / cost /
  逐档暴击）+ 4 档图纸（copper/silver/gold/rainbow，cap 900/2100/4200/8600）+
  `quality_exp_by_color`（10/16/26/42/70/110）——数值全部来自草案 v2。**④ 数据**：
  24 材料（每档 6）+ 6 图纸（铜2/银2/金1/彩1）+ 6 装备 + 6 配方 + 8 被动 + 8 被动效果 +
  `forge` 武器树 + `enhance.temper`。**⑤ 特效预设**：11 条落成示例词条（normal 档原值），
  含 2 对双方向（会心 ±10、受疗 ±15）。**⑥ 实测**：`/精造` 两次打造 uid/随机词条不同 →
  `/分解 <uid>` 得材料 + 精粹 → `core/temper` 淬炼加值/扣精粹/越限拒绝；
  无相性 → `requires_affinity` 词条抽不出（负向断言）。**红线**：`content/veinborn`
  一个字节未改、框架代码零改动；示例包跑既有校验器 **红拦 0 / 黄提示 0**。
  页脚批次串 →「批58 · 示例包数据」。
- **批57（2026-09-21）**：**装备淬炼（temper）+ 分解回收（精粹）**。
  口径 `/root/deliverables/淬炼与分解回收_实现口径.md`（C-1~C-7 / §2 / §3 / §4 / §5）+
  用户原案 §10/§14/§12 + `docs/深度打造_决策记录.md` §二 N5 / §十五 D 组；
  实现说明 §十九。**① 淬炼**：配置落 `enhance.json → temper`（默认 `enabled=false`），
  引擎**另立 `core/temper.py`**（纯函数；**不改既有强化成功率/失败段**）；状态挂
  `ItemInstance.temper_alloc`（`uid` 锚定）**增量幂等物化进既有 `stats_bonus`**
  （面板聚合/战斗桥/展示零改动）；上限按装备等级（新字段 `required_level`，打造写入）
  `等级×cap_per_level` + 单项 `floor(总×ratio)`，全部可配；消耗装备精粹（货币载体，
  D4），`cost_per_point.essence=1593`；**与强化分账**（`enhance_level`/`temper_alloc` 分存）。
  **② 分解回收**：**新开实例级路径**（既有 `/分解` 按 `item_id`、分解不了 uid 实例）——
  精粹启用时按 uid/名称定位打造实例，产**材料（`decompose_rate`）+ 精粹（`essence_rate`）
  两套率分键、语义相反不可合键**；`temper_refund` 随淬炼量**衰减**。**两处数值问题**：
  **（C-6）84:1 失衡 → 两侧同时定**，典型循环（分解 95 件 ↔ 满淬 5 件）产出/消耗
  **0.9999×**（报告 `p=1` 时 1593×），反解平衡点 ≈1593；**（C-7）β^色序 闸门无效 →
  真闸门**（β 降为正向系数 1.2；不可逆 + 返还衰减），20 轮模拟每轮净变化
  **−215,320 < 0**、余额单调递减 → **无套利**，校验器 V8 硬拦 `refund > cost`。
  **零变化**：不配 `temper`/不启用精粹 → 既有 5 段配置逐字段一致、红线复算
  （`batch45_measure` + `batch55_dual_ruler`）**修前=修后逐字节一致**。
  页脚批次串 →「批57 · 淬炼与分解回收」。
- **批56（2026-09-21）**：**行动速度轴（D2）+ 过量治疗开关（D4）+ 奖励轴核查（D5）**。
  口径 `docs/深度打造_决策记录.md` §十五 D 组裁决；`特效整理设计_1_修正轴全集.md`
  X28（行动速度）/ X29（后摇·废弃）/ §4-E5（overheal）。**① D2**：登记第 16 条特效轴
  `action_speed_pct`（双向 `-80~400` 百分点，范围由 `settings.effect_axes` 可配），
  消费点 = CTB **有效速度**（`battle._ctb_actor_speed` → `ctb_rules.time_cost` 分母，
  复用既有求值，不新开管线；`min_speed` 下限保护沿用）。**`action_recovery_pct`
  不登记、不实现**（二者互为倒数，并存会指数级加速）→ 进 `DEPRECATED_EFFECT_AXES`，
  校验器对声明/词条命中者给**黄提示**（点名改用 `action_speed_pct`，不硬拦）。
  **② D4**：新增 `settings.overheal = {enabled: bool}`（E5 = 布尔，不是数值轴）；
  缺省/关闭 = 与现状一致（按 `max_hp` 封顶、过量**丢弃**），开启 = **保留**（HP 可超上限）；
  5 处治疗落点收口 `effects.apply_heal_to_hp`，只对 HP 生效。设计未写清的**过量上限 /
  是否转护盾**进「待裁决」（不设额外上限、护盾不动）。**③ D5**：奖励类轴（掉率/经验/货币）
  核查确认**尚未接线**（既未登记为特效轴，也无消费点；`reward._SCALAR_KEYS` 只有
  coins/gem/exp/rep）→ **无处可钳 0**，如实登记到奖励轴批（届时在轴上写 `min: 0`），
  **不为交差硬造消费点**。**零变化**：不配置新键/新段 → 战斗结算快照与字段元数据逐字段
  一致；双尺子复算 工具尺 7/20/24、档位尺 Boss 越档结论**与批55 完全一致**（非本批引入），
  速度轴对斩回的乘性影响单列敏感性表（**只报告不擅调**，建议校准批给权表坐标）。
  页脚批次串 →「批56 · 速度轴与过量治疗」。
- **批54（2026-09-20）**：**框架特效预设集落数据**（P + 结算轴核查）。
  口径 `特效整理设计_2_框架预设包.md` §1（预设词条集）/ §2（成套预设）/ §4（速览）+
  `特效整理设计_1_修正轴全集.md` §3 P1 第 16 项，**复用既有 `content/entry_presets.py`
  机制（不新造一套）**。**① 框架预设集**：新增 `qbot_rpg/content/effect_presets.py`——
  设计 §1.1~§1.3 的 **26 条**预设族（武器 9 / 护甲 8 / 饰品 9）落成框架级声明，每条给
  「id / 中文名 / 一句话说明（≤60 字·忌长文）/ 使用的轴与档位取值 / 适用部位 / 叠加与互斥」；
  **同族两方向 = 两条预设**（如「重伤」`healing_received_pct: -15/-30/-50` ↔「强疗」同轴
  `+15/+30/+50`，同 `conflict_group` → 互斥；执行仍走既有装备互斥链）。**② 复用**：
  预设经 `entry_presets_for()` 投影成既有同形条目，由同 `merge_entry_presets`（框架默认 ∪
  包覆盖 − `entry_presets_disable`）/ 同 `web/api.new_entry_detail` 供编辑器直接选——
  **`items` 六种通用品类逐字段不变**，模块 `equipment` 零前端改动即可见。**③ 校验**：
  `effect_preset_errors()`——引用轴存在 / 三档取值在轴有效区间（**越界红拦**）/ id 唯一 /
  部位与方向合法 / `defaults` 取普通档。**④ 结算/奖励轴 `reward_mult{scope}` 如实报告不登记**
  （P1 尾项）：核查既有消费点确认**无可复用唯一收口**——标量走被非战斗系统共用的
  `reward.dispatch_reward`、战斗 `exp` 走 `LevelUpEngine.gain_exp`、掉率走 `roll_death_drops`，
  三处分散且扁平键空间无法承载 `scope` 而不违设计「勿造三键」→ **不为交差硬造**。
  **零变化**：不选预设 → 新建条目逐字段与批17 一致，框架新增不影响任何既有条目 / 战斗结算；
  红线复算 `batch45_measure.py` 修前/修后 `--json` **逐字节一致**。**不写进任何内容包**
  （框架预设 ≠ 内容数据）；数值全取设计档位示意（`_mult→_pct` 精确换算），不调数值平衡。
  页脚批次串 →「批54 · 预设集与结算轴」。
- **批55（2026-09-20）**：**特效强度预算 `effect_budget`（另立上限）+ A1 度量 + 方案 C 备用**。
  口径 `特效强度预算_设计.md` §二方案 B + §三推荐（B 主 + A1 度量 + C 备用）+ §四 红线守护。
  背景：批45 的 60% 只覆盖 `atk/dfn/hp`（`PANEL_AXIS_KEYS` 冻结），批50~53 接线的特效轴
  **不进 `equip_share`** → 实机口径会把 Boss 压到 ≈39–41（贴死 40 下沿）。
  **① 主闸（方案 B）**：`data/gear_stats` 新增坐标权表 `EFFECT_AXIS_WEIGHTS`
  （`等效% = 轴值/calib × 校准等效%`）→ 聚合器 `effect_equiv`（geometric/product/max）→
  按档位 `cap_equiv_pct × tier_mult` 判超限 → `gate_mode`（off/warn/red）决定 静默/黄提示/拒绝；
  缺省 `cap 8% × 1.5/1.0/0.625 = 普通12%/精英8%/Boss5%`，`enabled=false`（不配置即零行为）。
  **② A1 度量**：`core/panel_budget.effective_equip_share`（只报数不改数）常驻输出
  —— 典型生存 build 真实装备占比 **43.73%**（显式登记，红线 C3）。
  **③ 方案 C 备用**：`monster_scaling.effect_hp_mult/effect_atk_mult`（缺省 **1.0**，
  与 hp/atk 倍率相乘；改回 1.0 即回滚）——**本批不配置**。
  **④ 校验器**：`_check_effect_budget`（段结构/类型/枚举/负值红拦 + `calib=0` 黄提示 Y-20）
  + `_check_effect_budget_entries`（条目级越界两态：warn=Y-20 / red=R-5 / off=静默）；
  **⑤ 编辑器**：`settings.effect_budget` 中文名 + 8 子字段说明卡。
  **⑥ 双尺子复算**：`scripts/batch55_dual_ruler.py` —— 工具尺（batch45 口径 7/20/24，
  公差 ±1）对拍**本批缺省零变化**；典型生存 build 后 Boss **Δ−2 超公差**；定稿档位尺
  （红线 3-8/10-15/40-60）**Boss 38.69~40.52 越档**（跌破 40），闸上限 5% 守约后回到
  **≥45.77 ∈ 档**。缺省零变化：不配置 → `--json` 逐字节一致、`equip_share = 60%` 不变。
  页脚批次串 →「批55 · 特效强度预算」。
- **批53（2026-09-20）**：**时序 / 资源 / 结算轴接线**（K，P0+P1）。
  口径 `特效整理设计_3_落点与分期.md` §二「批 51」（旧编号 = 本批批53）+
  `特效整理设计_1_修正轴全集.md` X27/X21/X22/X23/X24/X30/X34/X35/X03 +
  `特效强度预算_设计.md` §四（红线守护）。**全部复用既有唯一消费点，不新开乘区**。
  **① 冷却乘法轴 `cooldown_pct`**：接既有 α3 技能冷却管线（与 α3 **同乘区相加后一次缩放**，
  结果 `max(0,…)`）；旧占位键 `cooldown_reduction_pct` **激活并归并**——`route_bonus_into`
  契约不变（仍不进 flat/pct），新增 `data/gear_stats.route_legacy_aliases_into_flat` 在聚合入口
  换算一次 `flat["cooldown_pct"] += −旧值`（旧键仍可用、**不双计**；与 §三 C-05 的偏差按用户
  口径登记）。**② 状态概率 `status_chance_pct`**：接 `apply_status` R1 命中判定（source 侧），
  `>100%` 溢出按每满 100% 折 1 层；归并悬空旧键 `debuff_chance_pct`/`buff_chance_pct`。
  **③ 状态抵抗 `status_resist_pct`**：扩展既有 `resist_table`（加算百分点、0..100 钳制，target 侧）。
  **④ 层数获取/上限 `stack_gain_pct`/`stack_cap_delta`**：接 `apply_status` 的 stack 框架增量与
  `max_stack`（与批48 `stacks` 乘算对齐）。**⑤ 行动条推动 `action_bar_shift`**：接
  `_after_actor_action` 收尾，复用 `hasten_actor`/`delay_actor` 双向原语。**⑥ 资源消耗/获取
  `resource_cost_pct`/`resource_gain_pct`**：`resource_axis` 既有门禁/扣款/入账加 `mult` 形参
  （唯一缩放处 `scale_amount_map`，下钳 0）。**⑦ 会心倍率 `crit_damage_pct`**：会心乘区等比缩放
  （crit_roll 之后、入 rating 之前；与超会心/属性会心不合并）。
  **缺省零变化**：不配置任一轴 → 战斗结算快照逐字段一致；红线复算 `batch45_measure.py`
  修前/修后 `--json` **逐字节一致**（普通 8/7/7、精英 22/20/19、Boss 26/24/22），
  `equip_share = 60.00%` 不变。**明确排除** `action_speed_mult`/`action_recovery_mult`
  （数学互为倒数、必须二选一，待裁决 D2）。页脚批次串 →「批53 · 时序与资源轴」。
- **批52（2026-09-20）**：**治疗 / 承伤双向轴接线**（M + K，P0 核心玩法）。
  口径 `特效整理设计_3_落点与分期.md` §二「批 50」（旧编号 = 本批批52）+ `特效整理设计_1_修正轴全集.md`
  §5-D2（X17/X16）/ §5-D3（X02）+ `特效强度预算_设计.md` §四（红线守护）。
  批50 只登记不接引擎；本批让三条轴**真生效**。
  **① 受疗轴 `healing_received_pct`**：新增唯一收口 `core.effects.heal_apply`——
  批48 重伤状态通道（`heal_taken`，经 S6 `cap_boost` 封顶）与新轴**同轴相加** → 按
  `settings.effect_axes` 声明区间钳制 → `round(基础 × (1 + 受疗/100))`；**双向**
  （<0 减疗 / >0 增疗）；**负治疗**：合计 ≤ −100 治疗转伤害（下界由包声明，默认 −200）。
  **② 出疗轴 `healing_done_pct`**：同一收口按 **source（施疗侧）** 取值；旧悬空键
  `heal_amp_pct` 经 `data.gear_stats.combatant_updates(flat, pct=None)` 按
  `axis += sign × 旧值` 归并进本轴（旧键自身路由不动）。**③ 多源一次改全**：
  `heal` 原子 / absorb_heal / regen / lifesteal / `battle.absorb_hp` 五处全接唯一收口。
  **④ 承伤轴 `damage_taken_pct`**：`battle._damage_taken_mult` 为**承伤乘区唯一求值处**
  （收敛口径 D3(b)）——**减伤/易伤一轴**，`immune_dmg` 作负半轴别名 `pct = −immune`
  只乘一次、**不双计**；读时按声明区间钳制；status `damage_mult`（倒地增伤）在同一函数内
  并入（破位窗口门控不变）→ 三路来源一处求值。**既有行为影响（如实登记）**：唯一受影响
  组合 =「破位 + 非零 `immune_dmg`」截断序改变可能少 1 点；无 `immune_dmg` 且无轴时逐位一致、
  `effects` 的 `mitigation` 阶段按批50 `consumer_note` 不动（详见决策记录 §十八.2）。
  **⑤ 声明段接线**：`settings.effect_axes` → 引擎配置 → `EffectRuntime.config`；
  新增 `data/gear_stats.EFFECT_AXES_KEY` + `effect_axis_value`（读时钳制，不写死区间）。
  **缺省零变化**：不配置轴 → 治疗原值 / 承伤乘区 1.0 / 战斗结算快照逐字段一致；
  红线复算斩杀回合三档逐格 0 变化（普通 8/7/7、精英 22/20/19、Boss 26/24/22），
  `equip_share = 60.00%` 不变。页脚批次串 →「批52 · 治疗与承伤双向轴」。
- **批51（2026-09-20）**：**触发归属与事件补点**（K，P0 缺口；**装备被动系统的前置**）。
  口径 `特效整理设计_3_落点与分期.md` §二「批 49」（旧编号 = 本批）+ `特效整理设计_1_修正轴全集.md`
  §3 P0 第 1 项（I01）+ `装备被动_实现口径.md` §3.3 方案 A。
  **① 归属过滤**：`core/event_dispatcher` 的 `_iter_candidates`/`dispatch_event` 新增
  `owner_effect_ids`（本侧拥有集）+ `claimed_effect_ids`（本场被任一持侧认领集，未认领 =
  全局效果照常触发）——带 `trigger` 的效果只在其**宿主侧**触发；两者缺省 → 全库扫描旧行为。
  **② 事件补点 `on_kill`**：`EVENT_POINTS` 补 `on_kill` = **我击杀敌**（派发给击杀者侧），
  与 `death` = 任一侧死亡（派发给死者侧）语义分清；在唯一死亡判定点 `_death_check_side`
  派发、`dead_mark` 门控恰好一次，覆盖「连段套中击杀」与「BOSS 死亡立即结束」两路径。
  枚举**唯一源下沉 `data/event_points.py`**（content 层校验器按 `content → {data}` 校验
  `trigger` 取值域，不反向 import core；`core.event_dispatcher.EVENT_POINTS` 原样再导出）。
  **③ 校验器**：`trigger` 未登记时点 → **黄提示 Y-19**（分派器只认 EVENT_POINTS，
  该效果永不触发）、非字符串 → 红拦 R-1（覆盖 effects 与 runes 两处声明面）。
  **④ 装备触发型效果最小接线**：`data/gear_stats.OWNED_EFFECT_IDS_KEY`（键名唯一源）+
  `core/equip_mods.worn_passive_effect_ids`（已穿戴件实例 `passives` 经批40 `uid` 定位 →
  `traits.effects` → effect id 集；复用 `_worn_defs` 副手失活过滤；只读不落缓存）→
  `_player_combatant` 有装备被动才写 combatant 归属集（无 → 不新增键）。
  **缺省零变化**：两侧都无归属集 → 全库扫描（既有 16 时点逐字段对拍一致）；
  未声明归属的旧内容行为不变；装备接线缺省不新增任何键。**不实现完整被动系统**
  （被动声明字段/相性变体/生效集缓存/展示属后续批）。页脚批次串 →「批51 · 触发归属与事件补点」。
- **批50（2026-09-20）**：**特效轴地基**（P + 小 K，**不含任何消费点**；口径文档
  `特效整理设计_1_修正轴全集.md` §2/§3 + `特效整理设计_3_落点与分期.md` §1.0/§1.2
  + §二「批48」（旧编号）+ 决策记录 §十三）。
  `data/gear_stats.py` 新增 **EFFECT 键族** `GEAR_EFFECT_KEYS` + 逐轴登记表
  `EFFECT_AXIS_SPECS`（唯一源）：本批只登记轴全集定级 **P0/P1 的 15 条轴**（P0 8 / P1 7），
  **每条轴都写出「唯一消费点（本批待接）」**；无消费点的轴不登记（`cooldown_reduction_pct`
  的教训）。新增包声明段 **`settings.effect_axes`**（`min/max/default/display/stack/legacy_alias`，
  范围与默认值可配、不写死）；`route_bonus_into` 把 EFFECT 键按 COMBAT 例外**留 flat、不进
  属性 pct 层**；`combatant_updates` 加**桥接行**（只桥接、不求值，缺省 0 → 行为零变化）；
  校验器新增**越界红拦 / 未知轴黄提示 / 面板三轴 stem 冲突红拦** + 内容侧取值越界红拦；
  字段元数据与编辑器可见（中文名 + 说明卡 + 双向提示）。**缺省/未配置 → 全量回归逐字段零变化**
  （registry 对拍 + 一场战斗的结算快照对拍）。页脚批次串 →「批50 · 特效轴地基」。
- **批48（2026-09-20）**：**符文 2/3 阶特殊效果 + 战斗接线 + 3 合 1 端到端**（口径文档
  43-C/43-D；原案 §9 R6/R7/R8），含口径 §〇 结论 7 两处**机制缺口**修复。
  **缺口①重伤（治疗削减）**：`core/effects.py` 新增 `HEAL_TAKEN_STAT` 语义键 + 唯一聚合收口
  `status_stat_modifier_sum`（**复用既有 `stat_modifier` 状态动作族**，不新造第二套减益通道），
  `heal` L0 动作在**治疗计算处**按 `1+heal_taken/100` 消费（下限 0、S6 封顶可配）。
  **缺口②层数型增益**：`_aggregate_boost` 改为按状态实例 `stacks` **乘算**（上限 = 状态包声明
  `max_stack`，缺省回落 `config.stack_default_max`）——聚合体下沉 `effects.status_stat_modifier_sum`
  （battle 只保留 S6/S7 封顶）；附**逐字段回归对拍**（批48 前算法逐字复制为基准，非 stack 路径全等）。
  **战斗接线**：`core/runes.py` 新增 `rune_effect_refs_of`；ctx 级取数 `active_rune_effect_refs`
  落 **新模块 `core/rune_battle.py`**（组合层，避免 `runes ↔ equipment` 架构环），
  `EquipmentEngine.active_rune_effects`（同一 worn 枚举 + 同一 `active_rune_sockets`，副手失活继承），
  `dispatch_event` 新增 `extra_candidates`（缺省 None 零破坏），`BattleEngine._rune_candidates` 按侧/时点
  执行符文声明效果（`combatant.rune_effects` 随快照往返；无符文不新增键）；符文施加来源按次区分
  `侧@行动序号` → 既有 S3 stack 逐次叠层（**不改 `apply_status` 行为**）。
  **3 阶偏向性**：`bias={affinity,bonus_pct}`，宿主主/副相性（批38 `core/affinity`）命中 → 数值
  ×(1+bonus_pct/100)（RUNE-07 形状校验）。**3 合 1 端到端 + 闸**：`_exec_rune` 新增
  `synth_allowed=false → runes_deep_locked`、`settings.deep_craft.enabled` 非 true → `runes_disabled`
  （ctx 无该段不额外收紧）；1→2→3 逐阶、禁跳级、失败原子回滚。页脚批次串 + 文档同步。

- **批47（2026-09-20）**：**符文 1 阶数值 + 跨装备类型差异生效**（口径文档 43-B；原案 §9 R2/R4）
  —— `core/runes.py` 新增 1 阶数值**求值层** `rune_stats_of` / `sum_rune_stats`（`by_equip_type`
  的 default + **`items.type`** 覆盖差异解析**只在此处发生**；键白名单 = `GEAR_NUMERIC_KEYS`
  唯一源，自造键由校验器红拦）；`core/equipment.aggregate_bonus` 新增**符文数值贡献段**
  （**唯一收口**）——每件已穿戴装备经 `JewelSystem.active_rune_sockets`（**孔位读取唯一入口**，
  副手失活自动继承）读激活符文，按装备类型解析后走**同一** `route_bonus_into` flat/pct 路由
  （**不新开聚合/键**）；`EquipmentEngine`/`EquipmentEngineAdapter`/装配层注入
  `runes`/`items`/`jewel`（缺省 → 零贡献，既有行为逐字段一致）。**孔位互斥补对向**：
  `JewelSystem.mount` 新增「该孔位已被同件实例符文占用 → `slot_full`」，与 `mount_rune`
  共用 `_rune_slot_taken`（一处判定）；解析不到穿戴 uid 不误拦。**本批不新增 gear_stats 词条键**
  （1 阶符文复用既有 FLAT/PCT/COMBAT 键族，口径 §三.2）。`core/battle.py`/`core/effects.py`
  零改动（2 阶重伤/层数缺口、2·3 阶战斗接线留 43-D）。页脚批次串同步。

- **批46（2026-09-20）**：**符文地基**（口径文档 43-A；原案 §9）——新增符文数据模块
  `runes.json`（三阶独立刻度 `tier ∈ {1,2,3}`，**不复用** quality 四档）与纯解析引擎
  `core/runes.py`（`rune_tier_of` / `by_equip_type` default+覆盖 / 3 合 1 纯函数
  `resolve_rune_upgrade`）；孔位/镶嵌**复用** `core/jewel.py`（`mount_rune`/`unmount_rune`/
  `active_rune_sockets`，绕过珠的槽级门票，与装饰珠**共用同一孔位数组**、一槽一物互斥）；
  镶嵌状态挂 `ItemInstance.uid` 的落档容器 `persistent_state["rune_sockets"]`
  （**不挂 EquipmentSlot**——卸装不丢；自由 dict 缺补，无需 DB schema 升级）；
  3 合 1 执行器 `UpgradeEngine` 新增 `rune_upgrade` 子类型（3×同阶同 id → +1 阶、**必成**、
  **禁跳级**、`_commit` 原子提交，档位走独立三阶解析）；`settings.rune_sockets.default_count`
  缺省三孔全开（可配）；总闸复用 `settings.deep_craft.enabled`（默认关）。专项校验
  `content/rune_models.validate_runes`（阶枚举 / default / stats 键空间 / effects 引用 / family）。
  编辑器可见 + 页脚批次串同步。**本批不接战斗效果**（1 阶数值上板 / 2·3 阶战斗接线留后续批）。

- **批45（2026-09-20）**：**数值校准 · 装备占比 40% → 60%**（决策记录 §三 补充 1，用户 2026-09-19）
  —— 面板预算参数化 `settings.panel_budget`（`white:equip:buff` 设计份 + **装备面板倍率**
  `equip_stat_mult`，**缺省 1.0 = 现状**）；veinborn 校准 `equip_stat_mult=2.25` → 装备份 8→18、
  装备占比 **60.00%**、面板总功率 20→30（+50%），**白值 7 / buff 5 绝对数值不动**。
  倍率在 `core/equipment.aggregate_bonus` **读时**作用于面板轴 `atk/dfn/hp`（**不改落档实例**，
  改回 1.0 即回滚），战斗直读词条（会心/耳栓/超会心/吸免穿）与其余属性不动。
  怪物侧新增 `settings.monster_scaling`（`hp_mult/atk_mult` **缺省 1.0**；veinborn 校准 1.5 = +50%），
  `con` 按防御系数非线性做仿射补偿 `(con+K)×def_factor−K`（校准 1.0828）→ **中值档三只代表怪
  斩回完全一致**（普通 7 / 精英 20 / Boss 24），不配置时逐字段不变。编辑器可见（中文名 +
  说明卡）+ 校验器（结构/类型/负值红拦）+ 页脚批次串同步。

- **批44（2026-09-20）**：深度打造**投入概率暴击**（决策记录 §七 用户裁定）——投料提交时按
  图纸档掷一次概率，命中给额外品质经验（倍率可配），使高档图纸有机会冲破常规经验上限达到
  **品质 10**；**用概率暴击替代拉高 cost cap / 强制扩充材料表**（cap 默认值与 13 行概率
  阶梯不变）。参数全部包声明：`craft_rules.quality_exp_crit`（逐档概率 铜15/银10/金7/彩5%、
  逐档倍率 ×2、适用档、`additive_exp`、`affects_quality_level`、`rolls_per_craft`、
  `exp_cap`；**缺省关** → 不掷、不消耗随机数，不暴击路径与既有**逐字段一致**）。
  随机走批40 玩家级随机流（可注入确定性 RNG 复现）；命中提示走模板表新键
  `deep_craft_crit_gain`；编辑器参数可见（中文名 + 说明卡）；页脚批次串同步。

- **批43（2026-09-20）**：强化系统**六档上限替换**（H3：品质等级 → +3/+6/+9/+12/+15/+18，
  替换既有 `max_by_rarity` 5/8/10/12；旧档经 `legacy_quality_level_by_rarity` 桥接读上限、
  既有 `enhance_level` 原样保留不降级）+ **每 4 级特殊词条**（跨度可配；从相性池经
  `affinity.resolve_available_entries` 抽取，载荷写入实例 `enhance_affixes`）+ 词条族注册
  （`data/gear_stats.py` 唯一源：回复强化 / 减益概率 / 增益概率 / 弱点伤害为 `_pct` 键；
  冷却缩减为**占位**只登记展示不接引擎）。`core/enhance_affix.py`（纯函数上限/词条）；
  曲线与石档延至 +18；编辑器上限表可见；页脚批次串同步。

- **批41（2026-09-19）**：深度打造**主体**（图纸 / 材料 / 打造主流程）——新指令 `/精造`
  （学习 / 预览 / 投料打造）；图纸作为 `items` 的一种（`blueprint_*` 字段，不新造平行物品
  体系）+ 材料等级/品质/cost 字段 + `settings.deep_craft` 打造参数段（等级加权 / 品质经验 /
  品质等级阈值 / 13 行品质概率阶梯 / 图纸档 cost 上限）；深度层引擎 `core/deep_craft.py`
  （纯函数：等级·品质经验·品质抽取·cost·防退化 N2）；投料→基础产出 100% 走**公用合成层**，
  随机用玩家级随机流（批40）；产出装备实例带 `uid` 入背包。属性与套装词条相性抽取（C 节）
  留批 42。

- **批 D（2026-09-14）**：存档「内容包通用状态格子」——新表 `player_pack_state`（每
  玩家×内容包 一格，`pack_id` 运行时传入，框架零包名/零业务键）+ `db_schema_version`
  1→2 迁移步（新库经 SCHEMA_DDL 直接具备、旧库幂等补表且既有数据无损）+ 纯存储层读写
  API `qbot_rpg/storage/pack_state.py`（get/set/patch/clear/list + 64 KiB 单格上限）。
- **M0-M5 归档欠账回填说明**（D8 ACC-03）：M0-M5 历史 verify（verify_m0~m5）全部只 print
  到 stdout、无文件写出——欠账原因 = G1「verify 输出留档于仓库 docs/」自 G1 成文起未落地
  （【批3A】P0-2/P1-5）。处置：M0-M5 不补历史报告文件，仅登记；**自 M6 起 verify_m6 按
  ACC-02 统一归档 docs/verify/**（验收单 m6_checklist.md / 归档报告 m6/verify_m6_<日期>.md /
  冒烟留档 m6_smoke.md / 覆盖率报表 coverage_latest.txt，写入者 = verify_m6.py）。
- **M6（进行中，2026-08-28 批8 收官）**：verify_m6 两段式门禁 + M6 唯一验收口径——段一 8 项
  验收单（D8 VG-01~09：热重载回退/冒烟闭环/故障注入六类/覆盖率≥80%/ruff-mypy-pytest/
  内容包 validator 全绿/里程碑验收单/CHANGELOG+归档）+ 段二 M2-M5 DELAYED 承接收口
  （DLY-01~10：到期扫描 + verify_m4 批次7-01 翻转 + 六组裁决转 pytest/残留登记）+
  ACC-01 验收单 + ACC-02 归档契约（本条目随 D7 CHG-03 预留条目收口）。
- **M6（进行中，2026-08-28 批7 落地）**：质量门禁载体落地——覆盖率实算+阈值断言（COV）/ ruff-mypy
  工具链（LNT）/ CHANGELOG 建档回填（CHG，本文件）/ CI 流水线（CI）/ PR 评审模板（RVW），
  待本批次与 verify_m6（D8）收口（D7 CHG-03 预留条目）。
- **M6 提交规范差距登记**（D7 CI-06）：历史提交无 scope，M6 起按 `<type>(<scope>)` 执行
  （存量提交不追溯改写，只校验新增）。
- **M5（2026-08-27）**：消息模板与渲染层实装——前缀公共接线/战斗渲染 BREP-01~25/结算连段/
  全仓 emoji 降级与登记表/背包筛选链/verify_m5 门禁 81 TC（六门禁全绿）。
- **M4（2026-08-26）**：指令系统实装——reward 发放器/统一条件引擎/指令解析层/NPC/商店/任务/
  签到/指令组/校验器接线 + e2e 冒烟集成收官（154 断言，五门禁全绿）。
- **M3（2026-08-26）**：地图/副本/时间天气系统实装——时间引擎/天气引擎/地图行走/刷怪/副本两型/
  换区追击/安全区快照死亡 + 集成回归收官（951 全绿四门禁过）。
- **M2（2026-08-26）**：怪物体系完成——enemies 八段 + AI 决策引擎 + 战斗挂接 + 世界边界
  （dsh 三批审查 P1×6 修复，G3 门禁 361 全绿）。
- **M1（2026-08-19）**：战斗系统实装——伤害公式/效果系统/公式引擎三模块 + 战斗引擎
  （状态机/回合时序/完整接线）+ 定稿冲突三拍板落地（先手击杀/派生整体拒/环=特性）。
- **M0（2026-08-25）**：实现层框架骨架实装——data/storage/content/core 四层 + G0 架构检查 +
  测试体系 + verify_m0 门禁（M0 复查三批 P0×2 / P1×31 全部修复）。

### Fixed

- **批49（2026-09-20）**：**擦除 `test_conftest_wrapper_still_works` 全量偶发红**。根因：仓库
  `tests/` 为 PEP 420 隐式命名空间包（无 `__init__.py`），当环境 `sys.path` 上存在同名 regular
  package（实测宿主 `/usr/local/lib/hermes-agent/tests`，自带 `__init__.py`）时，import 按
  「regular package 优先于 namespace package」解析，用例内
  `from tests.conftest import load_formula_params` 落到宿主包 →
  `ImportError: cannot import name 'load_formula_params' from 'tests.conftest'`（全量跑中间歇红、
  隔离跑绿）。修法：conftest 增 `conftest_formula_loader` fixture 注入同一薄包装函数，用例不再
  运行期 import `tests.conftest`（并新增同源对拍断言）；附静态回归用例
  `test_no_runtime_import_of_tests_conftest` 禁该模式复发。页脚批次串 →「批49 · 测试 flake 根治」。

## [v0.1.0] - 待发布（版本段骨架）

<!-- 首个版本发布时：将 [Unreleased] 条目归档至此，格式 `## [vX.Y.Z] - YYYY-MM-DD`
     （Keep a Changelog；D7 CHG-01）。M0-M5 各条目日期 = 记录.md 对应里程碑段落完成日
     （D7 CHG-02；M1 记录.md「更早」节无日期，已核对 git 提交日期 2026-08-19 属实——
     M1 定稿落地 42443a5/补测修复 bf83742 等均 2026-08-19，批7B 审查 P1-1 核销）。 -->