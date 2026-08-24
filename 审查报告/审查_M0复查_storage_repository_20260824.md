# 审查_M0复查 · storage/repository.py（M0 复查批1-路2：存储层读写管线 Repository）

> 日期：2026-08-24 · 审查对象：`qbot_rpg/storage/repository.py`（实际 747 行；任务描述称 721 行——见「审查备注 R-1」）
> 对照基准：`细化_4a_存储层契约.md`（v1.0，451 行；RW §2 RW-1~6 / TX §3 含 CAS / IDEM §4 含 7 天清理 / RC §5 RC-1~5 / MIG §6 / 验收 TC-01~18）
> 关联阅读：`qbot_rpg/storage/connection.py`、`migrations.py`、`schema.py`、`qbot_rpg/data/*`、`contract_deviations.md`、`tests/unit/test_storage.py`、`tests/unit/test_data.py`、`tests/conftest.py`
> 审查维度：① 错误（bug/边界/幂等键/事务回滚/编解码 round-trip/并发）② 缺漏（细化/定稿要求未实现、字段定义但零消费）③ 幻觉（注释引用的细化行号真实性与一致性、工程补白标注）
> 方法限制：本环境禁止运行任何命令/脚本，全部为**纯静态代码审查**；所有运行行为结论均标注「静态推导」。

---

## 〇、结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| **P0** | **0** | 未发现必改级缺陷（前次 P0-1 世界 CAS 半写已修复且验证闭环，见 §4） |
| **P1** | **2** | P1-1 回收默认不结算即删（数据丢失 footgun）；P1-2 写后缓存失效竞态（并发陈读/覆盖窗口） |
| **P2** | **14** | 见 §3（now 参数语义、round-trip 边界、str 载荷不对称、零消费/未实现、死导入等） |

**一句话结论**：`repository.py` 的契约章节/规则编号注释引用**全部真实一致**（§2~§6、RW/TX/IDEM/RC/MIG/SCHEMA/TC 未发现错号），事务模板/CAS/幂等同事务/懒迁移等核心机制方向正确；主要风险集中在**「不结算默认值」与「缓存失效时序」两个并发/数据完整性窗口**，以及一批边界/测试注入语义问题。

---

## 一、P1 问题（2 项）

### P1-1 回收默认 `settle=None` 即静默删除会话，不结算返还（RC-1/TC-15 数据丢失 footgun）
- **位置**：`repository.py` L546-547（`settle: Optional[...] = None`）、L568-574（`settle is None` 时直接 `DELETE FROM sessions`）。
- **依据**：契约 RC-1 / TC-15 明确「会话 last_active_at 距今 >30 天 → 自动**按退出结算（材料/状态返还）**后删除；结算与删除单事务」。0.2 一句话契约亦要求「自动按退出结算」。
- **问题（静态推导）**：默认 `settle=None` 时，过期会话行被删除且**不执行任何材料/状态返还**。D-05 虽把结算语义委托给会话管理器注入，但 storage 作为会话行**唯一删除方**，把「不结算直接删」设为默认值，等于把一个**静默丢玩家材料**的行为做成易踩默认。当前 `recycle_scan` 仅被测试消费（无生产调度，F-15 未接线），影响潜伏；一旦 M4 调度接入而调用方忘记传 `settle`，即发生无返还回收。
- **修复建议**：
  1. 默认 `settle=None` 时**拒绝删除**（返回错误/日志，或要求显式 `allow_unsettled=True` 才放行），或
  2. 删除前若 `settle is None` 至少打告警日志（避免静默），或
  3. 把签名改为必传 `settle: Callable`（默认不提供降级路径）。

### P1-2 写后缓存失效时序竞态：F3 主路径提交后无失效，并发读可把提交前旧快照写回缓存
- **位置**：`RepoTransaction.upsert_player` L691-693（**事务内、提交前** `invalidate_player`）；`load_player` L352-369（读连接 `fetchone_read` → 命中后写缓存 L368）；`save_player` L377-381（提交后 L381 失效）。
- **问题（静态推导）**：F3 模板主路径（契约 §3.2：`async with repo.tx() as tx: tx.upsert_player(...)`）只有**提交前**失效，提交后无失效。WAL 下只读连接在「失效 → 提交」窗口内开始执行的 SELECT 拿到**提交前快照**，但结果可能在提交后才写回 `_player_cache`（L368）——即**失效之后缓存又被写入旧数据**，60s TTL 内后续 `load_player` 命中陈读。若同一 qid 的并发读（如 `/角色` 展示路径，不在 per-player 串行队列内）与排队指令交错，陈读快照可能被后续指令加工后回写 → **覆盖/丢更新**。`save_player` 虽在提交后补了一次失效（L381），但当并发读的写缓存发生在该失效之后时仍无法完全闭合（读语句在提交前启动、写缓存晚于提交后失效）。
- **触发条件**：同一 qid 的读路径未与写路径完全串行（per-player 队列未覆盖所有读）；长事务（如战斗结算）放大窗口。
- **修复建议（静态推导）**：
  1. 引入**写代际号**（`self._write_generation`，每次 `invalidate_player` 自增）：`load_player` 在 DB fetch **返回后**比对代际号，若已变化则**丢弃本次结果不写缓存**（或重读），从根上消除「失效后被写回旧快照」；
  2. 或 `Repository.tx()` 出口统一对事务内 upsert 过的 qid 做提交后失效；
  3. 至少文档化：`repo.tx()` 体内 `upsert_player` 后**必须在 COMMIT 后再 invalidate_player**（当前 `save_player` 已遵守，F3 直接调用方未约束）。

---

## 二、P2 问题（14 项）

### P2-1 `now` 注入参数语义错误（cleanup_idem_keys / recycle_scan）：传 `now` 时保留期被忽略、可过度删除
- **位置**：`cleanup_idem_keys` L529-530；`recycle_scan` L558-559。
- **问题（静态推导）**：`if now is not None and parse_utc(now) < parse_utc(deadline): deadline = now`——当注入 `now` 早于自然截止线时，截止线被直接设为 `now`（即 **retention_days/max_days 被当作 0**），删除「早于 now」的一切，而非「now − retention」；当注入未来 `now` 时条件不成立、完全无效果。该参数名为 `now`，预期语义应为「以固定当前时间计算 `deadline = now − retention`」，现有实现无法表达固定时间语义，测试注入会在边界用例下**过度删除**（如应保留的 5 天前键在注入过去时间后被删）。当前无任何测试传 `now`（test_storage.py 均不传），缺陷未暴露。
- **修复建议**：`now` 提供时改为 `deadline = (parse_utc(now) - timedelta(days=retention_days)).strftime(...)`；`recycle_scan` 同理。并补一条传 `now` 的边界测试。

### P2-2 `row_to_player` 用 `col(k) or default` 吞数值 0，round-trip 失真边界
- **位置**：`row_to_player` L233-236（`level`/`exp`/`hp`/`mp`）、L249（`schema_version`）。
- **问题（静态推导）**：`int(col("level") or 1)` 中 `0 or 1` → 1。凡存储值为 0 的数值列（如 `level=0`、`hp=0`、`mp=0`、`schema_version=0`）读回后被改写为默认值（1/4），**破坏 TC-12 round-trip 全字段一致**（`db_roundtrip` 会报字段不一致）。`exp`（默认 0）恰好不受影响，故现有测试（夹具 level=35 等，conftest.py L53-95）未覆盖。
- **修复建议**：改为 `int(col("level") if col("level") is not None else 1)`（对 hp/mp/schema_version 同理）；或至少补 level=0/hp=0 的 round-trip 用例。

### P2-3 `_payload_to_json` str/bytes 分支与 `load_session` 解析不对称，会话载荷 round-trip 静默损坏
- **位置**：`_payload_to_json` L656-658（`isinstance(payload, (str, bytes)): return str(payload)`）；`load_session` L398（`_jloads(row["payload_json"], {})`）。
- **问题（静态推导）**：str/bytes 载荷被**原样落库**（不加 JSON 引号），读回时按 JSON 解析——非 JSON 串 → `_jloads` 兜底为 `{}`（**载荷丢失**）；恰好是合法 JSON 的串 → 被解析为 JSON 值（**类型被改写**，如 `"42"` 变 `42`）。两种都不满足「存什么读什么」。主路径（dataclass/dict 快照）不受影响，但该分支既存在又损坏，属**编解码不对称**。
- **修复建议**：删除 str/bytes 分支并统一 `_j(payload)` 编码（或反向在 load 侧按字符串语义读回）；快照类型文档化限定为 dataclass/dict。

### P2-4 `upsert_session` 不比对 version 即覆盖写，IDEM-3 依赖调用方无守卫
- **位置**：`upsert_session` L695-710（L702-705 `ON CONFLICT ... version=excluded.version`）。
- **问题（静态推导）**：会话 version 在冲突更新时被**无条件覆盖**为传入值——若陈旧指令携带旧 version 覆盖新 version，会话版本号回退，削弱 IDEM-3「期望 version 不匹配 → 拒绝」的防线；storage 侧无任何防护，全靠会话管理器前置校验（当前无生产者接线）。
- **修复建议**：`upsert_session` 增加可选 `expected_version` 参数，不匹配时抛错/跳过（与 TX-3 CAS 同风格）；或至少文档化「调用方必须先校验 version」。

### P2-5 `IdemKey.result_hash` 半消费：F4 模板先写幂等键后业务，重放摘要恒为 None
- **位置**：`idem_claim` 文档模板 L489-493（先 `write_idem_key` 后 `<业务写>`）；`write_idem_key` L715-723；`idem_find` L519-521（读 result_hash 供重放）。
- **问题（静态推导）**：契约 F4/IDEM-1 要求「命中 → 回放 result_hash 摘要」；但文档化模板在**业务结算前**插入幂等键，此时结果摘要尚不存在，`result_hash` 只能靠调用方预置（罕见），模板路径下恒为 None——`idem_find` 读出的 result_hash 大概率恒 None，重放退化为「该指令已处理」。
- **修复建议**：模板改为「业务结算 → 同事务内 `write_idem_key(result_hash=...)`（IDEM-2 同事务性不受影响）」，或提供 `update_idem_result(message_id, group_id, qid, result_hash)` 供事务内补写。

### P2-6 回收站 recycle_bin 四接口零实现（RC-2/3、TC-16）
- **位置**：repository.py 全文无 recycle_bin 方法；表结构在 `schema.py` L105-114（已建）。
- **问题**：契约 RC-2（30 天可恢复：add/restore）、RC-3（自动清理/一键清空/占用显示）要求的 storage 接口**全部缺失**，表定义但**零消费**。已登记 `contract_deviations.md` F-3（M6 编辑器递延），此处确认现状并标注验收 TC-16 当前不可满足。
- **建议**：按 F-3 排期，或至少提供 `recycle_add/restore/cleanup/usage` 骨架接口。

### P2-7 backups 表有效零消费：备份管线在 DB_SCHEMA_VERSION=1 / MIGRATION_STEPS 空下不可达（RC-4 相关）
- **位置**：`migrations.py` DB_SCHEMA_VERSION=1（L31）、MIGRATION_STEPS=[]（L37）、`migrate_database` L187-188（`version >= DB_SCHEMA_VERSION` 恒早退）；`pre_migration_backup` 仅在被早退拦住的路径内调用。
- **问题（静态推导）**：`pre_migration_backup`（VACUUM INTO 登记 backups）**任何情况下都不会被调用**（version≥1 恒 up_to_date），backups 表 M0 阶段恒空；RC-4（备份保留清理）与迁移前备份的实体路径均不可达。字段/接口定义但零消费（含 `add_column_if_missing`、`normalize_json_column` 两个导出助手零调用）。
- **建议**：M0 接受（骨架就位），但应在 contract_deviations 补记「backups 写路径不可达」；未来引入 MIGRATION_STEPS 首个迁移步时同步验证。

### P2-8 MIG-2 换包策略三选一与换包检测在 storage 层缺失
- **位置**：repository.py 全文无 `current_pack_id` 比对/换包检测；meta 表虽有 `current_pack_id/current_pack_version`（schema.py L88-89）但无读取/比对 API。
- **问题**：契约 §6.2 F5「换包（players.content_pack_id vs meta.current_pack_id 不符）→ ①自动迁移 ②全服重置 ③双存档并行」在 storage 层**无实现、无接口**；「字段级缺补默认/多忽略」只体现在 row_to_player 读路径（MIG-1 部分满足）。
- **建议**：M4/M6 换包里程碑在 storage 补 `pack_mismatch_detect / auto_migrate / full_reset / dual_save` 接口或明确落点（loader/hot_reload 侧）。

### P2-9 `_int_dict`/`_float_map` 对非法值直接 `int()/float()` 抛异常，违背 SCHEMA-6「不拦截加载」
- **位置**：`_float_map` L173-176、`_int_dict` L198-201；消费点 `load_world_state` L419（`world_stock`）。
- **问题（静态推导）**：若 world_state 某行 `world_stock` 值损坏/旧版为不可转数值（如 `null`、`"abc"`），`load_world_state` 直接抛 ValueError **加载崩溃**，与 SCHEMA-6「字段缺省=默认值，不拦截加载（只建议不限制）」的降级哲学相悖。
- **修复建议**：`_int_dict`/`_float_map` 对 `int()/float()` 包 try/except，失败键跳过或置 0（并补一条损坏数据加载不崩的用例）。

### P2-10 `currencies` 读回无类型校验
- **位置**：`row_to_player` L237（`currencies=_jloads(col("currencies"), {})`）。
- **问题（静态推导）**：与 `_obj_dict`（equipment 等有校验）不一致——currencies JSON 若为 list/str，直接作为 `Dict[str, int]` 进入 Player，下游 `player.currencies["gold"]` 行为异常。
- **修复建议**：仿照 `_int_dict` 加 dict 校验并 int 归一。

### P2-11 事务体内用 `repo.load_player` 读到事务前旧值（WAL 快照 footgun，API 未防护）
- **位置**：`load_player` L352-369（读连接）；`_load_player_in_tx` L580-584（已提供正确入口）；`recycle_scan` 已正确用后者（L569）。
- **问题（静态推导）**：`async with repo.tx()` 体内若直接调 `repo.load_player(qid)`，走**读连接**，WAL 下看不到当前事务未提交写，读到事务前快照——业务同事务读写不一致。`_load_player_in_tx` 已存在但为私有且未在 F3 模板文档中强调。
- **修复建议**：在 `repo.tx()`/`load_player` docstring 显式警示「事务内读玩家请用 `tx.fetchone`/`_load_player_in_tx`」，或将 `_load_player_in_tx` 提升为公共 `tx.load_player`。

### P2-12 `settle` 回调纯函数契约未防护（嵌套事务会触发拒绝）
- **位置**：`recycle_scan` L568-573。
- **问题（静态推导）**：`settle` 签名约定为纯函数（返回新 Player），若会话管理器误传一个内部再开 `repo.tx()` 的回调，会触发 `connection.py` 同任务嵌套事务拒绝（StorageTransactionNestingError），回收整体失败；当前无校验/文档强化。
- **修复建议**：在 `recycle_scan` docstring 显式声明「settle 必须为纯函数，禁止在回调内打开事务/访问 DB」；必要时入参断言。

### P2-13 死导入与不实 noqa 注释
- **位置**：`ensure_meta` L47（`# noqa: F401`，实际全文件未调用，仅 docstring 提及 L309）；`field` L22（`# noqa: F401（field 供类型注释可读）`——`field` 未在注解或代码中使用，注释说法不实）。
- **问题**：两处死导入；L22 的 noqa 注释属**不准确的工程补白**（幻觉维度的小瑕疵）。
- **修复建议**：删除两处导入；`ensure_meta` 如需 re-export 则列入 `__all__`。

### P2-14 job_id 折入 persistent_state 的 round-trip 死角（D-1 已登记，补强）
- **位置**：`player_to_row` L118-119（注入 `persistent["job_id"]`）；`row_to_player` L227（pop）；`codec_roundtrip` L589-595 / `db_roundtrip` L597-612。
- **问题（静态推导）**：若某系统在 `persistent_state` 自有 `job_id` 键（D-1 已登记风险），save 注入会**覆盖**它、load 弹出后 `persistent_state` 与原值不等 → `codec_roundtrip`/`db_roundtrip` 返回不一致；且 DB 行 `persistent_state` 内出现 storage 内部伪键，直读该列的迁移/编辑器可见脏数据。
- **修复建议**：按 D-1 建议改独立列（`players.job_id TEXT NOT NULL DEFAULT 'novice'`）彻底消除，或至少把 round-trip 用例覆盖「persistent_state 含 job_id」场景并显式拒绝。

---

## 三、规则实现状态映射（对照基准逐条）

| 契约条款 | 要求 | 实现状态 | 位置 / 备注 |
|---|---|---|---|
| RW-1 无上下线 | load 无需锁（WAL 多读） | ✅ 实现 | L352-369 读连接；connection.py 只读池 |
| RW-2 自动保存时机 | 每指令保存；战斗强制落盘；非战斗 200ms 防抖 | ⚠️ 部分 | 同步 commit ✅；200ms 防抖**未实现**（contract_deviations F-12 递延） |
| RW-3 原子写 | save=单事务 upsert players+sessions | ✅ 实现 | L377-381、L618-653、L695-710 |
| RW-4 写失败兜底 | OSError→人话+`.pending` 暂存补写 | ❌ 未实现 | 仅抛 StorageError；`.pending` F-1 递延（M4） |
| RW-5 备份快照 | VACUUM INTO/checkpoint；保存前 .bak | ⚠️ 部分 | `vacuum_into`/`pre_migration_backup` ✅；**保存前 .bak 未实现**（未显式登记递延） |
| RW-6 损坏恢复 | 启动 integrity_check + 关键表 round-trip 抽样；失败回退 .bak | ⚠️ 部分 | integrity_check ✅（connection.py L219-225）；round-trip 抽样/回退 .bak F-2 递延 |
| TX-1 单指令单事务 | 每指令一事务提交 | ✅ 实现 | `Repository.tx()` L334-338；connection.py BEGIN IMMEDIATE/ROLLBACK |
| TX-2 原子操作不拆分 | 结算性操作单事务、失败整体回滚 | ✅ 实现 | 事务模板 + TC-01~04 测试 |
| TX-3 世界资源 CAS | world_state 单行事务 + version CAS，冲突重读重试 | ✅ 实现 | L429-472（P0-1 哨兵回滚已修）；测试 test_world_cas* |
| TX-4 串行队列前置 | per-player 队列在事务外排队 | ⚠️ 部分 | 队列属 commands 层（未接线）；写侧由单写锁串行化 ✅ |
| TX-5 忙等重试 | SQLITE_BUSY 由 busy_timeout+单写队列兜底 | ✅ 实现 | connection.py busy_timeout=5000/写锁 |
| TX-6 错误可恢复 | 回滚后失败原因交 commands 层；不静默吞 | ✅ 实现 | StorageError 上抛，未见静默吞 |
| IDEM-1 message_id 幂等键 | (message_id,group_id,qid) 复合键 | ✅ 实现 | L477-479、schema.py PK |
| IDEM-2 同事务提交 | 幂等键与业务写同事务 | ✅ 实现 | `write_idem_key` L715-723（P1-1 已修：只查不插） |
| IDEM-3 会话 version 幂等 | 期望 version 不匹配拒绝 | ⚠️ 部分 | version 存/返 ✅（L400/L695）；**校验缺失**（见 P2-4） |
| IDEM-4 业务级幂等兜底 | 跨天/跨窗口由业务状态拦截 | — 非 storage 职责 | 业务层 |
| IDEM-5 7 天滚动清理 | idx_idem_created 支撑，7 天滚动 | ✅ 实现（参数） | L524-538（`now` 语义问题见 P2-1） |
| RC-1 僵尸会话 30 天回收 | 按退出结算后删除，单事务 | ⚠️ 部分 | 单事务 ✅；**默认不结算即删**（见 P1-1） |
| RC-2 回收站 30 天可恢复 | add/restore 单事务 | ❌ 未实现 | F-3 递延；recycle_bin 表已建零消费（P2-6） |
| RC-3 回收站自动清理 | expire_at 自动清理/一键清空/占用 | ❌ 未实现 | F-3 递延（P2-6） |
| RC-4 备份保留 30 天 | created_at>30 天删 .zip+元信息 | ❌ 未实现 | F-10 递延；且备份写路径不可达（P2-7） |
| RC-5 资源治理 | VACUUM 周级/阈值；磁盘预警；连接池上限+泄漏自检 | ⚠️ 部分 | auto_vacuum pragma+pool cap+leak_check ✅（connection.py）；周级 VACUUM/磁盘低水位 F-12 递延 |
| MIG-1 字段级迁移 | 缺补默认/多忽略 | ⚠️ 部分 | 读路径 row_to_player ✅；列级脚手架 add_column_if_missing ✅但零调用；迁移步表空 |
| MIG-2 换包策略三选一 | 自动迁移/全服重置/双存档 | ❌ 未实现 | 见 P2-8 |
| MIG-3 引用按 ID 显示按名字 | ID+名称冗余 | ✅ 实现 | data 类型 id+name；repository 原样往返 |
| MIG-4 旧配置结算 | 快照按旧配置结算、删配置降级 | — 非 storage 职责 | 会话/数据层 |
| MIG-5 迁移安全 | 迁移前强制备份/逐级单事务/迁移链完整/失败回滚继续跑 | ⚠️ 部分 | 管线骨架 ✅（migrations.py）；因 MIGRATION_STEPS 空而不可达（P2-7）；启动懒迁移 + 失败不置 _booted ✅ |
| TC-01~04 原子性 | 单事务全回滚 | ✅ 覆盖 | test_storage.py TC-01（购买回滚）、事务模板 |
| TC-05~08 幂等 | 并发双扣/回复前崩溃/业务幂等/重发 | ⚠️ 部分 | test_idempotency*/test_idempotency_no_orphan ✅；并发双购买（TC-05 完整语义）未测 |
| TC-09~11 损坏恢复 | 写失败兜底/崩溃恢复/备份损坏回滚 | ❌ 未覆盖 | F-1/F-2 递延 |
| TC-12 存档往返 | 每类快照序列化↔反序列化一致 | ⚠️ 部分 | codec/db roundtrip 测试 ✅；边界（level=0、str 载荷、job_id 冲突）未覆盖（P2-2/3/14） |
| TC-13 字段级迁移 | 旧版本存档迁移断言 | ⚠️ 部分 | 迁移机制无步不可真验；读路径缺补默认可验 |
| TC-14 换包后旧条目仍显示 | 旧条目按 ID+名称仍显示/红名 | ❌ 未覆盖 | 换包接口缺失（P2-8） |
| TC-15 僵尸会话回收 | 结算与删除同一事务 | ⚠️ 部分 | test_recycle_scan ✅（无 settle 注入，未验结算返还路径） |
| TC-16 回收站 30 天 | 恢复/清理/占用 | ❌ 未覆盖 | F-3（P2-6） |
| TC-17 随机种子往返 | random_seed 往返一致 | ⚠️ | seed 存/返 ✅；战斗续战语义属 battle 层 |
| TC-18 单写队列串行化 | 100 并发无 BUSY/无丢失 | ⚠️ 部分 | test_concurrent_save（20 并发）✅；100 并发与读不阻塞未达契约量级 |

---

## 四、幻觉与工程补白核对（维度③）

- **契约章节/规则编号注释：全部真实一致**。逐一核对 repository.py 头部与各函数注释：
  - `§二 存档读写（F1 管线…RW-3…RW-1）`、`§三 F3 事务模板`、`§四 幂等（IDEM-1~5，7 天保留滚动清理）`、`§五 回收（RC-1…D-05）`、`§六 迁移（首次访问懒迁移 D-06）`、`SCHEMA-5/6/7`、`MIG-1`、`MIG-5`、`TC-12`、`D-01`——与契约文本各节标题/编号**逐一吻合**，未发现错号或杜撰行号。
  - `4a §1.2 唯一数据源`、`4a §1.3`（world_state/sessions/idempotency_keys）、`4a §3.2 F3`、`4a TX-3`、`4a IDEM-1/2/5`、`4a RC-1`、`D-03 idx_idem_created` 等——均对应契约相应章节，正确。
- **修复追溯注释**：`修复（2026-08-18 dsh 审查 P0-1）`（L69-71）与 `修复（2026-08-18 dsh 审查 P1-1）`（L484-487）与 `contract_deviations.md §四`（P0-1 世界 CAS 半写、P1-1 idem_claim IDEM-2 陷阱）**一致**；`P2-8 修复：迁移结果可观测、取消信号不吞`（L312）与 migrations.py 的 `except Exception`（不吞 CancelledError）+失败打印行为一致。
- **工程补白标注**：`job_id 折入 persistent_state`（L61-63）有 contract_deviations D-1 对应登记 ✅；未发现「冒充定稿」或把【补白】当既有条款的标注（对比此前 M1 阶段 damage H1 类问题，本文件无同类复发）。
- **瑕疵（已计入 P2-13）**：L22 `field` 的 noqa 注释「供类型注释可读」不实；L47 `ensure_meta` 死导入。
- **任务描述行数差异**：任务称 repository.py「721 行」，实际 **747 行**——建议复核任务描述的审查对象版本是否与本文件一致（若按旧版本编号定位行号会偏移）。

---

## 五、审查备注

- R-1 本报告全部运行行为结论均为「静态推导」（环境禁止执行）。
- R-2 前次 P0-1（世界 CAS 半写）与 P1-1（idem_claim 独立事务早提交）已在代码中修复并有对应测试（test_world_cas_mid_way_conflict_rolls_back_all / test_idempotency_no_orphan_on_biz_failure），本次复查确认修复形态正确。
- R-3 多数未实现项（RW-2 防抖、RW-4 .pending、RW-6 抽样回退、RC-2/3/4、RC-5 VACUUM/预警、MIG-2 换包）已在 `contract_deviations.md` F-1/F-2/F-3/F-10/F-12 显式登记递延，非静默缺漏；其中 **MIG-2 换包策略未见递延登记条目**（P2-8 提请补登）。

---

## 六、修复优先级建议（合计）

| 优先级 | 条目 | 工作量 | 依赖 |
|---|---|---|---|
| P1-1 | recycle_scan 无 settle 拒绝/告警删除 | S | 会话管理器接线前 |
| P1-2 | 写代际号消除失效后陈写缓存 | M | — |
| P2-1 | now 参数改为 now−retention 语义 + 测试 | S | — |
| P2-2/3/10/14 | round-trip 边界（数值0、str 载荷、currencies、job_id） | M | 补用例 |
| P2-4/5 | upsert_session version 守卫、result_hash 补写 | M | 会话/指令层 |
| P2-6/7/8 | recycle_bin/backups/换包接口排期 | L | M4/M6 |
| P2-9/11/12/13 | 解析降级、事务内读 footgun、死导入 | S | — |

*（报告完）*
