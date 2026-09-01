"""M13 批6 路6A · 6b 变换引擎 F1 触发测试（tests/unit/test_transform_f1.py）。

文件名：tests/unit/test_transform_f1.py
创建时间：2026-09-02
作者：Hermes 子agent-6A（M13 6b 变换引擎实现组批6路6A：并发同仓，仅新建本文件 +
  qbot_rpg/core/transform.py；不碰兄弟文件——6B 独占 core/transform_revert.py
  （F2 还原）、6C 独占 core/transform_snapshot.py（F3 快照））

测试目标：qbot_rpg.core.transform（F1 变换触发 + 5 态状态机框架）：
  - 5 态状态机：常量 / 迁移表 / resolve_transition / state_of_transform_state
    常态三分（S1/S3/S5）/ 瞬态集合（S2/S4 不落快照不占回合，D-03）；
  - 触发闸 C1~C4：形态激活期拒绝（TC-03）/ 冷却中拒绝（TC-03）/ 被控拒绝
    （TC-04）/ 资源不足拒绝（TC-02）/ 全部满足放行；
  - F1 主流程 trigger_transform：
    - TC-01 四动作同拍：效果先结算（resolve_hook 先于变换，TRF-1）→
      变换（不额外耗回合 TRF-2，action_used 语义）→ 技能位重排（SH-1~5）→
      state_policy 处理（默认清连段/印记 keep/buff keep）→ 形态状态挂载
      （D-02 双轨：transform_state.form + form_status_id 双写）→
      remaining=turns 含变身当回合；
    - C2/C3/C4 拒绝路径幂等（不写 transform_state / 不重结算）；
    - resolve 失败 → 变换不触发；
    - duration=battle → remaining=-1 哨兵（整场不还原）；
    - state_policy 三键 clear 全清路径（combo/marks/buff 各自断言）；
    - 钩子注入形态（rearrange_hook / apply_status_hook / reassess_chains_hook /
      resource_check_hook / skip_check / resolve_hook 桩验证时序与参数）；
    - TransformEngine 引擎注入模式（钩子挂 ctx + audit 观察口）。

依据：docs/细化/细化_6b_职业库与变换引擎.md：
  - §2.1 流程 F1（①~⑥ 时序 + TRF-1~6：效果先结算 / 零额外回合 / 不重结算 /
    触发技标签显式 combo_preserve / 怒气沉没 / 形态代价可配）；
  - §3.1 状态集（S1~S5 五态 + 进入/退出语义）；§3.2 状态图；
  - §3.3 触发条件 C1~C4 / 持续时间 / 洗牌 SH-1~5；
  - §1.4 state_policy 三键（combo/marks/buff clear|keep，默认 clear/keep/keep）；
  - §0.3 ADR（D-02 双轨 / D-03 计时挂回合 tick）；
  - §六 TC-01~04（变换触发 4 例）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机；不 git commit；只写本文件。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, cast

from qbot_rpg.core.transform import (
    SLOT_ACTIVE,
    SLOT_BASIC,
    SLOT_PASSIVE,
    SLOT_TRIGGER,
    STATE_COOLDOWN,
    STATE_FORM_ACTIVE,
    STATE_NORMAL,
    STATE_REVERTING,
    STATE_TRANSFORMING,
    TRANSFORM_STATE_FIELDS,
    TRANSFORM_STATE_KEY,
    TRANSFORM_STATES,
    TRANSIENT_STATES,
    TransformEngine,
    apply_state_policy,
    can_transform,
    empty_transform_state,
    is_cooldown_active,
    is_form_active,
    normalize_transform_state,
    rearrange_slots,
    resolve_transition,
    state_of_transform_state,
    transform_state_of,
    trigger_transform,
)

# =====================================================================================
# 夹具（狂战士 berserker 最小 transform 段，对齐细化_6b §1.3 字段表 / 批4 样例）
# =====================================================================================

FORM_ID = "berserker_form"
FORM_NAME = "狂战士形态"
FORM_STATUS_ID = "rage_form"
TRIGGER_SKILL = "berserk"
SKILL_SET = "transform_skills"


def _transform(
    *,
    duration: str = "turns",
    turns: int = 4,
    cooldown: int = 5,
    policy: Optional[Mapping[str, str]] = None,
    form_status_id: Optional[str] = FORM_STATUS_ID,
    derive_chains: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """最小合法 transform 段（§1.3 #21~#31；缺省 = 狂战士主示例语义）。"""
    seg: Dict[str, Any] = {
        "transform_skill": TRIGGER_SKILL,
        "transform_to": FORM_ID,
        "form_name": FORM_NAME,
        "duration": duration,
        "turns": turns,
        "revert": True,
        "cooldown": cooldown,
        "dispel_reverts": True,
        "state_policy": (
            dict(policy) if policy is not None
            else {"combo": "clear", "marks": "keep", "buff": "keep"}
        ),
        "skill_set": SKILL_SET,
        "equip_restrict": [],
        "derive_chains": list(derive_chains) if derive_chains is not None else ["chain_rage"],
    }
    if form_status_id is not None:
        seg["form_status_id"] = form_status_id
    return seg


def _skill(
    sid: str,
    stype: str = "active",
    derive_only: bool = False,
) -> Dict[str, Any]:
    """raw dict 技能条目（形态技能组 fixture）。"""
    entry: Dict[str, Any] = {"id": sid, "name": sid, "type": stype}
    if derive_only:
        entry["derive_only"] = True
    return entry


def _form_skills() -> List[Dict[str, Any]]:
    """形态技能组（transform_skills）：狂暴斩/怒涛斩/裂地击/平息战意 +
    大回旋·终（derive_only 不占位，SH-3）+ 战意沸腾（trigger 槽，SH-2）。"""
    return [
        _skill("form_basic", "basic"),
        _skill("狂暴斩"),
        _skill("怒涛斩"),
        _skill("裂地击"),
        _skill("平息战意"),
        _skill("大回旋·终", derive_only=True),
        _skill("战意沸腾", "trigger"),
    ]


def _normal_skills() -> List[Dict[str, Any]]:
    """常态技能组（常态技能位 fixture）：斩击/怒击/硬撼/战嚎/狂暴 + 怒意/血怒。"""
    return [
        _skill("basic_attack", "basic"),
        _skill("斩击"),
        _skill("怒击"),
        _skill("硬撼"),
        _skill("战嚎"),
        _skill("狂暴"),
        _skill("怒意", "passive"),
        _skill("血怒", "passive"),
    ]


def _snapshot() -> Dict[str, Any]:
    """常态装配快照（assemble_slots 产物形态，SH-1 常态主动位）。"""
    return {
        "slots": [
            {"slot": SLOT_BASIC, "skill_id": "basic_attack"},
            {"slot": SLOT_ACTIVE, "skill_id": "斩击"},
            {"slot": SLOT_ACTIVE, "skill_id": "怒击"},
            {"slot": SLOT_ACTIVE, "skill_id": "硬撼"},
            {"slot": SLOT_ACTIVE, "skill_id": "战嚎"},
            {"slot": SLOT_ACTIVE, "skill_id": "狂暴"},
            {"slot": SLOT_PASSIVE, "skill_id": "怒意"},
            {"slot": SLOT_PASSIVE, "skill_id": "血怒"},
        ],
        "active_order": ["斩击", "怒击", "硬撼", "战嚎", "狂暴"],
        "passive": [
            {"slot": SLOT_PASSIVE, "skill_id": "怒意"},
            {"slot": SLOT_PASSIVE, "skill_id": "血怒"},
        ],
        "trigger": [],
        "version": 1,
    }


def _ctx(
    *,
    transform: Optional[Mapping[str, Any]] = None,
    form_skills: Optional[List[Dict[str, Any]]] = None,
    combo_count: int = 0,
    combo_chain: Optional[str] = None,
    marks: Optional[List[Dict[str, Any]]] = None,
    buffs: Optional[List[Dict[str, Any]]] = None,
    transform_state: Optional[Mapping[str, Any]] = None,
    resolve_ok: bool = True,
) -> Dict[str, Any]:
    """构造测试 ctx（战斗快照段 + G0 注入钩子位；默认放行闸门）。"""
    combo_state: Dict[str, Any] = {"player": {}, "enemy": {}}
    if combo_chain or combo_count:
        combo_state["player"] = {
            "chain_id": combo_chain,
            "chain_name": combo_chain,
            "count": combo_count,
            "hold": False,
            "step_index": 0,
        }
    marks_state: Dict[str, Any] = {"player": list(marks) if marks is not None else [], "enemy": []}
    status_state: Dict[str, Any] = {
        "player": list(buffs) if buffs is not None else [],
        "enemy": [],
    }
    ctx: Dict[str, Any] = {
        "transform": dict(transform) if transform is not None else _transform(),
        "form_skills": list(form_skills) if form_skills is not None else _form_skills(),
        "transform_state": (
            dict(transform_state) if transform_state is not None
            else empty_transform_state("berserker")
        ),
        "combo_state": combo_state,
        "marks_state": marks_state,
        "status_state": status_state,
        "combo_events": [],
        "resolve_hook": (
            (lambda c, t: {"ok": True, "effects": [{"type": "heal", "value": 10}]})
            if resolve_ok
            else (lambda c, t: {"ok": False, "error": "结算失败"})
        ),
    }
    return ctx


def _cast_dict(obj: object) -> Dict[str, Any]:
    return cast(Dict[str, Any], obj)


# =====================================================================================
# 1. 5 态状态机（§3.1 状态集 + §3.2 状态图）
# =====================================================================================


def test_five_states_constants_exact() -> None:
    """五态常量精确（§3.1 S1~S5）+ 全集登记恰 5 态。"""
    assert STATE_NORMAL == "NORMAL"
    assert STATE_TRANSFORMING == "TRANSFORMING"
    assert STATE_FORM_ACTIVE == "FORM_ACTIVE"
    assert STATE_REVERTING == "REVERTING"
    assert STATE_COOLDOWN == "COOLDOWN"
    assert TRANSFORM_STATES == (
        STATE_NORMAL,
        STATE_TRANSFORMING,
        STATE_FORM_ACTIVE,
        STATE_REVERTING,
        STATE_COOLDOWN,
    )
    assert len(TRANSFORM_STATES) == 5


def test_transient_states_not_snapshotted() -> None:
    """瞬态集合（D-03）：S2/S4 不落快照、不占回合——恰为 TRANSFORMING/REVERTING。"""
    assert TRANSIENT_STATES == (STATE_TRANSFORMING, STATE_REVERTING)
    assert STATE_TRANSFORMING in TRANSIENT_STATES
    assert STATE_REVERTING in TRANSIENT_STATES
    assert STATE_NORMAL not in TRANSIENT_STATES
    assert STATE_FORM_ACTIVE not in TRANSIENT_STATES
    assert STATE_COOLDOWN not in TRANSIENT_STATES


def test_transition_table_full_path() -> None:
    """迁移表全路径（§3.2 状态图）：S1→S2→S3→S4→S5→S1。"""
    assert resolve_transition(STATE_NORMAL, "trigger") == STATE_TRANSFORMING
    assert resolve_transition(STATE_TRANSFORMING, "complete") == STATE_FORM_ACTIVE
    assert resolve_transition(STATE_FORM_ACTIVE, "expire") == STATE_REVERTING
    assert resolve_transition(STATE_FORM_ACTIVE, "revert_now") == STATE_REVERTING
    assert resolve_transition(STATE_REVERTING, "complete", cooldown_remaining=5) == STATE_COOLDOWN
    assert resolve_transition(STATE_REVERTING, "complete", cooldown_remaining=0) == STATE_NORMAL
    assert resolve_transition(STATE_COOLDOWN, "cooldown_done") == STATE_NORMAL


def test_transition_table_unknown_event_safe() -> None:
    """迁移表未知事件/未知源态 → None（确定性兜底，不抛异常）。"""
    assert resolve_transition(STATE_NORMAL, "expire") is None
    assert resolve_transition(STATE_FORM_ACTIVE, "trigger") is None
    assert resolve_transition(STATE_TRANSFORMING, "revert_now") is None
    assert resolve_transition("UNKNOWN", "trigger") is None
    assert resolve_transition(STATE_NORMAL, "bogus") is None


def test_state_of_transform_state_three_observable_states() -> None:
    """可观测用户态三分（§3.1）：form 非空 → S3；form 空+冷却>0 → S5；否则 S1。"""
    assert state_of_transform_state(empty_transform_state()) == STATE_NORMAL
    assert (
        state_of_transform_state(
            {"form": FORM_ID, "remaining": 3, "cooldown_remaining": 0}
        )
        == STATE_FORM_ACTIVE
    )
    assert (
        state_of_transform_state(
            {"form": None, "remaining": 0, "cooldown_remaining": 2}
        )
        == STATE_COOLDOWN
    )
    # S5 冷却期 form=null 且 cooldown>0 是合法形态（§4.1 T5）
    assert is_form_active({"form": FORM_ID}) is True
    assert is_form_active(empty_transform_state()) is False
    assert is_cooldown_active({"form": None, "cooldown_remaining": 3}) is True
    assert is_cooldown_active(empty_transform_state()) is False


def test_transform_state_fields_7_keys() -> None:
    """transform_state 段恰 7 键（§4.1 T1~T7，对齐 6C 契约口径）。"""
    assert TRANSFORM_STATE_FIELDS == (
        "job_id",
        "form",
        "form_name",
        "remaining",
        "cooldown_remaining",
        "form_status_id",
        "active_skill_set",
    )
    assert len(TRANSFORM_STATE_FIELDS) == 7


def test_normalize_forces_remaining_zero_when_form_null() -> None:
    """归一不变量：form=null（常态）时 remaining 强制 0（§4.1 T4）。"""
    out = normalize_transform_state(
        {"form": None, "remaining": 5, "cooldown_remaining": 2}
    )
    assert out["remaining"] == 0
    assert out["cooldown_remaining"] == 2  # S5 冷却独立保留（T5）


# =====================================================================================
# 2. 触发闸 C1~C4（§3.3 触发条件）
# =====================================================================================


def test_can_transform_all_conditions_met() -> None:
    """C1~C4 全部满足 → 放行（{ok: True, guard: \"\"}）。"""
    ctx = _ctx()
    result = can_transform(ctx)
    assert result["ok"] is True
    assert result["guard"] == ""


def test_can_transform_c1_form_active_rejected() -> None:
    """C1 形态激活期（transform_state.form 非空）→ 拒绝（TC-03 路径一）。"""
    ctx = _ctx(transform_state={"form": FORM_ID, "remaining": 3})
    result = can_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C1"


def test_can_transform_c2_resource_insufficient_rejected() -> None:
    """C2 资源不足（resource_check_hook 注入 ok=False）→ 拒绝（TC-02）。"""
    ctx = _ctx()
    ctx["resource_check_hook"] = (
        lambda c, t: {"ok": False, "reason": "怒气不足（需要 100，当前 80）"}
    )
    result = can_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C2"
    assert "怒气不足" in str(result["reason"])


def test_can_transform_c3_cooldown_rejected() -> None:
    """C3 形态冷却中（cooldown_remaining>0，S5）→ 拒绝（TC-03 路径二）。"""
    ctx = _ctx(transform_state={"form": None, "cooldown_remaining": 3})
    result = can_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C3"


def test_can_transform_c4_skipped_rejected() -> None:
    """C4 被控（skip_check 注入 True）→ 拒绝（TC-04）；怒气保留归战斗层。"""
    ctx = _ctx()
    ctx["skip_check"] = lambda c: True
    result = can_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C4"


def test_can_transform_default_gates_allow() -> None:
    """缺省闸门放行（无 hook 注入）：C2/C4 默认放行（F1-7），仅 C1/C3 结构判定。"""
    ctx = _ctx()
    ctx.pop("resolve_hook", None)
    assert can_transform(ctx)["ok"] is True


# =====================================================================================
# 3. F1 主流程 trigger_transform（TC-01 四动作同拍 + 拒绝路径 + 双轨挂载）
# =====================================================================================


def test_trigger_full_success_tc01_four_actions() -> None:
    """TC-01 变换触发四动作同拍：效果先结算 / job_form 切换 / 技能位重排 /
    state_policy / 形态状态挂载（D-02 双轨）/ remaining=turns 含变身当回合。"""
    events: List[str] = []
    ctx = _ctx(combo_count=3, combo_chain="chain_normal")

    def resolve(c: Mapping[str, Any], t: Mapping[str, Any]) -> Dict[str, Any]:
        events.append("resolve")
        return {"ok": True, "effects": [{"type": "heal", "value": 10}]}

    def apply_status(c: Mapping[str, Any], t: Mapping[str, Any], form: str) -> str:
        events.append(f"status:{form}")
        return FORM_STATUS_ID

    ctx["resolve_hook"] = resolve
    ctx["apply_status_hook"] = apply_status
    result = trigger_transform(ctx)
    assert result["ok"] is True
    # ① 效果先结算（TRF-1）：resolve 事件先于 transform_committed
    assert events[0] == "resolve"
    assert events[1] == f"status:{FORM_ID}"
    committed = [e for e in result["side_effects"] if e.get("type") == "transform_committed"]
    assert len(committed) == 1
    # ② 变换不额外耗回合（TRF-2）：action_used=True（行动权已由触发技消耗）
    assert result["action_used"] is True
    # ④b job_form 切换（D-02 引擎轨）
    ts = _cast_dict(result["transform_state"])
    assert ts["form"] == FORM_ID
    assert ts["form_name"] == FORM_NAME
    assert ts["job_id"] == "berserker"
    # ④a 形态状态挂载（D-02 效果轨双写）：form_status_id 登记 T6
    assert ts["form_status_id"] == FORM_STATUS_ID
    assert any(e.get("type") == "form_status_applied" for e in result["side_effects"])
    # ⑥ remaining=turns 含变身当回合（TC-01④）+ cooldown 从触发起算（REV-6）
    assert ts["remaining"] == 4
    assert ts["cooldown_remaining"] == 5
    # ④c 技能位重排（SH-1~5）产物
    slots = _cast_dict(result["slots_snapshot"])
    assert slots["slots"][0] == {"slot": SLOT_BASIC, "skill_id": "form_basic"}
    assert "狂暴斩" in slots["active_order"]
    # ④d state_policy 默认：清连段+清活跃链（combo=clear）
    assert ctx["combo_state"]["player"]["count"] == 0
    assert ctx["combo_state"]["player"]["chain_id"] is None
    assert any(
        e.get("type") == "combo_clear" and e.get("reason") == "transform"
        for e in ctx["combo_events"]
    )
    # 印记/buff 默认 keep：不被动
    assert ctx["marks_state"]["player"] == []
    assert ctx["status_state"]["player"] == []
    # 引擎轨落 ctx（transform_state 段挂回）
    assert ctx[TRANSFORM_STATE_KEY]["form"] == FORM_ID
    assert result["state"] == STATE_FORM_ACTIVE


def test_trigger_resolve_failure_aborts_transform() -> None:
    """触发技效果结算失败 → 变换不触发（不写形态、不重结算）。"""
    ctx = _ctx(resolve_ok=False, combo_count=2, combo_chain="chain_normal")
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert "结算失败" in str(result.get("reason"))
    assert result["state"] == STATE_NORMAL
    assert result["transform_state"]["form"] is None
    # 不重结算：resolve 只发生一次（side_effects 恰 1 条 resolve 事件）
    resolve_events = [e for e in result["side_effects"] if e.get("type") == "resolve"]
    assert len(resolve_events) == 1
    # 连段不被清除（未进入 ④d）
    assert ctx["combo_state"]["player"].get("count") == 2


def test_trigger_rejected_when_form_active_tc03() -> None:
    """C1 形态激活期再施放触发技 → 拒绝（TC-03 路径一）：不写段、不耗额外回合。"""
    ctx = _ctx(transform_state={"form": FORM_ID, "remaining": 3})
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C1"
    assert result["transform_state"]["form"] == FORM_ID  # 形态保持
    assert result["action_used"] is False
    assert result["side_effects"] == []


def test_trigger_rejected_when_cooldown_tc03() -> None:
    """C3 冷却期施放触发技 → 拒绝（TC-03 路径二）：不写段、不耗回合。"""
    ctx = _ctx(transform_state={"form": None, "cooldown_remaining": 2})
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C3"
    assert "冷却中" in str(result.get("reason"))
    assert result["transform_state"]["form"] is None
    assert result["action_used"] is False


def test_trigger_rejected_when_skipped_tc04() -> None:
    """C4 被控回合内尝试变身 → 拒绝（TC-04）：不触发变换。"""
    ctx = _ctx()
    ctx["skip_check"] = lambda c: True
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C4"
    assert result["transform_state"]["form"] is None


def test_trigger_duration_battle_remaining_sentinel() -> None:
    """duration=battle → remaining=-1 哨兵（整场不还原，F1-6）。"""
    ctx = _ctx(transform=_transform(duration="battle", turns=0))
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["transform_state"]["remaining"] == -1


def test_trigger_default_hooks_no_injection() -> None:
    """无钩子注入（纯缺省）：四动作仍完整（效果先结算记录 / 形态状态缺省 /
    重排缺省组 / 派生链原样返回），确定性不炸。"""
    ctx = _ctx()
    ctx.pop("resolve_hook", None)
    ctx.pop("apply_status_hook", None)
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["transform_state"]["form"] == FORM_ID
    # 缺省 apply_status_hook → transform 段 form_status_id 候选登记（F1-1）
    assert result["transform_state"]["form_status_id"] == FORM_STATUS_ID
    # ⑤ 缺省 reassess → derive_chains 原样返回（F1-5）
    assert result["chains"] == ("chain_rage",)
    # ④c 缺省重排 → form_skills 组内装配
    slots = _cast_dict(result["slots_snapshot"])
    assert slots["slots"][0] == {"slot": SLOT_BASIC, "skill_id": "form_basic"}


# =====================================================================================
# 4. state_policy 三键 clear 全清（§1.4 #32~#34）
# =====================================================================================


def test_policy_clear_all_three_keys() -> None:
    """state_policy 三键全 clear：清连段 / 清印记 / 清 buff（§1.4）。"""
    marks = [{"mark_id": "m1", "count": 2}]
    buffs = [{"status_id": "b1", "category": "强化"}, {"status_id": "b2", "category": "增益"}]
    ctx = _ctx(
        transform=_transform(policy={"combo": "clear", "marks": "clear", "buff": "clear"}),
        combo_count=3,
        combo_chain="chain_normal",
        marks=marks,
        buffs=buffs,
    )
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert ctx["combo_state"]["player"]["count"] == 0
    assert ctx["marks_state"]["player"] == []
    assert ctx["status_state"]["player"] == []
    report = _cast_dict(result["policy_report"])
    assert report["combo"] == "clear"
    assert report["marks"] == "clear"
    assert report["buff"] == "clear"
    assert len(report["cleared_buffs"]) == 2


def test_policy_keep_all_three_keys() -> None:
    """state_policy 三键全 keep：连段/印记/buff 全部保留（跨形态保留，§1.4）。"""
    marks = [{"mark_id": "m1", "count": 2}]
    buffs = [{"status_id": "b1", "category": "强化"}]
    ctx = _ctx(
        transform=_transform(policy={"combo": "keep", "marks": "keep", "buff": "keep"}),
        combo_count=3,
        combo_chain="chain_normal",
        marks=marks,
        buffs=buffs,
    )
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert ctx["combo_state"]["player"]["count"] == 3  # 连段保留
    assert ctx["marks_state"]["player"] == marks       # 印记保留
    assert ctx["status_state"]["player"] == buffs      # buff 保留
    report = _cast_dict(result["policy_report"])
    assert report["combo"] == "keep"
    assert report["marks"] == "keep"
    assert report["buff"] == "keep"


def test_policy_clear_only_buffs_keeps_marks() -> None:
    """buff=clear 只清 buff 类（category=强化/增益），非 buff 条目（减益/其他）保留。"""
    buffs = [
        {"status_id": "b1", "category": "强化"},
        {"status_id": "d1", "category": "减益"},
        {"status_id": "o1", "category": "其他"},
        {"status_id": "o2"},  # category 缺省 other
    ]
    ctx = _ctx(
        transform=_transform(policy={"combo": "keep", "marks": "keep", "buff": "clear"}),
        buffs=buffs,
    )
    result = trigger_transform(ctx)
    assert result["ok"] is True
    remaining = [s["status_id"] for s in ctx["status_state"]["player"]]
    assert "b1" not in remaining
    assert "d1" in remaining
    assert "o1" in remaining
    assert "o2" in remaining


def test_apply_state_policy_direct_missing_segments() -> None:
    """apply_state_policy 直测：缺省三键 clear/keep/keep（§1.4 默认值）。"""
    snap: Dict[str, Any] = {}
    report = apply_state_policy(snap, {}, side="player", reason="transform")
    assert report["combo"] == "clear"
    assert report["marks"] == "keep"
    assert report["buff"] == "keep"
    assert snap["combo_state"]["player"]["count"] == 0  # 惰性建段
    assert "marks_state" not in snap  # keep 不建段
    assert "status_state" not in snap


def test_policy_unknown_values_fallback_defaults() -> None:
    """state_policy 枚举外值（V5 红拦归校验器）→ 引擎按缺省兜底（不抛异常）。"""
    ctx = _ctx(transform=_transform(policy={"combo": "shuffle", "marks": "x", "buff": "y"}))
    result = trigger_transform(ctx)
    assert result["ok"] is True
    report = _cast_dict(result["policy_report"])
    assert report["combo"] == "clear"   # 非法值 → 缺省 clear
    assert report["marks"] == "keep"
    assert report["buff"] == "keep"


# =====================================================================================
# 5. 技能位重排 SH-1~5（rearrange_slots）
# =====================================================================================


def test_rearrange_slots_sh1_3() -> None:
    """SH-1 主动位互换 + SH-3 derive_only 不占位：形态组重排快照。"""
    out = rearrange_slots(_snapshot(), _form_skills())
    slots = out["slots"]
    assert slots[0] == {"slot": SLOT_BASIC, "skill_id": "form_basic"}  # basic 固定第 1 位
    active_ids = [s["skill_id"] for s in slots if s["slot"] == SLOT_ACTIVE]
    assert active_ids == ["狂暴斩", "怒涛斩", "裂地击", "平息战意"]
    assert "大回旋·终" not in active_ids      # SH-3 derive_only 不占位
    assert out["active_order"] == active_ids
    # SH-2 被动/触发槽独立：本组无 passive；trigger 槽 = 战意沸腾
    assert out["passive"] == []
    assert out["trigger"] == [{"slot": SLOT_TRIGGER, "skill_id": "战意沸腾"}]


def test_rearrange_slots_empty_group_returns_copy() -> None:
    """组空/未注入 → 原快照副本（F1-4 防御兜底，不臆造重排）。"""
    out = rearrange_slots(_snapshot(), [])
    assert out["slots"] == _snapshot()["slots"]
    assert out["active_order"] == _snapshot()["active_order"]


def test_rearrange_slots_skips_invalid_entries() -> None:
    """无 id 条目 / 未知 type 条目防御性跳过（对齐 skill_slots 口径）。"""
    skills = [
        _skill("", "active"),       # 无 id → 跳过
        {"id": "weird", "type": "bogus"},  # 未知 type → 跳过
        _skill("only_basic", "basic"),
    ]
    out = rearrange_slots({}, skills)
    assert out["slots"] == [{"slot": SLOT_BASIC, "skill_id": "only_basic"}]


def test_rearrange_slots_no_basic_placeholder() -> None:
    """组内无 basic → basic 槽 None 占位（对齐 skill_slots P-3 兜底，不抛异常）。"""
    out = rearrange_slots({}, [_skill("a1"), _skill("a2")])
    assert out["slots"][0] == {"slot": SLOT_BASIC, "skill_id": None}
    assert out["active_order"] == ["a1", "a2"]


# =====================================================================================
# 6. 钩子注入形态（时序/参数验证）+ TransformEngine
# =====================================================================================


def test_hooks_receive_expected_arguments() -> None:
    """钩子注入：apply_status_hook 收 (ctx, transform, form) / reassess 收
    (ctx, transform, form) / rearrange 收 (ctx, transform, snapshot)。"""
    seen: Dict[str, Any] = {}
    ctx = _ctx()

    def apply_status(c: Mapping[str, Any], t: Mapping[str, Any], form: str) -> str:
        seen["status_form"] = form
        seen["status_skill"] = t.get("transform_skill")
        return FORM_STATUS_ID

    def reassess(c: Mapping[str, Any], t: Mapping[str, Any], form: str) -> List[str]:
        seen["reassess_form"] = form
        return ["chain_rage"]

    ctx["apply_status_hook"] = apply_status
    ctx["reassess_chains_hook"] = reassess
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert seen["status_form"] == FORM_ID
    assert seen["status_skill"] == TRIGGER_SKILL
    assert seen["reassess_form"] == FORM_ID
    assert result["chains"] == ("chain_rage",)


def test_rearrange_hook_injected_replaces_default() -> None:
    """rearrange_hook 注入覆盖缺省重排（SH-1~5 委托接线方自定义实现）。"""
    ctx = _ctx()

    def custom_rearrange(
        c: Mapping[str, Any], t: Mapping[str, Any], snapshot: Mapping[str, Any]
    ) -> Dict[str, Any]:
        return {"custom": True, "active_order": ["自定义位"]}

    ctx["rearrange_hook"] = custom_rearrange
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["slots_snapshot"] == {"custom": True, "active_order": ["自定义位"]}


def test_transform_engine_injection_and_audit() -> None:
    """TransformEngine 引擎注入：钩子挂 ctx（幂等不覆盖）+ audit 观察口。"""
    audits: List[str] = []
    resource_calls: List[bool] = []

    def resource_check(c: Mapping[str, Any], t: Mapping[str, Any]) -> Dict[str, Any]:
        resource_calls.append(True)
        return {"ok": True}

    eng = TransformEngine(
        resource_check_hook=resource_check,
        audit=audits.append,
    )
    ctx = _ctx()
    result = eng.trigger(ctx)
    assert result["ok"] is True
    assert resource_calls == [True]
    assert any("transform_f1: ok=True" in a for a in audits)
    # 幂等：构造器注入不覆盖 ctx 显式注入的 resolve_hook
    assert ctx["resolve_hook"] is not None
    ctx2 = _ctx()
    ctx2["resource_check_hook"] = lambda c, t: {"ok": False, "reason": "显式注入优先"}
    eng2 = TransformEngine(resource_check_hook=resource_check)
    result2 = eng2.trigger(ctx2)
    assert result2["ok"] is False
    assert result2["guard"] == "C2"


def test_transform_state_of_reads_ctx_and_persistent() -> None:
    """transform_state_of：ctx 段优先 / 存档兜底 / 缺省常态骨架。"""
    ctx = _ctx(transform_state={"form": FORM_ID, "remaining": 2})
    assert transform_state_of(ctx)["form"] == FORM_ID
    ctx2: Dict[str, Any] = {
        "player": {"persistent_state": {"transform_state": {"form": FORM_ID, "remaining": 1}}}
    }
    assert transform_state_of(ctx2)["form"] == FORM_ID
    assert transform_state_of({}) == empty_transform_state()


def test_trigger_commit_writes_ctx_segment() -> None:
    """触发成功后 ctx[TRANSFORM_STATE_KEY] 挂回（_ps_init 惰性挂回形态），
    后续 can_transform 立即读到 S3（C1 互斥生效，防二次触发）。"""
    ctx = _ctx()
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert ctx[TRANSFORM_STATE_KEY]["form"] == FORM_ID
    # 形态激活期再触发 → C1 拒绝（TC-17 状态机边界）
    again = trigger_transform(ctx)
    assert again["ok"] is False
    assert again["guard"] == "C1"
