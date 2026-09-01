# M11 批4 A3 · PVP 玩家互斗系统静态审查报告（j-space 门控 full 档）

- 审查对象：M11 批4 A3（PVP 玩家互斗系统，6 文件）
  - `qbot_rpg/core/pvp.py`（370 行：pvp_cfg / pvp_lock / pvp_attack / pvp_settle / sneak_attack_allowed）
  - `qbot_rpg/commands/pvp_commands.py`（375 行：/锁定玩家 /攻击玩家 指令壳）
  - `qbot_rpg/core/templates/pvp_tpl.py`（86 行：20 个 pvp_* 模板键）
  - `qbot_rpg/assembly/router_setup.py`（仅 REGISTER_GROUPS pvp 注册段，L104-105）
  - `qbot_rpg/commands/parsers.py`（仅 DEFAULT_WHITELIST 段，L150-151）
- 参考：`docs/细化/细化_4e_PVP决斗契约.md`（CMD-05/06、MIR、SET-R01~05、FR-R1~7、CFG-01~08、TC-01~20）+ `docs/m11_启动包.md` §2.3
- 交叉核验（静态读码）：`core/battle.py`（start/player_act/enemy_act/battle_state/_DEFAULT_STATS/_do_action_inner）、`world/session.py`（SessionManager.get_active 为 async；SessionView.session_type）、`data/player.py`（Player/PlayerAttributes frozen dataclass）、`assembly/context.py`（make_context 注入清单）、`assembly/runner.py`（_invoke_handler ctx 注入）、`core/reward.py`（dispatch_reward 幂等闸）、`commands/router.py`（_match_whitelist 最长前缀）、`commands/battle_commands.py`（_resolve_skill 口径）、`core/templates/__init__.py`（pvp_tpl 合并）

> 门禁说明：本环境无 bash 沙箱，全程仅静态代码审查，**未运行任何命令/脚本/测试**；一切运行时行为结论均为「静态推导」（标注 ⚙静态推导），以代码路径与已实读的接口契约为据。

---

## 一、结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | 4 | PVP 全链路装配零注入（锁目标/目标档案/每日防刷/回城钩子全部无消费方）；战斗引擎无状态无持久化（每次攻击新建、HP 不落档、技能库空）；free 模式行动字典键错恒「回合结算失败」；偷袭检测双坏（async 未 await + 属性名错） |
| **P1** | 9 | FR-R2/R4/R5 防刷空转；FR-R1 超限伪造防守方胜；回合制防守方自动普攻违约 TC-11；等级门槛单向；目标在线校验缺失；技能解析双失效+错文案；combatant 构建与生产 Player dataclass 形态不符；结算胜负判定单向/ended 恒 False/伤害恒 0；壳层-引擎 result 契约错位 |
| **P2** | 8 | def_ 键无效字段；QQ 9-11 位硬校验阻断测试号；属性公式缺 cond 层；装备摘要字段错位恒「无」；模板键计数文档 19 vs 实现 20；技能解析 DRY 漂移；mode 值域未校验；异常静默吞 |

**维度判定**：① 4e 契约落地——**双原语/非镜像/决斗四指令不复活/模板/注册/白名单全部确认通过**；但偷袭、防刷、结算、配置消费等运行侧全部被 P0 装配缺口卡死，契约验收点**不可达**。② 代码质量——壳层防御性好（F-1 未接线兜底、门槛、错误模板 4 类），引擎层边界问题集中在「生产 ctx 形态假设错误」与「无状态设计」。③ 部署级 P0 五型——指令注册 ✓ / 白名单 ✓ / make_context 注入 ✓（runner 传 ctx=ctx 成立）/ **hook 三要素：目标档案 hook、respawn_hook、防刷计数、锁状态持久化全部缺注入（✗ 四缺）** / 结算消费方：引擎结算结果无人落档（✗）。④ 遗漏——FR-R2、CFG-07 exp_on_win、SET-R04 快照回写、MIR-R1 快照即对局、同对一场（pair_key）未实现。

---

## 二、P0（部署级/契约验收必挂）

### P0-1 · PVP 全链路装配零注入：目标档案 / 锁定态 / 防刷计数 / 回城钩子 全部无消费方
- **位置**：`qbot_rpg/core/pvp.py` L71-86（`_player_by_qid`）、L232-234（`ctx["pvp_target"]`）、L314（`ctx["pvp_daily"]`）、L351（`ctx["respawn_hook"]`）；`qbot_rpg/assembly/context.py` 全文件（无任一注入）
- **证据（静态推导）**：
  - 全仓 grep `"players"`/`"get_player"`/`"pvp_target"`/`"pvp_daily"`/`"respawn_hook"`/`"active_sessions"`：除 pvp.py 自身引用外**零注入**。生产仓库只有 `Repository.load_player(qid)`（async，context.py L1050-1052），从不挂 ctx。
  - 结论链：`/锁定玩家` → `_player_by_qid` 恒 None → 恒回「目标玩家不存在」（pvp_lock_not_found）；即使打通，`pvp_lock` 返回 ok 也**不写任何状态**，`pvp_attack` 读 `ctx["pvp_target"]` 恒 None → 恒回「尚未锁定玩家」；`pvp_daily` 恒空 → FR-R1 防刷恒不计数；`respawn_hook` 恒 None → 回城惩罚钩子永不触发。
- **修复建议**：
  1. `assembly/context.py` 增注入位：`ctx["get_player"] = sync_wrapper(repo.load_player)`（async→同步适配，对齐 `_await_sync` 先例，或在引擎内 `asyncio.run`/事件循环桥接——注意 runner 事件循环内 asyncio.run 冲突，应改由装配层注入已 await 的目标档案快照或注入 async hook 并由壳层 await）。
  2. 锁定态持久化：对齐 `_ps_init` 先例挂 `ps["pvp_target"]`（context.py L303-320 模式），`pvp_lock` 成功时写入，`pvp_attack` 读取；生产每次指令 make_context 重建 ctx，**不落 ps 则跨指令恒丢**（M9 锻造 forge_preview P0-2 同款教训，context.py L1195-1199 注释）。
  3. 防刷计数 `pvp_daily` 挂 `_ps_init(ps, "pvp_daily", {})`；`respawn_hook` 由装配层注入（或对齐 kill_penalty 语义由世界层接线）。

### P0-2 · 战斗引擎无状态无持久化：每次 /攻击玩家 新建引擎，战斗不落会话、HP 不落档、技能库为空
- **位置**：`qbot_rpg/core/pvp.py` L245-274（`BattleEngine()` 裸构造 + 局部变量 `battle`）；L346-364（结算不回写双方档案）
- **证据（静态推导）**：
  - `BattleEngine()` 无 registry/defs → `ComboEngine(defs=None, registry=None)`、`DamagePipeline(registry=None)`（battle.py L322-343）→ `resolve_skill` 恒返回空 → 技能 defs/effects/MP 消耗/连段全部落空。
  - `battle` 为函数局部变量，每次指令新建、结算后丢弃：无 `to_snapshot`、无 `session_mgr.acquire("pvp")`、无快照续战 → 玩家互斗无法跨指令推进（回合制第二击从满血重新开战）；SET-R04「快照回写双方玩家档案」零实现（双方 HP/资源不回写）。
  - 无 `battle_reward_fn`/`dispatch_round` 集成，结算播报仅壳层 2 行模板。
- **修复建议**：对齐 `battle_commands` 的 `ctx["battle_engine"]` 装配模式（context.py L1088 注入位）+ `session_mgr.acquire(qid, "pvp", payload=snap)`（world/session.py L159-189，async 需壳层 await）+ 结算时 `pvp_settle` 内把 `battle.to_snapshot()` 经 session_mgr 落档、将双方 HP/资源一次性原子回写（SET-R04）。技能源注入 `ctx["skills"] = _table_from_registry(deps.registry, "skill")`。

### P0-3 · free 模式行动字典键错：`{"action":"guard"}` 应为 `{"type":"guard"}`，恒「回合结算失败」且双行动
- **位置**：`qbot_rpg/core/pvp.py` L268-270
- **证据（静态推导）**：`battle.enemy_act({"action": "guard"})` → `_do_action_inner` 读 `action_dict.get("type")`（battle.py L1064）→ `atype=""` → 非 normal/skill/item → `raise ValueError("未知动作类型")`（L1086）→ 被 pvp.py L271-272 except 捕获 → 「回合结算失败」。且修复后 `player_act` 内部（battle.py L1712）还会再触发一次默认 `enemy_act()` → 防守方既 guard 又反击，双行动。
- **修复建议**：free 模式改为 `battle.enemy_act({"type": "guard"})`，且不要先于 `player_act` 调用——应在 `player_act(action, params)` 之后、或改用引擎侧钩子让防守方本回合行动恒 guard（非回合制语义=进攻方连续输出、防守方一直防御，契约 TC-12 / 定稿 L353）。

### P0-4 · 偷袭检测双坏：async 协程未 await + SessionView 属性名错，偷袭恒 False
- **位置**：`qbot_rpg/core/pvp.py` L158-179（`_active_session_type`）
- **证据（静态推导）**：
  - `SessionManager.get_active` 为 **async def**（world/session.py L139），此处同步调用 `getter(qid)` → 返回协程对象（非 None）→ `getattr(coro, "type", "")` → `""` → 恒非 "battle"；且协程永不 await（泄漏 + RuntimeWarning）。
  - 即使 await，SessionView 字段名是 `session_type`（world/session.py L46），代码读 `getattr(sv, "type", "")` → 恒 `""`。同步兜底 `ctx["active_sessions"]` 也无注入。
- **修复建议**：`_active_session_type` 改为 async（壳层/装配层 await），读 `sv.session_type`；或由装配层注入已解析的 `ctx["target_in_battle"]` 布尔（对齐 `ctx["in_battle"]` 先例，context.py L1288-1292）。

---

## 三、P1（契约偏差 / 功能缺陷）

### P1-1 · FR-R2 pair_daily_limit 配置零消费；FR-R4 掉落不分胜负；FR-R5 幂等缺失
- **位置**：`qbot_rpg/core/pvp.py` L41（配置定义）、L346-364（结算）；`core/reward.py` L444-448（幂等闸依赖 ctx["tx_id"]+["ledger"]）
- **证据（静态推导）**：全仓 grep `pair_daily_limit` 仅 pvp.py 定义处；结算无配对计数、无同日对数判定（TC-18 不可达）。`dispatch_reward(loot, ctx)` 无条件授予**进攻方** ctx（无论胜负、无论战斗是否结束）→ 败方攻击也发奖、FR-R4 违约；无 `tx_id`/`ledger` → 幂等闸不生效，重复攻击重复发奖（TC-19 不可达）。
- **修复建议**：结算判定 winner 后仅胜方发奖（`dispatch_reward(loot, winner_ctx)`）；配对计数挂 ps 落档；传入 `ctx["tx_id"]=f"pvp:{qid}:{today}:{seq}"` + `ctx["ledger"]`（挂 ps）。

### P1-2 · FR-R1 超限分支伪造「防守方胜」
- **位置**：`qbot_rpg/core/pvp.py` L316-320
- **证据（静态推导）**：达上限时直接 `{"winner": "defender"}` —— 契约 TC-17 语义是「正常判负/播报但掉落 0」，即仍按真实战斗结果判胜负，仅掉落置 0；当前实现把进攻方直接判负（防守方躺赢），且未走 battle 结算。
- **修复建议**：先结算战斗取真实 winner，再按上限把 loot/exp 置 0（仅奖励封顶，胜负不变）。

### P1-3 · 回合制防守方自动普攻反击，违约 TC-11/SR-07「离线=一直防御」
- **位置**：`qbot_rpg/core/pvp.py` L266-270 + `core/battle.py` L1624-1646
- **证据（静态推导）**：turn_based 模式不注入防守方行动，`player_act` 内部 `enemy_act()` 无参 → `_ai_action_dict()`（无 enemy_ai → None）→ 回落默认普攻 `{"type":"normal"}`（battle.py L1636-1639）→ 离线/不操作的防守方每回合自动反击，与「防守方不操作则一直防御」（定稿 L352、B-5 注释自述仅 free 模式实现）矛盾。
- **修复建议**：回合制下防守方回合注入 `{"type":"guard"}`（对齐 SR-07「自然过=自动防御」）；若防守方有真实在线操作再允许其行动（当前双原语下防守方无攻击入口，恒 guard 即为契约语义）。

### P1-4 · 等级门槛单向校验（FR-R3 双向缺失）+ 目标在线校验缺失
- **位置**：`qbot_rpg/core/pvp.py` L206-209（仅 `ctx.get("level")` 进攻方）；L190-217（无在线判定）
- **证据（静态推导）**：FR-R3「双方均须达标」（契约 L192）；m11 启动包 §2.3「发起时目标需在线」。代码只查进攻方等级；目标等级/在线均不查（全仓无在线数据源，需装配层注入）。
- **修复建议**：`pvp_lock` 守卫链补 `target level >= gate`（读 `_target_status(target)["level"]`）；在线判定由装配层注入 presence 源（如 `ctx["online_qids"]` 集合），不在线拒绝并提示。

### P1-5 · 技能解析双失效 + 错误文案错位
- **位置**：`qbot_rpg/commands/pvp_commands.py` L149-167、L285-287；`qbot_rpg/core/pvp.py` L277-302
- **证据（静态推导）**：
  1. 壳层 `_resolve_skill` 读 `ctx["skills"]`——全仓 grep 证实 `assembly/context.py` **从未注入 `"skills"`**（`_table_from_registry` 从未以 "skill" 调用；`resolve_skill` 亦无注入；battle_commands / basic_commands 同病，属仓级既有缺口，PVP 为其新增受害面）→ `/攻击玩家 2` 恒 `skill_id=None` → 恒回 `pvp_attack_no_target`（「请先 /锁定玩家」——技能值域错误用了未锁定文案，误导玩家）。
  2. 即使壳层通了，引擎 `_resolve_skill_action` 再解析一次（同一缺失的 `ctx["skills"]`）→ 恒回落 `"normal"` 普攻；技能双解析冗余且两处可能漂移。
- **修复建议**：装配层注入 `ctx["skills"]`（`_table_from_registry(deps.registry, "skill")`，对齐 items 注入 L1097）；壳层/引擎单点解析：壳层已解析出 skill_id 后直接传 `{"action":"skill","skill_id":sid}` 形态给引擎（引擎不再重解析），或引擎独占解析并删壳层重复逻辑；技能非法时改回 `pvp_err_missing`/新模板（非「未锁定」）。

### P1-6 · `_combatant_of` 与生产 ctx["player"] 形态不符：恒「开战失败」
- **位置**：`qbot_rpg/core/pvp.py` L89-126、L250-252；`qbot_rpg/data/player.py` L22-53、L72-90
- **证据（静态推导）**：生产 `ctx["player"]` 是 **frozen dataclass `Player`**（非 Mapping），`_combatant_of` 对 `.get()` 调用 → AttributeError → pvp.py L255-260 except 捕获 → 「开战失败」。且 `player.attributes` 是 `PlayerAttributes` dataclass（base/bonus{flat,pct}/temp{pct,flat}/cond），`_attr` 期望 `{base:{},bonus:{flat,pct},temp:{flat,pct}}` dict 形态并读 `bonus.get("pct")`——dataclass 上无 `.get`。进攻方侧 `isinstance(ctx.get("player"), Mapping)` 为 False → 回落 `{"id":...,"name":"我"}`（满默认面板 500/500/50 系）。
- **修复建议**：`_combatant_of` 改为鸭子兼容：`player.get if Mapping else getattr(player, ...)`；属性合成直接复用 `assembly/context._attr_final`/`calc_all_final_attributes`（context.py L354-370）产出的 `ctx["attr_final"]`（已有正确管线），或对 PlayerAttributes 字段直读（base/bonus.flat/bonus.pct/temp.pct/temp.flat/cond）。

### P1-7 · 结算胜负判定单向 + ended 恒 False（含击杀路径也不报胜）
- **位置**：`qbot_rpg/core/pvp.py` L322-344
- **证据（静态推导）**：
  1. `ended = bool(state.get("ended")) or str(status) in ("ended","settle","lost")`——`battle_state()` 深拷贝 `_snap` 顶层**无 "ended" 键**（battle.py L1873-1875）；终态 `status` 值为 `STATUS_WIN="win" / STATUS_LOSE="lose" / STATUS_DRAW="draw"`（battle.py L742-783），**无一命中**该元组 → ended 恒 False，敌方当场死亡时 `hp=0` 但 `winner` 仍恒 None（`hp<=0` 判定挂在 `ended` 之后）→ 击杀也不报胜。
  2. `winner = "player" if ended and hp<=0`——只认进攻方胜；进攻方死亡/平局无分支（winner=None）。
  3. 伤害恒 0：`turn_result` 是 `TurnReport`（dataclass：turn/phases/player/enemy/ended/status/log/outcomes，battle.py L239-249），无 `damage` 字段 → `getattr(turn_result, "damage", 0)` 恒 0 → 壳层伤害行恒显示 0（真实伤害在 `turn_result.outcomes[].final_damage`）。
- **修复建议**：从 `battle.result()`/`_snap["status"]` 判终态与胜负（对齐 battle_commands `report.ended`/`report.status` 消费）；补进攻方败/平局分支；伤害取 `turn_result.outcomes` 聚合 `final_damage`；未终局时输出本回合伤害 + 双方剩余 HP（回合制持续推进需 P0-2 落档支撑）。

### P1-8 · 壳层-引擎 result 契约错位：嵌套字段被当顶层读
- **位置**：`qbot_rpg/core/pvp.py` L366-369（返回 `{"ok","message","result":{...}}`）vs `qbot_rpg/commands/pvp_commands.py` L302-313
- **证据（静态推导）**：壳层 `_render_attack_result` 读 `result.get("name"/"damage"/"hp"/"max_hp"/"result")`——引擎把 name/damage 等嵌在 `result["result"]` 内 → 顶层全 None → name 回落「对方」、伤害行被丢弃、`result.get("result")` 拿到内层 dict → `str(dict)` 整段 Python 字典字面量打进回复（「✅ 对 对方 发起攻击：{'name': ...}」）。锁状态卡同理：引擎返回 `equipment_summary` 字符串，壳层读 `target.get("equipment")` 恒 None → 恒「无」（P2-4）。
- **修复建议**：统一契约——壳层读 `result["result"]["name"/"damage"/...]`（或引擎把字段提升到顶层，二选一并在模块头注释锁定）；锁卡改读 `target["equipment_summary"]` 直用。

### P1-9 · 回合制无续战 + 攻击方无失败回写（含 SET-R04 快照回写整体缺失）
- **位置**：`qbot_rpg/core/pvp.py` L245-274（引擎局部新建）、L346-364（仅杀敌分支）
- **证据（静态推导）**：同 P0-2。SET-R04「战斗内资源变化一次性原子回写双方档案」零实现；回合制双方 HP 变化不落档 → 即便 P0-2 修好落档，当前结算也不回写。
- **修复建议**：结算统一入口（胜/败/平/未终局四分支）把双方 combatant HP/MP/资源经 `_player_of(ctx)` 回写（对齐 M8 currencies 就地引用落档先例，context.py L1163-1167），并处理 frozen dataclass 需经 repository save 的路径。

---

## 四、P2（质量 / 边界）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| P2-1 | pvp.py L122-124 | combatant 用 `def_` 键，引擎伤害管线实读 `dfn`/`con`/`foc`/`spd`/`lck`/`int`（battle.py L186、L1323-1405）——`def_` 是无效字段；`foc/con/int/mag` 未构建 → 恒默认 50 | 按 `_DEFAULT_STATS` 键全集构建（atk/dfn/foc/con/spd/lck/int/mag…），或直接 `merged=_DEFAULT_STATS; merged.update(...)` |
| P2-2 | pvp_commands.py L87、L196 | QQ 纯数字 9-11 位硬校验：契约 TC-01 等用例号（90001 等 5 位）不可达引擎；测试/私聊场景被拦 | 校验放宽为「纯数字 5-11 位」或由注入的 QQ 规则配置化（对齐 4e CMD-01 L41 口径但兼容测试） |
| P2-3 | pvp.py L102-112 | `_attr` 公式 `(b+bf)*(1+bp)+tf*(1+tp)` 与真实管线 `calc_final_attr`（base_total×(1+pct)×(1+temp_pct)+temp_flat+cond，player_attributes.py L137-162）近似但缺 `cond` 层、pct 语义为百分数（10=+10%）时未 ÷100 对齐 | 复用 `ctx["attr_final"]`（context.py L1145 已算好最终层） |
| P2-4 | pvp_commands.py L264-265 vs pvp.py L144-153 | 锁卡装备摘要字段错位（引擎给 `equipment_summary`，壳层读 `equipment`）恒「无」 | 壳层读 `target.get("equipment_summary")` 直用 |
| P2-5 | pvp_tpl.py | 审查单称 19 个模板，实际 20 键（err 4 + engine 2 + lock 9 + attack 3 + gate 2）；`pvp_lock_no_target`/`pvp_not_registered` 无消费方（死模板） | 校对文档计数；删除或登记死模板 |
| P2-6 | pvp.py L282-302 vs pvp_commands.py L149-167 | 技能解析逻辑两处重复实现（序号→配置序），漂移风险 | 单点收敛（见 P1-5） |
| P2-7 | pvp.py L266、pvp_cfg L46-65 | `mode` 值域（turn_based/free）未校验：任意其它字符串静默走回合制分支 | pvp_cfg 逐键枚举校验回落默认 |
| P2-8 | pvp.py L158-179、L84-85、L259-260、L271-272 | 多处 `except Exception: return None/False/统一文案` 静默吞异常，调试时无法区分「未接线」与「真实失败」 | 至少 `ai_errors` 式记录（对齐 battle.py L1553）或区分文案 |

---

## 五、无问题维度（确认通过）

1. **指令注册/白名单/前缀（部署 P0 五型·注册面）**：`router_setup.py` L104-105 `REGISTER_GROUPS` 已含 `pvp_commands.register_pvp_commands`；`parsers.py` L150-151 `DEFAULT_WHITELIST` 已含 锁定玩家/攻击玩家；`DEFAULT_PREFIX_REQUIRED` 未加（可快捷，F-9 声明一致）；CommandSpec 默认 whitelisted=True、无 GM 标记。Router 白名单最长前缀匹配（router.py L441-457）下「锁定玩家」优先于 stub「锁定」，**无遮蔽冲突**（stub 注册在 L214-232 亦不重名）。check_consistency 硬不一致为空（"锁定"/"锁定玩家"均在白名单）。
2. **make_context 注入（部署 P0 五型·ctx 面）**：`pvp_commands.register_pvp_commands` 签名 `(router, *, make_context=None)` 对齐先例；`_wrap` handler `(parsed, *a, **k)` 具 VAR_KEYWORD → runner `_invoke_handler` 的 `_accepts_ctx` 判定 True 并以 `ctx=ctx` 注入（runner.py L276-315）——生产路径不走 `_ctx()` 的 RuntimeError【待接线】分支（该分支仅裸调用时触发，F-8 声明成立）。
3. **决斗四指令不复活（用户拍板 2026-08-28）**：全仓无 `/决斗`/接受/拒绝/信息 注册、无 INVITE 状态机残留；CMD-01~04 仅存于契约文档追溯段。✓
4. **CMD-05/06 双原语**：`/锁定玩家 <QQ号>`（显示对方状态：等级/职业/血量/装备摘要）、`/攻击玩家 <技能序号>`（序号解析同 /攻击、不加 `*`）——指令面完整，壳层参数解析 ≤1 位置参数、4 类错误模板（ERR_MISSING/TOO_MANY/UNKNOWN_SEP/RESERVED 对齐 parsers 常量）、注册门槛 RUL-08 齐备。✓
5. **玩家互斗非镜像**：`pvp_attack` 把 `_combatant_of(target)`（真实玩家档案）作为 enemy 侧传入 `BattleEngine.start(battle_type="pvp")`——**设计符合 B-1/定稿 L349**（被注入缺口卡死运行，非设计错误）。✓
6. **模板配置化**：pvp_tpl 20 键全部并入 `DEFAULT_TEMPLATES`（templates/__init__.py L49-50），占位符白名单与模板引用一致；渲染零 emoji 铁律遵守（仅 ✅/❌）。✓
7. **settings.pvp 三态容错（B-3）**：`pvp_cfg` 对 段缺失/非 Mapping/逐键类型非法均回落默认不报错，对齐 fishing_cfg 口径；CFG-01 enabled/02 level_gate/04 mode/05 kill_penalty/06 loot/07 daily_reward_limit 有消费点（消费正确性见 P0/P1），CFG-03/04/05（邀请/回合超时/僵尸天）属已删决斗流程，不实现合法。✓
8. **技能解析双形态兜底（B-4）**：`_resolve_skill_action` 对 skills 映射 / resolve_skill callable 双形态兜底普攻——设计自洽（问题在注入，见 P1-5）。✓
9. **free 模式「防守方一直防御」设计意图（B-5）**：意图正确且对齐定稿 L352，实现键错见 P0-3。✓
10. **壳层防御性（F-1）**：引擎缺失/异常/非 Mapping 返回均有明确文案（pvp_engine_missing/unavailable），不静默空回。✓

---

## 六、验收点覆盖矩阵（契约 → 现状）

| 验收点 | 现状 | 判定 |
|---|---|---|
| CMD-05/06 双原语 | 指令面 ✓；运行被 P0-1 卡死 | 部分 |
| 玩家互斗非镜像（档案→敌方侧） | 设计 ✓，运行被 P1-6 卡死 | 部分 |
| 偷袭语义（目标战斗会话可偷袭） | P0-4 双坏恒 False | ✗ |
| 防刷 FR-R1~R7 | R1 错判负/R2 零消费/R4 反向/R5 无幂等/R6 无赌钱 ✓（无金额参数）/R7 串行队列由 runner 承担 ✓ | ✗ |
| settings.pvp CFG-01~08 | 读取容错 ✓；CFG-08 零消费 | 部分 |
| 结算 SET-R01~05 | R1 单向/R2 掉落乱发/R3 钩子未注入/R4 零回写/R5 无防刷判负分支（超限伪造胜） | ✗ |
| 决斗四指令已删不复活 | ✓ 全仓无残留 | ✓ |
| TC-01~20 | TC-06/07/09/13/16/19/20 等依赖已删流程/幂等/快照——按「只保留战斗态」口径 TC-10/11/12/14/15/17/18 为有效验收，全部当前不可达 | ✗ |

---

## 七、修复优先级建议（收口顺序）

1. **P0-1 装配注入**（context.py 增 get_player/pvp_target(ps)/pvp_daily(ps)/respawn_hook/skills 注入 + 壳层 async 适配）——不修则其余全部不可达。
2. **P0-2 战斗持久化**（session_mgr.acquire("pvp") + to_snapshot + 结算回写）——PVP 的「战斗」语义成立前提。
3. **P0-3/P0-4**（free 行动键、偷袭 async+属性名）——两个小改，验收 TC-11/12 直接相关。
4. **P1-5/P1-8**（技能单点解析、result 契约对齐）——玩家可见文案正确性。
5. **P1-1/2/3/4/7 + P2 清单** 随收口批次修复。

---

*报告生成：静态审查（无沙箱、未运行任何命令）；运行时行为结论均标注「静态推导」。审查档位：j-space full。*
