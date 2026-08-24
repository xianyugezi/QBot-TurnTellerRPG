# 审查报告：M0 复查批1-路1（存储层连接与 Schema）—— connection / schema / __init__

> 审查角色：QBot-TurnTellerRPG 代码审查 Agent（固定人格：见《审查角色_初始化.md》）
> 审查日期：2026-08-24（本环境禁止运行任何命令/脚本/验证，日期取任务指定文件名，与批次口径一致）
> 审查方式：**纯静态代码审查**；所有运行期行为结论均标注「静态推导」，未做任何执行验证。
> 结论：**有条件通过（P0 ×0 / P1 ×2 / P2 ×7）** —— 两个 P1 均为错误路径/复用路径缺陷，常用路径与 Schema 本体无阻断项。

---

## 一、审查对象

| # | 文件 | 行数 | 职责 |
|---|---|---|---|
| 1 | `qbot_rpg/storage/connection.py` | 390 | Database：WAL/单写锁串行/tx() 事务模板（BEGIN IMMEDIATE）/多只读池/建库时机/权限 600-700/泄漏自检 |
| 2 | `qbot_rpg/storage/schema.py` | 180 | 7 表 DDL / 6 显式索引+PK 自动 / CHECK 约束 / PRAGMA 常量（Schema 唯一数据源） |
| 3 | `qbot_rpg/storage/__init__.py` | 1 | 包注释（零 NoneBot） |

辅助对照：`审查报告/审查_M0_storage_20260818.md`（前批报告，本批为复查；已核对前批 connection 相关条目修复状态）。

## 二、对照基准

- `细化_4a_存储层契约.md` v1.0（451 行）：表总表 §1.1（L64-75）、players 字段级 §1.2（L76-99）、其余表 §1.3（L101-163）、索引与 PRAGMA §1.4（L165-185）、TX 事务 §3（F3 模板 L245-254、TX-1~6 L260-265）、幂等 §4（IDEM-1 L288）、回收 §5（RC-5 L312）、迁移 §6（§6.1 L320-323）、验收 TC-01~18（L357-416，重点 TC-10/TC-18）。
- 前批《审查_M0_storage_20260818.md》：connection.py 相关条目（P1-3、P2-1、P2-2、P2-10、P2-11）修复核验。

## 三、结果总表

| 级别 | 数量 | 条目 |
|---|---|---|
| 🔴 拦截 / P0 必改 | 0 | — |
| 🟡 注意 / P1 应改 | 2 | P1-1 只读池信号量在 `_open` 失败路径泄漏（容量永久缩水）；P1-2 integrity_check 失败后对象进入「坏但可用」态 + 无 .bak 自动回退（前批 P1-3 未闭环） |
| 🟡 注意 / P2 建议 | 7 | P2-1~P2-7（见 §五） |
| 🟢 通过/确认 | 9 | 见 §四 |

## 四、🟢 通过/确认（含前批修复核验 + 无问题维度确认）

1. **7 表字段/类型/约束逐项一致 ✓（§1.1/§1.2/§1.3）**：schema.py 与契约逐字段比对——players 22 列（§1.2 全部：13 个 JSON 列 NOT NULL+DEFAULT `'{}'/'[]'`、`content_pack_id/version TEXT NOT NULL`、`schema_version INTEGER NOT NULL DEFAULT 4`、`last_seen_group TEXT NULL`、`created_at/last_active_at TEXT NOT NULL`）；sessions（PK+FK→players ON DELETE CASCADE、`session_type CHECK IN ('battle','alchemy','challenge_alchemy')`、version/random_seed/created_at/last_active_at）；idempotency_keys 复合主键 `(message_id, group_id, player_qid)`；meta（key PK、db_schema_version NOT NULL、migration_log DEFAULT '[]'）；world_state（version DEFAULT 0 CAS 列）；recycle_bin（object_type CHECK 三值）；backups（backup_type CHECK 四值）。**无缺字段、无多余字段、CHECK 枚举与契约逐一相同。**
2. **索引 7 组 ✓（§1.4）**：6 显式索引（idx_players_last_active / idx_players_pack / idx_sessions_active / idx_idem_created / idx_recycle_expire / idx_backup_created）全部存在、名称/列定义与 §1.4 一致，+PK 自动索引=7 组；schema.py 头注「6 显式 + PK 隐含 = 7 组」与契约计数一致。
3. **PRAGMA 五件套 ✓（§1.4 写死）**：journal_mode=WAL（内存库回退 memory 不报错）、busy_timeout=5000、synchronous=NORMAL、foreign_keys=ON、auto_vacuum=INCREMENTAL（`_open` 在建表前对写连接设置；读连接在写连接存在后不再设——符合 auto_vacuum 须建表前设置的约束）。
4. **F3 事务模板主体 ✓**：`tx()` 唯一业务写入口；BEGIN IMMEDIATE → 业务写 → 出 with COMMIT / 任意 `BaseException`（含 CancelledError）ROLLBACK（connection.py:315-352，`except BaseException` 路径覆盖取消）；同任务嵌套 tx 显式拒绝防自锁（L319-323）；单写连接 + `_write_lock` 串行（TC-18 单写队列语义，D-02）；TX-6 异常上抛不吞；COMMIT 失败走 ROLLBACK 兜底。**前批 P0-1（世界 CAS 提前 return 击穿原子性）位于 repository.py，不在本批文件内；本批 connection.py 的 COMMIT/ROLLBACK 分支无同类击穿。**
5. **只读池有界 + 等待超时 + 泄漏自检 ✓（RC-5 主体）**：`_read_sem(max_readers)` + `wait_for(acquire, 10s)` 超时抛 StoragePoolExhaustedError；`pool_stats()`/`leak_check()`/`close` 前校验齐备。
6. **【前批 P2-1 已修复】✓**：旧死分支 `if self._read_sem.locked() and self._max_readers <= 0` 已删除（connection.py:235 现为注释「P2-1：原死分支已删」），池耗尽由 `wait_for(acquire, timeout)` 兜底，无恒假条件残留；文件行数 391→390 与删除吻合。
7. **零 NoneBot import（SCHEMA-2/3a R1）✓**：connection.py / schema.py / __init__.py 均无任何 NoneBot import（仅 import aiosqlite/sqlite3/asyncio/stdlib），可脱离 NoneBot 单测。
8. **__init__.py ✓**：单行包注释，无多余导入/副作用；零 NoneBot。
9. **注释引用核验（维度③，无幻觉）✓**：代码注释引用的细化_4a 章节/条款——§1.4、§3.2 F3、RW-6、SCHEMA-1、TX-1、TX-4、TX-6、TC-18、D-04、RC-5、IDEM-1、TX-3、SCHEMA-6/7/8、§1.1/§1.2/§1.3——全部真实存在且内容一致；【框架】L1154/L1436/L1613、【规则】L107/L484 等行号与契约自身引用完全一致，未发现编造/错位行号；无把实现行为冒充定稿之处（见 P2-5 唯一补白标注疏漏）。

## 五、🔴/🟡 问题清单（🔴 P0 / 🟡 P1/P2）

### 🟡 P1-1 只读池信号量在连接打开失败路径泄漏：池容量永久缩水、不可自检 【静态推导】

- **位置**：`connection.py:236-255`（重点 244-248）；`acquired` 标志 236/239 赋值后**从未使用**。
- **实际**：`_read_conn` 先 `await self._read_sem.acquire()` 拿到令牌（236-239），随后 `await self._open(writer=False)`（248）若抛异常（磁盘 I/O、连接建立失败、PRAGMA 报错等），异常直接上抛——**令牌未释放**：`try/finally`（250-255）在 `_open` 之后才开始，只覆盖 `yield` 与归还路径，不覆盖 `_open` 失败。后果：池容量从 `max_readers` 永久减 1；连续失败 `max_readers` 次后**所有**只读操作永久超时抛 StoragePoolExhaustedError，即使故障已恢复也不恢复；`leak_check()` 只查 `_read_active`，该路径 `_read_active` 未自增，故**泄漏完全不可自检**（RC-5 泄漏自检承诺失效）。`acquired=True` 存在即证作者本意用更宽 finally 兜底但未实现。
- **契约应有**：4a RC-5（L312「aiosqlite 连接池上限 + 泄漏自检」）、TC-18（L416 并发读不阻塞）。
- **修复建议**：把 `acquire` 之后到 `yield` 整体包进一个 `try/finally`：`finally` 内 `if acquired: self._read_sem.release()`（并统一 `_read_active` 增减）；或改结构为「acquire → try(_open → 增 active → yield) → finally(减 active → 归还 → release)」，保证 acquire 成功后任何异常路径都归还令牌。补测试：mock `_open` 抛异常 → 断言后续并发读不减少（令牌已归还）。

### 🟡 P1-2 integrity_check 失败后对象进入「坏但可用」态：复用即绕过 .bak 回退（前批 P1-3 未闭环并加深） 【静态推导】

- **位置**：`connection.py:204-216`（`_writer`：先赋 `self._write`/`_schema_ready=True` 再校验，失败仅 `raise`）；`218-225`（`_check_integrity` 仅单行 `ok` 判断）。
- **实际**：① 校验失败时 `self._write` 已被赋为**损坏连接**、`_schema_ready=True` 已置位；调用方若捕获 StorageIntegrityError 后**复用同一 Database 对象**（契约 RW-6 语义本应是「回退 .bak 后重试，服务不崩」），后续 `_writer()` 因 `self._write is not None` 直接返回损坏连接，**不再重跑 integrity_check**，事务/读照常执行在损坏库上——.bak 回退被静默绕过。② 前批 P1-3（无「从 backups 取最近 .bak → 原子替换 → 重验」的自动恢复、无「关键表 round-trip 抽样」、失败后服务无法继续）**仍未闭环**：`_writer` 失败异常沿首个访问上抛，服务即崩，与 D-04「服务不崩」相悖。
- **契约应有**：4a RW-6（L227「integrity_check + 关键表 round-trip 抽样；校验失败 → 自动回退最近 .bak + 人话提示，服务不崩」）、D-04（L54）、TC-10/TC-11（L393-394）。
- **修复建议**：① 校验失败路径重置状态：`await self._write.close(); self._write = None; self._schema_ready = False`（并保留 `_integrity_ok=False`），使任何复用都重新触发完整建库+校验流程，杜绝「坏连接被静默复用」；② 落地或 ADR 显式递延「自动 .bak 回退 + round-trip 抽样」（本批建议至少做 ①，② 与前批 P1-3 同判，需在 contract_deviations.md 登记）。

### 🟡 P2-1 管理写方法与 tx() 共享同一非重入写锁：tx 体内调用即永久挂起（前批 P2-10 未闭环） 【静态推导】

- **位置**：`connection.py:276-298`（execute/fetchone/fetchall 各自 `async with self._write_lock`）、`300-310`（vacuum_into 同锁）、`315-352`（tx() 同锁）。
- **实际**：嵌套守卫（319-323）只拦「同任务再进 tx()」，不拦同任务在 tx 体内调用 `db.execute/fetchone/fetchall/vacuum_into`——asyncio.Lock 非重入，这些调用会**永久挂起**。同理：tx 体内 `await` 一个会写库的子任务（`asyncio.create_task`）→ 子任务等 `_write_lock`、父任务等子任务 → 死锁。当前迁移/管理调用均在 tx 外（repository.py 未在本批），属潜在 footgun。
- **修复建议**：管理方法进入锁前做与 tx() 相同的同任务归属检查（`if self._tx_owner is asyncio.current_task(): raise`）；并文档强制「tx 体内一律用 `tx.execute`」+ 测试守卫；或给 `_write_lock` 加超时以把死锁转为显式错误。

### 🟡 P2-2 权限 600/700 只覆盖主库文件：-wal/-shm 伴生文件与已存在目录未收紧（前批 P2-2 未闭环）

- **位置**：`connection.py:195-201`（仅 `os.chmod(fd_path, file_mode)` 主库文件）、`139-141`（`os.makedirs(mode=0o700, exist_ok=True)` 对已存在目录不改权限）。
- **实际**：WAL 产生 `<db>-wal`/`<db>-shm`，SQLite 按 umask（常见 0644）创建，未 chmod 600——WAL 内容可被同机其他用户读取，违背 §1.4「数据文件权限 600、目录 700」（L184）；`exist_ok=True` 不修正已存在的宽松目录。
- **修复建议**：`_open` 尾部/持久化后对主文件 + `-wal` + `-shm`（若存在）统一 chmod 600；目录侧 `os.chmod(parent, 0o700)` 兜底已存在目录。

### 🟡 P2-3 RC-5 资源治理在 connection.py 未落地：无 VACUUM 调度、无磁盘低水位探测（前批 P2-11 未闭环）

- **位置**：`connection.py` 全文件（仅 `vacuum_into`（300-310）与 `PRAGMA auto_vacuum=INCREMENTAL` 常量；无 `PRAGMA incremental_vacuum` 触发、无主库 `VACUUM` 调用、无磁盘低水位 <15% 探测、无文件超阈值治理）。
- **实际**：4a RC-5（L312「VACUUM 周级或文件超阈值；磁盘低水位 <15% 预警」）在连接层零落地；`auto_vacuum=INCREMENTAL` 只是预备位，未配增量回收触发。
- **修复建议**：M0 递延需 ADR 登记；若实现：`Database.vacuum_incremental()`/`vacuum_full()` + 周级/阈值触发 + `disk_avail_pct()` 供启动器预警（可并入前批 RC-5 递延清单统一裁决）。

### 🟡 P2-4 players.schema_version DEFAULT 4 与细化 §6.1「当前 5」口径冲突

- **位置**：`schema.py:51`（`schema_version INTEGER NOT NULL DEFAULT 4`）。
- **实际**：schema 忠实照抄 §1.2 表（L95「DEFAULT 4」），但契约 §6.1（L322）与 §1.2 说明列（L95「当前 5【框架】L444」）均称当前 schema_version=5。新建玩家行落 DEFAULT 4，随后启动懒迁移会把每一条新档判为「旧档」做一次无操作迁移，且「默认版本 ≠ 当前版本」长期并存易误导后续迁移路径判断。属契约内部张力，schema 按表执行无错，但建议对齐。
- **修复建议**：与契约裁定统一（改 DEFAULT 5 或在 §0.3 ADR 登记「新档默认 4、建档时显式写当前版本 5」），并同步 §1.2/§6.1 两处口径。

### 🟡 P2-5 工程补白标注疏漏：内存库共享缓存未标【工程补白】；「P2-1：原死分支已删」自指注释无来源

- **位置**：`connection.py:117-119`（类 docstring）、`130-135`（`:memory:`→`file:...cache=shared` 重写）、`235`（「P2-1：原死分支已删」）。
- **实际**：① 内存共享缓存库（进程内多连接共享）是契约未定义、属实现层新增的**工程补白**（契约仅 §7 测试基建允许 `:memory:`），未按本项目补白纪律显式标注【工程补白】；② 注释引「P2-1」指向外部审查制品，无溯源（本批已知其指前批 P2-1，但独立读者无法定位），且为批次过程的临时注记。
- **修复建议**：① 在 docstring 标注「内存共享缓存库 = 工程补白（测试/临时库用，契约 §1.4 仅约束磁盘库）」；② 将「P2-1：原死分支已删」改为中性说明（如「池耗尽由 wait_for 兜底」），去除外部制品编号。

### 🟡 P2-6 close()/复用卫生：关闭后 `_schema_ready`/`_integrity_ok` 未重置；close 与活跃读存在竞态

- **位置**：`connection.py:373-383`（close：清 idle、关写连接、`_write=None`，但 `_schema_ready`/`_integrity_ok` 保留）。
- **实际**：① close 后复用同一 Database：内存库场景（共享缓存库随最后连接关闭销毁）下 `_schema_ready` 仍 True，后续 `_read_conn` 跳过 `_writer()` 直读空库 → `no such table`；文件库场景 `_write=None` 会重开并重跑 DDL（IF NOT EXISTS 无害），但 `_integrity_ok` 沿用旧值。② close 与进行中读无任务级互斥，仅在 `leak_check` 一处快照判断，存在「check 后、close 循环前」读连接被取走的窄竞态（shutdown 场景低风险）。
- **修复建议**：close 尾部重置 `_schema_ready=False`/`_integrity_ok=None`；close 内对 `_read_active` 加同一锁或在 close 期间拒绝新的 `_read_conn` 获取。

### 🟡 P2-7 Transaction 执行原语不返回行影响信息：无 lastrowid/rowcount，upsert 判 INSERT/UPDATE 缺原语

- **位置**：`connection.py:87-90`（`Transaction.execute` 返回 `await cur.close()` 即 None）。
- **实际**：F3 模板（§3.2 L245-254）的 `tx.upsert_player/upsert_session/write_idem_key` 未在本文件实现（应落 repository.py，本批不评审），但低层原语连 `lastrowid`/`rowcount` 都不暴露，repository 层如需区分「首次 INSERT vs 已存在 UPDATE」（如幂等键命中语义）只能靠额外 SELECT，API 面偏薄。
- **修复建议**：`Transaction.execute` 返回 `cursor.lastrowid`/`rowcount` 或加 `execute_rowcount()` 变体；或确认 repository.py 采用 SELECT-then-write 策略并在 repository 批次核验。

## 六、审查结论

**结论：有条件通过（P0 ×0 / P1 ×2 / P2 ×7）。**

- **Schema 本体（维度①/②）**：7 表字段/CHECK/FK/PK、6 索引、PRAGMA 五件套与细化 4a §1.1~§1.4 **逐项一致、零缺漏**；F3 事务模板核心（BEGIN IMMEDIATE/COMMIT/ROLLBACK 含 CancelledError）正确；前批 P2-1 死分支已修复。
- **需处理项**：**P1-1** 只读池令牌在 `_open` 失败路径泄漏（静默永久缩容，建议本轮必改）；**P1-2** integrity 失败后「坏连接可被复用」+ 无 .bak 自动回退（前批 P1-3 未闭环，建议至少做状态重置 ①，② 登记 ADR）；**P2-1/P2-2/P2-3** 为前批未闭环项（管理方法死锁 / -wal -shm 权限 / RC-5 VACUUM 治理），P2-4~P2-7 为本批新提（schema_version 口径 / 补白标注 / close 复用卫生 / Transaction API）。
- **无问题维度确认**：维度③（幻觉）——本批文件注释引用的细化章节/条款全部真实存在且内容一致，【框架】/【规则】行号与契约自身引用吻合，未发现编造；维度①错误路径之外的常用路径（建库、读、写、事务）静态推导无数据丢失/半写风险（前批 P0-1 在 repository.py，本批文件已确认无同类问题）。
- **合入门槛**：P1-1、P1-2(①) 修复后可合入；P1-2(②) 与 P2 项建议登记 `contract_deviations.md` ADR 递延并回执用户拍板。

---

*运行行为结论均标「静态推导」，未经任何执行验证；如需运行级证据请授权沙箱后补做。*
