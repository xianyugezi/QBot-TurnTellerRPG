【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。
【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态代码审查；运行行为结论标'静态推导'。】
【预算纪律】：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内，不要穷尽检索；引用抽查（行号存在性）用 read 直接定位，不必逐条精读定稿全文——参考文档可 grep 定位章节，不必全读。

任务：静态审查『/root/QBot-TurnTellerRPG』M8 炼金实现 批次A（炼金核心引擎层，5 文件）：
  - qbot_rpg/core/alchemy_core.py（AlchemyCore：new_snapshot/apply_feed/compute_chain/compute_element_scores/check_element_req/build_feature_pool/catalyst_resolve）
  - qbot_rpg/core/energy_bar.py（EnergyBar：懒计算能量条/lazy_regen/ENG-09 sync_after 锚点）
  - qbot_rpg/core/alchemy_auto.py（AutoFeed：配平贪心/基础材料/原子拒绝+差异）
  - qbot_rpg/core/alchemy_session.py（调合会话状态机：FEED/CAT/ENG/AUTO/BATCH 流程）
  - qbot_rpg/core/quality.py（QualitySystem：品质档位/round-half-up/上限三处叠加/降级 N 档）

参考：docs/m8_contract_核心机制.md（§六 FEED 全文/§七 会话快照形态/§二 职业等级）、
docs/m8_contract_指令契约.md（§2 /炼金 §3 /投料）、docs/细化/细化_2c4f_投料触媒与能量条.md、
docs/细化/细化_2c4e_品质与特性.md。

【审查维度】：
① 定稿落地（关键验收点）：会话快照形态 STO-03 键集（recipe_id/materials/chain/element_scores/pool/catalyst/pp/step/version）；投料守卫 GU-07~12（槽位/持有校验/原子拒绝差异）；连锁 compute_chain 相邻同属性 n-1 段/count 展开链位/chain_map 超界钳制；能量条 lazy_regen 查询即补格/上限封顶/safe zone 2 倍速/默认关直通；品质 round-half-up 四舍五入（非银行家舍入）/上限三处叠加 ≤100/降级差 N 档降 N 档最低普通封底；触媒 catalyst_resolve type 校验/注册制提示/方向修饰。
② 代码质量（bug/边界）：零 IO 零 NoneBot；构造器注入 settings；dict 操作不改外源；异常兜底。
③ 遗漏（验收点未覆盖）：细化 2c4f 40 规则/2c4e 56 规则中有无规则级遗漏；状态机迁移表缺边。

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8实现_批次A_jspace.md）：P0/P1/P2 分级+文件行号+修复建议；无问题维度确认（点名疑缺项已实现清单）。
最后回复：①门控档位②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
