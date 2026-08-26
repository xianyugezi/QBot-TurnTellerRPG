# 静态审查报告 · M3 地图里程碑 · 审查批次 1（地图数据层 + 通道行走）

- 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试；所有运行行为结论均标注「静态推导」）。
- 审查文件（5 组）：
  1. `qbot_rpg/content/map_models.py`（MapDef/SpawnDef/ExitDef + validate_maps）
  2. `qbot_rpg/content/map_graph.py`（can_move/bidirectional_consistent/path_exists）
  3. `qbot_rpg/content/dungeon_models.py`（DungeonDef + validate_dungeons + zone_change）
  4. `qbot_rpg/world/movement.py`（resolve_move/move_to_map/enter_context_route）
  5. `qbot_rpg/content/field_meta.py` + `validator.py`（M3 新增：dungeon 注册 / maps·dungeon 专项分派 / time_validator 接入）
- 参考依据：`docs/m3_shared_contract.md`（§2/§4/§3.1/§5.2/§6.2）、`docs/细化/细化_2a1a/2a1b/2a1c/2a2/2a3/2a1d`（定点核对）。

**结论汇总：P0 × 2 · P1 × 3 · P2 × 16（共 21 项）**

---

## P0（阻断级：生产路径功能缺失/崩溃）

### P0-1 · validate_maps 收口接线断裂 → M3 maps 深校验在生产路径静默空转
- **位置**：`qbot_rpg/content/validator.py:472-474`（`validate_maps(self._modules, self)`）；`qbot_rpg/content/map_models.py:214-224`（`_emit` 适配）、`453-506`（validate_maps 全部报告出口）。
- **根因（静态推导）**：`_emit` 的鸭子适配只查 `report.<method>` 与 `report._<method>`，即 `error`/`_error`、`warning`/`_warning`；而 `validator._Checker`（validator.py:315-341）**只有 `_err`/`_warn`/`_note`，无 `error`/`_error`**。`validate_maps(modules, _Checker)` 的每一次 `_emit(report, "error"|"warning", ...)` 都找不到 callable，**全部静默丢弃**。
- **影响**：契约 §2.2 ①-④（to 存在 / mode 枚举 / hidden 必带 condition / 双向不对称 Y-8）与 2a1b R24-R26（enemy 引用 / seasons·periods 枚举 / count·respawn·weather_weights 数值）在生产 `check_pack` 路径**零生效**；且 `field_meta.maps_fields`（field_meta.py:363-375）只注册了 M0/M1 旧字段（enemy_pool/battle/min/max/…），M3 8 字段全部按「未知字段默认放行 §2.3」跳过 → **M3 maps schema 在生产中实际零校验**（合法包照常通过，非法包静默放行）。
- **测试掩盖**：`tests/unit/test_maps_schema.py:110-118` 的「直传真实 `_Checker` 收口兼容测试」只在**合法包**上断言零红拦 → 有 bug 也必然通过（空转恰好满足断言）；坏包用例（如 L395）全走 `_Report`（公开 `error`/`warning` 方法，L40-52），与生产路径不一致。
- **docstring 幻觉**：map_models.py:214-218 声称 `_emit`「其次 validator._Checker 的 _<method>（_err/_warn）」——实现找的是 `_error/_warning`，与 `_err/_warn` 名不符，**声称已适配但实际不适配**（维度③）。
- **修复**：`_emit` 增加显式映射 `{"error":"_err","warning":"_warn","note":"_note"}`（或给 `_Checker` 补公开 `error/warning/note` 委托）；补一条「坏包直传真实 `_Checker` 应产生 errors」的收口测试（现测试无法暴露该缺陷）。

### P0-2 · time_validator._emit 未定义 → M3 时间校验在报错路径 NameError 崩溃
- **位置**：`qbot_rpg/content/time_validator.py`（全文 142 行，`_emit` 被调用 16 处——L32/41/50/59/67/71/78/82/115/119/126/131/134/141，**从未定义/导入**；同逻辑 `_emit` 存在于 `engine/worldtime.py:419`，content 迁移时丢失）。
- **根因（静态推导）**：`validate_time_cycle`/`validate_weather_pool` 内 `_emit(...)` 在模块全局找不到名称 → 任何校验命中即抛 `NameError: name '_emit' is not defined`。
- **影响**：`validator.py:504-507` 在 settings 分支直接调用 `validate_time_cycle(data, self)`（无 try/except）。配置**非法**时（如 `season_days=0`、`period_minutes=10`）→ 未捕获 NameError → `check_pack` **崩溃**而非产出 V1-V4 校验错误；配置合法时静默通过。**V1-V4 校验实际不可用**（合法不报、非法崩）。
- **修复**：从 `engine/worldtime.py:419` 移植 `_emit`（或改直接调用 `report._err`），并补一条非法 time_cycle 经 `check_pack` 的回归测试。

---

## P1（高：校验规则孤儿化 / 输入可触发崩溃）

### P1-1 · dungeon_entrances↔dungeon 双向引用校验与 2a1c R2 防嵌套：双向标注「M16 处理」却无落地
- **位置**：`map_models.py:23`（工程补白 2：dungeon 引用归 M16）、`map_models.py:499-503`（仅「非 list 即 R-1」结构提示）；`dungeon_models.py:312-326`（只校验 dungeon.json `maps` → maps.json，**从不反向校验 maps.json `dungeon_entrances`**）。
- **内容**：
  a) 2a1c R1 + 契约 §4.1：`dungeon_entrances[].dungeon` 引用存在（红拦）——map_models 标注「依赖 dungeon.json（M16）」，但 M16（validate_dungeons）未实现该**反向**校验 → 两端都不校验；
  b) 2a1c R2：副本内部地图禁止再挂 `dungeon_entrances`（红拦工程护栏，2a1c §1.1）——全仓库无实现；
  c) `dungeon_entrances` 条目结构（`{dungeon: string, name?: string}`）零校验：`dungeon` 缺失/非字符串/空串均静默放行。
- **修复**：在 `validate_maps`（或 validate_dungeons）补交叉校验：① 每条 entrance 的 `dungeon` ∈ 已注册 dungeon id（红拦）；② 本图 id ∉ 任何 dungeon.maps（R2 红拦）；③ entrance 条目结构（dungeon 必填 string、name 可选 string）。至少应在两文件互相指认排期，避免孤儿。

### P1-2 · 2a1b R25 weather_weights 键空间硬拦为孤儿规则（双端声明不校验）
- **位置**：`map_models.py:21-22`（工程补白 1：key 校验归 M41）+ `map_models.py:397`（注释）；`weather_validator.py:30-33`（工程补白 1：V6 范围**明确排除**「怪物 spawn weather_weights 键」，由「后续收口接线补充」）。
- **影响**：R25 半条硬拦（`weather_weights` key ∈ 注册天气集）在全仓库**无人校验**；且因 P0-1，其值非负校验（R26）在生产路径同样失效。配置「未注册天气键」可静默通过。
- **修复**：收口到 weather_validator V6（补 spawn weather_weights 键扫描）或 map_models 接入注册天气集；两处工程补白至少互相指认排期，避免各自为「对方负责」。

### P1-3 · enter_context_route 数字序号 `isdigit()`/`int()` 陷阱 → 用户输入触发未捕获 ValueError（静态推导）
- **位置**：`movement.py:372-379`：`if arg_s.isdigit(): idx = int(arg_s)`。
- **说明**：Python 语义下 `str.isdigit()` 对 `¹`/`²`/`³`/`①` 等 Unicode 数字返回 `True`，而 `int()` 对它们抛 `ValueError`（静态推导，属 Python 文档性行为）。`/进入 ²`、`/进入 ①` → 未捕获异常崩溃（非数据损坏，但指令路由是用户直触面）。
- **修复**：`try: idx = int(arg_s) except ValueError: return {"ok": False, "reason": ...}`；或将判定收紧为 `arg_s.isascii() and arg_s.isdigit()`。

---

## P2（建议：16 项）

| # | 位置 | 问题 | 建议 |
|---|---|---|---|
| P2-1 | map_models.py:4-5；test_maps_schema.py:3 | docstring 将「节点级 8 字段 / dungeon_entrances」归因细化_2a1a；**2a1a 实为 7 字段**（第 8 字段 dungeon_entrances 出自 2a1c §1.2，spawn 为 `{enemy,rank,chance}` 旧三字段形）。8 字段权威是 m3_shared_contract §2.1。归因不实（维度③） | docstring 精确化为「契约 §2.1（8 字段，2a1a 7 字段 + 2a1c 扩展）」 |
| P2-2 | map_models.py:372-376 vs :85 | validate_maps 与自身 SpawnDef 文档矛盾：`active_time: {}`（空=全天，2a1b 字段表「否（空=全天）」）被 from/to 双 R-1 红拦 | 空 dict 视为全天放行，或修正 docstring 口径 |
| P2-3 | map_graph.py:169-204 | `can_move` 对 `to` 悬空（None/空）的 bidirectional/one_way 边返回 `ok=True, to=None`，违反对契约 §2.4 的 MoveResult.to 语义（下游 path_exists 有 `nxt is None` 防御、resolve_move 有 `not ex.to` 前置守卫，故当前无崩溃） | `to is None` 时返回 `_blocked(...)`（与 dead-end 同口径） |
| P2-4 | map_graph.py:230-272 vs map_models.py:404-450 | 契约签名接口 `bidirectional_consistent` 生产零消费（仅测试引用）；validator 用私有孪生 `_check_bidirectional_symmetry`。双实现当前口径一致（含 hidden 回边 Y-8），但自环处理已分叉（map_graph 跳、map_models 不跳），有漂移风险（契约铁律 5 接线防死） | 收口 validator 改调 `bidirectional_consistent`，或删其一 |
| P2-5 | dungeon_models.py:458-470 | `validate_enemy_zone_change` **零消费**；docstring:464「validate_dungeons 内亦调用」不实——validate_dungeons:496 直接调 `_check_zone_change`（维度③ 声明不实 + 零消费函数） | 删除该导出，或改口径为「供未来独立接线」 |
| P2-6 | movement.py:58/283 vs map_graph.py:40/163 | 死路文案跨层不一致：resolve_move 报「此方向没有通道」，can_move 同场景报「此路不通」；map_graph docstring 声称「契约 §2.4 同文案」，实际两处不同 | 统一文案（对齐 2a1c R18 或契约 §2.4 择一） |
| P2-7 | movement.py:162-173 | `_hidden_ok` 以「单参调用抛 TypeError」推断形参不匹配并回退双参：callable 函数体内部抛 TypeError 会被误判重试（可能半执行/结果漂移）；fail-safe 方向仍安全 | 用 `inspect.signature` 判定形参个数，或以 `(cond, ctx)` 双参为唯一契约 |
| P2-8 | movement.py:218-221 | `_can_move` 广捕 `Exception` 兜底：map_graph.can_move 运行时异常也静默降级 `_contract_can_move`，掩盖实现缺陷并产生行为分歧 | 仅捕 ImportError；其余异常上抛 |
| P2-9 | movement.py:385-411 | 名称匹配仅两级（入口名→副本名→id），2a1c R17 为三级（缺「地图名」级）且失败不给候选列表（TC-15）；docstring 声称「逐级」 | 补地图名级或把工程补白写进 docstring |
| P2-10 | movement.py:367-379 | ① 序号语义仅「入口列表」（2a1c R16/R20 世界图=地图列表序号，无实现）；② 大写英文方向「UP」经 resolve_move 可识别（lowercase），经 enter_context_route 落名称匹配 → 大小写不一致 | 统一大小写归一；序号语义按上下文路由 |
| P2-11 | movement.py:316 | `move_to_map(map_id=None)` → `target=""` 落库并写 time_state（fail-open）；resolve_move 有守卫，但函数自身对坏输入不防御 | `map_id` 非法时返回失败不改位置 |
| P2-12 | field_meta.py:420 vs :36-46 | `dungeon` 用 `namespace="dungeon_lib"` 但 NAMESPACES 未登记（M0 审查已记录 formula_lib/cond_lib 同型缺项；NAMESPACES 本身生产零消费） | 补登记或统一「ModuleMeta.namespace 为唯一来源」 |
| P2-13 | dungeon_models.py:84-86 | `DungeonDef.entry_limit` 访问器返回 `Optional[float]`（`_num`），schema 为 int（校验器 int 口径） | 访问器用 int 专用 helper |
| P2-14 | movement.py:244 | `_contract_can_move` 未知 mode 回退 `bidirectional`（fail-open）；仅兜底路径可达且 validate_maps 红拦非法 mode | 未知 mode 改拦截（与 map_graph.can_move:206-207 一致） |
| P2-15 | movement.py:385 | R17 地图名级、R20 世界图序号级未实现，但 docstring 声称覆盖 R14-R18/R20 —— 范围声明略宽 | 补白与声明对齐 |
| P2-16 | movement.py:296-298 | resolve_move 成功返回丢弃 can_move 的 `lore`，改由 `move_to_map._exit_lore` 在旧图所有出口中按 to 重找：多出口同目标不同 lore 时可能取错方向文案 | 直接透传 can_move 的 lore |

---

## 无问题维度确认

- **① 定稿落地（主体）**：maps 8 字段访问器齐全（map_models.py:147-190）；exits 三态 + condition 归属（ExitDef 52-72，hidden 必带 condition、双向/单向配 condition 仅 Y-8）与契约 §2.2 ①-④ 对应；spawn 七字段 + 缺省（SpawnDef 76-109）与契约 §2.3 / 2a1b R24-R26 对应；dungeon_entrances 挂接访问器（188-190）与 2a1c §1.2 结构一致；dungeon 11 字段（DungeonDef 73-116）+ zone_change 4 字段（_check_zone_change）与契约 §4.1/§3.1 对应；`can_move/bidirectional_consistent/path_exists` 签名与契约 §2.4 一致。
- **② 代码质量（达标项）**：双向不对称判定两实现（map_models Y-8 与 map_graph）对 hidden 回边、悬空 to 跳过的口径一致；hidden 条件求值 fail-safe 达标（map_graph._hidden_satisfied 108-122 / movement._hidden_ok 149-173：未注入/异常/条件缺失一律 False，2a1d LC-D 依据真实）；`dungeon.maps`→maps、`boss`→enemies、`safe_zone`∈dungeon.maps、`gate_guard`/`spawn.enemy`→enemies 引用存在性逻辑正确（除 P0-1 使 maps 侧失效、P1-1 反向缺位）；MoveResult 键集与契约对齐（ok/to/mode/hidden_ok/blocked_reason? + 显式工程补白字段 to_name/lore）。
- **③ 幻觉/缺漏（达标项）**：工程补白均**显式标注、未冒充定稿**（spawn count 缺省 1、max_alive/spawn_weight、zone_change timing 枚举、map_graph Warning dict 形状、R22 双钩子/入场校验/M4 存储的批次接线、DEF_CLASSES["map"] 空壳现状——models.py:545 属实）；zone_change timing 补白「对齐 TRIGGER_TYPES」属实（validator.py:209-213 含 after_action/phase_changed）；引用行号核对：2a1b R1-R30（R24/R25/R26 属实）、2a1c R1/R2/R13-R22 + TC-05/14/23/24/25、2a3 R1-R7/R11/R15、2a1d §2.4 first_clear + LC-D、2a2 §7.1 + R5 **全部真实存在**。

---

## 引用真实性核对记录（维度③）

| 引用 | 核查结果 |
|---|---|
| map_models「2a1b R1-R13/R14-R26」 | ✅ 真实（2a1b 实际 R1-R32） |
| map_models「2a1a 节点级 8 字段」 | ❌ 不实（2a1a 为 7 字段；8 字段=契约 §2.1，dungeon_entrances=2a1c §1.2） |
| map_graph「2a1a §2 exits 6 字段」「2a1b R2-R7」 | ✅ 真实 |
| movement「2a1c R14-R18/R20/R22」「2a1b R11-R13」「2a1d LC-D」 | ✅ 真实 |
| dungeon_models「2a3 R1-R12/R15」「2a1d §2.4」「2a2 §7.1/R5」「契约 §4.1 11 字段」 | ✅ 真实 |
| dungeon_models「validate_enemy_zone_change：validate_dungeons 内亦调用」 | ❌ 不实（validate_dungeons 直接调 _check_zone_change） |

*注：本报告所有运行行为结论（_emit 静默丢弃、NameError、isdigit/int 崩溃、_hidden_ok TypeError 重试）均为静态推导，未执行任何代码。*
