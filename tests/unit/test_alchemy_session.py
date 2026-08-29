"""调合会话状态机纯逻辑单测（M8 批3·路3B · qbot_rpg/core/alchemy_session.py）。

文件名：tests/unit/test_alchemy_session.py
创建时间：2026-08-29
作者：Hermes 子agent-3B

功能：状态迁移全表单测——无会话→各事件（/炼金 allowed / 投料·继承·确认·放弃 非法「无会话」/
  已有活跃冲突）；会话中→/投料 追加 allowed+update、/炼金 新配方 拒绝「调合进行中」、/确认
  终态、/放弃 终态、重复 /确认 幂等「已结算」、战斗打断→挂起；挂起→/调合续 恢复、/调合续
  但已有活跃 拒绝、超 30 天 recycle；instant_ok 战斗内豁免互斥；每个迁移正反例 +
  version 幂等 + 挂起/恢复判定 + SessionView 鸭子类型（dataclass/dict）+ 非调合会话防御。

依据：docs/m8_contract_核心机制.md 七（§7.1 状态迁移表 12 行 / §7.2 契约要点）+ 定稿
  【炼金】L176-183 + docs/m8_batch_plan.md 批3·路3B。规则出处以模块内注释为准。

测试风格对齐 tests/unit/test_quality.py / test_synthesis.py：纯 pytest、零 NoneBot、零
  world/session import（兄弟路 3A 并行仓编辑，异常判定走鸭子类型）、断言精确 dict 字段。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

import pytest

from qbot_rpg.core.alchemy_session import (
    ACTION_ACQUIRE,
    ACTION_NONE,
    ACTION_RECYCLE,
    ACTION_RESTORE,
    ACTION_SETTLE_ABANDON,
    ACTION_SETTLE_CONFIRM,
    ACTION_SUSPEND,
    ACTION_UPDATE,
    ALCHEMY_SESSION,
    ALCHEMY_SESSION_TYPES,
    CHALLENGE_SESSION,
    Event,
    NONE,
    SESSION_ACTIVE,
    SUSPENDED,
    TERMINATED,
    TEMPLATE_ALREADY_ACTIVE,
    TEMPLATE_ALREADY_ACTIVE_ALCHEMY,
    TEMPLATE_ALREADY_SETTLED,
    TEMPLATE_IN_PROGRESS,
    TEMPLATE_MESSAGES,
    TEMPLATE_NO_SESSION,
    can_start,
    instant_ok,
    is_alchemy_session,
    is_conflict,
    resumable,
    suspendable,
    terminate_idempotent,
    transition,
)


# ---------------------------------------------------------------------------
# SessionView 鸭子类型构造（dataclass / dict 两形态，对齐收口裁决）
# ---------------------------------------------------------------------------
@dataclass
class _View:
    """会话视图 dataclass 形态（SessionView 契约：{player_qid, session_type, payload,
    random_seed, version, created_at, last_active_at}）。"""

    player_qid: str
    session_type: str
    payload: Any
    random_seed: int = 1
    version: int = 1
    created_at: str = ""
    last_active_at: str = ""


def _view(session_type: str = ALCHEMY_SESSION, version: int = 1) -> _View:
    return _View(
        player_qid="p1",
        session_type=session_type,
        payload={"recipe_id": "r1", "materials": [], "version": version},
        random_seed=7,
        version=version,
    )


def _view_dict(session_type: str = ALCHEMY_SESSION, version: int = 1) -> Dict[str, Any]:
    return {
        "player_qid": "p1",
        "session_type": session_type,
        "payload": {"recipe_id": "r1", "materials": []},
        "random_seed": 7,
        "version": version,
        "created_at": "",
        "last_active_at": "",
    }


# ---------------------------------------------------------------------------
# §7.1 行1：无会话 + /炼金 → 会话中 acquire
# ---------------------------------------------------------------------------
def test_row1_none_alchemy_start_allowed() -> None:
    """行1 正例：无会话 + /炼金 → 会话中，action=acquire。"""
    d = transition(NONE, Event.ALCHEMY_START)
    assert d["allowed"] is True
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_ACQUIRE
    assert d["template_key"] is None


def test_row1_none_new_recipe_is_start() -> None:
    """P-1：无会话 + /炼金 <新配方>（NEW_RECIPE）→ 等同开会话 acquire（行1 语义延伸）。"""
    d = transition(NONE, Event.NEW_RECIPE)
    assert d["allowed"] is True
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_ACQUIRE


def test_row1_terminated_can_restart() -> None:
    """P-2：终态后 /炼金 → 等同无会话可重新 acquire（槽位已清）。"""
    d = transition(TERMINATED, Event.ALCHEMY_START)
    assert d["allowed"] is True
    assert d["action"] == ACTION_ACQUIRE
    assert d["next_state"] == SESSION_ACTIVE


# ---------------------------------------------------------------------------
# §7.1 行2：无会话 + /投料 /继承 /继承超 /加成 /确认 /放弃 → 非法「无会话」
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("event", [
    Event.FEED, Event.INHERIT, Event.INHERIT_SUPER, Event.BUFF,
    Event.CONFIRM, Event.ABANDON,
])
def test_row2_none_operation_illegal_no_session(event: Event) -> None:
    """行2 正例：无会话收到操作事件 → 非法转移「无会话」，保持无会话。"""
    d = transition(NONE, event)
    assert d["allowed"] is False
    assert d["next_state"] == NONE
    assert d["action"] == ACTION_NONE
    assert d["template_key"] == TEMPLATE_NO_SESSION
    assert TEMPLATE_MESSAGES[TEMPLATE_NO_SESSION] == "当前没有调合会话，先 /炼金 <配方> 开始"


def test_row2_none_terminated_illegal_no_session() -> None:
    """P-2：终态收到操作事件 → 非法「无会话」（除 CONFIRM 幂等走行11）。"""
    for event in (Event.FEED, Event.INHERIT, Event.ABANDON):
        d = transition(TERMINATED, event)
        assert d["allowed"] is False
        assert d["template_key"] == TEMPLATE_NO_SESSION


# ---------------------------------------------------------------------------
# §7.1 行3：无会话 + /炼金 但已有其它会话 → 拒绝「已有活跃」（全局互斥）
# ---------------------------------------------------------------------------
def test_row3_alchemy_start_conflict_rejected() -> None:
    """行3 正例：无会话 + /炼金 但已有其它会话（conflict）→ 拒绝「已有活跃」全局互斥。"""
    d = transition(NONE, Event.ALCHEMY_START, conflict=True)
    assert d["allowed"] is False
    assert d["next_state"] == NONE
    assert d["action"] == ACTION_NONE
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE
    assert TEMPLATE_MESSAGES[TEMPLATE_ALREADY_ACTIVE] == "已有活跃会话"


def test_can_start_conflict_rejected() -> None:
    """can_start 行3：启动前置含冲突 → 拒绝「已有活跃」。"""
    d = can_start(NONE, conflict=True)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE


def test_row3_terminated_conflict_rejected() -> None:
    """P-2/行3：终态 + conflict → 同样拒绝「已有活跃」。"""
    d = can_start(TERMINATED, conflict=True)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE


def test_is_conflict_duck_typing() -> None:
    """is_conflict 鸭子类型：类名 SessionConflictError（含子类）命中，其它异常不命中。"""

    class SessionConflictError(Exception):
        """兄弟路 3A 领域异常（world/session.py L20，本测试零 import 用同构类）。"""

    class _Sub(SessionConflictError):
        pass

    class _OtherError(Exception):
        pass

    assert is_conflict(SessionConflictError("x")) is True
    assert is_conflict(_Sub("x")) is True
    assert is_conflict(_OtherError("x")) is False
    assert is_conflict(ValueError("x")) is False
    assert is_conflict("not-an-exception") is False
    assert is_conflict(None) is False


# ---------------------------------------------------------------------------
# §7.1 行4：会话中 + /投料 /继承 /继承超 /加成 → 会话中 update（version 递增）
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("event", [
    Event.FEED, Event.INHERIT, Event.INHERIT_SUPER, Event.BUFF,
])
def test_row4_active_update_allowed(event: Event) -> None:
    """行4 正例：会话中 + 操作事件 → allowed，action=update，保持会话中（version 递增壳层落库）。"""
    d = transition(SESSION_ACTIVE, event, session_view=_view())
    assert d["allowed"] is True
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_UPDATE
    assert d["template_key"] is None


def test_row4_active_update_dict_view() -> None:
    """行4：dict 形态 SessionView 同样消费（鸭子类型 .session_type/.version 回退 dict 键）。"""
    d = transition(SESSION_ACTIVE, Event.FEED, session_view=_view_dict())
    assert d["allowed"] is True
    assert d["action"] == ACTION_UPDATE


def test_row4_challenge_alchemy_is_alchemy_session() -> None:
    """is_alchemy_session：alchemy 与 challenge_alchemy 均为调合类（批0 SESSION_TYPES）。"""
    assert ALCHEMY_SESSION in ALCHEMY_SESSION_TYPES
    assert CHALLENGE_SESSION in ALCHEMY_SESSION_TYPES
    assert is_alchemy_session(_view(ALCHEMY_SESSION)) is True
    assert is_alchemy_session(_view(CHALLENGE_SESSION)) is True
    assert is_alchemy_session(_view_dict(ALCHEMY_SESSION)) is True
    assert is_alchemy_session(None) is False


def test_p6_non_alchemy_active_view_conflict() -> None:
    """P-6：活跃会话非调合类（battle）→ 全局互斥「已有活跃」拒绝。"""
    d = transition(SESSION_ACTIVE, Event.FEED, session_view=_view("battle"))
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE
    d2 = transition(SESSION_ACTIVE, Event.CONFIRM, session_view=_view("battle"))
    assert d2["allowed"] is False
    assert d2["template_key"] == TEMPLATE_ALREADY_ACTIVE


# ---------------------------------------------------------------------------
# §7.1 行5：会话中 + /炼金 <新配方>（再发）→ 拒绝「调合进行中」
# ---------------------------------------------------------------------------
def test_row5_active_new_recipe_rejected() -> None:
    """行5 正例：会话中 + /炼金 <新配方> → 拒绝「调合进行中」（定稿 L176）。"""
    d = transition(SESSION_ACTIVE, Event.NEW_RECIPE)
    assert d["allowed"] is False
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_NONE
    assert d["template_key"] == TEMPLATE_IN_PROGRESS
    assert TEMPLATE_MESSAGES[TEMPLATE_IN_PROGRESS] == "调合进行中！/放弃 退出 或 /调合续 继续"


def test_row5_active_alchemy_start_rejected() -> None:
    """行5：会话中再发 /炼金（ALCHEMY_START）→ 同样拒绝「调合进行中」。"""
    d = transition(SESSION_ACTIVE, Event.ALCHEMY_START)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_IN_PROGRESS


def test_can_start_active_rejected() -> None:
    """can_start：会话中启动 → 拒绝「调合进行中」。"""
    d = can_start(SESSION_ACTIVE)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_IN_PROGRESS


# ---------------------------------------------------------------------------
# §7.1 行6：会话中 + 战斗打断 → 挂起(战斗) suspend（快照持久化）
# ---------------------------------------------------------------------------
def test_row6_battle_interrupt_suspend() -> None:
    """行6 正例：会话中 + 战斗打断 → 挂起(战斗)，action=suspend。"""
    d = transition(SESSION_ACTIVE, Event.BATTLE_INTERRUPT, session_view=_view())
    assert d["allowed"] is True
    assert d["next_state"] == SUSPENDED
    assert d["action"] == ACTION_SUSPEND
    assert d["template_key"] is None


def test_row6_battle_interrupt_noop_without_session() -> None:
    """行6 反例（补白）：无会话/已挂起/终态 + 战斗打断 → 无操作（action=无，状态不变）。"""
    for state in (NONE, SUSPENDED, TERMINATED):
        d = transition(state, Event.BATTLE_INTERRUPT)
        assert d["allowed"] is True
        assert d["next_state"] == state
        assert d["action"] == ACTION_NONE


# ---------------------------------------------------------------------------
# §7.1 行7：挂起(战斗) + /调合续（或 /炼金 恢复）→ 会话中 restore
# ---------------------------------------------------------------------------
def test_row7_resume_restore() -> None:
    """行7 正例：挂起(战斗) + /调合续 → 会话中，action=restore（快照恢复）。"""
    d = transition(SUSPENDED, Event.RESUME, session_view=_view())
    assert d["allowed"] is True
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_RESTORE
    assert d["template_key"] is None


def test_row7_alchemy_start_resumes() -> None:
    """行7：挂起(战斗) + /炼金（或 /炼金 恢复）→ 恢复而非新开会话。"""
    d = transition(SUSPENDED, Event.ALCHEMY_START, session_view=_view())
    assert d["allowed"] is True
    assert d["next_state"] == SESSION_ACTIVE
    assert d["action"] == ACTION_RESTORE
    d2 = transition(SUSPENDED, Event.NEW_RECIPE, session_view=_view())
    assert d2["allowed"] is True
    assert d2["action"] == ACTION_RESTORE


def test_row7_resume_without_session_rejected() -> None:
    """行7 反例：无会话 /调合续 → 非法「无会话」。"""
    d = transition(NONE, Event.RESUME)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_NO_SESSION


def test_p3_resume_while_active_rejected() -> None:
    """P-3：会话中 /调合续 → 拒绝「调合进行中」（无需续）。"""
    d = transition(SESSION_ACTIVE, Event.RESUME)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_IN_PROGRESS


# ---------------------------------------------------------------------------
# §7.1 行8：挂起(战斗) + /调合续 但已有活跃会话 → 拒绝「已有一个调合会话进行中」
# ---------------------------------------------------------------------------
def test_row8_resume_conflict_rejected() -> None:
    """行8 正例：挂起 + /调合续 但已有活跃会话 → 拒绝（定稿 L177）。"""
    d = transition(SUSPENDED, Event.RESUME, conflict=True)
    assert d["allowed"] is False
    assert d["next_state"] == SUSPENDED
    assert d["action"] == ACTION_NONE
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE_ALCHEMY
    assert TEMPLATE_MESSAGES[TEMPLATE_ALREADY_ACTIVE_ALCHEMY] == "已有一个调合会话进行中"


def test_row8_alchemy_start_conflict_rejected() -> None:
    """行8：挂起 + /炼金 但已有活跃会话 → 拒绝「已有一个调合会话进行中」。"""
    d = transition(SUSPENDED, Event.ALCHEMY_START, conflict=True)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_ALREADY_ACTIVE_ALCHEMY


# ---------------------------------------------------------------------------
# §7.1 行9/10/11：会话中 /确认 /放弃 → 终态；重复 /确认 → 幂等「已结算」
# ---------------------------------------------------------------------------
def test_row9_confirm_terminal_settle() -> None:
    """行9 正例：会话中 + /确认 → 终态，action=settle_confirm（品质结算）。"""
    d = transition(SESSION_ACTIVE, Event.CONFIRM, session_view=_view(version=3))
    assert d["allowed"] is True
    assert d["next_state"] == TERMINATED
    assert d["action"] == ACTION_SETTLE_CONFIRM
    assert d["template_key"] is None


def test_row10_abandon_terminal_settle() -> None:
    """行10 正例：会话中 + /放弃 → 终态，action=settle_abandon（退还材料）。"""
    d = transition(SESSION_ACTIVE, Event.ABANDON, session_view=_view())
    assert d["allowed"] is True
    assert d["next_state"] == TERMINATED
    assert d["action"] == ACTION_SETTLE_ABANDON
    assert d["template_key"] is None


def test_row11_confirm_repeat_settled_idempotent() -> None:
    """行11 正例：重复 /确认（会话行已删除，view 缺失）→ 终态幂等「已结算」，action=无 不双扣。"""
    d = transition(SESSION_ACTIVE, Event.CONFIRM, session_view=None)
    assert d["allowed"] is True
    assert d["next_state"] == TERMINATED
    assert d["action"] == ACTION_NONE
    assert d["template_key"] == TEMPLATE_ALREADY_SETTLED
    assert TEMPLATE_MESSAGES[TEMPLATE_ALREADY_SETTLED] == "已结算"


def test_row11_confirm_after_terminated_settled() -> None:
    """行11：终态后再 /确认 → 幂等「已结算」。"""
    d = transition(TERMINATED, Event.CONFIRM)
    assert d["template_key"] == TEMPLATE_ALREADY_SETTLED
    assert d["action"] == ACTION_NONE


def test_p3_suspended_confirm_abandon() -> None:
    """P-3：挂起中 /确认 → 拒绝「调合进行中」（先恢复）；挂起中 /放弃 → 终态退还材料。"""
    d = transition(SUSPENDED, Event.CONFIRM)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_IN_PROGRESS
    d2 = transition(SUSPENDED, Event.ABANDON)
    assert d2["allowed"] is True
    assert d2["next_state"] == TERMINATED
    assert d2["action"] == ACTION_SETTLE_ABANDON


# ---------------------------------------------------------------------------
# §7.1 行12：挂起(战斗) 超 30 天 → 僵尸回收 recycle（settle 回调含已投材料返还）
# ---------------------------------------------------------------------------
def test_row12_timeout_recycle() -> None:
    """行12 正例：挂起(战斗) + 超 30 天 → 终态，action=recycle（僵尸回收+材料返还回调）。"""
    d = transition(SUSPENDED, Event.TIMEOUT)
    assert d["allowed"] is True
    assert d["next_state"] == TERMINATED
    assert d["action"] == ACTION_RECYCLE
    assert d["template_key"] is None


def test_p4_timeout_active_recycle() -> None:
    """P-4：会话中（活跃）超 30 天同样回收（recycle_scan 按 last_active_at 扫描）。"""
    d = transition(SESSION_ACTIVE, Event.TIMEOUT)
    assert d["allowed"] is True
    assert d["next_state"] == TERMINATED
    assert d["action"] == ACTION_RECYCLE


def test_timeout_no_session_noop() -> None:
    """行12 反例：无会话 TIMEOUT → 无操作。"""
    d = transition(NONE, Event.TIMEOUT)
    assert d["allowed"] is True
    assert d["next_state"] == NONE
    assert d["action"] == ACTION_NONE


# ---------------------------------------------------------------------------
# §7.2 version 幂等原语（terminate_idempotent）
# ---------------------------------------------------------------------------
def test_terminate_idempotent_view_missing() -> None:
    """terminate_idempotent：view 缺失（行已 delete_session）→ 已结算 True。"""
    assert terminate_idempotent(0, None) is True
    assert terminate_idempotent(5, None) is True


def test_terminate_idempotent_version_threshold() -> None:
    """terminate_idempotent：version 已达/越过结算标记版本 → 已结算 True；未达 → False。"""
    assert terminate_idempotent(5, 5) is True    # version 已到结算标记
    assert terminate_idempotent(5, 6) is True    # version 已越过
    assert terminate_idempotent(5, 4) is False   # 未结算，可结算
    assert terminate_idempotent(None, 4) is False


# ---------------------------------------------------------------------------
# 挂起/恢复判定（§7.1 行6/7）
# ---------------------------------------------------------------------------
def test_suspendable() -> None:
    """suspendable：仅会话中可挂起（行6）。"""
    assert suspendable(SESSION_ACTIVE) is True
    assert suspendable(NONE) is False
    assert suspendable(SUSPENDED) is False
    assert suspendable(TERMINATED) is False


def test_resumable() -> None:
    """resumable：仅挂起(战斗)可恢复（行7）。"""
    assert resumable(SUSPENDED) is True
    assert resumable(SESSION_ACTIVE) is False
    assert resumable(NONE) is False
    assert resumable(TERMINATED) is False


# ---------------------------------------------------------------------------
# §7.2 / 批9A：战斗即时调合豁免互斥（F-10，/即时调合 不进入本状态机）
# ---------------------------------------------------------------------------
def test_instant_ok_in_battle_exempts_mutex() -> None:
    """F-10：in_battle=True 时不受会话互斥约束——会话中/挂起/无会话均放行。"""
    assert instant_ok(in_battle=True, state=SESSION_ACTIVE) is True
    assert instant_ok(in_battle=True, state=SUSPENDED) is True
    assert instant_ok(in_battle=True, state=NONE) is True
    assert instant_ok(in_battle=True, state=TERMINATED) is True


def test_instant_ok_out_of_battle_rejected() -> None:
    """F-10 反例：非战斗（in_battle=False）无即时调合，一律拒绝。"""
    assert instant_ok(in_battle=False, state=SESSION_ACTIVE) is False
    assert instant_ok(in_battle=False, state=NONE) is False
    assert instant_ok(in_battle=False, state=SUSPENDED) is False


# ---------------------------------------------------------------------------
# can_start 全状态 + 未知事件防御
# ---------------------------------------------------------------------------
def test_can_start_none_acquire() -> None:
    """can_start：无会话 → acquire 开会话（行1）。"""
    d = can_start(NONE)
    assert d["allowed"] is True
    assert d["action"] == ACTION_ACQUIRE
    assert d["next_state"] == SESSION_ACTIVE


def test_can_start_suspended_rejected() -> None:
    """P-1：挂起中 can_start → 拒绝（需恢复）。"""
    d = can_start(SUSPENDED)
    assert d["allowed"] is False
    assert d["template_key"] == TEMPLATE_IN_PROGRESS


def test_unknown_event_defensive() -> None:
    """防御：未知事件值（非 Event 成员）→ allowed False 且不抛异常（零 IO 防御降级）。"""
    d = transition(NONE, "bogus-event")  # type: ignore[arg-type]
    assert d["allowed"] is False
    assert d["action"] == ACTION_NONE
    assert d["next_state"] == NONE
