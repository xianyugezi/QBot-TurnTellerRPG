"""6c 资源轴回合结清与生命周期引擎单测（tests/unit/test_resource_lifecycle.py · M13 批8 路8C）。

覆盖（细化_6c §1.3 机制 M3 · 流程 F-R1 + §1.4 快照 RS-1~6，对齐 TC-02~07）：
  1. 战斗开始：数值型置 base / 子池型各池置 base（F-R1 首行）
  2. 成功结算后 energy_gain 追加 + 封顶（数值型 ≤ max / 子池型每池 ≤ max_per_pool）
  3. 未命中不改（引擎不调用即不变，与 mark_add 同拍由接线方控制）
  4. 施放前 energy_cost 不足 → 被拒不耗回合（不增减、可反复尝试）
  5. 施放前 energy_cost 足 → 扣减成功
  6. 多资源同时增减（K4/K6）
  7. 0 值无操作（D-06）
  8. 被控 skip_turn 保留判定（S4）
  9. 回合结束结清：契约无每回合变化 → 保留（幂等钩子）
  10. 战斗结束 reset=battle → 清零（S5）
  11. 战斗结束 reset=keep → 跨战斗保留（RS-3）
  12. 战斗结束 reset=battle_start → 战斗内保留（下次战斗开始置 base）
  13. any 总量门（D-02）：足 → 逐池扣；不足 → 整体回滚被拒
  14. 快照导出/恢复 round-trip（数值型单键 + 子池型池级展开 D-04，RS-1/RS-2/RS-6）
  15. 已删注册轴恢复降级（RS-5）不报错
  16. 池级原子性：单池增减不整段覆盖（RS-6）

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；不碰兄弟文件。
"""

from __future__ import annotations

from typing import Any, Dict, MutableMapping

import pytest

from qbot_rpg.core.resource_lifecycle import (
    RESET_BATTLE,
    RESET_BATTLE_START,
    RESET_KEEP,
    RESOURCE_STATE_KEY,
    ResourceLifecycle,
)

# ---------------------------------------------------------------------------
# fixture：注册表（数值型 rage + 子池型 element_energy + keep/battle_start 型）
# ---------------------------------------------------------------------------

REGISTRY: Dict[str, Dict[str, Any]] = {
    "rage": {
        "name": "怒气", "type": "resource", "icon": "💢",
        "base": 0, "max": 100, "reset": "battle", "display": "status_line",
    },
    "element_energy": {
        "name": "元素能量", "type": "resource_custom",  # D-01b 兼容别名
        "base": 0, "max_per_pool": 3,
        "pools": ["fire", "water", "wind"],
        "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
        "display": "status_line",
    },
    "heat": {
        "name": "热量", "type": "resource", "base": 0, "max": 100,
        "reset": "keep", "display": "status_line",
    },
    "focus": {
        "name": "专注", "type": "resource", "base": 5, "max": 100,
        "reset": "battle_start", "display": "status_line",
    },
}


@pytest.fixture()
def lc() -> ResourceLifecycle:
    """生命周期引擎（注入注册表）。"""
    return ResourceLifecycle(REGISTRY)


@pytest.fixture()
def battle_state() -> Dict[str, Any]:
    """战斗快照骨架（per-side 容器）。"""
    return {"status": "active", "turn": 1, "player": {"hp": 500}, "enemy": {"hp": 500}}


def _side(bs: MutableMapping[str, Any], side: str = "player") -> MutableMapping[str, Any]:
    return bs[RESOURCE_STATE_KEY][side]


# ---------------------------------------------------------------------------
# ① 战斗开始（F-R1 首行）
# ---------------------------------------------------------------------------


def test_battle_start_init_numeric_and_pool(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """战斗开始：数值型置 base / 子池型各池置 base（【资源轴 L32/L46】）。"""
    lc.battle_start_init(battle_state, "player")
    assert _side(battle_state)["rage"] == 0
    assert _side(battle_state)["element_energy"] == {"fire": 0, "water": 0, "wind": 0}
    assert _side(battle_state)["focus"] == 5  # base=5（battle_start 型）
    # 覆盖战斗开始前残留值
    _side(battle_state)["rage"] = 80
    lc.battle_start_init(battle_state, "player")
    assert _side(battle_state)["rage"] == 0


def test_battle_start_init_axis_subset(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """战斗开始初始化仅作用于指定轴。"""
    lc.battle_start_init(battle_state, "player", axis_ids=["rage"])
    assert "rage" in _side(battle_state)
    assert "element_energy" not in _side(battle_state)


# ---------------------------------------------------------------------------
# ② 成功结算后 energy_gain 追加 + 封顶（F-R1 命中判定后）
# ---------------------------------------------------------------------------


def test_apply_gain_numeric_and_pool(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """energy_gain 追加：数值型 +15；子池型 fire +1（仅该池）。"""
    lc.battle_start_init(battle_state, "player")
    lc.apply_gain(battle_state, "player", {"rage": 15, "fire": 1})
    assert _side(battle_state)["rage"] == 15
    assert _side(battle_state)["element_energy"] == {"fire": 1, "water": 0, "wind": 0}


def test_apply_gain_cap_numeric(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """封顶：rage 95 + 15 → 100 封顶不再累计（TC-02③）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 95
    lc.apply_gain(battle_state, "player", {"rage": 15})
    assert _side(battle_state)["rage"] == 100


def test_apply_gain_cap_pool(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """每池封顶：fire 2 + 1 → 3 封顶（第 4 次不累计，TC-08②）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 0, "wind": 0}
    lc.apply_gain(battle_state, "player", {"fire": 1})
    assert _side(battle_state)["element_energy"]["fire"] == 3
    lc.apply_gain(battle_state, "player", {"fire": 1})
    assert _side(battle_state)["element_energy"]["fire"] == 3  # 超出不累计


def test_apply_gain_multi_axis_and_zero_noop(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """多资源同时增减（K4/K6）+ 0 值无操作（D-06）。"""
    lc.battle_start_init(battle_state, "player")
    lc.apply_gain(battle_state, "player", {"rage": 10, "heat": 5, "rage2": 0})
    assert _side(battle_state)["rage"] == 10
    assert _side(battle_state)["heat"] == 5
    before = dict(_side(battle_state))
    lc.apply_gain(battle_state, "player", {"rage": 0, "water": 0})
    assert _side(battle_state) == before  # 0 值无操作（D-06）


def test_apply_gain_unknown_axis_skipped(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """未注册键防御跳过（RS-5 精神；V1 红拦在加载期）。"""
    lc.battle_start_init(battle_state, "player")
    lc.apply_gain(battle_state, "player", {"not_registered": 5, "rage": 3})
    assert _side(battle_state)["rage"] == 3
    assert "not_registered" not in _side(battle_state)


# ---------------------------------------------------------------------------
# ③ 施放前 energy_cost 检查与消耗（F-R1 施放前段 / S4）
# ---------------------------------------------------------------------------


def test_cost_insufficient_rejected_no_spend(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """不足 → 被拒不耗回合：不增减、可反复尝试（TC-03①）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 80
    ok = lc.try_apply_cost(battle_state, "player", {"rage": 100})
    assert ok is False
    assert _side(battle_state)["rage"] == 80  # 怒气不变
    ok = lc.try_apply_cost(battle_state, "player", {"rage": 100})
    assert ok is False
    assert _side(battle_state)["rage"] == 80  # 可反复尝试，仍不变


def test_cost_sufficient_deducted(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """足 → 扣减成功（S2：狂暴 -100）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 100
    ok = lc.try_apply_cost(battle_state, "player", {"rage": 100})
    assert ok is True
    assert _side(battle_state)["rage"] == 0


def test_cost_pool_and_zero_noop(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """子池型池键消耗 + 0 值无操作（D-06）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    ok = lc.try_apply_cost(battle_state, "player", {"fire": 2})
    assert ok is True
    assert _side(battle_state)["element_energy"]["fire"] == 0
    before = dict(_side(battle_state))
    assert lc.try_apply_cost(battle_state, "player", {"rage": 0}) is True
    assert _side(battle_state) == before  # 0 值无操作


def test_cost_pool_insufficient_rejected(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """子池型池键不足 → 被拒不扣（D-02 池分布口径）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 1, "water": 1, "wind": 0}
    ok = lc.try_apply_cost(battle_state, "player", {"fire": 2})
    assert ok is False
    assert _side(battle_state)["element_energy"] == {"fire": 1, "water": 1, "wind": 0}  # 原子：不扣


def test_cost_dotted_pool_key(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """点分池级引用 [axis.pool]（D-04）消费。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 0, "wind": 0}
    assert lc.try_apply_cost(battle_state, "player", {"element_energy.fire": 1}) is True
    assert _side(battle_state)["element_energy"]["fire"] == 1


# ---------------------------------------------------------------------------
# ④ 被控保留（F-R1 被控段 / S4）
# ---------------------------------------------------------------------------


def test_controlled_preserved(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """被控 skip_turn：能量/怒气保留（不增不减）（TC-04①）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 60
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 0, "wind": 0}
    assert lc.is_controlled_preserved(battle_state) is True
    assert _side(battle_state)["rage"] == 60  # 保留
    assert _side(battle_state)["element_energy"] == {"fire": 2, "water": 0, "wind": 0}


# ---------------------------------------------------------------------------
# ⑤ 回合结束结清（F-R1 tick）
# ---------------------------------------------------------------------------


def test_tick_round_end_preserves_all(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """回合结束结清：契约无每回合变化字段 → 全保留（零增减幂等钩子）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 40
    _side(battle_state)["element_energy"] = {"fire": 1, "water": 1, "wind": 0}
    out = lc.tick_round_end(battle_state)
    assert out["player"]["rage"] == 40
    assert out["player"]["element_energy"] == {"fire": 1, "water": 1, "wind": 0}
    assert _side(battle_state)["rage"] == 40  # 状态未被改写


# ---------------------------------------------------------------------------
# ⑥ 战斗结束清零/保留（F-R1 终段 / S5 + TC-05）
# ---------------------------------------------------------------------------


def test_battle_end_reset_battle_clears(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """reset=battle → 战斗结束清零（数值型=0 / 子池型各池=0）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 72
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    lc.battle_end_reset(battle_state, RESET_BATTLE)
    assert _side(battle_state)["rage"] == 0
    assert _side(battle_state)["element_energy"] == {"fire": 0, "water": 0, "wind": 0}


def test_battle_end_reset_keep_preserves(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """reset=keep → 跨战斗保留（RS-3）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["heat"] = 30
    lc.battle_end_reset(battle_state, RESET_KEEP)
    assert _side(battle_state)["heat"] == 30


def test_battle_end_reset_battle_start_preserves(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """reset=battle_start → 战斗内保留；下次战斗开始置 base。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["focus"] = 8
    lc.battle_end_reset(battle_state, RESET_BATTLE_START)
    assert _side(battle_state)["focus"] == 8  # 战斗内保留
    lc.battle_start_init(battle_state, "player")
    assert _side(battle_state)["focus"] == 5  # 下次战斗开始重置为 base


def test_battle_end_reset_policy_per_axis(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """默认策略（battle）按注册表逐轴口径：battle 清零 / keep 保留 / battle_start 保留。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 72
    _side(battle_state)["heat"] = 30
    _side(battle_state)["focus"] = 8
    lc.battle_end_reset(
        battle_state, reset_policy=RESET_BATTLE, axis_ids=["rage", "heat", "focus"],
    )  # battle 策略显式
    assert _side(battle_state)["rage"] == 0   # battle → 清零
    assert _side(battle_state)["heat"] == 30  # keep → 保留
    assert _side(battle_state)["focus"] == 8  # battle_start → 保留


# ---------------------------------------------------------------------------
# ⑦ any 总量门（D-02）
# ---------------------------------------------------------------------------


def test_any_gate_sufficient_deducts_pools(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """any:2 足 → 逐池扣减（先可扣池序），总扣 2。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 1, "water": 1, "wind": 0}
    ok = lc.try_apply_cost(battle_state, "player", {"any": 2})
    assert ok is True
    assert _side(battle_state)["element_energy"] == {"fire": 0, "water": 0, "wind": 0}


def test_any_gate_insufficient_rejected_no_spend(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """any:2 总量不足 → 被拒、整体回滚不扣（D-02 原子性）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 1, "water": 0, "wind": 0}
    ok = lc.try_apply_cost(battle_state, "player", {"any": 2})
    assert ok is False
    assert _side(battle_state)["element_energy"] == {"fire": 1, "water": 0, "wind": 0}


def test_any_gate_spread_pools(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """any:2 分散两池扣减（fire1+water1，先可扣池序）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    assert lc.try_apply_cost(battle_state, "player", {"any": 3}) is True
    assert _side(battle_state)["element_energy"] == {"fire": 0, "water": 0, "wind": 0}


def test_gain_dotted_pool_key(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """点分池级引用 [axis.pool]（D-04）追加。"""
    lc.battle_start_init(battle_state, "player")
    lc.apply_gain(battle_state, "player", {"element_energy.water": 1})
    assert _side(battle_state)["element_energy"]["water"] == 1


# ---------------------------------------------------------------------------
# ⑧ resource_state 快照（RS-1~6 / D-04）
# ---------------------------------------------------------------------------


def test_snapshot_roundtrip(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """快照导出/恢复 round-trip：数值型单键 + 子池型池级展开（D-04，TC-07）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 72
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    snap = lc.snapshot_resource_state(battle_state)
    assert snap["player"] == {
        "rage": 72,
        "element_energy": {"fire": 2, "water": 1, "wind": 0},
        "heat": 0,
        "focus": 5,
    }
    # 新战斗快照（干净骨架）→ 恢复
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["rage"] == 72
    assert _side(bs2)["element_energy"] == {"fire": 2, "water": 1, "wind": 0}


def test_snapshot_restore_deleted_axis_degrades(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """已删注册轴恢复 → 字段缺失降级（RS-5），不报错不悬空。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["rage"] = 50
    snap = lc.snapshot_resource_state(battle_state)
    lc2 = ResourceLifecycle({"rage": REGISTRY["rage"]})  # 旧注册删掉 element_energy
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc2.restore_resource_state(bs2, snap)  # 不抛异常
    assert _side(bs2)["rage"] == 50
    assert "element_energy" not in _side(bs2)  # 降级：不写入


def test_snapshot_pool_atomicity(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """池级原子性：单池增减不整段覆盖（RS-6）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["element_energy"] = {"fire": 2, "water": 1, "wind": 0}
    lc.apply_gain(battle_state, "player", {"fire": 1})
    assert _side(battle_state)["element_energy"] == {
        "fire": 3, "water": 1, "wind": 0,  # water/wind 不动
    }


def test_restore_battle_start_resets_to_base(
    lc: ResourceLifecycle, battle_state: Dict[str, Any],
) -> None:
    """恢复后 battle_start 型轴重置为 base（F-R1 + RS-2 合并口径）。"""
    lc.battle_start_init(battle_state, "player")
    _side(battle_state)["focus"] = 8
    snap = lc.snapshot_resource_state(battle_state)
    bs2: Dict[str, Any] = {"status": "active", "player": {"hp": 500}, "enemy": {"hp": 500}}
    lc.restore_resource_state(bs2, snap)
    assert _side(bs2)["focus"] == 5  # 重置为 base（battle_start 型）
