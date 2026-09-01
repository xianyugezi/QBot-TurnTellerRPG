"""M13 6c 组合结算执行引擎（细化_6c §2.4 F-C2 + 可达性 RE）。

文件名：combo_settle.py
创建时间：2026-09-02
依据：docs/细化/细化_6c_资源轴与职业机制.md（497 行 v1.0）：
  - F-C2 组合结算：按锁定组合行执行——双耗 MP+能量、行为随组合变化
    （kind/power/element/hits/effects）；
  - 可达性 RE：统计当前技能集可达组合数；
  - D-02 先匹配后消耗（CM-2）。

功能描述：
  - settle_combo(ctx, combo_row, *, mp_cost, energy_cost, side) 组合结算入口：
      双耗检查（MP + 能量池）→ 扣减（原子）→ 行为执行（行参数经注入执行器）；
  - reachable_combos(ctx, skill, axis_id) 可达性统计；
  - 引擎注入模式（mp_check/mp_pay/energy_check/energy_pay/effect_runner 注入，
    缺省 None → 只结算登记不执行——战斗层接线后注入）。

工程补白（契约/细化未显式定义处的实现口径，显式标注供审查）：
  P-1  双耗检查顺序：先 MP 后能量（MP 不足直接拒，不查能量）；
  P-2  行为执行经 effect_runner 注入（缺省 None → 只登记行为参数，不执行）；
  P-3  可达性 = 当前技能集（技能 def combo_table 行）中能量池满足的行数。

铁律：零 NoneBot import；G0：core 层零 import content（技能/能量数据经
ctx 注入）；零定时器/零睡眠；纯函数确定性；不 git commit。
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Mapping, Optional

from qbot_rpg.core.combo_table import (
    ComboRow,
    match_combos,
    pool_values_of,
    row_cost_plan,
    rows_of,
)

# =====================================================================================
# 常量
# =====================================================================================

# 双耗键（组合行 cost 段）
COST_MP: str = "mp"
COST_ENERGY: str = "energy"


# =====================================================================================
# 组合结算
# =====================================================================================


def settle_combo(
    ctx: Mapping[str, Any],
    row: ComboRow,
    *,
    axis_id: str = "element_energy",
    side: str = "player",
    mp_cost: int = 0,
    mp_check: Optional[Callable[[Mapping[str, Any], int], bool]] = None,
    mp_pay: Optional[Callable[[Mapping[str, Any], int], None]] = None,
    energy_check: Optional[Callable[[Mapping[str, Any], str, Mapping[str, int]], bool]] = None,
    energy_pay: Optional[Callable[[Mapping[str, Any], str, Mapping[str, int]], None]] = None,
    effect_runner: Optional[Callable[[Mapping[str, Any], Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """F-C2 组合结算（双耗 MP+能量 + 行为随组合变化）。

    流程：
      1. 双耗检查（P-1：先 MP 后能量）——任一不足 → 被拒不耗（ok=False）；
      2. 扣减（原子：先 check 后 pay，不半扣）；
         - 能量扣减 = row_cost_plan(row)（组合多重集逐池出现次数，RS-6 池级原子）；
      3. 行为执行（effect_runner 注入；缺省只登记行为参数）。

    返回 {ok, reason, mp_cost, energy_cost, behavior, events} 契约：
      behavior = {kind, power, element, hits, effects}（行参数）。
    """
    # 能量扣减方案 = 组合行池分布（CM-2/F-C2 ①：row_cost_plan）
    plan = row_cost_plan(row)
    energy_cost: Dict[str, int] = {p["pool"]: int(p["amount"]) for p in plan}

    # 1. 双耗检查（先 MP 后能量）
    if mp_cost > 0 and mp_check is not None:
        if not mp_check(ctx, mp_cost):
            return {"ok": False, "reason": "mp_insufficient",
                    "mp_cost": mp_cost, "energy_cost": energy_cost,
                    "behavior": _row_behavior(row), "events": []}
    if energy_cost and energy_check is not None:
        if not energy_check(ctx, axis_id, dict(energy_cost)):
            return {"ok": False, "reason": "energy_insufficient",
                    "axis": axis_id, "mp_cost": mp_cost,
                    "energy_cost": energy_cost,
                    "behavior": _row_behavior(row), "events": []}

    # 2. 扣减（原子）
    events: List[Dict[str, Any]] = []
    if mp_cost > 0 and mp_pay is not None:
        mp_pay(ctx, mp_cost)
        events.append({"type": "mp_cost", "amount": mp_cost})
    if energy_cost and energy_pay is not None:
        energy_pay(ctx, axis_id, dict(energy_cost))
        events.append({"type": "energy_cost", "axis": axis_id, "amount": energy_cost})

    # 3. 行为执行
    behavior = _row_behavior(row)
    if effect_runner is not None:
        res = effect_runner(ctx, behavior)
        events.append({"type": "behavior", "ok": bool(getattr(res, "ok", True))})
    else:
        events.append({"type": "behavior", "ok": None, "skipped": "runner_not_injected"})

    return {"ok": True, "reason": "", "mp_cost": mp_cost,
            "energy_cost": energy_cost, "behavior": behavior,
            "events": events}


def _row_behavior(row: ComboRow) -> Dict[str, Any]:
    """组合行行为参数（kind/power/element/hits/effects——行为随组合变化）。"""
    return {
        "kind": getattr(row, "kind", None),
        "power": getattr(row, "power", 0),
        "element": getattr(row, "element", None),
        "hits": getattr(row, "hits", 1),
        "effects": list(getattr(row, "effects", []) or []),
    }


# =====================================================================================
# 可达性统计（RE）
# =====================================================================================

def reachable_combos(
    ctx: Mapping[str, Any],
    skill: Mapping[str, Any],
    axis_id: str,
    *,
    side: str = "player",
) -> List[Dict[str, Any]]:
    """可达性 RE：当前技能集（skill def combo_table 行）中能量池满足的行。

    返回可达行摘要列表 [{combo, name, reason}]；无组合表段 → []（B-3 常规放行）。
    """
    rows = rows_of(skill)
    if not rows:
        return []
    # 从行收集池名（组合键 = 池名，combo_counts 键）
    pools: List[str] = []
    for row in rows:
        counts = getattr(row, "combo_counts", None)
        if isinstance(counts, Mapping):
            pools.extend(str(p) for p in counts.keys() if isinstance(p, str))
    pool_values = pool_values_of(ctx, axis_id, tuple(pools), side=side)
    matched = match_combos(rows, pool_values)
    out: List[Dict[str, Any]] = []
    for row in matched:
        out.append({
            "combo": getattr(row, "combo", None),
            "name": getattr(row, "name", None),
            "reason": "pool_match",
        })
    return out


__all__ = [
    "COST_MP", "COST_ENERGY",
    "settle_combo", "reachable_combos",
]
