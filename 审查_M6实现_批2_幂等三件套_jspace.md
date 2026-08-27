# 审查报告 · M6 实现层批2（幂等事务三件套）

> 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试；凡涉运行行为结论均标注「静态推导」）。
> 审查对象：`qbot_rpg/commands/processing.py`（指令处理入口 + per-player 串行队列）、`qbot_rpg/commands/shop_tx.py`（购买结算入事务）、`qbot_rpg/world/battle_boundary.py`（聚焦 `settle_exit_idempotent` L821-884 实装段）、`tests/unit/test_idem_processing.py`、`tests/unit/test_per_player_queue.py`、`tests/unit/test_shop_double_pay.py`。
> 契约基准：`docs/细化/细化_M6_幂等事务三件套.md`（D2：IDEM-1~8/TC-IDEM-01~06、SEG-1~9/TC-SEG-01~05/§2.5 双扣两路径、POOL-1~6/TC-POOL-01~04、§四 P 项承接）；`docs/细化/细化_M6_接线闭环总纲.md` ADR-05/06/12。

---

## 〇、结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 三件套载体与 D2 契约主体一致，双扣防护/幂等链路/队列串行化的核心机制经静态核验成立 |
| **P1** | **2** | ①shop_tx 背包多实例回写计数膨胀（静默数据损坏）；②SEG 载体未接到线上 `/购买`（cmd_buy 仍无事务，接缝风险） |
| **P2** | **12** | 见 §四，含接口语义不一致、组哨兵双定义、清理无调度、部分 TC 分支未覆盖等 |

**总体判断**：批2 交付物（process_message + PerPlayerQueue + shop_tx 载体 + settle_exit_idempotent 实装 + 三份单测）与 D2 契约的**结构性要求全部对齐**——幂等载体在指令入口、只查不插、同事务写键、购买事务内读、BEGIN IMMEDIATE 串行化、per-player 队列、双扣两路径断言载体均落地。主要风险集中在**边缘数据路径**（背包多实例）与**尚未接线的线上路径**（cmd_buy / 装配层批次6/7 接缝），需显式登记防静默遗忘。

---

## 一、维度①：D2 契约落地核验（IDEM / SEG / POOL）

### 1.1 IDEM 件套（幂等键入指令入口）——逐条核验

| 规则 | 落点 | 核验 |
|---|---|---|
| IDEM-1 载体定位 = 指令处理入口非发送出口 | `processing.process_message` L242-281：入口 idem_claim → 入队 → 消费者 tx 内写键 → COMMIT → sender（L191-197）| ✅ 与 ADR-05 一致；发送出口仅 `_run_consumer` 内可选 sender（L192-197），非幂等载体 |
| IDEM-2 键三元组 (message_id, group_id, player_qid) | `process_message` L269-274 构造 `IdemKey`；`IdemKey`（repository.py L273-283）| ✅ 与 schema.py L71-81 复合主键一致；TC-IDEM-03 覆盖不同 player 互不幂等 |
| IDEM-3 只查不插 | 入口 `repo.idem_claim`（processing.py L276）只读；`repository.idem_claim`（L503-524）注释明言「只查不插」| ✅ 无独立事务预插；插入仅经 tx 内 `write_idem_key` |
| IDEM-4 同事务提交 | `_process_one` L215-236：`async with repo.tx()` 内 handler + `write_idem_key` 同一事务 COMMIT | ✅ 幂等键与业务写同事务（静态推导：tx 出口 COMMIT）|
| IDEM-5 命中幂等返回 | 入口命中 → `_replay_reply`（L75-84，ok=False/idempotent=True/send=False）；队列内二次确认命中 → 同（queued=True）| ✅ 业务零执行零发送（send=False）；TC-IDEM-02/03 覆盖 |
| IDEM-6 失败整单回滚 | `_process_one` L237-239 捕获异常转 `_failure_reply`；connection.py tx() L351-357 异常 ROLLBACK | ✅ 无孤儿键（写键与业务写同落同不落）；TC-IDEM-04 覆盖 |
| IDEM-7 7 天清理 | `cleanup_idem_keys`（repository.py L546-560）提供；TC-IDEM-06 直调验证 | ⚠️ 见 P2-3：**无生产调度调用点**（仅测试直调），表会无界增长 |
| IDEM-8 settle_exit_idempotent 实装 | battle_boundary.py L821-884：idem_claim → tx 内 idem_exists → delete_session + write_idem_key → COMMIT | ✅ 存根已实装（【批5A】P1-1 承接）；TC-IDEM-08 四用例覆盖；⚠️ 见 P1-2/P2-1 接缝 |

### 1.2 SEG 件套（购买结算入 repo.tx()）——逐条核验

| 规则 | 落点 | 核验 |
|---|---|---|
| SEG-1 购买结算整体入 repo.tx() | `shop_tx.buy_in_open_tx`（L245-298）在调用方 tx 内：读→校验→扣减→写回；`buy_in_tx`（L301-360）自开 tx | ✅ 载体成立；**但见 P1-2：线上 cmd_buy 未接线** |
| SEG-2 读在事务内 | `buy_in_open_tx` L274-281 用 `tx.fetchone` 重读玩家行/world_stock；`_build_ctx` 玩家态全部事务内重读 | ✅ 不取 load_player 60s 缓存；`test_seg_in_tx_reread_beats_stale_cache` 覆盖 |
| SEG-3 6 步校验链保留 | `shop_buy`（shop.py L1020-1153）原样调用 | ✅ 顺序即提示优先级未重排 |
| SEG-4 内存快照-回滚保留 | shop.py `_snapshot`/`_restore`（L862-871）+ `_SNAP_KEYS`（L144-147）| ✅ 保留为事务内校验层 |
| SEG-5 幂等键与购买同事务 | `buy_in_tx` L352-355 / `_process_one` L222-232 同 tx 写键；拦截不写键（工程补白 6）| ✅ 与 D2 §2.5 骨架 `if res["ok"]` 一致 |
| SEG-6 货币只扣一次 | BEGIN IMMEDIATE + 单写队列串行 → 后到事务重读余额；TC-SEG-02 断言 coins=750 | ✅ 静态推导成立；测试经 `:memory:` 共享库 + `_write_lock` 串行验证 |
| SEG-7 限购只 +1 | `_player_after_buy` L196 落 personal_buys；TC-SEG-03 断言 count=1 | ✅ |
| SEG-8 不依赖 wild_lock | shop_tx 全程未触碰 wild_lock；防护 = repo.tx() + 队列 | ✅ 与 ADR-06 一致 |
| SEG-9 业务级幂等兜底保留 | shop.py A1 tx_id/ledger（L1026-1031/L1134-1135）保留 | ✅ 引擎侧保留；载体靠 message 级幂等键，二者不冲突 |

### 1.3 POOL 件套（per-player 串行队列）——逐条核验

| 规则 | 落点 | 核验 |
|---|---|---|
| POOL-1 队列粒度 = 玩家 | `PerPlayerQueue._queues: Dict[player_qid, Queue]`（L136）+ 每玩家独立消费者 | ✅ TC-POOL-01/02 覆盖 |
| POOL-2 事务外排队 | `enqueue`（L140-160）不包 tx | ✅ 静态推导：入队仅在 `q.put`（无 DB 访问）|
| POOL-3 幂等查重入队前 | `process_message` L276 idem_claim → 命中不入队（L277）| ✅ TC-POOL-03 覆盖 |
| POOL-4 超时/失败处理 | 失败捕获转人话（`_failure_reply` L87-97，POOL-4）；**超时未实现** | ⚠️ 超时硬阈值按 D2 附录 A 明确「留待实测压测定型」，非本批缺失；但队列无任何超时保护，handler 卡死会永久阻塞同玩家后续指令（P2-5）|
| POOL-5 事件循环集成 | asyncio.Queue + `_run_consumer` 单消费者任务（L184-202）| ✅ 装配点批次6/7 注入并驱动（契约内）|
| POOL-6 崩溃/断线与队列 | sender 异常捕获（L192-197）不阻塞队列；内存队列随进程丢失、幂等键落 DB 兜底 | ✅ TC-IDEM-05 覆盖 |

### 1.4 双扣两路径（D2 §2.5）——核验

| 路径 | 断言对象 | 载体 |
|---|---|---|
| 货币路径 | 并发两条 /购买 → currencies 恰扣一份总额 | `test_tc_seg_02`（coins 1000→750，恰 -250）✅ |
| 限购路径 | 并发两条 /购买 → personal_buys 计数恰 +1 | `test_tc_seg_03`（count==1）✅ |

> 备注：两条路径的并发用例均使用**限购商品**（heal limit=1）制造单方成功，未真正隔离「货币不足」拦截路径（见 P2-12）。但断言对象（货币恰扣一份/限购恰 +1）与 D2 §2.5 表一致，判定为有效实现。

### 1.5 §四 P 项承接

| P 项 | 承接 | 核验 |
|---|---|---|
| 【批5B】P0-1 幂等零消费/购买不包事务/队列缺失 | IDEM-1~4/6、SEG-1、POOL-1~3 + TC-IDEM-01/02、TC-SEG-01、TC-POOL-01 | ✅ 载体落地 |
| 【批5B】P0-2 并发读-改-写竞态 | SEG-2/6/7 + TC-SEG-02/03 | ✅ |
| 【批5B】P1-1 双扣两路径载体 | §2.5 表 + TC-SEG-02/03 | ✅（见 P2-12 隔离性备注）|
| 【批5B】P1-3 回复前崩溃 → 不双结算 | IDEM-4/5/8 + TC-IDEM-05 | ✅ |
| 【批5B】P1-4 幂等载体错位（绑发送出口）| IDEM-1 + ADR-05 | ✅ 载体在指令入口 |
| 【批5B】P2-4 世界锁与购买无关 | SEG-8 + ADR-06 | ✅ |
| 【批5A】P1-1 settle 存根 | IDEM-8 实装 + TC-IDEM-08×4 | ✅（接缝见 P1-2）|

---

## 二、维度②：代码质量核验（bug / 边界 / 并发 / 时序 / 回滚 / 孤儿键 / 哨兵）

### 2.1 队列消费者时序（静态推导：安全，非问题）

`_run_consumer` L198-202 的「空检 + return 之间无 await」注释经核验成立：

- 消费者从 `q.task_done()` 到 `if q.empty(): return` 之间**无 await**（同步块）；`enqueue` 的 `await q.put(item)` 对无界队列（maxsize=0）`full()` 恒 False → 直接 `put_nowait` 亦**无内部 await**。单事件循环下两个同步块不可交错，故不存在「消费者空检返回后、新入队项滞留无消费者」的丢唤醒竞态。
- `enqueue` L155-159 的「consumer is None or consumer.done() → 新建」检查在 put 后同步执行，两次并发 enqueue（不同玩家）也不会为同玩家拉起双消费者（第二个看到已存 task 非 done）。

**结论：队列消费者时序无 P0/P1 问题，已核验确认。**

### 2.2 并发事务竞态（静态推导：安全）

- `buy_in_tx`/`_process_one` 全部经 `repo.tx()`（= connection.tx() L331-368：BEGIN IMMEDIATE + `_write_lock` 单写队列 + `_tx_owner` 防同任务嵌套）。同库并发事务严格串行，后到事务重读前事务提交后状态 → SEG-2/6/7 保证成立。
- 不同玩家队列各自独立消费者，DB 层仍由 `_write_lock` 串行化（POOL-2 注释已诚实标注）——「并行」落地为队列隔离，事务安全靠 BEGIN IMMEDIATE，与 D2/ADR-06 语义一致。

### 2.3 异常回滚 / 孤儿键 / 幂等键一致性

- 回滚：connection.tx() 捕获 `BaseException` 统一 ROLLBACK（L351-357），含 CancelledError。✅
- 孤儿键：仅 `ok=True` 在 tx 内写键；拦截/异常不写键 → 无孤儿键。✅
- 键一致：入口 `idem_claim`（读）与 tx 内 `idem_exists`（权威，BEGIN IMMEDIATE 持锁二次确认）双查重，防排队窗口双写。✅（`test_pool_queue_window_duplicate_authoritative` 覆盖）

### 2.4 Group 哨兵（"dm"）

- 两处定义：`processing.py` L59 `DM_GROUP_SENTINEL="dm"`；`battle_boundary.py` L789 同值。均含「装配层统一收敛一处定义」注释（对齐 D2 附录 A）。**功能正确**，但已出现 D2 附录 A 预警的「各造哨兵」雏形 → P2-9。

---

## 三、维度③：遗漏与接缝（TC 未覆盖 / 规则未落地 / 与既有 storage/shop 接缝）

### 3.1 与既有 shop 接缝（P1-2，最重要）

- **线上 `/购买` 仍未入事务**：`shop_commands.cmd_buy`（L422-433）仍直接 `shop_buy(shop_id, target, qty, ctx)`（L432），ctx 由 make_context（批次6/7 待接线）装配，**无 repo.tx() 包裹**。SEG-1 的「购买结算整体搬入 repo.tx()」目前只在 shop_tx 载体 + 测试中成立，**真实指令路径尚未获得 BEGIN IMMEDIATE + 单写队列防护**。
- D2 §五明确「装配接线点=批次6/7」，故**非本批回归**；但按审查维度③必须显式登记，否则到批次6/7 若只接 make_context 而漏接 buy_in_tx/process_message，线上双扣敞口将持续存在。**修复建议**：批次6/7 装配 `/购买` 时必须把 cmd_buy 的业务闭包替换为 `buy_in_open_tx`（或整条走 process_message），并在本批报告/清单中登记此接缝为「待接线项」。

### 3.2 settle_exit_idempotent 与 process_message 的嵌套张力（P2-1 接缝）

- `settle_exit_idempotent` **自行开事务**（battle_boundary.py L835-837 明言「调用方不得在已持有的 repo.tx() 内调用」）。
- 但 D2 的指令入口 `process_message._process_one`（processing.py L215）已把 handler 包在 `repo.tx()` 内。若 `/逃跑` 经 process_message 处理、其 handler 内调用 settle_exit_idempotent → 同任务嵌套 tx → `StorageTransactionNestingError`（connection.py L339）。
- 现测试均直调 settle（不经 process_message），故**组合路径未被测试、接线决策未定**（静态推导：若装配层把 /逃跑 走 process_message 并在 handler 内调 settle 必然抛错）。修复建议：装配层明确二选一——/逃跑 不走 process_message（settle 自带幂等+事务），或在 process_message 的 tx 内联结算逻辑（不调 settle）。需登记为批次6/7 接线决策。

### 3.3 TC 覆盖缺口（P2）

| 缺口 | 位置 | 建议 |
|---|---|---|
| `"dm"` 哨兵分支（process_message L268）无单测 | processing.py | 补一条 group_id 为空/None → 键 group_id=="dm" 的用例 |
| `buy_in_open_tx` no_player 分支（L275-276）无单测 | shop_tx.py | 补购买不存在玩家的用例 |
| settle_exit_idempotent 键要素缺失分支（L866-868）无单测 | battle_boundary.py | 补 message_id 为空 → 返回 False 且不动会话 |
| 「队列 + 购买」组合路径无集成测试（双扣经 tx 验证、队列经 POOL 验证，二者组合未断言）| D2 ADR-06 声明组合防护 | 建议批次6/7 补一条 process_message(buy_in_open_tx) 双扣组合用例 |

---

## 四、问题清单（P0 / P1 / P2 分级）

### P0（0 项）

无。

---

### P1（2 项）

**P1-1 ｜ shop_tx 背包多实例回写计数膨胀（静默数据损坏）**
- 文件/行号：`qbot_rpg/commands/shop_tx.py` L162-190（`_ctx_inventory_to_player`，尤其 L176-180）
- 现象：`_inventory_from_player`（L117-122）把 Player.inventory 按 item_id **合并计数**为 `{item_id: 总量}`；`_ctx_inventory_to_player` 回写时对同一 item_id 取 `pool[0]` 用合并总量替换其 count，却**额外保留 `pool[1:]` 各实例原 count**（L179 `out.extend(pool[1:])`）。若玩家持有两个同 item_id 实例（如不同 quality/bound），则回写总量 = 合并总量 + 其余实例原计数之和，**发生计数膨胀**。
- 例：inventory=[药水A(count=2), 药水B(count=3)] → `_inventory_from_player` 得 {"potion":5} → 任一次购买回写后 pool[0]=A(5) + B(3) = **8**，正确应为 5。
- 影响：任何一次购买（即便买别的物品）都会使同 item_id 多实例物品计数静默膨胀，无报错。代码 docstring（L159-160）自称「防御性处理」但该防御分支逻辑错误。
- 修复建议：合并回写时把总计数落在 `pool[0]`，**将 `pool[1:]` 计数置 0 或丢弃**（或改为保留各实例但按比例/按首实例承载总量）；至少补一条同 item_id 多实例的往返单测锁定总量守恒。

**P1-2 ｜ SEG 载体未接到线上 `/购买`（接缝，非本批回归但必须登记）**
- 文件/行号：`qbot_rpg/commands/shop_commands.py` L422-433（`cmd_buy` L432 直调 `shop_buy`，无 repo.tx()）
- 现象：D2 ADR-12 ②「购买结算整体搬入 repo.tx()」为 M6 前置接线（非可选），但本批仅交付 shop_tx 载体 + 测试；线上真实 `/购买` 指令路径仍无事务、无双扣防护。
- 影响：若批次6/7 装配层漏接，线上 `/购买` 读-改-写竞态敞口（【批5B】P0-2）继续存在。
- 修复建议：在批次6/7 装配时把 cmd_buy 业务闭包替换为 `buy_in_open_tx`（或整条走 `process_message`），并在此报告/清单显式登记该接缝为「待接线必办项」；本批若要求「落地即闭环」，则应在 cmd_buy 内补 `repo.tx()` 包裹作为过渡。

---

### P2（12 项）

**P2-1 ｜ settle_exit_idempotent 与 process_message 嵌套张力（接缝，见 §3.2）**
- battle_boundary.py L835-837 vs processing.py L215。装配层需明确二选一接线，否则 `/逃跑` 走 process_message + handler 内调 settle → 嵌套 tx 抛错。

**P2-2 ｜ 幂等重放的 `ok` 语义两载体不一致**
- processing.py `_replay_reply` L77-84 命中重放返回 `ok: False`；shop_tx `buy_in_tx` L333-340 幂等命中返回 `ok: True`。同为「已处理重放」，两个载体对 `ok` 字段语义相反。若装配层统一按 `ok` 判定成功/失败会误判。
- 修复建议：统一约定重放时 `ok` 的取值（建议重放返回专用状态位 `idempotent=True` 而 `ok` 恒 False 或恒 True 二选一），并写入装配契约。

**P2-3 ｜ 7 天清理无生产调度调用点**
- `cleanup_idem_keys`（repository.py L546-560）仅测试直调；process_message / shop_tx / 装配层均未调度。idempotency_keys 表持续增长，IDEM-7「滚动清理」在线上不生效。
- 修复建议：启动时/定时任务调用一次 `cleanup_idem_keys(7.0)`（可归批次6/7 装配或运维 cron）。

**P2-4 ｜ 队列任务无超时保护**
- `_process_one`/`_run_consumer` 无超时：handler 卡死 → 同玩家后续指令永久阻塞（POOL-4 的超时上限按 D2 附录 A 留待压测定型，故非本批缺失，但应登记：批次6/7 压测后需补 `asyncio.wait_for` 或等价超时）。

**P2-5 ｜ 消费者异常/关闭时 future 可能永不 resolve**
- `_run_consumer` L186-198：`item.future.set_result` 前若 `_process_one` 抛出 BaseException（如 CancelledError，`_process_one` 只 catch Exception）或 `queue.close()` 取消在途任务，则 `process_message` 的 `await fut`（L281）永久挂起。静态推导：正常路径不会触发，但关闭/取消路径存在挂起风险。
- 修复建议：`_run_consumer` 用 try/finally 确保在途 item 的 future 兜底 resolve（或 `_process_one` 捕获 BaseException 转 `_failure_reply`）。

**P2-6 ｜ handler 返回 ok=False 但已写 tx 时无幂等键保护**
- `_process_one` L219-236：若 handler 先写 DB 再返回 `ok=False`，则事务正常 COMMIT（非异常回滚）且不写幂等键 → 半执行残留无键。shop 载体（buy_in_open_tx）保证失败零写（L287-288），但 process_message 的通用 handler 契约未强制「ok=False ⇒ 零写」。
- 修复建议：契约层强制 ok=False 时 handler 不得有写副作用（或改成 ok=False 即抛异常回滚）；至少补文档声明。

**P2-7 ｜ 测试时序脆弱**
- `test_idem_processing.py` L127/L236 `await asyncio.sleep(0.01)` 等发送出口；`test_per_player_queue.py` L107-110/L157-160/L176-179 用 `for _ in range(5000): await sleep(0)` 忙等。均为时序断言，偶发变慢机器可能 flake。
- 修复建议：用 event/future 同步（如等 sender 完成后置 event）替代 sleep/忙等。

**P2-8 ｜ `queue.close()` 清空未消费队列，在途/排队 future 不 resolve**
- processing.py L172-179：测试用停机语义，但若关闭时仍有排队 item，对应 `process_message` 挂起（与 P2-5 同源）。测试均先 await 再 close，安全；生产停机需注意。

**P2-9 ｜ "dm" 哨兵两处重复定义**
- processing.py L59 与 battle_boundary.py L789 各自定义 `DM_GROUP_SENTINEL="dm"`。功能一致、各有「收敛一处定义」注释，但已出现 D2 附录 A 预警的多点定义雏形。建议装配层批次6/7 收敛到单一常量。

**P2-10 ｜ world_sold_out / last_refresh / blackmarket_goods 持久化缺失（工程补白 5 承接）**
- shop_tx.py L33-35 明言三态持久化归装配层/后续批；`_build_ctx` L139-141 深拷贝防污染 world_ctx。静态推导：若「永久下架」场景（shop.py `_mark_sold_out`）在装配层未补持久化，重启后 sold-out 状态丢失。属文档化承接项，登记防漏。

**P2-11 ｜ world_stock 内联 CAS 与 save_world_state 的版本交互（接缝）**
- shop_tx `_write_world_stock_in_tx`（L216-242）自增 world_stock 行 version；而 `save_world_state`（repository.py L451-494）按 `expected_versions` 全字段 CAS。静态推导：装配层若在购买前缓存了 world_stock 旧 version，购买后调 `save_world_state` 会 CAS 冲突整单回滚。需在装配层约定购买后重读 world 版本。

**P2-12 ｜ 双扣两路径未真正隔离（测试设计）**
- `test_tc_seg_02`（货币路径）与 `test_tc_seg_03`（限购路径）用同一限购商品（heal limit=1），两测试的拦截原因均为 `limit`；「货币不足」路径未被独立构造（若用无库存无限购商品，两路并发购买均成功属正确双购买，无法触发单方失败）。断言对象虽与 D2 表一致，但建议补一条「无限购商品 + 余额仅够一次」的纯货币路径用例。

---

## 五、无问题维度确认

1. **幂等载体定位**（IDEM-1 / ADR-05）：确认载体 = 指令处理入口（process_message），发送出口仅崩溃注入点，无误。
2. **只查不插**（IDEM-3）：确认 idem_claim 纯只读，无独立预插，无孤儿键，无误。
3. **同事务写键**（IDEM-4 / SEG-5）：确认业务写 + write_idem_key 同一 BEGIN IMMEDIATE 事务 COMMIT，无误。
4. **购买事务内读**（SEG-2）：确认玩家行/world_stock 均在 tx 内重读，未取 load_player 60s 缓存，无误。
5. **双扣两路径**（§2.5）：货币恰扣一份 + 限购恰 +1 均有断言载体，无误（隔离性备注见 P2-12）。
6. **队列消费者时序**（POOL-1/5）：静态推导无丢唤醒、无双消费者竞态，确认安全。
7. **异常回滚 / 孤儿键**（IDEM-6 / POOL-4）：确认 tx 异常 ROLLBACK、拦截不落键、失败人话消息不静默吞，无误。
8. **并发事务串行化**（SEG-2/6/7 / ADR-06）：确认 BEGIN IMMEDIATE + 单写队列串行化使后到事务重读最新状态，无误。
9. **不依赖 wild_lock**（SEG-8 / ADR-06）：确认购买防护与 wild_lock 无关，无误。

---

## 六、修复优先级建议

1. **先修 P1-1**（背包计数膨胀）——纯逻辑 bug，补单测 + 改 `_ctx_inventory_to_player`。
2. **登记 P1-2 + P2-1**（线上 /购买 未接线、settle 嵌套张力）为批次6/7 装配必办接缝项，纳入 D2 §五 遗留清单。
3. **顺带清 P2-2/P2-3/P2-5/P2-9**（ok 语义统一、清理调度、future 兜底、哨兵收敛）——改动小、收益明确。
