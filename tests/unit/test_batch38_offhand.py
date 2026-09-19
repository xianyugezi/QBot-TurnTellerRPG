"""批38 · ②（H7）副手开关与副手规则单测（引擎级证据 + 关闭对拍）。

依据：`docs/深度打造_决策记录.md` §一 H7 + §二（数值裁定权）+ §五 5.2（开关落点/关闭语义）；
需求源头 `打造系统_原案_20260919.md` §2/§12（单手作副手 50% + 五类加成不激活）；
明细 `打造系统_C_工程落地与风险.md` Q3（归一放 slot_defs、数值/失活在 aggregate_bonus，
技能/套装/符文失活放各自读取点）。

覆盖：
  A. **关闭 → 逐字段一致（对拍）**：开关缺省/false 时 aggregate_bonus 与既有聚合口径逐字段相等；
  B. **开启 → 折算与失活**：数值类 ×scale、`_pct`/战斗键/stats_pct 不激活；副手类装备不折算；
  C. **开启 → 装配放宽**：主手槽类型件（武器）可进 role=offhand 槽；关闭时仍拒绝；
  D. **五类失活各自可测**：α1 技能授予 / α3 增幅 / α5 普攻替换 / α6 职业覆盖（equip_mods 唯一
     枚举点）+ 套装件数（forge_sets）+ 符文孔位（jewel）；
  E. **编辑器可选项**：settings.equipment_offhand 元数据（中文名/说明/默认）+ 装配层注入。

测试只构造内存玩家状态与临时模块映射，不写任何真实内容包。
"""
from __future__ import annotations

import random
from types import SimpleNamespace
from typing import Any, Dict, List

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core import equip_mods as em
from qbot_rpg.core.equipment import (
    DEFAULT_OFFHAND_SCALE,
    EquipmentEngine,
    normalize_offhand_config,
    offhand_penalized_item_ids,
    slot_role_of,
)
from qbot_rpg.core.forge_sets import penalized_set_slots, set_lookup
from qbot_rpg.core.jewel import JewelSystem
from qbot_rpg.core.player_attributes import PlayerAttributes
from qbot_rpg.data.gear_stats import route_bonus_into
from qbot_rpg.data.item import ItemInstance

# ---------------------------------------------------------------------------
# 构造器（内存玩家状态；不写内容包）
# ---------------------------------------------------------------------------
SLOTS: Dict[str, Any] = {
    "weapon": {"name": "武器", "max": 1},
    "offhand": {"name": "副手", "max": 1, "role": "offhand"},
    "head": {"name": "头部", "max": 1},
}
ON: Dict[str, Any] = {"enabled": True, "single_hand_scale": 0.5}


def _item(item_id: str, slot: str, stats: Dict[str, float], **kw: Any) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                        bound=False, stack_max=1, slot=slot, stats_bonus=dict(stats), **kw)


def _player(rows: List[ItemInstance], equipment: Dict[str, Any]) -> Dict[str, Any]:
    return {"inventory": list(rows), "equipment": dict(equipment),
            "attributes": PlayerAttributes(), "persistent_state": {}}


def _worn(rows: List[ItemInstance], equipment: Dict[str, Any]):
    """(slot_id, row) 列表（确定性槽序）。"""
    out = []
    for slot_id in sorted(equipment):
        iid = equipment[slot_id]["item_id"] if isinstance(equipment[slot_id], dict) \
            else equipment[slot_id].item_id
        row = next((r for r in rows if r.item_id == iid), None)
        if row is not None:
            out.append((slot_id, row))
    return out


def _reference_snapshot(rows: List[ItemInstance], equipment: Dict[str, Any]):
    """既有聚合口径（batch38 之前）：全部已穿戴件 stats_bonus 直通 route_bonus_into。"""
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    for _slot, row in _worn(rows, equipment):
        route_bonus_into(row.stats_bonus, flat, pct)
    return {"flat": flat, "pct": pct}


_FULL_STATS = {"atk": 100.0, "hp": 50.0, "atk_pct": 20.0, "crit": 7.0, "pierce_pct": 5.0}


# ===========================================================================
# A. 关闭 → 逐字段一致（对拍）
# ===========================================================================
def test_off_switch_matches_reference_field_by_field() -> None:
    """开关缺省 / 显式 false：aggregate_bonus 与该系统引入前口径**逐字段相等**。"""
    scenarios = [
        # (背包装备, 穿戴表)
        ([_item("sword", "weapon", _FULL_STATS)], {"weapon": {"item_id": "sword"}}),
        # 主手件放进副手槽（关闭时不允许装配，但直接构造状态仍应逐字段一致）
        ([_item("sword", "weapon", _FULL_STATS)], {"offhand": {"item_id": "sword"}}),
        ([_item("sword", "weapon", _FULL_STATS), _item("shield", "offhand", {"dfn": 30.0})],
         {"weapon": {"item_id": "sword"}, "offhand": {"item_id": "shield"}}),
        ([_item("hat", "head", {"hp": 10.0, "hp_pct": 5.0})], {"head": {"item_id": "hat"}}),
    ]
    for rows, equipment in scenarios:
        p = _player([_item(r.item_id, r.slot, dict(r.stats_bonus)) for r in rows], equipment)
        expected = _reference_snapshot(p["inventory"], equipment)
        for cfg in (None, {"enabled": False}, {"enabled": False, "single_hand_scale": 0.5}):
            eng = EquipmentEngine(slots=SLOTS, offhand=cfg)
            assert eng.aggregate_bonus(p) == expected, (rows, equipment, cfg)
            assert eng.penalized_slots(p) == frozenset()
    # 缺省尺度 = 0.5（包声明可配；不改则用默认）
    assert normalize_offhand_config(None) == {"enabled": False,
                                             "single_hand_scale": DEFAULT_OFFHAND_SCALE}


def test_off_switch_slot_roles_default_main() -> None:
    """槽位角色缺省 main；显式 offhand 才归一为 offhand（归一入口唯一）。"""
    eng = EquipmentEngine(slots=SLOTS, offhand=ON)
    assert eng.slot_role("weapon") == "main"
    assert eng.slot_role("head") == "main"
    assert eng.slot_role("offhand") == "offhand"
    assert slot_role_of({"role": "不合法"}) == "main"  # 防御性：非法 → main（校验器红拦）


# ===========================================================================
# B. 开启 → 数值折算与失活
# ===========================================================================
def test_on_switch_scales_flat_and_deactivates_pct_and_combat() -> None:
    """单手武器作副手：flat ×0.5；`_pct` 键、战斗键、stats_pct 钩子一律不激活。"""
    row = _item("sword", "weapon", _FULL_STATS)
    p = _player([row], {"offhand": {"item_id": "sword"}})
    eng = EquipmentEngine(slots=SLOTS, offhand=ON)
    snap = eng.aggregate_bonus(p)
    assert snap["flat"] == {"atk": 50.0, "hp": 25.0}          # 数值类 ×0.5
    assert snap["pct"] == {}                                   # 百分比不激活
    assert "crit" not in snap["flat"] and "pierce_pct" not in snap["flat"]  # 战斗键不激活
    assert eng.penalized_slots(p) == frozenset({"offhand"})
    assert offhand_penalized_item_ids(p, SLOTS, ON) == frozenset({"sword"})


def test_on_switch_stats_pct_hook_deactivated() -> None:
    """`stats_pct` 钩子（对象行形态，getattr 读取）在副手折算槽不激活；开关关 → 照常聚合。"""
    row = SimpleNamespace(item_id="sword", slot="weapon", stats_bonus={},
                          stats_pct={"atk": 9.0})
    p = _player([row], {"offhand": {"item_id": "sword"}})
    assert EquipmentEngine(slots=SLOTS, offhand=ON).aggregate_bonus(p)["pct"] == {}
    assert EquipmentEngine(slots=SLOTS, offhand=None).aggregate_bonus(p)["pct"] == {"atk": 9.0}



def test_on_switch_offhand_category_item_not_penalized() -> None:
    """副手类装备（件自身可装备槽 = offhand）享受本身效果，不折算（原案 §12）。"""
    p = _player([_item("shield", "offhand", {"dfn": 30.0, "dfn_pct": 4.0})],
                {"offhand": {"item_id": "shield"}})
    eng = EquipmentEngine(slots=SLOTS, offhand=ON)
    snap = eng.aggregate_bonus(p)
    assert snap["flat"] == {"dfn": 30.0}
    assert snap["pct"] == {"dfn": 4.0}
    assert eng.penalized_slots(p) == frozenset()


def test_on_switch_scale_is_configurable_not_hardcoded() -> None:
    """折算比例由包声明驱动（0.25 → 数值类 ×0.25）。"""
    p = _player([_item("sword", "weapon", {"atk": 100.0})], {"offhand": {"item_id": "sword"}})
    eng = EquipmentEngine(slots=SLOTS, offhand={"enabled": True, "single_hand_scale": 0.25})
    assert eng.aggregate_bonus(p)["flat"] == {"atk": 25.0}


# ===========================================================================
# C. 开启 → 装配放宽（单手武器可进副手槽）
# ===========================================================================
def test_on_switch_allows_weapon_into_offhand_slot() -> None:
    eng = EquipmentEngine(slots=SLOTS, offhand=ON)
    p = _player([_item("sword", "weapon", {"atk": 10.0})], {})
    res = eng.equip(p, p["inventory"][0], "offhand")
    assert res["ok"] is True and res["slot"] == "offhand"


def test_off_switch_still_rejects_weapon_into_offhand_slot() -> None:
    """关闭 → EQP-02 部位匹配口径不变（武器进副手槽 = 这个位置穿不上）。"""
    eng = EquipmentEngine(slots=SLOTS, offhand=None)
    p = _player([_item("sword", "weapon", {"atk": 10.0})], {})
    res = eng.equip(p, p["inventory"][0], "offhand")
    assert res["ok"] is False and res["reason"] == "slot_mismatch"


# ===========================================================================
# D. 五类失活各自可测
# ===========================================================================
def _mods_ctx(enabled: bool) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "items": {
            "sword": {
                "id": "sword",
                "grant_skills": [{"skill": "fireball", "level": 3}],
                "skill_amp": [{"skill": "fireball", "type": "damage", "value": 50}],
                "attack_override": {"enabled": True, "skill": "fireball", "chance": 100},
                "job_override": {"job": "mage", "level_reset": False, "name_override": "法师"},
            },
        },
        "slots": {"slots": SLOTS},
    }
    if enabled:
        ctx["equipment_offhand"] = dict(ON)
    return ctx


def test_equip_mods_alpha_group_deactivated_when_penalized() -> None:
    """α1/α3/α5/α6 四类在同一枚举点失活（开关开）；开关关 → 全部恢复。"""
    eq = {"offhand": {"item_id": "sword"}}

    def _player_row() -> Dict[str, Any]:
        return _player([_item("sword", "weapon", {})], eq)

    # α1 技能授予
    on = _player_row()
    assert em.recompute_equip_skills(on, _mods_ctx(True)) == {}
    off = _player_row()
    assert em.recompute_equip_skills(off, _mods_ctx(False)) == {"fireball": 3}

    # α3 增幅
    assert em.skill_amp_table(_player_row(), _mods_ctx(True)) == {}
    assert em.skill_amp_table(_player_row(), _mods_ctx(False)) == {
        "player": {"fireball": {"damage": 50}}}

    # α5 普攻替换（需已授予技能；副手失活 → 未授予 → 不替换）
    p_on = _player_row()
    em.recompute_equip_skills(p_on, _mods_ctx(True))
    assert em.resolve_attack_override(_mods_ctx(True), p_on,
                                      rng=random.Random(1)) is None
    p_off = _player_row()
    em.recompute_equip_skills(p_off, _mods_ctx(False))
    assert em.resolve_attack_override(_mods_ctx(False), p_off,
                                      rng=random.Random(1)) == "fireball"

    # α6 职业覆盖
    p6_on = _player_row()
    assert em.recompute_job_override(p6_on, _mods_ctx(True)) == {}
    p6_off = _player_row()
    assert em.recompute_job_override(p6_off, _mods_ctx(False)).get("job") == "mage"


def test_set_piece_count_excludes_penalized_offhand() -> None:
    """套装件数统计处：副手折算件不计入件数（开关开）；开关关 → 计入。"""
    rows = [_item("sword", "weapon", {})]
    p = _player(rows, {"offhand": {"item_id": "sword"}})
    p["equipped"] = [{"node_id": "p_weapon", "slot": "weapon"},
                     {"node_id": "p_offhand", "slot": "offhand"}]
    sets = [{"id": "sunset", "name": "落日",
             "pieces": ["p_weapon", "p_offhand", "p_head"]}]

    mods_on = {"settings": {"slot_defs": SLOTS, "equipment_offhand": dict(ON),
                            "forge": {"set_piece_counts": [2, 3]}}}
    mods_off = {"settings": {"slot_defs": SLOTS, "forge": {"set_piece_counts": [2, 3]}}}
    assert penalized_set_slots(p, mods_on) == frozenset({"offhand"})
    assert set_lookup(p, sets, piece_counts=mods_on)[0]["pieces_have"] == 1
    assert set_lookup(p, sets, piece_counts=mods_off)[0]["pieces_have"] == 2


def test_jewel_active_sockets_empty_for_penalized_offhand() -> None:
    """符文孔位读取处：副手折算件 → 无激活孔位；开关关 → 与定义一致。"""
    js = JewelSystem(settings={})
    p = _player([_item("sword", "weapon", {})], {"offhand": {"item_id": "sword"}})
    socket_defs = {"sword": [{"slot_level": 1}, {"slot_level": 2}, {"slot_level": 3}]}
    base = {"player": p, "slots": {"slots": SLOTS}, "slot_defs": socket_defs}
    on = dict(base, equipment_offhand=dict(ON))
    off = dict(base)
    assert js.offhand_inactive(on, "sword") is True
    assert js.active_sockets(on, "sword") == []
    assert js.offhand_inactive(off, "sword") is False
    assert len(js.active_sockets(off, "sword")) == 3


# ===========================================================================
# E. 编辑器可选项 + 校验器
# ===========================================================================
def test_editor_metadata_has_offhand_switch_with_label_and_help() -> None:
    """部位设置面可见「是否启用副装备」：元数据 + 中文名 + 说明卡。"""
    table = default_field_meta_table()
    settings_meta = table.module("settings")
    assert settings_meta is not None
    fm = settings_meta.fields["equipment_offhand"]
    assert fm.type == "obj" and fm.label == "副手装备" and fm.help
    assert fm.children["enabled"].type == "bool"
    assert fm.children["enabled"].label == "是否启用副装备"
    assert fm.children["enabled"].help and fm.children["enabled"].default is False
    assert fm.children["single_hand_scale"].type == "number"
    assert fm.children["single_hand_scale"].help


def test_validator_offhand_switch_red_and_clean() -> None:
    """开关段：合法 → 0 错；结构/类型/区间非法 → 红拦。"""
    ok = check_pack({"settings": {"equipment_offhand": {
        "enabled": True, "single_hand_scale": 0.5}}})
    assert [(e.field, e.detail.get("rule")) for e in ok.errors] == []
    assert [(e.field, e.detail.get("rule")) for e in
            check_pack({"settings": {"equipment_offhand": {"enabled": False}}}).errors] == []
    bad_struct = check_pack({"settings": {"equipment_offhand": 3}}).errors
    assert any(e.detail.get("rule") == "section_structure" for e in bad_struct)
    bad_type = check_pack({"settings": {"equipment_offhand": {"enabled": "yes"}}}).errors
    assert any(e.field.endswith(".enabled") and e.detail.get("rule") == "type" for e in bad_type)
    bad_range = check_pack({"settings": {"equipment_offhand": {"single_hand_scale": 2}}}).errors
    assert any(e.detail.get("rule") == "ratio_out_of_range" for e in bad_range)


def test_engine_adapter_forwards_offhand_config() -> None:
    """指令壳适配层：offhand 配置透传引擎；跨模块读取点（equip_mods）经适配器取同源判定。"""
    from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter

    adapter = EquipmentEngineAdapter(slots=SLOTS, offhand=dict(ON))
    assert adapter._engine.offhand_active() is True
    assert adapter._engine.offhand_scale() == 0.5
    p = _player([_item("sword", "weapon", {})], {"offhand": {"item_id": "sword"}})
    assert adapter.penalized_slots(p) == frozenset({"offhand"})
    # 关闭（缺省）：不折算
    off_adapter = EquipmentEngineAdapter(slots=SLOTS)
    assert off_adapter._engine.offhand_active() is False
    assert off_adapter.penalized_slots(p) == frozenset()
