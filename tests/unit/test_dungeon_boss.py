"""M3 批次5·路O：M19 BOSS 版流程 + M20 BOSS 三阶段机制与换区联动 单元测试。

依据：细化_2a3 §2.3（S3 BOSS 追击 / S4 决战三阶段阶段表：阶段1 100-60% → 阶段2 60-30%
狂暴 → 阶段3 30-0% 绝境）+ 细化_2a2（换区追击 R1-R27：残血阈值触发 / PV 半恢复满值口径
向下取整 R9 / 残血保持不重置 R12-R13 / 追到续战 = 残血 + PV 半值 + 开场技 R19-R20）+
m3_shared_contract §3（zone_change 四字段）/§4.2（状态集 S0-S7 + 迁移表 M1-M15）。
数据源：legal 包 dungeon.json（molten_dungeon_boss：boss_room=lava_tunnel、
boss=ember_drake）/ enemies.json（ember_drake zone_change 样例：hp_threshold 0.3、
targets [molten_corridor, molten_core]、timing after_action）/ maps.json
（lava_tunnel gate_guard=ember_drake 节点级守门怪样例）。

断言分组：
  TestEnterBossRoom 入场校验（守门怪未击败拦截 / 击败放行 / 无守门怪放行 / 场所校验 /
     dungeon_def 级 gate_guard 扩展 / Def 对象形态与 dict 形态等价）
  TestPhaseFor 三阶段阈值（默认 60%/30% 边界归下阶段 / boss_def.phases 可配 /
     构造器 phases 可配）
  TestShouldZoneChange 换区触发（阈值命中/未命中 / hp+max_hp 形态 / hp=0 击杀优先 /
     disabled / targets 空 / cfg 缺失 / timing=phase_changed 衔接 / boss_def 缺省 cfg）
  TestOnChaseContinue 续战标记（resume/hp_keep/pv_half/opening_skill + pv_half_value
     半值计算 floor(pv_max × pv_recover)）

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.content.map_models import MapDef
from qbot_rpg.content.models import EnemyDef
from qbot_rpg.core.dungeon_boss import (
    SESSION_GATE_GUARDS_KEY,
    ZC_TRIGGER_PHASE_CHANGED,
    BossFlow,
)

LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"

# ember_drake 的 zone_change 样例（legal/enemies.json；m3 §3.1 四字段）
EMBER_ZONE_CHANGE = {
    "enabled": True,
    "hp_threshold": 0.3,
    "targets": ["molten_corridor", "molten_core"],
    "timing": "after_action",
}


# ---------------------------------------------------------------------------
# 夹具辅助：legal 包数据深拷贝 → BossFlow 构造
# ---------------------------------------------------------------------------


def _load(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _boss_dungeon(**overrides: Any) -> dict:
    """合法 BOSS 版副本深拷贝（molten_dungeon_boss：boss_room=lava_tunnel, boss=ember_drake）。"""
    for d in _load("dungeon"):
        if d.get("id") == "molten_dungeon_boss":
            entry = copy.deepcopy(d)
            entry.update(overrides)
            return entry
    raise AssertionError("legal/dungeon.json 缺少 molten_dungeon_boss")


def _ember_drake(**overrides: Any) -> dict:
    """合法 BOSS 怪物深拷贝（ember_drake：pv=300 + zone_change 样例）。"""
    for e in _load("enemies"):
        if e.get("id") == "ember_drake":
            entry = copy.deepcopy(e)
            entry.update(overrides)
            return entry
    raise AssertionError("legal/enemies.json 缺少 ember_drake")


def _maps_registry(gate_guard: Any = "ember_drake") -> dict:
    """maps.json 注册表（map_id → 配置）；lava_tunnel.gate_guard 可覆盖（缺省=夹具原值）。"""
    reg: dict = {}
    for m in _load("maps"):
        entry = copy.deepcopy(m)
        if entry.get("id") == "lava_tunnel":
            if gate_guard is None:
                entry.pop("gate_guard", None)
            else:
                entry["gate_guard"] = gate_guard
        reg[entry["id"]] = entry
    return reg


def _flow(
    boss: Any = None,
    dungeon: Any = None,
    session: Any = None,
    maps: Any = None,
    phases: Any = None,
) -> BossFlow:
    return BossFlow(
        boss if boss is not None else _ember_drake(),
        dungeon if dungeon is not None else _boss_dungeon(),
        session if session is not None else {},
        maps=maps if maps is not None else _maps_registry(),
        phases=phases,
    )


# ---------------------------------------------------------------------------
# M19 BOSS 房进入：守门怪 gate_guard（未击败拦截 / 击败放行）
# ---------------------------------------------------------------------------


class TestEnterBossRoom:
    """BOSS 房进入校验（M19；m3 §4.2 决战前置）：守门怪需先击败，未击败返回拦截。"""

    def test_guard_undefeated_blocks(self) -> None:
        flow = _flow(maps=_maps_registry("stone_skink"))
        out = flow.enter_boss_room({"map_id": "lava_tunnel"})
        assert out["allowed"] is False               # 1 拦截
        assert out["reason"] == "gate_guard"         # 2 拦截原因=守门怪
        assert out["gate_guard"] == "stone_skink"    # 3 守门怪 id

    def test_guard_defeated_allows(self) -> None:
        session = {SESSION_GATE_GUARDS_KEY: ["stone_skink"]}
        flow = _flow(maps=_maps_registry("stone_skink"), session=session)
        out = flow.enter_boss_room({"map_id": "lava_tunnel"})
        assert out["allowed"] is True                # 1 击败后放行
        assert out["boss"] == "ember_drake"          # 2 BOSS id

    def test_no_guard_allows_without_marker(self) -> None:
        flow = _flow(maps=_maps_registry(None))  # 无守门怪配置
        out = flow.enter_boss_room({"map_id": "lava_tunnel"})
        assert out["allowed"] is True                # 1 无守门怪直接放行

    def test_wrong_room_venue_check(self) -> None:
        flow = _flow()
        out = flow.enter_boss_room({"map_id": "rubble_field"})
        assert out["allowed"] is False               # 1 场所校验拦截
        assert out["reason"] == "wrong_room"         # 2 拦截原因=非 BOSS 房

    def test_dungeon_level_gate_guard_extension(self) -> None:
        # dungeon_def 级 gate_guard（工程扩展）优先于 maps 节点级
        dungeon = _boss_dungeon(gate_guard="stone_skink")
        flow = _flow(dungeon=dungeon, maps=_maps_registry("crag_den_guard"))
        out = flow.enter_boss_room({"map_id": "lava_tunnel"})
        assert out["allowed"] is False               # 1 拦截
        assert out["gate_guard"] == "stone_skink"    # 2 dungeon_def 级守门怪优先
        flow2 = _flow(
            dungeon=dungeon,
            maps=_maps_registry("crag_den_guard"),
            session={SESSION_GATE_GUARDS_KEY: ("stone_skink",)},
        )
        out2 = flow2.enter_boss_room({"map_id": "lava_tunnel"})
        assert out2["allowed"] is True               # 3 击败后放行

    def test_def_object_forms_equivalent(self) -> None:
        # EnemyDef / DungeonDef / MapDef 对象形态与 dict 形态等价（maps gate_guard 解析）
        boss = EnemyDef.from_entry(_ember_drake())
        dungeon = DungeonDef.from_entry(_boss_dungeon())
        maps = {m["id"]: MapDef.from_entry(m) for m in _load("maps")}
        flow = BossFlow(boss, dungeon, {}, maps=maps)
        out = flow.enter_boss_room({"map_id": "lava_tunnel"})
        assert out["allowed"] is False               # 1 夹具原值守门怪（ember_drake）拦截
        assert out["gate_guard"] == "ember_drake"    # 2 MapDef 节点级 gate_guard 解析
        flow2 = BossFlow(
            boss, dungeon, {SESSION_GATE_GUARDS_KEY: {"ember_drake"}}, maps=maps
        )
        out2 = flow2.enter_boss_room({"map_id": "lava_tunnel"})
        assert out2["allowed"] is True               # 3 set 形态已击败标记 → 放行


# ---------------------------------------------------------------------------
# M20 三阶段机制：HP 百分比 → 阶段号（默认 100-60/60-30/30-0，边界归下阶段）
# ---------------------------------------------------------------------------


class TestPhaseFor:
    """决战三阶段阈值（2a3 §2.3 S4 阶段表；衔接 monster_phases 阈值处归下阶段）。"""

    def test_default_thresholds_boundaries(self) -> None:
        flow = _flow()
        assert flow.phase_for(100) == 1              # 1 满血 → 阶段1
        assert flow.phase_for(61) == 1               # 2 >60% → 阶段1
        assert flow.phase_for(60) == 2               # 3 60% 边界归下阶段
        assert flow.phase_for(30) == 3               # 4 30% 边界归下阶段
        assert flow.phase_for(0) == 3                # 5 0% → 阶段3

    def test_configurable_phases_via_boss_def(self) -> None:
        boss = _ember_drake(
            phases=[{"threshold": 100}, {"threshold": 80}, {"threshold": 40}]
        )
        flow = _flow(boss=boss)
        assert flow.phase_for(81) == 1               # 1 (80,100] → 阶段1
        assert flow.phase_for(80) == 2               # 2 80% 边界归下阶段
        assert flow.phase_for(40) == 3               # 3 40% 边界归下阶段

    def test_configurable_phases_via_constructor(self) -> None:
        flow = _flow(
            phases=[{"threshold": 100}, {"threshold": 90}, {"threshold": 45}]
        )
        assert flow.phase_for(91) == 1               # 1 (90,100] → 阶段1
        assert flow.phase_for(90) == 2               # 2 90% 边界归下阶段
        assert flow.phase_for(45) == 3               # 3 45% 边界归下阶段


# ---------------------------------------------------------------------------
# M20 换区联动：残血阈值触发（enemies zone_change 配置）
# ---------------------------------------------------------------------------


class TestShouldZoneChange:
    """换区触发判定（m3 §3.2 + 2a2 §1.1：残血才换区 / 击杀优先 / 未配置不换区）。"""

    def test_threshold_hit_and_miss(self) -> None:
        flow = _flow()
        assert flow.should_zone_change({"hp_pct": 25.0}, EMBER_ZONE_CHANGE) is True    # 1 阈值内触发
        assert flow.should_zone_change({"hp_pct": 30.0}, EMBER_ZONE_CHANGE) is True    # 2 30% 整 ≤阈值触发
        assert flow.should_zone_change({"hp_pct": 30.1}, EMBER_ZONE_CHANGE) is False   # 3 超阈值不触发

    def test_hp_max_hp_form(self) -> None:
        flow = _flow()
        st = {"hp": 375, "max_hp": 1500}  # 25%
        assert flow.should_zone_change(st, EMBER_ZONE_CHANGE) is True                  # 1 绝对 HP 换算触发
        st2 = {"hp": 451, "max_hp": 1500}  # 30.07%
        assert flow.should_zone_change(st2, EMBER_ZONE_CHANGE) is False                # 2 超阈值不触发

    def test_hp_zero_kill_priority(self) -> None:
        flow = _flow()
        assert flow.should_zone_change({"hp": 0, "max_hp": 1500}, EMBER_ZONE_CHANGE) is False   # 1 R3 击杀优先

    def test_disabled_never_changes(self) -> None:
        flow = _flow()
        cfg = dict(EMBER_ZONE_CHANGE, enabled=False)
        assert flow.should_zone_change({"hp_pct": 10}, cfg) is False                   # 1 enabled=False 不换区

    def test_no_targets_or_missing_cfg(self) -> None:
        flow = _flow()
        # R4：候选区为空 → 永不换区
        assert flow.should_zone_change({"hp_pct": 10}, dict(EMBER_ZONE_CHANGE, targets=[])) is False   # 1
        # 显式空配置（无 targets/hp_threshold）→ 不触发
        assert flow.should_zone_change({"hp_pct": 10}, {}) is False                                    # 2
        # boss 未配置 zone_change → cfg 缺省回落为空 → 永不换区
        flow2 = _flow(boss=_ember_drake(zone_change=None))
        assert flow2.should_zone_change({"hp_pct": 10}, None) is False                                 # 3

    def test_timing_phase_changed(self) -> None:
        flow = _flow()
        cfg = dict(EMBER_ZONE_CHANGE, timing=ZC_TRIGGER_PHASE_CHANGED)
        # 阈值命中但本结算点无阶段切换 → 不触发（衔接 monster_phases phase_changed）
        assert flow.should_zone_change({"hp_pct": 25, "phase_changed": False}, cfg) is False   # 1
        # 阶段切换发生 → 触发
        assert flow.should_zone_change({"hp_pct": 25, "phase_changed": True}, cfg) is True      # 2
        # 阈值未命中即使阶段切换也不触发
        assert flow.should_zone_change({"hp_pct": 80, "phase_changed": True}, cfg) is False     # 3

    def test_boss_def_default_cfg(self) -> None:
        # cfg 缺省 → boss_def.zone_change（ember_drake 样例）
        flow = _flow()
        assert flow.should_zone_change({"hp_pct": 25.0}) is True                        # 1
        assert flow.should_zone_change({"hp_pct": 40.0}) is False                       # 2


# ---------------------------------------------------------------------------
# 追到续战准备：残血保持 + PV 半恢复（向下取整）+ 开场技标记
# ---------------------------------------------------------------------------


class TestOnChaseContinue:
    """追到续战准备（M6 追到 → S4 决战；2a2 R9/R12-R13/R19-R20，实际战斗接线批次 6）。"""

    def test_markers_and_pv_half_value(self) -> None:
        flow = _flow(session={"boss_state": {"pv": 0}})  # 破防场景（缺失量口径：0 + floor(300×0.5)=150）
        out = flow.on_chase_continue()
        assert out["resume"] is True                 # 1 续战标记
        assert out["hp_keep"] is True                # 2 残血保持（不重置不回血）
        assert out["pv_half"] is True                # 3 PV 半恢复触发标记
        assert out["pv_half_value"] == 150           # 4 floor(300×0.5)（2a2 §2.1 例）
        assert out["opening_skill"] is True          # 5 换区后第一回合开场技

    def test_pv_half_value_floor_odd(self) -> None:
        boss = _ember_drake(pv=201)
        out = _flow(boss=boss, session={"boss_state": {"pv": 0}}).on_chase_continue()
        assert out["pv_half_value"] == 100           # 1 破防：0 + floor(201×0.5) 向下取整

    def test_pv_half_value_custom_recover(self) -> None:
        boss = _ember_drake(zone_change=dict(EMBER_ZONE_CHANGE, pv_recover=0.25))
        out = _flow(boss=boss, session={"boss_state": {"pv": 0}}).on_chase_continue()
        assert out["pv_half_value"] == 75            # 1 破防：0 + floor(300×0.25) 可配恢复比例

    def test_pv_half_value_missing_amount_unbroken(self) -> None:
        """缺失量口径（用户拍板 2026-08-26）：未破防 250/300 换区 → 补缺口一半 = 275（回升）。"""
        out = _flow(session={"boss_state": {"pv": 250}}).on_chase_continue()
        assert out["pv_half_value"] == 275            # 250 + floor(50×0.5)

    def test_boss_state_hp_passthrough(self) -> None:
        session = {"boss_state": {"hp": 375, "max_hp": 1500}}
        out = _flow(session=session).on_chase_continue()
        assert out["boss_hp"] == 375                 # 1 残血保持数据源透传
        assert out["hp_keep"] is True                # 2 残血保持标记
