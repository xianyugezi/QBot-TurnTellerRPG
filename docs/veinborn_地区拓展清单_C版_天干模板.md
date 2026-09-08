# 后续地区拓展清单 · C版

> 用途：每新增一个地区（如 E 区新主线带）时必须整体走一遍的落地清单。
> 编号体系：阶段门分层——基础层（地基必做）/ 内容层（地区实体生产）/ 验证层（质量门）。每层内部用天干（甲、乙、丙、丁、戊）编号，工作项级编号记作「层·干—编号」，如【基础层·甲—01】。
> C 版特色：每个工作项都附「产出物模板骨架」，直接复制填空，产出与 A/B/C/D 区既有实例同构。
> 套用基线：以 A 区（a1-a4）+ B 区（b1-b4）真例为范例；数值/命名/装配均以 content/veinborn + docs/veinborn_* 为准绳。
> 通过凭据：每项产出物 + 验证层对应门禁全部绿灯才算该地区完成；任何一项「不适用的规模缩水」需在记录.md 写清理由。

---

## 总览

| 阶段门 | 干 | 工作项 | 通过凭据（产出物） |
|---|---|---|---|
| 基础层 | 甲 | 数值门规划 | 新区数值门表（推荐 Lv/装备档/难度斜率） |
| 基础层 | 乙 | 世界地图接缝设计 | 接缝矩阵 + 生态混居登记 |
| 基础层 | 丙 | 新区代号与 id 前缀规范 | id 登记表（图/怪/任务/NPC/行动） |
| 基础层 | 丁 | 文件落点与 manifest 影响评估 | 落点清单 + manifest/编辑器页表影响评估 |
| 内容层 | 甲 | 地图实体生产 | 图 JSON（含 respawn、Boss intro、exits） |
| 内容层 | 乙 | 怪物与专属行动 | enemy JSON + action JSON + 专属 marks 登记 |
| 内容层 | 丙 | 任务链 | quest JSON 链 + NPC 对话框 |
| 内容层 | 丁 | 营地与复战 | camp 图 + 药婆 NPC + 复战/挑战入口配置 |
| 内容层 | 戊 | 装备素材线 | 素材 items + 装备档位表（六系曲线对齐） |
| 验证层 | 甲 | JSON 校验门 | 0 红 249 黄基线不增 + 合规检查表绿色 |
| 验证层 | 乙 | 模拟器黑盒门 | 单 --file 长序列流程报告 + 数值抽查 |
| 验证层 | 丙 | 框架回归门 | pytest 基线 12 failed 零新增 / ruff / 页表同步 / 隐私扫描 |
| 验证层 | 丁 | 文档收尾门 | 记录.md / 玩家手册 / 风味文档更新确认 |

---

# 基础层（每新区必做，开工第一天全做完）

## 基础层·甲 数值门规划

目的：新区的推荐 Lv、装备档、难度斜率在写任何 JSON 之前定死，避免怪物数值拍脑袋。

### 甲—01 产出《新区数值门表》（模板）

| 字段 | 填写 | A 区真例（参照） | B 区真例（参照） |
|---|---|---|---|
| 区代号 | 如 E | A | B |
| 推荐 Lv 区间 | 如 1-14 | 1-14 | 15-21 |
| 基础怪生命区间 | 按曲线 | ridge_cub hp 263 | rift_wolf 见 enemies.json |
| 精英怪生命区间 | 按曲线 | 砾甲兽 | crystal_mane_lord hp 3596 |
| Boss 生命/复仇值 pv | 按 pv 曲线 | A主 hp 3964 / pv 300 | 砾冕 hp 4731 / pv 200 |
| 装备档位 | 第几档（新手/进阶/毕业） | 幼兽皮套 | 裂谷狼皮套 |
| 难度斜率 | 图推进每张 +% | 同 docs/veinborn_阶段一_数值模型_1-35_v2 | 同左 |
| 数值校准手段 | 蒙特卡洛/模拟器 | montecarlo 自证 | 同左 |

### 甲—02 校准口径
- 新区数值先填表、再生成敌人 JSON；生成后必须用 monster/玩家同公式模拟复算一次（参照 scripts/ 下 battle 模拟与 Monte Carlo 自证日志）。
- 装备档位与数值曲线只允许查表取值，禁止自定义单点 outlier（所有怪/装必须落在既有难度斜率带的 20% 容差内）。

---

## 基础层·乙 世界地图接缝设计

### 乙—01 生态混居规则套用（v2 定稿四条，逐条打勾）

1. 怪群不局限本区：每张图主怪 + 混居怪（前后相邻区）。
2. 下区怪提前露脸：出现在上区靠后图，刷量少、位置在图深处，给探路玩家「前方有大家伙」警示。
3. 上区怪残留：出现在下区靠前图（幼兽巢外游荡、狼群跟猎物迁徙），让玩家不必回老图刷旧素材。
4. 混居跨度 <= 1 个区段（本区图不直接出隔区怪），难度平滑。

真例：a2 断脊丘陵 = wasteland_wolf（主）+ ridge_cub（上区残留）；b1 裂谷风口 = rift_wolf（主）+ wasteland_wolf（A 区残留）。

### 乙—02 产出《接缝矩阵》模板

表格每行一条接缝，方向从左到右 = 玩家推进方向，检查「接缝两端是否满足上/下区残留」「通道是否双向」「是否把 Boss 图锁死成独木桥」。

| 接缝 | 上区末端图 | 下区首图 | 上区→下区混居怪 | 下区→上区残留怪 | 通道模式 |
|---|---|---|---|---|---|
| A→B | a4 领主高台 | b1 裂谷风口 | b1 乱入 1 种 | — | bidirectional |
| （新区） | ____ | ____ | ____ | ____ | ____ |

### 乙—03 通道设计规则
- 跨区通道分散多图，不锁 Boss 图；图与图用 exits.up/down/left/right + mode 连接。
- 新增区至少预留 1 个「营地图」位置（中段图），参照 a3/b3/c3/d3 既有营地分布。

---

## 基础层·丙 新区代号与 id 前缀规范

### 丙—01 区码分配
既有：驻地 bone_station（5 地点）、A 脊骸丘陵 a1-a4、B 蚀风裂谷 b1-b4、C 渊晶湿地 c1-c6、D 夜嚎群山 d1-d7。新增地区按字母序取下一码，如 E → e1-e4…，并在下表登记。

### 丙—02 产出《id 登记表》模板（对齐既有格式）

| 类型 | 前缀/格式 | 范例（真例） | 新区填写 |
|---|---|---|---|
| 图 | {区码}{序号}_{英文kebab} | a1_bone_field | e1_____ |
| 怪物 | 小写英文单名 | ridge_cub / wasteland_wolf | ____ |
| Boss 精英 | 与怪同风格 | wasteland_lord / crystal_mane_lord | ____ |
| 任务 | q_{区号}_{序号}_{*}_snake | q_tut0_first_blade / q_b1_gale_wolves | q_e1_____ |
| NPC | npc_{角色} | npc_old_hunter / npc_healer_apothecary | npc_____ |
| 专属行动 | {两字母前缀}_{动作} | bb_slam / al_howl_summon | __ 区前缀分配：___ |
| 素材 | 名词化小写 | vein_shard / lord_fang | ____ |

红线：不允许与既有图/怪/任务/NPC/行动 id 撞名；登记表在内容层开工前过一遍 grep 自检。

---

## 基础层·丁 文件落点与 manifest 影响评估

### 丁—01 落点总览（新地区只改这些文件）

content/veinborn/ 下：maps.json（加图）、enemies.json（加怪）、action.json（专属行动）、marks.json（专属印记，可选）、quest.json（链）、npc.json（任务 NPC/药婆）、items.json / equipment.json / forge.json（素材与装备线）、shop.json（可选）。

### 丁—02 产出《manifest 与页表影响评估》模板

| 影响对象 | 是否需要改 | 说明 |
|---|---|---|
| content/veinborn/manifest.json | 否（模块名不变） | 只是模块内实例增加；若新增模块文件则必须加模块名 |
| 编辑器页表 | 否 | 页表字段未变则零改动；若新增 boss 姿态开关等字段才评估页表同步（见验证层丙） |
| loader / validator 兼容 | 需回归确认 | 跑一遍内容校验 |
| 隐私扫描 | 需回归确认 | 新 desc/对话框文案无个人隐私字段 |

---

# 内容层（地区实体生产，每张图/怪/链都是一次套模板）

## 内容层·甲 地图实体生产

### 甲—01 图 JSON 骨架模板（直接复制填空）

```json
{
  "id": "e1_____",
  "name": "____",
  "desc": "（一句话风味 + 一句功能暗示）",
  "npcs": [],
  "monsters": [
    { "enemy": "____", "name": "____", "count": 3, "respawn_minutes": 6 }
  ],
  "exits": {
    "left":  { "to": "____", "mode": "bidirectional" },
    "right": { "to": "____", "mode": "bidirectional" }
  },
  "mechanics": []
}
```

### 甲—02 真例对照（A 区入门图 a1 骸骨草场，原样）

```json
{
  "id": "a1_bone_field",
  "name": "骸骨草场",
  "desc": "齐腰高的灰白草甸，幼兽在倒伏巨兽的肋骨间嬉戏。猎师入门之地。",
  "npcs": [],
  "monsters": [
    { "enemy": "ridge_cub", "name": "脊冢幼兽", "count": 3, "respawn_minutes": 3 }
  ],
  "exits": {
    "up":   { "to": "a2_ridge_hills", "mode": "bidirectional" },
    "down": { "to": "bone_station",  "mode": "bidirectional" }
  },
  "mechanics": []
}
```

### 甲—03 respawn_minutes 取表（真例归纳，新区照抄区间）

| 怪类型 | respawn_minutes 真例 | 新区取值 |
|---|---|---|
| 入门小怪 | 3（a1） | 3-5 |
| 普通小怪 | 4-10（a2-d2） | 按区上调 |
| 精英 | 15-25（b3/d3/d4） | 15-25 |
| Boss | 30-60（d7 夜嚎君王 60） | 30+（复战图另见基础层丁、内容层丁） |

### 甲—04 图类型检查表

- Boss 图：monsters 只放 1 只 Boss（主榜）+ 少量精英；Boss intro 用 phases[0].enter_action + broadcast 播报（真例：A主 phase1 enter_action 后 broadcast「低沉咆哮，唤来狼群助阵！」）
- 营地图：字段加 camp + camp_name，参照 a3 骨台真例：
  ```json
  "camp": { "name": "骨台", "unlock": "arrive", "safe": true },
  "camp_name": "骨台营地"
  ```
- 复战图：独立图 + 长 respawn，参照 b4 砾冕巢谷真例（gravelcrown 1 只 respawn 30）与独立挑战图 gravelcrown_hunt。

---

## 内容层·乙 怪物与专属行动

### 乙—01 三档行动数模板

| 档位 | 行动数 | 召唤限制 | 真例 |
|---|---|---|---|
| 小怪 | 1-2 行动 | 不召唤 | ridge_cub：1 行动 bb_cub_bite |
| 精英 | 2-3 行动 | 一般不召唤 | crystal_mane_lord：3 行动 |
| Boss | 3-5 行动 | 召唤 1-3 次/场 + 冷却 >= 3 | A主/砾冕：召唤行动见下表 |

### 乙—02 召唤行动硬规则（真例归纳）

| 真例 | action | trigger_limit.per_battle | cooldown |
|---|---|---|---|
| 荒原领主 | al_howl_summon | 1 | 4 |
| 渊泽龙王 | ad_roar_summon | 2 | 5 |
| 群山嚎主 | hl_call_summon | 3 | 3 |

召唤即 build：intent 用 "召唤"，power 0，携带 trigger_limit { per_battle: N }，cooldown >= 3。

### 乙—03 enemy JSON 骨架模板

```json
{
  "id": "____",
  "name": "____",
tier（精英填 "elite"，Boss 填 "boss"，小怪省略）,
  "area": "____",
  "desc": "____",
  "stats": { "hp": 0, "mp": 0, "str": 0, "con": 0, "spr": 0, "foc": 0, "agi": 0, "luk": 0 },
  "weakness": { "types": [], "elements": {} },
  "rewards": { "exp": 0, "currencies": { "coins": 0 } },
  "drops": {
    "battle": [], "special": [],
    "death": [ { "item": "____", "chance": 100, "count": 1 } ]
  },
  "phases": [],
  "special_actions": [],
  "actions": [
    { "action": "____", "weight": 100, "probability": 1 }
  ]
}
```

### 乙—04 真例对照：小怪脊冢幼兽 ridge_cub（原样节选）

```json
{
  "id": "ridge_cub",
  "name": "脊冢幼兽",
  "desc": "游荡在脉堑外围的脊冢兽幼崽。",
  "stats": { "hp": 263, "mp": 20, "str": 84, "con": 13, "spr": 10, "foc": 6, "agi": 5, "luk": 6 },
  "rewards": { "exp": 100, "currencies": { "coins": 50 } },
  "drops": { "battle": [], "special": [], "death": [ { "item": "vein_shard", "chance": 100, "count": 1 } ] },
  "phases": [],
  "special_actions": [],
  "actions": [ { "action": "bb_cub_bite", "weight": 100, "probability": 1 } ]
}
```

### 乙—05 真例对照：Boss 三姿态 + 部位破坏（砾冕 gravelcrown 高阶范式）

Boss 建议用 phases 分成 3 段（threshold 1.0 / 0.7 / 0.35 量级），每段带 actions、enter_action、broadcast；高配可加特殊部位破坏 marks + special_actions（参照砾冕的 surge_mark 困斗、tail_broken 尾锤已破拦截横扫）。骨架：

```json
"phases": [
  { "threshold": 1.0, "actions": [ { "action": "____", "weight": 40, "probability": 1 } ], "enter_action": "____", "broadcast": "{monster} ____" },
  { "threshold": 0.7, "actions": [ … ], "enter_action": "____", "broadcast": "…" },
  { "threshold": 0.35, "actions": [ … ], "enter_action": "____", "broadcast": "…" }
]
```

（若按砾冕新版三姿态写法 = 3 个独立 enemy + zone_change 接线，则按该范式成套实现。）

### 乙—06 专属行动 action JSON 骨架

```json
{
  "id": "____",
  "name": "____",
  "kind": "active",
  "power": 1.0,
  "attack_type": "打",
  "element": "____",
  "weight": 30,
  "probability": 0.6,
  "intent": "伤害",
  "cooldown": 0,
  "tags": ["物理"]
}
```

新怪用的每个专属行动先加进 action.json，再在 enemy 的 actions/phases 里引用；涉及部位破坏的新印记需同步登记 marks.json。

---

## 内容层·丙 任务链

### 丙—01 主线 q_chain unlock 模板

新区主线 = 一串 3-5 个任务，逐级 unlock_chain 串联，且链尾解锁 Boss 所在图/复战资格。骨架：

```json
{
  "id": "q_e1_00____",
  "name": "____",
  "type": "slay",
  "desc": "NPC 口吻一句话：____",
  "zone": "e1_____",
  "main": true,
  "consume": false,
  "repeatable": false,
  "unlock_chain": "q_e1_前一个任务 id 或 'q_前置区末任务'"（首任务可不写）,
  "conditions": [
    { "var": "kill_count", "op": "ge", "value": 2, "param": "____敌方怪 id____" }
  ],
  "reward": [ { "item": "____", "count": 1 }, { "exp": 0 }, { "coins": 0 } ],
  "npc": { "id": "npc_____" }
}
```

condition 三变量覆盖：level / kill_count（param 填怪 id）/ item_count（param 填物 id）。type 用 deliver / slay / collect。

### 丙—02 真例对照：q_tut0_first_blade（新手第一步，原样）

```json
{
  "id": "q_tut0_first_blade",
  "name": "猎师的见面礼",
  "type": "deliver",
  "desc": "老猎人·驼脊：新猎师总得有把趁手的家伙。来领你的第一把脊刃吧。",
  "zone": "a1_bone_field",
  "main": true,
  "consume": false,
  "repeatable": false,
  "conditions": [ { "var": "level", "op": "ge", "value": 1 } ],
  "reward": [ { "item": "ridge_blade_starter", "count": 1 }, { "exp": 30 }, { "coins": 100 } ],
  "npc": { "id": "npc_old_hunter" }
}
```

链内下一环真例（q_tut1）把 unlock_chain 指向上一环："unlock_chain": "q_tut0_first_blade"，conditions 换为 kill_count >= 2 param ridge_cub。新区的链形：区首任务解锁链 = 上一区末任务 id（对照 q_b1_gale_wolves unlock_chain q_tut4_gravel_armor）。

### 丙—03 NPC 对话框模板

quest_giver 型（真例 npc_old_hunter）：dialogues.options 用 { text, action: "quest", quests: [ { quest_id } ] } 收藏整条窗可选任务。merchant/药婆型见内容层丁。每个新区 NPC 至少 1 个 greeting、1 个发任务 option、1 个「离开」。

### 丙—04 任务链自检表

- 首任务解锁链 = 上一区链尾任务的 id；末任务解锁线索指向 Boss 图/复战图。
- 每个任务 zone 必须真实存在于 maps.json；每个条件 param（怪/物品）必须真实存在；每笔 reward item 必须存在于 items.json。
- NPC 对话框里 quests 列表收纳完整（参照 npc_old_hunter 已收纳 q_tut0 -> q_forge_intro 全链）。

---

## 内容层·丁 营地与复战

### 丁—01 营地

每新区中段图放 1 个营地 = 该图带 camp + camp_name + 1 名药婆/补给 NPC。真例：a3 骨冢洼地 camp「骨台营地」+ npc_healer_apothecary；b3/c3/d3 同构（风息台/泽心台/矿灯站）。药婆骨架：

```json
{
  "id": "npc_healer_apothecary",
  "name": "____",
  "icon": "药",
  "map": "e?_____",
  "type": "merchant",
  "visible": true,
  "dialogues": {
    "greeting": "____",
    "options": [
      { "text": "疗伤（____ 脉晶币）", "action": "heal", "cost": { "coins": 0 }, "heal": { "hp": "100%" } },
      { "text": "买点补给", "action": "shop", "shop_refs": ["station_supply"] },
      { "text": "离开" }
    ]
  }
}
```

疗伤价随区提高（A 免费主城 / B 50 / C 80 / D 120）。营地图同时保证规则：有怪默认隐藏图、营地+驿站可传送（/地图 传送规则收敛）。

### 丁—02 复战（Boss 再挑战）

- 区域 Boss 默认打死后可在 Boss 图 respawn 复战；如需「挑战副本」，沿用独立挑战图范式（gravelcrown_hunt 脉堑猎场 = 独立图 + gravelcrown 单怪 respawn 30，入场不经过主线图链）。
- 复战资格/成就触发：确认事件注册后挂解锁（巡回收口见记录.md 与框架回归门）；解锁后向玩家展示传送入口。
- 检查项：复战图 exits 应为空或单向入口，不在接缝矩阵里造成通路污染。

---

## 内容层·戊 装备素材线

### 戊—01 新区素材 items 骨架

```json
{
  "id": "____",
  "name": "____",
  "type": "material",
  "price": 100,
  "effects": [],
  "usable": false,
  "desc": "____：打造素材（__系）"
}
```

真例：vein_shard 脉晶碎片 50（通用）、wolf_pelt 荒原狼皮 60（骨脊系）、lord_fang 领主獠牙 400（王骸系·A）、wind_ridge_shell 风脊晶壳 130（脉铁系）、crystal_mane 晶鬃 260（鳞革系·精英）。每怪死亡掉落表中给 1 个本区素材；Boss 专属素材进 death 掉落。

### 戊—02 装备档位表模板（对齐六系曲线）

| 档位 | 推荐Lv | 武器 atk 区间 | 防具 dfn/hp 区间 | 源素材 | 系 | 新区对应档 |
|---|---|---|---|---|---|---|
| 新手 | Lv1 | 真例 砺脊刃 atk 18 / 幼兽皮甲 hp60 dfn10 | cub_leather_* | 骨脊入门 | ____ |
| 过渡 | Lv5+ | 长脊大剑 atk 28 / 脉行靴 | __ | ____ | ____ |
| 中段 | … | 锻造节点 atk 90/100/160/176… | … | 脉铁/骨脊 | ____ |
| 区毕业/进阶武器 | 推荐Lv 末 | 节点 atk 230/300… | … | 精英素材 | ____ |
| 顶级 | 末 | atk 360（脉铁王斩） | … | Boss 素材 | ____ |

铁律：新区装备档位全部落在六系曲线既有档位的插值/延续上，不允许新做一条偏离曲线的属性带；每件新装备在档位表中先登记、后写 equipment.json / forge.json 节点。

### 戊—03 forge 接线（模板，参照真例 node 字段）

```json
{
  "id": "node_____",
  "name": "____",
  "item": "____",
  "type": "weapon",
  "level": 2,
  "parent": "node_上一级",
  "stats": { "atk": 0 },
  "materials": [ { "item": "____", "count": 6 } ],
  "rarity": "fine",
  "final": false
}
```

新增系节点需挂入既有树根/父链并在 trees[].roots/nodes 登记；新区 Boss 素材合成的毕业武器 final 置 true。装备/材料全部落 items.json + equipment.json + forge.json 三处，缺一视为断链。

---

# 验证层（质量门，全绿才收工）

## 验证层·甲 JSON 校验门

- 跑内容校验：直接调用仓库校验脚本/validator 全量检查；基线 = 0 红 249 黄；新增 JSON 不允许制造新的红/黄计数，已有黄若被新区暴露为红则按 P1 修。
- 合规检查表（逐行勾）：

| # | 检查项 | 通过 |
|---|---|---|
| 1 | maps.monsters[].enemy 全部存在于 enemies.json | 是/否 |
| 2 | maps.exits.*.to 全部指向存在的图 id | 是/否 |
| 3 | quest[].zone 存在于 maps；npc[].map 存在于 maps | 是/否 |
| 4 | quest[].conditions[].param 引用的怪/物品存在 | 是/否 |
| 5 | quest[].unlock_chain 指向前序已存在任务 | 是/否 |
| 6 | drops/items/reward/forge.materials 引用的 item 存在于 items.json/equipment.json | 是/否 |
| 7 | enemy.actions/phases 引用的 action 存在于 action.json | 是/否 |
| 8 | 新印记 id 已登记 marks.json 且不重复 | 是/否 |
| 9 | 每张 Boss 图 respawn/复战时长符合甲—03 表 | 是/否 |
| 10 | 所有新 id 通过丙—02 前缀规范与撞名 grep | 是/否 |

## 验证层·乙 模拟器黑盒门

- 用具名模拟器单 --file 长序列跑一遍「新区全流程脚本」，清单模板如下，逐行写期望输出：

```
注册新玩家 -> 出生引导(驻地) -> 领取区首任务 -> 猎杀到链尾 -> Boss 战(含一次召唤被触发) -> 死亡惩罚(虚脱拦截) -> 营地疗伤恢复 -> 复战 Boss -> 掉落/经验核对 -> 传送门可用
```

- 数值抽查项：Boss 斩杀回合落在设定档；小怪经验/金币与档位表一致；素材掉率命中；召唤每场次数不超 trigger_limit；印记层数与冷却在报告留痕。
- 输出物：模拟报告文件（含命令、断言清单、通过/失败行），失败项回炉修 JSON 后重跑至全绿。

## 验证层·丙 框架回归门

- pytest：跑框架测试，基线 12 failed，新增内容零新增失败；出现新失败必须当场修或写明与新区无关的证据。
- ruff：对 qbot_rpg 改动面跑 ruff，无新增告警。
- 编辑器页表同步：若新内容引入新字段（如 Boss 新姿态或 camp 新开关），编辑器自动页表需同步或按既有方案登记；页表字段无变化则零改动并留痕。
- 隐私扫描：扫描全部新增 JSON/文案，确认无隐私字段入内容包；发现即删并复查。

## 验证层·丁 文档收尾门

| 文档 | 更新动作 | 完成 |
|---|---|---|
| docs 记录.md（如 m 系列记录/veinborn 进度存档） | 新区条目：区码、图/怪/任务数、数值门表摘要、当日报告 id | 是/否 |
| 玩家手册（指令清单/图鉴相关文档） | 新图/新怪/新任务可见性文案与列表登记 | 是/否 |
| 风味文档（世界总览/区域风味定稿） | 世界基调、生态混居、区域总览表补新区行 | 是/否 |
| 接缝矩阵与 id 登记表 | 回写基础层产出物 | 是/否 |
| 新技能/新机制（若涉及） | 另出细化文档并过技能轴审查 | 是/否 |

---

## 附录：新区收工十问（合并验收）

1. 数值门表定稿且全怪落在曲线容差内？
2. 接缝矩阵无独木桥、混居跨度 <= 1 区？
3. 图/怪/任务/NPC/行动 id 前缀合规且无撞名？
4. manifest 与编辑器页表影响评估已留痕？
5. 图 JSON 全部含 respawn 与 exits；营地图带 camp/camp_name；Boss intro 有广播？
6. 小怪/精英/Boss 行动数与召唤次数/冷却符合三档模板？
7. 任务链 unlock_chain 连续、条件与奖励引用全部真实存在？
8. 营地药婆 NPC 与复战入口可用（模拟器验证过）？
9. 素材-装备-锻造三处接线完整且档位对齐六系曲线？
10. 四道验证门全绿（JSON 校验/模拟器/回归/文档）？

以上十问全部「是」，新区 C 版清单即闭环。
