# 审查_M6实现_批1A_三引擎_jspace

> 门控档位：**full**（多文件跨读 + 单一可交付报告；采用 j-space 满档，ledger 全程在场）
> 方法：**纯静态代码审查**。本环境无 bash 沙箱，未执行任何命令/脚本/测试；所有「运行行为」结论一律为**静态推导**（逐行推演 + 领域类型核对），不构成运行验证。
> 范围（六文件）：`qbot_rpg/core/levelup.py`、`qbot_rpg/core/inventory.py`、`qbot_rpg/core/equipment.py`、`tests/unit/test_levelup.py`、`tests/unit/test_inventory.py`、`tests/unit/test_equipment.py`
> 参考契约：`docs/细化/细化_M6_三引擎与基础指令.md`（D1）：§一 LVL-01~12 / TC-LVL-01~06、§二 INV-01~11 / TC-INV-01~06、§三 EQP-01~12 / TC-EQP-01~06、§八 必测映射表。

---

## 〇、结论摘要

- **P0 = 0，P1 = 2，P2 = 9**（含 1 项 D1 文档勘误建议 + 2 处陈旧工程标注）。
- 三引擎已从空壳（原 `raise NotImplementedError`）实装完毕；18/18 验收用例全部落测试且**静态推演均可通过**；51 条规则中三引擎 35 条（LVL12+INV11+EQP12）逐条核对**已落地**，其中 2 条存在行为/边界缺陷（P1-1、P1-2），若干条为文档化偏移/半落点（P2）。
- 必测表（【规则】L293-295 三行）映射闭环：levelup→LVL-01/02/03/05+TC-LVL-01/02/03 ✓；inventory→INV-01/02/03/07/11+TC-INV-01/02/03/05 ✓；equipment→EQP-01/02/03/08+TC-EQP-01/02/06 ✓。
- EQP-12（/装备 换真实引擎）属命令壳装配层（basic_commands.py，本批六文件之外）——已核：`EquipmentEngineAdapter`（basic_commands.py L998-1091）包装真实 `EquipmentEngine` 并懒加载注入，适配层测试 `tests/unit/test_equip_adapter.py` 存在，P1-5③ 已闭环。

---

## 一、D1 契约落地逐项核对（维度①）

### 1.1 levelup（LVL-01~12）

| 规则 | 落地位置（levelup.py） | 核对 |
|---|---|---|
| LVL-01 经验曲线来源（内容包配置，缺省 100×lv，B-1） | `_normalize_curve` L83-108（callable/dict 表/缺省兜底） | ✓ 已落地；dict 表越界按 100×lv 兜底（工程补白 4） |
| LVL-02 0 经验边界（幂等拒绝 `exp_amount_invalid`，不抛异常） | `gain_exp` L148-149（bool/非 int/≤0 均拒） | ✓ TC-LVL-01 |
| LVL-03 满级不增长（静默丢弃，`{ok:True, level_ups:0, exp_next:0}`） | L153-159 | ✓ TC-LVL-02 |
| LVL-04 跨级判定（while 循环逐级） | L169-178 | ✓ TC-LVL-04（数值勘误见 P2-09） |
| LVL-05 升级回满（多级只在最后一级结算后回满一次，上限=重算后最终属性） | L183-199（calc_all_final_attributes 后取 hp/mp） | ✓ TC-LVL-03/04 |
| LVL-06 白值重算（growth 进白值层；换职业不重算） | L173-176（逐级累加进 attributes.base） | ✓ TC-LVL-05；与管线「base=工厂已算白值」口径一致 |
| LVL-07 SP 发放联动（`proficiency.<job_id>.sp_earned` +sp_per_level） | `_grant_sp` L117-128 | ✓ TC-LVL-03/04 |
| LVL-08 自由加点（注册表/amount≥1/非负） | `allocate_point` L211-241 | ✓ TC-LVL-06（重算链路缺联动见 P2-04） |
| LVL-09 返回值契约 `{ok,level,level_ups,sp_earned_delta,hp_restored,mp_restored,exp_next}` | L201-209 / L154-159 / L147-149 | ✓ 键集与契约一致 |
| LVL-10 存储事务（纯逻辑，零 IO） | 全文件无 IO/NoneBot import | ✓ |
| LVL-11 exp_next 口径（满级=0） | `exp_next` L110-115 | ✓ |
| LVL-12 战斗结算接缝 | 文件头工程补白 6 | ✓ 登记（装配层调用） |

### 1.2 inventory（INV-01~11）

| 规则 | 落地位置（inventory.py） | 核对 |
|---|---|---|
| INV-01 堆叠合并（同 id+实例键 null+同品质+同绑定；count≤stack_max） | `_mergeable` L99-111、`add_item` L207-219 | ✓ TC-INV-01（实例键以 stack_max 近似，见 P2-07） |
| INV-02 超上限拆行（满行+余量） | L220-224 | ✓ TC-INV-02 |
| INV-03 不可堆叠实例（独立行/恒 count=1/不合并不叠加） | L203-206 | ✓ TC-INV-03 |
| INV-04 remove 扣减与行清理（count=0 整行清理） | `remove_item` L285-298 | ✓ TC-INV-04/05b |
| INV-05 remove 不足/缺失拒绝（`not_enough`，不部分扣减） | L272-277 | ✓ TC-INV-04 |
| INV-06 count 统计口径（跨行求和，实例行按 1） | L300-313 | ✓ TC-INV-03 |
| INV-07 绑定（拒移；绑定/未绑定分开成行；add 按来源写绑定） | 扣减侧 L265-283 ✓；**add 侧「按来源写绑定」未落地**（见 P2-02） | ✓ TC-INV-05/05b |
| INV-08 单次入包数量上限（截断+提示「最多一次购买 99 个」） | L194-197、L242-243 | ✓ TC-INV-06/06b（数值勘误见 P2-09） |
| INV-09 背包格数上限（缺省不限；超→整单拒收） | L226-233 | ✓ 补充测试 test_supplement_inv_09 |
| INV-10 药剂到期惰性移除（任何背包操作；重算） | `_purge_expired` L118-141（add/remove/count 均前置调用） | ✓ 补充测试（重算钩子为半落点，见 P2-03） |
| INV-11 同类型回合限次钩子（potion_type 键+计数落点） | L50-52、`potion_type_of`/`potion_use_counts` L155-174 | ✓ 补充测试（判定归使用入口，契约口径一致） |

### 1.3 equipment（EQP-01~12）

| 规则 | 落地位置（equipment.py） | 核对 |
|---|---|---|
| EQP-01 穿戴校验链（占用→互斥→数量→穿上） | `equip` L262-291 | ✓ TC-EQP-01/02 |
| EQP-02 部位匹配（「这个位置穿不上」） | L256-260（以 ItemInstance.slot 代 type，B-3 口径） | ✓ TC-EQP-01 |
| EQP-03 互斥与数量校验（mutual_exclusions / max） | L263-291 | ✓ TC-EQP-02 |
| EQP-04 后装覆盖（新覆盖旧，旧件回包） | L298-309（替换 equipment 键即回包，槽内物品本就在背包） | ✓ TC-EQP-03 |
| EQP-05 unequip 回包（槽清空/回包/snapshot 移除；空槽拒绝） | `unequip` L321-358 | ✓ TC-EQP-04；**「写 ItemInstance.slot=null」偏离**（工程补白 2/8，有理由） |
| EQP-06 aggregate_bonus（flat/pct 同层求和→equip_snapshot） | `aggregate_bonus` L360-390 | ✓ TC-EQP-05；**同 item_id 多件双计缺陷（P1-1）** |
| EQP-07 属性全链重算（穿/脱→calc_all_final_attributes） | `_recalc` L209-218 | ✓ TC-EQP-04/05 |
| EQP-08 互斥环拦截（加载期 ValueError + 运行期人话拒绝） | `validate_slot_exclusions` L73-112 + equip L264-276 | ✓ TC-EQP-06 |
| EQP-09 战斗内不可穿脱 | L240-245 / L327-331（`player["in_battle"]`） | ✓ TC-EQP-06 |
| EQP-10 equip_search 预留签名（返回空+登记） | L392-404 | ✓ 补充测试 |
| EQP-11 装备层只进加成层（不写 temp） | aggregate_bonus 仅写 bonus；全文件无 temp 写入 | ✓ 补充测试 |
| EQP-12 命令壳适配（真实引擎注入） | 本批六文件外：basic_commands.py `EquipmentEngineAdapter` L998-1091、`_equip_engine` L1094-1112（懒加载兜底）| ✓ 已核存在（路B 交付物） |

### 1.4 必测表（§八）与指令承接

- 三行必测映射（levelup/inventory/equipment）**逐格勾闭**，见 §〇。
- §四/§五/§六 的 /注册（REG）、/状态（STT）、/快捷（SHC）为**基础指令承接**，属装配层/命令层，不在本批六文件范围；本批只交付三引擎。EQP-12 作为三引擎与命令壳的接缝已核闭（见 1.3）。

---

## 二、代码质量（维度②：P0/P1/P2 分级）

### P0（阻断级）
**无。** 静态核对：三引擎模块 import 链可解析（levelup/inventory/equipment 仅依赖 core/player_attributes、data/player、data/item，无循环依赖、无 commands/web 反向依赖，符合 G0 门禁）；`isinstance(x, typing.MutableMapping/Mapping)` 等运行期类型判断合法；grep 确认三文件 **0 处** `raise NotImplementedError` 残留（仅 levelup.py L12 注释提及 M1 空壳旧状）。

### P1-1　aggregate_bonus 按 item_id 回查背包行，同 id 多件并存时把「未穿戴行」词条也聚合进加成层（装备属性翻倍/错误）　【equipment.py L198-207 + L369-385】

**问题**：`_worn_rows` 以 `equipment` 槽实例的 `item_id` 匹配背包行，返回**所有**同 item_id 行（L207）。`aggregate_bonus` 对每件穿戴件遍历 `_worn_rows` 全部结果并求和（L369-378）。背包同时存在两把铁剑（stack_max=1，各自独立行）且只穿一把时，**另一把未穿戴的铁剑词条也被计入**加成层 → 最终属性翻倍/错误。同 item_id 不同品质/不同词条（如一把精炼 +7、一把白板 +5）时错误更明显；后装覆盖同 id 异词条（TC-EQP-03 用 mail_a/mail_b 不同 id，未触发）同样双计。文件头注释「同 item_id 多件的词条一致，任取皆等价」（L204-206）在品质/强化差异化后不成立。

**修复建议**：EquipmentSlot 增加「穿戴行身份」（行索引或实例键/生成键），穿戴时登记、`aggregate_bonus` 只聚合该行；或穿戴时对该行打行级标记（ItemInstance 为 frozen，需在槽实例侧存键）。至少应保证**每槽只取一件匹配行**而非全部。

### P1-2　unequip / 后装覆盖丢弃原 EquipmentSlot 的 slot_level/locked/gems（强化/镶嵌持久化数据丢失）　【equipment.py L298-309 + L339-348】

**问题**：B-3/F-20 下 `EquipmentSlot` 是强化等级/镶嵌宝石的唯一持久化落点（data/player.py L57-69）。`unequip` 直接 `del equipment[slot]`（L348），后装覆盖把 `equipment[slot]` 替换为新建 `EquipmentSlot(item_id, name)`（L309，slot_level=0/gems=()），原槽实例的 `slot_level/locked/gems` 全部丢弃；背包行 ItemInstance 又无强化字段（data/item.py 无 slot_level）。与代码自身意图自相矛盾：L305-307「同件重穿保留既有强化/镶嵌」只在槽实例仍驻留时成立——**先卸下再重穿即丢**。当前 强化/镶嵌 未接线故为潜伏，但字段已存在、一旦接线即数据丢失。

**修复建议**：卸下/覆盖时把原 EquipmentSlot 的强化/镶嵌字段写回背包行（为 ItemInstance 补 `slot_level/locked/gems` 字段或并入 stats 快照），重穿时恢复；或引擎内维护「item_id→最近槽实例」暂存。属 B-3 单向引用（槽→item_id）的固有缺陷，建议在数据模型层一次解决。

### P2 清单

- **P2-01　aggregate_bonus 全量重写 bonus 子层，抹除一切非装备加成层来源**　【equipment.py L386-389】：`attributes.bonus["flat"]/["pct"]` 直接整体赋值。契约 3b §1.1 L156 明确「战斗外药剂」也进加成层；任何此类来源在每次穿/脱后被抹除。当前全仓 `attributes.bonus` 唯一写入方=本函数（已 grep），故为潜伏；文件工程补白 4 亦自认「由装配层聚合后追加」。修复：改为对现有子层增量合并或提供外部追加接口。
- **P2-02　INV-07「add 时按来源写行级绑定」未落地**　【inventory.py add_item L179-244】：签名 `add_item(player, item, count)` 无 source 参数，绑定完全依赖调用方传入已 `bound=True` 的 item；按购买/奖励/掉落/锻造写绑定的职责被隐式委托给装配层，且**未在文件 工程补白 中显式标注**（扣减侧绑定拒移已标注，add 侧遗漏）。修复：补 工程补白 或为 add 增加 source→bound 映射参数。
- **P2-03　INV-10 惰性移除的「重算」钩子为空操作**　【inventory.py L136-141】：`calc_all_final_attributes` 为无副作用纯读（对三层求和返回，不写回），且引擎从未登记过期药剂的加成，移除后加成层也未撤销——调用结果不影响任何状态，仅测试以 monkeypatch 计数。属契约「到期自动移除重算」的半落点（文件已注明依赖装配层撤销加成）。修复：若加成撤销确在装配层，应在此显式留出「加成移除回调」接缝而非空调管线。
- **P2-04　allocate_point 改白值层后不触发全链重算**　【levelup.py L211-241】：与 gain_exp 内 `calc_all_final_attributes` 重算不一致；加点后最终属性直至下次 equip/升级/显式重算才刷新。契约未强制引擎重算，但建议保持同一重算纪律或显式注明「消费方需重算」。
- **P2-05　unequip 状态不一致兜底重建劣化物品**　【equipment.py L343-347】：背包无对应行时以 `quality="normal"/bound=False/stack_max=1` 重建，丢失原品质/绑定/词条/stats_bonus。文档已标注「装配层经 items 注册表补齐」，但引擎侧生成的劣化行可能直接落档。建议兜底行仅作临时占位或抛不一致标记。
- **P2-06　validate_slot_exclusions 对「冗余但可满足」的互斥组过度拦截**　【equipment.py L102-112】：并查集判环使 `[A,B]×2` / `[A,B]+[B,A]`（重复/镜像组，无实际约束冲突）也被判环拒绝。属可接受的保守策略，但注释「环」语义偏宽；如产品允许重复组应改「同组重复→忽略」。自环 A-A 判环正确（TC-EQP-06）。
- **P2-07　_mergeable 以 stack_max>1 近似「非实例行」**　【inventory.py L99-111】：契约 INV-01 的「同实例键（null）」被近似为 `stack_max>1`（文件注释已标注）。对将来「可堆叠但带实例快照」物品会误合并。建议后续在 ItemInstance 增加显式 instance_key 字段时修正。
- **P2-08　陈旧工程标注**：`core/dungeon.py` L27「InventoryEngine 为 M1 骨架，真实背包结算由批次 7 接线」——本批已实装，注释过时；`commands/basic_commands.py` L1110 报错文案「core/equipment.py（M1 骨架）」——引擎已实装，兜底报错文案过时（虽异常路径已几乎不可达）。
- **P2-09　D1 原文 TC 数值勘误建议**（非实现缺陷，测试注释已显式说明）：TC-LVL-04 原文「level=4 exp=395 +300」在默认曲线下仅升 1 级，测试改为 exp=600+500 以真正覆盖连升 2 级（行为断言与 D1 一致）；TC-INV-06 原文「99/51」与 B-4「截断作用于单次 add 的 count 参数」冲突，测试按 B-4 截断为 99 断言。实现侧均取更优口径，建议 D1 文档同步勘误避免后续误读。
- **P2-10　add_item 返回 `rows` 键语义误导**　【inventory.py L236-241】：`rows` 实为 `plan + working`（含全部既有行），非「新增行」。消费方若按 `rows` 计新增会误判；建议改为 `new_rows` 与 `total_rows` 分离。

### 2.1 操作对象=玩家状态 dict 的字段一致性（维度②专项）

- 三引擎**一致**以 ctx 玩家状态 dict（可变、就地改写）为操作对象，字段键与 `data/player.py`/`data/item.py` 领域类型一一对应：`level/exp/hp/mp/attributes/job_id/proficiency`（levelup）、`inventory`（list，元素 ItemInstance）+`attributes`（inventory）、`equipment`（dict，槽→EquipmentSlot）+`inventory`+`in_battle`（equipment）。与 checkin/quest/shop/reward 既有引擎的 dict 惯例一致。
- 重算链路：穿/脱→`aggregate_bonus`（写 bonus）→`calc_all_final_attributes`（写最终属性）自洽（P1-1 除外）；升级→growth 进 base→一次性全链重算→按最终属性回满，与管线「base=工厂已算白值」口径兼容（levelup L173-176 逐级累加 growth 进 base，非重跑白值公式，行为与 3b §4.4 一致）。
- 领域类型字段核对：`ItemInstance`（data/item.py L28-37）确有 count/quality/bound/stack_max/slot/stats_bonus；`EquipmentSlot`（data/player.py L57-69）确有 item_id/name/slot_level/locked/gems；`PlayerAttributes` 三层键空间（data/player.py L22-53）与引擎写入位置匹配。`expires_at`/`potion_type`/`stats_pct` 为 getattr 钩子（ItemInstance 现无字段），测试以 frozen 子类注入——落点合理、已注明。
- 持久化往返（`proficiency`/`potion_use_counts`/`equipment` dict 序列化）不在本批与 D6 存档往返之外验证——**登记为开放项**（归 D6）。

### 2.2 静态推演结论（未执行）

- 18 个 TC 测试（6+6+6）逐条按引擎代码路径推演：TC-LVL-01~06（含补充）、TC-INV-01~06（含 05b/06b/09/10/11 补充）、TC-EQP-01~06（含补充）**断言与实现一致，均可通过**（含 monkeypatch 计数、子类钩子、approx 浮点断言）。此为静态推导，非运行结果。
- 未发现 import/语法级阻断（P0=0）。

---

## 三、遗漏与工程补白（维度③）

- **TC 覆盖**：D1 §1.4/2.4/3.4 共 18 例**全量落测试**（无 TC 空档）；补充测试另覆盖 INV-09/10/11、EQP-08 自环、EQP-10/11、slots.json 包装形态、曲线表越界兜底。§八 必测表逐格闭环。
- **规则覆盖**：LVL-01~12 / INV-01~11 / EQP-01~12 全部落地（35/35）；2 处行为缺陷（P1-1/P1-2）、若干文档化偏移/半落点（P2）见 §二。
- **工程补白标注质量**：三文件均以「【工程补白】」显式标注 操作对象 dict 化 / 配置注入兜底 / B-3 槽位引用差异 / equip_snapshot=bonus 语义 / 战斗态写入 / 互斥环校验器 等契约偏离与取点，标注充分、不冒充定稿行号，符合 D1 变更纪律。个别未标注项见 P2-02。
- **指令承接（REG/STT/SHC）**：不在本批交付物；EQP-12 适配器与测试已在命令层确认存在（P1-5③ 闭环），/注册 等指令 handler 的实装归属后续批次，本批无可判项。
- **互斥环校验器的 3e 注册**：`validate_slot_exclusions` 为独立函数已提供；内容包 loader/validator 是否调用（D1 §八 口径说明「3e 校验器注册」）不在本批文件，登记为接缝待核项。

---

## 四、无问题维度确认

- 维度①（D1 契约落地）：三引擎 35 条规则 + 18 例 TC **确认实现且行为一致**（除 §二 列出的 2 项缺陷与文档化偏移外，无整条规则缺失、无凭文件名脑补的空壳残留）。
- 维度②（空壳残留）：grep 确认三文件 0 处 `raise NotImplementedError`；M1 骨架签名（gain_exp/allocate_point/add_item/remove_item/count/equip/unequip/aggregate_bonus/equip_search）全部保留且未破坏既有注入测试（FakeEquipEngine 注入路径仍可用）。
- 维度③（工程纪律）：变更均标 工程补白/细化取点，无冒充定稿行号；P 项承接（P1-5①④ 引擎与测试已闭环，②/③ 命令壳与装配层在命令层确认）。

---

*报告生成方式：j-space full 档静态审查；运行行为结论全部为静态推导（未执行任何命令/测试）。文件行号以审查时读取为准。*
