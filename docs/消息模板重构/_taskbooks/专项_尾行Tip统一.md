# 任务书 · 专项·跨模块尾行 Tip 统一（免斜杠 + 表驱动）

> 2026-09-12 · 消息模板重构战役 · 执行者：子 agent（本任务书 + `docs/消息模板重构/00_方案与规范_v1.md` 为唯一指令源）
> 背景：全量表已收口（713→706 键），但**各指令模块的尾行 Tip 仍是 py 常量 + 旧式「发送'…'」写法**
> （带单引号、带「发送」字样，与全表免斜杠口径不一致）。本批统一：进表 + 免斜杠。

## 1. 范围（逐处处理）

**A. `qbot_rpg/commands/basic_commands.py`（L823-833 一带的 Tip 常量 + 调用点）**
`_BAG_TAIL_TIP` / `_VIEW_TAIL_TIP` / `_EQUIP_TAIL_TIP` / `_SKILL_TAIL_TIP` / `_HELP_TAIL_TIP` /
`_HELP_DIR_TAIL_TIP` / `_HELP_GROUP_TAIL_TIP` / L932 `_tip_pool`（2 条）/ L2347 `_dir_tip` / L1413 `f"Tip:{...}"`

**B. `qbot_rpg/commands/checkin_commands.py` L138 `_TAIL_TIP`**

**C. `qbot_rpg/commands/quest_commands.py` L141 `_BOARD_TAIL_TIP`**

**D. `qbot_rpg/core/shop.py` L1058 `"tip": "发送'购买+物品名'即可购买商品"`**

**E. `qbot_rpg/core/templates/base.py`**：`help_tail` / `bag_tail` / `shop_tail`（值里仍是「发送'…'」旧式）+
`list_tail`（若需把 `Tip:` 前缀也表驱动）

## 2. 达标口径

- 全部尾行 Tip 文案 → **全量表键**（命名成体系，如 `tip_bag` / `tip_view` / `tip_equip` / `tip_skill` /
  `tip_help_dir` / `tip_help_group` / `tip_checkin` / `tip_quest_board` / `tip_shop` …），
  `content/test_demo/templates.json` 同步；命令模块里**不再留文案常量**（只留 key 名或直接 tpl_of）。
- **免斜杠**写法统一为「发 <指令> <参数>」（示例：`发 技能 2 翻页` / `发 任务 领取 <序号>` /
  `发 帮助 2` / `发 签到 补签` / `发 使用 <序号>`）；去掉单引号与「发送」字样。
- **行宽**：`Tip:` 前缀后 ≤28 半角（`list_render` 的 `Tip:` 拼接口径）；超宽改词或拆行。
- 既有测试同步（这些 Tip 有逐字断言）；**不得**为过测试改回旧文案。

## 3. 工作清单
1. 先落 fragment：`docs/消息模板重构/_fragments/spec_tip.json` → commit。
2. 合表：`python3 scripts/tpl_merge_fragments.py docs/消息模板重构/_fragments/spec_tip.json`
3. 改代码：上述模块常量 → 表键调用；内容包同步。
4. 自校验：checker（0 FAIL）+ `test_template_table` + `test_template_table_final` + `test_emoji_discipline`
   + 定向（basic/checkin/quest/shop 相关）+ 全量 `pytest tests/ -q -o addopts=""`（报计数）。
5. `ruff check <改动文件>` 干净；commit。**禁止 push / 禁止动 main**。

## 4. 报告（回复正文内联）
fragment 路径 + 新键文案 JSON 全量；「旧常量（文件:行）→ 新表键 → 新文案」对照表；改动文件清单；
checker 输出；定向+全量计数原文；未完成/存疑；commit hash。
