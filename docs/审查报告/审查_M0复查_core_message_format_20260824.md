# 审查_M0复查_core_message_format_20260824

> 批次：M0 复查 · 批3-路2 · 消息模板 message_format
> 审查对象：`qbot_rpg/core/message_format/{prefix_render,panel_render,battle_render,__init__}.py`（实读 139/106/50/1 行，共 296 行）
> 对照基准：`细化_3d_消息模板规范.md`（前缀三态 TPL-01~06 / §二 列表分页 / §三 长度控制 / §四 功能性标记 / §五 错误模板 / TC-01~26）+ `细化_3a_架构分层契约.md` §5（S1~S6 纯字符串契约）
> 辅助核对：`实现层规划文档.md`（D1-D5 / M5 里程碑）、`细化_3h_settings通用设置.md` §6.1（message_prefix 7 字段）、`细化_3b` §4.2/§4.4、`细化_4c`（title_state）、`commands/errors.py`、`tests/{contract/test_message_format.py,unit/test_core.py,conftest.py}`、前批 `审查报告/审查_M0_coredata_20260818.md`
> 审查方式：**纯静态**（read/grep/glob 只读比对，本环境无 bash 沙箱，未运行任何命令/脚本/验证）；所有运行行为结论为「静态推导」。

**关键背景（影响分级）**：消息模板 D1~D5 按《实现层规划文档》§8 属 **M5 里程碑**（L3480「M5 消息模板 | 渲染层 | D1-D5」）；本批复查前批（2026-08-18 `审查_M0_coredata`）对 message_format 提出的 P1-2/P1-3 修复闭环情况与 P2 递延项现状。外部定稿【前缀】（docs_archive）工作区不可直读，其行号引用（L22/L43/L48/L57 等）遵循仓库既有约定并以已发布的《幻觉审查_3d.md》背书。

---

## 〇、结果总览

| 级别 | 数量 | 摘要 |
|---|---|---|
| 🔴 P0（必改） | 0 | 无当前运行阻断项 |
| 🟡 P1（应改） | 1 | render_panel/render_stats_line 只读 base 白值层，面板显示值≠战斗最终属性；注释「加成已含于存档 base 白值，M0 口径」失实（前批 P2-6 未闭环且证据加强） |
| 🟢 P2（建议） | 9 | 模板注册表 TPL-07/08/09/10/11 零实现（前批 P2-3 仍开放）；settings.message_prefix 零消费；测试 `or True` 空转断言+覆盖缺口；P1-3 截断信号仅 API 层闭环；paginate 非 int 页码 TypeError（前批 P2-10 仍开放）；TP-02 编号错引；_worn_title 探测式取键；截断 len()/emoji 边界；extra 覆盖内建占位符 |

**① 错误 3（P1×1 + P2×2）　② 缺漏 3（P2×3）　③ 幻觉 3（P2×3）**

---

## 一、🔴 P0

**无。** 前缀三态、5 条/页分页、纯字符串契约（S1/S2/S3）、emoji 纪律核心路径经逐字核对全部正确（见 §四）。

---

## 二、🟡 P1

### P1-1（①错误 · 面板数据口径 + ③幻觉 · 注释冒充口径）render_panel/render_stats_line 只读 `attributes.base` 白值层；注释「加成已含于存档 base 白值，M0 口径」失实

- **位置**：`panel_render.py:48-55`（render_stats_line 取 `attributes.base`）、`:71-72`（max_hp/max_mp 取 `attributes.base.get("hp"/"mp")`）、`:80`（注释「加成已含于存档 base 白值，M0 口径；完整管线见 core.player_attributes」）、`:81`。
- **实际（静态推导）**：
  - 3b §4.4 / player_attributes.py:261 明确「base 即工厂已算好的**白值**（base+growth×lv+加点）」；加成层 `bonus{flat,pct}`、`temp{pct,flat}`、`cond` 为独立层，**不并入 base**（3b 术语表 L18-24）。
  - 本仓自带 fixture `tests/conftest.py:56-58` 的 Player 已含非空加成层：`bonus={"flat":{"str":5.0},"pct":{"hp":10.0}}`。按当前实现，面板属性简况行将显示 `力量 15`（仅 base），而 `calc_all_final_attributes`（battle 实际消费）结果为 **20**；HP 上限显示 100 而非 110 → 面板与战斗实际数值不一致，用户可见。
  - 注释所称「M0 口径」在 3b/3a/3d 均无任何定义（三文档只有「base=白值、加成分离」，无「加成并入 base」说法），属**冒充口径**的工程补白标注。
  - 前批（2026-08-18）P2-6 已点名并要求「注释口径需更正或标注」——**复查未闭环**，注释原样保留。
- **修复**：`render_stats_line`/`render_panel` 改为消费 `core/player_attributes.calc_all_final_attributes(player.attributes)`（加成/临时/条件层并入），hp/mp 上限同步用最终值；或至少把注释改为「M0 占位：仅白值层，加成/临时层待 M5 D5『/角色 三层展示』接入 calc_all_final_attributes」，并补一条 fixture 断言（base 有加成时面板值=最终值）。

---

## 三、🟢 P2

| # | 维度 | 位置 | 问题 | 建议 |
|---|---|---|---|---|
| P2-1 | ② | 全库（`panel_render.py:4-5,90` 声明页脚壳层拼装；`commands/errors.py:23-25` 仅 TPL-12/13/14） | **模板注册表零消费**：TPL-07 条目行 / TPL-08 页脚 / TPL-09 折叠行 / TPL-10·11 ✅❌ 标记 全库无常量落点（grep 零命中）；3d D-05「各系统渲染器按 ID 引用，禁止散落硬编码」无锚点，TC-12（页脚逐字）/TC-14（折叠）/TC-16·17（✅❌ 标记）当前不可达。**前批 P2-3（“M1 前补全 14 条”）仍开放**。分页页脚让各业务渲染侧自拼 → 违反 3d §2.3「页脚固定 TPL-08」 | M5 D3/D4 收口时在 message_format 增设模板常量表（TPL-07~11 逐字 + paginate 返回可拼页脚/折叠行），作为 TC-18 grep 锚点；登记待办 |
| P2-2 | ② | `prefix_render.py:55-134` 参数化但零消费；`commands/parsers.py:45`、`errors.py:37` 均为 M4 骨架 | **settings.message_prefix 7 字段零消费**（3h §6.1 / 3d 附-衔接表）：`enabled/format/hide_when_empty/empty_title_text/prefix_max_len/show_on_system/per_channel` 无任何读取方 → TPL-03/04/05/06 仅测试/API 可达、系统路径不可达；3d §九 校验器红黄六类（未知占位符黄提示、format 空补全、>80/占位符>10 黄、per_channel 枚举、结构红拦）零实现。模块 docstring L8-9 称「调用方（壳层/内容包 settings 消费处）控制」——当前不存在该消费处 | M5 D1 按实现层规划 L3295 接线 settings 段 + 3e 校验器；在此之前文档注明「settings 消费为 M5 待办」防误读为已闭环 |
| P2-3 | ① | `tests/contract/test_message_format.py:24`、`:1` | **测试空转 + 覆盖缺口**：L24 `assert "@" not in s.split("\n")[0] or True` 恒真（`or True` 空转，任何输入恒过），违反 G1「verify 必须可执行且有断言，禁『人工看了没问题』」；文件头声明「细化_3d#TC-12~19」与实际覆盖（TC-07/08/11 + S 契约 + emoji 扫描）不符；TC-04（`empty_title_text=""`）、TC-05/06（TPL-05/06/未知占位符）、TC-13（截断+truncated 信号）无断言（`test_core.py:87-90` 仅覆盖 TPL-01/02/03） | 删除 `or True` 改为真实断言（全文无 `@`）；修正头部声明；补 TPL-04 与 render_prefix_result.truncated 用例 |
| P2-4 | ① | `prefix_render.py:47-53,55-114`（PrefixResult/render_prefix_result）vs `panel_render.py:67` | **P1-3 修复仅 API 层闭环**：截断信号已做成可观察事件（PrefixResult.truncated，前批 P1-3 ✓），但唯一生产调用方 `render_prefix` 纯 str 路径；`render_prefix_result` 全库零生产消费 → 经面板/正常前缀路径 TC-13「前缀过长已截断」黄提示仍不可达 | 壳层/面板接线时改走 `render_prefix_result` 并转发 truncated → 黄提示；或把截断+提示职责整体移交壳层（3d §3.3 归属 sender） |
| P2-5 | ① | `panel_render.py:101-104` | **paginate 非 int 页码抛 TypeError**（`page < 1` 对 str 触发）而非约定异常（**前批 P2-10 仍开放**）；且异常消息 L102-104 含人话片段+实现指引（「页码 5 越界…壳层应转 TPL-12」），壳层若误转发即违反 3d §5.4 统一文案/3a R4 | 入口类型守卫统一抛 IndexError/ValueError（或领域异常 `PageOutOfRange`）；消息改纯诊断标识；docstring 注明壳层先经 M4 parsers 安全 int 解析 |
| P2-6 | ③ | `prefix_render.py:4-7`（docstring「TP-02/TP-03/TP-04」） | **模板编号错引**：3d §1.2（L70）明示「TP- 前缀字段引用 message_prefix settings 段字段名」；模板 ID 应为 **TPL-02/03/04**（同文件 L89 已正确用 TPL-）。「TP-02」指向不存在对象（settings 无该字段、模板表无 TP-02 条目），且与本文件 L5-7 上下文混淆 | 三处 TP- 全部改 TPL-02/03/04 |
| P2-7 | ② | `panel_render.py:35-45`（_worn_title 探测式取键） | **title_state 键名未固定**：4c（L224）定 title_state=已拥有集合+当前佩戴 ID，键名未固定；`_worn_title` 探测 current/title/worn/佩戴 四键+首非空值兜底——若真实键不在探测名中，兜底可能取到「已拥有集合」串 → 前缀 [称号] 显示错误集合文本 | 随成就批登记 title_state 键名后对齐（探测四键改为读取定稿键），删除非空值兜底或改为显式键 |
| P2-8 | ① | `prefix_render.py:111-113` | **截断按 len() 码点数**，非显示宽度（CJK 显示 2 列宽仍计 1）；可切断多码点/ZWJ 序列；且 3d §4.1/TC-19「前缀禁 emoji」依赖[称号]名合规——[称号] 为透传替换，若称号名含 emoji 渲染层无过滤（S5 不吞内容）即输出违规 emoji | 截断至少保证码点边界（不切代理对）；文档注明 len()=码点口径；前缀禁 emoji 依赖上游称号名/校验器（3d §九），渲染层职责写清即可 |
| P2-9 | ① | `prefix_render.py:104-107` | **extra 后替换可覆盖内建占位符**：built-in 替换（等级/玩家名/称号）在 extra 循环**之前**，`extra={"等级":...}` 等会覆盖内建结果 → 顺序耦合、未文档化 | built-in 替换后置，或 docstring 注明 extra 仅用于 [群名]/[职业] 等未知键（群/职业属平台信息由壳层注入） |

---

## 四、无问题维度确认（✅）

1. **前缀三态与分页核心路径正确（静态推导）**：TPL-01 `Lv35.阿伟 -斩龙者-`、TPL-02 `Lv35.阿伟 - -`、TPL-03 `Lv35.阿伟`（hide_when_empty，尾空格清理）、TPL-04 `Lv35.阿伟 - -`（empty_title_text=""，装饰符保留）逐字核对与 3d §1.4/TC-01~04 一致（`test_core.py:87-90` 断言 TPL-01~03）；`[称号]` 任意顺序/重复/单侧装饰/无装饰 format 均有 fallback 不再泄漏；未知占位符原样透传（TC-06）；paginate 12→3 页 5/5/2、0 条→1 页、单页无页脚由渲染侧判（3d §2.1/D-02）均正确。
2. **纯字符串契约 S1~S6**：四个模块全 `str` 输出（paginate 返回 tuple 属工具）；无 `[CQ:`、无 at/图片占位、无群号语义（D-06，[群名] 由壳层以 extra 注入而非渲染层感知群号）；渲染层不截断正文（S5）；前缀不计入正文长度由调用方语义保证（§3.3）。
3. **emoji 纪律**：prefix_render 输出无任何 emoji（含 ✅/❌，3d §4.1 前缀区禁）；panel 输出无禁用清单字符（test_message_format.py:27-35 覆盖）；生产代码零禁用 emoji。
4. **前批 P1-2 / P1-3 / P2-7 修复闭环 ✓**：`[称号]` 泄漏 fallback（prefix_render.py:84-85,95-96，对应 20260818 P1-2）、截断可观察事件 PrefixResult（L47-53，对应 P1-3）、未用 import 已删（原 P2-7）——「P1-2 修复」「P1-3 修复」标注**属实**，非冒充（P1-3 仅 API 层闭环，系统路径缺口见 P2-4）。
5. **幻觉维度主体无虚构**：模块引用的 3d §1.2/§1.4/§3.3、3a §5.2 S6、细化_1g2/1a/5e（battle_render 依据）均真实存在且内容相符；【前缀】L22/L43/L57/L48 等外部行号经已发布《幻觉审查_3d》背书（L22 默认格式/L43 字段/L48 prefix_max_len 40/L57 字段行）；「细化_3b §4.2 / L14-24」中 §4.2（StatDef）真实、L14-24 系沿 3b 表内对外部【属性定稿】的转引（外部不可核验，遵循仓库约定，非本文件编造）；仅 TP- 编号错引（P2-6）与「M0 口径」冒充（P1-1）两处注释纪律问题。
6. **battle_render M1 骨架符合里程碑**：三函数诚实 `NotImplementedError(_NOT_IMPL_MSG)` + TODO(M1) 标注，零业务假实现；职责/归属（3a §2.1/§5）与 S4 合并语义描述正确；引用文档全部实存。`__init__.py` 单行包文档正确（D-04 定位）。

---

## 五、结论

- **P0×0 / P1×1 / P2×9**。无当前运行阻断项，前批 P1-2/P1-3 已闭环；本批核心新发现为 P1-1（面板白值口径+注释失实，前批 P2-6 未闭环且本仓 fixture 已物化加成层）。
- **Top 3**：
  1. **P1-1** 面板只读 base 白值 → 显示值≠战斗最终属性（fixture 已带 bonus/temp）；注释「加成已含于存档 base 白值，M0 口径」失实、冒充口径，需改消费 calc_all_final_attributes 或诚实标注 M0 占位。
  2. **P2-1** 模板注册表 TPL-07/08/09/10/11 零实现零注册（前批 P2-3 仍开放）——D-05 程序化锚点缺失，TC-12/14/16/17 不可达，M5 D3/D4 前必须补页脚/折叠/✅❌ 常量。
  3. **P2-2/P2-3** settings.message_prefix 7 字段零消费（TPL-03~06 系统路径不可达）+ 测试 `or True` 空转断言与 TC 覆盖缺口（G1 verify 纪律）——M5 D1 接线与测试补强前，「模板三态可配」能力仅是 API 层面的存在。
- 修复次序：P1-1（注释诚实化 + 面板改最终值）→ P2-1（模板常量表）→ P2-3（空转断言清理 + 补 TPL-04/TC-13 用例）→ 其余随 M4/M5 接线收口。

*全部结论为静态推导（本环境禁止运行命令/脚本/验证）。*
