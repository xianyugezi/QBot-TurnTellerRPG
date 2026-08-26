"""M3 批次6·路R：M14 换区续战装配 + M15 离开副本重置 单元测试。

依据：
  - 细化_2a2_换区追击流程.md §2-4（PV 半恢复 R9/R10/R11 满值口径向下取整 + 门禁语义层数保留
    破防全量爆发；血量保持不重置 R12/R13；追到续战 R19-R21 残血+PV 半值+开场技）+ §5
    （离开副本重置 R24/R25：非战斗离开全清、死亡≠离开但离开即重置、恢复入口明示）
  - m3_shared_contract §3.2（续战 BOSS 残血保持 + PV 半恢复向下取整 + 开场技 + 血量不重置；
    门禁语义 debuff 层数保留）+ §4.4（快照续玩 ai_state+combo_state 全保留；死亡 ≠ 离开，
    离开即重置）
  - 规划_路2a_地图副本.md M14（换区后战斗续接）/ M15（离开副本重置界定）
  - 衔接细化_1g3（快照续战）/ 1g4 J-01（换区 PV 恢复裁决）/ 1f（开场技 battle_start）

断言分组：
  TestPrepareResumeBattle  M14 续战装配（追到全量标记 / 残血保持不重置 / PV 半值 floor 计算 /
     恢复比例取源 / PV 满值源优先级 / 快照透传 ai_state 保留 / 未追到拒绝 / 无快照非就绪）
  TestExitDungeonReset     M15 离开重置（非战斗离开全清 BOSS/残血/子任务/休息/换区上下文 /
     死亡离开同样重置 / 战斗中拒绝 / dataclass 形态 / 空会话离开）

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）。
"""

from __future__ import annotations

from qbot_rpg.core.dungeon import DungeonSession
from qbot_rpg.world.chase_resume import (
    MESSAGE_HINT_BATTLE_ONGOING,
    MESSAGE_HINT_LEAVE_RESET,
    STATE_LEFT,
    exit_dungeon_reset,
    prepare_resume_battle,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


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


def _battle_snapshot(**over) -> dict:
    """进行中战斗快照（1g4 BattleSnapshot dict 形态，含 ai_state/combo_state）。"""
    base = {
        "session_type": "battle",
        "turn": 9,
        "player": {"name": "P", "hp": 500, "max_hp": 1000},
        "enemy": {"name": "ember_drake", "hp": 137, "max_hp": 1000},
        "combo_state": {"step": 2, "top": 4},
        "ai_state": {"phase": 3, "charging": True, "chain_id": "flame_burst"},
        "status_state": {},
        "marks_state": {},
        "formula_state": {"random_seed": 42},
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# M14：追到续战装配
# ---------------------------------------------------------------------------


class TestPrepareResumeBattle:
    def test_caught_assembles_full_resume_context(self) -> None:
        """追到（caught:True，路Q pursue 捕获返回形态）→ 全量续战标记 + continue_data 收口。"""
        chase_ctx = {
            "caught": True,
            "target_map": "molten_core",
            "continue_data": {"pv_half_value": 150, "pv_recover": 0.5,
                              "boss_hp": 280, "boss_max_hp": 1000},
        }
        enemy_state = {"pv": 300, "pv_max": 300}
        out = prepare_resume_battle(chase_ctx, enemy_state, _battle_snapshot())
        assert out["resume"] is True                  # 1 续战标记
        assert out["hp_keep"] is True                 # 2 残血保持
        assert out["pv_half"] is True                 # 3 PV 半恢复
        assert out["opening_skill"] is True           # 4 开场技标记
        assert out["battle_ready"] is True            # 5 快照续接就绪
        assert out["pv_half_value"] == 150            # 6 floor(300×0.5)，continue_data 权威
        assert out["pv_recover"] == 0.5               # 7 恢复比例
        assert out["timing"] == "chase_continue"      # 8 续战语义
        assert out["boss_hp"] == 280                  # 9 残血透传（enemy 无 hp → continue_data 兜底）
        assert out["chase_target"] == "molten_core"   # 10 换区上下文透传（target_map 契约键）

    def test_hp_kept_residual_not_reset(self) -> None:
        """血量不重置（R12/R13）：残血原值透传，不出现回满；入参纯函数不改写。"""
        enemy_state = {"hp": 137, "max_hp": 1000, "pv_max": 300}
        out = prepare_resume_battle({"caught": True}, enemy_state)
        assert out["boss_hp"] == 137                  # 1 残血原值
        assert out["boss_hp"] != out["boss_max_hp"]   # 2 血量不重置为满
        assert enemy_state["hp"] == 137               # 3 入参未被改写（纯函数）

    def test_pv_half_value_floor_odd(self) -> None:
        """PV 半值向下取整（2a2 §2.1：floor(pv_max × pv_recover)，奇数/普通/缺省）。"""
        out = prepare_resume_battle({"caught": True}, {"pv_max": 300, "pv": 0})
        assert out["pv_half_value"] == 150            # 1 BOSS 300 破防 → 150
        out2 = prepare_resume_battle({"caught": True}, {"pv_max": 201, "pv": 0})
        assert out2["pv_half_value"] == 100           # 2 奇数 201 破防 → 100（向下取整验证）
        out3 = prepare_resume_battle({"caught": True}, {"pv_max": 15, "pv": 0})
        assert out3["pv_half_value"] == 7             # 3 普通怪 15 破防 → 7
        out4 = prepare_resume_battle({"caught": True}, {})
        assert out4["pv_half_value"] == 0             # 4 无 PV 源 → 0

    def test_pv_recover_source(self) -> None:
        """恢复比例取源：chase_ctx.pv_recover > zone_change.pv_recover > 缺省 0.5。"""
        out = prepare_resume_battle({"caught": True, "pv_recover": 0.25}, {"pv_max": 300, "pv": 0})
        assert out["pv_half_value"] == 75             # 1 floor(300×0.25)=75
        out2 = prepare_resume_battle(
            {"caught": True, "zone_change": {"pv_recover": 0.4}}, {"pv_max": 300, "pv": 0})
        assert out2["pv_half_value"] == 120           # 2 破防：0+floor(300×0.4)=120
        out3 = prepare_resume_battle({"caught": True, "pv_recover": "bad"}, {"pv_max": 300})
        assert out3["pv_recover"] == 0.5              # 3 非法恢复比 → 缺省

    def test_continue_data_precedence(self) -> None:
        """PV 值源优先级：路O continue_data（on_chase_continue）> 顶层键 > enemy_state 推算（缺失量口径）。"""
        out = prepare_resume_battle(
            {"caught": True, "continue_data": {"pv_half_value": 160, "pv_recover": 0.25}},
            {"pv_max": 300},
        )
        assert out["pv_half_value"] == 160            # 1 continue_data 权威（补白 2）
        assert out["pv_recover"] == 0.25              # 2 continue_data 恢复比
        out2 = prepare_resume_battle({"caught": True, "pv_half_value": 130}, {"pv_max": 300})
        assert out2["pv_half_value"] == 130           # 3 顶层键次优先
        out3 = prepare_resume_battle({"caught": True}, {"pv": 240, "max_pv": 250})
        assert out3["pv_half_value"] == 245           # 4 缺失量口径：240+floor(10×0.5)=245（未破防回升）

    def test_battle_snapshot_passthrough_ai_state(self) -> None:
        """战斗快照续接（1g4 战斗会话，m3 §4.4）：battle_state 透传，ai_state/combo_state 保留。"""
        snap = _battle_snapshot()
        out = prepare_resume_battle(
            {"caught": True},
            {"hp": 137, "max_hp": 1000, "pv_max": 300},
            snap,
        )
        assert out["battle_state"] is snap            # 1 快照透传（同一引用）
        assert out["ai_state"] is snap["ai_state"]    # 2 ai_state 保留（1g4 会话语义）
        assert out["ai_state"]["phase"] == 3          # 3 逐字段一致
        assert out["combo_state"] == snap["combo_state"]  # 4 combo_state 保留
        assert out["battle_ready"] is True            # 5

    def test_not_caught_refuses(self) -> None:
        """未追到（caught 非真）→ 拒绝装配续战（M13 错失窗口）。"""
        out = prepare_resume_battle({"caught": False}, {"pv_max": 300}, _battle_snapshot())
        assert out["resume"] is False                 # 1 不续战
        assert out["battle_ready"] is False           # 2
        assert out["reason"] == "not_caught"          # 3

    def test_missing_snapshot_not_ready(self) -> None:
        """无进行中战斗快照：battle_ready=False（补白 5），resume 语义仍成立。"""
        out = prepare_resume_battle(
            {"caught": True}, {"hp": 137, "max_hp": 1000, "pv_max": 300})
        assert out["resume"] is True                  # 1 续战语义成立
        assert out["battle_ready"] is False           # 2 无快照 → 非就绪
        assert out["reason"] == "missing_snapshot"    # 3


# ---------------------------------------------------------------------------
# M15：离开副本重置
# ---------------------------------------------------------------------------


class TestExitDungeonReset:
    def test_non_battle_leave_resets_all(self) -> None:
        """非战斗离开 → 副本全清（BOSS 状态/残血/子任务/休息/换区上下文），回外部锚点。"""
        session = _make_session()
        out = exit_dungeon_reset(session, {"map_id": "molten_core"})
        assert out["reset"] is True                   # 1 重置信号
        assert out["state"] == STATE_LEFT             # 2 S7 离开态
        assert out["external_anchor"] == "world_map_07"  # 3 回外部锚点（R8）
        assert out["message_hint"] == MESSAGE_HINT_LEAVE_RESET  # 4 恢复入口明示 R25
        s2 = out["session"]
        assert s2["state"] == STATE_LEFT              # 5
        assert s2["current_map"] is None              # 6 位置清空
        assert s2["subquest_progress"] == {}          # 7 子任务进度清空
        assert s2["boss_state"] == {}                 # 8 BOSS 状态/残血全清
        assert s2["rest_count"] == 0                  # 9 休息次数清零
        assert "chasing" not in s2                    # 10 换区上下文顶层清空
        assert s2["dungeon_id"] == "molten_dungeon"   # 11 元数据保留
        assert session["boss_state"]["hp"] == 280     # 12 原会话未被原地清空（纯函数）

    def test_death_leave_resets_too(self) -> None:
        """死亡离开同样重置（死亡 ≠ 离开，但离开即重置——2a2 §5.2 / m3 §4.4）。"""
        session = _make_session(
            state="DEAD_RECOVER",
            boss_state={"hp": 137, "max_hp": 1000, "chasing": True},
        )
        out = exit_dungeon_reset(session, {})
        assert out["reset"] is True                   # 1 死亡后离开 → 重置
        assert out["session"]["boss_state"] == {}     # 2 残血全清
        assert "chasing" not in out["session"]        # 3 换区上下文清空

    def test_battle_in_progress_refuses(self) -> None:
        """战斗中离开拒绝（战斗中断 ≠ 离开，走快照续玩 M27；R25 提示）。"""
        session = _make_session()
        out = exit_dungeon_reset(session, {"in_battle": True})
        assert out["reset"] is False                  # 1 战斗中拒绝重置
        assert out["reason"] == "battle_in_progress"  # 2
        assert out["message_hint"] == MESSAGE_HINT_BATTLE_ONGOING  # 3 「战斗中断可续玩…」
        assert out["session"] is session              # 4 会话原样保留（残血不动）

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
        out = exit_dungeon_reset(sess, {})
        assert out["reset"] is True                   # 1 重置
        s2 = out["session"]
        assert s2.state == STATE_LEFT                 # 2
        assert s2.boss_state == {}                    # 3 BOSS/残血全清
        assert s2.rest_count == 0                     # 4 休息清零
        assert sess.boss_state["hp"] == 280           # 5 原 dataclass 未变（不可变）

    def test_empty_fresh_session_leave(self) -> None:
        """入口态（S0 空会话）直接离开同样重置（补白：S0 非战斗离开同属离开=重置）。"""
        out = exit_dungeon_reset(
            _make_session(state="ENTRY", current_map="lava_tunnel", cleared_maps=[],
                          subquest_progress={}, boss_state={}, rest_count=0),
            {},
        )
        assert out["reset"] is True                   # 1
        assert out["session"]["state"] == STATE_LEFT  # 2
        assert out["message_hint"] == MESSAGE_HINT_LEAVE_RESET  # 3
