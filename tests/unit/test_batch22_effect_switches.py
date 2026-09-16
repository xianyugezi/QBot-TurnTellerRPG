"""批22 · B2/D2：定向压制开关 `ignore_shield` / `ignore_immune`（并入 effects，不升技能字段）。

覆盖：
  - effects 字段元数据登记 + 编辑器可见（接口断言）；
  - 管线级消费：置真 → ②护盾吸收 / ⑤免疫判定整段跳过（修前修后数值对照）；
  - 效果载体：`execute_action({type:"damage", ignore_shield:true})` 生效；
  - D2：怪物攻击 effects 带 ignore_shield → 玩家护盾不被消耗（引擎级）；
  - 回归：开关缺省/False 时既有护盾/免疫行为逐字段一致。

测试只建临时对象 / 临时包，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.core.effects import DamageCtx, DamagePipeline, EffectRuntime, execute_action
from qbot_rpg.web import api

PIPE = DamagePipeline()


def _defenses() -> dict:
    return {
        "mitigation": [],
        "shield": {"value": 0, "remaining": 0, "turns": 0, "max": 0},
        "reflect": {"value": 0, "pct": True, "active": False},
        "absorb": {"value": 0, "pct": True, "record": 0, "active": False},
        "fatal_immune": {"count": 0, "max": 0},
        "non_fatal_immune": {"active": False, "count": 0},
        "guts": {"count": 0, "max": 0},
        "immune": {"status": False, "damage": False, "interrupt": False, "all": False,
                   "block_debuff": True},
        "mount": {"remaining": 0},
    }


def _snapshot(enemy_hp: int = 1000) -> dict:
    return {
        "session_type": "battle", "turn": 1,
        "player": {"max_hp": 1000, "hp": 1000, "atk": 100, "name": "p", "defenses": _defenses()},
        "enemy": {"max_hp": 1000, "hp": enemy_hp, "atk": 100, "name": "e", "defenses": _defenses()},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "resist_table": {"player": {}, "enemy": {}},
        "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}},
                            "enemy": {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {"player": {}, "enemy": {}},
        "formula_state": {},
    }


def _ctx(snap, raw, variables=None):
    return DamageCtx(raw_damage=raw, attack_type="skill", attacker="player", target="enemy",
                     snapshot=snap, variables=dict(variables or {}))


# ---------------------------------------------------------------------------
# B2 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_b2_metadata_registered() -> None:
    fields = default_field_meta_table().module("effects").fields
    for k in ("ignore_shield", "ignore_immune"):
        fm = fields.get(k)
        assert fm is not None, f"effects 缺 {k} 登记"
        assert fm.type == "bool" and fm.label
    subgroups = default_field_meta_table().module("effects").field_subgroups
    assert subgroups.get("ignore_shield") == "behavior"
    assert subgroups.get("ignore_immune") == "behavior"


def test_b2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_b2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_b2", "version": "1", "schema_version": 1, "modules": ["effects"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "effects.json").write_text(json.dumps([
        {"id": "pierce_shield", "name": "破盾斩", "type": "damage",
         "ignore_shield": True, "ignore_immune": False}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_b2", "effects", "pierce_shield", root=tmp_path)
    by = {f["key"]: f for f in detail["fields"]}
    assert by["ignore_shield"]["present"] is True
    assert by["ignore_shield"]["type"] == "bool"
    assert by["ignore_immune"]["present"] is True


# ---------------------------------------------------------------------------
# B2 管线级消费：护盾 / 免疫整段跳过（修前修后对照）
# ---------------------------------------------------------------------------
def test_b2_ignore_shield_skips_absorption() -> None:
    snap0 = _snapshot()
    snap0["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    r0 = PIPE.damage_pipeline(_ctx(snap0, 100), EffectRuntime())
    assert r0.final_damage == 70 and snap0["enemy"]["defenses"]["shield"]["remaining"] == 0

    snap1 = _snapshot()
    snap1["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    r1 = PIPE.damage_pipeline(_ctx(snap1, 100, {"ignore_shield": True}), EffectRuntime())
    assert r1.final_damage == 100
    assert snap1["enemy"]["defenses"]["shield"]["remaining"] == 30  # 未被消耗
    assert not [e for e in r1.side_effects if e["type"] == "shield_absorbed"]


def test_b2_ignore_immune_skips_immunity() -> None:
    snap0 = _snapshot()
    snap0["enemy"]["defenses"]["immune"]["damage"] = True
    r0 = PIPE.damage_pipeline(_ctx(snap0, 100), EffectRuntime())
    assert r0.final_damage == 0 and r0.target_hp == 1000

    snap1 = _snapshot()
    snap1["enemy"]["defenses"]["immune"]["damage"] = True
    r1 = PIPE.damage_pipeline(_ctx(snap1, 100, {"ignore_immune": True}), EffectRuntime())
    assert r1.final_damage == 100 and r1.target_hp == 900

    # 致命免疫同样被跳过
    snap2 = _snapshot(enemy_hp=50)
    snap2["enemy"]["defenses"]["fatal_immune"] = {"count": 1, "max": 1}
    assert PIPE.damage_pipeline(_ctx(snap2, 100), EffectRuntime()).final_damage == 0
    snap3 = _snapshot(enemy_hp=50)
    snap3["enemy"]["defenses"]["fatal_immune"] = {"count": 1, "max": 1}
    assert PIPE.damage_pipeline(_ctx(snap3, 100, {"ignore_immune": True}),
                                EffectRuntime()).final_damage == 100


def test_b2_effect_carrier_execute_action() -> None:
    """效果载体：effect type=damage 上的开关经 execute_action 生效。"""
    snap = _snapshot()
    snap["enemy"]["defenses"]["shield"] = {"value": 50, "remaining": 50, "turns": 2, "max": 50}
    base = DamageCtx(raw_damage=0, attack_type="skill", attacker="player", target="enemy",
                     snapshot=snap, variables={})
    execute_action({"type": "damage", "value": 40, "target": "enemy"}, base, EffectRuntime())
    assert snap["enemy"]["defenses"]["shield"]["remaining"] == 10  # 无开关：正常吸收

    snap2 = _snapshot()
    snap2["enemy"]["defenses"]["shield"] = {"value": 50, "remaining": 50, "turns": 2, "max": 50}
    base2 = DamageCtx(raw_damage=0, attack_type="skill", attacker="player", target="enemy",
                      snapshot=snap2, variables={})
    execute_action({"type": "damage", "value": 40, "target": "enemy", "ignore_shield": True},
                   base2, EffectRuntime())
    assert snap2["enemy"]["defenses"]["shield"]["remaining"] == 50  # 开关：跳过


def test_b2_regression_flag_false_identical() -> None:
    snap0 = _snapshot()
    snap0["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    r0 = PIPE.damage_pipeline(_ctx(snap0, 100), EffectRuntime())
    snap1 = _snapshot()
    snap1["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    r1 = PIPE.damage_pipeline(_ctx(snap1, 100, {"ignore_shield": False, "ignore_immune": False}),
                              EffectRuntime())
    assert (r0.final_damage, r0.target_hp) == (r1.final_damage, r1.target_hp)
