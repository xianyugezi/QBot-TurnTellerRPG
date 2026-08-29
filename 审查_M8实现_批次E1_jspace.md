# 审查报告 · M8 炼金实现 批次E1（指令壳·会话主链段）

- 范围：`qbot_rpg/commands/alchemy_commands.py` 的 `cmd_alchemy / cmd_feed / cmd_inherit / cmd_inherit_super / cmd_confirm / cmd_abandon / cmd_resume / cmd_decompose` + 相关工具 `_player_of / _prof_level / _settings_of / _session_mgr_of / format 模板`（`_render_panel / _feed_feedback / _render_inherit_success / _render_decompose / _confirm_error / _feed_error / _inherit_error`）
- 参考：`docs/m8_contract_指令契约.md`（§2/3/4/5/18、MUT、ATO、TC）、`docs/细化/细化_2c4d_炼金指令表.md`
- 对照引擎：`core/alchemy_session.py`、`core/alchemy_settle.py`、`core/alchemy_core.py`、`core/alchemy_auto.py`、`core/trait_inherit.py`、`core/gem_wallet.py`、`core/energy_bar.py`、`core/proficiency.py`、`core/quality.py`、`world/session.py`、`assembly/context.py`、`assembly/runner.py`
- 门控：**j-space full 档**（接缝审计→分段精读→落盘→ship）
- 方法：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试）；运行行为结论均为**静态推导**
- 预算：验证性 grep 7 次（≤15），引用 read 直读定位

> 结论速览：**P0×2 / P1×2 / P2×6**。两个 P0 均为「壳层与装配接线断裂」导致的核心验收点不可达成（终态结算不落键不删会话；分解零落账）；两个 P1 为「生产上下文从未注入」导致的守卫模板/挂起恢复不可达。

---

## ① 定稿落地（关键验收点逐条）

### 守卫链逐条（合同 §2/3/4/5/18）

| 守卫 | 契约要求 | 实现落点 | 判定 |
|---|---|---|---|
| GU-05 | 炼金职业见习+ | `cmd_alchemy` L792-794：`_alchemy_prof_node(player) is None → ❌ 等级不足`；`tier_index_for_level` 取档 | ✅ 已实现（节点存在=见习起步） |
| GU-06 | 能量≥1（仅 energy_enabled=true） | L806-808：`_energy_enabled(settings) and energy.current_of(player)<1` 直通模板；L864-869 扣 1 格 | ✅ 已实现（R-08 默认关直通） |
| GU-07 | 单玩家无活跃会话·全局互斥 | L817-822 预查（调合类→`调合进行中`，其它→`已有活跃`）+ L858-863 `acquire` 竞态 `is_conflict` 鸭子捕获→`已有活跃`；**不触碰/不误删已有会话**（预查在 acquire 前，失败即返回） | ✅ 已实现（含竞态兜底） |
| GU-08 | 触媒需专家；位置参数 2 限固定子词/`触媒=` | L827-839：`tier_index < _catalyst_unlock_tier_index`（默认 expert=3）→「❌ 等级不足」；`catalyst_resolve` 校验注册/type | ⚠️ 半实现：专家门槛 ✅；**位置参数 2 任意词静默忽略**（见 P2-4） |
| GU-09 | 会话中 | `cmd_feed` L1023-1025：`get_active` 非调合类→`TEMPLATE_NO_SESSION` | ✅ 已实现 |
| GU-10 | 战斗拦截 | L1019 / L1153 / L1334 / L1421：`if ctx.get("in_battle")` → 战斗模板 | ⚠️ **生产不可达**：`ctx["in_battle"]` 全仓无写入（P1-3） |
| GU-11 | 不超槽位 | L1029 委托 `core.apply_feed`（FEED-04）→「投料超槽位」 | ✅ 已实现（引擎承载） |
| GU-12 | 材料存在+槽位持有 | L1029 委托 `core.apply_feed`（FEED-05 逐项全拒+差异） | ✅ 已实现（引擎承载） |
| GU-13 | 会话中 | `_run_inherit` L1156-1158 | ✅ 已实现 |
| GU-14 | PP 校验 | L1172-1175 委托 `TraitInherit.select_traits`（INH-09「PP 不足」） | ✅ 已实现（引擎承载） |
| GU-15 | 特性位余量 | L1162-1170 `slot_cap = min(inherit_slots, recipe.traits_inherit)` 传 select_traits（INH-06「继承超 N 项」） | ✅ 已实现 |
| GU-16 | group 互斥 + repeatable | L1172 委托 select_traits（INH-10/11）+ `cmd_confirm` L1347-1350 `check_placement_conflict` 结算复核 | ✅ 已实现（含结算复核） |
| GU-17 | /确认 /放弃 会话守卫 | L1337-1339 / L1423-1425 | ✅ 已实现 |
| GU-18 | /调合续 挂起+无活跃 | L1456-1460：`_is_suspended(view)`（读 `payload.state=="suspended"`） | ⚠️ **生产不可达**：全仓无任何代码写入 `state="suspended"` 标记（P1-4） |
| GU-19 | /确认 全量复核 | L1377-1381 委托 `SettleEngine.confirm` → `_core.verify_snapshot`（L468）→ 不足全拒+差异 | ✅ 已实现（引擎承载） |
| GU-32 | 仅炼金/深度产出可分解 | L1526 委托 `wallet.decompose` → `is_decomposable`；标准版拒/回收减半 | ⚠️ 判定有，**分解后零落账**（P0-2） |
| GU-33 | 道具在背包且为分解对象 | L1513-1515：`_find_item` 无→「❌ 道具不存在」；持有校验在引擎 `is_decomposable` | ⚠️ 半实现：**未扣道具/未校验持有量**（P0-2 下游） |

### 会话接线（点名疑缺项）

- **acquire 成功→扣能量→防孤儿会话**：✅ 已实现（L857-869）。`acquire` 成功后 `energy.consume(player,1)`，若竞态能量不足 → `session_mgr.release(qid)` 释放防孤儿。
- **SessionConflictError 鸭子捕获、不误删已有会话**：✅ 已实现（`is_conflict`，core/alchemy_session.py L406-417 遍历 MRO 比名；预查+竞态双重，失败路径零写）。
- **终态结算仿 settle_exit_idempotent**：✅ 结构对齐（`SettleEngine.settle_key`→`settle:confirm`/`settle:abandon`，`session_mgr.settle_alchemy` 单事务 delete_session+write_idem_key，world/session.py L282-327）。**但注入断裂** → P0-1。

### 渲染模板 M-02~05 / M-18

- `_render_panel`（M-02）、`_feed_feedback`（M-03）、`_render_inherit_success`（M-04）、`_render_decompose`（M-10）与引擎确认文案（M-05「确认成功：火焰弹（品质 72·史诗）」）**均为纯文本、零装饰 emoji**，仅保留 ✅/❌ 功能性标记。✅ 符合全仓 emoji 纪律。

### 幂等键（message_id / settle_key）

- settle_key 结构 ✅（`settle:{kind}`，alchemy_settle.py L399-404）。
- **message_id 生产注入断裂** → P0-1：`cmd_confirm` L1380 / `cmd_abandon` L1432 读 `ctx.get("message_id")`；引擎 gate `if message_id:`（L451/L579）才走 `settle_alchemy`（删会话+写键）。`assembly/context.py` L855-880 构建 ctx 时**不注入 message_id**，`runner.py` L585-611 计算了 `message_id` 却**未写入 ctx**——全仓仅有 alchemy_commands 两处读取 `ctx["message_id"]`。生产路径恒 None → 终态 gate 永不触发。

---

## ② 代码质量（bug/边界/接口对齐）

| 项 | 结论 |
|---|---|
| async/await 一致性 | ✅ 全部一致：`session_mgr` 5 方法+`settle_alchemy` 均 await；EnergyBar/引擎 sync；`cmd_decompose` 对 `wallet.decompose` 做 `inspect.isawaitable` 鸭子防御（L1527-1528） |
| 引擎接口与真实签名对齐 | ✅ 逐一核对：`new_snapshot(recipe,*,catalyst,job_tier)` / `apply_feed(snap,materials,ctx,*,append)` / `assemble_panel(snap,ctx,*,job_tier_index)` / `catalyst_resolve(name,ctx)` / `select_traits(player,snap,trait_ids,*,super_trait,job_tier_index,ctx,slot_cap)` / `apply_to_snapshot` / `check_placement_conflict` / `balance(ctx,recipe_def)` / `check_quantity` / `batch_quality` / `decompose(ctx,item_def,count,*,job_tier_index)` / `confirm` / `abandon` / SessionManager 构造注入 | 
| 异常兜底 | ✅ SessionConflictError 鸭子捕获（不 import 兄弟文件）；`get_active` 读快照纪律（异常→None）|
| 位置参数 2 限固定子词规则 | ⚠️ 未强制校验（P2-4）|
| 状态机消费 | ⚠️ 壳层不消费 `transition()/can_start()/resumable()`，仅用 `is_alchemy_session`（P2-5）|

---

## ③ 遗漏（验收点未覆盖 / 守卫链缺边）

| 项 | 说明 |
|---|---|
| TC-11/12/34（确认幂等/全量复核/原子幂等） | 实现层结构齐全，但受 P0-1 影响生产不可达成 |
| TC-08（战斗中拦截模板） | 模板在但不可达（P1-3）；行为上仍被会话互斥兜底拦截（不会误操作），但契约文案错误 |
| TC-13（挂起→续恢复） | 挂起标记无人写入，恢复链不可用（P1-4）|
| TC-18（分解落账+两段式） | 分解零落账（P0-2）+ 材料段渲染形态不匹配（P2-3）|
| /投料 在 /确认 后 | 正确终态流下（delete_session 后）→ 无会话模板（状态机 P-2 语义）✅；但 P0-1 未修前会对过期快照操作（下游混乱）|
| /放弃 幂等 | 引擎有 `already_settled→「已放弃」`（alchemy_settle.py L585-591），但壳层先 `get_active`：终态删会话后重复 /放弃 → `TEMPLATE_NO_SESSION`，引擎幂等分支经壳层**不可达**（P2-2）|

---

## P0 / P1 / P2 分级清单（文件:行号 + 修复建议）

### P0-1 终态结算注入断裂：/确认 /放弃 不删会话、不落幂等键（会话泄漏、重复确认非「已结算」）

- 位置：`assembly/context.py` L855-880（ctx 无 `message_id`）+ `assembly/runner.py` L585-611（`message_id` 算而未注入 ctx）+ `qbot_rpg/commands/alchemy_commands.py` L1380 / L1432（读 `ctx.get("message_id")`）+ `core/alchemy_settle.py` L451/L579（`if message_id:` 才走终态 gate）。
- 静态推导后果：`/确认` 成功扣料+产入但**不删会话不写幂等键** → 重复 /确认 命中旧快照 → `verify_snapshot` 因材料已扣 →「材料不足」而非「已结算」（M-05/ATO-04/TC-11 违反）；槽位永不释放，玩家被 GU-07「调合进行中」锁死至 30 天回收；`/放弃` 同样不释放。终态 F-05、MUT-02、TC-13/34 全部失守。
- 修复：`make_context` 注入 `"message_id": str(event.get("message_id") or "")`（event 本已含该键，runner L550）；或 `_make_handler` 装配时把 `message_id/group_id` 并入 ctx。改后 /确认 /放弃 的 `settle_alchemy` gate 生效（delete_session+write_idem_key 同事务）。

### P0-2 /分解 零落账：指令仅展示，不扣道具、不返材料、不入账宝石

- 位置：`qbot_rpg/commands/alchemy_commands.py` cmd_decompose L1526-1545；对照 `core/gem_wallet.py` L430-488 `decompose` 为**纯计算**（docstring「不删物品/不入包/不入账，GW-12」）、L508 `grant_gem` 为入账方法、L283 `_consume_materials` 不存在于钱包。
- 静态推导后果：cmd_decompose 只调用 `wallet.decompose(...)` 后渲染，**从未调用 `remove_item` / `add_item` / `grant_gem`** → 道具仍在包、材料/宝石不入账，用户被成功文案误导。GU-32/33、F-10、拍板①、TC-18 全部未达成。
- 修复：成功后补三步（建议引擎化或壳层接线）：`ctx["remove_item"](item_id, qty)`（扣道具）；对 `res["materials"]` 逐条 `ctx["add_item"](mid, count)`（返材料，元组 `(id,name,count)`）；`wallet.grant_gem(ctx, res["gem"])`（宝石入账，仅当 `res.get("gem",0)>0`）。扣料前应复用 `_count_item` 校验持有（GU-33 持有量）。

### P1-3 战斗拦截模板生产不可达：ctx["in_battle"] 全仓无注入

- 位置：`cmd_feed` L1019 / `cmd_inherit(_super)` L1153 / `cmd_confirm` L1334 / `cmd_abandon` L1421 读 `ctx.get("in_battle")`；`assembly/context.py` L855-880 及其余任何处**均未写 `ctx["in_battle"]`**（全仓 grep 无赋值）。
- 静态推导后果：战斗中发 /投料 等走 `get_active` → battle 会话 → `is_alchemy_session=False` → 返回「当前没有调合会话…」（错误模板），契约 GU-10/MUT-04/TC-08「战斗中使用 /即时调合 <配方>」永不出现。功能上仍被会话互斥兜底拦截（不会误操作），但契约消息不可达、TC-08 生产失败。
- 修复：`make_context` 据 `battle_session`（context.py L983 已有）或玩家战斗标志注入 `ctx["in_battle"]=bool(...)`。

### P1-4 挂起(战斗)标记无人写入：/调合续 恢复链不可用

- 位置：`cmd_resume` L1459 依赖 `_is_suspended(view)`（读 `payload.state=="suspended"`，L1231-1244）；全仓 grep `SUSPENDED`/`state="suspended"` 仅 alchemy_session.py 定义与 alchemy_commands.py L1241 读取，**无任何代码写入该标记**；`session_mgr.suspend` 各调用点（L1033/L1180/…）均写新快照、不带标记。
- 静态推导后果：任何会话 `_is_suspended` 恒 False → /调合续 恒回「已有一个调合会话进行中」或「无会话」；挂起→续恢复（GU-18/MUT-05/行6-7/TC-13）整体不可用。
- 修复：战斗打断挂起侧（批3 路3B/战斗接线）在调用 `session_mgr.suspend(qid, {**payload, "state":"suspended"})` 时写入标记；或改为由 `SessionManager.suspend` 统一打标、壳层/战斗侧传 `suspended=True` 标志。

### P2-1（并入 P0-1 之下游）重复 /放弃 模板不一致

- `cmd_abandon` L1423-1425 + `alchemy_settle.py` L585-591：引擎 `already_settled→「已放弃」` 分支经壳层不可达（终态删会话后 `get_active=None` → `TEMPLATE_NO_SESSION`）。P0-1 修复后可复现；建议壳层对「无会话」与「已放弃」语义统一（契约未强定义，属文案一致性）。

### P2-2 /分解 渲染材料段恒空（形态不匹配）

- `_render_decompose` L1284-1288 按 `Mapping` 迭代 `res["materials"]`，但 `gem_wallet._recover_materials` 返回 `List[Tuple[str,str,int]]`（`(id,name,count)`，见 _compose_result L410 / L397 元组解包）→ 每条 `continue` → 材料段恒为空，只剩「✅ 分解成功 + 宝石×N」。与 P0-2 修复一并改为按元组解包渲染。

### P2-3 cmd_alchemy 批量分支静默忽略触媒参数

- L801-804 `qty>=2` 分支先于 L824-839 触媒解析返回：`/炼金 配方*2 触媒=爆裂壶` 的触媒被静默吞掉（不报错不生效）；批量不开会话属工程决策（可接受），但建议对「批量+触媒」显式提示忽略。

### P2-4 位置参数 2 未强制「限固定子词/键值」

- `cmd_alchemy` L773-776 只探测 `自动` 与 `触媒=`，对其它位置参数 2 词（如 `/炼金 火焰弹 爆裂壶`）静默忽略，不符合 P-02「位置参数 2 限固定子词或键值」。建议对非 `自动`/非 `触媒=` 的 args[1] 拒绝（模板化）。

### P2-5 壳层不消费状态机 transition()/can_start()/resumable()

- 全部 E1 壳层仅用 `is_alchemy_session(view)`，未调用 `core/alchemy_session.py` 的 `transition/can_start/resumable/terminate_idempotent`。静态推导的语义偏差：
  - 挂起中 /投料 /继承 /确认 应拒（P-3「先 /调合续 恢复」），壳层会直接对挂起快照 apply_feed/confirm；
  - /炼金 遇挂起会话按行5「调合进行中」拒，而状态机行7 为「/炼金 恢复」。
  - 当前因 P1-4 标记无人写入而不可触发；标记接线后需同步补齐（推荐壳层统一走 `transition(state,...)` 判定而非自建 if 链）。

### P2-6 produce_counts 自增在 settle 事务外（非原子）

- `cmd_confirm` L1384-1394：`player["produce_counts"]` 在 `engine.confirm`（已 commit 删会话）之后由壳层自增，依赖 runner L409-444 的 `tx.upsert_player` 兜底落档；若其间崩溃则计数丢失（长线计数口径不精确，CASC-05）。建议并入 SettleEngine.confirm 返回内的同事务写，或至少文档标注。

---

## 无问题维度确认（点名疑缺项已实现清单）

1. **GU-05/06/07/08(专家)/09/11/12/13/14/15/16/17/19 守卫链**：已实现（见 ① 表，逐条含引擎委托承载）。
2. **acquire 成功→扣能量→防孤儿会话**：✅ 已实现（L857-869，能量竞态不足时 `release` 防孤儿）。
3. **SessionConflictError 鸭子捕获、不误删已有会话**：✅ 已实现（预查+竞态双重，失败路径零写）。
4. **渲染模板 M-02~05/M-10 纯文本无装饰 emoji**：✅ 已实现（仅 ✅/❌ 功能性标记）。
5. **幂等键结构 `settle:{kind}` + delete_session+write_idem_key 同事务**：✅ 已实现（world/session.py L282-327 仿 settle_exit_idempotent）；注入断裂另见 P0-1。
6. **引擎接口签名对齐 / async-await 一致性 / 读快照纪律**：✅ 全部核对一致。
7. **/继承超 独立指令防御收口**（剥离误并「超」子词，L1218-1223）：✅ 已实现；多超特性拒绝 ✅。
