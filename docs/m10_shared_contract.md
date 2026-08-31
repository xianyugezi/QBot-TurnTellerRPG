# M10 · 批0 共享契约（fishing 数据与配置层）

> 生成：2026-08-31 · 依据：钓鱼玩法设计定稿 v1.0.1 + 细化 2c1a（320 行）+ docs/m10_接口摸底.md
> 用途：批0 三路（路0A settings.fishing 段 / 路0B fishing.json 鱼种+CSV / 路0C 校验器 V1-V4+W1）的接口权威。多路并行零冲突的保证。
> 行号引用以细化文档为准；跨文件字段表在此唯一权威，细化行号不用抄。

## 〇、fishing 数据顶层结构

```
profession.json fishing 段（实现层=settings.json fishing 段，同 forge 段先例）:
fishing = {
  mode: "full",                 # 三态 full/simple/off（V4 硬枚举）
  bait_ids: ["饵_蚯蚓",...],      # 5 档饵引用炼金 recipe
  bait_bonus: {rare:8, gold:2}, # 对口饵加成（百分数）
  rod_full_bonus: {rare:4, gold:2}, # 满力收杆 roll 加成
  crown_thresholds: {reverse:5, silver:85, gold:95},
  wait_sec: {min:300, max:900}, # 0=即收
  daily_limit: 20,
  energy: {enabled: false},
  king_event: {enabled: true, window_daily: 2, chance: 0.3}
}

fishing.json = {
  schema_version: "1.0",
  species: Fish[],        # 鱼种池 ≥1（V5 防空池）
  king: KingEvent[]       # 可选鱼王表（批4 用，批0 只定义 schema）
}
```

## 一、settings.fishing 段（路0A · T01）

- **落点**：`content/test_demo/settings.json` 加 `"fishing": {...}` 段（对齐 forge 段先例，L201）；`tests/fixtures/packs/legal/settings.json` 同步。
- **字段表**（9 键，默认值与定稿 §三 逐键一致）：

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| mode | str | "full" | 三态枚举 full/simple/off（V4） |
| bait_ids | str[] | 5 档 | 炼金 recipe 引用 id |
| bait_bonus | obj | {rare:8,gold:2} | 对口饵稀有/金加成百分数 |
| rod_full_bonus | obj | {rare:4,gold:2} | 满力收杆 roll 加成百分数 |
| crown_thresholds | obj | {reverse:5,silver:85,gold:95} | 冠级阈值（V2 序校验） |
| wait_sec | obj | {min:300,max:900} | 等待区间秒；0=即收 |
| daily_limit | int | 20 | 每日次数 |
| energy | obj | {enabled:false} | 能量条开关 |
| king_event | obj | {enabled:true,window_daily:2,chance:0.3} | 鱼王事件 |

- **加载容错**（对齐 forge_settings 路0B 模式）：settings.fishing 段缺失/空 → 默认值兜底不报错；键名照契约原样；非法类型逐键兜底；**V4 mode 非枚举值硬错由校验器拦（路0C），读段不拦**。
- **自测**：段缺失默认 / 部分键覆盖 / 非法类型兜底。

## 二、fishing.json Fish 行（路0B · T02）

- **落点**：`content/test_demo/fishing.json` + `tests/fixtures/packs/legal/fishing.json`（同步）。
- **Fish 字段表**（2c1a F-01~F-14）：

| 字段 | 类型 | 必填 | 默认 | 语义 |
|---|---|---|---|---|
| id | str | 是 | — | 鱼种唯一键（英文小写蛇形，全文件唯一 V5） |
| name | str | 是 | — | 中文名 |
| rarity | enum | 是 | normal | normal/rare/gold（70/25/5 体系） |
| size_min | float | 是 | — | 大小下限 cm（百分位 0%） |
| size_max | float | 是 | — | 大小上限 cm（≥size_min V1） |
| weight_min | float | 是 | — | 重量下限 kg |
| weight_max | float | 是 | — | 重量上限 kg（≥weight_min V1） |
| seasons | enum[] | 否 | [] | spring/summer/autumn/winter；空=全年 |
| periods | enum[] | 否 | [] | dawn/noon/dusk/night/midnight；空=全天 |
| hours | str[] | 否 | ["00:00-24:00"] | 现实钟点硬约束 |
| spots | str[] | 是 | — | 钓点 id 引用 maps.json 采集点，≥1（V6） |
| preferred_bait | str[] | 否 | [] | 对口饵 id 引用 settings.fishing.bait_ids（V3） |
| codex_text | obj | 否 | — | {desc, unit:"cm-kg", best_mask}（C-01~03） |
| king | obj\|null | 否 | null | 鱼王行级配置（K 表，批4 用） |

- **夹具基准行**（2c1a §1.3 逐字段必测）：

```json
{
  "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
  "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
  "seasons": ["spring", "summer", "autumn"], "periods": ["dawn", "noon", "dusk"],
  "hours": ["00:00-24:00"], "spots": ["map_laketown:pier_01"],
  "preferred_bait": ["饵_蚯蚓"],
  "codex_text": {"desc": "鳞片泛银光的鲤，黄昏时最活跃。", "unit": "cm-kg",
    "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg · {best_crown} · 逆金冠×{reverse_crown_count}"},
  "king": null
}
```

> spots 引用注意：test_demo 现有 maps.json 采集点 id（gp_moon_grass 等）无「垂钓点」语义——夹具行 spots 用 map 名+钓点 id 组合（如 `map_laketown:pier_01`）作为**垂钓点 id**，钓鱼引擎侧按 maps 采集点变体解析（批2 接线）；路0B 只保证数据形态与校验器引用存在性口径对齐（V6 spots 引用存在性——若 test_demo 尚无垂钓点，夹具行 spots 用现有采集点 id 或标注【工程补白】待批2 建垂钓点）。

- **CSV 双向**（2c1a §1.4，13 列固定序）：`id/name/rarity/size_min/size_max/weight_min/weight_max/seasons/periods/hours/spots/preferred_bait/codex_text`；codex_text 单 JSON 单元格。导出→导入逐字段一致（TC-03）。
- **空数组语义**：seasons/periods 空=不限制（时段匹配层任意候选，TC-02）；hours 硬时钟约束（TC-04）。

## 三、校验器（路0C · T03）

- **落点**：`qbot_rpg/content/fishing_models.py`（FishDef/KingEventDef + validate_fishing）+ loader `_KIND_FOR_MODULE["fishing"]="fish"` + field_meta 登记（fishing_module_meta entry_type=object fields={} 空表防泛型误拦，专项全权——对齐 forge/dungeon 口径）。
- **校验规则**（V1-V4 硬 + W1 黄，V5/V6 扩展实现）：

| # | 级别 | 规则 |
|---|---|---|
| V1 | 硬 | 鱼种区间 size_min ≤ size_max 且 weight_min ≤ weight_max（逐鱼，报字段路径） |
| V2 | 硬 | 冠级阈值 0 < reverse < silver < gold < 100 |
| V3 | 硬 | 定向饵双向引用：preferred_bait[] 每个 id ∈ settings.fishing.bait_ids；「定向饵」recipe fish_target 指向鱼种存在 |
| V4 | 硬 | mode 三态枚举 full/simple/off（非枚举硬错不静默） |
| V5 | 硬 | 鱼种 id 全局唯一 |
| V6 | 硬 | seasons/periods/hours/rarity 枚举成员合法；spots 引用 maps 采集点存在且非空 |
| W1 | 黄 | simple（及 off）模式存在 fish king/king 表 → 提示「simple 不生效」不阻断 |

- **report 三形态收集器**：`_Checker._err/_warn` / `.errors` 列表 / `{"errors":[]}`（对齐 M3 路A 变体，收口直传 _Checker 零适配）。
- **自测**：V1-V4 各有独立失败用例（TC-18~21）+ W1 黄提示不阻断（TC-22）+ legal 包红拦零命中 + V5/V6 扩展（TC-22b）。

## 四、路分工与文件清单（零冲突）

| 路 | 文件（新增 or 扩展） | 独占 |
|---|---|---|
| 路0A | `qbot_rpg/core/fishing_settings.py`（新，读段容错）+ `tests/unit/test_fishing_settings.py` + `content/test_demo/settings.json`（加段）+ legal settings.json | settings.json |
| 路0B | `qbot_rpg/content/fishing_csv.py`（新，CSV 双向）+ `tests/unit/test_fishing_csv.py` + `content/test_demo/fishing.json`（新）+ legal fishing.json | fishing.json |
| 路0C | `qbot_rpg/content/fishing_models.py`（新，Def+校验器）+ `tests/unit/test_fishing_models.py` + `qbot_rpg/content/loader.py`（加行）+ `qbot_rpg/content/field_meta.py`（加行） | loader/field_meta |

> 三路零共享文件；路0A 只读不改 fishing.json；路0B 只读不改 settings.json；路0C 只读不改 content JSON（用 fixtures 校验）。**field_meta/loader 归路0C 独占**（避免并发写同一文件）。

## 五、铁律（每路必守）

1. 零 NoneBot import；core/content 层纯函数零 IO 零定时器
2. 确定性：无裸 random；测试种子化
3. 文件头标注「依据：细化_2c1a §Y / 定稿 §Y」
4. 子 agent 交付自报不可信：真实 smoke exit 0 + 单测全绿 + **ruff check . / mypy . 全绿**（lint 门禁，别只信 pytest）
5. **M43 docstring 禁词**：文件头/docstring 勿写字面「time.sleep」（探针扫全仓），用「零定时器/零睡眠」
6. emoji 纪律：渲染输出零 emoji（仅 ✅/❌ + 排版符号）；数据字段无 emoji
7. 未知键默认放行不破坏加载（对齐 §3 加载器兜底）
8. **契约偏差记 contract_deviations**：细化/派工单与实际实现不符处逐条写清，不静默