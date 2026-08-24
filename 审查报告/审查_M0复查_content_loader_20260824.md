# 审查_M0复查_content_loader（批2a-路1：内容包加载管线 loader）

> 审查对象：`qbot_rpg/content/loader.py`（272 行）
> 对照基准：`细化_3e_loader校验接线.md`（§1.1 五段管线 / §1.2 manifest 硬约束 / §1.3 加载顺序 / §1.4 校验阻断 / §1.5 挂载原子替换 / §1.6 to_thread / §1.7 错误模型 / §6 验收 TC-01~30）
> 辅助交叉核对：`qbot_rpg/content/{models,validator,registry,field_meta,hot_reload}.py`、`tests/unit/test_content.py`、`细化_3e2_热重载契约.md`、`细化_3b_玩家属性三层.md`
> 方式：纯静态审查，无任何运行/验证；涉及运行行为的结论一律标注「静态推导」。
> 日期：2026-08-24

## 0. 结论摘要

- **P0：0 条**（无破坏主路径、无数据损坏、无安全 RCE 级问题）
- **P1：3 条**（真实缺陷/契约违背，应在合入前修复）
- **P2：8 条**（性能/健壮性/文档一致性/零消费补丁）

三条 P1 全部是**潜伏型**：现有 `tests/unit/test_content.py` 未覆盖，当前不炸但违反 loader 自述契约：
1. manifest 错误在全量报告中**重复上报**（D-01「一次给全量」语义被破坏，计数断言会翻倍）；
2. manifest 顶层为 JSON 数组/标量时 `Manifest.from_dict` 抛 **AttributeError**，绕过 `PackLoadError` 错误模型；
3. map 形态模块（stats 等）注册的 `Def.id` 为**空串**，违反 §1.5「ID→定义对象」与 registry 名称冗余契约。

---

## 1. P1 问题（3 条）

### P1-1　manifest 错误重复上报（错误报告翻倍）
- 位置：`loader.py` L198-199（`manifest_check = check_pack({"manifest": ...})` + `errors.extend(...)`）与 L232-237（`modules["manifest"]=manifest_raw` 后再跑全量 `check_pack(modules, ...)` 并 `errors + report.errors` 合并）。
- 依据（静态推导）：`validator._ordered_defined_modules()` 会把 `manifest` 作为受检模块再次校验（validator.py L192-204），且 `field_meta.py` L205 已注册 manifest 的 ModuleMeta。故同一批 manifest 红拦会**先**经 L198-199 进 `errors`，**再**经 L233 的 `report.errors` 进来一次，`combined.errors` 中每条 manifest 错误出现两遍。例：TC-06（manifest 缺 `modules`）应报 1 条，实际报 2 条；同时缺 name+modules 报 4 条而非 2 条。
- 影响：违反 D-01「一次给全量、作者一次改完」的干净语义；任何按条数断言（TC-10「3 条 errors」式）会被翻倍干扰；commands 层人话消息会重复贴同一条 manifest 错误。
- 修复建议：删除 L198-199 的冗余 `manifest_check` 提前校验（全量校验已含 manifest）；若需在 B 阶段前早停，则只用于早停判断、**不要** `errors.extend`（或改判后直接 `_raise_if_blocked`）。
- 注意：现有 `test_required_missing_red`（test_content.py L139-146）用 `any(...)` 断言，**无法**暴露此重复，需补精确计数断言。

### P1-2　非法顶层类型的 manifest 抛 AttributeError 而非 PackLoadError
- 位置：`loader.py` L200 `manifest = Manifest.from_dict(manifest_raw)`。
- 依据（静态推导）：`Manifest.from_dict`（models.py L298-311）首行 `data.get("modules", [])`。若 `manifest.json` 是合法 JSON 但顶层为数组/字符串/数字（如 `[1,2,3]`），`manifest_raw` 非 Mapping → `data.get` 抛 **AttributeError**。此时 L198 的 `manifest_check` 其实已正确报出 R-5 `module_structure`，但 loader 在能抛 `PackLoadError` 之前就被裸异常打断。
- 影响：直接 `load_pack()`/`build_pack()`（commands 层初次挂载、编辑器保存前校验路径）会收到 AttributeError 而非领域异常，违反 §1.7/D-06 错误模型与 §1.2「manifest 自身结构 → 红拦」。热重载路径因 `hot_reload._reload_sync` 的宽 `except Exception`（hot_reload.py L241）被兜成 `unexpected_error` 才未外泄，但掩盖了 loader 侧缺陷。
- 修复建议：在 `Manifest.from_dict` 之前加 `if not isinstance(manifest_raw, Mapping):` → 追加 R-5 `module_structure` 并 `_raise_if_blocked`（或在 models.from_dict 内对非 Mapping 显式返回空/抛领域错误）。

### P1-3　map 形态模块（stats）注册的 `Def.id` 为空串
- 位置：`loader.py` L111-114（map 分支 `for eid, value in data.items(): _register_def(..., str(eid), value)`）与 `_register_def` L134-138（`d = cls.from_entry(entry)`）。
- 依据（静态推导）：stats.json 为 `{"hp": {...}, ...}`，值对象**不含 `id` 键**（键即 ID）。`_register_def` 走 Mapping 分支 `StatDef.from_entry(entry)`（models.py L162-166 `eid = str(entry.get("id",""))`）→ 注册的 `Def.id == ""`；仅 `tables["stat"]["hp"]` 的**字典键**保留 ID，`names["hp"]` 保留 name。即 `registry.resolve("hp","stat").id == ""`、`.get("id") == ""`。
- 影响：违反 §1.5「ID → 定义对象 映射 + 名称冗余（L177）」（registry.py `resolve_name`/快照按 ID 冗余）。当前消费方多用 `resolve().raw/.get()`（effects.py L968 等），故「静态推导」暂不炸，但任何读取 `Def.id` 的消费（对局快照按 ID 引用、调试、序列化）都会拿到空 ID；与 validator 侧「map 键 = ID」（validator.py L214-218 `eid = idx`）的键空间口径不一致。legal 包 9 个 stat 全部中招，现有测试只断言 `resolve(...,"formula") is not None`，未覆盖 stat 的 `.id`。
- 修复建议：map 分支注册前用键覆盖 ID——`d = cls.from_entry(entry); object.__setattr__`（frozen）不可行时，改在 `_register_def` 对 map 模块以 `eid` 显式重建 `cls(id=eid, name=..., raw=deepcopy(...))`，或给 `BaseDef.from_entry` 增加 `override_id` 参数。formula 的**字符串值**走非 Mapping 分支（L137 传 `id=eid`）是正确的，仅对象值（stats、formula 的 `{formula:...}` 形态）受影响。

---

## 2. P2 问题（8 条）

### P2-1　TRG-3「不做 IO」与自述「跳过 IO」均未实现（mtime 快筛缺失）
- 位置：`loader.py` L59-75（`file_signature` 每次全文件读+sha256）、L172-174（docstring「不改动则跳过 IO/解析」）、L214-216（sig 比对）。
- 依据：`file_signature` 无论是否变更都 `open+read` 整个文件算哈希；「mtime 未变」只省了 JSON 解析，**未省 IO**。与自身注释（跳过 IO）及细化_3e2 TRG-3「不做 IO、不重校验」（3e2 L78）矛盾；TRG-2 的「mtime 快筛」也未实现（无 mtime_ns+size 命中即跳过哈希的快路径）。正确性无碍（仍复用解析结果、全量校验仍跑，符合 3e §4.3），属性能与文档一致性缺口。
- 修复建议：缓存命中时先比 mtime_ns+size，一致则跳过哈希直取缓存（真·快筛）；或至少修正注释为「跳过重新解析」。

### P2-2　manifest 不入增量缓存、变更不进 `changed`、签名双重读取
- 位置：`loader.py` L184-185（`manifest_sig` 只用于 None 判断，其余未用）、L190-191（manifest 每次重读）、L179/L229/L246（`changed` 仅记模块）。
- 影响：仅修改 manifest.json（如 version 提升、modules 增删）时 `changed == ()`，3e2 TC-02 式「已重载：N 个模块变更」日志为空；且 manifest 被读两次（签名哈希 + json.loads）。正确性无碍（manifest 变更本应重解析），属缺漏。
- 修复建议：将 manifest 纳入 `changed` 上报；复用 `manifest_sig` 于缓存（避免双重 IO）。

### P2-3　`file_signature` 的 `stat()` 只捕获 FileNotFoundError，其余 OSError 裸抛
- 位置：`loader.py` L64-67。
- 依据（静态推导）：文件存在但不可读/是目录等场景 `stat` 抛 PermissionError/IsADirectoryError 等，未被捕获 → 裸异常绕过 `PackLoadError`。与 L192/L220 对 read 的 OSError 收敛不一致；§4.4 要求「任何红拦或 IO 异常 → 中断」，此处会成为非领域异常（热重载由宽 except 兜底，直接 load_pack 会外泄）。
- 修复建议：捕获 `OSError`（不只 FileNotFoundError）统一返回 None。

### P2-4　全文件无 logging 接线（调试日志 / 异常日志缺漏）
- 位置：`loader.py` 全文（无 `import logging`）。
- 依据：§1.2 要求未声明文件「静默跳过 + **调试日志**」（TC-09「调试日志记录跳过（L135）」）；§1.7/【规则】L114「任何加载/校验异常必须 log」。当前未声明跳过、Y-6、解析异常均只进报告不落日志。
- 修复建议：接入 logging：未声明文件跳过→debug；声明缺失 Y-6→info；JSON 解析失败→warning（含 path/error）。若日志归调用方统一，需在文档注明并补齐调用侧接线，否则 TC-09 的「调试日志」断言无落点。

### P2-5　conditional 模块在 D 阶段被静默丢弃（注册表零消费）
- 位置：`loader.py` L99-114（`_build_registry` 仅处理 list 与 `("stats","formula")` map 两种形态）、L157（`_KIND_FOR_MODULE["conditional"]`）、models.py L280（`DEF_CLASSES["conditional"]`）。
- 依据（静态推导）：conditional.json 为 `{"conditional":[...]}`（object 形态，field_meta.py L223），`_build_registry` 的 `elif isinstance(data, Mapping) and module_name in ("stats","formula")` 不命中 → conditional **不进 registry**。而 `_KIND_FOR_MODULE`/`DEF_CLASSES` 均声明了该 kind → 两处成**死条目**；`registry.resolve(id,"conditional")` 恒 None。当前消费方 `core/player_attributes.py` 从模块原始数据直读（不依赖 registry），故不崩，但 loader 内映射表与注册路径自相矛盾。
- 修复建议：二选一——(a) 若 conditional 不注册，删除 `_KIND_FOR_MODULE["conditional"]` 与 `DEF_CLASSES["conditional"]` 死条目，并在 `_build_registry` 注释注明「object 形态仅校验不注册」；(b) 若需注册，为 object 形态补注册分支（把 `data["conditional"]` 列表按条目注册）。

### P2-6　`names` 扁平映射跨命名空间同 ID 相互覆盖
- 位置：`loader.py` L139 `names[eid] = d.name`（裸 ID 作键）。
- 依据（静态推导）：validator 仅按命名空间去重（validator.py L225-239，跨命名空间允许同 ID），如 effect `heal` 与 item `heal` 可并存；loader 的 `names` 是全局扁平 dict → 后注册者覆盖先注册者，`registry.resolve_name("heal")` 返回错误显示名。违反 §1.5/§4.5「名称冗余（L177）」与 OLD-2 语义。
- 修复建议：`names` 键改为 `(kind, eid)` 或由上层按 kind 冗余；或与 §1.3「ID 全局唯一」（术语表）对齐，将跨命名空间同 ID 也提升为 R-5。

### P2-7　manifest 声明的模块名未净化（路径拼接风险）
- 位置：`loader.py` L206 `mpath = pack_dir / f"{module_name}.json"`。
- 依据（静态推导）：`module_name` 直接来自 manifest，未校验 `../`、绝对路径、空串等。恶意/误写 `"../x"` 会读 pack 目录外文件（哈希+尝试解析；解析失败即 R-5 阻断，但已对外部文件产生读+哈希副作用，错误串含 `str(e)` 可能泄漏路径）。与 §3.3 zip 路径白名单的收口思路不一致。
- 修复建议：对模块名做白名单（`^[a-z][a-z0-9_]*$`）或拒绝含路径分隔符/`.` 的条目（此非法条目本应由 validator 报 R-5，可双保险）。

### P2-8　注释引用 D-03 跨文档歧义（一致性/文档精度）
- 位置：`loader.py` L96「（独立对象，D-02/D-03）」。
- 依据：细化_3e 的 D-03 是「黄提示聚合一条消息」（3e L47）；细化_3e2 的 D-03 才是「指针级原子替换」（registry.py L7 同引）。loader 此处未标注来源，读者会误以为是 3e 的 D-03，语义对不上（黄提示聚合与 registry 构建无关）。
- 修复建议：改为「D-02 / 细化_3e2 D-03（指针级原子替换）」或去掉 D-03。其余细化行号引用（§1.1~1.7、TRG-2/TRG-3、细化_3b §3.2）经核对**均真实存在且内容相符**，无虚构行号。

---

## 3. 无问题维度确认（静态核对，未发现缺陷）

- **§1.3 注册顺序**：`FIXED_REGISTER_ORDER`（L40）与 `_ordered_declared`（L78-87）= effects→statuses→marks→skill_chains→action→其余按声明顺序，与 §1.3/L136 完全一致；validator 报告排序（validator.py `_PRIORITY`）同口径。
- **§1.2 Y-6 模块缺失不拒绝**：L208-213 缺失文件→黄提示 Y-6 + `cache.pop` 防残留，与 TC-17 一致；`missing_mod` fixture 测试通过路径成立。
- **§1.2 未声明文件不加载 / 空 modules**：仅遍历 `manifest.modules`（L205），磁盘多余文件不读不注册（TC-09）；空 modules→空包（静态推导），符合 L134 兼容语义。
- **D-02 半挂载禁止**：D 阶段仅在 `combined.ok` 后执行（L238-242），红拦不构建 registry；TC-11 语义成立。
- **D-05 / §1.6 to_thread**：`load_pack` 整流程 `asyncio.to_thread(build_pack, ...)`（L268）；`hot_reload` 的检测/重载亦走 to_thread（hot_reload.py L115/126/143/148/174/234），无校验内 await。
- **§4.3/TRG-3 增量缓存接线**：`parse_cache`（L167-168）由 `hot_reload._parse_cache` 传入（hot_reload.py L74/L235），`changed` 上报被消费（3e2 TC-02/TC-24、test_content.py L345-413）；缓存清理（缺失/坏 JSON → pop）正确。
- **§1.7 错误模型**：`PackLoadError` 携带 `report.errors: Tuple[PackError,...]`（L43-56），module/field/kind/detail 四元结构一致，无 loader 拼用户体验文案（D-06）；仅 P1-2 场景会绕过它（见上）。
- **③ 幻觉核查（关键）**：loader 注释引用的「细化_3e §1.1~1.7、§5.2」「细化_3e2 TRG-2/TRG-3」「细化_3b §3.2」经与基准文档/`细化_3e2_热重载契约.md`/`细化_3b_玩家属性三层.md` 逐条核对**均为真实存在、内容相符**；无虚构行号、无冒充定稿、无未标注的工程补白（除 P2-8 D-03 歧义、P2-1「跳过 IO」注释与实现不符两处文档精度问题）。
- **接口偏离说明**：§1.5 命名 `register_pack()` 在 loader 中改为 `build_pack()→Pack(registry)` + 上层 `HotReloadWatcher._commit_success` 提交（docstring L6 已注明「原子引用替换由上层/HotReloadWatcher 负责」），为已文档化接线选择，非缺漏。

---

## 4. 修复优先级建议

1. **P1-1**：删除冗余 manifest 预校验的 `errors.extend`（最小改动，杜绝重复报告）。
2. **P1-2**：`Manifest.from_dict` 前对非 Mapping 加 R-5 阻断（补 `test_content`：manifest 顶层为数组用例）。
3. **P1-3**：map 形态注册时以键覆盖 `Def.id`（补 stat `.id` 断言）。
4. P2 按 1→8 顺序：先修影响验收语义的（P2-1/2/4 涉及 TC-09/3e2 TC-02 断言落点），再做健壮性（P2-3/7）与清理（P2-5/6/8）。
