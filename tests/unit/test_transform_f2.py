"""M13 6b 变换引擎 F2 还原单测（tests/unit/test_transform_f2.py · M13 批6 路6B）。

覆盖细化_6b §2.2 还原结算 F2：
  - 三路归一：自然结束（turns 耗尽）/ 主动 revert_form / 被驱散 dispel_reverts
  - state_policy 执行（combo/marks/buff 按 clear/keep）
  - 形态冷却（cooldown 起算）
  - 回合 tick 推进（D-03 冷却递减 / remaining 递减）
  - 已常态时还原 → ok=True reverted=False

测试目标：qbot_rpg.core.transform_revert.{revert_transform, apply_state_policy,
tick_cooldown, tick_remaining, should_revert_natural, dispel_triggered}

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠；不引入随机。
"""

from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.core.transform_revert import (
    DEFAULT_STATE_POLICY,
    REVERT_DISPEL,
    REVERT_FORM,
    REVERT_NATURAL,
    STATE_COOLDOWN,
    STATE_FORM,
    apply_state_policy,
    dispel_triggered,
    revert_transform,
    should_revert_natural,
    tick_cooldown,
    tick_remaining,
)


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _transform(**over: Any) -> Dict[str, Any]:
    t: Dict[str, Any] = {
        "transform_skill": "berserk",
        "transform_to": "berserker_form",
        "duration": "turns",
        "turns": 4,
        "revert": True,
        "cooldown": 5,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
    }
    t.update(over)
    return t


def _ctx(transform_state: Dict[str, Any], *, pending_dispel: bool = False) -> Dict[str, Any]:
    ps: Dict[str, Any] = {"transform_state": dict(transform_state)}
    if pending_dispel:
        ps["transform_pending_dispel"] = True
    return {"player": {"persistent_state": ps}, "battle_state": {}}


def _active_state(**over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {
        "job_id": "berserker",
        "form": "berserker_form",
        "form_name": "狂战士形态",
        "remaining": 3,
        "cooldown_remaining": 0,
        "form_status_id": "form_berserker",
        "active_skill_set": "transform_skills",
    }
    s.update(over)
    return s


# ---------------------------------------------------------------------------
# 三路归一
# ---------------------------------------------------------------------------
def test_revert_natural_when_remaining_zero() -> None:
    """自然结束：remaining=0 → 还原（ok=True reverted=True reason=natural）。"""
    ctx = _ctx(_active_state(remaining=0))
    r = revert_transform(ctx, _transform(), reason=REVERT_NATURAL)
    assert r["ok"] is True and r["reverted"] is True
    assert r["reason"] == REVERT_NATURAL
    assert r["state"][STATE_FORM] is None
    assert r["state"][STATE_COOLDOWN] == 5  # 冷却起算


def test_revert_natural_remaining_positive_keeps_form() -> None:
    """自然结束但 remaining>0 → 不还原（ok=False）。"""
    ctx = _ctx(_active_state(remaining=3))
    r = revert_transform(ctx, _transform(), reason=REVERT_NATURAL)
    assert r["ok"] is False and r["reverted"] is False
    assert r["state"][STATE_FORM] == "berserker_form"


def test_revert_form_immediate() -> None:
    """主动 revert_form：立即还原（不判 remaining）。"""
    ctx = _ctx(_active_state(remaining=3))
    r = revert_transform(ctx, _transform(), reason=REVERT_FORM)
    assert r["ok"] is True and r["reverted"] is True
    assert r["reason"] == REVERT_FORM
    assert r["state"][STATE_FORM] is None


def test_revert_dispel_immediate() -> None:
    """被驱散 dispel：立即还原（P-3 冷却不豁免）。"""
    ctx = _ctx(_active_state(remaining=2))
    r = revert_transform(ctx, _transform(), reason=REVERT_DISPEL)
    assert r["ok"] is True and r["reverted"] is True
    assert r["reason"] == REVERT_DISPEL
    assert r["state"][STATE_COOLDOWN] == 5


def test_revert_already_normal_ok() -> None:
    """已在常态 → ok=True reverted=False（无事可还原）。"""
    ctx = _ctx({"form": None, "remaining": 0, "cooldown_remaining": 2})
    r = revert_transform(ctx, _transform(), reason=REVERT_NATURAL)
    assert r["ok"] is True and r["reverted"] is False


def test_revert_invalid_reason_falls_back_natural() -> None:
    """非法 reason → 回落 natural（无剩余 → 不还原）。"""
    ctx = _ctx(_active_state(remaining=2))
    r = revert_transform(ctx, _transform(), reason="bogus")
    assert r["reason"] == REVERT_NATURAL
    assert r["reverted"] is False


# ---------------------------------------------------------------------------
# state_policy 执行
# ---------------------------------------------------------------------------
def test_state_policy_clear_hooks_called() -> None:
    """policy=clear → 三通道全调（combo/marks/buff）。"""
    called: List[str] = []
    ctx = _ctx(_active_state())
    policy = {"combo": "clear", "marks": "clear", "buff": "clear"}
    r = apply_state_policy(
        ctx, policy,
        combo_clear=lambda side, snap, reason: called.append("combo"),
        marks_clear=lambda side, snap: called.append("marks"),
        buff_remove=lambda side, snap, sid: called.append("buff"),
    )
    assert set(called) == {"combo", "marks", "buff"}
    assert r["applied"] == {"combo": "clear", "marks": "clear", "buff": "clear"}


def test_state_policy_keep_no_calls() -> None:
    """policy=keep → 通道不调。"""
    called: List[str] = []
    ctx = _ctx(_active_state())
    r = apply_state_policy(
        ctx, DEFAULT_STATE_POLICY,
        combo_clear=lambda side, snap, reason: called.append("combo"),
        marks_clear=lambda side, snap: called.append("marks"),
        buff_remove=lambda side, snap, sid: called.append("buff"),
    )
    assert called == []
    assert r["applied"] == {}


def test_state_policy_mixed() -> None:
    """combo=clear + marks/buff=keep → 只调 combo。"""
    called: List[str] = []
    ctx = _ctx(_active_state())
    r = apply_state_policy(
        ctx, {"combo": "clear", "marks": "keep", "buff": "keep"},
        combo_clear=lambda side, snap, reason: called.append("combo"),
        marks_clear=lambda side, snap: called.append("marks"),
        buff_remove=lambda side, snap, sid: called.append("buff"),
    )
    assert called == ["combo"]
    assert r["applied"] == {"combo": "clear"}


def test_state_policy_default_keep() -> None:
    """transform 无 state_policy → 缺省 keep（P-1）。"""
    ctx = _ctx(_active_state())
    r = apply_state_policy(ctx, DEFAULT_STATE_POLICY)
    assert r["applied"] == {}


# ---------------------------------------------------------------------------
# 回合 tick（D-03）
# ---------------------------------------------------------------------------
def test_tick_cooldown_decrements() -> None:
    """冷却 5 → tick → 4。"""
    state = {"cooldown_remaining": 5}
    out = tick_cooldown(state)
    assert out["cooldown_remaining"] == 4


def test_tick_cooldown_zero_stays() -> None:
    """冷却 0 → 保持 0。"""
    out = tick_cooldown({"cooldown_remaining": 0})
    assert out["cooldown_remaining"] == 0


def test_tick_remaining_decrements() -> None:
    """剩余 3 → tick → 2。"""
    out = tick_remaining({"remaining": 3})
    assert out["remaining"] == 2


def test_tick_remaining_zero_stays() -> None:
    """剩余 0 → 保持 0。"""
    out = tick_remaining({"remaining": 0})
    assert out["remaining"] == 0


def test_tick_pure_function_no_mutation() -> None:
    """tick 纯函数：原 state 不被改。"""
    state = {"remaining": 3, "cooldown_remaining": 5}
    tick_remaining(state)
    tick_cooldown(state)
    assert state == {"remaining": 3, "cooldown_remaining": 5}


# ---------------------------------------------------------------------------
# 判定辅助
# ---------------------------------------------------------------------------
def test_should_revert_natural_true_when_remaining_zero() -> None:
    assert should_revert_natural({"form": "berserker_form", "remaining": 0}) is True


def test_should_revert_natural_false_when_remaining_positive() -> None:
    assert should_revert_natural({"form": "berserker_form", "remaining": 2}) is False


def test_should_revert_natural_false_when_no_form() -> None:
    assert should_revert_natural({"form": None, "remaining": 0}) is False


def test_dispel_triggered_true() -> None:
    ctx = _ctx({}, pending_dispel=True)
    assert dispel_triggered(ctx) is True


def test_dispel_triggered_false() -> None:
    ctx = _ctx({})
    assert dispel_triggered(ctx) is False
