# -*- coding: utf-8 -*-
"""M5 消息模板采集：调用各渲染函数收集实测输出（复用测试 make_ctx）。"""
import sys
sys.path.insert(0, '/root/QBot-TurnTellerRPG')

from qbot_rpg.commands.parsers import parse_command

OUT = []  # type: ignore[var-annotated]
def p(name, text):
    OUT.append(f"### {name}")
    OUT.append("```")
    OUT.append(text)
    OUT.append("```")
    OUT.append("")

# --- 基础列表 ---
from tests.unit.test_basic_commands import make_ctx as mk_basic
from qbot_rpg.commands.basic_commands import cmd_view, cmd_view_detail, cmd_bag, cmd_bag_filter, cmd_equip, cmd_skill, cmd_help

ctx = mk_basic()
# items 补 type（内容包 items.json 有 type；测试 ctx 缺省无 → 补上演示筛选效果）
_TYPE_BY_ITEM = {"potion_hp": "consumable", "iron_sword": "weapon", "quest_letter": "quest",
                 "iron_ore": "material", "cloth": "material"}
for _id, _t in _TYPE_BY_ITEM.items():
    if _id in ctx["items"]:
        ctx["items"][_id]["type"] = _t
p("/角色", cmd_view(parse_command("/角色"), ctx))
p("/角色详细", cmd_view_detail(parse_command("/角色详细"), ctx))
p("/背包", cmd_bag(parse_command("/背包"), ctx))
p("/背包筛选装备", cmd_bag_filter(parse_command("/背包筛选装备"), ctx))
p("/背包筛选药剂", cmd_bag_filter(parse_command("/背包筛选药剂"), ctx))
p("/装备", cmd_equip(parse_command("/装备"), ctx))
p("/技能", cmd_skill(parse_command("/技能"), ctx))
p("/帮助", cmd_help(parse_command("/帮助"), ctx))

# --- 商店 ---
try:
    from tests.unit.test_shop_commands import make_ctx as mk_shop
    from qbot_rpg.commands.shop_commands import cmd_shop
    p("/商店", cmd_shop(parse_command("/商店"), mk_shop()))
except Exception as e:
    p("/商店", f"(构造失败: {e})")

# --- 任务 ---
try:
    from tests.unit.test_quest_commands import make_ctx as mk_quest
    from qbot_rpg.commands.quest_commands import cmd_quest
    p("/任务", cmd_quest(parse_command("/任务"), mk_quest()))
except Exception as e:
    p("/任务", f"(构造失败: {e})")

# --- 签到 ---
try:
    from tests.unit.test_checkin_commands import make_ctx as mk_checkin
    from qbot_rpg.commands.checkin_commands import cmd_checkin
    p("/签到", cmd_checkin(parse_command("/签到"), mk_checkin()))
except Exception as e:
    p("/签到", f"(构造失败: {e})")

print("\n".join(OUT))
