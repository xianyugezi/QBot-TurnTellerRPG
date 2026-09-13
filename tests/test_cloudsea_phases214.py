# -*- coding: utf-8 -*-
"""九期 214 阶段状态机定向测试：非 HP 触发／HP 阈值／上位直切／latch 驻留／
inherit_boss_state 携带／动态弱点／三内建条件／纯阈值旧路径零变化。"""

import random

from qbot_rpg.core.monster_ai import MonsterAI

# 03 §M3.11 灰岗四阶段（content/cloudsea/phases.json 同构测试态）
HUILIANG_PHASES = [
    {"no": 1, "name": "常态·踏岛", "threshold": 100,
     "mods": {"dmg_mult": 1.0, "def_mod": 0, "spd": 85}},
    {"no": 2, "name": "激怒·崩岭", "threshold": 70,
     "enter_action": "崩解践踏蓄势",
     "mods": {"dmg_mult": 1.25, "def_mod": 80, "spd": 105}},
    {"no": 3, "name": "疲态·露核",
     "enter_when": [{"type": "seq_count", "value": 8}, {"type": "pv_broken"}],
     "from": [2],
     "mods": {"dmg_mult": 0.8, "def_mod": -120, "core_hardness": 0.45},
     "inherit_rules": {"stack_retain": 0.5, "control_mult": 0.5}},
    {"no": 4, "name": "狂澜·蚀涌", "threshold": 35,
     "mods": {"dmg_mult": 1.5, "def_mod": 150, "unbreakable": True}},
]


def _agent(phases):
    return MonsterAI({"name": "崩岭岩犀·灰岗", "phases": phases,
                      "weakness": {"岩": 1.7}}, action_lib={}, rng=random.Random(7))


def _state(hp, max_hp=12000, prev=None, pv=1.0):
    st = {"enemy": {"hp": hp, "max_hp": max_hp, "pv": pv,
                    "weakness": {"岩": 1.7}},
          "turn": 0}
    if prev is not None:
        st["ai_state"] = {"phase": prev, "boss_phase": prev}
    return st


def test_01_hp阈值70_切激怒():
    ai = _agent(HUILIANG_PHASES).decide(_state(hp=8000, prev=1))
    assert ai["ai_state"]["phase"] == 2
    assert ai["ai_state"]["phase_mods"]["dmg_mult"] == 1.25


def test_02_非HP触发_激怒满8序列_切疲态():
    bs = _state(hp=8000, prev=2)
    a = _agent(HUILIANG_PHASES)
    for _ in range(8):
        a.decide(bs)
    assert bs["ai_state"]["phase"] == 3
    assert bs["ai_state"]["phase_mods"]["core_hardness"] == 0.45


def test_03_上位直切_35pct从常态直达狂澜():
    ai = _agent(HUILIANG_PHASES).decide(_state(hp=3000, prev=1))
    assert ai["ai_state"]["phase"] == 4
    assert ai["ai_state"]["phase_mods"]["unbreakable"] is True


def test_04_latch驻留_疲态不回落激怒():
    bs = _state(hp=8000, prev=3)
    bs["ai_state"].update({"seq_count": 20})
    a = _agent(HUILIANG_PHASES)
    a.decide(bs)
    assert bs["ai_state"]["phase"] == 3


def test_05_inherit_boss_state携带():
    bs = _state(hp=8000, prev=2)
    bs["boss_state"] = {"ailment_buildup": {"蚀印": 4}, "stamina": {}, "break_slots": {}}
    a = _agent(HUILIANG_PHASES)
    for _ in range(8):
        a.decide(bs)
    # 疲态 inherit_rules stack_retain 0.5 → 蚀印积蓄 4×0.5
    assert bs["boss_state"]["ailment_buildup"]["蚀印"] == 2.0


def test_06_动态弱点换装与首切备份():
    phases = [{"no": 1, "threshold": 100},
              {"no": 2, "threshold": 50, "weakness": {"幽": 2.0}}]
    bs = _state(hp=4000, prev=1)
    ai = _agent(phases).decide(bs)
    assert bs["enemy"]["weakness"] == {"幽": 2.0}
    assert bs["ai_state"]["weakness_base"] == {"岩": 1.7}
    assert ai["ai_state"]["weakness_base"] == {"岩": 1.7}


def test_07_内建条件三型():
    bs = _state(hp=12000, prev=1)
    a = _agent(HUILIANG_PHASES)
    for _ in range(9):
        a.decide(bs)
    assert bs["ai_state"]["seq_count"] >= 8
    assert a._eval_condition({"type": "seq_count", "value": 8}, bs)
    assert not a._eval_condition({"type": "seq_count", "value": 99}, bs)
    # damage_taken：count 与 amount 双模
    bs2 = {"ai_state": {"damage_taken_events": 3, "damage_taken_amount": 1500.0}}
    assert a._eval_condition({"type": "damage_taken", "value": 3}, bs2)
    assert a._eval_condition({"type": "damage_taken", "mode": "amount", "value": 1000}, bs2)
    assert not a._eval_condition({"type": "damage_taken", "value": 4}, bs2)
    # stamina_empty：boss_state 全键 ≤0 成立、有正键不成立、缺数据 False
    assert a._eval_condition({"type": "stamina_empty"},
                             {"boss_state": {"stamina": {"k": 0}}})
    assert not a._eval_condition({"type": "stamina_empty"},
                                 {"boss_state": {"stamina": {"k": 2}}})
    assert not a._eval_condition({"type": "stamina_empty"}, {})


def test_08_纯阈值旧路径零变化():
    plain = [{"threshold": 100}, {"threshold": 60}, {"threshold": 30}]
    a = _agent(plain)
    ai = a.decide(_state(hp=5000, prev=1))
    assert ai["ai_state"]["phase"] == 2
    assert "phase_mods" not in ai["ai_state"]


def test_09_受击检测_回落计事件与量():
    bs = _state(hp=12000, prev=1)
    a = _agent(HUILIANG_PHASES)
    a.decide(bs)
    bs["enemy"]["hp"] = 11500
    a.decide(bs)
    assert bs["ai_state"]["damage_taken_events"] == 1
    assert bs["ai_state"]["damage_taken_amount"] == 500.0
