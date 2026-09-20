# 框架扩展开发手册 · 第 3 章 · 权责与「勿当 bug 修」

> 本章读者两条线：
> - **外部扩展开发者**（写内容包 / 写包自持代码 / 用 E 系扩展点）——你只该看 §1、§2 的"你做错了会怎样"、§3.1 的四条样例；
> - **未来的框架维护者**（动 `qbot_rpg/**` 之前）——§3 全章 + §4 稳定契约 + §5 改代码前 checklist 是必读。
>
> 本章要解决的问题，用立项原话说：**"避免后续更新将故意的设计作为 bug 修复"**（`docs/深度打造_决策记录.md:1568`）。

---

## 0. 阅读约定（先看这 5 条，后面所有表格都按它读）

| # | 约定 | 含义 |
|---|---|---|
| 0.1 | **复核基准** | 本章所有 `file:line` 均以 **HEAD `62cc299`（批 73 死代码清理后）** 的当前工作树为准，已逐条 `read`/`grep` 复核。上游盘点文档 `API手册_编撰前盘点.md` 基于 `d86d9dd`（批 71 后），**行号有漂移处本章一律以复核后为准**，并在 §6 登记全部偏差。 |
| 0.2 | **置信度** | **高** = 有明文铁律 / 用户拍板 / 代码注释直述"有意/刻意/兼容/不回退"；**中** = 有并存或两轨的事实，但未见"勿修"明示，可能只是"暂时并存、日后收敛"；**低（待查）** = 仅形似、意图未定，**不硬下结论**，写明还缺什么证据。 |
| 0.3 | **【稳定契约】** | 标注此记号的条目 = **改动需评审**（走评审 + 全量回归 + 零行为变化对拍）。它们要么是公开字段名，要么是跨模块顺序契约，要么是被外部内容依赖的兼容层。 |
| 0.4 | **【勿动】** | 标注此记号 = 与"稳定契约"叠加的最强档：**改它 = 已知会破坏玩法或旧内容**。误修后果写在同一条目里。 |
| 0.5 | **【待查】** | 证据不足，**不得**据此改代码；先补证据（章节里写明了需要什么）。 |

**一个反直觉但关键的前提**：框架里"看起来重复/写死/不生效"的东西，**绝大多数是刻意设计**（本章 §3 收录 40+ 条）。真正的 bug 也存在（见 §3.7），但判断顺序必须是 **先查本章 → 再看稳定契约 → 再跑门禁 → 最后才改**。反过来做，就是本章要防的事故。

---

## 目录

- [§1 三层权责地图：谁拥有什么、改哪里安全、代价多大](#1-三层权责地图)
  - [1.1 一张图看懂三层 + 两处开关](#11-一张图看懂三层--两处开关)
  - [1.2 框架层 `qbot_rpg/**`](#12-框架层-qbot_rpg)
  - [1.3 内容包层 `content/<包>/**`（纯 JSON）](#13-内容包层-content包纯-json)
  - [1.4 包自持代码层 `ext/` + `tests/` + `scripts/`（双闸默认关）](#14-包自持代码层-ext--tests--scripts双闸默认关)
  - [1.5 编辑器层 `qbot_rpg/web/**`（附加角色）](#15-编辑器层-qbot_rpgweb附加角色)
  - [1.6 三层对照总表（本条=§1 的浓缩版）](#16-三层对照总表)
- [§2 门禁清单（28 条）](#2-门禁清单28-条)
  - [2.1 最硬红线：红拦 5 类 → 整包拒绝](#21-最硬红线红拦-5-类--整包拒绝)
  - [2.2 28 条门禁逐条表](#22-28-条门禁逐条表)
  - [2.3 门禁的诚实边界（哪里没门禁）](#23-门禁的诚实边界哪里没门禁)
- [§3 ★「勿当 bug 修」正式清单（本章核心交付）](#3-勿当-bug-修正式清单本章核心交付)
  - [3.0 怎么用这份清单](#30-怎么用这份清单)
  - [3.1 用户点名四样例（逐条独立复核）](#31-用户点名四样例逐条独立复核)
  - [3.2 A 组：文档铁律（A1–A11）](#32-a-组文档铁律a1a11)
  - [3.3 B 组：合理并存 / 双轨（B1–B12 + 审计3 §6 并入 R1–R13）](#33-b-组合理并存--双轨b1b12--审计3-6-并入-r1r13)
  - [3.4 C 组：代码注释直述（C1–C27）](#34-c-组代码注释直述c1c27)
  - [3.5 D 组：CHANGELOG 批次裁决（D1–D7）](#35-d-组changelog-批次裁决d1d7)
  - [3.6 待查 / 待裁决清单（**不要贴"勿修"标签**）](#36-待查--待裁决清单不要贴勿修标签)
  - [3.7 复核发现：真正的 bug 与"盘点文档偏差"](#37-复核发现真正的-bug-与盘点文档偏差)
- [§4 稳定契约章节（改动需评审）](#4-稳定契约章节改动需评审)
- [§5 给维护者的"改代码前 checklist"](#5-给维护者的改代码前checklist)
- [§6 附：本次复核方法与偏差总表](#6-附本次复核方法与偏差总表)

---

# 1. 三层权责地图

## 1.1 一张图看懂三层 + 两处开关

```
仓库根 /root/QBot-TurnTellerRPG
│
├── qbot_rpg/**                 【第 1 层 · 框架】   机制 / 稳定面 / 门禁 / 校验器
│   ├── data/      领域模型唯一落点（最底层，仅标准库）
│   ├── core/      纯规则引擎（战斗/伤害/锻造/炼金/效果…）
│   ├── content/   内容包模型与校验（loader/validator/registry/field_meta）
│   ├── storage/   SQLite 持久化（每 玩家×内容包 一格，框架零包名）
│   ├── world/     世界与场景（地图/怪物池/会话）
│   ├── commands/  唯一 NoneBot 接触点（壳层）
│   ├── assembly/  装配层（最顶层，只组装不写业务）
│   ├── web/       编辑器外壳（只写内容包目录）
│   ├── testing/   包测试可用辅助面（对外公开）
│   └── ext_api.py 【唯一对外稳定面】
├── qbot_rpg_bridge/**         外层 NoneBot 部署桥接（框架侧）
├── scripts/**  tests/**       仓库工程：门禁脚本 + 主测试套件（框架侧）
│
└── content/<包>/**            【第 2 层 · 内容包】纯 JSON（manifest + 模块文件 + 可选 settings/field_meta/templates）
    ├── ext/                   【第 3 层 · 包自持代码】可执行扩展
    │     ├── commands.py      E1 自定义指令（配 commands.json 声明）
    │     └── render.py        E2 渲染钩子（只许改文本）
    ├── tests/                 E3 包自带测试（不自动进主套件）
    └── scripts/build.py       包自带构建（须支持 --check）
```

**两处开关（第 3 层的总闸，默认都关）**：

| 开关 | 位置 | 缺省 | 作用 |
|---|---|---|---|
| 闸 1（包自己声明） | `content/<包>/settings.json` → `ext.enabled` | `false` | 包作者自己决定要不要启用 |
| 闸 2（部署方给权限） | 启动参数 `--enable-pack-ext` 或环境变量 `QBotRPG_ENABLE_PACK_EXT` | 不出现 | 部署方决定要不要执行第三方代码 |
| **合取** | `assembly/pack_ext.py:141`（`pack_ext_enabled`）、`:114-118`（闸1）、`:125-138`（闸2） | **两闸必须同时为真** | 任一未开 → **完全不读 `ext/`、不 import 任何包内 Python**（`:514-519` 零文件访问） |

> **【稳定契约】** 双闸语义（两闸合取、未开=零文件访问）是 E 方案的装载安全底座，改它等于放开第三方代码执行。成文依据：`docs/游戏包扩展点_方案_E.md:53-58`。

---

## 1.2 框架层 `qbot_rpg/**`

**它拥有什么**：所有机制、不变量、门禁、稳定面、领域模型、持久化。一句话——**"怎么算"归它**。

**它不拥有什么**（红线，误碰即架构缺陷）：
- 不写死任何具体内容包名 / 模块名 / 业务字段名（`qbot_rpg/web/api.py:20`、`qbot_rpg/web/editor_ops.py:20`）；
- 不认任何具体 `pack_id`（`qbot_rpg/storage/schema.py:176`：「每 玩家×内容包 一格、框架零包名」）；
- 不 import `content/` 下具体包（依赖矩阵 `scripts/check_architecture.py:31-47`）。

**分层铁律与依赖方向**（改动前先看这张表）：

| 层 | 允许依赖 | 依据 |
|---|---|---|
| `data` | `set()`（最底层） | `scripts/check_architecture.py:44` |
| `content` | `data` | `:43` |
| `storage` | `data` | `:42` |
| `world` | `data`、`storage`、`content` | `:41` |
| `core` | 不含 `commands`/`web`；与 `world`/`storage`/`content`/`data` 无环 | `check_tc03` `scripts/check_architecture.py:319` |
| `commands` | 唯一 NoneBot 接触点 | `check_tc02` `scripts/check_architecture.py:189` |
| `assembly` | 顶层装配，方向放行（豁免） | `scripts/check_architecture.py:45` |
| `web` | 单向，谁都不依赖它 | `check_tc03`；细化契约 `docs/细化/细化_3a_架构分层契约.md:46`（D-05） |

**改哪里安全**：
- ✅ 安全：在 `core/`/`world/` 新增机制函数；在 `data/` 新增领域模型字段（要过字段元数据迁移门禁）；在 `content/` 新增一条"读包声明"的校验规则。
- ⚠️ 要评审：改 `data/gear_stats.py` 的特效轴表、改 `core/effects.py` 的管线阶段顺序、改 `content/validator.py` 的红拦清单、改 `ext_api.py` 的 `__all__`。
- ⛔ 不要动：`DEFAULT_PIPELINE_ORDER`（`core/effects.py:129-138`）、`EFFECT_AXIS_SPECS`（`data/gear_stats.py:230`）、`EVENT_POINTS`（`data/event_points.py`）、legacy 兜底（见 §3）。

**改的代价**：
1. 必须跑完整门禁链：`ruff` + `mypy` + `scripts/check_architecture.py`（须 `ARCH-OK`）+ `check_m7_content.py` + 全量 `pytest`（`scripts/check_all.py:100`、`scripts/run_all_tests.py:295`）。
2. 涉及公开 JSON 字段名 → 字段元数据迁移门禁必须 diff=0（`scripts/compare_field_meta_migration.py:320`）。
3. **零行为变化对拍**：不改玩法就要求"双尺子"复算逐字段一致（见 §5.4）。

**各子目录权责速查**：

| 子目录 | 一句话权责 | 关键入口 |
|---|---|---|
| `qbot_rpg/`（包根） | 包元信息 + 唯一对外稳定面 | `__init__.py:3-11`；`ext_api.py`（`__all__` `:42-57`、`EXT_API_VERSION` `:59`） |
| `assembly/` | 装配层（只组装不写业务）：loader→registry→GameWorld、Router 注册、包 `ext/` 通用装载 | `bootstrap.py:40`、`:60`（游玩门禁）、`router_setup.py:1`、`pack_ext.py:481`、`pack_render.py:319` |
| `commands/` | **唯一 NoneBot 接触点**（壳层）：注册/解析/权限/错误翻译/分条发送/幂等 | `router.py:191`（`Router`）、`:205`（`register`）、`parsers.py:112`（`DEFAULT_WHITELIST`）、`processing.py:267`（`process_message`） |
| `content/` | 内容包模型与校验：loader/validator/registry/字段元数据/原子写盘/包保护/导入导出 | `loader.py:235`（`build_pack`）、`:328`（`_raise_if_blocked`）、`validator.py:3901`（`check_pack`）、`registry.py:44`、`field_meta.py`、`module_catalog.py:68` |
| `core/` | **纯规则引擎** | `battle.py`、`damage.py`、`effects.py`、`event_dispatcher.py`、`message_format/`、`templates/template_table.json:1-5` |
| `data/` | **领域模型唯一落点**（最底层，仅标准库）+ 键空间常量 | `player.py`、`battle.py`、`status.py`、`item.py`、`world_state.py`、`gear_stats.py`、`event_points.py` |
| `storage/` | **SQLite 持久化** | `repository.py`、`schema.py:176`、`migrations.py`、`pack_state.py`、`pending.py` |
| `testing/` | **测试基建（对外公开面）**：包自带测试可用的通用辅助 + pytest 插件 | `testing/__init__.py:1`、`pytest_plugin.py:27`（注册 `--pack-root`） |
| `web/` | **编辑器外壳**（只读元数据层 + 写入层） | `api.py:171`（`_pack_dir`）、`editor_ops.py:671`（`save_entry`）、`:787`（`copy_framework_override`） |
| `world/` | 世界与场景：全局世界状态、会话互斥、刷新、追击、副本持久化 | `game_world.py:1-18`、`session.py`、`spawn.py`、`chase.py` |
| `qbot_rpg_bridge/`（仓根） | 外层 NoneBot 部署桥接（**不在 `qbot_rpg/` 内**） | `assemble.py:1-21`、`plugin.py` |

---

## 1.3 内容包层 `content/<包>/**`（纯 JSON）

**它拥有什么**：本包的全部内容数据与声明——`manifest.json`（模块声明）、每模块一个 `<模块>.json`、可选 `settings.json` / `field_meta.json` / `templates.json`。一句话——**"有什么内容"归它**。

**它不拥有什么**：
- 不改框架代码；
- **不覆盖框架指令名**（`docs/游戏包扩展点_方案_E.md:69-75`；重名一律拒绝 `assembly/pack_ext.py:331-388`）；
- **不改结算**（包代码不得改数值/改框架状态，`qbot_rpg/ext_api.py:16-18`）；
- **不跨包互调**（`docs/游戏包扩展点_方案_E.md:69-75`）；
- **不得让框架给 `players` 表加包专属列**（`docs/存档格子_内容包作者用法.md:104-109`）——要存状态就用包状态格子（`qbot_rpg/storage/schema.py:176`）。

**Container 事实（最容易踩的坑）**：
- **未在 `manifest.json` 声明的文件存在 → 不加载**（`docs/审查参考/RPG回合制框架设计文档.md:445`、`docs/审查参考/开发规则文档.md:135`）。
- 加载顺序 = 按 manifest 声明顺序，逐个校验（`qbot_rpg/content/loader.py:235` → `:311` → `:328`）。

**改哪里安全**：
- ✅ 安全：包目录内任意 JSON 文件，改完热重载即生效（`qbot_rpg/content/hot_reload.py:191`）；
- ⚠️ 要小心：`settings.schema_ext`（包自持的校验扩展声明，非法 → R-5 不放行，`qbot_rpg/content/validator.py:405-524`）；
- ⛔ 不要做：试图在 `content/` 里放 `.py` 后在主套件里 import（主套件不收集包 `tests/`，`scripts/run_pack_tests.py:18-19`）。

**改的代价**：见 §2.1——**红拦 5 类 → 整包拒绝挂载，registry 保持原状**。这是内容包作者最贵的一类错误。

**真实内容包清单**（供理解"包长什么样"）：

| 包 | 性质 |
|---|---|
| `content/veinborn/`、`content/test_demo/`、`content/demo_full/`、`demo_lv15/`、`demo_lv30/`、`demo_lv45/`、`demo_blank/` | 真实内容包 / 示例包（纯 JSON） |
| `content/zz_craft_demo/` | 深打造示例包 |
| `content/zz_probe_ext/` | **唯一同时具备 `ext/` + `tests/` + `scripts/` 的探针包**（可安全忽略/删除） |
| `content/zz_probe_packmeta/` | 展示元数据探针包 |

> 提醒：探针包与真实包同目录混放（`API手册_编撰前盘点.md` §5 C.4）。不要因为"它看起来像测试残留"就删——`zz_probe_ext` 是 E1/E2/E3 三个扩展点唯一的端到端实证。

---

## 1.4 包自持代码层 `ext/` + `tests/` + `scripts/`（双闸默认关）

**它拥有什么**：包自己的一小段可执行代码，用来做框架没提供的"包特有表现"。

| 形态 | 约定路径 | 装载方式 | 权威 `file:line` |
|---|---|---|---|
| **E1 指令扩展** | `content/<包>/commands.json` + `ext/commands.py` | 双闸开启后 `load_pack_extensions()` 读声明→校验重名→动态 import | `assembly/pack_ext.py:481`（主入口）、`:69-71`（`DECL_FILE`/`EXT_DIR`/`IMPL_FILE`）、`:331-388`（重名拒绝） |
| **E2 渲染钩子** | `content/<包>/ext/render.py`（约定导出 `EVENTS` + `render(event,data,default_text)`） | `load_pack_render_hook()`；**只许改文本、只读快照、异常落默认**；同一双闸 | `assembly/pack_render.py:319`、`:27`、`:348-349` |
| **E3 包自带测试** | `content/<包>/tests/`（pytest 风格） | `python scripts/run_pack_tests.py --pack <名>`；**显式只收该目录，主套件不自动收集** | `scripts/run_pack_tests.py:6-19`、`qbot_rpg/testing/__init__.py:1`、`qbot_rpg/testing/pytest_plugin.py:27` |
| **包自带构建** | `content/<包>/scripts/build.py`（须支持 `--check`） | `python scripts/run_pack_build.py --pack <名> [--check]`；退出码如实转发 | `scripts/run_pack_build.py:39`（`BUILD_ENTRY`）、`:99`、`:112` |

**它不拥有什么**（**能力约束**，`qbot_rpg/ext_api.py:14-19`）：
- 不提供网络 / 子进程 / 任意文件系统读写 / 热加载 / 跨包互调；
- 只许 `import qbot_rpg.ext_api`——**其余 `qbot_rpg.*` 都是内部实现，不承诺兼容**（`qbot_rpg/ext_api.py:5-10`）；
- 读入口一律只读包装（`player`/`settings`/`templates` 为只读映射），**不得改结算、改数值、改框架状态**；
- 可持久化的只有**该包自己的状态格子**（`async get_state / set_state / patch_state / clear_state`，玩家维度隔离，`ext_api.py:50-57`）。

**改哪里安全**：
- ✅ 安全：在双闸开启下，改 `ext/commands.py` / `ext/render.py`；用 `qbot_rpg.ext_api` 里的名字；异常自己捕获；
- ⚠️ 要小心：`ext/` 的路径约束——禁 `..` 组件、禁符号链接、解析后必须仍在包目录内（`assembly/pack_ext.py:181-220`）；重名指令一律拒绝，不支持 `replace=True`；
- ⛔ 不要依赖：**异常静默**。框架会兜底（记日志 + "该功能暂不可用"），但作者应自行捕获可预期错误（`ext_api.py:21-23`）。

**改的代价**：
1. **未启用 = 零代价**：两闸未开时框架完全不读包内 Python（`assembly/pack_ext.py:514-519`）。
2. **启用后失败 = 只降级自己**：`PackExtResult(ok=False)` + 日志，机器人照常启动、其它包不受影响（`pack_ext.py:498-525`）。
3. **`.ttrpack` 不分发扩展代码**：包导出**只收 `.json`/`.md`，拒绝 `.py`**（`content/pack_transfer.py:21`）——**分享包不会携带 `ext/`**，包作者必须知道这一点。

**【稳定契约】** `qbot_rpg.ext_api` 是唯一稳定面，`EXT_API_VERSION = "1"`（`ext_api.py:59`），破坏性变更必须递增版本。包代码越界 import 其它 `qbot_rpg.*`，框架升级不负责不破坏。

---

## 1.5 编辑器层 `qbot_rpg/web/**`（附加角色）

**它拥有什么**：把包元数据翻译成界面 JSON；经 `save_entry` 写**内容包目录内**的 `<模块>.json`（+ `.bak`、原子写）。

**它不拥有什么**（硬约束）：
- 不新写校验规则（复用唯一入口 `content.validator.check_pack`，`web/editor_ops.py:12`）；
- 不写框架代码、不写框架自有文件路径；
- **不硬编码任何包名/模块名/业务字段名**（`web/editor_ops.py:20`、`web/api.py:20`；判据 = "换成另一个包，编辑器零改动可用"，`docs/编辑器重写_需求与约束.md:9-16`）；
- 框架关键模板默认项**只读**——直接保存被拒，必须先 `copy_framework_override` 生成包覆盖（`web/editor_ops.py:70`、`:696-702`、`:787`）。

**编辑器边界成文出处**：`docs/编辑器使用说明.md:514-516`、`:526`；`docs/编辑器重写_需求与约束.md:9-16`、`:64`、`:172`。

---

## 1.6 三层对照总表

| 维度 | 第 1 层 框架 `qbot_rpg/**` | 第 2 层 内容包 `content/<包>/**` | 第 3 层 包自持代码 `ext/`+`tests/`+`scripts/` |
|---|---|---|---|
| **拥有** | 机制、不变量、门禁、稳定面、领域模型、持久化 | 本包全部内容数据与声明（JSON） | 包特有指令 / 渲染钩子 / 包自测 / 包构建 |
| **不拥有** | 具体包名 / 业务键 / `pack_id` | 框架代码、框架指令名、结算、跨包读写、`players` 专属列 | 稳定面以外的一切：网络/子进程/任意 FS/热加载/跨包互调 |
| **改哪里安全** | 新增机制、读包声明；改公开字段名要过迁移门禁 | 包目录内 JSON；未声明文件不加载 | 双闸开启后改 `ext/*.py`；只用 `ext_api` |
| **改的代价** | 全量门禁 + TC-01~04 + 零行为对拍 | 红拦 5 类 → 整包拒绝；黄提示不阻断 | 未启用零代价；启用后失败只降级自己 |
| **默认状态** | 生效 | 生效（但按 manifest 声明加载） | **关闭**（两闸默认关） |
| **谁能改** | 框架维护者（走评审） | 包作者 / 编辑器 | 包作者（需部署方开闸） |
| **权威成文** | `docs/审查参考/RPG回合制框架设计文档.md:20-33`、`docs/审查参考/开发规则文档.md:50-54` | `docs/游戏包扩展点_方案_E.md:5`、`:38-39` | `docs/游戏包扩展点_方案_E.md:53-58`、`:69-75` |
| **本章相关「勿当 bug 修」** | §3 全部 | §3.2 A8 / A10 / A11；§3.3 B1/B2 | §1.4 双闸；§3.5 D1（71-A2 兜底不删） |

**为什么这样切**（设计意图，别当偶然）：框架要能**在不改一行代码的情况下换包**（"换包零改动"最高原则，`docs/编辑器重写_需求与约束.md:9-16`）。因此凡是"某个包特有的东西"都必须下沉到第 2/3 层，框架只留**读声明的机制**。第 3 层之所以默认关，是因为执行第三方代码需要显式双开关（信任模型）。

---

# 2. 门禁清单（28 条）

## 2.1 最硬红线：红拦 5 类 → 整包拒绝

**这是全部内容包数据进入运行时的唯一收口**，也是"只建议不限制"哲学的硬边界。

| 项 | 内容 |
|---|---|
| **落点** | `qbot_rpg/content/loader.py:235`（`build_pack`，docstring 明写"任一红拦抛 `PackLoadError`"）→ `:328`（`_raise_if_blocked`）→ `:345`（`load_pack`）；校验入口 `qbot_rpg/content/validator.py:3901`（`check_pack`） |
| **红拦封闭清单** | 仅 **5 类**：类型错误 / 负数 / 非数字 / **引用不存在** / 结构错误（含死配置）——`qbot_rpg/content/validator.py:4`（§2.1 R-1~R-5） |
| **黄提示** | 数值范围等只进 warnings，**不阻断**（`validator.py:5`，§2.2 Y-1~Y-8） |
| **失败后果** | 抛 `PackLoadError`（`loader.py:49`）→ **整包拒绝挂载、registry 保持原状**；黄提示 → 可加载但进 warnings |
| **成文依据** | `docs/审查参考/RPG回合制框架设计文档.md:741`（红拦仅 5 类）、`:780-805`（人话报错）、`docs/审查参考/开发规则文档.md:148-159` |

> **给外部开发者的两条铁律**：
> 1. 报错里会写**哪个包、哪个键、什么问题**（`content/field_meta_pack.py:199-298` 报错含包名+出错键）——照着改即可，不要改框架；
> 2. **不要为了让自己的包过校验而放宽 `validator.py` 的红拦清单**——那会放开所有包。要用"包自持校验扩展"：`settings.schema_ext.<module>.<path>.allow_keys`（`validator.py:389-524`，批 71 · D1）。这是**给包开的口子，不是给框架改的规则**。

---

## 2.2 28 条门禁逐条表

> 口径：脚本类门禁失败 = `exit≠0`；pytest 类 = 用例红；加载/写入链路类 = 结构化拒绝 + 人话 + 不落盘/不装载。
> 行号均为 HEAD `62cc299` 复核值（与盘点文档 `API手册_编撰前盘点.md` §5 B.1 的差异见 §6）。

### A. 架构门禁（5 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 1 | **架构门禁 G0 · TC-03**（依赖方向/无环/叶子层） | `scripts/check_architecture.py:319`（`check_tc03`）；主流程 `:422`；依赖矩阵 `:31-47` | 分层铁律 R3 / D-05：`commands`/`web` 不被任何层 import；`core/world/storage/content/data` 之间无环；跨层方向符合矩阵；`assembly` 顶层豁免 | 输出 `ARCH-FAIL` + 违规清单，`exit 1`。**先看违规边属于哪两层，改 import 方向，不要改矩阵** |
| 2 | **架构门禁 G0 · TC-01**（零 NoneBot 五层） | `scripts/check_architecture.py:167`（`check_tc01`）；nonebot 检测 `:140-164` | R1「引擎层可脱离 NoneBot 单测」：`core/world/storage/content/data` 全部 `.py` 无 `import nonebot`（含 `ImportFrom` 与 `importlib.import_module`/`__import__` 动态形态） | `exit 1`。把 NoneBot 相关代码挪回 `commands/` |
| 3 | **架构门禁 G0 · TC-02**（commands 唯一适配器） | `scripts/check_architecture.py:189`（`check_tc02`） | R2「commands 唯一 NoneBot 接触点」：全仓 import nonebot 的文件只允许在 `qbot_rpg/commands/` 内 | `exit 1`。同上 |
| 4 | **架构门禁 G0 · TC-04**（领域类型唯一性） | `scripts/check_architecture.py:381`（`check_tc04`）；必需类型 `:49-51` | D-03 / U1：`Player`/`BattleSnapshot`/`StatusInstance`/`ItemInstance`/`WorldState` 各定义一次、均在 `data/`、且 `dataclass(frozen=True)` | `exit 1`。**不要新增第二份同名类型**；要在别处用就 import `data/` |
| 5 | **架构契约镜像测试** | `tests/contract/test_g0_architecture.py:25`、`:35`、`:49`、`:82` | 让架构门禁随主测试套件被回归（subprocess 断言 `exit 0` + `ARCH-OK`，并复用其纯函数做静态断言） | 用例红。见第 1 条的处置 |

### B. 字段 / 迁移门禁（2 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 6 | **字段元数据迁移门禁**（重定基线对拍） | `scripts/compare_field_meta_migration.py:320`（`DEFAULT_BASELINE_REF = "07293ee"`）、`:534`（`compare_snapshots`）；自证测试 `tests/unit/test_editor_pack_field_meta_migration.py:1` | 「**JSON 字段名 = 公共 API**」的向后兼容（`docs/审查参考/开发规则文档.md:68`）：用 `git worktree` 检出基线树逐字段对拍——① 删除任一项→红；② 值变化→红（派生展示键记 soft）；③ 新增→允许但逐条列出；④ `label/help/group` 与模块声明严格相等 | `exit 1`（硬差异 > 0）。**这是"改字段名"必须过的门**：要么保留旧键做兼容，要么走迁移方案重定基线 |
| 7 | **迁移脚本幂等门禁** | `scripts/migrate_pack_field_meta.py:43`（`DEFAULT_BASELINE_REF = "995e91b"`）、`--check` 只比对不落盘 | 包展示元数据下放的**可重复导出**，防手改漂移 | `--check` 不一致 → `exit 1`。重跑导出或修包，不要手改基线 |

> ⚠️ **两个基线值语义不同，别混用**：`:320` 的 `07293ee` = 等价性对拍基线；`migrate_pack_field_meta.py:43` 的 `995e91b` = 结构导出基线（`API手册_编撰前盘点.md` §5 C.3.4 已登记）。

### C. 零包名门禁（4 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 8 | **零包名门禁（后端源码）** | `tests/unit/test_editor_batch8_modules.py:272`（`test_catalog_source_has_no_real_pack_names`）、`:279`（`test_editor_code_has_no_pack_names`） | 「编辑器 = 通用工具、换包零改动」最高原则：框架/编辑器/模块目录源码不得出现真实包名；模块目录条目只含 module/label/purpose/entry_type/requires | 用例红。把包名从框架源码删除，改由包声明提供 |
| 9 | **零包名门禁（预设源 + 前端预设区）** | `tests/unit/test_editor_batch65_module_presets.py:357`、`:435` | 推荐组合后端预设源 + 前端预设渲染区源码零包名/零硬编码模块清单（数据全来自后端） | 用例红。同上 |
| 10 | **零包名门禁（换包验收脚本自身）** | `tests/unit/test_editor_pack_switch.py:153` | 验收脚本不写死包名（否则"换包零改动"自证失真） | 用例红。同上 |
| 11 | **框架零包名红线**（批 71 成文） | `CHANGELOG.md:65-67`（批 71「包专属残留清理…框架零包名红线」）；实现 = **包声明驱动 + 框架读取 + legacy 兜底** | 框架不得内联具体包的业务文案/状态 id/面板 id/条件过滤；改由包 `templates.json` / `statuses[].stance=="air"` / `settings.*` 声明 | **无独立全局扫描脚本**；由 8/9/10 三处测试 + 人工评审承载（见 §2.3 缺口） |

### D. 一键入口 / 静态 / CI（6 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 12 | **统一检查入口 `check_all.py`** | `scripts/check_all.py:100`（`main`）、`:123`（全量→`run_all_tests`）、`:134`（`check_m7_content`） | 单一下发点，防各门禁口径分裂；报告归档 `docs/verify/check_report.md` | 任一失败 → `exit 1` |
| 13 | **全量回归 `run_all_tests.py`** | `scripts/run_all_tests.py:295`（`main`）、`:243`（阶段 0 ruff+mypy）、`:218`（阶段 3 覆盖率）、`:59`（阶段 2 严格里程碑依赖序 m0→m6→M9） | 里程碑验收的唯一官方回归入口；CI 直接调用本入口保证本地/CI 同口径 | 任一阶段失败 → `exit≠0` |
| 14 | **ruff 门禁（含存量基线）** | `pyproject.toml:22-29`（`line-length=100`、`select=["E","F"]`）、`:31-214`（`per-file-ignores` 存量豁免）；执行 `scripts/run_all_tests.py:243` | E/F 组规则；**无全局 ignore E501**；存量问题文件级豁免，**清单外新增必拦** | 非 0 → 阶段 0 fail → `exit≠0`。新增代码零豁免 |
| 15 | **mypy 门禁（含存量基线）** | `pyproject.toml:216-225`（non-strict + `warn_unused_ignores`/`warn_redundant_casts` + `explicit_package_bases`/`namespace_packages`）；执行 `scripts/run_all_tests.py:243` | 类型标注纪律（`docs/审查参考/开发规则文档.md:71-74`）；存量按行内 `# type: ignore[码]` 逐处标注 | 非 0 → 阶段 0 fail |
| 16 | **lint/type 基线清单门禁** | `docs/verify/lint_baseline.md:1`；基线文件 `qa_ctb_baseline_ruff.txt`、`qa_ctb_baseline_mypy.txt`；脚本 `scripts/verify_ctb.py:1` | 按「(文件:行:列)→错误码」指纹化取集合差：基线有当前无 = 修复（允许），当前有基线无 = **新增 FAIL** | 任一 FAIL → `exit 1`。防"数量持平但换了位置"的假绿 |
| 17 | **CI 流水线门禁** | `.github/workflows/ci.yml:46-47`（调 `run_all_tests.py` 全量）、`:50-55`（归档 `docs/verify/`） | CI 直接调用本地同一全量入口，**不自定义第二套阈值**；任一 step 失败即 job 失败 | job 失败。本地先跑 `scripts/check_all.py` 对齐 |

### E. 内容包校验 / 保护 / 装载（6 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 18 | **内容包校验器（红/黄二分）** | `qbot_rpg/content/validator.py:3901`（`check_pack`）、`:4`（R-1~R-5 封闭清单）；接线 `content/loader.py:235` → `:328` → `:345` | 「只建议不限制」哲学 + 防坏包半套运行；字段口径来自 `field_meta.py` 唯一数据源 | 红拦 → `PackLoadError`，**整包拒绝挂载**；黄提示 → 可加载但进 warnings。见 §2.1 |
| 19 | **数据包保护游玩门禁** | `qbot_rpg/content/pack_protection.py:150`（`enforce_play_gate`）、`:38`（`PackProtectionError`）；调用点 `assembly/bootstrap.py:60` | 作者更新半成品包期间不破坏玩家体验；把既有 Y-6（声明缺文件）在保护期升级为阻断；**不新增第二套校验逻辑**、不影响编辑器 | `PackProtectionError` → 拒绝进入游玩（人话：哪个包/什么问题/去哪改） |
| 20 | **内容包扩展双闸门禁** | `qbot_rpg/assembly/pack_ext.py:141`（`pack_ext_enabled`）、`:114-118`（闸 1）、`:125-138`（闸 2）、`:514-519`（未启用直接返回、零文件访问）；渲染侧 `pack_render.py:348-349` | **默认安全**（执行第三方代码需显式双开关）；包扩展失败不拖垮框架/其它包 | 未启用 = 无该扩展；启用后失败 = `PackExtResult(ok=False)` + 日志，机器人照常启动 |
| 21 | **编辑器框架关键模板只读门禁** | `qbot_rpg/web/editor_ops.py:70`（`_framework_locked`）、`:79`（`_framework_lock_error`）、`:696-702`（`save_entry` 命中即 red 返回、零文件改动）；哨兵 `web/api.py:66` | 框架默认内容保持干净；包覆盖与框架默认分离 | `level=red`、本次**未写入任何文件**。先 `copy_framework_override`（`editor_ops.py:787`） |
| 22 | **编辑器保存原子性 / 回退门禁** | `qbot_rpg/web/editor_ops.py:671`（`save_entry`：红拦不落盘→备份→原子写→回读复核）；`content/atomic_store.py:225-237`（temp + `os.replace`）、`:402`（`backup`）；热重载回退 `content/hot_reload.py:191` | 「**永不假成功**」与热重载原子性（`docs/审查参考/开发规则文档.md:178`） | 结构性拒绝 + 人话；复核失败 `rolled_back`；绝不假成功/半套配置 |
| 23 | **包展示元数据严格解析门禁** | `qbot_rpg/content/field_meta_pack.py:10`、`:83`（允许键集合，未知键报错不静默）、`:199-298`（各形态 `_fail`，报错含包名 + 出错键） | 防各家包写法漂移；包声明优先于框架兜底但形态受控 | 解析层报错（指出包名 + 出错键），不静默吞 |

### F. 其它专项门禁（6 条）

| # | 门禁名 | 把关点 `file:line` | 它保护什么 | 触发了怎么处理 |
|---|---|---|---|---|
| 24 | **包导出 / 导入安全门禁** | `qbot_rpg/content/pack_transfer.py:21`（类型白名单：只收 `.json`/`.md`）+ 同文件 Zip Slip / 符号链接 / 体积上限 / sha256 / 过校验器 / 原子搬迁六条；CLI `scripts/pack_transfer.py` | 防 zip slip / zip bomb / 篡改；**导入不可绕过内容校验器**；`.ttrpack` 不携带 `.py` | `exit 1` / `{ok:false}` + 人话，不落盘 |
| 25 | **内容包可达性 / 条件键 / 占位符校验** | `scripts/check_m7_content.py:19-21`（校验项 1/2/3；缺省只查 `content/demo_lv15`） | 防「永不可发现」的隐藏内容与未注册条件键 / 非法占位符 | `exit 1` = 有提示（**提示性不阻断**，可保存但建议修）。⚠️ 缺省只查一个包，见 §2.3 |
| 26 | **M8 炼金 fixtures 自检门禁** | `scripts/check_m8_fixtures.py:1`（八项断言，无引擎依赖） | 炼金数据契约（REC/TRT/PRF/ALC）先行自检：JSON 可解析 / 必填键 / 包内引用自洽 / 进化线无环 / 元素键 ∈ 8 元素 / `manifest.modules` 与磁盘一一对应 / `settings.alchemy` 类型 / 品质键枚举 | `exit 1`（列出 FAIL） |
| 27 | **消息模板宽度门禁** | `scripts/check_template_width.py:30`（`BUDGET_HALF = 28` = 14 全角，2026-09-12 用户实机标定） | 手机 QQ 单行不折行；模板排版规范 | `exit 1`（存在 FAIL）。`meta.prose_keys` / `prose_placeholders` 登记项豁免（见 §3.4 C7） |
| 28 | **CTB 专用门禁** | `scripts/verify_ctb.py:1`（G-LINT-RUFF / G-LINT-MYPY / G-CTB-TEST / G0-ARCH） | CTB 重写期的「只减不增」质量护栏 | `exit 1` |

**门禁计数 = 28 条**（与盘点文档 §5 B.1 一致；#1 为 TC-03 主门禁，#6 为字段元数据迁移门禁，#8/#9/#10/#11 为零包名门禁族）。

**门禁成文规定位置总表**（与上表一一对应，供评审时引用）：

| 门禁族 | 成文 `file:line` |
|---|---|
| 架构 TC-01~04 / 依赖矩阵 R3 | `docs/细化/细化_3a_架构分层契约.md:59`（R3 铁律）、`:46`（D-05 web 单向）、`:86-96`（§1.4 依赖方向矩阵）、`:350-356`（TC 用例，TC-03 在 `:354`） |
| 门禁工具清单与通过标准 | `docs/检查工具指南.md:9-22`、`:28-35`（`check_architecture.py` 须 `ARCH-OK`）、`:37-42`（`verify_mN`） |
| ruff / mypy 工具链 | `docs/审查参考/开发规则文档.md:119-123`、`:92`；`docs/细化/细化_M6_质量门禁.md:118`、`:187-188`、`:207-208` |
| 字段元数据迁移门禁 | `docs/深度打造_决策记录.md:813-820`（门禁命令 + soft/hard 语义） |
| 零包名门禁 | `docs/编辑器重写_需求与约束.md:64`、`:172`、`:11-16`；`docs/编辑器重写_实现方案.md:387`、`:404`；`CHANGELOG.md:65-67` |
| 内容包红/黄校验 + 加载 | `docs/审查参考/RPG回合制框架设计文档.md:741`、`:780-805`、`:765-766`、`:445`；`docs/审查参考/开发规则文档.md:148-159`、`:135` |
| 扩展点与装载安全 | `docs/游戏包扩展点_方案_E.md:5`、`:38-39`、`:53-58`、`:69-75` |
| 编辑器只改内容包 | `docs/编辑器使用说明.md:514-516`、`:526`；`docs/编辑器重写_需求与约束.md:9-16`、`:55`、`:266-268` |
| CI 流水线 | `docs/细化/细化_M6_质量门禁.md:187-188`、`:207-208`；`.github/workflows/ci.yml:46-47` |

---

## 2.3 门禁的诚实边界（哪里没门禁）

维护者最容易误判的地方：**"有测试覆盖" ≠ "有全局门禁"**。以下缺口是盘点 + 本章复核确认的，写出来是为了让后来人别把"约定"当"强制"。

| # | 缺口 | 事实 | 影响与建议 |
|---|---|---|---|
| G-1 | **"框架零包名"没有单一全局门禁** | 被拆成至少 4 处测试（`tests/unit/test_editor_batch8_modules.py:272`、`:279`；`test_editor_batch65_module_presets.py:357`、`:435`；`test_editor_pack_switch.py:153`）+ `CHANGELOG.md:65-67` 成文红线，覆盖的是**特定文件/特定区域**，**不是全仓 `qbot_rpg/**` 扫描**。框架里仍有 `veinborn` 字样（多为注释/排障说明，如 `core/battle.py:347`、`core/equipment.py:85`），现有测试不会拦 | 零包名是**约定 + 抽样门禁 + 评审**。改框架时请人工 grep 一次，别指望脚本 |
| G-2 | **`check_m7_content.py` 缺省只查一个包** | 缺省 `content/demo_lv15`（`scripts/check_m7_content.py:21`），`check_all.py:134` 默认也只跑该缺省，**并未遍历全部内容包** | 多包项目要显式 `--path`，否则"可达性/条件键/占位符"三类问题漏检 |
| G-3 | **门禁命令的"唯一权威清单"分散** | `docs/检查工具指南.md`（工具清单）、`docs/细化/细化_M6_质量门禁.md`（LNT/COV/CI）、`scripts/check_all.py`（调度）、`scripts/run_all_tests.py`（阶段）各自维护一份 | 以 `scripts/check_all.py` 为准；文档清单可能与它对不上 |
| G-4 | **三个脚本只有 docstring 自述依据** | `scripts/check_m8_fixtures.py`、`check_template_width.py`、`verify_ctb.py` 在 `docs/检查工具指南.md:28-35` 的工具清单里**未被登记** | 不是失效，只是缺文档条目；不要因为"清单里没有"就删脚本 |
| G-5 | **文档与实现不一致（覆盖率目录）** | `docs/细化/细化_M6_质量门禁.md:73` 写"`core + engine + content` 三目录各 ≥80%"，但 `qbot_rpg/engine/` 已撤销并入 `core/`；实现侧 `scripts/run_all_tests.py:117` 明确"收敛为 core + content 两目录" | 文档未同步。以脚本为准："core + content 各 ≥80%" |
| G-6 | **分层/目录名旧文档未同步** | `docs/审查参考/RPG回合制框架设计文档.md:48-76` 与 `docs/审查参考/开发规则文档.md:36-48` 仍写旧目录 `engine/`、`state/`、`editor/`、`utils/`；实际落点见 `docs/细化/细化_3a_架构分层契约.md:42`（D-01） | 实际分层以 `scripts/check_architecture.py:31-47` 的依赖矩阵为准 |
| G-7 | **批 71 引用的两份依据文档在仓库内不存在** | `CHANGELOG.md:66` 引用 `批71_包专属残留_改造方案.md` 与 `框架体检报告.md`，`find`/`ls docs/` 均未找到；"未完成：71-A2…与 71-B1/B2/B3"的收尾状态仅存于 `CHANGELOG.md:87-88` | 两份原始裁决在仓外 `/root/deliverables/`。**写"legacy 兜底勿删"时必须引 §3.5 D1**，不要引不存在的那份 |

---

# 3. ★「勿当 bug 修」正式清单（本章核心交付）

## 3.0 怎么用这份清单

**判断一个"疑似 bug"的标准流程**：

1. **先在本章搜现象关键词**（例如"锻造没有成功率" → §3.1 样例①；"两处都换算" → §3.4 C3）。
2. 命中条目 → 看 **判据来源 `file:line`** 自己点开确认一次；看 **置信度**：
   - **高** → 有明文依据，**默认不要改**；要改先走 §4 评审；
   - **中** → 可能只是"暂时并存、日后收敛"，**先查是否有 ADR/裁决**，别贴"勿修"标签；
   - **低（待查）** → **不要动**，先补证据（条目里写了缺什么）。
3. 没命中 → 去 §3.7（真正的 bug 与偏差登记）确认它是不是已登记项。
4. 仍无法判断 → 按 §5 的 checklist 做，**并且把新结论回填本章**。

> **重要提醒（防止本章被滥用）**：本章不是"反对修 bug"的挡箭牌。**已确认的真 bug 列在 §3.7**，包括：`damage_base`/`heal_rate` 死兼容键（`docs/深度打造_决策记录.md` 相关待裁决项 D8）、`StatusInstance` 死表示（审计3 F6）、`forge.decompose_rate`（已于批 70 删除）等。真正的 bug 要修，本章只是要求"先确认它不是设计"。

**清单规模与置信度分布**（正式清单 = A 11 + B 12 + C 27 + D 7 = **57 条**；再加审计3 §6 并入的 R1–R13 = **13 条**，合计 **70 条**）：

| 置信度 | 条数 | 编号 |
|---|---|---|
| 高 | **56** | A1–A9、A11；B1–B4、B6、B7；C1–C7、C9、C12–C19、C21、C22、C25–C27；D1–D6；R1–R13 |
| 中 | **13** | A10；B5、B8、B9、B11、B12；C8、C10、C11、C20、C23、C24；D7 |
| 低（待查） | **1** | B10（另见 §3.6 T1–T13 的"待裁决"项，它们**不计入**本清单的"勿修"结论） |

（§3.1 的四样例与 A 组/C 组部分条目同源，**未重复计数**：样例①= A1/A2，样例②= C3，样例③= C1/C2/D1，样例④= C4/S2。）

---

## 3.1 用户点名四样例（逐条独立复核）

> 上游 §7 自述"未逐条复核全部行号（已抽样核验 §1-①/②/③/④）"。本节**逐条复核**了这四条的全部 `file:line`，结论：**四条全部成立，置信度维持"高"**；仅个别行号漂移（已在表内更新）。

### ★ 样例① 锻造无随机（forge 100% 确定性）—— **置信度：高**（8 处依据全部复核通过）

| 项 | 内容 |
|---|---|
| **现象（为什么形似 bug）** | 同样输入 1000 次，产出/消耗/经验/日志逐次一致；"素材够即成功、失败零消耗"——看起来"缺了成功率判定 / 没有失败分支"。`/锻造` 一条指令即时出结果，看起来"少了确认步骤"。 |
| **真实设计意图** | 失败与随机被**刻意隔离**到炼金（品质/特性）与强化（成功率）；锻造是**确定性派生树 + 零会话原子**，素材即进度。 |
| **判据来源（逐条复核后）** | ① `docs/m9_启动包.md:75`（"路6A 边界铁律：锻造 100% 确定性（无随机）…"）✅<br>② `docs/m9_启动包.md:95`（"用户拍板不可擅改：锻造「100% 确定性」「零会话」…实现不得引入随机/会话"）✅<br>③ `docs/规划/规划_路2c2_锻造.md:142`（"锻造 100% 确定性：失败/随机全部隔离于炼金（品质/特性）与强化（成功率）——锻造路径无随机分支"）✅<br>④ `docs/规划/规划_路2c2_锻造.md:147`（验收标准："锻造结果无随机路径"；盘点写的 `:146` 是相邻的"强化数值层归 enhance.json，锻造不写数值层"）<br>⑤ `docs/细化/细化_2c2b_锻造流程契约.md:14`（"100% 确定性…随机性不同源"）✅<br>⑥ `docs/细化/细化_2c2b_锻造流程契约.md:250`（TC-04："直锻同样输入 1000 次（种子 2026）→ 产出/消耗/经验/日志逐次一致（差分=0）；引擎无随机源"）✅<br>⑦ `docs/审查/覆盖审计_F_生活生产.md:63`（G-02 边界铁律：100% 确定性/三系统分工/随机性不同源）✅<br>⑧ `docs/审查/覆盖审计_F_生活生产.md:72`（G-11："100% 确定性：三谓词唯一决定、失败零副作用"）✅ |
| **置信度** | **高**（8/8 复核通过） |
| **【稳定契约】【勿动】** | 是 |
| **若被误修会怎样** | 给 forge 加随机 = **违背用户拍板铁律**（`docs/m9_启动包.md:95`）；破坏 TC-04 确定性差分=0、素材经济与"带孔装备唯一常规来源"口径；补会话会破坏"原子/零副作用"与幂等断言。 |
| **正确改法 / 不要动** | **不要动**。要加随机内容请去**炼金（品质/特性）**或**强化（成功率）**——那是设计规定的随机归属地。 |

### ★ 样例② 别名归并（键族 aliases）—— **置信度：高**

| 项 | 内容 |
|---|---|
| **现象** | 同一效果可写成新键或旧键，且旧键值常与轴符号相反（如 `immune_dmg` → `damage_taken_pct` 取负），看起来"重复字段 / 符号写错"。 |
| **真实设计意图** | 旧键 → 特效轴的**唯一兼容换算**：`pct = sign × 旧键值`；**只在聚合入口换算一次、不双计**；旧键自身链路不动。 |
| **判据来源（复核后）** | ① `qbot_rpg/data/gear_stats.py:26-30`（`cooldown_reduction_pct` 归 PLACEHOLDER，批 53 起经 `route_legacy_aliases_into_flat` 换算为 `flat["cooldown_pct"] = −旧值`，"只发生一次"）✅<br>② `qbot_rpg/data/gear_stats.py:60-62`（`legacy_alias` 声明口径：`pct = sign × 旧键值`；`sign = -1` = 旧键语义与本轴相反；"旧键自身链路本批不动"）✅<br>③ `qbot_rpg/data/gear_stats.py:584-589`（`EFFECT_LEGACY_ALIASES` 反查表）✅<br>④ `qbot_rpg/data/gear_stats.py:754-783`（`route_legacy_aliases_into_flat` 唯一换算入口 + docstring 明写"同一旧键不可能被两条路径各消费一次（不双计）"）✅<br>⑤ `qbot_rpg/data/gear_stats.py:720`、`:743`（`route_bonus_into` 对占位键显式 `continue` 跳过 → 不进 pct/flat）✅<br>⑥ `qbot_rpg/core/equipment.py:1006-1008`（聚合入口调用 `route_legacy_aliases_into_flat` 的唯一处）✅<br>⑦ 对照（条件引擎）：`qbot_rpg/core/condition_engine.py:98-105`（`OP_SYMBOL_ALIASES`）、`:108`（`OP_LEGACY_ALIASES`）、`:111-123`（`normalize_op`）、`:155`（`VAR_ALIASES`）、`:212-227`（`normalize_var` 识别顺序）✅<br>⑧ `qbot_rpg/data/gear_stats.py:248`（`heal_amp_pct` sign +1）、`:259`（`immune_dmg` sign −1）、`:272`（`weakness_dmg_pct` sign +1）、`:286`（`cooldown_reduction_pct` sign −1）、`:298`（`debuff_chance_pct`/`buff_chance_pct` sign +1）✅ |
| **置信度** | **高** |
| **【稳定契约】【勿动】** | 是（旧键是**拍板的兼容承诺**，且是占位键归并机制的唯一样板） |
| **若被误修会怎样** | 删旧键别名 → 旧内容包数值**静默失效**；改成两处都换算 → **双计**（同一旧键被消费两次，数值翻倍）；把 `sign=-1` 当 bug 改成正号 → **免伤变易伤**、冷却减缩变增加。 |
| **正确改法 / 不要动** | **不要动**。要新增"旧键→轴"只加 `EFFECT_AXIS_SPECS[*].legacy_alias`（唯一源，`gear_stats.py:230-447`），换算自动经现有三个分层且互斥的换算点（占位键 / pct 层 / COMBAT 旧键）。**不要**另开第四个换算点。 |

### ★ 样例③ legacy 兜底 / 声明+兜底双轨 —— **置信度：高**

| 项 | 内容 |
|---|---|
| **现象** | 框架里硬编码一小撮包专属 id（`sw_vault_air`、`sword_flow`），看起来"框架残留包名、该清理"。 |
| **真实设计意图** | 是**降级兜底**：权威来源已改为包声明（`statuses[].stance=="air"` / `marks[].role=="combo_counter"`），包不声明时回落旧集合以保**逐位一致**；实现明写 `or` **不是 union**（一旦有声明就完全以声明为准）。 |
| **判据来源（复核后）** | ① `qbot_rpg/core/battle.py:333-343`（`_LEGACY_AIR_STATUS_IDS` + `@deprecated 批71 · A1`：本常量已降级为"无任何包声明时的 legacy 兜底"，权威来源 = 包 `statuses.json` 的 `"stance": "air"`；"待所有包完成声明后删除（71-A2）"）✅<br>② `qbot_rpg/core/battle.py:346-358`（`_declared_air_stance_ids`：**框架零包名**，无声明 → 返回空 frozenset）✅<br>③ `qbot_rpg/core/battle.py:624-627`（`_air_status_ids = _declared_air_stance_ids(registry) or frozenset(_LEGACY_AIR_STATUS_IDS)`；注释："`or` 不是 union：一旦有声明就完全以声明为准，避免 legacy 泄漏进新包"）✅<br>④ `qbot_rpg/commands/basic_commands.py:1929-1931`（`_LEGACY_COUNTER_MARKS = frozenset({"sword_flow"})` + `@deprecated` 同族收口）✅<br>⑤ `qbot_rpg/commands/basic_commands.py:1934-1948`（`_combo_counter_mark_ids`：包声明 `role == "combo_counter"`；无声明 → 回落 legacy，fail-safe）✅<br>⑥ `CHANGELOG.md:65-88`（批 71：统一改法 = 包声明驱动 + 框架读取 + legacy 兜底；**未完成 71-A2 明确挂起**——"框架单测无 registry 走 legacy 路径，且云海包在仓外无法确认全声明，按方案保留兜底"）——盘点写的 `:17-19`/`:25-28`/`:32-34`/`:39-40` 是**旧行号**，批 72/73 记录前插后已整体后移 ✅ |
| **置信度** | **高** |
| **【稳定契约】【勿动】** | 是 |
| **若被误修会怎样** | 直接删兜底 → **无 registry 的框架单测路径**与**非声明旧包**行为改变（这正是 71-A2 被显式挂起的原因）；把 `or` 改成 union → legacy id **泄漏进新声明包**，行为污染。 |
| **正确改法 / 不要动** | **不要动**。要推进收口就走 71-A2 的**前置条件**：① 框架单测补 registry；② 仓外云海包确认全声明。两者都满足后才可评估删兜底，且必须零行为对拍。新包新增跃空姿态/连段印记**只需在包内声明，不要再改框架表**（`battle.py:340-341`、`basic_commands.py:1929`）。 |

### ★ 样例④ `mitigation` 阶段独立 —— **置信度：高**

| 项 | 内容 |
|---|---|
| **现象** | 承伤/易伤轴（`damage_taken_pct`）与减伤（`mitigation`）看起来是同一件事，疑似"两条减伤路径重复、该合并"。 |
| **真实设计意图** | 管线阶段 ① `mitigation` **只做减伤/减免**，位于"减伤之后、护盾之前"；承伤双向轴（含易伤）另有唯一收口 `battle._damage_taken_mult`。明写"**不得**动 effects 的 mitigation 阶段（混入易伤会与护盾/保底伤害交织）"。 |
| **判据来源（复核后）** | ① `qbot_rpg/core/effects.py:129-138`（`DEFAULT_PIPELINE_ORDER`：`mitigation` ① → `shield` ② → `reflect` ③ → `absorb` ④ → `fatal_immune` ⑤ → `guts` ⑥ → `apply_damage` ⑦ → `death_check` ⑧）✅<br>② `qbot_rpg/core/effects.py:1157-1184`（`_stage_mitigation`：只读 `defense.mitigation` 的 `value/100`，并在此取"最终伤害保底 `min_damage`"；docstring 明写"本阶段是「减伤之后、护盾之前」的天然落点"）✅<br>③ `qbot_rpg/data/gear_stats.py:253-265`（`damage_taken_pct` 轴 spec，`consumer_note` 明写"唯一收口 = `_status_damage_mult`…**不得**动 effects 的 mitigation 阶段（那里只做减伤、混入易伤会与护盾/保底伤害交织）"）✅<br>④ `qbot_rpg/data/gear_stats.py:88-89`（批 22 · A3：`immune_dmg` "作用于防御/格挡/乱数之后的 raw，**与管线 mitigation 阶段叠乘（互不替代）**"）✅<br>⑤ `qbot_rpg/core/battle.py:4229-4252`（`_damage_taken_mult`：承伤乘区唯一求值处，三路来源一处求值）✅<br>⑥ `CHANGELOG.md:325-330`（批 52：`damage_taken_pct` 收敛为"承伤乘区唯一求值处"；"`effects` 的 `mitigation` 阶段按批 50 `consumer_note` 不动"，详见决策记录 §十八.2）——盘点写的 `:277-282` 是旧行号 ✅ |
| **置信度** | **高** |
| **【稳定契约】【勿动】** | 是 |
| **若被误修会怎样** | 把易伤并进 `mitigation` → 与护盾/保底伤害（`min_damage`）交织、结算顺序改变、多个既有测试与红线对拍崩；把两阶段合并 → 阶段顺序契约 `DEFAULT_PIPELINE_ORDER` 破坏。 |
| **正确改法 / 不要动** | **不要动**。新增"承伤侧"效果一律走 `damage_taken_pct` 轴（含 `immune_dmg` 负半轴别名）；新增"减免类"防御数值走 `defense.mitigation`。两者**叠乘、互不替代**。 |

---

## 3.2 A 组：文档铁律（A1–A11）

> 判据类型 = 定稿 / 用户拍板 / 验收铁律。**点开 `file:line` 自己能读到原句**才算复核通过。
> 本节 11 条**全部复核通过**；其中 A5、A7、A8 的行号/路径有漂移，已按复核值更新（见 §6）。

| 编号 · 现象（为什么形似 bug） | 真实设计意图 | 判据来源 `file:line`（本章复核） | 置信度 | 误修会怎样 / 正确改法 |
|---|---|---|---|---|
| **A1 锻造 100% 确定性 / 失败随机隔离**<br>现象：无失败分支，素材够就成 | 失败/随机归炼金、强化；锻造无随机源 | `docs/m9_启动包.md:75`、`:95`；`docs/规划/规划_路2c2_锻造.md:142`、`:147`；`docs/细化/细化_2c2b_锻造流程契约.md:14`、`:250` | **高** | 见 §3.1 样例①。**不要动** |
| **A2 锻造 = 零会话原子（不用框架 3.18）**<br>现象：`/锻造` 一条指令即时出结果、不建确认窗，像"少了会话/确认步骤" | 明确不使用会话状态机；原子无中间态，防半成品/回滚 | `docs/细化/细化_2c2b_锻造流程契约.md:13`（"锻造 = 零会话原子（明确不使用框架 3.18）"）、`:247`（TC-01 断言"不建立任何会话/确认上下文"）；`docs/审查/覆盖审计_F_生活生产.md:64`（G-03）；`docs/m9_启动包.md:95` | **高** | 补会话会破坏"原子/零副作用"与幂等断言，引入中断恢复复杂度。**不要动**；确有交互需求请另起一条指令 |
| **A3 天气确定性抽签（seed = sha256(池键排序 + tick)）**<br>现象：天气"随机"却同 tick 全世界同值、重启不重抽、序列可预测，像"伪随机/种子写死" | 懒计算刚需：不存历史、不跑定时器，任何时刻可公式重算；v1 **刻意不做真随机**（预留路径） | `docs/审查参考/时间天气系统设计定稿.md:58`（`seed = sha256(生效池键列表(排序后) + str(weather_tick))`）、`:84`（"抽签**确定性**：seed 绑定…重启不重抽——懒计算刚需"）、`:425`（风险表"v1 不做真随机…预留路径"）；`docs/规划/规划_路2a_地图副本.md:24`（铁律"天气抽签必须确定性"）、`:260`（M37 实现要点） | **高** | 换真随机/随机种子 → 跨群/跨进程/重启不一致，懒计算与 M43 回归探针失效。**不要动**；要真随机需同时改存档口径（定稿 `:425` 已写预留路径） |
| **A4 零定时器 / 懒计算**<br>现象：天气/周期不跑 scheduler，像"时间系统没驱动" | 每指令前 `check_changes` 比较缓存懒推进；周期值由公式重算 | `docs/审查参考/时间天气系统设计定稿.md:61`（"不存历史、不跑定时器"）、`:62`（变化检测钩子）、`:63`（离线跨越多周期只播最新）；`docs/规划/规划_路2a_地图副本.md:24`（"铁律：周期值禁止定时器驱动"） | **高** | 加定时器 → 多群/离线/重启状态分叉，违反"零 apscheduler"工程铁律。**不要动** |
| **A5 合成（第一层）产物恒标准档 / 无随机**<br>现象：合成产物品质固定、无特性、不参与品质判定，像"品质系统没接上" | 三层漏斗的产出边界铁律：合成只产标准版，品质/特性归炼金 | `docs/规划/规划_路2c4c1_品质与刻度.md:25`（"合成（第 1 层）产物恒为标准档（品质固定、无随机、无特性），不参与品质判定与系数浮动"）、`:26`（验收"合成产物恒标准档且无随机分支"）；`docs/细化/细化_2c4a_炼金三层漏斗.md:19`（边界铁律行："合成只产标准版…`synth_allowed` 控制配方可否被合成"）<br>⚠️ **盘点写的 `docs/细化/细化_2c4c1_品质与刻度.md` 不存在**，正确路径是 `docs/规划/`（见 §6） | **高** | 让合成掷品质 → 破坏 `synth_allowed` 边界与三层漏斗经济。**不要动** |
| **A6 标准珠 = 固定 `base_effects`（无随机特性）**<br>现象：珠子属性固定，像"没做随机附魔" | 保底通道永可用；随机性隔离在炼金品质/特性 | `docs/审查参考/炼金系统设计定稿.md:117`（"**标准珠带固定基础效果**（base_effects，无随机特性）"）；`docs/规划/规划_路2c4a1_三层漏斗.md:19`（"产出：标准版成品；标准珠=固定 base_effects（无随机特性）…保底通道永可用"） | **高** | 加随机 → 保底通道失效，经济与"无随机差分"验收崩。**不要动** |
| **A7 技能库"三铁律"：漏配 = 合理默认 / 不拦数值**<br>现象：校验器只查结构/引用/死配置，不封顶 `power`，像"数值校验缺失" | 字段最少、扩展字段默认兜底；引擎不做数值预警，把平衡权交给作者 | `docs/细化/细化_6a_技能库契约.md:24`（三铁律对齐："不做数值预警——校验器只查结构/引用/死配置，power 999 是作者自由"）；`docs/审查/幻觉审查_6a.md:24`（该行"三铁律…逐字吻合"；盘点写 `:23` 是表头分隔行，漂移 1 行）；`docs/审查/覆盖审计_B_战斗核心.md:70`（F-01 同构双库哲学 + 三铁律） | **高** | 给 `power` 加硬上限 → 拦死合法作者配置；把"漏配"当错误红拦 → 大量合法内容包加载失败。**不要动**；要拦数值请做成**黄提示**而非红拦 |
| **A8 未知字段默认放行（field_meta §2.3 兜底）**<br>现象：内容包写错/多写字段大多只黄提示甚至放行，像"校验器太松" | 红拦清单**封闭**、黄提示**开放**；枚举尽量宽松避免误阻断合法包 | `qbot_rpg/content/field_meta.py:23-24`（"本表一律不设 required（避免误拦 M0 旧包）；联合形态字段…不注册、走 §2.3 默认放行"）；`qbot_rpg/content/validator.py:5`（§2.3"默认放行兜底"；盘点写 `:6` 漂移 1 行）、`:675`（"未登记模块：默认放行（§2.3 兜底）"）；`docs/m13_6a摸底.md:146`（V-11 对照："未知字段默认放行（field_meta.py:24 §2.3 铁律）——机制反着"）、`:221`（"V-11 与现有铁律方向相反"） | **高** | 收紧为"未登记字段红拦" → 既有内容包（含 `charge_*` 前缀、`condition` obj 等未登记键）整包被拒，方向与铁律相反。**不要动框架的放行策略**；要给自己包加约束用 `settings.schema_ext`（`validator.py:389-524`） |
| **A9 签到碎片化铁律：断签不清零 / 月度累计不要求连续**<br>现象：断签后月度累计仍在、连签奖励仍可能给到，像"断签惩罚没生效" | 断签不挫败，月底冲刺钩子；补签为可选模块默认关；凌晨不骚扰（重置 05:00） | `docs/审查参考/签到系统设计定稿.md:15`（"碎片化铁律：断签不挫败——月度累计不要求连续…"）、`:57`（月度累计行）、`:103`（quest_active 对齐"月度累计不因断签清零"）、`:205`（风险对策） | **高** | 改成断签清零 → 违背用户铁律与签到经济设计。**不要动** |
| **A10 商店"不配 `refresh` = 永不刷新"（用户拍板⑥）**<br>现象：不写刷新配置就永不下架/库存不回，像"默认值忘了给" | 明确拍板：缺省即永不刷新（旧口径"默认 daily 05:00"已被收敛为 `none`） | `记录.md:1522`（用户 8 项拍板：⑤库存+个人限购并存、⑥商店不配 refresh=永不刷新）；`qbot_rpg/content/shop_models.py:6-7`（"refresh 四模式…**不配置 = 永不刷新（用户裁决⑥）**"）；`docs/细化/细化_2b3_商店引擎契约.md:393`（P1-4："默认 refresh = 不配置永不刷新（用户拍板）：1.2#9/1.3 默认值改 none"）<br>⚠️ 盘点写的 `docs/细化/细化_M6_三引擎与基础指令.md:69` 实为**背包双上限**条目（B-4），非本项依据（见 §6） | **中**（有拍板，但代码侧无独立"勿修"注释，属"已成文裁决"；建议维护者引用时带上 `shop_models.py:6-7`） | 改默认刷新 → 商店库存/限购周期被意外重置，破坏经济与既有测试。**不要动**；要周期刷新请在包内显式写 `refresh` |
| **A11 指令分隔符三铁律（数量=`*`、列表=`,`、位置参数≤2、键值=`=`）**<br>现象：`/强化` 禁 `*`、序号不带 `*`、`A+B` 只是文档记法，像"同一种数量语法这里不认" | 参数格式唯一口径，防解析歧义；命名禁保留字符 | `docs/审查参考/指令分隔符统一规范.md:27-51`（铁律 1/2）、`:55-61`（铁律 3 + 命名铁律；"解析器按保留字符检查黄色提示（不拦截，只建议不限制）"）；`docs/审查/覆盖审计_A_框架基础.md:126-129`（F-02/F-03/F-04/F-05）；`docs/细化/细化_2c4c_珠与合成指令.md:79`（CMB-07："A+B 为**文档记法**，实现层落为两个空格位置参数；物品名禁用 `+`"） | **高** | 放开 `/强化 装备*2` 或允许物品名含 `+` → 解析歧义/串参。**不要动**；新增指令请照三条铁律设计参数面 |

---

## 3.3 B 组：合理并存 / 双轨（B1–B12 + 审计3 §6 并入 R1–R13）

> 本组 = 上游 §7 B 组（仓库内可考的"刻意并存/双轨"裁决）+ **审计3 §6「合理并存清单」**。
> ⚠️ **审计3 §6 原文不在仓库**（`docs/深度打造_决策记录.md:1568` 只是转引）。本节按用户指示，**从仓外 `/root/deliverables/审计3_勿增实体_重复机制.md` §6 摘录要点并入**，并**逐条回仓库复核判据 `file:line`**（审计原文行号有漂移处已标注）。

### B 组（上游 §7 B 组，逐条复核）

| 编号 · 现象（为什么形似 bug） | 真实设计意图 | 判据来源 `file:line`（本章复核） | 置信度 | 误修会怎样 / 正确改法 |
|---|---|---|---|---|
| **B1 商品「库存 + 个人限购」同条目并存（用户裁决⑤）**<br>现象：同一条目既扣全局库存又扣个人限购，`scope` 还只描述默认侧，像"互斥字段没互斥" | 裁决⑤：两制**并存**、各自独立读取、互不排他；`scope` 只管默认侧 | `qbot_rpg/content/shop_models.py:5`（docstring"库存+个人限购同条目并存（用户裁决⑤）"）、`:10`（"scope 扩展并存（P1-2）"）、`:206-209`（"与 stock 可**同条目并存**（L450/L465 型无损表达）；scope 只管默认侧"）、`:294-312`（`per_player` / `effective_scope` 访问器）；`docs/细化/细化_2b3_商店引擎契约.md:392`（P1-2"scope 扩展并存，用户拍板选并存"）；`记录.md:1522`（用户拍板⑤）；`tests/unit/test_shop_models.py:305-317`、`:357-372`（零红拦 + 仅黄提示） | **高** | 把 `scope` 恢复为二选一 → L450/L465 型配置无法无损表达，旧商店行为静默改变。**不要动** |
| **B2 签到多表并存、一次 `/签到` 全部结算**<br>现象：一份文件里 loop/monthly/activity 三表同时生效并各自独立连签，像"多份配置冲突没合并" | 奖励日历 = 多表并存；一次结算、单条汇总防刷屏；跨表互不写对方 state | `docs/审查参考/签到系统设计定稿.md:75`（§3.4 多表并存）、`:216`（验收"多表并存：loop/monthly/activity 同时生效，一次 /签到 全部结算，各自独立连签"）；`qbot_rpg/content/checkin_models.py:4`（"多表（loop/monthly/activity）并存一次结算"）、`:193-196`（奖励条目"**可并存**"）；`tests/unit/test_checkin.py:158`（① 多表并存一次结算）、`:161-173`（三表各自结算 + 存档按表 ID 键控）<br>⚠️ 盘点写的 `tests/unit/test_checkin.py:53` 是 `SETTINGS` 常量行，非本项依据（见 §6） | **高** | 只取一张表/合并表 → 奖励与连签计数错乱。**不要动** |
| **B3 dual 异框架状态"并存相加"（不是高覆盖低）**<br>现象：两个降攻/减益状态同时生效且数值相加，像"状态覆盖逻辑写错" | 刻意机制：`single` 同类高覆盖低、`dual` 异框架并存相加、`stack` 累积 | `qbot_rpg/core/effects.py:508-514`（`apply_status` docstring：S1–S7 叠加，含"dual 并存相加 2 槽"）、`:687-689`（dual 分支"不同框架并存相加；dual 2 槽约束"）；`docs/审查参考/效果系统设计定稿.md:228`（"dual：不同框架并存相加（两个降攻技叠出压制流）"）；`tests/unit/test_effects_gaps.py:117-136`（`test_c2_dual_coexist_and_add`：异框架两实例并存、`sum(vals)==24`、同类 dual 2 槽封顶） | **高** | 改成高覆盖 → 压制流/双降攻 build 失效，C-2 语义与测试崩。**不要动** |
| **B4 同回合互杀：双方死亡标记同轮并存 → 平局**<br>现象：双方都死却判平局（可配玩家败），像"死亡判定漏了先后" | 刻意规则：死亡标记同轮并存，判定基准 `order`/`hp_ratio` 可配；属设计内 | `docs/细化/细化_1g1a_战斗状态集.md:95`（"同回合互杀（双方死亡标记同轮并存）→ 结束结果=平局（可配 `player_loss`=玩家败）；判定基准二选一：`order`「先判定后手」/ `hp_ratio`「剩余 HP 比」，默认 order"）；`qbot_rpg/core/battle.py:1214-1220`（"互杀判定（双方死亡标记同轮并存，1g1b A2 / L59-63）"、`mutual_kill_basis` 默认 `order`）；`docs/审查/幻觉审查_1g3.md:57`（`units[].dead_mark` 引对："双方死亡标记同轮并存"） | **高** | 改成"先判先手胜" → PVP/自爆流结果改变，既有断言崩。**不要动**；基准已可配 |
| **B5 门槛判定两口径并存（`tier_index_for_level` vs `level` 直比）**<br>现象：两条路径对"职业等级门槛"算法不同，像"重复实现漂移" | 默认配置下两口径**等价**，属如实登记的并存（**未收敛**） | `记录.md:1159`（P2 登记："门槛判定两口径并存（`tier_index_for_level` vs `level` 直比，默认配置等价）"）；`审查_M8实现_批次E2_jspace.md:25`（P2 汇总同名项）、`:103`（P2-7 详述：`cmd_register` L1952-1953 vs 其余 10 处直比；`tier_index_for_level = min(level, len(tier_names)-1)`）<br>⚠️ **正确路径在仓库根 `审查_M8实现_批次E2_jspace.md`**，盘点写的 `docs/审查报告/…` 不存在（见 §6） | **中** | 贸然统一其中一条 → 非默认配置下职业门槛判定变化（`tier_names` 少于 5 档时 register 会钳制）。**先查内容包实际配置**再动 |
| **B6 背包"数量上限截断"与"格数上限"双口径并存**<br>现象：两个"上限"都叫上限、互不替代，像"同名冲突" | 裁决：数量截断作用于单次 `add` 的 `count`；格数上限作用于总行数，两条独立校验 | `docs/细化/细化_M6_三引擎与基础指令.md:69`（B-4："4b INV-R04（单次入包数量上限 99 截断+提示）与 INV-R05（背包格数 capacity 默认不限、可配）**两口径并存**…两条独立校验、互不替代"） | **高** | 合并成一条 → 大额入包或满包行为改变（吞物/误拒）。**不要动** |
| **B7 分解 × 全物入料 双回收出口并存**<br>现象：旧装备既能 `/分解` 又能当素材，两条回收链路，像"回收入口重复" | 刻意：两条链路并存、互不覆盖（专家解锁全物入料） | `docs/细化/细化_2c4c_珠与合成指令.md:220`（EDGE-05："旧成品/旧装备可走 /分解（材料+宝石，DEC）或全物入料当素材（专家解锁，L218）——两条回收链路并存，互不覆盖"） | **高** | 砍掉其一 → 回收经济闭环断裂，旧成品无处去。**不要动** |
| **B8 品质档名两套并存（优秀/稀有 vs 精良/史诗）**<br>现象：同一档位两套中文名并存，像"命名没统一/写错" | 定稿内部两套名并存，细化选边权威落点 §10.6（精良/史诗），旧名保留识别 | `审查_M8设计_批次1A_jspace.md:62`（P1-4："定稿内部两套中档名并存（优秀/稀有 vs 精良/史诗），细化选边 §10.6（权威落点）语义正确…修复建议：不裁决（上报定稿内部档名冲突）"）；`docs/m8_shared_contract.md:454`（拍板②："L150 旧名「优秀/稀有」**废弃**"） | **中** | 直接删旧名 → 旧包加载/迁移黄提示路径断裂；**须先确认旧名是否仍有内容包在用**。当前口径：新名 common/uncommon/rare/legendary 为准，旧名仅识别 |
| **B9 分解回收率 40%→65% 多处并存**<br>现象：同一回收率在三处写 40%/0.65/40-65%，像"复制没同步" | 定稿**自身多口径并存**，细化按 `settings` 上限 65% 取值；属定稿内部张力，非实现 bug | `docs/审查/幻觉审查_2c4a.md:36`（"原句…定稿内部 L168 写"回收率 40%→60%"、L418 配置到 0.65、L472 写"40-65%"——三处口径本身并存；细化…忠实分处转述，**未自造数值**"）；`docs/审查/幻觉审查_2c2c.md:69`（DEAD-03："L168"40%→60%"与 L418 王档 0.65 并存，取 settings 上限 65% 有据（定稿自身两处并存，非细化问题）"） | **中** | 按其中一处"修正数值" → 经济基准偏移、红线对拍失败。**先做数值裁决，不要在代码里单方面改** |
| **B10 套装技能"多技能并存"（数组）**<br>现象：定稿只定义单技能三档结构，实现支持多技能数组，像"超出定稿的私扩" | schema 自然延伸（`skills` 是数组），但**未显式标"本文扩展"**（审查已提示补注） | `docs/审查/幻觉审查_2c2d.md:80`（P2-5："定稿 L166/L315-319 仅定义「套装技能」单技能三档结构；多技能并存为 schema 自然延伸（SET-05 skills 是数组），但 ACT-04 引用列未显式标注「多技能为本文扩展」"） | **低（待查）** | 若判为越权而砍数组 → 多技能套装配置失效。**待查**：需确认是否应登记为"文档扩展"（只需补注，不必改代码） |
| **B11 怪物 `battle_start` 特例两轨并存**<br>现象：战斗开始事件存在特例保留路径，像"没被统一收编" | 已登记风险：特例保留（两轨并存），`on_tick` 特例二期收编 | `记录.md:843`（风险登记："怪物 `battle_start` 特例保留（两轨并存）；`on_tick` 特例二期收编；反伤递归深度限制"） | **中** | 立即收编特例 → 触发时点/事件顺序变化；**须先做兼容对拍** |
| **B12 炼金能量开关双源并存（`proficiency` vs `settings`）**<br>现象：两个地方都能配开关且优先级未定，像"双开关打架" | 契约要求保留双源、但**需声明优先级**（建议 `settings` 为准、`proficiency` 兜底）——属待收口并存 | `docs/审查/M8契约审查_20260829/审查_M8契约_路C_jspace.md:84`（P2-4："能量开关双源：`proficiency.json energy.enabled` 与 `settings alchemy.energy_enabled` 并存，**优先级/冲突口径未定**；修复建议：契约声明优先级（建议 settings 为准，proficiency 作默认兜底）"） | **中（待查：最终优先级）** | 未定优先级就"修"其一 → 两处配置行为互相覆盖，作者预期落空。**待查**：需 ADR 裁决优先级 |

### 审计3 §6「合理并存清单」并入（R1–R13，**别乱删**）

> 来源：仓外 `/root/deliverables/审计3_勿增实体_重复机制.md` §6（该审计自述"以下看着像重复、实际是有意设计，有文档/口径钉死"）。
> 下表 = 审计原文 13 条 + **本章回仓库复核后的判据行号**。审计原文行号有漂移处在"复核注"列标出。

| # | 看似重复 | 实际关系 | 判据 `file:line`（本章复核） | 置信度 |
|---|---|---|---|---|
| **R1** | 品质四档（`core/quality.py`）vs 打造品质等级 1~10（`core/deep_craft.py`） | **正交维度**，不是两套口径 | `docs/深度打造_决策记录.md:14`（H2："新增品质等级 1~10 × 颜色 6 档 × 图纸档；**不动**既有唯一品质注册表 common/uncommon/rare/legendary"）、`:15`（H3 只说替换 `max_by_rarity`） | **高** |
| **R2** | 合成公用层 `core/synthesis.py` vs 深度层 `core/deep_craft.py` | **公用层 + 深度层**分层 | `qbot_rpg/core/synthesis.py:1`（"第 1 层跨职业合成引擎"）、`qbot_rpg/core/deep_craft.py:1`（"深度打造引擎（打造家族的「深度层」）"）；`docs/批39_合成公用层接口.md`（存在） | **高** |
| **R3** | 强化「强化」`commands/enhance_commands.py` vs「淬炼」`core/temper.py` | **两套并存但状态分账**（`enhance_level` vs `temper_alloc`），文件明确互不读写 | `qbot_rpg/core/temper.py:21-22`（职责 6："**分账**：`enhance_level`（强化）与 `temper_alloc`（淬炼）**分开存**——本引擎不读写 `enhance_level`，既有强化链路不受影响"）<br>复核注：审计原文引 `temper.py:6-7,30-31`，当前 HEAD 分账声明在 `:21-22` | **高** |
| **R4** | `forge.essence_rate` 与 `enhance.temper.cost_per_point` | **分键、语义相反、不可合键**（材料/精粹方向相反；返还必须 < 消耗否则套利） | `docs/深度打造_决策记录.md:1317`（C-4/C-5 分解回收：实例级路径"材料（`decompose_rate`）+ 精粹（`essence_rate`）"）；`qbot_rpg/content/forge_settings.py:100-103`（`essence_rate` 段登记）、`:173-179`（`essence_rate` 字段 help）；`qbot_rpg/data/temper_stats.py:1-8`（键空间与默认值唯一源）、`:34`（"全部键可被内容包 `enhance.json → temper` / `settings.forge → essence_rate` 覆盖"） | **高** |
| **R5** | `material_recovery` 与 `_recover_materials`（审计3 F4） | 虽是同公式两写，但**新旧分解路径并存**是有理由的（实例级分解解决 uid 实例无法按 item_id 分解） | `qbot_rpg/core/decompose.py:1-12`（"实例级分解引擎…纯函数"）；`qbot_rpg/commands/alchemy_commands.py:1846-1855`（"实例级路径优先：仅当精粹启用时尝试（未启用 → 整段跳过，既有 `item_id` 路径…）"）<br>审计处置建议：**只做"同改时顺手收敛"，不要单独删任一方** | **高** |
| **R6** | `core/event_bus.py` vs `core/event_dispatcher.py` | **同名词不同事**：前者 = 事件计数/日志（条件引擎读），后者 = 效果触发时点分派 | `qbot_rpg/core/event_bus.py:1`（"事件写入引擎"）、`qbot_rpg/core/event_dispatcher.py:1`（"通用效果事件分派器"） | **高** |
| **R7** | `core/energy_bar.py` vs `core/resource_axis.py` / `resource_lifecycle.py` | 不同系统：炼金调合能量条 vs 战斗资源轴（增减/时点结清） | `qbot_rpg/core/energy_bar.py:1`（"调合能量条引擎…懒计算补格/上限随等级/消耗/安全区 2 倍速/默认关直通/存档同步"）；`qbot_rpg/core/resource_axis.py:1`（"6c energy_gain/energy_cost 运行时"）；`qbot_rpg/core/resource_lifecycle.py:1` | **高** |
| **R8** | `core/combo.py` vs `core/combo_table.py` | 同名词不同事：连段状态机（段数/派生）vs 元素多重集组合技（组合表匹配）；后者 `gate_conventional` 还调用前者 `combo.should_reject`，是**依赖不是重复** | `qbot_rpg/core/combo.py:1`（"连段引擎"）、`qbot_rpg/core/combo_table.py:1`（"6c combo_table 组合表达 schema + 触发判定"）、`:16-19` | **高** |
| **R9** | 多处「冷却」：`cooldown_pct` 轴 / 道具 `cooldown_of` / 形态 `cooldown_remaining` / 珠触发上限 | 不同对象、不同计数层，非同一机制 | `qbot_rpg/core/battle.py:3426-3441`（X27 `cooldown_pct` 消费点：技能冷却管线）、`qbot_rpg/core/alchemy_battle.py:202`（道具 `cooldown_of`）、`qbot_rpg/core/transform.py:25`/`:37`/`:101`（形态 `cooldown_remaining`）、`qbot_rpg/core/jewel.py:283`（`trigger_limit`：珠每场触发上限）<br>复核注：审计原文引 `battle.py:3404`，当前 HEAD 该轴消费点在 `:3426-3441` | **高** |
| **R10** | 别名「三个换算点」 | 唯一源 + 按层互斥换算（占位 / pct / COMBAT 分流），是**防双计**的分层，不是三套机制 | `qbot_rpg/data/gear_stats.py:754-783`（占位键 `route_legacy_aliases_into_flat`）、`:786-837`（`combatant_updates` 的 pct 层归并）、`:978-997`（`effect_values_of` 度量用途）；`route_bonus_into` 显式跳过占位键 `:743` | **高** |
| **R11** | `data/runes.py` vs `core/runes.py` | **data = 刻度常量 + 基础解析 / core = 差异表解析**，且 content 校验与 core 同源引用 | `qbot_rpg/data/runes.py:1`（"符文基础刻度与纯解析"）、`qbot_rpg/core/runes.py:1`（"符文定义解析层"）；`scripts/check_architecture.py:42`（`content` 允许依赖 `data`） | **高** |
| **R12** | 三条词条计划包装（`plan_affixes`/`plan_special_affixes`/`plan_effect_refs`） | 同一底层（`_pick_weighted` + `resolve_available_entries`），按载荷键分流；各自只做取值语义 | `qbot_rpg/core/deep_craft.py:621`（`_pick_weighted`）、`:696`（`plan_affixes`）；`qbot_rpg/core/enhance_affix.py:182`（`plan_special_affixes`）、`:213`（`rank_affinities`）；`qbot_rpg/core/alchemy_affinity.py:146`（`plan_effect_refs`）；`docs/深度打造_决策记录.md:1413`（池唯一入口） | **高** |
| **R13** | `forge.py`（`/锻造`）vs deep_craft（`/精造`） | **打造家族两成员**：M9 锻造 = 确定性派生树（无随机）；深打造 = 蓝图 + 随机（原案随机线）；H1 明示"不复用 forge 的『无随机』段" | `docs/深度打造_决策记录.md:13`（H1）、`:18`（H6 新指令名）、`:96-98`（`/精造` 与既有名零冲突结论）；`qbot_rpg/commands/deep_craft_commands.py:64`（`DEEP_CRAFT_CMD = "精造"`）；`qbot_rpg/commands/forge_commands.py:2242`（别名 `("打造", "铸造")`）<br>复核注：审计原文引 `forge_commands.py:2250-2251`，当前 HEAD 该处是另一条 `router.register`；别名在 `:2242` | **高** |

---

## 3.4 C 组：代码注释直述（C1–C27）

> 判据类型 = **代码注释**里明写"有意 / 刻意 / 为兼容 / 保持 / 不回退 / 勿修"。
> 这是最容易被后人当 bug 修的一类——因为**行为本身看起来就不对**，只有注释在解释"为什么不对才是对的"。
> **全部 27 条复核通过**；C7/C8/C19/C21/C24 的行号有漂移，已按复核值更新（见 §6）。

| 编号 · 现象（为什么形似 bug） | 真实设计意图 | 判据来源 `file:line`（本章复核） | 置信度 | 误修会怎样 / 正确改法 |
|---|---|---|---|---|
| **C1 legacy 兜底 / 声明+兜底双轨（`or` 不是 union）**<br>现象：框架硬编码包专属 id，像残留包名 | 包声明驱动 + 无声明回落 legacy，保逐位一致；有声明则以声明为准，防 legacy 泄漏 | `qbot_rpg/core/battle.py:333-343`、`:346-358`、`:624-627` | **高** | 见 §3.1 样例③。**不要动** |
| **C2 连段计数印记 legacy 兜底（`sword_flow`）**<br>现象：框架里写死一个具体印记 id | 权威 = 包声明 `marks[].role=="combo_counter"`；无声明回落 `_LEGACY_COUNTER_MARKS`（fail-safe） | `qbot_rpg/commands/basic_commands.py:1929-1931`（legacy 集合 + `@deprecated`）、`:1934-1948`（`_combo_counter_mark_ids` 包声明优先、无声明回落） | **高** | 同 C1。**不要动** |
| **C3 旧键别名归并：唯一换算入口、只一次、不双计**<br>现象：同一旧键既有自身链路又在聚合入口被换算，像"两处消费" | `route_legacy_aliases_into_flat` 是占位旧键 → 特效轴的**唯一**兼容换算；`route_bonus_into` 显式跳过占位键防双计 | `qbot_rpg/data/gear_stats.py:26-30`、`:56-62`、`:584-589`、`:720`+`:743`（跳过占位键）、`:754-783`；`qbot_rpg/core/equipment.py:1006-1008`；`CHANGELOG.md:296-301`（批 53 激活并归并） | **高** | 见 §3.1 样例②。**不要动** |
| **C4 `mitigation` 阶段独立，不得混入易伤**<br>现象：减伤与承伤易伤像重复逻辑 | 阶段① 只做减伤；承伤双向轴另有唯一收口；明写"不得动 mitigation 阶段" | `qbot_rpg/core/effects.py:129-138`、`:1157-1184`；`qbot_rpg/data/gear_stats.py:253-265`（`consumer_note` 明写"不得动…mitigation 阶段"）、`:88-89` | **高** | 见 §3.1 样例④。**不要动** |
| **C5 技能链成环 = 有意的循环连招，提示不拦截**<br>现象：校验器发现环却只给提示，像"环检测没硬拦" | 环形链是合法的循环连招（X-04），**刻意只提示** | `qbot_rpg/content/validator.py:1657-1660`（注释"链成环提示（细化派生：环形链=有意的循环连招，X-04；提示不拦截）"，`_note` 而非 `_err`）；`qbot_rpg/core/monster_chains.py:57-59`（规则表同口径）<br>复核注：盘点引 `validator.py:1654`，当前 HEAD 在 `:1657` | **高** | 改成红拦 → 合法循环连招内容包被拒载。**不要动** |
| **C6 地图双向边允许一侧缺失 / "刻意不对称"**<br>现象：`bidirectional` 声明了却允许 A→B 有、B→A 无，像"校验漏了对称性" | 只对声明 bidirectional 的边查对侧；缺失/非双向 → 黄提示，**允许作者刻意不对称** | `qbot_rpg/content/map_models.py:694-701`（`_check_bidirectional_symmetry` docstring："允许作者刻意不对称"）；`qbot_rpg/content/map_graph.py:231-233`（`bidirectional_consistent` 同口径，返回 `List[Warning]`） | **高** | 改成红拦 → 单向下行/密道等地形无法配置。**不要动** |
| **C7 派生行有意豁免折行（遗留 #37，用户拍板）**<br>现象：派生行整行全量显示、不折行，像"忘了走 16 行/折行门禁" | 2026-09-12 用户拍板：拆行会丢失/割裂信息，登记 `skill_info_derived` 于 `meta.prose_keys` **有意豁免** | `qbot_rpg/commands/basic_commands.py:2280-2282`（docstring："拆行/精简会丢失或割裂信息；登记 `skill_info_derived` 于表 `meta.prose_keys`（有意豁免）"）、`:2356-2362`（渲染处"整行全量显示、不折行——有意豁免"）；**权威登记** `qbot_rpg/core/templates/template_table.json:5`（`prose_keys` 段）、`:32`（`skill_info_derived` 豁免理由全文）<br>复核注：盘点引 `basic_commands.py:2289-2291`/`:2366`，当前 HEAD 漂移至 `:2280-2282`/`:2361`；且**更权威的登记在 `template_table.json:5,32`** | **高** | 纳入折行 → 技能信息被截断，违背拍板。**不要动**；新增长文本模板请登记进 `meta.prose_keys`/`prose_placeholders` |
| **C8 改名后旧名悬空、校验"如实报引用不存在"**<br>现象：改名后引用方仍指旧名，校验报错，像"改名功能没级联更新" | 明确容忍：引用方**保持旧名**、校验如实报，**不自动改数据** | `qbot_rpg/web/editor_ops.py:482-483`（`_RENAME_TOLERATE_NOTE = "改名后旧名悬空（引用方保持旧名，校验如实报「引用目标不存在」）："`） | **中** | 自动级联改名 → 可能误改跨包引用/不可控批量变更。**须走专门迁移**；当前行为是设计 |
| **C9 键名刻意避开 `settings.forge` 防语义混淆**<br>现象：明明有关联却故意换名，像"命名不统一" | 打造/合成层键名刻意避开既有 M9 锻造配置段，防两域语义混淆 | `qbot_rpg/content/field_meta.py:593`（"键名刻意避开既有 M9 锻造配置段 `settings.forge`，防语义混淆"）；`qbot_rpg/core/craft_paths.py:94-95`（`FORGE_CONFIG_KEY = "deep_craft"` + 同句注释） | **高** | 强行统一回 `settings.forge` → 两域配置互相覆盖。**不要动** |
| **C10 校验器"约束子集刻意最小"**<br>现象：校验 DSL 只支持 str/int/number/bool/list/obj + enum + required，像"能力不全" | **刻意最小子集**，降低作者理解成本与误拦风险 | `qbot_rpg/content/validator.py:394`（"约束子集**刻意最小**：`type`(str/int/number/bool/list/obj) + `enum`(可选) + `required`(可选)"） | **中** | 盲目扩展 DSL → 校验语义面扩大、旧包判定变化。**要扩展先评审**；包侧需求用 `settings.schema_ext` |
| **C11 模块目录"有意不放进可启用清单"的排除项**<br>现象：某些模块名不在可启用清单，像"清单漏登记" | 明确**排除项**（有意），不在清单内是设计 | `qbot_rpg/content/module_catalog.py:15-22`（"排除项（有意不放进「可启用清单」）：`manifest` 不是独立数据文件；`ai`/`hidden`/`env_event`/`log_card`/`editor` 是编辑器扩展视图/页表注册，没有对应独立内容数据文件"） | **中** | 补进清单 → 暴露未完成/不应启用的模块。**不要动** |
| **C12 条件引擎旧运算符/中文变量别名（`min→ge`、`max→le`、中英互译）**<br>现象：旧写法 `min/max` 语义像"取最小值"，却映射到 `>=`/`<=`，像"运算符写反" | 旧格式兼容别名 + 中英互译表；识别顺序：精确键 → 别名 → 带 `{T}` 占位 | `qbot_rpg/core/condition_engine.py:98-105`（`OP_SYMBOL_ALIASES`）、`:108`（`OP_LEGACY_ALIASES = {"min": "ge", "max": "le"}`）、`:111-123`（`normalize_op`）、`:155`（`VAR_ALIASES`）、`:212-227`（`normalize_var` 识别顺序） | **高** | 删旧别名 → 旧任务/NPC/成就条件失效；按字面"修正" `min`/`max` → 条件语义**反转**。**不要动** |
| **C13 NPC 旧策略名 legacy 归一 + 迁移提示**<br>现象：旧定稿枚举 `first_match→condition`、`weighted→random` 等，像"策略名对不上" | 归一时标 `legacy=True` 并给迁移提示，**不硬拒** | `qbot_rpg/core/npc.py:136-147`（`normalize_strategy` docstring + `LEGACY_STRATEGY_MAP`，返回 `legacy`/`migrate_hint`；"缺省/未知 → condition（DR01 默认承接定稿 first_match 默认态）。纯函数不抛错"） | **高** | 删兼容 → 旧包 NPC 策略无法加载。**不要动** |
| **C14 资源轴 `resource_custom` 兼容别名归一为 `resource`**<br>现象：同一类型两个名字，像"枚举值写错" | 契约 P-1 旧键兼容，加载归一 | `qbot_rpg/core/resource_axis.py:121`（"资源轴 type 枚举（D-01b：`resource_custom` 为兼容别名，加载归一为 `resource`）"）；`qbot_rpg/content/resource_axis_validator.py:173-175`（报错文案含"`rage`/`element_energy` 兼容旧键"）；`qbot_rpg/content/resource_axis_models.py:38`（"P-1 兼容旧键"） | **高** | 删别名 → 旧职业资源轴红拦。**不要动** |
| **C15 天气条件 `==` 为 `eq` 的兼容别名**<br>现象：同一运算符两种写法，像"op 写错" | 白名单 `eq`；`==` 为兼容别名，求值等价 | `qbot_rpg/core/weather_conditions.py:70`（"运算符白名单：`eq` / `==`（2a4c §2.1「op 用 eq」；`==` 为兼容别名，求值等价）"） | **高** | 删 `==` → 旧内容包天气条件失效。**不要动** |
| **C16 事件键 `EVENT_KEY_DEFAULTS` 缺省回退现键（向后兼容零破坏）**<br>现象：事件键有"常量→默认键"两级回退，像"硬编码没删干净" | 零配置时回退现字面量，保证旧行为零破坏；`resolve_event_key` 集中解析 | `qbot_rpg/core/event_bus.py:26-27`（docstring："`resolve_event_key` 集中解析 + `EVENT_KEY_DEFAULTS` 缺省回退现键（向后兼容零破坏）"）、`:63-66`（`EVENT_KEY_DEFAULTS` 定义 + "零配置时 `resolve_event_key` 回退至此，向后兼容零破坏"） | **高** | 删默认回退 → 未声明事件映射的旧包行为变化。**不要动** |
| **C17 `rng_state` V2 权威位 + `_rng_state` V1 旧键兜底读**<br>现象：快照里同时有 `rng_state` 和 `_rng_state`，像"字段冗余" | V2 权威位新键；V1 旧键保留兜底读，保证旧快照/旧代码可续 | `qbot_rpg/core/battle.py:5696-5700`（"`rng_state` 走顶层（V2 权威位）；`_rng_state` 为 V1 旧键，保留兜底读"；`data.get("rng_state", data.get("_rng_state"))`） | **高** | 删旧键 → 旧存档续战随机序列/兼容读断裂。**不要动** |
| **C18 `hp`/`mp`=0 合法（修复 `or 1` 致读档 0→1）**<br>现象：看到"`None` 才兜底"，像"少了 `or` 兜底" | 0 是合法值（死亡/空蓝），只有 `None` 才兜底；`or 1` 曾是 bug 已修 | `qbot_rpg/storage/repository.py:324-326`（"P2-3 修复：`hp`/`mp`=0 合法（死亡/空蓝），`or 1` 致读档 0→1；`None` 才兜底"，实现 `int(col("hp")) if col("hp") is not None else 1`） | **高** | 加回 `or 1` → 读档把 0 血/0 蓝变成 1，死亡/空蓝语义崩。**不要动**；同类"0 合法"字段一律用 `is not None` 判定 |
| **C19 同 `item_id` 多件实例并存时只算穿戴件（防词条翻倍）**<br>现象：`aggregate_bonus` 按 `item_id` 回查，曾把未穿戴行也聚合，像"聚合漏 filter" | 已按穿戴行精确区分（P1-1 修复），同 id 异词条互不污染 | `qbot_rpg/core/equipment.py:43-46`（P1-1 修复说明："每槽只取一件匹配行（`_worn_rows[0]`）…防未穿戴行词条翻倍"）、`:223`（`_first_worn_row`）、`:580-583`（`_resolve_worn_row` 优先行引用）；`审查_M6实现_批1A_三引擎_jspace.md:83`（原始问题 + 修复要求）；`tests/unit/test_equipment.py:275-277`（回归用例 `test_regress_p1_1_aggregate_takes_one_of_duplicate_id`）<br>复核注：**盘点引 `equipment.py:198-207` 是审计当时"问题所在行"（`_worn_rows` 返回全部同 id 行），不是修复落点**；当前 HEAD 修复落在 `:223`/`:580`（见 §6） | **高** | 回退成"遍历全部同 id 行" → 未穿戴词条也加成，属性翻倍。**不要动** |
| **C20 `any` 键与具名键并存时 `any` 优先（运行时防御）**<br>现象：K3 本应校验器红拦互斥，运行时却"`any` 优先、具名忽略"，像"静默吞配置" | 运行时防御降级**不抛异常**；红拦归批 11 V7（校验层），引擎不因坏配置崩 | `qbot_rpg/core/resource_axis.py:80-81`（B-3："`any` 键与具名键并存（K3 互斥本应校验器红拦）：运行时防御处理 = `any` 键优先（总量门），具名键忽略——不抛异常"）、`:587-588`（门禁函数内同口径） | **中** | 改成抛异常/取具名 → 坏包直接崩战斗；改成叠加 → 资源门禁数值错。**不要动**；要修的是校验层（V7）不是运行时 |
| **C21 渲染层"异常兜底不崩、绝不抛出"**<br>现象：多处 `except Exception: return 已装配行`，像"吞异常" | 明确铁律：渲染层任何异常 → 记日志并返回已装配行/空串，**绝不抛出**，保战斗响应可用 | `qbot_rpg/core/message_format/battle_render.py:2026`（"任何异常 → 记日志并返回已装配行（或空串），绝不抛出（渲染层不崩铁律）"）、`:72-78`、`:162-168`、`:263-269`（三处入口 docstring 同口径）；实现 `:92`/`:223`/`:308`/`:2070`/`:2146`/`:2224`（`except Exception: # pragma: no cover - 渲染层兜底不崩`） | **中** | 让异常上抛 → 单条渲染错误导致整场战斗响应丢失。**不要动**；渲染层新增分支也必须兜底 |
| **C22 素材来源确定性兜底文本"来源未知"**<br>现象：没标来源就填固定串，像"占位文案没做完" | SOUR-00 要求每条素材标来源；无标注时是**确定性兜底**，不抛不随机 | `qbot_rpg/content/forge_settings.py:35-36`（F-3："`resolve_source_text` 兜底文本 `DEFAULT_UNKNOWN_SOURCE="来源未知"`…无标注时的确定性兜底"）、`:107-108`（常量定义）；`qbot_rpg/core/forge_material.py:150`（兜底第 ③ 级："确定性 str（trimmed）。无异常"） | **中** | 改成报错/空 → 素材提示链路断；改成随机 → 破坏确定性。**不要动** |
| **C23 属性 `base`/`growth` 负数 → 黄提示、运行期按 0**<br>现象：负数被"放行"而非红拦，像"数值校验漏了" | 3b §4.2 / TC-17：负数 → 黄、运行期按 0（`allow_negative`） | `qbot_rpg/content/field_meta.py:333-335`（"3b §4.2/TC-17：base/growth 负数 → 黄提示（`allow_negative`），运行期按 0（calc 兜底）"；`FieldMeta(type="number", ..., allow_negative=True)`）；`docs/审查报告/审查_M0复查_content_field_meta_20260824.md:76`（"stats base/growth allow_negative（旧 P1-4）已修复…对齐 3b §4.2/TC-17「负数→黄、运行期按 0」"） | **中** | 改红拦 → 旧包（含故意负成长）被拒；去掉按 0 → 负白值代入放大。**不要动** |
| **C24 元数据未登记键走"兜底控件 + 显式标注"（不静默）**<br>现象：编辑器对未登记键仍渲染控件，像"元数据缺失没报错" | 原则：框架登记过按元数据、多出来的键走兜底但**显式标注**，不静默 | `qbot_rpg/web/api.py:2808-2811`（"批14 #4：元数据未登记子字段 → 兜底控件（按实际值推断）+ 显式标注（一号原则：框架登记过就按元数据渲染；数据里多出来、框架没登记的键走兜底也不静默）"；`meta_unregistered`/`meta_note`）、`:2672`（映射行同口径）、`:3071`（"值里多出的未登记键…走兜底列 + 未登记标注"）<br>复核注：盘点引 `api.py:2813-2814`，当前 HEAD 在 `:2808-2811` | **中** | 改成静默丢弃 → 作者配置被编辑器悄悄抹掉。**不要动** |
| **C25 条件/组合求值"未知键 → 安全失败"（不静默恒真）**<br>现象：未知键直接判不满足，像"求值太保守" | P0-1 修复：原实现静默忽略未知键导致**恒 True**、派生无条件触发（反安全），改为安全失败 | `qbot_rpg/core/combo.py:602-603`（"未知键 → 安全失败（1c3 TC-13；P0-1 修复：原静默忽略恒 True）"）、`:443`（"**不猜测**：非法元素静默跳过（求值端安全失败）"）、`:530-531`（"未知键 → 条件不满足…原实现静默忽略未知键恒 True，含印记条件的派生无条件触发——反安全"） | **高** | 回退为静默忽略 → 条件失效被当成立，派生技无条件触发。**不要动** |
| **C26 调合终端结算幂等：hook 缺失不静默跳过扣料**<br>现象：hook 缺失返回 `False`，像"扣料失败没兜底" | 原子防双扣：引擎**不静默跳过扣料**，缺 hook = 不结算（宁可不做不可半做） | `qbot_rpg/core/alchemy_settle.py:336-341`（`_consume_materials` docstring："`remove_item` hook 缺失 → `False`（引擎不静默跳过扣料——原子防双扣）"；实现 `if not callable(remove_item): return False`） | **高** | 加"跳过扣料继续结算" → 白送产物、经济漏洞。**不要动** |
| **C27 退出结算幂等键：同 `message_id`+`group`+`qid` 的不同结算类型"先到者胜"**<br>现象：不同 `kind` 却视为已结算、不双结算，像"去重键少了一维" | 明写 schema 约束：`command`/`kind` **不参与去重**、仅落审计列；同消息视为已结算防双扣 | `qbot_rpg/world/battle_boundary.py:833-848`（幂等键构成 + "注（schema 约束）：`idempotency_keys` 复合主键 = (message_id, group_id, player_qid)…`command` **不参与去重**——同 message_id+group+qid 的不同结算类型视为已结算（先到者胜，不双结算）"）、`:859`（流程① `idem_claim` 只读查重）；`qbot_rpg/world/session.py:289-310`（调合终态幂等封装同口径） | **高** | 把 `kind` 加进去重键 → 同消息重复结算/双扣风险回归。**不要动** |

---

## 3.5 D 组：CHANGELOG 批次裁决（D1–D7）

> 判据类型 = `CHANGELOG.md` 批次条目里的"刻意不修 / 明确排除 / 待裁决"。
> ⚠️ **批 72/73 的记录插在最前面，导致所有批 71 及更早条目的行号整体后移**；本表已全部用当前行号（盘点文档里的旧行号见 §6）。

| 编号 · 现象（为什么形似 bug） | 真实设计意图 | 判据来源 `file:line`（本章复核） | 置信度 | 误修会怎样 / 正确改法 |
|---|---|---|---|---|
| **D1 批 71 包专属残留清理：统一改法 = 包声明 + 框架读取 + legacy 兜底**<br>现象：框架里仍留包专属 id 兜底，像"清理没做干净" | 明确"包不声明 → 与现状逐字段一致"；**71-A2 删兜底被显式挂起**（框架单测无 registry 走 legacy、云海包在仓外无法确认全声明，故保留） | `CHANGELOG.md:65-89`（批 71 全条）；**挂起原因在 `:87-88`**（"未完成：71-A2（删 legacy 兜底——框架单测无 registry 走 legacy 路径，且云海包在仓外无法确认「全包已声明」，按方案保留兜底）与 71-B1/B2/B3"）<br>复核注：盘点引 `CHANGELOG.md:17-19`/`:25-28`/`:32-34`/`:39-40`，均为旧行号 | **高** | 强行执行 71-A2 删兜底 → 框架单测/未声明包行为改变。**不要动**；要做先满足两个前置 + 零行为对拍 |
| **D2 批 70 旧键 `weakness_dmg_pct` 经战斗桥归并入 `damage_dealt_pct`（只算一次）**<br>现象：旧键仍可用且又新增轴，像"两份数值" | 新增唯一收口 `battle._damage_dealt_mult`；旧键经 pct 层归并、只算一次 | `CHANGELOG.md:93-99`（批 70 ①："`damage_dealt_pct` 新增唯一收口 `battle._damage_dealt_mult`（总伤末/双通道末…），旧键 `weakness_dmg_pct` 经战斗桥 pct 层归并入本轴（只算一次）"）；`qbot_rpg/core/battle.py:4209-4228`（`_damage_dealt_mult` 实现 + docstring "旧键 `weakness_dmg_pct` 已在 `combatant_updates` 的 pct 层归并进本轴 → 只算一次、不在此重复"） | **高** | 两处都算 → 弱点增伤**翻倍**。**不要动** |
| **D3 批 53 冷却旧占位键"激活并归并"、不双计**<br>现象：`cooldown_reduction_pct` 与 `cooldown_pct` 符号相反、两键并存 | 旧键经 `route_legacy_aliases_into_flat` 换算一次 `flat["cooldown_pct"] += −旧值`；`route_bonus_into` 契约不变仍不进 flat/pct | `CHANGELOG.md:296-301`（批 53 ①："旧占位键 `cooldown_reduction_pct` **激活并归并**——`route_bonus_into` 契约不变（仍不进 flat/pct），新增 `route_legacy_aliases_into_flat` 在聚合入口换算一次 `flat["cooldown_pct"] += −旧值`（旧键仍可用、**不双计**）"）；`qbot_rpg/data/gear_stats.py:26-30`、`:754-783` | **高** | 去重键/正负号当 bug 改 → 冷却减缩变增加，或双计。**不要动** |
| **D4 批 52 `immune_dmg` 作"负半轴别名"只乘一次；`effects` 的 mitigation 阶段按批 50 不动**<br>现象：`immune_dmg` 与新承伤轴并存且取负，像"符号写反 + 重复减伤" | 承伤乘区唯一求值处；旧免疫键作负半轴并入、只乘一次、沿用 [0,100] 封顶；**明示不得动 mitigation 阶段** | `CHANGELOG.md:325-330`（批 52 ④："`battle._damage_taken_mult` 为**承伤乘区唯一求值处**…`immune_dmg` 作负半轴别名 `pct = −immune` 只乘一次、**不双计**…`effects` 的 `mitigation` 阶段按批 50 `consumer_note` 不动"）；`qbot_rpg/core/battle.py:4229-4252`；`qbot_rpg/data/gear_stats.py:253-265` | **高** | 见 §3.1 样例②/④：易伤变免疫、双计、或与护盾/保底交织。**不要动** |
| **D5 批 50：无消费点的轴**不登记**；`legacy_alias` 只声明不改旧链路**<br>现象：登记表里有的轴"只登记不生效"，像"死配置"；旧键换算声明却不消费，像"写了没用" | 原则：**无消费点的轴不得登记**（`cooldown_reduction_pct` 的教训）；本批只登记、旧键链路不动，缺省/未配置 → 逐字段零变化 | `CHANGELOG.md:356-367`（批 50 全条，含"每条轴都写出「唯一消费点（本批待接）」；无消费点的轴不登记（`cooldown_reduction_pct` 的教训）"）；`qbot_rpg/data/gear_stats.py:56-59`（登记纪律原文）、`:584-589`（`EFFECT_LEGACY_ALIASES` "本批不消费、不改写任何既有链路"） | **高** | 把"只登记"的轴当死代码删 → 后续批次接线锚点丢失；提前消费旧键 → 双计/行为变化。**不要动**；要清的只有"登记了却承诺生效"的项（走批 70 的三选一裁定） |
| **D6 批 59/批 56：`action_recovery_pct` 按裁决不登记、归 `DEPRECATED_EFFECT_AXES` 黄提示**<br>现象：明明有对应机制却"不实现、只黄提示"，像"功能漏做" | D2 裁决：`action_speed_mult` 与 `action_recovery_mult` 数学互为倒数、**必须二选一**；未裁决前不登记/不接线/不写测试 | `docs/深度打造_决策记录.md:1092`（§19.3 待裁决 D2："`action_speed_mult`（X28）vs `action_recovery_mult`（X29）**二选一**…二者数学互为倒数，并存 = 指数速度。用户未裁决 → 本批**不登记/不接线/不写测试**"）；`CHANGELOG.md:234-245`（批 56 ①）；`qbot_rpg/data/gear_stats.py:450-459`（`DEPRECATED_EFFECT_AXES = {"action_recovery_pct": ("action_speed_pct", "…二者并存会让作者叠加导致指数级加速…")}`） | **高** | 两个都接 → 速度**指数级加速**。**不要动** |
| **D7 批 56 `overheal` 是布尔开关、**不是特效轴****<br>现象：有强度/上限参数却不在特效轴表，像"登记遗漏" | D4：过量治疗是 E5 布尔开关，故不登记为轴；缺省 = 关闭 = 与现状一致 | `qbot_rpg/data/gear_stats.py:69-70`（"**D4 `overheal`**：**不是轴**（E5 = 布尔开关），故不在此登记表；…缺省 = 关闭 = 与现状一致（过量部分丢弃）"）；`CHANGELOG.md:242-245`（批 56 ②）；`CHANGELOG.md:188-191`（批 59 BV-1/BV-2：`cap_pct`/`cap_flat`、`mode ∈ keep\|discard`，`shield` 为**未实现保留位**） | **中** | 硬塞进特效轴 → 与开关语义冲突，缺省行为可能改变。**不要动**；要加上限/去向改 `settings.overheal` 段 |

---

## 3.6 待查 / 待裁决清单（**不要贴"勿修"标签**）

> 上游 §7 未决清单 + 审计3 §7（D1–D10）+ 本章复核新增。
> **纪律**：本节条目**不是**"勿当 bug 修"，而是"**还没裁定**"。改之前先补证据或拿到裁决，否则会把"待收口"当成"永久设计"。

### 3.6.1 已消解（上游列为缺口，本章已补齐）

| 上游缺口 | 现状 |
|---|---|
| "审计3 §6 合理并存清单原文不在仓库" | ✅ **已消解**：按用户指示从仓外 `/root/deliverables/审计3_勿增实体_重复机制.md` §6 摘录，逐条回仓库复核后并入 §3.3（R1–R13） |
| "用户点名样例② `affinity_keys.py` 的 `aliases` 表不在仓" | ✅ **已核实**：`qbot_rpg/data/affinity_keys.py` 全文 **85 行**（`wc -l` 复核），只有池类型/反应类型/载荷键/常量，**确无 aliases 表**。仓库内真实的"别名归并"见 §3.4 C3 / C12 / C14 / C15。**样例② 的表述需回填仓外来源，或改用"键族 aliases"泛指** |

### 3.6.2 待裁决（有并存事实，但"永久设计 vs 待收敛"未定）

| # | 事项 | 现状 | 需要什么证据 / 裁决 |
|---|---|---|---|
| **T1** | **B5 门槛判定两口径**（`tier_index_for_level` vs `level` 直比） | 默认配置等价；`cmd_register` 走钳制口径、其余 10 处直比（`审查_M8实现_批次E2_jspace.md:103`） | **需要**：内容包 `tier_names` 实际档数扫描（少于 5 档时两口径不等价）+ 是否要统一。**未确认前不要改任一条** |
| **T2** | **B12 炼金能量开关双源**（`proficiency.json energy.enabled` vs `settings alchemy.energy_enabled`） | 契约要求保留双源但**优先级未定**（`docs/审查/M8契约审查_20260829/审查_M8契约_路C_jspace.md:84`） | **需要**：ADR 裁定优先级（建议 `settings` 为准、`proficiency` 兜底）。**未定前改任一源都会让作者预期落空** |
| **T3** | **审计3 §7 D1：`weakness_dmg_pct` / `damage_dealt_pct`** | **批 70 已接线**（`CHANGELOG.md:93-99`、`battle.py:4209-4228`）→ 该项**已消解为设计**（旧键经 pct 层归并、只算一次） | 已无待裁决；保留本条仅为对表（若未来要撤登记，需同时撤别名 + 撤 preset，勿只改一半） |
| **T4** | **审计3 §7 D2：`settings.slot_defs` ↔ `slots.json`** | 两处注释**互相矛盾**：`module_catalog.py:87-99` 说"功能重叠、建议归口一处"；`field_meta.py:388-392` 说"是不同数据空间——这里是「装备部位定义」" (`fields key 用 slot_defs 避免撞名`) | **需要**：判定二者是否同一数据空间。若是 → 归口一处；若否 → **撤销 `overlap_with` 告警并更正 catalog 文案**。**在此之前不要删任一侧** |
| **T5** | **审计3 §7 D3：`deep_craft.craft_rules.cost_*` ↔ `forge.forge_fee`** | 都表达打造成本但属两条流程，无文档裁定关系 | **需要**：是否要统一"打造费用"口径。若两系统长期并存 → **明确写"各系统自算成本"并登记** |
| **T6** | **审计3 §7 D5：`debuff_chance_pct`/`buff_chance_pct` 是否 `scope={debuff,buff}` 分治** | `docs/深度打造_决策记录.md:1097`（D-new-5 待裁决） | **需要**：若要做分治 → 别名**不能简单删**；否则按 §3.4 C3"可删"处置。**裁决前保留** |
| **T7** | **审计3 §7 D6：`data/status.py::StatusInstance` 死表示** | 自认与 `effects.py` dict 形态不一致、禁止灌入；但它是 `check_architecture.py:49-51` TC-04 **必需类型**之一 | ✅ **批74 裁定：保留**。`check_tc04` 对 `REQUIRED_TYPES` 中「未定义」直接判 fail→`exit 1`，故门禁要求其存在；删除须先做双轨收敛评审 + 同步门禁与测试（登记理由见 `data/status.py:16-24`）。原「删或补互转」二选一留给收敛批 |
| **T8** | **审计3 §7 D7：`rune_sockets` / `alchemy.affinity_effects` 登记空档** | `content/field_meta.py` 已登记，但**无任何包声明**（`zz_craft_demo` 亦无） | **需要**：是否补示例包声明；否则属"登记了但内容从未用过"的准死段 |
| **T9** | **审计3 §7 D8：`damage_base`/`heal_rate` 兼容保留键** | `qbot_rpg/content/field_meta.py:1439`/`:1443`（两个 `FieldMeta`）+ 批74 裁决注释 `:1426-1438`；Python 侧 `formula_loader` **不消费**；审计原文 `:1381-1391` 为**行号漂移**（批74 前为 `:1424-1436`） | ✅ **批74 裁定：保留**。查证：① JS 侧 `web/static/index.html` 零硬编码（表单按 `FieldMeta` 动态渲染）；② 8 个既有包 `formula.json` 实带两键；③ 测试正面锁定；④ 属兼容承诺。删除三条件见代码注释 / 手册 §六 |
| **T10** | **审计3 §7 D9：命名冲突 `craft_paths.PATH_FORGE` 实际指 deep_craft，而 `/锻造` 是 M9 forge** | `core/craft_paths.py`（`forge_enabled`/`forge_path_enabled` 读 `settings.deep_craft.enabled`）；`settings.json.forge` 与 `forge.json` 是 M9 forge | **需要**：在文档/字段 help 明确"打造路径（deep craft）"与"锻造系统（M9 forge）"。**后人极易误改**（也正是 §3.4 C9 的成因） |
| **T11** | **审计3 §7 D10：`deep_craft.equipment_level`（算）vs `temper.resolve_equipment_level`（读）** | 同名异义，非重复但极易误用 | **需要**：二者之一改名（如 `derive_equipment_level`），消除同名 |
| **T12** | **§3.3 B10 套装技能"多技能并存"** | schema 自然延伸但**未显式标"本文扩展"** | **需要**：确认是否只需**文档补注**（`docs/审查/幻觉审查_2c2d.md:80` 已提示）。**低置信度——不要据此改代码** |
| **T13** | **§3.4 C8 改名后旧名悬空** | 注释明写"产品明确允许（确认后照常保存）"，但未标"永久"还是"待做级联" | **需要**：确认是否为永久容忍。若是 → 升为"勿修"；若否 → 需专门迁移方案。**当前不要改成自动级联** |

### 3.6.3 尚需全仓扫描的模式（上游 §7 未决清单 5，本章**未**逐一穷举）

上游建议"后续按批扫描 `qbot_rpg/` 全量注释"。本章复核确认这些模式**确实大量存在**，但**未**逐条给出 file:line 清单：

| 模式 | 为什么需要一次专项扫描 | 本章状态 |
|---|---|---|
| `or` 默认值兜底（`settings.get(...) or DEFAULT`） | 与 `or` 不是 union 的 legacy 兜底（§3.1 样例③）形似，但语义相反：一个是"空则兜底"，一个是"有则覆盖" | **待查**（未穷举） |
| 单位换算（`× 86400`、`/100` 百分点 ↔ 小数） | 同一语义在不同层用不同单位，改一处忘另一处会静默出错 | **待查** |
| 取整口径（`int()` / `round()` / `floor()`） | 承伤乘区"三路来源合入同一次整型截断"就属此类（`qbot_rpg/core/battle.py:4244-4251` 已如实登记 ≤1 点差异） | **待查** |
| 上限/下限钳制（`clamp` / 下钳 0 / 封顶 0.6） | `pierce` 统一封顶 0.6（`qbot_rpg/data/gear_stats.py:90-92`）、`immune_dmg` 封顶 [0,100]——都是"刻意不放宽" | **待查**（已复核 2 例，余未穷举） |
| 静默跳过 vs 安全失败 | C25/C26/C20 是三个不同答案（安全失败 / 不静默 / 运行时降级），**必须逐处看注释** | **待查**（已复核 3 例） |

---

## 3.7 复核发现：真正的 bug 与"盘点文档偏差"

> 本章不是"反对修 bug"。以下两类要分清：**真 bug 照修**；**盘点文档的行号/路径错误**要修正，否则后人照它 review 会找不到依据。

### 3.7.1 已确认的真 bug / 真缺口（不是"勿当 bug 修"）

| # | 事项 | 证据 `file:line` | 处置状态 |
|---|---|---|---|
| BUG-1 | **`pvp.py` free 模式 `enemy_act` 真 bug + verify 脚本过期调用** | `CHANGELOG.md` 批73 条目（登记为独立小批）；`qbot_rpg/core/pvp.py:367-378`；壳接口 `qbot_rpg/core/battle.py:5335`（`enemy_act`）/`:5354`（`end_turn`） | ✅ **已修（批74）**：free 模式移除已删的 `enemy_act` 调用——防守方「一直防御」由引擎 `_ai_action_dict()` 对 `battle_type=="pvp"` 恒返回 guard 保证（`battle.py:5238`）；`scripts/verify/verify_m1.py` 2 函数改 CTB 等价（`player_act`）；`scripts/verify_veinborn_smoke.py` 改 CTB（2 条独立缺口登记）；新增回归测试 2 条 |
| BUG-2 | **`damage_base` / `heal_rate` 死兼容键** | `qbot_rpg/content/field_meta.py:1439`（`damage_base`）/ `:1443`（`heal_rate`），批74 裁决注释 `:1426-1438`；审计3 D8（审计原文引 `:1381-1391`，批74 前为 `:1424-1436`——**行号漂移本批顺带登记**） | ✅ **裁定：保留（批74）**（见 §3.6 T9）——查证：JS 侧零硬编码（表单按 `FieldMeta` 动态渲染）、8 个既有包公式实带、测试正面锁定、属兼容承诺；**删除三条件**见 `field_meta.py:1426-1438` / 手册 §六 |
| BUG-3 | **`data/status.py::StatusInstance` 死表示** | 审计3 F6；`scripts/check_architecture.py:49-51`（TC-04 `REQUIRED_TYPES`）；批74 裁决注释 `qbot_rpg/data/status.py:16-24` | ✅ **裁定：保留（批74）**（见 §3.6 T7）——`check_tc04` 对「未定义」直接 `exit 1`，删它会碰架构门禁；属契约 spec 类型，删除须先做「双轨收敛」评审 + 同步门禁，**不是死码清理** |
| BUG-4 | **`forge.decompose_rate` 死键** | 批 70 已删除（`CHANGELOG.md:99-102`；`qbot_rpg/content/forge_settings.py:30-31` 记载删除） | ✅ **已修**（批 70）；唯一源 = `settings.alchemy.decompose_rate` |
| BUG-5 | **文档与实现不一致（覆盖率目录、旧分层名）** | §2.3 G-5/G-6 | **未修**（文档侧）；代码以脚本为准 |
| BUG-6 | **批 71 两份依据文档缺失** | §2.3 G-7；`CHANGELOG.md:66` | **仓外存在**（`/root/deliverables/`）；建议回填仓库，否则 CHANGELOG 悬空 |

### 3.7.2 判定原则（写进本章，供后人复用）

> **"形似 bug"的正确处理顺序**：
> 1. 先在本章 §3 搜现象 → 命中且置信度"高" → **默认不改**（要改走 §4）；
> 2. 命中但置信度"中/低" → 转 §3.6，**先补证据或拿裁决**；
> 3. 未命中 → 看 §3.7.1 是否已登记为真 bug；是 → 照修；否 → 按 §5 checklist 判定；
> 4. 判定完成 → **把新结论回填本章**（附 `file:line` + 置信度），否则下一个人还会重踩。

---

# 4. 稳定契约章节（改动需评审）

> **【稳定契约】= 改动必须走评审**：不是"不能改"，而是"改之前要知道自己在动什么、谁在用、怎么对拍"。
> 本节把散落在 §3 各条的"稳定契约"集中成一张表，供评审会直接引用。

| # | 稳定契约 | 唯一源 / 落点 `file:line` | 谁在用 | 自动校验处 | 改动要求 |
|---|---|---|---|---|---|
| S1 | **公开 JSON 字段名**（`field_meta` 键空间） | `qbot_rpg/content/field_meta.py`（整表）；包侧 `content/<包>/field_meta.json` | 所有内容包、编辑器、校验器 | **字段元数据迁移门禁**：`scripts/compare_field_meta_migration.py:320`（基线 `07293ee`）、`:534`（`compare_snapshots`） | 删/改任一字段名 → 必须保留旧键兼容或走迁移方案重定基线（`docs/审查参考/开发规则文档.md:68`：「JSON 字段名 = 公共 API」） |
| S2 | **伤害管线阶段顺序** `DEFAULT_PIPELINE_ORDER` | `qbot_rpg/core/effects.py:129-138` | `EffectsRuntime` 全流程、所有承伤/减伤/护盾/保底逻辑 | 既有 effects 单测 + 红线对拍 | 不得插队/合并阶段；**尤其不得把易伤并入 `mitigation`**（§3.1 样例④） |
| S3 | **特效轴登记表** `EFFECT_AXIS_SPECS`（17 轴）+ `legacy_alias` + `EFFECT_LEGACY_ALIASES` | `qbot_rpg/data/gear_stats.py:230`（表）、`:584-589`（反查表）、`:448-459`（`DEPRECATED_EFFECT_AXES`） | 战斗桥 `combatant_updates`、校验器、编辑器、框架预设 | 轴表/反查表一致性测试；`effect_values_of`（`:978-997`）度量 | 加轴必须同时给「唯一消费点」；**无消费点的轴不得登记**（§3.5 D5）；改 `sign` = 改玩法语义，必须评审 |
| S4 | **旧键 → 轴 的唯一换算三入口** | `gear_stats.py:754-783`（占位键 flat）、`:786-837`（pct 层）、各消费点（COMBAT 旧键） | 聚合入口 `core/equipment.py:1006-1008` | 双计回归测试；`route_bonus_into` 跳过占位键 `:743` | **不得新增第四个换算点**；不得把 `or` 改成 union（§3.1 样例②③） |
| S5 | **`EVENT_POINTS` 事件时点枚举 + `on_kill`/`death` 语义** | `qbot_rpg/data/event_points.py`（唯一源，批 51 下沉）；派发 `core/event_dispatcher.py` | 效果 `trigger`、装备被动、连段、怪物 AI | `check_m7_content.py`（条件键/占位符）；校验器 Y-19（未登记时点黄提示） | 增点时点必须同时改枚举 + 派发点 + 校验；**旧文档 `on_turn_start`/`on_death` 写法 → 现行键名无 `on_` 前缀**，见第二路手册 |
| S6 | **归属规则 `owner_effect_ids` / `claimed_effect_ids`** | `qbot_rpg/data/gear_stats.py`（`OWNED_EFFECT_IDS_KEY`）；批 51（`CHANGELOG.md:339-355`） | 装备被动、两侧触发过滤 | 缺省（两侧都无归属集）→ **全库扫描旧行为**逐字段对拍 | 缺省必须保持"全库扫描"；不得让归属集影响未声明内容 |
| S7 | **`qbot_rpg.ext_api` 稳定面** | `qbot_rpg/ext_api.py:42-57`（`__all__`）、`:59`（`EXT_API_VERSION = "1"`） | 所有包自持代码（`ext/*.py`） | 无自动校验；靠评审 + `EXT_API_VERSION` 纪律 | **破坏性变更必须递增 `EXT_API_VERSION`**；新增导出要评审（它是 E 方案的公开承诺） |
| S8 | **内容包红拦 5 类封闭清单** | `qbot_rpg/content/validator.py:4`（R-1~R-5）；接线 `loader.py:235`→`:328`→`:345` | 所有内容包 | 校验器单测；`loader` 集成测试 | **不得扩大红拦清单**（会让所有包同时被拒）；包侧需求用 `settings.schema_ext`（`validator.py:389-524`） |
| S9 | **扩展双闸语义** | `qbot_rpg/assembly/pack_ext.py:141`、`:514-519` | 部署方信任模型 | `tests/` 内双闸测试 | 不得改成"单闸"或"默认开"；未开必须**零文件访问** |
| S10 | **幂等键 schema**：(message_id, group_id, player_qid)，`command` 不参与去重 | `qbot_rpg/world/battle_boundary.py:840-848`；`storage/schema.py`（复合主键） | 退出结算、调合结算 | 幂等回归测试（双扣/重复结算） | **不得把 `kind` 加进去重键**（§3.4 C27）；不得改成"先到者合并" |
| S11 | **存档格子 `player_pack_state`（每 玩家×内容包 一格，框架零包名）** | `qbot_rpg/storage/schema.py:176` | 所有包状态持久化（`ext_api` 的 `get_state` 等） | 存储往返测试 | 不得给 `players` 表加包专属列（`docs/存档格子_内容包作者用法.md:104-109`）；不得跨包读写 |
| S12 | **分层依赖方向矩阵** | `scripts/check_architecture.py:31-47` | 全仓 import 图 | TC-03（`:319`）、TC-01（`:167`）、TC-02（`:189`）、TC-04（`:381`） | 加层/改边必须走架构评审（R3/R6）；`assembly` 顶层豁免不可扩散 |
| S13 | **指令分隔符三铁律** | `docs/审查参考/指令分隔符统一规范.md:27-61`；实现 `commands/parsers.py` | 所有指令解析 | 解析器单测 + 命令面验收 | 新指令必须照三条铁律设计参数面（§3.2 A11） |
| S14 | **`hp`/`mp`=0 合法语义** | `qbot_rpg/storage/repository.py:324-326` | 读档、战斗、死亡判定 | 存储往返测试 | 任何"兜底默认值"必须用 `is not None` 判定，**不得用 `or`**（§3.4 C18） |
| S15 | **`rng_state` V2 权威位 + `_rng_state` V1 兜底读** | `qbot_rpg/core/battle.py:5696-5700` | 续战/快照 | 续战回归测试（随机序列重放） | 删旧键前必须确认无旧存档（§3.4 C17） |
| S16 | **事件键 `EVENT_KEY_DEFAULTS` 缺省回退** | `qbot_rpg/core/event_bus.py:26-27`、`:63-66` | 条件引擎读事件计数 | 事件键一致性测试 | 零配置必须回退现字面量（§3.4 C16） |
| S17 | **渲染层"绝不抛出"铁律** | `qbot_rpg/core/message_format/battle_render.py:2026` + 各入口 `:92`/`:223`/`:308`/`:2070`/`:2146`/`:2224` | 战报/消息渲染 | 渲染单测（含异常注入） | 新增渲染分支也必须兜底（§3.4 C21） |
| S18 | **`mitigation` 只做减伤 / 承伤轴唯一收口** | `effects.py:1157-1184` + `battle.py:4229-4252` | 全部伤害结算 | 红线对拍 + effects 单测 | 两处**不得合并**（§3.1 样例④） |

> **评审时的最小动作**：命中 S1–S18 任一项 → 评审记录里必须写清 ① 为什么非改不可 ② 谁会被影响 ③ 用哪条对拍证明零行为变化（§5.4） ④ 是否要递增 `EXT_API_VERSION` / 重定迁移基线。

---

# 5. 给维护者的"改代码前 checklist"

> 这就是本章对维护者的核心价值。**顺序不要跳**：先查 → 再看契约 → 再跑门禁 → 最后对拍。

### ① 先查本章（3 分钟）

```bash
# 在仓库根
# 1) 记录基线（评审记录必须带这个值）
git rev-parse HEAD && git status --porcelain      # 必须为空

# 2) 用现象关键词搜本章（把"成功率/重复/双计/写死/不生效/吞异常"等换成你的现象）
grep -n "成功率\|双计\|写死\|不生效\|吞异常" /root/deliverables/API手册_3_权责与勿当bug修.md
```

- 命中 §3 任一 **高置信度** 条目 → **默认不改**；确要改 → 进 §4 评审。
- 命中 **中/低** → 转 §3.6，**先补证据或拿裁决**。
- 未命中 → 看 §3.7.1（已登记真 bug）→ 是 → 照修；否 → 继续 ②。

### ② 看是否有【稳定契约】标注（2 分钟）

- 你要改的文件/符号，是否出现在 §4 的 S1–S18？
- 判断口径：**改公开字段名 → S1；改管线/轴/归属 → S2/S3/S4/S6/S18；改校验红拦 → S8；改扩展装载 → S7/S9；改幂等/存储 → S10/S11/S14/S15；改分层 → S12。**
- 命中 → 必须拉评审，并在评审记录里写明"动的是哪条稳定契约"。

### ③ 跑哪些门禁 / 护栏（按改动面选，宁多勿少）

| 改动面 | 必跑 | 说明 |
|---|---|---|
| **任何改动** | `python scripts/check_all.py` | 默认 = 静态（ruff/mypy）+ 架构 + 内容包 + 单测（`check_all.py:100`、`:123`、`:134`） |
| **发布前 / 大改** | `python scripts/run_all_tests.py` | 阶段 0 lint → 阶段 1 pytest 金字塔 → 阶段 2 `verify_m0~m6`(+M9) → 阶段 3 `core`+`content` 各 ≥80%（`:295`） |
| **碰架构/import** | `python scripts/check_architecture.py` | 必须输出 `ARCH-OK`；否则 TC-01~04 会红 |
| **碰公开字段名/元数据** | `python scripts/compare_field_meta_migration.py` | 必须 **diff = 0（硬差异）**；新增字段允许但要逐条列出 |
| **碰模板/文案** | `python scripts/check_template_width.py` | 结构化行 ≤14 全角；`meta.prose_keys` 登记项豁免 |
| **碰内容包数据** | `python scripts/check_m7_content.py --path content/<包>` | 可达性/条件键/占位符；**注意缺省只查一个包**（§2.3 G-2） |
| **碰炼金数据** | `python scripts/check_m8_fixtures.py` | 八项契约自检 |
| **碰包自持代码** | `python scripts/run_pack_tests.py --pack <包>`；`python scripts/run_pack_build.py --pack <包> --check` | E3 包自测 / 包构建 `--check` |
| **换包验收（通用性）** | `python scripts/editor_verify_packs.py` | 12 包全 PASS（"换包零改动"自证） |
| **合入前** | `git status --porcelain` 必须为空 | 工作树干净是硬纪律 |

> **护栏不许动**：本仓库历次批次的硬纪律包含"既有护栏测试不许动"——审计报告 `框架体检报告.md:75`（仓外）写的是"**批 67 的 27 个护栏不许动**"。改动时若发现某个护栏挡住了你，**先怀疑自己**，不要删护栏。

### ④ 零行为变化对拍怎么做（**本仓库的硬纪律**）

**定义**：当你的改动**不应改变玩法**时，必须证明"改前 / 改后逐字段（或逐字节）一致"。

**三件套（按改动面选）**：

| 工具 | 用途 | 用法 |
|---|---|---|
| **工具尺** `scripts/batch45_measure.py` | 单发普攻基准（无技能/不暴击/乱数 1.0，**固定种子 20260919**，N=20000 蒙特卡洛） | 改前 / 改后各跑一次 `--json`，**逐字节比对** |
| **定稿档位尺** `scripts/batch55_dual_ruler.py` | 工具尺 + 定稿档位尺 + 精确翻转阈值（`docs/深度打造_决策记录.md:1203`） | 同上；用于"特效轴/数值类"改动 |
| **字段元数据对拍** `scripts/compare_field_meta_migration.py` | 公开字段名向后兼容 | 硬差异必须 = 0（§4 S1） |

**必测的"缺省路径"**（这是本仓库所有批次共同的验收口径）：

1. **不配置新键 / 新段** → 行为必须与引入前逐字段一致（例如批 70："未配置（轴 0）→ ×1.0 → 逐字段零变化"，`CHANGELOG.md:97-99`）。
2. **registry 对拍** + **一场战斗的结算快照对拍**（批 50 口径，`CHANGELOG.md:366-367`）。
3. **两侧都没声明归属** → 全库扫描旧行为（批 51 口径，`CHANGELOG.md:353-355`）。
4. **旧包/旧存档** → 迁移路径逐位一致（批 72 F1："归一 settings 逐字段一致"，`CHANGELOG.md:47-48`）。

**对拍不通过的处置**：
- 若差异是**预期的**（你故意改了玩法）→ 这不再是"零行为变化"，必须走评审 + 更新 CHANGELOG + 更新本章 §4；
- 若差异**不是预期的** → 你的改动引入了副作用，回退或修正。

### ⑤ 收尾

- CHANGELOG 追加条目（仅 `feat`/`fix` 进，`docs` 不进——`CHANGELOG.md:6-7`），按 `Added`/`Changed`/`Fixed` 分节；
- 若命中 §4 稳定契约 → **同步更新本章 §4 与相关章节**；
- 若新发现"形似 bug 实为设计" → **回填 §3**；若新发现真 bug → 登记 §3.7.1；
- 页脚批次串同步（本仓库惯例）。

---

# 6. 附：本次复核方法与偏差总表

## 6.1 复核方法（可复现）

1. **基准**：`git rev-parse --short HEAD` = `62cc299`（批 73 死代码清理后），`git status --porcelain` 为空。
2. **逐条独立复核**：对盘点文档 §7 的每一条 `file:line`，用 `sed -n '<range>p' <file>` 打印原文比对；对关键符号用 `grep -n` 定位定义行（不定位于引用行）。
3. **判据优先**：以**当前工作树**为准，不以盘点文档转述为准；盘点文档的行号/路径错误**逐条登记**（下表）。
4. **不硬下结论**：无法确认意图的标"待查"，写明缺什么证据（§3.6）。
5. **本章只读仓库**：未修改 `/root/QBot-TurnTellerRPG` 任何文件（仅产出本报告）。

## 6.2 盘点文档偏差总表

> 说明：盘点文档 `API手册_编撰前盘点.md` 基于 HEAD `d86d9dd`（批 71 后）。本章基于 `62cc299`（批 73 后）。**批 72/73 的记录插在 `CHANGELOG.md` 最前**，且批 73 删了部分死代码，因此出现系统性行号漂移。以下为**实质性偏差**（会让人找不到依据的），**非**纯 +N 漂移。

| # | 盘点文档写的 | 复核后（HEAD `62cc299`） | 性质 |
|---|---|---|---|
| 1 | `CHANGELOG.md:17-19`/`:25-28`/`:32-34`/`:39-40`（批 71 依据） | **`CHANGELOG.md:65-89`**（批 71 全条；71-A2 挂起在 `:87-88`） | 旧行号（批 72/73 前插） |
| 2 | `CHANGELOG.md:43-47`（批 70）、`:244-253`（批 53）、`:265-282`（批 52）、`:308-319`（批 50）、`:263`（批 56） | 分别在 **`:93-99`**、**`:296-301`**、**`:325-330`**、**`:356-367`**、**`:238-245`** | 旧行号 |
| 3 | `docs/细化/细化_2c4c1_品质与刻度.md:25`、`:26`（A5） | **该文件不存在**；正确路径 = **`docs/规划/规划_路2c4c1_品质与刻度.md:25-26`** | **路径错误** |
| 4 | `docs/细化/细化_M6_三引擎与基础指令.md:69`（A10 商店刷新） | 该行实为 **B-4 背包双上限**；A10 正确依据 = `qbot_rpg/content/shop_models.py:6-7` + `docs/细化/细化_2b3_商店引擎契约.md:392-393` + `记录.md:1522` | **张冠李戴** |
| 5 | `docs/审查/幻觉审查_6a.md:23`（A7） | **`:24`**（`:23` 是表头分隔行） | 漂移 1 行 |
| 6 | `qbot_rpg/content/validator.py:6`、`:3573`（A8） | **`:5`**（docstring §2.3）；默认放行实现 = **`:675`**（`:3573` 是 formula 标量透传分支） | 漂移 + 错引 |
| 7 | `qbot_rpg/commands/basic_commands.py:2289-2291`、`:2366`（C7） | **`:2280-2282`**、**`:2356-2362`**；**更权威登记** = `qbot_rpg/core/templates/template_table.json:5`、`:32` | 漂移 + 漏引权威源 |
| 8 | `qbot_rpg/core/equipment.py:198-207`（C19） | 这是审计当时"**问题所在行**"（`_worn_rows` 返回全部同 id 行），**不是修复落点**；当前修复落点 = `:43-46`（说明）、`:223`（`_first_worn_row`）、`:580-583`（`_resolve_worn_row`）；回归用例 `tests/unit/test_equipment.py:275-277` | **把问题行当依据** |
| 9 | `qbot_rpg/web/api.py:2813-2814`（C24） | **`:2808-2811`**（`meta_unregistered`/`meta_note`） | 漂移 |
| 10 | `qbot_rpg/content/validator.py:1654`（C5） | **`:1657-1660`**（`R15_chain_cycle` 的 `_note`） | 漂移 3 行 |
| 11 | `docs/审查报告/审查_M8实现_批次E2_jspace.md:25`、`:103`（B5） | **该路径不存在**；正确路径 = **仓库根 `审查_M8实现_批次E2_jspace.md:25`、`:103`** | **路径错误** |
| 12 | `docs/审查报告/审查_M6实现_批1A_三引擎_jspace.md:83`（C19 来源） | **该路径不存在**；正确路径 = **仓库根 `审查_M6实现_批1A_三引擎_jspace.md:83`** | **路径错误** |
| 13 | `qbot_rpg/content/validator.py:27`（门禁 #18"`check_pack`"） | `def check_pack` 在 **`:3901`**；`:27` 只是 docstring 提及 | 把提及行当定义行 |
| 14 | `qbot_rpg/content/loader.py:239`（`build_pack`） | **`:235`**（`:328` `_raise_if_blocked`、`:345` `load_pack`） | 漂移 |
| 15 | `qbot_rpg/content/pack_protection.py:27`（`enforce_play_gate`） | **`:150`**（`:38` `PackProtectionError`） | 漂移 |
| 16 | `scripts/check_architecture.py:440`（`main`） | **`:422`** | 漂移 |
| 17 | `qbot_rpg/commands/parsers.py:107`（`DEFAULT_WHITELIST`） | **`:112`** | 漂移 |
| 18 | `qbot_rpg/commands/processing.py:252`（`process_message`） | **`:267`** | 漂移 |
| 19 | `qbot_rpg/commands/router.py:194`/`:201`（`Router`/`register`） | **`:191`/`:205`** | 漂移 |
| 20 | `qbot_rpg/content/hot_reload.py:194`（`reload`） | **`:191`**（`HotReloadWatcher` 在 `:117`） | 漂移 |
| 21 | 审计3 R3 `qbot_rpg/core/temper.py:6-7`、`:30-31` | **`:21-22`**（职责 6「分账」） | 漂移 |
| 22 | 审计3 R9 `qbot_rpg/core/battle.py:3404` | **`:3426-3441`**（`cooldown_pct` 消费点） | 漂移 |
| 23 | 审计3 R13 `qbot_rpg/commands/forge_commands.py:2250-2251` | **`:2242`**（别名 `("打造", "铸造")`） | 漂移 |
| 24 | `tests/unit/test_checkin.py:53`（B2 多表并存） | 该行是 `SETTINGS` 常量；多表用例 = **`:158`（注释）、`:161-173`（断言）** | 错引 |
| 25 | `tests/unit/test_equipment.py:276`（C19 回归） | **`:275-277`**（`def test_regress_p1_1_...`） | 漂移 1 行 |
| 26 | `scripts/check_architecture.py:185-213`（盘点 §5 A.2 路径约束） | `assembly/pack_ext.py:181-220`（`_resolve_within`） | 跨文件错引 |
| 27 | §0-1「审计3 §6 合理并存清单本体不在本仓库」 | **仍不在仓库**（仓外 `/root/deliverables/审计3_勿增实体_重复机制.md` §6）；本章已按用户指示摘录并入 §3.3 | 已按用户指示消解 |
| 28 | §0-2「样例② `affinity_keys.py` aliases 表不在仓」 | **确认不在仓**（`qbot_rpg/data/affinity_keys.py` 全文 85 行，无 aliases）；真实别名机制见 §3.4 C3/C12/C14/C15 | 复核确认 |
| 29 | 审计3 §7 D8 `damage_base`/`heal_rate` 引 `qbot_rpg/content/field_meta.py:1381-1391` | **`:1424-1436`**（`:1424` 兼容键说明、`:1428`/`:1432` 两个 `FieldMeta` 定义） | 漂移 40+ 行 |
| 30 | 审计3 R10 `effect_values_of` 引 `qbot_rpg/data/gear_stats.py:973-997` | **`:978-997`**（`def effect_values_of` 在 `:978`） | 把函数体内一行当定义行 |

## 6.3 本章验收自检

| 验收要求 | 本章落点 | 状态 |
|---|---|---|
| 清单每条有判据 `file:line` | §3.1 四样例（8+8+6+6 处）、§3.2 A1–A11、§3.3 B1–B12 + R1–R13、§3.4 C1–C27、§3.5 D1–D7 | ✅ 每条均附复核后 `file:line` |
| 每条有置信度 | 全部条目均标 **高/中/低（待查）**；§3.0 有分布统计 | ✅ |
| 【稳定契约】条目明确 | §4 S1–S18 集中表 + §3 内联标注 | ✅ |
| 待查项如实标注 | §3.6 T1–T13 + §6.3 扫描模式，均写明"需要什么证据/裁决" | ✅ |
| 审计3 §6 并入 | §3.3「审计3 §6「合理并存清单」并入（R1–R13）」 | ✅ |
| 三层权责地图 | §1.1–§1.6（含"拥有/不拥有/改哪安全/代价"对照总表） | ✅ |
| 门禁 28 条 | §2.2（A–F 六组，标注 1–28） | ✅ |
| 维护者 checklist | §5（① 查本章 ② 看稳定契约 ③ 跑门禁 ④ 零行为对拍 ⑤ 收尾） | ✅ |
| 只读仓库 | 未修改仓库任何文件；仅产出本报告 | ✅ |

---

> **本章维护约定**：任何"框架更新"若改变了 §4 的稳定契约、或新增/收口了 §3 的"有意设计"，**必须同批更新本章**并注明批次与 `file:line`。否则下一轮维护者仍会把故意设计当 bug 修——这正是本章立项要防的事（`docs/深度打造_决策记录.md:1568`）。








