# 审查_M6实现_批1B_三指令（/注册 /状态 /快捷 + /装备 适配层）— j-space

> 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试；所有运行期行为结论均标注【静态推导】，未经执行验证）。
> 审查文件：
> - `qbot_rpg/commands/register_commands.py`（/注册，REG-01~06 / TC-REG-01~05）
> - `qbot_rpg/commands/status_commands.py`（/状态，STT-01~05 / TC-STT-01~03）
> - `qbot_rpg/commands/shortcut_commands.py`（/快捷解绑 /快捷列表，SHC-01~05 / TC-SHC-01~03）
> - `qbot_rpg/commands/basic_commands.py`（聚焦 **EquipmentEngineAdapter L998-1112** + cmd_help 别名消费 `_command_alias_display` L1369 + `_group_summary` L1406 + `_render_help_group` L1440）
> - `qbot_rpg/commands/parsers.py`（DEFAULT_WHITELIST 补「注册」）
> 参考契约：`docs/细化/细化_M6_三引擎与基础指令.md`（D1）§四~§七；`docs/细化/细化_4f_基础指令组契约.md`（RUL-01~15/CMD-06~08/TPL-4F-01~12/TC-01~10/17/22/23）。
> 关联核对：`core/equipment.py`（路A 引擎）、`data/item.py`、`data/player.py`、`commands/router.py`、`commands/sender.py`、`core/message_format/list_render.py`、`core/player_attributes.py`；配套测试 `tests/unit/test_register_commands.py` / `test_status_commands.py` / `test_shortcut_commands.py` / `test_equip_adapter.py`。

---

## 〇、结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| **P0** | **0** | 无覆盖验收 TC 直接失败、无数据损坏级缺陷 |
| **P1** | **3** | 固定子词吞名错位 / 穿装序号与背包显示序错位 / 适配层数据形态接缝不闭合 |
| **P2** | **11** | 契约保真度与代码质量（印记区缺失 / 保留字符黄提示部分实现 / 吞异常 / 别名备选形态等） |

- 三组指令（REG/STT/SHC）的**验收 TC 全部有配套单测且实现与 D1 承接口径一致**【静态推导：测试断言与实现文案逐字对齐】；未发现覆盖 TC 层面的 P0。
- 装配接线（make_context 注入 / save_player 事务 / message_prefix 叠加）仍按全局代码库约定归**批次7**（与 basic/checkin/gm/shop/quest/explore 全部 register_* 同态【待接线】），本批三模块保持一致，非本批缺陷。

---

## 一、维度① D1/4f 契约落地核对（逐条）

### 1.1 /注册（REG-01~06 / TC-REG-01~05；承接 4f TC-01~04/06）

| 契约 | 实现落点 | 判定 |
|---|---|---|
| REG-01 语法 ≤2 参 / TPL-12 | register_commands.py L414-420（error / fixed_subword / 缺名超参 → format_tpl12） | ✅ 一致 |
| REG-02 ① ≤20 字硬拦 | L99 TPL_NAME_TOO_LONG + L145-146 `len(name) > MAX_NAME_LEN` | ✅ 一致（TC-REG-05） |
| REG-02 ② 控制字符过滤 | L147-149 ord<0x20/0x7f → TPL_NAME_BAD_CHARS | ✅ 一致 |
| REG-02 ③ 保留字符黄提示 | L458-459 `reserved_char_hint` 尾缀 | ⚠️ **部分实现**：仅 `+ , =` 能存活到黄提示；空格/`*`/`/` 在解析层即 TPL-12 硬拦（详见 P2-2） |
| REG-03 重名红拦 | L450-456 `ctx["name_exists"]` → TPL_DUP_NAME（`❌ 已经有一个叫『xx』的角色了，换个名字吧`） | ✅ 与 TC-REG-03 逐字一致 |
| REG-03 已注册幂等 | L423-428 `ctx.get("registered", True) is True` → TPL_ALREADY_REGISTERED（L103-105，`❌ 你已经注册过了，当前角色：…`） | ✅ 与 TC-REG-04 / RUL-09 一致；幂等先于名字校验（L422 注释） |
| REG-04 缺省职业链 B7 | L203-220 `default_job`：settings.default_job_id → 首个 recommended_newbie → jobs 首职业；无效 default_job_id 防御续链 | ✅ 与 B7/TC-REG-02 一致 |
| REG-04 初始属性/位置 | L239-260 `_initial_base`（stats base + 100/30/10 兜底）、L263-273 `_initial_location`（default_map → 新手村） | ✅ 与 RUL-05/06 一致 |
| REG-05 注册门槛联动 | L464-466 `ctx["registered"]=True`；门槛本体由各 handler `_gate` 消费 TPL_REGISTER_GATE | ✅（见 1.4） |
| REG-06 ① 独立模块+路由注册 | L475-495 `register_register_commands` → `CommandSpec("注册")` | ✅ |
| REG-06 ② DEFAULT_WHITELIST 补「注册」 | parsers.py L116 `"注册"`（基础指令组块内） | ✅ **已补**（同时「状态」L114、「快捷解绑/快捷列表」L119 均在） |
| REG-06 ③ 建号事务 | 归批次7 make_context（本 handler 零 IO，L461-466 只写 ctx） | ✅ 按批次约定 |
| TPL-4F-01 成功模板 | L310-343 `render_register_success`：`Lv1.{名} - -` → `✅ 注册成功！…` → 职业/位置 → 初始属性 → 引导行 | ✅ 与 TC-REG-01 行序一致；🟢 按 M5 裁决降级「（推荐新手）」已在模块头标注 |
| 职业不存在文案 | L111 TPL_JOB_NOT_FOUND + L223-236 `_available_jobs`（`战士（推荐）…`） | ✅ 与 RUL-03 语义一致（无 emoji） |
| emoji 纪律 | 全模块仅 ✅/❌；test_register_commands L275-291 逐字符扫描 | ✅ |

### 1.2 /状态（STT-01~05 / TC-STT-01~03；承接 4f TC-07/09/10）

| 契约 | 实现落点 | 判定 |
|---|---|---|
| STT-01 面板五区 | status_commands.py L331-341：prefix → level → attr → location → effects | ✅（印记区缺，见 P2-1） |
| STT-02 等级/经验行 | L218-235 `level_line`：`【等级】3 ｜ 经验 320/1000`；满级 `【等级】45【已满级】`（level≥cap 或 exp_next==0，LVL-11 口径） | ✅ 与 RUL-11 一致 |
| STT-03 属性行最终层 | L238-249 `attr_line`：`_final_attrs`（ctx["attr_final"] 直取 → calc_all_final_attributes → resolve_attr_final 兜底）→ `【生命】cur/max ｜ 【魔力】… ｜ 【攻击】str ｜ 【防御】con` | ✅ 与 RUL-12/工程补白 2 一致；M6 路B 修复（L176-178 空 PlayerAttributes 不入管线）已注释 |
| STT-03 效果区前 5 + 还有N | L277-292 `effects_line`：`【效果】中毒 2/3（来源：…）`、>5 → `还有 N 个状态`、无 → `【效果】无` | ✅ 与 TC-STT-02 / RUL-13 一致 |
| STT-04 战斗内目标行 | L295-305 `target_line`：`【目标】史莱姆 18/30（第 3 回合）`；L337-339 追加于位置行后 | ✅ 与 TC-STT-03 / TPL-4F-03 行序一致 |
| STT-05 ① 模块+纯函数 | L312-341 `cmd_status`；无参才渲染，带参/解析错误 → TPL-12 | ✅ |
| STT-05 ② 路由注册 | L348-368 `register_status_commands` → `CommandSpec("状态")` | ✅ |
| STT-05 ④ 未注册门槛（非豁免） | L102-107 `_gate` → TPL_REGISTER_GATE | ✅ |
| 前缀行 | L208-215 `prefix_line`：`Lv3.阿伟 -斩龙者-` / 空称号 `- -` | ✅（TC-08 不在承接范围，settings.format 跟随归批次7，工程补白 1） |

### 1.3 /快捷（SHC-01~05 / TC-SHC-01~03；承接 4f TC-22/23/17）

| 契约 | 实现落点 | 判定 |
|---|---|---|
| SHC-01 解绑 | shortcut_commands.py L137-157 `cmd_shortcut_unbind`：恰好 1 参，不存在 `❌ 没有绑定『xx』`、成功 `✅ 已解绑『xx』`、就地删 ctx["shortcuts"] | ✅ 与 CMD-07/TPL-4F-10/TC-SHC-01 逐字一致 |
| SHC-02 列表 | L160-202 `cmd_shortcut_list`：头 `【快捷（N/20）】` + `快捷名 → 指令串`；空表 `❌ 还没有快捷绑定，试试 /快捷绑定 1 攻击` | ✅ 与 TPL-4F-11/TC-SHC-02 一致 |
| SHC-02 分页横切 | L186-201：5 条/页 + `resolve_page` 夹取（裁决②）+ CakeGame 尾段 | ✅（页码为工程补白 2 扩展，已标注） |
| SHC-03 持久化 | L182-201 只读写 ctx["shortcuts"]；落档归装配层（SHC-03 零 IO） | ✅ 按架构约定 |
| SHC-04 帮助别名替换 | basic_commands.py L1369-1395 `_command_alias_display` + L1406-1413 `_group_summary` + L1440-1462 `_render_help_group` 消费 settings.command_aliases | ✅ 主形态一致（备选形态见 P2-7） |
| SHC-05 ① 模块+路由注册 | L209-233 `register_shortcut_commands` → `CommandSpec("快捷解绑"/"快捷列表")` | ✅ |
| SHC-05 ④ 白名单已含 | parsers.py L119 | ✅ |
| 覆盖重绑（TC-SHC-01 前半） | 归 router.check_shortcut_binding（既有机制，本层不重定义） | ✅ |

### 1.4 横切契约

| 契约 | 判定 |
|---|---|
| RUL-08 未注册门槛 | 4 处 handler（/角色 /背包 /装备 /技能 /状态 /快捷解绑 /快捷列表）均 `_gate` 消费 TPL_REGISTER_GATE；/帮助 豁免 B6 | ✅（默认 True 风险见 P2-10） |
| B6 /帮助 豁免注册引导版 | basic L215-221 `_REGISTER_GUIDE` + L1477-1479 | ⚠️ 引导版列出「角色」而非 B6 原文「状态」；解析错误先于引导返回（见 P2-6） |
| TPL-12 统一 | 四模块全部经 `sender.format_tpl12`（fragment 截 20 字） | ✅ |
| emoji 纪律（仅✅❌） | 四模块渲染输出仅功能性标记；🟢 降级纯文本「（推荐新手）」有测试扫描 | ✅ |
| D1 §七 P1-2（DELAYED 收口） | 三组指令模块/路由注册函数/TC 单测均落地（pytest 载体），装配待批次7 | ✅ 承接成立 |
| D1 §七 P1-3（冒烟依赖 /注册） | `cmd_register` 真实 handler + `register_register_commands` 已交付；冒烟执行依赖批次7 装配 | ✅ 承接成立（接线时序一致） |
| /装备 换真实引擎（EQP-12/P1-5③） | basic L998-1091 EquipmentEngineAdapter 包装 core EquipmentEngine；`_equip_engine` 注入优先 → 懒加载兜底（L1094-1112） | ✅ 主路径成立（接缝细节见 1.5） |

### 1.5 /装备 适配层（EquipmentEngineAdapter L998-1112）专项

| 项 | 落点 | 判定 |
|---|---|---|
| 消费接口签名 equip_wear(index, ctx) / equip_remove(slot_id, ctx) → {ok, message} | L1034-1053 / L1055-1073 | ✅ 与 FakeEquipEngine 替身签名对齐（test_basic_commands L132-148） |
| 目标槽 = ItemInstance.slot（EQP-02 口径） | L1045-1047 `item.slot` | ✅ 与引擎部位匹配一致 |
| 失败透传 + reason 兜底人话（EQP-E1~E5） | L1075-1091 `_fail_message` 覆盖 slot_mismatch/mutual_exclusion/empty_slot/in_battle/item_not_found/unknown_slot/max_reached | ✅ 与 EQP-E1~E5 文案一致 |
| 战斗内不可穿脱（EQP-09） | 引擎 `player["in_battle"]` 判定 → 透传「战斗中不可更换装备（战前换装）」 | ✅ |
| 后装覆盖/卸装回包 | 引擎 EQP-04/05 语义经 `res["replaced"]` → `（已替换原装备并回包）` | ✅ |
| 玩家缺失提示 | L1037-1038 / L1058-1059 → 「❌ 玩家状态缺失（请先 /注册 创建角色）」 | ✅ |
| **序号语义（与 /背包 显示序一致性）** | L1042 `inv[index-1]` 取**原始存储序**；/背包 `_inventory_rows`（basic L510-529）按 acquired_at 倒序展示 | ❌ **P1-2**（穿错物品） |
| **行数据形态（ItemInstance vs 4a dict 行）** | L1043-1046 `isinstance(item, ItemInstance)` 硬校验；/背包 `_row_fields`（L547-570）显式兼容 dict 行 | ❌ **P1-3**（接缝不闭合） |
| **属性形态（PlayerAttributes vs dict）** | 引擎 `aggregate_bonus`（equipment.py L401-405）`attributes.bonus["flat"]=` 要求 PlayerAttributes；若装配给 dict 形态 attributes → AttributeError【静态推导】 | ⚠️ 并入 **P1-3** |
| 异常吞没 | `_cmd_equip_wear/_cmd_equip_remove`（L1118-1122 / L1128-1132）`except Exception: res={}` → 一律「❌ 装备失败」 | ⚠️ **P2-3** |
| 槽位名渲染与引擎配置形态一致性 | `_slot_name`（L895-906）不认 slots.json 包装形态 `{"slots":{…}}`（引擎构造认包装形态，equipment.py L148-155） | ⚠️ **P2-8** |

---

## 二、维度② 代码质量发现（bug / 边界 / ctx 契约 / parsed 参数 / TPL-12 / emoji）

### 2.1 P1-1【register_commands L416-419】固定子词吞名导致角色名静默错位
- **现象（静态推导）**：`/注册 自动 战士` 经解析后 `parsed.fixed_subword="自动"`、`args=["战士"]`（FIXED_SUBWORDS 在槽位 0 被抽离，parsers L477-479）。`cmd_register` 的 fixed_subword 分支仅拦「有子词且无 args」（L416-417），故落穿到 `name = str(args[0])`（L430）→ **注册名变成「战士」**（job 参数被当成名字，job 再走缺省兜底），意图名「自动」被静默丢弃。同一名字 `/注册 自动`（无 job）则走 TPL-12 —— 同一名字两种行为不一致。
- **影响**：产生与玩家意图不符的角色名（静默错误建号），且可绕过预期命名校验。
- **修复建议**：`cmd_register` 中若 `parsed.fixed_subword` 非空，将 fixed_subword 拼回名字（`name = f"{parsed.fixed_subword}{name}"`）或直接对含固定子词的首参走 TPL-12/黄提示；并补 `/注册 自动 战士` 单测。

### 2.2 P1-2【basic_commands L1042 vs L510-529】穿装序号与背包显示序错位（穿错物品）
- **现象（静态推导）**：/背包 展示按 `acquired_at` 倒序（RUL-17 要求，`_inventory_rows` L527 `sorted(..., reverse=True)`），玩家按 /背包 看到的序号（如 1=最近获得）输入 `装备 穿 N`；但适配层 `equip_wear` 用**原始存储序** `player["inventory"][index-1]`（L1042）。存储序 ≠ 展示序时（增删/合并/换包加载后几乎必然），会穿到**另一件**物品。
- **影响**：错误穿戴（用户可见错误行为）；test_equip_adapter 因构造时存储序恰为展示序而未暴露【静态推导】。
- **修复建议**：适配层 `equip_wear` 与 /背包 共用同一排序函数（按 acquired_at 倒序后取 index-1），或由 cmd_equip 传入已排序行视图；补「存储序≠时间序」的适配器单测。

### 2.3 P1-3【basic_commands L1043-1046 + equipment L401-405】适配层/引擎数据形态接缝不闭合
- **现象**：① 适配层与引擎 `equip` 均硬性要求 `ItemInstance`（L1043 `isinstance(item, ItemInstance)`、equipment.py L239）；而本文件 /背包 渲染 `_row_fields`（L547-570）显式兼容 4a 存档 **dict 行**（工程补白 8），storage 落点是 dict 形态（4a §1.2）——同一 ctx 背包，/背包 可渲染、/装备「穿」则恒「❌ 这件物品不能装备」。② 引擎 `aggregate_bonus` 对 `player["attributes"]` 要求 `PlayerAttributes`（`attributes.bonus["flat"]=`，equipment.py L401-405）；若装配从存储反序列化出 dict 形态 attributes，穿脱即 AttributeError【静态推导】，再被 `_cmd_equip_wear` 的裸 except 吞成「❌ 装备失败」。
- **影响**：装配层若不统一归一（dict→ItemInstance/PlayerAttributes），/装备 全量静默失败且不可诊断。
- **修复建议**：二选一——装配层 make_context 承诺统一归一并在 register_basic_commands 文档中写死契约；或适配层/引擎对 dict 行做轻量转换兜底（`ItemInstance(**row)`），并在吞异常处保留真实异常上下文。

### 2.4 P2-1【status_commands L277-292】印记区未实现
- STT-01 ⑤ / 4f RUL-13 明确面板含「印记区」（`【印记】火焰印记×2（敌方施放）`），`effects_line` 仅渲染 buff/debuff 效果、无印记行。三张 TC 均未覆盖印记 → 契约规则部分未落地。
- **修复建议**：effects 数据源增加 type 标记或在 ctx 增加 `imprints` 列表渲染 `【印记】…` 行；补单测。

### 2.5 P2-2【register L458-459】保留字符黄提示仅部分实现
- REG-02 ③ 要求空格/`* , = + /` 黄提示不硬拦；实际空格（token 切分）、`*`（数量操作符）、`/`（未知分隔符）在解析层即 TPL-12 硬拦，仅 `+ , =` 能走到 `reserved_char_hint` 黄提示。测试已记录该偏离（test_register_commands L213-223 注）。
- **修复建议**：在 REG-02 ③ 注释中显式登记「空格/*// 由解析器硬拦」为工程补白（与 REG-02 ② 超长 emoji 同口径），或文档更新契约。

### 2.6 P2-3【basic L1118-1122/L1128-1132】命令壳裸吞异常
- `except Exception: res={}` → 一律「❌ 装备失败/卸下失败」，丢失真实错误（叠加 P1-3 使故障不可诊断）。
- **修复建议**：至少 `logging` 留痕或保留异常到 reason。

### 2.7 P2-4【shortcut L123-130】`shortcut_max=0`（不限）显示为 /20
- RUL-26 允许 0=不限（router.check_shortcut_limit L860 正确判 0 不限）；`_shortcut_max` 把 0 兜底成 20 → 列表头 `【快捷（N/20）】` 分母错误。
- **修复建议**：`_shortcut_max` 遇 0 返回 None/「不限」，头部按 `N/不限` 渲染。

### 2.8 P2-5【shortcut L170-180】`/快捷列表 自动` 固定子词静默忽略
- fixed_subword 被解析器抽走后 args 为空 → 静默渲染第 1 页（未报错也未消费参数）。
- **修复建议**：与 /快捷解绑 一致，`fixed_subword` 非空即 TPL-12。

### 2.9 P2-6【basic L1473-1479】/帮助 注册引导版次序与内容
- ① 未注册玩家 `/帮助 xx!`（解析错误）先得 TPL-12 而非引导版（B6 豁免应在解析前）；② `_REGISTER_GUIDE`（L215-221）列出「角色」而 B6 原文为「状态」三项。
- **修复建议**：未注册分支前置到 `parsed.error` 判定之前；引导版按 B6 改为 注册/状态/背包（或登记偏离）。

### 2.10 P2-7【basic L1369-1395】别名显示不支持 router 备选形态
- `_command_alias_display` 仅认 `{原指令: {alias}}`（与 parsers._normalize_aliases 同构）；router.AliasTable.from_config 额外支持 `{别名: {command}}` 备选形态（router L690-696）。内容包若用备选形态，/帮助 显示层不替换而与触发行为不一致（TC-17 用主形态不受影响）。
- **修复建议**：`_command_alias_display` 与 AliasTable 共用归一逻辑，或登记「仅支持主形态」工程补白。

### 2.11 P2-8【basic L895-906】槽位名渲染不认 slots.json 包装形态
- `_slot_name`/`_slot_order` 读 `ctx["slots"]` 平铺形态；引擎构造认 `{"slots":{…},"mutual_exclusions":[…]}` 包装形态（equipment L148-155）→ 同一配置下渲染回退缺省名而引擎正常。
- **修复建议**：`_slot_name` 对包装形态取 `slots["slots"].get(slot_id)`；或装配层统一展开后注入。

### 2.12 P2-9【status L295-305 / L230-235】渲染缺省守卫不全
- `target_line` 对 hp/mx/turn 为 None 无守卫 → 「【目标】xx None/None（第 None 回合）」；`level_line` 无 exp_next 时输出无阈值（`经验 320`）；`f["exp"]` 可能为 float → `320.0/1000`。
- **修复建议**：target 字段缺省整行降级为 None；exp 渲染 `int()`/`_fmt_num` 归一（basic 已有 `_fmt_num` L241）。

### 2.13 P2-10【register L423 / status L105 / shortcut L104 / basic L277】`registered` 缺省 True 的系统性门槛风险
- 四模块门槛均 `ctx.get("registered", True)`；装配层若漏设 `registered=False`（新玩家），未注册玩家会被放行（/状态 /背包 空数据渲染）、/注册 反被幂等拒绝。此为全局约定（工程补白 7）但三新模块复制放大。
- **修复建议**：装配接线时在 make_context 强制显式设置 registered；或在批次7 装配清单登记「门槛字段必须显式注入」检查项。

### 2.14 P2-11【四个模块各一份 _fragment L130/L92/L91/L231】工具重复
- 同一 `_fragment`（raw 优先重构 TPL-12 片段）在 4 个命令模块重复实现。
- **修复建议**：抽到 `sender.py` 或 `parsers.py` 公共位置。

---

## 三、维度③ 遗漏核对（TC 未覆盖 / 规则未实现）

| 项 | 判定 |
|---|---|
| TC-REG-01~05 / TC-STT-01~03 / TC-SHC-01~03 覆盖 | ✅ 三模块单测齐备，逐条断言具体输出（test_register/status/shortcut_commands.py） |
| TC-EQP-01~05（经适配层） | ✅ test_equip_adapter.py 覆盖（部位匹配/互斥/后装覆盖/卸装/聚合/战斗内/emoji） |
| TC-EQP-06（互斥环加载 + 战斗内） | 互斥环加载拦截在 engine.validate_slot_exclusions（路A）；适配层战斗内拒绝有测 | ✅ |
| TC-08（前缀格式可配） | 不在 D1 承接范围（D1 只承接 4f TC-07/09/10）；前缀硬编码 + 批次7 裁决 | ✅ 登记承接边界 |
| 印记区（RUL-13/STT-01⑤） | **未实现**（无 TC 覆盖） | ❌ **P2-1** |
| 效果区 5 个以上折叠（TC-STT-02 后半） | ✅ L288-289 |
| 快捷列表翻页/夹取/非法页码 | ✅ 有测（test_shortcut L116-123） |
| 帮助别名 keep_original:false（TC-17） | ✅ 主形态；备选形态缺测 | ⚠️ P2-7 |
| GM 组保密（TC-18） | 既有 basic_commands 实现（`_help_groups` L1398-1403），不在本批变更面 | ✅ 未回归 |
| P1-2/P1-3 承接落点 | ✅ 见 1.4 |

---

## 四、无问题维度确认

- **parsers.DEFAULT_WHITELIST 补「注册」**：parsers.py L116 已补，且「状态」「快捷解绑」「快捷列表」均在 —— ✅ 无问题。
- **未注册门槛（RUL-08）**：7 处游玩指令 handler 均消费 TPL_REGISTER_GATE、/帮助 豁免 —— ✅（仅 P2-10 缺省值系统性提示）。
- **缺省职业链（B7/REG-04）**：default_job_id → recommended_newbie → 首职业三级兜底 + 无效配置防御 —— ✅。
- **重名 / 已注册幂等（REG-03）**：文案与 4f TC-03/04 逐字一致、不覆盖原档 —— ✅。
- **面板五区 / 效果区折叠 / 目标行（STT-01~04）**：行序与 TPL-4F-02/03 一致 —— ✅（印记区另列 P2-1）。
- **解绑 / 列表（SHC-01/02）**：文案逐字符合 TPL-4F-10/11 —— ✅。
- **帮助别名显示替换（SHC-04/TC-17）**：`_group_summary` 与 `_render_help_group` 均消费 `_command_alias_display`（目录行与组页都替换）—— ✅ 主形态。
- **TPL-12 统一与 emoji 纪律**：四模块均走 sender.format_tpl12、仅 ✅/❌、有 emoji 扫描测试 —— ✅。
- **路由注册与白名单联动**：三新模块 `register_*` 与既有模块同态（批次7 装配），CommandSpec 注册无重名冲突 —— ✅。

---

## 五、修复优先级汇总

| 级别 | 编号 | 位置 | 一句话 |
|---|---|---|---|
| P1 | P1-1 | register_commands.py L416-419 | 固定子词作角色名被吞，`注册 自动 战士` 静默注册名「战士」 |
| P1 | P1-2 | basic_commands.py L1042 vs L510-529 | 穿装序号按存储序取，/背包 展示按时间倒序 → 穿错物品 |
| P1 | P1-3 | basic_commands.py L1043-1046 / equipment.py L401-405 | 适配层/引擎仅认 ItemInstance+PlayerAttributes，与 /背包 dict 行兼容/4a 存档形态不闭合 |
| P2 | P2-1 | status_commands.py L277-292 | 印记区（RUL-13/STT-01⑤）未实现 |
| P2 | P2-2 | register_commands.py L458-459 | 保留字符黄提示仅 `+ , =`；空格/*// 解析层硬拦 |
| P2 | P2-3 | basic_commands.py L1118-1132 | 命令壳裸吞异常 → 一律「❌ 装备失败」 |
| P2 | P2-4 | shortcut_commands.py L123-130 | shortcut_max=0（不限）显示为 /20 |
| P2 | P2-5 | shortcut_commands.py L170-180 | `/快捷列表 自动` 固定子词静默忽略 |
| P2 | P2-6 | basic_commands.py L1473-1479 / L215-221 | /帮助 引导版在解析错误后返回；列出「角色」非 B6「状态」 |
| P2 | P2-7 | basic_commands.py L1369-1395 | 别名显示不支持 router 备选形态 `{别名:{command}}` |
| P2 | P2-8 | basic_commands.py L895-906 | 槽位名渲染不认 slots.json 包装形态 |
| P2 | P2-9 | status_commands.py L295-305/L230-235 | target/exp 缺省守卫不全 |
| P2 | P2-10 | register L423 / status L105 / shortcut L104 / basic L277 | registered 缺省 True 门槛风险（批次7 须显式注入） |
| P2 | P2-11 | 四模块 _fragment | 工具重复实现 |

---

*审查纪律：j-space 门控 full 档；接缝审计逐文件/逐契约执行；所有运行行为结论为静态推导（环境无沙箱，未执行任何命令）。*
