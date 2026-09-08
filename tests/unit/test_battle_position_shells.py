"""方位战斗系统 Step 0 快照地基（框架改造验收）：_snap 三段空壳 + 恢复透传。

依据：docs/方位战斗系统_框架改造草案.md（v0.6 技术定稿）：
  - §三.1 PositionState（每 combatant 一份：relative_to/side/height）
  - §三.3 PartState（parts_state 实例段：part_id → {break_value, broken}）
  - §三.7 BattleResourceState（battle_resources.materials 冻结容器 + battle_alchemy_used）
  - §五 快照/迁移（新增快照字段全部进 core/battle.py _snap 权威；旧档缺段降级；
    BattleSnapshot dataclass 不动，单列收敛）
  - 附录 A Step 0：快照地基——_snap 加 combat_position/parts_state/battle_resources
    空壳 + 恢复透传；验收=快照往返字段不丢

铁律：零 NoneBot import；纯逻辑断言；确定性（固定 random_seed）。
"""

from __future__ import annotations

import json

from qbot_rpg.core.battle import BattleEngine

# 最小玩家/敌人（对齐 tests/unit/test_battle_engine.py 构造口径）
PLAYER = {"hp": 100, "max_hp": 100, "mp": 20, "str": 15, "int": 10,
          "agi": 10, "spr": 5, "lck": 10, "name": "P"}
ENEMY = {"hp": 60, "max_hp": 60, "mp": 0, "str": 12, "int": 8, "agi": 8,
         "spr": 4, "lck": 5, "name": "E"}

_POSITION_DEFAULTS = {
    "player": {"relative_to": "enemy", "side": "front", "height": "ground"},
    "enemy": {"relative_to": "player", "side": "front", "height": "ground"},
}


def _fresh_engine() -> BattleEngine:
    """固定种子新战斗（start 即入首个回合，取 turn_start 边界快照）。"""
    return BattleEngine().start(PLAYER, ENEMY, random_seed=20260908)


class TestPositionSnapshotShells:
    """Step 0 空壳落位：start 建段、默认值正确、battle_state 权威查询可见。"""

    def test_start_snapshot_has_three_position_sections(self) -> None:
        """start 后 _snap 含 combat_position/parts_state/battle_resources 三段。"""
        eng = _fresh_engine()
        snap = eng.battle_state()
        # combat_position：每 combatant 一份，默认正面贴地
        assert snap["combat_position"] == _POSITION_DEFAULTS
        # parts_state：空实例段（尚无 EnemyDef.parts[] 配置）
        assert snap["parts_state"] == {}
        # battle_resources：materials 冻结容器空壳；battle_alchemy_used schema 占位 0
        assert snap["battle_resources"] == {"materials": {}, "battle_alchemy_used": 0}

    def test_combat_position_defaults_are_schema_valid(self) -> None:
        """默认值符合 §三.1 schema：side ∈ 四方位、height ∈ 空/地、relative_to 成对。"""
        cp = _fresh_engine().battle_state()["combat_position"]
        assert set(cp) == {"player", "enemy"}
        for entry in cp.values():
            assert entry["side"] in ("front", "back", "left", "right")
            assert entry["height"] in ("ground", "air")
        assert cp["player"]["relative_to"] == "enemy"
        assert cp["enemy"]["relative_to"] == "player"

    def test_turn_boundary_snapshot_carries_sections(self) -> None:
        """回合边界快照（to_snapshot）随 _snap 深拷贝携带三段（不落新键于边界外）。"""
        snap = _fresh_engine().to_snapshot()
        assert snap["combat_position"] == _POSITION_DEFAULTS
        assert snap["parts_state"] == {}
        assert snap["battle_resources"] == {"materials": {}, "battle_alchemy_used": 0}

    def test_record_alchemy_used_migrated_to_section(self) -> None:
        """Step 5 迁移（方位 v0.6 §三.7）：计数权威落 battle_resources 段内；顶层键
        保留同步镜像（旧读方/旧快照兼容）。原 Step 0「只走顶层/占位不污染」断言随
        迁移收口更新。"""
        eng = _fresh_engine()
        assert eng.record_alchemy_used() == 1
        state = eng.battle_state()
        assert state["battle_resources"]["battle_alchemy_used"] == 1  # 段内权威
        assert state["battle_alchemy_used"] == 1                       # 顶层镜像


class TestPositionSnapshotRoundtrip:
    """Step 0 验收：快照往返字段不丢（start → 序列化 → 还原 → 权威查询）。"""

    def test_json_roundtrip_keeps_position_sections(self) -> None:
        """to_snapshot → JSON 序列化（存储形态）→ from_snapshot → 三段保留值一致。"""
        src = _fresh_engine()
        snap = json.loads(json.dumps(src.to_snapshot(), ensure_ascii=False))
        eng2 = BattleEngine.from_snapshot(snap)
        state = eng2.battle_state()
        assert state["combat_position"] == _POSITION_DEFAULTS
        assert state["parts_state"] == {}
        assert state["battle_resources"] == {"materials": {}, "battle_alchemy_used": 0}

    def test_sections_survive_multiple_boundary_snapshots(self) -> None:
        """连续多回合（多次回合边界快照）后三段仍在（续战长链不丢字段）。"""
        eng = _fresh_engine()
        for _ in range(3):
            snap = eng.to_snapshot()  # turn_start 边界（玩家未行动）
            eng = BattleEngine.from_snapshot(snap)
        state = eng.battle_state()
        assert state["combat_position"] == _POSITION_DEFAULTS
        assert state["parts_state"] == {}
        assert state["battle_resources"] == {"materials": {}, "battle_alchemy_used": 0}

    def test_legacy_snapshot_without_sections_still_restores(self) -> None:
        """旧快照（无三段）→ from_snapshot 不崩不悬空（缺段降级，对齐 RS-5）。"""
        src = _fresh_engine()
        snap = src.to_snapshot()
        for key in ("combat_position", "parts_state", "battle_resources"):
            snap.pop(key, None)
        eng2 = BattleEngine.from_snapshot(snap)
        state = eng2.battle_state()
        assert "combat_position" not in state
        assert "parts_state" not in state
        assert "battle_resources" not in state
        assert eng2.battle_state()["turn"] == src.battle_state()["turn"]
