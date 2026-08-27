"""伤害公式模块单测（M1 战斗核心 · 细化_1a 验收 T01~T32 数值断言）。

依据：细化_1a_伤害公式数值 §1（乘区字段级定义）/§3（边界异常）/§4（验收用例
T01-T38）+ 战斗数值层设计定稿 L16-35。对应 M0 阶段 gate=verify_m1(引擎覆盖部分)。
"""
from __future__ import annotations

import pytest

from qbot_rpg.core.damage import (
    block_rate,
    channel_elem,
    channel_phys,
    crit_prob,
    crit_roll,
    defense_factor,
    effective_con,
    elem_factor,
    hit_rate,
    total_damage,
)


# ---------------- A 命中与会心频率（T01-T07） ----------------
def test_t01_hit_clamp_low():
    assert round(hit_rate(10, 1000), 3) == 0.10  # 10/(10+200)=0.0476 -> clamp 10%


def test_t02_hit_clamp_high():
    assert round(hit_rate(1000, 1), 3) == 0.95  # 0.9998 -> clamp 95%


def test_t03_hit_mid_range():
    # K=1（2026-08-24 用户拍板统一 3b/1a 口径）：同级 50/50 → 0.5
    assert round(hit_rate(50, 50), 3) == 0.5  # 50/(50+1*50)=0.5


def test_t05_crit_prob_formula():
    assert crit_prob(100) == 0.05  # P=√100×0.5%
    assert crit_prob(0) == 0.0


def test_t06_tier_boundaries():
    t, m = crit_roll(0.05, 100)   # r == P -> high
    assert t == "high" and m == 2.2
    t, m = crit_roll(0.15, 100)   # r == 3P -> mid
    assert t == "mid" and m == 1.7
    t, m = crit_roll(0.16, 100)   # r > 3P -> low
    assert t == "low" and m == 1.3


def test_t07_slash_crit_bonus():
    assert crit_prob(0, slash_crit=0.05) == 0.05  # P=0 + 5% 斩击加成


def test_t10_crit_cap():
    assert crit_prob(100000, cap=95) == 0.95  # 封顶 95%


# ---------------- B 会心倍率（T08-T09） ----------------
def test_t08_tiers():
    assert crit_roll(0.0, 100, tier_p=(1, 3))[1] == 2.2
    assert crit_roll(0.05, 100)[1] == 2.2
    assert crit_roll(0.16, 100)[1] == 1.3


def test_t09_super_crit_levels():
    assert crit_roll(0.05, 100, super_crit_level=1)[1] == pytest.approx(2.25)
    assert crit_roll(0.05, 100, super_crit_level=2)[1] == pytest.approx(2.30)  # 浮点 2.2+0.10
    assert crit_roll(0.05, 100, super_crit_level=3)[1] == pytest.approx(2.35)


# ---------------- C 格挡（T11-T13） ----------------
def test_t11_block_rate_cap():
    assert block_rate(150) == 0.40  # 150/300=0.5 -> cap 40%
    assert block_rate(0) == 0.0


# ---------------- D 防御减伤（T14-T18） ----------------
def test_t14_defense_factor():
    assert round(defense_factor(100), 3) == 0.5


def test_t15_defense_zero_no_divzero():
    assert defense_factor(0) == 1.0  # 0 防御不减免不增伤


def test_t16_pierce_effective_con():
    assert effective_con(100, 0.2) == 80
    assert round(defense_factor(effective_con(100, 0.2)), 4) == round(100 / 180, 4)


def test_t18_elem_resistance():
    assert elem_factor(0) == 1.0
    assert round(elem_factor(100), 3) == 0.5


# ---------------- E 弱点（T19-T21） ----------------
def test_t19_t20_weakness_mult_applied_to_channel():
    # 物理通道弱电 x1.3：165 攻、低级会心 1.3、无防御（eff_con=0 -> factor 1.0）
    no = channel_phys(165, 1.0, 1.0, 1.3, 1.0)
    weak = channel_phys(165, 1.0, 1.3, 1.3, 1.0)
    assert round(weak, 0) == round(no * 1.3, 0)  # 214 -> 278


# ---------------- F 通道与取整（T22-T26） ----------------
def test_t23_channel_floor_and_floor_once():
    # 通道末仅 floor 一次：214.5 -> 214（不逐段 floor）
    assert channel_phys(165, 1.0, 1.0, 1.3, 1.0) == 214
    assert channel_elem(74, 1.0, 1.0, 1.3, 1.0) == 96


def test_t24_total_damage_floor_min_1():
    assert total_damage(0, 0, rng=1.0) == (1, False)  # 双通道 0 -> 1


def test_t26_guard_command_halves():
    raw, _ = total_damage(214, 96, rng=1.0)
    raw_g, _ = total_damage(214, 96, rng=1.0, guard=True)
    assert raw == 310 and raw_g == 155  # 防御指令 x0.5


# ---------------- G 管线（T27 定稿样例） ----------------
def test_t27_spec_sample_214_96_310():
    """细化_1a §8.1 样例：ch_phys=214 / ch_elem=96 / 拦截链前和=310。"""
    assert channel_phys(165, 1.0, 1.0, 1.3, 1.0) == 214
    assert channel_elem(74, 1.0, 1.0, 1.3, 1.0) == 96
    raw, _ = total_damage(214, 96, rng=1.0)
    assert raw == 310


# ---------------- H 公式参数 fixture 对照（FIX-4 承接：D6 F-FIX-01~27 经
# formula_params 读取器注入，禁测试内硬编码 dataclass 默认值，TC-5d-05） ----------------
def test_formula_params_fixture_matches_segments(formula_params):
    """FIX-2 读取器装配对照（D6 TC-FIX-02 抽样）：fixture 值 = legal formula.json 段参数
    = F-FIX 表默认（base_attack_mult=1.0 / rng=[0.9,1.1] / hit.k=1.0 / crit.tiers=2.2,1.7,1.3 /
    block.k=150 / defense.k=100 / weakness.type_mult=1.3 / derived=1.5 / monster_def_rate=1.0）。"""
    p = formula_params
    assert p.base_attack_mult == 1.0
    assert p.rng == (0.9, 1.1)
    assert p.hit.k == 1.0 and p.hit.cap_min == 10 and p.hit.cap_max == 95
    assert p.crit.cap == 95 and p.crit.p_coef == 0.5
    assert p.crit.tiers.high == 2.2 and p.crit.tiers.mid == 1.7 and p.crit.tiers.low == 1.3
    assert p.crit.tier_p == (1, 3)
    assert p.crit.crit_mult_up.lv1 == 0.05 and p.crit.crit_mult_up.lv3 == 0.15
    assert p.block.k == 150 and p.block.cap == 40 and p.block.magic_ignores is True
    assert p.block.halve_after_block is True
    assert p.defense.mode == "ratio" and p.defense.k == 100
    assert p.defense.pierce_types == {"blunt": 0.2}
    assert p.weakness.type_mult == 1.3 and p.weakness.element_mult == 1.3
    assert p.type_affinity.enabled is True and p.type_affinity.slash_crit == 0.05
    assert p.type_affinity.magic_ignore_block is True
    assert p.derived.max_total_mult == 1.5
    assert p.monster_def_rate == 1.0        # O1 裁决：默认 1.0
    assert p.elements["earth"] == "地" and len(p.elements) == 8
