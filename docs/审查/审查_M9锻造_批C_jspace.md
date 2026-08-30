# M9 锻造 · 批C 静态审查报告（指令层 + 边界铁律 + P1/P2 预留）

> 审查方式：j-space full 档静态代码审查（本环境无 bash 沙箱，禁运行命令；结论均为**静态推导**，
> 未执行任何测试/脚本）。依据：细化 2c2b/2c2d、m9_shared_contract、m9_batch_plan、m9_接口摸底、
> 锻造系统设计定稿；实测证据经 grep/read 真实代码确认，不凭印象。
> 范围：`forge_commands.py` / `parsers.py`(白名单段) / `forge_bounds.py` / `forge_sets.py` /
> `forge_augments.py` / `forge_king.py`。

## 〇、结论速览

- **P0：2 项**（生产装配未接线 → 六指令不可达；确认窗跨指令丢窗）
- **P1：3 项**（铸造王未接线、白名单缺「图纸」、P-03 罗马等价与细化冲突）
- **P2：4 项**（边界铁律无运行时消费、熟练入账不回滚、费用 int 语义不一致、批量逐件原子弱化）

---

## 一、P0（阻断/生产不可达）

### P0-1 六指令在生产装配层未接线 —— 指令层整体不可达
- **位置**：`assembly/router_setup.py` L75-92 `REGISTER_GROUPS`（无 `forge_commands.register_forge_commands`）；
  `assembly/context.py` make_context（无 `ctx["forge"]` 注入）；`forge_commands.py` L1765-1834（注册函数仅被测试/verify 直接调用）。
- **静态推导**：生产 runner（`runner.py` L597 `route_and_expand` → `router`）只消费 `build_router` 产物；
  REGISTER_GROUPS 未含 forge → `/锻造 /确认 /图纸 /锻造树 /套装 /客制` 六指令在注册表缺失 → 路由 `_match_whitelist` 不命中 → **静默忽略**。
  即使注册上，`make_context` 未注入 `ctx["forge"]`（m9_接口摸底 §七「ctx['forge'] 表注入（批4）」未落地），
  `_forge_raw(ctx)` 恒 `{}` → GU-01 恒判「❌ 锻造系统未启用」。verify_m9_smoke 里 `register_forge_commands(router)` 是测试侧手工接线，掩盖生产缺口。
- **修复**：① router_setup.REGISTER_GROUPS 追加 `forge_commands.register_forge_commands`（注意见 P1-2「确认」重名）；② context.make_context 注入 `ctx["forge"]`（forge.json raw dict，含 trees/sets/augments/settings 四段，Def→dict 表注入坑见 m9_接口摸底 §八-2）。

### P0-2 确认窗状态仅存 ctx 内存窗 —— 预览→/确认 跨指令必丢窗
- **位置**：`forge_commands.py` L247-248 `PREVIEW_WINDOW_KEY`、L876-895 `_register_preview`（写 `ctx["forge_preview"][qid]`）、L106 F-3「装配层/测试注入共享 ctx 即共享窗」；
  生产 `runner.py` L597 `ctx = await make_context(event, deps)`（每条指令重建全新 ctx dict）；`assembly/context.py` 无 `ctx["forge_preview"]` 注入。
- **静态推导**：2c2b §3.3 要求确认窗「存在于单条指令→下一条指令之间」（TC-12 预览后 `/确认` 完成锻造）。实现把窗放 `ctx` 内存键，而生产每次指令 `make_context` 重建 ctx →
  预览登记的窗随本次 ctx 丢弃，下一条 `/确认` 读到全新空 ctx → 恒回「当前无可确认的锻造预览」。单测（test_tc12）用**同一 ctx 对象**串联两指令才通过，属「单测掩盖部署 bug」（m9_接口摸底 §八-4）。
- **修复**：装配层注入共享窗源（如 player 级 `persistent_state["forge_preview"]` 或 session_mgr 承载），
  `ctx["forge_preview"]` 指向该共享 MutableMapping（F-3 预留了口径，缺接线）。确认窗本身为一次性超短期、非 3.18 会话，仍可不持久化但必须跨指令共享。

---

## 二、P1（功能缺口 / 契约违背 / 验收不过）

### P1-1 铸造王（KF）未接线到 /锻造 —— 图鉴全亮不授予、king_only 无守卫
- **位置**：`forge_commands.py` L993-999（`_execute` 只调 `mark_seen`，无 `grant_forge_king`）、L787-839（守卫链 GU-01~06 无 king_only 检查）；`forge_king.py` L229 `grant_forge_king`、L365 `forge_king_eligible_check`、L259 `king_only_nodes`。
- **静态推导**：`forge_king.py` 六函数仅被 `tests/unit/test_forge_king.py` + `scripts/verify/verify_m9_b3.py`/`verify_m9_smoke.py` **直接调用**，生产 /锻造 流程零消费。
  → ① 2c2d KF-01「点亮最后一节点时即时结算铸造王称号」（TC-28）不满足：`mark_seen` 后无授予钩子；
  ② 2c2d N-16「king_only 节点 /锻造 前置守卫追加王资格」（TC-22）不满足：无王资格也可锻 king_only 专属配方。
- **修复**：`_execute` 成功路径 mark_seen 后调 `grant_forge_king(player, ctx)`；`_forge_once` 守卫链 GU-06 前调 `forge_king_eligible_check(player, ctx, node)`（或并入 GU-03b 同层）。

### P1-2 白名单登记缺「图纸」+ 「确认」与炼金 M8 重名
- **位置（图纸缺登记）**：`parsers.py` L107-143 `DEFAULT_WHITELIST`（含 锻造 L112 / 锻造树 L115 / 套装·客制 L118 / 确认 L135；**无「图纸」**）；
  `forge_commands.py` L1828-1833 六指令全注册（图纸=BLUEPRINT_CMD whitelisted=True）。
- **静态推导**：批5C/7C 自述「六指令全部注册 + 白名单登记」，且 parsers L114/L117 注明「独立指令名注册须进白名单才能被 S5 前缀匹配触发，缺白名单静默不响应」——
  「图纸」未登记违反自身裁决；`router_setup.check_consistency`（L201-222）会报 `registered_not_whitelisted={"图纸"}` 硬不一致（装配冒烟失败）；parsers 路径（`parse_command` L787-792 candidates 取 whitelist）会忽略 /图纸。
- **位置（确认重名）**：`alchemy_commands.py` L170/L3445 `CONFIRM_CMD="确认"` 已注册；`forge_commands.py` L236/L1829 同名注册。
- **静态推导**：`Router.register`（router.py L206）重名默认抛 `ValueError`（TCA-02）。若按 P0-1 把 forge 接入 REGISTER_GROUPS 且先于/后于 alchemy 注册 → build_router 直接抛错或一方被覆盖；两处 /确认 语义不同（炼金品质结算 vs 锻造预览确认），无法合并。
- **修复**：① parsers.DEFAULT_WHITELIST 补「图纸」；② 两个 /确认 需仲裁（建议 forge 确认复用同名指令但由装配层按上下文路由，或改 forge 确认入口名并同步批5 契约）。

### P1-3 P-03 罗马数字等价（F-11）与细化 2c2b 冲突 —— 需裁决记录
- **位置**：`forge_commands.py` L132-136（F-11 注明「任务派工单明令」）、L562-578（`_roman_normalize`/`_digit_to_roman`）、L581-613 `_resolve_with_roman`（炎剑Ⅱ↔炎剑2 双向等价）。
- **静态推导**：细化 2c2b §5.1 P-03 原文「Ⅱ 等罗马数字按普通字符参与匹配（炎剑Ⅱ ≠ 炎剑2 除非配置别名）」+ TC-21 断言「炎剑Ⅱ 与 炎剑2 互不混淆」。
  实现按等价归一（`/锻造 炎剑2` 命中炎剑Ⅱ，test L670-674 已固化为通过用例）。**与本次审查所引权威细化直接冲突**；F-11 声称的派工单裁决在 m9_batch_plan.md（批4 路4C 仅列「P-01~06 词法」无等价细节）中**不可验证**。
- **修复**：若派工单确有裁决，须在 m9_batch_plan/仲裁文档补录该裁决（含日期/决策人），并同步 TC-21 断言；否则回退 P-03 原义（罗马/数字按普通字符，不归一），删 F-11 双向映射。

---

## 三、P2（轻微 / 文档 / 原子性边角）

### P2-1 边界铁律四函数无运行时/冒烟消费
- **位置**：`forge_bounds.py` L233 `determinism_check` / L313 `slotted_source_check` / L463 `alchemy_interface` / L628 `forge_fee_check`。
- **静态推导**：全仓仅单测（tests/unit/test_forge_bounds.py）消费；`verify_m9_smoke.py`（批6B 冒烟）import 了 forge_commands 但未调 forge_bounds 四函数。
  「边界铁律接口契约」成为纯测试件，无生产/验收门禁兜底（确定性/带孔唯一来源/费用公式在内容包变更时无冒烟断言）。
- **修复**：verify_m9_smoke 加一节调用四函数断言 ok；或批8 门禁脚本纳入。

### P2-2 熟练入账失败不回滚已扣素材/金币（原子性边角）
- **位置**：`forge_commands.py` L983-986（`gain_forge_exp` 返回值被忽略）、L909-1001 `_execute`（回滚只覆盖素材/金币/入包失败分支）。
- **静态推导**：成功路径扣素材→扣金币→入包→发经验；若 `gain_forge_exp` 返回 `ok:False`（如计价配置异常），素材/金币已扣、物品已入包，但经验未发且无回滚 → 与「§1.2 原子写、失败零副作用」语义不符。正常计价下几乎不发生，属低概率原子性缺口。
- **修复**：`gain_forge_exp` 失败分支回滚素材+金币+移出刚入包物品，返回失败模板。

### P2-3 费用 `forge_fee` int 语义与 forge_fee_check 不一致
- **位置**：`forge_commands.py` L1004-1023 `_resolve_cost`（int → 固定费用直接返回）；`forge_bounds.py` L652-675 `forge_fee_check`（int → `base_fee_per_level`，即「节点等级×int」）。
- **静态推导**：同是 int `forge_fee`（如 100），指令层按**固定 100 金币/件**收，边界校验层按**每级 100**（100×节点等级）断言 → 两模块语义漂移；契约 S-01 未明确 int 是固定还是每级系数。
- **修复**：m9_shared_contract §三 S-01 补白 int 语义（建议 int=固定值、str「节点等级×N」=每级系数），两模块对齐；或 _resolve_cost 对 int 也乘 node.level。

### P2-4 批量 `*N` 中途失败保留已成功件（逐件原子而非整批原子）
- **位置**：`forge_commands.py` L745-756（循环 `_forge_once`，中途失败返回「第 N 次失败，已成功 M 次」，不回滚已成功件）。
- **静态推导**：与细化 §1.2「多件：按数量循环执行上述原子流程…原子无中间态」措辞有张力——实现为**每件**原子（素材逐件重跑 GU-05），整批非原子。测试（test_4c_batch_mid_failure）已固化「第 1 件成功保留」行为。行为有文档声明，仅契约措辞边界需标注（建议契约注明「批量=逐件原子，非整批原子」）。

---

## 四、维度确认（无问题项）

- **① 定稿落地（本体）**：GU-01~06 顺序链正确（GU-01 系统注册 → GU-02 空格/参数 → GU-03 节点+红名失效 → GU-04 前置已锻 → GU-05 素材足够 → GU-06 等级足够，与 2c2b §1.1 顺序一致）；直锻/预览双流路由正确（`straight_forge` 缺省 true，显式「预览」不受开关限制，false 强制预览，TC-09/10/13 语义对齐）；确认窗 90s 超时用 `ctx["now"]` 比较、零 sleep（F-8）；`/锻造树` 分页 5 条/页（`TREE_PAGE_SIZE = DEFAULT_PAGE_SIZE = 5`，越界页空态）；P-01 禁空格 / P-02 字符集 / P-04 ■省略 / P-05 *N / P-06 多词引号 / 歧义候选列表均实现；费用公式缺省 节点等级×10（`_resolve_cost` 与 `forge_fee_check` 对 str 公式一致）。
- **② 代码质量**：commands 层**零 NoneBot import**（forge_commands 仅 qbot_rpg 内部 + stdlib re/time/typing）；纯函数确定性（同参同值，时间戳走 ctx now 注入、`time.time()` 仅作时钟读兜底）；`_execute` 素材/金币/入包失败各有回滚分支；确认窗零 sleep；六指令 CommandSpec 全注册 + 白名单标记（缺「图纸」见 P1-2）。
- **③ 遗漏（本体）**：2c2b §六 A 直锻 TC-01~04、B 不足 TC-05~08、C 双流 TC-09~14 均有对应单测覆盖（tests/unit/test_forge_commands.py）；2c2d 套装/客制 P1 边界声明正确（cmd_sets/cmd_augments 仅查询骨架，SP-F4/F5 解锁门控，不执行激活/客制，符合 2c2d §1.5/§2.4 与 m9_接口摸底 §六）；parse_sets/validate_sets/parse_augments/validate_augments 委托批0 `validate_forge`（forge_models）且 (rule,field) 去重，无重复实现。
- **④ 跨模块一致性（接口签名）**：forge_commands 消费的 forge_tree（resolve_node/merge_forge_instance/load_trees/nodes/final_of/branch_of/children_of/line_endpoint/path_to_root/parent_forged/already_forged/node_level_met）、forge_job（_tier_name/exp_to_next/gain_forge_exp/level_gate_met）、forge_progress（material_holdings/shortfall/progress_line）、forge_sp（sp_locked）、forge_cascade（is_redflagged）、forge_sets（parse_sets/set_lookup）、forge_augments（parse_augments）**签名与返回结构全部对齐**（逐一核对实现确认）。
- **⑤ M43 零定时器**：6 文件全文（含 docstring）**无** `time.sleep` / `threading.Timer` / `schedule` 字面量（grep 全 `qbot_rpg/forge*.py` 零命中）；`import time` 仅用于 `time.time()` 时钟读，符合「只读时钟零睡眠」。

---

## 五、Top 3 问题（8 行内）

1. **P0-1 装配层未接线**：六指令未进 `router_setup.REGISTER_GROUPS` + `make_context` 未注入 `ctx["forge"]` → 生产 /锻造 六指令整体不可达（路由忽略 / 恒「锻造系统未启用」）；verify 手工注册掩盖缺口。
2. **P0-2 确认窗跨指令丢窗**：窗存 ctx 内存键而生产每次指令重建 ctx → 预览后 `/确认` 恒「无可确认的锻造预览」（TC-12 生产必败）；单测同 ctx 串联才通过。
3. **P1 铸造王/白名单**：forge_king 未接线（图鉴全亮不授予、king_only 无守卫）；「图纸」缺 DEFAULT_WHITELIST（六指令白名单缺 1 + check_consistency 硬不一致）；「确认」与炼金 M8 重名（接线即 ValueError）。

---

*审查基准：细化_2c2b / 细化_2c2d / m9_shared_contract / m9_batch_plan / m9_接口摸底 / 锻造系统设计定稿 v1.0.1 · 结论均为静态推导，未运行代码。*
