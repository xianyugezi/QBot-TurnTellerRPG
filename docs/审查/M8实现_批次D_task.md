【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。
【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态代码审查；运行行为结论标'静态推导'。】
【预算纪律】：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；引用抽查用 read 直接定位，不必全读定稿。

任务：静态审查『/root/QBot-TurnTellerRPG』M8 炼金实现 批次D（资源循环+装配接线，5 文件）：
  - qbot_rpg/core/alchemy_harvest.py（HarvesterEngine：种植 GU-60 正式/种子 seed 标记/定时收获默认4h/收获品质≥种子/继承特性/温室大师复制/地块存档）
  - qbot_rpg/core/alchemy_helper.py（HelperEngine：/代工 代采代调/能源道具 GU-63/后台 tick 产出/收取/助手等级）
  - qbot_rpg/assembly/router_setup.py（M8 全指令注册 alchemy_commands；/图鉴 并入 codex 分册不重复注册）
  - qbot_rpg/assembly/context.py（make_context M8 引擎注入：registry/session_mgr/items/recipe/traits 表 + wallet/prof_engine 实构 + _inventory_hooks dirty 标记+实例通道 + currencies 引用）
  - qbot_rpg/assembly/runner.py（落档 merge：_m8_dirty_inventory → _ctx_inventory_to_player + inventory_instances 实例并入）

参考：docs/m8_contract_指令契约.md（§20 /种植 /收获、§21 /代工 /收取、§22 代工）、
docs/m8_batch_plan.md（批11-2 装配接线）、docs/m8_contract_指令契约.md 全指令清单。

【审查维度】：
① 定稿落地（关键验收点）：种植收获 GU-60/61+F-21（正式门槛/种子存在+seed 标记+空闲地块 默认3/harvest_at 定时/收获品质≥种子品质 quality_floor/继承特性 正式1精通2专家3 可配 超出丢弃/温室 大师复制）；代工 GU-62/63+F-22（精通门槛/能源道具 糖果类 可配/键值列表 parse_task_spec 代采=材料*数量,代调=配方*数量/后台 tick 离线累积/收取入包+队列清空/助手等级 produced_total）；装配接线（Router 全量注册含 M8 30+ 指令 /图鉴 单入口/ctx 引擎注入位/currencies 引用 player.currencies 就地落档/背包 dirty merge+实例通道保留品质特性/未注册安全空值）。
② 代码质量（bug/边界）：now 注入（壳层 time）；定时 4h 可配；队列容量/能源消耗原子性；dirty 标记不会误触发（只对实际背包变更）；落档 merge 幂等（无变更不 merge 不覆盖）。
③ 遗漏（验收点未覆盖）：2c4d 指令表/TC 未覆盖；装配接线缺口（battle_alchemy_engine 战斗注入仍未接？/协力 same_group）。

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8实现_批次D_jspace.md）：P0/P1/P2 分级+文件行号+修复建议；无问题维度确认（点名疑缺项已实现清单）。
最后回复：①门控档位②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
