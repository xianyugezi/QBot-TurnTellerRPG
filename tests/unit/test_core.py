"""core 层单测：属性三层管线 / 派生属性 / 前缀渲染（细化_3b#TC-01~18 + 细化_3d#TC-01~03）。

纯逻辑、零 NoneBot。
"""
from __future__ import annotations

import math

from qbot_rpg.core.message_format.prefix_render import render_prefix
from qbot_rpg.core.player_attributes import (
    block_rate, calc_final_attr, crit_rate, crit_roll, elem_reduce,
    hit_rate, mag_reduce, phys_reduce,
)


# ---- 3b TC-01~04 / TC-09 / TC-18 三层管线 ----
def test_tc01_three_layer_floor():
    v = calc_final_attr("str", base=15, growth=0, level=1, free_points=0,
                        flat_bonus=5, pct_bonus=10, temp_flat=0, temp_pct=20)
    assert v == 26  # 20 -> 22 -> 26.4 -> floor 26


def test_tc02_pct_once():
    v = calc_final_attr("str", base=15, growth=0, level=1, free_points=0,
                        flat_bonus=5, pct_bonus=30, temp_flat=0, temp_pct=0)
    assert v == 26  # pct 10+20 同层合并 30，只乘一次 20*1.3


def test_tc04_cond_basis_is_base_total():
    # 基准=基础合计 20（白15+flat5）；pct=100% -> boosted=40 + cond 15 = 55
    v = calc_final_attr("str", base=15, growth=0, level=1, free_points=0,
                        flat_bonus=5, pct_bonus=100, temp_flat=0, temp_pct=0,
                        cond_rule=lambda bt: 15.0 if bt == 20 else 99.0)
    assert v == 55


def test_tc09_cond_not_multiplied():
    v = calc_final_attr("str", base=15, growth=0, level=1, free_points=0,
                        flat_bonus=5, pct_bonus=10, temp_flat=0, temp_pct=20,
                        cond_rule=lambda bt: 15.0)
    assert v == 41  # 26.4+15=41.4 -> floor 41，条件不被 pct 再乘


def test_tc18_resource_no_pct():
    v = calc_final_attr("hp", base=100, growth=0, level=1, free_points=0,
                        flat_bonus=0, pct_bonus=10, temp_flat=0, temp_pct=20,
                        pct_enabled=False)
    assert v == 100  # resource 型默认不吃百分比（ADR-02）


def test_white_base_growth():
    # 3b L168：白值 = base+growth*(lv-1)+加点
    v = calc_final_attr("str", base=15, growth=1.5, level=50, free_points=10,
                        flat_bonus=0, pct_bonus=0, temp_flat=0, temp_pct=0)
    assert v == 98  # 15+1.5*49+10=98.5 -> floor 98


# ---- 3b TC-12~16 派生属性 ----
def test_crit_rate_formula():
    assert crit_rate(100.0, 0.0, 95) == 5.0
    assert crit_rate(100.0, 3.0, 95) == 8.0
    assert crit_rate(40000.0, 0.0, 95) == 95.0  # cap
    assert crit_rate(40000.0, 0.0, 0) > 95.0     # cap=0 不封顶


def test_crit_roll_three_tiers():
    assert crit_roll(100.0, 1) == 2.2    # P=5, r<=5 高级
    assert crit_roll(100.0, 10) == 1.7   # 5<r<=15 中级
    assert crit_roll(100.0, 20) == 1.3   # r>15 低级
    assert crit_roll(100.0, 1, 3) == 2.35  # 超会心 Lv3


def test_hit_rate_edges():
    assert hit_rate(30.0, 0.0, 1) == 100.0  # 敌敏 0 -> 100%
    assert hit_rate(0.0, 0.0, 1) == 100.0   # 双方 0 -> 100%
    assert math.isclose(hit_rate(5.0, 5.0, 1), 50.0)
    assert math.isclose(hit_rate(30.0, 60.0, 2), 20.0)  # K=2: 30/(30+120)=20%


def test_block_phys_elem():
    assert block_rate(150.0) == 40.0        # cap 40%
    assert phys_reduce(100.0) == 50.0       # K=100
    assert elem_reduce(100.0) == 50.0


def test_mag_reduce_formula():
    """M0 复查补测：mag_reduce 委托 damage.defense_factor（精神 100 → 50%）。"""
    assert mag_reduce(100.0) == 50.0        # K=100
    assert mag_reduce(0.0) == 0.0           # 0 精神 → 0% 减伤
    assert mag_reduce(300.0) == 75.0        # 300/(300+100)=75%


# ---- 3d TC-01~03 前缀三态 ----
def test_prefix_three_states():
    assert render_prefix(35, "阿伟", "斩龙者") == "Lv35.阿伟 -斩龙者-"
    assert render_prefix(35, "阿伟", None) == "Lv35.阿伟 - -"
    assert render_prefix(35, "阿伟", None, hide_when_empty=True) == "Lv35.阿伟"


def test_prefix_no_cq_code():
    outs = [render_prefix(35, "阿伟", "斩龙者"), render_prefix(35, "阿伟", None)]
    assert all("[CQ:" not in s for s in outs)
