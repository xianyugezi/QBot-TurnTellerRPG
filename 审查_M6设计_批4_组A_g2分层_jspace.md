# 审查报告：M6 G2 测试体系设计（组A：分层 + 确定性/性质用例）

> 审查对象：`docs/实现层规划文档.md`【G2 测试体系（分层 + 确定性 + 往返）】L3455-3458
> 对照基准：【规则】`docs/审查参考/开发规则文档.md` §四（4.1 层级 / 4.2 必测表 / 4.3 往返 / 4.4 公式确定性 / 4.6 基础设施）；【框架】`docs/审查参考/RPG回合制框架设计文档.md` §13（L1527-1560）；细化 `docs/细化/细化_5d_测试体系总纲.md`（§1 金字塔 / TC-5d-01/04/05/14 / §6.1 门禁）
> 实况核对：`tests/conftest.py`、`tests/unit/*`、`tests/contract/*`、`tests/fixtures/packs/legal/formula.json`、`pytest.ini`、`pyproject.toml`、`qbot_rpg/core/battle.py`、`qbot_rpg/core/damage.py`、`qbot_rpg/storage/connection.py`、`scripts/verify/verify_m5.py`、`scripts/run_all_tests.py`
> 方法：**纯静态审查，未运行任何命令/脚本/验证**；所有运行行为结论均标注「静态推导」（文件为语句级存在性/引用核对，属确定事实；"测试是否全绿/能否通过"为静态推导）。

---

## 0. 结论摘要

- **P0：0 项**；**P1：6 项**；**P2：6 项**；另「已验证一致（非问题）」4 项。
- G2 设计文本（L3457-3458）总体与【规则】§四、细化_5d 总纲方向一致，**未编造"已实现"能力**；但三个"确定性/性质"核心要点（性质用例 1000 组 / 固定随机种子 fixture / 公式参数独立 fixture 包）**在仓库中全部未落地**，且验收①「battle 留后续路」为**陈旧口径**，与已实现 battle 测试体系直接矛盾。M6 若按 G2 验收逐条执行，③（性质 1000 组）必红、①（levelup/inventory/equipment 引擎必测）无载体。

---

## 1. ①缺漏——「应覆盖 X 但未覆盖」清单

### 1.1 【P1】性质用例（随机 1000 组→不变量）全仓为零，G2 验收③ 无法满足
- 设计/定稿要求：G2 L3457「性质用例（随机 1000 组→不变量：伤害 ≥1、乱数区间、会心率 ≤95%）」+ 验收 L3458③「性质用例 1000 组不变量全绿」；【规则】§4.4 L309；细化_5d L61 + TC-5d-04。
- 实况：全仓 `tests/` 无任何 property 测试——无 `hypothesis`、无 `for _ in range(1000)` 随机组循环、无 `random.uniform/randint`（grep 0 命中）。现有 `test_damage.py`（T01-T27）与 `test_damage_gaps.py`（T04-T32）全是**固定输入→精确数值**的确定性用例，无一例随机组不变量断言。
- 影响：G2 验收③（硬性）M6 执行必红；TC-5d-04「性质用例存在（≥1000 组随机参数）」不满足。
- 修复建议：在 `tests/unit/test_damage.py`（或新建 `test_formula_property.py`）补 property 用例：随机 1000 组属性→断言①`total_damage`/`channel_*` 输出恒 ≥1；②非会心时落在 `[0.95,1.05]×基础` 闭区间；③`crit_prob` 输出 ≤0.95。随机组须用**固定 seed 的可复现 RNG**（见 1.2），不能裸 `random.random()`。

### 1.2 【P1】固定随机种子 fixture（seed 参数化）未实现
- 设计/定稿要求：G2 L3457「固定随机种子 fixture（seed 参数化）」；【规则】§4.6 L331；细化_5d L178/TC-5d-14「随机种子 fixture 被伤害/掉落/模拟用例使用」。
- 实况：`tests/conftest.py`（100 行）**无任何 seed fixture / seed 参数化**，仅 pack 目录与 `player` 两个 fixture。现有确定性全靠**测试内联硬编码**：`random.Random(1)`（test_battle_boundary L141）、`random.Random(42)`（test_damage_gaps L79 / test_effects_runtime L60 / test_effects_gaps L70）、`random.Random(20260826)`（test_monster_ai L190）、引擎 `start(..., random_seed=N)`（test_battle_engine L39-243、test_battle_wiring L115）。
- 影响：TC-5d-14「随机种子 fixture 被……使用」不满足；确定性散落各文件，无法统一收敛/变更种子。
- 修复建议：conftest 增 `@pytest.fixture def seed() -> int: return 20260826`（或 `seeded_rng` 返回 `random.Random(seed)`），并把现有内联 `random.Random(N)` 迁移为注入；新增的 1000 组性质用例必须复用该 fixture。

### 1.3 【P1】公式参数独立 fixture 包未落地；测试直接硬编码生产参数
- 设计/定稿要求：G2 L3457「公式参数用独立 fixture 包，禁硬编码生产参数」；【规则】§4.4 L311「公式参数全部来自 formula.json 参数段……禁止硬编码生产参数」；细化_5d L63 + TC-5d-05「全仓 grep：测试内无公式参数硬编码常量（除 fixture 读取代码）」。
- 实况（三处失配）：
  1. `tests/fixtures/packs/legal/formula.json` 仅 2 键 `damage_base`/`heal_rate`（JS 公式风格），**不含 1a 段级参数**（hit.k / crit.cap / block.k / defense.k / weakness.type_mult 等）；
  2. 测试直接断言 dataclass 默认值即生产参数：`test_damage.py` L134-140 `test_formula_params_defaults`（`p.hit.k==1.0`、`p.crit.cap==95`、`p.rng==(0.9,1.1)`…）、`test_damage_gaps.py` L135/142/159/192/205/283 全部用 `DamageFormulaParams()` 默认值——**正是 TC-5d-05 要禁止的硬编码**；
  3. 生产路径 `qbot_rpg/core/battle.py` L325 `params or DamageFormulaParams()` **从不读内容包 formula.json 段参数**（全仓无把 formula.json→DamageFormulaParams 的加载代码），"公式参数来自 formula.json 参数段"仅为文档口径。
- 影响：G2 验收③ 之外的设计硬约束（L311/TC-5d-05）不满足；formula.json 段级参数无人消费，fixture 包与测试、生产三者脱节。
- 修复建议：①补 `tests/fixtures/packs/legal/formula.json` 段级参数（或建独立 formula-fixture 包）；②写 fixture 读取器把段参数灌入 `DamageFormulaParams`，测试一律经 fixture 注入、删除对 dataclass 默认值的断言；③生产侧 battle.py 支持从内容包 formula.json 装配参数（或显式登记"段级参数当前仅默认值"决策记录，避免文档口径悬空）。

### 1.4 【P1】integration 层载体缺失：`tests/integration/` 不存在，NoneBot 夹具打桩无落点
- 设计/定稿要求：G2 L3457「integration（commands → engine 全链路，NoneBot 测试夹具打桩）」；【规则】§4.1 L284；细化_5d L50（L2 集成→`tests/integration/`）+ TC-5d-01「四目录齐全」。
- 实况：
  - `tests/integration/` 目录**不存在**（glob 0 文件）；全仓仅 `tests/unit/` 与 `tests/contract/`。
  - commands→engine 全链路用例目前**全部塞在 tests/unit/**：test_battle_wiring（真实引擎+RecordingSender mock，一轮1条）、test_basic_commands（FakeEquipEngine 替身）、test_shop_commands / test_quest_commands / test_checkin_commands / test_gm_commands；e2e 冒烟被塞进 tests/contract/（test_e2e_smoke.py、test_3f_patch.py），`run_all_tests.py` L46-47 的 "e2e" 段即指向这两个 contract 文件。
  - **NoneBot 测试夹具无任何载体**：`pyproject.toml` L10 `dependencies=[]`（连 nonebot 依赖都不存在，dev 也仅 pytest/pytest-asyncio）；全仓测试铁律「零 NoneBot import」。
- 影响：TC-5d-01 不满足；"integration（NoneBot 夹具打桩）"设计无目录、无依赖、无夹具可落地，M6 G2 验收若按此执行无对象。
- 修复建议：M6 显式决议 integration 层形态——二选一：①建立 `tests/integration/` + 引入 nonebug/nonebot 测试夹具（需新增依赖）；②按现状把"NoneBot 夹具打桩"修订为"命令壳→引擎全链路，Sender 注入/RecordingSender mock 打桩"（零 NoneBot 铁律下的既有做法），并把 test_battle_wiring 等迁入 `tests/integration/` 对齐 TC-5d-01。

### 1.5 【P1】levelup / inventory / equipment 引擎必测场景无任何测试（验收①核心承诺未兑现）
- 设计/定稿要求：G2 L3458①「【规则】§4.2 必测表（battle/levelup/inventory/equipment/worldtime/storage）逐项有测试（本路覆盖 levelup/inventory 接口/equipment 部位/storage 往返，battle 留后续路）」；【规则】§4.2 L293-295（levelup 经验曲线边界 0 经验/满级不增长/升级回满；inventory 堆叠上限/道具不耗回合/药剂同类型回合限次 1/绑定物品不可赠送掉落；equipment 部位占用/互斥/数量校验、互斥环加载期拦截）；细化_5d TC-5d-02。
- 实况：`tests/` 全仓 **0 处 import `core/levelup`/`core/inventory`/`core/equipment`**；`core/equipment.py` 系「M1 骨架未实装」，/装备 命令由 **FakeEquipEngine 契约替身**驱动（test_basic_commands L15-18），L428-436 明示「【待接线】防御：装备引擎缺失（core.equipment 不可导入 + 未注入）→ RuntimeError」；levelup 仅命令层"满级头"（test_basic_commands L248）无引擎用例；inventory 仅命令层 /背包（test_basic_commands、test_explore_filter）与 in-memory（test_shop）无引擎必测。
- 影响：G2 验收①「本路覆盖 levelup/inventory 接口/equipment 部位」**与现状矛盾**——这些引擎必测场景全部未覆盖，属必测表最大缺口。
- 修复建议：M6 G2 交付前为 `core/levelup.py`/`core/inventory.py`/`core/equipment.py` 补 §4.2 三行的引擎级用例（经验曲线边界、堆叠上限/药剂限次/绑定物品、部位互斥/互斥环拦截），或把"未覆盖"诚实登记 DELAYED（对齐 verify_m5 的 DELAYED 口径），**不得继续宣称"已覆盖"**。

### 1.6 【P2】存档往返"每类快照"未全覆盖（调合会话 / 商店限购 往返用例缺失）
- 设计/定稿要求：G2 L3457「存档往返（存什么→读什么→完全一致，每类快照）」；【规则】§4.3 L301 五类快照：战斗/调合会话/状态印记/连段/商店限购；细化_5d TC-5d-03。
- 实况：已覆盖 battle（test_battle_engine B5 / test_snapshot_resume）、ai_state（test_monster_ai_battle L294）、marks（test_marks M07/M11）、combo（test_combo P1-1）、dungeon/dialog/player/worldtime（test_dungeon_persist / test_dialog / test_storage / test_time_state_persist）；**调合会话(alchemy session)、商店限购(personal_buys) 快照往返用例未见**（grep 0 命中）。
- 修复建议：补 alchemy 会话与商店限购（personal_buys）的序列化→反序列化→逐字段比对用例；同时补 `random_seed` 往返时序断言（规则 L304；现 test_storage L180/266 仅存 seed 字段，未见恢复后随机序列一致的时序断言——静态推导）。

---

## 2. ②错误（与现有体系对齐 / 陈旧口径）

### 2.1 【P1】L3458 验收①「battle 留后续路」为陈旧口径，与已实现 battle 测试体系直接矛盾
- G2 验收①「本路覆盖 levelup/inventory 接口/equipment 部位/storage 往返，**battle 留后续路**」。
- 实况（battle 早已实现并被门禁锁定）：
  - `tests/unit/test_battle_engine.py`：`BattleEngine().start(..., random_seed=11..27)` 8 项闭环（L39-243）；
  - `tests/unit/test_damage.py` + `test_damage_gaps.py`：T01-T32 确定性精确值（对应【规则】4.2 damage.py 必测 L292）；
  - `tests/unit/test_battle_boundary.py`：世界边界（丢失链/回血/僵尸回收），固定 seed `random.Random(1)`（L141）；
  - `tests/unit/test_battle_wiring.py`：真实引擎 + Sender mock 全链路（M5-08，PYTEST_FILES 含，verify_m5 ④b L505-513 真实引擎 `random_seed=42` 断言一轮 1 条）；
  - 细化_5d §2.1 L90：M1 battle.py/damage.py 必测场景 L291-292 已入 verify_m1；§6.1 G2 门禁（战斗）即要求「4.4 公式三型用例全过 + 存档往返」。
- 影响：G2 验收① 若被执行者按字面读，"battle 不必测"——与既有 verify_m1/verify_m5 门禁（battle 必测且已绿）自相矛盾，属陈旧口径/指令冲突。
- 修复建议：删除「battle 留后续路」，改为「battle 已覆盖（test_battle_engine/test_damage/test_battle_wiring/verify_m1/verify_m5），本路补齐 §4.2 其余引擎必测（levelup/inventory/equipment）+ 新增性质用例」。

### 2.2 【P2】「G2」命名撞车（跨文档）：规划 G2=测试体系 vs 细化_5d G2=战斗(M1)门禁
- 实现层规划 L3455「G2 测试体系」（M6 任务，L3481 列 G2-G4）；细化_5d §6.1 L223「**G2 战斗（M1）**」= verify_m1 全绿 + 公式三型 + 往返。
- 影响：同号不同义，跨文档引用歧义（"G2 门禁"指战斗门禁还是测试体系验收？）。
- 修复建议：在规划 L3455 加括注「与细化_5d §6.1 的 G2（战斗门禁）编号不同，本 G2=测试体系（M6）」；或规划 G 组改用 G2a/G2b。

### 2.3 【P2】「integration（commands→engine 全链路，NoneBot 测试夹具打桩）」机制与仓库现状脱节
- 仓库现状：零 NoneBot（pyproject `dependencies=[]`）；全仓测试铁律「零 NoneBot import」（conftest.py 头注、test_battle_wiring、e2e_m4_smoke.py L40 均声明）；现有全链路用例用 Sender 注入/RecordingSender mock（test_battle_wiring L86-94），**并非 NoneBot 夹具**。
- 影响：设计所述"NoneBot 测试夹具打桩"机制无依赖可挂、与「引擎零 NoneBot / 测试零 NoneBot」铁律冲突（见 1.4）。
- 修复建议：同 1.4 的决议——若引入 NoneBot 夹具须先引入依赖并明确测试层是否豁免零 NoneBot 铁律（细化_5d L72 只禁 L1 层 import NoneBot，L2 层允许夹具）；否则把设计措辞改为"Sender/命令壳打桩"。

### 2.4 【P2】unit/integration/contract/e2e 边界漂移（重复登记旧问题，M6 G2 需收敛）
- `run_all_tests.py` L46-47："contract"→`tests/contract`、"e2e"→`tests/contract/test_e2e_smoke.py + test_3f_patch.py`；tests/e2e/ 与 tests/integration/ 均不存在。与 `docs/审查报告/审查_M0复查_tests_m0_20260824.md` P1-4（"tests/e2e/ 与 tests/integration/ 目录不存在、L4 冒烟被塞进 contract 目录冒充"）为同一问题，**G2 设计未吸收该审查结论**。
- 修复建议：M6 G2 落地时把 e2e 冒烟迁出 contract、补齐目录结构，并在规划文档引用该审查报告归口。

### 2.5 已验证一致（非问题）
- **SQLite :memory: 与存档层现状 ✓**：`qbot_rpg/storage/connection.py` L121-139 支持 `:memory:`（共享缓存唯一库）；`tests/unit/test_storage.py` L29 全用 `Database(":memory:")`；storage round-trip（4a TC-12）存在；conftest.py L3 头注「SQLite 一律 :memory: 或 tmp_path」。与 G2 L3457「SQLite 用 :memory: 或 tmp_path」一致。
- **battle/formula 确定性用例（固定种子→精确数值）已覆盖 ✓**：test_battle_boundary（固定 seed）、test_battle_engine（random_seed 参数化）、test_damage/test_damage_gaps（固定输入→精确数值 T01-T32）。
- **worldtime 必测已覆盖 ✓**：test_time_query / test_worldtime_changes / test_time_regression / test_weather_pool / test_weather_consumers（刷新/补刷/离线封顶/跨天判定均有）。
- **存档往返 battle/marks/combo/dungeon/dialog/player 已覆盖 ✓**（见 1.6）。

---

## 3. ③幻觉（编造现有测试能力）

- **G2 设计文本本身未编造"已实现"**：L3457-3458 均为前视要点/验收，未声称"seed fixture 已存在/性质用例已存在"。但若把「固定随机种子 fixture」「公式参数用独立 fixture 包」当作**已具备**执行，即构成对仓库能力的编造——实际均未落地（见 1.2/1.3），属"设计要点未落地"缺漏而非"冒充已覆盖"。
- **任务输入「已实现参考」存在失实文件名**（P2，防下游沿用）：
  - `tests/unit/` 下 **`test_formula_*`、`test_attributes_*` 文件不存在**（glob 0 命中）——公式测试实为 `test_damage.py` / `test_damage_gaps.py`；属性三层在 `test_basic_commands.py`/`test_data.py`，无独立 test_attributes_*；
  - **`scripts/e2e_m3/m4_smoke.py` 路径不存在**——实为 `scripts/e2e_m3_smoke.py` 与 `scripts/e2e_m4_smoke.py`（文件级，非目录级）。
- **确认不存在"已有性质用例/seed fixture"的任何支撑**：conftest 无 seed fixture、全仓无 1000 组性质用例（grep 0 命中）；任何声称"已有"的表述均为幻觉。→ 已并入 1.1/1.2 修复。

---

## 4. ④跨文档一致性

| 对 | 结论 | 说明 |
|---|---|---|
| G2 ↔ 细化_5d 总纲（分层/确定性/往返/覆盖率） | 部分一致 / 见缺口 | 方向一致；但细化_5d 对 4.4 三型用例（确定性+性质≥1000+判定顺序，L60-62/TC-5d-04）、TC-5d-05（公式参数来源）、TC-5d-14（seed fixture）有硬性验收，G2 只在"实现要点"提及、**验收标准未映射这三项的可验证断言**（验收③只有"性质 1000 组全绿"，缺"公式参数来源检查/seed fixture 使用检查"）——G2 验收清单不完备，M6 无从判定 TC-5d-05/14 达标 |
| G2 ↔ M6 里程碑 L3481 | 一致（但交付物未完成） | M6 列 F5-F6、G2-G4 + 覆盖率 engine/content ≥80% + ruff/mypy/pytest 全绿；G2 验收②③（往返完全一致/性质 1000 组全绿）与之兼容；**但 1.1/1.2/1.3 三项交付物未实现，M6 verify 若执行即红** |
| G2 ↔ G1 门禁 L3452 | 一致 ✓ | G1 要求 pytest 全绿（含本里程碑新增用例）→ G2 新增用例自然纳入，无冲突 |
| G2 ↔【规则】§四（4.1/4.2/4.4/4.6） | 设计层对齐 ✓ / 实现层断裂 | 设计逐条引用对齐；断裂在实现（性质用例/seed fixture/公式 fixture 包/levelup·inventory·equipment 引擎必测均缺） |
| G2 ↔【框架】§13（L1527-1560 战斗/部位/存档验收） | 一致 ✓ | §13 为能力验收清单（1v1 闭环/部位互斥/存档不丢），G2 测试体系是其落地手段，无冲突 |
| G2 ↔ 细化_5d §6.1「G2 战斗门禁」 | **命名撞车** | 见 2.2 |

---

## 5. P0/P1/P2 汇总表（含文件行号 + 修复建议）

| 级 | # | 问题 | 位置 | 修复建议 |
|---|---|---|---|---|
| P0 | — | 无 | — | — |
| P1 | 1.1 | 性质用例（随机 1000 组不变量）全仓为零，验收③必红 | 规划 L3457/L3458③；规则 L309；细化_5d L61/TC-5d-04；test_damage.py、test_damage_gaps.py | 补 `test_formula_property.py`：固定 seed 随机 1000 组→伤害≥1 / 非会心∈[0.95,1.05]×基础 / 会心率≤95% |
| P1 | 1.2 | 固定随机种子 fixture（seed 参数化）未实现 | 规划 L3457；规则 L331；细化_5d TC-5d-14；tests/conftest.py（100 行无 seed fixture） | conftest 增 `seed`/`seeded_rng` fixture；迁移现有内联 `random.Random(N)`（test_battle_boundary L141 等） |
| P1 | 1.3 | 公式参数独立 fixture 包未落地 + 测试硬编码生产参数 + 生产不读 formula.json 段参数 | 规划 L3457；规则 L311；细化_5d TC-5d-05；fixtures/packs/legal/formula.json（仅 2 键）；test_damage.py L134-140；battle.py L325 | 段参数入 fixture formula.json；fixture 注入替代 dataclass 默认断言；battle 支持包内参数装配或登记决策 |
| P1 | 1.4 | integration 层载体缺失（tests/integration/ 不存在、NoneBot 夹具无依赖无落点） | 规划 L3457；规则 L284；细化_5d L50/TC-5d-01；pyproject.toml L10；run_all_tests.py L46-47 | 决议 integration 形态：建目录+引入 nonebug 夹具，或改为 Sender 打桩并把 test_battle_wiring 迁入 tests/integration/ |
| P1 | 1.5 | levelup/inventory/equipment 引擎必测场景无任何测试（验收①核心未兑现） | 规划 L3458①；规则 L293-295；test_basic_commands L15-18/L428-436（FakeEquipEngine 替身） | 为三引擎补 §4.2 引擎级用例，或诚实登记 DELAYED，不得再宣称"已覆盖" |
| P1 | 2.1 | L3458「battle 留后续路」陈旧口径，与已实现 battle 测试/门禁直接矛盾 | 规划 L3458①；test_battle_engine.py；test_battle_wiring.py；verify_m5.py L505/L617 ④b；细化_5d L90/L223 | 删除"留后续路"，改为"battle 已覆盖，本路补齐其余引擎必测 + 性质用例" |
| P2 | 1.6 | 存档往返"每类快照"未全覆盖（调合会话/商店限购往返用例缺失） | 规划 L3457；规则 L301；细化_5d TC-5d-03 | 补 alchemy/personal_buys 往返 + random_seed 时序断言 |
| P2 | 2.2 | 「G2」命名撞车（规划=测试体系 vs 细化_5d=战斗门禁） | 规划 L3455；细化_5d L223 | 规划 L3455 加括注消歧或改 G2a/G2b |
| P2 | 2.3 | integration"NoneBot 夹具打桩"机制与零 NoneBot 现状脱节 | 规划 L3457；pyproject.toml L10 | 同 1.4 决议；明确 L2 层 NoneBot 豁免与依赖引入 |
| P2 | 2.4 | unit/integration/contract/e2e 边界漂移（e2e 塞 contract；重复登记审查_M0复查 P1-4 旧问题） | run_all_tests.py L46-47；tests/contract/test_e2e_smoke.py | M6 G2 收敛目录结构；规划文档引用审查_M0复查归口 |
| P2 | 3.2 | G2 验收标准缺 seed fixture/公式 fixture 来源的可验证断言（TC-5d-05/14 未映射进 G2 验收） | 规划 L3458 | 验收清单补「① 公式参数来源检查 ② seed fixture 使用检查」 |
| P2 | 3.3 | 任务输入「已实现参考」文件名失实（test_formula_*/test_attributes_*/scripts/e2e_m3/m4_smoke.py 不存在） | 任务输入（非 G2 设计） | 改用真实文件名 test_damage.py/test_damage_gaps.py、scripts/e2e_m3_smoke.py/e2e_m4_smoke.py，防下游沿用幻觉 |

---

## 6. 最后回复

- **门控档位**：loop（多文件多维度跨文档，账本已开、每 seam 刷新、ship 前一致性审计）。
- **结论**：P0=0 / P1=6 / P2=6（另 4 项已验证一致：SQLite :memory:、battle 确定性用例、worldtime 必测、battle/marks/combo/dungeon/dialog/player 往返）。
- **Top 3**：
  1. G2 三个"确定性/性质"要点全部未落地——性质用例（1000 组不变量）全仓为零（验收③必红）、conftest 无固定随机种子 fixture、fixture formula.json 无段级参数且测试硬编码 `DamageFormulaParams()` 默认（TC-5d-04/05/14 全不满足）；
  2. L3458 验收①「battle 留后续路」为陈旧口径，与已实现 test_battle_engine/test_damage/test_battle_wiring/verify_m5④b 直接矛盾；且"本路覆盖 levelup/inventory/equipment/storage"中 levelup/inventory/equipment 引擎必测实际为 0（/装备 用 FakeEquipEngine 替身），验收① 名实不符；
  3. integration 层"NoneBot 测试夹具打桩"无载体：tests/integration/ 不存在、pyproject 零 NoneBot 依赖，现全链路用例（Sender mock）全塞 tests/unit/、e2e 塞 tests/contract/（TC-5d-01 不满足，与审查_M0复查 P1-4 重复登记）。
