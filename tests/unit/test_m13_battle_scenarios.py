"""M13 6c 战斗集成场景单测（tests/unit/test_m13_battle_scenarios.py · M13 批17 路17C）。

真实 BattleEngine 驱动（`player_act` 全流程，零 mock 引擎内部）：
  1. 狂战士场景：rage_burst 触发狂暴形态 → 形态技能怒涛斩 → 形态拍 tick →
     自然还原 → 冷却归零可再次触发（细化_6b F1/F2/S5 + TC-01/TC-05/TC-17）
  2. 元素法师场景：元素能量积蓄（fire/wind gain）→ 组合触发（火火水）→
     双耗结算 → 能量池分布行为变化（细化_6c F-C1/F-C2 + TC-14/TC-15）
  3. 多段 hits：blade_dance 3 段伤害战报（细化_6a TC-03 / 1g1c 段级流水）
  4. 集成闭环：怒气/能量战斗结束清零 + 快照 round-trip 续战携带双段

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。
  - 旧 `_full_turn` = `do_action("player")` → `enemy_act()`（怪物后手）→ `end_turn()`（⑥tick）
    三段；`enemy_act`/`end_turn` 已按 Wave A M4/M5 删除（壳方法抛 NotImplementedError），
    合并为**一次 `player_act`**（提交玩家行动 + 调度器自动推进 NPC 连锁）。
  - 形态（transform）在 CTB 下按**持有者行动次数**计时：形态属玩家 → 每次玩家
    `player_act` 后 remaining/cooldown 递减一拍（`_tick_transform_state(actor)`），
    与旧「回合 tick」逐拍等价。故本文件「一次玩家行动」即旧「一回合」的迁移目标。
  - 进度断言改用 `battle_state()["action_seq"]`（权威行动计数）；`turn` 仅为镜像。
  - 快照落点为 CTB 边界（`after_action`），不再是 `turn_start`/`turn_end`。

铁律：零 NoneBot import（平台无关核心包）；零定时器/零睡眠（引擎纯函数
确定性 tick）；每个用例至少一条断言；不 commit。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_RAGE = {"name": "怒气", "type": "rage", "base": 0, "max": 100, "reset": "battle"}
_ELEMENT = {"name": "元素能量", "type": "element_energy", "base": 0,
            "max_per_pool": 3, "pools": ["fire", "water", "wind"], "reset": "battle"}


def _skills() -> Dict[str, Dict[str, Any]]:
    """技能库：狂战士（触发技/普攻/形态技能/主动还原）+ 元素法师（产能量技/
    组合爆发）+ 多段 blade_dance。"""
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                         "kind": "damage", "power": 100, "mp_cost": 0},
        # 狂战士：触发技（狂暴）+ 常态技能 + 形态技能（怒涛斩）+ 主动还原
        "rage_burst": {"id": "rage_burst", "name": "狂暴", "type": "active",
                       "kind": "damage", "power": 80, "mp_cost": 15,
                       "energy_cost": {"rage": 100}},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                         "kind": "damage", "power": 150, "mp_cost": 8},
        "fury_slash": {"id": "fury_slash", "name": "怒涛斩", "type": "active",
                       "kind": "damage", "power": 220, "mp_cost": 0,
                       "job_form": "berserker_form"},
        "calm_down": {"id": "calm_down", "name": "平息战意", "type": "active",
                      "kind": "damage", "power": 100, "mp_cost": 0,
                      "revert_form": True, "job_form": "berserker_form"},
        # 元素法师：产能量技（fire/wind gain）+ 组合爆发技
        "fireball": {"id": "fireball", "name": "火球术", "type": "active",
                     "kind": "damage", "power": 130, "mp_cost": 6,
                     "energy_gain": {"element_energy": {"fire": 1}}},
        "wind_blade": {"id": "wind_blade", "name": "风刃", "type": "active",
                       "kind": "damage", "power": 120, "mp_cost": 6,
                       "energy_gain": {"element_energy": {"wind": 1}}},
        "elemental_burst": {"id": "elemental_burst", "name": "元素爆发",
                            "type": "active", "kind": "damage", "power": 100,
                            "mp_cost": 16, "cooldown": 1,
                            "energy_cost": {"element_energy": {"any": 2}},
                            "combo_table": [
                                {"combo": ["fire", "fire", "water"],
                                 "name": "蒸汽冲击", "kind": "damage", "power": 200,
                                 "element": "fire", "hits": 2,
                                 "effects": [{"type": "damage", "power": 100}]},
                                {"combo": ["fire", "wind"], "name": "火焰风暴",
                                 "kind": "damage", "power": 260, "element": "fire"},
                                {"combo": ["wind", "wind"], "name": "疾风连刃",
                                 "kind": "damage", "power": 160, "element": "wind",
                                 "hits": 2},
                            ]},
        # 多段 hits：blade_dance 3 段
        "blade_dance": {"id": "blade_dance", "name": "剑刃乱舞", "type": "active",
                        "kind": "damage", "power": 60, "mp_cost": 12, "hits": 3},
    }


def _transform() -> Dict[str, Any]:
    """transform 段（细化_6b §1.3：turns=4/cooldown=5/state_policy 默认）。"""
    return {
        "transform_skill": "rage_burst",
        "transform_to": "berserker_form",
        "form_name": "狂战士形态",
        "duration": "turns",
        "turns": 4,
        "revert": True,
        "cooldown": 5,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
    }


def _engine(**over: Any) -> BattleEngine:
    """构造战斗引擎（defs + resource_registry + set_transform_def 注入）。"""
    eng = BattleEngine(defs=_skills())
    eng.set_transform_def(_transform())
    eng._resource_registry = {"rage": _RAGE, "element_energy": _ELEMENT}  # type: ignore[attr-defined]
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
        **over,
    )
    return eng


def _ts(eng: BattleEngine) -> Dict[str, Any]:
    """transform_state 段读取。"""
    return eng.battle_state()["transform_state"]


def _rs(eng: BattleEngine, side: str = "player") -> Dict[str, Any]:
    """resource_state 段读取。"""
    return eng.battle_state()["resource_state"].get(side, {})


def _player_turn(eng: BattleEngine, action: Dict[str, Any]) -> Any:
    """CTB 单次玩家行动（替代旧「完整一轮」三段）。

    CTB 迁移（2026-09-10）：旧 `_full_turn` 走 `do_action("player")` → `enemy_act()`
    → `end_turn()`；CTB 下一次 `player_act` 即完成「玩家一拍 + 调度器自动推进 NPC
    连锁」。形态计时按持有者（玩家）行动次数推进，故本函数 = 旧「一回合」的等价物。
    """
    return eng.player_act(action)


def _last_events(eng: BattleEngine) -> Any:
    return eng._transform_events  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# 场景 1：狂战士——触发→形态→还原→冷却
# ---------------------------------------------------------------------------

def test_berserker_rage_burst_triggers_form() -> None:
    """狂战士：满怒施放狂暴 → 形态切换 + remaining/冷却起算。

    CTB 迁移（2026-09-10）：改用 `player_act`（旧 `do_action` 单步不推进行动条）。
    形态在触发行动自身的 AFTER_ACTION 位点即 tick 一拍（remaining 4→3）；冷却
    在形态激活期不递减（保持 5）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    out = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    assert out.outcomes[0].ok is True, f"狂暴应成功结算，got {out.outcomes[0].message}"
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"形态应切换，got {ts}"
    assert ts["remaining"] == 3, f"CTB：触发起算 4，触发行动自身 tick 后为 3，got {ts['remaining']}"
    assert ts["cooldown_remaining"] == 5, f"冷却应从触发起算 5，got {ts['cooldown_remaining']}"
    # C2 资源门禁：怒气 100 已消耗（TRF-5 怒气沉没）
    rs = _rs(eng)
    assert rs.get("rage", 0) == 0, f"狂暴后怒气应清零（-100 沉没），got {rs}"


def test_berserker_insufficient_rage_rejected() -> None:
    """狂战士：怒气不足（80<100）施放狂暴 → 被拒不消耗行动、怒气不变。

    CTB 迁移（2026-09-10）：R-6（裁决 2）被拒行动 = 零时间成本——经 `player_act`
    提交后 `action_seq` 不前进（旧「不耗回合」的 CTB 对应断言）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 80}, "enemy": {}}  # type: ignore[attr-defined]
    seq_before = int(eng.battle_state()["action_seq"])
    rep = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    out = rep.outcomes[0]
    assert out.ok is False, f"怒气不足应被拒，got {out}"
    assert "能量不足" in out.message
    assert int(eng.battle_state()["action_seq"]) == seq_before, \
        "CTB R-6：被拒行动零时间成本，action_seq 不得前进"
    assert _rs(eng).get("rage", 0) == 80, "被拒不应消耗怒气"
    assert _ts(eng)["form"] is None, "被拒不应触发形态"
    assert eng.battle_state()["player"]["mp"] == 100, "被拒不应扣 MP"


def test_berserker_form_skill_fury_slash() -> None:
    """狂战士：形态激活期施放怒涛斩（形态技能）→ 伤害结算且形态持续。

    CTB 迁移（2026-09-10）：经 `player_act`（含行动条推进）；形态技能自身 tick
    使 remaining 3→2，但形态保持（形态技能不触发还原）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form" and _ts(eng)["remaining"] == 3
    hp_before = eng.battle_state()["enemy"]["hp"]
    rep = eng.player_act({"type": "skill", "skill_id": "fury_slash"})
    assert rep.outcomes[0].ok is True, f"怒涛斩应成功，got {rep.outcomes[0]}"
    assert eng.battle_state()["enemy"]["hp"] < hp_before, "怒涛斩应造成伤害"
    assert _ts(eng)["form"] == "berserker_form", "形态技能不触发还原"
    assert _ts(eng)["remaining"] == 2, "CTB：形态技能行动自身 tick 使 remaining 3→2"


def test_berserker_revert_form_active_immediate() -> None:
    """狂战士：形态内施放平息战意（revert_form）→ 即时还原 + 冷却起算。"""
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    _player_turn(eng, {"type": "skill", "skill_id": "calm_down"})
    ts = _ts(eng)
    assert ts["form"] is None, f"平息战意应即时还原，got {ts}"
    assert ts["cooldown_remaining"] == 4, \
        f"主动还原后冷却应 5→4（还原行动自身 tick 递减），got {ts['cooldown_remaining']}"
    evs = _last_events(eng)
    assert any(e.get("type") == "transform_reverted" for e in evs), \
        f"应有还原事件，got {evs}"


def test_berserker_natural_revert_and_cooldown_full_cycle() -> None:
    """狂战士：turns=4 自然还原 → 冷却 5 逐次玩家行动递减 → 归零可再次触发。

    CTB 迁移（2026-09-10）：旧「回合」→「玩家行动次数」。形态 remaining（4）在
    触发行动自身 tick 后为 3，再经 3 次玩家行动走完 → 自然还原；冷却按玩家行动
    逐拍递减 4→3→2→1→0。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form" and _ts(eng)["remaining"] == 3
    for _ in range(3):
        _player_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["form"] is None, f"形态拍走完应自然还原，got {ts}"
    # 冷却 5 起算，还原行动自身 tick 已递减 → 4
    assert ts["cooldown_remaining"] == 4, f"自然还原后冷却应 5→4，got {ts}"
    # 冷却逐次玩家行动递减 4→3→2→1→0
    for expected in (3, 2, 1, 0):
        _player_turn(eng, {"type": "normal"})
        assert _ts(eng)["cooldown_remaining"] == expected, \
            f"冷却应递减到 {expected}，got {_ts(eng)}"
    # 归零回常态 → 再次触发（怒气重新攒满）
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"冷却归零应可再次触发，got {ts}"
    assert ts["cooldown_remaining"] == 5, f"二次触发冷却应从 5 起算，got {ts}"


def test_berserker_cooldown_rejects_retrigger() -> None:
    """狂战士：还原后冷却期（>0）施放狂暴 → C3 拒绝（不触发变换）。

    CTB 迁移（2026-09-10）：经 `player_act` 提交。形态门禁（C3）是**变换提交层**
    的否决（transform_rejected），非 R-6 整行动拒绝——故行动本身照常结算、行动条
    照常前进；断言口径为「产生 C3 拒绝事件且不提交新变换」。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    for _ in range(3):
        _player_turn(eng, {"type": "normal"})
    assert _ts(eng)["form"] is None and _ts(eng)["cooldown_remaining"] == 4
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    seq_before = int(eng.battle_state()["action_seq"])
    eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    evs = _last_events(eng)
    rej = [e for e in evs if e.get("type") == "transform_rejected"]
    assert rej and rej[-1].get("guard") == "C3", f"冷却期应 C3 拒绝，got {evs}"
    assert _ts(eng)["form"] is None, "C3 拒绝不应触发形态"
    # CTB：行动照常结算 → 行动条前进（形态门禁不影响本次行动的结算与推进）
    assert int(eng.battle_state()["action_seq"]) > seq_before, \
        "CTB：C3 仅否决变换提交，玩家行动本身仍推进 action_seq"


def test_berserker_form_active_rejects_retrigger() -> None:
    """狂战士：形态激活期再次施放狂暴 → C1 拒绝（形态不变）。

    CTB 迁移（2026-09-10）：经 `player_act` 提交。形态激活期二次触发由 C1 互斥
    否决变换提交（不产生新形态），但行动本身照常结算、行动条前进。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}  # type: ignore[attr-defined]
    seq_before = int(eng.battle_state()["action_seq"])
    eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form", "C1 拒绝不应改形态"
    evs = _last_events(eng)
    committed = [e for e in evs if e.get("type") == "transform_committed"]
    assert len(committed) == 1, f"二次触发不应提交新变换，got {evs}"
    # CTB：C1 仅否决变换提交，玩家行动本身仍推进 action_seq
    assert int(eng.battle_state()["action_seq"]) > seq_before, \
        "CTB：C1 拒绝不影响本次行动的结算与行动条推进"


# ---------------------------------------------------------------------------
# 场景 2：元素法师——能量积蓄→组合触发→双耗→行为变化
# ---------------------------------------------------------------------------

def test_element_mage_energy_gain_fire_and_wind() -> None:
    """元素法师：火球术/风刃命中 → fire/wind 池各 +1（封顶 3）。"""
    eng = _engine()
    _player_turn(eng, {"type": "skill", "skill_id": "fireball"})
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 1, "water": 0, "wind": 0}, \
        f"火球应 fire+1，got {rs['element_energy']}"
    _player_turn(eng, {"type": "skill", "skill_id": "wind_blade"})
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 1, "water": 0, "wind": 1}, \
        f"风刃应 wind+1，got {rs['element_energy']}"


def test_element_mage_pool_cap_at_max_per_pool() -> None:
    """元素法师：fire 池连打 4 次 → 封顶 3（第 4 次不累计）。"""
    eng = _engine()
    for _ in range(4):
        _player_turn(eng, {"type": "skill", "skill_id": "fireball"})
    rs = _rs(eng)
    assert rs["element_energy"]["fire"] == 3, f"fire 应封顶 3，got {rs['element_energy']}"
    assert rs["element_energy"]["water"] == 0 and rs["element_energy"]["wind"] == 0, \
        "其他池不受影响（池级独立）"


def test_element_mage_combo_fire_fire_water() -> None:
    """元素法师：fire2+water1 → 元素爆发命中「蒸汽冲击」组合行（双耗结算）。"""
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {},
    }
    out = eng.do_action("player", {"type": "skill", "skill_id": "elemental_burst"})
    assert out.ok is True, f"组合应命中并成功，got {out.message}"
    # F-C2 双耗：MP16 + 能量按行池分布扣减（fire2 + water1）
    assert eng.battle_state()["player"]["mp"] == 84, "MP 应扣 16"
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 0, "water": 0, "wind": 0}, \
        f"组合行消耗应 fire2+water1 归零，got {rs['element_energy']}"
    # 行为随组合变化（kind/power/element/hits 覆写）→ 战报审计
    assert out.combo_result is not None, "应有组合结果审计"
    assert out.combo_result.get("row") == "蒸汽冲击", f"组合名应=蒸汽冲击，got {out.combo_result}"


def test_element_mage_combo_insufficient_rejected() -> None:
    """元素法师：能量不足（总量门 any:2 不满足）→ 被拒不消耗行动。

    CTB 迁移（2026-09-10）：R-6 被拒 = 零时间成本（`action_seq` 不前进）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 1, "water": 0, "wind": 0}},
        "enemy": {},
    }
    seq_before = int(eng.battle_state()["action_seq"])
    out = eng.player_act({"type": "skill", "skill_id": "elemental_burst"}).outcomes[0]
    assert out.ok is False, f"能量不足应被拒，got {out}"
    assert "能量不足" in out.message
    assert eng.battle_state()["player"]["mp"] == 100, "被拒不应扣 MP"
    assert int(eng.battle_state()["action_seq"]) == seq_before, \
        "CTB R-6：被拒行动不应推进行动条"
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 1, "water": 0, "wind": 0}, \
        f"被拒能量不变，got {rs['element_energy']}"


def test_element_mage_combo_no_match_rejected() -> None:
    """元素法师：总量满足但池分布不匹配任何组合行 → 被拒不耗能量。

    CTB 迁移（2026-09-10）：R-6 被拒 = 零时间成本（`action_seq` 不前进）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 1, "water": 1, "wind": 0}},
        "enemy": {},
    }
    seq_before = int(eng.battle_state()["action_seq"])
    out = eng.player_act({"type": "skill", "skill_id": "elemental_burst"}).outcomes[0]
    assert out.ok is False, f"分布不匹配应被拒，got {out}"
    assert "组合未达成" in out.message
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 1, "water": 1, "wind": 0}, \
        f"被拒能量不变，got {rs['element_energy']}"
    assert int(eng.battle_state()["action_seq"]) == seq_before, \
        "CTB R-6：被拒行动不应推进行动条"


def test_element_mage_combo_behavior_changes_with_pool() -> None:
    """元素法师：相同爆发技随池分布不同 → 命中不同组合行（行为随组合变化）。"""
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 1, "wind": 1, "water": 0}},
        "enemy": {},
    }
    out = eng.do_action("player", {"type": "skill", "skill_id": "elemental_burst"})
    assert out.ok is True, f"火焰风暴应命中，got {out.message}"
    assert out.combo_result is not None
    assert out.combo_result.get("row") == "火焰风暴", f"组合名应=火焰风暴，got {out.combo_result}"
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 0, "water": 0, "wind": 0}, \
        f"火焰风暴应耗 fire1+wind1，got {rs}"
    assert eng.battle_state()["player"]["mp"] == 84, "双耗 MP16 应扣"


def test_element_mage_burst_cooldown_blocks_next_turn() -> None:
    """元素法师：爆发冷却 1 → 下次行动不可连续爆发（被拒）。

    CTB 迁移（2026-09-10）：冷却窗口按持有者行动次数计时；沿用 `player_act`
    推进（旧「下一回合」→ CTB「下一次玩家行动」）。二次爆发 R-6 被拒 →
    零时间成本（`action_seq` 不前进）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {},
    }
    _player_turn(eng, {"type": "skill", "skill_id": "elemental_burst"})
    # 重新攒能量后立即再爆发 → 冷却中（combo 引擎 should_reject）
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {},
    }
    seq_before = int(eng.battle_state()["action_seq"])
    out = eng.player_act({"type": "skill", "skill_id": "elemental_burst"}).outcomes[0]
    assert out.ok is False, f"冷却中应被拒，got {out}"
    assert eng.battle_state()["player"]["mp"] == 84, "被拒不扣 MP"
    rs = _rs(eng)
    assert rs["element_energy"] == {"fire": 2, "water": 1, "wind": 0}, \
        f"被拒能量不变，got {rs['element_energy']}"
    assert int(eng.battle_state()["action_seq"]) == seq_before, \
        "CTB R-6：冷却被拒不应推进行动条"


# ---------------------------------------------------------------------------
# 场景 3：多段 hits——blade_dance 3 段伤害战报
#
# CTB 迁移（2026-09-10）：本场景验证「单次结算的段级内容」（与时间轴正交），
# 沿用 `do_action`（平移的单次结算入口）；不涉及旧回合推进语义，无需改扫描口径。
# ---------------------------------------------------------------------------

def test_blade_dance_three_segments_in_action_record() -> None:
    """多段：blade_dance hits=3 → action_record 3 段独立记录。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    out = eng.do_action("player", {"type": "skill", "skill_id": "blade_dance",
                                   "segments": [{"hit": True, "mult": 1.0},
                                                {"hit": True, "mult": 1.0},
                                                {"hit": True, "mult": 1.0}]})
    assert out.ok is True, f"blade_dance 应成功，got {out}"
    rec = eng.battle_state()["action_record"]
    dance = [e for e in rec if e["action"] == "skill"]
    assert len(dance) == 3, f"hits=3 应 3 段记录，got {len(dance)}"
    # 每段独立判定（命中/会心/格挡逐段 rating + 段伤害）
    for seg in dance:
        assert seg["rating"]["hit"] is True, f"段应命中，got {seg}"
        assert seg["damage"]["final"] > 0, f"每段应有伤害，got {seg['damage']}"
    # MP 只扣一次（1 次施放 1 次消耗）
    assert eng.battle_state()["player"]["mp"] == 88, \
        f"MP 应只扣 12，got {eng.battle_state()['player']['mp']}"


def test_blade_dance_segments_total_damage() -> None:
    """多段：3 段伤害累计 = outcome 总伤害（raw/final 聚合）。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    hp_before = eng.battle_state()["enemy"]["hp"]
    out = eng.do_action("player", {"type": "skill", "skill_id": "blade_dance",
                                   "segments": [{"hit": True, "mult": 1.0},
                                                {"hit": True, "mult": 1.0},
                                                {"hit": True, "mult": 1.0}]})
    assert out.ok is True
    # M13 批17 路17C：多段真实生效——怪物掉血 = 段级合计（146），
    # outcome.final_damage 为末段值（37）；段级合计断言改口径。
    hp_after = eng.battle_state()["enemy"]["hp"]
    assert hp_after < hp_before, "多段应造成真实掉血"
    # 每段独立取整（段级 final 各自 ≥0，合计=实际掉血）
    rec = eng.battle_state()["action_record"]
    seg_sum = sum(e["damage"]["final"] for e in rec if e["action"] == "skill")
    assert seg_sum == hp_before - hp_after, \
        f"段级合计应=实际掉血，got {seg_sum} vs {hp_before - hp_after}"
    assert out.final_damage > 0


# ---------------------------------------------------------------------------
# 场景 4：集成闭环——战斗结束清零 + 快照续战
# ---------------------------------------------------------------------------

def test_battle_end_resets_rage_and_energy() -> None:
    """战斗结束（reset=battle）：怒气/元素能量同批清零。

    CTB 迁移（2026-09-10）：旧三段 `do_action("player")` → `enemy_act()` → `end_turn()`
    → 单次 `player_act`（调度器检测敌方 0 血 → 自动收尾 `BATTLE_END`）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"rage": 72, "element_energy": {"fire": 2, "water": 1, "wind": 0}},
        "enemy": {},
    }
    eng._snap["enemy"]["hp"] = 0  # type: ignore[attr-defined]
    rep = eng.player_act({"type": "normal"})
    rs = _rs(eng)
    assert rs.get("rage", 0) == 0 or "rage" not in rs, f"怒气战斗结束应清零，got {rs}"
    ee = rs.get("element_energy")
    assert ee is None or all(v == 0 for v in ee.values()), \
        f"元素能量战斗结束应清零，got {rs}"
    assert eng.battle_state()["status"] == "win", "敌人 0 血应胜利结算"
    assert rep.ended is True, "CTB：终局应由 player_act 报告 ended"


def test_snapshot_roundtrip_carries_both_segments() -> None:
    """快照 round-trip：transform_state + resource_state 双段携带续战。

    CTB 迁移（2026-09-10）：快照落点改为 CTB 边界 `after_action`（不再是
    `turn_start`/`turn_end`）；形态 remaining 按玩家行动次数计时（触发后 3）。
    """
    eng = _engine()
    eng._snap["resource_state"] = {  # type: ignore[attr-defined]
        "player": {"rage": 100, "element_energy": {"fire": 2, "water": 0, "wind": 1}},
        "enemy": {},
    }
    _player_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    snap = eng.to_snapshot(boundary="after_action")
    assert snap.get("transform_state", {}).get("form") == "berserker_form", \
        "快照应含形态"
    assert snap.get("resource_state", {}).get("player", {}).get("element_energy") == \
        {"fire": 2, "water": 0, "wind": 1}, "快照应含能量池级展开"
    eng2 = BattleEngine(defs=_skills()).set_transform_def(_transform()).from_snapshot(  # type: ignore[call-arg]
        snap, resource_registry={"rage": _RAGE, "element_energy": _ELEMENT})
    ts2 = _ts(eng2)
    assert ts2["form"] == "berserker_form" and ts2["remaining"] == 3, \
        f"恢复应带形态上下文，got {ts2}"
    rs2 = _rs(eng2)
    assert rs2["element_energy"] == {"fire": 2, "water": 0, "wind": 1}, \
        f"恢复应续战能量值，got {rs2}"
    # rage_burst energy_cost 100 → 触发后怒气 100→0（沉没），快照续战 0
    assert rs2.get("rage", 0) == 0, f"恢复应续战怒气值（狂暴沉没后 0），got {rs2}"
