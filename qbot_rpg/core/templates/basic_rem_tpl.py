"""
模板分区：basic_rem（基础指令剩余：装备/技能/货币等；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 basic_commands.py 的逐字文案迁移（RUL-08 注册门槛 /
空背包 / 装备栏 / 装备穿卸适配器消息 / 技能行与头 / 货币行 / 物品品质·绑定后缀 / 背包筛选 /
帮助注册引导与组页头），默认值改动会导致现有测试断言失效——需与 basic_commands 渲染处
tpl_of(ctx, "basic_*", {...}) 一致。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— RUL-08 注册门槛（对齐 register_commands / explore / investigate 本地门）——
    "basic_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",

    # —— /背包 空背包（4f §3.4）——
    "basic_empty_bag": "❌ 背包空空如也",

    # —— /背包 物品行品质·绑定后缀（RUL-19：仅非 normal 标注品质；绑定标注）——
    "basic_quality_suffix": "（{quality}）",
    "basic_bound_suffix": "（绑定）",

    # —— /背包 货币行（用户模板 `金币：0` / `钻石：0`）——
    "basic_currency_row": "{name}：{value}",

    # —— /背包筛选（框架 §7.4）——
    "basic_filter_hint": "❌ 背包筛选：输入物品类型（装备/药剂/货币袋/材料/技能书/任务）"
                             "，如「背包筛选装备」",
    "basic_filter_unknown": "❌ 没有「{word}」这个物品类型"
                             "（装备/药剂/货币袋/材料/技能书/任务）",

    # —— /装备 槽位 / 名称形式（值域文案，命令合法，不走 TPL-12）——
    "basic_no_slot": "❌ 没有这个装备槽位",
    "basic_equip_name_hint": "❌ 装备指令：请用 /装备 穿 <序号> 穿戴"
                             "（序号见 /背包），如 /装备 穿 3",

    # —— /装备 装备栏（意见一同步：去序号 + 头部 + 强化后缀）——
    "basic_equip_header": "【装备】",
    "basic_equip_line": "{slot}：{name}",
    "basic_equip_enh": " +{enhance}",

    # —— /装备 穿/卸 适配器消息（EquipmentEngineAdapter / EQP-E1~E5 边界文案）——
    "basic_equip_no_player": "❌ 玩家状态缺失（请先 /注册 创建角色）",
    "basic_equip_no_item": "❌ 背包里没有这件物品",
    "basic_equip_not_equippable": "❌ 这件物品不能装备",
    "basic_equip_no_slot": "❌ 这件物品不能装备（未登记装备槽位）",
    "basic_equip_ok": "✅ 已装备：{name}",
    "basic_equip_replaced": "（已替换原装备并回包）",
    "basic_equip_remove_ok": "✅ 已卸下：{name}",
    "basic_equip_fail": "❌ {msg}",
    "basic_equip_fail_wear": "装备失败",
    "basic_equip_fail_remove": "卸下失败",
    "basic_equip_wear_fail": "❌ 装备失败",
    "basic_equip_remove_fail": "❌ 卸下失败",
    "basic_equip_reason_slot_mismatch": "这个位置穿不上",
    "basic_equip_reason_mutual_exclusion": "装备冲突：与已穿装备互斥，无法同时穿戴",
    "basic_equip_reason_empty_slot": "该槽位没有装备",
    "basic_equip_reason_in_battle": "战斗中不可更换装备（战前换装）",
    "basic_equip_reason_item_not_found": "背包里没有这件物品",
    "basic_equip_reason_unknown_slot": "没有这个装备槽位",
    "basic_equip_reason_max_reached": "该槽位已达可装备数量上限",

    # —— /技能（LV 行固定头部 + 类型/MP/描述 + 派生指向；MP 仅 >0 显示）——
    "basic_skill_header": "【技能】Lv{level}.{name}（{job}）",
    "basic_skill_count": "技能 {count} 项",
    "basic_skill_row": "{idx}. {name}（{type}）",
    "basic_skill_mp": " {mp} MP",
    "basic_skill_chain": "可派生成：{names}",

    # —— /帮助 注册引导版（B6 豁免）+ 组页头（4f RUL-23）——
    "basic_register_guide": "【新手引导】发 注册 名字 职业 创建角色\n"
                            "注册 —— 创建角色（未注册必需）\n"
                            "状态 —— 查看角色状态面板\n"
                            "背包 —— 查看背包物品\n"
                            "装备/技能 等更多指令注册后可用，发 帮助 查看完整列表",
    "basic_help_group_header": "【{group}】",
}

PLACEHOLDER_WHITELIST: Dict[str, set] = {
    "basic_register_gate": set(),
    "basic_empty_bag": set(),
    "basic_quality_suffix": {"quality"},
    "basic_bound_suffix": set(),
    "basic_currency_row": {"name", "value"},
    "basic_filter_hint": set(),
    "basic_filter_unknown": {"word"},
    "basic_no_slot": set(),
    "basic_equip_name_hint": set(),
    "basic_equip_header": set(),
    "basic_equip_line": {"slot", "name"},
    "basic_equip_enh": {"enhance"},
    "basic_equip_no_player": set(),
    "basic_equip_no_item": set(),
    "basic_equip_not_equippable": set(),
    "basic_equip_no_slot": set(),
    "basic_equip_ok": {"name"},
    "basic_equip_replaced": set(),
    "basic_equip_remove_ok": {"name"},
    "basic_equip_fail": {"msg"},
    "basic_equip_fail_wear": set(),
    "basic_equip_fail_remove": set(),
    "basic_equip_wear_fail": set(),
    "basic_equip_remove_fail": set(),
    "basic_equip_reason_slot_mismatch": set(),
    "basic_equip_reason_mutual_exclusion": set(),
    "basic_equip_reason_empty_slot": set(),
    "basic_equip_reason_in_battle": set(),
    "basic_equip_reason_item_not_found": set(),
    "basic_equip_reason_unknown_slot": set(),
    "basic_equip_reason_max_reached": set(),
    "basic_skill_header": {"level", "name", "job"},
    "basic_skill_count": {"count"},
    "basic_skill_row": {"idx", "name", "type"},
    "basic_skill_mp": {"mp"},
    "basic_skill_chain": {"names"},
    "basic_register_guide": set(),
    "basic_help_group_header": {"group"},
}
