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

    # —— BREP-24 战斗结束汇总行 ——
    "battle_end_summary": "战斗结束：{label}｜行动数 {turns}｜输入 /战斗记录 查看明细",

    # —— BREP-07 技能释放（resource_text 空省略括号）——

    # —— BREP-08 状态资源差分行（D-5D 只显变化轴；L509 前 5 个）——

    # —— BREP-09 操作提示行（战报末行；tail 独立模板）——

    # —— BREP-04 会心/格挡附注 ——
    # 背击附注（B5 背击闭环，批④）：只露行为不露倍率（软提示口径）

    # —— BREP-02/03/05/06 玩家行动 ——

    # —— BREP-10~14 怪物行动 ——
    # 2026-09-12 消息模板重构·批5 路M：敌方行动与状态机制 27 键已迁全量模板表
    # （qbot_rpg/core/templates/template_table.json，fragment b5m）——
    # battle_enemy_hit / battle_enemy_miss / battle_enemy_position_miss /
    # battle_actor_landed / battle_air_dropped / battle_air_recover /
    # battle_enemy_turned / battle_position_changed / battle_part_broken(+_no_knock) /
    # battle_stun_hint / battle_stun_ko / battle_roar(+_plain/_blocked) /
    # battle_state_enraged / battle_state_fatigued / battle_state_recovered /
    # battle_fatigue_stagger / battle_enemy_intent / battle_enemy_special(+_suffix) /
    # battle_intercept_absorb / battle_intercept_reflect / battle_intercept_immune /
    # battle_parry_success / battle_counter_hit。
    # 【口径】受击/未命中行不重复血量（HP 括注已去，血量只在 HUD 两行，批4 拍板）；
    # 方位格入模板包裹【{pos}】（_position_cn 恒返回非空方位，不产生空【】）。

    # —— BREP-15 击杀行 ——
    "battle_kill_line": "✅ 你击败了{target}！",

    # —— BREP-20 经验与掉落行（items 已按 、 拼接）——
    "battle_reward_line": "✅ 获得 {items}",
    "battle_reward_exp": "经验 {exp}",
    "battle_reward_gold": "{currency} {gold}",
    "battle_reward_drop": "{name}×{count}",

    # —— 用户结算模板（2026-08-27 拍板；win 叙事句 + 经验/金币分行 + 战利品列表）——
    "battle_settle_win_narrative": "您对{enemy}造成了{dmg}点伤害！{enemy}已死亡。",
    "battle_settle_win_narrative_fallback": "您击败了{enemy}！",
    "battle_settle_exp": "获得经验：{exp}",
    "battle_settle_gold": "获得{currency}：{gold}",
    "battle_settle_loot_header": "获得的战利品如下→",
    "battle_settle_loot_item": "{index}.{name}×{count}",
    # —— 战斗升级行（2026-09-03 奖励结算：击杀奖励经验触发升级时附一行）——
    # 默认文案合并各段（升级提示一行内，避免占多条消息；level 为升级后等级）
    "battle_settle_levelup": "✅ 等级提升至 {level}！HP/MP 已回复",
    "battle_settle_levelup_multi": "✅ 等级提升至 {level}（连升 {level_ups} 级）！HP/MP 已回复",
    "battle_settle_levelup_sp": " 技能点 +{sp}",

    # —— BREP-16/18/19 lose / draw 结算 ——
    "battle_settle_lose": "❌ 你倒下了…",
    "battle_settle_lose_fail": "❌ 战斗失败：你被{enemy}击败了",
    "battle_settle_draw": "双方同归于尽，战斗以平局结束",

    # —— BREP-21 连段段行 + 派生封顶附注（L133）——

    # —— BREP-22 连段结算行（remark 空省略括号）+ 备注文案 ——
    "battle_combo_settle": "连段 {total} 段已结算",
    "battle_combo_settle_suffix": "（{remark}）",
    "battle_combo_remark_boss": "BOSS 已倒下，战斗结束，后续段数作废",
    "battle_combo_remark_waste": "目标已倒下，该段连式为无效消耗",

    # —— BREP-25 木桩明细（摘要行 + 条目行）——
    "battle_summary_header": "摘要：总伤害 {total}｜最大单段 {max_hit}｜会心 {crits} 次"
                             "｜格挡 {blocks} 次",
    "battle_summary_item": "{index}. {source} {damage}（{pct}%）",
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
    # CTB 三入口模板（Agent 5 · DataRender）
    "battle_end_summary": {"label", "turns"},
    "battle_kill_line": {"target"},
    "battle_reward_line": {"items"},
    "battle_reward_exp": {"exp"},
    "battle_reward_gold": {"currency", "gold"},
    "battle_reward_drop": {"name", "count"},
    "battle_settle_win_narrative": {"enemy", "dmg"},
    "battle_settle_win_narrative_fallback": {"enemy"},
    "battle_settle_exp": {"exp"},
    "battle_settle_gold": {"currency", "gold"},
    "battle_settle_loot_header": set(),
    "battle_settle_loot_item": {"index", "name", "count"},
    "battle_settle_levelup": {"level"},
    "battle_settle_levelup_multi": {"level", "level_ups"},
    "battle_settle_levelup_sp": {"sp"},
    "battle_settle_lose": set(),
    "battle_settle_lose_fail": {"enemy"},
    "battle_settle_draw": set(),
    "battle_combo_settle": {"total"},
    "battle_combo_settle_suffix": {"remark"},
    "battle_combo_remark_boss": set(),
    "battle_combo_remark_waste": set(),
    "battle_summary_header": {"total", "max_hit", "crits", "blocks"},
    "battle_summary_item": {"index", "source", "damage", "pct"},
}
