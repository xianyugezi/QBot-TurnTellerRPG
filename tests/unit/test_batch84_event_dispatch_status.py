"""批84 · B1：事件时点「派发状态」唯一源（`EVENT_POINT_TABLE`）回归。

依据：`docs/Vibecoding说明书.md` §二 D（**静默死效果**：合法枚举 + 无派发点 →
校验器静默通过）+ `docs/审查/审计与方案/API手册_2_事件与扩展点.md` §2.2。

覆盖：
  1. `EVENT_POINTS` 由 `EVENT_POINT_TABLE` 派生（值/顺序与前 16 + on_kill 逐字一致）；
  2. `dispatched` 逐点与**生产代码实际派发点**一致（自证式：扫源码字面量）；
  3. 批81 `turn_end` 补点后 = 12 点有派发 / 5 点二期未接；
  4. `core.event_dispatcher` 再导出与新入口一致（兼容旧 import 路径）。
"""
from __future__ import annotations

import re
from pathlib import Path

from qbot_rpg.data import event_points as src

_REPO = Path(__file__).resolve().parents[2]
_QBOT = _REPO / "qbot_rpg"

#: 生产派发调用的字面量时点：`_dispatch_event("x", ...)` / `_dispatch_status_event("x", ...)`
_DISPATCH_RE = re.compile(
    r"_dispatch_(?:status_)?event\(\s*[\"']([a-z_]+)[\"']"
)

#: 上述 12 点有真实派发点（批84 逐点 grep 核实；**以代码为准**）
_EXPECTED_DISPATCHED = (
    "battle_start", "battle_end", "action_start", "action_end",
    "turn_start", "turn_end", "status_gain", "status_lose",
    "death", "revive", "season_change", "on_kill",
)
#: 合法枚举但无派发点（二期）：写了永不触发
_EXPECTED_PHASE2 = ("mark_gain", "mark_lose", "on_attack", "on_hit", "on_skill")

_LEGACY_16 = (
    "battle_start", "battle_end",
    "action_start", "action_end",
    "turn_start", "turn_end",
    "status_gain", "status_lose",
    "mark_gain", "mark_lose",
    "death", "revive",
    "on_attack", "on_hit", "on_skill",
    "season_change",
)


def _production_dispatch_literals() -> set:
    found = set()
    for path in _QBOT.rglob("*.py"):
        found.update(_DISPATCH_RE.findall(path.read_text(encoding="utf-8")))
    return found


def test_event_points_derived_from_table_same_order() -> None:
    assert src.EVENT_POINTS == tuple(p.name for p in src.EVENT_POINT_TABLE)
    assert len(src.EVENT_POINTS) == 17
    assert src.EVENT_POINTS[:16] == _LEGACY_16
    assert src.EVENT_POINTS[16] == "on_kill"
    assert len(set(src.EVENT_POINTS)) == 17


def test_dispatched_flag_matches_production_code() -> None:
    """唯一源 `dispatched` **必须**与生产代码实际派发点一致（防文档/代码漂移）。"""
    actual = _production_dispatch_literals()
    declared_live = {p.name for p in src.EVENT_POINT_TABLE if p.dispatched}
    declared_phase2 = {p.name for p in src.EVENT_POINT_TABLE if not p.dispatched}
    assert declared_live == actual, (
        f"dispatched 与生产派发点不一致：declared-live={sorted(declared_live)} "
        f"actual={sorted(actual)}")
    # 二期点不得被误标为有派发点（反向：declared_live 只在 EVENT_POINTS 内）
    assert declared_live | declared_phase2 == set(src.EVENT_POINTS)


def test_expected_live_and_phase2_sets() -> None:
    assert {p.name for p in src.EVENT_POINT_TABLE if p.dispatched} == \
        set(_EXPECTED_DISPATCHED)
    assert src.undispatched_points() == _EXPECTED_PHASE2
    assert src.is_dispatched("turn_end") is True          # 批81·A1 补点
    assert src.is_dispatched("mark_gain") is False
    assert src.is_dispatched("on_hit") is False
    assert src.is_dispatched("不存在") is False            # 未知 → False


def test_status_event_subset_all_dispatched() -> None:
    for point in src.STATUS_EVENT_POINTS:
        assert point in src.EVENT_POINTS
        assert src.is_dispatched(point) is True


def test_core_reexport_is_same_single_source() -> None:
    from qbot_rpg.core import event_dispatcher as ed

    assert ed.EVENT_POINTS == src.EVENT_POINTS
    assert ed.EVENT_POINT_TABLE == src.EVENT_POINT_TABLE
    assert ed.EVENT_POINT_INDEX is not None
    assert ed.is_dispatched("status_lose") is True
    assert ed.undispatched_points() == src.undispatched_points()
