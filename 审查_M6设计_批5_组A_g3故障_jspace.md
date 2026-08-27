# 审查_M6设计_批5_组A_G3故障注入套件设计（六类注入设计合规）

> 审查方式：静态审查（本环境无 bash 沙箱，仅读文件/检索，未运行任何命令、脚本或验证；运行行为结论均标「静态推导」）。
> 门控档位：**full 档**（j-space：唤醒→门控→接缝审计→ship；未跑脚本控制器，ledger 内置于文）。
> 审查对象：
> - 设计 G3：`docs/实现层规划文档.md` L3460-3463（实现要点/验收标准）
> - 定稿对照：【规则】§四.5 故障注入表（`docs/审查参考/开发规则文档.md` L313-326）；【框架】§15.16（`docs/审查参考/RPG回合制框架设计文档.md` L1637）
> - 细化/门禁：`docs/细化/细化_5d_测试体系总纲.md` §5（六脚本形态/L184-196）、TC-5d-25/26/27/28/34、门禁 G6；里程碑 M6（实现层规划 L3481）；G1 门禁（L3452）
> - 已实现参考：`qbot_rpg/storage/`（repository/connection/migrations）、`qbot_rpg/core/effects.py`、`qbot_rpg/core/formula_engine.py`、`qbot_rpg/commands/sender.py`、`qbot_rpg/content/hot_reload.py`、`qbot_rpg/world/battle_boundary.py`、`qbot_rpg/core/shop.py`、`scripts/run_all_tests.py`、`tests/`

---

## 〇、结论摘要

| 等级 | 数量 | 一句话 |
|---|---|---|
| P0 | 0 | 无（设计本身未编造能力、六类与权威表逐行对齐；无数据丢失/安全级设计错误） |
| P1 | 4 | 六类中两类引用的生产行为未实装且 G3 未声明前置/任务分配；`--only fault` 驱动未实现；掉线重连断言目标未定义 |
| P2 | 5 | 六脚本载体细节、注入隔离纪律、现有测试覆盖缺口、若干 M6 前置交付物未实现等 |

**核心结论**：G3 六类与【规则】§四.5 六故障点逐行对照完全一致，断言强制（禁"不崩就行"）与 G1 门禁（L3452）一致，幻觉维度无编造；但「回复前崩溃→不双结算」与「存档写失败→本地暂存补写」两类**依赖的生产侧能力当前不存在**（`settle_exit_idempotent` 为 NotImplementedError 存根、RW-4 `.pending` 暂存补写 F-1 递延仍挂起、指令/壳层无 message_id 幂等接线），G3 设计未声明这些前置与 M6 内任务分配，直接威胁 M6「故障注入六类全绿」门禁（L3481）可达性。

---

## 一、逐行对照：G3 六类 vs 【规则】§四.5 故障注入表（维度②/④）

G3 实现要点（实现层规划 L3462）与【规则】表（开发规则 L317-324）逐行比对：

| G3 设计（L3462） | 【规则】故障点 | 【框架】依据 | 对齐 |
|---|---|---|---|
| mock 发送出口抛异常→战斗状态回滚/可重试、不双结算（message_id 幂等） | 回复前崩溃 | §15.16（L1637）＋§15.2（L1609 message_id 幂等键） | ✅ 行文对齐；⚠️ 生产行为缺失（见 P1-1） |
| mock storage 抛 OSError→"保存失败，请检查磁盘空间"+本地暂存补写 | 存档写入失败 | §15.16＋细化_4a RW-4/TC-09 | ✅ 行文对齐；⚠️ 生产行为缺失（见 P1-2） |
| 写入非法 JSON 触发重载→回退旧 registry 不崩 | 热重载失败 | §15.5（L1616-1618） | ✅ 一致；生产已实现（hot_reload.py L236-313） |
| 公式异常/超时→兜底 0/条件不满足不崩溃 | 公式求值异常/超时 | §15.16 | ✅ 一致；生产已实现（formula_engine.py L957-1027；细化_1c3#TC-13） |
| 并发两条购买→事务下只扣一次 | 双扣防护 | §15.2（L1607）＋细化_4a TX-3/TC-01 | ✅ 行文对齐；⚠️ 命令层事务未接线、无真实并发用例（见 P1-3/P2） |
| 掉线重连→玩家数据完好 | 掉线重连 | —— | ✅ 行文照抄；⚠️ 断言目标未定义（见 P1-4） |

「每个用例必须有断言（禁'不崩就行'）」与【规则】L326、细化_5d TC-5d-25 一致 ✅。

验收标准（L3463）①六类全绿+有断言、②双扣覆盖限购/货币两路径——与【规则】L323（限购/货币）一致 ✅。

跨文档一致性（维度④）：
- G3 ↔ M6 里程碑（L3481「故障注入六类全绿」）：一致，但见 P1-1/2 可达性风险。
- G3 ↔ G1 门禁（L3452「verify 必须可执行且有断言」）：一致。
- G3 ↔ 细化_5d §5 六脚本形态（crash/save/reload/formula/doublepay/netdrop）与 TC-5d-26/27/28/34：一致；但细化_5d 声称的 `run_all_tests.py --only fault` 驱动在现实现未落地（P1-3）；`scripts/gate/` G0~G7、`verify_m6.py`、`tests/integration/` 亦未实现（P2-4）。
- 六脚本内部引用（细化_3e2#TC-06~09、细化_1c3#TC-13、规则 L366「幂等键 P0 检查项」）均真实存在 ✅。

---

## 二、P0（必须改）

**无。**

说明：本审查为设计合规审查。G3 设计忠实复刻权威表、无编造既有能力、无数据丢失/安全级设计错误，故无 P0。下述 P1 多为「依赖的生产能力缺位/未声明前置」，若 M6 前不补，会以「六类全绿门禁不可达」形式变现。

---

## 三、P1（应改）

### P1-1 回复前崩溃：message_id 幂等未接线到任何指令/结算路径，`settle_exit_idempotent` 是 NotImplementedError 存根
- **位置**：设计 `docs/实现层规划文档.md` L3462；已实现 `qbot_rpg/world/battle_boundary.py` L782-801（`settle_exit_idempotent` 结尾 `raise NotImplementedError("M4 实装：退出结算幂等入口…")`）；`qbot_rpg/commands/battle_commands.py`（全程无 idem/message_id/回滚逻辑）；`qbot_rpg/commands/router.py` L39（per-player 串行队列/message_id 声明归「下游 on_command 装配 / 5b GM 层」承担，未落地）。
- **静态推导**：storage 侧幂等键**已实现**（`repository.py` IdemKey/write_idem_key/idem_exists，IDEM-1~5，含 test_storage 幂等单测）——因此「已实现无幂等键」不成立；但「指令处理以 message_id 做幂等键（框架 L1609）」在**任何指令/战斗路径都未调用**：battle_commands 发送失败仅抛 SenderSendError（sender.py L186-191），无战斗状态回滚、无可重试、无 message_id 防双结算。fault_inject_crash 的断言对象（战斗状态回滚/不双结算）在生产侧不存在。
- **修复建议**：G3 设计内显式声明前置——「M6 前必须实装 battle_boundary.settle_exit_idempotent（细化_4a IDEM-3/框架 L343）并接线到战斗逃跑/丢失/回收结算路径」；或在 M6 任务范围补一条接线任务；否则将 L3462「message_id 幂等」改为「依赖 A3 壳层 message_id 接线 + settle_exit_idempotent 实装，缺一不得绿」。

### P1-2 存档写失败：RW-4 `.pending` 本地暂存补写 +「保存失败，请检查磁盘空间」未实现（F-1 递延仍挂起）
- **位置**：设计 L3462；已实现 `qbot_rpg/storage/`（repository/connection 无 `.pending`/暂存/补写/磁盘空间文案，grep 零命中）；登记 `contract_deviations.md` L24（F-1：RW-4/TC-09 递延 M4）；复查 `docs/审查报告/审查_M0复查_storage_repository_20260824.md` L126「RW-4 ❌ 未实现」。
- **静态推导**：storage 写路径（`save_player`/`tx()`）对 OSError 仅向上抛（connection.py L331-368），无「人话提示挂起通道 + 本地暂存队列 + 磁盘恢复后补写」。fault_inject_save 若照 细化_5d L192 断言「弹『保存失败，请检查磁盘空间』；绝不静默丢数据；失败本地暂存可补写」→ 对当前代码必然失败（或被迫写成「断言 OSError 上抛」的弱断言，违反 L326）。
- **修复建议**：G3 设计必须把细化_4a RW-4/TC-09 实装列为前置（含 storage 抛 StorageError 可被 commands 翻译人话 + `.pending.jsonl` 队列重放），并核销 contract_deviations F-1；注意 细化_4a 引证语境错配（框架 L1175-1176 实为编辑器浏览器 localStorage 兜底）已在 `docs/审查/幻觉审查_4a.md` P1-1 登记，G3 勿再引【框架】L1175，主依据用【规则】L320。

### P1-3 六脚本载体：`run_all_tests.py --only fault` 未实现（静默落到全量回归）；命令层购物未包事务
- **位置**：`scripts/run_all_tests.py` L44-48（LAYER_PATHS 无 fault/tests/fault）、L64（`--help` 却声明 `fault`/`datapack`）、L75-85（`--only fault` 不命中 MILESTONES/LAYER_PATHS → 落入 else 全量回归）；对照细化_5d L126/L154、TC-5d-25（L282）。
- **静态推导**：`--only fault` 不报错、不跑故障组，而是跑全量——与细化_5d §3.3「`fault` 过滤故障注入全组」相悖；即使 M6 建了 `tests/fault/` 六脚本，也无驱动入口（LAYER_PATHS 与阶段 1 均不含）。另 `qbot_rpg/commands/shop_commands.py` 对 `shop_buy` 未包 SQLite 事务/未接 message_id（core/shop.py L1023「调用方应包裹 SQLite 事务」），fault_inject_doublepay 的「SQLite 事务下只扣一次」当前不可测。
- **修复建议**：run_all_tests.py 补 `fault` 分支（指向 tests/fault/，独立进程跑防串扰，细化_5d §3.2 步骤 5）；未支持前 `--only fault` 应显式报错而非静默全量；双扣脚本前置补 shop_commands 事务接线。

### P1-4 掉线重连：断言目标未定义（无生产网络/重连抽象，注入点/断言/恢复三要素缺失）
- **位置**：设计 L3462「掉线重连→玩家数据完好」；【规则】L324 原文亦模糊（「静默恢复或广播『我回来了』」）；已实现 `qbot_rpg/` grep「重连/掉线/断线/reconnect/netdrop」零生产命中（仅离线补刷/离线时长等无关语义）。
- **静态推导**：引擎层零网络（细化_3a 铁律），重连概念在 NoneBot 壳层，本仓库无壳层实现；fault_inject_netdrop 无从注入（无 send/dispatch 挂点可 mock 断开），「玩家数据完好」也无断言粒度（是读档 round-trip？会话 version 不变？）。按细化_5d §5.2「注入点、断言、恢复路径三要素必须有注释」无法满足。
- **修复建议**：G3 设计把该类收敛为可落地断言——例如「模拟断线→重连后 load_player/session 与断线前快照逐字段一致（round-trip）＋会话 version 未变」，注入点落在 storage load/save 边界（mock 临时 OSError/挂起），而非虚无的网络层；若框架层不引入重连概念，建议在 G3 中显式标注该类的可测边界并降级断言粒度，避免「不崩就行」偷渡。

---

## 四、P2（建议）

- **P2-1 双扣真实并发用例缺**：现测试仅「同 tx_id 重放幂等」（tests/unit/test_shop.py TC-23 L439-448）与「存储层 50 并发 save 单写队列」（tests/unit/test_storage.py TC-18 L197-210），无「两条独立购买指令并发扣同一限购/货币」的真实并发用例；应覆盖 X 但未覆盖 → 并发双买 × 限购、并发双买 × 货币两路径（G3 验收② 的承载用例当前为零）。
- **P2-2 发送失败→战斗状态回滚/可重试无既有用例**：test_sender.py L204 只测「重试耗尽抛 SenderSendError」，test_battle_wiring.py 只测发送次数/合并，均未测「发送失败→引擎状态不双结算/可重试」（G3 第一类在现有回归中的覆盖缺口点名）。
- **P2-3 G3 未引用细化_5d**：G3 实现要点（L3462）只引【规则】§四.5＋【框架】§15.16，未引用细化_5d §5 的六脚本形态/注入隔离纪律（L205-208：夹具内注入、禁黑入生产模块、独立 `:memory:`、恢复路径 finally）与 `--only fault` 驱动；建议补引用以防六脚本形态漂移。
- **P2-4 M6 前置交付物当前未实现**：`verify_m6.py`（run_all_tests L42 置 None）、`scripts/gate/` G0~G7（细化_5d TC-5d-29 期望）、`tests/integration/`（细化_5d TC-5d-01 期望四目录）均缺失；属「未到里程碑」正常态，但细化_5d 多处已将其当存在引用，G3 设计应把「fault 脚本 + run_all 驱动 + gate 接入」列为 M6 交付清单。
- **P2-5 热重载人话提示依赖 commands 层翻译**：hot_reload.ReloadResult 只产出 errors/warnings，人话翻译声明归 commands 层（D-06）；`cmd_gm_reload`（gm_commands.py L526-544）委托 GM 后端引擎 `reload_content`，该引擎是否实装未核查——fault_inject_reload 的「人话提示」断言需确认该链路 M6 前闭合（静态推导，未验证）。

---

## 五、缺漏点名：「应覆盖 X 但未覆盖」清单

1. **应覆盖**「回复前崩溃→战斗状态回滚/可重试/不双结算」——**未覆盖**：指令/结算路径无 message_id 幂等接线、`settle_exit_idempotent` 为 NotImplementedError 存根（P1-1）。
2. **应覆盖**「存档写失败→『保存失败，请检查磁盘空间』＋本地暂存补写」——**未覆盖**：RW-4/TC-09 未实现，F-1 递延未核销（P1-2）。
3. **应覆盖**「并发双购买→事务只扣一次（限购/货币两路径）」——**未覆盖**：现仅有 tx_id 重放幂等与存储层并发写，无独立双买并发用例；shop_commands 未包事务（P1-3/P2-1）。
4. **应覆盖**「掉线重连→玩家数据完好」——**未覆盖**：无生产重连抽象，注入点/断言/恢复三要素未定义（P1-4）。
5. **应覆盖**「每个用例必须有断言」——**当前零满足**（无 tests/fault/ 六脚本，属 M6 交付物；点名：现有回归中「发送失败→战斗状态」断言为零，见 P2-2）。
6. **应覆盖**「`--only fault` 六脚本独立驱动」——**未覆盖**：run_all_tests.py 无 fault 分支，参数静默落到全量（P1-3）。

---

## 六、幻觉维度（维度③）

- **无编造既有故障注入能力**：G3 设计文本（L3462）以「mock X → 期望行为 Y」的测试目标口吻书写，未声称 `tests/fault/` 六脚本、message_id 幂等或暂存补写「已存在」；「已实现参考」核验：tests/fault/ 不存在（非幻觉，为 M6 交付物）。
- **无编造幂等实现**：storage 幂等键表/API 真实存在（repository.py），G3 引用正确；但需纠正印象——「幂等键存在于 storage」≠「战斗结算路径幂等生效」，后者缺失（P1-1），这是**设计依赖缺漏**而非幻觉。
- **引证核验**：细化_5d 六脚本对【规则】L366（幂等键 P0 检查项）、细化_3e2#TC-06~09、细化_1c3#TC-13 的引用均真实存在且语义吻合；G3 未重蹈幻觉审查_4a P1-1 的「框架 L1175-1176」语境错配（G3 未引该行）。
- **残留风险提示**：细化_5d §5.2 注入隔离纪律（禁黑入生产模块、patch 仅作用于测试实例）是防「故障注入污染生产代码」的护栏；G3 设计应显式承接，否则六脚本可能写成直接 patch 生产模块的坏测试（静态推导提示）。

---

## 七、ship 前登记（j-space 接缝审计）

- 已核对：设计 G3/M6/G1 原文、【规则】§四.5/L326/L366、【框架】§15.16/§15.2/§15.5、细化_4a RW-4/TC-06/TC-09、细化_5d §3/§5/TC-5d、细化_3e2/细化_1c3、contract_deviations F-1、storage/effects/formula/sender/hot_reload/battle_boundary/shop/router/battle_commands/shop_commands、run_all_tests.py、tests/ 全域。
- 运行行为结论全部为「静态推导」，未执行任何命令/脚本/测试。
