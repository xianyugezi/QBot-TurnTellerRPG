# 审查_M6设计_批2_组A_F6内容包冒烟（静态审查，j-space）

- 审查对象：【F6 内容包冒烟】docs/实现层规划文档.md L3441-3444
- 审查方式：**纯静态审查**（本环境无 bash 沙箱，禁止运行任何命令/脚本/验证；全部运行行为结论标注「静态推导」）
- 审查基线：定稿【框架】§4.3/§四.1 + 细化_5d/细化_3a + 已实现参考（fixtures 四件套、scripts/verify/verify_m0.py、scripts/e2e_m4_smoke.py、qbot_rpg/content/loader.py、qbot_rpg/core/battle.py、qbot_rpg/commands/battle_commands.py）
- 审查维度：①缺漏 ②错误 ③幻觉 ④跨文档

## 0. 结论概览

| 级别 | 数量 | 摘要 |
|---|---|---|
| P0 | 0 | 无阻断性缺陷 |
| P1 | 4 | ①battle 留桩与已实现战斗栈冲突且弱于定稿；②模拟一局前两环（注册/锁定）无落点；③五档包逐档覆盖点与 validator 全绿验收缺失；④verify_m0「缺模块」断言空转+语义误标 |
| P2 | 8 | M6 口径跨文档冲突、五档包位置未定、归档未点名、未复用 e2e_m4_smoke 约定、迁移对象未区分、冒烟链三形态、G0 延期欠账、目录名不全 |

幻觉检查：**未发现 F6 编造五档包内容或编造冒烟断言**（四类样例包断言与 verify_m0/定稿语义一致；「旧 schema 迁移」有 M0 显式登记 M6 覆盖背书）。唯一「断言语义编造」风险来自已实现的 verify_m0 注释（见 P1-4），非 F6 本身。

---

## 1. P0（无）

无。F6 设计不会导致冒烟不可执行或直接假绿；主要问题是「设计口径与已实现现状冲突」和「覆盖点缺失」，均属 P1 及以下。

---

## 2. P1（4 项）

### P1-1 ｜ F6「battle 接口按 A3 留桩」与仓库已实现战斗栈冲突，且弱于定稿
- 位置：docs/实现层规划文档.md L3443（F6 实现要点）vs L3168/L3185（A 组范围边界）vs 定稿【规则】L285、细化_3a TC-22 L398
- 内容：F6 写「battle 接口按 A3 留桩，本路先跑通属性/背包/渲染链路」。该前提在规划文档自身 A 组（L3168「battle.py 战斗状态机（后续路挂接，本路留接口）」、L3185「battle.py 仅留状态机接口与快照协议」、L3203「业务指令本路只留注册骨架」）内自洽，但**与仓库已实现状态冲突**：
  - `qbot_rpg/core/battle.py` 已是 1841 行真实引擎（start/player_act→TurnReport，见 battle_commands.py L14-15 引用）；
  - `qbot_rpg/commands/battle_commands.py` L836-859 已把 /攻击 /防御 /逃跑 /道具 注册进 Router，`cmd_battle_attack`（L802）已消费 `ctx["battle_engine"]`（真实引擎实例，L30-32 ctx 契约）；
  - `core/message_format/battle_render.py` BREP-01~25 模板全部就绪（verify_m5 已测渲染）。
- 问题：若 M6 冒烟仍「留桩」，将绕过现成真实引擎，冒烟比定稿 §四.1「模拟一局战斗（锁定→攻击→结算）」与细化_3a TC-22（模拟一局战斗通过）要求的更弱——桩不能验证战斗状态机/结算/战报渲染，等于把已实装能力关掉再搭桩。
- 修复建议：删除/改写「留桩」口径；F6 冒烟的 攻击→结算 直接复用真实 `BattleEngine`（经 `ctx["battle_engine"]` 注入，装配参照 e2e_m4_smoke 的 ctx 构造方式），冒烟断言到真实 TurnReport/渲染输出。如确要保留桩，须在 F6 显式写明桩的断言面（调用顺序/参数/桩返回值/渲染行）并登记「战斗链路真实验证留后续路」——但鉴于引擎已存在，建议直接真实。

### P1-2 ｜ 「模拟一局」前两环（注册→锁定）依赖未实装指令，F6 未说明实现/桩口径
- 位置：docs/实现层规划文档.md L3443；已实现参考 scripts/verify/verify_m5.py L14-17、scripts/_gen_templates_full.py L90
- 内容：冒烟链 = 注册→锁定→攻击→结算。但「静态推导」现状：
  - /注册：仅 RUL-08 注册门槛文案（`basic_commands.py` L130-131 `TPL_REGISTER_GATE`、`explore_commands.py` L30-31），**无 cmd_register 实现**；verify_m5 L14-15 明确「/注册 指令未实装（DELAYED，首次注册流程依赖角色存档/职业推荐链，归属后续批次）」。
  - /锁定怪物：仅在 `parsers.DEFAULT_WHITELIST`（parsers.py L110）出现，**无 handler/无注册**；_gen_templates_full.py L90 标注「/锁定怪物｜待接线」。
- 问题：F6 把「注册→锁定」写进冒烟链路，但这两个指令当前无落点；不说明是「本路实现 /注册 /锁定怪物」还是「注入桩/直调函数」，冒烟无法按指令路径跑通（与 细化_3a TC-20 L396 的「NoneBot 夹具打桩 /注册→/锁定→/攻击→/道具」口径也不同：TC-20 明确是夹具打桩，F6 未写）。
- 修复建议：F6 明确两环口径：(a) 实现 /注册 最小流（名字+职业→属性初始化）与 /锁定怪物（当前地图怪目标→进战斗）；或 (b) 显式声明「本路经夹具/函数级直调替代指令路径」，并登记缺口的后续批次归属（对齐 verify_m5 的 DELAYED 诚实化惯例）。

### P1-3 ｜ 五档数据包逐档覆盖点未定义；五档包 validator 全绿未列入 F6 验收标准
- 位置：docs/实现层规划文档.md L3443-3444（F6 实现要点/验收标准）；定稿【规则】L285（对 content/ 全部预置包跑 validator）；细化_3a TC-22 L398（content/ 全部预置包 demo_blank~demo_full validator 全绿 + 模拟一局）；细化_5d L95（M6 verify 含四类样例包加载矩阵）
- 内容：F6 仅写「demo_blank 最小可玩包起步，按 §4.3 五档数据包逐步建立」，未定义：
  1. 每档包的内容范围/模块集（空白=？新手 1-15 含哪些模块；成长/进阶/完整递增什么；29 文件总表按档取舍——M2 verify L3477 提到 29 文件逐项加载断言）；
  2. 每档的 validator 覆盖点（各档应断言的模块红/黄计数）；
  3. 每档是否都跑「模拟一局」、各档链路差异（demo_blank 无怪物时模拟一局如何定义）；
  4. **五档包 validator 全绿未列入 F6 验收①**（验收①只列四类样例包断言；定稿与 TC-22 均要求 content/ 全部预置包 validator 全绿——G1 模板 L3452 有「预置内容包 validator 全绿」，但 F6 本任务验收项缺失）。
- 修复建议：在 F6 实现要点/验收中逐档列出「包目录/模块集/validator 断言点/是否模拟一局」四元组，并把「五档预置包 validator 全绿 + 每档模拟一局」纳入验收标准；对齐细化_3a TC-22 与细化_5d L95。

### P1-4 ｜ verify_m0 四件套「缺模块」分支断言空转 + docstring 语义误标（防 M2/F6 四件套口径被抄错）
- 位置：scripts/verify/verify_m0.py L62-69（docstring 写「badref / missing_mod：必须被红拦（PackLoadError）」）、L80-99（实际代码）；tests/fixtures/packs/missing_mod/README.md L5-9（「软性，不红拦」）；tests/unit/test_content.py L286-297（test_missing_mod_pack_y6 断言 report.ok）
- 内容（静态推导）：missing_mod 包语义是 **Y-6 黄提示 + 包仍挂载**（定稿 4.5 L787、细化_3e §1.2、README、单测一致），**并非红拦**。verify_m0 的 `_validate_fixtures`：
  - docstring 写「missing_mod 必须被红拦」，与语义矛盾（误标）；
  - 代码对 missing_mod 在 try/except 两个分支都不记 failure → 该包断言是**空转**（无论被拦/不被拦都通过），连「Y-6 提示存在」都未断言 → 违反 F4 防空转（L3433）。
- 与 F6 的关系：F6 验收①与 M2 verify L3477 都写「缺模块**提示**」（正确措辞，与定稿一致）；但实现 verify_m6 时若照抄 verify_m0 docstring「必须被红拦」会产生**编造断言**（假断言）。verify_m0 注释本身即「编造语义」（把黄提示写成红拦）。
- 修复建议：F6 明确 missing_mod 断言 = 「Y-6 警告存在（module=statuses）＋包仍挂载（report.ok）＋未声明文件（npc.json）不加载」，并同步修正 verify_m0.py L65 注释与补上有效断言（防空转）。

---

## 3. P2（8 项）

### P2-1 ｜ 里程碑号 M6 口径跨文档冲突（F6 所属 M6 vs 实际 verify_m6 的 M6）
- 位置：docs/实现层规划文档.md L3481（M6 接线闭环=F5-F6/G2-G4）vs docs/实现层启动手册.md L42（M6 数据框架=5a/5b/4c/4d/4e/6 系）vs scripts/run_all_tests.py L42（M6 数据框架，同启动手册）vs 细化_5d L95（M6 数据 verify_m6=114 条：3e/3e2/5a/5b/5c）
- 内容：同一里程碑号 M6 在规划文档定义为「接线闭环（热重载/冒烟/质量）」，在启动手册/run_all_tests/细化_5d 定义为「数据框架（编辑器/GM/图鉴/成就/PVP）」。F6 属前者；而 `run_all_tests.py` L34-43 的 m6 槽位（当前 None）将接入后者。F6 冒烟内容实际归 细化_5d L95 M6 数据 verify 的「四类样例包加载矩阵」。
- 修复建议：统一 M6 命名（建议以启动手册/run_all_tests/细化_5d 的「数据框架」为准，F6 冒烟并入其 verify_m6 门禁；或显式登记两套里程碑表的映射关系），避免 verify_m6 实现者对 F6 归属产生歧义。

### P2-2 ｜ 五档数据包存放位置未定（content/ vs tests/fixtures/packs）
- 位置：docs/实现层规划文档.md L3443；定稿【规则】L207（content/ 预置内容包 demo_blank~demo_full）、框架 §15 L1593-1597（content/ 下五目录）；细化_5d §5.1 L200（tests/fixtures/packs **四个各一，禁止更多**）
- 内容：细化_5d 对 tests/fixtures/packs 有硬约束「四个各一，禁止更多」。F6 未指明五档包（demo_blank 等）放哪。若误放 tests/fixtures/packs/ 将违反「禁止更多」；应放 content/（规则 L207/框架 §15/TC-22 均指向 content/）。
- 修复建议：F6 写明五档预置包目录 = `content/demo_blank~demo_full`（对齐框架 §15），与 tests/fixtures/packs 四件套（测试基线）分离；当前仓库无 content/ 目录，F6 需补建。

### P2-3 ｜ 冒烟/verify 归档位置与 CHANGELOG 未在 F6 点名
- 位置：docs/实现层规划文档.md L3444（「verify 归档」，未点名位置）；G1 L3453（verify 输出留档于仓库 docs/）；细化_5d L234（门禁记录在《开发记录》登记，附 pytest 摘要）；G1 L3452 + M6 行 L3481（每里程碑 verify 后更新 CHANGELOG）
- 内容：F6 只说「输出留档（verify 归档）」，未写具体路径/文件命名；也未提 CHANGELOG 更新（M6 行 L3481 有「CHANGELOG 归档」但 F6 任务内未承接）。
- 修复建议：F6 写明归档 = 仓库 `docs/`（含《开发记录》门禁记录，附冒烟输出摘要）+ CHANGELOG 更新条目，并给出冒烟输出文件的建议命名（如 docs/冒烟日志/m6_smoke_YYYYMMDD.md）。

### P2-4 ｜ F6 未引用 e2e_m4_smoke/e2e_m3_smoke 的既定冒烟约定
- 位置：docs/实现层规划文档.md L3443；参考 scripts/e2e_m4_smoke.py（零 NoneBot、固定 now+种子、两次运行摘要逐字一致、工程补白显式标注、Smoke 断言收集器）
- 内容：仓库既有冒烟脚本已确立约定（确定性铁律、补白显式标注、断言收集、独立可运行、退出码 0=全绿）。F6 未声明 M6 冒烟沿用这些约定，存在实现漂移风险（如随机战斗结果导致不可重放）。
- 修复建议：F6 增加一句「M6 冒烟沿用 e2e_m4_smoke 约定：零 NoneBot、固定 now+种子、两次重放逐字一致、工程补白显式标注」。

### P2-5 ｜ 「旧 schema 迁移」对象未区分（内容包迁移 vs 存档迁移），迁移链未定义
- 位置：docs/实现层规划文档.md L3443-3444；细化_5d §5.1 L202（旧 schema 包走迁移）、TC-5d-35 L292（构造旧 schema_version **存档** → 迁移 → 字段级缺补默认/多忽略）；qbot_rpg/storage/migrations.py（存档侧迁移链已实现：DB_SCHEMA_VERSION/MIGRATION_STEPS/migrate_database）；qbot_rpg/content/loader.py（**内容包侧无迁移链**，old_schema 目前仅「容忍加载」）
- 内容：F6 一句话「旧 schema 迁移」同时承担了两个不同对象：① 内容包 old_schema（schema_version 0，当前 test_content.py L300-310 仅断言「不红拦」，非真正迁移）；② 存档 schema_version（TC-5d-35，storage 侧已实现）。内容包侧的 0→1 迁移链（字段级缺补默认/多忽略 + schema_version 收敛 + registry 不污染——§5.1 要求）在 loader 中尚不存在，F6 未定义。
- 修复建议：F6 分列两个迁移对象：内容包迁移链（loader 侧新增，断言 schema_version 收敛、registry 未被污染、删除配置按「无效果/无链/无印」降级）与存档迁移（复用 storage/migrations.py，断言字段级缺补默认/多忽略）。确认 old_schema fixture 的 `manifest.schema_version=0` 被迁移到 1 而非仅容忍。

### P2-6 ｜ 冒烟链存在三种形态，F6 用其一未登记统一
- 位置：docs/实现层规划文档.md L3443（注册→锁定→攻击→结算）vs 【规则】L285/细化_5d L66/L253/细化_3a TC-22 L398（锁定→攻击→结算）vs 细化_3a TC-20 L396（注册→锁定→攻击→**道具**）vs 【规则】L435/细化_5d L221（/注册 /锁定 /攻击 一轮闭环）
- 内容：F6 的「注册→锁定→攻击→结算」有据可依（规则 L435 发布检查单冒烟形态 + 细化_5d L221 G0），与定稿 §四.1「锁定→攻击→结算」是同一冒烟的不同表达，不算冲突；但三种链形态散落多处且无归口说明。
- 修复建议：F6 注明「模拟一局 = 规则 L435 发布冒烟形态（注册→锁定→攻击→结算）；内容包冒烟（定稿 L285/TC-22）为锁定→攻击→结算，注册为前置」一句话归口，避免后续实现各按各的链。

### P2-7 ｜ G0 门禁「注册→锁定→攻击→结算」冒烟延期至 M6，欠账未登记
- 位置：细化_5d L221（G0 架构前置：L2/L4 冒烟打通 注册→锁定→攻击→结算 **M0 开工前必须全绿**）；tests/contract/test_e2e_smoke.py（目前仅 validator + 最小装载，**无模拟一局**）
- 内容：按细化_5d，该冒烟应早于 M0 全绿；实际 M0-M5 已过、M6 待补，冒烟缺位在门禁口径上未登记延期。
- 修复建议：在 细化_5d G0 或 F6 中登记「注册→锁定→攻击→结算 冒烟延期至 M6 F6 补」，并声明 G0 门禁在 M6 前以「validator 全量 + 最小装载」（现有 test_e2e_smoke）为暂代口径，防止门禁假绿。

### P2-8 ｜ F6 仅点名 demo_blank，未列五档目录名（与框架 §15 不一致细节）
- 位置：docs/实现层规划文档.md L3443（仅 demo_blank）；框架 §15 L1593-1597（demo_blank/demo_lv15/demo_lv30/demo_lv45/demo_full）
- 修复建议：F6 列出五档目录名与等级区间（空白=demo_blank、新手 1-15=demo_lv15、成长 1-30=demo_lv30、进阶 1-45=demo_lv45、完整=demo_full），与框架 §15/规则 L207 完全对齐。

---

## 4. ① 缺漏「应覆盖 X 但未覆盖」清单

1. **五档数据包（demo_blank~demo_full）每档的 validator 覆盖点与内容范围**（模块集/断言点/29 文件取舍）——L3443 仅一句「逐步建立」，未逐档定义。
2. **五档包 validator 全绿作为 F6 验收项**——定稿 L285 与细化_3a TC-22 要求 content/ 全部预置包 validator 全绿，F6 验收①只列四类样例包。
3. **每档是否模拟一局及链路差异**——空白包无怪物时模拟一局如何定义未写。
4. **注册/锁定两环的实现或桩口径**——/注册（verify_m5 DELAYED）、/锁定怪物（待接线）当前无落点。
5. **真实 battle 引擎的复用做法**——现有 core/battle.py + battle_commands ctx 契约未进 F6 口径（P1-1）。
6. **冒烟断言清单**——注册返回值/锁定目标/攻击结果/结算输出/渲染行未列出。
7. **冒烟确定性约定**——固定 now+种子+两次重放（e2e_m4_smoke 惯例）未声明（P2-4）。
8. **归档位置与文件命名**——docs/ 与《开发记录》、CHANGELOG（P2-3）。
9. **四类样例包与 verify_m0 四件套的重叠/增强关系及断言归属**——F6 与 verify_m0 重复断言还是 verify_m6 内联增强（尤其 old_schema 从「容忍」升级为「迁移」），未说明。
10. **旧 schema 迁移链定义**——内容包侧 0→1 迁移（loader 无此链），区分存档迁移 TC-5d-35（P2-5）。
11. **missing_mod 断言语义**——Y-6 提示+挂载+未声明不加载，并修正 verify_m0 注释（P1-4）。
12. **五档包存放位置**——content/ 而非 tests/fixtures/packs（防违反「四件套禁止更多」，P2-2）。

## 5. ② 错误 / ③ 幻觉 / ④ 跨文档 核对结论

**② 错误**：
- F6 与定稿 §4.3 五档（空白/新手 1-15/成长 1-30/进阶 1-45/完整）名称与等级区间逐档一致 ✓。
- 「模拟一局 注册→锁定→攻击→结算」与现有 e2e_m4_smoke.py（NPC→商店→任务→签到→快捷→翻页）链路**无重叠无冲突**（指令集合不相交），属互补 ✓；但 F6 未声明沿用其约定（P2-4）。
- A3 留桩口径：F6「battle 按 A3 留桩」在规划文档 A3 范围（L3203/L3168/L3185）内自洽，**但与仓库已实现 battle 栈冲突**（P1-1）——这是 F6 最重的错误项。
- verify_m0 注释「missing_mod 必须被红拦」与实际 Y-6 黄提示语义矛盾（P1-4）——已实现脚本的语义错误，F6 必须避免照抄。

**③ 幻觉**：无编造。五档包只引用 §4.3 未虚构内容；四件套断言与 verify_m0/定稿一致；「旧 schema 迁移」有 M0 显式登记（verify_m0.py L66-68/94-98「登记 M6 覆盖」）背书，非编造。唯一「断言语义编造」风险点在已实现 verify_m0 的 missing_mod 注释（P1-4），非 F6 本身。

**④ 跨文档**：
- F6（L3443-3444）↔ M6 里程碑（L3481）：冒烟链「注册→锁定→攻击→结算」一致 ✓；M6 行含 CHANGELOG 归档，F6 未承接（P2-3）。
- F6 ↔ G1 verify 归档（L3452-3453）：归档方向一致；F6 未点名 docs/（P2-3）。
- F6 ↔ M2 四件套（verify_m0）：四件套清单一致；missing_mod 断言语义需按 P1-4 修正。
- F6 ↔ e2e_m4_smoke：无重复；缺约定复用声明（P2-4）。
- F6 ↔ 细化_5d/细化_3a/启动手册/run_all_tests：M6 里程碑号口径冲突（P2-1）；G0 冒烟延期欠账（P2-7）。

## 6. 说明
- 全程静态审查，未运行任何命令；所有「当前未实装/无迁移链/已存在引擎」等运行行为结论均标「静态推导」，依据为仓库源码/README/verify 脚本/docstring 的静态内容。
- 任务题面「scripts/verify_m0.py」实际路径为 `scripts/verify/verify_m0.py`（复核定位，非设计缺陷）。
