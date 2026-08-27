# 审查_M6实现_批3A_wir_jspace

> 审查对象：M6 实现层批3A（热重载接线 WIR 件套）· 静态代码审查
> 方法：**纯静态审查（本环境无 bash 沙箱，未运行任何命令/测试/脚本）**；运行行为结论一律标注【静态推导】。
> 审查文件：qbot_rpg/content/hot_reload.py · qbot_rpg/commands/gm_commands.py · qbot_rpg/commands/reload_result.py · qbot_rpg/content/resolve_or_degrade.py · qbot_rpg/content/models.py（+ 关联接缝：loader/registry/effects/snapshot_resume/router/field_meta/细化_3d/细化_3e2/tests）
> 对照契约：docs/细化/细化_M6_热重载接线.md（D3）§一 WIR-01~22 + §1.3 权限分级 + §1.4 TPL-15~18 + TC-WIR-01~14；docs/细化/细化_3e2_热重载契约.md（机制本体）
> 门控：j-space **full 档**；已按 SKILL.md 唤醒 → 门控 → 接缝审计 → ship。

---

## 0. 结论摘要

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | **0** | 无致命/阻断级问题（四项接线、权限分级、四模板、红黄计数、resolve_or_degrade 均落地） |
| **P1** | **2** | F1 同步异步桥接失效（asyncio.Lock 循环绑定）；F2 TPL-17 连续失败次数恒为 1 |
| **P2** | **8** | F3~F10（死分支 / 日志格式 / TC 覆盖 / 对照公式 / 消费点登记 / 批边界登记等） |

---

## 1. 维度① D3 契约落地（核对表）

| 契约点 | 判定 | 证据 |
|---|---|---|
| 四项接线 WIR-01 | ✅ 组件级齐全 | ①start L176-193；②schedule_polling L69-88 + poll_once L233-266；③GmBackend.reload_content L460-489 + cmd_gm_reload L631-657；④reload_result.py 全文件。**壳层注册（启动调 start / scheduler.add_job）登记批次6/7【工程补白】→ 见 F9 批边界登记** |
| WIR-02 包发现/装配 | ✅ | __init__ L123-148 构造 watcher，meta 缺省 default_field_meta_table L132；pack_dir 缺失/非目录经 build_pack manifest_missing R-5 → start 红拦（L183-188）【静态推导】 |
| WIR-03 首轮失败=启动失败 | ✅ | start L185-188：失败记红黄计数后抛 PackLoadError（ADR-D3-01 兑现） |
| WIR-04 调度驱动（poll_once+apscheduler，禁 while+sleep） | ⚠️ 部分 | schedule_polling/poll_once 齐（L69-88/233-266）；但 run() while+sleep 自循环仍保留 L203-231 → 见 F8 |
| WIR-05 暂停/恢复 | ✅ | poll_once paused 直接返回 L246-255；手动 reload 成功复位 L400 |
| WIR-06 权限分级 | ✅ | GM_COMMAND_LEVEL[重载]=ROLE_MANAGER L198；GM_DEFAULT_GRANT 含重载 L207-209；check_gm_permission 三级+静默 L297-319；handle_gm_command 无权限→silent L876-878 |
| WIR-07 /重载 真实后端 | ⚠️ 主体 ✅ / 桥接 ⚠️ | reload_content = watcher.reload 同一管线 L477；{ok,summary,failures} 契约 L460-489；**同步桥接 _run_watcher_reload L512-526 存在缺陷 → F1**；no_change 死分支 → F3 |
| WIR-08 /备份 /恢复 契约声明 | ✅ | backup_content/restore_content 抛【待接线】NotImplementedError L491-509（已声明未接线登记） |
| WIR-09/10 翻译四模板逐字 + 落点 | ✅ | TPL-15~18 逐字抄录 L25-33（与 D3 §1.4 逐字比对一致）；禁词扫描 L36-44 通过（无 必须/强制/上限/封顶/拒绝）；commands 层翻译、content 零 NoneBot |
| WIR-11 红/黄计数可观测出口 | ✅（格式瑕疵→F4） | models.py count_errors/count_warnings/group_by_module L88-109；ReloadResult count_* L111-117；_log_report_counts L41-66；start 路径红黄计数 L187-192 |
| WIR-12 F4 验收③ caplog 断言 | ❌ 未落地 | 全 tests 无「N error(s) M warning(s)」日志断言 → F5 |
| WIR-13 F4 验收⑤ 登记表对照 | ⚠️ 部分 | test_hot_reload_wiring.py L61-68 只断言 `_KIND_FOR_MODULE ⊆ field_meta`，缺 `FIXED_REGISTER_ORDER ∪ manifest` 两段；verify_m6 静态检查未建（scripts/verify 无 verify_m6.py）→ F6 |
| WIR-14 删除降级 resolve_or_degrade | ⚠️ 部分 | 入口齐 L29-60；effects 复用 L193-194 但**丢弃 degraded 信号**；reward/marks/combo/quest 仅登记未迁移 → F7 |
| WIR-15~17 增量/攒批/原子写 | ✅ | build_pack 增量解析+全量校验 loader L209-219；_reload_sync 一次构建整批 L326-328；原子写归属编辑器、部分写入容错（R-5→回退→作者改签名→重试）逻辑齐 |
| WIR-18 router 注释清理 | ✅ | router.py L202-204「预留：内容包驱动指令注册未接线，M6 WIR-18 声明」 |
| WIR-19 message_prefix 渲染层快照边界 | ✅（无违规） | 本批无对渲染模板/显示配置快照化行为 |
| WIR-20 m5_shared_contract 回填 | ✅（文档侧已核） | 见细化_3d L88-93 TPL-15~18 已回填 |
| WIR-21/22 措辞 | ✅（代码侧符合修正后口径） | build_pack docstring「整包校验仍全量重跑」L216-219 与 WIR-15 修正口径一致 |

**维度①无问题项确认**：四项接线组件级齐全无缺失；权限分级三级+静默语义与 §1.3 矩阵逐格一致；TPL-15~18 四模板逐字与 §1.4 一致；红黄计数出口（count/group_by_module/日志）本体落地；resolve_or_degrade 统一降级入口落地且 effects 消费。

---

## 2. 维度② 代码质量（P1 明细）

### P1-F1【gm_commands.py L512-526 + hot_reload.py L146】同步异步桥接失效：asyncio.Lock 事件循环绑定 → /重载 经桥接恒退化

- **现象（静态推导）**：`_run_watcher_reload` 用 `asyncio.run(watcher.reload(...))`（L521），每次调用**新建一个事件循环**；而 `HotReloadWatcher.__init__` 在 L146 创建 `asyncio.Lock()`，该锁在**首次 await 时绑定到当时的运行循环**（start L183 / reload L200 均 `async with self._lock`）。`start()` 与后续 `reload()` 分别经两次独立的 `asyncio.run` → 锁绑定到 loop A，第二次 `asyncio.run`（loop B）await 锁 → 抛 `RuntimeError: ... is bound to a different event loop` → 被 `except RuntimeError`（L522）宽泛捕获 → 返回 None → reload_content 返回「热重载需在异步装配上下文执行」占位失败（L478-482）。即：**watcher.start() 后经同步桥接的 /重载 必然失败**。
- **Python 3.9 兼容下更糟**：项目标注 typing 3.9 兼容（models.py L10）；3.9 的 `asyncio.Lock.__init__` 在构造时即经 `get_event_loop()` 绑定默认循环，与后续 `asyncio.run` 的新循环必然冲突，**首次调用即失败**。
- **连带**：test_hot_reload_wiring.py `test_gm_backend_reload_success_path`（L137-154）正是「`asyncio.run` 起 watcher → 再 `asyncio.run` reload」序列，其 `assert res["ok"] is True` 会因此失败——测试与实现同源缺陷【静态推导，未运行】。
- **修复建议**：① 优先：批次7 装配改为异步命令上下文直接 `await watcher.reload(...)`（工程补白已声明），本批移除或显式标注 `_run_watcher_reload` 为**不可用占位**；② 若需同步壳：用独立长生命周期事件循环线程 + `loop.run_until_complete`，或把 watcher 串行化改为 `threading.Lock`（`_reload_sync` 本身全同步，async 包装仅为其串行化）；③ `except RuntimeError` 收窄为仅捕获「event loop is already running」并记 error 日志，勿吞真实 RuntimeError。

### P1-F2【gm_commands.py L488 + reload_result.py L79/94-96】TPL-17 连续失败次数 N 恒为 1

- **现象**：`render_reload_result` 的 `consecutive_failures` 参数缺省回退 **1**（L95）；唯一端到端消费方 `GmBackend.reload_content` 失败路径调用 `render_reload_result(result)` 时**未传** `consecutive_failures`（L488），而 `watcher.consecutive_failures` 属性可用（hot_reload.py L171-173）。凡经 /重载 后端渲染 paused 结果 → 输出「❌ 连续 **1** 次重载失败，已暂停自动检测」——与实际失败次数（≥3）不符。
- **触发路径（静态推导）**：_reload_sync 失败且 `fail_count >= max`（L366-369）→ result.paused=True → reload_content L488 渲染 → N=1。
- **修复建议**：`reload_content` 失败分支传 `consecutive_failures=watcher.consecutive_failures`（`render_reload_result(result, consecutive_failures=watcher.consecutive_failures)`）；或让 ReloadResult 自身携带该计数（WIR-09 契约注明 N = consecutive_failures，应由结果对象或调用方透传，避免缺省 1 的隐性错误）。

---

## 3. 维度② 代码质量（P2 明细）

### P2-F3【gm_commands.py L484-486】reload_content 的 no_change 死分支 + 手动无变更「0 个模块变更生效」

- `result.no_change` 仅由 `poll_once` 置位（hot_reload.py L260-264）；`reload()` 路径恒不置位（L195-201 → `_reload_sync`，`no_change` 恒 False）。故 L485-486 分支不可达（死代码）。
- 手动 /重载 无变更时：`build_pack` 缓存命中 → `changed=()` → TPL-15 输出「✅ 已重载【pack】：0 个模块变更生效」（误导性 UX）。契约 TPL-18「内容包无变更，无需重载」本可覆盖此场景。
- **修复**：二选一——a) 删除死分支 + 文案接受 N=0；b) 让 `reload()` 在 `changed==()` 时置 `no_change=True` 走 TPL-18（推荐，语义更准）。同时 L653 `TPL_15_HEAD + summary` 拼接若遇 TPL-18 summary 会双 ✅ 叠头，需一并处理。

### P2-F4【hot_reload.py L53-56 / L191-192 / L334-335】红黄计数日志三处格式不一致 + 启动失败重复记录

- 三处独立格式：`_log_report_counts`「红 %d / 黄 %d（error(s)=%d warning(s)=%d）」L54-56；start 黄路径「红 0 / 黄 %d（warning(s)=%d）」L191-192（**缺 error(s) 段**）；_reload_sync 失败路径「红 %d / 黄 %d（%s）」L334-335（缺 error(s)/warning(s) 明确段 + 无逐模块明细）。
- 启动失败时 L334 与 L187 各记一次（重复）。
- **影响**：TC-WIR-08 的 caplog 断言「N error(s) M warning(s)」在黄提示路径、以及轮询/手动失败路径无法统一匹配。
- **修复**：统一收敛到 `_log_report_counts`（含 per-module group_by_module 复用 models 接口），start 失败不重复记；黄路径补 error(s) 段。

### P2-F5【tests】WIR-12 / TC-WIR-08 的 caplog 红黄计数日志断言未落地

- 全 tests grep「caplog/error(s)/warning(s)」：仅 test_snapshot_resume_rebind.py L112 有 RSM-09 告警断言；**无任何测试断言启动路径「红 N / 黄 M」计数日志**（F4 验收③）。
- **修复**：补 `test_hot_reload_wiring.py`（或 test_content.py）用 `caplog.at_level("WARNING")` 断言 start 红拦/黄提示日志含计数+模块名（对齐 F4 验收③ + 3e D-06）。

### P2-F6【tests WIR-13 + scripts/verify】登记表对照公式不完整 + verify_m6 静态检查未建

- 契约 WIR-13 公式为 `FIXED_REGISTER_ORDER ∪ _KIND_FOR_MODULE.keys() ∪ manifest 声明模块 ⊆ field_meta.modules 键`；当前测试仅断言 `_KIND_FOR_MODULE ⊆ field_meta`（test_hot_reload_wiring.py L61-68），缺 `FIXED_REGISTER_ORDER`（effects/statuses/marks/skill_chains/action，field_meta 现含 20 模块、含全部）与 manifest 声明模块两段。
- `scripts/verify/` 只有 verify_m0~m5，**无 verify_m6.py**——WIR-13「verify_m6 静态检查（D8 执行）」未建。
- **修复**：补全测试三段并子集；M6 verify 批建 verify_m6.py 收录该静态检查（落点 D8）。

### P2-F7【resolve_or_degrade.py + core/effects.py L193-194】WIR-14 消费点仅 effects 复用且丢弃 degraded 信号

- 契约「消费点（effects/reward/marks/combo/quest）复用」；现状 effects 经 `_make_resolver` 复用入口但**只取 `[0]` 丢弃 degraded**（effects.py L194），「degraded=True 供降级提示」未接线；reward/marks/combo/quest 仅 docstring 登记（resolve_or_degrade.py L13-19「本批仅登记」），未迁移调用统一入口——存在四消费点各自降级语义与统一入口漂移风险。
- `resolve_or_degrade` Mapping 分支 `(registry.get(kind) or {}).get(id)`（L54-55）：若 kind 值非 Mapping（畸形注册表）→ 抛 AttributeError 而非按契约「不抛异常」降级。
- **修复**：后续批次将四消费点迁移到统一入口并透出 degraded（供降级提示/日志）；Mapping 分支加 isinstance 防护返回 (None, True)。

### P2-F8【hot_reload.py L203-231】run() while+sleep 自循环保留

- WIR-04 要求「禁止 while+sleep 自循环常驻任务（watcher.run() 收归壳层调度，不直接启用）」；代码保留 `run()` 作为「M0 零依赖可测默认」且未直接启用——不构成违约但留有被误启用风险（D-02 要求 apscheduler 驱动，批次6/7 若误用 run() 即违规）。
- **修复**：登记批次6/7 仅允许 `schedule_polling`/`poll_once` 接线、禁用 run()；或标注 `run()` deprecated 待移除。

### P2-F9【hot_reload.py L69-88 + 批边界】四项接线①② 壳层注册登记批次6/7

- WIR-01「四项缺一不可」中 ①启动装载（装配层调 start）②调度（scheduler.add_job）**本体到组件级已齐**，但 NoneBot 壳层注册（启动装载调用、apscheduler 注册）登记批次6/7【工程补白 L80-81/L212-215】——与 WIR-08「已声明未接线」同口径，批3A 验收需按批边界判定；若批3A 判据为「四项组件落地」，则达标，仅登记确认。
- **修复**：验收清单中把① ②标记为「组件落地 + 壳层登记批次6/7」，防漏。

### P2-F10【reload_result.py L99-100】TPL-18 无端到端消费路径（WIR-10 自动提示出口未接线）

- TPL-18 仅 `poll_once` no_change 结果可触发；本批无「自动重载提示 → 翻译 → 统一发送出口（+限频，不占玩法配额 D-06）」消费方——四模板中 TPL-18 端到端无接线（TC-WIR-07 覆盖到渲染器层）。
- **修复**：登记批次6/7 自动提示发送出口；本批补一个 poll 结果→render_reload_result 的纯函数用例即可闭环。

---

## 4. 维度③ 遗漏（TC 未覆盖 / 规则未实现 / 接缝）

| 项 | 判定 | 说明 |
|---|---|---|
| TC-WIR-01~07 | ✅/⚠️ | 01 组件级可测；02 start 失败红拦（test_content 红拦族）；03 轮询无变更（test_content L489-505）；04 暂停/恢复（L526-565）✅；05 权限矩阵（test_gm_commands L251-283）✅；06 /重载 后端 ⚠️ 成功路径测试受 F1 影响；07 四模板（test_reload_translator）✅ 但 TPL-17 经真实后端 N=1（F2）未断言 |
| TC-WIR-08 | ❌ | caplog 红黄计数断言缺 → F5 |
| TC-WIR-09 | ⚠️ | 测试存在但不完整 → F6 |
| TC-WIR-10 | ✅ | resolve_or_degrade 四态测试（test_hot_reload_wiring L84-106） |
| TC-WIR-11~13 | ✅ | 增量/攒批/部分写入由 test_content 既有回退增量族覆盖 |
| TC-WIR-14 | ✅ | router 注释（router.py L202-204）+ 3d TPL-15~18（L88-93）均符合 |
| 接缝：snapshot_resume / backup_snapshot | ✅ | RSM-05 激活接口被 snapshot_resume.py L220 `getattr(watcher,"backup_snapshot")` 消费（双口取档）；batch 3B 侧 |
| 接缝：router WIR-18 | ✅ | 注释已改，无「热重载」字样残留 |
| 接缝：细化_3e2 TRG-3 措辞 | ✅（代码侧） | loader/build_pack 已是「增量解析+全量校验」修正口径（WIR-15）；3e2 L78 母文档原文未改（文档侧遗留，非本批代码缺陷） |

---

## 5. 汇总清单

### P1（2）
1. **F1** 同步异步桥接失效：`_run_watcher_reload`(gm_commands.py L512-526) 的 `asyncio.run` 与 watcher 的 `asyncio.Lock`(hot_reload.py L146) 事件循环绑定冲突 → start 后经桥接的 /重载 恒「待异步装配」占位失败；`except RuntimeError` 过宽吞真错；测试 `test_gm_backend_reload_success_path` 同源必失败【静态推导】。修复见 §2。
2. **F2** TPL-17 N 恒 1：reload_content L488 未传 `consecutive_failures`，render_reload_result L95 缺省 1。修复：透传 `watcher.consecutive_failures`。

### P2（8）
3. F3 no_change 死分支 + 手动无变更「0 个模块变更生效」（gm_commands L484-486 / L653）
4. F4 红黄计数日志三格式不一致 + 启动失败重复（hot_reload L54/L191/L334）
5. F5 TC-WIR-08 caplog 断言未落地
6. F6 WIR-13 对照公式缺两段 + verify_m6 未建
7. F7 WIR-14 消费点仅 effects 复用且丢 degraded；Mapping 分支可抛 AttributeError
8. F8 run() while+sleep 保留待登记
9. F9 四项接线①② 壳层注册批次6/7 登记
10. F10 TPL-18 端到端发送出口未接线（WIR-10 自动提示）

### P0（0）

---

## 6. ship 确认（j-space full 档 · ship 前复读）

- 四项接线组件级齐全、权限矩阵一致、四模板逐字、红黄计数出口落地、resolve_or_degrade 落地——**维度①无 P0/P1 级缺失**；
- 2×P1 均为**当前批次可修**的明确缺陷（桥接失效与计数透传），修复点与行号已给出；
- 8×P2 多为登记/补测/一致性项，不阻塞批3A 组件验收，但 F5/F6 涉及 F4 验收③⑤ 的验收闭环，建议随 M6 verify 批补齐。
