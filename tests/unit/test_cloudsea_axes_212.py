# -*- coding: utf-8 -*-
"""九期批次 212 定向测试：资源轴三缺口 hook（tick 自然增长 / 负向增减 / 满槽 on_full）
＋ max_mod（effective_max）＋ 云海 21 轴注册数据加载。

红线自证：不 import battle/damage；纯 ResourceLifecycle / axes.json 层；
opt-in 缺省零行为（无 tick_per_round 字段的轴 tick 后零增减）。
"""
import io
import json
import os

import pytest

from qbot_rpg.core.resource_lifecycle import ResourceLifecycle

_AXES_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "content", "cloudsea", "axes.json",
)


def _load_axes():
    with io.open(_AXES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _state(**sides):
    rs = {}
    for side, values in sides.items():
        rs[side] = dict(values)
    return {"resource_state": rs}


# ---------------------------------------------------------------- 云海 21 轴注册


def test_cloudsea_axes_21_registered():
    axes = _load_axes()
    axes_only = {k: v for k, v in axes.items() if not k.startswith("_")}
    assert len(axes_only) == 21
    assert axes["_meta"]["player"] == 17
    assert axes["_meta"]["enemy"] == 4


def test_cloudsea_axes_fields_legal():
    axes = _load_axes()
    for axis_id, raw in axes.items():
        if axis_id.startswith("_"):
            continue
        assert isinstance(raw.get("max"), int) and raw["max"] > 0, axis_id
        assert raw.get("type") in ("rage", "resource"), axis_id
        # opt-in 字段缺省口径
        raw.setdefault("tick_per_round", 0)
        raw.setdefault("tick_floor", 0)
        raw.setdefault("on_full", "")


def test_cloudsea_tick_sources_match_design():
    """tick 值对设计稿键：风缆 WIND_PER_TURN=2 / 潮压 SURGE.GAIN_PER_ROUND=+2。"""
    axes = _load_axes()
    assert axes["cs_wind"]["tick_per_round"] == 2
    assert axes["cs_surge"]["tick_per_round"] == 2


# ---------------------------------------------------------------- tick 自然增长


def test_tick_growth_and_cap():
    reg = {"a": {"max": 10, "tick_per_round": 3}}
    lc = ResourceLifecycle(reg)
    st = _state(player={"a": 8}, enemy={})
    out = lc.settle_round_tick(st)
    assert st["resource_state"]["player"]["a"] == 10  # 8+3 → cap 10
    assert out["on_full_fired"] == []


def test_tick_decay_floor():
    reg = {"a": {"max": 10, "tick_per_round": -4, "tick_floor": 2}}
    lc = ResourceLifecycle(reg)
    st = _state(player={"a": 5}, enemy={})
    lc.settle_round_tick(st)
    assert st["resource_state"]["player"]["a"] == 2  # 5-4 → floor 2（衰减不破下限）


def test_tick_zero_optin_untouched():
    """无 tick_per_round 字段 → 零增减（opt-in 红线：既有包零影响）。"""
    reg = {"legacy": {"max": 10}}
    lc = ResourceLifecycle(reg)
    st = _state(player={"legacy": 7}, enemy={})
    lc.settle_round_tick(st)
    assert st["resource_state"]["player"]["legacy"] == 7


def test_tick_frozen_side_skipped():
    """被控侧（frozen_sides）整侧跳过——S4 被控不增不减契约。"""
    reg = {"a": {"max": 10, "tick_per_round": 5}}
    lc = ResourceLifecycle(reg)
    st = _state(player={"a": 1}, enemy={"a": 1})
    lc.settle_round_tick(st, frozen_sides=["player"])
    assert st["resource_state"]["player"]["a"] == 1  # 冻结
    assert st["resource_state"]["enemy"]["a"] == 6  # 正常 tick


def test_tick_on_full_fired():
    reg = {"a": {"max": 10, "tick_per_round": 2, "on_full": "surge_burst"}}
    lc = ResourceLifecycle(reg)
    st = _state(player={}, enemy={"a": 9})
    out = lc.settle_round_tick(st)
    assert st["resource_state"]["enemy"]["a"] == 10
    assert out["on_full_fired"] == [
        {"side": "enemy", "axis": "a", "proc": "surge_burst"}
    ]


def test_tick_no_on_full_below_max():
    reg = {"a": {"max": 10, "tick_per_round": 2, "on_full": "p"}}
    lc = ResourceLifecycle(reg)
    st = _state(player={}, enemy={"a": 5})
    out = lc.settle_round_tick(st)
    assert out["on_full_fired"] == []  # 7 < 10 不触发


# ---------------------------------------------------------------- 负向增减


def test_gain_negative_clamp_zero():
    reg = {"s": {"max": 8}}
    lc = ResourceLifecycle(reg)
    st = _state(player={}, enemy={"s": 3})
    lc.apply_gain(st, "enemy", {"s": -5})  # 气力 3-5 → 下限 0
    assert st["resource_state"]["enemy"]["s"] == 0


def test_gain_negative_pool_clamp_zero():
    reg = {"p": {"max": 6, "pools": ["fire", "water"]}}
    lc = ResourceLifecycle(reg)
    st = _state(player={"p": {"fire": 1, "water": 2}}, enemy={})
    lc.apply_gain(st, "player", {"p.fire": -3})
    assert st["resource_state"]["player"]["p"]["fire"] == 0  # 池级负向下限


# ---------------------------------------------------------------- max_mod


def test_effective_max_mod():
    reg = {"m": {"max": 3}, "inf": {"max": 0}}
    lc = ResourceLifecycle(reg)
    assert lc.effective_max("m", 0) == 3
    assert lc.effective_max("m", 1) == 4  # 本命/御风流式修正
    assert lc.effective_max("m", -2) == 1
    assert lc.effective_max("inf", 5) == 0  # 0=不限：mod 不生效（保持不限语义）


def test_movement_wind_spore_mods_from_axes():
    """云海三处 max_mod 场景轴：乐章 3(+1)／风缆 3(+1)／孢子 3(+2)。"""
    axes = _load_axes()
    assert axes["cs_movement"]["max"] == 3
    assert axes["cs_wind"]["max"] == 3
    assert axes["cs_spore"]["max"] == 3


# ---------------------------------------------------------------- 幂等/降级


def test_tick_empty_registry_noop():
    lc = ResourceLifecycle({})
    st = _state(player={"x": 1}, enemy={})
    out = lc.settle_round_tick(st)
    assert out["player"] == {"x": 1}


def test_tick_bad_state_safe():
    lc = ResourceLifecycle({"a": {"max": 5, "tick_per_round": 1}})
    assert lc.settle_round_tick({}) == {}
    assert lc.settle_round_tick({"resource_state": {}})["on_full_fired"] == []
