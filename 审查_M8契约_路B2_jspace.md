# 审查报告 · M8 共享契约 路B2（指令契约 §三~§八）· jspace

> 日期：2026-08-29 · 审查者：QBot-TurnTellerRPG 代码审查 Agent（路B2）
> 审查方式：静态文件审查（read/grep/glob，本环境无 bash 沙箱，运行行为结论均为**静态推导**）
> 门控档位：**full**（J-space 门控；目标 1 份报告、契约 1 份、代码 8 份、基准 5 份，可一次读全→逐条比对→落盘）

---

## 一、审查对象

- **目标**：`docs/m8_contract_指令契约.md`（477 行）——仅审 §三 解析器接线（L266-308）、§四 会话互斥 MUT（L312-327）、§五 原子幂等 ATO（L331-346）、§六 IF 接口清单（L350-398）、§七 TC 矩阵（L402-441）、§八 铁律与拍板（L445-473）；§〇/§一/§二 作为前述章节的引用锚点一并抽查。

## 二、对照基准（仓库内路径，已实际读取）

| 基准 | 文件 | 读取方式 |
|---|---|---|
| 细化修订版 | `docs/细化/细化_2c4d_炼金指令表.md`（432 行，全读） | §三 MUT-01~08 / §四 ATO-01~08 / §五 TC-01~34 |
| 定稿副本 | `docs/审查参考/炼金系统设计定稿.md`（516 行，读 L110-515） | §4.6 L171-185、§七 D1 L290-300、L115/L150/L178/L180/L181/L183/L224-230/L248/L316-344/L397-425/L509-511 |
| 分隔符规范 | `docs/审查参考/指令分隔符统一规范.md`（246 行，全读） | §一 L11-23 / 铁律 L27-51 / 命名 L55-61 / 管线 L65-74 / 内容包 L81-84 / L15 / L42 / L49 / L60 / L69 / L71 / L73 |
| 接口摸底 | `docs/m8_接口摸底.md` | 51 接口落点（L296 总计行）；parse_command L116-117 / settle_exit_idempotent L99-100 / shop_commands L136 |
| 批次派工 | `docs/m8_batch_plan.md`（113 行，全读） | 批0~批13、决策 1、用户 5 项拍板、批11 路11A 注册清单、179 TC |
| 真实代码 | `qbot_rpg/commands/parsers.py`（854 行，全读）、`router.py`（887 行，全读）、`shop_commands.py` L430-483、`storage/repository.py`（抽样 L280-944）、`storage/schema.py`（180 行，全读）、`world/session.py`（40 行，全读）、`world/battle_boundary.py` L810-884、`assembly/bootstrap.py`（81 行，全读）、`data/player.py` L57-69、`core/quest.py` L35-64 | 接口签名/行号逐条对拍 |
| 兄弟子文档 | `docs/m8_contract_核心机制.md`（grep CASC-08/ENG-01/CAT-01/IF-32~37/拍板⑤） | 跨文档一致性 |

## 三、结果总表

| 维度 | 判定 | 问题数 |
|---|---|---|
| ① 解析器接线（§三） | 🟢 通过（附 2 条 P2 澄清） | P2×2 |
| ② 会话互斥 MUT（§四） | 🟢 通过 | 0 |
| ③ 原子幂等 ATO（§五） | 🟡 注意（1 条 P1 溯源行号） | P1×1 |
| ④ IF 接口清单（§六） | 🟢 通过 | 0 |
| ⑤ TC 矩阵（§七） | 🟢 通过 | 0 |
| ⑥ 跨文档一致性 | 🟢 通过 | 0 |
| ⑦ 用户 5 项拍板 + R-07/R-08 | 🟢 通过 | 0 |

**汇总：🔴 拦截 P0 = 0 ｜ 🟡 注意 P1 = 1 ｜ 🟡 建议 P2 = 3**

---

## 四、问题清单（文件:行号 + 实际 + 应有 + 证据）

### 🔴 P0-0 · 无
未发现：契约编造定稿/代码行号（铁律 3）、自创幂等表（铁律 2）、实现↔细化行为矛盾、分层越界、数值擅自改动。

### 🟡 P1-1 · ATO-08 溯源行号 L509 → 应为 L511（契约应发挥修正层职责）
- **位置**：`docs/m8_contract_指令契约.md:344`（ATO-08 行）+ 继承来源 `docs/细化/细化_2c4d_炼金指令表.md:7,21,358,369`
- **实际**：细化四处引用「【炼金】L509（热重载旧快照结算）」；契约 ATO-08 行**未给行号引用**（规避了错误，但未指正）
- **应有**：热重载会话失效在定稿真实行号为 **L511**（`docs/审查参考/炼金系统设计定稿.md:511` = "热重载会话失效 | 调合会话旧快照结算（材料 ID+名称冗余）"）；L509 实为「消息超长/刷屏」风险行
- **证据**：定稿 L509/L511 已直接读取；契约 §〇 L14 宣称「契约内保留引用列」，且契约定位是修缺陷的修正层（幻觉审查教训：AI 行号编造）
- **修复建议**：契约 §五 ATO-08 行为「热重载会话失效」补引用列并写正确行号 `L511/L397`（现 397 正确）；同步在细化_2c4d L7/L21/L358/L369 将 L509 改 L511。因契约自身未复引错误行号，不构成编造，定 P1（应改）不升级 P0。

### 🟡 P2-1 · 固定子词在「位置 1」亦吞并配方/材料名，边界未文档化
- **位置**：`docs/m8_contract_指令契约.md:279-280`（§3.2）+ `qbot_rpg/commands/parsers.py:482-484`
- **实际**：契约 §3.2 仅声明「M8 所需子词全部已有，零新增」；§二 P-02 写「位置参数 2 限固定子词 自动」。但 parsers 判定 `fixed_subword is None and idx <= 1 and tok in FIXED_SUBWORDS`——**位置 1（idx=0）同样吞子词**：`/炼金 自动` → fixed_subword="自动"、args=[] → 走缺参（ERR_MISSING），而非「配方『自动』不存在」。名为「自动/确认/放弃/续/追加/预览/查看」的配方/材料名无法经对应槽位直达（命名铁律只禁保留字符、不禁子词同名）
- **应有**：契约明确「子词在位置 1（首参）亦优先于物品匹配；配方/材料名与子词同名将不可直达」；或按需在装配层对 /炼金 加 min_args=1 缺参提示兜底
- **证据**：parsers.py L483-485 子词判定；L827-830 command_specs 缺参判定；契约 §2-2 P-02「子词表…优先于物品匹配」未限定位置
- **修复建议**：契约 §3.2 或 §2-2 P-02 补一句边界声明（P2 建议，不影响批次排期）

### 🟡 P2-2 · §3.3「需新增 1 词：复制」必要性措辞略过度
- **位置**：`docs/m8_contract_指令契约.md:284-285`
- **实际**：契约写「需新增 1 词：复制（/复制 道具*数量 走 `*` 批量，ATO-07）」，暗示不入 DEFAULT_QUANTITY_COMMANDS 则 `*` 不生效
- **应有**：`*` 数量解析是 parsers 通用能力（仅 no_quantity_commands 禁 `*`），/复制 不在 quantity_commands 时 `/复制 魔力药水*5` 仍会解析 qty=5；加入该集合只额外启用「旧空格数量兼容回退」（`/复制 魔力药水 5`）
- **证据**：parsers.py L532-548（`*` 解析对所有指令生效，除 L534 no_quantity 分支）；L555-565（quantity_commands 仅控制空格旧式回退）
- **修复建议**：契约 §3.3 改注「加入 DEFAULT_QUANTITY_COMMANDS 为兼容『空格 数量』旧式；`*` 批量语法本身不依赖该集合」（P2 澄清，非缺陷）

### 🟡 P2-3 · quest.py 路径简写可补全
- **位置**：`docs/m8_contract_指令契约.md:235`（§2-19 数据落点）
- **实际**：写「quest.py L49 既有语义」——仓库内实为 `qbot_rpg/core/quest.py:49`（L49 = "filter（交付品质过滤，炼金委托板用）"，内容准确）
- **应有**：补全路径 `core/quest.py L49`，防实现组在 world/ 下找文件
- **证据**：glob 定位 core/quest.py；read L48-49 内容属实

---

## 五、各维度逐条确认（无问题维度）

### ① 解析器接线（§三）🟢
- `parse_command` 签名 L586-603 **逐字一致**（含 `max_qty=DEFAULT_MAX_QTY=99`、`gm_commands`、`command_specs`）→ 契约 L268 引用准确。
- ParsedCommand 字段 `args/positional/qty/targets/kv/seq/level/path/fixed_subword/error/hints`（L188-240 slots + L244/249/254 属性）+ `arg(i, default)` L259 → 契约 L268 引用准确。
- **白名单现状**：契约列 14 词（合成/炼金/调合/镶嵌/拆珠/投料/代工/继承/图鉴/任务/注册/购买/出售/签到）全部在 DEFAULT_WHITELIST L107-129 真实存在（L112/L116-117/L121/L125）。
- **需补 23 词清单**：`继承超、调合续、确认、放弃、深度炼金、进化、镶核心、加成、成品合成、分解、登记、复制、配方合成、特性合成、协力、挑战、即时调合、技能面板、种植、收获、雇工、收取、教学` —— 逐一比对 DEFAULT_WHITELIST 全缺，清单**准确**；且「确认/放弃/续」确在 FIXED_SUBWORDS 而非白名单（契约 L274 的「独立指令名仍须进白名单」判定正确——parsers S5 候选=白名单∪别名，子词不参与指令名匹配，L771）。
- **FIXED_SUBWORDS 零新增**：L99 集合 `{追加,预览,自动,查看,确认,放弃,续}` 与契约 L279 逐字一致；M8 所需子词全覆盖，**属实**。
- **DEFAULT_QUANTITY_COMMANDS**：L149 集合逐字一致；`复制` 确缺失（P2-2 见上）；`雇工` 的 `*` 在 kv value 内（parsers `_parse_kv_item` L436-445），确无需加入；no_quantity_commands={强化} L152 一致。
- **max_qty 注入**：DEFAULT_MAX_QTY L155=99 属实；契约 §3.4 把「从 settings.alchemy.max_qty 注入 2147483647」正确落在**批11 装配层**责任（非解析器改），超限提示文案「最多一次使用 N 个」与 parsers L545 一致、与分隔符 L73 对齐。
- **A+B 两空格位置参数**：parsers 位置参数 ≤2（L513/516）、名称禁空格禁保留字符（L58/命名铁律）、`_ALLOWED_TOKEN_RE` L160 含 `%` 与 `+`（契约 §3.5.3 属实）、特性名数值 `+` 黄色提示不拦截（L550-553 reserved_char_hint）→ 契约实现要点 5 条全部成立；同物两份 arg0==arg1 不拦截（parsers 无去重）属实。
- **其余**：command_specs `{"min_args": 0}` 机制存在（L827-830）；`/图鉴` 在 DEFAULT_PREFIX_REQUIRED L134（装配层不得移除）属实；`@` 参数由消息层剥离（parsers S0 L707-716 require_at 剥离 @）。

### ② 会话互斥 MUT（§四）🟢 与细化_2c4d §三 MUT-01~08 逐条一致
- MUT-01 单会话槽总纲 / MUT-02 全局互斥（`sessions.player_qid` 主键 = schema.py L60，天然互斥；upsert_session ON CONFLICT DO UPDATE L887）/ MUT-03 即时调合豁免（不调 SessionManager.acquire，对齐定稿 L293-294）/ MUT-04 战斗拦截模板（对齐 L295）/ MUT-05 挂起恢复（/调合续 已有活跃→"已有一个调合会话进行中" L177）/ MUT-06 非法转移模板（L175-176）/ MUT-07 深度/炼金会话类型分离（SESSION_TYPES schema.py L24 + CHECK L62 已含 alchemy/challenge_alchemy，**无需改表**属实）/ MUT-08 僵尸回收（recycle_scan L720 签名 `settle,max_days=30.0` 属实，默认 30 天、0=不限）。
- 代码锚点：SessionConflictError L20、SessionManager 5 方法 L24-40 占位（NotImplementedError）、bootstrap.py L61 注入点，全部属实。
- 终态结算模式：settle_exit_idempotent L821-884（签名/幂等键 `settle:{kind}` L873/只读查重 idem_claim L876/单事务 delete_session+write_idem_key L882-883/自行开事务不得嵌套 tx 声明 L835）——契约 L327 描述与代码逐句吻合。

### ③ 原子幂等 ATO（§五）🟡（P1-1 见上，其余通过）
- **ATO 复用框架幂等三件套、勿自创幂等表**：idempotency_keys 复合主键 (message_id, group_id, player_qid) schema.py L71-81；Repository.idem_claim L658（入口只读查重）；RepoTransaction.write_idem_key L922 / idem_exists L932（事务内权威判定）；tx L412（`async with repo.tx() as tx`）——契约 L333 全部引用**真实存在**，且明确复用、无自创表。
- ATO-01~08 行为与细化 §四 ATO-01~08 逐条一致（覆盖指令集合相同；ATO-05 两处均标【合理推论】；ATO-07 上限 2147483647/超限仅提示；ATO-08 见 P1-1）。
- ATO-03 附注「command 不参与去重（先到者胜）」与 battle_boundary L844-847 说明、schema PK（不含 command）一致；IdemKey 字段 (message_id, group_id, player_qid, command) = repository L303-311 + battle_boundary L869-874 属实。
- sessions.version 列默认 1：schema.py L63 + SessionRow L289/297 属实。

### ④ IF 接口清单（§六）🟢
- 壳函数 28 个（cmd_synth…cmd_quest_board）与批11 路11A 注册清单（batch_plan L76：23 核心 + 4 资源 + 2 面板挂接）**一一对应、无缺漏**；/协力（cmd_cooperate ⚠️补排期）与 /任务（cmd_quest_board 挂接既有入口）两处标注与 batch_plan 事实一致。
- 壳模式签名 `cmd_xxx(parsed, ctx) -> str`（战斗壳 dict）与 shop_commands.py L447-483 逐字对齐：`_ctx(parsed)` 闭包 make_context=None 抛 RuntimeError（L454-460）/ `_cmd(parsed,*a,**k)` 支持 k.get("ctx")（L462-466）/ router.register(CommandSpec(...))（L480-482）。
- `register_alchemy_commands(router, *, make_context=None)` 装配入口签名 = register_shop_commands(router, *, make_context=None) 同构；伪代码块与 shop_commands 实现一致。
- Router.register 重名 ValueError router.py L206-207 属实；router.get(name) L215 查重可行；「注册≠登记」无撞名、查重建议有效。

### ⑤ TC 矩阵（§七）🟢
- TC-01~34 **34 行全部存在**，与细化 §五 TC-01~34 编号/预期一一对应（TC-32 覆盖已砍 /秘钥、TC-33 会话互斥、TC-34 原子幂等）。
- 批次映射与 batch_plan 一致：TC-04 批4路4A+批5路5B（触媒机制=批5 路5B ✓）、TC-05 批4+批3、TC-08 批9路9B、TC-13 批3路3B、TC-22 ⚠️补排期（与附注①一致）等。
- 「179 TC = 2c4a 26+2c4b 25+2c4c 30+2c4d 34+2c4e 26+2c4f 38」与 batch_plan L80 逐字一致；测试文件命名与批次路号对应合理。

### ⑥ 跨文档一致性 🟢
- 核心机制子文档：CASC-08 会话类型分离 / ENG-01·ENG-10 能量默认关 / CAT-01 触媒专家解锁 / IF-32~37 解析器与壳签名 / 拍板⑤ 数量上限 —— 与契约 §四/§二/§八 完全一致，且与真实代码对拍通过。
- 接口摸底：51 接口落点（L296）、parse_command L586-603、settle_exit_idempotent L821、register_shop_commands L447-483 —— 与契约引用一致。
- 数据落点：data/player.py L69 `EquipmentSlot.gems: Tuple`（tuple 冻结）属实；quest.py L49 交付品质过滤属实（路径见 P2-3）；schema L24 SESSION_TYPES 属实。

### ⑦ 用户 5 项拍板 + R-07/R-08 🟢
- §八 8.1 拍板①~⑤全部落点（F-10/M-10/TC-18、M-05/TC-11、§2-17 备注、GU-36/TC-19、§3.4/ATO-07）与 batch_plan 拍板节逐字一致；拍板③（珠升阶无职业硬门槛）正确指引到细化_2c4c（非本 23 行）不越界。
- §八 8.2 R-07（catalyst_unlock_tier=expert，GU-08/TC-04）、R-08（energy_enabled=false，GU-06/21/52/TC-05）与 batch_plan 决策 6、核心机制 ENG-01 一致。
- 8.3 本域铁律 8 条中「勿自创幂等表」「A+B 落两空格」「/秘钥 不注册」「批次冲突以 batch_plan 为准」均已在本报告相应维度验证成立。

---

## 六、结论

**判定：可合入（无 P0）**。契约 `m8_contract_指令契约.md` §三~§八 与其声明的「真实代码」基准高度自洽：parsers/router/shop_commands/session/schema/repository/battle_boundary/bootstrap 全部行号引用经逐行对拍**无一编造**；MUT-01~08/ATO-01~08/TC-01~34 与细化_2c4d 逐条一致；幂等三件套明确复用框架设施（未自创幂等表）；批次归属与 batch_plan 完全对齐；5 项拍板与 R-07/R-08 落实无遗漏。

**待跟进（不阻断合入）**：
- P1-1：契约 ATO-08 行补正确溯源行号 L511（并同步修正细化_2c4d 四处 L509→L511），防实现组误溯源。
- P2-1~P2-3：三处边界/措辞/路径澄清（见 §四），可在批11 装配前随契约小修一并完成。

**门控档位：full**（外显汇报格式见末段）。
