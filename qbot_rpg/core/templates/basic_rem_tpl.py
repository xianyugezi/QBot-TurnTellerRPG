"""
模板分区：basic_rem（基础指令剩余：装备/技能/货币等；2026-08-31 模板配置化包拆分）。

默认模板表 + 占位符白名单；内容包 templates.json 可覆盖同 key。

铁律：字符串 = 2026-08-31 前写死在 basic_commands.py 的逐字文案迁移（RUL-08 注册门槛 /
装备栏 / 装备穿卸适配器消息 / 帮助注册引导与组页头），默认值改动会导致现有测试断言失效——
需与 basic_commands 渲染处 tpl_of(ctx, "basic_*", {...}) 一致。

2026-09-12 消息模板重构·批4·路L：本分区 27 键（/背包查看 bag_view_*、/背包 empty/品质/绑定/
货币/筛选、/装备 槽位·名称提示、卸下、/技能列表与详情·派生）迁出至全量表
core/templates/template_table.json；本文件不再登记这些 key（加载链默认表优先，同名以新表覆盖）。
"""
from __future__ import annotations

from typing import Any, Dict

DEFAULT_TEMPLATES: Dict[str, Any] = {
    # —— RUL-08 注册门槛（对齐 register_commands / explore / investigate 本地门）——
    "basic_register_gate": "❌ 请先 /注册 创建角色（/注册 名字 职业）",

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
    "basic_register_guide": set(),
    "basic_help_group_header": {"group"},
}
