# 审查报告 · M10 钓鱼批A-1（状态机核心）

- 审查对象：`qbot_rpg/core/fishing.py`（FishingEngine，733 行）
- 参考规格：`docs/细化/细化_2c1b_钓鱼流程状态机.md`（TR-01~11 / ST/SL / GU-01~04 / 模式前缀）、`docs/m10_shared_contract.md`（批0 权威）、`docs/m10_接口摸底.md`、`qbot_rpg/core/dayroll.py`、`qbot_rpg/core/fishing_settings.py`、`qbot_rpg/content/fishing_models.py`、`qbot_rpg/core/quest.py`、`qbot_rpg/core/shop.py`
- 审查方式：**纯静态代码审查（本环境禁止运行命令，所有行为结论为静态推导）**，未执行任何测试/脚本
- 审查维度：① 定稿落地（TR/GU/懒计算/决策窗/每日计数）② 代码质量（bug/边界/确定性/幂等）③ 遗漏（验收点未覆盖）

---

## 〇、结论摘要

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0**（阻断/功能性错误） | **0** | — |
| **P1**（须修复/有实际触发路径） | **1** | F-1：静默吞噬 roll_hook 异常 → 钩子失败被当作"成功出鱼" |
| **P2**（改进/防御/一致性） | **6** | F-2 等待期无上限保护；F-3 超时判定边界语义与文案；F-4 `casts` 类型一致性；F-5 `_pick_target` 死分支/宽松放行缺口；F-6 时空回拨防御缺口；F-7 自定义类型归一不一致 |
| 无问题维度确认 | 2 | ① 定稿落地（TR-01~11/GU-01~04/懒计算/每日计数/mode 路由）② 确定性/幂等/零定时器铁律 |

---

## 一、① 定稿落地审计（TR-01~11 / 守卫 / 懒计算 / 决策窗 / 每日计数 / 模式路由）

### 1.1 迁移表 TR-01~11 覆盖核验（静态逐条）

| 迁移 | 规格要求（细化 2c1b §2.2） | 实现位置（fishing.py） | 结论 |
|---|---|---|---|
| TR-01 | S0→S1：`/钓鱼 <钓点id>`，GU-01~04，扣饵+日计数+1 | `start_fishing` L504-534（守卫四连+扣饵+计数） | ✅ 落地 |
| TR-02 | S1→S2：抛竿受理完成，注册懒计时期 | `start_fishing` L567-573（cast_at=now+wait_sec） | ✅ 落地（S1 为瞬时态不落档，补白 B-1 明确） |
| TR-03 | S2→S3：等待期懒计算到期，生成三类鱼讯之一 | `bite_check` L614-642（now>=cast_at + rarity→讯类） | ✅ 落地 |
| TR-04 | S3→ST：`/收杆 满力` | `reel_in` L693-718（roll_hook 注入位/骨架） | ✅ 骨架落地（roll 概率归批2 路2C，B-6 登记） |
| TR-05 | S3→ST：`/收杆 自动` | 同 TR-04 | ✅ 同上 |
| TR-06 | S3→ST：`/收杆 止损`，不 roll、饵已计耗 | `reel_in` L687-691（_clear_session 回 S0） | ✅ 落地 |
| TR-07 | S3→SL：决策窗超时/换区/新钓局被动脱钩 | `reel_in` L678-685（超时→SL→清理回 S0）；换区/新局归批2 指令壳（B-7 登记） | ✅ 引擎侧落地；指令壳路径有登记（见 1.6） |
| TR-08 | ST→S0：结算消息发出，清理会话 | `reel_in` stop 分支 L689-691 / full/auto 分支 L704、L716（_clear_session） | ✅ 落地 |
| TR-09 | SL→S0：跑鱼文案发出，清理会话 | `reel_in` 超时分支 L683-685（_clear_session） | ✅ 落地 |
| TR-10 | S3→BOSS：猛烈+金闪 且鱼王命中 | `fish_intent_of` L158-168 金闪覆写位（king_hit 默认 False）；BOSS 战接线归批4 | ✅ 前置位落地，路径批4 接线（有登记） |
| TR-11 | S2/S3→S2/S3：`/鱼讯` 自环查询 | `bite_check` L605-612（S3 自环返回已有讯类，不重复 roll）+ L617-619（S2 未到期等待态） | ✅ 落地 |

**结论：TR-01~11 全部覆盖。** TR-04/05 的 roll 概率与 TR-10 的 BOSS 战分别以 roll_hook 注入位/king_hit 前置位显式留待批2/批4，符合批分工（文件头与 B-6 已登记，非静默缺失）。

### 1.2 守卫 GU-01~04 核验

| 守卫 | 规格要求（§2.3） | 实现 | 结论 |
|---|---|---|---|
| GU-01 | mode 路由：off 全拒绝 | `start_fishing` L504-506 / `bite_check` L591-593 / `reel_in` L658-660 三入口全部拒绝 | ✅ 落地（含 `/收杆 /鱼讯` 对应入口） |
| GU-02 | 每日上限 daily_limit，第 21 次拦截 | `start_fishing` L512-517（_daily_roll 懒重置后 `casts >= daily_limit`） | ✅ 落地 |
| GU-03 | 目标钓点属于当前地图可钓鱼点集 | `start_fishing` L520-522 + `_spot_ok` L382-390（已知钓点集=species 池 spots 并集） | ✅ 引擎侧落地；"属于当前地图"语义按补白 B-4 归批2 指令壳叠加（引擎无地图语义） |
| GU-04 | 同玩家仅一局 | `start_fishing` L525-528（S2/S3 中再下钩→拒绝） | ✅ 落地 |

**守卫序**与细化 §2.3 一致：GU-01 → GU-02 → GU-03 → GU-04（L504-528）。mode 取值经 `fishing_cfg` 归一（非空 str 生效、非法回退 full，fishing_settings.py A-4）；`start_fishing` 内 L501 另做 `str(cfg.get("mode") or "full")` 冗余归一，无害。

### 1.3 懒计算等待期

- `_roll_wait` L444-452：`wait_sec` 区间 `{min,max}` 非负 int 归一（`_normalize_wait` L193-210），经注入 rng randint 取整秒；`wait_sec=0` → `cast_at=now` 即收（TC-07）。✅
- `_normalize_wait` 对非法/缺失回退默认 300-900，与 `DEFAULT_FISHING_SETTINGS.wait_sec` 一致（fishing_settings.py L68）。✅
- 到期判定 `now >= cast_at`（L617）为纯时间戳懒判，零定时器/零睡眠（铁律 1）。✅
- **cast_at 由 now+wait_sec 计算，等待期无上限保护（见 P2-F-2）。**

### 1.4 决策窗（carry_sec）与 TR-07

- `_carry_sec_of` L318-329：构造器 carry_sec 优先（`max(0, int(...))`）→ `settings.fishing.carry_sec` 原始段（非负 int 生效，`_as_int` 排除 bool）→ 默认 90；0=不限。与补白 B-5、细化 §3.4 一致。✅
- 超时判定 `carry > 0 and (now - bite_ts) > carry`（L682）：静态推导结论——
  - `carry=0` 不判超时，即"0=不限"（TC-08 语义正确）；
  - `bite_ts` 缺省回退 `now`（L680）→ `now - bite_ts = 0`，不会误判超时；
  - 边界 `now - bite_ts == carry` 恰等于时**不**判超时（严格 `>`），与细化「默认 90s 内三选一、超时走 TR-07」的语义无冲突（`==90` 仍视为窗内）。严格 `>=` 与 `>` 在整秒时钟下仅差 1 秒边界，非功能差异，标注供对账参考（P2-F-3）。
- 超时后 `_clear_session` 清理会话回 S0（L683），返回 `state: STATE_LOST` 表示"本次结果=跑鱼"，终态语义与 TR-09 一致。⚠️ 但注意返回中 `state=SL` 与 `_clear_session` 已把 fs["state"] 置回 S0——调用方若以返回的 state 为准则正确（本次事件=SL），若以落档 state 为准则是 S0（无进行中钓局）。两处语义不同源，见 P2-F-3 建议（指令壳接线时以返回值为事件结果、以 fs 为会话态）。

### 1.5 每日计数（{today, casts} 对齐 dayroll）

- `_daily_roll` L393-402：`today_of(fs["today"], now, settings)`（05:00 日界，凌晨 0-5 归属前日）；跨日 → `casts` 清零并更新 today。与 quest._daily_node 同构（quest.py L316-329），符合摸底 §八-3「放 fish_state 内 {today, casts} 对齐 dayroll 懒重置」。✅
- 守卫序：GU-02 前先 `_daily_roll`（L509），跨日首下钩先清零再判定——第 21 次拦截语义正确（L511-517）。✅
- `start_fishing` L532 落 `fs["today"]`（跨日已由 _daily_roll 更新，此处为冗余回写，幂等无害）。
- GU-02 拒绝路径不改计数（casts 不加、today 已更新）——拒绝不耗次数，语义合理。✅
- 终态清理 `_clear_session` L469-486 保留 today/casts，跑鱼/止损日计数不回滚（TR-07/09 语义）。✅

### 1.6 模式路由 full/simple/off

| 模式 | 规格（§2.4） | 实现 | 结论 |
|---|---|---|---|
| off | 全部指令拒绝，不进入任何状态 | 三入口 GU-01 拒绝（L504/591/658） | ✅ |
| full | 完整 FSM | start_fishing L566-578 → bite_check → reel_in | ✅ |
| simple | S0→S1→ST 直接出鱼（无 S2/S3 实例） | start_fishing L536-564：落 last 快照+目标鱼种选定+state=ST+settle_pending=True；bite_check/reel_in 拒绝 simple_no_wait（L596-599/663-665） | ✅ 短接路径落地 |

simple 分支落 `fs["last"]` 快照与目标鱼种（L543-556），指令壳可直结 settle_catch（补白 M-1 补齐）；返回无 wait_sec/cast_at 键，符合"无等待期语义"，指令壳 cast_fishing 对 wait_sec 0 兜底（批2 路2B）。✅

### 1.7 鱼讯三类与金闪（§3.1/§3.3）

- `RARITY_KIND` L114-118 + `fish_intent_of` L158-168：normal→nibble / rare→tug / gold→violent；未知 rarity 保守回落 nibble（不炸）。✅
- 金闪覆写位：`golden = king_hit and kind == violent`（L167）——金闪只可能出现在猛烈鱼讯（TC-13），微动/拉扯永不携带。king_hit 默认 False（批4 接线），golden 恒 False（补白 B-6 前置位）。✅
- 到期时刻选定目标鱼种（B-2，L622-632）：spot 候选池 rng 等概率选一、无候选回落全池；写入 target_species_id/target_rarity 供批3 结算。✅

**① 维度结论：定稿落地无缺失，无问题维度确认。** 所有跨批接线（roll 概率/结算/鱼王 BOSS/地图归属/被动脱钩）均有显式补白登记，无静默偏差。

---

## 二、② 代码质量审计（bug/边界/确定性/幂等）

### 2.1 P1

#### P1-F-1：roll_hook 异常被静默吞噬 → 钩子失败被当作"成功出鱼"，且会话已清理无法重试

- **位置**：`fishing.py` L694-706（`reel_in` 的 roll_hook 分支）
- **问题**（静态推导）：`self._roll_hook(ctx, fs, choice)` 无 try/except 包裹。若钩子（批2 路2C 的 roll 实现）抛出任何异常：
  1. 异常向上传播到指令壳 → 玩家收到错误（若壳无兜底则崩溃该指令）；
  2. 但本方法在钩子调用**之前**未做任何暂存，而钩子抛异常时 L696-703 的 last 快照写入与 L704 的 `_clear_session` **均未执行** → 会话停留在 S3 咬钩态，可重试（这反而是唯一"幸运"点）；
  3. 更严重的路径：若钩子内部已部分写状态（例如自行改了 fs）再抛异常，会话状态不可预期。
- 与文件头铁律「拒绝场景 {ok:False, guard/reason, message} 不抛异常（对齐 HarvestEngine 惯例）」（L261-262）不一致——同文件 `_consume_bait` 对 hook 调用均做 try/except 静默降级（L416-419、L429-434），roll_hook 未遵循同一防御惯例，属不一致。
- **修复建议**（静态推导）：
  ```python
  if self._roll_hook is not None:
      try:
          roll_result = self._roll_hook(ctx, fs, choice)
      except Exception:
          # 钩子失败按失败收杆处理：不落成功快照、不清理会话，玩家可重试
          return {"ok": False, "reason": "roll_failed", "choice": choice,
                  "state": STATE_BITE, "message": MSG_ROLL_FAILED}
  ```
  或至少包裹异常并返回 `{ok:False, reason:"roll_failed"}`，保持 S3 态以便重试；批2 接线时建议约定钩子失败语义（可重试 vs 判定失败）。

### 2.2 P2

#### P2-F-2：等待期无上限保护 —— wait_sec 配置过大时 S2 可无限期悬挂

- **位置**：`_normalize_wait` L193-210 / `_roll_wait` L444-452
- **问题**（静态推导）：`wait_sec` 读自 `settings.fishing.wait_sec`，`_normalize_wait` 只保证非负，无上限钳制；`fishing_cfg`（fishing_settings.py）对 wait_sec 也只做非负 int 合并（A-2）。若配置误填 `{"min": 86400, "max": 86400*30}` 或字段为超大值，`cast_at` 可推到数月后——懒计算本身不炸（跨会话可结算），但玩家将长时间无鱼讯；且「鱼讯真实预告本局出鱼档位」的等待期语义失效，符合"挂机无趣"对策的反面。
- 修复建议：`_normalize_wait` 增加上限钳制（如 `max` 封顶 86400*7 或配置项显式上限，常量化），或由路0C 校验器对 wait_sec 加 V 级范围硬校验（登记契约偏差）。低触发概率（默认 300-900 正常），定为 P2。

#### P2-F-3：超时判定边界与 SL 状态返回语义需对齐（对账锚点）

- **位置**：`reel_in` L678-685
- **问题**（静态推导，二点）：
  1. `(now - bite_ts) > carry` 严格大于：`now - bite_ts == carry` 恰在窗边界时不判超时。与 TC-08 断言（carry_sec=90 超时→SL）无冲突；仅作对账提示：若批2/批3 验收按 `>=` 写断言将差分 1 秒，需统一口径（建议在契约或测试夹具中固定 `now` 注入，使边界可测）。
  2. 超时返回 `state: STATE_LOST` 而落档已回 S0（`_clear_session` L683）：返回值 state 是"本次事件结果"，落档 state 是"当前会话态"，语义不同源。指令壳若用返回值直接写玩家状态会短暂显示"跑鱼中"，用落档则是"空闲"。建议返回增加 `session_state: STATE_IDLE` 或注释明确两键语义，防批2 壳接线误读。

#### P2-F-4：`fs["casts"]` 类型一致性 —— 增量用 `int()` 强转、清零直接赋 0，与全场 `_as_int` 宽容风格不一致

- **位置**：`_daily_roll` L401（`fs["casts"] = 0`）、`start_fishing` L533（`int(fs.get("casts") or 0) + 1`）
- **问题**（静态推导）：fish_state 由持久化载入，`casts` 理论上可能是 float（旧档/手改档）。清零路径直接赋 `0` 可修复，但增量路径 `int(fs.get("casts") or 0)` 对 float 会抛 `TypeError: int() argument must be a string...`（如 `casts=3.0`），而全文件其它读取（`_daily_roll` 的 today 比较、`bite_ts` 等）都用宽容归一。无实际触发路径（本路自写自读均为 int），定为一致性改进。
- 修复建议：`casts = _as_int(fs.get("casts")) or 0`（对齐 L512 同款写法）。

#### P2-F-5：`_pick_target` 死分支与宽松放行缺口（B-4 口径的静态推导局限）

- **位置**：`_pick_target` L455-466 / `_spot_ok` L382-390
- **问题**（静态推导）：
  1. 细读：`_pick_target` 中 `if not candidates: candidates = list(pool)`（L461-462）回落全池分支在 V5 硬校验（species 非空，fishing_models.py L400-409）成立的装配环境**不可达**——池非空时，spots 覆盖某 spot 的鱼种至少一个（F-11 spots≥1）。该分支只在 `_known_spots` 为空（宽松放行）时才有意义：此时 candidates 必空、回落全池，与 GU-03 的 B-4 宽松放行语义自洽。属"防御代码存在但文档未言明依赖 V5"，非 bug；建议在补白 B-2 注明"无候选回落全池依赖 V5 spots≥1，宽松空池场景下即全池"。
  2. B-4 宽松放行（无鱼种数据时任何 spot 放行）是**已登记**的批2 叠加点，非本路遗漏；但提示：引擎层 `_spot_ok` 返回 True 后 `_pick_target` 可能返回 None → bite_check 拒绝 reason=no_species（L624-626）——即"下钩成功但必然无鱼讯"的语义窗口在引擎层存在，指令壳需对 no_species 有文案兜底（建议批2 接线时确认）。

#### P2-F-6：时钟回拨/now 倒流时懒计算与决策窗的防御缺口

- **位置**：`bite_check` L615-617 / `reel_in` L678-682 / `_daily_roll` L396-402
- **问题**（静态推导）：`now` 由 ctx 注入（确定性测试友好），但若生产时钟回拨（now < cast_at 或 now < bite_ts）：
  - 等待期：`now < cast_at` 保持 S2 等待——回拨期间不炸，恢复后到期，可接受（懒计算天然容忍）；
  - 决策窗：`now - bite_ts` 为负 → 不判超时（负值不 > carry），恢复后按新 now 计算，行为正确；但 `fs["bite_ts"]` 恒等于触发时 now（L635），无漂移风险。
  - 综上无功能错误；仅建议：`today_of` 对"未来日期键"已有防御回退（dayroll.py L28-29），本路可对 `bite_ts` 增加 `min(bite_ts, now)` 或保持现状（现状已安全）。定为防御性提示，可不改。

#### P2-F-7：`_carry_sec_of` 与 `_roll_wait` 的自定义类型归一不一致（bool/float）

- **位置**：`_carry_sec_of` L318-329 / `_normalize_wait` L193-210
- **问题**（静态推导）：`_carry_sec_of` 构造器路径 `max(0, int(self._carry_sec))`（L322）对 `True` 会得到 1（bool 是 int 子类），对 `1.5` 会截断为 1；而 settings 路径经 `_as_int` 排除 bool、拒绝非整 float。同一函数两条路径归一口径不一致。`_normalize_wait` 的 `_as_int` 同样排除 bool、拒绝非整 float，且非负钳制。构造器参数是编程接口（类型受控），实际触发概率低，定为一致性改进：
  - 建议：构造器路径也走 `_as_int`（`v = _as_int(self._carry_sec); return max(0, v) if v is not None else DEFAULT_CARRY_SEC`），与 settings 路径统一。

### 2.3 确定性 / 幂等 / 铁律核验

| 检查项 | 结论（静态推导） |
|---|---|
| 零 NoneBot import / 纯函数零 IO | ✅ L83-90 仅标准库与本地模块；`time.time()` 仅在 `_now_ts` 无注入时兜底（对齐 shop._now 惯例） |
| 零定时器/零睡眠 | ✅ 无任何 sleep/定时器调用；等待/超时均为时间戳懒判（L617/L682） |
| rng 注入确定性 | ✅ `_resolve_rng` L306-316：构造器 rng → ctx["rng"] → random 模块兜底，与 shop._rng（shop.py L166-171）同形；无裸 random 破坏确定性（兜底 random 模块与 shop 惯例一致，测试一律注入固定 rng） |
| 输出文案不写死模板 | ✅ 返回结构化 dict，文案为常量占位（L135-151，TODO 批6 标记）；MSG_CAST/MSG_BITE 用 format 插值 |
| 零 emoji | ✅ 全文件无 emoji |
| 幂等性 | ✅ `_fish_state_of` L332-348 幂等（已有键直返）；重复 bite_check 在 S3 自环返回已有讯类不重复 roll（L605-612）；重复 reel_in 在非 S3 态被拒（L667-672）；GU-02 拒绝不改 casts |
| 状态落档一致性 | ✅ 终态 `_clear_session` 保留 today/casts（L469-486），跑鱼/止损不返还饵、日计数不回滚（TR-07/09）；S1 瞬时态不落档（B-1） |

---

## 三、③ 遗漏审计（验收点 TC 覆盖核验）

细化 §六 共 TC-01~25。按本路边界（状态机核心）逐条核验：

| 用例 | 归属 | 本路覆盖核验 | 结论 |
|---|---|---|---|
| TC-01 | 列钓点（指令壳） | 批2 路2A 范围（引擎无地图语义） | 非本路 |
| TC-02 | 无钓点地图空态（指令壳） | 同上 | 非本路 |
| TC-03 | 下钩：扣饵+日计数+1+进入 S2 | L531-533、L573；扣饵 L405-441 | ✅ 覆盖 |
| TC-04 | 无饵下钩保底 / 第 21 次拦截 | L414-441（无饵 None 继续）、L512-517 | ✅ 覆盖 |
| TC-05 | happy path 状态序 S0→S1→S2→S3→ST→S0 | 全链 L499-718 | ✅ 覆盖（roll 骨架态） |
| TC-06 | 跨会话懒计算 | cast_at 落档 fs、now>=cast_at 懒判 | ✅ 覆盖 |
| TC-07 | wait_sec=0 即收 | L567-568（cast_at=now）+ L617 判定 | ✅ 覆盖 |
| TC-08 | 决策窗超时 → SL → S0 | L678-685 | ✅ 覆盖 |
| TC-09 | mode 路由 full/simple/off | L504/536/591/658 | ✅ 覆盖 |
| TC-10 | normal → 微动 | RARITY_KIND + fish_intent_of | ✅ 覆盖 |
| TC-11 | rare → 拉扯 | 同上 | ✅ 覆盖 |
| TC-12 | gold → 猛烈 | 同上 | ✅ 覆盖 |
| TC-13 | 金闪隔离 | L167（金闪仅猛烈） | ✅ 覆盖（king_hit 批4 接线后生效） |
| TC-14 | simple 无鱼讯实例 | L596-599、L663-665 拒绝；L536-564 短接 | ✅ 覆盖 |
| TC-15 | 满力 54/37/9 锚点 | 批2 路2C（roll_hook） | 跨批（B-6 登记） |
| TC-16 | 自动 70/25/5 锚点 | 批2 路2C | 跨批（B-6 登记） |
| TC-17 | 止损：饵已计耗、不触发收益、回 S0 | L687-691（_clear_session；饵耗已发生 L531） | ✅ 覆盖 |
| TC-18 | 无小游戏组件（纯决策分发） | 本文件无任何蓄力/点按/时序判定组件 | ✅ 覆盖（代码层面） |
| TC-19 | 3 讯类 × 3 收杆全组合 | 讯类不锁收杆（fish_intent_of 只预告）；reel_in 三选项对所有讯类开放 | ✅ 覆盖 |
| TC-20 | 猛烈+金闪 收杆前处理 / 日窗 2 | 批4（king_hit/TR-10） | 跨批（有登记） |
| TC-21 | S2 `/鱼讯` → 等待中 | L617-619 | ✅ 覆盖 |
| TC-22 | S3 `/鱼讯` → 讯类+金闪+收杆提醒 | L605-612 | ✅ 覆盖 |
| TC-23 | 空闲 `/鱼讯` → 无进行中钓局 | L601-603 | ✅ 覆盖 |
| TC-24 | 结算三要素+图鉴点亮 | 批3 settle_catch（last 快照已备） | 跨批（B-6/M-1 登记） |
| TC-25 | 冠级纯收藏差分=0 | 批3/批4（roll 与结算） | 跨批 |

**③ 维度结论：无本路遗漏。** 属本路职责的 18 条 TC 全部可映射到实现行；跨批 7 条（TC-01/02/15/16/20/24/25）均有显式补白（B-2/B-6/M-1/B-4）登记落点，无静默缺口。补充建议（P2 级）：`bite_check` 未到期分支返回 `kind: None`（L618），指令壳 `/鱼讯` 输出需自行区分"等待中"（S2）与"无钓局"（S1 未落档不存在）与"咬钩"（S3），建议在契约层固化返回键（如 `phase`），防批2 壳误判。

---

## 四、修复优先级汇总

| 编号 | 级别 | 位置 | 一句话 |
|---|---|---|---|
| F-1 | P1 | fishing.py L694-706 | roll_hook 异常无兜底：钩子失败静默上抛，与同文件 hook 防御惯例（L416-419/L429-434）不一致；应 catch 后返回可重试失败态 |
| F-2 | P2 | fishing.py L193-210/L444-452 | wait_sec 无上限钳制，配置过大可致 S2 悬挂过久 |
| F-3 | P2 | fishing.py L678-685 | 超时边界 `>` vs `>=` 对账锚点 + 返回值 state=SL 与落档 S0 双语义需注释固化 |
| F-4 | P2 | fishing.py L401/L533 | casts 增量 `int()` 强转与清零 `0` 不一致，建议统一 `_as_int` |
| F-5 | P2 | fishing.py L455-466/L382-390 | `_pick_target` 全池回落分支依赖 V5 才不可达，补白注明依赖；B-4 宽松放行后 no_species 拒绝窗口提示指令壳兜底 |
| F-6 | P2 | fishing.py L615-682 | 时钟回拨路径无功能错误，建议对 bite_ts/cast_at 加防御注释或 min 钳制（可缓） |
| F-7 | P2 | fishing.py L318-329 | `_carry_sec_of` 构造器路径 `int()` 与 settings 路径 `_as_int` 归一不一致（bool/float），建议统一 |

---

*审查方式声明：本报告全部结论为静态代码审查推导（本环境禁止运行命令/脚本/验证，未执行任何测试）；涉及运行期行为的表述均已标注"静态推导"。*
