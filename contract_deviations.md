# M0 实现层 · 递延清单与契约偏差登记（contract_deviations）

> 2026-08-18 · 对齐审查角色铁律：实现里出现设计文档没有的内容 = 疑点，必须显式标注；
> 本文件登记 M0 未实现/有意收敛/跨文档冲突的全部条目，供 M1+ 排期与用户/仲裁拍板。
> 参考：docs/审查报告/审查_M0_content|storage|coredata_20260818.md（P1/P2 详述）。

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
| F-30 | data 层双轨收敛：`StatusInstance`（status.py）与 `BattleSnapshot/CombatantSnapshot`（battle.py）为 3a §3.2 契约 spec 类型，但效果系统实际以 dict 形态落地（effects.py status_state：decay=str 类型+decay_subject/value、duration 扁平）、战斗快照实际为 1g3 dict（core/battle.py to_snapshot）——字段结构不一致、全库零消费。M0 复查已在两文件头标注【当前实现口径】；**M1 会话接线时收敛**（to_snapshot→BattleSnapshot 构造 / StatusInstance 补 decay_subject/value）或显式登记双轨保留。收敛前 U3「frozen 防误改」对真实 dict 快照未生效 | M1 会话接线 |

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

### M1 定稿对照修复（审查_M1_{damage,effects,battle,formula}_定稿对照_20260818.md，2026-08-18）
- damage **H1 O1 怪物防御率冒充「细化裁决」**→ 改【工程补白·待策划裁决】+ 登记 R-09（用户拍板：每怪物可配字段，见上表）
- damage **G1 斩击会心 +5% 悬空**（crit_prob 零调用）→ battle 会心接入 crit_prob+cap（p_override）/ **G3 base_attack_mult 零消费**→ battle 乘入攻击值 / P2 编造行号修正
- effects **G3 反弹「按 % 减伤并反弹」半支**（定稿 §3.4③ L138）→ 反弹同 % 减伤实伤 → test_g3_reflect_also_mitigates
- battle **G2 逃跑成功率接敏捷公式**（玩家属性定稿 L185 agi/(agi+敌agi)）→ test_g2 / **G3 stats_collector 补 weak_type/weak_elem**（定稿 §8.1 L326-327）→ / **G4 互杀 order 恒平局 + hp_ratio 致死前基准**（定稿 L60-63，原反射双死误判玩家胜）→ test_g4* / R-09 每怪可配（test_r09）
- formula **H1 补 [怪物血量百分比]**（定稿 §二③ L137）+ **H3/D1 结果类型白名单对齐**（定稿 L38 boolean/string≤1KB）

### M1-批3 审查修复（审查_M1_batch3_20260818.md，2026-08-18）
- **P0-1 条件求值未知键静默恒 True**（含印记条件的派生无条件触发，反安全）→ evaluate_condition 未知键安全失败（1c3 TC-13）+ marks 子句（C-1..C-5）经 battle marks_lookup 接线 → test_p0_marks_condition*
- **P1-1 ComboState.step_index `0 or -1` 快照回读错位** → from_dict 去 or-1 → test_p1_step_index
- **P1-2 marks_state 战末/逃跑不清零** → _settle 与 combo 双轴同清 → test_p1_marks_cleared
- **P1-3 技能 effects 零执行**（印记/打断仅道具路径可达）→ _resolve_combo_action 消费 skills effects（execute_action）
- **P1-4 打断/霸体闭环零接线**（apply_interrupt 零调用 + armor_active 永不置位）→ battle 技能 tag=interrupt → apply_interrupt；result.armor → armor_active
- **P1-5 被拒 _turn_acted 前置残留**（"不耗回合"被打穿 + 快照误判）→ 被拒回滚 + should_reject 补 skill def mp_cost → test_p1_rejected
- 附带基建：start() 尊重调用方注入自定义 RNG（测试 QueueRNG 确定性修复）
- P2×15 登记（target_hp_pct 简写语义/死代码/hold 免疫反馈/冷却降级分支/consume_marks 等，多数随 M5 或数据包）

### M1 定稿对照·批3 补测（审查_M1_{battle2}_定稿对照_20260819.md，2026-08-19）
- **P0-D1 印记条件语法复发修复**：combo 自建 _eval_marks 与 1d §3.1 规范语法不符（C-1 指定印记 min/max / C-4 all 齐备 / C-5 种类数）→ 全量转接 MarksManager.evaluate（唯一正确实现）+ 退化分支修正 → test_p0_marks_condition_with_lookup（AT-14 五原语）
- **D2 霸体窗口过早清位**（同回合敌后手打断不免疫）→ 清位移至 _after_actor_action（1c2 §2.2「使用期间」=行动阶段）
- **D4 技能 tag/effects/armor 未从 skills.json 合并**（标准技能路径不执行效果）→ _resolve_combo_action 从 resolve_skill 合并（sd.get）
- 幻觉注释 H1/H2/H3 修正（被拒 TC 引用、互杀 TC-11 措辞、start rng 注释）
- **D5 仲裁登记：定稿 L62（反伤互杀→平局）∨ 1g1c TC-11（先手击杀生效→先手胜）内部冲突**——实现取 L62（互杀一律平局），但按铁律上报用户/仲裁拍板，不得单方归平
- D3（interrupt 双实现归口 effects.json）、D6（印记按「结算末尾施加」顺序）、D7（被拒审计噪音）、D8（hp_ratio 致死着弹后记录）→ 登记递延，随 M1 收口/数据包处理
- **consume_marks 全库未实现**（1d P-1/AT-16/AT-17：消耗印记成功 / 不足即拒——不耗回合不改连段不清印记）→ 登记递延（数据包/技能库阶段，F-24 MP 通道一并）
- **marks 热重载降级不完整**（AT-08：apply_add 对未注册 mark 无门禁，0=不限重建无限叠）→ 登记 M 收口（apply_add 加未注册门禁 + 上限兜底）

### M1 定稿对照·批3 补测 combo（审查_M1_combo_定稿对照_20260819.md，2026-08-19；无 P0）
- **D4 step_index 写侧修复**（1c1a §2.1 形态机进度：派生/自动替换命中步从不写 step_index，前 P1-1 只修回读）→ apply_action 派生命中步写入 → test_c04 断言
- **D2 仲裁登记：TC-04（强行使用 cast to 按原技能降级）∨ TC-32（条件不足派生整体被拒）同场景冲突**——实现取 TC-32（整体被拒），上报裁决（原注释误称降级，已诚实化 H2）
- **D11 仲裁登记：loader skill_chains schema 与 ChainConfig 脱节 + R-5 环检 ∨ 1c3 TC-16「环=特性」冲突**——上报
- D1 冷却降级分支（定稿 L203/TC-31）、D3 validate_chain 零调用（校验器空转→接线数据包/loader）、D4b/D5-D10（节点出路/大招必填/缺省 tag 继承/overflow 配置/退出免疫反馈）→ 登记递延
- 幻觉注释 H1（行号交串 L355/356）/H3（缺省 tag 继承恒 +0）/H4（is_armored 声称两源）→ 修正/登记

### 硬编码审计 M 级落地（2026-08-19 · 33 份定稿 3 路审计，M×8/R×24/S×37）
- **审计报告**：docs/审查报告/硬编码审计_{战斗核心系,怪物职业系,系统玩法系}.md
- **M 文档修改已完成**（已落在 /root/docs_archive/RPG框架项目/ 8 份定稿）：
  M1 怪物防御率 R-09 回写（战斗数值层）/ M2 判定顺序 pipeline_order 开放 / M3 四时术士校验器降黄 season_group_max / M4 怪物难度 difficulty_template / M5 品质档位注册表 quality_tiers（统一 普通/精良/史诗/传说）/ M6 熟练度 tier_names 数组即级数（默认 7 级）/ M7 季节时段开放枚举（默认 4 季/5 时段）/ M8 素材稀有度唯一注册表
- **实现层承接登记（随各系统阶段落地）**：
  | 承接项 | 配置落点 | 落地阶段 |
  |---|---|---|
  | pipeline_order | formula.json 有序数组（默认现序） | 公式配置化（M2/数据包） |
  | season_group_max | skills 校验器软提示（默认5,0=不限） | 技能库校验 |
  | difficulty_template | enemies.json difficulty 档位/逐怪乘数覆盖 | M2 怪物 |
  | quality_tiers | 注册表数组（3/5/7 档均可） | M5 生活/强化 |
  | tier_names=级数 | proficiency.json（任意 1-N 级） | M5 生活 |
  | season/period 枚举开放 | 时间引擎配置（默认 4/5 保序） | M3 时间天气 |
  | rarity 注册表 | 素材唯一稀有度口径 | 数据包/M5 |
- **R 级高价值登记**：会心三处文字复写死值统一 formula crit.* / 命中 K 双定稿打架（0.2 vs 1）/ power 上限三处冲突（500/400/999）/ PV 减半 0.5 与换区恢复 0.5 参数化 / 经济基准（50 级尖峰/倍率带/斩杀回合）归口 formula.json 措辞「建议基准(可配)」/ 珠同名递减倍率配置化

### R 级高价值落地（2026-08-19 · 3 路子 agent 并行，17 项 · 15 份定稿）
- **战斗核心系** ✅：会心三处复写统一 formula crit.*（p_coef/tiers/super_tiers 可配）+ 超会心档数配置化（默认 4 档 0-3）+ 命中 K 统一（**默认 0.2，与实现层 damage.py 公式验收一致**；主 agent 修正 0.2↔1.0 方向）+ power 双路径上限统一（power.max=500 + formxul_max）
- **怪物职业系** ✅：PV 减半 `pv_half_ratio`（默认 0.5,0=不启用）逐怪可配 + 换区 `zone_change.pv_recover` + 经济基准措辞「建议基准（可配）」+ AI 默认值可配标注（breath_rounds/hungry/chain≥80%）
- **系统玩法系 R1-R9** ✅：对话深度 `max_dialog_depth` / 珠递减 `gem_diminish` / SP 解锁 `sp_panel[].value` / 幸运公式 `luck_formula+luck_scale` / 鱼饵 `bait_bonus+rod_full_bonus` / 90% 软锚 `milestone.items[i].desc_anchor` / 30 天回收统一 `lifecycle.recycle_days+backup_retention_days` / BOSS 阶段 `phases[]` per-entity / 刷新时刻 `refresh_time` 05:00（「4 点」清零）
- **待同步承接**：超会心 `super_tiers` ≡ 实现层 crit_mult_up（公式配置化阶段对齐字段名）；power 上限另两处权威（数值经济 400 封顶 / 技能库 999 自由）后续引用 formula.power.*

### M1 定稿冲突拍板（用户 2026-08-19）
- **D5 互杀**：拍板「先手击杀生效→先手胜（玩家对怪物，玩家胜利）」——order 互杀分支若
  player_killed_enemy 置位 → 玩家胜；无先手击杀双死（dot 双杀）→ 平局（test_g4_* 两用例）
- **D2 派生被拒**：拍板「条件不足派生整体被拒」（TC-32）——实现已取，无改动
- **D11 链环**：拍板「环=特性允许」（TC-16）——validate_chain 只查入口可达性，环本身不报错（死配置=不可达节点提示，TC-17；实现已合规，措辞落档）

### M0 复查修复（docs/审查报告/审查_M0复查_*_20260824.md，2026-08-24 · P0×0 / P1×11 / P2×41）
- **P1-1 只读池信号量泄漏**（connection）：acquire 成功但 `_open(writer=False)` 失败 → finally 仍 release 令牌，池容量不永久缩水 → test_read_pool_token_returned_on_open_failure
- **P1-2 integrity 失败坏连接复用**（connection）：`_writer` 校验失败时关闭坏连接并保持 `_write=None/_schema_ready=False`，复用重新走完整建库+校验流程（自动 .bak 回退仍登记 F-2 递延）
- **P1-1 回收默认丢数据**（repository）：`recycle_scan` 无 settle 且未 `allow_unsettled=True` → 拒绝删除（打告警跳过），防静默丢玩家材料 → test_recycle_scan_skips_without_settle
- **P1-2 缓存失效竞态**（repository）：写代际号 `_write_generation`，load_player fetch 返回后比对代际丢弃旧快照不写缓存；tx() 出口对事务内 dirty_qids 提交后统一失效 → 闭合「失效→提交」窗口
- **P1-1 迁移备份失败直抛**（migrations）：`pre_migration_backup` 异常包进 try → 返回 failed + 履历，由 _bootstrap 告警重试，服务携带旧版继续 → test_migrate_backup_failure_returns_failed
- **P1-2 迁移链完整性缺失**（migrations）：断档/跳级/末步<目标 → failed 不静默；全部应用后读回 meta 版本验证收敛 → test_migrate_chain_gap/incomplete_returns_failed
- **P1-3 add_column_if_missing 死锁 footgun**（migrations）：改为收事务句柄 tx（PRAGMA+ALTER 走 tx.fetchall/execute），消除 tx() 体内抢锁挂起
- **P1-1 ItemInstance 缺 stack_max**（data/item）：补 `stack_max: int = 99` 字段（4a §1.2 行格式；默认对齐 4b ITM-07）
- **P1-2/P1-3 data 双轨**（data/status、data/battle）：文件头标注【当前实现口径】（spec vs dict 落地），错引行号修正（3b §1.2→1b §1.4；4a §5.1→§0.1 术语表），收敛登记 F-30
- **P1-1 架构门禁漏检**（scripts/check_architecture）：`find_nonebot_imports` 补 `ast.ImportFrom` 的 `node.module` 判断（原只比对 alias.name，漏检 `from nonebot import X`）→ test_find_nonebot_imports_catches_from_import
- **run_all_tests.py 路径 bug**（顺带修复）：cwd=REPO(scripts/) 却传相对仓库根的 tests/unit → 阶段 1 恒红；cwd 改 REPO.parent，全量回归恢复绿

### M0 复查批2 修复（docs/审查报告/审查_M0复查_content_*_20260824.md，2026-08-24 · P0×1 / P1×12 / P2×44）
- **P0-1 monster_def_rate 负数误红拦**（field_meta）：`allow_negative=True`——负数 → Y-1 黄提示 + 运行期按 0（R-09 用户 08-18 拍板「负值→黄提示不红拦」）→ test_monster_def_rate_negative_hint_not_red
- **P1-1 marks/statuses duration 类型错注册**（field_meta）：statuses.duration → obj {turns,charges}（1b §1.2）；marks.duration → str "battle"/"turns:N"（1d §1.1），不再用 F_DURATION(number) → fixture statuses.json 同步对象形态
- **P1-2 marks.appliable_to 类型错注册**（field_meta）：str → list[string]（1d §1.1 字段6）→ fixture marks.json 重写（fire_mark 对齐样例 + 补 curse_mark，V-8 兑现）
- **P1-3 docstring 冒充细化字段表**（field_meta）：改述「M0 引擎简化口径，不冒充细化_1e 顶层 18 字段 / 3b §4.2 完整表」
- **P1-1 formula 安全例外两条绕过**（validator）：`_normalize_unicode_escapes`（\uXXXX/\xXX → 字符，封 `F\u0075nction`/`ev\x61l`）+ 方括号字符串键黑名单检查（封 `a["constructor"]["constructor"]("return process")()`）→ test_formula_blacklist_escape_bypasses_red
- **P1-1 manifest 错误重复上报**（loader）：删除 manifest 独立 check_pack + errors.extend（C 阶段全量已含，重复造成红拦翻倍）→ test_manifest_error_reported_once
- **P1-2 非法顶层 manifest AttributeError**（loader/models）：非 Mapping → 直接 R-5 module_structure 并早停 → test_manifest_non_mapping_blocked
- **P1-3 map 形态 Def.id 空串**（loader/models）：`from_entry` 加 `id_override`，loader 对 map 分支显式传键 → test_map_module_def_id_equals_key
- **P1-1 integrity_check 冒充自检 A**（registry）：删恒不可达 kind 内重复检查（dict 键天然唯一），补 modules⊇loaded + schema_version 一致两断言（跨表唯一注明由 validator NAMESPACES 前置拦截）→ test_registry_integrity_check_selfcheck_a
- **P1-1 BLK-5 暂停未兑现**（hot_reload）：paused 时 run() 循环/poll_once() 完全停止自动检测与重载（转手动 /reload，BLK-5 兑现；手动 reload 成功即复位）→ test_hot_reload_paused_poll_once_no_auto_reload

### M0 复查批3 修复（docs/审查报告/审查_M0复查_core_*_20260824.md + tests_m0，2026-08-24 · P0×1 / P1×8 / P2×31）
- **P0-1 空洞断言恒真**（tests/contract/test_message_format）：`assert ... or True` 删除，改真实断言「面板首行无裸 @」→ test_render_is_plain_string
- **P1-1 命中率 K 跨文档冲突**（用户拍板 K=1 唯一权威）：HitParams.k 默认 0.2→1.0、damage.hit_rate 默认 k→1.0，3b/1a 同口径；test_damage 断言同步（t03 50/50→0.5、默认值）→ 战斗命中率数值变化
- **P1-2 派生属性双套同名异构**（用户拍板可配置方案）：player_attributes 7 个派生函数全部改为委托 damage 参数化版（唯一实现，常数经 formula.json 可配），保持 3b % 对外口径；damage.crit_prob 补 cap=0 不限语义；mag_reduce 补测试 → test_mag_reduce_formula
- **P1-1 面板只读 base 白值**（message_format）：render_stats_line/render_panel 改消费 calc_all_final_attributes（加成/临时/条件层并入），面板值=战斗最终值；注释诚实化（原「M0 口径」冒充）→ 面板显示数值变化
- **P1-1 verify_m0 门禁盲区**：覆盖率段伪托「5d 允许估算口径」删除（基准无此条款，按 §7.4 显式标注简版）；门禁加 MIN_PASS_COUNT=100 防退化
- **P1-3 _validate_fixtures 无断言**：改为带断言版（legal 必须 0 errors；old_schema 改「迁移链 M6 覆盖」声明，不再「预期被拦」）
- **P1-4 test_message_format docstring 过度声明**：诚实化为「部分 TC」+ 未达项归 defer
- **P1-1 worldtime 骨架接口不对齐**：按 2a4c IF01~IF12 重建占位签名（原 now/is_daytime/tick_forward 完全不对齐且 now 语义反向）；里程碑 M1→M3 修正；删除 dummy_override 无据注释

## 五、职业设计规范 F 承接登记（JD-F 系 · 规范 v2.2 §十四 提议）
> 来源：职业设计规范 v2.2（三源整合 + 3 路审查）。**JD-F 前缀 = 职业设计规范侧编号**（避免与上文工程 F-1~F-29 冲突）；落地=框架工程需实现才能支撑对应职业。未实现前，设计引用标「规范层提议」。
> 关联：tpl_* 依赖已登记 F-27；反击容器关联 F-29；MP 消耗通道关联 F-24。

| JD-F | 内容 | 依赖职业（规范模板） | 落地阶段 | 关联现有 F |
|---|---|---|---|---|
| JD-F1 | stance 状态机：combatant `stance`(ground/air/down) + 转换表 + 倒地减防 30% + 快照持久化 + 倒地免疫参数(down_break_immunity_after=3/turns=2) | 三态流（ST）：御击者/三光剑士/枪空舞者 T10 | 姿态引擎里程碑 | — |
| JD-F2 | 命中修正：damage 层 ±1/3 姿态修正乘区（per-职业可覆盖，默认建议值非硬编码） | 同 JD-F1 | 姿态引擎里程碑 | — |
| JD-F3 | 怪物姿态/可反标签：细化_1f 技能池 `counter_tags`(blockable/dodgeable) + `stance_change` + `initial_stance`(飞行怪开局跃空) 字段 | 读招流（DF）：全部职业怪物侧 | 姿态引擎里程碑 + 细化_1f 扩展 | F-5 content 字段 |
| JD-F4 | 反击/闪袭追加：proc on_parry/on_dodge 事件（L0 现仅 on_attack/on_hit/on_skill/on_death/on_turn_start/on_turn_end）+ 免费追加动作 | 防反链（PR）：盾卫 T4/长枪/御击者 | 姿态引擎里程碑 | F-29（反击 proc 容器）|
| JD-F5 | 击落/倒地/打断起身：重击击空→倒地；陨星落断起身；起身动作替换（免费不耗 MP/冷却，占行动） | 三态流（ST） | 姿态引擎里程碑 | — |
| JD-F6 | 必中标记：倒地闪反成功→下回合必中 buff | 三态流（ST） | 姿态引擎里程碑 | — |
| JD-F7 | 处决循环：proc on_kill + cooldown_reset（击杀带印目标刷新冷却） | 处刑人 T7（EX） | 技能库/内容包阶段 | F-24 MP |
| JD-F8 | 完美格挡窗口：防反窗口内判定强化 | 盾卫 T4（PG） | 姿态引擎里程碑 | JD-F4 |
| JD-F9 | 无敌状态 L0：`invulnerable` 原子动作 | 护道人 T11（IN） | 效果系统扩展 | F-27 tpl |
| JD-F10 | 嘲讽/仇恨轴：`taunt`（1v1 简化=强制目标+增伤） | 盾卫 T4/护道人 T11（TH） | 内容包/怪物阶段 | — |
| JD-F11 | 连段收招攒资源：combo finisher 事件→资源轴 +N | 巨剑士 T1/三光剑士（RC） | 技能库阶段 | — |
| JD-F12 | 受击强化：on_hit 触发→层数轴累积 | 盾卫 T4（HG） | 姿态引擎/技能库 | JD-F4 事件 |
| JD-F13 | 蓄力减伤：蓄力期间 mitigation 叠加（可配置级：armor+mitigation 复合先行） | 巨剑士 T1（CM） | 配置级承接（可先行） | F-27 |
| JD-F14 | 资源轴自动变化钩子：end_turn 每回合 ±N（潮汐钟摆等） | 花葬客/能量轴职业 | 资源轴引擎扩展 | — |
| JD-F15 | 观星/读意图：怪物下回合意图标签 → [怪物意图] 条件键数据源（细化_1f 意图/锚点播报） | 读招流（DF）：三光剑士观星/御击者 | 怪物 AI 阶段 | — |
| JD-F16 | **组合规则层（组合表）**：N 种印记/状态按排列组合→M 种不同效果（织印者织结表 7 组合；元素连锁 风蚀+感电 双异常；岚霆双属性）。配置载体=`combos.json`（输入=印记集合+层数条件 / 输出=效果模板引用），条件引擎扩展：`combo:<印记A>:<层数>+<印记B>:<层数>` | 织印者/岚霆武士/百式灵武（组合系职业） | 效果系统扩展 | F-27 tpl / JD-F4 事件 |
| JD-F17 | **HP 消耗型技能（hp_cost）**：ActionCore 增 `hp_cost` 字段（类 mp_cost，按当前 HP 百分比或固定值扣血换资源/效果）；心脉缓冲=自伤先扣缓冲层不扣真血（tpl_shield 变体，护盾挡外部伤害/心脉挡自身扣血）。自伤可被免疫/减伤拦截（拦截链定序） | 命缚舞者（血量资源化） | 技能库/效果系统扩展 | F-24 MP 通道 / JD-F4 |
| JD-F18 | **延迟结算 DOT（delay）**：效果系统增 `delay: N` 参数——状态/伤害本回合挂载不结算，N 回合后结算（千影残影=delay:1 延迟复读 30% 伤害；残响终结=引爆全部 delay 层）。结算时机=回合开始/结束钩子（依赖 turn_start/turn_end 事件） | 千影（残影复读） | 效果系统扩展 | F-27 tpl / JD-F16 引爆 |

> 立项建议：姿态引擎（JD-F1~6/8/12）为**框架级新里程碑候选**（支撑 ST/DF 系职业）；JD-F7/F10/F15 随怪物/内容包阶段；JD-F13 可配置级先行。规范化 F-1~F-6/F-7~13/F-14 与 JD-F 系一一对应（规范层编号仅文档引用用）。

## 六、战斗语义裁定（用户 2026-08-23 · 全 A 采纳 · 影响所有职业/实现层）

| # | 议题 | 裁定 | 落点 |
|---|---|---|---|
| S-01 | consume_marks「无印被拒」副作用 | **完全免费**：不耗 MP、不耗行动、连段保留（符合 P1-5「被拒不耗回合不改连段」先例延伸） | consume 拒后零副作用；测试断言「拒了=啥也没发生」 |
| S-02 | pierce vs 免疫盾定序 | **免疫优先**：先判免疫 → 免疫该类型直接 0 伤；pierce 只穿防御系数不穿免疫 | 拦截链：免疫→…→pierce 定序 |
| S-03 | 免死 vs 斩杀定序 | **免死赢**：斩杀被免死挡下；BOSS 防斩杀靠 `kill_immune` 标记（非玩家免死） | 拦截链：免死先于斩杀判定；kill_immune 为 BOSS 专属 |
| S-04 | **敏捷行动条**（2026-08-25 用户拍板，全 A 采纳） | ①行动条 T=(双方敏捷和)/2，差值 d=敏差，回合末 acc+=d 给高敏方；②acc≥T 触发：**acc−=T（溢出保留）**；③触发回合=**行动机会转移**：高敏 +1 动 / 低敏 −1 动（总行动位不变）；④表现：玩家敏高→怪物不返回攻击消息；怪敏高→返回两条怪物行动消息；⑤全局生效 + per-实体开关 `action_bar`（默认 on，k=1 可调） | 设计稿：deliverables/agility_action_bar_v1.1.md；实现落点：细化_1g2 回合时序（行动位分配）；M1 战斗循环扩展 |

> 来源：封弊者策划书 v1.2（测试探针职业语义拍板）。

*M0 门禁：96 pytest 用例全绿 + G0 ARCH-OK + verify_m0 G1 exit 0。*
