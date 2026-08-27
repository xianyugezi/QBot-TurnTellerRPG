# 审查报告 · M6 实现批 6B（测试体系强化 · 公式性质测试 PRP + validator 标量透传）

> 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未执行任何命令/脚本/测试）；一切运行期行为结论均为**静态推导**，标注「静态推断」。
> 审查文件：
> - `tests/unit/test_formula_property.py`（455 行，1000 组×3 不变量 + PRP-8 确定性）
> - `qbot_rpg/content/validator.py`（formula 模块标量透传 FIX-2，L1493-1504）
> - `tests/fixtures/packs/legal/formula.json`（F-FIX-01~27 全段落位）
> 契约：`docs/细化/细化_M6_测试体系强化.md`（D6）§一 PRP-1~8 / TC-PRP-01~05 / §八 决策记录；`docs/细化/细化_1a_伤害公式数值.md`（【1a】）§3-B/M9/L119-137 等。
> 结论：**P0=0，P1=0，P2=6**（其中 2 条为轻量文档/口径条目）；无阻塞项，可 ship。

---

## 一、D6 契约落地核对（维度①）

### 1.1 PRP-1~8 逐条对账

| 规则 | 契约要求 | 实现落点 | 判定 |
|---|---|---|---|
| PRP-1 载体文件 | `tests/unit/test_formula_property.py`，无 hypothesis | 文件落盘；无 hypothesis import（L33-40）；4 条测试函数 ≥3 | ✅ |
| PRP-2 组数 | 三条不变量各 1000 组，不缩水 | `N_GROUPS=1000`（L67）；不变量①`_collect_groups(count=1000)`（L280-288）+ `assert len(groups)==count`（L262）；不变量②主循环收集 1000 组（L315-324）+ 组数断言（L324）；不变量③`for i in range(N_GROUPS)`（L371） | ✅ |
| PRP-3 不变量① | total_damage ≥1 且命中侧通道 ≥1 | L289-292 逐组断言；0 攻击/0 元素/0 体质边界组 L251-252，断言通道恰为 1（L295-296）。数学依据【1a】§3-B L298-299：`max(1, floor(...))` 兜底（damage.py L470/L502/L548） | ✅ |
| PRP-4 不变量② | 非会心 ∈ [floor(基础×0.95), floor(基础×1.05)] 闭区间 | L326-332 逐组断言；基础 = ch_phys+ch_elem（含 low 档倍率与防御系数，L305-307）；**抽样域偏离见 1.3** | ✅（附偏离） |
| PRP-5 不变量③ | crit_prob（cap 后）≤0.95；档位倍率 ∈ [1.3,2.35] | L399-400（≤95% 契约常数 + ≤参数 cap 双断言）；L412-414 倍率带（带界**由参数导出** L367-368，非硬编码，PRP-7 ✅）；幸运 0/幸运极高极端组 L375-380 + 定向断言 L416-424 | ✅ |
| PRP-6 随机源 | 一律经 seeded_rng() 注入，禁裸 random | 四个用例全部 `seeded_rng(offset=N)` 注入（L279/311/364/435）；全文件无裸 `random.random()/random.uniform()`（静态核对；`from random import Random` L37 仅类型标注） | ✅ |
| PRP-7 参数来源 | 公式参数经 FIX 读取器注入，不硬编码 | 唯一硬编码 = 契约断言带常数 `BAND_LO/HI=0.95/1.05`（L74-75，注释明确「契约断言常数，非 formula.json 参数」）与 `cap_max=95.0`（L366，注释同样明示）；符合 TC-5d-05（禁的是公式参数常量） | ✅ |
| PRP-8 确定性回归 | 同 seed 两次运行逐位一致 | `test_prp8_deterministic_regression`（L426-438）：`seeded_rng(offset=8)` 双实例各跑 300 组，`sig_a == sig_b`（L438）；`_collect_groups` 随机消费形状固定（`_draw_attrs` L105-120 固定调用序，guard 恒消费一次 L119 保证形状一致） | ✅ |

### 1.2 TC-PRP-01~05 对账

| 验收 | 判定 | 备注 |
|---|---|---|
| TC-PRP-01 载体与组数 | ✅ | 4 函数、三不变量各 1000；**口径歧义见 P2-5**（PRP-8 为 300 组） |
| TC-PRP-02 不变量① | ✅ | 含边界组（0 攻击/0 元素/0 体质 + rng 端点 0.9/1.1 每 50 组强制，L122-128） |
| TC-PRP-03 不变量② | ✅ | 闭区间断言 + 过滤逻辑（未命中/会心/格挡生效不入列，L320-321）；**断言强度见 P2-4** |
| TC-PRP-04 不变量③ | ✅ | 幸运极端组覆盖（【1a】§3-E L321） |
| TC-PRP-05 可复现与禁裸随机 | ✅ | 逐位一致断言 + 无裸随机（grep 静态核对 0 命中） |

### 1.3 PRP-4 偏离注记（重要审计点）

- D6 PRP-4 括号注「乱数 ∈ [0.9,1.1] 落在 [0.95,1.05] 内」在数学上不成立（0.9<0.95，[0.9,1.1] ⊄ [0.95,1.05]），契约前提自相矛盾、无法按字面实现。
- 实现选择（test_formula_property.py L21-27 头注记）：不变量②抽样域取断言带 [0.95,1.05]（闭端点每 100 组复现），另在 L334-351 补 rng 闭区间端点 0.9/1.1 显式边界组，按**真实带** [floor(基础×rng[0]), floor(基础×rng[1])] 断言（0.9/1.1 取自 `params.rng`，非硬编码）。
- **判定**：偏离本身工程上成立、理由充分、补偿完整（真实带 + 端点复现），未静默改语义——但注册位置不满足 D6 变更纪律，见 **P2-3**。

### 1.4 fixture 包 F-FIX 全段落位（维度①/③）

`tests/fixtures/packs/legal/formula.json` 27 键逐一对账 F-FIX-01~27 表（D6 L154-182）全部命中且值一致：base_attack_mult 1.0 / rng [0.9,1.1] / hit.k 1.0 / cap_min 10 / cap_max 95 / p_coef 0.5 / cap 95 / tiers 2.2·1.7·1.3 / tier_p [1,3] / crit_mult_up 0.05·0.10·0.15 / block 150·40·true·true / defense ratio·100·{blunt:0.2} / weakness 1.3·1.3 / type_affinity 全 5 键 / derived 1.5 / monster_def_rate 1.0 / elements 8 键。另保留 `damage_base`/`heal_rate` 两键（FIX-1 兼容要求）✅；附加键 `schema_version/floor_mode/deep_floor` 属 §3.4「dataclass 不装配」范围 ✅。**段缺省回退**（FIX §3.4）由 conftest 读取器 `_f()` 非 None 判定承接（conftest.py L127-129）✅。
- 注（不升级）：fixture `hit.k=1.0` 与【1a】§2.1 表 L236 的 0.2 不一致，但该差异系 2026-08-24 用户拍板 K=1 统一口径（damage.py L126-128 已登记），D6 F-FIX-03 表本身也按 1.0 定稿——三源一致，唯 D6 对【1a】L236 的引用行号不准确（应为「用户拍板」而非 1a 字段表），属引用瑕疵不入级。

### 1.5 validator 标量透传红拦语义（维度①核心问题）

- 路由：formula 模块 = `entry_type="map"` + `value_meta.type="formula"`（field_meta.py L454-460）→ `_check_module` L497-502 逐顶层键 → `_check_map_value`（validator.py L1479-1505）。
- 行为矩阵（静态核对）：
  - 字符串 → `_check_value` formula 分支（L1485-1486 → L1611-1620）：4KB 长度 + AST 黑名单 + new 表达式红拦 **保持不动** ✅（安全例外未被透传绕过）；
  - 含 `formula` 键的对象：字符串键值照常校验（L1489-1490）；非字符串 `formula` 键值 → R-5 formula_missing **保持**（L1491-1492）；
  - 无 `formula` 键的对象（段级参数容器 damage/hit/crit/...）→ 透传不红拦（FIX-1，L1493-1496）——注：此分支在改动前即静默放行，FIX-1 为注释登记而非语义变化；
  - **标量 int/float/bool → 新放行（FIX-2，L1501-1502）**——这是本批唯一行为变化；list/None/其它 → R-1 红拦保留（L1503-1504）。
- **判定：未破坏既有红拦语义**——①R-1~R-5 封闭清单（细化_3e §2.1）中，受影响者仅「formula 模块数值标量的 R-1 类型拦」一项，且为受控有界放松并带注释登记；②formula 安全例外（§3.3，不受只建议不限制覆盖）路径未触碰；③15 条段参数红黄校验（【1a】§2.1 L236-257：hit.k 0.05-1 红拦、cap 10-100 红拦、tiers 低<中<高、weakness ≤2.0 黄等）归实现层 T01，D6 §八「FIX-6 采纳登记」L367 已显式登记该依赖（"validator L1493-1496 已登记"），非静默悬空。
- 两个遗留缺口（见 P2-1、P2-2）：红拦边界**无测试锁定**；bool 放行与全库数字语义不一致。

---

## 二、代码质量（维度②）

### 2.1 不变量数学正确性（静态推导）

- **不变量①**：`channel_phys/elem = max(1, floor(raw))`（damage.py L470/L502）、`total_damage = max(1, floor(和×系数×rng))`（L548）→ 任一输入下 ≥1 恒成立；0 攻击 + 0 元素 + 0 体质时 raw=0 → 通道恰为 1（边界断言 L295-296 成立）；体质 0 → 防御系数 K/(0+K)=1.0 无除零（L397）✅。
- **不变量②**：`total = max(1, floor(base×rng))`（无格挡/无防御指令过滤后）；rng∈[0.95,1.05] 且 base≥2 ⇒ floor(base×0.95) ≤ floor(base×rng) ≤ floor(base×1.05)，且 max(1,·) 不破坏下界（1 ≥ floor(2×0.95)=1）→ 闭区间断言成立 ✅。端点组：rng=0.9 时 `max(1, floor(0.9base)) ≥ floor(0.9base)`、≤ floor(1.1base) 单调成立 ✅。float 精度（base≤~5.7e3，int() 截断=正数 floor）无边界误判风险 ✅。
- **不变量③**：`crit_prob` 经 cap 钳制 ≤95%（damage.py L289-292，cap=0 不限语义 L290）；幸运 0 → P=0.0 精确相等（L417，float 0+0 精确）；幸运 1e6 → P=5.0+slash≤5.05 → min(0.95,...)（L423-424 approx 精确）；`crit_roll` 倍率 ∈ [tiers.low+boost, tiers.high+boost(3)] ⊂ 参数导出带 [1.3, 2.35]（boost 封顶 L113-119）✅；`low_tier_min ≤ high_tier_max` 退化护栏（L369）✅。boundary 组（幸运 0 取非斩击类型 L381-385）保证 P=0 无 slash 加成，断言严谨 ✅。

### 2.2 边界组与护栏

- 未命中排除（【1a】§3-G 遗漏侧）— 属性随机 + `rng.random()>hr` 拒收（L153-154）✅；未命中不产生消耗下标错位（boundary 按迭代序收集，L259-260 注释）✅。
- 0 攻击/0 防御边界（D6 §1.3）— 每 100 迭代强制（L250-252），`assert boundary` 防循环结构回归（L294）✅；rng 端点 0.9/1.1 每 50 迭代强制（L124-127），i=0 处与边界组重叠（双端点复现）✅。
- 幸运极端组（D6 §1.3）— i%100==0 / ==50 强制（L375-380）✅。
- MAX_ITER=50000 拒收护栏（L70/L261/L323）：静态推断最坏情形——不变量②每迭代成功概率 ≥ 命中 10% × 非会心 ≥94% × 未格挡 ≥60% ≈ 5.6%（focus∈[10,600] 与 spd∈[1,60] 下命中率下界 10/70≈14.3% 优于 cap_min），1000 组期望迭代 ≈1.8 万 < 5 万，护栏留 2.7 倍余量；固定 seed 下确定非抖动 ✅。

### 2.3 断言强度（见 P2-4）

- 带内断言为契约闭区间（正确但弱于精确值）；端点组也仅断言宽带 [floor(0.9base), floor(1.1base)]，未断言精确 `total == floor(base×rng)`。静态推导：若 rng 乘区被整体删除（total=base），宽带断言**不报警**——不变量②的意图（乱数落在带内）仍能捕获越带，但无法捕获「乱数不生效」。建议端点组加精确等值断言。

### 2.4 性能上限（静态推断）

4 用例合计：不变量①~③各 1000 组 + PRP-8 600 组，单组迭代期望 1.8~10 次（最坏 5 万护栏）；单迭代 ≈14 次 `Random` 调用 + 一次全管线（约 20 次浮点乘）。总量 ≈ 3~6 万次管线求值，量级 <0.5s，无性能风险；pytest default 超时无压力 ✅。

### 2.5 标量透传宽容度（维度②）

- 宽容但**有界**：int/float 放行（monster_def_rate 数值型需要）、bool 放行（见 P2-2）、list/None/其它 R-1。
- 宽松点：数值标量不经 `_check_number`，负值/R-2/R-3(NaN)/Y-1~Y-4 全不适用——已由 T01 登记承接（D6 §八 L367），本批可接受。
- 安全边界：字符串路径不变，formula 安全例外（4KB/AST/new）仍生效，无黑名单绕过面 ✅。

---

## 三、遗漏与接缝（维度③）

- **TC-PRP 全覆盖** ✅：01~05 全部可静态对应到用例（1.2 表）。
- **validator R-1 接缝**：见 P2-1（无负例测试）、P2-2（bool 口径）。
- **FIX-8 验收承接**：TC-FIX-06（legal 包全绿）由 `test_pack_fixtures_matrix.py::test_smk08_legal_full_green`（L30-41，0 红 0 黄断言）间接承接——legal manifest 已声明 formula 模块（manifest.json L17），build_pack 全链路校验含段级参数容器与标量 ✅（无独立 TC-FIX-06 编号用例，属编号映射惯例，不入级）。
- **门禁接线**：`test_formula_property.py` 位于 tests/unit（pytest.ini testpaths=tests；run_all_tests.py L49 unit 段自动收录），无 verify 脚本显式引用（PRP-8 的 "--fast 抽样" 语义不依赖 verify 引用）✅。
- **无脏引用**：conftest 三 fixture 由路A 落盘且本文件消费处无本地遮蔽、无双源（头注 L29-31 属实；conftest.py L79-101/L194-202 核对一致）✅。

---

## 四、问题分级清单

| 级别 | 编号 | 位置 | 问题 | 修复建议 |
|---|---|---|---|---|
| P0 | — | — | 无 | — |
| P1 | — | — | 无 | — |
| P2 | P2-1 | validator.py L1493-1504；tests/unit/test_content.py L360-405 区块 | FIX-1/FIX-2 红拦边界（list→R-1 保留、int/float/bool→放行、无 formula 键容器→放行、`{"formula": 非字符串}`→R-5）**无任何正/负例测试锁定**，未来重构可静默把透传扩到字符串（即可绕过 formula 安全例外）而全量仍绿 | 在 test_content.py formula 安全区块补 `check_pack({"formula": {...}})` 边界用例：`{"x": [1]}`→R-1、`{"x": 1.0}`/`{"x": {"a":1}}`→绿、`{"x": {"formula": 123}}`→R-5；同时断言字符串路径黑名单仍红（防透传吞并） |
| P2 | P2-2 | validator.py L1501-1502 | bool 与 int/float 一并放行：与全库数字语义冲突（`_check_number` L1625-1628 明确 bool→R-1，`float(True)=1.0` 会在 FIX 读取器侧静默变真值）；当前 fixture 无顶层 bool（block.magic_ignores 在容器内走 FIX-1），纯冗余宽容 | 标量透传收窄为 `isinstance(value, (int, float)) and not isinstance(value, bool)`，bool 走 R-1（expect="number"）；或在注释与 D6 §八 显式登记 bool 宽容理由 |
| P2 | P2-3 | test_formula_property.py L21-27；D6 §八（L361-369） | PRP-4 偏离（抽样域改为断言带 [0.95,1.05] + 端点组补真实带）仅在测试文件头注记，**未登记 D6 §八 决策记录**——与 D6 变更纪律 L12「必须写入 §八」不合；本任务输入声称「§八（FIX-6 采纳/PRP-4 偏离注记）」与实际 D6 文件（仅 FIX-6 采纳 L367）不符 | D6 §八 追加「PRP-4 偏离登记（M6 批6B）】：偏离内容/理由（契约前提不成立）/补偿（端点显式组 + 真实带断言）/影响文档（test_formula_property.py L21-27）」；或审查正式确认接受文件级登记并在 §八 引用 |
| P2 | P2-4 | test_formula_property.py L334-351（端点组）、L326-332（带内组） | 端点组仅断言宽带 [floor(0.9base), floor(1.1base)]，未断言精确 `total == floor(base×rng)`：rng 乘区整体失效（total=base）时宽带断言全绿，无法区分「乱数生效但越带」与「乱数未生效」；带内组同理（契约带本身弱） | 端点组 rng 已知且 base 已知 → 追加精确等值断言 `group.total == max(1, int(base * endpoint))`（与生产同 float 运算序，静态可复现），锁「rng 应用 + 末位 floor 位置」；带内组保持契约带不动 |
| P2 | P2-5 | D6 L80（TC-PRP-01）vs test_formula_property.py L426-438 | TC-PRP-01 字面「**每函数**随机组 ≥1000」与 PRP-8 用例 300 组冲突；PRP-2 口吻（「三条不变量各覆盖 1000 组」）与 TC-PRP-01 不一致，静态核对口径存在被验收脚本字面误报的风险 | 二选一：PRP-8 提为 1000 组（成本 ~3.3 倍，仍 <0.5s）；或将 D6 TC-PRP-01 措辞对齐 PRP-2 改为「三条不变量各 ≥1000」 |
| P2 | P2-6 | validator.py L1498-1499 | 透传注释引用漂移：「D6 FIX-1/D6 §四」——段级参数落点是 D6 §三（FIX-1/F-FIX 表），§四 是 RTN 往返章节；应引用 §三 与 §3.4 | 注释改「D6 §三 FIX-1 / §3.4 边界异常」；顺带 L1493 的「（D6 FIX-8）」保留（校验归属）正确 |

---

## 五、无问题维度确认

- ✅ **1000 组不缩水**：三条不变量逐条静态核对均为 1000 组 + 组数断言（PRP-2/TC-PRP-01）。
- ✅ **随机源注入与确定性**：全文件无裸随机；所有 RNG 经 `seeded_rng(offset=N)`；固化消费形状。
- ✅ **参数经 FIX 读取器**：`formula_params` fixture 全用例注入；带界从参数导出（非硬编码）。
- ✅ **formula.json 全段落位**：F-FIX-01~27 全键落位、值一致、兼容键保留。
- ✅ **红拦语义主体**：R-1~R-5 封闭清单 + formula 安全例外未被透传破坏（除 P2-1/P2-2 两项边界口径）。
- ✅ **不变量数学正确性**：三条不变量静态推导均恒成立；边界组（0 攻击/0 体质/幸运 0/幸运 1e6/rng 端点）覆盖 D6 §1.3 全清单。
- ✅ **性能上限**：~6 万次管线求值上限，无超时风险；5 万迭代护栏有余量。
- ✅ **TC-PRP-01~05 验收映射**：全部落地（P2-5 口径歧义除外）。

---

## 六、审查门控结论

- **门控档位（j-space）**：full 档（唤醒 → 门控分级 → 接缝审计 → ship 注册）已完成。
- **结论**：P0=0 / P1=0 / **P2=6**。实现层数学正确、契约主体落地、红拦语义未被破坏（受控放松 + 登记）；6 条 P2 均为边界测试缺口、口径严谨性、文档登记类问题，无阻塞项——**可 ship，建议随批 6C 或 T01 批次消化 P2-1/P2-2**。