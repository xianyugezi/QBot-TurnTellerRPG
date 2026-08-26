"""M3 批次7·路S：M24 安全区 + M25 /休息 + M26 休息≠离开 单元测试。

依据：
  - 细化_2a3_副本两型流程.md §2（M15 原地休息≠离开：位置/BOSS 血量/快照保留，rest_count+1；
    R16 安全区 /休息 恢复 + 冷却缩减 + 次数限制可配；R21 唯一恢复点；TC-2a3-15 非安全区拒绝）
  - m3_shared_contract §4.4（/休息 副本内语义（恢复/冷却缩减/次数限制）；≠ 离开副本
    （不重置、快照保留）；safe_zone 缺省=入口区）
  - 规划_路2a_地图副本.md M24（安全区=入口区 + safe_zone 配置，缺省=[入口区]；/休息 可用性
    判定=当前位置∈安全区 且 非战斗 且 非 BOSS 房）+ M25（HP/MP 各 20% 恢复可配；冷却 −N 回合；
    rest_per_dungeon 每副本上限 0=不限；验收：20% 恢复正确、冷却 −3 生效、第 4 次被拦、
    rest_per_dungeon=1 同副本第 2 次被拦）+ M26（休息不改变位置/不退出/不重置，进度/BOSS
    血量/快照保留）
  - 衔接 2a1c R3（入口区缺省即安全区）

断言分组：
  TestIsSafeZone     M24 安全区判定（入口区 / safe_zone 配置 str+list 多区 / maps 节点标记 /
     非安全区 / BOSS 房 / dataclass 形态 / 无当前位置）
  TestRestInDungeon  M25 /休息（20% 恢复 / 封顶 / full 模式 / 百分比可配 / 冷却缩减默认 1 +
     配置 N / 冷却表取源 / rest_count 递增 / 次数超限拒绝 / 0=不限 / 非安全区拒绝 / 纯函数）
  TestRestIsNotExit  M26 休息≠离开（位置/BOSS/子任务/换区上下文保留不重置 / 状态不变 /
     与离开重置对照 / 重置形态 kept=False）

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）。
"""

from __future__ import annotations

from qbot_rpg.core.dungeon import DungeonSession
from qbot_rpg.world.chase_resume import exit_dungeon_reset
from qbot_rpg.world.rest import (
    DEFAULT_COOLDOWN_REDUCTION,
    DEFAULT_HP_MP_PCT,
    DEFAULT_REST_LIMIT,
    MESSAGE_REST_LIMIT,
    MESSAGE_REST_NOT_SAFE,
    REST_MODE_FULL,
    STATE_LEFT,
    is_safe_zone,
    rest_in_dungeon,
    rest_is_not_exit,
)


# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _dungeon_def(**over) -> dict:
    """dungeon.json 条目（dict 形态；无 safe_zone → 缺省入口区=首图，2a1c R3）。"""
    base = {
        "id": "molten_dungeon",
        "type": "boss",
        "maps": ["molten_entrance", "lava_tunnel", "molten_corridor", "molten_core"],
        "boss_room": "molten_core",
        "boss": "ember_drake",
    }
    base.update(over)
    return base


def _session(**over) -> dict:
    """副本会话（dict 持久化形态 + dungeon_def 内嵌扩展键；可覆写任意字段）。"""
    base = {
        "dungeon_id": "molten_dungeon",
        "dungeon_type": "boss",
        "state": "PEACE_EXPLORE",
        "current_map": "molten_entrance",
        "cleared_maps": ["molten_entrance"],
        "subquest_progress": {"sq_1": 2},
        "boss_state": {"hp": 280, "max_hp": 1000},
        "rest_count": 1,
        "external_anchor": "world_map_07",
        "dungeon_def": _dungeon_def(),
    }
    base.update(over)
    return base


def _maps(**over) -> dict:
    """maps 模块容器（modules 形态；首图 = 入口区）。"""
    base = {
        "maps": [
            {"id": "molten_entrance", "name": "熔岩入口"},
            {"id": "lava_tunnel", "name": "熔岩隧道"},
            {"id": "molten_corridor", "name": "熔岩走廊"},
            {"id": "molten_core", "name": "BOSS 房"},
        ]
    }
    base.update(over)
    return base


def _player_ctx(**over) -> dict:
    """玩家上下文（hp/mp/max + 战斗快照 effect_cooldowns 冷却表；1b 冷却登记形态）。"""
    base = {
        "map_id": "molten_entrance",
        "hp": 500,
        "mp": 300,
        "max_hp": 1000,
        "max_mp": 500,
        "player": {"hp": 500, "mp": 300},
        "battle_state": {
            "effect_cooldowns": {"flame_burst": 3, "frost_aura": 1, "passive_heal": 0},
        },
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# M24：安全区判定
# ---------------------------------------------------------------------------


class TestIsSafeZone:
    def test_entry_area_is_safe(self) -> None:
        """入口区（= 副本 maps 首图，2a1c R3）恒为安全区：dungeon_def 内嵌形态。"""
        sess = _session(dungeon_def=_dungeon_def())  # 无 safe_zone 配置 → 缺省入口区
        assert is_safe_zone(sess) is True                    # 1 首图=入口区 → 安全

    def test_entry_fallback_from_maps_param(self) -> None:
        """无内嵌 dungeon_def 时，maps 入参首图即入口区（安全区缺省=[入口区]）。"""
        sess = _session(dungeon_def=None)
        assert is_safe_zone(sess, maps=_maps()) is True      # 2 maps[0] 入口区 → 安全

    def test_safe_zone_config_marks_non_entry_area(self) -> None:
        """safe_zone 配置把非首图标记为安全区（多安全区配置生效，M24 验收）。"""
        sess = _session(current_map="molten_rest",
                        dungeon_def=_dungeon_def(safe_zone="molten_rest"))
        assert is_safe_zone(sess) is True                    # 3 配置区 → 安全
        sess2 = _session(current_map="lava_tunnel",
                         dungeon_def=_dungeon_def(safe_zone="molten_rest"))
        assert is_safe_zone(sess2) is False                  # 4 未配置区 → 非安全

    def test_safe_zone_config_list_multi(self) -> None:
        """safe_zone 数组（多安全区，规划 M24）：并集 = 入口区 ∪ 配置区。"""
        sess = _session(current_map="a_rest",
                        dungeon_def=_dungeon_def(safe_zone=["a_rest", "b_rest"]))
        assert is_safe_zone(sess) is True                    # 5 配置区 a
        sess2 = _session(current_map="b_rest",
                         dungeon_def=_dungeon_def(safe_zone=["a_rest", "b_rest"]))
        assert is_safe_zone(sess2) is True                   # 6 配置区 b
        sess3 = _session(current_map="molten_entrance",
                         dungeon_def=_dungeon_def(safe_zone=["a_rest", "b_rest"]))
        assert is_safe_zone(sess3) is True                   # 7 入口区仍安全（并集）
        sess4 = _session(current_map="molten_corridor",
                         dungeon_def=_dungeon_def(safe_zone=["a_rest", "b_rest"]))
        assert is_safe_zone(sess4) is False                  # 8 普通区 → 非安全

    def test_maps_node_marker(self) -> None:
        """maps 节点级 safe_zone:true 标记（工程扩展键）→ 安全区。"""
        maps = _maps(maps=[
            {"id": "molten_entrance", "name": "熔岩入口"},
            {"id": "molten_rest", "name": "休息区", "safe_zone": True},
            {"id": "lava_tunnel", "name": "熔岩隧道"},
        ])
        sess = _session(current_map="molten_rest", dungeon_def=None)
        assert is_safe_zone(sess, maps=maps) is True         # 9 标记节点 → 安全
        sess2 = _session(current_map="lava_tunnel", dungeon_def=None)
        assert is_safe_zone(sess2, maps=maps) is False       # 10 无标记节点 → 非安全

    def test_boss_room_not_safe(self) -> None:
        """BOSS 房（未标记安全区）非安全区（M24：非 BOSS 房才可 /休息）。"""
        sess = _session(current_map="molten_core")           # 不在安全区集合
        assert is_safe_zone(sess) is False                   # 11 BOSS 房 → 非安全

    def test_no_current_map_false(self) -> None:
        """无当前位置（None）→ 非安全（可用性判定需当前位置）。"""
        sess = _session(current_map=None)
        assert is_safe_zone(sess) is False                   # 12 无位置 → False

    def test_dataclass_session_form(self) -> None:
        """DungeonSession dataclass 形态：位置在 maps 首图 → 安全；普通区 → 非安全。"""
        sess = DungeonSession(
            dungeon_id="molten_dungeon", dungeon_type="boss",
            state="PEACE_EXPLORE", current_map="molten_entrance",
            boss_state={"hp": 280, "max_hp": 1000}, rest_count=1,
        )
        assert is_safe_zone(sess, maps=_maps()) is True      # 13 入口区 → 安全
        sess2 = DungeonSession(
            dungeon_id="molten_dungeon", dungeon_type="boss",
            state="PEACE_EXPLORE", current_map="lava_tunnel", rest_count=1,
        )
        assert is_safe_zone(sess2, maps=_maps()) is False    # 14 普通区 → 非安全


# ---------------------------------------------------------------------------
# M25：/休息 副本内语义（恢复 / 冷却缩减 / 次数限制）
# ---------------------------------------------------------------------------


class TestRestInDungeon:
    def test_restores_hp_mp_default_pct(self) -> None:
        """HP/MP 部分恢复缺省各 20%（M25）：floor(max × 0.2)。"""
        out = rest_in_dungeon(_session(), _player_ctx())
        assert out["rested"] is True                         # 1 休息成功
        assert out["hp_restored"] == 200                     # 2 floor(1000×0.2)=200
        assert out["mp_restored"] == 100                     # 3 floor(500×0.2)=100
        assert out["hp_after"] == 700                        # 4 恢复后 HP
        assert out["mp_after"] == 400                        # 5 恢复后 MP
        assert DEFAULT_HP_MP_PCT == 0.2                      # 6 常量口径

    def test_restore_capped_at_max(self) -> None:
        """恢复封顶：不超过满值；已满资源恢复 0。"""
        out = rest_in_dungeon(_session(), _player_ctx(hp=900, mp=500))
        assert out["hp_restored"] == 100                     # 7 20%=200 封顶至 100
        assert out["hp_after"] == 1000                       # 8 不超过 max
        assert out["mp_restored"] == 0                       # 9 已满 → 0
        assert out["mp_after"] == 500                        # 10

    def test_restore_full_mode(self) -> None:
        """mode="full" 全满恢复（任务口径：全满或按配置）。"""
        out = rest_in_dungeon(_session(), _player_ctx(), cfg={"mode": REST_MODE_FULL})
        assert out["hp_restored"] == 500                     # 11 1000-500
        assert out["mp_restored"] == 200                     # 12 500-300
        assert out["hp_after"] == 1000                       # 13
        assert out["mp_after"] == 500                        # 14

    def test_restore_pct_configurable(self) -> None:
        """恢复百分比可配：hp_mp_pct 共用 / hp_pct+mp_pct 分资源。"""
        out = rest_in_dungeon(_session(), _player_ctx(), cfg={"hp_mp_pct": 0.5})
        assert out["hp_restored"] == 500                     # 15 floor(1000×0.5)
        out2 = rest_in_dungeon(_session(), _player_ctx(),
                               cfg={"hp_pct": 0.1, "mp_pct": 1.0})
        assert out2["hp_restored"] == 100                    # 16 floor(1000×0.1)
        assert out2["mp_restored"] == 200                    # 17 floor(500×1.0) 封顶 200

    def test_cooldown_reduction_default(self) -> None:
        """冷却缩减缺省 −1 回合（本路默认；1b effect_cooldowns 表）。"""
        out = rest_in_dungeon(_session(), _player_ctx())
        assert out["cooldown_reduction"] == DEFAULT_COOLDOWN_REDUCTION  # 18 默认 1
        assert out["cooldown_reduction"] == 1                # 19
        assert out["cooldowns_affected"] == ("flame_burst", "frost_aura")  # 20 仅冷却中技能
        assert out["cooldowns_after"] == {"flame_burst": 2, "frost_aura": 0,
                                          "passive_heal": 0}  # 21 缩减后（min 0）

    def test_cooldown_reduction_config(self) -> None:
        """冷却缩减量可配（M25：−N 回合）：N=3 全清零。"""
        out = rest_in_dungeon(_session(), _player_ctx(), cfg={"cooldown_reduction": 3})
        assert out["cooldown_reduction"] == 3                # 22 配置 N=3
        assert out["cooldowns_after"] == {"flame_burst": 0, "frost_aura": 0,
                                          "passive_heal": 0}  # 23 全部归零

    def test_cooldown_source_fallbacks(self) -> None:
        """冷却表取源回退：ctx.effect_cooldowns → player.cooldowns（【补白 7】）。"""
        out = rest_in_dungeon(_session(), _player_ctx(battle_state=None,
                                                      effect_cooldowns={"flame_burst": 2}))
        assert out["cooldowns_after"] == {"flame_burst": 1}  # 24 ctx 层冷却表
        out2 = rest_in_dungeon(_session(), _player_ctx(
            battle_state=None, player={"hp": 500, "cooldowns": {"frost_aura": 1}}))
        assert out2["cooldowns_after"] == {"frost_aura": 0}  # 25 player 层冷却表

    def test_rest_count_increments(self) -> None:
        """rest_count 递增（M15 迁移语义：rest_count+1，状态不变）。"""
        out = rest_in_dungeon(_session(rest_count=1), _player_ctx())
        assert out["rest_count"] == 2                        # 26 1 → 2
        out2 = rest_in_dungeon(_session(rest_count=2), _player_ctx())
        assert out2["rest_count"] == 3                       # 27 2 → 3

    def test_limit_reached_rejects(self) -> None:
        """次数超限拒绝（M25 验收：rest_per_dungeon=1 时同副本第 2 次被拦）。"""
        out = rest_in_dungeon(_session(rest_count=1), _player_ctx(),
                              cfg={"rest_limit": 1})
        assert out["rested"] is False                        # 28 拒绝
        assert out["reason"] == "limit_reached"              # 29
        assert out["message"] == MESSAGE_REST_LIMIT          # 30 「休息次数已用完」
        assert out["limit_reached"] is True                  # 31
        assert out["rest_count"] == 1                        # 32 不递增
        assert out["hp_restored"] == 0                       # 33 不恢复

    def test_limit_zero_unlimited(self) -> None:
        """rest_limit=0 不限（M25：0=不限）。"""
        out = rest_in_dungeon(_session(rest_count=99), _player_ctx(),
                              cfg={"rest_limit": 0})
        assert out["rested"] is True                         # 34 0=不限
        assert out["rest_count"] == 100                      # 35
        assert DEFAULT_REST_LIMIT == 3                       # 36 默认上限常量 3

    def test_not_safe_zone_rejected(self) -> None:
        """非安全区拒绝 /休息（2a3 R16 / TC-2a3-15）。"""
        sess = _session(current_map="lava_tunnel")           # 普通区
        out = rest_in_dungeon(sess, _player_ctx())
        assert out["rested"] is False                        # 37 拒绝
        assert out["reason"] == "not_safe_zone"              # 38
        assert out["message"] == MESSAGE_REST_NOT_SAFE       # 39 非安全区文案
        assert out["rest_count"] == 1                        # 40 不递增

    def test_pure_no_input_mutation(self) -> None:
        """纯函数：不改写 player_ctx 与 session（恢复/冷却为计算值，落库归接线层）。"""
        ctx = _player_ctx()
        sess = _session(rest_count=1)
        rest_in_dungeon(sess, ctx)
        assert ctx["hp"] == 500                              # 41 HP 未被改写
        assert ctx["battle_state"]["effect_cooldowns"]["flame_burst"] == 3  # 42 冷却表未改写
        assert sess["rest_count"] == 1                       # 43 会话未改写

    def test_no_max_no_restore(self) -> None:
        """满值不可解 → 恢复量 0（【补白 5】：不越权猜测属性管线）。"""
        out = rest_in_dungeon(_session(), _player_ctx(max_hp=None, max_mp=None))
        assert out["hp_restored"] == 0                       # 44
        assert out["mp_restored"] == 0                       # 45


# ---------------------------------------------------------------------------
# M26：休息 ≠ 离开（不重置、快照保留）
# ---------------------------------------------------------------------------


class TestRestIsNotExit:
    def test_rest_keeps_position_boss_subquest_chase(self) -> None:
        """休息保留位置/BOSS 血量/子任务进度/换区上下文（chase_ctx），不触发重置。"""
        sess = _session(
            state="BOSS_CHASE",
            current_map="molten_corridor",
            subquest_progress={"sq_1": 2, "sq_2": 5},
            boss_state={"hp": 137, "max_hp": 1000, "pv": 150, "chasing": True},
            chase_ctx={"target": "molten_core", "chasing": True},
            rest_count=1,
        )
        out = rest_is_not_exit(sess)
        assert out["kept"] is True                           # 46 未离开/未重置
        assert out["state"] == "BOSS_CHASE"                  # 47 状态保留
        assert out["current_map"] == "molten_corridor"       # 48 位置保留
        assert out["boss_state_preserved"] is True           # 49 BOSS 血量保留
        assert out["subquest_progress_preserved"] is True    # 50 子任务保留
        assert out["chase_ctx_preserved"] is True            # 51 换区上下文保留
        assert out["reset_triggered"] is False               # 52 不触发重置

    def test_rest_state_unchanged(self) -> None:
        """/休息 不改变副本状态（M15：S0/S1/S3 原地休息，状态不变）。"""
        out = rest_in_dungeon(_session(state="PEACE_EXPLORE", rest_count=2), _player_ctx())
        assert out["state"] == "PEACE_EXPLORE"               # 53 状态不变
        assert out["current_map"] == "molten_entrance"       # 54 位置不变

    def test_boss_hp_untouched_by_rest(self) -> None:
        """休息不触碰 BOSS 状态（M26：休息后 BOSS 房状态未受影响）。"""
        sess = _session(boss_state={"hp": 137, "max_hp": 1000, "pv": 150})
        rest_in_dungeon(sess, _player_ctx())
        assert sess["boss_state"] == {"hp": 137, "max_hp": 1000, "pv": 150}  # 55 原样

    def test_reset_session_not_kept(self) -> None:
        """离开重置形态（S7 + 位置清空 + 进度清空）→ kept=False（与休息相反）。"""
        sess = _session(state=STATE_LEFT, current_map=None, boss_state={},
                        subquest_progress={}, rest_count=0)
        out = rest_is_not_exit(sess)
        assert out["kept"] is False                          # 56 重置形态非「保留」
        assert out["boss_state_preserved"] is False          # 57 BOSS 已清
        assert out["state"] == STATE_LEFT                    # 58

    def test_rest_vs_leave_reset_contrast(self) -> None:
        """对照：休息保留进度，离开（exit_dungeon_reset）全清——两语义互斥（M15/M26）。"""
        sess = _session(
            state="BOSS_CHASE",
            current_map="molten_corridor",
            subquest_progress={"sq_1": 2},
            boss_state={"hp": 137, "max_hp": 1000},
            rest_count=2,
        )
        assert rest_is_not_exit(sess)["kept"] is True        # 59 休息语义 → 保留
        cleared = exit_dungeon_reset(sess, {})
        assert cleared["reset"] is True                      # 60 离开 → 重置
        assert rest_is_not_exit(cleared["session"])["kept"] is False  # 61 重置后非保留
        assert rest_is_not_exit(cleared["session"])["boss_state_preserved"] is False  # 62
