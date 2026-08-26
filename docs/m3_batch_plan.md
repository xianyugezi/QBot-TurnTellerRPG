# M3 批次派工单（9 批次 43 任务 → 多批多路）

> 2026-08-26 · 依据：docs/m3_shared_contract.md（权威契约）+ 规划_路2a_地图副本.md + 细化_2a1a~2a4c。
> 每批 3 路并行（服务器 4 核舒适上限）；路间写不同文件防冲突；每批主 agent 落盘核对 + 全量回归再进下一批。

## 批次 0 · 数据骨架（M01/M07/M11/M16/M21/M31）—— 3 路并行

| 路 | 任务 | 文件（新增/扩展） | 接口锚点 |
|---|---|---|---|
| A | M01 maps 装载 + M07 spawn | content/models.py（MapDef/SpawnDef）、content/field_meta.py（maps_fields/spawn 子段）、content/validator.py（maps R 系列）、tests/fixtures/packs/legal/maps.json、tests/unit/test_maps_schema.py | 契约 §2.1-2.3；GameWorld.get_map/list_maps |
| B | M11 zone_change + M16 dungeon.json | content/models.py（DungeonDef）、content/field_meta.py（dungeon_fields/enemies zone_change 子段）、content/validator.py（dungeon R 系列）、tests/fixtures/packs/legal/dungeon.json、tests/unit/test_dungeon_schema.py | 契约 §3.1/§4.1；enemies.json zone_change 字段 |
| C | M31 time_cycle 配置 | content/field_meta.py（SETTINGS_FIELDS 加 time_cycle）、content/validator.py（V1-V3 + time_cycle 红拦）、qbot_rpg/engine/worldtime.py（骨架：ANCHOR/IF01 is_enabled）、tests/unit/test_time_cycle_config.py | 契约 §5.2/§5.3 IF01-IF06 骨架 |

**批次 0 收口**：3 路落盘核对 → fixtures 全量 validator 零红拦 → 全量 pytest 绿 → 进批次 1。

## 批次 1 · 时间引擎（M32–M36）—— 依赖批次 0 C 路

| 路 | 任务 |
|---|---|
| D | M32 锚点 + 三周期懒计算（IF02/IF03/IF06/IF07 纯函数）+ 单位测试（2026-08-16=夏） |
| E | M33 三周期独立推进 + M34 变化检测钩子 + 懒广播（IF09/IF10） |
| F | M35 time_state 存档（IF11）+ M36 /时间 /天气 查询指令（接口 + 文案，指令接线 M4 前落引擎） |

## 批次 2 · 天气引擎（M37–M41）—— 依赖批次 0 C + 批次 1

| 路 | 任务 |
|---|---|
| G | M37 天气池等概率确定性抽签（IF08/map_weather）+ M38 地图池覆盖（IF05） |
| H | M39 消费方联动（weather_mods/weather_weights/lore condition/combat.weather_mult）+ M40 条件键三键注册 |
| I | M41 校验器 V1-V8 接线 + 黄提示 |

## 批次 3 · 地图行走（M02–M06）—— 依赖批次 0 A + 批次 2（M05 依赖 M40）

| 路 | 任务 |
|---|---|
| J | M02 双向通道判定 + M03 单向拦截 + M04 捷径/追击路径（core/map_graph.py） |
| K | M05 隐藏通道（条件） + M06 /进入 <方向> 接线 + 地图切换钩子（world 层） |

## 批次 4 · 刷怪（M08–M10）—— 依赖批次 1/2

| 路 | 任务 |
|---|---|
| L | M08 补刷懒计算 + M09 时段/季节出没边界（world/spawn.py 扩展 + GameWorld.monster_pool 实装） |
| M | M10 天气权重刷新 + 在场不驱逐（weather_weights 接入） |

## 批次 5 · 副本两型+子任务（M17–M20、M22–M23）—— 依赖批次 0 B

| 路 | 任务 |
|---|---|
| N | M17 探索/BOSS 共用 + M18 探索版流程（core/dungeon.py 状态机 S0-S7） |
| O | M19 BOSS 版流程 + M20 BOSS 三阶段换区联动 |
| P | M22 子任务五形式判定 + M23 奖励（子任务引擎；M21 配置已在批次 0 B） |

## 批次 6 · 换区追击（M12–M15）—— 依赖批次 0 B + 战斗

| 路 | 任务 |
|---|---|
| Q | M12 换区触发 + M13 追击行走/错失窗口（world/chase.py） |
| R | M14 续战（残血保持+PV 半恢复+开场技，走战斗通道）+ M15 离开副本重置 |

## 批次 7 · 安全区/快照/死亡（M24–M30）—— 依赖批次 0 B + 战斗会话

| 路 | 任务 |
|---|---|
| S | M24 安全区 + M25 /休息 + M26 休息≠离开 |
| T | M27 快照续玩 + M28 非战斗离开重置 |
| U | M29 副本内死亡 + M30 副本会话持久化 |

## 批次 8 · 集成回归（M42–M43）

- M42 端到端冒烟（探索版 + BOSS 版两路径固定种子可重放）
- M43 三条回归探针（零定时器 / 确定性抽签 / 快照完整性）
- verify_m3 81 TC 全绿 + run_all_tests 注册 + dsh 审查 → 汇报用户拍板

---

## 批次 0 共享契约要点（本批 3 路必须先读 m3_shared_contract.md §2-§5）

- maps.json 8 字段（id/name/desc/spawn/exits/mechanics/gate_guard/dungeon_entrances）+ exits 4 方向（to/mode/condition）+ spawn 行 7 字段
- dungeon.json 两型（id/name/type/entry_item/entry_limit/maps/boss_room/boss/subquests/safe_zone/drops）
- enemies.json zone_change 子段（enabled/hp_threshold/targets/timing）
- settings.json time_cycle 段（enabled/season/period/weather/broadcast）
- 铁律：零 NoneBot import / 接线查调用方 / 文件头标注细化依据 / 工程补白显式标注
