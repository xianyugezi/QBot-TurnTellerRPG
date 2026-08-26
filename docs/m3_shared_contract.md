# M3 共享接口契约 v1（地图 / 换区 / 副本 / 时间天气）

> 2026-08-26 · M3 地图里程碑多路并行的权威依据。范围 = 规划_路2a_地图副本.md M01–M43（10 章 9 批次）+ 细化_2a1a~2a4c 共 9 份。verify_m3 = **81 条 TC**（2a1c 25 + 2a2 24 + 2a3 16 + 2a4b 16；2a1a/2a1b/2a4a/2a4c → worldtime 必测场景 L296 + M43 时间锚点回归）。
> 依据细化：细化_2a1a（地图 schema）/ 2a1b（通道刷怪）/ 2a1c（副本衔接）/ 2a1d（采集宝箱图鉴条件）/ 2a2（换区追击）/ 2a3（副本两型）/ 2a4a（时间引擎）/ 2a4b（天气引擎）/ 2a4c（时间天气接口）。定稿未定义处以【工程补白】标注。

---

## 一、批次与任务映射（9 批次 43 任务）

| 批次 | 内容 | 任务 | 依赖 |
|---|---|---|---|
| 0 数据骨架 | 装载器与配置全落地 | M01、M07、M11、M16、M21、M31 | 路3 E7/F 组 |
| 1 时间引擎 | M32–M36 | 依赖 M31 |
| 2 天气引擎 | M37–M41 | 依赖 M31、M32 |
| 3 地图行走 | M02–M06 | 依赖 M01；M05 隐藏通道依赖 M40 条件键 |
| 4 刷怪 | M08–M10 | 依赖 M32/M34 时间钩子、M38 天气池 |
| 5 副本两型+子任务 | M17–M20、M22–M23 | 依赖 M01/M16 |
| 6 换区追击 | M12–M15 | 依赖 M11 + 路1 T40/T42/T33 |
| 7 安全区/快照/死亡 | M24–M30 | 依赖 M16 + 路1 战斗会话 + 路3 A4/C 组 |
| 8 集成回归 | M42–M43 | 依赖全部 |

---

## 二、地图层（章1 网状地图 + 章2 刷怪，M01–M10）

### 2.1 maps.json 节点（8 字段，2a1a + 2a1c 扩展）

| 字段 | 类型 | 必填 | 语义 |
|---|---|---|---|
| `id` | string | 是 | 地图唯一 ID；dungeon.json `maps` 引用（探索/BOSS 共用同一组地图 ID） |
| `name` | string | 是 | 玩家可见地图名（换区提示/候选区用） |
| `desc` | string | 建议 | 地形/通道/机制/宝箱预告文本 |
| `spawn` | Spawn[] | 否 | 怪物分布（引用 enemies.json，BOSS 房可空） |
| `exits` | object | 否 | 4 方向通道（up/down/left/right；缺省=死路） |
| `mechanics` | Mechanic[] | 否 | 场地效果（落石/陷阱/机关；探索/BOSS 共用） |
| `gate_guard` | string | 否 | 守门怪（enemies.json 怪物 ID） |
| `dungeon_entrances` | DungeonEntrance[] | 否 | 副本入口挂载（2a1c 新增；非方向性，与 exits 并列） |

### 2.2 exits 通道（每方向一个对象）

```json
"exits": {
  "up":    { "to": "molten_entrance",    "mode": "bidirectional" },
  "down":  { "to": "molten_lava_tunnel", "mode": "one_way" },
  "left":  { "to": "molten_core",        "mode": "bidirectional" },
  "right": { "to": "molten_mine",        "mode": "hidden",
             "condition": { "var": "subquest_done", "op": "eq", "param": "learn_mechanic" } }
}
```

- `to`：目标地图 ID（须存在，硬拦）
- `mode`：`bidirectional` / `one_way` / `hidden`（hidden 必带 condition）
- `condition`：条件引擎表达式（{var,op,value,param} 统一语法）
- `shortcut`（2a1a 6 字段版）：捷径标记（通常配 one_way）；`lore`：通道介绍文本
- 校验器：① to 存在（硬拦）② mode 枚举 ③ hidden 必带 condition（硬拦）④ 双向不对称 → 黄提示

### 2.3 Spawn 行字段

| 字段 | 类型 | 默认 | 语义 |
|---|---|---|---|
| `enemy` | string | 必填 | enemies.json 引用（id/name 均可） |
| `count` | int | 1【工程补白】 | 该行同时在场数量上限 |
| `respawn_minutes` | int | 必填 | 刷新间隔分钟 ≥1 |
| `active_time` | {from,to} | 空=全天 | 现实钟点窗口（"20:00-06:00" 跨夜） |
| `seasons` | string[] | 空=全年 | 季节限定（∈ spring/summer/autumn/winter） |
| `periods` | string[] | 空=全天 | 时段限定（∈ dawn/noon/dusk/night/midnight） |
| `weather_weights` | {天气:倍率} | 默认 1 | 天气出现率倍率；0=该天气不刷；只影响刷新不驱逐在场 |

出没语义（2a1b R16-R22）：seasons/periods/active_time AND 叠加；**时段结束 → 场上怪物移除**（"对方逃跑了"，仅非战斗场景）；天气/季节不打断战斗（战斗会话每回合开始重读）；地图级 `max_alive` 聚合上限【工程补白 默认 10】；rank 权重 = 怪物本体 tier。

### 2.4 地图行走判定接口（M02–M06）

```python
# core/map_graph.py（新增，纯逻辑无 IO）
def can_move(map_id: str, direction: str, ctx: dict) -> MoveResult
    # MoveResult = {ok, to, mode, hidden_ok, blocked_reason?}
    # 双向直接可走；单向反方向 → 拦截提示"此路不通"；hidden 条件未满足 → 提示"此处无通道"
def bidirectional_consistent(maps: list) -> list[Warning]   # 双向不对称黄提示
def path_exists(from_id: str, to_id: str, maps: list, ctx: dict) -> bool  # 捷径/追击路径计算
```

---

## 三、换区追击（章3，M11–M15，2a2 细化）

### 3.1 zone_change 配置（enemies.json 怪物级）

| 字段 | 类型 | 语义 |
|---|---|---|
| `zone_change` | object | 怪物换区配置（残血阈值触发） |
| `zone_change.enabled` | bool | 是否启用换区 |
| `zone_change.hp_threshold` | float | 残血阈值（如 0.3 = 30% 以下） |
| `zone_change.targets` | string[] | 候选逃往地图（随机/条件选一） |
| `zone_change.timing` | string | 触发时机（行动后/阶段后） |

### 3.2 换区规则要点（2a2 R1-R27）

- **触发**：BOSS/精英残血（hp ≤ threshold）且非最后一次行动 → 换区逃跑，战斗结束
- **逃跑行为**：进入 `chasing:true`，提示"XX 逃向了【候选区】"（目标区名 = maps.name）
- **候选区**：targets 列表随机选一（固定种子可复现）；玩家不熟悉地图 → 绕路/遇精英
- **追击**：玩家 `/进入 <方向>` 走通道；**走错/错过 → 错失窗口**（BOSS 回满/离开副本）
- **续战**（M14）：追到后触发遭遇 → BOSS **残血保持 + PV 半恢复（向下取整）+ 开场技**；血量**不重置**
- **门禁语义**：PV 半恢复受 debuff 门禁（效果减半层数保留，破防全量爆发——1g4 PV 防护值机制）
- **离开副本重置**（M15）：非战斗离开 → BOSS 状态/残血/进度全清，下次满状态重打

```python
# world/chase.py（新增）
def should_zone_change(enemy_state: dict, cfg: dict) -> bool
def pick_chase_target(cfg: dict, rng) -> str        # 确定性（注入 rng）
def resume_chase_battle(enemy_state: dict) -> dict  # 残血保持 + pv 半恢复 + 开场技标记
```

---

## 四、副本（章4-7，M16–M30，2a3 细化）

### 4.1 dungeon.json 两型结构

| 字段 | 类型 | 语义 |
|---|---|---|
| `id` | string | 副本 ID（如 molten_dungeon） |
| `name` | string | 副本名 |
| `type` | "explore" / "boss" | 探索版（练习赛）/ BOSS 版（正式赛） |
| `entry_item` | string | BOSS 版入场道具（探索版 null 不扣） |
| `entry_limit` | int | 入场次数限制（0=不限） |
| `maps` | string[] | 引用 maps.json 地图 ID（两组副本**共用同一组地图**） |
| `boss_room` | string | BOSS 房地图 ID（BOSS 版） |
| `boss` | string | BOSS 怪物 ID（enemies.json） |
| `subquests` | string[] | 副本子任务（引用 quest.json） |
| `safe_zone` | string | 安全区地图（缺省=入口区） |
| `drops` | object | 通关掉落（含 first_clear 首通奖励，结构同 2a1d 宝箱） |

### 4.2 副本内状态集 S0–S7 + 迁移（M1–M15）

| 状态 | 名称 | 含义 |
|---|---|---|
| S0 | ENTRY | 入口态（=安全区） |
| S1 | PEACE_EXPLORE | 平静探索（走通道/子任务/宝箱采集） |
| S2 | ELITE_ESCALATE | 升压精英（遭遇精英，可打可绕） |
| S3 | BOSS_CHASE | BOSS 追击态（chasing:true，/进入 <方向> 追击） |
| S4 | FINAL_DEATHMATCH | 决战态（BOSS 房/残血续战） |
| S5 | CLEARED | 通关态（奖励/图鉴/首通） |
| S6 | DEAD_RECOVER | 死亡复活态（复活点 + 虚弱禁入非安全区） |
| S7 | LEFT | 离开态（副本重置） |

迁移要点：M5 换区（残血阈值）→ S3；M6 追到 → S4 决战（残血+PV 半值+开场技）；M8 击杀 → S5；M9 战斗死亡 → S6；M15 原地 /休息 ≠ 离开（位置/BOSS 血量/快照保留）；战斗中断不改变状态（走快照续玩）。

```python
# core/dungeon.py（新增）
def enter_dungeon(player_ctx, entrance: dict) -> EnterResult   # 入场校验（entry_item/limit）→ S0
def exit_dungeon(player_ctx) -> ExitResult                      # 非战斗离开 → S7 重置
def dungeon_state_machine(state: str, event: str, ctx: dict) -> str  # S0-S7 迁移
```

### 4.3 副本子任务五形式（M21–M23）

- 五形式：到达指定区域 / 击败指定怪 / 收集指定物 / 完成指定交互 / 达成指定条件
- zone 限定副本 ID；进副本自动激活（不占板槽位）；奖励与可选性（不完成可进 BOSS）

### 4.4 快照续玩 / 死亡 / 安全区（M24–M30）

- 战斗快照续玩：ai_state + combo_state + 换区上下文全保留（衔接细化_1g3/1g4）
- 副本内死亡：复活点复活 + 虚弱期（禁入非安全区含 BOSS 房）；死亡 ≠ 离开，离开即重置
- 副本会话持久化：当前区域/已清区域/子任务进度/换区上下文/BOSS 状态/休息次数随存档（路3 A4）；清理时机=通关/重置；含 content_pack_id+version 防跨包串档
- /休息：副本内语义（恢复 / 冷却缩减 / 次数限制）；≠ 离开副本（不重置、快照保留）

---

## 五、时间引擎（章8，M31–M36，2a4a 细化）

### 5.1 周期注册表（框架级唯一）

| 周期 | 键 | 周期长（可配） | 推进 |
|---|---|---|---|
| 季节 | spring/summer/autumn/winter | season_days ×86400（默认 7，整数 ≥1） | 顺序循环 |
| 时段 | dawn/noon/dusk/night/midnight | period_minutes ×60（默认 60，整数 ≥30） | 顺序循环 |
| 天气 | 内容包自定义键 | weather_minutes ×60（默认 60，整数 ≥30） | 生效池等概率抽签（tick 不取模） |

### 5.2 settings.json time_cycle 段

`enabled`（默认 true）/ `season.season_days` / `period.period_minutes` / `weather.weather_minutes` / `weather.default_pool`（非空键唯一）/ `broadcast.enabled`（默认 false）/ `broadcast.mode`（lazy）/ `broadcast.template`（占位符 {type,name,emoji,map}）

### 5.3 引擎公开接口 IF01–IF12（engine/worldtime.py 扩展，2a4c）

| # | 接口 | 签名 | 语义 |
|---|---|---|---|
| IF01 | 总开关 | `is_enabled() -> bool` | false → 查询提示未启用、条件键失效、spawn 退化为仅 active_time |
| IF02 | 季节查询 | `season_now(now=None) -> str` | 固定枚举 |
| IF03 | 时段查询 | `period_now(now=None) -> str` | 固定枚举 |
| IF04 | 天气查询 | `weather_now(map_id, now=None) -> str` | 玩家当前图天气（上下文绑定） |
| IF05 | 生效池 | `map_pool(map_id) -> list[str]` | 覆盖池 else 默认池（排序供种子） |
| IF06 | 周期索引 | `cycle_tick(kind, now=None) -> int` | season_idx=floor((now−ANCHOR)/(days×86400))%4；period_idx %5；weather_tick 不取模 |
| IF07 | 倒计时 | `time_remaining(kind, now=None) -> int` | 距下次变化秒（/时间 数据源） |
| IF08 | 确定性抽签 | `map_weather(map_id, tick, now=None) -> str` | 生效池[pick(sha256(池键排序+str(tick)))]；同 tick 跨群/进程/重启同值 |
| IF09 | 变化检测 | `check_changes(player, map_id) -> list[Change]` | 每条指令处理前调；比较缓存索引与重算值；一次 ≤3 条顺序固定 季节→时段→天气；离线只播最新 |
| IF10 | 懒广播 | `maybe_broadcast(changes, ctx) -> None` | 默认 false 不播；跨群去重；战斗结算后补播 |
| IF11 | 存档 | `load_time_state()/save_time_state()` | world_state.time_state（season_idx/period_idx/weather_tick/map_weather_seen）；字段级迁移缺补默认多忽略 |
| IF12 | 配置重排 | `recalc_on_config_change() -> None` | 改配置 → 旧缓存失效重算 + 黄提示；后续按新配置推进 |

**锚点**：ANCHOR = 2000-01-01 00:00:00 UTC+8；now = UTC+8 秒级时间戳。零定时器、不存历史、随时可重算。三周期互不读写对方状态。

### 5.4 条件键三键（M40，条件引擎注册表）

`{var:"season", op:"eq", param:X}` [季节:X] X∈四季固定；`{var:"period",...}` [时段:X] X∈五时段固定；`{var:"weather",...}` [天气:X] X∈注册天气集（内容包自定义，按玩家当前所在图取值）。季节/时段全局值；非法枚举红拦。

---

## 六、天气引擎（章9，M37–M41，2a4b 细化）

### 6.1 核心规则

- 每次天气变化从**生效池等概率抽一个**（确定性 seed，非顺序）
- 地图 `weather_pool` 覆盖（maps.json 顶层；缺省/空数组=默认池；元素 ∈ 注册键，V5 硬拦）
- 同一 tick 不同图可不同天气；变化时刻全局一致
- 消费方联动（M39）：采集点 weather_mods（rate_mult/rarity_shift，0=不出）/ 怪物 weather_weights（M10）/ 钓鱼 seasons/periods 过滤 / 图鉴 lore condition / 战斗 combat.weather_mult（默认关，每回合开始读天气，不改 formula 本体）

### 6.2 校验器 V1–V8 + 黄提示（M41）

V1 season_days≥1 / V2 period_minutes≥30 / V3 weather_minutes≥30 / V4 池非空键唯一 / V5 地图池引用∈注册键 / V6 消费方枚举引用 / V7 combat mults 键∈注册集 / V8 broadcast.template 占位符。黄提示：365 天/1440 分/池>12 种/单种池恒定/无消费方/池变更重排。

---

## 七、verify_m3 81 TC 矩阵（门禁承载）

| 来源 | TC 数 | 承载（实现后补） |
|---|---|---|
| 2a1c 地图副本衔接 | 25 | tests/unit/test_map_dungeon_link.py |
| 2a2 换区追击 | 24 | tests/unit/test_chase.py |
| 2a3 副本两型 | 16 | tests/unit/test_dungeon.py |
| 2a4b 天气引擎 | 16 | tests/unit/test_weather.py |
| 2a1a/2a1b/2a4a/2a4c | （worldtime 必测场景 L296） | tests/unit/test_worldtime.py + test_map_graph.py |

**门禁**：G3 已达成（M2 全绿）；M3 完成判据 = M01–M43 验收 + M42 端到端 + M43 三条回归全绿 + verify_m3 81 TC 全绿。

---

## 八、铁律（M3 所有路遵守）

1. **零定时器**：周期值只能由锚点公式得出（M43 探针），禁止定时器驱动周期
2. **确定性**：抽签/换区去向/追击路径固定种子可复现；随机一律注入 rng
3. **懒计算**：不存历史、不跑定时器、随时可重算；缓存索引仅供变化检测
4. **平台无关**：core/world/data 零 NoneBot import；world 层处理器签名 `(ctx: dict, pc: ParsedCommand) -> str`
5. **接线防死**：新模块查全库调用方（禁止孤岛）；共享接口以本契约签名为准
6. **战斗通道**：换区续战/死亡/回血走既有战斗通道（1g4 battle_boundary），禁止旁路直扣
7. **条件键单口**：季节/时段/天气三键只在条件引擎注册表登记一次，消费方零新增机制
8. **每功能可追溯**：文件头标注「依据：细化_2aX §Y」；工程补白显式标注不冒充定稿
9. **概率小数 fraction**：概率输出小数；不硬编码绝对路径/敏感信息（.env 或 config）
10. **快照完整性**：战斗中断续玩 ai_state+combo_state+换区上下文逐字段一致
