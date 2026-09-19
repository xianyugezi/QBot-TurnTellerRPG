# Changelog

本项目变更记录遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/) 与
[语义化版本](https://semver.org/lang/zh-CN/) 约定（开发规则 §6.2 L400-417）。

- **条目口径**（细化_M6_质量门禁 D7 CHG-05 / 开发规则 §6.2 L415）：提交信息为 `feat`/`fix` 的
  变更进 Changelog（按里程碑聚合一句话，不逐 commit）；`docs` 仅文档变更不进。
- **小节约定**（D7 CHG-01）：小节分 `### Added` / `### Changed` / `### Fixed` /
  `### BREAKING`；当前无 BREAKING 变更时（D7 CHG-02）BREAKING 节不出现。
- **版本段**：M0-M6 均未发布，条目暂存 [Unreleased]（D7 §3.3「Unreleased → 发布时归档」），
  首个版本发布时按 Keep a Changelog 归档至文末版本段骨架。

## [Unreleased]

### Added

- **批48（2026-09-20）**：**符文 2/3 阶特殊效果 + 战斗接线 + 3 合 1 端到端**（口径文档
  43-C/43-D；原案 §9 R6/R7/R8），含口径 §〇 结论 7 两处**机制缺口**修复。
  **缺口①重伤（治疗削减）**：`core/effects.py` 新增 `HEAL_TAKEN_STAT` 语义键 + 唯一聚合收口
  `status_stat_modifier_sum`（**复用既有 `stat_modifier` 状态动作族**，不新造第二套减益通道），
  `heal` L0 动作在**治疗计算处**按 `1+heal_taken/100` 消费（下限 0、S6 封顶可配）。
  **缺口②层数型增益**：`_aggregate_boost` 改为按状态实例 `stacks` **乘算**（上限 = 状态包声明
  `max_stack`，缺省回落 `config.stack_default_max`）——聚合体下沉 `effects.status_stat_modifier_sum`
  （battle 只保留 S6/S7 封顶）；附**逐字段回归对拍**（批48 前算法逐字复制为基准，非 stack 路径全等）。
  **战斗接线**：`core/runes.py` 新增 `rune_effect_refs_of` / `active_rune_effect_refs`，
  `EquipmentEngine.active_rune_effects`（同一 worn 枚举 + 同一 `active_rune_sockets`，副手失活继承），
  `dispatch_event` 新增 `extra_candidates`（缺省 None 零破坏），`BattleEngine._rune_candidates` 按侧/时点
  执行符文声明效果（`combatant.rune_effects` 随快照往返；无符文不新增键）；符文施加来源按次区分
  `侧@行动序号` → 既有 S3 stack 逐次叠层（**不改 `apply_status` 行为**）。
  **3 阶偏向性**：`bias={affinity,bonus_pct}`，宿主主/副相性（批38 `core/affinity`）命中 → 数值
  ×(1+bonus_pct/100)（RUNE-07 形状校验）。**3 合 1 端到端 + 闸**：`_exec_rune` 新增
  `synth_allowed=false → runes_deep_locked`、`settings.deep_craft.enabled` 非 true → `runes_disabled`
  （ctx 无该段不额外收紧）；1→2→3 逐阶、禁跳级、失败原子回滚。页脚批次串 + 文档同步。

- **批47（2026-09-20）**：**符文 1 阶数值 + 跨装备类型差异生效**（口径文档 43-B；原案 §9 R2/R4）
  —— `core/runes.py` 新增 1 阶数值**求值层** `rune_stats_of` / `sum_rune_stats`（`by_equip_type`
  的 default + **`items.type`** 覆盖差异解析**只在此处发生**；键白名单 = `GEAR_NUMERIC_KEYS`
  唯一源，自造键由校验器红拦）；`core/equipment.aggregate_bonus` 新增**符文数值贡献段**
  （**唯一收口**）——每件已穿戴装备经 `JewelSystem.active_rune_sockets`（**孔位读取唯一入口**，
  副手失活自动继承）读激活符文，按装备类型解析后走**同一** `route_bonus_into` flat/pct 路由
  （**不新开聚合/键**）；`EquipmentEngine`/`EquipmentEngineAdapter`/装配层注入
  `runes`/`items`/`jewel`（缺省 → 零贡献，既有行为逐字段一致）。**孔位互斥补对向**：
  `JewelSystem.mount` 新增「该孔位已被同件实例符文占用 → `slot_full`」，与 `mount_rune`
  共用 `_rune_slot_taken`（一处判定）；解析不到穿戴 uid 不误拦。**本批不新增 gear_stats 词条键**
  （1 阶符文复用既有 FLAT/PCT/COMBAT 键族，口径 §三.2）。`core/battle.py`/`core/effects.py`
  零改动（2 阶重伤/层数缺口、2·3 阶战斗接线留 43-D）。页脚批次串同步。

- **批46（2026-09-20）**：**符文地基**（口径文档 43-A；原案 §9）——新增符文数据模块
  `runes.json`（三阶独立刻度 `tier ∈ {1,2,3}`，**不复用** quality 四档）与纯解析引擎
  `core/runes.py`（`rune_tier_of` / `by_equip_type` default+覆盖 / 3 合 1 纯函数
  `resolve_rune_upgrade`）；孔位/镶嵌**复用** `core/jewel.py`（`mount_rune`/`unmount_rune`/
  `active_rune_sockets`，绕过珠的槽级门票，与装饰珠**共用同一孔位数组**、一槽一物互斥）；
  镶嵌状态挂 `ItemInstance.uid` 的落档容器 `persistent_state["rune_sockets"]`
  （**不挂 EquipmentSlot**——卸装不丢；自由 dict 缺补，无需 DB schema 升级）；
  3 合 1 执行器 `UpgradeEngine` 新增 `rune_upgrade` 子类型（3×同阶同 id → +1 阶、**必成**、
  **禁跳级**、`_commit` 原子提交，档位走独立三阶解析）；`settings.rune_sockets.default_count`
  缺省三孔全开（可配）；总闸复用 `settings.deep_craft.enabled`（默认关）。专项校验
  `content/rune_models.validate_runes`（阶枚举 / default / stats 键空间 / effects 引用 / family）。
  编辑器可见 + 页脚批次串同步。**本批不接战斗效果**（1 阶数值上板 / 2·3 阶战斗接线留后续批）。

- **批45（2026-09-20）**：**数值校准 · 装备占比 40% → 60%**（决策记录 §三 补充 1，用户 2026-09-19）
  —— 面板预算参数化 `settings.panel_budget`（`white:equip:buff` 设计份 + **装备面板倍率**
  `equip_stat_mult`，**缺省 1.0 = 现状**）；veinborn 校准 `equip_stat_mult=2.25` → 装备份 8→18、
  装备占比 **60.00%**、面板总功率 20→30（+50%），**白值 7 / buff 5 绝对数值不动**。
  倍率在 `core/equipment.aggregate_bonus` **读时**作用于面板轴 `atk/dfn/hp`（**不改落档实例**，
  改回 1.0 即回滚），战斗直读词条（会心/耳栓/超会心/吸免穿）与其余属性不动。
  怪物侧新增 `settings.monster_scaling`（`hp_mult/atk_mult` **缺省 1.0**；veinborn 校准 1.5 = +50%），
  `con` 按防御系数非线性做仿射补偿 `(con+K)×def_factor−K`（校准 1.0828）→ **中值档三只代表怪
  斩回完全一致**（普通 7 / 精英 20 / Boss 24），不配置时逐字段不变。编辑器可见（中文名 +
  说明卡）+ 校验器（结构/类型/负值红拦）+ 页脚批次串同步。

- **批44（2026-09-20）**：深度打造**投入概率暴击**（决策记录 §七 用户裁定）——投料提交时按
  图纸档掷一次概率，命中给额外品质经验（倍率可配），使高档图纸有机会冲破常规经验上限达到
  **品质 10**；**用概率暴击替代拉高 cost cap / 强制扩充材料表**（cap 默认值与 13 行概率
  阶梯不变）。参数全部包声明：`craft_rules.quality_exp_crit`（逐档概率 铜15/银10/金7/彩5%、
  逐档倍率 ×2、适用档、`additive_exp`、`affects_quality_level`、`rolls_per_craft`、
  `exp_cap`；**缺省关** → 不掷、不消耗随机数，不暴击路径与既有**逐字段一致**）。
  随机走批40 玩家级随机流（可注入确定性 RNG 复现）；命中提示走模板表新键
  `deep_craft_crit_gain`；编辑器参数可见（中文名 + 说明卡）；页脚批次串同步。

- **批43（2026-09-20）**：强化系统**六档上限替换**（H3：品质等级 → +3/+6/+9/+12/+15/+18，
  替换既有 `max_by_rarity` 5/8/10/12；旧档经 `legacy_quality_level_by_rarity` 桥接读上限、
  既有 `enhance_level` 原样保留不降级）+ **每 4 级特殊词条**（跨度可配；从相性池经
  `affinity.resolve_available_entries` 抽取，载荷写入实例 `enhance_affixes`）+ 词条族注册
  （`data/gear_stats.py` 唯一源：回复强化 / 减益概率 / 增益概率 / 弱点伤害为 `_pct` 键；
  冷却缩减为**占位**只登记展示不接引擎）。`core/enhance_affix.py`（纯函数上限/词条）；
  曲线与石档延至 +18；编辑器上限表可见；页脚批次串同步。

- **批41（2026-09-19）**：深度打造**主体**（图纸 / 材料 / 打造主流程）——新指令 `/精造`
  （学习 / 预览 / 投料打造）；图纸作为 `items` 的一种（`blueprint_*` 字段，不新造平行物品
  体系）+ 材料等级/品质/cost 字段 + `settings.deep_craft` 打造参数段（等级加权 / 品质经验 /
  品质等级阈值 / 13 行品质概率阶梯 / 图纸档 cost 上限）；深度层引擎 `core/deep_craft.py`
  （纯函数：等级·品质经验·品质抽取·cost·防退化 N2）；投料→基础产出 100% 走**公用合成层**，
  随机用玩家级随机流（批40）；产出装备实例带 `uid` 入背包。属性与套装词条相性抽取（C 节）
  留批 42。

- **批 D（2026-09-14）**：存档「内容包通用状态格子」——新表 `player_pack_state`（每
  玩家×内容包 一格，`pack_id` 运行时传入，框架零包名/零业务键）+ `db_schema_version`
  1→2 迁移步（新库经 SCHEMA_DDL 直接具备、旧库幂等补表且既有数据无损）+ 纯存储层读写
  API `qbot_rpg/storage/pack_state.py`（get/set/patch/clear/list + 64 KiB 单格上限）。
- **M0-M5 归档欠账回填说明**（D8 ACC-03）：M0-M5 历史 verify（verify_m0~m5）全部只 print
  到 stdout、无文件写出——欠账原因 = G1「verify 输出留档于仓库 docs/」自 G1 成文起未落地
  （【批3A】P0-2/P1-5）。处置：M0-M5 不补历史报告文件，仅登记；**自 M6 起 verify_m6 按
  ACC-02 统一归档 docs/verify/**（验收单 m6_checklist.md / 归档报告 m6/verify_m6_<日期>.md /
  冒烟留档 m6_smoke.md / 覆盖率报表 coverage_latest.txt，写入者 = verify_m6.py）。
- **M6（进行中，2026-08-28 批8 收官）**：verify_m6 两段式门禁 + M6 唯一验收口径——段一 8 项
  验收单（D8 VG-01~09：热重载回退/冒烟闭环/故障注入六类/覆盖率≥80%/ruff-mypy-pytest/
  内容包 validator 全绿/里程碑验收单/CHANGELOG+归档）+ 段二 M2-M5 DELAYED 承接收口
  （DLY-01~10：到期扫描 + verify_m4 批次7-01 翻转 + 六组裁决转 pytest/残留登记）+
  ACC-01 验收单 + ACC-02 归档契约（本条目随 D7 CHG-03 预留条目收口）。
- **M6（进行中，2026-08-28 批7 落地）**：质量门禁载体落地——覆盖率实算+阈值断言（COV）/ ruff-mypy
  工具链（LNT）/ CHANGELOG 建档回填（CHG，本文件）/ CI 流水线（CI）/ PR 评审模板（RVW），
  待本批次与 verify_m6（D8）收口（D7 CHG-03 预留条目）。
- **M6 提交规范差距登记**（D7 CI-06）：历史提交无 scope，M6 起按 `<type>(<scope>)` 执行
  （存量提交不追溯改写，只校验新增）。
- **M5（2026-08-27）**：消息模板与渲染层实装——前缀公共接线/战斗渲染 BREP-01~25/结算连段/
  全仓 emoji 降级与登记表/背包筛选链/verify_m5 门禁 81 TC（六门禁全绿）。
- **M4（2026-08-26）**：指令系统实装——reward 发放器/统一条件引擎/指令解析层/NPC/商店/任务/
  签到/指令组/校验器接线 + e2e 冒烟集成收官（154 断言，五门禁全绿）。
- **M3（2026-08-26）**：地图/副本/时间天气系统实装——时间引擎/天气引擎/地图行走/刷怪/副本两型/
  换区追击/安全区快照死亡 + 集成回归收官（951 全绿四门禁过）。
- **M2（2026-08-26）**：怪物体系完成——enemies 八段 + AI 决策引擎 + 战斗挂接 + 世界边界
  （dsh 三批审查 P1×6 修复，G3 门禁 361 全绿）。
- **M1（2026-08-19）**：战斗系统实装——伤害公式/效果系统/公式引擎三模块 + 战斗引擎
  （状态机/回合时序/完整接线）+ 定稿冲突三拍板落地（先手击杀/派生整体拒/环=特性）。
- **M0（2026-08-25）**：实现层框架骨架实装——data/storage/content/core 四层 + G0 架构检查 +
  测试体系 + verify_m0 门禁（M0 复查三批 P0×2 / P1×31 全部修复）。

## [v0.1.0] - 待发布（版本段骨架）

<!-- 首个版本发布时：将 [Unreleased] 条目归档至此，格式 `## [vX.Y.Z] - YYYY-MM-DD`
     （Keep a Changelog；D7 CHG-01）。M0-M5 各条目日期 = 记录.md 对应里程碑段落完成日
     （D7 CHG-02；M1 记录.md「更早」节无日期，已核对 git 提交日期 2026-08-19 属实——
     M1 定稿落地 42443a5/补测修复 bf83742 等均 2026-08-19，批7B 审查 P1-1 核销）。 -->