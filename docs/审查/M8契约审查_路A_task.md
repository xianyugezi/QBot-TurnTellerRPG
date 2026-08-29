# M8 契约审查 路A 任务文件（核心机制子文档）

（本文件 = 审查角色卡 + 审查任务，拼入 dshx 命令执行）

---

（角色卡从 docs/审查/审查角色_初始化.md cat 拼入）

---

【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。

【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态文件审查；运行行为结论标'静态推导'。禁止子代理，独自完成。】
【预算纪律：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；接口签名核对用 read 直接定位真实函数，不必穷尽。】

【审查任务】M8 共享契约审查 路A（核心机制子文档）——主 agent 自写契约对照审查：

审查对象：
- /root/QBot-TurnTellerRPG/docs/m8_contract_核心机制.md（三层漏斗/职业等级/能量条/品质/特性/投料触媒/调合会话状态机，455 行，IF-01~43）

对照基准（仓库内路径）：
- 细化修订版：docs/细化/细化_2c4a_炼金三层漏斗.md、细化_2c4e_品质与特性.md、细化_2c4f_投料触媒与能量条.md
- 定稿副本：docs/审查参考/炼金系统设计定稿.md（516 行）
- 接口摸底：docs/m8_接口摸底.md（真实签名基准）
- 仲裁：docs/仲裁/细化_0_仲裁决议汇总.md（R-07/R-08）
- 批次：docs/m8_batch_plan.md

【审查维度】：
① IF 接口签名 vs 代码真实签名（M5 最高价值教训）：契约 IF-xx 引用的签名（world/session.py SessionManager 5 方法、repository.upsert_session/delete_session/settle_exit_idempotent、InventoryEngine.add_item/remove_item、condition_engine [熟练度:{T}]、formula_engine [宝石]）read 真实代码核对——签名是否一致、行号是否准确、标注的实现批次是否合理
② 字段/schema vs 细化修订版：quality_tiers 键集 common/uncommon/rare/legendary、energy_enabled=false 默认、catalyst_unlock_tier=expert、数量上限 2147483647、平铺宝石、proficiency dict 形态——是否与细化修订版/拍板/R 裁决一致
③ 跨文档一致性：核心机制与指令契约/数据与校验/战斗资源子文档字段落点不冲突（energy/quality/proficiency 等）
④ 验收 TC 矩阵：2c4a TC-01~26 + 2c4e TC-01~26 + 2c4f TC-01~38 映射完整性
⑤ 用户 5 项拍板 + R-07/R-08 落实
⑥ 缺漏：细化要求（状态机迁移表/能量懒计算/品质降级/特性继承四规则族/触媒）未进契约

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8契约_路A_jspace.md）：P0/P1/P2 分级+契约文档:行号+证据行号+修复建议；无问题维度逐一确认。
最后回复：①门控档位 ②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
