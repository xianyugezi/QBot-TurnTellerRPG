# 审查报告 · M11 批4 A2（图鉴聚合系统）

> 方式：静态代码审查（本环境无 bash 沙箱，未运行任何命令/脚本/测试；全部结论为静态推导）
> 门控档位：full（技能唤醒 → 门控 full 档 → 接缝审计 → ship）
> 审查文件（6）：qbot_rpg/core/codex.py（572 行）· qbot_rpg/core/codex_milestones.py（375 行）· qbot_rpg/commands/codex_commands.py（192 行）· qbot_rpg/core/reward.py（501 行，item 首获段）· qbot_rpg/commands/battle_commands.py（956 行，monster 首杀段）· qbot_rpg/core/templates/codex_tpl.py（48 行）
> 参考：docs/细化/细化_4d_图鉴聚合契约.md（25 TC）+ docs/m11_图鉴摸底.md
> 邻接核实：condition_engine.py（var:codex/param 分册）、assembly/context.py（make_context 注入）、assembly/router_setup.py（REGISTER_GROUPS）、core/fishing_settle.py / core/fishing_codex.py / core/fishing_king.py / commands/fishing_reel_commands.py（fish 册与鱼王接线）、core/forge_king.py（weapon 旁路）、core/environment_lore.py / core/hidden_trigger.py（lore 与隐藏要素）、core/achievements.py（成就接线）、tests/unit/test_codex.py（契约测试）

---

## 〇、总评

批2 三路（2A craft 收敛 / 2B 加权 / 2C 展示+lore）主体均已落位：四册 CATEGORIES（D-01）、数据驱动归属判定（D-04）、加权公式 T=Σwi·Vi/Σwi（§2.2）、交集核算（COD-01）、展示取整+判定未取整（COD-08）、lore 行级解锁（D-05）、木桩引擎侧排除（COD-05）、五档里程碑+90 软锚+三件套（D-06）、/图鉴 总览下一档提示均已实现并有测试覆盖。遗留以接线断点与数据源缺陷为主：**鱼王条目（king）无点亮接线**（TC-02/TC-04 缺口）、**craft 册缺失炼金接线**（D-04 配方产物不计数）、**同步性/幂等语义缺陷**（P0 级 1 项），另有多处 P1/P2。

---

## 一、问题清单

### P0（部署级，1 项）

#### P0-1 里程碑检查（check_milestones）消费方覆盖不全 + 结算点链顺序颠倒：forge/fishing 点亮结算点不触发里程碑 → TC-11~TC-13 部分不可达；同一结算点内成就检测先于里程碑

- 文件：qbot_rpg/core/codex.py L386-401（mark_seen 内 sync_lore_unlocks → check_achievements）；qbot_rpg/commands/battle_commands.py L747-751；qbot_rpg/core/reward.py L483-489；qbot_rpg/commands/forge_commands.py L1072-1077（craft 点亮后无 check_milestones）
- 静态推导：
  1. **消费方仅两处**：全仓 grep `check_milestones(` 调用方 = battle_commands L751（monster 首杀）+ reward L487（item 首获）。**forge 首锻点亮（forge_commands L1075 mark_seen craft）之后没有 check_milestones**；**fish 册首获（fishing_settle L442 fish_codex_update）之后没有 check_milestones**；炼金合成无点亮（P1-1）——锻造全亮/钓鱼全收集这两条主线推进**永远不触发里程碑**，阶梯成就（TC-11~TC-13）对 craft/fish 册路径不可达。契约 §1.8 结算点链（①点亮→②日志→③完成度重判→里程碑→情报）要求每一点亮结算点执行。
  2. **顺序颠倒**：mark_seen 内顺序为 sync_lore_unlocks（L388-391）→（first_seen 时）check_achievements（L395-401）；check_milestones 由外部接线方在 mark_seen **之后**调用（battle L747-751 / reward L483-489）。若某成就条件 `{var:codex, ge, 50}` 与本点亮同刻满足，**成就先于里程碑达成**——里程碑档位成就的奖励（含物品型）发放路径又经 reward 触发 item 首获点亮 → 单结算点内图鉴新增→成就→奖励→图鉴新增**重入链**（有幂等闸但层级嵌套），且与 4d §1.8 ③「里程碑→情报」次序相悖。
  3. **非原子**：battle 首杀分支整体 try/except 吞异常（L739-753）——mark_seen 与 check_milestones 各自独立 try，mark 抛错则里程碑静默跳过（点亮部分写入）；reward 侧同理（L469-489 两个独立 try）。
- 修复建议：
  1. 结算点链收敛为单入口：mark_seen 内部统一按「点亮+日志+投影 → check_milestones → sync_lore_unlocks → check_achievements」顺序执行（放 mark_seen 内可消除静态环的仅有顾虑是 codex_milestones 惰性 import codex——_read_pct 已惰性 import，环可解，或由装配层注入回调）；至少保证**外部接线方覆盖全部四类点亮结算点**（battle/reward/forge/fishing_settle/炼金）。
  2. forge_commands L1072-1077、fishing_settle L440-442 之后补 check_milestones（对齐 battle L747-751 写法）。
  3. check_achievements 移出 first_seen 门或统一到链尾，保证每点亮结算点成就重判。

#### P0-2 鱼王条目（king）零点亮接线：fish 册分母含 king 但分子永不可达 → 100% 不可能、完成度恒缺 1 条（TC-02/TC-04 缺口）

- 文件：qbot_rpg/core/codex.py L186-201（_fish_ids 分母含 king）；qbot_rpg/core/fishing_king.py L192-196（king_victory_record 只计次数）；qbot_rpg/commands/fishing_reel_commands.py L278-289（king_event hook 命中后仅覆写 fs golden）
- 静态推导：全仓 grep：`mark_seen(` 调用方仅 battle_commands（monster）、forge_commands（craft）、reward（item）；fish 册由 fishing_codex.fish_codex_update 自有点亮（species 首获）；**king 条目（king[].id）没有任何地方执行 mark_seen/入册点亮**——king_victory_record 只对 codex_state["fish"]["__meta__"].king_victory_count+1，不写 king 条目 seen。而 _fish_ids 分母（L197-200）**包含 king[].id** → 21 条口径（species20+king）中 king 条目恒未解锁 → fish 册 V 恒 ≤20/21（95.2%），**总册 100% 与「收藏家」不可达**（契约 TC-02「20 条全首获 + 鱼王首胜后 fish 册 = 21/21」、TC-13 100% 三件套无法达成）。契约 L99「鱼王条目解锁 = 讨伐胜利首次」无任何实现载体（king_battle 指令/战场接线缺失）。
- 修复建议：鱼王讨伐胜利结算点（battle 胜利分支或 fishing_reel king 流程）调 `mark_seen(ctx,"fish",king_id,king_name)`（king_id=king 行 id，非 enemies 实体 id——与 _fish_ids 分母同键），并同步 check_milestones；若 fish 册 king 与 monster 册隐藏 BOSS 共用 enemies 实体，需明确「同实体双册计数」还是「monster 册不重复计」（契约 D-02 鱼王→fish 册，建议按 king 行 id 独立条目）。

---

### P1（重要，5 项）

#### P1-1 craft 册无炼金产物接线：D-04 判定器把 recipe 产物计入分母，但炼金结算零 mark_seen → craft 册分子缺失、物品册反向减除把配方产物从 item 册剔除后无处点亮

- 文件：qbot_rpg/core/codex.py L142-183（_craft_ids 含 recipe output.item）、L225-233（item 册反向减除）；qbot_rpg/core/reward.py L466-482（item 首获点亮）；qbot_rpg/commands/alchemy_commands.py（炼金结算，未见 mark_seen，grep 验证）
- 静态推导：craft 分母 = forge 节点 ∪ recipe 产物（L142-183，TC-03 已测）；forge_commands L1075 已 mark_seen(ctx,"craft",…)（单登记，双登记已收敛）；但**炼金合成结算（alchemy_commands 合成流程）没有 mark_seen(ctx,"craft",recipe_output.item)**——全仓 mark_seen 调用方仅 3 处（battle/forge/reward）。同时 reward.py 的 item 首获点亮（L473-480）对**所有 granted type=item 无条件 mark_seen(ctx,"item",…)**——而 item 册分母已反向减除制造品（L227-231），mark_seen 不校验归属（codex.py L350-358 仅查 CATEGORIES 与木桩）→ **炼金产物（如「火伤药」）若经 reward 发放会点亮到 item 册**（悬空条目：分母无此 id，U 不计），**不进 craft 册** → craft 册分子只能靠 forge，D-04「珠/料理→craft」对炼金路径整体落空；且 recipe 产物被 item 册分母剔除后，**没有任何册能正确点亮它**（TC-03/TC-04 断言匕首/火伤药→craft 仅分母侧成立）。
- 修复建议：炼金合成成功结算点补 `mark_seen(ctx,"craft",recipe.output.item,…)`（对齐 forge L1075 单登记）；reward.py item 点亮前用 `item_craft_relation(ctx,iid)`（codex.py L241-251）做归属判定，craft 归属者改 mark craft 册（或跳过由炼金结算点负责），防 item 册悬空点亮。

#### P1-2 mark_seen 内 check_achievements 先于 check_milestones 且成就条件可引用 codex 里程碑——达成序与 4d 结算点链（①点亮→②日志→③里程碑→情报）不一致

- 文件：qbot_rpg/core/codex.py L388-401
- 静态推导：mark_seen 内顺序为 sync_lore_unlocks →（first_seen 时）check_achievements；check_milestones 由外部接线方在 mark_seen **之后**调用（battle L747-751 / reward L483-489）。若成就条件 `{var:codex, ge, 50}` 恰好在本点亮后首次满足，而里程碑 50% 档成就奖励含物品（世界之书等），achievements 先于 milestones 发放 → 里程碑达成瞬间 reward 入包又触发 item 首获点亮（reward L469-482）→ 递归点亮链（图鉴新增→成就→奖励→图鉴新增）存在**单结算点多次重入**风险；同时成就检测与里程碑检测的 ctx["codex"] 投影刷新时机不同步（mark_seen 内 L384 已刷新，二者读取一致，但**执行顺序**颠倒 4d §1.8 ③ 里程碑→情报）。
- 修复建议：统一结算点链顺序：mark_seen（点亮+日志+投影）→ check_milestones → sync_lore_unlocks → check_achievements，由 mark_seen 内部按此序（或外部装配层单点接线），消除双入口。

#### P1-3 sync_lore_unlocks 每次 mark_seen 全量扫描 O(全册条目×resolve)（静态推导复杂度）

- 文件：qbot_rpg/core/codex.py L486-501
- 静态推导：L486-501 循环遍历 `st.items()` 全部四册全部条目（L486-489），对每一条目（含 fish 册 caught_count 条目、无 lore 的 item/craft 条目）都 resolve 一次（L492）→ 每次 mark_seen O(全册条目×resolve)；fish 条目（caught_count≥1）若 enemies.json 不存在该 id，_lore_thresholds resolve 失败返回 []，无害但空转。写回 `dict(raw)` 副本保留全部键，行级状态本身无丢键问题（丢键风险在 P1-4 的 mark_seen 四键覆写路径）。复杂度仅静态推导，正确性无碍。
- 修复建议（P2 级可）：仅遍历 monster 册（lore 仅怪物条目，契约 §5.1），且仅在 first_seen 或 pct 变化时调用。

#### P1-4 mark_seen 重复调用整条目覆写：已解锁条目的 name 被后续非首见 mark 覆盖（旧局快照/多结算点双写）

#### P1-5 鱼王条目 id 与敌人实体 id 的引用对齐风险（_fish_ids 取 king[].id，但 king 战经 enemy_id 引用 enemies 实体——两键空间可能不同）

- 文件：qbot_rpg/core/codex.py L197-200；qbot_rpg/core/fishing_king.py L162（king 行按 species_id 匹配，row 含 enemy_id？未验证字段）；qbot_rpg/commands/fishing_reel_commands.py L278-289
- 静态推导：_fish_ids 分母取 king 行 `id` 键；若 king 行结构为 {species_id, enemy_id}（king 战引用 enemies 实体，契约 L99「king 表引用的 enemies 实体」），**king 条目 id 与 battle 首杀 mark_seen 用的 enemies id 是不同键** → 即使 battle 首杀接线（P0-2 修复后），点亮写的是 enemy id，分母是 king id，分子分母对不上，完成度仍缺。需要确认 king 行 id 字段（fishing.json king[] 的 id 是否即 king 条目 ID）并保证点亮与分母同键。
- 修复建议：明确 king 行主键契约（king[].id），点亮侧与 _fish_ids 统一取该键；契约 §1.3 已定义 king 条目 ID 语义，实现需对齐。

---

### P2（一般，7 项）

#### P2-1 _craft_ids 的 recipe 产物未校验 items.json 存在性：分母可含悬空 id（COD-07 求值失败降级精神，但分母污染）

- qbot_rpg/core/codex.py L170-182：recipe output.item 直接入列表，未查 items 注册表；若 recipe 引用已删除物品 → craft 分母多计、玩家永远无法点亮该条（COD-01 交集只保护分子不保护分母）。建议对 recipe 产物做 items 存在性过滤（对齐 forge 节点隐含存在）。

#### P2-2 item 册反向减除仅对 registry item ids 生效：非 item kind 的制造品（equipment kind 等）可能同时出现在 craft 分母与 item 册外——不重复但语义悬空

- qbot_rpg/core/codex.py L225-233：item 册 = all_ids("item") − craft_ids；若 forge 产物在 items.json 中 kind 非 "item"（如 equipment 表单独登记），该 id 本就不在 item 分母，无碍；但若 forge 产物同时存在于 items 表（kind=item）与 equipment 表，反向减除只剔除 item 侧，craft 侧计入——语义正确（单册归属），仅提示核对数据模型一致性（COD-04 校验器缺位，见 P2-7）。

#### P2-3 _codex_weights 全 0 回落等权是静默行为：契约 §2.1 要求校验器硬拦（配置错误应报错）

- qbot_rpg/core/codex.py L286-287：运行期静默回落等权，无任何告警/日志；契约明确「全 0 = 配置错误，校验器硬拦」。建议 content/validator 增权重建校验（G-16 未落实），引擎侧至少留可观测标记。

#### P2-4 codex_view 分册 total 与 codex_progress 分母口径不一致（seen_map 旧条目并入 all_ids 导致 total 膨胀）

- qbot_rpg/core/codex.py L542-543：`all_ids = reg_ids + seen_map.keys()`——热重载删除条目后，旧局已见条目仍显示在分册页（total 含悬空），而 codex_progress 的 total/seen 用交集口径（COD-01）——**同一分册展示 total 与进度分母不一致**（展示 12/15、进度 12/13 之类）。契约 COD-01 要求交集口径，展示侧应同样剔除未注册 id（或显式标注「已移除条目」）。

#### P2-5 /图鉴 总览与分册对「鱼册特判渲染」绕过 codex_view：/图鉴 鱼 走 render_fish_codex，分册别名「鱼」无 craft 等价的统一渲染——展示层双轨（fish 特判、craft/item 走通用）

- qbot_rpg/commands/codex_commands.py L156-159；契约 §4.2 鱼条目格式为特判预期（冠级标注），但双轨导致总览的「下一档」提示与分册页进度条可能口径不一（总览用 codex_progress，分册鱼页用 fishing_codex 自算）。静态推导无功能错误，属展示一致性风险。

#### P2-6 codex_tpl 无进度条占位符（▓/░）：契约 §4.4 总览要求进度条渲染，当前模板仅百分比数字

- qbot_rpg/core/templates/codex_tpl.py L16-19；codex_commands._overview L75-83 仅输出百分比与下一档。契约 §4.4 展示示例含 ▓▓░░ 进度条（TC-16「进度条/百分比与精确值一致」）。属展示增强缺位，不影响判定。

#### P2-7 COD-04 单册归属校验器缺位：引擎侧无「同一物品 ID 只归一册」的加载期校验

- 契约 §2.3 COD-04 / §七「校验器/编辑器：条目单册归属校验」；当前仅 _category_ids 反向减除保证运行时单册，无配置校验（forge 产物与 recipe 产物 id 冲突、鱼获物品误入 item 册等静默）。建议 content/validator 增归属一致性校验（对齐 TC-03「拦截重复归属配置」）。

---

## 二、四个审查维度逐项确认

### ① 4d 契约落地（关键验收点核对）

| 验收点 | 状态 | 落点 |
|---|---|---|
| 四册 monster/fish/item/craft（D-01） | ✅ 已实现 | codex.py L44-56；CATEGORY_ORDER 四册；test_codex L235-243 断言无 weapon/alchemy |
| item-craft 归属判定（D-04） | ✅ 引擎侧已实现 | item_craft_relation L241-251；_category_ids 反向减除 L225-233；**但炼金侧零接线（P1-1）** |
| 加权完成度 T=Σwi·Vi/Σwi（§2.2） | ✅ 已实现 | codex_progress L310-331；_codex_weights L270-288（可配、默认等权）；test L113 四册等权断言 |
| 交集核算（COD-01） | ✅ 已实现 | 全局分支 L319-324 分子∩_category_ids；test_codex 悬空 id 用例存在 |
| 展示取整（COD-08 展示） | ✅ 已实现 | codex_commands L49/L81 round()；里程碑判定未取整（见下） |
| 里程碑判定未取整精确值（COD-08） | ✅ 已实现 | codex_milestones._read_pct L203-230 float 无 int 截断（G-17 已修复）；codex_commands L88 用 pct_f 原值比较 |
| 里程碑五档+跨档逐档+90 软锚（D-06） | ✅ 已实现 | MILESTONE_DEFS L78-89 含 90%「全收集还有更深处」；check_milestones L364-373 升序逐档；幂等 E-05 |
| lore 行级解锁（D-05） | ✅ 已实现 | sync_lore_unlocks L469-502（unlocked_lore 行数）；mark_seen 内自触发；environment_lore 读路径阈值过滤 |
| 隐藏要素归册（D-02） | ⚠️ 部分 | 分母侧已含（king 入 fish 分母、craft 含隐藏配方产物）；**点亮侧无 hidden 专用接线**——蚀月之狼击败后经 battle 首杀 mark_seen 可点亮（依赖 monster 册首杀接线，已实现），彩蛋物品经 reward 可点亮（已实现），**鱼王经 king_victory_record 零点亮（P0-2）**、隐藏配方经炼金零点亮（P1-1） |
| 木桩排除（COD-05） | ✅ 已实现 | _is_dummy_enemy L117-139；_category_ids monster L217-224 排除；mark_seen L355-358 引擎侧拦截（G-7 已收口） |
| 木桩配置 lore 黄提示（TC-25 后半） | ❌ 缺 | validator 侧未核实（本批文件清单外），标记未验证 |
| /图鉴 下一档提示 | ✅ 已实现 | codex_commands._overview L84-95（MILESTONE_PCTS 未达成最近档；无档 → codex_tier_maxed） |
| 100% 三件套（收藏家/世界之书/隐藏神龛） | ✅ 已实现 | check_milestones _grant_100 L311-334 + _world_book L245-269；**但受 P0-2 影响实际不可达** |
| 分册称号（怪物博士等） | ⚠️ 未落 | 依赖成就 param 条件键——condition_engine L555-562 已支持 param 分册（读 ctx["codex_categories"]，装配层 L494-512/L1228 注入）→ **条件键侧就绪，但 achievements.json 分册称号成就配置未核实（本批清单外）** |
| 隐藏要素⛩️揭示卡 | ✅ 已实现（既有） | hidden_trigger.reveal_find L548-585；**但 lore 补全交接 lore_pending=True 无消费方（见 ④ 遗漏-4）** |
| 图鉴新增日志 codex_new | ✅ 已实现 | mark_seen L372-383 log_codex_new + bump_event；fishing_codex 同款 |

### ② 代码质量

- 边界：空 ref/category 拦截（L350-353）；无 registry fail-safe（L213-215）；分页夹取（L559）；权重数值校验含 bool 排除（L284）。
- 精确值比较：里程碑/下一档均用未取整 float（P0-1 的 _read_pct、codex_commands L88），展示 round()——COD-08 两侧均正确。
- 问题：P0-1（killed 语义/sync 顺序）、P1-1~P1-5、P2-1~P2-7 见上。

### ③ 部署级 P0 五型

1. **指令注册** ✅ codex_commands.register_codex_commands 在 router_setup REGISTER_GROUPS L95（含 /图鉴）；白名单：DEFAULT_WHITELIST 含「图鉴」（codex_commands 文件头标注），未逐行核实白名单表——标「基本可信，未复核行」。
2. **make_context 注入** ✅ router_setup L158-209 统一 _resolve_make_context 注入；context.py L1181-1182 codex_state 注入、L1228 codex_categories 注入、L1095 registry 注入、L1109 fishing 注入（fish 册分母数据源）。
3. **hook 三要素（点亮→日志→里程碑）** ⚠️ 部分：monster（battle L737-751 全链）✅；item（reward L466-489 全链）✅；craft-forge（forge L1075 点亮，**check_milestones 缺——forge 结算点无里程碑检查**）⚠️；fish species（fishing_settle 经 fish_codex_update 点亮，**check_milestones 缺**）⚠️；**fish king 零点亮（P0-2）**❌；craft-alchemy 零点亮（P1-1）❌。
4. **结算零消费方** ❌ check_milestones 调用方 = battle L751 + reward L487 仅两处；**forge/fishing/炼金结算点均未接** → 锻造全亮、钓鱼全收集无法推进里程碑（TC-11~TC-13 部分不可达）。mark_seen 调用方 = battle/forge/reward 三处（fish 走专用函数）。
5. **成就接线** ⚠️ mark_seen 内 first_seen 才 check_achievements（L395-401）；forge/fishing 点亮不走 mark_seen（fish 专用函数、forge 直调 mark_seen 会触发）——forge 侧经 mark_seen 会触发成就 ✅，fish 册成就检测依赖 codex_categories 条件键的读取路径（condition_engine 已支持），但 **fish 点亮无成就结算点触发**（fishing 路径不调 check_achievements）⚠️。

### ④ 遗漏（验收点未覆盖）

1. TC-02 鱼王条目点亮（P0-2）——21/21 不可达。
2. TC-03/TC-04 炼金配方产物入册（P1-1）——craft 册分子缺炼金。
3. TC-11~TC-13 里程碑触发依赖 check_milestones 接线——forge/fishing 结算点未接（P0 级接线缺失，与 P0-1 合并为同一接线面）。
4. TC-24 隐藏 BOSS 击败 lore 全集一次性解锁——reveal_find 的 lore_pending=True 无消费方，unlock_lore_wired 无调用方（grep 验证：仅定义）；sync_lore_unlocks 按阈值逐行解锁，**不实现「隐藏要素发现后全集解锁」**（契约 §5.4 L356）。蚀月之狼 lore unlock 全 100 时，全局完成度需 ≥100 才全解锁——与「击败即补全」语义不符。
5. TC-16 进度条 ▓/░ 未渲染（P2-6）。
6. TC-18 冠级标注复核：fishing_codex.render_fish_entry_line 已实现（本批清单外，未逐行复核）。
7. TC-25 校验器 lore 非递增/越界/木桩黄提示：validator 侧未核实（清单外），标记待复核。
8. 分册称号成就（怪物博士等）配置未核实（清单外）。

---

## 三、结论

- **P0：1 项**（P0-1 mark_seen 结算点链时序/同步缺陷 + P0-2 鱼王 king 条目零点亮 → 100% 不可达——两者均阻断 TC-02/TC-13 验收）
- **P1：5 项**（P1-1 炼金 craft 零接线；P1-2 成就/里程碑顺序；P1-3 lore 全量扫描；P1-4 mark_seen 覆写；P1-5 king id 键空间对齐）
- **P2：7 项**

无问题维度确认：四册定义/加权公式/交集核算/展示取整/里程碑精确值比较/木桩排除/lore 行级解锁主路径/下一档提示均已正确实现并有契约测试覆盖（test_codex.py L102-243 四册加权、craft 分母、weapon 收敛断言齐全）。
