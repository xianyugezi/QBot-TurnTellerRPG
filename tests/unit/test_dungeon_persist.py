"""M3 批次7·路U：M29 副本内死亡处理 + M30 副本会话持久化 单元测试
（qbot_rpg/world/dungeon_persist.py）。

依据：
  - 细化_2a3_副本两型流程.md §2（S6 死亡复活态 + 迁移表 M9/M10/M11/M14）+ §4（死亡处理
    R26-R32：复活点默认入口可配 / penalty 三档 / checkpoint 回退 R29 自动降级 / BOSS
    状态 keep-reset R30 / 死亡≠离开 R31 / 虚弱禁入非安全区含 BOSS 房）
  - m3_shared_contract §4.4（副本内死亡：复活点复活 + 虚弱禁入非安全区；死亡≠离开；
    副本会话持久化：当前区域/已清/子任务/换区上下文/BOSS/休息次数随存档，清理时机=
    通关/重置，content_pack_id+version 防跨包串档）
  - 规划_路2a_地图副本.md M29（复活点/checkpoint/BOSS 状态/虚弱）+ M30（会话持久化）

断言分组：
  TestOnDungeonDeath       M29 死亡处理（默认入口复活 + BOSS 残血保留 / revive_point
      配置优先 / checkpoint 回退 / 未配 checkpoint 降级重置 / penalty 三档 / boss_state
      reset / BFS 兜底衔接 battle_boundary / 非可达状态拒绝 / 虚弱标记与禁入非安全区
      含 BOSS 房 / dataclass 输入返回持久化 dict）
  TestSaveLoadSession      M30 持久化（save 全字段序列化含换区上下文 / round-trip 还原 /
      dataclass 形态 / 缺补默认 / content_pack 不匹配拒绝不串档 / 非法 store）
  TestClearSession         M30 清理（容器剔除 / 缺键 / 单文档形态 / 纯函数不改入参）
  TestWeakenedChecks       虚弱判定（标记 + 时间态过期）与禁入非安全区检查

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）。
"""

from __future__ import annotations

import dataclasses
from typing import cast

from qbot_rpg.content.dungeon_models import DungeonDef
from qbot_rpg.core.dungeon import S0, S1, S5, S6, S7, DungeonSession
from qbot_rpg.world.dungeon_persist import (
    BOSS_STATE_KEEP,
    BOSS_STATE_RESET,
    PENALTY_CHECKPOINT,
    PENALTY_NONE,
    PENALTY_RESET,
    SCHEMA_VERSION,
    STATE_DEAD_RECOVER,
    WEAK_DURATION_DEFAULT_SEC,
    WEAKENED_KEY,
    WEAK_UNTIL_KEY,
    check_weakened_entry,
    clear_dungeon_session,
    is_weakened,
    load_dungeon_session,
    on_dungeon_death,
    save_dungeon_session,
)

NOW = "2026-08-26T12:00:00+00:00"
SECS = 60  # 复活后 1 分钟（与 WEAK_DURATION_DEFAULT_SEC 对齐；防过期误判取 59）


# -------------------------------------------------------------------------------------
# 夹具辅助
# -------------------------------------------------------------------------------------


def _dungeon_def(**over) -> DungeonDef:
    """BOSS 版副本定义（raw dict）；over 覆写 death_policy/checkpoints 等。"""
    base = {
        "id": "molten_dungeon_boss",
        "name": "熔岩洞窟·讨伐",
        "type": "boss",
        "maps": ["rubble_field", "crag_den", "lava_tunnel"],
        "safe_zone": "rubble_field",
        "boss_room": "lava_tunnel",
        "boss": "ember_drake",
    }
    base.update(over)
    return cast(DungeonDef, DungeonDef.from_entry(base))


def _maps_connected() -> list:
    """连通地图集：rubble_field(安全区) ↔ crag_den ↔ lava_tunnel(BOSS 房)。"""
    return [
        {"id": "rubble_field",
         "exits": {"up": {"to": "crag_den", "mode": "bidirectional"}}},
        {"id": "crag_den",
         "exits": {"down": {"to": "rubble_field", "mode": "bidirectional"},
                   "left": {"to": "lava_tunnel", "mode": "bidirectional"}}},
        {"id": "lava_tunnel",
         "exits": {"right": {"to": "crag_den", "mode": "bidirectional"}}},
    ]


def _maps_isolated() -> list:
    """死亡图（lava_tunnel）与安全区不连通（仅 hidden 通道）→ BFS 兜底 default。"""
    return [
        {"id": "rubble_field",
         "exits": {"up": {"to": "crag_den", "mode": "bidirectional"}}},
        {"id": "crag_den",
         "exits": {"down": {"to": "rubble_field", "mode": "bidirectional"}}},
        {"id": "lava_tunnel",
         "exits": {"right": {"to": "crag_den", "mode": "hidden"}}},
    ]


def _session(**over) -> dict:
    """副本会话（持久化 dict 形态）：决战态死战残血 BOSS。"""
    base = {
        "dungeon_id": "molten_dungeon_boss",
        "dungeon_type": "boss",
        "state": "FINAL_DEATHMATCH",
        "current_map": "lava_tunnel",
        "cleared_maps": ["rubble_field", "crag_den", "lava_tunnel"],
        "subquest_progress": {"sq_1": 2},
        "boss_state": {"hp": 280, "max_hp": 1000, "chasing": True},
        "rest_count": 2,
        "external_anchor": "world_map_07",
        "content_pack_id": "cp1",
        "content_pack_version": "1.0",
    }
    base.update(over)
    return base


def _ctx(**over) -> dict:
    """最小玩家上下文（世界图节点位置 + 内容包标识）。"""
    base = {
        "map_id": "lava_tunnel",
        "player": {"map_id": "lava_tunnel", "name": "阿伟"},
        "content_pack_id": "cp1",
        "content_pack_version": "1.0",
    }
    base.update(over)
    return base


def _dataclass_session(**over) -> DungeonSession:
    """DungeonSession dataclass 形态会话（决战态）；over 经 replace 覆写。"""
    base = DungeonSession(
        dungeon_id="molten_dungeon_boss",
        dungeon_type="boss",
        state="FINAL_DEATHMATCH",
        current_map="lava_tunnel",
        cleared_maps=frozenset({"rubble_field", "crag_den", "lava_tunnel"}),
        subquest_progress={"sq_1": 2},
        boss_state={"hp": 280, "max_hp": 1000},
        rest_count=2,
        external_anchor="world_map_07",
        content_pack_id="cp1",
        content_pack_version="1.0",
    )
    if over:
        return dataclasses.replace(base, **over)
    return base


# -------------------------------------------------------------------------------------
# M29：副本内死亡处理
# -------------------------------------------------------------------------------------


class TestOnDungeonDeath:
    def test_death_default_revive_safe_zone_boss_kept(self) -> None:
        """缺省配置（无 death_policy/checkpoints）：入口=safe_zone 复活 + 虚弱标记。"""
        ctx = _ctx()
        sess = _session()
        r = on_dungeon_death(ctx, sess, dungeon_def=_dungeon_def(),
                             maps=_maps_connected(), now_iso=NOW)
        assert r["revived"] is True                              # 1 复活成功
        assert r["state"] == STATE_DEAD_RECOVER                  # 2 S6 死亡复活态
        assert r["respawn_point"] == "rubble_field"              # 3 默认复活点=入口=safe_zone
        assert r["respawn_source"] == "bfs"                      # 4 BFS 兜底衔接 battle_boundary
        assert r["weakened"] is True                             # 5 虚弱标记
        assert r["weak_until"] is not None                       # 6 时间态弱虚截止
        assert r["session"]["state"] == S6                       # 7 会话状态 → S6
        assert r["session"]["current_map"] == "rubble_field"     # 8 会话落位复活点
        assert ctx["map_id"] == "rubble_field"                   # 9 玩家位置 → 复活点
        assert ctx[WEAKENED_KEY] is True                         # 10 ctx 虚弱镜像

    def test_death_revive_point_config_priority(self) -> None:
        """R27：death_policy.revive_point 显式配置优先（可指向 checkpoint 区/任意区域）。"""
        ddef = _dungeon_def(death_policy={"revive_point": "lava_tunnel"})
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["respawn_point"] == "lava_tunnel"               # 1 复活点=配置值
        assert r["respawn_source"] == "revive_point"             # 2 来源=显式配置
        assert r["revived"] is True                              # 3

    def test_death_revive_point_checkpoint_area(self) -> None:
        """checkpoint 区复活经 revive_point 显式指向（R27「如 checkpoint 区」）+ 进度回退。"""
        ddef = _dungeon_def(death_policy={"revive_point": "crag_den",
                                          "penalty": PENALTY_CHECKPOINT},
                            checkpoints=["crag_den"])
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["respawn_point"] == "crag_den"                  # 1 复活于 checkpoint 区（配置指向）
        assert r["respawn_source"] == "revive_point"             # 2 来源=revive_point
        assert r["progress"]["rolled_back"] is True              # 3 进度仍回退到 checkpoint
        assert r["session"]["cleared_maps"] == ["crag_den", "rubble_field"]  # 4 其后图需重探
        assert r["session"]["boss_state"]["hp"] == 280           # 5 BOSS 残血保留

    def test_death_checkpoint_reached_rolls_back(self) -> None:
        """M29 checkpoint 回退（TC-2a3-10）：复活于入口、进度回退到 checkpoint、BOSS 保留。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_CHECKPOINT},
                            checkpoints=["crag_den"])
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["respawn_point"] == "rubble_field"              # 1 复活于入口（安全区，TC-2a3-10）
        assert r["respawn_source"] == "bfs"                      # 2 BFS 兜底
        assert r["progress"]["rolled_back"] is True              # 3 已清区域回退
        assert r["progress"]["checkpoint_zone"] == "crag_den"    # 4 回退锚点
        assert r["progress"]["degraded_to_reset"] is False       # 5 未降级
        assert r["session"]["cleared_maps"] == ["crag_den", "rubble_field"]  # 6 其后图需重探
        assert r["session"]["boss_state"]["hp"] == 280           # 7 BOSS 残血保留
        assert r["session"]["subquest_progress"] == {"sq_1": 2}  # 8 子任务保留
        assert r["session"]["rest_count"] == 2                   # 9 休息次数保留

    def test_death_checkpoint_not_reached_degrades_to_reset(self) -> None:
        """R29：配置 checkpoints 但未到达 → 自动降级为重置副本（不悬空）。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_CHECKPOINT},
                            checkpoints=["crag_den"])
        sess = _session(cleared_maps=["rubble_field"])           # 未到达 crag_den
        r = on_dungeon_death(_ctx(), sess, dungeon_def=ddef, maps=_maps_connected())
        assert r["respawn_point"] == "rubble_field"              # 1 复活于入口安全区
        assert r["progress"]["degraded_to_reset"] is True        # 2 降级重置
        assert r["progress"]["rolled_back"] is False             # 3 无回退
        assert r["session"]["cleared_maps"] == []                # 4 进度全清
        assert r["session"]["boss_state"] == {}                  # 5 BOSS 满状态重打
        assert r["boss_state_preserved"] is False                # 6 BOSS 不保留
        assert r["session"]["rest_count"] == 0                   # 7 休息清零

    def test_death_checkpoint_missing_config_degrades_to_reset(self) -> None:
        """R29：缺省 penalty=checkpoint 但未配 checkpoints → 自动降级重置。"""
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=_dungeon_def(),
                             maps=_maps_connected())
        assert r["progress"]["degraded_to_reset"] is True        # 1 自动降级
        assert r["session"]["cleared_maps"] == []                # 2 进度全清
        assert r["session"]["subquest_progress"] == {}           # 3 子任务全清
        assert r["session"]["boss_state"] == {}                  # 4 BOSS 全清
        assert r["boss_state_preserved"] is False                # 5
        assert r["session"]["rest_count"] == 0                   # 6

    def test_death_penalty_none_keeps_progress(self) -> None:
        """R28 ③ penalty=none（低难探索）：仅复活，进度/BOSS 原样保留。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_NONE})
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["respawn_point"] == "rubble_field"              # 1 复活于安全区
        assert r["progress"]["penalty"] == PENALTY_NONE          # 2 档位=none
        assert r["session"]["cleared_maps"] == ["crag_den", "lava_tunnel", "rubble_field"]  # 3 已清原样
        assert r["session"]["subquest_progress"] == {"sq_1": 2}  # 4 子任务原样
        assert r["session"]["rest_count"] == 2                   # 5 休息原样
        assert r["boss_state_preserved"] is True                 # 6 BOSS 原样
        assert r["session"]["boss_state"]["hp"] == 280           # 7 残血保留

    def test_death_penalty_reset_clears_all(self) -> None:
        """R28 ② penalty=reset：等价离开重置，满状态重打（TC-2a3-11）。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_RESET})
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["progress"]["penalty"] == PENALTY_RESET         # 1 档位=reset
        assert r["session"]["cleared_maps"] == []                # 2 进度全清
        assert r["session"]["subquest_progress"] == {}           # 3 子任务全清
        assert r["session"]["boss_state"] == {}                  # 4 BOSS 全清
        assert r["boss_state_preserved"] is False                # 5
        assert r["session"]["rest_count"] == 0                   # 6 休息清零
        assert r["respawn_point"] == "rubble_field"              # 7 入口复活

    def test_death_boss_state_reset_mode(self) -> None:
        """R30：boss_state=reset → BOSS 满状态重打（进度按 penalty 档位处理）。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_NONE,
                                          "boss_state": BOSS_STATE_RESET})
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=ddef, maps=_maps_connected())
        assert r["boss_state_preserved"] is False                # 1 BOSS 不保留
        assert r["session"]["boss_state"] == {}                  # 2 满状态重打
        assert r["session"]["cleared_maps"] == ["crag_den", "lava_tunnel", "rubble_field"]  # 3 进度保留
        assert r["session"]["subquest_progress"] == {"sq_1": 2}  # 4 子任务保留

    def test_death_bfs_finds_nearest_safe_zone(self) -> None:
        """BFS 兜底（衔接 battle_boundary DEATH-07）：死亡图连通 → 最近安全区。"""
        r = on_dungeon_death(_ctx(map_id="crag_den"),
                             _session(current_map="crag_den", state="PEACE_EXPLORE"),
                             dungeon_def=_dungeon_def(), maps=_maps_connected())
        assert r["respawn_point"] == "rubble_field"              # 1 BFS 最近安全区
        assert r["respawn_source"] == "bfs"                      # 2

    def test_death_bfs_unreachable_defaults_safe_zone(self) -> None:
        """BFS 兜底：死亡图与安全区不连通（hidden 通道不可依赖）→ default=safe_zone。"""
        r = on_dungeon_death(_ctx(), _session(), dungeon_def=_dungeon_def(),
                             maps=_maps_isolated())
        assert r["respawn_point"] == "rubble_field"              # 1 default=安全区
        assert r["respawn_source"] == "bfs"                      # 2

    def test_death_ineligible_state_refused(self) -> None:
        """非死亡可达状态（S0/S5/S6/S7）拒绝：不改 ctx、不产新会话。"""
        for state in (S0, S5, S6, S7):
            ctx = _ctx()
            sess = _session(state=state)
            r = on_dungeon_death(ctx, sess, dungeon_def=_dungeon_def(),
                                 maps=_maps_connected())
            assert r["revived"] is False                         # 1 拒绝
            assert "不能响应副本内死亡" in r["reason"]            # 2 原因指向迁移表
            assert r["session"] is sess                          # 3 原会话不变
            assert ctx["map_id"] == "lava_tunnel"                # 4 ctx 未改
            assert ctx.get(WEAKENED_KEY) is not True             # 5 无虚弱标记

    def test_death_weakened_ban_and_expiry(self) -> None:
        """虚弱期禁入非安全区（含 BOSS 房）+ 虚弱结束后恢复。"""
        ctx = _ctx()
        r = on_dungeon_death(ctx, _session(), dungeon_def=_dungeon_def(),
                             maps=_maps_connected(), now_iso=NOW)
        sess = r["session"]
        # 虚弱中：安全区可滞留，非安全区（含 BOSS 房）禁入
        assert is_weakened(sess, ctx) is True                    # 1 虚弱判定 True
        assert check_weakened_entry(sess, "rubble_field", _dungeon_def(), ctx)["ok"] is True  # 2 安全区放行
        b1 = check_weakened_entry(sess, "crag_den", _dungeon_def(), ctx)
        assert b1["ok"] is False                                 # 3 非安全区拦截
        assert "非安全区" in b1["reason"]                          # 4 原因含 BOSS 房口径
        b2 = check_weakened_entry(sess, "lava_tunnel", _dungeon_def(), ctx)
        assert b2["ok"] is False                                 # 5 BOSS 房拦截
        # 虚弱时间态：超过 weak_until → 结束，恢复探索
        after = "2026-08-26T12:05:00+00:00"
        assert is_weakened(sess, ctx, after) is False            # 6 时间过期 → 不虚弱
        assert check_weakened_entry(sess, "crag_den", _dungeon_def(), ctx, after)["ok"] is True  # 7 恢复进入

    def test_death_dataclass_input_returns_dict_form(self) -> None:
        """DungeonSession dataclass 输入：死亡后返回持久化 dict 形态（含 weakened 标记）。"""
        ddef = _dungeon_def(death_policy={"penalty": PENALTY_CHECKPOINT},
                            checkpoints=["crag_den"])
        ds = _dataclass_session()
        r = on_dungeon_death(_ctx(), ds, dungeon_def=ddef,
                             maps=_maps_connected(), now_iso=NOW)
        assert isinstance(r["session"], dict)                    # 1 持久化 dict 形态
        assert r["session"][WEAKENED_KEY] is True                # 2 weakened 标记随会话
        rebuilt = DungeonSession.from_dict(r["session"])
        assert rebuilt.state == S6                               # 3 from_dict 重建状态
        assert rebuilt.current_map == "rubble_field"             # 4 复活点落位（入口）
        assert rebuilt.boss_state["hp"] == 280                   # 5 BOSS 残血保留（checkpoint 档）


# -------------------------------------------------------------------------------------
# M30：会话持久化（序列化 / 反序列化）
# -------------------------------------------------------------------------------------


class TestSaveLoadSession:
    def test_save_serializes_full_session(self) -> None:
        """M30：save 全字段序列化（当前区域/已清/子任务/换区上下文/BOSS/休息 + 防串档）。"""
        sess = _session(chasing=True, chase_target="lava_tunnel",
                        **{WEAKENED_KEY: True, WEAK_UNTIL_KEY: NOW})
        doc = save_dungeon_session(sess)
        assert doc["schema_version"] == SCHEMA_VERSION           # 1 文档版本
        assert doc["dungeon_id"] == "molten_dungeon_boss"        # 2 副本标识
        assert doc["dungeon_type"] == "boss"                     # 3 型别
        assert doc["state"] == "FINAL_DEATHMATCH"                # 4 当前状态
        assert doc["current_map"] == "lava_tunnel"               # 5 当前区域
        assert doc["cleared_maps"] == ["crag_den", "lava_tunnel", "rubble_field"]  # 6 已清区域
        assert doc["subquest_progress"] == {"sq_1": 2}           # 7 子任务进度
        assert doc["boss_state"] == {"hp": 280, "max_hp": 1000, "chasing": True}  # 8 BOSS 状态
        assert doc["rest_count"] == 2                            # 9 休息次数
        assert doc["external_anchor"] == "world_map_07"          # 10 外部锚点
        assert doc["content_pack_id"] == "cp1"                   # 11 防跨包串档 id
        assert doc["content_pack_version"] == "1.0"              # 12 防跨包串档 version
        assert doc["zone_chase_context"] == {"chasing": True, "chase_target": "lava_tunnel"}  # 13 换区上下文
        assert doc[WEAKENED_KEY] is True                         # 14 虚弱标记随档

    def test_roundtrip_load_restores_session(self) -> None:
        """M30 round-trip：save → load 还原会话（含换区上下文还原到顶层）。"""
        sess = _session(chasing=True, chase_target="lava_tunnel",
                        **{WEAKENED_KEY: True, WEAK_UNTIL_KEY: NOW})
        doc = save_dungeon_session(sess)
        r = load_dungeon_session(doc)
        assert r["ok"] is True                                   # 1 加载成功
        out = r["session"]
        assert out["dungeon_id"] == "molten_dungeon_boss"        # 2
        assert out["current_map"] == "lava_tunnel"               # 3 当前区域
        assert out["cleared_maps"] == ["crag_den", "lava_tunnel", "rubble_field"]  # 4 已清区域
        assert out["subquest_progress"] == {"sq_1": 2}           # 5 子任务
        assert out["boss_state"] == {"hp": 280, "max_hp": 1000, "chasing": True}  # 6 BOSS
        assert out["rest_count"] == 2                            # 7 休息次数
        assert out["chasing"] is True                            # 8 换区上下文还原
        assert out["chase_target"] == "lava_tunnel"              # 9
        assert out[WEAKENED_KEY] is True                         # 10 虚弱标记透传
        assert out[WEAK_UNTIL_KEY] == NOW                        # 11 虚弱截止透传
        assert out["content_pack_id"] == "cp1"                   # 12 防串档 id 还原

    def test_load_dataclass_session_roundtrip(self) -> None:
        """DungeonSession dataclass → save → load（from_dict 重建字段一致）。"""
        ds = _dataclass_session()
        doc = save_dungeon_session(ds)
        r = load_dungeon_session(doc)
        assert r["ok"] is True                                   # 1
        rebuilt = DungeonSession.from_dict(r["session"])
        assert rebuilt.dungeon_id == ds.dungeon_id               # 2
        assert rebuilt.dungeon_type == ds.dungeon_type           # 3
        assert rebuilt.state == ds.state                         # 4
        assert rebuilt.current_map == ds.current_map             # 5
        assert rebuilt.cleared_maps == ds.cleared_maps           # 6
        assert rebuilt.boss_state == ds.boss_state               # 7

    def test_load_fills_defaults(self) -> None:
        """M30 缺补默认：缺字段文档 → 缺省值（与 DungeonSession.from_dict 同口径）。"""
        r = load_dungeon_session({"dungeon_id": "d1"})
        assert r["ok"] is True                                   # 1
        out = r["session"]
        assert out["dungeon_type"] == "explore"                  # 2 缺省型别
        assert out["state"] == "ENTRY"                           # 3 缺省状态 S0
        assert out["current_map"] is None                        # 4 缺省区域
        assert out["cleared_maps"] == []                         # 5 缺省已清
        assert out["subquest_progress"] == {}                    # 6 缺省子任务
        assert out["boss_state"] == {}                           # 7 缺省 BOSS
        assert out["rest_count"] == 0                            # 8 缺省休息

    def test_load_content_pack_mismatch_rejected(self) -> None:
        """M30 防跨包串档：content_pack_id 不匹配 → 拒绝信号不产出会话。"""
        doc = save_dungeon_session(_session())
        r = load_dungeon_session(doc, content_pack_id="cp2")
        assert r["ok"] is False                                  # 1 拒绝
        assert r["reason"] == "content_pack_mismatch"            # 2 原因=不匹配
        assert r["session"] is None                              # 3 不产出会话（不串档）
        assert r["expected"] == "cp2"                            # 4 期望包
        assert r["found"] == "cp1"                               # 5 存档包

    def test_load_missing_pack_rejected_when_expected(self) -> None:
        """旧档缺 content_pack_id + 提供期望 → 保守拒绝；不提供期望 → 放行。"""
        doc = {"dungeon_id": "d1", "state": "PEACE_EXPLORE"}
        r = load_dungeon_session(doc, content_pack_id="cp1")
        assert r["ok"] is False                                  # 1 拒绝
        assert r["reason"] == "content_pack_mismatch"            # 2
        assert r["found"] is None                                # 3 存档包缺失
        r2 = load_dungeon_session(doc)                           # 4 不校验
        assert r2["ok"] is True                                  # 5 放行

    def test_load_invalid_store_rejected(self) -> None:
        """非法 store（非 Mapping / 缺 dungeon_id）→ invalid_store 拒绝。"""
        for bad in (None, [], {}, {"state": "PEACE_EXPLORE"}):
            r = load_dungeon_session(bad)
            assert r["ok"] is False                              # 1 拒绝
            assert r["reason"] == "invalid_store"                # 2 原因=非法 store
            assert r["session"] is None                          # 3

    def test_save_invalid_session_rejected(self) -> None:
        """无 dungeon_id 的会话不可序列化 → 拒绝 dict。"""
        r = save_dungeon_session({"state": "PEACE_EXPLORE"})
        assert r["ok"] is False                                  # 1
        assert "dungeon_id" in r["reason"]                       # 2


# -------------------------------------------------------------------------------------
# M30：会话清理（通关/重置）
# -------------------------------------------------------------------------------------


class TestClearSession:
    def test_clear_removes_from_container(self) -> None:
        """清理时机=通关/重置：从容器剔除目标会话；纯函数不改入参。"""
        d1 = save_dungeon_session(_session())
        d2 = save_dungeon_session(_session(dungeon_id="other_dungeon"))
        store = {"molten_dungeon_boss": d1, "other_dungeon": d2}
        r = clear_dungeon_session(store, "molten_dungeon_boss")
        assert r["ok"] is True                                   # 1
        assert r["cleared"] is True                              # 2 存在并清理
        assert set(r["store"].keys()) == {"other_dungeon"}       # 3 仅剩另一会话
        assert "molten_dungeon_boss" in store                    # 4 入参未改（纯函数）

    def test_clear_missing_key_reports_not_cleared(self) -> None:
        """容器缺目标键 → cleared=False，容器原样返回。"""
        store = {"other_dungeon": save_dungeon_session(_session(dungeon_id="other_dungeon"))}
        r = clear_dungeon_session(store, "ghost_dungeon")
        assert r["cleared"] is False                             # 1
        assert r["store"] == store                               # 2

    def test_clear_single_doc_form(self) -> None:
        """单文档形态清理 → cleared=True、store=None（存储行删除由 M4 接线）。"""
        doc = save_dungeon_session(_session())
        r = clear_dungeon_session(doc, "molten_dungeon_boss")
        assert r["cleared"] is True                              # 1
        assert r["store"] is None                                # 2

    def test_clear_none_store_and_invalid(self) -> None:
        """store=None（无既有会话）/ 非法形态处理。"""
        r = clear_dungeon_session(None, "d1")
        assert r["ok"] is True and r["cleared"] is False         # 1 无会话可清理
        r2 = clear_dungeon_session(42, "d1")
        assert r2["ok"] is False                                 # 2 非法形态
        assert r2["reason"] == "invalid_store"                   # 3


# -------------------------------------------------------------------------------------
# 虚弱判定与禁入非安全区
# -------------------------------------------------------------------------------------


class TestWeakenedChecks:
    def test_is_weakened_flag_and_time(self) -> None:
        """虚弱判定：标记 + 时间态（过期结束 / 无时间基准按标记）。"""
        assert is_weakened({WEAKENED_KEY: True}) is True         # 1 标记虚弱
        assert is_weakened({}) is False                          # 2 无标记
        sess = {WEAKENED_KEY: True, WEAK_UNTIL_KEY: NOW}
        assert is_weakened(sess, now_iso="2026-08-26T11:59:59+00:00") is True   # 3 未过期（剩 1 秒）
        assert is_weakened(sess, now_iso="2026-08-26T12:00:00+00:00") is False  # 4 到期
        assert is_weakened(sess) is True                         # 5 无时间基准按标记
        assert is_weakened(None, {"map_id": "x", WEAKENED_KEY: True}) is True   # 6 ctx 镜像

    def test_check_weakened_entry_safe_and_blocked(self) -> None:
        """禁入非安全区检查：非虚弱放行 / 虚弱安全区放行 / 非安全区与 BOSS 房拦截。"""
        ddef = _dungeon_def()
        # 非虚弱 → 全放行
        assert check_weakened_entry({}, "lava_tunnel", ddef)["ok"] is True      # 1
        # 虚弱 → 安全区放行
        weak = {WEAKENED_KEY: True}
        assert check_weakened_entry(weak, "rubble_field", ddef)["ok"] is True   # 2
        # 虚弱 → 非安全区拦截
        assert check_weakened_entry(weak, "crag_den", ddef)["ok"] is False      # 3
        # 虚弱 → BOSS 房拦截
        assert check_weakened_entry(weak, "lava_tunnel", ddef)["ok"] is False   # 4
        # 缺 dungeon_def → fail-safe 拦截
        f = check_weakened_entry(weak, "crag_den")
        assert f["ok"] is False and "无法判定安全区" in f["reason"]             # 5
