"""M13 批15 路15A transform 战斗闭环单测（tests/unit/test_transform_battle_full.py）。

覆盖（真实战斗驱动：CTB `player_act` 全流程）：
  - F1 触发技 transform_skill：/攻击 rage_burst → trigger_transform（形态切换
    + 技能位重排 + state_policy 清连段 + 触发事件登记）
  - C1~C4 触发闸：形态激活期互斥 / 冷却中拒绝 / 被控 skip_turn 拒绝
  - F2 三路还原：turns 耗尽自然还原（持有者行动收尾 tick）/ revert_form 主动即时
    还原 / dispel 被驱散延迟还原（持有者下一次行动收尾）
  - S5 冷却：触发即起算、随持有者行动 tick 递减、归零回常态可再次触发
  - 无 transform 配置 → 触发技零操作降级；非触发技不触发变换
  - transform_state 快照续战携带

测试目标：qbot_rpg.core.battle.BattleEngine（真实战斗驱动，不 mock 引擎内部）。

**CTB 迁移口径（2026-09-10 Wave C · C-1）**：
  - 旧 `_full_turn = do_action + enemy_act + end_turn` 三件套已随 Wave A M4/M5 删除，
    禁止恢复；改为 `player_act(action)`——提交一次玩家行动并由 CTB 调度器自动把
    NPC 连锁走完，直到下一个玩家 ready 或终局。
  - transform 形态/冷却按「**持有者（玩家）行动次数**」计时（Wave A M10）：
    每次玩家行动收尾 tick 一次。旧测试的「回合」断言改为「玩家行动次数」断言，
    数值序列不变（本测试双方每拍各行动一次，故行动数 ≈ 旧回合数）。
  - `_steps(eng, n, action)`：连打 n 次同一玩家行动（n 个 CTB 行动拍），返回末次结果；
    `_seq(eng)`：读 `battle_state()["action_seq"]`（CTB 权威进度计数），用于断言
    「行动条确实前进」——形/冷却的 N 次行动语义靠它佐证，不依赖兼容镜像 `turn`。

铁律：零 NoneBot import；零定时器/零睡眠（无任何 sleep 字面量）；纯函数确定性。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.battle import BattleEngine


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

def _skills() -> Dict[str, Dict[str, Any]]:
    """技能库：触发技 rage_burst（狂暴）+ 普攻 + 主动还原技 + 形态技能组。"""
    return {
        "basic_attack": {"id": "basic_attack", "name": "普攻", "type": "basic",
                         "kind": "damage", "power": 100, "mp_cost": 0},
        "rage_burst": {"id": "rage_burst", "name": "狂暴", "type": "active",
                       "kind": "damage", "power": 80, "mp_cost": 0},
        "power_strike": {"id": "power_strike", "name": "强力斩击", "type": "active",
                         "kind": "damage", "power": 150, "mp_cost": 8},
        "calm_down": {"id": "calm_down", "name": "冷静", "type": "active",
                      "kind": "damage", "power": 100, "mp_cost": 0,
                      "revert_form": True},
        # 形态技能组（skill_set=transform_skills 组内条目）
        "claw_slash": {"id": "claw_slash", "name": "利爪横扫", "type": "active",
                       "kind": "damage", "power": 120, "mp_cost": 0},
    }


def _transform() -> Dict[str, Any]:
    """transform 段（对齐细化_6b §1.3 字段表：transform_skill/transform_to/
    duration/turns/cooldown/state_policy/skill_set/revert）。"""
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
    """构造战斗引擎：技能库 defs + set_transform_def 注入 transform 段。"""
    eng = BattleEngine(defs=_skills())
    eng.set_transform_def(_transform())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
        **over,
    )
    return eng


def _ts(eng: BattleEngine) -> Dict[str, Any]:
    """transform_state 段读取。"""
    return eng.battle_state()["transform_state"]


def _seq(eng: BattleEngine) -> int:
    """已结算行动计数（CTB 权威进度计量；禁用兼容镜像 turn 做进度断言）。"""
    return int(eng.battle_state()["action_seq"])


def _full_turn(eng: BattleEngine, action: Dict[str, Any]) -> Any:
    """提交一次玩家行动（CTB：`player_act` 内含调度器自动推进）。

    旧 `do_action + enemy_act + end_turn` 三件套已删除，禁止恢复——CTB 的等价语义
    就是「提交一次行动 → 结算 → 行动条推进到下一个 ready actor」。
    """
    return eng.player_act(action)


def _steps(eng: BattleEngine, n: int, action: Dict[str, Any]) -> Any:
    """连打 n 次同一玩家行动（每次 = 一个 CTB 行动拍），返回末次结果。"""
    out = None
    for _ in range(n):
        out = eng.player_act(action)
    return out


# ---------------------------------------------------------------------------
# F1：transform_skill 触发
# ---------------------------------------------------------------------------

def test_trigger_transform_via_rage_burst() -> None:
    """真实战斗驱动：/攻击 rage_burst → 形态切换 + 触发事件登记。

    CTB：`player_act` 提交一次行动并推进到下一个 ready，行动收尾会 tick 一次形态
    （remaining 3→2、冷却起算 5 不变）。故断言 remaining=2（含变身当次行动，D-03）。
    """
    eng = _engine()
    out = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    assert out.outcomes[0].ok is True, f"触发技应成功结算，got {out}"
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"形态应切换，got {ts}"
    assert ts["remaining"] == 2, \
        f"触发当次行动 tick 后 remaining 应 3→2，got {ts['remaining']}"
    assert ts["cooldown_remaining"] == 5, \
        f"冷却应= cooldown(5) 从触发起算，got {ts['cooldown_remaining']}"
    assert ts["active_skill_set"] == "transform_skills"
    # 触发事件审计（战报消费）
    evs = eng._transform_events  # type: ignore[attr-defined]
    kinds = [e.get("type") for e in evs]
    assert "transform_committed" in kinds, f"应有 transform_committed 事件，got {kinds}"


def test_trigger_does_not_consume_extra_turn() -> None:
    """TRF-2：变换不额外耗行动——触发技消耗本次行动权，剩余次数不变。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    # 触发当拍行动收尾 tick：remaining 3→2（含变身当次行动，D-03）
    assert _ts(eng)["remaining"] == 2, f"触发当次行动 tick 后 remaining 应 3→2，got {_ts(eng)}"


def test_non_transform_skill_does_not_trigger() -> None:
    """非触发技（普攻/其他技能）不触发变换。"""
    eng = _engine()
    _full_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["form"] is None, f"普攻不应触发变换，got {ts}"


def test_no_transform_config_noop() -> None:
    """无 transform 配置（set_transform_def 未注入）→ 触发技零操作降级。"""
    eng = BattleEngine(defs=_skills())
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 50, "def": 30, "spr": 20, "spd": 10, "name": "玩家"},
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": "疾风狼"},
        random_seed=42,
    )
    out = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    assert out.outcomes[0].ok is True
    assert _ts(eng)["form"] is None, "无配置不应触发变换"


def test_transform_skill_mismatch_noop() -> None:
    """技能 ID 与 transform_skill 不匹配 → 不触发变换（普通技能结算）。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "power_strike"})
    assert _ts(eng)["form"] is None, "非触发技不应触发变换"


# ---------------------------------------------------------------------------
# C1~C4 触发闸（战斗驱动）
# ---------------------------------------------------------------------------

def test_c1_form_active_rejects_retrigger() -> None:
    """C1：形态激活期再次施放触发技 → 拒绝（不改形态、不耗额外行动）。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    # 形态激活期再次触发 → 形态不变、无新 transform_committed
    # （battle.py 入口闸：form 非空 → 不进入 trigger_transform，C1 拦截）
    out = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    assert out.outcomes[0].ok is True, "触发技本身仍按普通技能结算"
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"C1 拒绝不应改形态，got {ts}"
    evs = eng._transform_events  # type: ignore[attr-defined]
    committed = [e for e in evs if e.get("type") == "transform_committed"]
    assert len(committed) == 1, f"二次触发不应提交新变换，got {evs}"


def test_c3_cooldown_rejects_retrigger() -> None:
    """C3：还原后冷却期施放触发技 → 拒绝（冷却剩余>0）。"""
    eng = _engine()
    # 触发 → 走满 3 次玩家行动自然还原 → 冷却 5 起算
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    _full_turn(eng, {"type": "normal"})
    _full_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["form"] is None, "3 次玩家行动后应自然还原"
    # 还原当次行动收尾 tick 冷却 5→4（D-03：还原后同拍冷却递减）
    assert ts["cooldown_remaining"] == 4, f"还原后冷却应 5→4，got {ts['cooldown_remaining']}"
    # 冷却中再次触发 → C3 拒绝
    eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    evs = eng._transform_events  # type: ignore[attr-defined]
    rej = [e for e in evs if e.get("type") == "transform_rejected"]
    assert rej and rej[-1].get("guard") == "C3", f"冷却中应 C3 拒绝，got {evs}"


def test_c4_skip_turn_rejects_trigger() -> None:
    """C4：被控 skip_turn → 触发技不触发变换（拒绝登记），且时间轴照常前进。

    CTB 不变量（`_skip_turn` docstring）：被控者本次 ready 被消费但不产出行动——
    **时间必须继续走**（否则硬直死锁），故 `action_seq` 仍须严格增加。
    """
    eng = _engine()
    # 直接写控制状态（真实战斗控制通道的等价状态）
    eng.battle_state()  # noqa: B018 —— battle_state() 深拷贝不串改，写内部 _snap
    eng._snap["player"]["control_state"] = {
        "type": "睡眠", "skip_turn": 1.0, "turns": 1, "source": "enemy",
    }  # type: ignore[attr-defined]
    seq0 = _seq(eng)
    out = eng.player_act({"type": "skill", "skill_id": "rage_burst"})
    # 被控 → 行动被跳过（TurnReport.outcomes[0]），不会走到技能结算
    oc = out.outcomes[0]
    assert oc.action_type == "skip", f"被控应跳过行动，got {oc.action_type}"
    assert _ts(eng)["form"] is None, "被控不应触发变换"
    assert _seq(eng) > seq0, "被控跳过后行动条仍须推进（CTB 时间继续走，防硬直死锁）"


# ---------------------------------------------------------------------------
# F2：自然还原（持有者行动收尾 tick）
# ---------------------------------------------------------------------------

def test_natural_revert_when_turns_exhausted() -> None:
    """turns=3：触发当次行动 + 2 次后续行动 → 第 3 次玩家行动收尾自然还原。

    CTB 语义：「N 回合形态」= 持有者（player）**行动 N 次**；`action_seq` 严格
    增加佐证时间轴确实在推进（不是靠兼容镜像 turn）。
    """
    eng = _engine()
    seq0 = _seq(eng)
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form" and _ts(eng)["remaining"] == 2
    assert _seq(eng) > seq0, "触发行动后行动条应前进"
    _full_turn(eng, {"type": "normal"})
    assert _ts(eng)["form"] == "berserker_form" and _ts(eng)["remaining"] == 1
    _full_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["form"] is None, f"turns 耗尽应自然还原，got {ts}"
    assert ts["remaining"] == 0
    # 还原后冷却起算=5，且还原当次行动收尾 tick 已递减一次 → 4（D-03）
    assert ts["cooldown_remaining"] == 4, \
        f"自然还原后冷却应 5→4（还原当次行动递减），got {ts['cooldown_remaining']}"


def test_natural_revert_writes_event() -> None:
    """自然还原 → transform_reverted 事件（reason=natural）。

    CTB：触发当次 + 2 次后续玩家行动 = 持有者行动 3 次 → 还原（`_steps` 连打）。
    """
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    _steps(eng, 2, {"type": "normal"})
    evs = eng._transform_events  # type: ignore[attr-defined]
    reverted = [e for e in evs if e.get("type") == "transform_reverted"]
    assert reverted and reverted[-1].get("reason") == "natural", \
        f"应有 natural 还原事件，got {evs}"


# ---------------------------------------------------------------------------
# F2：revert_form 主动还原
# ---------------------------------------------------------------------------

def test_revert_form_skill_active_revert() -> None:
    """revert_form 技能：形态激活期施放 → 即时还原 + 冷却起算。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    _full_turn(eng, {"type": "skill", "skill_id": "calm_down"})
    ts = _ts(eng)
    assert ts["form"] is None, f"revert_form 应即时还原，got {ts}"
    # 主动还原当次行动收尾 tick 冷却 5→4（D-03：还原后同拍冷却递减）
    assert ts["cooldown_remaining"] == 4, \
        f"主动还原后冷却应 5→4（还原当次行动递减），got {ts['cooldown_remaining']}"


def test_revert_form_no_form_noop() -> None:
    """revert_form 技能：常态施放 → 零操作（不报错、不产生还原事件）。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "calm_down"})
    assert _ts(eng)["form"] is None
    evs = eng._transform_events  # type: ignore[attr-defined]
    assert not any(e.get("type") == "transform_reverted" for e in evs), \
        f"常态还原应零操作，got {evs}"


# ---------------------------------------------------------------------------
# F2：dispel 被驱散还原（D-05 延迟到持有者下一次行动收尾）
# ---------------------------------------------------------------------------

def test_dispel_reverts_at_next_turn_end() -> None:
    """dispel：形态状态被驱散 → 还原延迟到持有者下一次行动收尾。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    assert _ts(eng)["form"] == "berserker_form"
    # 登记 dispel 待还原（D-05：驱散命中 → transform_pending_dispel 标记，
    # 战斗层 _transform_dispel_pending 瞬态缓存承接，下一次行动收尾结算）
    eng._transform_dispel_pending["player"] = True  # type: ignore[attr-defined]
    # 同次行动窗口内形态仍在（延迟还原，不立即清）
    assert _ts(eng)["form"] == "berserker_form"
    _full_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["form"] is None, \
        f"dispel 应在下一次行动收尾还原，got {ts}"
    # dispel 还原当次行动收尾 tick 冷却 5→4（P-3 dispel 不豁免 + D-03 同拍递减）
    assert ts["cooldown_remaining"] == 4, \
        f"dispel 还原后冷却应 5→4（P-3 不豁免 + 当次行动递减），got {ts['cooldown_remaining']}"
    evs = eng._transform_events  # type: ignore[attr-defined]
    reverted = [e for e in evs if e.get("type") == "transform_reverted"]
    assert reverted and reverted[-1].get("reason") == "dispel", \
        f"应有 dispel 还原事件，got {evs}"


def test_dispel_persistent_marker_reverts() -> None:
    """dispel 持久标记（transform_pending_dispel in persistent_state）→ 还原。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    # 持久标记通道（transform_revert.dispel_triggered 读取位；战斗快照 player
    # 侧 persistent_state 段——start 未建则惰性建段）
    ps = eng._snap["player"].setdefault("persistent_state", {})  # type: ignore[attr-defined]
    ps["transform_pending_dispel"] = True
    _full_turn(eng, {"type": "normal"})
    assert _ts(eng)["form"] is None, "持久标记应触发 dispel 还原"


# ---------------------------------------------------------------------------
# S5：冷却 tick 与再次触发
# ---------------------------------------------------------------------------

def test_cooldown_ticks_down_and_allows_retrigger() -> None:
    """S5：冷却随持有者**行动次数**递减；归零回常态 → 可再次触发变换。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    _full_turn(eng, {"type": "normal"})
    _full_turn(eng, {"type": "normal"})
    # 自然还原 → 冷却 5 起算，还原当次行动 tick 已递减 → 4
    assert _ts(eng)["cooldown_remaining"] == 4
    # 冷却逐次行动递减（常态 tick_cooldown）4→3→2→1→0，每步均须推进 action_seq
    for expected in (3, 2, 1, 0):
        seq0 = _seq(eng)
        _full_turn(eng, {"type": "normal"})
        assert _seq(eng) > seq0, "每次冷却递减都必须伴随行动条前进"
        assert _ts(eng)["cooldown_remaining"] == expected, \
            f"冷却应递减到 {expected}，got {_ts(eng)}"
    # 归零后可再次触发（触发当次行动 tick 后 remaining 3→2，含变身当次 D-03）
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    ts = _ts(eng)
    assert ts["form"] == "berserker_form", f"冷却归零应可再次触发，got {ts}"
    assert ts["remaining"] == 2, f"二次触发当次行动 tick 后 remaining 应 3→2，got {ts}"
    assert ts["cooldown_remaining"] == 5, f"二次触发冷却应从 5 起算，got {ts}"


def test_cooldown_not_decremented_during_form() -> None:
    """S3 形态持续期：冷却不递减（形态期只递减 remaining）。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    ts = _ts(eng)
    assert ts["cooldown_remaining"] == 5, "形态期冷却不递减"
    _full_turn(eng, {"type": "normal"})
    ts = _ts(eng)
    assert ts["cooldown_remaining"] == 5, f"形态期冷却应保持 5，got {ts['cooldown_remaining']}"


# ---------------------------------------------------------------------------
# state_policy 战斗联动
# ---------------------------------------------------------------------------

def test_trigger_clears_combo_state() -> None:
    """state_policy.combo=clear：触发变换清连段（战斗快照 combo_state 空态）。"""
    eng = _engine()
    # 先打一次普攻建立连段计数
    eng.player_act({"type": "normal"})
    cs = eng.battle_state().get("combo_state", {})
    # 连段引擎对普攻可能不累计——直接写快照连段（真实快照段）
    eng._snap["combo_state"] = {"player": {"chain_id": "x", "chain_name": "链",
                                           "count": 3, "hold": True, "step_index": 1}}  # type: ignore[attr-defined]
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    cs = eng.battle_state().get("combo_state", {}).get("player", {})
    assert cs.get("count") == 0, f"触发变换应清连段，got {cs}"
    assert cs.get("chain_id") is None, f"触发变换应清链，got {cs}"


def test_snapshot_carries_transform_state() -> None:
    """快照续战：to_snapshot/from_snapshot 携带 transform_state（含形态/冷却）。"""
    eng = _engine()
    _full_turn(eng, {"type": "skill", "skill_id": "rage_burst"})
    snap = eng.to_snapshot()
    assert snap.get("transform_state", {}).get("form") == "berserker_form", \
        "快照应含形态"
    eng2 = BattleEngine(defs=_skills()).set_transform_def(_transform()).from_snapshot(snap)  # type: ignore[call-arg]
    ts2 = _ts(eng2)
    assert ts2["form"] == "berserker_form"
    assert ts2["remaining"] == 2, f"快照恢复应带 remaining，got {ts2}"
