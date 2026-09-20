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
     并钉死 vm watchdog 容差常量已放宽（30ms → 100ms）。

纪律：只构造内存对象（不写任何真实内容包）；匿名 id（`s_*`）；数值/区间全由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.data.gear_stats import (
    DEFAULT_EFFECT_AXES,
    EFFECT_AXIS_SPECS,
    EFFECT_CONSUMER_PENDING,
    EFFECT_TO_COMBATANT,
    GEAR_EFFECT_KEYS,
    combatant_updates,
    effect_axis_value,
)

REWARD_AXIS = "reward_mult_pct"
SPEED_AXIS = "action_speed_pct"


def _spec(axis: str) -> Mapping[str, Any]:
    return next(s for s in EFFECT_AXIS_SPECS if str(s["axis"]) == axis)


def _rules(rep: Any) -> Tuple[str, ...]:
    return tuple(str(e.kind) for e in rep.errors)


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
