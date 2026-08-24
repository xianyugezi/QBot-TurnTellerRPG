# 审查_M0复查_content_field_meta_20260824

> 批次：M0 复查 · 批2a-路3 · 字段元数据 field_meta
> 审查对象：`qbot_rpg/content/field_meta.py`（实读 **251 行**；任务描述/前批 20260818 报告均记为 221 行 → 确证本文件在 2026-08-18 硬编码审计后**被改动**，与本批任务假设一致）
> 对照基准：`细化_3e_loader校验接线.md` §5.2（每模块清单）/§5.3（字段元数据唯一数据源）；`细化_3a_架构分层契约.md` §3（领域模型字段）；交叉引用 `细化_1b/1d/1e/3b/2b1/2a1a`、`contract_deviations.md`、前批审计（20260818 content/coredata、20260819 marks/combo）
> 审查方式：**纯静态**（read/grep/glob 只读比对，本环境无 bash 沙箱，未运行任何命令/脚本/验证）；所有运行行为结论为「静态推导」。

## 〇、结果总览

| 级别 | 数量 | 摘要 |
|---|---|---|
| 🔴 P0（必改） | 1 | R-09 monster_def_rate 负数校验语义与用户拍板相反（假阳性红拦） |
| 🟡 P1（应改） | 4 | marks/statuses duration 类型错注册；marks appliable_to 类型错注册；docstring 冒充细化_1e/3b 字段表；「P0-1 修复」标注夸大且 fixture 未同步 |
| 🟢 P2（建议） | 9 | NAMESPACES 零消费/缺项；STAT_CHILDREN 缺 role/mh_map/note；marks probability 无权威依据；maps.reset 子字段未注册；「默认值」维度整体空置；§5.2 部分引用未接线；key_regex 弱 snake_case；M4/M2 前瞻不兼容；_module_table 死代码 |

**① 错误 4（P0×1+P1×2+P2×1）　② 缺漏 5（P1×0+P2×5）　③ 幻觉 3（P1×2+P2×1）**

---

## 一、🔴 P0

### P0-1（①错误 · 校验语义与用户拍板相反）monster_def_rate 负数被红拦，R-09 要求黄提示+运行期按 0
- **位置**：`field_meta.py:160-161`（注释自称「负数黄提示」，但注册为 `FieldMeta(type="number", range_min=0, range_max=5)`，**未设 `allow_negative=True`**）；消费点 `validator.py:523-525`（allow_negative 默认 False → 数值 <0 → **R-2 红拦**）；运行期 `core/battle.py:1323`（`float(tc.get(...) or p.monster_def_rate)`）与 `core/damage.py:463/495`（`max(0.0, monster_def_rate)` 按 0 护栏）。
- **实际**：R-09（用户 2026-08-18 拍板，`细化_1a §1.11 L215-219` + `contract_deviations.md` R-09 行）明文：「monster_def_rate ≥0 默认 1.0」「**负值 → 黄提示 + 运行期按 0（护栏统一）**」。本表给负值时校验器直接 **R-2 红拦** → 一个按裁决本应"黄提示放行+运行期钳 0"的包被误判非法（假阳性红拦），与文件自身"避免误阻断合法包"（L13）及注释 L160 意图相反。
- **为何定 P0**：本字段即本批重点新增字段（R-09 per-实体注册）；校验级别红/黄是裁决明文，非 M0 简化口径可覆盖；同类"合法值被假阳性红拦"在前批 content 审计按 P0-2（部位互斥）处理。
- **修复**：`"monster_def_rate": FieldMeta(type="number", allow_negative=True, range_min=0, range_max=5)` —— 负数落入 `_hint_number` range_min 检查 → Y-1 黄提示，运行期 battle/damage 已钳 0；补一条 validator 负值黄提示用例（当前 `test_r09` 仅正数 0.5，无负值覆盖）。

---

## 二、🟡 P1

### P1-1（①错误 · 类型错注册 → 合法包假阳性 R-1）marks.duration / statuses.duration 注册为 number
- **位置**：`field_meta.py:116`（marks `duration: F_DURATION`）、`:98`（statuses `duration: F_DURATION`）、`:53`（`F_DURATION = FieldMeta(type="number", range_min=0, range_max=999)`）；docstring `L9` 自述「marks：…duration "battle"/"turns:N"」。
- **实际**：权威 schema 中 marks.duration = `"battle" | "turns:N"` **字符串**（细化_1d §1.1 字段9；印记定稿 §八 L212-214）、statuses.duration = **对象** `{turns, charges}`（细化_1b §1.2 字段9/子结构 2a）。按权威格式写 `"duration": "battle"` 或 `{"turns":3,"charges":1}` → validator `_check_value` t=="number" → **R-1 红拦**。文件**自身 docstring（L9）与注册类型自相矛盾**；20260819 marks 审计 P0-1 已点名「duration 按 F_DURATION(number) 而非 battle/turns:N」，本次修复未覆盖。
- **修复**：marks.duration 独立注册（enum|str，可校验 "battle"/`turns:N`）；statuses.duration 独立注册（type="obj"，children {turns:int, charges:int}）；`F_DURATION` 仅保留给 M0 引擎简化 effects 用。

### P1-2（①错误 · 类型错注册 → 合法包假阳性 R-1）marks.appliable_to 注册为 str 而非 string[]
- **位置**：`field_meta.py:113`（`"appliable_to": FieldMeta(type="str")`，注释「可挂目标（AT-01/05；枚举值权威源在数据包）」）。
- **实际**：细化_1d §1.1 字段6 = **string[]**，非空子集 ⊆{self, enemy}（AT-03 空数组/非法值→校验拒绝）。合法写法 `"appliable_to": ["self","enemy"]`（tests/unit/test_effects_runtime.py:91 即用数组）→ t=="str" 分支 → **R-1 红拦**。
- **修复**：`FieldMeta(type="list", element=FieldMeta(type="str"))`；枚举（self/enemy）非空子集校验按注释交由数据包/正式表注入。

### P1-3（③幻觉 · 冒充细化文档字段表）docstring L8/L10 对 细化_1e / 细化_3b §4.2 的字段引用失实
- **位置**：`field_meta.py:8`「细化_1e_怪物八段schema（enemies 字段：hp/atk/def/drop_rate/actions/probability/weight）」；`:10`「细化_3b_玩家属性三层 §4.2（StatDef：base/growth/max/min/type=resource|combat）」。
- **实际**（实读）：
  - 细化_1e §① 顶层字段为 **18 个**：id/name/tier/type/area/desc/stats/weakness/pv/pv_recover/resistance/actions/special_actions/chains/drops/lore/def_base/elem_res。`hp` 只在 `stats.hp`（嵌套 9 键），**无顶层 atk/def/drop_rate**；probability/weight 只存在于 `actions[]` 条目（A02/A03），非顶层 enemies 字段。docstring 所列字段表与该文档不符；`enemies_fields`（L157-167）实为 M0 简化/旧框架 schema（fixture `tests/fixtures/packs/legal/enemies.json` 佐证），却以「细化_1e」背书 → **冒充**。
  - 细化_3b §4.2（行 199-209）字段表为 `name/type/base/growth/role/mh_map/note`；**无 max/min/display**。docstring 声称 §4.2 定义 `base/growth/max/min` 失实，且 §4.2 **必填的 role/mh_map/note 未注册**（见 P2-2）。
- **修复**：改引「M0 引擎简化口径（旧框架 schema，fixture 同构；正式表编辑器里程碑注入）」，去掉对细化_1e/3b §4.2 的具体字段冒充；或按细化文档登记完整字段。

### P1-4（③幻觉 · 「修复」标注夸大 + 联动未同步）marks「2026-08-19 定稿对照 P0-1 修复」仅部分成立
- **位置**：`field_meta.py:106-108` 注释「印记定稿 §八 数据结构汇总（2026-08-19 定稿对照 P0-1 修复）」。
- **实际**：与 20260819 审计 P0-1（marks_fields 缺 icon/appliable_to/polarity/element/desc、多 status 型字段、duration 非字符串）相比，本次确实补了 5 字段、删了 require_status/apply_status/apply_effect —— 但 **duration（P1-1）与 appliable_to 类型（P1-2）仍未对齐定稿 §八**，probability 字段保留且依据误引（P2-3）。配套 **fixture 未同步**：`tests/fixtures/packs/legal/marks.json` 仍为旧格式单条 `fire_mark`（`duration:0` int、带 `probability`、无 polarity/appliable_to/element/desc），细化_1d **V-8「内置样例 火印/诅咒印」仍缺 curse_mark**。
- **修复**：标注改为「P0-1 部分修复（5 字段已补；duration/appliable_to 待修）」，并同步 fixture（补 curse_mark、按新 schema 重写两条样例），否则 1d AT-01/03/04/05 与 V-8 仍不可达。

---

## 三、🟢 P2

| # | 维度 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| P2-1 | ① | `field_meta.py:25-35`（NAMESPACES）+ `:212/245`（formula_lib）+ `:224`（cond_lib） | NAMESPACES 字典**生产零消费**（validator `:222` 用 `mmeta.namespace`，`FieldMetaTable.namespace_of` 仅 test_content.py:294 引用）；且 `formula_lib`/`cond_lib` 两个 ModuleMeta.namespace 值**未登记进该字典** → 命名空间唯一性存在两套口径且不同步 | 补 `formula_lib`/`cond_lib` 进 NAMESPACES，或删除 NAMESPACES 让 `ModuleMeta.namespace` 为唯一来源（§5.3 唯一数据源精神） |
| P2-2 | ② | `field_meta.py:61-70` STAT_CHILDREN | 缺 3b §4.2 必填 `role`/`mh_map`/`note`（延续 20260818 P2-9 未修）；`max/min/display` 无 3b §4.2 依据（M0 简化口径，fixture stats.json 用到 max） | 补 role/mh_map/note（枚举由正式表注入）；max/min/display 改标注「M0 引擎简化」 |
| P2-3 | ③ | `field_meta.py:118`（marks probability） | marks.json 权威 10 字段（1d §1.1）**不含 probability**；1d A-1/AT-10 的概率施加是「mark_add 概率 50% 包 proc」（概率在技能/效果的 proc 包装层），注释把 AT-10 误当 marks 字段依据 | 删除或改「M0 引擎简化字段，正式表移除」，避免正式表注入时与权威 schema 冲突 |
| P2-4 | ① | `field_meta.py:175`（maps.reset = obj 空 children）+ `validator.py:432-440` | reset 的 mode/value 子字段未在元数据表注册，却在 validator `_check_dead_config` 硬编码消费 → §5.3「校验器不硬编码字段名」在 reset 子结构层面被绕过（同源 battle/revert 死配置判断字段已注册，属算法开关可接受） | 为 reset 注册 obj children {mode, value} 或登记 ADR 说明规则引擎例外 |
| P2-5 | ② | `field_meta.py` 全表 + `:12`（「只提供字段口径默认值」） | §5.3 要求元数据表含「默认值」维度，本表**无任何 FieldMeta.default 被填充**（含 monster_def_rate 的「默认 1.0」仅存在于注释+战斗回退 battle.py:1323），docstring「提供默认值」落空 | 为关键字段补 default（monster_def_rate=1.0 等）或改述为「默认值由消费方/正式表注入」 |
| P2-6 | ② | npc `:179-184` / traits `:150-156` / maps `:168-176` / skill_chains `:120-127` | §5.2 部分引用检查未在表中接线：npc 行「引用 item/**task**」→ 无 task 字段（任务模块未入表）；traits 行「引用 skill」→ 无 skill 字段（技能库 M6）；maps 行「引用**副本 ID**」→ 无 dungeon 模块；skill_chains schema（next/actions/effects）与 combo ChainConfig（trigger_skill/max_combo/steps）字段不一致（已登记 contract_deviations D11） | 各模块就位时按 §5.3「新字段=加一行」补注册；skill_chains 随 D11 收口 |
| P2-7 | ② | `field_meta.py:220/237` key_regex `[a-z][a-z0-9_]*` | 弱 snake_case：允许尾/连续下划线（`a_`、`a__b`），§5.2 stats 行要求「小写 snake_case」 | 收紧为 `[a-z][a-z0-9]*(\_[a-z][a-z0-9]*)*` 或登记宽松口径 |
| P2-8 | ② | `field_meta.py:161`（enemies）+ `:240-247`（formula value_meta） | 前瞻不兼容：M4 `difficulty_template`（enemies per-entity，M2 怪物承接）未预留字段位；M2 `pipeline_order`（formula.json 有序数组，contract_deviations M 承接表）与 formula value_meta(type=formula) 冲突——数组值会触发 `_check_map_value` → **R-1 假阳性** | M2 落地时 formula 值形态改为「formula 或 {pipeline_order:[...]}」并加分支；登记待办 |
| P2-9 | ① | `field_meta.py:177-178/219-220/240-247` | `_module_table()` 内的 stats/formula 空 ModuleMeta（含 stats key_regex）被 `default_field_meta_table()` 整体覆盖重建 → 重复构造死代码 | 合并为单处构建，避免两处口径漂移 |

---

## 四、无问题维度确认（✅）

1. **R-09 注册↔消费闭环**：monster_def_rate `field_meta.py:161` 注册 ✅ → `battle.py:1323` 读目标 combatant 配置、回退 DamageFormulaParams 默认 1.0 ✅ → `damage.py` 双通道 `max(0.0, mdr)` 运行期护栏 ✅。注册与消费不脱节（仅负数校验级别错误，见 P0-1）。
2. **conditional 条件加成接线（旧 P1-1）已闭环**：field_meta 注册（L187-202/L223-224，结构对齐 3b §3.2 的 id/source/target/per_point/note）✅ + loader `_KIND_FOR_MODULE`（L157）✅ + models `DEF_CLASSES`（L280）✅ + validator `_check_conditional`（环/引用 R-5/R-4）✅ —— 四层一致，3b TC-05 加载期红拦可达。
3. **stats base/growth allow_negative（旧 P1-4）已修复**：L65-66 `allow_negative=True` ✅ → 负数走 Y-1 黄提示，对齐 3b §4.2/TC-17「负数→黄、运行期按 0」。
4. **结构算法开关元数据化**：skill_chains `chain_field="next"`（L210）与 equipment `mutex_field="excludes"`（L214-215）在元数据表声明且被 validator `_check_chain_cycle`/`_check_mutex_cycle` 消费 ✅；§5.2「部位互斥成环 R-5」「链成环 R-5」可达。
5. **ref 类型字段消费一致**：effects/statuses/marks/traits/items/equipment/enemies/maps/npc 各 `ref_target`（effect/status/mark/action/trait/enemy/item）+ `skill_or_any` 特殊分支（validator L558-564）均被 validator 消费，R-4 引用缺失/Y-7 键空间提示可达 ✅；ID 跨表唯一（effect_family/action_lib/chain_lib 等）经 `mmeta.namespace` 生效 ✅。
6. **§5.3 兜底语义**：未注册字段/x_ 前缀默认放行（validator L417-418）✅，与 §2.3「缺失字段默认放行」一致，本表无字段被硬编码拒绝。
7. **引用行号真实性抽查**：`L23` 注释「细化_3a §4.2 line 254」实读 254 行 = 「效果注册表三表统一 / 行动注册表 / 派生链注册表」✅ 真实；`L12/L42/L147` 等【规则】Lxxx 引用遵循仓库既有约定（指向 docs_archive 外部文档，工作区无法核验，非本文件编造）。
8. **effects 简化 schema 有 fixture 佐证**：M0 引擎口径（power/duration/probability/max_stack 等）与 `tests/fixtures/packs/legal/effects.json`、`statuses.json` 同构 ✅（statuses 用 effects/on_tick/on_enter 简化形态，fixture 一致）。

---

## 五、结论

- **P0×1 / P1×4 / P2×9**。无 M0 当前运行阻断项（fixtures 均按简化口径可通过），但 R-09 负数校验与 marks/statuses duration/appliable_to 类型三处会在「按权威 schema 写包」时产生**假阳性红拦**，其中 P0-1 直接违反用户 2026-08-18 拍板。
- **①错误 4**：P0-1 monster_def_rate 负数红拦反裁决；P1-1/P1-2 marks/statuses duration 与 marks appliable_to 类型错注册；P2-9 死代码。
- **②缺漏 5**：STAT_CHILDREN 缺 role/mh_map/note（P2-2，旧 P2-9 未收口）；「默认值」维度空置（P2-5）；§5.2 task/skill/dungeon/ChainConfig 引用未接线（P2-6）；key_regex 弱（P2-7）；M4/M2 前瞻不兼容（P2-8）。
- **③幻觉 3**：docstring 冒充细化_1e/3b §4.2 字段表（P1-3）；「P0-1 修复」标注夸大且 fixture/V-8 未同步（P1-4）；marks probability 误引 AT-10（P2-3）。
- 优先修复次序：P0-1 → P1-1/P1-2（类型注册）→ P1-3/P1-4（标注与 docstring 诚实化 + fixture 同步），其余随里程碑/正式表注入收口。

*全部结论为静态推导（本环境禁止运行命令/脚本/验证）。*
