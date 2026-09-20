"""批70 · 「登记了却不生效」清账——接线类验收（X01 造成伤害轴 / X20 状态时长轴）。

背景（`审计4_勿增实体_死实体与空转.md` §2.1 R1/R2/R3 + §2.3 R6/R7/R8）：
    `damage_dealt_pct` / `status_duration_pct` / `status_duration_taken_pct` 三条轴
    **登记齐全 + 已进战斗桥 + 框架预设已发给作者**，但 `core/` 零读取 →
    作者写「弱点增伤 / 抗控 / 延长状态」数值不变（对作者是欺骗）。本批补消费点。

覆盖：
  A. X01 `damage_dealt_pct`（唯一收口 `battle._damage_dealt_mult`）：双向；声明区间钳制；
     旧键 `weakness_dmg_pct` 经战斗桥 pct 层归并等价；未配置零变化。
  B. X20 `status_duration_pct`（source）/ `status_duration_taken_pct`（target）：
     同一收口 `apply_status` 建实例处；turns/charges 双维缩放；永久维（−1）不动；
     存量实例不追改（仅新施加）；未配置零变化。

纪律：测试只构造内存对象（不写任何真实内容包）；数值/区间由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.effects import (
    STATUS_DURATION_AXIS,
    STATUS_DURATION_TAKEN_AXIS,
    DamageCtx,
    EffectRuntime,
)
from qbot_rpg.data.gear_stats import (
    EFFECT_AXES_KEY,
    combatant_updates,
    extract_bonus,
    route_bonus_into,
)

BP = "player"
BN = "enemy"

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 0,
          "mag": 50, "spd": 50, "foc": 100, "con": 0, "str": 100, "int": 80, "agi": 50,
          "spr": 0, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400000, "hp": 400000, "max_mp": 0, "mp": 0, "atk": 0, "dfn": 0,
         "mag": 0, "spd": 40, "foc": 0, "con": 0, "str": 0, "int": 0, "agi": 40,
         "spr": 0, "lck": 0, "elem_atk": 0, "name": "E"}


# ===========================================================================
# A · X01 造成伤害轴（damage_dealt_pct）＋ weakness_dmg_pct 归并
# ===========================================================================
def _run_dealt(extra_attacker: Mapping[str, Any], *, axes: Any = None) -> int:
    """打一发普攻，返回终伤；extra 加到**攻击方** combatant（唯一收口读攻击方轴）。"""
    cfg = {EFFECT_AXES_KEY: axes} if axes is not None else None
    eng = BattleEngine(config=cfg).start(dict(PLAYER, **dict(extra_attacker)),
                                         dict(ENEMY), random_seed=7)
    return eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0}).final_damage


def test_a1_damage_dealt_bidirectional() -> None:
    """`+25` → 终伤 ×1.25（增伤）；`−25` → ×0.75（削伤）；`0` → 原值。"""
    base = _run_dealt({})
    assert base > 0
    assert _run_dealt({"damage_dealt_pct": 25}) == int(round(base * 1.25))
    assert _run_dealt({"damage_dealt_pct": -25}) == int(round(base * 0.75))
    assert _run_dealt({"damage_dealt_pct": 0}) == base


def test_a2_damage_dealt_range_is_declaration_driven() -> None:
    """读时按 `settings.effect_axes` 声明区间钳制：声明 min=−10 → 轴 −50 被钳为 −10（×0.9）。"""
    base = _run_dealt({})
    got = _run_dealt({"damage_dealt_pct": -50},
                     axes={"damage_dealt_pct": {"min": -10, "max": 1000}})
    assert got == int(round(base * 0.9))


def test_a3_damage_dealt_headroom_is_multiplier_not_attack() -> None:
    """是「终伤乘区」而非属性乘区：轴 +100 → 终伤翻倍（不是加 flat 攻击的线性值）。"""
    base = _run_dealt({})
    assert _run_dealt({"damage_dealt_pct": 100}) == int(round(base * 2.0))


def test_a4_weakness_legacy_alias_folds_into_dealt_axis() -> None:
    """旧键 `weakness_dmg_pct` 归并证据：pct 层 → `combatant_updates` 折入 `damage_dealt_pct`
    一次（不双计）；未带旧键 → 不新增该键（零变化）。"""
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into(extract_bonus({"weakness_dmg_pct": 25}), flat, pct)
    assert pct == {"weakness_dmg": 25.0}
    assert "weakness_dmg_pct" not in flat
    assert combatant_updates(flat, pct).get("damage_dealt_pct") == 25.0
    # 未配置别名 → 战斗桥不产生该轴键（逐字段零变化）
    assert "damage_dealt_pct" not in combatant_updates({"atk": 3.0}, {})


def test_a5_damage_dealt_zero_change_when_absent() -> None:
    """零变化对拍（红线 C1）：未配置轴 → combatant 无该键；战斗级与基线逐值一致。"""
    base = _run_dealt({})
    assert _run_dealt({}, axes={}) == base          # 显式空声明段 = 缺省
    eng = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=7)
    mult, detail = eng._damage_dealt_mult(BP)
    assert mult == 1.0 and detail == {"damage_dealt_pct": 0.0}


# ===========================================================================
# B · X20 状态时长轴（dealt / received）——唯一收口 apply_status 建实例处
# ===========================================================================
class _Def:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def _status_def(sid: str, *, turns: int = 3, charges: int = 0,
                frame: str = "single", max_stack: int = 5) -> _Def:
    return _Def({
        "id": sid, "name": sid, "class": "status", "category": "weak",
        "stack_frame": frame, "max_stack": max_stack, "hit_rate": 100,
        "duration": {"turns": turns, "charges": charges},
        "actions": [{"type": "stat_modifier", "stat": "atk", "value": 10}],
    })


def _rt(defs: Mapping[str, Any], *, axes: Any = None) -> EffectRuntime:
    return EffectRuntime(
        status_state={BP: [], BN: []},
        defs=dict(defs),
        config=({EFFECT_AXES_KEY: axes} if axes is not None else None),
    )


def _ctx(*, bp_extra: Any = None, bn_extra: Any = None, rng: float = 0.1,
         source: str = BP, target: str = BN) -> DamageCtx:
    snap: Dict[str, Any] = {BP: {"max_hp": 1000, "hp": 1000},
                            BN: {"max_hp": 1000, "hp": 1000}}
    snap[source] = {**snap.get(source, {}), **dict(bp_extra or {})}
    snap[target] = {**snap.get(target, {}), **dict(bn_extra or {})}
    return DamageCtx(raw_damage=0, attack_type="skill", attacker=source,
                     target=target, snapshot=snap, variables={})


class _FixedRNG:
    def random(self) -> float:
        return 0.0


def _apply(rt: EffectRuntime, sid: str, ctx: DamageCtx) -> Any:
    ctx.variables["rng"] = _FixedRNG()
    return rt.apply_status(sid, ctx.target, source=ctx.attacker,
                           attacker=ctx.attacker, ctx=ctx)


def test_b1_duration_dealt_extends_new_instance() -> None:
    """`+100`（source 侧）→ 新实例 turns 3→6；`−50` → 3→2。"""
    d = {"s_x": _status_def("s_x")}
    r = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: 100}))
    assert r.applied and r.instance["turns"] == 6
    r2 = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: -50}))
    assert r2.instance["turns"] == 2   # round(3 × 0.5) = 2


def test_b2_duration_taken_shrinks_on_target_side() -> None:
    """`−100`（target 侧「我承受的」）→ 新实例 turns 下钳 1（抗控）。"""
    d = {"s_x": _status_def("s_x")}
    r = _apply(_rt(d), "s_x", _ctx(bn_extra={STATUS_DURATION_TAKEN_AXIS: -100}))
    assert r.applied and r.instance["turns"] == 1
    r2 = _apply(_rt(d), "s_x", _ctx(bn_extra={STATUS_DURATION_TAKEN_AXIS: 100}))
    assert r2.instance["turns"] == 6


def test_b3_duration_both_sides_multiply_once() -> None:
    """两侧实例各取一次、**相乘一次**：+50 且 +50 → round(3×1.5×1.5)=7（不是 ×1.5 或 ×2）。"""
    d = {"s_x": _status_def("s_x")}
    r = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: 50},
                                   bn_extra={STATUS_DURATION_TAKEN_AXIS: 50}))
    assert r.instance["turns"] == 7


def test_b4_duration_scales_charges_dimension() -> None:
    """持续双维一起缩放：charges 3 → +100 → 6；下钳 1（不产生 0 次状态）。"""
    d = {"s_x": _status_def("s_x", turns=1, charges=3)}
    r = _apply(_rt(d), "s_x", _ctx(bn_extra={STATUS_DURATION_TAKEN_AXIS: 100}))
    assert r.instance["charges"] == 6
    r2 = _apply(_rt(d), "s_x", _ctx(bn_extra={STATUS_DURATION_TAKEN_AXIS: -100}))
    assert r2.instance["charges"] == 1


def test_b5_duration_permanent_dim_untouched() -> None:
    """永久维（`-1` = 永不被清）不缩放：+100 仍是 −1（「永久」乘任何系数仍是永久）。"""
    d = {"s_x": _status_def("s_x", turns=-1)}
    r = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: 100}))
    assert r.instance["turns"] == -1


def test_b6_duration_zero_change_when_absent() -> None:
    """零变化对拍（红线 C1）：未配置两轴 → turns/charges 与接线前逐字段一致。"""
    d = {"s_x": _status_def("s_x", charges=2)}
    r = _apply(_rt(d), "s_x", _ctx())
    assert r.instance["turns"] == 3 and r.instance["charges"] == 2
    r2 = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: 0},
                                    bn_extra={STATUS_DURATION_TAKEN_AXIS: 0}))
    assert r2.instance["turns"] == 3 and r2.instance["charges"] == 2


def test_b7_duration_range_is_declaration_driven() -> None:
    """读时按声明区间钳制：声明 max=10 → 轴 +300 被钳为 +10（×1.1）→ round(10×1.1)=11。"""
    d = {"s_x": _status_def("s_x", turns=10)}
    r = _apply(_rt(d), "s_x",
               _ctx(bp_extra={STATUS_DURATION_AXIS: 300}))
    # 缺省区间 max=300 → ×4 → 40
    assert r.instance["turns"] == 40
    r2 = _apply(_rt(d, axes={"status_duration_pct": {"min": -80, "max": 10}}),
                "s_x", _ctx(bp_extra={STATUS_DURATION_AXIS: 300}))
    assert r2.instance["turns"] == 11


def test_b8_duration_renewal_uses_scaled_turns_not_retroactive() -> None:
    """只影响新施加实例：既有实例经 S5 强覆盖重置时用**缩放后**的时长，不改历史数值。"""
    d = {"s_x": _status_def("s_x")}
    rt = _rt(d)
    ctx = _ctx(bp_extra={STATUS_DURATION_AXIS: 100})
    first = _apply(rt, "s_x", ctx)
    assert first.instance["turns"] == 6
    # 手动把存量改短，再同源同强覆盖 → 重置为缩放后时长（6），而不是存量值
    first.instance["turns"] = 1
    again = _apply(rt, "s_x", ctx)
    assert again.applied and again.instance["turns"] == 6
