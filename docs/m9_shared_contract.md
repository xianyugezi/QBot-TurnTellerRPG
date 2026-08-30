# M9 · 批0 共享契约（forge 数据层）

> 生成：2026-08-30 · 依据：定稿 §11/§12 + 细化 2c2a/2c2b/2c2c/2c2d + docs/m9_接口摸底.md
> 用途：批0 三路（路0A forge 数据模型+校验器 / 路0B items/settings/equipment 扩展 / 路0C fixtures）的接口权威。多路并行零冲突的保证。
> 行号引用以细化文档为准；跨文件字段表在此唯一权威，细化行号不用抄。

## 〇、forge.json 顶层结构

```
forge.json = {
  schema_version: str(必填),      # D-01 如 "1.0"
  trees: ForgeTree[] (必填,≥1),    # D-02 每部位一棵（weapon + 防具×5 = 6 棵）
  sets: Set[] (可选),              # D-03 P1 防具套装（2c2d §一 展开）
  augments: {augments:[], limit_by_rarity:[]} (可选),  # D-04 P2 客制（2c2d §二 展开）
  settings: ForgeSettings (可选)   # D-05 全局可配（2c2a §1.4）
}
```

## 一、ForgeTree（树级字段 T-01~05）

| 字段 | 类型 | 必填 | 默认 | 语义 |
|---|---|---|---|---|
| id | str | 是 | — | 树唯一键（tree_weapon），全文件唯一（V1） |
| name | str | 是 | — | 部位中文名（武器树），/锻造树 分页标题 |
| type | enum | 是 | — | weapon/armor_head/armor_body/armor_hand/armor_leg/armor_foot；全文件唯一→每部位一棵（V1）；与树内节点 N-04 一致（V2） |
| roots | str[] | 是 | — | 根节点 id 列表（无 parent），≥1；均须为本树已定义节点（V3） |
| nodes | Node[] | 是 | — | 该部位全部节点；节点 id 全局唯一（V2） |

## 二、ForgeNode（节点级字段 N-01~17）

| 字段 | 类型 | 必填 | 默认 | 语义 |
|---|---|---|---|---|
| id | str | 是 | — | 节点唯一键，全文件唯一（V2） |
| name | str | 是 | — | 装备中文名，/锻造 参数匹配名 |
| item | str | 是* | — | 产物装备引用 items.json ID（别名 output_item 二选一，不双写，TC-08）；V7/V8 |
| type | enum | 是 | — | weapon/armor_head/...；须与 items 条目类型匹配（V8）、与所属树 type 一致（V2） |
| level | int | 是 | — | 节点等级（职业门槛），≥1（V12）；根节点建议 1（W6） |
| parent | str\|null | 是* | — | 父节点 id（根=null）；须本文件已定义且同树（V3）、无环（V4） |
| branch | str[] | 否 | [] | 分支节点 id（本线可转出其他线）；每 id 须存在（V5） |
| stats | obj | 否 | {} | 属性改造 {atk, element, element_value}；元素键走 formula 注册表；双源仲裁 AR-1/AR-2 |
| slots | {level:int}[] | 否 | [] | 孔位（slot_level ∈{1,2,3}，V14；带孔装备唯一来源） |
| materials | MaterialReq[] | 是 | — | 素材需求行 ≥1 行（V10/V11） |
| cost | obj | 否 | {} | 锻造金币开销 {coins}；缺省按 settings forge_fee 节点等级×10 |
| rarity | enum | 是 | 继承 items.quality | 四档 normal/fine/epic/legendary（V13）；历史整数 1-4 兼容映射；冲突以节点为准（AR-3） |
| monster_source | str\|null | 否 | null | 怪物来源 id（loot.json 怪物键） |
| final | bool | 是 | false | ■最终强化：线终点（叶子）必须 true（V6）；true 不得有子 |
| augmentable | bool | 否 | false | 可否客制（P2）；仅 final=true 且 weapon 时可 true（V16 黄） |
| king_only | bool | 否 | false | 铸造王专属配方节点（N-16 扩展，2c2d）；level≥7（W3 黄） |
| final_tier | bool | 否 | false | 终盘标记（N-17 扩展）；仅 final=true 且 rarity=legendary 时可 true（W4 黄） |

### MaterialReq（M-01~04）

| 字段 | 类型 | 必填 | 默认 | 语义 |
|---|---|---|---|---|
| item | str | 是 | — | 素材 id，引用 items.json 材料类条目（V10） |
| count | int | 是 | — | ≥1 正整数（V11） |
| tier | enum | 否 | items.material_tier | 素材档位覆写 normal/rare（M-03，行覆写 > items 元数据） |
| source_override | str | 否 | items 来源标签 | 来源提示覆写（M-04，显示文本如 火龙掉落/商店） |

### 双源仲裁（AR-1~5）
- AR-1 覆盖：节点声明的键（stats.*/slots/rarity/monster_source/final/augmentable…）以节点为准
- AR-2 追加：节点未声明键继承 items 基础值
- AR-3 品质：节点 rarity 必填（四档）；与 items.quality 冲突以节点为准；未配=继承 items.quality
- AR-4 配置模式：瘦 items+富节点 / 富 items+薄节点（只建议不限制）
- AR-5 实例快照：/锻造 完成时按「items 基础+节点改造」合并实例化，属性快照入玩家存档

## 三、ForgeSettings（S-01~05 + 2c2d 补白键）

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| forge_fee | str\|int | "节点等级×10" | 锻造金币开销（可配）；节点显式 cost 覆盖它 |
| synth_ratio_3to1 | bool | true | 3:1 合成开关（P1）= recipe.json kind=combine 实例开关；false=W4 死锁提示 |
| straight_forge | bool | true | 直锻模式（小白 1 步）；false=深度模式（预览→/确认 2 步） |
| decompose_rate | obj | {正式:0.4,...} | 分解回收率（复用炼金分解规则，/分解 用） |
| exp_per_forge | int | "节点等级×2" | 铸造熟练经验每件（可配） |
| sets_enabled | bool | true | P1 套装开关（2c2d 补白键）；false 时 sets 数据存在→W3 黄 |
| augments_enabled | bool | true | P2 客制开关（2c2d 补白键）；false 时 augments 数据存在→W3 黄 |

## 四、Set（forge_sets · P1 结构预留 · SET-01~08 + SK-01~04）

| 字段 | 类型 | 必填 | 默认 | 语义 |
|---|---|---|---|---|
| id | str | 是 | — | 套装族 id（α/β 两条记录共用），族级唯一（V1） |
| name | str | 是 | — | 中文名；/套装 参数匹配名 |
| variant | enum | 是 | — | alpha/beta；(id,variant) 唯一（V1） |
| pieces | str[] | 是 | — | 套装件 = forge 树节点 id 列表，≤5 项；type∈防具五部位且不重复（V2） |
| skills | SetSkill[] | 是(≥1) | — | 技能档位（V3：piece_count∈{2,3,5} 且同 skill 递增连续；level∈{1,2,3}） |
| desc | str | 否 | "" | 套装介绍（图鉴条目） |
| enabled | bool | 否 | true | 套装模块开关 |
| codex_group | str | 否 | =id | 套装图鉴聚合分组（4d craft 册） |

SetSkill：piece_count∈{2,3,5}（SK-01）/ skill str（SK-02）/ level∈{1,2,3}（SK-03）/ effect_ref str（SK-04 效果接线，空=占位）

## 五、Augment + limit_by_rarity（forge_augments · P2 结构预留 · AUG-01~12 + LIM-01~03）

```
augments: {
  augments: [
    {id, name, kind: numeric|slot, effect, stat_key?(numeric必填), value?{flat|pct},
     cost: [{item,count}]≥1, repeatable?(缺省true), max_repeat?(缺省3),
     slot_level?(slot必填∈{1,2,3}), disabled?(缺省false), trace?(缺省false)}
  ],
  limit_by_rarity: [
    {quality: epic|legendary, times≥1, final_only? 缺省false}   # V6：quality 只认四档枚举；同 quality 至多 2 行（1 普通+1 final_only）；final_only 行必须 quality=legendary
  ]
}
```
- V4：kind∈{numeric,slot}；numeric 必填 stat_key；slot 必填 slot_level∈{1,2,3}；cost≥1 行
- V5：cost[].item 引用 items 存在；龙脉石类须 material_tier:rare；宝石类引用存在
- 追溯行示例：aug_heal 已砍（回复·吸血，2026-08-16 用户拍板），disabled+trace 保留不生效（W2 黄）

## 六、校验器规则（V1-V15 硬；V16/W1-W6 黄）

### 硬校验（V1~V15，失败→加载失败报字段）
| # | 规则 |
|---|---|
| V1 | 树级唯一：trees[].type 全文件唯一；trees 非空；树 id 唯一 |
| V2 | 节点全局唯一 + 树内一致：node.id 全文件唯一；node.type 与所属树一致 |
| V3 | 父节点引用：parent 非空须本文件已定义节点且同树；roots 每 id 存在 |
| V4 | 树无环：沿 parent 正向遍历无自环；每节点可达某一根 |
| V5 | 分支可达：branch[] 每 id 已定义；重复分支去重告警 |
| V6 | 终点=最终强化：叶子（无子引用）必须 final=true；final=true 不得有子 |
| V7 | node.item 引用存在（items.json 装备条目） |
| V8 | items 条目类型与 node.type 匹配 |
| V9 | 改造键空间：节点改造键（stats.*/slots/rarity/final…）在 items 元数据键空间内 |
| V10 | 素材引用：materials[].item 存在且为 items 材料类条目 |
| V11 | 素材数量/档位：count≥1；tier∈{normal,rare}；materials 每节点≥1 行 |
| V12 | 等级合法：level≥1 整数 |
| V13 | 品质合法：rarity∈四档；历史整数 1-4 兼容 |
| V14 | 孔位合法：slots[].level∈{1,2,3} |
| V15 | 级联删除复查：级联操作后无残留悬空引用（红名节点父链完整、branch 已清）；/锻造 拒绝红名节点 |

### 黄提示（V16/W1~W6，不阻断）
| # | 规则 |
|---|---|
| V16 | augmentable=true 且 final=false 或非武器 → "仅最终强化武器可客制" |
| W1 | 改造键与 items 同键冲突 → "覆盖生效"提示 |
| W2 | 元素武器：节点带元素但怪物表无弱该属性怪 → "该怪无弱点，元素武器无发挥空间" |
| W3 | settings 关闭 P1/P2 但存在 sets/augments 数据 → "该段不生效" |
| W4 | synth_ratio_3to1=false 且素材死锁风险 → 提示 |
| W5 | 节点总量超规模（武器>500/防具>800）→ 配置负担预警 |
| W6 | 根节点 level≠1 → 建议根=1 |

### 2c2d 校验（V1-V8 硬；W1-W4 黄，针对 sets/augments）
- V1 套装族唯一+变体组合唯一；V2 套装件引用（forge 节点存在）+部位防具五部位+不重复+≤5；V3 技能档位 2/3/5 递增连续、level∈{1,2,3}；V4 客制项枚举结构；V5 客制消耗引用（items 存在、龙脉石 rare、宝石存在）；V6 次数表合法（四档枚举、同 quality≤2 行、final_only 必须 legendary、times≥1）；V7 节点扩展合法性（king_only→level≥7 W3 黄；final_tier→final=true 且 legendary W4 黄；augmentable→final=true 且 weapon）；V8 客制全段 disabled 且 settings 开 → 黄提示配置意图存疑
- W1 α/β 孔位对照（α≤β，技能多孔少/技能少孔多）；W2 追溯行 trace → 提示"回复已砍不生效"；W3 settings 关但数据存在；W4 套装技能 level 超默认封顶 3

## 七、接口签名（校验器统一形态）

```
# 校验器统一形态（对齐 M3/M8 收口口径）
def validate_forge(modules, report) -> None:
    """modules: dict（含 forge/items/settings 等模块 raw 数据，同 loader 形态）
    report: 收集器——优先找 report.error/warning 方法；回落 report._err/_warn；
            JSON 收集器形态 {"errors":[], "warnings":[]} 也可（_emit 兜底）。
    硬校验失败 → 写红（加载失败）；黄提示 → 写黄（不阻断）。
    """
# 收集器兼容：_emit(report, kind, module, rule, message, level) 内部统一封装
```

## 八、items/settings 扩展（路0B 契约）

### items.json 材料类扩展
```
材料类条目新增字段：
  "material_tier": "normal" | "rare"     # TIER-03a：普通/稀有两档（与装备品质四档独立，TIER-03b 不混用）
  "source": "采集点/怪物/商店"            # SOUR-00 来源标签（缺件提示/图纸分支数据源）
装备条目 type：weapon/armor_head/armor_body/armor_hand/armor_leg/armor_foot（五部位，4b EQP-04）
field_meta items_fields 需登记 material_tier（enum normal/rare）与 source（str）——宽松登记防泛型误拦
```

### settings.json forge 段
```
"forge": {
  "forge_fee": "节点等级×10",          # 或 int
  "synth_ratio_3to1": true,
  "straight_forge": true,
  "decompose_rate": {"正式": 0.4},     # 对齐 alchemy.decompose_rate 口径
  "exp_per_forge": "节点等级×2",       # 或 int
  "sets_enabled": true,
  "augments_enabled": true
}
```

### loader / field_meta 登记
- `content/loader.py` `_KIND_FOR_MODULE` 加 `"forge": "forge"`
- `content/field_meta.py` `_module_table` 加 forge ModuleMeta（entry_type="obj"？——forge.json 顶层是 obj 非 list，需按 loader 现有形态核对；若 loader 只收 list 模块，forge 走独立 parse（参考 alchemy_models 收口模式：DEF_CLASSES 无专属 Def → BaseDef 回退 + core 层 parse_* 读取 modules_raw））
- `manifest.json` 声明 "forge"

## 九、fixtures（路0C 契约 · test_demo）

样例树拓扑（对齐 2c2a TC-01 + 定稿 §4.1 示例 + 2c2b 验收）：
```
铁剑〔1级〕→ 铁剑Ⅰ → 铁剑Ⅱ → 炎剑 → 炎剑Ⅱ → 炎剑Ⅲ → ■炎王剑（火）
          └→ 冰剑（分支：node_ice_sword ← 冰晶矿，需 采集 冰晶）
          └→ 雷剑（分支：node_lightning_sword ← 雷兽牙，雷兽掉落）
```
- 武器树：铁剑主干线（6-7 级）+ 冰剑/雷剑 2 分支 + 炎王剑 final=true
- 素材两档：普通（ore 矿石/草药/皮骨 normal）、稀有（fire_dragon_scale 火龙鳞/雷兽牙 rare，monster_source 关联）
- settings forge 段（§八）
- items.json 材料类加 material_tier + source；装备条目 type 对齐节点
- manifest.json 声明 "forge"
- 校验器红拦零命中、黄提示记录可复现

## 十、M8 坑位复述（批0 强制）

1. F3 嵌套事务：本批纯数据层不涉事务，但勿在 content/core 写 time.sleep（M43 零定时器探针）
2. Def→dict 表注入：ctx["forge"] 走注册表必须转 raw dict + resolve 单参包装
3. field_meta 宽松登记：既有 items_fields 的 type 为 str 不设枚举（防误拦既有内容包）——material_tier 新增枚举时确认不影响既有内容包
4. 来源纯度：素材档位两档（normal/rare）与装备品质四档（normal/fine/epic/legendary）不得混用；引用他版机制须显式标注来源
5. 数据表非空 + validator 生效：forge_tree 空 → V1 硬错（防空池）
