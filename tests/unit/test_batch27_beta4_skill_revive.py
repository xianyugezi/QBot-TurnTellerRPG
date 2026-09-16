"""批27 · β4：技能复活标记 `revive`（CakeGame《技能附加与变量集表》:53 FHX 复活技能）。

设计口径（本批拍板，写进报告）：
  · 形态 = `skills[].revive` bool（缺省 false）；true = 该技能可复活死亡态目标；
  · 引擎消费 = `core/battle.py::revive_side`——清死亡标记 + 恢复 HP + 去 `weak`
    虚弱状态 + 回收 result 胜负标记 + **派发既有 `revive` 事件**（沿用
    `core/event_dispatcher.EVENT_POINTS` 的 revive 链路，不另造事件/链路）；
  · 释放路径：`_resolve_combo_action` 按**最终 skill_id**（派生/组合口径同 hp_cost）
    解析 revive 标记；目标为行动对侧；目标未死亡 → 零操作；
  · 校验：bool（泛型 R-1 红拦）；缺省 = 非复活技（既有包零变化，对拍）。
  · **模型差异（如实登记）**：本框架战斗为 1v1（无双侧友军），CakeGame 的
    「复活倒下的队友」在我们这里落为「复活死亡态目标」；CTB 的 `mark_dead` 无反向
    接口，本批只做战斗态复活、不回插调度队列（作为登记缺口）。

覆盖：
  - 元数据登记（skills，bool）+ 编辑器可见（临时内容根）；
  - 校验：非 bool → R-1 红；true/false/缺省 → 无红；
  - 引擎消费（状态级）：带标记技能 → 死亡目标 dead_mark 清、HP>0、side_effect 含
    revive 且 heal 生效；去 weak 虚弱状态；普通技能 → 目标仍 dead_mark；
  - 回归：不带 revive 字段行为逐字段一致；revive_side 对未死亡侧零副作用。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.web import api

_BASIC = {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
          "power": 100}


def _defs() -> Dict[str, Any]:
    return {
        "revive_skill": {
            "id": "revive_skill", "name": "回魂术", "type": "active", "kind": "heal",
            "power": 0, "revive": True,
            "effects": [{"type": "heal", "target": "enemy", "stat": "hp", "value": 30}],
        },
        "plain_skill": {
            "id": "plain_skill", "name": "普通治疗", "type": "active", "kind": "heal",
            "power": 0,
            "effects": [{"type": "heal", "target": "enemy", "stat": "hp", "value": 30}],
        },
        "weak_debuff": {"id": "weak_debuff", "name": "虚弱", "type": "debuff",
                        "category": "weak", "duration": {"turns": 5, "charges": 0}},
        "keep_buff": {"id": "keep_buff", "name": "保留", "type": "buff",
                      "category": "buff", "duration": {"turns": 5, "charges": 0}},
    }


def _engine(*, enemy_dead: bool = False) -> BattleEngine:
    eng = BattleEngine(defs=_defs(), config={})
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 100, "def": 0, "spr": 0, "spd": 10, "foc": 500, "con": 0,
         "lck": 0, "int": 0, "name": "玩家"},
        {"hp": 100, "max_hp": 100, "mp": 0, "max_mp": 0,
         "atk": 0, "def": 0, "spr": 0, "spd": 1, "foc": 0, "con": 0,
         "lck": 0, "int": 0, "name": "桩"},
        random_seed=7,
    )
    if enemy_dead:
        eng._snap["enemy"]["dead_mark"] = True  # noqa: SLF001 - 造死亡态（不触发终局结算）
        eng._snap["enemy"]["hp"] = 0            # noqa: SLF001
    return eng


# ---------------------------------------------------------------------------
# β4 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_b4_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("skills").fields.get("revive")
    assert fm is not None, "skills 缺 revive 登记"
    assert fm.type == "bool"
    assert fm.label == "复活技能" and fm.help
    assert tbl.module("skills").field_groups.get("revive") == "基本"


def test_b4_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_b4"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_b4", "version": "1", "schema_version": 1,
         "modules": ["skills"]}, ensure_ascii=False), encoding="utf-8")
    (root / "skills.json").write_text(json.dumps([
        dict(_BASIC),
        {"id": "soul_return", "name": "回魂术", "type": "active", "kind": "heal",
         "revive": True}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_b4", "skills", "soul_return", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "revive")
    assert f["present"] is True and f["type"] == "bool"


# ---------------------------------------------------------------------------
# β4 校验：bool 口径
# ---------------------------------------------------------------------------
def test_b4_validator_non_bool_red() -> None:
    report = check_pack({"skills": [
        dict(_BASIC), {"id": "s", "name": "复活技", "revive": "yes"}]})
    assert [e for e in report.errors if e.kind == "R-1" and "revive" in e.field], report.errors


def test_b4_validator_true_false_missing_ok() -> None:
    report = check_pack({"skills": [
        dict(_BASIC),
        {"id": "s", "name": "复活技", "revive": True},
        {"id": "t", "name": "非复活技", "revive": False},
        {"id": "u", "name": "普通技"},
    ]})
    assert not [e for e in report.errors if "revive" in e.field], report.errors
    assert not [w for w in report.warnings if "revive" in w.field], report.warnings


# ---------------------------------------------------------------------------
# β4 引擎消费（状态级）
# ---------------------------------------------------------------------------
def test_b4_marked_skill_revives_dead_target() -> None:
    eng = _engine(enemy_dead=True)
    assert eng._snap["enemy"]["dead_mark"] is True  # noqa: SLF001
    out = eng.do_action("player", {"type": "skill", "skill_id": "revive_skill"})
    assert out.ok is True, out
    enemy = eng._snap["enemy"]  # noqa: SLF001
    assert enemy["dead_mark"] is False, "带 revive 标记的技能应清死亡标记"
    assert int(enemy["hp"]) > 0, "复活后应恢复生命（1 点 + 治疗 30）"
    types = [e.get("type") for e in out.side_effects]
    assert "revive" in types, types
    assert "heal" in types, types


def test_b4_plain_skill_does_not_revive() -> None:
    eng = _engine(enemy_dead=True)
    out = eng.do_action("player", {"type": "skill", "skill_id": "plain_skill"})
    assert out.ok is True, out
    assert eng._snap["enemy"]["dead_mark"] is True, "普通技能不得复活"  # noqa: SLF001
    assert "revive" not in [e.get("type") for e in out.side_effects]


def test_b4_revive_removes_weak_status_only() -> None:
    """去虚弱：复活时清 `category=="weak"` 的虚弱状态，其余状态保留。"""
    eng = _engine(enemy_dead=True)
    rt = eng._new_runtime()  # noqa: SLF001
    rt.apply_status("weak_debuff", "enemy")
    rt.apply_status("keep_buff", "enemy")
    eng._absorb_runtime(rt)  # noqa: SLF001
    assert len(eng._new_runtime().status_instances("enemy")) == 2  # noqa: SLF001
    assert eng.revive_side("enemy") is True
    left = [i.get("status_id") for i in eng._new_runtime().status_instances("enemy")]  # noqa: SLF001
    assert left == ["keep_buff"], left


def test_b4_revive_side_idempotent_on_alive() -> None:
    """未死亡侧 → revive_side 返回 False，零副作用（幂等）。"""
    eng = _engine(enemy_dead=False)
    hp_before = int(eng._snap["enemy"]["hp"])  # noqa: SLF001
    assert eng.revive_side("enemy") is False
    assert int(eng._snap["enemy"]["hp"]) == hp_before  # noqa: SLF001


# ---------------------------------------------------------------------------
# β4 回归：不带 revive 字段行为逐字段一致
# ---------------------------------------------------------------------------
def test_b4_regression_without_field_identical() -> None:
    a = _engine(enemy_dead=False)
    b = _engine(enemy_dead=False)
    oa = a.do_action("player", {"type": "skill", "skill_id": "plain_skill"})
    ob = b.do_action("player", {"type": "skill", "skill_id": "plain_skill"})
    assert (oa.final_damage, oa.target_hp) == (ob.final_damage, ob.target_hp)
    assert [e.get("type") for e in oa.side_effects] == [e.get("type") for e in ob.side_effects]
