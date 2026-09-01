# M12 Web 编辑器 UX + 架构方案（六页壳 · 19 页扩展 · GM 指令权限系统）

> 版本：v1.0 · 类型：UX + 架构方案（可落地，非细化契约）
> 权威契约（唯一权威，引用编号以「5a」「5a2」标注，行号 Lxx）：docs/细化/细化_5a_编辑器契约.md（260 行）/ docs/细化/细化_5a2_编辑器扩展页.md（291 行）
> 现状核对：docs/m12_编辑器摸底.md（386 行，逐条缺口 + 15 风险坑位）——本方案每一节均对齐摸底结论
> 约束：中文，无 emoji（功能性 ✅/❌ 标记除外）；契约未覆盖处显式标注【待定】
> 前端铁律：零构建工具链、零 npm、零安装，浏览器直开 index.html；全中文界面；小白（零代码用户）可用

---

## 0. 阅读导览

| 章节 | 内容 | 对应契约 |
|---|---|---|
| §1 | UX 信息架构（六页壳 + 19 页扩展侧边栏 + 布局 + 控件 7 类前端落地） | 5a P-01~P-08 / C-01~C-07；5a2 M-02 |
| §2 | 技术选型（前端原生 JS 单页；后端 FastAPI 路由；认证方案） | 5a ED-01 / AU-01~06 |
| §3 | API 契约表（15 端点冻结） | 5a §6 / 5a2 M-03 |
| §4 | 数据流（保存 → 原子写盘 → 统一重载 → 回退） | 5a SV-01~08 |
| §5 | 元数据驱动表单引擎（FieldMeta 正式表 + 表单渲染器 + editor.json 注册表） | 5a P-07；5a2 PR-01~06 / M-06 |
| §6 | G0 分层与依赖注入（web → {content, core, storage, data}） | 3a D-05；G0 |
| §7 | 实施步骤（6 步，每步验收点） | — |
| §8 | 前端规模控制（最小可用壳先行路线） | m12 摸底 风险 13 |

> **契约冻结声明**：§3 的 15 端点表为 M12 实施唯一依据；如与 5a/5a2 有文字出入，以本表为准（表内逐行标注契约出处，可回溯）。

---

## 1. UX 信息架构

### 1.1 全局布局（P-01 ~ P-05 落地）

布局三层固定视口（`height:100vh` 三段 flex，任何一层内部滚动，整页永不滚动）：

```
┌────────────────────────────────────────────────────────────────┐
│ 顶栏（常驻，P-05）：🎮 你的游戏名 ｜ 数据包：test_demo ｜ [保存] [试玩] │
├──────────┬─────────────────────────────────────────────────────┤
│ 侧边栏    │  页面工作区（左列表 + 右卡片，P-03）                    │
│ （常驻，   │  ┌──────────────┐  ┌──────────────────────────────┐ │
│  P-04）   │  │ 列表（固定表   │  │ 编辑卡片（表单，内部滚动）       │ │
│ 总览      │  │ 格+内部滚动，  │  │ 字段按 C-01~C-07 控件渲染        │ │
│ 职业      │  │ 点击行→右侧） │  │ 底部：校验条（红/黄）+ 保存       │ │
│ 技能      │  └──────────────┘  └──────────────────────────────┘ │
│ 部位      │  （搜索框 / 排序 / 筛选 / 分页虚拟滚动，P-08）           │
│ 装备物品   │                                                     │
│ 怪物      │                                                     │
│ 掉落      │                                                     │
│ 地图      │                                                     │
│ 公式数值   │                                                     │
│ 任务      │                                                     │
│ 商店      │                                                     │
│ ─────    │                                                     │
│ NPC      │                                                     │
│ 签到      │                                                     │
│ 隐藏要素   │                                                     │
│ 环境事件   │                                                     │
│ 日志卡片   │                                                     │
│ ─────    │                                                     │
│ 运营      │                                                     │
│ 数据包管理 │                                                     │
└──────────┴─────────────────────────────────────────────────────┘
  底部抽屉（C-05 引用选择 / CSV 导入区 / 校验明细，从底部滑出）
```

- 顶栏（P-05）：左侧 🎮 游戏名（读 manifest.json `name`）；中间数据包信息（`<pack_id> · v<version>`）；右侧 [保存]（触发 §4 保存链路）与 [试玩]（跳转 5a 附录登记：试玩/模拟器独立能力，本里程碑仅占位按钮【待定】）。
- 侧边栏（P-04/P-05 + 5a2 M-02）：**顺序与启停完全由 editor.json 驱动**（5a2 M-06 / PR-03）；AI 并入怪物页标签栏不单列（5a2 M-02）。未声明页面不渲染（5a2 PR-01：内容包未声明 → 只显示「总览」与「数据包管理」）。
- 列表（P-02）：固定表格 + 内部滚动，每行「序号 + 中文名」；点击行 → 右侧编辑卡片；行尾角标：引用计数 / 「未使用」角标（5a2 N-11）/ 黄提示行标记。
- 未保存提示（P-08）：自动保存 30 秒 + `beforeunload` 关闭确认 + 跨页切换不丢失（数据留在前端草稿层，见 §4.3）。

### 1.2 六页壳侧边栏导航结构

| 页面 | page_id | 图标 | 模块文件 | meta_source | 子标签（tabs） | 契约 |
|---|---|---|---|---|---|---|
| 总览 | overview | 首页 | —（聚合） | — | —（统计条：各页条目数 / 红黄校验计数） | 5a2 PR-01 |
| 职业 | job | 徽章 | jobs.json | meta/job | 量身定制 / 转职路线 / 进阶职业卡片 | 5a P-06 |
| 技能 | skill | 剑 | skills.json | meta/skill | （行动库页 action.json 独立页） | 5a P-06 |
| 部位 | slot | 甲 | slots.json | meta/slot | — | 5a P-05 作用域声明 |
| 装备物品 | equipment+items | 袋 | equipment.json+items.json | meta/equipment / meta/items | — | 5a P-05 作用域声明 |
| 怪物 | monster | 兽 | enemies.json | meta/monster | 基本信息/属性/弱点/PV/抗性/行动/特殊行动/掉落/图鉴 + AI×6 | 5a P-06；5a2 M-02 |
| 掉落 | drop | 币 | （聚合视图） | meta/drop | — | 5a P-05 作用域声明 |
| 地图 | map | 图 | maps.json | meta/map | 基础/通道/怪物/NPC | 5a P-06；5a2 N-02 |
| 公式数值 | formula | 式 | formula.json | meta/formula | — | 5a P-05 作用域声明 |
| 任务 | quest | 卷 | quests.json | meta/quest | 基本信息/条件表单/奖励/板配置/链式任务 | 5a P-06 |
| 商店 | shop | 铺 | shop.json | meta/shop | 商店设置/商品表格 | 5a P-06 |
| 运营 | ops | 台 | —（只读） | — | —（编辑器作用域外，占位【待定】） | 5a P-05 L72-74；5a2 CK-08 |
| 数据包管理 | packs | 包 | —（管理） | — | —（包列表/启用切换/editor.json 管理） | 5a §6.4 |

> 部位/装备物品/掉落/公式数值四页复用同一套元数据渲染、保存、校验、热重载机制（5a 作用域声明 L74），机制契约与六页同等适用。

### 1.3 19 页扩展导航结构（5a2）

| 组 | 页面 | page_id | 载体 | 标签/子区 | 契约 |
|---|---|---|---|---|---|
| 交互 | NPC | npc | npc.json | 基础/地图挂点/对话/条件/交互/任务/商店/情报/教学/发牌（10 标签） | 5a2 N-01~N-11 |
| 交互 | 签到 | checkin | checkin.json | 基础/周期/每日奖励/连签奖励/月度累计/补签/预览（7 区） | 5a2 CK-01~CK-08 |
| 怪物 | AI×6 子页 | ai | enemies.json（extends=monster） | 行动表/条件行动/状态机/阶段/连招链/换区（挂怪物页标签栏） | 5a2 PA-01~PA-06 |
| 隐藏 | 隐藏要素×3 | hidden | maps.json（extends） | 隐藏BOSS/隐藏任务/彩蛋 + 总量面板 | 5a2 PH-01~PH-04 |
| 环境 | 环境事件 | env_event | settings.json | 事件定义/窗口条件/效果引用/触发纪律 | 5a2 PE-01~PE-04 |
| 日志 | 日志卡片 | log_card | settings.json | 记录类型/快照/容量传记/模板只读 | 5a2 PL-01~PL-04 |

### 1.4 控件 7 类 → 前端组件映射（C-01 ~ C-07）

| # | 控件 | 元数据类型 | 前端组件落地 | 交互要点 | 契约 |
|---|---|---|---|---|---|
| C-01 | text 文本框 | str | `<input type=text>` + 字数计数 | 名称类 ≤20 字计数提示；必填空保存标红 | 5a L94 |
| C-02 | number 数字框 | int / number | `<input type=number>` + 步进 | 负数即时标红（R-2）；越界黄色不拦截（Y-1） | 5a L95 |
| C-03 | select 下拉 | enum / bool | `<select>`（enum）；checkbox 开关（bool） | 选项值 = 元数据 enum 列中文标签；动态 enum 从 registry 取（5a2 PR-06 事件名下拉同机制） | 5a L96 |
| C-04 | range 滑条 | int 区间 | `<input type=range>` + 数值显示 | 区间 = range_min/max；zero_unlimited 字段滑条下限 0 + 「0=不限」提示（Y-4） | 5a L97 |
| C-05 | reference 引用芯片+抽屉 | ref | 高亮芯片（显示中文名）+ 底部抽屉 | 点击引用位 → 底部抽屉（搜索框+分页虚拟滚动）→ 选中渲染芯片；存储按 ID（TC-04 改名联动）；悬空红拦 R-4；芯片旁「跳转」按钮（P-08 跨页引用跳转） | 5a L98 / TC-06 |
| C-06 | list 子表 / obj / map | list / obj / map | 行编辑子表格（[+新增][-删除]）+ 拖拽排序（技能位/连招链）+ 递归渲染 children | obj=分组卡片递归；map=键值行表；商品表格 CSV 式行编辑 | 5a L99 |
| C-07 | formula 公式输入框 | formula | `<textarea>` 多行 + 语法高亮（简） | 含运算符或 [变量] 自动切换；旁挂【变量大全】面板（分类列出、自复制、不做下拉）；即时预览；长度 ≤4KB / 10ms 超时（前端软提示，权威校验在 validator） | 5a L100 |

> 表单渲染器 = 元数据驱动（§5.2）：`/api/meta/{page}` 返回字段元数据 → 前端按 type 分派到 7 类组件，**渲染器零页面特判**（P-07 唯一数据源）。

---

## 2. 技术选型

### 2.1 前端：原生 JS 单页（零构建工具链）

| 选项 | 结论 | 理由 |
|---|---|---|
| 原生 JS 单页（index.html + css + js，无框架） | ✅ 采用 | ① 零安装零构建：服务器无 npm 依赖、无需打包，systemd 托管静态目录直接可开（ED-01 部署约束）；② 全中文、小白可改：一个 html 文件，编辑任何片段刷新即见；③ 与 M12 前端规模控制路线匹配（§8 最小可用壳先行）；④ 无框架升级风险、无 lockfile 漂移 |
| 轻框架（Vue/React CDN） | ❌ 不采用 | CDN 依赖公网（公网默认关场景不可用，AU-05）；构建工具链违背「小白可用」；Vue 单文件组件需要编译步骤 |
| 服务端模板（Jinja2） | ❌ 不采用 | 编辑交互（抽屉/滑条/子表递归）是前端状态问题，服务端渲染会导致每次交互整页刷新，违背 P-01 固定视口 |

> 选型红线：前端**零 NoneBot 依赖、零网络 CDN**（静态文件随 FastAPI StaticFiles 挂载）；所有数据经 /api 拉取。

### 2.2 后端：FastAPI 路由结构

```
qbot_rpg/web/
├── api.py               # create_app(state) / iter_routes(app) 实装（35 行骨架替换）
├── deps.py              # 依赖注入装配（watcher / registry / auth_store / editor_registry）
├── routes/
│   ├── auth.py          # 4 端点（setup/login/logout/me）
│   ├── meta.py          # 2 端点（meta/{page} / refs/{target}）
│   ├── pages.py         # 6 端点（六页+19 页统一 CRUD + validate）
│   ├── system.py        # 3 端点（reload / packs / packs/active）
│   └── ui.py            # 静态页挂载（/ 与 /编辑 → index.html）+ 健康检查
├── security.py          # bcrypt 哈希 / token 会话表 / 防爆破锁 / CSP 头中间件（零 NoneBot）
├── editor_registry.py   # editor.json 解析 + page_id → meta_source/module_file/validator 映射（§5.3）
├── write_service.py     # 原子写盘（temp+rename）+ 快照回退 + 版本号维护（§4）
└── static/              # index.html / app.js / app.css / vendor（前端单页）
```

- 根路径 `/` 与 `/编辑` 均返回编辑器页面（5a §6 注：「前缀 /编辑 为编辑器页面入口」，ED-04 链接返回 `/编辑`）。
- 一切 >50ms 操作（校验/CSV/zip/文件 IO）走 `asyncio.to_thread`（5a §6 补白，禁止阻塞事件循环）——HotReloadWatcher.reload 本身已是 to_thread 内同步管线（hot_reload.py:194-200），直接复用。
- 端口 8080 目标（ED-01 `http://IP:8xxx`）；host/port 经 launcher 配置注入（web/launcher_hint.py 登记于 3a，文件不存在【待定】——M12 新建）。

### 2.3 认证方案（AU-01 ~ AU-06 落地）

| 项 | 方案 | 契约 |
|---|---|---|
| 密码哈希 | bcrypt（passlib）加盐，**不自研哈希**；无 bcrypt 依赖时 argon2-cffi 备选（5a L148 补白） | AU-02 |
| 首次设密 | 首次访问 → 强制跳设置页；≥8 位含字母数字，弱密码 400 拒绝（TC-17①） | AU-02 |
| 会话 | 随机 token（secrets.token_urlsafe(32)）+ 过期时间；**token 服务端维护**（内存/落盘会话表，重启可失效） | AU-03 |
| 互踢 | 会话表每用户单活：新登录顶掉旧 token（旧 token 操作 → 401），TC-18① | AU-03 |
| 防爆破 | 登录失败计数 5 次 → 锁 15 分钟 → 423（按 IP+账号双维度） | AU-04 |
| 公网安全 | 公网默认关闭（仅绑定 localhost/127.0.0.1，AU-01 家用模式）；手动开公网时强制 HTTPS 提示（内网穿透/反代自带），http 明文警告拒绝；CSP 头 + 渲染转义（XSS 转义函数全站统一）+ CSRF token（同源 + token 校验） | AU-05 |
| 权限语义 | 编辑器访问凭 `/编辑` 权限（机主/GM）；GM 身份经 permission_store（5b 已实现，runner.py:245-252）判定；**无 GM 权限 → 直接无视（不提示）**（ED-04）；登录会话绑定 gm 身份标记（机主=全功能 / GM=编辑功能） | AU-06 / ED-04 |
| 会话存储 | `web/security.py` 维护 `SessionTable`（token → {user, expiry, ip, role}），内存 dict + 可选落盘；重启清空（安全默认）【待定：是否持久化会话】 | AU-03 |

> 认证存储与 GM 权限存储（permission_store）**分离**：认证解决「谁能进编辑器」，权限解决「进编辑器能干什么」；web 层经依赖注入读 permission_store 判定角色（§6）。

### 2.4 依赖清单（requirements.txt 增补）

```
# ---- M12 Web 编辑器（运行时）----
fastapi==0.115.6          # 编辑器外壳 HTTP 框架（web/api.py 惰性 import 保持：不装也能 import 核心包）
uvicorn==0.32.1           # ASGI 服务器（systemd 托管子进程 / 插件子进程拉起）
passlib==1.7.4            # bcrypt 加盐哈希（不自研哈希，AU-02 补白）
bcrypt==4.2.1             # passlib 后端
python-multipart==0.0.20  # 表单/CSV 上传（TC-07）
# 测试隔离：web 路由测试 mock watcher/registry；核心层 pytest 不装 fastapi 仍可跑（api.py L17-23 惰性占位保持）
```

> 版本策略：锁版本号（规则 8）；fastapi 依赖保持 api.py 现有惰性 import 模式（api.py:17-23），核心层单测隔离（m12 摸底 风险 12）。

---

## 3. API 契约表（15 端点 · 冻结）

> 统一响应包络：`{"ok": true, "data": ...}` / `{"ok": false, "errors": [{"level": "red"|"yellow", "code": "...", "message": "<人话>", "field": "...", "value": ...}]}`（5a L183）。
> 认证要求：除 /api/auth/* 外全部需 `Authorization: Bearer <token>`；未认证 401，被互踢 401。
> 写端点一律 SV-06 原子写盘 + 统一触发热重载（§4）；>50ms 一律 asyncio.to_thread。
> page ∈ skill/job/monster/map/quest/shop/npc/checkin/ai/hidden/env_event/log_card（5a2 M-03 扩展）+ 部位/装备物品/掉落/公式数值（5a 作用域声明页）。

### 3.1 认证端点（4）

| # | Method | 路径 | 请求体 | 响应（data） | 错误码 | 认证 | 契约 |
|---|---|---|---|---|---|---|---|
| E01 | POST | /api/auth/setup | `{"password": str}` | `{"setup": true}` | 400 弱密码（<8 位或纯字母/纯数字）；409 已设密 | 无 | 5a L160 / TC-17 |
| E02 | POST | /api/auth/login | `{"password": str}` | `{"token": str, "expires_at": iso8601, "role": "owner"\|"gm"}` | 401 密码错；423 锁定（5 次错 15 分钟） | 无 | 5a L161 / TC-17② |
| E03 | POST | /api/auth/logout | — | `{"ok": true}` | — | Bearer | 5a L162 |
| E04 | GET | /api/auth/me | — | `{"authenticated": true, "role": "owner"\|"gm", "user": str}` | 401 未认证/被踢 | Bearer | 5a L163 / TC-18① |

### 3.2 元数据与引用端点（2）

| # | Method | 路径 | 请求体 | 响应（data） | 错误码 | 认证 | 契约 |
|---|---|---|---|---|---|---|---|
| E05 | GET | /api/meta/{page} | — | 字段元数据树（field_meta 正式表输出：字段名/中文名/类型/默认值/范围/引用目标/enum/children；P-07 唯一数据源） | 404 page 未登记或 enabled=false | Bearer | 5a L169 / 5a2 PR-03 |
| E06 | GET | /api/refs/{target} | `?q=&page=&size=` | `{"items": [{"id": str, "name": str}], "total": int, "page": int}`（registry.all_ids + resolve_name，O(1) 查表） | 404 target 未登记 | Bearer | 5a L170 / TC-06 |

### 3.3 页面 CRUD + 校验端点（6）

| # | Method | 路径 | 请求体 | 响应（data） | 错误码 | 认证 | 契约 |
|---|---|---|---|---|---|---|---|
| E07 | GET | /api/pages/{page} | `?page=&size=&q=&sort=` | `{"items": [{"id", "name", "summary"}], "total", "page", "size"}`（列表分页/搜索/排序；虚拟滚动数据源） | 404 page 未登记/禁用 | Bearer | 5a L176 / 5a2 PR-03 |
| E08 | GET | /api/pages/{page}/{id} | — | 条目全字段 + `_meta`: `{"version": int, "display_name": str}`（引用芯片渲染所需中文名由 E06 或本响应带出） | 404 条目不存在 | Bearer | 5a L177 |
| E09 | POST | /api/pages/{page} | 条目字段 JSON（无 id） | `{"id": "skill_0001", "entry": {...}}`（ID 自动生成 `类型_序号` 递增；创建即合法，字段缺失用默认值） | 422 字段结构错误（R-1/R-5 类） | Bearer | 5a L178 / TC-01 |
| E10 | PUT | /api/pages/{page}/{id} | `{"base_version": int, "entry": {...}}` | `{"id": str, "entry": {...}, "version": int+1}` | **409 版本冲突**（编辑锁：base_version ≠ 当前版本 → 提示「内容已被其他人修改」）；422 字段错误；404 | Bearer | 5a L179 / AU-06 |
| E11 | DELETE | /api/pages/{page}/{id} | — | `{"id": str, "cascade": {"removed_refs": [...]}}`（级联清理：删怪物→地图怪物表/掉落；删物品→掉落/商店/任务奖励；删地图→通道下拉；删职业→技能分配/转职；5a2 M-05 扩展 NPC→地图挂点/shop_refs/任务/教学；全部级联后校验器复查） | 404；422 级联后校验失败（整包回滚不落盘） | Bearer | 5a L180 / TC-03 |
| E12 | POST | /api/pages/{page}/validate | 草稿条目 JSON（不落盘） | `{"ok": bool, "errors": [...], "warnings": [...]}`（红/黄两级；**红黄皆 200** 供前端标红/标黄；红拦仅加载/热重载阶段生效，SV-02） | 404 | Bearer | 5a L181-183 / TC-09/10 |

### 3.4 热重载与数据包端点（3）

| # | Method | 路径 | 请求体 | 响应（data） | 错误码 | 认证 | 契约 |
|---|---|---|---|---|---|---|---|
| E13 | POST | /api/reload | — | `{"ok": bool, "changed_modules": [...], "warnings": [...], "errors": [...], "restored": bool, "paused": bool, "generation": int, "no_change": bool}`（复用 HotReloadWatcher.reload 同管线，ReloadResult 原样透出） | 422 红拦回退（body 带人话 errors） | Bearer | 5a L189 / TC-14 |
| E14 | GET | /api/packs | — | `{"packs": [{"pack_id", "name", "version", "active": bool, "enabled": bool}], "active_pack": str}`（扫描 content/ 目录枚举；单包框架） | — | Bearer | 5a L190 |
| E15 | PUT | /api/packs/active | `{"pack_id": str}` | `{"active_pack": str, "reload": {...}}`（切换启用包，即时生效；**单包约束** TRG-6 hot_reload.py:197） | 422 目标包校验失败/不存在 | Bearer | 5a L191 |

> **409 版本冲突语义（编辑锁，m12 摸底 风险 6）**：5a 附录 A 声明「编辑锁 UI 不实现」但 API 语义保留（L146/L179）；E10 的 409 是**并发冲突**（别人已保存新版本），不是校验拦截——与 SV-02「从不阻断保存」边界清晰：校验问题照常落盘（重载阶段红拦回退），版本冲突不落盘。写盘层维护版本号（§4.4）。

---

## 4. 数据流（保存链路）

### 4.1 端到端时序

```
前端 [保存] 或 30s 自动保存（P-08）
  │ ① 前端按元数据/引用集预检（SV-01 实时校验：标红/标黄，从不阻断保存 SV-02）
  ▼
E09/E10（POST/PUT /api/pages/...）
  │ ② 写盘层：序列化 JSON（ensure_ascii=False, indent=2）
  │ ③ 原子写盘：temp 文件 + os.replace rename（同目录 content/<pack_id>/，SV-06）
  │    单条写盘失败（磁盘满/权限）→ 回滚已写文件 + 人话报错（绝不半套）
  │ ④ 全部文件写完 → 统一触发一次重载（快路径：HotReloadWatcher.reload，同管线）
  ▼
热重载五段管线（hot_reload.py:305-412，已实现直接复用）
  │ ⑤ 通过 → 新 registry 生效（generation+1）→ QQ 新对局即用新数值（TC-13 ≤3s）
  │ ⑥ 红拦/异常 → 回退上一份校验通过快照（N=2）+ 人话提示（TC-14 服务不崩）
  ▼
响应前端：{"ok": true, "data": {...}} 或 {"ok": false, "errors": [...]}（人话文案）
```

### 4.2 原子写盘（write_service.py 新写，SV-06 核心缺口）

| 步骤 | 实现 |
|---|---|
| 临时文件 | `content/<pack_id>/.<file>.tmp-<pid>`（同目录！跨文件系统 rename 非原子，m12 摸底 风险 4） |
| 落盘 | `json.dumps(data, ensure_ascii=False, indent=2)` → temp 写入 → `os.replace(temp, target)` |
| 批量语义 | **一次保存可跨多文件**（级联删除 E11 会动地图/掉落/商店/任务多文件）：全部 temp 写完后逐个 replace；任一失败 → 反向回滚已 replace 的文件（从备份/重读原内容还原）→ 人话报错 |
| 版本号 | 写盘层维护 `base_version`：每文件条目保存次数递增；读取时从文件内容+元信息计算【待定：版本号落点——建议 manifest 外独立 `.editor_state.json` 隐藏文件，避免污染内容包校验】 |
| 快照 | 热重载回退已由 HotReloadWatcher 承担（hot_reload.py:141/352-380，SNAP-1~3）——**保存侧不另起校验逻辑**（m12 摸底 风险 5：两套语义漂移红线） |

### 4.3 前端草稿层

- 未保存内容跨页不丢失（P-08）：前端维护 `draftStore`（page → id → 草稿），30 秒定时 + 手动 [保存] 统一提交；`beforeunload` 关闭确认。
- Ctrl+Z 撤销栈（5a 附录 A 登记不实现 UI 细节；前端可做轻量历史栈【待定：M12 是否做，工作量与价值权衡】）。
- 校验反馈：保存前前端按元数据/引用集预检（SV-01），标红/标黄即时显示；后端 E12 权威校验兜底（红拦 5 类 R-1~R-5 与黄提示 Y-1~Y-8 全部由 validator 已实现引擎承担，前端只渲染）。

### 4.4 失败快照回退

- 回退主体 = HotReloadWatcher：`_reload_sync` 失败路径（hot_reload.py:352-380）已实现「快照当前 registry → 失败 → `Registry.from_snapshot(pre)` 恢复 + 人话」。
- 编辑器保存 → reload 返回 `restored: true` → 前端提示「配置有问题，已回退到上一版」+ 展示 errors 明细（红/黄清单，人话由 errors.py 唯一文案源翻译）。
- 连续失败 ≥3 → watcher 自动暂停轮询（BLK-5，hot_reload.py:363-367），编辑器保存同样受该保护（不空转）。

---

## 5. 元数据驱动表单引擎

### 5.1 FieldMeta 正式表注入（P-07）

现状（m12 摸底 三）：field_meta.py 781 行缺省表已覆盖 24 模块，docstring 自注「正式表在编辑器里程碑注入」（field_meta.py:23-24）；FieldMeta dataclass（models.py:118-144）**无中文名/描述字段**。

正式表注入清单：

| # | 注入项 | 做法 | 契约/现状 |
|---|---|---|---|
| 1 | FieldMeta 补字段 | models.py FieldMeta 追加 `label: str = ""`（中文名）、`desc: str = ""`（描述，参照 fishing_editor_service E-2 的 desc 补白模式，但正式表原生携带）；**dataclass 加字段带默认值，向后兼容**（m12 摸底 风险 10） | P-07 四要素+中文名 |
| 2 | 六页字段级元数据 | skill/job 两页模块整体缺失（6a/6b 未接线）：M12 需确认是否补最小登记（skills.json/jobs.json ModuleMeta+namespace skill_lib/job_lib）还是依赖后续里程碑【待定，m12 摸底 风险 11】；quest/shop/npc/checkin 四页 fields={} 专项全权（field_meta.py:737-740）→ 注入字段级元数据供表单渲染（校验仍走专项 validate_*） | 5a P-06 / 5a2 M-01 |
| 3 | enemies AI 段 | 补 ai.states/intent、phases、zone_change/teach_map/pressure 三组键（PA-03/04/06 缺口） | 5a2 PA-03/04/06 |
| 4 | settings 段 | 补 env_event 段（PE-01~04 载体）+ log_card 段（PL-01~04：容量/传记段数可配化，现状传记段数 50 是代码常量 log_commands.py:124） | 5a2 PE/PL |
| 5 | 命名空间/映射 | page_id → meta_source → 模块文件的映射表由 editor.json 承载（§5.3），不再散落代码 | 5a2 M-06 |

### 5.2 前端表单渲染器（C-01~C-07 映射）

```
/api/meta/{page} 返回元数据树
  → renderField(meta, value, path) 按 meta.type 分派：
      str→C-01 / int|number→C-02 / enum→C-03 select / bool→C-03 开关
      / range 类（range_min/max 齐备且数值型）→C-04 / ref→C-05 芯片+抽屉
      / list→C-06 行表 / obj→C-06 递归卡片 / map→C-06 键值行表 / formula→C-07
  → 校验徽标：required 空→红；负数→红（R-2）；越界→黄（Y-1）；概率→黄（Y-2）；
    zero_unlimited→黄提示「0=不限」（Y-4）；soft_label→永不红（Y-5）
  → 引用芯片：E06 预取名称映射 → 显示中文名；悬空→红标（R-4）
```

- 渲染器**零页面特判**：tabs 分页只是字段分组（meta_source 输出带 tab 归属【待定：tab 归属由 editor.json tabs 顺序 + 字段分组声明，或由各页 meta 表注入 section 字段】）。
- 事件名下拉（5a2 PR-06）：条件表单 `[事件:xxx]` 选项 = 预置 6 事件键空间（condition_engine.py:177-181）+ 内容包扩展登记动态枚举；未登记 → 黄提示「这个事件还没登记，会恒为 0 哦」。
- 互译显示（TC-08）：条件表单显示中文变量键，存储/校验用英文条件键（键空间注册表 condition_engine.py:125/706 已实现，前端做双向翻译面板）。

### 5.3 editor.json 注册表（5a2 PR-01 ~ PR-06）

结构与解析（editor.json 与 skills.json 同层，缺失 → 按 5a 六页默认值启动，M-06 向后兼容）：

```json
{
  "schema_version": 1,
  "pages": [
    {"page_id": "skill", "title": "技能", "icon": "⚔", "module_file": "skills.json",
     "meta_source": "meta/skill", "enabled": true, "validator": "skill"},
    {"page_id": "ai", "title": "AI", "icon": "🤖", "module_file": "enemies.json",
     "meta_source": "meta/ai", "enabled": true, "validator": "ai",
     "extends": "monster", "tabs": ["行动表", "条件行动", "状态机", "阶段", "连招链", "换区"]}
  ]
}
```

| 键 | 语义 | 消费方 |
|---|---|---|
| page_id | API 枚举（/api/pages/{page} 白名单） | 路由（E05/E07 404 判定） |
| title / icon | 侧边栏中文名/图标 | 前端侧边栏渲染（P-04/P-05） |
| module_file | 模块 JSON 文件 | 写盘层（§4）、读列表 |
| meta_source | 字段元数据表引用 | /api/meta/{page} 数据源（P-07） |
| tabs[] | 子标签页 | 前端 tab 栏 + 字段分组 |
| enabled | 启停：false → 侧边栏不渲染、/api/pages 404、不纳入编辑器校验（**引擎侧加载不受影响**） | 前端 + 路由 + 校验钩子映射（PR-03） |
| extends | 挂载进既有页（ai→monster / hidden→maps） | 前端 tab 挂载 + 路由归口 |
| validator | 校验器钩子名 → validate_{钩子} 专项（PR-05；钩子已存在：validate_npcs/validate_shops/validate_quests/validate_checkins/validate_enemies/validate_fishing…，只缺映射表） | E12 validate / 保存后重载全量校验 |

- editor.json 自身纳入 mtime 增量监控（PR-04）：HotReloadWatcher._current_declared（hot_reload.py:271-284）按 manifest 声明监控——需要把 editor.json 并入监控集【待定：实现上建议 manifest 声明列表追加 editor 键，或 watcher 固定监控 editor.json】。
- 注册表解析放 `web/editor_registry.py`（零 NoneBot，纯解析），缓存 + 增量重读。

---

## 6. G0 分层与依赖注入

### 6.1 依赖方向

```
              ┌─────────────────────────────────────────────┐
              │ web/（编辑器外壳：api + routes + security）   │
              │   └→ content（field_meta/hot_reload/loader/  │
              │             registry/editor_registry）       │
              │   └→ core（event_bus 只读、试玩占位）          │
              │   └→ storage（repo 鸭子类型，经注入）          │
              │   └→ data（types/logging）                   │
              └─────────────────────────────────────────────┘
                    ▲ 依赖注入（装配层 runner/bootstrap 注入）
                    │
              assembly/（runner/bootstrap：唯一知道全部接线的地方）
```

铁律（3a D-05 / m12 摸底 风险 1）：
1. web 只依赖 {content, core, storage, data}，任何层不得反向依赖 web；
2. **web 不 import commands**（指令壳层）：/api/reload 复用 GmBackend.reload_content（gm_commands.py:449-483）时**不能反向引 commands**——把 watcher 操作下沉：web 直接持有 `HotReloadWatcher` 实例调 `watcher.reload()`（同管线），GmBackend 的 reload_content 与 web 端点**各自持有 watcher 引用**，命令层翻译文案、web 层透出 ReloadResult 结构化数据，互不依赖；
3. editor/ 服务层保持零 NoneBot（fishing_editor_service.py:63-64 铁律示范）；
4. `web/api.py` 保持 fastapi 惰性 import（api.py:17-23），核心层 pytest 不装 fastapi 仍可跑（m12 摸底 风险 12）。

### 6.2 依赖注入（watcher / registry / 认证存储）

`create_app(state)` 接收注入的 state（沿用骨架签名 api.py:28）：

```python
# 装配层（runner/bootstrap 侧）构造：
state = {
  "pack_dir": Path("content/test_demo"),
  "watcher": HotReloadWatcher(pack_dir, meta=正式表),   # 已装配实例（含轮询调度）
  "meta": default_field_meta_table(),                    # 正式表实例
  "permission_store": deps.permission_store,             # GM 权限（5b 已实现）
  "repo": deps.repo,                                      # storage 鸭子类型
  "auth_store": AuthStore(...),                           # 会话/防爆破/密码（web/security.py）
  "settings": {...},                                      # 绑定地址/公网开关/端口
}
app = create_app(state)   # web 侧纯消费注入，零 import 装配层
```

- 测试隔离：web 路由测试 mock watcher/registry（传替身 state），零 NoneBot、零真实装配。
- 认证存储与权限存储分离（§2.3）；机主判定 = 配置的 owner（GM 权限三级 admin/manager/player，gm_commands.py:24-36 已实现）。

### 6.3 循环 import 防法（schema 之家单向持有）

- field_meta ↔ 专项 models 禁止双向 import（G0 TC-03 静态 import 图铁律）：正式表注入新增模块（skill/job/ai/hidden/env_event/log_card 元数据）必须沿用 field_meta.py:34-40/627-627 确立的「schema 之家单向持有」模式——字段定义归 field_meta（或自包含持有模块），专项校验器单向 import field_meta，**禁止函数级 import 成环**（field_meta.py:229-230 注释明确）。
- web 层 import 方向单一（§6.1），editor_registry/write_service/security 均零 NoneBot 零 commands。

---

## 7. 实施步骤（6 步，每步验收点）

| 步 | 内容 | 主要产出 | 验收点 |
|---|---|---|---|
| S1 | 骨架与依赖 | requirements 增补 fastapi/uvicorn/passlib；`create_app`/`iter_routes` 实装（路由注册 + 静态页挂载 + 健康检查）；launcher 装配（注入 watcher/registry/permission_store）；8080 监听 | ✅ `GET /` 返回编辑器页；`GET /api/auth/me` 401 未认证；核心层 pytest 不装 fastapi 仍全绿（m12 摸底 风险 12） |
| S2 | 认证 | web/security.py：bcrypt 哈希、首次设密、token 会话、互踢、5 次锁 15 分钟、CSP/CSRF 中间件、公网默认关 | ✅ TC-17（弱密码 400/5 次锁 423）；TC-18①（互踢 401）②（明文警告）③（XSS 转义 + CSP 头）；无权限访问编辑器 → 直接无视（ED-04） |
| S3 | 元数据正式表 + 列表/表单 | FieldMeta 补 label/desc；skill/job 登记裁决【待定】；enemies AI 段 + settings env_event/log_card 段注入；editor.json 注册表解析；E05/E06/E07/E08/E09/E10 六端点；前端列表+表单渲染器（C-01~C-07 最小版） | ✅ TC-01（技能页表单新建 skill_0001 零 JSON）；TC-02（六页同布局 CRUD）；TC-04（引用芯片改名联动）；TC-06（底部抽屉搜索分页） |
| S4 | 保存链路 + 引用回收站 | write_service（原子写盘 temp+rename + 版本号 + 批量回滚）；保存 → watcher.reload 统一触发；E10 409 编辑锁；E12 validate 草稿校验；前端标红/标黄/30s 自动保存 | ✅ TC-09（红拦 5 类逐类）；TC-10（黄提示不拦截）；TC-11（从不阻断保存：红拦仍写盘+重载回退）；TC-13（保存即生效 ≤3s）；TC-14（原子写与非法 JSON 回退不崩）；TC-15（增量重载） |
| S5 | 级联删除 + 扩展页 | E11 级联清理（5a 四类 + 5a2 M-05 三类扩展）；E13/E14/E15 三端点；5a2 十三新页表单（NPC 10 标签/签到 7 区/AI 6 子页/隐藏 3 子页/环境事件/日志卡片）；未使用角标/总量面板 | ✅ TC-03（级联删除复查无悬空）；5a2 TC-01~09（新页 CRUD/repair 置灰/断签模拟/隐藏可达性黄提示/editor.json 启停 404）；TC-16（进行中对局持旧快照） |
| S6 | 打磨 | 前端虚拟滚动/搜索排序筛选批量；CSV 导入导出（TC-07 钓鱼域复用 + 通用六页 CSV【待定：通用 CSV 是否本里程碑】）；E14/E15 数据包管理 UI；人话文案禁词核验（TC-12）；试玩占位（5a 附录 A） | ✅ TC-07（CSV 第 N 行人话）；TC-08（互译显示）；TC-12（禁词审计）；TC-18 全链路；全量回归 |

> 依赖关系：S1→S2→S3→S4→S5→S6 串行依赖（认证是列表表单前置，保存链路是级联前置）；S3 内六页表单与 editor.json 可并行；S5 扩展页表单复用 S3 渲染器零新增控件（5a2 M-04）。

---

## 8. 前端规模控制（最小可用壳先行）

> m12 摸底 风险 13：六页壳 33 规则中 P-01~P-08/C-01~C-07 全是前端交互规格，**全量实现前端工作量最大**；本方案采用「最小可用壳 → 迭代扩展」路线。

### 8.1 最小可用壳（M12 必达）

| 模块 | 最小实现 | 砍掉（后置） |
|---|---|---|
| 布局 | 顶栏 + 侧边栏 + 左列表右卡片（P-01~P-05 静态骨架） | 虚拟滚动（先用分页）；拖拽排序（先用上下移按钮） |
| 列表 | 固定表格 + 内部滚动 + 点击行 → 右侧卡片 + 搜索框 + 分页 | 排序/筛选/批量操作（P-08 后置） |
| 表单 | C-01 text / C-02 number / C-03 select / C-05 芯片+抽屉 / C-06 子表（表格+行增删） | C-04 range（先用 number 替代）；C-07 formula（先用 textarea + 长度软提示）；C-06 拖拽排序 |
| 校验 | 保存后 E12/热重载结果红黄清单展示 | 前端实时标红（先做保存后反馈） |
| 引用 | E06 名称映射 + 芯片显示中文名 + 悬空红标 | 跨页引用跳转定位（P-08 后置） |

### 8.2 迭代扩展路线

| 阶段 | 内容 | 触发条件 |
|---|---|---|
| 壳 v0.1 | 表格 + 表单 + 抽屉（8.1 最小壳）+ 认证 + 六页 CRUD + 保存链路 | M12 S1~S4 完成即交付可用 |
| 壳 v0.2 | C-04 range / C-07 formula 增强控件；实时标红/标黄；30s 自动保存；撤销栈【待定】 | v0.1 实测稳定后 |
| 壳 v0.3 | 虚拟滚动/排序筛选批量；CSV；跨页引用跳转；数据包管理 UI 完善 | 扩展页（5a2）上线后按需 |
| 壳 v0.4 | 试玩/模拟器（5a 附录 A 独立能力）；AI 设置页（OpenAI BYOK，不实现） | 独立里程碑另行细化 |

### 8.3 工作量预估（相对）

| 模块 | 占比 | 说明 |
|---|---|---|
| 前端（布局+渲染器+交互） | ~40% | 最大头；最小壳砍半后 ~20% |
| 后端（15 端点 + 认证 + 写盘） | ~35% | 大部分复用已就绪引擎（validator/registry/hot_reload） |
| 元数据正式表注入 | ~15% | 补字段/补段，机械但量大 |
| 装配与测试 | ~10% | mock watcher/registry；TC 逐条回归 |

---

## 附录 A：风险与对策（对齐 m12 摸底 第六节 15 条）

| # | 风险 | 对策（本方案落点） |
|---|---|---|
| 1 | G0 分层 web 依赖方向 | §6.1：web 直接持有 watcher，不反向 import commands |
| 2 | 循环 import | §6.3：schema 之家单向持有模式；正式表注入沿用 |
| 3 | 认证安全 | §2.3：bcrypt 加盐、token 服务端维护、互踢、5 次锁、公网默认关、CSP/CSRF、渲染转义 |
| 4 | 原子写盘 | §4.2：temp+rename 同目录；全部写完统一重载；失败回滚已写文件 |
| 5 | 快照回退同管线 | §4.1/4.4：保存 → watcher.reload 同一条管线，不另起校验 |
| 6 | 编辑锁 base_version 409 | §3.3 E10 + §4.4：409 并发冲突 ≠ 校验拦截，边界清晰 |
| 7 | 单包框架限制 | §3.4 E14/E15：单包语义 TRG-6；/api/packs 扫描 content/ 目录 |
| 8 | event 键前缀收口 | EV-02 键名差异（event_bus.py:150）：**收口前先对齐契约与实现**，避免改坏条件求值（condition_engine.py:601）——本方案不涉及运行引擎改动，仅登记【待定：收口另立小任务】 |
| 9 | 木桩特判 | EV-06 tier:training 不计：M12 补特判前先 grep 测试断言（m12_启动包 L128） |
| 10 | field_meta 表结构扩展 | §5.1：FieldMeta dataclass 加字段带默认值向后兼容；正式表原生携带 label/desc |
| 11 | 技能/职业页未接线 | §5.1 注入项 2：M12 内补最小登记 or 依赖 6a/6b【待定】 |
| 12 | fastapi 依赖与测试隔离 | §2.4：惰性 import 保持；web 测试 mock watcher/registry |
| 13 | 前端规模 | §8：最小可用壳（表格+表单+抽屉）先行，迭代扩展 |
| 14 | 级联删除跨模块写盘 | §4.2 + §3.3 E11：与原子写盘联动（整包一次写完再重载）+ validator 复查；forge_cascade.py 仅参考模式不照搬 |
| 15 | /商店 列表 收口 | SM-04 余额行 + SM-06 紧凑格式 + 帮助组登记：独立小任务，遵守「壳层只渲染、引擎给数据」边界（shop_commands.py L21-23） |

## 附录 B：【待定】清单汇总

1. skill/job 两页引擎侧最小登记（6a/6b 依赖）——M12 内补 or 后续里程碑（§5.1 注入项 2）
2. 版本号（base_version）落点——建议独立 `.editor_state.json` 隐藏文件（§4.2）
3. 会话是否持久化（重启后 token 失效 or 恢复）（§2.3）
4. tab 归属字段分组声明方式（§5.2）
5. editor.json 纳入热重载监控的接入方式（§5.3 PR-04）
6. 通用六页 CSV 导入导出是否本里程碑（§7 S6）
7. 前端撤销栈 Ctrl+Z 是否 M12 做（§4.3 / 8.2）
8. web/launcher_hint.py 新建（3a L152 登记但文件不存在）（§2.2）
9. EV-02 计数键前缀 event_count: 收口（运行引擎改动，另立小任务）（附录 A #8）
