# 审查_M0复查_content_registry_models（批2b-路1：注册表 registry + 数据结构 models）

> 审查对象：`qbot_rpg/content/registry.py`（203 行）、`qbot_rpg/content/models.py`（实际 361 行，任务描述 360 行，差 1 行为末行空行，无实质差异）
> 对照基准：`细化_3e_loader校验接线.md`（重点：ID 注册 §1.5 / O(1) 引用查表 / 快照-回退 / 原子引用替换 / 自检 A；附 §5.1 接口、§4.6 并发、§4.4 回退）+ `细化_3e2_热重载契约.md`（ATO-1~7 / SNAP-1~6 / OLD-2 / §5.3 自检 A）
> 辅助交叉核对：`qbot_rpg/content/{loader,validator,field_meta,hot_reload}.py`、`qbot_rpg/data/types.py`、`tests/unit/test_content.py`、`tests/fixtures/packs/legal/stats.json`、前批报告 `审查_M0_content_20260818.md` 与 `审查_M0复查_content_loader_20260824.md`
> 方式：**纯静态代码审查，无任何运行/验证**；所有运行行为结论一律标注「静态推导」。
> 日期：2026-08-24

---

## 0. 结论摘要

- **P0：0 条**（无主路径破坏、无数据损坏、无安全级问题）
- **P1：3 条**（契约未兑现 / 错误模型被绕过 —— 均为潜伏型，现有测试未覆盖，当前不炸但违反自述契约）
- **P2：8 条**（零消费 / 边界 / 文档精度 / 健壮性）

三条 P1 中 **2 条与前批 loader 报告同源**（P1-2↔loader P1-2、P1-3↔loader P1-3），本报告从 **models/registry 侧复述根因与修复落点**，避免批间丢失；P1-1（integrity_check 冒充自检 A）为本批新发现。

---

## 1. P1 问题（3 条）

### P1-1　`integrity_check` 仅实现 3e2 自检 A 的子集，注释/hot_reload 冒充「自检 A」【静态推导】
- 位置：`registry.py` L183-196（`integrity_check`）；docstring L183「一致性自检（细化_3e2 自检 A）」；接线方 `hot_reload.py` L248-253 同样注释「通过后自检 A（接口完整性，细化_3e2 自检 A）」。
- 依据：3e2 §5.3 自检 A（3e2 L215）定义四项断言：**ID 唯一性（效果家族跨表 / 技能行动同库）、modules 声明 ⊇ 已加载模块、schema_version 一致**；断言失败视为重载失败走 F3。实际实现只做两项：
  1. kind 内重复 ID 检查（L186-191）：`tables` 为 `dict`（键即 id），**字典不可能含重复键**，该分支对 dict 支撑的表**恒不可达（死代码）**；
  2. 每个 id 必须有名（L192-195）：这是 OLD-2/SNAP-4 的「名称冗余」检查，**不属于自检 A** 清单。
  三项核心断言（跨表唯一 / modules⊇loaded / schema_version 一致）**全部缺失**。
- 影响：hot_reload 以 `integrity_check()` 作为重载接受前的最后一道门（不通过即按失败走 F3），但该门只查「名称冗余」、不查自检 A 定义的任何一项 → 跨表 ID 冲突、模块与声明不一致、schema_version 漂移均可静默放行。目前 validator（`_Checker._register_id`，validator.py L225-239，按 field_meta NAMESPACES 前置拦跨表唯一）已兜住跨表重复，故为「契约缺口 + 注释冒充」，非当前必炸；但 3e2 §5.3 自检 A 为明确定稿要求，本批基准点「自检 A」未兑现。
- 修复建议：`integrity_check` 增加三项断言 —— ① 依据 NAMESPACES（field_meta L25-35）对同命名空间多 kind 表做跨表 ID 唯一性检查；② `modules` 声明 ⊇ `_tables` 已含 kind 对应的模块（需 Registry 持有模块声明集合，或改由 hot_reload 校验）；③ `_schema_version` 与 manifest 声明一致。删除恒不可达的 kind 内重复分支（或改为对任意 Mapping 输入的防御）。补单测：构造跨表同 ID 的 registry 直调 `integrity_check` 应非 None。

### P1-2　`Manifest.from_dict` 对非 Mapping 顶层抛 `AttributeError`，绕过 `PackLoadError` 错误模型
- 位置：`models.py` L298-311（`from_dict` 首行 L300 `raw_modules = data.get("modules", [])`）。
- 依据（静态推导）：`manifest.json` 为合法 JSON 但顶层是数组/字符串/数字（如 `[1,2,3]`）时，`manifest_raw` 非 Mapping → `data.get` 抛 `AttributeError`，在 loader 能抛 `PackLoadError` 之前打断。loader 侧调用点 `loader.py` L200 直接 `Manifest.from_dict(manifest_raw)`，无 Mapping 守卫。违反 §1.2「manifest 自身结构 → 红拦」与 §1.7/D-06 错误模型。热重载路径靠 `hot_reload._reload_sync` 的宽 `except Exception`（hot_reload.py L241）兜成 `unexpected_error`，掩盖了本缺陷。
- 与前批衔接：即 loader 报告 P1-2（loader.py L200），**根因在 models.py `from_dict`**，本批按落点定位。
- 修复建议：`from_dict` 首行 `if not isinstance(data, Mapping): return cls(name="", version="", schema_version=0, author="", modules=(), raw={})`（由 validator 报 R-5 `module_structure`），或由 loader 在调用前对非 Mapping 追加 R-5 并 `_raise_if_blocked`。补测试：manifest 顶层为数组。

### P1-3　`BaseDef.from_entry` 不感知 map 形态「键 = ID」，`StatDef.id` 为空串
- 位置：`models.py` L162-166（`from_entry` 的 `eid = str(entry.get("id", ""))`）；联动 `registry.py` L37-38（`tables` 键 = ID / `names` 按 ID 冗余）。
- 依据（静态推导）：stats.json 为 `{"hp": {"name":"生命",...}, ...}`（fixture `tests/fixtures/packs/legal/stats.json` 已核，值对象**无 `id` 键**）。loader `_build_registry`（loader.py L111-114）对 map 形态以键作 eid 调 `_register_def`，`_register_def`（loader.py L134-138）走 `cls.from_entry(entry)` → `StatDef(id="", name="生命", ...)`。即 `registry.resolve("hp","stat").id == ""`，仅 `tables["stat"]["hp"]` 的**字典键**保留 ID。formula 的**对象值**（`{"formula": "..."}` 形态，同样无 id 键）经 `DEF_CLASSES.get("formula", BaseDef)` → `BaseDef.from_entry` 亦得空 id；仅 formula **字符串值**走非 Mapping 分支（loader.py L137 `BaseDef(id=eid, ...)`）正确。
- 影响：违反 §1.5「ID → 定义对象 映射 + 名称冗余（L177）」与 OLD-2「按 ID 结算」。当前消费方多用 `resolve().raw/.get()`（effects.py L968 等），故「静态推导」暂不炸；任何读 `Def.id` 的消费（对局快照按 ID 引用、调试、序列化）拿到空串；与 validator 侧「map 键 = ID」（validator.py L214-218）键空间口径不一致。legal 包 9 个 stat 全部中招；现有测试仅断言 `resolve(...,"formula") is not None`（test_content.py L57），未覆盖 stat 的 `.id`。
- 与前批衔接：即 loader 报告 P1-3；本批在 **models 侧给根因落点**。
- 修复建议：`BaseDef.from_entry` 增加 `id_override`/`key` 参数（`cls(id=key or eid, ...)`），loader 对 map 形态显式传键；或 loader 对 map 分支绕过 `from_entry` 以 `cls(id=eid, name=..., raw=deepcopy(...))` 重建。补断言 `resolve("hp","stat").id == "hp"`。

---

## 2. P2 问题（8 条）

### P2-1　`names` 扁平映射，跨命名空间同 ID 相互覆盖 → `resolve_name` 返回错误显示名
- 位置：`registry.py` L38（`names: Mapping[str, str]  # id -> 显示名`）、L86-88（`resolve_name(id)` 无 kind 维度）。
- 依据（静态推导）：validator 仅按命名空间去重（validator.py L225-239，跨命名空间允许同 ID，如 effect `heal` 与 item `heal` 可并存且合法）；loader 以裸 ID 作 `names` 键（loader.py L139）→ 后注册者覆盖先注册者，`resolve_name("heal")` 返回错误显示名。违反 §1.5/§4.5「名称冗余（L177）」与 OLD-2 语义。registry 侧的数据结构缺 kind 维度，属本批落点（loader P2-6 同源）。
- 修复建议：`names` 键改为 `(kind, eid)` 且 `resolve_name(id, kind)`；或把跨命名空间同 ID 提升为 R-5（与 3e 术语表「ID 全局唯一」对齐，需仲裁口径）。

### P2-2　`RegistrySnapshot` 只读/不可变未落地（frozen 不防内部 dict 可变，SNAP-5 靠约定）
- 位置：`registry.py` L27-41（`@dataclass(frozen=True)` 但 `tables/names/modules_raw` 为深拷贝出的**可变 dict**）。
- 依据：frozen 只禁属性再赋值，不禁 `snap.tables["effects"]["heal"] = ...`。`restore()`/`from_snapshot()`（L136-138/L153-155）从快照**重新深拷贝**，若快照内容被外部改动，回退将恢复污染状态。3e2 SNAP-5「进行中对局持有的旧 registry 只读」（3e2 L154）与 D-05 只读持有语义在 registry 层无强制，仅注释约定。`_backup_snapshot()`（hot_reload.py L316-318）把 snapshot 交给会话层后，会话层若误写即污染回退源。
- 修复建议：快照表结构用 `MappingProxyType` 包装（或返回只读视图）；会话层持有侧文档标注只读约定，并在 `restore` 入口对来源快照做深拷贝前先防御校验。

### P2-3　`restore()`/`from_snapshot()` 对快照内容二次深拷贝（双深拷贝开销）
- 位置：`registry.py` L136-138（restore）、L153-155（from_snapshot）。
- 依据（静态推导）：`snapshot()` 已 `copy.deepcopy` 一次（L123-125），`restore`/`from_snapshot` 再深拷贝一次 → 失败回退路径两次全量深拷贝大 registry。与 20260818 P2-15（hot_reload 侧 pre+from_snapshot 双深拷贝）同源，本批在 registry 侧复述。
- 修复建议：快照内容改为共享不可变表（构建后冻结），restore 仅做引用替换省一次拷贝；或明确该开销为可接受（P2 性能项）。

### P2-4　零消费 API：`contains()` / `restore()` / `resolve_name()` 全库无调用方
- 位置：`registry.py` L109-114（contains）、L130-145（restore）、L86-88（resolve_name）。
- 依据：repo 全库 grep —— `contains(` 无调用；`restore(` 无调用（回退实际走 `from_snapshot`，hot_reload.py L259）；`resolve_name(` 仅定义处自身（registry.py L8/L86）出现，**无任何消费方**。`restore` 为 3e §5.1 规定接口（保留合理）；但 `resolve_name` 是 OLD-2「对局快照按 ID 查显示名」的载体，会话层（core/）尚未接线 → 名称冗余当前无人读取，仅写入。属维度②「定义零消费/待接线」。
- 修复建议：会话层（对局快照构建）接线 `resolve_name`；若 M0 明确递延，在 docstring 注明「待会话层接线」，避免被误判为已兑现 OLD-2 展示路径。

### P2-5　models.py 死导入：`Dict`/`List` + 15 个 `data.types` TypeAlias 全零消费
- 位置：`models.py` L16（`Dict, List`）、L18-33（ActionID/EffectID/EnemyID/ItemID/MapID/MarkID/ModuleName/NpcID/PackID/SkillChainID/SkillID/StatKey/StatusID/TraitID）。
- 依据：grep 确认这 17 个名字在 models.py 全文仅出现于 import 语句，正文零使用（模块体全部用 `str`/`Tuple`/`Mapping`/`Any`）。与 L9 铁律「完整类型标注」自述不符（导入了别名却从未用于标注），且为 F401 死代码。维度②「字段/定义零消费」。
- 修复建议：删除未使用导入，或为 Def 类/Manifest/Pack 的相应字段补上类型标注以兑现别名用途（如 `BaseDef.id: str`、`Manifest.pack` 相关）。

### P2-6　Def 类型 8 个属性 getter 全零消费（消费方一律 `.get()`/`raw`）
- 位置：`models.py` L173-183（EffectDef.power/duration）、L190-193（StatusDef.max_stack）、L205-208（SkillChainDef.next）、L220-228（ItemDef.price/atk）、L240-248（EnemyDef.hp/atk）。
- 依据：repo 全库 grep —— 这些 getter 无任何消费方；测试与消费方用 `registry.resolve(...).get("price")`（test_content.py L360/L413）而非 `.price`。`_f` 辅助（L173-175）随 getter 一并零消费。维度②「字段定义零消费」。
- 修复建议：二选一 —— (a) 消费方（effects/items/enemy 计算层）改用类型化 getter（更好）；(b) M0 递延则删除或以 `raw` 直读并在 docstring 注明「API 预留」。

### P2-7　`FieldMeta.default` 零消费 + DEF_CLASSES 与 loader `_KIND_FOR_MODULE` 两表漂移
- 位置：`models.py` L93（`default`）、L266-281（DEF_CLASSES，缺 "formula"、含 "conditional" 死条目）；`loader.py` L142-158（`_KIND_FOR_MODULE` 14 键）。
- 依据：
  1. `FieldMeta.default`（L93）在 validator 全流程零消费（validator 不补默认值）；3e §5.3 元数据含「默认值」列，缺补默认属 3e2 ATO-6 迁移职责（20260818 P2-8 已登记未实现）→ default 为「等迁移」的零消费字段。
  2. `DEF_CLASSES` 13 键 vs loader `_KIND_FOR_MODULE` 14 键：**formula 缺 DEF 类**（loader `DEF_CLASSES.get("formula", BaseDef)` 兜底，字符串值正确、对象值触 P1-3 空 id）；**conditional 为死条目**（conditional 模块为 object 形态，loader `_build_registry` 仅处理 list 与 `("stats","formula")` map，不注册 → `DEF_CLASSES["conditional"]` 永不实例化，loader P2-5 同源）。两张映射表分文件维护、无一致性检查。
- 修复建议：DEF_CLASSES 与 `_KIND_FOR_MODULE` 收敛为单一权威表（或加测试断言两表键集合一致）；conditional 按「仅校验不注册」显式注释或补 object 注册分支；default 关联 ATO-6 迁移落地后再消费。

### P2-8　边界与文档精度（三小项）
- 位置：`models.py` L82（FieldMeta.type 枚举 docstring）、L163-166（from_entry 类型强转）、L308（author 写法）。
- 内容：
  1. **from_entry 宽容强转**（静态推导）：`entry.get("id")` 为 `null` 时 `str(None)` → id `"None"`；数字 id `123` → `"123"` 静默强转。validator 前置会拦（F_ID type=str → R-1），但 `from_entry` 作为公开 classmethod 无防御，对绕开 validator 直建 Def 的路径会产出错误 id。建议对非 str id 显式置空/抛错。
  2. **FieldMeta.type 文档枚举**为 `int|float|number|str|bool|enum|ref|obj|list|map|formula`（L82），3e §5.2（L327）枚举为 `int/str/bool/enum/ref/obj/list/map/formula`（无 float/number）；validator（L455）接受 `int/float/number` 超集，功能无碍，但文档口径与 3e 枚举有偏差（float/number 疑来自不可验证的【规则】L143），建议统一或注明。
  3. `author=str(data.get("author","") or "")`（L308）`or ""` 冗余（str("") 已是 ""），无害但属文档/整洁瑕疵。

---

## 3. 无问题维度确认（静态核对，未发现缺陷）

- **O(1) 引用查表 ✓**：`resolve(id, kind)`（registry.py L84）为 `tables[kind].get(id)` 双字典取，O(1)，符合 §1.6「引用存在性用预构建 ID 集合查表」与 §5.1 接口签名。
- **快照-回退原子性 ✓**：`snapshot()` 深拷贝完整表集合 + 名称冗余 + 模块原始数据 + manifest/schema_version（SNAP-4「完整 registry + 原始数据 + schema_version/manifest 版本」逐项对齐）；`restore()`/`from_snapshot()` 在单锁内完成「构建 + 单引用替换」（`self._tables = new_tables`），CPython 单引用写，读方（`resolve`）无 torn 状态（§4.4/L178「字节一致」语义成立，除 P2-2 的可变快照风险外）。
- **原子引用替换 ✓**：`build()` 构建独立 Registry 对象（D-02「校验通过后才调用」由 loader 保证），hot_reload `_commit_success` 指针级替换（D-03），期间旧引用继续服务（§1.5 L175）——registry 侧不变式注释（L47-48）与实现一致。
- **双快照职责归属 ✓**：registry docstring（L1）正确声明「双快照由 HotReloadWatcher 维护 N=2」，与 hot_reload `deque(maxlen=2)`（hot_reload.py L77）一致；registry 自身只维护当前生效 + 快照接口，职责边界清晰、无重复实现。
- **锁纪律 ✓**：读路径无锁、写（snapshot/restore）单锁（§4.6「读不加锁、写用单写锁」）；registry 无 async、无跨 await 持锁；`snapshot` 持锁深拷贝不与其他锁嵌套。
- **ID 注册 / 注册冲突 ✓（主链路）**：registry 不做重复注册（validator 命名空间前置拦跨模块唯一，D-02 半挂载禁止由 loader 保证）；`build` 整体替换杜绝「半套配置」（L178）。剩余缺口仅 P1-1（registry 自检不回查）与 P2-1（名称冗余跨命名空间覆盖）。
- **3e §5.1 接口逐字段对齐 ✓**：PackError/PackWarning/ValidationReport（L40-69，module/field/kind/detail 四元 + ok 属性）、FieldMeta/ModuleMeta/FieldMetaTable（L77-139）、Manifest（L289-311）、Pack（L324-336）与 §5.1 代码块一致；`ValidationReport.ok` = errors 为空（D-02）。
- **元数据表字段消费核对 ✓**：ModuleMeta 全部字段被 validator 消费（entry_type/id_field/kind/namespace/chain_field/mutex_field/key_regex/value_meta）；FieldMeta 除 `default` 外全部被消费（type/required/ref_target/enum/range/probability/zero_unlimited/soft_label/allow_negative/element/children）。仅 default 待迁移接线（P2-7）。
- **维度③ 幻觉核查 ✓（重点）**：registry.py 引用的 3e §1.3（L4，§1.3 存在、L136 相符）、§1.5 D 阶段挂载（L5，§1.5 L103-107 存在、L175 相符）、§5.1（L6，§5.1 L311-316 存在）、§4.6（L81）、§4.4（L131）、L177/L178/L186（L38/L47 与 3e 自身引用口径一致）；3e2 D-03/D-04（L7，3e2 L51/L52 相符）、SNAP-1~4（L7/L116，3e2 L150-153 相符）、OLD-2（L8，3e2 L184 相符）；3a §4.2 line 254（L9，3a L247「### 4.2 内容包加载流程」、L254 内容「效果注册表三表统一（ID 跨表唯一）/ 行动注册表 / 派生链注册表」相符）；models.py 引用的 3e §5.1/§5.3（L4/L6）、3a §3.3 U2/§3.4（L6）、3b §3.2（L280，3b L143「### 3.2 规则配置」存在）**均真实存在、内容相符，无虚构行号**。工程补白均有显式标注（AnyDef 防循环引用 L23、HotReloadWatcher 维护 N=2 归属 L1、restore 单引用原子写说明 L131-133、Pack 前向引用打标 L318-321），**未发现冒充定稿**。唯一 overclaim 为 P1-1（「自检 A」实现覆盖声明）与 P2-8.2（FieldMeta.type 枚举文档口径）。
- **分层/依赖 ✓**：models 仅依赖 `qbot_rpg.data.types`；registry 仅依赖 `models`/`data.types`；两文件零 NoneBot import（铁律/3a 依赖方向）。
- **文件行数**：models.py 实际 361 行（含末行空行），与任务描述 360 行差 1，无实质差异。

---

## 4. 与前批报告的衔接

- 本批 P1-2/P1-3 分别与前批 loader 报告 P1-2（manifest 非 Mapping）、P1-3（map 形态 Def.id 空串）**同根同源**，本报告从 models/registry 侧给根因与修复落点，不重复计为两套独立缺陷。
- 本批 P2-1/P2-3/P2-7 与 loader 报告 P2-6（names 扁平覆盖）、20260818 P2-15（双深拷贝）、P2-8（ATO-6/default）、loader P2-5（conditional 死条目）对应；P2-2（快照不可变性）、P2-4（零消费 API）、P2-5（死导入）、P2-6（getter 零消费）为本批新增。
- 修复优先级建议：先 P1-1（补自检 A 三项断言 + 单测）→ P1-2（from_dict Mapping 守卫）→ P1-3（map 形态 ID 注入）→ P2 按 2-5-6（零消费清理）→ 2-1（names 键空间）→ 2-2/2-3（快照健壮性）→ 2-7/2-8（表收敛与文档）。

---

*运行行为结论均标「静态推导」，未经任何执行验证；如需运行级证据请授权后补做。*
