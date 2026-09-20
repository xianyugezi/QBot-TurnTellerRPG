"""批56 · 行动速度轴（D2）+ 过量治疗（D4）验收测试。

依据：
  · `docs/深度打造_决策记录.md` §十五 D 组裁决（D2 = 行动速度 / D4 = 过量治疗按 E5）；
  · `特效整理设计_1_修正轴全集.md` X28（行动速度）/ X29（行动后摇，废弃）/ §4-E5（overheal）；
  · `特效整理设计_3_落点与分期.md` §二「批 51」（旧编号 = 本批批56）验收点①②⑤。

覆盖：
  A. 行动速度轴 `action_speed_pct`：>0 提速 / <0 迟缓（CTB 有效速度方向）；范围由包声明
     可配；未配置 → 逐字段零变化。后摇轴 `action_recovery_pct` **不登记/不实现**，
     内容声明 → 校验器**黄提示**（不硬拦）。
  B. 过量治疗 `overheal`（待补）。

纪律：测试只构造内存对象（不写任何真实内容包）；匿名 id（s_*）；数值/区间全由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Optional, Tuple

from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.data.gear_stats import (
    DEPRECATED_EFFECT_AXES,
    EFFECT_AXES_KEY,
    GEAR_EFFECT_KEYS,
    effect_axis_value,
)

# 行动速度轴（键名唯一源 = effect_axis_spec；此处仅取登记名便于本测试引用）
SPEED_AXIS = "action_speed_pct"
RECOVERY_AXIS = "action_recovery_pct"

PLAYER: Dict[str, Any] = {
    "max_hp": 900, "hp": 900, "atk": 100, "dfn": 50, "spd": 10,
    "foc": 50, "con": 50, "lck": 50,
}
ENEMY: Dict[str, Any] = {
    "max_hp": 9000, "hp": 9000, "atk": 0, "dfn": 50, "spd": 8,
    "foc": 0, "con": 50, "lck": 0,
}


def _rules(report: Any) -> Tuple[list, list]:
    errs = [str(e.detail.get("rule")) for e in report.errors]
    warns = [str(w.detail.get("rule")) for w in report.warnings]
    return errs, warns


# ===========================================================================
# A · 行动速度轴（X28）
# ===========================================================================
def _run_speed(pct: float = 0.0, *, axes: Optional[Mapping[str, Any]] = None,
               side: str = "player") -> Tuple[float, float]:
    """跑一场（同种子），返回该侧 (effective_speed, next_ready)。"""
    cfg = {EFFECT_AXES_KEY: dict(axes)} if axes is not None else None
    eng = BattleEngine(config=cfg)
    p = dict(PLAYER)
    e = dict(ENEMY)
    target = p if side == "player" else e
    if pct:
        target[SPEED_AXIS] = pct
    eng.start(p, e, random_seed=1)
    view = eng._ctb.get_actor(side)  # noqa: SLF001
    assert view is not None
    return float(view.effective_speed), float(view.next_ready)


def test_a1_action_speed_registered_and_recovery_not_registered() -> None:
    """D2：只登记 action_speed_pct；action_recovery_pct 不登记、进废弃表。"""
    assert SPEED_AXIS in GEAR_EFFECT_KEYS
    assert RECOVERY_AXIS not in GEAR_EFFECT_KEYS
    assert DEPRECATED_EFFECT_AXES[RECOVERY_AXIS][0] == SPEED_AXIS


def test_a2_action_speed_bidirectional_and_zero_change() -> None:
    """>0 提速（有效速度↑ / next_ready↓）；<0 迟缓；0/未配置 = 原值（零变化）。"""
    spd0, ready0 = _run_speed(0.0)
    spdp, readyp = _run_speed(20.0)
    spdn, readyn = _run_speed(-20.0)
    # 0 / 未配置 → 有效速度 = 白值 spd（10），next_ready = recovery*100/10 = 1000
    assert spd0 == 10.0
    assert ready0 == 1000.0
    # +20 → ×1.2 = 12 → next_ready 变快
    assert spdp == 12.0
    assert readyp == 1000.0 / 1.2
    assert readyp < ready0
    # −20 → ×0.8 = 8 → next_ready 变慢
    assert spdn == 8.0
    assert readyn == 1000.0 / 0.8
    assert readyn > ready0


def test_a3_action_speed_range_is_declaration_driven() -> None:
    """范围可配：包声明收窄区间 → 消费点读声明钳制（不是写死）。"""
    spd_wide, _ = _run_speed(100.0)                       # 缺省 max=400 → ×2.0
    assert spd_wide == 20.0
    spd_clamped, _ = _run_speed(100.0, axes={SPEED_AXIS: {"min": -10, "max": 10}})
    assert spd_clamped == 11.0                            # 钳到 +10 → ×1.1
    # effect_axis_value 是同一读点（直接对拍钳制）
    assert effect_axis_value({SPEED_AXIS: 100.0}, SPEED_AXIS,
                             {SPEED_AXIS: {"min": -10, "max": 10}}) == 10.0
    assert effect_axis_value({SPEED_AXIS: 100.0}, SPEED_AXIS, None) == 100.0


def test_a4_action_speed_applies_to_enemy_side_too() -> None:
    """双向/双侧同构：轴取自**行动者**自身 combatant（敌侧同理）。"""
    spd_e, _ = _run_speed(0.0, side="enemy")
    spd_e20, _ = _run_speed(20.0, side="enemy")
    assert spd_e == 8.0 and spd_e20 == 8.0 * 1.2


def test_a5_no_axis_key_on_combatant_when_unconfigured() -> None:
    """缺省零变化：未配置 → 战斗快照 combatant 不含任何特效轴键。"""
    eng = BattleEngine()
    eng.start(dict(PLAYER), dict(ENEMY), random_seed=1)
    keys = set(eng._combat("player"))  # noqa: SLF001
    assert not (keys & set(GEAR_EFFECT_KEYS))


def test_a6_declaring_recovery_axis_is_yellow_hint_not_block() -> None:
    """D2：内容声明后摇轴 → 黄提示「已废弃，请改用行动速度」，不硬拦。"""
    rep = check_pack({"settings": {"effect_axes": {RECOVERY_AXIS: {"min": -80, "max": 400}}}})
    errs, warns = _rules(rep)
    assert not errs, errs
    assert "effect_axis_deprecated" in warns, warns
    # 消息里点名替代轴（不写死模块名/字段名，仅断言登记表给出的替代轴）
    msg = " ".join(str(w.detail.get("msg", "")) for w in rep.warnings)
    assert SPEED_AXIS in msg
    # 词条侧同样黄提示（不被静默忽略）
    rep2 = check_pack({"items": [{"id": "s_x", RECOVERY_AXIS: -20}]})
    errs2, warns2 = _rules(rep2)
    assert not errs2, errs2
    assert "effect_axis_deprecated" in warns2, warns2


def test_a7_registered_speed_axis_value_out_of_range_still_red() -> None:
    """已登记轴仍受越界红拦保护（废弃表不放松既有门禁）。"""
    rep = check_pack({"settings": {"effect_axes": {SPEED_AXIS: {"min": 50, "max": -50}}}})
    assert "effect_axis_range_inverted" in _rules(rep)[0]
