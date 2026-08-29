# M8 炼金 · 实现批次派工单（m8_batch_plan）

> 生成：2026-08-29 · 依据：6 份细化（2c4a~2c4f 修订版）+ 炼金定稿 v2.3 + 接口摸底（docs/m8_接口摸底.md）+ 用户 5 项拍板（2026-08-29）
> 批次结构：13 个实现批次（批0~批12）+ 1 个审查批（批13），每批 2-3 路并行（上限 3），批间收口（落盘核对+接线+回归+commit）
> 用户预估 14 批 28 路 → 实际 13 实现批（批0/4/7 各 3 路 + 其余 10 批各 2 路 = 29 路）+ 批13 审查批串行 5 路 ≈ 34 路（按实际调整）

## 〇、关键决策（接口缺口定案）

| # | 缺口 | 定案 |
|---|---|---|
| 1 | SessionManager 实装 | **M8 实装**（world/session.py 5 方法对齐 repository 会话持久化 + settle_exit_idempotent 模式），装配层已留注入点（bootstrap.py L61） |
| 2 | battle_alchemy_used | 挂 `core/battle.py to_snapshot()` 返回 dict **顶层键**；中断恢复不清零、战斗结束清零 |
| 3 | recipe/proficiency 四件套 | 照 traits 模式：field_meta ModuleMeta + loader._KIND_FOR_MODULE + validator 专项 + manifest 声明 |
| 4 | proficiency 存档形态 | **保持 dict 形态**（levelup.py 既有模式），Player dataclass 不加字段（避免 repository 大改） |
| 5 | gem 入账管线 | 复用统一 reward 发放器（T48）；settings.currencies 登记 gem=宝石；分解/挑战/掉落/品评会入账走同管线 |
| 6 | settings.alchemy 段 | field_meta.SETTINGS_FIELDS 加段 + validator 新增 _check_settings_alchemy 专项（energy_enabled=false 默认 / catalyst_unlock_tier=expert 默认 / 宝石费率 / job_tier_map） |

## 一、用户 5 项拍板（实现必须遵守）

1. **分解宝石** = 平铺基础值（普通1/精良3/史诗8/传说20，不乘回收率）+ 产出公式可配置（settings 可配项）
2. **品质档键名** = common/uncommon/rare/legendary（中文 普通/精良/史诗/传说）；quality_tiers 档位数可配 3/5/7、0=不限制；L150"优秀/稀有"旧名废弃
3. **珠升阶** = 无职业硬门槛（准入靠槽级 SOCK-02）
4. **复制费** = ⌊配方 cost.coins×20%⌋（只算 coins、向下取整）+ 可配置额外消耗（settings 可配，默认 0）
5. **数量上限** = 默认 2147483647（int32 max，settings 可配 max_qty）+ 超限「最多一次使用 N 个」提示不拦（对齐分隔符 L73）

## 二、批次派工单

### 批0 · 数据层（3 路）
- **路0A recipe/traits/proficiency 数据模型**：content 新增 recipe.json（kind craft/combine/upgrade、materials、cost{coins,gem}、slots、element_req、traits_inherit、catalyst[]、evolve_to、master_only、synth_allowed、combine_from）+ traits.json（id/name/rarity normal|super/effects/group/repeatable/source）+ proficiency.json（tier_names 7 级/每职业熟练值/成长曲线/job_tier_map）；校验器 validate_recipes/validate_traits/validate_proficiency（含进化线无环、特性互斥组、材料/触媒/效果 ID 引用、level 1-99、档位单调）；field_meta 登记 + loader._KIND_FOR_MODULE + manifest
- **路0B items/slots/settings 扩展**：items.json 补 type=装饰珠/quality/elements/traits/awaken/rarity/base_effects/seed + slots.json slot_level + settings.json alchemy 段（mode/quality_tiers/quality_coef/chain_map/pp_cost/energy_enabled=false/energy_max/energy_regen_sec/energy_regen_sec_safe/decompose_rate/gem{分解,复制,成品合成,配方合成,特性合成,珠升阶}/synth_exp/sp_per_level/catalyst_unlock_tier=expert/catalyst_consume/战斗道具/战斗即时调合/数量上限）+ _check_settings_alchemy 专项（值类型/枚举/费率/默认值对齐 R-07/R-08/拍板⑤）
- **路0C fixtures**：test_demo 内容包补 recipe.json/traits.json/proficiency.json + 装饰珠/触媒/材料/炼金成品 items + settings.alchemy 段 + manifest 声明；legal 包同步（校验器红拦零命中）

### 批1 · 熟练度+品质引擎（2 路）
- **路1A proficiency 引擎**：职业等级（熟练经验来源 制作/采集/战斗）、tier 判定（job_tier_map 区间）、SP 面板（sp_per_level 发放、/技能面板 分支自选：品质上限+10/投入次数+1/特性位+1/采集量+1/连锁上限+1，repeatable）、王称号（图鉴全点亮）；存档保持 player["proficiency"] dict 形态
- **路1B 品质系统**：quality_tiers 档位判定（score∈[lo,hi]→档位）、quality_coef 效果系数、成品品质分计算（投料材料均值四舍五入）、未达标降级（差一档降一档最低普通）、SP/核心/挑战品质上限叠加、品质分 ≤100

### 批2 · 合成层（2 路）
- **路2A /合成 引擎+指令**：第 1 层跨职业（任一制造/资源技能达标即可）、synth_allowed 校验（深度配方默认 false，改 true 提示"将绕过深度炼金玩法"不阻断）、原子校验（材料+金币全量满足否则全拒+差异提示）、标准版产出（品质固定无特性）、熟练经验=配方等级×1、合成图鉴点亮、数量上限 int32（拍板⑤）不耗能量；指令壳 /合成
- **路2B 合成引擎 kind=upgrade**：通用执行器（inputs N 入/cost{coins,gem}/output 1 出）+ 配置实例：珠三合一升阶（3×同档同 ID+宝石10→+1 阶，禁跳级，无职业硬门槛拍板③）、成品合成（两成品+材料+宝石10）、配方合成（两已学配方+宝石5→解锁，组合表）、特性合成（两同系特性+宝石20+材料→更高位）；组合表（2输入+1输出+条件）+ 玩家级解锁表（SQLite 或 persistent_state）

### 批3 · 会话基础（2 路）
- **路3A SessionManager 实装**：acquire/release/get_active/suspend/restore 对齐 repository.upsert_session/delete_session；单玩家 1 会话互斥（sessions.player_qid 主键天然互斥 + SessionConflictError）；settle_exit_idempotent 仿照（/放弃 /确认 终态结算：delete_session+write_idem_key 同事务）；30 天僵尸回收复用 recycle_scan
- **路3B 调合会话状态机**：无会话→会话中→挂起(战斗)→恢复→确认/放弃 终态；version 幂等（sessions.version 列映射，重复确认→"已结算"）；全局互斥（私聊+多群）；挂起(战斗)恢复（战斗打断→挂起→/调合续 恢复）；非法转移模板（无会话/已有活跃）；战斗即时调合不进入本状态机

### 批4 · 炼金核心（3 路）
- **路4A /炼金 开会话**：门槛（炼金职业见习+/能量 energy_enabled=true 时/会话互斥）、配方准入（job_tier_map 区间）、触媒参数（=键值，专家解锁 R-07 catalyst_unlock_tier）、自动子词、批量*N（N≥2 单批量）、面板渲染（材料/属性刻度/特性位/PP/投入次数）、会话快照（配方ID+材料链+连锁+特性+触媒+PP+步骤+version）
- **路4B /投料 链式**：材料列表 , 解析（先,再*再=）、追加子词、槽位上限、材料持有校验、连锁段数（相邻同属性对数 n-1）、chain_map 效果等级、属性刻度 element_req 累计、反馈附可继承特性清单、全物入料（专家）、战斗拦截模板
- **路4C 一键投料+批量**：/炼金 <配方> 自动 自动配平（优先 element_req 达标组合）、配平失败原子拒绝；批量平均品质丢特性、能量按次扣（BATCH-03）、原子扣减

### 批5 · 特性继承+触媒（2 路）
- **路5A /继承 /继承超**：可继承池（素材/金色素材/成品 source 分类）、PP 消耗（normal 1/super 2）、特性位上限（默认 3 普通可配 1-6 + 超特性第 4 位独占 gold_slot_exclusive）、等级化（正式1/精通2/专家3 + SP 特性位+1）、group 互斥（组内最多1）、repeatable、负面特性（宗师，继承强力特性需承受 1 负面）、结算写入成品 traits
- **路5B 触媒机制**：items type=触媒 校验、注册制（未注册仅提示）、触媒改变材料属性判定（连锁/刻度按新属性）、消耗（catalyst_consume 可配默认 true，/确认 时全量复核）、编辑器下拉（M12 延后，本批只做校验）

### 批6 · 结算+宝石货币（2 路）
- **路6A /确认 品质结算**：品质=投料材料均值×档位系数、未达标刻度降级（最低普通不吞材料）、加成道具（宗师限 1 次/调合）、核心镶嵌品质上限、SP 品质上限、终态 version 幂等（重复确认"已结算"）、确认时全量复核材料在包
- **路6B 宝石货币**：wallet.gem（currencies dict 加 gem 键）、统一 reward 入账（分解/挑战奖励/loot.json gem 列/品评会冠军）、/分解（仅炼金/深度产出可分解、标准版默认不可分解、材料×回收率向下取整、宝石平铺基础值拍板①、两段式消息）、分解公式可配置

### 批7 · 装饰珠+三类合成指令（3 路）
- **路7A /镶嵌 /拆珠**：槽级≥珠级校验（1级=普通/2级=精良及以下/3级=全部）、绑定默认、战斗中禁插拔、无损拆珠、珠实例堆叠键（ID+品质档+特性集）
- **路7B /珠升阶 + 珠特效**：3×同档同 ID+宝石10→+1 阶（禁跳级、无职业硬门槛拍板③、原数值不变）、同名递减乘法叠加（gem_diminish 第2颗50%/第3颗25%）、触发上限≤3次/场（按珠 ID，排除被动，计数落战斗快照）
- **路7C /成品合成 /配方合成 /特性合成 /登记 /复制**：原子扣费（宝石+材料全量）、门槛（宗师/专家/大师+宝石）、/登记 模板持久化、/复制 量产标准版（⌊cost.coins×20%⌋+可配额外消耗拍板④）、未登记拦截、组合表命中校验、同系校验

### 批8 · 深度炼金（2 路）
- **路8A /深度炼金 会话**：大师解锁（炼金职业≥大师）、深度会话类型（challenge_alchemy/alchemy 分离）、深度面板（6槽/核心槽/3普通+1金/刻度/进化线）、解锁公告+教学、/进化（宗师+炼金产出 N 次合成不计、永久解锁、特性不继承）、/镶核心（大师、品质上限+X/属性适配、可换）、/加成（宗师限 1 次）
- **路8B /挑战 /教学 /图鉴 /技能面板**：/挑战（宗师+材料×2、苛刻条件连锁≥5且刻度≥2 可配且/或、失败降级+退50%材料、成功品质上限+10）、/教学（无门槛、机制教学目录）、/图鉴 成长（点亮→奖励→王称号条件）、/技能面板 SP 自选解锁

### 批9 · 战斗接线（2 路）
- **路9A /即时调合**：battle_alchemy_used（快照 dict 顶层键、中断不清零、战斗结束清零、per_battle_limit=1）、战斗内一步出结果（不新开会话/不挂起/不申请槽/豁免互斥）、消耗携带素材+能量、auto_use 可配（默认当场自动使用）、吃冷却
- **路9B 战斗内拦截+道具渲染**：战斗中收到 /投料 /继承 /确认 → "战斗中使用 /即时调合"模板、战斗道具一行渲染（"火焰弹！造成 58 伤害"）、道具强度公式（技能×(1+0.4×冷却数) 可配）

### 批10 · 资源循环（2 路）
- **路10A /种植 /收获**：种子（items seed 标记）、地块（persistent_state 存档 种子+种植时间+收获时间）、定时收获（默认 4 小时可配）、收获品质≥种子品质、种子继承特性、温室（大师解锁可复制一种素材）
- **路10B /雇工 /收取**：代工助手（精通解锁、能源道具消耗、后台定时产出、上线收取、助手等级→特性更多/品质更高）、状态+产出队列存档

### 批11 · 装配接线（2 路）
- **路11A 指令装配**：alchemy_commands 全指令注册（/合成 /炼金 /投料 /继承 /继承超 /确认 /放弃 /调合续 /深度炼金 /进化 /镶核心 /加成 /成品合成 /分解 /登记 /复制 /配方合成 /特性合成 /挑战 /即时调合 /镶嵌 /拆珠 /教学 /协力 + /种植 /收获 /雇工 /收取 + /图鉴 /技能面板 挂接）、parsers 白名单补齐（**含 /协力**，2c4d 指令 15）、门槛接线（make_context 注入）、Router 注册、/秘钥 不注册（未知指令）
- **路11B 收口接线**：check_all/run_all_tests 接入 M8 校验器、热重载（recipe/traits/proficiency 变更→世代重绑定）、e2e 冒烟（注册→合成→炼金→投料→继承→确认→分解 全链路）、全量回归

### 批12 · 验收（2 路）
- **路12A verify_m8**：179 TC 承载（2c4a 26 + 2c4b 25 + 2c4c 30 + 2c4d 34 + 2c4e 26 + 2c4f 38）+ 门禁（子进程 pytest + 关键模块断言 + DELAYED 登记）；**TC-22（/协力，2c4d L400）用例归属批11A 注册验收同步**
- **路12B test_demo 炼金内容包**：补炼金配方/特性/材料/装饰珠/宝石数据到 test_demo + 全量回归 + 覆盖率三目录 ≥80%

### 批13 · dsh 审实现（审查批，串行 5 批）
- 审实现批次结构（对照 shared_contract + 细化）：数据层+校验器 / 合成+熟练度品质 / 调合会话+炼金核心 / 珠+深度炼金+战斗 / 指令装配+验收——每批 1 路 dshx 串行 + sleep 8 错峰

## 三、共享引用锚点（批间依赖，防并行冲突）

- **会话类型**：SESSION_TYPES 已含 alchemy/challenge_alchemy（schema.py L24）——批3 直接用，不改表
- **宝石键**：currencies dict 加 "gem"；shop.py L150 _CURRENCY_NAME_FALLBACK 已有 "gem":"宝石" 映射
- **白名单**：DEFAULT_WHITELIST 已含 合成/炼金/锻造/强化/调合/镶嵌/拆珠/投料/代工/继承/图鉴；FIXED_SUBWORDS 已含 自动/确认/放弃/续
- **ItemInstance.traits / EquipmentSlot.gems** 已存在（data/item.py L35 / data/player.py L69）
- **幂等**：idempotency_keys + idem_claim + write_idem_key（storage/repository.py L922/L932）——ATO-03 直接接线
- **熟练度条件/公式占位**：condition_engine [熟练度:{T}]（L161）、formula_engine [宝石]/熟练度（L218/L246）
- **traits 模块已登记**（field_meta L326-332 + loader L158）——只差数据文件
- **批9 依赖**：批9B 拦截接线依赖批3B/批4 指令壳（投料/继承/确认）先存在；批9A 豁免互斥不依赖 SessionManager 实装（方向正确，批序 0→13 串行天然满足）

## 四、铁律（实现组每条遵守）

1. 每功能可追溯：实现标注 `细化_2c4x §Y` + 定稿行号；出现设计文档没有的内容=疑点，除非标【工程补白】
2. 平台无关：world/storage/content/data 零 NoneBot；commands 唯一适配器接触点
3. 原子防双扣：合成/炼金/分解类 SQLite 事务 + message_id 幂等（ATO-01~08）
4. 数据表非空 + validator 生效：recipe/traits/proficiency 表非空、校验器挂进 check_pack
5. 指令严格对照细化_2c4d 指令契约章节（参数/流程/门槛/返回模板逐项）
6. 拦截链接线：每写一个函数查调用方（合成引擎/即时调合/宝石入账必须被消费）
7. 用户拍板 5 项不改（平铺宝石/键集/无门槛珠升阶/cost.coins 复制费/int32 数量上限）
8. 批量路径不抄 `+`（A+B 落两空格位置参数，特性名内数值 + 保留）；数量 `*`/列表 `,`/键值 `=` 按分隔符规范
9. 热重载世代：recipe/traits/proficiency 变更走 watcher 重绑定
10. 质量门禁：每批 pytest 全绿 + ruff/mypy + commit 才进下一批

## 五、共享契约文档

- 主契约：docs/m8_shared_contract.md（由 4 份子文档合并：核心机制/指令契约/数据与校验/战斗与资源循环）
- 子文档：docs/m8_contract_核心机制.md / m8_contract_指令契约.md / m8_contract_数据与校验.md / m8_contract_战斗资源.md
- 接口摸底：docs/m8_接口摸底.md（51 接口落点，实现组必读）
