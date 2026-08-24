# 审查报告：M0 复查批3-路1 · 玩家属性三层管线（qbot_rpg/core/player_attributes.py）

> 审查日期：2026-08-24 · 类型：静态代码审查（**本环境无 bash 沙箱且任务禁止运行命令，未执行任何脚本/测试**）
> 对象：`qbot_rpg/core/player_attributes.py`（374 行，任务预估「约 350 行」属估算误差，不影响结论）
> 基准：`细化_3b_玩家属性三层.md`（§1 三层 / §2 管线五步 / §3 条件加成三重锁 / §4 stats.json 字段 / §5 派生属性 / §6 TC-01~18）＋ `细化_3a_架构分层契约.md`（§3 领域类型）
> 关联交叉核对：`data/player.py`、`data/types.py`、`core/damage.py`、`core/battle.py`、`content/validator.py`、`content/field_meta.py`、`tests/unit/test_core.py`、`tests/unit/test_coredata_regress.py`
> 核验边界：**《玩家属性方案定稿.md》原文不在本仓库**——所有「Lxx」行号引用只能与 3b §8 自带行号回查表比对，无法逐条回查定稿原文；所有行为/数值结论均为**「静态推导」**（按源码逐行演算）。

---

## 1. 结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 规格内正常流程无崩溃、无错误结果、无数据损坏（静态推导） |
| **P1** | **2** | 命中率 K 跨文档口径冲突未登记；派生属性双套同名异构实现、本文件派生函数生产零消费 |
| **P2** | **11** | 边界健壮性 / 双入口行为不一致 / 重复实现 / 注释与行号真实性问题 |

**无问题维度已确认**：三层结构（§1）、管线五步顺序（§2）、百分比只乘一次、条件加成三重锁、取整时机唯一（ADR-04）、resource 型默认不吃百分比（ADR-02）、九预置键（§4.2）、零 NoneBot import（3a R1）、PlayerAttributes 唯一落点 data/（3a D-03）、类型标注基本完整（3a §3.1）。详见 §5。

---

## 2. ① 错误（bug / 边界 / 叠加规则 / 派生计算）

### 2.1 确认通过（静态推导，逐条演算）

- **管线五步顺序正确**：`_pipestep`（L143-150）＝白值+flat → 基础合计 → ×(1+加成pct) → ×(1+临时pct) → +条件+临时flat。TC-01（26）、TC-02（26）、TC-03（29）、TC-07（19）、TC-08（30）、TC-09（33）、TC-11（9）逐条演算全部一致；出口唯一 `int(math.floor(...))`（L203/L271，ADR-04）。
- **百分比只乘一次**：加成 pct 只乘基础合计（L145），临时 pct 只乘加成后属性（L146），各自不递归；同层合并是调用方职责（单值入参，物理上不可能叠乘）✓。
- **条件加成三重锁**：触发基准＝基础合计（白值+flat，L192/L244-246），产出在最后一步纯加法（L150/L150），永不进乘算基准 ✓（TC-04/TC-09/TC-10）。
- **环检测算法正确**：DFS 三色（L102-122）对 A→B→A 与 X→X 自环均抛 `ConditionalRuleCycleError`，`path.index` 与 GRAY 语义一致，无漏判（静态推导）✓（TC-05）。
- **resource 默认不吃百分比**：`apply_pct=False` 整体跳过两步 pct（L147-149），hp=100 → 100 ✓（TC-18）；`resource_pct=True` 可开启（L260）。
- **派生公式数值与 3b §5.1-5.4 一致**：crit_rate（√幸运×0.5%+bonus，cap 0=不限）✓、crit_roll 三档边界（≤P 高 / ≤3P 中 / 其余低）✓、hit_rate 特例先于 clamp ✓、block_rate cap 40% ✓、phys/mag/elem 除算 ✓（TC-12~16）。

### 2.2 P1 错误

**P1-1　命中率 K 跨文档口径冲突（3b §5.2 K=1 vs 1a 数值层 K_hit=0.2），生产路径取 0.2，冲突未登记 ADR**
- 位置：本文件 `hit_rate` L326-342（k 默认 1.0）；对照 3b §5.2「K 可配，默认 1（L82）」；`core/damage.py` L333-357 的 `hit_rate`（k=0.2，docstring 明言「K_hit 战斗口径默认 0.2（数值层 L21；区别于 3b 派生属性 hit.k=1——本模块为 1a 权威口径）」）；`core/battle.py` L1256 实际调用 damage 版。
- 问题：同一命中率概念在 3b（本文件口径，K=1）与 1a（生产口径，K=0.2）给出**不同结果**；两套细化文档冲突，仅以 damage.py 代码注释形式声明「1a 权威」，**未写入 3b §0.3 ADR，也未在 3b §5.2 登记该冲突**。任何按 3b 使用 `player_attributes.hit_rate` 的调用方都会与战斗结算命中率不一致（如 focus=10、敌敏=100：K=1 → 9.1%；K=0.2 → 33.3%）。
- 修复建议：在 3b §0.3 增加 ADR（或 §5.2 明确「战斗命中 K_hit=0.2 覆盖派生口径 K=1」）；二者择一为唯一权威并在另一侧加交叉引用；`hit_rate` 的 k 默认值按仲裁结果对齐，避免同名函数不同结果。

**P1-2　派生属性「同名异构」双套实现 + 本文件派生函数生产零消费**
- 位置：本文件 L279-374（crit_rate/crit_roll/hit_rate/block_rate/phys_reduce/mag_reduce/elem_reduce）对照 `core/damage.py` L265-288（crit_prob）、L291-326（crit_roll）、L333-357（hit_rate）、L364-374（block_rate）。
- 问题：
  1. `crit_roll` 同名不同签名/返回：本文件 `crit_roll(final_luck, random_roll, super_crit_level) -> float`（返回倍率 2.2）；damage 版 `crit_roll(r, lck, *, p_coef=0.5, tiers, tier_p, ...) -> Tuple[str, float]`（返回(档位, 倍率)）。两模块同名函数无法互换。
  2. `hit_rate` 同名不同单位与 K：本文件返回百分数（10.0=10%）、K=1；damage 版返回小数（0.10）、K=0.2。
  3. `block_rate` 同名不同形态：本文件 `(final_focus)` 固定 150/cap40 返回 %；damage 版 `(foc, *, k=150, cap=40)` 返回小数。
  4. `battle.py` L66-74 实际 import damage 版 → **本文件全部 7 个派生函数在战斗中零消费**，仅 test_core.py（6/7）与 formula_engine.py（crit_rate 一处）引用；`mag_reduce`（L362-365）**零消费且零测试**。
  5. damage.py L18-21 已以工程补白形式声明「本模块独立实现参数化版本，不修改 core/player_attributes.py」——补白诚实，但 3b §5/ADR-03「派生属性统一口径、只读」的契约被拆成两套实现。
- 修复建议：合并为一处权威实现（建议 damage 版承担战斗/数值权威、本文件作为 3b 派生语义薄封装并显式委托，或反之）；消除同名异构（至少 rename 或统一签名/返回单位）；补 `mag_reduce` 测试；在 3b §5 登记「派生属性实现落点＝core/player_attributes.py（3b 口径）＋core/damage.py（1a 战斗口径）」的接缝说明。

### 2.3 P2 错误（边界 / 健壮性）

**P2-1　负数兜底行为双入口不一致（TC-17「运行期按 0」在 calc_all 主入口不成立）**
- 位置：`calc_final_attr` L183-191（base/growth/free_points<0 → 按 0 兜底，P1-4 测试钉死）；`calc_all_final_attributes` L231-246（base/flat 直接取值，**无任何负数钳制**）。
- 影响：stats.json base/growth 负数属「黄提示可加载」（field_meta.py L68-70 allow_negative=True；TC-17），若 4a 白值工厂不自行钳制，负白值会经 calc_all 代入管线放大，与 calc_final_attr 结果分叉。
- 修复建议：把负数钳制抽为共享 helper，calc_all 对 base_map 负值同样按 0；并在接线前用「base=-5 全链」用例钉住两入口一致。

**P2-2　派生函数对负输入无保护（除零 / 负百分比）**
- 位置：`elem_reduce` L374（elem_res=-100 → 0/0 ZeroDivisionError）、`phys_reduce` L359 / `mag_reduce` L365（-100 → 0/0）、`block_rate` L351（focus=-150 → 0/0；focus=-50 → 返回 -50% 负格挡率）、`hit_rate` L341（final_focus=-k×敌敏 → 0/0）、`crit_rate` L294（负 crit_bonus → 负会心率）。
- 影响：派生属性输入＝最终属性（ADR-03），而最终属性可因允许加载的负 base/growth 或潜在负词条为负；对照 damage 版同函数均做了 `x<0 → 0` 钳制（L354-355/L372-373/L390-391），本文件缺。属可达性低但真实存在的健壮性缺口。
- 修复建议：各派生函数入口 `final_* = max(0.0, x)`（与 damage 版对齐）；`hit_rate` 增加分母==0 兜底。

**P2-3　条件加成产出键未并入 keys → 规则目标键不在任何层 dict 时产出静默丢弃**
- 位置：`calc_all_final_attributes` L238-241（keys＝各层 dict 键并集）vs L249-253（cond_out 按规则计算，目标键未并入 keys）。
- 影响：若规则 target 是「各层 dict 均无条目」的注册属性（如工厂只存非零白值、base 为 0 的自定义属性），该属性的条件产出不会进入 result，静默丢失。正常九键下不触发，属防御缺失。
- 修复建议：keys 并集追加 `cond_out.keys()`（在条件分支后）。

**P2-4　白值公式双口径 + 「白值工厂」缺失**
- 位置：`calc_final_attr` L182 用 `base + growth×(level−1) + free_points`（对齐 §2.1/TC-06）；`calc_all_final_attributes` L261 注释引用「§4.4：base=base+growth×lv+加点」并把 base 当**外部工厂已算好的白值**，本文件不计算白值。
- 问题：① 3b 基准自身矛盾——§2.1 伪代码 L94 写 ×(lv−1)、TC-06 用 ×49(lv=50) 验证 ×(lv−1)、而 §4.4 L228 注释写 ×lv；代码随 TC-06/§2.1，但 calc_all 注释引用了 ×lv 口径。② 该「白值工厂」在本仓库不存在/未定位（panel_render.py L80 走「加成已含于存档 base」的 M0 简化口径，不调用 calc_all）——calc_all 前置契约悬空。
- 修复建议：上报基准修正 §4.4 注释为 ×(lv−1)；定位/定义白值工厂并给 calc_all 增加前置校验或显式 white 入参。

**P2-5　crit_roll 超会心等级无上界钳制**
- 位置：L318 `boost = 0.05 * max(0, int(super_crit_level))`——只拦负、不拦上界；3b §5.1 超会心为 Lv1-3 语义。传 Lv10 → 倍率 2.7/2.2/1.8，超出矩阵。
- 修复建议：`min(3, max(0, int(...)))`（或在注释声明依赖效果系统保证 Lv1-3）。

（低危备注：`hit_rate` L339 对「敌敏 ≤ 0」一律返回 100%，含负敌敏——3b 仅定义 =0 场景，负敌敏语义未定义，依赖校验兜底即可。）

---

## 3. ② 缺漏（细化/定稿要求未实现、定义零消费）

**P2-6　环检测双份实现，core 版运行时防线无生产触发**
- 位置：`validate_conditional_rules` L80-122 vs `content/validator.py` `_graph_has_cycle` L375-395（两套独立 DFS 三色，算法等价）。
- 现状：注册表成员校验（R-4）已在 validator `_check_conditional`（L343-373）落实并有测试；但 core 版仅被**无任何生产调用方**的 `calc_all_final_attributes`（L225）触发——「加载期红拦 + 运行时防线」中运行时防线目前是死代码。
- 修复建议：calc_all 接线后自动激活；或 validator 改为复用 core 版，避免双份维护。

**P2-7　AttrID 别名 import 零消费（死代码）**
- 位置：L33 `from qbot_rpg.data.types import StatKey as AttrID`——全文件无 AttrID 使用（所有参数为 `attr_id: str`）。
- 修复建议：删除，或改用于参数/返回值标注（对齐 3a §3.1 类型约束）。

**P2-8　ConditionalRule 定义位置与 3a U2 的边界（低危观察）**
- 位置：L64-77。ConditionalRule 镜像 conditional.json 配置结构，按 3a §3.3 U2「配置类型（Def 系）落 content/」应归 content/；当前唯一定义在 core。运行时被 core 消费，可接受，但建议在 3b/3a 显式登记例外或迁至 content/。
- 注：`ConditionalRule.rule_id` 在计算管线零消费（仅 validator 校验 id 唯一，L359-364），属设计如此，字段 docstring 已注明「可选/注册表约束」，非缺漏。

**观察项（确认非缺漏）**
- **逃跑成功率（§5.4 派生项）不在本文件**：3b §5.4 将「逃跑成功率=最终敏捷/(最终敏捷+敌敏捷)（L185）」列为派生项；本文件未实现，但 `core/battle.py` `_flee_actor`（L1088-1094）已按敏捷比公式实现 → 属合理拆分。建议在 3b §5.4 或本文件头注明实现落点，避免派生属性清单看起来不完整。
- **resource_pct 配置落点未登记**：ADR-02 声明「可配扩展默认关闭」，代码以 calc_all 的 `resource_pct` 参数承接，但 3b §4.3「相邻可配项」表未登记该配置键/JSON 落点——接缝待定，建议在 3b 补登记。

---

## 4. ③ 幻觉 / 注释引用真实性

**H1（P2）　crit_roll docstring 行号「L66」误挂**
- 位置：L312「超会心 Lv1-3 各档 +0.05×等级（效果系统 crit_mult_up 提供，L66）」。
- 冲突：3b §8 行号回查表及 §5.1 正文把 **L66 对应「负会心 ×0.75：可选，怪物配置」**；超会心矩阵依据为 L49-63/L60-63，3b 未给 crit_mult_up 挂 L66。相对 3b 自带映射即冲突（定稿原文不在仓库，无法最终核验）。
- 修复建议：改引用「3b §5.1 超会心矩阵（L49-63/L60-63）」，删除 L66。

**H2（P2 低危）　crit_rate docstring「√√」双根号笔误**
- 位置：L286 `formula = min(cap, √√最终幸运 × 0.5 + crit_bonus)`——实现为单次 `math.sqrt`（L294），注释符号与实现不符。
- 修复建议：删一个根号。

**H3（P2 低危）　`_pipestep` docstring 层编号 ③ 错位**
- 位置：L136-139 写「①基础合计 / ②加成后 / ④战斗临时 / **③最终属性**」——把「③」贴在最终属性上；而 3b §2 原文 ③＝条件加成（L148），最终属性是 ④+③ 的合成（L150 未编号）。编号错位易误导。
- 修复建议：最终属性不编号，③ 留给条件加成。

**确认真实/无冒充（静态核对）**
- 其余行号引用与 3b 引用表一致：L7-12（L41-45/L49-63/L81-85/L90-92/L20,L32/L21,L31/L126-127）、L51-53（§4.2 九键）、L89/TC-10、L184/TC-17、L220-221/ADR-05、L290/TC-12 等均一致 ✓。
- 工程补白标注真实：L349 把「当回合格挡率减半 / 1v1 单次不消费」标注为战斗状态机职责（见细化_1g/M1）而非本文件冒充 ✓；damage.py 的「独立实现」声明诚实 ✓。
- 模块头对 3a 的引用（R1/D-03/§3.1）属实：零 nonebot import、类型标注完整、PlayerAttributes 仅 import 不重复定义 ✓。
- **核验边界**：定稿原文不在仓库，上述行号真实性结论止于「与 3b 自带回查表一致」，无法逐条回查定稿——建议将定稿文件纳入仓库以支撑「可逐条回查」承诺。

---

## 5. ④ 确认无问题维度（对照基准逐项）

| 维度 | 基准要求 | 结论（静态推导） |
|---|---|---|
| 三层结构 §1 | 白值/加成(flat+pct)/临时(pct+flat)/cond 四桶 | PlayerAttributes 字段一一对应（data/player.py L34-37），_pipestep 消费全部四桶 ✓ |
| 管线五步 §2 | 白值→基础合计→加成后→临时→最终，顺序写死 | L143-150 顺序正确，不可配 ✓ |
| 百分比只乘一次 | 加成 pct 乘基础合计、临时 pct 乘加成后、不递归 | L145-146 ✓（TC-02/TC-08） |
| 条件加成三重锁 | 基准锁/自引用锁/终值锁 | L102-122 + L192 + L150 ✓（TC-04/05/09/10） |
| stats.json 键空间 | 九预置 hp/mp=resource + 7 combat | L50-53 ✓；attr_types 缺省映射 ✓ |
| 取整时机唯一 | 仅出口 floor（ADR-04） | L203/L271 ✓（TC-01/TC-17） |
| resource 默认不吃 pct | ADR-02 / TC-18 | L147-149 + L260 ✓ |
| 派生属性只读不回写 | ADR-03 | 7 个纯函数无副作用 ✓（实现落点问题见 P1-2） |
| 零 NoneBot（3a R1） | core 不 import nonebot | import 仅 math/dataclasses/typing/data.* ✓ |
| 依赖方向（3a R3） | core → data 单向 | 仅依赖 qbot_rpg.data ✓ 无环 ✓ |
| 领域类型唯一落点（3a D-03） | PlayerAttributes 仅在 data/ | 本文件仅 import ✓（ConditionalRule 见 P2-8） |
| 类型标注（3a §3.1） | 公开函数完整标注 | 全部公开函数含参数与返回标注 ✓（AttrID 死代码见 P2-7） |
| 验收用例 | TC-01~18 | 数值逐条演算一致；但 calc_all_final_attributes 与 validate_conditional_rules 无测试（见 P1-2/P2-6） |

---

## 6. 修复建议汇总（按优先级）

**P1（2 条）**
1. 命中率 K 口径：在 3b §0.3 登记 ADR（或 §5.2 明确「战斗命中 K_hit=0.2 覆盖派生 K=1」），统一唯一权威并双向交叉引用；对齐 `hit_rate` 默认 K。（L326-342 / damage.py L337/L349 / battle.py L1256）
2. 派生属性合并：消除 crit_roll/hit_rate/block_rate 同名异构（统一签名与返回单位），确定唯一权威实现并委托；补 `mag_reduce` 测试；3b §5 登记双落点接缝。（L279-374 / damage.py L265-374 / battle.py L66-74）

**P2（11 条）**
3. 负数兜底抽共享 helper，calc_all 与 calc_final_attr 对齐（TC-17/P1-4）。（L183-191 vs L231-246）
4. 派生函数入口负输入钳 0、修除零。（L339-374）
5. keys 并入 cond_out.keys()，防条件产出静默丢失。（L238-253）
6. 上报基准修正 §4.4「×lv」→「×(lv−1)」；定位/定义白值工厂。（L182/L261）
7. crit_roll 超会心等级上界钳 3。（L318）
8. 环检测去重：validator 复用 core 版或 calc_all 接线激活运行时防线。（L102-122 / validator L375-395）
9. 删 AttrID 死 import 或用于标注。（L33）
10. ConditionalRule 位置按 U2 迁 content/ 或登记例外。（L64-77）
11. 修正 H1「L66」行号误挂。（L312）
12. 修正 H2「√√」笔误。（L286）
13. 修正 H3「③」编号错位。（L136-139）
14. （观察）3b §5.4 注明逃跑成功率的 battle.py 落点；3b §4.3 登记 resource_pct 配置键。

---

## 7. 附：结论复述

- **P0 = 0，P1 = 2，P2 = 11**（均静态推导，未运行任何命令）。
- **Top 3**：① 命中率 K 跨文档冲突（3b=1 vs 1a=0.2，生产取 0.2，未登记 ADR）；② 派生属性同名异构双实现（battle 用 damage 版，本文件派生函数生产零消费、mag_reduce 零测试）；③ 双入口负数兜底不一致 + 派生函数负输入除零/负百分比等边界缺口。
- 基准行号引用除 L66 误挂外与 3b 回查表一致；定稿原文不在仓库，行号最终核验受限。
