# 审查报告：M6 实现层批7B（质量门禁 · CHANGELOG + CI 流水线）

- **审查对象**：`CHANGELOG.md`（39 行）、`.github/workflows/ci.yml`（97 行）、`scripts/run_all_tests.py`（302 行）
- **契约基准**：`docs/细化/细化_M6_质量门禁.md`（D7）§三 CHG-01~06 + TC-CHG-01~04、§四 CI-01~02 + TC-CI-01~02（CI-03~07 顺带核查）；`记录.md` 里程碑段落（日期核对源）；`docs/实现层规划文档.md` §9 风险表（CI-07 落点）
- **审查方法**：纯静态代码审查（本环境无 bash 沙箱，**未运行任何命令/脚本/验证**）。凡涉及"运行后才会发生的行为"（GitHub Actions 语义、pytest/coverage/mypy 行为、日期是否属实），结论一律标注【静态推断】。
- **审查批次背景**：LNT/COV 组（批7A）已先行落地（requirements/pyproject/per-file-ignores/verify_m0 伪托修正/coverage 归档均已就位），本批为 CHG+CI 组，审查时一并核对接缝。

---

## 〇、结论摘要

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | **0** | 无门禁失效级问题；CHANGELOG 建档、CI workflow、CI 与本地同口径三条主链路均可落地 |
| **P1** | **2** | P1-1 CHANGELOG M1 日期来源偏离 CHG-02（编造日期风险）；P1-2 TC-CI-06 半落地（记录.md 待办缺登记行） |
| **P2** | **7** | 冗余双跑、help/实现漂移、死参数、CI-07 未落笔、CI-03~05 载体空窗、注释与 pytest.ini 矛盾、记录.md 头部日期滞后 |

**门禁判定【静态推断】**：CHANGELOG + CI 载体本体满足 D7 §三/§四 主体契约（TC-CHG-01/02/03、TC-CI-01/02 可验收；TC-CHG-04 依赖 D8 verify_m6，TC-CI-03~07 有缺口见 P2）。修复 P1-1/P1-2 后可视为本批收官。

---

## 一、维度① D7 契约落地核对

### 1.1 CHG 组（CHANGELOG）

| 契约 | 结论 | 证据（静态） |
|---|---|---|
| CHG-01 建档格式 | ✅ 满足 | `# Changelog`（L1）+ `## [Unreleased]`（L13）+ 版本段骨架 `## [v0.1.0] - 待发布`（L35-39，HTML 注释说明发布时归档）；小节约定 Added/Changed/Fixed/BREAKING 声明可见（L8-9） |
| CHG-02 M0-M5 回填 | ⚠️ 部分满足（P1-1） | 六条目齐全（L22-33）；**M0=2026-08-25 与记录.md L265 复查收官日一致（CHG-02 已确认）**；M2=08-26↔记录.md L222、M3=08-26↔L169、M4=08-26↔L134、M5=08-27↔L100 **全部一致**；内容与记录.md 逐条吻合（M0 P0×2/P1×31↔L266、M2 361↔L237、M3 951↔L174、M4 154 断言↔L142、M5 81 TC↔L109）。**例外：M1=2026-08-19（L30）来源为 git 提交日期，记录.md「更早」节（L282-284）无日期 → 见 P1-1** |
| CHG-03 M6 条目预留 | ✅ 满足 | [Unreleased] 段含 M6 预留条目（L17-19），含「质量门禁载体落地」一句（覆盖率实算/ruff-mypy/CHANGELOG/CI/PR 模板全覆盖），待 verify_m6（D8）收口声明明确 |
| CHG-04 触发机制 | ✅ 载体侧满足 | 触发声明在头部注释（L10-11「首个版本发布时按 Keep a Changelog 归档」）+ L19「待本批次与 verify_m6（D8）收口」；校验断言本体归 D8 verify_m6（契约明示本档只定义机制、D8 断言载体） |
| CHG-05 条目口径 | ✅ 满足 | L6-7 显式声明：feat/fix 进 Changelog、docs 不进、按里程碑聚合一句话 |
| CHG-06 BREAKING 醒目 | ✅ 满足 | L8-9 声明 BREAKING 节约定；当前无 BREAKING 变更 → 节不出现（CHG-02 允许）；与 CI-05 联动留待 D8 校验载体 |

### 1.2 TC-CHG 组

| 用例 | 结论 | 说明 |
|---|---|---|
| TC-CHG-01 建档与格式 | ✅ | 头/Unreleased/版本段骨架/小节约定全部可见 |
| TC-CHG-02 六条目+日期一致性 | ⚠️ | 五条日期与记录.md 一致、无编造迹象；M1 日期来源存疑（P1-1） |
| TC-CHG-03 M6 预留 | ✅ | 含质量门禁载体落地一句 |
| TC-CHG-04 触发机制闭环 | ➖ 转归 D8 | verify_m6 未落盘（scripts/verify/ 仅有 m0~m5），契约明示 D8 断言，非本批缺陷 |

### 1.3 CI 组（.github/workflows/ci.yml）

| 契约 | 结论 | 证据（静态） |
|---|---|---|
| CI-01 workflow 建档 | ✅ 满足 | `on: [push, pull_request]`（L14）；steps 顺序 = 依赖安装（L34-39）→ ruff（L44-45）→ mypy（L49-50）→ pytest 全量（L55-56）→ coverage 阈值（L62-89），与契约五步一一对应（另含检出/装 Python/归档 3 个辅助步，共 8 steps）【静态推断：GitHub Actions step 默认 `if: success()` 语义，任一 run 步非零退出即中止后续 → job 失败，未设置 continue-on-error】 |
| CI-02 流水线断言+口径一致 | ✅ 满足 | ci.yml 头部注释（L1-10）自声明为 D7 §四载体本体（流水线断言指向）；步骤④ 直接调用 `scripts/run_all_tests.py` 全量（L56，首选形态）；步骤⑤ 阈值 `THRESHOLD = 80.0` 与 run_all_tests `COV_THRESHOLD = 80.0` 同源（ci.yml L71 显式注明"与 D7 COV-04 / run_all_tests 同源阈值，不另定义"）；产物归档 docs/verify/（L92-97，if: always()） |

### 1.4 TC-CI 组

| 用例 | 结论 | 说明 |
|---|---|---|
| TC-CI-01 workflow 存在 | ✅ | on push/PR + 五步 + 失败即 job 失败（静态推断成立） |
| TC-CI-02 断言指向+口径一致 | ✅ | 调用 run_all_tests 全量入口 + 阈值同源不另定义 |

---

## 二、维度② 代码质量（静态审查）

### 2.1 YAML 语义（ci.yml）

- 结构合法：`on: [push, pull_request]`、`uses: actions/checkout@v4 / setup-python@v5 / upload-artifact@v4`、多行 `run: \|` 块、`<<'PY'` heredoc、`if: always()`【静态推断】。
- 步骤⑤ 内嵌 Python：`json.load(open("/tmp/coverage_ci.json"))` 聚合 `num_statements`/`covered_lines` 按目录前缀（`qbot_rpg/core/` 等，message_format/ 随 core/ 前缀归入，与 D7 §1.4 一致）；`st == 0 or pct < 80.0 → SystemExit(1)`（L85-88）与 run_all_tests `_aggregate_cov`（L101-117）逻辑等价。零语句目录视为测量异常不放行 ✅。
- 潜在小点：`open()` 未指定 encoding（ubuntu-latest 下 UTF-8 默认无碍）【静态推断】。

### 2.2 日期编造风险（CHANGELOG）→ P1-1

- CHANGELOG L30 M1 条目日期 = 2026-08-19；L38-39 注释自述「M1 记录.md『更早』节无日期，取 git 提交日期 2026-08-19 佐证」。
- **冲突点**：D7 CHG-02 边界异常（§3.3，细化_M6_质量门禁.md L162）明确「回填日期不得编造：日期必须从记录.md 对应段落核对填写；记录.md 无明确日期的里程碑（M1-M5）在回填时标【细化定型】取该段落首行日期，禁止凭空造日期」。实现侧：①未标【细化定型】；②未取"段落首行日期"（该节无日期）；③改用 git 提交日期——来源偏离契约规定路径，且**本审查禁 bash，无法验证 git 历史中 2026-08-19 是否属实** → 编造日期风险的直接命中点。时间线自洽性（M1 在记录.md 早于 08-24 段落）不构成对具体日期的证明。
- 建议：核对 git log M1 首提交日期；属实则保留日期并在 L38-39 或【细化定型】标注确认来源；无法核对则按 CHG-02 改标【细化定型】并注明「以 git 提交日期佐证，待 push 后复核」。

### 2.3 版本段骨架（CHANGELOG L35-39）

- `## [v0.1.0] - 待发布`：Keep a Changelog 标准为 `## [vX.Y.Z] - YYYY-MM-DD`，此处以「待发布」占位 + HTML 注释说明 M0-M5 日期来源约定——作为未发布项目的骨架合理，TC-CHG-01 预期即"版本段骨架" ✅。发布时需替换为真实日期（注释已写明）。

### 2.4 CI 与 .venv 布局兼容

- ci.yml 步骤① 建 `.venv` 并用 `.venv/bin/python/pip/ruff/mypy/coverage`（L36-39、L45、L50、L56、L64）；run_all_tests.py L32 `PY = REPO.parent/".venv"/"bin"/"python"`、verify_m0.py L22 同构 → CI 与本地布局完全同构，兼容 ✅【静态推断】。
- 依赖就位（批7A 成果顺带确认）：requirements.txt L13-17（ruff==0.16.5 / mypy==2.3.1 / coverage==7.15.4 锁版本）；pyproject.toml L13 dev 组（ruff>=0.5/mypy>=1.10/coverage>=7）、L22-30 [tool.ruff]、L216-225 [tool.mypy] → CI 步骤②③⑤ 均可执行。
- pytest.ini 无 `--cov`（无合计阈值配置）→ 不违反 COV-02（TC-COV-02 汇集核查通过）。

### 2.5 run_all_tests.py 内部质量

- 阶段结构 = 阶段0 lint（L269-275，--skip-lint 逃生口 L270-271 注明跳过）→ 阶段1 pytest 四层（L276-281）→ 阶段2 verify M0-M5（L282-289，m6=None 打印"未实现"继续）→ 阶段3 coverage（L290-293）→ 退出码 `1 if fail else 0`（L298）：与 D7 LNT-04/COV-04、5d §3.2 L133/L144 一致 ✅。
- 覆盖率段：`coverage run --source=qbot_rpg/core,qbot_rpg/engine,qbot_rpg/content -m pytest <LAYER_PATHS 全量>`（L130-132）→ json → 聚合（L93-117）→ 归档 docs/verify/coverage_latest.txt（L159-183，已存在且三目录各自 ≥80%：core 81.47 / engine 90.52 / content 86.57）✅【归档物为上次运行产物，静态推断其生成逻辑与代码一致】。
- 伪托修正链：全仓 `*.py` grep「估算口径」零命中；verify_m0 L50/57/273 已改引「细化_5d §7.4 决策记录 D5」；记录.md L300 已改「M6 恢复…5d §7.4 决策记录 D5」→ COV-06~09 落地 ✅（批7A 承接确认）。

---

## 三、维度③ 遗漏与接缝（TC-CHG/TC-CI 未覆盖 + git/记录.md 接缝）

| # | 接缝 | 结论 |
|---|---|---|
| 1 | **TC-CI-06 记录.md 侧缺失** → P1-2 | CHANGELOG L20-21 已登记「M6 提交规范差距登记」；但记录.md 待办表（L297-304）grep「提交规范差距/scope」零命中 → D7 CI-06「记录.md 待办表 + CHANGELOG M6 预留条目各记一行」只完成一侧，TC-CI-06 验收不完整 |
| 2 | **TC-CI-07 风险表未落笔** → P2-4 | docs/实现层规划文档.md §9（L3489-3498）仍为 8 行，无第 9 行「门禁载体缺失」（条目内容已定义于 D7 §七 L348-350）；D7 CI-07 落笔执行归批7 或 D8 四源同步——批7 未做、D8 未落盘 |
| 3 | **TC-CI-03/04/05 载体空窗** → P2-5 | .github/ 仅 ci.yml（无 commit-msg hook 实体）；scripts/verify/ 无 verify_m6.py → 提交规范校验（subject≤72/scope 格式/BREAKING footer/feat(pack) 分提交）当前无执行点；D7 CI-03 允许 hook 或 verify_m6 二选一、断言留 verify_m6 → 归 D8，本批未覆盖（接缝登记） |
| 4 | **git 历史接缝** | 禁 bash 无法核验：①M1 日期 2026-08-19（P1-1 已提）；②记录.md L299「7 commit 未 push 待 token」→ CI 对未 push 提交无约束（属既有登记，非本批问题） |
| 5 | **记录.md 头部日期滞后** → P2-7 | 记录.md L80 已含 2026-08-28 批6 完成条目、批7 覆盖内容已写入，但 L4「最后更新：2026-08-27」未刷新 |
| 6 | **TC-CHG-04 转归** | verify_m6 未落盘 → 触发机制断言归 D8，非缺陷（契约明示） |

---

## 四、问题清单（分级 + 文件行号 + 修复建议）

### P0（0 项）

无。

### P1（2 项）

**P1-1｜CHANGELOG M1 日期来源偏离 CHG-02，存在编造日期风险**
- 位置：`CHANGELOG.md` L30（日期 2026-08-19）、L38-39（来源注释）
- 问题：D7 CHG-02 §3.3 规定回填日期必须从记录.md 段落核对、无日期段落须标【细化定型】取首行日期、禁止凭空造日期；记录.md「更早」节（L282-284）无 M1 日期，实现侧改取 git 提交日期（未标【细化定型】），静态下无法验证该日期属实 → 契约来源路径偏离 + 日期可验证性缺口。
- 修复：`git log` 核对 M1 首提交日期；属实则在 L38-39 注明已核对；无法核对则按 CHG-02 标【细化定型】并书明「以 git 提交日期佐证，待复核」。

**P1-2｜TC-CI-06 半落地：记录.md 待办表缺「提交规范差距」登记行**
- 位置：`记录.md` L297-304 待办表（缺失）；`CHANGELOG.md` L20-21（已登记）
- 问题：D7 CI-06 要求记录.md 待办表 + CHANGELOG M6 预留条目**各记一行**；CHANGELOG 侧完成，记录.md 侧缺失 → TC-CI-06 验收不满足。
- 修复：记录.md 待办表补一行：`| 提交规范差距（CI-06） | ⏳ M6 起 | 历史提交无 scope，M6 起按 <type>(<scope>) 执行（存量不追溯，只校验新增） |`。

### P2（7 项）

**P2-1｜CI 门禁双重执行 + 注释过时（口径漂移隐患）**
- 位置：`.github/workflows/ci.yml` L6-10（注释）、L44-50（②③）、L62-89（⑤）；`scripts/run_all_tests.py` L269-275（阶段0）、L290-293（阶段3）
- 问题：ci.yml 注释声称「阶段0 lint / 阶段3 coverage 由 D7 LNT/COV 批次接入后自动继承」，但 run_all_tests.py **已含**阶段0/阶段3 → 步骤②③与阶段0、步骤⑤与阶段3 完全重复执行（ruff/mypy ×2、pytest 全量 ×3、coverage 测量 ×2），CI 时长数倍；且步骤⑤内嵌聚合脚本与 run_all_tests `_aggregate_cov` 是两套独立实现，未来单侧改动即产生 CI 内双口径【静态推断】。
- 修复：按 CI-02 收敛为单一形态——保留步骤④全量调用、删除②③⑤（或反之），并同步修正 L6-10 注释为已完成时态。

**P2-2｜--only help 声明 datapack 但无该层**
- 位置：`scripts/run_all_tests.py` L238（help 文案）；L54-69（LAYER_PATHS 仅 unit/contract/e2e/fault）
- 问题：`--only datapack` 实际落入未知层名分支（L262-266）报错 exit 2，与 help 宣称不符（文档-实现漂移）。
- 修复：补 datapack 层路径，或 help 文案删除 datapack。

**P2-3｜--fast 死参数**
- 位置：`scripts/run_all_tests.py` L239（定义）、main 无任何引用
- 问题：help 宣称「冒烟模式（跳过抽查/抽样收缩）」但实现无效果，静默无效选项。
- 修复：实现其语义或删除。

**P2-4｜TC-CI-07 §9 风险条目未落笔**
- 位置：`docs/实现层规划文档.md` L3498（表尾，仍 8 行）；条目内容在 D7 §七 L348-350
- 问题：D7 CI-07 落笔执行归批7 或 D8，两者均未落地 → TC-CI-07 未覆盖。
- 修复：本批补落第 9 行或将落点移交 D8 并在 D7/记录.md 注明。

**P2-5｜TC-CI-03/04/05 提交规范校验载体空窗**
- 位置：`.github/`（仅 workflows/ci.yml）；`scripts/verify/`（无 verify_m6.py）
- 问题：scope/BREAKING/feat(pack) 分提交校验当前无实体执行点（D7 CI-03 二选一：commit-msg hook 或 verify_m6 grep 断言）。
- 修复：D8 verify_m6 内实现 grep 断言（推荐，CI/本地共用校验点），或补 `.git/hooks/commit-msg`。

**P2-6｜run_all_tests L73 注释与 pytest.ini 矛盾**
- 位置：`scripts/run_all_tests.py` L73（「不用 -q：该环境捕获下 -q 会吞掉 "N passed" 汇总行」）；`pytest.ini` L5（`addopts = -q` 全局生效）
- 问题：注释宣称的意图被 pytest.ini 全局 -q 覆盖（实际每次 pytest 均带 -q）【静态推断 -q 不吞 summary 行，功能无碍，但注释与配置自相矛盾】。
- 修复：`_pytest` 显式加 `-o addopts=` 覆盖，或修订注释为「-rN 保证汇总行，-q 由 pytest.ini 注入」。

**P2-7｜记录.md 头部「最后更新」滞后**
- 位置：`记录.md` L4（2026-08-27）vs L80（批6，2026-08-28）及本批内容
- 问题：批6/批7 记录已写入而头部日期未刷新，后续核对日期易误判。
- 修复：刷新为 2026-08-28。

---

## 五、无问题维度确认（明确确认项）

1. **CHG-01/03/05/06**：建档格式、M6 预留、feat-fix 口径、BREAKING 节约定——全部满足（见 1.1）。
2. **CI-01/02 + TC-CI-01/02**：on push/PR、五步序、失败即 job 失败、调用 run_all_tests 全量入口、阈值 80.0 与本地同源不另定义、产物归档 docs/verify/——全部满足。
3. **依赖与配置接缝**：requirements.txt（ruff/mypy/coverage 锁版本）、pyproject dev 组 + [tool.ruff]/[tool.mypy]、pytest.ini 无 --cov——与 CI 步骤②③⑤ 及本地门禁兼容（批7A 成果确认）。
4. **CI 与 .venv 布局**：ci.yml 建 .venv、全部 .venv/bin/* 调用，与 run_all_tests/verify 脚本硬编码路径同构（兼容）。
5. **伪托 D5 修正链**：「估算口径」全仓 *.py 零残留；verify_m0/记录.md 均引真实 D5（COV-06~09 达成）。
6. **覆盖率归档**：docs/verify/coverage_latest.txt 存在、三目录各自 ≥80%（core 81.47 / engine 90.52 / content 86.57），口径与 COV-02 禁合计稀释一致；lint_baseline.md 存在（LNT-05/06）。
7. **CHANGELOG 回填内容真实性**：M0/M2/M3/M4/M5 五条日期与记录.md 段落完成日逐条一致，条目内容（P0×2/P1×31、361、951、154、81 TC）与记录.md 数字全吻合，无其他编造迹象。

---

*审查基于静态阅读，未执行任何命令；所有【静态推断】项（GHA step 语义、工具行为、归档物生成逻辑）需在首个 CI 实际运行后复核。*