# 审查报告：QBot-TurnTellerRPG M5 实现 批次A（D1 前缀 + D4 emoji + D2/D3 列表筛选探索）

> 日期：2026-08-27（M5 里程碑批次A）｜审查人：j-space 门控 full 档（用户指定）
> 方法：**纯静态审查**（用户声明本环境无 bash 沙箱，全程未运行任何命令/脚本/测试；所有运行行为结论一律标注「静态推导」）。
> 范围：D1 前缀接线（prefix_wiring + prefix_render）+ D4 emoji 纪律（登记表 + emoji_sanitize + test_emoji_discipline）+ D2/D3 列表筛选探索（basic_commands 背包筛选链 / explore_commands 壳）。
> 依据：docs/m5_shared_contract.md（§一/§三/§四/§五）、docs/全局图标登记表.md、细化_3d_消息模板规范.md（§1.5/§二/§3.3/§四/TPL-08/TC-03/13/18/19）、细化_4f_基础指令组契约.md（RUL-16/RUL-19/TC-14）、细化_3h_settings通用设置.md（§6.1/V9~V12）、docs/审查参考/消息前缀功能设计定稿.md（§五/§七/§九 L112-121）。

---

## 一、结论总览

| 级别 | 数量 | 概要 |
|---|---|---|
| **P0** | 0 | 无阻断性/契约整体性缺陷 |
| **P1** | 1 | cmd_bag_filter 页码非法处理缺失：`/背包筛选装备 0` 抛未捕获 ValueError；`-1`/非数字被当筛选词，违反裁决②「0/负数/非数字 → TPL-12」 |
| **P2** | 8 | 非战斗指令出口前缀未接线 / 私聊[群名]兜底缺失 / /背包 头部缺失 / format="" 未按默认补全 / explore TPL-12 文案自写 / 品质筛选 def 兜底缺失 / 探索壳无注册门槛 / basic 注释引用已作废条款 |
| 信息提示 | 2 | 3h 文件引用口径（V9~V12 不覆盖 message_prefix）/ test_emoji_discipline WHITELIST 脆性 |

**一句话结论**：D1 前缀 7 字段消费、门控顺序、截断黄提示发射，D4 登记表↔白名单↔剥离函数三方一致，筛选链三链叠加、页脚/夹取、探索壳 1 条 全部实现正确；核心缺漏集中在「装配层（on_command）未落」导致的非战斗出口接线未覆盖与一个筛选页码边界缺陷。

---

## 二、维度① 缺漏

### 2.1 已确认覆盖（✅）

- **D1 契约 7 字段消费全覆盖**：prefix_wiring.py `read_message_prefix_settings`（L108-152）+ `apply_message_prefix`（L155-220）消费 enabled（L190）/ per_channel（L194-197）/ show_on_system（L200-201）/ format（L205）/ hide_when_empty（L206）/ empty_title_text（L207）/ prefix_max_len（L208），7 键默认值 `DEFAULT_MESSAGE_PREFIX_SETTINGS`（L78-86）与 shared_contract §1.1 / 定稿 §三 逐字一致（静态推导）。✅
- **截断黄提示发射**：消费 `render_prefix_result(...).truncated` → `PREFIX_TRUNCATED_HINT`「前缀过长已截断」（L216-219）；battle_commands.BattlePipeline.send（L494-517）在 `res.hint` 时向**归属发起目标**追加独立短消息发送（不阻断正文）——TC-13 归属群口径成立。✅（battle 路径）
- **D4 登记表 = ✅❌ + 排版符号**：test_emoji_discipline `_ALLOWED == {✅(U+2705), ❌(U+274C)}`（L23/L111），与登记表 §一 一致；排版符号（| → × / 「」【】）全部落在扫描正则（U+2600+ / U+1F000+ / VS16 / ZWJ）范围外，天然豁免，与登记表 §一.2 声明一致。✅
- **筛选链 类型→子类→品质 三链叠加全实现**：basic_commands.py `_filter_inventory_rows`（L697-714）逐级过滤（大类→子类→品质），`_parse_filter_args`（L659-694）支持「类型/子类 键值 + 品质 键值 + 裸词容错 + 尾随数字页码」；test_explore_filter 三链用例通过预期。✅
- **探索壳 /进入 /休息 结果 1 条**：explore_commands.py `cmd_enter`/`cmd_rest` 均返回单条 str（多行合并为一条消息文本），对齐铁律 2 / 3d §3.1 承接表「探索结果 1 条」。✅（注：任务所述「与 m5_shared_contract §三 一致」实为 §三=分页筛选，探索 1 条归属铁律 2 与 3d §3.1 承接表 / shared_contract §5.4 ⬜确认项；本壳已落实。）
- **/采集 DELAYED 已登记理由**：explore_commands.py L6-7 文档字符串明确登记「DELAYED：采集引擎未接线——M3 地图批次未产出独立采集引擎，采集点在地图/副本探索流程内处理；M5-09 壳层不阻断，后续批次接线」。理由完整、诚实。✅（注意：非 81-TC 覆盖点，故未进 verify_m5 COVERAGE 机器门禁，仅文档登记——可接受。）

### 2.2 「应覆盖 X 但未覆盖」清单（点名）

1. **前缀挂玩家回复首行 —— 应覆盖全部玩家指令出口，但仅覆盖战斗指令出口（basic/explore/shop/checkin/quest 未接线）**。
   `apply_message_prefix` 当前唯一消费方为 `qbot_rpg/commands/battle_commands.py`（BattlePipeline / apply_battle_prefix，L406-517）；`/背包` `/背包筛选` `/进入` `/休息` `/帮助` `/角色` 等非战斗指令输出仍为**无前缀裸文本**（各 register_* 标注「批次6/7 装配待接线」，basic_commands L1257+ / explore_commands L123+）。与 shared_contract §1.4「前缀挂到玩家回复首行 ⬜」状态一致（**未谎报**），但 prefix_wiring.py 头注释 L16/L26「装配层（on_command）统一注入」在**当前仓库仅战斗路径成立**——批次A 交付范围须在验收中注明「前缀接线 = 战斗管线 + 纯函数就绪」，非战斗出口留待批次7。
2. **私聊 [群名]="私聊" 兜底 —— 未实现**。定稿 §五.5 / shared_contract §1.2 声明「[群名] 私聊渠道输出 私聊」，但 `apply_message_prefix` 仅透传调用方 `extra`，无任何私聊默认注入；装配层未接线 → 私聊 + 含 `[群名]` 的 format 当前会**原样输出 `[群名]`**。建议：apply_message_prefix 内当 `channel==CHANNEL_PRIVATE` 且 extra 未提供「群名」且 format 含 `[群名]` 时注入「私聊」（或由批次7 装配层统一提供）。
3. **/背包 首行头部「【背包 · 第 X/Y 页】」—— 未实现**。4f TC-11 / TPL-4F-04 示例预期首行含 `【背包 · 第 1/3 页】`；`_render_bag_page`（basic_commands L546-565）只输出行列表 + 夹取提示 + TPL-08 页脚，无头部（test_basic_commands L256-265 断言首行=条目，与 4f 示例不一致）。属 M4 既有缺口，但列于本批次 D2/D3 列表检查范围，建议补（或在 4f 口径上显式裁决删除）。
4. **format="" 运行时未按默认补全 —— 未覆盖**。校验器黄提示「已按默认格式补全」（validator L1443-1448），但 prefix_wiring 将空串原样传给 render（prefix_render 仅在 `format_template is None` 时用默认，L71）→ 运行时 **无前缀**（补全语义与提示文案不一致）。建议 read_message_prefix_settings 对空 format 归一为默认/None。
5. **品质筛选无 items.json 品质兜底 —— 数据归一缺一环**。`_row_fields` 品质取自行字段、缺省 "normal"（L511/L518），未像 `_row_type_key`（L621-634）那样回退 items.json 定义；若 inventory 行未带 quality 而 def 有品质，`品质 史诗` 等筛选会漏判。建议镜像 type 的 def 兜底口径。
6. **/进入 /休息 壳层无注册门槛 —— 与 basic 指令 `_gate` 口径不一致**。RUL-08「未注册玩家使用任何游玩指令 → 统一拦截」，basic_commands 各指令入口调用 `_gate`（L570/745），explore_commands 未做；当前无装配层集中拦截 → 未注册玩家可触发 /进入 /休息。建议壳层补 `_gate` 或批次7 装配统一拦截。

---

## 三、维度② 错误（重点核对）

### P1-1　cmd_bag_filter 页码非法处理缺失（裁决②违反 + 崩溃风险）

- **位置**：basic_commands.py `_parse_filter_args`（L659-694）/ `_render_rows_page`（L717-736）/ `cmd_bag_filter`（L739-758）
- **现象（静态推导）**：
  - `/背包筛选装备 0`：`"0".isdigit()` 为 True → `page=0`（L668-670）→ `_render_rows_page` → `resolve_page(0, ...)` 返回 `invalid=True` → **抛出未捕获 `ValueError`（L723-726）**。应输出 TPL-12。
  - `/背包筛选装备 -1`：`"-1".isdigit()` 为 False → 被当作**子类筛选词** `sub_word="-1"` → 结果空 → 返回「❌ 背包空空如也」。应输出 TPL-12（负数页码，裁决②）。
  - `/背包筛选装备 abc`：同 `-1`，被当子类词 → 空背包文案（裁决②「非数字 → TPL-12」边界；abc 亦可被语法视为裸子类词，需裁决口径，但 0/-1 两项为确定违反）。
- **对照契约**：裁决②（3d 尾注 / 4f RUL-16）「0/负数/非数字 → TPL-12 报错」；cmd_bag 本身经 `parse_page_arg` 正确处理（L580-582），筛选链路径漏做。
- **修复建议**：`_parse_filter_args` 末尾：尾随 token 为纯数字且 `int < 1` → 返回非法标记，`cmd_bag_filter` 转 `format_tpl12(_fragment(parsed))`；尾随非数字 token 无法识别为合法子类/品质词时按页码非法处理（或显式裁决裸词容错范围），并在 test_explore_filter 补 0/-1/非数字 用例。

### 核对通过项（无错误）

- **门控顺序 enabled→per_channel→show_on_system**：prefix_wiring L189-201 实现顺序与模块头文档 L168-171 一致；三者为 AND 关系、任一不满足 → 原样正文，与定稿 §五.1/§五.2、3d TC-24/TC-25 语义**完全等价**（顺序不影响结果）。✅ 与 3h §6.1 口径一致（message_prefix 消费归属 3d + 定稿§九）。
- **render_prefix 真实签名调用（[群名]/[职业] 经 extra）**：prefix_render `render_prefix_result(level, name, title, *, format_template, hide_when_empty, empty_title_text, prefix_max_len, extra)` 与 shared_contract IF01b 逐参一致；apply_message_prefix 以 `format_template=cfg["format"]` + `extra=extra` 委托（L203-210），`[群名]/[职业]` 经 extra 替换（prefix_render L105-107）。✅
- **cmd_bag_filter 页脚 TPL-08（单页不输出 D-02）与夹取（裁决②）**：`render_footer` 单页（total_pages<=1）返回 ""（list_render L140-142）；`_render_rows_page`/`_render_bag_page` 在 `res.clamped` 时追加 LAST_PAGE_HINT（L731-732）；页脚指令名用 BAG_FILTER_CMD（「/背包筛选 页码 翻页」）。✅（正常页码路径；非法页码见 P1-1）
- **strip_icon_emoji 剥离范围与 test_emoji_discipline WHITELIST 一致性**：`_EMOJI_CLASS`（emoji_sanitize L23-32）挖掉 ✅(2705)/❌(274C) 两码位 → 保留功能性标记；剥离范围 ⊇ 测试扫描正则（含 2600-27BF / 1F000-1FAFF / 1F1E6-1F1FF / FE0F / 200D），并额外覆盖 2300-23FF、2B00-2BFF；排版符号（| → × / 「」【】）均不在剥离/扫描范围 → 保留。WHITELIST 子串 = `_EMOJI_CLASS` 拼接常量片段 1-6 前缀，覆盖整常量（含 FE00-FE0F/ZWJ）→ 静态推导测试通过。✅
- **校验器 MP-1/MP-2 红黄分类与定稿 §九 逐条核对**：红拦 MP-1 = enabled 非布尔（L1422-1426）/ format 非字符串（L1429-1433）/ prefix_max_len 负数（L1435-1440）/ 段结构错误 null·非对象（L1410-1420）——对应定稿 L112-114；黄提示 MP-2 = 未知占位符（L1451-1454，定稿 L117）/ format 空补全（L1443-1448，L118）/ format 超长>80 或占位符>10（L1456-1461，L119）/ per_channel 非法按 all（L1464-1469，L120）/ prefix_max_len>200（L1471-1476，L121）。**逐条齐全、分类正确、文案与定稿一致**。✅

---

## 四、维度③ 幻觉

- **未发现编造校验规则**：validator MP-1/MP-2 全部有定稿 §九 对应条款，无自创红/黄规则；「结构错误 = 段形态错误（必填缺失解释）」有文档化推理（L1396-1398：字段全有默认值 → 段内无强制必填键）。✅
- **未发现编造定稿行号引用**：抽查 prefix_wiring L19（L42 enabled 总开关 ✓）/ L21（L100 截断黄提示 ✓）/ L65（L45 per_channel ✓）、validator L1392（§九 L112-121 ✓）、3d 附·校验器行 L358 实际为「校验器（4.5）新增 message_prefix 校验行」一行 ✓。全部对上。✅
- **编造/过度声明（P2）**：
  - prefix_wiring 头注释 L16/L26「装配层（on_command）统一注入、所有指令出口」——当前仓库仅 battle_commands 消费，**过度声明**（见缺漏 2.2-1）。
  - explore_commands `_tpl12`（L35-37）与 cmd_rest 手写「❌ 指令不正确：…」（L108）复制 TPL-12 文案而非引用 sender.format_tpl12 / errors.py 唯一源——违反 3d §5.4 D-04「禁止自写等价文案」（文案当前逐字一致，属工程补白自述「字面量同源」，但漂移风险真实存在）。sender 与 explore_commands 同属 commands/ 层，依赖方向允许，可直接 import。（P2）

---

## 五、维度④ 跨文档

- **m5_shared_contract §一 与实现逐条对齐**：7 字段类型/默认值（§1.1）与 `DEFAULT_MESSAGE_PREFIX_SETTINGS` 一致；占位符 5 个（§1.2）与 validator `MESSAGE_PREFIX_PLACEHOLDERS`（L321）一致；IF01/IF01b 签名（§1.3）与 prefix_render 一致；TPL-01~06 渲染与 §1.3 一致。✅
- **m5_shared_contract §四 与实现逐条对齐**：唯一允许 ✅❌、排版符号豁免、禁用清单与 emoji_sanitize/测试一致；「登记表 = ✅❌ + 排版符号豁免，无其他 emoji 出口」成立；「数据型功能图标一律降级纯文本」在 basic_commands `_item_icon`/`_row_fields` 走 strip_icon_emoji 落实。✅
- **登记表 ↔ test_emoji_discipline 白名单互指一致**：登记表 §四 所述 `_ALLOWED={✅,❌}`、`WHITELIST` 仅登记 emoji_sanitize 字符类定义、`test_registry_allowed_markers` 断言白名单恒等 `{✅,❌}`、`test_strip_icon_emoji_registry_contract` 断言保留/剥离/容错——全部与实现逐条吻合。✅
- **battle_render 接口签名（§五）**：`render_battle_start(party, enemy, hint=None)` / `render_battle_round(round_result)` / `render_battle_end(player, enemy, winner, summary=None)` 与 §5.1 IF30/31/32 一致（签名不改）。✅
- **P2 陈旧引用**：basic_commands.py L30-31 头注释仍写「数据型物品 icon 豁免 m4 §2.2」——该条款已被 M5 裁决**作废**（登记表 §三 作废登记 / shared_contract §4.1「M4 契约 §2.2 豁免条款作废」）。实现行为已按新口径（icon 剥离），仅注释未回写。建议同步删除/改写该豁免字样。

---

## 六、无问题维度确认

1. ✅ D1 前缀 7 字段消费（enabled/show_on_system/per_channel/hide_when_empty/empty_title_text/prefix_max_len/format）全覆盖。
2. ✅ 截断黄提示发射（truncated → PREFIX_TRUNCATED_HINT，battle 管线归属发起群发送，不阻断正文）。
3. ✅ apply_message_prefix 门控顺序与定稿/3d 语义一致。
4. ✅ render_prefix_result 真实签名 + [群名]/[职业] 经 extra。
5. ✅ 筛选链 类型→子类→品质 三链叠加全实现 + 分页 + TPL-08 页脚 + 裁决②夹取（正常页码路径）。
6. ✅ strip_icon_emoji 剥离范围（✅❌保留、排版符号保留、emoji 剥离）与登记表/测试白名单一致。
7. ✅ 校验器 MP-1/MP-2 红黄分类与定稿 §九 逐条一致（含行号引用正确）。
8. ✅ 探索壳 /进入 /休息 结果 1 条；/采集 DELAYED 文档登记理由完整。
9. ✅ 登记表 ↔ test_emoji_discipline 白名单互指一致。
10. ✅ battle_render 接口签名与 shared_contract §五 一致。
11. ✅ 无编造校验规则 / 无编造定稿行号引用。

---

## 七、分级问题清单（文件行号 + 修复建议）

### P1（1 项）

**P1-1　cmd_bag_filter 页码非法 → 崩溃 / 语义错位（裁决②违反）**
- 文件：`qbot_rpg/commands/basic_commands.py` L659-694（_parse_filter_args）、L717-736（_render_rows_page）、L739-758（cmd_bag_filter）
- 现象：`/背包筛选装备 0` → page=0 → resolve_page invalid → 未捕获 ValueError；`/背包筛选装备 -1`/`abc` → 被当子类筛选词 → 「❌ 背包空空如也」。均应为 TPL-12（0/负数/非数字，裁决②/3d §2.2/4f RUL-16）。
- 修复：尾随纯数字 token <1 → 转 `format_tpl12`；尾随无法识别为非筛选词的 token → 按页码非法 TPL-12；补 test_explore_filter 非法页码用例。

### P2（8 项）

| # | 问题 | 位置 | 建议 |
|---|---|---|---|
| P2-1 | 前缀挂首行仅战斗出口；prefix_wiring 头注释「装配层统一注入」过度声明 | prefix_wiring L16/L26；battle_commands L406-517；basic/explore register_* | 验收注明批次A 前缀接线范围=战斗管线+纯函数就绪；批次7 装配统一注入补全非战斗出口 |
| P2-2 | 私聊 [群名]="私聊" 兜底未实现 | prefix_wiring L155-220；定稿 §五.5 / §1.2 | apply_message_prefix 内 channel=private 且缺「群名」extra 时注入「私聊」 |
| P2-3 | /背包 首行「【背包 · 第 X/Y 页】」头部缺失（4f TC-11/TPL-4F-04） | basic_commands L546-565；test_basic_commands L256 | 补头部或显式裁决删除该 4f 口径 |
| P2-4 | format="" 运行时未按默认补全（校验器提示与实际渲染不一致） | validator L1443-1448；prefix_wiring L131-132/L203-210；prefix_render L71 | read_message_prefix_settings 对空 format 归一默认/None |
| P2-5 | explore_commands 自写 TPL-12 文案（D-04 违反） | explore_commands L35-37/L108 | 改 import sender.format_tpl12 / errors.py 唯一源 |
| P2-6 | 品质筛选无 items.json 品质兜底（与 type 兜底口径不一致） | basic_commands L505-528 vs L621-634 | _row_fields 品质缺省回退 def；按 4b INV-xx 确认 quality 行归属 |
| P2-7 | /进入 /休息 壳层无 RUL-08 注册门槛（与 basic _gate 不一致） | explore_commands L80-120 | 壳层补 `_gate` 或批次7 装配统一拦截 |
| P2-8 | basic_commands 头注释仍引用已作废「m4 §2.2 数据型 icon 豁免」 | basic_commands L30-31；登记表 §三 | 回写注释，删除已作废豁免字样 |

### 信息提示（非缺陷）

- **3h 引用口径**：任务指定「细化_3h_消息前缀功能设计.md（V9~V12 校验器）」——该文件名不存在，实际为 `细化_3h_settings通用设置.md`；其 V9~V12 为 settings 通用黄提示（数值过大/满级经验转换/未登记键/声明冲突），§6.1 明确 message_prefix 红黄按 3d 附 L332 + 定稿§九、**不重复覆盖**。实现（validator MP-1/MP-2）正确按定稿§九落地，无实现缺陷。
- **test_emoji_discipline WHITELIST 脆性**：白名单子串依赖 `_EMOJI_CLASS` 拼接常量经 CPython 相邻字面量折叠后含该子串；若未来拆行/改写，FE00-FE0F/U+200D 片段将不被覆盖 → 误报。建议改整常量精确匹配或拆分登记（低风险，静态推导）。

---

*审查结论：P0×0 / P1×1 / P2×8 / 信息提示×2。批次A 主体实现与契约、细化、定稿对齐良好，无 P0；唯一 P1 为筛选页码边界缺陷，建议修后放行。*
