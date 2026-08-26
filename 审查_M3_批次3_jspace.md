# 审查报告 · M3 地图里程碑 · 审查批次 3（副本两型 + 换区追击）

- 审查方式：**纯静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试；一切运行行为结论均标「静态推导」）
- 审查范围（5 文件）：
  1. `qbot_rpg/core/dungeon.py`（DungeonStateMachine S0–S7 + DungeonSession + explore_run）
  2. `qbot_rpg/core/dungeon_boss.py`（BossFlow：入场守门怪 / phase_for 三阶段 / should_zone_change / on_chase_continue）
  3. `qbot_rpg/core/dungeon_subquest.py`（子任务五形式）
  4. `qbot_rpg/world/chase.py`（chase_trigger / pick_chase_target / begin_chase / pursue）
  5. `qbot_rpg/world/chase_resume.py`（prepare_resume_battle PV 缺失量 / exit_dungeon_reset）
- 参考依据：`docs/m3_shared_contract.md`（§3/§4）、`docs/细化/细化_2a2_换区追击流程.md`（含文末 2026-08-26 裁决注记）、`docs/细化/细化_2a3_副本两型流程.md`、`docs/审查参考/副本系统设计定稿.md`、`docs/审查参考/怪物模块设计定稿.md`
- 交叉核对方：`core/monster_phases.py`、`content/dungeon_models.py`、`content/map_models.py`、`content/map_graph.py`、`world/movement.py`、`world/dungeon_persist.py`、`world/snapshot_resume.py`、`world/rest.py`、`tests/fixtures/packs/legal/*`、`tests/unit/test_{dungeon_flow,dungeon_boss,dungeon_subquest,chase,chase_resume,rest,snapshot_resume,dungeon_persist}.py`、`scripts/e2e_m3_smoke.py`、`scripts/verify/verify_m3.py`

---

## 0. 门控档位与结论摘要

- 门控档位：**full 档**（j-space 唤醒→门控→接缝审计→ship；无控制器，台账按技能「hand-executable」走会话内 ledger）。
- 结论：**P0 = 0 ｜ P1 = 1 ｜ P2 = 7 ｜ P3 = 3**
- 定稿落地面（状态集/迁移表/入场限制/BOSS 三阶段端点/残血换区/PV 缺失量公式本身/离开重置/子任务五形式）：**全部落地，主链路正确**；问题集中在「追击错失窗口计数语义」「PV 恢复时机与落库口径」「会话形态/配置形态/接口签名的跨模块漂移」「docstring 陈旧」。

---

## 1. 维度① 定稿落地核对

| 定稿项 | 结论 | 证据 |
|---|---|---|
| 状态集 S0–S7 | ✅ 完整 | dungeon.py L65-72，与契约 §4.2 一一对应 |
| 迁移表 M1–M15 | ✅ 完整 | dungeon.py L87-100；walk/elite/elite_done/chase/caught/re_chase/kill/death/recover/leave/clear/rest 全映射；探索版补白路径（S0→S7、S1→S5、S1/S2→S6）显式标注不冒充定稿 |
| 迁移合法性（事件×状态） | ✅ | 未知事件拒绝（L410-412）；BOSS 事件探索版拒绝（L414-417）；clear BOSS 版拒绝（L418-421）；非法前置状态拒绝（L423-426） |
| 入场限制（entry_item/entry_limit） | ✅ | dungeon.py `_validate_entry` L305-340：校验先于消耗（不足/超限不扣道具不耗次数）；0=不限；探索版 entry_item:null 宽松；与 legal pack（boss 版 potion/3）对齐 |
| 入场落位安全区/外部锚点 | ✅ | L374-385：safe_zone 缺省 maps[0]，external_anchor 记录，content_pack 字段落位 |
| BOSS 三阶段 phase_for | ✅ | dungeon_boss.py L313-326 夹取 [0,100] → PhaseTable.resolve_phase；默认 (100,60,30) 边界归下阶段（60→2、30→3），monster_phases L92-107 与测试 L185-208、e2e L437-443 一致 |
| 残血换区 should_zone_change | ✅ | L330-372：enabled=False/无 cfg/无 targets→永不换区（R4）；hp=0 击杀优先（R3）；hp% > threshold×100 不触发（R1/R2）；30% 整 ≤ 触发；timing=phase_changed 需 phase_changed 标志；与 chase.py 本地实现 `_contract_should_zone_change`（L143-173）同口径 |
| 续战 PV 缺失量公式 | ✅（公式正确，docstring 陈旧见 P2-1） | `_pv_half_value`（dungeon_boss L119-140 / chase_resume L110-132）：`current + floor((max−current)×pv_recover)`，0→保持、1→补满、破防（current=0）数值与旧满值口径一致；测试（250→275、破防 300→150、201→100）对齐 2026-08-26 裁决 |
| 开场技标记 | ✅（仅标记，接线补白） | on_chase_continue L416 `opening_skill: True`；实际触发委托战斗侧（细化_1f battle_start），补白 3 显式标注 |
| 离开重置 | ✅ | exit_dungeon_reset（chase_resume L295-359）：战斗中拒绝（快照续玩）、清 BOSS/残血/子任务/休息/换区上下文、回外部锚点；DungeonStateMachine leave（dungeon L431-434）全清；explore_run leave（L664-672）与 S7 一致 |
| 子任务五形式 | ✅ | dungeon_subquest.py L56-62 五键（reach_zone/defeat/collect/interact/condition）对应契约 §4.3 中文五形式；事件驱动判定 + 隐式激活 + 防重复领奖 + 不阻塞 BOSS（可选性） |
| 防串档字段 | ✅（字段落位；校验在持久化层） | DungeonSession L125-126 存 content_pack_id/version；enter L383-384 落位；load_dungeon_session（dungeon_persist L654-659）做 id 校验 |

**确认无问题**：状态迁移合法性、入场校验语义、三阶段阈值端点归属（60/30 归下阶段）、残血换区判定链、PV 缺失量公式本体、离开重置双通道（dataclass/dict）、子任务五形式事件键与可选性。

---

## 2. 维度② 代码质量（bug / 边界 / 跨模块契约）

### P1-1 · pursue 错失窗口把「合法推进」计为「走错」，深图正确追击必触发 BOSS 重置 【world/chase.py L441-446】

- 位置：`pursue` 未到达目标图分支 `miss_count += 1`（L442-443）；`missed = over_limit or back_to_start`（L445-446）；docstring L376-378 自称「走错一步」。
- 问题（静态推导）：代码对「本次移动未命中 target_map」一律 +1 miss。若起始区→目标区的正确可达路径步数 ≥ miss_limit+1（默认 3 → 路径 ≥4 步），玩家沿唯一正确路径推进，第 3 步（尚未到达目标）即触发 `boss_reset`（BOSS 回满/离开副本）。即「追到续战」（M6/R19）在非浅层地图上不可达。`走错`语义（2a2 R17「绕路/错过窗口」）被实现为「没到目标就算错」，与 2a1b R11/补白 5「死路不计错」也只覆盖移动失败，不覆盖合法中间步。
- 触发条件示例：`start=A → B → C → D → target`（4 步）：A→B(miss1) B→C(miss2) C→D(miss3→重置)，第 4 步 D→target 永远到不了。
- 修复建议：① miss 计数应只针对「偏离可达目标」的移动——移动后 `target_reachable(new_map, target)` 为 False 时计错；② 或引入「首次到达的中间图不计错，重复/回退才计」（visited 集合 + 回退检测）；③ 或 `miss_limit` 按 `path_exists` 距离自适应（≥ 最短路步数）。建议 ①+③ 组合，保持「地图知识=追击资源」的护栏本意。

### P2-1 · 「满值口径」docstring 陈旧，与代码（缺失量口径）及 2026-08-26 裁决矛盾 【core/dungeon_boss.py L29-32、L386-388；world/chase_resume.py L4-10、L27-30、L152、L161】

- 位置与旧口径表述：
  - dungeon_boss.py L29-32（补白 4）：「pv_half_value = floor(pv_max × pv_recover)（2a2 §2.1 满值口径…）」；L386-388（on_chase_continue docstring）同。
  - chase_resume.py L10（docstring 引规划 M14「PV=floor(PV×pv_recover)」）、L27-30（补白 2「公式 floor(pv_max × pv_recover)」）、L152、L161（返回字段说明「满值口径向下取整」）。
- 问题：代码两处 `_pv_half_value` 均已实现缺失量口径（与 2a2 文末 2026-08-26 裁决一致），但上述 docstring/补白仍引用被裁决取代的满值口径——属于「docstring 引用真实性」问题（幻觉/缺漏类别）：读者按 docstring 会得出与实现不同的期望值（如未破防 current=250 时实现给 275，docstring 描述会让人以为给 150）。
- 连带命名漂移：标记键 `pv_half` / `pv_half_value` 语义已变为「恢复后值」（缺失量口径），不再是「满值的一半」（未破防 250/300 时 275 ≠ 150）。生产端与消费端取值一致（不产生运行错误），但名称会误导后续战斗层接线（如按「半值」再乘一次）。
- 修复建议：统一改写上述 docstring 为缺失量公式并注明裁决日期；命名建议迁移为 `pv_restored` / `pv_restored_value`（或保留旧键加 docstring 强注「缺失量口径」并做收口别名）。

### P2-2 · PV 恢复时机（R10/TC-09）未落地：换区瞬间未恢复、未落库 【core/dungeon_boss.py L376-432；world/chase.py L227-255、L304-328、L426-439】

- 依据：2a2 §2.2（R10）「恢复时机=换区事件结算瞬间…不等玩家追到再恢复…恢复后数值随换区状态落库」；TC-09「换区瞬间即查 BOSS 状态 → PV 已达 150」。
- 现状（静态推导）：换区装配（chase_trigger / begin_chase）**不写 boss_state.pv**；PV 恢复值仅在「追到」分支（pursue L426-439 → on_chase_continue L376-432）现场计算并置于 `continue_data`（内存态）。全程无任何路径在换区瞬间把恢复后 PV 写入 boss_state / 快照。
- 后果：① TC-09 观察点失败（换区后玩家未动，BOSS 状态 PV 仍为换区前值）；② 追击中快照中断→恢复路径：持久化的 chase_ctx（zone_chase_context）不含 continue_data（catch 未发生），prepare_resume_battle 回落 enemy_state（重载后通常无 pv/pv_max）→ `pv_half_value=0`（TC-20「仍从 PV150 续战」无法满足，静态推导）。
- 修复建议：在换区结算点（chase_trigger/begin_chase 之后、进入追击态前）调用缺失量公式把 `boss_state.pv` 就地更新为恢复后值并落库；on_chase_continue 改为仅透传该落库值（避免双处计算漂移）。

### P2-3 · 会话形态漂移：frozen DungeonSession 与 chase 管线 plain-dict 不互操作 【core/dungeon.py L109-126；world/chase.py L320-322、L396-397；core/dungeon_boss.py L83-92、L189-190】

- DungeonSession 为 frozen dataclass 且无 chasing/chase_target 字段；begin_chase 仅 `isinstance(session, dict)` 时落盘（L320-322），传 DungeonSession 时**静默不落盘**；pursue 对非 dict chase_ctx 仅本地计数（L396-397）。
- BossFlow._session_get 经 `_cfg_get`（L83-92）读 dataclass：无 `.get` → 恒返回默认值——gate_guards_defeated 恒 False（守门怪永远拦截）、boss_state 读不到（on_chase_continue 拿不到当前 PV → 回落「近似满值」→ 恢复值偏大）。BossFlow docstring（L166）宣称接受 DungeonSession，实际静默降级。
- 现状缓解：dungeon_boss 补白 1（L18-20）自认「本路以扁平 dict 键承载，收口时对齐路N」；e2e/smoke 均用 dict 形态，测试全绿路径不受影响。但这是「声明覆盖但行为缺失」的真实收口风险。
- 修复建议：为 DungeonSession 增补 chasing/chase_target/zone_chase_context 字段（或提供 with_chase 方法），并给 BossFlow._session_get 增加 dataclass 字段直读（getattr），补一个「DungeonSession 形态 × BossFlow/begin_chase」的收口测试。

### P2-4 · 契约 §3.2 接口签名漂移：should_zone_change / resume_chase_battle 未按契约落位 【m3 §3.2 L106-111 vs world/chase.py L56-66；world/chase_resume.py L56-63】

- m3 §3.2 明确 `world/chase.py` 应导出 `should_zone_change(enemy_state, cfg) -> bool` 与 `resume_chase_battle(enemy_state) -> dict`（残血保持+PV 半恢复+开场技标记）。
- 实现：chase.py 无模块级 `should_zone_change`（仅私有 `_contract_should_zone_change` L143），判定移入 core/dungeon_boss.BossFlow.should_zone_change（方法形态）；`resume_chase_battle` 不存在，功能拆为 world/chase_resume.prepare_resume_battle（签名不同：chase_ctx/enemy_state/battle_state）。
- 影响：按 m3 契约签名的调用方会 ImportError / TypeError（静态推导，当前库内无此类调用方——铁律 5「共享接口以本契约为准」未满足，属契约合规缺口）。
- 修复建议：chase.py 增加契约签名薄封装（`should_zone_change = BossFlow(...).should_zone_change` 或委托 chase_trigger；`resume_chase_battle = prepare_resume_battle` 别名），或修订 m3 §3.2 签名并登记变更（二者取一，推荐前者保持契约稳定）。

### P2-5 · phases 配置形态漂移：定稿 `{hp_from, hp_to, behavior}` 不被 PhaseTable 解析 → 恒阶段1 【副本定稿 L241-246 / 细化_2a3 §2.3 vs core/monster_phases.py L63-72、L103；core/dungeon_boss.py L176-185】

- 定稿/2a3 的 phases 条目为 `{hp_from: 100, hp_to: 60, behavior: "阶段1·常规"}`（hp_from=高血端上限 / hp_to=低血端下限）；monster_phases.PhaseTable 只读 `threshold`（L66/L71/L103），`hp_from/hp_to` 会被忽略 → 全部 threshold 回落 0.0 → 任意 hp>0 的 `resolve_phase` 恒返回阶段 1（静态推导）。
- dungeon_boss 补白 3（L27-28）声称「phases 配置可覆盖（构造器 > boss_def.phases > 默认）」，但未说明只认 threshold 键形态——按定稿形态配内容包会静默全阶段 1（狂暴/绝境行为永不触发）。
- 修复建议：PhaseTable 增补 `hp_from/hp_to` 键归一（hp_to 视作 threshold 下限、hp_from 视作上界，按 (hp_from,hp_to] 归段；或显式映射 hp_from→threshold）；并给 dungeon_boss 加一条「定稿 phases 形态」测试。

### P2-6 · zone_change 配置形态文档漂移：2a2/定稿 `trigger:{type,value}` 与 dungeon 级 zone_change 不被解析 【2a2 §7.1 L240-245 / 副本定稿 L142-146、L222 vs core/dungeon_boss.py L360-367、L395-400；content/dungeon_models.py L188-200】

- 实现与校验器均按 m3 §3.1 顶层 `hp_threshold`（小数 0.3，dungeon_models 硬拦 ∈(0,1)）解析，与 legal pack（enemies.json L128-133 `hp_threshold: 0.3`）一致 ✅。
- 但 2a2 §7.1 与副本定稿的示例形态为嵌套 `trigger:{type:"hp_below", value:30}`（百分比）且副本定稿 L222 还把 `zone_change.pv_recover` 放在 dungeon.json 级——两种形态实现均不解析：按定稿形态写内容包会「永不换区」（trigger 未识别，静态推导）或 pv_recover 取不到（on_chase_continue 只读 boss.zone_change，L395-400，dungeon 级 pv_recover 被忽略）。
- 修复建议：以 m3 为准的前提下，在 dungeon_boss 读取处加 `trigger.value` / `trigger.hp_below` 兼容归一（或在校验器/文档层明确废弃 2a2 §7.1 形态并更新 2a2 示例），并统一 pv_recover 的配置源优先级（boss.zone_change → dungeon.zone_change）。

### P2-7 · pursue 不注入 conditions：hidden 通道在追击中不可走，目标区仅 hidden 可达则追击不可完成 【world/chase.py L362-367、L412】

- pursue 签名与调用均无 `conditions`（L412 `resolve_move(player_ctx, direction, maps=maps)`），hidden 通道按 fail-safe 不可走（movement `_hidden_ok` 未注入→False）。
- 契约 2a2 R16/R18 允许隐藏通道参与追击路径（追击走通道=同一 /进入 语义）；若 BOSS 候选区仅经 hidden 通道可达，玩家永远 caught=False（也不计 miss，因移动失败不计错），追击死锁（既不捕获也不错失，除非走回起始区）。静态推导。
- 修复建议：pursue 增加 `conditions` 透传参数（签名与 resolve_move 对齐），并把「hidden 不满足」与「死路」区分提示。

---

## 3. 维度③ 幻觉 / 缺漏

| 项 | 结论 |
|---|---|
| docstring 引用行号真实性 | ⚠️ 部分陈旧：见 P2-1（引用 2a2 §2.1 满值口径，已被文末 2026-08-26 裁决取代）、P2-6（引用 2a2 §7.1 trigger 形态，实现为 m3 形态）。其余（m3 §3/§4、2a3 §2.2/§2.3、怪物定稿 L98/L99）与文档内容相符 |
| 工程补白冒充定稿 | ✅ 无冒充：5 文件全部「工程补白」显式标注且内容属实（入场校验先于消耗、会话持久化批次 7、守门怪标记键、错失窗口护栏等均如实声明） |
| 声明覆盖但未实现 | ⚠️ 两处：① DungeonSession「防串档」字段已落位且持久化层已校验（非缺漏）；② BossFlow 声称接受 DungeonSession 但读取静默降级（见 P2-3）；③ 「PV 恢复时机=换区瞬间落库」未实现（见 P2-2） |
| 零消费函数 | ⚠️ `DungeonSession.with_rest_count`（dungeon.py L141-142）与 `DungeonStateMachine.state()`（L439-441）无任何生产/测试调用（grep 全库确认）——P3-1 |
| 跨模块接口签名漂移 | ⚠️ 见 P2-4（契约 §3.2 两函数改名/拆分）、P2-5（phases 键形态）、P2-6（zone_change 键形态）、P2-3（会话形态） |

---

## 4. P3（次要）

- P3-1 · 零消费方法：`DungeonSession.with_rest_count`（dungeon.py L141-142）、`DungeonStateMachine.state()`（L439-441）全库无调用。建议删除或补测试/接线。
- P3-2 · 防串档只校验 content_pack_id 不校验 version：`load_dungeon_session`（dungeon_persist L654-659）仅比 id；m3 §4.4「+version 防跨包串档」的 version 维度未落实（跨批次观察，非本批次文件）。
- P3-3 · verify_m3 `_KEY_FUNCS`（verify_m3.py L229-264）未登记 `chase_resume.prepare_resume_battle / exit_dungeon_reset` 模块导入（两函数由 snapshot_resume 传递消费、test_chase_resume 已覆盖，缺口仅门禁清单完整性）。

---

## 5. 结论

- **P0 = 0**（无崩溃/数据损坏级缺陷）
- **P1 = 1**：pursue 错失窗口误伤合法推进（深图追不到，追到续战不可达）
- **P2 = 7**：满值口径 docstring 陈旧 / PV 恢复时机未落库（R10/TC-09）/ 会话形态漂移 / 契约 §3.2 接口签名漂移 / phases 配置形态漂移 / zone_change 配置形态文档漂移 / pursue 不注入 conditions
- **P3 = 3**：零消费方法 / version 校验缺口 / verify_m3 清单未列 chase_resume
- 无问题维度确认：状态集与迁移表（含边界拒绝）、入场校验、三阶段端点归属、残血换区判定链、PV 缺失量公式本体、离开重置、子任务五形式——均已落地且主链路正确。
- 运行行为结论均为「静态推导」，未经执行验证。
