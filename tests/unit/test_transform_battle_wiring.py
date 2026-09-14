"""M13 6b transform 战斗接线单测（tests/unit/test_transform_battle_wiring.py · M13 批7 路7B）。

覆盖：
  - start() 建 transform_state 段（常态骨架 form=null）
  - 持有者行动收尾（ACTOR_TURN_END）后：remaining 递减 + 自然结束还原 + 冷却递减
  - _settle 战斗结束 transform 清零回常态
  - to_snapshot/from_snapshot 携带 transform_state

CTB 迁移（2026-09-10 · Agent 3）：旧「end_turn ⑥ tick」（回合边界全员 tick）在
CTB 下不存在——`enemy_act`/`end_turn` 已按 Wave A 删除为 `NotImplementedError` 壳。
形态/冷却改由**持有者（player）自己的 `_after_actor_action`（ACTOR_TURN_END）**
推进，因此旧「do_action → enemy_act → end_turn」三段被替换为一次 `player_act`
（提交玩家行动 + 调度器自动推进 NPC 连锁到下一个 ready）。

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

from typing import Any

from qbot_rpg.core.battle import BattleEngine


def _engine(**over: Any) -> BattleEngine:
    eng = BattleEngine()
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家", "agi": 10},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼", "agi": 10},
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


def _seq(eng: BattleEngine) -> int:
    """当前已结算行动计数（CTB 权威进度计量）。"""
    return int(eng.battle_state()["action_seq"])


def test_start_builds_transform_state() -> None:
    """start() 建 transform_state 常态骨架（form=null）。"""
    eng = _engine()
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] is None
    assert ts["remaining"] == 0
    assert ts["cooldown_remaining"] == 0


def test_owner_action_end_decrements_remaining() -> None:
    """形态持续中 → 持有者一次行动收尾（ACTOR_TURN_END）remaining-1。

    CTB 语义：形态按**持有者（player）自身行动次数**计时，不再随「回合」推进。
    """
    eng = _engine()
    _set_form(eng, remaining=2)
    seq0 = _seq(eng)
    eng.player_act("normal")  # 持有者提交一次行动（调度器自动推进 NPC 连锁）
    ts = eng.battle_state()["transform_state"]
    assert ts["remaining"] == 1, f"remaining 应 2→1，got {ts['remaining']}"
    assert _seq(eng) > seq0, "行动计数应严格增加（CTB 时间轴前进）"


def test_owner_action_end_natural_revert_when_remaining_zero() -> None:
    """remaining 递减到 0 → 自然结束还原（form 清空）。"""
    eng = _engine()
    _set_form(eng, remaining=1)
    eng.player_act("normal")
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] is None, f"形态应自然还原，got {ts}"
    assert ts["remaining"] == 0


def test_cooldown_decrements_on_owner_action() -> None:
    """常态+冷却期 → 持有者一次行动收尾冷却 -1。"""
    eng = _engine()
    eng._snap["transform_state"] = {
        "job_id": "berserker", "form": None, "form_name": None,
        "remaining": 0, "cooldown_remaining": 5,
        "form_status_id": None, "active_skill_set": None,
    }
    eng.player_act("normal")
    ts = eng.battle_state()["transform_state"]
    assert ts["cooldown_remaining"] == 4, f"冷却应 5→4，got {ts['cooldown_remaining']}"


def test_settle_clears_transform_state() -> None:
    """战斗结束 → transform_state 清零回常态。"""
    eng = _engine()
    _set_form(eng, remaining=3)
    # 直接杀敌触发战斗结束
    eng._snap["enemy"]["hp"] = 0
    eng.player_act("normal")
    ts = eng.battle_state()["transform_state"]
    assert eng.finished is True, "敌方归零后战斗应终局"
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
