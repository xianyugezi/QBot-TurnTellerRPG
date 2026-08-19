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
| F-20 | formula_engine 性能专项：每次求值起 Node 子进程 ~100-150ms（已接入 effects 默认求值），战斗内多公式求值会触「单指令 <200ms」预算——Python 白名单快路径 + Node fallback 或常驻 runner | M1-批2 前置 |
| F-21 | prepare_defense 战斗路径接入：整包效果/状态 → 防御行归一化（P1-2） | M1-批2 battle 组装 |
| F-22 | 反弹落地闭环：battle 层消费 reflect 副作用事件 → deliver_reflect 回注对方（P1-3） | M1-批2 |
| F-23 | S6/S7 攻防/三维组合上限接线到效果值聚合（P1-6） | M1-批2 已做 |
| F-24 | 1g1b T2 MP 资源校验缺失（1g1c TC-27「MP 不足被拒不改连段」不可满足）——技能 MP 消耗体系（普攻0/小技5-10/大招15-25，1a §2.2）待技能库阶段接线 | M5 技能库 |
| F-25 | element_modifier 元素附加/转化触发容器未实现（effects 定稿对照 G1） | M2/M5 |
| F-26 | pierce 魔法穿透 target=spr（无视一定百分比精神，定稿 §3.2/L121）未承接——execute_action pierce 仅 def，battle 元素管线未接 | M5 技能库 |
| F-27 | tpl_* 生存模板库（tpl_shield_30/15、tpl_mitigation_*、tpl_lifesteal_10、tpl_heal_* 等）零实现 + effects/statuses/marks 三表内容沉淀（G4） | 数据包阶段 |
| F-28 | 免死约束校验器空转（定稿 §9.2-6/H1：免死 1-3 次+致命免疫+续行互斥提示+PVP 可禁）未接线（G5） | M1 批3 / 效果校验 |
| F-29 | 反击特效引擎归口——反击=proc(on_hit) 容器接线未完成（G6，内容包作者配 defense 特效） | M1 批3 |

## 三、跨文档冲突裁决（2026-08-18 主 agent 对照定稿裁决，用户授权）

| # | 冲突 | 裁决 | 依据（定稿） | 落地 |
|---|---|---|---|---|
| C-1 | 3b §3.2「source==target → 黄提示」 vs TC-05「自环 → 红拦」 | **红拦**（统一自环/互环红拦） | 《玩家属性方案定稿》L148「每点力量+1智力——**防循环**」：条件加成设计意图即防自引用失稳 | 3b §3.2 文字已修正（2026-08-18 仲裁 C-1 标注）；validator conditional 自环 R-5（实现已对齐） |
| C-2 | 3b ADR-05/TC-17「未注册属性键红拦」 vs 3e Y-7「未注册键黄提示」 | **非真冲突**：两语境不同——属性定义/条件加成侧（3b，source/target ∈ 注册表）红拦；效果系统引用属性键侧（3e Y-7 stats 消费方）黄提示 | 《玩家属性方案定稿》L220「自定义属性**注册制（引用存在性校验）**」（属性侧红拦）＋ 3e §2.2 Y-7「消费方引用未注册键→提示」（消费侧黄） | 实现已区分：conditional source/target R-4；effects.patch.target 等 Y-7 |
| C-3 | 3e §1.6「轮询=独立后台任务」 vs 3e2 D-02/TRG-6「轮询=apscheduler」 | **定稿 L110 为准**：最终统一 apscheduler；M0 提供 `poll_once()` 供 M4 壳层 apscheduler 驱动，`run()` 保留为可测默认 | 《开发规则文档》L110「定时任务统一走 nonebot_plugin_apscheduler，与“操作时懒计算”并存」 | hot_reload.poll_once() 已实现（C-3 标注）；M4 接线 scheduler.add_job(watcher.poll_once, "interval", seconds=3) |
| R-09 | O1 怪物防御率（定稿 L27/L32 无算法，原「待策划裁决」） | **每怪物可配字段**：enemies.json per-monster `monster_def_rate`（默认 1.0=普通同玩家），战斗引擎取目标 combatant 配置乘入 ④⑤ 通道末因子；语义与怪物三档防御倍率（普通/精英×1.3/BOSS×1.5，定稿 L135-137）一致 | 用户 2026-08-18 拍板："怪物防御让用户自己给每个怪物都能调" | 细化_1a §1.11 更新；battle/channel 已接；用户=内容包作者 |

## 四、审查后修复记录（P0/P1 已修，单测闭环）

- **P0-1 防空转失效**（content 审查）：badref 每 3s 空转 → 失败路径补记触发源签名（hot_reload）→ test_dsh_regress
- **P0-2 部位互斥误判**（content 审查/测试验收组）：无向边去重 → test_dsh_regress
- **P0-1 世界 CAS 半写**（storage 审查）：哨兵异常强制 ROLLBACK → test_world_cas_mid_way_conflict_rolls_back_all
- **P1-1 formula 插值绕过 + 块注释误报**（content 审查）：插值保留扫描 + 块注释剥离 → test_dsh_regress
- **P1-1 idem_claim IDEM-2 陷阱**（storage 审查）：只查不插 + 事务内 idem_exists → test_idempotency* 
- **P1-1~P1-4**（coredata 审查）：conditional 接线 / 前缀格式泄漏 / 截断信号 / 负数黄提示 → test_coredata_regress

### M1-批1 审查修复（审查_M1_batch1_20260818.md，2026-08-18）
- **P0-1 S1/S5 覆盖规则恒真**：`power >= _boost_of(sdef)` 自身比较恒真 → 改为 `first_action_value >= existing.value`（统一原值口径）+ covered_low 分支可达 → test_m1_review_fixes（反向用例）
- **P0-2 formula_engine 零接线**：effects L0 公式框默认注入 formula_engine（_default_eval_formula），F-1~F-5 生效；性能专项登记 F-20 → test_m1_review_fixes
- **P1-4 chance lucky 模式**：mode="lucky" 走幸运修正分支（A-3）→ test_p14
- **P1-5 R3 resist_gain 统一出口**：S5-renewed/S1-replaced/stack 分支补 _r3_resist → test_p15
- **P1-8 重复修正器**：apply_lifesteal/apply_pierce/apply_mitigation 双份实现删除 + docstring 悬空引用修复 → test_p18
- **P1-1 total_damage pipeline 死代码**：删 pipeline 参数 + DamageContext/DamagePipeline 类型（接口不兼容，拦截链由 battle 直连 effects）→ test_p18
- **P1-7 派生封顶无消费**：新增 apply_derived_cap 纯函数（T32）→ test_p17
- G-1 快照五块 roundtrip 固化 → test_g1

### M1-批2 审查修复（审查_M1_batch2_20260818.md，2026-08-18）
- **P0-01 回合开始 dot 致死 ACT→DTH 非法迁移**：_LEGAL_EDGES 补 (ACT,DTH) → test_p001
- **P0-02 回合结束 tick dot 致死无死亡挂点**（0HP 不死单位/玩家死锁）：end_turn tick 后补 _death_check_side 挂点 → test_p002/test_p004
- **P1-01 F-21 每段结算前 _refresh_defenses**：新施加防御状态（reflect/absorb/mitigation）次击生效 → test_b7 改走真实装配
- **P1-02 _make_eval_formula 侧映射按当前行动者**：敌方技能/道具公式语义修正 → test_b8（补敌方侧）
- **P1-03 R3 dual 2 槽满分支补 _r3_resist**（与 P1-5 收敛目标自洽）
- BUG-1（trigger_halve 配置生效）在验收缺口路修复

*M0 门禁：96 pytest 用例全绿 + G0 ARCH-OK + verify_m0 G1 exit 0。*
