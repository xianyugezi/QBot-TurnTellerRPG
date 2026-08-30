# 审查 · M9 锻造 批B（素材经济 + 铸造职业层）— j-space 静态审查报告

> 门控：**full 档**（用户指定）。方式：纯静态代码审查，零命令/零运行/零验证；所有运行行为结论均标注「静态推导」。
> 范围：6 文件
>   - `qbot_rpg/core/forge_material.py`（素材两档/来源归一/3:1 combine/实例发现/映射）
>   - `qbot_rpg/core/forge_progress.py`（ForgeProgressEngine：持有量/差量/进度行/满链判定）
>   - `qbot_rpg/core/forge_deadlock.py`（死锁途径扫描/scan_ok/hint/comb_synth_map 解析）
>   - `qbot_rpg/core/forge_job.py`（FORGE_JOB_ID/forge_level/level_gate_met/forge_exp_for/gain_forge_exp/exp_to_next/rank_name/configure_proficiency）
>   - `qbot_rpg/core/forge_sp.py`（FORGE_SP_PANEL SP-F1~F5/sp_available/sp_unlock/sp_locked/sp_panel_view）
>   - `qbot_rpg/core/forge_king.py`（codex_all_lit/king_eligible/grant_forge_king/king_only_nodes/king_bonus/forge_king_eligible_check）
> 参考：细化 2c2c / 2c2d / m9_shared_contract / m9_接口摸底 / 定稿 / 批A 审查惯例；对照实机文件：`forge_tree.py`、`proficiency.py`、`forge_settings.py`、`forge_models.py`、`content/test_demo/proficiency.json`、各对应单测。
> 说明：行号以 read 工具行号为基准；「静态推导」= 未经运行验证的逻辑推演。

---

## 〇、结论速览

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | 0 | 无阻断级缺陷（无 NoneBot import、无定时器字面量、无缺功能） |
| **P1** | 1 | 素材档位双源仲裁跨模块不一致（forge_deadlock._tier_of 忽略行 tier=normal 覆写） |
| **P2** | 3 | progress_line 模板符号 ≠ 定稿；SP cost 配置未贯通；comb_synth_map 双实现语义分裂 |
| **P3** | 5 | 文档/代码顺序不一致、重复素材行折叠、参数遮蔽、默认值示例待确认、legal fixture 缺 forge 实例 |
| 无问题维度 | — | 维度 ③/④/⑤ 全通过；维度 ⑥ 完整一致 |

---

## 一、维度逐项结论

### 维度 ① 定稿落地 ✅（1 处 P1 例外）

| 细化/定稿点 | 落地位置 | 结论 |
|---|---|---|
| TIER-03a 素材两档双源仲裁（行覆写>items） | `forge_material.material_tier_of`（L106-135） | ✅ 行 tier 合法即生效 > items material_tier > 缺省 normal；**但 `forge_deadlock._tier_of`（L347-364）与之一致性破裂 → P1-1** |
| SOUR-00 来源归一三态（source_override>items.source>兜底） | `material_source`（L141-156）委托 `forge_settings.resolve_source_text` | ✅ 三态齐备，兜底「来源未知」 |
| CMB-01~04 3:1 combine 可用性（开关+SP-F2 解锁） | `combine_3to1_available`（L180-216）+ `_resolve_synth_3to1`（L162-177） | ✅ 开关缺省 true（F-3 三态容错）、SP-F2 委托 ProficiencyEngine.unlock_count |
| CMB-02 combine 实例发现 + comb_synth_map | `combine_instances`（L269-303）/ `comb_synth_map`（L309-335） | ✅ 双形态 recipe 兼容、N 素材→1 高级素材逐输入登记 |
| DEAD-04 死锁途径六类计数分级保底（普通≥3/稀有≥2） | `forge_deadlock`：SOURCE_CHANNELS 六类（L84）/THRESHOLD_NORMAL=3、THRESHOLD_RARE=2（L101-102）/deadlock_report（L401-467） | ✅ 六通道类别计数、combine 仅开关开时计（TC-19）、orphan 标记（TC-22） |
| 铸造 7 级门槛 level_gate_met（L213 可锻上限=职业等级） | `forge_job.level_gate_met`（L203-227） | ✅ node_level≤职业等级，非法 node_level 保守拒（F-4） |
| SP-F1~F5 五类解锁 | `forge_sp.FORGE_SP_PANEL`（L81-112）五项 + proficiency.json forge 实例 sp_panel 五项 | ✅ id/作用域/描述齐全，成本 1/repeatable=false/max_repeat=1 |
| 铸造王图鉴全亮→授予（KF-01） | `forge_king.codex_all_lit`（L188-197）/`king_eligible`（L203-223）/`grant_forge_king`（L229-253） | ✅ forged 集合主判定 + codex 分册旁路（F-1）；与等级解耦（TTL-01）；幂等 |

### 维度 ② 代码质量 ✅（P1-1 / P2-3 相关）

- **确定性**：6 文件无 random、无定时器调用、无 IO（`_count_item`/`_items_lookup` 的 hook 调用被 try/except 兜底为 0/None）✅
- **纯函数入参不变性**：绝大部分只读；有意改写点均已显式标注——`forge_prof_node`（创建 proficiency 节点，F-6）、`gain_forge_exp`/`sp_unlock`/`grant_forge_king`（委托引擎就地落账）✅
- **委托复用**（维度核心）：✅ 普遍复用而非重写——
  - forge_material：委托 `ProficiencyEngine.unlock_count`、`MaterialReq.from_entry`、`read_forge_settings`、`resolve_source_text`
  - forge_progress：`ForgeProgressEngine` 构造器注入 `ForgeTreeEngine`，forge_readiness 复用 `parent_forged`/`path_to_root`/`already_forged`
  - forge_job：委托 `ProficiencyEngine.gain_prof_exp`/`tier_name`；`FORGE_JOB_ID` 复用 forge_tree 单一真源
  - forge_sp：委托 `ProficiencyEngine.sp_available`/`unlock_item`/`unlock_count`
  - forge_king：委托 `ProficiencyEngine.grant_king_title`、`codex_progress`、`ForgeTreeEngine.nodes`
  - ⚠️ 例外：`forge_deadlock._tier_of` 与 `build_comb_synth_map` 属兄弟模块重写 → P1-1 / P2-3
- **exp_to_next 缺口口径（阈值差−级内经验）**：`forge_job.exp_to_next`（L306-341）cost = `ranks[level+1]-ranks[level]`、missing = `max(0, cost - exp)`，与 proficiency.py 升级判定（级内余量跨阈值）口径一致 ✅

### 维度 ③ 遗漏检查 ✅ 无遗漏

- 细化 2c2c §五 D TC-18~22 验收点：代码与单测全部对齐——
  TC-18（稀有途径 2 达标/1 缺口）、TC-19（comb_synth_map +1/关开关 −1）、TC-20（分解回收批外，本模块不消费 decompose_rate，已注记）、TC-21（商店限购不抹途径/普通≥3 保底/稀有 3:1 兜底）、TC-22（无孤儿/不可达，orphan 标记）
- SP 解锁幂等 / SP 不足拒 / 未识别拒：`sp_unlock`（L168-180）委托 `ProficiencyEngine.unlock_item`，panel_not_found / sp_insufficient / not_repeatable / max_repeat_reached 全由引擎承载（F-4）✅
- 铸造王与等级解耦：`king_eligible` 只读图鉴不读等级（L203-223）✅
- king_only 守卫：`forge_king_eligible_check`（L365-390）非 king_only 放行 / king_only 无称号拒 `king_title_required`（「未获铸造王」）✅

### 维度 ④ 零 NoneBot import ✅ 通过
grep `import/from nonebot|botpy|qqbot` 在 6 目标文件（及 `qbot_rpg/core/forge_*.py` 全系）零命中；仅 docstring 文字提及（不算 import 语句）。

### 维度 ⑤ M43 零定时器 ✅ 通过
grep `time.sleep` / `threading.Timer` / `schedule` / `Timer(` 字面量在 6 文件 docstring 零命中（文档仅以中文「不写定时器/睡眠调用」自述铁律，非禁止字面量）。

### 维度 ⑥ 并发协作遗留 proficiency.json forge 实例 ✅ 完整一致
`content/test_demo/proficiency.json`（L122-234）forge 实例核对：
- `tier_names` 7 级 见习→王 ✅
- `job_rank_levels` [0,100,300,700,1500,3000,6000] ✅（与 proficiency.py 默认、forge_job `_DEFAULT_RANK_LEVELS` 一致）
- `exp_sources.craft=1.0` ✅
- `sp_per_level=1` ✅
- `sp_panel` SP-F1~F5 五项（unlock_branch_tree/unlock_combine_3to1/unlock_slot_tool/unlock_sets/unlock_augment，cost=1/repeatable=false/max_repeat=1）✅ 与 `FORGE_SP_PANEL` 同构（test_forge_sp H 用例校验 id/name/cost/repeatable/max_repeat）
- 附：`job_tier_map` 见习1-5…王51-99 与 2c2d §3.1 CAST 表一致；energy.enabled=false

---

## 二、问题清单

### P1（功能性不一致，1 项）

**P1-1 · forge_deadlock._tier_of 忽略素材行 tier="normal" 覆写，与 forge_material.material_tier_of 双源仲裁结果分裂**
- 文件：`qbot_rpg/core/forge_deadlock.py` L347-364（`_tier_of`），对照 `qbot_rpg/core/forge_material.py` L106-135（`material_tier_of`）
- 现象（静态推导）：TIER-03a「行覆写 > items 元数据」。`material_tier_of` 对任意合法行 tier（normal/rare）都生效，即行 `tier:"normal"` 可把 items `material_tier:"rare"` 覆写为 normal；而 `_tier_of` 只判 `TIER_RARE in row_tiers`，行 tier=normal 被忽略，落到 items rare → 判定 rare。同一（行, items）输入在两个消费方产出不同档位。
- 影响（静态推导）：DEAD-04 分级阈值错配——该素材在死锁报告标 rare（threshold=2）而素材层为 normal（应 threshold=3），途径数达标判定、`sources`/`tier`/`threshold` 报告字段失真；两模块对同一规则同参不同值，违背确定性铁律与维度① TIER-03a 落地一致性。
- 修复建议：`_tier_of` 改为优先采纳合法行覆写值（normal/rare 均生效），行有合法 tier 即返回该值；否则取 items material_tier；否则 normal。或直接复用 `forge_material.material_tier_of` 的判定口径（每行判定），并在 `_collect_material_rows` 保留行级覆写。同步更新 F-2 注记（现仅承认 rare 覆写）。

### P2（契约/配置贯通/跨模块一致性，3 项）

**P2-1 · forge_progress.progress_line 用「✅」渲染，与定稿模板「✓」及自身 docstring 不符**
- 文件：`qbot_rpg/core/forge_progress.py` L272-278（`seg += " ✅"`、`f"{pname} ✅"`）
- 现象：细化 2c2c PROG-05 / TC-13 与 2c2b §2.2 模板均为 `铁剑Ⅰ ✓`、`矿石 5/5` 满额标 `✓`；本文件 docstring（L15-16、L38-40 F-1、L254）也写「✓」，但代码实际渲染「✅」（emoji）。测试文件与代码自洽（断言 ✅），但与契约模板字面不一致。
- 影响（静态推导）：`progress_line` 输出文本 ≠ 验收模板，TC-13 若按字面断言会失败；emoji 也可能触发 emoji 门禁。
- 修复建议：将「✅」统一改为「✓」或按指令层排版规范选择；并同步修正 docstring 的 ✓/✅ 措辞，消除文档-代码矛盾。

**P2-2 · forge_sp 的 SP 定价未贯通内容配置（本地兜底恒 cost=1，覆盖 2c5a SP-05 可配 cost）**
- 文件：`qbot_rpg/core/forge_sp.py` L121-149（`_forge_entry`/`_engine`），F-1（L41-46）
- 现象：`_engine()` 每次新建 `ProficiencyEngine(entries=[_forge_entry()])`，sp_panel 恒取 `FORGE_SP_PANEL` 静态定义（cost=1/repeatable=false/max_repeat=1），从不读取装配层注入的真实 `proficiency.json` forge 实例 sp_panel（含内容包可配 cost/repeatable）。F-1 称其为「本地兜底」，但实际是唯一路径——内容配置的 cost 覆盖永远不生效。
- 影响（静态推导）：若内容包把某项 SP cost 配成 2+，`sp_unlock` 仍按 1 扣（静态推导：unlock_item 用 sp_panel_defs 里该 engine 的 cost）；2c5a SP-05「1 SP/次可配 cost」与 2c2d §3.2「内容包可配 cost」被架空。当前 test_demo 恰好 cost=1 未暴露。
- 修复建议：`forge_sp` 复用装配层单一引擎（如 `forge_job.configure_proficiency` 注入的模块级 `_ENGINE`），或接收 entries 并读取 forge 实例 sp_panel；本地 `FORGE_SP_PANEL` 仅作无配置时的真兜底。同时消除 `forge_job`（模块级引擎）与 `forge_sp`（每次新建引擎）的配置源碎片化。

**P2-3 · comb_synth_map 双实现语义分裂（forge_material 后写覆盖 vs forge_deadlock 兜底 setdefault 先写保留）**
- 文件：`qbot_rpg/core/forge_material.py` L334（`out[in_id] = out_id`，同输入多实例后者覆盖）；`qbot_rpg/core/forge_deadlock.py` L263-287（`build_comb_synth_map` 用 `setdefault`，先写保留）与 L290-311（`resolve_comb_synth_map` 优先调兄弟模块，失败回退本地）
- 现象（静态推导）：同一输入素材 id 出现在多个 kind=combine 实例时（同系多输出），兄弟路径（后者覆盖）与本地兜底路径（先写保留）产出不同映射；`resolve_comb_synth_map` 因依赖兄弟模块是否可导入而结果可变。
- 影响（静态推导）：`_combine_sources`（取映射 values）在兜底/主路径下可能不同 → DEAD 途径计数不确定；违背确定性铁律。
- 修复建议：统一覆盖语义（推荐与兄弟模块一致的后写覆盖），或 `resolve_comb_synth_map` 直接委托 `forge_material.comb_synth_map` 且 `build_comb_synth_map` 与之一致；在测试中固定同输入多实例断言。

### P3（文档/边界/质量，5 项）

**P3-1 · deadlock_hint 建议通道顺序 docstring ≠ 代码**
- `forge_deadlock.py` L492-496 docstring 声明顺序「combine/shop/drop/gather/plant/helper」，代码 L519 实按 `SOURCE_CHANNELS`（drop/shop/combine/…）生成；TC-18 示例文案「建议补 3:1 合成/商店/另一掉落」顺序也与代码输出不同（测试仅断言包含关键字，未断言顺序）。建议统一顺序。

**P3-2 · material_holdings 以 item_id 为键，同节点重复素材行被折叠**
- `forge_progress.py` L203-221（`out[item_id] = {...}`）。V10/V11 未禁止同节点多行同 item_id（静态推导：若内容包在同一节点写两条同素材行，仅末行 need 生效，非求和）。当前 forge.json 无此形态。建议校验器补去重或引擎侧求和。

**P3-3 · forge_readiness 参数 node 被遮蔽**
- `forge_progress.py` L343 `node = tree.node(first_unforged)` 重绑定函数参数 `node`；后续不再用原 node，无功能 bug，属可读性/维护风险。建议换局部变量名。

**P3-4 · king_bonus 缺省 5% 为「示例」值，定稿/细化未定义缺省**
- `forge_king.py` L97-100（`FORGE_KING_BONUS_DEFAULT=5.0`），KF-02 ② 仅「全属性+X% 可配」；5% 系 F-6 工程补白示例。当前行为可接受，但需装配层确认是否为期望缺省。

**P3-5 · tests/fixtures/packs/legal/proficiency.json 无 forge 实例（信息项）**
- `tests/fixtures/packs/legal/proficiency.json` 仅 alchemy（L1-121）。该 fixture 属 loader 合法包参考集、非 test_demo 内容包，批 B 未改 fixtures 属契约内；仅提示若 loader 侧需 forge 职业覆盖可后续补登记（信息级，不构成缺陷）。

---

## 三、无问题维度确认

- **维度 ③（遗漏）**：TC-18~22 验收点、SP 幂等/不足/未识别拒、铸造王与等级解耦、king_only 守卫——代码与测试全部覆盖，无遗漏 ✅
- **维度 ④（NoneBot）**：6 文件 import 语句零 NoneBot 命中 ✅
- **维度 ⑤（M43）**：6 文件 docstring 无 time.sleep / threading.Timer / schedule 字面量 ✅
- **维度 ⑥（proficiency.json forge 实例）**：tier_names 7 级 / job_rank_levels / exp_sources craft=1.0 / sp_per_level=1 / SP-F1~F5 五项完整一致 ✅

---

*审查模式：j-space full 档 · 接缝审计 · 纯静态（无 bash/无运行/无验证；运行行为结论均为静态推导）。*
