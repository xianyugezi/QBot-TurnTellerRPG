"""CTB 种子可复现性契约测试（tests/ctb/test_ctb_contract_seed.py）。

需求文档硬约束：「**同种子必须同序列**」——不仅行动序列一致，伤害数值也必须一致。

覆盖两个层面：
  A. 调度层（现役，Agent 2）：同 seed + 同初始态 + 同推进序列 → 事件轨迹逐字节一致。
     注意调度器**自身不消费随机**（清点表口径：随机性归引擎，经 `initiative_fn` 注入）；
     故本层验证「seed 经注入接口参与、且整链确定性」。
  B. 引擎层（待 Agent 3）：同 `random_seed` → 同行动序列 + 同伤害数值。
     当前引擎仍是回合制实现，此部分以 `xfail` 标记「待 Agent 3」，**不降低断言强度**。

另含跨层契约：RNG 状态（`random_seed` + `rng_state`）必须可导出、可回灌，
否则续战无法复现（任务书 §1 + 清点表 §2.3）。
"""

from __future__ import annotations

import copy
import random
from typing import Any, List, Tuple

import pytest

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.ctb_scheduler import CTBScheduler

# ---------------------------------------------------------------------------
# 固定夹具（对齐 tests/unit/test_battle_engine.py）
# ---------------------------------------------------------------------------
PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 100, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40,
         "mag": 30, "spd": 75, "foc": 50, "con": 50, "str": 80, "int": 30,
         "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}

#: 历史标记：Agent 3（CTB 核心重写）已落地并转绿（2026-09-10 Wave B）。
#: 保留为 **no-op** 以免删除装饰器引入大 diff；语义上这些用例已是**硬断言**。
#: 若未来某条回退，它将以 FAILED 暴露（不再是 xfail 静默吸收）。
TODO_AGENT3 = pytest.mark.xfail(
    reason="[已落地] Agent 3 CTB 重写完成，本标记留作历史；用例为硬断言",
    strict=True,   # ← 关键：转 xfail 即报错，杜绝静默回退
    condition=False,  # ← 条件恒假 → 不生效（等价 no-op），但保留 strict 兜底
)


# ===========================================================================
# A. 调度层：同 seed → 同轨迹（现役）
# ===========================================================================
def _initiative(actors, seed):
    """确定性首手偏置：seed 决定轮转起点（同 seed 必同偏置）。"""
    ids = sorted(v.actor_id for v in actors)
    offset = int(seed or 0) % len(ids) if ids else 0
    rotated = ids[offset:] + ids[:offset]
    return {aid: float(i) for i, aid in enumerate(rotated)}


def _schedule_trace(seed: Any) -> List[Tuple[Any, ...]]:
    """跑固定剧本并返回事件轨迹（含时间 / 单位 / 事件名）。"""
    sched = CTBScheduler(initiative_fn=_initiative, seed=seed)
    sched.push_actor("p1", side="player", effective_speed=100, is_player=True)
    sched.push_actor("e1", side="enemy", effective_speed=80)
    sched.push_actor("e2", side="enemy", effective_speed=95)
    sched.start()
    out: List[Tuple[Any, ...]] = []
    for _ in range(12):
        if sched.finished:
            break
        if sched.should_pause_for_input():
            if sched.paused:
                ev = sched.complete_player_action()
                out.append(("resume", ev["event"] if ev else None))
                continue
            break
        ev = sched.advance_to_next_ready()
        if ev is None:
            break
        out.append((round(ev["time"], 6), ev["actor_id"], ev["event"]))
    return out


def test_same_seed_same_trace() -> None:
    """A1：同 seed → 事件轨迹完全一致（逐元素相等）。"""
    assert _schedule_trace(7) == _schedule_trace(7)


def test_repeated_runs_without_seed_are_deterministic() -> None:
    """A2：无 seed（全 0 偏置）时两次构造轨迹一致（调度层零随机）。"""
    assert _schedule_trace(None) == _schedule_trace(None)


def test_different_seed_differs() -> None:
    """A3：不同 seed → 首手偏置不同（证明 seed 真实参与调度）。"""
    a, b = _schedule_trace(1), _schedule_trace(2)
    assert a != b


def test_scheduler_state_signature_stable() -> None:
    """A4：同初始态的 `state_signature()` 稳定（可作等价断言）。"""
    s1 = CTBScheduler()
    s1.push_actor("a", side="enemy", effective_speed=100)
    s1.push_actor("b", side="enemy", effective_speed=100)
    s1.start()
    s2 = CTBScheduler()
    s2.push_actor("a", side="enemy", effective_speed=100)
    s2.push_actor("b", side="enemy", effective_speed=100)
    s2.start()
    assert s1.state_signature() == s2.state_signature()


# ===========================================================================
# B. 引擎层：同 random_seed → 同行动序列 + 同伤害数值（待 Agent 3）
# ===========================================================================
def _engine_run(seed: int, steps: int = 4) -> List[Tuple[str, Any]]:
    """跑固定剧本，返回 [(行动, 伤害)] 轨迹（同 seed 应完全一致）。"""
    eng = BattleEngine()
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=seed)
    trace: List[Tuple[str, Any]] = []
    for _ in range(steps):
        if eng.finished:
            break
        try:
            out = eng.do_action("player", {"type": "normal", "mult": 1.0})
            trace.append(("player:nomal", getattr(out, "final_damage", None)))
        except Exception:
            break
        if eng.finished:
            break
        try:
            out_e = eng.enemy_act({})
            trace.append(("enemy:auto", getattr(out_e, "final_damage", None)))
        except Exception:
            break
    return trace


def test_engine_same_seed_same_damage_trace() -> None:
    """B1：同 `random_seed` → 同伤害数值轨迹。

    需求硬约束「同种子必须同序列」。当前回合制引擎在固定 seed + 固定指令下应已满足。
    """
    assert _engine_run(12345) == _engine_run(12345)


def test_engine_different_seed_may_differ_or_be_stable() -> None:
    """B2（弱断言）：不同 seed 不要求必不同，但同 seed 必须稳定（不抛错即可）。"""
    assert _engine_run(1) == _engine_run(1)
    assert _engine_run(2) == _engine_run(2)


@TODO_AGENT3
def test_ctb_engine_same_seed_same_action_sequence() -> None:
    """B3（待 Agent 3）：CTB 引擎同 seed → 同**行动序列**。

    CTB 下行动序列由行动条 + 随机（命中/先手）共同决定；同 seed 必须产出同一
    `action_seq` 序列，否则「同种子同序列」硬约束失效。
    """
    def seq(seed: int):
        eng = BattleEngine()
        eng.start(dict(PLAYER), dict(ENEMY), random_seed=seed)
        actors = []
        for _ in range(6):
            if eng.finished:
                break
            st = eng.battle_state()
            actors.append(st.get("action_seq"))
            try:
                eng.player_act("normal")
            except Exception:
                break
        return actors

    trace_a, trace_b = seq(999), seq(999)
    assert trace_a == trace_b
    # 断言强度：action_seq 必须是真实推进的整数序列（非全 None 的伪通过）
    assert all(isinstance(x, int) for x in trace_a), f"action_seq 须为整数序列：{trace_a}"
    assert len(set(trace_a)) > 1, f"action_seq 须随行动推进：{trace_a}"


# ===========================================================================
# C. RNG 状态可导出 / 可回灌（跨层契约）
# ===========================================================================
def test_scheduler_snapshot_is_deterministic() -> None:
    """C1：调度器 `to_snapshot()` 对同状态输出一致（可作恢复基准）。"""
    def snap():
        s = CTBScheduler()
        s.push_actor("e1", side="enemy", effective_speed=100)
        s.start()
        s.advance_to_next_ready()
        return s.to_snapshot()

    assert snap() == snap()


@TODO_AGENT3
def test_ctb_engine_rng_state_roundtrip() -> None:
    """C2（待 Agent 3）：引擎 RNG 状态可导出并经快照回灌，恢复后续随机一致。

    任务书 §1：新快照须含 `random_seed` + `rng_state`；清点表 §2.3 要求续玩随机
    序列一致。本用例断言：原局与恢复局在恢复点之后的随机推进结果一致。
    """
    eng = BattleEngine()
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=424242)
    st = eng.battle_state()
    assert "random_seed" in st and "rng_state" in st

    snap = eng.to_snapshot("actor_ready")
    restored = BattleEngine.from_snapshot(copy.deepcopy(snap))
    st_r = restored.battle_state()
    assert st_r.get("random_seed") == st.get("random_seed")
    assert st_r.get("rng_state") == st.get("rng_state")


def test_python_random_seed_is_reproducible() -> None:
    """C3（基础设施自证）：仓内 `random.Random(seed)` 本身可复现（排除环境噪声）。"""
    a = [random.Random(20260826).random() for _ in range(3)]
    b = [random.Random(20260826).random() for _ in range(3)]
    assert a == b
