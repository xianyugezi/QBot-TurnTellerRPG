# 审查报告：M6 实现层批5B — 故障注入四脚本 + test_shop TC-23

> 审查方式：纯静态代码审查（本环境禁运行命令/脚本；运行行为结论均为静态推导，未执行验证）。
> 门控：j-space **full 档**（用户明示）；唤醒→门控→接缝审计→ship 流程执行完毕。
> 审查对象：`tests/fault/fault_inject_{reload,formula,doublepay,netdrop}.py` + `tests/unit/test_shop.py`（TC-23 补限购断言）。
> 参考契约：D5《细化_M6_故障注入》（FLT-18~21/22~24/25~29/30~34 + TC-FLT-10~18）、D3《细化_M6_热重载接线》（WIR-09/10、TPL-16）、3e2《热重载契约》（TRG/ATO/SNAP/BLK）、D2《幂等事务三件套》（SEG-1~9、TC-SEG-02/03）、4a《存储层契约》（IDEM-3）、细化_1c3 TC-13、5d 注入隔离纪律（L205-208）。
> 实现接缝交叉核对：hot_reload.py、reload_result.py、loader.py（R-5/kind 映射）、registry.py、formula_engine.py（含 _js_runner.js）、combo.py、shop_tx.py、shop.py、repository.py、connection.py、data/player.py+item.py、pytest.ini（asyncio_mode=auto）、run_all_tests.py、fixtures/packs/legal。

---

## 〇、结论总览

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | 0 | — |
| **P1** | 1 | `--only fault` 驱动分支未接线（FLT-35~38），help 广告 fault 却静默退化为全量运行（附批次归属说明） |
| **P2** | 6 | 断言强度/健壮性类问题（详见 §三） |

**总体判定**：批5B 四个故障注入脚本 + TC-23 对 D5 契约的落地**完整且忠实**——FLT-18~34 全部规则有对应用例、三要素注释齐全、每用例 ≥1 明确断言（无「不崩就行」偷渡）、注入隔离与确定性纪律执行到位；与 hot_reload/formula_engine/combo/shop_tx/repository/connection 六条既有实现接缝逐一交叉验证**一致**。未发现伪造断言、静默通过（除 P2-b 一处可假绿场景）、或与实现语义冲突的测试。

---

## 一、维度① D5 契约落地（逐规则映射）

### 1.1 fault_inject_reload.py（TC-FLT-10/11 ⇔ FLT-18~21）— ✅ 无问题

| 契约 | 落点 | 静态推导结论 |
|---|---|---|
| FLT-18 注入点=写非法 JSON 触发 reload，同管线 TRG-1 | L79-80 `write_text('{"id": "broken",')` → `watcher.reload()` | ✅ reload() 与 poll_once 均走 `_reload_sync`（hot_reload.py L194-200/L264-265 同一管线 TRG-1 兑现） |
| FLT-19 restored=True + errors 非空 + generation 不变 + registry 未污染 | L83-91 | ✅ 失败路径 `Registry.from_snapshot(pre)` 原子重建（hot_reload.py L354）；generation 失败路径不自增（L376）与断言一致；kind 映射经 loader.py `_KIND_FOR_MODULE`（effects→"effect"、items→"item"）核对，`all_ids("item"/"effect")` 有效 |
| FLT-20 服务不崩 + TPL-16 人话（WIR-09/10） | L92-98 | ✅ `render_reload_result` restored 分支文案与 D3 §1.4 TPL-16 逐字一致（reload_result.py L29）；`first_error_reason` 对 R-5 invalid_json 出 `effects.json R-5（rule=invalid_json…）`，断言子串（"重载失败，已回退旧配置"/"effects.json"/"请修正配置后保存，或手动 /重载 重试"）均成立；loader.py L274 PackError(module="effects", kind="R-5") 与 L86 断言一致 |
| FLT-21 恢复合法 JSON 再 reload 成功 generation+1 | test_flt11 L124-137 | ✅ build_pack 以 `self._generation+1` 建 registry（hot_reload.py L326）→ 成功提交 generation=gen_before+1；失败计数清零/paused 复位（L395-396）；`resolve("heal_small","effect")` 经 legal 包 effects.json（含 heal_small）+ kind="effect" 核对非空 |
| BLK-5 阈值节流（连续失败<3 不暂停） | test_flt10 L92-93 | ✅ max=3，1 次失败 → consecutive_failures==1、paused=False |
| 5d 注入隔离/恢复路径 | fixture L44-52 + finally L99-101/L138-140 | ✅ copytree 独立 tmp_path；源包只读；finally 还原字节 |

### 1.2 fault_inject_formula.py（TC-FLT-12/13 ⇔ FLT-22~24）— ✅ 无问题（含 1 条 P2 断言强度）

| 契约 | 落点 | 静态推导结论 |
|---|---|---|
| FLT-22 五类注入点 | 死循环 L57 / 未注册占位符 L71 / 超长>4KB L85 / 黑名单 L99 | ✅ 全覆盖；`FORMULA_MAX_LENGTH=4096`（formula_engine.py L67）与 `"1 + "*(4096+10)` 前置断言成立 |
| FLT-23 兜底 0 + warning 不崩 | 各用例断言 value==0.0 + warning 前缀 | ✅ 与实现逐一核对：`while(true){}`→Python ast.parse(mode="eval") SyntaxError（L877）→ Node `runInNewContext(timeout=30ms)`（_js_runner.js L73）抛超时→`eval_failed:*`；`[未知字段]`→`unknown_placeholder:[未知字段]`（L550）+替换 0→快路径 0.0；超长→`formula_too_long`（L975）；黑名单→`blacklist:`（L981，FORMULA_BLACKLIST 含 eval/globalThis/process L81-99） |
| FLT-24 条件不满足不崩溃 + 可继续行动（1c3 TC-13 同断言） | test_flt13 L119-124 + L127-173 | ✅ `evaluate_condition` 未知键→安全失败（combo.py L476-482）；引擎级：路径 c 无可用 replace 步→return None（L1402-1410）→ 基技能结算 form_id="a"、count_after=1、derivation=False；`pending_derivations` 步① `ok=False` + `_condition_reason` 出「条件不满足」（L836-852）——与断言逐条一致 |
| 恢复路径 | 纯函数无副作用 | ✅ 事实成立（evaluate_detail 无状态副作用） |

### 1.3 fault_inject_doublepay.py（TC-FLT-14/14b/15 ⇔ FLT-25~29）— ✅ 无问题

| 契约 | 落点 | 静态推导结论 |
|---|---|---|
| FLT-25 并发双买骨架（SEG-2/TC-SEG-02） | L156-159 asyncio.gather 两路 buy_in_tx（同 player、异 message_id、共享 repo） | ✅ buy_in_tx 整体包在 `repo.tx()`（shop_tx.py L332）；connection.py `tx()` = BEGIN IMMEDIATE + `_write_lock` 单写队列（L340-368），跨任务严格串行，后到事务重读前事务提交态（SEG-2 兑现） |
| FLT-26 货币恰扣一份（无丢失更新） | TC-FLT-14 coins 1000→750 + TC-FLT-14b 纯货币 funds 路径 400→150 | ✅ 事务内重读玩家行（buy_in_open_tx L276-280，无 60s 缓存陈旧读数）；失败方 shop_buy 校验链③/⑤ 返回 reason 与断言一致（shop.py L1074/L1105）；两路结果对称，断言与胜出方无关——确定性成立 |
| FLT-27 限购恰 +1（SEG-7/D-04） | TC-FLT-15 count==1 + 桶键 "2026-08-26" | ✅ shop_buy 成功才 node.count+=1（shop.py L1127-1129）；`_period_bucket_key` 按 UTC+8（L757-767），NOW=1787706000=2026-08-26 09:00 UTC+8（且 UTC 同日，时区无关，确定性良好）；persistent_state["personal_buys"] 键名与 D2 §2.2/【工程补白 2】一致 |
| FLT-28 不依赖 wild_lock | — | ✅ buy_in_tx/shop_tx 全链零 battle_boundary world 锁引用 |
| FLT-29 恢复路径 | finally `repo.close()` | ✅ 独立 :memory: 库；`Database.close()` 幂等（二次关闭安全），fixture teardown 双保险 |
| TL-14 idem 断言 | L168 `len(_idem_rows)==1` | ✅ write_idem_key 仅成功路径（shop_tx.py L357-359），拦截路径零写（L351-355）；SEG-5 语义一致 |

### 1.4 fault_inject_netdrop.py（TC-FLT-17/18 ⇔ FLT-30~34）— ✅ 无问题

| 契约 | 落点 | 静态推导结论 |
|---|---|---|
| FLT-30 注入点=storage load/save 边界 mock（OSError/挂起），不造网络抽象 | L127-136 实例级 monkeypatch save_player/load_player | ✅ 仅 patch 测试实例（FLT-04）；ADR-D5-02 收敛成立 |
| FLT-31 重连后逐字段一致（round-trip）+ 会话 payload 一致 | L147-152 `player_to_row(row_to_player(row))` 归一化比对 | ✅ 存读一致基线（4a TC-12）；Player 构造与 dataclass 字段（player.py L80-102）、ItemInstance/EquipmentSlot/PlayerAttributes 位置参数全部核对一致 |
| FLT-32 会话 version 断线前后不变（IDEM-3） | L153、L194、L205 | ✅ `load_session` 返回 (session_type, payload, random_seed, version, …)（repository.py L562-579），索引 [1]=payload/[3]=version 与实现一致；players 写不影响 sessions 行 |
| FLT-33 挂起不写脏 + 恢复重放完成 | TC-FLT-18 L187-206 | ✅ 挂起期零写（行比对 L193）；取消（超时兜底）→ CancelledError 被 pytest.raises 捕获（asyncio.CancelledError 为 BaseException 子类，pytest.raises 可捕获）；恢复后真实 save 重放成功 |
| FLT-34 断言粒度收敛 | 全部用例 | ✅ 未出现「静默恢复/广播我回来了」类模糊断言 |

### 1.5 test_shop.py TC-23（TC-FLT-16 ⇔ FLT-27 / 批5B P1-1 核销）— ✅ 无问题

- L446-454：`make_ctx(tx_id="T1", ledger=set())` → b1 ok/idempotent=False；b2 idempotent=True；coins 不变；inventory==1；**personal_buys count==1**（补限购计数断言完成）。
- 与 shop.py 幂等闸（L1026-1031 ledger 命中提前返回）及限购 +1（L1127-1129）语义逐条一致：重放路径不触碰计数，恰 +1 断言成立。
- 修正了既有「仅断言货币+背包」缺口（D5 §6.3 TC-FLT-16 / 批5B P1-1 落点核销）。

---

## 二、维度② 代码质量

### 已确认良好（无问题）
- **注入隔离**：monkeypatch 全部为测试实例属性（netdrop L135-136/L184），零生产模块全局 patch；reload 用 tmp_path 独立包副本；doublepay/netdrop 每用例独立 `:memory:`（唯一名共享缓存库，connection.py L137-139），互不串扰。
- **确定性**：doublepay 固定 NOW（时区无关的日期桶）、rng 不参与；formula 引擎断言与实现分支（快路径/Node 兜底）路径无关地收敛到 0.0；netdrop 无时钟依赖（挂起 0.05s 断言 `not task.done()` 对慢调度也成立）。
- **异步并发正确性**：并发双买由 BEGIN IMMEDIATE + 单写队列串行（非断言层假设，经 connection.py L332-368、shop_tx.py L332 实装验证）；两路 gather 结果对称，断言与胜出方无关。
- **共享可变状态防护**：并发共享 world_ctx 的 `world_sold_out/last_refresh/blackmarket_goods` 在 `_build_ctx` 深拷贝（shop_tx.py L139-141），`world_stock` 每事务新建；玩家态（currencies/inventory/personal_buys）逐事务从行重建——无跨事务串改。
- **三要素纪律**：7 个用例（TC-FLT-10/11/12×4/13×2/14/14b/15/17/18）docstring 均显式标注注入点/断言对象/恢复路径（FLT-03）；断言全部含具体期望值（禁「不崩就行」L326 成立）。

### P2 级发现（详见 §三）

---

## 三、P 项清单（附文件行号与修复建议）

### P1-1（运行载体 / 契约未落地）`run_all_tests.py`：`--only fault` 静默退化为全量
- **位置**：scripts/run_all_tests.py L48-53（LAYER_PATHS 无 `"fault"` 键）、L69（help 广告 `fault`）、L88-91 分支、L91-96 else 全量回退。
- **问题**：D5 §八 FLT-35~38/TC-FLT-19~21 未落地；help 已广告 fault，`python run_all_tests.py --only fault` 落入 else **静默跑全量**——正是 FLT-37「禁止落入 else 全量分支静默退化」与批5A P1-3 所禁行为。六脚本交付后无文档化入口（只能裸 pytest 跑）。
- **说明**：若该分支计划在批5 残余子批（5C/5D，与 SessionManager/暂存补写同批）落地，本项可在后续批核销；但当前状态即命中契约禁止的静默语义，故列 P1 并要求紧随批次显式接线（LAYER_PATHS 补 `"fault": ["tests/fault"]` + 独立子进程 + else 分支对未知层名显式报错）。
- **修复建议**：D5 §8.2 逐条落地；或至少将 help 广告与分支同步（FLT-38），未支持前 `--only fault` 显式报错退出非 0。

### P2-1 fault_inject_doublepay.py：asyncio.gather 位于 try 之外（L156-160、L184-188、L215-219）
- **问题**：若 gather 内任一 buy_in_tx 协程意外抛异常（非返回 dict），测试在 try 之前失败，`finally: await repo.close()`（FLT-29 三要素的恢复路径）被绕过；实际资源回收仍由 fixture teardown 兜底（无泄漏），但「恢复路径 finally」契约语义在异常路径下不成立，且错误上下文（哪一路抛的）丢失。
- **修复建议**：将 gather 移入 try 块（或 try 覆盖 gather + 断言段），finally 保留 close。

### P2-2 fault_inject_formula.py L57-63：死循环兜底断言不锁定「watchdog 真实中断」
- **问题**：注释声称「10ms 超时 watchdog 真实中断」，但断言只要求 `warnings` 以 `eval_failed:` 开头 + 值 0.0；实现上 node 不可用时（`FileNotFoundError` → `runner_unavailable`，formula_engine.py L944-945）同样以 `eval_failed:runner_unavailable` 通过——**无 node 环境该用例假绿**，watchdog 是否触发未被断言证明。
- **修复建议**：断言 `warnings` 含 `runner_fatal`/超时字样（_js_runner.js L29/L73 超时经 ERR_SCRIPT_EXECUTION_TIMEOUT → runner_fatal），或对 node 缺失加环境前置 skipif；二选一即可锁定注入有效性。

### P2-3 fault_inject_reload.py L89-91：registry「未污染」断言仅比对 item/effect 两表 ID 集合
- **问题**：FLT-19 断言对象是「registry 内容 = 上一份校验通过快照（原子替换未污染）」，现实现只比对两表 ID 元组；names/modules_raw/其余表未覆盖（弱于快照级断言）。
- **修复建议**：利用既有接口 `watcher.backup_snapshot()`（hot_reload.py L414-421）与失败前快照做全字段比对（RegistrySnapshot 为 frozen dataclass，可直接 ==），或比对 `snapshot().tables` 全 kind。

### P2-4 fault_inject_formula.py：FLT-23 描述面「结果类型非法」无用例
- **问题**：FLT-23 明确列「结果类型非法 → 0 + warning」（result_type:string_too_long/non_numeric/non_finite，formula_engine.py L886-898 已实装），脚本覆盖死循环/非法变量/超长/黑名单四注入点，但无结果类型用例（如 `evaluate("1/0")`（JS 均值 Infinity→非有限）或 `"1" + "a"` 类 → 0.0 + result_type 警告）。
- **修复建议**：补一个 `test_flt12_result_type_fallback_zero`，断言 value==0.0 + `result_type:` 前缀 warning（注意 `1/0` 在快路径 Python 中 ZeroDivisionError → 降级 Node → Infinity → result_type:non_finite，语义已核实）。

### P2-5 fault_inject_netdrop.py L142-155：恢复断言置于 finally 内
- **问题**：TC-FLT-17 将「重连后数据完好」断言（L146-153）放在 finally 块内；若前段注入/识别断言（L138-141）失败，恢复断言仍执行并可能与原异常叠加，调试时失败信息混淆。同类但更轻微：TC-FLT-18 L198-206 同构。
- **修复建议**：finally 只做 `monkeypatch.undo()`（+close 收尾），恢复断言放回正常控制流。

### P2-6 fault_inject_netdrop.py L152-153/L194/L205-206：load_session 返回元组列序索引隐式耦合
- **问题**：断言直接使用 `sess[1]`（payload）/`sess[3]`（version），与 repository.load_session 返回结构（repository.py L562-579）隐式耦合；若未来列序调整（如插入列），断言静默错位。
- **修复建议**：解包为命名变量（如 `_typ, payload, _seed, version, *_ = sess`）或加注释锚定 4a §1.3 列定义；低成本提升健壮性。

---

## 四、维度③ 遗漏核查

| 项 | 结论 |
|---|---|
| TC 未覆盖（D5 §四~§七 范围内） | ✅ FLT-18~34 对应的 TC-FLT-10/11/12/13/14/14b/15/17/18 全部落地；TC-FLT-16 经 test_shop.py TC-23 落地。FLT-23 结果类型面缺一角 → 见 P2-4 |
| 与既有 hot_reload 接缝 | ✅ reload 脚本消费真实 HotReloadWatcher/ReloadResult/render_reload_result，未复制语义；generation/restored/paused/快照回退行为与实现一致 |
| 与 formula_engine 接缝 | ✅ 直接调 evaluate/evaluate_detail，warnings 文案与实现字符串格式逐条一致（含未知占位符方括号形态） |
| 与 buy_in_tx 接缝 | ✅ 直接消费 shop_tx.buy_in_tx 真实实现，未 mock 引擎/存储；SEG-2 事务内重读语义与测试预期一致 |
| 与 storage 接缝 | ✅ row_to_player/player_to_row/load_session/upsert_session/tx() 全部真实接线；`.pending`（RW-4）归 fault_inject_save 脚本批次，本批不缺失 |
| 驱动分支（FLT-35~38） | ❌ 未落地 → P1-1（附批次归属说明） |
| TC-FLT-14「两路其一幂等返回或第二次重读被拦」 | ✅ 采用「第二次重读被拦」分支（D2 TC-SEG-02 的或语义），且 14b 补纯货币 funds 路径，覆盖完备 |
| BLK-5 连续 3 次失败暂停 | ✅ 不在 D5 四脚本 TC 范围（属 3e2 TC-09/hot_reload_wiring 既有覆盖面），不构成缺失 |

---

## 五、无问题维度确认

1. **D5 契约落地**：四脚本全部规则（FLT-18~34）→ 用例 → 具体断言三层映射完整，无悬空规则、无「不崩就行」；TC-23 限购断言补齐（批5B P1-1 核销）。
2. **注入隔离纪律（5d L205-208 / FLT-04）**：全部通过（实例级 patch、独立 tmp_path/:memory:、finally 恢复）。
3. **确定性**：全部通过（固定 NOW 且时区无关、断言与并发胜出方无关、纯函数无副作用论据成立）。
4. **异步并发正确性**：串行化载体（BEGIN IMMEDIATE + 单写队列）经实装验证与测试假设一致；无共享可变状态跨事务污染。
5. **接缝一致性**：六条既有实现接缝（hot_reload/reload_result+loader/registry、formula_engine、combo、shop_tx+shop、repository+connection、data 模型）交叉核对全部一致；测试未伪造任何生产接口。

---

*审查口径：P0=数据损坏/双扣漏检/断言必然失败或恒绿(假绿，且在常态环境必然发生)；P1=契约明确禁止的静默行为或必现缺陷（本批唯一 P1 带批次归属说明）；P2=断言强度/健壮性/可维护性。静态推导标签：所有「会通过/会失败」结论均为代码路径静态推导，未实际执行。*