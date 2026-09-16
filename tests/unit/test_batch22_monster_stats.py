"""批22 · D1：怪物常驻吸血/穿透/免伤——**复用 A3 的键**（同一注册表/桥），不新造第二套。

覆盖：enemies.stats 元数据同键 + `_enemy_combatant` 走同一 `combatant_updates` 桥（含封顶）
+ 数字级引擎证据（怪物吸血回血 / 免伤减伤）。测试只建临时对象，不写真实内容包。
"""
from __future__ import annotations

import copy
from typing import Any, Mapping

from qbot_rpg.commands.battle_launch_commands import _enemy_combatant
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.core.battle import BattleEngine

A3_ALL = ("absorb_hp", "immune_dmg", "pierce_val", "pierce_pct",
          "mag_pierce_val", "mag_pierce_pct")

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


def _rec(eng: BattleEngine, actor: str) -> Mapping[str, Any]:
    return [r for r in eng.battle_state()["action_record"] if r["actor"] == actor][-1]


def test_d1_enemy_stats_metadata_reuses_registry_keys() -> None:
    children = default_field_meta_table().module("enemies").fields["stats"].children
    for k in A3_ALL:
        assert k in children, f"enemies.stats 缺 {k}（应与 A3 同键）"
        assert children[k].label
    assert children["pierce_pct"].unit == "%"
    assert children["pierce_val"].unit == "点"


def test_d1_enemy_combatant_bridge_and_caps() -> None:
    comb = _enemy_combatant({"id": "m", "name": "怪", "stats": {
        "hp": 300, "con": 20, "absorb_hp": 25, "pierce_val": 7, "pierce_pct": 40,
        "immune_dmg": 10, "mag_pierce_val": 3, "mag_pierce_pct": 20}})
    assert comb["absorb_hp"] == 25 and comb["immune_dmg"] == 10
    assert comb["pierce_val"] == 7 and comb["pierce_pct"] == 40
    assert comb["mag_pierce_val"] == 3 and comb["mag_pierce_pct"] == 20
    capped = _enemy_combatant({"id": "m", "stats": {"hp": 10, "absorb_hp": 999,
                                                    "pierce_pct": 1000}})
    assert capped["absorb_hp"] == 100 and capped["pierce_pct"] == 100


def test_d1_enemy_absorb_hp_and_immune_dmg_effective() -> None:
    """怪物侧同名键真生效：吸血回血 / 免伤减伤（与玩家装备词条同桥同口径）。"""
    e0 = _enemy_combatant({"id": "m", "name": "E", "stats": {"hp": 400, "str": 80, "con": 50}})
    e0["hp"] = 300
    eng0 = _engine(PLAYER, e0)
    eng0._resolve_damage_action("enemy", {"type": "normal", "mult": 1.0})
    base_enemy_hp = eng0.battle_state()["enemy"]["hp"]
    base_final = _rec(eng0, "enemy")["damage"]["final"]

    e1 = _enemy_combatant({"id": "m", "name": "E",
                           "stats": {"hp": 400, "str": 80, "con": 50, "absorb_hp": 50}})
    e1["hp"] = 300
    eng1 = _engine(PLAYER, e1)
    eng1._resolve_damage_action("enemy", {"type": "normal", "mult": 1.0})
    assert eng1.battle_state()["enemy"]["hp"] - base_enemy_hp == base_final * 50 // 100

    m = _enemy_combatant({"id": "m", "name": "E",
                          "stats": {"hp": 400, "str": 80, "con": 50, "immune_dmg": 25}})
    engm = _engine(PLAYER, m)
    engm._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    base_eng = _engine(PLAYER, ENEMY)
    base_eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    assert _rec(engm, "player")["damage"]["final"] == max(
        0, round(_rec(base_eng, "player")["damage"]["final"] * 0.75))


def test_d1_editor_visible(tmp_path) -> None:
    """编辑器接口：怪物 stats 子字段可见（同一注册表键）。"""
    import json

    from qbot_rpg.web import api
    root = tmp_path / "pack_d1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_d1", "version": "1", "schema_version": 1, "modules": ["enemies"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "enemies.json").write_text(json.dumps(
        [{"id": "m", "name": "怪", "stats": {"hp": 100, "absorb_hp": 20, "pierce_pct": 15}}],
        ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_d1", "enemies", "m", root=tmp_path)
    stats = next(f for f in detail["fields"] if f["key"] == "stats")
    children = {c["key"]: c for c in stats.get("children") or []}
    assert children["absorb_hp"]["label"] == "吸血%"
    assert children["pierce_pct"]["label"] == "物穿%"
