"""批26 · α6：替换职业 `job_override`（CakeGame 装备附加Re《核心配置》:79-81）。

设计口径（本批拍板，写进报告）：
  · 形态 = obj{job: <jobs 引用>, level_reset: bool, name_override: str}；
  · 语义 = **穿戴期间**职业被替换（含等级重置、显示名替换），**卸下还原**——与
    `jobs.transform.transform_to`（`field_meta.py` 的**战斗内**形态切换）不是一回事；
  · 引擎 = core/equip_mods.recompute_job_override：改 `player.job_id` / `player.level`
    与 `persistent_state.job_name_override`；base（原 job/level）首次覆盖时快照，
    换装 A→B 不丢 base；
  · 显示名读点：装配层 context 取 `persistent_state.job_name_override` 优先于注册表名。

叠加顺序（与 α1/α3/α5，写进 equip_mods docstring）：
  穿/卸 → ① α1 装备来源技能重算 → ② α6 职业覆盖重算；
  战斗/指令期：α5 普攻替换（选技能）→ α3 增幅（作用于选定技能）→ α1 可用技能集。

覆盖：
  - 元数据登记（items + equipment，obj 子键）+ 编辑器可见；
  - 校验：job 引用缺失 → 泛型 R-4 红；
  - 引擎消费（状态级）：穿戴后职业/等级/名称变化（前后对比）；卸下还原；
    换装 A→B 保留 base；
  - 回归：不带 job_override → 职业/等级/显示名逐字段不变、不写覆盖键。

测试只建临时内容根 / 临时对象，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equip_mods import (
    EQUIP_JOB_OVERRIDE_KEY,
    JOB_NAME_OVERRIDE_KEY,
)
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes
from qbot_rpg.web import api

CROWN_A = {"id": "crown_a", "name": "王者冠A", "slot": "weapon",
           "job_override": {"job": "warrior", "level_reset": True,
                            "name_override": "剑圣"}}
CROWN_B = {"id": "crown_b", "name": "王者冠B", "slot": "weapon",
           "job_override": {"job": "mage", "level_reset": False}}
PLAIN = {"id": "plain", "name": "素冠", "slot": "weapon"}


def _row(item_id: str) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                        bound=False, slot="weapon")


def _ctx(inventory: list, items: dict) -> dict:
    player = {
        "inventory": list(inventory),
        "equipment": {},
        "attributes": PlayerAttributes(base={"hp": 100.0, "str": 15.0}),
        "in_battle": False,
        "job_id": "novice",
        "level": 10,
        "persistent_state": {},
    }
    return {
        "player": player, "items": items, "job_id": "novice", "level": 10,
        "job_name": "新手", "skills": {}, "skill_slots_state": {},
        "set_skills": {}, "equip_skills": {},
        "equip_engine": EquipmentEngineAdapter(
            slots={"weapon": {"name": "武器", "max": 1}}),
    }


def _wear(ctx: dict, index: int) -> dict:
    return ctx["equip_engine"].equip_wear(index, ctx)


def _remove(ctx: dict, slot: str = "weapon") -> dict:
    return ctx["equip_engine"].equip_remove(slot, ctx)


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a6_metadata_registered() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("job_override")
        assert fm is not None, f"{mod} 缺 job_override 登记"
        assert fm.type == "obj"
        kids = fm.children
        assert kids["job"].type == "ref" and kids["job"].ref_target == "job"
        assert kids["level_reset"].type == "bool"
        assert kids["name_override"].type == "str"
    assert tbl.module("equipment").field_groups.get("job_override") == "effects"


def test_a6_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a6"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a6", "version": "1", "schema_version": 1, "modules": ["equipment"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "equipment.json").write_text(json.dumps([
        {"id": "crown_a", "name": "王者冠A", "slot": "weapon",
         "job_override": {"job": "warrior", "level_reset": True,
                          "name_override": "剑圣"}}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_a6", "equipment", "crown_a", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "job_override")
    assert f["present"] is True and f["type"] == "obj"


# ---------------------------------------------------------------------------
# 校验：job 引用缺失 → R-4 红
# ---------------------------------------------------------------------------
def test_a6_validator_ref_missing_red() -> None:
    report = check_pack({
        "items": [{"id": "crown_a", "name": "王者冠A", "slot": "weapon",
                   "job_override": {"job": "no_such_job", "level_reset": True}}],
        "jobs": [{"id": "warrior", "name": "战士"}],
    })
    assert [e for e in report.errors
            if e.kind == "R-4" and "job_override" in e.field], report.errors


def test_a6_validator_valid_ok() -> None:
    report = check_pack({
        "items": [{"id": "crown_a", "name": "王者冠A", "slot": "weapon",
                   "job_override": {"job": "warrior", "level_reset": True,
                                    "name_override": "剑圣"}}],
        "jobs": [{"id": "warrior", "name": "战士"}],
    })
    assert not [e for e in report.errors if "job_override" in e.field], report.errors


# ---------------------------------------------------------------------------
# 引擎消费：穿戴 / 卸下 / 换装（状态级前后对比）
# ---------------------------------------------------------------------------
def test_a6_wear_overrides_and_unequip_restores() -> None:
    ctx = _ctx([_row("crown_a")], {"crown_a": CROWN_A})
    assert (ctx["job_id"], ctx["level"], ctx["job_name"]) == ("novice", 10, "新手")
    assert _wear(ctx, 1)["ok"] is True
    player = ctx["player"]
    ps = player["persistent_state"]
    assert player["job_id"] == "warrior"
    assert player["level"] == 1
    assert ps[JOB_NAME_OVERRIDE_KEY] == "剑圣"
    assert ps[EQUIP_JOB_OVERRIDE_KEY]["base_job_id"] == "novice"
    assert ps[EQUIP_JOB_OVERRIDE_KEY]["base_level"] == 10
    # 同拍镜像：ctx 职业/等级/显示名
    assert (ctx["job_id"], ctx["level"], ctx["job_name"]) == ("warrior", 1, "剑圣")

    assert _remove(ctx, "weapon")["ok"] is True
    assert player["job_id"] == "novice" and player["level"] == 10
    assert EQUIP_JOB_OVERRIDE_KEY not in ps and JOB_NAME_OVERRIDE_KEY not in ps
    assert (ctx["job_id"], ctx["level"]) == ("novice", 10)


def test_a6_swap_a_to_b_keeps_base() -> None:
    ctx = _ctx([_row("crown_a"), _row("crown_b")],
               {"crown_a": CROWN_A, "crown_b": CROWN_B})
    assert _wear(ctx, 1)["ok"] is True
    assert ctx["player"]["level"] == 1
    assert _wear(ctx, 2)["ok"] is True      # 同槽换装 B（覆盖 A）
    player = ctx["player"]
    ps = player["persistent_state"]
    assert player["job_id"] == "mage"
    assert player["level"] == 10            # B 不重置等级 → 还原 base
    # base 未被 B 覆盖（仍是原始 novice/10）
    assert ps[EQUIP_JOB_OVERRIDE_KEY]["base_job_id"] == "novice"
    assert ps[EQUIP_JOB_OVERRIDE_KEY]["base_level"] == 10
    assert JOB_NAME_OVERRIDE_KEY not in ps  # B 无显示名覆盖
    assert _remove(ctx, "weapon")["ok"] is True
    assert player["job_id"] == "novice" and player["level"] == 10


def test_a6_regression_without_field() -> None:
    ctx = _ctx([_row("plain")], {"plain": PLAIN})
    assert _wear(ctx, 1)["ok"] is True
    player = ctx["player"]
    assert player["job_id"] == "novice" and player["level"] == 10
    assert player["persistent_state"] == {}
    assert _remove(ctx, "weapon")["ok"] is True
    assert player["job_id"] == "novice" and player["level"] == 10
