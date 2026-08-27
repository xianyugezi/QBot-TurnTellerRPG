# 审查报告 · M6 设计批4 组B：G2 测试体系之往返硬约束与覆盖率

> 审查对象：docs/实现层规划文档.md 【G2】L3455-3458（往返/必测表/性质用例）+【G4】L3465-3468（覆盖率）
> 定稿对照：【规则】§四.2/§四.3/§四.6（开发规则文档.md L287-333）；【框架】§13（RPG回合制框架设计文档.md L1527-1561）
> 已实现参考：qbot_rpg/storage/repository.py + migrations.py；tests/unit/test_storage.py；test_battle_*/test_marks/test_combo/test_damage 等；scripts/verify/verify_m0~m5.py；scripts/run_all_tests.py；docs/细化/细化_5d_测试体系总纲.md
>
> **审查方式：纯静态（read/glob/grep），未运行任何命令/脚本。所有「运行行为结论」均标「静态推导」。**
> 门控档位：**full 档**（j-space；加载 broadcast.md + introspection.md 承载跨文档一致性与幻觉核查）。

---

## 〇、结论汇总

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 未发现会造成数据丢失/主动错误的活缺陷；硬约束缺漏集中在 P1，将阻断 M6 G5/G6 门禁 |
| **P1** | **6** | P1-1 每类快照往返 / P1-2 版本迁移往返 / P1-3 覆盖率门禁未实算+口径未定义 / P1-4 必测表三项未覆盖 / P1-5 1000 组性质用例缺失 / P1-6 伪托基准（幻觉） |
| **P2** | **4** | battle 措辞过时；「G2」跨文档三义；必测表枚举漏 damage；M6 目标文件缺位 |

Top3 问题（详见文末回复）：
1. **存档往返「每类快照完全一致」仅 Player 级 1 条 generic round-trip，五类快照中调合会话/商店限购零往返测试，且全部未走 Repository 持久化路径**——§4.3 硬约束（【规则】L301）/G2 验收②（规划 L3458②）/细化_4a TC-12 同时落空。
2. **覆盖率 ≥80% 实为「零实算」**：verify_m0 §5 简版后从未按「M1 恢复」兑现（verify_m1~m5 均无覆盖率段），run_all_tests 阶段3 只打印一行且输出「全绿（exit 0）」；G4 验收①②、细化_5d TC-5d-15/17、M6 L3481 依赖全部悬空。
3. **伪托基准（幻觉）**：verify_m0 L157 声称「按 5d §7.4 显式标注」而 §7.4 决策记录仅 D1-D4 无此项；run_all_tests L102 引用已被 verify_m0 删除的「估算口径」术语——覆盖率降级属 5d L13 明令必须登记的偏离，实际未登记。

---

## 一、维度① 缺漏（往返 + 覆盖率 + 必测表）

### 1.1 存档往返「每类快照完全一致」现状：仅 Player 级，未达每类快照（P1）

- **现状**：`tests/unit/test_storage.py` 仅 `test_roundtrip`（L36-44）调用 `Repository.db_roundtrip(player)` 做**单个 Player 的 generic 往返**；`repository.py` 的 `codec_roundtrip`/`db_roundtrip`（L623-646）也只支持 Player 类型。**无任何「按快照类逐一 序列化→反序列化→比对」的用例**。
- 五类快照（【规则】§4.3 L301：战斗快照/调合会话/状态印记/连段/商店限购）逐类现状：
  - **战斗快照** ✅ 引擎层：verify_m1 `t_1g3_snapshot_roundtrip`/`t_1g3_random_seed_resume`（L205-223）、test_battle_engine `test_b5_snapshot_json_roundtrip`（L86）、test_m43_regression（快照完整性）。
  - **状态印记** ✅：test_marks `test_m07_snapshot_roundtrip_json`（L89）。
  - **连段** ✅：test_combo `test_p1_step_index_roundtrip`（L191）。
  - **调合会话** ❌ **零往返测试**（无任何 alchemy/synthesis session roundtrip）。
  - **商店限购** ❌ **零往返测试**（test_shop 仅覆盖 `personal_buys` 计数/整单拒绝语义，无 限购快照 序列化→反序列化→比对；test_shop L440 的 tx_id 重发是幂等不是限购快照往返）。
- **且全部未过存储持久化路径**：上述往返均为引擎/dataclass 层 `to_snapshot/from_snapshot`；`Repository.load_session`（repository.py L408-425）对 payload 只做 `_jloads` 还原为裸 dict，**从不重建为类型化快照**，也无 `save_session→load_session→比对` 的存储层往返断言。
- **【规则】§4.3 L302 的「删除配置后读档按无效果/无链/无印降级不抛异常」**：全仓测试 **0 命中**。
- 对应硬约束要求：G2 验收②（规划 L3458②「往返测试对每类快照断言完全一致」）、细化_4a TC-12（L400「对每类快照……序列化→反序列化→比对（tmp_path 库）」）、细化_5d TC-5d-03（L250）、【规则】§4.3 L301（标注「硬约束」）。

### 1.2 版本迁移 round-trip 缺失，且 G2 设计未承接 §4.3 L303（P1）

- **现状**：`migrations.py` 的 `DB_SCHEMA_VERSION=1`、`MIGRATION_STEPS=[]`（L31/L37）——**迁移链为空，无任何真实迁移步**。`test_storage.py` 的迁移用例（L215-342）全部是**链完整性/备份失败的失败路径**（noop 步 + monkeypatch），**无一条「构造旧 schema_version 存档 → 迁移 → 断言字段级缺补默认/多忽略」的成功路径用例**，亦无「迁移后快照往返」。
- **G2 设计缺漏**：G2 的【定稿依据】引用了【规则】§四.3（含 L303 版本迁移条款），但【实现要点】L3457 只写「存档往返……每类快照」，【验收标准】L3458 只写「往返测试对每类快照断言完全一致」——**设计层面把 §4.3 L303 的版本迁移测试整条漏掉了**（对应细化_5d TC-5d-35 L292、细化_4a TC-13/14 L364/396 同步落空）。
- **往返与迁移链衔接**：G2 的「往返」与 migrations 迁移链**无任何衔接**（无迁移后快照往返断言）。verify_m0 §5 `old_schema` 已自述「迁移链 M6 覆盖」（verify_m0 L66-68/L94-98），即把迁移链功能延迟到 M6——但 G2 是 M6 的任务组之一，设计内未把「迁移链 + 往返」闭环写进 G2 验收。

### 1.3 必测表六项逐项覆盖现状：levelup/inventory/equipment 三项缺（P1）

【规则】§4.2（L287-297）七模块必测场景，G2 验收①（L3458①）取其中六项（battle/levelup/inventory/equipment/worldtime/storage），现状：

| 必测项 | 现状 | 判定 |
|---|---|---|
| battle.py | 状态机合法流转（test_battle_engine）/非法流转拒绝（test_battle_boundary）/丢失判定链含时段结束（test_decide_lost_chain）/中断恢复续打（test_snapshot_resume、test_chase_resume）/僵尸回收 30 天（test_should_zombie_recycle） | ✅ **全覆盖** |
| levelup.py | `core/levelup.py` **全部方法 `raise NotImplementedError`（占位）**；无 test_levelup.py；全仓无「0 经验/满级不增长/升级回满 HP/MP」用例（test_basic_commands 仅渲染「已满级」头） | ❌ **未覆盖** |
| inventory.py | `core/inventory.py` **占位未实装**；无 test_inventory.py；堆叠上限/绑定/同类型限次等语义仅在 shop/reward/命令渲染层间接出现 | ❌ **引擎级未覆盖** |
| equipment.py | 互斥环**加载期拦截** ✅（test_dsh_regress L27-44、test_content L207）；但部位占用/数量校验/运行时互斥（engine 占位未实装）无测试 | ⚠️ **部分**（仅加载期） |
| worldtime.py | 出没时段跨天（test_spawn L110）/刷新补刷/离线封顶（test_dayroll、test_time_*、test_worldtime_changes） | ✅ 已覆盖 |
| storage.py | 事务 ✅（test_purchase_rollback）/并发写队列 ✅（test_concurrent_save）/幂等 ✅/回收 ✅；**崩溃恢复 ❌、自动保存防抖合并 ❌、每类快照往返 ❌（见 1.1）** | ⚠️ **部分** |

- **结论**：levelup/inventory 完全缺、equipment 缺运行时侧、storage 缺 3/5 子项。G2 验收①「本路覆盖 levelup/inventory 接口/equipment 部位/storage 往返」在**当前测试面不成立**，且设计内**未为这三项登记任何 defer**（对比：battle 显式 defer 了；levelup 却未 defer）。
- **里程碑归属冲突（跨文档）**：细化_5d L94 把 levelup.py 必测场景挂 **M5**（verify_m5 覆盖），而 G2（M6 任务组）L3458① 又写「本路覆盖 levelup 接口」——**同一必测项被两文档分派到不同里程碑，且两者当前都未兑现**。

### 1.4 覆盖率 ≥80%：实算/阈值断言/报表归档全缺失，verify_m0 简版后未恢复（P1）

- **verify_m0 §5（L149-157）**：只检测 `coverage` 包是否安装并打印提示；**从不执行核算、从不比对 80% 阈值、不影响退出码**。其自述「M1 恢复 ≥80% 硬门禁」。
- **恢复情况（静态推导）**：verify_m1（L27-33 COVERAGE 仅为「TC 计数声明」dict，无 coverage 段）、verify_m2/m3/m4/m5（grep 无 coverage 核算段）——**「M1 恢复」从未兑现，M0~M5 六脚本无一实算覆盖率**。
- **run_all_tests.py L102**：阶段3 仅 `print("\n[阶段 3] 覆盖率核算（engine/+content/ ≥80%）：见 verify_m0 §5 估算口径")` ——不核算、不比对、不归档、不影响退出码（L104-107 结论仍可输出「全绿（exit 0）」）。细化_5d §3.2 步骤8 要求「覆盖率核算 → 输出覆盖率报表」（L140）、TC-5d-15（L267）要求「末尾输出 engine/+content/ 行覆盖率并与 80% 阈值比对」——**均未实现**。
- **G4 验收②「覆盖率达标报告归档」（规划 L3468②）、G1 门禁「覆盖率核算 ≥80%」（细化_5d L222）、TC-5d-17（L274）、M6 L3481「覆盖率 engine/content ≥80%」**：全部依赖该装置，装置不存在 → 均悬空。

### 1.5 性质用例 1000 组不变量：无 property-based 落地（P1）

- G2 验收③（L3458③）「性质用例 1000 组不变量全绿」、【规则】§4.4 L309「随机 1000 组属性 → 断言不变量（伤害≥1/区间/会心率≤95%）」、细化_5d TC-5d-04（L251）。
- **现状（静态推导）**：test_damage.py 仅确定性边界（test_t01~t27，固定输入）；verify_m1 `t_1a_random_injected`（L64-68）只做 5 个值同种子复现，**非性质用例**。全仓无 `for … in range(1000)` 的伤害不变量性质循环（唯一 range(10000)/range(1000,1020) 是天气池均匀性 test_weather_pool L191 与天气确定性 test_m43_regression L154，与伤害不变量无关）。

### 1.6 「应覆盖 X 但未覆盖」清单（点名）

1. 应覆盖「**每类快照存储层往返（战斗/调合会话/状态印记/连段/商店限购 经 Repository 持久化路径）**」但未覆盖（调合会话/商店限购连引擎层往返都没有）。
2. 应覆盖「**删除配置后读档按无效果/无链/无印降级不抛异常**」（§4.3 L302）但未覆盖。
3. 应覆盖「**版本迁移：构造旧 schema_version 存档 → 迁移 → 字段级缺补默认/多忽略 + 迁移后快照往返**」（§4.3 L303 / TC-5d-35）但未覆盖。
4. 应覆盖「**levelup 经验曲线边界（0 经验/满级不增长/升级回满 HP/MP）**」但未覆盖（引擎占位）。
5. 应覆盖「**inventory 堆叠上限/道具不耗回合/药剂同类型回合限次 1/绑定不可赠送掉落**」但未覆盖（引擎占位）。
6. 应覆盖「**equipment 部位占用/数量校验/运行时互斥**」但未覆盖（仅加载期互斥环校验）。
7. 应覆盖「**storage 崩溃恢复 + 自动保存防抖合并**」（storage 必测场景 L297）但未覆盖。
8. 应覆盖「**覆盖率 engine/+content/ ≥80% 实算 + 阈值断言 + 报表归档**」但全链路未实现。
9. 应覆盖「**性质用例随机 1000 组不变量**」但无 property-based 落地。

---

## 二、维度② 错误（设计/实现错位）

### 2.1 G2 验收①「battle 留后续路」与已实现 battle 测试：不构成硬矛盾，但措辞过时（P2）

- **静态推导结论**：battle 必测场景**已被大量现有测试全覆盖**（见 1.3 battle 行），verify_m1 即「G2 战斗门禁」。因此「battle 留后续路」若按字面理解为「battle 尚无测试、待后续路补」，与仓库现状**不符**——battle 由路1（战斗怪物路线/细化_1g3）已交付。
- 判定：这是**跨路边界措辞的时效性陈旧**（写于本路尚未覆盖 battle 时），不是逻辑矛盾。风险在于：M6 G2 验收时若照此验收标准判定，「battle 项」既不能说本路覆盖、也不能说后续路交付（后续路已完成但设计未回写），验收判定将无所适从。
- **修复建议**：L3458① 括注改为「battle 已由路1 交付（test_battle_engine/test_battle_boundary/test_snapshot_resume + verify_m1 G2 门禁），本路不重复覆盖」；或删去括注。

### 2.2 往返测试与 migrations.py 迁移链：无衔接（已并入 P1-2，见 1.2）

- `MIGRATION_STEPS=[]` + 无迁移后快照往返 → G2 的「往返」与「迁移」两条线各自孤立，M6 若直接验收「往返」而不验收「迁移后往返」，会漏掉迁移引入的字段漂移。G2 设计应把 §4.3 L303 的迁移 round-trip 显式纳入本路验收（当前设计 L3457-3458 完全未提）。

### 2.3 覆盖率口径：engine/+content/ 目录映射与「各自 vs 合计」均未定义（P1，并入 P1-B）

- **目录映射**：文档口径写 `engine/`（【规则】L333、G4 L3467、M6 L3481、细化_5d L106/L140），但仓库实际有 **qbot_rpg/core/**（battle/damage/levelup/inventory/equipment…）与 **qbot_rpg/engine/**（time_query/weather_*/condition_engine/worldtime…）两个目录；verify_m0 L152 示例命令只 `--source=qbot_rpg/core,qbot_rpg/content`，**把 engine/ 隐式映射为 core/ 并漏掉 qbot_rpg/engine/**，全文档未定义「engine/ 指哪个目录集」。
- **各自 vs 合计**：「engine/ + content/ 行覆盖 ≥80%」可读作 (a) engine/ 与 content/ **各自** ≥80%，或 (b) 二者**合计** ≥80%；verify_m0 示例 `coverage report`（单一百分比）暗示合计。G4/M6/细化_5d 均未明示，**验收无法对齐**。
- 此为设计文档自身的歧义（非实现侧独有），故 G4 与细化_5d 文本虽一致（见维度④），但「一致地歧义」——需在设计层定死口径。

---

## 三、维度③ 幻觉（编造现有能力 / 伪托基准）

### 3.1 verify_m0.py L156-157「P1-2 按 5d §7.4 显式标注」——伪托基准（P1）

- verify_m0 L157 原文：「coverage 未装：覆盖率未核算（简版口径，M1 恢复 ≥80% 硬门禁——**P1-2 按 5d §7.4 显式标注**，不暗示已达标）」。
- **核查**：细化_5d §7.4 决策记录（L295-302）**仅有 D1~D4 四条，无任何「M0 覆盖率简版口径/降级」条目**。所谓「按 §7.4 显式标注」指向的登记**不存在**。
- 性质判定：这是**伪托基准**——修复 P1-2 时本应「按 §7.4 在 5d 决策记录 D5 显式登记」（审查_M0复查_tests_m0 L61 的建议），但 D5 **从未补写**，verify_m0 反而把「已按 §7.4 标注」写成了事实。违反细化_5d L13 变更纪律（「任何偏离【规则】之处必须写入 §7.4 决策记录」）：覆盖率门禁未实算是偏离 L333 的实质变更，**未登记**。
- 修复：在 细化_5d §7.4 补 D5（M0~M5 覆盖率以简版口径验收、M6 恢复 ≥80% 硬门禁 + 依据 + 影响用例 TC-5d-15/17），并将 verify_m0 该注释改为引用真实 D5；或删去「按 §7.4 显式标注」字样。

### 3.2 run_all_tests.py L102「覆盖率核算……见 verify_m0 §5 估算口径」——编造核算 / 引用已删术语（P1）

- run_all_tests L102 以**进行时「覆盖率核算（engine/+content/ ≥80%）」**输出阶段标题，实际该行**不核算任何数字**，随后 L104-107 仍可能输出「全绿（exit 0）」——在唯一官方回归入口（细化_5d L118「唯一官方回归入口」）上**编造了「覆盖率核算」能力的存在**。
- 且「估算口径」是 verify_m0 上一轮修复中**明确删除并定性为「无据声明」**的术语（verify_m0 L153「原『估算口径』系无据声明」），run_all_tests 仍引用之 → **对已删除/已否定的基准做悬空引用**。
- 修复：改为「覆盖率未核算（简版）：engine/+content/ ≥80% 门禁待 M6 恢复」或真实接入 coverage 核算并纳入退出码（配合 P1-B）。

> 注：维度③ 中「编造**已有**覆盖率实算结果（如直接打印 ≥80%）」的极端形态未发现——verify_m0 至少明确标注了「未核算」。当前幻觉形态是「伪托登记基准 + 悬空引用已删术语 + 入口脚本标题冒充核算」。

---

## 四、维度④ 跨文档一致性

### 4.1 覆盖率口径文本一致性：四文档同文，但共同歧义且共同未落地（P1）

- G4 L3466-3468「engine/ + content/ 行覆盖 ≥80%」、【规则】L333 同文、M6 L3481「engine/content ≥80%」（缩略去加号/斜杠，语义同）、细化_5d L106/L140/L222/L267 同文 → **文本口径一致，无 G2↔G4 冲突**（G2 本身不涉覆盖率，职责分工正确）。
- 但四者**共同未定义**「各自 vs 合计」与「engine/ 目录映射」（见 2.3），且**共同未被实现承接**（见 1.4）——文本一致 ≠ 可验收。这是「设计自洽但实现缺位」，归入①缺漏而非④冲突。

### 4.2 「G2」跨文档三义命名冲突（P2）

- 规划文档 §7 L3455「**【G2 测试体系**（分层+确定性+往返）任务」vs 细化_5d §6.1 L223「**G2 战斗（M1）** 门禁」vs M6 行 L3481「F5-F6、**G2-G4**（指规划文档任务组）」——**同一「G2」在不同文档是三个不同实体**。M6 行引用的「G2-G4」是任务组引用，而细化_5d 的 G2 是门禁名，索引脆弱、易误读。建议规划文档任务组改 `T-G2` 前缀或在 §8 注明「与细化_5d 门禁 G 编号无关」。

### 4.3 其余一致性核对（✅）

- G2 必测表六项（L3458①）与【规则】§4.2 七模块：**缺 damage 一项**（P2，见 4.4），其余五项名称一致。
- G2【定稿依据】L3456 引 §四.1/§四.2/§四.3/§四.4：引用章节真实存在、无错号。
- 细化_5d L222 G1「覆盖率核算 ≥80%」与 verify_m0「简版」：verify_m0 已是「显式标注简版」→ 属推进期降级而非文本冲突（但缺 §7.4 登记，见 3.1）。
- verify_m0 §5「M1 恢复硬门禁」vs verify_m1~m5 无覆盖率段：**承诺与兑现脱节**（见 1.4）。

### 4.4 必测表枚举省略 damage（P2）

- G2 L3458① 枚举六项（battle/levelup/inventory/equipment/worldtime/storage），【规则】§4.2 实为**七行含 damage.py**。省略 damage 合理（§4.4 三型公式用例承接），但文档未注明，读者易误以为 damage 必测被漏。建议 L3458 加注「damage 由 §4.4 三型用例承接」。

---

## 五、P1 / P2 分级明细（文件 + 行号 + 修复建议）

### P1-1　存档往返「每类快照完全一致」未达硬约束
- 证据：tests/unit/test_storage.py L36-44（仅 Player 级）；repository.py L408-425（session payload 还原为裸 dict）/L623-646（round-trip 仅支持 Player）；调合会话/商店限购**零往返测试**；§4.3 L302 降级读档 0 命中。
- 落空条款：规划 L3458②、【规则】§4.3 L301-302（硬约束）、细化_4a TC-12 L400、细化_5d TC-5d-03 L250、G5 门禁「存档往返全快照类」（细化_5d L226）。
- 修复：① 为 战斗/调合会话/状态印记/连段/商店限购 五类各建 `save_session→load_session→逐字段比对` 的存储层往返用例（tmp_path 库）；② 补「删除配置后读档降级不抛异常」用例；③ G2 验收② 保持「每类快照断言完全一致」，并把 调合/商店 的载体明确到对应 verify 里程碑（M4/M5）。

### P1-2　版本迁移 round-trip 缺失，G2 设计未承接 §4.3 L303
- 证据：migrations.py L31/L37（DB_SCHEMA_VERSION=1、MIGRATION_STEPS=[]）；test_storage.py L215-342（仅失败路径）；规划 L3457-3458 无迁移条款。
- 落空条款：细化_5d TC-5d-35 L292、细化_4a TC-13/14 L364/L396。
- 修复：G2 L3457 实现要点增补「版本迁移：构造旧 schema 存档→迁移→断言字段级缺补默认/多忽略 + 迁移后快照往返」；补成功路径迁移用例（真实 STEP 或契约替身）；迁移链与往返在 M6 显式闭环。

### P1-3　覆盖率 ≥80% 硬门禁全链路未实算/未恢复/未归档 + 口径未定义
- 证据：verify_m0 L149-157（仅打印）；verify_m1~m5 无覆盖率段；run_all_tests L102（仅打印，结论仍「全绿」）；规划 L3468②/L3481、细化_5d L140/L222/L267/L274。
- 修复：① 接入 `coverage run --source=<engine目录集>,qbot_rpg/content` + 阈值比对 + 不达标 exit≠0；② 在 G4/M6/细化_5d **明确定死口径**：engine/ 目录集（建议 `qbot_rpg/core + qbot_rpg/engine`）与「各自 ≥80% or 合计 ≥80%」；③ 报表归档落盘 docs/；④ 更新 M6 L3481 措辞与 4.6 一致。

### P1-4　必测表 levelup/inventory/equipment 三项未覆盖，G2 验收① 与现状不符
- 证据：core/levelup.py L22-26、inventory.py L21-28、equipment.py L23-30 全 NotImplementedError；无 test_levelup/test_inventory/test_equipment；规划 L3458①。
- 修复：G2 L3458① 改为显式登记「levelup/inventory/equipment 引擎随 M4/M5 实装后由对应 verify 覆盖（细化_5d L94 levelup 挂 M5）」，删除「本路覆盖」表述或与细化_5d 里程碑归属对齐后按计划补测。

### P1-5　性质用例随机 1000 组不变量缺失
- 证据：test_damage.py 仅 test_t01~t27 确定性；verify_m1 L64-68 仅同种子 5 值复现；无 property 循环。
- 落空条款：规划 L3458③、【规则】§4.4 L309、细化_5d TC-5d-04 L251。
- 修复：补 `for i in range(1000)` 随机属性注入 → 断言 伤害≥1 / 非会心 ∈[0.95,1.05]×基础 / 会心率 ≤95% 的性质用例（挂 test_damage.py 或 verify_m1 补充段）。

### P1-6　伪托基准（幻觉）＋覆盖率降级未按 §7.4 登记
- 证据：verify_m0 L156-157（「按 5d §7.4 显式标注」）；细化_5d §7.4 L295-302 仅 D1-D4；run_all_tests L102（「估算口径」引用已删术语 + 标题冒充核算）。
- 修复：细化_5d §7.4 补 D5 登记（M0~M5 简版、M6 恢复 + 影响用例）；verify_m0/run_all_tests 注释改为引用真实 D5 或删去；run_all_tests 阶段3 改为「未核算（简版）」输出。

### P2-1　「battle 留后续路」措辞过时（见 2.1）
- 修复：L3458① 括注改为「battle 已由路1 交付（verify_m1 G2 门禁 + test_battle_* 现成），本路不重复覆盖」。

### P2-2　「G2」跨文档三义命名冲突（见 4.2）
- 修复：规划 §7 任务组编号加 `T-` 前缀（T-G2 测试体系），§8 M6 行引用同步，并在文内注明与细化_5d 门禁 G 编号无关。

### P2-3　必测表枚举漏 damage（见 4.4）
- 修复：L3458① 加注「damage 由 §4.4 三型用例承接」。

### P2-4　M6 目标文件缺位（推进期占位标注）
- 证据：scripts/ 无 verify_m6.py/verify_datapack.py/故障注入六脚本；run_all_tests L42 m6=None（已标注）；细化_5d 附录 A L311-314 宣称「7 脚本/1 datapack/6 故障注入」齐全。
- 修复：细化_5d 附录 A 加「M6 推进期未落盘」标注，避免与现状冲突（其余已由 run_all_tests 显式标注）。

---

## 六、证据索引（行号对照）

| 引用 | 位置 |
|---|---|
| G2 设计 | 实现层规划文档.md L3455-3458 |
| G4 设计 | 实现层规划文档.md L3465-3468 |
| M6 行 | 实现层规划文档.md L3481 |
| 必测表 | 开发规则文档.md L287-297（七模块） |
| 4.3 往返硬约束 | 开发规则文档.md L299-304（L301 每类快照 / L302 降级 / L303 版本迁移 / L304 random_seed） |
| 4.4 性质用例 | 开发规则文档.md L308-311（L309 随机 1000 组） |
| 4.6 覆盖率 | 开发规则文档.md L333 |
| 【框架】§13 | RPG回合制框架设计文档.md L1527-1561 |
| 细化_5d 往返/必测/覆盖率 TC | 细化_5d L249-250 / L267 / L274 / L292；L222-227 门禁；L295-302 §7.4 |
| storage 往返实现 | qbot_rpg/storage/repository.py L408-425、L623-646 |
| 迁移链 | qbot_rpg/storage/migrations.py L31/L37 |
| 往返测试现状 | tests/unit/test_storage.py L36-44（仅 Player 级） |
| 覆盖率装置现状 | scripts/verify/verify_m0.py L149-157；scripts/run_all_tests.py L102 |
| 必测表引擎占位 | qbot_rpg/core/levelup.py L22-26；inventory.py L21-28；equipment.py L23-30 |
| battle 已覆盖 | tests/unit/test_battle_engine.py、test_battle_boundary.py L53/L156、test_snapshot_resume.py、verify_m1.py L194-223 |
| 快照往返已覆盖类 | test_marks.py L89、test_combo.py L191、test_battle_engine.py L86 |

---

*审查方式声明：本报告全部结论来自静态阅读（read/glob/grep），未运行任何命令/脚本/测试；所有「运行行为结论」（如「未覆盖」「0 命中」「无 1000 组循环」）均为静态推导。*
