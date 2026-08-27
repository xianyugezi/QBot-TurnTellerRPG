# M6 里程碑验收单（docs/verify/m6_checklist.md）

> 写入者：verify_m6 段一⑦（D8 ACC-01；写入者 = verify_m6.py）；生成时间：2026-08-28
> 粒度：到子文档，不进每条 TC（【总纲】附录 A L193）；对照【规划】L3481 任务> T 编号（F5-F6/G2-G4）。
> 子文档 TC 计数（D1~D7 各档「文档总览」验收用例数）：> D1 29 + D2 15 + D3 21 + D4 21 + D5 26 + D6 30 + D7 30
> = 172 例 TC（D8 §〇 断言对象聚合）——verify_m6 段一断言对象的 TC 计数总和。

| 验收项 | 断言对象/产物 | 对照【规划】任务 | 子文档 TC 计数 | 勾选时间 | 结论 |
|---|---|---|---|---|---|
| ① 热重载回退 | verify_m6 段一①（D3 WIR/RSM 载体 + F5 快照冗余，四测试文件） | F5（L3436-3439） | D3 21 例 | 2026-08-28 | ✅ 通过 |
| ② 冒烟闭环 | scripts/e2e_m6_smoke.py + tests/unit/test_e2e_m6_smoke.py（四步矩阵 + validator 四件套） | F6（L3441-3444） | D4 21 例 | 2026-08-28 | ✅ 通过 |
| ③ 故障注入六类 | tests/fault/ 六脚本（crash/save/reload/formula/doublepay/netdrop） | G3（L3460-3463） | D5 26 例 | 2026-08-28 | ✅ 通过 |
| ④ 覆盖率 ≥80% | docs/verify/coverage_latest.txt（D7 COV 报表：core/engine/content 各自 ≥80%） | G4（L3465-3468） | D7 30 例（COV） | 2026-08-28 | ✅ 通过 |
| ⑤ ruff/mypy/pytest | pyproject [tool.ruff]/[tool.mypy] 阶段0 快速门 + 全量 pytest | G4 | D7 30 例（LNT） | 2026-08-28 | ✅ 通过 |
| ⑥ 内容包 validator 全绿 | content/ 五档包动态扫描 + validator 矩阵 + 防嵌套红拦 + PYTEST_FILES 红拦回归 | F6/G1 | D4 21 例 | 2026-08-28 | ✅ 通过 |
| ⑦ 里程碑验收单 | docs/verify/m6_checklist.md（本文件，verify_m6 段一⑦ 写入） | G1（L3450-3453） | D8 21 例 | 2026-08-28 | ❌ 失败（回溯见 docs/verify/m6/ 归档报告） |
| ⑧ CHANGELOG+归档 | CHANGELOG.md（M6 条目 + ACC-03 欠账段）+ docs/verify/ 四归档物 | G1/G4 | D7 30 例（CHG） | 2026-08-28 | ❌ 失败（回溯见 docs/verify/m6/ 归档报告） |

---

| 子文档 | 验收用例计数 |（D8 §〇 断言对象聚合）|
|---|---|
| D1 | 29 例 | |
| D2 | 15 例 | |
| D3 | 21 例 | |
| D4 | 21 例 | |
| D5 | 26 例 | |
| D6 | 30 例 | |
| D7 | 30 例 | |
| 合计 | 172 例 | |

## 失败回溯

（无失败时填「无」）
