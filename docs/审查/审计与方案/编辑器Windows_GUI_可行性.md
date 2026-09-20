# 可行性评估：把内容编辑器做成「Windows 桌面 GUI 应用」麻不麻烦？

> 状态：**已完成**（2026-09-20）；骨架先行、逐节写回。
> 纪律：**只读仓库**，除本报告外不改仓库任何文件；每条结论带 `file:line` 或「命令 + 输出摘要」；不写实现代码。
> 取证环境：`/root/QBot-TurnTellerRPG`（本机即那台服务器，见 `/root/deliverables/编辑器部署_方案.md` §一）。
> 关联既有文档（不重复、不冲突）：`docs/编辑器重写_需求与约束.md`、`docs/编辑器重写_实现方案.md`、
> `/root/deliverables/编辑器部署_方案.md`（已有"systemd 常驻 + 一键隧道"方案）。

---

## 〇、一句话结论（先看这一节）

**麻烦——但要看你说的"桌面应用"是哪一档。**

| 你想要的 | 结论 | 等级 | 工作量量级（估算） |
|---|---|---|---|
| **A. 双击图标就能用**（不想开隧道、不想记命令，**接受仍要联网、仍改服务器上的包**） | **不麻烦** | **简单** | **0.5–1 人日**（甚至已有现成方案，见下） |
| **B. 一个真正的 Windows 窗口程序**（有自己的窗口/图标/不用浏览器，数据仍在服务器） | 略麻烦 | **中等** | 4–10 人日（含 Windows 打包/签名） |
| **C. 离线也能编辑**（本地存一份内容包，改完同步回服务器） | **麻烦** | **复杂** | 15–30 人日，且之后要长期维护"谁是权威副本" |
| **D. 不需要服务器**（前端直接读写本地 JSON 文件） | **很麻烦，且不建议** | **复杂** | 40+ 人日，并会推翻现有校验/备份/回退原则 |

**最省事的路线（明确推荐）＝ A**：不做窗口程序，只做一个**桌面双击的启动器**（`.bat` 或单文件 `.exe`），它替用户干两件事：
① 起 SSH 隧道（复用**已经交付给用户**的免密私钥）；② 用系统默认浏览器打开 `http://127.0.0.1:8090`。

> **重要（避免重复劳动）**：这条路线**不是新提案**，`/root/deliverables/编辑器部署_方案.md` §三 Step 4 已经写好了
> `编辑器隧道.bat` 全文和"压缩包 + 放哪里"的交付方式，§〇 也把"双击图标"定为 ★首选。
> 本次评估相对那份方案的**唯一增量**是：把 `.bat` 包成 `.exe`（可选，见 §五 第 1 步）。

**再强调一句**：做成"桌面 GUI"这件事本身不难（前端零 CDN、后端纯 Python、无 Node 依赖，壳起来很轻）；
**难的是"把数据从服务器搬到本地"**——而这件事恰恰是用户没要求的。所以别做 C/D，做 A。

---

## 一、事实基线（只读取证）

### 1.1 前端：一个 7871 行的单文件、零构建、零 CDN

| 核查项 | 命令 / 位置 | 输出摘要 | 对"做桌面应用"的含义 |
|---|---|---|---|
| 规模 | `wc -l qbot_rpg/web/static/index.html` | `7871`；`ls` 显示 385090 字节 | 一个文件，无模块拆分 |
| 唯一外部资源 | `grep -n '<script src\|<link rel' index.html` | **只有** `index.html:7` → `<link rel="stylesheet" href="/static/tokens.css">`（12994 字节） | **零 CDN**；离线也渲染 |
| JS 加载方式 | `grep -n '<script' index.html` | `index.html:8`、`index.html:1211` 两处**内联** `<script>`（无 `src`） | 无打包器、无 `import`/`require`（`grep -c` = **0**） |
| Node 依赖 | `ls package.json node_modules` | `No such file or directory` ×2 | **不需要 Node/npm**；前端不是"前端工程" |
| 后端调用点 | `grep -c 'fetch(' ` = **7**；`api(` = **14**、`postJSON(` = **10** | 约 **24 处**业务调用，全部经 `api()/postJSON()` 两个助手（`index.html:3021`、`3030`） | 调用面收敛，易替换基址 |
| 基址怎么写 | `grep -n 'API_BASE\|location.origin\|window.location' index.html` | **无任何匹配**；路径全是根绝对字符串 `"/api/pack/" + …`（如 `index.html:3357, 3394, 3980, 4785, 7611, 7645`） | **关键**：页面 origin 一变，路径就失效 → 壳必须让页面仍从后端 origin 加载，或注入基址 |
| 浏览器 API | `localStorage`（`115`、`3447`）、`indexedDB`（`3598`、`3601`）、`FileReader`（`3696`）、`input.files`（`7586, 7640, 7715, 7751`）、`URL.createObjectURL`（`7602`） | 都是**普通 Web 能力**，Chromium/WebView2 全支持 | 换壳不改代码 |
| 安全上下文 API | `grep -n 'crypto\.' index.html` | **0 处**（与 `/root/deliverables/编辑器部署_方案.md` §1.5 复核一致） | 不怕 `crypto.randomUUID` 类坑 |
| 下载文件 | `downloadBlob()` `index.html:7601-7608`（`<a download>` + `createObjectURL`） | 导出 `.ttrpack` / CSV 走**浏览器下载** | 壳里要处理"下载落盘"行为（WebView 需给下载目录） |

**小结**：前端几乎是为"被打包"而生的——单文件、零构建、零外部依赖。**壳的难点不在前端，在数据侧。**

### 1.2 后端：315 行宿主 + 约 1.18 万行服务端逻辑，且**必须能写内容目录**

| 核查项 | 命令 / 位置 | 输出摘要 |
|---|---|---|
| 宿主规模 | `wc -l scripts/editor_host.py` | `315` 行 |
| 路由数 | `grep -c '@app\.' scripts/editor_host.py` | **32** 个（会话/包/模块/条目/引用/索引/校验/保存/删除/备份/回退/导出/导入/CSV/静态页） |
| 宿主职责 | `editor_host.py:4-6` | 「只做 HTTP 宿主 —— 起 FastAPI/uvicorn、托管静态页、把 `qbot_rpg/web/api.py`…暴露为 JSON API」，**零 NoneBot import** |
| 依赖包 | `editor_host.py:29-32` | `uvicorn`、`fastapi`（`Body/FastAPI/Request`、`FileResponse/JSONResponse/Response`、`StaticFiles`） |
| 写权限 | `atomic_store.py:246-248` `write_modules(content_dir, …)`；`editor_host.py:17`「落盘一律经 editor_ops → atomic_store」 | **必须对内容目录有写权限**（沙箱/只读盘直接不可用） |
| 保存链路 | `editor_ops.py:6`、`512`、`610` | 顺序固定：**校验通过才落盘 → 先备份 `.bak` → 原子写 → 回读复核** |
| 校验入口 | `editor_ops.py:12`、`40` → `qbot_rpg/content/validator.py:3663 check_pack` | **唯一校验入口**，`validator.py` 共 3723 行 |
| 备份/回退 | `editor_ops.py:8-9`、`editor_host.py:183-193` | `/backup` 看状态、`/rollback` 从 `.bak` 原子恢复；另有 manifest 级 `/manifest/backup|rollback` |
| 权限位 | `editor_ops.py:112-115` `require_edit` → `Forbidden(403)`；`editor_host.py:15-16`「批2 **不做登录页**」 | 只有 `owner`/`gm` 两种角色，**无认证**；写权限靠 `--role` 启动参数 |
| 服务端逻辑量级 | `wc -l` 六文件合计 | `api.py 4345` + `editor_ops.py 1376` + `csv_ops.py 537` + `validator.py 3723` + `atomic_store.py 875` + `pack_transfer.py 905` = **11761 行** |
| 内容包位置 | `api.py:146-150` `content_root()`：默认 **`<仓库根>/content`**（不是 CWD） | 服务器上现有 **10 个包**（`ls content/`：`veinborn`、`zz_craft_demo`、`demo_*`×5、`test_demo`、`zz_probe_*`×2） |

### 1.3 打包前提：**纯 Python，但没有任何现成打包工具**

| 核查项 | 命令 / 位置 | 输出摘要 |
|---|---|---|
| Python（仓库 venv） | `.venv/bin/python --version` | **Python 3.14.7**（部署方案 §1.2 记服务器同源） |
| Python（系统） | `python3 --version` | 3.11.15（部署方案另记服务器系统 `python3` 是 **3.8.10**，故必须用 `.venv`） |
| 依赖清单 | `wc -l requirements.txt` = **23 行**；通读全文 | 运行时就 4 个：`aiosqlite`、`pypinyin`（可选）、`fastapi==0.115.14`、`uvicorn==0.34.3`；其余是 dev（pytest/ruff/mypy/coverage） |
| 打包工具 | `grep -in 'pyinstaller\|nuitka\|pywebview\|briefcase\|electron' requirements.txt pyproject.toml` | **无任何匹配** → 打包工具**要新增**（新依赖、新构建链） |
| 是否有二进制依赖 | `.venv/.../site-packages/*.so` | 只有 `...__mypyc.cpython-314-*.so`（mypy 自带的编译产物，**运行时不需要**）；`fastapi/uvicorn/pypinyin/aiosqlite` 均为纯 Python 包 | 理论适合 PyInstaller/Nuitka |
| 关键运行链是否碰 NoneBot | `grep -rn 'nonebot\|NoneBot' qbot_rpg/web/*.py scripts/editor_host.py` | 仅出现在注释里的"零 NoneBot import"铁律；**无实际依赖** | 打包**不必**带 NoneBot 全家桶（这是好消息） |
| 项目体积 | `du -sh . .git .venv tests .mypy_cache qbot_rpg content docs` | 仓库 **490M**（其中 `.git` 99M、`.venv` 282M、`tests` 38M、`.mypy_cache` 27M、`qbot_rpg` 25M、`docs` 9.3M、`content` **1.4M**） | 内容包本体只 1.4M；大的是 venv/缓存/测试——打包**只需挑运行必需文件** |

### 1.4 「数据在服务器上」这条硬约束（决定一切）

- 编辑器读写的是**服务器**上的 `content/<包>/*.json`（`editor_host.py` 全文以 `content_root` 为根；§1.2 写权限证据）。
- 打包 / 校验 / 备份 / 回退 / 迁移门禁**全在服务端**：
  - 校验 `check_pack`（`validator.py:3663`，3723 行）；
  - 备份 / 回退 `backup_modules` / `restore_modules_from_backup`（`atomic_store.py:402, 438`）；
  - 打包传输 `.ttrpack`（`pack_transfer.py`，905 行，含 sha256 完整性、Zip Slip 防护、`max_archive_bytes = 64MB`（`pack_transfer.py:80`）、"过现有校验器才落盘"、覆盖前自动备份）——契约见 `docs/编辑器重写_需求与约束.md` 〇·补五（第 120-142 行）。
  - 迁移门禁：`scripts/compare_field_meta_migration.py`（`docs/编辑器重写_实现方案.md:690`、`docs/编辑器修改意见0915_台账与方案.md:175`）。
- 因此：**任何"本地 GUI"方案的第一道题不是 UI，而是"数据怎么到本地、改完怎么回去、谁说了算"。** 这一条贯穿 §二 三条路线。

> 补充事实：编辑器**零鉴权**（`editor_host.py:15-16`；部署方案 §1.5 逐条取证），安全边界 100% 依赖
> "只监听 `127.0.0.1` + SSH 隧道"（`scripts/editor_start.sh` 安全提示、`docs/编辑器使用说明.md:55-65`）。
> 这直接决定：**"桌面壳直连公网后端"这条变体会引入一个现在不存在的新风险面。**

---

## 二、三条候选路线对比

### 2.0 同表对比

| 维度 | **路线 1 · 网页壳**（仍连远程后端） | **路线 2 · 本地全栈**（离线编辑 + 同步） | **路线 3 · 纯静态前端 + 本地文件直读** |
|---|---|---|---|
| 技术栈 | Python + **pywebview**（Windows 走 WebView2/Edge 内核）或 Electron/Tauri | Python 全栈打包（PyInstaller/Nuitka：fastapi + uvicorn + `.venv` 那套）+ 本地内容包副本 | 纯 `index.html` + **File System Access API**（Chromium 专有） |
| 用户拿到什么 | 一个带图标的窗口（或**干脆只有浏览器 + 一个启动器**），**仍需联网** | 一个能离线打开的 `.exe`，本地有自己的一份内容包 | 一个便携工具，直接打开本地文件夹里的 JSON |
| **数据怎么到本地** | **不到本地**——改的仍是服务器上的包 | ① `.ttrpack` 导出/导入（**已有**：`pack_transfer.py`）② scp/sftp 整包同步 ③ git 拉推 | 直接读写本地文件，无"同步"概念（也就无权威副本） |
| 工作量（**估算**，非实测） | **1a 最轻变体 0.5–1 人日**；1b 真窗口 4–10 人日 | **15–30 人日** + 长期维护 | **40+ 人日**，且要推翻既有原则 |
| 主要风险 | 窗口壳的下载/权限/证书细节；WebView2 运行时的 Windows 版本差异 | **双写冲突、副本漂移**；备份/回退/校验语义两侧不一致；打包体积与杀软误报（待实测） | 与"元数据驱动 + 唯一校验入口 + 备份回退 + 迁移门禁"**正面冲突**；JS 重写 11761 行 Python 逻辑 |
| 是否需要服务器 | **必须**（且服务器要保持常驻，见部署方案 §三） | 需要（同步目标），离线期间不需要 | 不需要（代价 = 丢掉服务端全部能力） |
| 是否引入新安全面 | 1a **不引入**（复用 SSH 隧道）；"壳直连公网后端"变体**会引入**（见难点 ⑤） | 引入（私钥/凭据在客户端 + 同步通道） | 不引入网络面，但引入"本地文件可被任意脚本改"的完整性风险 |

### 2.1 路线 1 · 网页壳（仍连远程后端）

**两种做法，成本差 10 倍：**

- **1a. 最轻变体（推荐）：不做窗口，只做"免命令启动器"。**
  双击 → `ssh -N -L 8090:127.0.0.1:8090 -i <私钥> root@<服务器>` → `start http://127.0.0.1:8090`。
  - **这条已经存在**：`/root/deliverables/编辑器部署_方案.md` §三 Step 4 给出了 `编辑器隧道.bat` **全文**，
    §〇 已把"双击一个图标"定为 ★首选方案，私钥也已交付（`/root/deliverables/id_ed25519_服务器免密私钥.txt`、
    `免密登录_使用说明.md`）。
  - 本次增量：把 `.bat` 换成**单文件 `.exe`**（内嵌脚本 + 图标），或干脆保留 `.bat`（0 人日）。
  - 代价：仍会弹一个黑窗口（不能关）+ 仍要开浏览器（**这其实不是"桌面 GUI 应用"**，但完全满足"不想开隧道/不想记命令"）。
- **1b. 真窗口壳：pywebview + WebView2。**
  一个 Python 进程做三件事：拉起 SSH 隧道（`paramiko` 或调系统 `ssh.exe`）→ 等端口就绪 → `webview.create_window()`
  加载 `http://127.0.0.1:8090`。**前端一行不用改**——因为页面仍从后端 origin 加载，`/api/...` 根绝对路径继续有效（§1.1 证据）。
  - **为什么不是 Electron**：Electron 要 Node 工具链，而本仓库**没有任何 Node 依赖**（§1.1）；引入 Node 只为包一个已存在的页面，纯亏。
  - **为什么不是 Tauri**：要 Rust 工具链 + MSVC 构建环境，对"非技术用户交付"没有额外好处。
  - 代价：需要 WebView2 运行时（Win11 自带；Win10/Server 视版本而定，**需在目标机上实测**）；
    打包后是**一个 exe + 一个私钥文件**。

### 2.2 路线 2 · 本地全栈（离线编辑 + 同步回服务器）

- **技术栈**：把 `scripts/editor_host.py` + `qbot_rpg/web/*` + `qbot_rpg/content/*` 用 PyInstaller/Nuitka 打成 Windows exe，
  本地起 `127.0.0.1:8090`，`--content-root` 指向**用户机器上的一份 content 副本**；壳再套 WebView。
- **用户拿到什么**：能离线编辑的窗口程序（"像本地软件"）。
- **数据怎么到本地**（三条可选，各有代价）：
  1. **`.ttrpack` 导出/导入（现成能力，最省事）**：服务器导出 → 传到本地 → 本地导入；改完反向再来一次。
     好处：`pack_transfer.py` 已实现 sha256 完整性、Zip Slip 防护、**过校验器才落盘**、覆盖前自动备份、
     导入需 owner（`docs/编辑器重写_需求与约束.md:120-142`）。坏处：**整包往返**，不是增量；每次都要"选文件 → 导入"，
     对非技术用户并不比隧道简单。
  2. **scp/sftp 整包同步**：脚本化，但"哪边新"要自己判断，容易覆盖掉对方的改动。
  3. **git**：有版本与冲突检测，但要求用户机器装 git、会处理冲突——**对非技术用户直接出局**。
- **工作量**：15–30 人日（打包链 3–5 + 同步语义 5–10 + 冲突/回退/UI 提示 5–10 + Windows 联调/杀软 2–5）。
  **估算依据**：需要新写的不是 UI（UI 现成），而是**"双副本一致性"**这整套——现有代码里**没有**任何相关实现。
- **风险**：① **权威副本歧义**：服务器上还有打包/校验/备份/回退/迁移门禁，本地副本改完回灌时，
  服务端的 `.bak` 回退语义与本地副本对不上；② 双写冲突（用户 A 本地改、服务器上被 B 改）；
  ③ 打包体积与杀软误报（**未实测**，实施时必须验证）。
- **是否需要服务器**：需要（作为同步目标），但离线期间不联网。

### 2.3 路线 3 · 纯静态前端 + 本地文件系统直读

- **设想**：把 `index.html` 改成用 File System Access API（`showDirectoryPicker`）直接读写用户选的 `content/<包>/*.json`，**去掉后端**。
- **与既有原则的兼容性评估（这是本节重点）＝ 不兼容**：
  1. **元数据驱动仍能活着**：前端本来就是读 `manifest.modules` + 字段元数据渲染（`docs/编辑器重写_需求与约束.md:7-19` 第〇节），
     这部分在 JS 里读 JSON 即可；**这一条不是障碍**。
  2. **校验 → 必须重写**：唯一校验入口是 Python 的 `check_pack`（`validator.py:3663`，3723 行）。
     JS 侧要么重写一遍（**双实现 = 必然漂移**），要么放弃校验（**红线**）。
  3. **备份/回退 → 必须重写**：`.bak` 生成与原子恢复在 `atomic_store.py:402, 438`；
     JS 里没有"原子写 + 回读复核"的等价物（浏览器写文件是尽力而为的），**回退能力会显著弱化**。
  4. **迁移门禁 → 失效**：门禁脚本是 Python CLI（`scripts/compare_field_meta_migration.py`），前端直读模式下没有触发点。
  5. **导出/导入 `.ttrpack` → 必须重写**：`pack_transfer.py` 905 行（sha256、Zip Slip、五项体积上限、
     校验器、冲突改名/覆盖备份）。JS 里要全量再实现一遍。
  6. **技术限制**：File System Access API 是 **Chromium 系专有**（Firefox/Safari 不支持）且要求**安全上下文**；
     而 `index.html` 现在用的是**根绝对路径** `/static/tokens.css`（`index.html:7`），`file://` 下直接失效，
     必须改造成相对路径或起本地服务——**"去后端"最后往往又长出一个小后端**。
- **结论**：这条路**不是"省掉服务器"，而是"把服务端 11761 行逻辑中的校验/备份/回退/打包部分搬到 JS 重写"**，
  工时最高、风险最大、且直接违反既有设计纪律。**明确不建议。**

---

## 三、关键难点清单（每条带证据）

> 按"会不会真正拖垮项目"排序。①③⑤是**结构性**的，②④⑥⑦是**工程量**的。

**① 服务端的校验 / 备份 / 回退 / 迁移门禁是 Python 实现的；本地化 = 重写它们，或者把整套 Python 搬过去。**
- 证据：`editor_ops.py:6-17` 明确写死保存链路「校验通过才落盘 → `.bak` → 原子写 → 回读复核」；
  `validator.py` 3723 行、`atomic_store.py` 875 行、`pack_transfer.py` 905 行、`api.py` 4345 行、`editor_ops.py` 1376 行、`csv_ops.py` 537 行，**合计 11761 行**。
- 含义：路线 3 要把这些搬到 JS（双实现必漂移）；路线 2 要把这些**原样打包**（可行，但那是"打包"，不是"桌面化"的收益）。

**② 前端硬编码根绝对路径 `/api/...`，没有基址配置——壳不能随便换 origin。**
- 证据：`grep -n 'API_BASE\|location.origin\|window.location'` → **0 匹配**；24 处调用写死 `"/api/pack/" + …`（`index.html:3357, 3394, 3980, 4785, 7611, 7645, 7756, 7822` …）；样式也是 `/static/tokens.css`（`index.html:7`）。
- 含义：**路线 1 反而最省事**（页面仍从后端 origin 加载，路径天然有效）；**路线 3 最麻烦**（`file://` 下全废）。
  若走"壳直连公网 HTTPS 后端"，还要额外处理 CORS/Origin ——而宿主**当前没有任何 Origin/Host 校验**，属于"能用但没护栏"。

**③ 内容包在服务器上，且服务器上还有别的角色（打包/校验/迁移门禁）——"谁是权威副本"没有现成答案。**
- 证据：默认内容根 `<仓库根>/content`（`api.py:146-150`）；服务器现有 10 个包（`ls content/`）；
  覆盖前自动备份到 `.ttrpack_backups/`、导入需 owner（`docs/编辑器重写_需求与约束.md:120-142`）；
  `pack_transfer.py:80` `max_archive_bytes = 64MB`。
- 含义：现有代码里**没有"两台机器各一份副本"之间的同步/冲突解决**。
  `grep -rn '离线\|双副本\|drift\|漂移' qbot_rpg/web/*.py` → **0 匹配**；仓库里的"冲突"只指
  **同一个内容根内**的包 id 冲突（`pack_transfer.py:692 _resolve_target(on_conflict=…)`）与 CSV 同 id 冲突
  （`csv_ops.py:19, 320, 332`：`skip`/`overwrite`）。二者都不是跨副本同步。
  路线 2 的 15–30 人日基本都花在这里，而**用户并没有提出离线需求**。

**④ Python 打包：要新增工具链，且构建只能在 Windows 上做。**
- 证据：`requirements.txt` 23 行，**无** `pyinstaller`/`nuitka`/`pywebview`（`grep` 无匹配）；
  `.venv` 是 **Python 3.14.7**、**282M**；仓库 490M（`.git` 99M、`tests` 38M、`.mypy_cache` 27M）。
- 含义：新依赖 + 新构建脚本 + 只在 Windows 出产物；**必须显式排除** tests/docs/.git/.mypy_cache 等（否则产物巨大）。
  杀软误报是此类工具的常见现象，但**本环境无法验证**，实施时必须在目标机实测（列为待验证项）。

**⑤ 编辑器零鉴权——"壳直连公网"会把现在的安全模型打穿。**
- 证据：`editor_host.py:15-16`「批2 **不做登录页**」；`editor_ops.py:112-115` 只有角色断言（`owner`/`gm`）**不是认证**；
  `/api/session/role` 可**运行期切角色**（`editor_host.py:76-83`）；`editor_start.sh` 安全提示与 `docs/编辑器使用说明.md:55-65` 都要求走 SSH 隧道。
- 含义：若桌面壳"直连服务器 HTTPS"，等于把一个**无登录、可任意写内容包**的编辑器暴露到公网。要这么做，
  **必须先补一层认证**（nginx basic auth 或应用内登录）——这是路线 1"直连变体"的隐藏成本，文档里容易漏。
  走 SSH 隧道（1a/1b）则**不引入**这个新面。

**⑥ 凭据怎么放到用户电脑上：私钥就是服务器 root 权限。**
- 证据：私钥已交付用户（`/root/deliverables/id_ed25519_服务器免密私钥.txt`）；`免密登录_使用说明.md` 首句即
  「**这个私钥文件就等于你的服务器密码**」；部署方案 §一 记该密钥可 `root` 免密登录。
- 含义：任何本地方案都要把这份私钥放在非技术用户的 Windows 上（有丢失/泄露/换机/撤销的运维成本）。
  **这条是既有方案就已承担的成本，不是桌面 GUI 新增的**——但路线 2/3 会把它藏得更深（用户更不知道它存在）。

**⑦ Windows 无 Python 环境 / WebView2 运行时版本差异。**
- 证据：编辑器必须用 `.venv` 的 Python（`.venv/bin/python` = 3.14.7；系统 `python3` 3.11.15，服务器系统 `python3` 3.8.10——见部署方案 §1.2）。
- 含义：不能假设用户机器有 Python（所以路线 2 必须打包解释器）；WebView2 在 Win11 自带、Win10 视版本，
  **需在目标机实测**（待验证项）。

---

## 四、推荐路线 + 理由

### 4.1 结论：**不建议现在做"完整桌面应用"；建议只做路线 1a（免命令启动器）。**

**理由（三条，按权重）：**

1. **用户真正的痛点是"开隧道 + 记命令"，不是"想要一个窗口程序"。**
   任务书原话是「不想开隧道 / 不想记命令」。路线 1a **直接命中**这个痛点，且**0.5–1 人日**；
   而 B/C/D 解决的是用户**没提出**的问题（窗口、离线），代价却高 1–2 个数量级。
2. **做 B/C/D 的收益几乎全在"数据同步"这一侧，而这一侧的现有实现为零。**
   前端（零 CDN 单文件）、后端（纯 Python 无 Node）都**天然适合被壳**，
   所以"桌面化"本身很便宜——贵的是**把服务器上的校验/备份/回退/打包搬来搬去**（难点 ①③）。
   换句话说：**不是"桌面应用"难，是"离开服务器"难。**
3. **有一条已经被设计好、且与现有安全模型完全兼容的现成路线。**
   `/root/deliverables/编辑器部署_方案.md` §〇 已把"systemd 常驻 + 一键隧道"定为 ★首选，
   §三 Step 4 连 `.bat` 全文都写好了。**本次评估的正确结论是"沿用并（可选）美化它"，而不是另起一套。**

### 4.2 如果要"更像一个应用的体验"（介于两者之间的轻量替代）

按推荐顺序，**每一步只在前一步不够用时才做**：

| 选项 | 做什么 | 增量成本 | 用户感受 |
|---|---|---|---|
| **L0（建议基线）** | 保留 `.bat` 双击启动器（部署方案 §三 Step 4 现成） | **0** | 双击 → 黑窗 → 浏览器 |
| **L1** | 把 `.bat` 用 `ie4uinit`/资源编辑器加图标，或包成**自解压 exe**；隧道起来后**自动**打开浏览器（`start "" http://127.0.0.1:8090`） | **0.5–1 人日** | 双击一个带图标的 exe，浏览器自动弹出 |
| **L2** | 用 **pywebview + WebView2** 做真窗口（内嵌隧道 + 探测端口 + 自动加载），前端**零改动** | **+3–5 人日**（含打包） | 一个独立窗口，无浏览器地址栏，无黑窗 |
| **L3** | 做托盘常驻 / 断线自动重连 / 内置"服务器未启动"的友好提示 | **+2–4 人日** | 忘记关窗口也不影响 |

**明确不做**：路线 2（离线全栈）与路线 3（去后端直读文件）——除非用户**明确要求离线编辑**，
且接受"每次同步都要选文件/可能冲突"（见 §六 待确认 1）。

---

## 五、工作量与分期（若要做）

> **前提**：本节只在用户**明确要"真窗口 GUI"甚至"离线"**时才启用。
> 若用户接受 §四 的 L0/L1，则**只有第 1 步**，做完即交付。

| 期 | 交付物 | 验收标准（可观测） | 工作量（估算） | 依赖 |
|---|---|---|---|---|
| **第 1 步 · 免命令启动器（强烈建议先做，单独可用）** | 桌面一个带图标的 `编辑器隧道.exe`（或现成 `.bat`）：双击 → 建 SSH 隧道 → 自动打开浏览器到 `http://127.0.0.1:8090` | 在用户的 Windows 上双击后 10 秒内浏览器出现编辑器界面并**能保存一条改动**；关掉窗口即断开 | **0.5–1 人日** | 服务器侧 systemd 常驻（部署方案 §三 Step 1–3）；已交付的私钥 |
| **第 2 步 · 真窗口壳（可选）** | `pywebview` 窗口版：内嵌隧道 + 端口就绪探测 + 失败人话提示 + 下载落地（`.ttrpack` / CSV） | Windows 目标机上：断网/服务器未启动/端口被占/私钥缺失，四种情况都有中文提示且不白屏；导出的 `.ttrpack` 能落到"下载"目录 | **3–5 人日**（含 PyInstaller 打包与体积极简） | 第 1 步可用；WebView2 运行时在目标机实测通过 |
| **第 3 步 · 体验收尾（可选）** | 托盘常驻、断线自动重连、开机自启（用户可选） | 拔网线 30 秒后自动恢复；重启电脑后仍能双击即用 | **2–4 人日** | 第 2 步 |
| **（不建议）第 4 步 · 离线编辑 + 同步** | 本地全栈 + `.ttrpack`（或 sftp）双向同步 + 冲突提示 | **需先定义"权威副本"规则**（见 §六 待确认 1）；必须给出"本地改了、服务器也改了"时的确定行为 | **15–30 人日** + 长期维护 | 用户明确要离线；且要先补服务端认证/防双写方案 |

**关于杀软误报与体积**：第 2 步的产物必须实测（本环境是 Linux，**无法**给出 Windows 产物大小的实测值；
本报告不编造体积数字）。已知可减少体积的可控项：`.venv` 282M、`tests` 38M、`.mypy_cache` 27M、`.git` 99M
**都不需要进产物**（§1.3 体积证据）。

---

## 六、待用户确认

| # | 需要用户决定 | 选项 | 不确认的后果 |
|---|---|---|---|
| 1 | **是否需要"离线编辑"**（没网也能改内容包）？ | 不需要（推荐）/ 需要 | 需要 → 直接跳到路线 2，工时 15–30 人日，且要先定"权威副本"规则 |
| 2 | **是否接受"仍然要联网"**（打开时连着服务器）？ | 接受（推荐）/ 不接受 | 不接受 → 只能走路线 2 或 3（都更贵） |
| 3 | **是否愿意在电脑上装一个 `.exe`**？ | 愿意 / 只接受 `.bat` 脚本 / 只接受浏览器网址 | 决定做 L1 还是 L2；若"只接受网址"→ 走部署方案 §四（公网 + basic auth），代价是开端口 |
| 4 | 要**真窗口**（独立窗口无地址栏）还是**浏览器**就够？ | 浏览器够（推荐）/ 要真窗口 | 要真窗口 → +3–5 人日（第 2 步） |
| 5 | 用户电脑是 **Windows 10 还是 11**？（影响 WebView2 是否需另装） | Win10 / Win11 / 都要支持 | 影响 L2 是否需要附带 WebView2 安装包 |
| 6 | 是否允许**沿用已交付的私钥**放在用户电脑（`%USERPROFILE%\.ssh\`）？ | 允许（现状）/ 想改密码登录 | 改密码 → 每次要输密码，"免命令"体验打折 |
| 7 | 是否接受**黑窗口不能关**（隧道断则编辑器失效）？ | 接受 / 要托盘常驻 | 要常驻 → +2–4 人日（第 3 步） |

> 注：其中第 3、5 项与既有 `/root/deliverables/编辑器部署_方案.md` §七 的待确认项**重叠**，建议合并一次问用户，别问两遍。

---

## 附录 A · 取证命令与输出摘要

> 只读命令，均在 `/root/QBot-TurnTellerRPG` 下执行（除注明外）。输出为原文摘要。

**A1 前端规模与依赖**
```
$ wc -l qbot_rpg/web/static/index.html
7871 qbot_rpg/web/static/index.html
$ ls -la qbot_rpg/web/static/
-rw-r--r-- 385090 Sep 20 15:15 index.html
-rw-r--r--  12994 Sep 14 14:54 tokens.css
$ grep -n '<script' qbot_rpg/web/static/index.html
8:<script>
1211:<script>
$ grep -n '<link rel' qbot_rpg/web/static/index.html
7:<link rel="stylesheet" href="/static/tokens.css">
$ grep -cn 'import \|require(\|type="module"' qbot_rpg/web/static/index.html
0
$ ls package.json node_modules
ls: cannot access 'package.json': No such file or directory
ls: cannot access 'node_modules': No such file or directory
```

**A2 前端后端调用面与基址（关键）**
```
$ grep -c 'fetch(' qbot_rpg/web/static/index.html        → 7
$ grep -c 'api('     …                                    → 14
$ grep -c 'postJSON(' …                                   → 10
$ grep -n 'API_BASE\|location.origin\|window.location' …  → （无匹配）
$ grep -n '"/api/' … | head
3357 / 3381 / 3394 / 3848 / 3861 / 3965 / 3980 / 4318 / 4389 / 4467 / 4491 /
4517 / 4749 / 4785 / 4810 / 4823 / 4857 / 4892 / 5124 / 6625 / 6647 / 6722 /
7611 / 7645 / 7733 / 7756 / 7822
```

**A3 前端浏览器 API**
```
$ grep -n 'localStorage\|indexedDB\|FileReader' qbot_rpg/web/static/index.html
115, 3447 (localStorage) / 3598, 3601 (indexedDB) / 3696 (FileReader)
$ grep -n '\.files\b' …  → 3737, 7586, 7640, 7715, 7751
$ grep -n 'crypto\.' …   → （无匹配，0 处）
$ grep -n 'URL.createObjectURL' …  → 7602
```

**A4 后端**
```
$ wc -l scripts/editor_host.py qbot_rpg/web/api.py qbot_rpg/web/editor_ops.py \
        qbot_rpg/web/csv_ops.py qbot_rpg/content/validator.py \
        qbot_rpg/content/atomic_store.py qbot_rpg/content/pack_transfer.py
   315 scripts/editor_host.py
  4345 qbot_rpg/web/api.py
  1376 qbot_rpg/web/editor_ops.py
   537 qbot_rpg/web/csv_ops.py
  3723 qbot_rpg/content/validator.py
   875 qbot_rpg/content/atomic_store.py
   905 qbot_rpg/content/pack_transfer.py
$ grep -c '@app\.' scripts/editor_host.py   → 32
$ sed -n '15,17p' scripts/editor_host.py
  · --role 表达权限位（沿用「机主可编辑 / GM 只读预览」语义）：owner 可编辑、gm 只读；
    批2 不做登录页，顶栏开关可在运行期切换（`/api/session/role`）。
  · 落盘一律经 editor_ops → atomic_store：写前校验 + 自动备份 .bak + 原子写 + 回退。
$ sed -n '112,115p' qbot_rpg/web/editor_ops.py
def require_edit(role: object) -> None:
    """写入前置权限断言：只读角色 → Forbidden(403)，绝不落盘。"""
$ sed -n '146,150p' qbot_rpg/web/api.py
def content_root(root: Optional[object] = None) -> Path:
    """内容包根目录：显式传入则用之，否则默认 <仓库根>/content。"""
```

**A5 同步/冲突能力现状（路线 2 的关键空白）**
```
$ grep -rn '离线\|双副本\|drift\|漂移' qbot_rpg/web/*.py            → （无匹配）
$ grep -rn 'def .*conflict\|on_conflict' qbot_rpg/web/*.py qbot_rpg/content/pack_transfer.py
qbot_rpg/web/csv_ops.py:19  · 冲突：同 id 已存在 → on_conflict=skip（默认）… / overwrite …
qbot_rpg/web/csv_ops.py:332 conflict = str(on_conflict or CONFLICT_SKIP).strip().lower()
qbot_rpg/content/pack_transfer.py:692 def _resolve_target(content_root: Path, pid: str, on_conflict: str, …
（均为"同一内容根内"，非跨副本同步）
```

**A6 打包前提**
```
$ wc -l requirements.txt   → 23
$ grep -in 'pyinstaller\|nuitka\|pywebview\|briefcase\|electron' requirements.txt pyproject.toml
（无匹配）
$ .venv/bin/python --version   → Python 3.14.7
$ python3 --version            → Python 3.11.15
$ du -sh . .git .venv tests .mypy_cache qbot_rpg content docs
490M . / 99M .git / 282M .venv / 38M tests / 27M .mypy_cache / 25M qbot_rpg / 1.4M content / 9.3M docs
$ ls content/
demo_blank demo_full demo_lv15 demo_lv30 demo_lv45 test_demo veinborn zz_craft_demo zz_probe_ext zz_probe_packmeta
```

**A7 既有交付物（本报告的外围前提）**
```
$ ls -la /root/deliverables/ | grep -E '编辑器|SSH|免密'
-rw------- 50806 Sep 20 13:57 编辑器部署_方案.md
-rw-r--r-- 17717 Sep 14 08:17 编辑器使用说明.md
-rw-------   411 Sep 15 00:05 id_ed25519_服务器免密私钥.txt
-rw-r--r--  5213 Sep 14 23:58 SSH上手_腾讯云.md
-rw-r--r--  2851 Sep 15 00:06 免密登录_使用说明.md
```

**A8 未能在本环境验证的项（如实登记，不编造）**
- Windows 产物体积、PyInstaller/Nuitka 对 **Python 3.14** 的实际支持度 → 需在 Windows 上实测。
- WebView2 运行时在用户目标机（Win10 具体版本）是否已装 → 需实测。
- 杀软误报 → 需实测。
- Windows side 的 `.exe` 是否被 SmartScreen 拦 → 需实测。

---

## 附录 B · 与既有《编辑器部署_方案》的关系

| | `/root/deliverables/编辑器部署_方案.md`（既有） | 本报告（新增） |
|---|---|---|
| 解决的问题 | 编辑器**怎么跑起来、用户怎么连上**（服务器侧 systemd 常驻 + 用户侧一键隧道；备选公网 HTTPS） | 编辑器**要不要做成 Windows 桌面 GUI 应用**（可行性 + 三条路线 + 成本） |
| 结论 | ★首选 ② systemd 常驻 + 一键隧道（`.bat` 双击） | 支持该结论，并**定量说明"再往前走一步"的代价**：真窗口 +3–5 人日、离线 +15–30 人日、去后端 +40 人日 |
| 重叠部分 | §三 Step 4 的 `编辑器隧道.bat`、§七 待确认 3/5/7 | 本报告 §四 L0/L1 直接复用**不重写**；§六 待确认与 §七 **合并询问**，避免重复打扰用户 |
| 本次新增的关键判断 | — | ① 前端零 CDN/无 Node → **壳很便宜**；② 零鉴权（`editor_host.py:15-16`）→ **"壳直连公网"必须补认证**；③ 服务端 11761 行校验/备份/回退/打包 → **"离开服务器"才是真成本** |

**B·补 · 取证期间观察到的并发事实（强证据）**：本报告交付时，仓库出现一个**未跟踪**的新文件
`scripts/gen_editor_tunnel_kit.sh`（12444 字节，mtime `Sep 20 15:32`，头部注释自述"批63 · 一键隧道交付包生成脚本"，
用途为「生成 Windows/macOS 双击即用隧道脚本 + 小白说明 + 私钥 → 打 zip」）。
它**不是本报告所在任务的产物**（本任务只读仓库），但对本报告的结论构成**现场印证**：
**团队已经在按"路线 1a（免命令启动器）"落地**——这正是 §四 推荐的 L0/L1。
因此本报告的增量价值集中在两点：① 给出"再往前走"的定量代价（L2/B/C/D）；
② 提醒若走"壳直连公网"必须先补认证（难点 ⑤）。

---

## 自查（交付纪律核对）

- [x] 本报告为**本次任务唯一被写入的文件**（`/root/deliverables/编辑器Windows_GUI_可行性.md`）。
      本次执行**未对仓库做任何写入**：全部命令为只读（`wc/grep/ls/sed/du/git status/python --version`）。
      交付时 `git status --porcelain` 显示 **1 个未跟踪文件** `scripts/gen_editor_tunnel_kit.sh`
      （mtime `Sep 20 15:32`，与本报告写入同一时刻）——**不是本任务创建的**，系**并发进行的其它工作**
      （批63「一键隧道交付包生成脚本」）所产生；如实登记，未触碰。
- [x] 每条结论均带 `file:line` 或「命令 + 输出」；无法验证的项在 A8 明确标注为"未验证"，未编造数字。
- [x] 工作量数字**全部标注为"估算"**，并给出估算依据（要新写的部分 + 现有实现空白）。
- [x] 结论明确：**完整桌面应用 = 麻烦（中等～复杂）；只解决"免命令" = 不麻烦（简单，0.5–1 人日）**。
- [x] 未写任何实现代码。
