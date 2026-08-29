# M8 契约审查 路B2 任务文件（指令契约 §三~§八）

（本文件 = 审查角色卡 + 审查任务，拼入 dshx 命令执行）

---

（角色卡从 docs/审查/审查角色_初始化.md cat 拼入）

---

【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。

【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态文件审查；运行行为结论标'静态推导'。禁止子代理，独自完成。】
【预算纪律：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 12 次内；接口签名核对用 read 直接定位真实函数。420 秒内必须开始写报告。】

【审查任务】M8 共享契约审查 路B2（指令契约 §三~§八：解析器/会话互斥/原子幂等/IF/TC/铁律）——主 agent 自写契约对照审查：

审查对象（只审指令契约子文档的 §三 解析器接线 + §四 会话互斥 MUT + §五 原子幂等 ATO + §六 IF 清单 + §七 TC 矩阵 + §八 铁律）：
- /root/QBot-TurnTellerRPG/docs/m8_contract_指令契约.md（后约 300 行）

对照基准（仓库内路径）：
- 细化修订版：docs/细化/细化_2c4d_炼金指令表.md（§三 MUT-01~08 / §四 ATO-01~08 / §五 TC-01~34）
- 定稿副本：docs/审查参考/炼金系统设计定稿.md（§4.6 会话 L171-185、§七 D1 L290-300、L115 原子、L178 version、L180 串行队列、L509 热重载）
- 分隔符规范：docs/审查参考/指令分隔符统一规范.md
- 接口摸底：docs/m8_接口摸底.md（parse_command/CommandSpec/Router/命令壳模式真实签名）
- 真实代码：commands/parsers.py、commands/router.py、commands/shop_commands.py（register_shop_commands 壳模式）、storage/repository.py（idem 设施）、world/battle_boundary.py（settle_exit_idempotent）
- 批次：docs/m8_batch_plan.md

【审查维度】：
① 解析器接线：白名单缺词清单 read parsers.py 核对是否准确、FIXED_SUBWORDS 零新增是否属实、DEFAULT_QUANTITY_COMMANDS 是否含复制、max_qty 注入 2147483647、A+B 两空格位置参数实现注意
② 会话互斥 MUT：与细化_2c4d MUT-01~08 一致（单会话槽总纲【框架补白】/全局互斥/即时调合豁免/战斗拦截/挂起恢复/非法转移模板/深度会话分离/僵尸回收）——对齐 world/session.py + repository + settle_exit_idempotent
③ 原子幂等 ATO：与细化_2c4d ATO-01~08 一致；**ATO 是否复用框架 idempotency_keys/idem_claim/write_idem_key（勿自创幂等表）**；每条覆盖指令+实现批次
④ IF 接口清单：新指令壳函数（cmd_synth/cmd_alchemy/cmd_feed/cmd_inherit/cmd_confirm/cmd_quit/cmd_resume/cmd_deep/cmd_evolve/cmd_core/cmd_boost/cmd_compose/cmd_decompose/cmd_register/cmd_duplicate/cmd_recipe_compose/cmd_trait_compose/cmd_challenge/cmd_battle_alchemy/cmd_socket/cmd_unsocket/cmd_teach 等）签名 read 真实代码核对（对照 shop_commands.py register_shop_commands L447-483 壳模式）；register_alchemy_commands(router, *, make_context=None) 装配入口
⑤ TC 矩阵：细化_2c4d TC-01~34 映射到实现批次完整性
⑥ 跨文档一致性：与核心机制/数据与校验/战斗资源子文档批次/字段不冲突
⑦ 用户 5 项拍板 + R-07/R-08 落实

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8契约_路B2_jspace.md）：P0/P1/P2 分级+契约文档:行号+证据行号+修复建议；无问题维度逐一确认。
最后回复：①门控档位 ②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
