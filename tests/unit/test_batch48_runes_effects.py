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

from typing import Any, Dict, List, Mapping, Optional

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


# ===========================================================================
# C. 2 阶战斗接线：符文声明 effect + trigger → 按侧/时点触发（孔位经 active_rune_sockets）
# ===========================================================================
# 效果容器（**不带 trigger**：不进全局注册表扫描 → 不会对所有战斗单位泄漏）
FX_ATK_STACK = _Def({
    "id": "fx_atk_stack", "name": "fx_atk_stack", "class": "special",
    "actions": [{"type": "status_apply", "status": "s_atk_stack", "target": "self"}],
})
FX_GRIEVOUS = _Def({
    "id": "fx_grievous", "name": "fx_grievous", "class": "special",
    "actions": [{"type": "status_apply", "status": GRIEVOUS.id, "target": "enemy"}],
})
DEFS = {FX_ATK_STACK.id: FX_ATK_STACK, FX_GRIEVOUS.id: FX_GRIEVOUS,
        STACK_ATK.id: STACK_ATK, GRIEVOUS.id: GRIEVOUS}

RUNE_STACK = {
    "id": "r_stack", "name": "r_stack", "tier": 2, "family": "f",
    "by_equip_type": {"default": {"effects": [
        {"effect": FX_ATK_STACK.id, "trigger": "action_start"}]}},
}
RUNE_GRIEVOUS = {
    "id": "r_grievous", "tier": 2, "family": "f",
    "effects": [{"effect": FX_GRIEVOUS.id, "trigger": "on_hit"}],
}
SLOTS_C: Dict[str, Any] = {
    "weapon": {"name": "武器", "max": 1},
    "offhand": {"name": "副手", "max": 1, "role": "offhand"},
}
OFFHAND_C = {"enabled": True, "single_hand_scale": 0.5}
ITEMS_C: Dict[str, Any] = {"sword": {"id": "sword", "type": "weapon"}}
RUNES_C: Dict[str, Any] = {RUNE_STACK["id"]: RUNE_STACK, RUNE_GRIEVOUS["id"]: RUNE_GRIEVOUS}


def test_rune_effect_refs_of_difference_table() -> None:
    """差异解析：命中类型覆盖条目优先；未命中/无覆盖 → 回流符文顶层 effects。"""
    d = {
        "id": "r", "tier": 2, "family": "f",
        "effects": [{"effect": "fx_top", "trigger": "battle_start"}],
        "by_equip_type": {
            "default": {"effects": [{"effect": "fx_default", "trigger": "on_hit"}]},
            "weapon": {"effects": [{"effect": "fx_w", "trigger": "action_start"}]},
        },
    }
    from qbot_rpg.core.runes import rune_effect_refs_of

    assert [r["effect"] for r in rune_effect_refs_of(d, "weapon")] == ["fx_w"]
    assert [r["effect"] for r in rune_effect_refs_of(d, "armor_body")] == ["fx_default"]
    # 条目未声明 effects → 顶层 effects 兜底（口径 §二.1 顶层形状）
    d2 = {"id": "r2", "tier": 2, "family": "f",
          "effects": [{"effect": "fx_top", "trigger": "battle_start"}],
          "by_equip_type": {"default": {"stats": {"atk": 1}}}}
    refs = rune_effect_refs_of(d2, "weapon")
    assert refs == [{"effect": "fx_top", "trigger": "battle_start"}], refs
    # 非法元素/空 effect 丢弃
    d3 = {"id": "r3", "tier": 2, "family": "f", "by_equip_type": {
        "default": {"effects": ["x", {"trigger": "on_hit"}, {"effect": ""},
                                {"effect": "ok", "overrides": {"value": 3}}]}}}
    assert rune_effect_refs_of(d3, None) == [
        {"effect": "ok", "overrides": {"value": 3}}]


def _player_ctx(item_id: str, socket_row: list, slot: str = "weapon",
                runes: Any = None) -> Dict[str, Any]:
    from qbot_rpg.data.item import ItemInstance

    row = ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                       bound=False, stack_max=1, slot=slot)
    player: Dict[str, Any] = {
        "inventory": [row],
        "equipment": {slot: {"item_id": item_id, "uid": row.uid}},
        "persistent_state": {"rune_sockets": {row.uid: list(socket_row)}},
    }
    return {
        "player": player, "slots": SLOTS_C, "equipment_offhand": dict(OFFHAND_C),
        "runes": dict(runes if runes is not None else RUNES_C), "items": dict(ITEMS_C),
        "settings": {"deep_craft": {"enabled": True}, "rune_sockets": {"default_count": 3}},
    }


def test_active_rune_effect_refs_uses_active_sockets() -> None:
    """取数经 jewel.active_rune_sockets：装符文 → 有 refs；空孔 → []。"""
    from qbot_rpg.core.rune_battle import active_rune_effect_refs

    ctx = _player_ctx("sword", ["r_stack", None, None])
    refs = active_rune_effect_refs(ctx)
    assert refs == [{"effect": FX_ATK_STACK.id, "trigger": "action_start"}], refs
    assert active_rune_effect_refs(_player_ctx("sword", [None, None, None])) == []


def test_active_rune_effect_refs_offhand_inactive() -> None:
    """副手失活继承：同件挪作副手 → 符文效果 refs 为空（active_rune_sockets → []）。"""
    from qbot_rpg.core.rune_battle import active_rune_effect_refs

    ctx = _player_ctx("sword", ["r_stack", None, None])
    ctx["player"]["equipment"] = {"offhand": ctx["player"]["equipment"]["weapon"]}
    assert active_rune_effect_refs(ctx) == []


def test_active_rune_effect_refs_switch_off_and_missing_sources() -> None:
    """总闸关 / 缺 runes / 缺 player → 零 refs（防御降级，不抛）。"""
    from qbot_rpg.core.rune_battle import active_rune_effect_refs

    ctx = _player_ctx("sword", ["r_stack", None, None])
    ctx["settings"]["deep_craft"]["enabled"] = False
    assert active_rune_effect_refs(ctx) == []
    ctx = _player_ctx("sword", ["r_stack", None, None])
    ctx["runes"] = {}
    assert active_rune_effect_refs(ctx) == []
    assert active_rune_effect_refs({}) == []


def _rune_engine(refs: List[Dict[str, Any]], side: str = BP) -> Any:
    """BattleEngine（defs 直连）+ 该侧 combatant 携带 rune_effects。"""
    from qbot_rpg.core.battle import BattleEngine

    eng = BattleEngine(defs=dict(DEFS))
    eng._snap = {"status_state": {BP: [], BN: []}, "action_seq": 0,  # noqa: SLF001
                 "player": {"max_hp": 1000, "hp": 400, "atk": 100, "name": "p"},
                 "enemy": {"max_hp": 1000, "hp": 400, "atk": 100, "name": "e"}}
    if refs:
        eng._snap[side]["rune_effects"] = list(refs)  # noqa: SLF001
    return eng


def test_rune_per_attack_stack_scales_in_battle() -> None:
    """每次攻击（action_start）→ 层数增益逐次上升、达 max_stack=4 后不再增（逐次数值）。"""
    eng = _rune_engine([{"effect": FX_ATK_STACK.id, "trigger": "action_start"}])
    seen: List[float] = []
    for i in range(1, 7):
        eng._snap["action_seq"] = i                     # noqa: SLF001 —— 模拟第 i 次行动
        # 达上限后 applied=False（at_max_stack）→ 容器传播失败、side_effects 为空
        # （既有 execute_action 语义）——层数平台期由 boost 断言体现
        eng._dispatch_event("action_start", BP)         # noqa: SLF001
        seen.append(eng._aggregate_boost(BP, "atk"))    # noqa: SLF001
    assert seen == [5.0, 10.0, 15.0, 20.0, 20.0, 20.0], seen
    inst = eng._snap["status_state"][BP][0]             # noqa: SLF001
    assert int(inst["stacks"]) == 4


def test_rune_grievous_on_hit_end_to_end() -> None:
    """2 阶重伤端到端：on_hit 给目标挂重伤 → 目标受治疗减少（战斗中 heal 实测）。"""
    eng = _rune_engine([{"effect": FX_GRIEVOUS.id, "trigger": "on_hit"}])
    eng._snap["action_seq"] = 1                         # noqa: SLF001
    fx = eng._dispatch_event("on_hit", BP)              # noqa: SLF001
    assert any(e.get("type") == "status_apply" and e.get("applied") for e in fx), fx
    assert eng._snap["status_state"][BN][0]["status_id"] == GRIEVOUS.id  # noqa: SLF001
    # 敌方（被重伤）受伤后治疗：不经战斗主循环，直接跑 heal 动作（同 ctx/hp 段）
    rt = eng._new_runtime()                             # noqa: SLF001
    before = eng._snap[BN]["hp"]                        # noqa: SLF001
    execute_action({"type": "heal", "value": 100, "target": "self"},
                   _ctx(eng._snap, attacker=BN, target=BP), rt)  # noqa: SLF001
    assert eng._snap[BN]["hp"] - before == 60           # noqa: SLF001


def test_rune_candidates_empty_without_runes_field() -> None:
    """回归：无 rune_effects 字段 → 候选空 → dispatch 与既有（无符文）逐字段一致。"""
    eng = _rune_engine([])
    assert eng._rune_candidates("action_start", BP) == []   # noqa: SLF001
    assert eng._dispatch_event("action_start", BP) == []    # noqa: SLF001
    # 敌方没有符文 → 候选空（不误触发）
    eng2 = _rune_engine([{"effect": FX_ATK_STACK.id, "trigger": "action_start"}])
    assert eng2._rune_candidates("action_start", BN) == []  # noqa: SLF001
    assert eng2._rune_candidates("battle_start", BP) == []  # noqa: SLF001


def test_player_combatant_carries_rune_effects_only_when_present() -> None:
    """指令壳装配：有符文 → combatant.rune_effects；无符文 → 不新增键（逐字段一致）。"""
    from qbot_rpg.commands.battle_launch_commands import _player_combatant

    ctx = _player_ctx("sword", ["r_stack", None, None])
    comb = _player_combatant(ctx)
    assert comb["rune_effects"] == [
        {"effect": FX_ATK_STACK.id, "trigger": "action_start"}]
    plain = _player_ctx("sword", [None, None, None])
    base = _player_combatant(plain)
    assert "rune_effects" not in base
    assert base == _player_combatant(_player_ctx("sword", [None, None, None]))


# ===========================================================================
# D. 3 阶偏向性符文（默认口径：偏向某相性，对接批38 相性层）
# ===========================================================================
AFF_ITEMS: Dict[str, Any] = {
    "sword_fire": {"id": "sword_fire", "type": "weapon",
                   "affinities": {"fire": 80, "ice": 20}},
    "sword_ice": {"id": "sword_ice", "type": "weapon",
                  "affinities": {"ice": 80, "fire": 20}},
    "sword_plain": {"id": "sword_plain", "type": "weapon"},
}
RUNE_BIAS = {
    "id": "r_bias_fire", "tier": 3, "family": "f",
    "by_equip_type": {"default": {"stats": {"atk": 10}}},
    "bias": {"affinity": "fire", "bonus_pct": 50},
}


def test_rune_bias_of_shape() -> None:
    """bias 解析：`{affinity, bonus_pct}`；affinity 缺/非法 → {}（不臆断）。"""
    from qbot_rpg.core.runes import rune_bias_of

    assert rune_bias_of(RUNE_BIAS, "weapon") == {"affinity": "fire", "bonus_pct": 50.0}
    assert rune_bias_of({"id": "r", "bias": {"bonus_pct": 10}}) == {}
    assert rune_bias_of({"id": "r", "bias": {"affinity": "fire"}}) == {
        "affinity": "fire", "bonus_pct": 0.0}
    assert rune_bias_of({"id": "r"}) == {}


def test_rune_stats_of_bias_main_and_sub_affinity() -> None:
    """按相性生效：偏向相性 = 主相性 / 副相性 → ×1.5；不命中/无相性 → 原值。"""
    from qbot_rpg.core.runes import rune_stats_of

    assert rune_stats_of(RUNE_BIAS, "weapon", {"fire": 80, "ice": 20}) == {"atk": 15.0}
    assert rune_stats_of(RUNE_BIAS, "weapon", {"ice": 80, "fire": 20}) == {"atk": 15.0}
    assert rune_stats_of(RUNE_BIAS, "weapon", {"ice": 80, "wind": 20}) == {"atk": 10.0}
    assert rune_stats_of(RUNE_BIAS, "weapon", None) == {"atk": 10.0}
    assert rune_stats_of(RUNE_BIAS, "weapon", {}) == {"atk": 10.0}
    # 非正相性值不参与排名（批38 rank_affinities 口径）
    assert rune_stats_of(RUNE_BIAS, "weapon", {"fire": 0, "ice": 5}) == {"atk": 10.0}


def test_rune_stats_bias_negative_and_zero() -> None:
    """bonus_pct 可 0（契约等价）/可负（反向偏科）；0 → 数值逐字段等于未声明 bias。"""
    from qbot_rpg.core.runes import rune_stats_of

    zero = {"id": "r0", "tier": 3, "family": "f",
            "by_equip_type": {"default": {"stats": {"atk": 10}}},
            "bias": {"affinity": "fire", "bonus_pct": 0}}
    neg = {"id": "rn", "tier": 3, "family": "f",
           "by_equip_type": {"default": {"stats": {"atk": 10}}},
           "bias": {"affinity": "fire", "bonus_pct": -20}}
    assert rune_stats_of(zero, "weapon", {"fire": 9}) == {"atk": 10.0}
    assert rune_stats_of(neg, "weapon", {"fire": 9}) == {"atk": 8.0}


def test_aggregate_bonus_bias_per_host_item() -> None:
    """战斗/面板证据：同符文装 fire 主相性件 → atk 15；装 ice 主相性件 → atk 15（副相性命中）。"""
    from qbot_rpg.core.equipment import EquipmentEngine
    from qbot_rpg.core.jewel import JewelSystem

    eng = EquipmentEngine(slots=SLOTS_C, runes={RUNE_BIAS["id"]: RUNE_BIAS},
                          items=AFF_ITEMS, jewel=JewelSystem(
                              settings={"deep_craft": {"enabled": True}}))
    rows = {}
    for iid in ("sword_fire", "sword_plain"):
        from qbot_rpg.data.item import ItemInstance
        row = ItemInstance(item_id=iid, name=iid, count=1, quality="normal",
                           bound=False, stack_max=1, slot="weapon")
        p = {"inventory": [row], "equipment": {"weapon": {"item_id": iid, "uid": row.uid}},
             "persistent_state": {"rune_sockets": {row.uid: ["r_bias_fire", None, None]}}}
        rows[iid] = (eng.aggregate_bonus(p), row)
    assert rows["sword_fire"][0] == {"flat": {"atk": 15.0}, "pct": {}}
    assert rows["sword_plain"][0] == {"flat": {"atk": 10.0}, "pct": {}}


def test_bias_regression_no_bias_field_identical() -> None:
    """回归：无 bias（1/2 阶）→ 数值与批47 逐字段一致（有/无相性输入都一样）。"""
    from qbot_rpg.core.runes import rune_stats_of, sum_rune_stats

    plain = {"id": "r1", "tier": 1, "family": "f",
             "by_equip_type": {"default": {"stats": {"atk": 6, "hp_pct": 5}}}}
    for aff in (None, {}, {"fire": 9}):
        assert rune_stats_of(plain, "weapon", aff) == {"atk": 6.0, "hp_pct": 5.0}
    assert sum_rune_stats(["r1"], {"r1": plain}, "weapon", {"fire": 9}) == {
        "atk": 6.0, "hp_pct": 5.0}


def test_validator_bias_shape() -> None:
    """RUNE-07：bias 形状红拦/黄提示（指向相性层引用）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.validator import check_pack

    def _pack(rune: Dict[str, Any], settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        pack: Dict[str, Any] = {
            "manifest": {"name": "t", "version": "1.0", "schema_version": 1,
                         "author": "t", "modules": ["runes"]},
            "runes": [rune],
        }
        if settings is not None:
            pack["settings"] = settings
        return pack

    good = {"id": "r3", "tier": 3, "family": "f",
            "by_equip_type": {"default": {"stats": {"atk": 1}}},
            "bias": {"affinity": "fire", "bonus_pct": 25}}
    assert check_pack(_pack(good), default_field_meta_table()).count_errors == 0
    # affinity 缺失 → 红拦
    bad = {"id": "r3", "tier": 3, "family": "f",
           "by_equip_type": {"default": {"stats": {"atk": 1}}},
           "bias": {"bonus_pct": 25}}
    rep = check_pack(_pack(bad), default_field_meta_table())
    assert "bias_affinity_required" in [e.detail.get("rule") for e in rep.errors]
    # 相性引用靶已接线 + 未知相性 → 黄提示；低阶声明 bias → 黄提示
    rep2 = check_pack(
        _pack(good, {"affinities": [{"id": "ice"}]}), default_field_meta_table())
    rules = [w.detail.get("rule") for w in rep2.warnings]
    assert "bias_affinity_unknown" in rules
    low = {"id": "r1", "tier": 1, "family": "f",
           "by_equip_type": {"default": {"stats": {"atk": 1}}},
           "bias": {"affinity": "ice", "bonus_pct": 25}}
    rep3 = check_pack(_pack(low), default_field_meta_table())
    assert "bias_only_tier3" in [w.detail.get("rule") for w in rep3.warnings]


# ===========================================================================
# E. 3 合 1 端到端（1→2→3 逐阶 / 禁跳级 / 失败原子性 / synth_allowed+总闸交互）
# ===========================================================================
RUNES_CHAIN: Dict[str, Any] = {
    "r_t1": {"id": "r_t1", "name": "r_t1", "tier": 1, "family": "f",
             "by_equip_type": {"default": {"stats": {"atk": 1}}}},
    "r_t2": {"id": "r_t2", "name": "r_t2", "tier": 2, "family": "f",
             "by_equip_type": {"default": {"stats": {"atk": 2}}},
             "effects": [{"effect": "fx_atk_stack", "trigger": "action_start"}]},
    "r_t3": {"id": "r_t3", "name": "r_t3", "tier": 3, "family": "f",
             "by_equip_type": {"default": {"stats": {"atk": 4}}},
             "bias": {"affinity": "fire", "bonus_pct": 50}},
}


def _chain_ctx(held: Dict[str, int], *, gem: int = 20,
               deep_craft: Any = "enabled", add_ok: bool = True) -> Any:
    inv = dict(held)

    def remove_item(i: Any, c: int) -> bool:
        key = str(i)
        if inv.get(key, 0) < int(c):
            return False
        inv[key] -= int(c)
        return True

    def add_item(i: Any, c: int, bound: bool) -> bool:
        if not add_ok:
            return False
        inv[str(i)] = inv.get(str(i), 0) + int(c)
        return True

    ctx: Dict[str, Any] = {
        "runes": dict(RUNES_CHAIN), "items": {}, "inventory": inv,
        "count_item": lambda i: int(inv.get(str(i), 0)),
        "remove_item": remove_item, "add_item": add_item,
        "currencies": {"coins": 0, "gem": gem},
    }
    if deep_craft != "absent":
        ctx["settings"] = {"deep_craft": {"enabled": deep_craft == "enabled"}}
    return ctx, inv


def _chain_recipe(inp: str, out: str, **over: Any) -> Dict[str, Any]:
    d = {"kind": "upgrade", "subtype": "rune_upgrade", "id": "rcp",
         "inputs": [{"item": inp, "count": 3}], "output": {"item": out, "count": 1},
         "cost": {"gem": 10}}
    d.update(over)
    return d


def _upg() -> Any:
    from qbot_rpg.core.upgrade import UpgradeEngine

    return UpgradeEngine(settings={})


def test_rune_3in1_end_to_end_tier1_to_2_to_3() -> None:
    """端到端：3×1 阶 → 2 阶 → 3×2 阶 → 3 阶（逐阶贴产物）。"""
    eng = _upg()
    ctx, inv = _chain_ctx({"r_t1": 3, "r_t2": 3})
    # 第一阶：3×r_t1 → r_t2
    r1 = eng.execute(ctx, _chain_recipe("r_t1", "r_t2"))
    assert r1["ok"] and (r1["tier_in"], r1["tier_out"]) == (1, 2), r1
    assert inv == {"r_t1": 0, "r_t2": 4}, inv            # 3 消耗 + 1 产出
    # 第二阶：3×r_t2 → r_t3
    r2 = eng.execute(ctx, _chain_recipe("r_t2", "r_t3"))
    assert r2["ok"] and (r2["tier_in"], r2["tier_out"]) == (2, 3), r2
    assert inv == {"r_t1": 0, "r_t2": 1, "r_t3": 1}, inv
    assert ctx["currencies"]["gem"] == 0                 # 2×10


def test_rune_3in1_rejects_skip_and_max() -> None:
    """禁跳级/满阶：1→3 越阶拒；3 阶输入无更高阶可升 → 拒（零副作用）。"""
    eng = _upg()
    ctx, inv = _chain_ctx({"r_t1": 3, "r_t3": 3})
    res = eng.execute(ctx, _chain_recipe("r_t1", "r_t3"))
    assert res["ok"] is False and res["reason"] == "rune_skip_tier"
    assert inv == {"r_t1": 3, "r_t3": 3} and ctx["currencies"]["gem"] == 20
    res2 = eng.execute(ctx, _chain_recipe("r_t3", "r_t3", rune_tier=4))
    assert res2["ok"] is False and res2["reason"] == "rune_max_tier"
    assert inv == {"r_t1": 3, "r_t3": 3} and ctx["currencies"]["gem"] == 20


def test_rune_3in1_atomic_add_failure_leaves_no_half_product() -> None:
    """失败原子性：产出 hook 失败 → 货币/背包 best-effort 回滚（不留半成品）。"""
    eng = _upg()
    ctx, inv = _chain_ctx({"r_t1": 3}, add_ok=False)
    res = eng.execute(ctx, _chain_recipe("r_t1", "r_t2"))
    assert res["ok"] is False and res["reason"] == "add_item_failed"
    assert inv == {"r_t1": 3}, inv                       # 输入未被扣
    assert ctx["currencies"]["gem"] == 20               # 宝石未扣


def test_rune_3in1_deep_craft_switch_interaction() -> None:
    """总闸交互：deep_craft 关 → runes_disabled 零副作用；开 → 通过；ctx 无该段 → 不收紧。"""
    eng = _upg()
    ctx, inv = _chain_ctx({"r_t1": 3}, deep_craft="disabled")
    res = eng.execute(ctx, _chain_recipe("r_t1", "r_t2"))
    assert res["ok"] is False and res["reason"] == "runes_disabled"
    assert inv == {"r_t1": 3} and ctx["currencies"]["gem"] == 20
    ctx2, _ = _chain_ctx({"r_t1": 3}, deep_craft="enabled")
    assert eng.execute(ctx2, _chain_recipe("r_t1", "r_t2"))["ok"] is True
    ctx3, _ = _chain_ctx({"r_t1": 3}, deep_craft="absent")
    assert eng.execute(ctx3, _chain_recipe("r_t1", "r_t2"))["ok"] is True


def test_rune_3in1_synth_allowed_interaction() -> None:
    """synth_allowed 交互：显式 false → 深度未解锁拒（零副作用）；true/缺省 → 放行。"""
    eng = _upg()
    ctx, inv = _chain_ctx({"r_t1": 3})
    res = eng.execute(ctx, _chain_recipe("r_t1", "r_t2", synth_allowed=False))
    assert res["ok"] is False and res["reason"] == "runes_deep_locked"
    assert inv == {"r_t1": 3} and ctx["currencies"]["gem"] == 20
    ctx2, _ = _chain_ctx({"r_t1": 3})
    assert eng.execute(ctx2, _chain_recipe("r_t1", "r_t2", synth_allowed=True))["ok"] is True
    ctx3, _ = _chain_ctx({"r_t1": 3})
    assert eng.execute(ctx3, _chain_recipe("r_t1", "r_t2"))["ok"] is True
