# M8 契约审查 路C 任务文件（数据与校验子文档）

（本文件 = 审查角色卡 + 审查任务，拼入 dshx 命令执行）

---

（角色卡从 docs/审查/审查角色_初始化.md cat 拼入）

---

【使用 j-space 技能】：按 SKILL.md 唤醒→门控（full 档）→接缝审计→ship。

【重要：本环境无 bash 沙箱，禁止尝试运行任何命令/脚本/验证，只做静态文件审查；运行行为结论标'静态推导'。禁止子代理，独自完成。】
【预算纪律：本任务有 480 秒硬时限，必须优先落盘完整报告；验证性 grep 控制在 15 次内；接口签名核对用 read 直接定位真实函数，不必穷尽。】

【审查任务】M8 共享契约审查 路C（数据与校验子文档）——主 agent 自写契约对照审查：

审查对象：
- /root/QBot-TurnTellerRPG/docs/m8_contract_数据与校验.md（recipe/traits/proficiency/settings schema + 59 条校验规则，470 行，IF01~25）

对照基准（仓库内路径）：
- 细化修订版：docs/细化/细化_2c4b_宝石货币经济.md、细化_2c4c_珠与合成指令.md、细化_2c4e_品质与特性.md
- 定稿副本：docs/审查参考/炼金系统设计定稿.md（§10 数据结构 L348-426）
- 接口摸底：docs/m8_接口摸底.md（loader._KIND_FOR_MODULE/field_meta/validator 挂接）
- 仲裁：docs/仲裁/细化_0_仲裁决议汇总.md
- 批次：docs/m8_batch_plan.md

【审查维度】：
① IF 接口签名 vs 代码真实签名：契约引用的 Registry.resolve/InventoryEngine.add_item/remove_item/Repository 系列/reward 发放器 dispatch_reward/幂等设施 签名 read 真实代码核对
② 字段 schema vs 细化修订版 + 定稿 §10：recipe.json 全字段（kind/level/synth_allowed/master_only/materials/cost/slots/element_req/effects/traits_inherit/catalyst/combine_from/evolve_to）、traits.json 7 字段、proficiency.json、settings alchemy 全段（quality_tiers 键集 common/uncommon/rare/legendary、energy_enabled=false、catalyst_unlock_tier=expert、gem{分解 1/3/8/20,复制 0.2,...}、max_qty=2147483647）——逐字段核对是否与细化修订版/拍板一致
③ 校验器四件套：field_meta 登记（recipe/proficiency 新增、traits 已登记 L326-332）+ loader._KIND_FOR_MODULE + validator 专项（validate_recipes/validate_traits/validate_proficiency/_check_settings_alchemy 59 条规则）+ manifest——挂接方式是否按既有鸭子类型模式（validate_xxx(modules,report)）、规则红拦/黄提示分级是否合理
④ 跨文档一致性：与核心机制/指令契约/战斗资源子文档字段落点不冲突
⑤ 用户 5 项拍板 + R-07/R-08 落实（键集/平铺宝石/复制 cost.coins/无门槛珠升阶/int32 数量上限）
⑥ 缺漏：定稿 §10 要求字段未进契约、校验规则缺漏

输出报告（落盘 /root/QBot-TurnTellerRPG/审查_M8契约_路C_jspace.md）：P0/P1/P2 分级+契约文档:行号+证据行号+修复建议；无问题维度逐一确认。
最后回复：①门控档位 ②结论（P0/P1/P2 数量）③Top 3 问题（8 行内）。
