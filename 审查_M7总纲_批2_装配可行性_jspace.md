# 审查_M7总纲_批2_装配可行性_jspace

> 审查方式：**纯静态审查**（本环境无 bash 沙箱，未执行任何命令/脚本/验证；运行行为结论一律标「静态推导」）。
> 审查对象：`docs/细化/细化_M7_交互补全总纲.md` 的 A 系列（A-01~A-05 装配层）与 N 系列（N-01~N-04 NPC 接线）。
> 对照代码：`qbot_rpg/commands/quest_commands.py`、`register_commands.py`、`status_commands.py`、`core/npc.py`、`core/dialog.py`、`commands/processing.py`、`commands/router.py`（另按需对照 `core/quest.py`、`basic_commands.py`、`battle_commands.py`、`shop_commands.py`、`checkin_commands.py`、`shortcut_commands.py`、`gm_commands.py`、`explore_commands.py`、`commands/parsers.py`、`commands/sender.py`、`commands/prefix_wiring.py`、`storage/repository.py`、`world/game_world.py`、`world/session.py`）。
> 审查维度：① ctx 字段契约真实性 ② 接口签名 ③ 装配可行性 ④ 接缝遗漏。

---

## 结论摘要

- **P0 = 0 · P1 = 4 · P2 = 9**
- 总纲 A/N 系列的**大方向可行**：A-01/A-03/A-05 引用的引擎与装配件（process_message / sender.send / apply_message_prefix / cleanup_idem_keys / GameWorld.load / SessionManager / snapshot_resume 世代绑定 / Router 构造）全部真实存在且签名对齐；N 系列引用的 dialog/npc 引擎接口（parse_dialog_command / DialogSession.step / dispatch_action / render_npc_list / render_interaction_menu / build_resume_brief / to_snapshot / from_snapshot）全部真实存在。装配层确实缺失（`Router(` 零命中、无 make_context 工厂、无 NoneBot 入口——总纲"现状铁证"核实为真）。
- **但存在 4 处会让"按总纲字面装配"即出错/即炸"的契约冲突**，集中在 ctx 字段形态、注册清单、GM/日志注册冲突三处；另有 9 处遗漏/歧义/承诺无落点。

---

## 维度① ctx 字段契约真实性（A-01「ctx 字段全景」 vs 各指令壳消费契约）

### P1-1　`inventory` 同键双形态冲突：展示形态 vs 任务引擎计数映射

- **总纲声明**：A-01 L38「背包与装备：inventory（[名称]×数量 形态 + acquired_at 倒序）」——明确为 /背包 展示形态。
- **代码事实**：
  - `core/quest.py` L410-413 `_read_current`：`inv = ctx.get("inventory")`，要求 `{item_id: count}` 计数映射（`inv.get(param, 0)`）；L703-706 `_count_item`、L716-721 `_remove_item` 同样按 `inv.get(item_id, 0)` / `inv[item_id] = cur - count` 消费**同一 ctx 键**。
  - `basic_commands.py` L512-516 /背包：`ctx["inventory"]` = ItemInstance/dict 行（展示形态，acquired_at 倒序）。
- **判定**：同一 `inventory` 键无法同时满足两种形态。make_context 若按 A-01 造展示形态，任务引擎 `item_count` 条件恒 0、交付扣物失败、`gain_count` 等累计失效——**任务接取/交付在默认 make_context 下静默坏掉**（静态推导）。
- **修复建议**：A-01 改为声明双形态并落到装配契约：`inventory`（计数映射，任务引擎/条件引擎消费）+ 展示列表另键（或 `count_item`/`remove_item` hook 注入，`core/quest.py` 补白已留 hook 口）；在 A-01 明示两种形态与 hooks，防止 make_context 只建一种。

### P1-2　货币键名漂移：总纲「currency」单数 vs 代码「currencies」复数

- **总纲声明**：A-01 L41「商店：…/ currency / world_stock」——唯一货币字段写作单数 `currency`。
- **代码事实**：全代码消费 `currencies`（复数）：`core/npc.py` L484-505（heal 扣费 `currencies.get("coins")`）、L598-606（teleport 扣费）、`core/quest.py` L36（reward 发放桶）、`basic_commands.py` L607（货币行）、`shop_commands.py` L455（docstring「currencies」）、`battle_commands` 奖励结算。
- **判定**：字段名不符（维度①「形态/命名不符」）。若 make_context 照 A-01 注入 `currency`，NPC 治疗/传送费、商店结算、任务奖励入账全落空：npc.py 在 `currencies` 缺失时返回「无法结算治疗费」（`_action_heal` L484-486）或把 0 当余额（L598-606 静默放行免费传送）——治疗功能直接不可用（静态推导）。
- **修复建议**：A-01 L41 `currency` → `currencies`（复数），并在全景补一处全局货币字段说明（任务/商店/战斗/NPC 共用同一可变表）。

### P2-1　A-01 全景缺多个指令壳真实消费字段（缺字段面大）

A-01 自称「汇总各指令壳消费契约」，但对照实读代码，以下字段均不在全景：

- **battle**（`battle_commands.py` L30-46）：`battle_engine`/`sender`（必填，缺省 RuntimeError）/`to`/`channel`/`prefix_settings`/`prefix_extra`/`battle_reward_fn`/`battle_rewards`/`battle_hint`/`battle_status_changes`/`battle_summary` 全缺。
- **basic**（`basic_commands.py` L39-73）：`equip_engine`/`skills`/`resolve_skill`/`skill_chains`/`resolve_chain`/`skill_ids`/`slots`/`slot_order`/`is_gm`/`max_level`/`items`/`conditional_rules`/`attr_types` 缺。
- **gm**（`gm_commands.py` L909-910）：`gm_backend`/`permission_store`/`audit_store`/`qq_id`/`group_id`/`audit_hmac_key` 缺。
- **quest 引擎**（`core/quest.py` L26-36 补白 2）：`quests`/`resolve_quest`/`quest_ids`/`longline_counters`/`event_counts`/`tx_id`/`ledger`/`reputation_state` 缺（`longline_counters` 只在 A-03 事件写入提、未入 A-01 任务段）。
- **status**（`status_commands.py` L21-35 实读 `_gate`/`_to_attributes`/`_final_attrs`）：`imprints`/`attr_layers`/`conditional_rules`/`attr_types` 缺。
- **dialog**（`dialog.py` L463-470 类 docstring）：`npcs`/`heard`/`npc_interactions`/`get_narration`/`eval_condition`/`condition_ctx` 缺（全景只有「npc_delivered / heard / 当前地图 npc 列表」）。

另：`register_quest_commands` docstring（`quest_commands.py` L443-446）写「items/currencies」，与 quest 引擎消费键 `inventory`/`currencies` 不完全对齐（壳层 docstring 与引擎 docstring 命名漂移）。

- **判定**：若 make_context 仅照 A-01 组装，battle/gm/basic 的装配必缺字段（battle `sender` 缺失直接抛【待接线】RuntimeError）。
- **修复建议**：A-01 改为「代表性字段 + 权威以各指令壳 docstring/引擎补白为准」的声明，或逐壳补全；BCH-01 验收「ctx 全字段单测」应以各壳真实消费字段建断言矩阵。

### P2-2　已听集合双轨键格式：dialog `heard`（info_key）vs npc `npc_delivered`（intel:ref_id）未声明桥接

- **代码事实**：
  - `dialog.py` L403-412 `_info_key_of`：信息类选项已听键 = 显式 `info_key` 或 `action:{index}`（如「intel:1」）；菜单置灰读 `ctx["heard"]`（L833-839 `_heard`），经 `_exec_done` 的 `mark_heard` 上报（L729-731）。
  - `npc.py` L437-441 `_intel_keys`：情报交付键 = `intel:<ref_id>`；已听判定读 `ctx["npc_delivered"]`（L358-366），由 `mark_delivered` 落档（L338-350）。
- **判定**：同一情报在两套不同键、不同 ctx 字段。A-01（L44「npc_delivered / heard」）与 N-01（L87「mark_delivered/is_delivered 读 ctx["npc_delivered"]；信息类置灰已听」）都提到两字段，但**未声明 /对话 壳必须同时维护并双向持久化两套键**——否则菜单「已听」置灰与 npc 动作去重脱节，情报可能重复交付（静态推导）。
- **修复建议**：N-01 增加接缝说明：/对话 壳在 `exec_done` 后把 `mark_heard`（dialog 键）与 `dispatch_action` 结果的 `npc_delivered`（npc 键）双写落玩家存档；或统一 info_key 生成口径（`_info_key_of` 与 `_intel_keys` 共用 ref_id 派生）。

---

## 维度② 接口签名一致性

### 已核对一致（真实签名全部相符）

| 总纲引用 | 代码真实签名 | 位置 |
|---|---|---|
| parse_dialog_command | `parse_dialog_command(args, npcs) -> dict` | dialog.py L235 |
| DialogSession.step | `step(event, ctx=None) -> dict` | dialog.py L522 |
| dispatch_action | `dispatch_action(entry, ctx, rng=None, npc_id=None, state=None) -> dict` | npc.py L688 |
| render_npc_list | `render_npc_list(npcs) -> List[str]` | dialog.py L270 |
| render_interaction_menu | `render_interaction_menu(interactions, *, heard, conditions, page, max_options) -> dict` | dialog.py L318 |
| build_resume_brief | `build_resume_brief(snapshot, *, npc_name=None) -> Optional[str]` | dialog.py L418 |
| quest_board 系 | `quest_board(ctx)`/`resolve_board_index(ctx, ref)`/`quest_accept(qid, ctx)`/`quest_progress(qid, ctx)`/`quest_complete(qid, ctx)`/`quest_abandon(qid, ctx)` | quest.py L530/580/599/648/824/965 |
| process_message | `process_message(repo, queue, *, message_id, group_id, player_qid, command, handler, sender)` | processing.py L252 |
| Router/register | `Router(command_mode=..., require_at=...)` + `register(spec, replace=False)` + `register_command(...)` | router.py L194/201/870 |
| to_snapshot/from_snapshot | `to_snapshot() -> dict` / `from_snapshot(snap, **overrides)` | dialog.py L490/505 |
| route_message/route_and_expand/dispatch_message | 三者均存在；会话→快捷→别名→白名单→忽略优先级与 A-02 L57 一致 | router.py L490/591/617, L524-588 |

### P2-3　N-01「DialogSession._on_exec → dispatch_action」流程归属错位

- **总纲声明**：N-01 L86「动作分发：DialogSession._on_exec → dispatch_action（quest/shop/heal/…）→ 结果渲染」。
- **代码事实**：`dialog.py` L675-689 `_on_exec` **只处理 continue/exit/exec_done，不调用也不引用 npc.dispatch_action**（dialog.py 全文件零 import npc，纯状态机）。真实架构：/对话 壳在 T07 拿到 `action/handoff` 后**自行**调用 `npc.dispatch_action`，再把结果映射为 `("exec_done", {info_key, is_info, subui, label, shop_refs})` 回调状态机（`dialog.py` L721-753 `_exec_done` 消费该 payload）。
- **判定**：文档把「动作分发」归到状态机内部方法名下，会误导实现者在不存在的内部分发处接线；真正的接缝是壳层的 exec_done payload 映射（info_key/is_info/subui/label/shop_refs 六键）。
- **修复建议**：N-01 L86 改写为「壳层在 T07 后调用 npc.dispatch_action → 结果映射 exec_done payload（info_key/is_info/subui/label/shop_refs）回传 DialogSession.step」。

### P2-4　N-01「route_session_input」与 A-02「route_message」会话路由双轨歧义

- **总纲声明**：N-01 L85「会话中纯数字·继续·结束词·选择N（route_session_input 送状态机 mode=session_digit）」；A-02 L57「接入 route_message 的 dialog_active 会话路由」。
- **代码事实**：两条路径并存且互不调用——`dialog.py` L170 `route_session_input(text, *, session_active)`（返回 {kind, subword}）是独立二选一判定；`router.py` L524-531 `route_message` 走自己的 `is_session_subword`（router.py L111）+ `ROUTE_SESSION`/`MODE_SESSION_DIGIT`。装配实际走的是 router 路径。
- **判定**：N-01 引用的是不会在装配流水线中执行的函数，属于文档歧义。
- **修复建议**：N-01 明确「会话路由统一由 router.route_message 的 ROUTE_SESSION 分支处理，/对话 壳按 subword 调 DialogSession.step」，删除对 route_session_input 的引用（或标注其为纯函数测试用等价实现）。

---

## 维度③ 装配可行性

### P1-3　A-02 注册清单漏已实装的 explore_commands（/进入 /休息）

- **总纲声明**：A-02 L55-56 注册清单列出 battle/basic/quest/shop/checkin/register/shortcut/status/gm + N-01 dialog_commands + F 系列，**不含 explore**。
- **代码事实**：`explore_commands.py` L272 `register_explore_commands(router, *, make_context)` 已实装，注册 `/进入`（ENTER_CMD）`/休息`（REST_CMD）；`parsers.DEFAULT_WHITELIST`（parsers.py L110）已含「进入」。
- **判定**：按总纲字面装配则 /进入 /休息 不注册——移动/换区断链，直接波及 A-05 world 装配、N-02 传送动作（teleport 后需 /进入 级联）与 VM7-01 端到端冒烟（「注册→状态→…→对话」不含移动，但玩家到不了有 NPC 的地图）（静态推导）。
- **修复建议**：A-02 注册清单补 `explore_commands`，并把 A-05/N-02 的移动链路（/进入 /休息）纳入 VM7-01 冒烟路径。

### P1-4　/日志 玩家视图与 GM 注册冲突（A-02 装配即炸）

- **总纲声明**：A-02 L55 注册 gm_commands + L114（F-01）log_commands 注册 `/日志`（玩家视图分组分页 + 传记 + GM 视图权限分支）。
- **代码事实**：
  - `gm_commands.py` L158/163-165 `GM_CMD_LOG = "日志"` ∈ GM_COMMANDS；L197-203 GM_COMMAND_LEVEL 日志=GM；L923-929 `register_gm_commands` 把全部 GM_COMMANDS（含日志）以 `is_gm=True` + `permission=PERM_GM` 注册进 Router。
  - `parsers.py` L123 DEFAULT_WHITELIST、L129 DEFAULT_PREFIX_REQUIRED、L140 DEFAULT_GM_COMMANDS 均含「日志」→ GM 判定与强制 / 前缀。
  - `router.py` L206-207 `register` 同名冲突直接 `raise ValueError`（replace=False 默认）。
- **判定**：F-01 的 log_commands 若再 register「日志」，Router 同名注册冲突必现（装配即炸）；即便改名，parsers 侧 GM 判定（is_gm_command / DEFAULT_GM_COMMANDS）与 GM 权限执行也会拦截玩家视图。A-02 把「gm_commands + log_commands」并列注册而未处理同名/权限冲突（静态推导）。
- **修复建议**（方案择一，需在总纲 ADR 定稿）：① log_commands 并入 gm_commands 的「日志」spec，单 handler 内按 permission_store 分支玩家/GM 视图（is_gm=True 保持强制前缀，玩家视图也走 /日志 前缀）；② GM 清单移除「日志」，改由 log_commands 统一注册 + 内部权限分支，同步改 parsers DEFAULT_GM_COMMANDS/DEFAULT_PREFIX_REQUIRED。总纲须先裁定，避免 BCH-05 撞车。

### P2-5　PerPlayerQueue 超时承诺无代码落点（ADR-08/A-03）

- **总纲声明**：ADR-08 L177 + A-03 L65「装配层含 cleanup_idem_keys 调度 + PerPlayerQueue 超时（D2 P2-3/P2-4 登记必办收口）」。
- **代码事实**：`processing.py` L100-114 `QueueItem.enqueued_at` 字段**全文件无任何读取/超时判定**；`PerPlayerQueue`（L117-180）无超时 API、无重试/丢弃逻辑。cleanup 侧 `storage/repository.py` L701 `cleanup_idem_keys` 真实存在（可接）。
- **判定**：清理有落点、超时无落点——ADR-08 承诺的「队列超时收口」须在装配层新增（或扩展 processing.py），工作量被低估。
- **修复建议**：总纲在 A-03 标注「PerPlayerQueue 超时 = 装配层新增模块（processing.py 无此能力）」，并给出超时行为（丢弃/重试/幂等键兜底）与验收断言。

### P2-6　ROUTE_SESSION（对话子词）在 process_message 流水线中的位置未定义

- **总纲声明**：A-03 L62 流水线只描述「指令解析 → make_context → handler(tx) → COMMIT → 发送」。
- **代码事实**：`router.route_message` 对会话子词返回 `kind=ROUTE_SESSION`（router.py L528-531），但 A-03 未说明该分支是否走 process_message（幂等键/事务/队列）还是旁路直调 DialogSession.step；会话快照持久化落哪个存储键/事务也无指定（N-04 L103 只写「落 ctx/玩家存档」）。
- **判定**：对话子词的处理路径与会话快照持久化是 A-03/N-04 的交界接线点，总纲未闭合（静态推导）。
- **修复建议**：A-03 增加「ROUTE_SESSION 分支：旁路 process_message，壳层直接 step + 快照入同事务（或经独立幂等键）」的明示；N-04 明确会话快照的存储键与事务归属。

### P2-7　A-02 注册自检与 GM 权限执行层检查无代码落点

- **总纲声明**：A-02 L58「注册后自检（指令名冲突/白名单缺注册/注册缺白名单）→ 装配冒烟断言」；L56 配置装载含「GM 权限表」。
- **代码事实**：`router.py` 仅 register 查重（L206），无自检 API（白名单一致性比对需装配层新建，router 只暴露 `whitelist_names()` L224 / `names()` L221）；`router.py` L312-315 只暴露 `result.is_gm`/`spec.permission` 供下游检查，A-03 流水线无权限校验步；`gm_commands.py` L906 handler 返回 `GmResult`「批次7 装配据此处理静默/消息/审计」——A-02/A-03 均未定义 GmResult 的分发与 GM 权限（permission_store）检查位置。
- **判定**：GM 权限执行层检查与 GmResult 分发是装配层必须新增的接线点，总纲未落地。
- **修复建议**：A-03 流水线显式插入「permission 校验（result.spec.permission vs ctx permission_store）→ GM 指令走 GmResult 分发（静默/消息/审计）」两步骤；A-02 自检写成装配层独立函数并纳入 VM7-01。

---

## 维度④ 接缝遗漏

### P2-8　/调查 不在 parsers 白名单；/对话 白名单实为已就绪（N-01 措辞需修正）

- **代码事实**：`parsers.py` L116 已含「对话」、L129 `DEFAULT_PREFIX_REQUIRED` 已含「对话」（M4 接缝裁决：可快捷绑定、不可免前缀直发——与 N-01 L88 一致）；**「调查」不在 DEFAULT_WHITELIST**。
- **总纲声明**：SYN L187「parsers.py 白名单（/对话 /日志 /调查 注册）」——把三词并列当「待注册」处理，但 /对话 已注册、/日志 是 GM 指令（见 P1-4）、/调查 才真待加。
- **修复建议**：N-01 L88「注册：parsers 白名单 + Router 注册」改为「parsers 白名单已含 /对话（DEFAULT_PREFIX_REQUIRED），仅 Router 注册」；F-05 新增 /调查 时补 parsers 白名单，并核对 /调查 前缀模式（是否随 M4 接缝进入 prefix_required）。

### P2-9　A-02 快捷装载所需注入（shortcut_max / gm_commands）未入 A-01 全景

- **代码事实**：`shortcut_commands.py` L23/224 消费 `ctx["shortcuts"]` 可变表 + `shortcut_max`；router 路由读 `ctx["shortcuts"]`（router.py L348）；快捷绑定校验需 `gm_commands=GM_COMMANDS` 注入（`gm_commands.py` L858，复用 `router.check_shortcut_binding`）。
- **总纲声明**：A-02 L56 提「快捷表（玩家绑定）」、A-01 L43 有「shortcuts（可变表）/ shortcut_max（缺省 20）」，但**绑定校验所需的 gm_commands 注入、快捷表落玩家存档的装配点**未列（N/A 系列均无）。
- **修复建议**：A-01/A-02 补「快捷绑定校验注入（gm_commands 集合）+ 快捷表持久化归口（装配层 make_context 从玩家存档装载 / 回写）」。

### 已闭合（无遗漏）的接缝

- **前缀模式/免前缀配置**：`command_mode`（global_shortcut/prefix_only/combat_shortcut）+ `require_at`/`at_text` 全在 `router.py` L194/340-357/374-402 实装，A-02 引用真实。✓
- **会话路由接入**：`route_message` 的 dialog_active 分支与 A-02 ①~⑤ 优先级一致（router.py L524-588）。✓（壳侧处理见 P2-6）
- **世界装配**：`GameWorld.load/to_world_state`（game_world.py L190/193）、`SessionManager`（world/session.py L24）、`snapshot_resume` registry_generation 世代绑定（snapshot_resume.py L178/306/415）全部存在，A-05 可接。✓
- **发送出口**：`sender.send(text, *, to, budget)`（sender.py L157，CQ 转义+长度分条+重试）、`apply_message_prefix`（prefix_wiring.py L157）、DEFAULT_LENGTH_BUDGET=4000（sender.py L46，对齐 A-03 L63）。✓
- **N-02 当前商店连接**：npc.py L472-474 写 `ctx["current_shop_ref"]=refs[0]`，与总纲「shop_refs[0] 地图级状态、离开地图清除」口径一致（dialog.py 补白 4 L32-34）。✓
- **N-03 事件键**：dialog.py L262-264 `dialog_event_key` 产出 `[事件:NPC对话:{npc_id}]`，step 结果 `events` 列表透出（L946）——写入侧由装配层承接，与 N-03 L96-100 一致。✓
- **N-04 收尾**：T15 自动收尾清 dialog_active + 事件计数（dialog.py L755-761），与 N-04 L105 一致。✓

---

## 分级汇总

| 级别 | 数量 | 编号 |
|---|---|---|
| P0 | 0 | — |
| P1 | 4 | P1-1 inventory 同键双形态冲突 · P1-2 currency/currencies 键名漂移 · P1-3 explore_commands 漏注册 · P1-4 /日志 玩家视图与 GM 注册冲突 |
| P2 | 9 | P2-1 A-01 全景缺字段 · P2-2 已听双轨键未桥接 · P2-3 N-01 dispatch 流程归属错位 · P2-4 会话路由双轨歧义 · P2-5 队列超时无落点 · P2-6 ROUTE_SESSION 流水线位置未定义 · P2-7 自检/GM 权限执行无落点 · P2-8 /调查 白名单缺失+措辞修正 · P2-9 快捷装载注入未入全景 |

**优先修复顺序（建议）**：P1-4（装配即炸，需 ADR 先裁定）→ P1-1（任务链路默认装配即坏）→ P1-3（移动断链）→ P1-2（货币键名）→ P2-5/P2-6（装配工作量校准）→ 其余 P2 随 BCH 批次消化。

*本报告基于纯静态阅读；所有「运行行为」结论（如默认 make_context 下任务扣物失败、/日志 注册冲突、NPC 治疗失败）均为静态推导，未经执行验证。*
