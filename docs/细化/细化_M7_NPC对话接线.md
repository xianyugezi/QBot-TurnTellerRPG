# 细化_M7_NPC对话接线（/对话 指令壳 · 世界层挂载 · 事件写入 · 会话持久化）

> 版本：v1.0 · 类型：实现层细化契约（M7 N 系列）
> 权威依据：细化_M7_交互补全总纲（N-01~N-04）+ 细化_2b1_NPC数据与发牌员.md + 细化_2b2_对话会话状态机.md + m4_shared_contract §3.1（B1-B6）+ 用户拍板（NPC 系统设计定稿 v1.3 全套，2026-08-27 已落地 M4 引擎）
> 现状基线：npc.py（751 行 发牌员三策略+10 动作）/ dialog.py（954 行 会话状态机）/ npc_models.py（1185 行 schema）**M4 已实装三套测试全绿**；本细化只做接线（指令壳/世界层/事件/持久化），引擎零改动。
> 编号规则：任务 N-xx；规则 RN-xx；验收用例 TCN-xx

---

## 〇、一句话契约

> NPC 对话 = 已实装引擎（DialogSession 状态机 + npc 发牌员 + 10 类动作）接到运行链路：`/对话` 指令壳（N-01）→ 世界层当前地图 NPC 挂载（N-02）→ 事件写入 [事件:NPC对话:ID] 等 6 预置事件（N-03）→ 会话快照持久化与中断恢复（N-04）。零引擎改动，纯装配。

---

## 一、N-01 /对话 指令壳（dialog_commands.py）

### 1.1 指令签名（RN-01）
- 指令名：`对话`（白名单注册，显示名 `/对话`）；**需 / 前缀**（M4 接缝裁决：可快捷绑定、不可免前缀直发——parsers.py prefix_required 已含）。
- 子形态：`/对话`（无参=列表）· `/对话 N`（序号）· `/对话 名称`（名称优先，禁空格）。参数解析**委托** `dialog.parse_dialog_command(args, npcs)`（真实签名，已 read 核对）。
- 列表渲染：`dialog.render_npc_list(npcs)` → 序号+名字+类型图标（渲染剥离 emoji，对齐 emoji 纪律）。

### 1.2 会话生命周期（RN-02 · 核心接线）
指令壳持有一个 `DialogSession` 实例（装配层按玩家注入），生命周期：

| 阶段 | 输入 | 引擎调用 | ctx 前置 |
|---|---|---|---|
| 建会话 | /对话 参数 | `parse_dialog_command` → `session.step(("dialog", parsed), ctx)` | ctx: npcs（当前地图 visible NPC）/ settings / heard / eval_condition / condition_ctx |
| 会话路由 | 纯数字/继续/离开/再见/退出/选择N | `session.step((sub, value), ctx)`（**会话路由统一由 router.route_message 的 ROUTE_SESSION 分支处理**，壳按 subword 调 step；classify_session_input 归一子词） | dialog_active=True 时 router 送 mode=session_digit → 本壳 |
| 动作执行 | 菜单选择 N | `session.step(("select", N), ctx)` → 返回 exec 请求 → **壳自行调 `dispatch_action`**（状态机内 `_on_exec` 不调 npc）→ 结果映射 `("exec_done", payload)` 回传 | 见 1.3 |
| 执行回调 | 动作完成 | `session.step(("exec_done", {...}), ctx)`（payload 六键：info_key/is_info/subui/label/shop_refs） | — |
| 中断 | 任意时刻 | `session.step(("interrupt", None), ctx)` → 落快照即回（状态不变） | — |
| 收尾 | 退出 | `session.step(("exit", None), ctx)` → 清 dialog_active + 事件计数 | — |

- **step 结果消费**：step 返回 dict（`_result` 形态：`{ok, kind, state, lines, ...}`）——壳按 kind 分支：`list`/`menu`/`narration`/`exec`/`subui`/`ended`/`command`（带指令词不消费 → 返回壳继续正常解析，R2）。
- **对话会话激活标记**：ctx["dialog_active"]=True（建会话起）→ False（收尾/中断不迁移但保持激活？——中断=落快照即回，**激活态保持**，2b2 §2.3；离开地图/收尾才清除）。
- **当前地图 NPC 来源**：N-02 世界层提供。

### 1.3 动作执行接线（RN-03）
- 菜单选项选中 → step 返回 exec 请求（含选中的 interaction 条目）→ **壳自行调** `npc.dispatch_action(entry, ctx, rng, npc_id, state)`（真实签名：entry/ctx/rng/npc_id/state）→ 结果映射 `("exec_done", payload)` 回传 DialogSession.step——**payload 六键**：`info_key`（信息类已听键，`_info_key_of` 口径：显式 info_key 或 action:{index}）/ `is_info`（信息类标记）/ `subui`（子界面标记）/ `label`（子界面名）/ `shop_refs`（商店移交列表）/ `completed`（SUBUI 确认）。
- **已听双轨键桥接**（dsh 审查 P2-2 收口）：/对话 壳在 exec_done 后**双写**——① dialog 侧 `mark_heard`（ctx["heard"]，info_key 键，菜单置灰）；② npc 侧 `npc.mark_delivered(ctx, npc_id, f"intel:{ref_id}")`（ctx["npc_delivered"]，动作去重）——两套键都落玩家存档（persistent_state["npc_heard"] / persistent_state["npc_delivered"]），防情报重复交付。
- 结果渲染：ok → ✅ 业务文案（dispatch_action 返回 message/data）；condition_not_met → 条件提示；一次一物已听 → 「你已经听过了」。
- **shop 移交**：action=shop 且命中 → dispatch_action 改写 ctx["current_shop_ref"]（地图级状态，2b3 §四）→ exec_done 回菜单，玩家后续 /商店 直接回店。
- **quest 移交**：action=quest → 走 quest 引擎（N-02 quest 联动）。
- **发牌员**：NPC type=发牌员（dealer 子结构）→ `npc.deal(npc_id, dealer, ctx, rng, rotate_state, greeting)`；rotate_state 由装配层按 npc 持有（persistent_state["npc_rotate"]）。

### 1.4 注册与白名单（RN-04）
- parsers 白名单（FIXED/DEFAULT）+ Router 注册（register_dialog_commands(router, *, make_context)）；会话路由接入 processing 驱动（A-03 装配时接 route_message 的 dialog_active 分支）。
- /对话 需前缀：parsers prefix_required 集合已含（m4 §2.3 接缝裁决），装配层确认生效。

---

## 二、N-02 世界层 NPC 挂载

### 2.1 GameWorld 地图 NPC 接口（RN-05）
- GameWorld 新增/确认方法：`get_npcs(map_id) -> List[dict]`——读 map_def.npcs（地图挂点 npc id 列表）+ npc registry（content registry "npc" 键）解析为完整 npc dict（含 visible/dealer/interactions/dialogues）；visible=false 过滤（可见性 SM01）。
- 无 NPC 地图 → 空列表 → 指令壳输出 DIALOG_EMPTY_MAP_HINT（「当前地图没有可对话的人」）。
- 玩家位置来源：ctx["location"]（当前 map_id，装配层从玩家存档/世界状态读）。

### 2.2 当前商店连接（RN-06）
- NPC 对话 shop 动作 → dispatch_action 改写 ctx["current_shop_ref"]（地图级状态）→ 同地图 /商店 直接回店（shop_refs[0]）；离开地图清除 → 全局默认商店（2b3 §四 TC-29~32）。
- 装配层 make_context 注入 current_shop_ref 读写（读自 world_state 地图级状态）。

### 2.3 quest / codex 联动（RN-07）
- quest：NPC 发任务卡（dealer 池 quest 卡）→ `npc.available_quests(deliver, ctx)` 过滤（已领/已完成去重）→ 接取走 quest 引擎（ctx["quest_engine"]）。
- codex：intel 情报交付 → dispatch_action 改写 ctx["codex_state"]（图鉴点亮）→ 图鉴回看出口（置灰不死胡同）。

### 2.4 隐藏任务（3f F-09 接缝，RN-08）
- NPC 发任务条件组合（quest.npc conditions 全与，3f D-05）→ 满足才主动发；不满足 → 普通对话分支零暗示（不提示原则）。
- 隐藏任务 quest 不配置 board → 天然不上任务板（D-06）；接取后 /任务 正常展示。

---

## 三、N-03 事件写入契约

### 3.1 6 个预置事件写入（RN-09 · 覆盖审计 #39 收口）
| 事件键 | 写入时机 | 写入者 |
|---|---|---|
| `[事件:NPC对话:{npc_id}]` | 对话会话收尾（exit） | dialog_commands 壳（dialog_event_key 生成） |
| `[事件:副本通关]` | 副本结算（dungeon） | world/dungeon 结算点 |
| `[事件:任务完成]` | quest_complete 成功 | quest 引擎结算点 |
| `[事件:签到]` | checkin 成功 | checkin 引擎结算点 |
| `[事件:怪物击杀]` | battle 怪物死亡结算 | battle 引擎结算点 |
| `[事件:等级提升]` | levelup 升级成功 | levelup 引擎结算点 |

### 3.2 写入管线（RN-10 · 统一口径 · ADR-05）
- **双表落点**：
  - `longline_counters`（只增不减，data/player.py L94 已确认）——冒险日志累计
  - `event_counts`（条件引擎读取源，condition_engine L570-571 `[事件:*]` 求值）——NPC/任务/隐藏要素条件消费
  - `persistent_state["event_log"]`（JSON 数组，环形 300 可配）——事件实例日志（3f E-01 模型含 snapshot/first_seen/ts，冒险日志 6 类记录数据源）
- **写入函数**：装配层提供统一 `bump_event(ctx, key, *, instance=None)`（longline_counters[key] +1 + event_counts[key] +1 + 事件实例入 event_log 环形）——**条件读 event_counts / 日志累计读 longline + event_log**（非统一读 longline）。
- **原子性**：事件写入与触发结算**同事务**（D2 幂等三件套：业务写 + write_idem_key 同事务）+ message_id 幂等防双记（3f R-02 写入原子性）。
- **消费方**：NPC 发牌员条件 / 任务条件 / 隐藏要素（3f）读 event_counts；冒险日志（3f）读 event_log + longline_counters。

---

## 四、N-04 会话持久化与恢复

### 4.1 快照落点（RN-11 · 零新存储 + 生命周期对齐）
- DialogSession 快照（to_snapshot，JSON 可序列化）落 **persistent_state["dialog_session"]**（玩家存档通用非会话持久容器，已确认存在——零 schema 改动）。
- **生命周期**（dsh 审查 P2-6 收口）：dialog_session 键按 2b2「会话快照 30 天回收」口径在读取/启动时**惰性清理**（last_active_at 超 30 天 → 清除恢复上下文）——与已交付标记（npc_heard/npc_delivered 常驻不回收）分离。
- 已听集合 heard 落 persistent_state["npc_heard"]（一次一物已交付标记，L88 落玩家存档不落会话快照，30 天回收不清）。
- 发牌 rotate_state 落 persistent_state["npc_rotate"]（{npc_id: {index}}）。
- 恢复：装配层 make_context 从 persistent_state 读 → DialogSession.from_snapshot（真实签名，已 read 核对）+ 注入 npcs/settings/heard。

### 4.2 中断恢复（RN-12）
- 中断（interrupt）→ 快照落盘（状态不变）→ 下次 /对话 或会话路由纯数字 → build_resume_brief(snapshot) 恢复简报（「上次的『XX』未完成」+ 菜单层重显 + 长叙述分段 page 索引恢复，2b2 §2.3）。
- 恢复简报渲染：`dialog.build_resume_brief(snapshot, npc_name=...)`（真实签名）。

### 4.3 会话收尾清理（RN-13）
- exit → step 收尾 → 清 persistent_state["dialog_session"] + ctx["dialog_active"]=False + 事件计数（N-03）+ 释放会话。
- 离开地图：当前商店清除（2b3）+ 对话会话若激活 → 中断落快照（玩家回图可续）或收尾（按 2b2 语义：离开地图不自动断会话，回来可续）。

---

## 五、验收测试用例（TCN-01 ~ TCN-12）

| # | 用例 | 步骤 | 预期 |
|---|---|---|---|
| TCN-01 | /对话 列表 | 地图有 3 NPC 执行 /对话 | 序号+名字+类型图标列表；无 NPC → 「当前地图没有可对话的人」 |
| TCN-02 | /对话 序号/名称 | /对话 2 与 /对话 铁匠 | 均进入该 NPC 菜单；名称优先；含空格名称不可命中 |
| TCN-03 | 会话路由 | 菜单激活后发 1/继续/离开/选择2 | 纯数字/选择N 送状态机；带指令词（攻击1）照常解析（R2） |
| TCN-04 | 动作执行 | 选 quest 动作 | dispatch_action 调用 + ✅ 结果 + 任务接取（quest 引擎） |
| TCN-05 | 商店移交 | 选 shop 动作 | ctx["current_shop_ref"] 改写；随后 /商店 直接回店 |
| TCN-06 | 发牌员 | 对话发牌员 NPC | deal 抽牌交付；无牌 → 孤寂卡 greeting |
| TCN-07 | 一次一物 | 听情报后再进 | 「你已经听过了」置灰；mark_delivered 已记 |
| TCN-08 | 事件写入 | 会话收尾 | longline_counters["[事件:NPC对话:X]"] +1 **且 event_counts 同键 +1**（双表） |
| TCN-09 | 中断恢复 | 菜单中断 → 回图 → 再对话 | build_resume_brief 恢复简报 + 状态原样重入 |
| TCN-10 | 快照落盘 | 中断后读存档 | persistent_state["dialog_session"] 含快照；heard 落 npc_heard |
| TCN-11 | 收尾清理 | exit 后 | dialog_active=False + 快照清 + 事件计数已写 |
| TCN-12 | 6 预置事件 | 触发副本通关/任务完成/签到/击杀/升级 | 各自 longline_counters + event_counts 双表键 +1（同事务幂等） |

---

## 六、登记与开关

| 落点 | 内容 |
|---|---|
| 白名单 | parsers 补「对话」（已含 prefix_required） |
| 存储 | persistent_state 键：dialog_session / npc_heard / npc_rotate（零新列） |
| 事件注册表 | 6 预置事件键（N-03 表） |
| 模块 | commands/dialog_commands.py（新）+ GameWorld.get_npcs（新方法）+ 装配层（A-01 make_context 注入） |

*设计依据：细化_2b1 + 细化_2b2 + m4_shared_contract §3.1 + 总纲 N-01~04；引擎接口全部 read 真实签名核对（2026-08-28）。【2026-08-28 dsh 审查批1/批2 修订】：RN-10 双表管线（event_counts）+ event_log 落点、已听双轨键桥接、exec_done payload 六键、会话路由统一 route_message、快照 30 天惰性清理、TCN-08/12 双表断言。*
