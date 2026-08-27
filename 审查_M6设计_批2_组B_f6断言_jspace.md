# 审查：M6 设计 批2 组B —— F6 内容包冒烟断言与可执行性（断言/归档/现有衔接）

> 门控档位：**full**（j-space）。方法：**静态审查**。本环境无 bash 沙箱，未运行任何命令/脚本/测试；
> 全部运行行为结论为「静态推导」（依据源码/测试/文档逐行核对）。审查对象：
> - 设计：`docs/实现层规划文档.md` F6 L3441-3444、G1 L3450-3453、M6 里程碑 L3481
> - 已实现参考：`scripts/verify/verify_m0.py~verify_m5.py`、`scripts/run_all_tests.py`、
>   `scripts/e2e_m3_smoke.py`、`scripts/e2e_m4_smoke.py`、`tests/fixtures/packs/` 四包、
>   `tests/unit/test_content.py`、`tests/unit/test_battle_boundary.py`、`qbot_rpg/content/loader.py`、
>   `qbot_rpg/commands/*`、`docs/细化/细化_5d_测试体系总纲.md`、`docs/细化/细化_3e_loader校验接线.md`、
>   `docs/审查参考/开发规则文档.md`

---

## 0. 结论摘要

- **P0 = 2**，**P1 = 8**，**P2 = 3**。
- 总体：F6 设计方向正确（四类包 + validator + 模拟一局，对齐 细化_3e TC-30 / 细化_5d §5.1），
  但**验收②「冒烟闭环走通」未定义任何逐步断言，违反 G1「verify 必须可执行且有断言」硬规则**；
  且「注册」「锁定」两步在现有实现中不可执行、「battle 留桩」前提已过时、
  「归档」无约定、接入 verify_m6 无声明——F6 在 M6 实施前必须补断言矩阵与接线声明。
- 幻觉核对：四类包预期**大部分真实**（合法全过/坏引用拦截均已实现断言），但
  「缺模块提示」在 verify_m0 中是**空断言**（双分支皆过）、「旧 schema 迁移」语义歧义（容忍 vs 迁移链）、
  「battle 接口按 A3 留桩」为**过时陈旧前提**。

---

## 1. P0（阻断：按现有设计不可断言/不可执行）

### P0-1 F6「模拟一局（注册→锁定→攻击→结算）」无逐步断言定义，且「注册」「锁定」两步不可执行
- **位置**：`docs/实现层规划文档.md` L3443-3444（F6 实现要点/验收②）、L3481（M6 verify 列「冒烟闭环（注册→锁定→攻击→结算）」）；
  冲突点：G1 L3452「verify 必须可执行且有断言（禁"人工看了没问题"）」。
- **静态推导**：
  1. 「注册」：`/注册` 指令**未实现**。`scripts/verify/verify_m5.py` L156-167 把 4f TC-01/02/03/04/06
     （/注册 首次/缺省职业/重名/幂等/名字长度）全部标 **DELAYED**；`qbot_rpg/commands/basic_commands.py`
     L131 仅有 `TPL_REGISTER_GATE` 门槛文案（"❌ 请先 /注册 创建角色…"）、L203 引导行，L1357-1384
     `register_basic_commands` 不注册 `/注册` handler。
  2. 「锁定」：无 `/锁定` 或 `锁定怪物` 指令 handler。`qbot_rpg/commands/parsers.py` L110 白名单含
     「锁定怪物」但全仓 `register_*`（basic/battle/explore/shop/quest/checkin/gm）均无其接线；
     `qbot_rpg/world/battle_boundary.py` L599-660 有 `wild_lock` 先到先得世界锁（F-07/RACE-02），
     `tests/unit/test_battle_boundary.py` L117-122 有 `test_try_acquire_lock` 单元用例——但那是
     **世界锁**，不是冒烟「锁定」步骤，也无命令/装配层接续。
  3. 验收② 只写「冒烟闭环走通且输出留档」，**未给出注册/锁定/攻击/结算四步各自的可断言输出**
     （输出文案、状态迁移、数值、快照）。对照 细化_5d L221（G0：注册→锁定→攻击→结算 冒烟形态）与
     开发规则 L435（服务器冒烟 = `/注册 /锁定 /攻击` 一轮闭环），F6 把**服务器冒烟**的词汇搬进了
     **内容包冒烟**（内容包冒烟的权威形态是 规则 L285 / 细化_3e TC-30 的「锁定→攻击→结算」，无「注册」）。
- **修复建议**：F6 增补逐步断言矩阵（见 §5 清单），并将：
  - 「注册」明确为**注册门槛断言**（`registered=False` → 各指令返回 TPL_REGISTER_GATE，已有
    `test_basic_commands::test_register_gate_rul08` 承载），或显式声明依赖 `/注册` 实现（当前 DELAYED）；
  - 「锁定」明确映射到 `try_acquire_lock`（先到先得：无锁获得/有锁拒绝/holder 暴露）或 `BattleEngine.start`，
    二选一并给断言；
  - 明确内容包冒烟 ≠ 服务器冒烟，不在 F6 中引入 `/注册 /锁定` 命令形态。

### P0-2 F6 冒烟接入 verify_m6 / run_all_tests 未定义，且 M6 范围三处定义冲突
- **位置**：`docs/实现层规划文档.md` L3481（M6 接线闭环 = F5-F6、G2-G4）vs
  `docs/细化/细化_5d_测试体系总纲.md` L95（M6 数据 = `verify_m6.py` 114 TC：3e 30 + 3e2 14 + 5a 18 + 5b 34 + 5c 18）
  vs `scripts/run_all_tests.py` L42（m6 注释「M6 数据框架（5a/5b/4c/4d/4e/6 系）」）。
- **静态推导**：`scripts/verify/` 下**无 verify_m6.py**（仅 m0~m5）；`run_all_tests.py` L34-43
  `MILESTONES["m6"] = None`（"M6 尚未实现，置 None 标记"），L76-79/95-97 阶段2 跳过 m6。
  F6（L3443-3444）与 G1（L3452-3453）均**未成文声明**「F6 冒烟应成为 verify_m6 的一部分 /
  run_all_tests MILESTONES['m6'] 何时置位」。细化_5d L95 已把「4.6 四类样例包加载矩阵」放进
  verify_m6 补充引擎段，但细化_5d 的 M6（数据）与规划文档的 M6（接线闭环）**不是同一个 verify_m6**，
  F6 冒烟归属未仲裁。
- **修复建议**：在 G1/§8 里程碑表声明 `verify_m6` 构成 = 细化_5d L95 的 114 TC + F6 冒烟（四件套矩阵 +
  模拟一局），M6 落地时置位 `run_all_tests.MILESTONES["m6"]`；统一三处 M6 范围描述。

---

## 2. P1（必须补但可实施时解决）

### P1-1 F6 验收①「缺模块提示」无真实断言可挂——verify_m0 的 missing_mod 断言为空
- **位置**：`scripts/verify/verify_m0.py` L80-100 `_check_each`；F6 验收① `docs/实现层规划文档.md` L3444。
- **静态推导**：verify_m0 对 `missing_mod` **两个分支都不产生 failure**（try 分支只对 `legal` 查 `report.ok`；
  except 分支只对 `legal`/`old_schema` 报错），即 missing_mod「加载成功」与「被拦」**均记 ✓**——
  正是 verify_m0 自身 docstring（L62）说要修复的「恒打印 ✓ 无断言」（P1-3）反模式的残留。
  且 note 文案「加载被拦（预期）」暗示作者以为 missing_mod 应被拦，而正确语义是**软放行**。
- **已实现正确断言**：`tests/unit/test_content.py` L286-297 `test_missing_mod_pack_y6`——missing_mod 应
  **加载成功 + warnings 含 Y-6(statuses) + 未声明 npc.json 不注册**。verify_m0 未复用。
- **修复建议**：F6 明确「缺模块提示 = 加载成功 + Y-6 黄提示 + 未声明文件不加载」（软性，非红拦），
  verify_m6 引用 `test_missing_mod_pack_y6` 或补脚本级同款断言；修正 verify_m0 空断言。

### P1-2 「旧 schema 迁移」语义歧义（容忍 vs 迁移链），F6 验收①无可断言对象
- **位置**：F6 验收① L3444「旧 schema 迁移」；`verify_m0.py` L66-68/L94-98（登记「迁移链 M6 覆盖」）；
  `tests/unit/test_content.py` L300-309 `test_old_schema_tolerated`；
  `docs/细化/细化_5d_测试体系总纲.md` L202/L292（TC-5d-35 为**存档**迁移，非内容包迁移）。
- **静态推导**：`qbot_rpg/content/loader.py`（300 行）**无任何内容包迁移逻辑**（仅 `registry.py`
  L203-207 schema_version 一致性自检）；`qbot_rpg/storage/migrations.py` 实现的是**存档**迁移（MIG-1~5），
  与内容包旧 schema 无关。当前旧 schema 包仅「容忍加载」（缺补默认/多忽略，old_slime.hp=None），
  **没有任何「迁移链产物」断言**。F6 若不指明「迁移」= 容忍（已实现）还是迁移链（需新实现），验收① 无法落断言。
- **修复建议**：F6 定义「旧 schema 迁移」语义：(a) 容忍加载（引用 test_old_schema_tolerated，已实现）；
  或 (b) 内容包迁移链（schema_version 0→1 输出、字段级改写）——若 (b)，M6 需新实现并给出迁移产物断言。

### P1-3 content/ 预置包与五档数据包不存在，「对 content/ 全部预置包跑 validator」无对象，且与「四个各一禁止更多」冲突未仲裁
- **位置**：F6 L3442-3443（定稿依据「对 content/ 全部预置包跑 validator」；实现要点「demo_blank 起步，
  按 §4.3 五档数据包逐步建立」）；`docs/细化/细化_5d_测试体系总纲.md` L200（「四个各一，禁止更多」）。
- **静态推导**：仓库无 `content/` 目录、无 `demo_blank`、无五档包（glob 全空）；仅
  `tests/fixtures/packs/` 四包。F6 验收只覆盖四类 fixture 包（L3444①），**五档包构建/冒烟无验收落点**，
  定稿依据中的「content/ 全部预置包」实际悬空。细化_5d L200 与 F6 五档包计划直接冲突（未仲裁放哪）。
- **修复建议**：F6 显式声明 M6 冒烟范围 = `tests/fixtures/packs` 四包（对齐细化_5d L200 与细化_3e TC-30），
  把「content/ 五档生产包」登记为独立后续任务（或工程补白声明不纳入 M6 verify）。

### P1-4 冒烟「输出留档（verify 归档）」无归档约定；G1「verify 输出留档于仓库 docs/」在 M0-M5 全部未实现
- **位置**：F6 L3444②「输出留档（verify 归档）」；G1 L3453②「verify 输出留档于仓库 docs/」。
- **静态推导**：verify_m0~m5 **全部只 print 到 stdout、无任何文件写出**（逐行核读）；docs/ 下无 verify
  输出目录（`docs/审查报告/` 是审查报告，非 verify 输出）。F6 ② 未定义归档路径/文件名/内容
  （全量输出？断言计数？validator 报告？）。
- **修复建议**：F6 指定归档物与写入方式（如 `docs/verify/m6_smoke.md`：四包 validator 报告 + 模拟一局
  断言计数 + 确定性重放结果，由 verify_m6 写文件），并补 M0-M5 归档欠账或显式 defer。

### P1-5 CHANGELOG.md 不存在，但 G1 要求每里程碑更新、M6 要求「CHANGELOG 归档」
- **位置**：G1 L3452（每里程碑 verify 后更新 CHANGELOG）；M6 L3481（CHANGELOG 归档）；
  `docs/审查参考/开发规则文档.md` L210（项目树含 CHANGELOG.md）、L400/L424/L551（Keep a Changelog）。
- **静态推导**：仓库根**无 CHANGELOG.md**（glob 全空）；M0-M5 已全部违反 G1（无文件可更新）。
  M6/F6 的「CHANGELOG 归档」验收无法满足。
- **修复建议**：M6 创建 `CHANGELOG.md`（Keep a Changelog 格式）并回填 M0-M5 条目，或显式登记 defer。

### P1-6 「battle 接口按 A3 留桩，本路先跑通属性/背包/渲染链路」与实现现状矛盾（battle 已全量实装，且 M0 前置即要求战斗冒烟）
- **位置**：F6 L3443；`qbot_rpg/core/battle.py`（BattleEngine 全量）；`scripts/verify/verify_m1.py` L179-224
  （start/do_action/enemy_act/end_turn/to_snapshot/from_snapshot）；`scripts/verify/verify_m5.py` L497-513
  （④b 一轮=1条真实引擎战斗）；`docs/细化/细化_3a_架构分层契约.md` L355 TC-04（M0 前置：import battle
  并执行一局完整战斗 锁定→攻击→结算）；`docs/细化/细化_5d_测试体系总纲.md` L221（G0：M0 开工前冒烟打通）。
- **静态推导**：battle 引擎（M1）+ 战斗渲染/接线（M5 `battle_commands.py` L839-862 注册 /攻击 /防御 /逃跑 /道具）
  均已实现且被 verify_m1/m5 门禁覆盖；G0/细化_3a TC-04 要求 M0 前即跑通「锁定→攻击→结算」。F6 的
  「battle 留桩、先跑通属性/背包/渲染」是**过时倒退假设**。且「A3」指代混乱——规划文档 A3 有两处
  （L750 日界统一 / L3201 commands 壳层），两者均不含 battle 留桩语义（A3 commands 壳层 L3203
  「业务指令只留注册骨架」也已被 M4/M5 超越）。
- **修复建议**：F6 改为「battle 已实装（M1 引擎 + M5 渲染/接线），模拟一局直接走真实
  BattleEngine + battle_commands/battle_render，按 legal 包数据驱动」。

### P1-7 F6「validator 全绿（红拦必须真拦截/黄提示可过）」未点名回归载体
- **位置**：F6 L3443-3444；G1 L3453③「任一红拦类回归失败 → 里程碑不通过」。
- **静态推导**：现有覆盖已充分但分散：红拦 `verify_m0.py` L80-100（badref→PackLoadError）、
  `verify_m2.py` L215-239（badref 规则级 R1/R3/R2/R6/R8）、`test_content.py` L143-247（R-1~R-5 等）、
  `test_enemies_schema.py::test_badref_8seg_red_blocks`；黄提示可过 `test_content.py` L250-310
  （Y-1/Y-2/Y-4/Y-6/Y-7）+ legal 零红零黄（L43-48/L91-92）。F6 未说明「红拦必须真拦截」断言落在
  verify_m6 的脚本级还是子进程 pytest 载体。
- **修复建议**：F6 显式列 verify_m6 子进程 `PYTEST_FILES`（含 `test_content.py` / `test_enemies_schema.py`），
  与 verify_m2 的 PYTEST_FILES 机制对齐。

### P1-8 F6 模拟一局与现有战斗冒烟重复，未声明「复用 vs 增强」
- **位置**：F6 L3443；`verify_m1.py` L194-224（1g2 回合时序 / 1g3 快照往返 / random_seed 续接）；
  `verify_m5.py` L497-513（④b 一轮=1条）；细化_3a TC-04。
- **静态推导**：引擎级「锁定→攻击→结算」已被 verify_m1/verify_m5 + test_battle_wiring 覆盖；
  F6 的边际价值仅在「以 legal 包数据装配怪 → 战斗 → 结算」的集成路径（细化_3e TC-30 要求，当前
  test_battle_wiring 用硬编码 PLAYER/ENEMY dict，非 legal 数据）与四包 validator 绑定。F6 未声明关系。
  且 F6 未声明断言风格（应沿用 e2e_m3/e2e_m4_smoke 的 `Smoke.check/check_eq` + 确定性重放）。
- **修复建议**：F6 声明「复用 verify_m1/M5 战斗断言 + 新增 legal 包数据驱动集成战斗 + 四包 validator 矩阵」，
  不重复实现；沿用 e2e 冒烟断言风格。

---

## 3. P2（小瑕）

### P2-1 verify_m4「批次7-01 端到端冒烟」DELAYED 声明过期
- `verify_m4.py` L16/L135 声明「test_e2e_m4_smoke.py 并行实现未落盘」，但 `tests/unit/test_e2e_m4_smoke.py`
  **已存在**（包装 `scripts/e2e_m4_smoke.py`）。DELAYED 未自动翻转，覆盖声明与事实不符。
- 教训：F6/verify_m6 的覆盖声明应避免硬编码「未落盘」表述；DELAYED→pytest: 翻转应纳入门禁自检
  （verify_m3/m4/m5 的 `t_coverage_self_consistent` 只验格式与文件存在，不验 DELAYED 过期）。
- 修复：verify_m4 批次7-01 转 pytest: 承载；verify_m6 覆盖声明采用函数级核验（对齐 verify_m4/m5）。

### P2-2 run_all_tests.py `--only datapack/fault` 未实现但 help 承诺；`--fast` 解析未使用
- `run_all_tests.py` L64（help 过滤含 datapack/fault）vs L75-86（仅 MILESTONES/LAYER_PATHS 特判，
  datapack/fault 落入 else 全量回归）；L65 `--fast` 定义后全程未引用。

### P2-3 四类包断言三处并存且语义不一（重复 + 漂移风险）
- verify_m0（load_pack 语义，missing_mod 空断言）/ verify_m2（check_pack，legal 零红零黄 + badref 规则级）/
  test_content.py（逐规则）对同一批 fixtures 重复断言；F6 若再实现第四处会加剧漂移。
- 修复：F6 声明「四类包断言 = 复用 verify_m0._validate_fixtures（先修 missing_mod 空断言）+
  verify_m2 规则级 + test_content 逐规则」，verify_m6 只做聚合与新增，不重复实现。

---

## 4. 「应覆盖 X 但未覆盖」清单（维度① 断言可执行性）

| # | 应覆盖但未覆盖 | 依据（权威） | 现状 |
|---|---|---|---|
| 1 | 冒烟「注册」步骤的可断言输出：`registered=False` → 各指令 TPL_REGISTER_GATE 拦截 | F6 L3443 / 4f TC-05 | `test_basic_commands::test_register_gate_rul08` 已覆盖门槛，F6 未引用；真实 /注册 流程（建档/默认职业/重名/幂等/名字长度）DELAYED，F6 未声明处理 |
| 2 | 冒烟「锁定」步骤的可断言输出：先到先得锁（无锁获得/有锁拒绝/holder） | F6 L3443 / 1g4 F-07 | `test_battle_boundary.py` L117-122 `test_try_acquire_lock` 已有单元，无集成冒烟；`锁定怪物` 指令 handler 不存在（parsers L110 白名单仅登记） |
| 3 | 冒烟「攻击」步骤的可断言输出：合法包数据驱动的 BattleEngine 攻击（伤害数值/HP 差分/一轮一条） | 细化_3e TC-30 / 5e TC-07~23 | 单元已覆盖（verify_m5 ④b、5e 渲染逐字），但均非 legal 包数据装配；集成路径未存在 |
| 4 | 冒烟「结算」步骤的可断言输出：victory 文案 + 掉落 + 回合数 + 快照 round-trip | 细化_3a TC-22 / 5e TC-18/25 / 1g3 | 单元已覆盖，legal 数据驱动的集成结算未存在 |
| 5 | 冒烟确定性/重放（固定 now/种子，两次运行摘要逐字一致） | e2e_m3/e2e_m4_smoke 铁律 | F6 未声明 |
| 6 | content/ 五档预置包（空白/新手/成长/进阶/完整）与 demo_blank 的构建/冒烟 | F6 L3443 / 框架 §4.3 | 不存在、无验收落点（见 P1-3） |
| 7 | 归档物（verify 输出留档 docs/、CHANGELOG.md） | G1 L3453② / M6 L3481 | 未定义、M0-M5 均未落实（见 P1-4/P1-5） |
| 8 | 「任一红拦类回归失败 → 里程碑不通过」在 verify_m6 的回归载体（test_content.py / test_enemies_schema.py 纳入子进程门禁） | G1 L3453③ | F6 未列 PYTEST_FILES（见 P1-7） |
| 9 | 旧 schema 迁移链产物断言（字段级迁移输出，非仅容忍） | F6 验收① / 细化_5d L202 | 未实现、语义未定义（见 P1-2） |
| 10 | 内容包冒烟用例落位 L4（tests/e2e/ 或 pytest 包装） | 细化_5d L52/L66/L253（TC-5d-06） | `tests/e2e/` 目录不存在；TC-5d-06 未落地（当前冒烟以 scripts/e2e_m4_smoke.py + test_e2e_m4_smoke.py 包装形式存在） |

---

## 5. ③ 幻觉核对（F6 声称 vs verify_m0/仓库实际断言）

| F6 声称 | 核对结果 |
|---|---|
| 「合法全过」 | ✅ 真实。verify_m0 L87-88 断言 legal `report.ok`；test_content L43-48 断言 0 errors + **0 warnings** |
| 「坏引用拦截」 | ✅ 真实。verify_m0 L89-93（PackLoadError）；verify_m2 L215-239（规则级 R1/R3/R2/R6/R8） |
| 「缺模块提示」 | ⚠️ 部分幻觉。verify_m0 对 missing_mod **无断言**（双分支皆过，L80-100）；真正断言在 test_content L286-297（加载成功 + Y-6 + 未声明不加载）。若 F6 以为「verify_m0 已断言缺模块提示」则被误导 |
| 「旧 schema 迁移」 | ⚠️ 歧义性幻觉。verify_m0 只断言「不被拦」（L94-98 注明迁移链 M6 覆盖）；test_old_schema_tolerated 只断「容忍」；**无迁移链断言**存在（若「迁移」指迁移链则属未实现目标被写成已具备预期） |
| 「battle 接口按 A3 留桩」 | ❌ 陈旧幻觉。battle 引擎（M1）+ 渲染/接线（M5）+ 门禁断言已全量存在；G0/细化_3a TC-04 要求 M0 前即跑通战斗冒烟 |
| 「冒烟闭环走通」 | ⚠️ 未落地目标、无既有断言可对照（e2e_m4 无战斗；verify_m1/m5 有引擎战斗但非「注册→锁定→攻击→结算」命名、非 legal 数据驱动）。验收② 无断言细节 = 空转风险，非「编造断言」 |

---

## 6. ④ 跨文档衔接（F6 ↔ G1 ↔ M6 ↔ verify_m6）

- **F6 → verify_m6**：衔接方向正确但未成文。细化_5d L95 已把「4.6 四类样例包加载矩阵」放进 verify_m6
  补充引擎段；规划 L3481 M6 verify 列含「冒烟闭环」。**F6 应成为 verify_m6 的一部分**：verify_m6 =
  细化_5d M6 114 TC + F6 冒烟（四件套矩阵 + 模拟一局）；`run_all_tests.MILESTONES["m6"]`（当前 None）在
  M6 落地时置位。
- **F6 ↔ G1**：G1 L3452「verify 必须可执行且有断言」是 F6 验收的合规底线（当前验收②不达标）；
  G1 L3453③「任一红拦类回归失败→里程碑不通过」需 F6 指明红拦回归载体；G1 L3453②「verify 输出留档
  docs/」= F6②「输出留档」的上位要求，但 M0-M5 均未落实，F6 是首个归档落地点，需定义路径。
- **F6 ↔ M6**：M6 范围三处冲突（规划接线闭环 / 细化_5d 数据 / run_all_tests 数据框架）；且冒烟既在
  G0 前置（M0 前全绿，细化_5d L221）又在 M6 验收（L3481），出现**同一冒烟既前置又验收的循环风险**。
  需仲裁：G0 的「注册→锁定→攻击→结算」= 服务器冒烟（/注册 /锁定 /攻击 命令）；F6 的「模拟一局」=
  内容包冒烟（validator + 战斗）。F6 不应把服务器冒烟的「注册」搬进内容包冒烟。

---

## 7. Top 3 问题

1. **P0-1 冒烟四步零断言、两步不可执行**：F6 验收② 无逐步断言，违反 G1 硬规则；「注册」（/注册 DELAYED）、
   「锁定」（无 handler）按字面不可执行。
2. **P0-2 接入未定义 + M6 范围三处冲突**：verify_m6 不存在、run_all_tests m6=None、F6 未声明归属，
   细化_5d 的 M6(数据) 与规划的 M6(接线闭环) 不是同一 verify_m6。
3. **P1-6/P1-4 过时前提 + 归档悬空**：「battle 按 A3 留桩」已被 M1/M5 全量实现推翻；「输出留档 docs/、
   CHANGELOG 归档」在 M0-M5 全部未落实且无归档约定，F6 是首个落地点但未定义路径/内容。
