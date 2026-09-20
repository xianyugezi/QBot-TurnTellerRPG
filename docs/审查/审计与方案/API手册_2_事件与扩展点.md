# 框架扩展开发手册 · 第 2 章 · 事件与扩展点

> **本章读者**：① 写内容包 / 写包自持代码 / 用 E 系扩展点的**外部扩展开发者**；② 改框架代码前先看它的**未来维护者**。
> **本章目标**：把"框架在哪些时点会对外说话（事件）、包能在哪些位置把代码/数据接进去（扩展点）、每一段的声明归谁读、改了谁会疼"一次讲清；使后续更新**不再把故意设计当 bug 修**。
> **写法**：中文说人话，先讲"这是什么 / 什么时候用 / 谁负责"；每条附 `file:line` 供查；表格优先。

## 0. 本章导读

### 0.1 三条口径（全章通用术语）

| 口径 | 定义 | 对扩展开发者意味着什么 |
|---|---|---|
| **唯一源**（single source of truth） | 该信息**只有一处定义**，其它模块必须 `import` 它，**不得写死字面量** | 你要改它，只改这一处；你要用它，从这一处取 |
| **可被包覆盖** | 内容包通过 `settings.json` / 同名 json 能改；引擎侧"只读声明、不写死" | 你能在包里调数值 / 开开关，而不是改框架 |
| **有派发点 / 无派发点** | 事件时点在**生产代码里真的有一处会调用 `_dispatch_event(...)`** / 只在枚举里声明 | **无派发点 = 你照它写效果永远不会触发**（详见 §2.2 三态表） |

**路径书写约定**：为省版面，本章正文里的 `battle.py` / `effects.py` / `event_dispatcher.py` / `validator.py` 等简写，均指 `qbot_rpg/` 下的对应文件。**唯一需要特别记住的一处歧义**：`battle.py` = `qbot_rpg/core/battle.py`（**不是** `qbot_rpg/data/battle.py`，后者是 `BattleSnapshot` 等契约 dataclass）。其余引用若省略目录，可在仓库里用 `grep -rn` 按文件名定位。

### 0.2 【稳定契约】标记说明

凡标注 **【稳定契约】** 的条目 = **改动需评审**。含义是：该名称 / 值域 / 形状已被内容包、测试或存档数据依赖；单方面改它会**静默破坏**（不是编译报错，而是旧包效果永不触发、旧存档读不出、测试对拍崩）。改之前请：

1. 读该条目的 `file:line` 定义处注释（多数已写明"勿动 / 为什么"）；
2. 查 `docs/深度打造_决策记录.md` 是否已有落地登记 / 裁决；
3. 确认有迁移或兼容路径，再动。

### 0.3 核对基线与复核声明

- **本次核对基线**：仓库 HEAD = `62cc299`（批73 死代码清理后）。
  上游盘点文档 `API手册_编撰前盘点.md` 基于 `d86d9dd`（2026-09-20），**行号已整体漂移**（`core/battle.py` 漂移 −3 ~ −5 行，`core/effects.py` 漂移 −3 ~ −9 行）。
- **复核方式（分两级，如实标注）**：
  - **一级（逐条重读源码 / 运行核对）**——§1 两套事件体系、**§2 全部 17 个时点及其派发点**、§3 易混对、§4 归属规则、§5 E1/E2/E3 契约、§6 `ext_api`、§8 hooks：这些结论**均已逐行读源码**，或由 `grep -rn` 全仓扫描、`python3` 导入取值确认。
  - **二级（机器校验行号存在性）**——§7 包声明段表（尤其 `settings.*` 的"谁读它"列）体量大，本次对全章 **462 处 `file:line`** 跑了一遍自动校验（解析每个引用 → 定位文件 → 核对行号在范围内）：**孤儿引用 2 处，已修正**（`ext/render.py` 的区间上界、`方案_E.md` 的路径写法）。**范围为"行号真实存在"，不等于"该行语义即所述"**；§7 的读取处若有疑，请按 `file:line` 复核后再引用。
  - **未复制**盘点文档的未复核结论：凡与盘点不一致处，均以本次实测为准并在 §10.2 逐条列出。
- **已发现并纠正的盘点文档说法**（详见 §10 复核记录）：
  1. 盘点把 `settings.*` 声明段记为 **41 条**；本次运行 `field_meta._module_table()` 实测框架 `settings` schema 有 **54 段**（41 是盘点选择性列出的行数）。
  2. 盘点把 `field_meta.json` 顶层段记为 **12 条**；本次读 `field_meta_pack.TOP_LEVEL_KEYS` 实测 **16 个顶层键**（12 是盘点把 4 组同族键合并成行后的行数）。
  3. 盘点称 `EVENT_POINTS` 17 点里 **11 点有派发点**；本次全仓 `grep -rn` 复核**结论一致**（§2.2 给了 11 条派发点原文证据）。
  4. 盘点"93 条"= **行数口径**（9+41+30+12+1），不是唯一键数口径；§7.1 说明两种口径的差别。
  5. **本次新发现 3 条盘点未提的事实**：veinborn 的 `surge_tick` 静默死效果（§3.3）、`on_expire` 无派发路径（§3.2）、`action_end` 与 `action_start` 不对称（§2.4）——均**只报告、不改**，列入 §10.3 待查。
- **标"待查"**：凡本章未亲手核到唯一源 / 未确认意图的，一律写"待查"，**不猜**。

### 0.4 本章结构

| 节 | 讲什么 | 你会拿它做什么 |
|---|---|---|
| §1 | 两套"事件"体系辨析 | 先分清你要用的是哪一套（**外部开发者第一坑**） |
| §2 | `EVENT_POINTS` 逐时点 17 点 + 三态表 | 写 `effects.trigger` 前查这里，确认它真的会触发 |
| §3 | 易混对专章（各给正 / 反例） | 避免把效果挂到错误的一侧 |
| §4 | 归属（owner）规则 | 理解"谁的效果只能由谁触发" |
| §5 | 扩展点 E1 / E2 / E3 契约 | 写包自持指令 / 渲染 / 测试 |
| §6 | 稳定面 `qbot_rpg.ext_api` | 包代码**唯一允许** `import` 的面 + 版本兼容 |
| §7 | 包声明段全表 | 查某个 `settings.*` / `manifest.*` 段归谁读、能不能覆盖 |
| §8 | hooks：对外 vs 内部 | 分清哪些是契约、哪些"不是扩展点" |
| §9 | "怎么接"可复制步骤 | 照着做：加时点 / 加指令 / 加渲染 |
| §10 | 复核记录 | 本章改了盘点文档哪些结论、证据是什么 |

---

## 1. 两套"事件"体系辨析（外部开发者最容易混的第一坑）

### 1.1 这是什么 / 为什么会有两套

框架里有**两个都叫"事件"、但互不派发**的体系。名字像、都能在配置里写、都影响"什么时候发生什么"，但它们是两条完全独立的管线：

| 体系 | 唯一源 | 用途 | 存储 | 消费方 | 你能在哪写它 |
|---|---|---|---|---|---|
| **A. 战斗效果时点** `EVENT_POINTS` | `qbot_rpg/data/event_points.py:25` | 让 `effects` 条目的 `trigger` 字段 / `statuses` 条目的 `on_gain/on_lose/on_expire` 在**战斗过程中的某个时点**触发一批动作 | **不存储**，即时分派 | `core/event_dispatcher.dispatch_event`（`event_dispatcher.py:246`） | `effects.json` 的 `trigger`、`statuses.json` 的 `on_*` |
| **B. 计数事件键** `[事件:XXX]` | `qbot_rpg/core/event_bus.py:53`（`EVENT_KEY`）+ `:66`（`EVENT_KEY_DEFAULTS`） | 进阶 / 成就 / 任务条件的**计数触发**（签到、击杀、图鉴、副本通关…累计了多少次） | `event_counts` + `event_log` 环形（`:46` `EVENT_LOG_KEY`，`:49` `DEFAULT_EVENT_LOG_CAP=300`） | `core/condition_engine` / `core/quest.py` / 成就校验器 | `条件`里的 `[事件:签到]` 这种键；`settings.events` 段可配 name 段 |

**一句话判据**：
- 你要做的是"**开战时给全体上护盾**""**被杀时回血**""**每次行动开始叠一层**"→ 用 **A（`EVENT_POINTS`）**。
- 你要做的是"**累计签到 7 次解锁称号**""**击杀 100 只怪完成任务**"→ 用 **B（`[事件:XXX]`）**。
- 两者**不会互相触发**：A 的时点派发**不**给 B 加计数；B 的计数**不**派发 A 的效果。

### 1.2 体系 B 的键清单（13 类，`event_bus.py:66-80`）

`EVENT_KEY_DEFAULTS` 是**缺省键名表**（零配置时 `resolve_event_key` 回退到这里，向后兼容零破坏）：

| # | 事件名（`settings.events` 可配的 name 段） | 写入点（注释所指出处） |
|---|---|---|
| 1 | 签到 | `core/checkin.py` `do_checkin` 尾 |
| 2 | 副本通关 | `core/dungeon.py` 探索 clear 通关点 |
| 3 | 等级提升 | `core/levelup.py` 升级结算 |
| 4 | 怪物击杀 | `commands/battle_commands.py` win 结算 |
| 5 | 任务完成 | `core/quest.py` → `adventure_log.log_story_node` |
| 6 | 图鉴新增 | `core/codex.py` + `core/fishing_codex.py` + `log_codex_new` |
| 7 | 成就达成 | `core/achievements.py` `_log_milestone` |
| 8 | 首杀 | `adventure_log.log_first_kill` |
| 9 | 首钓冠级 | `adventure_log.log_first_crown` |
| 10 | 隐藏发现 | `adventure_log.log_hidden_find` + `investigate_commands` 兜底 |
| 11 | 里程碑 | `adventure_log.log_milestone` |
| 12 | 环境事件 | `environment_events` `ENV_EVENT_KEY_BASE` |
| 13 | NPC对话 | `dialog` 动态键 + `event_key_npc_dialog`（`event_bus.py:57`） |

**硬编码边界（勿改）**：`[事件:` 外壳与 `:target]` 拼装是**路由语法**，`condition_engine` / `quest` / 内容校验器按 `[事件:` 前缀 + `]` 尾缀 + `rsplit(":")` 解析。**只可配 name 段，外壳必须硬编码保留**——这是 `event_bus.py:51-53` 注释写明的审计结论（风险5）。**改外壳 = 拆掉三处解析器的公共协议**，属【稳定契约】。

**配置形状**：`settings.events` 段 = `{事件名: 键名}`。取段函数 `_events_section`（`:83`）兼容"传 ctx"与"传 settings"两种入参；解析入口 `resolve_event_key`（`:100`）。缺失/非 Mapping → 一律回退默认键，**零配置不抛**。

### 1.3 体系 A 的接线全景（本章主线）

```
effects.json 条目.trigger ──┐
statuses.json 条目.on_gain/on_lose/on_expire ──┤
装配注入 procs（ctx_vars.procs） ──┤
符文声明效果（combatant.rune_effects） ──┘
                        │
                        ▼
      battle._dispatch_event(event, side)     ← core/battle.py:2035（唯一派发封装）
                        │  归属过滤 _owner_scope  battle.py:2067
                        ▼
      event_dispatcher.dispatch_event(...)    ← core/event_dispatcher.py:246
                        │  _iter_candidates  :81（扫注册表 / 归属过滤）
                        │  _run_candidate    :184（计数·深度·chance 门 + execute_action）
                        ▼
              side_effects 列表（回到战斗主流程）
```

**谁负责**：框架 `core` 层持有全部派发逻辑；内容包**只声明数据**（`trigger` / `on_*` / 符文效果引用），**不写派发代码**。这是"包只声明、引擎才派发"的权责分界。

**安全失败（包/内容出错不崩服）**：
- `battle._dispatch_event` 整体包 `try/except`：未注入 registry / 分派异常 → 返回 `[]`，**不阻断战斗主流程**（`battle.py:2052-2065`）。
- `dispatch_event` 对未知事件 → `[]`（`event_dispatcher.py:289-290`）；`snapshot` 非 Mapping → `[]`（`:291-292`）；无候选 → `[]`（`:301-302`）。
- `_iter_candidates` 在 registry 没有 `resolve` / `all_ids` 时 → `[]`（`:110-111`）。

---

## 2. `EVENT_POINTS` 逐时点（17 点）

### 2.1 唯一源与再导出

| 项 | file:line | 说明 |
|---|---|---|
| **唯一源** 【稳定契约】 | `qbot_rpg/data/event_points.py:25` | `EVENT_POINTS: Tuple[str, ...]`，17 个时点。**这是 `effects.trigger` 的唯一值域源** |
| 再导出（兼容旧 import 路径） | `qbot_rpg/core/event_dispatcher.py:68` | `EVENT_POINTS = EVENT_POINTS_SOURCE`，故 `from qbot_rpg.core.event_dispatcher import EVENT_POINTS` 依旧可用 |
| 状态事件子集 | `qbot_rpg/data/event_points.py:38` | `STATUS_EVENT_POINTS = ("status_gain", "status_lose")` |
| 派发封装（唯一出口） | `qbot_rpg/core/battle.py:2035` | `Battle._dispatch_event` |
| 归属作用域 | `qbot_rpg/core/battle.py:2067` | `Battle._owner_scope` |
| 校验器（值域门禁） | `qbot_rpg/content/validator.py:3335-3412` | `trigger ∉ EVENT_POINTS` → **黄提示 Y-19**（允许先声明未来时点，但永不触发）；非字符串 → **红拦 R-1**；缺 `trigger` / 空串 → 放行 |

**为什么落在 `data` 层而不是 `core` 层**（`event_points.py:3-6`）：为了让 `content` 层校验器能按分层契约 `content → {data}` 校验 `trigger` 取值域，而**不必**反向 `import core`——与批50 把面板三轴 stem 落在 `data/gear_stats.py` 是同一取舍。**改这个文件的层位 = 改分层契约**，属【稳定契约】。

**顺序也是契约**（`event_points.py:23-24`）：前 16 点（`battle_start` … `season_change`）**原样保序**，批51 新增的 `on_kill` **插在 `on_skill` 与 `season_change` 之间**——目的是避免既有断言位移。**追加新时点请追加在末尾**，不要插入中间。

### 2.2 三态总表（17 点：已接 11 / 二期未接 5 / 故意不派发 1）

> **这是本章最重要的一张表**。外部开发者照枚举写效果之前**必须**先看"态"列：写"无派发点"的时点，效果**永远不会触发**（校验器只发黄提示，不拦你）。

| # | 时点 | 态 | 生产派发点（file:line） | 谁收（side） | 备注 |
|---|---|---|---|---|---|
| 1 | `battle_start` | ✅ 已接 | `battle.py:2465`（player）/ `:2466`（enemy） | 两侧各一次 | 在资源初始化之后、CTB 建条之前 |
| 2 | `battle_end` | ✅ 已接 | `battle.py:2170`（player）/ `:2171`（enemy） | 两侧各一次 | **在 marks 清零前**派发——效果仍可读印记/状态 |
| 3 | `action_start` | ✅ 已接 | `battle.py:2959` | 行动者 | 在 `_do_action_inner` 动作分派**之前**，**覆盖全部动作类型**（普攻/技能/道具/防御/逃跑） |
| 4 | `action_end` | ✅ 已接 | `battle.py:3018` / `:3119` / `:4058` / `:4635` / `:5044` | 行动者 | **5 条返回路径各自派发**（见 §2.4 缺口）；改战斗流程时勿漏 |
| 5 | `turn_start` | ✅ 已接 | `battle.py:2837` | **行动者**（不是双方） | 按持有者派发（替代旧的全员 `turn_start`） |
| 6 | `turn_end` | ⛔ **故意不派发** | **无** | — | CTB 已删除"回合单位"；枚举保留**仅为兼容**。见 §3.3 |
| 7 | `status_gain` | ✅ 已接 | `effects.py:2254`（`_dispatch_status_event`，def `:2031`） | **状态持有侧** | 状态施加**成功后**（`res.applied` 为真）才派发 |
| 8 | `status_lose` | ⚠️ 已接（驱散）/ 未接（tick 过期） | `effects.py:2276`（dispel 移除后） | 状态持有侧 | `on_expire` 也映射到本事件（`event_dispatcher.py:74`）；**tick 过期路径的 `on_lose` 尚未接**（见 §3.2 待查） |
| 9 | `mark_gain` | ⛔ 二期未接 | **无** | 印记持有侧 | `记录.md:842` 列为二期。**写了永不触发** |
| 10 | `mark_lose` | ⛔ 二期未接 | **无** | 印记持有侧 | 同上。注意：`battle.py:1102` 的 `result["mark_lose"]` 是**战斗结果标记**，与本事件**同名不同物**，别误认成派发点 |
| 11 | `death` | ✅ 已接 | `battle.py:1133` | **死者自己** | 唯一死亡判定点 `_death_check_side`（`battle.py:1114`） |
| 12 | `revive` | ✅ 已接 | `battle.py:1188` | 复活侧 | 注释 `:1157` 记录："此前无人派发，现补" |
| 13 | `on_attack` | ⛔ 二期未接 | **无** | 攻击方 | 全仓**零字面量**（除枚举/docstring） |
| 14 | `on_hit` | ⛔ 二期未接 | **无** | 攻击方 | 设计意图见 `docs/审查参考/效果系统设计定稿.md:157`（特效伤害不进 `on_attack`，需 `on_hit` 显式配置）。**当前不可用** |
| 15 | `on_skill` | ⛔ 二期未接 | **无** | 攻击方 | `记录.md:842` 列为二期 |
| 16 | `season_change` | ✅ 已接 | `battle.py:2031`（player）/ `:2032`（enemy） | 两侧各一次 | 与 `season_procs`（既有装配通道）**双轨**触发 |
| 17 | `on_kill` | ✅ 已接 | `battle.py:1145` | **击杀者侧**（1v1 的另一侧） | 批51 新增；`dead_mark` 门控，每次击杀**恰好一次**；同归于尽 / 战斗已结束 → 不派发 |

**计数核对**：已接 = #1,2,3,4,5,7,8,11,12,16,17 = **11 点**；二期未接 = #9,10,13,14,15 = **5 点**；故意不派发 = #6 = **1 点**。11+5+1 = 17 ✅。

**"无派发点"的复核方法**（你可自己重跑）：
```bash
cd /root/QBot-TurnTellerRPG
for ev in mark_gain mark_lose on_attack on_hit on_skill turn_end; do
  echo "### $ev"
  grep -rn "\"$ev\"\|'$ev'" --include=*.py qbot_rpg/ \
    | grep -v "event_points.py\|event_dispatcher.py"
done
```
实测：`mark_gain` / `on_attack` **零输出**；`mark_lose` 只命中 `battle.py` 的战斗结果标记；`turn_end` 只命中 `_LEGACY_BOUNDARIES`（`battle.py:212`）与 DOT 的 `tick` 值（`effects.py:1374`）；`on_hit` 只命中 `resource_axis_validator.py:99` 的**另一套** `PROC_TRIGGER_EVENTS`（`on_turn_start/on_hit/on_season_change`，与 `EVENT_POINTS` **不是同一套**，见 §10 待查 P-3）；`on_skill` 只命中 `effects.py:2179` 的 `when in ("instant","on_skill")`（技能**施放时机**字段，不是事件派发）。

### 2.3 逐时点"何时派发"细节（已接 11 点）

> 供维护者改战斗流程时对表；供扩展开发者判断"我这个时点到底在哪个瞬间"。

| 时点 | 派发时机（人话） | 派发点所在函数 | 关键上下文 |
|---|---|---|---|
| `battle_start` | 战斗**开始**、资源已初始化、CTB 还没建条 | `Battle.start`（def `battle.py:2284`） | 两侧各派一次；`_to_state(STATE_ACT,"battle_start")` 在其后 `:2475` |
| `battle_end` | 战斗**收尾**，`result.flag` 已写、combo 已清零、**marks 尚未清零** | `Battle._settle`（def `:2142`） | 效果可读印记/状态；`marks_state` 在其后 `:2173` 清零 |
| `action_start` | 一次行动**开始**，在动作分派前（`atype` 尚未解析） | `Battle._do_action_inner`（def `:2956`） | **全动作类型覆盖**：普攻/技能/道具/防御/逃跑 |
| `action_end` | 一次行动**收尾**（各 return 前） | `_guard_actor:3018` / `_resolve_item_action:3119` / `_position_miss_outcome:4058` / `_resolve_damage_action:4635`、`:5044` | 5 条路径 |
| `turn_start` | 该 actor 的回合开始（`PHASE_TURN_START` 已设） | `Battle._start_actor_turn`（def `:2821`） | 按 actor 单侧派发；其后处理 `tick=="turn_start"` 的 DOT（`:2844`） |
| `status_gain` | **状态施加成功后**（`res.applied` 为真） | `effects.execute_action` 的 `atype=="status_apply"` 分支（`effects.py:2248-2255`） | 经 `_dispatch_status_event`（`:2031`）→ 注入的 `dispatch_event` |
| `status_lose` | **驱散移除后**，对该次被移除的每个 `status_id` 各派一次 | `effects.execute_action` 的 `atype=="dispel"` 分支（`effects.py:2257-2277`） | 注释 `:2259` 明写"印记非增益/减益，**天然不命中**" |
| `death` | 死亡标记后（`_mark_dead` 已完成、`STATE_DTH` 已设） | `Battle._death_check_side`（def `:1114`） | 派给**死者侧**（`side`） |
| `revive` | 复活成功：清 `dead_mark`、恢复 HP、去弱体、回收标记之后 | `Battle.revive_side`（def `:1150`） | 只对 `dead_mark=True` 的侧生效 |
| `season_change` | 季节事件结算之后（`season_procs` 通道已跑完） | `Battle._fire_season_event`（def `:1992`） | 双轨：`season_procs` + effects 通道 |
| `on_kill` | 与 `death` **同一判定点**，紧接着 `death` 之后 | `Battle._death_check_side`（def `:1114`） | 派给**击杀者侧** `self._opposite(side)`；`killer in BATTLE_SIDES and not self._dead(killer)` 才派 |

### 2.4 本次新发现：`action_start` / `action_end` **不对称**（待裁决，勿擅自"修"）

- `action_start` 派发点在 `_do_action_inner`（`battle.py:2959`），位于 **atype 分派之前** → **所有**动作类型都会派发。
- `action_end` 只有 **5 个派发点**，覆盖：防御（`_guard_actor`）、道具（`_resolve_item_action`）、方位 miss（`_position_miss_outcome`）、伤害结算（`_resolve_damage_action` ×2）。
- **`_flee_actor`（def `battle.py:3044`）与 `_skip_turn`（def `:3025`）里没有任何 `_dispatch_event`**（本次逐函数扫描确认）。

**这意味着**：`trigger="action_start"` 的效果在**逃跑/跳过回合**时会触发，`trigger="action_end"` 的效果在同样情形下**不会**触发。

**本章态度**：本次复核**只报告差异，不判定意图**——它可能是"逃跑不算完整行动"的**故意设计**，也可能是遗漏。**在 `docs/深度打造_决策记录.md` 给出裁决前，不要把它当 bug 直接补上**（补上会改变既有战斗数值，可能触发对拍崩）。标 **待查 P-4**（见 §10）。

### 2.5 状态事件映射（`on_gain` / `on_lose` / `on_expire`）

`statuses.json` 条目的三个字段映射到两个时点（`event_dispatcher.py:71-75`）：

| status 字段 | 映射到 | 说明 |
|---|---|---|
| `on_gain` | `status_gain` | 状态**获得**时 |
| `on_lose` | `status_lose` | 状态**消失**时（驱散） |
| `on_expire` | **`status_lose`** | 过期**归入消失语义**（同一事件，来源区分放在侧信息里） |

**这是"故意设计"**：三个字段、两个时点，`on_expire` 与 `on_lose` **共用一个事件**。改成一事件对一字段会拆掉既有内容包的效果链路，属【稳定契约】。

**字段值形态**：`[{"effect": id, "overrides": {...}}]` 或裸 actions 列表（`event_dispatcher.py:15-18`、`:130-138`）。状态事件的效果**默认作用在状态持有侧**（`side`）：动作未显式 `target` → 补 `target=side`（`event_dispatcher.py:232-235`）——"heal 状态获得回自己、爆炸打对方由动作显式指定"。

**状态事件不受归属过滤影响**（`event_dispatcher.py:104-105`）：状态 `on_*` 由 `status_id` 精确定位，**本已归属到状态持有侧**，所以 `owner_effect_ids` / `claimed_effect_ids` 对它不生效。

---

## 3. 易混对专章（各给正 / 反例）

> 这一节专治"效果挂到了错误的一侧"和"照着枚举写了永不触发的效果"。每条给一对 JSON 正/反例，可直接照着改。

### 3.1 `death` vs `on_kill` —— 语义相反、方向不同

**判断口诀**：**"我想在谁身上发生什么？"**——动作的对象是**死者**就写 `death`，是**击杀者**就写 `on_kill`。

| 想表达 | 写哪个 | 派发给谁 | 动作 `target` 相对谁 |
|---|---|---|---|
| 我击杀敌人时**回血 / 叠层 / 免冷却** | `on_kill` | **击杀者**（1v1 的另一侧） | 相对**击杀者** |
| 我死亡时**爆炸 / 给对手挂状态 / 留遗言** | `death` | **死者自己** | 相对**死者侧** |

**正例 A（击杀者回血）**——注意动作 `target` 是 `self`，而 `self` 在 `on_kill` 派发时**就是击杀者**：
```json
{
  "id": "kill_lifesteal",
  "name": "击杀汲取",
  "class": "special",
  "type": "heal",
  "trigger": "on_kill",
  "actions": [{ "type": "heal", "target": "self", "power": 120 }],
  "desc": "击杀敌人时回复自身 120 生命"
}
```

**正例 B（死亡爆炸）**——`target` 写 `enemy`，因为派发侧是**死者**，`enemy` 对死者而言就是对面：
```json
{
  "id": "death_blast",
  "name": "临终爆裂",
  "class": "special",
  "type": "damage",
  "trigger": "death",
  "actions": [{ "type": "damage", "target": "enemy", "power": 200 }],
  "desc": "死亡时对对面造成 200 伤害"
}
```

**反例（写错就挂到死者身上）**：
```json
{
  "id": "kill_lifesteal_WRONG",
  "trigger": "death",
  "actions": [{ "type": "heal", "target": "self", "power": 120 }],
  "desc": "❌ 本意是击杀回血，写 death 会变成「自己死的时候给自己回血」——人已经死了，白写"
}
```

**为什么这是故意的**（判据 `file:line`，不是我的推断）：
- `qbot_rpg/data/event_points.py:11-14`（模块 docstring 明写"两者语义相反、方向不同，不得混用"）；
- `qbot_rpg/core/event_dispatcher.py:32-37`（批51 补点语义说明）；
- `qbot_rpg/core/battle.py:1123-1127, 1140-1145`（同一判定点、`dead_mark` 门控）。

**边界（勿改）**：同归于尽 / 战斗已结束时，`on_kill` **不派发**（`battle.py:1144`：`killer in BATTLE_SIDES and not self._dead(killer)`）。这是"避免给已死单位挂击杀触发"的**故意设计**，不是漏判。

**幂等保证**：两者都靠 `dead_mark` 门控，**每次击杀恰好一次**——即使"连段套中击杀"也只派一次。

### 3.2 `status_gain` vs `mark_gain` —— 两套容器、两套动作

**状态（statuses）与印记（marks）是两套完全独立的容器**，不是同一种东西的两种名字。

| 维度 | 状态 `statuses.json` | 印记 `marks.json` |
|---|---|---|
| 施加动作 | `status_apply` | `mark_add` |
| 移除动作 | `dispel` / 过期 | `mark_remove` |
| 增益/减益属性 | **是**（有 `category`：buff/debuff/weak…） | **否**——印记**非增益也非减益** |
| 能否被驱散 | ✅ 能 | ❌ **天然不命中**（`effects.py:2259` 注释明写） |
| 事件时点 | `status_gain` / `status_lose` **已接** | `mark_gain` / `mark_lose` **未接（二期）** |
| 事件声明字段 | `on_gain` / `on_lose` / `on_expire` | 待查（无派发点，故当前无可用声明面） |

**正例**：想让"护盾被驱散时爆炸"，必须写成**状态的 `on_lose`**，不能指望印记：
```json
{
  "id": "shield_break",
  "type": "buff",
  "on_lose": [{ "effect": "explode_damage" }]
}
```
而 `effects.json` 里：
```json
{
  "id": "explode_damage",
  "name": "碎裂冲击",
  "type": "damage",
  "power": 150
}
```

**反例（把印记当状态用）**：
```json
{
  "id": "surge_mark_break_WRONG",
  "trigger": "mark_lose",
  "actions": [{ "type": "damage", "target": "enemy", "power": 150 }],
  "desc": "❌ mark_lose 无派发点（§2.2 #10），永不触发；且印记本就不吃 dispel"
}
```

**判据**：`effects.py:2259`（"印记非增益/减益，天然不命中"）；`data/gear_stats.py` 的 `stack_cap_delta` 轴 `consumer_note` 明写"marks.max_stack_of 半边未接，印记与状态两套容器"。

**待查 P-1（本次复核确认是"结构性缺口"，但未见意图裁决）**：`on_expire` 在分派器里映射到 `status_lose`（`event_dispatcher.py:74`），但**生产代码里唯一派发 `status_lose` 的地方是 `dispel` 分支**（`effects.py:2276`）。本次逐路径核对两条**tick 过期**路径，都只写 log、**不派发事件**：
- 衰减归零移除：`effects.py:824-825`（`_remove_status` 后 log `{"type": "status_expired", ...}`）；
- 持续双维回合扣减归零移除：`effects.py:1418-1420`（`tick_turns` 返回后 log `status_expired`）。

**结论**：`on_expire` 声明的效果**当前不会触发**；`on_lose` 只在**被驱散**时触发。这是"合法字段 + 无派发点"的第二类陷阱（与 §3.5 第 3 行同族，但更隐蔽——`on_expire` 连 `EVENT_POINTS` 值域校验都不过，因为它不是 `trigger` 字段）。**判据只有源码结构，无裁决文本** → 标**待查**，不改。

### 3.3 `turn_start` vs `action_start`（附 `turn_end` 废弃）

**CTB 之下"回合单位"已被"行动单位"取代**：一次行动开始 = `action_start`；一个 actor 轮到自己 = `turn_start`。

| 对比项 | `turn_start` | `action_start` |
|---|---|---|
| 派发次数 | 该 actor 轮到时 **1 次** | 该 actor **每次行动** 1 次 |
| 派发位置 | `Battle._start_actor_turn`（`battle.py:2821`） | `Battle._do_action_inner`（`:2956`） |
| 覆盖动作类型 | 回合开始（不含具体动作） | **全部**动作类型（普攻/技能/道具/防御/逃跑） |
| 配套收尾 | **无**（`turn_end` 不派发） | `action_end`（**5 条路径，且逃跑/跳过不派发**，见 §2.4） |

**正例（每回合开始叠一层、每次行动开始回蓝）**：
```json
{ "id": "turn_regen",  "trigger": "turn_start",  "type": "mark_add", "actions": [{"type":"mark_add","target":"self","mark":"surge_mark","count":1}] }
```
```json
{ "id": "action_mp",   "trigger": "action_start", "type": "mp_gain", "actions": [{"type":"mp_gain","target":"self","value":3}] }
```

**反例（`turn_end` 永不触发）**：
```json
{
  "id": "tick_gain_WRONG",
  "trigger": "turn_end",
  "actions": [{ "type": "mark_add", "target": "enemy", "mark": "surge_mark", "count": 1 }],
  "desc": "❌ turn_end 故意不派发——CTB 已删除回合单位，枚举保留仅为兼容"
}
```

**⚠️ 这个反例在仓库里真实存在（本次复核发现，高价值）**：
`content/veinborn/effects.json:51-64` 的 `surge_tick` 写了 `"trigger": "turn_end"`，而它自己的 `desc` 是"每次行动结束时敌方困斗+1（蚀脉蓄能）"——**描述的是 `action_end` 的语义，写的却是永不派发的 `turn_end`**。

- **为什么校验器没拦**：`validator.py:3409` 的 Y-19 判据是 `tv not in EVENT_POINTS`。`turn_end` **在** `EVENT_POINTS` 里，所以**黄提示不触发**（`validator.py:3373-3375` 的注释只说"值 ∉ EVENT_POINTS"这一种情况）。
- **为什么测试没拦**：全仓唯一引用它的测试是 `tests/unit/test_editor_batch45_nested_labels.py:147`，只验证**编辑器嵌套字段的中文 label**（`("veinborn","effects","surge_tick",("actions",0,"mark"))`），**不验证效果是否触发**。
- **结论**：这是一个**"合法枚举值 + 无派发点 = 静默死效果"**的实例，`desc` 与行为不一致。这正是框架自己在 `event_dispatcher.py:101-102` 警告的"**登记了不生效 = 陷阱**"同族问题。
- **本章态度**：**报告，不擅自改**。修它有两种可能（改 `trigger` 为 `action_end`，或框架补 `turn_end` 派发点），**都会改变 veinborn 的战斗数值**，须走评审。标 **待查 P-2**。

**判据（`turn_end` 是故意不派发）**：`docs/深度打造_实现说明.md:735`（"CTB 已删除回合单位 → 不再派发（写法保留仅为兼容）"）；`battle.py:212`（`_LEGACY_BOUNDARIES` 含 `turn_end`，仅作 legacy 边界名）。

### 3.4 `EVENT_POINTS` vs `[事件:XXX]` —— 两套体系

见 §1.1 对比表。**最短判据**：写 `effects.json` 的 `trigger` 字段 → 查 `EVENT_POINTS`；写 `条件`/`quest` 里的 `[事件:...]` → 查 `EVENT_KEY_DEFAULTS`。**互不派发**。

**反例（把计数事件键写进 trigger）**：
```json
{
  "id": "WRONG",
  "trigger": "[事件:怪物击杀]",
  "desc": "❌ 非字符串? 不——它是字符串，所以过 R-1；但 ∉ EVENT_POINTS → Y-19 黄提示，永不触发"
}
```

### 3.5 "登记了不生效 = 陷阱"：一张自查表

| 你写了 | 会发生什么 | 校验器反应 | 怎么发现 |
|---|---|---|---|
| `trigger` 是**拼错的词**（如 `on_kil`） | 永不触发 | **Y-19 黄提示** | 看校验输出 |
| `trigger` 是**未来时点**（`on_hit` 等） | 永不触发 | **Y-19 黄提示** | 看校验输出 |
| `trigger` 是**合法枚举但无派发点**（`turn_end` / `mark_gain` / `mark_lose` / `on_attack` / `on_hit` / `on_skill`） | 永不触发 | **⚠️ 静默通过（无提示）** | **只能查 §2.2 三态表** |
| `trigger` 非字符串（如数字） | 永不触发 | **R-1 红拦**（整包拒绝） | 看校验输出 |
| `trigger` 缺省 / 空串 | 走主动作/状态链路（非事件型） | 放行 | — |

**结论**：**第 3 行是本框架最危险的一类**——校验器只能判"枚举里有没有"，判不了"有没有人派发"。**唯一可靠的判据是本章 §2.2 的三态表**。

### 3.6 未登记的未来时点（框架预留的扩展位）

以下时点**尚未进入 `EVENT_POINTS`**，属于"未来扩展位"素材。**它们连枚举都没有**，所以写了会命中 **Y-19 黄提示**（比 `turn_end` 那种静默死效果更安全）：

| 未来时点 | 依据 | 说明 |
|---|---|---|
| `on_struck` / `on_block` / `on_crit` / `on_interrupt` / `on_cc` / `on_synergy` | `docs/深度打造_实现说明.md:794-796` | 各自**需要新派发点 = 行为改动**，须单独批次测量 |
| `on_tick` | `core/event_dispatcher.py:30` | 注明"二期收编，**本期不接**" |

**给维护者**：新增这些时点**不是**加一个枚举值就完事——必须同时（a）加枚举、（b）加生产派发点、（c）评估数值影响、（d）走批次评审。步骤见 §9.1。

**另一套同名不同物的清单（勿混）**：`qbot_rpg/content/resource_axis_validator.py:99` 里有 `PROC_TRIGGER_EVENTS = ("on_turn_start", "on_hit", "on_season_change")`——这是**资源轴 proc 的触发时点词表**，命名风格类似但**与 `EVENT_POINTS` 不是同一个值域**（注意它写的是 `on_turn_start` 而不是 `turn_start`）。标 **待查 P-3**：需确认这两套是否有意统一。

---

## 4. 归属（owner）规则："谁的效果只能由谁触发"

### 4.1 这是什么 / 解决什么问题

**问题**：`effects.json` 里的效果带 `trigger` 字段。如果某玩家装备了一件"开战时给我加速"的装备，**敌人开战时也会触发它**——因为分派器默认**全库扫描**所有带该 `trigger` 的效果。这在 1v1 里就是"装备被动串场"。

**批51 的解法**：引入**归属作用域**——装配层把"本侧拥有哪些效果 id"写进 combatant 的 `owned_effect_ids`；分派时按它过滤。

### 4.2 归属数据链路（谁写、谁读）

| 环节 | file:line | 说明 |
|---|---|---|
| 归属键常量 【稳定契约】 | `qbot_rpg/data/gear_stats.py:491` | `OWNED_EFFECT_IDS_KEY = "owned_effect_ids"` |
| 装配层计算"穿戴者的被动效果 id 集" | `qbot_rpg/core/equip_mods.py:319` | `worn_passive_effect_ids(ctx, player)` → 装备实例 `passives` → traits `effects` → id 集 |
| 写进 combatant | 装配 → `combatant["owned_effect_ids"]` | 随快照往返，续战不丢 |
| 战斗侧读取 | `qbot_rpg/core/battle.py:2090` `_owned_effect_ids(side)` | 键缺省 / 值畸形 → `None`（**不启用过滤**）；键存在（含空列表）→ 返回 id 列表 |
| 作用域计算 | `qbot_rpg/core/battle.py:2067` `_owner_scope(side)` | → `(owner_effect_ids, claimed_effect_ids)` |
| 传入分派器 | `qbot_rpg/core/battle.py:2055-2057` | `opts = {"owner_effect_ids": owner, "claimed_effect_ids": claimed}` |
| 实际过滤 | `qbot_rpg/core/event_dispatcher.py:144-151` | 判定式见 §4.4 |

**谁负责**：**装配层**写归属键、**战斗层**读并过滤、**内容包不写这个键**（包只写装备的 `passives` / traits 的 `effects`，由框架推导 id 集）。

### 4.3 三态判定表（**零变化口径**是这张表的灵魂）

| 本场战斗的情况 | `_owner_scope` 返回 | 引擎行为 | 对既有内容的影响 |
|---|---|---|---|
| **两侧都没声明** `owned_effect_ids` | `(None, None)` | **全库扫描**所有带该 `trigger` 的效果 | **逐字段零变化**——即"本机制引入前"的旧行为 |
| **任一侧声明了** | `(自己的 id 列表, 两侧并集)` | 该侧候选 = **自己拥有的** ∪ **未被任何一侧认领的**（全局效果） | 只有"被认领的效果"开始受限；**全局效果照常触发** |
| 某侧声明了但值是**空列表** | `([], 并集)` | **该侧零候选**（不含任何 owned；仅剩全局效果） | 明确的"我什么都不拥有" |

**为什么要有"全局效果"豁免**（`event_dispatcher.py:100-102`）：如果只用 `owner` 白名单，那么**未被任何一侧认领**的效果（框架内置的、或没写进装备 `passives` 的）会被静默吞掉——那是"登记了不生效 = 陷阱"的同族风险。所以判定式刻意写成 `eid ∈ owner` **或** `eid ∉ claimed`。

**为什么这是"勿当 bug 修"**（维护者注意）：
- 改 `_owner_scope` 让"缺省也启用过滤" = **打破零变化承诺**，会让既有包的效果集体失效。
- 改判定式为纯白名单 = **静默吞掉全局效果**。
- 两者都会让"旧内容包升级后行为变化"，属 **误修**。

### 4.4 判定式与代码

`event_dispatcher.py:144-151`：
```python
owner   = None if owner_effect_ids   is None else {str(x) for x in owner_effect_ids}
claimed = None if claimed_effect_ids is None else {str(x) for x in claimed_effect_ids}
for eid in all_ids("effect"):
    if owner is not None or claimed is not None:
        sid = str(eid)
        if not ((owner is not None and sid in owner)
                or (claimed is not None and sid not in claimed)):
            continue
    ...
```

判定式：**`eid ∈ owner` 或 `eid ∉ claimed`**（`claimed=None` 视为无全局豁免）。
- 归属键用的是 **effects 定义的注册 id**（`all_ids("effect")` 的键）。
- 状态事件分支**不受**这两个参数影响（`event_dispatcher.py:104-105`，见 §2.5）。

### 4.5 符文候选（`extra_candidates`）—— 另一条"只对持侧生效"的路

符文效果**不走归属过滤**，而是走**追加候选**通道：

| 环节 | file:line | 说明 |
|---|---|---|
| 数据源 | combatant 的 `rune_effects`（装配层经 `core/rune_battle.active_rune_effect_refs` 从激活孔位收集；键随快照往返） | |
| 候选生成 | `qbot_rpg/core/battle.py:2107` `_rune_candidates(event, side)` | 只取 `trigger == event` 的引用；动作语义仍由 effects 注册表定义 |
| 合并 | `qbot_rpg/core/battle.py:2062` → `dispatch_event(..., extra_candidates=...)` | 与全局候选**合并同批执行** |
| 追加逻辑 | `qbot_rpg/core/event_dispatcher.py:296-300` | 只接受"3 元组"形态的候选 |

**为什么单独一条路**（`event_dispatcher.py:273-281`）：`extra_candidates` **已由调用方按持侧自过滤**，所以归属参数**对它不生效**——符文挂在穿戴者身上，天然只对该侧生效。

**工程细节（勿改）**：符文施加来源按次区分为 `"{side}@{action_seq}"`（`battle.py:2138`），让"每次攻击获得物攻加成"的 S3 叠层框架**真正逐次叠层**——注释明写"**不改 `apply_status` 行为**"。ref 自带 `source` 时以声明为准。

### 4.6 去重 / 上限 / chance —— 全部复用 `EffectRuntime`，不另造

| 机制 | 位置 | 语义 |
|---|---|---|
| 每回合上限 | `event_dispatcher.py:200-204` | `max_triggers_per_turn`（缺省 10） |
| 每场上限 | 同上 | `max_triggers_per_battle`（缺省 99） |
| 递归深度 | `:205-208` | `chain_depth`（缺省 3）——防 `on_hit`→反伤→`on_hit` 无限 |
| chance 三态 | `:209-216` | `-1` 必定 / `0-100` 固定 / `lucky`；复用 `effects._chance_roll`；求值异常 → **不触发** |
| 计数写回 | `:237-242` | 仅 `res.ok` 时 `increment_trigger`（per_turn + per_battle）；计数异常不阻断结果 |

**设计口径**（`event_dispatcher.py:21-24`）：这些语义**全部复用 `effects.EffectRuntime` 既有实现**，事件分派器**不另造一套**。改上限/深度请改 `EffectRuntime` 的 config 口径，不要在分派器里加平行机制。

---

## 5. 扩展点契约：E1 / E2 / E3

### 5.1 总览：包能把代码接到哪三个位置

| 入口 | 你写什么文件 | 框架从哪装载 | 要在 `manifest.modules` 声明吗 | 双闸 |
|---|---|---|---|---|
| **E1 指令** | `content/<包>/commands.json`（声明）+ `content/<包>/ext/commands.py`（实现） | `load_pack_extensions()` @ `qbot_rpg/assembly/pack_ext.py:481`；生产接线 `qbot_rpg_bridge/assemble.py:181` | **否**（独立于 `manifest.modules`） | ✅ 要 |
| **E2a 渲染钩子** | `content/<包>/ext/render.py` | `load_pack_render_hook()` @ `qbot_rpg/assembly/pack_render.py:319`；生产接线 `assemble.py:185` | **否** | ✅ 要 |
| **E2b 文案模板覆盖** | `content/<包>/templates.json` | `resolve_templates()` @ `qbot_rpg/core/templates/__init__.py:101`；经 `assembly/context.py:737` | **✅ 是**（不声明 `templates` 模块则**静默不加载**） | 否 |
| **E3a 包内测试** | `content/<包>/tests/` | `scripts/run_pack_tests.py:168` → pytest + `qbot_rpg/testing/pytest_plugin.py` | 否 | 否 |
| **E3b 包内构建** | `content/<包>/scripts/build.py` | `scripts/run_pack_build.py:99`（入口常量 `:39`） | 否 | 否 |
| **包自持校验扩展** | `settings.json` 的 `schema_ext` 段 | `validator.py:429` `_parse_schema_ext`；接线 `:543-549` | 否（在 settings 内） | 否 |
| **包展示元数据** | `content/<包>/field_meta.json` | `load_field_meta()` @ `qbot_rpg/content/field_meta_pack.py:783`；消费 `web/api.py:242` | 否（**不参与运行时**） | 否 |

**可照抄的实证包**：`content/zz_probe_ext/`（E1+E2+E3 全量探针）、`content/zz_probe_packmeta/`（声明段/展示元数据探针）、`content/veinborn/`（真实大包）。

### 5.2 E1：包自定义指令

#### 5.2.1 这是什么 / 什么时候用 / 谁负责

- **这是什么**：让内容包注册**自己的聊天指令**（如"探针"、"献祭"），走框架既有的指令路由与权限体系。
- **什么时候用**：你的包需要一个只有它才有的入口指令时。
- **谁负责**：包负责**声明 + 实现**；框架负责**装载、权限、重名拦截、失败隔离**。包**不得**碰结算/数值（见 §6.4）。

#### 5.2.2 声明形状（`commands.json`）

固定文件名 `DECL_FILE = "commands.json"`（`pack_ext.py:69`）。顶层形态 `{"commands": [ … ]}`，`parse_declarations()` @ `pack_ext.py:304`。

**单条声明允许的键 = 闭集** `_ALLOWED_KEYS` @ `pack_ext.py:81`：`{name, aliases, usage, help, handler, gm_only}`。**未知字段 = 拼错，直接报错拒绝**（`_validate_one` @ `:251`，防静默失效）。

| 字段 | 类型 | 必填 | 约束 |
|---|---|---|---|
| `name` | str | ✅ | 非空、无空白、无 `/`（`_is_token` @ `:240`） |
| `handler` | str | ✅ | 合法 Python 标识符，且实现文件里**必须存在同名可调用对象**（`:600-603`） |
| `aliases` | str[] | ❌ | 每项同 `name` 约束 |
| `usage` | str | ❌ | 必须字符串 |
| `help` | str | ❌ | 必须字符串 |
| `gm_only` | bool | ❌ | 必须布尔；`true` → `PERM_GM`，否则 `PERM_USER`（`:618`） |

#### 5.2.3 最小示例（可直接抄）

`content/zz_probe_ext/commands.json:1-12`（**仓库实测原文**）：
```json
{
  "commands": [
    {
      "name": "探针",
      "aliases": ["zzprobe"],
      "usage": "探针 [任意文字]",
      "help": "内容包扩展装载探针（验证用，无业务含义）",
      "handler": "probe",
      "gm_only": false
    }
  ]
}
```

`content/zz_probe_ext/ext/commands.py:1-21`（**只 import 稳定面**）：
```python
"""内容包扩展探针实现（E1 验证用）。"""
from __future__ import annotations

from qbot_rpg import ext_api          # ← 包代码唯一允许 import 的框架面


def probe(ctx, parsed):
    """探针指令：回显包 id / 玩家 id / 参数。"""
    lines = [
        f"【扩展探针】包={ctx.pack_id}",
        f"玩家={ctx.player_id or '未注册'}",
    ]
    if ctx.args:
        lines.append("参数=" + " ".join(ctx.args))
    lines.append(f"ext_api=v{ext_api.EXT_API_VERSION}")
    return "\n".join(lines)
```

#### 5.2.4 装载路径（一条线走完）

| 环节 | file:line |
|---|---|
| 常量：声明文件 / 实现目录 / 实现文件 | `pack_ext.py:69-71`（`commands.json` / `ext` / `commands.py`） |
| 双闸判定 | `pack_ext.py:513-520` → `pack_ext_enabled` @ `:148`（= `settings_enabled :115` **且** `resolve_cli_enabled :125`） |
| 声明路径解析（禁 `..` / 禁符号链接 / 必须在包内） | `_resolve_within` @ `:185`；`resolve_ext_file` @ `:216` |
| 读声明 | `_load_enabled` @ `:560`，读 `commands.json` @ `:570-580` |
| 冲突预检（对框架名/别名、包内自冲突） | `_check_conflicts` @ `:331`（调用 `:588`） |
| 动态 import 实现 | `import_ext_module` @ `:421`（调用 `:591`） |
| handler 齐备性预检 | `:599-603`（缺任一 → **整包拒绝**，避免半装） |
| 构造 `CommandSpec` + 权限 | `:606-620` |
| 原子注册 + 失败回滚 | `:622-646`（`router.register(spec)` @ `:630`，`unregister` @ `:643`） |
| handler 上下文适配（异常隔离） | `_make_handler` @ `:430` |

#### 5.2.5 约束（每条都是"别踩"）

| 约束 | 说明 | file:line |
|---|---|---|
| **双闸默认全关** | `settings.ext.enabled`（缺省 `false`）**且** `--enable-pack-ext` / `QBotRPG_ENABLE_PACK_EXT`，缺一不启用 | `pack_ext.py:115,125,148` |
| **未启用零文件访问** | 不读 `commands.json`、不 import 包内 Python。⚠️ **严格表述**：`pack_path = Path(pack_dir)` 在双闸判定**之前**执行（`:506`），但它只做 `Path()` 构造 + `.name` 取包名，**未 stat / 未 read** | `:506,513-520` |
| **重名一律拒绝** | 与框架指令/别名冲突、或包内自冲突 → **整包扩展降级不生效**；**不做** `replace=True` | `_check_conflicts:331`、`:630` |
| **路径安全** | 禁 `..`、禁符号链接、解析后必须在包目录内；只允许固定文件名 | `_resolve_within:185`、`resolve_ext_file:216` |
| **失败隔离** | 声明非法 / 路径非法 / import 失败 / handler 异常 **均不抛到顶层**；`load_pack_extensions` **承诺不抛**。handler 异常 → 回退模板键 `ext_command_unavailable`（`:78`） | `:481`、`:499-534` |
| **不热加载** | 装载只在装配期发生一次，运行期不重载 | `ext_api.py:11-20` |
| **不跨包互调** | 包扩展代码不得调用另一个包 | 同上 |
| **不改结算** | 包 handler **不得**改数值/状态（只读包装 + 自己的状态格子） | 同上 |
| **分隔符沿用框架** | 包指令进既有 `Router`，用框架指令解析器的全部分隔符/前缀模式（**无包专属分隔符**）；`CommandSpec(..., whitelisted=True)` @ `:616`，故**无需**改 `parsers.DEFAULT_WHITELIST` | `:616` |
| **帮助自动列出** | 注册进 Router，帮助动态列出（`assembly/context.py` 注入 `registered_cmds`） | — |

### 5.3 E2a：渲染钩子（`ext/render.py`）

#### 5.3.1 这是什么 / 什么时候用

- **这是什么**：让包**改写玩家可见的最终文本**（指令回复、战斗正文）。
- **什么时候用**：你的包需要给回复加后缀、改写措辞、按包风格渲染时。
- **谁负责**：框架负责**调用时机、超时、异常兜底**；包只提供**一个同步纯函数**，**只许换文本**。

#### 5.3.2 声明形状

固定文件名 `RENDER_FILE = "render.py"`（`pack_render.py:73`），放在 `ext/` 下。

```python
EVENTS = ("command.reply",)                 # 可选：事件白名单；缺省 = 全部已知事件
def render(event, data, default_text): ...  # 返回 None/"" = 用框架默认；返回 str = 替换
```

**已知事件（框架稳定名，只增不减）** @ `pack_render.py:83-85`：
- `command.reply`：一切经 runner sender 闭包发出的指令回复（指令返回、列表、面板…）；
- `battle.round`：战斗管线经 `ctx["sender"]` 直发的战斗正文（结算渲染）。

#### 5.3.3 最小示例（仓库实测原文）

`content/zz_probe_ext/ext/render.py:1-22`：
```python
"""内容包渲染钩子探针（E2 验证用）。"""
from __future__ import annotations

# 事件白名单：只接指令回复；未命中事件框架不会调用本函数。
EVENTS = ("command.reply",)

_SUFFIX = "（探针改写）"


def render(event, data, default_text):
    """``command.reply`` → 在框架最终文本后缀探针标记；其余 → ``None``（用默认）。"""
    if event != "command.reply":
        return None
    if not default_text:
        return None
    return f"{default_text}{_SUFFIX}"
```

#### 5.3.4 契约要点

| 契约项 | 说明 | file:line |
|---|---|---|
| **钩子拿到的是框架渲染好的最终文本** | **前缀注入之后**、`Sender.send` 之前 | `runner.py:894-905` |
| **返回 `str` = 替换；`None`/`""` = 用默认** | 唯一决策规则 | `pack_render.py:240` |
| **异常 / 超时 / 非 str → 落默认文本** | 进程不崩、不影响其它包 | `:240-266` |
| **软超时 0.5s，不做线程抢占** | 调用返回后核对耗时，超预算即丢弃改写。仓库铁律「零定时器」禁止线程计时 → **钩子必须自己快速返回，禁止 sleep / 网络 / 长任务** | `:75-80`、`_invoke :222` |
| **`data` 是递归只读快照** | 每层都是新建只读容器，嵌套可变对象转元组/冻结；**不含** ctx / Player / 引擎 / repo / db / sender 等**任何活对象** | `build_render_data :134`、`:146-158` |
| **`battle.round` 出口仅当声明该事件才代理** | 未声明 → 不套 `RenderSender`，零改动 | `runner.py:845-852`、`RenderSender :410` |
| **事件白名单：未知事件警告 + 忽略；形态非法 → 整包不装** | `_parse_events :289` | `:289-313` |
| **双闸与 E1 完全一致** | 未启用 → 零文件访问，不读 `ext/render.py`、不 import 包内 Python | `pack_render.py:370-404` |
| **钩子不得写库/写存档/发起新指令** | 本面**不提供**任何此类能力 | `pack_render.py:12-22` |

### 5.4 E2b：文案模板覆盖（`templates.json`）

#### 5.4.1 这是什么 / 与 E2a 的区别

E2a 是**用代码改写文本**；E2b 是**用数据替换模板串**。E2b 更简单、更安全（纯数据、不执行代码），**优先选它**。

- **全量表唯一源**：`qbot_rpg/core/templates/template_table.json`（由 `core/templates/__init__.py:46-81` 加载进 `DEFAULT_TEMPLATES` @ `:38`）。
- **覆盖入口**：`resolve_templates(content_overrides, *, strict=False)` @ `core/templates/__init__.py:101`。
- **渲染统一入口**：`render_template` @ `:128`；`tpl_of(ctx, key, data)` @ `:144`（局部覆盖缺 key 回落默认表）。
- **运行时兜底**：`ext_api.tpl` @ `ext_api.py:113`；`ExtContext.tpl` @ `ExtContext`。

#### 5.4.2 最小示例

`content/<包>/templates.json`：
```json
{
  "battle_win": "【{name}】击败了 {enemy}，拾得 {drop}。",
  "checkin_ok": "签到成功，第 {days} 天。"
}
```
包 `manifest.json` **必须**声明（否则静默不加载）：
```json
{ "name": "我的包", "version": "1.0.0", "schema_version": 1,
  "modules": ["items", "effects", "templates"] }
```

#### 5.4.3 三个必须知道的约束

| 约束 | 说明 | file:line |
|---|---|---|
| **⚠️ 必须声明 `templates` 模块** | `templates.json` **只有在该包 `manifest.modules` 声明了 `templates` 模块时才被 loader 加载**；否则**静默不生效** | `loader.py:286-311` |
| **只合并已存在 key** | 未知 key → 逐键 warning；运行时 `strict=False`（不抛），`strict=True` 抛错 | `core/templates/__init__.py:101-125` |
| **覆盖是逐 key 整体替换，不是深合并** | ⚠️ 文档注释写"深合并"，**实现是逐 key 整体替换**（值为字符串，无嵌套合并语义）。这是**注释与实现不一致**（盘点已列，本次复核确认），**以实现为准** | `core/templates/__init__.py:102` vs `:113-119` |

**模块登记**：`field_meta.py:3435-3442`（`ModuleMeta(entry_type="map", kind="templates", namespace="template_lib", key_source="templates")`）。

**目录澄清（易踩坑）**：`qbot_rpg/core/message_format/`（`battle_render.py` / `list_render.py` / `panel_render.py` / `prefix_render.py`）是**框架渲染器实现**，**不是**可覆盖目录；渲染器统一经 `tpl_of(ctx, …)` 读模板。

### 5.5 E3：包内测试与构建

#### 5.5.1 E3a 包内测试 `content/<包>/tests/`

| 环节 | file:line |
|---|---|
| 测试目录发现 | `scripts/run_pack_tests.py:168`（`tests_dir = pack_dir / "tests"`；`is_dir()` 检查 `:169`） |
| pytest 命令构造（**显式只收该包 tests/**） | `:73-101`（`--rootdir`、`-c pytest.ini`、`-p qbot_rpg.testing.pytest_plugin`、`--pack-root`） |
| 主入口 `run_pack_tests` | `:141-200`（**先 collect 取数，再真跑取退出码**） |
| CLI `main` | `:221`（`--pack` / `--content-root` / `--` 透传） |
| pytest 插件 `--pack-root` | `qbot_rpg/testing/pytest_plugin.py:27-36`；`pack_root` fixture `:39-52`；`pack_deps` fixture `:55-62` |
| 框架测试辅助公开面 | `qbot_rpg/testing/__init__.py`（`pack_root_from` / `pack_app` / `send_command` / `load_pack_ext` / `load_pack_render` / `validate_pack_data`） |
| 辅助实现 | `qbot_rpg/assembly/testing_support.py`（`pack_root_from :78`，`MANIFEST_FILE :69`，E1/E2 接线 `:218-221`） |

**隔离保证**：主套件 `pytest.ini:3`（`testpaths = tests`）**不会自动收集**包测试；`run_pack_tests.py` 显式只收该包 `tests/`，并设 `PYTHONDONTWRITEBYTECODE=1` / 关 `cacheprovider`。

**最小示例**：`content/zz_probe_ext/tests/test_probe_ext.py:1-48`（48 行）。

#### 5.5.2 E3b 包内构建 `content/<包>/scripts/build.py`

| 环节 | file:line |
|---|---|
| 构建入口固定名 | `scripts/run_pack_build.py:39`（`BUILD_ENTRY = "build.py"`） |
| 入口路径拼接 | `:99`（`pack_dir / "scripts" / BUILD_ENTRY`）；缺失 → 报错 `:104` |
| 主入口 `run_pack_build` | `:73`（cwd = 包目录、`PYTHONPATH` 含仓库根、退出码**如实转发**） |
| CLI | `:133`（`--pack` / `--content-root` / `--check` / `--` 透传） |

**最小示例**：`content/zz_probe_ext/scripts/build.py`（`--check` 只读校验 manifest / 数据模块 / `commands.json` handler 齐备 + 复用框架整包校验）。

**⚠️ 文档精度提示（勿当 bug 修）**：方案 E 文档在 `docs/游戏包扩展点_方案_E.md:49` **已**写明 `content/<pack>/scripts/` 这一层级；但紧接着的 `:50` 只说"框架只认**入口约定**（如 `build.py --check`）"，**未在该句里点明入口位于 `scripts/` 下**。**本次复核澄清**：入口 = `content/<包>/scripts/build.py`（`run_pack_build.py:39` + `:99`）——**以实现为准**；这是表述精度问题，不是代码错。

### 5.6 包自持校验扩展（`settings.schema_ext`）

- **这是什么**：包给**自己的自定义模块**声明额外的**字段校验**（允许键并集 + 最小约束子集）。
- **什么时候用**：你的包有自定义模块（如 `zz_probe_ext_data.json`），想让框架校验器帮忙检查它的字段。
- **形状**：`schema_ext.<module>.<field-path>.allow_keys = {key: constraint}`（`validator.py:390-402`）。
- **解析**：`_parse_schema_ext` @ `validator.py:429`；接线 `:543-549`。
- **约束子集**：`type` 取值限白名单（表达式 / 引用 / 自定义算子属**第二层 ext 算子**，**不在此**，`:399`）。
- **失败行为**：形状/取值非法 → **记 issue 且跳过**（不静默放行）；`schema_ext` 缺失/空 → `({}, [])`。
- **⚠️ 文档缺口**：`schema_ext` 在方案 E 文档中**未提及**（属"批71·D1"代码内能力）。**它以代码与本节为唯一说明源**。

### 5.7 扩展点复用的安全口径（总结表）

| 安全线 | E1 | E2a | E2b | E3 |
|---|---|---|---|---|
| 双闸默认关 | ✅ | ✅ | ❌（loader 按 manifest 加载） | ❌ |
| 未启用零文件访问 | ✅ | ✅ | — | — |
| 重名/未知事件拒绝 | ✅ 整包拒绝 | ✅ 未知事件忽略 | ❌ 未知 key warning | — |
| 异常不崩服 | ✅ | ✅ 落默认文本 | — | — |
| 路径安全（禁 `..`/符号链接） | ✅ | ✅ | — | — |
| 包能改结算吗 | ❌ | ❌（只读快照 + 只换文本） | ❌（只换文案） | — |

---

## 6. 稳定面 `qbot_rpg.ext_api`：包代码唯一允许 `import` 的框架面

### 6.1 这是什么 / 为什么这么严

包内的扩展代码（`content/<包>/ext/*.py`）**只许 `import qbot_rpg.ext_api`**（或 `from qbot_rpg import ext_api`）。

**判据（`ext_api.py:1-11`）**：
> 本模块导出的名字在 E 方案的 **major 版本内承诺兼容**（`EXT_API_VERSION` 随框架 major 递增）。
> **`qbot_rpg.*` 的其余部分（含子模块、私有名、函数签名）都是内部实现，不承诺兼容**；包扩展代码直接 import 其它 `qbot_rpg.*` 属于**越界**，框架升级**不负责其不破坏**。

**给维护者**：这条边界是**双向**的——你改 `ext_api` 的导出名/签名 = 破坏包；你改 `qbot_rpg` 内部任意模块 = **不构成**破坏包（因为包本来就不该 import 它）。**所以内部重构时不要再为"怕破坏包"而加兼容层**。

### 6.2 `EXT_API_VERSION` 机制

| 项 | file:line | 说明 |
|---|---|---|
| 版本常量 【稳定契约】 | `ext_api.py:59` | `EXT_API_VERSION = "1"` |
| 导出清单 `__all__` | `:42-56` | 12 个名字，见下表 |
| 兼容承诺 | `:6` | "随框架 major 递增；**破坏性变更必须递增**" |

**版本语义（给外部开发者）**：
- `EXT_API_VERSION` 是**字符串**（当前 `"1"`），与**框架 major 同轨**。
- **同一 major 内**（如都是 `"1"`）：`__all__` 里的名字**承诺兼容**——你可以放心 `import`。
- **major 递增**（`"1"` → `"2"`）：**允许破坏性变更**。你的包代码应**显式检查**：
  ```python
  from qbot_rpg import ext_api
  if ext_api.EXT_API_VERSION != "1":
      return "本扩展需要 ext_api v1，当前框架为 v" + ext_api.EXT_API_VERSION
  ```
- **实测**：`content/zz_probe_ext/ext/commands.py:20` 就把 `ext_api.EXT_API_VERSION` 回显出来——这是**推荐的版本自检范式**。

**注意**：`ext_api` **没有**"未知名拒绝"之外的保护机制；`ext_api.py:307-312` 对未知名**拒绝**（属 `ExtApiError` 家族）。

### 6.3 `__all__` 导出清单（12 个名字）

| 名字 | 用途 | file:line |
|---|---|---|
| `EXT_API_VERSION` | 版本自检 | `:59` |
| `ExtApiError` | 扩展层可预期错误基类（你可抛/可捕） | `:62` |
| `ExtApiUnavailable` | 依赖不可用（未注入存档 / 玩家未注册 / 状态格子不可写） | `:66` |
| `ExtContext` | handler 的 `ctx` 类型（`pack_id` / `player_id` / `args` / `tpl` / `log` / 状态格子…） | `:125`；`ctx.tpl` `:257`；`ctx.rng` `:262` |
| `log` | 扩展默认日志器（`content.ext`；建议用 `ctx.log` 拿带包 id 的子日志器） | `:71` |
| `rng` | 确定性随机源（按 `包+玩家` 播种）——**不要**自己 `import random` | 模块级 `:103` |
| `tpl` | 取模板文本（`tpl(key, data)`；缺 key 回落框架默认表） | `:113` |
| `get_pack_state` | 读本包 × 本玩家的状态格子 | `:42-56` |
| `set_pack_state` | 写 | 同上 |
| `patch_pack_state` | 局部改 | 同上 |
| `clear_pack_state` | 清 | 同上 |
| `list_pack_states` | 列 | 同上 |

### 6.4 能力边界（**明确"包不能做什么"**）

照 `docs/游戏包扩展点_方案_E.md` §三·装载安全·4（转述于 `ext_api.py:11-15`）：

| 不得 | 说明 |
|---|---|
| ❌ 网络 | 本面不提供 |
| ❌ 子进程 | 本面不提供 |
| ❌ 任意文件系统读写 | 本面不提供（只有"该包自己的状态格子"可持久化） |
| ❌ 热加载 | 不提供 |
| ❌ 跨包互调 | 不提供 |
| ❌ 改结算 / 改数值 / 改框架状态 | 读入口一律是**只读包装**（`player` / `settings` / `templates` 为只读映射） |

**包可持久化的唯一东西**：**该包自己的状态格子**（复用批 D `player_pack_state`），玩家维度隔离——`async get_state / set_state / patch_state / clear_state`。

**失败隔离承诺（给包作者的反向提醒）**（`ext_api.py:19-22`）：扩展代码抛出的异常由框架装载层兜底（记日志 + 返回"该功能暂不可用"人话提示，进程不崩）。**但扩展作者不应依赖异常静默**——请自行捕获可预期错误并返回人见文本。

**包状态格子上下文**：`ExtContext.get_state/set_state/patch_state/clear_state` @ `ext_api.py:283/291/296/301`。

---

## 7. 包声明段全表

### 7.1 先说清"93 条"是什么口径（重要）

上游盘点给的 "93 条" = **盘点表格的行数**：`manifest 9 + settings 41 + 模块 json 30 + field_meta.json 12 + commands.json 1 = 93`。

**但行数 ≠ 键数**。盘点为了表格紧凑，把若干同族键合并成一行（例如 `field_labels / field_help` 合成一行）。本次**逐条复核实测**：

| 分组 | 盘点行数 | 本次实测 | 差异原因 |
|---|---|---|---|
| `manifest.json` | 9 | **8 个声明字段 + `raw`** = 9 | 一致（8 个 schema 字段见 `field_meta.py:2155-2166`，`raw` 见 `models.py:748`） |
| `settings.json` | 41 | **框架 schema 54 段** | 盘点漏列 14 段（见 §7.3 标注"**＋本次补**"的行）；另盘点含 3 个**不在 schema 内**的段（`ext` / `schema_ext` / `worldtime`）与 1 个已废弃嵌套键（`forge.decompose_rate`） |
| 各模块 json | 30 | 模块表 **36 条目** = **29 个数据模块** + 7 个非数据条目（`manifest`/`settings`/`ai`/`hidden`/`env_event`/`log_card`/`editor`）；再加**不在模块表里**的 `commands.json` → **30 行** | 非数据条目的 `ai`/`hidden`/`env_event`/`log_card` 见 `docs/死代码删除登记表.md` §5「空视图·保留」 |
| `field_meta.json` | 12 | **16 个顶层键** | 盘点把 4 组同族键合并成行 |
| `commands.json` | 1 | 1 | 一致 |

**怎么用这张表**：按**段名**查（行数口径不影响你查段）。**要数总数时用"本次实测"列**。

### 7.2 `manifest.json`（包清单，每包必有）

**读取/校验链**：`loader.py:259`（文件定位）→ `:266`（JSON 解析）→ `:282`（`Manifest.from_dict`）→ `:286-311`（按 `modules` 声明加载）。校验时把 `manifest` 当受检模块（`validator.py:590-591`）。框架 schema 唯一源：`field_meta.py:2155-2166`（字段表）+ `:3239-3242`（`ModuleMeta`）。

| # | 段名 | 用途 | 唯一源 file:line | 谁读它 | 可否被包覆盖 | 示例 |
|---|---|---|---|---|---|---|
| 1 | `name` | 包显示名 | `field_meta.py:2155`；`models.py:743` | `loader.py:282` → `models.py:737-749` | 包自声明（该文件即包） | `"name": "内容包扩展探针（验证用）"` |
| 2 | `version` | 包版本（供 `ctx.pack_version`） | `field_meta.py:2156`；`models.py:744` | `models.py:737-749`；`pack_ext.py:467-475` | 包自声明 | `"version": "0.0.1"` |
| 3 | `schema_version` | 数据 schema 版本 | `field_meta.py:2157`；`models.py:740-741` | `models.py:737-749`；`registry.py:209` | 包自声明 | `"schema_version": 1` |
| 4 | `author` | 作者 | `field_meta.py:2158`；`models.py:746` | `models.py:737-749` | 包自声明 | `"author": "e1-pack-ext"` |
| 5 | `modules` | **启用模块清单**（= `<module>.json` 文件名去后缀）**决定 loader 加载哪些文件** | `field_meta.py:2159`；`models.py:738-739` | `loader.py:286-311` | 包自声明（换包零改动） | `"modules": ["settings","stats","formula","effects","items","zz_probe_ext_data"]` |
| 6 | `module_tree` | 模块层级（编辑器左栏父子关系） | `field_meta.py:2162` | `field_meta_pack.py:715`、`:287`；`web/api.py:300` | ✅ 可被 `field_meta.json.module_tree` **整体覆盖**（`field_meta_pack.py:35-37`） | `"module_tree": [{"module":"items","children":["equipment"]}]` |
| 7 | `module_groups` | `module_tree` 的**别名**（兼容键） | `field_meta.py:2164` | 同上 | ✅ 同 `module_tree` | `"module_groups": [...]` |
| 8 | `module_labels` | 模块中文名 | `field_meta.py:2166` | `field_meta_pack.py:713`；`web/api.py` | ✅ 可被 `field_meta.json.module_labels` **逐键覆盖** | `"module_labels": {"zz_probe_ext_data": "扩展探针数据"}` |
| 9 | `raw`（扩展） | 原样保留整份 manifest | `models.py:734,748` | `registry.modules_raw["manifest"]`（`loader.py:314`） | 包自声明 | — |

**⚠️ 关键约束**：`manifest.modules` 里**没写**的模块文件，loader **不会加载**（`loader.py:286-311`）。声明了但文件缺失 → **Y-6 黄提示**并继续。**这就是 `templates.json` 必须声明才生效的根因**（§5.4.3）。

### 7.3 `settings.json`（包设置）

#### 7.3.1 ⚠️ 双通道读取（本框架最需要知道的例外）

| 通道 | file:line | 行为 |
|---|---|---|
| ① 作为**普通模块**被 loader 加载/校验 | `loader.py:286-311` | **前提**：`manifest.modules` 含 `settings`。含 → 受 `check_pack` 全量校验 |
| ② **无视 manifest 直接读** | `qbot_rpg_bridge/assemble.py:89-98`（`_load_settings`） | **无条件**读 `settings.json` → 注入 `deps.settings` / `ctx["settings"]`，**不经校验** |

**后果**：某包若 **没**在 `manifest.modules` 里声明 `settings`，`settings.json` **运行时仍生效，但绕过校验**。**这是"声明了才生效"这条规则的唯一例外**，属已知缺口（盘点归入"无单一源"）。**实测**：`content/zz_probe_packmeta` 就是这种包（3 个模块且无 `settings`）。

#### 7.3.2 全段表（实测 54 段）

**框架 schema 唯一源**：`SETTINGS_FIELDS` @ `field_meta.py:378-746`（基础段）+ `SETTINGS_FIELDS[...]=` / `SETTINGS_FIELDS.update({...})` @ `:3047-3236`（专项段与软段）。校验分派：`validator.py:864-898`（`_check_settings_1g4` @ `:1884` + 各专项）。

> **"盘点"列**：✅ = 盘点 §4 已收录；**＋补** = 本次复核新补（盘点漏列）。

| # | 段名 | 用途 | 唯一源 file:line | 谁读它（file:line） | 可否被包覆盖 | 示例 | 盘点 |
|---|---|---|---|---|---|---|---|
| 1 | `default_map` | 默认地图 | `field_meta.py:381` | `assembly/context.py:1396`；`register_commands.py:277` | 包配置 | `"default_map": "town"` | ✅ |
| 2 | `world_name` | 世界名 | `field_meta.py:382` | `register_commands.py:371` | 包配置 | `"world_name": "云海"` | ✅ |
| 3 | `currencies` | 货币定义表 | `field_meta.py:383` | `validator.py:1905`；`alchemy_commands.py:448` | 包配置 | `"currencies":[{"id":"coins","name":"金币","cap":999999}]` | ✅ |
| 4 | `death_penalty` | 死亡惩罚 | `field_meta.py:384` | `world/battle_boundary.py:356`；`battle_commands.py:1370` | 包配置 | `"death_penalty":{"drop_exp":{"enabled":true,"percent":10}}` | ✅ |
| 5 | `slot_defs` | 装备部位定义 | `field_meta.py:392` | `context.py:1862`；`alchemy_commands.py:2090`；`core/jewel.py` | 包配置 | `"slot_defs":{"weapon":{"name":"武器","max":1,"role":"main"}}` | ✅ |
| 6 | `equipment_offhand` | 副手装备开关 | `field_meta.py:407` | `context.py:1865-1867`；`basic_commands.py:1496` | 包配置 | `"equipment_offhand":{"enabled":true,"single_hand_scale":0.5}` | ✅ |
| 7 | `panel_budget` | 装备面板预算 | `field_meta.py:424` | `context.py:1870-1872`；`core/panel_budget.py:90` | 包配置（缺省不注入） | `"panel_budget":{"white":7,"equip":8,"buff":5,"equip_stat_mult":1.0}` | ✅ |
| 8 | `effect_budget` | 特效强度预算 | `field_meta.py:447` | `data/gear_stats.py:152`；`validator.py:2167` | 包配置 | `"effect_budget":{"enabled":false,"gate_mode":"warn"}` | ✅ |
| 9 | `overheal` | 过量治疗 | `field_meta.py:505` | `validator.py:2459`；`data/gear_stats.py` | 包配置 | `"overheal":{"enabled":true,"mode":"keep","cap_pct":50}` | ✅ |
| 10 | `effect_axes` | 特效轴逐轴声明 | `field_meta.py:532` | `context.py:1879-1881`；`gear_stats.py:477` | 包配置（覆盖 min/max） | `"effect_axes":{"crit_damage_pct":{"min":-100,"max":300}}` | ✅ |
| 11 | `monster_scaling` | 怪物数值倍率 | `field_meta.py:570` | `context.py:1874-1876`；`panel_budget.py:91` | 包配置 | `"monster_scaling":{"hp_mult":1.5,"atk_mult":1.5}` | ✅ |
| 12 | `deep_craft` | 深度打造 | `field_meta.py:594` | `alchemy_commands.py:1788`；`core/upgrade.py:144` | 包配置 | `"deep_craft":{"craft_rules":{...}}` | ✅ |
| 13 | `rune_sockets` | 符文孔位初值 | `field_meta.py:608` | `context.py:1571`；`data/runes.py:47`（`RUNES_STATE_KEY`） | 包配置 | `"rune_sockets":{"enabled":true}` | ＋补 |
| 14 | `affinities` | 相性定义 | `field_meta.py:618`（type=list） | `core/affinity.py`；`validator.py:3061-` | 包配置 | `"affinities":[{"key":"fire","name":"火"}]` | ✅ |
| 15 | `affinity_pools` | 相性池 | `field_meta.py:628` | `core/affinity.py:118`；`validator.py:2945` | 包配置 | `"affinity_pools":{...}` | ✅ |
| 16 | `affinity_linkage` | 相性联动 | `field_meta.py:651` | `core/affinity.py:131`；`validator.py:3176` | 包配置 | `"affinity_linkage":[...]` | ✅ |
| 17 | `affinity_reactions` | 相性反应 | `field_meta.py:659` | `core/affinity.py:133`；`alchemy_core.py:853` | 包配置 | `"affinity_reactions":[...]` | ✅ |
| 18 | `register_gift` | 新玩家注册礼包 | `field_meta.py:679` | `register_commands.py:313` | 包配置 | `"register_gift":[{"item":"potion","count":3}]` | ＋补 |
| 19 | `register_level` | 注册初始等级 | `field_meta.py:685` | `register_commands.py:295` | 包配置 | `"register_level": 1` | ＋补 |
| 20 | `command_gates` | 指令开放门控 | `field_meta.py:694` | `assembly/runner.py:357` | 包配置 | `"command_gates":{"battle":{"min_level":5}}` | ＋补 |
| 21 | `rate_limit` | 指令频率限制 | `field_meta.py:710` | `assembly/runner.py:219` | 包配置 | `"rate_limit":{"window":10,"max":5}` | ＋补 |
| 22 | `message_chunk_len` | 消息分段字节预算 | `field_meta.py:726` | `commands/sender.py:133,162`；`runner.py:192` | 包配置 | `"message_chunk_len": 800` | ✅ |
| 23 | `pack_protection` | 包防篡改/保护 | `field_meta.py:739` | `content/pack_protection.py:60` | 包配置 | `"pack_protection":{"enabled":false}` | ＋补 |
| 24 | `env_event` | 环境事件（settings 侧） | `field_meta.py:1224`（`setdefault`） | **⚠️ 无读取点** | 包配置（**填了不起作用**） | — | ＋补 |
| 25 | `log_card` | 日志卡片（settings 侧） | `field_meta.py:1228`（`setdefault`） | **⚠️ 无读取点** | 包配置（**填了不起作用**） | — | ＋补 |
| 26 | `alchemy` | 炼金/合成设置 | `field_meta.py:3047`；`content/alchemy_settings.py` | `alchemy_commands.py:491,500`；`validator.py:897-898` | 包配置 | `"alchemy":{"mode":"full","decompose_rate":0.3}` | ✅ |
| 27 | `forge` | 锻造设置 | `field_meta.py:3050`；`content/forge_settings.py` | `context.py`（`_forge_module_raw`→`ctx["forge"]`） | 包配置 | `"forge":{"mode":"full","temper":{...}}` | ✅ |
| 28 | `fishing` | 钓鱼设置 | `field_meta.py:3064`；`content/fishing_settings.py` | `content/fishing_models.py:271`；`fishing_commands.py:229` | 包配置 | `"fishing":{"mode":"full"}` | ✅ |
| 29 | `assistant` | 代工助手 | `field_meta.py:3069` | `core/alchemy_helper.py:212-217` | 包配置 | `"assistant":{"enabled":true}` | ✅ |
| 30 | `battle` | 战斗参数（`min_damage` 等） | `field_meta.py:3073`（`min_damage` `:3074`） | `core/battle_config.py:70`；`battle_launch_commands.py:501` | 包配置（**白名单键**） | `"battle":{"min_damage":10}` | ✅ |
| 31 | `command_aliases` | 指令别名 | `field_meta.py:3079`；`ALIAS_CONFIG_KEY` @ `:84` | `router_setup.py:274`；`runner.py:177`；`basic_commands.py:2499` | 包配置 | `"command_aliases":{"背包":["bag"]}` | ✅ |
| 32 | `contest` | 品评会配置 | `field_meta.py:3080` | `context.py:1475,1625` | 包配置 | `"contest":{...}` | ✅ |
| 33 | `ctb` | 行动条（CTB）参数 | `field_meta.py:3081` | `battle_launch_commands.py:491-493`；`core/ctb_config.resolve_ctb_settings` | 包配置 | `"ctb":{"base_speed":100}` | ✅ |
| 34 | `events` | 事件文案 / 事件键 name 段 | `field_meta.py:3082` | `core/event_bus.py:83`（`_events_section`）；`resolve_event_key` @ `:100` | 包配置（**只可配 name 段**，外壳硬编码） | `"events":{"签到":"每日签到"}` | ✅ |
| 35 | `exp_curve` | 经验曲线 | `field_meta.py:3083` | `context.py:468`；`core/battle_reward.py:372` | 包配置 | `"exp_curve":{"mode":"poly","base":100}` | ✅ |
| 36 | `level_cap` | 等级上限 | `field_meta.py:3084` | `context.py:467,1416`；`register_commands.py:298` | 包配置 | `"level_cap": 60` | ✅ |
| 37 | `quest_board` | 委托板配置 | `field_meta.py:3085` | `context.py:1473,1623`（`ctx["quest_board_cfg"]`） | 包配置 | `"quest_board":{"slots":5}` | ✅ |
| 38 | `time_cycle` | 时间天气 | `field_meta.py:3090` | `qbot_rpg_bridge/assemble.py:164-166`；`core/worldtime.py` | 包配置（桥梁装配读取） | `"time_cycle":{"season":{"season_days":7}}` | ✅ |
| 39 | `message_prefix` | 消息前缀 7 字段 | `field_meta.py:3129` | `commands/prefix_wiring.py:123`；`validator.py:3435` | 包配置 | `"message_prefix":{"enabled":true,"format":"[{level}]{name}"}` | ✅ |
| 40 | `pvp` | PVP 8 键 | `field_meta.py:3142`；`core/pvp.py:32`（`PVP_SETTINGS_KEYS`） | `core/pvp.py:62` | 包配置 | `"pvp":{"enabled":false,"mode":"turn_based"}` | ✅ |
| 41 | `post_battle_recovery` | 战后恢复 | `field_meta.py:3160` | `battle_commands.py:1270-1271`；`validator.py:1949` | 包配置 | `"post_battle_recovery":{"hp_pct":20}` | ✅ |
| 42 | `codex` | 图鉴设置 | `field_meta.py:3173` | `core/environment_lore.py:295`（`ctx["codex"]`） | 包配置 | `"codex":{"enabled":true}` | ＋补 |
| 43 | `event_log_cap` | 事件日志环形容量（**兼容键**） | `field_meta.py:3182` | `event_bus.py:182`（**兜底**，优先用 `event_log_capacity`）；`context.py:900` | 包配置 | `"event_log_cap": 300` | ＋补 |
| 44 | `event_log_capacity` | 同上（**优先键**） | `field_meta.py:3185` | `event_bus.py:182`（`for k in ("event_log_capacity","event_log_cap")`） | 包配置 | `"event_log_capacity": 300` | ＋补 |
| 45 | `command_mode` | 前缀模式 | `field_meta.py:3189` | `commands/parsers.py:83`；`router_setup.py:246-247` | 包配置 | `"command_mode": "prefix"` | ✅ |
| 46 | `require_at` | 是否要求 @ 机器人 | `field_meta.py:3195` | `router_setup.py:246-247` | 包配置 | `"require_at": true` | ✅ |
| 47 | `at_text` | @ 机器人的显示文本 | `field_meta.py:3198` | `commands/router.py:361`；`runner.py:187` | 包配置 | `"at_text": "@机器人"` | ＋补 |
| 48 | `attr_types` | 属性类型声明 | `field_meta.py:3202` | `context.py:1393-1394,1417-1418` | 包配置 | `"attr_types":{"str":"力量"}` | ✅ |
| 49 | `conditional_rules` | 条件加成规则 | `field_meta.py:3204` | `context.py:1393-1394` | 包配置 | `"conditional_rules":[...]` | ✅ |
| 50 | `imprints` | 印记展示 | `field_meta.py:3215` | `context.py:1419`；`status_commands.py:354-372` | 包配置 | `"imprints":{"surge_mark":"困斗"}` | ✅ |
| 51 | `shortcut_max` | 快捷上限 | `field_meta.py:3224` | `shortcut_commands.py:27,117`；`context.py:1470,1620` | 包配置 | `"shortcut_max": 20` | ✅ |
| 52 | `default_job_id` | 默认职业 | `field_meta.py:3227` | `register_commands.py:217` | 包配置 | `"default_job_id": "warrior"` | ＋补 |
| 53 | `max_dialog_depth` | NPC 对话最大深度 | `field_meta.py:3230` | `core/dialog.py:128`（`SETTINGS_MAX_DIALOG_DEPTH`）；`npc_models.py:610` | 包配置 | `"max_dialog_depth": 10` | ＋补 |
| 54 | `resource_pct` | 资源按百分比显示 | `field_meta.py:3233` | `commands/status_commands.py:197-198` | 包配置 | `"resource_pct": false` | ✅ |

#### 7.3.3 ⚠️ 三个**不在** schema 里、但真实生效/被引用的段（盘点把它们也列了）

| 段名 | 用途 | 语义源 file:line | 读取处 | 可被包覆盖 | 说明 |
|---|---|---|---|---|---|
| `ext` | **E1/E2 扩展总开关** | **无 field_meta 登记**；语义源 `pack_ext.py:115` | `pack_ext.py:119`；`pack_render.py:349`（经 `pack_ext_enabled`） | 包配置（**缺省 false**） | **双闸第一闸**。因为无 schema 登记，写错键名**不会有任何提示**（§5.1） |
| `schema_ext` | **包自持校验扩展** | `validator.py:390-402`（约束子集） | `validator.py:429`（`_parse_schema_ext`）、`:543-549` | 包配置 | 见 §5.6 |
| `worldtime` | 世界时间快照兼容段 | **无 field_meta 登记** | `qbot_rpg_bridge/assemble.py:164`（`settings_map.get("worldtime")`） | 包配置 | 与 `time_cycle` 并存：`worldtime` 是**桥梁直读的兼容段**，`time_cycle` 才是已登记段 |

#### 7.3.4 已废弃的嵌套键（保留兼容）

| 键 | 状态 | 判据 | 说明 |
|---|---|---|---|
| `forge.decompose_rate` | **已废弃** | 迁移黄提示 `validator.py:2582-2601` | 唯一源已迁到 `settings.alchemy.decompose_rate`；**引擎从不读取**。黄提示 **Y-21 不阻断**。**勿当 bug 删**——删了旧包会失去迁移指引 |
| `settings.alchemy.assistant` | 兼容双路 | `core/alchemy_helper.py:212-217` | 与顶层 `settings.assistant` 双路兜底，有 legacy 读取顺序 |

### 7.4 各模块 json（`<module>.json`）

**统一加载机制**：`manifest.modules` 每个名字 → `content/<包>/<name>.json`（`loader.py:286-311`）→ 进 `modules` 字典（键 = 模块名）→ `check_pack(modules)` 校验（`loader.py:315`）→ `_build_registry` 按 `_KIND_FOR_MODULE`（`loader.py:146`）登记（`:96-128`）→ 经 `ctx["..."]` 或 `registry.modules_raw` 消费。

| # | 模块 / 文件 | 顶层形态 | 唯一源（field_meta） | 读取处 file:line | 可否被包覆盖 | 示例 |
|---|---|---|---|---|---|---|
| 1 | `effects.json` | `list` | `field_meta.py:3243`（`kind="effect"`, ns=`effect_family`） | `loader.py:288`；`context._table_from_registry` | 包数据 | `[{"id":"thorns","class":"special","trigger":"on_hit","actions":[...]}]` |
| 2 | `statuses.json` | `list` | `field_meta.py:3253`（`kind="status"`） | 同上 | 包数据 | `[{"id":"shield_break","type":"buff","on_lose":[{"effect":"explode_damage"}]}]` |
| 3 | `marks.json` | `list` | `field_meta.py:3262`（`kind="mark"`） | 同上 | 包数据 | `[{"id":"surge_mark","name":"困斗"}]` |
| 4 | `skill_chains.json` | `list` | `field_meta.py:3267`（`chain_field="next"`） | 同上 | 包数据 | `[{"id":"combo1","next":"combo2"}]` |
| 5 | `action.json` | `list` | `field_meta.py:3278` | 同上 | 包数据 | `[{"id":"slash","type":"damage"}]` |
| 6 | `skills.json` | `list` | `field_meta.py:3289`（`kind="skill"`, ns=`skill_lib`） | `loader.py:159`；`ctx["skills"]` | 包数据 | `[{"id":"fireball","actions":[...]}]` |
| 7 | `jobs.json` | `list` | `field_meta.py:3310`（`kind="job"`） | `loader.py:163`；`ctx["jobs"]` | 包数据 | `[{"id":"warrior","name":"战士"}]` |
| 8 | `items.json` | `list` | `field_meta.py:3319`（+`ITEMS_ALCHEMY_FIELDS`/`ITEMS_FORGE_FIELDS`） | `loader.py:164`；`ctx["items"]` | 包数据 | `[{"id":"potion","name":"药水","price":10}]` |
| 9 | `equipment.json` | `list` | `field_meta.py:3325` | 同上 | 包数据 | `[{"id":"sword","slot":"weapon","stats":{"atk":10}}]` |
| 10 | `traits.json` | `list` | `field_meta.py:3332` | 同上 | 包数据 | `[{"id":"brave","effects":["thorns"]}]` |
| 11 | `recipe.json` | `list` | `field_meta.py:3338` | `loader.py:169`；`ctx["recipe"]` | 包数据 | `[{"id":"r_potion","out":"potion"}]` |
| 12 | `runes.json` | `list` | `field_meta.py:3344`（`kind="rune"`） | `loader.py:175`；`ctx["runes"]` | 包数据 | `[{"id":"rune_fire","effects":[{"effect":"burn","trigger":"on_hit"}]}]` |
| 13 | `proficiency.json` | `list` | `field_meta.py:3348` | `loader.py:170` | 包数据 | `[{"id":"sword_mastery"}]` |
| 14 | `slots.json` | `list` | `field_meta.py:1530`（`kind="slots"`） | `loader.py:171`；`validate_slots` @ `alchemy_settings.py` | 包数据 | `[{"equip_id":"sword","slots":[{"slot_level":1}]}]` |
| 15 | `enemies.json` | `list` | `field_meta.py:3369` | `loader.py:189` | 包数据 | `[{"id":"slime","hp":50}]` |
| 16 | `maps.json` | `list` | `field_meta.py:3376` | `loader.py:190`；`validate_maps` | 包数据 | `[{"id":"town","name":"城镇"}]` |
| 17 | `dungeon.json` | `list` | `field_meta.py:3386` | `loader.py:191`；`validate_dungeons` | 包数据 | `[{"id":"cave","floors":3}]` |
| 18 | `stats.json` | `map`（键=ID） | `field_meta.py:3390`（`kind="stat"`, ns=`stat_lib`） | `loader.py:117-120`；`ctx` 属性计算 | 包数据 | `{"str":{"name":"力量"}}` |
| 19 | `formula.json` | `map`（键=ID） | `field_meta.py:3318`（`kind="formula"`, ns=`formula_lib`） | `loader.py:117-120`；`core/formula_loader.py` | 包数据 | `{"dmg":"atk*2-def"}` |
| 20 | `npc.json` | `list` | `field_meta.py:3395` | `loader.py:193`；`validate_npcs` | 包数据 | `[{"id":"elder","name":"长老"}]` |
| 21 | `shop.json` | `list` | `field_meta.py:3402` | `loader.py:199`；`validate_shops` | 包数据 | `[{"id":"shop1","items":["potion"]}]` |
| 22 | `quest.json` | `list` | `field_meta.py:3409` | `loader.py:200`；`validate_quests` | 包数据 | `[{"id":"q1","cond":"[事件:怪物击杀]"}]` |
| 23 | `checkin.json` | `list` | `field_meta.py:3416` | `loader.py:201`；`validate_checkins` | 包数据 | `[{"day":1,"reward":"coins"}]` |
| 24 | `achievements.json` | `list` | `field_meta.py:3422` | `loader.py:188`；`validate_achievements` | 包数据 | `[{"id":"a1","cond":"[事件:首杀]"}]` |
| 25 | `conditional.json` | `object`（`{}`） | `field_meta.py:3427`（`kind="conditional"`） | `loader.py:195`；`condition_engine` | 包数据 | `{"rules":[...]}` |
| 26 | `templates.json` | `map`（key→模板串） | `field_meta.py:3435-3442`（`kind="templates"`, ns=`template_lib`） | **须在 manifest 声明**；`context.py:727-738` | ✅ **覆盖框架默认表** | `{"battle_win":"【{name}】胜了"}` |
| 27 | `forge.json` | `object`：`schema_version`,`trees`,`sets?`,`augments?`,`settings?` | `field_meta.py:3050`（`forge_settings_meta`） | `loader.py:178`；`ctx["forge"]` | 包数据 | `{"schema_version":1,"trees":[...]}` |
| 28 | `enhance.json` | `object`：`settings`,`cost`,`success_curve`/`temper`,`values`,`protect_stone` | `content/enhance_models.py` | `loader.py:182`；`ctx["enhance"]` | 包数据 | `{"settings":{"enabled":true}}` |
| 29 | `fishing.json` | `object`：`schema_version`,`species`,`king` | `field_meta.py:3064`（`fishing_settings_meta`） | `loader.py:185`；`ctx["fishing"]`（`context.py:608/617`） | 包数据 | `{"species":[...],"king":{...}}` |
| 30 | `commands.json` | `object`：`commands[]` | `pack_ext.py:81`（`_ALLOWED_KEYS`）+ `:304`（解析） | `pack_ext.py:570-582`（E1，**不走 loader/validator**） | 包扩展声明 | 见 §5.2.3 |

**任意自定义模块（机制，不是特例）**：`content/<包>/<任意名>.json` 只要列进 `manifest.modules`，就按 list/object 泛型校验并进 registry（`loader.py:138` 缺省 `BaseDef` 回退）。**实测**：`zz_probe_ext_data.json`、`zz_probe_gadgets.json`。这是"包自定义数据段"的正式机制。

### 7.5 `field_meta.json`（包展示元数据，**编辑器层**）

**读取层**：`qbot_rpg/content/field_meta_pack.py`（`FIELD_META_FILENAME` @ `:80`，允许顶层键闭集 `TOP_LEVEL_KEYS` @ `:84-115`，`parse_field_meta` @ `:700`，`load_field_meta` @ `:783`）。**消费方**：`qbot_rpg/web/api.py:242`。**⚠️ 不参与运行时 loader/validator**——纯粹影响编辑器展示。

| # | 段名 | 用途 | 唯一源 file:line | 谁读它 | 可否被包覆盖 | 示例 | 盘点 |
|---|---|---|---|---|---|---|---|
| 1 | `schema_version` | 声明版本（**须 = 1**） | `field_meta_pack.py:82`、`:689` | `:689-698` | 包声明 | `"schema_version": 1` | ✅ |
| 2 | `module_labels` | 模块中文名（逐键覆盖 `manifest`） | `:86`、`:713` | `:713`；`web/api.py` | ✅ **覆盖 manifest** | `"module_labels":{"items":"物资"}` | ✅ |
| 3 | `module_tree` | 模块层级（**整体替换** `manifest`） | `:87`、`:715` | `:715`、`:287` | ✅ **覆盖 manifest** | `"module_tree":[{"module":"items","children":["equipment"]}]` | ✅ |
| 4 | `field_labels` | 字段 label（覆盖框架表同键） | `:88` | `:713-`；`web/api.py` | ✅ 覆盖框架默认 | `"field_labels":{"items":{"price":"售价"}}` | ✅（与 #5 合并行） |
| 5 | `field_help` | 字段说明（覆盖框架表同键） | `:89` | 同上 | ✅ 覆盖框架默认 | `"field_help":{"items":{"note":"无业务含义"}}` | ✅（与 #4 合并行） |
| 6 | `group_labels` | 字段分组显示名 | `:90` | 同上 | ✅ 覆盖框架默认 | `"group_labels":{"base":"基础"}` | ✅ |
| 7 | `subgroup_labels` | 二级分组显示名（模块→子分组键→中文名） | `:93` | 同上 | ✅ 覆盖框架默认 | `"subgroup_labels":{...}` | ✅ |
| 8 | `entry_merge` | 展示层条目聚合 | `:94` | `web/api.py` | 包声明（纯展示） | `"entry_merge":{...}` | ✅（与 #16 合并行） |
| 9 | `segment_pages` | 对象模块合并页 | `:97` | `web/api.py` | 包声明（纯展示） | `"segment_pages":{...}` | ✅ |
| 10 | `id_prefix` | 新建 ID 前缀 | `:100` | `web/api.py:3609` | 包声明 | `"id_prefix":"it_"` | ✅（与 #11 合并行） |
| 11 | `id_width` | 新建 ID 宽度（缺省 3、上限 12） | `:101` | `web/api.py:3609` | 包声明 | `"id_width": 3` | ✅（与 #10 合并行） |
| 12 | `entry_presets` | 条目预设模板 | `:102` | `web/api.py:3580` | 包声明 ∪ 框架默认（`entry_presets.py`） | `"entry_presets":{...}` | ✅（与 #13 合并行） |
| 13 | `entry_presets_disable` | 关闭框架默认（或包自己的）条目预设 | `:104` | `web/api.py:3580` | 包声明 | `"entry_presets_disable":{"items":["p1"]}` | ✅（与 #12 合并行） |
| 14 | `entry_tree` | 条目级层级（左栏从"模块级"扩到"条目级"） | `:107` | `web/api.py` | 包声明（纯展示） | `"entry_tree":[...]` | ✅ |
| 15 | `entry_merge_filtered` | 按条件过滤的条目并入 | `:111` | `web/api.py` | 包声明（纯展示） | `"entry_merge_filtered":[...]` | ✅（与 #8 合并行） |
| 16 | `entry_groups` | 中栏条目分组 | `:114` | `web/api.py` | 包声明（纯展示） | `"entry_groups":[...]` | ✅（与 #8 同行） |

**计数校正**：实测 **16 个顶层键**（`TOP_LEVEL_KEYS` @ `field_meta_pack.py:84-115`）。盘点表是 **12 行**（把 #4/#5、#8/#15、#10/#11、#12/#13 四组合并成行）。

**实证**：`content/zz_probe_packmeta/field_meta.json`（`module_labels` 覆盖 manifest 同名占位、`module_tree`、`field_labels`、`field_help`、`group_labels`）。

**⚠️ 未知键一律报错**（`field_meta_pack.py:85` 注释明写"未知键一律报错，不静默吞掉——防各家包写法漂移"），非法 → `PackFieldMetaError`。

### 7.6 `commands.json`（E1 唯一声明段）

| # | 段名 | 用途 | 唯一源 file:line | 谁读它 | 可否被包覆盖 | 示例 |
|---|---|---|---|---|---|---|
| 1 | `commands` | 包自定义指令数组 | `pack_ext.py:81`（字段闭集）、`:304-328`（解析） | `pack_ext.py:570-582` | 包声明（**框架无默认**） | 见 §5.2.3 |

### 7.7 声明校验位置（框架侧，改校验看这里）

| 校验对象 | 入口 file:line |
|---|---|
| 整包校验入口 | `validator.py:3870`（`check_pack`）→ `_Checker.run` @ `:588-593` → `_check_module` @ `:671`（专项分派 @ `:711-898`） |
| `manifest` 校验 | `validator.py:590-603`（`manifest` 作为受检模块）+ `field_meta.py:3239`（`ModuleMeta`） |
| `settings` 校验 | `validator.py:864-898`（`_check_settings_1g4` @ `:1884` + `check_settings_alchemy` @ `:897` + 各专项） |
| 模块登记一致性门禁 | `loader.py:205-233`（`check_register_table_consistency` / `check_manifest_modules_registered`） |
| 包展示元数据校验 | `field_meta_pack.py:700`（`parse_field_meta`，非法 → `PackFieldMetaError`） |
| E1 声明校验 | `pack_ext.py:304`（`parse_declarations`） |
| E2 声明校验 | `pack_render.py:289`（`_parse_events`） |
| `trigger` 值域校验 | `validator.py:3335-3412`（Y-19 黄提示 / R-1 红拦） |
| 红拦总门禁 | `content/loader.py:239`（`build_pack()`，docstring 明写「任一红拦抛 `PackLoadError`」）+ `validator.py:1-30`（红拦 R-1~R-5 封闭清单） |

### 7.8 已废弃 / legacy 兼容键（**勿当 bug 删**）

| 键 | 是什么 | 判据 file:line | 删了的后果 |
|---|---|---|---|
| `manifest.module_groups` | `module_tree` 的**别名** | `field_meta.py:2164` | 用旧名的包编辑器左栏层级消失 |
| `settings.forge.decompose_rate` | 已废弃，唯一源迁到 `settings.alchemy.decompose_rate` | `validator.py:2582-2601`（Y-21 黄提示） | 旧包失去迁移指引（提示消失） |
| `settings.alchemy.assistant` | 与顶层 `settings.assistant` 双路兜底 | `core/alchemy_helper.py:212-217` | 写在 alchemy 里的助手配置失效 |
| `settings.event_log_cap` | `event_log_capacity` 的**兼容兜底** | `event_bus.py:182`（优先 capacity，兜底 cap） | 旧包的事件日志容量回落 300 |
| `settings.worldtime` | `time_cycle` 之外的**桥梁直读兼容段** | `qbot_rpg_bridge/assemble.py:164` | 用 worldtime 的包天气/季节失效 |
| `settings` 软段（`soft_label=True`）一大批 | "包实有、原表未登记"的兼容放行（泛型校验短路） | `field_meta.py:3068-3236` | 包可自由声明这些段而**不被红拦**——删软标志会让大量既有包红拦 |
| `content/veinborn/*.json.bak` | 非 `.json` 后缀，**不被 loader 读取** | — | 属遗留备份文件，**建议清理以免误认**（不是兼容键） |

---

## 8. hooks：哪些是给包的"扩展点"，哪些**不是**

### 8.1 ⚠️ 先说结论（最容易被误当契约的一节）

框架里有**两类** hook：

| 类 | 面向谁 | 是扩展契约吗 | 包能注册吗 |
|---|---|---|---|
| **① 对外扩展钩子** | 内容包作者 | ✅ **是**（本章 §5） | ✅ 能（E1/E2/`schema_ext`/`field_meta.json`） |
| **② 框架内部注入式回调** | 框架引擎之间 | ❌ **不是** | ❌ **不能**，也不该 |

**给维护者**：第 ② 类 hook 的**名字、签名、是否存在**都是内部实现细节，**随时可改**——因为包代码本来就不许 `import qbot_rpg.*`（§6.1）。**不要**因为"怕破坏包"而给它们加兼容层。

### 8.2 ① 对外扩展钩子（**是契约**）

| hook / 注册点 | file:line | 用途 | 谁调用 |
|---|---|---|---|
| E1 `load_pack_extensions(router, …)` | `assembly/pack_ext.py:481` | 把包 `commands.json` 声明注册进 Router | `qbot_rpg_bridge/assemble.py:181`、`testing_support.py:218` |
| E1 `Router.register(spec, replace=False)` | `commands/router.py:205` | 实际登记点；重名 `ValueError` | `pack_ext.py:630` |
| E1 `Router.unregister(name)` | `commands/router.py:215` | 失败回滚 | `pack_ext.py:643` |
| E1 `AliasTable.add/remove` | `commands/router.py:732` / `:741` | 包指令别名登记 / 回滚 | `pack_ext.py:634` / `:641` |
| E1 **`qbot_rpg.ext_api` 稳定面** | `ext_api.py:42`（`__all__`）、`:59`（版本） | **包代码唯一允许 import 的面** | 包内 `ext/commands.py` |
| E1 `ExtContext.get_state/set_state/patch_state/clear_state` | `ext_api.py:283/291/296/301` | 包 × 玩家状态格子读写 | 包 handler |
| E2 `load_pack_render_hook(pack_dir, …)` | `assembly/pack_render.py:319` | 装载 `ext/render.py` | `assemble.py:185`、`testing_support.py:221` |
| E2 `RenderHook.apply(event, data, default)` | `pack_render.py:240` | 单出口文本替换 + 隔离 | `runner.py:894`、`pack_render.py:441`（`RenderSender`） |
| E2 `RenderSender`（`ctx["sender"]` 代理） | `pack_render.py:410` | 战斗正文直发也过钩子 | `runner.py:845-852` |
| E2b `resolve_templates(overrides)` | `core/templates/__init__.py:101` | 包 `templates.json` 覆盖全量表 | `assembly/context.py:737` |
| E2b `_templates_table(registry)` | `assembly/context.py:727` | 读 `registry.modules_raw["templates"]` → 合并 → 注入 `ctx["templates"]` @ `:1336` | `context.py:1336` |
| 包自持校验 `settings.schema_ext` | `validator.py:429`（解析）、`:543-549`（接线 R-5） | 包声明 `allow_keys/type/enum/required` 扩展校验 | `_Checker.__init__` / `_check_module` 各字段点 |
| 包展示元数据 `field_meta.json` | `field_meta_pack.py:783`（`load_field_meta`）、`:700`（`parse_field_meta`） | 包覆盖字段 label/help/模块树/分组等**展示层** | `web/api.py:242`（`_pack_declaration`） |
| 包模板键来源 | `field_meta.py:3435`（`key_source="templates"`）、`web/framework_keys.py` | 编辑器列出包模板键 ∪ 框架全量键 | 编辑器 `/api/meta` |

### 8.3 ② 框架内部 hook / 回调注入点（**明确"不是扩展点"**）

> 下面每一条**都不是**内容包契约。**包不得依赖它们**；框架维护者可以随时改动/重命名/删除。

| hook | file:line | 用途 | 谁调用 |
|---|---|---|---|
| `register_event_dispatcher(fn)`（effects 回调槽） | `core/effects.py:2022` | 注册状态事件分派回调（**破循环依赖**用） | `core/event_dispatcher.py:332`（模块加载末尾） |
| `bump_event`（事件计数 / 环形日志） | `core/event_bus.py:196` | 事件打点：`longline_counters` + `event_counts` + `event_log` | `ctx["bump_event"]`（`context.py:1854`，`_resolve_bump_event` @ `:908`） |
| `ctx["add_item"] / remove_item / count_item` | `context.py:1106`（`_inventory_hooks`），返回键 `:1239` | 背包增/删/计（reward/shop 契约） | `context.py:1560` 展开注入；各引擎 |
| `ctx["resolve_item"] / resolve_shop / resolve_recipe / resolve_trait` | `context.py:1848-1851`（`_kind_resolver`）；`resolve_attr_final` @ `:1901` | registry 引用解析闭包 | 指令壳 / 引擎 |
| `ctx["consume_bait"] / mode / king_event / king_victory_record` | `context.py:1510-1513`（薄委托） | 钓鱼引擎回调 | `core/fishing.py` |
| `ctx["respawn_hook"]` | `context.py:1539`（`_respawn_hook_of`） | PVP 击杀惩罚回城 | `core/pvp.py` |
| `ctx["npc_interactions"]` | `context.py:1663` | NPC 交互菜单解析 | `core/dialog.py` |
| `ctx["start_battle"]` | `context.py:1754`（**当前 `None`**） | 调查遭遇开战 | `core/investigate.py` / `battle_launch_commands` |
| `ctx["sender"]`（统一发送出口） | `runner.py:841-852` | 战斗管线直发正文 | `battle_commands` / `BattlePipeline` |
| `ctx["resolve_player_name"] / same_group` | `context.py:1372-1373`（**当前 `None`**） | `/协力` 注入位 | 协力指令 |
| `Router` 框架指令注册元组 `REGISTER_GROUPS` | `assembly/router_setup.py:94`（`build_router` @ `:225`） | 框架内置指令分组登记 | 装配 `build_router` |

**⚠️ 文档缺口（盘点已列，本次复核确认）**：上面这些 `ctx[...]` 注入点**只在代码注释/docstring 里说明**，`docs/游戏包扩展点_方案_E.md` **未列**；`docs/内容包扩展_指令.md` 只面向 E1。**本节是它们的第一份成文清单**——但请记住 §8.1 的结论：**清单存在 ≠ 它们是契约**。

### 8.4 包自持代码的边界（`ext/` + `tests/` + `scripts/`）

| 目录 | 内容 | 触发方式 | 边界 |
|---|---|---|---|
| `content/<包>/ext/commands.py` | E1 指令实现 | 双闸 + 装配期装载 | 只 `import qbot_rpg.ext_api` |
| `content/<包>/ext/render.py` | E2a 渲染钩子 | 双闸 + 装配期装载 | **不 import 任何 `qbot_rpg.*`**（只拿只读快照 + 最终文本） |
| `content/<包>/tests/` | E3a 包内测试 | `scripts/run_pack_tests.py` | 主套件不自动收集 |
| `content/<包>/scripts/build.py` | E3b 包内构建 | `scripts/run_pack_build.py` | cwd = 包目录；退出码如实转发 |

**双闸默认关 + 重名拒 + 失败隔离**的完整口径见 §5.2.5 / §5.3.4。

---

## 9. 给扩展开发者的"怎么接"

### 9.1 新增一个**事件时点**（框架侧改动，**必须走评审**）

> ⚠️ **这不是内容包能做的事**。内容包只能**使用**已有时点。新增时点 = 改框架战斗流程。

**前置判断**：你要的语义能不能用现有时点表达？先查 §2.2 三态表——**如果只是写错名字，不用新增时点**。

**六步清单**（缺一步就会留下"登记了不生效"陷阱）：

| 步 | 动作 | 落点 | 不做的后果 |
|---|---|---|---|
| 1 | **追加**枚举值到 `EVENT_POINTS` **末尾** | `qbot_rpg/data/event_points.py:25` | 插中间会位移既有断言（`:23-24` 明写保序要求） |
| 2 | 加**生产派发点** `self._dispatch_event("<新时点>", side)` | 对应战斗流程处（参考 `battle.py` 现有 11 处） | **效果永不触发**（本框架最危险的坑，§3.5） |
| 3 | 更新语义 docstring | `core/event_dispatcher.py:26-37`；`data/event_points.py` 模块 docstring | 下一个人不知道它派给谁 |
| 4 | 确认**谁收**（`side` 语义）并写进注释 | 派发点处 | 效果挂错侧（§3.1 的 `death`/`on_kill` 教训） |
| 5 | 评估**数值影响** + 加对拍测试 | `tests/` | 改变既有战斗数值而无人知 |
| 6 | 登记裁决到 **`docs/深度打造_决策记录.md`** | 决策记录 | 下次"死代码清理"可能把它删掉（**批73 已有 47 条死代码删除登记表**：`docs/死代码删除登记表.md`） |

**新增后自动获得的东西**（不需要额外改）：
- `trigger` 值域校验自动放行（校验器读 `EVENT_POINTS`：`validator.py:3383` `known = tuple(EVENT_POINTS)`）；
- Y-19 不再对新值报警。

**新增后**仍需**手动**改的东西：
- **`docs/深度打造_实现说明.md:728-752` 的 14.3 事件时点表**——它是**人工维护的**，不会自动同步。
- `STATUS_EVENT_POINTS`（`data/event_points.py:38`）**只有**两个状态时点，别往里塞非状态时点。

**复制模板（第 2 步的代码形状）**：
```python
# 在对应战斗流程处
self._dispatch_event("<新时点>", "<side>")   # side ∈ {"player","enemy"}，或 attacker/actor
```

**🔴 反例警示（真实存在）**：`content/veinborn/effects.json:51-64` 的 `surge_tick` 用了 `trigger: "turn_end"`——**枚举里有、但没人派发**，所以**静默不触发**，校验器也不报警。**新增时点后请务必确认第 2 步真的做了**（§3.3 待查 P-2）。

### 9.2 新增一个**指令**（包侧，5 步可复制）

| 步 | 动作 | 落点 |
|---|---|---|
| 1 | 写声明 `commands.json` | `content/<包>/commands.json`，形状见 §5.2.3 |
| 2 | 写实现 `ext/commands.py`，函数名 = `handler` | `content/<包>/ext/commands.py`；**只** `from qbot_rpg import ext_api` |
| 3 | 开 `settings.ext.enabled = true` | `content/<包>/settings.json`：`{"ext":{"enabled":true}}` |
| 4 | 启动时开第二闸 | CLI `--enable-pack-ext` **或** 环境变量 `QBotRPG_ENABLE_PACK_EXT=1` |
| 5 | 写包内测试 | `content/<包>/tests/test_*.py`，跑 `python3 scripts/run_pack_tests.py --pack <包>` |

**自查**：
- 指令名/别名**不能**与框架指令重名——重名 → **整包扩展降级不生效**（`_check_conflicts:331`）。
- handler **必须**在 `ext/commands.py` 里存在（`pack_ext.py:600-603` 会预检，缺 → 整包拒绝）。
- 别写未知字段（`_ALLOWED_KEYS` 闭集，写错直接报错）。

**验证**：`python3 scripts/run_pack_build.py --pack <包> --check`（复用框架整包校验）。

### 9.3 新增**一段渲染**（包侧，两条路，**优先 E2b**）

**路线选择**：

| 你的需求 | 用哪条 | 为什么 |
|---|---|---|
| 只改**文案字符串**（措辞、后缀、格式） | **E2b `templates.json`** | 纯数据、不执行代码、最安全 |
| 需要**按上下文计算**才决定文本 | **E2a `ext/render.py`** | 能拿到只读快照 |

**E2b 步骤**：
1. 在 `manifest.json` 的 `modules` 里**加 `"templates"`**（⚠️ **不加就是静默不生效**）；
2. 写 `content/<包>/templates.json`：`{"模板键": "文案"}`；
3. 键必须是**已存在**的框架模板键（未知 key 只 warn，不会新增）。

**E2a 步骤**：
1. 开双闸（同 §9.2 第 3、4 步）；
2. 写 `content/<包>/ext/render.py`：`EVENTS`（可省）+ `render(event, data, default_text)`；
3. **只返回 str 或 None/""**；异常/超时/非 str 会被兜底成默认文本；
4. **禁止** sleep / 网络 / 长任务（软超时 0.5s，不做线程抢占）；
5. 事件名只能用 `pack_render.py:85` 的 `KNOWN_EVENTS`（`command.reply` / `battle.round`）；未知事件**警告 + 忽略**。

### 9.4 新增一个**包状态格子**（包侧）

包可持久化的**唯一**东西就是"该包 × 该玩家"的状态格子：

```python
from qbot_rpg import ext_api

async def my_handler(ctx, parsed):
    st = await ctx.get_state()              # dict
    st["counter"] = st.get("counter", 0) + 1
    await ctx.set_state(st)
    return f"计数={st['counter']}"
```

方法：`get_state` / `set_state` / `patch_state` / `clear_state`（`ext_api.py:283/291/296/301`）。**玩家维度隔离**——不同玩家互不可见（`ext_api.py:15-17`）。

### 9.5 给未来的维护者：改框架前 checklist

改任何"事件 / 扩展点 / 声明段"之前，按顺序过这 6 条：

1. **它有三态表里的哪一态？** 查 §2.2。删一条"无派发点"的枚举**看似清死代码，实则可能删掉已登记的二期扩展位**（先看 `docs/死代码删除登记表.md`）。
2. **它是"零变化口径"的一部分吗？** §4.3 的三态（`(None,None)` = 全库扫描）、§5.3.4 的"未装钩子零改动"——**改它们=打破向后兼容承诺**。
3. **它在 §7.8 legacy 表里吗？** 在 → **勿删**，先读对应 `file:line` 的注释与裁决。
4. **它在 `ext_api.__all__`（§6.3）里吗？** 在 → 破坏性变更**必须**递增 `EXT_API_VERSION`（`ext_api.py:59`）。
5. **它有 `docs/深度打造_决策记录.md` 的落地登记吗？** 有 → 改动要同步那一条。
6. **改完跑什么？** 至少 `python3 scripts/check_architecture.py`（架构门禁）+ `python3 scripts/compare_field_meta_migration.py`（字段迁移门禁）+ 相关 `tests/`。

**本手册对维护者的核心价值**：§3.5 的"合法枚举 + 无派发点 = 静默死效果"、§4.3 的"零变化口径"、§7.8 的 legacy 表——**这三处一旦被当成 bug"修"掉，会静默破坏既有内容包**。

---

## 10. 复核记录

### 10.1 本次复核做了什么

| 手段 | 命令 / 方式 | 覆盖 |
|---|---|---|
| 读源码 | `read` / `sed` 逐段读 | `event_points.py` / `event_dispatcher.py` / `battle.py`（派发与归属段）/ `effects.py`（状态事件段）/ `pack_ext.py` / `pack_render.py` / `ext_api.py` |
| 全仓扫描 | `grep -rn` 逐时点字面量 | 17 个 `EVENT_POINTS` 时点的派发点存在性 |
| 逐函数归属 | `python3` 脚本把每个 `_dispatch_event(...)` 调用映射到所属函数 | 11 个已接时点 + `action_end` 的 5 条路径 |
| 运行时枚举 | `python3 -c` 导入 `_module_table()` | `settings` 段 **54**、模块表 **36** 条目 |
| 读常量 | 直接读 `TOP_LEVEL_KEYS` | `field_meta.json` **16** 键 |
| 实测包 | 读 `content/zz_probe_ext/*`、`content/veinborn/*` | E1/E2/E3 最小示例、`surge_tick` 死效果 |

### 10.2 本章纠正 / 补充了盘点文档的哪些结论

| # | 盘点说法 | 本次实测 | 处置 |
|---|---|---|---|
| 1 | `settings.*` 声明段 **41 条** | 框架 `settings` schema 实测 **54 段** | §7.3.2 全 54 段列出，漏列的 14 段标"＋补" |
| 2 | `field_meta.json` **12 段** | `TOP_LEVEL_KEYS` 实测 **16 键** | §7.5 全 16 键列出，标注盘点 12 行的合并关系 |
| 3 | "93 条" | 是**行数口径**，非键数口径 | §7.1 明确两种口径并给对照表 |
| 4 | `EVENT_POINTS` 17 点 / 11 点有派发点 | **复核一致**（给出 11 条原文证据） | §2.2 |
| 5 | 行号（基于 `d86d9dd`） | HEAD `62cc299` 已漂移（`battle.py` −3~−5、`effects.py` −3~−9） | **本章所有行号已重核** |
| 6 | `turn_end` "故意不派发" | 复核一致（`实现说明.md:735`） | §3.3 |
| 7 | `status_lose` "部分：tick 过期待接" | **复核确认**：两条 tick 过期路径（`effects.py:824-825`、`:1418-1420`）只写 log、不派发 | §3.2 待查 P-1（给出精确行号） |
| 8 | `content/veinborn` 是"真实大包" | ⚠️ **新发现**：其 `effects.json:51-64` `surge_tick` 用 `turn_end` → **静默死效果**，校验器与测试都不拦 | §3.3 / §9.1 待查 P-2 |
| 9 | `action_start`/`action_end` 对称 | ⚠️ **新发现**：`_flee_actor` / `_skip_turn` **不派发 `action_end`** | §2.4 待查 P-4 |
| 10 | 方案 E 文档"只写 `build.py --check`，未写明在 `scripts/` 子目录" | **复核部分不成立**：`docs/游戏包扩展点_方案_E.md:49` **已**写明 `content/<pack>/scripts/`；只是 `:50` 那句"入口约定"没在本句点明路径 | §5.5.2 改判为"**表述精度提示**"，非"文档缺项" |
| 11 | "未启用时零文件访问"（`pack_ext.py:503` 注释） | **复核：表述宽松**——`pack_path = Path(pack_dir)` 在双闸判定**之前**执行（`:506`），但只构造 `Path` + `.name`，未 stat/read | §5.2.5 按实测口径写明，不称其为 bug |

### 10.3 待查清单（**明写"未确认"，不猜**）

| 编号 | 待查内容 | 已知事实（file:line） | 缺什么 |
|---|---|---|---|
| **P-1** | `status_lose` 的 **tick 过期**路径不派发，`on_expire` 效果是否会触发？ | `effects.py:824-825`、`:1418-1420` 只 log 不派发；`event_dispatcher.py:74` 把 `on_expire` 映射到 `status_lose` | **意图裁决**（是漏设计还是故意二期） |
| **P-2** | `content/veinborn/effects.json:51-64` `surge_tick` 的 `trigger:"turn_end"` 是笔误还是预留？ | `turn_end` 无派发点；其 `desc` 写的是"每次行动结束时" | 原作者意图 / 是否应改为 `action_end` |
| **P-3** | `resource_axis_validator.py:99` 的 `PROC_TRIGGER_EVENTS = ("on_turn_start","on_hit","on_season_change")` 与 `EVENT_POINTS` 是否是**同一套**？ | 命名风格近似但值不同（`on_turn_start` ≠ `turn_start`） | 两套是否有意统一 |
| **P-4** | `action_start` / `action_end` 不对称（逃跑/跳过无 `action_end`）是设计还是遗漏？ | `battle.py:2959`（全类型）vs `:3018/3119/4058/4635/5044`（5 路径）；`_flee_actor:3044-3091`、`_skip_turn:3025-3043` 无派发 | 意图裁决 |
| **P-5** | `settings.ext` / `settings.schema_ext` / `settings.worldtime` **无 field_meta 登记**，写错键名无任何提示 | `ext_api` 语义源 `pack_ext.py:115`；`schema_ext` @ `validator.py:390-402`；`worldtime` @ `assemble.py:164` | 是否应补 schema 登记（属改进项，非 bug） |
| **P-6** | `core/templates/__init__.py:102` 注释写"深合并"，实现是**逐 key 整体替换** | `:102` vs `:113-119` | 哪个是意图（本次以**实现**为准） |
| **P-7** | `settings.json` 双通道（loader 校验 vs `assemble.py:89-98` 无条件直读）是否应统一？ | `loader.py:286-311` vs `assemble.py:89-98`；`zz_probe_packmeta` 即无 `settings` 模块 | 是否有意保留"无校验也生效" |

### 10.4 与上游盘点的对应关系（便于交叉查证）

| 本章节 | 上游盘点对应 |
|---|---|
| §1 | §3.0（两套事件体系） |
| §2 | §3.1（逐时点）+ §0 发现 1（三态） |
| §3 | §3.1 易混表 + §6 C 组 |
| §4 | §3.2（派发与归属规则） |
| §5 | §4 §A（E1/E2/E3 契约） |
| §6 | §4 A.1.2（`ext_api` 稳定面） |
| §7 | §4 §B（包声明段总清单） |
| §8 | §4 A.4（hooks 全清单） |
| §9 | §8.2（第二路编撰建议） |

---

*第 2 章完。本章所有 `file:line` 基于 HEAD `62cc299`，均经本次逐条重读或运行核对。*





