# M6 设计审查 · 批6 · 组A：G4 质量门禁（CI/工具链合规）静态审查报告

> 审查对象：`docs/实现层规划文档.md`【G4 质量门禁（工具链/Git/评审）】L3465-3468（CI 门槛 ruff+mypy+pytest 全绿才合入；覆盖率门槛 engine/+content/ 行覆盖≥80% 且新功能必须有测试；提交信息 Conventional Commits 中文 subject/正文关联定稿/破坏性变更 BREAKING 标注；内容包 JSON 变更 feat(pack) 与代码变更分提交；PR 评审清单安全/性能/错误处理/零代码/并发/可维护性六类 P0 未清零不得合并）。
> 定稿对照：`docs/审查参考/开发规则文档.md` §一.7（L121-123）/§三（L198-273）/§四.6（L333）/§五（L337-386）。
> 已实现参考：`pyproject.toml`、`pytest.ini`、`requirements.txt`、`.github/workflows/`（不存在）、`scripts/run_all_tests.py`、`scripts/verify/*`、`.git/logs/HEAD`、`docs/细化/细化_5d_测试体系总纲.md`、`docs/审查/覆盖审计_A_框架基础.md`、`docs/审查报告/*`。
> 方法：**纯静态审查**（read/glob/grep 文本扫描，未运行任何命令/脚本）；本环境无 bash 沙箱且任务明令禁止运行验证，故一切"能否通过/能否运行"结论均以**【静态推导】**标注，不构成运行验证。
> 结论分级：P0（阻断/门禁悬空，G4 验收不可满足）= **2**；P1（严重缺陷/落地机制缺失/跨文档矛盾）= **6**；P2（改进/命名/文档类）= **4**。

---

## 一、总体结论

G4 六项文本与【规则】§一.7/§三/§四.6/§五 **逐字对齐**（无转述失真），与 M6 里程碑行（L3481）行文一致，与细化_5d 的门禁**意图**一致（细化_5d §3.2 L133 同样要求 ruff/mypy 快速门、L140 要求覆盖率核算）；**未发现 G4 文本编造已有工具链能力**（幻觉维度：无 ruff/mypy 配置、无 CI workflow 的编造声称）。

但 G4 六项中的**「CI 门槛」与「覆盖率门槛」两项在当前仓库无任何可执行载体**，且 G4 未包含使门禁可落地的使能子任务（配置/依赖/流水线/实算工具），导致验收标准①②（L3468）**不可执行**——这是本组核心缺漏，两项均判 P0。其余缺漏集中在：feat(pack) 分提交、PR 评审清单 A-F、提交信息可断言校验、CHANGELOG 等落地机制缺失；跨文档问题集中在：G4 与细化_5d/run_all_tests 未接线、"G4"标签命名冲突、engine/ 口径含糊。

**「应覆盖 X 但未覆盖」点名清单**（详见 P0-1/P0-2/P1-1/P1-2/P1-5/P2-3）：
1. 应覆盖「ruff/mypy 配置与依赖落地」但未覆盖（pyproject/requirements 均无；G4 无使能子任务）。
2. 应覆盖「CI 流水线定义与落地」但未覆盖（无 workflow 文件；G4 验收① 引用不存在的对象）。
3. 应覆盖「覆盖率实算工具与门槛接入」但未覆盖（无 coverage 依赖、无执行、报告无产出；verify_m0 §5 明示"暂不执行"）。
4. 应覆盖「engine/ 口径裁决（core vs engine 并存）」但未覆盖（规则 §4.2 / verify_m0 §5 / G4 各取一词）。
5. 应覆盖「feat(pack) 分提交执行机制」但未覆盖（无顶层 content/、无 hook/CI 检查、无 verify_datapack.py）。
6. 应覆盖「PR 评审清单 A-F 载体（模板文件）」但未覆盖（无 pull_request_template；审查任务调用模板无 A-F 清单）。
7. 应覆盖「提交信息可断言校验（commit-msg hook/CI 步骤）」但未覆盖（验收③ 为人工抽查，且与 G1"禁人工"矛盾）。
8. 应覆盖「CHANGELOG 建档」但未覆盖（仓库无 CHANGELOG.md，G1 L3452 与 M6 L3481 却依赖它）。
9. 应覆盖「G4 与细化_5d 门禁接线（run_all_tests 补 ruff/mypy 快速门/verify_datapack/故障注入/实算覆盖率）」但未覆盖。

---

## 二、P0 问题（2 项）

### P0-1 【缺漏/悬空】CI 门槛（ruff+mypy+pytest 全绿才合入）无可执行载体，验收① 不可满足

- **位置**：`docs/实现层规划文档.md` L3467（"CI 门槛：ruff + mypy + pytest 全绿才合入"）、L3468 验收①（"CI 全绿方可合并（流水线断言）"）；佐证：`pyproject.toml` L1-16（无 `[tool.ruff]`/`[tool.mypy]`，dev 仅 pytest/pytest-asyncio）、`requirements.txt` L9-11（无 ruff/mypy）、`.venv/lib/python3.11/site-packages`（无 ruff/mypy 包，静态推导）、`scripts/run_all_tests.py` L88-102（唯一官方回归入口只跑 pytest 层 + verify_m0~m5，**无 ruff/mypy 步骤**）、`.github/workflows/`（**不存在**，全仓 glob 无 workflow 文件）。
- **问题**：
  1. ruff/mypy 无配置、无依赖、未安装——"ruff + mypy + pytest 全绿"中的前两项无从执行；
  2. 门禁接入点 `run_all_tests.py`（细化_5d §3.2 L133 已要求"ruff/mypy 快速门（L423）"，实现缺失）不跑 ruff/mypy；
  3. **全仓无 CI 流水线**：`docs/实现层规划文档.md` 中全部 6 处"CI/流水线"提及均为抽象表述（L376/L380「随 CI 常驻」、L3468「流水线断言」），无任何任务负责创建 workflow（A1 工程骨架 L3191-3194 不含工具链配置；G1 L3452 只定义 verify 清单模板）。G4 验收①"CI 全绿方可合并（流水线断言）"指向一个不存在且无人负责创建的对象 → **G4 核心验收不可执行**。
- **修复建议**：G4（或 A1 工程骨架）补三项使能子任务并写清落点：a) `pyproject.toml` 增 `[tool.ruff]`/`[tool.mypy]` 配置，`requirements.txt` dev 段加 ruff、mypy；b) `run_all_tests.py` 按细化_5d §3.2 L133 增 ruff/mypy 快速门（短路中止 + `--skip-lint` 逃生口）；c) 新建 `.github/workflows/ci.yml`（PR/推送触发：run_all_tests.py 全量 + ruff/mypy 通过 + 产物留档）。验收① 改为"`run_all_tests.py` exit 0 + ruff/mypy 通过 + CI 流水线断言"，并指定 workflow 文件路径。

### P0-2 【缺漏/悬空】覆盖率门槛（engine/+content/ ≥80%）零实算且测量路径与口径不符，验收② 不可满足

- **位置**：`docs/实现层规划文档.md` L3467（"覆盖率门槛 engine/ + content/ 行覆盖 ≥80%"）、L3468 验收②（"覆盖率达标报告归档"）；佐证：`scripts/run_all_tests.py` L102-103（阶段3 仅打印"覆盖率核算（engine/+content/ ≥80%）：见 verify_m0 §5 估算口径"）、`scripts/verify/verify_m0.py` L149-156（coverage 已装则"请手动核算……**本脚本暂不执行**"；未装则"覆盖率未核算（简版口径……）"）、`pyproject.toml`/`requirements.txt`（无 coverage/pytest-cov）、`verify_m0.py` L152（建议命令 `--source=qbot_rpg/core,qbot_rpg/content`，**测的是 core+content，非门禁口径 engine/+content/**）。
- **问题**：
  1. 与「前批已审：零实算」结论一致——G4 设计**仍未补实算机制**：无 coverage 依赖/配置，run_all_tests 与 verify_m0 均不执行测量（"估算口径"非核算，静态推导）；
  2. 唯一测量建议路径（verify_m0 L152）的 --source 范围是 `qbot_rpg/core,qbot_rpg/content`，与门禁口径 `engine/ + content/` 不一致（见 P1-3）；
  3. G4 验收②"覆盖率达标报告归档"无产出机制（无归档路径、无报表格式）——M6 verify 行 L3481"覆盖率 engine/content ≥80%"在静态上不可断言。
- **修复建议**：a) dev 依赖加 coverage（或 pytest-cov）+ 配置（pytest.ini addopts 或 `[tool.coverage]`）；b) run_all_tests.py 阶段3 改为真实执行 `coverage run --source=<裁决后口径> -m pytest … && coverage report` 并断言 ≥80%；c) 指定报表归档路径（如 `docs/verify/coverage_latest.txt`）作为验收② 凭证；d) 同步修正 verify_m0 §5 的 --source 与门禁口径（先裁决，见 P1-3）。

---

## 三、P1 问题（6 项）

### P1-1 【缺漏】内容包 JSON 变更 feat(pack) 分提交无落地机制

- **位置**：`docs/实现层规划文档.md` L3467（"内容包 JSON 变更（feat(pack)）与代码变更分开提交"）；佐证：仓库无顶层 `content/` 目录（glob 无），仅有 `tests/fixtures/packs/` 四类 fixture（legal/badref/missing_mod/old_schema 已齐）；`.git/logs/HEAD` 全量 93 行无任何 `feat(pack)` 或带 scope 的提交（静态推导）；`scripts/verify/` 无 `verify_datapack.py`（细化_5d L164/L313 规划存在）。
- **问题**：G4 忠实转述规则 §3.1/§3.3，但未指定执行/校验机制（pre-commit hook 或 CI 检查：content/ 路径变更不得与 qbot_rpg/ 代码同提交）；且内容包本体尚不存在，该条长期悬置无抓手。
- **修复建议**：G4 补落地：a) 明确 `content/` 目录建立后的分提交校验脚本（单 commit 不同时含 content/ 与 qbot_rpg/ 变更）；b) 挂 CI 步骤或 git hook；c) 与细化_5d verify_datapack 脚本落地计划衔接（其缺失同时影响 M6 所属 G6 门禁，见 P1-5）。

### P1-2 【缺漏/矛盾】PR 评审清单 A-F 无载体且与实际流程两套；验收④ 无从勾选

- **位置**：`docs/实现层规划文档.md` L3467（"PR 评审清单……P0 未清零不得合并"）、L3468 验收④（"评审清单 A-F 逐项可勾选"）；佐证：规则 §5.2 L345-386（清单本体仅存在于规则文档）；仓库无 `.github/pull_request_template.md`；`docs/审查/审查任务调用模板.md` 无 A-F 清单；`docs/审查报告/*.md` 全部使用自定义 P0/P1/P2 格式，未见 A-F 勾选（抽样 `审查_M0复查_架构分层_20260824.md` L5-6）；`docs/审查/覆盖审计_A_框架基础.md` L88 明言"**清单本体无细化（工程流程，实现时处理）**"；`.git/logs/HEAD` 全部直接提交 main、无 PR/merge 记录（静态推导），规则 §3.2"main 必须走 PR"未执行。
- **问题**：① 验收④"评审清单 A-F 逐项可勾选"未指定载体（模板文件），无从勾选；② 实际审查流程是 dsh 审查（docs/审查报告 专用格式），与规则 §5 的 PR 评审流程是**两套体系**，衔接未定义；③ "P0 未清零不得合并"预设 PR 合并流程，而仓库无 PR 流程（全直推 main），P0 清零门无入口。
- **修复建议**：a) 新建 `.github/pull_request_template.md`（含 A-F 六类 checklist 逐项可勾选）；b) 定义 dsh 审查报告结论 → A-F 清单的映射规则；c) 落地规则 §3.2 分支策略（develop/feature + PR 回 develop）或显式登记"小团队直推 main"豁免（规则 §3.2 L232 允许），否则该条与 P1-2 均悬置。

### P1-3 【错误】覆盖率口径 "engine/" 指代含糊 + 测量路径不一致

- **位置**：`docs/实现层规划文档.md` L3467（"engine/ + content/"）；佐证：`qbot_rpg/engine/`（5 个文件：weather_consumers/condition_engine/worldtime/time_query/weather_conditions）与 `qbot_rpg/core/`（30+ 文件：battle/damage/effects/levelup/equipment 等）**两个包并存**；`scripts/verify/verify_m0.py` L152 建议 `--source=qbot_rpg/core,qbot_rpg/content`（core+content）；规则 §4.2 L287-297 必测表点名 battle.py/damage.py/levelup.py 等（位于 core/）。
- **问题**：门禁口径"engine/"若按字面只测 `qbot_rpg/engine/` 小包，则 battle/damage 等核心逻辑（core/）不在门槛内，80% 将虚高且失去意义；若意图是"引擎层"则应显式含 core/。规则 §4.2 与 verify_m0 §5 各取一侧，G4 未裁决 → 门槛计算对象不定，验收② 无法稳定复跑。
- **修复建议**：G4 明确定义 coverage 目标 = `qbot_rpg/core + qbot_rpg/engine + qbot_rpg/content`（或与规则 §4.2 引擎清单对齐），并同步 verify_m0 §5 与 run_all_tests 的 --source。

### P1-4 【错误】G4 与 G1「verify 必须可执行且有断言」矛盾（验收③④ 为人工抽查）

- **位置**：`docs/实现层规划文档.md` G1 L3452（"**verify 必须可执行且有断言**（禁'人工看了没问题'）"）；G4 L3468 验收③（"提交信息规范抽查（subject ≤72 字、关联定稿）"）、④（"评审清单 A-F 逐项可勾选"）；佐证：`.git/logs/HEAD` L91-93 等多条提交 subject 目测远超 72 字（静态推导：reflog 为明文文本）。
- **问题**：G4 验收③④ 是人工抽查/勾选、无断言，与同文档 G1 的硬性要求直接矛盾；验收③ 无执行载体（无 commit-msg hook、无 CI 检查步骤）；且现有历史大量 subject 超 72 字，抽查基准（查存量还是只查新增）未定义。
- **修复建议**：G4 将验收③ 改为可断言机制：commit-msg hook 或 CI 步骤校验 subject 格式/长度（≤72）+ 正文定稿引用（软校验），明确存量提交豁免口径；验收④ 改为 PR 模板勾选（见 P1-2）。

### P1-5 【跨文档】G4 门禁与细化_5d / run_all_tests 未接线（门禁口径分裂、实现缺失）

- **位置**：`docs/细化/细化_5d_测试体系总纲.md` §3.2 L133（ruff/mypy 快速门）、L124/L138/L140（全量回归 = 7 verify + verify_datapack + 故障注入 + 覆盖率核算）、§6.1 G6 L227（M5/M6 门禁含 verify_datapack + 故障注入 + 安全回归）；`scripts/run_all_tests.py` L34-48（MILESTONES 仅 m0~m5、m6=None；LAYER_PATHS 无 fault/datapack；L75-85 `--only datapack/fault` 落入全量 else 分支 = 静默跑全量，静态推导）；`scripts/verify/`（无 verify_m6.py/verify_datapack.py/六故障注入脚本）。
- **问题**：G4 定稿依据只引规则 §一.7/§三/§五/§四.6，**未引细化_5d，也未指定落地载体**；细化_5d 已把 ruff/mypy 快速门、覆盖率核算、verify_datapack、故障注入写进 run_all_tests 契约（L133-140），但实现全部缺失——G4 与细化_5d 意图一致、却都没有驱动实现落地；M6 所属 G6 门禁（L227）同样依赖不存在的 verify_datapack/故障注入脚本。
- **修复建议**：G4 增"落地载体"字段：点名 `scripts/run_all_tests.py`（细化_5d §3.2）+ 新建 verify_m6.py/verify_datapack.py/六故障注入脚本，作为 M6 verify 前置；验收① 引用细化_5d TC-5d-17/15 作为断言入口。

### P1-6 【错误/缺漏】M6 里程碑 verify 行将未实现项写成验收项（L3481）

- **位置**：`docs/实现层规划文档.md` L3481（"M6 接线闭环 | … | 覆盖率 engine/content ≥80%；ruff/mypy/pytest 全绿；CHANGELOG 归档"）；佐证：仓库无 `CHANGELOG.md`（glob 无），G1 L3452 亦要求"每个里程碑 verify 后更新 CHANGELOG"，全仓无该文件。
- **问题**：① "覆盖率 engine/content ≥80%"与"ruff/mypy/pytest 全绿"当前均无执行载体（P0-1/P0-2），里程碑表却把未实现的门禁写成可勾选验收项；② "CHANGELOG 归档"依赖不存在的 CHANGELOG.md；③ 与 run_all_tests 阶段3"估算口径"呼应，有把估算当核算之嫌（静态推导）。
- **修复建议**：M6 verify 行改为指向可执行项："`run_all_tests.py` 全量 exit 0（含 ruff/mypy 快速门 + 覆盖率实算报表 ≥80%）+ verify_m6 全绿 + 新建 CHANGELOG.md 并归档更新"。

---

## 四、P2 问题（4 项）

### P2-1 【跨文档】"G4"标签命名冲突
- **位置**：`docs/实现层规划文档.md` L3465 "G4 质量门禁" vs `docs/细化/细化_5d_测试体系总纲.md` L225 "**G4 地图（M3）门禁**"（细化_5d 门禁编号 G0~G7，L219-228）。两个文档的 "G4" 指不同对象，跨文档引用时歧义。
- **修复**：实现层规划 G 组任务改编号（如 QG4）或细化_5d 门禁改门禁号（如 GATE-4），全仓检索替换并回写引用点。

### P2-2 【错误】G4 未继承规则 §3.3 的 scope 要求（提交格式从 `<type>(<scope>)` 退化为 `<type>`）
- **位置**：`docs/实现层规划文档.md` L3467（未提 scope）；规则 §3.3 L237（"格式：`<type>(<scope>): <subject>`"）；佐证：`.git/logs/HEAD` 几乎全部为无 scope 的裸 `feat:`/`fix:`（静态推导）。
- **修复**：G4 明确写 `type(scope)` 格式（内容包=pack、battle/formula 等），否则 feat(pack) 分提交的识别依赖 scope 将落空（P1-1 的校验脚本需按 scope 区分）。

### P2-3 【缺漏】破坏性变更 BREAKING 标注与 CHANGELOG 无落地
- **位置**：`docs/实现层规划文档.md` L3467（"破坏性变更 BREAKING 标注"）；佐证：仓库无 CHANGELOG.md；reflog 仅含 subject、无法验证 BREAKING footer 是否存在（静态推导：footer 不可从 reflog 读取）。
- **修复**：G4 增"建档 CHANGELOG.md（Keep a Changelog 格式）+ 提交规范强制 BREAKING CHANGE footer"，与 G1 L3452/M6 L3481 的 CHANGELOG 要求形成闭环。

### P2-4 【相邻发现（非 G4 文本）】`.git/config` 含明文 GitHub PAT
- **位置**：`.git/config` L10（`branch.main.remote` URL 内嵌 `ghp_...` 明文 token）。
- **说明**：该文件为本机配置、不入库不随 push 分发，但任何持有工作副本者可读；建议轮换该 token 并改用凭据管理器/SSH。属审计过程相邻发现，不属 G4 设计缺陷。

---

## 五、维度对照小结

**① 缺漏**：P0-1（CI 门槛悬空）、P0-2（覆盖率零实算）、P1-1（feat(pack) 分提交无机制）、P1-2（评审清单无载体）、P1-5（门禁未接线）、P2-3（CHANGELOG/BREAKING 无落地）；「应覆盖 X 但未覆盖」清单见第一节 9 项点名。

**② 错误**：G4 六项与【规则】§一.7/§三/§四.6/§五 **逐字对齐**（✅ 无转述失真）；与现有提交历史**前缀不冲突**（feat:/fix:/docs:/chore:/refactor:/test: 均已实践，✅ 无冲突）；但与已实现（run_all_tests.py 无 ruff/mypy）及 G1（L3452）的"verify 可执行有断言"矛盾（P0-1/P1-4）；与 M6（L3481）行文一致但所引验收项不可执行（P1-6）；engine/ 口径含糊（P1-3）；scope 退化（P2-2）。

**③ 幻觉**：**无编造已有工具链能力**——G4 文本未声称存在 ruff/mypy 配置或 CI workflow（✅）；但两处需修正：G4 验收①"流水线断言"引用不存在的对象（设计悬空，非编造现状，P0-1）；`run_all_tests.py` L102-103 把"估算口径"当作"覆盖率核算"输出（静态推导，实现层过度声称，非 G4 文本）。

**④ 跨文档**：G4 ↔ 【规则】对齐（✅）；G4 ↔ M6（L3481）行文一致但验收悬空（P1-6）；G4 ↔ G1（L3452）"禁人工"矛盾（P1-4）；G4 ↔ 细化_5d 意图一致但未接线（P1-5）；G4 与规划_路3 L327-329 为同文副本（✅ 无冲突）；"G4"标签与细化_5d 门禁编号冲突（P2-1）；覆盖审计_A L88 已登记"评审清单无细化"开放项，G4 未承接（P1-2）。

---

*方法声明：本报告全部为静态审查（read/glob/grep），未执行任何命令；所有运行行为结论（coverage 未安装、ruff/mypy 未安装、--only datapack 静默跑全量、提交信息长度等）均为「静态推导」。*
