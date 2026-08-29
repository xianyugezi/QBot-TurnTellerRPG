【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。
【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态代码审查；运行行为结论标'静态推导'。】
【预算纪律】：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；引用抽查用 read 直接定位，不必全读定稿——参考文档可 grep 定位章节。

任务：静态审查『/root/QBot-TurnTellerRPG』M8 炼金实现 批次B（合成+继承+结算+宝石，5 文件）：
  - qbot_rpg/core/synthesis.py（SynthesisEngine：跨职业合成 GU-01~03/原子校验全量差额/快照回滚单事务/熟练=配方等级×成品数）
  - qbot_rpg/core/upgrade.py（UpgradeEngine：kind=upgrade 通用执行器/珠三合一/配方合成幂等/特性合成同系/原子提交）
  - qbot_rpg/core/trait_inherit.py（TraitInherit：继承位等级化+SP 叠加/PP 预算/互斥/repeatable/负面/超特性第4位）
  - qbot_rpg/core/alchemy_settle.py（SettleEngine：/确认 9 步管线/全量复核/品质聚合+系数/上限叠加/刻度降级/触媒消耗/终态幂等 /放弃）
  - qbot_rpg/core/gem_wallet.py（GemWallet：/分解 回收率/宝石平铺基础值/两段式消息/入账）

参考：docs/m8_contract_指令契约.md（§2 /合成 §4 /继承 §5 /确认 §18 /分解）、
docs/m8_contract_核心机制.md、docs/细化/细化_2c4a_炼金三层漏斗.md、
docs/细化/细化_2c4c_珠与合成指令.md、docs/细化/细化_2c4e_品质与特性.md。

【审查维度】：
① 定稿落地（关键验收点）：合成 GU-01~04（跨职业任一制造/资源职业达标/原子校验差异/快照回滚/熟练经验=配方等级×成品数）；升级 4 实例（珠 3×同档同 ID+宝石→+1 阶禁跳级/配方合成已解锁幂等/特性合成同系判定+group 互斥/成品合成）；继承 INH-01~15（候选池/位预算 正式1精通2专家3+SP/PP 预算/互斥组/repeatable/负面特性宗师/超特性第 4 位独占/写入快照）；结算 F-05（9 步：全量复核→品质→系数→上限→刻度降级→触媒消耗→产出入包→熟练→终态幂等；材料不结算 /放弃）；宝石 GEM-15（分解 两段式：材料×回收率向下取整+宝石平铺 普通1/精良3/史诗8/传说20/标准版拒绝/入账 grant_gem）。
② 代码质量（bug/边界）：原子性（失败全拒+差异）；幂等键（message_id）；上限/预算溢出；dict 操作不改外源。
③ 遗漏（验收点未覆盖）：2c4a 29 规则/2c4c 46 规则/2c4e 56 规则有无规则级遗漏；TC 矩阵未覆盖。

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8实现_批次B_jspace.md）：P0/P1/P2 分级+文件行号+修复建议；无问题维度确认（点名疑缺项已实现清单）。
最后回复：①门控档位②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
