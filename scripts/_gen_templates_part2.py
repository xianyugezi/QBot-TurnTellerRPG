# -*- coding: utf-8 -*-
"""M5 消息模板采集 part2：战斗 + 探索 + 前缀 + 错误模板。"""
import sys
sys.path.insert(0, '/root/QBot-TurnTellerRPG')
from types import SimpleNamespace

from qbot_rpg.commands.parsers import parse_command
from tests.unit.test_battle_render_startend import _party, _enemy
from tests.unit.test_battle_render_player import _outcome, _enriched
from tests.unit.test_battle_render_settlement import _round, _combo
from qbot_rpg.core.message_format.battle_render import (
    render_battle_start, render_battle_round, render_battle_end,
)

OUT = []
def p(name, text):
    OUT.append(f"### {name}")
    OUT.append("```")
    OUT.append(text)
    OUT.append("```")
    OUT.append("")

# --- 战斗 ---
p("战斗开始", render_battle_start(_party(), _enemy(), hint="弱点：火（×1.3）"))

p("战斗轮·玩家命中", render_battle_round(_round(
    outcomes=(_enriched(_outcome(final_damage=18, target_hp=7)),),
    player=21, enemy=7, enemy_name="史莱姆", player_max_hp=35, enemy_max_hp=25)))

p("战斗轮·会心击杀", render_battle_round(_round(
    outcomes=(_enriched(_outcome(final_damage=40, target_hp=0, crit="high",
                                battle_ended=True, status="win"), target_max_hp=25),),
    player=21, enemy=0, enemy_name="史莱姆", player_max_hp=35, enemy_max_hp=25,
    ended=True, status="win")))

p("战斗轮·怪物反击", render_battle_round(_round(
    outcomes=(
        _enriched(_outcome(final_damage=12, target_hp=13)),
        _enriched(_outcome(seq=2, actor="enemy", action_type="normal", target="阿伟",
                           final_damage=6, target_hp=29)),
    ),
    player=29, enemy=13, enemy_name="史莱姆", player_max_hp=35, enemy_max_hp=25)))

combo_oc = _combo([
    {"seg": 1, "action": "火球术", "final_damage": 10, "target_hp": 15,
     "target_max_hp": 25, "target": "史莱姆", "crit": "low", "blocked": False,
     "derived_capped": False},
    {"seg": 2, "action": "火球术", "final_damage": 12, "target_hp": 3,
     "target_max_hp": 25, "target": "史莱姆", "crit": "low", "blocked": False,
     "derived_capped": False},
    {"seg": 3, "action": "火球术", "final_damage": 3, "target_hp": 0,
     "target_max_hp": 25, "target": "史莱姆", "crit": "low", "blocked": False,
     "derived_capped": False},
], target_hp=0, target="史莱姆", target_max_hp=25)
p("战斗轮·连段", render_battle_round(_round(
    outcomes=(combo_oc,),
    player=21, enemy=0, enemy_name="史莱姆", player_max_hp=35, enemy_max_hp=25,
    ended=True, status="win")))

p("结算·胜利", render_battle_end(
    _party(), _enemy(), "win", status="win", exp=100000, gold=10000,
    drops=[("材料", 10), ("材料", 100), ("装备", 1), ("装备", 1), ("药剂", 1), ("药剂", 1)],
    enemy_name="史莱姆", final_damage=246))

p("结算·失败", render_battle_end(_party(), _enemy(), "lose", status="lose", enemy_name="史莱姆"))

p("结算·平局", render_battle_end(_party(), _enemy(), "draw", status="draw", enemy_name="史莱姆"))

p("木桩明细", render_battle_end(
    _party(), _enemy(), "win", status="win", exp=0, gold=0, drops=(),
    enemy_name="木桩",
    summary=SimpleNamespace(turns=5, actions=[("火球术", 120, 0.6), ("普通攻击", 80, 0.4)]),
))

# --- 探索 ---
try:
    from tests.unit.test_explore_filter import make_ctx as mk_exp, _enter_ctx
    from qbot_rpg.commands.explore_commands import cmd_enter, cmd_rest
    p("/进入", cmd_enter(parse_command("/进入 上"), _enter_ctx()))
    p("/休息(拒绝)", cmd_rest(parse_command("/休息"), mk_exp()))
except Exception as e:
    p("/进入", f"(构造失败: {e})")

# --- 前缀 ---
try:
    from qbot_rpg.commands.prefix_wiring import apply_message_prefix
    r = apply_message_prefix(
        "正文内容",
        level=49, name="玩家", title="",
        extra={"群名": "新手村"},
        settings={"format": "Lv[等级].[玩家名] -[称号]-", "enabled": True, "show_on_system": False,
                  "per_channel": "all", "hide_when_empty": False, "empty_title_text": "-",
                  "prefix_max_len": 40},
    )
    p("前缀接线", str(r.text))
except Exception as e:
    p("前缀接线", f"(构造失败: {e})")

# --- 错误模板 ---
try:
    from qbot_rpg.commands.sender import format_tpl12
    p("指令错误 TPL-12", format_tpl12("/背包 abc"))
except Exception as e:
    p("指令错误 TPL-12", f"(构造失败: {e})")

from types import SimpleNamespace
print("\n".join(OUT))
