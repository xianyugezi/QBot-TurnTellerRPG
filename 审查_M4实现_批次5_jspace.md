# 审查报告：M4 实现层 · 批次5（签到/指令组收尾）——j-space 静态审查

- 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，全程未运行任何命令/脚本/校验；所有运行期行为结论均标注「静态推导」）
- 审查流程：j-space full 档（接缝审计：每读一个文件/文档即对账契约核；交付前 ship 复查）
- 审查对象（4 文件，全文通读）：
  - `qbot_rpg/content/checkin_models.py`（1163 行：多表/连签/补签/里程碑/校验 + [签到:*] 三键解析）
  - `qbot_rpg/core/checkin.py`（960 行：多表一次结算/连签/补签只计不补发/三键取值）
  - `qbot_rpg/commands/basic_commands.py`（1109 行：/查看 /背包 /装备 /技能 /帮助）
  - `qbot_rpg/commands/gm_commands.py`（810 行：权限三级/静默/留痕/禁绑）
- 权威依据（已逐份核对仓库内实际文件）：
  - `docs/m4_shared_contract.md` §0（裁决①~⑧）/§2.2/§2.3/§3.4
  - `docs/细化/细化_2b5_签到引擎契约.md`（§1.2~1.8/§二~§五/D-01~06/TC-01~33 + 尾部 2026-08-27 裁决⑦⑧ L444-448）
  - `docs/细化/细化_4f_基础指令组契约.md`（RUL-01~34/B6/B8/RUL-25 + TC-01~24）
  - `docs/细化/细化_5b_GM指令契约.md`（§1 三级权限/静默/双检查/§2 G1-G14/§3.2 禁绑/§4 审计/TC-01~34）
  - `docs/审查参考/签到系统设计定稿.md`（L51-58/L62-73/L75-79/L127-151）、`docs/审查参考/指令分隔符统一规范.md`（L160-161 GM 清单）
  - 交叉核验：`qbot_rpg/core/dayroll.py`、`qbot_rpg/core/reward.py`、`qbot_rpg/engine/condition_engine.py`、`qbot_rpg/commands/router.py`、`parsers.py`、`sender.py`、`core/message_format/list_render.py`、`tests/unit/test_checkin*.py`

## 结论速览

**P0 = 0 · P1 = 3 · P2 = 11**（共 14 项）

| 级别 | 数量 | 项 |
|---|---|---|
| **P0** | 0 | — |
| **P1** | 3 | ①补签跨月 makeup_used/月上限未归一（误拦+错计）；②[签到:*] 三键表 id 限定被校验器放行但引擎不解析→条件静默 False；③bonus 倍率键名跨层分裂（校验器/测试认 `mult`，引擎认 `multiplier/rate/倍率`）→mult 配置静默失效 |
| **P2** | 11 | ①页码非法未附 TPL-08 页脚；②activity 无 cycle_days 校验口径与引擎不一致→误报黄提示；③period/makeup 未知键不校验（typo 静默）；④引擎 items 恒 bound=True 忽略配置；⑤bonus 误乘 rep（偏离 D-04）；⑥补签"挽回断签"语义弱化；⑦单表 batch 回滚路径死代码；⑧GM 下授 vs CommandSpec.permission 冲突风险；⑨/帮助 GM 可见性双源+非 GM TPL-12 探测面；⑩审计时序"先执行后写"偏离 5b §4.3；⑪三键缺省表名/英文字段口径微差 |

---

## 〇、行号引用真实性抽核（维度③ · 核心）

对 4 文件 docstring/注释中的定稿/细化/裁决行号引用做定向回查（≥30 处），**全部真实存在、内容相符，未发现编造行号**：

| 引用 | 回查结果 |
|---|---|
| 签到定稿 L127-137 字段元数据表（id L127/name L128/type L129/period L130-132/rewards L133-135/makeup L136/bonus L137） | ✅ 逐行一致 |
| 签到定稿 L51-58 奖励四通道 / L60 统一 reward 条目 / L62-73 结算管线 / L75-79 多表并存 / L139-151 校验器 / L106 统一周期键 / L147-151 黄提示五条 / L27 漏配兜底 / L16 只建议不限制 / L102/L104 三表对齐 | ✅ 全部命中 |
| 细化_2b5 §1.2（顶层字段）/§1.4（period 4 key）/§1.5（rewards 三通道）/§1.6（makeup 3 key）/§1.7（bonus）/§1.8（校验边界）/§三 连签/§四 补签/§五 幂等/D-01~D-06/TC-01~33 | ✅ 存在且口径一致 |
| 细化_2b5 尾部裁决 L444-448（⑦ 补签只计不补发/里程碑不重复；⑧ [签到:<表名>.<字段>] 三键加表名限定） | ✅ L446/L447 原文一致 |
| 4f RUL-01~34 / B6（/帮助 豁免注册门槛）/B8（GM 组仅 GM 渲染）/RUL-25（GM 保密）/RUL-17（acquired_at 倒序）/RUL-19（行格式） | ✅ 一致 |
| 5b §1.1 三级权限 / §1.1.1 默认授予集与机主专属 / §1.2 权限存储不进存档 / §1.4 绑定层+执行层双检查 / §2.1 G1-G14 / §3.2 禁绑 / §4 审计字段与成败皆写 / TC-01~34 | ✅ 一致 |
| 分隔符规范 L160-161（GM 指令清单：重载/封禁/日志/编辑/设置 + 禁绑拒绝文案） | ✅ L160-161 原文一致（m4 §2.3 "+设置"成立） |
| 裁决②（超页夹取+已到最后一页；0/负数/非数字 → TPL-12） | ✅ m4 §0.2 + 3d 尾注一致 |

**工程补白标注纪律**：4 文件全部显式标注【工程补白】（checkin_models 1-9 / core/checkin 1-8 / basic_commands 1-9 / gm_commands 1-10），无冒充定稿行号、无「工程补白冒充定稿支持」的表述。

---

## 一、维度① 定稿落地核查

| 检查点 | 要求 | 实现 | 结论 |
|---|---|---|---|
| 多表一次结算（E1） | loop/monthly/activity 并存，一次 /签到 全部结算 | `checkin_do` 遍历 `_all_checkin_tables` 逐表 `_settle_table`，单条汇总消息 `_summary_lines`（定稿 L210 防刷屏） | ✅ |
| 连签独立计数 | 各表独立 streak / signed_days / month_total | 存档按表 ID 键控 `checkin_state[<表ID>]`（细化 §3.1 L252）；三表各自结算互不合并 | ✅ |
| 断签归 1 | 间隔>1 天且 reset_on_break=true → streak=1 | `_settle_table` L670-676：`days_elapsed>1 → 1`；false → 不归 1（TC-15/16） | ✅ |
| 补签两通道 | 补签卡（物品）+ 货币 cost，任一满足 | `checkin_makeup` L910-927：卡优先，否则 cost；`_count_item`/`_remove_item`/`_deduct_currency` | ✅ |
| 补签默认关 / 月上限 0=不限 | enabled=false → 提示未开启；max_per_month>0 才拦 | L884-886（enabled is True 才可用）/L903（max>0 且 used≥max 拦） | ✅（跨月口径见 P1-1） |
| 裁决⑦ 补签只计不补发 | 恢复 signed_days/streak 连续性，不补发 daily、不触发里程碑 | makeup 分支零 dispatch_reward（L910-946 只落档）；`test_makeup_no_milestone_grant` 覆盖 | ✅ |
| 裁决⑦ 里程碑不重复 | 每档每周期至多一次 | streak 恰好命中 `streak==d`（每连签段一次）；monthly_total 用 `month_milestones` 去重、跨月清零（D-06） | ✅ |
| 裁决⑧ [签到:<表名>.<字段>] 三键 | 连续天数=streak / 本月天数=当月 signed_days / 今日已签；缺省表名=主表 loop | `parse_checkin_key`（content）+ `checkin_value`/`checkin_condition_ctx`（core）+ `condition_engine._resolve_checkin` 全链路；type 限定格式 `[签到:monthly.本月天数]` 可求值 | ⚠️ type 口径闭环；表 id 限定口径断裂 → **P1-2** |
| 幂等（同日） | 同日重复 /签到 → 今天已签到不重复发奖 | `_settle_table` L650-667 last_date==today → already_signed；tx_id/ledger 重放闸 | ✅ |
| 懒计算日界 05:00 | 统一配置键 refresh_time；凌晨 0-5 点归前一天 | `today_of(None, _now(ctx), _cfg(ctx))`；`_cfg` 读 settings（dayroll 权威） | ✅ |
| bonus 乘算（D-04） | 本次实际发放 items.count/coins/gem/exp 向下取整 | `_bonus_multiplier` + `_scale_entries`（物品下限 1/标量下限 0） | ⚠️ 键名分裂 → **P1-3**；rep 误乘 → **P2-5** |
| 发奖失败兜底（D-05） | 单条失败黄字跳过不吞整次 | `dispatch_reward` 逐条 skip（reward.py P1-2 语义） | ✅（batch 级回滚为死代码 → P2-7） |
| 漏配天数兜底（TC-10） | 复制第 1 天 + 黄色提示 | `_daily_entry` L465-477 fallback + notes「第 X 天未配置，已按第 1 天奖励补全」 | ✅ |
| monthly_total 跨月清零（D-06） | 自然月切换归 0；longline 只增不减 | `_normalize_month` L389-400（signed_days/month_total/month_milestones 重置；makeup_month 对齐；longline 不动） | ✅（补签路径除外 → P1-1） |
| 活动表懒启停 | 未开始/已过期 → 自动停用不报错 | `table_active` L308-318 + `is_window_open`；checkin_do 跳过 inactive | ✅ |
| 校验器硬拦/黄提示 | 定稿 §八 红拦 3 类 + 黄提示 5 条 | R-1/R-2/R-4/R-5 族 + Y-4 族（含 14 条，见 validate_checkins 规则清单） | ✅（未知键/周期口径缺口 → P2-2/P2-3） |
| 基础指令五条 | /查看 /背包 /装备 /技能 /帮助 | 5 个 handler 全接线（`register_basic_commands` → Router CommandSpec） | ✅ |
| 5 条/页 + TPL-08 + 裁决② | 列表 5 条/页；页脚固定 TPL-08；超页夹取+已到最后一页；0/负数/非数字 TPL-12 | 全部走 `list_render.resolve_page/render_footer/LAST_PAGE_HINT`，无自造页脚 | ⚠️ 非法页码未附页脚 → **P2-1** |
| 注册门槛（RUL-08）/ 帮助豁免（B6） | 未注册拦截；/帮助 返回注册引导版 | `_gate`（registered is False → TPL_REGISTER_GATE）；`cmd_help` B6 分支 `_REGISTER_GUIDE` | ✅ |
| GM 三级权限 | 机主>GM>普通玩家；判定优先级 | `check_gm_permission`（admin 全放/manager 默认集+下授/player 静默）；GM_COMMAND_LEVEL 对齐 5b（设置=机主） | ✅（下授 vs spec 元数据 → P2-8） |
| 静默（安全边界） | 无权限 → 零出站零审计 | `silent_result()`；handle_gm_command 无权限分支不调 record_audit | ✅ |
| 留痕（信任边界） | 成败皆写；追加写；无权限不写 | `build_audit_record`/`record_audit`（ctx["audit_log"] + audit_store）；result 三态 | ✅（时序 → P2-10） |
| GM 禁绑 / 强制前缀 | 绑定层 C02 + 执行层 E02 双检查；永不快捷 | `gm_binding_guard`→`check_shortcut_binding(gm_commands=GM_COMMANDS)`；CommandSpec.is_gm=True；parsers.DEFAULT_PREFIX_REQUIRED 已含 5 条 | ✅ |
| GM 清单 = L160 长清单 | 重载/封禁/日志/编辑/设置（+设置） | `GM_COMMANDS` frozenset 5 条；GM_HELP_GROUP 同步；5b G2-G7/G9/G11/G12 明确登记延后（工程补白 1） | ✅ |

---

## 二、维度② 代码质量核查（bug/边界）

### P1-1 补签跨月 `makeup_used` / 月上限未归一：新月份首日误拦 + 支付后错计

- 位置：`qbot_rpg/core/checkin.py` L888-906（守卫期）与 L929-942（应用期）
- 问题（静态推导）：`checkin_makeup` 在**支付前**以 `_peek_state` 只读节点读 `used = _as_int(node.get("makeup_used"))`（L902）判月上限（L903），而 `_normalize_month`（L931）只在**支付成功后**的应用期执行。两个后果：
  1. **新月份首日误拦**：上月 makeup_used=3 且 max_per_month=3，次月首日直接 `/签到 补签`（未先普通 /签到）→ 守卫读上月 used=3 → 误报「本月补签已达上限」（应为新月份重新计数）；
  2. **支付后错计**：max_per_month=0（不限）时无拦截，支付成功后 `_normalize_month` 把 makeup_used 重置为 0，随即 L942 `node["makeup_used"] = used + 1` 用**旧月 used** 写入 → 新月份首笔补签后 makeup_used=4（应为 1），此后每月首笔都错。
- 可达性：普通 /签到（`_settle_table` L647）会先归一，故仅在「新月份首次操作即补签」时触发；现有测试（test_checkin.py L471-511）全部停留在单月内，未覆盖跨月。
- 修复建议：把月上限判定改为「按节点 makeup_month 与当前月比对后的**当月有效 used**」（跨月视为 0），或在守卫期先行只读归一（不落档）再判上限；应用期 `makeup_used = 当月有效 used + 1`。补一条跨月补签测试（8 月补满 → 9 月首日补签应成功且 makeup_used=1）。

### P1-2 [签到:*] 三键表名限定「双口径」断裂：校验器放行表 id 限定键，引擎静默求值 False

- 位置：`qbot_rpg/content/checkin_models.py` L1042-1050（`_check_checkin_references` 双口径）；`qbot_rpg/engine/condition_engine.py` L252-263（`_parse_checkin_body`）；`qbot_rpg/core/checkin.py` L291-296（`_table_id_for_type`）/L539-564（`checkin_value`）
- 问题（静态推导）：checkin_models 的引用校验显式声明「限定符匹配表 **id 或生效 type**，两口径皆可解析」（L1042-1043），且对表 id 限定键（如 `[签到:checkin_monthly.本月天数]`，表 id 存在于 `refs.checkin_ids`）**不告警放行**。但消费侧两个引擎都**只认 type 名**：
  - `condition_engine._parse_checkin_body`：`if table not in CHECKIN_TABLES: return None`（CHECKIN_TABLES 仅 ("loop","monthly","activity")）→ 表 id 限定键返回 None → `_resolve_checkin` fail-safe False；
  - `core/checkin.checkin_value`：`_table_id_for_type(ctx, "checkin_monthly")` 按 `table["type"]=="checkin_monthly"` 匹配 → None → 返回 0。
- 影响：内容作者按校验器「双口径」承诺配表 id 限定键（表 id 恰为定稿正典示例 `checkin_monthly`），**校验零告警、运行期条件恒 False**（任务/NPC 门槛永不满足），属「声明覆盖但引擎未实现」+ 静默失败（D-03 求值失败默认 False 掩盖）。
- 修复建议：二选一——① 消费侧统一支持表 id 口径（`checkin_value` 增加按 id 解析 + `condition_engine` 允许 id→type 映射）；② 校验器收回双口径承诺，表 id 限定键一律告警「仅支持表类型名（loop/monthly/activity）」。并补一条表 id 限定键的条件求值测试。

### P1-3 bonus 倍率键名跨层分裂：校验器/模型/测试认 `mult`，引擎认 `multiplier/rate/倍率`

- 位置：`qbot_rpg/content/checkin_models.py` L903-918（`_check_bonus` 校验 `bonus.mult`）；`qbot_rpg/core/checkin.py` L430-444（`_bonus_multiplier` 只读 "multiplier"/"rate"/"倍率" 与裸数值）
- 问题（静态推导）：内容层正典键为 `mult`（校验器错误文案 L918「bonus.mult 需 ≥0 数值」、`tests/unit/test_checkin_models.py` L130/L231/L562-564 全部用 `{"mult": 2}`）；引擎 `_bonus_multiplier` **不读 `mult`**（引擎测试 `test_checkin.py` L401 用 `{"multiplier": 2}`）。结果：
  1. 作者按校验器/编辑器约定配 `bonus: {"mult": 2}` → 校验通过 → 引擎返回 1.0 → **限时双倍静默不生效**；
  2. 反方向 `{"multiplier": -1}` → 校验不拦 → 引擎取 -1.0 → 所有奖励被削到下限（物品 1/标量 0）。
- 修复建议：统一键名为 `mult`（对齐内容层/编辑器/校验器/模型测试），引擎 `_bonus_multiplier` 增读 `mult`（可保留 multiplier/rate/倍率 兼容）；补引擎侧 `{"mult": 2}` 用例。

### P2-1 页码非法（0/负数/非数字）仅裸 TPL-12，未附 TPL-08 页脚

- 位置：`qbot_rpg/commands/basic_commands.py` cmd_view L457-459 / cmd_bag L578-580 / cmd_equip L773-775 / cmd_skill L964-966 / cmd_help L1071-1073；`qbot_rpg/commands/gm_commands.py` cmd_gm_log L600-603（经 `_record_and_return` → error_result → format_tpl12）
- 问题（静态推导）：3d §2.2 L142-143 与 `sender.page_error_tpl12`（L108-116）要求非法页码输出 TPL-12 **并附当前页脚 TPL-08**；五条基础指令与 /日志 均只 `format_tpl12(_fragment(parsed))` 裸报错。属规范符合度缺口（超页夹取路径正确，仅非法输入缺页脚）。
- 修复建议：改用 `sender.page_error_tpl12(fragment, command, total_pages, total)`（需先 resolve_page 拿总页数），或在 TPL-12 后拼 `render_footer`。

### P2-2 activity 表无 cycle_days 时校验口径与引擎不一致 → 误报黄提示

- 位置：`qbot_rpg/content/checkin_models.py` `_effective_cycle` L613-620 vs `qbot_rpg/core/checkin.py` `cycle_days_of` L334-338
- 问题（静态推导）：校验器对 activity 无 cycle_days → 默认 7；引擎对 activity 无 cycle_days → `start→end` 日数（如 14 天活动）。于是活动表配 `daily day=10` 或 `streak days=10`（无 cycle_days）时校验器误报「该档永远不会被轮到/周期只有 7 天」（实际引擎周期 14 可达到）。黄提示误报会误导作者删合法配置。
- 修复建议：`_effective_cycle` 对 activity 无 cycle_days 时按 `start/end` 日差（同引擎口径）计算，无法解析才回落 7。

### P2-3 period / makeup 未知键不校验，typo 静默吞掉

- 位置：`qbot_rpg/content/checkin_models.py` `_check_period` L639-697 / `_check_makeup` L849-900
- 问题（静态推导）：`_check_reward_entry` 有未知键红拦（R-5 checkin_entry_unknown_key），但 period/makeup 无同类检查。`"cycl_days": 5` typo → 走「循环表缺 cycle_days 已按默认 7 补全」误导黄提示；`"costs": {...}` typo → 「补签不花钱？确认」。配置错字静默吞掉、作者无从发现。
- 修复建议：对 period/makeup 增未知键红拦（R-5），错误信息列合法键集（对齐 reward 条目做法）。

### P2-4 引擎 items 恒写 bound=True，忽略 items[].bound 配置

- 位置：`qbot_rpg/core/checkin.py` `_channel_entries` L417/L422（`"bound": True` 硬编码）
- 问题（静态推导）：checkin_models `_check_item` 显式校验 `bound` 键（REWARD_BOUND_KEY，L734-737），即内容层声明 bound 是合法可配字段；但引擎入账恒 true。作者配 `bound:false` 通过校验却仍按绑定发放（不可卖防套利语义被强制）。引擎测试也未覆盖 bound:false。
- 修复建议：`_channel_entries` 读 `it.get("bound", True)`（bool 校验兜底 true），补一条 bound:false 用例。

### P2-5 bonus 乘算误作用于 rep，偏离 D-04

- 位置：`qbot_rpg/core/checkin.py` `_scale_entries` L458-460
- 问题（静态推导）：D-04（细化 L42/L156）明示乘算范围 = items.count/coins/gem/exp，**不含 rep**；`_scale_entries` 对非物品条目的所有 int 标量键（含 `{"rep": N}`）统一乘算。签到奖励含 rep 时倍率会错误放大声望。
- 修复建议：乘算仅作用于 `("coins","gem","exp")` 三键，rep 原样透传。

### P2-6 补签「挽回断签」语义弱化：仅补今日，断签缺口不可补

- 位置：`qbot_rpg/core/checkin.py` L939-941
- 问题（静态推导）：D-03/TC-20 承诺「补签所补回的日期计入 signed_days 并参与连签连续性（挽回 streak 断签）」；实现只对 **today** 生效（`/签到 补签` 无历史日期参数），`streak += 1`、`last_date=today`。断签已发生后（如昨天漏签）再补签，streak 只 +1，**不回断签前值**，「挽回断签」实际不可达（只能让今日不断）。
- 定性：设计取舍（契约未定义历史日期补签通道，工程补白 5 已声明「作用于当前归属日 today」），但与 D-03「挽回 streak 断签」的措辞存在落差，需确认或补注。
- 修复建议：确认口径——若仅今日补签，则在 D-03/TC-20 补「断签恢复仅限今日连续」说明；若要真正挽回，需补日期参数与按日回填逻辑（超当前实现范围）。

### P2-7 `_settle_table` 单表 batch 失败回滚路径实际不可达（死代码防御）

- 位置：`qbot_rpg/core/checkin.py` L698（`raise _Rollback("reward_failed")`）与 L750-759（回滚分支）
- 问题（静态推导）：`dispatch_reward` 对 `_channel_entries` 产出的合法 list 恒 `ok=True`（batch 级失败仅 ctx 非 Mapping / entries 顶层形态非法，两者在此均不可能），`_Rollback("reward_failed")` 永不可达；「一表失败不影响其他表（D-05）」的 batch 级快照-回滚实际为防御性死代码（逐条 skip 是 D-05 的真正落地）。checkin_makeup 的 `no_payment_channel`/`card_remove_failed` 回滚路径可达，机制本身有在用。
- 修复建议：保留防御（跨进程事务由调用方兜底）但补注释说明该分支当前不可达；或让 `dispatch_reward` 的异常路径（如 add_item hook 抛非预期异常）能被 `_Rollback` 捕获（将异常包入 try）。

### P2-8 GM per-command 下授（设置）与 CommandSpec.permission=owner 元数据冲突风险

- 位置：`qbot_rpg/commands/gm_commands.py` L802-808（`register_gm_commands`：`permission=_SPEC_PERMISSION[level]`，设置→PERM_OWNER）与 L285-307（`check_gm_permission`：manager 可经 granted_commands 下授执行设置）
- 问题（静态推导）：5b §1.1.1 明示「机主专属（可另行下授）＝…设置」；本层 handler 侧已实现 per-command 下授放行，但注册进 Router 的 CommandSpec.permission 对「设置」硬编码 owner。若批次7 装配层把 CommandSpec.permission 当硬门禁，被下授的 manager 会在进 handler 前被拦，下授语义失效；若装配层以 handle_gm_command 的 GmResult 为准则无碍。属接缝未闭合。
- 修复建议：装配层明确以 `handle_gm_command` 返回的 GmResult（含 silent）为准、CommandSpec.permission 仅作展示/路由元数据；或对可下授指令的 spec.permission 放宽到 PERM_GM 并由 handler 二次判定。

### P2-9 /帮助 GM 组可见性双源 + 非 GM 发「/帮助 GM」得 TPL-12（探测面）

- 位置：`qbot_rpg/commands/basic_commands.py` L974-979（`_help_groups` 用 `ctx["is_gm"]`）与 L1066-1070（非 GM `/帮助 GM` → `_render_help_group` 查无组 → format_tpl12）
- 问题（静态推导）：① 5b 权限唯一事实来源 = permission_store/admin_users（gm_commands L461-479），/帮助 的 GM 组可见性却读 `ctx["is_gm"]` 独立标记，双源可能不一致（帮助可见但执行被静默拦，或反之）；② 非 GM 发 `/帮助 GM` 得「❌ 指令不正确：/帮助 GM」，虽为通用文案，但对该输入产生与 GM 玩家不同的出站，构成 RUL-25「不提示存在」下的间接探测面（GM 玩家同样输入会得到 GM 组页）。
- 修复建议：/帮助 GM 判定改经统一权限源（注入 is_gm 的装配层保证与 permission_store 同源，或提供 ctx["is_gm"] 由装配层按 permission_store 填充）；非 GM 对 `/帮助 GM` 回目录页（与未知组名区分或统一静默）。

### P2-10 审计时序「先执行后写审计」偏离 5b §4.3

- 位置：`qbot_rpg/commands/gm_commands.py` cmd_gm_reload L536-546 / cmd_gm_ban L567-581 / cmd_gm_settings L657-665（先调 backend，后 `_record_and_return`）；`_record_and_return` L493-517
- 问题（静态推导）：5b §4.3「审计写入与业务写入同事务（重载/恢复类**先写审计事件再执行**，防『没留痕的操作』）」；本层纯逻辑侧全部「先执行后写」，若 audit_store 落库失败（批次7 事务接管前）或进程在两步之间崩溃，可能产生「已执行未留痕」操作。
- 修复建议：本层至少在 docstring 注明时序依赖批次7 同事务落库；或在执行前预写 pending 审计（result=rejected/进行中）再在成功后回填 result，确保无操作无痕。

### P2-11 [签到:*] 三键缺省表名 / 英文字段口径微差

- 位置：`qbot_rpg/core/checkin.py` L95-102（CHECKIN_FIELDS 兼收英文）/L539-545（checkin_value 缺省固定 "loop"）；`qbot_rpg/content/checkin_models.py` L446-473（parse_checkin_key 只认中文三值）
- 问题（静态推导）：① `checkin_makeup` 缺省目标表用 `_primary_table_id`（无 loop 取首表，L873-874），`checkin_value` 缺省表名用固定 "loop"（无 loop → `_table_id_for_type` 返回 None → 0）——「主表」口径不一致（无 loop 只配 monthly 的包，补签作用于首表而三键缺省值恒 0）；② `parse_checkin_key`/校验器对 `[签到:loop.streak]`（英文字段）报「键格式不认识」，而 condition_engine 与 core 均接受英文——校验告警与运行期可求值矛盾。
- 修复建议：① `checkin_value` 缺省表名改用 `_primary_table_id`（与补签一致）；② 校验器补认英文三值或明确声明仅中文正典（对齐裁决⑧ 示例）。

---

## 三、维度③ 幻觉/缺漏核查

| 检查点 | 结果 |
|---|---|
| docstring 引用行号真实性 | ✅ 抽查 30+ 处全部真实（见 §〇），无编造行号、无「引用不存在行」 |
| 工程补白显式标注 | ✅ 4 文件共 36 处全部【工程补白】标注，未冒充定稿/裁决支持 |
| 声明覆盖但未实现 | ⚠️ 表 id 限定三键（P1-2）、bonus `mult` 键（P1-3）、补签挽回断签（P2-6）、GM 下授 metadata（P2-8） |
| 零消费函数 | ✅ 模型访问器（streak_thresholds/monthly_total_thresholds/has_cost_channel/item_ids/has_reward/effective_reset_on_break/parse_checkins）均被 `tests/unit/test_checkin_models.py` 消费；core 公开函数全被引擎/指令层/测试引用——未发现全库零引用死 API（对比批次4 P2-4 未复现）。注：引擎直接读 raw 未复用模型访问器（双层读取是 P1-3 键名分裂的根因之一） |
| 死代码分支 | ⚠️ `_settle_table` batch 失败回滚路径不可达（P2-7） |
| 裁决贯彻 | ✅ 裁决②（超页夹取/非法 TPL-12）、裁决⑦（只计不补发/里程碑不重复，含补签不触发里程碑测试）、裁决⑧（type 限定格式全链路闭环）均已落地；m4 §2.3 GM 清单 L160（+设置）落地 |
| 未实现项登记 | ✅ 5b G2-G7/G9/G11/G12 明确登记延后（gm_commands 工程补白 1）；basic/gm make_context 与引擎注入均标「批次6/7 待接线」（与批次4 同模式） |

---

## 四、确认无问题维度（含「静态推导」运行行为结论）

- **多表一次结算与汇总**：`checkin_do` 对全部生效表独立跑 ①~⑥ 管线并汇总单条消息，跨表互不写对方 state（静态推导：三表并存首次 /签到 各表 streak=1 且单条输出，对齐 TC-07/08）。
- **断签与连签独立**：`_days_between(last_date, today)` + reset_on_break 分支正确；loop day 编号 `((streak-1)%cd)+1` 满足 D-01「余 0 → cycle_days」；monthly 按自然月当日、activity 按 start 日差（静态推导，TC-13/15/16）。
- **里程碑不重复**：streak 恰好命中 + month_milestones 去重（跨月 D-06 清零），补签不触发任何里程碑（测试覆盖）——与裁决⑦ 一致（静态推导）。
- **幂等与防双发**：同日 `last_date==today` 早退不重发；tx_id/ledger 全局重放闸 + dispatch_reward 子 tx 记账互不冲突（静态推导：同参数重放一次仅一次入账，TC-25/26）。
- **三键 type 限定正典格式**：`[签到:monthly.本月天数]` → condition_engine `_parse_checkin_body`（type 名）→ `ctx["checkin"][monthly][month_days]` 投影 → checkin_condition_ctx 刷新，链路闭环可求值；缺表/未签 fail-safe 0（静态推导，TC-32）。
- **GM 静默/留痕/禁绑**：player 与未下授 manager 发 GM 指令 → silent_result 零出站零审计；成功与失败均 `_record_and_return` 写审计；`gm_binding_guard` 对 `/重载 X` 与裸「重载」均拒绑（is_gm_command 剥离 / 后判定）；Router `_trigger_allowed` 对 GM 强制 / 前缀（静态推导，TC-01/23/24/28）。
- **页码横切（裁决②）**：超页 → `resolve_page` clamped 夹取最后一页 + LAST_PAGE_HINT；正常页 → TPL-08 页脚（`render_footer` 单页不输出）；非法输入 TPL-12（缺页脚见 P2-1）。
- **/查看 属性三层**：`calc_all_final_attributes` 出口唯一取整、pct 以 % 单位展示（`+10%` 语义正确，3b 管线 pct/100）；resource 型显示当前/上限（静态推导）。
- **校验器红拦族**：R-1/R-2/R-4/R-5 对 id/name/type/负数/引用/结构逐项落地，`_Checker._err/_warn` 签名（module, field, kind, **detail）与 `_emit` 鸭子类型适配一致（已验证 validator.py L336-344）。

---

## 五、修复建议清单（按优先级）

1. **P1-1**：补签月上限/`makeup_used` 改为「按 makeup_month 与当前月比对后的当月有效 used」判定与写入（守卫期只读归一或跨月视为 0）；补跨月补签测试。
2. **P1-2**：三键消费侧（condition_engine + core.checkin）支持表 id 限定口径，或校验器收回「双口径」承诺并对表 id 限定键告警；补 id 限定键求值测试。
3. **P1-3**：引擎 `_bonus_multiplier` 增读 `mult`（内容层/编辑器正典键），保留兼容键；补 `{"mult": 2}` 引擎用例。
4. **P2-1~P2-11**：非法页码附 TPL-08 页脚；activity 无 cycle_days 校验口径对齐引擎；period/makeup 未知键红拦；`_channel_entries` 读 bound 配置；`_scale_entries` 排除 rep；补签挽回语义确认或补注；`_settle_table` 回滚死路径注释；装配层以 GmResult 为准 + 下授 spec 权限收敛；/帮助 GM 判定同源 + 非 GM 回目录；审计时序与 5b §4.3 对齐（批次7 事务接管）；checkin_value 缺省表名对齐 `_primary_table_id` + 校验器补认英文字段。

## 六、评分

- 主体实现质量高：定稿/细化/裁决落地完整（多表一次结算/连签/补签只计不补发/三键 type 口径/权限三级/静默/留痕/禁绑/L160 清单），行号引用 30+ 处全部真实，工程补白纪律严明，裁决⑦⑧ 主语义贯彻无遗漏，未复现批次4「声明覆盖但引擎零消费」型 P1（本批该型退化为 3 项跨层口径分裂）。
- 主要短板集中在**跨层口径分裂**（补签跨月归一 P1-1、三键表名双口径 P1-2、bonus 键名 P1-3）与一批校验/渲染/时序微差（P2×11）。
- **P0=0 · P1=3 · P2=11 · 评分 A-**
