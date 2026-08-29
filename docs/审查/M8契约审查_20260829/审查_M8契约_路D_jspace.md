# 审查 M8 契约 路D（战斗资源子文档 + batch_plan）

> 审查 Agent · j-space 门控：**loop**（多文件多阶段审计）
> 日期：2026-08-29 · 方式：**静态文件审查**（read/grep 核对，未运行任何命令/脚本，运行行为结论标『静态推导』）
> 审查对象：`docs/m8_contract_战斗资源.md`（323 行，IF-B01~30）+ `docs/m8_batch_plan.md`（113 行）
> 对照基准：细化_2c4b / 细化_2c4c / 炼金定稿 v2.3 §七·§10.6·§11 / m8_接口摸底 / 仲裁细化_0（R-07/R-08）/ m8_batch_plan

## 〇、结论摘要

| 维度 | 结果 | 数量 |
|---|---|---|
| ① IF 接口签名 vs 代码真实签名（IF-B01~30） | 🟢 通过 | 30/30 全部 read 核对命中，无编造行号 |
| ② 战斗即时调合（BA-01~11） | 🟢 通过 | 与定稿 §七 L279-300 逐条一致 |
| ③ 宝石货币（GEM-01~16） | 🟡 注意 | P1×1（SRC-03 掉落误引结算函数） |
| ④ 装饰珠（BEL-B01~12） | 🟢 通过 | 与 2c4c BEL/SOCK + 定稿 §七/§10.6 一致 |
| ⑤ 资源循环（RC-01~15） | 🟡 注意 | P1×1（委托/种植/代工细化追溯缺失） |
| ⑥ batch_plan 批次合理性 | 🟡 注意 | P1×1（/协力 未补排期）+ P2×2 |
| ⑦ 用户 5 项拍板 + R-07/R-08 | 🟢 通过 | 拍板①③④ 本域铁律，②⑤ 关联，R-08 落实，R-07 归域外 |

**分级：P0 = 0 · P1 = 3 · P2 = 4**
**结论：可合入（无 P0 拦截）**，但需按 P1 清单修订契约/批次后再交付实现组。

---

## 一、逐维度核查明细

### 维度① IF 接口签名 vs 代码真实签名 —— 🟢 通过（30/30）

契约 §五 全部签名（文件:行号）逐条 read 真实定义核对命中，**无一行编造行号**：

| IF | 契约声明 | 代码真实定义 | 判定 |
|---|---|---|---|
| IF-B01 do_action | battle.py L1031 `def do_action(self, attacker: str, action_dict: Mapping[str, Any]) -> ActionOutcome` | L1031 同签名 ✅ | ✓ |
| IF-B02 ActionOutcome | L219-236 dataclass（ok..status 14 字段） | L218-236 dataclass，字段逐一同 ✅ | ✓ |
| IF-B03 to_snapshot | L1740 `(self, boundary: Optional[str]=None) -> Dict[str, Any]` | L1740 同签名 ✅ | ✓ |
| IF-B04 _resolve_item_action | L1162 `(self, attacker: str, action: Dict[str, Any]) -> ActionOutcome` | L1162 同签名，经 L0 执行器跑 actions 跳过伤害链 ✅ | ✓ |
| IF-B05 start/start_turn/interrupt/from_snapshot | L850/L951/L1778/L1785 | 全部命中 ✅ | ✓ |
| IF-B06 settle_exit_idempotent | battle_boundary L821 关键字参数 4 元组 | L821-827 同签名；L879-884 单事务 delete_session+write_idem_key；幂等键 command=`settle:{kind}`（L873）✅ | ✓ |
| IF-B07 session_mutex_decision | L702 | L702 命中 ✅ | ✓ |
| IF-B08 settle_currency_drops | L406 `(currencies, drops) -> Tuple[Dict, Dict]` | L406-409 同签名 ✅（**但语义标注错，见 P1-1**） | ⚠️ |
| IF-B09 DeathPenaltyConfig.from_settings | L349 模式 | L349-350 `@classmethod from_settings(cls, settings: object)` 容错解析 ✅ | ✓ |
| IF-B10 dispatch_reward | reward.py L308 `(entries: Any, ctx: Optional[Mapping]=None) -> dict`；返回 {ok,granted,skipped,[idempotent]} | L308 同签名；返回结构、ctx 就地改写 currencies/exp/reputation_state、tx_id+ledger 幂等闸（L337-340）全部一致 ✅ | ✓ |
| IF-B11 _SCALAR_KEYS/_grant_scalar | L59 `("coins","gem","exp","rep")`；L225-238 gem 入账；键空间前置 skip(unknown_currency) | L59 同元组；L225-238 中 L230-236 校验 `key not in space → skip(unknown_currency)`，键空间 = _settings_currency_space（L67-79，源 settings.currencies[].id，缺省 ("coins","diamond") L56）✅ | ✓ |
| IF-B12 _ITEM_KEYS/add_item hook | L61 `("item","id")`；ctx["add_item"] hook 签名 (item_id,count,bound)（文件头补白3） | L61 同元组；reward.py 文件头 工程补白 3 原文同签名 ✅ | ✓ |
| IF-B13 add_item | inventory.py L183 `(self, player, item, count=1)` 返回 {ok,added,rows,new_rows,truncated,message?} | L183 同签名；L241-249 返回含 ok/added/new_rows/rows/truncated ✅ | ✓ |
| IF-B14 remove_item | L254 `(self, player, item_id, count=1)` 返回 {ok,removed} 或 {ok:False, reason:"not_enough"\|"bound"} | L254 同签名；L280-291 not_enough/bound 语义一致 ✅ | ✓ |
| IF-B15 count | L308 `(self, player, item_id) -> int` | L308 命中，跨行求和 ✅ | ✓ |
| IF-B16 POTION_USE_COUNTS_KEY | L56 常量 + L168 `potion_use_counts(player)` 返回可变 dict | L56/L168 命中，docstring「中断恢复不重置、战斗入口负责清零」与 BA-02 口径一致 ✅ | ✓ |
| IF-B17 ItemInstance | data/item.py L20-37（含 traits 冻结 tuple） | L20-37 命中，字段 item_id..cooldown_until 逐一同 ✅ | ✓ |
| IF-B18 EquipmentSlot.gems | data/player.py L69 `Tuple[str,...] = ()` | L69 命中 ✅ | ✓ |
| IF-B19 currencies | data/player.py L87 `Dict[str, int]` | L87 命中 ✅ | ✓ |
| IF-B20 _CURRENCY_NAME_FALLBACK | core/shop.py L150 `{"coins":"金币","gem":"宝石"}` | L150 命中同值 ✅ | ✓ |
| IF-B21 load/save_player | repository.py L442/L473 | L442/L473 命中同签名 ✅ | ✓ |
| IF-B22 load_session | L563 返回 6 元组 | L563-566 命中 (session_type,payload,random_seed,version,created_at,last_active_at) ✅ | ✓ |
| IF-B23 upsert/delete_session/tx | L887/L904/L412 | L887 ON CONFLICT(player_qid) DO UPDATE；L904 DELETE；L412 asynccontextmanager tx ✅ | ✓ |
| IF-B24 write_idem_key/idem_exists | L922/L932 | L922/L932 命中同签名 ✅ | ✓ |
| IF-B25 recycle_scan | L720 `(settle=None, max_days=30.0, now=None, allow_unsettled=False) -> List[str]` | L720-727 命中；「无 settle 不删除」（L731）与 RC-13 复用语义一致 ✅ | ✓ |
| IF-B26 SessionManager 5 方法 | world/session.py L24-40 占位 + SessionConflictError L20 | 全部 NotImplementedError（L27-40），L20 异常类 ✅ | ✓ |
| IF-B27 quest.py 6 函数 | L530/L580/L599/L648/L824/L973 | 逐一命中（quest_board/resolve_board_index/quest_accept/quest_progress/quest_complete/quest_abandon）✅ | ✓ |
| IF-B28 cmd_battle_alchemy 战斗壳 | 对齐 battle_commands.cmd_battle_attack L818 | 经 m8_接口摸底 §3.3 已核（cmd_battle_attack L818 返回 dict）；M8 新建壳 ✅ | ✓ |
| IF-B29 资源循环壳 | 对齐 shop_commands 壳 L447-483 | 经 m8_接口摸底 §3.3 已核（register_shop_commands L447-483）；M8 新建壳 ✅ | ✓ |
| IF-B30 register_alchemy_commands + bootstrap 注入点 | bootstrap.py L61 | read 核对 L61 `session_mgr=SessionManager()` 注入点命中 ✅ | ✓ |

**BA-02 落点结构性核对（维度②关键项）**：to_snapshot（battle.py L1740）返回 `snap = copy.deepcopy(self._snap)` 后追加 schema_version/snapshot_at/snapshot_context/_engine_state/_guard_active/_death_order/formula_state 等**顶层键**（L1754-1771）——纯 dict 结构，新增 `battle_alchemy_used` 顶层键与珠特效同层计数键**完全支持**；当前快照无该键（契约已正确标注 IF-B03「待实装」）。『静态推导』✅

### 维度② 战斗即时调合（BA-01~11）—— 🟢 通过

对照定稿 §七 L279-300（read 核对）逐条一致：
- BA-01 战斗内子流程/一步出结果 ↔ 定稿 L293（写死）✅
- BA-02 battle_alchemy_used 顶层键/中断不清零/结束清零/per_battle_limit=1 ↔ 定稿 L299/L300 + L425 ✅
- BA-04 豁免互斥 ↔ 定稿 L294（写死）✅
- BA-05 拦截模板「战斗中使用 /即时调合 <配方>」 ↔ 定稿 L295 ✅
- BA-06 吃冷却/携带素材+能量（R-08 能量默认关）↔ 定稿 L283 + 仲裁 R-08 ✅
- BA-07 auto_use 可配 ↔ 定稿 L296-298；true 走 _resolve_item_action（L1162 已核）✅
- BA-09 一行渲染「🔥 火焰弹！造成 58 伤害」↔ 定稿 L287 ✅
- BA-10 道具强度公式「技能×(1+0.4×冷却数)」↔ 定稿 L286 + §10.6 L424 ✅

### 维度③ 宝石货币（GEM-01~16）—— 🟡 注意（P1-1）

- GEM-02/IF-B10/IF-B11：四来源统一走 dispatch_reward、gem 标量键、键空间前置硬拦——reward.py L233-236 已核，**settings.currencies 登记 gem 为硬前置**（未登记 → skip unknown_currency 静默不发），批0B 前置标注正确 ✅
- GEM-01 落点 currencies（player.py L87）✅；「金币/声望/宝石并列」沿袭 2c4b SRC-05 松表述（见 P2-2）
- GEM-03 键空间前置 100% 属实（reward.py L230-236）✅
- GEM-06/15/16 分解平铺基础值 1/3/8/20 + 公式可配（拍板①）↔ 2c4b DEC-03、定稿 L419 ✅
- GEM-07 挑战成功宝石+失败降级退 50% 材料不发宝石 ↔ 2c4b SRC-02 ✅
- SINK-01~07 七口数值（20%/10/5/20/10/evolve_to.cost.gem/温室二选一）↔ 2c4b §二、定稿 L419 ✅
- GEM-15 回收率六档 0.4/0.45/0.5/0.55/0.6/0.65、逐材料向下取整 ↔ 2c4b DEC-02、定稿 L418 ✅
- GEM-13 四轴防套利 ↔ 2c4b ARB-01~04 ✅
- **P1-1：GEM-08/IF-B08 误引 settle_currency_drops 为掉落结算路径**（详见问题清单）

### 维度④ 装饰珠（BEL-B01~12）—— 🟢 通过

- BEL-B01 珠等级=品质档（拍板②）↔ 2c4c 档位键集 ✅
- BEL-B02 槽级映射（1=普通/2=精良及以下/3=全部）↔ 2c4c SOCK-02（L88）✅
- BEL-B08 同名递减 第2颗×50%/第3颗×25%、gem_diminish 表驱动 ↔ 2c4c BEL-10（L47）、定稿 L420 ✅
- BEL-B09 触发上限≤3次/场按珠ID、排除被动、同层计数键（工程补白）↔ 定稿 L284/L299、2c4c TC-24（L270）✅
- BEL-B10/B11 珠升阶无职业硬门槛（拍板③）+ 禁跳级 ↔ 2c4c BEL-13/BEL-14（L50-51）、TC-02「全链路 130 宝石」（L233）、TC-03 ✅
- BEL-B06 战斗中不可插拔 ↔ 定稿 L284、2c4c SOCK-04 ✅
- BEL-B03/B05 ItemInstance.traits / 堆叠键（ID+品质+特性集）↔ data/item.py L36、定稿 L401 ✅

### 维度⑤ 资源循环（RC-01~15）—— 🟡 注意（P1-3）

- RC-01~05 委托板：刷新 3 天/三档评价/声望升阶/截止惩罚 −10% ↔ 定稿 11.1 L433-439 ✅（**但缺细化追溯，见 P1-3**）
- RC-06~09 种植：seed 标记/地块存档/4 小时/品质≥种子+继承特性 ↔ 定稿 11.2 L443-445 ✅
- RC-10 温室（大师、宝石或金币二选一不可双付、ARB-00）↔ 定稿 L446、2c4b SINK-07 ✅
- RC-11~14 代工：/雇工 /收取、能源道具、后台产出、助手等级 ↔ 定稿 11.4 L460-466 ✅
- RC-15 材料闭环 ↔ 定稿 11.5 L469-476 ✅

### 维度⑥ batch_plan 批次合理性 —— 🟡 注意（P1-2 + P2）

- 13 实现批（批0~12）+ 1 审查批（批13）结构自洽；每批 ≤3 路并行；批间收口。✅
- 共享锚点（§三）：会话类型 SESSION_TYPES 已含 alchemy/challenge_alchemy、gem 键、白名单、ItemInstance.traits/EquipmentSlot.gems、幂等 write_idem_key、condition/formula 占位、traits 已登记——与摸底 §一/§三/§四 逐条对得上 ✅
- 决策 1-6 与 6 项接口缺口一一对应（SessionManager 实装/battle_alchemy_used/四件套/proficiency dict/gem 管线/settings.alchemy 段含 R-07/R-08）✅
- **P1-2：/协力 批次未补排期**（详见问题清单）
- P2-3：批9→批3 依赖未标注；P2-4：「≈ 28 路」与实际路数偏差

### 维度⑦ 用户 5 项拍板 + R-07/R-08 —— 🟢 通过

- 拍板① 平铺宝石+公式可配：GEM-15/16 + batch_plan 决策/拍板1 ✅
- 拍板② 键集 common/uncommon/rare/legendary + 档位数 3/5/7、0=不限制：BEL-B01 + 定稿 L411 ✅
- 拍板③ 珠升阶无职业硬门槛：BEL-B10/SINK-05 + 拍板3 ✅
- 拍板④ 复制费 ⌊cost.coins×20%⌋：SINK-01 + 拍板4 ✅
- 拍板⑤ int32 数量上限：SINK-00 + 拍板5 ✅
- R-08 能量默认关：batch_plan 决策6 + BA-06 ✅
- R-07 触媒专家解锁：batch_plan 决策6/批0B；本契约 §〇 已显式划出本域边界（触媒归《数据与校验》），不属战斗资源子文档职责，无遗漏 ✅

---

## 二、问题清单

### P1（应改，3 项）

**P1-1 · GEM-08 / IF-B08 将死亡惩罚扣币函数误标为 loot 掉落结算路径**
- 位置：`docs/m8_contract_战斗资源.md` L46（GEM-08）、L194（IF-B08 调用方列）
- 实际内容：GEM-08「战斗击杀结算走 `settle_currency_drops(currencies, drops)`（world/battle_boundary.py **L406**）或统一 reward gem 条目」；IF-B08 调用方「loot.json `gem` 列掉落：宝石直接入货币槽（SRC-03）」
- 应有内容：settle_currency_drops 是**死亡惩罚扣币**函数——`battle_boundary.py L406-409` 签名虽一致，但 docstring（L410-413）明确「货币掉落（DEATH-03 / F-02）：按 {currency:ratio} **逐项扣减**」、返回「扣后余额, 各币种掉量」——语义为**扣减**，绝非发放。宝石掉落（SRC-03）应唯一走统一 reward gem 条目（契约 GEM-02/IF-B10/IF-B11 已写死四来源统一入账，`dispatch_reward` gem 标量键即正确路径）
- 证据：`qbot_rpg/world/battle_boundary.py` L406-421（扣减语义）；`core/reward.py` L59/L225-238/L308（统一发放器）
- 修复建议：删去 GEM-08 的 settle_currency_drops 分支；IF-B08 调用方列改为「loot gem 列掉落 → dispatch_reward gem 条目」（或删除 IF-B08 并归并入 IF-B10，因 SRC-03 不再需要该接口）；不改代码

**P1-2 · batch_plan 未给 /协力 补排期（批11A 注册清单仍缺）**
- 位置：`docs/m8_batch_plan.md` L76（批11A 注册清单 28 词）、L67-69（批8/批9）；对照 `docs/m8_contract_指令契约.md` L46/L56 附注①
- 实际内容：批11A「全指令注册（…/复制 /配方合成 /特性合成 /挑战 /即时调合 /镶嵌 /拆珠 /教学 + /种植 /收获 /雇工 /收取 + /图鉴 /技能面板）」——**无 /协力**；批0~批12 全程无 /协力 批次
- 应有内容：/协力 为细化_2c4d #15 有效指令（TC-22，大师+同群好友，社交向），兄弟契约《指令契约》已用附注① 显式标注缺口并指令「批8 或批11 补排期」，但 batch_plan（权威派工单）**仍未落实**——按批11A 字面执行将静默漏注册 /协力
- 证据：`docs/细化/细化_2c4d_炼金指令表.md` L44（指令 15）/L400（TC-22）；`docs/m8_contract_指令契约.md` L46/L56
- 修复建议：batch_plan 批8A（深度炼金/社交同批）或批11A 注册清单补 /协力 + 白名单补词「协力」，并同步 批12 verify_m8 TC 归属

**P1-3 · 资源循环（RC-01~14）细化追溯缺失**
- 位置：`docs/m8_contract_战斗资源.md` L131（§四 依据仅列「炼金定稿 §11 L430-467」）
- 实际内容：委托任务板（RC-01~05）/种植（RC-06~09）/代工（RC-11~14）仅引定稿 §11，未引任何细化文档
- 应有内容：仓库已有 `docs/细化/细化_2c5b_委托板与声望.md`、`docs/细化/细化_2c5c_种植品评代工.md`（+2c5a 职业等级与 SP），正是该三块功能的实现直接依据；按审查铁律 1（每功能必可追溯细化文档+定稿），§四 依据表应补 2c5b/2c5c 行号锚点（温室 RC-10↔2c4b SINK-07、品评会 GEM-09↔2c4b SRC-04 已有追溯，仅委托/种植/代工缺）
- 证据：glob docs/细化 可见 `细化_2c5b_委托板与声望.md`、`细化_2c5c_种植品评代工.md`、`细化_2c5a_职业等级与SP.md`（对照基准 2c4b/2c4c 内无委托/种植/代工条目）
- 修复建议：§四 依据行补「细化_2c5b / 细化_2c5c」及关键行号；实现组按 2c5b/2c5c 逐条对齐

### P2（建议，4 项）

**P2-1 · batch_plan 批9→批3 依赖未标注**
- 位置：`docs/m8_batch_plan.md` L67-69（批9）
- 内容：批9B（战斗内拦截 /投料/继承/确认）实际依赖批3B/批4 的调合会话指令壳先存在；批9A 即时调合豁免互斥、不依赖 SessionManager 实装（方向正确）。批次按 0→13 串行执行天然满足，不影响派工，但 §三 共享锚点未列该依赖
- 修复建议：§三 补一行「批9B 拦截接线依赖批3B/批4 指令壳（投料/继承/确认）；批9A 豁免互斥不依赖 SessionManager」

**P2-2 · GEM-01「金币/声望/宝石并列」口径易误导**
- 位置：`docs/m8_contract_战斗资源.md` L34
- 内容：沿袭 2c4b SRC-05 松表述；实际 currencies dict 持 coins/diamond/gem，声望落 reputation_state（reward.py 文件头补白 2「rep 不入货币表」）
- 修复建议：改为「金币/钻石/宝石并列」或注明「声望另落 reputation_state」

**P2-3 · batch_plan「≈ 28 路」与实际路数偏差**
- 位置：`docs/m8_batch_plan.md` L5
- 内容：批0/4/7 各 3 路 + 其余 8 批各 2 路 + 批13 串行 5 路 ≈ 34 路，与「≈ 28 路」偏差较大（近似标注，不影响派工）

**P2-4 · §四 header 锚点范围 L430-467 未含 11.5**
- 位置：`docs/m8_contract_战斗资源.md` L18/L131
- 内容：材料经济闭环（RC-15）正文已正确引 L469-476，header 锚点 L430-467 建议改 L430-476

---

## 三、无问题维度确认

- ① IF 接口签名 30/30 全部命中，无编造行号（禁止编造铁律达标）
- ② 战斗即时调合 11 条与定稿 §七 写死语义逐条一致；to_snapshot dict 支持新增顶层键（'静态推导'）
- ③ gem 键空间前置（reward.py L233-236）属实，批0B 前置标注正确
- ④ 装饰珠 12 条与 2c4c BEL/SOCK/TC + 定稿 §七/§10.6 一致（含 130 宝石全链路、禁跳级、无门槛）
- ⑥ 批次结构/决策/共享锚点自洽（除 P1-2/P2 项）
- ⑦ 拍板①~⑤ 全量体现，R-08 落实，R-07 正确归域外

## 四、结论

**可合入**（无 P0 拦截；🟢 4 维 + 🟡 3 维 / P0=0 · P1=3 · P2=4）。
P1 三项均为**契约文档/派工单层修订**，不涉及已实现代码，修订后可交实现组；建议按 P1-1 → P1-2 → P1-3 顺序一次修订回执 Hermes 主 Agent。

*本报告全部引用为静态文件核对（read/grep），未运行任何命令；运行行为结论均标『静态推导』。*
