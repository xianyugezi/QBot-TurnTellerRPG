# 审查报告 · M11 批4 A1（成就系统）—— j-space 静态审查

- **审查方式**：纯静态代码审查（无 bash/无沙箱，按任务要求禁止运行任何命令）。所有运行行为结论均标注【静态推导】，未经执行验证。
- **审查对象**（≤6 文件，按任务清单）：
  1. `qbot_rpg/core/achievements.py`（469 行）
  2. `qbot_rpg/core/reward.py`（501 行，只看 title 型 `_grant_title` + `dispatch_reward` 的 item 首获 `mark_seen` 接线）
  3. `qbot_rpg/engine/condition_engine.py`（789 行，只看 `_codex_category_pct` codex param 分支）
  4. `qbot_rpg/content/achievements_models.py`（512 行）
  5. `qbot_rpg/commands/achievement_commands.py`（259 行）
  6. `qbot_rpg/assembly/context.py`（1373 行，只看 achievement_state/achievements/titles/codex_categories 注入段）
- **契约基准**：`docs/细化/细化_4c_成就系统契约.md`（22 TC · 11 叶子字段 · D-01~D-09 · ACH-01~13）；补充参考 `docs/m11_成就摸底.md`。
- **接线审计范围（P0 五型）**：指令组注册（REGISTER_GROUPS）/ 白名单 / make_context 注入 / check_achievements 结算点消费方 / 「待接线」标志消费方。辅助核查：`assembly/router_setup.py`、`commands/parsers.py`、`content/loader.py`、`content/validator.py`、`assembly/runner.py`、`commands/processing.py`、`core/event_bus.py`、`core/codex.py`、`core/codex_milestones.py`、`core/proficiency.py`、`core/templates/achievement_tpl.py`。

---

## 〇、门控与结论速览

- **j-space 门控档位**：**full 档**（多步 22 TC 对账 + 6 文件 + 接线审计；单一交付物=本报告；一次阅读可验证）。已加载 capacity / broadcast / introspection 模块；无 loop 档（不开启 ledger 控制器——任务明令禁止运行任何命令，无状态跨多轮需求）。
- **结论**：**P0 × 1 · P1 × 6 · P2 × 6**（P0 为 1 项部署级接线缺失；P1 含 1 项静默丢奖 + 1 项防剧透泄露 + 4 项契约口径偏差；P2 为遗漏与加固项）。审查中 P1-4/P2-7 两项经落档链路追证后降级为口径确认（已并入对应条目），故计数取最终版。无问题维度确认见 §五。
- **最重要一句话**：本批 1A 交付的是「成就引擎 + 指令壳 + 校验器 + 装配注入」四件套，**结算器 check_achievements 目前没有任何消费方**（全仓 0 处调用，含图鉴/掉落/升级/任务/事件结算点）——即成就墙在真机上永远不会达成，只有 /成就 列表、/成就信息、/称号 三个查询指令可见。这是部署级 P0，必须由后续批次（G15 结算点钩子）或本批收口接线。

---

## 一、P0（部署级 · 必须修复）

### P0-1 【接线】check_achievements 结算点钩子零消费方（成就系统整体不可达成）

- **位置**：`qbot_rpg/core/achievements.py` L213（定义）；全仓 grep `check_achievements\(` 仅 2 处命中 = 定义处 + 模块 docstring L16 自述。`qbot_rpg/assembly/runner.py`、`commands/processing.py`、`core/event_bus.py`、`commands/battle_commands.py`、`commands/forge_commands.py` 均无调用。
- **证据链（静态推导）**：
  - reward.py L466-489 的 `dispatch_reward` 只接线了图鉴：item 首获 `mark_seen` + `check_milestones`（L485-487）；`core/codex_milestones.py::check_milestones` L337 有 `battle_commands.py` L751 与 reward L487 两处消费方——但 **check_achievements 一处都没有**。
  - 结算点（图鉴点亮/事件触发/物品获得/升级/任务完成）是 D-07 唯一授予时机；无消费方 = 任何条件满足都不触发达成结算。
  - `achievement_commands.py` L19 F-2 明示「正常指令流不主动触发」reveals——即 /成就 列表路径也不会触发结算，进一步确认零消费方。
- **契约依据**：4c §2.1 结算点钩子（D-07）、TC-01/03/16 全部依赖结算点触发；摸底 §五 收口检查单 G15。
- **修复建议**：
  1. 在真实结算点接线：`codex.py::mark_seen` 首见后（L372 起）、`event_bus.py::bump_event`（L150 后）、`reward.py` item 首获（L480 旁）、升级/任务完成结算处，调用 `check_achievements(ctx, sources=[...])`，并把返回的 `messages/reveals` 并入当次回复。
  2. 若本批范围不允许接线，必须显式登记【待接线】并给出结算点清单（承接批2/批3 G15），否则成就系统在真机上永远零达成——比「指令壳不可用」更隐蔽（界面齐全但永远不触发）。
  3. 至少补一个单测：构造已满足条件的 ctx 调 `check_achievements`，断言 granted/reveals 产出（测试文件 `tests/unit/test_achievements.py` 已存在，属于本批承载）。

---

## 二、P1（重要 · 建议本批修复）

### P1-1 【静默丢奖】`_grant_reward` 无条件把 tx_id 记入 ledger，破坏 reward「item_add_failed 不封口」语义

- **位置**：`qbot_rpg/core/achievements.py` L197-210（`_grant_reward`）与 L300-313（调用点）。
- **问题（静态推导）**：reward.py L493-499 明示：批次含 `item_add_failed`（物品未实际入包）→ **不记 ledger、不封口幂等**，由消费方整单回滚兜底、可重试。而 `_grant_reward` 在 `dispatch_reward` 返回后**无条件** `ledger.add(tx_id)`（L208-209），把「未入包的物品奖励」一并封口。若 reward 的 `item_add_failed` 分支实际触发，成就已写 unlocked（L304）但物品没进包，且同 tx 幂等闸（L253）导致重试也不补发 → 静默丢奖。
- **契约依据**：4c §3.4「条目级失败黄字跳过不吞整次」+ 规划 L180「发奖失败（物品不存在）黄字跳过不吞整次」；reward.py 自身 P1-1 不封口纪律。
- **修复建议**：`_grant_reward` 仿照 reward L493-499：仅当返回 skipped 中无 `type=="item" and reason=="item_add_failed"` 时才 `ledger.add(tx_id)`；或由调用方（achievements.py）检查 `r["skipped"]` 后再落账。同时补单测：`check_achievements` 在 add_item 失败时同 tx 重放应可重发物品。

### P1-2 【防剧透泄露】locked 未达成隐藏成就的 desc 明文经 `/成就信息` 与 `/成就` 列表泄露

- **位置**：`core/achievements.py` L417-428（`list_achievements`）与 L457-468（`achievement_view`）。
- **问题（静态推导）**：locked 未达成时仅把 `name` 置为「？？？」（L415-416 / L455-456），但 `desc`（L420 / L460）仍原样输出配置明文。4c §1.3 明示 locked 行「不渲染 name/desc/reveal_text」；D-08 要求未达成时任何路径不渲染 reveal_text；TC-14 断言 `/成就信息 <N>` 同样只显示锁定态。若 desc 含线索（如「收集全部神鱼支线」），等于直接把隐藏成就内容告诉玩家——**探索感破坏 + 违反 D-08 揭示纪律**。
- **修复建议**：locked 未达成时 `desc` 输出空串（或「？？？」），仅已达成时输出 desc；`achievement_view` 同修。`reveal_text` 两处均已条件化（L427/L467），正确。

### P1-3 【契约口径】`sources` 筛选读配置键 `source`，而 4c schema 无此字段（filter 恒空 → 分层结算点永远不触发）

- **位置**：`core/achievements.py` L276-279。
- **问题（静态推导）**：`sources` 传入时，用 `entry.get("source")` 与标签比对。但 4c §1.2 顶层 8 字段**无 `source` 键**；校验器 `TOP_FIELDS`（achievements_models.py L27-29）也无 `source` → 内容包配置里永远不会出现 `source` → `sources_set` 非 None 时**所有成就被过滤**，分层结算点（如只传 `["codex"]`）恒零达成。P0-1 修复时若按 G15 传标签，将直接踩此坑。
- **修复建议**：两选一——(a) 在 4c 契约补充 `source` 字段（顶层 8 → 9，需更新 schema/校验器/摸底）；(b) 取消 sources 筛选，`check_achievements` 始终全量检测（配置量小，逐批全检成本可忽略）。建议 (b)（最小契约漂移）；若选 (a) 必须同步 `TOP_FIELDS` 与字段计数口径（11 → 12 叶子）。

### P1-4 【口径确认】`title_state` 落档链路成立但依赖引用同一性（建议补实机验证）

- **位置**：`assembly/context.py` L1173-1174（`"title_state": player.title_state` 就地引用）；`data/player.py` L97（title_state 为 Player 独立字段，非 ps 段）；`storage/repository.py` L166/L272（title_state 独立列序列化）。
- **结论（静态推导，已确证）**：`ctx["title_state"]` 引用 `player.title_state`（就地可变引用）→ `_grant_title`（reward L315-325）写 `ctx["title_state"]["owned"]` 即改 `player.title_state` → runner L489 `upsert_player(p)` 序列化 `player.title_state`（repository L166）→ 落档成立 ✅。`/称号 佩戴`（equip_title 写 `ts["equipped"]`）同样就地落档 ✅。**无缺陷**；唯一残留风险：`achievement_commands._owned_titles`（L76-91）优先 `ProficiencyEngine().owned_titles(player)` 读 `player.title_state`（L462-475），与 `_current_title`（L94-102）读 `ctx["title_state"]` 同源 → 一致 ✅。**降级为口径确认项**：建议补一次实机验证「成就发放称号 → 读档 → /称号 可见」（TC-09 断言），并确认 `player.title_state` 旧档形态（Dict[str,str] 缺 owned 列表）与 `_owned_list` 的兼容。

### P1-5 【条件口径】事件型条件 `[事件:成就达成]` 计数形态与条件引擎读取形态不匹配（事件计数条件失效）

- **位置**：`core/achievements.py` L366-386（`_log_milestone` → `bump_event`），`core/event_bus.py` L137-147，`engine/condition_engine.py` L600-601 / L390-409。
- **问题（静态推导）**：
  - `bump_event` 写入：带 target → **nested** `event_counts[key][target]`（event_bus L140-145）；无 target → flat `event_counts[key]`。
  - `_read_counter`（condition_engine L390-409）读取：nested 表 `table[name][param]`；**无 param 时若 sub 是 Mapping → 返回 0.0**（L404-405，注释「嵌套形态需 param 维度」）。
  - `achievements.py` `_log_milestone` 调 `bump_event(ctx, "[事件:成就达成]", instance={"tag":..., "target": aid, ...})` **带 target=aid** → 写 nested `event_counts["[事件:成就达成]"][aid]`。
  - 而条件 `{var:"[事件:成就达成]", op:ge, value:1}` 无 param → `_read_counter` 读 `event_counts["[事件:成就达成]"]` 得 Mapping → **返回 0** → 事件型成就条件恒不满足（D-03 fail-safe 反而掩盖）。
- **契约依据**：4c §2.2 事件计数 `{var:"[事件:神鱼支线完成]", op:ge, value:8}`（无 param）；`[事件:成就达成]` 若被其它成就引用（成就链/统计类成就），同样踩此形态坑。
- **修复建议**：`_log_milestone` 的 `bump_event` 调用**不带 target**（或把计数写 flat 键），让无 param 条件可读；同时确认 `_fallback_bump_event`（context.py L736-779，param 分支写复合键 `"name:param"`）与 event_bus 的 nested 形态差异——两套兜底语义不一致，需统一（建议 event_bus 与 condition_engine 双形态读齐：`_read_counter` 无 param 时若 sub 是 Mapping，取子键计数之和或 max，而不是硬 0）。

### P1-6 【契约口径】内联串 `__inline__` 包装层在 dispatch_reward 中不可达（形同虚设，但无副作用）

- **位置**：`core/achievements.py` L181-194（`_iter_entries`），`core/reward.py` L394-413（`_iter_entries`）。
- **问题（静态推导）**：`achievements._iter_entries` 对 str 产出 `{"__inline__": raw}`（L185）；但 `dispatch_reward` 的 `_dispatch_one`（L330-350）只认 item/id/title/rep/prof/标量键，`{"__inline__": ...}` 走 `invalid_entry` skip（L350）→ 内联串奖励**永远 skip、永不入账**。reward 自己的 `_iter_entries`（L394-399）对 str 直接 `expand_inline_reward` 展开——成就层包了一层「单条目 dict」是多余的，且破坏 D-05「内联串=序列化糖等价展开」。TC-22 断言内联串与结构化数组入账结果完全一致 → 当前实现直接违反。
- **修复建议**：`achievements._iter_entries` 对 str 直接 `yield raw`（或直接调 `dispatch_reward(entry.get("reward"))`，让 reward 层自己展开 str）；删除 `__inline__` 包装。补 TC-22 断言。

### P1-7 【契约口径】once=false 重复达成时间戳语义（repeat 幂等补发与揭示纪律）

- **位置**：`core/achievements.py` L300-304、L317-322。
- **问题（静态推导）**：once=false 已达成再满足 → `repeat[aid]+1` 且**重发奖励**（L302/309）——契约允许（重复发小奖励，通胀自担）。但：① `unlocked[aid]` 时间戳在首次达成后不再更新（重复达成 ts 停留在首次）——契约 4.1 无 repeat 时间戳要求，可接受但建议记录最近一次达成时间；② 隐藏成就 once=false：第二次达成时 `already=True` → reveal 不再输出（L317 `not already` 判定）——符合 D-08「一次性揭示」；但 `rec["ts"]` 用 `unlocked.get(aid)` 首次时间戳，repeat 展示口径待定。整体可接受，列为 P2 加固即可。
- **修复建议**：属口径确认项，非缺陷；若产品要「重复达成刷新展示时间」，在 4c 决策记录补一行。

---

## 三、P2（遗漏 / 加固 / 非阻断）

### P2-1 【遗漏】热重载降级提示「配置已移除」未实现

- **位置**：`core/achievements.py` `list_achievements`（L392-432）——纯遍历当前配置；`reload_result.py` 无成就侧渲染。
- **契约依据**：4c §4.3（TC-13：删除成就 → /成就 不再显示 + 降级提示「配置已移除」+ unlocked 存档字段保留）。
- **静态推导**：unlocked 保留天然满足（ps 独立段，配置删除不影响）；但「已达成但配置已删」的降级提示无任何输出位。建议：`list_achievements` 对 `unlocked` 中存在但配置不存在的 ID 输出一行降级提示（数据源已可拿到 unlocked 全集），或在 1C 模板加 `ach_removed` 行。

### P2-2 【遗漏】hidden `hide` 模式的 /成就信息 序号口径

- **位置**：`commands/achievement_commands.py` L168-170（`/成就信息 <N>` 按 list 过滤后序号）。
- **静态推导**：`/成就` 列表过滤 hide 后（L120），`/成就信息` 用同一个过滤后 list 序号（L168-171）——一致、正确。但「锁定行占序号」与「hide 不占序号」的混合序号在 /成就信息 与 /成就 之间**保持一致**（都消费同一 entries），确认无问题。此项仅为口径确认，不列缺陷。

### P2-3 【加固】`achievements_models.py` 校验器与运行期引擎的别名/字段镜像漂移风险

- **位置**：`content/achievements_models.py` L34-53（COND_VARS / COND_EVENT_PRESETS 本地镜像）。
- **问题（静态推导）**：B-1 注释明示 content 层禁止 import engine，本地镜像 `COND_VARS`（codex/gain_count/item_count/level + 4 别名）**缺 kill_count/dungeon_clear/main_progress/prof_level/reputation/季节时段天气等已注册键**（对比 condition_engine REGISTERED_VARS）；`COND_EVENT_PRESETS` 仅 6 条，含 `[事件:图鉴新增]`/`[事件:隐藏发现]`，缺 `[事件:成就达成]` 等。校验器放行但引擎不认识，或引擎认识但校验器红拦（假阴性/假阳性）都会出现——镜像需与 REGISTERED_VARS 全量对齐，否则 4c §1.4「变量未注册硬拦」误伤合法配置。
- **修复建议**：把 `COND_VARS` 扩展为 REGISTERED_VARS 全量（或在校验器加「引擎键空间导出」机制，content 只读常量不 import 函数）。

### P2-4 【加固】`achievement_view` 与 `list_achievements` 重复实现（DRY）

- **位置**：`core/achievements.py` L392-469。
- **问题（静态推导）**：两函数各自重写 unlocked/repeat 读取 + ？？？归一 + 字段组装；且 `cmd_achievement_info` 用 `list_achievements(ctx)[idx-1]` 而非 `achievement_view`（L168-171），`achievement_view` 成为无消费方死代码（静态推导：仅 __all__ 导出）。不属缺陷，但建议 `/成就信息` 改用 `achievement_view`，删除重复分支。

### P2-5 【口径】`_now_iso` 兜底读系统时钟（与「零系统时钟」纪律冲突）

- **位置**：`core/achievements.py` L353-363。
- **静态推导**：docstring 声称「时间戳与日期全部由 ctx 注入，不读取系统时钟」，但 `_now_iso` 在 ctx 无 now/today 时 `datetime.now(timezone.utc)` 兜底（L361-363）。生产 ctx 必注 now/today（context.py L1296-1297），此兜底仅裸 ctx 触发；但违反模块自述纪律。建议改为返回空串或强制注入，保持纯函数确定性。

### P2-6 【遗漏】`_MAX_NAME_LEN=40 / _MAX_DESC_LEN=120` 与契约 20/50 不一致（防御常量漂移）

- **位置**：`core/achievements.py` L83-84 vs `achievements_models.py` L62-63（NAME_MAX=20 / DESC_MAX=50）。
- **静态推导**：引擎侧防御常量是校验器上限的 2 倍多，且引擎侧**未实际使用**（grep：_MAX_NAME_LEN 仅定义无消费）。属死常量，删除或对齐契约，避免未来误用。

### P2-7 【口径确认】`/称号 佩戴` 校验「已拥有」的 owned 来源与持久化源一致（P1-4 确认后连带消除）

- **位置**：`commands/achievement_commands.py` L76-91（`_owned_titles`）。
- **静态推导**：`_owned_titles` 优先 `ProficiencyEngine().owned_titles(player)`（读 `player.title_state.owned`，proficiency L462-475），`_current_title` 读 `ctx["title_state"].equipped`——两者同源（P1-4 确认 ctx["title_state"] ≡ player.title_state）→ 佩戴校验 `title_not_owned` 正常 ✅。此项由 P1-4 确认后连带消除，仅保留「旧档形态兼容」的实机复核建议（见 P1-4）。

---

## 四、接线审计（P0 五型逐项结论）

| # | 部署级检查项 | 结论 | 证据（静态推导） |
|---|---|---|---|
| 1 | 指令组注册：REGISTER_GROUPS 含 register_achievement_commands？ | ✅ 已注册 | `router_setup.py` L103，`build_router` L208-209 逐组调用 |
| 2 | 白名单含三词（成就/成就信息/称号）？ | ✅ 已登记 | `parsers.py` L149（DEFAULT_WHITELIST）；`DEFAULT_PREFIX_REQUIRED` L162 含 成就/成就信息（/称号 免前缀可快捷，对齐「纯查询+佩戴可快捷」注释）；`check_consistency` L260-261 口径：registered_not_whitelisted 硬不一致 → 空 ✅ |
| 3 | make_context 注入 ctx 模块？ | ✅ 已注入 | `context.py` L1224-1228（achievement_state 挂 ps / achievements 配置表 / titles 注册表 / codex_categories 投影）+ L1262-1265 未注册安全空值 |
| 4 | check_achievements 结算点接线方？ | ❌ **零消费方（P0-1）** | 全仓 grep 仅定义处 2 命中；reward.py 只接 mark_seen + check_milestones |
| 5 | 「待接线」标志零消费方？ | ⚠️ 部分 | `achievement_commands.py` L240-243（make_context 缺省 RuntimeError【待接线】）——但 `router_setup._resolve_make_context` L167-176 恒注入 ctx_factory → 生产路径不会触发该 RuntimeError（bridge 已接）；`pvp_commands.py` L47 引用说明这是共享模式，非死代码。真正的「待接线」是 P0-1 结算点（非字符串标记，是缺失调用）。 |

**其余接线确认**：`content/loader.py` L172（achievements 模块登记 `_KIND_FOR_MODULE`，modules_raw 通道 ✅）；`content/validator.py` L563-566（achievements 专项校验 ACH-01~13 已挂 ✅）；`core/templates/achievement_tpl.py`（1C 模板分区齐全，`cmd_achievements` 消费的 ach_list_* / ach_view_* / ach_title_* / ach_empty 全部存在 ✅）；`reward.py` `_grant_title`（L292-325：titles 注册表校验 + title_state.owned 写入 + 幂等，逻辑正确；衔接 P1-4 的落档问题）；`condition_engine._codex_category_pct`（L314-329：codex_categories 投影直取 + fail-safe None，正确，与 context.py L494-512 投影注入闭环 ✅；但见 P1-5 的 nested/flat 事件形态问题）。

---

## 五、无问题维度确认

- **① 4c 契约落地（schema/校验器）**：11 叶子字段（TOP_FIELDS 8 + HIDDEN_FIELDS 3）✅；conditions 全与（D-02）由 `eval_condition` list 全与 + 引擎 L653-654 承载 ✅；求值失败 fail-safe（D-03）由 `_resolve_var`/`_apply_op`/`eval_condition` 三重 None→False 承载 ✅；默认值兜底（D-09）由校验器 L419/L436/L460 与引擎 `_hidden_of` 归一承载 ✅；trigger 仅 check 硬拦（TC-21）✅（models L395-399）；condition 单对象别名 + 同给异值黄提示（D-01/TC-20）✅（models L402-406）；reward/rewards 别名（D-05/TC-22 结构部分）✅（models L451-457）；hidden 两模式 + reveal_text/clue_ref 校验（TC-14/15/18）✅（models L424-448）；称号型 reward 校验（ACH-13/TC-09 校验侧）✅（models L283-299）。**以上为校验/数据侧确认；达成侧见 P0-1/P1 系列。**
- **② 代码质量（幂等/跨档）**：幂等闸前置（L251-254）+ unlocked 幂等 + 跨档逐档授予语义（once=true 已达成跳过，条件逐条求值，天然逐档不漏不重授）✅；`_hidden_of` 三形态归一 ✅；`_reveal_of` 一次性揭示判定 ✅；`get_achievement_state` 只读快照 ✅；`dispatch_reward` 顶层/内容级错误分层 + item_add_failed 不封口（reward 内部）✅（成就侧衔接见 P1-1）。
- **③ 指令契约（/成就 /成就信息 /称号）**：三指令 handler 全部实现且注册；分页（5 条/页）✅；locked 占位「？？？」✅；hide 过滤不占序号（TC-15）✅（L120）；/称号 查看默认（F-3）✅（L192-212）；/称号 佩戴 1 槽替换 ✅（L197-205 → equip_title）。**展示侧确认；达成揭示（TC-16）依赖 P0-1。**

---

## 六、修复优先级建议

1. **P0-1**：结算点接线（或显式登记【待接线】+ 单测兜底）——成就系统是否「活着」的分水岭。
2. **P1-1**：`_grant_reward` 不封口 item_add_failed——防静默丢奖。
3. **P1-2**：locked 隐藏成就 desc 泄露——防剧透，改动两行。
4. **P1-5**：事件计数形态统一（nested/flat）——事件型成就条件可达性。
5. **P1-3**：sources/source 契约决策（建议取消筛选）。
6. **P2**：热重载降级提示、校验器键空间镜像全量、DRY、死常量清理；P1-4（title_state 落档）已确认无缺陷，仅补实机复核。

---

## 七、静态推导声明

本报告全部结论基于**静态代码阅读**（read/grep/glob），未运行任何命令/测试/脚本（环境无 bash 沙箱且任务明令禁止）。凡涉及「运行时会怎样」的表述（如 P0-1 零消费方、P1-1 丢奖路径、P1-5 形态不匹配）均标注【静态推导】，建议在具备执行环境的批次以单测/实机冒烟复核后再关闭。
