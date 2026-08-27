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