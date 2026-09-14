"""最低伤害保底（settings.battle.min_damage）单元测试 · 2026-09-14 用户拍板。

语义口径（原文见 docs/细化/细化_3h_settings通用设置.md §九）：
  - 新增设置项 `settings.battle.min_damage`（int，默认 0 = 关闭，0 时零行为变化）。
  - 一次「命中并产生伤害」的实例：最终伤害（所有增伤/减伤/防御结算之后）若 <
    min_damage → 抬到 min_damage；若 ≥ → 不变。
  - 不适用：闪避/未命中/无伤害实例（没有伤害对象时不产生伤害）——不因保底造伤。
  - 双向：玩家打怪、怪打玩家都生效。
  - 顺序：保底在拦截链 ①减伤 之后、②护盾吸收 之前（先取保底、再走护盾吸收；
    护盾可以先吃掉保底伤害）。
  - 不越权：floor 而非 set（只抬不压）；不影响暴击/命中/格挡等既有判定。

铁律：零 NoneBot import；确定性（random_seed 固定）。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle_config import BATTLE_SETTINGS_KEYS, resolve_battle_settings
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.core.battle import BattleEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

_HUGE_CON = 999999


def _engine(config: Dict[str, Any] | None = None,
            defs: Dict[str, Any] | None = None,
            player_con: int = 50, enemy_con: int = _HUGE_CON,
            enemy_atk: int = 5, player_atk: int = 50) -> BattleEngine:
    """玩家 vs 高体质石像怪：默认 raw 伤害 = 1（可被保底观察）。"""
    eng = BattleEngine(defs=defs or {}, config=config)
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": player_atk, "dfn": 50, "con": player_con, "spd": 10, "name": "玩家"},
        {"hp": 5000, "max_hp": 5000, "mp": 0, "max_mp": 0,
         "atk": enemy_atk, "dfn": 50, "con": enemy_con, "spd": 8, "name": "石像怪"},
        random_seed=42,
    )
    return eng


def _normal(mult: float = 1.0) -> Dict[str, Any]:
    return {"type": "normal", "attack_type": "slash", "mult": mult}


def _player_outcome(eng: BattleEngine) -> Any:
    rep = eng.player_act(_normal())
    return next(o for o in rep.outcomes if o.actor == "player")


def _enemy_outcome(eng: BattleEngine) -> Any:
    rep = eng.player_act(_normal())
    return next(o for o in rep.outcomes if o.actor == "enemy")


def _events(outcome: Any, type_: str) -> list:
    return [e for e in (outcome.side_effects or ()) if e.get("type") == type_]


# ================================================================== 1. 默认 0 = 零行为变化

def test_default_and_zero_no_behavior_change():
    """未配置 / min_damage=0：伤害与无保底基线一致，且不产生保底事件。"""
    base = _player_outcome(_engine())
    zero = _player_outcome(_engine({"min_damage": 0}))
    assert base.final_damage == 1, "基线：高防目标下 raw 应为 1"
    assert zero.final_damage == base.final_damage == 1
    assert _events(base, "min_damage") == []
    assert _events(zero, "min_damage") == []


def test_pipeline_zero_is_noop():
    """拦截链入口 direct：min_damage 缺省/0 → 原样传递。"""
    eng = _engine()
    assert eng.resolve_damage("player", "enemy", 9).final_damage == 9
    assert eng.resolve_damage("player", "enemy", 9,
                              variables={"min_damage": 0}).final_damage == 9


# ================================================================== 2. 低于保底 → 抬起

def test_below_floor_raised_to_floor():
    """raw=1 < 5 → 抬到 5；保底事件记录 from/to（floor 而非 set）。"""
    out = _player_outcome(_engine({"min_damage": 5}))
    assert out.final_damage == 5
    evs = _events(out, "min_damage")
    assert evs and evs[0]["from"] == 1 and evs[0]["to"] == 5


# ================================================================== 3. 等于 / 高于 → 不变

def test_equal_floor_unchanged():
    eng = _engine()
    assert eng.resolve_damage("player", "enemy", 5,
                              variables={"min_damage": 5}).final_damage == 5


def test_above_floor_unchanged():
    """高于保底 → 不被压低（floor 只抬不压，绝不 set）。"""
    eng = _engine()
    res = eng.resolve_damage("player", "enemy", 999,
                             variables={"min_damage": 5})
    assert res.final_damage == 999
    assert _events(res, "min_damage") == []


# ================================================================== 4. 无伤害实例不适用

def test_no_damage_object_not_floored():
    """没有伤害对象（raw=0）→ 保底不为其造伤。"""
    eng = _engine({"min_damage": 5})
    res = eng.resolve_damage("player", "enemy", 0, variables={"min_damage": 5})
    assert res.final_damage == 0
    assert _events(res, "min_damage") == []


def test_position_miss_not_floored():
    """方位未命中（闪避/未命中一类）：无伤害对象 → 保底不生效、不扣血。"""
    eng = _engine({"min_damage": 5})
    eng._snap["combat_position"] = {
        "player": {"side": "front", "height": "air"},
        "enemy": {"side": "front", "height": "ground"},
    }
    hp_before = eng._snap["player"]["hp"]
    out = eng.do_action("enemy", {"type": "normal", "mult": 1.0,
                                  "position_rule": {"height": ["ground"]}})
    assert out is not None and out.hit is False
    assert out.final_damage == 0 and out.raw_damage == 0
    assert _events(out, "min_damage") == []
    assert eng._snap["player"]["hp"] == hp_before


def test_zero_mult_segment_not_floored():
    """0 倍率段（无伤害实例）跳过整条命中/拦截链 → 保底不生效。"""
    eng = _engine({"min_damage": 5})
    rep = eng.player_act({"type": "normal", "attack_type": "slash", "mult": 0.0})
    o = next(x for x in rep.outcomes if x.actor == "player")
    assert o.final_damage == 0
    assert _events(o, "min_damage") == []


# ================================================================== 5. 双向生效

def test_player_to_enemy_floored():
    out = _player_outcome(_engine({"min_damage": 5}))
    assert out.actor == "player" and out.final_damage == 5


def test_enemy_to_player_floored():
    """怪打玩家同样吃保底（玩家高体质 → 怪 raw=1 → 抬到 5）。"""
    eng = _engine({"min_damage": 5}, player_con=_HUGE_CON, enemy_con=50)
    out = _enemy_outcome(eng)
    assert out.actor == "enemy" and out.final_damage == 5
    evs = _events(out, "min_damage")
    assert evs and evs[0]["to"] == 5


# ================================================================== 6. 与减伤 / 护盾的先后

def test_floor_applied_after_mitigation():
    """①减伤 结算后取保底：50% 减伤把 raw=1 压到 0，保底仍抬到 5。"""
    defs = {"test_mitigation": {"type": "mitigation", "value": 50, "scope": "all"}}
    eng = _engine({"min_damage": 5}, defs=defs)
    eng.set_effect_ids("enemy", ["test_mitigation"])
    out = _player_outcome(eng)
    assert out.final_damage == 5, "保底在减伤之后 → 减伤不能把伤害压到保底以下"


def test_floor_before_shield_shield_can_eat_it():
    """先取保底、再走护盾：护盾吃掉保底后的 5 点 → final=0，盾剩余 95，保底事件仍在。"""
    defs = {"test_shield": {"type": "shield", "value": 100}}
    eng = _engine({"min_damage": 5}, defs=defs)
    eng.set_effect_ids("enemy", ["test_shield"])
    out = _player_outcome(eng)
    assert _events(out, "min_damage"), "保底先于护盾结算，事件应记录"
    shield_evs = _events(out, "shield_absorbed")
    assert shield_evs, "护盾应吸收保底后的伤害"
    assert shield_evs[0]["absorbed"] == 5 and shield_evs[0]["remaining"] == 95, \
        "护盾按保底后的 5 点吸收 → 剩余 95"
    assert out.final_damage == 0, "护盾可以先吃掉保底伤害"


# ================================================================== 7. 不改变暴击/命中判定

def test_floor_does_not_change_crit_hit_block():
    """同一随机种子：min_damage 只改伤害值，不改 命中/会心档/格挡 判定。"""
    off = _player_outcome(_engine())
    on = _player_outcome(_engine({"min_damage": 5}))
    assert on.hit == off.hit
    assert on.crit == off.crit
    assert on.blocked == off.blocked
    assert on.final_damage == 5 and off.final_damage == 1


def test_rendered_message_uses_floored_value():
    """模板渲染取 ActionOutcome.final_damage → 保底后的值被正确渲染（不改模板）。"""
    from qbot_rpg.core.message_format.battle_render import _render_player_hit

    out = _player_outcome(_engine({"min_damage": 5}))
    line = _render_player_hit(out, action_phrase="攻击", target_max_hp=5000)
    assert "造成 5 伤害" in line
    assert "造成 1 伤害" not in line


# ============================ 8. 设置项装配（settings → engine config）

def test_battle_config_whitelist_and_validation():
    assert "min_damage" in BATTLE_SETTINGS_KEYS
    assert resolve_battle_settings({"battle": {"min_damage": 7}})["min_damage"] == 7
    assert resolve_battle_settings({"battle": {"min_damage": 0}})["min_damage"] == 0
    # 坏值 → 忽略（回落引擎默认 0），绝不抛错
    for bad in (None, "5", 3.5, True, -1):
        assert "min_damage" not in resolve_battle_settings({"battle": {"min_damage": bad}}), bad


def test_field_meta_registration():
    """框架 settings 段登记 min_damage：int、默认 0、软标注。"""
    fields = default_field_meta_table().modules["settings"].fields
    fm = fields["battle"].children["min_damage"]
    assert fm.type == "int"
    assert fm.default == 0
    assert fm.soft_label is True
    assert "最低伤害" in fm.label


def test_veinborn_pack_declares_zero():
    """veniborn 包 settings.json battle.min_damage=0（保持现状可用）→ 引擎零覆盖。"""
    import json
    from pathlib import Path

    path = Path("content/veinborn/settings.json")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["battle"]["min_damage"] == 0
    assert resolve_battle_settings(raw)["min_damage"] == 0
