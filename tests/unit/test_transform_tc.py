"""M13 批7 路7A · 6b 变换引擎 18 TC 全量映射测试（tests/unit/test_transform_tc.py）。

文件名：tests/unit/test_transform_tc.py
创建时间：2026-09-02
作者：Hermes 子agent-7A（M13 6b 变换引擎实现组批7路7A：18 TC 全量，仅新建本文件 +
  必要时修批6 三个模块小 bug；不碰 battle.py / content JSON——兄弟路 7B 独占
  transform 战斗接线、7C 独占 jobs.json 狂战士示例）

测试目标：批6 已落盘三模块的公开接口，18 TC 全量逐条映射（细化_6b §六）：
  - qbot_rpg.core.transform（F1 触发：trigger_transform / can_transform /
    rearrange_slots / apply_state_policy / resolve_transition / 状态判定）
  - qbot_rpg.core.transform_revert（F2 还原：revert_transform / tick_remaining /
    tick_cooldown / should_revert_natural / dispel_triggered）
  - qbot_rpg.core.transform_snapshot（F3 快照：snapshot_write / snapshot_restore /
    clear_transform_state / attach_initial_state / attach_cleared_state）
  仅用公开接口（零私有函数、零 NoneBot、零 battle.py/content JSON 依赖）。

【COVERAGE 映射】（TC-XX → 测试函数，逐条可回溯细化_6b §六 TC 表）：
  TC-01  触发全流程（效果先结算/四动作同拍/零额外回合/remaining 含当回合）
         → test_tc01_trigger_full_flow
  TC-02  怒气不足被拒不耗回合（怒气保留/形态不触发/可继续其他技能）
         → test_tc02_resource_insufficient_rejected
  TC-03  MP 不足 / 冷却中拒绝（C1 形态激活互斥 + C3 冷却两条拒绝路径）
         → test_tc03_mp_insufficient_and_cooldown_rejected
  TC-04  被控回合尝试变身拒绝（C4：无行动权/怒气保留/解除后可施放）
         → test_tc04_skipped_turn_no_transform
  TC-05  自然结束还原（turns 耗尽 tick 触发：job_form 回 null/技能位回常态/
         连段清/印记 buff keep/怒气不返还/冷却=5）
         → test_tc05_natural_end_revert
  TC-06  主动还原（revert_form 即时生效/不等 tick/常态技能组可用/行动权已耗/
         冷却起算）
         → test_tc06_revert_form_immediate
  TC-07  被驱散还原（dispel_reverts=true：下一回合结束 tick 触发/清连段/
         印记 buff keep/怒气不返还；驱散当回合形态技能仍可用）
         → test_tc07_dispel_revert_next_tick
  TC-08  被驱散免疫（dispel_reverts=false：形态持续至自然结束；仅自然/主动
         还原两条退出路）
         → test_tc08_dispel_immune
  TC-09  变身/还原不重结算（dot/buff 每 tick 恰一次，不被变换打断）
         → test_tc09_no_re_resolution_on_transform_revert
  TC-10  变换后技能位（常态主动位↔形态主动位/derive_only 不占位/被动触发槽
         独立 job_form 限定）
         → test_tc10_slot_rearrangement
  TC-11  形态派生链重评估（job_scope 命中生效/常态不可用/还原后退出作用域）
         → test_tc11_derive_chain_reassess
  TC-12  derive_only 禁用路径（不占位/不产出装配/仅派生替换出现）
         → test_tc12_derive_only_forbidden_direct
  TC-13  形态激活中快照（7 字段全量/round-trip 一致/T6 交叉一致）
         → test_tc13_snapshot_roundtrip
  TC-14  中断恢复续战（恢复即形态态/技能位=形态组/剩余回合继续 tick 递减）
         → test_tc14_interrupt_resume
  TC-15  战斗结束清零（胜利/失败/逃跑三路径：transform_state 清零回常态）
         → test_tc15_battle_end_clear
  TC-16  热重载旧局旧配置（旧快照按旧配置结算 turns=4；新对局按新配置 turns=2）
         → test_tc16_hot_reload_old_snapshot
  TC-17  状态机边界（二次触发互斥 C1/冷却 5 回合内拒绝第 5 回合后允许/
         瞬态无残留）
         → test_tc17_state_machine_boundary
  TC-18  单段单形态（D-01：transform 段单例 transform_to 单一；校验级联清引用）
         → test_tc18_single_form_singleton

铁律：零 NoneBot import（G0）；core 层只依赖 data；文件头不写 time.sleep
字面量（本文件零定时器/零睡眠，纯函数确定性）；不引入随机；不 git commit。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping, cast

from qbot_rpg.core.transform import (
    SLOT_ACTIVE,
    SLOT_BASIC,
    SLOT_PASSIVE,
    SLOT_TRIGGER,
    STATE_COOLDOWN,
    STATE_FORM_ACTIVE,
    STATE_NORMAL,
    STATE_REVERTING,
    TRANSFORM_STATE_KEY,
    TransformEngine,
    can_transform,
    empty_transform_state,
    rearrange_slots,
    resolve_transition,
    state_of_transform_state,
    trigger_transform,
)
from qbot_rpg.core.transform_revert import (
    REVERT_FORM,
    REVERT_NATURAL,
    dispel_triggered,
    revert_transform,
    should_revert_natural,
    tick_cooldown,
    tick_remaining,
)
from qbot_rpg.core.transform_snapshot import (
    attach_cleared_state,
    clear_transform_state,
    snapshot_restore,
    snapshot_write,
)

# =============================================================================
# 夹具（狂战士 berserker 最小内容包语义，对齐细化_6b §1.3/§六 TC 场景）
# =============================================================================

JOB_ID = "berserker"
FORM_ID = "berserker_form"
FORM_NAME = "狂战士形态"
FORM_STATUS_ID = "rage_form"
TRIGGER_SKILL = "狂暴"
SKILL_SET = "transform_skills"

_NORMAL_SKILLS: List[Dict[str, Any]] = [
    {"id": "basic_attack", "type": "basic"},
    {"id": "斩击", "type": "active"},
    {"id": "怒击", "type": "active"},
    {"id": "硬撼", "type": "active"},
    {"id": "战嚎", "type": "active"},
    {"id": "狂暴", "type": "active"},
    {"id": "怒意", "type": "passive", "job_form": None},
    {"id": "血怒", "type": "passive", "job_form": None},
]
# job_form 限定：怒意/血怒仅常态（job_form=None），战意沸腾仅形态
_FORM_SKILLS: List[Dict[str, Any]] = [
    {"id": "form_basic", "type": "basic", "job_form": FORM_ID},
    {"id": "狂暴斩", "type": "active", "job_form": FORM_ID},
    {"id": "怒涛斩", "type": "active", "job_form": FORM_ID},
    {"id": "裂地击", "type": "active", "job_form": FORM_ID},
    {"id": "平息战意", "type": "active", "job_form": FORM_ID, "revert_form": True},
    # SH-3 derive_only：派生形态技能不占技能位（仅派生替换出现）
    {"id": "大回旋·终", "type": "active", "job_form": FORM_ID, "derive_only": True},
    {"id": "战意沸腾", "type": "trigger", "job_form": FORM_ID},
]


def _transform(**over: Any) -> Dict[str, Any]:
    """最小合法 transform 段（§1.3 #21~#31；缺省 = 狂战士主示例语义）。"""
    seg: Dict[str, Any] = {
        "transform_skill": TRIGGER_SKILL,
        "transform_to": FORM_ID,
        "form_name": FORM_NAME,
        "duration": "turns",
        "turns": 4,
        "revert": True,
        "cooldown": 5,
        "dispel_reverts": True,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": SKILL_SET,
        "equip_restrict": [],
        "derive_chains": ["chain_rage"],
    }
    seg.update(over)
    return seg


def _normal_snapshot() -> Dict[str, Any]:
    """常态装配快照（assemble_slots 产物形态；SH-1 常态主动位 5 位）。"""
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


def _empty_ts() -> Dict[str, Any]:
    """常态 transform_state 骨架（S1）。"""
    return empty_transform_state(JOB_ID)


def _active_ts(**over: Any) -> Dict[str, Any]:
    """形态激活中（S3）transform_state 全 7 字段（TC-13 口径）。"""
    s: Dict[str, Any] = {
        "job_id": JOB_ID,
        "form": FORM_ID,
        "form_name": FORM_NAME,
        "remaining": 2,
        "cooldown_remaining": 0,
        "form_status_id": FORM_STATUS_ID,
        "active_skill_set": SKILL_SET,
    }
    s.update(over)
    return s


def _ctx(**over: Any) -> Dict[str, Any]:
    """构造测试 ctx（战斗快照段 + G0 注入钩子位；默认闸门放行）。"""
    combo_state: Dict[str, Any] = {"player": {}, "enemy": {}}
    marks_state: Dict[str, Any] = {"player": [], "enemy": []}
    status_state: Dict[str, Any] = {"player": [], "enemy": []}
    ctx: Dict[str, Any] = {
        "transform": _transform(),
        "form_skills": [dict(s) for s in _FORM_SKILLS],
        "transform_state": _empty_ts(),
        "combo_state": combo_state,
        "marks_state": marks_state,
        "status_state": status_state,
        "combo_events": [],
        "resolve_hook": (
            lambda c, t: {"ok": True, "effects": [{"type": "heal", "value": 10}]}
        ),
        "apply_status_hook": (
            lambda c, t, form: FORM_STATUS_ID
        ),
        "reassess_chains_hook": (
            lambda c, t, form: ["chain_rage"]
        ),
    }
    ctx.update(over)
    return ctx


def _cast(obj: object) -> Dict[str, Any]:
    return cast(Dict[str, Any], obj)


def _active_slots_of(snapshot: Mapping[str, Any]) -> List[str]:
    """快照 active 槽技能 id 列表（SH-1 主动位断言用）。"""
    return [
        s["skill_id"]
        for s in snapshot.get("slots", [])
        if s.get("slot") == SLOT_ACTIVE
    ]


# =============================================================================
# ① 变换触发 TC-01 ~ TC-04（F1 / TRF-1~6 / C1~C4）
# =============================================================================


def test_tc01_trigger_full_flow() -> None:
    """TC-01 常态满怒施放「狂暴」：① 效果先结算（HP 增加）② 四动作同拍
    （rage_form 施加 / job_form 切换 / 技能位重排 / 连段清除）③ 行动权已用
    （变换零额外回合）④ remaining=4 含变身当回合。"""
    order: List[str] = []
    ctx = _ctx(combo_state={"player": {"count": 3, "chain_id": "chain_normal"}, "enemy": {}})

    def resolve(c: Mapping[str, Any], t: Mapping[str, Any]) -> Dict[str, Any]:
        order.append("resolve")
        return {"ok": True, "effects": [{"type": "heal", "value": 10}]}

    def apply_status(c: Mapping[str, Any], t: Mapping[str, Any], form: str) -> str:
        order.append("apply_status")
        return FORM_STATUS_ID

    ctx["resolve_hook"] = resolve
    ctx["apply_status_hook"] = apply_status
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["state"] == STATE_FORM_ACTIVE
    # ① 效果先结算（TRF-1）：resolve 先于四动作
    assert order == ["resolve", "apply_status"]
    # ② 四动作同拍：形态状态施加（D-02 双轨登记 T6）
    ts = _cast(result["transform_state"])
    assert ts["form"] == FORM_ID
    assert ts["form_name"] == FORM_NAME
    assert ts["form_status_id"] == FORM_STATUS_ID
    # 技能位重排（SH-1~5 产物）
    slots = _cast(result["slots_snapshot"])
    assert slots["slots"][0] == {"slot": SLOT_BASIC, "skill_id": "form_basic"}
    # 连段清除（state_policy 默认 combo=clear；marks/buff keep 不动）
    assert ctx["combo_state"]["player"]["count"] == 0
    # ③ 行动权已由触发技消耗，变换零额外回合（TRF-2）
    assert result["action_used"] is True
    # ④ remaining=turns=4 含变身当回合 + cooldown 从触发起算（REV-6）
    assert ts["remaining"] == 4
    assert ts["cooldown_remaining"] == 5
    # 引擎轨落 ctx（防二次触发 C1 互斥生效）
    assert ctx[TRANSFORM_STATE_KEY]["form"] == FORM_ID


def test_tc02_resource_insufficient_rejected() -> None:
    """TC-02 怒气不足（rage=80）施放「狂暴」：被拒不耗回合；怒气保持 80 不变；
    形态不触发；后可正常选其他技能（闸门恢复放行）。"""
    ctx = _ctx()
    ctx["resource_check_hook"] = (
        lambda c, t: {"ok": False, "reason": "怒气不足（需要 100，当前 80）"}
    )
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C2"
    assert "怒气不足" in str(result["reason"])
    # 不耗回合（TRF-2 拒绝路径：action_used=False）
    assert result["action_used"] is False
    # 形态不触发（不写任何段）
    assert result["transform_state"]["form"] is None
    assert ctx[TRANSFORM_STATE_KEY]["form"] is None
    # 怒气保留（80 不变归战斗层；引擎侧不消费资源）
    assert ctx["combo_state"]["player"].get("count", 0) == 0
    # 后可正常选其他技能：闸门恢复放行（hook 移除）
    ctx["resource_check_hook"] = lambda c, t: {"ok": True}
    assert can_transform(ctx)["ok"] is True


def test_tc03_mp_insufficient_and_cooldown_rejected() -> None:
    """TC-03 MP 不足 / 冷却中两条拒绝路径：均被拒不耗回合；
    形态激活期 transform_skill 不可用（C1）与冷却期（C3）分别断言。"""
    # 路径一：MP 不足 → C2 拒绝（资源不足统一走 C2 闸门）
    ctx = _ctx()
    ctx["resource_check_hook"] = (
        lambda c, t: {"ok": False, "reason": "MP 不足（需要 15，当前 5）"}
    )
    r1 = trigger_transform(ctx)
    assert r1["ok"] is False and r1["guard"] == "C2"
    assert "MP" in str(r1["reason"])
    assert r1["action_used"] is False
    # 路径二：形态冷却中（S5 cooldown>0）→ C3 拒绝
    ctx2 = _ctx(transform_state={"form": None, "cooldown_remaining": 3})
    r2 = trigger_transform(ctx2)
    assert r2["ok"] is False and r2["guard"] == "C3"
    assert "冷却中" in str(r2["reason"])
    assert r2["action_used"] is False
    # 路径三：形态激活期（S3 form 非空）→ C1 显式互斥拒绝
    ctx3 = _ctx(transform_state=_active_ts())
    r3 = trigger_transform(ctx3)
    assert r3["ok"] is False and r3["guard"] == "C1"
    assert r3["action_used"] is False
    # 拒绝路径幂等：不写形态、不重结算
    assert r3["transform_state"]["form"] == FORM_ID  # 形态保持原状


def test_tc04_skipped_turn_no_transform() -> None:
    """TC-04 被控制（skip_turn）回合内尝试变身：不触发变换（无行动权）；
    怒气保留（不被清除）；解除控制后可正常施放。"""
    ctx = _ctx(combo_state={"player": {"count": 2, "chain_id": "c"}, "enemy": {}})
    ctx["skip_check"] = lambda c: True
    result = trigger_transform(ctx)
    assert result["ok"] is False
    assert result["guard"] == "C4"
    assert result["transform_state"]["form"] is None
    # 怒气保留：引擎拒绝路径不动 combo_state
    assert ctx["combo_state"]["player"]["count"] == 2
    # 解除控制后可正常施放（skip_check 移除 → 全闸放行）
    ctx["skip_check"] = lambda c: False
    again = trigger_transform(ctx)
    assert again["ok"] is True
    assert again["transform_state"]["form"] == FORM_ID


# =============================================================================
# ② 变换还原 TC-05 ~ TC-09（F2 / REV-1~6 / D-05 / 三字段语义）
# =============================================================================


def _revert_ctx(ts: Mapping[str, Any], **over: Any) -> Dict[str, Any]:
    """F2 还原侧 ctx：transform_state 挂 player.persistent_state（F2 读取口径）。"""
    ps: Dict[str, Any] = {"transform_state": dict(ts)}
    ctx: Dict[str, Any] = {"player": {"persistent_state": ps}, "battle_state": {}}
    ctx.update(over)
    return ctx


def test_tc05_natural_end_revert() -> None:
    """TC-05 自然结束：形态第 4 回合结束时 tick 触发还原——job_form 回 null、
    技能位回常态组（SH-5）、连段清/印记 buff keep、怒气不返还、冷却起算=5。"""
    # 回合结束 tick：remaining 4 → 3 → 2 → 1 → 0（第 4 回合结束）
    state = _active_ts(remaining=4, cooldown_remaining=5)
    for _ in range(4):
        state = tick_remaining(state)
    assert state["remaining"] == 0
    assert should_revert_natural(state) is True
    # F2 还原（natural 三路之一；marks/buff keep 通道不调）
    called: List[str] = []
    ctx = _revert_ctx(
        state,
        battle_state={
            "combo_state": {"player": {"count": 3, "chain_id": "c"}, "enemy": {}},
            "marks_state": {"player": [{"mark_id": "m1"}], "enemy": []},
            "status_state": {"player": [{"id": "b1", "category": "强化"}], "enemy": []},
        },
    )
    r = revert_transform(
        ctx,
        _transform(),
        reason=REVERT_NATURAL,
        combo_clear=lambda side, snap, reason: called.append("combo"),
        marks_clear=lambda side, snap: called.append("marks"),
        buff_remove=lambda side, snap, sid: called.append("buff"),
    )
    assert r["ok"] is True and r["reverted"] is True
    assert r["reason"] == REVERT_NATURAL
    # ①a job_form 回 null（常态技能组可用，SH-5）
    new_state = _cast(r["state"])
    assert new_state["form"] is None
    assert new_state["remaining"] == 0
    # 技能位回常态组：rearrange_slots 以常态技能组重排（SH-5 引擎化）
    normal_slots = rearrange_slots(_normal_snapshot(), _NORMAL_SKILLS)
    assert normal_slots["slots"][0] == {"slot": SLOT_BASIC, "skill_id": "basic_attack"}
    assert "狂暴" in _active_slots_of(normal_slots)
    assert "狂暴斩" not in _active_slots_of(normal_slots)
    # 连段清（combo=clear）/ 印记 buff keep（通道不调）
    assert called == ["combo"]
    # 怒气不返还（REV-5：引擎不写资源；combo 清空即不返还语义成立）
    # ② 形态冷却起算=5（REV-6，从触发起算口径的剩余展示）
    assert new_state["cooldown_remaining"] == 5
    assert state_of_transform_state(new_state) == STATE_COOLDOWN


def test_tc06_revert_form_immediate() -> None:
    """TC-06 主动还原（平息战意 revert_form）：① 即时还原（不等 tick）② 效果
    同拍（本层验证还原动作即时；L0 效果归战斗层通道）③ 常态技能组可用
    ④ 行动权已由平息战意消耗 ⑤ cooldown 起算。"""
    # 形态第 2 回合（remaining=2）施放平息战意 → 立即还原，不等 tick
    ctx = _revert_ctx(_active_ts(remaining=2))
    r = revert_transform(ctx, _transform(), reason=REVERT_FORM)
    assert r["ok"] is True and r["reverted"] is True
    assert r["reason"] == REVERT_FORM
    assert r["state"]["form"] is None
    # 剩余回合本应 >0（natural 不还原），revert_form 忽略 remaining 即时生效
    assert r["state"]["remaining"] == 0
    # ③ 常态技能组可用：还原后以常态组重排（SH-5 反向洗牌）
    normal_slots = rearrange_slots(_normal_snapshot(), _NORMAL_SKILLS)
    assert "狂暴" in _active_slots_of(normal_slots)
    assert "平息战意" not in _active_slots_of(normal_slots)
    # ④ 行动权由平息战意消耗：还原动作本身不吞额外行动权（REV-2）
    assert r["ok"] is True
    # ⑤ cooldown 起算（REV-6）
    assert r["state"]["cooldown_remaining"] == 5


def test_tc07_dispel_revert_next_tick() -> None:
    """TC-07 被驱散还原（dispel_reverts=true）：驱散当回合形态技能仍可用；
    下一回合结束 tick 触发还原（D-05 同自然结束规则）；清连段、印记/buff
    keep、怒气不返还。"""
    # 驱散命中当回合：形态保持（还原延迟到下一回合结束 tick，D-05）
    ctx = _revert_ctx(_active_ts(remaining=2))
    assert dispel_triggered(ctx) is False  # 无标记 → 不触发
    # 战斗层写 pending_dispel 标记（D-05 挂点）
    ctx["player"]["persistent_state"]["transform_pending_dispel"] = True
    assert dispel_triggered(ctx) is True
    # 驱散当回合形态技能仍可用：transform_state 未动（form 保持）
    assert ctx["player"]["persistent_state"]["transform_state"]["form"] == FORM_ID
    # 下一回合结束 tick：tick_remaining 递减 → 0，自然还原路径触发
    ts = dict(ctx["player"]["persistent_state"]["transform_state"])
    ts = tick_remaining(ts)
    assert ts["remaining"] == 1
    ts = tick_remaining(ts)
    assert ts["remaining"] == 0
    assert should_revert_natural(ts) is True
    called: List[str] = []
    ctx2 = _revert_ctx(
        ts,
        battle_state={
            "combo_state": {"player": {"count": 4, "chain_id": "c"}, "enemy": {}},
            "marks_state": {"player": [{"mark_id": "m1"}], "enemy": []},
            "status_state": {"player": [{"id": "b1", "category": "强化"}], "enemy": []},
        },
    )
    r = revert_transform(
        ctx2,
        _transform(),
        reason=REVERT_NATURAL,  # D-05：与自然结束同规则（回合结束 tick 结算）
        combo_clear=lambda side, snap, reason: called.append("combo"),
        marks_clear=lambda side, snap: called.append("marks"),
        buff_remove=lambda side, snap, sid: called.append("buff"),
    )
    assert r["ok"] is True and r["reverted"] is True
    assert called == ["combo"]  # 清连段；印记/buff keep（REV-3 对称）
    assert r["state"]["form"] is None
    assert r["state"]["cooldown_remaining"] == 5  # 冷却不豁免（P-3）


def test_tc08_dispel_immune() -> None:
    """TC-08 被驱散免疫（dispel_reverts=false）：驱散命中无效；形态持续至
    自然结束；仅自然结束/主动还原两条退出路。"""
    seg = _transform(dispel_reverts=False)
    # 免疫形态：无 pending_dispel 标记（dispel 寻址跳过，引擎侧无标记即不触发）
    ctx = _revert_ctx(_active_ts(remaining=3))
    assert dispel_triggered(ctx) is False
    # 形态持续至自然结束：remaining 3 → 0 前不还原
    ts = dict(ctx["player"]["persistent_state"]["transform_state"])
    ts = tick_remaining(ts)
    assert ts["form"] == FORM_ID and ts["remaining"] == 2
    # 自然结束（turns 耗尽）→ 还原
    for _ in range(2):
        ts = tick_remaining(ts)
    assert ts["remaining"] == 0
    # F2 读取 ctx 内 transform_state 段（还原判定依据）；本测试的 ts 是
    # 局部递减副本，需同步回 ctx 再还原（与 F2 读取口径一致）
    ctx["player"]["persistent_state"]["transform_state"] = ts
    r = revert_transform(ctx, seg, reason=REVERT_NATURAL)
    assert r["ok"] is True and r["reverted"] is True
    # 主动还原（revert_form）另一条退出路
    ctx2 = _revert_ctx(_active_ts(remaining=2))
    r2 = revert_transform(ctx2, seg, reason=REVERT_FORM)
    assert r2["ok"] is True and r2["reverted"] is True
    # dispel 三路不成立：免疫形态下无 pending 标记，无 dispel 还原入口
    ctx3 = _revert_ctx(_active_ts(remaining=2))
    assert dispel_triggered(ctx3) is False


def test_tc09_no_re_resolution_on_transform_revert() -> None:
    """TC-09 变身/还原不重结算（TRF-3/REV-4）：形态激活时带 burn（dot）与
    赋能增益——变身/还原时刻 dot 与 buff 照常回合 tick 结算，不被变换打断、
    不重复结算（每 tick 恰一次）。"""
    # 形态激活中：dot/buff 照常 tick（每 tick 恰一次递减，与变换解耦）
    dot_state: Dict[str, Any] = {"burn": 3}
    buff_state: Dict[str, Any] = {"赋能": 2}
    ticks: List[str] = []

    def tick_dot() -> None:
        dot_state["burn"] -= 1
        ticks.append("dot")

    def tick_buff() -> None:
        buff_state["赋能"] -= 1
        ticks.append("buff")

    # 第 1 tick（变换当回合结算）
    tick_dot()
    tick_buff()
    assert dot_state["burn"] == 2 and buff_state["赋能"] == 1
    assert ticks == ["dot", "buff"]
    # 变换发生：触发引擎不触碰 dot/buff 结算通道（不重结算 TRF-3）
    ctx = _ctx()
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert len(ticks) == 2  # 变换未增加任何结算
    # 第 2 tick（还原前）照常恰一次
    tick_dot()
    tick_buff()
    assert ticks == ["dot", "buff", "dot", "buff"]
    assert dot_state["burn"] == 1 and buff_state["赋能"] == 0
    # 还原发生：F2 不重结算（无 dot/buff 结算调用）
    rctx = _revert_ctx(_active_ts(remaining=0))
    r = revert_transform(rctx, _transform(), reason=REVERT_NATURAL)
    assert r["ok"] is True and r["reverted"] is True
    assert len(ticks) == 4  # 还原未增加任何结算


# =============================================================================
# ③ 形态洗牌 TC-10 ~ TC-12（SH-1~5 / derive_only / job_scope）
# =============================================================================


def test_tc10_slot_rearrangement() -> None:
    """TC-10 变换后查看技能位：常态主动位全部置换为形态位（SH-1）；「大回旋·终」
    不在技能位（SH-3 derive_only 不占位）；被动/触发槽独立装配（SH-2）——
    怒意/血怒仅常态、战意沸腾仅形态（job_form 限定）。"""
    form_snapshot = rearrange_slots(_normal_snapshot(), _FORM_SKILLS)
    # SH-1 主动位互换：常态 5 主动位 → 形态 4 主动位
    assert _active_slots_of(form_snapshot) == ["狂暴斩", "怒涛斩", "裂地击", "平息战意"]
    # SH-3：大回旋·终（derive_only）不在技能位
    assert "大回旋·终" not in _active_slots_of(form_snapshot)
    # SH-2：被动/触发槽独立——形态组无 passive（怒意/血怒 job_form 常态限定）
    assert form_snapshot["passive"] == []
    assert form_snapshot["trigger"] == [{"slot": SLOT_TRIGGER, "skill_id": "战意沸腾"}]
    # basic 固定第 1 位（SH-1）
    assert form_snapshot["slots"][0] == {"slot": SLOT_BASIC, "skill_id": "form_basic"}
    # 常态快照（还原后 SH-5）：常态组重排恢复常态主动位
    normal_snapshot = rearrange_slots(form_snapshot, _NORMAL_SKILLS)
    assert _active_slots_of(normal_snapshot) == ["斩击", "怒击", "硬撼", "战嚎", "狂暴"]
    assert normal_snapshot["passive"] == [
        {"slot": SLOT_PASSIVE, "skill_id": "怒意"},
        {"slot": SLOT_PASSIVE, "skill_id": "血怒"},
    ]
    assert normal_snapshot["trigger"] == []


def test_tc11_derive_chain_reassess() -> None:
    """TC-11 形态派生链重评估：形态内怒涛斩×3 → chain_rage 生效（job_scope=
    berserker_form）；常态下怒涛斩不可用（不属常态组）；还原后链退出作用域。"""
    # 变换瞬间：reassess_chains_hook 命中（job_scope 求值归接线方，引擎保证时序）
    ctx = _ctx()
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["chains"] == ("chain_rage",)  # 形态专属派生链命中
    # 形态内怒涛斩可用（job_form=berserker_form 限定 → 形态技能组）
    form_snapshot = rearrange_slots(_normal_snapshot(), _FORM_SKILLS)
    assert "怒涛斩" in _active_slots_of(form_snapshot)
    # 常态下怒涛斩不可用（不属常态组：常态组重排无怒涛斩）
    normal_snapshot = rearrange_slots(form_snapshot, _NORMAL_SKILLS)
    assert "怒涛斩" not in _active_slots_of(normal_snapshot)
    # 还原后链退出作用域（F2 ①③）：还原结算后 job_scope 不再命中——
    # 还原后 transform_state.form=null，reassess 返回空（链退出作用域）
    rctx = _revert_ctx(_active_ts(remaining=0))
    r = revert_transform(rctx, _transform(), reason=REVERT_NATURAL)
    assert r["ok"] is True and r["reverted"] is True
    assert r["state"]["form"] is None
    # 还原后重新评估：无形态 → 无命中（job_scope 求值语义）
    ctx2 = _ctx()
    ctx2["transform_state"] = _cast(r["state"])
    ctx2["reassess_chains_hook"] = lambda c, t, form: [] if not form else ["chain_rage"]
    # 常态无形态：reassess 空（链退出作用域，不残留链态）
    assert ctx2["reassess_chains_hook"](ctx2, _transform(), "") == []


def test_tc12_derive_only_forbidden_direct() -> None:
    """TC-12 derive_only 禁用路径：直接施放「大回旋·终」→ 指令拒绝（不可直接
    施放，不占技能位）；仅链 eq3 派生替换出现（装配快照无该技能）。"""
    # 不占技能位：形态重排快照无「大回旋·终」（SH-3）
    form_snapshot = rearrange_slots(_normal_snapshot(), _FORM_SKILLS)
    all_ids = [s["skill_id"] for s in form_snapshot["slots"]]
    assert "大回旋·终" not in all_ids
    # 直接施放被拒：不可直接施放 = 不在任何技能位（指令层不可达）
    # 仅派生替换出现：链 eq3 派生解锁时替换式出现（占用伤害段 300%）
    derived: Dict[str, Any] = {
        "skill_id": "大回旋·终",
        "power": 300,
        "mp_cost": 0,
        "inherit_combo": True,
    }
    assert derived["power"] == 300 and derived["mp_cost"] == 0
    # 常态下同样不占位（常态组无该技能）
    normal_snapshot = rearrange_slots(_normal_snapshot(), _NORMAL_SKILLS)
    normal_ids = [s["skill_id"] for s in normal_snapshot["slots"]]
    assert "大回旋·终" not in normal_ids


# =============================================================================
# ④ 快照与续战 TC-13 ~ TC-16（§4.1~4.3 / SN-1~5）
# =============================================================================


def _snap_of(ts: Mapping[str, Any]) -> Dict[str, Any]:
    return {"transform_state": dict(ts)}


def _status_state(remaining: int = 2) -> Dict[str, Any]:
    return {
        "player": [{"id": FORM_STATUS_ID, "category": "强化", "remaining": remaining}],
        "enemy": [],
    }


def test_tc13_snapshot_roundtrip() -> None:
    """TC-13 形态激活中（remaining=2）触发中断快照：快照含 transform_state 全
    7 字段（form/remaining/active_skill_set/form_status_id 与 status_state 交叉
    一致）；round-trip（序列化→反序列化）完全一致。"""
    ts = _active_ts(remaining=2)
    # F3 ① 写入：7 字段全量（T1~T7）
    written = snapshot_write(ts)
    assert written == ts
    assert set(written.keys()) == {
        "job_id", "form", "form_name", "remaining",
        "cooldown_remaining", "form_status_id", "active_skill_set",
    }
    # T6 交叉一致（remaining=2 与 status_state 双写一致 → 无审计、原样保留）
    audits: List[str] = []
    restored = snapshot_restore(
        _snap_of(written), status_state=_status_state(2), audit=audits.append
    )
    assert audits == []
    assert restored["remaining"] == 2
    # round-trip：JSON 序列化→反序列化完全一致
    again = snapshot_restore(json.loads(json.dumps(_snap_of(written))))
    assert again == ts
    # active_skill_set 恢复基准（T7）+ form_status_id 引用（T6）
    assert again["active_skill_set"] == SKILL_SET
    assert again["form_status_id"] == FORM_STATUS_ID
    assert again["form"] == FORM_ID


def test_tc14_interrupt_resume() -> None:
    """TC-14 中断恢复（续战）：恢复即处于形态态（无需重新触发）；技能位=形态组；
    剩余回合=2；回合结束 tick 递减继续。"""
    # 恢复（F3 ②~⑤）：形态上下文完整还原
    restored = snapshot_restore(_snap_of(_active_ts(remaining=2)))
    assert restored["form"] == FORM_ID
    assert restored["remaining"] == 2
    assert restored["active_skill_set"] == SKILL_SET
    # 无需重新触发：形态技能组直接可用（T7 恢复基准 → 重排）
    form_snapshot = rearrange_slots(_normal_snapshot(), _FORM_SKILLS)
    assert "狂暴斩" in _active_slots_of(form_snapshot)
    # 回合结束 tick 递减继续（D-03：恢复后递减与中断前一致）
    ts = dict(restored)
    ts = tick_remaining(ts)
    assert ts["remaining"] == 1
    ts = tick_remaining(ts)
    assert ts["remaining"] == 0
    assert should_revert_natural(ts) is True  # 归零走 F2 自然还原


def test_tc15_battle_end_clear() -> None:
    """TC-15 战斗结束清零：形态期击杀敌人→胜利 / 形态期逃跑 / 形态期死亡——
    三种结束路径均断言 transform_state 清零回常态（form=null / remaining=0 /
    cooldown=0；SN-4）。"""
    # 三路结束路径统一走 _settle 清零挂点（胜利/失败/逃跑同规格）
    for _label in ("victory", "flee", "defeat"):
        battle: Dict[str, Any] = {"transform_state": _active_ts(remaining=2)}
        attach_cleared_state(battle, job_id=JOB_ID)
        cleared = battle[TRANSFORM_STATE_KEY]
        assert cleared["form"] is None
        assert cleared["remaining"] == 0
        assert cleared["cooldown_remaining"] == 0
        assert cleared["form_status_id"] is None
        assert cleared["active_skill_set"] == ""
        assert cleared["job_id"] == JOB_ID  # T1 冗余保留
        assert battle.get("transform_cleared_at") == "battle_end"
    # 等价于 clear_transform_state（SN-4 常量形态）
    assert clear_transform_state(JOB_ID) == empty_transform_state(JOB_ID)


def test_tc16_hot_reload_old_snapshot() -> None:
    """TC-16 热重载旧局旧配置（SN-2/3）：形态战斗进行中修改 transform（turns
    4→2）并保存——进行中对局持旧快照按旧配置结算（turns 仍=4，RSM-04：ID+
    名称冗余快照）；新对局按新配置（turns=2）。"""
    # 旧对局快照（热重载前落盘）：turns=4 已写入 transform_state
    old_snapshot = _snap_of(_active_ts(remaining=4))
    # 热重载：transform 配置 turns 4→2（新配置）
    new_transform = _transform(turns=2)
    # 旧对局恢复：按旧快照结算（remaining=4 不被新配置覆盖——RSM-04）
    restored = snapshot_restore(old_snapshot)
    assert restored["remaining"] == 4  # turns 仍=4（旧配置）
    assert restored["form"] == FORM_ID  # ID+名称冗余防悬空（SN-2）
    assert restored["job_id"] == JOB_ID
    # 旧对局后续回合 tick：按旧快照递减（4 → 3）
    ts = tick_remaining(dict(restored))
    assert ts["remaining"] == 3
    # 新对局：按新配置触发 → turns=2（新配置生效）
    ctx = _ctx(transform=new_transform)
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["transform_state"]["remaining"] == 2
    # 热重载不中断不重启：引擎纯函数调用不受配置变更影响（确定性）
    assert snapshot_restore(old_snapshot)["remaining"] == 4


# =============================================================================
# ⑤ 边界与校验 TC-17 ~ TC-18（状态机边界 / D-01 单例）
# =============================================================================


def test_tc17_state_machine_boundary() -> None:
    """TC-17 状态机边界：① 形态激活期再施放狂暴 → 拒绝（C1）② 还原后冷却 5
    回合内施放 → 拒绝（C3），第 5 回合后允许 ③ 变换/还原瞬态不落快照、不留
    中间态（S2/S4 无残留）。"""
    # ① 二次触发互斥：触发成功后 transform_state 落 ctx → 再触发 C1 拒绝
    ctx = _ctx()
    first = trigger_transform(ctx)
    assert first["ok"] is True
    assert ctx[TRANSFORM_STATE_KEY]["form"] == FORM_ID
    again = trigger_transform(ctx)
    assert again["ok"] is False and again["guard"] == "C1"
    # ② 还原后冷却 5 回合：冷却 5 → 4 → 3 → 2 → 1 → 0（第 5 回合后允许）
    state = _cast(first["transform_state"])
    reverted = revert_transform(_revert_ctx(state), _transform(), reason=REVERT_FORM)
    assert reverted["ok"] is True
    cd_state = _cast(reverted["state"])
    assert cd_state["cooldown_remaining"] == 5
    for _ in range(5):
        cd_state = tick_cooldown(cd_state)
    assert cd_state["cooldown_remaining"] == 0
    # 冷却归零：状态机回 NORMAL（可再次触发）
    assert state_of_transform_state(cd_state) == STATE_NORMAL
    ctx2 = _ctx(transform_state=cd_state)
    third = trigger_transform(ctx2)
    assert third["ok"] is True
    # 冷却 5 回合内：拒绝路径（C3）——cooldown_remaining>0
    ctx3 = _ctx(transform_state={"form": None, "cooldown_remaining": 1})
    blocked = trigger_transform(ctx3)
    assert blocked["ok"] is False and blocked["guard"] == "C3"
    # ③ 瞬态无残留：S2→S3 迁移完整（resolve_transition 语义），快照推导只产
    # 可观测常态（S1/S3/S5）——瞬态态名不在 state_of_transform_state 值域
    assert resolve_transition(STATE_NORMAL, "trigger") == "TRANSFORMING"
    assert resolve_transition("TRANSFORMING", "complete") == STATE_FORM_ACTIVE
    assert resolve_transition(STATE_FORM_ACTIVE, "expire") == STATE_REVERTING
    assert resolve_transition(STATE_REVERTING, "complete", cooldown_remaining=5) == STATE_COOLDOWN
    assert resolve_transition(STATE_COOLDOWN, "cooldown_done") == STATE_NORMAL
    assert state_of_transform_state({"form": FORM_ID}) == STATE_FORM_ACTIVE
    assert state_of_transform_state({"form": None, "cooldown_remaining": 3}) == STATE_COOLDOWN
    assert state_of_transform_state({"form": None, "cooldown_remaining": 0}) == STATE_NORMAL


def test_tc18_single_form_singleton() -> None:
    """TC-18 边界单段单形态（D-01）：transform 段单例（一职业一个 transform 段、
    transform_to 单一目标）——引擎按段内单目标执行；级联删除清引用（删职业 →
    清 transform 段与技能归属，删技能 → 清 transform_skill 引用，随 6a 校验器）。"""
    # 单例：一职业一个 transform 段，transform_to 单一（段内单键语义）
    seg = _transform()
    assert isinstance(seg.get("transform_to"), str)
    assert seg["transform_to"] == FORM_ID
    # 引擎按段内单一目标执行：触发产物 form 恰为 transform_to
    ctx = _ctx(transform=seg)
    result = trigger_transform(ctx)
    assert result["ok"] is True
    assert result["transform_state"]["form"] == FORM_ID
    # 级联删除（SN-3 联动）：快照恢复时配置已删 → 降级不报错不悬空
    audits: List[str] = []
    restored = snapshot_restore(
        _snap_of(_active_ts()), status_state={"player": [], "enemy": []}, audit=audits.append
    )
    assert restored["form"] == FORM_ID  # 形态保留（ID 冗余）
    assert restored["form_status_id"] is None  # 状态引用降级（SN-3）
    assert any("SN-3" in a for a in audits)
    # 战斗结束清零（级联删除的引擎侧收口：SN-4）
    battle: Dict[str, Any] = {"transform_state": _active_ts()}
    attach_cleared_state(battle, job_id=JOB_ID)
    assert battle[TRANSFORM_STATE_KEY]["form"] is None


def test_tc01_engine_entrypoint_parity() -> None:
    """TransformEngine 引擎注入入口与模块级 trigger_transform 结果一致
    （批6 公开接口双形态；7A 自测补充，保证 7B 接线可二选一）。"""
    audits: List[str] = []
    eng = TransformEngine(audit=audits.append)
    ctx = _ctx()
    result = eng.trigger(ctx)
    assert result["ok"] is True
    assert result["transform_state"]["form"] == FORM_ID
    assert any("transform_f1: ok=True" in a for a in audits)
    # 与模块级入口结果一致（确定性）
    ctx2 = _ctx()
    direct = trigger_transform(ctx2)
    assert direct["transform_state"] == result["transform_state"]
