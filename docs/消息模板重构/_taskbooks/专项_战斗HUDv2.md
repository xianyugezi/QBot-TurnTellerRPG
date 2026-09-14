# 任务书 · 专项·战斗 HUD v2（按用户样稿重构回合消息）

> 2026-09-12 · 消息模板重构战役 · 执行者：子 agent（本任务书为唯一指令源）
> 用户原话：「消息模板改成这样，如果没有护盾/法力等资源则不显示这些资源，持续效果也一样。
> 另外，怪物的朝向就是正面，只有玩家位于怪物的哪个方位，没有怪物哪个方位。」

## 1. 用户样稿（**逐字**=目标形态）

**现状（用户收到的实况，问题态）**：
```
Lv3.zerc - -
（怪物行动）
❌ 脊冢幼兽使出幼兽扑咬，你受到 39 伤害（HP 484/523）
Lv3.zerc - -
✅ 你御剑·斩
造成 76 伤害
你 484/523【正面上空】
脊冢幼兽 90/263【正面】
→ 攻击 或 攻击 <技能名>
```

**目标（用户手写样稿）**：
```
Lv3.玩家名
（怪物行动）
❌ 脊冢幼兽使出幼兽扑咬，你受到 39 伤害。
【持续效果】燃烧 生效，造成 100 伤害。
【效果失效】狂暴 效果时间结束。
✅ 你发动技能 御剑·斩，造成 76 伤害。
【持续效果】流血 生效，你受到 1 伤害。
剩余生命：484/523（92.5%）
剩余法力：1/100（1%）
剩余护盾：100（3s）
玩家站位：正面上空
怪物生命：90/263（34.2%）
怪物护盾：20（1s）
怪物状态：跃空丨左翼破坏丨尾部破坏
→ 攻击 或 攻击 <技能名>
```

## 2. 口径（必须）

1. **分项资源行 + 百分比**：`剩余生命：{hp}/{max}（{pct}%）`；pct = hp/max×100，一位小数，
   整数省略小数（92.5% / 34.2% / 1% / 100%）。
2. **按需显示（用户明确）**：无法力资源→不显示「剩余法力」行；无护盾→不显示「剩余护盾」/「怪物护盾」行；
   无持续效果/效果失效→不出对应行；怪物无状态→不显示「怪物状态」行。**不要输出空行/占位。**
3. **方位语义修正（用户明确）**：**怪物没有朝向**——不得再显示【正面】等怪物方位；
   只有**玩家站位** = 玩家相对于怪物的方位（值域 正面/背后/左侧/右侧，空中追加「上空」，如 `正面上空`）。
   「玩家站位：正面上空」**不带方括号**（按用户最新样稿；覆盖早前「方位【】」口径，notes 注明）。
4. **行动行**（按样稿风格）：怪行动 `❌ {name}使出{action}，你受到 {damage} 伤害。`；
   玩家技能/攻击 `✅ 你发动技能 {skill}，造成 {damage} 伤害。`（叙述句含「，」与句号「。」；
   样稿中「使出X」「发动技能 X」为**展示前缀**，与现有 `battle_commands` 展示串注入通道对齐）。
5. **行宽**：结构化行（剩余生命/法力/护盾/站位/怪物生命/护盾/状态）仍 ≤14 全角（28 半角）；
   样稿中两行超宽（怪行动句 ≈20 字、怪物状态 17 字）——按 14 上限拆分或精简（**不依赖手机折行**）；
   行动叙述句允许按样稿形态（若超 14 在 notes 说明拆法）。
6. 既有保留：`（怪物行动）` 标题行、尾行 `→ 攻击 或 攻击 <技能名>`；零装饰 emoji（仅 ✅❌【】「」）。

## 3. 数据面地图（已勘察，直接可用；缺口如实报告）

- **渲染入口**：`qbot_rpg/core/message_format/battle_render.py`
  - `_render_round_action()`（≈L690-710）：现仅取 player/enemy HP+max + player_pos/enemy_pos → **需扩展取数**；
  - `render_action_hint()`（≈L360-400）：HUD 两行 + 尾行组装处 → 重构为分项块；
  - 敌方行动行组装 ≈L773（docstring 仍为旧式 `…你受到 N 伤害（HP …）`）与 `_render_enemy_action`（≈L1100+）→ 改为样稿式。
- **报告对象**：`qbot_rpg/core/battle.py::TurnReport`（≈L374，字段：turn/action_seq/battle_time/player/enemy/
  player_pos/enemy_pos/outcomes/log…）→ **需补**：player_mp(_max)、player_shield(_turns)、enemy_shield(_turns)、
  enemy_states、效果事件（见下）。注入点在 `qbot_rpg/commands/battle_commands.py`
  （`_enrich_*` 系列，≈L240-340；接线层可自引擎对象/快照取数）。
- **持续效果（DOT/到期）**：引擎 `core/battle.py` `dot_pool`（≈L2565 行动开始结算 / ≈L4660 行动结束）
  → 产出 tick/到期事件（可入 outcome.side_effects 或 report.log），渲染为 `【持续效果】…`/`【效果失效】…`。
- **护盾**：拦截链 `effects.py` 阶段②（先扣护盾）+ `battle.py`≈L4482 → 取当前护盾值与剩余回合（s）。
- **怪物状态**：跃空姿态状态表（`battle.py`≈L313 空中姿态状态 ID 全集）+ 部位破坏（`battle_part_broken*` 已迁表）
  → 汇总为 `怪物状态：跃空丨左翼破坏丨尾部破坏`（丨分隔；超宽则拆行）。
- **优先级坑**：`battle.py`≈L3215「渲染层 message 优先直出」——检查旧串是否抢先（现状实况行的
  `（HP …）` 即来自旧组装）；确保新渲染生效。

> 若某项（如护盾剩余回合/效果到期）在引擎侧确实不可得：**如实列出缺口与建议**（例如「需引擎补字段」），
> 不得编造数据或显示假行。

## 4. 工作清单

1. 通读上述数据面；确定每个样稿行的**数据来源**（列一张「行 → 数据字段/事件 → 取值处」表放进报告）。
2. **先写 fragment**：`/tmp/tpl_b7s/docs/消息模板重构/_fragments/b7s.json`——新增键建议（可调整命名，保持 `battle_hud_*`/`battle_effect_*` 前缀）：
   `battle_hud_player_hp` / `battle_hud_player_mp` / `battle_hud_player_shield` / `battle_hud_player_pos` /
   `battle_hud_enemy_hp` / `battle_hud_enemy_shield` / `battle_hud_enemy_status` / `battle_effect_tick` / `battle_effect_expire`
   （旧键 `battle_action_hint` / `battle_action_hint_tail` / `battle_resource_cur_max` 等如被替代：从表与分区移除，
   相关测试同步；notes 写清替代关系）。
3. 改代码：引擎取数（TurnReport 字段/事件）→ commands 注入 → battle_render 组装（条件行 + 百分比 + 方位语义）。
4. 修/加测试（tests/unit/test_battle_render_*.py、test_ctb_render.py、相关 e2e）；新增用例至少覆盖：
   ① 无护盾/无法力→对应行不出现；② 有护盾/法力→出现且格式正确；③ 百分比格式化（92.5/34.2/1/100）；
   ④ 怪物行不含【正面】等朝向；⑤ 玩家站位行值=方位（含上空）；⑥ 持续效果/失效行出现与缺省。
5. 自校验：checker 0 FAIL；test_template_table + test_emoji_discipline；定向测试；**全量 tests/unit 一次**。
6. 提交（worktree 分支 tpl-b7s，禁止 push/动 main）→ 报告。

## 5. 预算纪律（重要）
本任务含引擎取数，比纯文本批重。**第一步就把 fragment 落盘**；每完成一节 commit；临近工具/时间上限：
优先 (a) fragment (b) 已改代码+测试 commit (c) 如实报告缺口（主 agent 接手收口）。
**绝不允许**：谎报完成、编造数据行、把目标行留成假值。

## 6. 报告格式（回复正文【内联】）
- 行→数据来源表；fragment 路径 + 全部新键文案；变更文件清单（引擎/commands/渲染/模板/测试）
- 测试结果（定向＋全量计数原文）；checker 输出；**数据缺口清单**（如有）；未完成项；commit hash
