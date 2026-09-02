"""consume_marks 运行时消费单测（G2 2026-09-02 接线，细化_1d §4.2 / S-01）。

覆盖：
  1. 有足够印记 → 施放成功 + 印记扣除
  2. 印记不足 → 被拒不耗回合（S-01：不耗 MP/不改连段/印记不清）
  3. 同技能 mark_add 自产自销被拒（D-01 / AT-17：先于结算判定）
  4. 无 consume_marks 技能零变化

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""
from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine


def _skills() -> Dict[str, Dict[str, Any]]:
    """技能库：消耗印记技（heavens_smash 型）+ 普通技 + 印记定义（供 _side_of 判定）。"""
    defs: Dict[str, Dict[str, Any]] = {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                         "kind": "damage", "power": 100, "mp_cost": 0},
        "flame_burst": {"id": "flame_burst", "name": "烈焰爆发", "type": "active",
                        "kind": "damage", "power": 120, "mp_cost": 0,
                        "consume_marks": {"fire_mark": 1}},
        "no_consume": {"id": "no_consume", "name": "无消耗技", "type": "active",
                       "kind": "damage", "power": 100, "mp_cost": 0},
        # mark 定义（_side_of 经 resolver 查 appliable_to 判定扣减侧）
        "fire_mark": {"id": "fire_mark", "name": "火印", "type": "mark",
                      "appliable_to": ["self", "enemy"], "polarity": "positive"},
    }
    return defs


def _player(**over: Any) -> Dict[str, Any]:
    p = {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"}
    p.update(over)
    return p


def _enemy(**over: Any) -> Dict[str, Any]:
    e = {"hp": 800, "max_hp": 800, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"}
    e.update(over)
    return e


def _marks(side: str, mark_id: str, count: int, polarity: str = "positive") -> Dict[str, Any]:
    return {"marks_state": {
        "player": [{"mark_id": mark_id, "name": mark_id, "count": count,
                    "polarity": polarity, "applier": "player"}] if side == "player" else [],
        "enemy": [{"mark_id": mark_id, "name": mark_id, "count": count,
                   "polarity": polarity, "applier": "player"}] if side == "enemy" else [],
    }}


def _count(eng: BattleEngine, side: str, mark_id: str) -> int:
    st = eng.battle_state()
    total = 0
    for m in (st.get("marks_state") or {}).get(side, []):
        if m.get("mark_id") == mark_id:
            total += int(m.get("count", 0))
    return total


def test_consume_success_deducts_marks() -> None:
    """有足够印记 → 施放成功 + 印记扣除（AT-16）。"""
    eng = BattleEngine(defs=_skills())
    eng.start(_player(), _enemy())
    # 预置 2 层 fire_mark 于玩家侧（apply_add 官方姿势，fire_mark appliable_to 含 self → attacker 侧）
    from qbot_rpg.core.marks import AddMark  # noqa: PLC0415

    eng.marks_manager().apply_add(AddMark(side="player", mark="fire_mark", count=2))
    out = eng.do_action("player", {"type": "skill", "skill_id": "flame_burst"})
    assert out.ok is True, f"应施放成功，got {out.message}"
    assert _count(eng, "player", "fire_mark") == 1, "印记应扣至 1"


def test_consume_insufficient_rejected_free() -> None:
    """印记不足（0 层 < 需求 1）→ 被拒不耗回合（S-01：完全免费）。"""
    eng = BattleEngine(defs=_skills())
    eng.start(_player(mp=0), _enemy())
    # 不预置任何印记 → 不足
    out = eng.do_action("player", {"type": "skill", "skill_id": "flame_burst"})
    assert out.ok is False, "印记不足应被拒"
    assert "印记不足" in out.message
    # 零副作用：印记不清、连段不改、可再行动（state 仍 act）
    assert _count(eng, "player", "fire_mark") == 0, "印记不应被清（S-01）"
    assert eng.state == "act", "被拒不耗回合（state 应仍 act）"


def test_consume_self_produced_rejected_before_settle() -> None:
    """同技能 mark_add 自产自销被拒（D-01：先于结算判定，AT-17）。"""
    # 技能本身 effects 先 mark_add fire_mark 再 consume 它 → 检查先于结算 → 被拒
    skills = _skills()
    skills["self_produce"] = {
        "id": "self_produce", "name": "自产自销", "type": "active", "kind": "damage",
        "power": 100, "mp_cost": 0,
        "consume_marks": {"fire_mark": 1},
        "effects": [{"type": "mark_add", "target": "self", "mark": "fire_mark", "count": 1}],
    }
    eng = BattleEngine(defs=skills)
    eng.start(_player(), _enemy())
    eng._snap["marks_state"] = {"player": [], "enemy": []}
    out = eng.do_action("player", {"type": "skill", "skill_id": "self_produce"})
    assert out.ok is False, "先结算后扣 → 无印应被拒（AT-17）"
    assert _count(eng, "player", "fire_mark") == 0, "被拒不应施加效果"


def test_no_consume_skill_untouched() -> None:
    """无 consume_marks 技能 → 不触及印记、施放成功。"""
    eng = BattleEngine(defs=_skills())
    eng.start(_player(), _enemy())
    eng._snap["marks_state"] = {"player": [], "enemy": []}
    out = eng.do_action("player", {"type": "skill", "skill_id": "no_consume"})
    assert out.ok is True, f"无 consume 技能应正常，got {out.message}"
    assert _count(eng, "player", "fire_mark") == 0
