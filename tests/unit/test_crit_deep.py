"""负会心 + 属性会心参数数值层单测（怪猎对照采纳 E19/E21）。

依据：怪猎对照采纳 E19（负会心：会心率 P 可为负，负率=min(100%, −P)，
档位 ×0.75 可配 negative_crit，0=关，不吃超会心）/ E21（属性会心：元素通道
默认不吃会心，天赋 Lv1-3 每级 +elem_crit_step，缺省 0.05）。
覆盖：crit_roll 负会心档 / 边界含等号 / 负率封顶 / 开关 / 正会心回归 /
负档不吃超会心 / crit_prob 负值透传 / loader crit 段装配 / 默认值。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.damage import CritParams, crit_prob, crit_roll
from qbot_rpg.core.formula_loader import load_formula_params


# ---------------- E19 负会心（crit_roll） ----------------
def test_negative_crit_hit():
    """E19：P<0 且 r 落在负率内 → 负会心档 ×0.75。"""
    assert crit_roll(0.05, 0, p_override=-0.2) == ("negative", 0.75)


def test_negative_crit_outside_low():
    """E19：r 落在负率外 → 照常判低档 ×1.3（负率不额外扩档）。"""
    assert crit_roll(0.5, 0, p_override=-0.2) == ("low", 1.3)


def test_negative_rate_capped_at_one():
    """E19：负率封顶 100%——min(1, −P)=1.0 时 r∈[0,1] 均判负会心。"""
    assert crit_roll(0.999, 0, p_override=-1.5) == ("negative", 0.75)
    assert crit_roll(0.05, 0, p_override=-1.5) == ("negative", 0.75)


def test_negative_boundary_inclusive():
    """E19：负率边界含等号——r == −P 判负会心，r 略大判低档。"""
    assert crit_roll(0.2, 0, p_override=-0.2) == ("negative", 0.75)
    assert crit_roll(0.201, 0, p_override=-0.2) == ("low", 1.3)


def test_negative_crit_switch_off():
    """E19：negative_crit=0 → 负会心关（负率内也回归低档）。"""
    assert crit_roll(0.05, 0, p_override=-0.2, negative_crit=0) == ("low", 1.3)


def test_positive_crit_regression():
    """正值回归（E19 不改动正会心）：p=0.1 → r 0.1/0.3/0.5 = high/mid/low。"""
    assert crit_roll(0.1, 0, p_override=0.1) == ("high", 2.2)
    assert crit_roll(0.3, 0, p_override=0.1) == ("mid", 1.7)
    assert crit_roll(0.5, 0, p_override=0.1) == ("low", 1.3)


def test_negative_crit_ignores_super_crit():
    """E19：负会心档不吃超会心加成——super_crit_level=3 仍返回 0.75。"""
    assert crit_roll(0.05, 0, p_override=-0.2, super_crit_level=3) == ("negative", 0.75)


# ---------------- E19 负值透传（crit_prob） ----------------
def test_crit_prob_negative_passthrough():
    """crit_prob 负值透传：P 可为负（负会心来源）——cap 只封顶不封底。"""
    assert crit_prob(0, crit_bonus=-0.3) == pytest.approx(-0.3)
    assert crit_prob(0, crit_bonus=-0.3, slash_crit=0.05) == pytest.approx(-0.25)


# ---------------- E19/E21 参数装配（loader + 默认值） ----------------
def test_loader_assembles_crit_deep_params():
    """loader 装配：crit.negative_crit / crit.elem_crit_step 实读；空段回落默认。"""
    p = load_formula_params({"crit": {"negative_crit": 0.5, "elem_crit_step": 0.1}})
    assert p.crit.negative_crit == 0.5
    assert p.crit.elem_crit_step == 0.1
    d = load_formula_params({})
    assert d.crit.negative_crit == 0.75
    assert d.crit.elem_crit_step == 0.05


def test_crit_params_defaults():
    """E19/E21 默认值：CritParams() 负会心 0.75 / 属性会心步进 0.05。"""
    c = CritParams()
    assert c.negative_crit == 0.75
    assert c.elem_crit_step == 0.05
