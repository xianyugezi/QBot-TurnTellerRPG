# M8 炼金 · shared_contract 子文档：《数据与校验》

> 生成：2026-08-29 · 归属：`docs/m8_shared_contract.md` 四子文档之一（核心机制 / 指令契约 / **数据与校验** / 战斗与资源循环）
> 本文定义 M8 炼金**数据模型（recipe/traits/proficiency/items·slots 扩展/settings.alchemy 段）与校验器（四件套）的可实现契约**——字段级 schema、默认值、可配标注、校验规则、SQLite 扩展、IF 接口清单、验收 TC 矩阵、本域铁律。
> 依据：细化_2c4b（修订版）/ 细化_2c4c（修订版）/ 细化_2c4e（修订版） + 炼金定稿 v2.3 §10（L348-424）+ 接口摸底报告（docs/m8_接口摸底.md，下称【摸底】）+ 用户 5 项拍板（2026-08-29）。
> 铁律：① 字段 schema 必须与细化修订版一致；② 接口签名以【摸底】§四为准（已 read 实核，非凭印象）；③ 【工程补白】显式标注；④ 只写本文件。

---

## 〇、范围与依据

| 依据 | 定位 | 关键章节 |
|---|---|---|
| 细化_2c4b_宝石货币经济（修订版） | 宝石四来源/七消耗口/三币/四轴防套利/分解回炉；TC-01~25 | §一 SRC / §二 SINK / §四 DEC |
| 细化_2c4c_珠与合成指令（修订版） | 珠体系/复制/三类组合合成/镶嵌/镶核心/分解；TC-01~30 | §一 BEL/DUP/CMB/SOCK/COR/DEC / §二 字段级 schema |
| 细化_2c4e_品质与特性（修订版） | 品质四档/traits.json schema/特性继承/存储显示；TC-01~26 | §一 QLT / §二 TSC / §三 INH / §四 STO |
| 炼金定稿 v2.3 §10（L348-424） | recipe.json 元数据表 / traits.json / items.json 扩展 / 存档 / settings alchemy 段字段表 | L352-368 / L372-376 / L378-382 / L395-406 / L408-426 |
| 细化_2c5a_职业等级与SP（辅助） | proficiency.json 字段级 schema（LVL/EXP/SP/TTL） | §五 5.1-5.3 / §6.2 校验器 |
| 【摸底】§四 内容加载与校验 | `_KIND_FOR_MODULE` / `ModuleMeta` / `check_pack` / `_check_module` 专项派发 / `validate_xxx(modules, report)` 鸭子模式 / manifest / 幂等设施 | §4.1~4.4 / §1.3 / §5.1 / §7 |
| 用户 5 项拍板 | ① 分解宝石平铺可配 ② 键集 common/uncommon/rare/legendary ③ 珠升阶无门槛 ④ 复制费 cost.coins ⑤ 数量上限 2147483647 | m8_batch_plan §一 |

**本域边界**：本文只管「数据长什么样 + 数据怎么被校验」，不展开机制流程（见《核心机制》子文档）、不展开指令参数模板（见《指令契约》子文档）、不展开战斗/种植/代工运行（见《战斗与资源循环》子文档）。

---

## 一、recipe.json 字段级 schema

> 依据：炼金定稿 §10.1 L352-358（recipe.json 元数据表）+ 细化_2c4c §2.2（四类 upgrade 实例映射）+ 细化_2c4e QLT-11（element_req）+【摸底】§4.1。
> 定位：recipe.json = 炼金全部「配方」唯一数据源，内容包 JSON；kind=craft/combine/upgrade 三类；**合成引擎 = 框架机制（代码），炼金四类「N 入→1 出」合成 = 本文件 `kind=upgrade` 的配置实例**（机制与内容分离，定稿 L359-361）。

### 1.1 字段表（逐字段契约）

| 字段 | 类型 | 默认 | 可配 | 语义 / 校验要点 | 引用 |
|---|---|---|---|---|---|
| `id` | string | 必填 | — | 配方唯一标识；命名禁保留字符 `* , = +` 空格【工程补白：对齐定稿 L12 分隔符规范 / 分隔符 L58 命名铁律】 | 定稿 L353 |
| `name` | string | 必填 | — | 展示名；/合成 /炼金 /进化 参数按 name 匹配 | L353 |
| `kind` | enum | — | — | `craft`（合成层标准版）\| `combine`（素材合成，锻造 3:1 同源）\| `upgrade`（N 入→1 出：珠升阶/成品/配方/特性四实例） | L354 / L370 |
| `level` | int | — | — | 配方等级 1-99；**准入判定**：配方 level 落在当前职业 `job_tier_map` 区间才可调合/合成（细化_2c5a LVL-06）；合成经验 = 配方等级 ×1（synth_exp） | L354 / L421 |
| `synth_allowed` | bool | `true` | 可配 | 深度配方默认 false；**改 true 提示"将绕过深度炼金玩法"不阻断**；synth_allowed 是防「合成绕过深度」字段（L505） | L354 / L505 |
| `master_only` | bool | `false` | 可配 | 大师独占配方 | L357 |
| `materials` | array | 必填(craft/combine) | — | `[{id, count}]`；id 引用 items 存在（硬拦）；count ≥1 整数；**materials = 框架统一 schema 的 inputs（item 同义，仅改名）**（L360）；**仅 craft/combine 用 materials，kind=upgrade 用 inputs/output，与 materials 互斥** | L354 / L360 |
| `inputs` | array | 必填(kind=upgrade) | — | upgrade 实例 N 入：`[{item, count}]`；item 引用 items 存在（硬拦）、count ≥1 整数（细化_2c4c §2.2；**与 materials 互斥**，upgrade 用 inputs） | L363-368 / 细化_2c4c §2.2 |
| `output` | object | 必填(kind=upgrade) | — | upgrade 实例 1 出：`{item, count}`；item 引用 items 存在（硬拦）、**count=1**（REC-11） | L363-368 / REC-11 |
| `cost` | object | — | 可配 | `{coins, gem}` 非负整数；coins=金币合成成本（复制费基准，见 §1.3）；gem=宝石消耗（kind=upgrade 实例的 cost.gem，数值对应 settings gem 段） | L355 |
| `slots` | int | `4` | 可配 2-10 | 炼金层投料槽位上限 | L355 / L356 |
| `element_req` | object | — | 可配 | `{元素: [{阈值, 效果}]}`；元素 ∈ 8 元素注册表（地水火风雷晶月无，formula.json element 表 L387）；投料累计元素值 ≥ 阈值 → 效果显现（QLT-11）；未达标 → 品质降级（QLT-10） | L355 / L152 / L387 |
| `effects` | array | — | — | 原子动作列表（效果系统 L0 词汇表，ID 引用存在性硬拦；成品效果数值 = 基准 × quality_coef 档位系数，QLT-04） | L356 / L150 |
| `traits_inherit` | int | `1` | 可配 1-3 | 可继承特性位数（普通位默认上限 3，SP/等级可扩展，细化_2c4e INH-06/14/15）；**字段范围 1-3（定稿 L356）；继承位总上限 1-6（INH-06）由 SP/等级扩展承载** | L356 |
| `catalyst` | array | `[]` | 可配 | `catalyst[]`：items type=触媒 引用存在（硬拦）；未注册仅提示（批5B 触媒机制） | L356 / L492 |
| `combine_from` | array | `[]` | 可配 | `combine_from[](recipe)`：组合合成输入配方引用（配方合成表 2 输入+1 输出+条件，L390） | L357 / L390 |
| `evolve_to` | object | — | 可配 | `{id, condition:{count, source}}`：目标配方 id 引用存在；condition.count ≥1（低阶炼金产出 N 次，合成不计）；source 来源枚举（进化线逐级计次）；**特性不继承**（TSC-18） | L357 / L200 |
| `pp_budget` | int | 内容包配 | 可配 | 配方卡 PP 上限（例：火焰弹 PP 5/5），**int ≥0**；本字段定稿表 L353-358 未单列，落 `traits_inherit` 段附近（PP 预算实现口径见细化_2c4e INH-09/§六 落点；定稿 L414 pp_cost 计价联动）【工程补白】 | L135 / L414 / INH-09 |

> **双 schema 口径**：`kind∈{craft,combine}` 用 `materials[{id,count}]`（定稿 L354）；`kind=upgrade` 用 `inputs[{item,count}]` + `output{item,count}`（定稿 L363-368 / 细化_2c4c §2.2），**与 materials 互斥**（upgrade 实例不得写 materials，否则 REC-11 校验对象无定义）。

### 1.2 kind=upgrade 四实例字段映射（合成引擎统一执行器）

> 依据：定稿 §10.1 L360-368 + 细化_2c4c §2.2 + 批2B 通用执行器（inputs N 入 / cost{coins,gem} / output 1 出）。
> 通用执行器契约：`inputs`（N 入，原子校验全量满足否则全拒+差异提示）、`cost`（原子扣费）、`output`（1 出）。**四实例均为 recipe.json `kind=upgrade` 配置实例，字段名与框架统一 schema 对齐**（inputs/cost/output，数值与定稿一致）。

| 合成 | kind | inputs（N 入） | cost（消耗） | output（1 出） | 门槛 | 引用 |
|---|---|---|---|---|---|---|
| 珠三合一升阶 | upgrade | `3×同档同 ID 珠`（普通→精良→史诗→传说，禁跳级） | `cost.gem=10`（gem.珠升阶） | 珠 +1 阶（**原数值不变**，不新随机，堆叠键变） | **无职业硬门槛**（准入靠槽级 SOCK-02，**拍板③**） | L365/L274/L230/L419 |
| 成品合成 | upgrade | 两成品（+材料，材料随成品合成表配置必耗） | `cost.gem=10` + 材料 | 更强成品（组合表目标，1 出） | 宗师 + 宝石 | L367/L203/L226/L328 |
| 配方合成 | upgrade | 两配方（已学） | `cost.gem=5` | 新配方解锁（组合表预置，2 输入+1 输出+条件；仅解锁不产物品） | 专家 + 宝石 | L368/L209/L227/L331/L390 |
| 特性合成 | upgrade | 2 同系特性 | `cost.gem=20` + 材料 | 更高位特性（高品質Lv1×Lv2=更高级；新特性条目，原两条消耗） | 宗师 + 宝石 | L366/L215/L229/L332 |

> 注：锻造 3:1 素材合成 = `kind=combine` 实例（L370，归锻造域，本文不展开）。

### 1.3 与 settings 的联动（复制费基准）

- **复制费基准 = 配方 `cost.coins`**（只算金币项、不折入材料基准价，向下取整 `⌊cost.coins×gem.复制⌋`）+ 可配额外消耗（默认 0，键名 `gem.复制额外`（=`copy_extra_cost`），int ≥0，默认 0，**拍板④**）【工程补白键/拍板④】——见《指令契约》DUP / 细化_2c4c DUP-03。
- upgrade 实例的 `cost.gem` 与 settings `gem.{成品合成/配方合成/特性合成/珠升阶}` 数值一致（L419 注：均为 kind=upgrade 实例的 cost.gem 消耗项）。

---

## 二、traits.json 字段级 schema

> 依据：炼金定稿 §10.2 L372-376 + 细化_2c4e §二 TSC-04~10 +【摸底】§4.2（traits 模块已登记）。
> 定位：traits.json = 特性**唯一数据源**（进框架 4.1，L372）；觉醒/潜力/核心表**并入** traits.json 效果表（复用原子动作，L386）；是效果系统六挂载点之一（【效果】L35-39）。

### 2.1 字段表（对照 TSC-04 ~ TSC-10）

| 字段 | 类型/枚举 | 默认 | 规则（TSC 编号） | 引用 |
|---|---|---|---|---|
| `id` | string | 必填 | 特性唯一标识；命名禁保留字符 `* , = +` 空格【工程补白：TSC-04，对齐定稿 L12 分隔符规范】；被成品 `traits` 数组与调合会话快照引用；**快照/存档冗余存储 ID+名称**（删配置降级不报错，STO-05） | L372 / L12 / L511 |
| `name` | string | 必填 | 展示名（例：灼烧强化 / 攻击+15%）；投料反馈清单、成品消息、/继承 参数均用 name 匹配 | L138 / L140 |
| `rarity` | enum | `normal` | `normal` \| `super`；**super=超特性（金色）**，PP 消耗翻倍（pp_cost.super=2）；rarity 是 PP 计价唯一依据（TSC-11） | L373 / L414 |
| `effects` | array | 必填 | 效果系统 L0 原子动作列表（damage/heal/stat_modifier/dot/control/…）；**ID 引用存在性硬拦**；特性自身不内联实现逻辑（TSC-02） | L374 / 【效果】L281-305 |
| `group` | string | — | **互斥组：组内最多 1 项**——同组特性在「继承选择」与「成品共存」两个层面互斥；同系判定键（特性合成 CMB-04）；编辑器校验器做互斥组校验（INH-13/L492） | L375 / L151 / L492 |
| `repeatable` | bool | `false` | false=同一特性不可多次继承/成品上不重复出现；true=允许重复（受效果系统叠加规则约束：同类互斥/同名递减） | L375 / L151 |
| `source` | enum | — | `素材` \| `成品` \| `金色素材`：决定投料后特性进入哪个可继承池——普通素材→普通池；金色素材→超特性池（第 4 位独占，gold_slot_exclusive）；成品（全物入料）→按携带特性原样入池（TSC-13/INH-04） | L376 / L201 / L218 |

### 2.2 JSON 样例

```json
{
  "id": "trait_burn_boost",
  "name": "灼烧强化",
  "rarity": "normal",
  "effects": [{"type": "element_modifier", "element": "fire", "value": 15}],
  "group": "fire_boost",
  "repeatable": false,
  "source": "素材"
}
```

### 2.3 与现有登记的差异（【摸底】§4.2 —— 集成要点）

- traits 模块**已登记**（field_meta L326-332 + L418）：`ModuleMeta(entry_type="list", fields=traits_fields, kind="trait", namespace="trait_lib")`；loader `_KIND_FOR_MODULE["traits"]="trait"`（loader.py L158）。
- 现有 `traits_fields`（L326-332）= `id/name/type/probability/max_stack/effects/require_status/apply_status`（状态效果触发向），**不含** 炼金 schema 的 `rarity/group/repeatable/source`。
- **集成动作【工程补白】**：`traits_fields` **增量扩展** `rarity/group/repeatable/source` 四键（保留现有 8 键，兼容既有内容包）；新增 `validate_traits` 专项（现不存在，见 §六）；内容包补 `traits.json` 数据文件。若不在 field_meta 扩展，泛型校验对新键的处理按「未知字段」口径可能漏检——以增量登记为准。

---

## 三、proficiency.json 字段级 schema

> 依据：细化_2c5a §五 5.1-5.3（LVL-03/05、EXP-02、SP-01/03/08、LVL-06、TTL-02）+【摸底】§4.1（未登记）+ m8_batch_plan 关键决策 #4（存档保持 dict 形态）。
> 定位：proficiency.json 管「职业的等级尺子」（7 级默认名/每职业熟练值/成长曲线/SP 面板/能量条，通用框架机制·代码层）；profession.json 管副职玩法内容（不在本域）。

### 3.1 字段表（细化_2c5a §5.2 逐行 + 工程补白子字段）

| 字段 | 类型 | 默认 | 范围/说明 | 引用 |
|---|---|---|---|---|
| `id` | str | 必填 | 唯一；对应 jobs.json 职业（生活职业，如 alchemy）；校验器查 id 引用 jobs 存在（硬拦） | 【熟练度】L168 |
| `tier_names` | list | `["见习","正式","精通","专家","大师","宗师","王"]` | 7 级称号**可改名**（内容包自定义）；长度 ≥2 且与 job_rank_levels 一一对应；**内容包可改、最小 2、默认 7、与 job_rank_levels 一一对应** | L169 / L27 |
| `job_rank_levels` | list | `[0,100,300,700,1500,3000,6000]`【补白数值】 | 成长曲线：7 个累计熟练阈值，与 tier_names 一一对应；键名【工程补白】（定稿仅要求"成长曲线"字段存在）；单调递增、首项=0 | L16 / L31 |
| `exp_sources` | map | `{craft:1.0, gather:1.0, combat:1.0}` | 三来源经验倍率可配；子键 craft/gather/combat【补白键名】；值 ≥0 | L170 / L32 |
| `sp_per_level` | int | `1` | ≥0；升级获得 SP 点数 | L171 |
| `sp_panel` | list | `[]` | 分支自选解锁项；子字段 `{id,name,cost,repeatable,max_repeat,desc}`【补白：定稿仅定义 list 语义】；六类解锁项（品质上限+10/投入次数+1/特性位+1/解锁复制·进化·挑战/采集量+1/连锁上限+1） | L172 / L41-47 |
| `energy` | obj | `{enabled:false, max_by_tier:[5,8,10,12,15,18,20], regen_sec:1800}` | 可选软节奏模块；**enabled 默认 false（非炼金职业默认关）**；regen_sec=1800（30 分钟回 1 格）；安全区/休整加速由 settings `energy_regen_sec_safe` 承接（见 §五）；**双开关优先级：settings.alchemy.energy_enabled 为准，本段 energy 作默认兜底**（防双开关打架，P2-4） | L173 / L69-70 |
| `job_tier_map` | map | `"settings"` | 称号→配方等级区间（见习 1-5 … 王 51+）；**主落点 settings.json**（本文档可选覆盖、默认继承 settings）；称号引用 tier_names 存在、区间单调 | L174 / L34 |
| `titles` | list | `[]` | 通用称号注册表 `{id,name,icon,source,desc}`；source ∈ king/contest/achievement/custom；**king 条目自动生成**（id=职业 ID，图鉴全亮时，TTL-03） | L175 / L141-142 |

### 3.2 玩家存档形态（保持 dict，不升格 dataclass 字段）

```json
"proficiency": {
  "alchemy": { "level": 4, "exp": 850, "sp_earned": 4, "sp_used": 2,
               "unlocks": { "quality_cap_10": 2, "trait_slot_1": 1 },
               "energy_current": 6 }
},
"title_state": { "owned": ["alchemy", "contest_champion"], "equipped": "alchemy" }
```

- **保持 dict 形态**（m8_batch_plan 关键决策 #4；【摸底】§1.2：Player dataclass 无 proficiency 字段、core/levelup.py L117-128 已有 dict 形态雏形）——**Player dataclass 不加字段**，避免 repository 大改；sp_earned+sp_used 双计防重复扣点（SP-06），加载时校验 sp_used ≤ sp_earned。
- title_state 走既有存档列（【摸底】§1.2 players 含 title_state 列）。

---

## 四、items.json / slots.json 扩展

> 依据：炼金定稿 §10.3 L378-382 + 细化_2c4c §2.1 + 细化_2c4e STO-01/02 +【摸底】§5.2。

### 4.1 items.json 扩展字段

| 字段 | 类型 | 默认 | 语义 | 引用 |
|---|---|---|---|---|
| `type` | string | — | 补 `装饰珠` 值（另触媒 type=触媒 供 catalyst 过滤下拉）；`seed` 可种植标记 | L381 / L492 |
| `quality` | enum | `common` | 珠等级=品质档（**common/uncommon/rare/legendary ↔ 普通/精良/史诗/传说**，拍板②）；素材稀有度档位（普通/稀有/金色）沿用统一稀有度注册表 | L257 / L380 |
| `elements` | object | — | 元素属性值（8 元素地水火风雷晶月无），投料累计判定 element_req | L380 / L152 |
| `traits` | array | `[]` | 继承特性 ID 集（炼金珠/成品独有；标准版恒空，TSC-03） | L380 / L117 |
| `awaken` | bool | `false` | 觉醒标记（✨素材投料，宗师；并入 traits 效果表） | L380 / L204 |
| `rarity` | enum | — | 普通/稀有/金色（素材用；provenance/rarity 注册表驱动，3 档默认） | L380 |
| `base_effects` | object | 必填（标准珠） | 珠基础效果，固定数值（标准珠=只有这个；炼金珠 base_effects+traits 两套词条） | L265 / L381 |
| `seed` | bool | `false` | 可种植标记（/种植 种子，批10A） | L381 / L392 |

### 4.2 slots.json 扩展

```json
{ "equip_id": "sword_iron",
  "slots": [ { "slot_level": 2 }, { "slot_level": 2 } ] }
```

| 字段 | 类型 | 默认 | 语义 | 引用 |
|---|---|---|---|---|
| `slot_level` | int(1-3) | — | 装备孔位等级：1=只装普通 / 2=精良及以下 / 3=全部（含传说） | L258 / L260 |
| `slots` 数量 | int | 1-3【工程补白 SOCK-01】 | 单件装备槽位数量定稿未写死，默认 1-3 个，内容包可配 | L257 / SOCK-01 |

### 4.3 珠实例堆叠键

- **装饰珠实例堆叠键 = `ID + 品质档 + 特性集`**（同键可堆叠，键变则分堆；升阶使品质档变化 → 堆叠键变更）（BEL-15 / STO-02 / L401）。
- 落点：`ItemInstance`（data/item.py L20-37，含 `quality`/`traits` 冻结语义）+ repository `_item_from_dict`（repository.py L176，未知键多忽略、round-trip 兼容）。
- 珠实例携带 `bind_on_pickup=true`（BEL-08 绑定默认，防交易刷珠）【工程补白：绑定=拾取/产出即绑定，内容包可配关闭】。

---

## 五、settings.json alchemy 段全字段表

> 依据：炼金定稿 §10.6 L408-426 + 细化_2c4b/2c4c §2.3 + m8_batch_plan 批0B + 用户拍板。
> 消费模式：`AlchemyConfig.from_settings(settings)` 容错解析（仿 `DeathPenaltyConfig.from_settings`，battle_boundary L349）+ 校验器 `_check_settings_alchemy` 硬拦（【摸底】§7.2）。**段未登记前未知字段默认放行，加校验规则必须 field_meta.SETTINGS_FIELDS 登记 + validator 专项（§六）**。

| 键 | 类型 | 默认值 | 可配 | 语义 / 校验要点 | 引用 |
|---|---|---|---|---|---|
| `mode` | enum | `"full"` | 可配 | full 三层漏斗 / simple 仅合成层（无炼金/深度/职业等级/特性/能量条）/ off 关闭；枚举硬拦 | L410 / EDGE-04 |
| `quality_tiers` | obj | `{common:0-39, uncommon:40-59, rare:60-79, legendary:80-100}` | 可配（档位数 3/5/7、0=不限制） | 品质档位注册表；**键集 common/uncommon/rare/legendary（拍板②）**；区间单调覆盖 0-100 不重叠；**档位数/区间合法性只提示不拦截**（对齐 L411）；0-100 为品质分计算口径 | L411 / QLT-02/03/05 |
| `quality_coef` | obj | `{common:0.8, uncommon:1.0, rare:1.2, legendary:1.5}` | 可配（数值不变） | 档位系数（成品效果 = 基准 × 系数）；键随档位派生、数值 >0 | L412 / QLT-04 |
| `chain_map` | obj | `{1:1,2:2,3:3,4:4,5:5,6:6}` | 可配 | 链式投料段数→效果等级 | L413 / QLT-13 |
| `pp_cost` | obj | `{normal:1, super:2}` | 可配 | 特性继承 PP 消耗（rarity 计价唯一依据） | L414 / TSC-14 |
| `pp_refresh` | str | `"会话重置"` | 可配 | PP 重置时机（挂起/恢复不清零，/确认 结算后随会话重置） | L415 / INH-09 |
| `energy_enabled` | bool | `false` | 可配 | 能量条开关（**R-08：默认关**）；关闭时 /炼金 /深度炼金 /即时调合 不扣能量、不显示上限、无「能量不足」模板；**优先级：本键为准，proficiency.json energy 段作默认兜底**（双开关不打架，P2-4） | R-08 / L416 注 |
| `energy_max` | obj | `{见习:5,正式:8,精通:10,专家:12,大师:15,宗师:18,王:20}` | 可配 | 能量上限随职业等级 7 档 | L416 |
| `energy_regen_sec` | int | `1800` | 可配 | 每 30 分钟回 1 格（现实时间） | L417 / LVL-09 |
| `energy_regen_sec_safe` | int | `900` | 可配 | 休整/安全区恢复加速（安全区回 1 格时长；细化_2c5a LVL-09「休整/安全区可加速」落点）【工程补白键】 | LVL-09 |
| `decompose_rate` | obj | `{正式:0.4,精通:0.45,专家:0.5,大师:0.55,宗师:0.6,王:0.65}` | 可配 | 分解回收率 6 档（称号档跳变、只升不降）；材料返还乘数（向下取整）；见习无分解（表自正式起） | L418 / DEC-02/05 |
| `catalyst_unlock_tier` | enum | `"expert"` | 可配 | 触媒默认解锁=专家（**R-07**）；枚举 ∈ 职业等级（见习/正式/精通/专家/大师/宗师/王）硬拦 | R-07 |
| `catalyst_consume` | bool | `true` | 可配 | 触媒是否消耗（/确认 时全量复核） | 批5B |
| `gem.分解` | obj | `{common:1, uncommon:3, rare:8, legendary:20}` | 可配 | 分解宝石基础值=**平铺**（不乘回收率，**拍板①**）；键=quality_tiers 档位（键名拍板②）；键枚举合法+数值非负硬拦；**产出公式可配置**——键名 `gem.decompose_formula: "flat"|"rate"`（默认 `"flat"` 拍板①；rate=⌊基础值×回收率⌋，回收率取 decompose_rate 档位）【工程补白键】 | L419 / DEC-04 |
| `gem.复制` | float | `0.2` | 可配 | 复制费率=⌊配方 cost.coins×20%⌋ 宝石（基准=cost.coins，**拍板④**）+ 可配额外消耗（默认 0，**拍板④**）；数值非负硬拦 | L419 / L225 / DUP-03 |
| `gem.成品合成` | int | `10` | 可配 | 成品合成单次费用（=upgrade 实例 cost.gem） | L419 / L226 |
| `gem.配方合成` | int | `5` | 可配 | 配方合成单次费用 | L419 / L227 |
| `gem.特性合成` | int | `20` | 可配 | 特性合成单次费用 | L419 / L229 |
| `gem.珠升阶` | int | `10` | 可配 | 珠三合一升阶单次费用 | L419 / L230 |
| `gem_diminish` | array | `[{n:2,mult:0.5},{n:3,mult:0.25}]` | 可配（空/0=无递减） | 珠同名递减表驱动（第 2 颗 ×50%、第 3 颗 ×25%；无第 4 档）；n≥2 递增、mult∈(0,1] | L420 / BEL-10 |
| `synth_exp` | str | `"配方等级×1"` | 可配 | 合成熟练经验公式 | L421 / EXP-03 |
| `sp_per_level` | int | `1` | 可配 | 每升 1 级 SP 点数（≥0；本文档级配置与 proficiency.json 同名键并存，proficiency.json 优先） | L422 / SP-01 |
| `sp_panel` | array | 4 项：品质上限+10 / 投入次数+1 / 采集量+1 / 连锁上限+1（前两项 repeatable:true） | 可配 | SP 面板解锁项（值/可多次可配）；六类全量由 proficiency.json sp_panel 承载，settings 提供默认兜底 | L423 / SP-03 |
| `战斗道具` | obj | `{强度公式:"技能×(1+0.4×冷却数)", 珠触发上限:3}` | 可配 | 战斗道具强度公式（字符串）+ 珠特效触发上限 ≤3 次/场（正整数） | L424 / BEL-11 |
| `战斗即时调合` | obj | `{auto_use:true, per_battle_limit:1}` | 可配 | 产出自动使用/入包；限 1 次/场（入战斗快照 battle_alchemy_used） | L425 |
| `max_qty` | int | `2147483647` | 可配 | 合成/复制批量数量上限（int32 max，**拍板⑤**）；超限「最多一次使用 N 个」**提示不拦截** | 拍板⑤ / 分隔符 L73 |
| `job_tier_map` | map | 见习 1-5 … 王 51+ | 可配 | 称号→配方等级区间（**主落点 settings**，proficiency.json 可选覆盖）；称号引用职业等级枚举、区间单调 | L34 / LVL-06 |

> **段默认值兜底**：settings 缺 alchemy 段时按上表默认值兜底（对齐 L506「机制过多配置负担 → 默认值兜底 + 模块开关」）；`mode:off` 时整段不生效。

---

## 六、校验器四件套（field_meta / loader / validator / manifest）

> 依据：【摸底】§4.1~4.4（真实接口）+ m8_batch_plan 关键决策 #3。四件套顺序：**field_meta 登记 → loader._KIND_FOR_MODULE → validator 专项挂接 → manifest 声明**（traits 已有骨架，只差数据文件；recipe/proficiency 全新增）。

### 6.1 四件套接线点（真实定义）

| # | 件 | 现有状态 | M8 动作 | 真实接口（【摸底】/已实核） |
|---|---|---|---|---|
| 1 | **field_meta 登记** | traits 已登记（L326-332 + L418）；recipe/proficiency 未登记；SETTINGS_FIELDS 仅 currencies/death_penalty（L206-209） | ① traits_fields 增量扩展 rarity/group/repeatable/source 四键；② 新增 `recipe` ModuleMeta（entry_type="list", fields=recipe_fields, kind="recipe", namespace="recipe_lib"）；③ 新增 `proficiency` ModuleMeta（entry_type="list", fields=proficiency_fields, kind="proficiency", namespace="proficiency_lib"）；④ SETTINGS_FIELDS 加 `alchemy` 段 | `default_field_meta_table() -> FieldMetaTable`（field_meta.py L441）；`ModuleMeta(entry_type, fields, kind, namespace, key_regex, value_meta, chain_field, mutex_field)`；命名空间表 L36-50 |
| 2 | **loader._KIND_FOR_MODULE** | traits→trait（loader.py L158）；recipe/proficiency 未登记 | 登记 `"recipe": "recipe"`、`"proficiency": "proficiency"`（按现有模式：模块名→注册表 kind 同名；DEF_CLASSES 缺省回退 BaseDef） | `_KIND_FOR_MODULE: Mapping[str,str]`（loader.py L150-172）；`_register_def` 按 `kind` 进 `registry.tables[kind]`（L131/L138）；`FIXED_REGISTER_ORDER`（L46）不动（recipe/proficiency 非前置依赖） |
| 3 | **validator 专项挂接** | 鸭子类型模式：validate_npcs/validate_shops/validate_quests（validator.py L531-538）；settings 专项 `_check_settings_1g4`（L1329，settings 分支 L559） | ① `validate_recipes(modules, report) -> None`；② `validate_traits(modules, report) -> None`（**现不存在**，需新建）；③ `validate_proficiency(modules, report) -> None`；④ `_check_settings_alchemy(module_name, data)`（挂 settings 分支 L559 旁） | `check_pack(modules, meta) -> ValidationReport`（_Checker.run L383）；`_check_module(module_name)`（L465）按 `module_name` 分支派发；**鸭子类型签名**：`validate_xxx(modules: Mapping[str,object], report: object) -> None`，用 `report._err/_warn/_note` 收集（shop_models._emit L478）；泛型 `_check_entry` 随后继续跑（双保险）；`_check_chain_cycle`（L1692，成环硬拦） |
| 4 | **manifest 声明** | 无内容包声明 traits/recipe/proficiency（【摸底】§4.4） | test_demo/legal 内容包 modules 数组加 `recipe`/`traits`/`proficiency`；settings.json 加 alchemy 段 | manifest 必填 name/version/schema_version/modules（field_meta L218-224）；声明才加载、声明缺失 Y-6 继续；`check_register_table_consistency`（loader L175）——`FIXED_REGISTER_ORDER ∪ _KIND_FOR_MODULE ⊆ field_meta 模块表`，**新增模块未接校验器会被拦截（双向保障）** |

> **挂接方式铁律**：M8 专项校验器一律走 **鸭子类型模式** `validate_xxx(self._modules, self)`（validator.py L531-533），与 dungeon 的「ValidationReport 合并模式」区分（L515-519 桥接回填为既有特例，M8 不引入新合并模式）。

### 6.2 校验器规则清单（59 条）

> 级别：**红拦**=PackLoadError 阻断加载；**提示（W/N）**=只提示不拦截。编号前缀：REC（recipe）/ TRT（traits）/ PRF（proficiency）/ ALC（settings.alchemy）。

#### validate_recipes（REC-01 ~ REC-16，16 条）

| # | 规则 | 级别 | 依据 |
|---|---|---|---|
| REC-01 | `kind` 枚举 ∈ {craft, combine, upgrade} | 红拦 | 定稿 L354 |
| REC-02 | `level` ∈ [1,99] 整数 | 红拦 | L354 |
| REC-03 | `materials[{id,count}]`：id 引用 items 存在、count ≥1 | 红拦 | L354 |
| REC-04 | `cost.coins`/`cost.gem` 非负整数（gem 可缺省=0） | 红拦 | L355 |
| REC-05 | `element_req`：元素 ∈ 8 元素注册表（地水火风雷晶月无）、阈值数值 ≥0、效果=原子动作 ID 引用存在（**8 元素注册表归属批0 在 formula.json element 表登记、field_meta 补登记，否则本红拦落空**） | 红拦 | L355/L387 |
| REC-06 | `effects`：原子动作 ID 引用存在（效果注册表） | 红拦 | L356 / TSC-02 |
| REC-07 | `catalyst[]`：引用 items `type=触媒` 存在（未注册仅提示【批5B 口径】→ 引用不存在红拦） | 红拦 | L356 / L492 |
| REC-08 | `combine_from[]`：引用 recipe 存在（配方合成表 2 输入+1 输出+条件） | 红拦 | L357 / L390 |
| REC-09 | `evolve_to.id` 引用 recipe 存在；`condition.count` ≥1；`condition.source` 枚举合法 | 红拦 | L357 / L200 |
| REC-10 | **进化线无环**：evolve_to 链成环 → 红拦（复用 `_check_chain_cycle` 模式） | 红拦 | L494 / R-5 |
| REC-11 | `kind=upgrade` 实例：inputs 引用 items 存在、output 引用 items 存在、output.count=1 | 红拦 | L365-368 |
| REC-12 | `traits_inherit` ∈ 1-3（默认 1，可配上限）；**字段范围 1-3（定稿 L356），继承位总上限 1-6（INH-06）由 SP/等级扩展承载** | 提示 | L356 / INH-06 |
| REC-13 | `slots` ∈ 2-10（默认 4） | 提示 | L355 |
| REC-14 | `synth_allowed` 布尔；深度配方设 false→提示「将绕过深度炼金玩法」不阻断 | 提示 | L505 / 批2A |
| REC-15 | `master_only` 布尔（值类型） | 提示 | L357 |
| REC-16 | 配方 `id` 命名禁保留字符 `* , = +` 空格【工程补白：对齐分隔符 L12/L58】 | 红拦 | L12 / L58 |

#### validate_traits（TRT-01 ~ TRT-09，9 条）

| # | 规则 | 级别 | 依据 |
|---|---|---|---|
| TRT-01 | `id` 命名禁保留字符 `* , = +` 空格【工程补白：TSC-04】 | 红拦 | L12 / L58 |
| TRT-02 | `rarity` 枚举 ∈ {normal, super} | 红拦 | L373 |
| TRT-03 | `effects`：L0 原子动作 ID 引用存在（效果注册表，热重载自动迁移） | 红拦 | L374 / 【效果】L448 |
| TRT-04 | **互斥组校验**：group 组内成员存在性 / 同特性不登记进多个互斥组 / 组内自引用 | 红拦 | L375 / L492 / INH-13 |
| TRT-05 | `repeatable` 布尔（默认 false） | 提示 | L375 |
| TRT-06 | `source` 枚举 ∈ {素材, 成品, 金色素材} | 红拦 | L376 |
| TRT-07 | `name` 非空 | 红拦 | L138 |
| TRT-08 | 快照/存档引用冗余 ID+名称：删配置降级不报错（引用失效兜底） | 提示 | L511 / 【效果】L462 |
| TRT-09 | `rarity=super` 第 4 位独占 `gold_slot_exclusive` 可配项合法（布尔） | 提示 | L201 / TSC-12 |

#### validate_proficiency（PRF-01 ~ PRF-10，10 条）

| # | 规则 | 级别 | 依据 |
|---|---|---|---|
| PRF-01 | `id` 引用 jobs.json 职业存在 | 红拦 | 【熟练度】L192 |
| PRF-02 | `tier_names` 长度 ≥2（**最小 2、默认 7**）、**内容包可改**、与 `job_rank_levels` 一一对应 | 红拦 | L169 / L16 |
| PRF-03 | `job_rank_levels` 单调递增、首项=0 | 红拦 | L16 / L31 |
| PRF-04 | `exp_sources` 子键 ∈ {craft, gather, combat}、值 ≥0 | 红拦 | L170 |
| PRF-05 | `sp_per_level` 非负整数 | 红拦 | L171 |
| PRF-06 | `sp_panel` 项 id 唯一、cost ≥1、repeatable 布尔、max_repeat ≥1 | 提示 | L172 / SP-05 |
| PRF-07 | `energy.enabled` 布尔；enabled=true 时 `max_by_tier` 长度与 tier_names 一致、`regen_sec` ≥0 | 提示 | L173 / 【熟练度】L193 |
| PRF-08 | `job_tier_map`：称号引用 tier_names 存在、区间 [lo,hi] 单调（默认继承 settings） | 红拦 | L174 / LVL-06 |
| PRF-09 | `titles` source 枚举 ∈ {king, contest, achievement, custom} | 提示 | L175 |
| PRF-10 | source=king 王称号条目自动生成（id=职业 ID，不手写配置）；手写 king 条目→提示 | 提示 | L141 / TTL-03 |

#### _check_settings_alchemy（ALC-01 ~ ALC-24，24 条）

| # | 规则 | 级别 | 依据 |
|---|---|---|---|
| ALC-01 | `mode` 枚举 ∈ {full, simple, off}（默认 full） | 红拦 | L410 |
| ALC-02 | `quality_tiers` 区间单调覆盖 0-100 不重叠；**档位数 3/5/7、0=不限制 → 只提示不拦截** | 提示 | L411 / QLT-03 |
| ALC-03 | `quality_coef` 键随档位派生、数值 >0 | 提示 | L412 |
| ALC-04 | `chain_map` 值 ∈ 1-6 整数 | 提示 | L413 |
| ALC-05 | `pp_cost` {normal, super} 正整数 | 红拦 | L414 |
| ALC-06 | `pp_refresh` 枚举（"会话重置"） | 提示 | L415 |
| ALC-07 | `energy_enabled` 布尔（默认 false，R-08） | 红拦 | R-08 |
| ALC-08 | `energy_max` 7 档非负整数（见习 5 … 王 20） | 提示 | L416 |
| ALC-09 | `energy_regen_sec`/`energy_regen_sec_safe` 非负整数 | 提示 | L417 / LVL-09 |
| ALC-10 | `decompose_rate` 6 档 ratio ∈ (0,1] 单调（见习无分解→表自正式起） | 红拦 | L418 / DEC-05 |
| ALC-11 | `catalyst_unlock_tier` ∈ 职业等级枚举（默认 expert，R-07） | 红拦 | R-07 |
| ALC-12 | `catalyst_consume` 布尔（默认 true） | 红拦 | 批5B |
| ALC-13 | `gem.分解` 键 ∈ {common, uncommon, rare, legendary} + 数值非负（键名拍板②） | 红拦 | L419 / 拍板② |
| ALC-14 | `gem.{复制/成品合成/配方合成/特性合成/珠升阶}` 数值非负（复制可浮点） | 红拦 | L419 |
| ALC-15 | gem 段**不存在 `gem.秘钥` 键**（已砍）；遗留引用 → W 级提示 | 提示 | L419 注 / TC-23 |
| ALC-16 | `gem_diminish` [{n,mult}]：n ≥2 递增、mult ∈ (0,1] | 提示 | L420 |
| ALC-17 | `synth_exp` 字符串（"配方等级×1"） | 提示 | L421 |
| ALC-18 | `sp_per_level` 非负整数 + `sp_panel` 4 项默认 + repeatable 布尔 | 提示 | L422-423 |
| ALC-19 | `战斗道具`：强度公式字符串 + 珠触发上限 ≥1 正整数（默认 3） | 提示 | L424 |
| ALC-20 | `战斗即时调合`.auto_use 布尔（默认 true） | 红拦（布尔） | L425 |
| ALC-20′ | `战斗即时调合`.per_battle_limit 正整数 ≥1（默认 1） | 红拦 | L425 |
| ALC-21 | `max_qty` 正整数（默认 2147483647，**拍板⑤**） | 红拦 | 拍板⑤ |
| ALC-22 | 宝石产出公式可配项合法（默认平铺，**拍板①**） | 提示 | 拍板① / DEC-04 |
| ALC-23 | 复制额外消耗可配项 `gem.复制额外`（=`copy_extra_cost`）非负 int、默认 0（**拍板④**） | 提示 | 拍板④ / DUP-03 |
| ALC-24 | `job_tier_map`：称号引用职业等级枚举、区间单调（主落点 settings） | 红拦 | L34 / LVL-06 |

> **校验器规则合计：REC 16 + TRT 9 + PRF 10 + ALC 24 = 59 条**（ALC-20 拆 auto_use 布尔 + per_battle_limit ≥1 两项，独立级别）。

---

## 七、SQLite 扩展（无新表）

> 依据：【摸底】§1.1~1.4（真实 schema）+ 定稿 §10.5 L395-406 + m8_batch_plan 关键决策 #1/#4/#5。

- **无新表**：`sessions` 已含 `session_type IN ('battle','alchemy','challenge_alchemy')`（schema.py L24）——调合/深度会话直接用，不改表；`sessions.player_qid` 主键 = 单玩家 1 会话互斥；`version` 列（默认 1）= 调合会话 version 幂等落点。
- **currencies dict 加 `gem` 键**（schema.py L39 + data/player.py L87 多币种 dict；shop.py L150 `_CURRENCY_NAME_FALLBACK` 已有 `"gem":"宝石"` 映射）——宝石不入背包物品栈、不占格子（SRC-05）。
- **player proficiency dict 形态**（不加 Player dataclass 字段；levelup.py L117-128 既有模式；sp_earned/sp_used 双计 + sp_used ≤ sp_earned 校验）。

### 7.1 persistent_state 新键空间清单（自由 JSON 桶，data/player.py L93）

| 键 | 形态 | 承接 | 批次 |
|---|---|---|---|
| `energy.<job_id>` | 能量条当前值（或折 proficiency.<job_id>.energy_current，细化_2c5a §5.3 落 proficiency dict） | 批4A / 批3B | 批3B/4A |
| `farming_plots` | 种植地块：种子+种植时间+收获时间（定时收获默认 4 小时可配） | 批10A | 批10A |
| `assistant_state` | 代工助手：状态+产出队列（后台定时产出→上线收取） | 批10B | 批10B |
| `registed_templates` | /登记 模板：登记物品 ID+成本快照（DUP-06；换包同 ID 保留/红名） | 批7C | 批7C |
| `player_recipe_unlocks` | 玩家级配方解锁表（配方ID+解锁来源+条件；SQLite 或 persistent_state 二选一，m8_batch_plan 批2B） | 批2B/7C | 批2B |
| `battle_alchemy_used` | **落战斗快照顶层键**（sessions.payload_json，非 persistent_state；中断恢复不清零、战斗结束清零；批9A） | 批9A | 批9A |

> 其余既有键（checkin/shop/rest/time/dummy_log…）不动；新增键空间全部经「缺补默认/多忽略」编解码（MIG-1）。

---

## 八、IF 接口清单（真实签名 + 调用方 + 实现批次）

> 签名均来自【摸底】+ 已实核代码（非凭印象）。实现批次编号 = m8_batch_plan §二。

| # | 接口 | 真实签名 / 定义 | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF01 | `Registry.resolve` | `resolve(id, kind) -> AnyDef`（content/registry.py L82） | 合成引擎/炼金会话/继承引擎按 kind=recipe/trait/item 解析 | 批0A/2A |
| IF02 | `Registry.resolve_name` | `resolve_name(id: str) -> Optional[str]`（content/registry.py L86；ID→冗余显示名，热重载降级用） | 热重载旧局快照显示名降级 | 批0A/4B |
| IF03 | `Registry.all_ids` | `all_ids(kind) -> Tuple[str,...]` | 校验器 collect_ids / 图鉴点亮 / 王称号条件 | 批0A/8B |
| IF04 | `Registry.build` / `from_snapshot` | `build(...)`（L163）/ `from_snapshot(...)`（L148） | 热重载世代重绑定（recipe/traits/proficiency 变更→watcher 重绑定） | 批11B |
| IF05 | `loader._KIND_FOR_MODULE` | 登记 `"recipe":"recipe"`、`"proficiency":"proficiency"`（loader.py L150-172） | 加载管线 B 段（recipe/proficiency 进注册表） | 批0A |
| IF06 | `field_meta.default_field_meta_table` | `() -> FieldMetaTable`（field_meta.py L441）；recipe/proficiency ModuleMeta 新增 + traits_fields 扩展（L326-332）+ SETTINGS_FIELDS 加 alchemy 段（L206-209） | check_pack 泛型字段校验 | 批0A/0B |
| IF07 | `check_pack` | `check_pack(modules, meta) -> ValidationReport`（validator.py _Checker.run L383） | 加载管线 C 段（任一红拦抛 PackLoadError） | 批0B |
| IF08 | `_check_module` 专项派发 | `_check_module(module_name)`（L465）按模块名分支；鸭子类型 `validate_xxx(modules, report) -> None` | validate_recipes/validate_traits/validate_proficiency + `_check_settings_alchemy(module_name, data)`（settings 分支 L559 旁） | 批0A/0B |
| IF09 | manifest 声明 | modules 数组加 recipe/traits/proficiency + settings alchemy 段（demo_full/manifest.json 模式） | 加载管线 A 段（声明才加载） | 批0C/12B |
| IF10 | `InventoryEngine.add_item` | `add_item(player, item, count=1) -> dict`（core/inventory.py L183；{ok,added,rows,…}） | 合成/炼金结算/复制产出/分解返还/种植收获 入包 | 批2A/6B/10A |
| IF11 | `InventoryEngine.remove_item` | `remove_item(player, item_id, count=1) -> dict`（L254；{ok,removed} / bound 拒移） | 合成材料扣减/投料消耗/分解销毁/珠升阶三珠 | 批2A/4B/7B |
| IF12 | `InventoryEngine.count` | `count(player, item_id) -> int`（L308） | 原子校验材料持有（材料+金币全量满足否则全拒） | 批2A/4B |
| IF13 | `Repository.save_player` / `load_player` | `async save_player(self, player) -> None`（repository.py L473）/ `async load_player(self, qid) -> Optional[Player]`（L442） | 引擎结算后落盘（分解/合成/调合确认） | 批6B/6A |
| IF14 | `Repository.load_session` | `async load_session(self, qid) -> Optional[Tuple[...]]`（L563） | 调合会话恢复（payload 含配方ID/材料链/连锁/特性/触媒/PP/步骤/version） | 批3B |
| IF15 | `RepoTransaction.upsert_session` / `delete_session` / `Repository.tx` | `upsert_session(self, session: SessionRow)`（L887，ON CONFLICT(player_qid) DO UPDATE）/ `delete_session(self, qid)`（L904）/ `tx()`（L412） | 调合会话持久化 + 终态删除（同事务） | 批3A/3B |
| IF16 | `RepoTransaction.write_idem_key` / `idem_exists` | `write_idem_key(self, key: IdemKey)`（L922）/ `idem_exists(self, key: IdemKey) -> bool`（L932） | /确认 /放弃 /分解 幂等（同事务，IDEM-2；ATO-03） | 批3B/6B |
| IF17 | **reward 发放器（gem 入账）** | `dispatch_reward(entries: Any, ctx: Optional[Mapping[str, Any]]=None) -> dict`（core/reward.py L308；ctx 就地改写 currencies/exp/reputation_state；tx_id+ledger 幂等闸；返回 {ok, granted, skipped, idempotent}） | **统一 reward 管线（T48）**：分解宝石/挑战奖励/loot.json gem 列/品评会冠军 全部走此管线；ctx["currencies"]["gem"] 入账 | 批6B |
| IF18 | `settle_exit_idempotent` | `async settle_exit_idempotent(*, session, settlement_kind, message_id, repository) -> bool`（world/battle_boundary.py L821；delete_session+write_idem_key 同事务） | 调合会话 /放弃 /确认 终态结算**仿照此模式**（幂等键 command="settle:{kind}"） | 批3A |
| IF19 | `SessionManager` 五方法 | `acquire/release/get_active/suspend/restore`（world/session.py L24-40，现为 NotImplementedError 占位，**M8 实装**）；`SessionConflictError`（L20） | 调合会话互斥（私聊+多群全局） | 批3A |
| IF20 | `BattleEngine.to_snapshot` | `to_snapshot(boundary=None) -> Dict[str, Any]`（core/battle.py L1740） | `battle_alchemy_used` 挂返回 dict **顶层键**（中断恢复不清零、战斗结束清零） | 批9A |
| IF21 | condition/formula 变量 | `condition_engine` `[熟练度:{T}]`（L161）/ `formula_engine` `[宝石]`（L218）、`熟练度`（L246） | 熟练度准入条件 / 宝石·熟练度公式变量 | 批1A/9B |
| IF22 | `AlchemyConfig.from_settings` | 容错解析类方法（仿 `DeathPenaltyConfig.from_settings`，battle_boundary L349 模式） | 引擎侧读 settings.alchemy 段（校验器硬拦兜底） | 批0B |
| IF23 | `ItemInstance` | dataclass（data/item.py L20-37）：`item_id/name/count/quality/bound/stack_max/slot/stats_bonus/traits/cooldown_until`（traits 冻结 tuple） | 炼金成品/装饰珠实例构造（品质/特性/绑定直接携带） | 批6A/7A |
| IF24 | `EquipmentSlot.gems` | `gems: Tuple[str, ...] = ()`（data/player.py L69） | 装饰珠镶嵌落点（/镶嵌 /拆珠） | 批7A |
| IF25 | 珠实例堆叠键 | ID+品质档+特性集（repository `_item_from_dict` L176 兼容 round-trip） | /镶嵌 堆叠合并 / 珠升阶键变更 | 批7A/7B |

> **IF02 补注【工程补白·需新增】**：/合成 /投料 /继承 参数按 name 匹配在真实代码**无承载接口**（真实 Registry 仅 `resolve(id, kind)` 按 ID 查表、`resolve_name(id)` 返回显示名）。需新增 `Registry.resolve_by_name(name, kind) -> Optional[AnyDef]`（批11 实现时建 name→id 索引），**或**改用 `resolve(id, kind)` + `all_ids(kind)` 遍历方案。

---

## 九、验收 TC 矩阵（映射到实现批次 / 校验器规则）

> 依据：细化_2c4b TC-01~25 + 细化_2c4c TC-01~30。批号 = m8_batch_plan §二；规则号 = §六 6.2。

### 9.1 细化_2c4b（TC-01 ~ TC-25，宝石货币经济）

| TC | 场景摘要 | 实现批次 | 关联校验器规则 / 数据字段 |
|---|---|---|---|
| TC-01 | /分解 史诗炼金防具 → 宝石+8 + 材料返还（SRC-01） | 批6B | ALC-13（gem.分解键）/ ALC-22（平铺公式）|
| TC-02 | /挑战 成功（连锁≥5 且刻度≥2）→ 品质上限+10 + 宝石奖励；失败退 50% 材料、宝石零 | 批8B | ALC-22 / reward 管线 IF17 |
| TC-03 | loot.json `gem:{min,max}` 掉落 → 直接入货币槽 | 批6B | IF17 / currencies.gem |
| TC-04 | 品评会冠军 → 称号+宝石+展示（分账结算） | 批8B | IF17 / ARB-00 |
| TC-05 | 存档 wallet.gem +500 重载精确恢复、无负数 | 批6B | currencies dict（§七） |
| TC-06 | /复制 未登记拒绝；登记后 扣 ⌊cost.coins×20%⌋×10+材料 → 标准版×10；超限提示不拦 | 批7C | ALC-14/ALC-21/ALC-23 / DUP-02/05 |
| TC-07 | 宝石不足 → 原子拒绝整单（SINK-00） | 批7C | IF10/11 原子口径 |
| TC-08 | /成品合成 炼狱爆弹·改×2 → 灭世爆弹（gem10+材料） | 批7C | REC-11（upgrade 实例） |
| TC-09 | /配方合成 A+B 已学 → 解锁新配方（gem5） | 批7C | REC-08（combine_from） |
| TC-10 | /特性合成 同系 → 更高位特性（gem20+材料） | 批7C | TRT-04（互斥组/同系） |
| TC-11 | 珠升阶累计 9 普通→精良→史诗 = 4 次×10=40 宝石 | 批7B | REC-11 / BEL-12/13 |
| TC-12 | /进化 低阶炼金产出 N 次 → 目标配方永久解锁（特性不继承） | 批8A | REC-09/10（evolve_to/无环） |
| TC-13 | 温室（大师）复制素材 耗宝石或金币二选一 | 批10A | ALC-14 / ARB-00 |
| TC-14 | 轴1：商店买料→/合成 标准版→/分解 → 拒绝（标准版默认不可分解） | 批6B | DEC-02（对象限制） |
| TC-15 | 轴1：分解非炼金产出 → 拒绝 | 批6B | DEC-02 |
| TC-16 | 轴2：王档分解×复制 20% 循环 3 轮 → 每轮净资产单调递减 | 批6B | ALC-10/ALC-14 |
| TC-17 | 轴3：金币↔宝石直换/卖店/声望互换 → 全部无入口 | 批11A | ALC-15（无 gem.秘钥） |
| TC-18 | 轴4：复制-分解回炉-再复制 每圈被双重计费；拆珠不返宝石 | 批6B/7B | BEL-11/ALC-21 |
| TC-19 | 六称号分解 → 回收率 0.4→0.65 逐档跳变 | 批6B | ALC-10 / DEC-05 |
| TC-20 | 配方 {水结晶×3,草药×2} 回收率 0.5 → 1+1（向下取整） | 批6B | ALC-10 / DEC-03 |
| TC-21 | 分解 精良（uncommon）成品 → 宝石+3（平铺） | 批6B | ALC-13（键名拍板②） |
| TC-22 | 传说分解（王档）→ 宝石+20 + 材料×0.65；全物入料并行不发宝石 | 批6B | ALC-10/ALC-13 / DEC-06 |
| TC-23 | settings gem 段改值即时生效；无 gem.秘钥 键（W 级提示） | 批0B | ALC-13/14/15 |
| TC-24 | mode=simple → 宝石经济整体关闭 | 批0B | ALC-01 / EDGE-04 |
| TC-25 | 回归全量（TC-01~24 + 门槛一致） | 批12A | 全量 |

### 9.2 细化_2c4c（TC-01 ~ TC-30，珠与合成指令）

| TC | 场景摘要 | 实现批次 | 关联校验器规则 / 数据字段 |
|---|---|---|---|
| TC-01 | 3×普通攻击珠+宝石10 → 精良（数值不变） | 批7B | REC-11 / BEL-12 |
| TC-02 | 全链路 27 普通→1 传说 = 13 次×10=130 宝石 | 批7B | REC-11 / BEL-12/13 |
| TC-03 | 禁跳级：组合表预置「普通→传说」→ 拒绝（链式相邻） | 批7B | REC-11 / BEL-13 |
| TC-04 | 混档/混 ID → 拒绝（须三同档同 ID） | 批7B | REC-11 / BEL-14 |
| TC-05 | 宝石不足 → 拒绝「宝石不足」，珠与宝石不消耗 | 批7B | SINK-00 / IF10/11 |
| TC-06 | 任意炼金职业 → /珠升阶 可执行（**无职业硬门槛，拍板③**） | 批7B | BEL-12 / SOCK-02 |
| TC-07 | 未登记 /复制 → 拒绝「未登记复制」；/登记 后可执行 | 批7C | DUP-02 / §七 persistent_state |
| TC-08 | /复制 ×10：⌊cost.coins×20%⌋+额外消耗+材料×10 → 标准版×10 | 批7C | ALC-14/ALC-23 / DUP-03 |
| TC-09 | /登记 炼金品质成品 → 拒绝（仅标准版可复制） | 批7C | DUP-04 |
| TC-10 | 材料/宝石不足 → 全拒 + 差异提示 | 批7C | DUP-05 / IF10/11/12 |
| TC-11 | 复制 ×999999999 → 超限提示不拦（**拍板⑤**），仍执行 | 批7C | ALC-21 |
| TC-12 | 宗师 /成品合成 → 灭世爆弹（组合表目标，gem10+材料） | 批7C | REC-11 / CMB-02 |
| TC-13 | 等级不足/宝石不足 → 拒绝，输入成品不消耗 | 批7C | REC-11 / SINK-00 |
| TC-14 | 专家 /配方合成 已学 → 解锁预置新配方（gem5）；图鉴点亮 | 批7C | REC-08 / CMB-03 |
| TC-15 | 未学配方 → 拒绝（两配方须已学） | 批7C | REC-08 |
| TC-16 | 正式/精通 → /配方合成 拒绝（专家解锁） | 批7C | LVL-07 门槛 |
| TC-17 | 宗师 /特性合成 攻击+15%+10% → 攻击+25%（gem20+材料） | 批7C | TRT-04 / CMB-04 |
| TC-18 | 不同系 → 拒绝；重复特性（同 ID 两份）→ 拒绝 | 批7C | TRT-04 / CMB-05 |
| TC-19 | 专家 → /特性合成 拒绝（宗师解锁） | 批7C | LVL-07 门槛 |
| TC-20 | 长剑（2 级槽）/镶嵌 精良珠 → 成功；短剑（1 级槽）普通珠 → 成功 | 批7A | slots.json slot_level / SOCK-02 |
| TC-21 | 2 级槽 /镶嵌 传说珠 → 拒绝（需 3 级槽） | 批7A | SOCK-02 |
| TC-22 | /拆珠 → 珠无损返还（原档原特性），槽位空闲 | 批7A | SOCK-03 / BEL-15 |
| TC-23 | 战斗中 /镶嵌 /拆珠 → 拒绝（战斗中不可插拔） | 批9B | BEL-09 |
| TC-24 | 3 颗同名珠 100%/50%/25% 递减；第 4 次同珠特效不触发（≤3 次/场） | 批7B/9B | ALC-16（gem_diminish）/ ALC-19 / IF20 |
| TC-25 | 大师+深度会话 /镶核心 龙晶核 → 品质上限+20、火适配 | 批8A | COR-01/02 / traits 并入 |
| TC-26 | 无会话/非大师 → 拒绝「核心不匹配」 | 批8A | COR-01 |
| TC-27 | 宗师 /分解 火焰弹（火晶石×4, 精良）→ 火晶石×2 + 宝石×3（平铺） | 批6B | ALC-10/ALC-13 / DEC-03/04 |
| TC-28 | /分解 标准版 → 默认拒绝（防商店套宝石） | 批6B | DEC-02 |
| TC-29 | 六称号下 /分解 → 返还量 40%→65% 逐档上升 | 批6B | ALC-10 / DEC-05 |
| TC-30 | 见习 /分解 → 拒绝；非炼金产出 → 拒绝 | 批6B | DEC-01/02 |

---

## 十、铁律与拍板（本域专属）

| # | 铁律 / 拍板 | 强制内容 | 落点 |
|---|---|---|---|
| B1 | **键集（拍板②）** | 品质档键**只允许** `common/uncommon/rare/legendary`（中文 普通/精良/史诗/传说）；`quality_tiers`/`quality_coef`/`gem.分解` 全部用此键集；`fine`/`优秀`/`稀有` 旧名**废弃**；档位数可配 3/5/7、0=不限制 | §一/§二/§五/ALC-02/ALC-13 |
| B2 | **分解宝石平铺（拍板①）** | 分解宝石实收 = 平铺基础值（普通1/精良3/史诗8/传说20，**不乘回收率**）+ 产出公式可配置（默认平铺）；低阶分解关闭/减半为内容包可配门控 | §五 gem.分解 / ALC-22 |
| B3 | **复制费 = cost.coins（拍板④）** | 复制费 = `⌊配方 cost.coins × gem.复制(0.2)⌋`（只算金币项、向下取整）+ 可配额外消耗（默认 0） | §一1.3 / §五 / ALC-23 |
| B4 | **珠升阶无门槛（拍板③）** | 珠升阶**无职业硬门槛**（任意炼金职业可升阶）；准入靠槽级（SOCK-02 槽级≥珠级）；禁跳级、原数值不变 | §一1.2 / 批7B |
| B5 | **int32 数量上限（拍板⑤）** | 合成/复制批量数量上限默认 `2147483647`（int32 max，settings `max_qty` 可配）；超限「最多一次使用 N 个」**提示不拦截** | §五 max_qty / ALC-21 |
| B6 | 校验器四件套 | recipe/proficiency 新增 + traits 扩展 + settings.alchemy 段登记必须**同时**落（`check_register_table_consistency` 双向拦截）；专项一律鸭子类型 `validate_xxx(modules, report)` | §六 |
| B7 | 无新表 | 数据持久化零新增表（sessions 已含 alchemy 类型；gem 走 currencies dict；proficiency 保持 dict 形态；新键全折 persistent_state） | §七 |
| B8 | 幂等与原子 | 合成/炼金/分解类 SQLite 事务 + message_id 幂等（write_idem_key 同事务）；SINK-00 原子扣减（全量满足否则全拒+差异提示） | §八 IF15/16/18 |
| B9 | 【工程补白】纪律 | 凡定稿/细化未显式定义处的实现口径必须标【工程补白】，与定稿引用严格分离；出现设计文档没有的内容=疑点 | 全文 |
| B10 | 热重载世代 | recipe/traits/proficiency 变更走 watcher 世代重绑定（registry from_snapshot + 快照 ID+名称冗余降级） | §八 IF04 / STO-05 |

---

*本子文档契约口径与细化_2c4b/2c4c/2c4e（修订版）逐项对齐；接口签名以【摸底】§四及代码实核为准；全部默认值取自炼金定稿 §10.6 与细化文档，标注"可配"项归属内容包；【工程补白】均为显式实现补充。*
