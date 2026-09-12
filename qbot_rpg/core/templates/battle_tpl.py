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
    "battle_no_battle": "❌ 当前没有进行中的战斗",
    # —— /查看目标（框架 7.6 L1356/L1367：目标属性面板，掉落不显示）——
    "battle_target_no_battle": "❌ 当前没有进行中的战斗（/锁定 1 开战后可查看目标）",
    "battle_target_head": "【目标】{name}（第 {round} 行动）",
    "battle_target_hp": "【生命】{hp}/{max_hp}",
    "battle_target_attr": "【{attr_name}】{value}",
    "battle_target_marks": "【印记】{marks}",
    "battle_target_status": "【状态】{statuses}",
    "battle_target_weak": "【弱点】{weak}",
    "battle_target_tail": "查看目标不显示掉落（击破后见战报）",
    "battle_no_skill": "❌ 没有这个技能",
    "battle_no_item_arg": "❌ 请指定要使用的道具（/道具 药水）",
    "battle_no_item": "❌ 没有这个道具",
    "battle_flee_ok": "✅ 逃跑成功，脱离战斗",
    "battle_flee_failed": "❌ 逃跑失败，战斗继续",
    # 道具使用行（P2-4 补白合成文案）
    "battle_item_used": "✅ 你使用了{item_name}",
    # 参数为当前地图怪物名 → 开战引导（P2-3；2026-09-04：锁定已实装，
    # 陈旧「开战功能尚未实装」误导 → 引导 /锁定 怪物名 开战）
    "battle_no_battle_map_monster": "❌ 当前没有进行中的战斗。可用 锁定 <怪物名> 开战；"
                                    "进入战斗后使用 攻击 <技能序号或名称> 发动技能。",
    # 指令返回 message 元数据（非发送正文，逐字迁移）
    "battle_result_end": "战斗结束（{status}）",
    # CTB 口径（收口 2026-09-10）：{turn} 槽位承载 `action_seq`（已结算行动数）——
    # CTB 无「回合」概念，玩家可见文案统一改「第 N 行动」。
    "battle_result_round": "第 {turn} 行动结算",

    # —— BREP-23 战斗开始 ——
    "battle_start_line": "与{name}的战斗开始！{name} {hp}/{max_hp}",

    # —— CTB 重写（Agent 5 · DataRender）：单次行动 / 批量 NPC 行动 / 玩家 ready ——
    # 依据 docs/ctb/01_asset_inventory.md §0.2 事件位点词典（ACTOR_READY / ACTOR_TURN_START）+
    # docs/ctb/02_wave_a_decisions.md 裁决口径。CTB 无「回合」概念，状态行以逻辑时间计。
    "battle_ctb_ready": "轮到你行动了",
    "battle_ctb_status": "距离你下次行动：{n}",
    "battle_ctb_turn_start": "轮到 {actor} 行动",
    # 批次时间头（2026-09-11 增补 v1 调整显示词）：隐性标准——玩家文案不暴露行动条
    # 原始数值；原「（行动时间 {start} → {end}）」与技能「行动时间」撞名，退役。
    "battle_ctb_batch_head": "（怪物行动）",

    # —— TPL-09 16 行折叠（战斗轮 / 明细块）——
    "battle_fold_lines": "…（其余 {n} 行已折叠）",
    "battle_fold_items": "…（其余 {n} 条已折叠，输入 /{command} {page} 查看）",

    # —— BREP-24 战斗结束汇总行 ——
    "battle_end_summary": "战斗结束：{label}｜行动数 {turns}｜输入 /战斗记录 查看明细",

    # —— BREP-07 技能释放（resource_text 空省略括号）——
    "battle_skill_cast": "✅ 你施放{skill_name}：{effect_desc}",
    "battle_skill_cast_suffix": "（{resource_text}）",
    "battle_resource_cur_max": "{label} {cur}/{max}",

    # —— BREP-08 状态资源差分行（D-5D 只显变化轴；L509 前 5 个）——
    "battle_status_diff_item": "{label} {old}→{new}",
    "battle_status_diff_more": " ｜ 还有 {rest} 个状态",

    # —— BREP-09 操作提示行（战报末行；tail 独立模板）——
    "battle_action_hint": "你 {player_hp}/{player_max_hp}{player_pos} | {target_name} "
                          "{target_hp}/{target_max_hp}{target_pos} → {tail}",
    "battle_action_hint_tail": "攻击 或 攻击 技能名",

    # —— BREP-04 会心/格挡附注 ——
    "battle_crit_note": "（会心·{tier} ×{mult}）",
    "battle_blocked_note": "（被格挡，伤害减半）",
    # 背击附注（B5 背击闭环，批④）：只露行为不露倍率（软提示口径）
    "battle_backstab_note": "（背击）",

    # —— BREP-02/03/05/06 玩家行动 ——
    "battle_player_hit": "✅ 你{action}，造成 {damage} 伤害{note}（{target} {hp}/{max_hp}）",
    "battle_player_miss": "❌ 未命中：{target} 闪过了你的{action}（{target} {hp}/{max_hp}）",
    "battle_player_defend": "✅ 你进入防御姿态（本次行动受到伤害减半）",
    "battle_player_defend_hit": "✅ 你防御了{attacker}的{action}，"
                               "受到 {damage} 伤害（HP {hp}/{max_hp}）",

    # —— BREP-10~14 怪物行动 ——
    "battle_enemy_hit": "❌ {name}{action}，你受到 {damage} 伤害（HP {hp}/{max_hp}）",
    "battle_enemy_miss": "✅ {name}的攻击被你躲开（HP {hp}/{max_hp}）",
    # 方位 miss（方位 v0.6 §四/附录 A Step 1：未命中——怪物行动打不到玩家当前方位）
    "battle_enemy_position_miss": "✅ 未命中：{name}的攻击未能命中{pos}的你（HP {hp}/{max_hp}）",
"battle_actor_landed": "{actor} 从空中落回地面",
# 被击落行（跃空风险闭环，批③：对空必杀命中空中玩家——纯行为播报，零数值）
"battle_air_dropped": "{name}将你从空中击落——你重重摔落在地",
# 受身行（跃空续航批⑨：被击落时翔虫受身——纯行为播报，零数值）
"battle_air_recover": "{name}将你从空中击落——你借翔虫之力翻身，稳稳落地",
# 转向行（增补 v1 §三 转向事件化：怪在玩家行动前转回面向——纯行为播报，零数值）
"battle_enemy_turned": "{name}转过身来，盯住了你",
"battle_position_changed": "{actor} 移动到了{pos}",
"battle_part_broken": "{part}被击碎！{name}轰然倒地",
"battle_part_broken_no_knock": "{part}被击碎，{name}仍稳立当场",
# 气绝 KO / 咆哮（批⑦A #2/#3）：纯行为播报、零数值
"battle_stun_hint": "（{name}的步幅一滞，气息开始散乱……）",
"battle_stun_ko": "{name}颅腔嗡鸣，四肢一软伏倒在地——【气绝】",
"battle_roar": "{name}仰天咆哮，声浪碾过旷野——你被震得踉跄后退（连势震散）",
"battle_roar_plain": "{name}仰天咆哮，声浪碾过旷野——你被震得踉跄后退",
"battle_roar_blocked": "{name}仰天咆哮——轰鸣掠过，你的耳栓滤去声浪，身形纹丝未动",
# 怒·三态 / 疲劳（批⑦B #4/#5）：纯行为播报、零数值
"battle_state_enraged": "{name}的脉息陡然暴涨——它被激怒了！",
"battle_state_fatigued": "{name}的喘息粗重起来，动作明显迟滞了",
"battle_state_recovered": "{name}重新稳住了呼吸",
"battle_fatigue_stagger": "{name}腿下一软，这一击失了准头",
    "battle_enemy_intent": "{name} 蓄力中（下次行动发动「{skill}」）",
    "battle_enemy_special": "{name} {action}",
    "battle_enemy_special_suffix": "（{change}）",
    "battle_intercept_absorb": "{shield} 吸收了 {n} 点伤害",
    "battle_intercept_reflect": "反弹 {n} 伤害给{target}",
    # 2026-09-09 防反/闪反（用户拍板标签制）：格挡免伤行 + 反击行
    "battle_parry_success": "✅ 你格挡了{action}（完全免伤）",
    "battle_counter_hit": "反击：{name}造成 {damage} 伤害",
    "battle_intercept_immune": "免疫了{effect}",

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
    "battle_combo_seg": "第 {seg} 段：{action} 造成 {damage} 伤害{note}"
                        "（{target} {hp}/{max_hp}）",
    "battle_derived_cap": "（派生倍率已达上限 1.5×）",

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
    "battle_no_battle": set(),
    "battle_target_no_battle": set(),
    "battle_target_head": {"name", "round"},
    "battle_target_hp": {"hp", "max_hp"},
    "battle_target_attr": {"attr_name", "value"},
    "battle_target_marks": {"marks"},
    "battle_target_status": {"statuses"},
    "battle_target_weak": {"weak"},
    "battle_target_tail": set(),
    "battle_no_skill": set(),
    "battle_no_item_arg": set(),
    "battle_no_item": set(),
    "battle_flee_ok": set(),
    "battle_flee_failed": set(),
    "battle_item_used": {"item_name"},
    "battle_no_battle_map_monster": set(),
    "battle_result_end": {"status"},
    "battle_result_round": {"turn"},

    # —— battle_render ——
    "battle_start_line": {"name", "hp", "max_hp"},
    # CTB 三入口模板（Agent 5 · DataRender）
    "battle_ctb_ready": set(),
    "battle_ctb_status": {"n"},
    "battle_ctb_turn_start": {"actor"},
    "battle_ctb_batch_head": set(),
    "battle_fold_lines": {"n"},
    "battle_fold_items": {"n", "command", "page"},
    "battle_end_summary": {"label", "turns"},
    "battle_skill_cast": {"skill_name", "effect_desc"},
    "battle_skill_cast_suffix": {"resource_text"},
    "battle_resource_cur_max": {"label", "cur", "max"},
    "battle_status_diff_item": {"label", "old", "new"},
    "battle_status_diff_more": {"rest"},
    "battle_action_hint": {"player_hp", "player_max_hp", "target_name",
                           "target_hp", "target_max_hp", "tail"},
    "battle_action_hint_tail": set(),
    "battle_crit_note": {"tier", "mult"},
    "battle_blocked_note": set(),
    "battle_backstab_note": set(),
    "battle_player_hit": {"action", "damage", "note", "target", "hp", "max_hp"},
    "battle_player_miss": {"target", "action", "hp", "max_hp"},
    "battle_player_defend": set(),
    "battle_player_defend_hit": {"attacker", "action", "damage", "hp", "max_hp"},
    "battle_enemy_hit": {"name", "action", "damage", "hp", "max_hp"},
    "battle_enemy_miss": {"name", "hp", "max_hp"},
    "battle_enemy_position_miss": {"name", "pos", "hp", "max_hp"},
"battle_actor_landed": {"actor"},
"battle_air_dropped": {"name"},
"battle_air_recover": {"name"},
"battle_enemy_turned": {"name"},
"battle_position_changed": {"actor", "pos"},
"battle_part_broken": {"part", "name"},
"battle_part_broken_no_knock": {"part", "name"},
"battle_stun_hint": {"name"},
"battle_stun_ko": {"name"},
"battle_roar": {"name"},
"battle_roar_plain": {"name"},
"battle_roar_blocked": {"name"},
"battle_state_enraged": {"name"},
"battle_state_fatigued": {"name"},
"battle_state_recovered": {"name"},
"battle_fatigue_stagger": {"name"},
    "battle_enemy_intent": {"name", "skill"},
    "battle_enemy_special": {"name", "action"},
    "battle_enemy_special_suffix": {"change"},
    "battle_intercept_absorb": {"shield", "n"},
    "battle_intercept_reflect": {"n", "target"},
    "battle_intercept_immune": {"effect"},
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
    "battle_combo_seg": {"seg", "action", "damage", "note", "target", "hp", "max_hp"},
    "battle_derived_cap": set(),
    "battle_combo_settle": {"total"},
    "battle_combo_settle_suffix": {"remark"},
    "battle_combo_remark_boss": set(),
    "battle_combo_remark_waste": set(),
    "battle_summary_header": {"total", "max_hit", "crits", "blocks"},
    "battle_summary_item": {"index", "source", "damage", "pct"},
}
