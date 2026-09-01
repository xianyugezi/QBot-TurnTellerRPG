# 审查 · M10 钓鱼批A-3 流程指令（fishing_commands / fishing_reel_commands / fishing_cast / fishing_roll）

> 方式：j-space 静态审查（full 档）· 本环境无 bash 沙箱，**零命令执行**，全部结论为静态推导
> 日期：2026-09-01 · 审查人：主 agent（j-space 会话）
> 文件清单（本批）：
> - `qbot_rpg/commands/fishing_commands.py`（/钓鱼 钓点列举+鱼讯参考，488 行）
> - `qbot_rpg/commands/fishing_reel_commands.py`（/鱼讯 + /收杆 三选一，322 行）
> - `qbot_rpg/core/fishing_cast.py`（cast_fishing / bite_trigger 接线，295 行）
> - `qbot_rpg/core/fishing_roll.py`（roll 概率 70/25/5、54/37/9，315 行）
> 参考：`docs/细化/细化_2c1b_钓鱼流程状态机.md`（§四 收杆三选一 TC-15~20 / §五 /鱼讯 TC-21~23 / §一 列钓点）/ `docs/m10_shared_contract.md` / `docs/m10_接口摸底.md` / 定稿（经仓库内契约转引，定稿原文在仓库外不可达）
> 交叉核对（装配/引擎/数据层）：`qbot_rpg/core/fishing.py`（FishingEngine）、`qbot_rpg/core/fishing_settings.py`、`qbot_rpg/core/fishing_bait.py`、`qbot_rpg/core/fishing_mode.py`、`qbot_rpg/core/templates/__init__.py` + `fishing_tpl.py`、`qbot_rpg/assembly/context.py`、`qbot_rpg/assembly/router_setup.py`、`qbot_rpg/assembly/runner.py`、`qbot_rpg/commands/parsers.py`、`qbot_rpg/commands/router.py`、`content/test_demo/settings.json` / `maps.json` / `fishing.json`、`tests/unit/test_fishing_commands.py` / `test_fishing_reel_commands.py` / `test_fishing_cast.py` / `test_fishing_roll.py` / `test_fishing_tpl.py`、`docs/审查报告/审查_M10_A2_jspace.md`（前例口径）

> ⚠️ 可达性说明：定稿原文在仓库外 `/root/docs_archive/RPG框架项目/钓鱼玩法设计定稿.md`（glob 不可达），本报告以仓库内契约（m10_shared_contract 声称与定稿 §三 逐键一致）与细化 2c1b 为准对表；凡涉及定稿行号（L19/L94/L96 等）均为**转引口径**，直接冲突时以契约为准。
> ⚠️ 重要前提：**批6 路6A 已收口**（2026-09-01，context.py L1129-1136 已注入 fish_state/consume_bait/mode/king_event hooks；fishing_tpl.py 分区已并入 DEFAULT_TEMPLATES；tests/unit/test_fishing_tpl.py 全 key 断言通过）。本批四个文件头多处「批6 迁移/待装配注入/未落盘」注释与当前仓库状态**不符**（下述）。

## 结论速览

| 级别 | 数量 | 要点 |
|---|---|---|
| P0 | 2 | ①三指令未注册进 Router/白名单（装配断线，全链不可达）②`consume_bait` hook 签名错位（生产扣饵永不执行，满配锚点不可达） |
| P1 | 4 | ③/鱼讯 无 bite_check 触发接线（S2→S3 无入口）④`bite_kind` 键名漂移（S3 恒回退微动）⑤fishing_engine 注入/自建两分支 roll_hook 契约不一致（注入路径永不 roll）⑥simple 模式壳层未按 command_allowed 路由 |
| P2 | 6 | ⑦roll_rarity 调用 cfg/ctx 参数语义错位（fishing_cfg 三态容错恰好兜住，脆弱）⑧壳层 fallback 双轨与模板分区并存（文案双源）⑨文件头「批6/待接线」注释过时 ⑩`fish_intent_ref` 渲染前缀差异 ⑪测试未覆盖装配接线 ⑫qid/数据缺失兜底注释缺落点 |

---

## 一、维度① 定稿落地核对

### 1.1 roll 概率锚点（细化 §4.2 / TC-15/16）——**代码正确，装配层不可达（P0-2/P1-3）**

| 核对项 | 结果 | 证据（静态推导） |
|---|---|---|
| AUTO 基础 70/25/5 | ✅ 代码 | `fishing_roll.py` L69 `AUTO_WEIGHTS={normal:70,rare:25,gold:5}`；`roll_weights` L168-170 auto→基础；`test_roll.py` L37-41 断言 =={70,25,5} |
| FULL·对口饵 满配 54/37/9 | ✅ 代码 | `fishing_roll.py` L149-159：base(70/25/5)+bait(rare+8,gold+2)+rod(rare+4,gold+2) → rare=25+8+4=37、gold=5+2+2=9、normal=100-46=54；`test_roll.py` L52-61 断言 =={54,37,9} |
| FULL·无对口饵 60/31/9 | ✅ 代码（补白 R-1 标注非定稿值） | `fishing_roll.py` L72 `DEFAULT_FULL_ODDS={60,31,9}` + pull_odds 可配键读取 L113-143；细化 L159「*实现层插值默认，非定稿值」——标注一致 |
| 种子 42/2026 收敛 ±0.5pp | ✅ 代码 + 测试 | `_weighted_pick` L263-278（rng.random()*total 权重归一）；`test_roll.py` L91-121 断言 N=100000 收敛 ±0.5pp（TC-15/16） |
| **满配锚点在装配层可达性** | ❌ **不可达** | ①`ctx["fishing_engine"]` 生产不注入（context.py 无此键）→ 壳 `_engine_of` 自建引擎**带 roll_hook**（fishing_reel_commands L176-184）→ 该分支本可 roll；但若装配层未来按 R-1 注入引擎（复用），注入的引擎**无 roll_hook**（装配层无构造点）→ 走骨架分支（fishing.py L718-728 `roll_pending=True` 无 roll）——两分支行为不一致（P1-3）；②更硬的断点：P0-1 指令未注册（整链不可达）与 P0-2 consume_bait 签名错位（生产扣饵失败→无饵→`has_matching_bait=False`→FULL 恒 pull_odds 60/31/9）。**54/37/9 锚点整链不可达** |

### 1.2 三选一语义（细化 §4.1 / TC-17/18/19）——**止损路径正确；满力/自动路径壳自建引擎带 roll_hook，但注入路径与装配断点使其不可达（P0-1/P0-2/P1-3）**

| 核对项 | 结果 | 证据 |
|---|---|---|
| 止损：不 roll、饵已计耗、无收益（TC-17） | ✅ | `cmd_fish_reel` L270-271 stop→`_DEF_REEL_STOP`；引擎 `reel_in` L691-695 stop→`_clear_session`（饵不返还、日计数不减）→ 语义对齐 |
| 满力：升级 roll | ⚠️ 壳正确、装配断 | 壳 `_engine_of` 自建分支注入 `roll_hook`（L176-184）→ 本可 roll；但①P0-1 指令未注册整链不可达；②装配注入的引擎（若未来按 R-1 注入）无 roll_hook → 骨架分支无 roll（P1-3 两分支不一致） |
| 自动：基础概率 | ⚠️ 同上 | 同上 |
| 非法 choice → 提示三选一（R-2） | ✅ | L250-252 `_normalize_choice` None → `_DEF_REEL_BAD_CHOICE`「请选择：满力 / 自动 / 止损」；测试 L127-131 断言三词 |
| 缺省参数默认自动（细化 §4.1 实现层默认） | ✅ | L249 `args[0] if args else CHOICE_AUTO`；测试 L106-110 |
| 决策窗超时 → TR-07 跑鱼（TC-08） | ✅ | 引擎 reel_in L686-689 timeout→SL；壳 L260-261 reason timeout/lost→`_DEF_REEL_TIMEOUT`；测试 L134-143 |

### 1.3 /鱼讯 推进（细化 §五 / TC-21~23）——**壳层状态读取正确，但 S2→S3 触发接线缺失（P1-1）**

| 场景 | 结果 | 证据 |
|---|---|---|
| S2 等待中 → 钓点/已耗时/等待中（TC-21） | ✅ 壳 | `cmd_fish_bite` L212-216；`_elapsed` L151-157（now-cast_at，负夹 0）；测试 L51-58 |
| S3 已触发 → 讯类+金闪标记行+收杆提醒（TC-22） | ⚠️ 键名漂移 | L219 `fs.get("bite_kind")` 读不到引擎键 `kind`（fishing.py L637 `fs["kind"]`）→ 恒 "micro"；L221 golden 读 `fs.get("golden")` ✓（引擎 L638 落档 `golden`）|
| 空闲/无钓局 → 空态不报错（TC-23） | ✅ | L204-206/L227-228；测试 L44-48 |
| **S2 到期 → S3 迁移触发** | ❌ **无接线** | 壳 `cmd_fish_bite` **纯读 fs 状态，从不调 `bite_check`/`bite_trigger`**；`fishing_cast.bite_trigger` 全仓无消费方（仅测试）。细化 TR-03「等待期懒计算到期 → 生成三类鱼讯之一」在指令链上**无任何入口** → S2 恒等待、S3 永不到达、鱼讯三类永不出（除非其他批接线，当前无） |

### 1.4 /钓鱼 列钓点（细化 §1.1 / TC-01/02/09）——**代码正确**

| 核对项 | 结果 | 证据 |
|---|---|---|
| 当前地图全部可钓鱼点 | ✅ | `list_fishable_spots` L319-373：maps 采集点 ∩ 鱼种 spots 引用（双形态匹配 `_spot_matches` L270-275） |
| 候选规则 = 当前季节/时段存在候选鱼种 | ✅ | L356-360 `_season_ok`/`_period_ok`（白名单；空=不限；None=不限宁多勿少） |
| 名称/时段偏好/稀有度标记 | ✅ | L363-372；`_union_periods` L309-316 / `_max_rarity` L296-306（gold>rare>normal） |
| 鱼讯参考说明逐字三组关键词（TC-01） | ✅ | `FISH_INTENT_REF` L111 逐字「微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王！」；测试 L187-192 逐字断言 |
| 空态含「本图暂无可钓鱼点」（TC-02） | ✅ | L441-442；测试 L292-320 多形态 |
| off 全拒绝（GU-01 / TC-09） | ✅ | L431-432；测试 L335-348 |
| 有参下钩转发 cast_fishing | ✅ 代码 | `_cast_forward` L395-414（try/except ImportError 探活→真转发） |

### 1.5 数据层/装配数据源（交叉核对）

- `settings.fishing` 段完整 9 键（settings.json L212-247）✅；`fishing.json` species 含 `spots:["gp_moon_grass"]`（L15）✅；maps.json 采集点 `gp_moon_grass`（L64-71，无 name 字段 → 列表显示回退 id，符合 C-1 约定）✅。
- ctx 注入：`fishing`（context.py L1030）、`fish_state`（L1132）、`rng`（L1196）、`now`（L1198）、`season/period`（L1200）、`maps`（L1253，**list 形态**）✅ 全部与壳层读取口径一致。
- **但 ctx 未注入 `fishing_cfg`**：壳 `_mode_of`（fishing_commands L221-228）读 `ctx["fishing_cfg"]` 优先、缺失回落 `fishing_cfg(ctx)`（从 settings 全量解析）→ 回落路径 ✓ 无 bug；reel 壳 `_mode_of`（L124-128）直接 `fishing_cfg(ctx)` ✓。
- **ctx 未注入 `fishing_engine`**：见 P1-3。

---

## 二、维度② 代码质量（bug / 边界 / 壳-引擎契约）

### P0-1 三指令未注册进 Router 与白名单 → 全链静默不可达（装配断线）

**位置**：`qbot_rpg/assembly/router_setup.py` L77-93（REGISTER_GROUPS 无 register_fishing_commands / register_fishing_reel_commands）、L197-198（逐组注册）；`qbot_rpg/commands/parsers.py` L106-140（DEFAULT_WHITELIST 无「钓鱼/收杆/鱼讯」）

**静态推导**：玩家发 `/钓鱼` → router `route_message` 白名单匹配（router.py L559-584）→ `_match_whitelist`（L441-457）对「钓鱼」零命中 → ROUTE_IGNORED（L586-588）→ **静默无回**（非 stub 未实装提示）。`check_consistency`（router_setup.py L234-255）不会红拦——因为白名单无钓鱼词，`whitelist_not_registered` 是「信息性」非硬错。`_UNIMPLEMENTED_HINTS`（L203-217）也无钓鱼词 → 无「尚未实装」提示。**三指令零入口**。
本批文件头 F-9 / R-1 声称「白名单由主 agent 装配收口登记」——装配层从未执行（批6 路6A 只做了 context hooks 与模板，未做指令注册）。

**修复**：
1. `router_setup.py` REGISTER_GROUPS 增加两行：`fishing_commands.register_fishing_commands`、`fishing_reel_commands.register_fishing_reel_commands`；
2. `parsers.py` DEFAULT_WHITELIST 加「钓鱼/收杆/鱼讯」三词（对齐 forge 先例 L237-240 注释）；
3. 补 `check_consistency` 或装配冒烟断言三指令已注册。

### P0-2 `consume_bait` hook 签名错位 → 生产扣饵永不执行（无饵保底掩盖）

**位置**：`qbot_rpg/assembly/context.py` L460-476（`_hook(qid)` 注入 `ctx["consume_bait"]`）；`qbot_rpg/core/fishing.py` L418-424（引擎调 `hook(ctx, self)`）

**静态推导**：引擎 `_consume_bait` L421 `result = hook(ctx, self)` —— 传入 2 参；`_consume_bait_hook` 的 `_hook(qid)` 只收 1 参 → **TypeError** → 被 L422-424 `except Exception: return None` 吞 → 扣饵失败 → 引擎回落内置扣饵（L425-445：remove_item hook 或 inventory 映射）→ 若内置路径也无（生产 ctx 的 remove_item 由 `_inventory_hooks` 注入，有）→ 内置扣饵执行 → **但走的是引擎内置档序，不是 fishing_bait.consume_bait 的完整语义**。
关键后果：`fishing_bait.consume_bait`（含 `had_bait` 语义/择饵序）从未被调用；更严重的是**对口饵判定 `has_matching_bait` 只看持有计数不看是否真消耗**——但满配锚点依赖 roll_hook（P1-3），两缺陷叠加使 54/37/9 整链不可达。
`fishing_bait.py` L214-220 明示「装配注入 ctx[consume_bait] 时必须 functools.partial 包装 (ctx, engine) 形态」——context.py 未包装。

**修复**：`_consume_bait_hook` 改为适配 `(ctx, engine)` 签名：`def _hook(_ctx, _engine): return consume_bait(ctx, qid)`（用闭包 ctx，忽略入参），或 `functools.partial` 包装。

### P1-1 /鱼讯 无 bite_check 触发接线（S2→S3 无入口）

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L192-228（cmd_fish_bite 纯读状态）；`qbot_rpg/core/fishing_cast.py` L229-280（bite_trigger 无消费方）

**静态推导**：细化 TR-03「S2→S3 等待期懒计算到期 → 按本局目标生成三类鱼讯」——指令链上唯一能触发 `bite_check`（懒判到期）的是 `/鱼讯` 查询；当前壳不调引擎 `bite_check`，只读 `fs` 快照 → **S3 永不到达**（除非批4/批6 其它入口，grep 无）。鱼讯三类、金闪、决策窗全部死链。`bite_trigger`（fishing_cast L229）作为「鱼讯接线」的**唯一调用方缺失**——本批文件头自称「鱼讯接线服务」但零消费。
（注：引擎 `bite_check` 是纯懒判，壳层调它零定时器合规——细化 §五「/鱼讯 推进」语义即查询时推进。）

**修复**：`cmd_fish_bite` 调 `eng.bite_check(ctx)`（或 `fishing_cast.bite_trigger(ctx)`）→ 拿 `{ok, bite, kind, golden, state, ...}` → 按 bite 与否渲染等待中/鱼讯。测试同步补「S2 到期后 /鱼讯 返回讯类」。

### P1-2 `bite_kind` 键名漂移 → S3 讯类恒回退微动

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L219（读 `fs.get("bite_kind")`）；引擎落档键 `kind`（`qbot_rpg/core/fishing.py` L637 `fs["kind"]`、L707/L720 last 快照 `kind`）

**静态推导**：引擎 S3 落档 `fs["kind"]="tug"` 等；壳读 `fs["bite_kind"]` → None → `or "micro"` → `/鱼讯` S3 恒显示「微动」。测试用 `bite_kind` 键构造（test_fishing_reel_commands.py L64/L90）→ 测试与实现同错，掩盖。修复后 P1-1 生效即暴露。

**修复**：L219 改 `fs.get("kind")`；测试夹具同步改 `kind`；`_reel_ctx` L90 同样改。

### P1-3 `fishing_engine` 注入/自建两分支 roll_hook 契约不一致 → 注入路径收杆永不 roll

**位置**：`qbot_rpg/assembly/context.py`（无 fishing_engine 注入）；`qbot_rpg/commands/fishing_reel_commands.py` L170-186（_engine_of 自建无 roll_hook 的场景）；`qbot_rpg/core/fishing.py` L698-716（注入才 roll）/ L718-728（骨架无 roll）

**静态推导**：生产 ctx 无 `fishing_engine` → 壳 `_engine_of` L180-184 自建 `FishingEngine(settings, rng, roll_hook=_roll_hook)`——**该分支有 roll_hook** ✓。但若装配层未来按 R-1 注入引擎（复用），注入的引擎**无 roll_hook**（装配层无构造点）→ 走骨架。当前实际走自建分支 → roll_hook 生效（若 P0-1 修复后）→ 但 `_roll_hook` 内部调用 `roll_rarity` 参数语义错位（P2-1）。综合：**引擎复用契约与 roll_hook 注入位未在装配层定义单一事实源**，两分支行为不一致（自建有 hook、注入无 hook）——契约漂移。

**修复**：装配层注入 `ctx["fishing_engine"]` 时构造器必带 `roll_hook`（包装 roll_rarity）；或在 R-1 补白中明确「注入引擎必须同构注入 roll_hook」，壳层 `_engine_of` 对注入引擎无 hook 时**兜底包一层**（当前不包）。

### P2-1 `roll_rarity` 调用 cfg/ctx 参数语义错位（脆弱但当前可用）

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L176-178 `_roll_hook`：`roll_rarity(choice, _ctx, _ctx, _ctx.get("rng"))`；签名 `roll_rarity(choice, cfg, ctx, rng)`（fishing_roll.py L284）

**静态推导**：第 2 参 cfg 与第 3 参 ctx 都传 `_ctx`（引擎传的玩家上下文）。`roll_weights(choice, cfg, ctx)` → `_full_weights(cfg, has_matching_bait(ctx))`：cfg 应为 settings 全量/段（读 bait_bonus/rod_full_bonus/pull_odds），ctx 应为玩家上下文（读 fish_state/inventory）。两者同传 → **歪打正着可用**：`fishing_cfg` 三态解析（fishing_settings.py L191-192：ctx 含 settings 键 → 解包）恰好把 ctx 当 settings 全量解析出同一配置；`has_matching_bait(ctx)` 也恰好读到同一 ctx。**当前无功能错误，但语义错位、脆弱**——任一函数改严格类型即炸，且代码意图（cfg/ctx 分离）被破坏。定级 P2（原 P1-4 修正为 P2-1，因静态推导无实际错误路径）。

**修复**：`roll_rarity(choice, _ctx.get("settings"), _ctx, _ctx.get("rng"))`——cfg 传 settings 全量、ctx 传玩家上下文，消除语义错位。

### P1-5 simple 模式壳层未按 command_allowed 路由

**位置**：`qbot_rpg/commands/fishing_reel_commands.py` L201-202/L245-246（仅判 off）；`qbot_rpg/core/fishing_mode.py` L178-192（command_allowed：simple 仅 /钓鱼 可达）

**静态推导**：`/鱼讯`/`/收杆` 在 simple 模式下应**明确拒绝**（无 S2/S3 实例，TC-09/14）；当前壳层只拦 off，simple 下 `/鱼讯` 走 fs 空态「无进行中钓局」（误导——不是模式限制）、`/收杆` 走引擎 `reel_in` simple 分支 `{ok:False, reason:"simple_no_wait"}` → 壳 L262-263 落入 idle 空态（非明确拒绝）。`fishing_mode.command_allowed` 已定义正确矩阵但壳未消费（重复实现 mode 判定的风险）。

**修复**：壳层改用 `fishing_mode.command_allowed(mode, CMD_BITE/CMD_REEL)` 统一门控；simple 下 `/鱼讯`/`/收杆` 返回「simple 模式无等待/鱼讯流程」类明确文案。

---

## 三、维度③ 遗漏

| 遗漏项 | 说明 | 级别 |
|---|---|---|
| 指令注册 + 白名单接线 | `register_fishing_commands` / `register_fishing_reel_commands` 未进 REGISTER_GROUPS；「钓鱼/收杆/鱼讯」未进 DEFAULT_WHITELIST | P0 |
| consume_bait hook 包装 | 装配层未按 fishing_bait 契约 partial 包装 (ctx, engine) | P0 |
| /鱼讯 触发 bite_check 接线 | cmd_fish_bite 纯读状态，S2→S3 无入口；bite_trigger 零消费方 | P1 |
| fishing_engine + roll_hook 注入 | 装配层无引擎注入点，壳自建/注入两分支 roll_hook 行为不一致 | P1 |
| simple 模式壳层路由 | 未消费 fishing_mode.command_allowed，/鱼讯 /收杆 在 simple 下语义错误 | P1 |
| roll_rarity 参数语义 | cfg/ctx 同传（歪打正着可用，脆弱） | P2 |
| 模板双轨 | fishing_tpl.py 分区已建（fish_* 全 key 并入 DEFAULT_TEMPLATES），壳层 `_DEF_*` fallback 永不触发但保留 → 文案双源漂移风险（`_DEF_FISH_INTENT_REF_LINE` 含「鱼讯参考：」前缀，模板 `fish_intent_ref` 无前缀→渲染差异） | P2 |
| 文件头注释过时 | 四文件头多处「批6 迁移/待装配注入/未落盘」注释与批6 已收口现状不符（context.py L1129-1136 / fishing_tpl.py 已存在） | P2 |
| 测试未覆盖装配 | test_fishing_* 全部直测壳/引擎，无 run_command 全链路；装配缺注册静默（check_consistency 不红拦） | P2 |
| 引擎复用契约 | `_engine_of` 注入/自建两分支 roll_hook 不一致未在契约登记 | P2（与 P1-3 同源） |
| qid/数据缺失兜底 | 壳层 qid 未消费（对齐前例 P2-2 口径），fishing 数据缺失全默认兜底无断言 | P2 |

---

## 四、修复优先级汇总

| 编号 | 级别 | 位置 | 修复建议 |
|---|---|---|---|
| P0-1 | P0 | router_setup.py L77-93/L197 / parsers.py L106-140 | REGISTER_GROUPS 注册两 register 函数；DEFAULT_WHITELIST 加「钓鱼/收杆/鱼讯」；补装配冒烟断言 |
| P0-2 | P0 | context.py L460-476 / fishing.py L418-424 | `_consume_bait_hook` 改收 `(ctx, engine)` 两参（闭包吞入参）或 partial 包装 |
| P1-1 | P1 | fishing_reel_commands.py L192-228 | cmd_fish_bite 调 eng.bite_check / fishing_cast.bite_trigger，按结果渲染等待中/讯类 |
| P1-2 | P1 | fishing_reel_commands.py L219/L90 | 读 `fs["kind"]` 替代 `bite_kind`；测试夹具同步 |
| P1-3 | P1 | context.py（引擎注入位）/ fishing_reel_commands.py L170-186 | 装配注入引擎必带 roll_hook；壳对注入引擎无 hook 时兜底包一层（当前自建分支有 hook、注入分支无 hook，行为不一致） |
| P1-4 | P1 | fishing_reel_commands.py L201/L245 | 消费 fishing_mode.command_allowed 门控；simple 下明确拒绝 |
| P2-1 | P2 | fishing_reel_commands.py L176-178 | cfg 传 `_ctx.get("settings")`、ctx 传 `_ctx`（修正参数语义位） |
| P2-2 | P2 | fishing_commands.py L163-171 / fishing_reel_commands.py L95-118 | 删除/标注永不触发的 _DEF_* fallback（模板分区已接管），消除双源 |
| P2-3 | P2 | 四文件头 | 更新「批6 迁移/待装配」注释为已收口现状 |
| P2-4 | P2 | fishing_commands.py L454 | `fish_intent_ref` 渲染与模板前缀统一（fallback 含「鱼讯参考：」、模板无） |
| P2-5 | P2 | tests/unit/test_fishing_*.py | 补装配级 run_command 全链路测试（注册/白名单/扣饵/收杆 roll） |
| P2-6 | P2 | 全批 | 引擎复用 roll_hook 契约登记 + qid 消费落点注释 |

---

## 五、与批6 收口现状的冲突说明（重要）

本批四个文件头（fishing_commands L56-58 F-6、fishing_cast L30、fishing_reel_commands L41-42 R-4）多处声称「批6 fishing_tpl 分区迁移」「待批6 装配注入」——但**批6 路6A 已收口**（2026-09-01）：
- `fishing_tpl.py` 已建且并入 `DEFAULT_TEMPLATES`（templates/__init__.py L41/L68），`test_fishing_tpl.py` 全 key 断言通过 → 壳层 `tpl_of` 全部命中，`_DEF_*` fallback 实际永不触发；
- `context.py` 已注入 `fish_state`/`consume_bait`/`mode`/`king_event` hooks（L1129-1136）；
- **但指令注册（P0-1）与 `fishing_engine` 注入（P1-3）未做**——批6 收口不完整，装配断线是本批最大风险。

---

*静态推导声明：本报告全部结论基于文件静态阅读与仓库内交叉核对，未执行任何命令/脚本/运行验证；「红拦」「可通过」「TypeError」「渲染结果」等行为结论均为代码路径静态推导。*
