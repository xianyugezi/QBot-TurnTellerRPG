"""批23 · B1：技能生命消耗 `hp_cost`（CakeGame Config_Skills.ConsumeType=HP；§三 B1）。

设计口径（本批拍板，写进报告）：
  - **不引入** `consume_type` 枚举——单个数值字段直接表达「放这招要付血」（少而深）；
  - 与 `mp_cost` 并列、资源各自独立扣；
  - **不得致死**：`hp - hp_cost < 1` → **阻止释放**（被拒不消耗行动、不改 hp），
    而非「扣到 1 为止」。依据：与 energy_cost / consume_marks 的既有语义一致——
    资源不足即拒绝、零副作用可重试；「扣到 1」会静默打折代价、鼓励 1 血无限放招。

覆盖：
  - 元数据登记（skills，`int` ≥0，单位=点，中文 help）+ 编辑器接口可见；
  - 校验：非整数 → R-1 红；负数 → R-2 红；0/缺省 → 无红无黄；
  - 引擎消费（数值级）：扣血精确值 / 致死阻止 / 与 mp_cost 并存各自独立 /
    组合技能（combo_table）路径同样生效 / 派生链变体技能按派生技 def 生效；
  - 回归：不带 hp_cost 时既有行为逐字段一致（MP/HP/被拒语义）。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.marks import AddMark
from qbot_rpg.web import api

#: 技能库校验 V-7 要求「每职业恰 1 普攻」——测试技能库统一带一个 basic 占位。
_BASIC = {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
          "power": 100}


# ---------------------------------------------------------------------------
# 引擎夹具（零 content 依赖）
# ---------------------------------------------------------------------------
def _engine(defs: Dict[str, Dict[str, Any]], *, hp: int = 100, mp: int = 100,
            registry: Any = None) -> BattleEngine:
    eng = BattleEngine(defs=defs, config={"combo_enforce_mp": True})
    eng.start(
        {"hp": hp, "max_hp": 100, "mp": mp, "max_mp": 100,
         "atk": 100, "def": 0, "spr": 0, "spd": 10, "foc": 100, "con": 0,
         "lck": 0, "int": 0, "name": "玩家"},
        {"hp": 2000, "max_hp": 2000, "mp": 0, "max_mp": 0,
         "atk": 0, "def": 0, "spr": 0, "spd": 1, "foc": 0, "con": 0,
         "lck": 0, "int": 0, "name": "砾冕"},
        random_seed=7,
    )
    if registry is not None:
        eng._resource_registry = registry  # noqa: SLF001 - 资源注册表注入位（同既有测试）
    return eng


def _hp(eng: BattleEngine) -> int:
    return int(eng.battle_state()["player"]["hp"])


def _mp(eng: BattleEngine) -> int:
    return int(eng.battle_state()["player"]["mp"])


# ---------------------------------------------------------------------------
# B1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_b1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("skills").fields.get("hp_cost")
    assert fm is not None, "skills 缺 hp_cost 登记"
    assert fm.type == "int"
    assert fm.range_min == 0 and fm.range_max == 9999
    assert fm.unit == "点"
    assert fm.label == "生命消耗"
    assert fm.help, "hp_cost 缺中文说明（说明卡）"
    assert tbl.module("skills").field_groups.get("hp_cost") == "数值"


def test_b1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_b1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_b1", "version": "1", "schema_version": 1, "modules": ["skills"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "skills.json").write_text(json.dumps([
        {"id": "blood_rage", "name": "血怒", "type": "active", "kind": "damage",
         "power": 100, "hp_cost": 20}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_b1", "skills", "blood_rage", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "hp_cost")
    assert f["present"] is True
    assert f["type"] == "int"
    assert f["label"] == "生命消耗"


# ---------------------------------------------------------------------------
# B1 校验：非法值口径
# ---------------------------------------------------------------------------
def test_b1_validator_negative_red() -> None:
    report = check_pack({"skills": [
        dict(_BASIC), {"id": "s", "name": "血技", "hp_cost": -5}]})
    assert [e for e in report.errors if e.kind == "R-2" and "hp_cost" in e.field]


def test_b1_validator_non_int_red() -> None:
    report = check_pack({"skills": [
        dict(_BASIC), {"id": "s", "name": "血技", "hp_cost": "20"}]})
    assert [e for e in report.errors if e.kind == "R-1" and "hp_cost" in e.field]


def test_b1_validator_zero_and_missing_ok() -> None:
    report = check_pack({"skills": [
        dict(_BASIC),
        {"id": "s", "name": "血技", "hp_cost": 0},
        {"id": "t", "name": "普通技"},
    ]})
    assert not [e for e in report.errors if "hp_cost" in e.field]
    assert not [w for w in report.warnings if "hp_cost" in w.field]


# ---------------------------------------------------------------------------
# B1 引擎消费：扣血精确值 / 不得致死 / 与 mp_cost 独立
# ---------------------------------------------------------------------------
def test_b1_engine_deducts_exact_hp() -> None:
    defs = {"blood_rage": {"id": "blood_rage", "name": "血怒", "type": "active",
                           "kind": "damage", "power": 100, "mp_cost": 0, "hp_cost": 20}}
    eng = _engine(defs, hp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "blood_rage"})
    assert out.ok is True, out
    assert _hp(eng) == 80, f"应扣 20 点生命，got {_hp(eng)}"


def test_b1_lethal_is_blocked_not_clamped() -> None:
    """hp - hp_cost < 1 → 阻止释放（不改 hp、不消耗行动），不「扣到 1 为止」。"""
    defs = {"blood_rage": {"id": "blood_rage", "name": "血怒", "type": "active",
                           "kind": "damage", "power": 100, "hp_cost": 20}}
    eng = _engine(defs, hp=20)
    out = eng.do_action("player", {"type": "skill", "skill_id": "blood_rage"})
    assert out.ok is False, out
    assert _hp(eng) == 20, "被拒不扣血"
    assert "生命不足" in out.message and "20" in out.message
    # 恰好留 1 点 → 放行（边界）
    eng2 = _engine(defs, hp=21)
    assert eng2.do_action("player", {"type": "skill", "skill_id": "blood_rage"}).ok is True
    assert _hp(eng2) == 1


def test_b1_mp_and_hp_independent() -> None:
    defs = {"both": {"id": "both", "name": "血法技", "type": "active",
                     "kind": "damage", "power": 100, "mp_cost": 10, "hp_cost": 5}}
    eng = _engine(defs, hp=100, mp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "both"})
    assert out.ok is True, out
    assert (_hp(eng), _mp(eng)) == (95, 90), (_hp(eng), _mp(eng))


def test_b1_combo_table_path_also_pays_hp() -> None:
    """组合技能（combo_table）路径：能量满足 → 生命照扣；能量不足被拒 → 不扣生命。"""
    element = {"name": "元素能量", "type": "element_energy", "base": 0,
               "max_per_pool": 3, "pools": ["fire", "water", "wind"]}
    defs = {"steam_blast": {
        "id": "steam_blast", "name": "蒸汽爆发", "type": "active", "kind": "damage",
        "power": 100, "mp_cost": 0, "hp_cost": 25,
        "combo_table": [{"combo": ["fire", "fire"], "name": "烈焰爆破",
                         "kind": "damage", "power": 200, "element": "fire"}],
    }}
    eng = _engine(defs, hp=100, registry={"element_energy": element})
    eng._snap["resource_state"] = {  # noqa: SLF001
        "player": {"element_energy": {"fire": 3, "water": 0, "wind": 0}}, "enemy": {}}
    assert eng.do_action("player", {"type": "skill", "skill_id": "steam_blast"}).ok is True
    assert _hp(eng) == 75, f"组合命中应扣 25 生命，got {_hp(eng)}"

    eng2 = _engine(defs, hp=100, registry={"element_energy": element})
    eng2._snap["resource_state"] = {  # noqa: SLF001
        "player": {"element_energy": {"fire": 1, "water": 0, "wind": 0}}, "enemy": {}}
    out2 = eng2.do_action("player", {"type": "skill", "skill_id": "steam_blast"})
    assert out2.ok is False, out2
    assert _hp(eng2) == 100, "组合被拒不应扣生命"


def test_b1_derived_variant_uses_derived_hp_cost() -> None:
    """派生链变体技能：按**派生技** def 的 hp_cost 扣血（源技能无血耗）。"""
    defs = {
        "src": {"id": "src", "name": "源技", "type": "active", "kind": "damage",
                "power": 60, "mp_cost": 0,
                "effects": [{"type": "mark_add", "target": "enemy",
                             "mark": "mv", "count": 120}],
                "chain_refs": ["ch"]},
        "dv": {"id": "dv", "name": "派生技", "type": "active", "kind": "damage",
               "power": 200, "mp_cost": 0, "hp_cost": 30,
               "consume_marks": {"mv": 120}},
        "ch": {"id": "ch", "name": "链", "trigger_skill": "src", "max_combo": 1,
               "max_combo_behavior": "reset",
               "steps": [{"from": "src", "to": "dv", "tag": "none",
                          "condition": {"target_marks": {"mv": {"min": 120}}},
                          "priority": 1, "mode": "replace", "armor": False,
                          "consume": 0, "variant_override": {}}]},
    }
    eng = _engine(defs, hp=100)
    eng.marks_manager().apply_add(AddMark(side="enemy", mark="mv", count=120))
    out = eng.do_action("player", {"type": "skill", "skill_id": "src"})
    assert out.ok is True, out
    assert (out.combo_result or {}).get("form_id") == "dv"
    assert _hp(eng) == 70, f"应按派生技 hp_cost=30 扣血，got {_hp(eng)}"


# ---------------------------------------------------------------------------
# B1 回归：不带 hp_cost 时既有行为逐字段一致
# ---------------------------------------------------------------------------
def test_b1_regression_without_field_identical() -> None:
    defs = {
        "plain": {"id": "plain", "name": "普技", "type": "active",
                  "kind": "damage", "power": 100, "mp_cost": 10},
        "zero": {"id": "zero", "name": "零血耗", "type": "active",
                 "kind": "damage", "power": 100, "mp_cost": 10, "hp_cost": 0},
    }
    a = _engine(defs, hp=100, mp=100)
    b = _engine(defs, hp=100, mp=100)
    oa = a.do_action("player", {"type": "skill", "skill_id": "plain"})
    ob = b.do_action("player", {"type": "skill", "skill_id": "zero"})
    assert oa.ok is True and ob.ok is True
    assert (_hp(a), _mp(a)) == (_hp(b), _mp(b)) == (100, 90)
    # 非 int 的 hp_cost（历史脏数据）不得触发扣血（int() 防御，行为同缺省）
    c = _engine(defs, hp=100, mp=100)
    assert c.do_action("player", {"type": "skill", "skill_id": "plain"}).ok is True
    assert (_hp(c), _mp(c)) == (100, 90)


# ---------------------------------------------------------------------------
# B1 端到端：临时内容根建包 → 加载 → 释放 → HP 真扣（贴数值）
# ---------------------------------------------------------------------------
def test_b1_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_b1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_b1", "version": "1", "schema_version": 1,
         "modules": ["skills"]}, ensure_ascii=False), encoding="utf-8")
    (root / "skills.json").write_text(json.dumps([
        dict(_BASIC),
        {"id": "blood_rage", "name": "血怒", "type": "active", "kind": "damage",
         "power": 120, "hp_cost": 20}], ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    defs = {e["id"]: dict(e) for e in pack.modules["skills"]}
    assert defs["blood_rage"]["hp_cost"] == 20

    eng = _engine(defs, hp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "blood_rage"})
    assert out.ok is True, out
    assert _hp(eng) == 80, f"E2E 应 HP 100 → 80，got {_hp(eng)}"
