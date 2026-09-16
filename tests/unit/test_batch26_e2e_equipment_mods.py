"""批26 · 端到端（临时内容根）：装备附加链 内容根 → 装包 → 穿戴 → 技能集变化 → 卸下复原。

链路（真实 loader + registry + 装备引擎适配器）：
  临时内容根（manifest/equipment/items/skills/jobs）
    → content.loader.load_pack（含校验；errors 非空即抛 PackLoadError）
    → registry（kind=item ∪ kind=equipment → ctx["items"]）
    → EquipmentEngineAdapter.equip_wear/equip_remove
    → core.equip_mods.sync_equip_mods（装备来源技能容器）
    → core.skill_slots_battle.available_skills（战斗可用技能集）

测试只建临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

from qbot_rpg.assembly.context import _table_from_registry
from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.content.loader import load_pack
from qbot_rpg.core.equip_mods import equip_skills_of
from qbot_rpg.core.skill_slots_battle import available_skills
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes
from qbot_rpg.web import api


def _write_pack(root: Path) -> Path:
    d = root / "pack_e2e"
    d.mkdir()
    modules = {
        "manifest.json": {"name": "pack_e2e", "version": "1", "schema_version": 1,
                          "modules": ["jobs", "skills", "items", "equipment"]},
        "jobs.json": [{"id": "novice", "name": "新手"}],
        "skills.json": [
            {"id": "basic_atk", "name": "普攻", "type": "basic"},
            {"id": "granted", "name": "戒律斩", "type": "active"},
        ],
        "items.json": [],
        "equipment.json": [
            {"id": "ring", "name": "技能戒", "slot": "weapon",
             "grant_skills": [{"skill": "granted", "level": 2}]},
        ],
    }
    for name, data in modules.items():
        (d / name).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return d


def test_e2e_temp_content_root_wear_and_remove(tmp_path: Path) -> None:
    pack_dir = _write_pack(tmp_path)
    pack = asyncio.run(load_pack(pack_dir))

    # 编辑器接口（同一临时内容根）能读到新字段
    detail = api.entry_detail("pack_e2e", "equipment", "ring", root=tmp_path)
    grant = next(x for x in detail["fields"] if x["key"] == "grant_skills")
    assert grant["present"] is True and grant["type"] == "list"

    # registry → ctx["items"]（item ∪ equipment，与装配层同口径）
    items = dict(_table_from_registry(pack.registry, "item"))
    items.update(_table_from_registry(pack.registry, "equipment"))
    assert "ring" in items

    player = {
        "inventory": [ItemInstance(item_id="ring", name="技能戒", count=1,
                                   quality="normal", bound=False, slot="weapon")],
        "equipment": {},
        "attributes": PlayerAttributes(base={"hp": 100.0}),
        "in_battle": False,
        "job_id": "novice",
        "level": 1,
        "persistent_state": {},
    }
    ctx = {
        "player": player, "items": items,
        "skills": {
            "basic_atk": {"id": "basic_atk", "name": "普攻", "type": "basic"},
            "granted": {"id": "granted", "name": "戒律斩", "type": "active"},
        },
        "skill_slots_state": {"slots": [{"slot": "basic", "skill_id": "basic_atk"}],
                              "active_order": [], "passive": [], "trigger": [],
                              "version": 1},
        "set_skills": {}, "equip_skills": {},
        "equip_engine": EquipmentEngineAdapter(slots={"weapon": {"name": "武器", "max": 1}}),
    }

    before = available_skills(ctx)
    assert before == ["basic_atk"], before

    assert ctx["equip_engine"].equip_wear(1, ctx)["ok"] is True
    after = available_skills(ctx)
    assert "granted" in after and "granted" not in before, (before, after)
    assert equip_skills_of(player) == {"granted": 2}

    assert ctx["equip_engine"].equip_remove("weapon", ctx)["ok"] is True
    restored = available_skills(ctx)
    assert restored == before, (before, restored)
    assert equip_skills_of(player) == {}
