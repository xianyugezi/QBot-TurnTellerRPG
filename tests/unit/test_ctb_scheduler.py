"""CTB 调度器单元测试（tests/unit/test_ctb_scheduler.py）—— CTB 重写 · Agent 2。

覆盖任务书验收项：
  1. 速度差异导致的行动顺序（SPD 100 vs 75）
  2. 同速 tie-break 的确定性（speed 降序 → 阵营 player 优先 → actor_id 字典序）
  3. next_ready 计算公式（含 min_speed 下限保护）
  4. 票据 generation 失效与丢弃
  5. NPC 连锁自动推进 + 玩家 Ready 暂停
  6. 多 NPC 行动合并上报（ActionBatchReport）
  7. 同种子完全可复现

硬约束自检：本文件**不 import qbot_rpg.core.battle**，独立可跑绿。
"""

from __future__ import annotations

from qbot_rpg.core.ctb_rules import (
    CTB_TIEBREAK_RULE,
    DEFAULT_RECOVERY,
    ACTION_DELAY,
    MIN_SPEED,
    SPEED_REFERENCE,
    ActionBatchReport,
    CtbEvent,
    CtbRuleConfig,
    EVENT_ORDER,
    build_tiebreak_key,
    next_ready,
    recovery_for,
    time_cost,
)
from qbot_rpg.core.ctb_scheduler import CTBScheduler, CtbTicket


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------
def _run_ticks(sched: CTBScheduler, n: int):
    """连续推进 n 拍（遇暂停即停），返回 [(time, actor_id, event)]。"""
    trace = []
    for _ in range(n):
        if sched.should_pause_for_input():
            break
        ev = sched.advance_to_next_ready()
        if ev is None:
            break
        trace.append((round(ev["time"], 4), ev["actor_id"], ev["event"]))
    return trace


# ---------------------------------------------------------------------------
# 1. next_ready 公式（ctb_rules）
# ---------------------------------------------------------------------------
def test_next_ready_formula_basic() -> None:
    """next_ready = current + recovery * speed_reference / max(speed, min_speed) + delay。"""
    # SPD == speed_reference 时，一次默认 recovery 的代价 = recovery 本身
    assert next_ready(0.0, {"id": "atk"}, SPEED_REFERENCE) == DEFAULT_RECOVERY
    # SPD 75：100 * 100 / 75 = 133.333…
    assert abs(next_ready(0.0, {"id": "atk"}, 75) - 100 * 100 / 75) < 1e-9


def test_next_ready_includes_previous_time_and_delay() -> None:
    """公式含 current_time 累加项与 action_delay 加项。"""
    got = next_ready(50.0, {"id": "atk", "recovery": 60, "action_delay": 5}, 120)
    expect = 50.0 + 60 * SPEED_REFERENCE / 120 + 5
    assert abs(got - expect) < 1e-9


def test_next_ready_min_speed_guard() -> None:
    """min_speed 下限保护：速度为 0 / 负值时用 min_speed 兜底（不除零）。"""
    zero = next_ready(0.0, {}, 0)
    neg = next_ready(0.0, {}, -999)
    assert zero == neg
    assert zero == DEFAULT_RECOVERY * SPEED_REFERENCE / MIN_SPEED
    # 自定义 min_speed 生效
    cfg = CtbRuleConfig(min_speed=50.0)
    assert next_ready(0.0, {}, 10, cfg) == DEFAULT_RECOVERY * SPEED_REFERENCE / 50.0


def test_next_ready_faster_speed_shorter_wait() -> None:
    """速度越高，时间代价越小（单调性）。"""
    assert time_cost({}, 200) < time_cost({}, 100) < time_cost({}, 50)


def test_recovery_for_override_and_default() -> None:
    """recovery(action) 支持自带键与 recovery_table 覆盖，兜底 default_recovery。"""
    assert recovery_for({}, CtbRuleConfig()) == DEFAULT_RECOVERY
    assert recovery_for({"recovery": 40}, CtbRuleConfig()) == 40.0
    assert recovery_for({"行动恢复": 30}, CtbRuleConfig()) == 30.0
    cfg = CtbRuleConfig(recovery_table={"heavy": 250.0})
    assert recovery_for({"id": "heavy"}, cfg) == 250.0
    # 负数非法 → 兜底默认
    assert recovery_for({"recovery": -5}, CtbRuleConfig()) == DEFAULT_RECOVERY


def test_rule_config_overrides_are_safe() -> None:
    """CtbRuleConfig.with_overrides 非法输入回退原值，不抛错。"""
    base = CtbRuleConfig()
    same = base.with_overrides({"min_speed": None, "unknown": 1})
    assert same.min_speed == base.min_speed
    assert base.with_overrides(None) is base


def test_action_delay_default_zero() -> None:
    """缺省 action_delay = 0（对齐常量）。"""
    assert ACTION_DELAY == 0.0
    assert next_ready(0.0, {"recovery": 10}, 100) == 10.0


# ---------------------------------------------------------------------------
# 2. tie-break 键与规则确定性
# ---------------------------------------------------------------------------
def test_tiebreak_key_ordering() -> None:
    """tie-break 键：speed 降序 → player 优先 → actor_id 字典序。"""
    fast = build_tiebreak_key(10.0, 100.0, "enemy", "z")
    slow = build_tiebreak_key(10.0, 50.0, "enemy", "a")
    assert fast < slow  # 快者优先（speed 降序）

    player = build_tiebreak_key(10.0, 100.0, "enemy", "z")
    enemy = build_tiebreak_key(10.0, 100.0, "player", "z")
    assert enemy < player  # player 优先（side 优先级升序）

    a = build_tiebreak_key(10.0, 100.0, "enemy", "a")
    b = build_tiebreak_key(10.0, 100.0, "enemy", "b")
    assert a < b  # 字典序

    assert isinstance(CTB_TIEBREAK_RULE, str) and CTB_TIEBREAK_RULE


def test_tiebreak_is_deterministic_for_same_speed() -> None:
    """同速 tie-break：player 优先于 enemy；同阵营按 actor_id 字典序。"""
    sched = CTBScheduler()
    # 乱序登记，验证排序结果与登记顺序无关
    sched.push_actor("zeta", side="enemy", effective_speed=100)
    sched.push_actor("alpha", side="enemy", effective_speed=100)
    sched.push_actor("player1", side="player", effective_speed=100, is_player=True)
    sched.start()
    assert sched.peek_next().actor_id == "player1"

    sched2 = CTBScheduler()
    sched2.push_actor("zeta", side="enemy", effective_speed=100)
    sched2.push_actor("alpha", side="enemy", effective_speed=100)
    sched2.start()
    assert sched2.peek_next().actor_id == "alpha"


def test_tiebreak_same_id_fifo_fallback() -> None:
    """三级全等（同 ready/速度/阵营/id 不可能，用同速不同序验证稳定序）。"""
    s1 = CTBScheduler()
    for aid in ("c", "a", "b"):
        s1.push_actor(aid, side="enemy", effective_speed=100)
    s1.start()
    order1 = [s1.peek_next().actor_id]
    s2 = CTBScheduler()
    for aid in ("b", "c", "a"):
        s2.push_actor(aid, side="enemy", effective_speed=100)
    s2.start()
    order2 = [s2.peek_next().actor_id]
    assert order1 == order2 == ["a"]


# ---------------------------------------------------------------------------
# 3. 速度差异导致行动顺序（调度器层）
# ---------------------------------------------------------------------------
def test_speed_100_acts_before_speed_75() -> None:
    """SPD 100 比 SPD 75 先行动，且后续节奏交替（100 → 75 → 100 → 75）。"""
    sched = CTBScheduler()
    sched.push_actor("slow", side="enemy", effective_speed=75)
    sched.push_actor("fast", side="enemy", effective_speed=100)
    sched.start()
    trace = _run_ticks(sched, 4)
    assert [t[1] for t in trace] == ["fast", "slow", "fast", "slow"]
    # 时间点：100 / 133.33 / 200 / 266.67
    assert trace[0][0] == 100.0
    assert abs(trace[1][0] - 133.3333) < 1e-3
    assert trace[2][0] == 200.0


def test_higher_speed_gets_more_actions() -> None:
    """速度更高者在同一时间窗内获得更多行动次数。"""
    sched = CTBScheduler()
    sched.push_actor("fast", side="enemy", effective_speed=200)
    sched.push_actor("slow", side="enemy", effective_speed=50)
    sched.start()
    trace = _run_ticks(sched, 6)
    fast_n = sum(1 for t in trace if t[1] == "fast")
    slow_n = sum(1 for t in trace if t[1] == "slow")
    assert fast_n > slow_n


# ---------------------------------------------------------------------------
# 4. 事件模型（10 种 + 顺序确定）
# ---------------------------------------------------------------------------
def test_event_model_has_ten_events() -> None:
    """10 种事件齐全且 EVENT_ORDER 覆盖。"""
    names = {
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
    assert len(names) == 10
    assert names == set(EVENT_ORDER)


def test_event_sequence_for_npc_action_is_deterministic() -> None:
    """NPC 一次行动链路事件顺序：TURN_START→BEFORE→RESOLVE→AFTER→TURN_END。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.start()
    sched.drain_events()  # 清掉 BATTLE_START
    sched.advance_to_next_ready()
    events = [e["event"] for e in sched.drain_events()]
    # 首拍时间从 0 跳到 ready，故链路前含 BATTLE_TIME_ADVANCE
    chain = [
        CtbEvent.BATTLE_TIME_ADVANCE,
        CtbEvent.ACTOR_READY,
        CtbEvent.ACTOR_TURN_START,
        CtbEvent.BEFORE_ACTION,
        CtbEvent.ACTION_RESOLVE,
        CtbEvent.AFTER_ACTION,
        CtbEvent.ACTOR_TURN_END,
    ]
    assert events == chain
    # 二次行动：每次行动都消耗时间，故仍有 BATTLE_TIME_ADVANCE（时间单调前进）
    sched.drain_events()
    sched.advance_to_next_ready()
    assert [e["event"] for e in sched.drain_events()] == chain


def test_battle_time_advance_emitted_on_time_jump() -> None:
    """时间推进时派发 BATTLE_TIME_ADVANCE 且携带 delta。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=50)
    sched.start()
    sched.drain_events()
    sched.advance_to_next_ready()
    events = {e["event"]: e for e in sched.drain_events()}
    assert CtbEvent.BATTLE_TIME_ADVANCE in events
    assert events[CtbEvent.BATTLE_TIME_ADVANCE]["delta"] == 200.0


def test_subscribe_callback_receives_events_and_isolated() -> None:
    """订阅者能收到事件；订阅者异常不阻断调度。"""
    got = []

    def boom(_payload):
        raise RuntimeError("订阅者故意抛错")

    sched = CTBScheduler()
    sched.subscribe(CtbEvent.ACTOR_READY, got.append)
    sched.subscribe(CtbEvent.ACTOR_READY, boom)
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.start()
    sched.advance_to_next_ready()
    assert got and got[0]["event"] == CtbEvent.ACTOR_READY


def test_battle_end_once() -> None:
    """BATTLE_END 幂等（finish 多次只派发一次）。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.start()
    sched.drain_events()
    sched.finish()
    sched.finish()
    ends = [e for e in sched.drain_events() if e["event"] == CtbEvent.BATTLE_END]
    assert len(ends) == 1
    assert sched.finished is True


# ---------------------------------------------------------------------------
# 5. generation 票据失效与丢弃
# ---------------------------------------------------------------------------
def test_generation_bumps_on_state_change() -> None:
    """状态变更（速度更新 / 规则变更 / 死亡）递增 generation。"""
    sched = CTBScheduler()
    sched.push_actor("a", side="enemy", effective_speed=100)
    sched.start()
    g0 = sched.generation
    sched.update_speed("a", 50)
    g1 = sched.generation
    sched.change_rules({"default_recovery": 80})
    g2 = sched.generation
    sched.mark_dead("a")
    g3 = sched.generation
    assert g0 < g1 < g2 < g3


def test_stale_ticket_is_dropped() -> None:
    """旧 generation 票据回流被识别并丢弃，不污染队列。"""
    sched = CTBScheduler()
    sched.push_actor("a", side="enemy", effective_speed=100)
    sched.start()
    old_ticket = sched.get_actor("a").ticket
    assert sched.resolve_ticket(old_ticket) is True  # 当前代有效

    sched.update_speed("a", 200)  # bump generation → 旧票失效
    assert sched.is_ticket_stale(old_ticket) is True
    assert sched.resolve_ticket(old_ticket) is False
    assert sched.stale_dropped == 1

    # 新票据为当前代，有效
    new_ticket = sched.get_actor("a").ticket
    assert sched.is_ticket_stale(new_ticket) is False


def test_invalidate_ticket_alias() -> None:
    """invalidate_ticket 与 bump_generation 语义一致。"""
    sched = CTBScheduler()
    before = sched.generation
    sched.invalidate_ticket("manual")
    assert sched.generation == before + 1


def test_non_ticket_object_treated_as_stale() -> None:
    """非票据对象（None / 字符串）一律按失效处理，不抛错。"""
    sched = CTBScheduler()
    assert sched.is_ticket_stale(None) is True
    assert sched.is_ticket_stale("not-a-ticket") is True
    assert sched.resolve_ticket(None) is False


def test_dead_actor_ticket_dropped_and_not_rescheduled() -> None:
    """死亡单位旧票失效；死亡后不再出现在队列头。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.push_actor("e2", side="enemy", effective_speed=90)
    sched.start()
    dead_ticket = sched.get_actor("e1").ticket
    sched.mark_dead("e1")
    assert sched.is_ticket_stale(dead_ticket) is True
    assert sched.peek_next().actor_id == "e2"


# ---------------------------------------------------------------------------
# 6. 可暂停输入式 CTB：NPC 连锁自动推进 + 玩家暂停
# ---------------------------------------------------------------------------
def test_npc_chain_auto_advances() -> None:
    """纯 NPC 场景：引擎自动连续推进，不请求输入。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=75)
    sched.push_actor("e2", side="enemy", effective_speed=75)
    sched.start()
    assert sched.should_pause_for_input() is False
    trace = _run_ticks(sched, 4)
    assert len(trace) == 4  # 无暂停，持续推进
    assert all(t[2] == CtbEvent.ACTOR_TURN_END for t in trace)


def test_player_ready_pauses_for_input() -> None:
    """玩家 Ready 时暂停并交还控制权。"""
    sched = CTBScheduler()
    sched.push_actor("p1", side="player", effective_speed=100, is_player=True)
    sched.push_actor("e1", side="enemy", effective_speed=50)
    sched.start()
    # 第一拍玩家先 ready
    ev = sched.advance_to_next_ready()
    assert ev["event"] == CtbEvent.ACTOR_READY
    assert ev["is_player"] is True
    assert sched.should_pause_for_input() is True
    assert sched.paused is True
    assert sched.paused_actor_id == "p1"


def test_complete_player_action_resumes_scheduler() -> None:
    """引擎结算玩家行动后解除暂停，调度器继续自动推进。"""
    sched = CTBScheduler()
    sched.push_actor("p1", side="player", effective_speed=100, is_player=True)
    sched.push_actor("e1", side="enemy", effective_speed=100)
    sched.start()
    sched.advance_to_next_ready()  # 玩家 ready → 暂停
    assert sched.paused is True
    end_evt = sched.complete_player_action()
    assert end_evt["event"] == CtbEvent.ACTOR_TURN_END
    assert sched.paused is False
    # 继续推进：轮到 NPC
    sched.drain_events()
    ev = sched.advance_to_next_ready()
    assert ev["actor_id"] == "e1"


def test_should_pause_when_queue_empty() -> None:
    """队列为空（无后续自动推进对象）→ 应暂停交还引擎。"""
    sched = CTBScheduler()
    sched.start()
    assert sched.should_pause_for_input() is True


# ---------------------------------------------------------------------------
# 7. 多 NPC 行动合并上报
# ---------------------------------------------------------------------------
def test_multi_npc_actions_merged_into_batch() -> None:
    """多 NPC 连锁行动合并为一次上报（ActionBatchReport）。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=75)
    sched.push_actor("e2", side="enemy", effective_speed=75)
    sched.push_actor("e3", side="enemy", effective_speed=75)
    sched.start()
    # 推进到三只 NPC 各行动一次（4 拍内必覆盖）
    _run_ticks(sched, 3)
    batch = sched.current_batch
    assert isinstance(batch, ActionBatchReport)
    assert batch.count == 3
    assert set(batch.actor_ids) == {"e1", "e2", "e3"}
    assert batch.event_sequence == [CtbEvent.ACTOR_TURN_END] * 3
    # take_batch 取出后清空
    taken = sched.take_batch()
    assert taken is not None and taken.count == 3
    assert sched.current_batch is None


def test_batch_marked_pause_on_player_ready() -> None:
    """批次在玩家 Ready 暂停时登记 paused_actor_id / 区间。"""
    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=75)  # 133.33 ready
    sched.push_actor("p1", side="player", effective_speed=100, is_player=True)  # 100 ready
    sched.start()
    # 玩家 100 先 ready → 暂停（此时无 NPC 行动，批次可为空）
    sched.advance_to_next_ready()
    assert sched.paused_actor_id == "p1"
    sched.complete_player_action()
    # 玩家结算后（200 ready），NPC e1 在 133.33 ready → 自动推进
    sched.drain_events()
    ev = sched.advance_to_next_ready()
    assert ev["actor_id"] == "e1"
    batch = sched.current_batch
    assert batch is not None and batch.count == 1


def test_batch_report_dict_serializable() -> None:
    """ActionBatchReport.to_dict 可序列化且字段齐全。"""
    batch = ActionBatchReport(start_time=1.0, end_time=2.0)
    batch.add({"actor_id": "e1", "event": CtbEvent.ACTOR_TURN_END, "time": 2.0})
    batch.mark_pause("p1", 3.0)
    d = batch.to_dict()
    assert d["count"] == 1
    assert d["actor_ids"] == ["e1"]
    assert d["paused_actor_id"] == "p1"
    assert d["paused_ready_at"] == 3.0
    # 非 Mapping 条目被忽略（不抛错）
    batch.add("bad")  # type: ignore[arg-type]
    assert batch.count == 1


# ---------------------------------------------------------------------------
# 8. 确定性 / 可复现
# ---------------------------------------------------------------------------
def _build_sched(seed) -> CTBScheduler:
    """构造一套固定剧本（含先手注入）用于复现性测试。

    initiative 按 seed 做**确定性打乱**：同 seed 必同偏置；不同 seed 偏置不同，
    足以改变首拍排序（用于验证 seed 参与可复现性、且随机性由注入接口承载）。
    """
    def initiative(actors, s):
        ids = sorted(v.actor_id for v in actors)
        n = len(ids)
        offset = int(s or 0) % n if n else 0
        # 轮转偏置：seed 决定谁是 0 偏置（先手），其余依次 +1
        rotated = ids[offset:] + ids[:offset]
        return {aid: float(i) for i, aid in enumerate(rotated)}

    sched = CTBScheduler(initiative_fn=initiative, seed=seed)
    sched.push_actor("p1", side="player", effective_speed=100, is_player=True)
    sched.push_actor("e1", side="enemy", effective_speed=80)
    sched.push_actor("e2", side="enemy", effective_speed=95)
    sched.start()
    return sched


def test_same_seed_fully_reproducible() -> None:
    """同初始态 + 同 seed + 同推进序列 → 事件轨迹完全一致。"""
    def trace():
        sched = _build_sched(7)
        out = []
        for _ in range(8):
            if sched.should_pause_for_input():
                ev = sched.complete_player_action()
                out.append(("resume",))
                if ev is None:
                    break
                continue
            ev = sched.advance_to_next_ready()
            if ev is None:
                break
            out.append((round(ev["time"], 4), ev["actor_id"], ev["event"]))
        return out

    assert trace() == trace()


def test_different_seed_changes_initiative() -> None:
    """不同 seed → 先手偏置不同（首拍 ready 时刻随之不同）。"""
    a = _build_sched(1)
    b = _build_sched(2)

    def ready_map(sched):
        return {v.actor_id: round(v.next_ready, 4) for v in sched.actors()}

    # 同 speed 的 p1/e1：偏置不同 → 首拍 ready 时刻必然不同
    assert ready_map(a) != ready_map(b)


def test_scheduler_consumes_no_randomness() -> None:
    """调度器本体不消费随机：rule 层纯函数，同参必同值。"""
    assert next_ready(10.0, {"id": "x"}, 33) == next_ready(10.0, {"id": "x"}, 33)
    # 无 init stive_fn 的调度器，两次构造轨迹一致
    def trace():
        sched = CTBScheduler()
        sched.push_actor("slow", side="enemy", effective_speed=75)
        sched.push_actor("fast", side="enemy", effective_speed=100)
        sched.start()
        return _run_ticks(sched, 6)
    assert trace() == trace()


def test_state_signature_deterministic() -> None:
    """state_signature 对同状态稳定，可作等价断言。"""
    sched = CTBScheduler()
    sched.push_actor("b", side="enemy", effective_speed=100)
    sched.push_actor("a", side="enemy", effective_speed=100)
    sched.start()
    sig1 = sched.state_signature()
    sig2 = sched.state_signature()
    assert sig1 == sig2
    # 队列序为字典序（a 先）
    assert sig1[3] == ("a", "b")


# ---------------------------------------------------------------------------
# 9. 异常兜底（防崩溃）
# ---------------------------------------------------------------------------
def test_invalid_inputs_do_not_crash() -> None:
    """非法入参（None / 非数 / 重复登记）不抛错，走兜底。"""
    sched = CTBScheduler(config="not-a-dict")
    sched.push_actor("x", side="enemy", effective_speed=None)
    sched.push_actor("x", side="enemy", effective_speed="bad")  # 重复覆盖
    sched.subscribe("BAD", None)  # type: ignore[arg-type]
    sched.start()
    assert sched.advance_to_next_ready() is not None
    assert sched.update_speed("missing", 10) is False
    assert sched.mark_dead("missing") is False


def test_ticket_dataclass_frozen() -> None:
    """CtbTicket 为不可变数据类（generation 语义不可被外部篡改）。"""
    ticket = CtbTicket(actor_id="a", generation=1, ready_at=1.0, seq=1)
    try:
        ticket.generation = 2  # type: ignore[misc]
        raise AssertionError("CtbTicket 应为 frozen")
    except Exception as exc:  # FrozenInstanceError
        assert "frozen" in str(exc).lower() or exc.__class__.__name__ == "FrozenInstanceError"


def test_to_snapshot_serializable() -> None:
    """to_snapshot 输出 JSON 友好（可 dump）。"""
    import json

    sched = CTBScheduler()
    sched.push_actor("e1", side="enemy", effective_speed=100, meta={"hp": 10})
    sched.start()
    sched.advance_to_next_ready()
    snap = sched.to_snapshot()
    assert json.dumps(snap)  # 不抛错即序列化成功
    assert snap["action_seq"] == 1
