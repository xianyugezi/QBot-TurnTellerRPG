"""批26 · α1：装备赋予技能 `grant_skills`（CakeGame 装备附加Re《核心配置》:73）。

设计口径（本批拍板，写进报告）：
  · 形态 = `grant_skills` list<obj>{skill: <skills 引用>, level: int ≥1}；缺省 = 无；
  · 语义 = **穿戴时获得、卸下时收回**（区别于 `effects.type=learn_skill` 的消耗品
    学一次、`jobs.transform.skill_set` 的战斗内变身）；
  · 装配口径**沿用既有来源容器**：装备来源写 `persistent_state.equip_skills`
    （经 ctx["equip_skills"] 注入），由 `core.skill_slots_battle.with_source_skills`
    与装配快照（skill_slots 学习）/ 套装激活（set_skills）**取并集**——
    来源计数语义：卸下只清装备容器，其它来源的技能不被收走。

覆盖：
  - 元数据登记（items + equipment，list<obj> 子键 skill 引用/level ≥1）+ 编辑器可见；
  - 校验：skill 引用缺失 → 泛型 R-4 红；level < 1 → IV-2 红；
  - 引擎消费（状态级）：穿戴后技能集多出该技能（前后对比）；卸下收回；
    被其它来源（学习快照）拥有的技能不被收走；换装 A→B 不残留；
  - 回归：不带 grant_skills → equip_skills 恒空、可用技能集逐字段一致。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equip_mods import (
    EQUIP_SKILL_SOURCES_KEY,
    equip_skills_of,
)
from qbot_rpg.core.skill_slots_battle import available_skills, is_slot_equipped
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes
from qbot_rpg.web import api

SKILLS = {
    "basic_atk": {"id": "basic_atk", "name": "普攻", "type": "basic", "kind": "damage"},
    "granted": {"id": "granted", "name": "戒律斩", "type": "active", "kind": "damage"},
    "other": {"id": "other", "name": "别式", "type": "active", "kind": "damage"},
}


def _row(item_id: str, name: str, slot: str = "weapon") -> ItemInstance:
    return ItemInstance(item_id=item_id, name=name, count=1, quality="normal",
                        bound=False, slot=slot)


def _make_ctx(inventory: list, items: Mapping[str, Any], *,
              learned: list = ()) -> dict:
    snapshot = {
        "slots": [{"slot": "basic", "skill_id": "basic_atk"}]
        + [{"slot": "active", "skill_id": s} for s in learned],
        "active_order": list(learned),
        "passive": [], "trigger": [], "version": 1,
    }
    player = {
        "inventory": list(inventory),
        "equipment": {},
        "attributes": PlayerAttributes(base={"hp": 100.0, "mp": 30.0, "str": 15.0}),
        "in_battle": False,
        "job_id": "novice",
        "level": 1,
        "persistent_state": {},
    }
    return {
        "player": player, "items": dict(items), "skills": dict(SKILLS),
        "skill_slots_state": snapshot, "set_skills": {}, "equip_skills": {},
        "job_id": "novice", "level": 1,
        "equip_engine": EquipmentEngineAdapter(
            slots={"weapon": {"name": "武器", "max": 1}}),
    }


def _wear(ctx: dict, index: int = 1) -> dict:
    return ctx["equip_engine"].equip_wear(index, ctx)


def _remove(ctx: dict, slot: str = "weapon") -> dict:
    return ctx["equip_engine"].equip_remove(slot, ctx)


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("grant_skills")
        assert fm is not None, f"{mod} 缺 grant_skills 登记"
        assert fm.type == "list"
        kids = fm.element.children
        assert kids["skill"].type == "ref" and kids["skill"].ref_target == "skill"
        assert kids["level"].type == "int" and kids["level"].range_min == 1
    assert tbl.module("equipment").field_groups.get("grant_skills") == "effects"


def test_a1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a1", "version": "1", "schema_version": 1, "modules": ["equipment"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "equipment.json").write_text(json.dumps([
        {"id": "ring", "name": "技能戒", "slot": "weapon",
         "grant_skills": [{"skill": "granted", "level": 3}]}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_a1", "equipment", "ring", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "grant_skills")
    assert f["present"] is True and f["type"] == "list"
    kids = {c["key"]: c for c in (f["element"]["children"] or [])}
    assert kids["skill"]["type"] == "ref" and kids["level"]["present"] is True


# ---------------------------------------------------------------------------
# 校验：skill 引用缺失 → R-4 红；level < 1 → IV-2 红
# ---------------------------------------------------------------------------
def test_a1_validator_ref_missing_red() -> None:
    report = check_pack({
        "items": [{"id": "ring", "name": "戒", "slot": "weapon",
                   "grant_skills": [{"skill": "no_such_skill", "level": 1}]}],
        "skills": list(SKILLS.values()),
    })
    assert [e for e in report.errors
            if e.kind == "R-4" and "grant_skills" in e.field], report.errors


def test_a1_validator_level_below_one_red() -> None:
    for bad in (0, -2):
        report = check_pack({
            "items": [{"id": "ring", "name": "戒", "slot": "weapon",
                       "grant_skills": [{"skill": "granted", "level": bad}]}],
            "skills": list(SKILLS.values()),
        })
        assert [e for e in report.errors
                if e.kind == "IV-2" and "grant_skills" in e.field], (bad, report.errors)


def test_a1_validator_valid_and_missing_ok() -> None:
    report = check_pack({
        "items": [{"id": "ring", "name": "戒", "slot": "weapon",
                   "grant_skills": [{"skill": "granted", "level": 1}]},
                  {"id": "plain", "name": "普通戒", "slot": "weapon"}],
        "skills": list(SKILLS.values()),
    })
    assert not [e for e in report.errors if "grant_skills" in e.field], report.errors


# ---------------------------------------------------------------------------
# 引擎消费：穿戴 / 卸下 / 换装（状态级前后对比）
# ---------------------------------------------------------------------------
def test_a1_wear_grants_and_unequip_revokes() -> None:
    items = {"ring_a": {"id": "ring_a", "name": "技能戒A", "slot": "weapon",
                        "grant_skills": [{"skill": "granted", "level": 3}]}}
    ctx = _make_ctx([_row("ring_a", "技能戒A")], items)
    before = available_skills(ctx)
    assert "granted" not in before
    assert equip_skills_of(ctx["player"]) == {}

    assert _wear(ctx, 1)["ok"] is True
    after = available_skills(ctx)
    assert "granted" in after and "granted" not in before, (before, after)
    assert is_slot_equipped(ctx, "granted") is True
    assert equip_skills_of(ctx["player"]) == {"granted": 3}
    ps = ctx["player"]["persistent_state"]
    assert ps["equip_skill_sources"] == {"granted": ["weapon"]}
    assert ctx["equip_skills"] == {"granted": 3}

    assert _remove(ctx, "weapon")["ok"] is True
    assert "granted" not in available_skills(ctx)
    assert equip_skills_of(ctx["player"]) == {}
    assert ctx.get("equip_skills") in (None, {})


def test_a1_other_source_not_revoked() -> None:
    """关键单测：技能已由「学习快照」来源拥有时，卸下装备不得把它收走。"""
    items = {"ring_a": {"id": "ring_a", "name": "技能戒A", "slot": "weapon",
                        "grant_skills": [{"skill": "granted", "level": 3}]}}
    ctx = _make_ctx([_row("ring_a", "技能戒A")], items, learned=["granted"])
    assert _wear(ctx, 1)["ok"] is True
    assert equip_skills_of(ctx["player"]) == {"granted": 3}
    assert _remove(ctx, "weapon")["ok"] is True
    # 装备来源容器已清空，但学习快照来源仍在 → 技能不被收走
    assert equip_skills_of(ctx["player"]) == {}
    assert "granted" in available_skills(ctx)
    assert is_slot_equipped(ctx, "granted") is True


def test_a1_swap_a_to_b_no_residue() -> None:
    items = {
        "ring_a": {"id": "ring_a", "name": "技能戒A", "slot": "weapon",
                   "grant_skills": [{"skill": "granted", "level": 3}]},
        "ring_b": {"id": "ring_b", "name": "技能戒B", "slot": "weapon",
                   "grant_skills": [{"skill": "other", "level": 1}]},
    }
    ctx = _make_ctx([_row("ring_a", "技能戒A"), _row("ring_b", "技能戒B")], items)
    assert _wear(ctx, 1)["ok"] is True
    assert equip_skills_of(ctx["player"]) == {"granted": 3}
    # 同槽换装 B（覆盖 A）→ 装备来源只应剩 B 的技能（A 不残留）
    assert _wear(ctx, 2)["ok"] is True
    assert equip_skills_of(ctx["player"]) == {"other": 1}
    av = available_skills(ctx)
    assert "other" in av and "granted" not in av, av


def test_a1_regression_without_field_identical() -> None:
    items = {"plain": {"id": "plain", "name": "素戒", "slot": "weapon"}}
    ctx = _make_ctx([_row("plain", "素戒")], items)
    before = available_skills(ctx)
    assert _wear(ctx, 1)["ok"] is True
    assert available_skills(ctx) == before
    assert equip_skills_of(ctx["player"]) == {}
    # 无装备来源技能 → 不写空容器（既有行为逐字段一致，回归对拍）
    assert "equip_skills" not in ctx["player"]["persistent_state"]
    assert EQUIP_SKILL_SOURCES_KEY not in ctx["player"]["persistent_state"]
