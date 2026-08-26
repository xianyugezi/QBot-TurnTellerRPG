"""M3 批次4·路M（M10 天气权重刷新 + GameWorld.monster_pool 集成）单元测试。

依据：
  - 细化_2a1b_通道规则与刷怪.md §二（R18 天气权重只影响刷新不驱逐在场 / R21 地图级
    max_alive 聚合上限【工程补白 默认 10】/ R26 权重 0=该天气不刷 / R27 出没判定链 /
    R28 有效刷新间隔 = respawn_minutes/weight）
  - 规划_路2a_地图副本.md M10（天气权重刷新：weight ≥1 补刷更快 / weight=0 不补刷但
    已在场怪保留；只影响补刷结算）
  - m3_shared_contract §2.3（Spawn 行 weather_weights 默认 1；0=该天气不刷；不驱逐在场）

测试口径（对齐 test_worldtime_changes 风格）：构造输入 → 跑纯函数 → 断言结果。
  - world_state = 地图级刷怪状态切片 {行序号: {"alive", "last_refresh"}}（UTC+8 epoch 秒）
  - spawn 行兼容 raw dict 与 SpawnDef 双形态
  - GameWorld 依赖注入 maps（modules dict / {id:raw} / MapDef 列表）+ spawn_manager 鸭子类型
    （路L SpawnManager 契约：filter_eligible / alive_monsters；未注入 → monster_pool 空）
"""
from __future__ import annotations

import datetime
from typing import Any, List, Mapping, Optional

import pytest

from qbot_rpg.content.map_models import MapDef, parse_maps
from qbot_rpg.world.game_world import GameWorld
from qbot_rpg.world.spawn_weather import (
    DEFAULT_MAX_ALIVE,
    active_time_ok,
    filter_eligible_rows,
    max_alive_guard,
    spawn_eligible,
    weather_weighted_refresh,
)

_TZ_UTC8 = datetime.timezone(datetime.timedelta(hours=8))
NOW = int(datetime.datetime(2026, 8, 16, 12, 0, 0, tzinfo=_TZ_UTC8).timestamp())
MIN = 60


def _ts(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> int:
    """UTC+8 墙钟 → Unix epoch 秒（引擎 now 口径一致）。"""
    return int(datetime.datetime(y, m, d, hh, mm, 0, tzinfo=_TZ_UTC8).timestamp())


# ---------------------------------------------------------------------------
# 基础行 fixture（raw dict 形态；SpawnDef 形态见 filter 测试）
# ---------------------------------------------------------------------------
def _row(**over: Any) -> dict:
    base = {"enemy": "幽灵", "count": 5, "respawn_minutes": 10}
    base.update(over)
    return base


def _state(rows: Mapping[int, Any]) -> dict:
    """行序号 → {"alive", "last_refresh"} 的地图级刷怪状态切片。"""
    return {str(i): v for i, v in rows.items()}


# ---------------------------------------------------------------------------
# max_alive_guard：地图级在场总数上限（R21，聚合所有 spawn 行）
# ---------------------------------------------------------------------------
def test_guard_under_cap_allows_requested() -> None:
    assert max_alive_guard(alive_count=3, max_alive=10, requested=2) == 2


def test_guard_partial_cap() -> None:
    assert max_alive_guard(alive_count=8, max_alive=10, requested=5) == 2


def test_guard_over_cap_returns_zero() -> None:
    assert max_alive_guard(alive_count=10, max_alive=10, requested=1) == 0
    assert max_alive_guard(alive_count=15, max_alive=10, requested=3) == 0


def test_guard_default_max_alive_is_ten() -> None:
    assert DEFAULT_MAX_ALIVE == 10
    assert max_alive_guard(alive_count=9, requested=3) == 1  # 默认 10


def test_guard_custom_max_alive_and_clamps() -> None:
    assert max_alive_guard(alive_count=2, max_alive=3, requested=3) == 1
    assert max_alive_guard(alive_count=-1, max_alive=10, requested=2) == 2
    assert max_alive_guard(alive_count=0, max_alive=10, requested=0) == 0


# ---------------------------------------------------------------------------
# weather_weighted_refresh：天气倍率变速补刷（M10 / R28）
# ---------------------------------------------------------------------------
def test_refresh_default_weight_one() -> None:
    # weather 不在 weather_weights → 默认 1：间隔 10min，30min 流逝 → due=3
    rows = [_row()]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert len(products) == 1
    p = products[0]
    assert p["enemy"] == "幽灵" and p["count"] == 3
    assert p["row_index"] == 0 and p["weight"] == 1.0 and p["weather"] == "sunny"


def test_refresh_weight_two_faster() -> None:
    # fog 倍率 2 → 有效间隔 5min：30min 流逝 → due=6，截断到缺口 count=5 → 5 只（刷更快）
    rows = [_row(weather_weights={"fog": 2.0})]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "fog", NOW, ws)
    assert len(products) == 1 and products[0]["count"] == 5
    assert products[0]["weight"] == 2.0


def test_refresh_weight_half_slower() -> None:
    # rain 倍率 0.5 → 有效间隔 20min：30min 流逝 → due=1
    rows = [_row(weather_weights={"rain": 0.5})]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "rain", NOW, ws)
    assert len(products) == 1 and products[0]["count"] == 1


def test_refresh_weight_zero_no_spawn() -> None:
    # storm 倍率 0 = 该天气不刷（R26）：无产物、计时不推进
    rows = [_row(weather_weights={"storm": 0})]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "storm", NOW, ws)
    assert products == []
    assert ws["0"]["last_refresh"] == NOW - 30 * MIN  # 0 权重行计时冻结


def test_refresh_gap_truncated_by_alive_gap() -> None:
    # 已有 4 只在场（count=5）：due=3 截断到缺口 1
    rows = [_row()]
    ws = _state({0: {"alive": 4, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert len(products) == 1 and products[0]["count"] == 1


def test_refresh_no_record_means_no_initial_spawn() -> None:
    # 缺省行记录 → alive=0、last_refresh=now：首刷归 M07/initial_spawn，本模块不首刷
    products = weather_weighted_refresh([_row()], "sunny", NOW, {})
    assert products == []


def test_refresh_lazy_write_back_consumes_elapsed() -> None:
    # 懒计算写回：消耗全部已流逝间隔（防重复补刷）；再调用同参数 → 无新增
    rows = [_row()]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert ws["0"]["alive"] == 3
    assert ws["0"]["last_refresh"] == NOW  # 30min / 10min × 3 间隔全部消耗
    again = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert again == []  # 无新流逝 → 不重复补刷


def test_refresh_default_count_is_one() -> None:
    # count 缺省 → 1【工程补白 contract §2.3】
    row = _row()
    del row["count"]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh([row], "sunny", NOW, ws)
    assert len(products) == 1 and products[0]["count"] == 1


def test_refresh_skips_invalid_respawn_row() -> None:
    # respawn_minutes 缺失/非法（R26 必填 ≥1）→ 该行不参与补刷，其余行照常
    rows = [{"enemy": "坏行", "count": 3}, _row()]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN},
                 1: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert len(products) == 1 and products[0]["enemy"] == "幽灵"


# ---------------------------------------------------------------------------
# 在场不驱逐（R18/R30：天气变化只影响后续刷新，已在场怪保留）
# ---------------------------------------------------------------------------
def test_weather_zero_keeps_alive_monsters() -> None:
    # storm 权重 0：不补刷，但已在场 3 只保留（不驱逐）
    rows = [_row(weather_weights={"storm": 0})]
    ws = _state({0: {"alive": 3, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "storm", NOW, ws)
    assert products == []
    assert ws["0"]["alive"] == 3  # 已在场怪不被天气驱逐


def test_weather_change_only_affects_future_refresh() -> None:
    # 天气从 fog（快刷）切到 storm（0）：先前在场怪保留，后续不补刷
    rows = [_row(weather_weights={"fog": 2.0, "storm": 0})]
    ws = _state({0: {"alive": 1, "last_refresh": NOW - 30 * MIN}})
    first = weather_weighted_refresh(rows, "fog", NOW, ws)
    assert len(first) == 1 and first[0]["count"] == 4  # 缺口补满
    alive_after_fog = ws["0"]["alive"]
    assert alive_after_fog == 5
    second = weather_weighted_refresh(rows, "storm", NOW, ws)
    assert second == []  # 雷雨天不刷
    assert ws["0"]["alive"] == 5  # 天气变化不驱逐已在场怪


def test_weather_zero_row_does_not_block_other_rows() -> None:
    # 该天气下 0 权重的行跳过，其他行正常补刷
    rows = [_row(enemy="雷雨幽灵", weather_weights={"storm": 0}),
            _row(enemy="晴日幽灵", weather_weights={"storm": 2.0})]
    ws = _state({0: {"alive": 0, "last_refresh": NOW - 30 * MIN},
                 1: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "storm", NOW, ws)
    assert [p["enemy"] for p in products] == ["晴日幽灵"]
    assert ws["0"]["alive"] == 0  # 0 权重行不刷也不驱逐


# ---------------------------------------------------------------------------
# max_alive 地图级聚合上限（R21：聚合所有 spawn 行，超限不补刷）
# ---------------------------------------------------------------------------
def test_aggregate_cap_blocks_both_rows_when_full() -> None:
    # 两行合计已在场 10 = max_alive 上限 → 两行均不补刷（超限返回 0）
    rows = [_row(enemy="A", count=10), _row(enemy="B", count=5)]
    ws = _state({0: {"alive": 6, "last_refresh": NOW - 30 * MIN},
                 1: {"alive": 4, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert products == []


def test_aggregate_cap_sequential_allocation() -> None:
    # 合计 8，上限 10：行0 先获批 2 → 合计满 10 → 行1 获批 0
    rows = [_row(enemy="A", count=10), _row(enemy="B", count=5)]
    ws = _state({0: {"alive": 5, "last_refresh": NOW - 30 * MIN},
                 1: {"alive": 3, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws)
    assert len(products) == 1
    assert products[0]["enemy"] == "A" and products[0]["count"] == 2


def test_aggregate_cap_custom_max_alive() -> None:
    # 合计在场 5，自定义上限 6：行0 获批 1 → 合计满 6 → 行1 获批 0
    rows = [_row(count=10), _row(count=5)]
    ws = _state({0: {"alive": 5, "last_refresh": NOW - 30 * MIN},
                 1: {"alive": 0, "last_refresh": NOW - 30 * MIN}})
    products = weather_weighted_refresh(rows, "sunny", NOW, ws, max_alive=6)
    assert len(products) == 1 and products[0]["count"] == 1  # 6-5=1


# ---------------------------------------------------------------------------
# 出没判定链（R27 全 AND：active_time ∧ seasons ∧ periods ∧ weather_weights≠0）
# ---------------------------------------------------------------------------
def test_eligible_seasons_filter() -> None:
    row = _row(seasons=["autumn"])
    assert spawn_eligible(row, {"season": "autumn"})
    assert not spawn_eligible(row, {"season": "summer"})
    assert spawn_eligible(_row(), {"season": "summer"})  # 空=全年恒真


def test_eligible_periods_filter() -> None:
    row = _row(periods=["night", "midnight"])
    assert spawn_eligible(row, {"period": "night"})
    assert not spawn_eligible(row, {"period": "noon"})
    assert spawn_eligible(_row(), {"period": "noon"})  # 空=全天恒真


def test_eligible_weather_zero_excluded() -> None:
    row = _row(weather_weights={"storm": 0, "fog": 2.0})
    assert not spawn_eligible(row, {"weather": "storm"})
    assert spawn_eligible(row, {"weather": "fog"})
    assert spawn_eligible(row, {"weather": "sunny"})  # 缺省倍率 1


def test_eligible_active_time_window() -> None:
    row = _row(active_time={"from": "20:00", "to": "06:00"})
    assert spawn_eligible(row, {}, now=_ts(2026, 8, 16, 22, 0))  # 窗口内
    assert spawn_eligible(row, {}, now=_ts(2026, 8, 16, 2, 0))  # 跨夜后段
    assert not spawn_eligible(row, {}, now=_ts(2026, 8, 16, 12, 0))  # 窗口外
    assert spawn_eligible(_row(), {}, now=_ts(2026, 8, 16, 12, 0))  # 空=全天


def test_eligible_active_time_ok_helper() -> None:
    assert active_time_ok({}, now=NOW)
    assert active_time_ok(None, now=NOW)
    assert active_time_ok({"from": "09:00", "to": "17:00"}, now=_ts(2026, 8, 16, 10, 0))
    assert not active_time_ok({"from": "09:00", "to": "17:00"}, now=_ts(2026, 8, 16, 20, 0))


def test_eligible_all_and_chain() -> None:
    # TC-16：半满足（仅时段满足）→ 不出现——全 AND 叠加
    row = _row(seasons=["autumn"], periods=["night"], weather_weights={"fog": 1.0, "storm": 0})
    assert not spawn_eligible(row, {"season": "summer", "period": "night", "weather": "fog"})
    assert not spawn_eligible(row, {"season": "autumn", "period": "noon", "weather": "fog"})
    assert not spawn_eligible(row, {"season": "autumn", "period": "night", "weather": "storm"})
    assert spawn_eligible(row, {"season": "autumn", "period": "night", "weather": "fog"})


def test_filter_eligible_rows_subset() -> None:
    rows = [_row(enemy="A", seasons=["autumn"]),
            _row(enemy="B", weather_weights={"storm": 0}),
            _row(enemy="C")]
    got = filter_eligible_rows(rows, {"season": "autumn", "weather": "storm"})
    assert [r["enemy"] for r in got] == ["A", "C"]  # B 被天气 0 排除


def test_filter_eligible_accepts_spawndef() -> None:
    # SpawnDef 形态（map_models）与 raw dict 同语义
    maps = parse_maps({"maps": [{
        "id": "m1", "name": "M1",
        "spawn": [
            {"enemy": "X", "count": 2, "respawn_minutes": 10, "seasons": ["winter"]},
            {"enemy": "Y", "count": 2, "respawn_minutes": 10},
        ],
    }]})
    defs = maps[0].spawn_defs()
    got = filter_eligible_rows(defs, {"season": "summer"})
    assert len(got) == 1 and got[0].enemy == "Y"


# ---------------------------------------------------------------------------
# GameWorld.monster_pool / get_boss 集成（注入 maps + spawn 管理）
# ---------------------------------------------------------------------------
_MAP_RAW = {
    "id": "molten_corridor", "name": "熔岩走廊",
    "spawn": [
        {"enemy": "幽灵", "count": 5, "respawn_minutes": 10,
         "seasons": ["autumn"], "periods": ["night"],
         "weather_weights": {"fog": 2.0, "storm": 0}},
        {"enemy": "熔岩史莱姆", "count": 3, "respawn_minutes": 20},
    ],
    "gate_guard": "熔岩守卫",
}
_MAP_NO_GUARD = {"id": "molten_core", "name": "熔岩核心", "spawn": []}


class _FakeSpawnManager:
    """完整路L SpawnManager 契约（filter_eligible(spawn_row, now) + alive_monsters）。"""

    def __init__(self, alive: Optional[List[Mapping[str, Any]]] = None) -> None:
        self.alive = list(alive) if alive is not None else []
        self.filter_calls: List[tuple] = []

    def filter_eligible(self, spawn_row: Any, now: Optional[int] = None) -> bool:
        self.filter_calls.append((spawn_row, now))
        return _enemy(spawn_row) != "熔岩史莱姆"

    def alive_monsters(self, map_id: str) -> List[Mapping[str, Any]]:
        return self.alive


class _FilterOnlyManager:
    """仅 filter_eligible（路L 单行契约），无 alive_monsters（存储接线 M4 未落盘）。"""

    def filter_eligible(self, spawn_row: Any, now: Optional[int] = None) -> bool:
        return _enemy(spawn_row) != "熔岩史莱姆"


def _enemy(r: object) -> Any:
    return r.get("enemy") if isinstance(r, Mapping) else getattr(r, "enemy", None)


def _gameworld(spawn_manager: Any = None, maps: Any = None,
               ctx_provider: Any = None) -> GameWorld:
    return GameWorld(maps=maps if maps is not None else {"maps": [_MAP_RAW, _MAP_NO_GUARD]},
                     spawn_manager=spawn_manager, ctx_provider=ctx_provider)


def test_monster_pool_delegates_to_spawn_manager() -> None:
    fake = _FakeSpawnManager(alive=[{"enemy": "幽灵", "hp": 100}])
    gw = _gameworld(fake)
    pool = gw.monster_pool("molten_corridor")
    assert pool == [{"enemy": "幽灵", "hp": 100}]
    # 过滤被调用（调 spawn 过滤）：每行一次（路L 单行契约 filter_eligible(row, now)）
    assert len(fake.filter_calls) == 2
    rows_seen = [call[0] for call in fake.filter_calls]
    assert [r.enemy for r in rows_seen] == ["幽灵", "熔岩史莱姆"]  # 读该图 spawn 表


def test_monster_pool_placeholder_from_eligible_rows() -> None:
    # 管理器未提供 alive_monsters → 按可出没行返回占位条目（存储接线 M4 补白）
    gw = _gameworld(_FilterOnlyManager())
    pool = gw.monster_pool("molten_corridor")
    assert pool == [{"enemy": "幽灵", "alive": 0}]  # 熔岩史莱姆被管理器过滤掉


def test_monster_pool_without_spawn_manager_empty() -> None:
    assert _gameworld(None).monster_pool("molten_corridor") == []


def test_monster_pool_unknown_map_empty() -> None:
    fake = _FakeSpawnManager(alive=[{"enemy": "幽灵"}])
    assert _gameworld(fake).monster_pool("no_such_map") == []


def test_monster_pool_ctx_provider_feeds_local_filter() -> None:
    # 无 filter_eligible 的管理器（空对象）→ 本地 filter_eligible_rows + ctx_provider 上下文
    gw = _gameworld(object(), ctx_provider=lambda map_id: {"season": "winter", "period": "noon"})
    pool = gw.monster_pool("molten_corridor")
    # 幽灵 seasons=[autumn] 在冬季不出现；熔岩史莱姆无季节限定 → 保留
    assert pool == [{"enemy": "熔岩史莱姆", "alive": 0}]


def test_monster_pool_with_real_spawn_manager() -> None:
    # 收口对齐：注入已落盘的路L SpawnManager（world/spawn.py）→ 逐行调 filter_eligible(row, now)
    from qbot_rpg.world.spawn import SpawnManager as LSpawnManager

    maps = parse_maps({"maps": [_MAP_RAW, _MAP_NO_GUARD]})
    mgr = LSpawnManager(spawn_rows=maps[0].spawn_defs())
    gw = GameWorld(maps={"maps": [_MAP_RAW, _MAP_NO_GUARD]}, spawn_manager=mgr)
    pool = gw.monster_pool("molten_corridor")
    # 无 worldtime 注入 → seasons/periods 退化为不限（路L 与 IF01 同口径）→ 两行均可出没；
    # SpawnManager 无 alive_monsters → 走占位条目路径（存储接线 M4 补白）
    assert pool == [{"enemy": "幽灵", "alive": 0}, {"enemy": "熔岩史莱姆", "alive": 0}]


def test_get_boss_reads_gate_guard() -> None:
    gw = _gameworld(None)
    assert gw.get_boss("molten_corridor") == "熔岩守卫"
    assert gw.get_boss("molten_core") is None  # 未配置 gate_guard
    assert gw.get_boss("no_such_map") is None  # 未知地图 → None


def test_maps_injection_forms() -> None:
    # {id: raw} 映射形态 + MapDef 列表形态均可注入
    gw_a = GameWorld(maps={"molten_corridor": _MAP_RAW})
    assert gw_a.get_boss("molten_corridor") == "熔岩守卫"
    gw_b = GameWorld(maps=list(parse_maps({"maps": [_MAP_RAW, _MAP_NO_GUARD]})))
    assert gw_b.get_boss("molten_corridor") == "熔岩守卫"
    assert gw_b.get_boss("molten_core") is None
    assert GameWorld(maps=None).get_boss("molten_corridor") is None
