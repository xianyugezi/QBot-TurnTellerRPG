# 细化_M6_verify门禁与承接（M6 子细化文档 D8 · 收官聚合文档 · verify_m6 两段式门禁契约 · run_all_tests 接入 m6 · 四源同步 · DELAYED 到期扫描收口 · 验收单 8 项 · G 编号统一 · verify 归档契约）

> 版本：v1.0 · 类型：实现层细化文档（M6 子细化文档集 **D8** · 批8 交付 · 收官聚合文档：把 D1~D7 的 TC/载体聚合为 verify_m6 两段式门禁的断言对象，并落地 run_all_tests 接入 m6 / 四源同步 / DELAYED 到期扫描 / 验收单 8 项 / G 编号统一 / verify 归档契约）
> 追溯依据（**严格引用权威源，引用到行号 Lxx / 文件名 / 审查报告编号，附原文摘录**）：
> - 《细化_M6_接线闭环总纲.md》→ 简称【总纲】——§二 VM6-1 L60-68（段一 8 项验收单，逐项落点子文档）/ VM6-2 L70（段二承接 M2-M5 DELAYED 六组清单）/ VM6-3 L72（不假绿铁律）/ VM6-4 L74（DELAYED 到期扫描 + verify_m4 批次7-01 立即翻转）；§一 SCP-4 L56（验收单 8 项 = 热重载回退/冒烟闭环/故障注入六类/覆盖率≥80%/ruff-mypy-pytest/内容包 validator 全绿/里程碑验收单/CHANGELOG+verify 归档）；§三 3.1 注册表 L89（D8 行：run_all_tests 接入 m6 + 验收单 8 项 + 四源同步 + DELAYED 收口 + G 编号统一）；§四 4.2 映射表 L119-120（批3组A P0-1/P1-4/P1-5/P1-6 → D8；批3组B P0-1/P0-2/P1-1/P1-2/P1-4/P1-5 → D8）；§五 SYN-1 L130（四源同步，由 D8 执行）；§六 BCH-3 L150 / BCH-4 L151（批 1~7 全部完成才进批 8；M6 完结判据 = verify_m6 段一+段二全绿 + run_all_tests 全量 exit 0 含 m6 + CHANGELOG 建档 M6 条目）；§七 ADR-07 L163（verify 输出统一「M<N> 门禁」，G 编号保留各文档内部语义）/ ADR-08 L164（缺失 PYTEST_FILES 必测文件按失败处理或 DELAYED 诚实化登记含到期日，禁止「缺失仍全绿」）/ ADR-09 L165（验收单 8 项为 M6 唯一验收口径，产物 docs/verify/m6_checklist.md）/ ADR-10 L166（归档统一 docs/verify/，写入者 = verify_m6.py；M0-M5 归档欠账 CHANGELOG 建档时统一回填说明）；DOC-3 L97（D8 用 VG/ACC/DLY 前缀）；附录 A L191（内容包 validator 全绿 = 动态扫描 content/ 全部预置包）/ L193（验收单粒度到子文档）
> - 《审查_M6设计_批3_组A_g1门禁_jspace.md》→ 简称【批3A】——P0-1 L24-34（G1 统一 verify 清单模板 7 项中 4 项无可执行无断言载体，硬规则自反失效）；P1-4 L61-64（里程碑验收单内容/粒度/产物未定义，与 COVERAGE 两层关系未仲裁）；P1-5 L66-69（verify 结果归档路径/命名/写入者未定义，docs/ 与《开发记录》两目标冲突）；P1-6 L71-74（verify_m6 构成四源冲突 + `--only m6` 返回 0 假绿陷阱）；P2-1 L80 / P2-2 L83 / P2-3 L86 / P2-4 L89 / P2-5 L92 / P2-6 L95（P2 全量）
> - 《审查_M6设计_批3_组B_g1跨里程碑_jspace.md》→ 简称【批3B】——P0-1 L22-26（M6 里程碑范围三处定义冲突，verify_m6.py 内容无唯一权威）；P0-2 L28-32（run_all_tests 对未实现 M6 返回假绿：`--only m6` exit 0 / 全量静默跳过不置 fail）；P1-1 L46-51（DELAYED 过期不检测 + verify_m4 批次7-01 实证失真）；P1-2 L53-57（DELAYED→M6 承接孤儿，M6 verify 列 6 项均不承接 → 永久死缺口）；P1-4 L65-69（G1 模板 5 步 vs M6 verify 列 6 项不对应）；P1-5 L71-75（run_all_tests 与细化_5d §3.2 流程不符 + help 广告未实现过滤）；P2-1 L81-85 / P2-2 L87-91 / P2-3 L93-97 / P2-4 L99-103（P2 全量）
> - 《审查_M6设计_批2_组B_f6断言_jspace.md》→ 简称【批2B】——P2-1 L153-158（verify_m4「批次7-01 端到端冒烟」DELAYED 声明过期——tests/unit/test_e2e_m4_smoke.py 已落盘且已入 PYTEST_FILES，本档翻转）
> - 现有实现（**契约必须建立在真实实现上，先读代码再落笔**）：`scripts/run_all_tests.py`（L42 `"m6": None,  # M6 数据框架（5a/5b/4c/4d/4e/6 系）` / L64 help 广告 datapack/fault / L65 `--fast` 定义后全程未引用 / L75-79 `--only m6` 时 script is None → return 0 假绿 / L95-97 全量 m6=None → continue 跳过 / L102 覆盖率仅打印「见 verify_m0 §5 估算口径」）；`scripts/verify/verify_m0.py~m5.py`（各自 COVERAGE 结构 + t_coverage_self_consistent：verify_m3 L287-312 / verify_m4 L383-419 / verify_m5 L399-435 只验条目数/格式/文件存在，不验 DELAYED 过期；verify_m4 L476/L478 打「G5/M4 门禁」混用、verify_m5 L662/L664 打「G5/M5 门禁」混用）；`scripts/verify/verify_m4.py` L135（批次7-01 DELAYED「test_e2e_m4_smoke.py 并行实现未落盘」——实际 tests/unit/test_e2e_m4_smoke.py 已落盘且已入 PYTEST_FILES L168，声明失真）；`docs/实现层启动手册.md` L42（M6 数据框架 5a/5b/4c/4d/4e/6 系）；`docs/实现层规划文档.md` L3481（M6 接线闭环行——核对已为新口径）；`docs/细化/细化_5d_测试体系总纲.md`（§2.1 L95 M6 数据 114 TC / §3.2 L118-146 / §7.4 决策记录 L295-302 D1-D4 / TC-5d-07 L259 / TC-5d-08 L260 / TC-5d-15 L267 / TC-5d-17 L274 / TC-5d-31 L288）
> - 兄弟文档（**只引用不重定义**，各档头部「文档总览」计数即 verify_m6 断言对象）：D1 细化_M6_三引擎与基础指令（51 规则/29 用例：TC-LVL/INV/EQP/REG/STT/SHC）；D2 细化_M6_幂等事务三件套（23/15：TC-IDEM/SEG/POOL）；D3 细化_M6_热重载接线（31/21：TC-WIR/RSM）；D4 细化_M6_内容包冒烟（29/21：TC-SMK/PCK）；D5 细化_M6_故障注入（46/26：TC-FLT/SES）；D6 细化_M6_测试体系强化（40/30：TC-PRP/SED/FIX/RTN/IGR）；D7 细化_M6_质量门禁（38/30：TC-COV/LNT/CHG/CI/RVW）
> - 母契约（承接引用不重定义）：《细化_5d_测试体系总纲.md》→ 简称【5d】（§3.2 执行顺序 L130-146：L133 ruff/mypy 快速门 / L139-140 verify_m0→m6 顺序执行严格按里程碑依赖序 + 覆盖率报表 / L124 全量回归 = L1~L4 + 7 个 verify + verify_datapack + 故障注入 + 覆盖率核算；§6.1 门禁定义 L219-228 G0-G7；§7.4 决策记录 L295-302 D1-D4）；《开发规则文档.md》→ 简称【规则】（§6.3 发布检查单 L418-435：L422 pytest 全绿+覆盖率达标+内容包冒烟 / L423 ruff/mypy / L424 CHANGELOG / L426 预置内容包全过 validator；L435 服务器冒烟「/注册 /锁定 /攻击 一轮闭环」）
> 范围：本档只定 **verify_m6 两段式门禁契约 + run_all_tests 接入 m6 + 四源同步 + DELAYED 到期扫描收口 + 验收单 8 项 + G 编号统一 + verify 归档契约** 七件事的**可执行契约**——verify_m6 如何聚合 D1~D7 的 TC/载体做断言（段一 8 项）、如何承接 M2-M5 DELAYED（段二 6 组）、run_all_tests 如何接入 m6 且不假绿、四源如何统一为「接线闭环」、验收单与归档的产物/粒度/写入者。
> 不覆盖：verify_m6 各断言对象的载体**本体**——热重载接线载体归 D3（WIR/RSM）、冒烟脚本与五档包归 D4（SMK/PCK）、故障注入六脚本与 `--only fault` 分支归 D5（FLT/SES）、覆盖率实算工具与 ruff/mypy/CHANGELOG 建档/CI 归 D7（COV/LNT/CHG/CI/RVW）、三引擎实装与 /注册 /状态 /快捷 承接归 D1（LVL/INV/EQP/REG/STT/SHC）、幂等三件套载体归 D2（IDEM/SEG/POOL）、性质用例/seed/往返归 D6（PRP/SED/FIX/RTN/IGR）；M6 批 1~7 的实现批次见各子文档与【总纲】§六。
> 承接协议：跨档引用统一 [总纲·VM6-1]/[D7·COV-01]/[5d·§2.1]/[批3A·P0-1]/[D3·TC-WIR-01] 格式（【总纲】DOC-1），带档名前缀防张冠李戴（【总纲】DOC-3）；母契约/兄弟文档已定义者只引用不重写。
> 变更纪律：任何偏离【总纲】ADR 之处必须写入 §九 决策记录并注明理由+影响文档，禁止静默改语义；P 项未在本档落地者视为孤儿项（【总纲】TC-M6-12 暴露）；定稿/契约未定义处显式标注【工程补白】/【细化定型】，不得冒充行号。

---

## 文档总览（计数）

| 维度 | 计数 | 分布 |
|---|---|---|
| 规则 | **34 条** | VG×21（两段式契约 11 + run_all_tests 接入 4 + 四源同步 4 + G 编号统一 2）+ DLY×10（段二承接 6 + 到期扫描 4）+ ACC×3（验收单/归档），全部为表格行首编号，自检脚本可实算 |
| 字段 | **0 项** | 本档为门禁/承接契约，无数据 schema 字段（对齐 D7 口径）；承载载体字段归各兄弟文档 |
| 验收用例 | **21 例** | TC-VG×16 + TC-DLY×3 + TC-ACC×2，逐条带依据引用 |
| 承接 P 项 | **21 项** | 批3组A 10 项（P0-1/P1-4/P1-5/P1-6 + P2-1~P2-6）+ 批3组B 10 项（P0-1/P0-2/P1-1/P1-2/P1-4/P1-5 + P2-1~P2-4）+ 批2组B 1 项（P2-1）——§七 逐条显式承接，转归 D7/D6/D5/D1/D4 的注明 |
| 断言对象聚合 | **172 例** | D1 29 + D2 15 + D3 21 + D4 21 + D5 26 + D6 30 + D7 30 = 172 例 TC（各档头部「文档总览」计数），即 verify_m6 段一断言对象的 TC 计数总和 |

---

## 〇、术语与定位

| 术语 | 定义 | 依据 |
|---|---|---|
| 两段式 verify_m6 | verify_m6 = 段一 接线闭环门禁（SCP-4 八项验收单可执行断言）+ 段二 承接 M2-M5 DELAYED 项 | 【总纲】§二；VM6-1/VM6-2 |
| 段一 8 项 | 热重载回退 / 冒烟闭环 / 故障注入六类 / 覆盖率≥80% / ruff-mypy-pytest / 内容包 validator 全绿 / 里程碑验收单 / CHANGELOG+verify 归档 | 【总纲】SCP-4；ADR-09 |
| 不假绿 | 未实现的门禁显式失败，禁止「未实现 = 通过」：`--only m6` 未实现 exit≠0；全量遇 m6=None 置 fail | 【总纲】VM6-3；【批3A】P1-6；【批3B】P0-2 |
| DELAYED 到期扫描 | t_coverage_self_consistent 升级：解析每个 DELAYED 的「依赖 M<N>」，对比 verify_m<N>.py COVERAGE 是否承接；过期未翻转即失败 | 【总纲】VM6-4；【批3B】P1-1 |
| 残留登记 | DELAYED 项无法在 M6 内转 pytest 承载时的诚实登记，含原因 + 到期日，杜绝永久死缺口 | 【总纲】VM6-2；ADR-08 |
| 四源同步 | 【规划】L3481 / 细化_5d L95 / run_all_tests L42 注释 / 启动手册 L42 四处统一「接线闭环」口径 | 【总纲】SYN-1；SCP-1 |
| 验收单 | 对照【规划】任务 T 编号逐项勾选的里程碑验收产物，粒度到子文档（不进每条 TC），产物 docs/verify/m6_checklist.md | 【总纲】ADR-09；附录 A L193；【批3A】P1-4 |
| 归档 | verify 输出（报表/冒烟留档/验收单）统一写入 docs/verify/，写入者 = verify_m6.py | 【总纲】ADR-10 |

---

## 一、verify_m6 两段式契约（VG-01 ~ VG-11）

### 1.1 段一 8 项验收单（唯一验收口径）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-01 | 段一·8 项唯一验收口径 | verify_m6 段一 = 【总纲】SCP-4 八项里程碑验收单的可执行断言（不是「人工看了没问题」的勾选清单），八项逐项有断言对象 + 落点脚本段；验收单 8 项为 M6 里程碑唯一验收口径，粒度到子文档 | 【总纲】VM6-1/ADR-09；【批3A】P0-1/P1-4 |
| VG-02 | 段一①·热重载接线回退 | 断言对象 = D3 WIR/RSM 全部 TC（watcher 启动装载 + 调度驱动 + /重载 真实后端 + ReloadResult 人话翻译 + P0-1 续战世代绑定重绑定 + F5 验收③快照冗余断言）；落点 = verify_m6 段一① 脚本段（引用 D3 载体） | 【总纲】VM6-1 项1；【批1B】P0-1 |
| VG-03 | 段一②·冒烟闭环 | 断言对象 = D4 SMK/PCK 全部 TC（真实 BattleEngine 模拟一局「注册门槛→锁定→攻击→结算」逐步断言 + 四件套 validator 矩阵 + 五档包 validator 全绿）；落点 = verify_m6 段一② 子进程段（e2e_m6_smoke + 四件套/五档包） | 【总纲】VM6-1 项2；【批2B】P0-1 |
| VG-04 | 段一③·故障注入六类 | 断言对象 = D5 FLT/SES 全部 TC（tests/fault/ 六脚本全过 + `--only fault` 分支 + SessionManager 实装 + 暂存补写）；落点 = verify_m6 段一③ 脚本段 + `--only fault` 分支 | 【总纲】VM6-1 项3；【批5A】P1-3 |
| VG-05 | 段一④·覆盖率 ≥80% | 断言对象 = D7 COV 全部 TC（qbot_rpg/core + engine + content 各自 ≥80% 行覆盖实算 + 阈值断言 + 报表归档 docs/verify/）；落点 = verify_m6 段一④ 覆盖率段 | 【总纲】VM6-1 项4/ADR-04；【批3A】P1-2；【批6A】P0-2 |
| VG-06 | 段一⑤·ruff/mypy/pytest 全绿 | 断言对象 = D7 LNT 全部 TC（pyproject [tool.ruff]/[tool.mypy] 快速门 + 基线豁免清单）；落点 = verify_m6 段一⑤ 前置段（run_all_tests 阶段0 ruff/mypy 快速门，失败 exit≠0） | 【总纲】VM6-1 项5；【批3A】P1-1；【5d】L133 |
| VG-07 | 段一⑥·内容包 validator 全绿 | 断言对象 = D4 SMK validator 矩阵（红拦真拦截/黄提示可过）+ 动态扫描 content/ 全部预置包（含五档包逐档）+ 子进程 PYTEST_FILES 红拦回归载体（test_content.py / test_enemies_schema.py 等）；落点 = verify_m6 段一⑥ 子进程段 | 【总纲】VM6-1 项6/附录 A L191；【批2B】P1-7 |
| VG-08 | 段一⑦·里程碑验收单 | 断言对象 = 本档 ACC-01 定义的 docs/verify/m6_checklist.md（对照【规划】任务 T 编号逐项勾选 + 各子文档 TC 计数列 + 勾选时间/结论）；落点 = verify_m6 段一⑦ 产物检查段 | 【总纲】VM6-1 项7/ADR-09；【批3A】P1-4 |
| VG-09 | 段一⑧·CHANGELOG + verify 输出归档 | 断言对象 = D7 CHG 全部 TC（CHANGELOG.md 建档回填 + Keep a Changelog 格式）+ 本档 ACC-02（docs/verify/ 归档物齐全）；落点 = verify_m6 段一⑧ 检查段 | 【总纲】VM6-1 项8/ADR-10；【批3A】P0-2/P1-5 |

**段一 断言对象表**（每项 = 断言对象 + 落点脚本段 + 引用 D1~D7 对应 TC/规则）：

| 项 | 断言对象（载体） | 落点脚本段（verify_m6） | 引用 TC/规则 |
|---|---|---|---|
| ① 热重载回退 | D3 WIR/RSM TC + F5 验收③快照冗余断言 | 段一① 脚本段（热重载接线载体） | [D3·TC-WIR-01~14]/[D3·TC-RSM-01~07] |
| ② 冒烟闭环 | D4 SMK/PCK TC + e2e_m6_smoke + 四件套矩阵 | 段一② 子进程段（e2e/validator） | [D4·TC-SMK-01~15]/[D4·TC-PCK-01~06] |
| ③ 故障注入六类 | D5 FLT/SES TC + tests/fault/ 六脚本 | 段一③ 脚本段 + `--only fault` 分支 | [D5·TC-FLT-01~21]/[D5·TC-SES-01~05] |
| ④ 覆盖率 ≥80% | D7 COV 阈值（core/engine/content 各自） | 段一④ 覆盖率段 + 报表落盘 | [D7·TC-COV-01~08] |
| ⑤ ruff/mypy/pytest | D7 LNT + pyproject 快速门 | 段一⑤ 前置段（阶段0） | [D7·TC-LNT-01~05] |
| ⑥ 内容包 validator 全绿 | D4 SMK validator 矩阵 + content/ 动态扫描 | 段一⑥ 子进程段（PYTEST_FILES） | [D4·SMK validator 矩阵]/[D4·TC-PCK-01~06] |
| ⑦ 里程碑验收单 | 本档 ACC-01（m6_checklist.md） | 段一⑦ 产物检查段 | [本档·ACC-01]/[总纲·ADR-09] |
| ⑧ CHANGELOG + 归档 | D7 CHG + 本档 ACC-02（docs/verify/） | 段一⑧ 检查段 | [D7·TC-CHG-01~04]/[本档·ACC-02] |

### 1.2 段二承接 M2-M5 DELAYED（六组清单）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-10 | 段二·承接 M2-M5 DELAYED | verify_m6 段二 = 【总纲】VM6-2 六组承接清单（图鉴分级/防嵌套红拦/锻造 TPL-10/11//注册//状态//快捷解绑与列表），每组按 DLY-01~06 裁决为「转 pytest: 承载」或「显式残留登记（原因 + 到期日）」，杜绝永久死缺口 | 【总纲】VM6-2；【批3B】P1-2 |

**段二承接裁决表**（裁决本体见 §三 DLY-01~06）：

| 组 | 承接的 DELAYED 项 | 裁决 | 落点 |
|---|---|---|---|
| 图鉴分级 | 1f-TC-11 / 1f-TC-12（verify_m2 L63-64） | 显式残留登记（依赖图鉴 codex_state，归 M11） | DLY-01 |
| 防嵌套红拦 | 2a1c-TC-22（verify_m3 L64） | 转 pytest: 承载（M6 校验器防嵌套规则接线后红拦断言） | DLY-02 |
| 锻造 TPL-10/11 | 3d TC-16 / 3d TC-17（verify_m5 L78-81） | 显式残留登记（锻造系统实装不在 M6 接线闭环范围） | DLY-03 |
| /注册 | 4f TC-01~04 / 4f TC-06（verify_m5 L156-167） | 转 pytest: 承载（D1 TC-REG-01~05） | DLY-04 |
| /状态 | 4f TC-07 / 4f TC-09 / 4f TC-10（verify_m5 L168-175） | 转 pytest: 承载（D1 TC-STT-01~03） | DLY-05 |
| 快捷解绑/列表 | 4f TC-17 / 4f TC-22 / 4f TC-23（verify_m5 L188-200） | 转 pytest: 承载（D1 TC-SHC-01~03） | DLY-06 |

### 1.3 不假绿铁律

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-11 | 不假绿铁律 | run_all_tests 对未实现门禁显式失败——`--only m6` 在 script is None 时 return 1（未实现即不通过）并提示「M6 未接入 → 门禁不完整」；全量回归遇 m6=None 置 fail 并打印「M6 未接入 → 门禁不完整」，退出码非 0。禁止 `--only m6` 未实现仍返回 0（现状 run_all_tests L77-79 假绿，本档废弃该行为） | 【总纲】VM6-3；【批3A】P1-6；【批3B】P0-2 |

---

## 二、run_all_tests 接入 m6（VG-12 ~ VG-15）

### 2.1 MILESTONES 置位与全量顺序

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-12 | MILESTONES["m6"] 置位 | run_all_tests.py MILESTONES["m6"] 由 None 置为 `scripts/verify/verify_m6.py`（VERIFY_M6 常量），注释同步改为「M6 接线闭环（verify_m6 两段式）」（现状 L42 注释「M6 数据框架（5a/5b/4c/4d/4e/6 系）」废弃，见 §四） | 【总纲】SYN-1；【批3B】P0-1 |
| VG-13 | 全量阶段顺序 m0→m6 严格依赖序 | run_all_tests 全量回归阶段2 按 m0 → m1 → m2 → m3 → m4 → m5 → m6 顺序执行，严格按里程碑依赖序（不可乱序、不可跳过） | 【5d】§3.2 L139-140；【批3B】P1-5 |

### 2.2 分支与 help 同步

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-14 | `--only m6` 分支 + help 与分支同步 + `--fast` 真正使用 | `--only m6` 走 MILESTONES 分支执行 verify_m6；help 文本（L64）与实现分支同步——已实现的分支如实列出，未实现的 `--only datapack`/`--only fault` 若 D5/D7 未落地则移出 help 或标注「待 D5/D7 接入」（现状 L64 广告 datapack/fault 但 L75-86 无分支，属文档-代码漂移）；`--fast` 参数（L65）真正进入分支逻辑（冒烟模式：跳过性质用例全量抽样/覆盖率抽样核算，对齐【5d】§3.1 L125），不再定义后全程未引用 | 【批3A】P2-6；【批2B】P2-2；【批3B】P1-5 |
| VG-15 | run_all_tests 与细化_5d §3.2 全量回归流程对齐 | run_all_tests 全量流程（现状 L88-102 仅 pytest 层 + verify_m0~m5 + 覆盖率打印）与【5d】§3.2 L130-146 对齐——L1~L4（unit/contract/e2e）→ ruff/mypy 快速门（L133）→ 故障注入（L137）→ verify_datapack（L138，若 D7 接入）→ verify_m0~m6 严格依赖序（L139）→ 覆盖率核算（L140）→ 汇总（L141）；任一失败按短路原则收集全部失败但退出码非 0（L144）。verify_m6 段一④⑤ 即消费本段覆盖率/ruff/mypy 结果 | 【5d】§3.2 L118-146；【批3A】P1-1/P1-3；【批3B】P1-5 |

---

## 三、DELAYED 到期扫描收口（DLY-01 ~ DLY-10）

### 3.1 段二承接裁决（六组）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| DLY-01 | 图鉴分级 · 显式残留登记 | 1f-TC-11（图鉴分级：L2 招名不显示/L3 不显示需图鉴接线）与 1f-TC-12（中断恢复预演消息渲染）显式残留登记——原因：依赖图鉴 codex_state 系统，归 M11 横切系统（【总纲】SCP-2「4d 图鉴 → M11」），非 M6 接线闭环范围；到期日 = 图鉴系统里程碑（M11）。1f-TC-12 的机制部分（ai_state 全字段快照往返）已由 test_monster_ai_battle.py::test_ai_state_snapshot_roundtrip 承载 | 【总纲】VM6-2/SCP-2；【批3B】P1-2 |
| DLY-02 | 防嵌套红拦 · 转 pytest: 承载 | 2a1c-TC-22（副本内部地图配 dungeon_entrances 红拦）转 pytest: 承载——M6 由 D3 热重载接线把 loader 校验器防嵌套/递归规则接入后，断言 dungeon_entrances 红拦真拦截（红拦 = 加载失败 + PackLoadError + registry 未被污染）；落点 = verify_m6 段一⑥ PYTEST_FILES（test_maps_schema / test_content 等） | 【总纲】VM6-2；【批3B】P1-2；【3e】F4 |
| DLY-03 | 锻造 TPL-10/11 · 显式残留登记 | 3d TC-16（锻造成功 TPL-10）与 3d TC-17（锻造失败 TPL-11）显式残留登记——原因：锻造系统实装不在 M6 接线闭环范围（verify_m5 L78-81 自述「M6 生活生产批次」实为无承接批次，M6 范围仲裁后确认非本批）；到期日 = 生活生产内容包实现批次。✅/❌ 功能性标记口径已由 3d TC-18 emoji 纪律承载，不构成缺口 | 【总纲】VM6-2；【批3B】P1-2 |
| DLY-04 | /注册 · 转 pytest: 承载 | 4f TC-01~04/06（首次注册/缺省职业/重名/幂等/名字长度）转 pytest: 承载——D1 批1 实装 /注册 真实后端（REG-01~06 规则 + TC-REG-01~05），verify_m5 原 DELAYED 声明（L156-167）转 pytest: 引用 D1 载体 | 【总纲】VM6-2；【D1】TC-REG-01~05 |
| DLY-05 | /状态 · 转 pytest: 承载 | 4f TC-07/09/10（战斗外总览/效果区/战斗内目标行）转 pytest: 承载——D1 实装 /状态 面板（STT-01~05 规则 + TC-STT-01~03），verify_m5 原 DELAYED 声明（L168-175）转 pytest: | 【总纲】VM6-2；【D1】TC-STT-01~03 |
| DLY-06 | 快捷解绑/列表 · 转 pytest: 承载 | 4f TC-17（帮助别名）/TC-22（覆盖重绑/解绑边界）/TC-23（快捷列表与持久化）转 pytest: 承载——D1 实装 /快捷 解绑/列表（SHC-01~05 规则 + TC-SHC-01~03），verify_m5 原 DELAYED 声明（L188-200）转 pytest: | 【总纲】VM6-2；【D1】TC-SHC-01~03 |

### 3.2 到期扫描机制（t_coverage_self_consistent 升级）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| DLY-07 | t_coverage_self_consistent 升级为到期扫描 | verify_m6 内置全仓 DELAYED 到期扫描——解析 verify_m2/m3/m4/m5.py 每个 DELAYED 项的「依赖 M<N>」目标，对比 verify_m<N>.py 的 COVERAGE 是否已承接该 TC；「依赖 M<N>」且 N ≤ M6 的目标若未转 pytest: 承载且未显式残留登记（含到期日），即过期未翻转 → verify_m6 断言失败。升级点 = 现有 verify_m3 L287-312 / verify_m4 L383-419 / verify_m5 L399-435 只验条目数/格式/文件存在、不验 DELAYED 过期 | 【总纲】VM6-4；【批3B】P1-1；【批2B】P2-1 |
| DLY-08 | verify_m4 批次7-01 立即翻转 | verify_m4.py L135 批次7-01「DELAYED：依赖批次7·路H1（test_e2e_m4_smoke.py 并行实现未落盘）」立即翻转——tests/unit/test_e2e_m4_smoke.py 已落盘（75 行 pytest 固化，包装 scripts/e2e_m4_smoke.py）且已入 PYTEST_FILES L168，声明失真（实际已测、声明未翻转）；翻转承载 = `pytest:test_e2e_m4_smoke.py::test_smoke_subprocess_exit0_and_green_line + test_e2e_m4_smoke.py::test_run_smoke_green_and_deterministic + test_e2e_m4_smoke.py::test_path_assertion_counts + test_e2e_m4_smoke.py::test_smoke_core_run_green` | 【总纲】VM6-4；【批3B】P1-1；【批2B】P2-1 |
| DLY-09 | 缺失 PYTEST_FILES 必测文件按失败处理 | M6 起对 verify_m6 声明必测的 PYTEST_FILES 缺失文件**按失败处理**（fail，不黄提示跳过）——除非该项已纳入 DELAYED 诚实化登记（含到期日）；禁止「缺失仍全绿」（现状 verify_m2~m5 L281-299/332-350/443-461/629-647 缺失文件仅黄提示，与 G1「pytest 全绿含本里程碑新增用例」语义有缝隙） | 【总纲】ADR-08；【批3B】P2-3；【批3A】P2-3 |
| DLY-10 | M2/M3/M5 全量 DELAYED 收口对账 | verify_m6 段二实施时按下表逐项对账——现状（DELAYED 原文）→ 裁决（转 pytest: 承载 / 显式残留登记）；表内裁决为本档【细化定型】（M6 范围决策，实现时以 verify_m6 到期扫描实测复核） | 【总纲】VM6-4；【批3B】P1-1/P1-2 |

### 3.3 M2/M3/M5 DELAYED 收口对账表

| 源 | 项（依赖目标） | 现状（DELAYED 原文位置） | 裁决 |
|---|---|---|---|
| verify_m2 | 1e-TC-14 换区/开场技运行期（依赖 M3） | L51 | 转 pytest: 承载（verify_m3 2a2-TC-17 开场技 + 换区 2a2 TC-01~09 已覆盖；M6 战斗接线后补运行期断言）【细化定型】 |
| verify_m2 | 1f-TC-11 图鉴分级（依赖 M6） | L63 | 显式残留登记（依赖图鉴 codex_state，归 M11；到期日 = 图鉴系统里程碑）→ DLY-01 |
| verify_m2 | 1f-TC-12 中断恢复（依赖 M6+M3） | L64 | 显式残留登记（预演消息渲染依赖图鉴；机制部分已由快照往返承载；到期日 = 图鉴系统里程碑）→ DLY-01 |
| verify_m2 | 1f-TC-19 换区流程（依赖 M3） | L71 | 转 pytest: 承载（verify_m3 2a2 TC-01~24 换区/追击/续战全流程已覆盖） |
| verify_m2 | 1f-TC-20 验收判据（依赖 M3/M6） | L72 | 转 pytest: 承载（2a3 BOSS 战完整节奏由 verify_m3 覆盖）+ 图鉴/换区主观判据残留登记（到期日 = 图鉴系统里程碑） |
| verify_m3 | 2a1c-TC-06 紧凑「进入上」（依赖 M4） | L48 | 转 pytest: 承载（verify_m4 2.1-01 分隔符五类/紧凑双认已覆盖） |
| verify_m3 | 2a1c-TC-07 /进入 幂等（依赖 M4） | L49 | 转 pytest: 承载（verify_m4 2.1-02 紧凑/空格等价已覆盖） |
| verify_m3 | 2a1c-TC-22 防嵌套红拦（依赖 M6） | L64 | 转 pytest: 承载（M6 校验器接线后红拦断言）→ DLY-02 |
| verify_m3 | 2a2-TC-10 PV>0 debuff 减半（依赖 M4） | L78 | 转 pytest: 承载（M6 战斗接线读换区 PV 门禁后断言）【细化定型】 |
| verify_m3 | 2a2-TC-14 /进入up 无空格（依赖 M4） | L82 | 转 pytest: 承载（verify_m4 2.1-02 紧凑双认已覆盖） |
| verify_m3 | 2a3-TC-2a3-03 双副本并发（依赖 M4 会话容器） | L96 | 转 pytest: 承载（M6 会话容器接线后双副本并发断言，落 verify_m6 段一）【细化定型】 |
| verify_m4 | 批次7-01 端到端冒烟（依赖批次7·路H1） | L135 | 立即翻转 pytest:test_e2e_m4_smoke.py::test_smoke_* → DLY-08 |
| verify_m5 | 3d TC-16 锻造成功 TPL-10（依赖 M6） | L78 | 显式残留登记（锻造系统不在 M6 范围；到期日 = 生活生产内容包批次）→ DLY-03 |
| verify_m5 | 3d TC-17 锻造失败 TPL-11（依赖 M6） | L81 | 显式残留登记（同上）→ DLY-03 |
| verify_m5 | 4f TC-01~04/06 /注册（依赖 M6） | L156-167 | 转 pytest: 承载（D1 TC-REG-01~05）→ DLY-04 |
| verify_m5 | 4f TC-07/09/10 /状态（依赖 M6） | L168-175 | 转 pytest: 承载（D1 TC-STT-01~03）→ DLY-05 |
| verify_m5 | 4f TC-17 帮助别名（依赖 M6） | L188 | 转 pytest: 承载（D1 TC-SHC-03）→ DLY-06 |
| verify_m5 | 4f TC-22 覆盖重绑/解绑（依赖 M6） | L198 | 转 pytest: 承载（D1 TC-SHC-01）→ DLY-06 |
| verify_m5 | 4f TC-23 快捷列表/持久化（依赖 M6） | L200 | 转 pytest: 承载（D1 TC-SHC-02）→ DLY-06 |

**残留登记格式**（DLY-01/03 等登记项的统一样式）：`DELAYED：依赖 M<N>（原因 + 到期日），M6 已复核登记`——原因写清不在 M6 范围的具体归属（如「图鉴归 M11」），到期日写清目标里程碑/批次；登记后该项不再触发到期扫描失败，但必须随到期日所属里程碑复核。依据【总纲】VM6-2/ADR-08。

---

## 四、四源同步（VG-16 ~ VG-19）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-16 | 四源统一「接线闭环」口径 | 四处 M6 定义统一为「接线闭环」（【规划】L3481 已为新口径；run_all_tests L42 注释、启动手册 L42、细化_5d L95 待同步），并引用【仲裁】/【总纲】SCP-1；执行本档 §四后四处一致（对齐【总纲】SYN-1 / TC-M6-01） | 【总纲】SYN-1/SCP-1 |
| VG-17 | run_all_tests L42 注释同步 | run_all_tests.py L42 注释由「M6 数据框架（5a/5b/4c/4d/4e/6 系）」改为「M6 接线闭环（verify_m6 两段式门禁，见 细化_M6_verify门禁与承接 D8）」；`MILESTONES["m6"]` 置位见 VG-12 | 【总纲】SYN-1 |
| VG-18 | 启动手册 L42 M6 行同步 | 实现层启动手册 L42 M6 行由「数据框架 编辑器/GM/图鉴/成就/PVP（5a/5b/4c/4d/4e/6 系）」改为「M6 接线闭环 热重载/冒烟/质量（F5-F6、G2-G4，verify_m6 两段式）」；5a/5b 归 M12、4c/4d/4e/6 归 M11/M13（【总纲】SCP-2） | 【总纲】SYN-1/SCP-2 |
| VG-19 | 细化_5d §2.1 L95 M6 计数改接线闭环口径 | 细化_5d §2.1 M6 行（L95）M6 计数标注「历史口径，以 verify_m6 COVERAGE 为准」——verify_m6 断言对象 = D8 段一 8 项 + 段二 6 组承接（§1.1 断言对象表），不再沿用「3e 30 + 3e2 14 + 5a 18 + 5b 34 + 5c 18 = 114 TC」数据口径；3e/3e2 校验面并入 verify_m6 段一⑥ 内容校验面（不做新功能只验证，【总纲】SCP-2）；5a/5b 归 M12 | 【总纲】SYN-1/SCP-2/SYN-3；【批3B】P2-4 |

---

## 五、验收单与归档（ACC-01 ~ ACC-03）

### 5.1 里程碑验收单（m6_checklist.md）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| ACC-01 | 验收单 8 项逐项勾选 | 产物 = `docs/verify/m6_checklist.md`，由 verify_m6 段一⑦ 写入；结构 = 8 项验收单逐项行，每行含「验收项 + 断言对象/产物路径 + 对照【规划】任务 T 编号（F5-F6/G2-G4，L3481）+ 各子文档 TC 计数列（D1~D7 各档「文档总览」计数）+ 勾选时间 + 结论（✅ 通过 / ❌ 失败 + 失败回溯）」。粒度到子文档，不进每条 TC（【总纲】附录 A L193） | 【总纲】ADR-09/VM6-1 项7；【批3A】P1-4 |

**验收单模板**（【工程补白】——总纲未定义逐行字段，本档定型）：

```
# M6 里程碑验收单（docs/verify/m6_checklist.md）
| 验收项 | 断言对象/产物 | 对照【规划】任务 | 子文档 TC 计数 | 勾选时间 | 结论 |
|---|---|---|---|---|---|
| ① 热重载回退 | verify_m6 段一① | F5（L3436-3439） | D3 21 例 | YYYY-MM-DD | ✅/❌ |
| ② 冒烟闭环 | e2e_m6_smoke + 五档包 | F6（L3441-3444） | D4 21 例 | ... | ✅/❌ |
| ③ 故障注入六类 | tests/fault/ 六脚本 | G3（L3460-3463） | D5 26 例 | ... | ✅/❌ |
| ④ 覆盖率 ≥80% | 覆盖率报表 | G4（L3465-3468） | D7 30 例（COV） | ... | ✅/❌ |
| ⑤ ruff/mypy/pytest | 快速门结果 | G4 | D7 30 例（LNT） | ... | ✅/❌ |
| ⑥ 内容包 validator 全绿 | PYTEST_FILES 全绿 | F6/G1 | D4 21 例 | ... | ✅/❌ |
| ⑦ 里程碑验收单 | 本文件 | G1（L3450-3453） | D8 21 例 | ... | ✅/❌ |
| ⑧ CHANGELOG+归档 | CHANGELOG.md + docs/verify/ | G1/G4 | D7 30 例（CHG） | ... | ✅/❌ |
```

### 5.2 verify 输出归档

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| ACC-02 | verify 输出归档 docs/verify/ | verify 输出归档路径统一 = `docs/verify/`（【总纲】ADR-10），写入者 = verify_m6.py；归档物 = ① verify_m6 报告（`docs/verify/m6/verify_m6_<YYYYMMDD>.md`：全量输出摘要 + 断言计数 + 失败回溯）② 冒烟留档（`docs/verify/m6_smoke.md`，D4 定义，五段【工程补白】）③ 覆盖率报表（`docs/verify/coverage_<YYYYMMDD>.txt`，D7 COV 定义）④ 验收单（`docs/verify/m6_checklist.md`，本档 ACC-01）。《开发记录》保留「门禁通过/失败 + 摘要」一行并附 docs/verify/ 链接（对齐【5d】L234） | 【总纲】ADR-10/VM6-1 项4·8；【批3A】P1-5；【批2B】P1-4 |
| ACC-03 | M0-M5 归档欠账回填 | M0-M5 历史 verify 无归档（verify_m0~m5 全部只 print 到 stdout、无文件写出）——欠账在 D7 CHANGELOG 建档（CHG 规则）时统一回填说明：CHANGELOG.md 新增「M0-M5 归档欠账」说明段（记录原因 = G1「verify 输出留档于仓库 docs/」自 G1 成文起未落地），并声明自 M6 起 verify_m6 按 ACC-02 归档；M0-M5 不补历史报告文件，仅登记 | 【总纲】ADR-10；【批3A】P0-2/P1-5；【批2B】P1-4/P1-5 |

---

## 六、G 编号统一（VG-20 ~ VG-21）

| 编号 | 规则 | 内容 | 依据 |
|---|---|---|---|
| VG-20 | verify 输出统一「M<N> 门禁」 | verify 脚本输出（通过/失败行）统一改用「M<N> 门禁」字样（如「M4 门禁：verify_m4 全绿」），G 编号保留各文档内部语义、不再出现在 verify 输出——现状 verify_m4 L476/L478 混打「G5/M4 门禁」、verify_m5 L662/L664 混打「G5/M5 门禁」、verify_m3 L368/L370 打「G3 门禁」（细化_5d 称 M3=G4，编号错位），本档统一为「M<N> 门禁」根除跨文档歧义 | 【总纲】ADR-07；【批3B】P2-2 |
| VG-21 | 细化_5d §6.1 G0-G7 与规划 G1-G4 撞名登记 | 细化_5d §6.1（L219-228）G0-G7（里程碑门禁）与实现层规划 §7（L3448-3468）G1-G4（验证体系任务）存在 G1/G2/G3/G4 撞名——登记处理：① 细化_5d 侧 G 编号只作里程碑门禁语义（G1=M0 … G6=M5/M6），规划侧 G1-G4 只作任务语义；② 两套 G 编号互不引用、不交叉换算；③ verify 输出不再打印任何 G 编号（VG-20），撞名仅存在于文档内部语义，由本登记收口 | 【总纲】ADR-07；【批3B】P2-2；【批6B】P2-5 |

---

## 七、承接审查 P 项（对账表）

> 承接纪律：【总纲】DOC-2/PMP-4——先回读报告原文再落笔；每条给落点规则/TC，归 D7/D6/D5/D1/D4 的注明转归；孤儿项由【总纲】TC-M6-12 暴露。

### 7.1 批3组A（G1 门禁，10 项）

| 序号 | P 项 | 问题摘要（审查原文要点） | 落点规则/TC |
|---|---|---|---|
| 1 | 【批3A】P0-1 | G1 统一模板 7 项中 4 项（ruff/mypy、验收单、归档、CHANGELOG）无可执行载体 → 模板重构为 8 项且每项声明执行载体与断言落点 | VG-01（8 项模板）+ VG-02~09（逐项载体）；CHANGELOG 转归 D7（CHG） |
| 2 | 【批3A】P1-4 | 验收单内容/粒度/产物未定义，与 COVERAGE 两层关系未仲裁 | ACC-01（m6_checklist 模板，粒度到子文档）；COVERAGE 为其 TC 级子层（§1.1 断言对象表） |
| 3 | 【批3A】P1-5 | 归档路径/命名/写入者未定义，docs/ 与《开发记录》两目标冲突 | ACC-02（docs/verify/ + 命名 + 写入者 = verify_m6.py）+ ACC-03（M0-M5 欠账回填） |
| 4 | 【批3A】P1-6 | verify_m6 构成四源冲突 + `--only m6` 返回 0 假绿 | VG-01（段一 8 项）+ VG-10（段二 6 组）+ VG-11（不假绿）+ §四 四源同步 |
| 5 | 【批3A】P2-1 | G1 模板缺覆盖率核算/故障注入两项，「统一模板」名不副实 | VG-01 8 项含 ④ 覆盖率 / ③ 故障注入两项 |
| 6 | 【批3A】P2-2 | G1 验收③「任一红拦类回归失败 → 里程碑不通过」判定载体未成文 | VG-07（validator 红拦回归载体）+ VG-15（退出码聚合） |
| 7 | 【批3A】P2-3 | verify_m5 缺失测试文件黄提示不判失败，与「pytest 全绿」张力 | DLY-09（缺失必测文件按失败，ADR-08） |
| 8 | 【批3A】P2-4 | G2「battle 留后续路」陈旧口径 | 转归 D6（SYN-3 已清）；本档不承接 |
| 9 | 【批3A】P2-5 | §9 风险表未登记 G1 侧欠账 | 转归 D7（§9 风险补条目）；本档不承接 |
| 10 | 【批3A】P2-6 | run_all_tests/记录.md 宣称能力与实际不符（datapack/fault/--fast） | VG-14（help 与分支同步 + --fast 真正使用）+ VG-15（对齐 5d §3.2） |

### 7.2 批3组B（G1 跨里程碑，10 项）

| 序号 | P 项 | 问题摘要（审查原文要点） | 落点规则/TC |
|---|---|---|---|
| 1 | 【批3B】P0-1 | M6 范围三处定义冲突，verify_m6.py 无唯一权威 | §四 四源同步（VG-16~19）+ VG-12（MILESTONES 置位） |
| 2 | 【批3B】P0-2 | `--only m6` exit 0 假绿 / 全量静默跳过 m6 | VG-11（不假绿铁律） |
| 3 | 【批3B】P1-1 | DELAYED 过期不检测 + verify_m4 批次7-01 实证失真 | DLY-07（到期扫描）+ DLY-08（批次7-01 立即翻转） |
| 4 | 【批3B】P1-2 | DELAYED→M6 承接孤儿（图鉴/防嵌套/锻造/注册/状态/快捷） | VG-10 + DLY-01~06（六组裁决）+ DLY-10（对账表） |
| 5 | 【批3B】P1-4 | G1 模板 5 步 vs M6 列 6 项不对应 | VG-01（8 项模板统一）+ ACC-01（验收单） |
| 6 | 【批3B】P1-5 | run_all_tests 与细化_5d §3.2 流程不符 + help 广告未实现过滤 | VG-15（对齐 5d §3.2）+ VG-14（help 与分支同步） |
| 7 | 【批3B】P2-1 | verify_m0 §5「硬门禁」与 exit 0 矛盾 + 「M1 恢复」未兑现 | 转归 D7（COV/ADR-11 伪托 D5 修正）；VG-05 引用其产出 |
| 8 | 【批3B】P2-2 | G 编号跨文档混乱（verify_m3/m4/m5 打 G3/G5） | VG-20（输出统一 M<N> 门禁）+ VG-21（撞名登记） |
| 9 | 【批3B】P2-3 | 缺失 PYTEST_FILES 黄提示不判失败 | DLY-09（缺失必测文件按失败，ADR-08） |
| 10 | 【批3B】P2-4 | 细化_5d §2.1 TC 计数陈旧 | VG-19（L95 标注历史口径以 verify_m6 COVERAGE 为准） |

### 7.3 批2组B（F6 断言，1 项）

| 序号 | P 项 | 问题摘要（审查原文要点） | 落点规则/TC |
|---|---|---|---|
| 1 | 【批2B】P2-1 | verify_m4「批次7-01 端到端冒烟」DELAYED 声明过期（test_e2e_m4_smoke.py 已落盘） | DLY-08（立即翻转 `pytest:test_e2e_m4_smoke.py::test_smoke_*`）+ DLY-07（教训固化：DELAYED→pytest: 翻转纳入门禁自检） |

---

## 八、收官核验（BCH-4）

| 判据 | 定义 | 依据 |
|---|---|---|
| ① M6 完结判据 | verify_m6 段一（8 项验收单）+ 段二（6 组承接）全绿 = M6 完结判据 | 【总纲】BCH-4；TC-VG-01~11/TC-DLY-01~03 |
| ② 全量回归 | M6 完结后 `run_all_tests.py` 全量 exit 0 且输出含 m6 小节（MILESTONES["m6"] 已置位，不假绿） | 【总纲】BCH-4；TC-VG-14 |
| ③ CHANGELOG 建档 | CHANGELOG.md 建档 M6 条目（D7 CHG 承接）+ M0-M5 欠账回填说明（ACC-03） | 【总纲】BCH-4/ADR-10；TC-ACC-02 |
| ④ 六门禁全绿 | M0-M6 六门禁全绿（verify_m0~m6 各自全绿）后进入 M7 | 【总纲】BCH-4 |

**收官流程**：批 1~7 全部完成（BCH-3）→ 批 8 落地 verify_m6.py + run_all_tests 接入 m6（VG-12~15）→ 段一 8 项 + 段二 6 组全绿（§一/§三）→ 四源同步 + 验收单勾选 + 归档落盘（§四/§五）→ `run_all_tests.py` 全量 exit 0 含 m6 → M6 完结，进入 M7。依据【总纲】BCH-3/BCH-4。

---

## 九、决策记录与遗留

### 9.1 决策记录

- **ADR-D8-01（段一 8 项粒度）**：verify_m6 段一 8 项验收单 = 每项一个 verify_m6 断言/产物段，验收单粒度到子文档不进每条 TC。理由 = 对齐【总纲】ADR-09/附录 A L193；防「勾选」退化为人工判定反模式（【批3A】P1-4）。影响 = VG-01/ACC-01。
- **ADR-D8-02（段二残留登记裁决）**：段二 6 组承接中「图鉴分级/锻造 TPL-10/11」显式残留登记（到期日 = 图鉴系统里程碑 M11 / 生活生产内容包批次），不强行转 pytest。理由 = 图鉴归 M11（SCP-2）、锻造不在 M6 接线闭环范围；残留登记含到期日即不构成永久死缺口（VM6-2/ADR-08）。影响 = DLY-01/DLY-03。
- **ADR-D8-03（到期扫描口径）**：到期扫描「依赖 M<N>」目标为 verify_m<N>.py 的 COVERAGE 承接，N ≤ M6 未翻转即失败；残留登记（DLY-01/03）为唯一豁免。理由 = 对齐【总纲】VM6-4；防 M2/M3/M5 DELAYED 链在 M6 无人收口（【批3B】P1-1）。影响 = DLY-07/DLY-10。
- **ADR-D8-04（G 编号统一）**：verify 输出统一「M<N> 门禁」，G 编号不再出现在 verify 输出；细化_5d G0-G7 与规划 G1-G4 撞名只登记不换算。理由 = 对齐【总纲】ADR-07；verify_m3/m4/m5 现行 G3/G5 编号错位（【批3B】P2-2）。影响 = VG-20/VG-21。
- **ADR 引用不重裁决**：本档全部接缝（两段式定义/归档/验收单/不假绿/G 编号）引用【总纲】VM6-1~4/ADR-07~10，不重复裁决（【总纲】DOC-4）。

### 9.2 边界与遗留（承接 P2 收纳）

- **本档不覆盖的 P2**：批3A P2-4（battle 陈旧口径，转归 D6，SYN-3 已清）；批3A P2-5（§9 风险表，转归 D7）；批3B P2-1（verify_m0 覆盖率表述，转归 D7，ADR-11）；批4A/批4B/批5A/批5B/批6A/批6B 的 P 项由 D1~D7 各自承接，本档不重复。
- **历史 M6 数据口径废弃登记**：细化_5d §2.1 L95「M6 数据 114 TC（3e 30 + 3e2 14 + 5a 18 + 5b 34 + 5c 18）」为历史口径，由 VG-19 标注作废；verify_m6 COVERAGE 以本档段一断言对象表为准（【总纲】SYN-3）。
- **verify_datapack 接入**：细化_5d §3.1 L124 全量回归含 verify_datapack，但 scripts/verify/verify_datapack.py 不存在（【批3B】P1-5 现状核对）——接入决策归 D7（数据包/数值模拟载体），本档 VG-15 仅要求 run_all_tests 分支与 help 同步（未接入项如实标注或移出 help）。
- **服务器冒烟（【规则】L435）区分**：本档 verify_m6 段一② 冒烟 = 内容包冒烟（D4，注册门槛→锁定→攻击→结算），≠ 服务器冒烟（/注册 /锁定 /攻击 一轮闭环，G7 发布门）——形态区分承接【总纲】ADR-01，不在本档重新裁决。

---

## 附录 A（本档验收用例，TC-VG-01 ~ TC-VG-16 + TC-DLY-01 ~ TC-DLY-03 + TC-ACC-01 ~ TC-ACC-02，共 21 例）

### A.1 段一 8 项 + 段二承接 + 不假绿（TC-VG-01 ~ TC-VG-11）

| # | 用例名 | 前置 | 操作 | 预期 | 引用 |
|---|---|---|---|---|---|
| TC-VG-01 | 段一 8 项可执行 | verify_m6.py 落盘 | 逐项找断言对象/产物 | 8 项各有可执行断言/产物，与 §1.1 断言对象表一致 | VG-01；【总纲】TC-M6-06 |
| TC-VG-02 | 段一① 热重载断言载体 | D3 落盘 | 断言 verify_m6 段一① 引用 D3 载体 | D3 TC-WIR/RSM 全绿 + 快照冗余断言在段 | VG-02；[D3·TC-WIR-01~14] |
| TC-VG-03 | 段一② 冒烟断言载体 | D4 落盘 | 断言 e2e_m6_smoke + 四件套/五档包 | D4 TC-SMK/PCK 全绿，四步逐步断言 | VG-03；[D4·TC-SMK-01~15] |
| TC-VG-04 | 段一③ 故障注入断言载体 | D5 落盘 | 断言 tests/fault/ 六脚本 + --only fault | D5 TC-FLT/SES 全绿 + fault 分支 exit0 | VG-04；[D5·TC-FLT-01~21] |
| TC-VG-05 | 段一④ 覆盖率断言载体 | D7 COV 落盘 | 断言 core/engine/content 各自 ≥80% | 三目录各自行覆盖 ≥80% + 报表落 docs/verify/ | VG-05；[D7·TC-COV-01~08] |
| TC-VG-06 | 段一⑤ ruff/mypy 断言载体 | D7 LNT 落盘 | 断言 pyproject 快速门 | ruff check + mypy 通过，失败 exit≠0 | VG-06；[D7·TC-LNT-01~05] |
| TC-VG-07 | 段一⑥ validator 断言载体 | D4 落盘 | 断言 PYTEST_FILES 红拦回归 | 红拦真拦截/黄提示可过，content/ 动态扫描全绿 | VG-07；[D4·SMK validator 矩阵] |
| TC-VG-08 | 段一⑦ 验收单产物 | verify_m6 落盘 | 检查 docs/verify/m6_checklist.md | 8 项逐项勾选 + T 编号 + TC 计数列 + 时间/结论 | VG-08；ACC-01 |
| TC-VG-09 | 段一⑧ 归档产物 | verify_m6 落盘 | 检查 docs/verify/ | verify_m6 报告/冒烟留档/覆盖率报表/验收单四物齐全 | VG-09；ACC-02 |
| TC-VG-10 | 段二 6 组承接 | 批1 完成 | 检查 DLY-01~06 裁决落地 | 6 组各转 pytest: 承载或残留登记（含到期日），无永久死缺口 | VG-10；DLY-01~06 |
| TC-VG-11 | 不假绿 --only m6 | verify_m6 未置位 | 跑 `run_all_tests.py --only m6` | exit≠0 + 提示「M6 未接入 → 门禁不完整」 | VG-11；【批3B】P0-2 |

### A.2 run_all_tests 接入（TC-VG-12 ~ TC-VG-14）

| # | 用例名 | 前置 | 操作 | 预期 | 引用 |
|---|---|---|---|---|---|
| TC-VG-12 | MILESTONES 置位 + 顺序 | verify_m6.py 落盘 | 读 run_all_tests L35-43 | MILESTONES["m6"] = verify_m6.py，注释为接线闭环；全量按 m0→m6 顺序 | VG-12/VG-13；【5d】L139-140 |
| TC-VG-13 | help 与分支同步 | run_all_tests 更新 | 跑 `--help` 并核对 --only 分支 | help 列出的过滤项均有实现分支；--fast 生效（冒烟抽样） | VG-14；【批2B】P2-2 |
| TC-VG-14 | 全量回归含 m6 | M6 完结 | 跑 `run_all_tests.py` 全量 | exit 0 + 输出含 m6 小节（不假绿），覆盖率 ≥80% | VG-15；【5d】L124/L140；【总纲】BCH-4 |

### A.3 DELAYED 到期扫描（TC-DLY-01 ~ TC-DLY-03）

| # | 用例名 | 前置 | 操作 | 预期 | 引用 |
|---|---|---|---|---|---|
| TC-DLY-01 | verify_m4 批次7-01 已翻转 | verify_m6 落盘 | grep verify_m4 COVERAGE 批次7-01 | 已转 `pytest:test_e2e_m4_smoke.py::test_smoke_*`，无「未落盘」字样 | DLY-08；【批2B】P2-1 |
| TC-DLY-02 | 到期扫描过期即失败 | verify_m6 落盘 | 人为保留一条过期 DELAYED（依赖 M<N>、N≤6 未翻转） | verify_m6 断言失败，提示「DELAYED 过期未翻转」 | DLY-07；【总纲】VM6-4 |
| TC-DLY-03 | 收口对账表核对 | 批1~7 完成 | 对 DLY-10 对账表逐项实测 | 每项现状 → 裁决一致；残留登记均含到期日 | DLY-10 |

### A.4 四源同步 + 验收单/归档 + G 编号（TC-VG-15 ~ TC-VG-16 + TC-ACC-01 ~ TC-ACC-02）

| # | 用例名 | 前置 | 操作 | 预期 | 引用 |
|---|---|---|---|---|---|
| TC-VG-15 | 四源同步 | 本档落盘 | 对照【规划】L3481 / 细化_5d L95 / run_all_tests L42 / 启动手册 L42 | 四处均表述「接线闭环」且引用【仲裁】 | VG-16~19；【总纲】TC-M6-01 |
| TC-VG-16 | 输出统一 M<N> 门禁 | verify 脚本更新 | grep verify_m0~m6 输出行 | 统一「M<N> 门禁」字样，无 G 编号混打 | VG-20/VG-21；【总纲】ADR-07 |
| TC-ACC-01 | m6_checklist 落盘 | verify_m6 段一⑦ | 读 docs/verify/m6_checklist.md | 8 项勾选齐全 + T 编号 + TC 计数列 + 时间/结论 | ACC-01；【总纲】ADR-09 |
| TC-ACC-02 | 归档物齐全 | verify_m6 全绿 | ls docs/verify/ | 报告/冒烟留档/覆盖率报表/验收单四物齐全；M0-M5 欠账说明入 CHANGELOG | ACC-02/ACC-03；【总纲】ADR-10 |

---

*本档为 M6 细化文档集收官文档（D8）：聚合 D1~D7 的 172 例 TC 计数为 verify_m6 段一断言对象，落地段二 6 组承接、不假绿铁律、DELAYED 到期扫描、四源同步、验收单与归档契约、G 编号统一；M6 完结判据与收官流程见 §八（承接【总纲】BCH-4）。*
