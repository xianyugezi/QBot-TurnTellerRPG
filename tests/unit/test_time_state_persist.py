"""world_time_persist（M35 / IF11 time_state 数据契约）单元测试。

依据：细化_2a4a §六 TC-13（重启恢复缓存索引一致、map_weather_seen 只含访问过的图、
      跨内容包迁移不崩）+ 细化_2a4c §1.1 IF11（字段级迁移缺补默认多忽略、去重 =
      缓存与重算相等不播）+ m3_shared_contract §5.3 IF11。

覆盖：缺补默认 / 多忽略迁移 / 保存写回 / map_weather_seen 惰性 / 缓存索引相等判定。
零 NoneBot、零 IO（store 由用例直接构造 dict 传入）。
"""
from __future__ import annotations

from qbot_rpg.data.world_time_persist import (
    DEFAULT_TIME_STATE,
    cache_indexes_equal,
    load_time_state,
    mark_map_seen,
    save_time_state,
)

# 契约字段（IF11：season_idx/period_idx/weather_tick/map_weather_seen）
_KEYS = ("season_idx", "period_idx", "weather_tick", "map_weather_seen")


def _default() -> dict:
    return {"season_idx": 0, "period_idx": 0, "weather_tick": 0, "map_weather_seen": {}}


# -------------------------------------------------------------------------------------
# 缺补默认（load_time_state）
# -------------------------------------------------------------------------------------
def test_default_constant_shape():
    assert set(DEFAULT_TIME_STATE) == set(_KEYS)
    assert DEFAULT_TIME_STATE["season_idx"] == 0
    assert DEFAULT_TIME_STATE["period_idx"] == 0
    assert DEFAULT_TIME_STATE["weather_tick"] == 0
    assert DEFAULT_TIME_STATE["map_weather_seen"] == {}


def test_load_store_none_returns_full_default():
    assert load_time_state(None) == _default()
    # 返回独立实例：改返回值不影响下次调用（不共享可变对象）
    a = load_time_state(None)
    a["map_weather_seen"]["x"] = 1
    assert load_time_state(None) == _default()


def test_load_non_dict_store_returns_full_default():
    for bad in ("str", 42, [], 3.14):
        assert load_time_state(bad) == _default()  # type: ignore[arg-type]


def test_load_missing_time_state_returns_full_default():
    assert load_time_state({}) == _default()
    assert load_time_state({"other_key": 1}) == _default()
    assert load_time_state({"time_state": None}) == _default()
    assert load_time_state({"time_state": "junk"}) == _default()


def test_load_partial_fills_missing_with_default():
    ts = load_time_state({"time_state": {"season_idx": 2}})
    assert ts == {"season_idx": 2, "period_idx": 0, "weather_tick": 0, "map_weather_seen": {}}
    ts = load_time_state({"time_state": {"period_idx": 4, "weather_tick": 233376}})
    assert ts == {"season_idx": 0, "period_idx": 4, "weather_tick": 233376, "map_weather_seen": {}}


def test_load_wrong_types_fall_back_to_default_per_field():
    ts = load_time_state({"time_state": {
        "season_idx": "2",          # 非 int → 默认 0
        "period_idx": True,         # bool 是 int 子类 → 拒绝 → 默认 0
        "weather_tick": None,
        "map_weather_seen": "x",    # 非 Mapping → 默认 {}
    }})
    assert ts == _default()


# -------------------------------------------------------------------------------------
# 多忽略迁移（未知键忽略，跨内容包不崩）
# -------------------------------------------------------------------------------------
def test_load_ignores_unknown_keys():
    ts = load_time_state({"time_state": {
        "season_idx": 1,
        "future_field": "x",
        "version": 99,
        "nested": {"a": 1},
    }})
    assert ts == {"season_idx": 1, "period_idx": 0, "weather_tick": 0, "map_weather_seen": {}}


def test_load_preserves_seen_values_and_stringifies_keys():
    ts = load_time_state({"time_state": {
        "map_weather_seen": {"map_a": "fog", 7: "rain"},
    }})
    assert ts["map_weather_seen"] == {"map_a": "fog", "7": "rain"}


def test_old_shape_migrates_forward():
    # 旧包（无 weather_tick / map_weather_seen）→ 加载后补默认，不崩
    old = load_time_state({"time_state": {"season_idx": 3, "period_idx": 2}})
    assert old["weather_tick"] == 0 and old["map_weather_seen"] == {}
    # 规整后写回 → 落盘形态已含全部契约字段
    saved = save_time_state({"time_state": {"season_idx": 3, "period_idx": 2}}, old)
    assert set(saved["time_state"]) == set(_KEYS)


# -------------------------------------------------------------------------------------
# 保存写回（save_time_state）
# -------------------------------------------------------------------------------------
def test_save_writes_normalized_state_and_does_not_mutate_input():
    store = {"other": "keep-me"}
    out = save_time_state(store, {"season_idx": 1, "weather_tick": 5})
    assert out["time_state"] == {
        "season_idx": 1, "period_idx": 0, "weather_tick": 5, "map_weather_seen": {},
    }
    # 非原地改：入参 store 不变（纯函数语义）
    assert store == {"other": "keep-me"}
    assert "time_state" not in store


def test_save_drops_unknown_keys_and_normalizes():
    out = save_time_state({}, {"season_idx": 2, "unknown": 1, "period_idx": True})
    assert set(out["time_state"]) == set(_KEYS)
    assert out["time_state"]["period_idx"] == 0  # bool → 默认


def test_save_non_dict_store_creates_new():
    assert save_time_state(None, {"season_idx": 1}) == {  # type: ignore[arg-type]
        "time_state": {"season_idx": 1, "period_idx": 0, "weather_tick": 0, "map_weather_seen": {}},
    }


def test_save_then_load_round_trip_stable():
    ts = {"season_idx": 2, "period_idx": 4, "weather_tick": 233376, "map_weather_seen": {"map_a": True}}
    store = save_time_state({}, ts)
    assert load_time_state(store) == ts


def test_save_copies_seen_not_aliased():
    ts = {"map_weather_seen": {"map_a": True}}
    out = save_time_state({}, ts)
    out["time_state"]["map_weather_seen"]["new_map"] = True
    assert "new_map" not in ts["map_weather_seen"]  # 不共享可变对象


# -------------------------------------------------------------------------------------
# mark_map_seen 惰性增长
# -------------------------------------------------------------------------------------
def test_mark_seen_records_only_visited_maps():
    state = _default()
    out = mark_map_seen(state, "map_a")
    assert out["map_weather_seen"] == {"map_a": True}
    out2 = mark_map_seen(out, "map_b")
    assert out2["map_weather_seen"] == {"map_a": True, "map_b": True}
    # 未访问的图不出现（TC-13「只含访问过的图」）
    assert "map_c" not in out2["map_weather_seen"]


def test_mark_seen_is_non_mutating_and_idempotent():
    state = _default()
    out = mark_map_seen(state, "map_a")
    assert state["map_weather_seen"] == {}  # 入参不变
    again = mark_map_seen(out, "map_a")
    assert again["map_weather_seen"] == {"map_a": True}  # 幂等，不重复
    assert again["season_idx"] == 0  # 其它字段原样保留


def test_mark_seen_grows_existing_loaded_state():
    state = load_time_state({"time_state": {"map_weather_seen": {"map_a": True}}})
    out = mark_map_seen(state, "map_b")
    assert out["map_weather_seen"] == {"map_a": True, "map_b": True}


def test_mark_seen_handles_non_dict_state_defensively():
    out = mark_map_seen(None, "map_a")  # type: ignore[arg-type]
    assert out["map_weather_seen"] == {"map_a": True}
    assert out["season_idx"] == 0


# -------------------------------------------------------------------------------------
# cache_indexes_equal（缓存索引 vs 重算值，IF09 去重）
# -------------------------------------------------------------------------------------
def _indexes(s=1, p=2, t=100):
    return {"season_idx": s, "period_idx": p, "weather_tick": t}


def test_indexes_equal_when_all_three_match():
    assert cache_indexes_equal(_indexes(), _indexes()) is True


def test_indexes_differ_on_each_key():
    assert cache_indexes_equal(_indexes(s=1), _indexes(s=0)) is False
    assert cache_indexes_equal(_indexes(p=2), _indexes(p=3)) is False
    assert cache_indexes_equal(_indexes(t=100), _indexes(t=101)) is False


def test_indexes_ignore_map_weather_seen_and_unknown_keys():
    cached = {**_indexes(), "map_weather_seen": {"map_a": True}, "extra": 1}
    recomputed = _indexes()
    assert cache_indexes_equal(cached, recomputed) is True


def test_indexes_missing_key_versus_value_is_unequal():
    assert cache_indexes_equal({"season_idx": 0, "period_idx": 0}, _indexes()) is False


def test_indexes_both_empty_means_no_change():
    # 无缓存 = 无变化 → 不播（相等）
    assert cache_indexes_equal({}, {}) is True


def test_indexes_non_mapping_is_unequal():
    assert cache_indexes_equal(None, _indexes()) is False
    assert cache_indexes_equal(_indexes(), "junk") is False
