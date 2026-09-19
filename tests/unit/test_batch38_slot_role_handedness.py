"""批38 · ③ 槽位角色 role + 装备/物品手数 handedness 字段登记与校验单测。

依据：`docs/深度打造_决策记录.md` §五 5.1/5.2 + 批38 任务 ③（枚举合法；副手部位在开关
关闭时声明 → 黄提示不硬拦；编辑器可见；不做数值实现）。

覆盖：
  A. 元数据登记：slot_defs.role（enum main/offhand + 中文名 + 说明）、
     items/equipment.handedness（enum one_hand/two_hand + 中文名 + 说明）；
  B. 编辑器可见：settings.slot_defs 键值表出 role 下拉列（中文名）；
  C. 校验器：role 非法枚举红拦 / role=offhand 且开关关 → 黄提示（不红拦）/ 开关开 → 干净；
     handedness 非法枚举红拦 / 合法与缺省 → 干净；
  D. 缺省语义：role 缺省 = main（引擎归一，②已测）；handedness 缺省 = 未声明（不限制）。

测试只读框架元数据 / 内存模块映射，不写内容包。
"""
from __future__ import annotations

from pathlib import Path

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equipment import EquipmentEngine, slot_role_of
from qbot_rpg.web import api

CONTENT = Path(api.repo_root()) / "content"


def _rules(report: object, attr: str) -> list:
    return [(x.field, x.detail.get("rule")) for x in getattr(report, attr)]


# ===========================================================================
# A. 元数据登记
# ===========================================================================
def test_slot_defs_role_field_registered() -> None:
    table = default_field_meta_table()
    settings_meta = table.module("settings")
    assert settings_meta is not None
    slot_defs = settings_meta.fields["slot_defs"]
    assert "role" in slot_defs.children
    role = slot_defs.children["role"]
    assert role.type == "enum" and role.enum == ("main", "offhand")
    assert role.label == "部位角色" and role.help and role.default == "main"


def test_handedness_field_registered_on_items_and_equipment() -> None:
    table = default_field_meta_table()
    for mod in ("items", "equipment"):
        mmeta = table.module(mod)
        assert mmeta is not None
        fm = mmeta.fields["handedness"]
        assert fm.type == "enum" and fm.enum == ("one_hand", "two_hand")
        assert fm.label == "手数" and fm.help


# ===========================================================================
# B. 编辑器可见（键值表 role 下拉列）
# ===========================================================================
def test_editor_slot_defs_role_column_selectable() -> None:
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    assert d["whole_table"] is True
    kv = d["fields"][0]["kv_table"]
    cols = {c["key"]: c for c in kv["columns"]}
    assert cols["role"]["control"] == "select"
    assert cols["role"]["enum"] == ["main", "offhand"]
    assert cols["role"]["label"] == "部位角色"
    assert cols["role"]["meta_unregistered"] is False


# ===========================================================================
# C. 校验器
# ===========================================================================
def test_validator_role_enum_and_switch_warning() -> None:
    # 非法枚举 → 红拦
    bad = check_pack({"settings": {"slot_defs": {
        "offhand": {"name": "副手", "max": 1, "role": "sub"}}}})
    assert ("settings.slot_defs.offhand.role", "enum_invalid") in _rules(bad, "errors")
    # role=offhand 但开关关闭 → 黄提示（不硬拦：errors 为空）
    off = check_pack({"settings": {"slot_defs": {
        "offhand": {"name": "副手", "max": 1, "role": "offhand"}}}})
    assert _rules(off, "errors") == []
    assert ("settings.slot_defs.offhand.role", "offhand_role_without_switch") in _rules(
        off, "warnings")
    # 开关开启 → 无黄
    on = check_pack({"settings": {
        "slot_defs": {"offhand": {"name": "副手", "max": 1, "role": "offhand"}},
        "equipment_offhand": {"enabled": True}}})
    assert _rules(on, "errors") == [] and _rules(on, "warnings") == []
    # 缺省（无 role）→ 干净
    clean = check_pack({"settings": {"slot_defs": {"weapon": {"name": "武器", "max": 1}}}})
    assert _rules(clean, "errors") == [] and _rules(clean, "warnings") == []


def test_validator_handedness_enum() -> None:
    bad = check_pack({"items": [{"id": "x", "name": "x", "type": "武器",
                                 "handedness": "three_hand"}]})
    assert any(f == "items.0.handedness" for f, _ in _rules(bad, "errors"))
    ok = check_pack({"items": [{"id": "x", "name": "x", "type": "武器",
                                "handedness": "one_hand"}]})
    assert _rules(ok, "errors") == []
    absent = check_pack({"items": [{"id": "x", "name": "x", "type": "武器"}]})
    assert _rules(absent, "errors") == []


# ===========================================================================
# D. 缺省语义
# ===========================================================================
def test_role_defaults_to_main_when_absent() -> None:
    assert slot_role_of({}) == "main"
    eng = EquipmentEngine(slots={"weapon": {"name": "武器"}, "offhand": {"name": "副手"}})
    assert eng.slot_role("offhand") == "main"  # 未声明 role → main
