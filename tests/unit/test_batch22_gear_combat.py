"""批22 · A3/D1：常驻战斗词条（吸血/免伤/物穿/法穿）——注册表 + 战斗桥 + 数值级引擎证据。

覆盖：
  - `data.gear_stats` 注册表分层（COMBAT）+ 聚合路由 + combatant 桥（A3）；
  - items/equipment 字段元数据（A3）+ enemies.stats 同名键（D1，同一注册表）；
  - 战斗结算真生效：穿透抬高伤害 / 免伤压低伤害 / 吸血回血（修前修后对照）；
  - 回归：无这些键时战斗数值逐字段一致（对拍断言）。

测试只建临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage import channel_phys, defense_factor, effective_con
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    COMBAT_TO_COMBATANT,
    GEAR_COMBAT_KEYS,
    GEAR_COMBAT_PCT_KEYS,
    GEAR_COMBAT_VALUE_KEYS,
    GEAR_NUMERIC_KEYS,
    combatant_updates,
    extract_bonus,
    route_bonus_into,
)

A3_PCT = ("absorb_hp", "immune_dmg", "pierce_pct", "mag_pierce_pct")
A3_VAL = ("pierce_val", "mag_pierce_val")
A3_ALL = A3_PCT + A3_VAL

PLAYER = {"max_hp": 500, "hp": 300, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50,
          "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
         "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
         "lck": 10, "elem_atk": 0, "name": "E"}
SEQ = [0.5, 0.5, 0.5, 1.0]


class _QueueRNG:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _engine(player: Mapping[str, Any], enemy: Mapping[str, Any]) -> BattleEngine:
    eng = BattleEngine()
    eng._rng = _QueueRNG(SEQ)
    eng.start(copy.deepcopy(dict(player)), copy.deepcopy(dict(enemy)), random_seed=7)
    return eng


def _player_rec(eng: BattleEngine) -> Mapping[str, Any]:
    return [r for r in eng.battle_state()["action_record"] if r["actor"] == "player"][-1]


def _enemy_rec(eng: BattleEngine) -> Mapping[str, Any]:
    return [r for r in eng.battle_state()["action_record"] if r["actor"] == "enemy"][-1]


def _phys_expected(eng: BattleEngine, rec: Mapping[str, Any], *, magic: bool = False,
                   def_con_delta: float = 0.0, pierce_override: float | None = None) -> int:
    """按引擎同口径复算物理通道（用于穿透数值断言）。"""
    p = eng._params
    ac = eng._combat("player")
    tc = eng._combat("enemy")
    r = rec["rating"]
    attack = float(ac.get(p.stat_map.atk_atk, 0))
    if magic:
        attack = float(ac.get(p.stat_map.mag_int, ac.get("mag", attack)))
    attack *= p.base_attack_mult
    con = max(0.0, float(tc.get(p.stat_map.def_con, 50)) - def_con_delta)
    pierce = float(r["pierce"]) if pierce_override is None else pierce_override
    df = defense_factor(effective_con(con, pierce), k=p.defense.k)
    mdr = float(tc.get("monster_def_rate", p.monster_def_rate) or p.monster_def_rate)
    return channel_phys(attack, float(r["multi"]), float(r["weak_type"]),
                        float(r["crit_mult"]), df, monster_def_rate=mdr)


# ---------------------------------------------------------------------------
# A3 注册表 / 聚合 / 桥
# ---------------------------------------------------------------------------
def test_a3_registry_layering() -> None:
    for k in A3_ALL:
        assert k in GEAR_COMBAT_KEYS, f"{k} 应在 COMBAT 分层（战斗直读）"
        assert k in GEAR_NUMERIC_KEYS
    assert set(A3_PCT) <= set(GEAR_COMBAT_PCT_KEYS)
    assert set(A3_VAL) <= set(GEAR_COMBAT_VALUE_KEYS)
    mapped = {src for src, _dst, _cap in COMBAT_TO_COMBATANT}
    assert set(A3_ALL) <= mapped


def test_a3_extract_and_route_keeps_pct_combat_in_flat() -> None:
    bonus = extract_bonus({"absorb_hp": 20, "pierce_pct": 30, "pierce_val": 8,
                           "dfn_pct": 5, "atk": 3, "crit": 0})
    assert bonus.get("pierce_pct") == 30.0 and bonus.get("dfn_pct") == 5.0
    assert "crit" not in bonus  # 0 值排除
    flat: dict = {}
    pct: dict = {}
    route_bonus_into(bonus, flat, pct)
    assert flat.get("pierce_pct") == 30.0        # COMBAT 的 _pct 键不进属性管线
    assert "pierce" not in pct
    assert pct.get("dfn") == 5.0                 # 既有 PCT 键口径不变
    assert flat.get("absorb_hp") == 20.0 and flat.get("pierce_val") == 8.0


def test_a3_combatant_updates_caps() -> None:
    up = combatant_updates({"absorb_hp": 999, "immune_dmg": -5, "pierce_val": 12,
                            "pierce_pct": 250, "mag_pierce_val": 3, "mag_pierce_pct": 20})
    assert up["absorb_hp"] == 100 and up["pierce_pct"] == 100 and up["mag_pierce_pct"] == 20
    assert up["immune_dmg"] == 0.0              # 负值经封顶归 0（非负下限）
    assert up["pierce_val"] == 12 and up["mag_pierce_val"] == 3


def test_a3_pvp_bridge_into_combatant() -> None:
    player = {
        "qid": "p1", "name": "P", "level": 5, "hp": 100, "max_hp": 500, "mp": 50, "max_mp": 100,
        "attributes": {"base": {"atk": 100.0, "con": 50.0}, "bonus": {
            "flat": {"pierce_val": 10, "absorb_hp": 25, "immune_dmg": 10,
                     "pierce_pct": 30, "mag_pierce_val": 5, "mag_pierce_pct": 20}, "pct": {}},
            "temp": {}, "cond": {}},
    }
    c = _combatant_of(player)
    assert c["pierce_val"] == 10 and c["absorb_hp"] == 25 and c["immune_dmg"] == 10
    assert c["pierce_pct"] == 30 and c["mag_pierce_val"] == 5 and c["mag_pierce_pct"] == 20


def test_a3_metadata_items_equipment() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fields = tbl.module(mod).fields
        for k in A3_ALL:
            fm = fields.get(k)
            assert fm is not None, f"{mod}.{k} 缺登记"
            assert fm.label
            assert fm.unit == ("%" if k in A3_PCT else "点")
        assert fields["pierce_pct"].range_max == 100
        assert fields["pierce_val"].range_max == 99999


# ---------------------------------------------------------------------------
# A3 引擎消费：穿透抬高伤害（数值级，复算对齐）
# ---------------------------------------------------------------------------
def test_a3_engine_pierce_val_raises_damage() -> None:
    eng0 = _engine(PLAYER, ENEMY)
    eng0._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base_ch = _player_rec(eng0)["damage"]["ch_phys"]

    p = dict(PLAYER, pierce_val=10)
    eng1 = _engine(p, ENEMY)
    eng1._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    rec = _player_rec(eng1)
    assert rec["damage"]["ch_phys"] == _phys_expected(eng1, rec, def_con_delta=10)
    assert rec["damage"]["ch_phys"] > base_ch, (rec["damage"]["ch_phys"], base_ch)


def test_a3_engine_pierce_pct_raises_damage() -> None:
    eng0 = _engine(PLAYER, ENEMY)
    eng0._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base_ch = _player_rec(eng0)["damage"]["ch_phys"]

    p = dict(PLAYER, pierce_pct=30)
    eng1 = _engine(p, ENEMY)
    eng1._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    rec = _player_rec(eng1)
    assert rec["rating"]["pierce"] == 0.3
    assert rec["damage"]["ch_phys"] == _phys_expected(eng1, rec, pierce_override=0.3)
    assert rec["damage"]["ch_phys"] > base_ch


def test_a3_engine_magic_pierce_only_on_magic() -> None:
    eng_p = _engine(dict(PLAYER, mag_pierce_val=10, mag_pierce_pct=30), ENEMY)
    eng_p._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base = _engine(PLAYER, ENEMY)
    base._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    # 物理攻击不吃法穿
    assert _player_rec(eng_p)["damage"]["ch_phys"] == _player_rec(base)["damage"]["ch_phys"]

    eng_m = _engine(dict(PLAYER, mag_pierce_val=10, mag_pierce_pct=30), ENEMY)
    eng_m._resolve_damage_action("player", {"type": "normal", "mult": 1.0,
                                            "attack_type": "magic"})
    rec = _player_rec(eng_m)
    assert rec["rating"]["pierce"] == 0.3
    assert rec["damage"]["ch_phys"] == _phys_expected(eng_m, rec, magic=True,
                                                      def_con_delta=10, pierce_override=0.3)


def test_a3_engine_immune_dmg_reduces_damage() -> None:
    base = _engine(PLAYER, ENEMY)
    base._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base_final = _player_rec(base)["damage"]["final"]

    e = dict(ENEMY, immune_dmg=25)
    eng = _engine(PLAYER, e)
    eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    rec = _player_rec(eng)
    assert rec["damage"]["final"] == max(0, round(base_final * 0.75))


def test_a3_engine_absorb_hp_heals_attacker() -> None:
    base = _engine(PLAYER, ENEMY)
    base._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base_hp = base.battle_state()["player"]["hp"]
    base_final = _player_rec(base)["damage"]["final"]

    p = dict(PLAYER, absorb_hp=50)
    eng = _engine(p, ENEMY)
    eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    hp_with = eng.battle_state()["player"]["hp"]
    assert hp_with - base_hp == base_final * 50 // 100


# ---------------------------------------------------------------------------
# A3 回归：无这些键时战斗数值逐字段一致
# ---------------------------------------------------------------------------
def test_a3_regression_bridge_identical_when_absent() -> None:
    """对拍：属性 flat 不含新键 vs 含全 0 值 → combatant 逐字段完全一致（0 被桥过滤）。"""
    def _player(flat):
        return {"qid": "p", "name": "P", "level": 1, "hp": 100, "max_hp": 100, "mp": 10,
                "max_mp": 10, "attributes": {"base": {"atk": 100.0, "con": 50.0},
                                             "bonus": {"flat": flat, "pct": {}},
                                             "temp": {}, "cond": {}}}
    a = _combatant_of(_player({}))
    b = _combatant_of(_player({k: 0 for k in A3_ALL}))
    assert a == b


def test_a3_regression_battle_numbers_identical_when_absent() -> None:
    """对拍：战斗体不含新键 vs 含全 0 值 → 伤害/血量/判定逐字段一致。"""
    def _run(extra):
        eng = _engine(dict(PLAYER, **extra), ENEMY)
        eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
        rec = _player_rec(eng)
        st = eng.battle_state()
        return (rec["damage"]["final"], rec["damage"]["ch_phys"],
                st["player"]["hp"], st["enemy"]["hp"],
                {k: rec["rating"].get(k) for k in ("crit", "blocked", "pierce", "multi")})

    assert _run({}) == _run({k: 0 for k in A3_ALL})
