"""M13 6c 组合结算执行单测（tests/unit/test_combo_settle.py · M13 批11 路11B）。

覆盖细化_6c §2.4 F-C2：
  - 双耗检查（MP + 能量池，先 MP 后能量）
  - 扣减（原子：先 check 后 pay）
  - 行为随组合变化（kind/power/element/hits/effects）
  - 可达性 RE 统计

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.core.combo_settle import reachable_combos, settle_combo
from qbot_rpg.core.combo_table import ComboRow


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _row(**over: Any) -> ComboRow:
    raw: Dict[str, Any] = {
        "combo": ["fire", "fire", "water"],
        "name": "蒸汽冲击",
        "kind": "damage",
        "power": 200,
        "element": "fire",
        "hits": 2,
        "effects": [{"type": "damage", "power": 100}],
    }
    raw.update(over)
    return ComboRow(raw)


def _skill(**over: Any) -> Dict[str, Any]:
    s: Dict[str, Any] = {"id": "steam", "name": "蒸汽", "combo_table": [_row().raw]}
    s.update(over)
    return s


# ---------------------------------------------------------------------------
# 双耗检查
# ---------------------------------------------------------------------------
def test_settle_ok_with_checks_and_pays() -> None:
    """双耗检查+扣减全通过 → ok=True + 事件含 mp/energy/behavior。"""
    events: List[str] = []
    mp_checked: List[int] = []
    energy_checked: List[tuple] = []

    def mp_check(ctx: Any, cost: int) -> bool:
        mp_checked.append(cost)
        return True

    def mp_pay(ctx: Any, cost: int) -> None:
        events.append(f"mp:{cost}")

    def energy_check(ctx: Any, axis: str, cost: Dict[str, int]) -> bool:
        energy_checked.append((axis, cost))
        return True

    def energy_pay(ctx: Any, axis: str, cost: Dict[str, int]) -> None:
        events.append(f"energy:{axis}:{cost}")

    def effect_runner(ctx: Any, behavior: Dict[str, Any]) -> Any:
        events.append(f"behavior:{behavior['kind']}")
        return type("R", (), {"ok": True})()

    r = settle_combo(
        {}, _row(), mp_cost=16,
        mp_check=mp_check, mp_pay=mp_pay,
        energy_check=energy_check, energy_pay=energy_pay,
        effect_runner=effect_runner,
    )
    assert r["ok"] is True
    assert mp_checked == [16]
    assert len(energy_checked) == 1
    assert energy_checked[0][1] == {"fire": 2, "water": 1}
    assert events[0] == "mp:16"
    assert events[1].startswith("energy:element_energy:")
    assert events[2] == "behavior:damage"


def test_settle_mp_insufficient_rejected() -> None:
    """MP 不足 → 被拒不耗（先 MP 后能量——energy 不查）。"""
    energy_checked: List[tuple] = []

    def mp_check(ctx: Any, cost: int) -> bool:
        return False

    def energy_check(ctx: Any, axis: str, cost: Dict[str, int]) -> bool:
        energy_checked.append((axis, cost))
        return True

    r = settle_combo({}, _row(), mp_cost=16, mp_check=mp_check, energy_check=energy_check)
    assert r["ok"] is False and r["reason"] == "mp_insufficient"
    assert energy_checked == [], "MP 不足不应查能量（P-1 先 MP）"


def test_settle_energy_insufficient_rejected() -> None:
    """能量不足 → 被拒不耗。"""
    paid: List[str] = []

    def mp_check(ctx: Any, cost: int) -> bool:
        return True

    def mp_pay(ctx: Any, cost: int) -> None:
        paid.append("mp")

    def energy_check(ctx: Any, axis: str, cost: Dict[str, int]) -> bool:
        return False

    r = settle_combo({}, _row(), mp_cost=16, mp_check=mp_check, mp_pay=mp_pay,
                     energy_check=energy_check)
    assert r["ok"] is False and r["reason"] == "energy_insufficient"
    assert paid == [], "被拒不应扣费"


def test_settle_behavior_follows_row() -> None:
    """行为参数随组合行变化（kind/power/element/hits/effects）。"""
    row = _row(power=300, kind="control", element="water", hits=3)
    r = settle_combo({}, row)
    assert r["behavior"]["kind"] == "control"
    assert r["behavior"]["power"] == 300
    assert r["behavior"]["element"] == "water"
    assert r["behavior"]["hits"] == 3
    assert r["behavior"]["effects"] == [{"type": "damage", "power": 100}]


def test_settle_no_runner_skips_behavior() -> None:
    """effect_runner 未注入 → behavior 只登记 skipped（不执行不阻断）。"""
    r = settle_combo({}, _row())
    assert r["ok"] is True
    assert r["events"][-1]["skipped"] == "runner_not_injected"


def test_settle_zero_mp_ok() -> None:
    """无 MP 消耗 → 直接 ok（能量仍按组合行池分布）。"""
    row = _row()
    r = settle_combo({}, row)
    assert r["ok"] is True
    assert r["mp_cost"] == 0
    assert r["energy_cost"] == {"fire": 2, "water": 1}


# ---------------------------------------------------------------------------
# 可达性 RE
# ---------------------------------------------------------------------------
def test_reachable_combos_pool_match() -> None:
    """能量池满足 → 可达行列表非空。"""
    ctx = {
        "stats": {
            "element_energy": {
                "name": "元素能量", "type": "element_energy", "base": 0,
                "max_per_pool": 3, "pools": ["fire", "water", "wind"],
            }
        },
        "resource_state": {
            "player": {"element_energy": {"fire": 3, "water": 2, "wind": 0}}
        }
    }
    skill = _skill()
    # 走引擎（内部从行收集 pools）
    out = reachable_combos(ctx, skill, "element_energy")
    assert len(out) >= 1, f"能量池满足应可达，got {out}"
    assert out[0]["reason"] == "pool_match"


def test_reachable_combos_empty_when_no_rows() -> None:
    """无组合表段 → []（B-3 常规放行）。"""
    ctx = {"resource_state": {"player": {"element_energy": {"fire": 3}}}}
    out = reachable_combos(ctx, {"id": "x", "name": "普攻"}, "element_energy")
    assert out == []
