# 审查_M8契约_路C：数据与校验子文档（jspace 档）

> 审查者：QBot-TurnTellerRPG 代码审查 Agent（固定角色）
> 审查方式：静态文件审查（本环境无 bash，禁止运行命令；结论均标"静态推导"）
> 审查日期：2026-08-29 · 门控档位：full
> 预算纪律：验证 grep 1 次（validator 行号）、read 实核 12 处真实函数，其余行号以 read 定位为准

---

## 〇、审查对象与对照基准

- 审查对象：`docs/m8_contract_数据与校验.md`（470 行，recipe/traits/proficiency/settings alchemy schema + 59 条校验规则 + IF01~25 + 验收 TC + 铁律）
- 对照基准（全部实核）：
  - 炼金定稿 v2.3 §10 数据结构（L348-426，`docs/审查参考/炼金系统设计定稿.md`）
  - 细化_2c4b（修订版）/ 细化_2c4c（修订版）/ 细化_2c4e（修订版）/ 细化_2c5a（职业等级与SP）
  - 接口摸底 `docs/m8_接口摸底.md`
  - 仲裁 `docs/仲裁/细化_0_仲裁决议汇总.md`（R-07 / R-08）
  - 批次 `docs/m8_batch_plan.md`（用户 5 项拍板）
  - 真实代码（qbot_rpg 包）接口签名 read 实核

## 一、结果总表

| 严重级 | 数量 | 摘要 |
|---|---|---|
| 🔴 P0 必改 | 1 | IF02 `Registry.resolve_name` 契约签名 ≠ 代码真实签名（契约写 2 参返回 AnyDef，真实 1 参 ID→显示名） |
| 🟡 P1 应改 | 1 | recipe.json §1.1 字段表漏 `inputs`/`output`，与 §1.2 通用执行器契约 / REC-11 / 细化_2c4c §2.2 冲突 |
| 🟢 P2 建议 | 8 | 见第四节（公式键未落名 / 额外消耗键未落名 / PP 预算无字段名 / 能量双开关优先级 / element 表落点 / traits_inherit 1-3 vs 1-6 / ALC-20 级别标注 / PRF-02 长度≥2） |

逐维度结论：
- ① IF 接口签名：**IF02 一个 P0**；其余 24 项实核全部吻合
- ② 字段 schema：与细化修订版 + 定稿 §10 逐字段一致，**仅 upgrade 实例 inputs/output 未入字段表（P1）**
- ③ 校验器四件套：挂接方式、59 条规则、红拦/提示分级全部对齐既有鸭子类型模式 ✓
- ④ 跨文档一致性：与核心机制/指令契约/战斗资源子文档落点不冲突（grep 全量比对一致）✓
- ⑤ 用户 5 项拍板 + R-07/R-08：7 项全部落实 ✓
- ⑥ 缺漏：定稿 §10.1/10.2/10.3/10.6 字段**零缺漏**全部进契约 ✓（仅若干配置键未落名的 P2）

---

## 二、🔴 P0 必改（1 条）

### P0-1 IF02 `Registry.resolve_name` 契约签名与代码真实签名不符（含编造嫌疑）

- **契约位置**：`docs/m8_contract_数据与校验.md` L355（§八 IF02）
  > IF02 | `Registry.resolve_name` | `resolve_name(name, kind) -> Optional[AnyDef]` | /合成 /投料 /继承 参数按 name 匹配
- **真实代码**：`qbot_rpg/content/registry.py` **L86**（read 实核）
  ```python
  def resolve_name(self, id: str) -> Optional[str]:
      """ID → 显示名（旧局旧配置：对局快照冗余存储名称，重载后展示仍用旧名，L177/L186）。"""
      return self._names.get(id)
  ```
- **差异**：契约写 **2 参 `(name, kind)` 返回 `AnyDef`**（名→定义），真实是 **1 参 `id` 返回显示名 str**（ID→名称）。参数个数、语义、返回类型三重不符。真实 Registry 中**不存在任何"按显示名匹配到 Def"的接口**（仅 `resolve(id, kind)` 按 ID 查表）。契约宣称的用途「/合成 /投料 /继承 参数按 name 匹配」在真实代码里**无承载接口**——实现组按此契约写 `registry.resolve_name(name, kind)` 必然 TypeError / 拿到 None。
- **证据**：
  - 契约 L355（错误签名）；`registry.py L86`（真实签名 `resolve_name(self, id: str) -> Optional[str]`）
  - 摸底 §4.1 L154 仅列出 `resolve_name` 名称、未给签名——契约作者在摸底缺签名处**自行补写并误标"已 read 实核"**，违反文档铁律「禁止编造 / 接口签名以实核为准」。
  - 同型错误已**传播**到 `docs/m8_shared_contract.md` L1307（同款错误签名），需一并修订。
- **修复建议**：
  1. 将 IF02 改录真实签名：`Registry.resolve_name(id: str) -> Optional[str]`（ID→冗余显示名，热重载降级用）；
  2. "参数按 name 匹配"的实际承载需另立接口：新增 `Registry.resolve_by_name(name, kind) -> Optional[AnyDef]`（遍历 `tables[kind]` 按 `Def.name` 匹配，内容包加载后构建 `name→id` 索引）并在契约中显式标注【工程补白·需新增】；或明确改用 `resolve(id, kind)` + `all_ids(kind)` 遍历方案；
  3. 同步修订 `shared_contract` L1307 与《核心机制》IF-43（L374，行号标注 L82/L163 亦错，resolve_name 真实 L86）。

---

## 三、🟡 P1 应改（1 条）

### P1-1 §1.1 recipe 字段表缺 `inputs`/`output`，与 §1.2/REC-11/细化_2c4c §2.2 冲突

- **契约位置**：§1.1 字段表（L33-50）只列 `materials`（L41，注释"=框架统一 schema 的 inputs（item 同义，仅改名）"），**未列 `inputs`/`output` 字段**；而同文：
  - §1.2 通用执行器契约（L55）：「inputs（N 入）/ cost / output（1 出）……字段名与框架统一 schema 对齐（**inputs/cost/output**）」；
  - REC-11（L256）：「kind=upgrade 实例：**inputs** 引用 items 存在、**output** 引用 items 存在、**output.count**=1」；
  - 细化_2c4c §2.2（L163-171 JSON 实例）与定稿 §10.1 映射表（L363-368 列名 **inputs/cost/output**）均用 `inputs`/`output` 键。
- **证据**：契约 L41（materials 行）vs L55（inputs/cost/output）vs L256（REC-11）；细化_2c4c §2.2 实例键 `inputs`/`output`。
- **问题**：一处字段表、两套键名。实现组若只读 §1.1 会漏建 `inputs`/`output`（或把 upgrade 实例错误建成 `materials`）；REC-11 校验对象在字段表无定义。
- **修复建议**：在 §1.1 明确双 schema 口径——`kind∈{craft,combine}` 用 `materials[{id,count}]`（定稿 L354）；`kind=upgrade` 用 `inputs[{item,count}]` + `output{item,count}`（定稿 L363-368 / 细化_2c4c §2.2，字段级契约表补两行：`inputs` 数组 ref items + `output` obj ref items 且 count=1），并注明与 `materials` 的互斥关系。

---

## 四、🟢 P2 建议（8 条，不阻断）

| # | 位置 | 问题 | 修复建议 |
|---|---|---|---|
| P2-1 | §五 gem.分解（L204）/ ALC-22（L317） | "产出公式可配置（默认平铺，可改 ⌊基础值×回收率⌋ 等）"——**未落具体 settings 键名与语法**，实现组无从接线 | 补工程补白键（如 `gem.decompose_formula: "flat"|"rate"` 或模板串），与 2c4b DEC-03 拍板①对齐 |
| P2-2 | §1.3（L68）/ ALC-23（L318） | "可配额外消耗（默认 0）"——**未落具体 settings 键**（复制额外消耗） | 补键名（如 `gem.复制额外` 或 `copy_extra_cost`），与拍板④/2c4c DUP-03 对齐 |
| P2-3 | §1.1 末行（L50） | PP 预算字段只有【工程补白】行，**无具体字段名**（例：火焰弹 PP 5/5 落哪个键） | 落名（如 `pp_budget`，int≥0），引 细化_2c4e INH-09 / 定稿 L414 |
| P2-4 | §3.1 energy（L127）+ §五 energy_enabled（L197） | 能量开关双源：proficiency.json `energy.enabled` 与 settings `alchemy.energy_enabled` 并存，**优先级/冲突口径未定** | 契约声明优先级（建议 settings 为准，proficiency 作默认兜底），防双开关打架 |
| P2-5 | REC-05（L250） | "元素 ∈ 8 元素注册表（地水火风雷晶月无）" 硬拦依赖 formula.json element 表，但 element 表**本契约未定义、field_meta formula fields={} 未登记**（field_meta.py L381/L454） | 契约注明 element 表归属批0/其它子文档登记，否则 REC-05 红拦落空 |
| P2-6 | REC-12（L257）/ §1.1 traits_inherit（L46） | 定稿 L356 该字段 1-3 与 细化_2c4e INH-06「普通特性位可配 1-6」口径并立，契约只按 1-3 记 | 补注：字段范围 1-3（定稿），继承位总上限 1-6（INH-06）由 SP/等级扩展承载，消除歧义 |
| P2-7 | ALC-20（L315） | 级别标注"红拦（布尔）"混两语义（布尔红拦 + per_battle_limit≥1 未给独立级别） | 拆两条或明确 per_battle_limit 级别 |
| P2-8 | PRF-02（L282） | tier_names"长度 ≥2"与"默认 7 级"并立，最小 2 未说明依据 | 注明"内容包可改、最小 2、默认 7、与 job_rank_levels 一一对应" |

---

## 五、逐维度核对结论

### ① IF 接口签名 vs 真实代码（read 实核 12 处）

| IF | 契约（行号） | 真实代码（read 实核） | 结论 |
|---|---|---|---|
| IF01 resolve | L354 `resolve(id,kind)->AnyDef` | registry.py L82 ✓ | 🟢 |
| IF02 resolve_name | L355 `(name,kind)->Optional[AnyDef]` | registry.py **L86 `(id)->Optional[str]`** | 🔴 P0 |
| IF03 all_ids | L356 `all_ids(kind)->Tuple[str,...]` | registry.py L90 ✓ | 🟢 |
| IF04 build/from_snapshot | L357 build(L163)/from_snapshot(L148) | registry.py L148/L162 ✓ | 🟢 |
| IF10 add_item | L363 `(player,item,count=1)->dict` | inventory.py L183 ✓ | 🟢 |
| IF11 remove_item | L364 `(player,item_id,count=1)->dict` | inventory.py L254 ✓ | 🟢 |
| IF12 count | L365 `(player,item_id)->int` | inventory.py L308 ✓ | 🟢 |
| IF13 save/load_player | L366 save(L473)/load(L442) | repository.py L473/L442 ✓ | 🟢 |
| IF14 load_session | L367 (L563) 返回6元组 | repository.py L563 ✓ | 🟢 |
| IF15 upsert/delete/tx | L368 upsert(L887)/delete(L904)/tx(L412) | repository.py L887/L904/L412 ✓ | 🟢 |
| IF16 write_idem/idem_exists | L369 (L922/L932) IdemKey | repository.py L922/L932 ✓ | 🟢 |
| IF17 dispatch_reward | L370 (reward.py L308) 返回{ok,granted,skipped,[idempotent]}、ctx 就地改写、tx_id+ledger 幂等闸 | reward.py L308 全部吻合 ✓ | 🟢 |
| IF18 settle_exit_idempotent | L371 `(*,session,settlement_kind,message_id,repository)->bool`(L821)、delete+write_idem 同事务 | battle_boundary.py L821 全部吻合 ✓ | 🟢 |
| IF19 SessionManager | L372 五方法(L24-40)+SessionConflictError(L20) | session.py L24-40 全部占位、L20 ✓ | 🟢 |
| IF20 to_snapshot | L373 `(boundary=None)->Dict`(L1740) | battle.py L1740 ✓ | 🟢 |
| IF21 condition/formula | L374 [熟练度:{T}](L161)/[宝石](L218)/熟练度(L246) | 与摸底 §7.3 一致（实核基线）✓ | 🟢 |
| IF22 AlchemyConfig.from_settings | L375 仿 DeathPenaltyConfig.from_settings(battle_boundary L349) | battle_boundary.py L349-350 容错解析模式存在 ✓ | 🟢 |
| IF23 ItemInstance | L376 data/item.py L20-37 十字段+traits 冻结 | item.py L20-37 全吻合 ✓ | 🟢 |
| IF24 EquipmentSlot.gems | L377 data/player.py L69 | player.py L69 `gems: Tuple[str,...]=()` ✓ | 🟢 |
| IF25 珠堆叠键 | L378 repository._item_from_dict L176 round-trip | repository.py L176 缺补默认/多忽略 ✓ | 🟢 |

### ② 字段 schema vs 细化修订版 + 定稿 §10（逐字段）

- recipe.json：定稿 §10.1 L353-358 全部 15 字段（id/name/kind/level/synth_allowed/master_only/materials/cost/slots/element_req/effects/traits_inherit/catalyst/combine_from/evolve_to）**零缺漏**，类型/默认/范围与定稿一致；PP 预算为显式【工程补白】（引 INH-09）✓。唯一问题 = P1-1（upgrade 实例 inputs/output 未入字段表）。
- traits.json：定稿 §10.2 L372-376 **7 字段**（id/name/rarity/effects/group/repeatable/source）逐字段与细化_2c4e TSC-04~10 一致；JSON 样例（L92-102）与细化_2c4e §2.2 样例完全同构 ✓。
- proficiency.json：细化_2c5a §5.2 **9 字段**（id/tier_names/job_rank_levels/exp_sources/sp_per_level/sp_panel/energy/job_tier_map/titles）逐字段一致，默认值（[0,100,300,700,1500,3000,6000] / 7 级名 / exp_sources 三键 / regen_sec=1800）一致；玩家存档 dict 形态（L131-143）与 2c5a §5.3 一致，Player dataclass 不加字段（player.py L72-102 确认无 proficiency 字段）✓。
- settings alchemy：定稿 §10.6 L408-426 **16 键零缺漏**（mode/quality_tiers/quality_coef/chain_map/pp_cost/pp_refresh/energy_max/energy_regen_sec/decompose_rate/gem/gem_diminish/synth_exp/sp_per_level/sp_panel/战斗道具/战斗即时调合），默认值逐项与定稿一致；另加 6 键均标依据（energy_enabled=R-08 / catalyst_unlock_tier=R-07 / catalyst_consume=批5B / max_qty=拍板⑤ / job_tier_map=L34·LVL-06 / energy_regen_sec_safe=工程补白键）。quality_tiers 键集 common/uncommon/rare/legendary ✓（拍板②）。
- items.json 扩展（L378-382 8 字段）+ slots.json（slot_level + 数量 1-3 补白 SOCK-01）✓ 与 2c4c §2.1 一致。

### ③ 校验器四件套（field_meta / loader / validator / manifest）

- field_meta：traits 已登记（field_meta.py L326-332 **8 键** id/name/type/probability/max_stack/effects/require_status/apply_status + L418 ModuleMeta kind="trait" namespace="trait_lib"）✓；recipe/proficiency 未登记 ✓（契约要求新增）；SETTINGS_FIELDS L206-209 仅 currencies/death_penalty ✓；default_field_meta_table L441 ✓；NAMESPACES L36-50 ✓。
- loader：_KIND_FOR_MODULE L150-172、traits→trait L158 ✓；recipe/proficiency 未登记 ✓；FIXED_REGISTER_ORDER L46 ✓；_register_def L131 按 kind 进 tables ✓；check_register_table_consistency L175 双向拦截 ✓。
- validator：check_pack/_Checker.run L383 ✓；_check_module L465 按模块名分支 ✓；鸭子类型 validate_npcs(L532)/validate_shops(L536)/validate_quests(L539)/validate_checkins(L542) ✓；settings 分支 L559 + _check_settings_1g4 L1329 ✓；_check_chain_cycle L1692 ✓；dungeon 合并模式桥接 L514-524 ✓；shop_models._emit L478 ✓。挂接铁律（M8 专项一律鸭子类型 validate_xxx(modules, report)，与 dungeon 合并模式区分）与现状一致 ✓。
- 规则数 59 = REC 16 + TRT 9 + PRF 10 + ALC 24 ✓；红拦/提示分级总体合理（有据可依，L 号实核 L354-425/L492/L494/L505/L511/L12 均真实存在，未发现编造行号）；个别级别标注见 P2-6/7/8。

### ④ 跨文档一致性

- 对 核心机制/指令契约/战斗资源 三子文档 + shared_contract 全量比对：max_qty（拍板⑤ 2147483647 超限提示不拦）、energy_enabled=false（R-08）、catalyst_unlock_tier=expert（R-07）、battle_alchemy_used 落 to_snapshot dict 顶层键（中断不清零、战斗结束清零）、to_snapshot(L1740)/settle_exit_idempotent(L821)/load_session(L563)/upsert_session(L887)/tx(L412) 签名——**全部一致，无冲突** ✓。
- 唯一跨文档问题 = P0-1 的错误 IF02 签名已传播至 shared_contract L1307（本子文档为源头）。

### ⑤ 用户 5 项拍板 + R-07/R-08

| 项 | 契约落点 | 结论 |
|---|---|---|
| 拍板① 分解宝石平铺（1/3/8/20 不乘回收率）+公式可配 | B2 / §五 gem.分解 / ALC-22 / TC-21 | ✓ |
| 拍板② 键集 common/uncommon/rare/legendary、旧名废弃 | B1 / quality_tiers·quality_coef·gem.分解 / ALC-13 | ✓ |
| 拍板③ 珠升阶无职业硬门槛（槽级准入） | B4 / §1.2 / TC-06 | ✓ |
| 拍板④ 复制费=⌊cost.coins×0.2⌋+额外消耗(默认0) | B3 / §1.3 / ALC-23 | ✓ |
| 拍板⑤ 数量上限 2147483647、超限提示不拦 | B5 / §五 max_qty / ALC-21 / TC-11 | ✓ |
| R-07 catalyst_unlock_tier=expert | §五 / ALC-11 | ✓ |
| R-08 energy_enabled=false | §五 / ALC-07 | ✓ |

### ⑥ 缺漏

- 定稿 §10.1/10.2/10.3/10.6 字段**零缺漏**进契约（见②）；定稿 §10.5 存档项（图鉴/SP/能量当前值/种植/助手/委托）在 §七 persistent_state 键空间有承接 ✓。
- 落名类缺口（P2-1/2/3）、element 表落点（P2-5）、能量双开关优先级（P2-4）均非"定稿字段缺失"，属契约未落名的可配项。

---

## 六、结论

- **需返工（1 个 P0 必改 + 1 个 P1 应改）**：P0-1 修正 IF02 resolve_name 真实签名并另立 name→def 接口；P1-1 在 §1.1 补 upgrade 实例 inputs/output 字段契约。8 条 P2 建议在返工批一并落地。
- 其余维度（字段 schema / 四件套挂接 / 跨文档一致 / 拍板与仲裁）全部通过，59 条规则数与分级合理，定稿行号引用经抽查真实无编造。
- 结论：**本子文档可合入，但须先完成 P0/P1 修订**（作为 m8_shared_contract 合并前置）。

*审查完成，报告已落盘核对（read 确认写入成功）。*
