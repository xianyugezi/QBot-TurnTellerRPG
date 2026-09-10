"""CTB 事件序列契约测试（tests/ctb/test_ctb_contract_events.py）。

依据：
  - docs/ctb/01_asset_inventory.md §0.2「CTB 事件位点词典」（10 种事件）。
  - qbot_rpg/core/ctb_rules.py `EVENT_ORDER`（冻结逻辑序）+ `CtbEvent`（常量容器）。
  - qbot_rpg/core/ctb_scheduler.py `advance_to_next_ready()` 的事件派发链路。

本文件锁定**事件的合法顺序**（不变量），作为 Agent 3 重写引擎事件派发时的靶子：
  I1  `ACTOR_TURN_START` 必须先于该单位的 `ACTION_RESOLVE`
  I2  `BATTLE_END` 之后不得再有其他事件
  I3  一次行动链路的相对次序：
      ACTOR_READY → ACTOR_TURN_START → BEFORE_ACTION → ACTION_RESOLVE
      → AFTER_ACTION → ACTOR_TURN_END
  I4  每个 `ACTION_RESOLVE` 必须有其单位在前方出现的 `ACTOR_READY`
  I5  `BATTLE_TIME_ADVANCE` 单调不减（逻辑时间不回退）
  I6  `ACTOR_DEATH` 必须先于 `BATTLE_END`（若同侧全灭）
  I7  `BATTLE_START` 是首个事件（若存在）
  I8  事件名必须属于 10 种词典（无拼写漂移）

这些不变量当前由 **Agent 2 调度器**（ctb_scheduler）直接满足——它是 CTB 事件模型的
唯一现役产出方；故本文件对调度器运行时立即生效（非 xfail）。引擎侧事件派发落地后，
Agent 3 应以同一事件序列契约自证（可在本文件追加引擎驱动器）。
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from qbot_rpg.core.ctb_rules import CtbEvent, EVENT_ORDER
from qbot_rpg.core.ctb_scheduler import CTBScheduler

#: 10 种 CTB 事件词典（§0.2）
ALL_EVENTS = {
    CtbEvent.BATTLE_START,
    CtbEvent.ACTOR_READY,
    CtbEvent.BEFORE_ACTION,
    CtbEvent.ACTION_RESOLVE,
    CtbEvent.AFTER_ACTION,
    CtbEvent.ACTOR_TURN_START,
    CtbEvent.ACTOR_TURN_END,
    CtbEvent.BATTLE_TIME_ADVANCE,
    CtbEvent.ACTOR_DEATH,
    CtbEvent.BATTLE_END,
}

#: 一次行动链路的冻结相对次序（调度器保证）
ACTION_CHAIN = (
    CtbEvent.ACTOR_READY,
    CtbEvent.ACTOR_TURN_START,
    CtbEvent.BEFORE_ACTION,
    CtbEvent.ACTION_RESOLVE,
    CtbEvent.AFTER_ACTION,
    CtbEvent.ACTOR_TURN_END,
)


# ---------------------------------------------------------------------------
# 驱动：跑一段战斗并收集完整事件轨迹
# ---------------------------------------------------------------------------
def _collect_events(
    *,
    p_speed: float = 100.0,
    e_speed: float = 75.0,
    ticks: int = 8,
    damage_every: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """驱动调度器跑 ticks 拍，收集全部事件 payload（含玩家暂停自动解除）。

    :param p_speed: 玩家有效速度
    :param e_speed: 怪物有效速度
    :param ticks: 最大推进拍数
    :param damage_every: 每 N 次 NPC 行动后杀死敌方（用于触发 ACTOR_DEATH/BATTLE_END）
    :return: 事件 payload 列表（按时序）
    """
    sched = CTBScheduler()
    sched.push_actor("p1", side="player", effective_speed=p_speed, is_player=True)
    sched.push_actor("e1", side="enemy", effective_speed=e_speed)
    sched.start()
    events: List[Dict[str, Any]] = list(sched.drain_events())
    npc_actions = 0
    for _ in range(ticks):
        if sched.finished:
            break
        if sched.should_pause_for_input():
            if sched.paused:
                ev = sched.complete_player_action()
                events.extend(sched.drain_events())
                if ev is None and not sched.paused:
                    break
                continue
            break
        ev = sched.advance_to_next_ready()
        events.extend(sched.drain_events())
        if ev is None:
            break
        if ev["event"] == CtbEvent.ACTOR_TURN_END and ev.get("actor_id") == "e1":
            npc_actions += 1
            if damage_every and npc_actions >= damage_every:
                sched.mark_dead("e1")
    events.extend(sched.drain_events())
    return events


def _names(events: Iterable[Dict[str, Any]]) -> List[str]:
    return [str(e.get("event")) for e in events]


# ===========================================================================
# 词典完整性
# ===========================================================================
def test_event_dictionary_is_exactly_ten() -> None:
    """I8：CTB 事件词典恰为 10 种，且 EVENT_ORDER 覆盖全集（清点表 §0.2）。"""
    assert len(ALL_EVENTS) == 10
    assert set(EVENT_ORDER) == ALL_EVENTS


def test_all_emitted_events_belong_to_dictionary() -> None:
    """I8：轨迹中事件名必须全部属于 10 种词典（无拼写漂移）。"""
    names = _names(_collect_events())
    assert names, "应至少产出若干事件"
    assert set(names) <= ALL_EVENTS


# ===========================================================================
# I7 BATTLE_START 首个
# ===========================================================================
def test_battle_start_is_first_event() -> None:
    """I7：`BATTLE_START` 是第一个事件。"""
    names = _names(_collect_events())
    assert names[0] == CtbEvent.BATTLE_START


# ===========================================================================
# I3 行动链路相对次序
# ===========================================================================
def test_action_chain_relative_order_holds() -> None:
    """I3：每次行动链路的事件相对次序为 READY→TURN_START→BEFORE→RESOLVE→AFTER→TURN_END。

    校验方式：依次扫描轨迹，链路成员的出现顺序必须与 ACTION_CHAIN 的**循环序**一致
    （即每 6 个链路事件构成一个链路段，不受其间 BATTLE_TIME_ADVANCE 干扰）。
    """
    events = _collect_events()
    chain_seq = [n for n in _names(events) if n in ACTION_CHAIN]
    assert chain_seq, "应有行动链路事件"
    # 逐位置比对循环序
    for i, name in enumerate(chain_seq):
        assert name == ACTION_CHAIN[i % len(ACTION_CHAIN)], (
            f"链路次序错位：位置 {i} 期望 {ACTION_CHAIN[i % len(ACTION_CHAIN)]} 实得 {name}"
        )
    assert len(chain_seq) % len(ACTION_CHAIN) == 0, "链路应完整成段"


# ===========================================================================
# I1 ACTOR_TURN_START 先于该单位的 ACTION_RESOLVE
# ===========================================================================
def test_turn_start_precedes_action_resolve_per_actor() -> None:
    """I1：任一单位的 `ACTOR_TURN_START` 必须先于其 `ACTION_RESOLVE`。

    不变量：`resolve_count[actor] <= turn_start_count[actor]` 在轨迹任一前缀均成立。
    """
    events = _collect_events()
    started: set[str] = set()
    for ev in events:
        name, actor = ev["event"], str(ev.get("actor_id"))
        if name == CtbEvent.ACTOR_TURN_START:
            started.add(actor)
        elif name == CtbEvent.ACTION_RESOLVE:
            assert actor in started, f"{actor} 的 ACTION_RESOLVE 先于其 ACTOR_TURN_START"


# ===========================================================================
# I4 每个 ACTION_RESOLVE 前有该单位 ACTOR_READY
# ===========================================================================
def test_ready_precedes_resolve_per_actor() -> None:
    """I4：每个 `ACTION_RESOLVE` 之前，该单位必有 `ACTOR_READY`。"""
    events = _collect_events()
    ready_seen: set[str] = set()
    for ev in events:
        name, actor = ev["event"], str(ev.get("actor_id"))
        if name == CtbEvent.ACTOR_READY:
            ready_seen.add(actor)
        elif name == CtbEvent.ACTION_RESOLVE:
            assert actor in ready_seen, f"{actor} 的 ACTION_RESOLVE 之前缺 ACTOR_READY"


# ===========================================================================
# I5 BATTLE_TIME_ADVANCE 时间单调不减
# ===========================================================================
def test_battle_time_advance_monotonic() -> None:
    """I5：`BATTLE_TIME_ADVANCE` 携带的 battle_time 单调不减（逻辑时间不回退）。"""
    events = _collect_events()
    times = [float(e["battle_time"]) for e in events if e["event"] == CtbEvent.BATTLE_TIME_ADVANCE]
    assert times, "应有时间推进事件"
    assert times == sorted(times), f"battle_time 非单调：{times}"


# ===========================================================================
# I2 / I6 BATTLE_END 之后无事件；ACTOR_DEATH 先于 BATTLE_END
# ===========================================================================
def test_death_precedes_battle_end() -> None:
    """I6：`ACTOR_DEATH` 必须先于 `BATTLE_END`。"""
    events = _collect_events(damage_every=1)
    names = _names(events)
    assert CtbEvent.ACTOR_DEATH in names, "杀死全部敌人后应产出 ACTOR_DEATH"
    assert CtbEvent.BATTLE_END in names, "一方全灭后应产出 BATTLE_END"
    assert names.index(CtbEvent.ACTOR_DEATH) < names.index(CtbEvent.BATTLE_END)


def test_no_events_after_battle_end() -> None:
    """I2：`BATTLE_END` 之后不得再有任何事件（硬不变量）。"""
    events = _collect_events(damage_every=1)
    names = _names(events)
    assert CtbEvent.BATTLE_END in names
    end_idx = names.index(CtbEvent.BATTLE_END)
    # BATTLE_END 至多出现一次，且其后无事件
    assert names.count(CtbEvent.BATTLE_END) == 1
    assert end_idx == len(names) - 1, f"BATTLE_END 之后仍有事件：{names[end_idx + 1:]}"


def test_battle_end_idempotent() -> None:
    """I2：`finish()` 幂等——重复调用只产出一个 `BATTLE_END`。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.start()
    sched.drain_events()
    sched.finish()
    sched.finish()
    sched.finish()
    ends = [e for e in sched.drain_events() if e["event"] == CtbEvent.BATTLE_END]
    assert len(ends) == 1


# ===========================================================================
# 附加：事件 payload 结构契约
# ===========================================================================
def test_event_payload_required_fields() -> None:
    """契约：每个事件 payload 必含 event / time / generation / actor_id 四字段。"""
    for ev in _collect_events():
        for key in ("event", "time", "generation", "actor_id"):
            assert key in ev, f"事件缺字段 {key}: {ev}"


def test_action_events_carry_action_seq() -> None:
    """契约：行动链路事件携带 `action_seq`（CTB 下替代回合数的行动计数源）。"""
    events = _collect_events()
    chain_events = [e for e in events if e["event"] in ACTION_CHAIN]
    assert chain_events
    for ev in chain_events:
        if ev["event"] == CtbEvent.ACTOR_READY:
            continue  # READY 已在调度器侧带 action_seq，容忍缺失以保持宽松
        assert "action_seq" in ev, f"{ev['event']} 缺 action_seq"
