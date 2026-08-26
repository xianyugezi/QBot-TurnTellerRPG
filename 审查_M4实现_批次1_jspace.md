# 审查：M4 实现层 · 批次1（公共基础 + 指令解析）

> 审查方式：**纯静态代码审查**（本环境禁用 bash/命令/运行验证，未执行任何脚本）；涉及运行行为的结论一律标注【静态推导】。
> 审查文件（5 个）：`qbot_rpg/core/reward.py` · `qbot_rpg/engine/condition_engine.py` · `qbot_rpg/core/dayroll.py` · `qbot_rpg/commands/parsers.py` · `qbot_rpg/commands/router.py`
> 依据：`docs/m4_shared_contract.md`（§0 八项拍板 / §1 A1-A3 / §2）+ `docs/细化/细化_2b4/2b5/3c/4f` + `docs/审查参考/任务定稿/签到定稿/分隔符规范` + 2026-08-27 裁决注记（P0-1 / P1-2 / P2-4 / P2-5 等）。
> 覆盖测试抽样：`tests/unit/test_reward.py` · `test_condition_engine.py` · `test_dayroll.py` · `test_parsers.py` · `test_router.py` 及 quest/checkin 引擎/指令测试。

---

## 〇 结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | 0 | 无崩溃/数据损坏/已接线的权限绕过（GM 快捷绕过已被 router 正确拦截，parsers 未接线） |
| **P1** | 2 | ① dispatch_reward 物品通道依赖调用方注入 hooks，两个消费方未接线且无失败感知；② parsers/router 双管线平行实现、已现 3 处口径漂移 |
| **P2** | 10 | 键空间错位 / 内联中文键缺失 / fail-safe 声称差异 / 固定子词冲突漏检 / mode 溯源 / 列表内数量未拆 / 零消费工具 / 返回形态登记 / 旧货币键残留 / 契约措辞 |

> P1-1 若批次 7 装配漏接 `add_item`，任务/签到的**物品奖励将静默丢失且无法重试**（幂等封口），影响等级按 P0 处理。

---

## 一、P1（必修，影响正确性/结构）

### P1-1 跨模块契约缺口：物品奖励依赖调用方注入，生产消费方未接线、且无失败感知

**文件**：`qbot_rpg/core/reward.py` L168-207（`_grant_item`）/ L193-204（add_item hook）/ L25-26（补白③）；消费方 `qbot_rpg/core/quest.py` L858-901、`qbot_rpg/core/checkin.py` L694-726、`L405-411`。

**证据**：
- `_grant_item` 的物品存在性只读 `ctx["items"]` 注册表或 `ctx["resolve_item"]` 解析器（L151-165）；实际入包只经 `ctx["add_item"]` hook（L193-204）。三者任一缺失 → 该条 `item_registry_missing` skip 或 `applied=False`。
- 当前两个生产消费方 `quest.py` / `checkin.py` **均未**向 ctx 注入 `items`/`add_item`（grep 无命中），且二者只消费 `rw["granted"]` 拼文案（quest L897-901），**不检查 `applied`、不检查 item 类 skipped**。
- 测试侧全部显式注入 hooks（`tests/unit/test_quest.py` L115、`test_quest_commands.py` L67-82、`test_checkin.py` L145、`test_npc.py` L424），且 `test_quest.py` L523 已承认"注册表缺失 → skip"行为——即**生产装配（批次 6/7 make_context）未注入则物品奖励在默认配置下整体静默丢失**。
- dispatch_reward 在批次完成即记 `ledger`（L351-353，幂等封口）→ 一旦发生 skip，同 tx 重试不补发，**无法补救**。

**修复建议**：
1. 批次 7 装配 `make_context` 必须注入 `ctx["items"]`（物品注册表）+ `ctx["add_item"]`（背包引擎入包 hook，默认绑定）。
2. 消费方（quest/checkin）结算后校验：`rw["granted"]` 中 `type=="item" and applied is False` → 黄字提示"物品未入包"且**不写幂等 ledger**；或由 reward 层对无 hook 的 item 条目直接置 `ok=False`（batch 级）而非"照常 granted"。
3. 至少在 dispatch_reward 无 hook 时返回条目级 `skip(item_add_failed)` 而非静默 `granted(applied=False)`（现状把"未入包"伪装成"已发放"，是静默丢奖的根源）。

### P1-2 双管线平行实现并已漂移：parsers.parse_command 与 router.route_and_expand 各自实现同一 3c S0-S8 流程

**文件**：`qbot_rpg/commands/parsers.py` L561-803 vs `qbot_rpg/commands/router.py` L468-586。

**证据**：
- commands 层只 import `parsers.parse_int` + `router.CommandSpec`（`basic/quest/checkin/shop/gm_commands` 的 import 区），`parse_command` 仅被测试直接驱动；`router.route_and_expand` 亦仅被测试驱动。生产装配（register_* 的 make_context）全部标注"**批次6/7 待接线**"（basic L1083、quest L443、checkin L337、shop L449、gm L779）→ **当前无生产入口，两条管线均存活，批次 7 接线前必须定唯一入口**；router 产出 RouteResult（非 ParsedCommand），若选 router 作入口还需 RouteResult→ParsedCommand 桥接（本批不存在该桥接）。
- 两管线已出现 **3 处可观测口径漂移**：
  - **(a) require_at 下裸 `/` 触发**：parsers S0 先剥 `@`（L667-676），无 `@` 则忽略 → `"/攻击 2"` 被忽略；router `_strip_trigger_prefix`（L366-380）if/elif 只剥其一，剥 `/` 后放行 → `"/攻击 2"` 通过。**router 绕过 @机器人 要求**（与规范 6.2 相悖）。
  - **(b) require_at 下 `@机器人 /攻击 2` 组合**：parsers 先剥 `@` 再剥 `/` → 正确；router 只剥 `@`、残余 `/` 使白名单失配 → 忽略。**两管线对同一合法输入给出相反结果**。
  - **(c) 快捷展开到 GM 指令**：parsers 在 `"/1"`（prefix_only）触发时 `prefix_stripped=True` 并透传（L694/L752-754）→ `重载` 被放行为可执行指令（**parsers 自身"GM 永不快捷"声明不成立，仅剩绑定层+执行层兜底**）；router `_trigger_allowed`（L453-465）对 `spec.is_gm` 且无实际 `/` 一律 `gm_requires_prefix` 拦截 → **正确**。当前路由入口是 router，故无实时漏洞，但为纵深防御缺口。

**修复建议**：
1. 批次 7 接线前定唯一管线入口并删/并另一套（或明确"parsers=纯 token 化、router=路由判定"的单向分工，禁止各自实现完整 S0-S8）。
2. 若保留 parsers 为入口之一：将 GM 判定从"prefix_required 集合"升级为"spec.is_gm 且前缀必须真正落在展开串上"；统一 `@` 与 `/` 的组合剥离顺序（先剥 `/` 再剥 `@`，或按规范只允许 `@机器人` 一种触发）。
3. 为两管线补同一输入集的对拍测试（require_at×{裸/,@,@+/} × {普通/GM/快捷}），防止批次 7 接错实现。

---

## 二、P2（应修/建议）

### P2-1 gem 奖励在默认键空间下静默跳过（键空间与条目键集错位）
**文件**：`qbot_rpg/core/reward.py` L51（`DEFAULT_CURRENCY_IDS=("coins","diamond")`）/ L54（`_SCALAR_KEYS` 含 `gem`）/ L224-230（unknown_currency skip）。
**证据**：契约 3h §5.1 默认货币模板 = 金币+钻石（`diamond`）；而任务/签到定稿的 reward 条目键为 `gem`（宝石）。无 settings 时 `{gem:3}` → `unknown_currency` 静默跳过；该行为被 `tests/unit/test_reward.py` L134-142 明确钉死（属"既有设计"，非隐藏 bug），但默认配置下宝石奖励静默丢失是真实 footgun。
**修复**：默认键空间并入 `gem`，或 `gem`→`diamond` 兼容映射；同步 `content/field_meta.py` L211 默认模板并保持三处 `DEFAULT_CURRENCY_IDS` 一致（field_meta/validator/reward/battle_boundary）。

### P2-2 内联键值串不支持定稿示例的中文键「声望」
**文件**：`qbot_rpg/core/reward.py` L58-59（`_PAIR_RE` 仅 ASCII 键）/ L110-117。
**证据**：任务定稿 §九 L289 明示 `"声望=20" ≡ rep`（"声望 ≡ rep，中文键经互译表等价"）；当前 `expand_inline_reward("声望=20")` 抛 ValueError → dispatch 时整串 skip。
**修复**：`_SCALAR_KEYS` 增中文别名映射 `{声望:rep, 金币:coins, 宝石:gem}`（对齐 A2 互译表口径）。

### P2-3 condition_engine 补白④ 声称的 fail-safe 区分未实现
**文件**：`qbot_rpg/engine/condition_engine.py` L52-56（补白4 声明"event_counts 整体缺失 → None → False，longline 缺失 → 0"）vs L351-376（`_read_counter` 对**两种表缺失都返回 0.0**）与 L553-556。
**证据**：`{var:"[事件:x]", op:"eq", value:0}` 在 event_counts 整体缺失时求值 **True**，与补白声称的 None→False 可观测不同；ge 1 场景两者都 False（测试未覆盖 eq 0 边界）。
**修复**：对 `event_counts` 缺表返回 None（事件未接线=严格不满足），或修订 docstring 与实际一致。

### P2-4 快捷绑定冲突检测未纳入固定子词表（3c S6）
**文件**：`qbot_rpg/commands/router.py` L777-829（C01 只合并 `_registry_names ∪ alias_names ∪ reserved_words`）/ 生产调用方 `qbot_rpg/commands/gm_commands.py` L731-743（未传 `reserved_words`）。
**证据**：3c S6 裁决"动态注册表 = 框架指令 ∪ 内容包注册指令 ∪ **固定子词表**"；`parsers.FIXED_SUBWORDS`（追加/预览/自动/确认/放弃/续）未进入 C01 → 绑定名为「确认」「预览」不被拒绝。
**修复**：`check_shortcut_binding` 内置固定子词表（或 `gm_binding_guard` 传入 `FIXED_SUBWORDS`）。

### P2-5 快捷展开到别名时触发来源 mode 被覆盖（溯源丢失）
**文件**：`qbot_rpg/commands/parsers.py` L741-747（S4 别名分支 `mode = MODE_ALIAS`）。
**证据**：快捷 → 别名链在 parsers 中 `mode` 由 shortcut 变为 alias（expand_count=1 仍在）；router `route_and_expand` L582 强制保留 MODE_SHORTCUT。两管线对同一语义给出不同 mode。
**修复**：别名分支保留触发来源优先（`mode` 非 shortcut 才置 alias），或与 router 口径统一。

### P2-6 列表内单项 `*数量` 未按规范 L69 顺序拆解
**文件**：`qbot_rpg/commands/parsers.py` L471-529（`*` 拆数量仅在"普通位置参数"分支；列表分支只拆 `,`）。
**证据**：`投料 赤铁矿*3,火药*2` → `targets=["赤铁矿*3","火药*2"]`、`qty=None`——数量后缀留在名称内，消费方会当作物品名查询。规范 L69 参数内顺序"先 `,` 再 `*` 再 `=`"，列表项含 `*` 应逐项拆。
**修复**：列表分支对每项再按 `*` 拆数量（targets 存名称、qty 取首项或按项结构化），或明确定义"列表内单项数量"未支持并文档化。

### P2-7 dayroll.days_elapsed / advance_cycles 零消费（声明覆盖但未接线）
**文件**：`qbot_rpg/core/dayroll.py` L196-208 / L271-293。
**证据**：grep 全仓无任何模块 import 这两个函数（shop/quest/checkin/npc 只消费 today_of/weeks_elapsed/is_window_open）；签到 `day_index_of`（checkin L342-361）自实现 day 编号、未用 advance_cycles。
**修复**：确认后续批次消费方或标注"预留"；对零消费工具补充单测以免死代码漂移。

### P2-8 today_of 返回形态与契约签名偏差（已显式补白，登记供复核）
**文件**：`qbot_rpg/core/dayroll.py` L169-193。
**证据**：契约 m4 §1 A3 签名 `today_of(last_key, now=None) -> str`，实现返回 `{today, days_elapsed, refreshed}` 并新增 `cfg` 参数——文件头【工程补白】已显式说明派工单明确了该返回形态，非幻觉；登记差异供契约版本复核。
**修复**：无需改代码；契约 v2 建议同步签名为 `-> dict`（或补 `today_str` 便捷属性）。

### P2-9 跨模块：panel_render 使用旧货币键 gold 且 render_panel 零消费
**文件**：`qbot_rpg/core/message_format/panel_render.py` L83-86（`player.currencies.get("gold",0)`）。
**证据**：M4 统一键空间为 `coins`；`render_panel` 全仓无消费方（M0 遗留），gold 查找在 coins 键下恒 0。
**修复**：标注废弃或迁移 `coins`（注意该文件不在本批清单内，属维度③旧枚举残留扫描发现）。

### P2-10 契约措辞：m4 §2.1「分隔符五类」实列 7 种
**文件**：`docs/m4_shared_contract.md` L42。
**证据**：同一行列空格/`*`/`,`/`=`/`+`/`-`/`>` 共 7 种却称"五类"；3c/规范均为 7 种，parsers.py 按 7 种实现（**正确**）。
**修复**：修订 m4 §2.1 措辞为"分隔符七类"，避免实现方误读。

---

## 三、定稿落地确认（A1-A3 · 裁决 · 无问题维度）

### A1 统一 reward 发放器 —— 确认
- ✅ **rep 不入货币表**：`_grant_scalar` rep 分支 L242-250 写 `ctx["reputation_state"]`，货币表原样；测试 L187-193 钉死。
- ✅ **条目形态**：`{item,count}`（默认绑定，id 别名兼容 NPC L153）· `coins/gem/exp/rep` 标量 · 组合数组按序入账（测试 L221-228）。
- ✅ **内联串=序列化糖**：`expand_inline_reward` 等价展开（D-05/TC-02，测试 L57-69）；非法段加载期抛错、运行时整串 skip（P1-2，测试 L93-99）。
- ✅ **逐条目失败黄字跳过不中断**：P1-2 裁决落实（测试 L235-251）。
- ✅ **幂等**：`tx_id+ledger` 同 tx 不重复入账；批次完成（含 skipped）即记 ledger、batch 级失败不记（测试 L314-366）；只给 tx_id 不给 ledger 时不幂等（测试 L345-351，符合补白⑤）。
- ✅ **键空间**：coins/gem 走 settings 货币键，键不在空间 skip 不硬拦（缺省错位见 P2-1）。

### A2 统一条件引擎 —— 确认（除 P2-3）
- ✅ **9 运算符** gt/ge/lt/le/eq/ne/between/is/not（L94）；符号双写 `>= > <= < = !=` 归一（L96-103）；旧简写 min/max→ge/le（L106）。
- ✅ **三原语**：值型（level/item_count 读当前值，param 缺失 fail-safe）· 累计型（gain_count/kill_count/dungeon_clear/main_progress 读 longline_counters，缺表=0）· 事件型（`[事件:x]` 读 event_counts，op 缺省 ge、value 缺省 1）。
- ✅ **组合**：any/all/not 嵌套递归 + list/tuple=全与（2b4 D-02）；旧 `{type:"event",...}` 等价归一（L621-630）。
- ✅ **互译表**：VAR_ALIASES 覆盖任务速查键 + 三键（NPC 4.3.1 权威口径）；`[签到:连续天数]` 旧三键缺省表名=loop 兼容保留（L168-170）。
- ✅ **签到三键（裁决⑧）**：`[签到:<表名>.<字段>]` 解析（L252-263），字段名 `streak/month_days/today_signed` 与 `core/checkin.py` 投影（L568-577）**逐字段对齐**；本月天数=当月 signed_days 口径（checkin L173-178）。
- ✅ **求值失败默认 False**（D-03）：未知 var/op/param 缺失/ctx 无法取值 → False 不抛（测试 L345-363；边界差异见 P2-3）。

### A3 日界统一与懒计算 —— 确认
- ✅ **05:00 重置 + 凌晨归属**：`_date_key`（L146-152）= UTC+8 时刻 − refresh_time 偏移后的日期，重置后算新一天、0-5 点归前一天；统一配置键 `refresh_time` 默认 05:00（L67/L124-137）。
- ✅ **懒补算**：`today_of` 返回 days_elapsed/refreshed，零定时器、纯函数、离线多天按天数差补算（补白 L22-31）。
- ✅ **跨周判定**：`weeks_elapsed` 按"周周期锚点差 //7"，语义被 `tests/unit/test_dayroll.py` L205-246 钉死（周五/周日锚点跨下周一 = 1、跨 2 周 = 2、同周 = 0）——**审查中一度疑有 off-by-one，实测语义正确，撤回**。
- ✅ **once 时间窗**：`is_window_open` 闭区间三态（not_started/open/expired），start/end 缺省=常驻开放（L322-339）。
- ✅ **月推进**：`_advance_month` 自然月进位 + 夹取目标月天数（L256-268，2026-01-31+1月→02-28）。

### 裁决① 战斗中裸数字 = 快捷表 —— 确认
- parsers：S2 会话路由仅 `session_active and not in_battle`（L697-699）；调用方对战斗传 `session_active=False`（补白 L16-18），裸数字落到 S3 快捷表；`/攻击 2` 序号不带 `*` 正常解析。测试 L477-502 覆盖（战斗内 `1`→快捷、`3` 无快捷→忽略/白名单、`/攻击 2`→正常）。
- router：会话路由仅 `dialog_active`（L498-505），战斗裸数字落快捷表；`route_and_expand` 一级展开（L565-586）。

### 裁决② 页码夹取 —— 确认（跨模块）
- `core/message_format/list_render.py` L93-107：超总页数 → 夹取最后一页 + `LAST_PAGE_HINT`（"已到最后一页"）；0/负数/非数字由调用方走 TPL-12（`parsers.parse_int` L320-330 只认完整整数，非法返回 None 供壳层报错）。

### GM 禁绑 / 强制前缀 —— 确认（router 侧）
- ✅ 绑定层：`router.check_shortcut_binding` C02（L800-807）拒绝 GM 目标；生产包装 `gm_commands.gm_binding_guard`（L731-743）注入 `GM_COMMANDS` 单一事实源。
- ✅ 触发层：router `_trigger_allowed` 对 `spec.is_gm` 且无实际 `/` 一律拦截（L453-465）；`RouteResult.is_gm`（L304-307）供执行层二次检查位（E02）。
- ⚠️ parsers 侧同一场景存在放行路径（见 P1-2c，当前非生产入口）。

### 幻觉/缺漏审计 —— 结论
- ✅ **docstring 行号真实性**：抽查 reward 引"任务定稿 L100-126 / NPC 定稿 L153"、dayroll 引"商店 §七"、parsers/router 引 3c/规范/裁决①——均可回查到真实落点，**未发现虚构行号**。
- ✅ **工程补白纪律**：5 文件均显式 `【工程补白】` 标注（return 形态、hook 缺省、幂等前提、会话判定前置、别名紧凑、require_at 剥离顺序等），无冒充定稿行号的表述。
- ⚠️ 声明覆盖但未实现/未消费：P2-3（fail-safe 声称差异）、P2-7（days_elapsed/advance_cycles 零消费）、P2-9（panel_render 零消费）、P1-2（parsers.parse_command 仅测试消费）。
- ⚠️ 旧枚举残留：P2-9 `gold` 货币键（panel_render/formula_engine 侧）；`diamond` 与 `gem` 键名错位（P2-1）；`min/max` op 简写为**有意**兼容（OP_LEGACY_ALIASES，非残留）；发牌员旧枚举 `first_match/weighted→condition/random` 为裁决④**有意**兼容（npc.py normalize_strategy L126-138）。
- ⚠️ 硬编码扫描：数量上限 99 / 快捷上限 20 / 别名上限 50 / refresh_time 05:00 / weekday 1 / 5 条每页——均以"默认值可配"形式实现，非写死；`%4` 命中（dayroll L262、worldtime L210）为闰年/四季周期合法取模，非缺陷。

---

## 四、修复优先级建议

1. **P1-1**：批次 7 装配必须注入 `ctx["items"]+ctx["add_item"]`，且 reward/消费方补"未实际入包→不封口幂等"的防护——这是 M4 奖励闭环的静默丢奖风险。
2. **P1-2**：批次 7 接线前定唯一管线入口，消除 parsers/router 双实现漂移（尤其 GM 前缀豁免与 require_at 口径）。
3. **P2-1/P2-2**：先修"默认配置下 gem 静默跳过"与"声望=20 内联串整段报废"两个与定稿直接矛盾的键空间问题。

（本报告为静态审查结论；所有运行行为标注见各处【静态推导】，未经实际执行验证。）
