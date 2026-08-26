"""M3 批次7·路T：M27 战斗快照续玩 + M28 非战斗离开重置 单元测试。

依据：
  - 细化_1g3_快照续战与测试.md（§1.2 快照字段级：ai_state+combo_state 全保留 S1、turn 双写；
    §2.1 退出/超时/锁屏 → 快照续玩、非战斗离开 → 副本重置；§2.3 恢复时序；§2.4 死亡 ≠ 中断）
  - 细化_1g4_战斗世界边界.md（BattleSnapshot 会话形态 / TIME-04 中断恢复）
  - m3_shared_contract.md §4.4（快照续玩 ai_state+combo_state+换区上下文全保留；战斗中断
    不改变副本状态）+ §八 10（快照完整性铁律）
  - 规划_路2a_地图副本.md M27（续玩逐字段一致；恢复入口明示「战斗中断可续玩，离开副本
    将重置」）/ M28（非战斗离开重置；战斗中断离开不触发重置，分工明确）
  - 衔接 world/chase_resume.py（M15 exit_dungeon_reset 重置信号 + 明示文案常量）

断言分组：
  TestResumeFromSnapshot  M27 快照续玩（stub 工厂注入：ai_state/combo_state 逐字段保留 /
     换区上下文保留 / turn 恢复；战斗中断不重置副本状态；快照完整性校验；工厂异常防御；
     未注入工厂退化为校验闸门；真实 BattleEngine.from_snapshot 端到端续玩）
  TestNonCombatExit       M28 非战斗离开重置（调 exit_dungeon_reset + 明示文案 / 战斗中
     拒绝离开提示续玩 / 显式 in_battle 开关 / 纯函数不改入参 / dataclass 形态）

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）；battle_factory 一律 stub 注入
（真实工厂仅 1 例端到端用 BattleEngine.from_snapshot）。
"""

from __future__ import annotations

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.dungeon import DungeonSession
from qbot_rpg.world.chase_resume import (
    MESSAGE_HINT_BATTLE_ONGOING,
    MESSAGE_HINT_LEAVE_RESET,
    STATE_LEFT,
)
from qbot_rpg.world.snapshot_resume import (
    MESSAGE_HINT_BATTLE_ONGOING as HINT,
    non_combat_exit,
    resume_from_snapshot,
)

# 真实 BattleEngine 端到端夹具（对齐 test_battle_engine.py 形态）
_PLAYER = {"max_hp":500,"hp":500,"max_mp":100,"mp":100,"atk":100,"dfn":50,"mag":50,"spd":50,
           "foc":100,"con":50,"str":100,"int":80,"agi":50,"spr":50,"lck":50,"elem_atk":0,"name":"P"}
_ENEMY = {"max_hp":400,"hp":400,"max_mp":0,"mp":0,"atk":80,"dfn":40,"mag":30,"spd":40,"foc":50,
          "con":50,"str":80,"int":30,"agi":40,"spr":40,"lck":10,"elem_atk":0,"name":"E"}


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _snapshot(**over) -> dict:
    """进行中战斗快照（1g3 §1.2 字段级形态：ai_state/combo_state/turn 双写齐全）。"""
    base = {
        "schema_version": 1,
        "snapshot_id": "snap-1",
        "snapshot_at": {"boundary": "turn_end", "turn": 12},
        "saved_at": "2026-08-26T00:00:00Z",
        "session_type": "battle",
        "turn": 12,
        "turn_boundary": "turn_end",
        "player": {"uid": "p1", "hp": 320, "mp": 45},
        "enemy": {"uid": "ember_drake", "hp": 137, "max_hp": 1000, "pv": 150},
        "ai_state": {
            "boss_phase": 2,
            "action_table_state": "pattern_index",
            "pending_action": "charge_breath",
            "combo_anchor": 3,
            "marks": {"mark_x": 2},
            "zone_change": {"triggered": True, "from": "molten_core",
                            "targets": ["熔岩坑道"]},
            "pv_recover_pending": 0.5,
        },
        "combo_state": {
            "active_combo": "combo_flame",
            "seg": 3,
            "total_segs": 5,
            "combo_resources": {"imprint": 1},
            "derived_mult_total": 1.2,
        },
        "status_state": {},
        "marks_state": {},
        "formula_state": {"random_seed": 42},
        "stats_collector": {"per_action": []},
    }
    base.update(over)
    return base


def _make_session(**over) -> dict:
    """副本会话（dict 持久化形态，to_dict 形状）；可覆写任意字段。"""
    base = {
        "dungeon_id": "molten_dungeon",
        "dungeon_type": "boss",
        "state": "BOSS_CHASE",
        "current_map": "molten_core",
        "cleared_maps": ["lava_tunnel", "molten_corridor"],
        "subquest_progress": {"sq_1": 2},
        "boss_state": {"hp": 280, "max_hp": 1000, "pv": 150, "chasing": True},
        "rest_count": 2,
        "external_anchor": "world_map_07",
        "content_pack_id": "cp1",
        "content_pack_version": "1.0",
    }
    base.update(over)
    return base


class _StubFactory:
    """battle_factory stub：记录收到的快照 + 受控返回引擎对象 / 抛错（不依赖真实引擎）。"""

    def __init__(self, engine: object = None, error: Exception | None = None) -> None:
        self.engine = engine if engine is not None else object()
        self.error = error
        self.calls: list = []

    def __call__(self, snapshot):
        self.calls.append(snapshot)
        if self.error is not None:
            raise self.error
        return self.engine


# ---------------------------------------------------------------------------
# M27：战斗快照续玩
# ---------------------------------------------------------------------------


class TestResumeFromSnapshot:
    def test_stub_factory_resumes_with_all_preserved_flags(self) -> None:
        """stub 工厂注入 → 续玩成功：ai_state/combo_state/换区上下文全保留 + turn 恢复。"""
        snap = _snapshot()
        factory = _StubFactory()
        out = resume_from_snapshot({}, snap, battle_factory=factory)
        assert out["resumed"] is True              # 1 引擎已构建续玩就绪
        assert out["turn"] == 12                   # 2 回合数恢复（顶层 turn）
        assert out["ai_state_preserved"] is True   # 3 ai_state 保留
        assert out["combo_state_preserved"] is True  # 4 combo_state 保留
        assert out["chase_context_preserved"] is True  # 5 换区上下文保留
        assert factory.calls == [snap]             # 6 工厂收到同一快照（引用）
        assert out["engine"] is factory.engine     # 7 引擎引用返回
        assert out["reset"] is False               # 8 续玩非重置
        assert out["state_unchanged"] is True      # 9 战斗中断不改变副本状态

    def test_ai_state_field_level_preserved(self) -> None:
        """ai_state 逐字段保留（m3 §八 10：boss_phase/行动表指针/读招/印记/换区字段一致）。"""
        snap = _snapshot()
        factory = _StubFactory()
        resume_from_snapshot({}, snap, battle_factory=factory)
        ai = factory.calls[0]["ai_state"]
        assert ai["boss_phase"] == 2               # 1 BOSS 阶段
        assert ai["action_table_state"] == "pattern_index"  # 2 行动表指针
        assert ai["pending_action"] == "charge_breath"  # 3 当前读招/蓄力
        assert ai["combo_anchor"] == 3             # 4 连招锚点
        assert ai["marks"] == {"mark_x": 2}        # 5 印记状态
        assert ai["zone_change"]["triggered"] is True  # 6 换区状态（ai_state 内嵌）
        assert ai["zone_change"]["targets"] == ["熔岩坑道"]  # 7 候选区域
        assert ai["pv_recover_pending"] == 0.5     # 8 换区后 PV 恢复
        assert factory.calls[0]["ai_state"] is snap["ai_state"]  # 9 引用透传不改写

    def test_combo_state_field_level_preserved(self) -> None:
        """combo_state 逐字段保留（套内续玩：active_combo/seg/total_segs/资源/倍率一致）。"""
        snap = _snapshot()
        factory = _StubFactory()
        resume_from_snapshot({}, snap, battle_factory=factory)
        cb = factory.calls[0]["combo_state"]
        assert cb["active_combo"] == "combo_flame"  # 1 当前连段/套
        assert cb["seg"] == 3                       # 2 已执行段数（套内续玩载体）
        assert cb["total_segs"] == 5                # 3 总段数
        assert cb["combo_resources"] == {"imprint": 1}  # 4 连段资源
        assert cb["derived_mult_total"] == 1.2      # 5 派生累计倍率

    def test_chase_context_top_level_and_ai_state_fields(self) -> None:
        """换区上下文（chase ctx）判定源：顶层键 + ai_state 内嵌键全命中。"""
        snap = _snapshot(
            chase_ctx={"target_map": "molten_core", "miss_count": 1},
            zone_chase={"active": True},
            chasing=True,
            chase_target="molten_core",
        )
        out = resume_from_snapshot({}, snap, battle_factory=_StubFactory())
        assert out["chase_context_preserved"] is True  # 1
        fields = out["chase_fields"]
        assert "chase_ctx" in fields                # 2 顶层 chase_ctx
        assert "zone_chase" in fields               # 3 顶层 zone_chase
        assert "chase" not in fields                # 4 未携带键不虚报
        assert "chasing" in fields                  # 5 追击态标志
        assert "chase_target" in fields             # 6 追击目标
        assert "ai_state.zone_change" in fields     # 7 ai_state 内嵌换区状态
        assert "ai_state.pv_recover_pending" in fields  # 8 ai_state 内嵌 PV 恢复

    def test_no_chase_context_flag_false(self) -> None:
        """无换区上下文 → chase_context_preserved=False，续玩核心（ai/combo）不受影响。"""
        snap = _snapshot(
            ai_state={"boss_phase": 1}, combo_state={},
        )
        out = resume_from_snapshot({}, snap, battle_factory=_StubFactory())
        assert out["resumed"] is True               # 1 续玩仍成立
        assert out["chase_context_preserved"] is False  # 2 无换区上下文
        assert out["chase_fields"] == []            # 3 无命中字段
        assert out["ai_state_preserved"] is True    # 4 ai_state 保留判定独立

    def test_turn_from_snapshot_at_fallback(self) -> None:
        """turn 双写任一处（1g3 §1.3）：顶层缺失 → snapshot_at.turn；反之亦然。"""
        snap = _snapshot(turn=None)
        assert resume_from_snapshot({}, snap, _StubFactory())["turn"] == 12  # 1
        snap2 = _snapshot(snapshot_at={}, turn=7)
        assert resume_from_snapshot({}, snap2, _StubFactory())["turn"] == 7  # 2

    def test_incomplete_snapshot_rejected_without_factory_call(self) -> None:
        """完整性失败（缺 combo_state）→ 拒绝续玩，不调用工厂，missing_fields 明示。"""
        snap = _snapshot()
        snap.pop("combo_state")
        factory = _StubFactory()
        out = resume_from_snapshot({}, snap, battle_factory=factory)
        assert out["resumed"] is False              # 1
        assert out["reason"] == "incomplete_snapshot"  # 2
        assert out["valid"] is False                # 3
        assert out["missing_fields"] == ["combo_state"]  # 4
        assert factory.calls == []                  # 5 工厂未被调用
        assert out["ai_state_preserved"] is True    # 6 其余字段判定仍计算
        assert out["chase_context_preserved"] is True  # 7

    def test_non_mapping_snapshot_invalid(self) -> None:
        """非 Mapping 快照 → invalid_snapshot（防御）。"""
        out = resume_from_snapshot({}, None)
        assert out["resumed"] is False              # 1
        assert out["reason"] == "invalid_snapshot"  # 2
        assert out["reset"] is False                # 3

    def test_factory_error_reported(self) -> None:
        """注入工厂抛错 → factory_error（防御，不吞细节，补白 1）。"""
        factory = _StubFactory(error=RuntimeError("boom"))
        out = resume_from_snapshot({}, _snapshot(), battle_factory=factory)
        assert out["resumed"] is False              # 1
        assert out["reason"] == "factory_error"     # 2
        assert "boom" in out["error"]               # 3 错误细节透出

    def test_no_factory_validation_gate(self) -> None:
        """未注入工厂 → 契约形态校验闸门（补白 1）：valid/turn/保留标志照常计算。"""
        out = resume_from_snapshot({}, _snapshot())
        assert out["resumed"] is False              # 1 未构建引擎
        assert out["reason"] == "factory_missing"   # 2
        assert out["valid"] is True                 # 3 契约形态完整
        assert out["turn"] == 12                    # 4
        assert out["ai_state_preserved"] is True    # 5
        assert out["combo_state_preserved"] is True  # 6
        assert out["chase_context_preserved"] is True  # 7

    def test_battle_interrupt_does_not_touch_session_state(self) -> None:
        """战斗中断（退出/超时/锁屏）不改变副本状态（续玩非重置，m3 §4.4）。"""
        session = _make_session()
        ctx = {"in_battle": True, "session": session}
        factory = _StubFactory()
        out = resume_from_snapshot(ctx, _snapshot(), battle_factory=factory)
        assert out["reset"] is False                # 1 续玩非重置
        assert out["state_unchanged"] is True       # 2
        assert ctx == {"in_battle": True, "session": session}  # 3 玩家上下文未改写
        assert session["boss_state"]["hp"] == 280   # 4 副本会话残血原样
        assert session["state"] == "BOSS_CHASE"     # 5 副本状态原样

    def test_empty_state_mappings_contract_valid(self) -> None:
        """ai_state/combo_state 空 dict 合法（1g1c B5 清零形态）：键存在即保留。"""
        out = resume_from_snapshot({}, _snapshot(ai_state={}, combo_state={}),
                                   battle_factory=_StubFactory())
        assert out["resumed"] is True               # 1
        assert out["ai_state_preserved"] is True    # 2
        assert out["combo_state_preserved"] is True  # 3
        assert out["chase_context_preserved"] is False  # 4 空 ai_state 无换区字段

    def test_real_battle_engine_from_snapshot_factory(self) -> None:
        """真实 BattleEngine.from_snapshot 端到端续玩：中断快照 → 引擎还原逐字段一致。"""
        eng = BattleEngine().start(_PLAYER, _ENEMY, random_seed=42)
        eng.do_action("player", {"type": "normal", "mult": 1.0})
        eng.enemy_act()
        eng.end_turn()  # 回合边界（1g3 S0：快照只落回合边界）
        eng._snap["ai_state"] = {"boss_phase": 2,
                                 "zone_change": {"triggered": True, "from": "molten_core"},
                                 "pv_recover_pending": 0.5}
        eng._snap["combo_state"] = {"active_combo": "combo_flame", "seg": 3, "total_segs": 5}
        snap = eng.to_snapshot()
        out = resume_from_snapshot({}, snap, battle_factory=BattleEngine.from_snapshot)
        assert out["resumed"] is True               # 1 真实引擎还原成功
        assert isinstance(out["engine"], BattleEngine)  # 2 引擎类型正确
        assert out["turn"] == snap["turn"]          # 3 回合数与中断前一致
        assert out["ai_state_preserved"] is True    # 4
        assert out["combo_state_preserved"] is True  # 5
        assert out["chase_context_preserved"] is True  # 6 ai_state 内嵌换区字段命中
        restored = out["engine"].battle_state()
        assert restored["ai_state"]["boss_phase"] == 2  # 7 还原引擎 ai_state 逐字段一致
        assert restored["ai_state"]["zone_change"]["triggered"] is True  # 8 换区上下文一致
        assert restored["combo_state"]["seg"] == 3  # 9 连段 seg 逐字段一致


# ---------------------------------------------------------------------------
# M28：非战斗离开重置与明示文案
# ---------------------------------------------------------------------------


class TestNonCombatExit:
    def test_non_battle_leave_resets_with_explicit_entry_hint(self) -> None:
        """非战斗离开 → exit_dungeon_reset 副本重置 + 明示文案「战斗中断可续玩，离开副本将重置」。"""
        session = _make_session()
        out = non_combat_exit({}, session, in_battle=False)
        assert out["reset"] is True                 # 1 重置信号（M28）
        assert out["via_snapshot"] is False         # 2 非战斗离开不走快照
        assert out["message_hint"] == MESSAGE_HINT_LEAVE_RESET  # 3 重置自身文案（透传）
        assert out["entry_hint"] == HINT            # 4 恢复入口明示完整文案（M27）
        assert out["entry_hint"] == "战斗中断可续玩，离开副本将重置"  # 5 文案原文
        s2 = out["session"]
        assert s2["state"] == STATE_LEFT            # 6 S7 离开态
        assert s2["boss_state"] == {}               # 7 BOSS/残血全清
        assert s2["external_anchor"] == "world_map_07"  # 8 回外部锚点
        assert out["state"] == STATE_LEFT           # 9

    def test_in_battle_flag_refuses_and_hints_snapshot_resume(self) -> None:
        """in_battle=True（显式开关）→ 拒绝离开、提示续玩走快照（M27 分工）。"""
        session = _make_session()
        out = non_combat_exit({}, session, in_battle=True)
        assert out["reset"] is False                # 1 战斗中拒绝重置
        assert out["reason"] == "battle_in_progress"  # 2
        assert out["message_hint"] == HINT          # 3 完整明示文案
        assert out["via_snapshot"] is True          # 4 走 M27 快照续玩
        assert out["session_unchanged"] is True     # 5 副本会话原样
        assert out["session"] is session            # 6 同一引用（未清空）
        assert session["boss_state"]["hp"] == 280   # 7 残血原样（不重置）

    def test_player_ctx_battle_flags_refuse(self) -> None:
        """玩家战斗标志（委托 exit_dungeon_reset）→ 同样拒绝，分工明确。"""
        session = _make_session()
        out = non_combat_exit({"in_battle": True}, session)
        assert out["reset"] is False                # 1
        assert out["reason"] == "battle_in_progress"  # 2
        assert out["via_snapshot"] is True          # 3
        out2 = non_combat_exit({"battle_state": {"turn": 3}}, _make_session())
        assert out2["reset"] is False               # 4 battle_state 非空同样拦截

    def test_success_does_not_mutate_input_session(self) -> None:
        """纯函数：重置成功不改写传入会话（返回清空后新会话，对齐 M15）。"""
        session = _make_session()
        out = non_combat_exit({}, session)
        assert out["reset"] is True                 # 1
        assert out["session"] is not session        # 2 返回新会话（dict 重建）
        assert session["state"] == "BOSS_CHASE"     # 3 原会话未变
        assert session["boss_state"]["hp"] == 280   # 4 原残血未动

    def test_dataclass_session_form(self) -> None:
        """DungeonSession dataclass 形态等价重置（frozen 不可变，返回新实例）。"""
        sess = DungeonSession(
            dungeon_id="molten_dungeon",
            dungeon_type="boss",
            state="BOSS_CHASE",
            current_map="molten_core",
            cleared_maps=frozenset({"lava_tunnel"}),
            subquest_progress={"sq_1": 2},
            boss_state={"hp": 280, "max_hp": 1000, "pv": 150, "chasing": True},
            rest_count=2,
            external_anchor="world_map_07",
        )
        out = non_combat_exit({}, sess)
        assert out["reset"] is True                 # 1
        assert out["entry_hint"] == HINT            # 2 明示文案不缺席
        s2 = out["session"]
        assert s2.state == STATE_LEFT               # 3
        assert s2.boss_state == {}                  # 4 BOSS/残血全清
        assert sess.boss_state["hp"] == 280         # 5 原 dataclass 未变

    def test_death_leave_resets_too(self) -> None:
        """死亡后非战斗离开同样重置（死亡 ≠ 离开，离开即重置——m3 §4.4）。"""
        session = _make_session(
            state="DEAD_RECOVER",
            boss_state={"hp": 137, "max_hp": 1000, "chasing": True},
        )
        out = non_combat_exit({}, session)
        assert out["reset"] is True                 # 1
        assert out["session"]["boss_state"] == {}   # 2 残血全清
        assert out["via_snapshot"] is False         # 3
