# 审查_M5细化_批次1（D1 message_prefix + D2 统一发送出口）

> 门控档位：**full**（j-space 全量；唤醒→门控→接缝审计→ship 已执行；本环境无 bash 沙箱，未运行任何命令/脚本，全部结论为**静态推导**）
> 审查对象：`docs/m5_shared_contract.md`（主：§〇/§一/§二/§六/§七）· `docs/m5_batch_plan.md`（M5-01/02/06）· `docs/细化/细化_3d_消息模板规范.md`（§1.5/§3.1/§3.4）· `qbot_rpg/core/message_format/prefix_render.py`（139 行）· `qbot_rpg/commands/sender.py`（192 行）· `docs/审查参考/消息前缀功能设计定稿.md`（【前缀】）
> 交叉核对：`细化_5e`（BREP 注册表/TC）· `细化_4f`（CMD-09/TC-25~28/RUL-16/TPL-4F-13）· `细化_3h`（§6.1/V9~V12/§11.2）· `errors.py`·`list_render.py`·`battle_render.py`·`panel_render.py`·`basic_commands.py`·`content/validator.py`·`router.py`·`tests/unit/test_sender.py`·`docs/审查/m5_素材提取.txt`
> 方式：read/grep/glob 静态核对；代码事实以 read 为准；运行类行为（如某批跑起来会 TypeError）标注「静态推导」。

## 结论汇总

**P0 = 0 · P1 = 2 · P2 = 7**

| 编号 | 级别 | 一句话 |
|---|---|---|
| P1-1 | P1 | IF01 `render_prefix` 契约签名与已实现代码签名不符（首参/占位符入参/返回类型全对不上） |
| P1-2 | P1 | message_prefix 校验器规则被误标为「3h V9~V12」，3h §6.1 明示 V9~V12 不覆盖 message_prefix，真实规则源为【前缀】§九 |
| P2-1 | P2 | §1.4「enabled 字段消费 ✅ prefix_render 内」标注不实（prefix_render 无 enabled 参数，消费在 M5 装配层） |
| P2-2 | P2 | IF11 参数名契约写 `limit`，实现为 `budget`（关键字调用会 TypeError） |
| P2-3 | P2 | 「前缀过长已截断」黄提示接线（3d §3.3/TC-13，消费 `PrefixResult.truncated`）无任何批次认领、契约 ⬜ 矩阵未列 |
| P2-4 | P2 | 3d §3.4 第 5 项「渲染层长度预算统一（共用长度预算常量）」未纳入 D2 契约 |
| P2-5 | P2 | batch_plan M5-02 验收引用「3d 附 L332」；当前 3d 该行为空白，附表在 L352-363（校验器行 L358） |
| P2-6 | P2 | （越界观察·D5）BREP-02 模板文本在 shared_contract §5.2 与 batch_plan M5-03 两处均与 5e 逐字不符 |
| P2-7 | P2 | （越界观察·D5）IF30/IF32 契约签名与 battle_render.py 骨架签名不符 |

---

## 一、P1 问题

### P1-1　IF01 `render_prefix` 契约签名与已实现代码不一致（契约自诩「实现层唯一依据」，误导性最高）

- **位置**：`docs/m5_shared_contract.md` §1.3 IF01（L52）
- **契约原文**：
  `IF01 render_prefix(format: str, *, level, name, title, group_name, job, hide_when_empty, empty_title_text, prefix_max_len) -> PrefixResult`
  （并标注「prefix_render.py 已实装」）
- **实现真实签名**（`qbot_rpg/core/message_format/prefix_render.py` L117-134）：
  ```python
  def render_prefix(level: int, name: str, title: Optional[str] = None, *,
                    format_template: Optional[str] = None, hide_when_empty: bool = False,
                    empty_title_text: str = "-", prefix_max_len: int = DEFAULT_PREFIX_MAX_LEN,
                    extra: Optional[Mapping[str, object]] = None) -> str
  ```
  截断信号入口为 `render_prefix_result(...) -> PrefixResult`（L55-114）。
- **逐项差异**：
  1. 首位置参数：契约 `format: str`；实现为 `level: int`（`format` 是只读关键字参数 `format_template`）。
  2. `group_name` / `job`：实现**不存在**这两个参数；[群名]/[职业] 经 `extra: Mapping[str, object]` 传入（`extra={"群名":…,"职业":…}`）。
  3. 返回类型：契约 `-> PrefixResult`；实现 `render_prefix -> str`（`PrefixResult` 由 `render_prefix_result` 返回）。
- **影响（静态推导）**：M5-01 装配层若照契约写 `render_prefix(format, level=…, group_name=…, job=…)`，将同时触发 `format` 位置错位、`group_name/job` 非法关键字、返回 str 却按 PrefixResult 取 `.truncated` 三类错误。契约头部声明「本契约 = 实现层唯一依据」，这是后续实现最大的误导源（边界 P0，按 doc 层错误记 P1）。
- **修复建议**：契约改写为
  `IF01 render_prefix(level, name, title=None, *, format_template=None, hide_when_empty=False, empty_title_text="-", prefix_max_len=40, extra=None) -> str`
  并补 `IF01b render_prefix_result(...) -> PrefixResult`（截断信号），注明「[群名]/[职业] 经 extra 传入」；M5-01 依据真实签名接线。

### P1-2　message_prefix 校验器规则被误标为「3h V9~V12」（幻觉引用）

- **位置**：`docs/m5_shared_contract.md` §1.4（L63）；`docs/m5_batch_plan.md` M5-02 标题与「依据」（L17/L19）
- **事实**：`docs/细化/细化_3h_settings通用设置.md` §6.1（L288）原文：
  > 校验：红黄规则按 3d 附 L332 + 【前缀】§九（…「前缀段红黄按【前缀】§九」）→ **本契约 V9~V12 不重复覆盖**。
  即 3h **明确排除** message_prefix 于 V9~V12 之外；3h 的 V9~V12（§11.2，L506-513）是 level_cap 超限/死亡惩罚比率/event_push 未登记键/modules 声明冲突等**通用黄提示**，与 message_prefix 无关。
- **真实规则源**：【前缀】§九（L112-121）+ 3d 附表校验器行（L358）。
- **修复建议**：shared_contract §1.4 与 batch_plan M5-02 的「3h V9~V12」改标「【前缀】§九 / 3d 附校验器行」；M5-02 内容中枚举的红/黄规则本身与【前缀】§九逐条一致（硬拦：enabled 非布尔/format 非字符串/prefix_max_len 负数/结构错误；黄提示：未知占位符/format 空补全/超长 >80/占位符 >10/per_channel 非法按 all/prefix_max_len >200），规则内容无编造，仅来源标注错误。

---

## 二、P2 问题

### P2-1　§1.4「enabled 字段消费 ✅ prefix_render 内」标注不实

- **位置**：`docs/m5_shared_contract.md` §1.4（L60）
- **事实**：`prefix_render.py` 无 `enabled` 参数，docstring（L8-9）明言「enabled 总开关/渠道限定/系统豁免等由**调用方**（壳层/内容包 settings 消费处）控制」。真正消费在 M5-01 装配层（⬜），与同表「show_on_system/per_channel 消费接线 ⬜」自相矛盾。
- **修复建议**：该行改「format/hide_when_empty/empty_title_text/prefix_max_len ✅ prefix_render 内；enabled/show_on_system/per_channel ⬜ M5 装配层消费」。（维度④「已实现✅ 项是否真实」核查：除本项外其余 ✅ 项均真实，见 §四。）

### P2-2　IF11 参数名契约 `limit` vs 实现 `budget`

- **位置**：`docs/m5_shared_contract.md` §2.1 IF11（L72）
- **事实**：契约写 `segment_by_length(text, limit=4000)`；实现（`sender.py` L68）为 `segment_by_length(text, budget=4000)`。默认值一致，关键字名不一致——按契约用 `limit=` 调用会 TypeError（静态推导）。
- **修复建议**：契约改 `budget`。

### P2-3　「前缀过长已截断」黄提示接线缺漏（3d §3.3 / TC-13 / 【前缀】L100）

- **位置**：缺漏——shared_contract §1.4 ⬜ 矩阵、batch_plan M5-01/02/06 均未认领
- **事实**：3d §3.3 / TC-13 要求截断后发黄提示「前缀过长已截断」（归属发起指令所在群，不阻断正文）。`prefix_render_result` 已返回 `truncated` 标志，但**无任何批次消费该标志发射提示**；M5-01 验收 ①~⑤ 均不含截断断言。
- **修复建议**：M5-01 装配层注入前缀时消费 `PrefixResult.truncated` → 发黄提示；验收增加 TC-13 断言；shared_contract §1.4 增 ⬜ 行「截断黄提示发射（装配层）」。

### P2-4　发送出口第 5 项「渲染层长度预算统一」未纳入 D2 契约

- **位置**：缺漏——`docs/m5_shared_contract.md` §二 未覆盖 3d §3.4 第 5 条（L204「渲染层长度预算统一：所有渲染路径共用长度预算常量，禁止各系统各自定上限」）
- **事实**：D2 契约 IF10-14 / 2.2 覆盖了 3d §3.4 的 统一出口/超长分两条/CQ 转义/失败重试 四项（与 3d L205「四项均已实装」口径一致），但未声明「共用长度预算常量」纪律（`sender.DEFAULT_LENGTH_BUDGET` 已存在，契约未引用为共享常量）。
- **修复建议**：§2.2 增行「渲染层长度预算统一（共用 DEFAULT_LENGTH_BUDGET，禁止各系统自定上限）」。

### P2-5　batch_plan M5-02 验收引用「3d 附 L332」为失效行号

- **位置**：`docs/m5_batch_plan.md` M5-02 验收（L21）
- **事实**：当前 3d（372 行）L332 为空白；「附：系统衔接一览」在 L352-363，校验器行为 **L358**。该引用系 3h L288 的历史行号照抄继承。
- **修复建议**：改「对齐 3d 附·校验器行（L358）」。

### P2-6　（越界观察·D5）BREP-02 模板文本两处与 5e 逐字不符

- **位置**：`docs/m5_shared_contract.md` §5.2（L139）；`docs/m5_batch_plan.md` M5-03（L26）
- **事实**：5e BREP-02 = `✅ 你{攻击动作}{目标}，造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`；shared_contract 只写 `…造成 {伤害} 伤害`（**丢 HP 后缀**）；batch_plan M5-03 写 `…（{目标} {HP}）`（**变量名不符**）。`m5_素材提取.txt` L60 与 5e 一致，证明两文档均偏离素材源。M5-06 一轮消息拼接/逐字验收依赖该模板。
- **修复建议**：两处统一为 5e 原文 `（{目标} {剩余HP}/{最大HP}）`。

### P2-7　（越界观察·D5）IF30/IF32 契约签名与 battle_render.py 骨架不符

- **位置**：`docs/m5_shared_contract.md` §5.1（L130/L132）
- **事实**：契约 `render_battle_start(ctx) -> str` / `render_battle_end(ctx) -> str`；实现骨架（50 行）为 `render_battle_start(party, enemy, hint=None)` / `render_battle_end(player, enemy, winner, summary=None)`。M5-03 实装前需对齐，否则与既有骨架签名冲突。
- **修复建议**：M5-03 开工前统一签名（保留骨架参数或一并修订契约）。

---

## 三、缺漏维度点名「契约应覆盖 X 但未覆盖」清单

1. **契约应覆盖「前缀过长已截断」黄提示接线（3d §3.3 / TC-13 / 【前缀】L100：截断后发黄提示、归属发起群、不阻断正文）但未覆盖**——shared_contract §1.4 ⬜ 矩阵无此行，batch M5-01/02/06 无批次认领 `PrefixResult.truncated` 的消费（→ P2-3）。
2. **契约应覆盖「渲染层长度预算统一（所有渲染路径共用长度预算常量，禁止各系统各自定上限）」（3d §3.4 第 5 条）但未覆盖**——D2 只覆盖四项，未声明长度预算共享纪律（→ P2-4）。
3. **M5-01 任务划分应含 prefix_max_len 截断提示接线但未含**——M5-01 内容只列 show_on_system/per_channel/enabled + 首行注入，验收 ①~⑤ 无截断/黄提示断言（并入 P2-3）。
4. （确认无缺漏）D1 的 7 字段/5 占位符/显示规则五条/合并策略四条+单次上限/发送出口四项，以及 M5-02 的红黄规则内容、M5-06 的一轮 1 条/开始结束 1 条/探索 1 条/无裸 send 划分，均已覆盖（见 §四）。

## 四、无问题维度确认（含已实现/待实现衔接核对）

- **7 字段默认值/枚举 vs 【前缀】§三 逐字段一致**：enabled(true)/format(`Lv[等级].[玩家名] -[称号]-`)/show_on_system(false)/per_channel("all", all/group/private)/hide_when_empty(false)/empty_title_text("-")/prefix_max_len(40) —— 全部一致，无编造字段。
- **5 占位符 vs 【前缀】§四 / 3d §1.3**：[等级]/[玩家名]/[称号]/[群名](私聊="私聊")/[职业] 名称与取值来源一致。
- **显示规则（【前缀】§五 5 条）**：仅玩家相关回复/渠道限定/只加合并消息首行/不影响解析/私聊群名兜底 —— 契约铁律 1 + §1.1/§1.2/§1.4 全数覆盖。
- **合并策略 4 条 + 单次上限（3d §3.1 承接表）**：战斗一轮/开始/结束/探索各 1 条 + 单次 ≤1-2 条 —— 铁律 2 + §2.2 ⬜ 行覆盖，承接方标注正确。
- **发送出口 4 项**：统一出口/超长分两条/CQ 转义/失败重试 —— IF10-14 + §2.2 覆盖且实现真实（第 5 项见 P2-4）。
- **TPL-01~06 与 3d 逐字一致**：六条模板文本逐一比对无差异。
- **铁律 10 条出处引用真实**：3d §3.1/§3.4/§五/D-01、5e 军规 2/4/D-5D、4f §2.5/裁决①③、框架 §8.3/§15.7、开发规则 L509、【前缀】§七 —— 全部核对通过。
- **TC 矩阵（§六）**：3d 26 = 6+6+3+4+3+4；5e 27 = 6+5+4+5+3+4；4f 28（TC-25~28 为 /角色）；合计 81 —— 与 3d/5e/4f 覆盖矩阵一致。
- **批次划分（§七 ↔ batch_plan 批0~批3）**：一一对应；依赖与锚点（TPL-01~14/BREP-01~25/TPL-4F-13/TPL_REGISTER_GATE/errors.py）均真实存在。
- **已实现✅ 项真实性**：prefix_render.py **139 行**、sender.py **192 行**、list_render.py **201 行**、battle_render.py **50 行骨架**（三个函数均为 NotImplementedError 骨架）—— 行数与契约精确一致；panel_render（含 render_prefix 调用）、basic_commands.cmd_view/attr_line（4f RUL-37/38 口径）、format_tpl12/13/14、errors.py TPL-12/13/14 与 3d 逐字一致 —— 全部真实。（唯一例外 = enabled ✅ 标注，P2-1。）
- **待实现⬜ 项真实缺失**：show_on_system/per_channel 全仓零消费（grep 0 命中）；前缀挂首行仅 panel_render 单出口已用、统一注入未做（router.py 无 message_prefix 注入）；message_prefix 校验器（content/validator.py 1686 行无 message_prefix 分支）；消息合并（battle_render 为骨架）；全仓禁裸 send 静态检查（verify_m5 不存在，scripts/run_all_tests.py 存在可接入）—— 全部确为缺项。
- **5e P2-8 一致性**：契约 §5.1「不直接复用引擎 ActionOutcome.message」与 battle.py 实际 `message=f"{attacker} 对 {target} 造成 {damage.get('final',0)} 伤害"`（素材提取 L190 同）句式差异核对一致，注释成立。

## 五、核对底稿（关键一行一证）

- IF01 错证：prefix_render.py L117-134 与 shared_contract L52。
- 3h V9~V12 错证：3h L275-288（§6.1 明示不覆盖）+ L506-513（§11.2 V9~V12 定义）vs shared_contract L63 / batch_plan L17-19。
- enabled 错证：prefix_render.py L1-15（docstring L8-9）vs shared_contract L60。
- IF11 错证：sender.py L68-71 vs shared_contract L72。
- 截断黄提示缺漏证：prefix_render.py L109-114（truncated 返回）vs 3d L320（TC-13）vs batch_plan M5-01 验收 L15。
- 长度预算统一缺漏证：3d L204 vs shared_contract §二（L67-83）。
- 3d 附 L332 错证：3d L332（空白）/L358（校验器行）vs batch_plan L21。
- BREP-02 错证：5e L95 vs shared_contract L139 vs batch_plan L26 vs 素材提取 L60。
- IF30/32 错证：battle_render.py L29-50 vs shared_contract L130/132。
