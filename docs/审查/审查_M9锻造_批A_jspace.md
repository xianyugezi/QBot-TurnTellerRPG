# 审查报告 · M9 锻造 批A（核心数据层 + 派生树引擎）

> 审查方式：**纯静态代码审查**（环境无 bash 沙箱，禁止运行命令/脚本/验证；运行行为结论全部标注「静态推导」）。
> 审查对象（4 文件）：
> - `qbot_rpg/content/forge_models.py`（1763 行）
> - `qbot_rpg/content/forge_settings.py`（248 行）
> - `qbot_rpg/core/forge_tree.py`（500 行）
> - `qbot_rpg/core/forge_cascade.py`（538 行）
> 参考文档（实际文件路径核对）：
> - 细化：`docs/细化/细化_2c2a_锻造派生树schema.md`（346 行，任务描述名「细化_2c2a_锻造数据与校验.md」对应此文件）
> - 细化：`docs/细化/细化_2c2d_锻造套装与客制.md`（422 行）、`docs/细化/细化_2c2b_锻造流程契约.md`（317 行）、`docs/细化/细化_2c2c_锻造素材经济.md`（192 行）
> - 契约：`docs/m9_shared_contract.md`（211 行）
> - 定稿：`/root/docs_archive/RPG框架项目/锻造系统设计定稿.md`（v1.0.1 · 411 行）——**不在 docs/ 下**，位于 docs_archive
> - 摸底：`docs/m9_接口摸底.md`（138 行）

---

## 〇、审查结论速览

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | **0** | 未发现阻断级/数据不可恢复级缺陷 |
| **P1** | **3** | ①2c2d V3 档位连续性口径与细化 §五 V3 冲突（硬校验放行细化明令拦截项）；②`delete_forge_nodes` promote 同批删「祖先+后代」产生悬空 parent（违反「链不断」，依赖 id 排序）；③`delete_items_effect` redflag 模式不清红名节点自身 branch → 带 branch 中间节点红名复查必失败（TC-27 冲突） |
| **P2** | **6** | ①`forge_guard` 未集成红名拒绝（GU-03 语义缺口）；②死代码 `tree_raw`/`node_type_by_tree`/`branch_refs` 构建未消费；③`merge_node_item`「深拷贝」名不符实（浅拷贝共享嵌套引用）；④`MaterialReq.index`/`LimitByRarity.index` 恒 0（诊断定位字段未接线）；⑤V13/N-12「rarity 必填」与 AR-3「未配置继承」文档张力（实现取继承，建议文档对齐）；⑥validate_forge W4 为「存在稀有素材即提示」简化判定（完整途径数扫描在批2 `forge_deadlock.py`，分工提示） |

维度④（零 NoneBot import）与维度⑤（M43 零定时器）**确认无问题**。

---

## 一、维度① 定稿落地（逐条对照）

### 1.1 V1~V16 硬校验 + V16/W1~W6 黄（细化 §五，对照 forge_models.py）

| 规则 | 实现落点 | 判定 |
|---|---|---|
| V1 树级唯一 | `_check_tree_shape` L779-817：trees_empty / tree_id_required+duplicate / tree_type_invalid+duplicate | ✅ 对齐（细化 V1） |
| V2 节点全局唯一+树内一致 | `_check_node` L853-867：node_id_required+duplicate / node_type_tree_mismatch | ✅ |
| V3 父节点引用 | `_check_node` L870-888（parent_invalid/missing/cross_tree）+ `_check_cycle_and_reach` L1116-1124（roots_required/root_missing） | ✅（细化 V3 含 roots 存在性） |
| V4 树无环+可达根 | `_check_cycle_and_reach` L1126-1157：parent_cycle / parent_self_cycle / root_not_declared | ✅ |
| V5 分支可达 | `_check_node` L893-914：branch_not_list / branch_entry_invalid / branch_missing；重复 id → branch_duplicate 黄（去重告警） | ✅ |
| V6 终点=最终强化 | `_check_tree_nodes` L1219-1244：leaf_not_final / final_has_child / final_not_bool | ✅ |
| V7 node.item 引用 | `_check_node` L916-934：item_alias_duplicate（TC-08）/ item_required / item_missing | ✅ |
| V8 类型匹配 | L936-944：item_type_mismatch（items 条目 type vs node.type） | ✅ |
| V9 改造键空间 | L946-986：stats_not_object / stat_key_drift / element_invalid（键空间 = items 键 ∪ FORGE_STAT_KEY_SPACE ∪ 8 元素键） | ✅（实现聚焦 stats.* 键，slots/rarity/final 等顶层键由 V14/V13/V6 覆盖，符合防漂移本意） |
| V10 素材引用 | L1004-1018：material_item_required / missing / not_material_class（type=="material" 或含 material_tier） | ✅ |
| V11 素材数量/档位 | L989-1027：materials_required（≥1 行）/ not_list / row_not_object / count_invalid / tier_invalid | ✅ |
| V12 等级合法 | L1029-1036：node_level_invalid（≥1 整数） | ✅ |
| V13 品质合法 | L1038-1044 + `_normalize_rarity` L820-826：rarity_invalid，历史整数 1-4 兼容映射 | ✅ |
| V14 孔位合法 | L1046-1062：slots_not_list / slot_row_not_object / slot_level_invalid（{1,2,3}） | ✅ |
| V15 级联删除复查 | `_check_tree_nodes` L1246-1291：红名（item 缺失）→ red_name_referenced / red_name_branch_not_cleared | ⚠️ 规则实现对齐；**但 redflag 级联不清 branch → 带 branch 红名必拦（见 P1-3）** |
| V16 黄 | L1064-1071：augmentable_not_final_weapon | ✅ |
| W1 黄 | L963-968：stat_override_items | ✅ |
| W2 黄 | L980-986 + `_enemy_element_weaknesses` L563-583：element_no_weak_enemy（enemies 存在且无弱该元素怪） | ✅（批0 修过空弱点集误判，现正确） |
| W3 黄 | `_check_sets` L1464-1467 / `_check_augments` L1637-1640：sets/augments_disabled_but_data | ✅ |
| W4 黄 | validate_forge L1727-1763：synth_off_deadlock_risk | ⚠️ 简化判定，见 P2-6 |
| W5 黄 | `_check_tree_nodes` L1293-1303：weapon_scale（>500）/ armor_scale（>800） | ✅ |
| W6 黄 | `_check_tree_nodes` L1203-1211：root_level_not_1 | ✅ |

### 1.2 2c2d V1~V8 硬 / W1~W4 黄（细化 2c2d §五，对照 forge_models.py `_check_sets`/`_check_augments`）

| 规则 | 实现落点 | 判定 |
|---|---|---|
| V1 套装族唯一+变体唯一 | `_check_sets` L1327-1352：set_id_required / set_variant_invalid / set_variant_duplicate（(id,variant) 组合唯一；族 id 可 α/β 共用，VAR-01 合法形态） | ✅ |
| V2 套装件引用+部位 | L1354-1386：set_pieces_required / too_many（≤5）/ piece_invalid / missing / not_armor / duplicate | ✅ |
| V3 技能档位 2/3/5 连续 + level∈{1,2,3} | L1388-1449：set_skills_required / not_object / piece_count_invalid / skill_id_required / level_invalid / missing_start / gap；W4 set_skill_level_over_cap | ❌ **口径冲突见 P1-1**（细化明令「缺 5 档留 2/3 → 拦」，实现放行 {2,3}） |
| V4 客制项枚举结构 | `_check_augments` L1493-1576：augment_id_required+duplicate / kind_invalid（numeric/slot）/ numeric 必填 stat_key / slot 必填 slot_level∈{1,2,3} / cost≥1 行 + count≥1 | ✅ |
| V5 客制消耗引用 | L1548-1571：augment_cost_item_required / missing / not_rare（龙脉石类须 material_tier:rare） | ✅（宝石类经 items 存在性覆盖；DEAD-04 途径扫描归批2） |
| V6 次数表 | L1596-1635：limit_not_list / row_not_object / quality_invalid（四档枚举）/ times_invalid / final_only_not_bool / final_only_requires_legendary / quality_too_many（≤2 行） | ✅ |
| V7 节点扩展 | `_check_node` L1073-1093：king_only level<7 → 黄 / final_tier 非 final+legendary → 黄 / 非 bool → 硬；augmentable 复用 V16 | ✅（细化 V7 各子判定为 W3/W4 黄提示，实现一致；编号重名已补白声明） |
| V8 客制全段 disabled | `_check_augments` L1589-1594：augments_all_disabled 黄 | ✅ |
| W1 α/β 孔位对照 | `_check_sets` L1451-1462：alpha_beta_slot_mismatch（α>β 黄） | ✅ |
| W2 追溯行 | `_check_augments` L1583-1587：augment_trace_legacy（回复已砍不生效） | ✅ |
| W3 settings 关但数据存在 | 并入 2c2a W3（见上） | ✅ |
| W4 技能 level 超封顶 | `_check_sets` L1441-1449：set_skill_level_over_cap | ✅ |

### 1.3 双源仲裁 AR-1~5（细化 §1.3，对照 forge_models.py `merge_node_item` L589-645 + forge_tree.py `merge_forge_instance` L374-394）

| 规则 | 实现 | 判定 |
|---|---|---|
| AR-1 覆盖 | stats 键级合并（节点 stats 覆盖 items 同键）+ 顶层键 slots/monster_source/final/augmentable/king_only/final_tier/cost/level/name/type 以节点为准 | ✅（细化 AR-1 列表 stats.*/slots/rarity/monster_source/final/augmentable…，实现扩展 name/type/level/cost/king_only/final_tier 属「节点=形态定稿」合理延伸） |
| AR-2 追加 | `out = dict(base)`，节点未声明键继承 items | ✅ |
| AR-3 品质 | 节点 rarity 声明 → out["rarity"]=节点值；未声明 → 继承 items["quality"]（L627-631） | ✅（与细化 AR-3「未配置=继承 items.quality」一致；「必填」表述张力见 P2-5） |
| AR-4 配置模式 | 天然支持瘦 items+富节点 / 富 items+薄节点 | ✅ |
| AR-5 实例快照 | `merge_forge_instance` setdefault stats/slots/rarity/final/augmentable/monster_source 缺省键 | ✅ |

### 1.4 级联删除 ①② 路径（细化 §12.1.2，对照 forge_cascade.py）

| 场景 | 路径 | 实现 | 判定 |
|---|---|---|---|
| 删 items → 树同步 | ① redflag 保留标红 | `delete_items_effect` L252-265：被引节点+整棵子树 `redflagged:true`（补白2） | ⚠️ 标红对齐；**未清红名节点自身 branch → P1-3** |
| 同上 | ② remove 整棵子树移除 | L267-289：`_clean_refs`（branch/roots 同步清理）+ 移除子树 | ✅ |
| 删 forge 节点 | ① promote 上提重连 | `delete_forge_nodes` L333-353：直接子 parent→原父的父；被删根节点直接子上提为根（_add_root） | ⚠️ **同批祖先+后代悬空 → P1-2** |
| 同上 | ② remove 整支移除 | L354-357：`_clean_refs` + `_remove_nodes` | ✅ |
| 复查 | cascade_recheck | L413-483：validate_forge 全量 + redflag_expected 过滤 + dangling_errors（_DANGLING_RULES） | ✅（V15 判定面 = V3/V4/V5/V15/非红名 V7；V6 等作者标注类留在 errors 不计级联失败，补白5） |
| 红名查询 | is_redflagged | L527-538：redflagged:true / invalid:true 双标记 + ForgeNode/raw 双形态 | ✅ |

---

## 二、维度② 代码质量

| 项 | 结论 |
|---|---|
| 确定性（无随机/定时器） | ✅ 4 文件无 random/time/threading/Timer/schedule/sleep 字面量（grep 零命中）；遍历均按文件序/字典序确定 |
| 纯函数入参不变性 | ✅ `delete_items_effect`/`delete_forge_nodes` 均 `copy.deepcopy(forge)` 后改写，返回新 dict，不改写（测试 test_inputs_not_mutated_* 覆盖）；`cascade_recheck` 对 modules 仅浅拷贝重赋 forge 键不污染。⚠️ `merge_node_item` 声称「深拷贝」实为浅拷贝（见 P2-3） |
| 跨树/跨模块边界 | ✅ content 层（forge_models/forge_settings）只依赖 `qbot_rpg.content.models`，不 import core（G0 单向）；core 层（forge_tree/forge_cascade）只依赖 content 层，无环 |
| merge_node_item 非 str 字段兜底 | ✅ stats 键 `str(k)` 归一、非 str 值原样透传（由 V9 校验层拦截）；item_ref/node_id 非 str 跳过不写；rarity 非 str 原样透传（V13 校验层拦截） |
| 收集器三形态 | ✅ `_emit` L518-537 兼容 error/warning 方法 → _err/_warn → dict 兜底（契约 §七） |
| 死代码 | ⚠️ `tree_raw`/`node_type_by_tree`/`branch_refs` 构建后未消费（见 P2-2） |

---

## 三、维度③ 遗漏检查（细化 §六 TC-01~27 覆盖）

批A 范围（数据层/引擎/级联；指令渲染归批4 指令壳，非本批）：

| TC | 覆盖 | 说明 |
|---|---|---|
| TC-01/02（树加载/type 唯一） | ✅ | validate_forge V1/V2 + ForgeTree 解析 |
| TC-03（branch 提示） | ✅ | engine.branch_of（数据层） |
| TC-04/04b（V6/W5） | ✅ | leaf_not_final/final_has_child + weapon/armor_scale |
| TC-05~09（V7/V8/AR-1/AR-2/AR-3/别名） | ✅ | merge_node_item + V7 item_alias_duplicate |
| TC-10/11（material_tier 派生/行覆写） | ✅ | ITEMS_FORGE_FIELDS + V11 tier 枚举（派生计算归批2 forge_material） |
| TC-12（3:1 合成） | ✅ | settings.synth_ratio_3to1 读段（执行器复用 synthesis.py，摸底缺口1 已实装） |
| TC-13~15/18（/图纸 /锻造 流程） | ✅ 数据侧 | 树引擎 path_to_root/subtree_of + resolve_source_text 缺件来源（指令壳批4） |
| TC-16/17（确定性） | ✅ | 引擎纯函数零随机 |
| TC-19~24b（校验器负例） | ✅ | V3/V4/V5/V2/V7/V8/V10/V6/W1/W2 全数 |
| **TC-25（级联 ①② 红名保留/子树移除）** | ⚠️ | 叶子路径正例 ✅；**带 branch 中间节点红名 V15 复查必失败（P1-3），且补白仅声明 parent 残留场景，未声明 branch 场景** |
| **TC-26（删节点 promote/remove）** | ⚠️ | 单节点 promote/remove ✅；**同批删祖先+后代产生悬空 parent（P1-2），行为依赖 id 排序，测试未覆盖** |
| TC-27（复查） | ✅ | cascade_recheck 零悬空判定面成立（红名父链完整） |

**红名保留 / 子树移除 / 重连链不断 / 零悬空** 四项验收点：红名保留 ✅（叶子）、子树移除 ✅、重连链不断 ⚠️（单节点 ✅ / 同批多删 ❌ P1-2）、零悬空 ⚠️（P1-2 + P1-3 边界）。

---

## 四、维度④ 零 NoneBot import

**确认无问题。** 4 文件全部 import 语句仅涉及标准库 + `qbot_rpg.content.models` / `forge_models` / `forge_settings`。docstring 中「零 NoneBot import」字样为铁律声明，非 import 语句（任务口径：docstring 提及不算）。

## 五、维度⑤ M43 零定时器

**确认无问题。** 4 文件全文（含 docstring）均无字面量 `time.sleep` / `threading.Timer` / `schedule`（grep 逐文件零命中）。记录.md 记载批0 曾命中 time.sleep 字面量并已修复，当前干净。

---

## 六、问题清单（P0/P1/P2）

### P1-1：2c2d V3 档位连续性口径与细化 §五 V3 冲突（硬校验放行细化明令拦截项）
- **位置**：`forge_models.py` L56-60（工程补白 8）、L1420-1440（连续性判定）
- **依据**：细化 2c2d §五 V3「同一 skill 档位按 2<3<5 递增连续（**缺 5 档留 2/3 → 拦**；缺档会制造非预期激活曲线）」
- **现状（静态推导）**：对 pcs={2,3}，`ordered=[2,3]`，need 从 2 起逐一命中到 5，循环自然结束，**无 set_skill_gap** → 放行 {2,3}。补白 8 明确「缺 5 档留 2/3 按跳档口径不拦」，属对细化显式规则的**反向解释**（工程补白本应填补「未显式定义」处，此处细化已显式定义「拦」）。
- **影响**：{2,3} 档位数据（缺 5）通过加载，穿 5 件时按 ACT-02 取 ≤N 最大档回落 3 件档，产生细化所称「非预期激活曲线」。
- **修复建议**：对齐细化 —— 连续性判定尾追加「ordered 未达 {2,3,5} 完整前缀即缺 5 档 → set_skill_gap / 新 rule=set_skill_missing_cap 红拦」；或与细化/契约方发起规则变更（需用户拍板，勿擅改）。

### P1-2：delete_forge_nodes promote 同批删「祖先+后代」产生悬空 parent（违反「链不断」，依赖 id 排序）
- **位置**：`forge_cascade.py` L333-353（promote 分支）、L322-330（present/affected 构建）
- **依据**：细化 2c2a §12.1.2 ①「子节点上提重连（parent 指向原父节点的父节点，**链不断**）」+ TC-26
- **现状（静态推导）**：设删 A（子，父=P）与 P 同批，B 为 A 的直接子。`present=sorted([A,P])`。若 A 先处理：`by_id[A].get("parent")=P` → grand=P → `B.parent=P`；随后处理 P：grand=PP，改 A.parent=PP；`_remove_nodes` 删 A、P。**B.parent 残留 = P（已删）→ 悬空 parent**，cascade_recheck 会以 parent_missing 红拦。若排序使 P 先处理（P 处理时 A.parent=PP，A 处理时读到 PP），则 B.parent=PP 链完整。**结果依赖 id 字典序**——确定性但语义错误，测试仅覆盖单节点删除（test_tc26a_*），未覆盖此边界。
- **修复建议**：promote 前先计算「每个被删节点的最终存活祖父链」——当 grand ∈ present 时继续上溯到首个不在 present 的祖先（或 None），再统一重连；并对「被删根节点 + 其直接子亦被删」的场景断言 roots 无残留（_clean_refs 已清 roots，但重连目标须最终存活）。

### P1-3：delete_items_effect redflag 模式不清红名节点自身 branch → 带 branch 中间节点红名后 V15 复查必失败
- **位置**：`forge_cascade.py` L252-265（redflag 分支，仅标红未清 branch）；对照 `forge_models.py` L1286-1291（V15 red_name_branch_not_cleared）
- **依据**：细化 2c2a §五 V15「级联操作后无残留悬空引用（红名节点父链完整、**branch 已清**）」+ TC-25①「均无悬空」/ TC-27「V15 复查通过」
- **现状（静态推导）**：删 items → redflag 只对子树加 `redflagged:true`，**不清红名节点 branch**。若被引节点带 branch（fixture 中 node_flame_sword_2.branch=[冰剑,雷剑] 即此类），V15 对红名节点 branch 非空 → `red_name_branch_not_cleared` 硬拦 → cascade_recheck ok=False。补白 2 仅声明 parent 残留（red_name_referenced）负例，未声明 branch 残留场景；测试 test_tc25a_delete_item_redflag_mid_negative 用的中间节点 branch 为空。
- **修复建议**：redflag 分支对被引红名节点（及其标红节点）同步清空 `branch` 字段（对齐 remove 的 _clean_refs 精神，或仅对 V15 判定 red_nodes 清 branch）；并在补白 2 显式声明「带 branch 红名的 branch 残留处置」，补 test 覆盖。

### P2-1：forge_guard 未集成红名拒绝（GU-03 语义缺口）
- **位置**：`forge_tree.py` L349-369（forge_guard 组合守卫）
- **依据**：细化 2c2b §1.1 GU-03「节点存在 & 可锻；**红名失效节点拒绝**（级联删除①，2c2a §五 V15）」
- **现状**：forge_guard 仅 resolve→already_forged→parent_forged→node_level_met，无 is_redflagged 检查；reason 枚举无 redflag 项。当前指令壳 `forge_commands.py` L787-789 自行实现 GU-03b is_redflagged 拒绝（未使用 forge_guard），故运行路径无漏洞，但 forge_guard 作为引擎侧「GU-03→04→06 组合守卫」语义不完整。
- **修复建议**：forge_guard 增 is_redflagged 检查（引入 core.forge_cascade 依赖或注入判定），reason 增 `redflagged`；或 docstring 明确「红名拒绝由指令壳 GU-03b 另行承担」。

### P2-2：死代码——tree_raw / node_type_by_tree / branch_refs 构建后未消费
- **位置**：`forge_models.py` L810-817（node_type_by_tree/tree_raw 构建）、L1669（接收）、L913-914（branch_refs 填充）、L1676/1717（传递）
- **现状**：`node_type_by_tree`/`tree_raw` 由 `_check_tree_shape` 返回后仅赋值未使用；`branch_refs` 全程只增不减、V5 重复判定用本地 seen_b，branch_refs 从未读取。
- **修复建议**：删除未消费的返回/参数，或补用途（如 V15 级联复查以 branch_refs 交叉验证）；降低维护噪音与 lint 负担。

### P2-3：merge_node_item 文档声称「深拷贝」实为浅拷贝（嵌套引用共享）
- **位置**：`forge_models.py` L600（docstring「深拷贝，不改写入参」）、L603/607（`dict(base)` 浅拷贝）
- **现状**：`out = dict(items_def)` 浅拷贝；若 node 无 stats，`out["stats"]` 与 items_def["stats"] 共享同一 dict 引用，下游若对快照 stats 做可变操作会污染 items 表。当前消费方（merge_forge_instance）只 setdefault 不改嵌套，风险低。
- **修复建议**：docstring 改「浅拷贝，嵌套结构共享引用，调用方不可改写嵌套值」，或对 stats/slots/cost 等嵌套容器做一层深拷贝。

### P2-4：MaterialReq.index / LimitByRarity.index 恒 0（诊断定位字段未接线）
- **位置**：`forge_models.py` L284（MaterialReq.index 补白字段）、L449（LimitByRarity.index）、L241-242/L356-357（from_entry 调用未传 index）
- **现状**：`material_defs()`/`skill_defs()` 调 `from_entry(e)` 均未传行号，index 恒默认 0，docstring 声称「行序号供诊断定位」功能形同虚设。
- **修复建议**：`material_defs`/`limit_defs` 遍历时传 `index=i`（与 ForgeTree.node_defs 的 index 口径一致）。

### P2-5：V13/N-12「rarity 必填」与 AR-3「未配置继承」文档张力
- **位置**：`forge_models.py` L1039-1044（V13 仅校验格式，未查必填）
- **依据**：细化 2c2a N-12 必填=是；AR-3「未配置 = 继承 items.quality」。两处表述并存。
- **现状**：实现取 AR-3 继承口径（合理），V13 不拦缺失。
- **修复建议**：非缺陷，仅建议细化/契约对 N-12 必填列与 AR-3 继承口径做一致性说明（若意图必填则 V13 补 rarity_required 红拦；若意图可继承则 N-12 必填列改否）。

### P2-6：validate_forge W4 为「存在稀有素材需求即提示」简化判定
- **位置**：`forge_models.py` L1727-1763
- **依据**：细化 2c2c DEAD-04「稀有素材 ≥2 途径」+ 契约 W4「素材死锁风险」
- **现状**：W4 仅在 synth_ratio_3to1=false 且 forge 素材需求出现 rare 时黄提示，未做途径数扫描（扫描实现归批2 `forge_deadlock.py`，分工明确）。
- **修复建议**：批A 内可保留（分工合理），建议在补白 6 补充「完整途径数死锁扫描见 core/forge_deadlock.py」交叉引用，防误读为完整实现。

---

## 七、无问题维度确认

| 维度 | 结论 |
|---|---|
| ④ 零 NoneBot import | ✅ 确认无问题（4 文件 import 语句全部干净） |
| ⑤ M43 零定时器 | ✅ 确认无问题（docstring 无 time.sleep / threading.Timer / schedule 字面量） |
| 确定性 / 纯函数 / 跨模块边界 | ✅ 确认无问题（除 P2-3 浅拷贝注记外） |

---

*审查完毕 · 静态推导 · 2026-08-30*
