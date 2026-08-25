# 审查_M0复查_content_hot_reload（批2b-路2：热重载 hot_reload）

> 审查对象：`qbot_rpg/content/hot_reload.py`
> 对照基准：`细化_3e2_热重载契约.md`（v1.0）：触发 TRG-1~7 / 原子替换 ATO-1~7(F2) / 快照回退 SNAP-1~6(F3) / 旧局旧配置 OLD-1~8(F4) / 校验阻断 BLK-1~5(F5) / 验收 TC-01~14
> 辅助交叉核对：`qbot_rpg/content/{loader,registry,models,field_meta,__init__}.py`、`细化_3e_loader校验接线.md`、`tests/unit/{test_content,test_dsh_regress}.py`、旧审查 `审查报告/审查_M0_content_20260818.md`
> 方式：**纯静态审查，禁止运行任何命令/脚本/验证**；涉及运行行为的结论一律标注「静态推导」
> 日期：2026-08-24

**行数核对**：任务书标注 284 行，实测当前文件 **321 行**。284 与旧审查《审查_M0_content_20260818.md》记录一致（该版本为 P0-1/P1-1 修复前基线）；本轮文件为修复后版本，新增 `_last_attempt`/`detected` 防空转、`poll_once()` 等约 37 行。属任务元数据过期，非代码幻觉。

## 0. 结论摘要

- **P0：0 条**（主链路正确；防空转核心安全达成，无数据损坏/半套配置/死锁级问题）
- **P1：1 条**（BLK-5「自动暂停自动轮询转手动」未兑现 —— 旧审查 P0-1 的修复②未落地 + 模块 docstring 声称与实际不符）
- **P2：12 条**（含旧审查残留 P2-2/P2-9/P2-12/P2-15 与本轮新发现：日志留痕缺失、`poll_once` 生产零调用、自检 A 覆盖不全、陈旧监控、D-01 单位不一致等）

三条核心链路（触发检测 / 原子替换 / 快照回退）经静态推导均正确：`build_pack` 四参签名、`file_signature` 三元签名（mtime_ns+size+sha256）、`PackLoadError.errors/.report`、`Registry.snapshot/from_snapshot/integrity_check`、`pack.registry/.report` 等全部与调用点对齐，无接口错配。**防空转主修复（P0-1 的①）有效**：失败路径用 `detected` 回填 `_last_attempt`（L262-266），同签名坏包不再每 3s 空转（旧审查 P0-1 核心危害已消除，静态推导覆盖 manifest 变更/模块删除/引用断裂等场景均收敛）。

---

## 1. P1 问题（1 条）

### P1-1　BLK-5「自动暂停自动轮询」未兑现：`_paused` 从不被轮询循环消费（旧审查 P0-1 修复②未落地 + docstring 声称失实）【静态推导】

- **位置**：`run()` L128-150（循环 L142-149）、`poll_once()` L152-174、`_paused` 置位 L270 / 复位 L301 / 属性 L99-101；模块 docstring L8。
- **实际**：`self._paused` 在 `_fail_count >= _max_failures` 时置 True（L268-272），但 **`run()` 与 `poll_once()` 的循环/方法体均不检查 `_paused`**——置位后轮询循环照常每 `poll_interval_s` 执行 `_detect_changes`（L143），对新签名事件照常 `_reload_sync`（L147-148）。`_paused` 仅被：①赋值 ②`paused` 属性读出 ③写进 `ReloadResult.paused`（L279/309）④`_commit_success` 复位——**对轮询行为零约束**。
- **对照**：细化_3e2 BLK-5（L209）「连续失败计数→自动暂停自动轮询重载、转手动 /重载」；TC-09（L249）「自动轮询重载暂停（防空转，不空转）；手动 /重载 仍可触发」。旧审查 P0-1 修复建议②「`run()` 循环将 `_paused` 纳入判别」**未落地**（仅落地了①detected 写 `_last_attempt` 与③TC-09 测试）。
- **当前达成的安全**（静态推导）：同签名空转已被 `_last_attempt` 差分（L195-211「签名≠基线 且 ≠最近尝试」）杜绝，坏包不重试打转——BLK-5 的核心目的「防无人值守空转」达成。因此不判 P0。
- **残留偏差**：①paused 期间仍每 3s 对全部被监控文件做 stat+全量 sha256 IO（L203-210），「暂停」未省电未省 IO；②paused 期间作者新保存（新签名）仍**自动**触发重载，与「转手动 /重载」字面不符；③`ReloadResult.paused=True` 会向 M4 壳层/调用方发出「自动轮询已停」的误导信号（实际未停）。
- **测试盲区**：`test_dsh_regress.test_three_consecutive_failures_pauses`（L118-129）与 `test_content.test_hot_reload_consecutive_failure_pauses`（L382-399）只断言 `watcher.paused is True` 标志位，**从不驱动 `run()`/`poll_once()` 断言轮询停止**，故无法暴露此偏差。
- **修复建议**：
  1. `run()` 循环顶部加 `if self._paused and not <签名变化的新事件>: continue`（paused 时仅放行「签名≠基线 且 ≠最近尝试」的新事件一次、成功后复位——与旧审查建议②同语义）；`poll_once()` 同步：paused 且无新签名事件时直接返回 `last_result` 不重载；
  2. 或将该行为收敛为显式设计决策（沿用 C-3 补白格式写 ADR：paused 仅作状态标志、新签名仍自动重试、不停止轮询），并同步改写模块 docstring L8（删去「自动暂停自动轮询转手动」表述）与 `ReloadResult.paused` 注释（L47）；
  3. 补 TC-09 级断言：paused 后调用 `run()`/`poll_once()` 对新签名事件不得自动重载（手动 `reload()` 除外）。

---

## 2. P2 问题（12 条）

### P2-1　失败日志留痕缺失：F3⑤ / BLK-5「每次失败写脱敏日志（原因/触发源/时间戳）」无落点

- **位置**：hot_reload.py 全文无 `import logging`（L16-31 导入清单）、`ReloadResult` L37-53 无时间戳字段、失败路径 L257-285 仅写内存 `note`（原因+`[source=...]`，无时间戳）。
- **依据**：细化_3e2 F3 流程⑤（L143）「日志留痕（脱敏）：记录失败原因/触发源/时间戳」；BLK-5（L209）「每次失败写脱敏日志（原因/触发源/时间戳）」；TC-09（L249）「日志记录每次失败原因（脱敏）」。全库 grep：`qbot_rpg/` 仅 `core/formula_engine.py` 有 logging，content 层无；repo 亦无 commands/壳层消费 `ReloadResult` 落日志。
- **修复建议**：失败路径接入 `logging`（原因=errors/note、触发源=source、时间戳=time）、或确认日志归调用侧后补 `ReloadResult` 时间戳字段并登记调用侧接线（否则 TC-09 日志断言无落点）。

### P2-2　N=2 快照队列死数据结构（旧审查 P2-2 残留）

- **位置**：`self._snapshots`（L77 `deque(maxlen=2)`）仅 `append`（L299），**从不 `restore`/消费**；失败回退恒用 `pre = self._registry.snapshot()`（L227）+ `from_snapshot`（L259）。
- **对照**：D-04（L52）/SNAP-1（L150）「保留上一份校验通过的 registry 快照（N=2 档）」字面未兑现；语义上「当前有效=上一份校验通过」，回退目标正确（字节一致 L178 达成），故为契约形状缺口而非功能缺陷。
- **修复建议**：restore 分支消费 `_snapshots` 实现「连续两代都坏回更早一档」，或删除死队列并把 D-04 注释收敛为「单份当前有效」（旧审查同建议，未落实）。

### P2-3　TRG-6/D-02 轮询未走 apscheduler（旧审查 P2-9 残留）+ `poll_once` 生产零调用方

- **位置**：`run()` L128-150 为 asyncio `while+sleep` 循环；`poll_once()` L152-174 为 apscheduler 驱动接口；C-3 收敛标注 L136-139。
- **实际**：全库生产代码（`qbot_rpg/`）对 `HotReloadWatcher` 各方法（start/reload/run/poll_once/_backup_snapshot）**零调用**；`poll_once` 仅被 `tests/unit/test_dsh_regress.py`（L134-158）调用；repo 无任何 apscheduler 接线/壳层文件。TRG-6（L81）/D-02（L50）「轮询=apscheduler 定时任务」运行时未实现。
- **性质**：C-3 注释（L136-139）已显式标注「M0 零依赖可测默认、M4 壳层改用 poll_once+apscheduler」，属**已登记的递延补白**，非冒充定稿；但 TRG-6 字面未实现须留痕。注意 `run()` 与 `poll_once()` 是互斥两套驱动，M4 接线时需二选一（注释已声明收归壳层调度）。

### P2-4　`_backup_snapshot` 私有 + 零调用（OLD-1/OLD-2 挂点死代码；旧审查 P2-12 残留）

- **位置**：L316-318（私有方法，注释却称「对外供旧局旧配置结算引用」）。
- **实际**：全库零调用；`_` 前缀私有方法与「对外供」注释自相矛盾；D-05 引用计数 / SNAP-5 只读持有（L54/L188）在 content 侧亦未实现（依赖 GC+会话层持快照）。OLD-1~8 主体在会话层（不在本文件范围），本文件仅此一挂点且为死代码。
- **修复建议**：改为公开 `backup_snapshot()` 并登记会话层接线；或删除并注明 OLD 挂点在会话层。

### P2-5　自检 A 覆盖不完整（L248-249 声称「接口完整性」名实不符）

- **位置**：`_reload_sync` L248-249 调 `pack.registry.integrity_check()`；`registry.py` L184-196。
- **对照**：细化_3e2 自检 A（L215）要求「ID 唯一性（效果家族跨表 / 技能行动同库）、modules 声明 ⊇ 已加载模块、schema_version 一致」。`integrity_check` 仅做 per-kind ID 去重 + 名称冗余存在性，**未覆盖**跨表唯一、`modules ⊇ 已加载`、`schema_version` 一致性三断言。
- **修复建议**：补全 `integrity_check` 三断言（跨表唯一可依 namespace 表；modules⊇loaded 比对 manifest；schema_version 与 manifest 一致），或收敛注释措辞为「per-kind 去重 + 名称冗余自检」。

### P2-6　从 manifest 移除但文件仍在的模块被永久监控（陈旧 watch）

- **位置**：`_current_declared` L185 `watch = set(self._baseline.keys()) - {"manifest"}`（基线键永不收缩）+ L294-296 `_commit_success` 基线重建亦含陈旧模块。
- **实际**（静态推导）：模块 B 从 manifest 移除且 `B.json` 仍存在时，B 因在基线里被持续监控；后续 B 内容改动 → `_detect_changes` 报事件（L207-210）→ 触发整包重载，但 build_pack 只加载已声明模块 → 出现 `changed=()` 的「空重载」（note 显示 "reloaded 0 changed module(s)"）。TRG-5「未声明不加载」仍成立（不加载），但「未声明不监控」语义未达成，且空重载污染上报。
- **修复建议**：`_current_declared` 基线并集仅保留「manifest 仍声明」的模块（声明的权威来源），或对基线残留模块从 watch 剔除并在 `_commit_success` 同步清理基线。

### P2-7　失败路径 `ReloadResult.changed_modules=()` 上报失实

- **位置**：L228 `changed` 初值 `()`；`build_pack` 抛 `PackLoadError`（L237-240）时 L234-236 解包不完成 → `changed` 保持 `()`；结果对象 L276 用 `changed` 上报。
- **实际**（静态推导）：红拦/坏 JSON 主失败路径下，实际已重解析（或损坏）的模块清单只写进 `_last_attempt`（L262-266），不回传给 `ReloadResult.changed_modules`，调用方看到空清单。
- **修复建议**：失败路径将 `failed_mods` 一并填入 `changed_modules`（或新增 `attempted_modules` 字段）。

### P2-8　`run()` 无 try/finally，异常退出时 `_running` 残留 set

- **位置**：L141 `_running.set()`，L150 `_running.clear()` 仅正常退出执行。
- **修复建议**：`try: ... finally: self._running.clear()` 包住循环；或在 `stop()` 内一并 `_running.clear()`。

### P2-9　D-01 配置单位不一致（`poll_interval_s` vs 契约 `poll_interval_ms`）

- **位置**：L33/L63 参数 `poll_interval_s: float = 3.0`；细化_3e2 D-01（L49）配置键 `hot_reload.poll_interval_ms` 默认 3000。
- **风险**（静态推导）：M4 壳层若按 D-01 键名取值直传，会差 1000 倍（3ms 或 3000s）。当前无壳层接线故未爆。
- **修复建议**：统一单位（参数改 ms 或在 docstring 标注「秒，壳层须 ms→s 换算」）。

### P2-10　mtime 快筛未实现（每轮全量 sha256）

- **位置**：`_detect_changes` L203-210 对每个被监控文件调用 `file_signature`（loader.py L59-75，无 mtime_ns+size 命中即跳过哈希的快路径）。
- **对照**：细化_3e2 TRG-2（L77）「mtime 快筛 + 哈希」、loader docstring（loader.py L60）自称「mtime 快筛」。正确性无碍（判据满足），属性能与文档一致性缺口（loader 复查 P2-1 同款）。
- **修复建议**：命中 mtime_ns+size 快筛后再哈希，或收敛注释。

### P2-11　失败回退双倍深拷贝（旧审查 P2-15 残留）

- **位置**：L227 `pre = self._registry.snapshot()`（全量深拷贝）+ L259 `Registry.from_snapshot(pre)`（再深拷贝）。
- **修复建议**：性能优化项；或 registry 快照改为共享不可变表仅替换引用（省一次拷贝）。

### P2-12　引用清晰度：裸「L178」跨文档歧义

- **位置**：L221/258 的「字节一致，L178」未带「【规则】」前缀。对照基准中 L178 语义出自 ATO-4 引用的【规则】L178（细化_3e2 L118-119），旧审查亦用此简写，非编造。
- **修复建议**：统一为「【规则】L178」，避免与细化_3e2 自身行号混淆。

---

## 3. 各维度核验结论

### 维度① 错误 / 边界（bug / mtime / hash / 失败节流 / 快照回退）—— 无 P0，1×P1 + 多 P2

- **触发检测（TRG-2）** ✓：`file_signature` = mtime_ns+size+sha256 三元签名（loader L59-75），判据「mtime+内容哈希」达成；`_detect_changes`（L195-211）签名差分正确。
- **失败节流/防空转**：P1-1（paused 未约束循环）+ P2-1（日志）；**同签名空转已根治**（`detected` 回填 `_last_attempt`）。静态推导覆盖的场景均收敛：manifest 删除/损坏→回退基线+节流；模块删除（sig=None）→节流；包目录整体删除→回退旧 registry 持续服务（SNAP-2 服务不崩）；start() 失败→`_last_attempt` 节流但 start()/手动 reload 不受节流（显式调用可重试）；检测与装载间 TOCTOU（作者编辑中）→装载以最新文件为准，自愈。
- **快照回退（SNAP-1~3）** ✓ 主链路：失败不发布新对象（L259 重建旧）+ `restored=True` + 无半套配置（测试 test_content L377-378 断言注册表内容不变）；P2-2（N=2 队列未消费）、P2-11（双深拷贝）。
- **边界**：`_reload_sync` 宽 `except Exception`（L241-246）将 IO/意外异常兜为 R-5 `unexpected_error`（SNAP-2 语义正确，且掩盖 loader 侧异常——见 loader 复查 P1-2）；P2-6（陈旧监控）、P2-7（失败 changed 失实）、P2-8（_running 残留）。

### 维度② 缺漏（细化/定稿要求未实现）—— P1-1 + P2-1/2-3/2-4/2-5/2-9

- **已实现并确认**：TRG-1 三源合一（reload/poll 同管线 L120-126/147-148）✓；TRG-2 判据 ✓；TRG-3 增量（parse_cache 复用+全量重校验，loader L214-216）✓；TRG-4 新模块入监控（`_current_declared` 每轮重读 manifest L185-193）✓；TRG-5 未声明不加载（build_pack 只处理声明模块）✓；ATO-3/4/7 全量校验→通过才指针切换→失败不发布（L234-259）✓；SNAP-1~3 主链路 ✓；自检 B generation（ReloadResult.generation L48、`_commit_success` L292）✓。
- **未实现（含递延登记）**：BLK-5 暂停语义（P1-1）；失败日志留痕（P2-1）；TRG-6/D-02 apscheduler 接线且 `poll_once` 生产零调用（P2-3，C-3 已登记 M4 递延）；OLD-1/2 挂点 `_backup_snapshot` 死代码（P2-4）；自检 A 三断言不全（P2-5）；D-01 配置键单位（P2-9）。BLK-1~4/OLD-3~8/TC-10~14 属 validator/loader/commands/会话层范围，非本文件缺失。

### 维度③ 幻觉（注释引用行号真实性 / 冒充定稿 / 工程补白标注）—— 通过，1 处声称失实（并入 P1-1）

- **行号引用真实性** ✓：`细化_3e_loader校验接线.md` §4.1（L221 触发检测）/§4.2（L228 原子替换）/§4.4（L242 快照回退）/§4.6（L261 并发）逐一核实为真；细化_3e2 TRG/BLK/SNAP/D-01/D-04/自检 A/B 编号均存在。**未发现编造行号**。
- **冒充定稿**：无。C-3 收敛（L136-139）为显式【设计收敛，2026-08-18】工程补白标注，已声明 M0 默认/M4 收归壳层，未冒充定稿。
- **声称/行为不一致**：模块 docstring L8 称 BLK-5「自动暂停自动轮询转手动」已实现，与 `run()`/`poll_once()` 实际行为不符（P1-1）。
- **任务元数据**：284 行 vs 实际 321 行（旧审查版本行数，见页首核对），非代码幻觉。

---

*运行行为结论均标「静态推导」，未执行任何命令/脚本/验证；如需运行级证据请授权沙箱后补做。*
