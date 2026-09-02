# veinborn 预设游戏包 · 开工启动包（交接文档）

> 生成：2026-09-02 ｜ 上一会话收尾（框架能力铺垫①②③ 全部落地）
> 用途：新对话直接开工 veinborn 预设包的权威上下文（无需重读旧会话）

---

## 一、任务源头

用户原始需求（2026-09-02）：
1. 读 https://github.com/xianyugezi/veinborn-hunters（「蚀脉猎师」v0 规划稿 = Primal 桌游机制 × 苍穹界世界观 × QBot 引擎）
2. **不增删改其功能**评估对 QBot-TurnTellerRPG 框架的适配性 → 已完成（见 §三）
3. 据此制作**框架第一个预设游戏包**（content 预设包，类比 content/test_demo）→ **本次开工目标**
4. 途中扩展为：把做不出来的机制纯配置化转换 + 框架级能力补全（enemy 读印记 / 效果引用+条件 / 事件分派器）

用户最新指令（本会话末）：**「继续，收尾完，然后开新对话正式开始做」**——收尾已完成，本文件即新对话启动包。

## 二、当前框架状态（HEAD 7985c72，工作区干净）

权威仓库：/root/QBot-TurnTellerRPG（本地 M13 收官 035c973 之上，本日新增 10 commit）

| commit | 内容 |
|---|---|
| bd87c77 | **功能一** monster_conditions enemy_mark/player_mark 触发（TRIGGER_TYPES 15 类 + 校验 A06a + 测试 12 + 契约 1e/1f/m2） |
| f3e1614 | **功能二** 效果引用归一 + condition 门控（execute_action 入口展开 {effect,overrides} + 查表合成 + L2 容器 + 环截断；测试 10 + 1b 契约） |
| 2442126 | 功能三立项设计契约 |
| 7651753 | **功能三批1** event_dispatcher.py 引擎（16 事件组 / effects trigger 消费落地 / statuses on_gain/on_lose/on_expire；测试 12） |
| d746c21 | **功能三批2** battle 接线（battle_start/turn_start/turn_end/action_start/action_end×3/death/battle_end/season_change 收编双轨；测试 7） |
| 9a9811b | **功能三批3** effects 层 status_apply→status_gain + dispel→status_lose（_dispatch_status_event resolver-only registry；测试 4） |
| 7985c72 | 记录.md 功能三收官同步 |

门禁：全仓 tests/unit 全绿（~5700+）+ ruff/mypy 绿。工具链 .venv/bin/python（3.14，勿用系统 python3）。

## 三、veinborn 适配性结论（已交付，见 /root/deliverables/veinborn_framework_适配性评估.md）

- **适配性高**；三大支柱框架侧已全具备（transform 恒效 = 专精聚焦 / resource_axis = 精力 / 怪物意图 = 行为预告）
- 设计稿词面偏差（改数据不改框架）：四色卡写 action.json（实际玩家技能落 **skills.json**）；skill_chains 写 steps+derive（真实 = trigger_skill+steps[{from,to}]）；zone_change 写数组（真实 = 对象 {enabled,hp_threshold,targets,timing}）；姿态推进按 dungeon_boss 三阶段（70/35）而非换实体
- 框架真缺（已补/待补）：部位破坏（用破坏印记二段式纯配置解决，见下）、敌方资源轴（可省略用印记近似）
- **框架新能力（本次会话产出，veinborn 直接受益）**：
  - enemy 条件可读印记：`{"type":"enemy_mark","mark":"vein_core_broken","absent":true}`（部位技无破坏印记才可用）
  - 效果引用+condition：`{"effect":"smite","condition":{"target_marks":{"vulnerable":{"min":1}}}}`（有破绽这刀 180）
  - 事件分派：effects `trigger: battle_start/turn_start/turn_end/action_end/death/...` + statuses `on_gain/on_lose`（盾碎爆炸/获得回血/死亡触发全可配）

## 四、纯配置转换设计结论（已交付 /root/deliverables/veinborn_纯配置转换设计.md + 用户逐条拍板修正）

用户拍板的 4 条修正（全部可行，实现载体已实证）：
1. **敌方每回合 +1（困斗蓄能）**：给怪物所有行动带 mark_add 自挂困斗印记（battle L2383 effects 通道实证可行）——替代"回合自动+1"
2. **未出某色→受威胁**：回合开始挂"未防御"印记，出对应色牌（防御技 effect mark_remove）解除 → 未解除转威胁印记
3. **印记不可消除**：marks 本身免疫驱散（marks.py §五）；怪不配 clear 技即永续——玩家给怪挂的破坏印记可留存
4. **部位技无印记才可用**：✅ 功能一 enemy_mark absent 条件实现（部位破坏印记留 boss 身上 → 部位技 trigger 条件 absent）

**部位破坏（用户原创方案，纯配置成立）**：
- 破坏值积累 = 印记计数（max_stack 封顶不溢出）+ 每次打击 mark_add +N
- 满层 → 部位破坏印记（另一印记；battle 型 duration 永续不 tick 不消除）
- 技能读破坏印记增伤：condition target_marks 门控派生技 or 公式占位符动态增伤
- 部位技失效：enemy_mark absent 条件（功能一）——破坏印记在 → 部位技不可用

**困斗值轴 surge（原设计缺引擎）**：收敛为困斗印记 + enemy_mark min 条件触发宣泄大招（功能一）

**tag 四色坑**：skills 校验器 tag 锁死六枚举（none/combo/combo_preserve/combo_push/interrupt/armor）——四色 attack/maneuver/parry/dodge 会红拦。**拍板点遗留**：用 attack_type 表达 or 改枚举加值（后者非纯配置，需用户拍板）

## 五、开工路径（本次新对话建议）

1. **03 schema 修正稿**（转译前必做）：veinborn 02/03 设计稿 → 按真实引擎 schema 回写（skills/effects/statuses/marks/enemies 字段 + 部位破坏印记二段式 + 困斗印记 + 受威胁印记 + 事件 trigger/on_gain/on_lose 利用）——先产文档（放 /root/deliverables/veinborn_03_schema_修正稿.md）待用户确认
2. **content/veinborn/ 预设包**（类比 content/test_demo 结构）：按 04 转译批次做，包内容 = 2 职业 + 原兽×姿态 + 第 1 猎季 + 四色技能表（先解决 tag 拍板）
3. 验收：content 校验器全过 + 战斗冒烟（用 event_dispatcher/trigger 验证部位破坏全链）+ test_demo 零破坏回归

## 六、相关文件速查

| 文件 | 内容 |
|---|---|
| /tmp/veinborn-hunters/ | 设计稿源（7 md，未修改）：00 总览/01 世界观/02 机制映射/03 schema/04 批次/05 名词法务 |
| /root/deliverables/veinborn_framework_适配性评估.md | 适配性报告（含 N-01~04 拍板项） |
| /root/deliverables/veinborn_纯配置转换设计.md | 转换设计（含确实不行清单 + 补偿） |
| /root/deliverables/框架_战斗状态条件化设计.md | ①② 功能设计源 |
| /root/QBot-TurnTellerRPG/docs/框架_功能二_效果引用归一与条件化_设计.md | 功能二设计契约 |
| /root/QBot-TurnTellerRPG/docs/框架_功能三_通用效果事件分派器_设计.md | 功能三设计契约 |
| /root/QBot-TurnTellerRPG/content/test_demo/ | 预设包范例（结构/字段参考） |
| /root/QBot-TurnTellerRPG/记录.md | 本日全部工作记录 |

## 七、遗留拍板项（新对话首问用户）

1. **tag 四色**：接受用 attack_type（斩/打/突/魔五枚举已有）表达四色语义？还是给 tag 枚举加 attack/maneuver/parry/dodge 值（小改框架 schema，非纯配置）？
2. **部位破坏与姿态推进**：合并成"同实体多阶段"（dungeon_boss phases）还是独立破坏印记轴？（设计稿两概念并存，用户此前倾向纯配置印记）
3. 预设包首版范围：2 职业 + 1 原兽 + 第 1 猎季够不够？还是先做 03 修正稿确认再定批次？
