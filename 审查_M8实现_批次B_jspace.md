# 审查报告：M8 炼金实现 批次B（合成+继承+结算+宝石，5 文件）— j-space 静态审查

- 审查对象：`qbot_rpg/core/synthesis.py`、`upgrade.py`、`trait_inherit.py`、`alchemy_settle.py`、`gem_wallet.py`
- 参考：`docs/m8_contract_指令契约.md`（§1/§4/§5/§18/§10）、`docs/m8_contract_核心机制.md`、`docs/细化/细化_2c4a/2c4c/2c4e`
- 方法：**纯静态代码审查**。本环境无 bash 沙箱，未运行任何命令/脚本/测试；所有运行行为结论为「静态推导」，以源码对照契约规则得出，未经执行验证。
- 预算：480s 硬时限内完成；验证性 grep 8 次（≤15），read 定位抽查。
- j-space 门控：**full 档**（用户指定）——模块：`self-monitoring`（DONE-CHECK / ERROR TRAP / 校准）；接缝审计：5 文件全读 → 依赖签名核验 → 契约规则核对 → 报告落盘 → 终态自查。

---

## 结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | 0 | 未发现资金/物品重复发放、越权结算、崩溃级缺陷 |
| **P1** | 5 | 见下：继承增量双计数/丢选、结算丢超特性/负面、负面规则口径不一致、merge 职业门槛缺失、结算中途无进程内回滚 |
| **P2** | 10 | 边界/防御/死代码/契约依赖类 |

**总体判断**：5 文件工程补白标注完整、纯函数/零 IO/零 NoneBot 铁律执行到位、原子提交（synthesis/upgrade）与终态幂等（settle）骨架正确；主要问题集中在**跨模块/跨函数口径一致性**（结算↔继承、select 与写入快照的约定）与**门槛归属**（指令级门槛未在引擎内兜底）。

---

## P0（无）

未发现。全量扫描了扣款/入账/入包路径：synthesis 事务快照-回滚、upgrade 两段式+回滚、gem grant_gem 键空间硬前置，均无重复发放或越权扣减的静态证据。（静态推导）

---

## P1（5）

### P1-1　继承增量更新：select_traits 与 apply_to_snapshot 约定矛盾（二次 /继承 双计数或丢前选）
- 位置：`trait_inherit.py:456-498`（select_traits 位预算/PP）vs `trait_inherit.py:578-604`（apply_to_snapshot）
- 机制：`select_traits` 把 `prev_count = len(snap["traits"]) + len(snap["negatives"])`（L490-491）再叠 `len(chosen)`（L493）计为「本次使用」；而 `apply_to_snapshot` 是 **整体替换** `snap2["traits"] = list(traits)`（L580），非合并。
  - 若指令壳后续 /继承 传**全量累计列表**：prev_count 与 len(chosen) 重复计数 → 位预算虚高 → `slot_overflow` 误拒（如专家 3 位，已选 2 再加 1 → 2+3=5>3）。
  - 若指令壳传**仅新增项**：apply_to_snapshot 覆盖写 → 此前已选特性被丢（成品 traits 缺失）。
  - 测试（`test_trait_inherit.py:278-286`）中第二次 select 只传新增项、PP 先于位校验触发「PP 不足」而被掩蔽，未覆盖「PP 充足时增量新增」路径，故该矛盾未被测试暴露。
- 修复建议：统一约定——要么 `apply_to_snapshot` 改为合并（`union` 去重后写入），要么 `select_traits` 增加 `cumulative` 语义（传入含旧选的列表时先扣 prev 再计数）；并在指令壳/测试双侧固化「全量重选」或「增量追加」二选一。
- 置信：强（纯源码静态可证，无需运行）。

### P1-2　结算产出入包 traits 只读 snap["traits"]，超特性(gold_slot)/负面(negatives) 丢失
- 位置：`alchemy_settle.py:256-269`（`_snap_traits`）、`alchemy_settle.py:352-353`（`_produce` 用 `_snap_traits(snap)`）
- 机制：继承路径把超特性写入 `snap["gold_slot"]`（独占时，`trait_inherit.py:553`）、负面写入 `snap["negatives"]`（L554），**均不并入 snap["traits"]**；而 settle 的 `_snap_traits` 只读 `snap["traits"]`（dict 防御也只认 `ids|traits` 键）。结果：/确认 产出的 ItemInstance 不携带超特性与负面特性——与 INH-08「所选特性集随 /确认 写入成品 traits」、INH-12「负面效果生效」相悖。
- 同管线矛盾佐证：settle 调用的复核 `check_placement_conflict`（`trait_inherit.py:644-649`）聚合 **traits+negatives+gold_slot** 三处，与 `_snap_traits` 只取一处的口径不一致（复核看到全集、落包只写子集）。
- 修复建议：`_snap_traits` 增加 gold_slot/negatives 合并（或由批6A 壳层预合并）；同时将「产出 traits = 复核口径全集」写入契约与测试。
- 置信：强（纯静态）。**依赖批6A 壳层是否预合并——若已预合并则为 P2 文档性差异，建议在 settle 内显式兼容，勿依赖壳层记忆。**

### P1-3　负面特性：select_traits 不参与 group/repeatable，check_placement_conflict 计入 → 结算复核误拒合法选择
- 位置：`trait_inherit.py:503-544`（⑦⑧ 只遍历 `all_chosen`=普通+超，不含 negatives；工程补白 T-4 声明「负面不参与」）vs `trait_inherit.py:644-670`（check_placement_conflict 把 negatives 并入 ids，参与 group>1 与 repeatable>1 判定）
- 机制：若某负面特性与已选强力特性同 group，或与快照既有特性重复，select_traits 放行（合法 build 取舍），/确认 结算复核却报 `group`/`repeatable` 冲突 → 会话无法结算。INH-10/11 在两函数间行为不一致。
- 修复建议：统一口径——按 T-4 精神在 `check_placement_conflict` 中排除 negatives（或明确 negatives 也参与并回改 select_traits 预检），并在批6A 集成测试覆盖「负面与已选同组」用例。
- 置信：强（纯静态）。

### P1-4　upgrade 三种 merge 子类型的职业门槛未在引擎校验（规则级遗漏）
- 位置：`upgrade.py:699-705`（product_merge）、`737-801`（formula_merge）、`806-863`（trait_merge）
- 机制：指令契约明确门槛——`/成品合成` GU-30「炼金职业 ≥ 宗师」、`/配方合成` GU-40「专家」、`/特性合成` GU-41「宗师」（指令契约 L40/44/177；细化 2c4a CASC-07；2c4e TSC-15/INH-16「解锁=宗师」）。`upgrade.py` 三个执行器均**无 tier 门槛**（仅同批 `trait_inherit.py` 在引擎内校验了超特性/负面宗师门槛 TSC-11/INH-12，`trait_inherit.py:436-453`，形成明显不对称）。
  - 珠升阶「无职业硬门槛」系拍板③ 显式豁免，正确；但其余三实例的 GU 门槛完全依赖批7C 指令壳。
- 修复建议：在 `execute` 或各 `_exec_*` 前置注入 `job_tier_index` 门槛校验（宗师/专家），与 trait_inherit 引擎内门槛保持一致；若坚持壳层归属，请在 docstring 显式声明并加壳层测试锚点。
- 置信：中-强（门槛归属可能为指令级设计，静态推导提示接受风险；若批7C 已实现则降 P2）。

### P1-5　结算中途失败无进程内回滚：触媒/材料已扣、产出入包失败 → 副作用残留依赖壳层 repo.tx
- 位置：`alchemy_settle.py:511-536`（⑥ 触媒扣减 → 扣材料 → ⑦ 产出入包，任一步返回失败即 return，无 restore）
- 机制：`_consume_materials` / 触媒 `remove_item` / `_produce` 的 `add_item` 均为不可逆 hook 调用；若产出入包失败，已扣触媒+材料不回滚（引擎内零快照）。docstring 声明「存储与事务由壳层完成」、批6B 壳层用 repo.tx() 包裹——**若壳层事务非真原子（或引擎在壳层事务外被复用），材料即损失**。对比 synthesis（快照-回滚，`synthesis.py:583-615`）与 upgrade（快照-回滚，`upgrade.py:480-573`）均有进程内回滚，settle 是唯一无回滚的结算引擎。
- 修复建议：① 将触媒扣减移到扣材料之后、产出入包之前（先易失败后不易失败）；② 引擎内加进程内快照-回滚兜底（对齐 synthesis）；③ 或在契约中强制壳层 repo.tx 且增加「产出失败 → 壳层回滚」集成测试。
- 置信：中（原子性归属按设计在壳层；风险路径真实存在）。

---

## P2（10）

- **P2-1　珠升阶禁跳级在边界静默失效**：`upgrade.py:647-657`。① in/out 档位任一无法解析（items 无 quality/tier、无 jewel_tier）→ 整段校验跳过（U-J1「数据直通」）；② top-tier（legendary）`index_to_tier(tier_index+1)` 被 `quality.py:213-223` 钳回 legendary → `out_tier==expected` 判定通过，3×legendary→legendary 视为「合法 +1」。建议：档位信息不全时保守拒绝而非直通；明确 top-tier 合并应拒绝（无更高阶）。静态推导。
- **P2-2　见习分解仍发宝石**：`gem_wallet.py:482-488`。`decompose_rate(0)=0.0`（L187-188）但 `_gem_amount` flat 公式 `base*n`（L233）不乘 rate → 见习可分解可分解物并获宝石（GW-6 门槛归壳层、GW-11 声明低阶门控不实现）。建议：rate==0 时 gem 恒 0（或返回 `decompose_denied`），作为引擎侧防泄漏兜底。静态推导。
- **P2-3　合成候选职业未显式过滤「制造/资源」**：`synthesis.py:368-382`。遍历整个 proficiency 桶而不验职业类别（工程补白 3 声明由装配层保证不掺战斗职业）；若装配层失守，战斗职业等级可越权合成。建议引擎内按职业类别过滤。静态推导。
- **P2-4　负面引用失效：门槛已按配置预判、附加被静默丢弃**：`trait_inherit.py:439-453, 492`。`_negative_of` 按配置判出 neg → 先判宗师门槛 → 再 `_resolve_negatives` 丢弃不可解析项（STO-05）；不可解析的负面仍消耗「负面需宗师」判定（过度拦截）。建议先解析后判门槛。静态推导。
- **P2-5　特性落位对 tuple target 不一致**：`upgrade.py:925-937`（`_placement_conflict` 接受 list/tuple）vs `upgrade.py:531`（`_commit` 仅 `isinstance(target, list)` 才落位）。target 为 tuple 时互斥校验执行但消耗不生效。建议统一 list 或显式拒绝 tuple。静态推导。
- **P2-6　gem 货币键空间仅支持 list 形态**：`gem_wallet.py:493-506`。`settings.currencies` 为 dict 形态时回落默认空间（coins/diamond）→ `grant_gem` 恒 `unknown_currency` 误拒。建议兼容 dict 形态。静态推导。
- **P2-7　settle_key 死代码**：`alchemy_settle.py:398-404`。`settle_key()` 未被 confirm/abandon 使用（两处直接传 `SETTLE_CONFIRM/ABANDON` 常量给 `settle_alchemy`）。若壳层未复用则删除或改为唯一落键点。静态推导。
- **P2-8　幂等键(message_id)依赖壳层**：5 引擎中仅 settle 通过 `session_mgr.settle_alchemy` 承接 message_id 幂等（`alchemy_settle.py:451-465`）；synthesis/upgrade 仅返回 `idempotent: False`/`already` 标志（`synthesis.py:652`、`upgrade.py:773-778`），不写幂等键。ATO-04/TC-34 的 idem_claim 落在 session_mgr/壳层——若壳层漏接 message_id，存在重放风险。建议在指令壳测试中固化 message_id 链路。静态推导（分工符合设计，仅为接缝提示）。
- **P2-9　upgrade._as_int 不支持 float**：`upgrade.py:114-125`（synthesis/gem 版本均支持 float 整数归一）；配置里 `count: 3.0`/`gem: 10.0` 会被兜底，与同仓不一致。建议对齐。
- **P2-10　合成最高职业排序依赖 proficiency 桶 level 键名**：`synthesis.py:369-373` 用 `node.get("level")`；若桶节点用档位索引其他键名，排序/提示文案失真（资格判定走 prof 引擎不受影响）。建议与 proficiency.py 存档口径核对键名。静态推导。

---

## 无问题维度确认（关键验收点已实现 + 点名疑缺项已实现清单）

以下为逐条静态核对（源码含出处标注），未发现问题：

- **合成 GU-01~04**：mode≠off（`synthesis.py:347-350`）；配方存在（resolve_recipe，L351-355）；任一职业达标取最高（L362-382）；synth_allowed 缺省=not master_only、深度提示不阻断（L383-392）；**原子校验全量差额+差异文案**（`_material_shortfall`/`_format_shortfall`，L400-447）；**快照-回滚单事务**（L583-615）；**熟练=配方等级×成品数×倍率**（L617-623）；图鉴回调 on_codex（L625-630）；不耗能量（全程无能量读写）。
- **升级 4 实例**：珠 3×同档同 ID+宝石10→+1 阶禁跳级（`upgrade.py:626-678`，档位联动+禁跳级校验存在，边界见 P2-1）；配方合成已解锁幂等「不重复扣宝石」（L770-778）；特性合成同系判定+group 互斥落位复核（L806-863、L865-937）；成品合成原子提交（L699-732）；进程内两段式提交+回滚（L461-573）。
- **继承 INH-01~15**：候选池来源（`trait_inherit.py:356-434`）；位预算 正式1/精通2/专家3+SP 叠加、总上限 6、见习硬门槛（L274-297）；PP 预算会话累计（L455-473）；互斥组（L503-530）；repeatable（L533-544）；负面特性宗师门槛+同源映射+占位不耗 PP（L325-353、L439-453）；超特性第 4 位独占+宗师门槛（L419-453、L499-501）；写入快照 version 递增（L562-604）；结算复核（L623-674）。
- **结算 F-05 9 步**：终态幂等 gate 前置（`alchemy_settle.py:449-465`）→ 全量复核（L467-475）→ 品质聚合均值（L480-481）→ 上限叠加 SP×10+核心/挑战，≤100（L483-487、L198-223）→ 刻度降级最低普通封底不吞材料（L489-503）→ 档位系数只放大数值（L505-508、L308-319）→ 触媒消耗同事务（L510-527）→ 产出入包 quality=tier+traits（L533-536）→ 熟练=配方等级×1（L538-539）。**/放弃 材料不结算**（L557-594，零背包改写）。
- **宝石 GEM-15**：分解两段式（材料×回收率向下取整 `_recover_materials` L309-326 + 宝石行 `_compose_result` L380-420）；宝石平铺基础值 普通1/精良3/史诗8/传说20 不乘回收率（默认 flat，L202-217、L227-233）；标准版拒绝（`is_decomposable` L259-268）+ 回收减半可配（L466-470）；grant_gem 统一入账+键空间硬前置（L508-533）。

**点名疑缺项已实现确认**：合成图鉴（on_codex）✓；深度提示不阻断（CASC-04）✓；数量上限 advisory 截断 ✓；SP 品质上限/特性位解锁计数 ✓；负面同源映射（traits.json negative 字段优先 + settings 映射）✓；终态幂等 settle_alchemy ✓；材料不结算（/放弃）✓；GEM-03 键空间硬前置 ✓；DEC-04 低阶门控为内容包可配（GW-11 显式声明不实现）✓；拍板③ 珠升阶无职业硬门槛 ✓。

---

## 规则级覆盖核对（③：2c4a/2c4c/2c4e 遗漏）

- **2c4a（LAY-01~06 / CASC-01~10 / JOB-01~06）**：合成层规则 LAY-01/04a/05/06、CASC-01/02/04、JOB-03/04 已覆盖；CASC-03/05/06（深度必须经炼金层达标、进化计数防跳、王称号=图鉴全点亮）为合成层边界正确未越权（合成仅 on_codex 小加成、不计进化），无越权；**CASC-07 指令门槛中 /成品合成 /特性合成=宗师、/配方合成=专家 未在 upgrade 引擎内落地 → P1-4**。
- **2c4c（DEC-01~05）**：DEC-01（见习无分解，rate=0）✓ 但 gem 泄漏见 P2-2；DEC-02/03/04/05 ✓。
- **2c4e（QLT-01~13 / TSC-01~18 / INH-01~16）**：QLT-01~13 由 quality.py+settle 覆盖（QLT-09 加成道具属批8A /加成，非本批缺陷，settle 无接入点=预留）；TSC-01~14 ✓；**TSC-15/INH-16「特性合成解锁=宗师」未落地 → P1-4**；INH-01~16 ✓（INH-10/11 负面口径不一致 → P1-3；INH-08 成品写 traits 丢 gold/negative → P1-2）。
- **TC 矩阵**：抽查 `test_trait_inherit.py`（TC-12~15/18~20 有对应用例）；synthesis/settle/gem/upgrade 的 TC-01/02/07/08/09/15/16/23、TC-02/03/05/08/09/15/20、TC-19~22 以 docstring 与测试文件存在为据，**未逐条执行核对**（静态审查边界内）；建议 CI 全量跑通后再作 TC 覆盖结论。

---

## 静态推导局限声明

本报告全部结论基于源码阅读与契约文档交叉比对，**未执行任何运行验证**。以下判定依赖未读入的外部壳层（批5/批6A/批6B/批7C 指令壳与 session_mgr 语义），已逐一标注「静态推导」：P1-2 的 gold_slot 预合并、P1-4 的门槛归属、P1-5 的壳层事务原子性、P2-2 的见习门槛、P2-8 的 message_id 链路。若对应壳层已实现，相关条目应降级。
