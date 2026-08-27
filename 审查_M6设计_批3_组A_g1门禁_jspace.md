# 审查：M6 设计 批3 组A —— G1 里程碑与 verify 门禁设计合规

> 门控档位：**full**（j-space，唤醒→门控→接缝审计→ship）。方法：**静态审查**。
> 本环境无 bash 沙箱，**未运行任何命令/脚本/测试**；全部运行行为结论为「静态推导」（依据源码/测试/文档逐行核对）。
> 审查对象：
> - 设计：`docs/实现层规划文档.md` G1 L3450-3453、M6 里程碑 L3481、§9 风险 L3488-3498、G2 L3455-3458、G3 L3460-3463、G4 L3465-3468、F6 L3441-3444
> - 定稿对照：【规则】§六.3（发布检查单，L418-435）/ §四（测试规范，L277-333）/ §6.2（Changelog，L398-417）/ §一.7（工具链，L119-123）；【框架】§13（验收标准，L1527-1561）
> - 已实现参考：`scripts/verify/verify_m0.py~verify_m5.py`、`scripts/run_all_tests.py`、`docs/细化/细化_5d_测试体系总纲.md`、`docs/细化/细化_3e/3e2`、`记录.md`
> - 与本批衔接：批2 组A（F6 冒烟，审查_M6设计_批2_组A_f6冒烟_jspace.md）、批2 组B（F6 断言，审查_M6设计_批2_组B_f6断言_jspace.md）

---

## 0. 结论摘要

- **P0 = 2，P1 = 6，P2 = 6**。
- 总体：G1 的**定稿依据引用真实**（【规则】§六.3/§四、【框架】§13 均存在且语义相符），「verify 必须可执行且有断言」这一硬规则的**方向正确**，且与已实现 verify_m0~m5 的「子进程 pytest + COVERAGE 覆盖声明 + DELAYED 诚实化 + t_coverage_self_consistent」模式在 pytest/validator 两项上**确实对齐**。
- 但 G1「统一 verify 清单模板」7 项中 **4 项（ruff/mypy、里程碑验收单、结果归档、CHANGELOG 更新）在设计与实现中均无可执行载体/无断言定义**，使 G1 自身硬规则自反失效、验收①「逐项可勾选」不可达成；其中 CHANGELOG 条款在 M0-M5 **六次零发生**，为系统性违约欠账。M6 里程碑 verify 列 6 项中 5 项（热重载/冒烟/故障注入/覆盖率/ruff-mypy/CHANGELOG）无声明载体。
- 幻觉核对：**无编造脚本名/编造来源**；但「每里程碑 verify 后更新 CHANGELOG」把**从未发生的流程写成既有事实**（CHANGELOG.md 不存在）；细化_5d §3.2 描述的 run_all_tests 能力（ruff/mypy 快速门 / verify_datapack / 故障注入 / 覆盖率核算）与真实脚本**不符**。

---

## 1. P0（阻断：G1 门禁设计本身不可执行/自相矛盾）

### P0-1 G1「统一 verify 清单模板」7 项中 4 项无可执行、无断言载体 → G1 硬规则自反失效
- **位置**：`docs/实现层规划文档.md` L3452（模板定义 + 「verify 必须可执行且有断言（禁"人工看了没问题"）」）；L3453①（「逐项可勾选且命令可复跑」）。
- **静态推导**（逐项核对模板 7 项的可执行性）：
  1. pytest 全绿（含本里程碑新增用例）→ ✅ 可执行（verify 脚本子进程 pytest，m1 L250-256、m5 L636-645）且有断言。
  2. ruff/mypy 通过 → ❌ **无任何执行载体**：全仓无 CI workflow（glob .github 全空）、无脚本调用 ruff/mypy（grep 全仓 .py 零命中）、run_all_tests.py 未接入、verify_m0~m5 未接入。【规则】§一.7 L122「CI 门槛：ruff + mypy + pytest 全绿」与 G4 L3467「ruff + mypy + pytest 全绿才合入」一并悬空。
  3. 预置内容包 validator 全绿 → ✅ 可执行（verify_m0 `_validate_fixtures` L61-103 带断言、verify_m2 L215-239），但 missing_mod 为空断言、旧 schema 仅「不被拦」无迁移链断言（与批2 P1-1/P1-2 同根，见 P2 清单 #8）。
  4. 冒烟闭环 → ⚠️ 部分可执行（e2e_m3/e2e_m4_smoke 已存在；M6 的「注册→锁定→攻击→结算」按字面不可执行，批2 P0-1 已审，本批不重复）。
  5. 里程碑验收单（对照本规划任务勾选）→ ❌ **内容/粒度/产物未定义**（全仓 grep「验收单」仅 L3452 与其在 规划_路3 L313 的副本，无任何模板/粒度/落点定义）；verify_m0~m5 均无验收单产物（只有 COVERAGE 覆盖声明与 stdout 打印）。
  6. 结果归档 → ❌ **路径/命名/写入者未定义**（见 P1-5）。
  7. 每个里程碑 verify 后更新 CHANGELOG → ❌ **无文件可更新、无触发机制**（见 P0-2）。
- **修复建议**：G1 将模板重构为「7 项 + 每项声明执行载体与断言落点」：ruff/mypy 接入 run_all_tests 前置段（细化_5d §3.2 step1 落地）；验收单定义为「任务级勾选单 = 里程碑所属任务（如 M6 的 F5/F6/G2/G3/G4）的【验收标准】逐条 → 映射到 verify_m6 断言/子进程 PYTEST_FILES」；归档定义为路径+命名+写入脚本（见 P1-5）。缺项不得宣称「统一模板已成立」。

### P0-2 CHANGELOG 系统性欠账 + M6「CHANGELOG 归档」无对象（存在性幻觉 + 触发机制缺位）
- **位置**：`docs/实现层规划文档.md` L3452（每里程碑 verify 后更新 CHANGELOG）、L3481（M6「CHANGELOG 归档」）；【规则】L210（项目树含 CHANGELOG.md）、L398-417（§6.2 Keep a Changelog）、L424（发布检查单 CHANGELOG 项）。
- **静态推导**：仓库根**无 CHANGELOG.md**（glob CHANGELOG* 全空）；`记录.md`（《开发记录》，M0-M5 全量验收记录）**通篇无 CHANGELOG 字样**——即 G1「每里程碑 verify 后更新 CHANGELOG」在 M0-M5 六次零发生。M6/F6 的「CHANGELOG 归档」验收**无文件可写、无回填基线、无触发机制**（设计未定义手动/门禁自动；verify 脚本与 run_all_tests 均无 CHANGELOG 写入或校验逻辑）。
- **幻觉定性**：G1/M6 把 CHANGELOG 更新/归档表述为**既有流程**（「每里程碑 verify 后更新」），而文件与流程均不存在——属「把未发生流程写成既有事实」的存在性幻觉 + 未登记欠账。
- **修复建议**：M6 落地时创建 `CHANGELOG.md`（Keep a Changelog），**回填 M0-M5 六条目**（记录.md 已逐里程碑有摘要可转写）；显式声明触发 = 每里程碑 verify 通过后人工/脚本追加条目；TC-5d-31（发布门素材「CHANGELOG 校验」）需配套校验脚本段。若 M6 范围内不做，须在 G1/§9 显式登记 defer，禁止默认「已达标」。

---

## 2. P1（必须补，可在 M6 实施时解决）

### P1-1 ruff/mypy 无执行载体：G1 模板项、G4 CI 门槛、细化_5d §3.2 step1 三者承诺同一能力但现状全无
- **位置**：`docs/实现层规划文档.md` L3452（模板项）、L3467（G4「CI 门槛：ruff + mypy + pytest 全绿才合入」）；`docs/细化/细化_5d_测试体系总纲.md` L133（run_all_tests §3.2 第 1 步「静态与覆盖前置：ruff/mypy 快速门 → 不通过直接中止」）；`scripts/run_all_tests.py` 全文（无 ruff/mypy 段）。
- **静态推导**：细化_5d L133 描述的 run_all_tests 首段 ruff/mypy 快速门在真实脚本中**不存在**；run_all_tests 实际只跑「阶段1 金字塔单测 → 阶段2 里程碑 verify → 阶段3 覆盖率打印提示」（L88-102）。G1 模板项 ruff/mypy 通过 → M6「ruff/mypy/pytest 全绿」无任何可执行机制。
- **修复建议**：run_all_tests 阶段0 增加 `ruff check . && mypy .`（或等价 lint 子进程），失败即 exit 非 0；verify_m6 的 G4 门禁引用该段；并登记 G1 模板项执行载体。

### P1-2 覆盖率 ≥80% 硬门禁自 M0 简版后从未恢复：M6「覆盖率 engine/content ≥80%」与 G4 验收②「覆盖率达标报告归档」无载体
- **位置**：`docs/实现层规划文档.md` L3481（M6 覆盖率项）、L3467-3468（G4 覆盖率 ≥80% + 验收②「覆盖率达标报告归档」）；`scripts/verify/verify_m0.py` L149-157（「覆盖率未核算：简版口径，M1 恢复 ≥80% 硬门禁」）；`记录.md` L210（覆盖率 ⏳ M1 恢复，至今未还）；run_all_tests.py L102（仅打印「见 verify_m0 §5 估算口径」）。
- **静态推导**：verify_m1~m5 与 run_all_tests **均无 coverage 执行**（grep 全仓 .py 无 `coverage run`）；「M1 恢复」承诺在 M1-M5 五次未兑现且无重新登记。M6/G4 把「覆盖率 engine/content ≥80%」写成硬门禁，但无测量器、无报告文件、无归档路径。
- **修复建议**：M6 将覆盖率核算落地为 verify_m6/G4 段真实执行（`coverage run --source=qbot_rpg/core,qbot_rpg/content` + `coverage report` + 阈值断言 ≥80%），输出报表文件到 P1-5 定义的归档目录；把 verify_m0「M1 恢复」陈旧承诺改为「M6 恢复」并登记到 §9/记录.md。

### P1-3 故障注入六类（G3）无执行载体：tests/fault/ 不存在，run_all_tests --only fault/datapack 静默降级为全量
- **位置**：`docs/实现层规划文档.md` L3460-3463（G3）、L3481（M6「故障注入六类全绿」）；`scripts/run_all_tests.py` L64（help 承诺 datapack/fault 过滤）vs L75-86（仅 MILESTONES/LAYER_PATHS 特判，datapack/fault 落入 else **全量回归**）；`docs/细化/细化_5d_测试体系总纲.md` L187（tests/fault/ 六脚本）、L124/L126（全量/过滤命令形态）。
- **静态推导**：仓库无 `tests/fault/`（glob 全空）；`run_all_tests --only fault` / `--only datapack` **不是过滤而是静默跑全量**（参数被吞），且全量流程（L88-102）也不含 fault/datapack 段——过滤语义与细化_5d §3.1/§3.3 完全脱节。M6「故障注入六类全绿」无执行入口。
- **修复建议**：run_all_tests 增加 fault/datapack 分支（细化_5d §3.3）；M6 建 tests/fault/ 六脚本（fault_inject_crash/save/reload/formula/doublepay/netdrop）并入 verify_m6 门禁；G1 模板补充「故障注入」模板项（见 P2-1）。

### P1-4 里程碑验收单内容/粒度/产物未定义，且与已实现 COVERAGE 覆盖声明的两层关系未仲裁
- **位置**：`docs/实现层规划文档.md` L3452（「里程碑验收单（对照本规划任务勾选）」）；已实现 verify_m3/m4/m5 的 COVERAGE 覆盖声明 + `t_coverage_self_consistent`（verify_m5 L399-435）。
- **静态推导**：验收单仅有「对照本规划任务勾选」一句——**粒度**（任务级？验收标准条目级？）、**内容**（勾选什么字段）、**产物**（文件？stdout？记录.md？）、**与 COVERAGE 覆盖声明的关系**（任务级验收单 vs TC 级覆盖声明是两个粒度层，未定义映射）全部缺失。M0-M5 无任何验收单产物（记录.md L10-15 仅一行「验收：…全绿」）。「勾选」语义对 verify 脚本而言不可程序化断言，与「verify 必须可执行且有断言」存在张力——勾选动作要么被自动化（脚本判定），要么是「人工看了没问题」的反模式。
- **修复建议**：定义验收单 = 里程碑所属任务【验收标准】逐条清单，每条映射到 verify 脚本核心断言或子进程 pytest 用例（如 M6：F5 验收①②③ + F6 验收①② + G2 验收①②③ + G3 验收①② + G4 验收①②③④）；由 verify_m6 输出「验收单逐条 = 断言名/退出码」表，保证可执行可断言；COVERAGE 覆盖声明作为其 TC 级子层。

### P1-5 verify 结果归档路径/命名/写入者未定义，且归档目标两处冲突（docs/ vs 《开发记录》）
- **位置**：`docs/实现层规划文档.md` L3453②（「verify 输出留档于仓库 docs/」）；`docs/细化/细化_5d_测试体系总纲.md` L234（「门禁记录在《开发记录》登记（附 pytest 输出摘要）」）、L112；`记录.md`（《开发记录》现为手工维护）。
- **静态推导**：verify_m0~m5 **全部只 print 到 stdout、无任何文件写出**（逐行核读）；docs/ 下无 verify 输出子目录（docs/审查报告/ 是审查报告，非 verify 输出）；`docs/` 与《开发记录》(记录.md) 两个归档目标**不一致且均非自动化**。G1 验收②「留档于仓库 docs/」自 G1 成文起从未落地。
- **修复建议**：统一归档契约——verify 输出 = `docs/verify/<mX>/verify_mX_<YYYYMMDD>.md`（全量输出摘要 + 断言计数 + 覆盖率报表 + 验收单勾选表），由 verify_mX 脚本写文件；《开发记录》保留「门禁通过/失败 + 摘要」一行并附文件链接；M0-M5 缺档项显式 defer 或 M6 补。

### P1-6 verify_m6 构成与 M6 里程碑号四源冲突未仲裁 + run_all_tests `--only m6` 返回 0（假绿陷阱）
- **位置**：`docs/实现层规划文档.md` L3481（M6=接线闭环 F5-F6/G2-G4）；`docs/实现层启动手册.md` L42 与 `scripts/run_all_tests.py` L42（M6=数据框架 5a/5b/4c/4d/4e/6 系）；`docs/细化/细化_5d_测试体系总纲.md` L95（verify_m6=114 TC：3e 30 + 3e2 14 + 5a 18 + 5b 34 + 5c 18 + 补充引擎段四类样例包矩阵/热重载回退/安全回归）；run_all_tests.py L34-43（MILESTONES["m6"]=None）。
- **静态推导**：同一「M6」四个定义分属两套内容——规划文档的**接线闭环**（F5 热重载 + F6 冒烟 + G2/G3/G4）与 启动手册/run_all_tests/细化_5d 的**数据框架**（3e/3e2/5a/5b/5c + 图鉴/成就/PVP/编辑器）。F6 冒烟归前者，细化_5d 把四件套矩阵归后者的 verify_m6 补充段——**归属未仲裁**（批2 组A P2-1 同根）。更严重：`run_all_tests --only m6` 在 L77-79 `script is None` 时 `return 0`（**未实现的门禁返回通过**），若 M6 实现者误用会假绿。
- **修复建议**：在 G1/§8 成文声明 verify_m6 构成 = 细化_5d L95 数据 114 TC + F5/F6 接线冒烟 + G3 故障注入 + G4 质量/覆盖率（或显式登记两套 M6 映射表）；`--only m6` 在脚本缺失时应 return 1（未实现即不通过），勿 return 0。

---

## 3. P2（小瑕）

### P2-1 G1 模板缺「覆盖率核算」「故障注入」模板项，「统一模板」与 M6/G4/细化_5d 全绿定义不一致
- L3452 模板仅 pytest→ruff/mypy→validator→冒烟→验收单→归档；而 M6 L3481、G4 L3467、细化_5d L232（「全绿定义：退出码 0 且覆盖率达标」）与 §6.1 G6（含 verify_datapack/故障注入/安全回归）均要求覆盖率与故障注入。统一模板名不副实。修复：模板增补两模板项。

### P2-2 G1 验收③「任一红拦类回归失败 → 里程碑不通过」判定载体未成文
- 实际承载为隐式：verify 脚本断言失败/子进程 pytest 失败 → exit 1 → run_all_tests L101 `fail = fail or (r.returncode != 0)`。但设计未声明；且 `--only mX` 时红拦覆盖取决于该脚本 PYTEST_FILES 是否含红拦测试（m2 含 test_content 类，m5 不含）→ 过滤态下「任一红拦类回归失败」并不保证拦截。修复：G1 成文声明判定载体 = verify 脚本核心断言 + 子进程 PYTEST_FILES 全绿 + run_all_tests 退出码聚合，并保证每个里程碑脚本的红拦测试纳入子进程门禁。

### P2-3 verify_m5 子进程 pytest「缺失文件黄提示不判失败」（L629-647）与 G1「pytest 全绿（含本里程碑新增用例）」张力
- verify_m5 对缺失测试文件只黄提示跳过、不判失败 → 本里程碑新增用例缺失时门禁仍可绿。与 G1「pytest 全绿（含本里程碑新增用例）」及细化_5d §6.2 全绿定义冲突。修复：仅对显式 DELAYED 项放行，已声明 pytest: 承载的项文件缺失应判失败（fail），或强制走 DELAYED 诚实化。

### P2-4 G2 L3458「battle 留后续路」与已实现覆盖矛盾（陈旧口径）
- G2 验收①「…battle 留后续路」；而 verify_m1（L179-224 真实 BattleEngine 断言）、verify_m5（L497-513 一轮=1条真实战斗）、细化_5d §2.1 M1 战斗覆盖均已实现 battle 引擎与渲染/接线。修复：G2 该句改为「battle 已由 M1/M5 覆盖」。

### P2-5 §9 风险表（L3488-3498）未登记 G1 侧欠账
- 风险 #1（校验空转）只覆盖 validator 空转；未登记「CHANGELOG/归档欠账」「ruff/mypy/覆盖率/故障注入无载体」「M6 范围多源冲突」等门禁失效风险。修复：§9 增补 1-2 行。

### P2-6 run_all_tests/记录.md 宣称能力与实际不符
- run_all_tests L64 help 承诺 datapack/fault 过滤（未实现）；L65 `--fast` 定义后全流程未引用；记录.md L15「全量 run_all_tests 六门禁全绿（M0-M5 + G0 ARCH-OK）」而脚本不含 check_architecture（G0 实为独立脚本，未入 run_all_tests）。修复：实现或删除承诺能力；记录.md 措辞与脚本实际一致。

---

## 4. ① 缺漏「应覆盖 X 但未覆盖」清单（组A：G1 门禁设计）

| # | 应覆盖但未覆盖 | 依据（权威） | 现状 |
|---|---|---|---|
| 1 | G1 模板「ruff/mypy 通过」的可执行断言载体 | 【规则】§一.7 L122 / G1 L3452 / M6 L3481 | 无 CI、无脚本、run_all_tests 未接（P1-1） |
| 2 | 「里程碑验收单」内容/粒度/产物/自动化定义 | G1 L3452 | 仅一句「对照本规划任务勾选」，M0-M5 无产物（P1-4） |
| 3 | 「结果归档」路径/命名/写入者 | G1 L3453② | 只说 docs/，无子目录/命名；verify_m0~m5 零写出（P1-5） |
| 4 | CHANGELOG.md 存在性 + M0-M5 回填 + 更新触发机制 | G1 L3452 / 【规则】§6.2 / M6 L3481 | 文件不存在、六次零更新、触发未定义（P0-2） |
| 5 | 覆盖率 ≥80% 的执行与报告归档 | G4 L3467-3468 / M6 L3481 / 【规则】§四.6 L333 | verify_m0 简版后从未恢复，无报告（P1-2） |
| 6 | 故障注入六类的执行入口 | G3 L3460-3463 / M6 L3481 / 细化_5d §5 | tests/fault/ 不存在、run_all_tests 未接（P1-3） |
| 7 | verify_m6 构成与 run_all_tests.MILESTONES["m6"] 置位时机 | G1 L3452 / 细化_5d L95 / M6 L3481 | 四源冲突未仲裁、m6=None、`--only m6` 假绿（P1-6） |
| 8 | 「预置内容包 validator 全绿」的缺模块/旧 schema 断言语义 | 细化_3e TC-17/TC-30 / 细化_5d §5.1 | verify_m0 missing_mod 空断言、旧 schema 无迁移链断言（P0-1 ③） |
| 9 | G1 验收①「命令可复跑」的复跑一致性证据（确定性重放） | G1 L3453① / e2e_m3/m4 铁律 | verify 脚本无复跑对比机制（仅 e2e 冒烟有） |
| 10 | G1 模板与 G2/G3/G4 的衔接映射（pytest→G2 必测表、故障注入→G3、覆盖率/ruff-mypy→G4） | G1 L3452 / G2 L3456 / G3 L3462 / G4 L3467 | 模板未引用 G2/G3/G4 验收项，衔接不成文 |

---

## 5. ③ 幻觉核对（G1 声称 vs 仓库实际）

| G1/M6 声称 | 核对结果 |
|---|---|
| 「每个里程碑 verify 后更新 CHANGELOG（【规则】§6.2）」 | ⚠️ **存在性幻觉 + 违约**：CHANGELOG.md 不存在，M0-M5 六次零发生（记录.md 无 CHANGELOG 字样）——把未发生流程写成既有事实（P0-2） |
| 「verify 输出留档于仓库 docs/」（验收②） | ⚠️ 未落地目标：verify_m0~m5 零文件写出，docs/ 无 verify 输出目录；作为「应然要求」是缺漏非幻觉（P1-5） |
| 「统一 verify 清单模板」含 ruff/mypy/验收单/归档 | ⚠️ 名不副实：模板声称「统一」，但 M0-M5 实现从未含这 4 项（P0-1） |
| 「任一红拦类回归失败 → 里程碑不通过」（验收③） | ⚠️ 载体隐式：靠退出码聚合承载，无成文机制（P2-2）——非编造，但设计未指明载体 |
| 细化_5d §3.2「run_all_tests：ruff/mypy 快速门 + verify_datapack + 故障注入 + 覆盖率核算」 | ⚠️ 宣称能力 ≠ 真实脚本：run_all_tests 仅 pytest 层 + verify 脚本 + 覆盖率打印提示（P1-1/P1-3/P2-6） |
| G1 定稿依据【规则】§六.3/§四、【框架】§13 | ✅ 引用真实：三处定稿均存在且语义相符，无编造来源 |

---

## 6. ④ 跨文档衔接（G1 ↔ M6 / G2 / G3 / G4 + verify_m6 构成仲裁）

- **G1 ↔ M6（L3481）**：M6 verify 列（热重载回退/冒烟闭环/故障注入/覆盖率/ruff-mypy-pytest/CHANGELOG）相对 G1 模板**缺「预置内容包 validator 全绿」「里程碑验收单」「结果归档（非 CHANGELOG）」三项、多「覆盖率」一项**，且各项均无载体 → 模板与里程碑行不一致（P0-1/P2-1）。
- **G1 ↔ G2（L3455-3458）**：G1「pytest 全绿（含本里程碑新增用例）」与 G2 分层/必测表衔接方向正确（细化_5d 为共同细化）；但 G2 L3458「battle 留后续路」为陈旧口径（P2-4）。
- **G1 ↔ G3（L3460-3463）**：G3 故障注入六类「每个用例必须有断言」与 G1「verify 必须可执行且有断言」精神一致；但 G1 模板**不含故障注入项**，M6 要求与模板脱节（P1-3/P2-1）。
- **G1 ↔ G4（L3465-3468）**：G4 ruff/mypy/pytest CI 门槛与 G1 模板项一致但**均无载体**；G4 覆盖率 ≥80% + 验收②「覆盖率达标报告归档」在 G1 模板缺失（P1-1/P1-2/P2-1）。
- **verify_m6 构成归属仲裁建议**：以「M6 = 接线闭环（F5/F6/G2-G4，实现层规划 L3481）+ 细化_5d L95 数据 114 TC 合并进 verify_m6」为基线；启动手册/run_all_tests L42 的「M6 数据框架（5a/5b/4c/4d/4e/6 系）」中的 5a/5b 属细化_5d M6 数据、4c/4d/4e/6 系归属需按细化_5d §2.1 与批2 组A P2-1 的映射建议统一；F6 冒烟（四件套矩阵 + 模拟一局）与 G3 故障注入并入 verify_m6；`run_all_tests.MILESTONES["m6"]` 在 M6 落地时置位且 `--only m6` 未实现时返回 1（P1-6）。

---

## 7. Top 3 问题

1. **P0-1 模板自反失效**：G1「统一 verify 清单模板」7 项中 4 项（ruff/mypy、验收单、归档、CHANGELOG）无执行/无断言载体，「verify 必须可执行且有断言」对模板自身不成立，验收①「逐项可勾选」不可达成。
2. **P0-2 CHANGELOG 六次零发生**：仓库无 CHANGELOG.md，G1「每里程碑 verify 后更新 CHANGELOG」在 M0-M5 全部违约，触发机制未定义，M6「CHANGELOG 归档」无对象，需回填。
3. **P1-1/P1-2/P1-3 质量/故障载体全缺**：ruff/mypy、覆盖率 ≥80%、故障注入六类均无执行入口（细化_5d §3.2 承诺的 run_all_tests 能力与实际脚本不符，--only fault/datapack 静默全量、--only m6 假绿返回 0），M6 六项 verify 中五项无载体。
