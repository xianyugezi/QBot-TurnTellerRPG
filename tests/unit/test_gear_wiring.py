"""批⑧ 装备接线收口测试（2026-09-12）——会心/百分比/耳栓/超会心全链 + 商店 dfn 回归。

覆盖：注册表键空间与工具函数 / 实例化转换（context 与 shop_tx 双路径；商店 dfn 回归钉死）/
聚合拆层 / PVP 战斗桥（含 pct 单位修正）/ 物品详情词条行 / 编辑器字段表同源守卫 /
veinborn 内容抽查（词条与赌狗武器落位）。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.commands.basic_commands import _item_stat_parts
from qbot_rpg.commands.shop_tx import _new_default_instance
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    GEAR_COMBAT_KEYS,
    GEAR_FLAT_KEYS,
    GEAR_NUMERIC_KEYS,
    GEAR_PCT_KEYS,
    combatant_updates,
    extract_bonus,
    route_bonus_into,
)
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content" / "veinborn"


def _mk_item(item_id, name, slot, stats_bonus=None):
    return ItemInstance(
        item_id=item_id, name=name, count=1, quality="normal", bound=False,
        stack_max=1, slot=slot, stats_bonus=dict(stats_bonus or {}),
    )


def _mk_player(inventory):
    return {
        "inventory": list(inventory),
        "equipment": {},
        "attributes": PlayerAttributes(base={"str": 15.0, "hp": 100.0, "mp": 30.0}),
        "in_battle": False,
    }


# ---------------------------------------------------------------------------
# 1. 注册表（data.gear_stats）
# ---------------------------------------------------------------------------
def test_b8_registry_keyspace_shape():
    assert GEAR_FLAT_KEYS[:3] == ("atk", "def", "dfn")
    assert "dfn_pct" in GEAR_PCT_KEYS and "atk_pct" in GEAR_PCT_KEYS
    assert "crit" in GEAR_COMBAT_KEYS and "earplug" in GEAR_COMBAT_KEYS
    assert GEAR_NUMERIC_KEYS == GEAR_FLAT_KEYS + GEAR_PCT_KEYS + GEAR_COMBAT_KEYS


def test_b8_extract_bonus_keeps_crit_pct_drops_zero_bool():
    cfg = {"atk": 10, "crit": -6, "dfn_pct": 5, "earplug": 1, "hp": 0, "usable": True, "desc": "x"}
    assert extract_bonus(cfg) == {"atk": 10.0, "crit": -6.0, "dfn_pct": 5.0, "earplug": 1.0}


def test_b8_route_bonus_splits_pct_layer():
    flat, pct = {}, {}
    route_bonus_into({"dfn_pct": 5, "atk": 6, "crit": 3}, flat, pct)
    route_bonus_into({"dfn_pct": 2}, flat, pct)  # 同层叠加
    assert flat == {"atk": 6.0, "crit": 3.0}
    assert pct == {"dfn": 7.0}


def test_b8_combatant_updates_caps_and_negative():
    up = combatant_updates({"crit": -12, "earplug": 5, "super_crit_lv": 4, "elem_crit_lv": 1})
    assert up["crit_bonus"] == -12.0
    assert up["earplug"] == 2.0
    assert up["super_crit_lv"] == 3.0
    assert up["elem_crit_lv"] == 1.0
    assert combatant_updates({}) == {}


# ---------------------------------------------------------------------------
# 2. 聚合拆层（EquipmentEngine 引擎级）
# ---------------------------------------------------------------------------
def test_b8_aggregate_splits_pct_and_keeps_crit():
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    bonus = {"atk": 6.0, "crit": 3.0, "dfn_pct": 5.0}
    sword = _mk_item("w1", "测试剑", "weapon", stats_bonus=bonus)
    player = _mk_player([sword])
    assert eng.equip(player, sword, "weapon")["ok"] is True
    snap = eng.aggregate_bonus(player)
    assert snap["flat"] == {"atk": 6.0, "crit": 3.0}
    assert snap["pct"] == {"dfn": 5.0}
    assert player["attributes"].bonus["pct"] == {"dfn": 5.0}


# ---------------------------------------------------------------------------
# 3. 实例化转换：context.add_item 路径
# ---------------------------------------------------------------------------
def test_b8_context_add_item_converts_crit_pct():
    from qbot_rpg.assembly.context import _inventory_hooks

    ctx = {"items": {"guji_x": {"name": "骨脊试刃", "slot": "weapon", "atk": 100,
                                "crit": 2, "dfn_pct": 5, "earplug": 1}}}
    hooks = _inventory_hooks(ctx)
    assert hooks["add_item"]("guji_x", 1) is True
    insts = ctx["inventory_instances"]
    want = {"atk": 100.0, "crit": 2.0, "dfn_pct": 5.0, "earplug": 1.0}
    assert insts and insts[-1]["stats_bonus"] == want


# ---------------------------------------------------------------------------
# 4. 实例化转换：shop_tx 路径（商店 dfn 回归钉死）
# ---------------------------------------------------------------------------
def test_b8_shop_instance_keeps_dfn_regression():
    items = {"yizhan_5_body": {"name": "驿站护甲", "slot": "body", "dfn": 8, "dfn_pct": 5}}
    inst = _new_default_instance("yizhan_5_body", 1, items)
    assert inst.stats_bonus.get("dfn") == 8.0
    assert inst.stats_bonus.get("dfn_pct") == 5.0


# ---------------------------------------------------------------------------
# 5. PVP/战斗桥 + pct 单位修正
# ---------------------------------------------------------------------------
def test_b8_combatant_of_bridge_and_pct_unit():
    player = {
        "qid": "10001", "name": "T", "level": 10, "hp": 500, "mp": 30,
        "attributes": {
            "base": {"atk": 100, "dfn": 50, "lck": 20},
            "bonus": {"flat": {"crit": -12, "earplug": 2, "super_crit_lv": 1, "atk": 10},
                      "pct": {"atk": 10, "dfn": 20}},
            "temp": {"flat": {}, "pct": {}},
            "cond": {},
        },
    }
    comb = _combatant_of(player)
    assert comb["crit_bonus"] == -12.0     # 赌狗负会心直通
    assert comb["earplug"] == 2            # 耳栓封顶
    assert comb["super_crit_lv"] == 1
    # pct 单位=百分点：atk=(100+10)*(1+10/100)=121；dfn=50*(1+20/100)=60
    assert comb["atk"] == 121
    assert comb["dfn"] == 60


# ---------------------------------------------------------------------------
# 6. 物品详情词条行（展示）
# ---------------------------------------------------------------------------
def test_b8_item_stat_parts_display():
    parts = _item_stat_parts({"atk": 10, "crit": 3, "dfn_pct": 5, "dfn": 0,
                              "earplug": 1, "super_crit_lv": 2})
    assert parts == ["攻击 10", "防御 +5%", "会心 +3%", "耳栓 Lv1", "超会心 Lv2"]
    assert _item_stat_parts({"crit": -12}) == ["会心 -12%"]


# ---------------------------------------------------------------------------
# 7. 编辑器字段表同源守卫（防漂移）
# ---------------------------------------------------------------------------
def test_b8_field_meta_covers_registry():
    from qbot_rpg.content.field_meta import default_field_meta_table

    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fields = tbl.module(mod).fields
        missing = [k for k in GEAR_NUMERIC_KEYS if k not in fields]
        assert not missing, f"{mod} 字段表缺键：{missing}"


# ---------------------------------------------------------------------------
# 8. veinborn 内容抽查（词条与赌狗武器落位 + 键空间防漂移）
# ---------------------------------------------------------------------------
def test_b8_veinborn_content_wired():
    items = json.loads((CONTENT / "items.json").read_text(encoding="utf-8"))
    by = {i["id"]: i for i in items}
    assert by["guji_blade_c"]["crit"] == 2
    assert by["yuanmai_blade_2"]["atk_pct"] == 5
    assert by["night_king_sword"]["atk_pct"] == 8
    assert by["night_king_seal"]["super_crit_lv"] == 1
    assert by["crystal_mane_pendant"]["earplug"] == 1
    assert by["haozhu_helm"]["earplug"] == 1
    fren = by["guji_blade_frenzy"]
    assert fren["crit"] == -12 and fren["atk"] == 273
    allowed = set(GEAR_NUMERIC_KEYS)
    for it in items:
        for k in it:
            if k.endswith("_pct") or k in ("crit", "earplug", "super_crit_lv", "elem_crit_lv"):
                assert k in allowed, (it["id"], k)
