"""批22 · D2：怪物攻击无视玩家护盾——**复用 B2 的 `ignore_shield`**（并入 effects），不造新开关。

怪物行动定义（`_ai_action_dict`）把 `effects` 合并到行动顶层，B2 的开关扫描（battle.py
`_suppress_flags`）据此生效 → 引擎级证据：怪物攻击不再被护盾吸收、护盾 remaining 不减。
测试只建临时对象，不写真实内容包。
"""
from __future__ import annotations

import copy

from qbot_rpg.core.battle import BattleEngine

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50,
          "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
         "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
         "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]
SHIELD_FX = {"id": "sh", "name": "盾", "class": "effect", "type": "shield", "value": 100}


class _QueueRNG:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _monster_attack(ignore_shield: bool):
    eng = BattleEngine(defs={"sh": SHIELD_FX})
    eng._rng = _QueueRNG(SEQ)
    eng.start(copy.deepcopy(PLAYER), copy.deepcopy(ENEMY), random_seed=7)
    eng.set_effect_ids("player", ["sh"])
    action = {"type": "normal", "mult": 1.0}
    if ignore_shield:
        action["effects"] = [{"type": "buff", "ignore_shield": True}]
    eng._resolve_damage_action("enemy", action)
    st = eng.battle_state()
    rec = [r for r in st["action_record"] if r["actor"] == "enemy"][-1]
    return st["player"]["defenses"]["shield"]["remaining"], rec["damage"]["final"]


def test_d2_monster_attack_ignores_player_shield() -> None:
    rem_no, dmg_no = _monster_attack(False)
    rem_ig, dmg_ig = _monster_attack(True)
    assert dmg_no == 0 and rem_no == 30            # 护盾吸收 70/100（修前）
    assert dmg_ig == 70 and rem_ig == 100          # 无视护盾：护盾未动、伤害直达（修后）
