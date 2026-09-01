"""M13 6c on_season_change 换季事件单测（tests/unit/test_season_events.py · M13 批10 路10C）。

覆盖细化_6c §2.5 M7（E1~E6）：
  - 事件枚举登记表（V11 依赖）
  - 恰一次幂等（换季只触发一次）
  - L2 proc 执行（runner 注入）
  - 战斗外/缺段降级
  - 战斗结束清理

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.core.season_events import (
    LAST_SEASON_IDX_KEY,
    ON_SEASON_CHANGE,
    SEASON_EVENT_STATE_KEY,
    SEASON_EVENTS,
    clear_season_event_state,
    season_changed,
    trigger_season_event,
)


# ---------------------------------------------------------------------------
# 事件枚举登记
# ---------------------------------------------------------------------------
def test_event_enum_registered() -> None:
    """事件枚举登记表含 on_season_change（V11 依赖）。"""
    assert ON_SEASON_CHANGE in SEASON_EVENTS


def test_event_state_key_constants() -> None:
    assert SEASON_EVENT_STATE_KEY == "season_event_state"
    assert LAST_SEASON_IDX_KEY == "last_season_idx"


# ---------------------------------------------------------------------------
# 换季判定
# ---------------------------------------------------------------------------
def test_season_changed_true_when_new() -> None:
    """生效季节 spring（idx 0）→ 当前 summer（idx 1）→ 换季。"""
    state = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 0}}
    assert season_changed(state, "summer") is True


def test_season_changed_false_same() -> None:
    """生效季节 summer → 当前 summer → 未换季。"""
    state = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 1}}
    assert season_changed(state, "summer") is False


def test_season_changed_true_initial() -> None:
    """缺段（无 season_event_state）→ 缺省 -1 → 首次必触发。"""
    assert season_changed({}, "spring") is True


def test_season_changed_unknown_season_false() -> None:
    """未知季节 → idx -1 == 缺省 → 不触发（防御）。"""
    state = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: -1}}
    assert season_changed(state, "bogus") is False


# ---------------------------------------------------------------------------
# 触发 + 恰一次幂等
# ---------------------------------------------------------------------------
def test_trigger_first_time() -> None:
    """首次换季 → triggered=True + 幂等标记写回。"""
    state: Dict[str, Any] = {}
    r = trigger_season_event(state, "spring")
    assert r["triggered"] is True
    assert r["from_idx"] == -1 and r["to_idx"] == 0
    assert state[SEASON_EVENT_STATE_KEY][LAST_SEASON_IDX_KEY] == 0


def test_trigger_second_time_noop() -> None:
    """同季再触发 → 幂等无操作（triggered=False）。"""
    state: Dict[str, Any] = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 0}}
    r = trigger_season_event(state, "spring")
    assert r["triggered"] is False


def test_trigger_proc_runner_called() -> None:
    """proc_runner 注入 → 每条 proc 执行。"""
    state: Dict[str, Any] = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 0}}
    called: List[str] = []

    def runner(proc: Any, runtime: Any) -> Any:
        called.append(str(proc.get("id", "")))
        return type("R", (), {"ok": True})()

    procs = [{"id": "p1", "type": "heal"}, {"id": "p2", "type": "dispel"}]
    r = trigger_season_event(state, "summer", procs=procs, runtime=object(), proc_runner=runner)
    assert r["triggered"] is True
    assert set(called) == {"p1", "p2"}
    assert len(r["proc_results"]) == 2


def test_trigger_no_runner_skips() -> None:
    """runner 未注入 → proc 只登记 skipped（不执行不阻断）。"""
    state: Dict[str, Any] = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 0}}
    procs = [{"id": "p1", "type": "heal"}]
    r = trigger_season_event(state, "summer", procs=procs)
    assert r["triggered"] is True
    assert r["proc_results"][0]["skipped"] == "runner_not_injected"


def test_trigger_proc_exception_isolated() -> None:
    """proc 抛异常 → 该条 ok=False 不阻断换季。"""
    state: Dict[str, Any] = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 0}}

    def runner(proc: Any, runtime: Any) -> Any:
        raise RuntimeError("boom")

    r = trigger_season_event(state, "summer", procs=[{"id": "p1"}],
                             runtime=object(), proc_runner=runner)
    assert r["triggered"] is True
    assert r["proc_results"][0]["ok"] is False
    assert r["proc_results"][0]["error"] == "proc_exception"


def test_trigger_marks_idempotent_state() -> None:
    """触发后幂等段写回 → 下次同季不触发。"""
    state: Dict[str, Any] = {}
    trigger_season_event(state, "spring")
    r2 = trigger_season_event(state, "spring")
    assert r2["triggered"] is False


# ---------------------------------------------------------------------------
# 战斗结束清理
# ---------------------------------------------------------------------------
def test_clear_resets_state() -> None:
    """战斗结束 → 幂等段复位 -1（下次战斗首季必触发）。"""
    state: Dict[str, Any] = {SEASON_EVENT_STATE_KEY: {LAST_SEASON_IDX_KEY: 2}}
    clear_season_event_state(state)
    assert state[SEASON_EVENT_STATE_KEY][LAST_SEASON_IDX_KEY] == -1


def test_clear_recreates_missing() -> None:
    """缺段 → 清理建段。"""
    state: Dict[str, Any] = {}
    clear_season_event_state(state)
    assert state[SEASON_EVENT_STATE_KEY][LAST_SEASON_IDX_KEY] == -1
