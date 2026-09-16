"""批26 · α3：装备增幅技能 `skill_amp`（CakeGame 装备附加Re《核心配置》:104-110）。

设计口径（本批拍板，写进报告）：
  · 形态 = `skill_amp` list<obj>{skill: <skills 引用>, type: <damage|cooldown>, value: int}；
  · 全局上下限**不硬编码**：默认值在 content/forge_settings（settings.forge.skill_amp_bounds，
    既有可配处，形态沿用 obj 段），校验器/引擎一律读配置；
  · 超限口径 = **红拦**（非钳制）：门禁只严不宽；钳制会静默改写作者填写的数值，
    让「超限」在包加载期不可见（与上下限护栏意图相悖）。引擎侧不再二次钳制；
  · `损伤` 类 = `1 + 总计/100` 作伤害乘数（引擎 core/battle 落在最终技能倍率）；
    `冷却` 类 = 同比率缩放冷却时长；
  · **「熟练」类跳过**（如实登记）：我们有职业熟练度（core/proficiency，按职业 exp/level），
    **无 per-技能熟练**概念，故 type 枚举只做 damage/cooldown 两项。

覆盖：
  - 元数据登记（items + equipment，list<obj> 子键）+ 编辑器可见；
  - 校验：type 越界 → 泛型 R-1；value 越上下限 → IV-4 红（默认 bounds 与包覆写
    两种配置都测，证明「读配置」而非硬编码）；
  - 引擎消费（数值级）：+50 → 伤害 1.5 倍（131 → 196 实测）；-50 → 冷却 10 → 5；
    无增幅 → 快照零新增键、伤害/冷却逐字段一致（回归）。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.forge_settings import DEFAULT_SKILL_AMP_BOUNDS, read_skill_amp_bounds
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.equip_mods import (
    amp_value,
    skill_amp_entries_of,
    skill_amp_table,
)
from qbot_rpg.web import api

SKILLS = [{"id": "s1", "name": "火球", "type": "active", "kind": "damage", "power": 100}]

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 0,
          "mag": 50, "spd": 50, "foc": 100, "con": 0, "str": 100, "int": 80, "agi": 50,
          "spr": 0, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400000, "hp": 400000, "max_mp": 0, "mp": 0, "atk": 0, "dfn": 0,
         "mag": 0, "spd": 40, "foc": 0, "con": 0, "str": 0, "int": 0, "agi": 40,
         "spr": 0, "lck": 0, "elem_atk": 0, "name": "E"}


class _QueueRNG:
    """确定性随机源（命中/会心/格挡/乱数 4 判定固定序列）。"""

    def __init__(self, seq) -> None:
        self.seq = list(seq)
        self.i = 0

    def random(self) -> float:
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _run(amp: Dict[str, Any] | None, *, cooldown: int = 0) -> tuple:
    defs = {"s1": {"id": "s1", "name": "火球", "tag": "combo", "power": 100,
                   "cooldown": cooldown}}
    cfg: Dict[str, Any] = {"combo_enforce_mp": True}
    if amp is not None:
        cfg["equip_skill_amp"] = amp
    eng = BattleEngine(defs=defs, config=cfg)
    eng._rng = _QueueRNG([0.5, 0.5, 0.5, 1.0])  # noqa: SLF001 - 确定性注入（同既有测试）
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=1)
    out = eng.do_action("player", {"type": "skill", "skill_id": "s1", "tag": "combo",
                                   "mult": 1.0})
    cds = eng._snap.get("skill_cooldowns", {}).get("player", {})  # noqa: SLF001
    return out, cds, eng


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a3_metadata_registered() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("skill_amp")
        assert fm is not None, f"{mod} 缺 skill_amp 登记"
        assert fm.type == "list"
        kids = fm.element.children
        assert kids["skill"].type == "ref" and kids["skill"].ref_target == "skill"
        assert kids["type"].type == "enum" and kids["type"].enum == ("damage", "cooldown")
        assert kids["value"].type == "int" and kids["value"].allow_negative is True
    # 上下限在既有 settings.forge 段（obj），框架默认值在 content/forge_settings
    forge = tbl.module("settings").fields["forge"]
    assert "skill_amp_bounds" in forge.children
    assert "damage_max" in forge.children["skill_amp_bounds"].children
    assert tbl.module("equipment").field_groups.get("skill_amp") == "effects"
    assert DEFAULT_SKILL_AMP_BOUNDS["damage_max"] == 90


def test_a3_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a3"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a3", "version": "1", "schema_version": 1, "modules": ["equipment"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "equipment.json").write_text(json.dumps([
        {"id": "blade", "name": "增幅刃", "slot": "weapon",
         "skill_amp": [{"skill": "s1", "type": "damage", "value": 30}]}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_a3", "equipment", "blade", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "skill_amp")
    assert f["present"] is True and f["type"] == "list"


# ---------------------------------------------------------------------------
# 校验：enum + 上下限（默认 / 包覆写）
# ---------------------------------------------------------------------------
def _amp_pack(value: int, amp_type: str = "damage", settings: Any = None) -> dict:
    modules: Dict[str, Any] = {
        "items": [{"id": "blade", "name": "增幅刃", "slot": "weapon",
                   "skill_amp": [{"skill": "s1", "type": amp_type, "value": value}]}],
        "skills": SKILLS,
    }
    if settings is not None:
        modules["settings"] = settings
    return modules


def test_a3_validator_enum_red() -> None:
    report = check_pack(_amp_pack(10, amp_type="proficiency"))
    assert [e for e in report.errors
            if e.kind == "R-1" and "skill_amp" in e.field], report.errors


def test_a3_validator_bounds_default_red() -> None:
    for value, kind in ((91, "damage"), (-91, "damage"), (101, "cooldown"),
                        (-51, "cooldown")):
        report = check_pack(_amp_pack(value, amp_type=kind))
        assert [e for e in report.errors
                if e.kind == "IV-4" and "skill_amp" in e.field], (value, kind, report.errors)


def test_a3_validator_bounds_inside_ok() -> None:
    for value, kind in ((90, "damage"), (-90, "damage"), (100, "cooldown"),
                        (-50, "cooldown"), (0, "damage")):
        report = check_pack(_amp_pack(value, amp_type=kind))
        assert not [e for e in report.errors if "skill_amp" in e.field], (value, kind)


def test_a3_bounds_configurable_not_hardcoded() -> None:
    """包覆写 settings.forge.skill_amp_bounds → 校验按新上下限（证明读配置）。"""
    custom = {"forge": {"skill_amp_bounds": {"damage_max": 200, "damage_min": -200}}}
    assert read_skill_amp_bounds(custom)["damage_max"] == 200
    ok = check_pack(_amp_pack(150, settings=custom))
    assert not [e for e in ok.errors if e.kind == "IV-4" and "skill_amp" in e.field], ok.errors
    red = check_pack(_amp_pack(201, settings=custom))
    assert [e for e in red.errors if e.kind == "IV-4" and "skill_amp" in e.field]


# ---------------------------------------------------------------------------
# 引擎消费：数值级（伤害乘数 / 冷却）
# ---------------------------------------------------------------------------
def test_a3_pure_aggregation() -> None:
    assert skill_amp_entries_of({"skill_amp": [{"skill": "s1", "type": "damage",
                                                "value": 20}]}) == [("s1", "damage", 20)]
    # 非法 type / 非整 value → 清洗跳过
    assert skill_amp_entries_of({"skill_amp": [{"skill": "s1", "type": "x", "value": 1},
                                               {"skill": "s1", "type": "damage",
                                                "value": "1"}]}) == []
    player = {"equipment": {"weapon": {"item_id": "b"}}, "persistent_state": {}}
    ctx = {"items": {"b": {"id": "b", "skill_amp": [
        {"skill": "s1", "type": "damage", "value": 30},
        {"skill": "s1", "type": "damage", "value": 20},
        {"skill": "s1", "type": "cooldown", "value": -10}]}}}
    table = skill_amp_table(player, ctx)
    assert table == {"player": {"s1": {"damage": 50, "cooldown": -10}}}
    assert amp_value(table, "player", "s1", "damage") == 50
    assert amp_value(table, "player", "s1", "cooldown") == -10
    assert amp_value(table, "player", "missing", "damage") == 0
    assert skill_amp_table({"equipment": {}}, {"items": {}}) == {}


def test_a3_damage_multiplier_1_5x() -> None:
    base, _, eng0 = _run(None)
    amp, _, eng1 = _run({"player": {"s1": {"damage": 50}}})
    assert base.raw_damage == 131, base.raw_damage
    assert amp.raw_damage == 196, (base.raw_damage, amp.raw_damage)
    assert round(amp.raw_damage / base.raw_damage, 2) == 1.5
    # 无增幅：快照零新增键（回归）；有增幅：键在
    assert "equip_skill_amp" not in eng0._snap  # noqa: SLF001
    assert eng1._snap["equip_skill_amp"] == {"player": {"s1": {"damage": 50}}}  # noqa: SLF001


def test_a3_damage_negative_amp_halves() -> None:
    base, _, _ = _run(None)
    amp, _, _ = _run({"player": {"s1": {"damage": -50}}})
    assert base.raw_damage == 131
    assert amp.raw_damage == round(base.raw_damage * 0.5), (base.raw_damage,
                                                            amp.raw_damage)


def test_a3_cooldown_scaled() -> None:
    _, base_cd, _ = _run(None, cooldown=10)
    _, red_cd, _ = _run({"player": {"s1": {"cooldown": -50}}}, cooldown=10)
    _, up_cd, _ = _run({"player": {"s1": {"cooldown": 100}}}, cooldown=10)
    assert base_cd == {"s1": 10}, base_cd
    assert red_cd == {"s1": 5}, red_cd      # round(10*0.5)+1 stored → tick → 5
    assert up_cd == {"s1": 20}, up_cd       # round(10*2.0)+1 stored → tick → 20


def test_a3_regression_without_amp_identical() -> None:
    base, base_cd, eng = _run(None, cooldown=0)
    assert base.ok is True and base.raw_damage == 131
    assert base_cd == {}
    assert "equip_skill_amp" not in eng._snap  # noqa: SLF001
