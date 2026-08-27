# 审查报告：M6 实现层批7A（质量门禁 · coverage + lint）

> 审查方式：**纯静态代码审查**（本环境无 bash 沙箱且任务明令禁止运行命令/脚本/验证——全程 0 命令执行）。
> 所有运行行为结论（退出码、子进程行为、coverage 输出形态等）均为**静态推导**，文中以 ⚙️静态推导 标注。
> 审查框架：j-space 技能（用户指定 full 档：唤醒 → 门控 → 接缝审计 → ship）。
> 审查基准：docs/细化/细化_M6_质量门禁.md（D7）§一 COV-01~09 / §二 LNT-01~06 / TC-COV×8+TC-LNT×5；
> 参考：细化_5d §7.4（D5 行）、细化_M6_verify门禁与承接.md（D8 VG-05/06 断言预期）、记录.md L300。
> 审查对象：scripts/run_all_tests.py、scripts/verify/verify_m0.py、pyproject.toml、requirements.txt、
> docs/verify/lint_baseline.md、docs/verify/coverage_latest.txt、细化_5d §7.4。

## 〇、结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| P0 | **0** | 未发现门禁旁路、假绿、契约缺项落地失败 |
| P1 | **3** | TC-COV-04 假数据双向验证无载体；per-file-ignores「新增零豁免」不可机械执行+豁免扩容无拦截；覆盖率报表不含未导入文件（测量基数收缩，与 1.2 全集无对账） |
| P2 | **6** | verify_m0↔run_all_tests 双实现漂移；异常路径裸崩且跳过归档；lint 工具缺失无诊断信息；mypy python_version 未定档；记录.md L300 措辞矛盾；继承项（--fast 死参数/--only m6 return 0/help 广告 datapack）登记确认 |

D7 契约 COV-01~09 / LNT-01~06 **载体全部落地且静态自洽**；「各自 ≥80% 禁合计稀释 / exit≠0 阈值断言 / 归档写入者 / coverage json 7.15.4 兼容 / verify_m0 M6 恢复无陈旧术语 / --skip-lint 逃生口」六个维度**确认无问题**（详见 §三）。

---

## 一、P0（0 项）

无。⚠️ 说明：`--only m6` return 0（run_all_tests.py L225-229）与 `--fast` 死参数（L214）为**既有继承问题**（D8 档 L9 已登记，置位归 D8），本批未触碰、未引入新旁路，详见 P2-6。

---

## 二、P1（3 项）

### P1-1｜TC-COV-04「假数据双向验证」无执行载体（声明与实现脱节）
- **位置**：scripts/run_all_tests.py L168-190（`_coverage_gate` docstring L172：自述「阈值分支可注入假数据测 exit≠0」）；L93-140（`_coverage_measure`）
- **问题**：全仓 tests/ 无任何引用 `_coverage_measure`/`_coverage_gate`/`_write_coverage_archive` 的测试（grep 确认）；`_coverage_measure` 的 JSON 来源是内部 `NamedTemporaryFile`（L113-115），**无注入参数/环境变量钩子**，外部无法喂假数据。维度②「假数据双向验证」：① 假数据→断言（<80% → ok=False/exit≠0；≥80% → ok=True；零语句目录 → False）② 真核算→归档格式断言，**双向均无载体**。契约 TC-COV-04 验收用例按设计不可执行——「阈值分支可注入假数据」停留在 docstring 声明。
- **修复建议**：将 L124-140 的聚合/判定逻辑抽取为纯函数 `_aggregate_cov(json_data: dict) -> tuple[bool, dict]`（不依赖 tempfile/子进程），新增 tests/unit/test_quality_gate.py 直接喂双向假 JSON（含 79.99%/80.01% 边界、零语句目录、目录缺失三种形态）；归档格式断言由同一测试对 `_write_coverage_archive` 的输出做形状校验。

### P1-2｜「新增零豁免」仅对未豁免文件成立；豁免清单扩容无自动化拦截
- **位置**：pyproject.toml L31-214（`[tool.ruff.lint.per-file-ignores]` 181 条）；docs/verify/lint_baseline.md §一/§五；run_all_tests.py L193-208（`_lint` 仅依赖 ruff/mypy 退出码）
- **问题**：LNT-05/06 要求「清单内存量放行、清单外新增必拦、豁免仅限存量、不得新增豁免」。现状（静态核对）：
  1. per-file-ignores 是**整文件×整规则码**豁免——豁免文件内**新增**的 E501/F401 等违规行不拦截（181 文件覆盖全仓绝大多数生产与测试代码，E501 尤甚）——「新增代码零豁免」在机制上不可满足；
  2. 向 per-file-ignores **追加新文件/新码 = 扩容豁免清单**，无任何门禁检测该扩容（基线清单↔pyproject 双向对账无自动化, `_lint` 只看两工具退出码）。
  即维度①「基线豁免新增必拦」只剩半截：新文件的新问题会被拦 ✓（文件不在豁免表内即报错），但豁免表自身可静默增长。
- **修复建议**：D8 verify_m6 增断言——解析 lint_baseline.md §二 文件集合 == pyproject per-file-ignores 键集合（防扩容/防漂移）；新豁免一律改用逐行 `# noqa:<code>` 并携日期注解（保留行级坐标），per-file-ignores 冻结为存量快照。

### P1-3｜覆盖率报表不含「未导入源文件」：percent 基数收缩，与契约 1.2 目录全集无对账
- **位置**：run_all_tests.py L93-140 / verify_m0.py L56-102；契约 D7 §1.2（core 27 + engine 6 + content 16 文件全集）
- **问题**（⚙️静态推导，证据来自 .venv 内 coverage 7.15.4 源码）：`coverage json` 无 morfs 时走 `_get_file_reporters(morfs=None)` → `morfs = self._data.measured_files()`（coverage/control.py L1075-1076），即**仅已执行（被 import）文件入报表**；未导入文件只触发 "Module … was never imported" 警告（被 `capture_output` 吞掉）而不计 statements。后果：新增一个零测试的模块 → 百分比**不受影响**（不拉低），报表 81.47%/90.52%/86.57% 是「已导入文件」口径而非契约 1.2 全集口径；content/「零代码配置层低覆盖」防线（COV-02）对「整模块隐身」无效。
- **修复建议**（任选其一）：① 报表/程序输出中显式登记口径「已导入文件行覆盖（未导入文件不入 statements，coverage 标准语义）」；② D8 增断言：报表 files 数 ≥ 契约 1.2 全集文件数（或逐文件存在性核对 core 27/engine 6/content 16），发现缺失即提示补测；③ 对目录做抽样核对（如 grep 报表中是否有 battle.py/formula_engine.py 等必测表文件）。

---

## 三、P2（6 项）

### P2-1｜coverage 核算双实现 + 测量集不一致（口径漂移风险）
- **位置**：verify_m0.py L51-102（`_measure_coverage`，测量集 = unit/contract/e2e）vs run_all_tests.py L83-190（`_coverage_measure`，测量集 = unit/contract/e2e/**fault**）
- **问题**：近 50 行逐行复制（COV_SOURCES/COV_DIRS/COV_THRESHOLD/聚合/判定逻辑×2），且 fault 层加入测量运行后两处数字**必然不同**——`--only m0`（或独立跑 verify_m0）与全量阶段3 会出现两套覆盖率；边界态（全量含 fault 后某目录 79.9% vs verify_m0 口径 80.1%）可给出相反判定。fault 文件不匹配 `test_*.py`、以子进程注入故障，计入测量对百分比无污染（tests/ 不在 --source 内）但影响「测量运行须全绿」的门槛集。
- **修复建议**：抽取公共模块（如 scripts/verify/_cov_common.py）统一测量集与函数；或 verify_m0 复用 run_all_tests 的 `_coverage_measure`（参数化 paths）。

### P2-2｜报表解析异常路径裸崩且跳过归档
- **位置**：run_all_tests.py L120-124；verify_m0.py L82-86（`json.loads(Path(tmp_json).read_text(...))` 无 try/except 包裹解析）
- **问题**（⚙️静态推导）：若 `coverage json` 输出缺失 `files`/`summary` 键或 JSON 损坏 → KeyError/JSONDecodeError 未捕获 → traceback 直接退出（exit 1，门禁语义未破）但 `_write_coverage_archive` **不被调用**（归档物缺失，TC-COV-05 存在性断言在异常态失败）。
- **修复建议**：解析包 try/except → 打印「coverage 报表解析失败（coverage 版本/schema 异常?）」并继续走「测量失败」归档分支（L159-160 已有如实归档能力）。

### P2-3｜lint 工具缺失时 FileNotFoundError 裸崩，无可诊断信息
- **位置**：run_all_tests.py L201-207（`subprocess.run([str(PY.parent / tool), ...])`）
- **问题**（⚙️静态推导）：全新克隆按 requirements.txt 安装前跑全量 → `.venv/bin/ruff`/`mypy` 不存在 → FileNotFoundError traceback（exit≠0 语义保住，但无「pip install -r requirements.txt」指引）；.venv/bin/{ruff,mypy,coverage} 当前均存在（glob 确认），属健壮性问题。
- **修复建议**：`_lint` 捕 FileNotFoundError → 打印安装指引 + return False；同理 `_coverage_measure` 的 `coverage` 入口。

### P2-4｜mypy 目标版本未定档，与 ruff target-version=py39 不一致
- **位置**：pyproject.toml L25（`target-version = "py39"`）vs L216-225（`[tool.mypy]` 无 `python_version`）
- **问题**：mypy 未设 `python_version` 时默认取运行解释器版本（.venv 为 3.11）——名义语法下限两工具不一致（3.9 语义在 mypy 侧不校验）；「non-strict 定档」（D7-D1）成立，但版本定档缺失另一半。
- **修复建议**：`[tool.mypy] python_version = "3.9"`（先实跑确认存量代码无 3.10+ 语法报错，避免门禁突变），或在 lint_baseline 技术备案中显式登记「mypy 以解释器 3.11 为分析目标」。

### P2-5｜记录.md L300 单元格内措辞自相矛盾
- **位置**：记录.md L300「覆盖率 ≥80% 硬门禁 | ⏳ M6 恢复 | verify_m0 当前**简版口径**（5d §7.4 决策记录 D5 登记；M6 批7·路A 已接入**真实核算**：verify_m0 §5 / run_all_tests 阶段3）」
- **问题**：COV-08 的「M1→M6 恢复 + 引真实 D5」已满足 ✓，但同一单元格「当前简版口径」与「已接入真实核算」并存，读者歧义。
- **修复建议**：改为「⏳ M6 恢复（M6 批7·路A 已接入真实核算：verify_m0 §5 / run_all_tests 阶段3；M0-M5 简版口径见 5d §7.4 D5）」。

### P2-6｜继承项登记（非本批引入，D8 范围，静态确认无新旁路）
- **位置**：run_all_tests.py L213（help 广告 datapack 但 `datapack` 不在 LAYER_PATHS → 未知层名 exit 2）、L214（`--fast` 解析后全程未用）、L225-229（`--only m6` → `script is None` → return 0 假绿语义指向 D8 置位）
- **说明**：D8（细化_M6_verify门禁与承接.md L9）已全部登记并承担置位；本批未改。建议与 P1-2 修复同批处理 `--only m6` 的假绿语义（D8 置位时自然消除）。

---

## 四、无问题维度确认（契约逐条 + 审查维度①）

| D7 条目 | 静态核验结论 |
|---|---|
| COV-01 依赖落地 | ✅ requirements.txt L17 `coverage==7.15.4`（锁版本，与 .venv 实装 version.py `(7,15,4,…)` 一致）；pyproject L13 dev 组 `coverage>=7`；无 hypothesis |
| COV-02 口径定死 | ✅ 三目录各自 ≥80%（run_all_tests L86-88；verify_m0 L51-53）；无 `--fail-under` 综合阈值（D7 §1.4 合计稀释拦截成立）；零语句目录视为不达标（L138） |
| COV-03 测量路径 | ✅ `--source=qbot_rpg/core,qbot_rpg/engine,qbot_rpg/content` 恰为三目录；按目录聚合 statements/covered_lines 求和（L124-131）；子包 message_format 随 core/ 前缀归入（L127） |
| COV-04 阈值断言 | ✅ 任一 <80% → fail → exit 1（L267-268/L273）；非仅打印；测量运行 pytest 红 → 不放行（L107-112） |
| COV-05 归档 | ✅ COV_ARCHIVE=docs/verify/coverage_latest.txt（L90）；写入者 = run_all_tests 覆盖率段（L89 注释/归档头 L152）；测量失败也如实归档「—（测量失败）」行（L158-160）；归档物存在且数字自洽（见下） |
| COV-06 verify_m0 恢复 | ✅ §5 标题/正文「M6 恢复真实核算」（L262）；覆盖率**纳入通过判定**（L282 `cov_ok and …`）；「估算口径」「M1 恢复」全仓 scripts/ 零残留（grep 确认，仅存于历史审查报告与契约引文） |
| COV-07 verify_m0 引 D5 | ✅ L50/L273 显式引「细化_5d §7.4 决策记录 D5」；5d §7.4 确有 D5 行（细化_5d L303，紧随 D4 L302，与契约 §6.2「原样追加」一致） |
| COV-08 记录.md 引 D5 | ✅ 记录.md L300 已改「M6 恢复 | … 5d §7.4 决策记录 D5 登记」 |
| COV-09 run_all_tests 阶段3 | ✅ L174 阶段3 标题「真实核算（M6 恢复）」；「估算口径」术语已删 |
| LNT-01 [tool.ruff] | ✅ line-length=100（L24）、target-version=py39（L25）、select=E/F（L29）、**无全局 E501 ignore** |
| LNT-02 [tool.mypy] | ✅ non-strict 定档（无 strict，D7-D1 记载于 L217-218）；warn_unused_ignores/warn_redundant_casts=true（L219-220） |
| LNT-03 依赖落地 | ✅ requirements L13-14 `ruff==0.16.5`/`mypy==2.3.1` 锁版本；pyproject dev 组 `ruff>=0.5, mypy>=1.10`（L13） |
| LNT-04 阶段0 快速门 | ✅ 阶段0 在阶段1 前（L244）；失败置 fail 并继续收集全部失败（D7-D2，L248-250）；`--skip-lint` 逃生口 + 输出注明跳过（L245-246）；CI 共用入口口径成立（D8 VG-06 引用同入口） |
| LNT-05/06 基线承载 | ✅ lint_baseline.md 存在且非空（278 行）；ruff 由 per-file-ignores 181 条承载、mypy 由 `# type: ignore[码]` 逐处承载（verify_m0 L110-111 实证）；格式含 文件+规则码+计数+首次发现日期 ✓；「新增必拦」半截成立（见 P1-2） |
| coverage json 7.15 兼容 | ✅（⚙️静态推导，证据 = .venv coverage 7.15.4 源码）：jsonreport.py `files[relative_filename]` 存在且 `summary` 含 `num_statements`/`covered_lines` 两键（与解析代码 L128-130 逐键吻合）；`relative_filename` 相对 coverage 进程 cwd（两子进程均 cwd=仓库根）→ `fpath.startswith(d+"/")` 匹配成立；`coverage json` 无 morfs → 走 report 管线（data.measured_files），schema 无版本分支需要 |
| 归档数字自洽 | ✅ coverage_latest.txt：core 7721/9477=81.47%、engine 907/1002=90.52%、content 4621/5338=86.57%（逐项四则复核；三目录均 ≥80，门禁行正确）；格式与 `_write_coverage_archive` 输出逐行吻合 |
| 基线↔配置对账 | ✅ 静态抽样：per-file-ignores 181 条 ↔ 清单 §二 181 行 ↔ 双方声明「181 文件」一致；规则码抽样 15 处全部吻合（含 F822/F541/E731/E401/E702/E741/F601/F811 等稀有码）；§四 统计自洽（ruff 各码求和=1582 ✓；mypy 各码求和=283 ✓；mypy 58 文件 ✓）；计数精度未全量枚举（需执行，静态标注） |
| pytest.ini 轨道 | ✅ 无 `--cov`（COV 边界「coverage 命令行二选一」成立，无 pytest-cov 双轨） |
| D8 接缝（VG-05/06） | ✅ D8 断言对象（三目录各自 ≥80% + 报表落 docs/verify/ + ruff/mypy 通过 exit≠0）与本批产物逐一对应，无缺口 |
| e2e 冒烟接缝 | ✅ test_e2e_m6_smoke.py 未入 LAYER_PATHS（L57 注释）、MILESTONES["m6"]=None（L52）——与 D8/SMK-17 置位协议一致，无漂移 |

---

## 五、j-space 接缝审计记录（①~⑩）

① 契约锚定（D7 全文 435 行）→ ② 阶段0↔阶段3（run_all_tests）→ ③ verify_m0↔run_all_tests 通过判定（exit 语义一致，测量集见 P2-1）→ ④ pyproject↔requirements↔baseline 三载体（一致 ✓）→ ⑤ per-file-ignores↔baseline 双向对账（181/181 + 抽样 ✓，见 P1-2 盲区）→ ⑥ 归档物↔写入格式（逐行吻合 ✓）→ ⑦ D5 行↔verify_m0↔记录.md 三处一致（✓）→ ⑧ coverage schema↔解析代码（7.15.4 源码静态证实 ✓）→ ⑨ 路径前缀+measured_files 口径（前缀 ✓；未导入文件见 P1-3）→ ⑩ pytest.ini/D5 上下文/D8 断言预期/工具可执行体（✓）。

**静态推导标注汇总**：所有退出码/子进程/coverage 输出形态结论均基于源码静态阅读推导（含 coverage 7.15.4 内部实现），未以任何方式执行验证；「cov_ok→exit 1」「测量运行红→不放行」「per-file-ignores 拦截范围」「未导入文件不入报表」均属此类。

**修复优先级建议**：P1-1（补 TC-COV-04 载体）与 P1-3（口径登记/对账）宜随本批立即补；P1-2 与 D8 verify_m6 断言同步落地；P2 各项随代码重构窗口消化（轮换规则：豁免随重构消除）。

---
*报告终。审查范围 = 7 文件 + 2 契约 + 2 归档物 + coverage 7.15.4 源码；P0=0 / P1=3 / P2=6。*