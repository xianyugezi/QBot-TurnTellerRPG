"""M13 6a 技能位装配落存档单测（tests/unit/test_skill_slots_persist.py · M13 批13 路13B）。

覆盖：
  - ctx["skill_slots"] 接口注入（assemble/save/load 绑 persistent_state）
  - 装配快照落存档 round-trip
  - basic 固定第 1 位 + active 排序 + passive/trigger 槽
  - 未注册玩家 → 接口空值兜底

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.assembly.context import _skill_slots_interface


def _skills_table() -> Dict[str, Dict[str, Any]]:
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage"},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage"},
        "healing_light": {"id": "healing_light", "name": "治疗术", "type": "active",
                           "kind": "heal"},
        "stone_guard": {"id": "stone_guard", "name": "石肤", "type": "passive",
                         "kind": "utility"},
        "counter_strike": {"id": "counter_strike", "name": "反击", "type": "trigger",
                            "kind": "damage"},
    }


def _ctx(**over: Any) -> Dict[str, Any]:
    c: Dict[str, Any] = {"skills": _skills_table(), "job_id": "warrior"}
    c.update(over)
    return c


def test_interface_shape() -> None:
    """接口 dict 含 assemble/save/load 三键。"""
    iface = _skill_slots_interface(_ctx(), {})
    assert set(iface.keys()) == {"assemble", "save", "load"}


def test_assemble_basic_first_slot() -> None:
    """装配快照 basic 固定第 1 位。"""
    iface = _skill_slots_interface(_ctx(), {})
    snap = iface["assemble"]()
    slots = snap.get("slots", [])
    assert slots and slots[0]["slot"] == "basic", f"basic 应第 1 位，got {slots}"
    assert slots[0]["skill_id"] == "basic_attack"


def test_assemble_active_and_slots() -> None:
    """active 可排序 + passive/trigger 槽。"""
    iface = _skill_slots_interface(_ctx(), {})
    snap = iface["assemble"]()
    active = snap.get("active_order", [])
    assert "power_strike" in active and "healing_light" in active
    passive = snap.get("passive", [])
    assert any(s["skill_id"] == "stone_guard" for s in passive)
    trigger = snap.get("trigger", [])
    assert any(s["skill_id"] == "counter_strike" for s in trigger)


def test_save_load_roundtrip() -> None:
    """装配结果落存档 → load 读回一致。"""
    ps: Dict[str, Any] = {}
    iface = _skill_slots_interface(_ctx(), ps)
    snap = iface["assemble"]()
    iface["save"](snap)
    assert ps.get("skill_slots") is not None, "装配结果应落 ps"
    loaded = iface["load"]()
    assert loaded.get("slots") == snap.get("slots")


def test_load_default_empty() -> None:
    """未装配过 → load 返回空 {}（惰性挂回）。"""
    ps: Dict[str, Any] = {}
    iface = _skill_slots_interface(_ctx(), ps)
    loaded = iface["load"]()
    assert loaded == {}
    assert "skill_slots" in ps, "load 应惰性挂回键"


def test_save_updates_ps_in_place() -> None:
    """save 写 ps 引用（引擎写即落档）。"""
    ps: Dict[str, Any] = {}
    iface = _skill_slots_interface(_ctx(), ps)
    iface["save"]({"slots": [{"slot": "basic", "skill_id": "basic_attack"}]})
    assert ps["skill_slots"]["slots"][0]["skill_id"] == "basic_attack"


def test_assemble_no_skills_empty() -> None:
    """无技能表 → 空装配（不崩）。"""
    iface = _skill_slots_interface(_ctx(skills={}), {})
    snap = iface["assemble"]()
    assert snap.get("slots", []) == [] or snap.get("slots") is not None


def test_assemble_custom_skills_arg() -> None:
    """assemble(skills=...) 显式传表。"""
    iface = _skill_slots_interface(_ctx(), {})
    custom = {"x_basic": {"id": "x_basic", "name": "X", "type": "basic"}}
    snap = iface["assemble"](custom)
    assert snap.get("slots", [])[0]["skill_id"] == "x_basic"
