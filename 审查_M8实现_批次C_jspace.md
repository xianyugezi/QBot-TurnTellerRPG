# 审查报告 · M8 炼金实现 批次C（珠+复制+深度+图鉴+战斗即时调合，5 文件）

- 审查对象：`qbot_rpg/core/jewel.py` / `alchemy_register.py` / `alchemy_deep.py` / `alchemy_meta.py` / `alchemy_battle.py`
- 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/验证）；所有"运行行为结论"一律标注 **静态推导**。
- 合同依据：`docs/m8_contract_指令契约.md`（§6-8/11-20/23）、`docs/m8_contract_战斗资源.md`、`docs/细化/细化_2c4b/2c4c/2c4d`、拍板④⑤。
- 方法：验收点逐条对账（任务给定预期结论当"假设"核验，非既成事实）；外部 API 签名与配置键用 grep/read 抽查核验（计数落点 battle_alchemy_used 已到 core/battle.py 与装配层交叉确认）。

## 结论摘要

| 级别 | 数量 | 概要 |
|---|---|---|
| P0 | 0 | 无阻断性正确性缺陷（无合同数值/常量错误、无常路径崩溃） |
| P1 | 2 | ① 登记/复制大师门槛（DUP-01）实现不一致——`/登记` 无门槛、引擎无 tier 校验；② `DeepEngine.evolve_unlock` 材料扣除无引擎内快照-回滚（ATO-01 严禁部分执行） |
| P2 | 6 | 见逐文件清单（拆珠不转发 quality/traits、配置非法值防御、快照判定宽松等） |

---

## 一、P1（2 项）

### P1-1 登记/复制 大师门槛（DUP-01/GU-34）引擎缺失 + 壳层不一致
- **文件/行号**：`alchemy_register.py` L409-413（`register` 签名）、L532-538（`copy` 签名）——两入口**均无 player/职业参数、无 tier 校验**；`alchemy_commands.py` L1912-1927 `cmd_register` 注释明确「无职业门槛」，L1931-1946 `cmd_copy` 才有大师门槛。
- **合同**：指令契约 L42 指令表第 11 行「/登记 /复制 守卫=大师 + 宝石/材料全量」，L159 GU-34「炼金职业 ≥ 大师」。即 `/登记` 与 `/复制` 均应大师门槛。任务验收点亦点名「大师门槛」。
- **影响（静态推导）**：`/登记`（模板成本快照冻结 + 登记表落点）可被任意职业调用，绕过 GU-34；与同批 DeepEngine（`deep_eligible`/`evolve_eligible` 引擎内判档）、BattleAlchemyEngine（`instant_eligible` 引擎内判档）的"引擎内门槛"模式不一致；引擎侧零校验使壳层漏加即全线裸奔。另 DUP-01「SP 可解锁替代」仅出现在模块 docstring，引擎/壳层均未见消费（SP 面板"解锁 复制"分支是否被 cmd_copy 认领未核验——见遗漏③）。
- **修复建议**：① 引擎 `register`/`copy` 增加可选 `player`/`job_id` 参数 + `tier gate` helper（对齐 deep/battle 模式），壳层统一调用；② 壳层 `/登记` 补大师门槛（对齐 GU-34）或由契约/细化确认「登记无门槛、复制有门槛」后显式修正契约表述（二选一，勿留隐式差异）。

### P1-2 `DeepEngine.evolve_unlock` 材料扣除无引擎内快照-回滚（ATO-01 严禁部分执行）
- **文件/行号**：`alchemy_deep.py` L567-569——`for m in need: if not _hook_ok(remove_item(...)): return 失败`，循环**中途任一 remove 失败即直接返回，先前已扣材料不回滚**；L570-573 宝石/金币扣除亦无失败回滚路径（此处逻辑上不会失败）。
- **对比**：同批 `alchemy_register.py` L625-643、`alchemy_battle.py` L493-531 均含 `_snapshot`/`_restore` 引擎内原子回滚；`evolve_unlock` 缺此机制，仅靠 docstring「同事务由壳层包裹」。
- **影响（静态推导）**：正常时前置全量校验（`_ctx_have` L529-541）可防；但 count_item 与 remove_item 两 hook 口径不一致（引擎内已有此类测试先例 test_quest L479）时，`evolve_unlock` 会留下"已扣 1/N 份材料 + 宝石已扣"的部分状态，违反 ATO-01「严禁部分执行/部分扣除」，且无 any 错误标记提示调用方需回滚。
- **修复建议**：扣料前 `_snapshot`（currencies+inventory，对齐 register/battle），循环任一失败 `_restore` 后返回 `materials_remove_failed`。

---

## 二、P2（6 项）

### P2-1 无损拆珠不转发 quality/traits（SOCK-03 原档/原特性/原堆叠键返还）
- **文件/行号**：`jewel.py` `_add_jewel` L415-424（`add_item(jewel_id, count, True)`，仅 3 参）；调用点 `unmount` L662。
- **依据**：装配层 `assembly/context.py` L749-768 `add_item(item_id, count, bound, **kw)` 已支持 `quality/traits` 关键字（实例通道）；`alchemy_settle.py` L331、`alchemy_battle.py` `_into_pack` L756-758 均已传 quality/traits，jewel 是唯一漏传的引擎。
- **影响（静态推导）**：常规珠（def 固定）经 def 重算堆叠键往返无损；但换包后 def 变更、或品质实例珠（走 inventory_instances 通道）拆下时，原档/原特性不会经实例通道保留，堆叠键按当前 def 重算 → 与 SOCK-03「原堆叠键/原特性返还」存在偏差。
- **修复建议**：`_add_jewel` 透传快照 `quality`/`traits`（可带 `stack_key`）给 add_item。

### P2-2 `mount` 特性集归一假定 list（str 特性会按字符拆）
- **文件/行号**：`jewel.py` L574 `traits = [str(t) for t in (jewel_def.get("traits") or [])]`。
- **影响（静态推导）**：若内容包把 traits 存为字符串（如 "火焰"），会拆成 ["火","焰"] 使 BEL-15 堆叠键错；`alchemy_battle.py` `_def_traits` L702-712 已处理 str 形态，jewel 未对齐。
- **修复建议**：复用 str→[整串] 的归一逻辑（对齐 `_def_traits`）。

### P2-3 配置/外部值非法时可能抛异常（违反「不抛异常」铁律）
- **文件/行号**：
  - `alchemy_meta.py` L197-205 `_reward_table`：`sorted(rows, key=lambda r: int(r.get("lit", 0)))`——`lit` 为非数字串（如 "abc"）时 `int()` 抛 ValueError。
  - `jewel.py` L729 `n = bucket.get(jewel_id, 0)` 后 `n >= limit`、L754 `int(bucket.get(...))`——战斗快照桶被外部写入非 int 值（如 str）时抛 TypeError。
- **影响（静态推导）**：仅在非法配置/外部污染时触发；正常数据不可达。但引擎铁律为「不抛异常（防御降级返回 dict）」。
- **修复建议**：`_reward_table` 用 try/except 跳过非法 lit；jewel 用 `_to_int` 归一 bucket 值。

### P2-4 深度会话判定与 challenge 子态标记宽松/悬空
- **文件/行号**：`alchemy_deep.py` L618-620 `_is_deep_snap`：`session_type==CHALLENGE_SESSION or "core_slot" in snap`——普通炼金快照若带同名键即误判为深度会话（buff/mount_core/challenge_settle 全部放行）；L414 `snap["challenge"]=False` 在引擎内无任何处置置 True 处（子态标记悬空，依赖壳层设置）。
- **影响（静态推导）**：误判风险低（快照结构受控），但纯凭键存在判定与 MUT-07「session_type 分离」的强语义不一致；`challenge` 标记无人消费会误导后续结算读方。
- **修复建议**：仅以 `session_type == CHALLENGE_SESSION` 判定；`challenge` 置 True 由 challenge 开启处（壳层或引擎入口）显式完成。

### P2-5 复制材料清单仅支持 list 形态
- **文件/行号**：`alchemy_register.py` L393-404 `copy_cost` 材料解析仅处理 list；`{id: count}` dict 形态不解析（materials 静默为空 → 复制只扣宝石、材料免扣）。
- **影响（静态推导）**：数据契约 §1 规定 `materials=[{id|item, count}]`（list），故正常数据不触发；但 dict 形态作为防御缺口存在（deep/battle 均兼容 dict 兜底，register 未对齐）。
- **修复建议**：`copy_cost` 增加 dict 形态解析（对齐 `DeepEngine._normalize_materials`）。

### P2-6 `battle._materials` 将 count≤0 强制归一为 1
- **文件/行号**：`alchemy_battle.py` L594-599 `max(1, n)`——配方某材料 count=0（内容包若以 0 表免费）会被强制扣 1 份。
- **影响（静态推导）**：与 register（cnt>0 才计）/deep（`_normalize_materials` max(1) 同款）不一致；正常配方 count≥1 不可达。低风险防御选择。
- **修复建议**：统一口径（要么全链路跳过 ≤0，要么全部 max(1)），并注明内容包约束。

---

## 三、无问题维度确认（点名疑缺项 → 已实现核验清单）

以下为任务点名"疑缺项"，经逐条静态核验**均已实现**，无遗漏：

1. **珠系统 BEL-03 槽级映射**：`jewel.py` `slot_accepts` L198-216——槽级 3 全放行（含传说）、1 级=普通（index<1）、2 级=精良及以下（index<2），逐档核验与 BEL-03 一致。✅
2. **BEL-15 堆叠键**：`stack_key` L218-238 = `ID|品质档|排序去重特性`，同键可堆叠、键变分堆。✅
3. **BEL-10 同名递减 1.0/0.5/0.25**：`diminish_mult` L240-268 表驱动，1/2/3 颗=1.0/0.5/0.25，第 4 颗及以上 0.0（"不叠加"口径，注释明示）；0/空配置→恒 1.0。✅
4. **BEL-11 触发上限 3 可配**：`trigger_limit` L270-280 默认 3、`settings.alchemy.战斗道具.珠触发上限` 可配（test_demo settings.json L150=3 吻合）；计数落 `battle_snapshot.jewel_triggers`（与 battle_alchemy_used 同层，J-3）。✅
5. **SOCK-05 战斗中不可插拔**：`can_toggle_in_battle` L318-324 + mount/unmount 首闸 L475/L626。✅
6. **登记复制 ⌊cost.coins×20%⌋**：`copy_cost` L392 `math.floor(coins×rate)`，费率默认 0.2（settings L193 吻合），只算 coins；额外消耗 AR-4（L403）。✅
7. **DUP-02 先登记后复制 / DUP-04 仅标准版 / DUP-05 上限提示不拦 / DUP-06 登记持久化**：`copy` L567 未登记拒、L311-327 `is_copyable`（traits/awaken/evolution/core 非空拒）、L586-590 超限 advisory+截断、`register` L450 落 `ctx["registered"]`。✅
8. **深度炼金**：`deep_eligible`（大师解锁，TC-14）✅；`deep_snapshot`（6 槽/核心槽/3普通+1金/进化线，D-10）✅；`evolve_eligible`/`evolve_unlock`（宗师门槛=5、炼金产出 N 次合成不计、永久解锁写 `upgrade_unlocks`、`traits_inherited=False` 特性不继承、已解锁幂等 ATO-05）✅；`mount_core`（大师+深度+核心物品+与配方适配+品质上限+X+可换 COR-02）✅；`buff`（宗师限 1 次/调合 buff_used）✅；`challenge_check`/`challenge_settle`（连锁≥5 刻度≥2 可配 and/or、成功上限+10、失败降级+退 50% 只一次 ATO-06）✅。
9. **图鉴 AlchemyMeta**：`codex_summary`（点亮进度/全亮）✅；`codex_reward`（成长奖励幂等 claimed 集合）✅；`king_eligible`（TTL-01 图鉴全亮→prof.grant_king_title 透传）✅；`skill_panel_view`/`skill_panel_unlock`（SP 自选解锁 6 分支透传）✅；`tutorial_catalog`/`tutorial_show`（教学目录）✅；`master_announcement`（升大师 6 机制预览，DEEP_MECHANISM_NAMES L83-85）✅。**codex 分母已核**：`codex.py` L49 CATEGORIES 已含 `alchemy:("recipe","item")`，与 meta `ALCHEMY_KINDS` 一致，非 bug。✅
10. **战斗即时调合 BA-01~10**：`instant_eligible`（战斗中/大师/能量/限次 默认 1）✅；`carry_ok`（素材全量、全拒+差异 ATO-01）✅；`cooldown_of`（配方>output>默认 3）✅；`intensity`（技能×(1+0.4×冷却)，系数可配，settings L149 吻合）✅；`resolve`（一步出结果：原子校验→快照→能量→扣料→扣宝石→产出实例→auto_use 或入包→计数+1）✅；`battle_alchemy_used` 顶层键：engine 提供 `BATTLE_ALCHEMY_USED_KEY`/read/write（L99/L251-265），且 **core/battle.py L922 快照初始化 0、L1782-1789 有累计写入**——双落地已交叉确认，中断不清零/战斗结束清零归战斗层（BA-02 语义）。✅
11. **确定性种子（/协力 防 PYTHONHASHSEED）**：批次 C 5 文件**无 hash 序敏感输出**（所有 dict/set 迭代均以计数/排序归一：stack_key 显式 sort、reward 表按 lit 排序、材料清单保序），静态推导无 PYTHONHASHSEED 依赖；`/协力` 随机加成不在本批次（壳层 cmd_assist，批11），未见其随机源。✅
12. **强度公式/冷却/限次配置与 test_demo settings 全量吻合**：战斗道具{强度公式,珠触发上限}、战斗即时调合{auto_use:true,per_battle_limit:1}、max_qty=2147483647、gem.复制/复制额外——grep 核验一致。✅

---

## 四、遗漏与未覆盖（验收点/TC 矩阵）

1. **DUP-01「SP 可解锁替代」**：引擎与壳层均未见对"SP 解锁复制"的消费路径（SP 面板分支 F-19 存在"解锁 复制·进化·挑战"，但 cmd_copy 的大师门槛未见 SP 豁免）。壳层接线需确认/补测——列入 P1-1 一并跟踪。
2. **/协力（2c4d #15）**：契约附注① 明示批8/批11 排期、非本批次；本批次引擎文件不含（壳层 cmd_assist 已在 alchemy_commands.py）。非遗漏。
3. **珠三合一升阶（BEL-12）**：jewel.py 明确"升阶执行=复用 UpgradeEngine，本引擎不做"——设计内分派，非遗漏；执行器在 core/upgrade.py（批2）。
4. **TC 矩阵覆盖**：5 引擎对应单测文件均存在（tests/unit/test_jewel.py / test_alchemy_register.py / test_alchemy_deep.py / test_alchemy_meta.py / test_alchemy_battle.py，另 test_deep_commands.py）；本静态审查未执行测试，TC 通过率不可断言（运行结论须回归验证）。建议对 P1-1（登记无门槛）与 P1-2（部分扣除回滚）补 TC。
5. **2c4b/2c4c/2c4d 规则级**：宝石经济（2c4b）非本批次引擎职责；2c4c 的 DUP/BEL/SOCK 族已逐条对账；2c4d 战斗即时调合/图鉴/教学/挑战已对账。未发现本批次职责范围内规则遗漏（除 P1-1 门槛差异）。

---

## 五、审查方法与可信度说明

- 本报告所有"运行行为"结论均为**静态推导**（未执行任何命令/脚本/测试）；涉及外部 hook 一致性、装配接线、配置热更路径的结论以"需壳层确认"标注。
- 引用抽查采用 read 直接定位（contract 62 处匹配、assembly context add_item 签名、core/battle.py 快照落点、settings.json 配置键、codex.py CATEGORIES），验证性 grep 共 12 次（≤15 预算）。
- 上下文：P0=无；P1=2；P2=6。
