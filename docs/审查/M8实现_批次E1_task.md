【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。
【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态代码审查；运行行为结论标'静态推导'。】
【预算纪律】：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；引用抽查用 read 直接定位；alchemy_commands.py 约 3425 行，只精读本批功能段（grep 定位函数行号后 read 该段），其他段跳过。

任务：静态审查『/root/QBot-TurnTellerRPG』M8 炼金实现 批次E1（指令壳·会话主链段：/炼金 /投料 /继承 /继承超 /确认 /放弃 /调合续 /分解）：
  - qbot_rpg/commands/alchemy_commands.py（只审以下函数段：cmd_alchemy/cmd_feed/cmd_inherit/cmd_inherit_super/cmd_confirm/cmd_abandon/cmd_resume/cmd_decompose + 相关工具 _player_of/_prof_level/_settings_of/_session_mgr_of/format 模板）

参考：docs/m8_contract_指令契约.md（§2 /炼金 GU-05~08 F-02 M-02、§3 /投料 GU-09~12 F-03 M-03、§4 /继承 GU-13~16 F-04 M-04、§5 /确认 /放弃 /调合续 GU-17~19 F-05 M-05、§18 /分解 GU-33 F-18 M-18）、
docs/细化/细化_2c4d_炼金指令表.md。

【审查维度】：
① 定稿落地（关键验收点）：守卫链逐条（GU-05 炼金职业见习+ / GU-06 能量≥1 仅 energy_enabled=true 关则直通 / GU-07 单玩家无活跃会话全局互斥 SessionConflictError 鸭子捕获 不误删已有会话 / GU-08 触媒专家 位置参数2 限固定子词 自动 或键值 触媒= / GU-09 战斗拦截 / GU-10 会话中 / GU-11 材料存在+槽位持有 / GU-12 追加子词 / GU-13~16 继承 位预算/PP/候选池/超特性宗师 / GU-17~19 确认 会话守卫+幂等 / 分解 道具存在+wallet）；会话接线（acquire 成功后扣能量防孤儿会话）；渲染模板 M-02~05/M-18 纯文本无装饰 emoji；幂等键（message_id/settle_key）。
② 代码质量（bug/边界）：async/await 一致性；引擎接口消费与真实签名对齐（_session_mgr/engine 构造注入）；异常兜底；位置参数 2 限固定子词规则。
③ 遗漏（验收点未覆盖）：2c4d TC 未覆盖；守卫链缺边（如 /投料 在 /确认 后应拒？/放弃 幂等？）。

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8实现_批次E1_jspace.md）：P0/P1/P2 分级+文件行号+修复建议；无问题维度确认（点名疑缺项已实现清单）。
最后回复：①门控档位②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
