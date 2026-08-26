# 审查报告：M4 实现层 · 批次4（商店/任务引擎）——j-space 静态审查

- 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，全程未运行任何命令/脚本/校验；所有运行期行为结论均标注「静态推导」）
- 审查流程：j-space loop 档（ledger 携带状态跨文件/文档 seam；broadcast 以共享契约核为 hub 交叉核验）
- 审查对象（4 文件，全文通读）：
  - `qbot_rpg/content/shop_models.py`（1137 行）
  - `qbot_rpg/core/shop.py`（1286 行）
  - `qbot_rpg/content/quest_models.py`（1131 行）
  - `qbot_rpg/core/quest.py`（952 行）
- 权威依据（已逐份核对仓库内实际文件）：
  - `docs/m4_shared_contract.md` §0（裁决①~⑧）/§3.2/§3.3
  - `docs/细化/细化_2b3_商店引擎契约.md`（§1.2~1.6/§二/§三/§四/§五 + 2026-08-27 裁决 P1-1~P1-4）
  - `docs/细化/细化_2b4_任务引擎契约.md`（§1.2~1.5/§二~§五 + 2026-08-27 裁决 P1-1/P1-2）
  - `docs/审查参考/商店系统设计定稿.md`、`docs/审查参考/任务系统设计定稿.md`
  - `审查_M4设计_批次3_jspace.md`、`审查_M4设计_批次4_jspace.md`
  - 交叉核验：`qbot_rpg/core/dayroll.py`、`qbot_rpg/core/reward.py`、`qbot_rpg/commands/shop_commands.py`、测试与 verify_m4 引用

## 结论速览

**P0 = 0 · P1 = 1 · P2 = 6**（共 7 项）

| 级别 | 数量 | 项 |
|---|---|---|
| **P0** | 0 | — |
| **P1** | 1 | 黑市上架 N：`listing_count` 声明+校验但引擎零消费；`blackmarket_listing_n` 与引擎 `_redraw_blackmarket` N 语义分裂；校验器对定稿 L507 正典示例误报 |
| **P2** | 6 | ①quest_complete 事务内 normalize_reward 异常未捕获→扣物不回滚；②resolve_board_index docstring 与实现不符；③board.limit 声明+校验但引擎零消费；④has_reward_alias_conflict/reward_entries 全库零引用；⑤repeatable cap 警告分支死代码；⑥refresh:{} 校验红拦 vs 引擎 none 兜底口径微差 |

---

## 〇、行号引用真实性抽核（维度③ · 核心）

对 4 个实现文件 docstring/注释中的定稿/细化/裁决行号引用做定向回查（≥20 处），**全部真实存在、内容相符，未发现编造行号**：

| 引用 | 回查结果 |
|---|---|
| 商店定稿 L128-143 顶层 14 字段表 | ✅ id/name/icon/type/currency/level_required/reputation_required/open_condition/refresh/items/pool/price_fluctuation/visible/desc 逐列一致 |
| 商店定稿 L168-181 条目 12 字段表 | ✅ item/price/currency/scope/stock/refresh/limit/period/reputation_required/min_level/discount/sold_out_once 逐列一致 |
| 商店定稿 L183 旧字段兼容 | ✅ 「旧 stock/per_player 自动映射」原句存在 |
| 商店定稿 L44 数量上限 ≤99 | ✅ 原句存在 |
| 商店定稿 L216「按 items 配置数量从池中抽 N 个上架」 | ✅ 原句存在 |
| 商店定稿 L281-285 refresh 四模式 | ✅ daily/weekly/once/none 四行存在 |
| 商店定稿 L289-292 刷新三件事 / L301 不配置=永不刷新 | ✅ 存在（裁决⑥ 定稿侧一致） |
| 商店定稿 L408-433 校验器（红拦/黄提示/默认兜底） | ✅ L411-432 逐条对应（L420~L428 黄提示族含空店/库存过小/price=0/黑市>30%/未使用/同物不同价） |
| 商店定稿 L450/L465 型「stock+per_player 同条目并存」 | ✅ 示例条目真实（裁决⑤ 依据成立） |
| 商店定稿 L507 黑市 items=[] pool=3 示例 | ✅ 存在（正典形态，P1 问题锚点） |
| 任务定稿 L61 main_progress done 计数 / L138 main 命名 | ✅ 原句存在（P3-1 定稿原文命名成立） |
| 任务定稿 L181-187 板规则 / L183 接取≤5 / L184 完成≤10 | ✅ 原句存在 |
| 任务定稿 L190-194 双板仲裁 | ✅ 原句存在 |
| 任务定稿 L205 quest_active ID+名称冗余 / L276 校验器硬拦 4 类 | ✅ 存在 |
| 细化_2c5b REP-04 声望 5 级阈值表 | ✅ L1陌生0/L2熟悉100/L3信赖300/L4崇敬600/L5传说1000 一致 |
| 细化_2b3 §1.2/§1.3/§1.4/§1.5/§1.6 与裁决 P1-1~P1-4 | ✅ 存在且与实现口径一致（P1-2 scope 并存 / P1-3 period 独立驱动 / P1-4 默认 none） |
| 细化_2b4 §1.2~1.5/§二/§三/§四/§五 与裁决 P1-1/P1-2 | ✅ 存在；P2-1/P2-2/P3-1/P3-2 裁决项在实现中均有对应落地标注 |
| 2026-08-27 裁决⑤⑥（m4 §0.5-6） | ✅ 原文一致 |

**工程补白标注纪律**：4 文件全部显式标注【工程补白】（shop_models 1-8 / shop.py 1-9 / quest_models 1-7 / quest.py 1-9），无冒充定稿行号、无「工程补白冒充定稿支持」的表述（批次3/4 设计审查 P1-1 幻觉引用未复现）。

---

## 一、维度① 定稿落地核查

| 检查点 | 要求 | 实现 | 结论 |
|---|---|---|---|
| 五类型 | normal/npc/reputation/event/blackmarket | shop_models L67 `SHOP_TYPES` 5 值；shop.py L118；type 仅入口/刷新默认分叉，购买引擎同一套（shop.py 仅黑市货架来源+刷新默认分叉） | ✅ |
| stock 0=无限 | 0=无限、缺省=无限 | shop.py `_entry_stock`：`v>0` 才有限，0/缺省→0=无限；校验器允许 stock≥0 | ✅ |
| 刷新四模式 | daily/weekly/once/none | shop.py `resolve_refresh` 归一 4 模式（daily hour 缺省 5、weekly weekday 缺省 1、once start/end、none）；`shop_refresh_due` 惰性判定（daily 跨日/weekly 跨周/once 非周期补货/none 永不） | ✅ |
| 裁决⑥ 不配置=永不刷新 | 缺省 none | `resolve_refresh` 非 Mapping/非法 mode → `{"mode":"none"}`；`shop_refresh_due` mode none → False | ✅ |
| 限购 period 独立驱动（裁决⑤/P1-3） | 个人限购清零以条目 period 为准，与 refresh 解耦 | `personal_limit_state` 按 `_period_bucket_key`（day/week/month + 全局 refresh_time 边界 + week_start）惰性清零；`shop_apply_refresh` 不含②限购清零（P1-3 口径） | ✅ |
| 裁决⑤ stock+per_player 同条目并存 | scope 只管默认侧，L450/L465 型无损表达 | shop_models `effective_scope`/`has_global_side`/`has_personal_side`；引擎 `_entry_stock`/`_entry_limit` 各自独立读取，互不排他；校验器不拦并存 | ✅ |
| 原子防双扣（D-03） | 校验链全过→单事务结算；幂等 | shop_buy：幂等闸（tx_id/ledger）+ 快照-回滚 + 结算段条件式库存复查（remaining<n→回滚）；跨进程由调用方 SQLite 事务+条件 UPDATE 兜底（已文档化） | ✅ |
| 当前商店机制 | 地图级 current_shop、中断恢复、回退 normal 兜底 | `current_shop_id`/`set_current_shop`/`clear_current_shop`/`resolve_shop_arg`（无参→当前→默认；int 序号；str 名称） | ✅ |
| 三原语求值 | 判定唯一权威 = condition_engine | quest.py `quest_conditions_met`→`eval_condition`；进度 current 仅展示（`_read_current` 本地镜像）；数组全与 D-02；求值失败默认不满足 D-03 | ✅ |
| 每日防刷 | daily_limit≤10 / accept_limit≤5 / quest_daily / 完成即移出 | `_daily_limit`/`_accept_limit`（settings 全局覆盖→board→缺省 10/5）；quest_accept 校验 active 行数；quest_complete 校验当日完成数；完成即移出 active + 非 repeatable 记 completed | ✅ |
| 主线置顶（main 常驻） | main:true 置顶常驻不刷新不移除 | quest_board main 段置顶；完成亦显示（completed 标记）；P2-1 裁决：主线计入 accept_limit 行数、照常结算，无豁免 | ✅ |
| 双板 | /任务=玩家任务板；委托板独立 | board.slot 多板（daily/weekly/event）分组；委托板仲裁明确登记为指令层职责（quest.py 工程补白 6/7、quest_models 工程补白 7），本批只服务玩家任务板 | ✅ |
| 黑市重抽确定性 | 刷新三件事③ pool 抽选+价格重浮动 | `_redraw_blackmarket` rng 注入（ctx["rng"]）sample 不重复抽样 + randint 浮动，确定性可测；`_clear_shop_stock` 清计数、sold_out 保留 | ✅（N 来源问题见 P1-1） |
| sold_out_once | 售出永久下架，刷新不恢复 | shop_buy 售罄标记 `world_sold_out`；`shop_apply_refresh` 跳过已售罄条目；`_is_sold_out` 前置拦截 | ✅ |
| 重复衰减（F-4/TC-23） | {decay,cap} 第 n 次 ×decay^n 至 cap 下限 | `_decay_state` mult=decay^n（n=已完次数）；`_scale_reward` 标量/物品 floor 至 ≥cap | ✅ |
| 单事务回滚（D-04） | 结算簿记原子性 | quest_complete 快照-回滚（currencies/exp/reputation_state/quest_active/quest_completed/quest_daily/longline_counters/inventory）；条目级失败黄字跳过（P1-2，dispatch_reward） | ✅（见 P2-1 边界缺口） |
| 页码 | 夹取+「已到最后一页」/TPL-12 | 引擎 shop_browse/shop_list 防御性夹取 [1,pages]；指令层 `resolve_page` 负责 TPL-12/超页夹取标记（3d 已实现）——接缝闭合确认 | ✅ |
| 当前商店中断恢复/离图回退 | 触发①②③ + 清除 | resolve_shop_arg 全链路 + clear_current_shop | ✅ |

---

## 二、维度② 代码质量核查（bug/边界）

### P1-1 黑市上架数量 N：`listing_count` 引擎零消费 + 两文件语义分裂 + 正典示例误报

- 位置：
  - `qbot_rpg/content/shop_models.py` L34-37（工程补白 2 声明）、L109-111（字段常量）、L427-439（`listing_count`/`blackmarket_listing_n`）、L1014-1028（黑市专项黄提示 N 解析）
  - `qbot_rpg/core/shop.py` L564-582（`_redraw_blackmarket`）、L570-571（N 解析）
- 问题（静态推导）：
  1. **引擎零消费**：`_redraw_blackmarket` 只读 `pool`/`price_fluctuation`/`items`，**从不读取 `listing_count`**（全库 grep 确认该字段仅在 content 层与测试出现）。内容包配 `listing_count:1` 期望黑市每次只上架 1 件，引擎仍按 `len(items)`/`len(pool)` 上架全部——工程补白 2 声明的能力未落地。
  2. **两文件 N 语义分裂**：shop_models `blackmarket_listing_n`（L434-439）与校验器（L1020-1028）口径为「listing_count>0→该值；否则 len(items)；两者皆缺省→0（不上架）」；shop.py 引擎（L570-571）为「items 非空→len(items)；items 为空→回退 len(pool)」。**items=[] 且无 listing_count 时，content 层断言 N=0，引擎实际取 len(pool)**。
  3. **正典示例误报**：定稿 L507 黑市正典形态 `items=[] pool=3` 下，校验器判 `n=0` → 黄提示「黑市未配上架数量（listing_count 与 items 均空）→ 每次刷新不上架任何商品？确认」，而引擎实际会全池上架 3 件。校验器对定稿自带示例给出事实错误警告。
- 定性：跨文件实现口径分裂 + 声明覆盖但引擎未实现（维度③）→ **P1**。
- 修复建议：①引擎 `_redraw_blackmarket` 读取 `listing_count`（>0 取之）；②shop_models `blackmarket_listing_n` 与校验器 N 解析统一为「listing_count>0→N；items 非空→len(items)；否则→len(pool)（对齐 L216/L507 正典）」，删除「→0 不上架」分支（或仅当 pool 亦空才黄提示）；③补 N 来源一致性测试（引擎侧含 listing_count 用例）。

### P2-1 quest_complete 事务内 `normalize_reward` 异常未捕获 → 扣物不回滚、异常逃逸

- 位置：`qbot_rpg/core/quest.py` L851-887（结算块）；L859 `normalize_reward(quest.get("reward", ""))`
- 问题（静态推导）：结算块先扣 consume 物（L853-857，`_remove_item`），再 `normalize_reward`（L859）。`normalize_reward`（reward.py L121-143）对非法 reward 形态（如 int、list 含非 dict 元素）会抛 `ValueError/TypeError`，而结算块的异常处理仅捕获 `_Rollback`（L885-887）。因此**非法 reward 配置下：consume 物品已扣除、reward 未发放、quest_active 未移出、异常直接逃逸到指令层，快照回滚不执行**——单事务语义（D-04）被破坏。shop_buy 结算块无同类问题（结算内无会抛异常的调用，price_for 在快照前完成）。
- 可达性：校验器 `_check_reward` 对结构非法 reward 红拦（加载期挡住），故仅热重载/绕过校验器等边界可达；但引擎自述 D-03「求值失败不崩」口径下属健壮性缺口。
- 修复建议：将 `normalize_reward` 包入 try/except（ValueError/TypeError → `raise _Rollback("reward_invalid")`），或把 normalize 提前到快照之前；确保「扣物→发奖→簿记」整块要么全成要么全回滚。

### P2-2 resolve_board_index docstring 与实现不符（「序号带 * 不计可接序号」未实现）

- 位置：`qbot_rpg/core/quest.py` L578-591
- 问题：docstring 称「序号带 `*` 为已接取不计可接序号」，但 `seen += 1` 对**每一行**（含已接取/不可接取行）无条件计数。已接取行占序号位，`/接取 N` 命中已接取行时返回 `already_active`，与契约「* 已接取不计可接序号」（2b4 §5.1/L296）存在口径分歧（2b4 示例 L283-292 又全行编号，契约本身两义）。实现单索引服务 /接取 与 /交付 两个语义，属于可辩护收敛，但**docstring 承诺的能力未实现**。
- 修复建议：二选一——①指令层渲染时已接取行以 `*` 代替序号、resolve_board_index 跳过 marked 行（/交付 改用 active 独立编号）；②改 docstring 为「展示序号即 /接取 /交付 参数（含已接取行），已接取行命中提示 already_active」，消除承诺-实现落差。

### P2-3 board.limit 声明+校验但引擎零消费（未实现且未标注延后）

- 位置：`qbot_rpg/content/quest_models.py` L164-166（BoardDef.limit 访问器）、L789-796（校验器 limit≥0）；`qbot_rpg/core/quest.py`（`_accept_limit`/`_daily_limit` 只读 accept_limit/daily_limit，全库无 limit 读取）
- 问题：2b4 §1.3#3 定义 board.limit「本周期该任务最多上架/完成次数（示例 limit:1/3）」；模型声明、校验器校验（负数红拦、≥0 放行），但**引擎任何路径都不消费该字段**，且未列入 quest.py 工程补白 6 的「未实现/延后」清单（该清单只含 timed.penalty/filter/bonus/zone 子任务/npc 发任务/委托板）。
- 定性：声明覆盖但未实现、未标注（维度③）→ P2。
- 修复建议：补实现（按周期完成次数上限）或将该字段显式登记进「本批不消费、后续批次承接」清单，避免作者配置 limit 后无任何效果。

### P2-4 has_reward_alias_conflict / reward_entries 全库零引用（死 API）

- 位置：`qbot_rpg/content/quest_models.py` L441-458（`reward_entries`、`has_reward_alias_conflict`）
- 问题（静态推导）：两方法全库（含测试、指令层、引擎、verify_m4）grep **零引用**。校验器对 reward/rewards 别名冲突用的是内联实现（L969-972），未调用 `has_reward_alias_conflict`；`reward_entries` 亦无消费方。属公开 API 面上的死代码。
- 修复建议：由消费方（校验器/测试）调用以兑现其声明的语义，或删除并登记；至少补单测覆盖避免被当作已接线 API。

### P2-5 校验器 repeatable cap 警告分支死代码（不可达）

- 位置：`qbot_rpg/content/quest_models.py` L907-915（`_check_repeatable`）
- 问题（静态推导）：cap 分支 `if ... or cap < 1: _err(...)` 已把 cap<1 归入红拦，其后 `elif isinstance(cap, (int,float)) and cap < 1: _warn(...)` **永不可达**（cap<1 的数值必先命中 if）。黄提示「cap 低于 1，衰减无下限？确认」永远不会触发；decay 分支无此问题（decay<=0/>=1 可正常到达 elif 黄提示）。
- 修复建议：删除死 elif，或把「cap<1 数值」从红拦降为黄提示（与文档 Y-4「衰减异常黄提示」口径统一），二者择一。

### P2-6 校验器 `refresh:{}` 红拦 vs 引擎 `resolve_refresh` 按 none 兜底（口径微差）

- 位置：`qbot_rpg/content/shop_models.py` L688-693（`_check_refresh`：非 None Mapping 且 mode 缺失 → 红拦 `shop_refresh_mode_required`）vs `qbot_rpg/core/shop.py` L387-392（`resolve_refresh`：mode 非法/缺失 → `{"mode":"none"}`）
- 问题（静态推导）：作者写 `"refresh": {}` 会被校验器红拦「refresh 缺 mode」，而引擎（绕过校验器/热重载场景）按 none 处理不刷新。裁决⑥「不配置=永不刷新」语义下，`{}` 属「配置了但未指定模式」与「未配置」的边界，两层处理不一致（各自内部自洽）。
- 定性：低危口径微差 → P2（低）。
- 修复建议：统一为「refresh 键存在但非合法模式对象 → 红拦；缺省/None → none 不拦」并在校验器文案注明；或允许 `{}` 视同 none 放行并同步引擎。

---

## 三、维度③ 幻觉/缺漏核查

| 检查点 | 结果 |
|---|---|
| docstring 引用行号真实性 | ✅ 抽查 20+ 处全部真实（见 §〇），无编造行号、无批次3/4 P1-1 型幻觉复现 |
| 工程补白显式标注 | ✅ 4 文件全部显式标注，未冒充定稿/裁决支持 |
| 声明覆盖但未实现 | ⚠️ listing_count（P1-1）、board.limit（P2-3）、has_reward_alias_conflict/reward_entries（P2-4） |
| 零消费函数 | ⚠️ `blackmarket_listing_n`（P1-1）、`board.limit`（P2-3）、`has_reward_alias_conflict`/`reward_entries`（P2-4）；`quest_daily_reset` 为公开 API（verify_m4 登记，非死代码）✅ |
| 死代码分支 | ⚠️ repeatable cap 黄提示分支不可达（P2-5） |
| 裁决贯彻 | ✅ 裁决⑤（并存/scope 默认侧/period 独立）、裁决⑥（缺省 none）、2b3 P1-1~P1-4、2b4 P1-1/P1-2、P2-1（主线计入行数）、P2-2（daily 简写）、P3-1（main 定稿命名）、P3-2（接取数记录不消费，已声明）全部落地 |
| 未实现项登记 | ✅ timed.penalty/filter/bonus/zone 子任务/npc 发任务/委托板 均入 quest.py 工程补白 6 延后清单（board.limit 除外，见 P2-3） |

## 四、确认无问题维度（含「静态推导」运行行为结论）

- **并发超卖防护（D-03）**：shop_buy 结算段对 world_stock 做条件式复查（`remaining<n → _Rollback`），配合调用方 SQLite 事务/条件 UPDATE，双人同刻抢最后一件的场景仅一人成功（静态推导）。
- **限购清零驱动**：period 桶键惰性清零与 shop_apply_refresh 解耦（P1-3），`refresh:none`+personal 条目下限购仍按 period 每日 05:00 清零、global 库存不补（静态推导）。
- **黑市重抽确定性**：ctx["rng"] 注入 + `sample` 不重复抽样 + `randint` 浮动，同种子同参必同货架（静态推导）。
- **sold_out_once**：售罄标记跨刷新保留、重抽后仍显示已售罄并拦截购买（静态推导）。
- **重复衰减**：decay^n 至 cap 下限，cap 下限=单条奖励下限，符合 TC-23（静态推导）。
- **单事务回滚**：快照-回滚覆盖 ctx 可变子结构；hook 通道（add_item/remove_item）的跨进程回滚明确依赖调用方事务，已文档化——属设计移交非缺陷（P2-1 的 normalize 异常缺口除外）。
- **页码（裁决②）**：引擎防御性夹取 + 指令层 `resolve_page` 负责 TPL-12/超页夹取标记（shop_commands.py L223-238），接缝闭合。
- **五类型/stock 0/刷新四模式/当前商店/三原语/防刷/主线置顶/双板**：全部落地（见维度①表）。

## 五、修复建议清单（按优先级）

1. **P1-1**：引擎 `_redraw_blackmarket` 接 `listing_count`；shop_models `blackmarket_listing_n` 与校验器 N 解析统一为「listing_count>0→N；items 非空→len(items)；否则→len(pool)」；补引擎侧 listing_count 用例。
2. **P2-1**：quest_complete 结算块 `normalize_reward` 异常包入 `_Rollback`（或前移），保单事务完整性。
3. **P2-2/P2-3**：resolve_board_index docstring 与实现对齐（或实现跳过 marked 行）；board.limit 补实现或登记延后。
4. **P2-4/P2-5/P2-6**：死 API 补消费或删/登记；cap 死分支清理；refresh:{} 口径统一。

## 六、评分

- 主体实现质量高：定稿/细化/裁决落地完整、行号引用全部真实、工程补白纪律严明、P 项裁决贯彻无遗漏；4 文件运行期主路径无 P0。
- 主要短板集中在**黑市 N 来源的跨文件语义分裂与零消费**（P1）与任务侧**事务健壮性/死代码/零消费字段**（P2×6）。
- **P0=0 · P1=1 · P2=6 · 评分 A-**
