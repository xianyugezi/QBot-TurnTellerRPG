# 细化_3h_settings通用设置（settings.json 字段级 schema · 六大分段 · 排行榜 · 事件推送 · 数据包保护 · 校验与接缝 · 验收测试）

> 版本：v1.0 · 类型：实现层细化契约（大厂模式：字段 schema / 功能开关默认关 / 推送频道 / 只读保护与锁定签名 / 校验二分法 / 跨契约接缝 / 验收测试）
> 追溯依据（**严格引用策划案，引用到行号 Lxx，附原文摘录**）：
> - 《RPG回合制框架设计文档.md》v2.19（2026-08-16）→ 简称【框架】（**主依据**，全篇行号引用）
> - 《时间天气系统设计定稿.md》v1.0 → 简称【时间天气】（time_cycle 段字段级依据）
> - 《炼金系统设计定稿.md》→ 简称【炼金】（job_tier_map 字段依据）
> - 《指令分隔符统一规范.md》→ 简称【分隔】（command_mode/require_at/whitelist/aliases 字段依据）
> - 《开发规则文档.md》v1.0 → 简称【规则】（校验二分法/QQ 频率约束/只建议不限制）
> - 覆盖审计《覆盖审计_A_框架基础.md》P1-3（settings 通用设置段整体无细化宿主 → 本契约收口）
> - 实现层规划《规划_路3_框架指令数据.md》A5/C3/C5 与《实现层规划文档.md》L3327/L3374（settings 行定义与模块 mode 三态）
> 范围：内容包 `settings.json` **通用设置**的实现层细化——① 文件级契约与六大分段（世界/时间/战斗/经济/消息/功能开关）字段级 schema；
> ② 排行榜段（功能开关默认关 + 显示规则）；③ 事件推送段（新玩家/大事件/升级/稀有掉落推送，默认关 + 频道配置）；
> ④ 数据包保护段（只读保护 + 锁定签名，编辑期间拦截与恢复）；⑤ 模块 mode 三态（alchemy/fishing）与指令模式组（command 段）；
> ⑥ settings 模块校验规则清单（红拦/黄提示，承接 3e §5.2 校验器）；⑦ 与 3e/3e2/6c/2a4x/2c5a/4e/3d/5a/5b 接缝清单；⑧ 验收测试用例。
> 不含：PVP 流程编排（见 4e）、时间/天气引擎内部（见 2a4a/2a4b/2a4c）、消息前缀模板语义（见 3d）、炼金/钓鱼系统语义（见 2c 系列）、
> 编辑器 UI 交互细节（见 5a；本契约只登记通用设置页卡片清单供 5a 元数据渲染）。
> 变更纪律：定稿未明处一律标注【补白】/【细化补充】；任何偏离写入 §0.3 ADR 并注明理由+影响用例，禁止静默改语义。

---

## 文档总览（计数）

| 维度 | 计数 | 分布 |
|---|---|---|
| 分段 | **6 大段** | 世界（3 段项）/ 时间（1）/ 战斗（2）/ 经济（2）/ 消息（2）/ 功能开关（5） |
| 段项 schema | **15 项** | level_cap / death_penalty / job_tier_map / time_cycle / pvp / post_battle_recovery / currencies / sell_ratio / message_prefix / event_push / leaderboard / data_protection / modules / command / hot_reload |
| 流程 | **3 个** | F1 设置装配与默认值合并 / F2 事件推送管线（触发→限频→频道投递）/ F3 数据包保护生命周期（锁定→拦截→发布解除） |
| 校验规则 | **12 条** | V1~V8 红拦（settings 专属 6 条 + 复用二分法 2 条）+ V9~V12 黄提示 |
| 接缝 | **10 处** | 3e / 3e2 / 6c / 2a4a·2a4c / 2c4d·2c4f / 2c5a / 4e / 3d / 5a / 5b |
| 验收用例 | **18 例** | TC-01~04 加载与默认值 + TC-05~09 功能开关 + TC-10~12 事件推送 + TC-13~16 数据包保护 + TC-17~18 校验与旧局旧配置 |

---

## 〇、契约总则

### 0.1 术语表

| 术语 | 定义 | 依据 |
|---|---|---|
| settings.json | 内容包【通用设置】文件："货币定义/PVP/死亡惩罚/等级上限/出售比率/排行榜/事件推送/数据包保护/alchemy/message_prefix/time_cycle 段" | 【框架】L374 |
| 六大分段 | 本契约对 settings 全部段项的**实现层分组**：世界/时间/战斗/经济/消息/功能开关——分组仅为文档组织与编辑器卡片归组，**不改变 JSON 顶层键名**（顶层键直接平铺，见 §1.2） | 【细化补充】 |
| 功能开关默认关 | 排行榜/事件推送/数据包保护等**面向玩家的展示与推送类功能默认关闭**，作者显式开启才生效——防刷屏、防半成品运行的统一口径 | 【框架】L1101「事件推送…默认关，防刷屏」；【覆盖审计_A】P1-3 |
| mode 三态 | 模块启用三态 `full / simple / off`：off = 模块指令提示未启用、相关条件键失效；full/simple = 完整/简化两档（各系统细化承接简化档语义） | 【规划_路3】A5「模块 mode 三态解析（alchemy / fishing / time_cycle 等，off 时模块指令提示未启用、相关条件键失效）」；【时间天气】L101 |
| 锁定签名 | 数据包保护开启时，对**当前校验通过的发布配置快照**计算的内容哈希（sha256）：标记「可发布版本」与「半成品编辑版本」的边界凭证 | 【补白】（§10） |
| 事件推送 | 系统事件（升级/稀有掉落/新玩家/大事件公告）的主动消息投递，逐事件类型独立开关 + 频道配置，走统一发送出口与限频 | 【框架】L1101 / L1125-1126 / L1168 |
| 公告通道 | 系统级消息通道（推送到全部群 + 私聊；磁盘/内存预警等系统事件复用） | 【框架】L1125 / L1168 |

### 0.2 一句话契约

> settings.json = 内容包的**通用设置唯一宿主**【框架】L374：六大分段 15 段项全字段可选、缺省合并框架默认值（F1）；
> 展示/推送类功能（排行榜、事件推送、数据包保护）**默认关**，显式开启后按各自显示规则与频道配置工作【框架】L1100-1101/L1191-1197；
> 数据包保护开启 = 内容包只读 + 玩家指令拦截 + 锁定签名标记半成品，关闭/保存发布后原子放行（F3）；
> 本文件经 3e loader 走完整校验（12 条红黄规则）、随 3e2 热重载原子生效、对局持旧配置快照；
> 各段按接缝契约被 4e（pvp）/2a4x（time_cycle）/3d（message_prefix）/2c5a（job_tier_map）/6c（季节键）/5b（公告通道）等消费。

### 0.3 决策记录（ADR，均为对定稿空白的显式收敛，标注【补白】）

| 编号 | 决策 | 理由 | 影响用例 |
|---|---|---|---|
| D-01 | settings.json 为**常驻模块**：不依赖 manifest.modules 声明即总是被 loader 读取（manifest 声明它仅为显式登记，缺失声明不报错）；全段字段可选，缺省合并框架默认值 | 通用设置是框架兜底默认值来源；若按 3e「声明才加载」处理，空 modules 包将无任何默认设置可依【补白】 | TC-01/TC-02 |
| D-02 | 六大分段仅为文档组织，JSON 顶层键平铺（`level_cap`/`pvp`/`time_cycle`/`currencies`/`leaderboard`…直接挂在根对象）；不引入 `world:`/`battle:` 等包装层 | 定稿 L374 段清单即平铺形态；增加包装层会破坏编辑器元数据表与 CSV 导入路径的键空间（【框架】L447-474 字段元数据唯一源）【补白】 | TC-03 |
| D-03 | 面向玩家的展示/推送功能（leaderboard / event_push / data_protection）**默认关**；模块开关（alchemy/fishing mode）默认 full | 定稿仅对事件推送明示默认关（L1101）；排行榜无明示，按同源防刷屏精神统一默认关；data_protection 语义是「常态关闭、大改版临时开启」，默认关符合其定位【补白】 | TC-05~TC-10/TC-13 |
| D-04 | 事件推送**逐事件类型独立开关 + 独立频道**（level_up/rare_drop/player_join/announcement），全走统一发送出口并受单群每分钟 ≤20 条限频；推送消息不占战斗结算消息配额 | 定稿 L1101 仅给两个类型与「默认关」，L1125/L1128/L1168 给出公告/欢迎/预警三类系统投递且复用公告通道 → 收敛为事件类型注册表；【规则】L499-501/L523 频率约束与 3e2 D-06 同口径【补白】 | TC-10~TC-12 |
| D-05 | 排行榜为**只读查询 + 快照缓存**：按 `refresh_sec`（默认 86400）缓存榜单快照，窗口内重复查询直接返回缓存；不产生任何主动推送 | 定稿 L1100 仅定「榜单类型 + 刷新秒数」；缓存设计对齐「零通知/懒计算」总纲（时间天气定稿 L61 同哲学）与防刷屏约束【补白】 | TC-07/TC-08 |
| D-06 | 数据包保护开启期间：① 内容包**只读锁**（编辑器禁止保存该包）；② 玩家游玩指令全部拦截返回固定提示；③ 生成**锁定签名**标记半成品；④ 热重载检测到变更仅进编辑器预览**不发布**；关闭保护 = 原子发布（换新签名并解除拦截） | 定稿 L1191-1197 只给「编辑期间拦截指令」；只读/签名/发布边界是「避免玩家用半成品数据游玩」的完整闭环（L1196）【补白】 | TC-13~TC-16 |

---

## 一、settings.json 文件级契约与六大分段总览

### 1.1 文件定位

- settings.json 是内容包通用设置文件，承载"货币定义/PVP/死亡惩罚/等级上限/出售比率/排行榜/事件推送/数据包保护/alchemy/message_prefix/time_cycle 段"【框架】L374。
- **常驻加载**（D-01）：不依赖 manifest.modules 声明；文件缺失 = 全段使用框架默认值（空包可跑，3e §1.2「空 modules 合法」兼容）。
- 结构错误（非 JSON 对象/数组类型错）→ 按 3e 红拦第 5 类结构错误整包阻断；**绝无半套设置运行**（3e 1.4）。
- 字段引用（如出售比率 overrides 引用 items.json ID、排行榜 currency_id 引用本文件 currencies）→ 走 3e 校验器引用存在性检查（红拦第 4 类）。
- 无独立货币/世界/时间模块文件：time_cycle 等段落点即 settings.json，manifest modules **不需要**新增模块名【时间天气】L126。

### 1.2 六大分段总览表（顶层键 = 段项，字段级 schema 见 §二~§七）

| 分段 | 段项（顶层键） | 一句话语义 | 消费契约 | 依据 |
|---|---|---|---|---|
| 世界 | `level_cap` | 等级上限/满级经验去向 | 3b/4f RUL-11 | 【框架】L294-296 |
| 世界 | `death_penalty` | 死亡惩罚（掉货币/经验/物品）+ 虚弱时长 | 2a1b/4f 复活接点 | 【框架】L282-292 |
| 世界 | `job_tier_map` | 称号→配方等级区间（7 档） | 2c5a LVL-06/2c2a N-05/2c4d | 【炼金】L61 |
| 时间 | `time_cycle` | 季节/时段/天气三周期引擎全局设置（唯一） | 2a4a/2a4b/2a4c/6c 季节键 | 【时间天气】L97-124 |
| 战斗 | `pvp` | 玩家决斗开关与全部参数（9 字段） | 4e CFG-01~08 | 【框架】L357-362/L374 |
| 战斗 | `post_battle_recovery` | 战后恢复（默认关） | 1g 战斗结算链 | 【框架】L298-300 |
| 经济 | `currencies` | 货币列表（默认金币+钻石） | 4b/4d/5c 数值经济 | 【框架】L1096-1097 |
| 经济 | `sell_ratio` | 通用出售比率（默认 30% 买价）+ 单条覆盖 | 4b 出售管线 | 【框架】L1098-1099 |
| 消息 | `message_prefix` | 消息前缀 7 字段 | 3d 全量消费 | 【框架】L1104-1109；3d |
| 消息 | `event_push` | 事件推送开关 + 频道配置 | 5b G7 公告通道 | 【框架】L1101/L1125-1126/L1168 |
| 功能开关 | `leaderboard` | 排行榜（默认关）+ 显示规则 | 本契约 §8/4f 展示入口 | 【框架】L1100 |
| 功能开关 | `data_protection` | 数据包保护（默认关） | 3e2 热重载/5a 编辑器 | 【框架】L1191-1197 |
| 功能开关 | `modules` | alchemy/fishing mode 三态 | 3c 路由/2c4d/2c1x | 【规划_路3】A5；【框架】L400 |
| 功能开关 | `command` | 指令模式三态/require_at/白名单/别名 | 3c/4f/【分隔】§6.1/6.5/6.6/6.7 | 【规划_路3】C3/C5 |
| 功能开关 | `hot_reload` | 热重载轮询间隔等运行参数 | 3e2 TRG-1/D-01 | 3e2 D-01 |

---

## 二、世界段 schema（level_cap / death_penalty / job_tier_map）

### 2.1 `level_cap` 等级上限

依据：【框架】L294「内容包配置【等级上限】（如 45 级）；满级后经验不再增长（或经验转货币，可选）」/ L296-297「升级时 HP/MP 回满」。

```jsonc
"level_cap": {
  "value": 45,          // int ≥1，默认 1（不配=仅 1 级，作者必配）；满级后经验不再增长
  "exp_convert": false  // bool，默认 false；true = 满级后经验按兑换比率转货币（比率见 sell_ratio 同段或 5c 数值经济总表）
}
```

- 消费：升级结算链（3b §六/4f RUL-11）读取 `value`；**升级 HP/MP 回满为固定行为，不可配**（作者无法关闭 JRPG 惯例，L297）。
- 校验：value 非正整数 → 红拦 V1；value > 9999 → 黄提示 V10（数值范围）。

### 2.2 `death_penalty` 死亡惩罚

依据：【框架】L282-292——默认【无惩罚】复活回最近安全区 + 虚弱；虚弱时间默认 1 分钟；可配掉货币（比例 + 指定币种）/掉经验/掉物品（随机）；绑定物品免疫掉落；复活点=地图配置（本文件不承载复活点）。

```jsonc
"death_penalty": {
  "mode": "none",            // enum: none（默认）| currency | exp | items | mixed（多选组合时用 mixed）
  "weak_time_sec": 60,       // int ≥0，默认 60；虚弱期间无法进入非安全区地图（防立刻送死）
  "currency_loss": {         // mode 含 currency 时生效
    "ratio": 0.05,           // number 0~1，默认 0.05（黄提示阈值：>0.3 提示）
    "currencies": ["gold"]   // string[]，引用本文件 currencies.id；空数组 = 全部货币按比例掉
  },
  "exp_loss": { "ratio": 0.1 },   // mode 含 exp 时生效；number 0~1，默认 0.1
  "item_loss": { "count": 1 }     // mode 含 items 时生效；int ≥0，默认 1（随机选背包物品；绑定物品免疫，L290）
}
```

- 复活回最近安全区 = 固定行为（L291 地图配置安全区/复活点，新手村默认），本文件不设复活点字段。
- 校验：mode 枚举非法 → 红拦 V1；ratio 超出 0~1 → 红拦 V5（范围外数值，负数走 3e 红拦第 2 类）；ratio > 0.3 → 黄提示 V9；currencies 引用不存在 → 红拦 V2（引用检查）。

### 2.3 `job_tier_map` 职业等级区间

依据：【炼金】L61「settings.json `job_tier_map`：称号→配方等级区间（见习 1-5/正式 6-10/精通 11-20/专家 21-30/大师 31-40/宗师 41-50/王 51+）」；
2c5a LVL-06「job_tier_map：主落点 settings.json…proficiency.json 可选覆盖、默认继承 settings」。

```jsonc
"job_tier_map": {
  "见习": [1, 5], "正式": [6, 10], "精通": [11, 20],
  "专家": [21, 30], "大师": [31, 40], "宗师": [41, 50], "王": [51, 999]
}
```

- 键 = 称号名（7 档，proficiency.json tier_names 可改名 → 区间键与 tier_names 一一对应，2c5a LVL-05/06）。
- 语义：配方 level 落在当前称号区间才可调合/合成（2c5a LVL-06 / 2c2a N-05「可锻造节点等级上限 = 职业等级」联动）。
- 缺省 = 上表默认七档；proficiency.json 提供 `job_tier_map` 同键覆盖（默认值="settings"，见 2c5a LVL-06）。
- 校验：值必须为 `[min,max]` 二元 int 数组且 min≤max、档位区间单调衔接 → 否则红拦 V1/V5（区间错乱属结构错误）。

---

## 三、时间段 schema（time_cycle）

### 3.1 字段级 schema（全局唯一，三周期同一锚点懒计算）

依据：【时间天气】§二 L97-124（settings.json time_cycle 段）——逐字段引录。

```jsonc
"time_cycle": {
  "enabled": true,                  // bool，默认 true；false 时 /时间 /天气 提示未启用、条件键 [季节]/[时段]/[天气] 失效
  "season":  { "season_days": 7 },  // int ≥1，默认 7；季节周期长（天）
  "period":  { "period_minutes": 60 }, // int ≥30，默认 60；时段周期长（分钟）
  "weather": {
    "weather_minutes": 60,          // int ≥30，默认 60；天气节拍（分钟）
    "default_pool": [               // 非空、键唯一；缺省 = 框架内置池（晴/多云/雨/雷雨/雾）
      {"key": "clear", "name": "晴", "emoji": "☀️"}
    ]
  },
  "broadcast": {
    "enabled": false,               // 变化广播总开关，默认关（不主动播报，玩家 /时间 /天气 自查）
    "mode": "lazy",                 // enum: lazy（默认）| timer（预留）
    "template": "{emoji} {name}"    // 播报文案模板，占位符 {type} {name} {emoji} {map}
  },
  "combat": {                       // 战斗天气修正（可选，默认关）
    "weather_mult": { "enabled": false, "mults": {"rain": 0.95, "storm": 1.1, "fog": 0.9} }
  }
}
```

- 周期语义（季节 4 值顺序循环/时段 5 值顺序循环/天气取生效池等概率抽签）与确定性计算见 2a4a；地图级 `weather_pool` 覆盖见 maps.json（缺省用默认池）【时间天气】L131-139。
- 全部**全局唯一**：世界只有一个季节/时段/天气节拍【时间天气】L127（对齐【框架】L239-249 全局世界）；时区固定 UTC+8【框架】L203。
- 校验：season_days < 1 / period_minutes·weather_minutes < 30 → 红拦 V5；default_pool 空数组或键重复 → 红拦 V1；weather 键与 map 引用不一致 → 黄提示 V11。

### 3.2 消费方与开关语义

- 2a4a/2a4b：三周期引擎读本段计算；广播默认关（懒广播，2a4c「懒广播（默认关）」行）。
- 6c 季节技能组：`enabled=false` → `[季节:X]` 条件键失效（【时间天气】L101），6c 季节组全部技能按通用组处理、`on_season_change` 不触发（⑥ 接缝 §12-4）。
- 战斗天气修正：战斗开局按当时配置锁定（旧局旧配置，见 §12-2）。

---

## 四、战斗段 schema（pvp / post_battle_recovery）

### 4.1 `pvp` 玩家决斗（9 字段 = 4e CFG-01~08 + 模式二选一）

依据：【框架】L357-362（PVP 卡片：L358 开关 / L359 模式二选一 / L360 等级门槛 / L361 战斗掉落 无/货币/物品 掉落表可配 / L362 击杀惩罚 无/回城 / L363 不搞赌钱）；4e §4.3「CFG-01 ~ CFG-08，settings.json PVP 卡片扩展」。

```jsonc
"pvp": {
  "enabled": false,          // bool，默认 false；false = 拒绝发起决斗（4e CMD-A1 校验②）
  "mode": "turn",            // enum: turn（回合制）| realtime（非回合制），编辑器 PVP 卡片二选一
  "level_gate": 10,          // int ≥1，默认 10；发起/接受双向校验（4e FR-R3）
  "invite_timeout_sec": 60,  // int ≥10，默认 60；邀请等待超时（4e ST-T1/CFG-03）
  "turn_timeout_sec": 60,    // int ≥10，默认 60；回合制离线方每回合自动防御等待（4e ST-T2/CFG-04）
  "zombie_days": 30,         // int ≥1，默认 30；僵尸战斗回收（4e ST-T3/CFG-05，【框架】L1167）
  "daily_reward_limit": 5,   // int ≥0，默认 5；每日胜利奖励上限（4e FR-R1/CFG-06）；0 = 无上限（黄提示）
  "exp_on_win": false,       // bool，默认 false；胜利不给经验（防等级速刷，4e CFG-07）
  "pair_daily_limit": 3      // int ≥0，默认 3；同一对玩家每日对局上限（4e FR-R2/CFG-08）；0 = 无上限（黄提示）
}
```

- PVP 卡片中「战斗掉落（无/货币/物品，掉落表可配）」与「击杀惩罚（无/回城）」为 **PVP 卡片两级配置**（编辑卡片/地图侧）。掉落引用 loot.json、货币引用本文件 currencies（4e SET-R02），惩罚=回城引用地图复活点——本文件只承载上表运行参数；卡片两级配置字段随 5a 编辑器 PVP 卡片细化登记，不重复造字段（4e §4.3 已收口）。
- 校验：enabled 非 bool 等类型错 → 红拦；mode 非法枚举 → 红拦 V1；zombie_days < 30 → 黄提示 V9（定稿 L1167 固定 30 天，改小提示确认）；daily_reward_limit/pair_daily_limit 负数 → 红拦第 2 类。

### 4.2 `post_battle_recovery` 战后恢复（默认关）

依据：【框架】L298-300「【战后恢复（默认关闭）】：胜利后回复 HP/MP 比例 + 安全区回复；默认关闭（花钱治疗本身是资源循环的一部分）；用户可开启：战后治疗比例 / 安全区停留回复」。

```jsonc
"post_battle_recovery": {
  "enabled": false,      // bool，默认 false；true = 开启战后恢复
  "heal_ratio": 0.2,     // number 0~1，默认 0.2；胜利后回复 HP/MP 比例
  "safe_zone_heal": 0.1  // number 0~1，默认 0.1；安全区停留回复比例（每次指令触发判定时的回复量）
}
```

- 消费：1g 战斗结算链（胜利方结算后按比例回复）；安全区回复挂 2a1b 安全区判定。
- 校验：ratio 越界 → 红拦 V5；ratio > 0.5 → 黄提示 V9（回复过高会击穿「花钱治疗=资源循环」L299 设计）。

---

## 五、经济段 schema（currencies / sell_ratio）

### 5.1 `currencies` 货币定义

依据：【框架】L1096-1097「货币列表：名称/图标/持有上限（默认不设）/用途备注；默认模板：金币 + 钻石，可改名/增删」。

```jsonc
"currencies": [
  { "id": "gold",   "name": "金币", "icon": "🪙", "cap": 0,        "note": "通用货币" },
  { "id": "diamond","name": "钻石", "icon": "💎", "cap": 99999,    "note": "稀有货币" }
]
```

- `id`：机器键（snake_case，全局唯一，被 sell_ratio / pvp 掉落 / 4b 背包 / 4d 图鉴 / 商店等引用）；`name` 显示名；`icon` emoji；`cap` 持有上限，**0 = 不设上限**（默认不设，L1096）；`note` 用途备注（编辑卡片展示）。
- 默认模板 = 金币 + 钻石两行，可改名/增删（L1097）。
- 校验：id 重复/非法字符 → 红拦 V1/V2；name 为空 → 红拦 V1；cap 负数 → 红拦第 2 类。

### 5.2 `sell_ratio` 出售比率

依据：【框架】L1098-1099「通用出售比率（默认 30% 买价）；可单条覆盖（如金珠材料可单独配『卖 10 万金币』，作为卖钱专用材料）」。

```jsonc
"sell_ratio": {
  "default": 0.3,        // number 0~1，默认 0.3；通用出售比率（× 买价）
  "overrides": {         // 单条覆盖：items.json id → 比率（0~1）或固定价 {"fixed": 100000}
    "gold_pearl_material": 0.9,
    "legacy_sword": {"fixed": 100000}
  }
}
```

- `overrides` 键 = items.json 物品 id（引用检查，红拦 V2）；值 = 比率 number 或 `{"fixed": N}` 固定卖价（卖钱专用材料通道，L1099）。
- 校验：default 越界 → 红拦 V5；override 物品引用不存在 → 红拦 V2（3e 引用类）。

---

## 六、消息段 schema（message_prefix / event_push）

### 6.1 `message_prefix` 消息前缀（7 字段，3d 全量消费）

依据：【框架】L1104-1109（enabled 默认 true / format 默认 `Lv[等级].[玩家名] -[称号]-` / 占位符 / 显示位置首行 / 只建议不限制）；3d §1.2（7 字段 full schema 已细化，**本契约不重复造字段，仅登记落点**）：

```jsonc
"message_prefix": {
  "enabled": true, "format": "Lv[等级].[玩家名] -[称号]-",
  "show_on_system": true, "per_channel": {},
  "hide_when_empty": false, "empty_title_text": "", "prefix_max_len": 40
}
```

- 字段级 schema / 占位符 / 显示规则五条 / 称号三态联动 → **全部见 3d**（3d TPL-* / §3.3），本文件仅登记该段归属 settings.json（3d 已在此消费，此处不重复）。
- 校验：红黄规则按 3d §九（【实现层规划】L3327「前缀段红黄按【前缀】§九」）→ 本契约 V9~V12 不重复覆盖。

### 6.2 `event_push` 事件推送（默认关 + 频道配置）——详细契约见 §9

```jsonc
"event_push": {
  "enabled": false,          // 总开关，默认 false（防刷屏）；false = 全部事件类型不推送
  "events": {
    "level_up":       { "enabled": false, "channels": ["all_groups"] },
    "rare_drop":      { "enabled": false, "channels": ["all_groups"] },
    "player_join":    { "enabled": false, "channels": ["all_groups"], "template": "欢迎 {name} 加入冒险！" },
    "announcement":   { "enabled": false, "channels": ["all_groups", "dm"] }
  }
}
```

- `channels` 枚举：`"all_groups"`（全部群）/ `"dm"`（私聊）/ `[群号...]`（指定群列表）；`announcement` 同时投递私聊 = 复用公告通道（L1125「一键推送到全部群+私聊」/ L1168「私聊推送机主（复用公告通道）」）。
- 每个事件类型：`enabled` 独立开关（总开关关 = 全不推，逐类型开 = 仅该类型推）；`template` 可配文案（占位符按类型注册，见 §9.3）。
- 事件类型为**开放注册表**：定稿两个（level_up / rare_drop，L1101）+ 补白两个（player_join 新人入群欢迎语 L1126 / announcement 大事件公告 L1125）；未来新事件类型按同 schema 扩展登记，无需改引擎（3e 校验器对未登记事件键 → 黄提示 V11）。

---

## 七、功能开关段 schema（leaderboard / data_protection / modules / command / hot_reload）

### 7.1 `leaderboard` 排行榜（默认关）——详细契约见 §8

```jsonc
"leaderboard": {
  "enabled": false,           // 默认 false（功能开关默认关，D-03）
  "types": ["level", "currency", "kills"],  // 榜单类型，可多选（等级/货币/击杀数，L1100）
  "refresh_sec": 86400,       // int ≥60，默认 86400（L1100「刷新秒数（默认 86400）」）
  "top_n": 10,                // 每榜展示位次，int 1~50，默认 10（若含 0 → 红拦 V1；>50 → 黄提示 V9）
  "currency_id": "gold"       // currency 榜排序货币（引用 currencies.id；缺省 = 第一个货币）
}
```

### 7.2 `data_protection` 数据包保护（默认关）——详细契约见 §10

```jsonc
"data_protection": {
  "enabled": false,           // 默认 false；true = 编辑期间拦截玩家指令（L1193-1194）
  "lock_signature": "",       // str（自动维护，作者不手填）：保护开启时对发布配置快照的 sha256；编辑器显示只读
  "player_notice": "作者更新中，请稍后再试...",  // 拦截提示文案（L1194）可改
  "editor_readonly": true     // bool，默认 true；true = 保护期间编辑器该包只读不可保存（模板只读精神 L1030-1033）
}
```

### 7.3 `modules` 模块 mode 三态

依据：【规划_路3】A5「模块 mode 三态解析（alchemy / fishing / time_cycle 等，off 时模块指令提示未启用、相关条件键失效）」；【框架】L400（fishing 段含 mode 三态）+ L374（settings.json 含 alchemy 段）。

```jsonc
"modules": {
  "alchemy": "full",   // enum: full | simple | off，默认 full；off = 炼金/合成/深度炼金指令提示未启用（2c4d 指令表整体不路由）
  "fishing": "full"    // enum: full | simple | off，默认 full；off = 钓鱼指令未启用、鱼种数据不参与刷新
}
```

- 三态语义：`off` = 模块指令提示未启用、相关条件键失效（对齐时间天气 L101 的 enabled=false 语义）；`full` = 完整机制；`simple` = 简化档（各系统细化承接简化内容：炼金 simple 见 2c4a 三层漏斗简化档、钓鱼 simple 见 2c1b mode 三态）。
- time_cycle 的开关语义由 `time_cycle.enabled` 承载（§3），不重复登记于 modules（防重复造开关，与 6c 同哲学）。
- 校验：mode 枚举非法 → 红拦 V1；off 模块仍在 manifest.modules 声明 → 黄提示 V12（提示作者该模块已关闭但文件仍在声明）。

### 7.4 `command` 指令模式组

依据：【分隔】§6.1（前缀三态）/§6.2（@机器人 开关）/§6.5（防误触）/§6.7（别名）；【规划_路3】C3/C5（字段级要点已列）。

```jsonc
"command": {
  "command_mode": "global_shortcut",  // enum: prefix_only | combat_shortcut | global_shortcut，默认 global_shortcut（全局免前缀）
  "require_at": false,                // bool，默认 false；true = 快捷名需 @机器人 触发
  "command_shortcut_whitelist": ["攻击","防御","逃跑","道具","使用","进入","锁定怪物","采集","合成","炼金","锻造","强化","调合","镶嵌","拆珠","状态","背包","怪物","地图"],
  "command_aliases": {},              // {别名: 原指令}，如 {"炼丹":"炼金"}；keep_original 默认 true
  "keep_original": true               // bool，默认 true；false = 原指令隐藏禁用（发旧名提示新名）
}
```

- 防误触三件套（非指令消息不响应/随机文本忽略/GM 指令永不快捷）与别名冲突检测、上限 50 条 → 3c/4f 契约化执行（【规划_路3】C3/C5），本文件只登记字段归属。
- 校验：command_mode 枚举非法 → 红拦 V1；whitelist 含 GM 指令名 → 黄提示 V12（GM 指令强制 / 前缀，白名单内无效）。

### 7.5 `hot_reload` 热重载运行参数

依据：3e2 D-01「热重载轮询间隔固定默认 3 秒…轮询为可配项（`hot_reload.poll_interval_ms`，编辑器通用设置段），默认 3000」。

```jsonc
"hot_reload": {
  "poll_interval_ms": 3000   // int ≥1000，默认 3000；自动检测轮询间隔
}
```

- 校验：<1000 → 红拦 V5（不可低于 1 秒，防轮询风暴）；>60000 → 黄提示 V9。

---

## 八、排行榜契约（功能开关默认关 + 显示规则）

### 8.1 开关与默认值

- `leaderboard.enabled` 默认 false（D-03）。关闭时：`/排行榜` 指令 → 提示「本服未开启排行榜」，不产生任何计算与存储开销（懒计算，与 D-05 缓存同哲学）。
- 依据：【框架】L1100「榜单类型（等级/货币/击杀数，可多选）+ 刷新秒数（默认 86400）」；开启后按 §8.2~8.4 运行。

### 8.2 榜单类型与数据源（L1100）

| 榜单类型 | 排序键 | 数据源 | 备注 |
|---|---|---|---|
| `level` | 玩家等级（降序），同级按经验值 | 玩家存档等级/经验（3b 三层属性，4a 落盘） | 同经验并列位次相同 |
| `currency` | 指定货币持有量（`currency_id`，降序） | 玩家存档货币段（4b） | 缺省取第一货币；含 0 持有玩家不入榜 |
| `kills` | 累计击杀（降序） | `longline_counters.kill_count`【框架】L229 | 只增不减的长线计数 |

- 多选 = 多榜并存，`/排行榜` 缺省展示第一类型，`/排行榜 货币` 等参数切换（4f 展示入口增补，本契约登记指令面契约，4f 落实现）。

### 8.3 显示规则（只读 + 快照缓存，D-05）

- **只读查询**：榜单不产生任何主动推送；`/排行榜` 为读操作，不触发消息合并/不占战斗结算配额。
- **快照缓存**：榜单按 `refresh_sec`（默认 86400 = 每日刷新）缓存快照；窗口内重复查询直接返回缓存（防重算、防刷屏）；首次查询或缓存过期时**异步重建**（>50ms 走 asyncio.to_thread，【规则】L106），期间返回旧快照（有则返回，无则「榜单生成中，请稍后再试」）。
- **展示格式**：`🏆 等级榜（刷新于 HH:MM）\n1. [玩家名] Lv.45\n2. ...`；位次取 `top_n`（默认 10）；显示名走消息前缀/称号显示层（3d）；私聊与群聊同榜（全局世界，L239-249）。
- **隐私**：玩家查询他人榜单不暴露 QQ 号明文（显示名），对齐运营页 CSV 脱敏精神（L1129）。

### 8.4 边界

- 封禁玩家不入榜（5b 封禁名单联动）；数据包保护期间榜单不刷新（见 §10.3）。
- 热重载：榜单快照带 config_ref（旧快照随旧配置，切换内容包后按新包配置重建）→ 旧局旧配置哲学（§12-2）。

---

## 九、事件推送契约（默认关 + 频道配置 + 推送管线）

### 9.1 事件类型注册表（四个类型，两个定稿 + 两个补白）

| 类型键 | 触发点 | 默认 | 依据 |
|---|---|---|---|
| `level_up` | 玩家升级成功（升级结算链末尾） | 关 | 【框架】L1101「升级推送」 |
| `rare_drop` | 掉落稀有度 ≥ 金色/觉醒标记物（4b 掉落入账判定点；稀有度标记见 L1087-1090） | 关 | 【框架】L1101「稀有掉落推送」 |
| `player_join` | 新玩家完成注册（/注册 成功 @ 所在群）/ 新人入群（群成员增加事件） | 关 | 【框架】L1126「新人入群自动推送欢迎语」 |
| `announcement` | CM/机主发布公告（5b G7 `/广播`）、活动开启/结束、系统预警 | 关 | 【框架】L1125/L1128/L1168 |

- **默认关**（L1101「默认关，防刷屏」+ D-03）：作者逐类型开启；三个独立开关层级（总开关 → 类型开关 → 频道），全部通过才投递。

### 9.2 频道配置

- `channels`：`"all_groups"` / `"dm"` / 指定群号列表（6.2）。
- 频道语义：`all_groups` = 玩家所在全部群（升级/稀有掉落推送到该玩家活跃群 + @玩家或指名）；`dm` = 私聊投递；公告类（announcement）默认同时投群+私聊（复用公告通道 L1125/L1168）。
- **限频硬约束**：全部事件推送走统一发送出口，单群每分钟 ≤20 条（【规则】L499-501/L523，3e2 D-06 同口径）；推送消息不计入战斗结算消息配额；同事件（升级/掉落）多次触发合并为一条（同回合多掉落合并为「获得 2 件稀有物品」）。
- 推送消息走消息前缀显示层（3d）与消息合并策略（【框架】8.3）。

### 9.3 推送管线（F2）

```text
事件触发（升级结算/掉落入账/注册完成/G7 公告/系统预警）
  → ① 总开关 enabled? 否→丢弃
  → ② 类型开关 events.<type>.enabled? 否→丢弃
  → ③ 模板渲染（按类型占位符表：{name} 玩家名 / {level} 等级 / {item} 物品名 / {quality} 品质 / {message} 公告正文 / {time} 时间）
  → ④ 频道路由（channels 展开为群/私聊目标）
  → ⑤ 统一发送出口：限频检查（单群 ≤20/分钟，超限丢弃并记日志）→ 3d 前缀装配 → 投递
```

- 投递失败/超限丢弃**不影响玩法结算**（推送为副作用，事务外执行；结算事务先提交再发推送，推送失败不打回结算）。

---

## 十、数据包保护契约（只读保护 + 锁定签名）

### 10.1 依据

【框架】L1191-1197：

> 数据包保护（作者更新中）：
> - 编辑器【通用设置】开启"数据包保护"：编辑期间玩家发送任何指令 → 返回"作者更新中，请稍后再试..."
> - 关闭保护 / 保存发布后玩家恢复正常游玩
> - 用于大改版时避免玩家用半成品数据游玩

另：模板只读带锁 L1030-1033（预置数据包带锁，复制副本编辑）；活动管理与数据包保护联动 L1128「到点由 apscheduler 自动启停，与数据包保护联动」。

### 10.2 生命周期（F3：锁定 → 拦截 → 发布解除）

```text
开启保护（enabled=true）
  → A 锁定：对当前校验通过的发布配置快照计算 lock_signature = sha256(配置快照 JSON 规范化序列化)
              编辑器该包进入只读（editor_readonly=true），保存/修改被拒（"数据包保护中，请先关闭保护"）
  → B 运行侧拦截：玩家（非 GM/机主）任何游玩指令 → player_notice 提示（L1194 原文为默认文案）
              GM/机主指令放行（可继续 /重载 /调试 等管理动作）；/帮助 /状态 等只读查询按 5b 权限分级处理
  → C 保护中编辑（半成品）：编辑器文件写入仍允许（经编辑器"预览保存"通道）→ 热重载检测到变更但**不发布**（仅编辑器内预览可用，3e2 接缝）
              每次校验通过的预览变更 → lock_signature 刷新（半成品标记延续）
  → D 关闭保护 / 保存发布：lock_signature 清除 → 当前配置按 3e2 原子替换发布 → 玩家指令恢复
```

- 防绕过：拦截发生在 commands 层统一入口（3c 路由之后、业务执行之前），**无法通过别名/快捷/私聊绕过**（私聊同样拦截——数据包保护是内容包级而非频道级）；封禁、GM 与管理指令不受拦截。
- 活动联动（L1128）：活动到点（apscheduler）判定时若处于保护中 → **延后启动**（不激活半成品配置）；保护解除后补触发判定一次【补白】。
- 玩家可感知：保护中玩家触发任意指令收到固定提示（L1194），不含配置细节（不泄露作者在改什么）。

### 10.3 与其他系统的关系

| 系统 | 保护期间行为 |
|---|---|
| 热重载（3e2） | 变更检测照常 → 仅编辑器预览，不发布；registry 快照保持上一发布版本 |
| 排行榜（§8） | 榜单快照不刷新（保持发布版数据） |
| 事件推送（§9） | 玩法类事件（升级/掉落）照常收（玩家仍在玩上一发布版）；announcement 公告类仍可发（作者主动公告） |
| 活动/签到 | 活动到点延后启动（10.2）；签到按发布版配置照常 |
| 编辑器（5a） | 通用设置页显示保护状态 + 锁定签名摘要；包列表只读标记 |

---

## 十一、校验规则（settings 模块校验清单，承接 3e §5.2）

> 校验二分法与阻断语义（红拦 5 类 = 拒绝加载 / 黄提示 = 放行）→ 3e §2；本清单为 **settings 模块专属行**，注册进 3e 校验器 `settings.json` 模块校验清单（3e 5.2 表补行，含字段元数据表登记 L447-474）。

### 11.1 红拦（V1~V8，任一 → 整包阻断 + 聚合报错）

| # | 规则 | 判定 | 对应 3e 红拦类 |
|---|---|---|---|
| V1 | 结构/枚举合法 | 类型错误、枚举非法（pvp.mode / modules mode / command.command_mode / death_penalty.mode / broadcast.mode）、action 键不存在 | 第 1/5 类 |
| V2 | 引用存在 | sell_ratio.overrides 键 / leaderboard.currency_id / death_penalty.currency_loss.currencies / event_push.channels 群号格式 → 必须存在或格式合法 | 第 4 类 |
| V3 | ID 唯一 | currencies.id / job_tier_map 键（同名档位）全局唯一 | 第 5 类 |
| V4 | 数量合法 | level_cap.value / job_tier_map 区间 min≤max / top_n / poll_interval_ms / 各时长字段 ≥ 下限 | 第 2 类（负数）/第 5 类 |
| V5 | 数值范围 | ratio 类（0~1）、refresh_sec ≥60、season_days ≥1、period/weather_minutes ≥30 | 第 2/3 类（越界=非法值） |
| V6 | 结构完整 | time_cycle.weather.default_pool 非空且键唯一；job_tier_map 七档区间单调衔接（下档 max+1 = 上档 min） | 第 1/5 类 |
| V7 | 保护语义 | data_protection.enabled=true 时 lock_signature 必须为空或合法 sha256 格式（作者不可手填伪造签名） | 第 1 类 |
| V8 | 数组规模 | currencies 非空（0 个货币 = 无经济系统 → 拒绝，防半套配置）；types 非空且 ∈ 三枚举 | 第 5 类 |

### 11.2 黄提示（V9~V12，放行 + 一条聚合提示）

| # | 规则 | 提示阈值 |
|---|---|---|
| V9 | 数值过大 | level_cap > 9999、death_penalty ratio > 0.3、post_battle_recovery ratio > 0.5、top_n > 50、hot_reload > 60000ms、pvp.zombie_days < 30 |
| V10 | 满级经验转换 | level_cap.exp_convert=true 且未配换算比率（5c 数值经济总表对应键）→ 提示确认 |
| V11 | 未登记键 | event_push.events 中出现类型注册表外的键（新事件类型扩展）→ 提示将按模板字面输出 |
| V12 | 声明与开关冲突 | modules.mode=off 但 manifest.modules 仍声明该模块文件 / command white_list 含 GM 指令名 → 提示确认 |

---

## 十二、接缝清单（10 处）

| # | 接缝 | 本契约给出 | 对方契约承接 |
|---|---|---|---|
| 1 | **3e loader 校验** | settings 模块校验清单 V1~V12（§11）注册进 3e §5.2 校验器模块清单；settings 为常驻模块（D-01），读入时机=manifest 之后、其余模块之前（经济/开关被其它模块校验引用） | 3e §1（五段管线/红黄二分/聚合报错） |
| 2 | **3e2 热重载** | settings 变更随热重载原子生效（3e2 F2）；保护中变更仅预览不发布（§10.2-C）；进行中对局持旧 settings 快照（PVP 配置/战斗天气修正/出售比率开局锁定，4e TC-13「快照旧配置结算」对齐）；hot_reload.poll_interval_ms 进本文件 §7.5 | 3e2 TRG/ATO/SNAP/OLD/BLK 全表 |
| 3 | **6c 资源轴开关** | time_cycle.enabled=false → [季节:X] 条件键失效、6c 季节技能组全按通用、on_season_change 不触发（§3.2）；**边界声明**：资源轴注册在 stats.json、能量增减在技能行，两者开关均不在 settings——本文件不重复造资源轴开关（防重复造系统，6c D-01 同哲学） | 6c §二.5 换季边界/§三 组合表 |
| 4 | **2a4a/2a4c 时间天气** | time_cycle 段字段级 schema（§3）为三周期引擎唯一配置源；broadcast 默认关（懒广播） | 2a4a 周期注册表/2a4c 条件键互译表（[季节:X] 补行已登记） |
| 5 | **2c4d/2c4f 炼金** | modules.alchemy mode 三态（§7.3）；off → 2c4d 指令表整体不路由（提示未启用） | 2c4d 指令表/2c4f 能量条（不依赖 settings 开关，能量=资源轴） |
| 6 | **2c5a 职业等级** | job_tier_map 主落 settings（§2.3），默认七档；proficiency.json 可选覆盖（默认值="settings"） | 2c5a LVL-05/06（成长曲线 job_rank_levels 默认阈值已在 2c5a） |
| 7 | **4e PVP** | pvp 段 9 字段 schema（§4.1）= 4e CFG-01~08 + 模式二选一；卡片两级配置（掉落/惩罚）不重复造字段 | 4e CMD-A1 校验①②③④/CFG 表/ST-T1~T4/SET-R02~03 |
| 8 | **3d 消息前缀** | message_prefix 段归属登记（§6.1），不重复字段 | 3d §1.2/§3.3/§九 红黄规则全量 |
| 9 | **5a 编辑器** | 通用设置页卡片清单 = 六大分段 15 段项（§1.2 总览表）；数据包保护编辑器只读锁（§10.2-A） | 5a P-03/P-05 作用域声明（通用设置页复用元数据渲染/保存/校验/热重载机制） |
| 10 | **5b GM/公告** | event_push 频道复用公告通道（§9.2）；announcement 类型与 G7 /广播 同管线；保护中 GM 指令放行（§10.2-B） | 5b G7（推送目标群数+私聊+定时）/G2 权限分级 |

---

## 十三、验收测试用例（TC-01 ~ TC-18）

> 覆盖映射：加载与默认值 TC-01~04（§1/§0.3）+ 功能开关 TC-05~09（§7/§8）+ 事件推送 TC-10~12（§9）+ 数据包保护 TC-13~16（§10）+ 校验与旧局旧配置 TC-17~18（§11/§12）。引用列 = 断言依据。

| # | 用例名 | 前置 | 操作 | 预期 | 引用 |
|---|---|---|---|---|---|
| TC-01 | 空包默认值装配 | content 包无 settings.json（manifest 空 modules） | loader 加载 | 加载成功；全段项取框架默认值（currencies=金币+钻石/level_cap=1/death_penalty=none/pvp.enabled=false/leaderboard.enabled=false…），无红拦无黄提示 | 【框架】L374；3e §1.2；D-01 |
| TC-02 | settings 常驻加载 | manifest.modules 未声明 settings | loader 加载 | settings.json 仍被读取并生效（如 currencies 覆盖默认金币名） | D-01；【时间天气】L126（无独立模块名） |
| TC-03 | 顶层键平铺 | settings 含 level_cap/pvp/time_cycle/currencies/leaderboard | 解析后断言 keys | 根对象直接含全部段项键，无 world/battle 包装层；编辑器元数据表按平铺登记 | D-02；【框架】L374 |
| TC-04 | 空配置也能玩 | settings.json = `{}` | 玩家 /攻击 | 按默认值正常游玩（默认无经济惩罚/无 PVP/无排行榜） | D-03；【覆盖审计_A】P1-3 |
| TC-05 | 排行榜默认关 | settings 未配 leaderboard | 玩家：`/排行榜` | 提示「本服未开启排行榜」；无任何榜单计算/缓存写入 | D-03；【框架】L1100 |
| TC-06 | 排行榜开启 | leaderboard.enabled=true, types=[level,currency], refresh_sec=3600 | 玩家：`/排行榜` | 返回快照缓存榜单（Top10 等级榜）；1 秒内重复查询命中缓存（无重算日志） | D-05；【框架】L1100 |
| TC-07 | 榜单数据源 | 玩家 A 等级 45/Lv2 玩家 B 10；kill_count A=999 | 切换 `/排行榜 击杀` | kills 榜 A 首位；数据来自 longline_counters.kill_count | 【框架】L229；8.2 |
| TC-08 | 榜单刷新窗口 | refresh_sec=60；A 升级后 <60s 查榜 | 60s 内查询两榜 | 缓存快照不变（显示旧等级）；60s 后查询显示新等级 | D-05；8.3 |
| TC-09 | PVP 关闭拦截 | pvp.enabled=false | A：`/决斗 90001` | 「本服未开启玩家决斗」拒绝发起 | 4e TC-03；【框架】L358 |
| TC-10 | 升级推送默认关 | event_push 未配置（默认关） | 玩家升级成功 | 无任何推送消息；升级结算正常 | 【框架】L1101「默认关，防刷屏」；9.1 |
| TC-11 | 升级推送开启+限频 | level_up.enabled=true, channels=[指定群 10001]；同回合 3 人升级 | 3 人升级触发 | 群 10001 收到 3 条内合并推送；单群每分钟计数 ≤20；推送失败不影响结算 | L1101；【规则】L499-501；9.2/9.3 |
| TC-12 | 新玩家欢迎推送 | player_join.enabled=true, template 自定义 | 新玩家 /注册 成功 | 所在群收到欢迎语（{name} 渲染为玩家名）；未开启时不推 | 【框架】L1126；9.1 |
| TC-13 | 数据包保护开启→指令拦截 | data_protection.enabled=true | 玩家：`/攻击 2`；GM：`/调试` | 玩家收到「作者更新中，请稍后再试...」；GM 指令放行；lock_signature 生成非空 sha256 | 【框架】L1193-1194/L1195；10.2-A/B；V7 |
| TC-14 | 保护中编辑器只读 | 保护开启 + editor_readonly=true | 编辑器保存任一模块 | 保存被拒（「数据包保护中…」）；文件 mtime 未变；热重载不发布（registry 快照保持上一发布版） | L1030-1033；10.2-A/C；3e2 ATO |
| TC-15 | 关闭保护=发布解除 | 保护开启，期间改过预览配置 | 关闭保护 / 保存发布 | lock_signature 清除；新配置按 3e2 原子替换发布；玩家指令恢复；玩家行为数据不回滚 | L1195；10.2-D |
| TC-16 | 保护中活动延后 | 保护开启；活动到点 | apscheduler 到点触发 | 活动不启动（不激活半成品）；保护解除后补触发判定一次并启动 | L1128；10.2-C |
| TC-17 | 红拦聚合 | settings 含 3 处错误（mode 非法/currencies 空数组/override 引用不存在） | loader 校验 | 一次抛 3 条聚合红拦，整包拒绝挂载，无部分生效 | 3e §1.4（阻断式）；V1/V2/V8 |
| TC-18 | 旧局旧配置 | 战斗/决斗进行中热重载 pvp 与 sell_ratio | 重载后结算 | 对局按开局 config_ref 快照结算（掉落比率/PVP 参数不变）；新对局用新配置 | 3e2 OLD；4e TC-13；§12-2 |