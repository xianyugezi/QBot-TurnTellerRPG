# 审查报告：M6 G1 里程碑 verify 跨里程碑一致性（组B：M1-M6 衔接）

> 审查方式：**纯静态审查**（本环境无 bash 沙箱，禁运行命令/脚本/验证；所有运行行为结论均标「静态推导」）。
> 审查范围：`docs/实现层规划文档.md` G1 L3450-3453 + §8 里程碑表 L3472-3483（M6 行 L3481）+ G2/G3/G4 L3455-3468；
> 已实现参考 `scripts/verify/verify_m0~m5.py`、`scripts/run_all_tests.py`、`scripts/e2e_m3_smoke.py`/`scripts/e2e_m4_smoke.py`；
> 旁证 `docs/细化/细化_5d_测试体系总纲.md`（§2.1 矩阵 L89-95、§3.2 流程 L118-140、§6 G 门禁 L222-227、TC-5d-07/15/17/19/31）、`docs/实现层启动手册.md`（L42/L44）、`pyproject.toml`、`tests/unit/test_e2e_m4_smoke.py`。
> 审查维度：①缺漏（跨里程碑重点）②错误 ③幻觉 ④跨文档。分级 P0/P1/P2。

---

## 结论摘要

- **P0 × 3**（跨里程碑一致性断裂：M6 定义三处冲突；M6 未实现却返回假绿；M6 verify 列 6 项中 4 项零实现零接入）
- **P1 × 5**（DELAYED 过期不检测且已实证失真；DELAYED→M6 承接孤儿；冒烟闭环无落地载体且依赖未实装 /注册；G1 模板 5 步与 M6 列 6 项不对应；run_all_tests 与细化_5d 流程不符 + help 广告未实现过滤）
- **P2 × 4**（verify_m0 覆盖率「硬门禁」声明与行为矛盾；G 编号跨文档混乱；缺失测试文件黄提示不判失败；细化_5d TC 计数陈旧）
- **幻觉结论**：未发现 verify_m0~5 直接编造「已跑 ruff/mypy/覆盖率/CHANGELOG/故障注入」；但存在 3 处「悬挂/误导声明」（run_all_tests 阶段3 把未实现包装成已接入口径、verify_m0「硬门禁」与 exit 0 矛盾、「M1 恢复硬门禁」未兑现）与 1 处「过期声明失真」（verify_m4 批次7-01）。

---

## P0（3 项）

### P0-1　M6 里程碑范围三处定义冲突，verify_m6.py 内容无唯一权威

- **位置**：`docs/实现层规划文档.md` L3481（M6 接线闭环=F5-F6、G2-G4，6 项质量门禁）vs `docs/细化/细化_5d_测试体系总纲.md` L95（M6 数据=3e 30+3e2 14+5a 18+5b 34+5c 18=**114 TC**，verify_m6.py）vs `docs/实现层启动手册.md` L42 + `scripts/run_all_tests.py` L42 注释（M6 数据框架=**5a/5b/4c/4d/4e/6 系**）。
- **静态推导**：三份权威对「M6 到底验收什么」给出三套互斥范围。M6 verify 列（L3481）的 6 项（热重载/冒烟/故障注入/覆盖率/ruff-mypy-pytest/CHANGELOG）**与细化_5d 的 114 条 TC（3e/3e2/5a/5b/5c）无一条对应**，与启动手册的 5a/5b/4c/4d/4e/6 系也无对应（后者是内容数据系统，前者是质量门禁）。「M6 verify 列 6 项如何落到 verify_m6.py」在现有文档**无答案**：G1 只给了 5 步模板，M6 列只给了 6 个验收项，二者之间没有把 6 项翻译成 verify_m6.py 可执行断言的结构（尤其「里程碑验收单」「结果归档」这类非 pytest 项）。
- **修复**：以 G1 §8 为唯一权威，仲裁 M6 的双重语义——要么把「M6 数据（3e/3e2/5a/5b/5c 或 5a/5b/4c/4d/4e/6 系）」与「M6 质量门禁（6 项）」合并为 M6 的分层验收（内容 TC 断言 + 质量门禁两段式 verify_m6.py），要么把「数据框架」移到 M5/M7 并同步三份文档；细化_5d L95、启动手册 L42、run_all_tests L42 必须与 §8 一致。

### P0-2　run_all_tests 对未实现 M6 返回「假绿」：`--only m6` exit 0，全量回归静默跳过 m6 不判失败

- **位置**：`scripts/run_all_tests.py` L75-79（`script is None → print("[未实现]...") → return 0`）、L96-97（全量时 `script is None → continue`，不置 fail）。
- **静态推导**：`run_all_tests.py --only m6` 对**未实现的里程碑返回 exit 0（通过语义）**；全量回归中 m6=None 被静默跳过且不使 `fail` 置真。直接违反 G1 `L3453` ①「每里程碑 verify 清单逐项可勾选且命令可复跑」与 ③「任一红拦类回归失败 → 里程碑不通过」的判定语义——任何把 run_all_tests 当 CI 门禁的调用都会在 M6 完全缺席时误判全绿。G1 ③ 的「回归结论 exit 非 0」对齐仅对**已实现**里程碑（M0-M5，L101 `fail = fail or rc != 0`，L107 return 1）成立，对 M6 不成立。
- **修复**：`--only m6` 在 script is None 时 return 1（显式失败并提示未实现）；全量回归在 m6=None 时置 fail 或打印「M6 未接入 → 门禁不完整」且 exit 非 0，保证「未实现 ≠ 通过」。

### P0-3　M6 verify 列 6 项中 4 项（覆盖率 / ruff-mypy / CHANGELOG / 故障注入）在 M0-M5 与 run_all_tests 零实现零接入

- **覆盖率 engine/content ≥80%**：`verify_m0.py` L149-157 仅打印「请手动 `coverage run ...`」；L162-167 通过判定**不含覆盖率**（不核算也 exit 0）；`verify_m1.py`~`verify_m5.py` 全文无任何覆盖率段；`run_all_tests.py` L102 阶段3 仅打印「见 verify_m0 §5 估算口径」；`细化_5d` TC-5d-15（L267）要求「run_all_tests 末尾输出行覆盖率并与 80% 阈值比对」——**未实现**。且 `verify_m0.py` L154/L157 承诺「M1 恢复硬门禁」**未兑现**（verify_m1 无覆盖率段）。
- **ruff/mypy**：全仓无 ruff/mypy 配置（`pyproject.toml` 无 `[tool.ruff]/[tool.mypy]`，无 ruff.toml/mypy.ini），无任何执行点；`细化_5d` L133「ruff/mypy 快速门」未实现；`run_all_tests.py` 无 lint 段。
- **CHANGELOG 归档**：仓库**无 CHANGELOG 文件**（glob `CHANGELOG*` 为空）；G1 L3452「每个里程碑 verify 后更新 CHANGELOG」从未落地；M6 列「CHANGELOG 归档」无承载对象、无校验脚本。
- **故障注入六类**：全仓无故障注入测试（glob `tests/**/test_*fault*.py` 为空）；`run_all_tests.py` L64 help 广告 `--only fault` 但 L75-101 **无 fault 分支**；`细化_5d` G6（L227）「故障注入六脚本全过」无脚本。
- **修复**：M6 前在 run_all_tests 统一接入：① coverage 实跑 engine/+content/ 行覆盖 ≥80% + 报表归档到 docs/；② ruff/mypy 门（对齐 G4 ①/细化_5d L133）；③ CHANGELOG 存在性 + 每里程碑条目校验；④ 六类故障注入测试（对齐 G3 ①，每用例有断言）。这些是 M6 列「每项可执行有断言」的前提。

---

## P1（5 项）

### P1-1　DELAYED 过期不检测（批2 P2-1 教训），且 verify_m4 已实证失真

- **位置**：`verify_m3.py` L287-312、`verify_m4.py` L383-419、`verify_m5.py` L399-435 的 `t_coverage_self_consistent`——只验①条目数②格式（`pytest:`/`DELAYED` 前缀）③pytest 引用文件落盘+函数名存在；**不验 DELAYED 依赖里程碑是否到期、是否被后续 verify 承接**。
- **实证（静态推导）**：`verify_m4.py` L135「批次7-01 端到端冒烟 … DELAYED：依赖批次7·路H1（test_e2e_m4_smoke.py 并行实现未落盘）」——`tests/unit/test_e2e_m4_smoke.py` **已于 2026-08-26 落盘**（75 行 pytest 固化脚本，包装 scripts/e2e_m4_smoke.py），且已被 verify_m4 L168 列入 PYTEST_FILES（子进程 pytest 会真跑它），但 COVERAGE 条目仍标 DELAYED → **覆盖声明失真：实际已测、声明未翻转**。这正是批2 P2-1 教训「t_coverage_self_consistent 只验格式不验 DELAYED 过期」造成的现实危害。
- **M6 是否需升级**：**必须升级**。M6 是最后一个里程碑，verify_m6 的自洽断言必须全仓扫描 M2-M5 所有 DELAYED 项，校验「标『依赖 M6』的项已转 `pytest:` 承载」或「显式登记残留原因 + 到期日」，否则 M2/M3/M5 的 DELAYED 链在 M6 处无人收口。
- **修复**：在 t_coverage_self_consistent 增加「DELAYED 到期扫描」：解析每个 DELAYED 的「依赖 M<N>」目标，对比现有 verify_m<N>.py 的 COVERAGE 是否承接；verify_m4 的批次7-01 立即翻转回 `pytest:test_e2e_m4_smoke.py::test_smoke_*`。

### P1-2　DELAYED→M6 承接孤儿：M6 verify 列 6 项均不含这些「依赖 M6」项

- **位置**：`verify_m2.py` L51（1e-TC-14 依赖 M3）、L63（1f-TC-11 图鉴分级 依赖 M6）、L64（1f-TC-12 依赖 M6 图鉴+M3）、L71（1f-TC-19 依赖 M3）、L72（1f-TC-20 依赖 M3/M6）；`verify_m3.py` L64（2a1c-TC-22 防嵌套红拦 依赖 M6 loader 校验器未接线）；`verify_m5.py` L78-81（3d TC-16/17 锻造 TPL-10/11 依赖 M6 生活生产批次）、L156-175（4f TC-01~04/06 /注册、TC-07/09/10 /状态、TC-17/22/23 快捷解绑/列表 归属后续批次）。
- **静态推导**：这些项明确标「依赖 M6」，但 M6 verify 列（L3481）6 项 = 热重载/冒烟/故障注入/覆盖率/ruff-mypy-pytest/CHANGELOG，**无一项承接** 图鉴分级（codex_state）、loader 防嵌套红拦、锻造 TPL-10/11、/注册、/状态、/快捷解绑/列表。同时细化_5d 定义的 verify_m6 范围（3e/3e2/5a/5b/5c）也不含这些项 → 这批 DELAYED 成为**永久死缺口**：若照 L3481 实现 verify_m6，M2/M3/M5 的诚实化承诺将全部落空。
- **修复**：G1 §8 M6 行显式增加「承接 M2-M5 DELAYED 项」清单段（或逐项仲裁为「M6 不承接 + 残留登记」），并把 图鉴/防嵌套/锻造/注册/状态/快捷解绑 的验收断言写进 verify_m6.py 范围。

### P1-3　M6 冒烟闭环（注册→锁定→攻击→结算）无落地载体，且依赖未实装的 /注册

- **位置**：M6 列 L3481「冒烟闭环（注册→锁定→攻击→结算）」↔ F6 L3443-3444（冒烟=validator 全绿+模拟一局）；`verify_m5.py` L156-167（4f TC-01~04/06 /注册 **未实装**，DELAYED）；`scripts/_gen_templates_full.py` L91-95（/状态 /快捷绑定等指令未注册）。
- **静态推导**：① /注册 未实装，「注册」步无实现，M6 冒烟闭环不可构建（跨里程碑硬依赖：M5 遗留的 DELAYED 阻塞 M6 的验收项，且 M6 列未把它列为前置）。② 现有冒烟 `scripts/e2e_m4_smoke.py`（NPC→商店→任务→签到→快捷→翻页，非战斗闭环）与 `scripts/e2e_m3_smoke.py`（探索版+BOSS 版，仅 prepare_resume_battle 装配、**不跑完整对局**）**均未接入 run_all_tests**（run_all_tests L44-48 e2e 层只含 `tests/contract/test_e2e_smoke.py`+`test_3f_patch.py`），且都无「注册→锁定→攻击→结算」。③ F6 L3443 自述「battle 接口按 A3 留桩」——M6 列却要求完整闭环，口径需仲裁。
- **修复**：M6 实现 /注册；新增战斗冒烟脚本（复用 verify_m5 已建 BattlePipeline/dispatch_round，跑 注册→锁定→攻击→结算 真实闭环，固定种子可重放，带断言）；把冒烟脚本纳入 run_all_tests 全量回归（G1 模板「冒烟闭环」步的落地载体）。

### P1-4　G1 模板 5 步与 M6 verify 列 6 项不对应

- **位置**：G1 L3452（模板 5 步：pytest 全绿→ruff/mypy→预置内容包 validator 全绿→冒烟闭环→里程碑验收单→结果归档）vs M6 列 L3481（6 项）。
- **静态推导**：逐项对应结果——① pytest 全绿 ↔ M6「ruff/mypy/pytest 全绿」的 pytest 部分 ✓；② ruff/mypy ↔ 同上 ✓（文字）；③ **预置内容包 validator 全绿：M6 列未单列**（仅 verify_m0 §2 对 4 fixtures 执行 validator，verify_m2 只对 legal/badref 两包，M2~M5 未对 content/ 全部预置包执行，M6 列无此独立项）；④ 冒烟闭环 ✓；⑤ **里程碑验收单（对照本规划任务勾选）：M6 列缺失**；⑥ 结果归档 → M6 列窄化为「CHANGELOG 归档」，**缺 G1 L3453②「verify 输出留档于仓库 docs/」**（无归档路径、无机制）。故 M6 列 6 项 ≠ G1 模板 5 步的展开。
- **修复**：M6 列补齐为「热重载回退 / 冒烟闭环 / 故障注入六类 / 覆盖率≥80% / ruff-mypy-pytest / 内容包 validator 全绿 / 里程碑验收单 / CHANGELOG+verify 输出归档」8 项，或让 G1 模板与 M6 列共用同一模板；明确 verify 输出留档目录（docs/ 下具体子目录）。

### P1-5　run_all_tests 与细化_5d §3.2 全量回归流程不符，help 广告未实现的过滤项

- **位置**：`细化_5d` L124（全量回归 = L1~L4 + 7 个 verify_mX + verify_datapack + 故障注入 + 覆盖率核算）、L133（ruff/mypy 快速门）、L139-140（verify_m0→m6 顺序 + 覆盖率报表）vs `run_all_tests.py` L87-102（全量 = unit/contract/e2e pytest + verify_m0~m5 + 覆盖率打印）；L64 help 广告 `--only ... datapack / fault`，L75-101 **无 datapack/fault 分支**（`--only datapack`/`--only fault` 落入 else 全量执行）。
- **静态推导**：官方回归入口（细化_5d L118 声称「唯一官方回归入口」）与细化_5d 自己规定的流程不符：无 verify_datapack（glob `scripts/**/verify_datapack*` 为空）、无故障注入、无 ruff/mypy、无覆盖率实算、无 verify_m6。help 文本与实现分支不一致属文档-代码漂移。
- **修复**：run_all_tests 补齐或显式标注「未接入段」；help 与分支同步（删 datapack/fault 或实现之）。

---

## P2（4 项）

### P2-1　verify_m0 §5「覆盖率硬门禁，未核算不标通过」与 main() 行为矛盾；「M1 恢复硬门禁」承诺未兑现

- **位置**：`verify_m0.py` L149（标题「覆盖率核算（engine/+content/ ≥80% —— 硬门禁，未核算不标通过）」）、L162-167（通过判定仅 `total_f==0 and total_p>=100`，**不含覆盖率**）、L154/L157（「M1 恢复硬门禁」）；`verify_m1.py` 全文无覆盖率段。
- **静态推导**：脚本宣称「未核算不标通过」，但 main() 在不核算覆盖率时仍 `return 0`（通过）。「M1 恢复硬门禁」承诺在 verify_m1 未兑现，且 M2-M5 也未补——覆盖率硬门禁至今（M6 列要求 ≥80%）无任何载体。
- **修复**：删除「硬门禁」表述或把覆盖率纳入 verify_m0 通过判定；在 M6 统一落地（见 P0-3）。

### P2-2　G 编号跨文档混乱

- **位置**：`实现层规划文档.md` §7 L3448-3468（G1-G4 = 验证体系任务：G1 门禁定义/G2 测试体系/G3 故障注入/G4 质量门禁）vs `细化_5d` §6 L222-227（G1-G6 = 里程碑门禁：G1=M0…G6=M5/M6）vs `实现层启动手册.md` L44（G0~G7）。
- **静态推导**：verify 脚本打印的「G 门禁」编号与两套 G 语义均不完全对齐——`verify_m2.py` L316/L318 打「G3 门禁」（细化_5d G3=M2 ✓）；`verify_m3.py` L368/L370 打「G3 门禁」（细化_5d 称 M3=G4，✗ 应为 G4）；`verify_m4.py` L476-478、`verify_m5.py` L662-665 打「G5 门禁」（细化_5d G5=M4 ✓，但 M5 属 G6 ✗）。「G3 门禁」在 verify_m3 语境易与实现层规划 §7 的「G3 故障注入套件」混淆。
- **修复**：verify 输出统一改用「M<N> 门禁」，G 编号保留给各自文档内部语义，避免跨文档歧义。

### P2-3　verify_m2~m5 对「缺失 PYTEST_FILES 黄提示跳过不判失败」与 G1 ③ 语义缝隙

- **位置**：`verify_m2.py` L281-299、`verify_m3.py` L332-350、`verify_m4.py` L443-461、`verify_m5.py` L629-647（缺失文件仅黄提示，`pytest_ok` 只由已存在文件决定）。
- **静态推导**：里程碑可在**声明必测文件缺失**时仍输出「全绿 ✔」并 exit 0。G1 L3453 ③ 只说「任一红拦类回归失败 → 里程碑不通过」，「缺失」不算「失败」故不违反字面——但「每里程碑 verify 清单逐项可勾选」下，缺失文件对应 TC 无承载却通过，与诚实化精神存在缝隙。
- **修复**：M6 起对声明必测文件缺失按失败处理，或纳入 DELAYED 诚实化登记并给到期日（与 P1-1 的到期扫描合并）。

### P2-4　细化_5d §2.1 表 TC 计数与 verify 实际覆盖数陈旧

- **位置**：`细化_5d` L93（M4=176）、L94（M5=620）、L95（M6=114）vs `verify_m4.py` L7-8（83 覆盖点，显式声明不沿用 176）、`verify_m5.py` L5-7（81 覆盖点，不沿用 620）。
- **静态推导**：verify_m4/verify_m5 已主动声明旧计数作废，但细化_5d §2.1 表未同步；M6=114 条（3e/3e2/5a/5b/5c）若继续被引用（run_all_tests L42/启动手册 L42 引 M6 数据），将进一步固化 P0-1 的范围冲突。
- **修复**：细化_5d §2.1 表更新为实际口径或标注「历史口径，以 verify_mX COVERAGE 为准」。

---

## 缺漏点名：「应覆盖 X 但现有 verify 无 X」清单

| # | 应覆盖 X（出处） | 现有 verify 现状 |
|---|---|---|
| 1 | **覆盖率核算**（engine/+content/ ≥80%，实算+报表归档）（G4 ⑥/M6 列 L3481/细化_5d TC-5d-15） | verify_m0 仅打印、verify_m1~m5 无、run_all_tests 阶段3 仅打印 |
| 2 | **ruff/mypy 门禁**（G4 ①/M6 列/细化_5d L133） | 全仓无执行点、无配置 |
| 3 | **CHANGELOG 归档**（G1 L3452/M6 列） | 仓库无 CHANGELOG 文件、无校验 |
| 4 | **故障注入六类**（G3 ①/M6 列/细化_5d G6） | 无测试、`--only fault` 无分支 |
| 5 | **热重载失败回退不崩**（F5 ①/M6 列首项） | 无 hot_reload 测试、无 verify |
| 6 | **冒烟闭环（注册→锁定→攻击→结算）**（F6 ②/M6 列） | 无战斗冒烟脚本；/注册 未实装；e2e_m3/m4_smoke 未接入 run_all_tests |
| 7 | **verify_m6.py 本体**（细化_5d §2.1/run_all_tests L42） | run_all_tests m6=None；无脚本 |
| 8 | **M6 承接 M2-M5 DELAYED**（图鉴分级 1f-TC-11/12、防嵌套红拦 2a1c-TC-22、锻造 TPL-10/11 3d TC-16/17、/注册 4f TC-01~04/06、/状态 4f TC-07/09/10、快捷解绑/列表 4f TC-17/22/23） | M6 列 6 项均不含（P1-2） |
| 9 | **预置内容包 validator 全绿**（G1 模板第 3 步） | 仅 verify_m0 §2 对 4 fixtures；M2~M5 未对 content/ 全部预置包执行；M6 列未单列 |
| 10 | **里程碑验收单**（对照本规划任务勾选）（G1 L3452） | 无 verify 输出验收单；M6 列未含 |
| 11 | **verify 输出留档于仓库 docs/**（G1 L3453②） | 无归档机制/路径 |
| 12 | **run_all_tests datapack/fault 过滤**（help L64 广告） | 无实现分支 |

---

## 幻觉专项结论（③）

- **无直接编造**：未发现 verify_m0~5 声称「已跑 ruff/mypy/覆盖率/CHANGELOG/故障注入」；verify_m0 §5 反而显式声明「本脚本暂不执行」「显式登记为简版」——诚实方向正确。
- **悬挂/误导声明 ×3**（建议按 P2/P1 处理）：
  1. `run_all_tests.py` L102「[阶段 3] 覆盖率核算（engine/+content/ ≥80%）：见 verify_m0 §5 估算口径」——把**未实现**表述得像「已接核算口径」，读者易误判覆盖率已核算（P1 级误导）。
  2. `verify_m0.py` L149「硬门禁，未核算不标通过」与实际 exit 0 行为矛盾（P2-1）。
  3. `verify_m0.py` L154/L157「M1 恢复硬门禁」承诺未兑现（P2-1）。
- **过期声明失真 ×1**：`verify_m4.py` L135「批次7-01 DELAYED（H1 未落盘）」——`tests/unit/test_e2e_m4_smoke.py` 已落盘且已入 PYTEST_FILES，声明未翻转（P1-1 实证）。

---

## 修复优先级建议

1. **立即**（P0）：仲裁 M6 唯一范围 → 实现/接线 run_all_tests 的 coverage/ruff-mypy/CHANGELOG/故障注入/verify_m6 → `--only m6` 与全量回归对未实现 M6 显式失败。
2. **M6 verify 落地前**（P1）：t_coverage_self_consistent 增加 DELAYED 到期扫描并翻转 verify_m4 批次7-01；M6 行补「承接 M2-M5 DELAYED 清单」；实现 /注册 + 战斗冒烟闭环并接入 run_all_tests；M6 列补齐 G1 模板 8 项。
3. **文档同步**（P2）：细化_5d §2.1 计数与 G 编号、run_all_tests help 与分支、verify_m0 覆盖率表述。

*注：所有「运行/行为」结论均为静态推导（读码推演），未执行任何命令。*
