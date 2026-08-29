# M8 契约审查 路D 任务文件（战斗资源子文档 + batch_plan）

（本文件 = 审查角色卡 + 审查任务，拼入 dshx 命令执行）

---

（角色卡从 docs/审查/审查角色_初始化.md cat 拼入）

---

【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。

【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态文件审查；运行行为结论标'静态推导'。禁止子代理，独自完成。】
【预算纪律：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；接口签名核对用 read 直接定位真实函数，不必穷尽。】

【审查任务】M8 共享契约审查 路D（战斗资源子文档 + batch_plan）——主 agent 自写契约对照审查：

审查对象：
- /root/QBot-TurnTellerRPG/docs/m8_contract_战斗资源.md（宝石货币/装饰珠/战斗即时调合/资源循环，323 行，IF-B01~30）
- /root/QBot-TurnTellerRPG/docs/m8_batch_plan.md（批次派工单：13 实现批 + 1 审查批）

对照基准（仓库内路径）：
- 细化修订版：docs/细化/细化_2c4b_宝石货币经济.md、细化_2c4c_珠与合成指令.md
- 定稿副本：docs/审查参考/炼金系统设计定稿.md（§七 战斗对接 L279-300 + §11 资源循环 L430-476）
- 接口摸底：docs/m8_接口摸底.md（battle.py do_action/to_snapshot/battle_boundary.settle_exit_idempotent）
- 仲裁：docs/仲裁/细化_0_仲裁决议汇总.md
- 批次：docs/m8_batch_plan.md

【审查维度】：
① IF 接口签名 vs 代码真实签名：契约引用的 BattleEngine.do_action/ActionOutcome/to_snapshot/battle_boundary.settle_exit_idempotent/dispatch_reward/InventoryEngine 系列 签名 read 真实代码核对
② 战斗即时调合：battle_alchemy_used 挂 to_snapshot dict 顶层键（核对 battle.py to_snapshot 实际结构是否支持新增顶层键）、中断不清零/结束清零语义、per_battle_limit=1、auto_use 可配、战斗内拦截模板、道具强度公式
③ 宝石货币：四来源走 dispatch_reward 入账（核对 reward.py _grant_scalar 的 gem 键空间前置——settings.currencies 登记 gem 是硬前置）、七消耗口 SINK-01~07 消耗量与门槛、分解平铺基础值 拍板①、材料×回收率向下取整
④ 装饰珠：同名递减 gem_diminish、触发上限≤3次/场按珠ID、珠升阶无门槛 拍板③ 禁跳级、战斗中不可插拔
⑤ 资源循环：委托任务板/种植/代工 与细化 2c4b/2c4c 覆盖完整性
⑥ batch_plan 批次合理性：13 实现批 + 1 审查批的路数/依赖/共享锚点是否自洽、/协力 批次是否已补排期、批9 战斗接线依赖批3 会话是否标注
⑦ 用户 5 项拍板 + R-07/R-08 落实

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8契约_路D_jspace.md）：P0/P1/P2 分级+契约文档:行号+证据行号+修复建议；无问题维度逐一确认。
最后回复：①门控档位 ②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
