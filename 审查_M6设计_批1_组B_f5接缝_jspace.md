# 审查：M6 设计 · F5 热重载接缝一致性（组B：与现有模块衔接）

- **审查对象**：`docs/实现层规划文档.md` F5 热重载原子性（L3436-3439）+ F4 校验器接线（L3431-3434）+ §9 风险（L3496，行 6）
- **审查依据（现有实现，全部静态阅读）**：`qbot_rpg/content/loader.py` · `content/validator.py` · `content/registry.py` · `content/hot_reload.py` · `content/field_meta.py` · `commands/router.py` · `core/battle.py` · `data/battle.py` · `world/session.py` · `world/snapshot_resume.py` · `core/effects.py` · `core/reward.py` · `storage/repository.py` · `docs/m5_shared_contract.md` · `docs/细化/细化_3e2_热重载契约.md` · 相关测试
- **方法**：静态审查，未运行任何命令/脚本（环境禁用 bash，结论均为静态阅读推导；凡涉及"运行时会怎样"的结论标注「静态推导」）
- **门控档位**：full（先对仓库实测核验简报行号，再按四维度交叉比对，ship 前一致性复核）

---

## 〇、简报行号核验（先证简报自身是否可信）

| 简报引用 | 实测 | 结论 |
|---|---|---|
| F5 L3436-3439 | 见 `实现层规划文档.md` 3429-3439，F5 起于 3436，实现要点 3438，验收 3439 | ✅ 相符 |
| F4 L3432-3434 | F4 标题 3431，实现要点 3432-3433，验收 3434 | ✅ 相符（简报"L3432-3434"含实现要点） |
| §9 风险 L3496 | 3496 = 行 6「热重载导致对局异常/半套配置」 | ✅ 相符 |
| M6 里程碑 L3481 | 3481 = M6 接线闭环（含热重载失败回退） | ✅ 相符 |
| G3 L3460-3463 | 3460-3463 = 故障注入套件（热重载失败用例在第 3462 行） | ✅ 相符 |

结论：简报行号全部实测相符，无幻觉引用。以下审查以此为准。

---

## 一、现有实现能力盘点（判据矩阵，静态阅读确认）

| F5 需求点（L3438） | 现有实现 | 衔接状态 |
|---|---|---|
| 按文件 mtime 增量 | `loader.file_signature`（mtime_ns+size+sha256，L65-81）+ `build_pack` parse_cache 增量解析（L235-250）+ `HotReloadWatcher._detect_changes`（hot_reload.py L217-233，TRG-2） | ✅ 实存 |
| 只重载变更模块 / 新模块纳入监控 | `_current_declared()` 每轮重读 manifest.modules 纳新（hot_reload.py L202-215）+ `changed_modules` 上报（TRG-3） | ✅ 实存（但"只重载变更模块"措辞含歧义，见 P2-1） |
| 校验失败 → 回退上一份 registry 快照 | `Registry.snapshot()/restore()/from_snapshot()`（registry.py L117-159）+ `HotReloadWatcher._reload_sync` 失败路径 `Registry.from_snapshot(pre)`（L285-295）+ N=2 快照 deque（L81/L327） | ✅ 实存 |
| 校验失败 → 人话提示 | `ReloadResult`（结构化 errors/warnings）就绪；**但无任何 shell/commands 消费翻译**（见 P2-6） | ⚠️ 半实存 |
| 先写临时文件再原子 rename | **无写入侧实现**（无编辑器；watcher 只负责轮询检测） | ❌ 缺（见 P2-2） |
| 进行中对局持旧快照（ID+名称冗余）、新对局新配置 | 内存中对局：`BattleEngine` 构造期绑定 registry 对象引用（battle.py L331），旧对象随指针替换被持有 → 在途战斗天然用旧配置；**续战/读档路径无旧配置重绑定机制**（见 P0-1） | ⚠️ 半实存（关键缺口） |
| 删除配置按"无效果/无链/无印"降级不报错 | content 侧 `Registry.resolve` 删除后返回 None；运行时单点降级已实现：`effects.apply_status` 未知 status → `unknown_status`（effects.py L463-467）、`reward._grant_item` item 缺失 → skip（reward.py L156-209）；**无会话层统一降级入口、无端到端接线**（见 P1-3） | ⚠️ 半实存 |

另核：F5 验收①（非法 JSON → 回退不崩）有测试 `tests/unit/test_content.py::test_hot_reload_failure_rollback`（L507-523）；验收②（变更单模块仅重载该模块 mtime 断言）有测试 `test_hot_reload_success_incremental`（L489-504，断言 `changed_modules==("items",)`）；验收③（进行中对局持旧配置快照冗余断言）**无测试、无实现**。

---

## 二、问题清单

### P0（必清，1 项）

#### P0-1 旧局旧配置对「续战/读档对局」失效：续战引擎无法重绑定旧 registry → 半套配置
- **位置**：设计 = `实现层规划文档.md` L3438「进行中对局持旧快照（ID+名称冗余）、新对局用新配置」；实现缺口 = `core/battle.py::from_snapshot`（L1768-1819，**签名无 registry 参数**，构造时 `registry=None`）、`core/battle.py::resume`（L1821-1825 仅透传 `self._pipeline/self._defs`）、`world/session.py`（L24-40 **全 NotImplementedError 桩**）、`content/hot_reload.py::_backup_snapshot`（L344-346 **声明"对外供旧局旧配置结算引用"但全仓无调用方**）、`storage/repository.py`（快照存储无 registry 世代字段）。
- **问题**：F5 承诺的「旧局旧配置」只对**内存中在途战斗**成立（引擎持旧 registry 对象引用）。一旦对局被打断/存档，**热重载后从快照续战**：
  - 敌方战斗数值从 `_snap` 还原（start 时已快照进 combatant dict，battle.py L872-893，旧值 ✓）；
  - 但效果/状态/印记解析依赖 `from_snapshot` 注入的 `pipeline/defs`——调用方若传当前（新）registry，续战对局即**旧 combatant 数值 + 新 effects/status/marks 解析**混跑，等于「半套配置」，直接违反 F4 L3432「绝不半套配置运行」铁律与细化_3a H4。
  - 「ID+名称冗余」本身不足以解决续战：冗余只够显示层防悬空（`Registry.resolve_name`），**还原解析用配置仍需旧 registry 对象或世代绑定**，而快照内无 registry 世代、无旧配置快照，`_backup_snapshot` 无人调用。
- **修复建议**（M6 接线必做，三选一或组合）：
  1. `BattleSnapshot/1g3 dict` 增加 `registry_generation` 字段；续战入口按世代从 `HotReloadWatcher._snapshots`（N=2 滚动，含上一份）取对应 registry 快照重建 `Registry` 注入 `from_snapshot`；
  2. 或 `from_snapshot` 增加 `registry` 参数并在 `BattleEngine.__init__` 透传（当前签名缺该参数是明确的接口缺漏）；
  3. 或在会话层（`world/session.py` 实装时）按「会话创建时刻的 registry 世代」持久化绑定，并落 F5 验收③ 断言（快照冗余 + 世代绑定往返）。
- **点名**：应覆盖「续战/读档对局在热重载后仍按旧 registry 结算」，现有实现无「对局快照携带 registry 世代 / 旧 registry 重绑定」机制。

### P1（高优，3 项）

#### P1-1 F4 验收⑤「校验器调用点登记表与 loader 对照」未落地 → 校验空转旧教训可复发
- **位置**：`实现层规划文档.md` L3434 验收⑤；实现 = `content/validator.py::_check_module`（L465-469，`mmeta is None: return` 默认放行）、`content/field_meta.py::_module_table()`（登记表）、`content/loader.py::_KIND_FOR_MODULE`（L150-172）。
- **问题**：validator 的"必经"依赖 field_meta 登记；**未登记的模块名默认放行**（§2.3 兜底）。loader 的 `_KIND_FOR_MODULE` 与 field_meta 模块表是两套独立登记，**仓库内无任何测试/静态检查保证「新增模块同时进 loader 与 field_meta」**（全仓未找到 _KIND_FOR_MODULE ↔ field_meta 的对照断言；test_content.py L78-111 只覆盖 M4 四模块个案）。若 M6 加新模块只改 loader 不改 field_meta → 注册进 registry 但零校验，正是 §9 风险 1「校验空转」的复发通道。
- **修复建议**：新增对照测试（遍历 `loader.FIXED_REGISTER_ORDER ∪ _KIND_FOR_MODULE ∪ manifest 声明模块` 断言 ⊆ field_meta 模块表，缺失即 fail）；或引入 CI 静态检查脚本，落地 F4 验收⑤。
- **点名**：应覆盖「新增模块未接线校验器 → CI 拦截（登记表对照）」，现有实现无该对照。

#### P1-2 F4 验收③「红/黄计数日志断言」缺失；校验结果无可观测计数出口
- **位置**：`实现层规划文档.md` L3433「校验结果可观测（日志记录红/黄计数与模块名，供编辑器红显）」+ L3434 验收③；实现 = `validator.py::check_pack`（L1781-1790 返回 errors/warnings **列表**，无计数结构）、`hot_reload.py::_reload_sync`（L262-266 仅失败路径日志计数）、`tests/`（全仓无 caplog/assertLogs 断言计数）。
- **问题**：启动路径（`load_pack`/`build_pack`）仅在红拦阻断时记错误数（`_raise_if_blocked` L276-281），**黄提示计数与逐模块红/黄明细无日志**；编辑器红显所需的「每模块 红/黄 计数」无可消费接口。F4 验收③ 无断言 → 未来编辑器接线时该可观测性需重做。
- **修复建议**：`ValidationReport` 增加计数属性（`count_errors/count_warnings` 按模块聚合）或 hot_reload/load 路径输出结构化模块级红黄计数日志；补日志断言测试（F4 验收③）。
- **点名**：应覆盖「红/黄计数可观测 + 日志断言」，现有实现无断言、启动路径无黄计数日志。

#### P1-3 F5「删除配置降级不报错」边界未界定，设计文本与 validator R-4 行为易冲突
- **位置**：`实现层规划文档.md` L3438「删除配置按'无效果/无链/无印'降级不报错」；对照 = `validator.py` R-4（L1674-1677，引用不存在红拦）+ 细化_3e2 L258/TC-26（新局引用已删 ID → 红拦）。
- **问题**：F5 文本按字面读会被误读为「删除配置一律不报错」。实际语义是二元的：
  - **配置加载期**：被其它模块引用的配置被删 → R-4 红拦 → 整包回退（删除不生效，正确）；
  - **运行期（旧局）**：`resolve→None` → `apply_status` unknown_status / reward skip（已实现降级，静态推导）。
  F5 未区分这两层，M6 实现者按字面「降级不报错」做会在配置期跳过 R-4（危险）或误以为回退是 bug。另：删除降级**无会话层统一入口**，各消费点（effects/reward/marks/combo/quest）自行降级，无注册表式收口。
- **修复建议**：F5 文本补一句边界说明：「配置期被引用删除 → R-4 红拦回退；运行期旧局引用已删配置 → resolve→None 按无效果/无链/无印降级不抛异常」；M6 可在 content 层加统一降级工具函数（`resolve_or_degrade`）供消费点复用。
- **点名**：应覆盖「删除降级的配置期/运行期边界与统一降级入口」，现有实现仅 content 单点 + 各消费点自降级、无统一收口。

### P2（可延后/澄清，6 项）

#### P2-1 F5「按文件 mtime 增量校验，只重载变更模块」措辞歧义（应=解析增量+校验全量）
- **位置**：`实现层规划文档.md` L3438；实现 = `loader.py::build_pack`（B 阶段增量解析 L235-250，C 阶段 **全量** `check_pack` L252-260）。
- **问题**：按字面「增量校验」实现（跳过未变更模块校验）会漏跨模块悬空引用（如 A 改了引用、B 未变），违反 F4「绝不半套」。当前实现正确（解析增量、校验全量，TRG-3），但设计文本未澄清。
- **修复建议**：L3438 改「按文件 mtime 增量**解析**，只重新解析变更模块；校验仍**全量**（跨模块引用需全量重跑）」。

#### P2-2 F5「先写临时文件再原子 rename」无实现对应物（写入侧=编辑器，未实现）
- **位置**：`实现层规划文档.md` L3438；现状 = 无编辑器代码，`HotReloadWatcher` 仅轮询检测（hot_reload.py）。
- **问题**：原子写是**写入侧**契约（编辑器里程碑），当前由 watcher 的失败重试（同签名防空转）兜底容忍非原子写（写一半 → 非法 JSON → 失败回退 → 作者写完改签名 → 重试成功）。非缺陷，但 F5 把写入侧契约列为实现要点时无对应物，M6 若不接编辑器则该行空转。
- **修复建议**：F5 标注该要点归属编辑器（细化_5a SV-08），loader 侧补一条「部分写入容错」说明。

#### P2-3 指令注册表（router）无快照/回退；register(replace=True) 声明的热重载路径无调用点
- **位置**：`commands/router.py::register`（L201-208，注释声明"热重载/内容包升级"）、Router 类（L187-229，无 snapshot/rollback）、全仓 register 调用点（battle/explore/quest/shop/checkin/gm/basic_commands 均代码静态注册，**无 replace=True 调用**）。
- **问题**：指令是代码注册，热重载内容不触发指令重注册 → F5 不要求 router 快照，**当前无缺陷**。但 register(replace=True) 注释与 `check_shortcut_binding` C01 冲突检测提及的「内容包注册指令」（L836）是**已声明未接线**能力；若 M6 引入内容包驱动指令注册，需补 router 快照/回退。
- **修复建议**：M6 若引入内容驱动指令，`Router` 增加 snapshot/restore 或按注册批次回滚；否则删除 replace 注释中的"热重载"字样防误导。

#### P2-4 M5 渲染层在热重载下无明确行为：message_prefix 显示配置不随旧局快照
- **位置**：`docs/m5_shared_contract.md` §1.4（M5-01 前缀接线 ⬜）+ `validator._check_message_prefix`（已实装）+ F5 L3438（未声明渲染层归属）。
- **问题**：`message_prefix` 为 settings 配置、渲染时 live 读取（静态推导：接线后每次渲染经 prefix_render 消费当前 settings），热重载后**在途/旧局消息立即用新前缀格式**，与「旧局旧配置」的数值侧不一致（cosmetic）。battle_render BREP 模板为代码、不随热重载（稳定 ✓），但 F5 未显式声明「渲染模板/显示配置不在旧局快照范围」。
- **修复建议**：M5 装配层确认前缀按「每消息实时读配置」还是「会话级快照」，并在 F5 补一句显示配置边界。

#### P2-5 m5_shared_contract 状态表与实现不同步（message_prefix 校验器已实装仍标 ⬜）
- **位置**：`docs/m5_shared_contract.md` L66「message_prefix 校验器 … ⬜ M5-02 接线」 vs `validator.py` L1392-1476 `_check_message_prefix`（已实装、含 MP-1/MP-2）。
- **问题**：跨文档陈旧（实现先行、契约表未回填）。非 F5 核心，但组B 审查维度的"现有实现与文档一致"问题。
- **修复建议**：回填 m5_shared_contract §1.4 状态列。

#### P2-6 HotReloadWatcher 未被任何 engine/commands 接线（M6 待办，需点名）
- **位置**：全仓仅 `content/__init__.py` 导出；`commands/gm_commands.py` 的 /重载 仅测试 FakeGmBackend 声明 `reload_content` 接口（test_gm_commands.py L104-115）。
- **问题**：热重载组件实存且自测完备，但**启动装载（`watcher.start()`）、apscheduler/轮询驱动（`poll_once`）、/重载 指令真实后端、ReloadResult→人话提示翻译**均未接线（M6 职责，符合预期）。点名以防 M6 漏掉人话提示这一 F5 验收点（验收①要求"人话提示"）。
- **修复建议**：M6 接线清单显式含四项：start 装载、调度驱动、/重载 后端、ReloadResult 翻译。

---

## 三、四维度结论

### ① 缺漏（接缝重点，点名清单）
| 应覆盖 X | 现有实现无 X | 级别 |
|---|---|---|
| 续战/读档对局按旧 registry 结算（registry 世代 / 旧快照重绑定） | `from_snapshot` 无 registry 参数；快照无世代；`_backup_snapshot` 死代码；SessionManager 桩 | P0-1 |
| F4 验收⑤ 校验器登记表与 loader 对照 CI | 无 _KIND_FOR_MODULE ↔ field_meta 对照测试/静态检查 | P1-1 |
| F4 验收③ 红/黄计数日志断言 | 全仓无计数日志断言；启动路径无黄计数日志 | P1-2 |
| 删除降级的配置期/运行期边界界定 + 统一降级入口 | F5 未区分；无统一收口（仅 content 单点 + 各消费点自降级） | P1-3 |
| F5 原子写（临时文件+rename） | 无写入侧实现（编辑器未实现），watcher 仅失败重试容错 | P2-2 |
| 热重载人话提示 + /重载 真实后端 + 启动装载/调度驱动 | HotReloadWatcher 全未接线；gm reload 仅测试桩接口 | P2-6 |
| M5 渲染层热重载行为（显示配置快照 or 显式排除） | F5 未声明；message_prefix live 读取不随旧局 | P2-4 |

### ② 错误（与现有模块签名/行为冲突）
- **无明显签名冲突**：`load_pack(pack_dir, meta, generation)` 无 mtime 参数不构成冲突——mtime 由 `file_signature` 内部实现，F5 未要求该签名（静态推导）。`validator` 无红黄计数字段不冲突（列表可派生），缺的是可观测出口与断言（P1-2）。`router` 无快照回退不构成 F5 冲突（指令为代码注册），仅已声明未接线（P2-3）。
- **潜在行为冲突（P1-3）**：F5「删除配置降级不报错」字面与 validator R-4（被引用删除 → 红拦回退）二元语义未区分，按字面实现会冲突。
- **M5 渲染层（P2-4）**：battle_render 为代码模板、不受热重载影响（稳定）；唯一需关注的是 message_prefix 显示配置 live 读取，F5 未定义其快照归属。

### ③ 幻觉（有无编造现有实现能力）
- **F5 设计文本本身无编造现有能力**：L3438 各要点均为「未来实现点」或对现有组件（file_signature/registry snapshot/hot_reload）的正确引用。
- **关键提示**：任务点名的「已有 registry 快照」**真实存在**（registry.py L117-159 + hot_reload N=2），非幻觉——不可误判为编造。
- **真正的"幻觉前提"在 P0-1**：F5「进行中对局持旧快照（ID+名称冗余）」隐含「冗余即足以防热重载失效」，但 ID+名称冗余只够显示层，**续战解析用旧配置需世代/旧快照重绑定**——这是设计建立在未实现的机制之上（近似幻觉前提），已在 P0-1 点出。

### ④ 跨文档（F5↔M6↔G3↔F4↔细化_3e2）
- **F5 ↔ M6（L3481）**：M6 verify「热重载失败回退不崩」有实现支撑（回退测试在案）；但 M6 不含「旧局旧配置续战」验收，P0-1 缺口在 M6 门禁外 —— 需补进 M6 验收。
- **F5 ↔ G3（L3460-3463）**：G3 故障注入「写入非法 JSON 触发重载 → 回退旧 registry 不崩」与 F5 验收① 同源，实现/测试已在（test_content.py L507-523）✅；G3 的「人话提示」依赖 P2-6 接线。
- **F5 ↔ F4（L3432-3434）**：F4「回退上一份校验通过快照」实存；F4 验收③⑤ 未落地（P1-1/P1-2）。
- **F5 ↔ 细化_3e2**：热重载契约（TRG/SNAP/BLK/OLD）在实现中大面积落地（hot_reload.py 每行注释对应），衔接良好；唯一断点是 OLD-1/OLD-2「旧局旧配置」的世界层/存储层（P0-1）。

---

## 四、结论
- **门控档位**：full
- **结论**：**P0 × 1 / P1 × 3 / P2 × 6**。F5 热重载的 content 层（mtime 增量、快照回退、防空转、失败节流）已高完成度实存且自测完备；主要接缝缺口集中在**世界/存储层**（续战旧配置重绑定，P0）与**F4 验收的可观测/对照测试**（P1）。设计文本无编造现有能力，但「旧局旧配置」依赖一个尚未实现的重绑定机制（P0 幻觉前提）。

### Top 3（8 行内）
1. **P0-1 续战=半套配置**：`from_snapshot` 无 registry、快照无世代、`_backup_snapshot` 死代码、SessionManager 全桩 → 热重载后读档续战 = 旧数值+新效果解析，违反 F4「绝不半套」；需世代绑定+旧快照重绑定并补 F5 验收③。
2. **P1-1 登记表对照缺失**：validator 未登记模块默认放行（validator.py L468-469），无 `_KIND_FOR_MODULE`↔field_meta 对照测试 → 「新增模块零校验」校验空转复发通道，F4 验收⑤ 未落地。
3. **P1-3 删除降级二元边界未界定**：F5「删除降级不报错」字面与 R-4 红拦回退冲突，且无统一降级入口；需文本澄清「配置期红拦回退 / 运行期 resolve→None 降级」，并补 P1-2 红黄计数可观测。
