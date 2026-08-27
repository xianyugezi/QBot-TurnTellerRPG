# 审查报告 · M6 实现层批5A（故障注入 crash+save + `.pending` 实装）· j-space 门控 full 档

- **审查对象**：tests/fault/fault_inject_crash.py、tests/fault/fault_inject_save.py、qbot_rpg/storage/pending.py、qbot_rpg/storage/repository.py（save_player 写失败转写 + replay_pending）、qbot_rpg/storage/connection.py（_commit 注入接缝）、contract_deviations.md（F-1 核销）
- **参考契约**：docs/细化/细化_M6_故障注入.md（D5）§一 FLT-01~10 + §二 FLT-11~17 + TC-FLT-01~09；docs/细化/细化_4a_存储层契约.md（RW-4 L225 / TC-09 L392 / F4 L276）；docs/细化/细化_M6_幂等事务三件套.md（IDEM-4/5/8，批2 已实装）
- **方法**：纯静态代码审查（本环境无 bash 沙箱，未运行任何命令/脚本；全部运行行为结论为**静态推导**）。读文件工具 + grep 取证。
- **结论**：**P0×0 / P1×2 / P2×8**。契约主链（FLT-06~17 / TC-FLT-04~09 / RW-4 / IDEM-4/5/8 / F-1 核销）实现到位，两个 P1 均为写路径兜底与重放清空的边界缺陷。

---

## 一、D5 契约落地对照（维度①）

### 1.1 规则映射（FLT-06~17 全部落地）

| 规则 | 契约要求 | 实现位置 | 判定 |
|---|---|---|---|
| FLT-06 注入点=发送出口 | mock Sender.send/send_text 抛异常，发送出口非幂等载体 | fault_inject_crash.py L151-153（crash_sender 抛 SenderSendError，注入 process_message 的 sender 参数——测试构造实例非全局 patch） | ✅ |
| FLT-07 断言=业务已提交+键已落 | players 行已变 + idempotency_keys 含三元组 | fault_inject_crash.py L162-165（gold 450 + idem_find 非 None + command 校验） | ✅ |
| FLT-08 同键重发幂等返回 | 业务零执行/零发送/不双结算 | fault_inject_crash.py L176-179、L218-223（idempotent=True、record==[]、sent==[]、gold 不变） | ✅ |
| FLT-09 settle 二次结算 False | IDEM-8 实装后断言二次结算返回 False | fault_inject_crash.py L245-259（ok1 True → 二次 ok2 False + 会话不重复删） | ✅ |
| FLT-10 恢复路径 | finally 还原发送回调 + 重发验证 + 清理 | fault_inject_crash.py L166-180（finally 内正常 sender 重发断言） | ✅（finally 健壮性见 P2-6） |
| FLT-11 注入点=storage 写路径 | mock save_player / tx() COMMIT 抛 OSError（_commit 接缝） | connection.py L370-377（_commit 抽方法，生产路径不变）；fault_inject_save.py L87-90 + L136-138（实例属性遮蔽，仅测试实例） | ✅ |
| FLT-12 人话通道 | 「保存失败，请检查磁盘空间」进文案源 | pending.py L52（SAVE_FAILURE_MESSAGE，G0 R3 禁止 storage→commands 故文案源落 storage 层，文件头 L19-23 工程补白）；repository.py L478 拼入 StorageError | ✅（单源偏离 ADR-D5-01 建议，理由充分，见 P2-8 双源登记） |
| FLT-13 绝不静默丢数据 | 写失败转写 .pending，禁静默 | repository.py L354-371（_transcribe_pending，二次失败记 critical 日志）+ L469-478 | ✅（覆盖面见 P1-2） |
| FLT-14 .pending 队列实装 | .pending.jsonl 追加写，条目 F-01~04 | pending.py 全文件（JSONL append + fsync L149-152；F-01~04 L84-87） | ✅ |
| FLT-15 磁盘恢复后重放 | 单事务逐条重放→成功清空→失败保留 | repository.py L481-504（单事务整体回滚 + 文件保留） | ⚠️（重放窗口竞态 P1-1） |
| FLT-16 F-1 核销 | contract_deviations L24 标注 M6 已实装 | contract_deviations.md L24（「**M6 已实装**」+ 落点详述）；fault_inject_save.py L164-177（test_flt_09 断言） | ✅ |
| FLT-17 断言对象 | 人话文案 + pending 含数据行 + 重放后 load_player 一致；禁弱断言 | fault_inject_save.py L95-111（文案/四个 F 字段/回滚后无行）、L149-157（重放后逐字段 round-trip） | ✅ |

### 1.2 验收用例对照（TC-FLT-04~09）

| TC | 用例 | 三要素注释 | 断言数 | 判定 |
|---|---|---|---|---|
| TC-FLT-04 发送出口异常→业务已提交+键已落 | fault_inject_crash.py test_flt_04（L134-180） | docstring L137-144 ✅ | 5（ok/gold/idem 键/command/重发组） | ✅ 断言静态成立：process_message 首处理→_process_one 写键 COMMIT→消费者 sender 抛异常 `except Exception: pass`（processing.py L202-207）→ok=True；finally 重发走入口 idem_claim 命中（processing.py L286-287）→_replay_reply send=False |
| TC-FLT-05 同 message_id 重发幂等返回 | test_flt_05（L184-225） | ✅ | 7 | ✅ 静态成立：queued=False（入口命中）、零发送（send=False 分支 processing.py L202）、gold 不变（业务零执行） |
| TC-FLT-06 settle 幂等不双结算 | test_flt_06（L232-260） | ✅ | 5 | ✅ 静态成立：settle_exit_idempotent（battle_boundary.py L821-884）首结 → 删会话+写键 settle:flee（group 取 payload.origin_group=g_battle）；二次 idem_claim 命中返回 False（L876-877） |
| TC-FLT-07 写失败人话+pending 落 | fault_inject_save.py test_flt_07（L68-114） | ✅ | 9 | ✅ 静态成立：mock 实例 `_commit` → tx() L360-366 else 分支捕获→ROLLBACK→raise（connection.py L359-366）→save_player except (OSError, OperationalError)（repository.py L472）→转写（F-01~04 全断）+ StorageError 人话；断言 ③「表无行」= 事务已回滚（静态推导） |
| TC-FLT-08 磁盘恢复后重放一致 | test_flt_08（L121-158） | ✅ | 7 | ✅ 静态成立：replay_pending 单事务整批 upsert（L496-503）→clear；load_player 与 make_player 默认值一致（conftest L53-95：阿伟/35/gold 350/potion 首项） |
| TC-FLT-09 F-1 核销登记 | test_flt_09（L164-177） | ✅ | 2 | ✅ 只读静态断言（L175-177：行含「已实装」+「M6」） |

### 1.3 与批2 幂等/接缝的一致性（维度③交叉）

- crash 脚本消费真实 process_message / PerPlayerQueue / settle_exit_idempotent（批2 实装），**未 mock 引擎**——断言打到真实幂等链路（IDEM-4/5/8），非「幂等假象」。✅
- save 脚本注入点 = connection._commit 实例接缝，生产路径不变（connection.py L370-377 注释明示）。✅
- sender 异常在 processing.py L202-207 被捕获（幂等键已落兜底），与「发送出口仅是崩溃注入点」（总纲 ADR-05）一致。✅

---

## 二、代码质量（维度②）

### 2.1 无问题确认项

- **注入隔离（FLT-04/TC-FLT-03）**：crash 注入 sender 为测试构造回调；save 注入为 `monkeypatch.setattr(测试实例, "_commit", …)` 实例属性遮蔽 + finally undo；每用例独立 tmp_path 文件库（WAL，生产等价；crash 脚本 L47-52 注释解释了不用 :memory: 的原因——共享缓存内存库表级锁触发 SQLITE_LOCKED）。✅
- **防 G0 反向 import**：grep `import nonebot | from qbot_rpg.commands/world/web` 于 qbot_rpg/storage/ 全零命中；pending.py 仅 import qbot_rpg.data.logging_utils；repository→pending 单向（pending 零 DB 依赖，无循环 import）。✅
- **pending 写入原子性**：append 单行 write+flush+fsync（pending.py L149-152），事件循环内无 await 点、原子执行。✅
- **FF-01~04 字段语义**与 D5 §九一致；created_at 缺省补 _utcnow（L92）。✅
- **重放单事务/失败保留**符合 FLT-15 字面（repository.py L495-504，`except Exception` 不捕 CancelledError，取消时文件保留——设计正确）。✅
- **坏行处理**：read_all 坏行/残缺 payload 跳过不删原文件（pending.py L155-180，P2-2 修复注释），配套单测 test_pending_queue_bad_line_skipped/missing_payload_skipped。✅
- **F-1 双重承载**：tests/unit/test_pending_queue.py（FLT-16 要求单元半边，D5 P2-1 已补建，含 OperationalError 补测 L85-102）。✅

### 2.2 发现项（详见 §四）

- P1-1：replay 清空竞态（read_all→事务→clear 三阶段无隔离，事务窗口内新 append 条目被 clear 整文件删除）。
- P1-2：写失败兜底仅 save_player 单点，settle/购买等直连 repo.tx() 路径 COMMIT 失败无转写、抛裸 OperationalError。
- P2-1：OperationalError 宽捕获（含 SQLITE_BUSY/语法错误等非盘满错误）统一转写 pending + 报「磁盘满」人话。
- P2-2：clear 双失败（unlink + 写空均 OSError）从 replay_pending 逃逸。
- P2-3：坏行「保留待人工审计」（L169/L178 注释）与成功重放后 clear 整文件删除自相矛盾。
- P2-6：crash 脚本 finally 重发断言失败会替换主断言异常；queue.close() 在断言失败时不执行。
- P2-7：条目 player_qid 与 row_payload.player_qid 一致性未校验。
- P2-8：SAVE_FAILURE_MESSAGE 与 3d 模板注册表双源；语义坏条目（解析通过、重放必败）整批阻塞重放。

---

## 三、遗漏（维度③）

1. **FLT-15 后半「重放失败保留条目不丢」无测试承载**：TC-FLT-08 只测成功路径（replay 返回 1 + 清空）；重放事务失败→返回 0→文件保留 → 无用例。
2. **session_upsert / delete_session 两类重放动作无测试**（_apply_pending_entry L511-523 分支零覆盖）；且全仓无此类条目生产者（见 P1-2）。
3. **_transcribe_pending 二次失败**（磁盘持续不可写、pending 落盘也失败 → 记 critical 返回 False）无用例。
4. **clear 失败路径**（unlink 失败写空文件）无用例。
5. **replay 窗口竞态**（P1-1）无用例（需并发写失败注入）。
6. **启动 bootstrap / 定时触发的装配消费点为零**：grep `replay_pending` 仅 repository.py 定义 + 两处测试调用——FLT-15「启动 + apscheduler 定时检测」接线留待批6/7 装配（D5 §10.5 登记范围内，本批不判违规，仅标注）。
7. TC-FLT-01/02/03、19/20/21（六脚本形态/`--only fault` 驱动）归驱动批次，不在本批范围——已确认批5A 交付面内无遗漏。

---

## 四、问题清单（P0/P1/P2）

### P0：0

### P1：2

**P1-1 · replay 清空竞态：重放事务窗口内新落条目被 clear 整文件删除（违反 RW-4 绝不静默丢数据）**
- 位置：repository.py L492-503（`read_all → 单事务重放 → q.clear()` 三步无隔离）；pending.py L186-193（clear 删除整个文件）
- 静态推导：`read_all` 读完后进入含多个 await 的事务（L496-498），期间其他协程可因新的写失败 `append` 新条目；重放成功后 `clear()` unlink **整个文件** → 新条目（已确认数据）随文件删除 → 静默丢失。触发需「重放进行中再次写失败」，概率低但直接违反 RW-4 绝对承诺与 FLT-15「失败保留条目不丢」精神。
- 修复建议（三选一）：① 重放前 `os.replace(path, f"{path}.replay")` 原子切分——旧文件移交重放（成功后删旧文件），新 append 落新路径文件，天然隔离；② clear 改为行级清理（仅删除本次重放覆盖的行）；③ clear 前重读对比行数，文件有新增则放弃删除并告警。

**P1-2 · 写失败兜底仅 save_player 单点：D5 §三 3.1「写路径（save_player / tx() COMMIT）」只落地一半**
- 位置：repository.py L469-478（`_transcribe_pending` 唯一调用点，grep 证据）；battle_boundary.py L879-883（settle_exit_idempotent 自行开事务，COMMIT 失败裸抛）
- 静态推导：settle / 批2 已接线的购买、签到等直接 `repo.tx()` 写路径 COMMIT 抛 OSError/OperationalError → **无 .pending 转写**、无 StorageError 人话翻译（命令层按 D5 FLT-11/12 「捕获 StorageError 翻译人话」会漏捕裸 sqlite3.OperationalError）；F-02 已定义的 session_upsert/delete_session 两类转写动作全仓无生产者。数据面：settle 结算成功但 COMMIT 失败 → 会话删除与幂等键均回滚（IDEM-6 正确），但内存已结算的玩家收益无任何本地暂存 → 玩家感知为「发了指令没结果」，恢复后数据不完整。
- 修复建议：提供 Repository 统一兜底入口（如 `save_with_pending(action, qid, payload)` 或 tx 级异常归一化 StorageError 工厂），settle_exit_idempotent 与购买/签到等已接事务的调用方接入「捕获→转写→人话」；至少 settle 路径先补（战斗结算为最高价值数据）。

### P2：8

**P2-1 · OperationalError 宽捕获 → 非盘满错误误转写 pending + 误报磁盘人话**
- 位置：repository.py L472
- 说明：sqlite3.OperationalError 亦覆盖 SQLITE_BUSY（锁超时）、SQL 错误等；一律转写「保存失败，请检查磁盘空间」会污染 pending 队列（重放时必然再次失败并整批阻塞，见 P2-8）且掩盖编程错误。静态概率低（单写队列下 BUSY 罕见，语法错误仅代码 bug 时发生），但易修。
- 建议：按 `exc.sqlite_errorcode` 过滤（SQLITE_FULL=13 / SQLITE_IOERR=10 / SQLITE_CANTOPEN=14 / SQLITE_READONLY=8 等 IO 类才转写），其余原样上抛。

**P2-2 · clear 双失败 OSError 逃逸 replay_pending**
- 位置：pending.py L186-193；repository.py L503
- 说明：unlink 失败 → 写空文件；若写空也失败（磁盘持续满）→ OSError 从 `await q.clear()` 逃逸（replay_pending 无包覆）→ 启动/定时触发方需自行兜底，且「重放已完成但清空失败」状态无信号（下次重放整体幂等重写，安全但重复）。
- 建议：clear 内把写空失败也转日志+吞（条目保留即不丢，下次重放幂等安全），或 replay_pending 包 try 统一记告警。

**P2-3 · 坏行「保留待人工审计」与 clear 整文件删除矛盾**
- 位置：pending.py L169/L178（跳过保留注释）vs L186-193（成功重放后 unlink 整个文件）
- 说明：重放成功后坏行随文件删除，「保留待人工审计」承诺落空。坏行本身为损坏数据，实际损失有限，但注释与行为不一致。
- 建议：坏行单独转存（如 `.pending.bad-<ts>.jsonl`）或注释诚实化。

**P2-4 · TC 覆盖缺口（FLT-15 后半等）**
- 位置：fault_inject_save.py（无失败重放用例）
- 缺：重放失败→返回 0→文件保留（TC-FLT-08 只测成功面）；session_upsert/delete_session 重放；转写二次失败；clear 失败。均有单测承载条件（test_pending_queue.py 已建同型用例），补齐成本低。

**P2-5 · replay_pending 装配消费点为零（登记，非本批违规）**
- 位置：repository.py L481；grep 仅测试两处调用
- 说明：FLT-15「启动 bootstrap + apscheduler 定时」由批6/7 装配接线；建议装配批次验收时覆盖「启动即有 pending → 自动重放」。

**P2-6 · crash 脚本 finally 内重发断言可掩盖主断言，且 queue.close 不保证执行**
- 位置：fault_inject_crash.py L166-180（TC-FLT-04 finally 内含 4 条断言）；L224-225
- 说明：若 try 段断言失败，finally 断言若再失败将替换主异常（pytest 报告失真）；断言失败时 `queue.close()` 不执行（消费者任务残留，靠 pytest-asyncio 循环回收兜底，实际影响小）。测试层面非契约违规（D5 FLT-10 明文要求恢复路径含重发断言）。
- 建议：main 断言与恢复路径断言分离（重发验证移出 finally 或在 finally 中 try/except 收敛后复抛原异常），queue 关闭用独立 try/finally。

**P2-7 · 条目 player_qid 与 row_payload.player_qid 一致性未校验**
- 位置：pending.py L174-176
- 说明：read_all 校验了 payload 含 player_qid，但未校验与 F-01 同值；`delete_session` 重放用条目 qid（repository.py L523），若被篡改/手改不一致可删错会话。
- 建议：read_all 增加 `entry.player_qid == payload["player_qid"]` 校验，不一致按坏条目跳过。

**P2-8 · 双源文案登记 + 语义坏条目整批阻塞重放**
- 位置：pending.py L52（SAVE_FAILURE_MESSAGE 独立于 3d 模板注册表，F-18 递延项相关）；repository.py L495-504
- 说明：① 文案与 3d 模板注册表未来合并时需收敛一处（命令层透传同一常量）；② 契约 FLT-15 规定重放为单事务——任一语义坏条目（能解析但重放必败，如字段类型非法）导致整批回滚并**永久阻塞**后续新条目（每次重放同样失败，且与 P2-1 相加会放大：误转写的条目永占队列）。属契约设计结果，实现忠实，登记供 D8 仲裁（逐条事务 vs 单事务的取舍）。

---

## 五、无问题维度确认（显式确认项）

- 三要素注释：6/6 用例 docstring 齐备（含 test_flt_09 的「注入点=无」显式声明）✅
- 断言强制（FLT-02）：各用例断言数 5/7/5/9/7/2，全部 ≥1 且为具体值断言（gold 450、command 内容、逐字段 round-trip），无「不崩就行」✅
- 注入隔离（FLT-04/TC-FLT-03）：无生产模块全局 patch，全部作用于测试构造实例，独立 data 目录 ✅
- 幂等断言真实性：IDEM-4/5/8 断言全部打在批2 真实实现（process_message/settle/connection.tx）上，无 mock 引擎 ✅
- G0 架构：storage 层零 commands/world/web/nonebot 反向 import ✅
- F-1 核销：contract_deviations.md L24 已标注「M6 已实装」且 test_flt_09 有断言；TC-09 由 fault_inject_save + test_pending_queue 双承载 ✅
- connection.tx() 生产路径行为不变（_commit 仅抽方法，注释明示）✅

---

*审查方式：j-space 门控 full 档（skill 已加载）；本环境无 bash 沙箱，全程仅静态审查，未执行任何命令；运行行为结论（如事务回滚、幂等命中路径）均为源码静态推导。*