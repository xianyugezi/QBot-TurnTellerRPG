# 审查_M6实现_批3B_rsm_jspace

> 审查对象：M6 实现层批3B（P0-1 续战世代绑定 RSM 件套）· 静态代码审查
> 方法：**纯静态审查（本环境无 bash 沙箱，未运行任何命令/测试/脚本）**；运行行为结论一律标注【静态推导】。
> 审查文件：qbot_rpg/core/battle.py（快照 registry_generation + from_snapshot registry 参数 + resume 透传）· qbot_rpg/world/snapshot_resume.py（世代重绑定 pick_registry_snapshot / rebind_registry_for_snapshot + 自检）· tests/unit/test_battle_snapshot_generation.py · tests/unit/test_snapshot_resume_rebind.py（+ 关联接缝：hot_reload/registry/repository/effects/chase_resume/resolve_or_degrade/test_snapshot_resume）
> 对照契约：docs/细化/细化_M6_热重载接线.md（D3）§二 RSM-01~09 + §2.3 F-RSM-01/02 + TC-RSM-01~07 + §2.1 P0-1 缺陷根因；WIR-14 运行期降级
> 门控：j-space **full 档**；已按 SKILL.md 唤醒 → 门控 → 接缝审计 → ship。

---

## 0. 结论摘要

| 级别 | 数量 | 摘要 |
|---|---|---|
| **P0** | **0** | 无致命/阻断级问题（RSM 三件套主体落地、半套禁绝的解析路径绑定完整） |
| **P1** | **2** | RSM-01 世代重绑定核心验收未测（TC-RSM-02/03 半套禁绝无断言）；RSM-02 "none" 降级路径不告警 + degraded=False（半套复发最高频路径静默） |
| **P2** | **6** | RSM-03~08（防御缺口 / AI 侧登记 / 测试质量） |

---

## 1. 维度① D3 契约落地（核对表）

| 契约点 | 判定 | 证据 |
|---|---|---|
| RSM-01 缺陷根因声明 | ✅ | battle.py 模块 docstring L4/工程补白 + start L890-892 注释；snapshot_resume.py docstring L16-21/L60-73 |
| RSM-02 快照 registry_generation 字段 | ✅ | battle.py start L893-896：`int(getattr(self._registry,"generation",0)) if registry else 0`；to_snapshot L1744 deepcopy 自动沿用（中断/回合边界同路径）；旧快照缺字段 → snapshot_resume.snapshot_registry_generation L178-187 默认 0（_num/bool 防御） |
| RSM-03 from_snapshot 透传 | ✅ | battle.py from_snapshot 增 registry 参数 L1779；透传 __init__ L1802（__init__ L297/L331 既有）；resume() L1842-1845 透传 self._registry；_make_battle_resolver registry 优先 L269-281 |
| RSM-04 续战入口世代重绑定 | ✅（集成测试缺 → P1-RSM-01） | snapshot_resume.pick_registry_snapshot L198-237（_snapshots N=2 + backup_snapshot 双口、exact/fallback/none/skipped 四态）；rebind_registry_for_snapshot L240-266（Registry.from_snapshot 重建）；resume_from_snapshot watcher 注入 L394-410 → factory(snap, registry=reg) |
| RSM-05 backup_snapshot 双口 | ✅ | hot_reload.py backup_snapshot() L414-421（批3A 激活死代码）；snapshot_resume L220-228 getattr+callable 防御消费 |
| RSM-06 快照存储世代持久化 | ✅ | repository.py upsert_session L732-747 `_payload_to_json(payload)` 整体序列化 → registry_generation 内嵌，无新列（L736-745 SQL 无 payload 列变化）；load_session L408-425 `_jloads(payload_json)` 原样返回；test_rsm_06 L64-94 覆盖往返 |
| RSM-07 F5 验收③ 断言 | ⚠️ 部分 | 世代字段往返（test_rsm_06）+ 世代绑定往返（rebind exact 一致）已覆盖；**「热重载后旧局按旧 registry 解析 / 新局新配置 / 双局并存互不串扰」未断言 → P1-RSM-01** |
| RSM-08 SessionManager 世代绑定契约 | ✅（契约态） | snapshot_resume 补白 9 L70-73 明确 D5 实装、本批不引入 session 依赖；F-RSM-02 同步登记。批边界正确 |
| RSM-09 世代一致性自检 | ⚠️ 部分 | fallback → degraded=True + `_logger.warning` L259-265 ✅；exact → False ✅；**none → 直接 return (None, status, target, None, False) 不告警、degraded=False → P1-RSM-02** |
| F-RSM-01 registry_generation（int 默认 0） | ✅ | battle.py L893 + snapshot_resume L178-187（类型/bool 防御） |
| F-RSM-02 session_generation（int 默认 0） | ✅（契约态） | 补白 9 登记 D5，本批不实现（正确） |
| WIR-14 运行期降级承接 | ✅（承接面） | resolve_or_degrade 入口由批3A 落地（content/resolve_or_degrade.py L29-65，Mapping 畸形防护已修）；本批 rebind 后引擎按旧 registry 解析（battle __init__ L323 → DamagePipeline(registry)；effects._make_resolver L187-194 复用统一入口），查无 → (None,True) 不抛【静态推导】；effects 消费丢弃 degraded 信号为批3A P2-F7 已登记，非本批 |

**维度①无问题项确认**：RSM-01/02/03/05/06/08 + F-RSM-01 落地无缺失；RSM-04 主体正确（四态取档 + 降级不拒绝恢复符合 ADR-D3-03）；半套禁绝的**解析路径绑定完整**——rebind registry 同时驱动 effects（pipeline L323）/marks（_resolver L333）/combo（L334-337）/defenses（_refresh_defenses）四路，无遗漏消费点【静态推导】。

---

## 2. 维度② 代码质量（P1 明细）

### P1-RSM-01【snapshot_resume.py L394-410 + battle.py L1837-1845 + tests】TC-RSM-02/03 核心验收无测试——世代重绑定端到端行为未锁定

- **现象（静态推导/全库 grep）**：
  1. 全 tests **无任何调用 `resume_from_snapshot(..., watcher=...)`**——watcher 注入 → pick → Registry 重建 → `battle_factory(snap, registry=reg)`（L407-412）这条 RSM-04 主链路零测试覆盖；
  2. **`BattleEngine.resume()` 透传 registry 无测试**（grep 无 `.resume(` 于 BattleEngine）；`from_snapshot(registry=...)` 仅 test_rsm_03 L51 断言 `eng2._registry is new_reg`（引用注入），**未断言引擎实际解析（resolve effects/statuses/marks）走旧 registry**——TC-RSM-03「旧局 resolve 走旧定义、新局走新定义、双局并存互不串扰」无任何断言；
  3. 接缝契约脆弱：现有 `_StubFactory`（test_snapshot_resume.py L108-120）`__call__(self, snapshot)` **不接受 registry 关键字**——watcher 注入且命中档时 resume_from_snapshot 调 `battle_factory(snap, registry=reg)` → stub 抛 TypeError → factory_error。真实工厂 BattleEngine.from_snapshot 接受 registry（L1779）故生产不炸，但该关键字约定无测试背书，契约断裂不报警。
- **影响**：P0-1 修复的**行为验收**（半套配置禁绝）无回归锁；后续装配层若误用不兼容 factory/stub，回归不可感知。
- **修复建议**：① 补 `test_resume_from_snapshot_watcher_rebind`：快照 generation=N + watcher(_snapshots=[snapN]) + battle_factory=真实 BattleEngine.from_snapshot → 断言 `out["resumed"]`、`rebind_status=="exact"`、`out["engine"]._registry.generation==N`、`engine.battle_state()["registry_generation"]==N`；② 补半套禁绝断言：同世代两套 defs（旧 effects 定义 A / 新定义 B），旧局 from_snapshot(registry=旧) 后 `eng.resolve_damage`/技能解析取 A、新局取 B，双局并存互不串扰；③ 补 `BattleEngine.resume()` 透传断言；④ 给 `_StubFactory` 加 `**kwargs` 或按补白 7 约定支持 registry 关键字。

### P1-RSM-02【snapshot_resume.py L255-256 + L234-237】RSM-09 自检在 "none" 降级路径不告警、degraded=False——半套复发最高频路径静默

- **现象（静态推导）**：快照世代已滚出 watcher N=2 窗口（旧局跨 ≥2 次热重载续战，`_snapshots` 全 > 目标世代，无 ≤ 档可取）→ `pick_registry_snapshot` 返回 (None,"none")（L234-237）→ `rebind_registry_for_snapshot` 走 L255-256 **直接 return (None,"none",target,None,False)**：无 `_logger.warning`、`degraded=False`。而该场景正是 **P0-1 半套配置的复发路径**（引擎回落默认/新配置解析旧 combatant 数值），且是全库最可能的现实触发（档案隔多次重载续战）。
- **契约对照**：RSM-09「续战绑定后校验 registry.generation == 快照世代（不匹配 → RSM-04 降级策略 + **日志**）」与 ADR-D3-03「…+ 告警」的告警义务在 none 分支未兑现；fallback（degraded=True+告警）与 none（静默）两条降级路径可观测性不一致。测试 test_rebind_none_not_bound L124-130 把 `degraded is False` 锁死，固化了该缺口。
- **修复建议**：none 分支补 `_logger.warning`（含目标世代 + 可用档世代范围，语义「无 ≤ 目标档可绑定，回退默认解析，半套风险」）；或将 `degraded` 语义扩展为 `degraded = (status != "exact")`（fallback 与 none 统一为 True，exact/skipped 为 False），并同步更新测试。功能侧「不拒绝恢复」符合 ADR-D3-03，本项仅收口可观测性。

---

## 3. 维度② 代码质量（P2 明细）

### P2-RSM-03【snapshot_resume.py L257 + L400-403】rebind_registry_for_snapshot 对畸形档无防护——Registry.from_snapshot 异常穿透 resume_from_snapshot

- `rebind_registry_for_snapshot` 的 `Registry.from_snapshot(snap)`（L257）不在任何 try/except 内；且 `resume_from_snapshot` 中 rebind（L400-403）位于 factory 的 try（L406）**之前**。若 watcher._snapshots 含非完整 RegistrySnapshot 的契约替身（缺 tables/names/modules_raw）→ AttributeError 直接抛给调用方，违反「降级不拒绝恢复」。真实 watcher 恒存 RegistrySnapshot（registry.py L27-41），防御面。
- **修复**：rebind 内包 try/except，捕获后按 (None,"none",target,None,True) 处理 + 告警；或先校验 snap 是否含 from_snapshot 所需四属性。

### P2-RSM-04【snapshot_resume.py L178-187 / L253】公开函数假定 snapshot 为 Mapping，自身无防护

- `snapshot_registry_generation(snapshot)` 与 `rebind_registry_for_snapshot(snapshot, ...)` 直接 `snapshot.get(...)`；非 Mapping（dataclass 快照形态）→ AttributeError。`resume_from_snapshot` 已先 L322 防 Mapping，但两个公开函数自身未防（对齐 `_num`/`_to_int` 的既有防御风格）。
- **修复**：两函数入口加 `isinstance(snapshot, Mapping)` 防护（非 Mapping → 世代按 0）。

### P2-RSM-05【battle.py L893-896】start 世代强转无类型防护

- `int(getattr(self._registry, "generation", 0))`：注入 registry 的 generation 若为非数值（str/None 外的畸形）→ ValueError 使 start 崩溃。契约 Registry.generation 恒 int（registry.py L98-99），防御面；测试替身用 int。建议 `_num` 校验回落 0（对齐 snapshot_registry_generation 口径）。

### P2-RSM-06【snapshot_resume.py L394-410】续战重建引擎不注入 enemy_ai——AI 侧回落 + AI 半套登记批次6/7

- `resume_from_snapshot` 只透传 `registry`（L407-412），不传 enemy_ai/enemy_def/ai_action_lib → 重建引擎 `_enemy_ai=None` → 怪物回落 M1 默认普攻（battle L1535-1536）。这是 M27 既有行为（非本批引入），但与本批「旧局旧配置」目标交互：若装配层以 partial 绑定**新** defs 构造 enemy_ai/ai_action_lib，则 AI 决策用新定义而战斗数值用旧 registry → **AI 侧半套**（RSM 只绑 effects/statuses/marks/combo，未含 AI action lib）。
- **修复/登记**：批次6/7 装配层经 rebind 后的 registry 派生 ai_action_lib（或 from_snapshot 增透传）；本批在 resume_from_snapshot docstring 补白 7 注明「enemy_ai 需调用方按 rebind 档重建」，防半套静默。

### P2-RSM-07【snapshot_resume.py L222-225】backup_snapshot() 失败静默吞 + 注释与实现不符

- `except Exception: bs = None`（L224）无任何日志；docstring 补白 7 L62-63 与注释「契约防御：取档失败按无此档处理，**不吞细节**」（L224）与实际行为（完全静默吞掉）不符。backup_snapshot 连续失败时双口降级不可见。
- **修复**：except 内 `_logger.debug/warning`（含异常类型），或改注释口径为「按无此档降级，不中断」。

### P2-RSM-08【tests】测试质量两处小项

- test_battle_snapshot_generation.py L40-43 `test_rsm_02_turn_boundary_snapshot_carries_generation` 名称「回合边界」实为 start 后 turn_start 边界（state=ACT、玩家未行动），**未真正走 turn_end（end_turn 后）边界或 interrupt_snapshot** 断言世代沿用——字段经 deepcopy 恒携带故功能无虞，建议补 interrupt_snapshot/turn_end 路径断言使测试名实相符；
- test_battle_snapshot_generation.py L91-94 `asyncio.get_event_loop().run_until_complete(...)` + RuntimeError 兜底：与 pytest-asyncio 事件循环策略耦合（test_storage.py 全用 `@pytest.mark.asyncio`），Python 3.12+ 主线程 get_event_loop 弃用告警、3.14 起可能由兜底转 asyncio.run 改变语义。建议直接 `@pytest.mark.asyncio` + await（对齐库内惯例）或统一 asyncio.run。

---

## 4. 维度③ 遗漏（TC 未覆盖 / 规则未实现 / 接缝）

| 项 | 判定 | 说明 |
|---|---|---|
| TC-RSM-01 世代字段往返 | ✅ | test_battle_snapshot_generation L27-43 + test_rsm_06 L64-94（含 JSON 往返）+ rebind 缺字段默认 0（L41-53/L140-146） |
| TC-RSM-02 续战世代重绑定 | ❌ 核心未测 | pick/rebind 单元级已测（test_snapshot_resume_rebind L59-146），但 `resume_from_snapshot(watcher=...)` 端到端 + `BattleEngine.resume()` 透传 + 「引擎按旧 registry 解析」未测 → P1-RSM-01 |
| TC-RSM-03 半套配置禁绝 | ❌ | 无「旧局 resolve 走旧定义 / 新局走新定义 / 双局并存互不串扰」断言 → P1-RSM-01 |
| TC-RSM-04 世代缺失/无档降级 | ⚠️ | fallback/none 取档态已测（L70-96/L152-167）；「引用 ID 在新配置已删 → resolve_or_degrade 降级不崩」**仅注释声明**（test_snapshot_resume_rebind L150-169），未真实引入 resolve_or_degrade 断言（批3A 已测四态，可接受但建议补 rebind 后 resolve 已删 ID 的联合用例） |
| TC-RSM-05 存储世代持久化 | ✅ | test_rsm_06（payload 内嵌 + 无新列口径；schema 无新列未直接断言，repository SQL 可证） |
| TC-RSM-06 F5 验收③ 快照冗余+世代绑定往返 | ⚠️ | 世代绑定往返已测（rebind exact）；「ID+名称冗余 resolve_name 可解析旧名」未覆盖（属 F5 验收③，建议补旧 registry 上 resolve_name 断言） |
| TC-RSM-07 SessionManager 契约 | ✅（契约态） | D5 依赖正确 defer，非本批范围 |
| 接缝：snapshot_resume ↔ hot_reload（backup_snapshot/_snapshots） | ✅ | 双口消费 L216-228 + hot_reload L414-421；deque 迭代/dedup/None 过滤齐 |
| 接缝：snapshot_resume ↔ battle.from_snapshot（factory 签名） | ⚠️ | 真实工厂兼容 registry 关键字；stub 契约无测试背书 → P1-RSM-01 |
| 接缝：battle ↔ repository（RSM-06） | ✅ | payload 透传即满足，无新列，无需新代码 |
| 接缝：battle.from_snapshot ↔ combo/effects/marks | ✅ | 四路均绑 rebind registry（L323/333/334-337）【静态推导】 |

---

## 5. 汇总清单

### P1（2）
1. **RSM-01** TC-RSM-02/03 核心验收无测试：`resume_from_snapshot(watcher=...)` 主链路、`BattleEngine.resume()` 透传、半套禁绝（旧局走旧定义/新局新定义/双局并存）全无断言；`_StubFactory` 不接受 registry 关键字，接缝契约无背书。修复见 §2。
2. **RSM-02** "none" 降级路径（世代滚出 N=2 窗口 = 半套复发最高频场景）不告警 + degraded=False，RSM-09「日志」义务未兑现；fallback 与 none 可观测性不一致。修复见 §2。

### P2（6）
3. RSM-03 Registry.from_snapshot 畸形档无防护，异常穿透 resume_from_snapshot（L257/L400-403）
4. RSM-04 snapshot_registry_generation/rebind 假定 Mapping，公开函数自身未防（L178-187/L253）
5. RSM-05 start `int(getattr(...))` 非数值 generation 崩溃（battle.py L893-896）
6. RSM-06 resume 重建引擎不注入 enemy_ai → AI 回落 + AI 侧半套登记批次6/7（L394-410）
7. RSM-07 backup_snapshot 异常静默吞 + 注释「不吞细节」与实现不符（L222-225）
8. RSM-08 测试质量：turn_boundary 测试名实不符 + test_rsm_06 事件循环模式耦合

### P0（0）

---

## 6. ship 确认（j-space full 档 · ship 前复读）

- **维度①**：RSM-01/02/03/05/06/08 + F-RSM-01 落地无缺失；RSM-04 主体正确；半套禁绝四路解析绑定完整——**无 P0 级缺失**；
- **2×P1**：其一为**验收测试缺口**（半套禁绝/世代重绑定行为未锁，非实现缺陷）；其二为 **RSM-09 none 路径可观测性缺口**（半套复发无告警）。均为本批可修项，修复点与行号已给出；
- **6×P2**：多为防御面/登记/测试质量，不阻塞批3B 组件验收；
- 运行行为结论（异常传播、rebind 解析绑定、事件循环等）均已标注【静态推导】，未在本环境执行任何验证。
