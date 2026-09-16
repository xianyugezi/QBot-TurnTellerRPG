"""批26 · α5：替换普攻 `attack_override`（CakeGame 装备附加Re《核心配置》:76-78）。

设计口径（本批拍板，写进报告）：
  · 形态 = obj{enabled: bool, skill: <skills 引用>, chance: int 0~100}；
  · 引擎消费 = 普攻入口（`commands/battle_commands._attack_action` 无参分支）按
    `chance` 概率替换为指定技能；RNG 用引擎既有单源（ctx["rng"]，缺省 random），
    可注入确定性随机源 → 替换/不替换两态不 flaky；
  · 只有「装备赋予技能」（α1）成立时才允许：替换技能须在本玩家装备来源已授予
    技能集内，否则**不替换**（不硬拦）；校验层给 Y-9 黄提示；
  · `chance=0`/缺省/不满足 → 行为与现状**逐字段一致**（对拍）。

覆盖：
  - 元数据登记（items + equipment，obj 子键）+ 编辑器可见；
  - 校验：skill 未在本件 grant_skills → Y-9 黄（不红）；引用缺失 → 泛型 R-4；
  - 引擎消费：注入确定性 RNG → 替换/不替换两态；未授予/禁用/chance=0 → 不替换；
  - 回归：无 attack_override → 既有 basic 槽行为逐字段一致。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.commands.battle_commands import _attack_action
from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equip_mods import (
    attack_override_of,
    resolve_attack_override,
)
from qbot_rpg.web import api

SKILLS = {
    "basic_atk": {"id": "basic_atk", "name": "普攻", "type": "basic", "kind": "damage"},
    "ovr": {"id": "ovr", "name": "替换斩", "type": "active", "kind": "damage"},
}


class FakeRNG:
    """确定性 RNG：randint 恒返回给定值（注入 ctx["rng"]，不 flaky）。"""

    def __init__(self, roll: int) -> None:
        self.roll = roll

    def randint(self, lo: int, hi: int) -> int:
        return self.roll


def _make_ctx(item_def: dict, *, roll: int = 1, granted: bool = True,
              learned: list = ()) -> dict:
    snapshot = {
        "slots": [{"slot": "basic", "skill_id": "basic_atk"}]
        + [{"slot": "active", "skill_id": s} for s in learned],
        "active_order": list(learned), "passive": [], "trigger": [], "version": 1,
    }
    equip_skills = {"ovr": 1} if granted else {}
    player = {
        "equipment": {"weapon": {"item_id": "blade", "name": "替换刃"}},
        "persistent_state": {"equip_skills": dict(equip_skills)},
    }
    return {
        "player": player,
        "items": {"blade": item_def},
        "skills": dict(SKILLS),
        "skill_slots_state": snapshot,
        "set_skills": {},
        "equip_skills": dict(equip_skills),
        "rng": FakeRNG(roll),
    }


OVERRIDE = {
    "id": "blade", "name": "替换刃", "slot": "weapon",
    "grant_skills": [{"skill": "ovr", "level": 1}],
    "attack_override": {"enabled": True, "skill": "ovr", "chance": 100},
}


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a5_metadata_registered() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("attack_override")
        assert fm is not None, f"{mod} 缺 attack_override 登记"
        assert fm.type == "obj"
        kids = fm.children
        assert kids["enabled"].type == "bool"
        assert kids["skill"].type == "ref" and kids["skill"].ref_target == "skill"
        assert kids["chance"].type == "int"
        assert kids["chance"].range_min == 0 and kids["chance"].range_max == 100
    assert tbl.module("equipment").field_groups.get("attack_override") == "effects"


def test_a5_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a5"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a5", "version": "1", "schema_version": 1, "modules": ["equipment"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "equipment.json").write_text(json.dumps([
        {"id": "blade", "name": "替换刃", "slot": "weapon",
         "grant_skills": [{"skill": "ovr", "level": 1}],
         "attack_override": {"enabled": True, "skill": "ovr", "chance": 50}}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_a5", "equipment", "blade", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "attack_override")
    assert f["present"] is True and f["type"] == "obj"


# ---------------------------------------------------------------------------
# 校验：未授予 → Y-9 黄（不红）；引用缺失 → R-4
# ---------------------------------------------------------------------------
def test_a5_validator_not_granted_yellow() -> None:
    report = check_pack({
        "items": [{"id": "blade", "name": "替换刃", "slot": "weapon",
                   "attack_override": {"enabled": True, "skill": "ovr", "chance": 50}}],
        "skills": list(SKILLS.values()),
    })
    assert [w for w in report.warnings if w.kind == "Y-9"], report.warnings
    assert not [e for e in report.errors if "attack_override" in e.field], report.errors


def test_a5_validator_granted_no_yellow() -> None:
    report = check_pack({
        "items": [{"id": "blade", "name": "替换刃", "slot": "weapon",
                   "grant_skills": [{"skill": "ovr", "level": 1}],
                   "attack_override": {"enabled": True, "skill": "ovr", "chance": 50}}],
        "skills": list(SKILLS.values()),
    })
    assert not [w for w in report.warnings if w.kind == "Y-9"], report.warnings


def test_a5_validator_ref_missing_red() -> None:
    report = check_pack({
        "items": [{"id": "blade", "name": "替换刃", "slot": "weapon",
                   "attack_override": {"enabled": True, "skill": "no_such", "chance": 50}}],
        "skills": list(SKILLS.values()),
    })
    assert [e for e in report.errors
            if e.kind == "R-4" and "attack_override" in e.field], report.errors


def test_a5_pure_parse() -> None:
    assert attack_override_of(OVERRIDE) == {"enabled": True, "skill": "ovr",
                                            "chance": 100}
    assert attack_override_of({"attack_override": {"skill": ""}}) is None
    assert attack_override_of({}) is None


# ---------------------------------------------------------------------------
# 引擎消费：确定性 RNG 两态
# ---------------------------------------------------------------------------
def test_a5_replacement_and_no_replacement() -> None:
    ctx_hit = _make_ctx(OVERRIDE, roll=100)
    assert resolve_attack_override(ctx_hit) == "ovr"
    # 概率 1%：roll=2 不中、roll=1 命中（确定性两态，不 flaky）
    ovr_low = dict(OVERRIDE)
    ovr_low["attack_override"] = {"enabled": True, "skill": "ovr", "chance": 1}
    ctx_miss = _make_ctx(ovr_low, roll=2)
    assert resolve_attack_override(ctx_miss) is None
    assert resolve_attack_override(_make_ctx(ovr_low, roll=1)) == "ovr"


def test_a5_zero_chance_and_disabled_and_ungranted() -> None:
    zero = dict(OVERRIDE)
    zero["attack_override"] = {"enabled": True, "skill": "ovr", "chance": 0}
    assert resolve_attack_override(_make_ctx(zero, roll=1)) is None
    off = dict(OVERRIDE)
    off["attack_override"] = {"enabled": False, "skill": "ovr", "chance": 100}
    assert resolve_attack_override(_make_ctx(off, roll=1)) is None
    assert resolve_attack_override(_make_ctx(OVERRIDE, roll=1, granted=False)) is None


def test_a5_attack_entry_uses_override() -> None:
    parsed = parse_command("/攻击")
    ctx = _make_ctx(OVERRIDE, roll=1)
    action, err = _attack_action(parsed, ctx)
    assert err is None and action == {"type": "skill", "skill_id": "ovr"}, action


def test_a5_attack_entry_regression_without_field() -> None:
    parsed = parse_command("/攻击")
    plain = {"id": "blade", "name": "普通刃", "slot": "weapon"}
    action, err = _attack_action(parsed, _make_ctx(plain, roll=1))
    assert err is None and action == {"type": "skill", "skill_id": "basic_atk"}, action
    # 无 basic 槽 → 引擎普攻兜底逐字段一致
    ctx = _make_ctx(plain, roll=1)
    ctx["skill_slots_state"] = {"slots": [{"slot": "basic", "skill_id": None}],
                                "active_order": [], "passive": [], "trigger": [],
                                "version": 1}
    action2, err2 = _attack_action(parsed, ctx)
    assert err2 is None and action2 == {"type": "normal"}, action2
