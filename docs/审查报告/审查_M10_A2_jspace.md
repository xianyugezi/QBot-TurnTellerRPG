# 审查 · M10 钓鱼批A-2 鱼饵体系（fishing_bait.py + 饵内容/配方）

> 方式：j-space 静态审查（full 档）· 本环境无 bash 沙箱，**零命令执行**，全部结论为静态推导
> 日期：2026-09-01 · 审查人：主 agent（j-space 会话）
> 文件清单：
> - `qbot_rpg/core/fishing_bait.py`（230 行，本批核心）
> - `content/test_demo/items.json`（524 行，5 档饵条目 L485-523）
> - `content/test_demo/recipe.json`（449 行，rcp_bait_* 配方 L318-448）
> 参考：`docs/细化/细化_2c1a_鱼种数据与冠级.md` §1.2（F-12）/ §五（V3 双向）、`docs/m10_shared_contract.md` §一（settings.fishing 字段表/加载容错）、`定稿钓鱼玩法设计定稿.md` §1 M2 L16/L96（经 m10_shared_contract/细化 转引）
> 交叉核对：`qbot_rpg/core/fishing_settings.py`、`qbot_rpg/core/fishing.py`（L400-445）、`qbot_rpg/content/fishing_models.py`、`content/test_demo/settings.json` L212-240、`content/test_demo/fishing.json`、`qbot_rpg/content/field_meta.py` L524-531

> ⚠️ 可达性说明：定稿原文在仓库外 `/root/docs_archive/RPG框架项目/钓鱼玩法设计定稿.md`（glob 不可达），本报告以仓库内契约（m10_shared_contract 声称与定稿 §三 逐键一致）与细化 2c1a 为准对表；凡涉及定稿行号（L16/L74-76/L96）均为**转引口径**，直接冲突时以契约为准。

## 结论速览

| 级别 | 数量 | 要点 |
|---|---|---|
| P0 | 0 | 无阻断性缺陷 |
| P1 | 3 | ①bait_bonus 逐键兜底可能吞半合法配置 ②items.json 5 饵缺 `usable` 键 + shop 无饵来源 ③F-2 择饵序对齐声明与兄弟路 hook 形态存在张力 |
| P2 | 5 | ④is_bait/is_preferred_bait 空串判定与 bait_ids_of 清洗不一致 ⑤qid 冗余参数未接线未标 TODO ⑥F-1 补白未登记 contract_deviations ⑦缺消费方（装配/流程）消费 bait_bonus 的落点引用 ⑧缺负面测试/集成接线单测 |

---

## 一、维度① 定稿落地核对

### 1.1 5 档饵（定稿 L74 bait_ids 5 档 + L96 1 次=1 饵）

| 核对项 | 结果 | 证据（静态推导） |
|---|---|---|
| 代码默认 5 档 | ✅ | `fishing_bait.py` L55-61 `_DEFAULT_BAIT_IDS` 5 档，与 `fishing_settings.py` L60、`settings.json` L214-220 三处同序同值 |
| settings.json 显式 5 档 | ✅ | `settings.json` L212-220 `fishing.bait_ids` 5 档全量 |
| items.json 5 饵条目 | ✅ | L485-523：`饵_蚯蚓/饵_面团/饵_小鱼/饵_黄金虫/饵_龙涎`，type=consumable、价格 30/25/60/120/200 |
| recipe.json 5 配方 | ✅ | L318-448：`rcp_bait_worm/dough/smallfish/goldbug/dragonspit`，kind=craft，materials 用既有素材（moon_grass/star_iron/ghost_moss/ore/ash_core/fire_dragon_scale），cost 小额，符合 F-1 补白口径 |
| 配方输出 ↔ 条目 | ✅ | 5 配方 output.item 逐一对应 5 饵 id（recipe L331/355/383/411/439 ↔ items L485/493/501/509/517） |
| bait_ids 引用完整性（V3 正向） | ✅ | 5 饵 id ∈ settings.bait_ids；`fishing.json` L16 `preferred_bait:["饵_蚯蚓"]` ∈ bait_ids；校验器 `fishing_models.py` L481-491 红拦缺引用 |
| V3 反向（fish_target） | ✅ 静态 | 全仓 `recipe.json` 无 `fish_target` 键 → 契约明示跳过（fishing_models.py L542-543），本批配方不涉 |
| L96 一次 1 饵 | ✅ | `consume_bait` L214-220 每次恰扣 1（`_remove_item(ctx, bid, 1)`） |

### 1.2 对口饵判定（F-12 / 2c1a §1.2）

- `is_preferred_bait`（L109-125）双形态：FishDef 访问器（`getattr(species, "preferred_bait")`）或 raw dict（`species.get("preferred_bait")`）均支持，与 `FishDef.preferred_bait`（fishing_models.py L166-168）对齐；元素级 `isinstance(x, str) and x == item_id` 正确。
- 判定不依赖 bait_ids 白名单（任何鱼种自声明饵即对口）——符合 F-12 语义（对口 = 鱼种声明，非档位过滤）。
- 无饵保底：`bait_available` L195-198 任一档计数 >0 即 True；`consume_bait` 无饵/全失败返回 `{ok:True, used:None, had_bait:False}`（L220）——对齐定稿 L16 铁律（可无饵抛竿仅不吃对口饵加成）。静态推导：抛竿流程可读 `had_bait=False` 跳过加成，不卡死。

### 1.3 饵加成（L75 bait_bonus）

- `bait_bonus_of`（L128-144）：缺省 `{rare:8, gold:2}`（L64 与 `fishing_settings.py` L62、settings.json L221-224 一致）；仅接受非负 int 且排除 bool；**本路只读不消费**（L132 注释，加成作用于收杆 roll 由批2 路2C 消费）——符合本批分工。

### 1.4 背包 hooks（M9 _inventory_hooks 契约）

- `_count_item`（L150-164）：`ctx["count_item"]` hook 优先（异常→0）、`ctx["inventory"]` 计数映射兜底（非 int/bool → 0）——与 quest.py `_count_item` 形态一致。
- `_remove_item`（L167-182）：hook 优先（异常→False）、inventory 就地扣减兜底（不足/非 int → False）——兜底扣减幂等（成功才改映射，`cur < count` 提前拒绝）。
- 扣饵失败→继续后续档（L218-219 `continue`）——半扣不卡死，语义正确。

### 1.5 交叉核对：兄弟路1B 同序声称（F-2）

`fishing.py` L430-444 `_consume_bait` 内置扣饵：按 `bait_ids` 档序、`remove_item` hook 优先、inventory 兜底——与 `fishing_bait.consume_bait` 的档序/hook 序**一致**（静态比对两处循环结构）。差异仅形态：fishing.py 在 `ctx["remove_item"]` 存在时**不再回落 inventory**（L433-439 `continue`），而 fishing_bait.py 无 hook 时回落 inventory——行为对齐（hook 注入是常态）。

## 二、维度② 代码质量（bug / 边界 / 幂等 / hooks）

### P1-1 bait_bonus_of 逐键兜底吞半合法配置（fishing_bait.py L136-144）

**静态推导**：`bonus = section.get("bait_bonus")` 经 `fishing_cfg` 归一后必为全键 dict（fishing_settings.py L221-224 `_merge_int_map` 已保证 rare/gold 均存在），故 `out` 恒满键；唯一可能 `out` 空的情形是**绕过 fishing_cfg** 的调用（如直传自定义 Mapping 仅含 `{"rare": 5}`）→ 此时**整体**回退默认 `{rare:8,gold:2}`，`gold=2` 幸存但 `rare=5` 被吞。
**影响**：与契约 §一「逐键兜底」语义（非法类型逐键回退）不一致；上游 `fishing_cfg` 当前保证全键，缺陷被掩盖，属防御层不完整。P1 而非 P2 的理由：一旦未来调用方直传段 dict（本模块 docstring L82 明示三态入参含「settings.fishing 段本身」），静默吞配置且无日志。
**修复**：循环内非 int/负值回退 `_DEFAULT_BAIT_BONUS[key]`，缺键补默认，最终全键返回：

```python
for key, default in _DEFAULT_BAIT_BONUS.items():
    v = bonus.get(key)
    out[key] = default if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0) else v
```

### P1-2 items.json 5 饵缺 `usable` 键 + shop 无饵来源（items.json L485-523）

**静态推导**：
- 既有 consumable 条目（potion/mana_potion/antidote/hi_potion/flame_bomb 系列）**均带** `"usable": true`（items.json L10/20/30/40/268/282/296/312），5 饵条目只有 `type/source/price/desc`，无 `usable`——若装配层按 `usable==True` 过滤可消耗物（游戏惯例），饵将不可从物品栏使用/不可见；虽 `field_meta.py` L524-531 对 items 仅宽松 str 登记、无硬校验（静态推导不红拦），但**既有条目形态不一致**是本批引入的不对齐。
- 5 饵 `source` 均为 `"炼金产出"`；全仓 `shop.json` 无 `饵_*` 条目（grep 零命中）→ **饵的唯一获取路径是炼金合成**；若炼金装配层尚未产出（批A-2 不含装配），运行期钓鱼可能断供（无饵保底可下钩，但体验降级）；定稿/契约均未要求商店卖饵，此项为「可用性提示」非缺陷。
**修复**：5 饵条目补 `"usable": true`（或确认装配层消费口径）；若设计意图为饵仅炼金产出，在 F-1 补白或派工单中显式声明，避免消费方按 `usable` 过滤时饵不可用。

### P1-3 F-2 择饵序「对齐兄弟路1B」声明与 hook 形态张力（fishing_bait.py L37-38、L214-220）

**静态推导**：`fishing.py` L418-424 优先委托 `ctx["consume_bait"]` hook（**签名 `(ctx, engine) -> Optional[str]`**），未注入才走内置档序扣饵；而本模块 `consume_bait(ctx, qid)` 签名不同（无 engine），装配层若直接把本函数注入 `ctx["consume_bait"]`，fishing.py L421 `hook(ctx, self)` 会把 engine 当第 2 参传入 → `consume_bait` 的 `qid` 参数会收到 **engine 对象**而非玩家标识——本路 qid 未使用（F-3），不炸但语义错位；若装配层改注入 `functools.partial` 则无此问题。即：**模块自身无 bug，但「同序对齐」的保证依赖装配层包装，未在本文件显式标注接线契约**。
**修复**：在 `consume_bait` docstring 增注「装配注入 `ctx["consume_bait"]` 时须 partial 包装 `(ctx, engine)` 形态（对齐 fishing.py L421 调用签名）」；或在 F-2 补白明示「同序仅指内置路径，hook 形态差异由批2 装配消化」。

### P2-1 is_bait/is_preferred_bait 空串判定与 bait_ids_of 清洗不一致（fishing_bait.py L104-106、L116-117）

`is_bait`/`is_preferred_bait` 对 `"  "`（空白串）返回 False（strip 后空）；而 `bait_ids_of` L88 清洗也剔除空白串——**一致**。但 `bait_ids_of` 对显式档内 `"  "` 条目剔除、`is_bait(ctx, "  ")` 与 `is_bait(ctx, "")` 都 False——**行为自洽，无 bug**。真正的不一致：`is_bait` 不 trim 后比较（`item_id in bait_ids` 原样比较），若上游传 `" 饵_蚯蚓 "`（带空格）→ False 但 `bait_ids_of` 清洗只去**空串**不去**首尾空白**，档内条目不会被 trim——`" 饵_蚯蚓 "` 既不等于档内 `"饵_蚯蚓"` 也不被清洗，判定 False 但原因隐晦。**低危，防御性 trim 建议**（条目来源为配置文件，风险极低）。升级为 P2。

### P2-2 qid 冗余参数未接线且无 TODO（fishing_bait.py L188-220）

F-3 补白声明 qid 仅身份冗余、本路不依赖；但 `bait_available`/`consume_bait` 未标注「若批2 按 qid 路由需在装配层拆包」的落点，后续维护易把 qid 当已生效标识。建议补一行注释或派工单引用。

### P2-3 F-1 补白未登记 contract_deviations（fishing_bait.py L32-41）

契约 §五.8「契约偏差记 contract_deviations」：饵条目/配方数值属自拟补白（F-1），代码内已标注【工程补白】但未见登记到契约/派工单的 deviations 清单（静态搜索 m10_shared_contract.md 无 A2 补白登记段）。非功能缺陷，流程项。

### P2-4 bait_bonus 消费方落点未引用（fishing_bait.py L128-144）

docstring 称「批2 路2C 消费」，但未指向具体文件/函数（fishing.py 收杆 roll 或装配层）；跨批依赖无锚点，易悬空。建议补 `docs/m10_*` 消费方引用或派工单编号。

### P2-5 缺负面/集成测试锚点（fishing_bait.py 全文件）

文件零单测引用（对照契约铁律 4「单测全绿」）；`consume_bait` 无饵保底、hook 异常→continue、兜底扣减幂等均无测试锚点。静态推导：批A 应有配套 tests/unit/test_fishing_bait.py（本审查未见，归批A 清单遗漏则 P2；若在兄弟路则忽略）。建议补：无饵保底/半扣/非 int 计数/`"  "` 档条目 4 类用例。

## 三、维度③ 遗漏

| 遗漏项 | 说明 | 级别 |
|---|---|---|
| 三处默认值漂移 | `_DEFAULT_BAIT_IDS`（L55）/`DEFAULT_FISHING_SETTINGS`（fishing_settings L60）/settings.json L214-220 同值但**无单测断言三处一致**——V3 只查引用存在性，不查「默认档位==内容包档位」 | P2 |
| 无饵保底消费方契约 | `had_bait=False` 时收杆侧「不吃对口饵加成」的**具体行为定义**（加成加在哪一步、为 0 还是跳过）未在本路/契约给出——批2 若误把 `had_bait` 当布尔开关而非语义位，可静默吞掉无饵限制 | P2 |
| recipe fish_target 无接线 | V3 反向要求「定向饵 recipe 的 fish_target 指向鱼种存在」——全仓 recipe 无此键，属契约允许的跳过，但**饵-鱼对口的经济闭环（炼金产出→对口）无任何数据连接**（仅 `preferred_bait` 文本引用） | P2（契约允许，流程提示） |

---

## 四、修复优先级汇总

| 编号 | 级别 | 位置 | 修复建议 |
|---|---|---|---|
| P1-1 | P1 | fishing_bait.py L136-144 | bait_bonus 逐键兜底（非整体回退） |
| P1-2 | P1 | items.json L485-523 | 补 `usable:true`；shop 无饵来源声明意图 |
| P1-3 | P1 | fishing_bait.py L37-38/L214-220 | 增注 hook 注入形态（partial 包装），消除同序声明张力 |
| P2-1 | P2 | fishing_bait.py L104-106/L116-117 | 防御性 trim 或注释说明原样比较 |
| P2-2 | P2 | fishing_bait.py L188-220 | qid 接线落点注释 |
| P2-3 | P2 | fishing_bait.py L32-41 | F-1 登记 contract_deviations |
| P2-4 | P2 | fishing_bait.py L128-144 | 消费方落点引用 |
| P2-5 | P2 | 全文件 | 补单测锚点（无饵保底/半扣/幂等） |
| P2-6 | P2 | 三处默认值 | 一致性断言 |
| P2-7 | P2 | 无饵保底语义 | 收杆侧 had_bait 消费契约定义 |

---

*静态推导声明：本报告全部结论基于文件静态阅读与仓库内交叉核对，未执行任何命令/脚本/运行验证；「红拦」「可通过」等校验器行为结论均为代码路径静态推导。*
