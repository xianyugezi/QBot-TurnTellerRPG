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
- **审计报告**：审查报告/硬编码审计_{战斗核心系,怪物职业系,系统玩法系}.md
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

### M1 定稿冲突拍板（用户 2026-08-19）
- **D5 互杀**：拍板「先手击杀生效→先手胜（玩家对怪物，玩家胜利）」——order 互杀分支若
  player_killed_enemy 置位 → 玩家胜；无先手击杀双死（dot 双杀）→ 平局（test_g4_* 两用例）
- **D2 派生被拒**：拍板「条件不足派生整体被拒」（TC-32）——实现已取，无改动
- **D11 链环**：拍板「环=特性允许」（TC-16）——validate_chain 只查入口可达性，环本身不报错
  （死配置=不可达节点提示，TC-17）；实现已合规，措辞落档

*M0 门禁：96 pytest 用例全绿 + G0 ARCH-OK + verify_m0 G1 exit 0。*
