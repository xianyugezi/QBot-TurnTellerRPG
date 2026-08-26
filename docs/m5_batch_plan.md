# M5 批次派工单 v2（消息模板与渲染层 D1-D5 · 6 批 12 任务）

> 版本：v2.0 · 2026-08-27 · 依据 docs/m5_shared_contract.md（唯一契约）+ 细化_3d/5e/3h/3b/4f + 已实现渲染模块
> 节奏：每批 2 路并行（delegate_task）→ 批间收口（落盘核对 + 接线 + 全量回归 + commit）→ 全部完成后 dsh 审实现
> 已实现（M4 顺带，勿重做）：prefix_render/list_render/panel_render/sender/basic_commands.cmd_view

---

## 批0 公共接线（D1 + 3h）——2 路

### M5-01 消息前缀消费接线
- **内容**：message_prefix settings 段全字段消费——`show_on_system`（系统公告/群广播豁免，默认 false，true 时也加）、`per_channel`（all/group/private 渠道限定）、`enabled` 总开关（默认 true，false 完全无前缀）；前缀渲染结果注入玩家指令回复**首行**（装配层统一入口，非各指令自行拼装）；**截断黄提示发射**——消费 `render_prefix_result().truncated` → 输出「前缀过长已截断」（归属发起指令所在群，不阻断正文，3d §3.3/TC-13/【前缀】L100）。
- **依据**：shared_contract §一 / 细化_3d §1.5/§3.3 / 【前缀】§五/§七 / 3h §6.1
- **实现位置**：qbot_rpg/commands/ 装配层（router 或 sender 注入点）+ settings 读取 helper；用真实签名 `render_prefix(level, name, title, *, format_template, hide_when_empty, empty_title_text, prefix_max_len, extra)`（[群名]/[职业] 经 extra 传入）
- **验收**：① show_on_system=false 系统公告无前缀，true 时加 ② per_channel=group 仅群聊/private 仅私聊 ③ enabled=false 完全无前缀 ④ 玩家回复首行带前缀、多行仅首行 ⑤ 前缀不影响指令解析 ⑥ 前缀超长→截断+黄提示，正文照常（TC-13）

### M5-02 message_prefix 校验器接线（规则源【前缀】§九 + 3d 附校验器行）
- **内容**：settings.json message_prefix 段校验器——硬拦（enabled 非布尔/format 非字符串/prefix_max_len 负数/结构错误）+ 黄提示（未知占位符原样输出、format 空按默认补全、format>80 字符/占位符>10 个、per_channel 非法按 all 补全、prefix_max_len>200）。
- **依据**：【前缀】§九（L112-121）/ 细化_3d 附·校验器行（L358）/ shared_contract §1.4；3h V9~V12 不覆盖 message_prefix
- **实现位置**：qbot_rpg/content/ 校验器（settings 段注册）
- **验收**：非法包红/黄分类正确（对齐 3d 附 L358）

## 批1 战斗渲染·骨架 + 玩家侧（D5）——2 路

### M5-03 battle_render 骨架 + 玩家行动基础模板（BREP-01~06）
- **内容**：按**现有骨架签名**实装 render_battle_start/render_battle_round/render_battle_end 骨架 + 玩家行动基础模板——BREP-01 前缀行（委托 prefix_render）/02 攻击命中（`✅ 你{攻击动作}{目标}，造成 {伤害} 伤害（{目标} {剩余HP}/{最大HP}）`——HP 后缀必须保留；{目标} 可选仅指动作短语）/03 未命中/04 会心·格挡附注（会心档 ×2.2/1.7/1.3、格挡 ×0.5）/05 防御/06 防御受击。
- **依据**：5e BREP-01~06 + TC-07~10 / shared_contract §5.2 / 铁律 3/8/9
- **输入**：`TurnReport`（outcomes 流水）+ `ActionOutcome`（实际字段 ok/hit/crit/blocked/raw_damage/final_damage/target_hp/side_effects/message/battle_ended/status；战报伤害取 final_damage、目标 HP 取 target_hp）；不直接复用引擎 message
- **验收**：TC-07/08/09/10 逐字对齐（含 `（史莱姆 7/25）` HP 后缀）；无 emoji（✅/❌ + 排版符号）

### M5-04 玩家技能 + 状态资源差分行 + 操作提示行（BREP-07~09）
- **内容**：BREP-07 技能释放（`✅ 你施放{技能}：{效果描述}（{资源变化}）`）/08 状态资源差分行（`{状态项} {旧值}→{新值}`，**只渲染实际变化轴**；状态数默认前 5 个，超出追加「还有 N 个状态」——开发规则 L509）/09 操作提示行（`你 {HP}/{最大} | {目标} {HP}/{最大} → /攻击[技能] /道具 /防御 /逃跑`，多怪取第一存活怪）。
- **依据**：5e BREP-07~09 + TC-11 / shared_contract §5.2 / 铁律 10
- **验收**：TC-11 逐字对齐（治疗术 MP 30→22 消耗 8）；状态差分只显变化轴；操作提示行含 /最大 分母

## 批2 战斗渲染·怪物 + 结算连段（D5）——2 路

### M5-05 怪物行动模板（BREP-10~14）
- **内容**：BREP-10 反击命中（`❌ {怪物}{攻击动作}，你受到 {伤害} 伤害（HP {剩余}/{最大}）`）/11 攻击未命中/12 意图预告（`{怪物} 蓄力中（下回合发动「{招名}」）` 固定句式 D-5E）/13 特殊行动/14 拦截链效果行（盾吸收/反弹/免疫）。
- **依据**：5e BREP-10~14 + TC-12~15 / shared_contract §5.2 / 铁律 9
- **验收**：TC-12~15 逐字对齐；先手击杀不渲染怪反击行（写死）

### M5-06 结算 + 连段模板（BREP-15~22）
- **内容**：结算——BREP-15 击杀（`✅ 你击败了{怪物}！` 紧跟伤害行）/16 玩家死亡/17 胜利/18 失败/19 互杀平局（默认 draw，可配 player_loss）/20 经验与掉落（`✅ 获得 经验 {n}、金币 {n}、{素材}×{n}` 只在战斗结束消息输出一次）；连段——BREP-21 段行（`第 {N} 段：…` 每段独立一行，段号=收集器 seg）/22 结算行（`连段 {N} 段已结算（{备注}）`；BOSS 死立即结束后续段作废）。
- **依据**：5e BREP-15~22 + TC-16~23 / shared_contract §5.2 / 铁律 9/11
- **验收**：TC-16~23；击杀紧跟伤害行；胜利/掉落同消息且只一次；BOSS 提前结束后续段作废

## 批3 战斗渲染·开始结束 + 接线（D5/D2）——2 路

### M5-07 开始/结束/明细战报（BREP-23~25 + 16 行折叠）
- **内容**：BREP-23 战斗开始（`与{怪物}的战斗开始！{怪物} {HP}/{最大HP}` + 意图/弱点情报行）×1 条 /BREP-24 汇总（`战斗结束：{胜负}｜回合数 {N}｜输入 /战斗记录 查看明细`）/BREP-25 木桩明细块（摘要行 `总伤害 {N}｜最大单段 {M}｜会心 {K} 次｜格挡 {G} 次` + 条目行 `{来源} {总伤害}（{占比}%）` + 5 条/页分页 + **≤16 行折叠** TPL-09，普通战斗默认不展示）。
- **依据**：5e BREP-23~25 + TC-24~27 / shared_contract §5.2 / 铁律 4/11
- **验收**：TC-24~27；开始 1 条/结束 1 条；木桩 5 条/页 + ≤16 行折叠（TC-06）

### M5-08 战斗接线 + 消息合并
- **内容**：battle.py 引擎回合结果 → battle_render 渲染 → 消息合并（一轮=1条，前缀只加首行，战斗开始=1条/结束=1条，单次操作≤1-2条）→ 走 Sender 统一出口；战斗指令（/攻击 /防御 /逃跑 /道具）输出走此管线。
- **依据**：shared_contract §二/§五 / 3d §3.1 承接表 / 框架 §8.3 / 铁律 2/7
- **验收**：一轮 1 条（行动+反击合并）；开始/结束独立 1 条；无裸 send

## 批4 探索 + 筛选 + emoji 降级（D2/D3/D4）——2 路

### M5-09 探索结果 1 条 + 筛选链
- **内容**：① 探索结果消息合并 1 条（世界层探索/移动/采集出口，单次≤1-2 条——铁律 2 / 开发规则 L515）；② 筛选链实现（`背包筛选 装备 类型 武器 品质 史诗`：类型→子类→品质可叠加，框架 §7.4 / 4f RUL-16 / TC-14）。
- **依据**：shared_contract §三 / 3d §2/§3.1 / 框架 §7.4 / 开发规则 L508/L515
- **验收**：探索 1 条；筛选叠加生效；筛选结果 >5 条分页 5 条/页 + TPL-08（TC-14）

### M5-10 全仓渲染输出 emoji 降级
- **内容**：全仓渲染输出中非 ✅❌ 非排版符号的 emoji 一律降级纯文本——gm_commands 🚫→❌（封禁行，注释「数据型功能图标豁免」删）、combo 🔥→✅（完美连段）、quest ⚠️→❌（物品未入包）、basic_commands 背包行 items icon 渲染剥离、NPC/商店/天气/印记 icon 渲染剥离（保纯文本/自定义文本符号）、单机向 ⛩️ 揭示卡改纯文本；tests fixtures 中 emoji icon 数据清理（npc 🙂/shop 🏪🧺🔨🏰🎆🌙/weather ☀️☁️🌧⛈🌫 等改纯文本或删）。
- **依据**：M5 裁决「不用 emoji」/ shared_contract §4.1 / 铁律 3
- **验收**：全仓渲染路径零非 ✅❌ emoji；fixture 无 emoji icon 数据；相关测试断言同步

## 批5 收口（D4 + G5）——2 路

### M5-11 emoji 登记表 + 全仓静态检查脚本
- **内容**：全局图标登记表（= ✅❌ + 排版符号豁免 `| → × / 「」【】`，无其他 emoji 出口）+ 全仓渲染输出 emoji 静态检查脚本（渲染字符串 grep 非 ✅❌ 非排版符号 emoji，命中=0）接入 run_all_tests.py。
- **依据**：3d §四 / TC-18/19 / M5 裁决 / shared_contract §4.1
- **验收**：检查脚本通过全仓（零命中）；禁用 emoji 用例被拦截

### M5-12 verify_m5 门禁（G5）
- **内容**：verify_m5.py——81 TC 覆盖点（3d 26 + 5e 27 + 4f 28，诚实化：已承载 + DELAYED 注明理由）+ 新增门禁断言（前缀验收示例逐字、一轮=1条合并、/角色 三层行、emoji 静态检查、无裸 send）+ 子进程 pytest。接入 run_all_tests.py。
- **依据**：5d 测试体系总纲 / 3d/5e/4f TC 矩阵 / shared_contract §六
- **验收**：全量回归全绿；verify_m5 覆盖点诚实声明

---

## TC-01~27 ↔ M5 验收映射表

| TC 区间 | 内容 | M5 验收归属 |
|---|---|---|
| TC-01/02 | 单条+前缀首行 / 前缀三态 | M5-01 + M5-08 |
| TC-03 | 前缀截断 + 黄提示 | M5-01 验收⑥ |
| TC-04/05 | emoji 扫描 / 排版符号 | M5-11 |
| TC-06 | BOSS 45 回合 ≤16 行 | M5-07 + M5-08 |
| TC-07~11 | 玩家行动 | M5-03 + M5-04 |
| TC-12~15 | 怪物行动 | M5-05 |
| TC-16~23 | 结算 + 连段 | M5-06 |
| TC-24~27 | 开始/结束/明细 | M5-07 |

## 依赖与锚点

- **依赖**：批0 独立；批1（M5-03/04）→ 批2（M5-05/06）→ 批3（M5-07 渲染片段独立，M5-08 接线依赖 M5-03~07）；批4 的 M5-09 独立、M5-10 独立；批5 的 M5-11 依赖 M5-10、M5-12 依赖全部
- **共享引用锚点**：TPL-01~14（3d）/BREP-01~25（5e）/TPL-4F-13（4f）/TPL_REGISTER_GATE（basic_commands）；错误文案常量在 errors.py
- **互引**：M5-03~07 同属 render_battle_round 拼接，各路实现本侧模板，收口对齐拼接顺序（先手行→击杀→后手行→结算，铁律 9）；M5-08 以各模板函数为准接线
- **已实现勿重做**：prefix_render/list_render/panel_render/sender/cmd_view（M4）；battle.py 引擎不改（只消费 TurnReport/ActionOutcome）
