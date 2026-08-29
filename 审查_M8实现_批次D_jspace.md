# 审查 · M8 炼金实现 批次D（资源循环+装配接线，5 文件）— j-space 门控 full 档

- 范围：`qbot_rpg/core/alchemy_harvest.py`（HarvestEngine）、`qbot_rpg/core/alchemy_helper.py`（HelperEngine）、`qbot_rpg/assembly/router_setup.py`、`qbot_rpg/assembly/context.py`、`qbot_rpg/assembly/runner.py`
- 依据：`docs/m8_contract_指令契约.md`（§20 /种植 /收获、§21 /代工 /收取、§22、指令注册总表/附注③/IF 清单/TC 矩阵）、`docs/m8_batch_plan.md`（批10/批11-2 装配接线）
- 方式：纯静态代码审查（本环境无 bash 沙箱，未运行任何命令/脚本）；运行行为结论均标注【静态推导】
- 预算：480s 硬时限；验证性 grep 15 次内；引用行号经 read 直接定位

---

## 一、P0 / P1 / P2 分级问题

### P0-1 地块存档/助手状态不落档：`farm_plots`、`helpers` 写入 ctx 后从不 merge 回 player（持久化完全失效）
- 触发链：
  - `Player` 为 `@dataclass(frozen=True)`（`qbot_rpg/data/player.py:72-73`，无 `__getitem__/__setitem__/get`，无 proficiency/farm_plots 字段）→ 壳层 `_player_of(ctx)`（`qbot_rpg/commands/alchemy_commands.py:264-273`）判定 `isinstance(player, MutableMapping)` 为 **False** → 生产路径返回 **ctx 自身** 作为 engine 的 `player` 实参。
  - `HarvestEngine.plant/harvest/greenhouse` 写 `player["farm_plots"]`（`alchemy_harvest.py:455, 634, 747`）→ 落在 `ctx["farm_plots"]`；`HelperEngine.assign/collect` 写 `player["helpers"]`（`alchemy_helper.py:300, 324, 642`）→ 落在 `ctx["helpers"]`。
  - `runner._make_handler` 落档（`qbot_rpg/assembly/runner.py:411-440`）仅处理 `_m8_dirty_inventory`（inventory）与 currencies（in-place 引用），**从不把 `ctx["farm_plots"]`/`ctx["helpers"]` 写回 `player.persistent_state`**。
- 影响【静态推导】：`/种植` 地块（种子+planted_at+harvest_at）、`/代工` 助手状态（config/started_at/last_tick_at/queue/produced_total）每次指令后即随 upsert 丢弃；收获/收取的入包因为走 ctx inventory dirty 通道可保留，但**种植/代工核心状态无持久化**。
- 修复建议：对齐 currencies 就地引用方案（context.py:923-927 已修）——make_context 把 `player.persistent_state["farm_plots"]`/`player.persistent_state["helpers"]` 以可变 dict 注入 ctx（引擎写入即落档），或 runner 在 upsert 前将 `ctx["farm_plots"]/ctx["helpers"]` 合并进 `p.persistent_state`；并补 dirty 标记语义与测试（test_alchemy_harvest.py 目前以 dict player 直测引擎层，未覆盖 runner 落档链路）。

### P1-1 `ctx["proficiency"]` 未注入 → M8 职业门槛（GU-60/62/44 等）在装配链路恒「等级不足」
- `make_context`（context.py 全文件）未注入 `ctx["proficiency"]`；全仓 grep 无任何 `ctx["proficiency"]` 赋值（M8 决策4：proficiency dict 形态存于 persistent_state，Player dataclass 不加字段）。
- 壳层 `_prof_level(player)`（alchemy_commands.py:302-310）读 `player.get("proficiency")`，player=ctx → None → 0（见习）。`cmd_plant`（2902）/`cmd_harvest`（2925）/`cmd_helper`（2953）/`cmd_assist`（3022）及引擎内 `_tier_index`（alchemy_harvest.py:395-420）/`_alchemy_level`（alchemy_helper.py:336-345）同源读空 → 0。
- 影响【静态推导】：`/种植 /收获 /代工`（及全部 M8 壳层 GU 门槛）在默认 `context.make_context` 链路恒拒；测试以 dict player 直测掩盖此装配缺口。
- 修复建议：make_context 从 `player.persistent_state["proficiency"]` 注入 `ctx["proficiency"]`（并考虑 `tier_index` 预计算，对齐 alchemy_harvest `_tier_index` 优先读取）；runner 侧如写入则并入 persistent_state（同 P0-1 修复）。

### P1-2 炼金产出「实例通道」与 count map 双计 → 同物两份、数量×2 膨胀
- `_inventory_hooks.add_item`（context.py:749-770）无条件 `inv[key] += c`，且带 quality/traits 关键字时再 append 实例通道。
- 生产方确实走该路径：`SettleEngine._produce`（`core/alchemy_settle.py:331`）、`BattleAlchemyEngine._produce_record`（`core/alchemy_battle.py:758`）均以 `quality=..., traits=...` 调 `ctx["add_item"]`。
- runner merge（runner.py:416-439）：`_ctx_inventory_to_player(count map)`（shop_tx.py:154-192，把该 item 计数并入既有堆栈）后，**再追加** `ItemInstance(item_id, count)` 实例 → 同一产出在背包中出现普通堆栈 + 品质实例两份。
- 影响【静态推导】：`/确认` 炼金产出、`/即时调合` 产出入包数量翻倍（数据损坏/资源漏洞）。注意：收获路径（alchemy_harvest.py:726 `_add_item` 无 quality kw）不触发双计，仅 inventory 计数正常。
- 修复建议：三选一——(a) 带 quality/traits 的 add_item 不进 count map（实例为唯一通道）；(b) runner 合并时对 instance 的 item_id 从 count map 剔除后再 merge；(c) runner 对 instance item 与堆栈按 id 去重合并（保留 quality 实例、累计 count）。

### P2-1 战斗接线缺口确认：`ctx["battle_alchemy_engine"]`/`battle_snapshot` 仍为 None（/即时调合 不可用）
- context.py:871-872 注入位 `"battle_snapshot": None`、`"battle_alchemy_engine": None`；全仓无任何装配注入点写回（`core/alchemy_battle.py` BattleAlchemyEngine 已实装但未接线）。
- `cmd_instant`（alchemy_commands.py:2658-2664）取到 None 抛 RuntimeError【待接线】。
- 影响【静态推导】：`/即时调合` 装配链路不可用（依赖批11-2/战斗接线完成）。

### P2-2 /协力 群校验与玩家名 hook 未接（安全空值，功能降级）
- context.py:878-879 `"resolve_player_name": None`、`"same_group": None`。
- `cmd_assist`（alchemy_commands.py:3036-3041）`same_group=None` → 保守放行（GU-46 同群校验缺失，alchemy_commands.py:50 文档化工程补白）；`resolve_player_name` 缺失（3107-3111）→ 回退兜底。安全失败不抛错，属功能降级而非阻断。

### P2-3 收获品质/特性未走实例通道落档（H-7 已知延迟）
- `HarvestEngine.harvest` 调 `_add_item(ctx, output, count, False)`（alchemy_harvest.py:726）无 quality/traits kw → 不触发实例通道；品质/特性仅存返回 dict（H-7 标注「落款为装配层/后续批次责任」）。
- 影响【静态推导】：`/收获` 的 品质≥种子/继承特性 仅展示不持久化（STO-02 堆叠键未应用）。非缺陷，属已知延迟项，与 P1-2 的实例通道本可承载但未接。

### 低级别/备注（不单列 P 级）
- context.py:944 与 1014 两处 `_inventory_hooks(ctx)` 重复构造（闭包双份但共享同一 `ctx["inventory"]`/`ctx["inventory_instances"]` 容器，功能一致；冗余可删一处）。
- `collect`（alchemy_helper.py:766-775）：全失败时仍写全部 `last_collect_at`（语义小瑕疵）；B-10 失败项留队列已正确实现。
- `tick`（alchemy_helper.py:691-719）：produced_total/queue 在 cfg 上原地累积，无快照回滚（纯 dict 写，风险低）。

---

## 二、无问题维度确认（点名疑缺项已实现清单）

- **/种植 /收获（GU-60/61 + F-21 + FARM-01~10）**：正式门槛（alchemy_harvest.py:586-590）、种子存在+seed 标记两形态（H-1，_seed_info 461-517）、空闲地块+plots_max 默认 3 可配（360-363, 606-626）、`harvest_at=now+harvest_sec`（634-639，默认 14400s=4h 可配、逐种子覆盖 FARM-02 347-358）、收获品质=种子品质下限≥（H-2，519-535）、继承特性 正式1/精通2/专家3 可配、超出丢弃并提示（H-3，422-438, 731-745）、温室大师解锁+宝石/金币双付可配（H-5，365-390, 792-881）、地块存档 dict 形态（H-4）——**引擎层全部落地**。
- **/代工 /收取（GU-62/63 + F-22 + ASST-01~09）**：精通门槛（alchemy_helper.py:564-571）、能源道具糖果/馅饼类可配（B-3，213-218）、`parse_task_spec` 键值列表（=定键、,分隔、*数量；代采=材料*数量、代调=配方*数量；未知键/重复键/非正整数量拒绝，119-164）、后台 tick 离线累积余数顺延（B-4，667-723）、/收取 入包+队列清空+失败项留队列（B-10，728-781）、助手等级 `produced_total` 终身只升不降（B-7，490-497, 786-798）——**全部落地**。
- **装配接线**：Router 全量注册（router_setup.py:75-92 16 组含 alchemy_commands；alchemy_commands.py:3392-3422 注册 29 指令）；`/图鉴` 由 codex_commands 单入口注册、alchemy_commands **不重复注册**（3341, 3414 注释 + router_setup.py:90）；make_context 注入 registry/session_mgr/items/recipe/traits + wallet/prof_engine 实构（context.py:866-879）+ currencies 就地引用 `player.currencies`（923-927，落档保留）+ `_inventory_hooks` dirty 标记与实例通道（723-795）+ 未注册/注入位安全空值（872, 878-879, registered=False 分支 947-968）。
- **代码质量项**：now 注入（壳层 `_clock_of` alchemy_commands.py:2813-2822：`ctx["now"]` 优先 → `time.time()` 兜底）；定时 4h 可配；队列容量 `max_slots` 可配（229-236）且 assign 在扣能源**前**先做容量校验（602-634 顺序正确）；plant/harvest/greenhouse 快照-回滚防双扣（630-644, 720-753, 849-863）；dirty 仅在实际 add/remove 时 `_mark`（746-789）不误触发；落档 merge 幂等——无变更不 merge 不覆盖（runner.py:416 仅 dirty 分支）。
- **验收点 TC/指令表覆盖**：TC-29→`tests/unit/test_alchemy_harvest.py`；TC-30→`tests/unit/test_alchemy_helper.py`；/种植 /收获 /代工 /收取 壳层→`test_resource_commands.py`；/协力→`test_assist_commands.py`；装配含 /图鉴→`test_m8_assembly.py`（L85 断言 图鉴 in names）、`test_assembly_router.py`、`test_assembly_context.py`、`test_assembly_runner.py`。

---

## 三、③ 遗漏（验收点未覆盖项）

1. **battle_alchemy_engine 战斗注入仍未接**（P2-1）：`/即时调合` 在装配链路不可用，缺战斗接线注入（context.py:872 注入位 → 全仓无写回）。
2. **/协力 same_group / resolve_player_name 未接**（P2-2）：安全空值降级，GU-46 同群校验缺失（功能可运行，语义弱化）。
3. **ctx["proficiency"] 装配缺口**（P1-1）：proficiency 桶未注入 ctx → M8 全部职业门槛在默认链路恒败（影响面超出批次D，需装配层统一收口）。
4. **runner 落档缺口**（P0-1）：farm_plots/helpers 无 dirty 标记、无 merge，落档链路未覆盖（与本批次 runner.py 直接相关，优先级最高）。

---

## 四、结论

- 门控档位：**full**（5 文件 + 契约/批计划/装配/落档交叉验证；验收点逐条核对；16 次 grep 内；0 次命令执行）。
- 结论：引擎层（HarvestEngine/HelperEngine）定稿落地扎实（验收点几乎全覆盖、工程补白显式标注、原子性/注入纪律到位）；**主要问题集中在装配-落档链路**：P0×1（地块/助手状态不落档）、P1×2（proficiency 未注入致门槛恒败；实例通道双计致背包×2 膨胀）、P2×3（战斗注入未接、协力 hook 未接、收获品质不落实例）。
- Top 3 问题：
  1. **P0-1** runner 只 merge inventory，`ctx["farm_plots"]`/`ctx["helpers"]`（因 `_player_of` 对 frozen Player 回退 ctx 而落在 ctx）从不写回 player → /种植 地块与 /代工 状态每次指令后丢失（runner.py:411-440 + alchemy_commands.py:264-273 + alchemy_harvest.py:455）。
  2. **P1-1** make_context 未注入 `ctx["proficiency"]` → `_prof_level(player=ctx)` 恒 0，/种植 /收获 /代工 GU 门槛装配链路恒拒「等级不足」（context.py 全文件 + alchemy_commands.py:302-310）。
  3. **P1-2** 带 quality/traits 的 add_item 同时进 count map 与实例通道，runner 又先 merge count map 再 append 实例 → 炼金产出/即时调合入包数量×2（context.py:749-770 + runner.py:421-439 + alchemy_settle.py:331）。
