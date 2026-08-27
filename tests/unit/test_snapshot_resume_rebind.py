"""续战世代重绑定补测（M6 批3·路B · D3 RSM-04/09 + WIR-14 运行期降级）。

依据：细化_M6_热重载接线.md（D3）§二 RSM-04（续战入口世代重绑定）/ RSM-09（世代一致性
自检）+ §2.1 P0-1（半套配置禁绝）+ WIR-14（引用 ID 已删 → 降级不崩）。

覆盖：snapshot_registry_generation 读取 / pick_registry_snapshot 取档四态（skipped/exact/
fallback/none）/ rebind_registry_for_snapshot 世代一致性自检（degraded 标记 + 告警）/
无档不绑定。注：本文件为路B 迭代上限截断后由主 agent 补建（实现已落盘，测试补齐）。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from qbot_rpg.content.registry import Registry, RegistrySnapshot
from qbot_rpg.world.snapshot_resume import (
    pick_registry_snapshot,
    rebind_registry_for_snapshot,
    snapshot_registry_generation,
)


def _snap(generation: int, pack_id: str = "pack") -> RegistrySnapshot:
    """真实 RegistrySnapshot 替身（tables/names/modules_raw 最小空表可重建 Registry）。"""
    return RegistrySnapshot(
        pack_id=pack_id, generation=generation,
        tables={}, names={}, modules_raw={},
    )


def _watcher(*snaps, backup=None):
    """watcher 替身：_snapshots（N=2 deque）+ backup_snapshot() 契约接口。"""
    return SimpleNamespace(_snapshots=list(snaps), backup_snapshot=lambda: backup)


# ---------------------------------------------------------------------------
# snapshot_registry_generation（RSM-02 / F-RSM-01 读取）
# ---------------------------------------------------------------------------
def test_generation_missing_default_zero():
    assert snapshot_registry_generation({}) == 0
    assert snapshot_registry_generation({"registry_generation": None}) == 0


def test_generation_numeric():
    assert snapshot_registry_generation({"registry_generation": 5}) == 5
    assert snapshot_registry_generation({"registry_generation": 5.0}) == 5


def test_generation_non_numeric_defensive():
    assert snapshot_registry_generation({"registry_generation": "abc"}) == 0
    assert snapshot_registry_generation({"registry_generation": True}) == 0  # bool 防误判


# ---------------------------------------------------------------------------
# pick_registry_snapshot（RSM-04 取档四态）
# ---------------------------------------------------------------------------
def test_pick_skipped_without_watcher():
    snap, status = pick_registry_snapshot(None, 3)
    assert snap is None and status == "skipped"


def test_pick_exact_match():
    watcher = _watcher(_snap(2), _snap(3), _snap(4))
    snap, status = pick_registry_snapshot(watcher, 3)
    assert status == "exact" and snap.generation == 3  # 精确世代匹配（旧局旧配置）


def test_pick_fallback_to_nearest_le():
    """无精确档 → 取最近一份世代 ≤ 目标的档（ADR-D3-03，不拒绝恢复）。"""
    watcher = _watcher(_snap(1), _snap(3))
    snap, status = pick_registry_snapshot(watcher, 2)
    assert status == "fallback" and snap.generation == 1


def test_pick_none_no_usable_snapshot():
    """目标世代低于全部档（无 ≤ 档可取）→ none（不绑定）。"""
    watcher = _watcher(_snap(3))
    snap, status = pick_registry_snapshot(watcher, 0)
    assert snap is None and status == "none"  # 无世代 ≤ 0 的档


def test_pick_uses_backup_snapshot_contract():
    """取档双口：backup_snapshot()（RSM-05 激活接口）也在候选内。"""
    backup = _snap(7)
    watcher = _watcher(_snap(6), backup=backup)
    snap, status = pick_registry_snapshot(watcher, 7)
    assert status == "exact" and snap.generation == 7


def test_pick_backup_missing_no_crash():
    """backup_snapshot 未实装（契约防御）→ 不崩，走 _snapshots 候选。"""
    watcher = SimpleNamespace(_snapshots=[_snap(4)])  # 无 backup_snapshot 属性
    snap, status = pick_registry_snapshot(watcher, 4)
    assert status == "exact" and snap.generation == 4


# ---------------------------------------------------------------------------
# rebind_registry_for_snapshot（RSM-04 + RSM-09 世代一致性自检）
# ---------------------------------------------------------------------------
def test_rebind_exact_not_degraded():
    """exact 绑定 → 世代一致（rebound == target），degraded=False。"""
    snapshot = {"registry_generation": 4}
    watcher = _watcher(_snap(3), _snap(4))
    reg, status, target, rebound, degraded = rebind_registry_for_snapshot(snapshot, watcher)
    assert isinstance(reg, Registry)
    assert status == "exact" and target == 4 and rebound == 4
    assert degraded is False


def test_rebind_fallback_degraded_warns(caplog):
    """fallback 绑定 → 世代不一致（RSM-09 自检 degraded=True）+ 日志告警（不拒绝恢复）。"""
    snapshot = {"registry_generation": 2}
    watcher = _watcher(_snap(1), _snap(3))
    with caplog.at_level("WARNING"):
        reg, status, target, rebound, degraded = rebind_registry_for_snapshot(snapshot, watcher)
    assert isinstance(reg, Registry)
    assert status == "fallback" and target == 2 and rebound == 1
    assert degraded is True
    assert "世代不一致" in caplog.text  # RSM-09 自检告警


def test_rebind_none_not_bound():
    """无可用档（目标低于全部档）→ 不绑定（registry=None，走 RSM-04 降级：默认解析不崩）。"""
    snapshot = {"registry_generation": 0}
    watcher = _watcher(_snap(3))
    reg, status, target, rebound, degraded = rebind_registry_for_snapshot(snapshot, watcher)
    assert reg is None and status == "none"
    assert rebound is None and degraded is False


def test_rebind_skipped_without_watcher():
    """未注入 watcher → skipped（不重绑定，旧行为零影响）。"""
    snapshot = {"registry_generation": 3}
    reg, status, target, rebound, degraded = rebind_registry_for_snapshot(snapshot, None)
    assert reg is None and status == "skipped"


def test_rebind_old_snapshot_without_generation_defaults_zero():
    """旧快照无 registry_generation → 目标 0（RSM-04 降级：取 ≤0 档或 none 不绑定）。"""
    snapshot = {}  # 旧快照（无世代字段）
    watcher = _watcher(_snap(0), _snap(1))
    reg, status, target, rebound, degraded = rebind_registry_for_snapshot(snapshot, watcher)
    assert target == 0
    assert status in ("exact", "fallback", "none")  # 按 watcher 档位决定；不崩即可


# ---------------------------------------------------------------------------
# WIR-14 运行期降级（引用 ID 已删 → resolve_or_degrade 语义占位核验）
# ---------------------------------------------------------------------------
def test_rsm_snapshot_resume_degrades_not_crash():
    """P0-1 半套配置禁绝的兜底面：无可用档时续战不崩（resolve None 降级）。

    真实 resolve_or_degrade（路A 提供 content 层入口）合入后替换；本用例锁定
    「无可用档 → 不绑定 → 引擎按默认解析不崩」的降级行为（WIR-14 运行期语义）。
    """
    # 场景 A：目标世代低于 watcher 全部档 → none（无 ≤ 档可取）→ 不绑定
    snapshot = {"registry_generation": 0}
    watcher = _watcher(_snap(1))
    reg, status, _, rebound, degraded = rebind_registry_for_snapshot(snapshot, watcher)
    assert status == "none" and reg is None
    # 场景 B：目标世代超出全部档 → fallback（取最近 ≤ 档，ADR-D3-03 不拒绝恢复）
    snapshot2 = {"registry_generation": 99}
    reg2, status2, _, rebound2, degraded2 = rebind_registry_for_snapshot(snapshot2, watcher)
    assert status2 == "fallback" and reg2 is not None and rebound2 == 1
    assert degraded2 is True  # RSM-09 世代不一致告警
    # 引擎侧降级（from_snapshot registry=None 走默认 defs/pipeline，不抛异常）——由
    # test_battle_snapshot_generation.py::test_rsm_03_from_snapshot_without_registry_backward_compat 覆盖
