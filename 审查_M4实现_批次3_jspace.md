# 审查报告：M4 实现层·批次3（NPC / 对话）

- **审查对象（3 文件）**：
  - `qbot_rpg/content/npc_models.py`（1185 行：NPCDef 15 字段 / 6 子表 / validate_npcs 专项校验）
  - `qbot_rpg/core/npc.py`（751 行：发牌员三策略 rotate/random/condition + 10 类动作 + 一次一物 + 条件统一）
  - `qbot_rpg/core/dialog.py`（935 行：会话状态机 7 态 15 迁移 + 会话路由 + 深度可配 + 恢复简报 + 事件计数）
- **参考**：`docs/m4_shared_contract.md`（§3.1 / §0 裁决③④）+ `docs/细化/细化_2b1_NPC数据与发牌员.md` + `docs/细化/细化_2b2_对话会话状态机.md` + `docs/审查参考/NPC系统设计定稿.md`（v1.3.1，513 行）+ 2026-08-27 裁决③（深度可配）/④（策略枚举保留细化版）+ 跨层支撑（`core/reward.py` / `core/dayroll.py` / `commands/router.py` / `tests/unit/test_npc.py` / `test_dialog.py`）。
- **审查维度**：①定稿落地 ②代码质量（bug/边界）③幻觉/缺漏。
- **方法**：纯静态代码审查（无 bash / 无运行 / 无验证；j-space 门控 **full 档**）。凡运行期行为结论一律标注 **【静态推导】**。bash 沙箱确认不可用，未执行任何命令。
- **门控档位**：**full**（多文件多维度、单份可复核报告）。

---

## 〇、结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 三文件自洽、主链可运行；未发现"接口全面失配/不可用"级阻塞（对照批次2 的 checkin P0）。 |
| **P1** | **3** | ① dialog.py 把 reply 误列为信息类→闲聊被置灰"已听"/拦截，违背 2b1 AC10 + 定稿 L90；② dialog.py 叙述提取对 reply `text[]` 列表返回空→选"随便聊聊"空白屏；③ 快照 round-trip 丢失 `_exec_index`→中断续读完成后"已听"标记丢失可重复领情报。 |
| **P2** | **11** | docstring 行号漂移、全角数字输入崩溃、条件校验缺 op/value 不报、T04 打 `[事件:NPC对话:None]`、迁移 trace 虚构 S2/复用 T09、快照 current_shop_ref None、双"已听"键命名空间、折叠页离开编号与不变量2 冲突、校验器/运行器三分歧、give_item 指纹碰撞、intel Mapping ref 写 codex_state[None]。 |

**Top 3 问题**：
1. **P1-1（置灰幂等违反定稿）**：dialog.py `INFO_ACTIONS` 含 `"reply"`（L126），`_is_info`（L827-830）对 reply 恒真且 `"info": false` 无法逃生→闲聊交付后置灰"已听"、重选报"你已经听过了"、交付提示"已交付（图鉴可回看）"——三处都与 2b1 AC10"reply 不触发一次一物/不置灰可重复"、定稿 L90"功能类不置灰"直接冲突，且与同批 npc.py `INFO_ACTIONS=("intel","tutorial")`（L96，test_npc L341 已锁定正确集合）自相矛盾。
2. **P1-2（reply 空白屏）**：`_narration_of`（dialog.py L873-882）只认单字符串 text / lines / narration / content 键，对 AC10 规范形态 `text[]`（列表）返回 `[]`→`_on_menu` T07（L657）输出空、S4 EXEC 无任何回复文本；npc.py `_action_reply`（L655-671，test_npc L528-536 实测）正确处理列表，两侧行为分裂。
3. **P1-3（快照 round-trip 数据丢失）**：`to_snapshot`（L478-490）含 `exec_option` 但不含 `_exec_index`；`from_snapshot`（L492-504）不恢复→续读 EXEC 态后 `_exec_done`（L710-711）info_key 推导为 None→`mark_heard` 空，"已听"置灰丢失（可重复获取情报），违反 O03/O08 断点续谈语义。

---

## 一、维度① 定稿落地

### 1.1 已落地且确认（无问题维度）

| 契约点 | 确认 | 依据 |
|---|---|---|
| 发牌员三策略 rotate/random/condition（裁决④） | ✅ npc.py `STRATEGIES` + `normalize_strategy`（L76-138）+ `_draw_*` 三实现；旧 first_match→condition / weighted、random→random 兼容映射 + 迁移提示 | npc.py L79/L82-86/L125-138；npc_models.py L81-87/L963-973 |
| 10 类动作（AC01-AC10） | ✅ npc.py `ACTIONS` 10 类 + `_HANDLERS` 全映射（L90-93/L674-685）；npc_models `ACTION_TYPES` 10 类 + 逐 action 专属子字段校验（L71-74/L736-799）；repair 降级"不可用+友好提示"（S4） | npc.py L583-586；npc_models L765-767 |
| 一次一物（O01-O08） | ✅ npc.py `npc_delivered` 存档键 + mark_delivered/is_delivered/delivered_value（L338-366）+ intel/tutorial/give_item(once/daily)/card(once) 四类交付键；dialog.py 菜单"已听"置灰 + `mark_heard` 上报（L634-638/L716-717） | npc.py 补白②③、L437-448、L515-550；dialog.py 补白③ |
| 会话路由 R1-R5 | ✅ classify_session_input / route_session_input 实现"会话激活中子词送状态机、其余送指令解析"二选一（L132-177）；与 router.py SESSION_SUBWORD_* 同值 | dialog.py L99-177；router.py L92-98 |
| 菜单 ≤6 折叠 + 固定 N.离开 | ✅ render_interaction_menu 首页 ≤6 + "7.更多…" + "N.离开"；TC-06 口径 8 选项→6 项+7.更多+8.离开（测试锁定） | dialog.py L306-365；test_dialog L405-418 |
| 深度可配 settings.max_dialog_depth（裁决③，0=不限） | ✅ 双侧落地：npc_models `_max_dialog_depth`（L606-613）+ `_check_dialog_options` 软拦（L869-873，`max_depth and` 保证 0=不限不拦）；dialog.py `resolve_max_dialog_depth`/`is_depth_blocked`/`authored_node_depth`（L183-218），0→False 不限 | dialog.py L645-649 |
| 事件计数 [事件:NPC对话:ID]（L290） | ✅ dialog.py `dialog_event_key` + `_finish` 经 result.events 上报、由调用方落 longline_counters（补白②） | dialog.py L251-253/L741-747 |
| 会话状态机 7 态 15 迁移 | ✅ STATES 7 态（L89）；TRANSITION_IDS 15 条（L92-96）；T01-T15 逐条在代码中出现（trace 语义瑕疵见 P2-5） | dialog.py 全部 |
| 恢复简报（L94-102） | ✅ build_resume_brief 四态（菜单/EXEC 段位/SUBUI 标签/不可恢复） | dialog.py L406-427 |
| 当前商店移交 2b3（裁决 T12/T13） | ✅ dialog.py 只经 shop_refs/handoff 上报、S5 无选购分支（test_dialog L686-697 锁定） | dialog.py L25-27/L712/L737；npc.py 补白⑦（写 ctx 口径见 P2-8） |
| 条件统一 {var,op,value,param}（A2） | ✅ npc.py/dialog.py 均委托 `engine.condition_engine.eval_condition`（npc.py L48/L705；dialog.py L843 懒加载）；求值失败默认 False 不抛（D-03） | npc.py L196/L223/L705；dialog.py L832-846 |

### 1.2 校验器落地（validate_npcs）

- 15 顶层字段（F01-F15）+ 6 子表访问器全部齐备：NPCDef 13 个访问器（icon/map/type/desc/visible/dialogues/interactions/quests/shop_refs/intel/intel_refs/tutorials/dealer）+ BaseDef 承载 id/name（npc_models L298-392），与定稿 L436-437 列全 15 字段一致（S1 裁决落地）。
- 校验规则覆盖 TC-01/02/03/08/20 + 发牌员：id 唯一 / name 禁空格（`\u3000` 等全空白均拦）/ icon/type/map/visible 类型 / 引用存在性（quest/shop/items/effects/maps 反向）/ 对话树深度软拦 / 条件四要素红拦分流 / 未使用 NPC 黄提示（maps 已声明 npcs 时，补白④）/ 旧 strategy 迁移提示（裁决④）/ 孤寂卡空池提示（Y-5）。
- **空池/孤寂卡语义**：npc.py `deal`（L714-751）空池/无牌→`lonely:True` + greeting 兜底，不交付（SM05）✅；牌级 once 交付成功落 `card:<id>`（P05）✅；quest 三表去重（SM06）✅（available_quests L172-199 兼容扁平/嵌套 quest_daily 两形态）。

---

## 二、维度② 代码质量（bug / 边界）

### P1-1 【dialog.py 把 reply 误判为信息类 → 闲聊被置灰"已听"/拦截，违背 2b1 AC10 + 定稿 L90】

**文件/行号**：`qbot_rpg/core/dialog.py` L126（`INFO_ACTIONS = frozenset({"intel","tutorial","reply"})`）、L827-830（`_is_info`：`"info": false` 显式逃生无效，回退仍按 action 匹配 reply）、L634-638（`_on_menu` 已听拦截「你已经听过了」）、L716-717（`_exec_done` mark_heard）、L735（T10 交付提示「已交付（图鉴可回看）」）。

**对照**：
- 2b1 AC10：reply「**不置灰可重复**（闲聊不交付线索，**不触发一次一物**）」；定稿 L90：功能类交互（quest/shop/heal/give_item）不置灰——reply 属闲聊非信息类。
- 同批 npc.py L96：`INFO_ACTIONS: tuple = ("intel", "tutorial")`（无 reply）；test_npc.py L341 断言 `set(INFO_ACTIONS) == {"intel","tutorial"}`。**两个文件对 reply 分类直接矛盾**。

**后果【静态推导】**：在 dialog.py 自包含流程中，任何 `action:"reply"` 的选项交付一次后即被置灰「已听」，重选被 `already_heard` 拦截、提示「你已经听过了」；交付消息还写「已交付（图鉴可回看）」（reply 与图鉴无关）。玩家无法重复闲聊——与"闲聊不触发一次一物"的定稿语义相反。`"info": false` 逃生口对 reply 不生效（回退分支仍命中）。

**修复建议**：① `INFO_ACTIONS` 去掉 `"reply"`（对齐 npc.py L96）；② `_is_info` 改为「显式 `info:true` 优先、否则 action ∈ INFO_ACTIONS」；③ 若某 reply 确实要按信息类，需显式 `"info": true` 而非默认；④ 补一条"reply 交付后不置灰、可重复选择"的用例（现无任何测试覆盖 reply 选择流）。

### P1-2 【dialog.py 叙述提取对 reply `text[]` 列表返回空 → 选「随便聊聊」空白屏】

**文件/行号**：`qbot_rpg/core/dialog.py` L873-882（`_narration_of`：仅处理 `lines`/`narration`/`content` 列表键与单字符串 `text`，对列表 `text` 落入 `return []`）、L657（`out = [self.narration[0]] if self.narration else []` → 空输出进 S4 EXEC）。

**对照**：2b1 AC10 reply 专属字段 = `text[]`（**列表**，随机/循环取一条）；同批 npc.py `_action_reply`（L655-671）正确处理列表并随机/循环取一条（test_npc.py L528-536 实测）——两侧行为分裂。dialog.py 补白⑦自称"由会话从内容节点读取（intel/tutorial/**reply 多段**）"，但默认路径做不到。

**后果【静态推导】**：对话流中选一个 `action:"reply"` 且 `text:[...]` 的选项 → T07 输出空、S4 EXEC 无任何文本；玩家按「继续」→ `exec_done({})` 直接回菜单，回复内容全程不可见。单字符串 text 形态可显示，但那是非规范形态。`ctx["get_narration"]` hook 可兜底（集成层若提供则掩盖），默认自包含路径 broken。

**修复建议**：`_narration_of` 的 info 分支增加 `text` 列表处理（与 `lines` 同逻辑：`if isinstance(val, list): return [str(x) for x in val]`），或明确登记"reply 必须经 get_narration 注入"。补 reply 选择流测试。

### P1-3 【快照 round-trip 丢失 `_exec_index` → 中断续读完成后"已听"标记丢失】

**文件/行号**：`qbot_rpg/core/dialog.py` L478-490（`to_snapshot` 含 `exec_option` 不含 `_exec_index`）、L492-504（`from_snapshot` 不恢复 `_exec_index`，`cls()` 后为 None）、L710-711（`_exec_done`：`info_key = payload.get("info_key") or (_info_key_of(option, self._exec_index) if self._exec_index is not None else None)`）。

**后果【静态推导】**：EXEC 长叙述态中断 → 快照含 `exec_option` 但 `_exec_index=None` → 恢复后玩家「继续」翻到末段 → `_exec_done` 因 `_exec_index is None` 推导不出 info_key → `mark_heard=[]` → 交付不置灰。情报类（intel）可被再次领取，违反 O03/O08「断了能续、已交付不重发」语义。现有 test_snapshot_roundtrip（test_dialog L670-683）只断言状态/页码/narration 恢复，未覆盖"恢复后完成→置灰"。

**修复建议**：`to_snapshot` 增加 `"exec_index": self._exec_index`；`from_snapshot` 恢复 `_exec_index`；补一条"EXEC 中断→恢复→继续到末段→mark_heard 非空"用例。

### P2-1 【docstring 行号漂移：事件计数 L289 应为 L290；三词同义 L62 应为 L63】

**文件/行号**：npc.py L12（「事件计数 L289」）、dialog.py L12（「L289 [事件:NPC对话:ID]」）、dialog.py L103（「三词同义，L62」）。

**定稿实际（审查参考副本，逐行核对）**：L290 = `[事件:NPC对话:ID] 与 NPC 完成一次对话`（L289 实为 `[事件:等级提升]`）；L63 = 「结束词统一」（L62 实为「快捷表仅在无会话上下文生效」）。两处为 **+1 偏移**，继承自 2b2（L90 T15 引 L289、L120 R1 引 L58），且 2b2 自身对结束词行号亦有偏移（P2-1 见设计审查批次2）。实现侧 docstring 逐字照搬未自纠——不属编造，但引用真实性存疑。

**修复建议**：npc.py L12 / dialog.py L12 改引 L290；dialog.py L103 改引 L63（三词同义），并同步 router.py L94（批1 文件同根）。

### P2-2 【全角/圈号数字 isdigit+int 崩溃 + 状态值 int() 强制转换脆弱】

**文件/行号**：dialog.py L147-148（`classify_session_input`：`t.isdigit()` → `int(t)`）、L243-244（`parse_dialog_command` 同）；router.py L117-118（同根，批1 文件）；npc.py L309（`_draw_rotate` `int(state.get("index",0))`）、L665（`_action_reply` `int(state.get("reply_index",0))`）；dialog.py L422（`build_resume_brief` `int(snapshot.get("page_index") or 0)`）。

**问题【静态推导】**：`"②".isdigit()` / `"０".isdigit()`（全角数字）为 True，但 `int("②")` / `int("０")` 抛 **ValueError** → 输入分类/指令解析崩溃（QQ 中文输入法全角数字、圈号数字是现实输入）。state/快照值若被外部写成非整型（如字符串"2"）同样 `int()` 崩溃。

**修复建议**：纯数字判定改 `t.isascii() and t.isdigit()` 或 `re.fullmatch(r"\d+", t)`（对齐 _SELECT_RE 的口径）；state 读取用防御 `isinstance(v,int) and not isinstance(v,bool)` 兜底。

### P2-3 【条件校验缺 op / value 要素不报 → 四要素契约缺口】

**文件/行号**：`npc_models.py` L485-506（`_check_condition` 的 `var` 分支：`elif cond.get("op") is not None and not _cond_op_ok(...)` —— op 缺失时跳过，且无 value 存在性检查）。

**问题【静态推导】**：`{var:"level"}`、`{var:"level", op:"ge"}`（缺 value）通过校验零红零黄。定稿 C01 四要素 `{var,op,value,param?}` 中 value 为必填；缺 op/value 属结构错误，应红拦（校验器 4.5「结构错误」硬拦项）。当前此类坏条件静默放行，运行期恒 False（条件永假）且仅显示「需要：条件未满足」，作者无提示可循。

**修复建议**：`var` 分支补：op 缺失/非法→error（`op_missing`）；value 缺失→error（`value_missing`）；保留旧格式 type 黄提示。

### P2-4 【T04 列表直接结束 → 打 `[事件:NPC对话:None]` 计数污染】

**文件/行号**：dialog.py L578-580（`_on_list` exit → `_finish`）、L741-747（`_finish`：`event = dialog_event_key(self.npc_id)` 在 `_reset_all` 之前取值，但 T04 路径从未落地 NPC → npc_id=None）。

**问题【静态推导】**：玩家在 NPC 列表（S1）直接「离开/再见/退出」→ T04 收尾 → 产出 `[事件:NPC对话:None]` 事件键并上报。L290 语义为「与 NPC **完成一次对话**」，未选中任何 NPC 不应计数；None 键会污染事件计数表。

**修复建议**：`_finish` 仅当 `self.npc_id` 非空才生成事件；T04 路径事件列表置空。

### P2-5 【迁移 trace 语义：T02/T03 不实态化 S2；EXEC 内结束复用 T09】

**文件/行号**：dialog.py L696-705（`_land_npc` 直接 `self.state = S_MENU`，S2 仅存在于 trace 前缀 `[("T02", S_NPCSEL)]`）、L537-538（`_on_npcsel` 恒 `npcsel_noop` 死分支）、L670-672（`_on_exec` 叙述中结束 → `_finish([("T09", S_END)])`）。

**问题**：① 15 迁移表 T02/T03 定义为「→ S2 NPCSEL」，实现折叠 S2 直达 S3，trace 虚构了一次从未真实发生的 S2 状态（对断言的 trace 语义有误导性）；② EXEC 态「退出」无表中对应迁移，复用 T09（表定义是「菜单结束」）——15 迁移表无 EXEC→END 出口，属 trace 级自由度。均不影响运行行为（宏链自洽），但违反"迁移合法性可追溯"的审计初衷。

**修复建议**：trace 语义在 docstring 明示"T02/T03→T05 为合成路径、S2 不实态化"；EXEC 结束可登记为补白或给出专用 trace 标识。

### P2-6 【快照 current_shop_ref round-trip：None 值 list() 抛 TypeError】

**文件/行号**：dialog.py L496-499（`from_snapshot` 对 `current_shop_ref` 直接 `setattr`，不包装）、L485（`to_snapshot` `list(self.current_shop_ref)`）。

**问题【静态推导】**：`to_snapshot` 恒写 list，正常 round-trip 安全；但手工构造/外部恢复的快照若 `current_shop_ref=None`，`from_snapshot` 直赋 None 后，下一次 `to_snapshot` 的 `list(None)` 抛 TypeError。低危（仅非本模块产生的快照触发），但与 P1-3 同属 round-trip 防护不足。

**修复建议**：`from_snapshot` 对 current_shop_ref 做 `list(x or [])` 归一；`to_snapshot` 对非 list 防御。

### P2-7 【双"已听"键命名空间：dialog {action}:{index} vs npc 交付键不同源】

**文件/行号**：dialog.py L391-400（`_info_key_of` = 显式 `info_key` 或 `f"{action}:{idx+1}"`）；npc.py L437-448（交付键 `intel:<ref>` / `tutorial:<id>`）、L433-434（`give_item:<指纹>`）、L227（`card:<id>`）。

**问题**：两条互不相通的已交付簿记：dialog.py 的「已听」键（`info_key`/`{action}:{序号}`，经 ctx["heard"]），与 npc.py 的 `npc_delivered` 交付键（`intel:<ref_id>` 等，经补白②）**键值不同源**。装配层若不桥接（用 npc.py 的 `intel:<ref>` 判定菜单置灰），则情报交付后菜单可能不置灰（或置灰键与交付键脱节）——O07「置灰判定用 is_delivered(intel:<ref_id>)」与 dialog 的 `{action}:{序号}` 口径冲突。

**修复建议**：明确唯一键命名空间——建议菜单置灰统一走 npc.py 交付键（info_key 优先、缺省按 action 专属 id 派生），dialog.py `_info_key_of` 的 `{action}:{idx}` 兜底改为与 npc.py 一致的键（intel:<ref> 等），或登记为装配层必做桥接点。

### P2-8 【折叠二级页离开编号与不变量2「N=选项数+1」口径冲突 + 无返回首页】

**文件/行号**：dialog.py L332-337（page 1：`leave_no = shown + 1`，8 选项→`"3.离开"`）、L352-354（末项追加）；test_dialog.py L418 已锁定 `["7.选项7","8.选项8","3.离开"]`。

**问题**：2b2 §七 不变量2「菜单末项 = N.离开 恒定：N=选项数+1」。实现首页 N=8（TC-06 口径 ✓），但二级页 N=3（本页可见项数+1）——同一菜单两页离开编号不同（8 vs 3），与不变量字面冲突（已登记工程补白"二级页编号定稿未定义"），且二级页无「返回上一页」导航（选中剩余项后只能离开重进才能回首页）。

**修复建议**：二级页离开编号统一为「总选项数+1」（8 选项恒 9 或按 TC-06 口径恒 8），或补「返回首页」项；同步修订 2b2 不变量2 措辞。

### P2-9 【校验器/运行器三分歧：coins 浮点、strategy 大小写、give_item 键别名】

**文件/行号**：
- coins：npc_models.py L731（`_check_cost` 接受 `(int,float)`）vs npc.py L482（`_action_heal`）、L596（`_action_teleport`）——非 int 一律按 0（免费）。
- strategy 大小写：npc_models.py L963（`strategy not in DEALER_STRATEGIES` 逐字）vs npc.py L132-138（`normalize_strategy` lower().strip()）。
- give_item 键：npc_models.py L677（只认 `id`）vs reward.py L170（`key = "item" if "item" in entry else "id"` 等价别名）。

**问题【静态推导】**：① `cost.coins:50.5` 校验通过但运行按 0 免费扣费（配置作者困惑）；② `"ROTATE"`/`"First_Match"` 校验器红拦而运行器正常归一（校验比运行更严，同一配置两套口径）；③ `items:[{item:"药水",count:3}]`（A1 reward 合法形态，2b1「id≡item 键」）被校验器 `npc_give_item_id_invalid` 红拦。

**修复建议**：三处统一口径——coins 校验收窄为 int（或运行器放宽 float）；strategy 校验先归一 lower；give_item 校验接受 `id|item` 任一键（对齐 reward 别名）。

### P2-10 【give_item 指纹碰撞：同 NPC 相同 items 的多个交互共用交付键】

**文件/行号**：npc.py L413-434（`_items_fingerprint` 基于条目 key/id 或 items 序列，不含交互身份）。

**问题【静态推导】**：同一 NPC 配两个 `give_item` 交互（items 相同、如两个不同入口发同一种补给），指纹相同 → 交付键 `give_item:<指纹>` 相同 → 第一个领取后第二个被判 `once_claimed`/`daily_claimed` 误拦。低概率但属真实误伤。

**修复建议**：指纹并入交互上下文（npc_id + 选项序号/action 标识），或 key 由调用方显式传 `info_key`/`key` 区分。

### P2-11 【intel Mapping 形态 ref 无 id → codex_state[None] 写入】

**文件/行号**：npc.py L627-631（`_action_intel`：`rid = ref.get("id") if isinstance(ref, Mapping) else ref` → `cs[rid] = True`）。

**问题【静态推导】**：校验器对 interactions[].intel 的 intel_refs 只允许 str（`_check_string_ref_list`），Mapping 形态仅 `_intel_keys` 防御性支持；若未校验内容包出现 `{...}` 且无 id → `cs[None]=True` 污染图鉴状态。低危（仅绕过校验的数据触发）。

**修复建议**：`if rid is not None:` 才写 codex_state；Mapping 缺 id 该条跳过并计入 skipped。

---

## 三、维度③ 幻觉 / 缺漏

### 3.1 docstring 行号 / 引用真实性（抽核结论）

以 `docs/审查参考/NPC系统设计定稿.md`（513 行）为基准，抽核 ≥30 处实现侧引用的定稿行号：

| 引用 | 定稿实际 | 判定 |
|---|---|---|
| npc_models L9-12：L434 顶层 14 字段 / L436-437 列全 15 个 / L344-349 类型 6 类 / L444-448 校验器 | L434 =「顶层 14 字段 + 6 子表」、L436-437 = 15 字段、L344-349 = 6 类型、L444-448 = 校验器 | ✅ 逐行一致 |
| npc_models L71：10 类动作 L126-139 | L126-137 action 表、L139 repair 注 | ✅ |
| npc_models L90：菜单上限 L108-113 | L108-113 菜单上限 | ✅ |
| npc.py L11-12：发牌员 L401-415 / 10 类 L126-137 / 一次一物 L83-92 / 统一入账 L153 / 事件计数 L289 | L401-415 / L126-137 / L83-92 / L153 / **事件计数实为 L290** | ⚠ 仅事件计数 +1 偏移 → P2-1 |
| dialog.py L9-12：§2.1 L55-71 / §2.4 L94-102 / 菜单 L108-113 / 对话树 L316-336 / 深度 L324/L328 / 事件计数 L289 | 均存在；L324 = max_dialog_depth、L328 = 超深软拦、**事件计数 L290** | ⚠ 仅事件计数偏移 → P2-1 |
| dialog.py L103：三词同义 L62 | L62 = 快捷表（无关），实为 L63 | ⚠ +1 偏移 → P2-1 |
| dialog.py L115：已听过 L87 / L120：深度提示 L328 / L123：≤6 L110-111 / L263：列表 L40-41 | L87 / L328 / L110-111 / L40-41 | ✅ |
| npc.py L96：INFO_ACTIONS L86-90 | L86-90 信息类置灰+功能类不置灰 | ✅（分类引用本身错位见 P1-1） |

**结论**：无「引用不存在行号/语义改写定稿」级编造；两处 +1 行号漂移（事件计数 L290、三词同义 L63）继承自 2b2 且实现未自纠，判 P2-1。

### 3.2 工程补白 vs 冒充

- 三文件【工程补白】纪律良好：npc_models 6 条（条件镜像/牌池与 tutorials 键名/intel_refs 仅结构/未使用 NPC 防噪/repair 降级/对话树不成环+超深软拦）、npc.py 10 条（条件求值 A2/npc_delivered 键/daily 复用 A3/quest 去重三表/rotate 指针+reply cycle/buff 落点/teleport 纯函数/repair 降级/无 npc_id 不记账/菜单置灰委托）、dialog.py 11 条（不 import npc_models/事件计数委托/已听委托/current_shop_ref 移交/SUBUI 仅三场景/二级页编号收敛/长叙述注入/深度守卫 auth-node-depth/子节点以叙述交付/T15 自动衔接/结束词写死）——**均显式标注并给理由，无冒充定稿行号**。
- ⚠ 唯一隐性缺口：dialog.py 把 reply 列 INFO_ACTIONS 未标补白，且自称对齐 L86-89（信息类）——实为对 2b1 AC10 的误读（P1-1）。

### 3.3 声明覆盖但未实现

- ✅ 诚实委托：事件计数写 longline_counters、已听落玩家存档、current_shop_ref 记录、teleport 世界侧副作用、菜单置灰渲染——全部声明"由调用方/装配层完成"，无自拟虚假接口（对照批次2 checkin P0 的失实补白，本批干净）。
- ✅ npc.py 补白⑨（无 npc_id 不记账）为显式降级语义，非"未实现冒充"。
- ⚠ `deal` 的 greeting 兜底依赖调用方传入；`DialogSession` 不 import npc_models（并行路零冲突）由装配层桥接——均已在补白声明，属正常分工。

### 3.4 零消费函数 / 字段

- npc.py `INFO_ACTIONS`/`FUNCTIONAL_ACTIONS`/`DEGRADED_ACTIONS` 三个分类常量仅导出、本批零消费（等待装配层）——**但 dialog.py 自建同名 INFO_ACTIONS 且内容不同**（P1-1），暴露"导出分类无人消费 → 双份定义漂移"风险，建议装配层统一从 npc.py 引入。
- `DialogSession._on_npcsel` 恒 noop、S2 态不可达（P2-5）——死分支，建议保留为快照恢复容错或删注释。
- NPCDef 顶层 `intel` 字段仅校验不运行消费（情报运行期走 intel_refs）——属定稿 schema 字段，保留合理。

### 3.5 裁决贯彻

- 裁决③（深度可配）：✅ 双侧落地（npc_models + dialog.py），默认 2、0=不限、超深软拦，完全贯彻。
- 裁决④（策略枚举保留细化版）：✅ npc.py/npc_models 三策略 + 旧值兼容映射 + 迁移黄提示，完全贯彻。
- 裁决 T12/T13（current_shop_ref 移交 2b3）：✅ dialog.py 只上报不记录（test_dialog L686-697 锁定）；npc.py `_action_shop` 仍直写 ctx["current_shop_ref"]（补白⑦），与 dialog 补白④ 存在职责重叠口径（见下）。

### 3.6 跨文件责任口径张力（并入 P2）

- npc.py L472-473 `_action_shop` 直写 `ctx["current_shop_ref"]=refs[0]`，与 dialog.py 补白④「记录移到商店独立交付路径（2b3）、本模块只上报 shop_refs」存在重叠：若 2b3 也写 current_shop_ref，两来源并存。建议 npc.py shop 动作改为只上报、由装配层/2b3 写地图级状态。

---

## 四、发现分级汇总（P0=0 / P1=3 / P2=11）

| 级别 | 编号 | 主题 | 文件:行 |
|---|---|---|---|
| P1 | P1-1 | dialog.py 把 reply 误判信息类→置灰"已听"/拦截，违背 2b1 AC10 + 定稿 L90，与 npc.py INFO_ACTIONS 矛盾 | dialog.py L126/L827-830/L634-638/L735；npc.py L96 |
| P1 | P1-2 | reply `text[]` 叙述提取返回空→选「随便聊聊」空白屏（默认自包含路径） | dialog.py L873-882/L657 |
| P1 | P1-3 | 快照 round-trip 丢失 `_exec_index`→续读完成"已听"标记丢失 | dialog.py L478-490/L492-504/L710-711 |
| P2 | P2-1 | docstring 行号漂移（事件计数 L290、三词同义 L63） | npc.py L12；dialog.py L12/L103 |
| P2 | P2-2 | 全角/圈号数字 isdigit+int 崩溃 + 状态值 int() 脆弱 | dialog.py L147-148/L243-244/L422；npc.py L309/L665；router.py L117-118 |
| P2 | P2-3 | 条件校验缺 op/value 要素不报（四要素契约缺口） | npc_models.py L485-506 |
| P2 | P2-4 | T04 列表直接结束打 `[事件:NPC对话:None]` | dialog.py L578-580/L744 |
| P2 | P2-5 | 迁移 trace 虚构 S2 实态 / EXEC 结束复用 T09 | dialog.py L696-705/L537-538/L670-672 |
| P2 | P2-6 | 快照 current_shop_ref=None round-trip list(None) 崩溃 | dialog.py L496-499/L485 |
| P2 | P2-7 | 双"已听"键命名空间（dialog {action}:{idx} vs npc intel:<ref> 等） | dialog.py L391-400；npc.py L437-448 |
| P2 | P2-8 | 折叠二级页离开编号与不变量2 冲突 + 无返回首页 | dialog.py L332-337；test_dialog L418 |
| P2 | P2-9 | 校验器/运行器三分歧（coins float / strategy 大小写 / give_item item 键） | npc_models L731/L963/L677；npc.py L482/L596/L132-138；reward.py L170 |
| P2 | P2-10 | give_item 指纹碰撞（同 NPC 相同 items 多交互误拦） | npc.py L413-434 |
| P2 | P2-11 | intel Mapping ref 无 id→codex_state[None] 污染（低危） | npc.py L627-631 |

---

## 五、无问题维度确认（复核通过）

1. **发牌员三策略 + 兼容映射 + 迁移提示（裁决④）**：rotate 环形指针（连抽 4 次 A→B→C→A，TC-11）/ random 加权归一（全 0/等权→纯随机）/ condition 顺序首匹配（TC-09）；旧 first_match→condition、weighted→random 等权、random→random + 黄提示——代码与 2b1 DS01-DS04 逐条对齐。
2. **10 类动作**：ACTIONS 与 ACTION_TYPES 10 类枚举、_HANDLERS 全覆盖、repair 降级、give_item 经 reward 统一入账（A1）、buff 三表引用、quest 三表去重——全落地。
3. **深度可配 0=不限（裁决③）**：npc_models + dialog.py 双侧一致，0 不拦、超深软拦、每 NPC 至多一条黄提示。
4. **会话路由 R1-R5**：与 router.py 词表同值、与 2b2 §三 一致（含带指令词委托指令层）。
5. **事件计数落地**：dialog.py `_finish` 经 result.events 上报、键名与 L290 一致（除 None-NPC 边角 P2-4）。
6. **校验器结构**：id 唯一 / name 禁空格（全空白类）/ 引用双向校验 / 未使用 NPC 防噪 / 旧 strategy 迁移 / 孤寂卡提示——结构完整，_emit 鸭子类型 fail-safe。
7. **零 NoneBot import / 纯函数 / 确定性（rng 注入）**：三文件纪律成立；快照 JSON 可序列化。

---

## 六、后续批次衔接提醒（非本批缺陷）

- **装配层必做桥接**（否则 P1-1/P1-2/P2-7 在接线后立即暴露）：① 统一"已听"键命名空间（npc.py 交付键）；② 菜单"已听"置灰判定统一走 `is_delivered(ctx, npc_id, key)`；③ reply 叙述经 get_narration 注入或修 `_narration_of`。
- **分类常量双份漂移**：建议装配层从 npc.py 引入 INFO_ACTIONS/FUNCTIONAL_ACTIONS/DEGRADED_ACTIONS，删除 dialog.py 自建版（避免再次漂移）。
- **条件引擎侧**：A2 `condition_engine.eval_condition` 对缺 op/value 的容错行为（D-03 恒 False）已满足运行期，但校验器补 P2-3 后需与引擎口径对齐。
- **verify_m4 注册**：npc_models/npc/dialog 已列 verify_m4 映射（L202-204）；P1-3 建议补"EXEC 中断恢复→完成→置灰"端到端用例进 TC 矩阵。

---

## 附录 A｜接缝审计记录（j-space 寄存器，供下轮延续）

- **Ledger**
  - Goal：静态审查 M4 实现批次3（NPC/对话 3 文件）→ P0/P1/P2 报告落盘 → 最终回复（门控档位/结论/Top3）。
  - Verified：三实现文件全文（1185/751/935 行）；m4 §3.1/§0、2b1、2b2、NPC定稿 513 行全文；reward/dayroll/router/condition_engine 签名；test_npc.py / test_dialog.py 关键断言（INFO_ACTIONS L341、reply_card L67-68、reply 测试 L528-536、折叠页 L418、快照 L670-683、current_shop_ref L686-697）；行号逐一抽核 ≥30 处；无 bash（全部运行行为结论 = 静态推导）。
  - Open：无。
  - Next：交付最终回复。
- **Invariants 检查**：① 无未处置标记器；② 抽核有明确结果（行号逐行核对非"扫过没发现"）；③ 密写可展开（报告全中文）；④ 置信度分级与证据一致；⑤ 结论已落盘；⑥ 每条 P 问题标注文件+行号+修复；⑦ 报告无密写泄漏；⑧ 已按 §〇 结论逐条回溯核对。
- **Ship 检查**：本报告即 ship 对象——行号以 read 输出与审查参考定稿副本为准，Top3 与正文一致，无未核断言。

---

*审查模式：j-space · full 档 · 无 bash 静态审查 · 运行行为结论均标【静态推导】*
