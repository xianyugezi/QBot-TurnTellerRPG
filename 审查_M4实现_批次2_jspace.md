# 审查报告：M4 实现层·批次2（消息模板 + 四系统指令接线）

- **审查对象（5 文件）**：
  - `qbot_rpg/commands/sender.py`（segment_by_length / TPL-12/13/14 / 退避重试）
  - `qbot_rpg/core/message_format/list_render.py`（resolve_page 裁决② / TPL-08 页脚）
  - `qbot_rpg/commands/shop_commands.py`（/商店 /购买 /出售）
  - `qbot_rpg/commands/quest_commands.py`（/任务 接取/交付/信息/放弃）
  - `qbot_rpg/commands/checkin_commands.py`（/签到 结算/状态/补签）
- **参考**：`docs/m4_shared_contract.md`（§2.2/§2.3/§3.2/§3.3/§3.4）+ `docs/细化/细化_3d_消息模板规范.md` + `细化_2b3/2b4/2b5` + 裁决②（页码夹取）/⑦（补签只计不补发）/⑧（表名限定三键）。
- **审查维度**：①定稿落地 ②代码质量（bug/边界）③幻觉/缺漏。
- **方法**：纯静态代码审查（无 bash/无运行/无验证；j-space 门控 **full 档**，introspection 模块加载）。凡运行期行为结论一律标注 **【静态推导】**。bash 沙箱确认不可用，未执行任何命令。
- **门控档位**：**full**（多文件多维度、单份可复核报告）。

---

## 〇、结论摘要

| 级别 | 数量 | 一句话 |
|---|---|---|
| **P0** | 1 | checkin_commands 与同批引擎 core/checkin.py **接口全面失配**（调用的 checkin_today/checkin_status 不存在、checkin_makeup 参数顺序颠倒、resolve_checkin_table 返回类型不符、返回形态不符）→ /签到 接真实引擎即 AttributeError/恒败 |
| **P1** | 1 | test_checkin_commands 以「契约忠实替身」驱动且宣称"替身可整体替换为真实引擎断言不破"——**替身与真实引擎不可互换**，主动掩盖了 P0 |
| **P2** | 9 | 页码非法缺页脚指引、转义序列跨分片、死代码/零生产消费、/商店 N 二义性与 TC-02 冲突、展示序号脆弱耦合、逐页重拉引擎、吞异常误报"不存在"、紧凑子词碰撞、折扣+混合支付货币名空显 |

---

## 一、维度① 定稿落地

### 1.1 已落地且确认（无问题维度）

| 契约点 | 确认 | 依据 |
|---|---|---|
| 列表 5 条/页上限 | ✅ 三壳统一 DEFAULT_PAGE_SIZE=5 重分页 | list_render L39；shop/quest/checkin 各自重分页（补白已标注） |
| 页脚固定 TPL-08、禁自造 | ✅ 唯一出口 render_footer，格式逐字核对 `— 第 {X}/{Y} 页 · 共 {N} 条 · 输入 /{指令} 页码 翻页 —` | list_render L134-142；test_sender L134 逐字断言 |
| 错误模板唯一文案源 TPL-12/13/14 | ✅ 全部经 sender.format_tpl12/13/14 → errors.py 常量，业务代码零自造三要素句式 | errors.py L23-25；五文件引用一致 |
| 页码夹取裁决②（超总页→最后一页+「已到最后一页」） | ✅ resolve_page.clamped + LAST_PAGE_HINT，三壳与引擎双侧夹取 | list_render L106-107/L41；shop.py L982 |
| 页码 0/负数/非数字→TPL-12 | ✅ parse_int / _coerce_int / 壳层 n<1 分支均判 TPL-12 | list_render L104-105；三壳 |
| 裁决⑧ [签到:表名.字段] 三键 | ✅ 引擎 checkin_value 按表名限定（缺省主表 loop）【静态推导】 | core/checkin.py L539-564 |
| 裁决⑦ 补签只计不补发 / 里程碑不重复 | ✅ 引擎 checkin_makeup 仅恢复 signed_days/streak，不补发不触发里程碑【静态推导】 | core/checkin.py L856-960 |
| 装饰性 emoji 禁用（D-01） | ✅ 5 批文件零装饰 emoji；唯一 ✅/❌ 功能性标记；━━/— 为排版字符不在禁用清单 | 全文件 grep 零命中 |
| 零 NoneBot import / 纯函数 | ✅ 五文件均无 nonebot import，发送/now/rng 经注入 | sender L10-11 |
| 页码空列表口径 | ✅ resolve_page 空列表 total_pages=1，与 panel_render.paginate 同口径（引用真实） | list_render L98/L102；panel_render L108 |

### 1.2 商店指令语义（/商店 /购买 /出售）

- 主入口三态（无参=当前→默认兜底 / 列表 / 名称 / 整数）语义完整；购买/出售目标解析与 6 步校验链、原子结算、数量上限（99 截断提示不拦截）、限购/库存/货币差额全部委托引擎，壳层只装配渲染 —— 与 2b3 §2.1-2.3 一致【静态推导】。
- `cmd_shop` 整数二义性（页码优先→超页切店→夹取）已按【工程补白 2】显式登记，语义自洽；但与 2b3 TC-02「/商店 2 序号切换进第二家」的引用断言存在张力（见 P2-4）。

### 1.3 任务指令语义（/任务 接取/交付/信息/放弃）

- 子指令 + 序号、任务板 5 条/页 + 双板段头 + 主线置顶、交付 skipped（P1-2 逐条目失败黄字跳过注记）渲染齐全；resolve_board_index→quest_id 转换与引擎真实签名一致（quest 测试用真实引擎，已实证对齐）。

### 1.4 签到指令语义（/签到 结算/状态/补签）—— **P0：语义无法落地**

- 见 P0-1。命令层文件头自拟的消费接口与同批已落盘引擎 **不存在同名函数**，/签到（结算/状态/补签）接真实引擎即崩/恒败，裁决⑦⑧ 的"透传"承诺无法兑现。

---

## 二、维度② 代码质量（bug/边界）

### P0-1 【checkin_commands ↔ core/checkin 接口全面失配】（阻塞级）

**文件/行号**：`qbot_rpg/commands/checkin_commands.py` L20-21、L37-50（自拟契约）、L54-57（补白1 声称"尚未收口【待接线】"——已失实）、L176-193（懒加载真实模块）、L253（`engine.checkin_today(ctx)`）、L265（`engine.checkin_status(ctx)`）、L277（把 Mapping 当 str 表 id）、L280（`engine.checkin_makeup(tid, ctx)` 参数顺序颠倒）、L313（缺省表名→None→TPL_NO_TABLE）。

**对照真实引擎** `qbot_rpg/core/checkin.py`：
- L586 `checkin_state(ctx) -> {ok, today, tables:[...]}`；L824 `checkin_do(ctx) -> {ok, today, tables, message}` —— **不存在 checkin_today / checkin_status**；
- L856 `checkin_makeup(ctx, table_id=None)` —— 参数顺序与命令层调用 **相反**；
- L242 `resolve_checkin_table(ctx, table_id) -> Optional[Mapping]`（返回表定义 dict，且非 str 入参直接 None）—— 命令层按 `Optional[str]` id 消费，类型不符。

**后果【静态推导】**：
1. 未注入 `checkin_engine` 的缺省路径（懒加载真实模块）→ `/签到` 调 `checkin_today` **AttributeError** 崩溃；注入"符合文件头契约的适配器"也不存在现成实现。
2. 即使改名，`checkin_makeup(tid, ctx)` 收到 (str, dict) → 引擎首参 `ctx` 非 Mapping → 恒返回「❌ 结算上下文非法」。
3. `/签到 补签`（2b5 §2.1 无参形态，裁决⑧ 缺省=主表 loop）被命令层 resolve 为 None → 直接 TPL_NO_TABLE「❌ 没有这个签到表」——缺省表名语义被破坏。
4. 返回形态不符：命令层期望 `{ok, message, sections:[{title, rows}]}`，引擎 `checkin_do` 返回 `tables`（每表 dict），`flatten_sections` 读 `sections` 恒空 → 即便改名，正文渲染也落空；且引擎 `_summary_lines` 自带 `┌─ 📅 签到汇总 ────`/`⚠` 装饰 emoji（L792/L811，📅/⚠ 均在 3d D-01 禁用清单），命令层补白 2 宣称的"降级纯文本"无法对真实引擎达成。

**修复建议**（二选一，建议①）：
① 以真实引擎为准改造命令层：`/签到`→`engine.checkin_do(ctx)`、`/签到 状态`→`engine.checkin_state(ctx)`，从 `tables`（或 `checkin_value`）重建 `sections`（表段头 + 流水行，纯文本），`/签到 补签`→缺省表名=主表 loop 传 None 给 `checkin_makeup(ctx, table_id)`（或先 `_primary_table_id`），`resolve_checkin_table` 返回值取 `.get("id")`；
② 或在引擎补 `checkin_today/checkin_status` 包装 + 调整 `checkin_makeup` 参数序 —— 不推荐，违背"命令层消费引擎唯一接口"的批次分工。
无论哪种，须同步修正文件头契约块（L37-50）与 补白1（L54-57 的"尚未收口"失实声明），并登记 contract_deviations（文件头 L36 自称会登记，实际未登记）。

### P1-1 【测试替身掩盖失配 ·「断言不破」声明不成立】

**文件/行号**：`tests/unit/test_checkin_commands.py` L9-12、L41-122（FakeCheckinEngine 实现文件头契约而非真实引擎）；`checkin_commands.py` L54-57。

**问题**：命令层单测用"契约忠实替身"驱动，替身只实现文件头自拟接口；文件头声称"路F2 落盘后替身可整体替换为真实引擎，断言不破"——**不成立**（真实引擎无 checkin_today/checkin_status、checkin_makeup 参数序相反、resolve_checkin_table 返回 Mapping）。对比：`test_quest_commands.py` L35/L91/L370 直接注入真实 `core.quest`，quest 侧失配能当场暴露；checkin 侧替身使批内测试全绿、掩盖 P0。

**修复建议**：单测改为注入真实 `core/checkin`（对齐 test_quest_commands 模式），或至少加一条"真实引擎与命令层契约对齐"的断言；删除/改写"断言不破"声明。

### P2-1 【页码非法缺 TPL-08 页脚指引 · page_error_tpl12 生产零消费】

**文件/行号**：shop_commands.py L367/L375/L392/L397、quest_commands.py L419/L435、checkin_commands.py L306/L323/L329（非法页仅 `format_tpl12(...)`）；sender.py L108-116（page_error_tpl12 实现"TPL-12+页脚"但**无任何生产调用**，仅 test_sender / verify_m4 引用）。

**问题**：3d §2.2「非法值（0/负数/非数字）→ TPL-12 + 页脚指引」；专为此设计的 `page_error_tpl12` 在三个壳零消费，用户非法翻页时收不到 TPL-08 翻页指引（§5.4"错误不附页脚"与 §2.2 存在张力，但专用助手存在说明意图即"附页脚"）。

**修复建议**：三壳非法页分支改用 `page_error_tpl12(fragment, command, total_pages, total)`（或拼 `render_footer`），或明确登记按 §5.4 口径省略并删除死助手。

### P2-2 【cq_escape 后分片 → 转义序列可被切跨段边界】

**文件/行号**：sender.py L169-170（`escaped = cq_escape(text)` → `segment_by_length(escaped, budget)`）、L83。

**问题【静态推导】**：超 4000 字消息中若含 `&`/`[`/`]`，转义为 `&amp;`/`&#91;`/`&#93;`（5 字符），切分点可能落在转义串中间 → 段尾残留 `&`/`&#`、段首 `#91;` 等，分条发送后可见乱码（无注入风险，纯显示）。

**修复建议**：先按原文分片、再对每段 `cq_escape`（或分片时避开未闭合转义序列）；补一条"转义串不跨段"单测。

### P2-3 【死代码 / 生产零消费】

- `sender.py` L149 `self._client` 占位属性声明后从未使用（"兼容旧占位签名"），建议删除或登记待接线。
- `shop_commands.py` L122 `format_number` 仅被测试引用（test_shop_commands L431），生产路径零消费——保留无妨但应注明"供外部/测试"或删除导出。

### P2-4 【/商店 <整数> 页码优先与 2b3 TC-02 序号切换冲突】

**文件/行号**：shop_commands.py L31-35（补白2）、L371-387。

**问题**：当前店商品 >5 条（pages5≥2）时 `/商店 2` 恒为翻页，**永远无法**经 `/商店 2` 序号切换第二家店（TC-02 断言），须改 `/商店 <名称>`。属已登记补白，但与文件头引用为权威的 2b3 TC-02 冲突。

**修复建议**：在 2b3 侧登记该收敛（或提供 `/商店 切 2` 类显式切店子词）；至少将 TC-02 标注为"仅当前店 ≤5 条时成立"。

### P2-5 【quest render_board 重算展示序号而非消费 engine row.index】

**文件/行号**：quest_commands.py L318-326（`board_line(start + i + 1, row)`）；core/quest.py L503-516（row 带全局 `index`）。

**问题**：文件头声称"row.index 即展示序号，/任务 接取 N 即此序号"（L35-36），但壳层自行按扁平位置重算，未消费 row.index。当前引擎（空段跳过、全量返回）下与 `resolve_board_index` 计数一致，无漂移；一旦引擎过滤行/改段序即静默错位（显示序号与接取目标对不上）。

**修复建议**：壳层改用 `row.get("index")` 作为展示序号（扁平位置仅作段头/分页依据），消除脆弱耦合。

### P2-6 【_all_browse_rows/_all_shop_rows 逐页重拉引擎 · 200 页硬上限】

**文件/行号**：shop_commands.py L177-216。

**问题**：`_all_*` 循环调 `shop_browse/shop_list` 直到 `len(rows)>=total`（最多 200 页=2000 行）。每次调用重跑 `shop_lazy_refresh` + `goods` 重建（shop.py L976-977）；同一 /商店 调用内首页触发惰性刷新后后续页基本一致，但大店为 O(页数×全表) 重复计算，且 200 页截断对超大店静默丢尾部数据【静态推导】。

**修复建议**：引擎暴露一次性全量行接口（或壳层只取第 1 页的 total 后仅拉所需页），并去掉 200 页魔法上限（改按 total 精确收敛）。

### P2-7 【吞引擎异常误报"不存在"】

**文件/行号**：quest_commands.py L340-345（`_seq_to_quest_id` 捕 Exception→None）、checkin_commands.py L164-169（`resolve_checkin_table_arg` 同）。

**问题**：引擎内部错误（如 resolve_board_index 抛异常）被静默转成「❌ 任务不存在 / ❌ 没有这个签到表」——误导排障；值域语义（None=越界）与异常语义被混为一谈。

**修复建议**：仅对「返回 None」走值域文案；异常上抛由上层统一处理（errors.translate_error 待接线）。

### P2-8 【checkin 紧凑子词 startswith 碰撞】

**文件/行号**：checkin_commands.py L316-324（`first.startswith(SUB_MAKEUP)` / `startswith(SUB_STATUS)`）。

**问题**：任何以"补签"/"状态"开头的实参（如表名"补签表"、`/签到 状态栏`）被强制按子词解析，`/签到 补签表` 会把"表"当表名送 `resolve_checkin_table`。quest 侧用全匹配正则 `_SUB_SEQ_RE`（L135）较安全，checkin 侧过宽【静态推导】。

**修复建议**：改为全匹配正则（`^(补签|状态)(.+)?$` 且目标非空才走紧凑路径）。

### P2-9 【折扣 + 混合支付：原价行货币名空显】

**文件/行号**：shop_commands.py L260-266（`_browse_row_text` 折扣分支）。

**问题【静态推导】**：混合支付 `price_for` 返回 `{kind:"mixed", parts}` 无 `currency` 键（shop.py L727-734）；折扣 + 原价显示时 `price.get("currency","")` 取空 → `_currency_name(ctx,"")` → `""`，原价行呈现 `原价 100()`（货币名缺失）。单币无此问题。

**修复建议**：混合价折扣行按 `parts` 多币并显（如 `原价 50(金币)+5(宝石)`），或折扣价下省略原价货币名。

---

## 三、维度③ 幻觉/缺漏

### 3.1 docstring 行号/引用真实性（抽查结论）

- ✅ 真实可查：list_render 引 4f RUL-16（4f L198/L229「已到最后一页」逐字一致）/ RUL-18（L205）；panel_render.paginate"空列表同口径"（panel_render L108 逐行一致）；m4 §2.2/§3.2-3.4、2b3/2b4/2b5、裁决②⑦⑧ 尾注全部真实存在。
- ❌ **虚假/失实**：checkin_commands 文件头"消费接口契约块"（L37-50）与 补白1"尚未收口【待接线】"（L54-57）——契约签名不存在、引擎已落盘，属**声明覆盖但未实现 + 失实补白**（并入 P0-1）。
- ⚠ 未验证（外部引用，树内无对应文档，不判假）：sender L4-5 引【框架】L1622/【规则】L507/L523 等。

### 3.2 工程补白 vs 冒充

- shop/quest/checkin 三文件的跨路分页收敛、二义性裁决、模板降级、待接线、引擎解析等**均显式标注【工程补白】/【待接线】并给出理由**，纪律良好。
- 唯一失实：checkin 补白1 的"尚未收口"（见 P0-1）。另有 sender `_client` 占位（P2-3）属显式补白，可接受。

### 3.3 声明覆盖但未实现

- ✅ 诚实标注：三个 `register_*_commands` 的 `make_context=None → RuntimeError【待接线】`；quest 引擎头 6)「未实现/延后」清单（timed.penalty/filter/bonus/zone 子任务/npc 发布）。
- ❌ checkin 命令层自拟接口未实现（P0-1）。

### 3.4 零消费函数

- `sender.page_error_tpl12`（P2-1）、`shop_commands.format_number`（P2-3）、`sender._client`（P2-3）。

### 3.5 裁决贯彻

- 裁决② ✅ 完全落地（壳层 + 引擎双侧夹取 + TPL-12 + 提示）。
- 裁决⑦ ✅ 引擎落地（命令层仅透传，本批无违背）。
- 裁决⑧ ⚠ 引擎 checkin_value 落地；但命令层 `/签到 补签` 缺省表名被拒（P0-1 子项），致裁决⑧"缺省=主表 loop"在命令入口不可达。

---

## 四、发现分级汇总（P0=1 / P1=1 / P2=9）

| 级别 | 编号 | 主题 | 文件:行 |
|---|---|---|---|
| P0 | P0-1 | checkin 命令层 ↔ core/checkin 接口全面失配（函数缺失/参数序/返回类型/形态/缺省表名） | checkin_commands.py L37-50, L253/265/277/280, L313 |
| P1 | P1-1 | 测试替身掩盖失配、「断言不破」声明不成立 | test_checkin_commands.py L9-12/L41-122 |
| P2 | P2-1 | 页码非法缺 TPL-08 页脚；page_error_tpl12 生产零消费 | 三壳非法页分支 + sender.py L108 |
| P2 | P2-2 | cq_escape 后分片，转义串可跨段乱码 | sender.py L169-170/L83 |
| P2 | P2-3 | 死代码/零生产消费（_client / format_number） | sender.py L149；shop_commands.py L122 |
| P2 | P2-4 | /商店 N 页码优先与 2b3 TC-02 序号切换冲突 | shop_commands.py L31-35/L371-387 |
| P2 | P2-5 | render_board 重算展示序号，未消费 row.index | quest_commands.py L318-326 |
| P2 | P2-6 | _all_* 逐页重拉引擎 + 200 页硬上限 | shop_commands.py L177-216 |
| P2 | P2-7 | 吞引擎异常误报"不存在" | quest L340-345；checkin L164-169 |
| P2 | P2-8 | checkin 紧凑子词 startswith 碰撞 | checkin_commands.py L316-324 |
| P2 | P2-9 | 折扣+混合支付原价货币名空显 | shop_commands.py L260-266 |

---

## 五、无问题维度确认（复核通过）

1. 5 条/页 + TPL-08 页脚唯一源（list_render）+ 页码夹取裁决② —— 三壳与引擎一致。
2. TPL-12/13/14 错误统一文案唯一源（errors.py），五文件零自造三要素句式。
3. emoji 纪律：5 批文件零装饰 emoji（仅 ✅/❌ + 配置化商店 icon 豁免）；━━/— 非禁用字符。
4. 分片不吞内容/顺序不颠倒（segment_by_length）；退避重试上限、空文本、非法 budget 边界正确。
5. quest/shop 命令层与引擎签名真实对齐（quest 测试注入真实引擎实证）。
6. 数量上限（99 截断不拦截）、6 步校验链顺序、原子结算、限购/库存/货币差额提示均由引擎承担且命令层透传正确【静态推导】。
7. 零 NoneBot import、确定性（now/rng 注入）、纯函数纪律在 5 文件中成立。

---

## 六、后续批次衔接提醒（非本批缺陷）

- core/checkin.py `_summary_lines`（L792/L811）自带 `📅`/`⚠` 装饰 emoji，违反 3d D-01；命令层无法靠"降级渲染"规避（消息来自引擎）。修 P0-1 时需一并让引擎输出纯文本或由命令层重建正文。
- 装配层（批次6/7）注入 make_context 前，需先消解 P0-1，否则三个 register_* 的【待接线】RuntimeError 会在接线后立即暴露。
- `errors.translate_error`（errors.py L35-37）仍为占位 NotImplementedError，批次内错误统一文案已由 format_tpl12~14 覆盖，但领域异常翻译留待 M4 errors 实装。
