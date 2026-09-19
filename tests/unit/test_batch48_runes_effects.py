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


# ===========================================================================
# B. 层数型增益（每次攻击叠层 → 按层上升 → 达上限不再增；上限包声明/可配）
# ===========================================================================
def _engine_with(defs: Mapping[str, Any], instances: List[Dict[str, Any]],
                 side: str = BP) -> Any:
    """最小 BattleEngine（只种 status_state 块）——验证战斗侧 `_aggregate_boost` 消费。"""
    from qbot_rpg.core.battle import BattleEngine

    eng = BattleEngine(defs=dict(defs))
    eng._snap = {"status_state": {BP: [], BN: []}}  # noqa: SLF001 —— 单测直种快照块
    if side == BP:
        eng._snap["status_state"][BP] = list(instances)
    else:
        eng._snap["status_state"][BN] = list(instances)
    return eng


def _legacy_sum(rt: EffectRuntime, side: str, stat: str) -> float:
    """批48 修正**前**的聚合算法逐字复制（回归对拍基准；来源 battle._aggregate_boost）。"""
    agg = 0.0
    for inst in rt.status_instances(side):
        raw = rt._resolver(str(inst.get("status_id", "")), "status")  # noqa: SLF001
        raw = raw.raw if hasattr(raw, "raw") else (raw or {})
        for a in (raw.get("actions") or []):
            if not isinstance(a, dict):
                continue
            if a.get("type") == "stat_modifier" and a.get("stat") == stat:
                v = a.get("value")
                if isinstance(v, str) and v.strip().endswith("%"):
                    try:
                        agg += float(v.strip().rstrip("%"))
                    except ValueError:
                        pass
                elif isinstance(v, (int, float)) and not isinstance(v, bool):
                    agg += float(v)
    return agg


STACK_ATK = _status("s_atk_stack", stacks_actions=[
    {"type": "stat_modifier", "stat": "atk", "value": 5}], max_stack=4, category="buff")


def _per_attack(rt: EffectRuntime, sid: str, times: int, side: str = BP) -> None:
    """模拟「每次攻击各施加一次」：S5 同来源只保留一个 → 逐次用不同来源让 S3 叠层。

    （符文接线侧由 `source=侧#行动序号` 自动区分，见 C 组；此处直接区分以单测引擎层。）
    """
    for i in range(times):
        rt.apply_status(sid, side, source=f"atk{i}", force=True)


def test_stack_boost_rises_per_attack_then_caps() -> None:
    """每次攻击叠加：逐次 apply_status → 加成 5/10/15/20，达 max_stack=4 后不再增。"""
    rt = EffectRuntime(defs={STACK_ATK.id: STACK_ATK})
    seen_stacks: List[int] = []
    seen_boost: List[float] = []
    for i in range(6):
        rt.apply_status(STACK_ATK.id, BP, source=f"atk{i}", force=True)
        inst = rt.find_status(BP, STACK_ATK.id)
        assert inst is not None
        seen_stacks.append(int(inst["stacks"]))
        eng = _engine_with({STACK_ATK.id: STACK_ATK}, [dict(inst)])
        seen_boost.append(eng._aggregate_boost(BP, "atk"))  # noqa: SLF001
    assert seen_stacks == [1, 2, 3, 4, 4, 4], seen_stacks
    assert seen_boost == [5.0, 10.0, 15.0, 20.0, 20.0, 20.0], seen_boost


def test_stack_cap_is_pack_declared() -> None:
    """上限包声明可配：同动作值、max_stack 3 vs 5 → 平台期不同（15 vs 25）。"""
    def _plateau(max_stack: int) -> float:
        st = _status(f"s_cap{max_stack}", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": 5}],
            max_stack=max_stack, category="buff")
        rt = EffectRuntime(defs={st.id: st})
        _per_attack(rt, st.id, 8)
        inst = rt.find_status(BP, st.id)
        assert inst is not None
        return _engine_with({st.id: st}, [dict(inst)])._aggregate_boost(BP, "atk")  # noqa: SLF001
    assert _plateau(3) == 15.0
    assert _plateau(5) == 25.0


def test_stack_cap_via_engine_config_default_max() -> None:
    """未声明 max_stack 时回落引擎 config（stack_default_max）——同样可配。"""
    st = _Def({"id": "s_cfg", "name": "s_cfg", "class": "status", "category": "buff",
               "stack_frame": "stack", "duration": {"turns": 3, "charges": 0},
               "actions": [{"type": "stat_modifier", "stat": "atk", "value": 5}]})
    rt = EffectRuntime(defs={st.id: st}, config={"stack_default_max": 2})
    _per_attack(rt, st.id, 5)
    inst = rt.find_status(BP, st.id)
    assert inst is not None and int(inst["stacks"]) == 2
    assert _engine_with({st.id: st}, [dict(inst)])._aggregate_boost(BP, "atk") == 10.0  # noqa: SLF001


def test_stack_boost_still_capped_by_s6() -> None:
    """层数总值超 S6 单属性上限（cap_boost=±100 可配）→ 封顶 100（层数上限之外的第二道闸）。"""
    st = _status("s_big", stacks_actions=[
        {"type": "stat_modifier", "stat": "atk", "value": 40}], max_stack=10, category="buff")
    rt = EffectRuntime(defs={st.id: st})
    _per_attack(rt, st.id, 5)
    inst = rt.find_status(BP, st.id)
    assert inst is not None and int(inst["stacks"]) == 5      # 5×40=200 原始
    assert status_stat_modifier_sum(rt, BP, "atk") == 200.0
    assert _engine_with({st.id: st}, [dict(inst)])._aggregate_boost(BP, "atk") == 100.0  # noqa: SLF001


# ===========================================================================
# F. 回归对拍：修正后既有（stacks==1）状态型增益路径逐字段一致
# ===========================================================================
def _legacy_capped(rt: EffectRuntime, side: str, stat: str) -> float:
    """批48 修正前 battle._aggregate_boost 全量（含 S6/S7 封顶）逐字复制。"""
    agg = _legacy_sum(rt, side, stat)
    return rt.cap_combined(rt.cap_boost(agg))


def test_legacy_paths_field_by_field_identical() -> None:
    """对拍矩阵：非 stack 框架（stacks 恒 1）各值形态 → 新聚合与批48 前逐字段一致。"""
    cases: List[tuple] = [
        # (状态定义, 期望新聚合, 期望含封顶)
        (_status("s_single", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": 12}], frame="single", max_stack=1),
         12.0, 12.0),
        (_status("s_single_str", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": "25%"}], frame="single", max_stack=1),
         25.0, 25.0),
        (_status("s_single_neg", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": -30}], frame="single", max_stack=1),
         -30.0, -30.0),
        (_status("s_other_stat", stacks_actions=[
            {"type": "stat_modifier", "stat": "dfn", "value": 99}], frame="single", max_stack=1),
         0.0, 0.0),
        (_status("s_dual", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": 7}], frame="dual", max_stack=2),
         7.0, 7.0),
        (_status("s_level", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": 9}],
            frame="level_based", max_stack=3),
         9.0, 9.0),
        (_status("s_bool_value", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": True}], frame="single", max_stack=1),
         0.0, 0.0),
        (_status("s_over_cap", stacks_actions=[
            {"type": "stat_modifier", "stat": "atk", "value": 130}], frame="single", max_stack=1),
         130.0, 100.0),
    ]
    for sdef, want_raw, want_capped in cases:
        rt = EffectRuntime(defs={sdef.id: sdef})
        rt.apply_status(sdef.id, BP, source=BN, force=True)
        inst = rt.find_status(BP, sdef.id)
        assert inst is not None
        # 非 stack 框架 → stacks 恒 1（对拍前提）
        assert int(inst.get("stacks", 1)) == 1, (sdef.id, inst)
        assert status_stat_modifier_sum(rt, BP, "atk") == want_raw, sdef.id
        assert status_stat_modifier_sum(rt, BP, "atk") == _legacy_sum(rt, BP, "atk"), sdef.id
        eng = _engine_with({sdef.id: sdef}, [dict(inst)])
        assert eng._aggregate_boost(BP, "atk") == want_capped, sdef.id        # noqa: SLF001
        assert eng._aggregate_boost(BP, "atk") == _legacy_capped(rt, BP, "atk"), sdef.id  # noqa: SLF001
    # 多状态混合（不同实例求和）同样逐字段一致
    mixed = {d.id: d for d, _a, _b in (cases[0], cases[1], cases[4])}
    rt = EffectRuntime(defs=mixed)
    for sid in mixed:
        rt.apply_status(sid, BP, source=BN, force=True)
    insts = [dict(i) for i in rt.status_instances(BP)]
    eng = _engine_with(mixed, insts)
    assert eng._aggregate_boost(BP, "atk") == _legacy_capped(rt, BP, "atk") == 44.0  # noqa: SLF001


def test_stacks_zero_or_invalid_counts_as_single_layer() -> None:
    """防御：stacks 缺失/0/非法 → 按 1 层（不放大、不归零），与既有实例形状兼容。"""
    st = _status("s_def", stacks_actions=[
        {"type": "stat_modifier", "stat": "atk", "value": 6}], max_stack=3, category="buff")
    for bad in (0, -2, "x", None):
        inst = {"status_id": st.id, "stacks": bad}
        eng = _engine_with({st.id: st}, [inst])
        assert eng._aggregate_boost(BP, "atk") == 6.0, bad  # noqa: SLF001


def test_s5_same_source_renews_distinct_source_stacks() -> None:
    """S5 交互如实登记：同来源 → 只保留一个（renewed，层数不增）；异来源 → S3 叠层。

    符文接线侧据此以「来源=侧#行动序号」区分每次攻击施加（见 C 组），**不改 apply_status 行为**。
    """
    rt = EffectRuntime(defs={STACK_ATK.id: STACK_ATK})
    r1 = rt.apply_status(STACK_ATK.id, BP, source="same", force=True)
    r2 = rt.apply_status(STACK_ATK.id, BP, source="same", force=True)
    assert r1.reason == "applied" and r2.reason == "renewed"
    inst = rt.find_status(BP, STACK_ATK.id)
    assert inst is not None and int(inst["stacks"]) == 1
    r3 = rt.apply_status(STACK_ATK.id, BP, source="other", force=True)
    assert r3.reason == "stacked"
    assert int(rt.find_status(BP, STACK_ATK.id)["stacks"]) == 2
    assert _engine_with({STACK_ATK.id: STACK_ATK},
                        [dict(rt.find_status(BP, STACK_ATK.id))])._aggregate_boost(  # noqa: SLF001
        BP, "atk") == 10.0
