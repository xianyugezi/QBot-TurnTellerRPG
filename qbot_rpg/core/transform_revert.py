"""M13 6b 变换引擎 F2 还原（细化_6b §2.2：三路归一 + state_policy + 形态冷却）。

文件名：transform_revert.py
创建时间：2026-09-02
依据：docs/细化/细化_6b_职业库与变换引擎.md（409 行 v1.0）：
  - §2.2 还原结算 F2：三路归一（自然结束 turns 耗尽 / 主动 revert_form /
    被驱散 dispel_reverts）→ state_policy 执行（combo/marks/buff 按
    clear/keep）→ 形态冷却（cooldown 起算）→ 回合 tick 推进（D-03 挂
    end_turn tick；D-05 驱散时点：dispel 立即清状态、还原延迟到下一回合
    结束 tick）。
  - §3.1 五态 S3（FORM_ACTIVE）→ S4（REVERTING 瞬态）→ S5（COOLDOWN）。

功能描述：
  - revert_transform(state, ctx, *, reason, hook) 三路归一还原入口：
      reason ∈ {"natural", "revert_form", "dispel"}：
      - natural：turns 耗尽自然结束；
      - revert_form：主动施放还原技（平息战意类）；
      - dispel：形态状态被驱散（dispel_reverts=true 联动）。
  - state_policy 执行：combo/marks/buff 按 {clear, keep} 决定是否清空。
  - 形态冷却：cooldown_remaining = transform.cooldown（还原后进入 COOLDOWN）。
  - 回合 tick：tick_cooldown(state, ctx) 回合结束递减（D-03）。

工程补白（契约/细化未显式定义处的实现口径，显式标注供审查）：
  P-1  state_policy 三键缺省 keep（契约 §1.4 枚举 {clear, keep}，缺省保守不清）。
  P-2  natural 还原时 remaining<=0 判定（含当回合：remaining 初始=turns 含当回合）。
  P-3  dispel 还原的冷却口径与 natural/revert_form 一致（dispel_reverts 联动不豁免冷却）。
  P-4  被驱散时点（D-05）：本引擎提供 dispel_triggered() 标记函数，实际延迟
       还原由战斗层在下一回合结束 tick 调用 revert_transform 完成（引擎不内置定时）。

铁律：零 NoneBot import；完整类型标注；纯函数确定性；零定时器/零睡眠；
不引入随机；不 git commit。仅依赖标准库（core 层零 import content/data）。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Mapping, Optional

# =====================================================================================
# 常量（契约 §1.4 / §2.2）
# =====================================================================================

# 还原原因三路（契约 §2.2 三路归一）
REVERT_NATURAL: str = "natural"      # 自然结束（turns 耗尽）
REVERT_FORM: str = "revert_form"     # 主动还原技
REVERT_DISPEL: str = "dispel"        # 被驱散（dispel_reverts 联动）
REVERT_REASONS: tuple = (REVERT_NATURAL, REVERT_FORM, REVERT_DISPEL)

# state_policy 三键（契约 §1.4 #32~#34）
POLICY_COMBO: str = "combo"
POLICY_MARKS: str = "marks"
POLICY_BUFF: str = "buff"
POLICY_KEYS: tuple = (POLICY_COMBO, POLICY_MARKS, POLICY_BUFF)

# state_policy 值域（契约 §1.4：{clear, keep}）
POLICY_CLEAR: str = "clear"
POLICY_KEEP: str = "keep"
POLICY_VALUES: tuple = (POLICY_CLEAR, POLICY_KEEP)

# 默认 state_policy（P-1：缺省保守不清）
DEFAULT_STATE_POLICY: Dict[str, str] = {
    POLICY_COMBO: POLICY_KEEP,
    POLICY_MARKS: POLICY_KEEP,
    POLICY_BUFF: POLICY_KEEP,
}

# 形态状态字段（对齐 transform_snapshot 7 字段 T1~T7；本引擎只读写相关键）
STATE_FORM: str = "form"
STATE_REMAINING: str = "remaining"
STATE_COOLDOWN: str = "cooldown_remaining"
STATE_FORM_STATUS: str = "form_status_id"
STATE_JOB_ID: str = "job_id"


# =====================================================================================
# 状态读取辅助
# =====================================================================================

def _state_of(ctx: Mapping[str, Any], side: str = "player") -> Dict[str, Any]:
    """从 ctx 读取玩家侧 transform_state（缺省建常态骨架，不改引用）。"""
    player = ctx.get(side)
    if not isinstance(player, Mapping):
        return {}
    ps = player.get("persistent_state")
    if isinstance(ps, Mapping):
        ts = ps.get("transform_state")
        if isinstance(ts, Mapping):
            return dict(ts)
    return {}


def _policy_of(transform: Optional[Mapping[str, Any]]) -> Dict[str, str]:
    """读取 transform.state_policy（缺省 DEFAULT_STATE_POLICY）。"""
    if not isinstance(transform, Mapping):
        return dict(DEFAULT_STATE_POLICY)
    sp = transform.get("state_policy")
    if not isinstance(sp, Mapping):
        return dict(DEFAULT_STATE_POLICY)
    out: Dict[str, str] = dict(DEFAULT_STATE_POLICY)
    for k in POLICY_KEYS:
        v = sp.get(k)
        if isinstance(v, str) and v in POLICY_VALUES:
            out[k] = v
    return out


def _cooldown_of(transform: Optional[Mapping[str, Any]]) -> int:
    """读取 transform.cooldown（缺省 0；负值钳 0）。"""
    if not isinstance(transform, Mapping):
        return 0
    cd = transform.get("cooldown")
    if isinstance(cd, (int, float)) and not isinstance(cd, bool):
        return max(int(cd), 0)
    return 0


# =====================================================================================
# state_policy 执行
# =====================================================================================

def apply_state_policy(
    ctx: Mapping[str, Any],
    policy: Mapping[str, str],
    *,
    side: str = "player",
    combo_clear: Optional[Callable[[str, Mapping[str, Any], str], Any]] = None,
    marks_clear: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    buff_remove: Optional[Callable[[str, Mapping[str, Any], str], Any]] = None,
) -> Dict[str, Any]:
    """state_policy 执行（契约 §1.4：combo/marks/buff 按 clear/keep 清空）。

    注入三通道（G0：core 层不 import content/data）：
      - combo_clear(side, snap, reason)：连段清零（复用 combo.clear 签名）；
      - marks_clear(side, snap)：印记整组清空（复用 marks.apply_clear）；
      - buff_remove(side, snap, status_id)：状态移除（复用 effects.remove_status）。
    未注入 → 只登记 acted 不实际清（战斗层接线后生效）。

    返回 {applied: {combo, marks, buff}, acted: [...]} 契约。
    """
    out: Dict[str, Any] = {"applied": {}, "acted": []}
    snap_raw = ctx.get("battle_state")
    snap: Dict[str, Any] = dict(snap_raw) if isinstance(snap_raw, Mapping) else {}
    if policy.get(POLICY_COMBO) == POLICY_CLEAR and combo_clear is not None:
        combo_clear(side, snap, "transform_revert")
        out["applied"][POLICY_COMBO] = POLICY_CLEAR
        out["acted"].append("combo")
    if policy.get(POLICY_MARKS) == POLICY_CLEAR and marks_clear is not None:
        marks_clear(side, snap)
        out["applied"][POLICY_MARKS] = POLICY_CLEAR
        out["acted"].append("marks")
    if policy.get(POLICY_BUFF) == POLICY_CLEAR and buff_remove is not None:
        ts = _state_of(ctx, side)
        status_id = ts.get(STATE_FORM_STATUS)
        if isinstance(status_id, str) and status_id:
            buff_remove(side, snap, status_id)
            out["applied"][POLICY_BUFF] = POLICY_CLEAR
            out["acted"].append("buff")
    return out


# =====================================================================================
# 回合 tick（D-03：挂 end_turn ⑥ 之后）
# =====================================================================================

def tick_cooldown(state: Dict[str, Any]) -> Dict[str, Any]:
    """回合结束冷却递减（D-03：S5 COOLDOWN 每回合 -1，归 0 回 NORMAL）。

    纯函数：返回新 state（不原地改）。
    """
    out = dict(state)
    cd = int(out.get(STATE_COOLDOWN, 0) or 0)
    if cd > 0:
        out[STATE_COOLDOWN] = cd - 1
    return out


def tick_remaining(state: Dict[str, Any]) -> Dict[str, Any]:
    """回合结束形态剩余递减（F2 自然结束判定：remaining-1，<=0 触发还原）。

    纯函数：返回新 state。remaining<=0 时保持 0（还原判定由调用方做）。
    """
    out = dict(state)
    rem = int(out.get(STATE_REMAINING, 0) or 0)
    if rem > 0:
        out[STATE_REMAINING] = rem - 1
    return out


# =====================================================================================
# 三路归一还原入口
# =====================================================================================

def revert_transform(
    ctx: Mapping[str, Any],
    transform: Optional[Mapping[str, Any]] = None,
    *,
    reason: str = REVERT_NATURAL,
    side: str = "player",
    combo_clear: Optional[Callable[[str, Mapping[str, Any], str], Any]] = None,
    marks_clear: Optional[Callable[[str, Mapping[str, Any]], Any]] = None,
    buff_remove: Optional[Callable[[str, Mapping[str, Any], str], Any]] = None,
) -> Dict[str, Any]:
    """F2 还原结算（三路归一入口，契约 §2.2）。

    流程：
      1. 读当前 transform_state（form/remaining/cooldown_remaining）；
      2. 三路原因归一（reason ∈ natural/revert_form/dispel）：
         - natural：remaining<=0 才还原（否则返回 ok=False reason=still_active）；
         - revert_form / dispel：立即还原（不判 remaining）；
      3. state_policy 执行（apply_state_policy）；
      4. 形态冷却：cooldown_remaining = transform.cooldown（P-3 dispel 不豁免）；
      5. 写回常态骨架（form=null + remaining=0 + cooldown=cooldown 值）。

    返回 {ok, reverted, reason, messages, state} 契约：
      ok=True 表示还原已执行（或已在常态无需还原）；
      state 为还原后的 transform_state（写回由调用方做）。
    """
    if reason not in REVERT_REASONS:
        reason = REVERT_NATURAL
    ts = _state_of(ctx, side)
    form = ts.get(STATE_FORM)
    if form is None or not str(form):
        # 已在常态（NORMAL/S5 冷却期）→ 无事可还原
        return {"ok": True, "reverted": False, "reason": reason,
                "messages": ["当前不在形态中"], "state": dict(ts)}
    if reason == REVERT_NATURAL:
        rem = int(ts.get(STATE_REMAINING, 0) or 0)
        if rem > 0:
            return {"ok": False, "reverted": False, "reason": reason,
                    "messages": [f"形态剩余 {rem} 回合，未到自然结束"],
                    "state": dict(ts)}
    # state_policy 执行
    policy = _policy_of(transform)
    applied = apply_state_policy(
        ctx, policy, side=side,
        combo_clear=combo_clear, marks_clear=marks_clear, buff_remove=buff_remove,
    )
    # 形态冷却（P-3：三路一致）
    cd = _cooldown_of(transform)
    new_state: Dict[str, Any] = {
        STATE_FORM: None,
        STATE_REMAINING: 0,
        STATE_COOLDOWN: cd,
        STATE_FORM_STATUS: None,
        STATE_JOB_ID: str(ts.get(STATE_JOB_ID, "") or ""),
    }
    return {
        "ok": True, "reverted": True, "reason": reason,
        "messages": [f"形态还原（{reason}），进入冷却 {cd} 回合"],
        "state": new_state, "policy_applied": applied,
    }


# =====================================================================================
# 还原判定辅助（战斗层接线用）
# =====================================================================================

def should_revert_natural(state: Mapping[str, Any]) -> bool:
    """自然结束判定：form 非空且 remaining<=0 → 应还原。"""
    form = state.get(STATE_FORM)
    if form is None or not str(form):
        return False
    return int(state.get(STATE_REMAINING, 0) or 0) <= 0


def dispel_triggered(ctx: Mapping[str, Any], *, side: str = "player") -> bool:
    """被驱散标记（D-05：dispel 立即清状态，还原延迟下一回合结束 tick）。

    战斗层在 dispel 事件发生时写 ctx[side].persistent_state.transform_pending_dispel=True，
    本函数读取该标记；战斗层在下一回合结束 tick 消费后清除。
    """
    player = ctx.get(side)
    if not isinstance(player, Mapping):
        return False
    ps = player.get("persistent_state")
    if isinstance(ps, Mapping):
        return bool(ps.get("transform_pending_dispel", False))
    return False


__all__ = [
    "REVERT_NATURAL", "REVERT_FORM", "REVERT_DISPEL", "REVERT_REASONS",
    "POLICY_COMBO", "POLICY_MARKS", "POLICY_BUFF", "POLICY_KEYS",
    "POLICY_CLEAR", "POLICY_KEEP", "POLICY_VALUES", "DEFAULT_STATE_POLICY",
    "STATE_FORM", "STATE_REMAINING", "STATE_COOLDOWN", "STATE_FORM_STATUS",
    "STATE_JOB_ID",
    "apply_state_policy", "tick_cooldown", "tick_remaining",
    "revert_transform", "should_revert_natural", "dispel_triggered",
]
