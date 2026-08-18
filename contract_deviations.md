# M0 实现层 · 递延清单与契约偏差登记（contract_deviations）

> 2026-08-18 · 对齐审查角色铁律：实现里出现设计文档没有的内容 = 疑点，必须显式标注；
> 本文件登记 M0 未实现/有意收敛/跨文档冲突的全部条目，供 M1+ 排期与用户/仲裁拍板。
> 参考：审查报告/审查_M0_content|storage|coredata_20260818.md（P1/P2 详述）。

## 一、M0 已实现的契约收敛（【补白】）

| # | 条目 | 收敛说明 | 依据 |
|---|---|---|---|
| D-1 | job_id 折入 players.persistent_state | 4a §1.2 players 宽表无 job_id 列（唯一数据源），按 D-01「固定列只承载框架必须字段」折入 persistent_state["job_id"]，写回剥离。**风险**：可能与某系统自有 persistent_state.job_id 键冲突（写覆盖/读弹出）——若冲突需改独立列 | 4a §1.2 / D-01；storage 审查 P2-7 |
| D-2 | 并发事务排队语义 | tx() 只拒绝「同任务嵌套」（防死锁）；不同任务并发事务由单写锁排队（TC-18 要求），非误判为嵌套拒绝 | 4a TX-4/TC-18；主 agent 修复 |
| D-3 | 空库只读路径自建表 | Database._read_conn 首次取连接前确保写连接建表（防 no such table） | 4a RW-1；A 组未收尾点修复 |
| D-4 | P0-1 世界 CAS 哨兵回滚 | save_world_state 冲突 raise 内部哨兵 → ROLLBACK（撤半写），外层返回 False | 4a TX-3；storage 审查 P0-1 |
| D-5 | idem_claim 只查不插 | 幂等插入必须由业务事务内 write_idem_key 承担（IDEM-2 同事务）；idem_claim 只读检查 | 4a IDEM-2；storage 审查 P1-1 |
| D-6 | 3f 契约层前置 | 3f 功能 TC 依赖 M3/M4/M6 系统，M0 仅落地 validator 可达性 + 补丁包可加载，其余登记 | 5d §2.1；verify_m0 §4 |

## 二、M0 明确递延（P1/P2，登记待 M 里程碑排期）

### P1 递延（应改但 M0 不实现，依赖后续里程碑接线）

| # | 条目 | 递延理由 | 落点 |
|---|---|---|---|
| F-1 | `.pending` 暂存补写 + 写失败人话兜底（RW-4/TC-09） | 涉及并发写队列与磁盘恢复重放，M4 指令层实装时落地（storage 已抛 StorageError 上层可捕获翻译） | M4 |
| F-2 | 启动 integrity 失败自动回退最近 .bak + 关键表 round-trip 抽样（RW-6/D-04/TC-11） | 恢复流程与启动器协作，编辑器/启动器里程碑实装（当前失败显式抛 StorageIntegrityError 不静默） | M6/启动器 |
| F-3 | 回收站四接口 add/restore/cleanup/clear/usage（RC-2/3/TC-16） | 表结构已建（schema OK），编辑器/会话管理器依赖时实装 | M6 编辑器 |
| F-4 | content 部位引用存在性 R-4（3e §5.2/TC-07） | 部位键空间语义依赖装备系统；field_meta 注释已标「正式表可注入 ref_target=slot」 | M2 装备 |
| F-5 | content Y-3 组合强度 / Y-7 未注册键 / x_ 字段内引用（TC-14/18/19） | 依赖效果系统语义；部分与跨文档冲突交织（见 §三） | M1/M6 |

### P2 递延（建议，登记）

| # | 条目 | 位置 |
|---|---|---|
| F-6 | -wal/-shm 伴生文件权限未 chmod 600 | connection.py |
| F-7 | 60s 读缓存共享可变嵌套 dict（快照可被外部串改） | repository.py |
| F-8 | ISO 字符串比较清理（全库 Z 定长前提下安全，防格式漂移） | repository.py |
| F-9 | -wal/shm 与已存在目录权限修正 | connection.py |
| F-10 | backup 30 天保留清理 + 孤儿 .bak 善后（RC-4） | migrations.py |
| F-11 | 管理方法 db.execute 与 tx 同锁非重入守卫（footgun） | connection.py |
| F-12 | 周级 VACUUM / 磁盘低水位预警 / 200ms 防抖合并（RC-5/RW-2） | storage 全层（M3/M 消息层） |
| F-13 | sessions random_seed 列与 payload 内一致性断言 | repository.py |
| F-14 | content schema_version 自动迁移链（ATO-6） | loader/registry |
| F-15 | content 滚轮 apscheduler 接线（TRG-6 口径） | hot_reload |
| F-16 | content zip 导入安全链（T3） | content 全层 |
| F-17 | content 旧局旧配置引用计数（D-05/SNAP-5） | 会话层 |
| F-18 | 3d 模板注册表 14 条全量登记（D-05 程序化锚点） | message_format/commands（M1 前） |
| F-19 | data TypeAlias/NewType 静态强校验、PlayerAttributes 单一 build_white 入口 | data/core |

## 三、跨文档冲突上报（用户/仲裁拍板，实现已取其一，不擅自裁决）

| # | 冲突 | 实现当前取 | 建议 |
|---|---|---|---|
| C-1 | 3b §3.2「source==target → 黄提示（自身增益合法）」 vs 3b TC-05「X→X 自环 → 红色拦截」 | TC-05 红（conditional 自环 R-5） | 建议保留红拦，同步修正 §3.2 表格文字 |
| C-2 | 3b ADR-05/TC-17「未注册自定义属性键 → 红拦」 vs 3e Y-7「未注册键 → 黄提示不拦」 | 条件加成 source/target 未注册键 → R-4 红（3b 场景语义）；effects.patch.target 等未注册键 → Y-7 黄（3e） | 建议按消费方语义区分并文档化 |
| C-3 | 3e §1.6「轮询=独立后台任务」 vs 3e2 D-02/TRG-6「轮询=apscheduler」 | 3e（asyncio 后台任务，零 NoneBot 依赖） | 项目接入定时器后统一接线（F-15） |

## 四、审查后修复记录（P0/P1 已修，单测闭环）

- **P0-1 防空转失效**（content 审查）：badref 每 3s 空转 → 失败路径补记触发源签名（hot_reload）→ test_dsh_regress
- **P0-2 部位互斥误判**（content 审查/测试验收组）：无向边去重 → test_dsh_regress
- **P0-1 世界 CAS 半写**（storage 审查）：哨兵异常强制 ROLLBACK → test_world_cas_mid_way_conflict_rolls_back_all
- **P1-1 formula 插值绕过 + 块注释误报**（content 审查）：插值保留扫描 + 块注释剥离 → test_dsh_regress
- **P1-1 idem_claim IDEM-2 陷阱**（storage 审查）：只查不插 + 事务内 idem_exists → test_idempotency* 
- **P1-1~P1-4**（coredata 审查）：conditional 接线 / 前缀格式泄漏 / 截断信号 / 负数黄提示 → test_coredata_regress

*M0 门禁：96 pytest 用例全绿 + G0 ARCH-OK + verify_m0 G1 exit 0。*
