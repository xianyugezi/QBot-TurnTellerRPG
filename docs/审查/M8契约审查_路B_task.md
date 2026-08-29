# M8 契约审查 路B 任务文件（指令契约子文档）

（本文件 = 审查角色卡 + 审查任务，拼入 dshx 命令执行）

---

（角色卡从 docs/审查/审查角色_初始化.md cat 拼入）

---

【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。

【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态文件审查；运行行为结论标'静态推导'。禁止子代理，独自完成。】
【预算纪律：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；接口签名核对用 read 直接定位真实函数，不必穷尽。】

【审查任务】M8 共享契约审查 路B（指令契约子文档）——主 agent 自写契约对照审查：

审查对象：
- /root/QBot-TurnTellerRPG/docs/m8_contract_指令契约.md（22 条有效指令契约/解析器接线/会话互斥 MUT/原子幂等 ATO，477 行）

对照基准（仓库内路径）：
- 细化修订版：docs/细化/细化_2c4d_炼金指令表.md
- 定稿副本：docs/审查参考/炼金系统设计定稿.md（§九 指令总表 L316-344）
- 分隔符规范：docs/审查参考/指令分隔符统一规范.md
- 接口摸底：docs/m8_接口摸底.md
- 仲裁：docs/仲裁/细化_0_仲裁决议汇总.md
- 批次：docs/m8_batch_plan.md

【审查维度】：
① IF 接口签名 vs 代码真实签名：契约引用的 parse_command/CommandSpec/Router.register/命令壳模式 cmd_xxx(parsed,ctx)->str/register_xxx_commands 签名 read 真实代码核对；新指令壳函数清单（cmd_synth/cmd_alchemy/cmd_feed 等 22+）签名是否与既有模式一致（对照 shop_commands.py L447-483）
② 指令契约 vs 细化_2c4d 修订版：22 条指令的门槛/参数/流程/消息模板是否与细化一致（尤其触媒专家 R-07、能量默认关 R-08、数量上限 2147483647、分解宝石平铺、A+B 两空格位置参数、/秘钥 不注册）
③ 解析器接线：白名单缺词清单是否准确（read parsers.py 核对）、FIXED_SUBWORDS 零新增是否属实、DEFAULT_QUANTITY_COMMANDS 是否含复制、max_qty 注入
④ 会话互斥 MUT/原子幂等 ATO：与细化修订版一致；ATO 是否复用框架 idempotency_keys/idem_claim/write_idem_key（勿自创幂等表）
⑤ 跨文档一致性：与核心机制/数据与校验/战斗资源子文档的批次/字段落点不冲突
⑥ 用户 5 项拍板 + R-07/R-08 落实；/协力 批次缺口处理是否合理

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8契约_路B_jspace.md）：P0/P1/P2 分级+契约文档:行号+证据行号+修复建议；无问题维度逐一确认。
最后回复：①门控档位 ②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
