# 审查报告 · M3 地图里程碑 审查批次2（时间天气引擎）

> 方法：静态代码审查（只读 read/grep/glob，**未运行任何命令/脚本/测试**）。涉及运行行为或数值推断的结论一律标注【静态推导】。
> 范围（5 文件）：`engine/worldtime.py`、`engine/time_query.py`、`engine/weather_conditions.py`、`engine/weather_consumers.py`、`content/time_validator.py`
> 参照：`m3_shared_contract.md`（§5/§6）、`细化_2a4a/2a4b/2a4c`（含文档末尾 2026-08-26 裁决注记）、`审查参考/时间天气系统设计定稿.md`、以及交叉核对的 `content/weather_validator.py`、`content/validator.py`、`core/worldtime.py`、`data/world_time_persist.py`、`scripts/verify/verify_m3.py`。

## 结论总览

**P0 = 0 · P1 = 6 · P2 = 8**（无 P0；批次1 P0-1/P0-2 的 `_emit` 鸭子类型问题确认已修，见 §六）。

---

## 一、定稿落地核对（维度①）

| 契约点 | 实现 | 结论 |
|---|---|---|
| 三周期独立推进、共锚不共界 | `cycle_tick` 三 kind 各自整除，互不读写对方状态 | ✅ 一致 |
| 锚点 ANCHOR = 2000-01-01 00:00 UTC+8 | `_anchor_epoch()` = 946656000（手算：946684800 − 8×3600） | ✅ 正确 |
| season/period 取模 `% len(enum)`（2026-08-26 裁决） | `cycle_tick` 用 `len(self._seasons/_periods)`，weather 不取模 | ✅ 公式贯彻；见 P2-1 展示层残留 |
| 确定性抽签 seed = sha256(池键排序后 + str(tick)) | `map_weather` 与 2a4b §2.3 R11 / 定稿 L58 逐字一致；等概率 `int(seed,16)%len(pool)` | ✅ 一致 |
| 生效池 覆盖 else 默认（R18：空/全非法→默认池） | `map_pool` 正确回退；`_pool_keys` 兼容 str 与 {key,name,emoji} 双形态 | ✅ 引擎取值侧 |
| 广播顺序 季节→时段→天气，≤3 条，离线只播最新 | `_CHANGE_ORDER` + `[:3]` + 缓存比较 | ✅ 一致 |
| 消费方联动（weather_mods/combat/lore） | `weather_consumers`：rate_mult（0=不出）/ rarity_shift clamp 4 档 / combat 默认关 / lore LC-D fail-safe | ✅ 一致 |
| 存档 IF11（time_state 字段级迁移） | `data/world_time_persist.py` 承载（本批次外），字段级迁移/惰性增长/去重相等判定齐全 | ✅ 承载（未接线，见 P2-7） |
| **enabled=false → 三条件键失效（TC-22）** | `eval_condition` 不读 `is_enabled()` | ❌ **P1-5** |
| 枚举开放可配 → 校验器按「声明枚举集」比对（裁决#2/#3） | 校验器（M40/M41）仍按固定四季/五时段比对 | ❌ **P1-3** |

## 二、代码质量（维度②）

**确认通过项**：
- 锚点整除/`%` 语义：`diff//length` + Python 负数 `%` 与契约 `floor(...)%N` 逐字一致；`time_remaining` 边界（diff%length==0 → 完整周期）有文档说明。
- `%len(enum)` 越界：season/period 取 `len(self._seasons/_periods)`，自定义长度无越界；weather 不取模。【静态推导】全库未发现 `%4`/`%5` 字面残留（仅 `_SEASON_CN`/`_PERIOD_CN` 展示表为固定 4/5，见 P2-1）。
- 池覆盖/回退：`map_pool` 对覆盖池空数组/键全非法回退默认池（R18）；覆盖池只改取值不改节拍（R20）。
- 条件 fail-safe：`eval_condition` 未知 var/op/param/上下文无法取值一律 False 不抛错；`_season/_period/_weather_now` 均 try/except 兜底。
- `_emit` 鸭子类型：三份 `_emit` 均支持 `_err(...)` / `.errors` 列表 / Mapping["errors"]（批次1 P0 修复点）；weather_conditions 额外支持 `.error()` 方法 → 跨副本不一致，见 P2-4。

**问题项见 §四/§五**（P1-1~P1-6、P2-1~P2-8）。

## 三、幻觉 / 缺漏（维度③）

**docstring 引用行号真实性核对**（逐条比对 2a4a/2a4b/2a4c/2a1d/定稿）：

| 引用 | 核对 |
|---|---|
| `weather_conditions` "2a4c §2.1 L100（eq+param 判定）" | ✅ 2a4c L100 原文吻合 |
| `weather_conditions` "2a4c TC-18（简写与完整形等价）" | ✅ 存在 |
| `weather_conditions` "2a1d LC-D（求值失败默认不满足）" | ✅ 2a1d L194 吻合 |
| `weather_consumers` "2a1d GP-08~GP-11 / LC-01~LC-04" | ✅ 2a1d L49-70/L176-183 吻合；GP-11「普通/稀有/金色/✨觉醒」吻合 |
| `weather_consumers` "2a4b R25/R26" | ✅ 2a4b §4.3/§4.4 吻合 |
| `worldtime` "细化_2a4b §2.3 R11/R12/R14"、"定稿 L44（枚举可配）"、"裁决批次3 P1-1" | ✅ 全部吻合 |
| `time_validator` "细化_2a4b（§8 V1-V4）" | ❌ **2a4b 无 §8**（校验器实际在 §6.2 对齐表 + 2a4a §1.3）→ P2-6 |

**工程补白冒充/未兑现**：
- ❌ `time_query` 头注「确定性抽签（IF08）未落地前先取 pool_keys[0]，抽签落地后仅需替换一行」——批次2 IF08 已落地，**替换未执行** → P1-1。
- ⚠️ 大量模块标注「供主 agent 收口接入 check_pack」= 收口未完成，本批次函数全库运行时零调用（孤岛）→ P2-7；其中 `validate_weather_pool`、`validate_condition_keys` 仅测试调用 → P2-3/P2-5。
- ⚠️ 测试陈旧证据：`test_weather_consumers.py:191` 仍注「真实 WorldTime 尚无 weather_now」，与批次2 落地状态矛盾 → P2-8。

**枚举可配完整贯彻检查（%4/%5/固定枚举残留）**：
- ✅ `cycle_tick` 无固定取模。
- ❌ 展示层固定：`_SEASON_CN/_PERIOD_CN/_SEASON_EMOJI/_PERIOD_EMOJI`（4/5 索引表）→ P2-1。
- ❌ `time_query` 固定 `SEASONS/PERIODS`（`.index`/`next_key`/中文名）→ P1-2。
- ❌ 校验器固定 `SEASON_KEYS/PERIOD_KEYS`（M40 + weather_validator 镜像）→ P1-3。
- ⚠️ 2a1d V-4Z/LC-04 仍写「固定写死」（未随 2026-08-26 裁决更新）——文档未同步，非代码缺陷。

---

## 四、P1 问题清单（6 条）

### P1-1 `time_query` M36 /天气 未接入批次2 IF08，仍取 `pool[0]` 【静态推导】
- 位置：`engine/time_query.py:160`（`key = pool[0] if pool else None`）、`:144`（`map_id` 签名预留未用）、头注 `:20-21`。
- 现象：`weather_status` 返回「生效池首键」而非 IF08 确定性抽签的当前天气；与引擎实际值（`weather_now`/`map_weather`）在池长>1 时不一致。模块头注明确承诺「抽签落地后仅需替换一行」，但批次2 落地后未执行——**补白承诺未兑现**。指令层未接线，故障待接线后显现（/天气 输出错误天气）。
- 修复：`key = WorldTime(cfg).weather_now(map_id, now)`（或 `map_weather(map_id, cycle_tick("weather", now))`），删除补白占位。

### P1-2 `time_query` M36 季节/时段查询不兼容枚举可配，自定义枚举直接抛异常 【静态推导】
- 位置：`engine/time_query.py:97`（`SEASONS.index(key)`）、`:101`（`SEASON_NAMES[key]`）、`:103/:124`（`next_key` 用固定 `SEASONS/PERIODS`）。
- 现象：内容包声明 `season.enum=["s1","s2","s3"]` 后，`wt.season_now()` 返回 `"s2"`，`SEASONS.index("s2")` 抛 `ValueError`；即便不崩，`SEASON_NAMES[key]` 也 `KeyError`、`next_key` 按固定 4/5 循环错位。2026-08-26 拍板的枚举可配在查询层未贯彻——/时间 在自定义枚举下崩溃。
- 修复：改用 `wt._seasons/_periods` 求 idx/next_key；中文名对自定义键回退原键（同 `weather_name` 口径）。

### P1-3 校验器 V6 未按「声明枚举集」比对（2026-08-26 裁决未贯彻到校验链）
- 位置：`engine/weather_conditions.py:243-252`（`validate_condition_keys` 用固定 `SEASON_KEYS/PERIOD_KEYS`）；`content/weather_validator.py:184-193`（V6 镜像同病）。
- 现象：求值侧 `eval_condition` 接受 `ctx["season_keys"/"period_keys"]` 注入（可配，`:100-103`），但校验侧无 enum 参数、恒比对固定四季/五时段。自定义枚举内容包的合法条件（如 `param:"s2"`）在 load 阶段被 V6 误红拦，与裁决「校验器只比对『引用键 ∈ 声明枚举集』」相悖。
- 修复：`validate_condition_keys`/`weather_validator` 增加声明枚举集参数（读 `cfg.time_cycle.season.enum/period.enum`），比对目标改为声明集。

### P1-4 对象形态 default_pool 链断裂：`default_pool()` 产出垃圾键 + 接线 V4 误拦规范形态 + `validate_weather_pool` 零消费
- 位置：`engine/worldtime.py:181`（`[str(k) for k in p]` 对 `{key,name,emoji}` 对象 → `str(dict)` 垃圾键）；`engine/time_query.py:150-159`（回退池 + `pool_label` 比较用该垃圾键）；`content/time_validator.py:100-104`（接线 V4 仅字符串形态，对象条目误红拦「天气键要填字符串」）；`content/validator.py:506-510`（check_pack 未调 `validate_weather_pool`）。
- 现象：定稿 §1.4/2a4b R3 的规范 default_pool 是 `{key,name,emoji}` 对象形态。引擎 `map_pool` 走 `_default_pool_raw+_pool_keys` 正确处理（`worldtime.py:372-397`），但 `default_pool()` 方法（供 time_query）与接线校验器都只认字符串形态：① 对象形态下 `default_pool()` 返回 `["{'key': ...}"]` 垃圾键，/天气 回退池与 label 推导错误；② 规范对象形态配置被接线 V4 误红拦（「天气键要填字符串」）——**规范配置无法通过 check_pack（静态推导）**；③ 对象形态校验器 `validate_weather_pool`（含 V4「key+中文名齐全」R3）未接入 check_pack（全库仅测试调用）→ 定稿 V4「键+中文名齐全」实际未生效。
- 修复：`default_pool()` 改走 `_pool_keys`（提取 key）；接线 `validate_weather_pool` 或统一两形态校验口径。

### P1-5 条件键未受系统总开关 `enabled` 门控（TC-22 未实现）
- 位置：`engine/weather_conditions.py:77-115`（`eval_condition` 不读 `is_enabled()`）。
- 现象：定稿 §二 L101 / 2a4a TC-22 / 2a4c TC-22 要求 `time_cycle.enabled=false` 时 `[季节]/[时段]/[天气]` 条件键**全部失效**。引擎 `WorldTime.is_enabled()`（worldtime.py:149-152）存在且 `maybe_broadcast` 已用它短路，但条件求值与消费方（weather_consumers）未接入——enabled=false 下三键仍正常求值（静态推导）。
- 修复：收口接线时按 `is_enabled()` 短路三键求值，或 `eval_condition` 增加 enabled 检查（ctx 注入开关）。

### P1-6 V1b/V2b 单值枚举提示走红拦通道（违反裁决「档位数量/命名只提示不拦截」）
- 位置：`content/time_validator.py:52-55`（Y1）、`:73-76`（Y2）；`content/validator.py:333-334`（`_err` → errors）。
- 现象：单值枚举（恒定季节/时段，合法配置）的「只提示」语义经 `_emit` → `_err` 进入 `errors` 列表 → check_pack 按红拦处理，**合法配置被硬拦**（静态推导），与 2026-08-26 裁决#3 相悖。引擎副本 `worldtime.py` 无 V1b/V2b（见 P2-2），故此问题只在 content 副本。
- 修复：Y1/Y2 改走 `_warn`/`_note` 通道（`_emit` 需支持对应收集器形态）。

---

## 五、P2 问题清单（8 条）

### P2-1 展示层固定 4/5 索引表，自定义枚举错位 + 陈旧注释
- `engine/worldtime.py:103-107`（`_SEASON_CN/_PERIOD_CN/_SEASON_EMOJI/_PERIOD_EMOJI`）、`:332-348`（`_value_cn/_value_emoji` 按 `index % len(固定表)`）。自定义 5 季枚举第 5 季会被标成「春」（显示错位，可被 `Change['name'/'emoji']` 覆盖但默认路径错）；`:87-90` 注释仍写「4 值/5 值固定枚举」，与裁决矛盾。
- 修复：展示名改为按键映射（自定义键回退原键），注释同步裁决。

### P2-2 广播：天气默认文案恒空 + `map_weather_seen`（按图）去重未接入
- `engine/worldtime.py:333-339`（`_value_cn("weather",…)` 恒 `""`，new=weather_tick 整数）→ 默认模板 `{emoji} {name}` 下天气播报行为空文案（需调用方挂 name，补白承认但批次2 已可自解）；`:265-269`（去重只看 `seen` 的 `weather_tick` 全局索引，不认 定稿/IF11 的 `map_weather_seen` 各图已播 tick；`data/world_time_persist.py:132` 的 `mark_map_seen` 值也是 True 占位）→ 按图天气广播去重缺失。
- 修复：IF08 落地后引擎侧按 池+键 自解天气名；maybe_broadcast 接收 map 级 seen。

### P2-2b `validate_time_cycle` 双副本分歧（engine 副本缺 V1b/V2b）
- `engine/worldtime.py:455-526` vs `content/time_validator.py:46-76`。迁移说明（time_validator.py:5-7）称 engine 保留同名函数「世界侧可直接用」，但 engine 副本**没有** V1b/V2b 枚举校验——若世界侧走 engine 副本，自定义枚举完全不校验，`_enum_field` 静默回退默认（`:138-146`）。
- 修复：删除 engine 副本或补 V1b/V2b，单口收口。

### P2-3 `validate_condition_keys`（M40）零消费 + V6 双实现漂移
- `engine/weather_conditions.py:199-262` 全库仅测试调用；check_pack 的 V6 实际走 `content/weather_validator.py:160-198` 的平行实现 `_check_condition`（rule 名「对齐」但逻辑复制，含 P1-3 同病）。两份实现漂移风险。

### P2-4 `_emit` 鸭子类型三副本不一致（批次1 P0 修复未全量同步）
- `weather_conditions.py:176-196` 支持 `.error()` 方法通道；`worldtime.py:434-452`、`time_validator.py:169-188` 不支持。批次1 的 P0-1/P0-2 修复未同步到全部副本。

### P2-5 `core/worldtime.py` 占位类未清（误导性「M3 实装」docstring + 接线陷阱）
- `core/worldtime.py:1-79`：IF01-12 全部 `raise NotImplementedError`，docstring 自称「M3 实装」，与真实现 `engine/worldtime.py` 并存。当前无代码 import 它，但未来按 2a4c「engine/worldtime.py 扩展」误引即踩坑。建议删除或改为转发 engine 实现。

### P2-6 IF12 `recalc_on_config_change` 缺失 + W6 静态近似误报面
- 引擎无 IF12 方法（契约 §5.3 IF12 / 2a4c TC-12）；运行时效果由懒公式天然覆盖，但 API 缺失；黄提示由 `content/weather_validator.py:259-266` W6 静态近似——以「default_pool 键集 ≠ 内建」近似「配置变更」，键集相同但顺序/对象形态不同也会误报。

### P2-7 批次内运行时孤岛（收口未接线，铁律 5 接线防死）
- 全库非测试代码零调用：`engine/worldtime.py` 的 `WorldTime`（check_changes/maybe_broadcast/weather_now 等）、`time_query.*`、`weather_conditions.eval_condition`、`weather_consumers.*`。仅 `scripts/verify/verify_m3.py` 探针存在性 + 测试。`world/spawn.py:97-107` 已预留注入点、`world/game_world.py:96` 注明「收口时接 engine/worldtime」——属计划内延迟，但 P1-1/P1-2 的故障正是此类「收口未做、补白占位滞留」的产物，需在收口批次统一兑现。

### P2-8 docstring 章节引用不实 + 测试陈旧 + fail-safe 缺口
- ① `content/time_validator.py:3`「细化_2a4b（§8 V1-V4）」——2a4b 无 §8（weather_validator 头同病但已自注「按任务口径标注」）。② `test_weather_consumers.py:191` 注「真实 WorldTime 尚无 weather_now」与批次2 状态矛盾（静态推导：相关断言在真实 WorldTime 下行为已变化）。③ `engine/weather_consumers.py:113` `float(base_rate)` 未包 try，坏 base_rate 抛 ValueError，与函数 fail-safe 声称不符（其余字段均已 try）。

---

## 六、无问题维度确认（逐项确认通过）

1. **锚点手算**：ANCHOR=946656000 正确（2000-01-01 00:00 UTC+8 = 946684800−28800）。
2. **确定性抽签**：seed 公式与 2a4b §2.3 R11 / 定稿 L58 逐字一致；等概率无权重（R10）；同 tick 同池跨进程/重启一致（纯函数）。
3. **%len(enum) 越界**：cycle_tick 全部用 `len(self._seasons/_periods)`，无 `%4`/`%5` 字面残留，weather 不取模；负 diff 时 Python `%` 语义与契约逐字一致。
4. **weather_pool 覆盖/回退**：R18（缺省/空/全非法→默认池）与 R20（覆盖池只改取值不改节拍）语义正确，`_pool_keys` 双形态兼容。
5. **条件 fail-safe**：`eval_condition` 全形态 fail-safe；`lore_visible` LC-D（求值失败→不满足）对齐 2a1d L194。
6. **消费方联动**：`apply_weather_mods`（rate_mult 0=不出 / rarity_shift clamp 4 档，2a1d GP-11「普通/稀有/金色/✨觉醒」一致）、`combat_weather_mult`（默认关，respect formula）、`lore_visible`（优先级 ctx.weather_now > current_weather > worldtime 兜底，与文档一致）。
7. **存档语义（IF11）**：由 `data/world_time_persist.py` 承载（字段级迁移缺补默认/多忽略、map_weather_seen 惰性增长、cache_indexes_equal 去重判定），与定稿 §六 一致。
8. **广播语义**：默认关（`broadcast.enabled` 缺省 false）、顺序 季节→时段→天气、≤3 条、离线只播最新、跨群去重按已播索引——与 2a4a/2a4c 一致（map 级去重缺口见 P2-2）。
9. **`_emit` 鸭子类型（批次1 P0-1/P0-2）**：多收集器形态（`_err`/`.errors` 列表/Mapping）均已支持，确认已修；跨副本通道差异见 P2-4。

---

## 附：审查方法与边界

- 全程仅静态阅读；未运行 verify_m3 / pytest / 任何 python 脚本（用户禁令）。「会抛 ValueError」「check_pack 拦截」「跨进程一致」等均为对源码语义的静态推导，标注如上。
- 交叉文件（weather_validator / validator / core.worldtime / world_time_persist / verify_m3 / spawn / game_world）仅作接线与契约佐证，不在本批次 5 文件修复范围内。
- 未核查：批次1 报告原文（P0-1/P0-2 具体内容仅按任务注记与当前代码形态确认「已修」）；G3/M2 门禁基线。
