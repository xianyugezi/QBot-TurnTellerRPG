# M5 共享契约（消息模板与渲染层 · D1-D5）

> 版本：v1.0 · 2026-08-27 · 类型：里程碑共享契约（大厂模式：字段表 / 接口清单 / 模板注册表 / 已实现-待实现矩阵 / TC 矩阵 / 铁律 / 验收）
> 依据：细化_3d_消息模板规范（v1.0，26 TC）· 细化_5e_战斗战报格式（v1.0，27 TC）· 细化_3h_settings 通用设置 · 细化_3b_玩家属性三层 · 细化_4f_基础指令组（28 TC）；实现层规划 §4 D 组（D1-D5）
> 定稿：docs/审查参考/（消息前缀功能设计定稿 · RPG回合制框架设计文档 · 玩家属性方案定稿 · 开发规则文档 · 战斗数值层设计定稿）
> 状态：M5 设计审查 3 批（P0×1+P1×7+P2×28）已修复 + 用户 3 项拍板（/角色 更名 / K=1 定稿回写 / 无条件全层展示）已落地；本契约 = 实现层唯一依据

---

## 〇、铁律十条（不可违背项，全部源自细化/定稿/拍板）

1. **前缀只加首行**：玩家指令回复首行渲染 message_prefix（TPL-01~06），多行回复仅首行带前缀；前缀不进解析器/条件键/存档（纯渲染层产物）。【3d §3.1 / 【前缀】§五】
2. **一轮战斗 = 1 条消息**：玩家行动+怪物反击合并；战斗开始=1条 / 战斗结束=1条 / 探索结果=1条；**单次操作最多 1-2 条消息**。【3d §3.1 承接表 / 框架 §8.3】
3. **少 Emoji 只留 ✅/❌**：功能性标记仅 ✅（成功）/❌（失败）；装饰性 emoji（🔥🟢💥⚔️🛡️✨⭐ 等）全局禁用；定稿示例的 🔥/🟢 一律降级为 ✅/❌ 或纯文本；排版符号（`|` `→` `×` `/` `「」` `【】`）豁免非 emoji。【3d D-01 / 5e 军规2】
4. **列表 5 条/页**：列表类回复每页最多 5 条（默认，可配），页码可输入；页脚固定 TPL-08；单页无页脚；超总页数**夹取最后一页**+「已到最后一页」，0/负数/非数字 TPL-12 报错。【3d §二 / 裁决②】
5. **错误统一文案**：三类错误（指令/条件/资源）固定 TPL-12/13/14（errors.py 唯一文案源），禁止自造。【3d §五】
6. **/角色 = 三层属性明细**：指令名 /角色（已更名）；LV 行固定头部 + 白值/加成/临时三层折叠行；**无条件全层展示**（战斗外/战斗中均显示临时层）。【4f §2.5 / 裁决①③】
7. **发送走统一出口**：全部发送路径必须走 Sender，禁止裸 send；CQ 转义防注入；超长分两条不吞消息；失败指数退避重试（不无限重发）。【3d §3.4 / 框架 §15.7】
8. **前缀不计入长度判定**：防刷屏判定只计正文；prefix_max_len 截断+黄提示不阻断正文。【【前缀】§七】
9. **渲染顺序对齐判定顺序**：战报行序 = 回合死亡判定顺序（回合开始 dot→即死→先手→击杀→后手→tick→互杀→结算）；击杀行紧跟伤害行。【5e 军规4】
10. **状态行差分**：只渲染实际变化的资源轴；状态数默认前 5 个，超出追加「还有 N 个状态」。【5e D-5D / 开发规则 L509】
11. **结算一次性 + 16 行折叠**：胜负/奖励/掉落/快照统一当轮事件末尾结算一次，经验/掉落只在战斗结束消息输出一次；BOSS/最后目标死亡→立即结束、后续事件作废不渲染；单条消息 ≤16 行折叠上限（超限按正文尾部→中间过程行折叠 TPL-09；3d §3.2 L184 / 5e TC-06；与 sender 分两条为分层关系：内容层按行折叠、传输层按字符分条）。【5e 军规5 / 3d §3.2】

---

## 一、D1 message_prefix 前缀渲染器

### 1.1 message_prefix settings 段字段表（7 字段，来源【前缀】§三）

| 字段 | 类型 | 默认 | 枚举/说明 |
|---|---|---|---|
| enabled | bool | true | 总开关，内容包可关 |
| format | string | `Lv[等级].[玩家名] -[称号]-` | 占位符自由组合，任意顺序/重复/单用 |
| show_on_system | bool | **false** | 系统公告/群广播是否也加前缀 |
| per_channel | string | **"all"** | all 群聊+私聊 / group 仅群聊 / private 仅私聊 |
| hide_when_empty | bool | false | 无称号整段省略 [称号]+相邻装饰符+尾空格清理 |
| empty_title_text | string | **"-"** | 无称号时 [称号] 输出；"" 仅隐本体保留装饰符 |
| prefix_max_len | int | 40 | 前缀渲染后最大长度，0=不限，超长截断+黄提示 |

### 1.2 占位符体系（5 个，【前缀】§四）

| 占位符 | 取值来源 | 备注 |
|---|---|---|
| [等级] | 存档 level | — |
| [玩家名] | 角色名 | 无则 QQ 昵称兜底 |
| [称号] | 佩戴称号状态 | 无称号→empty_title_text 三态 |
| [群名] | 消息所在群 | 私聊="私聊" |
| [职业] | jobs.json 当前职业 | — |

### 1.3 模板（TPL-01~06）与接口

- TPL-01 `Lv[等级].[玩家名] -[称号]-` / TPL-02 `Lv[等级].[玩家名] - -` / TPL-03 `Lv[等级].[玩家名]`（hide_when_empty）/ TPL-04 `Lv[等级].[玩家名] - -`（仅隐本体）/ TPL-05 `[职业] Lv[等级].[玩家名]` / TPL-06 `【[群名]】[玩家名]`
- **IF01** `render_prefix(level: int, name: str, title: Optional[str] = None, *, format_template: Optional[str] = None, hide_when_empty: bool = False, empty_title_text: str = "-", prefix_max_len: int = 40, extra: Optional[Mapping[str, object]] = None) -> str`（prefix_render.py 已实装；**[群名]/[职业] 经 `extra={"群名":…,"职业":…}` 传入**）
- **IF01b** `render_prefix_result(level, name, title, *, format_template=None, hide_when_empty=False, empty_title_text="-", prefix_max_len=40, extra=None) -> PrefixResult`（返回 PrefixResult 含 `truncated` 截断信号，3d §3.3/TC-13 消费）
- **IF02** settings 读取：message_prefix 段 → prefix_render 参数（M5 接线）

### 1.4 已实现 / 待实现

| 项 | 状态 |
|---|---|
| render_prefix 纯渲染（三态/截断/未知占位符/尾空格清理） | ✅ prefix_render.py（139 行） |
| format/hide_when_empty/empty_title_text/prefix_max_len 字段消费 | ✅ prefix_render 内 |
| **enabled / show_on_system / per_channel 消费接线**（总开关/系统消息豁免/渠道限定，装配层） | ⬜ M5-01 接线（prefix_render 无这些参数，由调用方控制） |
| **截断黄提示发射**（消费 `PrefixResult.truncated` →「前缀过长已截断」，归属发起群，不阻断正文；3d §3.3 / TC-13） | ⬜ M5-01 装配层 |
| **前缀挂到玩家回复首行**（所有指令出口） | ⬜ M5 接线（装配层统一注入） |
| message_prefix 校验器（**来源【前缀】§九 + 3d 附校验器行 L358**：硬拦 enabled 非布尔/format 非字符串/prefix_max_len 负数/结构错误；黄提示未知占位符/format 空补全/超长>80/占位符>10/per_channel 非法按 all/prefix_max_len>200） | ⬜ M5-02 接线（settings 校验器） |

---

## 二、D2 统一发送出口与消息合并

### 2.1 接口（sender.py 已实装，192 行）

- **IF10** `cq_escape(text) -> str`：CQ 码转义防注入
- **IF11** `segment_by_length(text, budget=4000) -> list[str]`：超长分两条不吞消息（sender.py 已实装，参数名 **budget**）
- **IF12** `format_tpl12/13/14(...)`：错误统一文案（与 3d TPL-12/13/14 逐字一致）
- **IF13** `Sender`：统一出口，失败指数退避重试（MAX_RETRIES=3/BACKOFF_BASE=2.0）
- **IF14** `page_error_tpl12(...)`：页码非法→TPL-12+页脚

### 2.2 已实现 / 待实现

| 项 | 状态 |
|---|---|
| CQ 转义 / 长度分条 / 重试退避 / 统一出口 | ✅ sender.py |
| **渲染层长度预算统一**（共用 `sender.DEFAULT_LENGTH_BUDGET`，禁止各系统自定上限；3d §3.4 第 5 条） | ⬜ M5 确认（共享常量引用） |
| **消息合并策略落地**（战斗一轮=1条/开始=1条/结束=1条/探索=1条/单次≤1-2条） | ⬜ battle_render + 探索渲染消费（D5） |
| **全仓「禁止裸 send」审查**（D2 验收④） | ⬜ 静态检查（verify_m5） |

---

## 三、D3 分页与筛选（5 条/页）

### 3.1 接口（list_render.py 已实装，201 行）

- **IF20** `resolve_page(raw_page, total, per_page=5) -> PageResolution`：0/负数/非数字→invalid；超总页数→clamp 最后一页+LAST_PAGE_HINT
- **IF21** `page_items / render_item_line / render_footer / render_list_page`：条目行 TPL-07 + 页脚 TPL-08 + 单页无页脚
- 页码语法：`/指令 页码` 与 `背包2` 粘合等价（4f RUL-16）

### 3.2 已实现 / 待实现

| 项 | 状态 |
|---|---|
| 分页 5 条/页 / 页脚 TPL-08 / 越界夹取 | ✅ list_render.py |
| **空列表文案**（各业务自定，**禁 emoji 装饰**；3d §2.1） | ⬜ M5 确认（4f 已有 `❌ 背包空空如也` 作锚点） |
| **筛选链**（`背包筛选 装备 类型 武器 品质 史诗`：类型→子类→品质可叠加） | ⬜ M5-07 实现（框架 §7.4 / 4f RUL-16） |
| 各业务系统列表走统一分页（商店/背包/任务/签到/图鉴/成就） | ✅ M4 已接（shop/checkin/quest/basic） |

---

## 四、D4 少 emoji 模板库

### 4.1 纪律（3d §四 · M5 裁决：不用 emoji）

- **唯一允许功能性标记：✅（成功）/❌（失败）**；位置约束：✅/❌ 只能出现在**结果行行首**，一行至多一个，其后必须纯文本描述（3d §4.1）
- **【2026-08-27 用户拍板：不用 emoji】**：除 ✅/❌ 功能性标记外，**渲染输出不含任何 emoji 字符**——含数据型功能图标（物品 icon / NPC 类型图标 / 商店 icon / 天气 emoji / 印记 icon / GM 结果前缀 🚫⚙️📝 / 单机向 ⛩️ 揭示卡）一律降级为纯文本（文本符号或 ✅/❌）；**M4 契约 §2.2「数据型功能图标豁免」条款作废**（以本裁决为准）
- **数据 icon 字段处理**：内容包 schema 的 icon 字段（items.json/npc.json/shop.json/weather_pool/marks.json）**保留字段但渲染时剥离 emoji 字符**（保纯文本/自定义符号，作者可配「火」「+」等文本图标）
- 禁用清单（渲染输出 grep 必零命中）：🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸ + 其余一切非 ✅❌ emoji（3d TC-18）
- 排版符号豁免：`|` `→` `×` `/` `「」` `【】`（5e D-5B）
- 前缀区纯文本无 emoji（TC-19）
- **登记表 = ✅❌ + 排版符号豁免**（无其他 emoji 出口）；3d/5e「唯二 emoji=✅❌」措辞成立；规划_路3 L171 旧登记表（⚔️🟢❤💙💰⛩️）口径作废

### 4.2 已实现 / 待实现

| 项 | 状态 |
|---|---|
| 已实现模块无装饰 emoji（prefix/list/panel/sender） | ✅ |
| **全仓渲染输出 emoji 降级**（gm 🚫→❌ / combo 🔥→✅ / quest ⚠️→❌ / basic 背包 icon / NPC/商店/天气 icon 剥离；既有引擎输出清理） | ⬜ M5-08（含 fixture 数据清理） |
| **全局固定图标登记表**（= ✅❌ + 排版符号豁免，无其他 emoji 出口） | ⬜ M5-08 产出 |
| **全仓渲染输出 emoji 静态检查脚本**（渲染字符串 grep 非 ✅❌ 非排版符号 emoji，命中=0） | ⬜ M5-08（verify_m5） |
| battle_render 实装遵守 ✅/❌ + 禁 emoji | ⬜ D5 实装时 |

---

## 五、D5 战斗/状态消息模板 + /角色 三层展示

### 5.1 battle_render.py（50 行骨架 → 需实装）

- **IF30** `render_battle_start(party, enemy, hint=None) -> str`（**骨架现有签名，M5-03 按此实装不改签名**；`hint` 承载意图/弱点情报行，映射 BREP-23）
- **IF31** `render_battle_round(round_result) -> str`：BREP-01~22（玩家行动+怪物反击合并 1 条消息）
- **IF32** `render_battle_end(player, enemy, winner, summary=None) -> str`（**骨架现有签名**；`winner` 胜负结果、`summary` 承载 BREP-24/25 汇总与明细）
- 引擎输出源：**`TurnReport`**（turn/phases/player/enemy HP/ended/status/**outcomes** 流水）+ **`ActionOutcome`**（**实际字段 = ok/seq/actor/action_type/target/hit/crit/blocked/raw_damage/final_damage/target_hp/side_effects/message/battle_ended/status**——注意**无 rating/damage/outcomes 字段**）
- **取数口径**：战报伤害 = `final_damage`（拦截链后实际扣血，对齐 5e §2.1）；目标 HP = `target_hp`（扣血后即时值）；`outcomes` 在 TurnReport 不在 ActionOutcome
- **⚠️ 5e P2-8：对外战报文案由 battle_render 按 BREP 模板生成，不直接复用引擎 ActionOutcome.message**（引擎内部 message `{attacker} 对 {target} 造成 {damage} 伤害` 与 BREP-02 句式不同）

### 5.2 BREP 模板注册表（25 条，5e §1.4）

- 骨架：BREP-01（前缀行归 D1）/BREP-09（操作提示行 `你 {HP}/{最大} | {目标} {HP}/{最大} → /攻击[技能] /道具 /防御 /逃跑`）
- 玩家行动：BREP-02 攻击命中（`✅ 你{攻击动作}{目标}，造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`——**HP 后缀必须保留**；`{目标}` 可选仅指动作短语「你{攻击动作}」，省略时 `你施放火球术，造成 …`）/03 未命中/04 会心·格挡附注/05 防御/06 防御受击/07 技能释放/08 状态资源差分行
- 怪物行动：BREP-10 反击命中（`❌ {怪物}{攻击动作}，你受到 {伤害} 伤害（HP {剩余}/{最大}）`）/11 攻击未命中/12 意图预告（`{怪物} 蓄力中（下回合发动「{招名}」）`）/13 特殊行动/14 拦截链效果行
- 结算：BREP-15 击杀（`✅ 你击败了{怪物}！`，**紧跟伤害行**）/16 玩家死亡/17 胜利/18 失败/19 互杀平局/20 经验与掉落（`✅ 获得 经验 {n}、金币 {n}、{素材}×{n}`，**只在战斗结束消息输出一次**——军规5）
- 连段：BREP-21 段行（`第 {N} 段：…` 每段独立一行，每段独立取整，段号=收集器 seg）/22 结算行（`连段 {N} 段已结算（{备注}）`；BOSS 死立即结束后续段作废——军规5）
- 开始/结束/明细：BREP-23 战斗开始（`与{怪物}的战斗开始！{怪物} {HP}/{最大HP}` + 意图/弱点情报行）/24 汇总（`战斗结束：{胜负结果}｜回合数 {N}｜输入 /战斗记录 查看明细`）/25 木桩明细（摘要行 `总伤害 {N}｜最大单段 {M}｜会心 {K} 次｜格挡 {G} 次` + 条目行 `{来源} {总伤害}（{占比}%）` + 5 条/页分页 + **≤16 行折叠**）
- **渲染顺序**：对齐回合死亡判定顺序（铁律 9）

### 5.3 /角色 三层展示（4f §2.5 CMD-09，已实现）

- 指令 `/角色 [页码]`；LV 行固定头部 `【角色】Lv3.阿伟（战士） ｜ 经验 320/1000`（满级→【已满级】）
- 三层折叠行：`1. 【力量】26（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）`（3b 三层模型；**示例数值应为 29**——15+5→20×1.10→22×1.20→26.4+临时flat3→29.4→29，3b TC-03 管线）；resource 型变体：`1. 【生命】21/30（白值 15 ｜ 加成 +5·+10% ｜ 临时 +3·+20%）`（4f RUL-38）
- 9 属性 5 条/页（2 页）+ TPL-08 页脚 + 裁决②夹取；未注册→TPL_REGISTER_GATE
- ✅ basic_commands.py cmd_view/attr_line 已实现（M5 无需重做，纳入回归）

### 5.4 已实现 / 待实现

| 项 | 状态 |
|---|---|
| panel_render.py 渲染助手（render_panel/render_stats_line/paginate 存在；**/状态 指令未注册**，面板五区随装配层批次承接——verify_m5 4f TC-07/09/10 DELAYED 同口径） | ✅ 助手存在 / ⬜ 指令待装配 |
| /角色 三层明细（cmd_view/attr_line） | ✅ |
| **battle_render.py 实装（BREP-01~25 + 27 TC）** | ⬜ M5 最大块 |
| **战斗渲染接线**（引擎 ActionOutcome→battle_render→消息合并/前缀首行） | ⬜ M5 |
| **状态行规则**（前 5 个 + 还有 N 个状态） | ⬜ battle_render 内 |
| **意图预告/拦截链行/连段段行**（BREP-12/14/21/22） | ⬜ battle_render 内 |
| **探索结果 = 1 条**（世界层探索渲染） | ⬜ 确认（map 探索出口） |
| /查看目标（掉落不显示，框架 §7.6） | ⬜ 待承接（战斗指令批次，4f §2.6 挂靠说明） |

---

## 六、TC 矩阵汇总（实现验收锚点）

| 细化 | 用例数 | 范围 |
|---|---|---|
| 3d 消息模板 | 26（TC-01~26） | 前缀渲染 6 / 分页 6 / 长度折叠 3 / emoji 4 / 错误 3 / 联动 4 |
| 5e 战斗战报 | 27（TC-01~27） | 单回合单条 6 / 玩家行动 5 / 怪物行动 4 / 结算 5 / 连段 3 / 开始结束明细 4 |
| 4f 基础指令 | 28（TC-01~28） | 含 /角色 4（TC-25~28） |

**合计 81 个 TC** 为 verify_m5 覆盖点基准；另加 D2 全仓无裸 send / D4 emoji 静态检查 / D1 前缀验收示例逐字断言。

---

## 七、M5 实现批次建议（详见 m5_batch_plan.md）

- 批0 公共接线：message_prefix 消费接线（show_on_system/per_channel）+ 前缀挂首行 + settings 校验器 V9~V12
- 批1 战斗渲染：battle_render 实装（BREP-01~25 + 状态行规则 + 意图预告/拦截链/连段）
- 批2 战斗接线：引擎→渲染→消息合并（一轮=1条/开始/结束）+ 探索 1 条 + 筛选链
- 批3 收口：emoji 登记表 + 静态检查 + verify_m5（81 TC 覆盖点）+ 全量回归 + 记录.md
