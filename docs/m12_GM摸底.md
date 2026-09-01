# M12 GM 摸底：5b 契约 vs 现状代码缺口清单

> 性质：纯摸底文档（不改任何代码）。契约唯一权威 = `docs/细化/细化_5b_GM指令契约.md`（346 行）；现状代码 = `qbot_rpg/commands/gm_commands.py`（920 行）等。
> 标注口径：【已实现】= 契约要求已有代码承载；【已声明未接线】= 有契约声明/壳/消费接口，但无真实后端或未注入；【缺】= 现状无对应物。
> 行号引用：`契约 Lxx` = 细化_5b；`gm Lxx` = qbot_rpg/commands/gm_commands.py；其余文件单独标注。
> 结论摘要：G1-G14 中 **5 条已实现**（G1/G8/G10/G13/G14）、**9 条待接线**（G2-G7/G9/G11/G12）；权限模型核心判定已实现、admin_users 存储层缺失；审计记录构造已实现、audit_log 表与 store 缺失；WIR 三键 `gm_backend`/`permission_store`/`audit_store` 全部**声明但未注入**（生产装配显式置 None）。

---

## 一、5b 契约逐条核对：14 条指令 G1-G14

### 已实现 5 条（L160 长清单）

**G1 `/重载 <内容包>`** ——【已实现】
- 契约：`契约 L89、L108-112`（权限 GM；1 位置参数；热重载摘要 + 失败项清单）。
- 现状：处理器 `cmd_gm_reload`（gm L630-656）；权限 `GM_COMMAND_LEVEL`（gm L186-192）；注册 `register_gm_commands`（gm L889-920，is_gm=True）。
- 真实后端：`GmBackend.reload_content`（gm L449-483）= `HotReloadWatcher.reload` 同一条管线（gm L506-525 `_run_watcher_reload`）。
- 缺口：热重载 watcher 实例由装配层注入（`GmBackend(watcher)`，gm L442-443），现状无装配方构造 GmBackend。

**G8 `/日志`（GM 版）** ——【已实现】
- 契约：`契约 L96、L144-147`（权限 GM；`条数=N` 默认 20 上限 50；系统日志最近事件）。
- 现状：处理器 `cmd_gm_log`（gm L694-730）；常量 `LOG_DEFAULT_SHOW=20`/`LOG_MAX_ENTRIES=50`/`LOG_PAGE_SIZE=5`（gm L212-218）；渲染 `render_log_line`/`render_log_page`（gm L791-820）；`/日志` 双分支中仅 GM 版在本模块（gm L72-73 工程补白 4）。
- 缺口：数据源 `_backend(ctx).recent_audit`（gm L715）= audit_log 表，表不存在、后端未接线。

**G10 `/封禁 <QQ号> [时长] [原因=...]`** ——【已实现】（壳层）
- 契约：`契约 L98、L155-159`（权限 GM；时长默认永久；封禁留痕 E4）。
- 现状：处理器 `cmd_gm_ban`（gm L659-691）；QQ 纯数字校验（gm L668）、时长默认 `BAN_DEFAULT_DURATION="永久"`（gm L221）、`原因=` 键值解析（gm L674-676）；审计 E4 字段 target/时长/到期/原因入 detail（gm L684-689）。
- 缺口：真实封禁引擎 `_backend(ctx).ban_player`（gm L677）未接线；封禁名单存储、被封玩家游玩指令「人话提示」分支（契约 §3.3 L216）**全仓无实现**（见五-10）。

**G13 `/编辑`** ——【已实现】（壳层）
- 契约：`契约 L101、L167-168`（机主/GM；编辑器链接 + 权限级提示）。
- 现状：处理器 `cmd_gm_edit`（gm L733-747）；按 `perm.level` 取链接与提示（gm L740）。
- 缺口：`_backend(ctx).editor_link`（gm L740）未接线；编辑器链接配置源缺失（M12 5a 六页壳交付物）。

**G14 `/设置`** ——【已实现】（壳层）
- 契约：`契约 L102、L170-173`（机主；`=键值` 语法；切换群级配置即时生效）。
- 现状：处理器 `cmd_gm_settings`（gm L750-775）；缺参/超参/空值校验（gm L755-766）；权限列 = ROLE_ADMIN（gm L191），manager 需 per-command 下授（gm L79-80 工程补白 7）。
- 缺口：`_backend(ctx).apply_setting`（gm L767）未接线；`command_mode=global_shortcut` 等键值对实际生效链路无实现。

### 待接线 9 条（不在 L160 长清单）

| # | 指令 | 契约 | 现状 | 判定 |
|---|---|---|---|---|
| G2 | `/备份` | `契约 L90、L114-116` | `GmBackend.backup_content` 契约声明，调用抛 NotImplementedError「【待接线】」（gm L485-493）；无指令注册、无处理器、无路由 | 【已声明未接线】 |
| G3 | `/恢复` | `契约 L91、L118-120` | `GmBackend.restore_content` 契约声明，调用抛 NotImplementedError「【待接线】」（gm L495-503）；同上 | 【已声明未接线】 |
| G4 | `/存档导出` | `契约 L92、L122-125` | 无任何代码物（无指令名常量/无处理器/无后端方法声明） | 【缺】 |
| G5 | `/调试` | `契约 L93、L127-130` | 无任何代码物 | 【缺】 |
| G6 | `/测试` | `契约 L94、L132-135` | 无任何代码物 | 【缺】 |
| G7 | `/广播 <消息>` | `契约 L95、L137-142` | 无任何代码物（契约明确标注【细化指令入口】） | 【缺】 |
| G9 | `/玩家查询 <QQ号>` | `契约 L97、L149-153` | 无任何代码物（契约标注【细化指令入口】） | 【缺】 |
| G11 | `/解封 <QQ号>` | `契约 L99、L161-162` | 无任何代码物 | 【缺】 |
| G12 | `/封禁列表` | `契约 L100、L164-165` | 无任何代码物（契约含分页语法细化） | 【缺】 |

- 自我声明依据：gm L62-65 工程补白 1「另有 G2-G7/G9/G11/G12（备份/恢复/存档导出/调试/测试/广播/玩家查询/解封/封禁列表）等 9 条不在本批范围——留待批次6/7 其它路或后续批次」；gm L436-439 WIR-08「/备份 /恢复 真实后端 = 已声明未接线」。
- 契约侧 G2/G3 有独立依据行（`契约 L90-91`），其余 7 条中 G5/G6/G7/G9 契约自身标注【细化】或【细化指令入口】（`契约 L94、L95、L97、L132、L137、L149`）。

---

## 二、权限模型核对（契约 §1，L33-76）

### 2.1 admin_users 表（契约 §1.2 L52-62）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| admin_users 表：{qq_id, role: owner\|gm, granted_commands[], granted_by, granted_at, revoke_log} | 契约 L56 | schema.py 现有 7 表（players/sessions/idempotency_keys/meta/world_state/recycle_bin/backups，schema.py L29-135）**无 admin_users**；全仓 grep `admin_users` 仅契约/启动包/审查文档提及，无建表 SQL | 【缺】 |
| 权限缓存：进程内存 {qq_id: role}，启动全量加载，热重载不重建 | 契约 L57 | 无权限缓存实现 | 【缺】 |
| 玩家存档不含权限字段（防拷贝伪造） | 契约 L58、L61 | players 表 20 列（schema.py L32-55）无任何 role/gm/ban 权限字段；player.py 无权限/封禁字段 | 【已实现】（现状即满足，属天然合规） |
| 机主初始写入：安装向导写 owner，不经指令 | 契约 L60 | 无安装向导/机主写入逻辑；`deps.permission_store = None`（assemble.py L169） | 【缺】 |
| 机主身份变更仅编辑器/数据库操作 | 契约 L60 | 无相关代码 | 【缺】 |
| 权限变更即时生效 + 变更写审计 E5 | 契约 L62 | E5 无实现（见 §三） | 【缺】 |

### 2.2 三级权限判定（契约 §1.1 L35-50）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| 三级：机主 > GM > 普通玩家 | 契约 L37-43 | `ROLE_ADMIN/ROLE_MANAGER/ROLE_PLAYER`（gm L173-175）+ `check_gm_permission` 判定优先级（gm L286-308）；router 侧 `PERM_OWNER/PERM_GM/PERM_USER`（router.py L76-78）一一对应 | 【已实现】 |
| 默认授予集 = 指令表标 GM 全部（重载/备份/恢复/日志/编辑/封禁/解封/封禁列表） | 契约 L49 | `GM_DEFAULT_GRANT` = 由 GM_COMMAND_LEVEL 推导（gm L196-198）；但 GM_COMMAND_LEVEL 仅含 L160 5 条（gm L186-192），**备份/恢复/解封/封禁列表不在集合**（因指令未注册） | 【已实现】（5 条范围）；【缺】（9 条接入后需扩表） |
| 机主专属可下授（存档导出/调试/测试/广播/玩家查询/设置） | 契约 L49 | manager 走 `user.granted_commands` 放行（gm L305-306）；设置=机主专属已按此口径（gm L191）；但 granted_commands 的**授予/撤销操作（E5）无实现** | 【已实现】（判定侧）；【缺】（授权操作侧） |
| 判定优先级同人命中高级别 | 契约 L43 | role_of 归一后单角色判定（gm L279-283、L298-308） | 【已实现】 |
| GM 不自动授予群管理 | 契约 L44 | 无群管理映射代码 | 【已实现】（现状即默认不映射） |
| 静默语义：无权限 → 零出站零审计 | 契约 L45 | `silent_result()`（gm L339-341）+ `handle_gm_command` 静默分支（gm L875-877）+ 装配层 `_dispatch_gm_result`（runner.py L338-350）+ 路由前门控 RA-10（runner.py L648-650） | 【已实现】 |
| 权限存储不进玩家存档 | 契约 L58、L61 | players 表无权限字段（schema.py L32-55）；GmUser 类显式声明唯一事实来源 = admin_users（gm L236-241） | 【已实现】 |

### 2.3 granted_commands 下授（契约 §1.1.1 L49、§1.4）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| per-command 粒度存数据库 granted_commands 表 | 契约 L49 | 无表（同 2.1）；`GmUser.granted_commands` 仅为内存快照（gm L243-251） | 【缺】 |
| 机主可在编辑器/数据库设置调整 | 契约 L49 | 无 | 【缺】 |
| 权限变更即时生效（内存缓存失效重载） | 契约 L62 | 无缓存实现 | 【缺】 |

### 2.4 GM 禁绑（契约 §3.2 L194-209）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| 绑定层：绑定目标为 GM 指令 → 拒绝 | 契约 L198 | `gm_binding_guard`（gm L841-853）→ `router.check_shortcut_binding`（router.py L804-830，C02 判定 L828） | 【已实现】 |
| 白名单层：GM 永不快捷、强制 / 前缀 | 契约 L199 | `GM_PREFIX_REQUIRED`（gm_constants.py L48-50）+ parsers `DEFAULT_PREFIX_REQUIRED` 含 5 条（parsers.py L159-160）；CommandSpec.is_gm → 路由层 W07 拦截裸发（router.py L485、L564） | 【已实现】（5 条范围） |
| 执行层二次检查（快捷脏数据兜底） | 契约 L201 | `handle_gm_command` 入口再判权限（gm L860-882，TC-24 口径）+ 装配层 RA-10 前门控（runner.py L233-242、L648-650） | 【已实现】 |
| 别名层：GM 不可别名化，校验器拒绝 | 契约 L202 | 无 GM 别名校验器代码（别名装载 router_setup.py L649/665 引用 AliasTable，未见 GM 指向拒绝逻辑） | 【缺】 |
| 触发层：prefix_only 下快捷名也要 / 前缀 | 契约 L203 | 由 is_gm 注册 + W07 覆盖（router.py L485、L564） | 【已实现】 |

### 2.5 群管理映射（契约 §1.3 L64-69）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| 默认不映射（群主/群管理 ≠ GM） | 契约 L66 | 无映射代码（现状默认满足） | 【已实现】 |
| `allow_group_admin_map: false` 可配项 | 契约 L67 | 配置键无任何读取点 | 【缺】 |
| 开启后群主映射受限 GM、入退群即时生效 | 契约 L67 | 无 | 【缺】 |
| 映射 GM 不可再授予他人 | 契约 L69 | 无 | 【缺】 |

### 2.6 校验时机：绑定层 + 执行层双检查（契约 §1.4 L71-75）

- 绑定层拒绝：已实现（见 2.4）。执行层权限二次检查：已实现（gm L860-882 + runner L648-650）。
- 内容包注册层：GM 指令由框架注册、内容包不可覆盖（契约 L75）——框架注册 = `register_gm_commands`（gm L889-920）；「内容包不可注册同名指令覆盖」依赖 Router.register 重名冲突抛错（router_setup.py L189），但 **M12 前 gm_commands 未进 build_router 注册清单**（router_setup.py L27-29「GM 归 M12」、L78），需 M12 装配时纳入。【部分缺】

---

## 三、审计核对（契约 §4，L223-264）

### 3.1 审计事件类 E1-E6（契约 §4.1 L227-234）

| 事件类 | 契约触发 | 现状 | 判定 |
|---|---|---|---|
| E1 内容操作（G1 重载/G2 备份/G3 恢复） | 契约 L229 | G1 成功/失败均构造审计记录（gm L630-656，`_record_and_return` gm L599-623）；G2/G3 无指令 | 【已实现】（G1）；【缺】（G2/G3） |
| E2 数据导出（G4 存档导出） | 契约 L230 | 无 | 【缺】 |
| E3 广播（G7 广播） | 契约 L231 | 无 | 【缺】 |
| E4 封禁闭环（G10/G11） | 契约 L232 | G10 留痕含 target/时长/到期/原因（gm L684-689、E4 detail）；G11 无 | 【已实现】（G10）；【缺】（G11） |
| E5 权限变更（授予/撤销 GM、per-command 调整） | 契约 L233 | 无授权操作指令/界面 | 【缺】 |
| E6 系统事件（踢群/磁盘预警/封禁提示触发/备份失败） | 契约 L234 | 无 | 【缺】 |

### 3.2 审计记录字段（契约 §4.2 L236-254）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| audit_log 表（追加写，主键自增，id UUID） | 契约 L239-240 | schema.py 7 表无 audit_log；全仓 grep 无建表 SQL | 【缺】 |
| 字段 id/ts/qq/group_id/command/params/target_qq/result/detail/ref/audit_ts_hmac | 契约 L240-250 | `build_audit_record` 全字段构造（gm L381-406）与契约字段一致（含 id=uuid4、group_id 私聊=0、params 截断 200 字、result 三态 success/failed/rejected） | 【已实现】（记录构造侧） |
| audit_ts_hmac HMAC-SHA256（默认开） | 契约 L250 | `audit_hmac`（gm L365-378）+ `AUDIT_HMAC_FIELDS`（gm L227-229）；密钥经 ctx["audit_hmac_key"] 注入，None=不落校验值（gm L81-82 工程补白 8） | 【已实现】（函数侧）；【缺】（密钥注入，见 §四） |
| 成败皆写、result 区分 | 契约 L253 | `_record_and_return` 按 result 分支（gm L599-623）；TC-28 口径 | 【已实现】 |
| 无权限调用不写（防探测） | 契约 L253 | 静默分支不调 record_audit（gm L875-877）；装配层 `_dispatch_gm_result` 同口径（runner.py L343-350） | 【已实现】 |
| /日志 GM 版展示源 = 本表 | 契约 L254 | `cmd_gm_log` 消费 `recent_audit`（gm L715）语义一致 | 【已实现】（接口侧）；【缺】（表） |
| 审计写入与业务写入同事务（重载/恢复先写审计再执行） | 契约 L263 | 现状「先执行后写」（gm L644-656 先 `_backend().reload_content` 再 `_record_and_return`）；审查_M4实现_批次5 L166 已指出该时序缺口 | 【缺】（时序倒置） |

### 3.3 生命周期与安全约束（契约 §4.3 L256-264）

| 契约项 | 条款 | 现状 | 判定 |
|---|---|---|---|
| 不可删：无 GM 指令可删/清空审计表 | 契约 L260 | 无审计表 → 无删除指令（现状无「可删」指令，天然满足；但表建成后需确认无删除路径） | 【已实现】（现状无删除面） |
| 轮转：大小+保留份数，随磁盘水位预警 | 契约 L261 | 无审计轮转代码；backups 表存在（schema.py L116-124）但属备份恢复域非审计轮转 | 【缺】 |
| 权限：审计文件随 SQLite 目录 600/700 | 契约 L262 | 无审计文件；DB 文件权限设置无代码（TC-34 未覆盖） | 【缺】 |
| 幂等：审计与业务同事务 | 契约 L263 | 同 3.2 最后一行：现状先执行后写，无同事务保证 | 【缺】 |
| 展示：普通玩家永远看不到本表 | 契约 L264 | /日志 双分支 GM 版仅权限 ≥ manager 可达（gm L72-73、L694-730）；玩家版冒险日志归 log_commands（ADR-09，细化_M7_交互补全总纲 L183） | 【已实现】（分支口径） |

---

## 四、WIR 契约核对：ctx 三键声明 vs 注入现状

### 4.1 三键消费接口声明（gm_commands.py 文件头，gm L39-58）

| 键 | 契约消费接口 | 声明位置 |
|---|---|---|
| ctx["gm_backend"] | reload_content / ban_player / recent_audit / editor_link / apply_setting（gm L41-51） | gm L39-40、L588-596（未注入抛 RuntimeError「【待接线】」） |
| ctx["permission_store"] | user_of(qq_id) -> GmUser（gm L53-55） | gm L567-585 `_user_of`（store 优先，ctx role/granted 兜底） |
| ctx["audit_store"] | append(record)（gm L56-57） | gm L409-420 `record_audit`（追加 ctx["audit_log"] + store.append） |

### 4.2 注入现状（生产装配）

| 注入点 | 现状 | 判定 |
|---|---|---|
| qbot_rpg_bridge/assemble.py `build_app_deps` | `deps.permission_store = None`、`deps.audit_store = None`、`deps.audit_hmac_key = None`（assemble.py L169-171，注释「GM 后端归 M12，permission/audit 暂 None」）；**无 gm_backend 字段** | 【缺】 |
| qbot_rpg/assembly/runner.py `run_command` GM 上下文注入 | `ctx["permission_store"] = deps.permission_store`、`ctx["audit_store"] = deps.audit_store`、`ctx["audit_hmac_key"] = deps.audit_hmac_key`（runner.py L641-645）——仅当 `spec.is_gm` 时注入 | 【已声明未接线】（deps 侧为 None，实际注入 None） |
| runner.py RA-10 前门控 | `_permission_store_is_gm`（runner.py L245-270）消费 store.is_gm/user_of，store=None → False → GM 指令零出站（runner.py L648-650） | 【已声明未接线】（门控生效=全部 GM 指令被静默拦截） |
| runner.py `_dispatch_gm_result` | GmResult 分发：silent→零出站零审计；ok 无消息→静默成功不回显；其余→出站（runner.py L338-350） | 【已实现】（分发侧） |
| ctx["gm_backend"] | 全仓仅 gm_commands.py 消费（gm L590），**无任何装配方构造/注入 GmBackend**（GmBackend 需 watcher 实例，gm L442-443） | 【缺】 |
| make_context 工厂 | `register_gm_commands(make_context=...)`（gm L889-907）——装配层需注入玩家上下文工厂；现状无装配调用 register_gm_commands | 【缺】 |
| 测试替身 | tests/unit/test_gm_commands.py L171 `make_ctx` 注入 FakeGmBackend；L750-760 FakeStore 验证 permission_store 注入；test_assembly_runner.py L356-378 验证 audit_store 接线 | 【已实现】（测试侧，纯单测替身） |

### 4.3 接线缺口小结（M12 必接）

1. **gm_backend**：需 M12 构造 `GmBackend(watcher)`（watcher 来自 hot_reload 装配）并注入 ctx——现状无装配方。
2. **permission_store**：需 admin_users 表 + 缓存 + `user_of/is_gm` 实现类；assemble.py L169 的 None 需替换。
3. **audit_store**：需 audit_log 表 + `append` 追加写实现；assemble.py L170 的 None 需替换。
4. **audit_hmac_key**：配置注入（默认 None=不落校验值，gm L81-82）；5b §4.2「默认开」需配置到位。
5. **register_gm_commands 纳入 build_router**：router_setup.py L27-29 明确「GM 归 M12」，当前 build_router 不注册 gm 指令（GM 指令名已在 parsers 白名单 L153-160，但无 CommandSpec → 路由到不了处理器）。
6. **/日志 双分支冲突**：ADR-09（细化_M7_交互补全总纲 L183）「日志 spec 由 log_commands 统一注册」，gm_commands 也注册「日志」会重名冲突——M12 需按 ADR-09 裁定合并方式（审查_M7总纲_批2 L113 指出 BCH-05 撞车）。

---

## 五、9 条待接线指令逐条：契约要求 vs 现状 + 实现要点清单

### G2 `/备份`（契约 L90、L114-116）
- 契约：GM 权限；无参；VACUUM INTO/checkpoint 后复制产 zip；保留 30 天（L1166）；返回 `备份完成：…zip（大小）`。
- 现状：`GmBackend.backup_content` 抛 NotImplementedError（gm L485-493）；无指令注册。
- 实现要点：① 新指令常量 + GM_COMMANDS/GM_COMMAND_INDEX/GM_COMMAND_LEVEL（机主/GM 均可，契约 L40 默认授予集含备份）扩展；② 后端实现 backup_content：zip 存档+内容包+配置（契约 L114-115）；③ 保留策略（30 天/份数）；④ 处理器 + TPL-12 错误模板；⑤ 审计 E1（含备份文件名 ref）；⑥ GM_COMMAND_LEVEL 扩表后 GM_DEFAULT_GRANT 自动含（gm L196-198 推导）。

### G3 `/恢复`（契约 L91、L118-120）
- 契约：GM 权限；无参；校验→自动备份当前档→原子替换→失败回滚；恢复中标记。
- 现状：`GmBackend.restore_content` 抛 NotImplementedError（gm L495-503）。
- 实现要点：① 指令注册（同上）；② 后端 restore_content：取最近备份（backups 表，schema.py L116-124 可复用）、备份当前档 backup_pre_restore.zip、原子替换、回滚；③ 恢复中标记 + 玩家恢复游玩（契约 L119）；④ 审计 E1（恢复回滚标记）；⑤ 与 /重载 同事务口径（审计先写再执行，契约 L263）。

### G4 `/存档导出`（契约 L92、L122-125）
- 契约：机主（可下授）；无参；CSV 默认脱敏；`= + - @` 前缀转义/拒绝（L1156）；产物权限 600；返回 `已导出 N 名玩家：exports/…csv（脱敏开启）`。
- 现状：无代码物。
- 实现要点：① 指令注册 + 权限 ROLE_ADMIN（下授走 granted_commands）；② CSV 导出引擎（等级/货币/活跃/最近在线，L1129 字段集）；③ 脱敏开关 + 公式注入防护（L1156）；④ 产物文件权限 600（TC-14/TC-34）；⑤ 审计 E2（产物路径/脱敏开关）。

### G5 `/调试`（契约 L93、L127-130）
- 契约：机主（可下授）；无参；切换调试模式（日志详略/性能计时）；不影响游玩数据。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_ADMIN；② 调试开关（日志级别/性能计时）后端；③ 返回 `调试模式：开（日志级别=DEBUG…）`；④ 审计（GM 指令成败皆写）。

### G6 `/测试`（契约 L94、L132-135）
- 契约：机主（可下授）；无参；**只读冒烟测试集**（三表 schema/引用完整性 + 指令路由连通性）；零写操作（TC-20）。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_ADMIN；② 只读冒烟引擎（schema 校验/路由连通检查）；③ 严格零写（TC-20 探针断言）；④ 返回摘要/错误模板；⑤ 审计。

### G7 `/广播 <消息>`（契约 L95、L137-142）
- 契约：机主（可下授）；消息 ≤200 字；`定时=HH:MM`（apscheduler，L1128）；`群=群号,群号` 限定；跨群去重；频率受单群 ≤20 条约束（L1311）。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_ADMIN；② 消息 ≤200 字校验（TC-16）；③ 定时键值 → apscheduler（注意：项目现「零 apscheduler」铁律，runner.py L708-731 用懒循环替代——定时广播需按同口径实现或引入调度）；④ 群限定列表解析（`,` 语法）；⑤ 推送通道复用公告通道；⑥ 审计 E3（群数/私聊数/定时标记）；⑦ 频率约束（GM 不豁免）。

### G9 `/玩家查询 <QQ号>`（契约 L97、L149-153）
- 契约：机主（可下授）；QQ 纯数字校验；脱敏摘要（等级/货币/最近在线/封禁状态）；无背包/收益明细；未注册 → 错误模板（非静默）。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_ADMIN；② QQ 纯数字校验（复用 cmd_gm_ban 校验模式，gm L668）；③ 脱敏查询引擎（players 表 L32-55 字段足够）；④ 未注册 → TPL-12（目标不存在≠静默，契约 L153）；⑤ 审计（target_qq 字段）。

### G11 `/解封 <QQ号>`（契约 L99、L161-162）
- 契约：GM；QQ 号；返回 `已解封`；不在名单 → 错误模板（含 /封禁列表 提示）。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_MANAGER（默认授予集）；② 解封引擎 + 封禁名单存储（与 G10 ban_player 同一存储）；③ 不在名单 → TPL-12；④ 审计 E4（解封闭环）。

### G12 `/封禁列表`（契约 L100、L164-165）
- 契约：GM；无参（分页语法 `/封禁列表 <页>`）；5 条/页；原因/时长/到期；超长截断两条（L1346）。
- 现状：无代码物。
- 实现要点：① 指令注册 + ROLE_MANAGER；② 封禁名单查询引擎；③ 分页渲染（复用 render_list_page_text/render_log_page 模式，gm L791-820）；④ 页码裁决② 夹取口径（与 /日志 一致）；⑤ 审计。

**共同前置（9 条全部依赖）**：指令常量/清单/序号/权限级扩展（gm_constants.py + GM_COMMAND_LEVEL）；gm_backend 注入（§四）；封禁域需要「封禁名单」存储（G10 后端 + G11/G12 共用，现无）；广播域需要推送通道。

---

## 六、风险与坑位

1. **静默语义双源风险**：/帮助 GM 组可见性读 `ctx["is_gm"]`（basic_commands.py L222 GM 组），执行判定读 permission_store——审查_M4实现_批次5 L160-161 已指出双源不一致可能（帮助可见但执行被静默拦，或反之，构成 RUL-25 间接探测面）。M12 装配时 `ctx["is_gm"]` 必须与 permission_store 同源填充。
2. **GM 禁绑四攻击面**（契约 §3.2 L205-209）：① 绑「快捷名=重载」→ 绑定层拒绝（已实现）；② 绑「快捷名=/重载」完整串 → 执行层权限二次检查静默（已实现）；③ 内容包注册别名/同名指令指向 GM 语义 → **框架指令优先权 + 别名校验器拒绝【缺】**——现无 GM 别名校验器代码，需补；④ 直写存档快捷表脏数据 → 执行层二次检查兜底（已实现，TC-24）。M12 需补齐③并复测全四面。
3. **权限唯一事实来源**：admin_users 表 = 唯一事实来源（契约 L58、L61），玩家存档天然不含权限字段（schema.py L32-55 合规）——M12 建表后**严禁**向 players 加权限列；`_user_of` 兜底路径（gm L584-585 ctx role/granted）只应服务测试，生产必须经 permission_store（否则直连 ctx 注入可绕过 admin_users）。
4. **审计无权限不写**：静默分支零审计已实现（gm L875-877）；但 runner.py RA-10 前门控（runner.py L648-650）在 handler 之前拦截，与 gm_commands 内层静默是**两道独立闸**——M12 接线后需保证不出现「门控放行但内层静默」或反向的空档（审查_M7总纲_批2 L134：A-03 流水线需显式定义 permission 校验步与 GmResult 分发位置）。
5. **审计时序倒置**：契约 L263「审计先写再执行、与业务同事务」vs 现状「先执行后写」（gm L644-656）——audit_store 落库失败或进程崩溃可产生「已执行未留痕」操作（审查_M4实现_批次5 L166）。M12 建 audit_log 后需改同事务口径。
6. **/日志 注册撞车（BCH-05）**：ADR-09 已定「日志 spec 由 log_commands 统一注册」，gm_commands 同注册必冲突（细化_M7_交互补全总纲 L183；审查_M7总纲_批2 L113）——M12 需按 ADR-09 合并或裁定，且 parsers 白名单已含 5 条 GM 指令（parsers.py L153-160），路由可达性取决于注册归属。
7. **GM 后端依赖热重载 watcher**：GmBackend.reload_content 依赖 HotReloadWatcher 实例（gm L442-443）；M12 装配需把 hot_reload 的 watcher（内容包启动装载管线，hot_reload.py L187-194）注入 GmBackend，否则 /重载 恒「内容包未启用」。
8. **GM 不豁免频率**：契约 L176、TC-32/33——频率控制在 runner/processing 层（per-player 队列 + message_id 幂等，runner.py L659-665），GM 指令走同一管线即天然受限，M12 接线时勿为 GM 开旁路。
9. **/设置 群级生效**：G14 契约「切换后对该群即时生效」（契约 L172）——apply_setting 后端需按群维度读写配置（settings.json 群级段），现状壳层只透传键值（gm L750-775），群维度语义未定。
10. **封禁闭环缺「人话提示」分支**：契约 §3.3 L216「被封玩家发游玩指令 → 人话提示（你已被禁止使用本游戏…）」全仓无实现（grep 封禁/ban 无游玩指令入口钩子）——G10 后端落库后必须补被封玩家触发游玩指令的拦截提示（TC-07），且与 GM 静默严格区分（TC-08：被封 GM 发 GM 指令照常）。

---

## 附：关键文件与行号索引

| 文件 | 关键行号 |
|---|---|
| docs/细化/细化_5b_GM指令契约.md | 总表 L85-104；逐条 L106-173；跨指令约束 L175-178；权限模型 L33-76；禁绑 L194-209；审计 L223-264；TC L286-343 |
| qbot_rpg/commands/gm_commands.py | 消费接口 L39-58；权限三级 L173-205；check_gm_permission L286-308；结果模型 L315-351；审计构造 L358-420；GmBackend L427-503；处理器 L630-775；渲染 L791-820；禁绑 L827-853；主入口 L860-882；注册 L889-920 |
| qbot_rpg/data/gm_constants.py | 5 条清单 L27-37；G 序号 L40-46；强制前缀 L48-50 |
| qbot_rpg/assembly/runner.py | RA-10 门控 L233-270；GmResult 分发 L338-350；ctx GM 注入 L641-645；权限拦截 L648-650 |
| qbot_rpg_bridge/assemble.py | 鸭式字段置 None L167-172 |
| qbot_rpg/storage/schema.py | 7 表 L29-135（无 admin_users/audit_log） |
| qbot_rpg/commands/parsers.py | 白名单 L153-160；DEFAULT_GM_COMMANDS L174；DEFAULT_PREFIX_REQUIRED L159 |
| qbot_rpg/commands/router.py | PERM_* L76-78；is_gm L146-168；check_shortcut_binding L804-830 |
| qbot_rpg/assembly/router_setup.py | GM 归 M12 L27-29；gm_commands_set 快照 L237 |
