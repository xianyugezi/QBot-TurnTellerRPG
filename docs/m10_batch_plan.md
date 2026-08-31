# M10 钓鱼 · 批次派工单（7 批 + 收口）

> 生成：2026-08-31 · 依据：docs/m10_启动包.md §五（7 批建议）+ 用户拍板「每批 2-3 路并行 + 批间收口」
> 批次节奏铁律（M9 实测）：每批返回 → 主 agent 收口（lint 门禁 + 回归 + G0 + 提交）→ 再派下一批，不叠批；scnet 并发 ≤3 路（稳妥 2 路）；每路子任务单文件 ≤~40KB / 测试 ≤40 例

## 批次总览

| 批 | 内容 | 路数 | 依据细化/定稿 |
|---|---|---|---|
| 批0 | 数据与配置（fishing 段 / fishing.json+CSV / 校验器） | 3 | 2c1a |
| 批1 | 鱼饵体系 + 流程状态机核心 | 2 | 2c1b |
| 批2 | /钓鱼 钓点列举 / 抛竿+鱼讯 / /鱼讯+/收杆 三选一 | 3 | 2c1b |
| 批3 | 出鱼结算 / 冠级六档 / 纯收藏差分 | 3 | 2c1a/2c1b |
| 批4 | codex 鱼册+冠级标注 / 鱼王事件 | 2 | 2c1a/2c1c |
| 批5 | 熟练度+钓鱼王 / mode 路由 / 四出口闭环 | 3 | 2c1c |
| 批6 | 模板配置化+指令注册 / verify_m10_smoke | 2 | 2c1b/5d |
| 批7 | 编辑器服务层预留 | 1 | 定稿 §五 |
| 批8 | 收口（全仓回归 + dsh 审查 + 部署实机） | 2 | — |

## 逐批派工单

### 批0 · 数据与配置（3 路并行 · 已派）
详见 docs/m10_shared_contract.md（接口权威）。
- 路0A settings.fishing 段 + 加载容错（T01）→ fishing_settings.py + test
- 路0B fishing.json 鱼种 + CSV 双向（T02）→ fishing_csv.py + fixtures
- 路0C 校验器 V1-V4+W1（T03）→ fishing_models.py + loader/field_meta 登记

### 批1 · 鱼饵 + 状态机（2 路）
- **路1A 鱼饵体系（T04）**：5 档通用饵 + 定向饵（炼金 recipe 引用）+ 无饵保底不卡死；`qbot_rpg/core/fishing_bait.py`（bait_lookup / is_preferred_bait / consume_bait 薄委托 + 对口饵加成读取 settings.fishing.bait_bonus）+ items.json/recipe.json 补饵条目（路0B 已建 fishing.json，饵条目落 items/recipe 各自文件）
- **路1B 流程状态机核心（T06 前半）**：`qbot_rpg/core/fishing.py`（FishingEngine：start_fishing 扣饵+日计数+懒计时注册 / bite_check 到期懒判+鱼讯三类生成 / reel_in 收杆三选一入口 / fish_state 持久化 _ps_init 挂 ps / TR-01~11 迁移 + GU-01~04 守卫）；鱼讯意图复用「rarity 直接映射」语义（normal→微动/rare→拉扯/gold→猛烈+金闪覆写）

### 批2 · 流程指令（3 路 · 最高优先）
- **路2A /钓鱼 钓点列举（T05）**：垂钓点=采集点变体（时段+稀有度标记）；/钓鱼 列出 + 鱼讯参考说明（微动=小鱼 / 拉扯=中鱼 / 猛烈=大鱼或鱼王）+ 空态 + off 拒绝（GU-01）
- **路2B 抛竿 + 鱼讯（T06 后半/T07）**：扣饵 + 懒计算等待 + 每日计数（fish_state.today/casts 对齐 dayroll）；鱼讯三类生成 + 金闪标记（king 命中时）
- **路2C /鱼讯 + /收杆 三选一（T08/T09）**：状态查询（等待中/已触发/空闲）；满力（升级 roll）/自动（基础 70/25/5）/止损（不 roll）；种子化 roll（42/2026 复现 54/37/9 与 70/25/5）；decision window carry_sec 90（0=不限）超时跑鱼 TR-07

### 批3 · 出鱼结算 + 冠级（3 路）
- **路3A 出鱼结算（T10）**：鱼种×大小×重量×冠级 → 图鉴点亮 + 熟练经验 + 奖励（reward 发放器一条调用）；结算记录含 size/weight/crown
- **路3B 冠级百分位生成与六档判定（T11）**：crown_of 纯函数（阈值可配、判定顺序写死、边界 4.9/5.0 84.9/85.0 94.9/95.0）+ gen_size_weight 线性插值
- **路3C 冠级纯收藏约束（T12）**：差分测试（同鱼同尺寸不同冠级 → 价值/经验/售价全同，差分=0）

### 批4 · 图鉴 + 鱼王（2 路）
- **路4A codex 鱼册 + 冠级标注（T13/T14）**：codex CATEGORIES 加 fish 分册 + fish_codex_update（防 mark_seen 覆盖）+ /图鉴 fish 特判渲染（render_fish_codex，冠级标注，不写判定公式）
- **路4B 鱼王事件（T15）**：金闪鱼讯 → 鱼王 BOSS 战（enemies 引用，复用 BOSS 引擎入口）+ 每日窗口 2 + 30% 概率 + king_trigger/victory 两把计数 + 胜利计次

### 批5 · 职业 + 开关 + 经济（3 路）
- **路5A 钓鱼职业熟练度 + 钓鱼王（T16）**：proficiency.json 加 fishing 实例（M9 计数断言坑）+ grant_fishing_exp（source=gather）+ fish_king_eligible 图鉴补全授予（全鱼种 caught≥1 ∧ king_victory≥2）+ title_state + MC 332 竿中位
- **路5B mode 三态路由（T17）**：full/simple/off 行为矩阵（simple=/钓鱼 直接出鱼无等待/鱼讯/鱼王；off 全拒绝）
- **路5C 经济四出口闭环（T18）**：商店出售（无冠级加成）/ 委托交付 / 品评投稿 / 炼金饵料回链；种子化日经济 ≈256 金

### 批6 · 收尾（2 路）
- **路6A 模板配置化 + 指令注册**：fishing_tpl.py 分区 + templates/__init__ 登记 + /钓鱼 /收杆 /鱼讯 路由注册 + 白名单（沿用 M9 铁律）
- **路6B 全链路冒烟 verify_m10_smoke**：钓点→抛竿→等待→鱼讯→收杆→出鱼→图鉴→钓鱼王

### 批7 · 编辑器服务层（1 路，M12 协同）
- **路7A 编辑器数据接口预留（T19）**：钓鱼卡片字段 / 鱼种 CSV 导入导出 / 冠级阈值表单 / 图鉴模拟（服务端函数，UI 归 M12）

### 批8 · 收口（2 路）
- **路8A**：全仓回归 + emoji 门禁 + G0 架构检查 + verify_m10 各批脚本 + run_all_tests 注册
- **路8B**：dsh 审查（分步 ≤5 文件/批，沿用 M8/M9 模式）→ 汇报用户 → 部署实机