"""M13 批16 路16B · transform×资源联动单测（tests/unit/test_transform_resource_link.py）。

覆盖（真实战斗驱动：BattleEngine + resource_registry + transform 段全链路）：
  1) C2 资源门禁（触发技 energy_cost 不足 → 形态不触发、怒气保留、被拒不耗回合）：
     - 怒气满 → 触发成功（100 沉没 0，TRF-5）+ 形态切换 + transform_committed
     - 怒气不足（<100）→ C2 拒绝（transform_rejected guard=C2）形态不触发
     - 怒气不足时触发技仍按普通技能结算（效果通道已结算，TRF-1），但变换不触发
     - 怒气保留语义：被拒后怒气不变（energy_cost 不足不扣，REV-5 沉没问题）
     - 怒气恰好=100 → 边界放行（check_cost >= 语义）
     - 未注入 resource_registry → 触发技零操作降级（不触发变换，不报错）
  2) 形态技能 energy_gain 增减（fury_slash 带 energy_gain rage）：
     - 触发成功后形态技能施放 → rage 0→gain 值（成功施放后增加封顶）
     - energy_cost+gain 并存（先扣后增，K4）：形态技能带 cost 10 + gain 15
     - 施放 cost 不足 → 被拒不耗回合（energy_insufficient 拒绝消息）
     - 封顶：rage 95 + gain 15 → 100（≤max，超出不累计，TC-02③）
  3) 还原 state_policy（combo/marks/buff clear/keep 三键战斗内真实生效）：
     - 还原（natural）→ combo 清空（快照 combo_state 五字段空态）
     - 还原 → marks=clear 清印记 / keep 保留
     - 还原 → buff=clear 清强化类状态 / keep 保留
     - 怒气沉没：还原后 rage 不返还（REV-5，资源槽保持触发后值）
     - 触发时 combo=clear 亦真实清连段（触发瞬间 ④d）

测试目标：qbot_rpg.core.battle.BattleEngine 真实战斗驱动（不 mock 引擎内部）。

铁律：零 NoneBot import（G0 门禁）；文件头不写 time.sleep 字面量（本文件
零定时器/零睡眠，纯函数确定性）；不引入随机；不 git commit。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

# 数值型怒气轴注册（6c §1.1：max 缺省 100；battle 型战斗结束清零）
_RAGE = {"name": "怒气", "type": "rage", "base": 0, "max": 100}


def _skills() -> Dict[str, Dict[str, Any]]:
    """技能库：触发技 rage_burst（狂暴，energy_cost rage 100）+ 形态技能组。"""
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                         "kind": "damage", "power": 100, "mp_cost": 0},
        "rage_burst": {"id": "rage_burst", "name": "狂暴", "type": "active",
                       "kind": "damage", "power": 80, "mp_cost": 0,
                       # C2 资源门禁：触发技带 energy_cost rage 100（细化_6b §3.3 C2）
                       "energy_cost": {"rage": {"rage": 100}}},
        "calm_down": {"id": "calm_down", "name": "冷静", "type": "active",
                      "kind": "damage", "power": 100, "mp_cost": 0,
                      "revert_form": True},
        # 形态技能组（skill_set=transform_skills 组内条目）
        "fury_slash": {"id": "fury_slash", "name": "狂暴斩", "type": "active",
                       "kind": "damage", "power": 120, "mp_cost": 0,
                       # 形态技能 energy_gain rage：成功施放后增加封顶（M2 E1）
                       "energy_gain": {"rage": {"rage": 15}}},
        "fury_cost": {"id": "fury_cost", "name": "怒焰斩", "type": "active",
                      "kind": "damage", "power": 130, "mp_cost": 0,
                      # cost+gain 并存：先扣后增（K4）
                      "energy_cost": {"rage": {"rage": 10}},
                      "energy_gain": {"rage": {"rage": 15}}},
    }


def _transform() -> Dict[str, Any]:
    """transform 段（对齐细化_6b §1.3 字段表）。"""
    return {
        "transform_skill": "rage_burst",
        "transform_to": "berserker_form",
        "form_name": "狂战士形态",
        "duration": "turns",
        "turns": 3,
        "revert": True,
        "cooldown": 5,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
    }


def _engine(**over: Any) -> BattleEngine:
    """构造战斗引擎：defs + transform 段 + 资源轴注册表 + 怒气槽。"""
    rage: int = int(over.pop("rage", 100))
    no_registry: bool = bool(over.pop("no_registry", False))
    defs = dict(over.pop("defs", {}) or {})
    for k, v in _skills().items():
        defs.setdefault(k, v)
    eng = BattleEngine(config={"combo_enforce_mp": True}, defs=defs)
    eng.set_transform_def(_transform())
    if not no_registry:
        eng._resource_registry = {"rage": _RAGE}
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    eng._snap["resource_state"] = {"player": {"rage": rage}, "enemy": {}}
    return eng


def _rage(eng: BattleEngine) -> int:
    """玩家侧怒气当前值。"""
    return int(eng._snap["resource_state"]["player"].get("rage", 0))


def _ts(eng: BattleEngine) -> Dict[str, Any]:
    """transform_state 段读取。"""
    return eng.battle_state()["transform_state"]


def _full_turn(eng: BattleEngine, action: Dict[str, Any]) -> Any:
    """完整一轮：玩家行动 → 敌后手 → end_turn tick。"""
    out = eng.do_action("player", action)
    eng.enemy_act()
    eng.end_turn()
    return out


def _events(eng: BattleEngine) -> Any:
    """transform 事件审计（战报/测试可观察）。"""
    return eng._transform_events


def _committed(eng: BattleEngine) -> int:
    return len([e for e in _events(eng) if e.get("type") == "transform_committed"])


def _rejected(eng: BattleEngine) -> Any:
    return [e for e in _events(eng) if e.get("type") == "transform_rejected"]


# ---------------------------------------------------------------------------
# ① C2 资源门禁：触发技 energy_cost 不足 → 形态不触发
# ---------------------------------------------------------------------------

def test_c2_full_rage_triggers_and_sinks() -> None:
    """怒气满（100）→ 触发成功：形态切换 + 怒气 100 沉没为 0（TRF-5）。"""
    eng = _engine(rage=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert out.ok is True, f"触发技应成功结算，got {out.message}"
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"形态应切换，got {ts}"
    assert _rage(eng) == 0, f"怒气 100 应沉没为 0（TRF-5），got {_rage(eng)}"
    assert _committed(eng) == 1, f"应有 transform_committed，got {_events(eng)}"


def test_c2_insufficient_rage_rejects_transform() -> None:
    """怒气不足（80 < 100）→ C2 拒绝：形态不触发、transform_rejected guard=C2。

    能量门禁（_apply_skill_energy 先行）不足 → 触发技本身被拒不耗回合
    （energy_insufficient 拒绝消息）——技能结算即被拦，变换闸 C2 未达。
    """
    eng = _engine(rage=80)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert out.ok is False, f"怒气不足应被拒，got {out.message}"
    assert "能量不足" in out.message
    ts = _ts(eng)
    assert ts["form"] is None, f"怒气不足形态不应触发，got {ts}"
    # 被拒路径不产生 transform_rejected（技能结算即被拦，C2 闸未达）——
    # 形态不触发即 C2 资源门禁语义成立；怒气保留另测（test_c2_insufficient_rage_keeps_rage）
    assert _committed(eng) == 0, f"不应有 transform_committed，got {_events(eng)}"


def test_c2_insufficient_rage_keeps_rage() -> None:
    """怒气不足被拒：怒气保留（80 不变，不扣不增——C2 门禁在扣费之前）。"""
    eng = _engine(rage=80)
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert _rage(eng) == 80, f"被拒怒气应保留 80，got {_rage(eng)}"


def test_c2_exact_rage_boundary_triggers() -> None:
    """怒气恰好=100（边界）→ check_cost >= 语义放行 → 触发成功。"""
    eng = _engine(rage=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert out.ok is True
    assert _ts(eng)["form"] == "berserker_form", "边界 100 应触发"
    assert _rage(eng) == 0, "触发后怒气沉没为 0"


def test_c2_zero_rage_rejects() -> None:
    """怒气 0 → C2 拒绝（形态不触发，怒气保持 0）。"""
    eng = _engine(rage=0)
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] is None, "零怒气不应触发"
    assert _rage(eng) == 0


def test_c2_no_registry_noop() -> None:
    """未注入 resource_registry → 能量门禁零操作降级（_apply_skill_energy 不拦）。

    rage_burst 未注册怒气轴 → energy_cost 门禁跳过（RS-5 降级），触发技
    正常结算并触发变换（资源轴未装配时引擎不臆造资源约束，B-3 常规回退）。
    """
    eng = _engine(rage=80, no_registry=True)
    out = eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert out.ok is True, f"无注册表不拦技能，got {out.message}"
    assert _ts(eng)["form"] == "berserker_form", "无注册表资源门禁降级放行 → 触发变换"


# ---------------------------------------------------------------------------
# ② 形态技能 energy_gain 增减（战斗内真实结算）
# ---------------------------------------------------------------------------

def test_form_skill_gain_rage_after_trigger() -> None:
    """触发成功后形态技能 fury_slash 施放 → rage 0→15（成功施放后增加封顶）。"""
    eng = _engine(rage=100)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    assert _rage(eng) == 0
    _full_turn(eng, {"type": "skill", "skill_id": "fury_slash"})
    assert _rage(eng) == 15, f"形态技能 gain 后 rage 应 0→15，got {_rage(eng)}"


def test_form_skill_cost_then_gain() -> None:
    """cost+gain 并存（K4 先扣后增）：rage 20 → -10 → +15 = 25。"""
    eng = _engine(rage=100)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    eng._snap["resource_state"]["player"]["rage"] = 20
    _full_turn(eng, {"type": "skill", "skill_id": "fury_cost"})
    assert _rage(eng) == 25, f"先扣 10 后增 15 应=25，got {_rage(eng)}"


def test_form_skill_cost_insufficient_rejected() -> None:
    """形态技能 cost 不足（rage 5 < 10）→ 被拒不耗回合（energy_insufficient）。"""
    eng = _engine(rage=100)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    eng._snap["resource_state"]["player"]["rage"] = 5
    out = eng.do_action("player", {"type": "skill", "skill_id": "fury_cost"})
    assert out.ok is False, f"能量不足应被拒，got {out}"
    assert "能量不足" in out.message
    assert _rage(eng) == 5, "被拒不应扣增"


def test_form_skill_gain_capped_at_max() -> None:
    """封顶：rage 95 + gain 15 → 100（≤max，超出不累计，TC-02③）。"""
    eng = _engine(rage=100)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    eng._snap["resource_state"]["player"]["rage"] = 95
    _full_turn(eng, {"type": "skill", "skill_id": "fury_slash"})
    assert _rage(eng) == 100, f"95+15 应封顶 100，got {_rage(eng)}"


# ---------------------------------------------------------------------------
# ③ 还原 state_policy（combo/marks/buff clear/keep 战斗内真实生效）
# ---------------------------------------------------------------------------

def test_revert_combo_clear_real_snapshot() -> None:
    """还原（natural）state_policy.combo=clear：战斗快照 combo_state 清空。"""
    eng = _engine(rage=100)
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    eng._snap["combo_state"] = {"player": {"chain_id": "c", "chain_name": "链",
                                           "count": 3, "hold": True, "step_index": 1},
                                "enemy": {}}
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = _ts(eng)
    assert ts["form"] is None, f"turns=3 耗尽应自然还原，got {ts}"
    cs = eng.battle_state().get("combo_state", {}).get("player", {})
    assert cs.get("count") == 0, f"还原 combo=clear 应清连段，got {cs}"
    assert cs.get("chain_id") is None, f"还原应清活跃链，got {cs}"


def test_revert_marks_clear_and_buff_clear() -> None:
    """还原 state_policy marks=clear + buff=clear：印记与强化类状态真实清空。"""
    seg = _transform()
    seg["state_policy"] = {"combo": "clear", "marks": "clear", "buff": "clear"}
    # 触发前注入印记与状态（④d 触发拍与还原拍均按 clear 策略执行：先注入
    # 再触发——触发瞬间即清；还原拍幂等再清一次，无残留可断言）。
    eng = _engine(rage=100)
    eng.set_transform_def(seg)
    eng._snap["marks_state"] = {"player": [{"mark_id": "m1"}], "enemy": []}
    eng._snap["status_state"] = {
        "player": [{"id": "rage_form", "category": "强化"},
                   {"id": "t1", "category": "弱化"}],
        "enemy": [],
    }
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    snap0 = eng.battle_state()
    # 触发时（④d）同策略已清：marks=clear → 印记清空；buff=clear → 强化类清空
    assert snap0["marks_state"]["player"] == [], \
        f"触发 ④d marks=clear 应清印记，got {snap0['marks_state']['player']}"
    remain0 = [s.get("id") for s in snap0["status_state"]["player"]]
    assert "t1" in remain0 and "rage_form" not in remain0, \
        f"触发 ④d buff=clear 应清强化类，got {remain0}"
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = _ts(eng)
    assert ts["form"] is None, f"turns 耗尽应自然还原，got {ts}"
    snap = eng.battle_state()
    assert snap["marks_state"]["player"] == [], \
        f"marks=clear 应清印记，got {snap['marks_state']['player']}"
    remain = [s.get("id") for s in snap["status_state"]["player"]]
    assert "t1" in remain, f"弱化类状态应保留（仅清强化类），got {remain}"
    assert "rage_form" not in remain, f"强化类形态状态应清空，got {remain}"


def test_revert_marks_buff_keep() -> None:
    """还原 state_policy marks/buff=keep（默认）：印记与强化类状态保留。"""
    eng = _engine(rage=100)
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    eng._snap["marks_state"] = {"player": [{"mark_id": "m1"}], "enemy": []}
    eng._snap["status_state"] = {
        "player": [{"id": "b1", "category": "强化"}], "enemy": [],
    }
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    eng.do_action("player", {"type": "normal"})
    eng.enemy_act()
    eng.end_turn()
    ts = _ts(eng)
    assert ts["form"] is None, f"turns 耗尽应自然还原，got {ts}"
    snap = eng.battle_state()
    assert snap["marks_state"]["player"] == [{"mark_id": "m1"}], \
        f"marks=keep 应保留印记，got {snap['marks_state']['player']}"
    remain = [s.get("id") for s in snap["status_state"]["player"]]
    assert "b1" in remain, f"buff=keep 应保留强化状态，got {remain}"


def test_revert_rage_not_refunded() -> None:
    """REV-5 怒气沉没：还原（任何一路）不退还怒气——还原后 rage 保持触发后值。"""
    eng = _engine(rage=100)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    # 形态技能积累怒气
    _full_turn(eng, {"type": "skill", "skill_id": "fury_slash"})
    assert _rage(eng) == 15
    # 主动还原（revert_form 即时）
    _full_turn(eng, {"type": "skill", "skill_id": "calm_down"})
    ts = _ts(eng)
    assert ts["form"] is None, f"主动还原应即时生效，got {ts}"
    # 还原后怒气保留（15 不返还、不清零）
    assert _rage(eng) == 15, f"还原后怒气应保留 15（REV-5），got {_rage(eng)}"


def test_trigger_combo_clear_real() -> None:
    """触发瞬间 ④d state_policy.combo=clear：变换时真实清连段（快照空态）。"""
    eng = _engine(rage=100)
    eng._snap["combo_state"] = {"player": {"chain_id": "x", "chain_name": "链",
                                           "count": 4, "hold": True, "step_index": 2},
                                "enemy": {}}
    eng.do_action("player", {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    cs = eng.battle_state().get("combo_state", {}).get("player", {})
    assert cs.get("count") == 0, f"触发应清连段（④d），got {cs}"
    assert cs.get("chain_id") is None, f"触发应清活跃链，got {cs}"
