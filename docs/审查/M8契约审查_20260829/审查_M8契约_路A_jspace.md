# 审查报告 · M8 共享契约 路A（核心机制子文档）

> 审查人：QBot-TurnTellerRPG 代码审查 Agent（j-space **full 档**门控：单交付物·一次阅读可校验）
> 日期：2026-08-29 · 方式：静态文件审查（read/grep 真实定义核对，无运行、无子代理）
> 结论：**可合入（附 1 处 P1 文档修正 + 6 处 P2 建议）** —— 无 P0、无行为语义错误、无编造行号

---

## 一、审查对象

- 目标：`docs/m8_contract_核心机制.md`（455 行，IF-01~43）
- 范围：三层漏斗 / 职业等级 / 能量条 / 品质 / 特性 / 投料触媒 / 调合会话状态机

## 二、对照基准（仓库内路径，全部实读）

| 基准 | 文件 | 作用 |
|---|---|---|
| 细化修订版 | `docs/细化/细化_2c4a_炼金三层漏斗.md`（211 行）/ `细化_2c4e_品质与特性.md`（244 行）/ `细化_2c4f_投料触媒与能量条.md`（183 行） | 实现的直接依据（LAY/CASC/JOB/QLT/TSC/INH/STO/FEED/AUTO/BATCH/CAT/ENG + TC） |
| 定稿副本 | `docs/审查参考/炼金系统设计定稿.md`（516 行） | 定稿行号锚点校验（禁止编造维度） |
| 接口摸底 | `docs/m8_接口摸底.md`（307 行） | 51 接口落点基准 |
| 仲裁 | `docs/仲裁/细化_0_仲裁决议汇总.md`（R-07 L99-104 / R-08 L108-113） | 触媒=专家 / 能量默认关 |
| 批次 | `docs/m8_batch_plan.md`（决策 1-6 / 拍板 1-5 / 批0~13） | 实现批次标注合理性 |
| 兄弟子文档 | `docs/m8_contract_数据与校验.md` / `m8_contract_战斗资源.md` / `m8_contract_指令契约.md`（后两者未穷读，交叉核对字段落点） | 跨文档一致性 |
| 真实代码 | `qbot_rpg/`（storage/repository.py、world/session.py、world/battle_boundary.py、core/inventory.py、core/levelup.py、engine/condition_engine.py、core/formula_engine.py、core/battle.py、assembly/bootstrap.py、commands/parsers.py、commands/router.py、content/loader.py、content/field_meta.py、content/validator.py、content/registry.py、data/item.py、data/player.py、storage/schema.py） | IF 签名核对 |

## 三、结果表

| # | 审查维度 | 结论 | 级别 |
|---|---|---|---|
| ① | IF 接口签名 vs 代码真实签名（43 条） | 🟡 40 精确 / 2 处 P2 行号±1 / **1 处 P1 锚点错误** | P1×1 + P2×2 |
| ② | 字段/schema vs 细化修订版（quality_tiers 键集 / energy_enabled=false / catalyst_unlock_tier=expert / 2147483647 / 平铺宝石 / proficiency dict 形态） | 🟢 全部一致 | — |
| ③ | 跨文档一致性（energy/quality/proficiency 字段落点） | 🟡 energy 状态存储位置子文档间未统一 | P2×1 |
| ④ | 验收 TC 矩阵（2c4a 26 + 2c4e 26 + 2c4f 38 = 90） | 🟢 全映射无缺漏；179 总量算术核验通过 | — |
| ⑤ | 用户 5 项拍板 + R-07/R-08 | 🟢 全量落实（②⑤ 本域铁律，①③④ 归战斗资源并留档位索引） | — |
| ⑥ | 缺漏检查（状态机迁移表 / 能量懒计算 / 品质降级 / 特性四规则族 / 触媒） | 🟡 迁移表在但相对定稿 §4.6 不完整；僵尸回收缺材料返还 | P2×2 |
| ⑦ | 其它（命名禁制保真度） | 🟡 TSC-04 漏「禁空格」 | P2×1 |

**汇总：🟢 4 维 / 🟡 3 维 / 🔴 0 维；P0 0 / P1 1 / P2 6**

---

## 四、问题清单（文件:行号 + 实际 + 应有 + 证据）

### P1（必改，1 处）

**P1-1 · IF-41 check_pack 行号锚点错误（契约文档:行号 = m8_contract_核心机制.md:372）**
- 实际：IF-41 写作 `check_pack(modules: Mapping, meta: FieldMetaTable) -> ValidationReport`（content/validator.py **L383**）。
- 应有：`check_pack` 模块级公开入口定义于 `content/validator.py` **L1793**（`def check_pack(modules, meta=None) -> ValidationReport`，L1793-1795）；L383 实为 `_Checker.run()`（无参内部入口）。兄弟子文档 `m8_contract_数据与校验.md` IF07 已正确写作「check_pack(...)（validator.py **_Checker.run** L383）」，本子文档漏掉 `_Checker.run` 限定词，读者按 L383 找不到 check_pack（差 1410 行）。
- 证据：validator.py L383 `def run(self) -> ValidationReport:`；validator.py L1793 `def check_pack(`。
- 影响：违反「禁止编造行号 / 行号真实存在」铁律与本表「全部签名均 read 真实定义」承诺；实现组 grep L383 会误当 check_pack 入口（签名还不同）。
- 修复：L372 改为「check_pack（公开入口 **L1793**；内部 `_Checker.run` L383）」；或照数据与校验 IF07 口径加 `_Checker.run` 限定。

### P2（应改，6 处）

**P2-1 · IF-05 tx 行号 ±1（契约:行号 301）**
- 实际：`@contextlib.asynccontextmanager` 装饰器在 repository.py **L412**，`async def tx` 在 **L413**。
- 应有：接口表「真实签名（行号）」应锚 def 行 L413（或明确"装饰器 L412"）。
- 证据：repository.py L412-413。
- 影响：低（装饰器行真实存在且紧邻），但接口表行号精度承诺应一致。

**P2-2 · IF-09 SessionRow 行号 ±1（契约:行号 305）**
- 实际：`@dataclass(frozen=True)` 在 repository.py **L289**，`class SessionRow:` 在 **L290**。
- 应有：锚 L290。
- 证据：repository.py L289-290。
- 影响：低（同 P2-1）。

**P2-3 · 能量状态存储位置跨子文档不一致（契约:行号 130；数据与校验:行号 137/337）**
- 实际：核心机制 ENG-09 定 `能量当前值 + energy_last_regen_ts 入玩家存档（persistent_state 桶，data/player.py L93）`；数据与校验 §3.2 JSON 示例把 `energy_current: 6` 放 **proficiency dict 内**，§7.1 写 `energy.<job_id>（或折 proficiency.<job_id>.energy_current，细化_2c5a §5.3 落 proficiency dict）`。
- 应有：同一契约 4 子文档应统一能量当前值 + energy_last_regen_ts 的落点（建议同桶共存，保证懒计算锚点同读）。两处并存会使实现按两个桶拆分、懒计算读到旧值。
- 证据：m8_contract_核心机制.md L130（ENG-09）；m8_contract_数据与校验.md L137（§3.2 示例）、L337（§7.1）；data/player.py L93（persistent_state 自由 JSON 桶，实核存在）。
- 影响：合并主契约时需裁决统一；属于跨文档口径未对齐。

**P2-4 · 调合会话状态机迁移表相对定稿 §4.6 不完整（契约:行号 265-276）**
- 实际：§7.1 表只有「（无会话）/投料 → 非法」「（无会话）/炼金 已有其它会话 → 拒绝」两行覆盖非法转移；缺失定稿 §4.6 的另两条明确转移+模板。
- 应有：补两行——① 会话中 发 /炼金 新配方 → 拒绝「**调合进行中！/放弃 退出 或 /调合续 继续**」（定稿 L176）；② /调合续 但已有活跃会话 → 「**已有一个调合会话进行中**」（定稿 L177）。
- 证据：定稿副本 L175-177（§4.6 非法转移错误模板三态）；核心机制 §7.1 表（L265-276）未含后两条。
- 影响：实现组照迁移表会漏掉两条定稿指定模板/状态迁移。

**P2-5 · 僵尸回收遗漏「材料返还」语义（契约:行号 276/283）**
- 实际：§7.1/§7.2 只写 `recycle_scan(max_days=30.0) + settle 回调结算（lifecycle.recycle_days）`，未提材料返还。
- 应有：定稿 §4.6 L183「无操作超时（lifecycle.recycle_days，可配 0=不限）→ **僵尸会话回收（材料返还）**」——终态回调应含已投材料返还口径（否则 30 天回收静默吞材料，与 §7.2「防静默丢材料」自述矛盾）。
- 证据：定稿副本 L183；核心机制 L276（僵尸回收行）、L283。
- 影响：回收路径材料处置未契约化。

**P2-6 · traits.json id 命名禁制漏「禁空格」（契约:行号 175）**
- 实际：核心机制 5.1 TSC-04 写作「命名禁 `* , = +` 保留字符（对齐分隔符规范）」。
- 应有：细化_2c4e TSC-04 与数据与校验 §2.1/REC-16/TRT-01 均为「命名**禁空格**/禁保留字符 `* , = +`」。
- 证据：2c4e L83；数据与校验 L82/L261/L267；核心机制 L175。
- 影响：同一契约 4 子文档对 id 命名禁制口径不一致（空格漏项）。

---

## 五、维度确认（无问题项逐一确认）

- **① IF 签名（其余 40 条）**：逐条 read/grep 实核一致——IF-01 load_player L442、IF-02 save_player L473、IF-03 load_session L563、IF-04 recycle_scan L720、IF-06 upsert_session L887、IF-07 delete_session L904、IF-08 write_idem_key L922 / idem_exists L932、IF-10 player_to_row L143 / row_to_player L234、IF-11~15 SessionManager L27/30/33/36/39 全占位 + SessionConflictError L20、IF-17 settle_exit_idempotent L821、IF-18 session_mutex_decision L702、IF-19 bootstrap L61、IF-20 add_item L183、IF-21 remove_item L254、IF-22 count L308、IF-23 ItemInstance L20-37、IF-24 _grant_sp L117、IF-25 gain_exp L133、IF-26 condition_engine L161/L131、IF-27 formula_engine L218、IF-28 L246、IF-29 to_snapshot L1740、IF-30 do_action L1031、IF-31 _resolve_item_action L1162、IF-32 parse_command L586、IF-33 FIXED_SUBWORDS L99、IF-34 DEFAULT_WHITELIST L112/121/125、IF-35 DEFAULT_QUANTITY_COMMANDS L149 / DEFAULT_MAX_QTY L155、IF-38 loader L150/158、IF-39 field_meta L441/418、IF-40 SETTINGS_FIELDS L206、IF-42 _check_settings_1g4 L1329、IF-43 registry resolve L82 / build L163；另实核 schema.py L24 `SESSION_TYPES=("battle","alchemy","challenge_alchemy")`、data/player.py L93 persistent_state 桶。**标注批次与 m8_batch_plan 批号对应合理**（IF-11~15 批3、IF-29 批9、IF-38~42 批0、IF-32~37 批11 均与派工单吻合）。
- **② 字段/schema**：`quality_tiers {common:[0,39],uncommon:[40,59],rare:[60,79],legendary:[80,100]}` 与定稿 L411/2c4e QLT-02 一致；`quality_coef 0.8/1.0/1.2/1.5`（L145）与定稿 L412 一致；档位数 3/5/7、0=不限制、L150 旧名「优秀/稀有」废弃（L141-142）与拍板②一致；`energy_enabled:false`（L122/442）与 R-08/2c4f ENG-01 一致；`catalyst_unlock_tier:"expert"`（L250/445）与 R-07/2c4f CAT-01 一致；数量上限 2147483647（L243/450/435）与拍板⑤/2c4f BATCH-04 一致；平铺宝石 1/3/8/20（L431）与拍板①/2c4a TC-20 一致（正确归属战斗资源并留本域档位索引）；proficiency dict 形态（L72/420）与决策4/levelup.py L117 实核一致。
- **④ TC 矩阵**：9.1 2c4a 26 例四段（各层解锁 TC-01~06 / 防跳层 TC-07~14 / 产出边界 TC-15~23 / 三渠道 TC-24~26）与 2c4a §五 逐一对应；9.2 2c4e 26 例五段全对应；9.3 2c4f 38 例四段（投料 TC-01~14 / 触媒 TC-15~20 / 能量条 TC-21~30 / 即时调合 TC-31~38）全对应；179 总量（26+25+30+34+26+38）算术成立。
- **⑤ 拍板 + 仲裁**：5 项拍板全量落点；R-07 触媒=专家含定稿 L84 专项表 vs L154 行内冲突说明与采纳理由；R-08 能量默认关含关闭时 /炼金 /深度炼金 /即时调合 不扣能量、无上限显示、无「能量不足」模板（L122），与 2c4f ENG-01 逐字一致。
- **⑥ 缺漏**：能量懒计算 ENG-05（L126）与三周期懒计算口径对齐；品质降级 QLT-10（L159）差一档降一档最低普通不吞材料；特性继承四规则族 INH-01~16（L204-207）来源/传递/冲突/等级化全族在册；触媒 CAT-01~06（L250-255）全量。仅 P2-4/P2-5 两处补强。

## 六、定稿行号锚点抽查（禁止编造维度）

契约引用的定稿行号经副本（516 行）抽查全部真实存在：L411（quality_tiers 键集）、L412（quality_coef）、L416（energy_max）、L84（专家触媒）/ L154（精通触媒冲突）、L95（休整/安全区可加速）、L115（合成 ≤99）、L120（合成图鉴小加成）、L200（进化=炼金产出 N 次）、L410（mode）、L397（会话快照）/ L398（battle_alchemy_used）/ L401（珠堆叠键）、L211（#13 秘钥强化已砍→19 项生效）。**未发现编造行号。**

## 七、结论

- **判定：可合入**（本子文档核心语义、数值、TC、拍板、签名均与细化/定稿/真实代码一致）
- P0 清单：无
- P1 清单：1 处文档修正（IF-41 check_pack 锚点 L383→L1793）
- P2 清单：6 处（2 处接口表行号±1、energy 落点跨文档未统一、状态机迁移表缺定稿 L176/L177 两迁移、僵尸回收缺材料返还、TSC-04 漏禁空格）
- 建议：P1 合并主契约前修正；P2 由主契约合并时统一（尤其 P2-3 energy 落点、P2-4 迁移表补齐），其余可后续批次随改随修。
