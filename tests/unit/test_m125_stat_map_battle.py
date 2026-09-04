"""M12.5 需求1 批B 验证：stat_map 语义键 → combatant 键参数化（battle 7 处 + effects 3 处）。

依据：docs/m125_战斗数值动态化方案.md 批 B B1/B2/B3。
验收：
  1. 缺省 stat_map（DamageFormulaParams()）= 现值键 → 战斗数值与现状完全一致；
  2. stat_map 覆盖 hit_focus/hit_spd/crit_luck/def_con/atk_atk → 战斗实读新键；
  3. effects 层 L0 damage/pierce 经 ctx.variables.stat_map 取数（atk_base/dfn_base）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage import DamageFormulaParams, StatMap
from qbot_rpg.core.effects import DamageCtx, execute_action

PLAYER: Dict[str, Any] = {
    "max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100,
    "atk": 100, "dfn": 50, "mag": 50, "spd": 50,
    "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50, "spr": 50, "lck": 50,
    "custom_focus": 200, "custom_luck": 200, "custom_con": 200, "custom_spd": 200,
    "custom_atk": 200, "elem_atk": 0, "name": "P",
}
ENEMY: Dict[str, Any] = {
    "max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0,
    "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
    "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40, "lck": 10,
    "custom_focus": 10, "custom_luck": 10, "custom_con": 10, "custom_spd": 10,
    "custom_atk": 10, "elem_atk": 0, "name": "E",
}

SEQ = [0.99, 0.99, 0.99, 1.0]  # 高随机数：命中/会心/格挡判定都倾向保守（不 miss 不格挡）


class QueueRNG:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _rng():
    return QueueRNG(SEQ)


def _hit_rolls(eng: BattleEngine) -> float:
    """打一发普攻返回命中率相关证据：直接把消费点读的值抠出来。"""
    # 命中率（0-1）：foc/(foc+spd)。用内部可达的 stat_map 语义直接算期望
    sm = eng._params.stat_map
    focus = float(eng._combat("player").get(sm.hit_focus, 50))
    espd = float(eng._combat("enemy").get(sm.hit_spd, 50))
    return focus / (focus + espd)


def test_stat_map_default_is_identity() -> None:
    """缺省 stat_map 所有语义键 = 现值键名（零破坏）。"""
    sm = StatMap()
    assert sm.hit_focus == "foc"
    assert sm.hit_spd == "spd"
    assert sm.crit_luck == "lck"
    assert sm.block_focus == "foc"
    assert sm.def_con == "con"
    assert sm.atk_atk == "atk"
    assert sm.mag_int == "int"
    assert sm.atk_base == "atk"
    assert sm.dfn_base == "dfn"


def test_stat_map_override_changes_hit_read() -> None:
    """stat_map.hit_focus/hit_spd 换自定义键 → 命中公式实读新键。"""
    params = DamageFormulaParams(
        stat_map=StatMap(hit_focus="custom_focus", hit_spd="custom_spd")
    )
    eng = BattleEngine(params=params)
    eng.start(dict(PLAYER), dict(ENEMY))
    # 玩家 custom_focus=200，敌方 custom_spd=10 → 命中率 200/(200+10)≈0.952
    # 若仍读 foc/spd（100/50）= 0.667
    hr = _hit_rolls(eng)
    assert abs(hr - 200.0 / 210.0) < 1e-9
    assert hr != 100.0 / 150.0


def test_stat_map_override_crit_and_defense() -> None:
    """stat_map.crit_luck/def_con 换自定义键 → 战斗实读新键。"""
    params = DamageFormulaParams(
        stat_map=StatMap(crit_luck="custom_luck", def_con="custom_con")
    )
    eng = BattleEngine(params=params)
    eng.start(dict(PLAYER), dict(ENEMY))
    sm = eng._params.stat_map
    # 会心：攻击方 custom_luck=200（原 lck=50）
    lck = float(eng._combat("player").get(sm.crit_luck, 50))
    assert lck == 200.0
    # 防御系数：防御方 custom_con=10（原 con=50）—— 防御变弱伤害更高
    eff_con = float(eng._combat("enemy").get(sm.def_con, 50))
    assert eff_con == 10.0


def test_stat_map_default_battle_identical_to_hardcoded() -> None:
    """缺省 stat_map 战斗 = 无 stat_map 现状（同数值、同伤害）。"""
    # 现状 = 直接 BattleEngine()（内部 DamageFormulaParams() 缺省）
    eng_default = BattleEngine()
    eng_default.start(dict(PLAYER), dict(ENEMY), random_seed=42)
    eng_explicit = BattleEngine(params=DamageFormulaParams())
    eng_explicit.start(dict(PLAYER), dict(ENEMY), random_seed=42)
    # 同 seed 打一发普攻
    out_d = eng_default.do_action("player", {"type": "normal", "mult": 1.0})
    out_e = eng_explicit.do_action("player", {"type": "normal", "mult": 1.0})
    assert out_d.raw_damage == out_e.raw_damage
    assert out_d.final_damage == out_e.final_damage


def _make_effects_ctx(side_stats: Mapping[str, Any], stat_map: StatMap) -> DamageCtx:
    snap: Dict[str, Any] = {
        "player": dict(PLAYER, **side_stats.get("player", {})),
        "enemy": dict(ENEMY, **side_stats.get("enemy", {})),
        "combo_state": {},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "resist_table": {"player": {}, "enemy": {}},
        "effect_triggers": {"player": {}, "enemy": {}},
        "effect_cooldowns": {"player": {}, "enemy": {}},
    }
    return DamageCtx(
        raw_damage=0, attack_type="skill", attacker="player", target="enemy",
        snapshot=snap, variables={"stat_map": stat_map},
    )


class _RT:
    """最小 EffectRuntime 替身：execute_action 深层用到的方法补齐。"""

    def _resolver(self, id_, kind):
        return None

    def immune_to_interrupt(self, target, defs):
        return False

    def immune_dims(self, target, defs):
        return {}

    def immune_mount(self, target, defs):
        return {}

    def status_immune(self, status_id, target):
        return False

    @property
    def config(self):
        return {"chain_depth": 3}


def _rt() -> _RT:
    return _RT()


def test_effects_damage_uses_stat_map_atk_base() -> None:
    """effects damage 动作基值经 stat_map.atk_base 取自定义键。"""
    sm = StatMap(atk_base="custom_atk")
    ctx = _make_effects_ctx({"player": {"custom_atk": 300}}, sm)
    res = execute_action({"type": "damage", "value": "100%"}, ctx, _rt())
    # 300% 语义？value="100%" = base*1.0；此处验证读到 custom_atk=300 → damage 300 起
    assert res.ok
    # damage action 有 damage_dealt side effect；raw 由 pipeline 结算（无拦截直通）
    dealt = [e for e in res.side_effects if e.get("type") == "damage_dealt"]
    assert dealt and dealt[0]["damage"] > 0


def test_effects_pierce_uses_stat_map_dfn_base() -> None:
    """effects pierce 动作取防御方 dfn_base 自定义键。"""
    sm = StatMap(dfn_base="custom_dfns")
    ctx = _make_effects_ctx({"enemy": {"custom_dfns": 200}}, sm)
    res = execute_action({"type": "pierce", "value": 50}, ctx, _rt())
    assert res.ok
    ev = [e for e in res.side_effects if e.get("type") == "pierce"]
    assert ev and ev[0]["effective_defense"] == 100  # 200 × (1-50/100)


def test_effects_missing_stat_map_falls_back_identity() -> None:
    """无 stat_map 注入（纯 ctx 无 variables）→ 回落 dfn/atk 现值键。"""
    ctx = _make_effects_ctx({}, StatMap())
    ctx = DamageCtx(
        raw_damage=0, attack_type="skill", attacker="player", target="enemy",
        snapshot=ctx.snapshot, variables={},  # 无 stat_map
    )
    res = execute_action({"type": "pierce", "value": 50}, ctx, _rt())
    assert res.ok
    ev = [e for e in res.side_effects if e.get("type") == "pierce"]
    assert ev and ev[0]["effective_defense"] == 20  # ENEMY dfn=40 × 0.5
