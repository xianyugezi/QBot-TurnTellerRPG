# 审查报告 · M5 实现 批次C（verify_m5 门禁 + 跨文档一致性 + M5 契约兑现度）

- 审查方式：**纯静态审查**（用户声明本环境无 bash 沙箱，全程未运行任何命令/脚本/测试；涉及运行期行为结论一律标注「静态推导」）。
- 门控档位：**full**（本文档交付即 ship 审查；采用 introspection + self-monitoring 双模块）。
- 审查范围：`scripts/verify/verify_m5.py`（658 行）× `scripts/run_all_tests.py`（111 行）× `docs/m5_shared_contract.md`（§一~§六）× `docs/全局图标登记表.md` × 细化 3d（26 TC）/5e（27 TC）/4f（28 TC）× 实现（battle_commands / basic_commands / explore_commands / prefix_wiring / message_format/prefix_render·battle_render·list_render·panel_render / commands/sender / content/validator）× `tests/unit/` 落盘清单 × 批次A/B 审查报告。

---

## 〇、结论总览

| 级别 | 数量 | 概要 |
|---|---|---|
| **P0** | 0 | 无阻断性/契约整体性缺陷；81 TC 统计诚实、无编造覆盖点、无谎报承载 |
| **P1** | 1 | 5e TC-18/TC-25「同一消息含 BREP-17+24+20」规格 vs 实现两消息拆分——批次B P1-1 未闭环（测试口径已改，契约/5e/batch_plan/verify_m5 标签未落 ADR） |
| **P2** | 6 | /背包 首行头部未实现未登记 / 战斗轮 16 行折叠无测试 / basic 头注释作废条款残留 / verify_m5 ④e 无裸 send 正则盲区+仅扫单文件 / 4f TC-19 机制级承载未注明 / 契约 §5.4 panel_render「/状态 ✅」表述张力 |
| 信息提示 | 2 | 「8 项门禁断言」= checks 8 项（含 ①②③）；批次B P1-1 拆分决策需落正式 ADR |

**一句话结论**：verify_m5 门禁的统计口径（68 承载 + 13 DELAYED）、pytest 引用真实性、8 项断言落地、与 verify_m4 模式一致性全部成立，无幻觉；批次A/B 主要修复项（P1-1 页码非法 / P2-5 explore 文案源 / 批次B P1-2·P1-3 折叠与连段）已反映到代码；残留问题集中在「批次B P1-1 跨文档拆分未闭环」与数个 P2 级规格件/注释/门禁强度缺口。

---

## 一、维度① 缺漏

### 1.1 81 TC 覆盖点统计诚实性 —— ✅ 属实

- `COVERAGE` 字典逐条核对：3d TC-01~26（26 条）、5e TC-01~27（27 条）、4f TC-01~28（28 条），合计 **81**（verify_m5.py L46-212）。
- DELAYED 项 13 条：3d TC-16/17（2）+ 4f TC-01/02/03/04/06/07/09/10/17/22/23（11）＝ **13**；已承载 81−13 = **68**。与任务口径「68 承载 + 13 DELAYED」一致（verify_m5.py L430-434 运行期亦自算校验，静态推导成立）。
- `t_coverage_self_consistent` 还强制：每条值仅允许 `pytest:`/`DELAYED` 前缀；所有 pytest 引用文件必须落盘；引用函数名必须存在于对应文件 `def` 列表（L399-428，反虚假承载机制）。**该机制本身存在且逻辑自洽。**

### 1.2 DELAYED 理由充分性 —— ✅ 13 条全部与代码现状一致

| DELAYED 项 | verify_m5 理由 | 静态核对 |
|---|---|---|
| 3d TC-16/17（锻造 TPL-10/11） | 锻造系统未实装（M6 生活生产批次） | ✅ `qbot_rpg/commands/` 无任何 forge 指令（全局 grep CommandSpec 无锻造）；细化_2c2* 为规划文档 |
| 4f TC-01~04/06（/注册 首次/职业/重名/幂等/名字长度） | /注册 未实装，仅 TPL_REGISTER_GATE 拦截文案；TC-05/27 承载门槛 | ✅ 全仓无 cmd_register/CommandSpec 注册；basic_commands `_gate` 用 TPL_REGISTER_GATE；保留字符提示确由 M4 2.1-03（test_parsers::test_reserved_char_hint_*，L553/558/563）承载 |
| 4f TC-07/09/10（/状态 五区/效果区/战斗内目标行） | /状态 未实装，B4 裁决由装配层承接；本 M5 实现 /角色 TC-25~28 | ✅ 全仓无 cmd_status/STATUS_CMD（grep 零命中）；panel_render 仅渲染助手（见 P2-6） |
| 4f TC-17（帮助别名显示替换） | cmd_help 未消费别名表 | ✅ `_help_groups`/`_group_summary` 用静态 HELP_GROUPS 名，无别名替换（basic_commands L1159-1174） |
| 4f TC-22/23（快捷解绑/列表与持久化） | /快捷解绑 /快捷列表 无 handler（help 目录登记指令名但未注册） | ✅ basic_commands L184-185 HELP_GROUPS「快捷」组登记三指令名；全仓无三指令 CommandSpec（grep 零命中），router 仅有校验函数（L740-866） |

### 1.3 新增门禁断言 8 项落地 —— ✅ 全部落地（8 = checks 列表 ①~③ + ④a~④e）

- verify_m5.py `main()` checks 列表共 **8 项**（L592-613）：① 模块导入 ② 关键函数+零 NoneBot ③ COVERAGE 自洽 ④a 前缀验收示例逐字 ④b 一轮=1条 ④c /角色 三层行 ④d emoji 静态 ④e 无裸 send。任务括号内命名的 5 项＝④a~④e（G5 新增），另 3 项为 ①②③。
- ④a~④e **静态可推成立**（详见「无问题维度」第 4 条）：④a 前缀三态/正文第二行逐字可复算；④b 真实引擎+Mock sender → dispatch_round 恰 1 次 send（默认前缀不触发截断黄提示）；④c /角色 29 值经 `calc_all_final_attributes` 管线（15+5→20×1.10→22×1.20→26.4+3→29，`_pipestep` player_attributes L137-162）成立；④d 样本零禁用 emoji 且 `_assert_no_banned_emoji` 按 CJK/全角/ASCII 白名单兜底（比 BANNED_EMOJI 枚举更宽）；④e battle_commands 无 `Sender(` 实例化、`.send*` 接收者首段 ∈ {self, pipeline, sender}。

### 1.4 M5 契约 §一~§六 无「完全无实现且无登记」项 —— ✅（部分规格件见 P2 点名）

- §一 D1 / §二 D2 / §三 D3 / §四 D4 / §五 D5 的全部 ⬜ 待实现项均已有实现（M5-01~08）或保持 ⬜ 登记；「前缀挂玩家回复首行（所有指令出口）」仅战斗出口接线——契约 §1.4 已标 ⬜，非静默缺漏（批次A P2-1 已登记，批次7 装配承接）。
- 唯一**部分规格件未实现且未登记**：4f TC-11 /背包 首行头部「【背包 · 第 X/Y 页】」（见 P2-1）。

---

## 二、维度② 错误

- **pytest 引用路径真实存在**：verify_m5 COVERAGE + PYTEST_FILES 引用的 17 个测试文件（test_core / test_coredata_regress / test_message_prefix_wiring / test_message_prefix_validator / test_battle_render_player·skill·enemy·settlement·startend / test_battle_wiring / test_explore_filter / test_emoji_discipline / test_basic_commands / test_sender / test_list_render / test_parsers / test_router）**全部落盘**于 `tests/unit/`。✅
- **引用函数名全部真实**：COVERAGE 全部 ~120 处 `file::fn` 引用逐文件对照 `def test_` 清单全部命中；test_parsers 引用的 4 个为类内方法（TestCompact/TestModes/TestShortcut），pytest 可收集，且 verify_m5 校验正则 `^\s*def (test_\w+)\s*\(` 可命中缩进方法——机制正确。✅
- **DELAYED 理由与实际情况一致**：见维度① 1.2，全部对上。✅
- **run_all_tests 阶段2 m5 接入与 verify_m4 模式一致**：`MILESTONES` 字典 m5→VERIFY_M5（L32/L41），阶段 2 循环统一对 m0~m5 跑 verify 脚本子进程（L95-101），`--only m5` 命中（L75-82）；与 m4 完全同构。verify_m5 内部 COVERAGE 校验/函数级核验/DELAYED 机制亦与 verify_m4（verify_m4.py L383-419）逐行同构。✅

---

## 三、维度③ 幻觉

- **无编造覆盖点**：81 条 TC 标签全部对应细化 3d/5e/4f 真实 TC（26/27/28 数一致）；无引用不存在的 TC 编号（TC-01~26 / TC-01~27 / TC-01~28 连续无跳号）。✅
- **无「实现未覆盖谎报为已承载」**：所有 pytest 引用均真实落盘且有对应 def；13 条未实现项如实标 DELAYED 而非伪承载。✅
- **标签与承载语义的部分偏差（P2 级，非幻觉）**：
  - 5e TC-18 标签「（BREP-17/24/20，掉落仅此一次）」未复述 5e 规格「同一消息」，而承载测试断言两消息拆分（见 P1-1）——标签诚实但承载语义与规格文本有落差。
  - 5e TC-06 标签「单条 ≤16 行折叠」的承载测试仅覆盖 BREP-25 明细块折叠，战斗轮消息折叠已实现但无测试（见 P2-2）。
  - 4f TC-11 标签省略 /背包 首行头部规格件（见 P2-1）；4f TC-19 承载为机制级（见 P2-5）。

---

## 四、维度④ 跨文档

- **§六 81 TC 矩阵与细化 TC 数一致**：3d 细化 26（TC-01~26，L298-348）＋ 5e 细化 27（TC-01~27，L365-416）＋ 4f 细化 28（TC-01~28，L386-438）＝ 81；与 m5_shared_contract §六（L179-185）逐条对齐。✅
- **登记表与批次A 结论一致**：`docs/全局图标登记表.md` 唯二 ✅/❌ ＋ 排版符号豁免（§一）＝ test_emoji_discipline `_ALLOWED={✅,❌}`（L23/L111）＝ emoji_sanitize `_EMOJI_CLASS` 挖掉 U+2705/U+274C（L27-29）；`test_registry_allowed_markers` 断言白名单不扩宽；登记表 §四 覆盖点与 4 个测试逐条吻合。与批次A「三方一致」结论延续成立。✅
- **批次A/B 已修项反映到代码（抽查）**：
  - ✅ **P1-1 页码非法修复**：basic_commands `cmd_bag_filter` L752-758 对尾随 `0`/负数 → TPL-12（`last.isdigit() and int(last)<1` / `-N` 分支）；测试 `test_filter_page_invalid_tpl12`（test_explore_filter L129-133，覆盖 0/-1/-3）。非数字保留为筛选词容错（与批次A 建议一致）。
  - ✅ **P2-5 explore 文案源**：explore_commands L19 `from .sender import format_tpl12`，L92/L117 引用，原自写 `_tpl12` 已删；同批 P2-2（私聊[群名]兜底，prefix_wiring L205-213）、P2-4（format 空补全 L130-134）、P2-7（壳层 `_gate` L39-43）亦已修。
  - ✅ **批次B P1-2（16 行折叠实现）**：battle_render `_fold_message_lines`（L74-92）接入 `render_battle_round`（L160）。
  - ✅ **批次B P1-3（连段 segments 注入）**：battle_commands `_build_segments`（L419-447）读引擎快照 action_record → `_inject_display_outcomes` 注入 segments（L400-407）→ dispatch_round L649 接线；battle_render `_render_combo_segments` 消费。
  - ✅ **批次B P2-3（死亡守卫）**：battle_render L136-138 玩家 HP≤0 跳过反击行。
- **批次A/B 未闭环项（本批新登记）**：批次A P2-3（/背包 头部）→ 本批 P2-1；批次A P2-8（basic 注释）→ 本批 P2-3（半修）；批次B P1-1（结算拆分跨文档）→ 本批 P1-1（半修）；批次B P1-2（战斗轮折叠测试）→ 本批 P2-2（实现已修、测试未补）。

---

## 五、缺漏维度点名「应覆盖 X 但未覆盖」清单

1. **4f TC-11 /背包 首行头部「【背包 · 第 X/Y 页】」应实现/登记但未实现未登记**：细化 4f L406/TPL-4F-04 规格含头部；`_render_bag_page`（basic_commands L547-566）只出条目+夹取提示+TPL-08；`test_bag_page1_rows_and_footer`（L258-264）首行=条目，无头部；verify_m5 4f TC-11 标签未含该规格件、无 DELAYED 登记（→ P2-1）。
2. **5e TC-06 单条 ≤16 行折叠对「战斗轮消息」应补测试但未补**：实现已折叠（battle_render L160），但全仓无 `render_battle_round` 超 16 行用例；TC-06 承载仅覆盖 BREP-25 明细块（test_battle_render_startend L255-284）（→ P2-2）。
3. **D2「全仓无裸 send」静态检查应覆盖全仓但 verify_m5 ④e 仅扫 battle_commands.py**：契约 §二 待实现「全仓禁止裸 send 审查（D2 验收④）」，④e 只读单文件（→ P2-4）。
4. **5e TC-18/TC-25「同一消息含 BREP-17+24+20」规格应实现或登记 ADR 但未闭环**：实现为两消息拆分，规格未改、ADR 未落（→ P1-1）。
5. （已登记非静默）前缀挂玩家回复首行仅战斗出口 / 战斗开始接线待批次7——契约 ⬜ 已登记，随批次7 装配承接。

---

## 六、分级问题清单（文件行号 + 修复建议）

### P1（1 项）

**P1-1　5e TC-18/TC-25「同一消息含 BREP-17+24+20」规格 vs 实现两消息拆分（批次B P1-1 未闭环）**
- 位置：实现/测试 `test_battle_wiring.py::test_battle_end_flow_summary_and_drops`（L238-256，显式断言 `len(sender.calls)==2`：当轮消息含 BREP-15/17/20、结束消息含 BREP-24）；`battle_render.py` `_render_settlement` 挂当轮（L148-152）、`render_battle_end` 只出 BREP-24/25（L163-173）；`dispatch_round` L635-644 结束后追加 `send_end`。规格未同步：`细化_5e` L397（TC-18「同一消息含 BREP-17+24+20」）/L414（TC-25「结果横幅/掉落与汇总同消息输出」）、`m5_batch_plan` L46「胜利/掉落同消息且只一次」、`m5_shared_contract §5.2/§六` 均仍为单消息口径。
- 现状（静态推导）：结束操作 2 条消息，仍在铁律 2「单次操作 ≤1-2 条」预算内、掉落只输出一次（军规 5），**功能无崩坏**；属契约-实现语义缺口。verify_m5 5e TC-18 标签「（BREP-17/24/20，掉落仅此一次）」未复述「同一消息」，承载测试断言的是拆分语义——标签诚实但规格项未兑现。
- 修复建议（落 ADR，二选一）：(a) 将结算（BREP-17~20）并入 `render_battle_end`，当轮只出行动+击杀，使结束=1 条并满足 TC-18 字面；(b) 在 5e TC-18/TC-25、m5_batch_plan、m5_shared_contract §5.2/§六 显式登记拆分决策（当轮含结算、结束仅汇总明细，≤2 条，铁律 2），并同步 verify_m5 5e TC-18 标签措辞。

### P2（6 项）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| P2-1 | 4f TC-11 /背包 首行头部「【背包 · 第 X/Y 页】」未实现且 verify_m5 标签省略、无 DELAYED 登记（批次A P2-3 未闭环） | basic_commands `_render_bag_page` L547-566；test_basic_commands L256-264；verify_m5 L176（4f TC-11 标签） | 补头部（4f TPL-4F-04 口径）或显式裁决删除该 4f 规格件并在 verify_m5 标签/DELAYED 注明 |
| P2-2 | 5e TC-06 战斗轮消息 16 行折叠无测试（实现已修、用例未补；批次B P1-2 半闭环） | battle_render L74-92/L160；test_battle_render_startend L255-284 | 补 `render_battle_round` 超 16 行（多段连段+拦截链+状态+结算+提示）折叠用例，断言 ≤16 行 + TPL-09 省略行 |
| P2-3 | basic_commands 头注释仍载已作废「数据型 icon 豁免 m4 §2.2」措辞（批次A P2-8 半闭环：L19 已加 M5 裁决纠正注记，其余未回写） | basic_commands L6-7/L32/L68；登记表 §三 | 统一改写为「icon 渲染剥离 emoji（M5 裁决，登记表为准）」，删除豁免字样 |
| P2-4 | verify_m5 ④e 无裸 send 正则盲区 + 范围：`[A-Za-z0-9_.]*?` 无法匹配 `expr().send(`（battle_commands L654 `BattlePipeline.from_ctx(ctx).send` 未被检查，当前非违规）；且仅扫 battle_commands.py，非契约 D2「全仓」口径（其余指令壳返回 str 无 Sender，风险低） | verify_m5 L568-585；契约 §二 | ① 补充链式调用（含括号）匹配或显式注明「检查简单链；`expr().send` 走统一出口视为合规」；② 或在 docstring 注明 ④e 范围=battle_commands（D2 全仓审查由指令壳 str 返回结构保证） |
| P2-5 | 4f TC-19「快捷绑定+触发」承载为机制级（校验函数+路由展开），/快捷绑定 指令 handler 未注册 CommandSpec；标签未注明 | verify_m5 L192-193（4f TC-19）；router.py L740-866 仅校验函数；basic_commands L184-185 登记指令名未注册 | 标签注明「机制级承载（绑定校验+路由展开），/快捷绑定 指令注册随批次7」；或补指令 handler |
| P2-6 | m5_shared_contract §5.4「panel_render.py 总览面板（/状态）｜✅」与 verify_m5 4f TC-07/09/10 DELAYED「/状态 未实装」并存易误读 | m5_shared_contract L166；panel_render.py（仅 render_panel/render_stats_line/paginate）；全仓无 cmd_status | 契约 §5.4 改为「panel_render 渲染助手模块存在；/状态 指令未注册，面板五区随装配层批次承接」，与 DELAYED 口径一致 |

### 信息提示（非缺陷）

- **「8 项门禁断言」口径**：任务括号内命名 5 项（前缀示例逐字/一轮=1条/角色三层行/emoji 静态/无裸 send）＝ verify_m5 ④a~④e（G5 新增）；「8 项」＝ checks 列表 8 项（① 模块导入 ② 关键函数+零 NoneBot ③ COVERAGE 自洽 ④a~④e）。两者均成立，无代码缺陷，仅任务措辞粒度差异。
- **批次B P1-1 拆分决策已体现在测试注释**（test_battle_wiring L239「当轮 1 条 + 结束 1 条（≤2 条，铁律 2）」），但未落正式 ADR——随 P1-1 一并登记即可。

---

## 七、无问题维度确认

1. ✅ **81 TC 统计诚实**：3d 26 + 5e 27 + 4f 28 = 81；68 承载 + 13 DELAYED 属实；13 项 DELAYED 理由与代码现状全部一致（见维度① 1.2）。
2. ✅ **pytest 引用零幻觉**：17 个文件全部落盘；COVERAGE 全部函数名（含 test_parsers 类内方法）均存在于对应 def 列表；`t_coverage_self_consistent` 反虚假承载机制逻辑自洽。
3. ✅ **verify_m5 与 verify_m4 门禁模式一致**；run_all_tests 阶段2 m5 接入与 m4 同构（MILESTONES 字典 + --only m5 生效）。
4. ✅ **8 项门禁断言全部落地且静态可推成立**：④a `Lv35.阿伟 -斩龙者-`/`Lv35.阿伟 - -`/`Lv35.阿伟` 三态逐字可复算（prefix_render L55-114）、正文第二行（prefix_wiring L228-231）；④b 真实引擎+Mock sender `call_count==1`（battle_commands dispatch_round L633 单条 send_round，默认前缀不触发截断黄提示）；④c `/角色` 头部/29 值/TPL-08 页脚（player_attributes 管线复算 29.4→29；render_footer L142 格式逐字吻合）；④d 样本零禁用 emoji + 全仓 AST 扫描由 test_emoji_discipline 承载；④e battle_commands 无 `Sender(` 实例化、`.send*` 接收者全为 self/pipeline/sender。
5. ✅ **§六 TC 矩阵与各细化 TC 数一致**（26/27/28）。
6. ✅ **登记表 ↔ test_emoji_discipline ↔ emoji_sanitize 三方一致**（与批次A 结论一致）；登记表 §四 覆盖点与测试逐条吻合。
7. ✅ **批次A/B 已修项反映到代码**：P1-1（筛选页码非法→TPL-12+测试）、P2-5（explore 改引 sender.format_tpl12）、P2-2/P2-4/P2-7（私聊兜底/format 空补全/壳层 _gate）、批次B P1-2/P1-3/P2-3（折叠/连段注入/死亡守卫）全部核实落地。
8. ✅ **无编造覆盖点 / 无「实现未覆盖谎报已承载」**：13 条未实现项如实标 DELAYED；全部 pytest 引用真实。

---

*审查方法声明：本文档全部结论为静态阅读产出（未运行任何命令/脚本/测试）；P1/P2 涉及运行期行为处均标注「静态推导」，修复后应由回归测试证实。*
