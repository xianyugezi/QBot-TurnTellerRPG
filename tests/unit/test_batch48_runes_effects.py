"""批48 · 符文 43-C/D 单测：重伤治疗削减 + 层数型增益 + 2/3 阶战斗接线 + 3 合 1 端到端。

依据：`/root/deliverables/符文系统_实现口径.md` §〇 结论 7/8 + §三 3.1/3.2 + §五 43-C/43-D；
原案 `打造系统_原案_20260919.md` §9；`docs/深度打造_决策记录.md` H1/H2/H7。

覆盖：
  A. 重伤（治疗削减）：heal 计算处消费状态 `stat_modifier{stat: HEAL_TAKEN_STAT}` 聚合；
     未重伤不受影响；削减封顶（cap_boost，可配）；治疗归零不反向扣血；
  B. 层数型增益：`_aggregate_boost` 按 `stacks` 乘算（上限由状态 `max_stack` 包声明）；
     上限可配（改 max_stack / config）；
  C. 2 阶战斗接线：符文声明 effect + trigger（经 `active_rune_sockets` 读激活孔位）→
     战斗事件时点按侧执行（副手失活不触发）；
  D. 3 阶偏向性：按相性层主/副相性命中 → 数值放大（default 不命中不受影响）；
  E. 3 合 1 端到端：1→2→3 逐阶、禁跳级、越阶输入拒绝、失败原子性、总闸/synth_allowed 交互；
  F. 回归对拍：`_aggregate_boost` 修正后既有（非 stack）状态型增益逐字段一致。

纪律：测试只构造内存数据（不写任何真实内容包）；框架不得出现内容包业务名 →
       测试用匿名 id（r_*/s_*）；数值/上限全部由包声明（测试内声明）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping

from qbot_rpg.core.effects import (
    HEAL_TAKEN_STAT,
    DamageCtx,
    EffectRuntime,
    execute_action,
    status_stat_modifier_sum,
)

BP = "player"
BN = "enemy"


class _Def:
    """最小 Def 桩（镜像 frozen Def：id/name/raw，registry 直连测试）。"""

    def __init__(self, raw: Dict[str, Any]) -> None:
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def _status(sid: str, *, stacks_actions: List[Dict[str, Any]], frame: str = "stack",
            max_stack: int = 3, category: str = "harm") -> _Def:
    """包装一个状态定义（actions 由调用方声明——数值/上限全包声明）。"""
    return _Def({
        "id": sid, "name": sid, "class": "status", "category": category,
        "stack_frame": frame, "max_stack": max_stack,
        "duration": {"turns": 3, "charges": 0},
        "actions": list(stacks_actions),
    })


def _snap() -> Dict[str, Any]:
    def _c() -> Dict[str, Any]:
        return {"max_hp": 1000, "hp": 400, "max_mp": 100, "mp": 50, "atk": 100, "dfn": 50}
    return {
        BP: _c(), BN: _c(),
        "status_state": {BP: [], BN: []},
        "marks_state": {BP: [], BN: []},
        "resist_table": {BP: {}, BN: {}},
        "effect_triggers": {BP: {"per_turn": {}, "per_battle": {}},
                            BN: {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {BP: {}, BN: {}},
    }


def _ctx(snap: Mapping[str, Any], attacker: str = BP, target: str = BN) -> DamageCtx:
    return DamageCtx(raw_damage=0, attack_type="skill", attacker=attacker,
                     target=target, snapshot=snap, variables={"rng": _AlwaysZero()})


class _AlwaysZero:
    def random(self) -> float:
        return 0.0


GRIEVOUS = _status("s_grievous", stacks_actions=[
    {"type": "stat_modifier", "stat": HEAL_TAKEN_STAT, "value": -40}])


def _run_heal(snap: Mapping[str, Any], runtime: EffectRuntime,
              value: int = 100, target: str = "self") -> Any:
    return execute_action({"type": "heal", "value": value, "target": target},
                          _ctx(snap), runtime)


# ===========================================================================
# A. 重伤（治疗削减）—— heal 计算处消费，未重伤不受影响
# ===========================================================================
def test_heal_unaffected_without_grievous() -> None:
    """未重伤目标：治疗量原样（前后 hp 贴数值）。"""
    snap = _snap()
    rt = EffectRuntime(defs={GRIEVOUS.id: GRIEVOUS})
    res = _run_heal(snap, rt, value=100)
    assert res.ok is True
    assert snap[BP]["hp"] == 500, snap[BP]["hp"]        # 400 + 100
    heal_fx = [e for e in res.side_effects if e["type"] == "heal"]
    assert heal_fx and heal_fx[0]["value"] == 100


def test_grievous_reduces_heal_amount() -> None:
    """被重伤目标受到治疗 → 治疗量减少（贴前后数值：100 → 60，hp 400 → 460）。"""
    snap = _snap()
    rt = EffectRuntime(defs={GRIEVOUS.id: GRIEVOUS})
    assert rt.apply_status(GRIEVOUS.id, BP, source=BN).applied is True
    # 前置：目标确实带重伤
    assert rt.find_status(BP, GRIEVOUS.id) is not None
    res = _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 460, snap[BP]["hp"]        # 400 + 60（-40%）
    heal_fx = [e for e in res.side_effects if e["type"] == "heal"]
    assert heal_fx and heal_fx[0]["value"] == 60


def test_grievous_only_affects_its_bearer() -> None:
    """异常对照：重伤在玩家侧 → 敌方受治疗不受影响（按侧隔离）。"""
    snap = _snap()
    rt = EffectRuntime(defs={GRIEVOUS.id: GRIEVOUS})
    rt.apply_status(GRIEVOUS.id, BP, source=BN)
    _run_heal(snap, rt, value=100, target="enemy")
    assert snap[BN]["hp"] == 500, snap[BN]["hp"]        # 敌方满额
    assert snap[BP]["hp"] == 400                       # 玩家未受治疗，仍 400


def test_grievous_capped_no_negative_heal() -> None:
    """削减封顶（cap_boost=±100）且治疗不为负：-150% → 仍按 -100% 计（治疗 0）。"""
    snap = _snap()
    hard = _status("s_hard", stacks_actions=[
        {"type": "stat_modifier", "stat": HEAL_TAKEN_STAT, "value": -150}])
    rt = EffectRuntime(defs={hard.id: hard})
    rt.apply_status(hard.id, BP, source=BN)
    _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 400, snap[BP]["hp"]        # 0 治疗，不反向扣血


def test_heal_bonus_positive_modifier() -> None:
    """反向：正修正（受治疗增幅）同样经本通道 —— +50% → 治疗 150。"""
    snap = _snap()
    amp = _status("s_amp", stacks_actions=[
        {"type": "stat_modifier", "stat": HEAL_TAKEN_STAT, "value": 50}], category="buff")
    rt = EffectRuntime(defs={amp.id: amp})
    rt.apply_status(amp.id, BP, source=BP)
    _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 550, snap[BP]["hp"]


def test_heal_taken_sum_shares_single_collection_point() -> None:
    """唯一收口：`status_stat_modifier_sum` 直接给出聚合值；未知 stat / 空运行时 → 0。"""
    rt = EffectRuntime(defs={GRIEVOUS.id: GRIEVOUS})
    rt.apply_status(GRIEVOUS.id, BP, source=BN)
    assert status_stat_modifier_sum(rt, BP, HEAL_TAKEN_STAT) == -40.0
    assert status_stat_modifier_sum(rt, BN, HEAL_TAKEN_STAT) == 0.0
    assert status_stat_modifier_sum(rt, BP, "atk") == 0.0
    assert status_stat_modifier_sum(None, BP, HEAL_TAKEN_STAT) == 0.0


def test_heal_taken_str_percent_value() -> None:
    """值形态兼容：带 `%` 串按百分点解析（与 battle 原实现同口径）。"""
    snap = _snap()
    st = _status("s_str", stacks_actions=[
        {"type": "stat_modifier", "stat": HEAL_TAKEN_STAT, "value": "-25%"}])
    rt = EffectRuntime(defs={st.id: st})
    rt.apply_status(st.id, BP, source=BN)
    assert status_stat_modifier_sum(rt, BP, HEAL_TAKEN_STAT) == -25.0
    _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 475, snap[BP]["hp"]        # 400 + 75
