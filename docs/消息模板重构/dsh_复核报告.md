# dsh 复核报告 · 2026-09-12「消息模板重构战役」

> 复核对象：本仓库 2026-09-12 战役改动（加载链 / 战斗 HUD v2 / 技能列表详情 / 炼金引擎文案 / effect_events / 终态门禁）。
> 复核方式：对 `4d02ac7..HEAD`（战役起点前一提交 → 当前 HEAD `a3ce80f`）按文件逐一读 diff + HEAD 原文定位行号；
> 对关键路径用 `python3` 直接调用被测函数做最小复现。**本环境未安装 pytest（`No module named pytest`），测试结论均为静态审查 + 手工复现，未跑全量回归。**
> 约束遵守：除本文件外未改动任何代码/配置，未 commit。
> 规范基线：`docs/消息模板重构/00_方案与规范_v1.md`（B=28 半角/14 全角、免斜杠、｜少用多换行、结构化行硬上限）与 `02_遗留登记.md`。

---

## 〇、结论速览

| 严重度 | 数量 | 条目 |
|---|---|---|
| 高 | 1 | H1 effect_events 在 NPC 批量段与玩家段**重复渲染** |
| 中 | 8 | M1 effect_events 清空时序丢事件；M2 结算尾行未入 16 行预算；M3 折叠硬上限可被单元素击穿；M4 加载器仅捕 OSError；M5 `_derived_tags` 漏 combo_push/preserve；M6 `instant_eligible` 迁移键无消费方（死迁移）；M7 新增玩家可见硬编码中文；M8 残留 `/炼金` 斜杠指令提示 |
| 低 | 8 | L1 tpl_of 部分地图缺键返空串；L2 内容包未知 key 静默 + 门禁只查 test_demo；L3 HUD 三键超 28 半角未豁免、宽度门禁只 WARN；L4 `丨` 硬编码；L5 方位【】口径与规范冲突；L6 怪物状态行有意超宽未登记 prose_keys；L7 终局仍输出「→ 攻击」提示；L8 `from_report` 死构造点 |
| 测试盲区 | 11 | 见 §四 |

**最需要立刻修的是 H1**：只要本次行动包含 NPC 连锁（CTB 常见路径），`【持续效果】/【效果失效】` 行会在桥接合并后的同一条消息里出现两次。

---

## 一、① 逻辑缺陷 / 边界

### H1【高】effect_events 在批量段与玩家段重复渲染

- 位置：
  - `qbot_rpg/commands/battle_commands.py:1095`（`dispatch_batch` 把**整份** `report.effect_events` 灌进 batch）
  - `qbot_rpg/commands/battle_commands.py:1469-1474`（`_dispatch_merged_action` 同一拍先发 batch、再发玩家段）
  - `qbot_rpg/commands/battle_commands.py:599`（`_without_npc_outcomes` 原样透传 `effect_events=report.effect_events`）
  - `qbot_rpg/core/message_format/battle_render.py:2070`（batch 渲染 `_render_effect_lines`）
  - `qbot_rpg/core/message_format/battle_render.py:197` / `1994`（玩家段 `render_battle_round` / `render_battle_action` 同样渲染）
- 证据（实测，精确复刻 `dispatch_batch` 的真实 SimpleNamespace：无 `player/enemy/player_max_hp` 字段）：

  ```
  $ python3 - <<'EOF'
  ... render_battle_action_batch(SimpleNamespace(entries=[], effect_events=evs, **battle_hud_payload(snap)))
  EOF
  batch 段输出: '【效果失效】狂暴 效果时间结束。'
  玩家段输出（render_battle_round(_without_npc_outcomes(rep))）:
    【持续效果】流血 生效，你受到 7 伤害。
    ...（同一份 effect_events）
  ```

  `_dispatch_merged_action` 两段都被 `BattlePipeline` 送入 `Sender.delivered`，桥接层 `qbot_rpg_bridge/plugin.py:128` 用 `"\n".join(_bodies)` 合并成**一条**消息 → 同一效果行出现两次。
  注意：HUD 分块本身**没有**重复（batch 没有 `player/enemy/player_max_hp` 字段，`_render_action_hint_from_report` 在 `battle_render.py:856` 直接返回空串），重复的只有本次新增的 effect 行。
- 建议修法（择一）：
  1. `dispatch_batch` 只提取 NPC 侧事件：`tuple(e for e in report.effect_events if e.get("side") == "enemy")`，把玩家侧事件留给玩家段；或
  2. `_without_npc_outcomes` 置 `effect_events=()`，让 effect 行只由 batch 段出（配合 `render_battle_action_batch` 的单次渲染）；或
  3. 在 `_dispatch_merged_action` 里给两段各传一个「已渲染」标记，渲染层去重。
  推荐 2（语义最清晰：效果行归「本拍统一播报」一条），并补一条端到端断言（见 T2）。

### M1【中】`player_act` 清空 effect_events 的时序会吞掉「玩家拍前 NPC 连锁」事件

- 位置：`qbot_rpg/core/battle.py:4940-4947`
  ```python
  self._npc_outcomes = []
  if self._ctb is not None and not self._ctb.paused and not self._finished:
      self._resolve_ready_actor()        # 4942：可能追加 _effect_events
  pre_npc = list(self._npc_outcomes)     # 4943：这批 outcome 会进本报告
  self._npc_outcomes = []
  self._effect_events = []               # 4945：把上面刚追加的事件一并清掉
  ```
- 证据：`pre_npc` 会进报告 `outcomes`（`:4983` / `:5002`），但与之配对、由 `_resolve_ready_actor` 在 `battle.py:2581`（行动开始 DOT）与 `:4674`（行动收尾 DOT/失效/再生）追加的事件被 4945 清掉且不再补发 → 这批 NPC 行动的持续效果行永久丢失。
  触发条件为 `not self._ctb.paused`（非常规玩家 ready 态），属边界路径，故定为中。
- 建议修法：把 `self._effect_events = []` 移到 `:4941` 的 `if` **之前**（先清历史、再收集本拍），或在 4943 取 `pre_npc` 时同时快照 `pre_effects = list(self._effect_events)` 并把它们并入最终报告。

### M2【中】终局尾提示置底时未计入 16 行预算

- 位置：`qbot_rpg/core/message_format/battle_render.py:272-280`
  ```python
  if summary is not None:
      overhead = sum(max(1, len(str(ln).splitlines())) for ln in lines)  # 275：此时还没有 tail
      block = _render_summary_block(summary, overhead=overhead, ctx=ctx)
      ...
  if tail and str(tail).strip():
      lines.append(str(tail))                                            # 279-280：预算外追加
  ```
- 证据（实测，使用 `test_tc06_fold_over_16_lines` 同款输入）：
  ```
  tail=None  → 16 行（末行 "发 战斗记录 2 查看"）
  tail="→ 攻击 或 攻击 <技能名>" → 17 行
  ```
  即铁律 11「单条 ≤16 行」在终局消息被 +1 行击穿。
- 建议修法：把 tail 预估行数（`max(1, len(str(tail).splitlines()))`）先从 `overhead` 里扣掉，再调 `_render_summary_block`；或把 tail 行并入 `lines` 后再统一算 overhead。

### M3【中】`_fold_message_lines` 的硬上限可被「单个多行元素」击穿

- 位置：`qbot_rpg/core/message_format/battle_render.py:113-132`
  ```python
  budget = max_lines - counts[0] - 1
  if budget < 1: budget = 1
  ...
  if keep_tail < 1: keep_tail = 1     # 127-128：强制保留 1 个尾部元素
  ```
- 证据（实测）：
  ```
  末元素自身 20 物理行 → 折叠后 3 元素 / 22 物理行（>16）
  首元素自身 15 物理行 → 折叠后 3 元素 / 17 物理行（>16）
  ```
  强制 `keep_tail=1`（以及 `budget` 下限 1）都假定「每个元素 ≤1 物理行」，与本次「按物理行计」的改造自相矛盾。当前战斗侧单元素最多约 8 行（HUD 块），暂难触发；但函数被文档声明为硬门禁，且文案可被内容包改成多行。
- 建议修法：`keep_tail` 拟合失败（`keep_tail==0`）时不要强塞整元素，改为对该元素按物理行截断/只保留其末尾若干行，或允许预算不足时输出「已折叠」提示并保证总物理行 ≤ max_lines。

### M4【中】加载器只捕 `OSError`，表文件损坏会在 import 期崩溃

- 位置：`qbot_rpg/core/templates/__init__.py:44-51`
  ```python
  try:
      _doc = json.loads(_TABLE_PATH.read_text(encoding="utf-8"))
      ...
  except OSError:
      TABLE_TEMPLATES = {}     # 注释称「表文件缺失的兼容路径」
  ```
- 证据：`json.JSONDecodeError` 与 `UnicodeDecodeError` 都是 `ValueError` 子类而非 `OSError`（实测 `issubclass(json.JSONDecodeError, OSError) == False`）。表被截断/编码损坏时 `import qbot_rpg.core.templates` 直接抛异常，整个包不可用；与注释承诺的「兼容路径」不符。
- 建议修法：`except (OSError, ValueError)`（或 `except (OSError, json.JSONDecodeError, UnicodeDecodeError)`），并记一条 warning。

### M5【中】`_derived_tags` 漏掉 `combo_preserve` / `combo_push`

- 位置：`qbot_rpg/commands/basic_commands.py:1821`
  ```python
  if str(_skill_field(defn, "tag", "") or "") == "combo":
      tags.append("combo")
  ```
- 证据：字段枚举 `qbot_rpg/content/field_meta.py:971` 明确为 `none/combo/combo_preserve/combo_push/interrupt/armor`；内容侧已有使用：`content/test_demo/skills.json:114`（剑舞 `combo_push`）、`:659`（平息战意 `combo_preserve`）。这些技能在 `brief` 为空时不会出现【连段】标签，简述行与详情「标签」行都会缺一项。
- 建议修法：`if str(_skill_field(defn, "tag", "") or "").startswith("combo"):`，并为三类 tag 各加一条断言。

### M6【中】`instant_eligible` 迁移成表键，但全仓无消费方（死迁移）

- 位置：
  - `qbot_rpg/core/alchemy_battle.py:307 / 311 / 316 / 321`（`alchemy_engine_battle_not_in_battle` / `_master_required` / `_energy_short` / `_already_used`）
  - 活路径：`qbot_rpg/commands/alchemy_commands.py:3028-3075` 的 `cmd_instant` 自己内联守卫，用的是 `alchemy_instant_not_battle`（`:3033`）、`alchemy_level_insufficient`（`:3037`）、`alchemy_instant_limit`（`:3054`）等**另一套键**。
- 证据：全仓 `grep -rn "instant_eligible" --include=*.py .` 只命中 `alchemy_battle.py` 自身定义与 docstring，零调用点；表内两套文案并存且不同（`alchemy_engine_battle_not_in_battle='❌ 仅战斗中可即时调合'` vs 活键 `alchemy_instant_not_battle='❌ 即时调合仅限战斗中\n战斗内发 即时调合 <配方>'`）。内容作者改 `alchemy_engine_battle_*` 不会生效。
- 建议修法：删除 `instant_eligible` 或让 `cmd_instant` 改调它（把三处内联守卫收敛回引擎）；同步清理 4 个无消费键，避免下一轮审计再当「活键」维护。

### L1【低】`tpl_of` 在「有 templates 但缺 key」时返回空串而非回落默认表

- 位置：`qbot_rpg/core/templates/__init__.py:100-103` + `:86-92`
- 证据：`tpls = ctx.get("templates")` 只要 `isinstance(..., Mapping)` 就整体替换默认表；`render_template` 缺 key 返回 `""`。正常链路 `ctx["templates"] = resolve_templates(...)` 是「全量默认 + 覆盖」故无碍；但任何调用方传入**局部覆盖 dict**（或 key 被后续批次删除）时，整行/整块会静默消失。`test_template_table.py:50-55` 只测了 `tpl_of(None, key)`，未覆盖该分支。
- 建议修法：`render_template` 缺 key 时回落 `DEFAULT_TEMPLATES.get(key)`（或 `tpl_of` 在 `templates` 缺 key 时补默认）。若坚持「ctx 即全量」，请在 docstring 明确契约并加断言。

### L2【低】内容包未知 key 静默忽略，且门禁只覆盖 test_demo

- 位置：`qbot_rpg/core/templates/__init__.py:80-82`；门禁 `tests/unit/test_template_table_final.py:64-68`
- 证据：`resolve_templates` 对不在 `merged` 的 key 直接跳过（无日志）；门禁只读 `content/test_demo/templates.json`，`content/veinborn/templates.json`（2 键）未纳入；实测 veinborn 2 键当前均在表内，但拼错时不会被发现。
- 建议修法：门禁改为遍历 `content/*/templates.json`；`resolve_templates` 对未知 key 记 warning（或提供 strict 开关供校验脚本用）。

### L7【低】战斗结束后仍输出「→ 攻击 或 攻击 <技能名>」

- 位置：`qbot_rpg/commands/battle_commands.py:1293`（`tail=_hud_tail_line(ctx)`）→ `qbot_rpg/core/message_format/battle_render.py:279-280`
- 证据：`render_battle_end` 对 `tail` 无条件追加；win/lose/escape 结束后该提示已无可行行动，仍置底显示。这是用户 2026-09-12「置底」拍板的直接后果，列此供确认是否只应在 `status is None/进行中` 输出。
- 建议修法：若确认不想要，在 `_dispatch_battle_end` 按 `status` 决定是否传 tail（例如仅 `draw`/存活续战语义才给）。

### L8【低】`EnrichedTurnReport.from_report` 成为第二构造点（与 `enrich_round_report` 重复）

- 位置：`qbot_rpg/commands/battle_commands.py:236-291`（`from_report`）与 `:346-375`（`enrich_round_report`）都手写同一份 HUD 字段映射；全仓无调用方（grep 无命中）。
- 证据/风险：正是 `02_遗留登记.md` #26 警告的「新增字段必须同步两个投影」同款陷阱——现在又多了一个构造点，且未被测试覆盖；未来加 HUD 字段漏改 `from_report` 不会报错。
- 建议修法：删除 `from_report`，或让 `enrich_round_report` 复用它，只保留一个映射点。

---

## 二、② 与规范不一致

### M7【中】本次新增了玩家可见的硬编码中文（规范 §一/§三「零硬编码」「免斜杠」）

基线对比（AST 提取非 docstring 的中文常量，`4d02ac7` vs HEAD）显示 `basic_commands.py` 新增以下**玩家可见**字面量：

| 位置 | 新增字面量 | 说明 |
|---|---|---|
| `qbot_rpg/commands/basic_commands.py:159` | `"❌ 请先创建角色\n发 注册 名字 职业"` | `TPL_REGISTER_GATE` |
| `:170` | `"❌ 穿戴请用 使用 <序号>\n序号见 背包 列表\n示例：发 使用 1"` | `TPL_EQUIP_NAME_HINT` |
| `:184` | `_ENERGY_LABELS`（`灵能/精力/聚焦`） | 详情「消耗」行 |
| `:192-204` | `_SKILL_TAG_LABELS`（`【伤害】…【打断】`） | `brief` 兜底标签 |
| `:2083/2087/2118/2136/2140` | `"类型"/"标签"/"消耗"/"效果"/"行动恢复"` | 作为 `skill_info_line` 的 `{k}` 直接写死在代码 |
| `:2104/2116/2127/2130/2132/2134` | `f"{...} {n}"` / `"冷却 {cd} 次行动"` / `"破坏值 {bp}"` / `"霸体"/"打断"` | 详情数值行 |

其中 `TPL_REGISTER_GATE` **不只在 basic_commands 使用**：`battle_commands.py:1310`、`checkin_commands.py:173`、`codex_commands.py:66`、`dialog_commands.py:192`、`log_commands.py:164`、`quest_commands.py:188`、`shop_commands.py:139`、`shortcut_commands.py:100`、`status_commands.py:113`、`use_commands.py:172` 全部 `return TPL_REGISTER_GATE` 常量直出。`_gate`（`basic_commands.py:441-450`）自己已改走 `tpl_of(ctx, "basic_register_gate")`，但兄弟模块没有 —— 内容包覆盖 `basic_register_gate` 对这 10 处无效。
`basic_commands.py:48-52` 的模块 docstring 自称「本层零文案常量」，与上述实现不符。
- 建议修法：兄弟模块统一改 `tpl_of(ctx, "<各自的 register gate key>")`（或保留一个共享渲染 helper）；标签兜底字典迁入表（如 `skill_tag_*` 键 + `meta.prose`/数据映射豁免登记），`skill_info_line` 的 `k` 也改由表键承载（`skill_info_kind_label` 等）。若这些确属「数据映射豁免」，请在 `02_遗留登记.md` §B 明确登记，别让规范与实现互相打架。

### M8【中】仍带斜杠的玩家可见指令提示

- 位置与证据（均经引擎 `message` 透传到玩家，`cmd_*` 直接 `str(res.get("message"))`）：
  - `qbot_rpg/core/alchemy_core.py:744`：`"当前没有调合会话，先 /炼金 <配方> 开始"`
  - `qbot_rpg/core/alchemy_core.py:893`：同上
  - `qbot_rpg/core/alchemy_settle.py:461`：同上
  - `qbot_rpg/core/alchemy_core.py:747`：`"投料参数非法"`（无斜杠但同样未迁表）
  - 同类残留：`alchemy_core.py:777/790/829/990`、`alchemy_deep.py:356/358/364/529/572/588/689-707/785+`、`alchemy_helper.py:486-502`
- 证据补充：表内亦有 2 处 `/` 分隔（`explore_enter_noarg='❌ 发 进入 上/下/左/右…'`、`pvp_err_unknown_sep='❌ 不支持列表/数量/键值…'`），规范「多选一写『或』」；`battle_settle_levelup*`/`worldtime_disabled` 等的 `/` 为 `HP/MP`、`时间/天气`，非指令，可豁免。
- 建议修法：斜杠指令提示改免斜杠（`发 炼金 <配方>`）并迁表；`上/下/左/右` 改「或」；把这些残留补进 `02_遗留登记.md` 的引擎文案专项清单（当前 #52/#59 只列了部分）。

### L3【低】HUD 三键超 28 半角且未做 prose 豁免，宽度门禁只 WARN 不拦截

- 位置：`qbot_rpg/core/templates/template_table.json` 的 `battle_hud_player_hp` / `battle_hud_player_mp` / `battle_hud_enemy_hp`
- 证据：`scripts/check_template_width.py` 实测输出
  ```
  [WARN] battle_hud_player_hp L1 估算 40/28半角：'剩余生命：{hp}/{max}（{pct}%）'
  [WARN] battle_hud_player_mp L1 估算 40/28半角：'剩余法力：{mp}/{max}（{pct}%）'
  [WARN] battle_hud_enemy_hp L1 估算 40/28半角：'怪物生命：{hp}/{max}（{pct}%）'
  表内 792 条：FAIL 0 / WARN 17
  ```
  三键均不在 `meta.prose_keys`（实测列表无 battle_hud_*）；`tests/unit/test_template_table.py:72-76` 只断言 `not fails`，WARN 完全不拦截。规范 §三「结构化行必须 ≤B，禁止依赖自动换行」。
- 建议修法：要么按数值政策改设计（如标签行与 `{hp}/{max}（{pct}%）` 拆两行，或压到 8 位数字仍 ≤28），要么把这三键以「数值行允许超宽」理由登记 `meta.prose_keys`，并把宽度门禁从「只 0 FAIL」升级为「新增 WARN 需显式豁免登记」。

### L4【低】`丨` 连接符硬编码在渲染层

- 位置：`qbot_rpg/core/message_format/battle_render.py:455`：`{"status": "丨".join(_states)}`
- 证据：规范标记集为 `｜`（全角竖线）与换行优先；`丨`（U+4E28）不在登记集，且是渲染层硬编码，内容包无法改。
- 建议修法：加表键（如 `battle_hud_state_sep`，默认 `丨` 或 `\n`），或至少登记该标记为允许符号。

### L5【低】HUD「玩家站位」去掉【】与规范 §三「方位格一律带【】」冲突

- 位置：`qbot_rpg/core/message_format/battle_render.py:1004-1007`（`_position_cn` 返回裸词）→ `battle_hud_player_pos='玩家站位：{pos}'`
- 证据：`00_方案与规范_v1.md` §三「方位强调（2026-09-12 用户拍板）：战斗方位格一律带【】…」；而 HUD v2（`02_遗留登记.md` #25）按用户样稿「站位去【】」。两处 2026-09-12 拍板互相矛盾，代码只实现了 HUD 侧。`battle_enemy_position_miss` 等其它行仍是 `【{pos}】`（`_position_cn` 输出裸词 + 模板补括号），说明去【】只发生在 HUD 行。
- 建议修法：在规范 §三 补一条「HUD 站位行例外（无【】）」，或 HUD 行也加【】；否则后续批会按规范又加回去。

### L6【低】「怪物状态」有意不折行但未登记为 prose 豁免

- 位置：`qbot_rpg/core/message_format/battle_render.py:452-456`；测试 `tests/unit/test_battle_hud_v2.py:162-170` 已断言可超 14 全角不折行。
- 证据：`meta.prose_keys` 只登记了 `skill_info_derived` 等 26 键，没有 `battle_hud_enemy_status`；`check_template_width` 因占位符 `{status}` 估算仅 6 半角而不告警，属于「侥幸不拦」。
- 建议修法：把 `battle_hud_enemy_status` 也登记 `meta.prose_keys`（理由：状态完整枚举、有意超宽），与 `skill_info_derived` 同口径。

---

## 三、③ 测试盲区（应补的断言）

> 现有覆盖较好的部分：`tests/unit/test_battle_hud_v2.py`（_fmt_pct、按需显示、怪物无朝向、玩家站位、状态行、effect 行、payload 取数/容错、effect_events 接线透传）、`tests/unit/test_battle_wiring.py`（两段合并后 `_joined.count(PREFIX)==1`，间接覆盖 suppress_prefix 的可观测结果）、`tests/unit/test_battle_render_startend.py`（16 行折叠正常路径）。

| # | 盲区 | 现状 | 建议补的断言 |
|---|---|---|---|
| T1 | `defer_tail` 全链路 | 零测试（`grep defer_tail tests/` 无命中） | `_render_action_hint_from_report(SimpleNamespace(defer_tail=True, ...))` 不含 `→ 攻击`；`render_battle_end(..., tail=...)` 末行 == tail；`_run_battle_action` 终局时 `_without_npc_outcomes` 收到 `defer_tail=True` |
| T2 | effect_events 单次性/去重 | 无（H1 因此漏网） | 走 `_dispatch_merged_action`（含 NPC outcome）后，把 `sender.calls` join 起来，断言 `joined.count("【持续效果】") == 1`（DOT 事件只播一次） |
| T3 | 投影透传（#26 陷阱） | `test_ctb_hud_pos_regression.py` 只锁 `player_pos/enemy_pos` | 对 `_without_npc_outcomes` / `_without_player_outcomes` 逐个断言 HUD 9 字段（`player_mp/max/shield/turns`、`enemy_shield/turns`、`enemy_air`、`enemy_broken_parts`、`effect_events`）与原报告相等 |
| T4 | `_derived_tags` 全分支 | 仅 `test_basic_commands.py:494` 一处 `【消耗】【派生】` | 为 `combo`/`combo_push`/`combo_preserve`、`armor`、`interrupt`、`air_policy`、`counter_type=dodge/parry`、`effects[].type=reposition`、`break_power`、`hits>1` 各构造一个 def，断言标签集合；补 `skill_brief` 在内容包 `brief` 非空时原样返回（不落兜底） |
| T5 | `_status_display_name` 的 `ctx["statuses"]` 分支 | `test_battle_hud_v2.py:200-205` 只测 name 与 id 回落 | 传 `ctx={"statuses": {"burn": {"name": "燃烧"}}}` 且事件不带 name，断言输出「燃烧」；以及 `statuses[sid]` 为字符串/缺 name 的回落 |
| T6 | 终态门禁②「白名单」| `test_template_table_final.py:46-50` 恒真：`PLACEHOLDER_WHITELIST` 就是由同一份表值 `setdefault` 派生的（`templates/__init__.py:55-56`），且 `base∩table == []`（实测） | 改为对照手工维护/冻结的期望集合，或反向断言「表值占位符 ⊆ 聚合白名单且**不能**仅来自自动派生」；`test_template_table.py:57-63` 同款恒真，一并修 |
| T7 | 宽度门禁 | `test_template_table.py:72-76` 只断言 0 FAIL；WARN 17 长年不降 | 断言 WARN 集合等于一份显式豁免清单（或数量上限），新增 WARN 必须走 `meta.prose_keys` 显式登记 |
| T8 | 内容包表外键 | 只查 test_demo（`test_template_table_final.py:64-68`） | 遍历 `content/*/templates.json`；并对「未知 key 被静默忽略」加一条 `caplog` 断言（或 strict 模式） |
| T9 | `battle_hud_payload` 真形态 | `test_battle_hud_v2.py:212-228` 用**手造** snap；未验证 `engine.battle_state()` 真键名 | 用真实 `BattleEngine` 跑一回合后取 `battle_state()` 断言 mp/shield/parts/combat_position 键命中（当前手工核对通过，但无回归保护） |
| T10 | `tick_turns` 返回值 | `tests/unit/test_effects_runtime.py:240` 调 `rt.tick_turns("enemy")` 但不接收返回值 | 断言归零状态被返回、`turns==-1/0` 不返回；`tick_turn_end` 同时产出 `status_expired` 且带 `side/name` |
| T11 | `_fold_message_lines` 边界 | 只有「正常超限」用例（`test_battle_render_startend.py:315-345`） | 单元素 20 物理行 / 首元素 15 行的用例，断言输出物理行 ≤ max_lines（当前会失败，对应 M3） |

---

## 四、④ 回归风险

### R1【高·同 H1】effect_events 对既有战斗流程的影响
`_render_effect_lines` 被挂到 4 个入口（`battle_render.py:197/1994/2070/2148`）；任何被两段同时消费的 `effect_events` 都会重复。修复前，凡「一次玩家操作含 NPC 连锁」（CTB 常态）的回合都会在实机出现重复的效果行——`02_遗留登记.md` #31「偶发两条回复内容相同」很可能就是同类症状（文档记为「预存、另案排查」，本次新增的 effect 行会加重它）。

### R2【中】`tick_turns` 返回值 + `tick_turn_end` 新增事件类型
- `effects.py:770-788` 返回值从 `None` 变 `List[Dict]`：现有调用方（`effects.py:1303`、`tests/unit/test_effects_runtime.py:240`）忽略返回值，兼容。
- 但 `effects.py:1303-1307` 会往 `tick_turn_end` 的 `log` 追加新类型 `status_expired`，而该 log 会 `extend` 进 `battle.py:4673` 的 `self._snap["turn_end_log"]`。全仓该键唯一读写点都在 `battle.py`（无外部消费方），风险主要为**存档体积**与旧快照读方的类型假设；建议在续战/存档测试里加一条「含 status_expired 的 turn_end_log 可回灌」断言。

### R3【中】引擎侧 `tpl_of(ctx, ...)` 的 ctx 缺失会静默失配内容包
- `alchemy_battle.py:284` 的 `instant_eligible(..., ctx=None)`、`alchemy_deep.py:369` 的 `deep_snapshot(..., ctx=None)`、`alchemy_helper.py:120` 的 `parse_task_spec(spec, ctx=None)` 新增了可选 ctx；漏传时 `tpl_of` 回落 `DEFAULT_TEMPLATES`（表默认值），**不报错**，内容包覆盖静默失效。
- 实测：`alchemy_commands.py:2540` 已传 `ctx=ctx`、`:3238` 已传 `parse_task_spec(spec, ctx)`；`plant/harvest/greenhouse`（`:3183/:3206/:3534`）也已传 ctx。**但仍建议**给 `instant_eligible` 这类「新加 ctx 形参」的方法加一条调用点测试，防止后续新调用点漏传。

### R4【低】`TPL_REGISTER_GATE` 常量直出的覆盖失效（同 M7）
改文案/内容包覆盖 `basic_register_gate` 时，10 个兄弟模块（见 M7 列表）不会变。这是「可配置性回归」，且 `test_demo` 的镜像也改不到它们。

### R5【低】技能列表体积膨胀
`basic_commands.py:1961-1966` 每个技能从 1 行变为「行 + 简述 + 分隔线」最多 3 行；一页 5 个技能 ≈ 15 行 + 头部 + 尾段 ≈ 17 行。技能列表不走 16 行折叠（仅战斗消息走），对照「手机 QQ 排版」目标属于新增长消息；若用户端反馈刷屏，可考虑简述行合并或降低每页条数。无测试断言页高。

---

## 五、建议修复顺序

1. **H1**（重复渲染，实机可见）→ 顺带补 T2。
2. **M2 / M3**（16 行硬上限被击穿，属「铁律 11」门禁）→ 补 T11。
3. **M1**（事件丢失）与 **M6**（死迁移，影响内容作者）。
4. **M4 / M5**（健壮性 + 标签兜底漏项）。
5. **M7 / M8**（硬编码与斜杠残留）→ 与 `02_遗留登记.md` 合并登记。
6. L1–L8 与测试盲区 T1、T3–T10 随批补齐；**T6/T7 优先**，因为这两个门禁当前形同虚设，是后续批「越改越偏」的温床。

> 复核人：dsh ｜ 依据：`4d02ac7..a3ce80f` 全量 diff + HEAD 文件行号 + 本文所列复现命令 ｜ pytest 不可用，未执行全量回归。
