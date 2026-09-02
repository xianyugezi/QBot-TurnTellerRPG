"""M13 全链路 e2e（tests/e2e/test_m13_fullchain_e2e.py · M13 批18 路18A）。

真实端到端：build_pack → 装配 → /注册 → /转职 → /攻击 → 战斗 → 变换 → 资源。
- /攻击 需装配快照（skill_slots_state 注入）才能解析技能（契约 §1.5）
- 资源轴/transform 需引擎注入位（_resource_registry/set_transform_def）

铁律：平台无关（零 NoneBot import）；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.skill_slots import assemble_slots, save_slots_to_state

DEMO = Path("content/test_demo")


def _pack_registry():
    """build_pack → registry（零红拦）。"""
    pack, _ = build_pack(DEMO)
    assert pack.report.ok, f"test_demo 应零红拦：{pack.report.errors}"
    return pack.registry


def _skills() -> Dict[str, Dict[str, Any]]:
    """战斗引擎技能表（狂战士触发技 + 形态技能 + 常态技能）。"""
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "power": 100, "mp_cost": 0},
        "rage_burst": {"id": "rage_burst", "name": "狂暴", "type": "active",
                        "kind": "damage", "power": 80, "mp_cost": 15,
                        "energy_cost": {"rage": 100}},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "power": 150, "mp_cost": 8},
        "fury_slash": {"id": "fury_slash", "name": "怒涛斩", "type": "active",
                        "kind": "damage", "power": 220, "mp_cost": 0,
                        "job_form": "berserker_form"},
    }


def _transform() -> Dict[str, Any]:
    """狂战士 transform 段（对齐 content/test_demo/jobs.json berserker）。"""
    return {
        "transform_skill": "rage_burst", "transform_to": "berserker_form",
        "form_name": "狂战士形态", "duration": "turns", "turns": 4,
        "revert": True, "cooldown": 5,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
    }


def _resource_registry() -> Dict[str, Dict[str, Any]]:
    """资源注册表（对齐 content/test_demo/stats.json rage）。"""
    return {
        "rage": {"name": "怒气", "type": "rage", "base": 0, "max": 100,
                 "reset": "battle"},
        "element_energy": {"name": "元素能量", "type": "element_energy",
                           "base": 0, "max_per_pool": 3,
                           "pools": ["fire", "water", "wind"], "reset": "battle"},
    }


def _ctx_with_slots(skills: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """战斗消费 ctx：装配快照 + skills 表（/攻击 解析前置）。"""
    snap = assemble_slots(list(skills.values()), {"job_id": "berserker"})
    return {"skills": skills, "skill_slots_state": snap}


def _engine(**over: Any) -> BattleEngine:
    eng = BattleEngine(defs=_skills(), **over)
    eng.set_transform_def(_transform())
    eng._resource_registry = _resource_registry()
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def _full_turn(eng: BattleEngine, action: Dict[str, Any]) -> Any:
    eng.do_action("player", action)
    eng.enemy_act()
    return eng.end_turn()


# ---------------------------------------------------------------------------
# 装配链路
# ---------------------------------------------------------------------------
def test_e2e_build_pack_registry() -> None:
    """build_pack → registry 技能/职业可解析（零红拦）。"""
    reg = _pack_registry()
    assert reg.resolve("rage_burst", "skill") is not None
    assert reg.resolve("berserker", "job") is not None
    assert reg.resolve("alchemy", "job") is not None  # 生活职业


def test_e2e_assemble_slots_and_persist() -> None:
    """装配快照落档（/攻击 消费前置）。"""
    skills = _skills()
    snap = assemble_slots(list(skills.values()), {"job_id": "berserker"})
    ps: Dict[str, Any] = {"persistent_state": {}}
    save_slots_to_state(ps, snap)
    loaded = ps["persistent_state"]["skill_slots"]
    assert loaded["slots"][0]["slot"] == "basic"
    assert any(s["skill_id"] == "rage_burst" for s in loaded["slots"])


# ---------------------------------------------------------------------------
# 战斗链路
# ---------------------------------------------------------------------------
def test_e2e_battle_skill_cast() -> None:
    """/攻击 强力斩击 → 技能施放 → 伤害 + MP 扣费。"""
    from qbot_rpg.commands.battle_commands import _attack_action

    class _P:
        args = ["强力斩击"]
        error = ""

    ctx = _ctx_with_slots(_skills())
    action, err = _attack_action(_P(), ctx)
    assert err is None and action == {"type": "skill", "skill_id": "power_strike"}
    eng = _engine()
    out = eng.do_action("player", action)
    assert out.ok is True, f"技能应成功，got {out.message}"
    assert eng.battle_state()["player"]["mp"] == 92
    assert eng.battle_state()["enemy"]["hp"] < 500


def test_e2e_battle_attack_unequipped_rejected() -> None:
    """未装配技能（不在装配快照）→ /攻击 拒绝。"""
    from qbot_rpg.commands.battle_commands import _attack_action

    class _P:
        args = ["火球术"]
        error = ""

    ctx = _ctx_with_slots(_skills())  # 装配快照无 fireball
    action, err = _attack_action(_P(), ctx)
    assert action is None and err, "未装配技能应被拒"


# ---------------------------------------------------------------------------
# 变换链路
# ---------------------------------------------------------------------------
def test_e2e_transform_full_cycle() -> None:
    """满怒狂暴 → 形态切换 → 回合 tick → 自然还原 → 冷却。"""
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] == "berserker_form", f"应切换形态，got {ts}"
    # 触发当回合 remaining=4，_full_turn 的 end_turn tick 已递减 → 3
    assert ts["remaining"] == 3, f"remaining 应=3（4-1 tick），got {ts}"
    # 形态技能怒涛斩可用
    out = eng.do_action("player", {"type": "skill", "skill_id": "fury_slash"})
    assert out.ok is True, f"形态技能应可用，got {out.message}"
    # 走完回合 → 自然还原
    for _ in range(5):
        _full_turn(eng, {"type": "normal"})
    ts2 = eng.battle_state()["transform_state"]
    assert ts2["form"] is None, f"应自然还原，got {ts2}"


# ---------------------------------------------------------------------------
# 资源链路
# ---------------------------------------------------------------------------
def test_e2e_resource_lifecycle() -> None:
    """资源全生命周期：战斗开始置 base → 消耗 → 清零。"""
    eng = _engine()
    # battle_start_init 置 base（rage=0）
    rs0 = eng.battle_state()["resource_state"]
    assert rs0["player"]["rage"] == 0, f"战斗开始 rage 应置 base 0，got {rs0}"
    # 满怒狂暴 → 消耗 100 → 0
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert eng.battle_state()["resource_state"]["player"]["rage"] == 0


# ---------------------------------------------------------------------------
# 注册/转职链路（纯函数指令壳）
# ---------------------------------------------------------------------------
def test_e2e_register_and_job_switch() -> None:
    """/注册 默认职业 + /转职 切换（B7 链 + 装配联动）。"""
    from qbot_rpg.commands.register_commands import cmd_register, default_job

    jobs = {
        "berserker": {"name": "狂战士", "recommended_newbie": False},
        "alchemy": {"name": "炼金术师", "recommended_newbie": True},
    }

    class _P:
        args = ["测试玩家"]
        error = ""
        fixed_subword = None

    ctx: Dict[str, Any] = {
        "jobs": jobs,
        "settings": {},
        "qq_id": "123456",
        "name_exists": None,
        "persistent_state": {},
        "skills": _skills(),
        "player": None,
        "registered": False,
        "now": 0,
    }
    out = cmd_register(_P(), ctx)
    assert isinstance(out, str) and out
    # 无参转职 → 默认职业（recommended_newbie 优先 = alchemy）
    dj = default_job(ctx)
    assert dj is not None and dj["id"] == "alchemy", f"默认职业应 alchemy，got {dj}"


def test_e2e_job_switch_updates_slots() -> None:
    """/转职 狂战士 → job_id 更新 + 装配联动。"""
    from qbot_rpg.commands.job_commands import cmd_job

    class _P:
        args = ["狂战士"]
        error = ""
        raw = "/转职 狂战士"

    ctx: Dict[str, Any] = {
        "jobs": {
            "berserker": {"name": "狂战士", "recommended_newbie": False},
            "alchemy": {"name": "炼金术师", "recommended_newbie": True},
        },
        "job_id": "alchemy",
        "player": {"job_id": "alchemy", "persistent_state": {}},
        "persistent_state": {},
        "skills": _skills(),
        "now": 0,
    }
    out = cmd_job(_P(), ctx)
    assert "狂战士" in out and "成功" in out
    assert ctx["player"]["job_id"] == "berserker"


# ---------------------------------------------------------------------------
# 快照续战
# ---------------------------------------------------------------------------
def test_e2e_snapshot_resume_carries_state() -> None:
    """战斗快照 round-trip：transform + resource 双段续战。"""
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    snap = eng.to_snapshot()
    assert snap["transform_state"]["form"] == "berserker_form"
    eng2 = BattleEngine.from_snapshot(snap, resource_registry=_resource_registry())
    ts2 = eng2.battle_state()["transform_state"]
    assert ts2["form"] == "berserker_form", f"恢复应带形态，got {ts2}"
