# -*- coding: utf-8 -*-
"""M5 消息模板采集 part3：业务结果消息（购买/出售/任务子指令/签到子指令/战斗外响应）。"""
import sys
sys.path.insert(0, '/root/QBot-TurnTellerRPG')

from qbot_rpg.commands.parsers import parse_command

OUT = []
def p(name, text):
    OUT.append(f"### {name}")
    OUT.append("```")
    OUT.append(text)
    OUT.append("```")
    OUT.append("")

# --- 购买 / 出售 ---
try:
    from tests.unit.test_shop_commands import make_ctx as mk_shop
    from qbot_rpg.commands.shop_commands import cmd_buy, cmd_sell
    ctxs = mk_shop()
    p("/购买 成功", cmd_buy(parse_command("/购买 药水 3"), ctxs))
    p("/购买 余额不足", cmd_buy(parse_command("/购买 金珠"), ctxs))
    p("/出售 成功", cmd_sell(parse_command("/出售 铁矿"), ctxs))
except Exception as e:
    p("购买/出售", f"(构造失败: {e})")

# --- 任务子指令 ---
try:
    from tests.unit.test_quest_commands import make_ctx as mk_quest
    from qbot_rpg.commands.quest_commands import cmd_quest
    ctxq = mk_quest()
    p("/任务 接取", cmd_quest(parse_command("/任务 接取 1"), ctxq))
    p("/任务 信息", cmd_quest(parse_command("/任务 信息 1"), ctxq))
    p("/任务 交付", cmd_quest(parse_command("/任务 交付 1"), ctxq))
    p("/任务 放弃", cmd_quest(parse_command("/任务 放弃 1"), ctxq))
except Exception as e:
    p("任务子指令", f"(构造失败: {e})")

# --- 签到子指令 ---
try:
    from tests.unit.test_checkin_commands import make_ctx as mk_checkin
    from qbot_rpg.commands.checkin_commands import cmd_checkin
    ctxc = mk_checkin()
    p("/签到 补签", cmd_checkin(parse_command("/签到 补签"), ctxc))
except Exception as e:
    p("签到补签", f"(构造失败: {e})")

# --- 战斗外响应 ---
try:
    from tests.unit.test_battle_wiring import RecordingSender
    from qbot_rpg.commands.battle_commands import cmd_battle_attack, cmd_battle_defend, cmd_battle_flee
    from tests.unit.test_basic_commands import make_ctx as mk_basic
    ctx = mk_basic()
    ctx["sender"] = RecordingSender()   # M5-08 装配注入
    def _msg(r):
        return r["message"] if isinstance(r, dict) and r.get("message") else str(r)
    p("/攻击 无战斗", _msg(cmd_battle_attack(parse_command("/攻击 史莱姆"), ctx)))
    p("/防御 无战斗", _msg(cmd_battle_defend(parse_command("/防御"), ctx)))
    p("/逃跑 无战斗", _msg(cmd_battle_flee(parse_command("/逃跑"), ctx)))
except Exception as e:
    p("战斗外响应", f"(构造失败: {e})")

print("\n".join(OUT))
