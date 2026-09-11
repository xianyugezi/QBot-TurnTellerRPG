"""M13 全链路冒烟（tests/unit/test_m13_smoke.py · M13 批17 路17A）。

覆盖装配/战斗/变换/资源/季节全链路（真实驱动）：
  - build_pack → registry skills/jobs 登记
  - 装配：assemble_slots 快照 + save/load round-trip
  - 战斗：/攻击 <技能> → skill_id → 伤害 → MP 扣费
  - 变换：触发技 → 形态切换 → 自然还原 → 冷却
  - 资源：energy_gain/cost 增减
  - 季节：换季检测/事件

CTB 迁移（2026-09-10）：旧 round 语义 → CTB 语义。
  - 旧「一轮」= `do_action`（玩家先手）→ `enemy_act`（怪物后手）→ `end_turn`（⑥tick
    收尾）三段；`enemy_act`/`end_turn` 已按 Wave A M4/M5 删除（保留壳抛
    NotImplementedError），旧三段合并为**一次 `player_act`**（提交玩家行动 + 调度器
    自动推进 NPC 连锁）。
  - 旧断言「经过 N 回合」→「执行 N 次 `player_act`」；旧「回合数 turn」→ 权威计量
    `battle_state()["action_seq"]`（`turn` 仅为 action_seq 镜像，不再作进度断言）。
  - 变换（transform）的形态计时在 CTB 下按**持有者行动次数**推进：形态属玩家，
    故每次玩家 `player_act` 后 remaining/cooldown 递减一拍 —— 与旧「回合 tick」等价。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.skill_slots import assemble_slots, load_slots_from_state, save_slots_to_state

DEMO = Path("content/test_demo")


def _skills() -> Dict[str, Dict[str, Any]]:
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                          "kind": "damage", "power": 100, "mp_cost": 0},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                          "kind": "damage", "power": 150, "mp_cost": 8},
        "rage_burst": {"id": "rage_burst", "name": "狂暴", "type": "active",
                        "kind": "damage", "power": 80, "mp_cost": 15,
                        "energy_cost": {"rage": 100}},
    }


def _transform() -> Dict[str, Any]:
    return {
        "transform_skill": "rage_burst", "transform_to": "berserker_form",
        "form_name": "狂战士形态", "duration": "turns", "turns": 4,
        "revert": True, "cooldown": 5,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
    }


def _engine(**over: Any) -> BattleEngine:
    eng = BattleEngine(defs=_skills(), **over)
    eng.set_transform_def(_transform())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    return eng


def _player_act(eng: BattleEngine, action: Dict[str, Any]) -> Any:
    """CTB 单次玩家行动：提交一次行动 + 调度器自动推进 NPC 连锁。

    CTB 迁移（2026-09-10）：替代旧 `_full_turn`（player do_action → enemy_act →
    end_turn 三段）。CTB 下一次 `player_act` 即承载「玩家一拍 + 后续自动推进」，
    故「一次玩家行动」= 一次调用。
    """
    return eng.player_act(action)


# ---------------------------------------------------------------------------
# 装配链路
# ---------------------------------------------------------------------------
def test_build_pack_registry_skills_jobs() -> None:
    """build_pack → registry 登记 skills/jobs（零红拦）。"""
    pack, _ = build_pack(DEMO)
    assert pack.report.ok, f"test_demo 应零红拦：{pack.report.errors}"
    assert pack.registry.resolve("rage_burst", "skill") is not None, "技能应可解析"
    assert pack.registry.resolve("berserker", "job") is not None, "职业应可解析"


def test_assemble_slots_snapshot_shape() -> None:
    """装配快照：basic 第 1 位 + active 排序 + passive/trigger 槽。"""
    snap = assemble_slots(list(_skills().values()), {"job_id": "warrior"})
    slots = snap.get("slots", [])
    assert slots[0]["slot"] == "basic", "basic 应第 1 位"
    assert any(s["skill_id"] == "power_strike" for s in slots)


def test_assemble_save_load_roundtrip() -> None:
    """装配落存档 → load 读回一致。"""
    ps: Dict[str, Any] = {"persistent_state": {}}
    snap = assemble_slots(list(_skills().values()), {"job_id": "warrior"})
    save_slots_to_state(ps, snap)
    loaded = load_slots_from_state(ps)
    assert loaded.get("slots") == snap.get("slots")


# ---------------------------------------------------------------------------
# 战斗链路
# ---------------------------------------------------------------------------
def test_battle_skill_cast_damage() -> None:
    """技能施放 → 伤害 + MP 扣费。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.ok is True, f"技能应成功，got {out.message}"
    assert eng.battle_state()["player"]["mp"] == 92, \
        f"MP 应扣 8，got {eng.battle_state()['player']['mp']}"
    assert eng.battle_state()["enemy"]["hp"] < 500, "应有伤害"


def test_battle_normal_attack() -> None:
    """普攻正常。"""
    eng = _engine()
    out = eng.do_action("player", {"type": "normal"})
    assert out.ok is True


# ---------------------------------------------------------------------------
# 变换链路
# ---------------------------------------------------------------------------
def test_transform_trigger_form_and_revert() -> None:
    """触发技 → 形态切换 → 自然还原（CTB：形态按持有者行动次数计时）。"""
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _player_act(eng, {"type": "skill", "skill_id": "rage_burst"})
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] == "berserker_form", f"应切换形态，got {ts}"
    # CTB：形态 remaining（turns=4）按玩家行动次数递减；再执行 3 次玩家行动走完剩余拍
    for _ in range(3):
        _player_act(eng, {"type": "normal"})
    ts2 = eng.battle_state()["transform_state"]
    assert ts2["form"] is None, f"形态应自然还原，got {ts2}"
    # CTB 进度权威：形态走完 = action_seq 严格前进（不再用回合数断言）
    assert int(eng.battle_state()["action_seq"]) > 0, "行动计数应已推进"


# ---------------------------------------------------------------------------
# 资源链路
# ---------------------------------------------------------------------------
def test_resource_gain_and_cost() -> None:
    """energy_gain 增加 + energy_cost 消耗。"""
    eng = _engine()
    eng._resource_registry = {"rage": {"name": "怒气", "type": "rage", "base": 0, "max": 100}}
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _player_act(eng, {"type": "skill", "skill_id": "rage_burst"})
    rs = eng.battle_state()["resource_state"]
    assert rs["player"]["rage"] == 0, f"狂暴应耗怒 100→0，got {rs}"


# ---------------------------------------------------------------------------
# 季节链路
# ---------------------------------------------------------------------------
def test_season_change_event_state() -> None:
    """换季事件状态段就绪（进战登记当前季节索引）。"""
    eng = BattleEngine(defs={})
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    snap = eng.battle_state()
    assert "battle_season" in snap, "战斗应含换季状态段"
    assert "season_event_state" in snap, "战斗应含事件幂等段"


def test_battle_cast_insufficient_mp_rejected() -> None:
    """MP 不足 → 技能被拒不消耗行动（enforce_mp 开）。"""
    eng = _engine(config={"combo_enforce_mp": True})
    eng._snap["player"]["mp"] = 3  # power_strike 需 8
    mp_before = eng.battle_state()["player"]["mp"]
    out = eng.do_action("player", {"type": "skill", "skill_id": "power_strike"})
    assert out.ok is False, f"MP 不足应被拒，got {out}"
    assert eng.battle_state()["player"]["mp"] == mp_before, "被拒不应扣 MP"


def test_transform_cooldown_blocks_retrigger() -> None:
    """形态变更期 → 再次触发不产生**额外**形态提交（C1 互斥/C3 冷却）。

    CTB 迁移（2026-09-10）：旧口径按「回合」推演冷却；CTB 二次触发的门禁由
    transform 引擎在同一玩家行动拍上判定 —— 断言不再依赖行动数，而改为
    「形态保持唯一、且提交次数不因二次触发而累加」的 CTB 行为断言。
    """
    eng = _engine()
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _player_act(eng, {"type": "skill", "skill_id": "rage_burst"})
    committed_after_first = [
        e for e in eng._transform_events if e.get("type") == "transform_committed"
    ]
    assert len(committed_after_first) == 1, "首次触发应恰提交一次形态"
    # 形态激活期再次触发（怒气重新注入）：C1 互斥 → 不得新增提交
    eng._snap["resource_state"] = {"player": {"rage": 100}, "enemy": {}}
    _player_act(eng, {"type": "skill", "skill_id": "rage_burst"})
    committed_after_second = [
        e for e in eng._transform_events if e.get("type") == "transform_committed"
    ]
    ts = eng.battle_state()["transform_state"]
    assert ts["form"] in (None, "berserker_form"), f"形态仍应合法，got {ts}"
    assert len(committed_after_second) == len(committed_after_first), \
        f"形态激活期不应二次提交变换，got {committed_after_second}"
    # CTB 进度：两次玩家行动应使 action_seq 严格前进
    assert int(eng.battle_state()["action_seq"]) > 0


def test_skill_def_resolve_from_registry() -> None:
    """build_pack 后 registry 可解析技能 def（装配消费同源）。"""
    pack, _ = build_pack(DEMO)
    sd = pack.registry.resolve("rage_burst", "skill")
    assert sd is not None
    assert sd.get("name") == "狂暴"


def test_job_def_resolve_from_registry() -> None:
    """build_pack 后 registry 可解析职业 def（转职消费同源）。"""
    pack, _ = build_pack(DEMO)
    jd = pack.registry.resolve("berserker", "job")
    assert jd is not None
    assert jd.get("name") == "狂战士"
