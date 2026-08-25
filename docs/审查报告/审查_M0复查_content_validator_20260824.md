# 审查_M0复查_content_validator_20260824（内容包校验器 validator · 批2a-路2）

> 审查对象：`qbot_rpg/content/validator.py`（**实际 695 行**；任务描述与前批报告所称「587 行」为旧快照行数，文件已扩展，下文行号以 695 行实文件为准）
> 对照基准：《细化_3e_loader校验接线.md》（R-1~R-5 §2.1 / Y-1~Y-8 §2.2 / 兜底默认放行 §2.3 / 只建议不限制十项 §3.1 / 安全例外 §3.3 / TC-01~30）+《细化_3e2_热重载契约.md》（BLK-1~5）
> 辅助对照：`qbot_rpg/content/{loader,hot_reload,field_meta,models,registry}.py`、`tests/unit/test_content.py`、`细化_3b_玩家属性三层.md`（仲裁 C-1 记录）、`contract_deviations.md`、前批《审查_M0_content_20260818.md》
> 审查方式：**纯静态审查**（本环境无 bash 沙箱，禁止运行任何命令/脚本/验证）；所有运行行为结论一律标注「静态推导」
> 审查日期：2026-08-24

---

## 结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 无「必崩/必然放行坏配置」级问题；阻断式抛错、默认放行兜底、非空转接线均成立 |
| **P1** | **1** | formula 安全例外黑名单经简化词法仍可绕过（方括号字符串键 / Unicode 转义标识符，两条新路径） |
| **P2** | **7** | x_ 字段内引用未查（TC-19 后半）、链 next 悬空未红拦、Y-3 零实现、conditional 红黄分级跨模块不一致+注释状态失准、manifest 双次校验重复报错、非 dict manifest 裸 AttributeError、validator 硬编码 conditional 违反 §5.3 防漂移 |
| **P3** | **6** | int 严格性/NaN 双报、上限字段缺失无 Y-4、skill_or_any 过宽、map 非法键先注册、conditional 缺 id 双报、Y-7 默认死分支+slot 部位引用未接线 |

维度②「校验器空转零注册」：**确认无问题**（validator 真实被 loader/hot_reload 调用并门控挂载，测试覆盖 R-1~R-5/Y-1/Y-2/Y-4/Y-6/Y-7/formula/回退/节流）。
维度③ 幻觉核验：文档节号引用全部与 3e/3e2 实文一致；前批 P1-1 修复注记与实现一致；仅 conditional 注释对仲裁状态表述过期（并入 P2-4）。

---

## 一、维度① 错误（bug / 边界 / 红黄分级 / 安全例外 / 循环检测）

### 🟥 P1-1 formula 安全例外：AST 黑名单经「简化词法」仍可绕过（两条新路径）【静态推导】

- **位置**：`validator.py:55-74`（`check_formula`）+ `77-153`（`_strip_literals`）；受影响即 3e §3.3 安全例外（硬约束，不受只建议不限制覆盖，TC-29）
- **前批状态**：前批《审查_M0_content_20260818.md》P1-1（模板串插值绕过/块注释误伤）**已修复**——`_strip_literals` 现保留 `` `${...}` `` 插值内容（L109-135）、剥离 `/* */` 块注释（L145-150），`test_formula_blacklist_hidden_in_string_ok` 亦验证字面量内黑名单词不误报。本批确认修复有效，但**同一安全保证仍存在两条未闭合路径**：
  - **路径 A 方括号字符串键取构造器**（静态推导）：`a["constructor"]["constructor"]("return process")()`。`_strip_literals` 将 `"constructor"` 当作字符串字面量整体剥离（L89-100），`_FORMULA_IDENT_RE`（L55）只见 `a[][]()()`，黑名单不可见 → 返回 None（通过）。JS 语义下该串即经典 `x["constructor"]["constructor"]("return process")()` RCE 链。
  - **路径 B 标识符 Unicode 转义**（静态推导）：`F\u0061nction("x")` / `ev\u0061l(1)`。词法正则 `[A-Za-z_$][A-Za-z0-9_$]*` 遇反斜杠断词，token 拆为 `F` + `u0061nction`（均不在黑名单）→ 通过；而 JS 语义等价于 `Function`/`eval`。
- **分级理由**：§3.3 是唯一允许在 5 类红拦外加红的硬安全例外，契约要求「AST 黑名单」语义；简化词法（已注释「M0 无外部 JS 解析器依赖」）未达到该语义，且绕过串具体可复现，故定 P1。
- **修复建议**：① 扫描前先对表达式做 Unicode 转义归一化（`\uXXXX`→字符）再跑标识符扫描；② 对「方括号内字符串键」单独检查其字面内容是否命中黑名单（与 `'eval' + x` 的普通字符串用法区分需结构感知，建议至少对 `[“<黑名单词>”]` 形态单独命中）；③ 若 M0 确实无法做到结构解析，须在 `contract_deviations.md` 显式登记「安全例外降级为词法近似」并列出已知绕过，禁止静默（3e §0.3 变更纪律）。

### 🟡 P2-4 conditional 未注册 stat 键红拦 R-4 与 3e Y-7/§3.1-9 跨模块分级不一致；注释仲裁状态失准

- **位置**：`validator.py:310-314`（`_check_conditional` 接线）、`338-341`（source/target 未注册 stat 键 → **R-4 红**）、`553-557`（通用 `ref_target="stat"` → **Y-7 黄**，`test_y7_unregistered_stat_key` 证实可达）
- **实际**（静态推导）：同一「stats.json 键空间」，通用消费方（enemies.key_ref 等经 meta 注入）走 Y-7 黄放行，唯独 conditional 模块 source/target 走 R-4 红拦 → 跨模块分级不一致。3e §2.2 Y-7 与 §3.1-9 明示「未注册属性键 → 黄提示不拦截」。
- **缓解事实**：`细化_3b` L42/ADR-05、L161 与 `contract_deviations.md` §三 **C-1（2026-08-18）已裁红拦**（自环/互环统一红），故 conditional 取红**有仲裁依据**、非无据偏离。
- **问题**：`validator.py:311-312` 注释称「为跨文档冲突（dsh 审查 P2-9，**上报用户/仲裁**）；此处按 3b 场景语义取红」——把冲突表述为**待仲裁**，但 C-1 已于 2026-08-18 裁决、3b L162 已落字，注释状态**过期失准**（维度③）。
- **修复建议**：注释改引「3b ADR-05 + 2026-08-18 仲裁 C-1（contract_deviations.md §三）」作为红拦依据，注明「仅 conditional 专项、非 3e Y-7 通用口径」；若追求一致可把该键空间红/黄口径提交用户拍板统一，否则显式登记 module-specific 特例。

### 🟡 P2-7 validator 硬编码 conditional 模块/字段名，违反 §5.3「校验器只实现规则引擎，不包含任何具体字段名（L140 防漂移）」

- **位置**：`validator.py:310-346`（`module_name == "conditional"` + `source`/`target`/`id` 字面量）
- **实际**：条件加成依赖图/键空间检查绕过 meta 机制（chain_field/ref meta），在规则引擎内写死模块与字段名。field_meta 已把 conditional 结构声明进表（field_meta.py:187-202），故类型层是通用的，但环/R-4 逻辑硬编码。
- **修复建议**：优先用现有通用机制表达（conditional 可借 `chain_field` 类结构 + ref 到 `stat` kind），或把该专项显式标注为「受控例外，对应 P1-1 接线」，避免后续字段漂移时漏检。

### 🟢 循环检测（维度①专项）——确认正确【静态推导】

- **链成环**（`validator.py:572-616`）：DFS 三色判有向环，含自环（A→A），命中报 R-5 `chain_cycle`；仅报一条后停止，符合阻断语义。✓
- **部位互斥环**（`validator.py:618-665`）：前批 P0-2（对称互斥对重复 union 误报）**已修复**——现先用 `frozenset` 去重为无向边集再并查集（L627/L642），武器↔盾合法互斥对不再误判，≥3 件成环正确红拦（测试 `test_mutex_cycle_red`）。✓
- **条件加成依赖环**（`validator.py:348-368`）：DFS 判有向环含自环（source==target）→ R-5，符合 C-1「自环/互环一律红拦」。✓
- 三者均为静态推导结论（未运行）。

### 🟡 红/黄分级其它核对——确认正确

- R-1 类型（str 数字「12」→ R-1，`validator.py:511-514` ✓）、R-2 负数（`allow_negative` 门控，`523-525` ✓）、R-3 NaN/Infinity（`519-522`，TC-04 ✓）、R-4 引用（`551-569`，stat→Y-7 除外 ✓）、R-5 结构（必填/死配置 `min>max`/`reset eq≠max`/`battle+revert`/互斥环/链环 ✓，TC-06~08）。
- Y-1/Y-2/Y-4（`532-549`）只进 warnings 不阻断 ✓；Y-5 软标注永不红拦（`453-454`）✓；Y-8/未知字段默认放行（`417-418`）✓（但内引用不查，见 P2-1）；§3.1 十项不拦清单无一误作红拦 ✓（与前批一致）。
- 安全例外其余项：公式长度 >4KB（L64-65）✓；「结果 >1KB / 求值超时 10ms」属运行期引擎职责，validator 无法静态判，非缺漏；zip 导入安全链在 loader/编辑器侧，validator 无责。✓

---

## 二、维度② 缺漏（细化/定稿要求未实现）

### 🟡 P2-1 x_/未知字段内引用存在性未查（Y-8「仅查引用存在性」/ TC-19 后半未实现）——前批 P2-5 复查确认仍在

- **位置**：`validator.py:413-419`（`if fmeta is None: continue` 整段跳过未知/x_ 字段，不递归）
- **实际**（静态推导）：`x_my_field: {"effect_id": "ghost"}` 或含 ref 形状的值被整体放行，内部引用永不被查。3e Y-8/L145 + TC-19（L393）要求「引用不存在的 x_ 字段内引用 → 按 R-4 查」；`tests/unit/test_content.py:266-274` 的 docstring 声称覆盖该点，但**断言仅覆盖标量放行**（`x_my_field: "任意值"`），docstring 过度声明。
- **修复建议**：二选一——(a) 对未知字段值做「引用形状」探测（如值为含 `ref`/`id` 键的 dict 或命中注册 kind 命名字符串则查存在性）；(b) 明确无法在无 meta 下判定引用目标，登记递延并在测试 docstring 撤回过度声明。

### 🟡 P2-2 skill_chains `next` 悬空引用未红拦【静态推导】

- **位置**：`validator.py:572-616`（`_check_chain_cycle`：`if v not in color: continue` 静默跳过未定义链节点）+ `field_meta.py:124`（`next` 声明为普通 str 列表，非 ref）
- **实际**：链 A 的 `next` 指向包内不存在的链 id → 只做环检测，不做存在性检查，静默通过。§3.2「引用悬空 → 红拦」口径下应 R-4；§5.2 只列了「链内节点引用 skill/action 不存在」为 R-4，`next` 悬空属同类漏洞面。
- **修复建议**：field_meta 将 `next` 声明为 `ref_target="skill_chain"`（顺带自动获得 R-4 存在性 + 类型检查），或 `_check_chain_cycle` 对 `adj` 中非 `id_set` 的目标报 R-4。

### 🟡 P2-3 Y-3 组合强度零实现零测试——前批 P2-3 复查确认仍在

- **位置**：`validator.py` 全文件无 Y-3 分支（grep 无命中）；`tests/unit/test_content.py` 无 Y-3 用例
- **实际**：3e §2.2 Y-3 与 §5.2（skill_chains 链长/组合强度、items 一身神装、action 消耗/冷却）与 TC-14 要求 Y-3 提示。与 §3.1-10「数值强弱推断超出校验器职责」存在张力。
- **修复建议**：实现一条可判定的保守启发（如「倍率+无消耗+必中同现」）并配 TC-14 测试，或显式在 validator/field_meta 注释登记「Y-3 依 §3.1-10 由玩法测试承担，实现递延」，二选一、禁止静默。

### 🟡 P2-5 manifest 双次校验 → 同一红拦在 combined.errors 重复——前批 P2-2 复查确认仍在

- **位置**：`loader.py:198`（`check_pack({"manifest": manifest_raw})` 独立校验）+ `loader.py:232-233`（再把 manifest 塞进 modules 参与整包 check_pack）
- **实际**（静态推导）：manifest 缺 name/modules 等红拦时，`combined.errors` 同一错误出现**两次**；TC-10「3 处红拦一次给全」口径下破坏清单清洁度（人话聚合会重复）。
- **修复建议**：去掉独立校验（保留首次 JSON 解析错误即可），或整包校验结果对 manifest 去重。

### 🟡 P2-6 manifest 顶层非 dict（合法 JSON 数组/字符串）→ 裸 AttributeError，违反 PackLoadError 领域异常模型【静态推导】

- **位置**：`loader.py:200`（`Manifest.from_dict(manifest_raw)` 在 C 阶段判定生效前执行）+ `models.py:299-311`（`data.get(...)` 对 list/str 直接 AttributeError）
- **实际**：`manifest.json` 为合法 JSON 数组/字符串时，validator 会正确报 R-5（`validator.py:271-278`），但 loader 先崩出裸 `AttributeError`。首次 `load_pack` 抛错类型错误；热重载路径被 `_reload_sync` 泛 `except` 兜住（hot_reload.py:241-246）转 R-5 `unexpected_error`，故不崩服务但语义降级。
- **修复建议**：`Manifest.from_dict` 入口先验 `isinstance(data, Mapping)`，非 dict → 返回/抛出由管线统一转 PackLoadError。

---

## 三、维度③ 幻觉核验（注释引用真实性 / 冒充定稿 / 工程补白标注）

### ✅ 确认无问题的项

- **节号引用真实性**：validator.py 头注释与全文件引用的 3e §2.1/2.2/2.3/3.3/5.1/5.2/5.3、3e2 BLK-1 均与两基准文档实文**逐节核对一致**（红拦 5 类封闭、黄提示开放、兜底放行、formula 安全例外、§5.3 元数据表唯一数据源均吻合）；「【规则】L92/L145/L146/L448/L449」等 L 行号指向开发规则文档，不在本仓库可验证范围，但与 3e 转引一致，未见编造。
- **修复注记真实性**：`_strip_literals` 的「修复（2026-08-18 dsh 审查 P1-1）」与代码实现一致（模板插值 `${...}` 保留 L109-135、块注释剥离 L145-150）；互斥环「修复记录（M0 测试验收 2026-08-18）」与实现一致（frozenset 去重 + 并查集 L627/L642）。两条前批修复均真实落地。
- **M0 工程补白标注**：`check_formula`「M0 无外部 JS 解析器依赖」（L62）、`skill_or_any`「M0 无技能库模块场景」（L559）、field_meta「正式元数据表注入」等均**显式标注**，无冒充定稿之嫌。
- **非幻觉项**：文件 695 行 ≠ 任务描述/前批报告「587 行」——属文件扩展后的旧行数失效，非代码幻觉（已在本报告头注明）。

### 🟡 并入 P2-4 的失准项

- `validator.py:311-312` 将 conditional 键空间红/黄冲突表述为「上报用户/仲裁（待决）」，实际 2026-08-18 仲裁 C-1 已裁决红拦（3b L162 / contract_deviations.md §三）——注释对仲裁状态表述过期，见 P2-4。

---

## 四、P3 级明细（边界/提示级）

- **P3-1** `validator.py:516-521`：int 字段填 `3.0`（JSON float）→ 判 R-1（`expect int, got float`）偏严格，作者写 `max_stack: 3.0` 会被误红；int 字段填 NaN → 先报 R-1 再报 R-3 双条。建议：int 判定改为「数值且小数部分为 0 即过」；NaN 分支提前 return 避免双报。
- **P3-2** `validator.py:535-536` + `field_meta.py:54`：上限字段**缺失**不产生 Y-4（TC-15 字面「缺失 → warnings 含 Y-4」口径未达）；且默认 meta 仅 `max_stack` 接线 zero_unlimited，TC-15 的 `crit.cap`/`max_combo` 未入表（未知字段放行）。建议明确口径并登记。
- **P3-3** `validator.py:558-564`：`skill_or_any` 命中**任一**注册 kind 即通过，与其它 kind ID 撞名时会吞真实悬空 skill 引用（R-4 false-negative）。M0 已注释，建议登记递延。
- **P3-4** `validator.py:207-223`（_collect_ids）vs `284-294`（key_regex）：map 模块非法键先注册进 `_id_space` 后报 R-5 `key_invalid`，非法键会短暂满足 Y-7 引用查询（前批 P2-6 复查仍在）。建议 _collect_ids 预筛 key_regex 或 Y-7 查询排除非法键。
- **P3-5** `validator.py:332-333` + `field_meta.py:193`：conditional 规则缺 `id` 时，通用必填检查（_check_entry）与 `_check_conditional` 手动检查**双报** required_missing。建议去重。
- **P3-6**（复查确认，非新问题）：Y-7 在默认 meta 下仍无消费方字段（默认死分支，仅测试经自定义 meta 注入可达）；`slot` 部位引用仍无 ref_target（前批 P1-2 复查仍在，属 field_meta 侧、validator 通用机制已具备）。建议随编辑器元数据表注入一并落地。

---

## 五、复查对照：前批问题闭合情况（validator 相关）

| 前批条目 | 状态 |
|---|---|
| P1-1 formula 模板串插值/块注释缺陷 | ✅ 已修复（本批复核 _strip_literals 实现一致）；但见新 P1-1 两条绕过 |
| P0-2 互斥无向边去重缺失 | ✅ 已修复（frozenset 去重 + 并查集） |
| P1-2 部位引用存在性未校验 | ⚠️ 仍开放（field_meta slot 无 ref_target，validator 通用机制已备）→ P3-6 |
| P2-2 manifest 双次校验重复 | ⚠️ 仍开放 → P2-5 |
| P2-3 Y-3 组合强度零实现 | ⚠️ 仍开放 → P2-3 |
| P2-5 x_ 字段内引用未查 | ⚠️ 仍开放 → P2-1 |
| P2-6 map 非法键先注册 | ⚠️ 仍开放 → P3-4 |
| P2-4 Y-7 死分支 | ✅ 部分改善（现经自定义 meta 注入可测可达），默认 meta 仍无消费方 → P3-6 |

---

## 六、维度② 空转/接线核验（确认无问题）

- validator 非空转：`loader.build_pack` 两处调用 `check_pack`（manifest 独立 + 整包，L198/L233），`report.ok` 门控 registry 构建与挂载（L238-242，D-02）；`hot_reload._reload_sync` 每轮重载均经 `build_pack`（hot_reload.py:234），无旁路可绕过校验。
- 测试证据（静态核验存在性）：`tests/unit/test_content.py` 覆盖 R-1~R-5（type/negative/nan/required/dead_range/mutex_cycle）、Y-1/Y-2/Y-4/Y-6/Y-7、x_ 放行、formula 安全（黑名单/超长/字面量不误报）、热重载成功增量/失败回退/连续失败暂停、parse_cache 增量。
- 兜底默认放行（§2.3）成立：未知字段/未登记模块均放行，红拦清单封闭无外溢，§3.1 十项均不红拦（前批已证、本批复核一致）。
