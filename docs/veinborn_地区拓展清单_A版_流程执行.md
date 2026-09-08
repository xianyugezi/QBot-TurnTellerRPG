# 后续地区拓展清单·A版（流程执行版）

> 适用范围：veinborn（蚀脉猎师·群脊荒原）阶段二及以后，每新增一个地区（E 区起）照此流程执行。
> 编号体系：P0-P8 流程阶段序——每阶段有明确「做什么/产出物/验收标准」，串行推进。
> 与 B/C 版关系：B 版=门禁视角（每道门=可验收出口）；C 版=模板视角（每项给可填骨架）；本版=执行视角（按阶段推进每一步做什么、怎么验收、常见坑）。可混合选用：流程照 A、验收照 B、落内容套 C。
> 参照基线：docs/veinborn_阶段一_区域风味设计_v1.md、docs/veinborn_阶段一_数值模型_1-35_v2.md、docs/veinborn_装备体系规划_v1.md、content/veinborn/ 全 JSON、docs/qa_report_20260907.md。

---

## P0 前置勘察（半天）

**做什么**：摸清旧区 A-D 区怎么落的，新区只准对齐不准发明。
- 读文档锚点：区域风味设计 v1（A-D 区表/生态混居规则/Boss 召唤限制）、数值模型 v2（公式口径/玩家成长/区域数值总表/Boss 表/装备档位/经验曲线）、装备体系规划 v1。
- 读内容 JSON 摸字段形状（不是只看文档——文档字段名与 loader 实际消费可能差）：maps.json（exits 结构/camp/monsters 组）、enemies.json（stats 键名/rewards/drops/actions 引用）、quest.json（type/zone/unlock_chain/conditions 形态）、npc.json（dialogues/interactions）、items/equipment/shop/forge、action.json（kinds 表 68 条 active）、effects/statuses/marks/skill_chains、settings（exp_curve）。
- 产出《旧区做法对照表》：A 4 图/B 4 图/C 5+1/D 7；每图主怪+混居怪；每区 1-2 精英；主 Boss 位+隐藏 Boss；任务链（A 区 5 链 q_tut0-4 引导、B-D 区 q_b1-q_d3 区链）；营地（a3/b3/c3/d3 中段 camp）；装备线六系（脉铁/骨脊/蚀晶/鳞革/渊脉/王骸）区段档。

**产出物**：《X区_开工页》（区代号/图前缀/接续点/推荐等级带）+《旧区做法对照表》。
**验收标准**：开工页四要素齐；对照表每行有出处（区名/图名/JSON 文件）。

**常见坑**：只看文档不读 JSON → 字段形状对不上 loader；照搬 A 区新手节奏做后期区（引导任务/白给装备只属于 A）；新区 id 撞旧区词根。

---

## P1 概念与风味定稿（1-2 天）

**做什么**：
- 世界基调续接：新区与苍穹界/群脊荒原的承接关系——为何存在、接哪张旧图（D 区预留「D2 夜嚎森林西缘 → 阶段二」通道）、给旧区留什么回望点。
- 生态设计：主怪+混居怪分配，混居跨度 ≤1 区段；下区怪提前露脸（放上区靠后图）、上区怪残留（放下区靠前图）。
- 玩家数值门：进区门槛（推荐 Lv/装备线档/主线完成度）+ 毕业门槛（下一区会拿什么打你），对照 v2 玩家成长外推。
- 地区三表（必须对齐风味 v1 表格式）：图表 | # | 图名 | 风味 | 主怪 | 混居怪 |；怪风味表 | 怪 | 类 | 风味 | 行为特征 |；Boss 行为表（三姿态设计）。
- Boss 召唤限制逐 Boss 写明：召唤行动名/单场上限 1-3 次/间隔冷却 ≥3 回合/绑定血线姿态/召唤物数值偏弱（玩家 1-2 刀清）。

**产出物**：新区风味设计段（可并入/新建 _区域风味设计 文档，格式对齐 v1）+ 三表。
**验收标准**：三表格式逐列对齐 v1；数值门有进区/毕业两行；召唤限制字段齐全；接缝通道有解释。

**常见坑**：三表走样（评审逐格比对 v1 表头）；召唤行动不写冷却次数 → 玩家陷入清小怪重复劳动；入口接旧图却不改旧图 exits（新区在地图上但旧区过不去——图可见性/可达性见 P4）。

---

## P2 数值设计（1-2 天）

**做什么**：
- 怪三档数值表（格式对齐 v2 区域数值总表）：| 怪 | 类 | Lv | HP | atk | con | 斩回 | 单发% | 评 |。对照口径：小怪等级 ≤ 旧区 Boss 等级；斩回=玩家几回合击杀；单发%=怪单发打中值玩家 HP 百分比。与前后区衔接无断崖。
- 经验奖励：A 小怪 100-400 / B 1000-2500 / C 4000-9000 / D 1.5万-4万 曲线外推；settings exp_curve 前缀不断裂；新怪 exp 不与旧区尾 Boss 倒挂。
- 装备素材线：新区怪掉落素材（沿用通用素材 vein_shard + 新怪专属素材）→ 武器系新档位（对照六系表 A前/A后/B/C/C隐D前/D 档）+ 防具套（商店套/精英素材套/Boss 素材套），数值衔接不跳变。
- Boss 数值沿用 v2「Boss 7 只」表结构：首杀/复战同数值；隐藏 Boss 可超模（对照 D隐 8000HP 毕业锚定）但普怪不能借超模名义。

**产出物**：新区数值表 + 装备素材线表（素材→来源怪→用途三列闭环）+ 经验对照。
**验收标准**：数值表六列无空、与前后区 Δ 在模型允许带内；素材-装备-锻造三处接线闭环；新怪 exp 在曲线档内。

**常见坑**：斩回/单发% 只填理论值没跑模拟器（v2 是实跑模型，评审看实跑）；装备线只给一件武器没给全套；经验曲线改了 settings.json exp_curve 没跟。

---

## P3 怪物行动与专属行动（2-3 天，与 P2 数值表并行）

**做什么**（铁序：世界观风味 → 行为特征 → 专属行动——先定怪是什么/怎么打，再设计招式）：
- 小怪 1-2 专属行动；精英 2-3；Boss 3-5（含 1 个召唤类，召唤限 1-3 次/场+冷却 ≥3，绑定姿态/血线）。
- 行动落 action.json（kinds 表 active 类型，新区动作先加 action 再被 enemies.actions 引用）；涉及新印记同步 marks.json；boss 姿态用 phases（threshold 1.0/0.7/0.35 三段 + enter_action + broadcast 播报）或砾冕式 zone_change 三独立 enemy 范式。
- effects/action 全部纯配置，零代码——需要新机制先登记框架缺口走框架流程，不硬塞内容包。

**产出物**：新区全部怪物的 enemies.json 条目 + action.json 新行动 + （如需要）marks/effects 登记。
**验收标准**：行动数符合三档；召唤限制字段齐；broadcast/intro/signal 文案有；无「utility power=0 却期望伤害」的怪动作。

**常见坑**：怪物 action 漏 _derived 派生标记 → 血线触发了但派生大招不结算（QA 误判 Boss 卡死）；utility/power=0 动作期望打伤害（框架已修渲染但内容侧别再造）；召唤物数值做太强 → Boss 战变先清小怪。

---

## P4 地图与通道（1 天）

**做什么**：
- 图数匹配等级带宽度（约 1 大级/图，隐藏图单列——先例 C 5+1/D 7）；每图怪 1-3 种。
- 通道非一本道：跨区通道分散多图、不锁 Boss 图；提前探路通道（上区尾图 → 下区边缘，可采素材/预警）与主线隘口（击败 Boss 后开）双轨——先例 A2→B1 提前通道 + A4 击败 A主 → B2 主线隘口。
- 营地图每区 1 张（区中段，camp + camp_name + safe），先例 a3 骨台/b3 风息台/c3 泽心台/d3 矿灯站；营地=传送目标+安全区。
- respawn_minutes 取表：小怪 3-8 / 精英 15-25 / Boss 30-60；Boss intro/signal 文案（hidden_boss=true 时）。
- 地图可见性纪律：未发现图不泄露——隐藏图/未解锁图不进玩家可见列表（对照 c6 沉渊回廊先例）；玩家导航靠「位置」指令显示当前图出口（不靠地图列表）。

**产出物**：maps.json 新区条目（含 exits/camp/monsters 组/Boss intro）。
**验收标准**：无一本道死锁；无「低等级白进新区图」漏网（进区等级门若需要须配）；隐藏图有解锁条件且不可见；营地图位置中段。

**常见坑**：地图列表泄露未发现图（玩家看见去不了）；exits 漏改旧图 → 旧区到不了新区；隐藏图无解锁条件 → 永不可达（内容校验 RED）。

---

## P5 任务链与 NPC（1-2 天）

**做什么**：
- 主线任务链：新区 3-5 个任务逐级 unlock_chain 串联（先例 q_b1→q_b2→q_b3 区链 + q_tut0→4 引导链），链尾解锁 Boss 图/复战资格；type 用 slay/deliver，conditions 引用真实存在的怪/物 id。
- NPC：任务发牌 NPC（老猎人型）+ 营地 NPC（药婆型疗伤，收费随区递增 50/80/120 先例）+ 商店 NPC 引 shop_refs。
- 复战入口：首杀成就 → NPC 对话选项（condition 检查成就）→ 传送副本图（纯配置，绕开新功能）。
- 引导/新手任务只属于 A 区先例；新区不做白给装备引导。

**产出物**：quest.json 新区链 + npc.json 新区 NPC + 成就/复战接线配置。
**验收标准**：unlock_chain 连续无断；conditions/reward 引用全部真实存在；复战入口模拟器可达。

**常见坑**：任务链断了（中间任务没接上）→ 玩家卡死；NPC 引 shop_refs 指向不存在的店；复战数值与首战不一致（两处配置改一半）。

---

## P6 内容包 JSON 落地与校验（1-2 天）

**做什么**：
- 全部新区条目写入 content/veinborn/ 既有文件对应区段（maps/enemies/quest/npc/items/equipment/shop/forge/effects/action/skill_chains）；若新开模块文件 → manifest.json modules 登记 + 编辑器 auto 页表断言同步（见 P8）。
- 引用健壮性复查：enemies.actions → action.json 存在 id；skills.effects → effects/statuses/marks 存在 id；maps.exits.to → 存在 map id；npc.interactions.shop_refs → shop.json 存在 id；quest.reward/conditions.param → items/enemies 存在 id。
- 文案零 emoji（新区全部 desc/name/broadcast/templates）。
- 跑内容包校验（scripts/check_m7_content.py --path content/veinborn）：RED 0；YELLOW 相对既有基线（249）无净增，净增逐条说明落盘。

**产出物**：全部 JSON 落地 + 校验报告。
**验收标准**：引用复查全绿；RED 0；黄不净增（或逐条解释）；零 emoji。

**常见坑**：漏 entrance/unlock 声明 → 隐藏图变 RED；新增黄不解释；templates.json 覆盖照抄旧模板丢 ctx 占位符（注册引导/转职提示覆盖需 ctx 装配注入，P1-2 修复先例——复制粘贴会渲染崩/空提示）。

---

## P7 黑盒验证（1-2 天）

**做什么**（scripts/qq_group_sim.py，单 --file 长序列逐发，勿跨进程——跨进程回滚末发是模拟器已知坑）：
1. 全流程长序列：注册（验证注册引导文案）→ 引导推图 → 任务链（领/杀/交/奖励入账）→ 推进跨区（旧区进新区可达）→ Boss（信号/姿态/召唤次数上限）→ 复战（成就/NPC/传送）→ 死亡惩罚（虚弱拦截/经验掉落/疗伤）→ 营地休息（camp 图恢复）。
2. 数值抽查三表：伤害（怪单发% vs P2 表 ±容差、玩家斩回接近表值、派生技结算正常——对照 P1-1 cap 修复）、掉落（drops 表概率/特殊掉落通道）、经验入账（rewards.exp + exp_curve 档位一致）。
3. 边界抽查：1 级角色不能白进新区（要拦则拦得有理）；隐藏 Boss 图未解锁不可进；死亡回营地后新区图 respawn 正常；复战 Boss 数值与首战一致。

**产出物**：长序列命令文件+输出存档+实测 vs 设计值对照表。
**验收标准**：全流程出口文案/状态符合预期；数值三抽查对齐 P2 表；无「低等级偷渡/未解锁图可进/Boss 召唤超次数」三类漏网。

**常见坑**：只测到 Boss 门口就停（任务链/死亡惩罚/营地休息最易漏）；看「结算 ok」不看「入账数字」（以 DB 为准）；复制粘贴旧区序列（新区通道/怪名不同跑不完）。

---

## P8 回归与收尾（半天）

**做什么**：
1. 全仓 pytest：基线 12 failed（环境性集合：test_g0_architecture/test_battle_render_skill×2/test_codex_commands/test_contest/test_e2e_m4_smoke×4/test_emoji_discipline/test_investigate_commands/test_m125_formula_assembly）零新增——失败集合逐条与基线比对。
2. ruff 只查新区改动/新增文件，零告警。
3. 编辑器 auto 页断言同步：veinborn 模块数变化时同步 tests/unit/test_editor_registry.py 的 test_auto_pages_veinborn_all_modules（先例：模块数 22 → auto 页 len(ids)==20——模块数变则重算同步注释）；模块数未变则记录「不需动」。
4. 记录.md 追加（批次/提交/验收门禁/已知基线四节）；触发了引擎修改 → 登记 docs/veinborn_引擎缺口登记与修复.md（G1/G2/G3 模式）。
5. 玩家指令手册更新：✅=veinborn 有数据实机可用 / ⚠️=框架已实现 veinborn 未配数据。
6. 隐私扫描（token/密钥/真名/隐私字段）→ git 提交（内容与 docs 可分拆；提交信息含新区代号，遵循仓库提交规范）。

**产出物**：回归报告 + 记录.md + 手册更新 + commit。
**验收标准**：pytest 零新增红；ruff 干净；页表断言与实际模块数一致；记录/手册已更新；隐私扫描过；提交完成。

**常见坑**：模块数动而页表断言没同步（编辑器 auto 页静默缺新区模块页）；提交改 JSON 没改 docs（下个新区勘察对照失真）；把「转职不重算属性」当 bug 报（=定稿设计，勿报）；回归脚本把新区任务链频繁转职当 bug（已知限制勿报，不改引擎）。

---

## 附：与 B/C 版混选对照

| 需求 | 选哪版 |
|---|---|
| 按阶段推进每一步做什么 | A 版（P0-P8 执行流） |
| 要可验收的关卡出口 | B 版（E0-E6 门禁） |
| 要直接套的 JSON/表格骨架 | C 版（基础/内容/验证三层模板） |
| 要查坑清单 | 三版都有，A/B 版坑在每节尾、C 版在验证层 |
