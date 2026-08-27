"""M3 批次6·路Q：M12 换区触发装配 + M13 追击行走与错失窗口 单元测试。

依据：细化_2a2_换区追击流程.md §1（触发 R1-R8）+ §4（追击时序 R15-R22）+ §5（离开重置 R24）
+ m3_shared_contract.md §3（zone_change 配置 / 换区规则要点）/ §八 2（确定性：随机注入 rng）。
测试目标：qbot_rpg.world.chase（chase_trigger / pick_chase_target / begin_chase / pursue）。
零 NoneBot、零 IO：maps/玩家上下文由用例直接构造 dict 注入；rng 用 ScriptedRng 注入确定性。

断言分组：
  TestChaseTrigger        触发判定（阈值命中/边界/未命中/disabled/空 targets/cfg 缺失/
                          hp=0 击杀优先/timing=phase_changed/BossFlow 注入委派/本地口径一致）
  TestPickChaseTarget     候选区确定性选一（同 rng 同值/不同 rng 不同/未注入固定种子同值/
                          空候选 None/索引映射）
  TestBeginChase          追击态开启（chasing:true + 提示「BOSS 逃向了【XX】」+ 显示名
                          = maps.name + session 落盘 + 未知图回退 id）
  TestPursue              追击行走与错失窗口（到达捕获/走错计数/死路不计错/走回起始区错失/
                          连续错失上限默认 3/自定义上限/超限 boss_reset/续战准备接线/可达信息位）

铁律：零 NoneBot import；纯逻辑断言；确定性（无随机依赖）。
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from qbot_rpg.content.models import EnemyDef
from qbot_rpg.core.dungeon_boss import ZC_TRIGGER_PHASE_CHANGED, BossFlow
from qbot_rpg.world.chase import (
    MISS_LIMIT_DEFAULT,
    SESSION_CHASING_KEY,
    SESSION_CHASE_TARGET_KEY,
    begin_chase,
    chase_trigger,
    pick_chase_target,
    pursue,
)

LEGAL_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs" / "legal"

# ember_drake 的 zone_change 样例（legal/enemies.json；m3 §3.1 四字段）
EMBER_ZONE_CHANGE = {
    "enabled": True,
    "hp_threshold": 0.3,
    "targets": ["molten_corridor", "molten_core"],
    "timing": "after_action",
}


# -------------------------------------------------------------------------------------
# 辅助：确定性 rng / 注入对象 / legal 数据 / 追击地图夹具
# -------------------------------------------------------------------------------------


class ScriptedRng:
    """注入确定性 rng：按脚本序列循环返回 random()；choice 走 random() 映射（铁律 6）。"""

    def __init__(self, values: list[float]) -> None:
        self._values = list(values)
        self.calls = 0

    def random(self) -> float:
        v = self._values[self.calls % len(self._values)] if self._values else 0.0
        self.calls += 1
        return v

    def choice(self, seq: list[Any]) -> Any:
        return seq[int(self.random() * len(seq)) % len(seq)]


class StubBossFlow:
    """触发判定/续战准备注入替身（记录调用，返回脚本值）。"""

    def __init__(self, result: bool = True) -> None:
        self._result = result
        self.calls = 0

    def should_zone_change(self, enemy_state: Any, cfg: Any) -> bool:
        self.calls += 1
        return self._result

    def on_chase_continue(self, player_ctx: Any = None) -> dict:
        return {"resume": True, "hp_keep": True, "pv_half": True,
                "pv_half_value": 150, "opening_skill": True}


def _load(name: str) -> list:
    data = json.loads((LEGAL_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert isinstance(data, list)
    return data


def _ember_drake(**overrides: Any) -> dict:
    for e in _load("enemies"):
        if e.get("id") == "ember_drake":
            entry = copy.deepcopy(e)
            entry.update(overrides)
            return entry
    raise AssertionError("legal/enemies.json 缺少 ember_drake")


# 追击地图夹具（网状：起始厅 → 回廊 → 龙巢；死胡同/虚空房单向入/环廊回路）
_CHASE_MAPS = [
    {
        "id": "s_room", "name": "起始厅",
        "exits": {
            "up":    {"to": "corridor", "mode": "bidirectional"},
            "down":  {"to": "dead_end", "mode": "bidirectional"},
            "right": {"to": "void_room", "mode": "one_way"},
        },
    },
    {
        "id": "corridor", "name": "回廊",
        "exits": {
            "down": {"to": "s_room", "mode": "bidirectional"},
            "up":   {"to": "boss_den", "mode": "bidirectional"},
            "left": {"to": "loop_a", "mode": "bidirectional"},
        },
    },
    {
        "id": "boss_den", "name": "龙巢",
        "exits": {"down": {"to": "corridor", "mode": "bidirectional"}},
    },
    {
        "id": "dead_end", "name": "死胡同",
        "exits": {"up": {"to": "s_room", "mode": "bidirectional"}},
    },
    {
        "id": "void_room", "name": "虚空房",
        "exits": {},
    },
    {
        "id": "loop_a", "name": "环廊",
        "exits": {"right": {"to": "corridor", "mode": "bidirectional"}},
    },
]


def _pctx(map_id: str) -> dict:
    """最小玩家上下文（会话 map_id + player 位置 + time_state，对齐 test_movement）。"""
    return {
        "map_id": map_id,
        "player": {"map_id": map_id, "name": "阿伟"},
        "time_state": {"season_idx": 0, "period_idx": 0, "weather_tick": 0,
                       "map_weather_seen": {}},
    }


def _chase(target: str = "boss_den", start: str = "s_room",
           miss_limit: int | None = None, boss_flow: Any = None) -> dict:
    cc: dict = {SESSION_CHASING_KEY: True, "target_map": target,
                "start_map": start, "miss_count": 0}
    if miss_limit is not None:
        cc["miss_limit"] = miss_limit
    if boss_flow is not None:
        cc["boss_flow"] = boss_flow
    return cc


# -------------------------------------------------------------------------------------
# M12 换区触发装配：阈值命中/未命中/disabled/空候选/击杀优先/时机/注入委派
# -------------------------------------------------------------------------------------


class TestChaseTrigger:
    """chase_trigger：触发判定 + 候选区装配（m3 §3.2 / 2a2 §1.1 + §1.4）。"""

    def test_threshold_hit(self) -> None:
        out = chase_trigger({"hp_pct": 25.0}, EMBER_ZONE_CHANGE)
        assert out["triggered"] is True                       # 1 阈值内触发
        assert out["targets"] == EMBER_ZONE_CHANGE["targets"]  # 2 候选区原样返回
        assert out["target"] in EMBER_ZONE_CHANGE["targets"] # type: ignore[operator]  # 3 目标 ∈ 候选
        assert isinstance(out["target"], str)                 # 4 目标为图 id 字符串

    def test_threshold_boundary_and_miss(self) -> None:
        assert chase_trigger({"hp_pct": 30.0}, EMBER_ZONE_CHANGE)["triggered"] is True   # 1 30% 整触发
        out = chase_trigger({"hp_pct": 30.1}, EMBER_ZONE_CHANGE)
        assert out["triggered"] is False                      # 2 超阈值不触发
        assert out["target"] is None                          # 3 未触发无目标

    def test_hp_max_hp_form(self) -> None:
        st = {"hp": 375, "max_hp": 1500}  # 25%
        assert chase_trigger(st, EMBER_ZONE_CHANGE)["triggered"] is True                # 1 绝对 HP 换算

    def test_hp_zero_kill_priority(self) -> None:
        out = chase_trigger({"hp": 0, "max_hp": 1500}, EMBER_ZONE_CHANGE)
        assert out["triggered"] is False                      # 1 R3 击杀优先不进换区

    def test_disabled_never_triggers(self) -> None:
        cfg = dict(EMBER_ZONE_CHANGE, enabled=False)
        assert chase_trigger({"hp_pct": 10}, cfg)["triggered"] is False                 # 1 enabled=False

    def test_no_targets_or_missing_cfg(self) -> None:
        out = chase_trigger({"hp_pct": 10}, dict(EMBER_ZONE_CHANGE, targets=[]))
        assert out["triggered"] is False                      # 1 R4 候选区空 = 永不换区
        assert out["targets"] == []                           # 2 空候选列表返回
        out2 = chase_trigger({"hp_pct": 10}, None)
        assert out2["triggered"] is False                     # 3 cfg 缺失不触发
        assert out2["targets"] == []                          # 4 无配置无候选
        assert out2["target"] is None                         # 5 无配置无目标

    def test_timing_phase_changed(self) -> None:
        cfg = dict(EMBER_ZONE_CHANGE, timing=ZC_TRIGGER_PHASE_CHANGED)
        assert chase_trigger({"hp_pct": 25, "phase_changed": False}, cfg)["triggered"] is False  # 1 无阶段切换不触发
        assert chase_trigger({"hp_pct": 25, "phase_changed": True}, cfg)["triggered"] is True   # 2 阶段切换触发

    def test_boss_flow_injected_delegation(self) -> None:
        bf = StubBossFlow(True)
        out = chase_trigger({"hp_pct": 25.0}, EMBER_ZONE_CHANGE, boss_flow=bf)
        assert out["triggered"] is True                       # 1 注入判定结果生效
        assert bf.calls == 1                                  # 2 判定委派注入实现
        assert out["target"] in EMBER_ZONE_CHANGE["targets"] # type: ignore[operator]  # 3 触发后仍装配候选区
        bf2 = StubBossFlow(False)
        assert chase_trigger({"hp_pct": 25.0}, EMBER_ZONE_CHANGE, boss_flow=bf2)["triggered"] is False  # 4 注入拦截

    def test_local_contract_matches_boss_flow(self) -> None:
        # 本地契约实现（未注入）与路O BossFlow.should_zone_change 判定链同口径（补白 1）
        flow = BossFlow(EnemyDef.from_entry(_ember_drake()), {"id": "d"}, {}, maps={})
        samples = [
            ({"hp_pct": 25.0}, EMBER_ZONE_CHANGE),
            ({"hp_pct": 30.0}, EMBER_ZONE_CHANGE),
            ({"hp_pct": 45.0}, EMBER_ZONE_CHANGE),
            ({"hp_pct": 25, "phase_changed": False},
             dict(EMBER_ZONE_CHANGE, timing=ZC_TRIGGER_PHASE_CHANGED)),
        ]
        for st, cfg in samples:
            local = chase_trigger(st, cfg)["triggered"]
            injected = chase_trigger(st, cfg, boss_flow=flow)["triggered"]
            assert local == injected                           # 1/2/3/4 双实现口径一致


# -------------------------------------------------------------------------------------
# M12 候选区确定性选一（R8：同 rng 同值 / 不同 rng 不同 / 未注入固定种子同值）
# -------------------------------------------------------------------------------------


class TestPickChaseTarget:
    """pick_chase_target：确定性（m3 §八 2：随机一律注入 rng，未注入固定种子）。"""

    def test_same_rng_same_value(self) -> None:
        rng = ScriptedRng([0.1])
        a = pick_chase_target(EMBER_ZONE_CHANGE, rng=rng)
        b = pick_chase_target(EMBER_ZONE_CHANGE, rng=rng)
        assert a == b                                          # 1 同 rng 序列同值
        assert a in EMBER_ZONE_CHANGE["targets"] # type: ignore[operator]  # 2 目标 ∈ 候选

    def test_different_rng_different(self) -> None:
        a = pick_chase_target(EMBER_ZONE_CHANGE, rng=ScriptedRng([0.1]))
        b = pick_chase_target(EMBER_ZONE_CHANGE, rng=ScriptedRng([0.9]))
        assert a != b                                          # 1 不同 rng 不同值
        assert {a, b} <= set(EMBER_ZONE_CHANGE["targets"]) # type: ignore[call-overload]  # 2 两目标均 ∈ 候选

    def test_random_index_mapping(self) -> None:
        # rng.random() 索引映射：int(r×n) 覆盖各下标
        assert pick_chase_target(EMBER_ZONE_CHANGE, rng=ScriptedRng([0.0])) == "molten_corridor"  # 1 下标 0
        assert pick_chase_target(EMBER_ZONE_CHANGE, rng=ScriptedRng([0.99])) == "molten_core"     # 2 下标 1

    def test_fixed_seed_deterministic_without_rng(self) -> None:
        a = pick_chase_target(EMBER_ZONE_CHANGE)
        b = pick_chase_target(EMBER_ZONE_CHANGE)
        assert a == b                                          # 1 未注入 rng 固定种子同候选集同值
        assert a in EMBER_ZONE_CHANGE["targets"] # type: ignore[operator]  # 2 目标 ∈ 候选
        c = pick_chase_target(dict(EMBER_ZONE_CHANGE, targets=["zone_x"]))
        assert c == "zone_x"                                   # 3 单候选恒选中

    def test_empty_targets_none(self) -> None:
        assert pick_chase_target({"targets": []}) is None      # 1 空候选 → None
        assert pick_chase_target(None) is None                 # 2 cfg 缺失 → None


# -------------------------------------------------------------------------------------
# M13 追击态开启：chasing:true + 提示「BOSS 逃向了【XX】」（显示名 = maps.name）
# -------------------------------------------------------------------------------------


class TestBeginChase:
    """begin_chase：追击态开启（契约 §3.2 逃跑行为 / §4.2 chasing:true / 2a2 R7）。"""

    def test_hint_with_maps_name(self) -> None:
        session: dict = {}
        out = begin_chase(session, "boss_den", {"boss_den": "龙巢"})
        assert out["chasing"] is True                          # 1 追击态开启
        assert out["target_map"] == "boss_den"                 # 2 目标图 id
        assert out["hint"] == "BOSS 逃向了【龙巢】"             # 3 提示含 maps.name
        assert out["target_name"] == "龙巢"                    # 4 显示名 = maps.name

    def test_session_state_persisted(self) -> None:
        session: dict = {}
        begin_chase(session, "boss_den", {"boss_den": "龙巢"})
        assert session[SESSION_CHASING_KEY] is True            # 1 session chasing 落盘
        assert session[SESSION_CHASE_TARGET_KEY] == "boss_den"  # 2 session 目标区落盘

    def test_unknown_map_fallback_to_id(self) -> None:
        out = begin_chase({}, "boss_den", None)
        assert out["hint"] == "BOSS 逃向了【boss_den】"         # 1 无地图名回退 id

    def test_maps_list_entries_form(self) -> None:
        out = begin_chase({}, "boss_den", _CHASE_MAPS)
        assert out["target_name"] == "龙巢"                    # 1 地图条目列表形态取 name


# -------------------------------------------------------------------------------------
# M13 追击行走与错失窗口：捕获 / 走错 / 死路不计错 / 回起始区 / 上限 / 续战准备
# -------------------------------------------------------------------------------------


class TestPursue:
    """pursue：/进入 <方向> 走通道追击（2a2 §4.2 R15 / §4.4 R18 / §5.1 R24）。"""

    def test_catch_on_reaching_target(self) -> None:
        ctx = _pctx("corridor")
        cc = _chase()
        out = pursue(ctx, "up", cc, maps=_CHASE_MAPS)
        assert out["caught"] is True                           # 1 到达目标图捕获
        assert out["missed"] is False                          # 2 非错失
        assert ctx["player"]["map_id"] == "boss_den"           # 3 玩家位置原地更新至目标图
        assert cc[SESSION_CHASING_KEY] is False                # 4 追击态关闭

    def test_legal_progress_not_counted(self) -> None:
        ctx = _pctx("s_room")
        cc = _chase()
        out = pursue(ctx, "down", cc, maps=_CHASE_MAPS)       # 合法中间推进：s_room → dead_end
        assert out["caught"] is False                          # 1 未捕获
        assert out["missed"] is False                          # 2 未达错失窗口
        assert out["miss_count"] == 0                          # 3 合法推进（目标仍可达）不计错
        assert cc["miss_count"] == 0                           # 4 计数未递增
        assert out["reachable"] is True                        # 5 目标仍可达（BFS 信息位）

    def test_blocked_move_not_counted(self) -> None:
        ctx = _pctx("s_room")
        cc = _chase()
        out = pursue(ctx, "left", cc, maps=_CHASE_MAPS)        # left 无通道 = 死路
        assert out["caught"] is False                          # 1 未捕获
        assert out["moved"] is False                           # 2 移动失败
        assert out["missed"] is False                          # 3 不计错
        assert cc["miss_count"] == 0                           # 4 死路不消耗行动资源（补白 5）

    def test_back_to_start_misses(self) -> None:
        ctx = _pctx("s_room")
        cc = _chase()
        out1 = pursue(ctx, "up", cc, maps=_CHASE_MAPS)         # 合法推进：s_room → corridor
        assert out1["missed"] is False and cc["miss_count"] == 0  # 1 未错失、合法推进不计错
        out2 = pursue(ctx, "down", cc, maps=_CHASE_MAPS)       # 走回起始区 s_room
        assert out2["missed"] is True                          # 2 走回起始区 = 错失
        assert out2["boss_reset"] is True                      # 3 BOSS 回满/离开副本信号
        assert out2["reason"] == "back_to_start"               # 4 错失原因 = 回起始区
        assert cc["miss_count"] == 1                           # 5 计数递增至 1

    def test_miss_limit_default_three(self) -> None:
        assert MISS_LIMIT_DEFAULT == 3                         # 1 默认错失上限 3
        ctx = _pctx("s_room")
        cc = _chase()
        out1 = pursue(ctx, "up", cc, maps=_CHASE_MAPS)         # 合法推进：s_room → corridor
        assert out1["missed"] is False and out1["miss_count"] == 0  # 2 合法推进不计错
        out2 = pursue(ctx, "left", cc, maps=_CHASE_MAPS)       # 合法推进：corridor → loop_a
        assert out2["missed"] is False and out2["miss_count"] == 0  # 3 合法推进不计错
        out3 = pursue(ctx, "right", cc, maps=_CHASE_MAPS)      # 回已访问图 corridor → 计错 1
        assert out3["missed"] is False and out3["miss_count"] == 1  # 4 回访计错 1 未达上限
        out4 = pursue(ctx, "left", cc, maps=_CHASE_MAPS)       # 回已访问图 loop_a → 计错 2
        assert out4["missed"] is False and out4["miss_count"] == 2  # 5 回访计错 2 未达上限
        out5 = pursue(ctx, "right", cc, maps=_CHASE_MAPS)      # 再回 corridor → 计错 3 = 上限
        assert out5["missed"] is True                          # 6 三错达上限 = 错失
        assert out5["reason"] == "miss_limit"                  # 7 错失原因 = 超限
        assert out5["boss_reset"] is True                      # 8 BOSS 回满/离开副本信号
        assert cc[SESSION_CHASING_KEY] is False                # 9 追击态关闭

    def test_custom_miss_limit(self) -> None:
        ctx = _pctx("s_room")
        cc = _chase(miss_limit=1)
        out = pursue(ctx, "right", cc, maps=_CHASE_MAPS)       # 单向入虚空房 → 目标不可达 = 偏离
        assert out["missed"] is True                           # 1 自定义上限 1：首错即错失
        assert out["miss_count"] == 1                          # 2 计数 = 上限
        assert out["reason"] == "miss_limit"                   # 3 错失原因 = 超限
        assert out["boss_reset"] is True                       # 4 超限 BOSS 回满信号

    def test_unreachable_after_wrong_move_info_flag(self) -> None:
        ctx = _pctx("s_room")
        cc = _chase()
        out = pursue(ctx, "right", cc, maps=_CHASE_MAPS)       # 单向入虚空房（无出口）
        assert out["missed"] is False                          # 1 未达错失窗口（仅信息位）
        assert out["reachable"] is False                       # 2 虚空房不可达目标（BFS 信息位）

    def test_caught_prepares_continue_data(self) -> None:
        ctx = _pctx("corridor")
        cc = _chase(boss_flow=StubBossFlow())
        out = pursue(ctx, "up", cc, maps=_CHASE_MAPS)
        assert out["caught"] is True                           # 1 捕获
        assert out["continue_data"]["resume"] is True          # 2 续战准备标记（R19）
        assert out["continue_data"]["pv_half_value"] == 150    # 3 PV 半值随续战准备交付（M14 消费）