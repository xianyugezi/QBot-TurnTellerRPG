# 审查报告：M0 复查批1-路3（存储层迁移）—— migrations / schema.db_schema_version

> 审查角色：QBot-TurnTellerRPG 代码审查 Agent（固定人格：见《审查角色_初始化.md》）
> 审查日期：2026-08-24（本环境无 bash 沙箱，任务明令禁止运行任何命令/脚本/验证，日期取任务指定文件名，与批次口径一致）
> 审查方式：**纯静态代码审查**；所有运行期行为结论均标注「静态推导」，未做任何执行验证。
> 结论：**有条件通过（P0 ×0 / P1 ×3 / P2 ×6）** —— 当前 MIGRATION_STEPS 为空（v1 无迁移步），无运行期数据丢失缺陷；三项 P1 均集中在「首条真实迁移步落地时必然踩中」的设计缺口（备份失败路径、迁移链完整性/round-trip 校验、add_column 助手与事务结构冲突），建议本轮或首条迁移步落地前修复。

---

## 一、审查对象

| # | 文件 | 行数 | 职责 |
|---|---|---|---|
| 1 | `qbot_rpg/storage/migrations.py` | 264 | db_schema_version 检测 / 字段级迁移（MIG-1）/ 迁移前 .bak（D-06）/ 履历（SCHEMA-8）/ 失败回滚（MIG-5） |
| 2 | `qbot_rpg/storage/schema.py`（db_schema_version 相关） | 180（相关 L83-94） | meta 表 DDL：db_schema_version INTEGER NOT NULL / migration_log DEFAULT '[]'（§1.3） |

辅助对照：`qbot_rpg/storage/repository.py`（_bootstrap 懒迁移调用方）、`qbot_rpg/storage/connection.py`（Database/tx()/写锁语义）、`tests/unit/test_storage.py`（迁移用例）、`contract_deviations.md`（递延登记核对）、前批《审查_M0_storage_20260818.md》（migrations 相关 P2-8/P2-9 修复核验）。

## 二、对照基准

- `细化_4a_存储层契约.md` v1.0（451 行）：**§六 存档兼容迁移（MIG ×5，L316-349）**——§6.1 两层版本模型（L318-323）、§6.2 流程 F5 迁移管线（L325-339：检测→迁移前强制 .bak（VACUUM INTO）→逐级迁移（每级单事务）→**round-trip 校验**→写 meta.migration_log→提交；失败整体回滚+服务携带旧版继续）、MIG-1（L345 字段级缺补默认/多忽略）、MIG-5（L349 **迁移链完整校验** meta.migration_log 有始有终 / 迁移前强制备份 / 失败回滚且服务继续跑）。
- ADR D-06（L56）：迁移执行时机=启动检测+首次访问懒迁移；迁移前强制 .bak；**失败回滚且服务携带旧版 schema 继续运行（绝不因迁移起不来）**。
- 验收用例：TC-13（L401 字段级迁移/履历/失败回滚旧版可读 round-trip）、TC-14（L402 换包后旧条目仍显示）。
- 前批《审查_M0_storage_20260818.md》migrations 条目：P2-8（吞 CancelledError + _bootstrap 忽略失败）、P2-9（孤儿 .bak / RC-4 清理缺失）修复核验；`contract_deviations.md` F-2/F-10/F-11 递延登记核对。

## 三、结果总表

| 级别 | 数量 | 条目 |
|---|---|---|
| 🔴 拦截 / P0 必改 | 0 | — |
| 🟡 注意 / P1 应改 | 3 | P1-1 迁移前备份失败在 try 之外，异常直抛首访即崩（D-06「绝不因迁移起不来」违反）；P1-2 迁移链完整性 + round-trip 校验缺失（MIG-5/F5/TC-13），链断档/跳级静默「migrated」且版本停滞；P1-3 add_column_if_missing 与逐级单事务结构冲突，首条真实迁移步调用即死锁 |
| 🟡 注意 / P2 建议 | 6 | P2-1 部分成功后续失败的 to_version 误报；P2-2 高版本库静默按 up_to_date（无降级/告警）；P2-3 ensure_meta 回填启发式=未标注工程补白 + players 单表判据漏判；P2-4 备份实体 .bak vs §1.3「.zip」口径不一致；P2-5「（P2-8）」自指外部审查编号注释；P2-6 RC-4 备份 30 天清理 + 孤儿 .bak 仍未闭环（F-10 复查） |
| 🟢 通过/确认 | 7 | 见 §四（含前批 P2-8 修复核验） |

## 四、🟢 通过/确认（含前批修复核验 + 无问题维度确认）

1. **前批 P2-8 已修复 ✓**：migrations.py:230 已由 `except BaseException` 改为 `except Exception`——CancelledError（BaseException 子类）不再被吞，直接重抛，注释「CancelledError 需重抛」与代码一致；repository.py `_bootstrap`（L314-323）现检查 `result.state == "failed"` 打告警且**不置 `_booted`** → 下次访问重试迁移（前批「失败无观测、重启前不再重试」闭环）。
2. **版本常量与初始值一致 ✓（§6.1/D-06）**：`DB_SCHEMA_VERSION=1`（migrations.py:31）与契约「db_schema_version（初始 1）」（L130/L323）、schema.py meta 表 `db_schema_version INTEGER NOT NULL`（L86）三者口径一致；`META_KEY="global"` 与 §1.3 单行 key 约定一致。
3. **meta 行管理 ✓（SCHEMA-8）**：ensure_meta（migrations.py:61-80）查不到即 INSERT 单行（db_schema_version/current_pack_id/current_pack_version/last_migration_at/migration_log='[]'/created_at/updated_at），字段与 §1.3 meta 表（L125-134）及 schema.py:83-94 完全吻合，无缺列/多列。
4. **迁移前强制 .bak ✓（RW-5/D-06/MIG-5 主体）**：pre_migration_backup（migrations.py:122-145）用 `VACUUM INTO`（connection.vacuum_into 不动主库，L300-310）生成独立 `.bak`，备份目录 mode 700（L39/131），并在 backups 表登记 `backup_type='pre_migration'`（与 BACKUP_TYPES 四值枚举一致，schema.py:26）；内存库显式跳过返回 None（仅日志语义）——处理正确。
5. **逐级单事务 + 同事务写版本与履历 ✓（F5/MIG-5 主体）**：迁移循环（migrations.py:199-229）每步 `async with db.tx()`（BEGIN IMMEDIATE），`db_schema_version=to_v` 与 `migration_log` 追加在**同一事务**内更新（L209-228），任一步异常 → tx() ROLLBACK → 失败路径（L230-243）→ 服务继续跑旧版（D-06）。**回滚安全主体正确**：meta 版本与履历不会半写。
6. **字段级工具就绪 ✓（MIG-1 主体）**：`add_column_if_missing`（PRAGMA table_info 检测 + `ALTER TABLE ADD COLUMN ... DEFAULT`，缺补默认/多忽略跳过）与 `normalize_json_column`（非法/空 JSON 兜底默认，SCHEMA-6）就绪待用；read 路径 `row_to_player`（repository.py:204-253 col() 语义）确实实现「缺补默认/多忽略」——模块 docstring L13 引用真实（非幻觉）。*注：add_column_if_missing 的可用性缺陷见 P1-3。*
7. **注释引用核验（维度③，主体无幻觉）✓**：migrations.py 全部注释引用的细化_4a 章节/条款——§六/MIG-1~5/D-06、§6.1/§6.2、F5、RW-5、SCHEMA-2/6/8——均真实存在且内容一致，未发现编造行号；与契约 §6 全部对应。*残余问题：docstring 将 F5 全流程（含 round-trip 校验）当作已实现描述（P1-2 文档侧）；未标注补白（P2-3）；自指「P2-8」（P2-5）。*

## 五、🔴/🟡 问题清单（🔴 P0 / 🟡 P1/P2）

### 🟡 P1-1 迁移前备份失败位于 try 之外：异常直抛 → 首次访问即崩，违反 D-06「绝不因迁移起不来」 【静态推导】

- **位置**：`migrations.py:195-196`（`pre_migration_backup(db)` 调用在 `for` 循环与 `try`（L200-243）**之外**）；对照 failure 处理只在 L230 起的 `except` 内。
- **实际**：D-06/MIG-5 承诺「迁移失败整体回滚，服务携带旧版 schema 继续运行（绝不因迁移起不来）」，而迁移管线第 1 步「迁移前强制 .bak」恰是最易失败的一步（VACUUM INTO 写盘 / backups INSERT / makedirs，磁盘满时正是 RW-4 场景）。该调用一旦抛异常（OSError/StorageError），不进入 L230 的 `except`，`migrate_database` 直接上抛 → repository._bootstrap（repository.py:319）同步上抛 → 首次 `load_player/player_exists/...` 即崩，**服务起不来**，且无任何「携带旧版继续」兜底。
- **契约应有**：4a D-06（L56）、MIG-5（L349「迁移前强制备份；失败回滚且服务继续跑」）、0.2（L45「绝不因更新起不来」）。
- **修复建议**：将 `pre_migration_backup` 调用移入同一 `try` 或单独包 `try/except`：备份失败 → 记录失败履历（result="failed"）+ 返回 `MigrationResult(state="failed", backup_id=None)`，由 _bootstrap 按既有失败路径告警并重试，**绝不上抛**。补用例：mock `vacuum_into` 抛 OSError → 断言 `migrate_database` 返回 failed 而非抛异常、服务可继续访问旧档。

### 🟡 P1-2 迁移链完整性与 round-trip 校验缺失（MIG-5/F5/TC-13）：链断档/跳级静默「migrated」且版本停滞 【静态推导】

- **位置**：`migrations.py:190-193`（步骤过滤 `s[0] >= version and s[1] <= DB_SCHEMA_VERSION`，仅按 `s[0]` 排序，**无连续性/完整性校验**）、`199-248`（循环后无「meta 版本 == DB_SCHEMA_VERSION」验证、无 round-trip 校验）、模块 docstring `L5-7`（把 F5「→ round-trip 校验 →」写成管线既有步骤）。
- **实际**：① **断档/跳级不拦截**：若步骤表为 [(1,2),(3,4)] 而当前版本 1，过滤后两步都入选并按 s[0] 排序执行——(1,2) 跑完后 (3,4) 在**错误的版本基线（实际 2）**上执行 fn，链完整性（MIG-5「meta.migration_log 有始有终」）无人校验；若末步 `to_v < DB_SCHEMA_VERSION`（如只有 (1,2) 而目标是 3），循环结束后返回 `MigrationResult(1, 3, ..., state="migrated")`，**meta 实际停在 2，却谎报已迁移到 3**。② **零步骤仍报 migrated**：版本 1 且 DB_SCHEMA_VERSION 升到 2 但 MIGRATION_STEPS 未追加步 → ordered 为空 → 仍备份一次、返回 `state="migrated"`（`applied_steps=()`），meta 停在 1；_bootstrap 因 state!="failed" 置 `_booted`，进程内不再重试——**每次进程启动都白备份一份并谎报 migrated，版本永不收敛**。③ **无 round-trip**：F5 明文要求「round-trip 校验（写回后读一致）」，TC-13 断言「迁移失败回滚且旧版可读（round-trip）」——代码迁移后零验证，一个写坏数据的迁移步会被无条件接受（repository 已有 codec_roundtrip/db_roundtrip 工具（repository.py:589-612）却未被迁移管线调用）。
- **契约应有**：4a MIG-5（L349「迁移链完整校验（meta.migration_log 有始有终）」）、F5（L335-336「逐级迁移 vN→vN+1（每级单事务）→ round-trip 校验（写回后读一致）→ 写履历 → 提交」）、TC-13（L401）。
- **修复建议**：① 循环前校验步骤链连续：`sorted` 后断言 `steps[i][0] == current_version` 且相邻 `from == prev.to`、最后 `to == DB_SCHEMA_VERSION`，否则 `raise MigrationError("迁移链不完整: ...")` 走失败路径（不静默）；② 全部步应用后（循环结束）读回 `meta.db_schema_version`，断言 `== DB_SCHEMA_VERSION`，不等则按失败处理；③ 每级或整链后执行一次 round-trip 抽查（调用 repository.db_roundtrip 或关键表读回比对），失败即整体回滚；④ 修正 docstring，避免把 round-trip 校验写成已实现步骤。补用例：构造断档步骤表/空步骤表 → 断言返回 failed 且版本不谎报。

### 🟡 P1-3 add_column_if_missing 与「逐级单事务」结构冲突：首条真实迁移步调用即永久死锁（挂起而非报错） 【静态推导】

- **位置**：`migrations.py:93-106`（`add_column_if_missing(db, ...)` 内部 `db.fetchall`（L101）与 `db.execute`（L105）各自 `async with self._write_lock`）；对照迁移循环 `L201-202`（`async with db.tx() as tx:` 已持有 `_write_lock`（connection.py:324-325），体内 `await fn(tx, db, ...)`）。
- **实际**：`db.tx()` 自 `BEGIN IMMEDIATE` 起持有**唯一写锁**直至 COMMIT/ROLLBACK；asyncio.Lock 非重入。迁移步若按模块 docstring 指示「调用方负责包进单事务（MIG-5 每级单事务）」调用 `add_column_if_missing(db, ...)`，其内部 `db.fetchall/execute` 会去抢**同一任务自己已持有的锁** → 永久挂起（死锁），连失败都不报。当前 MIGRATION_STEPS 为空故未触发，但**首条真实列迁移步照本模块引导写法落地即挂死服务**。同一根因已登记 `contract_deviations.md F-11`（connection 管理方法与 tx 同锁守卫，P2 递延），但本 helper 是该 footgun 在迁移路径上的**具体必踩触发点**，且 helper 签名收 `db` 而非事务句柄，与调用点（fn 同时收到 `tx` 和 `db`）语义相悖。
- **契约应有**：4a MIG-5（L349「逐级迁移每级单事务」）、TX-1/F3（L260/L245-254 禁止 tx 外残留写、单事务内统一走事务句柄）。
- **修复建议**：把 `add_column_if_missing` 改为接收事务句柄（`tx.fetchall`/`tx.execute`，如 `Transaction`/`RepoTransaction`）——迁移循环内调用方传 `tx` 即可，天然与单事务一致且消除死锁；同时为 `db.fetchall/execute/vacuum_into` 补「同任务 tx 归属检查」守卫（落实 F-11）。补用例：在 `db.tx()` 体内调用该助手 → 断言不挂起（能完成或显式抛错）。

### 🟡 P2-1 部分步骤成功、后续步骤失败时 MigrationResult 的 to_version 误报为原始版本 【静态推导】

- **位置**：`migrations.py:240-243`（失败返回 `MigrationResult(version, version, applied_steps=tuple(applied), state="failed", ...)`）。
- **实际**：若 v1→v2 成功（meta 已到 2）、v2→v3 失败，返回的 `to_version` 仍是初始 `version`（1），与 meta 实际（2）不符；调用方与迁移履历均被误导（失败履历 entry 的 from/to 用的是失败步自身 L234，正确；但返回对象的 from/to 错误）。后续重试靠 ensure_meta 读真实版本能自愈，属**报告性错误**，非数据错误。
- **修复建议**：失败返回时 `to_version` 应为「最后一个成功步的 to」（`applied[-1][1] if applied else version`），或直接回读 meta 现值。

### 🟡 P2-2 高版本库（version > DB_SCHEMA_VERSION）被旧程序打开：静默按 up_to_date，无降级/告警 【静态推导】

- **位置**：`migrations.py:187-188`（`if version >= DB_SCHEMA_VERSION: return ... note="schema 已是最新"`）。
- **实际**：D-06「meta.db_schema_version vs 代码预期 → 不符 → 迁移」对「不符」只处理了旧→新单向；当 db_schema_version 高于代码（被高版本程序迁移过的库回滚到旧程序）时，代码在未知 schema 上静默运行，无任何降级策略或告警（结构已知差异可能导致旧代码误读新列/新表）。
- **修复建议**：`version > DB_SCHEMA_VERSION` 分支打告警（并登记 ADR「不支持降级，遇到高版本库只读/提示升级程序」），至少不静默。

### 🟡 P2-3 ensure_meta 版本回填启发式 = 未标注工程补白，且以 players 单表判据可能漏判 【静态推导】

- **位置**：`migrations.py:64-66`（docstring 回填策略）、`71-72`（`has_players = SELECT 1 FROM players LIMIT 1`；`version = 1 if has_players else DB_SCHEMA_VERSION`）。
- **实际**：① 契约 D-06/F5 只说「meta.db_schema_version 比对 → 不符 → 迁移」，未定义「meta 缺失时如何判定老库/新库」——本启发式（有 players 数据 → 回填 1 触发迁移链；无 → 直写 CURRENT）是**契约未列的实现层收敛**，未按变更纪律 §0.3 / 补白纪律标注【补白】；② 判据只看 players：若库里只有 sessions/world_state 等数据而无 players 行（异常/迁移中断场景），会被误判为「全新库」直写 CURRENT 版本，**跳过本应执行的结构迁移**（表级 ALTER 波及所有表）。
- **修复建议**：在 `contract_deviations.md` 登记该回填策略（【补白】）；判据扩展为「任一用户数据表（players/sessions/world_state）有行即视为老库回填 1」。

### 🟡 P2-4 备份实体为 .bak（VACUUM INTO 产物）与契约 §1.3 backups「备份实体为 .zip」口径不一致 【静态推导】

- **位置**：`migrations.py:133-134/143`（`{uuid}.bak` 实体）；对照契约 §1.3 backups（L155「备份实体为 .zip 文件」）。
- **实际**：契约内部张力——§1.3 称 .zip，而 D-04/RW-5（L54/L226）允许「VACUUM INTO 或 checkpoint 后复制」；实现取 VACUUM INTO 产物命名为 `.bak`，与 RW-5「保存前 .bak」一致、与 §1.3「.zip」字面不符。实现合法，但属**契约内部冲突的取舍**，应显式收敛而非静默。
- **修复建议**：在 contract_deviations.md 登记「迁移前备份实体 = VACUUM INTO 生成的 SQLite .bak（采用 D-04/RW-5），§1.3 .zip 描述待契约修订」，并确认备份恢复侧（F-2/M6 启动器）按 .bak 兼容实现。

### 🟡 P2-5 注释自指外部审查编号「（P2-8）」，无来源 【静态推导】

- **位置**：`migrations.py:230`（`# noqa: BLE001 — 失败回滚后整体交接；CancelledError 需重抛（P2-8）`）。
- **实际**：与前批在 connection.py 发现并标注的同型问题（connection「P2-1：原死分支已删」）一致——注释引用外部审查制品编号，独立读者无法定位（虽本句附带自解释「CancelledError 需重抛」）。属维度③工程补白/注释纪律问题，非功能缺陷。
- **修复建议**：改为中性说明（如「失败回滚后整体交接；CancelledError 为 BaseException 子类，用 except Exception 使其自然重抛」），去除外部编号。

### 🟡 P2-6 RC-4 备份 30 天保留清理 + 孤儿 .bak 善后仍未闭环（前批 P2-9，登记 F-10 复查确认） 【静态推导】

- **位置**：`migrations.py:122-145`（pre_migration_backup 只登记不清扫）+ repository/全 storage 层（无 `cleanup_backups(retention_days=30)`）。
- **实际**：backups 表只增不清理、`idx_backup_created`（schema.py:146）建成无人消费（契约 RC-4 L311「created_at 距今 >30 天自动删除 .zip + 元信息行」缺失）；且 VACUUM INTO 成功后 backups INSERT 若失败（L140-144）留孤儿 `.bak` 文件无善后。该条已在 `contract_deviations.md F-10` 登记递延——本批复查确认**仍未闭环**，随 P1-1 修复（备份失败兜底）应一并补孤儿文件清理。
- **修复建议**：补 `cleanup_backups()`（事务：过期行 → 删实体文件（OSError 容错）→ 删行）；pre_migration_backup 的 INSERT 失败时删除已生成的 target 文件（或延迟到 VACUUM 成功后只保留登记文件），落实 F-10。

## 六、审查结论

**结论：有条件通过（P0 ×0 / P1 ×3 / P2 ×6）。**

- **当前代码（MIGRATION_STEPS 为空）常用路径静态推导无数据丢失/半写风险**：版本常量、meta 行管理、迁移前 .bak（VACUUM INTO 不动主库）、逐级单事务（版本+履历同事务提交）、失败回滚、懒迁移接线（_bootstrap 失败不置位重试）均正确；前批 P2-8（吞 CancelledError / _bootstrap 忽略失败）**已修复核验通过**。
- **需处理项**：P1-1 备份失败在 try 外 → 首访即崩（D-06 违反，建议本轮必改）；P1-2 迁移链完整性 + round-trip 校验缺失 → 链断档/空步静默「migrated」且版本停滞（MIG-5/F5/TC-13 未落地，首条迁移步落地前必须补）；P1-3 add_column_if_missing 死锁 footgun（与 F-11 同源，首条列迁移必踩）。三项 P1 均为「未来首条迁移步」的必踩点，M0 空步下不触发，故不升 P0，但建议随首条迁移步一并修复。
- **无问题维度确认**：维度③（幻觉）——引用的细化章节/条款全部真实且一致、无编造行号；仅 3 处注释纪律问题（P1-2 文档侧 overclaim、P2-3 补白未标注、P2-5 自指编号）。维度①错误路径之外的常用路径（检测/备份/逐级/履历/回滚）静态推导无数据错误。
- **合入门槛**：P1-1、P1-2、P1-3 修复（或登记递延并随首条迁移步一起落地）；P2-1~P2-6 建议登记 `contract_deviations.md` 或随 P1 一并处理，并回执用户拍板。

---

*运行行为结论均标「静态推导」，未经任何执行验证；如需运行级证据请授权沙箱后补做。*
