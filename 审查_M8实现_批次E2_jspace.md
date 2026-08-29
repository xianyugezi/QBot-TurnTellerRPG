# 审查报告 · M8 炼金实现 批次E2（指令壳·扩展指令段）· j-space 门控 full

> 审查对象：`qbot_rpg/commands/alchemy_commands.py`（3457 行）本批功能段——
> cmd_synthesis(728) / cmd_mount(1766) / cmd_unmount(1791) / cmd_jewel_up(1818) /
> cmd_product_merge(1843) / cmd_formula_merge(1872) / cmd_trait_merge(1908) /
> cmd_register(1938) / cmd_copy(1964) / cmd_deep(2304) / cmd_evolve(2381) /
> cmd_core(2410) / cmd_buff(2446) / cmd_challenge(2482) / cmd_skill_panel(2595) /
> cmd_tutorial(2624) / cmd_instant(2760) / cmd_plant(2918) / cmd_harvest(2945) /
> cmd_helper(2968) / cmd_collect(3008) / cmd_assist(3029) / register_alchemy_commands(3215)。
> 参考：docs/m8_contract_指令契约.md、docs/m8_contract_战斗资源.md、docs/细化/细化_2c4d_炼金指令表.md。
> 方法：静态代码审查（本环境无 bash 沙箱，未运行任何验证；运行行为结论均标「静态推导」）。
> grep 用次 7/15（预算内），精读行数约 1500。

---

## 〇、结论摘要

| 等级 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 1 |
| P2 | 7 |

- **P1（1）**：`cmd_instant` 能量先扣后校验 → 失败路径非零副作用（违背 ATO-01）。
- **P2（7）**：/协力 同群校验 fail-open；/挑战 目标配方与深会话配方一致性二义；/镶核心·/加成·/进化 壳层未显式前置职业守卫（依赖引擎，本文件不可验证）；「雇工→代工」拍板未同步契约文档；复制 数量接线未进 DEFAULT_QUANTITY_COMMANDS + parsers DEFAULT_MAX_QTY=99 与拍板⑤ 不符（均批11 依赖）；/拆珠 槽位 0/负值透传；门槛判定「直接比 level」与「经 tier_index_for_level」两种口径并存。

无问题维度确认见 §三；逐条发现见 §二。

---

## 一、定稿落地逐条核对（关键验收点）

| 验收点 | 结论 | 位置 | 备注 |
|---|---|---|---|
| /合成 跨职业 | ✅ | cmd_synthesis 728-745 | 门槛/原子/文案全委托引擎，透传「合成 ✅/❌」与缺料差异（静态推导：引擎承载 GU-01~04） |
| /珠升阶 无职业硬门槛（拍板③） | ✅ | cmd_jewel_up 1818-1840 | 无任何职业判断；3×同档同 ID + 宝石10 由 UpgradeEngine 承载 |
| /成品合成 宗师 | ✅ | 1856 | `_prof_level < _GRANDMASTER_TIER_INDEX(5)` 拒绝 |
| /配方合成 专家 | ✅ | 1887 | `EXPERT_TIER_INDEX(3)`；已学检查 1895-1899（GU-38） |
| /特性合成 宗师 | ✅ | 1922 | `_GRANDMASTER_TIER_INDEX(5)` |
| /登记 /复制 大师 | ✅ | 登记 1950-1954（tier_index_for_level ≥ 4）；复制 1979 | 两指令门槛一致（语义等价，见 P2-7） |
| /深度炼金 大师 | ✅ | 2332-2335 | DeepEngine.deep_eligible（master_only + 档位≥4） |
| /进化 宗师 | ⚠️ 壳层依赖引擎 | 2402-2406 | 壳层无显式 `_prof_level` 门槛，委托 evolve_unlock（见 P2-3） |
| /镶核心 大师+会话中 | ⚠️ 壳层依赖引擎 | 2431-2443 | 会话前置在壳（GU-26），大师门槛委托 mount_core（见 P2-3） |
| /加成 宗师 限1次 | ⚠️ 壳层依赖引擎 | 2467-2479 | 会话前置在壳，宗师+限次委托 buff（见 P2-3） |
| /挑战 宗师+材料×2 | ✅ | 2502（宗师）2524（×2 全量原子） | 扣减后记 material_paid；挑战子态快照 |
| /即时调合 大师+战斗内+限次 | ⚠️ | 2794/2798/2818 | 三道守卫均在；但能量消耗顺序违规（见 **P1-1**） |
| /教学 无门槛 | ✅ | cmd_tutorial 2624-2655 | 无门槛；带参=show、空参=目录 |
| /技能面板 无门槛 | ✅ | cmd_skill_panel 2595-2621 | 查看态无门槛；`解锁=` 为工程补白（F-19 SP 分支自选，契约允许） |
| /种植 /收获 正式 | ✅ | 2936 / 2959 | `FORMAL_TIER_INDEX(1)` |
| /代工 精通 | ✅ | 2987 | `PROFICIENT_TIER_INDEX(2)`；/收取 无门槛（F-22）✅ 3019-3026 |
| /协力 大师+会话中+同群 | ⚠️ | 3056/3066/3072-3074 | 同群校验 fail-open（见 **P2-1**） |
| 守卫链完整性 | ⚠️ | 见 P1-1 / P2-3 | 多数完整；两处依赖引擎、一处顺序违规 |
| 引擎接口消费与签名对齐 | ✅ | 全段 | 均鸭子/透传引擎 `res.get("ok")/message`；cmd_instant 只消费不 import（战斗资源 §三 对齐） |
| 渲染纯文本无装饰 emoji | ✅ | 2142/2244/2301/3096/2737 | 仅 ✅/❌ 功能性标记；深度面板/挑战面板/SP 面板/图鉴/教学均纯文本 |
| 幂等 ATO-05（复制/登记/进化） | ✅ | 1964-1987 / 2381-2407 | 已解锁幂等委托引擎（注释明示）；message_id 幂等走框架 ATO-03（批11 装配） |
| 数量上限提示不拦（复制 2147483647） | ✅ | 1976-1987 | 壳层不拦截 qty；引擎按 settings.alchemy.max_qty 归一（静态推导）；parsers 侧默认见 P2-5 |

---

## 二、发现（P0/P1/P2）

### P1-1（1 条）· /即时调合 能量先扣后校验，失败路径非零副作用
- **位置**：`alchemy_commands.py` L2805-2819（cmd_instant）
- **问题**：GU-52 在 L2806-2809 直接 `engine.consume_energy(player, ctx)` **实扣能量**，随后 L2811-2814 才做 GU-53 `engine.carry_ok`（素材全量校验）、L2816-2819 才做 GU-54 限次校验。两条失败路径：
  1. 携带素材不足 → `carry_ok` 返回非 ok → 返回「材料不足」，**能量已被扣**；
  2. 本场已用过即时调合（限 1 次）→ 走到限次拒绝，**能量已被扣**。
  这违背契约 ATO-01「/即时调合 全量原子校验（材料+金币/宝石全量满足才执行，否则全拒）」「单事务内复核持有量 → 任一步失败 ROLLBACK 零副作用」，属**命令失败仍扣资源**的非零副作用（静态推导：consume_energy 为写路径，非只读；L2806 注释即「consume_energy，不足拒」）。
- **影响**：`energy_enabled=true`（R-08 可配开关）时，玩家会凭空损失能量；默认 false 时潜在（契约 R-08 默认关，但契约铁律 6 明示「全拒零副作用」适用 /即时调合）。
- **修复建议**：把能量消耗并入 `engine.resolve` 的原子事务内（resolve 校验全通过后统一扣），或至少把 carry_ok / 限次检查前置到 consume_energy 之前（检查顺序按 GU-53→GU-54→GU-52 消耗，校验只读、消耗收尾）。同时限次拒绝可前置到消耗前（限次是纯读快照，顺序无关但更安全）。

### P2-1 · /协力 同群校验 fail-open（依赖装配注入，缺省放行）
- **位置**：`alchemy_commands.py` L3072-3074（cmd_assist）
- **问题**：`same_group = ctx.get("same_group"); if same_group is not None and not same_group: reject`——键缺失/None 时**保守放行**。若批11-2 装配层未注入 `same_group`，GU-46「同群好友」校验静默失效，TC-22「非同群拒」无法满足。docstring L3035-3036 自承「无群信息保守放行【工程补白】」。
- **修复建议**：装配层必须注入 same_group（对齐 SEP-15 消息层剥 @ 口径）；壳层建议改为 fail-closed（键缺失即拒绝并提示「无法校验同群关系」），或至少在 make_context 装配清单中把 `same_group` 列为必填注入项并留测试断言。

### P2-2 · /挑战 目标配方与当前深度会话配方一致性未校验（结算口径二义）
- **位置**：`alchemy_commands.py` L2520-2542（cmd_challenge）
- **问题**：`recipe = _find_recipe(ctx, target)` 按 `/挑战` 参数取配方，材料×2（L2524）与 challenge_recipe_id（L2540）按**目标配方**；但会话 `snap["recipe_id"]` 仍为**深度会话原配方**，`_render_challenge_panel` 与后续 `/确认` 的挑战结算将同时引用两个配方 id（L2203 `challenge_recipe_id or recipe_id` 兜底二义）。契约 GU-48「挑战会话从深度会话发起」，未定义目标配方 ≠ 深会话配方时行为。
- **修复建议**：`/挑战` 参数配方须与当前深度会话 `snap["recipe_id"]` 一致，否则拒绝（「挑战配方与当前深度调合配方不一致」）；或明确结算统一以 challenge_recipe_id 为准并在 /确认 侧同步（需核对 cmd_confirm 消费）。

### P2-3 · /镶核心 /加成 /进化 壳层未显式前置职业守卫（依赖引擎，本文件不可验证）
- **位置**：cmd_core L2437-2443、cmd_buff L2473-2478、cmd_evolve L2402-2406
- **问题**：GU-27 大师（镶核心）、GU-28 宗师（加成）、GU-23 宗师（进化）均未在壳层用 `_prof_level` 显式校验，docstring 标注由 `DeepEngine.mount_core / buff / evolve_unlock` 承载。本文件（批次E2 范围）无法验证引擎侧确实实现；若引擎漏检则门槛整体失效。同文件其余指令（合成/成品/配方/特性/登记/复制/挑战/即时/种植/收获/代工/协力）均在壳层显式前置，风格不一致。
- **修复建议**：壳层前置统一门槛（与 P2-7 口径统一），或在报告/测试中给出 DeepEngine 三方法守卫的覆盖证据（TC-14/15/16 测试断言）。

### P2-4 · 「雇工→代工」用户拍板未同步契约文档
- **位置**：实现 `cmd_helper` L2968（指令名 `代工`，HELPER_CMD）；文件头 L38 记「2026-08-28 用户拍板指令名改用『代工』」；**契约文档** `m8_contract_指令契约.md` §21（L53）与 §3.1 待新增词（L274）仍写「雇工」。
- **问题**：文档-代码命名漂移。功能无碍——DEFAULT_WHITELIST 已含「代工」（parsers.py L125），Router 按 HELPER_CMD 注册正常触发；但契约评审方按「雇工」检索会对不上。
- **修复建议**：契约文档 §21/§3.1 及 2c4d 指令表 §22 行同步为「代工」，或加拍板注解。

### P2-5 · 解析器接线未完成项（批11 依赖，非本批缺陷但需确认）
- **位置**：`parsers.py` L157 `DEFAULT_QUANTITY_COMMANDS` 缺「复制」；L163 `DEFAULT_MAX_QTY = 99`；契约 §3.3/§3.4（m8_contract_指令契约.md L284-294）
- **问题**：
  1. 契约 §3.3「需新增 1 词：复制」未落入 parsers——壳层 `_copy_qty`（L1707-1729）已兜底 `*N` 批量（主语法可用），仅**旧式空格数量** `/复制 魔力药水 5` 不兼容（静态推导：parsed.qty 为 None 且 args[0] 无 `*` → 返回 1）；
  2. parsers `DEFAULT_MAX_QTY=99` 与拍板⑤「默认 2147483647」不符——契约 §3.4 明示由批11 装配层从 `settings.alchemy.max_qty` 注入，壳层不重复（文件头 L78-79 已声明），但**若装配层未注入则默认仍 99**，超限语义（提示不拦）由 parsers 注入 max_qty 决定。
- **修复建议**：批11 路11A 落实两处接线；本批壳层已具备兜底，无需改动。

### P2-6 · /拆珠 槽位 0/负值透传引擎
- **位置**：`alchemy_commands.py` L1806-1811（cmd_unmount）
- **问题**：`si = int(slot_text)`；`engine_si = si - 1 if si >= 1 else si`——用户输入 `0` 时 `engine_si=0` 直接操作引擎首槽（用户侧 1 起语义下 `/拆珠 装备 0` = 拆首槽，边界语义含糊）；负值（如 -1）原样透传引擎（引擎若未防御则越界访问）。
- **修复建议**：对 `si < 1` 明确拒绝（「槽位从 1 开始」），或钳制为合法范围后提示。

### P2-7 · 门槛判定两种口径并存
- **位置**：cmd_register L1952-1953（`tier_index_for_level(job, _prof_level(player)) < _MASTER_TIER_INDEX`）vs 其余 10 处指令（L1856/1887/1922/1979/2502/2798/2936/2959/2987/3056 直接 `_prof_level(player) < TIER_INDEX`）
- **问题**：`tier_index_for_level = min(level, len(tier_names)-1)`（proficiency.py L231-239），level 与 tier index 默认数值对齐（0见习~6王），**当前默认配置下两者等价**（静态推导）。但若职业 tier_names 配置少于 5 档，register 口径会钳制导致高等级玩家被拒、其余指令放行——配置相关的不一致。
- **修复建议**：统一走 `tier_index_for_level`（语义正确且不受配置钳制影响），其余指令同步改写。

---

## 三、无问题维度确认（点名疑缺项已实现清单）

1. **/珠升阶 无职业硬门槛** ✅ —— cmd_jewel_up（L1818-1840）无任何职业判断，直接珠解析→升阶配方→UpgradeEngine（拍板③/TC-06）。
2. **/图鉴 不重复注册** ✅ —— register_alchemy_commands **未**注册 CODEX_CMD（L3374-3376 注释 + L3448 收口）；codex_commands.py L30/L140 注册「图鉴」，L107-108 单向 import `render_alchemy_codex` 作炼金分册渲染（防双注册 ValueError）。渲染器 L2552-2592 纯文本无装饰 emoji、成长奖励幂等。
3. **指令注册完整性** ✅ —— register_alchemy_commands 注册 30 个指令名（L3426-3456），覆盖本批全部 22 个函数 + 终态/投料/继承/分解；无重复注册（Router 重名 ValueError 风险规避）。
4. **DEFAULT_WHITELIST 含全部 M8 指令** ✅ —— parsers.py L107-137 已含 继承超/确认/放弃/调合续/深度炼金/进化/镶核心/加成/成品合成/分解/登记/复制/配方合成/特性合成/挑战/即时调合/教学/协力/种植/收获/收取/技能面板/珠升阶（批11-2 收口补）+ 既有 合成/炼金/镶嵌/拆珠/投料/代工/继承/图鉴（契约 §3.1 23 词全部到位）；/图鉴 在 DEFAULT_PREFIX_REQUIRED（L142，契约 §3.6 维持）。
5. **async/await 一致性** ✅ —— 除 cmd_synthesis 为同步 def（设计如此，`_synth` 直接返回 str，runner 对 isawaitable 自动 await）外，全部 async；注册闭包正确返回协程。
6. **异常兜底** ✅ —— 会话互斥冲突用鸭子 `is_conflict` 判定（cmd_deep L2360-2363）；session_mgr/battle_alchemy_engine/battle_snapshot 缺失抛 RuntimeError 显式提示装配接线（L2341-2345/2425-2428/2460-2464/2505-2509/2695-2700/2711-2715/3060-3063），非静默失败；槽位/数量/种子解析均有 try/except 兜底。
7. **数量上限提示不拦** ✅ —— cmd_copy 透传 qty 不拦截（引擎承载，拍板⑤）；max_qty 注入为批11 职责（见 P2-5）。
8. **A+B 两空格位置参数 + 同物两份** ✅ —— cmd_product_merge/formula_merge/trait_merge 均消费 args[0]/args[1] 两个纯名称位置参数（契约 §3.5）；成品合成同物两份由引擎组合表决定（壳不拦截）。
9. **/协力 同群校验存在** ✅（但 fail-open，见 P2-1）；@ 剥离由消息层，壳收纯 QQ 号（SEP-15）✅。
10. **2c4d TC 覆盖** ✅ —— 本批指令壳覆盖 TC-06(珠升阶)/TC-13~21/TC-22/TC-23/TC-24-25/TC-26/TC-27/TC-29/TC-30/TC-31 对应壳层；TC-32（/秘钥 不注册）确认未注册、走通用未知指令；TC-28（/任务）非 M8 范围由任务板承接；TC-34（幂等）属批11 装配。无本批指令壳层面的 TC 缺口。
11. **渲染模板纯文本无装饰 emoji** ✅ —— 深度面板（L2139-2197）、挑战面板（L2200-2240）、SP 面板（L2243-2260）、图鉴（L2552-2592）、教学（L2624-2655）、协力（L3096-3098）、即时（L2735-2757）均纯文本，仅 ✅/❌ 功能性标记（文件铁律 L69）。

---

## 四、修复优先级建议

1. **先修 P1-1**（/即时调合 能量顺序）：改消耗收尾，杜绝失败扣能量。
2. **P2-3 + P2-1** 需装配侧配合：补 DeepEngine 三守卫测试证据 + same_group 必填注入（或改 fail-closed）。
3. **P2-2** 补挑战配方一致性校验；**P2-4/P2-5** 属文档/接线同步，随批11 一并收口；**P2-6/P2-7** 低风险健壮性打磨。

> 本报告全部结论为**静态推导**：未运行任何命令/脚本/测试；引擎侧行为（SynthesisEngine/UpgradeEngine/AlchemyRegister/DeepEngine/AlchemyMeta/HarvestEngine/HelperEngine/BattleAlchemyEngine/ProficiencyEngine/JewelSystem）按 docstring 契约假定，需批12 路12A `verify_m8`（179 TC）实测确认。
