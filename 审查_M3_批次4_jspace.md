# 审查_M3_批次4_jspace.md

> 静态审查报告（j-space 门控 full 档 · 接缝审计 · ship 前核对）
> 批次4 世界集成：刷怪 / 安全区休息 / 快照 / 副本持久化
> 审查日期：2026-08-26 后（与仓库 docs 拍板日同源）
> **方法声明**：本环境无 bash 沙箱，全程零命令/脚本/运行验证，仅静态代码审查 + 参考文档比对 + 测试文件交叉印证；所有运行行为结论均标注「静态推导」。
> 审查文件（6）：`qbot_rpg/world/spawn.py`、`spawn_weather.py`、`rest.py`、`snapshot_resume.py`、`dungeon_persist.py`、`game_world.py`
> 参考文档：`docs/m3_shared_contract.md`（§2.3/§4.4/§八）、`docs/细化/细化_2a1b_通道规则与刷怪.md`（含 2026-08-26 裁决）、`docs/细化/细化_2a3_副本两型流程.md`、`docs/细化/细化_2a4c_时间天气接口.md`、`docs/细化/细化_1g3_快照续战与测试.md`、`docs/规划/规划_路2a_地图副本.md`、`docs/实现层规划文档.md`、`docs/审查参考/副本系统设计定稿.md`、`docs/审查参考/怪物模块设计定稿.md`、`docs/审查参考/时间天气系统设计定稿.md`（引用路径）、配套测试 `tests/unit/test_spawn.py` / `test_spawn_weather.py` / `test_rest.py` / `test_snapshot_resume.py` / `test_dungeon_persist.py`
> 依赖交叉核对：`qbot_rpg/content/map_models.py`、`qbot_rpg/content/dungeon_models.py`、`qbot_rpg/world/battle_boundary.py`、`qbot_rpg/world/chase_resume.py`、`qbot_rpg/core/dungeon.py`

---

## 结论汇总

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | **0** | 未发现数据损坏/串档/越权级确定性缺陷；content_pack 防串档拒绝逻辑正确 |
| **P1** | **2** | ① max_alive 阻塞行计时被消耗（补刷永久丢失，静态推导）；② weak_duration_sec=0 导致永久虚弱（静态推导） |
| **P2** | **20** | 跨模块契约分裂（active_time/出没链/world_state 键形态）、声明-实现落差、防御缺口、文档残迹等 |

---

## 一、维度① 定稿落地（逐项确认）

### 1.1 已确认落地（无问题）

| 定稿项 | 落点 | 核验 |
|---|---|---|
| 懒补刷（M08，零定时器） | spawn.py `refresh` L124-176 | floor(时间差/有效间隔) 截断缺口 ✓；无击杀记录全量补足 ✓；测试 test_spawn.py L208-309 印证 |
| 时段/季节出没 AND 叠加（R16/R27/TC-16） | spawn.py `filter_eligible` L178-192；spawn_weather `spawn_eligible` L230-264 | active_time∩seasons∩periods 全 AND ✓；空=不限（R27）✓；测试双覆盖 |
| 出没边界移除（E2/R17/R29） | spawn.py `zone_expire_removal` L194-224 | 只认 seasons/periods 边界；天气不驱逐（R30）✓；active_time 结束不移除 ✓；测试 test_spawn.py L314-381 |
| 天气权重变速不驱逐（M10/R28/R30） | spawn_weather L112-189 | weight≥1 更快 / 0<w<1 更慢 / 0=不刷且计时冻结（L178-184）✓；在场怪只增不删 ✓；测试 L172-202 |
| 地图级 max_alive（R21 补白） | spawn_weather `max_alive_guard` L91-106 + 聚合顺序结算 L145-176 | 实装并有测试（test_spawn_weather L60-83、L206-233）；**但见 P1-1 与 P2-4（未收口）** |
| 安全区休息（M24/M25/M26） | rest.py 三函数 | 安全区=入口区∪配置∪maps 标记（补白 3/4 显式）；恢复/冷却缩减/次数限制/≠离开 语义齐备 |
| 快照续玩（M27） | snapshot_resume.py `resume_from_snapshot` | ai_state/combo_state/turn 完整性闸门 + factory 注入 ✓；续玩非重置（reset:False）✓ |
| 死亡复活（M29） | dungeon_persist.py `on_dungeon_death` | 复活点优先级（revive_point→BFS）✓；penalty 三档 ✓；R29 未配 checkpoint 自动降级重置 ✓；BOSS keep/reset（R30）✓；死亡≠离开 ✓ |
| 会话持久化（M30） | dungeon_persist.py save/load/clear | 字段清单（当前区域/已清/子任务/换区上下文/BOSS/休息次数）✓；清理时机=通关/重置 ✓；content_pack_id 不匹配拒绝 ✓（test L404-421） |
| **monsters 键名统一（2026-08-26 拍板）** | map_models.py L155（`_entries("monsters")`）、L338（`entry.get("monsters")`）；game_world `spawn_defs()`；测试均用 `monsters` | **content 层与 world 层一致落地 ✓**；残留 `spawn` 字样仅文档/报错路径（map_models.py L4 docstring 8 字段名仍写 `spawn`、L342/L346 校验错误 field 路径 `maps.{idx}.spawn`）——仅命名残迹，不影响读取 |

### 1.2 未完全落地 / 偏离

- **冷却缩减默认值**：定稿/规划 M25/验收 TC-2a3-15 为「默认 3 回合」（副本定稿 §2.1 L98、规划 L188、2a3 TC-2a3-15 L297），实现取 1（rest.py L79-80 补白 1）→ P2-8。
- **休息次数默认**：定稿 rest_per_dungeon 缺省 = null/不限（副本定稿 L214），实现 DEFAULT_REST_LIMIT=3（rest.py L82-83）把「每日 3 次」口径误用到每副本上限 → P2-9。
- **虚弱时长 0**：`_death_policy` 接受 0（dungeon_persist.py L324），on_dungeon_death 仍无条件写 weakened=True 且不写 weak_until → is_weakened 永久为真 → **P1-2**。
- **content_pack_version 防串档**：契约 §4.4「id+version 防串档」；save 落 version（L577）但 load 只比对 id 不比对 version（L654-659）→ P2-15。
- **max_alive 未进路L 收口路径**：SpawnManager.refresh（路L）无 max_alive 参数；GameWorld.monster_pool 亦不应用；max_alive 仅存在于无生产调用方的路M → P2-4。

---

## 二、维度② 代码质量（P1/P2 明细，全部静态推导）

### P1-1 · spawn_weather.py L167-176 + L177-184：max_alive 阻塞行计时被消耗 → 补刷永久丢失

`weather_weighted_refresh` 顺序结算：行因地图级 max_alive 聚合上限被拦（`allowed=0`）时，写回块 `if due > 0:` 仍执行 `st_new["last_refresh"] = min(now, last_refresh + int(due*interval*60))`（L181-183）——已流逝间隔被消耗。静态推导：此后即使场上腾出名额（击杀/换图），下次调用 `elapsed≈0 → due=0`，该行不补刷，直到再过一个完整间隔；若刷新间隔很长（如 60 分钟），被挡补刷在 max_alive 让位后的一个间隔内静默丢失。测试 test_spawn_weather L208-233 只断言 products 与 alive，未断言被拦行 last_refresh（缺口）。
**修复建议**：`allowed==0 且 due>0` 时该行不推进 last_refresh（欠账保留，下次补）；仅当 `requested==0`（行已满）或 `allowed>0` 时才消耗计时；并补「被拦行计时冻结」测试。

### P1-2 · dungeon_persist.py L494-496 / L507-512 / L516-520 + L733-737：weak_duration_sec=0 → 永久虚弱

`_death_policy` 接受 `weak_duration_sec>=0`（L324），`weak_until` 仅在 `duration>0` 时生成（L495-496），但 `weakened=True` 无条件写入会话与 ctx（L507/L516）。`is_weakened` 无 weak_until 时回退布尔标记（L733-737）→ 配置 0（语义应为「不虚弱」，对齐 battle_boundary.apply_weakness L477-478「0 → 不虚弱」）后玩家被 `check_weakened_entry` 无限期禁入非安全区。静态推导；测试仅覆盖 duration=60 路径。
**修复建议**：`weak_duration_sec==0` 时不写 weakened 标记（或写 weak_until=now 即时过期），与 DEATH-01/apply_weakness 口径对齐；补 0 时长测试。

### P2 明细（按文件）

**spawn.py**
- P2-1（L203）：`zone_expire_removal` docstring「仅非战斗场景由调用方触发」与 2026-08-26 裁决冲突——裁决：「时段边界战斗中按细化_1g4『提示对方逃跑了 → 按退出结算』，非『仅非战斗』」；m3 契约 §2.3 同处旧措辞。战斗路径由 battle_boundary.decide_lost(period_ended)（LOST-06）承载，分工可解释，但注释应改为「非战斗场景由本函数触发；战斗中走 decide_lost(period_ended)」，避免收口时被误读为只做非战斗。
- P2-2（L248-254）：`_row_key` = enemy 引用（补白 1 自认「同图多行引用同一 enemy 共享 world_state 键」）。静态推导：两行同 enemy（count 2+3）时 alive_count 合并，各行 gap=cap−共享存活 互相吞噬，行2 可能永不补刷。建议 key 改为 `f"{enemy}#{index}"` 或直接行序号（输出 dict 已带 index，文案取怪名可另映射）。
- P2-3（L37-44）：`Spawner.catch_up_offline` docstring 写「M3 实装」但函数体 `raise NotImplementedError`；类头已声明「仅签名」，方法级 docstring 措辞与实现不符。建议 docstring 标注「预留签名」。

**spawn_weather.py（跨模块分裂，收口风险最高）**
- P2-4（L112-189 + L91-106）：`weather_weighted_refresh`/`max_alive_guard` **生产零消费**（全仓仅本模块引用自身 + 测试）；与路L `SpawnManager.refresh` 并存两套补刷语义：world_state 键形态（`{row_index:{alive,last_refresh}}` vs `{last_kill_time,alive_count}` 按 enemy 键）、首刷归属、写回策略（路M 可变 dict 才写回）。补白均显式，但「收口时对齐」尚未发生——monster_pool 注入路L 管理器后 max_alive 完全不生效。建议批次收口时明确单一权威实现或显式分层。
- P2-5（L210-227 vs spawn.py L289-306）：`active_time_ok` 边界语义不一致——路M 闭区间 `lo<=cur<=hi`（06:00 含），路L 半开 `[from,to)`（06:00 不含，补白 3，测试 L110-115 固化）；半配（仅 from/to）路M=全天、路L=单侧无界；`_hhmm`（L201-207）不做 0-23/0-59 范围校验（"25:00"→1500 通过），路L `_hhmm_to_minutes` 校验。同契约字段两套语义，GameWorld 换过滤源结果不同。建议统一为路L 半开口径 + 范围校验。
- P2-6（L230-264 vs spawn.py L178-192）：出没链含天气不一致——路M `spawn_eligible` 链尾含 `weather_weights≠0`（对齐 2a1b R27 全 AND），路L `filter_eligible` 不含天气（补白 2 归 E3/refresh）。两套「可出没」定义并存；建议在收口契约中显式固定一条（推荐天气归刷新结算，与 S1/2a4c 一致）。
- P2-7（L186-188）：非可变 world_state 路径只返回 products（仅含获批行），不含被拦/满行的新 last_refresh；「由调用方落盘」从返回值不可重建 world_state 更新。建议返回中包含 per-row 状态变更或约定落盘格式。

**rest.py**
- P2-8（L79-80）：DEFAULT_COOLDOWN_REDUCTION=1 vs 定稿/规划 M25/TC-2a3-15「默认 3」；补白 1 称「批次指令取默认 1」——仓内无可验证依据（唯一仓内默认=3）。测试 test_rest L229-233 固化 1。建议补白注明拍板出处，或在收口时改回 3（配置可覆盖）。
- P2-9（L82-83）：DEFAULT_REST_LIMIT=3 为「每副本上限」语义，但 3 是定稿「每日 3 次/天」的默认；副本定稿 rest_per_dungeon 缺省=null（不限）。静态推导：未配 rest_limit 的 BOSS 副本第 4 次休息被拦，与定稿「不限」冲突。建议缺省 0（不限）或显式按 rest_per_dungeon 配置注入。
- P2-10（L285-310）：`_read_current_resource`/`_read_max_resource` 对 `player_ctx=None` 或非 Mapping 无防御（直接 `.get` → AttributeError），与模块其余「防御兼容」风格（is_safe_zone/_session_field）不一致；chase_resume._battle_in_progress 同类场景有 `isinstance` 兜底。建议入口归一 `ctx = player_ctx if isinstance(player_ctx, Mapping) else {}`。
- P2-11（L480-495）：`rest_is_not_exit` 的 `kept` 判定未纳入 `chase_ctx`（docstring L473 声称换区上下文保留为判据，返回字段有 chase_ctx_preserved 但 kept 不含）；且 boss_state/subquest_progress 要求非空 Mapping——探索版/无 BOSS 会话合法空 dict 时恒 kept=False（假阴性）。建议 kept 只断言「键存在且未清空语义」，或把空 dict 视为合法保留态。

**snapshot_resume.py**
- P2-12（L195-208 + docstring L145-174）：铁律 10「ai_state+combo_state+换区上下文逐字段一致」——实现仅做键存在性校验（Mapping 非空），逐字段一致性未校验（依赖注入 factory 自担）；docstring「逐字段保留」措辞过满（补白 2 已部分说明）。建议 docstring 明确「闸门=键存在性；逐字段由 factory 保证」。
- P2-13（L32-33 补白 2 + L108-118）：引用「1g3 §1.2/§1.3 双写」措辞偏差——1g3 L97 双写为 `turn` 与 `snapshot_at.boundary`；代码读 `snapshot_at.turn`（该键在 1g3 §1.2 schema L30 确实存在，功能无害），但引用表述不精确。建议改引「snapshot_at.turn（schema L30）」。
- P2-14（L76）：`_CHASE_CTX_KEYS` = (chase_ctx, zone_chase, zone_change, chasing, chase_target) 与 chase_resume._ZONE_CHASE_KEYS（含 chase、不含 zone_change）清单不一致，docstring 称「对齐 chase_resume 补白 7」——同源声明，清单却不同。建议双端统一常量（如收口到 chase_resume 导出）。

**dungeon_persist.py**
- P2-15（L633-669）：load 仅校验 content_pack_id，version 只透传不比对；契约 §4.4「content_pack_id+version 防跨包串档」的 version 侧未落地。建议 load 增加 `expected_version` 参数（可选）或返回信号由接线层比对。
- P2-16（L568-569 vs L597-599）：save 的 subquest_progress 值不过滤类型（`{str(k): v ...}`），load 过滤 `isinstance(v,int) and not bool`——round-trip 不对称（脏值存进去、读出来被丢）。建议 save 侧同过滤，保证 round-trip 幂等。
- P2-17（L712-737）：`is_weakened` docstring 声称「+ player persistent 兜底」，代码实际只读 session/ctx/ctx.player 三源，**不读 Player.persistent_state[WEAK_UNTIL_KEY]**（权威落点，battle_boundary WEAK_UNTIL_KEY L304）。静态推导：权威时间态仅存 persistent_state 而无镜像时，虚弱禁入判定漏判。建议补读 persistent_state（或补白声明依赖 M4 镜像写入）。
- P2-18（L740-775）：`check_weakened_entry` 虚弱放行仅比较单 `_safe_zone`（L771-773）；2a3 §4.3 L266「期间可待在复活点/入口/安全区」——入口区（maps[0]≠safe_zone 配置时）与复活点（=入口或 revive_point）均被拦；且与 rest.is_safe_zone 并集定义（入口∪配置∪标记）不一致。建议放行集合与 is_safe_zone 同源（复用/注入安全区集合）。

**game_world.py**
- P2-19（L151-170）：`monster_pool` 注入 `alive_monsters` 时，前面算出的 `eligible`（L165）被丢弃——「过滤可出没行」仅在占位路径生效；docstring L154-156 声称流程含过滤。静态推导：alive_monsters 返回的在场怪（含已过期但未到边界移除的）原样透出。建议明确语义（在场查询权威 → 过滤仅用于占位）或对结果再过滤。
- P2-20（L93-94 + L121-138）：docstring 写注入契约 `filter_eligible(spawn_rows, ctx)`，实调为 `filter_eligible(row, now)`（路L 单行契约，L135），与 spawn_weather.filter_eligible_rows 签名混淆；`WorldNotFoundError`（L33-35）定义后零使用（get_map 抛 NotImplementedError）。建议 docstring 修正签名；异常类或接线或删除。

---

## 三、维度③ 幻觉 / 缺漏

### 3.1 docstring 引用行号真实性核查（抽样全查）

| 引用 | 核验结果 |
|---|---|
| spawn.py：实现层规划文档.md L480-488（M08/M09） | ✅ 真实（docs/实现层规划文档.md L480-483 M08、L485-488 M09） |
| spawn.py：细化_2a1b §二/§三、2a4c §3（E1-E3/S1/S2）、m3 §2.3 | ✅ 真实 |
| spawn_weather.py：2a1b R14/R18/R21/R26-R28、规划 M10、契约 §2.3/§八铁律 1/3 | ✅ 真实 |
| rest.py：2a3 R16/R21/R32/M15、m3 §4.4、规划 M24-M26、2a1c R3 | ✅ 真实（2a3 L52/57/68/160；规划 L182-195；2a1c L28） |
| rest.py 补白 1「批次指令按批次收口取默认 1」 | ⚠️ 仓内不可验证（唯一仓内默认=3，见 P2-8） |
| snapshot_resume.py：1g3 §1.2/S1/§2.1/§2.3/§2.4、1g4 TIME-04/F-08 | ✅ 基本真实；「双写」措辞偏差见 P2-13 |
| dungeon_persist.py：2a3 §2 迁移表 M9/M10/M11/M14、§4 R26-R32、m3 §4.4、规划 M29/M30、battle_boundary DEATH-01/02/07/08 | ✅ 全部真实（含 battle_boundary L302/304/508/559） |
| game_world.py：契约 §2.1/2a1a §1.7（gate_guard） | ✅ 真实 |

**结论：未发现编造行号；发现 1 处仓内不可验证的「批次指令」依据（P2-8）与 2 处引用措辞偏差（P2-13、P2-14）。**

### 3.2 工程补白冒充检查

✅ 未发现补白冒充定稿：rest.py 补白 1-8、dungeon_persist 补白 1-9、spawn.py 补白 1-4、spawn_weather 补白均显式标注「工程补白/不冒充定稿」；safe_zone 节点标记（rest 补白 4）明确声明为工程约定（契约 2a1a 8 字段确未列）。补白质量整体良好。
⚠️ 例外：P2-8/P2-9 两处默认值偏离虽有补白，但其偏离方向和仓内唯一权威默认相反，且「批次指令」依据不可验——补白「显式」但不「可追溯」（铁律 8 精神）。

### 3.3 声明覆盖但未实现 / 零消费函数

| 项 | 状态 |
|---|---|
| Spawner 三方法（refresh_map/catch_up_offline/refill_world_stock） | 声明「仅签名」✅；但 catch_up_offline 方法 docstring 写「M3 实装」→ P2-3 |
| GameWorld get_map/list_maps/move_to_map/world_stock/load/to_world_state/is_boss_alive | 类 docstring 声明「预留签名」✅（不在本批次实装范围） |
| resume_from_snapshot 默认（无 factory） | 退化为校验闸门，已补白 1 ✅（但「续玩」实际能力依赖接线注入） |
| content_pack_version 防串档 | 声明含 version，load 未校验 → P2-15 |
| is_weakened「player persistent 兜底」 | 声明有、代码无 → P2-17 |
| 全部 6 文件对外函数的生产调用方 | **生产路径零消费**（仅测试消费）；各模块 docstring 均声明「接线由 M4/M6/指令层/存储层」，✅ 属里程碑中间态；**接缝最高点 = 路L/路M 双补刷路径未收口（P2-4）** |

### 3.4 跨模块契约对齐

核心不一致清单：active_time 边界（P2-5）、出没链含天气（P2-6）、world_state 键形态/写回（P2-4/P2-7）、安全区集合（rest 并集 vs core.dungeon._safe_zone 单图 vs check_weakened_entry 单图，P2-18，其中 rest.py 补白 3 已显式声明与 core.dungeon「互补不冲突」✅）、_ZONE_CHASE_KEYS 清单（P2-14）。**monsters 键名、状态常量（S1-S7/DEAD_RECOVER/LEFT）、rest_count 迁移（core.dungeon L86/L430 rest_count+1）等关键契约两侧一致 ✅。**

---

## 四、分级问题清单（编号 / 文件:行号 / 修复建议摘要）

| 级别 | 编号 | 位置 | 问题（静态推导） | 修复建议 |
|---|---|---|---|---|
| P1 | 1 | spawn_weather.py L167-184 | max_alive 阻塞行 last_refresh 仍推进 → 补刷欠账丢失 | 被拦行（allowed=0 且 due>0）冻结计时；补测试 |
| P1 | 2 | dungeon_persist.py L494-520, L733-737 | weak_duration_sec=0 → 永久虚弱禁入 | duration=0 不写 weakened；与 apply_weakness 口径对齐 |


---

## 五、无问题维度确认

1. **懒补刷核心公式（M08）**：两模块 floor 折算、缺口截断、零定时器 ✅（除 P1-1 阻塞边角）
2. **时段/季节出没 AND 叠加与边界移除（M09/E2）**：判定与移除语义 ✅
3. **天气权重只变速不驱逐（M10/R18/R30）**：两模块一致 ✅
4. **死亡≠离开 / 复活点 / 三档惩罚 / R29 降级 / BOSS keep-reset** ✅
5. **content_pack_id 防串档拒绝逻辑** ✅（version 侧见 P2-15）
6. **monsters 键名统一（2026-08-26 拍板）**：content 层+world 层一致 ✅（残留 `spawn` 字样仅 map_models.py L4 docstring / L342/L346 报错路径，命名残迹不影响读取）
7. **docstring 行号真实性**：抽样全查无编造 ✅（3 处偏差见 P2-8/P2-13/P2-14）
8. **工程补白显式标注、不冒充定稿** ✅（默认值偏离方向问题见 P2-8/P2-9）
9. **状态常量/rest_count/离开重置跨模块对齐**（core.dungeon/chase_resume/rest/snapshot/dungeon_persist）✅
10. **纯函数纪律**：零 NoneBot import、零 IO、不改入参（rest 补白 6、snapshot 补白 4、dungeon_persist 铁律）✅

---

*审查口径：P0=确定性数据损坏/串档/越权；P1=可复现功能缺陷（配置/边界触发）；P2=契约分裂、声明-实现落差、防御缺口、文档残迹。全部运行行为结论为静态推导，未经运行验证。*
