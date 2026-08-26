# M4 共享契约（交互系统 · 指令解析 + NPC/商店/任务/签到）

> 多路并行权威依据。2026-08-27 定稿审查（4 批 dsh）已过、用户 8 项拍板已回写 7 份细化。
> 行号引用以 docs/细化/ 各细化 + docs/审查参考/ 定稿副本为准；本契约 = 实现层唯一权威（冲突时以本契约为准 + 登记 contract_deviations）。
> 铁律沿用 M3：零 NoneBot import（commands/ 层除外）、纯函数/懒计算、确定性（rng 注入）、工程补白显式标注、文件头标注依据、不 git commit（子代理）。

## §0 用户 8 项拍板（2026-08-27，已回写细化，实现必须遵守）
1. 战斗中裸数字 = 快捷绑定（无会话上下文，快捷表生效）；选技能用带指令词「/攻击 2」（3c P0-1）
2. 列表页码超总页数 → 夹取最后一页 + 提示「已到最后一页」；0/负数/非数字 → TPL-12 报错（3d P0-2）
3. 对话树深度可配 `settings.max_dialog_depth`（默认 2，0=不限），超深软拦（2b1 P1-1）
4. 发牌员策略枚举保留细化版 `rotate/random/condition`（定稿 first_match/weighted/random 作兼容映射：first_match→condition、weighted→random 等权、random→random），保留兼容迁移提示（2b1 P1-2）
5. 商店 stock（global 库存）+ per_player（personal 限购）**同条目并存**（scope 只管默认侧；L450/L465 型无损表达）（2b3 P1-2）
6. 商店不配置 refresh = **永不刷新**（配置才刷新；TC-36 一致）（2b3 P1-4）
7. 补签只恢复 signed_days 与 streak 连续性，**不补发所补日期 daily 奖励**；里程碑奖励不重复（2b5 P2-5）
8. [签到:*] 三键加表名限定：`[签到:<表名>.<字段>]`（如 [签到:loop.连续天数]/[签到:monthly.本月天数]/[签到:activity.今日已签]；缺省表名=主表 loop）（2b5 P2-4）

## §1 公共基础（A1-A3，跨系统唯一实现，先于各系统落地）

### A1 统一 reward 解析器（dispatch_reward）
- 新文件 `qbot_rpg/core/reward.py`，单一入口 `dispatch_reward(entries, ctx) -> dict`（发放器唯一实现）
- 条目形态：`{item,count}`（入包，默认绑定）/ `coins`/`gem`（货币表，键空间=settings 货币键）/ `exp` 数值直入 / `rep`（入 reputation_state，**不入货币表**）
- 内联键值串 `"exp=50,coins=80,item:铁矿*3"` = 序列化糖，加载时等价展开为条目数组；存储与校验以结构化条目为准
- **失败策略（用户裁决）**：逐条目失败黄字跳过、不中断整批结算（物品不存在/数值非法→跳过该条）；任务完成结算的簿记（main_progress/移出/quest_daily）单事务原子
- 幂等：结算上下文携带 version/tx id，同一上下文重复调用不重复入账（防双发/防双扣）

### A2 统一条件引擎（eval_condition · 9 运算符 · 三原语 · 互译表）
- 扩展 `qbot_rpg/engine/weather_conditions.py`（M40 三键）为完整统一引擎，或新建 `qbot_rpg/engine/condition_engine.py`（推荐新建，weather_conditions 保持三键薄封装）
- 结构 `{var, op, value, param}`；9 运算符 gt/ge/lt/le/eq/ne/between/is/not + 符号双写 >= > <= < = != 归一；旧 {type,var,op,value} 的 type 忽略（var 归一），黄提示「旧格式，建议迁移」
- 三原语：值型（level/item_count 读当前值）/ 累计型（kill_count/gain_count 读 longline_counters）/ 事件型（var 前缀 `[事件:xxx]`，param=目标，读事件计数）
- 组合：any/all/not 嵌套递归求值（NPC 4.4）；任务条件 D-02 裁决「conditions 数组全与 + 支持 {all:[...]} 嵌套」
- var 键空间注册表：任务类/物品类/状态类/职业类/累计类/时间类/关系类/`[签到:<表名>.<字段>]`/事件类；中英文互译表（NPC §4.3 权威主表）
- 求值失败默认 False 不抛错（D-03 工程补白）

### A3 日界统一与懒计算（today_of）
- 新文件 `qbot_rpg/core/dayroll.py`，单一入口 `today_of(last_key, now=None) -> str`（重置时刻默认 05:00 可配，与 quest_daily/商店/签到共用配置键）
- 语义：重置时刻（默认 05:00 UTC+8）之后算新一天，凌晨 0-5 点归属前一天；惰性补刷（玩家操作时按时间差补算，不依赖定时器）；离线多天不丢不炸
- 跨周判定（结束 > 开始）、once 时间窗（未开门/自动下架）复用同一套周期工具

## §2 指令解析层（3c/3d/4f/5b）

### 2.1 解析管线（commands/parsers.py 实装）
- 顺序：快捷表 → 别名 → 白名单 → 忽略；分隔符五类：空格分参数、*连数量、,列列表、=键值、+等级、-连招、>路径；物品名禁空格
- 快捷指令三模式（command_mode 默认 global 免前缀"攻击2"）+ require_at 默认关；紧凑+空格双认
- 快捷绑定：个人别名上限 20，GM 禁绑（防权限绕过），冲突检测动态注册表；指令别名（世界观定制 keep_original 可选，显示层全替换）
- 会话路由：对话激活时纯数字/继续/退出/选择N 送状态机（跳过快捷表纯数字），带指令词照常解析；**战斗中裸数字 = 快捷表（用户裁决①）**
- ParsedCommand 形态：{raw, tokens, command, args, mode, ...}（对齐 3c §1）

### 2.2 消息模板（commands/sender.py + core/message_format/）
- 列表类 5 条/页上限；页脚固定 TPL-08「— 第 X/Y 页 · 共 N 条 · 输入 /指令 页码 翻页 —」禁止各系统自造页脚
- **页码越界：夹取最后一页 + 「已到最后一页」（用户裁决②）**；0/负数/非数字 → TPL-12 报错
- 错误模板统一 TPL-12/13/14（3d D-04 唯一文案源；4f/5b 不再自造三要素错误）
- emoji 纪律：装饰性禁用（✅/❌ 功能性保留）；数据型功能图标豁免（物品 icon/NPC 类型图标/recommended_newbie 角标/GM 结果前缀）
- 技能卡模板沿用 M2 定稿（LV 行固定头部 + LOL 式数值公式 + 派生指向）

### 2.3 基础指令组 + GM 指令（4f/5b）
- 基础指令组：/角色 /背包 /装备 /技能 /帮助 等（4f RUL-01~34，页码夹取口径）——【2026-08-27 M5 设计审查裁决①】属性面板指令名由 /查看 更名回定稿 /角色（用户拍板；VIEW_CMD="角色"）
- GM 指令：/gm 权限三级 + 静默 + 留痕 + 禁绑（5b）；GM 指令清单以分隔符规范 L160 长清单为准（+设置）
- /对话 可快捷绑定、不可免前缀直发（接缝裁决）

## §3 交互系统（路 2b 24 任务）

### 3.1 NPC/对话（B1-B6）
- 新文件 `qbot_rpg/content/npc_models.py`（NPCDef：14 顶层字段 + 子表）+ `qbot_rpg/core/npc.py`（发牌员三策略 rotate/random/condition + 10 类动作 quest/shop/heal/give_item/buff/repair/teleport/intel/tutorial/reply）+ `qbot_rpg/core/dialog.py`（会话状态机）
- 一次一物：信息类交付后置灰"已听"（落玩家存档 + 情报进图鉴可回看）；条件统一 {var,op,value,param}
- 会话路由：/对话 列表/序号/名称；对话树 ≤ max_dialog_depth（可配，0=不限）；退出词三词同义 + 菜单"N.离开"；菜单 ≤6 选项折叠
- 发牌员：dealer 牌池（rotate 轮转/condition 条件/random 随机三策略，用户裁决④）+ 不重复发已完成任务

### 3.2 商店（C1-C6）
- 新文件 `qbot_rpg/content/shop_models.py` + `qbot_rpg/core/shop.py`
- 五类型 normal/npc/reputation/event/blackmarket；stock 0=无限；sold_out_once 售出永久下架不随刷新恢复
- **库存 + 个人限购同条目并存**（用户裁决⑤）；个人限购清零以条目 period（day/week/month，默认每日 05:00）为准
- refresh 四模式 daily/weekly/once/none；**不配置 = 永不刷新**（用户裁决⑥）；刷新三件事（库存回满/限购清零/黑市重抽）同刻发生
- 原子防双扣：SQLite 事务 + 会话快照幂等；当前商店机制（地图级状态兜底商店中断恢复）
- /商店 /购买 /出售 + /商店 列表（补缺漏）

### 3.3 任务（D1-D5）
- 新文件 `qbot_rpg/content/quest_models.py` + `qbot_rpg/core/quest.py`
- 三原语引擎（值型/累计型/事件型）+ 统一 reward + 每日防刷（daily_limit≤10 / accept_limit≤5 / quest_daily / 完成即移出）+ 主线置顶（main:true 常驻）
- 任务板：/任务 接取 N / 交付 N（+任务信息/放弃）；双板仲裁（日常+主线）；main 沿用定稿 L138 命名
- 发放器失败策略统一：条目失败黄字跳过（见 A1）

### 3.4 签到（E1-E4）
- 新文件 `qbot_rpg/content/checkin_models.py` + `qbot_rpg/core/checkin.py`
- 多表（loop/monthly/activity）并存一次结算；连签独立计数（streak）+ 补签（默认关/两通道/月上限）
- **补签只计不补发**（用户裁决⑦）；里程碑不重复
- **[签到:<表名>.<字段>] 三键**（用户裁决⑧）：连续天数=指定表 streak / 本月天数=指定表当月 signed_days / 今日已签=指定表今日已签；缺省表名=主表 loop

## §4 批次派工单（8 批，每批 3 路并行，路间写不同文件）
- 批次 0 公共基础：A1 reward.py / A2 condition_engine.py / A3 dayroll.py
- 批次 1 指令解析：parsers.py 实装 / sender.py+模板 / router.py 会话路由
- 批次 2 NPC：npc_models.py / core/npc.py 发牌员 / core/dialog.py 会话
- 批次 3 商店：shop_models.py / core/shop.py 引擎 / shop 指令接线
- 批次 4 任务：quest_models.py / core/quest.py 引擎 / quest 指令接线
- 批次 5 签到：checkin_models.py / core/checkin.py 引擎 / checkin 指令接线
- 批次 6 指令组：4f 基础指令组实装 / 5b GM 指令 / 校验器+manifest 注册
- 批次 7 集成：端到端冒烟 / verify_m4 / 回归

## §5 完成判据
- verify_m4（TC 矩阵随实现补充）+ run_all_tests 全绿（四门禁 + M4 门禁）
- 端到端：NPC 对话 → 商店购买 → 任务接取/交付 → 签到，全链路冒烟
- 设计审查 P 项（P1×12/P2×24 除已拍板项）实现时顺手修
