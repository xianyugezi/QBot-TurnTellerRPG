# 审查 · M10 钓鱼批A-5 模式路由+装配+模板+编辑器（fishing_mode / context 注入 / router_setup / parsers / fishing_tpl / fishing_editor_service）

> 方式：j-space 静态审查（**full 档**：directed-focus + introspection 已加载）· 本环境无 bash 沙箱，**零命令执行**，全部结论为静态推导
> 日期：2026-09-01 · 审查人：主 agent（j-space 会话）
> 文件清单（本批）：
> - `qbot_rpg/core/fishing_mode.py`（mode_of / mode_matrix / feature_available / command_allowed，208 行）
> - `qbot_rpg/assembly/context.py`（fishing/fish_state/consume_bait/mode/king hooks 注入，L460-500 + L1129-1140）
> - `qbot_rpg/assembly/router_setup.py`（REGISTER_GROUPS 钓鱼注册，批8 审查 A3 P0-1 已修验证）
> - `qbot_rpg/commands/parsers.py`（DEFAULT_WHITELIST 钓鱼词）
> - `qbot_rpg/core/templates/fishing_tpl.py`（fish_* 模板分区）
> - `qbot_rpg/editor/fishing_editor_service.py`（编辑器服务层）
> 参考：`docs/细化/细化_2c1b_钓鱼流程状态机.md`（§2.4 模式前缀 / §六 TC-09/14/13/20）/ `docs/m10_shared_contract.md`（§五 铁律）/ 细化_5a_编辑器契约（§七 schema）/ 定稿（经仓库契约转引口径）
> 交叉核对：`qbot_rpg/core/fishing.py`（FishingEngine）、`fishing_bait.py`、`fishing_roll.py`、`fishing_cast.py`、`fishing_settle.py`、`fishing_king.py`、`fishing_codex.py`、`fishing_settings.py`、`commands/fishing_commands.py`、`fishing_reel_commands.py`、`fishing_codex_commands.py`、`codex_commands.py`、`assembly/runner.py`、`commands/processing.py`、`tests/unit/test_fishing_*.py`、`test_assembly_router.py`、`docs/审查报告/审查_M10_A3_jspace.md`（A3 修复验证基准）

> ⚠️ 可达性说明：定稿原文在仓库外（glob 不可达），本报告以仓库内契约（m10_shared_contract §一 声称与定稿 §三 逐键一致）与细化 2c1b 为准对表；定稿行号均为转引口径。
> ⚠️ 重要前提：**批6 路6A 已收口**（context hooks + fishing_tpl 分区已并入 DEFAULT_TEMPLATES）；**批8 审查 A3 的 P0-1（指令注册）已修**（本批验证）；A3 其余修复逐条复核见 §五。

## 结论速览

| 级别 | 数量 | 要点 |
|---|---|---|
| P0 | 1 | ①`settle_catch` 全仓零消费方——simple 直出与 full 收杆成功后均无出鱼结算调用，图鉴点亮/奖励/熟练经验/TC-24/25/经济闭环整链不可达 |
| P1 | 4 | ②consume_bait hook 返回值契约错位（A3 P0-2 只修签名未修返回值，bait_used 恒 None）③金闪/鱼王整链死链（king_hit 判定零消费方，TC-13/20 不可达）④收杆成功消息 kind 恒回退「微动」⑤simple 模式 cast_fishing 消息/state 与引擎语义不符 |
| P2 | 8 | ⑥simple 拒绝文案误导 ⑦编辑器 crown_preview/simulate 阈值参数化不一致 ⑧模板双源+intent_ref 前缀差异未清理 ⑨装配冒烟断言未覆盖钓鱼三词 ⑩ctx mode/king hooks 死注入 ⑪_engine_of 直改私有 _roll_hook ⑫壳层「批6 待迁移」注释过时 |

---

## 一、A3（批8）修复验证（维度③ 装配注入一致性）

| A3 编号 | 修复项 | 验证结果 | 证据（静态推导） |
|---|---|---|---|
| P0-1 | 三指令注册+白名单 | ✅ **已修完整** | `router_setup.py` L97-99 REGISTER_GROUPS 已含 register_fishing_commands / register_fishing_reel_commands；`parsers.py` L145-147 DEFAULT_WHITELIST 已含「钓鱼/鱼讯/收杆」三词；`check_consistency`（router_setup L239-260）registered_not_whitelisted 空 → 装配冒烟不再红拦 |
| P0-2 | consume_bait hook 签名 | ⚠️ **只修了一半** | `context.py` L471 `_hook(_ctx, _engine=None)` 收两参——TypeError 已消除（A3 原判根因修复）；但 **返回值仍是 dict**（`consume_bait` 返回 {ok, used, had_bait}），而引擎 `fishing.py` L421-422 `result = hook(ctx, self); return result if isinstance(result, str) and result else None` **期望 Optional[str]（饵 id）** → dict 非 str → 恒返回 None → `bait_used` 生产恒 None → 下钩消息恒「无饵抛竿」（误导）。**扣饵实际发生**（fishing_bait 内部 `_remove_item` 已扣），但契约错位未修 → 新 P1-1 |
| P1-1 | /鱼讯 bite_check 触发 | ✅ 已修 | `fishing_reel_commands.py` L233-240：state==WAITING 时调 `eng.bite_check(ctx)` 懒判推进（零定时器合规）；测试 `test_bite_triggered` 等覆盖 |
| P1-2 | bite_kind 键漂移 | ✅ 已修 | L253 `fs.get("kind")`；引擎落档键 `kind`（fishing.py L637）；测试夹具已同步改 `kind`（test_fishing_reel_commands L63/L73） |
| P1-3 | 注入/自建 roll_hook 两分支 | ✅ 已修（有小瑕疵） | L179-180 注入引擎无 hook 时兜底包一层 `_make_roll_hook`；自建分支带 hook → 两分支一致。瑕疵：直改私有属性 `eng._roll_hook`（→ P2-11） |
| P1-4 | simple 壳层路由 | ✅ 已修（文案待优化） | L223/L285 消费 `command_allowed`，simple 下 /鱼讯 /收杆 明确拒绝；但拒绝文案用 `fish_bite_idle`「无进行中钓局」——与模式限制语义混淆（→ P2-6） |
| P2-1 | roll_rarity cfg 语义 | ✅ 已修 | L196 `roll_rarity(choice, _ctx.get("settings"), _ctx, _ctx.get("rng"))`——cfg 传 settings 全量、ctx 传玩家上下文 |
| P2-2/P2-4 | 模板双源/intent_ref 前缀 | ❌ 未修 | 三壳层 `_DEF_*` fallback 仍与 fishing_tpl 逐字并存；`fish_intent_ref` 模板无「鱼讯参考：」前缀而 fallback 有（→ P2-8） |
| P2-3 | 注释过时 | ❌ 未修 | 四文件头多处「批6 才建/待迁移」与批6 已收口不符（→ P2-12） |
| P2-5 | 装配测试 | ❌ 未修 | test_assembly_router 的 ALL_REGISTERED 断言集合未含钓鱼三词（→ P2-9） |

---

## 二、维度① 定稿落地核对

### 2.1 三态行为矩阵（细化 §2.4 / TC-09/14）——**代码正确，鱼王行与实现不符（P1-2）**

| 核对项 | 结果 | 证据 |
|---|---|---|
| full：S0→S1→S2→S3→{ST,SL,BOSS} | ✅ | `mode_matrix`（fishing_mode L112-120）path/wait/bite/reel/king 全 True、direct/reject_all False；test_matrix_full_complete_fsm 断言一致 |
| simple：S0→S1→ST 短接 | ✅ | L121-129 direct=True、wait/bite/reel/king 全 False（TC-14 无 S2/S3 实例）；test_matrix_simple_shortcut 断言一致 |
| off：全拒绝 | ✅ | L130-138 reject_all=True；test_matrix_off_reject_all 一致 |
| mode_of 归一（非法/缺失回落 full） | ✅ | L73-86 仅 MODE_VALUES 内 str 放行；V4 枚举硬错归校验器（fishing_models L388-391）不读段拦——契约 §三 口径一致；test_mode_of_* 全覆盖 |
| command_allowed（GU-01） | ✅ | L178-192 off 全拒 / simple 仅 fish / full 三指令；test_command_allowed 全覆盖 |
| **king=True 与实现可达性** | ❌ **不一致** | 矩阵声明 full 下 king=True（TR-10 BOSS 战+金闪），但全仓 `king_hit` 判定零消费方（见 P1-2）——矩阵是「宣称」，实现不可达 |

### 2.2 模板零 emoji + 分区完整性（铁律 6）——**✅ 通过**

| 核对项 | 结果 | 证据 |
|---|---|---|
| 分区 13 key 齐全 | ✅ | fishing_tpl DEFAULT_TEMPLATES：fish_off/spot_list_header/spot_line/spot_empty/intent_ref + bite_idle/waiting/triggered + reel_bad_choice/timeout/stop/success + codex 3 key；并入 DEFAULT_TEMPLATES（templates/__init__ L41/L68）；test_fishing_tpl L32-38 全 key 断言 |
| PLACEHOLDER_WHITELIST 全 key | ✅ | L54-69 逐 key 登记；test_all_keys_have_whitelist 断言 |
| 零 emoji | ✅ | test_no_emoji_in_templates / test_no_emoji_in_rendered 全模板静态断言 |
| 内容包可覆盖 | ✅ | resolve_templates 白名单内覆盖（__init__ L100-111）；test override 用例通过 |
| 缺键占位符原样保留 | ✅ | _safe_format 缺键不抛；test 断言 `{spot_name}` 保留 |

### 2.3 编辑器 schema（细化_5a P-07 元数据驱动 / §七）——**✅ 主体正确，2 处参数化瑕疵（P2-7/P2-8）**

| 核对项 | 结果 | 证据 |
|---|---|---|
| fish_card_schema 九键 | ✅ | 薄封装 FISHING_SETTINGS_FIELD_DEFS（fishing_settings L94-114）零重写；mode 补 enum=MODE_VALUES（L171-172）；bait_ids 补 element（L173-174）；嵌套 obj 补 children（L175-176 + _OBJ_CHILDREN L195-202）——与契约 §一 9 键逐键一致 |
| CSV 13 列双向 | ✅ | fish_csv_export/import 直接委托 fishing_csv.fishing_to_csv/csv_to_fishing（同款列序 SPECIES_CSV_COLUMNS = CSV_COLUMNS） |
| CSV 预检 V1/V3/V5/V6 口径 | ✅ | fish_csv_validate：id 必填/唯一（V5）、区间序（V1）、枚举（V6）、hours 格式+分钟≤59（V6 增强）、spots 非空（V6）、preferred_bait 引用（V3，bait_ids 缺省跳过不误报）——与 fishing_models 规则码口径一致；E-3 声明不做包级校验（V2/V4/W1 归内容包校验器）合理 |
| crown_preview / simulate_catches | ⚠️ 2 处 | ①crown_preview L422 `"thresholds": dict(DEFAULT_CROWN_THRESHOLDS)` **恒返回默认阈值**——调用方传自定义 thresholds 时判定用自定义、返回体却写默认（UI 展示误导）；②simulate_catches `_THEORETICAL_PROBS`（L123-130）按**默认阈值** 5/85/95 算理论概率，thresholds 参数化后不重算——自定义阈值下理论对比失真 |

---

## 三、维度② 代码质量（bug / 边界 / 装配注入一致性）

### P0-1 出鱼结算整链零消费方 → simple 直出与 full 收杆后均无结算（图鉴/奖励/熟练全失效）

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L294-323（cmd_fish_reel 调 reel_in 后直接渲染 fish_reel_success，无 settle_catch 调用）；`qbot_rpg/commands/fishing_commands.py` L395-414（_cast_forward 转发 cast_fishing，simple 直出后无结算）；`qbot_rpg/core/fishing_settle.py` L340（settle_catch 定义，**全仓唯一出现 = 定义 + __all__**）

**静态推导**：全仓 grep `settle_catch` 调用方 = 空（fishing_settle.py 仅定义/导出；fishing_cast/指令壳/runner 均无）。引擎 `reel_in` 成功返回 `settle_pending: True`（fishing.py L716/L728）与 `start_fishing` simple 分支 `settle_pending: True`（L564）——**「结算待接线」标志在指令链上无人消费**。后果：
- full 收杆成功 → 玩家看到「收杆成功！」消息，但**图鉴不点亮、金币奖励不发、熟练经验不入账**（TC-24/25 不可达）；
- simple `/钓鱼` 直出 → 同样只扣饵+日计数，无出鱼（TC-09/14「直出」语义不成立）；
- `fishing_economy.daily_ledger_check` 的流入侧（coins=20×20）与整条经济闭环（R-08~R-12）依赖结算 → 连带不可达。

**修复**：cmd_fish_reel 成功分支（reeled=True）调 `settle_catch(ctx, rng=ctx.get("rng"))` 并按返回组装出鱼消息（size/weight/crown/首获/奖励）；_cast_forward 对 simple 直出（got["mode"]=="simple"）同样接 settle_catch（引擎 M-1 已落 last 快照）；补全链测试。

### P1-1 consume_bait hook 返回值契约错位（A3 P0-2 修复不完整）

**位置**：`qbot_rpg/assembly/context.py` L471-477（_hook 返回 `consume_bait(ctx, _ctx)` 的 dict）；`qbot_rpg/core/fishing.py` L418-424（引擎期望 Optional[str]）

**静态推导**：引擎 `_consume_bait`：`result = hook(ctx, self); return result if isinstance(result, str) and result else None`——装配 hook 返回 `{ok, used, had_bait}` dict → `isinstance(result, str)` False → 恒 None。扣饵**实际发生**（fishing_bait.consume_bait 内部经 remove_item hook 扣 1），但 `bait_used` 落档 None → 下钩消息恒显示「无饵抛竿（不吃对口饵加成）」（MSG_BAIT_NONE）——有饵玩家被误导；边界：玩家仅剩 1 饵时扣完 → has_matching_bait=False → FULL 恒 pull_odds 60/31/9（满配 54/37/9 不可达）。fishing.py 的 hook 契约注释（L259-260「Optional[str]」）与 fishing_bait 返回 dict（L205-230）双方文档都对、装配包装**两边都不转**。

**修复**：`_hook` 内转形态：`r = consume_bait(ctx, _ctx); return r.get("used") if isinstance(r, Mapping) and r.get("ok") else None`；测试补「装配 hook → 引擎 start_fishing 返回 bait_used=饵 id」。

### P1-2 金闪/鱼王整链死链（TC-13/20 不可达；mode_matrix king=True 与实现不符）

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L236（`eng.bite_check(ctx)` 不传 king_hit）；`qbot_rpg/core/fishing_cast.py` L229-244（bite_trigger 默认 king_hit=False，且**本身零消费方**）；`qbot_rpg/assembly/context.py` L1138-1139（ctx["king_event"]/["king_victory_record"] hooks 注入但**全仓零调用**）；`qbot_rpg/core/fishing_king.py` L142（king_event_available 仅定义+装配委托，无业务调用方）

**静态推导**：全仓 grep：`king_event_available` 唯一业务出口是 context 的薄委托（L496-507），而该 hook 无任何指令壳/引擎消费；`bite_trigger`（带 king_hit 参数的唯一候选接线点）零调用方（cmd_fish_bite 直调引擎 bite_check 而非 bite_trigger）。→ `bite_check(ctx)` 恒 king_hit=False → fish_intent_of golden 恒 False（fishing.py L168）→ **金闪永不出现、TR-10 鱼王 BOSS 战不可达**。与 mode_matrix full 行 king=True（fishing_mode L117）、细化 TC-13（金闪隔离）/TC-20（猛烈+金闪收杆前处理）矛盾。

**修复**：cmd_fish_bite 到期分支（bite=True 且 kind==violent）调 `ctx["king_event"](target_species_id, rng)` 判定（full 模式 + king_available 门控）→ 命中传 king_hit=True 重跑 bite_check 或覆写 golden；BOSS 战接线（批4 预留 enemy_id）与 king_victory_record 在讨伐结算调用；测试补「猛烈+金闪」全链。

### P1-3 收杆成功消息 kind 恒回退「微动」

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L313-319（成功分支读 `result.get("kind") or result.get("bite_kind")`）；`qbot_rpg/core/fishing.py` L706-716/L719-728（reel_in 成功返回体**无 kind 键**——kind 只落 fs["last"] 快照后被 _clear_session 清理）

**静态推导**：reel_in 成功返回 `{ok, choice, state, reeled, roll, settle_pending, message}`——无 kind/golden；壳 L319 两个键都读不到 → `kind="micro"` → `/收杆 自动` 在「拉扯/猛烈」咬钩后仍显示「收杆成功！微动 · 普通」。A3 P1-2 只修了 /鱼讯 的 kind 读取（L253），**收杆成功路径是另一处读取点，同样漂移**（且带 bite_kind 残留）。

**修复**：L319 改读 `result.get("roll", {}).get("kind")` 或引擎成功返回体补 kind/golden 键（推荐：reel_in 返回体加 `"kind"`/`"golden"`，与 fs["last"] 同源）；测试断言「S3 拉扯 → /收杆 成功消息含『拉扯』」。

### P1-4 simple 模式 cast_fishing 组装消息/state 与引擎语义不符

**位置**：`qbot_rpg/core/fishing_cast.py` L205-223（成功分支统一组装 MSG_CAST_OK/IMMEDIATE + state=STATE_WAITING）；`qbot_rpg/core/fishing.py` L540-568（simple 分支返回 message=MSG_SIMPLE_DIRECT、落档 state=STATE_REELED）

**静态推导**：simple 下 start_fishing 返回无 wait_sec 键 → cast_fishing `wait_sec = int(got.get("wait_sec") or 0)` → 0 → 走 MSG_CAST_IMMEDIATE「鱼讯即刻可查（即收）」——但 simple 无鱼讯流程（/鱼讯 被 command_allowed 拒绝）→ **消息引导玩家去查不存在的鱼讯**；且返回体 state=STATE_WAITING（L220 硬编码）与 fs 实际落档 STATE_REELED 不一致（返回体误导后续消费方/测试）。

**修复**：cast_fishing 先判 `got.get("mode") == "simple"` → 透传 got["message"]（MSG_SIMPLE_DIRECT）与 got["state"]（REELED）；full 保持现有组装。

---

## 四、维度③ 遗漏（含 P2 明细）

| # | 遗漏项 | 说明 | 级别 |
|---|---|---|---|
| P2-6 | simple 拒绝文案误导 | cmd_fish_bite L224 / cmd_fish_reel L286：simple 拒绝渲染 fish_bite_idle「无进行中钓局」——玩家无法区分「模式限制」与「无会话」。修复：simple 用专属文案（对齐引擎 MSG_SIMPLE_NO_WAIT「simple 模式无等待/鱼讯流程」） | P2 |
| P2-7 | crown_preview thresholds 返回写死默认 | fishing_editor_service.py L422 恒 `dict(DEFAULT_CROWN_THRESHOLDS)`；自定义阈值时判定与返回体不一致（UI 误导）。修复：返回归一后的实际阈值（crown_of 三态归一结果） | P2 |
| P2-8 | simulate_catches theoretical 阈值参数化失真 | L123-130 理论概率按默认 5/85/95 写死；thresholds 参数化后不重算。修复：按传入阈值重算六档理论概率，或文档标注仅默认阈值有效 | P2 |
| P2-9 | 装配冒烟断言未覆盖钓鱼 | test_assembly_router.py L329 `set(ALL_REGISTERED) <= set(DEFAULT_WHITELIST)`——ALL_REGISTERED 未含「钓鱼/鱼讯/收杆」→ 三指令注册回归无守卫；check_consistency 抽样锚点（L339）也未含。修复：ALL_REGISTERED 补三词 | P2 |
| P2-10 | ctx mode/king hooks 死注入 | context.py L1136-1139：ctx["mode"]/["king_event"]/["king_victory_record"] 注入但全仓零消费（引擎 _mode 读 fishing_cfg、壳 _mode_of 读 fishing_cfg）→ 装配面宣称已接线、实际无消费方（与 P1-2 联动）。修复：接线或标注【待接线】 | P2 |
| P2-11 | _engine_of 直改私有 _roll_hook | fishing_reel_commands.py L179-180 `eng._roll_hook = ...` 破封装（引擎为纯状态机，无公开 setter）。修复：FishingEngine 加构造/公开注入位或壳层持有包装 | P2 |
| P2-12 | 壳层「批6 待迁移」注释过时 | fishing_commands.py L56-62（F-6/F-7）、fishing_cast.py L30/L77、fishing_reel_commands.py L41-42（R-4）、fishing_codex_commands.py L73-74（D-5）——「批6 才建 fishing_tpl/待装配注入」与批6 已收口现状不符（A3 P2-3 未修） | P2 |
| P2-13 | 模板双源 + intent_ref 前缀差异 | 三壳层 _DEF_* fallback 与 fishing_tpl 逐字并存（fishing_commands L167-171 / fishing_reel_commands L98-104 / fishing_codex_commands L76-78）——双源漂移风险；`fish_intent_ref` 模板无「鱼讯参考：」前缀、fallback 有（实际渲染 tpl_of 恒命中 → 前缀消失，与 fallback 形态不一致，A3 P2-2/P2-4 未修）。修复：删 fallback 统一走 tpl_of，或统一前缀 | P2 |

---

## 五、修复优先级汇总

| 编号 | 级别 | 位置 | 修复建议 |
|---|---|---|---|
| P0-1 | P0 | fishing_reel_commands.py L294-323 / fishing_commands.py L395-414 / fishing_settle.py L340 | 收杆成功（reeled=True）与 simple 直出后调 settle_catch 并渲染出鱼消息；补全链测试 |
| P1-1 | P1 | context.py L471-477 / fishing.py L418-424 | _hook 返回值转 str 饵 id（`r.get("used") if Mapping and ok else None`） |
| P1-2 | P1 | fishing_reel_commands.py L236 / context.py L1138-1139 / fishing_cast.py L229 | 猛烈鱼讯到期分支接 king_event hook → king_hit=True；BOSS 战与胜利计次接线 |
| P1-3 | P1 | fishing_reel_commands.py L313-319 / fishing.py L706-728 | 收杆成功消息 kind 读 fs["last"]["kind"] 或引擎返回体补 kind/golden |
| P1-4 | P1 | fishing_cast.py L205-223 | simple 分支透传 got["message"]/got["state"]（MSG_SIMPLE_DIRECT / REELED） |
| P2-6~P2-13 | P2 | 见 §四 | 逐条按上表修复 |

---

## 六、结论（静态推导声明）

- 批8 审查 A3 修复验证：**P0-1 完整修复**（注册+白名单）；P0-2 **签名已修、返回值契约未修**（降级为 P1-1 遗留）；P1-1/P1-2/P1-3/P1-4/P2-1 全部修复；P2-2/3/4/5 未修（本批登记）。
- 本批模式路由/矩阵/门控/模板/编辑器 schema 本体质量高（测试覆盖充分）；**最大风险在装配层跨模块接线**：结算（P0-1）、金闪（P1-2）两条核心链零消费方——「装配注入已收口」的宣称与业务消费方实际存在缺口。
- 全部结论基于文件静态阅读与仓库内交叉核对，未执行任何命令/脚本/运行验证；「恒 None」「不可达」「零调用方」等行为结论均为代码路径静态推导。

*静态推导声明：本报告全部结论基于文件静态阅读与仓库内交叉核对，未执行任何命令/脚本/运行验证；「红拦」「TypeError」「渲染结果」等行为结论均为代码路径静态推导。*
