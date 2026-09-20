"""批59 · 特效体系小尾巴验收测试（奖励轴 D5 / overheal BV-1~3 / m1 flake 根治）。

依据：
  · `docs/深度打造_决策记录.md` §十五 **D5**（奖励轴下钳 0）+ §二十一 批56 登记的
    **BV-1/BV-2/BV-3** 三个待裁决；
  · `特效整理设计_1_修正轴全集.md` §1.7 X43（`reward_mult{scope}`）/ X28（行动速度）/
    §4-E5（过量治疗）；
  · 实现说明 §二十一（批59）。

覆盖：
  A. **奖励轴（D5）**：`reward_mult_pct`（X43）登记进 `EFFECT_AXIS_SPECS`、`min: 0`
     下钳 0、`bridge="settlement"`（不进战斗桥）、`consumer` = 待接哨兵（**不硬造消费点**）。
  B. **overheal BV-1**：过量上限可配（`cap_pct` / `cap_flat`；默认 `None` = 无额外上限，
     与批56 现状一致）。
  C. **overheal BV-2**：去向选择点显式化（`mode: keep|discard`；`shield` 为**未实现**保留位，
     校验器黄提示、不半成品生效）。
  D. **BV-3**：`action_speed_pct` 权表坐标登记（不再 `unknown_axis`），可配。
  E. **m1 flake 根治**：`evaluate("true"/"false")` 走 Python 快路径、不经 Node，结果确定；
     并钉死 vm watchdog 容差已放宽（见实现说明批59）。

纪律：只构造内存对象（不写任何真实内容包）；匿名 id（`s_*`）；数值/区间全由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.effects import (
    DamageCtx,
    EffectRuntime,
    apply_heal_to_hp,
    execute_action,
)
from qbot_rpg.data.gear_stats import (
    DEFAULT_EFFECT_AXES,
    EFFECT_AXIS_SPECS,
    EFFECT_AXIS_WEIGHTS,
    EFFECT_CONSUMER_PENDING,
    EFFECT_TO_COMBATANT,
    GEAR_EFFECT_KEYS,
    OVERHEAL_KEY,
    combatant_updates,
    effect_axis_value,
    effect_equiv,
    normalize_overheal,
    overheal_cap,
)

REWARD_AXIS = "reward_mult_pct"
SPEED_AXIS = "action_speed_pct"


def _spec(axis: str) -> Mapping[str, Any]:
    return next(s for s in EFFECT_AXIS_SPECS if str(s["axis"]) == axis)


def rules(rep: Any) -> Tuple[str, ...]:
    return tuple(str(e.kind) for e in rep.errors)


def warnings_of(rep: Any) -> Tuple[str, ...]:
    return tuple(str(w.kind) for w in rep.warnings)


# =====================================================================================
# A · 奖励轴（D5）：登记 + min: 0 下钳 0 + 消费点待接（不硬造）
# =====================================================================================
def test_a1_reward_axis_registered_min_zero_and_pending_consumer() -> None:
    """X43 登记：`min:0` / `bridge=settlement` / `consumer`=待接哨兵（不是伪造的唯一收口）。"""
    spec = _spec(REWARD_AXIS)
    assert spec["doc_id"] == "X43"
    assert str(spec["priority"]) == "P1"
    assert float(spec["min"]) == 0.0                  # D5 下钳 0
    assert float(spec["max"]) == 400.0                # ×5.0 的百分点形式
    assert float(spec["default"]) == 0.0              # 缺省恒等（×1.0）
    assert spec["consumer"] == EFFECT_CONSUMER_PENDING
    assert str(spec["consumer_note"]).strip()
    assert tuple(spec.get("scope", ())) == (
        "exp", "coins", "gem", "rep", "drop_chance", "drop_count", "drop_rarity")
    assert REWARD_AXIS in GEAR_EFFECT_KEYS
    # 结算期轴 → 不进战斗桥（EFFECT_TO_COMBATANT 由 bridge 字段派生）。
    assert spec.get("bridge") == "settlement"
    assert REWARD_AXIS not in EFFECT_TO_COMBATANT
    assert "reward_mult_pct" not in combatant_updates({REWARD_AXIS: 25.0})


def test_a2_reward_negative_is_clamped_zero_by_declaration_not_hardcoded() -> None:
    """下钳 0 的证据：默认声明把负值钳成 0；包声明可改（读声明、不写死）。"""
    # 默认声明（未配置 settings.effect_axes）→ min=0 → 负值被钳 0。
    assert DEFAULT_EFFECT_AXES[REWARD_AXIS]["min"] == 0.0
    assert effect_axis_value({REWARD_AXIS: -30.0}, REWARD_AXIS, None) == 0.0
    assert effect_axis_value({REWARD_AXIS: 25.0}, REWARD_AXIS, None) == 25.0
    # 包声明可放开下界（证明钳制来自声明，不是引擎硬编码）。cfg = effect_axes 段本体。
    cfg = {REWARD_AXIS: {"min": -50.0}}
    assert effect_axis_value({REWARD_AXIS: -30.0}, REWARD_AXIS, cfg) == -30.0


def test_a3_reward_axis_is_visible_in_editor_metadata() -> None:
    """编辑器可见：items/equipment 字段表覆盖该轴，中文名 + 说明 + range_min=0 齐备。"""
    table = default_field_meta_table()
    for mod in ("items", "equipment"):
        fields = table.module(mod).fields
        assert REWARD_AXIS in fields, mod
        fm = fields[REWARD_AXIS]
        assert fm.label == _spec(REWARD_AXIS)["display"]["label"]
        assert fm.help == _spec(REWARD_AXIS)["display"]["help"]
        assert fm.range_min == 0.0
        assert fm.range_max == 400.0


def test_a4_reward_axis_has_no_wired_consumer_zero_change() -> None:
    """未接线 = 零变化：不配置 → 战斗桥无该键；轴只是登记（登记 ≠ 已发放加成）。"""
    from qbot_rpg.data.gear_stats import route_bonus_into

    flat: Dict[str, float] = {}
    route_bonus_into({REWARD_AXIS: 0.0}, flat, {})
    assert combatant_updates(flat) == {}
    # 即使显式给了非零值，也就地留在 flat（结算期轴），不进 combatant。
    flat2: Dict[str, float] = {}
    route_bonus_into({REWARD_AXIS: 25.0}, flat2, {})
    assert flat2[REWARD_AXIS] == 25.0
    assert REWARD_AXIS not in combatant_updates(flat2)


# =====================================================================================
# B · overheal BV-1：过量上限可配（默认无额外上限 = 批56 现状）
# =====================================================================================
def test_b1_default_has_no_extra_cap_same_as_batch56() -> None:
    """缺省 = 无额外上限（与批56 逐字段一致）：满血治疗 200 → HP 1200。"""
    n = normalize_overheal(None)
    assert n["cap_pct"] is None and n["cap_flat"] is None
    assert overheal_cap(1000, None) == 1000.0          # 未启用 → 既有封顶
    assert overheal_cap(1000, {"enabled": True}) is None  # 启用且无上限 → None（不封顶）
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 200, cap=1000, cfg={"enabled": True}) == 1200


def test_b2_cap_pct_caps_overheal() -> None:
    """`cap_pct`：最多超出 max_hp 的百分比（50 → 上限 ×1.5 = 1500）。"""
    cfg = {"mode": "keep", "cap_pct": 50}
    assert overheal_cap(1000, cfg) == 1500.0
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 800, cap=1000, cfg=cfg) == 1500
    assert c["hp"] == 1500


def test_b3_cap_flat_caps_overheal() -> None:
    """`cap_flat`：最多超出的点数（200 → 上限 max_hp+200 = 1200）。"""
    cfg = {"enabled": True, "cap_flat": 200}
    assert overheal_cap(1000, cfg) == 1200.0
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 500, cap=1000, cfg=cfg) == 1200


def test_b4_both_caps_take_stricter() -> None:
    """两道上限同给取更小者：cap_pct 50（1500）vs cap_flat 100（1100）→ 1100。"""
    cfg = {"enabled": True, "cap_pct": 50, "cap_flat": 100}
    assert overheal_cap(1000, cfg) == 1100.0
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 999, cap=1000, cfg=cfg) == 1100


def test_b5_zero_cap_means_no_overheal() -> None:
    """上限 0 = 一个点都不许超（但仍走保留分支，结果同现状）。"""
    assert overheal_cap(1000, {"enabled": True, "cap_flat": 0}) == 1000.0
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 100, cap=1000, cfg={"enabled": True, "cap_flat": 0}) == 1000


def test_b6_cap_applies_through_engine_heal_action() -> None:
    """引擎级证据：EffectRuntime 技能治疗经同一收口封顶（BV-1 不只纯函数）。"""
    snap = {"player": {"hp": 1000, "max_hp": 1000, "defenses": {}},
            "enemy": {"hp": 500, "max_hp": 500, "defenses": {}},
            "status_state": {"player": [], "enemy": []},
            "marks_state": {"player": [], "enemy": []},
            "resist_table": {"player": {}, "enemy": {}}}
    ctx = DamageCtx(raw_damage=0, attack_type="skill", attacker="player",
                    target="enemy", snapshot=snap, variables={})
    rt = EffectRuntime(status_state=snap["status_state"],
                       config={OVERHEAL_KEY: {"enabled": True, "cap_flat": 300}})
    execute_action({"type": "heal", "value": 800, "target": "self", "stat": "hp"}, ctx, rt)
    assert snap["player"]["hp"] == 1300


def test_b7_validator_cap_fields() -> None:
    """校验：cap_pct/cap_flat 合法放行；非数值 / 布尔 / 负数 → 红拦 R-1。"""
    assert not check_pack({"settings": {OVERHEAL_KEY: {"enabled": True, "cap_pct": 50}}}).errors
    assert not check_pack({"settings": {OVERHEAL_KEY: {"enabled": True, "cap_flat": 0}}}).errors
    for bad in ({"cap_pct": "x"}, {"cap_flat": True}, {"cap_pct": -1}, {"cap_flat": -5}):
        rep = check_pack({"settings": {OVERHEAL_KEY: bad}})
        assert "R-1" in rules(rep), (bad, rules(rep))


# =====================================================================================
# C · overheal BV-2：去向选择点显式化（keep/discard；shield 未实现）
# =====================================================================================
def test_c1_mode_keep_retains_and_discard_discards() -> None:
    """`mode` 直接决定去向，且 `enabled` ⇔ `mode == "keep"`。"""
    keep = normalize_overheal({"mode": "keep"})
    assert keep["mode"] == "keep" and keep["enabled"] is True
    discard = normalize_overheal({"mode": "discard"})
    assert discard["mode"] == "discard" and discard["enabled"] is False
    c = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c, 200, cap=1000, cfg={"mode": "keep"}) == 1200
    c2 = {"max_hp": 1000, "hp": 1000}
    assert apply_heal_to_hp(c2, 200, cap=1000, cfg={"mode": "discard"}) == 1000


def test_c2_mode_takes_precedence_over_enabled() -> None:
    """显式 `mode` 优先于兼容的 `enabled`（把选择点表达清楚，避免两键打架）。"""
    assert normalize_overheal({"enabled": False, "mode": "keep"})["enabled"] is True
    assert normalize_overheal({"enabled": True, "mode": "discard"})["enabled"] is False


def test_c3_shield_is_reserved_not_implemented() -> None:
    """`shield`（转护盾，BV-2 未实现）：**不生效**（回落 discard），且被拒绝 + 明确标注。"""
    n = normalize_overheal({"mode": "shield"})
    assert n["mode"] == "discard" and n["enabled"] is False
    c = {"max_hp": 1000, "hp": 1000}
    # 未实现 = 不许半成品生效：写 shield 仍是现状（丢弃）。
    assert apply_heal_to_hp(c, 200, cap=1000, cfg={"mode": "shield"}) == 1000
    rep = check_pack({"settings": {OVERHEAL_KEY: {"mode": "shield"}}})
    # 半成品开关的正确处理 = 不放行（红拦）+ 显式标注「未实现」（黄提示）。
    assert "R-1" in rules(rep)
    assert "Y-21" in warnings_of(rep)


def test_c4_unknown_mode_is_red() -> None:
    """未知 mode → 红拦 R-1（不是静默回落）。"""
    rep = check_pack({"settings": {OVERHEAL_KEY: {"mode": "nonsense"}}})
    assert "R-1" in rules(rep)


def test_c5_supported_modes_are_documented_and_closed() -> None:
    """枚举闭合：只承认 keep/discard；shield 在保留表里（明确未实现）。"""
    from qbot_rpg.data.gear_stats import OVERHEAL_MODES, OVERHEAL_MODE_RESERVED

    assert OVERHEAL_MODES == ("keep", "discard")
    assert "shield" in OVERHEAL_MODE_RESERVED
    assert "未实现" in OVERHEAL_MODE_RESERVED["shield"]


# =====================================================================================
# D · BV-3：速度轴权表坐标登记（不再 unknown_axis）
# =====================================================================================
def test_d1_speed_axis_weight_registered() -> None:
    """`action_speed_pct` 进权表：calib=+20 ⇔ output=+20%（实现说明 §18.7 设计口径）。"""
    w = EFFECT_AXIS_WEIGHTS[SPEED_AXIS]
    assert float(w["calib"]) == 20.0
    assert float(w["output"]) == 20.0
    assert float(w["survival"]) == 0.0
    assert str(w["doc_id"]) == "X28"


def test_d2_speed_no_longer_unknown_axis() -> None:
    """开启闸时速度轴不再落 `unknown`（BV-3 的直接目的）。"""
    eq = effect_equiv({SPEED_AXIS: 20.0}, {"enabled": True})
    assert eq["unknown"] == []
    assert eq["output_pct"] == 20.0
    assert eq["survival_pct"] == 0.0
    assert eq["equiv_pct"] > 0.0          # 几何合成为 (√1.2−1)×100 ≈ 9.54


def test_d3_speed_weight_is_overridable() -> None:
    """权表仍可逐键覆盖（坐标可配，不是写死）。"""
    cfg = {"enabled": True, "axis_weights": {SPEED_AXIS: {"calib": 10.0, "output": 5.0}}}
    assert effect_equiv({SPEED_AXIS: 20.0}, cfg)["output_pct"] == 10.0


def test_d4_speed_weight_default_inert() -> None:
    """缺省（未启用闸）→ 速度轴不影响任何数值（缺省零变化）。"""
    assert effect_equiv({SPEED_AXIS: 20.0}, None)["equiv_pct"] == 0.0


# =====================================================================================
# E · m1 flake 根治：布尔字面量走 Python 快路径（不 spawn Node）+ watchdog 容差放宽
# =====================================================================================
def test_e1_boolean_literals_are_fast_path_deterministic() -> None:
    """`evaluate("true"/"false")` 不再降级 Node：结果确定且无 `eval_failed` 警告。

    修复前：`true`/`false` 被 Python 快路径拒（`ast.Name` 不在白名单）→ 每次 spawn Node；
    Node vm watchdog 在 30ms 预算下 ~2%~12% 误报 `ERR_SCRIPT_EXECUTION_TIMEOUT` →
    `eval_failed:runner_fatal` → 兜底 0.0 → `evaluate("true")==1.0` 全量偶发红。
    大量重复执行即回归探针（修复前 200 次几乎必现，修复后 0 次）。
    """
    from qbot_rpg.core.formula_engine import EvaluatorCtx, evaluate, evaluate_detail

    ctx = EvaluatorCtx(attacker={}, target={}, battle={}, rng_state=1)
    for _ in range(200):
        assert evaluate("true", ctx) == 1.0
        assert evaluate("false", ctx) == 0.0
    v, w = evaluate_detail("true", ctx)
    assert v == 1.0 and not any(str(x).startswith("eval_failed") for x in w)
    v2, w2 = evaluate_detail("false", ctx)
    assert v2 == 0.0 and not any(str(x).startswith("eval_failed") for x in w2)


def test_e2_boolean_fast_path_does_not_change_mixed_js_semantics() -> None:
    """只接管**根节点**布尔字面量：参与运算仍走 Node，保 JS 数值强制转换语义。"""
    from qbot_rpg.core.formula_engine import EvaluatorCtx, evaluate_detail

    ctx = EvaluatorCtx(attacker={}, target={}, battle={}, rng_state=1)
    # JS：true + 1 === 2；true == 1 === true。若快路径误接管会得 Python 语义（0）。
    assert evaluate_detail("true + 1", ctx)[0] == 2.0
    assert evaluate_detail("true == 1", ctx)[0] == 1.0


def test_e3_vm_watchdog_slack_widened_for_scheduling_jitter() -> None:
    """根因修复证据：有效 vm 预算 30ms → 100ms（10ms 执行契约字面值不变）。"""
    from qbot_rpg.core import formula_engine as fe

    assert fe.FORMULA_TIMEOUT_MS == 10                       # 执行预算契约不变
    assert fe._VM_EFFECTIVE_TIMEOUT_MS == 100  # noqa: SLF001  # 抖动容差放宽
    assert fe._VM_EFFECTIVE_TIMEOUT_MS == fe.FORMULA_TIMEOUT_MS + fe._VM_CTX_SLACK_MS  # noqa: SLF001


def test_e4_boolean_path_does_not_invoke_node(monkeypatch: Any) -> None:
    """机制证据：布尔字面量**根本不调用** Node 运行器（钉死 `_invoke_runner` 不被触发）。"""
    from qbot_rpg.core import formula_engine as fe

    def _boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("布尔字面量不应触发 Node 回退")

    monkeypatch.setattr(fe, "_invoke_runner", _boom)
    ctx = fe.EvaluatorCtx(attacker={}, target={}, battle={}, rng_state=1)
    assert fe.evaluate("true", ctx) == 1.0
    assert fe.evaluate("false", ctx) == 0.0
