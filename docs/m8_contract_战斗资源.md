# M8 shared_contract · 子文档 4/4：《战斗与资源循环契约》

> 生成：2026-08-29 · 归属：M8 炼金里程碑 shared_contract（主契约 docs/m8_shared_contract.md 由 4 份子文档合并）
> 本子文档定义 **炼金 × 战斗对接与资源循环的可实现契约**：宝石货币（四来源/七消耗口/三币/四轴防套利/分解回炉）/ 装饰珠（珠体系/镶嵌/珠升阶/递减/触发上限）/ 战斗即时调合（battle_alchemy_used/一步出结果/豁免互斥/道具渲染）/ 资源循环（委托任务板/种植温室/代工助手）/ 接口清单（真实签名）/ 验收 TC 矩阵 / 铁律与拍板
> 兄弟子文档：m8_contract_核心机制.md（漏斗/等级/能量/品质/特性/会话）/ m8_contract_指令契约.md（指令与门槛）/ m8_contract_数据与校验.md（recipe/traits/proficiency 四件套与校验器）
> 接口口径来源：`docs/m8_接口摸底.md`（51 接口落点）+ **代码原文复核**（本子文档全部签名均 read 真实定义，非凭印象；复核文件：core/battle.py / world/battle_boundary.py / core/reward.py / core/inventory.py / core/quest.py / data/item.py / data/player.py / storage/repository.py / world/session.py / core/shop.py）
> 实现批次对照：`docs/m8_batch_plan.md`（决策 1-6 / 拍板 1-5 / 批0~批13）

---

## 〇、范围与依据

| 依据文档 | 定稿行号锚点 | 本契约章节 |
|---|---|---|
| `docs/细化/细化_2c4b_宝石货币经济.md`（25 TC） | 【炼金】L207/L214/L222-230/L274/L418-419/L435-437/L446/L455-456/L510 | 一、二、六 |
| `docs/细化/细化_2c4c_珠与合成指令.md`（30 TC） | 【炼金】L255-275/L279-300/L337/L359-368/L386/L390/L401/L418-422 | 二、六 |
| `docs/审查参考/炼金系统设计定稿.md` §七 L279-300（战斗对接+会话互斥） | L282-287/L293-299 | 三 |
| 炼金定稿 §11 L430-476（委托/种植/品评会/代工/材料闭环） | L433-439/L443-448/L453-457/L461-466/L469-476 | 一（SRC-04）、四 |
| `docs/细化/细化_2c5b_委托板与声望.md`（25 TC） | §一 委托板 L29-93 / §二 声望链 L94-133 | 四（RC-01~05） |
| `docs/细化/细化_2c5c_种植品评代工.md`（24 TC） | §一 种植温室 L23-58 / §三 代工助手 L94-123 | 四（RC-06~10 / RC-11~14） |
| `docs/m8_batch_plan.md` | 决策 1-6 / 拍板 1-5 / 批6 宝石 / 批7 珠 / 批9 战斗 / 批10 资源循环 | 全篇 |
| `docs/m8_接口摸底.md` | 51 接口落点（§六 战斗接线点 L219-249 / §七 settings / §五 物品背包） | 五 |

> **本域边界**：本子文档只管**宝石货币 / 装饰珠 / 战斗即时调合 / 资源循环**四块；指令参数与消息模板归《指令契约》（/分解 /复制 /镶嵌 /拆珠 /即时调合 /种植 /收获 /雇工 /收取 的壳函数已列于指令契约 §六）；recipe/traits/proficiency 数据模型与校验器归《数据与校验》；调合会话状态机（战斗外）归《核心机制》。本域只定义它们与**战斗/奖励/背包/存储真实接口**的对接契约。

---

## 一、宝石货币（GEM-01 ~ GEM-16）

### 1.1 货币槽与入账管线（GEM-01 ~ GEM-05）

> 依据：【炼金】L222（专属货币）、L395-405（存档）、SRC-05（2c4b）；接口：`dispatch_reward`（core/reward.py L308，**gem 为原生标量键**）。

| # | 规则 | 行为口径 | 引用 / 接口 |
|---|---|---|---|
| GEM-01 | **wallet.gem 落点** | 宝石 = 货币，**不入背包物品栈、不占格子**；存玩家钱包三槽之一——落点 = `Player.currencies: Dict[str, int]`（data/player.py **L87**，金币/钻石/宝石并列；声望另落 reputation_state、不入货币表，无独立 wallet 列）【工程补白：钱包=currencies dict，键 `"gem"`】 | 摸底 §1.2 L52 / 2c4b SRC-05 |
| GEM-02 | **统一入账管线（T48）** | 四来源（分解 SRC-01 / 挑战 SRC-02 / loot.json gem 列 SRC-03 / 品评会冠军 SRC-04）**全部走统一 reward 发放器** `dispatch_reward(entries, ctx) -> dict`（core/reward.py **L308**）；gem 条目 = 标量键（`_SCALAR_KEYS = ("coins","gem","exp","rep")`，**L59**）→ `_grant_scalar`（L225-238）→ `ctx["currencies"]["gem"] += value` | 摸底 §九 缺口5 / 决策 5 |
| GEM-03 | **⚠️ 键空间硬前置（实现关键）** | `_grant_scalar` 校验 gem ∈ 货币键空间（`_settings_currency_space` L67-79，源 = settings.currencies[].id，缺省 `DEFAULT_CURRENCY_IDS=("coins","diamond")` L56）——**gem 未在 settings.currencies 登记 → 该条 skip(`unknown_currency`)，宝石静默不发**。故 **settings.currencies 必须登记 gem（批0B 前置）**，否则批6B 管线全空转 | reward.py L233-236 / 批0B |
| GEM-04 | **流水记账** | 钱包变动全量记流水（来源通道 SRC-xx + 数额）；/图鉴 或 /面板 可查。整数值、无负数；所有消耗口原子校验（SINK-00） | 2c4b SRC-05 / L395 |
| GEM-05 | **SRC-00 来源限定** | 宝石只允许四来源入账；来源之外（交易/商店/任务直发/管理员发放除外）视为非法，供校验器与运营排查 | 2c4b SRC-00 |

### 1.2 四来源（GEM-06 ~ GEM-09）

| # | 来源 | 入账口径 | 接口 / 批次 |
|---|---|---|---|
| GEM-06 | SRC-01 **分解产出**（核心） | /分解 任意炼金成品 → 按**成品最终品质档**（分解时品质定格）平铺基础值：普通 1 / 精良 3 / 史诗 8 / 传说 20（可配；拍板①）；两段式结算（先返材料再发宝石，同条消息分行）→ gem 条目走 dispatch_reward | 批6B（IF-B10） |
| GEM-07 | SRC-02 **挑战奖励** | /挑战 调合成功 → 品质上限+10（可配）+ 宝石奖励按 settings 挑战奖励表入账（内容包可配：条件达成档位→宝石数）；**失败分支降级+退 50% 材料（向下取整），不发宝石**【细化决策】 | 批8B + 批6B |
| GEM-08 | SRC-03 **部分怪掉落** | loot.json 条目级字段 `gem: {min, max}` 随机区间（区间可配）【细化决策】；战斗击杀结算**唯一走统一 reward 发放器** `dispatch_reward` 的 gem 条目（IF-B10/IF-B11）——**不经 `settle_currency_drops`**（该函数为死亡惩罚**扣币**语义，见 §五 IF-B08 附注）；**掉落不入包、直接入货币槽**；无 gem 列 → 0 | 批6B + 批9B（经 IF-B10/IF-B11 入账） |
| GEM-09 | SRC-04 **品评会冠军** | 周常品评会冠军 → 称号（品评冠军）+ 宝石奖励（每周固定值可配）+ 群内展示；与声望加成（L456）分两个独立账目同时结算（ARB-00）。【工程补白：品评会事件本体未排本里程碑批次，批6B 只落 gem 管线接口；事件排期归后续】 | 批6B（管线预留） |

### 1.3 七消耗口（GEM-10，SINK-01 ~ SINK-07）

> 依据：【炼金】§5.3 L220-231；口径全表见 2c4b §二。**SINK-00 原子口径**：每次消耗为原子扣减——宝石+材料全量满足才执行，任一不足整单拒绝并提示差量；报错复用「宝石不足」模板（L344）；消耗按「次」计；批量上限默认 2147483647（int32 max，settings 可配，超限仅提示不拦截——拍板⑤）。

| # | 消耗口 | 指令/触发 | 门槛 | 消耗量（定稿默认） | 批次 |
|---|---|---|---|---|---|
| SINK-01 | 量贩复制 | /复制 <道具> | 大师+先 /登记 | **宝石费 = ⌊制作成本×20%⌋**【工程补白：制作成本=配方 **cost.coins**，仅金币项、向下取整；拍板④】+ 可配额外消耗（默认 0）+ 材料按配方原样另付；产出=量产标准版 | 批7C |
| SINK-02 | 成品合成 | /成品合成 A+B | 宗师+宝石 | **10 宝石/次**（可配）+ 两成品 + 材料（必耗）【工程补白】 | 批7C |
| SINK-03 | 配方合成 | /配方合成 A+B | 专家+宝石 | **5 宝石/次**（可配）；两配方已学 | 批7C |
| SINK-04 | 特性合成 | /特性合成 A+B | 宗师+宝石+材料 | **20 宝石/次**（可配）+ 材料；两同系特性 | 批7C |
| SINK-05 | 珠三合一升阶 | /珠升阶（§6.3 入口） | 无职业硬门槛（拍板③，准入靠槽级） | **10 宝石/次**（可配）+ 3×同档同 ID 珠；路径 普通×3=精良→…→传说（禁跳级，原数值不变） | 批7B |
| SINK-06 | 配方进化线 | /进化 <配方> | 宗师+低阶配方炼金产出 N 次（合成不计） | 宝石+材料（=recipe `evolve_to.cost.gem`，内容包按表配置，定稿无固定默认） | 批8A |
| SINK-07 | 温室复制素材 | 温室选素材→复制 | 大师（温室解锁） | 耗宝石 **或** 耗金币（二选一，比例可配，不可双付——ARB-00 分账） | 批10A |

### 1.4 三币关系与四轴防套利（GEM-11 ~ GEM-15）

- **GEM-11 三币对照**：金币=通用交易（合成 L112/商店 L129）；声望=委托交付评价（L435）+品评会评价（L456）；宝石=炼金专属货币（L222）。**无任何直接兑换口**；与金币唯一换算通道 = 复制费「⌊配方 cost.coins×20%⌋」（L225，固定费率非市场）。
- **GEM-12 ARB-00 分账铁律**：涉及双币/三币结算（复制费、温室复制、品评会）必须分账独立结算——输出消息分列金币账/声望账/宝石账变动，禁止混算。
- **GEM-13 四轴防套利**：轴1 来源限定（宝石只四来源入账；分解仅限炼金/深度产出；标准版默认不可分解）+ 轴2 转换损耗（分解=材料×回收率 40-65% 向下取整、复制=20% 费率，循环必收敛为负）+ 轴3 兑换口封闭（无直换口、商店不售不收宝石、宝石不可交易）+ 轴4 消耗回笼（7 消耗口全覆盖；珠升阶原数值不变、拆珠不返宝石）。
- **GEM-14 分解对象限制**：仅炼金/深度炼金产出可分解；**标准版默认不可分解**（回收减半为内容包可配备选；默认宝石发 0）。
- **GEM-15 分解数值**：材料返还 = 配方材料 × 回收率 **向下取整**（逐材料 id 分别取整，不足 1 归 0）；回收率档位 decompose_rate：正式 0.4 / 精通 0.45 / 专家 0.5 / 大师 0.55 / 宗师 0.6 / 王 0.65（称号档跳变，可配）；宝石 = 平铺基础值（**不乘回收率**，拍板①）。**两段式消息**：材料行 + 宝石行（对齐 L248 示例「火晶石×2 + 宝石×5」）。

### 1.5 产出公式可配置（GEM-16，拍板①）

- **拍板①实现口径**：默认宝石产出 = 平铺基础值（普通1/精良3/史诗8/传说20，不乘回收率）；**产出公式可配置**（settings alchemy 可配项，如可改 `⌊基础值×回收率⌋` 等，后续按需调整）；默认平铺，配置项归属 `settings.alchemy.gem.分解`（data 与校验子文档 §五 全字段表）。
- settings 键（对齐 2c4c §2.3 / 数据与校验 §五）：`gem.分解{common,uncommon,rare,legendary}` / `gem.复制=0.2` / `gem.成品合成=10` / `gem.配方合成=5` / `gem.特性合成=20` / `gem.珠升阶=10` / `decompose_rate` / `gem_diminish` / `战斗道具.珠触发上限=3` / `战斗即时调合{auto_use,per_battle_limit}`。

---

## 二、装饰珠（BEL-B01 ~ BEL-B12）

> 依据：2c4c §一 1.1（BEL-01~15）+ 炼金定稿 §六 6.3 L270-275 + §七 L284/L299。数据落点（items.json type=装饰珠 / slots.json slot_level / 珠实例堆叠键）详见《数据与校验》§四；本域只定义**战斗/背包侧对接契约**。

| # | 规则 | 行为口径 | 接口 / 批次 |
|---|---|---|---|
| BEL-B01 | 珠等级=品质档 | 珠等级直接取品质档四档：普通/精良/史诗/传说（common/uncommon/rare/legendary，拍板②，与 items.json 四档同源）；槽级分 1/2/3 | 批7A |
| BEL-B02 | 槽级映射 | 1 级槽=只装普通；2 级槽=精良及以下；3 级槽=全部（含传说）；开槽=锻造/掉落/炼金产出开槽道具（可配）；不开槽则无可用珠位 | 批7A |
| BEL-B03 | 两套词条 | `base_effects`=珠基础效果（固定数值，标准珠=只有这个）；`traits`=继承特性（品质浮动+可继承，炼金珠独有）。实例落点 = `ItemInstance`（data/item.py L20-37，含 `traits: Tuple[str,...]` 冻结 tuple） | 批7A |
| BEL-B04 | 绑定默认 | 珠绑定角色默认开启（防交易刷珠）；绑定=拾取/产出即绑定，不可群内交易赠送，内容包可配关闭【工程补白】；`ItemInstance.bound=True` 直携 | 批7A |
| BEL-B05 | 堆叠键 | 珠实例堆叠键 = ID + 品质档 + 特性集（同键可堆叠、键变分堆；升阶使品质档变化→堆叠键变更）；对接 `InventoryEngine.add_item` 堆叠合并（INV-01）与 repository `_item_from_dict`（L176）round-trip | 批7A/7B |
| BEL-B06 | **战斗中不可插拔** | 战斗中 /镶嵌 /拆珠 → 拒绝（「战斗中不可插拔」模板）；战前换珠=核心策略（部署决策前置到战斗外）；进出战斗按快照结算配置 | 批7A + 批9B（拦截） |
| BEL-B07 | 镶嵌/拆珠 | /镶嵌 <珠> <装备>：门票=槽级≥珠档；落点 = `EquipmentSlot.gems: Tuple[str, ...] = ()`（data/player.py **L69**，装饰珠落点已存在）；/拆珠 <装备> <槽位> 无损返还（原档/原特性/原堆叠键） | 批7A |
| BEL-B08 | 同名递减 | 同名珠效果乘法叠加：第 2 颗 ×50%、第 3 颗 ×25%（无第 4 颗档位→第 4 颗及以上不叠加）；递减表 = settings alchemy `gem_diminish`（默认 `[{n:2,mult:0.5},{n:3,mult:0.25}]`，0/空=无递减），可配置表驱动 | 批7B |
| BEL-B09 | **触发上限 ≤3 次/场** | 战斗内特效触发 ≤3 次/场（按珠 ID 计，**排除被动常驻**）；计数落战斗快照（与 `battle_alchemy_used` 同层，见 §三；中断恢复不清零、战斗结束清零）【工程补白：珠特效计数需在 to_snapshot dict 新增同层计数键，如 `bead_effect_used`，键名内容包可配】 | 批7B + 批9A |
| BEL-B10 | 珠升阶无门槛（拍板③） | /珠升阶 = 3×同档同 ID 珠 + 宝石 10 → 珠 +1 阶（**无职业硬门槛**，准入靠槽级 SOCK-02；原数值不变、不产生新随机）；＝合成引擎 `kind=upgrade` 配置实例（批2B 通用执行器消费） | 批7B |
| BEL-B11 | 禁跳级 | 档位链必须逐级相邻：3×普通 不可直跳 史诗/传说；链终点=传说（3×传说 无可再升）；组合表预置「普通→传说」→ 命令行校验拒绝（BEL-13） | 批7B |
| BEL-B12 | 特性集归属 | 3 颗同 ID 同档但特性集不同 → 输出珠特性集默认**保留**（与「原数值不变」一致，内容包可配归属策略：保留/取最高档/并集/首颗）【工程补白】 | 批7B |

---

## 三、战斗即时调合（BA-01 ~ BA-11）

> 依据：炼金定稿 §七 L279-300（战斗对接 +【会话互斥】补丁写死）+ 2c4f TC-31~38 + m8_batch_plan 批9。接口：core/battle.py / world/battle_boundary.py（签名见 §五）。

### 3.1 定位与计数（BA-01 ~ BA-03）

| # | 规则 | 行为口径 | 接口 |
|---|---|---|---|
| BA-01 | **即时调合 = 战斗内子流程（写死）** | 在战斗会话内执行——**不产生独立调合会话、不进入 §4.6 调合会话状态机、战斗不挂起**；借用战斗会话上下文（战斗快照即过程态），/即时调合 **一步出结果**（无 投料/继承/确认 链） | 批9A（do_action / _resolve_item_action 路径） |
| BA-02 | **battle_alchemy_used 落点（写死）** | 挂 `core/battle.py to_snapshot()` 返回 dict **顶层键**（与 ai_state/combo_state 同层，随 sessions.payload_json 持久化）；**中断恢复不清零**（对齐 potion_use_counts 口径）；**战斗结束清零**（「按场计」= 战斗会话生命周期）；`per_battle_limit = 1`（settings `战斗即时调合.per_battle_limit` 可配） | 批9A（IF-B03） |
| BA-03 | 计数模式对齐 | 计数落点模式对齐 `POTION_USE_COUNTS_KEY = "potion_use_counts"`（core/inventory.py **L56**）+ `potion_use_counts(player)`（L168）：引擎只提供落点，**中断恢复不重置、回合推进重置由战斗入口负责** | 批9A（IF-B16） |

### 3.2 会话互斥衔接（BA-04 ~ BA-06，写死）

- **BA-04 豁免互斥**：战斗会话已占用唯一会话槽，即时调合**不申请新会话槽、不触发 §4.6「单玩家同时只允许 1 个调合会话」互斥判定**（该互斥只约束战斗外调合）；§4.6 状态机的 挂起(战斗) 仅用于「战斗外调合被战斗打断」，与即时调合无关。
- **BA-05 战斗中调合指令拦截模板**：战斗中收到 /投料 /继承 /确认 等调合会话指令 → 错误模板：**「战斗中使用 /即时调合 <配方>（不进入调合会话）」**；拦截接线 = 命令壳在 `in_battle=True` 时的分支（对齐 parsers `in_battle` 参数 / battle_commands 战斗壳）。
- **BA-06 消耗与门槛**：/即时调合 <配方>（限 1 次/场）**吃冷却**（对齐 /道具 冷却配置，炸弹 3 回合冷却），消耗**携带素材 + 能量**（能量条默认关 R-08，开启时才扣能量）。

### 3.3 产出与渲染（BA-07 ~ BA-11）

| # | 规则 | 行为口径 | 接口 |
|---|---|---|---|
| BA-07 | **auto_use 可配（默认当场自动使用）** | `auto_use: true`（默认）：当场自动使用——消耗品效果立即结算（伤害/回血等），走战斗道具行动入口 `_resolve_item_action(attacker, action) -> ActionOutcome`（core/battle.py **L1162**，经 L0 执行器跑道具 actions，跳过伤害链）；`auto_use: false`：产出入背包（战斗结束后可用；本场战斗内不可再使用该产出） | 批9A（IF-B04） |
| BA-08 | **一步出结果** | 合成结算在一步内完成：材料/宝石原子扣减（走 `InventoryEngine.remove_item` L254 + gem 扣减）→ 产出实例构造（`ItemInstance`）→ auto_use 结算或入包（`InventoryEngine.add_item` L183）→ 返回 `ActionOutcome` 供战斗渲染 | 批9A |
| BA-09 | **战斗道具一行渲染** | 战斗消息一行渲染：「🔥 火焰弹！造成 58 伤害」（对齐 §七 L287；emoji 渲染按平台适配，No-emoji 渲染策略另见 output-policy） | 批9B |
| BA-10 | **道具强度公式（可配）** | 平衡公式：**道具强度 ≈ 技能×(1+0.4×冷却数)**（默认可配，settings `战斗道具.强度公式`）；强度参与伤害链结算 | 批9B |
| BA-11 | 珠特效触发联动 | 战斗内珠特效触发计数（BEL-B09）与 battle_alchemy_used 同层落战斗快照；特效 ≤3 次/场（settings `战斗道具.珠触发上限=3`） | 批9A/9B |

---

## 四、资源循环（RC-01 ~ RC-14）

> 依据：炼金定稿 §11 L430-476（委托任务板 11.1 / 种植温室 11.2 / 品评会 11.3 / 代工助手 11.4 / 材料经济闭环 11.5）；**实现直接依据**：`docs/细化/细化_2c5b_委托板与声望.md`（§一 委托板 L29-93 / §二 声望链 L94-133，委托板 4.1）+ `docs/细化/细化_2c5c_种植品评代工.md`（§一 种植温室 L23-58 / §三 代工助手 L94-123，种植/代工 4.2/4.3）。批次：批10（路10A 种植/收获、路10B 雇工/收取）；委托任务板复用 quest.py 模式（批10A 挂接）。

### 4.1 委托任务板（RC-01 ~ RC-05）

> 依据：定稿 11.1 L433-439 + `细化_2c5b_委托板与声望.md` §一 L29-93 / §二 L94-133（委托板/声望实现直接依据）。接口参照 `core/quest.py`（M4 已实装：`quest_board(ctx)->dict` L530 / `resolve_board_index(ctx, ref)->Optional[str]` L580 / `quest_accept(quest_id, ctx)->dict` L599 / `quest_progress(quest_id, ctx)->dict` L648 / `quest_complete(quest_id, ctx)->dict` L824 / `quest_abandon(quest_id, ctx)->dict` L973）。**仲裁：/任务 归玩家任务板，委托板用 /委托**——委托任务板为独立板，按 quest.py 模式新建（不混用 /任务 槽位）。

| # | 规则 | 行为口径 | 批次 |
|---|---|---|---|
| RC-01 | 刷新周期 | 委托任务板每 N 天刷新（默认 3 天，可配）；存档落 persistent_state（板期+条目） | 批10A |
| RC-02 | 接取/交付 | /委托 查看 /接取 <N> /交付 <委托> <道具>：接取=移入 active；交付=三档评价（品质/特性/数量，对齐 A11 王国委托星级）——评价判定复用 quest.py `quest_progress` 三原语判定模式（met=全真可交付） | 批10A |
| RC-03 | 声望升阶 | 交付评价 → 声望入账（走 `dispatch_reward` rep 标量键，`ctx["reputation_state"]`）→ 声望升阶 → 解锁更高委托 + 配方/材料奖励（奖励走 reward 发放器） | 批10A（IF-B10） |
| RC-04 | 截止惩罚 | 截止日未交 → 小惩罚（声望 -10%，可配）；未交条目按截止结算（对齐 quest.py `quest_abandon` 默认无惩罚 + timed.penalty 可配模式）【工程补白：委托板惩罚=定稿 11.1「声望-10%」，quest.py 的 /任务 放弃默认无惩罚不冲突，委托板为独立条目】 | 批10A |
| RC-05 | QQ 适配 | 群内任务板 = 活跃度引擎 + 道具消耗口 + 社交展示台 | 批10A |

### 4.2 种植 / 温室（RC-06 ~ RC-10）

> 依据：定稿 11.2 L443-448 + `细化_2c5c_种植品评代工.md` §一 L23-58（种植温室实现直接依据）。种子数据：items.json 条目带 `seed` 标记（见《数据与校验》§四）。

| # | 规则 | 行为口径 | 批次 |
|---|---|---|---|
| RC-06 | 种子 seed 标记 | 种子 = items.json 条目带 `seed` 标记的素材；/种植 <种子> 消耗种子入地块 | 批10A |
| RC-07 | 地块存档 | 地块 = persistent_state 存档（种子 + 种植时间 + 收获时间），非会话持久 | 批10A |
| RC-08 | 定时收获 | 定时收获默认 4 小时（可配 settings）；到期可 /收获，未到期提示剩余时间 | 批10A |
| RC-09 | 收获规则 | **收获品质 ≥ 种子品质**（保底不降档）；**种子继承特性**（traits 从种子携入收获物，对齐 2c4e INH-14）；收获入包走 `InventoryEngine.add_item`（L183） | 批10A |
| RC-10 | 温室（大师解锁） | 大师解锁温室：可复制一种素材（滚雪球，**耗宝石或耗金币二选一**，比例可配，不可双付——ARB-00 分账，SINK-07）；种子可群内交易分享（对照珠绑定关闭口径，种子不受绑定限制） | 批10A |

### 4.3 代工助手（RC-11 ~ RC-14）

> 依据：定稿 11.4 L461-466 + `细化_2c5c_种植品评代工.md` §三 L94-123（代工助手实现直接依据）。指令：/雇工 /收取（壳函数见《指令契约》§六）。

| # | 规则 | 行为口径 | 批次 |
|---|---|---|---|
| RC-11 | /雇工 | /雇工 <助手> 设定「持续代采 X / 代调 Y」；解锁=精通（对齐 2c4a 精通层代工助手解锁） | 批10B |
| RC-12 | 能源道具 | 代工消耗能源道具（糖果/馅饼类，可配；items type=能源道具），消耗走 `InventoryEngine.remove_item`（L254） | 批10B |
| RC-13 | 后台产出/收取 | 后台定时产出 → 上线 /收取（产出队列存 persistent_state；收取走 `InventoryEngine.add_item` L183 + 产出消息渲染）；30 天未收回收可复用 `Repository.recycle_scan`（L720）模式【工程补白：代工产出过久未收取的清理口径对齐会话回收】 | 批10B |
| RC-14 | 助手等级 | 助手等级提升 → 赋予特性更多 / 采集品质更高（等级存档 + 产出品质/特性档位联动） | 批10B |

### 4.4 材料经济闭环（RC-15）

- **获取**：采集（稀有度/金色/✨）/ 种植 / 代工 / 掉落 / 商店限购 → **生产**：合成（保底）/ 炼金（品质特性）/ 深度炼金（极限）→ **消耗**：战斗道具 / 装饰珠 / 委托交付 / 品评会投稿 → **回收**：分解（40-65%+宝石）/ 全物入料 / 素材转换 → **防死锁**：合成保底通道 + 分解回收 + 商店可买基础材料（定稿 11.5 L469-476）。宝石在「消耗→回收」闭环中充当计量货币（7 消耗口全覆盖，ARB-04）。

---

## 五、IF 接口清单（真实签名 + 调用方 + 实现批次）

> 签名均来自【摸底】+ **代码原文复核**（非凭印象）。编号前缀 **IF-B**（Battle/资源域），与兄弟子文档 IF-01~43（核心机制）、IF01~25（数据与校验）合并时无冲突。实现批次编号 = m8_batch_plan §二。

### A. 战斗引擎（IF-B01 ~ IF-B05）— `qbot_rpg/core/battle.py`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B01 | 行动执行 | `def do_action(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome`（**L1031**） | /即时调合 一步出结果（合成产道具→当场 use 或入包） | 批9A |
| IF-B02 | 行动结果 | `ActionOutcome` dataclass（**L219-236**）：`ok/seq/actor/action_type/target/hit/crit/blocked/raw_damage/final_damage/target_hp/side_effects/message/battle_ended/status` | 即时调合结果渲染（BA-09 一行渲染的数据源） | 批9A |
| IF-B03 | 战斗快照 | `def to_snapshot(self, boundary: Optional[str] = None) -> Dict[str, Any]`（**L1740**）——返回 dict；**`battle_alchemy_used` 新增顶层键（M8 决策 2）**，中断恢复不清零、战斗结束清零；珠特效计数同层扩展键 | 即时调合限次计数 / 珠特效触发计数 | 批9A |
| IF-B04 | 道具行动入口 | `def _resolve_item_action(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome`（**L1162**）——经 L0 执行器跑道具 actions，跳过伤害链 | 即时调合 `auto_use: true` 当场使用走此路径 | 批9A |
| IF-B05 | 战斗生命周期 | `start(...)`（L850）/ `start_turn() -> TurnReport`（L951）/ `interrupt_snapshot()`（L1778）/ `from_snapshot(...)`（L1785） | 战斗开始/打断/恢复；battle_alchemy_used 清零时机 = 战斗会话生命周期结束（to_snapshot→sessions.payload_json） | 批9A |

### B. 世界边界（IF-B06 ~ IF-B09）— `qbot_rpg/world/battle_boundary.py`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B06 | 退出结算幂等 | `async def settle_exit_idempotent(*, session: object, settlement_kind: str, message_id: str, repository: object) -> bool`（**L821**）——单事务 `delete_session(qid) + write_idem_key(key)`（L879-884），幂等键 command=`"settle:{kind}"` | 调合会话 /放弃 /确认 终态结算**仿照此模式**（IF-15 同款）；战斗结束清算（battle_alchemy_used 归零）的幂等参照 | 批3A / 批9A |
| IF-B07 | 会话互斥判定 | `session_mutex_decision(...)`（L702） | 即时调合**豁免互斥**判定依据（战斗会话已占用槽位，不申请新槽） | 批9A |
| IF-B08 | 货币掉落（死亡惩罚扣币） | `settle_currency_drops(currencies, drops) -> Tuple[Dict, Dict]`（**L406**，语义=**扣减**：按 {currency:ratio} 逐项扣，返回扣后余额/各币掉量；DEATH-03/F-02，battle_boundary.py L406-421） | **M8 不新增调用**——loot gem 列掉落（SRC-03）唯一走 `dispatch_reward` gem 条目（IF-B10/IF-B11） | —（保留编号） |
| IF-B09 | settings 容错解析模式 | `DeathPenaltyConfig.from_settings(settings)`（**L349**）模式——「容错解析 + 校验器硬拦」 | `AlchemyConfig.from_settings` 参照（战斗即时调合/战斗道具/宝石费率配置读取） | 批0B |

### C. 奖励发放器（IF-B10 ~ IF-B12）— `qbot_rpg/core/reward.py`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B10 | **统一 reward 发放器（T48）** | `def dispatch_reward(entries: Any, ctx: Optional[Mapping[str, Any]] = None) -> dict`（**L308**）——返回 `{"ok", "granted", "skipped", [idempotent]}`；ctx 就地改写 currencies/exp/reputation_state；tx_id+ledger 幂等闸 | **宝石四来源统一入账**（分解/挑战/loot gem 列/品评会冠军）+ 委托交付声望/奖励 | 批6B / 批10A |
| IF-B11 | gem 标量键路径 | `_SCALAR_KEYS = ("coins", "gem", "exp", "rep")`（**L59**）+ `_grant_scalar`（L225-238）——`ctx["currencies"]["gem"] += value`；**gem 不在 settings.currencies 键空间 → skip(`unknown_currency`)** | 四来源 gem 入账底层路径；**前置=批0B settings.currencies 登记 gem** | 批6B |
| IF-B12 | 物品条目/入包 hook | `_ITEM_KEYS = ("item", "id")`（**L61**）；ctx `["add_item"]` hook（签名 `add_item(item_id, count, bound)`，reward.py 文件头工程补白 3） | 掉落物/品评会道具/委托奖励入包 | 批6B / 批10A |

### D. 背包引擎（IF-B13 ~ IF-B16）— `qbot_rpg/core/inventory.py`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B13 | 入包 | `def add_item(self, player: Any, item: Any, count: int = 1) -> Any`（**L183**）——返回 `{ok, added, rows, new_rows, truncated, message?}` 或拒绝 `{ok:False, reason, message?}`；堆叠合并/拆行/单次截断 99/格数上限整单拒 | 复制/分解返还/种植收获/代工收取/即时调合入包（auto_use:false） | 批7C/6B/10A/10B |
| IF-B14 | 扣减 | `def remove_item(self, player: Any, item_id: str, count: int = 1) -> Any`（**L254**）——返回 `{ok, removed}` 或 `{ok:False, reason:"not_enough"\|"bound"}`（绑定拒移，不部分扣减） | 合成/复制/珠升阶材料扣减、分解销毁、即时调合携带素材消耗、代工能源消耗 | 批7C/7B/6B/9A/10B |
| IF-B15 | 持有计数 | `def count(self, player: Any, item_id: str) -> int`（**L308**） | 原子校验材料+宝石全量满足（SINK-00，缺则全拒+差异提示） | 批7C/6B |
| IF-B16 | 计数落点模式 | `POTION_USE_COUNTS_KEY = "potion_use_counts"`（**L56**）；`potion_use_counts(player)`（**L168**）返回可变 dict | **battle_alchemy_used 计数模式对齐**（引擎只提供落点，中断不重置、战斗入口负责清零） | 批9A |

### E. 数据模型（IF-B17 ~ IF-B20）— `qbot_rpg/data/`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B17 | 物品实例 | `ItemInstance` dataclass（data/item.py **L20-37**）：`item_id/name/count/quality/bound/stack_max/slot/stats_bonus/traits/cooldown_until`（traits 冻结 tuple） | 炼金成品/装饰珠/种子实例构造（品质/特性/绑定直接携带；珠堆叠键基础） | 批6B/7A/10A |
| IF-B18 | 装备珠槽 | `EquipmentSlot.gems: Tuple[str, ...] = ()`（data/player.py **L69**） | /镶嵌 /拆珠 落点（珠 ID 元组） | 批7A |
| IF-B19 | 货币 dict | `currencies: Dict[str, int]`（data/player.py **L87**） | **wallet.gem 落点**（三币并列；repository 编解码 round-trip） | 批6B |
| IF-B20 | gem 显示名 | `_CURRENCY_NAME_FALLBACK = {"coins":"金币","gem":"宝石"}`（core/shop.py **L150**；core/dialog.py L289 同款） | gem 已在显示名映射就位（店铺/对话框），M8 只需登记+入账 | 批6B |

### F. 存储 / 会话（IF-B21 ~ IF-B26）— `qbot_rpg/storage/repository.py` + `world/session.py`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B21 | 玩家存取 | `async def load_player(self, qid: str) -> Optional[Player]`（repository.py **L442**）/ `async def save_player(self, player: Player) -> None`（**L473**） | 分解/复制/即时调合/种植/代工结算后落盘（wallet.gem / inventory / persistent_state） | 批6B/7C/10 |
| IF-B22 | 会话读取 | `async def load_session(self, qid: str) -> Optional[Tuple[str, object, int, int, str, str]]`（**L563**）——返回 `(session_type, payload, random_seed, version, created_at, last_active_at)` | 战斗中断恢复读 battle_alchemy_used（payload_json） | 批9A |
| IF-B23 | 会话持久化 | `RepoTransaction.upsert_session(self, session: SessionRow) -> None`（**L887**，ON CONFLICT(player_qid) DO UPDATE）/ `delete_session(self, qid)`（**L904**）/ `Repository.tx()`（**L412**） | 战斗快照（含 battle_alchemy_used）持久化 + 战斗结束删除；种植/代工结算事务 | 批9A/10 |
| IF-B24 | 幂等键 | `RepoTransaction.write_idem_key(self, key: IdemKey) -> None`（**L922**）/ `idem_exists(self, key: IdemKey) -> bool`（**L932**） | 分解/复制/即时调合/委托交付幂等（同事务，ATO-03） | 批6B/7C/9A |
| IF-B25 | 僵尸回收 | `async def recycle_scan(self, *, settle=None, max_days: float = 30.0, now=None, allow_unsettled=False) -> List[str]`（**L720**） | 种植/代工/委托板 30 天未收取清理（复用入口，settle 回调注入）【工程补白】 | 批10 |
| IF-B26 | 会话管理器 | `acquire/release/get_active/suspend/restore`（world/session.py **L24-40**，现 NotImplementedError 占位，**M8 实装**）；`SessionConflictError`（L20） | 调合会话互斥（战斗外）；即时调合**豁免互斥**的对照判定 | 批3A |

### G. 任务/委托（IF-B27）— `qbot_rpg/core/quest.py`（M4 已实装，委托板参照）

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B27 | 任务板模式 | `quest_board(ctx) -> dict`（**L530**）/ `resolve_board_index(ctx, ref) -> Optional[str]`（**L580**）/ `quest_accept(quest_id, ctx) -> dict`（**L599**）/ `quest_progress(quest_id, ctx) -> dict`（**L648**）/ `quest_complete(quest_id, ctx) -> dict`（**L824**）/ `quest_abandon(quest_id, ctx) -> dict`（**L973**） | **委托任务板（/委托）按此模式新建独立板**（仲裁：/任务 归玩家板、/委托 归委托板）；三档评价交付/截止惩罚参照 quest_complete + timed.penalty | 批10A |

### H. 命令壳（IF-B28 ~ IF-B30）— `qbot_rpg/commands/`

| # | 接口 | 真实签名（行号） | 调用方（M8） | 批次 |
|---|---|---|---|---|
| IF-B28 | 即时调合战斗壳 | `cmd_battle_alchemy(parsed, ctx) -> dict`（战斗壳，对齐 `battle_commands.cmd_battle_attack` L818；注册见《指令契约》§六） | /即时调合（战斗内一步出结果，返回 dict 供战斗轮渲染） | 批9A |
| IF-B29 | 资源循环壳 | `cmd_plant / cmd_harvest / cmd_worker / cmd_collect(parsed, ctx) -> str`（对齐 shop_commands 壳模式 L447-483） | /种植 /收获 /雇工 /收取 | 批10A/10B |
| IF-B30 | 装配入口 | `register_alchemy_commands(router, *, make_context=None)` + `_ctx(parsed)` 闭包（make_context=None → RuntimeError【待接线】）；bootstrap.py L61 注入点 | 全部战斗/资源指令注册接线 | 批11A |

> **IF 统计：共 30 条**（A 战斗引擎 5 + B 世界边界 4 + C 奖励发放 3 + D 背包引擎 4 + E 数据模型 4 + F 存储/会话 6 + G 任务/委托 1 + H 命令壳 3）。
> 待实装标记：IF-B03（battle_alchemy_used 顶层键 + 珠特效同层计数键）、IF-B10/IF-B11（依赖批0B settings.currencies 登记 gem）、IF-B26（SessionManager 实装）、IF-B27（委托板新建，参照 quest.py）。

---

## 六、验收 TC 矩阵（映射到实现批次）

> 用例全文见各细化文档，此处仅映射归属 + 批次。门禁：批12 verify_m8 承载 179 TC（含 2c4b 25 + 2c4c 30）；本子文档覆盖 2c4b 全 25 + 2c4c 全 30（2c4c 组合合成类 TC-12~19 宝石消耗口记录于本域 SINK，其合成流程归《指令契约》）。

### 6.1 细化_2c4b（25 例，全量本域——宝石货币经济）

| TC 段 | 用例 | 实现批次 | 本域章节 |
|---|---|---|---|
| TC-01 ~ TC-05 | 宝石来源（分解/挑战/loot gem 列/品评会冠军/存档 wallet.gem） | 批6B（管线）+ 批8B（挑战）+ 批9B（loot 掉落）+ 批0B（gem 键登记前置） | 一（GEM-06~09） |
| TC-06 ~ TC-13 | 七消耗口（复制/成品合成/配方合成/特性合成/珠升阶/进化线/温室复制 + 宝石不足原子） | 批7C / 批7B / 批8A / 批10A | 一（SINK-01~07） |
| TC-14 ~ TC-18 | 四轴防套利（标准版不可分解/分解对象限制/循环收敛/兑换口封闭/拆珠不返宝石） | 批6B + 批7B + 批7C | 一（GEM-13/14） |
| TC-19 ~ TC-22 | 分解回炉（回收率六档/向下取整/平铺宝石两段式/传说+全物入料） | 批6B | 一（GEM-14/15） |
| TC-23 ~ TC-25 | 配置与回归（gem 键校验/mode=simple 关闭宝石/指令总表门槛一致） | 批0B（校验器）+ 批12 | 一（GEM-16）+ 数据与校验 |

### 6.2 细化_2c4c（30 例，珠与合成——本域 22 例 + 联动 8 例）

| TC 段 | 用例 | 实现批次 | 本域章节 |
|---|---|---|---|
| TC-01 ~ TC-06 | 珠升阶链（数值不变/全链路 130 宝石/禁跳级/混档混 ID 拒绝/宝石不足/无职业硬门槛） | 批7B | 二（BEL-B10/B11） |
| TC-07 ~ TC-11 | 复制（未登记拦截/量产标准版/复制对象限制/原子全拒/数量超限提示不拦） | 批7C | 一（SINK-01）+ GEM-11 |
| TC-12 ~ TC-19 | 三类组合合成（成品/配方/特性 + 门槛/同系/重复拒绝）——**流程归指令契约，宝石消耗记录于本域 SINK-02/03/04** | 批7C | 一（SINK-02~04） |
| TC-20 ~ TC-24 | 镶嵌/珠规则（槽级准入/传说需 3 级槽/无损拆珠/战斗中不可插拔/同名递减×触发上限） | 批7A + 批7B + 批9A/9B（战斗中拦截+计数） | 二（BEL-B02/B06/B08/B09） |
| TC-25 ~ TC-26 | 镶核心（大师+会话中/可换）——**归核心机制域，本域仅记录消耗口联动** | 批8A | — |
| TC-27 ~ TC-30 | 分解（宗师 60% 返还/标准版默认拒绝/六档回收率/见习与非炼金产出拒绝） | 批6B | 一（GEM-14/15） |

> **战斗/资源相关用例覆盖口径**：2c4b 全 25 例 + 2c4c 战斗/资源相关 22 例（TC-01~11、20~24、27~30）= **47 例**；其余 8 例（2c4c TC-12~19、25~26）为跨域联动，宝石消耗口已在本域记录，流程验收归《指令契约》《核心机制》。

---

## 七、铁律与拍板（本域专属）

### 7.1 本域铁律

1. **接口签名纪律**：五章全部签名来自 `docs/m8_接口摸底.md` + 代码原文复核（core/battle.py / battle_boundary.py / reward.py / inventory.py / quest.py / data/item.py / data/player.py / repository.py / session.py / shop.py），实现组不得凭印象改写；新增调用前先 grep 调用方（拦截链接线，batch_plan 铁律 6）。
2. **宝石键空间前置**：`dispatch_reward` 的 gem 标量键在 gem 未登记 `settings.currencies` 时 **skip(`unknown_currency`)** 静默不发——**批0B 必须先登记 gem**，批6B 管线才有意义（reward.py L233-236）。
3. **battle_alchemy_used 写死落点**：挂 `to_snapshot()` 返回 dict **顶层键**；中断恢复不清零、战斗结束清零；per_battle_limit=1；珠特效 ≤3 次/场计数同层（BEL-B09）。
4. **即时调合写死语义**：战斗内子流程——不新开会话、不挂起、不申请槽、豁免互斥；战斗中收到 /投料 /继承 /确认 → 拦截模板「战斗中使用 /即时调合 <配方>（不进入调合会话）」。
5. **原子防双扣**：分解/复制/即时调合/委托交付类操作 SQLite 事务 + message_id 幂等（`write_idem_key` 同事务）；任一材料/宝石/能量不足全拒+差异提示，绝不部分执行。
6. **四轴防套利纵深**：来源限定（标准版默认不可分解）/ 转换损耗（回收率向下取整+20% 复制费率）/ 兑换口封闭（无直换、不可交易）/ 消耗回笼（7 口全覆盖）四轴并立，任一轴失效其余三轴仍拦截。
7. **未标【工程补白】不得新增定稿外行为**：本域补白均已显式标注——钱包=currencies dict（GEM-01）、品评会事件未排批次（GEM-09）、珠特效计数键名（BEL-B09）、珠特性集归属默认保留（BEL-B12）、委托板惩罚口径（RC-04）、代工清理复用 recycle_scan（RC-13）。
8. **分账结算铁律（ARB-00）**：复制费/温室复制/品评会等双币结算必须分账独立结算，禁止混算。

### 7.2 用户 5 项拍板（本域 ①③④ 全量体现；②⑤ 关联体现）

| # | 拍板 | 本域落点 |
|---|---|---|
| ① | **分解宝石 = 平铺基础值（普通1/精良3/史诗8/传说20，不乘回收率）+ 产出公式可配置** | **一 GEM-15/GEM-16——本域铁律**（settings `gem.分解`，默认平铺可配） |
| ② | **品质档键名 common/uncommon/rare/legendary（普通/精良/史诗/传说）；档位数可配 3/5/7、0=不限制** | 二 BEL-B01（珠等级=品质档）+ 一 GEM-16（宝石档位键）——珠档位与宝石档位共用同一键集 |
| ③ | **珠升阶无职业硬门槛（准入靠槽级 SOCK-02）** | **二 BEL-B10 + 一 SINK-05——本域铁律**（禁跳级 BEL-B11） |
| ④ | **复制费 = ⌊配方 cost.coins×20%⌋（只算 coins、向下取整）+ 可配置额外消耗（默认 0）** | **一 SINK-01——本域铁律**（复制费基准=cost.coins） |
| ⑤ | **数量上限默认 2147483647（int32 max，可配 max_qty）+ 超限提示不拦截** | 一 SINK-00（消耗按次、批量上限 int32）——对齐分隔符 L73；max_qty 接线归《指令契约》 |

### 7.3 配置默认值速查（本域）

| 键 | 默认值 | 依据 |
|---|---|---|
| `settings.currencies` 含 gem | `{"id":"gem","name":"宝石",...}`（**必须登记**，否则 dispatch_reward skip） | reward.py L233-236 / 决策 5 |
| `alchemy.gem.分解` | `{common:1, uncommon:3, rare:8, legendary:20}`（平铺，拍板①） | 2c4b DEC-03 / 2c4c DEC-04 |
| `alchemy.gem.复制` | `0.2`（⌊cost.coins×20%⌋，拍板④） | 2c4c DUP-03 |
| `alchemy.gem.成品合成 / 配方合成 / 特性合成 / 珠升阶` | `10 / 5 / 20 / 10` | 2c4b SINK-02~05 |
| `alchemy.decompose_rate` | 正式0.4/精通0.45/专家0.5/大师0.55/宗师0.6/王0.65 | 2c4b DEC-02 |
| `alchemy.gem_diminish` | `[{n:2,mult:0.5},{n:3,mult:0.25}]` | 2c4c BEL-10 |
| `alchemy.战斗道具` | `{强度公式:"技能×(1+0.4×冷却数)", 珠触发上限:3}` | 定稿 §10.6 L424 |
| `alchemy.战斗即时调合` | `{auto_use:true, per_battle_limit:1}` | 定稿 §10.6 L425 / §七 L300 |
| `alchemy.委托刷新天数` | `3`（每 N 天刷新） | 定稿 11.1 L434 |
| `alchemy.种植收获时长` | `4 小时` | 定稿 11.2 L444 |
| `alchemy.max_qty` | `2147483647`（int32 max，拍板⑤） | 拍板⑤ |

---

*本子文档全部契约可追溯至：细化_2c4b（SRC/SINK/ARB/DEC 编号 + TC-01~25）、细化_2c4c（BEL/DUP/CMB/SOCK/COR/DEC/EDGE 编号 + TC-01~30）、炼金定稿 v2.3（§六 6.3 L270-275 / §七 L279-300 / §10.6 L418-425 / §11 L430-476）、m8_batch_plan（决策 1-6 / 拍板 1-5 / 批6-批10）、m8_接口摸底（§五 物品背包 / §六 战斗接线点 / §七 settings）；接口签名经代码原文复核（battle.py / battle_boundary.py / reward.py / inventory.py / quest.py / data/item.py / data/player.py / repository.py / session.py / shop.py）。【工程补白】均已显式标注，与定稿引用严格分离。*
