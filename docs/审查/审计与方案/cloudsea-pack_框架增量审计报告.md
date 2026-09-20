# 云海包（`origin/cloudsea-pack`）框架层增量审计报告

- **审计对象**：`origin/cloudsea-pack` @ `4a409bf`（= `/tmp/cs_audit` 工作树，二者 HEAD 相同）
- **我方基线**：`origin/main` @ `3131c5a`（含消息模板重构终态 813/809 键全量表、CTB 行动条战斗重写、Web 编辑器重写、字段展示元数据下放）
- **共同祖先**：`4ae3eaa`（2026-09-09）
- **范围**：`git diff --name-status origin/main...origin/cloudsea-pack -- qbot_rpg/ qbot_rpg_bridge/ scripts/ .github/` 命中的 **44 个文件**
- **方法**：只读。`git show/diff/numstat/grep` + 静态符号核对（`grep` 我方 main 的同名锚点）；未运行 pytest、未编译、未写任何被审文件。
- **本报告文件**：`/tmp/cloudsea_audit.md`（唯一新建文件）

> **命令口径说明**：`A...B` 三点 diff 以共同祖先为 base。因此某文件若被 main 删除、被云海侧修改，会显示为 `M`（如 `battle_tpl.py`）。判断"能否落到 main"必须另做 main 侧锚点核对，本报告逐项做了。

---

## 0. 结论速览

### 0.1 量化对账（实测）

| 区域 | 文件数 | +行 | −行 |
|:--|--:|--:|--:|
| `content/cloudsea/**`（C 类纯内容，不在本审计内，仅列总量） | 36 | +175,893 | 0 |
| `docs/cloudsea/**`（C 类，不在本审计内，仅列总量） | 49 | +5,476 | 0 |
| **`qbot_rpg/**`（审计范围）** | 23 | +2,226 | −37 |
| **`qbot_rpg_bridge/**`（审计范围）** | 3 | +178 | −14 |
| **`scripts/**`（审计范围）** | 17 | +2,720 | −2 |
| **`.github/**`（审计范围）** | 1 | +17 | −1 |
| `tests/**`（特别核对项 5，不在 scope 命令内但必须看） | 10 | +1,045 | −2 |
| 根文件（`.gitignore`/`CHANGELOG`/`README`/`.workbuddy`/`dist`） | 5 | +43 | −1 |
| **全量合计** | **144** | **+187,598** | **−57** |

审计范围（44 文件）合计 **+5,141 / −54**。

### 0.2 提案 A 类"15 件 / +885 / −51"对账结果：**算术精确命中，但披露不完整**

提案 §一 声称 A 类 =「core·content·storage 13 件 + bridge 2 件 = 15 文件 / +885/−51」。实测：

| 组 | 文件 | +/− |
|:--|:--|:--|
| `qbot_rpg/**` 修改 12 件 | sender / resource_axis_models / skill_models / validator / battle / monster_ai / monster_intent / monster_phases / resource_lifecycle / battle_tpl / (engine→core)condition_engine / migrations | +713 / −37 |
| `qbot_rpg_bridge/**` 修改 2 件 | `__init__.py` / `plugin.py` | +51 / −14 |
| `qbot_rpg/core/` 新增 1 件 | `gear_skill_aggregator.py` | +121 / −0 |
| **合计** | **15 件** | **+885 / −51** ✅ |

**结论**：提案的行数账目是诚实的、可复算的。但有三处实质缺口：

1. **漏报 2 处框架路径改动**（不在其 15 件内）：`.github/workflows/ci.yml` +17/−1、`scripts/deploy_smoke.py` +4/−2。二者都在审计 scope 内、都改的是框架文件。
2. **`battle_tpl.py` 在我方 main 已被删除**（2026-09-12 消息模板重构：删 21 个 `*_tpl.py` 分区 + 收敛为 `__init__.py`+`base.py`+`template_table.json`）。提案把它当"可收编的框架增强"，实际是**对一个不存在的文件打补丁**。这一项占了声称的 +15。
3. **提案基线早于我方 CTB 重写**（main `5ed44ee`「CTB 行动条战斗取代回合制」）。`battle.py` 的 +173 行**全部锚点在 main 已不存在**，属"整体重写"而非"收编"；`monster_ai.py` 同类降级。提案未披露这一前提差异。

### 0.3 五条红线级发现（详见 §3）

| # | 发现 | 证据 | 影响 |
|:--|:--|:--|:--|
| **R1** | `qbot_rpg/core/battle.py` 的 **每一个 hunk 锚点在 main 都不存在**（CTB 重写后无"回合"概念） | `grep -c 'self._dispatch_event("turn_start", "player")' main:battle.py` = **0**；`tick_round_end(...)` 调用 = **0**；`_dispatch_trigger_procs`/`_tick_field_periods`/`_tick_cloudsea_ailments`/`boss_state`/`per_segment_effects` 均 = **0** | 无法 patch，必须重写；A 类 ③ 主体作废 |
| **R2** | `storage/migrations.py` v1→v2 给核心 `players` 表加 **云海专属列** `cloudsea_state`，**但全新库拿不到该列** | `ensure_meta`：「全新库（players 无数据）→ 直接写 CURRENT 版本」= 2 ⇒ 迁移步不执行；而 `qbot_rpg/storage/schema.py` 与 main **逐字节相同**（`git diff` 空），`CREATE TABLE players` 无 `cloudsea_state` | 文档自称"新库 CREATE TABLE 已直接携带"**为假**；且全库无任何代码读写该列（仅注释/docstring 命中）——纯负债 |
| **R3** | `resource_lifecycle.py` 的"负向下限"是**行为变更，不是 opt-in** | `_gain_scalar`/`_gain_pool` 追加 `if nxt < 0: nxt = 0`；旧语义允许存负值 | 与提案"全部 opt-in、缺省零破坏"自述矛盾 |
| **R4** | `gear_skill_aggregator.load_tiers()` **缺 `import io`**，异常被 `except Exception` 吞掉 | `io.open(path,...)` 在 38 行，模块级 import 仅 19–21 行（`__future__` + `typing`） | 该函数**恒返回 `{"techs": []}`**，功能静默失效 |
| **R5** | 提案 §二.7「bridge 插件挂载点（游戏包以插件形态注册发送器/命令）」**不存在** | `qbot_rpg_bridge/plugin.py` 的全部 +23/−7、`__init__.py` 的全部 +28/−7 都是 **`/tmp` 调试日志的跨平台路径回退**，无一行业务挂载 | 提案以此作为 B 类"插件自持"的落地前提——前提不成立 |

另有一条**未披露的额外改动**：`qbot_rpg/content/validator.py` 除提案说的 2 处外，还有第 3 处（连段链长 >4 → Y-8 黄提示，见 §3.1）。

### 0.4 建议批次（详见 §4）

- **批次 1（立刻可收，5 件）**：`validator.py`（含第 3 处的取舍）、`monster_phases.py`、`monster_intent.py`、`condition_engine.py`（改路径）、`resource_axis_models.py`（+ 其测试改动）
- **批次 2（小改后收，3 件）**：`bridge/__init__.py`、`bridge/plugin.py`、`skill_models.py`（缓存套到 main 的新版 `skills_fields`）
- **批次 3（需真正改写，6 件）**：`gear_skill_aggregator.py`、`resource_lifecycle.py`、`monster_ai.py`、`sender.py`、`deploy_smoke.py`、模板 5 新键（改写进 `template_table.json` 而非 `battle_tpl.py`）
- **批次 4（拒收／另案，4+ 件）**：`battle.py`（重写而非收编）、`migrations.py`（去云海列/去全局版本号）、`ci.yml`、`battle_tpl.py`；`dist/**`、`*_out.txt`、`.workbuddy/**` 一律拒收
- **随内容包仓自持**：11 个 `cloudsea*` 文件 + 16 个脚本 + 9 个云海测试（唯一例外见 §3.2）

---

## 1. 基线与方法

| 项 | main | cloudsea-pack | 共同祖先 |
|:--|:--|:--|:--|
| 分支 tip | `3131c5a` | `4a409bf` | `4ae3eaa` |
| 领先/落后 | 领先 46 笔 | 落后 310 笔 | — |
| `qbot_rpg/engine/` | **已删**（`condition_engine.py`/`weather_conditions.py` 迁至 `qbot_rpg/core/`） | 仍为 `qbot_rpg/engine/` | 存在 |
| 战斗内核 | **CTB 行动条**（`battle.py` 5,386 行，快照 V2，拒收 v1 快照） | 回合制（3,905 行，快照 V1） | 回合制（3,734 行） |
| 模板层 | 全量表 `template_table.json`（809 键）+ `__init__.py` + `base.py`；21 个 `*_tpl.py` 已删 | 迁移期分区文件仍在（`battle_tpl.py` 等） | 分区文件并存 |
| Web | `qbot_rpg/web/{api,editor_ops,static}`（重写版） | `qbot_rpg/web/{api,auth,pages_crud,static}`（旧版，**本分支未改 web/**） | 旧版 |

**关键：**云海分支 46 笔提交里**没有一笔触碰 `qbot_rpg/web/**`**（`git diff --name-status origin/main...origin/cloudsea-pack -- qbot_rpg/web/` 为空），所以与我方编辑器重写**无直接文件冲突**；但 `scripts/web_shell.py` 属于第二套 UI（见 §3.4 ⑧）。

---

## 2. 逐文件总表

图例：opt-in = 缺省零行为；触碰 = 是否落在我们已重构的敏感区（模板分区删除 / `template_table.json` / content 字段元数据下放 / `qbot_rpg/web` 编辑器）。
"建议"：**收** = 可收 / **改** = 需改写 / **拒** = 拒收。

### 2.1 我方既有文件（16 个 `M`）

| 文件 | A/M | +/− | 它做了什么 | 真 opt-in? | 触碰重构区 | 冲突或风险 | 建议 | 改写要点 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `.github/workflows/ci.yml` | M | +17/−1 | 追加独立 job `cloudsea-package`：跑 `verify_cloudsea.py` + `package_cloudsea.py`，上传 `dist/cloudsea_content.zip` | 否（无条件执行） | 否 | 框架仓无 `content/cloudsea` → 该 job 必红；且它不是主门禁（主门禁是 `run_all_tests.py`），**没有让门禁更严** | **拒**（原样） | 若真要收：改为 `if: hashFiles('content/cloudsea/**') != ''` 的可选 job；或改为只归档不判定的 artifact |
| `qbot_rpg/commands/sender.py` | M | +30/−9 | 给 TPL-12/13/14 加可选 `ctx` 形参，从 `ctx["templates"]` 读 `err_*` 覆盖键 | 是（`ctx=None` → 原行为） | **是**（模板全量表） | ① 其基线是**未含我方 M8 免斜杠修复**的旧版（无 `frag = frag[1:]`），套用即回归；② 绕过 `_safe_format` 与 `resolve_templates` 白名单 → 内容包键会被静默丢弃；③ `err_condition`/`err_lack_resource` 不在我方表内，覆盖通道不成立 | **改** | 用既有 `tpl_of(ctx, "err_bad_command", {"fragment": clipped})`；保留 M8 剥斜杠；`err_condition`/`err_lack_resource` 作为框架键补进 `template_table.json`（默认值取 `errors.py` 现状），再给调用方注入 `ctx` |
| `qbot_rpg/content/resource_axis_models.py` | M | +41/−1 | 新增 3 个 opt-in 字段的 property + 登记：`tick_per_round`(0)/`tick_floor`(0)/`on_full`("")，并补 `__all__` | 是 | 是（content 字段元数据） | 与我方"字段展示元数据下放"接口一致但需内容包补 `field_meta` 条目，否则编辑器不显示中文名/分组 | **收** | 直接 patch（main 与 ancestor 逐字节相同，`__all__` 上下文吻合）；随包补 `field_meta` |
| `qbot_rpg/content/skill_models.py` | M | +16/−0 | 把 `skills_fields()` 拆成 `_build_skills_fields()` + 模块级惰性缓存 | 是（行为等价） | 是（字段登记表） | main 已在同文件 +33 行（F29/F30 `brief`/`detail` 等），函数体不同 → hunk 上下文不吻合 | **改** | 手工重做：在 main 的 `skills_fields()` 上套"缓存包装 + 拆 `_build_`"，保留 main 新增字段 |
| `qbot_rpg/content/validator.py` | M | +20/−1 | (a) `skill_or_any` 并集惰性缓存；(b) part 键白名单放行 `cls`/`break_behavior`；**(c) 未披露**：链长 >4 → Y-8 黄提示 | (a)(b) 是；(c) 会产生新告警 | 否 | main 三处锚点均与 ancestor 逐字节相同 → 可原样 patch；但 (c) 若被任何"warning=失败"的门禁消费，则非零行为 | **收（含 (c)，但需确认告警不进门禁）** | 直接 patch；若门禁对 warning 敏感，(c) 单独拆出评审 |
| `qbot_rpg/core/battle.py` | M | +173/−2 | 触发 proc 钩子表 + round_head 派发；冷却口径统一函数；段级 effect；环境场周期器；九态积蓄回合末衰减；`boss_state` 视图；`to_snapshot` 深拷贝改浅拷贝 | 部分（`to_snapshot` 浅拷贝**非** opt-in） | 否 | **全部锚点在 main 缺失（CTB 重写）**；`to_snapshot` 在 main 是 V2 + `copy.deepcopy` | **拒（原样）/改（重写）** | 按 CTB 事件位点重写：`round_head` 钩子挂 `ACTOR_TURN_START`/`BEFORE_ACTION`；周期器与积蓄衰减挂 `AFTER_ACTION`/`BATTLE_TIME_ADVANCE`；`boss_state` 并入 V2 快照；**浅拷贝优化另案并加隔离测试** |
| `qbot_rpg/core/monster_ai.py` | M | +175/−10 | 行为计数器（`seq_count`/`damage_taken_*`/`last_hp`）；`no/enter_when/from/latch/weakness/mods` 扩展阶段机 + `inherit_boss_state` 消费；3 个新内建条件 `seq_count`/`damage_taken`/`stamina_empty` | 计数器写入**非** opt-in（无功能影响）；阶段机与条件为 additive | 否 | ① main 已 +18 行（CTB 措辞 + 我方 `enemy_axis` 条件）→ `return False` 前多了一段，hunk 需重锚；② `stamina_empty` 与我方 `enemy_axis` 语义重叠（都读气力/耐力）→ 双口径风险 | **改** | 剥离为两个独立补丁：条件扩展（放到 `enemy_axis` 之后，并明确与它的分工）与阶段机扩展；计数器改为只在配置声明需要时写 |
| `qbot_rpg/core/monster_intent.py` | M | +18/−1 | `build_intent` 增 4 个 keyword-only 扩展字段 `stage_shift/windup/target_ref/damage_tier`，值为 `None` 时不入 dict | 是 | 否 | main 与 ancestor **逐字节相同** → 干净 patch；`adef` 变量在 main L86 存在 | **收** | 直接 patch |
| `qbot_rpg/core/monster_phases.py` | M | +39/−0 | 追加纯函数 `inherit_boss_state(prev, rules)`：按 `stack_retain`/`control_mult` 缩放 `break_slots`/`stamina`/`ailment_buildup` | 是（无人调用即零行为） | 否 | main 与 ancestor 逐字节相同；尾部追加，`Mapping/Any/Optional` 均已 import | **收** | 直接 patch |
| `qbot_rpg/core/resource_lifecycle.py` | M | +113/−10 | `effective_max`；`tick_per_round`/`tick_floor`/`on_full` 读取；`tick_round_end` 实装 tick + `frozen_sides` + `on_full_fired` 事件；**`_gain_scalar`/`_gain_pool` 负值钳 0** | tick 部分**是**；负值钳 **否** | 否 | ① main 仅 14 处措辞改动（回合→行动），上下文基本吻合；② 负值钳是全局行为变更，违反提案"opt-in"自述；③ `tick_round_end` 返回值多一个键（main 测试用子集断言，安全）；④ main 无调用点（CTB 走 `AFTER_ACTION`），接线要重做 | **改** | 负值钳若确为意图，单独提交 + 单独断言；tick 接线改挂 CTB `AFTER_ACTION`；`on_full_fired` 保持新键 |
| `qbot_rpg/core/templates/battle_tpl.py` | M | +15/−0 | 向迁移期分区文件追加 5 个战报模板键 + 占位符白名单 | n/a | **是（文件已删）** | **文件在 main 不存在**（模板重构已删 21 个分区）→ 无文件可 patch | **拒（原样）/改（键转移）** | 把 5 键写进 `qbot_rpg/core/templates/template_table.json`；占位符白名单在 main 已由表自动派生，无需另加 |
| `qbot_rpg/engine/condition_engine.py` | M | +50/−0 | 追加纯函数 `clamp_weight` / `condition_weight_product`（条件数组连乘 + clamp[1,100]） | 是（新增，无调用者） | 否 | **main 无此路径**：文件已迁 `qbot_rpg/core/condition_engine.py`（内容逐字节相同） | **收（换路径）** | 把 +50 追加到 `qbot_rpg/core/condition_engine.py` 尾部即可，零上下文调整 |
| `qbot_rpg/storage/migrations.py` | M | +23/−3 | `DB_SCHEMA_VERSION` 1→2；新增 `migrate_v1_to_v2` 给 `players` 加 `cloudsea_state` 列并注册迁移步 | **否** | 否 | ① 见 R2：全新库写版本 2 ⇒ 迁移不执行、`schema.py` 又无该列 ⇒ **新库缺列**；② 全库无任何代码读写该列；③ 框架全局 schema 版本被内容包需求推高 | **拒（原样）/改** | 内容包状态不入核心 `players` 表：改用 `persistent_state`/独立内容包状态表；若坚持加列，**必须同时改 `schema.py` 的 `CREATE TABLE players`** 并补"新库/旧库双向"测试 |
| `qbot_rpg_bridge/__init__.py` | M | +28/−7 | 调试日志路径从硬编码 `/tmp` 改为「`/tmp` → 仓库 `logs/`」回退，不可用则静默 | 是 | 否 | main 与 ancestor 逐字节相同；`Optional` 已在 typing 导入（无 NameError） | **收** | 直接 patch |
| `qbot_rpg_bridge/plugin.py` | M | +23/−7 | 同上（`_bridge_dbg()` 回退） | 是 | 否 | main 仅在 L112 注释改了一行（"回合"→"行动"），hunk 区域不同 → 干净 patch | **收** | 直接 patch（与 `__init__.py` 同一批） |
| `scripts/deploy_smoke.py` | M | +4/−2 | 默认包路径 `/root/.../content/demo_full` → **`content/cloudsea`**；DB 改 `data/deploy_smoke.db`；改用 `os.environ.setdefault` | **否**（改默认值） | 否 | main 无 `content/cloudsea` → 框架冒烟脚本必失败；`setdefault` 也救不了缺省场景 | **改** | 保留 `demo_full` 为缺省（或改成仓库相对的 `content/demo_full` + 绝对路径可覆盖）；云海默认值放回内容包仓的包装脚本 |

### 2.2 框架新增文件（12 个 `A`）

| 文件 | A/M | +/− | 它做了什么 | 真 opt-in? | 触碰重构区 | 冲突或风险 | 建议 | 改写要点 |
|:--|:--|:--|:--|:--|:--|:--|:--|:--|
| `qbot_rpg/core/gear_skill_aggregator.py` | A | +121 | 装备技能三档聚合纯函数：`load_tiers` / `resolve_tier` / `aggregate_gear_skills` | 是（零引擎 import） | 否 | **R4：缺 `import io` → `load_tiers` 恒返回空表**；硬编码云海套装白名单 `MUTATION_AFFINITY={"王骸","巨兽"}`（L127） | **改** | 修 `import io`（或直接 `open`）；`MUTATION_AFFINITY` 改为入参/数据驱动；补单测覆盖"文件存在→真读到 techs" |
| `qbot_rpg/core/cloudsea_ailment.py` | A | +88 | 九态积蓄数值核：`apply_buildup`（阈值/×3.0 增长上限/饱和）、`tick_round_end`（A−=D）、`tick_from_snapshot` | 是（零框架 import；唯一框架触点被 `try/except` 守卫） | 否 | 通用部分真实存在（见 §3.2A）；`DAMAGE_KIND={"ail_corrosion","ail_detonate"}` 硬编码 | **改（提通用化后收）** | 抽 `ailment_buildup` 通用核（阈值/增长/衰减全部由注入 spec 驱动），`DAMAGE_KIND` 改数据驱动；云海命名与云海 statuses 表留在包内 |
| `qbot_rpg/core/cloudsea_async.py` | A | +166 | 四件零墙钟异步组件：`TurnoutGuard`/`AutoplayDriver`/`OutboxQueue`/`LongSleepPolicy` | 是（无框架 import） | 否 | `AutoplayDriver` 硬编码云海语汇（`"调和"` L95、`"炮台守"/"side:"` L113）；`MutableMapping` 未使用 | **改（拆）** | `TurnoutGuard`/`OutboxQueue`/`LongSleepPolicy` 可通用化后进框架；`AutoplayDriver` 留包内 |
| `qbot_rpg/core/cloudsea_clock.py` | A | +53 | 合成游戏日钟：`synth_now(D)=anchor+D*86400+12h`、`game_week`、`is_in_beast_window` | 是（零 import） | 否 | `is_beast_window` 忽略 `game_day` 恒 True（自述为占位） | **改（去品牌后收）** | 仅收"锚点+日偏移"纯函数骨架；窗口判定留包内 |
| `qbot_rpg/core/cloudsea_gm.py` | A | +61 | `CLOUDSEA_STATE_VERSION=2`、GM 十指令 spec 表、纯函数 `diagnostic_pack(level)` | 是 | 否 | 版本常量与 `migrations.DB_SCHEMA_VERSION` **两处重复**（漂移风险）；GM 表为云海指令 | **改（拆）** | `diagnostic_pack`（L1/L2/L3 分级）通用可收；GM 表 + 版本常量留包内（版本常量应删或改为引用框架单源） |
| `qbot_rpg/core/cloudsea_tactics.py` | A | +199 | 战术四件套：态势动量+反击 proc、钉位连击、方位加成、响应槽；`register_cloudsea_tactics` 经注入的 `register_trigger_proc_hook` 挂钩 | 是（不注册即零行为） | 否 | 依赖 R1 要重写的 `TRIGGER_PROC_HOOKS`（main 无）；云海词表 `aberrant/tainted`、marks `rolling/burrowing/no_face` 硬编码；`position_bonus`/`ArmedQueue` 未被 `register_*` 接线 | **拒（本批）/改** | 先落 R1 重写后的钩子接口，再随包以插件形态自持；云海词表必须数据化 |
| `qbot_rpg/core/templates/cloudsea_emoji.py` | A | +54 | 进程级 emoji 白名单注册 + `validate_emoji_use` 正则校验（✅/❌ 恒放行） | 是（未注册 → 恒通过） | **是**（`core/templates/` 已收敛目录） | 无云海数据，纯通用校验器；但落在重构后的 `templates/` 目录并带云海前缀；正则会命中 `☀-➿ ⬀-⯿ ▪-◿ ←-⇿` 等大量非 emoji 符号（误报面） | **改（改名收）** | 更名 `qbot_rpg/core/templates/emoji_whitelist.py`（或 `qbot_rpg/core/message_format/`），收窄正则区间；注册表改为**按包作用域**而非进程全局 |
| `qbot_rpg/core/templates/cloudsea_err_tpl.py` | A | +72 | 21 键云海错误文案表 + 通用 `$C.DOMAIN.KEY` 字面替换 `expand_consts`（查不到保留字面） | 是（无框架 import） | **是**（`*_tpl.py` 名 + `templates/` 目录） | ① 名字形态正是我们**刚删掉的 21 个 `*_tpl.py` 分区**，会把分区文件重新引入收敛目录；② 21 键若走内容包 `templates.json`，会被我方 `resolve_templates` 按"未知键"丢弃 | **改** | 21 键表随内容包仓；`expand_consts` 若通用则迁 `qbot_rpg/core/`（非 templates/）并去 `cloudsea` 名；若确需框架放行这 21 键，须显式登记进 `template_table.json` |
| `qbot_rpg/commands/cloudsea_commands.py` | A | +243 | 注册 `帮/预/局面/挂/撤/1/2/3/4/绝` 云海指令 | 是（需显式注册） | 否 | 纯云海指令面；`format_tpl12` 未传 `ctx`；依赖 `router.CommandSpec`（main 存在） | **拒（框架仓）** | 随内容包仓；映射到框架命令扩展点 |
| `qbot_rpg/commands/cloudsea_deep_commands.py` | A | +160 | `深度炼成` 列表/配方 | 是 | 否 | 云海专属；**疑似逻辑缺陷（待确认意图）**：`lib["recipes"]` 只含 R-*，而 `depth2.base_ref` 为 `AD-*` ⇒ AD2 门控 `base_lv=0`、恒取 `2*step`（L84-87、L110-112） | **拒（框架仓）** | 随包；AD2 门控缺陷需包内确认后修 |
| `qbot_rpg/commands/cloudsea_extra_commands.py` | A | +296 | `港 档/港 鉴/勘察/晨报/预案` 五指令 | 是 | 否 | 云海专属；`make_context` 形参声明但**从未使用**；`SIDE_ENUM=["front","side","rear"]`（L42）与文档/自带兜底模板 `side:left`（L50）、`front|left|right|back`（L20,251）**三处矛盾**，导致 `_validate_preset` 警告自己的兜底模板；`router.register` 外层 `except: continue` 可静默跳过全部注册 | **拒（框架仓）** | 随包；先修 `SIDE_ENUM` 值域与 `make_context` 死形参 |
| `qbot_rpg_bridge/cloudsea_sender.py` | A | +127 | 战报频控调度器：30s 合并窗 + 摘要行 + 4 类 @白名单直发 + emoji 剥除 | 是（不实例化即零行为） | 否 | 零框架 import（只依赖注入回调）；`flush` 无定时器（窗到期后若无后续 `feed`，缓冲永不发出——待确认宿主职责）；`Dict` 未使用；模板键 `battle_merge_summary`/`battle_mention_line` 在 main 表内**不存在** | **改（去品牌后收）** | 更名 `qbot_rpg_bridge/report_throttle.py` 收进壳层（去掉云海模板键默认值，改为强制注入）；或在内容包仓自持并补宿主定时 flush 契约 |

### 2.3 工具脚本（16 个 `A` + `deploy_smoke.py` 已列于 2.1）

| 文件 | A/M | +/− | 它做了什么 | 真 opt-in? | 建议 | 说明 / 改写要点 |
|:--|:--|:--|:--|:--|:--|:--|
| `scripts/parse_doc12.py` | A | +283 | 12 号常量表 → `docs/cloudsea/fragments` 对账出片 | 是（独立脚本） | **拒** | 硬编码 `../yunhai/cloudsea-hunting-corps/12_全局常量表.md`、输出 `docs/cloudsea/` |
| `scripts/parse_actions.py` | A | +261 | 动作池四册 → `content/cloudsea/action.json` | 是 | **拒** | 硬编码设计稿路径与输出 |
| `scripts/parse_enemies.py` | A | +336 | 七潮位怪物五源合流 → `enemies_t{1..7}.json` | 是 | **拒** | 同上；含 `BASE_EHP`/tide 专属常量 |
| `scripts/parse_quests_maps.py` | A | +260 | 章节卡 → `quest.json`(540) + `maps.json`(28) | 是 | **拒** | 同上 |
| `scripts/assemble_enemies_226.py` | A | +144 | t1–t3 → `enemies.json` 组装 | 是 | **拒** | 同上 |
| `scripts/verify_tide_pack.py` | A | +128 | 七潮位分版本验收探针 | 是 | **拒** | 同上 |
| `scripts/verify/verify_cloudsea.py` | A | +148 | 云海包三段探针（结构/数据/功能）+ 方位断言 | 是 | **拒（框架仓）** | 云海专属；注意它落在**框架既有的 `scripts/verify/` 目录**——但 main 的 `run_all_tests.py` 是**显式枚举** verify 脚本（`VERIFY_M0 = REPO/"verify"/"verify_m0.py"`），故不会被自动纳入门禁（好消息） |
| `scripts/package_cloudsea.py` | A | +30 | `content/cloudsea` → `dist/cloudsea_content.zip` | 是 | **拒** | 输出二进制产物；与 `.gitignore` 新增 `dist/` 自相矛盾 |
| `scripts/package_standalone.py` | A | +154 | 整机交付 zip（引擎源码 + 云海包 + demo_full + web_shell + 部署 README） | 是 | **改（去云海化后可收）** | 骨架是通用的"仓库 zip 打包器"（stdlib `zipfile`/`py_compile`、排除 `__pycache__/.git/data/logs/dist`）；但 `INCLUDE` 硬编码 `content/cloudsea`、`docs/cloudsea/云海转化映射表.md`，`README_DEPLOY` 全文云海 |
| `scripts/web_shell.py` | A | +152 | 单文件 stdlib web 游玩壳（`http.server` + `build_app_deps` + `run_command`） | 是 | **改（去品牌后可收／待确认）** | 依赖的 `qbot_rpg_bridge.assemble.build_app_deps`（main L130）与 `qbot_rpg.assembly.runner.run_command`（main L778）**都存在**，签名 `build_app_deps(*, pack_dir, db_path, settings)` 吻合（调用 `build_app_deps(pack_dir=..., db_path=...)` ✅）；但缺省 `--pack content/cloudsea`（main 无此目录）、UI 全云海文案。与我们的 web 编辑器是**两套 UI**，需明确取舍 |
| `scripts/e2e_cloudsea_mvp.py` | A | +87 | 第 1 章 MVP E2E 灰岗闭环 | 是 | **拒** | 云海专属流程 |
| `scripts/e2e_cloudsea_mvp_out.txt` | A | +251 | 上述 E2E 的**输出转储文本** | n/a | **拒** | 非代码产物，不应入库 |
| `scripts/批次210_生成.py` | A | +97 | 生成 `content/cloudsea` 骨架 | 是 | **拒** | 中文批次脚本；生成器 |
| `scripts/批次221_技能.py` | A | +166 | 职业卡 → `skills.json` | 是 | **拒** | 含 **Windows 绝对路径** `D:\1V1TXTRPG\...` |
| `scripts/批次221_萃取.py` | A | +89 | 14 职业卡 → `jobs.json` | 是 | **拒** | 同上（`D:\...`） |
| `scripts/批次223_萃取.py` | A | +130 | 武器图鉴 → `generated/equipment_index_223.json` | 是 | **拒** | 同上（`D:\...`） |

> **命名勘误**：任务清单写作 `批次221_汲取.py`/`批次223_汲取.py`；仓库实际文件名为 `批次221_萃取.py`/`批次223_萃取.py`。

---

## 3. 特别核对项

### 3.1 `qbot_rpg/content/validator.py`：能否原样移植到我方 main？

**结论：两处都能原样移植（直接 patch，零上下文调整）。同时存在提案未披露的第 3 处改动。**

**前提核对**：`git log --oneline 4ae3eaa..main -- qbot_rpg/content/validator.py` → **空**。即 main 自共同祖先以来**从未改过 validator.py**；`git show main:...|wc -l` = 2114 = ancestor 行数。三处 hunk 的上下文与 main 逐行吻合（已核对 L861-866、L1964-1966、L1995-1998）。

**(a) `skill_or_any` 并集惰性缓存（性能修复）** — 3 个 hunk：

```python
# ① 初始化（main L379 区，紧随 _element_reg 先例）
         self._element_reg: Optional[frozenset] = None
+        self._all_ref_ids_cache: Optional[set] = None
# ② 写面失效（main L438 _register_id 内）
     def _register_id(self, kind, namespace, eid, module_name) -> None:
         self._id_space.setdefault(kind, {}).setdefault(eid, module_name)
+        self._all_ref_ids_cache = None
# ③ 读面命中（main L1956 if target == "skill_or_any":）
-            all_reg = {e for ids in self._id_space.values() for e in ids}
+            if self._all_ref_ids_cache is None:
+                self._all_ref_ids_cache = {e for ids in self._id_space.values() for e in ids}
+            all_reg = self._all_ref_ids_cache
```

**移植方式：直接 patch。** 正确性成立的关键是"所有 `_id_space` 写点都经 `_register_id`"。已核对：main 中 `_id_space` 的写入只出现在 `_register_id` 一处（`setdefault(kind, {}).setdefault(eid, ...)`），且 `_all_ref_ids_cache` 在 `__init__` 里声明，无跨实例泄漏。**唯一残留风险**：若未来有人绕过 `_register_id` 直接写 `_id_space`，缓存会陈旧——建议在 `_all_ref_ids_cache` 处加一行注释约束（延伸原注释里的"注册即失效"）。

**(b) part 键白名单放行 `cls` / `break_behavior`** — 1 个 hunk，位于 `_check_parts` 的 part 键白名单环：

```python
             for k in part:
+                # 九期238：白名单放行云海两键——cls（件型标注）与 break_behavior
+                if k in ("cls", "break_behavior"):
+                    continue
                 if k not in ("id", "name", "positions", "break_threshold",
                              "target_priority", "on_break"):
                     self._err(module_name, f"{pth}.{k}", "R-5", rule="R16_part_unknown_key", ...)
```

**移植方式：直接 patch。** 但请注意**语义**：这**不是**"框架实现了部件破坏绑定"，而是**校验器不再红拦这两个键**。全分支 `break_behavior` 的代码命中只有：本白名单、`scripts/assemble_enemies_226.py:80/97`、`scripts/parse_enemies.py:263`——即**消费方不在这 15 件框架增量里**（提案 §二.3 称"部件破坏绑定（part 键 break_behavior 白名单）"属表述过度）；真正扣血/破坏结算在云海增量 hook 面（且其宿主 `battle.py` 部分在 main 不存在，见 R1）。

**(c) 提案未披露的第 3 处：连段链长校验** — `_check_chain_cycle` 内，紧随 `adj` 构建、在"# 环检测（有向）DFS"之前：

```python
+        # 九期207：链长校验（$C.POOL.CHAIN_MAX=4 同源上限）——链 next 列表超长
+        # Y-8 黄提示不红拦（八期池契约链长 2–4，超长多为配置笔误）。
+        for _eid, _nxt in adj.items():
+            if len(_nxt) > 4:
+                self._warn(module_name, f"{module_name}.{_eid}.{mmeta.chain_field}", "Y-8",
+                           rule="chain_length_exceeded", length=len(_nxt), max=4)
```

main 的 `_check_chain_cycle`（L1969 起）与之逐行吻合，`_warn(self, module, field, kind, **detail)` 签名一致（L387），**可原样 patch**。
**唯一需拍板**：这是新增**告警**，严格讲不是"缺省零行为"。我方 `tests/unit/test_chain_*` 等是否对 warning 计数做精确断言、`scripts/verify/verify_m0.py` 是否把 warning 当失败——**本审计未运行门禁，标「待确认」**。若门禁对 warning 敏感，(c) 应从 (a)(b) 拆出单独评审。

**综合建议**：(a)(b) 直接 patch 收；(c) 同批或拆批评审。

---

### 3.2 云海专属件清单 + 摘出框架树后仍需保留的通用能力

`qbot_rpg/**` 与 `qbot_rpg_bridge/**` 中 `cloudsea*` 命名文件共 **11 件**，全部为新增（`A`），合计 **+1,459 行**：

| 件 | 行数 | 依赖的框架能力（实测） |
|:--|--:|:--|
| `core/cloudsea_tactics.py` | +199 | `register_trigger_proc_hook`（云海侧 `battle.py:88` 定义）；快照 `monster.marks.pinned/pinned_by` |
| `core/cloudsea_async.py` | +166 | **零框架 import**；注入的 `ctx["game_day"]` |
| `commands/cloudsea_extra_commands.py` | +296 | `router.CommandSpec`；ctx 键 `player/registered/game_day/args/cloudsea_pkg/preset_store/cloudsea_enemies_t1..t7/...` |
| `commands/cloudsea_commands.py` | +243 | `router.CommandSpec`（L35）、`format_tpl12`（L36）；ctx `battle_snapshot/cloudsea_presets/shortcut_exec` |
| `commands/cloudsea_deep_commands.py` | +160 | `CommandSpec`、`format_tpl12`、`cloudsea_err_tpl.expand_consts`；ctx `cloudsea_consts/cloudsea_recipes/alchemy_level` |
| `qbot_rpg_bridge/cloudsea_sender.py` | +127 | **零框架 import**；注入回调 `send` / `tpl`（形如 `tpl_of`）/ `emoji_validator` |
| `core/cloudsea_ailment.py` | +88 | **零框架 import**；被框架 `battle.py:3682` 守卫式反向调用 |
| `core/templates/cloudsea_err_tpl.py` | +72 | **零框架 import** |
| `core/cloudsea_gm.py` | +61 | **零框架 import**（版本常量与 `migrations` 重复） |
| `core/templates/cloudsea_emoji.py` | +54 | **零框架 import** |
| `core/cloudsea_clock.py` | +53 | **零框架 import** |

#### 摘出框架树后，哪些通用能力仍需保留？

**先说最重要的结论（反向依赖核查）**：
- `git grep -i cloudsea origin/main` → **0 命中**（main 干净）。
- 云海侧：**唯一一条"框架文件 import 云海模块"的边是 `qbot_rpg/core/battle.py:3682`**，且被双重保护——先 `if not isinstance(self._snap.get("cloudsea_statuses"), dict) or not ...: return`，再 `try/except Exception: return`。因此**内容包缺席不会破坏框架 import**。
- 其余命中全是注释（`sender.py:90`、`validator.py:866`、`battle_tpl.py:145`）或 docstring（`gear_skill_aggregator.py:4`）。
- 但**框架侧硬耦合有两处不是文件不 import 就能摘干净的**：`storage/migrations.py`（`DB_SCHEMA_VERSION=2` + `players.cloudsea_state` 列，见 R2）与 `battle.py`（`_tick_cloudsea_ailments` 调用点，见 R1）。这两处才是"摘出框架树"的真实门槛。

**`cloudsea_ailment.py` 是否只是云海行为？——不是，有可通用化部分。**
`tick_from_snapshot(snap, statuses)`（L82-88）与 `CloudseaAilmentState.apply_buildup/tick_round_end`（L40-79）中**没有任何云海 import 或云海 id**：行为完全由注入的 `statuses` spec 驱动（`threshold_T`/`growth_mult`/`max_per_battle`/`decay_D`），快照键 `boss_state.ailment_buildup` 也是通用契约（`battle.py` 侧保证为 dict）。云海专属只有 `DAMAGE_KIND = {"ail_corrosion","ail_detonate"}`（L25）与命名；其 docstring 自称"框架转译数值核"。→ **建议：通用"积蓄/异常累积（buildup→threshold→decay）"核入框架，云海 statuses 表与 DAMAGE_KIND 留包内（改数据驱动）。**

**`cloudsea_emoji.py`：是通用校验器，不是云海表。** 模块内**零云海常量/数据**，白名单全靠运行时 `register_emoji_whitelist` 注入，未注册即恒通过（L50-51），正则与 `FUNCTIONAL_MARKS={✅,❌}` 均为通用。只有文件名与 docstring 带"cloudsea"。→ **11 件里最强的"应该进框架"候选**（改名 + 收窄正则 + 改按包作用域）。

**其他可通用化的部分**（建议按此切分，而非整件收/整件拒）：

| 件 | 可通用化部分 | 必须留包内的部分 |
|:--|:--|:--|
| `cloudsea_clock.py` | 锚点+日偏移的合成钟骨架 | 锚点值、`SYNTH_CLOCK_KEY`、`is_in_beast_window` |
| `cloudsea_gm.py` | `diagnostic_pack` L1/L2/L3 分级装配 | GM 十指令表、`CLOUDSEA_STATE_VERSION` |
| `cloudsea_async.py` | `TurnoutGuard` / `OutboxQueue` / `LongSleepPolicy` | `AutoplayDriver`（硬编码"调和"/"炮台守"） |
| `cloudsea_err_tpl.py` | `expand_consts`（`$C.*` 字面替换） | 21 键云海文案表 |
| `cloudsea_sender.py` | 合并窗 + @白名单 + emoji 剥除的调度骨架 | 云海模板键默认值 |
| `cloudsea_tactics.py` | 依赖通用钩子接口（需先有 R1 重写） | 云海 graylist/marks 词表 |

---

### 3.3 改我们既有文件的 3 处高风险改动

#### (1) `qbot_rpg/commands/sender.py`（+30/−9）

**他们改了什么**：给 `format_tpl12/13/14` 加可选 `ctx: Any = None`；新增 `_err_tpl(ctx, key, fallback)`，从 `ctx.get("templates")` 取 `err_bad_command`/`err_condition`/`err_lack_resource` 覆盖值，取不到回落 `errors.py` 常量。

**与我们现状的冲突（三重）**：
1. **基线过时，会回归我方 M8 修复。** 他们的 `format_tpl12` 体是 `clipped = fragment[:20] + ...`；我方 main（`88c024a`「M8 复核修复」）已是：
   ```
   frag = str(fragment or "")
   if frag.startswith("/"):   # ← 他们版没有这两行
       frag = frag[1:]
   clipped = frag[:20] + ...
   ```
   若按 diff 机械套用，直接丢掉"玩家可见文案零斜杠"修复。
2. **绕过我方模板基建。** main 已有 1198 处调用的统一入口 `tpl_of(ctx, key, data)`（`core/templates/__init__.py:129`）与 `render_template`（含 `_safe_format` 花括号保护 + 缺失 key 回落 `DEFAULT_TEMPLATES`），且 `resolve_templates`（L86）对**未知键会告警并丢弃**。他们的 `ctx["templates"].get(key).format(...)` 既无花括号保护，也无"未知键可见性"。
3. **两个键在我方表内不存在。** `template_table.json`（809 键）只有 `err_bad_command`；`err_condition`/`err_lack_resource` **查无此键** → `resolve_templates` 会把内容包注入的这两个键当未知键丢掉，**覆盖通道实际不成立**。

有意思的是，我方 `errors.py:26-28` 的注释**已经预告了他们的方向**：
> 「TPL-12（M8 复核修复 2026-09-12）：文案迁全量表键 `err_bad_command`…本模块读**默认表值**作唯一源——`format_tpl12` 家族无 ctx 形参，**内容包覆盖需后续给调用方注入 templates**」

**怎么改写**：
- 保留"可选 `ctx` 形参"这一向后兼容形状（161 个调用点不必全改）；
- 实现改走基建：`return tpl_of(ctx, "err_bad_command", {"fragment": clipped}) if ctx is not None else TPL_ERR_BAD_COMMAND.format(fragment=clipped)`，并**保留 M8 剥斜杠**；
- 把 `err_condition`/`err_lack_resource` 作为框架默认键补进 `template_table.json`（默认值取 `errors.py` 现值），这样内容包覆盖才真正生效；
- 若要支持云海 21 条 `err_*`，必须**显式登记白名单**（否则被 `resolve_templates` 丢弃）。

#### (2) `qbot_rpg/core/templates/battle_tpl.py`（+15，**main 已删除该文件**）

**他们改了什么**：向迁移期分区文件 `battle_tpl.py` 的 `DEFAULT_TEMPLATES` 追加 5 键（`battle_stage_shift_line`/`battle_windup_unknown`/`battle_windup_ready`/`battle_merge_summary`/`battle_mention_line`），并同步追加 `PLACEHOLDER_WHITELIST`。

**与我们现状的冲突**：
- `git cat-file -e main:qbot_rpg/core/templates/battle_tpl.py` → **fatal: Not a valid object name**。main 的 `qbot_rpg/core/templates/` 只有 `base.py` / `__init__.py` / `template_table.json`（我方 `204b052`「模板·终态：删除 21 个迁移期分区空壳 + 加载链收敛」）。
- 且 main 侧这 5 个键**都不在表内**：`template_table.json` 查询结果 `battle_stage_shift_line/battle_windup_unknown/battle_windup_ready/battle_merge_summary/battle_mention_line` → **全部 `None`**。而 `resolve_templates` 会丢弃未知键 ⇒ **内容包 `templates.json` 对这 5 键的覆盖会被静默忽略**（还会打 warning）。
- 附带连带：`cloudsea_sender.py` 的模板注入依赖这 2 个键；`test_cloudsea_215.py` 断言这 5 键在 `DEFAULT_TEMPLATES`+`PLACEHOLDER_WHITELIST` 中——在 main 形态下该断言需重写为查 `template_table.json`。

**怎么改写**：把这 5 键（含 `battle_summary_*` 同族风格的中文文案）写进 `qbot_rpg/core/templates/template_table.json` 的 `templates` 段；**占位符白名单不用手写**——main 已由表内 key 的占位符自动派生（`__init__.py` 顶部设计说明 + `_PLACEHOLDER_RE`）。相应测试改为读 `DEFAULT_TEMPLATES`（由 `table` 合并而来）即可。

#### (3) `scripts/deploy_smoke.py`（M，+4/−2）

**他们改了什么**：
```python
-os.environ["QBotRPG_PACK_DIR"] = "/root/QBot-TurnTellerRPG/content/demo_full"
-os.environ["QBotRPG_DB_PATH"] = "/root/QBot-TurnTellerRPG/data/rpg_full_test.db"
+_ROOT = Path(__file__).resolve().parent.parent
+os.environ.setdefault("QBotRPG_PACK_DIR", str(_ROOT / "content" / "cloudsea"))
+os.environ.setdefault("QBotRPG_DB_PATH", str(_ROOT / "data" / "deploy_smoke.db"))
```

**与我们现状的冲突**：main **没有 `content/cloudsea/`**（实测 `ls: cannot access 'content/cloudsea': No such file or directory`；main 的 content 目录为 `demo_blank/demo_full/demo_lv15/demo_lv30/demo_lv45/test_demo/veinborn/zz_probe_packmeta`）。缺省值一旦变成云海包，框架自带的部署冒烟脚本在 main 上**必然打不开包而失败**。`setdefault` 只在环境变量已设时兜底，救不了缺省路径。

**怎么改写**：拆成两件事——
- **可收的部分**：去掉硬编码 `/root/...` 绝对路径，改成 `_ROOT / "content" / "demo_full"` 与 `_ROOT / "data" / "deploy_smoke.db"`（这是真正的通用化修复）；
- **拒收的部分**：把缺省包指向 `content/cloudsea`；该缺省应由内容包仓自己的包装脚本/CI 覆盖（`QBotRPG_PACK_DIR=content/cloudsea python scripts/deploy_smoke.py`）。

---

### 3.4 A 类八项能力域逐项核对

> 每项格式：涉及文件与行数 → 是否真 opt-in → 与 main 的冲突点 → 建议与改写要点。

#### ① 资源轴生命周期
- **文件行数**：`core/resource_lifecycle.py` +113/−10；`content/resource_axis_models.py` +41/−1（3 个缺省常量 + 3 个 property + 3 个 `FieldMeta` + `__all__`）
- **真 opt-in?** **部分不是**。新增 `effective_max` / `tick_per_round` / `tick_floor` / `on_full` 与 `tick_round_end` 的 tick 分支确为 opt-in（缺省 0 / "" → 跳过）。但 `_gain_scalar`（main L235）/ `_gain_pool`（main L245）追加的 `if nxt < 0: nxt = 0` 是**全局行为变更**：旧实现允许把轴值减为负数。
- **与 main 冲突**：文件层面几乎无冲突（main 相对 ancestor 仅 14 处措辞替换"回合→行动"，已核 `git diff --stat` = 14/14，上下文吻合）。**真冲突在接线**：`ResourceLifecycle(...).tick_round_end(self._snap)` 的调用点在他们 `battle.py:3439`，而 main 的 `battle.py` **根本没有 `tick_round_end` 调用**（`grep` = 0）；main 的 CTB 资源结算是 `_resource_ctx` + `resource_axis.apply_gain`（battle.py L1154/L1273）与战斗结束的 `battle_end_reset`（L1942）。main 里 `tick_round_end` 只剩定义与单测。
- **建议**：**改**。
- **改写要点**：(a) 负值钳 0 拆成独立提交 + 独立断言（若确为意图）；(b) tick 结算重新挂到 CTB 的 `AFTER_ACTION` 位点，并用 `frozen_sides` 承载"被控不增不减"；(c) `tick_round_end` 返回值新增 `"on_full_fired"` 是安全的——main 的单测（`tests/unit/test_resource_lifecycle.py:263`）只做子集断言（`out["player"]["rage"]`），无全等比较；(d) `resource_axis_models` 的 3 个新字段是 FieldMeta 登记，属我方"字段展示元数据下放"的同一接口，**需随内容包补 `field_meta.json` 条目**（否则编辑器无中文名/分组）。

#### ② Boss 阶段状态继承
- **文件行数**：`core/monster_phases.py` +39（纯函数 `inherit_boss_state`）；消费方在 `core/monster_ai.py`（阶段扩展块内，见下）
- **真 opt-in?** **是**。`monster_phases.py` 只是尾部追加一个纯函数，无人调用即零行为；`rules` 缺省/`None` → 原值透传。
- **与 main 冲突**：**无文件冲突**。`monster_phases.py` main 与 ancestor **逐字节相同**（254 行）；`Mapping/Any/Optional/Sequence` 均已 import（L36）。
- **建议**：**收**（`monster_phases.py` 直接 patch）。
- **改写要点**：函数本身零调整。但注意它的**消费方**在 `monster_ai.py` 的扩展阶段机内（`entry.get("inherit_rules")` → `battle_state["boss_state"] = inherit_boss_state(...)`），那部分随 ③ 一起改；另：`battle.py` 侧还提供 `boss_state()` 视图（把 `break_slots/stamina/ailment_buildup` 三键 setdefault 进快照）——在 main 的 CTB 快照 V2 下需要另找落点（可并入 `_snap` 顶层，随 V2 全量携带）。

#### ③ 战斗核心适配面（部件/位面/air）
- **文件行数**：`core/battle.py` +173/−2；`core/monster_ai.py` +175/−10；`core/monster_intent.py` +18/−1；`content/validator.py` 的 `cls`/`break_behavior` 白名单
- **真 opt-in?** 子项混合：`monster_intent` 是（`None` 不入 dict）；`monster_ai` 的计数器写入**非**（`decide()` 每次无条件写 `seq_count`/`damage_taken_*`/`last_hp`）；`battle.py` 的 `to_snapshot` 深拷贝→浅拷贝**非**（行为/隔离性变更）。
- **与 main 冲突（本项最重）**：
  - **R1 级**：`battle.py` 的**全部 6 个 hunk 锚点在 main 均不存在**。逐锚点实测（`grep -c` on main `battle.py`）：`def unified_cooldown_turns`=0、`TRIGGER_PROC_HOOKS`=0、`_dispatch_trigger_procs`=0、`self._dispatch_event("turn_start", "player")`=0、`tick_round_end(...)`=0、`_tick_field_periods`=0、`_tick_cloudsea_ailments`=0、`def boss_state`=0、`per_segment_effects`=0。main 的 `battle.py`（5,386 行 vs 他们 3,905 行）是 `5ed44ee`「CTB 行动条战斗取代回合制」的整篇重写，模块 docstring 明写"**不存在「回合」这一时间单位**"、快照 `schema_version=2`、拒收 v1 快照、边界枚举为 `actor_ready`/`after_action`。
  - **③ 的一半能力其实早已存在**：提案称的"部位 positions 数组值域（side→四值）、air 语义"并非他们的增量——`qbot_rpg/content/validator.py:786/1237`（`("height",("ground","air"))`）、`content/skill_action_models.py:107`（`AIR_POLICY_VALUES=("preserve","land","preserve_height")`）、`content/field_meta.py:139`、`core/effects.py` 在 **ancestor 就已存在**（`git diff 4ae3eaa...origin/cloudsea-pack -- 这些文件` 为空），main 同样具备（四文件在 main 均 EXISTS）。他们真正的增量只是"validator 放行两个键 + 云海侧消费"。
  - `monster_ai.py`：main 已 +18 行（措辞 + **我方 `enemy_axis` 内建条件**）。他们的新条件 hunk 尾部上下文 `return False` 在 main 被 `enemy_axis` 块隔开 → 需重锚；且 `stamina_empty` 与 `enemy_axis` **语义重叠**（都读气力/耐力），存在双口径风险。
  - `monster_intent.py`：main 与 ancestor 逐字节相同（339 行），`adef` 在 main L86 存在 → **干净 patch**。
- **建议**：`monster_intent.py` **收**；`monster_ai.py` **改**；`battle.py` **拒（原样）/改（重写）**；validator 白名单 **收**。
- **改写要点**：
  - `battle.py`：按 CTB 事件位点重写——`round_head` 钩子 → `ACTOR_TURN_START`/`BEFORE_ACTION`；环境场周期器与积蓄衰减 → `AFTER_ACTION`/`BATTLE_TIME_ADVANCE`；`boss_state` → 并入 V2 快照顶层；`per_segment_effects` → 迁到 CTB 段结算循环；`unified_cooldown_turns` → 可原样复用（纯函数，但 main 的冷却写入点已改，需重接）。
  - **`to_snapshot` 浅拷贝必须单独评审**：main 是 V2 + `copy.deepcopy(self._snap)`（L5055）。他们的不变式论证依赖"调用方随即 JSON 序列化后才演进战斗"，而 main 的 `to_snapshot` 还要往顶层塞 `ctb_state`/`snapshot_context` 等结构，`units`/`ai_state`/`marks` 等子树会被共享。作为性能优化（12MB 包启动前置）可以考虑，但**必须**：单独立项、补"快照后继续战斗再比对快照内容"的隔离回归测试。本轮**建议拒收**。

#### ④ 装备技能聚合器
- **文件行数**：`core/gear_skill_aggregator.py` +121（新增，零引擎 import）
- **真 opt-in?** **是**（新文件、无调用者）。
- **与 main 冲突**：无文件冲突（纯新增）。**但功能已坏**：R4——`io.open(path,...)`（L38）而模块级只有 `from __future__` + `from typing`（L19-21），**没有 `import io`**；`NameError` 被 `except Exception`（L41）吞掉 → `load_tiers` **恒返回 `{"techs": []}`**，即使 `skill_tiers.json` 存在也读不到。另：`MUTATION_AFFINITY={"王骸","巨兽"}`（L127）把云海套装名硬编码进框架文件。
- **建议**：**改**。
- **改写要点**：修 `import io`（或直接用内建 `open`）；`MUTATION_AFFINITY` 改为入参或由 `skill_tiers.json` 数据驱动；**补一条"文件存在 → 真读到 techs"的单测**，否则该缺陷会再次逃逸（现有测试只覆盖聚合算术）。

#### ⑤ 内容模型与校验扩展
- **文件行数**：`content/validator.py` +20/−1；`content/resource_axis_models.py` +41/−1；`content/skill_models.py` +16/−0；`tests/unit/test_resource_axis_models.py` +4/−2
- **真 opt-in?** validator (a)(b) 是，(c) 产生新告警；`resource_axis_models` 是（新增字段 + 缺省常量）；`skill_models` 是（纯缓存，行为等价）。
- **与 main 冲突**：
  - `validator.py`：main **从未改过**（`git log 4ae3eaa..main -- <file>` 空）→ 三处均可直接 patch（§3.1）。
  - `resource_axis_models.py`：main 与 ancestor 逐字节相同 → 干净 patch；测试文件 main 也**未改过**，仍在断言 `test_def_fields_table_10_keys`（L101-103，10 键）→ 他们的 `13_keys` 改法可直接套用。
  - `skill_models.py`：**main 已 +33 行**（F29/F30 `brief`/`detail` 及字段登记），`skills_fields()` 位置从 385 变到 407 且函数体不同 → 缓存重构需手工套到新版。
- **建议**：validator + resource_axis_models **收**；skill_models **改**。
- **改写要点**：`skill_models` 在 main 的 `skills_fields()`（L407）外包一层 `_SKILLS_FIELDS_CACHE` + 拆 `_build_skills_fields()`，保留 F29/F30 新字段；顺带核对是否有别处也在重建这 24→26 个 `FieldMeta`（同一性能问题的另一实例）。

#### ⑥ 条件引擎 + 存档迁移
- **文件行数**：`engine/condition_engine.py` +50/−0；`storage/migrations.py` +23/−3
- **真 opt-in?** 条件引擎**是**（两个纯函数，无调用者）；存档迁移**否**（全局 `DB_SCHEMA_VERSION` 1→2 + 核心 `players` 表加云海列 + 迁移步注册）。
- **与 main 冲突**：
  - 条件引擎：**main 无 `qbot_rpg/engine/`**（已迁 `core/`）。`git diff 4ae3eaa:qbot_rpg/engine/condition_engine.py main:qbot_rpg/core/condition_engine.py --stat` = **空** ⇒ 两文件逐字节相同。main 的 `core/condition_engine.py` 已具备 `Mapping`/`Optional`（L73）与 `eval_condition`（L731）⇒ 把 +50 追加到**新路径**尾部即可，零上下文调整。
  - 存档迁移：**R2 级**。`ensure_meta` docstring 明写「全新库（players 无数据）→ 直接写 CURRENT 版本」⇒ 新库直接是 v2，**`migrate_v1_to_v2` 永不执行**；而 `qbot_rpg/storage/schema.py` 与 main **逐字节相同**（无 `cloudsea_state` 列，已核 `CREATE TABLE players` L41-66 全列）⇒ 文档中"新库 CREATE TABLE 已直接携带（read 路径 row_to_player 缺补忽略天然兼容）"这一句**与事实相反**。旧库（有 players 数据但 meta 缺失 → 回填 1）才会走 ALTER。且全仓 `cloudsea_state` 只出现在注释/docstring/迁移里，**没有任何读写方**（`git grep -n cloudsea_state origin/cloudsea-pack` 仅 `cloudsea_gm.py` 文档与 `migrations.py` 本体）。他们的测试 `tests/test_cloudsea_237.py` 只断言 `DB_SCHEMA_VERSION==2`、迁移链完整、常量一致，**从不打开数据库验证列存在** → 缺陷未被覆盖。
- **建议**：条件引擎 **收（换路径）**；存档迁移 **拒（原样）/改**。
- **改写要点**：条件引擎两个纯函数能否对齐 main 的 `# --- 条件校验 ---` 尾部；迁移若确需内容包状态，走 `persistent_state`（已存在）或内容包独立状态表，**不要**把 `cloudsea_state` 写进核心 `players`；若坚持加列，**必须同步改 `schema.py` 的 `CREATE TABLE players`**，并补"新库直接建表 + 旧库 ALTER"双向测试（不能只测常量）。

#### ⑦ bridge 插件挂载点
- **文件行数**：`qbot_rpg_bridge/__init__.py` +28/−7；`qbot_rpg_bridge/plugin.py` +23/−7
- **真 opt-in?** **是**。
- **与 main 冲突**：`__init__.py` main 与 ancestor **逐字节相同**（254→？实测 `git diff 4ae3eaa..main -- qbot_rpg_bridge/__init__.py` 为空）；`plugin.py` main 只改了 L112 一行注释，与 hunk 区域不同 → 两者都可干净 patch。`Optional` 已在 `__init__.py` 的 typing 导入（L31）⇒ 无 `NameError`。都不触碰 `qbot_rpg/web`。
- **建议**：**收**（作为"调试日志跨平台回退"小修），但**必须纠正提案定性**。
- **改写要点**：**提案 §二.7 名不副实**。所谓"游戏包以插件形态注册发送器/命令的挂载机制雏形"在这 51 行里**不存在**——两个文件的全部改动就是把硬编码 `/tmp/qbot_rpg_bridge_debug.log` 换成「`/tmp` → 仓库 `logs/`」的 `os.path.isdir` 回退并对不可用静默。这直接影响提案 §三 的推理链：B 类"改为插件自装"**缺乏已实现的挂载点支撑**，需要框架**新增**命令/发送器注册扩展点（这是一项尚未开工的设计工作，不是"收编既有代码"）。按现状收，只能收"日志路径回退"这一小修并如实描述。

#### ⑧ 通用工具（打包器 / web 壳 / CI）
- **文件行数**：`scripts/package_standalone.py` +154；`scripts/web_shell.py` +152；`.github/workflows/ci.yml` +17/−1
- **真 opt-in?** 脚本本身是（新增、不自动执行）；**CI 作业不是**（新增 job 无条件在每次 push/PR 执行）。
- **与 main 冲突**：
  - `ci.yml`：main 与 ancestor **逐字节相同**（`git log 4ae3eaa..main -- .github/workflows/ci.yml` 空）⇒ 其追加 job 的上下文吻合，可 patch。但作业内容 `python scripts/verify/verify_cloudsea.py` + `python scripts/package_cloudsea.py` 在 main 上必然失败（无 `content/cloudsea`）⇒ **CI 必红**。且它**没有增强主门禁**：main 的门禁是单一 job `quality-gate` → `.venv/bin/python scripts/run_all_tests.py`（ruff+mypy+pytest 全量+verify_m0~m12+coverage 三目录 ≥80%）；他们只是**并列**加了一个云海专用 job。
  - `web_shell.py`：依赖面在 main 上**成立**——`qbot_rpg_bridge.assemble.build_app_deps`（main L130，签名 `(*, pack_dir=None, db_path=None, settings=None)`）与 `qbot_rpg.assembly.runner.run_command`（main L778）；调用 `build_app_deps(pack_dir=self.pack_dir, db_path=self.db_path)` 吻合。缺省 `--pack content/cloudsea` 在 main 不存在（但命令行可覆盖）。它是**第二套 web UI**（stdlib `http.server` 单页壳），与我方 `qbot_rpg/web/` 重写版**并存**——**未触碰**我们的编辑器文件，但产品面重复。
  - `package_standalone.py`：stdlib-only 的"仓库打包器"骨架是通用的，但 `INCLUDE`/`README_DEPLOY`/验收断言硬编码 `content/cloudsea`、`docs/cloudsea/云海转化映射表.md`。
- **建议**：脚本 **改（去云海化后可收）**；`ci.yml` **拒（原样）**。
- **改写要点**：CI 作业加 `if:` 守卫或改为"存在即跑"的可选形态，绝不能让它成为无条件红；`web_shell.py` 缺省包改 `content/demo_full`（或强制 `--pack`），云海默认值随包；`package_standalone.py` 把 `INCLUDE`/README 抽出为参数或模板，框架仓只保留通用打包器。

---

### 3.5 他们改我们测试/门禁了吗？

**测试（`tests/**`，10 文件 / +1,045 / −2）**——**没有一个新增测试是"框架门禁加固"性质的**，全部是云海功能自测：

| 文件 | +/− | 读 `content/cloudsea`? | 无内容包时能否通过 | 备注 |
|:--|--:|:--|:--|:--|
| `tests/test_cloudsea_215.py` | +114 | 否 | ✅ 需分支代码（`cloudsea_sender`/`cloudsea_emoji`）+ 5 个模板键在 `DEFAULT_TEMPLATES` | 该断言在 main 形态下需改为查 `template_table.json` |
| `tests/test_cloudsea_237.py` | +60 | 否 | ✅ | 只测常量/迁移链/GM 表，**不验证 `players.cloudsea_state` 列真实存在**（R2 逃逸点） |
| `tests/test_cloudsea_phases214.py` | +125 | 否（数据内联 L9） | ✅ | 覆盖新旧阶段路径对照（有价值） |
| `tests/test_cloudsea_tactics.py` | +116 | 否 | ✅ | 依赖 `cloudsea_tactics` + 钩子面 |
| `tests/unit/test_cloudsea_axes_212.py` | +175 | **是**（`axes.json`，21 轴） | ❌ | 硬依赖包 |
| `tests/unit/test_cloudsea_commands_231.py` | +154 | 否（读源码） | ✅ | 含与框架 96 词面的冲突矩阵复扫 |
| `tests/unit/test_cloudsea_deep_235h.py` | +121 | **是**（`recipes.json`/`settings.json`） | ❌ | 硬依赖包 |
| `tests/unit/test_cloudsea_econ_235.py` | +82 | **是**（`recipes.json`/`economy.json`） | ❌ | 硬依赖包 |
| `tests/unit/test_cloudsea_err_233.py` | +94 | **是**（`templates.json` 21 条） | ❌ | 硬依赖包 |
| `tests/unit/test_resource_axis_models.py` | +4/−2 | 否 | ✅ | **唯一框架通用测试改动**：`test_def_fields_table_10_keys`→`13_keys`，断言集加 `tick_per_round/tick_floor/on_full` |

**门禁影响（实测）**：
- `pytest.ini`：`testpaths = tests` ⇒ **`tests/` 根目录下的 4 个 `test_cloudsea_*.py` 也会被收集**。所以那 5 个硬依赖包的测试在 main（无 `content/cloudsea`）上会**红**——**收编即破门禁**。
- `scripts/run_all_tests.py` 对 verify 脚本是**显式枚举**（`VERIFY_M0 = REPO / "verify" / "verify_m0.py"`，逐个常量），**不做 glob** ⇒ 新增的 `scripts/verify/verify_cloudsea.py` **不会**被自动纳入主门禁（这是好消息，但同时也说明它**没让门禁更严**）。
- `pyproject.toml` / `pytest.ini` / `requirements.txt`：**均未改动**（已核）。
- **静态安全扫描**（全部 317 个 `tests/**/*.py`）：`open(...,'w')` = 0；`write_text` 27 处**全部**指向 `tmp_path`/`tempfile`/`copytree` 的临时副本，**无一处写仓库 `content/`**；`requests`/`urllib`/`socket`/`httpx`/`aiohttp` = **0（无网络）**；13 处 `subprocess` 中 1 处是 monkeypatch 假替身、其余在仓内跑脚本。**10 个被改测试文件均未出现在任何写盘/子进程清单中。**
- **结论对"门禁只能更严"要求**：**未达成，也未破坏主门禁配置**——他们既没有给主质量门禁加断言，也不应把这 9 个云海测试并入门禁（会成为必红项）。若我们要收，必须把云海测试**连同内容包一起**放到内容包仓，或加 `pytest.importorskip` / `pytest.mark.skipif(not (ROOT/'content/cloudsea').exists())` 守卫。

**CI**：见 §3.4 ⑧。`.github/workflows/ci.yml` +17/−1 是**并列新增云海 job**，非主门禁加固，且在框架仓必红 → **拒收原样**。
**`.github` 之外无其他门禁文件改动**（`scripts/check_*`、`scripts/verify_m*.py` 均未动）。

---

### 3.6 不该进框架仓的东西

按"非框架物"口径逐项（来源：`git diff --name-status origin/main...origin/cloudsea-pack` 全 144 条）：

| # | 路径 | 状态 | +/− | 为什么不该进框架仓 |
|:--|:--|:--|:--|:--|
| 1 | `dist/cloudsea_content.zip` | A | 二进制（numstat `-`） | **构建产物**。更糟：同一 diff 还给 `.gitignore` 加了 `dist/`（见 #2）却把它 force-add 进来，自相矛盾 |
| 2 | `.gitignore` | M | +1/−0 | 唯一改动是加 `dist/`（本身合理），但与 #1 直接冲突；且它会让内容包产物的忽略规则进入框架仓 |
| 3 | `scripts/e2e_cloudsea_mvp_out.txt` | A | +251 | E2E 的**输出转储文本**，非代码；251 行云海日志 |
| 4 | `.workbuddy/memory/2026-09-10.md` | A | +13 | 智能体/编辑器记忆文件。**该文件自己 L13 就写着**「`.workbuddy/` … 未在 `.gitignore` 中 … 提交前注意排除」 |
| 5 | `content/cloudsea/generated/**`（8 件：`enemies_t1..t7.json` + `equipment_index_223.json`） | A | 约 +50,000（含在 content 175K 内） | **可再生的生成物**；源码 `scripts/parse_enemies.py`/`批次223_萃取.py` 在同一 diff 里。生成物应留在内容包仓、由构建重放 |
| 6 | `scripts/批次210_生成.py` / `批次221_技能.py` / `批次221_萃取.py` / `批次223_萃取.py` | A | +97/+166/+89/+130 | 中文批次脚本；含 **Windows 绝对路径 `D:\1V1TXTRPG\...`**，在框架仓不可能跑通 |
| 7 | `scripts/parse_*.py` / `assemble_enemies_226.py` / `verify_tide_pack.py` / `package_cloudsea.py` / `verify/verify_cloudsea.py` / `e2e_cloudsea_mvp.py` | A | 合计 ≈ +1,900 | 内容包构建管线（设计稿路径、潮位/灰岗常量、`content/cloudsea` 输出）——属内容包仓工具链 |
| 8 | `.workbuddy/**` 以外无编辑器缓存 | — | — | 已核：无 `.vscode`/`.idea`/`.DS_Store`/`__pycache__`/`*.pyc`/`.jspace` 进 diff（**这一项他们是干净的**） |
| 9 | `README.md`（+26，含云海章节，且**路径写错**：`python scripts/verify_cloudsea.py`，实际是 `scripts/verify/verify_cloudsea.py`）/ `CHANGELOG.md`（+3/−1，云海 G0–G7 条目） | M | +29/−1 | 内容属云海交付叙事；若要收只能收"框架侧变更"那一小段并修正路径 |
| 10 | `docs/cloudsea/**`（49 件 / +5,476，其中 `fragments/**` 47 件为流水线产物） | A | +5,476 | C 类内容/文档，随内容包仓（不在本审计范围，仅列总量） |
| 11 | `qbot_rpg/core/templates/cloudsea_err_tpl.py` | A | +72 | **落在我们刚收敛的 `templates/` 目录、且名字就是被删掉的 `*_tpl.py` 形态** → 会重新引入分区文件（见 §3.4 ⑤ 与 2.2） |

**框架仓可以留下的**（非"非框架物"，但需按 §2 的"改/拒"处理）：16 个 `M` 里的 14 个（`battle_tpl.py`、`migrations.py`、`deploy_smoke.py`、`ci.yml` 除外）+ `gear_skill_aggregator.py`。

---

## 4. 移植顺序建议（推荐批次）

### 批次 0 · 先做的判定（无代码）
1. **是否接受 CTB 与云海回合计数的语义鸿沟**。这是全部 A 类 ③ 的成败前提：`battle.py` +173 必须重写为 CTB 事件位点，工作量 ≈ 一个小专项，不是"收编 15 件"里的一行账。
2. **是否在框构仓内放行云海内容键**（5 个 `battle_*` 模板键 + 21 个 `err_*` + `cls`/`break_behavior`）。放行 = 框架表登记；不放行 = 内容包覆盖通道失效（`resolve_templates` 会丢未知键）。二选一必须先定。
3. **内容包状态是否允许写进核心 `players` 表**（R2）。建议不允许。

### 批次 1 · 立刻可收（5 件，零上下文调整，已逐行核对 main）
| 顺序 | 文件 | 方式 | 验证 |
|:--|:--|:--|:--|
| 1 | `qbot_rpg/core/monster_phases.py` | 直接 patch（尾部追加） | `inherit_boss_state` 单测 |
| 2 | `qbot_rpg/core/monster_intent.py` | 直接 patch | 既有 `test_monster_intent*` + 新扩展字段缺省不入 dict 的断言 |
| 3 | `qbot_rpg/core/condition_engine.py`（**改路径**，原 `engine/`） | 追加到 `core/` 尾部 | 两个纯函数单测（clamp 边界/连乘取整/非法输入） |
| 4 | `qbot_rpg/content/resource_axis_models.py` + `tests/unit/test_resource_axis_models.py` | 直接 patch（成对） | 13 键断言 |
| 5 | `qbot_rpg/content/validator.py`（a)(b)） | 直接 patch | 引用校验并集缓存一致性 + `cls`/`break_behavior` 放行 |

> (c) 链长 Y-8 告警：与 1-5 同批或拆批评审，取决于"warning 是否被门禁消费"（**待确认**，需跑 `scripts/verify/verify_m0.py` 确认；本审计未运行）。

### 批次 2 · 小改后收（3 件）
| 顺序 | 文件 | 改写要点 |
|:--|:--|:--|
| 6 | `qbot_rpg_bridge/__init__.py` + `qbot_rpg_bridge/plugin.py` | 直接 patch；提交信息如实写"调试日志跨平台回退"，**不要**写成"插件挂载点" |
| 7 | `qbot_rpg/content/skill_models.py` | 手工把缓存包装套到 main L407 的新版 `skills_fields()`（保留 F29/F30 字段） |

### 批次 3 · 需真正改写（6 件/项）
| 顺序 | 项 | 改写要点 |
|:--|:--|:--|
| 8 | 模板 5 新键 | 写进 `template_table.json`（不是 `battle_tpl.py`）；白名单自动派生；同步改 `test_cloudsea_215` 的断言口径 |
| 9 | `qbot_rpg/commands/sender.py` | 改走 `tpl_of`；保留 M8 剥斜杠；`err_condition`/`err_lack_resource` 补进 `template_table.json` |
| 10 | `qbot_rpg/core/resource_lifecycle.py` | tick 接线改挂 CTB `AFTER_ACTION`；负值钳单独提交+断言；`on_full_fired` 保留新键 |
| 11 | `qbot_rpg/core/gear_skill_aggregator.py` | 修 `import io`；`MUTATION_AFFINITY` 数据化；补读文件单测 |
| 12 | `qbot_rpg/core/monster_ai.py` | 拆两补丁（条件扩展重锚到 `enemy_axis` 之后并厘清分工；阶段机扩展）；计数器改为配置驱动 |
| 13 | `scripts/deploy_smoke.py` | 只收"去 `/root/` 绝对路径"，缺省仍 `content/demo_full` |

### 批次 4 · 拒收 / 另案
| 项 | 结论 |
|:--|:--|
| `qbot_rpg/core/battle.py` +173 | **拒原样**；按 CTB 事件位点另立专项重写（含 `TRIGGER_PROC_HOOKS`、周期器、积蓄衰减、`boss_state`）。`to_snapshot` 浅拷贝**单独另案**（须配隔离回归测试） |
| `qbot_rpg/storage/migrations.py` +23 | **拒原样**；内容包状态不入核心表（用 `persistent_state`/独立表）；若坚持加列必须先改 `schema.py` 并补双向测试 |
| `.github/workflows/ci.yml` +17 | **拒原样**；加 `if:` 守卫或改可选 job |
| `qbot_rpg/core/templates/battle_tpl.py` +15 | **拒原样**（文件不存在）；价值已由批次 3 第 8 项承接 |
| `scripts/package_standalone.py` / `web_shell.py` | **先拒，待去云海化**后再议（`web_shell` 另需产品口径裁定：与我方 web 编辑器并存或替代） |
| `dist/**`、`scripts/e2e_cloudsea_mvp_out.txt`、`.workbuddy/**`、`content/cloudsea/generated/**`、中文批次脚本、`D:\` 路径脚本 | **一律拒** |

### 随内容包仓自持
- 11 个 `cloudsea*` 文件（**唯一例外**：`cloudsea_emoji.py` 与 `cloudsea_ailment.py` 的通用核建议提通用化后入框架，见 §3.2）
- 16 个内容包工具脚本、9 个云海测试、`content/cloudsea/**`(36 件)、`docs/cloudsea/**`(49 件)
- 前提：**R5** —— 提案设想的"插件自装"挂载点当前**不存在**，框架需先**新增**命令/发送器注册扩展点（这是新设计工作，不是收编）

---

## 5. 待确认清单（禁止臆断，逐条给出理由）

| # | 待确认项 | 理由 / 需要谁拍板 |
|:--|:--|:--|
| 1 | `validator.py` (c) 链长 Y-8 告警是否会影响门禁 | 本审计只读、未运行 `verify_m0`/`run_all_tests`；若门禁按 warning 计数或"零告警"判绿，则 (c) 非零行为 |
| 2 | `resource_lifecycle` 负值钳 0 是否为有意修复 | 违反提案"全部 opt-in"自述；需作者确认是"缺陷修复"还是"顺手改动" |
| 3 | `migrations` v1→v2 的**真实意图**：是否已知"新库拿不到列" | 文档与代码矛盾（`ensure_meta` 行为 + `schema.py` 未改），且无测试覆盖；可能是作者的认知错误，需确认后决定"改"还是"整项拒" |
| 4 | `cloudsea_deep_commands` AD2 门控（`base_ref=AD-*` vs `lib["recipes"]` 只含 `R-*`） | 需读包内 `recipes.json` 全量与设计稿意图；本次仅静态发现，未判定是"缺陷"还是"AD2 本就该按 step 计" |
| 5 | `cloudsea_extra_commands` 的 `SIDE_ENUM` 权威值域 | 同文件三处自相矛盾（L42 vs L20/L251 vs L50 兜底模板），需内容侧拍板 |
| 6 | `cloudsea_sender.flush` 的窗到期由谁触发 | 无内置定时器；若宿主不周期调用 `flush()`，缓冲永不发送。需确认宿主契约 |
| 7 | `cloudsea_gm.CLOUDSEA_STATE_VERSION` 与 `migrations.DB_SCHEMA_VERSION` 双常量是否刻意 | 两处都为 2，漂移风险；需确认是否改为单一来源 |
| 8 | `web_shell.py` 与我方 `qbot_rpg/web/` 重写编辑器的产品关系 | 两套 UI 并存；是"取代 / 互补 / 拒收"需产品拍板 |
| 9 | `cloudsea_emoji` 的注册表作用域 | 当前是进程级全局（`_WHITELIST`），多内容包并发切换会有状态泄漏；改成按包作用域是否可接受，需设计确认 |
| 10 | 9 个云海测试"无内容包是否真红" | 静态依赖分析结论（5 必红 / 4 可过）；未实际运行 pytest（受只读约束），如需要可在容器内跑一次取证 |

---

## 6. 证据索引（关键 file:line）

| 结论 | 证据 |
|:--|:--|
| main `validator.py` 从未改动 | `git log --oneline 4ae3eaa..main -- qbot_rpg/content/validator.py` → 空 |
| validator 三处锚点吻合 | main `validator.py:379`（`_element_reg`）、`:438`（`_register_id`）、`:857-866`（part 键环）、`:1956-1966`（`skill_or_any`）、`:1969-1982`（`_check_chain_cycle`）、`:387`（`_warn` 签名） |
| `battle.py` CTB 重写 | main `battle.py:1-41` docstring"CTB（Charge Time Battle）…不存在「回合」这一时间单位"；`:151/196-197` `CTB_BOUNDARIES=("actor_ready","after_action")`；`to_snapshot` `:5055` `copy.deepcopy(self._snap)` + `schema_version=2` |
| 6 个 battle hunk 锚点全缺 | main `grep -c`：`"turn_start", "player"`=0、`tick_round_end`=0、`_dispatch_trigger_procs`=0、`_tick_field_periods`=0、`_tick_cloudsea_ailments`=0、`def boss_state`=0、`per_segment_effects`=0 |
| R2 新库缺列 | `migrations.py` `ensure_meta`：「全新库（players 无数据）→ 直接写 CURRENT 版本」（`version = 1 if has_players else DB_SCHEMA_VERSION`）；`DB_SCHEMA_VERSION=2`；`schema.py` `CREATE TABLE players`（L41-66）无 `cloudsea_state`；`git diff origin/main...origin/cloudsea-pack -- qbot_rpg/storage/schema.py` → 空 |
| R2 无消费方 | `git grep -n cloudsea_state origin/cloudsea-pack` → 仅 `cloudsea_gm.py` 文档 5 处 + `migrations.py` 4 处 |
| R2 测试盲区 | `tests/test_cloudsea_237.py:16-30` 只断言常量与链，无 DB 打开 |
| R3 非 opt-in | `resource_lifecycle.py` `_gain_scalar`/`_gain_pool` 内 `if nxt < 0: nxt = 0`（cs diff L268-279） |
| R4 io 未导入 | `gear_skill_aggregator.py:19-21` 仅 `__future__`+`typing`；`:38` `io.open(...)`；`:41` `except Exception: return {"techs": []}` |
| R5 挂载点不存在 | `git diff origin/main...origin/cloudsea-pack -- qbot_rpg_bridge/` 全部 hunk = `_bridge_debug_path()`/`_bridge_dbg()` 日志路径回退 |
| 提案漏报 ci/deploy_smoke | numstat：`.github/workflows/ci.yml` +17/−1、`scripts/deploy_smoke.py` +4/−2，均不在 15 件 |
| main 无 `content/cloudsea` | `ls content/` → demo_blank/demo_full/demo_lv15/demo_lv30/demo_lv45/test_demo/veinborn/zz_probe_packmeta |
| main 无 `battle_tpl.py` | `git cat-file -e main:qbot_rpg/core/templates/battle_tpl.py` → fatal |
| main 5 个战报键缺失 | 读 `template_table.json`：`battle_stage_shift_line`/`battle_windup_*`/`battle_merge_summary`/`battle_mention_line` 全 `None`；`err_bad_command` 存在 |
| 模板未知键会被丢弃 | `core/templates/__init__.py:86` `resolve_templates`（unknown → warning，`strict=True` 抛错）、`:113` `render_template`、`:129` `tpl_of` |
| sender M8 剥斜杠 | main `commands/sender.py:86-97`（`if frag.startswith("/"): frag = frag[1:]`）；cs 版无此两行 |
| errors.py 已预告 ctx 需求 | `commands/errors.py:26-28` 注释 |
| positions/air 早已存在 | ancestor 已有（`git diff 4ae3eaa...origin/cloudsea-pack -- content/field_meta.py content/skill_action_models.py content/skill_validator.py core/effects.py` → 空）；main 四文件均 EXISTS；main `validator.py:786`、`skill_action_models.py:107` |
| main 桥接依赖成立 | `qbot_rpg_bridge/assemble.py:130` `build_app_deps(*, pack_dir, db_path, settings)`；`qbot_rpg/assembly/runner.py:778` `run_command` |
| main 门禁形态 | `.github/workflows/ci.yml`：单 job `quality-gate` → `.venv/bin/python scripts/run_all_tests.py`；`scripts/run_all_tests.py:41-56` verify 脚本**显式枚举** |
| 测试收集范围 | `pytest.ini`：`testpaths = tests` |
| 唯一反向依赖 | `battle.py:3678-3684` 守卫式 `from qbot_rpg.core.cloudsea_ailment import tick_from_snapshot` |
| main 完全无 cloudsea | `git grep -i cloudsea origin/main` → 0 命中 |

---

*报告结束。本审计未修改任何被审代码，未 push，未动 main。唯一产出文件为本报告。*
