# M8 shared_contract · 子文档 1/4：《炼金核心机制契约》

> 生成：2026-08-29 · 归属：M8 炼金里程碑 shared_contract（主契约 docs/m8_shared_contract.md 由 4 份子文档合并）
> 本子文档定义 **炼金核心机制的可实现契约**：三层漏斗总纲 / 职业等级体系 / 调合能量条 / 品质系统 / 特性体系 / 投料与触媒 / 调合会话状态机 / 接口清单（真实签名）/ 验收 TC 矩阵 / 铁律与拍板
> 兄弟子文档：m8_contract_指令契约.md（指令与门槛）/ m8_contract_数据与校验.md（recipe/traits/proficiency 四件套与校验器）/ m8_contract_战斗资源.md（宝石货币/珠/战斗即时调合/资源循环）
> 接口口径来源：`docs/m8_接口摸底.md`（51 接口落点）+ 代码原文复核（本子文档全部签名均 read 真实定义，非凭印象）
> 实现批次对照：`docs/m8_batch_plan.md`（批0~批13）

---

## 〇、范围与依据

| 依据文档 | 定稿行号锚点 | 本契约章节 |
|---|---|---|
| `docs/细化/细化_2c4a_炼金三层漏斗.md`（26 TC） | 【炼金】L5/L16-28/L43-47/L55-98/L104-121/L128/L192-218/L318-344 | 一、二、三、十 |
| `docs/细化/细化_2c4e_品质与特性.md`（26 TC） | 【炼金】L150-156/L167/L201-218/L348-382/L395-424；【效果】L29/L281-305 | 四、五、十 |
| `docs/细化/细化_2c4f_投料触媒与能量条.md`（38 TC） | 【炼金】L131-143/L153-156/L279-300/L344/L408-424；【分隔符】L29-73；【规划】L156/L286/L560 | 三、六、七、十 |
| `docs/m8_batch_plan.md` | 决策 1-6 / 拍板 1-5 / 批0-批13 派工 | 全篇 |
| `docs/m8_接口摸底.md` | 51 接口落点（含文件:行号） | 七、八 |

> 本域边界：本子文档只管**核心机制语义**（漏斗边界/等级/能量/品质/特性/投料触媒/会话状态机）；指令参数与消息模板归《指令契约》，数据模型 schema 与校验器归《数据与校验》，宝石货币/装饰珠/即时调合归《战斗资源》。

---

## 一、三层漏斗总纲（LAY / CASC）

### 1.1 三层边界（LAY-01 ~ LAY-04）

| # | 层 | 定义 | 解锁条件 | 产出边界 |
|---|---|---|---|---|
| LAY-01 | 第 1 层【合成】 | 跨职业快捷生产：配方+材料 → 直接得成品 | 任一制造职业/资源技能达到配方等级（无炼金职业门槛） | **只产标准版**：品质固定（标准）、无特性/超特性/进化/核心类；标准珠固定 `base_effects` |
| LAY-02 | 第 2 层【炼金】 | 职业专属：投料/品质/特性继承/属性刻度/触媒 | 炼金职业等级见习起步 | 品质四档浮动 + 特性继承（默认 ≤3）+ 属性刻度达标→额外效果 |
| LAY-03 | 第 3 层【深度炼金】 | 大师解锁完全体：20+ 机制（实际生效 **19** 项，#13 秘钥强化已砍） | 炼金职业等级 ≥ 大师（写死，他职不可替代） | 机制表全部生效；`synth_allowed=false` 拦合成绕过 |

**LAY-04 边界铁律**
- 4a：合成层产出恒标准版（traits/awaken 恒空）——【工程补白：属性独立】标准版实例 `traits=()`、`awaken` 无，见 STO-01。
- 4b：炼金层产出品质分 0-100 四档（拍板②，见四）+ 继承特性（正式 1 → 精通 2 → 专家 3，等级化）。
- 4c：深度层全部机制；`synth_allowed` 默认 false 拦绕过（CASC-04）。

### 1.2 mode 三态（LAY-06）

- `settings.alchemy.mode`：`full`（三层漏斗，**默认**）/ `simple`（仅合成层：无炼金层/深度炼金/职业等级/特性/能量条，漏斗缩为单层）/ `off`（关闭）。
- mode=simple 时本契约 二~七 的炼金层规则**全部不生效**（仅保留合成原子校验与标准版产出）。

### 1.3 synth_allowed 与瀑式解锁（CASC-01 ~ CASC-10）

- **CASC-01 合成是瀑式熟练入口**：每个合成成品 = 配方等级 ×1 熟练（可配）；熟练经验来源 = 制作（合成/炼金/锻造）+ 采集 + 战斗。
- **CASC-02 等级独立 + 区间映射**：职业等级与角色等级独立；`job_tier_map` 称号↔配方等级区间（见二）。
- **CASC-03 深度必须经炼金层达标**：深度解锁 = 炼金职业 ≥ 大师（写死），合成层通用达标逻辑不适用。
- **CASC-04 深度配方合成拦截**：深度配方 `synth_allowed` 默认 false（可配）；默认态 /合成 深度配方 → 拒绝（「深度未解锁」类模板）；内容包改 true → 可合成但**提示不阻断**「此深度配方可被合成，将绕过深度炼金玩法」。
- **CASC-05 进化计数防跳**：配方进化线前置 = 「低阶配方**炼金产出** N 次（**合成不计**）」；/合成 刷 N 次 → /进化 拒绝。
- **CASC-06 王称号防跳**：王条件 = 该职业**图鉴全点亮**（与等级区间解耦）；图鉴成长仅由炼金/深度炼金产出点亮（合成图鉴仅小加成，不点亮炼金图鉴条目【工程推导】——定稿 L120 未明示与炼金图鉴点亮关系，见 2c4a CASC-06）。
- **CASC-07 指令门槛防跳**：/深度炼金=大师+能量 /进化=宗师+炼金产出 N 次 /挑战=宗师+材料×2 /即时调合=大师+能量（限 1 次/场）/镶核心·加成=大师/宗师 /成品合成·特性合成=宗师+宝石 /配方合成=专家+宝石。
- **CASC-08 会话类型分离**：/深度炼金 与 /炼金 为不同会话类型（SESSION_TYPES 已含 `alchemy`/`challenge_alchemy`）；深度机制操作必须在深度会话内；挑战/挂起恢复不得跨层混用。
- **CASC-09 特性继承等级化**：正式 1 → 精通 2 → 专家 3，见习无继承位；SP 面板另可解锁特性位+1（可多次）。
- **CASC-10 能量软门槛**：能量条默认关（R-08，见三）；开启时每次炼金/深度炼金消耗 1 格；/合成 保底不耗能量、永可用。

### 1.4 防跳层验收锚点（TC 索引见九）

2c4a TC-07/08/09（synth_allowed 拦/提示）、TC-10（进化计数）、TC-11（王图鉴）、TC-12（会话分离）、TC-13（区间校验）、TC-14（继承等级化）。

---

## 二、职业等级体系（proficiency）

> 依据：2c4a JOB-01~06 / CASC-01~02；接口对齐 `core/levelup.py` L117-128（`player["proficiency"]` dict 形态，见 IF-24）。

### 2.1 七阶与 tier_names（JOB-01 ~ JOB-02）

- 七阶名：**见习 → 正式 → 精通 → 专家 → 大师 → 宗师 → 王**（王为职业化终极称号：炼金王/铸造王/钓鱼王/收集王…）。
- `proficiency.json`：`tier_names` **数组长度即级数**（默认 7 级，内容包可改名/可配级数）+ 每职业熟练值 + 成长曲线；职业等级与角色等级独立。
- 存档形态：**保持 `player["proficiency"]` dict 形态**（M8 决策 4），Player dataclass **不加字段**（避免 repository 编解码大改）；`proficiency.<job_id>.sp_earned` 为 SP 落点（对齐 levelup.py L117-128）。

### 2.2 job_tier_map 区间（JOB-03）

| 称号 | 配方等级区间 | 三层关系锚点 |
|---|---|---|
| 见习 | 1-5 | 第 1 层合成可用；第 2 层炼金基础开放 |
| 正式 | 6-10 | 炼金层深化①：特性继承 1 项；种植解锁 |
| 精通 | 11-20 | 炼金层深化②：特性继承 2 项；属性刻度显现；代工助手解锁 |
| 专家 | 21-30 | 炼金层深化③：特性继承 3 项；触媒（R-07）；配方合成；全物入料 |
| 大师 | 31-40 | ⭐ 第 3 层深度炼金解锁（连锁/核心镶嵌/分解回炉/量贩复制/图鉴成长/战斗即时调合） |
| 宗师 | 41-50 | 深度炼金完全体（进化线/金色超特性/成品合成/觉醒/挑战调合/负面特性…） |
| 王 | 51+ | 终极称号（炼金王）：全图鉴+专属配方+称号加成 |

- 配方准入判定：配方 `level` 落在当前称号区间（job_tier_map）才可调合/合成——合成与炼金**共用同一区间校验**。
- `settings` 落点：`alchemy.job_tier_map`（校验器 `_check_settings_alchemy` 引用职业枚举，IF-42）。

### 2.3 熟练经验来源（CASC-01）

- 制作（合成/炼金/锻造）+ 采集 + 战斗 → 熟练值；合成每个成品 = 配方等级 ×1（可配 `synth_exp`）。
- 熟练经验入账走 `levelup.gain_exp`（IF-25）同款返回 dict，SP 发放走 `_grant_sp`（IF-24）。

### 2.4 SP 面板 sp_panel（JOB-05，各解锁项）

- 每升 1 级职业等级 → 获得 1 点 SP（可累积）；`sp_per_level` 可配（默认 1）。
- /技能面板 分支**自选解锁**（非等级自动给，每项 `repeatable` 语义）：

| 解锁项 | repeatable | 上限语义 | 本域引用 |
|---|---|---|---|
| 品质上限 +10 | 可多次 | 叠加进品质上限，品质分仍 ≤100 | 四 QLT-08 |
| 投入次数 +1 | 可多次 | 扩 /投料 追加次数上限 | 六 FEED |
| 特性位 +1 | 可多次 | 普通特性位默认上限 3（可配 1-6），SP 与职业等级位叠加 | 五 INH-15 |
| 解锁复制·进化·挑战 | 单次 | 各自指令门槛的前置解锁 | 指令契约（兄弟子文档） |
| 采集量 +1 | 可多次 | 采集产出数量 | 战斗资源（兄弟子文档） |
| 连锁上限 +1 | 可多次 | 链式投料最大连锁段数 | 六 FEED-06 |

### 2.5 王称号（JOB-06 / CASC-06）

- 不唯一、按职业独立授予；条件 = 该职业**图鉴全点亮**（与等级区间解耦——60 级未全点亮不授）。
- 奖励 = 专属配方 + 称号加成（全属性 +X% 可配）+ 群内称号展示；品评会冠军专属联动（每周）。
- 图鉴点亮来源：炼金/深度炼金产出点亮（合成仅小加成，不点亮炼金图鉴【工程推导】）。

---

## 三、调合能量条（ENG）

> 依据：2c4f ENG-01~10；R-08（仲裁）。接口落点：`settings.alchemy` + 玩家存档（energy 当前值 + `energy_last_regen_ts`）。

| # | 契约 | 行为 |
|---|---|---|
| ENG-01 | **默认关**（R-08） | `settings.alchemy.energy_enabled: false`（默认）；内容包显式开启后全部规则生效；关闭时 /炼金 /深度炼金 /即时调合 不扣能量、无上限显示、无「能量不足」模板（不干预炼金节奏）；mode=simple 本就无能量条 |
| ENG-02 | 解锁 | 见习解锁能量条；上限随职业等级 |
| ENG-03 | 上限 7 档 | `energy_max: {见习:5, 正式:8, 精通:10, 专家:12, 大师:15, 宗师:18, 王:20}`（可配）；显示「能量 0/10」 |
| ENG-04 | 每炼金消耗 1 格 | /炼金 开会话扣 1 格；/深度炼金 扣 1 格；批量 N 次扣 N 格（BATCH-03）；/即时调合 扣 1 格（结算时扣）；不足 → 「能量 0/10，等 30 分钟回 1 格，或 /合成 保底」 |
| ENG-05 | 恢复 30 分钟 1 格 + **懒计算** | `energy_regen_sec: 1800`（可配）；存档 `energy_last_regen_ts`，查询/消耗时按 `(now - last_regen_ts) / energy_regen_sec` 补格、上限封顶（对齐三周期懒计算同款口径） |
| ENG-06 | 安全区 2 倍速 | 【工程补白：定稿 L95 仅言「休整/安全区可加速」未给数值】`energy_regen_sec_safe: 900`（新增，可配）：玩家当前场景为安全区/休整态时按 safe 间隔补格（2 倍速），离开恢复 1800 基准 |
| ENG-07 | 合成豁免 | 合成不耗能量（保底通道永可用）；/合成 指令不检查能量 |
| ENG-08 | 保底定位 | 能量空 = 软节奏（防无限刷）不卡死体验：能量 0 时 /合成 仍可用 |
| ENG-09 | 存档 | **能量当前值 + `energy_last_regen_ts` 统一存 persistent_state 桶**（自由 JSON 折入，data/player.py L93；与数据与校验子文档统一，**不落 proficiency dict**）；热重载不丢 |
| ENG-10 | 门槛挂载 3 指令 | /炼金（L321）/深度炼金（L325）/即时调合（L336）在 `energy_enabled=true` 时统一走能量前置守卫；关闭时守卫直通 |

---

## 四、品质系统（QLT）

> 依据：2c4e QLT-01~13；拍板②。接口：品质判定函数（本域新建，见 IF-43 归口 Registry + 判定引擎内部）。

### 4.1 档位与系数（QLT-01 ~ QLT-05）

- **品质唯一注册表**：四档 `common/uncommon/rare/legendary`（中文 **普通/精良/史诗/传说**）；炼金/强化/锻造跨系统引用同一注册表，不重复定义（拍板②）；L150 旧名「优秀/稀有」**废弃**。
- **档位数可配**：3/5/7、0=不限制；**四档为默认模板**。
- **档位判定函数**：`score ∈ [lo, hi] → 档位`；`quality_tiers: {common:[0,39], uncommon:[40,59], rare:[60,79], legendary:[80,100]}`（可配）；品质分 0-100 整数口径（计算用），四舍五入取整后落档；80 分即传说、79 分仍史诗。
- **档位边界不可重叠**：39/40、59/60、79/80 为跳档点；配置校验器对档位数/区间合法性**只提示不拦截**（对齐 L411，QLT-03）。
- **品质系数**：`quality_coef: {common:0.8, uncommon:1.0, rare:1.2, legendary:1.5}`（可配，数值不变）——只放大效果数值，不改效果结构。
- **珠等级 = 品质档**（QLT-05）：装饰珠等级直接取品质档；槽级→珠档映射 1 级=普通 / 2 级=精良及以下 / 3 级=全部（归《战斗资源》子文档珠章节）。

### 4.2 成品品质分判定（QLT-06 / QLT-07）

- **【工程补白：聚合公式显式标注】定稿未给材料→成品聚合公式**，实现层取最小必要推导：**成品品质分 = 全部投料材料品质分均值（四舍五入取整）**，再受 4.3 修正；基础调合 **100% 成功，绝不吞材料**（QLT-06）。
- 批量 = 按平均品质出货（同均值口径）、**丢特性**；单件逐项调合才进入特性继承流程（QLT-07 / BATCH-02）。

### 4.3 上限叠加与降级（QLT-08 ~ QLT-10）

| # | 规则 | 行为 |
|---|---|---|
| QLT-08 | 品质上限三处叠加（互不冲突） | ① SP「品质上限+10」（可多次）；② 核心镶嵌「品质上限+X」（大师）；③ 挑战成功「品质上限+10」（可配）。上限提升只放宽品质分**可达上限**，档位判定仍按 4.1 区间，**品质分 ≤100** |
| QLT-09 | 加成道具 | /加成 <道具>（宗师，限 1 次/调合）：品质均值结算后施加（例：贤者之石 品质+30） |
| QLT-10 | 未达标 = 降级不失败 | 任何未达标（属性刻度未达标等）**不失败、不吞材料**：差一档降一档，**最低普通**封底——传说刻度全不达标 → 降至普通仍出货 |

### 4.4 属性刻度 × 品质联动（QLT-11 ~ QLT-13）

- 刻度机制：配方 `element_req: {元素: [{阈值, 效果}]}`；投料累计元素值 ≥ 阈值 → 效果显现；刻度效果 = 效果系统 L0 原子动作。
- 双向联动：① 达标 → 效果显现且品质不受影响；② 未达标 → 品质降级（QLT-10）；③ 反馈分级：第 2 层引导语（"火系还差一点，试试多投火系材料？"）、大师级精确阈值（"火 42/45"）。
- 门槛：刻度效果显现需炼金职业 ≥ 精通（精通前达标不显现）；链式投料段数 → 效果等级（chain_map，1 段=1 级…6 段=6 级，可配）；同属性判定 = 材料当前属性（触媒改变后按新属性）。

---

## 五、特性体系（TSC / INH）

### 5.1 traits.json 7 字段 schema（TSC-04 ~ TSC-10）

| 字段 | 类型/枚举 | 契约 |
|---|---|---|
| `id` | string | 唯一标识；【工程补白：命名**禁空格**/禁保留字符 `* , = +`（对齐分隔符规范）】；被成品实例 `traits` 数组与会话快照引用；快照/存档冗余存 ID+名称（热重载删配置降级不报错） |
| `name` | string | 展示名；投料反馈清单/成品消息//继承 参数均用 name 匹配 |
| `rarity` | normal \| super | **super = 超特性（金色超特性）**；PP 消耗翻倍（pp_cost.super=2），普通 1；rarity 是 PP 计价唯一依据 |
| `effects` | L0 原子动作列表 | 引用效果系统 L0 词汇表（ID 引用，热重载自动迁移）；特性自身不内联实现逻辑 |
| `group` | string（互斥组） | **组内最多 1 项**：继承选择与成品共存两层面互斥；编辑器校验器做互斥组校验 |
| `repeatable` | boolean（默认 false） | false = 不可重复继承/成品上不重复出现；true = 允许重复（受效果叠加规则约束） |
| `source` | 素材 \| 成品 \| 金色素材 | 决定投料后特性进入哪个可继承池：普通素材→普通池；金色素材→超特性池（第 4 位）；成品→原样入池 |

- traits.json 为特性**唯一数据源**（TSC-01）；觉醒/潜力/核心表并入 traits.json 效果表（复用原子动作，TSC-01）。
- 两套词条分工（TSC-03）：`base_effects` = 固定基础效果（标准版/标准珠只有这个）；`traits` = 品质浮动 + 可继承（炼金/深度独有）；标准版 traits 恒空。

### 5.2 超特性（TSC-11 ~ TSC-14）

- `rarity=super` 即超特性；**继承超特性需炼金职业 ≥ 宗师**。
- **第 4 位独占**（TSC-12）：超特性占第 4 特性位（普通位 3 个之外），默认 `gold_slot_exclusive: true`（可配关闭；关闭后与普通共用位池仍受位上限约束）。
- 触发来源（TSC-13）：稀有金色素材投料（素材继承）——素材自身 `source=金色素材` 的特性才进超特性池；无金色素材 → 超特性位空缺、/继承超 无可选项。
- PP 消耗（TSC-14）：超 PP2 / 普通 PP1（`pp_cost`）；PP 预算 = 配方卡 PP 上限（例：火焰弹 5/5），会话内消耗、`pp_refresh:"会话重置"`。

### 5.3 进化特性（TSC-15 ~ TSC-18）

- 定义：/特性合成 产出更高位特性（两同系特性融合升级），极限 build 天花板；解锁 = 宗师。
- 合成引擎映射：`kind=upgrade` 配置实例——inputs=2 同系特性、cost=宝石 20 + 材料（可配 `gem.特性合成`）、output=更高位特性。
- 示例：/特性合成 攻击+15% + 攻击+10% → 攻击+25%；产物为新特性条目，原两条被消耗。
- 与配方进化线区分（TSC-18）：/进化 只继承「继承槽位余量 + 投入次数 + 平均品质」，**特性不继承**——两条独立路径。

### 5.4 继承四规则族（INH-01 ~ INH-16）

| 族 | 规则 |
|---|---|
| **来源** | 材料带特性进可继承池（INH-01）；三渠道供特性——采集（稀有/金色/✨）/种植（种子继承、收获品质 ≥ 种子品质）/代工（助手等级→特性更多）（INH-02）；投料反馈附可继承特性清单（名称+PP）（INH-03）；全物入料（专家，成品 source 原样入池）（INH-04） |
| **传递** | /继承 `<特性1>,<特性2>…`（`,` 列表）继承普通；/继承超 继承第 4 位（INH-05）；普通位默认 ≤3（可配 1-6），超 3 项 → 错误模板「继承超 3 项」（INH-06）；**单件才有继承，批量丢特性**（INH-07）；所选特性随 /确认 写入成品 `traits`；觉醒（✨素材，宗师）→ 附加隐藏效果、潜力（属性超隐藏阈值，宗师）→ 独立隐藏能力（均并入 traits 效果表）（INH-08）；会话内 PP 预算、pp_refresh=会话重置、不足 → 「PP 不足」（INH-09） |
| **冲突** | `group` 互斥组内最多 1 项：/继承 与已选同组 → 拒绝并提示（或提示替换）；结算校验成品无同组并存（INH-10）；repeatable=false 不可重复、true 可重复（受叠加规则约束）（INH-11）；**负面特性**（宗师）：继承强力特性需承受 1 个同源负面（占特性位/效果生效）（INH-12）；编辑器校验器互斥组校验（组名/成员存在性/同特性多组/引用失效兜底）（INH-13） |
| **等级化** | 正式 1 → 精通 2 → 专家 3，见习无继承位（/继承 → 拒绝「无继承位」）（INH-14）；SP「特性位+1」可多次、与职业等级位叠加（例：专家 3 + SP×2 = 5）（INH-15）；/特性合成（宗师+宝石 20+材料）（INH-16） |

### 5.5 成品存储与显示（STO-01 ~ STO-09，简）

- 存储：成品实例落 `quality`/`elements`/`traits`/`awaken`/`rarity`（STO-01）；珠堆叠键 = **ID + 品质档 + 特性集**（同键堆叠、键变分堆）（STO-02）；会话快照存 配方ID+材料链+连锁+特性+触媒+PP+步骤+version（STO-03）；热重载冗余 ID+名称（STO-05）。
- 显示：品质文字档「品质 <分>·<档位文字>」（「品质 72·精良」）（STO-06）；成品消息展示继承特性效果（STO-07）；刻度悬念分级（引导语/精确阈值）（STO-08）；委托三档评价 + 品评会四维评分共用品质档+特性集口径（STO-09）。

---

## 六、投料与触媒（FEED / AUTO / BATCH / CAT）

> 依据：2c4f 一~二节；解析顺序对齐【分隔符】L65-74。指令语法细节归《指令契约》，本节只钉核心机制语义。

### 6.1 链式投料（FEED-01 ~ FEED-10）

- **解析顺序（写死）**：先按 `,` 拆列表 → 再按 `*` 拆数量 → 再按 `=` 拆键值（【分隔符】L69）；全角/半角等价、不空格；`/投料 追加 <材料>` 追加子词。
- 会话前置：无会话 → 「当前没有调合会话，先 /炼金 <配方> 开始」；战斗中 → 「战斗中使用 /即时调合 <配方>（不进入调合会话）」。
- 槽位上限：不超配方 `slots`（「投料超槽位」；深度层 6 槽/核心槽）。
- 材料持有：逐项校验，不足全拒+差异提示（原子口径）。
- **连锁段数**：段数 = 相邻同属性对数（连续 n 个 = n-1 段）；同属性判定 = 材料**当前**属性（触媒改变后按新属性）；段数 → 效果等级 `chain_map`（1 段=1 级…6 段=6 级，可配）。
- **属性刻度**：累计材料属性对照 `element_req` 阈值；未达标 = 品质降级（差一档降一档，最低普通，绝不吞材料）。
- 反馈：附可继承特性清单；金色素材 → 超特性候选；✨素材 → 觉醒候选；连锁 ≥3 段 → 连锁奖励候选。
- 全物入料：专家起成品/装备可入料（按 items.json 元素/特性/品质折算材料属性）。
- /确认 全量复核材料（含追加链）仍在背包，不足拒绝+差异提示（防过期快照）。

### 6.2 一键投料（AUTO-01 ~ AUTO-03）

- `/炼金 <配方> 自动`（固定子词 `自动`）：机器人按配方 `materials` 清单 + 背包持有自动配平入料（小白兜底）。
- 配平优先级：优先 `element_req` 达标组合 → 其次配方基础材料；配平结果照常进入连锁/刻度/特性候选计算。
- 配平失败 → 全拒+差异提示（缺 水结晶×5 同款），不部分入料。

### 6.3 单批量（BATCH-01 ~ BATCH-05）

- 触发：`/炼金 <配方>*<N>`（数量 `*` 对齐分隔符规范；N=1 默认逐项调合；N≥2 单批量一步出结果）【工程补白：定稿未给批量触发语法，取 `*` 对齐 L32 同款】。
- 批量产出 = **平均品质、丢特性**：无特性/无连锁奖励/无刻度效果；熟练经验按每个成品 = 配方等级 ×1。
- 能量按次：批量 N 次 = 扣 N 格（ENG-04/BATCH-03），指令执行时一次性原子扣减。
- **数量上限（拍板⑤）**：默认 **2147483647（int32 max）**、可配（覆盖【分隔符】L33 的 ≤99 默认）；超限提示「最多一次使用 N 个」（N=配置上限）**不拦截**（对齐 L73 只提示不拦截）。
- 原子性：材料 ×N + 能量 N 格 + 金币全量满足才执行，否则全拒+差异提示；单事务提交，任一步失败 ROLLBACK 零副作用。

### 6.4 触媒（CAT-01 ~ CAT-06）

| # | 契约 | 行为 |
|---|---|---|
| CAT-01 | **解锁等级（R-07 定案）** | 专家解锁（定稿 L84 专项表 vs L154 行内「精通」冲突 → 按细化_0 R-07 采纳 = 专家）；`settings.alchemy.catalyst_unlock_tier: "expert"`（默认 expert，可配）；未达 → 「等级不足」 |
| CAT-02 | 作用 | 同材料 + 不同触媒 = 不同方向：触媒改变材料属性判定（连锁/刻度按新属性）与成品效果方向 |
| CAT-03 | 注册制 | 未注册触媒 → 仅提示（不阻断）；指定语法 `/炼金 <配方> 触媒=<触媒名>`（键值 `=`） |
| CAT-04 | **消耗【工程补白】** | 定稿未明示消耗——实现默认：每次调合确认结算消耗触媒 1 个（与材料同事务扣减，纳入 /确认 全量复核）；`catalyst_consume: true`（可配 false = 不消耗仅作方向修饰） |
| CAT-05 | 类型与校验 | 触媒必须 `items.json type=触媒`；非触媒 → 「触媒无效」；编辑器触媒下拉按 type 过滤 + 校验器存在性 |
| CAT-06 | 面板展示【工程补白】 | 定稿面板示例不含触媒项、未定义展示——若实现展示属实现层细化（证据缺口）；指定走 `触媒=` 语法 |

---

## 七、调合会话状态机（§4.6）

> 依据：2c4a CASC-08；m8_batch_plan 批3；接口摸底 二（SessionManager 占位 + repository 会话持久化 + settle_exit_idempotent 模式）。

### 7.1 状态迁移表

| 当前状态 | 触发 | 下一状态 | 动作 | 终态? |
|---|---|---|---|---|
| （无会话） | /炼金 <配方>（或 /深度炼金） | 会话中 | `acquire` 成功 → 扣能量（ENG-04）→ 面板渲染 | 否 |
| （无会话） | /投料 /继承 /确认 /放弃 | （无会话） | 非法转移模板「当前没有调合会话，先 /炼金 <配方> 开始」 | — |
| （无会话） | /炼金 但已有其它会话 | （拒绝） | `SessionConflictError` → 「已有活跃会话」模板（全局互斥，私聊+多群） | — |
| 会话中 | /投料 追加 /继承 /继承超 /加成 /确认 | 会话中 | 状态更新（材料链/连锁/特性/PP/步骤），version 递增 | 否 |
| 会话中 | /炼金 <新配方>（再发） | （拒绝） | 拒绝模板「调合进行中！/放弃 退出 或 /调合续 继续」（定稿 L176） | — |
| 会话中 | 战斗打断 | **挂起(战斗)** | `suspend`：快照持久化（配方ID+材料链+连锁+特性+触媒+PP+步骤+version） | 否 |
| 挂起(战斗) | /调合续（或 /炼金 恢复） | 会话中 | `restore` 恢复快照（特性选择与 PP 状态不丢） | 否 |
| 挂起(战斗) | /调合续 但已有活跃会话 | （拒绝） | 「已有一个调合会话进行中」（定稿 L177） | — |
| 会话中 | /确认 | **终态** | 品质结算（四）→ 产出入包 → `settle_exit_idempotent` 同款终态结算 | ✅ |
| 会话中 | /放弃 | **终态** | 退还材料（或按放弃规则）→ 终态结算 | ✅ |
| 会话中 | /确认（重复） | 终态（幂等） | version 幂等：sessions.version 列映射，重复确认 → 「已结算」（不双扣） | ✅ |
| 挂起(战斗) | 超过 30 天未活动 | **僵尸回收** | `recycle_scan(max_days=30.0)` + settle 回调结算（lifecycle.recycle_days），**终态回调含已投材料返还**（定稿 L183「僵尸会话回收（材料返还）」） | ✅ |

### 7.2 契约要点

- **version 幂等**：调合会话快照 `version` 映射 sessions 表 `version` 列（默认 1，schema.py L58-69）；重复 /确认 → 判定已结算，不双扣材料/能量/金币。
- **全局互斥**：`sessions.player_qid` 主键天然互斥（单玩家 1 会话，私聊+多群全局）；`SessionConflictError` 领域异常（world/session.py L20）由壳层翻译人话模板。
- **终态结算模式（对齐 `settle_exit_idempotent`，battle_boundary.py L821）**：单事务 `delete_session(qid) + write_idem_key(key)`（command=`"settle:{kind}"`），幂等键 = (message_id, group_id, player_qid)；调用方不得在已持有 repo.tx() 内调用（防嵌套事务）。调合会话的 /放弃 /确认 终态**仿照此模式**（M8 决策 1）。
- **僵尸回收**：复用 `recycle_scan`（30 天，`lifecycle.recycle_days` 可配），settle 回调由 SessionManager 注入；**终态回调必须含已投材料返还口径**（定稿 L183「僵尸会话回收（材料返还）」）——无 settle 默认不删，防静默丢材料/吞材料。
- **战斗即时调合不进入本状态机**：/即时调合 为战斗内子流程——不新开会话/不挂起战斗/不申请会话槽/豁免互斥（INST-02）；本状态机「挂起(战斗)」仅用于战斗外调合被战斗打断。
- **接口缺口**：`world/session.py` SessionManager 5 方法当前全占位（NotImplementedError，L24-40）——**M8 实装**（装配注入点 `assembly/bootstrap.py` L61 `session_mgr=SessionManager()` 已就位）。

---

## 八、IF 接口清单（真实签名）

> 来源：`docs/m8_接口摸底.md` + 代码原文复核。**签名一律来自代码真实定义，禁止实现组凭印象改写**。实现批次对照 `m8_batch_plan.md` 批号。

### A. 存储层 Repository 系列（IF-01 ~ IF-10）— `qbot_rpg/storage/repository.py`

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-01 | 读玩家 | `async def load_player(self, qid: str) -> Optional[Player]`（L442） | 会话恢复/能量懒计算/熟练度读取 | 批3 |
| IF-02 | 写玩家 | `async def save_player(self, player: Player) -> None`（L473） | 结算/熟练/能量/SP 落盘 | 批3 |
| IF-03 | 读会话 | `async def load_session(self, qid: str) -> Optional[Tuple[str, object, int, int, str, str]]`（L563）——返回 `(session_type, payload, random_seed, version, created_at, last_active_at)` | SessionManager.restore/get_active | 批3 |
| IF-04 | 僵尸回收 | `async def recycle_scan(self, *, settle: Optional[Callable[[Player, object], Optional[Player]]] = None, max_days: float = 30.0, now=None, allow_unsettled=False) -> List[str]`（L720） | 调合会话 30 天回收（lifecycle.recycle_days） | 批3 |
| IF-05 | 事务上下文 | `@contextlib.asynccontextmanager async def tx(self) -> AsyncIterator["RepoTransaction"]`（L412） | 所有原子操作（合成/炼金/分解/结算） | 批2 |
| IF-06 | 会话 upsert | `async def upsert_session(self, session: SessionRow) -> None`（L887）——`ON CONFLICT(player_qid) DO UPDATE` | SessionManager.acquire/suspend | 批3 |
| IF-07 | 会话删除 | `async def delete_session(self, qid: str) -> None`（L904） | 终态结算/放弃/回收 | 批3 |
| IF-08 | 幂等键 | `async def write_idem_key(self, key: IdemKey) -> None`（L922）/ `async def idem_exists(self, key: IdemKey) -> bool`（L932） | 终态结算防双扣 | 批3 |
| IF-09 | 会话行 | `SessionRow(player_qid, session_type, payload: object, random_seed, version=1, created_at="", last_active_at="")`（L289） | 调合会话快照载体（payload=JSON dict） | 批3 |
| IF-10 | 编解码 | `player_to_row(player: Player) -> Dict[str, Any]`（L143）/ `row_to_player(row) -> Player`（L234） | proficiency dict 落存档（M8 决策 4：不加字段） | 批3 |

### B. 会话管理（IF-11 ~ IF-19）

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-11 | acquire | `def acquire(self, player_qid: str, session_type: str) -> Any`（world/session.py L27，**当前占位 NotImplementedError，M8 实装**） | /炼金 /深度炼金 开会话 | 批3 |
| IF-12 | release | `def release(self, player_qid: str) -> None`（L30，占位） | 终态/放弃释放 | 批3 |
| IF-13 | get_active | `def get_active(self, player_qid: str) -> Optional[Any]`（L33，占位） | 会话前置守卫/互斥判定 | 批3 |
| IF-14 | suspend | `def suspend(self, player_qid: str, snapshot: Any) -> None`（L36，占位） | 战斗打断 → 挂起 | 批3 |
| IF-15 | restore | `def restore(self, player_qid: str) -> Optional[Any]`（L39，占位） | /调合续 恢复 | 批3 |
| IF-16 | 互斥异常 | `class SessionConflictError(Exception)`（L20，已定义） | 全局互斥翻译人话模板 | 批3 |
| IF-17 | 终态结算模式 | `async def settle_exit_idempotent(*, session: object, settlement_kind: str, message_id: str, repository: object) -> bool`（world/battle_boundary.py L821） | /确认 /放弃 终态（仿照；幂等键 command=`"settle:{kind}"`） | 批3/6 |
| IF-18 | 互斥判定 | `session_mutex_decision(...)`（world/battle_boundary.py L702） | 战斗/调合会话互斥复用 | 批3 |
| IF-19 | 装配注入点 | `session_mgr=SessionManager()`（assembly/bootstrap.py L61） | M8 实装接线 | 批3 |

### C. 背包引擎（IF-20 ~ IF-23）— `qbot_rpg/core/inventory.py`

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-20 | 入包 | `def add_item(self, player: Any, item: Any, count: int = 1) -> Any`（L183）——返回 `{ok, added, rows, new_rows, truncated, message?}` 或 `{ok:False, reason, message?}` | 成品/宝石/回收入包 | 批2/4/6 |
| IF-21 | 扣减 | `def remove_item(self, player: Any, item_id: str, count: int = 1) -> Any`（L254）——`{ok, removed}` 或 `{ok:False, reason: "not_enough"|"bound"}` | 投料/合成/分解扣材料（不部分扣减） | 批2/4 |
| IF-22 | 计数 | `def count(self, player: Any, item_id: str) -> int`（L308）——跨行求和 | 原子校验/配平 | 批2/4 |
| IF-23 | 物品实例 | `@dataclass(frozen=True) class ItemInstance: item_id/name/count/quality/bound/stack_max=99/slot/stats_bonus/traits=()/cooldown_until`（data/item.py L20-37） | 成品品质/特性直接由实例携带；`traits` tuple 冻结语义 | 批0/4/5 |

### D. 熟练度/等级（IF-24 ~ IF-25）— `qbot_rpg/core/levelup.py`

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-24 | SP 发放 | `def _grant_sp(self, player: MutableMapping[str, Any], job_id: str) -> int`（L117）——`proficiency.<job_id>.sp_earned += sp_per_level` | SP 面板/升级联动；**proficiency dict 形态对齐点** | 批1 |
| IF-25 | 经验入账 | `def gain_exp(self, player: Any, amount: int) -> Any`（L133）——返回 `{ok, level, level_ups, sp_earned_delta, hp_restored, mp_restored, exp_next}` | 熟练经验来源（制作/采集/战斗）入账 | 批1 |

### E. 条件/公式引擎（IF-26 ~ IF-28）

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-26 | 熟练度条件 | `VAR_ALIASES["[熟练度:{T}]"] = ("prof_level", "{T}")`（engine/condition_engine.py L161）；`VAR_CATEGORIES["熟练类"] = ("prof_level",)`（L131）——**已注册** | 委托/任务/商店熟练度门槛 | 批1 |
| IF-27 | 宝石公式变量 | `"[宝石]": ("attacker", "gem")`（core/formula_engine.py L218）——**已预留** | 分解/挑战/品评会宝石入账公式 | 批6 |
| IF-28 | 熟练度公式变量 | `("熟练度:", "attacker", "prof")`（L246）——**已预留** | 熟练度相关公式 | 批1 |

### F. 战斗接线（IF-29 ~ IF-31）— `qbot_rpg/core/battle.py`

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-29 | 战斗快照 | `def to_snapshot(self, boundary: Optional[str] = None) -> Dict[str, Any]`（L1740）——返回 dict；**`battle_alchemy_used` 新增顶层键（M8 决策 2）**，中断恢复不清零 | 即时调合限次计数 | 批9 |
| IF-30 | 行动执行 | `def do_action(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome`（L1031） | 即时调合一步出结果 | 批9 |
| IF-31 | 道具行动入口 | `def _resolve_item_action(self, attacker, action)`（L1162） | 即时调合走战斗道具路径 | 批9 |

### G. 指令注册（IF-32 ~ IF-37）— `qbot_rpg/commands/`

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-32 | 解析主入口 | `parse_command(raw, *, command_mode=MODE_GLOBAL_SHORTCUT, require_at=False, shortcuts=None, aliases=None, whitelist=None, prefix_required=None, gm_commands=None, session_active=False, in_battle=False, max_qty=99, quantity_commands=None, no_quantity_commands=None, free_arg_commands=None, command_specs=None) -> ParsedCommand`（parsers.py L586-603） | 全部 M8 指令；`max_qty` 参数用于拍板⑤上限 | 批11 |
| IF-33 | 固定子词 | `FIXED_SUBWORDS = frozenset({"追加","预览","自动","查看","确认","放弃","续"})`（L99）——M8 用「自动/确认/放弃/续」已在 | /投料 追加、/炼金 自动、终态 | 批11 |
| IF-34 | 白名单 | `DEFAULT_WHITELIST` 已含 合成/炼金/锻造/强化/调合/镶嵌/拆珠（L112）、投料/代工/继承（L125）、图鉴（L121） | 新指令白名单补齐 | 批11 |
| IF-35 | 数量语法 | `DEFAULT_QUANTITY_COMMANDS = {使用,购买,合成,投料,出售,炼金,调合}`（L149）；`DEFAULT_MAX_QTY=99`（L155）——**M8 按拍板⑤以 settings `max_qty` 覆盖默认，默认 2147483647** | /合成 /炼金 /投料 数量 `*` | 批11 |
| IF-36 | 注册 | `CommandSpec(name, *, aliases=None, permission=PERM_USER, cooldown_seconds=0.0, handler=None, whitelisted=True, is_gm=False)`（router.py L140-184）/ `Router.register(spec, *, replace=False)`（L187） | register_alchemy_commands | 批11 |
| IF-37 | handler 模式 | `cmd_xxx(parsed: Any, ctx: MutableMapping[str, Any]) -> str`（战斗壳返回 dict）+ `register_xxx_commands(router, *, make_context=None)` | alchemy_commands.py 新建（仿 shop_commands） | 批11 |

### H. 内容加载与校验（IF-38 ~ IF-43）

| # | 接口 | 真实签名（行号） | 调用方 | 批次 |
|---|---|---|---|---|
| IF-38 | 模块 kind 登记 | `_KIND_FOR_MODULE`（content/loader.py L150-172）——**traits 已登记（L158）；recipe/proficiency 未登记，M8 补** | recipe/proficiency 四件套 | 批0 |
| IF-39 | 字段元数据 | `ModuleMeta(entry_type, fields, kind, namespace, key_regex, value_meta, chain_field, mutex_field)`（content/field_meta.py L441）——traits 已登记（L326-332 + L418） | recipe/proficiency 模块登记 | 批0 |
| IF-40 | settings 段登记 | `SETTINGS_FIELDS`（field_meta.py L206-209，现仅 currencies/death_penalty）——**alchemy 段加段登记** | `_check_settings_alchemy` 生效前提 | 批0 |
| IF-41 | 校验器入口 | `check_pack`（公开入口 content/validator.py **L1793**；内部 `_Checker.run` L383）；专项派发 `_check_module`（L465）——模式 `validate_xxx(modules, report) -> None` | validate_recipes/validate_traits/validate_proficiency | 批0 |
| IF-42 | settings 专项 | `_check_settings_1g4`（L1329）模式——**M8 新增 `_check_settings_alchemy`**（energy_enabled 布尔 / catalyst_unlock_tier ∈ 职业枚举 / gem 费率 / job_tier_map / quality_tiers 单调 / max_qty） | settings.alchemy 段校验 | 批0 |
| IF-43 | 注册表解析 | `Registry.resolve(id, kind) -> AnyDef`（registry.py L82）/ `build`（L163）/ `resolve_name(id: str) -> Optional[str]`（L86，ID→显示名，**非** `(name, kind)`）；按 name 匹配需新增 `resolve_by_name(name, kind)`（**工程补白·需新增**）或改用 `resolve(id, kind) + all_ids(kind)` 遍历 | recipe/traits/proficiency 数据读取 | 批0 |

> **IF 统计：共 43 条**（A 存储 10 + B 会话 9 + C 背包 4 + D 熟练度 2 + E 条件/公式 3 + F 战斗 3 + G 指令 6 + H 内容 6）。
> 待实装标记：IF-11~15（SessionManager 5 方法，M8 决策 1 实装）；IF-38/39/40/41/42（recipe/proficiency/alchemy 登记与校验器）；IF-29（battle_alchemy_used 顶层键）。

---

## 九、验收 TC 矩阵（与章节映射）

> 用例全文见各细化文档，此处仅映射归属，不重写全文。门禁：批12 verify_m8 承载 179 TC（2c4a 26 + 2c4b 25 + 2c4c 30 + 2c4d 34 + 2c4e 26 + 2c4f 38）；本子文档覆盖 2c4a + 2c4e + 2c4f 共 90 例。

### 9.1 2c4a（26 例）映射

| TC 段 | 用例 | 归属章节 |
|---|---|---|
| TC-01 ~ TC-06 | 各层解锁（合成/炼金/深度炼金门槛、区间校验、无职业拒绝、大师解锁公告） | 一（LAY/CASC）+ 二（job_tier_map） |
| TC-07 ~ TC-14 | 防跳层（synth_allowed 拦/提示、跨职业只通合成、进化计数、王图鉴、会话分离、区间防跳、继承等级化） | 一（CASC-03~10）+ 二（2.5）+ 五（INH-14） |
| TC-15 ~ TC-23 | 产出边界（标准版无特性、合成数量上限、品质系数、刻度降级、深度机制全集、分解回收率+宝石、标准珠 vs 炼金珠、能量消耗/豁免、原子校验） | 一（LAY-04）+ 二 + 三（ENG）+ 四（QLT） |
| TC-24 ~ TC-26 | 三渠道衔接（材料 id 入包识别、种子继承特性、代工产物连锁判定） | 五（INH-02）+ 六（FEED） |

### 9.2 2c4e（26 例）映射

| TC 段 | 用例 | 归属章节 |
|---|---|---|
| TC-01 ~ TC-06 | 品质判定（边界落档、均值口径、系数、批量丢特性、上限叠加、加成道具） | 四（QLT-01~09） |
| TC-07 ~ TC-11 | 属性刻度×品质（达标显现、降级不吞、最低普通、精通显现门槛、悬念分级） | 四（QLT-11~13） |
| TC-12 ~ TC-17 | 特性继承（等级化位、SP 位、可继承清单、PP 预算、种子继承、全物入料） | 五（INH-01~09/14/15） |
| TC-18 ~ TC-21 | 冲突规则（互斥组、repeatable、负面特性、编辑器校验） | 五（INH-10~13） |
| TC-22 ~ TC-26 | 超特性与进化特性（第 4 位独占、gold_slot_exclusive、PP2、特性合成 upgrade、进化不继承特性） | 五（TSC-11~18） |

### 9.3 2c4f（38 例）映射

| TC 段 | 用例 | 归属章节 |
|---|---|---|
| TC-01 ~ TC-14 | 投料三通道（链式解析/追加/无会话/槽位/战斗拦截/数量解析/连锁段数/刻度/全物入料/一键配平/配平原子拒/批量平均品质/能量按次/数量上限） | 六（FEED/AUTO/BATCH）+ 三（ENG） |
| TC-15 ~ TC-20 | 触媒（专家解锁 R-07、方向修饰、注册制、非触媒拒绝、等级不足、确认全量复核+消耗） | 六（CAT-01~06） |
| TC-21 ~ TC-30 | 能量条（上限 7 档、每炼金扣 1、合成豁免、能量空提示、懒计算补格、安全区 2 倍速、默认关、存档） | 三（ENG-01~10） |
| TC-31 ~ TC-38 | 即时调合（战斗内子流程、限 1 次/场、中断不清零、战斗结束清零、豁免互斥、指令拦截、auto_use、门槛与消耗） | 七（7.2）+ 兄弟子文档《战斗资源》 |

---

## 十、铁律与拍板（本域专属）

### 10.1 本域铁律

1. **接口签名纪律**：八章全部签名来自 `docs/m8_接口摸底.md` + 代码原文复核，实现组不得凭印象改写；新增调用前先 grep 调用方（拦截链接线）。
2. **proficiency 存档形态**：保持 `player["proficiency"]` **dict 形态**（对齐 levelup.py L117-128），Player dataclass 不加字段——M8 决策 4。
3. **会话终态幂等**：/确认 /放弃 终态必须走 `settle_exit_idempotent` 同款模式（单事务 delete_session + write_idem_key，command=`"settle:{kind}"`），调用方不得嵌套 repo.tx()。
4. **原子防双扣**：合成/炼金/分解/结算类操作 SQLite 事务 + message_id 幂等；任一材料/能量/金币不足全拒+差异提示，绝不部分执行。
5. **解析顺序写死**：`先 , 再 * 再 =`（对齐【分隔符】L69）；批量不抄 `+`；特性名内数值 `+` 保留。
6. **未标【工程补白】不得新增定稿外行为**：所有证据缺口实现默认均已显式标注（品质均值口径 QLT-06 / 安全区 2 倍速 ENG-06 / 触媒消耗 CAT-04 / 批量触发语法 BATCH-01 / 王图鉴点亮 CASC-06）。
7. **校验器只提示不拦截**（品质档位数/区间 QLT-03；synth_allowed 提示 CASC-04；数量超限 BATCH-04）。

### 10.2 用户 5 项拍板（本域相关 ②⑤ 全量体现；其余标注归属）

| # | 拍板 | 本域落点 |
|---|---|---|
| ① | 分解宝石 = 平铺基础值（普通1/精良3/史诗8/传说20，不乘回收率）+ 公式可配 | 归《战斗资源》；本域品质档基准 四 QLT-01 为宝石平铺值的档位索引 |
| ② | **品质档键名 common/uncommon/rare/legendary（中文 普通/精良/史诗/传说）；档位数可配 3/5/7、0=不限制，四档默认模板；L150 旧名「优秀/稀有」废弃** | **四 4.1（QLT-01/02/03）——本域铁律** |
| ③ | 珠升阶无职业硬门槛（准入靠槽级 SOCK-02） | 归《战斗资源》；本域 一 LAY-04b 品质档=珠档位基准不变 |
| ④ | 复制费 = ⌊cost.coins×20%⌋ + 可配额外消耗 | 归《战斗资源》 |
| ⑤ | **数量上限默认 2147483647（int32 max，可配 max_qty）+ 超限提示「最多一次使用 N 个」不拦截** | **六 6.3（BATCH-04）+ 八 IF-32/IF-35——本域铁律**（对齐【分隔符】L73） |

### 10.3 配置默认值速查（本域）

| 键 | 默认值 | 依据 |
|---|---|---|
| `alchemy.mode` | `full` | 2c4a LAY-06 |
| `alchemy.energy_enabled` | `false`（默认关） | R-08 / 2c4f ENG-01 |
| `alchemy.energy_max` | 见习5/正式8/精通10/专家12/大师15/宗师18/王20 | 2c4f ENG-03 |
| `alchemy.energy_regen_sec` / `energy_regen_sec_safe` | `1800` / `900`（安全区 2 倍速【工程补白】） | 2c4f ENG-05/06 |
| `alchemy.catalyst_unlock_tier` | `"expert"`（R-07 定案） | 2c4f CAT-01 |
| `alchemy.catalyst_consume` | `true`（消耗 1/次【工程补白】） | 2c4f CAT-04 |
| `alchemy.quality_tiers` / `quality_coef` | common0-39 0.8 / uncommon40-59 1.0 / rare60-79 1.2 / legendary80-100 1.5 | 2c4e QLT-02/04 |
| `alchemy.pp_cost` / `pp_refresh` | normal 1 / super 2；"会话重置" | 2c4e TSC-14 |
| `alchemy.chain_map` | 1 段=1 级…6 段=6 级 | 2c4f FEED-06 |
| `alchemy.max_qty` | `2147483647`（int32 max，拍板⑤） | 拍板⑤ |
| `proficiency.json tier_names` | 7 级（见习→王） | 2c4a JOB-02 |

---

*本子文档全部契约可追溯至：细化_2c4a（LAY/CASC/JOB 编号 + TC-01~26）、细化_2c4e（QLT/TSC/INH/STO 编号 + TC-01~26）、细化_2c4f（FEED/AUTO/BATCH/CAT/ENG 编号 + TC-01~38）、m8_batch_plan（决策 1-6 / 拍板 1-5 / 批0-批13）、m8_接口摸底（51 接口落点）；接口签名经代码原文复核（repository.py / session.py / inventory.py / levelup.py / battle_boundary.py / battle.py / condition_engine.py / formula_engine.py / parsers.py / router.py / loader.py / field_meta.py / validator.py / bootstrap.py / data/item.py）。*
