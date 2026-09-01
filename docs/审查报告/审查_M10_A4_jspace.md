# 审查报告 · M10 钓鱼批A-4（出鱼结算 + 冠级）· j-space

- 审查日期：2026-08-31（静态代码审查，未运行任何命令/脚本——所有运行行为结论均为**静态推导**）
- 审查范围（批A-4 三文件）：
  - `qbot_rpg/core/fishing_settle.py`（settle_catch 出鱼结算：图鉴点亮/熟练经验/reward 奖励/纯收藏差分）
  - `qbot_rpg/core/fishing_crown.py`（crown_of 六档判定 / gen_size_weight 线性插值）
  - `qbot_rpg/core/fishing_codex.py`（fish_codex_update 七键入册 / render_fish_entry_line）
- 依据：`docs/细化/细化_2c1a_鱼种数据与冠级.md`（§2.1 大小重量 / §2.2 六档判定 / §4.2 图鉴七键 / §2.4 纯收藏约束）+ `docs/细化/细化_2c1c_鱼王与图鉴经济.md`（R-05 图鉴更新 / R-06 展示）
- 交叉核对：`fishing_settings.py`（fishing_cfg 九键）、`reward.py`（dispatch_reward 幂等/内联语法）、`proficiency.py`（gain_prof_exp 返回键）、`fishing_models.py`（FishDef 访问器）、`fishing_codex_commands.py`（渲染路径）、`tests/unit/test_fishing_settle.py` / `test_fishing_codex.py` / `test_fishing_crown.py`
- 审查维度：① 定稿落地（六档判定顺序/边界、七键更新、纯收藏差分=0）② 代码质量（bug/边界/幂等/确定性）③ 遗漏

---

## 零、总评

三文件与两份规格的**定稿语义一致度高**：六档判定顺序（逆金冠→大金冠→金冠→大银冠→银冠→普通）、边界语义（==5 非逆金冠、==85/==95 达级）、七键更新规则（best_crown 优先级链、逆金冠不入链、min ∞ 语义、防整条目覆盖）、纯收藏约束（结算数值侧不读 crown）均正确落地，`fish_codex_update` 与渲染路径（`render_fish_entry_line` + `render_fish_codex`）衔接一致。

问题集中在**幂等闸的边界条件、图鉴 `name` 键的持久化泄漏、异常吞噬面**三处。无 P0 阻断级问题。

结论：**P0=0 / P1=3 / P2=7**（见分级清单）。

---

## 一、P0（阻断/定稿违背）

无。

（候选不成立项：settle 幂等闸在 ledger 缺失时形同虚设——但按 S-7 声明与 reward 同一契约，指令壳必注入 tx_id+ledger，且预检与 dispatch_reward 的闸语义一致，不构成阻断，降为 P1-1。）

---

## 二、P1（缺陷，建议修复）

### P1-1 settle 幂等闸在 `tx_id` 存在但 `ledger` 缺失时形同虚设
- 位置：`qbot_rpg/core/fishing_settle.py` L400-405（幂等闸）
- 问题：闸条件 `tx_id is not None and isinstance(ledger, MutableSet)`——若 ctx 只带 `tx_id` 不带 `ledger`（装配漏注入/测试直调），同一结算可无限重复入账（金币/经验/图鉴计数三重复）。S-7 声明「无 tx_id/ledger（测试直调）→ 每次独立结算」，但**带 tx_id 缺 ledger 的中间态**未被声明也未处理。
- 影响：事务缺装配时静默双花；且无任何报错提示（返回 ok:True），排障困难。
- 建议：① 装配层保证 tx_id 与 ledger 成对注入（注入处断言/单测覆盖中间态）；② 或本路对「tx_id 有而 ledger 缺」按 `{ok:False, reason:"missing_ledger"}` 拒绝（宁可失败不可双花）；③ 至少补一个该中间态的拒绝/降级用例。

### P1-2 图鉴条目写 `name` 键：数据源不稳 + 与 codex 分册语义分叉
- 位置：`qbot_rpg/core/fishing_codex.py` L267（`_mark_fish_seen(ctx, species_id, str(entry.get("name") or species_id))`）→ 内部 L159 `entry["name"] = str(name or species_id)`
- 问题：此分支传入的 name 恒为 `species_id`（七键更新从未写 name），于是**首获条目的 `name` 键恒等于 species_id**（英文蛇形）。而渲染层 `fishing_codex_commands.py` L111-115 与 `render_fish_entry_line` 均以 `entry["name"]` 优先显示——若数据源在持久化层把「key=英文 id、name=中文名」分开（FishDef 中文名在 `name`，条目键在 `id`），则本路写入的 name 会把**英文 id 顶到展示位**，中文名丢失。
- 影响：展示层中文名可能被英文 id 覆盖；若未来 mark_seen 语义期望 name=中文名，此处写入即污染。
- 建议：① 首获时从 species 数据取中文名（settle 已持有 `_name_of(species)`，可随 catch 传入，或在 fish_codex_update 增加可选 name 参数）；② 或渲染层改为「name 键缺失/等于 id 时回落 species 数据中文名」；③ 至少补一个「entry.name ≠ id」的断言用例。

### P1-3 异常吞噬面过宽：`dispatch_reward` 全异常吞成空奖励，可静默丢奖
- 位置：`qbot_rpg/core/fishing_settle.py` L445-451（`try: from qbot_rpg.core.reward import dispatch_reward ... except Exception:`）
- 问题：把「import 失败」与「发放器自身异常」都吞为 `{ok:False, granted:[], skipped:[{type:"batch", reason:"dispatch_error"}]}`——奖励静默丢失且不记 ledger（后续 tx 重试可再补，但消息已回「成功」）。同时**结算已先入图鉴/经验，奖励失败无法回滚**，与 2c1c R-05「写入原子性：图鉴更新与出鱼结算奖励同写「SQLite 事务 + message_id 幂等」」不符（本路无事务包裹）。
- 影响：金币/物品静默丢失；事务原子性承诺未落地（属批间收口范畴，但本路至少应可观测）。
- 建议：① 降级为仅捕获 `ImportError`（import 失败属装配缺失，可明示 reason）；② dispatch 自身异常捕获后至少把 reason 透出（detail）；③ 收口时按 R-05 将图鉴+经验+奖励纳入同一事务/幂等闸。

---

## 三、P2（轻微/加固建议）

### P2-1 `fish_codex_update` 非幂等重放
- 位置：`qbot_rpg/core/fishing_codex.py` L230（`caught = ... + 1`）
- 问题：对同一 catch 重复调用 caught_count 每次 +1（best/min 单调不重复）。若结算壳重复调用（如消息重发重试），计数虚高。R-05 承诺「消息_id 幂等」，但本函数无幂等键。
- 建议：幂等由外层事务/结算幂等闸保证即可（本路已声明）；至少补注释说明「本函数非幂等，重放保护归调用方」。

### P2-2 `_grant_prof_exp` 与 reward 的 `_grant_prof` 双轨熟练经验，存在重复入账窗口
- 位置：`qbot_rpg/core/fishing_settle.py` L441（_grant_prof_exp）vs `reward.py` L283 `_grant_prof`
- 问题：settle 的 ④⑤ 步分别调 `_grant_prof_exp` 与 `dispatch_reward`；若内容包配置 `settle_reward` 里包含 `{"prof": {...}}` 条目，同一结算会**两路各加一次**熟练经验（reward 路 source=quest、settle 路 source=gather）。S-5 注释「经验不发 reward 的 exp」只防了默认形态，未拦配置形态。
- 影响：内容包可配键下经验双轨入账。
- 建议：① `_settle_entries` 对 `prof` 键条目显式过滤/拒绝；② 或在 settle 返回中携带 prof 入账来源标记供审计。

### P2-3 `settle_catch` 对 `_species_of` 命中**非 FishDef 且缺四区间键**的兜底数据不做区分
- 位置：`qbot_rpg/core/fishing_settle.py` L408-411（species 解析）
- 问题：`_interval_of` 缺键回落 0.0（fishing_crown.py L143），size=weight=0 仍照常入图鉴/经验/奖励。V1 校验器在加载期硬拦，运行期兜底「不炸」语义成立——但若运行期数据源被热替换为缺键行，会静默产出 0 尺寸结算。
- 建议：可接受（V1 硬拦 + 兜底语义）；至少补一条运行期日志/告警。

### P2-4 `_thresholds_of` 对乱序阈值（如 reverse=95 > silver=85）不修正、不告警
- 位置：`qbot_rpg/core/fishing_crown.py` L175-182
- 问题：C-6 明确「乱序不修正（V2 归路0C）」，但若运行期读到的阈值乱序（内容包热更新绕过校验），判定语义会畸形（如 r>s 时区间翻转）。C-6 与 C-3 注释已声明，属已知容错边界。
- 建议：保持现状；补注释提示「校验器硬拦，运行期不重复」。

### P2-5 `_settle_entries` 内联串形态：`"coins=30"` 依赖 `expand_inline_reward` 语法，未加注释说明失败路径
- 位置：`qbot_rpg/core/fishing_settle.py` L245-247
- 问题：`_iter_entries` 对非法内联串返回 skip（reward.py L336-339），最终静默跳过该奖励；但 settle 返回的 `reward_skipped` 会携带 reason，属可观测。注释未指明「非法内联串 → 整条 skip」。
- 影响：极低（已可观测）；建议补注释。

### P2-6 `render_fish_entry_line` 与 `codex_text.best_mask` 模板分叉
- 位置：`qbot_rpg/core/fishing_codex.py` L311-314 vs 2c1a C-03（`codex_text.best_mask` 示例无 `Lv{lv}` 前缀）
- 问题：实现模板为 `{name} Lv{lv} · 最大 … · 逆金冠×{n}`，而 2c1a §1.2 C-03 示例 best_mask 为 `{name} · 最大 … · 逆金冠×…`（无 Lv）；2c1c TC-07 期望 `鲤鱼 Lv3 · …`（含 Lv）。两文档间 Lv 位不一致，实现取了 TC-07 含 Lv 口径——方向正确，但未显式标注「以 2c1c TC-07 为准」。
- 影响：无功能影响；建议在模块注释中标注口径来源，防后续按 C-03 模板回改造成回归。

### P2-7 `CROWN_PRIORITY` 双文件重复定义
- 位置：`qbot_rpg/core/fishing_settle.py` L132 与 `qbot_rpg/core/fishing_codex.py` L99
- 问题：同一常量两处硬编码定义（值一致）。若未来链序调整（如新增档位），需两处同步；且 settle 的 `__all__` 导出与 codex 的 `__all__` 导出重复。
- 建议：settle 收口时改为 `from qbot_rpg.core.fishing_codex import CROWN_PRIORITY`（其 docstring 已声明收口替换，本项属待办确认）。

---

## 四、逐项核对记录（定稿落地）

### 4.1 六档判定（2c1a §2.2/§2.3 + 2c1c）
| 检查项 | 结论 |
|---|---|
| 判定顺序写死：逆金冠→大金冠→金冠→大银冠→银冠→普通（L254-293） | ✅ 与 §2.3 逐条一致 |
| 逆金冠严格 `<`（==5 非逆金冠，TC-07） | ✅ L278 `s < r and w < r` |
| 金冠/大金冠 `>=`（==95 达金冠，TC-08/09b） | ✅ L281/L284 |
| 银冠/大银冠 `>=`（==85 达银冠，TC-08） | ✅ L287/L290 |
| 混合极端 size≥g 且 weight<r → 金冠（TC-09） | ✅ L284 单边短路，逆金冠在 L278 已排除双<r 情形 |
| 阈值参数化（C-3 三态 + 默认 5/85/95） | ✅ L150-182；fishing_cfg 归一读段与测试 L312-329 覆盖 |
| 乱序阈值运行期不修正（C-6，V2 归校验器） | ✅ 声明一致 |

### 4.2 线性插值（2c1a §2.1）
| 检查项 | 结论 |
|---|---|
| size/weight = min + (max-min)×pct/100（L224-225） | ✅ 与 §2.1 公式一致 |
| 每次出鱼独立生成两百分位 ∈[0,100) 均匀（L222-223） | ✅ 独立两次 random() |
| 边界 pct=0 → min；不封 100（docstring） | ✅ 语义一致（无封顶） |
| 4 位小数保留（C-5） | ✅ round(..., 4) |
| rng 注入三态（参数→ctx→random 兜底，C-2） | ✅ L216-220，测试 _FixedRng 每次恰 2 次 random |

### 4.3 七键入册（2c1a §4.1/4.2 + 2c1c R-05）
| 检查项 | 结论 |
|---|---|
| 七键常量与 G-01~G-07 对齐 | ✅ settle L120-128 与 codex L87-95 同值同序 |
| best_crown 优先级链 big_gold>gold>big_silver>silver>normal（L232-236） | ✅ index 比较正确 |
| 逆金冠不入链、单独 reverse_crown_count（L249） | ✅ |
| best/min 极值（max/min，min ∞ 语义首获直落，L240-248） | ✅ |
| 防整条目覆盖（C-6：dict(existing) 复制后 update） | ✅ L227/L252-262，killed/lore_unlocked 保留，测试 L285-295 |
| 首获创建+点亮（L228/L266-267） | ✅ first_seen 语义正确 |
| __meta__ king_victory_count 默认 0 就位（C-4） | ✅ L270 |
| catch 数值归一（C-2：bool→0.0、非法 crown→normal） | ✅ L219-224 |

### 4.4 纯收藏差分=0（2c1a §2.4 + 2c1c 铁律）
| 检查项 | 结论 |
|---|---|
| 结算数值侧（奖励/经验/消息）不读 crown 字段 | ✅ 静态推导：settle 的 `_settle_entries`/`_prof_exp_amount`/`dispatch_reward` 入参均不含 crown；crown 仅入 catch→图鉴与返回展示 |
| 经验 amount 与 crown 无关（S-6/S-8） | ✅ 常数为 10，与 crown 无关 |
| 奖励条目与 crown 无关（S-5/S-8） | ✅ 默认/可配条目均不含 crown |
| TC-25 差分测试存在 | ✅ test_fishing_settle.py L385-416（3 组阈值→3 冠级，金币/经验/奖励全同） |
| 消息文案含 crown 仅展示（S-9） | ✅ MSG_SETTLED 含 {crown}，属展示非数值 |

### 4.5 其它接线
| 检查项 | 结论 |
|---|---|
| 熟练经验 source=gather / job_id=fishing（2c1c R-13） | ✅ L111-114/L322 |
| gain_prof_exp 返回键名 `level` 读取正确 | ✅ settle L332 读 `r.get("level")`，proficiency.py L300 返回 `"level"` |
| 引擎缺失静默跳过不阻断（S-6） | ✅ L306-320，测试 L328-335 |
| 奖励默认 coins=20 可配（S-5） | ✅ L236-248，测试 L361-379 |
| 结算三要素 size/weight/crown（TC-24） | ✅ L460-464，测试 L167-176 |
| 确定性：注入 rng 单源、零 IO 零定时器 | ✅ 静态推导一致（random 兜底仅测试直调路径） |
| 快照双形态（含 roll / 无 roll）兼容（S-1） | ✅ L393 只读 target_species_id |

---

## 五、遗漏审计（维度③）

1. **文件头注释与实现状态漂移**：`fishing_settle.py` L13-14/L52-56 声明「本路先做本地薄实现、路4A 落盘后收口替换」，但 L93 已直接 import 正式版 `fish_codex_update`——注释（S-3/S-4 的「本地薄实现」表述）与代码现状不一致，属文档滞后（建议收口时同步更新注释，防后续误读）。
2. **`_mark_fish_seen` 的 adventure_log / event_bus import 为「用前 import」**（fishing_codex.py L164/L170）：函数体内 import 会触发「import 不置顶」风格问题，且异常吞噬（L167-168/L173-174）使日志/事件静默丢失——属可接受容错（对齐 codex.mark_seen），但建议在收口时确认两个模块存在性与契约。
3. **`render_fish_entry_line` 的 `lv` 占位 0**（L292）：与批5 熟练度接线是已知待办（任务书明确），不属本批缺陷。
4. **`settle_catch` 未处理 `fish_state["last"]` 的消费**（S-7 仅 tx 幂等，快照本身不删除）：指令壳消费后是否清 last 由壳负责，属批间契约，建议在批6 指令壳接线时确认「结算后清 last」。

---

## 六、修复优先级建议（落地顺序）

1. P1-1：装配层 tx_id/ledger 成对注入 + 中间态单测（结算幂等闭环）。
2. P1-2：`fish_codex_update` 首获 name 取中文名（或渲染层回落 species 中文名）+ 断言。
3. P1-3：`dispatch_reward` 异常分类（ImportError 与业务异常分开）+ reason 透出；收口时按 R-05 同事务。
4. P2-2：`_settle_entries` 过滤 `prof` 键条目，防双轨经验。
5. P2-7：settle 收口改 import codex.CROWN_PRIORITY，删本地重复定义。
6. 其余 P2 按注释补强/单测补充处理。
