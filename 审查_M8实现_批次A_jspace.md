# 审查报告：M8 炼金实现 · 批次A（炼金核心引擎层，5 文件）

- 审查方式：**静态代码审查**（本环境无 bash 沙箱，未运行任何命令/脚本/测试；运行行为结论均为「静态推导」）
- 审查文件：
  - `qbot_rpg/core/alchemy_core.py`（1041 行）
  - `qbot_rpg/core/energy_bar.py`（487 行）
  - `qbot_rpg/core/alchemy_auto.py`（421 行）
  - `qbot_rpg/core/alchemy_session.py`（465 行）
  - `qbot_rpg/core/quality.py`（358 行）
- 参考文档：`docs/m8_contract_核心机制.md`（§六 FEED / §七 状态机 / §三 ENG / §四 QLT / §二 职业等级）、`docs/m8_contract_指令契约.md`（§2 /炼金 GU-05~08、§3 /投料 GU-09~12）、`docs/细化/细化_2c4f_投料触媒与能量条.md`（40 规则）、`docs/细化/细化_2c4e_品质与特性.md`（56 规则）
- 审查日期：2026 批次A

---

## 〇、结论摘要

| 级别 | 数量 | 说明 |
|---|---|---|
| **P0**（阻断/数据错误/明确违反契约） | **0** | 未发现 |
| **P1**（功能缺口/契约点未真正落地/正确性锚点脆弱） | **2** | A-1 自动配平不校验槽位与专家门槛；A-2 状态机「已结算」幂等分支不可达 + version 兜底恒 False |
| **P2**（边界/防御/一致性缺陷） | **3** | B-1 能量关闭模式 lazy_regen/current_of 仍写存档；B-2 check_element_req shortfall 语义与文档不符；B-3 cap_quality 负 hard_max 可返回负品质分 |
| **P3**（防御性缺口/配置健壮性/文档级） | **3** | C-1 `int(count)` 对 count=None 抛 TypeError；C-2 consume 关闭路径缺 `consumed` 键；C-3 energy_enabled 字符串"false"误判 + SP「追加次数」引擎无独立实现 |

---

## 一、定稿落地核对（关键验收点）——全部通过 ✅

### 1.1 会话快照形态 STO-03 键集（alchemy_core.py new_snapshot L437-468）
- 契约 STO-03（核心机制 L211）：配方ID + 材料链 + 连锁 + 特性 + 触媒 + PP + 步骤 + version
- 实现键集：`recipe_id / materials / chain / element_scores / pool / catalyst / pp / step / version`（L456-468）——**8/8 全部落地** ✅，另冗余 `job_tier / job_tier_index`（用于全物入料/刻度门槛，合理）
- `version` 默认 1，apply_feed 成功路径 `version = snapshot_version(snap)+1`（L821，§7.1 行4「version 递增」）✅

### 1.2 投料守卫 GU-07~12 / FEED-01~10（apply_feed L714-833）
| 验收点 | 实现 | 结论 |
|---|---|---|
| GU-07 无活跃会话（全局互斥） | alchemy_session.py transition/can_start（行3 conflict） | ✅ |
| GU-08 触媒 ≥ 专家 | catalyst_resolve 注释标注壳层判定（L850）；引擎管 type 校验 | ✅（壳层职责，已声明） |
| GU-09 会话中 | apply_feed 无快照拒绝「no_snapshot」（L737-743）；状态机行4 update | ✅ |
| GU-10 战斗拦截 | 状态机 BATTLE_INTERRUPT→挂起（L345-354）；INST-06 战斗拦截归批9A | ✅ |
| GU-11 槽位 FEED-04 | apply_feed ∑count ≤ slots（L781-790），A-6 单位口径（count 展开） | ✅ |
| GU-12 持有 FEED-05 | 逐项 count_item 校验，不足全拒 + shortfall 差异（L792-807） | ✅ |
| FEED-10 确认全量复核 | verify_snapshot（L876-921）：材料 + 触媒均复核，防过期快照 | ✅ |

### 1.3 连锁 compute_chain（L499-530）
- 相邻同属性 n-1 段：`positions[i]==positions[i-1] and is not None`（L514-517）✅
- count 展开链位：`positions.extend([elem]*count)`（L495-496，A-1/TC-06）✅
- chain_map 超界钳制：`segments > max(cmap)` → 取最高配置等级（L521-522）；0 段/低于最小 → 0（L524）✅
- 同属性判定 = 材料「当前属性」，触媒方向修饰（A-2/A-3，L351-364）✅

### 1.4 能量条 lazy_regen / ENG-01~10（energy_bar.py）
- 查询即补格 + 回写：lazy_regen/current_of → `_compute(write=True)`（L357-390）✅
- 上限封顶：`current = min(raw, mx)`（L333-334）+ 配置下调钳制（L335-337）✅
- 安全区 2 倍速：`interval = _regen_sec_safe if safe else _regen_sec`（L307），safe_scenes 注入（L144-152）✅
- 默认关直通：consume 关闭 → 只读计算 bypassed:True 不写不扣（L422-429，E-7/ENG-01）✅
- 懒计算公式 `floor((now-last)/interval)`（L329-331，E-2/TC-27）+ 首锚点缺失=now（E-3，L319-320）+ 时钟回拨不补不覆写（E-4，L329）✅
- 合成豁免 n=0 只补格不扣（L434-444，ENG-07）✅
- 存档统一 persistent_state 桶，不落 proficiency（E-1/ENG-09，L231-244）✅

### 1.5 品质 round-half-up / 上限叠加 / 降级（quality.py）
- 四舍五入 = round-half-up：`int(floor(total/n + 0.5))`（L259，**非** Python 银行家舍入）✅（TC-02：70/70/80 → 73·精良，静态推导一致）
- 档位判定单调不重叠：score_to_tier（L175-194，39/40、59/60、79/80 跳档）✅
- 上限三处叠加 ≤100：`reachable = min(hard_max + extra_cap, 100)`（L300，QLT-08）✅
- 降级 N 档降 N 档最低普通封底：`new_index = max(0, tier_index - levels)` + 分数裁剪到降档区间（L329-340，QLT-10/TC-09）✅

### 1.6 触媒 catalyst_resolve（L838-871）
- type 校验：type≠触媒 → 拒绝「触媒无效」（L863-870，CAT-05）✅
- 注册制提示不阻断：未注册 → ok:True + message（L855-862，CAT-03）✅
- 方向修饰：catalyst elements 主元素 → compute_chain/compute_element_scores 消费（CAT-02/A-3）✅

---

## 二、代码质量核对（零 IO 零 NoneBot / 构造注入 / 不改外源 / 异常兜底）——通过 ✅

| 维度 | 核对结果 |
|---|---|
| 零 NoneBot import | 5 文件均无 NoneBot 引用（仅 energy_bar 引 `time` 作缺省 now，注入可测，合规） |
| 零 IO | 纯函数/纯类，无文件/DB/网络操作（静态推导） |
| 构造器配置注入 | AlchemyCore(prof, settings)、EnergyBar(settings, safe_scenes)、AutoFeed(settings, quality_system)、QualitySystem(tiers/coef/labels) 均构造注入 + 缺省兜底 ✅ |
| dict 操作不改外源 | apply_feed 用 `snap2 = dict(snap)` 浅拷贝后改写（L815）；ctx 全程只读；EnergyBar `_ps_rw` 仅在明确写路径新建 persistent_state ✅ |
| 异常兜底 | _clamp_int/_as_positive_int/__init__ 配置解析均有 try/except 兜底；catalyst_resolve/_find_def 防御降级 ✅ |

---

## 三、发现的问题（P0/P1/P2/P3 分级）

### P1-A｜alchemy_auto.balance() 自动配平不校验槽位（FEED-04）与专家门槛（FEED-09/TC-09）
- **文件**：`alchemy_core.py` 无需改动；`alchemy_auto.py` L302-340（balance / _plan_element_combo）
- **问题**：AUTO-02 契约（2c4f L49）要求「配平结果照常进入连锁/刻度/特性候选计算（复用 FEED-06/07/08）」且受投料守卫约束。当前 balance() 产出的 plan：
  1. **不感知 recipe.slots**——贪心按元素缺口取材料可超出槽位上限，交付给 apply_feed 时被「投料超槽位」通用错误拒绝，一键投料 UX 断裂；
  2. **不感知专家门槛**——`_plan_element_combo` 候选为「持有且带 elements 贡献的物品」（L221-234），成品/装备（type≠material，如旧爆弹）若带 elements 也会入选；非专家玩家一键投料会配平出含成品的 plan，随后被 apply_feed 以「expert_required」拒绝，而非回到基础材料兜底。
- **修复建议**：balance 接收 job_tier_index；候选过滤 `is_finished`（非专家时剔除）；配平后对 plan 做 `∑count ≤ slots` 校验，超限时回落基础材料或全拒差异。

### P1-B｜状态机行11「重复确认→已结算」分支不可达；terminate_idempotent 的 version 兜底恒 False（死代码）
- **文件**：`alchemy_session.py` L301-317（CONFIRM）、L420-441（terminate_idempotent）
- **问题**：
  1. `transition` 会话中 CONFIRM 调 `terminate_idempotent(_settle_marker(view_ver), view_ver)`，即比较 `view_ver >= view_ver+1`——**恒 False**。`terminate_idempotent` 只有 `view_version is None` 时返回 True。契约 settle_exit_idempotent 终态会 `delete_session`（核心机制 L284），故重复 /确认 时会话已删、壳层状态为 NONE，走 CONFIRM 的 NONE 分支 →「无会话」模板，**「已结算」模板（行11）在正常删除语义下永远不触发**；
  2. P-5 声称的「version ≥ 阈值判定（防御性兜底）」是死代码——当前正确性完全依赖壳层 write_idem_key 幂等键兜住「不双扣」，状态机自身承诺的模板语义未落地。
- **严重性**：不双扣防护存在（壳层幂等键），故不升 P0；但契约行11 的模板与状态机职责未兑现，属正确性锚点脆弱。
- **修复建议**：CONFIRM 时若 view 存在且 `version > 会话快照已知版本`（用快照 base 版本而非当前 view 版本自比）判定已结算；或让壳层在幂等键命中时以「已结算」模板短路，并在本模块注释声明该分支依赖删除语义。

### P2-B1｜能量关闭模式（默认关）下 lazy_regen / current_of 仍写存档
- **文件**：`energy_bar.py` L357-390（lazy_regen/current_of → `_compute(player, now, True, safe)`）
- **问题**：ENG-01/E-7 明确「关闭时 consume 只读计算、不写存档、不扣」（L422-429 已正确 write=False），但 `lazy_regen`/`current_of` 未检查 `_enabled`，在关闭模式下仍 `_ps_rw` 新建并写 `persistent_state.energy_current/last_regen_ts`（L339-343）——与 consume 的关闭直通口径不一致，且对无 persistent_state 的玩家凭空建桶污染存档。
- **修复建议**：`lazy_regen`/`current_of` 增加 `if not self._enabled: return self._compute(player, now, False, safe)`（只读）。

### P2-B2｜check_element_req 的 shortfall 语义与 docstring 不符（部分达标时恒 0）
- **文件**：`alchemy_core.py` L614-618
- **问题**：docstring（L585-586）声明「shortfall = 距下一未达标阈值的差值（全达标→0）」，但实现 `if met_count > 0: ... shortfall = 0`——**部分达标（如 2/3 档已达标、还有下一档未达）时 shortfall=0** 而非距下一未达标阈值差值。`_element_display` 精确阈值「火 42/45」因自行重扫 thresholds（L960-966）不受影响，但公开出参字段语义与契约/文档不一致，消费方若直接取用会拿到错误缺额。
- **修复建议**：部分达标时计算 `shortfall = next_unmet_threshold - score`（扫 thresholds 取首个 `score < threshold`）。

### P2-B3｜cap_quality 对负 hard_max 可返回负品质分
- **文件**：`quality.py` L300-303
- **问题**：`reachable = min(hmax + extra, 100)`；若配置 `hard_max < 0`（异常配置），`reachable` 为负，`s > reachable` → 返回负值，破坏品质分 0-100 口径。
- **修复建议**：`hmax = max(0, int(hard_max))` 后再参与计算（与 extra<0→0 的防御对齐）。

### P3-C1｜apply_feed/compute_chain 对 `count=None` 的记录会抛 TypeError
- **文件**：`alchemy_core.py` L495（`int(rec.get("count", 1))`）、L782（同式）
- **问题**：快照链中若有 count 键存在但为 None/float 的记录（损坏/旧快照），`int(None)` 抛 TypeError——防御链在此断点（_resolve_material 正常产出均为 int，属边界防御缺口）。
- **修复建议**：改用 `_clamp_int(rec.get("count", 1), 1, lo=1)` 或 try 兜底。

### P3-C2｜consume 关闭路径返回结构缺 `consumed` 键
- **文件**：`energy_bar.py` L424-429
- **问题**：关闭直通返回 `{ok, current, max, bypassed}`，不含 `consumed`/`regen_gained`，与开启路径结构不一致；壳层若统一取 `consumed` 需判键。
- **修复建议**：补 `"consumed": 0`（或文档声明壳层按 bypassed 分支处理）。

### P3-C3｜配置健壮性与 SP「追加次数」缺口
- **文件**：`energy_bar.py` L106（`bool(self._alchemy.get("energy_enabled", False))`）
- **问题**：若配置为字符串 `"false"`，`bool("false")==True` 误判开启。另：核心机制 §2.4 SP 面板「投入次数 +1」映射「六 FEED」扩 /投料 追加次数上限，但 FEED-01~10 与引擎均无独立「追加次数」上限实现（现仅靠槽位单位封顶 FEED-04）——契约对 FEED 的引用存在歧义，引擎侧未落地该 SP 项。
- **修复建议**：`_enabled` 用 `is True` 或规范化字符串；「追加次数」若确为独立上限需在 FEED 层补实现或在契约侧澄清归并槽位。

---

## 四、无问题维度确认（点名疑缺项已实现清单）

1. **会话快照 STO-03 键集 8/8**：recipe_id/materials/chain/element_scores/pool/catalyst/pp/step/version 全齐 ✅
2. **投料守卫 GU-07~12**：槽位/持有/原子拒绝+差异/会话前置/战斗拦截/触媒门槛全部覆盖 ✅
3. **compute_chain**：相邻同属性 n-1 段 / count 展开链位 / chain_map 超界钳制 / 触媒方向修饰 ✅
4. **能量 lazy_regen**：查询即补格 / 上限封顶 / safe zone 2 倍速 / 默认关直通 / 合成豁免 / persistent_state 存档 ✅
5. **品质**：round-half-up 四舍五入（非银行家舍入）/ 上限三处叠加 ≤100 / 降级 N 档降 N 档最低普通封底 ✅
6. **catalyst_resolve**：type 校验 / 注册制提示 / 方向修饰 ✅
7. **规则级遗漏核对（维度③）**：
   - 2c4f 40 规则（FEED10+AUTO3+BATCH5+CAT6+ENG10+INST6）：FEED/AUTO/BATCH/CAT/ENG 本批次引擎侧全落地；INST 6 条属批9A（即时调合），不在本批次 ✅
   - 2c4e 56 规则（QLT13+TSC18+INH16+STO9）：QLT-01~13 本批次全落地（含 QLT-08 三处叠加 / QLT-10 降级 / QLT-11~13 刻度×品质 + 悬念分级）；TSC/INH/STO 属继承批次 ✅
   - 状态机迁移表 12 行全可判定（无缺边）；RESUME on SESSION_ACTIVE / BATTLE_INTERRUPT 无操作 / TERMINATED 后 /炼金 等同无会话 / 挂起中 /放弃 退还材料等均为 P-1~P-8 显式补白，非遗漏 ✅
8. **代码质量**：零 IO 零 NoneBot / 构造器注入 / 不改外源 / 异常兜底 全部达标 ✅

---

## 五、审查边界说明

- 全部运行行为为**静态推导**（未执行任何代码/测试/命令）。
- 批次A 仅引擎层；指令壳（批4B）、结算（批6A）、即时调合（批9A）消费点在批B 后续审查核对。
- 已知合理设计（非问题）：A-1~A-8、E-1~E-9、Q-1~Q-4、P-1~P-8 工程补白均有显式标注，未新增定稿外机制行为。
