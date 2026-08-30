"""M3 批次3·路K：世界移动处理层（M05 隐藏通道 + M06 /进入 接线 + 地图切换钩子）单元测试。

依据：
  - 细化_2a1b §1.3（R11-R13 通道与移动衔接）+ §1.2（R7-R9 隐藏条件打开）+ TC-01~TC-06
  - 细化_2a1c §3（/进入 参数解析 R14-R18/R20 + §3.2 上下文路由）+ TC-01~TC-15/TC-24/TC-25
  - m3_shared_contract §2.4（can_move MoveResult）+ §5.3 IF11（map_weather_seen）
  - world_time_persist.mark_map_seen（M35 惰性增长语义）

测试目标：qbot_rpg.world.movement（resolve_move / move_to_map / enter_context_route）。
零 NoneBot、零 IO（ctx 由用例直接构造 dict 传入；maps/dungeons 注入内存 fixture）。

覆盖：双向可走往返 / 单向反方向拦截 / 隐藏条件满足与未满足（含未注入与抛错 fail-safe）/
死路方向 / 非法方向 / 地图切换钩子（位置原地改 + map_weather_seen 惰性增长 + desc/lore 返回 +
R22 双钩子）/ /进入 方向行走 / 入口名·副本名·序号·id 匹配 / 未命中与错误入口。
"""
from __future__ import annotations

from typing import Mapping

import pytest

from qbot_rpg.world.movement import (
    DIRECTION_ALIASES,
    enter_context_route,
    move_to_map,
    resolve_move,
)

# -------------------------------------------------------------------------------------
# 内存 fixture（网状图：双向 / 单向 / 隐藏 / 死路 + 双副本入口）
# -------------------------------------------------------------------------------------
_MAPS = [
    {
        "id": "a_plains", "name": "平原入口", "desc": "开阔平原",
        "exits": {
            "up":    {"to": "b_forest", "mode": "bidirectional"},
            "down":  {"to": "d_mine", "mode": "one_way"},                       # 单向（前向可走）
            "right": {"to": "c_cave", "mode": "hidden", "lore": "藤蔓掩映的窄道",
                      "condition": {"var": "subquest_done", "op": "eq", "param": "learn_mechanic"}},
            # left 未配置 = 死路（2a1b R2）
        },
        "dungeon_entrances": [
            {"dungeon": "molten_dungeon", "name": "熔岩洞窟·讨伐"},
            {"dungeon": "molten_explore"},                                        # 无 name → 回退副本名
        ],
    },
    {
        "id": "b_forest", "name": "幽暗森林", "desc": "树影幢幢",
        "exits": {"down": {"to": "a_plains", "mode": "bidirectional"}},          # 与 a_plains.up 双向
    },
    {
        "id": "c_cave", "name": "秘洞", "desc": "洞窟入口",
        "exits": {},
    },
    {
        "id": "d_mine", "name": "废矿", "desc": "废弃矿道",
        "exits": {},                                                              # 单向到达后全向死路
    },
]

_DUNGEONS = [
    {"id": "molten_dungeon", "name": "熔岩洞窟"},
    {"id": "molten_explore", "name": "熔岩洞窟·探索"},
]


def _ctx(map_id: str = "a_plains", seen: dict | None = None,
         subquest_done: str | None = None) -> dict:
    """最小玩家上下文（map_id 会话态 + player 位置 + time_state）。"""
    player: dict = {"map_id": map_id, "name": "阿伟"}
    if subquest_done is not None:
        player["subquest_done"] = subquest_done
    return {
        "map_id": map_id,
        "player": player,
        "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                       "map_weather_seen": dict(seen or {})},
    }


def _cond_learn(cond: Mapping[str, object], ctx: dict) -> bool:
    """子任务解锁条件（2a1b R9：玩家进度学习解锁）：param=learn_mechanic 且玩家已学。"""
    return cond.get("param") == "learn_mechanic" and \
        (ctx.get("player") or {}).get("subquest_done") == "learn_mechanic"


def _cond_false(cond: Mapping[str, object], ctx: dict) -> bool:
    return False


def _cond_raise(cond: Mapping[str, object], ctx: dict) -> bool:
    raise RuntimeError("条件引擎崩")


# -------------------------------------------------------------------------------------
# 方向字面量（2a1c R15：上/下/左/右 + 别名 北/南/东/西）
# -------------------------------------------------------------------------------------
def test_direction_aliases_cover_contract():
    assert set(DIRECTION_ALIASES) >= {"up", "down", "left", "right",
                                      "上", "下", "左", "右", "北", "南", "东", "西"}


def test_direction_alias_semantics():
    assert DIRECTION_ALIASES["北"] == "up"
    assert DIRECTION_ALIASES["南"] == "down"
    assert DIRECTION_ALIASES["东"] == "right"
    assert DIRECTION_ALIASES["西"] == "left"


# -------------------------------------------------------------------------------------
# resolve_move：双向可走 / 单向 / 隐藏 / 死路
# -------------------------------------------------------------------------------------
def test_bidirectional_walk_round_trip():
    ctx = _ctx("a_plains")
    r = resolve_move(ctx, "上", maps=_MAPS)
    assert r["ok"] is True
    assert r["to"] == "b_forest"
    assert r["name"] == "幽暗森林"
    assert r["desc"] == "树影幢幢"
    assert ctx["player"]["map_id"] == "b_forest"      # 位置原地改
    assert ctx["map_id"] == "b_forest"                # 会话上下文同步
    assert ctx["time_state"]["map_weather_seen"] == {"b_forest": True}  # map_weather_seen 记录
    # 往返（双向通道 2a1b TC-01）
    r2 = resolve_move(ctx, "下", maps=_MAPS)
    assert r2["ok"] is True and r2["to"] == "a_plains"
    assert ctx["player"]["map_id"] == "a_plains"
    assert set(ctx["time_state"]["map_weather_seen"]) == {"b_forest", "a_plains"}


def test_english_and_chinese_direction_equivalent():
    assert resolve_move(_ctx("a_plains"), "up", maps=_MAPS)["to"] == "b_forest"
    assert resolve_move(_ctx("a_plains"), "上", maps=_MAPS)["to"] == "b_forest"


def test_one_way_forward_walkable():
    ctx = _ctx("a_plains")
    r = resolve_move(ctx, "下", maps=_MAPS)          # a_plains.down → d_mine（one_way 前向）
    assert r["ok"] is True and r["to"] == "d_mine"
    assert ctx["player"]["map_id"] == "d_mine"


def test_one_way_reverse_blocked_at_destination():
    # 单向到达 d_mine 后，任何方向均无通道（2a1b TC-02 / 2a1c TC-02：反方向拒绝，位置不变）
    ctx = _ctx("d_mine")
    for d in ("上", "下", "左", "右", "up", "down", "left", "right"):
        r = resolve_move(ctx, d, maps=_MAPS)
        assert r["ok"] is False, d
        assert r["reason"] == "此方向没有通道", d
    assert ctx["player"]["map_id"] == "d_mine"        # 位置不变


def test_dead_end_direction_blocked():
    ctx = _ctx("a_plains")
    r = resolve_move(ctx, "左", maps=_MAPS)           # left 未配置 = 死路（2a1b R2）
    assert r["ok"] is False
    assert r["reason"] == "此方向没有通道"
    assert ctx["player"]["map_id"] == "a_plains"      # 位置不变


def test_hidden_blocked_without_conditions():
    # 未注入 conditions → hidden 不可走（任务口径：未注入 = 不可走）
    ctx = _ctx("a_plains")
    r = resolve_move(ctx, "右", maps=_MAPS)
    assert r["ok"] is False
    assert r["reason"] == "此处无通道"
    assert ctx["player"]["map_id"] == "a_plains"


def test_hidden_blocked_when_condition_not_met():
    ctx = _ctx("a_plains", subquest_done=None)
    r = resolve_move(ctx, "右", maps=_MAPS, conditions=_cond_learn)   # 未完成机制学习
    assert r["ok"] is False and r["reason"] == "此处无通道"
    assert ctx["player"]["map_id"] == "a_plains"


def test_hidden_walkable_when_condition_met():
    ctx = _ctx("a_plains", subquest_done="learn_mechanic")
    r = resolve_move(ctx, "右", maps=_MAPS, conditions=_cond_learn)   # 条件满足（2a1b TC-06）
    assert r["ok"] is True
    assert r["to"] == "c_cave"
    assert r["desc"] == "洞窟入口"
    assert r["lore"] == "藤蔓掩映的窄道"                              # 通道 lore 带回
    assert ctx["player"]["map_id"] == "c_cave"
    assert "c_cave" in ctx["time_state"]["map_weather_seen"]


def test_hidden_condition_raising_is_fail_safe():
    # 求值抛错 → 默认不满足（2a1d LC-D fail-safe）
    ctx = _ctx("a_plains")
    r = resolve_move(ctx, "右", maps=_MAPS, conditions=_cond_raise)
    assert r["ok"] is False and r["reason"] == "此处无通道"


def test_invalid_direction_rejected():
    ctx = _ctx("a_plains")
    for bad in ("斜", "右上", ""):
        r = resolve_move(ctx, bad, maps=_MAPS)
        assert r["ok"] is False, bad
        assert "不是方向" in r["reason"], bad
    assert ctx["player"]["map_id"] == "a_plains"


def test_unknown_current_map_rejected():
    ctx = _ctx("nowhere")
    r = resolve_move(ctx, "上", maps=_MAPS)
    assert r["ok"] is False
    assert "找不到当前地图" in r["reason"]


def test_current_map_falls_back_to_player_map_id():
    ctx = _ctx("a_plains")
    del ctx["map_id"]                       # 会话态缺失 → 兜底 player.map_id
    r = resolve_move(ctx, "上", maps=_MAPS)
    assert r["ok"] is True and r["to"] == "b_forest"


# -------------------------------------------------------------------------------------
# move_to_map：地图切换钩子
# -------------------------------------------------------------------------------------
def test_move_to_map_updates_position_in_place():
    ctx = _ctx("a_plains")
    r = move_to_map(ctx, "b_forest", maps=_MAPS)
    assert r["ok"] is True
    assert ctx["player"]["map_id"] == "b_forest"   # 玩家位置原地改
    assert ctx["map_id"] == "b_forest"             # 会话上下文同步


def test_move_to_map_returns_name_desc_lore():
    r = move_to_map(_ctx("a_plains"), "b_forest", maps=_MAPS)
    assert r["name"] == "幽暗森林" and r["desc"] == "树影幢幢"
    # 直移经 right 通道（带 lore）→ lore 从旧图 exits 找回
    r2 = move_to_map(_ctx("a_plains"), "c_cave", maps=_MAPS)
    assert r2["name"] == "秘洞" and r2["desc"] == "洞窟入口"
    assert r2["lore"] == "藤蔓掩映的窄道"
    # 无 lore 的通道 → None
    assert r.get("lore") is None


def test_move_to_map_map_weather_seen_grows_idempotent():
    ctx = _ctx("a_plains", seen={})
    move_to_map(ctx, "b_forest", maps=_MAPS)
    assert ctx["time_state"]["map_weather_seen"] == {"b_forest": True}
    move_to_map(ctx, "c_cave", maps=_MAPS)
    assert set(ctx["time_state"]["map_weather_seen"]) == {"b_forest", "c_cave"}  # 惰性增长
    move_to_map(ctx, "b_forest", maps=_MAPS)
    assert set(ctx["time_state"]["map_weather_seen"]) == {"b_forest", "c_cave"}  # 幂等不重复


def test_move_to_map_creates_time_state_when_missing():
    ctx = {"map_id": "a_plains", "player": {"map_id": "a_plains", "name": "阿伟"}}
    assert "time_state" not in ctx
    move_to_map(ctx, "b_forest", maps=_MAPS)
    assert ctx["time_state"]["map_weather_seen"] == {"b_forest": True}
    assert ctx["time_state"]["season_idx"] == 0   # 其余字段按契约默认


def test_move_to_map_r22_hooks_fired():
    calls = []
    ctx = _ctx("a_plains")
    ctx["move_hooks"] = {
        "on_leave": lambda old, c: calls.append(("leave", old)),
        "on_enter": lambda new, c: calls.append(("enter", new)),
    }
    move_to_map(ctx, "b_forest", maps=_MAPS)
    assert calls == [("leave", "a_plains"), ("enter", "b_forest")]   # R22 离开+进入双钩子


def test_move_to_map_unknown_target_graceful():
    ctx = _ctx("a_plains")
    r = move_to_map(ctx, "zzz", maps=_MAPS)
    assert r["ok"] is True and r["map_id"] == "zzz"   # 位置仍更新（钩子语义），信息缺省 None
    assert r["name"] is None and r["desc"] is None
    assert "zzz" in ctx["time_state"]["map_weather_seen"]


def test_move_to_map_persists_location_to_ps_dict():
    """P1-5（QA 黑盒·位置不持久）：move_to_map 写 persistent_state["location"]（dict 形态玩家）。

    Player 无 map_id 字段，位置真落点位 = persistent_state["location"]——移动后重启仍保持。
    """
    ps: dict = {"location": "a_plains"}
    ctx = {
        "map_id": "a_plains",
        "location": "a_plains",
        "player": {"map_id": "a_plains", "name": "阿伟", "persistent_state": ps},
        "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                       "map_weather_seen": {}},
    }
    r = move_to_map(ctx, "b_forest", maps=_MAPS)
    assert r["ok"] is True
    assert ps["location"] == "b_forest"               # 真落档位更新（重启后仍保持）
    assert ctx["location"] == "b_forest"              # 会话键同步
    assert ctx["player"]["map_id"] == "b_forest"      # 兼容旧键（dict 形态原地改）


def test_move_to_map_persists_location_to_ps_top_key():
    """P1-5：persistent_state 挂在 ctx 顶层键（生产装配形态：ctx["persistent_state"]）→ 落档。"""
    from qbot_rpg.data.player import Player

    ps: dict = {"location": "a_plains"}
    player = Player(qid="10001", name="阿伟", persistent_state=ps)
    ctx = {"player": player, "persistent_state": ps, "location": "a_plains",
           "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                          "map_weather_seen": {}}}
    move_to_map(ctx, "b_forest", maps=_MAPS)
    assert ps["location"] == "b_forest"               # Player 可变子结构就地改 → 落档
    assert player.persistent_state["location"] == "b_forest"


def test_move_to_map_persists_dataclass_player_attribute():
    """P1-5：Player dataclass（frozen，无 map_id）形态——ctx 仅含 player，位置落属性 ps。"""
    from qbot_rpg.data.player import Player

    ps: dict = {"location": "a_plains"}
    player = Player(qid="10001", name="阿伟", persistent_state=ps)
    ctx = {"player": player, "location": "a_plains",
           "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                          "map_weather_seen": {}}}
    r = move_to_map(ctx, "b_forest", maps=_MAPS)
    assert r["ok"] is True
    assert player.persistent_state["location"] == "b_forest"   # dataclass 可变子结构就地改
    assert ctx["location"] == "b_forest"


def test_resolve_move_persists_location_dataclass_player():
    """P1-5 端到端（world 层）：/进入 上 移动后位置落 Player.persistent_state["location"]，
    会话键同步——后续 /位置（ctx["location"]）读新图，重启（ps）仍新图。"""
    from qbot_rpg.data.player import Player

    ps: dict = {"location": "a_plains"}
    player = Player(qid="10001", name="阿伟", persistent_state=ps)
    ctx = {"player": player, "location": "a_plains", "maps": _MAPS,
           "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                          "map_weather_seen": {}}}
    r = resolve_move(ctx, "上", maps=_MAPS)
    assert r["ok"] is True and r["to"] == "b_forest"
    assert player.persistent_state["location"] == "b_forest"   # 落档（重启仍保持）
    assert ctx["location"] == "b_forest"                        # 会话同步（/位置 立即可见）


def test_enter_context_route_persists_location_dataclass_player():
    """P1-5 端到端（world 层）：enter_context_route 方向行走同样持久化位置。"""
    from qbot_rpg.data.player import Player

    ps: dict = {"location": "a_plains"}
    player = Player(qid="10001", name="阿伟", persistent_state=ps)
    ctx = {"player": player, "location": "a_plains", "maps": _MAPS,
           "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                          "map_weather_seen": {}}}
    r = enter_context_route(ctx, "上", maps=_MAPS)
    assert r["ok"] is True and r["to"] == "b_forest"
    assert player.persistent_state["location"] == "b_forest"


# -------------------------------------------------------------------------------------
# enter_context_route：/进入 路由（方向 → 通道行走；入口名/序号 → 进副本信号）
# -------------------------------------------------------------------------------------
def test_route_direction_walks_channel():
    ctx = _ctx("a_plains")
    r = enter_context_route(ctx, "上", maps=_MAPS)
    assert r["type"] == "move" and r["ok"] is True and r["to"] == "b_forest"
    assert ctx["player"]["map_id"] == "b_forest"
    # 英文键等价（R12 双认：进入上 / 进入up）
    assert enter_context_route(_ctx("a_plains"), "up", maps=_MAPS)["to"] == "b_forest"


def test_route_failed_direction_does_not_move():
    ctx = _ctx("a_plains")
    r = enter_context_route(ctx, "左", maps=_MAPS)    # 死路
    assert r["type"] == "move" and r["ok"] is False
    assert r["reason"] == "此方向没有通道"
    assert ctx["player"]["map_id"] == "a_plains"      # 位置不变


def test_route_entrance_by_explicit_name():
    r = enter_context_route(_ctx("a_plains"), "熔岩洞窟·讨伐", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is True and r["type"] == "dungeon"
    assert r["dungeon_id"] == "molten_dungeon"
    assert r["name"] == "熔岩洞窟·讨伐"                # 入口显式名
    assert "批次 5" in r["note"]                       # 【工程补白】副本流程待接线


def test_route_entrance_by_default_dungeon_name():
    # 入口 2 无 name → 回退副本名（R17 逐级；2a1c §1.2 缺省用 dungeon.name）
    r = enter_context_route(_ctx("a_plains"), "熔岩洞窟·探索", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is True and r["type"] == "dungeon"
    assert r["dungeon_id"] == "molten_explore"
    assert r["name"] == "熔岩洞窟·探索"


def test_route_entrance_by_dungeon_id():
    r = enter_context_route(_ctx("a_plains"), "molten_dungeon", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is True and r["type"] == "dungeon" and r["dungeon_id"] == "molten_dungeon"


def test_route_entrance_by_index_one_based():
    # 序号不带 *（R16；1 起始，2a1c TC-09）
    r1 = enter_context_route(_ctx("a_plains"), "1", maps=_MAPS, dungeons=_DUNGEONS)
    assert r1["dungeon_id"] == "molten_dungeon"
    r2 = enter_context_route(_ctx("a_plains"), "2", maps=_MAPS, dungeons=_DUNGEONS)
    assert r2["dungeon_id"] == "molten_explore"


def test_route_index_out_of_range():
    for arg in ("0", "99"):
        r = enter_context_route(_ctx("a_plains"), arg, maps=_MAPS, dungeons=_DUNGEONS)
        assert r["ok"] is False, arg
        assert "序号" in r["reason"] and "无效" in r["reason"], arg


def test_route_node_without_entrances():
    # 非入口节点（2a1c TC-14：此处没有副本入口）
    r = enter_context_route(_ctx("b_forest"), "熔岩洞窟", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is False and r["reason"] == "此处没有副本入口"


def test_route_unmatched_name():
    r = enter_context_route(_ctx("a_plains"), "不存在的入口", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is False and r["reason"] == "没有这个入口/方向"


def test_route_star_rejected():
    # 保留字符 *（2a1c TC-25：/进入 无数量位）
    r = enter_context_route(_ctx("a_plains"), "熔岩洞窟*2", maps=_MAPS, dungeons=_DUNGEONS)
    assert r["ok"] is False
    assert "不支持数量" in r["reason"]


def test_route_empty_arg():
    # 便捷指令无参（2a1c TC-23：P1 预留，不自动行走）
    for arg in ("", None):
        r = enter_context_route(_ctx("a_plains"), arg, maps=_MAPS)
        assert r["ok"] is False, arg
        assert "需要参数" in r["reason"], arg
    # 无参不移动
    assert _ctx("a_plains")["player"]["map_id"] == "a_plains"


# -------------------------------------------------------------------------------------
# 防御 / 形态
# -------------------------------------------------------------------------------------
def test_maps_via_modules_container_and_player_ctx():
    # modules 容器形态（content 装载 {"maps": [...]}）→ 归一
    modules = {"maps": _MAPS}
    assert resolve_move(_ctx("a_plains"), "上", maps=modules)["to"] == "b_forest"
    # 未显式传 maps → 从 player_ctx["maps"] 取（指令层常预载 ctx）
    ctx = _ctx("a_plains")
    ctx["maps"] = _MAPS
    assert resolve_move(ctx, "上")["to"] == "b_forest"


def test_move_does_not_mutate_input_maps():
    ctx = _ctx("a_plains")
    resolve_move(ctx, "上", maps=_MAPS)
    assert ctx["time_state"]["map_weather_seen"] == {"b_forest": True}
    # 原 maps fixture 不被改动（零冲突/纯数据）
    assert _MAPS[0]["exits"]["up"]["to"] == "b_forest"