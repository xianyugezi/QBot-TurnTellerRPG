# 审查报告：M6 G3 故障注入之幂等与双扣防护（组B：message_id 幂等/事务/并发）

> - 审查对象：`docs/实现层规划文档.md`【G3】L3460-3463 + §9 风险 L3493 + M6 里程碑 L3481 + G1 L3452；定稿对照【规则】§4.5（L313-326）、【框架】§15.16（L1637）；细化_5d（§5 故障注入 / §6.1 G5-G6 / TC-5d-25~28/34）。
> - 已实现参考（静态审查）：`qbot_rpg/world/battle_boundary.py`、`qbot_rpg/commands/shop_commands.py`、`qbot_rpg/core/shop.py`、`qbot_rpg/storage/repository.py`、`qbot_rpg/storage/connection.py`、`qbot_rpg/commands/sender.py`、`qbot_rpg/commands/battle_commands.py`、`qbot_rpg/world/session.py`、`qbot_rpg/world/snapshot_resume.py`、`tests/unit/test_shop.py`、`tests/unit/test_shop_commands.py`、`tests/unit/test_storage.py`、`tests/unit/test_battle_wiring.py`、`scripts/verify/verify_m4.py`、`scripts/run_all_tests.py`。
> - 方法声明：**本环境无 bash 沙箱，全程未执行任何命令/脚本/验证**；全部运行/接线行为结论为**静态推导**（源码与文档 grep/read 交叉核对得出，未跑测试）。

---

## 0. 一句话结论

**G3 双扣/幂等验收在当前已实现层全面悬空**：幂等键设施（idempotency_keys 表 + repository API）存在但**零消费**，购买结算仍是「内存快照-回滚 + 业务级 tx_id/ledger 幂等」、未包 SQLite 事务，并发双购买的「读-改-写」竞态敞口真实存在；六类故障注入脚本、fault_inject_doublepay/crash/netdrop、verify_m6 全部缺失。G3 设计本身方向正确、与定稿六行一一对应，但**未把前置接线任务写进设计**，且验收②（限购/货币双路径）无载体。

---

## 1. ① 缺漏（幂等/双扣重点）

### 1.1 message_id 幂等键现状 —— 设施在、零接线
- **已有**：`qbot_rpg/storage/schema.py` L79 `idempotency_keys` 复合主键 `(message_id, group_id, player_qid)`；`qbot_rpg/storage/repository.py` L503 `idem_claim`（只查不插，P1-1 已修）、L526 `idem_find`、L752 `write_idem_key`（同事务）、L762 `idem_exists`、L546 `cleanup_idem_keys`（7 天）。幂等键 API 面完备，方向正确。
- **缺口（静态推导）**：全仓 grep `idem_claim|write_idem_key|idem_exists|idem_find|IdemKey` **仅 `storage/repository.py` 自身命中**——无任何指令处理、发送出口、购买/战斗/签到结算路径调用；`qbot_rpg/commands/` 全目录 grep `message_id|event_id|msg_id` **零命中**。即细化_4a F4「指令处理前查幂等键 → 未命中 → 单事务【业务写+幂等键插入】→ COMMIT → 发送」的接线**完全未实现**。

### 1.2 并发两条购买 → 事务下只扣一次 —— 机制缺口
- **已有**：`qbot_rpg/storage/connection.py` L331-368 `tx()` = `BEGIN IMMEDIATE` + 单写连接队列 + `_tx_owner` 嵌套防死锁（原语健全）；`save_player` 单事务 upsert；`save_world_state` CAS（repository L451-494，P0-1 冲突整体 ROLLBACK）。
- **缺口（静态推导）**：购买结算不在该事务内。`qbot_rpg/core/shop.py` `shop_buy`（L1020-1153）是**内存 ctx 快照-回滚**（L1114-1132）+ `tx_id/ledger` 业务幂等（L1026-1031，A1 模式）；docstring（L1023）明言「调用方应包裹 SQLite 事务（存储层）」，但 `qbot_rpg/commands/shop_commands.py` `cmd_buy`（L422-433）**不包任何事务**。快照-回滚只防结算中异常，不防并发。
- **竞态敞口（静态推导）**：若两条并发 /购买 各自 `load_player` 读到相同余额/限购计数，各自在各自 ctx 里扣减后再 `save_player` 覆盖写回 → 货币丢失更新（双买一件只扣一次钱）、限购计数漏加（超限购买）。单写连接队列只串行化 DB 写语句，**不**使读-改-写整体原子——「事务下只扣一次」当前无实现载体。`test_storage.py::test_concurrent_save`（L199-210）是 20 个**不同玩家**并发 save（只证无 BUSY），不是并发双购买。

### 1.3 验收②「双扣防护覆盖限购/货币两条路径」—— 载体缺失
- 现有测试：`test_shop.py::test_tc22_buy_rollback_on_add_failure`（L428，入包失败回滚，内存）、`test_tc23_buy_idempotent_tx`（L439，同 tx_id 重发幂等，断言货币+背包，**未断言限购 personal_buys 计数**）、`test_sell_idempotent_tx`（L536）。均为**内存级、顺序、无 SQLite、无并发、无 message_id**。
- `verify_m4.py` L113「3.2-05 原子防双扣（SQLite 事务回滚 / 会话快照幂等 tx）」映射的正是上述内存测试——「SQLite 事务回滚」claim 与实际（内存快照-回滚）**名不副实**。
- `fault_inject_doublepay.py`（细化_5d §5 L195 定义）**不存在**；限购路径并发双扣无任何测试。

### 1.4 掉线重连 → 玩家数据完好 —— 载体缺失
- **已有**：快照续战基础设施 `qbot_rpg/world/snapshot_resume.py`、`qbot_rpg/core/battle.py` `resume/from_snapshot`（L1721-1822）、细化_1g3 快照 schema。
- **缺口（静态推导）**：`qbot_rpg/world/session.py` `SessionManager` 为**签名存根**（acquire/release/get_active/suspend/restore 全 `NotImplementedError`，L27-40）——单玩家 1 会话互斥/挂起/恢复未实装；`fault_inject_netdrop.py` **不存在**，无断线重连测试。

### 1.5 发送出口 message_id 幂等键现状
- `qbot_rpg/commands/sender.py`（审查范围引用的 `core/message_format/sender.py` **不存在**，实际发送出口为 `commands/sender.py`）：`Sender.send` 只做 CQ 转义/长度分条/失败重试+指数退避（L157-192），**无 message_id 参数、无去重记录、无幂等键调用**。
- 发送出口侧无「已发送记录/去重」能力；幂等键契约（细化_4a IDEM）语义落在「指令处理」而非发送出口（见 2.2）。

### 1.6 执行载体缺失
- 六类故障注入脚本 `tests/fault/fault_inject_{crash,save,reload,formula,doublepay,netdrop}.py` **全部不存在**（`tests/fault/` 目录不存在）。
- `scripts/verify/verify_m6.py` **不存在**（`scripts/run_all_tests.py` L42 `"m6": None` 标「未实现」）。
- `scripts/run_all_tests.py` help（L64）声称支持 `--only fault`，但实现（L75-85）只处理 `MILESTONES`/`LAYER_PATHS`，`fault` **落入全量 else 分支** → 细化_5d §5「由 run_all_tests.py --only fault 统一驱动」承诺落空（静默退化为全量跑）。

### 1.7 「应覆盖 X 但未覆盖」清单（点名）
1. **应覆盖**：message_id 幂等键接入指令处理（`idem_claim`/`write_idem_key` 与业务写同事务）→ **未覆盖**（零消费）。
2. **应覆盖**：购买结算包 SQLite 事务（`repo.tx()` BEGIN IMMEDIATE 内完成 读-校验-扣减-幂等键写-提交）→ **未覆盖**（内存快照-回滚，壳层不包事务）。
3. **应覆盖**：per-player 串行队列（同玩家指令按序处理，【框架】L1606）→ **未覆盖**（`commands/` 无任何队列/串行化）。
4. **应覆盖**：并发两条购买指令 → 货币只扣一次 → **未覆盖**（无并发测试）。
5. **应覆盖**：并发两条购买指令 → 限购 personal_buys 只 +1 → **未覆盖**（test_tc23 未断言限购计数）。
6. **应覆盖**：回复前崩溃（mock 发送出口抛异常）→ 状态回滚/可重试、不双结算 → **未覆盖**（fault_inject_crash.py 缺失，sender 无 message_id）。
7. **应覆盖**：掉线重连 → 玩家数据完好 → **未覆盖**（fault_inject_netdrop.py 缺失，SessionManager 为 stub）。
8. **应覆盖**：验收② 双扣防护覆盖限购/货币**两条路径** → **未覆盖**（无载体）。
9. **应覆盖**：六故障脚本 + verify_m6 + `run_all --only fault` 驱动 → **未覆盖**（全缺失）。

---

## 2. ② 错误（设计 vs 已实现冲突）

- **2.1 P0（冲突/竞态）**：G3 L3462「并发两条购买 → 事务下只扣一次」把「事务」当作**已存在前提**，但购买结算当前不在 SQLite 事务内（见 1.2）。照 G3 直接写并发用例会失败（或被迫降级为顺序重放，如 test_tc23）。G3 未把「购买结算接入 repo.tx() + 幂等键同事务 + per-player 串行队列」列为**前置接线任务**——设计对实现现状的依赖关系缺失。同时细化_4a TC-05 声称「单写队列串行 + 业务状态校验 → 只成交一次」：单写队列只串行 DB 写、不串行内存读-改-写，**该保证的机制在当前购买实现下不成立**（设计链断言与实现语义冲突）。
- **2.2 P1（载体错位）**：G3 L3462「mock 发送出口抛异常 → …不双结算（message_id 幂等）」把幂等键绑在**发送出口**；但细化_4a F4/IDEM-2 的幂等判定在**指令处理入口**（业务事务内写键），发送出口本身无幂等键。设计表述与契约载体不一致——「回复前崩溃不双结算」的真正载体的「业务已提交+幂等键已落（IDEM-2）」，而非发送出口键；应改写为引用 IDEM-2/F4。
- **2.3 P2（澄清性）**：`battle_boundary.try_acquire_lock`（L642-657，纯函数）/`acquire_wild_lock_tx`（L660-679，stub）是**野图实例锁**，与商店购买并发**无关**。若把世界锁当作购买并发载体属错位——G3 文本未误用（未提世界锁），但审查参考把 battle_boundary 列为「并发购买现状」易误导，建议在设计里显式澄清「购买并发不依赖 wild_lock」。
- **2.4 P1（悬空判定）**：已实现无幂等键接线时，G3 验收①「六类故障注入用例全绿且均有断言」（L3463）与 M6 门禁「故障注入六类全绿」（L3481）**悬空**——无脚本、无载体、无 verify_m6。G3 设计未与细化_5d §5 的 `fault_inject_*.py` 载体显式挂钩（缺「载体=fault_inject_doublepay.py」引用）。

---

## 3. ③ 幻觉核查

- **未发现凭空编造的幂等/事务能力**：`idempotency_keys` 表（schema.py L79）、`tx()=BEGIN IMMEDIATE`（connection.py L344）、`idem_claim/write_idem_key`（repository）均真实存在——不是幻觉。
- **半幻觉/超前声明（需修正）**：
  - G3 L3462 行文隐含「发送出口/指令处理已接入 message_id 幂等」——该接线当前不存在，属**把规划能力当现状引用**。
  - 细化_5d §5 L191「message_id 幂等键生效（L366）」（fault_inject_crash 断言前提）把未接线的机制当作**生效前提**——文档级超前声明。
  - verify_m4.py L113「原子防双扣（SQLite 事务回滚）」把内存快照-回滚包装成「SQLite 事务回滚」——claim 与实现不符（名不副实，非纯幻觉）。
- **引用失真（user 提供）**：任务描述「§9 风险 L3493（双扣/崩溃恢复）」——实际 L3493 为风险 #3「指令解析冲突（快捷/别名/会话/紧凑歧义）」；§9 风险表（L3487-3499）8 条中**无任何双扣/崩溃恢复条目**（见 4.1）。

---

## 4. ④ 跨文档一致性

- **4.1 P2 §9 风险表缺双扣/崩溃恢复条目 + 引用失真**：实现层规划 §9（L3487-3499）8 条风险无「双扣/崩溃恢复」；而 G3（L3460-3463）与【规则】§4.5（L313-326）正是为双扣/崩溃恢复设防——**风险登记表未覆盖本组核心风险**。任务引用的 L3493 实为指令解析冲突（引用失真）。
- **4.2 P2 双扣防护双归属**：细化_5d §2.1 L93 把「双扣防护 L323」挂 **M4 指令**（补充引擎覆盖列）+ G5 门禁（L226「双扣并发用例」）；而细化_5d §5/G6（L227「故障注入六脚本全过」）把 fault_inject_doublepay 挂 **M6**。同一能力 M4/M6 双归属，口径不完全一致；且 M4 侧「双扣并发用例」claim 未兑现（verify_m4 只有内存级顺序幂等）。
- **4.3 ✓ 一致面**：G3 L3462 六类故障点与【规则】§4.5 六行**一一对应**；M6 L3481「故障注入六类全绿」与细化_5d G6 一致；G3 验收①「全绿且有断言」与【规则】L326 一致；「掉线重连→玩家数据完好」与【规则】L324 一致；「并发两条购买→只扣一次（限购/货币）」与【规则】L323 及细化_4a TC-05/细化_5d TC-5d-27 同源一致（机制层面缺口见 2.1）。
- **4.4 ✓ 细化_5d 内部一致**：TC-5d-25（--only fault 六脚本全过）、TC-5d-27（双扣并发注入）、TC-5d-28（断网）、TC-5d-34（fault_inject_crash 断言 message_id 幂等去重）互相衔接，但**全部依赖不存在的脚本/接线**。

---

## 5. 分级问题清单（P0/P1/P2 + 定位 + 修复建议）

### P0（2 项——验收悬空/真实竞态，合入/门禁前必清）
| # | 问题 | 定位 | 修复建议 |
|---|---|---|---|
| P0-1 | G3 幂等/事务验收无实现载体：message_id 幂等键零消费 + 购买不包 SQLite 事务 + per-player 队列缺失，「不双结算」「事务下只扣一次」当前不可达成，M6 验收悬空 | 实现层规划 L3462-3463；qbot_rpg/core/shop.py L1020-1153；qbot_rpg/commands/shop_commands.py L422-433；qbot_rpg/storage/repository.py L497-560；commands/ 全目录 | G3 设计显式补「前置接线任务」：①指令入口接入 idem_claim（只查不插）+业务事务内 write_idem_key（IDEM-2）；②购买结算整体搬入 repo.tx()（BEGIN IMMEDIATE 已具备）；③per-player 串行队列（【框架】L1606）。并把载体挂钩 fault_inject_doublepay.py/细化_5d TC-5d-27 |
| P0-2 | 并发双购买「读-改-写」竞态敞口：货币丢失更新 + 限购计数漏加（静态推导）；快照-回滚只防异常不防并发 | qbot_rpg/core/shop.py L1114-1132（内存结算）；qbot_rpg/commands/shop_commands.py cmd_buy 不包事务；细化_4a TC-05 声称的机制不成立 | 购买结算 = repo.tx() 内「读余额/限购/库存 → 6 步校验 → 扣减 → write_idem_key → COMMIT」（失败整单回滚）；或同玩家指令串行队列；补并发双购买真并发测试（asyncio.gather 同 player、共享 repo） |

### P1（5 项——重要缺漏/载体错位）
| # | 问题 | 定位 | 修复建议 |
|---|---|---|---|
| P1-1 | 验收②「双扣防护覆盖限购/货币两条路径」无载体：fault_inject_doublepay.py 缺失；test_tc23 未断言限购计数；限购路径并发双扣零测试 | 实现层规划 L3463；tests/unit/test_shop.py L439-448；细化_5d L195/TC-5d-27 | 新增 fault_inject_doublepay.py：并发双购买断言货币恰扣一份 **且** personal_buys 计数恰 +1（两条路径各断言）；test_tc23 补限购计数断言 |
| P1-2 | 「掉线重连→玩家数据完好」无载体：fault_inject_netdrop.py 缺失；SessionManager（会话互斥/挂起/恢复）为签名存根 | 实现层规划 L3462；qbot_rpg/world/session.py L27-40；细化_5d L196/TC-5d-28 | M6 前置实装 SessionManager（sessions 表 PK=player_qid 互斥已就位）；新增 fault_inject_netdrop.py 断言重连后快照续战数据完好 |
| P1-3 | 「回复前崩溃→不双结算」无载体：fault_inject_crash.py 缺失；sender.py 无 message_id 幂等键；无 mock 发送出口抛异常测试 | 实现层规划 L3462；qbot_rpg/commands/sender.py L157-192；细化_5d L191/TC-5d-34 | 前置幂等键接线（P0-1）后新增 fault_inject_crash.py：mock 发送出口抛异常 → 断言业务已提交+幂等键已落（IDEM-2）、同 message_id 重发不双结算 |
| P1-4 | 幂等载体错位：G3 把 message_id 幂等绑「发送出口」，与细化_4a IDEM-2/F4（指令处理入口、幂等键与业务写同事务）不一致 | 实现层规划 L3462；细化_4a §4.1 F4/L288-290 | G3 文案改为引用细化_4a IDEM-2/F4（业务事务内写键），明确「发送出口」仅是崩溃注入点、非幂等键载体 |
| P1-5 | 执行载体缺失：verify_m6.py 不存在；run_all_tests `--only fault` 无效（fault 落全量分支）；六故障脚本全缺 | scripts/verify/（无 verify_m6）；scripts/run_all_tests.py L64/L75-85；细化_5d §5/L227 | 补 verify_m6.py（114 条）+ 六 fault_inject_*.py + run_all_tests 支持 `--only fault`（修复 help 与实现不一致） |

### P2（4 项——引用/一致性/名实）
| # | 问题 | 定位 | 修复建议 |
|---|---|---|---|
| P2-1 | §9 风险表无双扣/崩溃恢复条目；任务引用「L3493 双扣/崩溃恢复」失真（实为指令解析冲突） | 实现层规划 L3487-3499（8 条风险） | §9 增补「并发双扣/崩溃恢复」风险行并登记 G3/细化_4a 对策；审查引用改用正确行号 |
| P2-2 | 双扣防护 M4/M6 双归属口径不一；verify_m4「3.2-05 原子防双扣（SQLite 事务回滚）」名不副实（内存快照-回滚） | 细化_5d L93/L226 vs L195/L227；verify_m4.py L113 | 统一双扣防护归属（M6 故障注入载体为准，M4 仅业务级幂等），verify_m4 文案改「进程内快照-回滚 + tx_id 幂等」 |
| P2-3 | 审查范围引用路径漂移：`core/message_format/sender.py` 不存在，实际为 `commands/sender.py` | qbot_rpg/commands/sender.py | 引用与计划文档统一为 commands/sender.py |
| P2-4 | 世界锁（wild_lock）与购买并发无关，作为「并发购买现状」参考易误导 | qbot_rpg/world/battle_boundary.py L642-679 | 设计/审查口径澄清：购买并发不依赖 wild_lock，依赖事务+串行队列（P0-1） |

---

## 6. 结论汇总

- **P0 = 2，P1 = 5，P2 = 4（共 11 项）**。
- **幻觉**：未编造已有幂等/事务能力（表与 BEGIN IMMEDIATE 真实存在）；但存在 3 处「把待办当现状/把内存回滚当 SQLite 事务」的半幻觉声明（G3 行文、细化_5d L191、verify_m4 L113）。
- **最要紧**：G3 是 M6 规划任务，方向正确，但**验收落地依赖的三条前置接线（幂等键入指令入口、购买入 SQLite 事务、per-player 串行队列）未在设计里点名**，导致「不双结算/只扣一次/限购+货币双路径」在已实现层全部悬空；并发双扣竞态敞口是静态推导可确认的真实风险。
