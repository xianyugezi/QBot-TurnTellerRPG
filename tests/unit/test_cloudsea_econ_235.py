# -*- coding: utf-8 -*-
"""九期批次 235 定向测试：recipe/economy 直载＋游戏日合成时钟。"""
import json
import io
import os

from qbot_rpg.core.cloudsea_clock import (
    CLOUDSEA_EPOCH_ANCHOR, NOON_OFFSET_SECONDS, SECONDS_PER_DAY,
    synth_now, game_week, is_in_beast_window,
)

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load(name):
    p = os.path.join(_ROOT, "content", "cloudsea", name)
    return json.load(io.open(p, encoding="utf-8"))


# ---------------------------------------------------------------- 直载


def test_recipes_counts():
    d = _load("recipes.json")
    assert d["_meta"]["counts"] == {"recipes": 86, "depth1": 42, "depth2": 14}
    assert len(d["recipes"]) == 86 and len(d["depth1"]) == 42 and len(d["depth2"]) == 14


def test_recipes_id_unique_and_links():
    d = _load("recipes.json")
    rids = {r["id"] for r in d["recipes"]}
    assert len(rids) == 86
    for ad in d["depth1"]:
        assert ad["base_ref"] in rids, ad  # AD1 挂靠配方在库
    d1ids = {a["id"] for a in d["depth1"]}
    for ad2 in d["depth2"]:
        assert ad2["base_ref"] in d1ids, ad2  # AD2 唯一挂靠 AD1
    assert len({a["base_ref"] for a in d["depth1"]}) == len(d["depth1"])  # 每配方至多 1 AD1
    assert len({a["base_ref"] for a in d["depth2"]}) == len(d["depth2"])  # 每AD1至多1 AD2


def test_depth_coefs_within_caps():
    d = _load("recipes.json")
    # 「复合申报」条目（分项分别 ≤带顶）coef=None 合法；数值条目 ≤1.5/1.9
    for a in d["depth1"]:
        if a["coef"] is None:
            assert "复合" in a.get("coef_note", ""), a["id"]
        else:
            assert a["coef"] <= 1.5, a["id"]
    for a in d["depth2"]:
        if a["coef"] is None:
            assert "复合" in a.get("coef_note", ""), a["id"]
        else:
            assert a["coef"] <= 1.9, a["id"]


def test_economy_keys():
    e = _load("economy.json")
    assert e["sigil_daily"]["grant_per_game_day"] == 6
    assert e["beast_window"]["windows_per_day"] == 1
    assert e["material_daily_rotation"]["formula"] == "D % 7"
    assert e["feeding_per_game_day"] == 3


# ---------------------------------------------------------------- 合成时钟


def test_synth_now_formula():
    assert synth_now(0) == CLOUDSEA_EPOCH_ANCHOR + NOON_OFFSET_SECONDS
    assert synth_now(7) == CLOUDSEA_EPOCH_ANCHOR + 7 * SECONDS_PER_DAY + NOON_OFFSET_SECONDS
    assert synth_now(-3) == synth_now(0)  # 负日防御钳 0
    assert synth_now(5) == synth_now(5)   # 同日重进同 now（幂等）


def test_game_week():
    assert game_week(0) == 0 and game_week(6) == 0
    assert game_week(7) == 1 and game_week(14) == 2


def test_beast_window_daily():
    assert is_in_beast_window(3) is True
    assert is_in_beast_window(3, windows_per_day=1) is True
