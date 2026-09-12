"""
模板分区：battle_tpl（战斗指令（battle_commands）+ 战斗消息渲染（battle_render）；
2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 battle_commands.py（6 TPL 常量 + 6 f-string）与
battle_render.py（BREP-01~25 输出模板）的逐字文案迁移，默认值改动会导致现有测试断言
失效——需与 battle_commands / battle_render 渲染处 tpl_of(ctx, "battle_*", {...})
一致。

key 命名：battle_<用途>。占位符白名单：每类模板允许的占位符；超出白名单渲染时原样
保留（提示缺失）。渲染零 emoji（仅 ✅/❌ 功能性标记 + 「」排版符，D-5B）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— battle_commands 壳层（6 TPL 常量 + 6 f-string 迁移）——
    # 2026-09-12 消息模板重构·批4 路J：战斗目标面板 + 基础交互 16 键已迁全量模板表
    # （qbot_rpg/core/templates/template_table.json，fragment b4j）——
    # battle_no_battle / battle_target_no_battle / battle_target_head / battle_target_hp /
    # battle_target_attr / battle_target_marks / battle_target_status / battle_target_weak /
    # battle_no_skill / battle_no_item_arg / battle_no_item / battle_flee_ok /
    # battle_flee_failed / battle_item_used / battle_no_battle_map_monster（15 键入表）；
    # battle_target_tail 全仓零引用 → 死键清除（不迁入表）。
    # 【旧占位说明】目标面板原约定「掉落不显示」（框架 7.6 L1356/L1367）现由
    # battle_commands.cmd_battle_target 保证：面板只为 enemy_def 白名单字段生成行，
    # 「查看目标不显示掉落」的旧尾注模板随死键一并清除。

    # —— BREP-23 战斗开始 ——

    # —— CTB 重写（Agent 5 · DataRender）：单次行动 / 批量 NPC 行动 / 玩家 ready ——
    # 依据 docs/ctb/01_asset_inventory.md §0.2 事件位点词典（ACTOR_READY / ACTOR_TURN_START）+
    # docs/ctb/02_wave_a_decisions.md 裁决口径。CTB 无「回合」概念，状态行以逻辑时间计。
    # 批次时间头（2026-09-11 增补 v1 调整显示词）：隐性标准——玩家文案不暴露行动条
    # 原始数值；原「（行动时间 {start} → {end}）」与技能「行动时间」撞名，退役。

    # —— TPL-09 16 行折叠（战斗轮 / 明细块）——

    # —— BREP-24 战斗结束汇总行 / BREP-15 击杀 / BREP-20 经验掉落 /
    #    用户结算模板（经验·金币·战利品·升级）/ BREP-16~19 lose·draw /
    #    BREP-22 连段结算备注 / BREP-25 木桩明细 ——
    # 2026-09-12 消息模板重构·批6 路P：结算与奖励 24 键已迁全量模板表
    # （qbot_rpg/core/templates/template_table.json，fragment b6p）——
    # battle_kill_line / battle_reward_line / battle_reward_exp / battle_reward_gold /
    # battle_reward_drop / battle_settle_win_narrative_fallback / battle_settle_exp /
    # battle_settle_gold / battle_settle_loot_header / battle_settle_loot_item /
    # battle_settle_levelup(+_multi/_sp) / battle_settle_lose(+_fail) /
    # battle_settle_draw / battle_end_summary / battle_combo_settle(+_suffix) /
    # battle_combo_remark_boss / battle_combo_remark_waste /
    # battle_summary_header / battle_summary_item（23 键入表）；
    # battle_settle_win_narrative 全仓零引用（2026-09-09 击杀去重后叙事句整行摘除，
    # 无动态拼接构造）→ 死键清除（不迁入表，test_demo 同 key 移除）。
    # 【口径】结算块保持「经验/金币/战利品/升级」逐行结构（不再含单行叙事句）；
    # battle_end_summary 免斜杠（发 战斗记录）；连段备注与摘要行按「少｜多换行」拆行。
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    # —— battle_commands 壳层 ——
    # 2026-09-12 批4 路J：本批 15 键已迁全量模板表，白名单由 __init__ 自动派生
    # （表内文本占位符 = {name}/{round}/{hp}/{max_hp}/{attr_name}/{value}/{marks}/
    # {statuses}/{weak}/{item_name}）；battle_target_tail 死键清除。

    # —— battle_render ——
    # 2026-09-12 批5 路M：敌方行动与状态机制 27 键已迁全量模板表，白名单由 __init__
    # 自动派生（表内文本占位符 = {name}/{action}/{damage}/{pos}/{actor}/{skill}/
    # {part}/{shield}/{n}/{target}/{effect}/{change}）。
    # —— battle_render 结算与奖励（批6 路P）——
    # 2026-09-12 批6 路P：结算与奖励 23 键已迁全量模板表，白名单由 __init__ 自动派生
    # （表内文本占位符 = {target}/{items}/{exp}/{currency}/{gold}/{name}/{count}/
    # {enemy}/{index}/{level}/{level_ups}/{sp}/{label}/{turns}/{total}/{remark}/
    # {max_hit}/{crits}/{blocks}/{source}/{damage}/{pct}）；
    # battle_settle_win_narrative 死键清除（零引用，白名单同步删除）。
}
