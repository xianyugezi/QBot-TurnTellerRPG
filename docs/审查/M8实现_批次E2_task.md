【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。
【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态代码审查；运行行为结论标'静态推导'。】
【预算纪律】：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；引用抽查用 read 直接定位；alchemy_commands.py 约 3425 行，只精读本批功能段（grep 定位函数行号后 read 该段），其他段跳过。

任务：静态审查『/root/QBot-TurnTellerRPG』M8 炼金实现 批次E2（指令壳·扩展指令段：/合成 /珠 /三类合成 /登记 /复制 /深度炼金 /进化 /镶核心 /加成 /挑战 /即时调合 /协力 /教学 /技能面板 /种植 /收获 /代工 /收取）：
  - qbot_rpg/commands/alchemy_commands.py（只审：cmd_synthesis/cmd_jewel_up/cmd_mount/cmd_unmount/cmd_product_merge/cmd_formula_merge/cmd_trait_merge/cmd_register/cmd_copy/cmd_deep/cmd_evolve/cmd_core/cmd_buff/cmd_challenge/cmd_instant/cmd_assist/cmd_tutorial/cmd_skill_panel/cmd_plant/cmd_harvest/cmd_helper/cmd_collect + 注册段 register_alchemy_commands）

参考：docs/m8_contract_指令契约.md（§1 /合成、§7 /进化、§8 /镶核心 /加成、§9 /珠升阶、§11-13 /成品合成 /配方合成 /特性合成、§14 /镶嵌 /拆珠、§15 /协力、§16 /挑战、§17 /即时调合、§19 /图鉴 /技能面板、§20 /登记 /复制、§21-22 /种植 /收获 /代工 /收取、§23 /教学）、
docs/m8_contract_战斗资源.md、docs/细化/细化_2c4d_炼金指令表.md。

【审查维度】：
① 定稿落地（关键验收点）：各指令门槛逐条（合成 跨职业/珠升阶 无职业硬门槛/成品合成 宗师/配方合成 专家/特性合成 宗师/登记复制 大师/深度炼金 大师/进化 宗师/镶核心 大师+会话中/加成 宗师限1次/挑战 宗师+材料×2/即时调合 大师+战斗内+限次/教学 无门槛/技能面板 无门槛/种植收获 正式/代工 精通）；守卫链完整性；引擎接口消费与真实签名对齐；渲染模板纯文本无装饰 emoji；幂等（复制/登记/进化 ATO-05）；数量上限提示不拦（复制 2147483647）。
② 代码质量（bug/边界）：async/await 一致性；注册完整性（register_alchemy_commands 全部指令注册，/图鉴 不重复注册）；异常兜底；位置参数/键值/列表语法解析。
③ 遗漏（验收点未覆盖）：2c4d TC 未覆盖；指令名/白名单一致（DEFAULT_WHITELIST 含全部）；/协力 同群校验。

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8实现_批次E2_jspace.md）：P0/P1/P2 分级+文件行号+修复建议；无问题维度确认（点名疑缺项已实现清单）。
最后回复：①门控档位②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
