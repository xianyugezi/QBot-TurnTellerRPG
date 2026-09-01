"""M13 6b transform 战斗接线单测（tests/unit/test_transform_battle_wiring.py · M13 批7 路7B）。

覆盖：
  - start() 建 transform_state 段（常态骨架 form=null）
  - end_turn ⑥ tick 后：remaining 递减 + 自然结束还原 + 冷却递减
  - _settle 战斗结束 transform 清零回常态
  - to_snapshot/from_snapshot 携带 transform_state

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

from typing import Any

from qbot_rpg.core.battle import BattleEngine


def _engine(**over: Any) -> BattleEngine:
    eng = BattleEngine()
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def _set_form(eng: BattleEngine, **over: Any) -> None:
    """直接写引擎内 transform_state（绕过 F1，测 tick/清零接线）。"""
    # battle_state() 是深拷贝——改引擎内部 _snap
    eng._snap["transform_state"] = {
        "job_id": "berserker", "form": "berserker_form", "form_name": "狂战士形态",
        "remaining": 2, "cooldown_remaining": 0,
        "form_status_id": "form_berserker", "active_skill_set": "transform_skills",
        **over,
    }


def test_start_builds_transform_state() -> None:
    """start() 建 transform_state 常态骨架（form=null）。"""
    eng = _engine()
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] is None
    assert ts["remaining"] == 0
    assert ts["cooldown_remaining"] == 0


def test_end_turn_decrements_remaining() -> None:
    """形态持续中 → end_turn tick remaining-1。"""
    eng = _engine()
    _set_form(eng, remaining=2)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = eng.battle_state()["transform_state"]
    assert ts["remaining"] == 1, f"remaining 应 2→1，got {ts['remaining']}"


def test_end_turn_natural_revert_when_remaining_zero() -> None:
    """remaining 递减到 0 → 自然结束还原（form 清空）。"""
    eng = _engine()
    _set_form(eng, remaining=1)
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] is None, f"形态应自然还原，got {ts}"
    assert ts["remaining"] == 0


def test_end_turn_cooldown_decrements() -> None:
    """常态+冷却期 → end_turn tick cooldown-1。"""
    eng = _engine()
    eng._snap["transform_state"] = {
        "job_id": "berserker", "form": None, "form_name": None,
        "remaining": 0, "cooldown_remaining": 5,
        "form_status_id": None, "active_skill_set": None,
    }
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = eng.battle_state()["transform_state"]
    assert ts["cooldown_remaining"] == 4, f"冷却应 5→4，got {ts['cooldown_remaining']}"


def test_settle_clears_transform_state() -> None:
    """战斗结束 → transform_state 清零回常态。"""
    eng = _engine()
    _set_form(eng, remaining=3)
    # 直接杀敌触发战斗结束
    eng._snap["enemy"]["hp"] = 0
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] is None, f"战斗结束形态应清零，got {ts}"


def test_snapshot_carries_transform_state() -> None:
    """to_snapshot/from_snapshot 携带 transform_state。"""
    eng = _engine()
    _set_form(eng, remaining=2)
    snap = eng.to_snapshot()
    assert snap.get("transform_state", {}).get("form") == "berserker_form", \
        "快照应含 transform_state 形态"
    # 恢复
    eng2 = BattleEngine().from_snapshot(snap)  # type: ignore[call-arg]
    ts2 = eng2.battle_state()["transform_state"]
    assert ts2["form"] == "berserker_form"
    assert ts2["remaining"] == 2
