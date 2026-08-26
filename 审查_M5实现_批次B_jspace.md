# 审查报告 · M5 实现 批次B（D5 battle_render BREP-01~25 + battle_commands 一轮1条接线）

- 审查方式：**纯静态审查**（本环境禁运行命令/脚本，全部结论来自逐行阅读）；涉及运行期行为处标注「静态推导」。
- 审查范围：`docs/m5_shared_contract.md`（§五 D5 / 铁律 2/9/11）× `docs/细化/细化_5e_战斗战报格式.md`（BREP-01~25 + TC-01~27 + 军规1-5）× `docs/细化/细化_3d_消息模板规范.md`（§3.1 承接表 / §3.2 L184）× `docs/m5_batch_plan.md` × 实现代码（`battle_render.py` 1099 行 / `battle_commands.py` 795 行 / 6 个测试文件）×(引擎) `qbot_rpg/core/battle.py`。
- 门控档位：**full**（本文档交付即 ship 审查）。

---

## 〇、总览

| 级别 | 数量 | 摘要 |
|---|---|---|
| P0 | 0 | 无虚构模板/虚构 TC/虚构接线；签名、取数、字段口径均与契约一致 |
| P1 | 3 | ①结算放置与 5e §6.2/TC-18/3d §3.1 冲突 ②16 行折叠未覆盖战斗轮消息 ③连段 segments 未接线、BREP-21/22 真实管线不可达 |
| P2 | 4 | 战斗开始接线待批次7 / BREP-25 条目行带序号 / 渲染层无死亡守卫 / 逃跑·道具自合成文案 |

**P0 核查（无问题确认）**：
- BREP-01~25 **全部实装**（25/25），逐条对照 5e §1.4 注册表通过（唯一差异见 P2-2）。
- IF30/IF31/IF32 签名按骨架保留：`render_battle_start(party, enemy, hint=None)`（battle_render.py L43-47）、`render_battle_round(round_result)`（L74）、`render_battle_end(player, enemy, winner, summary=None)`（L138-143）。
- 取数口径：战报伤害全用 `final_damage`、目标 HP 全用 `target_hp`；**无 `rating`/`damage`/`outcomes` 误用**。引擎 `ActionOutcome` 真实字段（battle.py L219-236 = ok/seq/actor/action_type/target/hit/crit/blocked/raw_damage/final_damage/target_hp/side_effects/message/battle_ended/status）与契约 §5.1 逐字一致；`battle_commands._OUTCOME_FIELDS`（L352-356）亦逐字一致。
- 无裸 send：全部战斗消息经 `BattlePipeline.send → Sender`（L494-517），`dispatch_round`/`_fail`/`_run_battle_action` 无一例外；测试 `test_round_one_message_mock_sender_call_count` 断言 send 调用次数=合并消息数。
- 铁律 9 拼接顺序：`render_battle_round` 按 outcomes 流水先手→击杀（`target_hp<=0` 即查）→后手→结算（L98-128），与回合死亡判定顺序对齐（依赖引擎 outcomes 时序，见 P2-3 守卫说明）。
- 军规 5 结算一次性：`_render_settlement` 仅 `ended=True` 时调用一次（L125-128 / L765-766）；掉落仅 `status=="win"` 输出一次（L778-789）；`render_battle_end` 不重复结算（L152-154）。
- 无幻觉：测试引用的 TC-01~27、M5-01~08 均真实存在于 5e §七 / batch_plan；全部模板文本与 5e 逐字对照通过；无编造拼接行为。

---

## 一、P1（3 项，需决策/修复）

### P1-1 结算内容放置与 5e §6.2 / TC-18 / 3d §3.1 冲突（跨文档）
- 位置：battle_render.py L124-128（`_render_settlement` 挂在当轮消息尾部）、L150-156（`render_battle_end` 只输出 BREP-24/25 不重复结算）；battle_commands.py L635-644（`dispatch_round` ended 后追加 `send_end`）；测试固化为该拆分（test_battle_wiring.py L237-255）。
- 契约要求：5e §6.2「战斗结束消息 = BREP-24 汇总行 + 胜/负/平横幅（BREP-17/18/19）+ 经验掉落（BREP-20）+ 明细入口」；5e TC-18「**同一消息**含 `✅ 战斗胜利！`（BREP-17）+ 汇总行 `战斗结束：胜利｜回合数 5｜…`（BREP-24）+ `✅ 获得 经验 42、金币 25、史莱姆凝胶×2`（BREP-20）」；3d §3.1 承接表「战斗结束 = 1 条（结算：胜负/奖励/掉落）→ BREP-24/25」。
- 现状：结束操作 = 2 条消息——当轮消息含 BREP-15/17/20，结束消息含 BREP-24（+25）。**没有任何一条消息同时含 BREP-17+24+20**，TC-18「同一消息」按字面无法通过；3d 承接表「结束 1 条（结算：胜负/奖励/掉落）」未满足。
- 静态推导：结束操作共 2 条消息，仍在铁律 2「单次操作 ≤1-2 条」预算内，且军规 5「掉落只输出一次」满足——故非功能崩坏，属**契约对齐缺口**。
- 修复建议（二选一，需落 ADR）：(a) 将 `_render_settlement`（BREP-17~20）移入 `render_battle_end`，当轮消息只出行动+击杀（BREP-15），结束消息 = BREP-17~20 + BREP-24 + BREP-25，使结束=1 条且满足 TC-18；或 (b) 在 m5_shared_contract / 5e 记录拆分决策（当轮消息含结算、结束消息仅汇总明细）并改写 TC-18/§6.2 断言口径，同时同步 `test_battle_wiring.py` 注释。

### P1-2 16 行折叠未覆盖战斗轮消息（缺漏维度①）
- 位置：battle_render.py L1022-1043 / L1046-1067（`_fold_item_lines`/`_render_summary_block` 仅服务 BREP-25 明细块）；`render_battle_round`（L74-135）直接 `"\n".join(lines)` **无任何折叠**。
- 契约要求：铁律 11「单条消息 ≤16 行折叠上限（超限按正文尾部→中间过程行折叠 TPL-09；3d §3.2 L184 / 5e TC-06）」；5e TC-06「BOSS 战 45 回合…**单条消息渲染行数 ≤16 行（超限折叠）**」。
- 现状：战斗轮消息（多段连段段行 + 状态差分 + 拦截链 + 结算 + 操作提示行）可超 16 行时不会折叠 → TC-06 对战斗轮消息不满足。
- 修复建议：在 `render_battle_round` 收尾处对 `lines` 做与 BREP-25 同口径的 16 行折叠（尾部→中间过程行 → TPL-09），并把 `_fold_item_lines` 抽象为通用折叠入口复用；补 TC-06 针对战斗轮消息的用例。

### P1-3 连段 segments 未接线，BREP-21/22 在真实管线不可达（缺漏维度①）
- 位置：battle_render.py L811-853（`_render_combo_segments` 以 `outcome.segments` 为唯一开关，缺失→返回 `[]` 走聚合单行）；battle_commands.py L370-402（`_inject_display_outcomes` 仅注入 target/attacker_name/player_max_hp/target_max_hp，**不注入 segments**）；L199-237（`enrich_round_report` 同）。
- 现状（静态推导）：引擎对多段/连段技能在循环内逐段结算但**只产出 1 个聚合 ActionOutcome**（battle.py L1283-1455，L1454 单次 `_action_outcome`；`ActionOutcome` 无 `segments` 字段）；M5-08 接线层也未从伤害构成收集器读取段记录注入 → `outcome.segments` 恒为空 → **生产路径中 BREP-21 段行/ BREP-22 结算行永不触发**，多段技能将以聚合 BREP-02 单行输出，D-5C「每一段伤害一行」与 TC-21/22/23 不满足。
- 修复建议：M5-08 接线层（`enrich_round_report`/`_inject_display_outcomes`）增加从引擎伤害构成统计（stats_collector per-action 段记录，seg 字段）读取并注入 `segments=[{seg,action,final_damage,target_hp,target_max_hp,target,crit,blocked,derived_capped}]` 的步骤；补一条真实引擎多段技能→`dispatch_round`→战报含 `第 N 段` 的集成测试。

---

## 二、P2（4 项，低危/待接）

### P2-1 战斗开始=1 条仅具能力+单测，本批次无调用方
- 位置：battle_commands.py L521-529（`BattlePipeline.send_start`）；测试 test_battle_wiring.py L196-206。
- 现状：`send_start` 已实现且单测通过，但 `dispatch_round`/四指令 handler 均未调用——战斗入口（世界层遭遇）属批次 7 装配待接线（模块头注释「批次7 装配待接线」）。若按「开始各 1 条全覆盖」验收口径，本批次未覆盖。
- 建议：批次 7 装配时接通 `send_start`；或本批次补一条「装配层调用 send_start」的接线冒烟测试。

### P2-2 BREP-25 条目行带 `{序号}.` 前缀，与 5e 正式模板不符
- 位置：battle_render.py L1006-1008（`_summary_item_line` = `{index}. {source} {damage}（{pct}%）`）。
- 现状：5e §6.3 正式模板/TC-26 为 `{来源} {总伤害}（{占比}%）`（无序号）；5e 示例 L338-342 及 5e §6.3「复用 5 条/页分页规则（TPL-07 `{序号}.`）」自带序号——文档内部不一致，实现跟随示例+TPL-07 列表惯例。
- 建议：同步 5e 注册表正式模板加 `{序号}. `，消除文档内不一致（实现本身合理）。

### P2-3 render_battle_round 无死亡防御性守卫
- 位置：battle_render.py L98-117。
- 现状（静态推导）：先手击杀后若引擎仍产出后手 outcome（或回合开始即死仍产出玩家行动 outcome），渲染层会照渲——依赖引擎不发（docstring 自述「由引擎 enemy_act 保证，L61 写死」），无自身守卫。
- 建议：加两处轻守卫——玩家分支前查「该目标是否已死」、后手分支前查「怪物已死→跳过反击行」，防引擎时序异常时违反数值层 L61/L49-52 写死语义。

### P2-4 逃跑/道具行动行由 battle_commands 自合成文案（工程补白 2）
- 位置：battle_commands.py L129-131（`TPL_FLEE_OK/FAILED`）、L569（`✅ 你使用了{item_name}`）。
- 现状：5e 25 条注册表无逃跑/道具行动行模板，本层自合成（模块头已显式标注工程补白 2，对齐 P2-8 精神）。属 D-5A「禁止自造句式」下的补白豁免，但文案未登记。
- 建议：在 5e §1.4 注册表或契约 ADR 中补登记（如 BREP-26/27 或注明「本层合成」），固化文案锚点供 CI grep。

---

## 三、缺漏维度点名「应覆盖 X 但未覆盖」

1. **TC-06 / 铁律 11「单条消息 ≤16 行」→ 战斗轮消息**：仅 BREP-25 明细块有折叠（P1-2）。
2. **TC-21/22/23 连段段行/鞭尸/提前结束 → 真实接线**：模板+单测齐备但 segments 未注入，生产不可达（P1-3）。
3. **TC-18/TC-25「同一消息含 BREP-17+24+20」→ 结束消息**：结算与汇总分居两消息（P1-1）。
4. **战斗开始=1 条接线 → 本批次无调用路径**：能力+单测有，装配待批次 7（P2-1）。

## 四、无问题维度确认

- BREP-01~25 全量实装、逐字对照 5e §1.4 通过（BREP-02/09/12/15/20/21/23/24 等抽查全绿；唯一差异=P2-2）。
- BREP-02 HP 后缀 `（{目标} {剩余HP}/{最大HP}）` 保留、`{目标}` 省略降级口径正确（L381，TC-07 逐字）。
- BREP-09 操作提示行含 `/最大` 分母、指令尾 `→ /攻击[技能] /道具 /防御 /逃跑` 逐字（L258-261，TC-05）。
- BREP-15 击杀行紧跟伤害行（L109-112 及连段内 L846-850，TC-16/22）。
- BREP-20 掉落只在结束流程输出一次、多素材 `、` 分隔（L747，军规 5 / TC-18）。
- BREP-21 段号 = 收集器 seg（L834，TC-21/5e §5.1）。
- 军规 5 结算一次性、BOSS 提前结束后续段作废（L851-852，TC-23）、派生封顶附注（L842-843）均落地。
- 一轮=1 条（玩家行动+怪物反击合并）、结束=1 条、单次操作 ≤1-2 条、无裸 send —— 与 3d §3.1 承接表一致（除 P1-1 的结算归属外）。
- 前缀只加首行（M5-01 委托 + `_prefix_free_ns` 防双前缀，battle_commands L254-264）。
- emoji 纪律：全模板唯 ✅/❌ + 排版符号豁免，6 个测试文件均含全量扫描。
- 引擎 ActionOutcome/TurnReport 字段、`final_damage`/`target_hp` 取数、IF30/IF31/IF32 签名——全部与契约逐字一致，无字段幻觉。

---

*审查方法声明：本文档全部结论为静态阅读产出（未运行任何测试/脚本）；P1-1~P1-3 的运行期行为结论均标注「静态推导」，修复后应由回归测试证实。*
