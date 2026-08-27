"""伤害公式性质用例（M6 批6·路B PRP 组 · D6 §一 PRP-1~8 / TC-PRP-01~05）。

依据：
- 《细化_M6_测试体系强化.md》（D6）：§一 PRP-1~8 规则表 L60-67 + TC-PRP-01~05 验收
  L80-84 + §1.1 机制说明 L54 + §1.3 边界异常 L71-74；随机源契约 §二 SED
  （F-SED-01~03 L109-111、§2.5 派生种子 L128）；参数来源契约 §三 FIX
  （F-FIX-01~27 L156-182、FIX-2 读取器 L189、§3.4 段缺省回退 L200）
- 《开发规则文档.md》L309：「随机 1000 组属性 → 断言不变量：伤害 ≥1、不会心时在
  [0.95,1.05]×基础 区间、会心率 ≤95%」
- 《细化_1a_伤害公式数值.md》：§3-B L298-299（最低伤害恒 ≥1）/ §1.9 M9 乱数
  L188-193（乱数 ∈ [0.9,1.1] 闭区间，一次判定双通道共用）/ §1.4-1.5 会心档位与
  频率 L119-137（三档倍率 2.2/1.7/1.3、P=√幸运×p_coef÷100、cap 95%、档位倍率
  low 1.3 ~ high+超会心 Lv3 2.35）/ §3-E L320-321（乱数端点合法、幸运 0 / 幸运极高）

三不变量（每条 1000 组固定 seed 随机，PRP-2）：
  ① 伤害恒 ≥1（命中侧通道 ≥1）（PRP-3）
  ② 非会心（low 档）total_damage ∈ [floor(基础×0.95), floor(基础×1.05)] 闭区间
    （基础 = 同输入无乱数、无格挡、无防御指令的通道和）（PRP-4）
  ③ 会心率（cap 后）恒 ≤95%；档位倍率 ∈ [1.3, 2.35]（PRP-5）

【工程补白·偏离 D6 注记】PRP-4 括号注「乱数 ∈ [0.9,1.1] 落在 [0.95,1.05] 内」在数学上
不成立（0.9 < 0.95，[0.9,1.1] ⊄ [0.95,1.05]）：若 ② 随机组按公式参数全区间 [0.9,1.1]
抽乱数，rng<0.95 的组必然跌破 floor(基础×0.95) 下界，TC-PRP-03 闭区间断言无法全绿。
故 ② 的随机乱数抽样域取契约断言带 [0.95,1.05]（断言常数，非公式参数），并在同用例内
追加乱数闭区间端点 0.9/1.1 的显式边界组（断言真实带 [floor(基础×0.9), floor(基础×1.1)]，
参数取自 formula.json damage.rng，【1a】§3-E L320 端点合法）；端点复现同时由 ① 全区间
抽样（每 50 组强制端点）覆盖。

【工程补白·fixture 来源】seed/seeded_rng/formula_params 三 fixture 由路A 落盘于
tests/conftest.py（D6 §二/§三），本文件用例直接消费 conftest 注入（无本地遮蔽、无双源）；
formula.json 已全段落位（F-FIX-01~27，路A），段缺省回退 dataclass 默认（FIX §3.4）。
"""
from __future__ import annotations

import json
from pathlib import Path
from random import Random
from typing import Any, Callable, Mapping, NamedTuple, Optional, Tuple, TypeVar

import pytest

from qbot_rpg.core.damage import (
    BlockParams,
    CritMultUp,
    CritParams,
    CritTiers,
    DamageFormulaParams,
    DefenseParams,
    DerivedParams,
    HitParams,
    TypeAffinityParams,
    WeaknessParams,
    block_rate,
    channel_elem,
    channel_phys,
    crit_prob,
    crit_roll,
    defense_factor,
    effective_con,
    elem_factor,
    hit_rate,
    pierce_pct,
    total_damage,
)

# D6 PRP-2 / TC-PRP-01：每条不变量随机组数 1000（【规则】L309「随机 1000 组属性」）。
N_GROUPS = 1000
# 收集循环护栏（拒收抽样上限）：命中率最低 10%（hit.cap_min），最坏情形 ~10000 次；
# 50000 留足余量防公式参数回归导致死循环。确定性由固定 seed 保证。
MAX_ITER = 50000

# 乱数断言带 [0.95,1.05]（开发规则 L309 / D6 PRP-4 / TC-PRP-03 契约断言常数，
# 非 formula.json 参数；公式乱数全区间 [0.9,1.1] 经 seeded_rng 抽样 + 端点组复现）。
BAND_LO = 0.95
BAND_HI = 1.05

# ---------------------------------------------------------------------------
# 随机属性生成与全管线求值（判定顺序写死：命中→会心→格挡→双通道→防御→总伤害，
# 【1a】§0.1 / 数值层 L16）
# ---------------------------------------------------------------------------

class GroupResult(NamedTuple):
    """单组命中求值结果（性质断言输入）。"""

    ch_phys: int          # 物理通道（已 floor，下限 1）
    ch_elem: int          # 元素通道（已 floor，下限 1）
    tier: str             # 会心档位 high/mid/low
    crit_mult: float      # 档位倍率输出
    crit_p: float         # 有效会心率 P（cap 后）
    total: int            # total_damage（拦截链前）
    base: int             # 基础 = ch_phys + ch_elem（无乱数/无格挡/无防御指令的通道和）
    blocked_eff: bool     # 格挡实际生效

def _draw_attrs(
    rng: Random,
    params: DamageFormulaParams,
    *,
    lck_max: float,
    guard_prob: float,
) -> dict[str, Any]:
    """随机属性（D6 §1.1：攻/防/幸运/专注/乱数 全随机；随机一律经注入 rng，PRP-6）。

    守卫概率独立消费一次随机（即使 guard_prob=0）以保持各用例 RNG 消费形状一致。
    """
    return {
        "atk": rng.uniform(0.0, 500.0),            # 物理首因子（力量侧）
        "skill_mult": rng.uniform(0.5, 3.0),       # M2 技能倍率
        "type_weak": rng.choice((1.0, params.weakness.type_mult)),  # M3 类型弱点
        "elem_atk": rng.uniform(0.0, 300.0),       # 元素首因子
        "elem_skill_mult": rng.uniform(0.5, 3.0),  # M2 元素技能倍率
        "elem_weak": rng.choice((1.0, params.weakness.element_mult)),
        "con": rng.uniform(0.0, 300.0),            # 体质 → 有效体质 → 防御系数
        "elem_res": rng.uniform(0.0, 300.0),       # 元素抗性 → 元素减伤系数
        "lck": rng.uniform(0.0, lck_max),          # 幸运 → P
        "focus": rng.uniform(10.0, 600.0),         # 专注 → 命中率/格挡率
        "enemy_spd": rng.uniform(1.0, 60.0),       # 对方敏捷
        "attack_type": rng.choice(("slash", "blunt", "thrust", "magic")),
        "super_crit": float(rng.randint(0, 3)),    # 超会心 Lv0-3（档位倍率 +0~0.15）
        "guard": rng.random() < guard_prob,        # 防御指令（M8）
    }

def _sample_rng_full(rng: Random, params: DamageFormulaParams, i: int) -> float:
    """乱数全区间抽样 [damage.rng]（D6 §1.3：闭区间端点 0.9/1.1 每 50 组强制复现）。"""
    if i % 50 == 0:
        return params.rng[0]
    if i % 50 == 25:
        return params.rng[1]
    return rng.uniform(params.rng[0], params.rng[1])

def _sample_rng_band(rng: Random, i: int) -> float:
    """不变量②乱数抽样域 = 契约断言带 [0.95,1.05]（含闭端点；【偏离 D6】注记见文件头）。"""
    if i % 100 == 0:
        return BAND_LO
    if i % 100 == 50:
        return BAND_HI
    return rng.uniform(BAND_LO, BAND_HI)

def _hit_group(
    rng: Random, params: DamageFormulaParams, attrs: Mapping[str, Any]
) -> Optional[GroupResult]:
    """单组全管线求值：命中→会心→格挡→双通道→总伤害（判定顺序写死【1a】§0.1）。

    未命中返回 None（miss → 0 伤害属状态机层，【1a】§3-G L329-331，不在此列）。
    """
    # ① 命中（【1a】§1 命中 / 数值层 L21-22）
    hr = hit_rate(
        attrs["focus"],
        attrs["enemy_spd"],
        k=params.hit.k,
        cap_min=params.hit.cap_min,
        cap_max=params.hit.cap_max,
    )
    if rng.random() > hr:
        return None
    # ② 会心（【1a】§1.4-1.5 / 数值层 L23-24；斩击加成入 P 后统一 cap，§5-⑦；
    #    p_override 注入有效 P（G1 定稿），cap 应用于档位判定前）
    attack_type = attrs["attack_type"]
    slash = (
        params.type_affinity.slash_crit
        if attack_type == "slash" and params.type_affinity.enabled
        else 0.0
    )
    p_eff = crit_prob(
        attrs["lck"],
        p_coef=params.crit.p_coef,
        crit_bonus=0.0,
        cap=params.crit.cap,
        slash_crit=slash,
    )
    tier, mult = crit_roll(
        rng.random(),
        attrs["lck"],
        p_coef=params.crit.p_coef,
        tiers=params.crit.tiers,
        tier_p=params.crit.tier_p,
        super_crit_level=int(attrs["super_crit"]),
        p_override=p_eff,
    )
    # ③ 格挡（【1a】§1.7 / 数值层 L25）
    br = block_rate(attrs["focus"], k=params.block.k, cap=params.block.cap)
    blocked = rng.random() < br
    is_magic = attack_type == "magic"
    # ④⑤ 双通道（M1/M2/M3/M4/M6 + O1；打类型内置破防，数值层 L30/L90）
    pierce = 0.0
    if params.type_affinity.enabled and attack_type == "blunt":
        pierce = pierce_pct(attack_type, blunt_pierce=params.type_affinity.blunt_pierce)
    dfac = defense_factor(
        effective_con(attrs["con"], pierce), k=params.defense.k
    )
    efac = elem_factor(attrs["elem_res"], k=params.defense.k)
    ch_phys = channel_phys(
        attrs["atk"] * params.base_attack_mult,
        attrs["skill_mult"],
        attrs["type_weak"],
        mult,
        dfac,
        params.monster_def_rate,
    )
    ch_elem = channel_elem(
        attrs["elem_atk"],
        attrs["elem_skill_mult"],
        attrs["elem_weak"],
        mult,
        efac,
        params.monster_def_rate,
    )
    # ⑥ 总伤害（M7 格挡减半 / M8 防御指令 / M9 乱数，最末一次 floor，数值层 L34-35）
    total, blocked_eff = total_damage(
        ch_phys,
        ch_elem,
        rng=float(attrs["rng_val"]),
        blocked=blocked,
        magic=is_magic,
        guard=bool(attrs["guard"]),
        magic_ignores_block=params.block.magic_ignores,
        halve_after_block=params.block.halve_after_block,
    )
    return GroupResult(
        ch_phys=ch_phys,
        ch_elem=ch_elem,
        tier=tier,
        crit_mult=mult,
        crit_p=p_eff,
        total=total,
        base=ch_phys + ch_elem,
        blocked_eff=blocked_eff,
    )

def _collect_groups(
    rng: Random,
    params: DamageFormulaParams,
    count: int,
    *,
    lck_max: float,
    guard_prob: float,
    rng_sampler: Callable[[Random, DamageFormulaParams, int], float],
    boundary_every: int = 0,
) -> Tuple[list[GroupResult], list[GroupResult]]:
    """收集 count 组命中结果（未命中拒收），返回 (全部命中组, 边界组)。

    boundary_every>0 时每 N 次循环迭代强制一组 0 攻击/0 元素攻击/0 体质边界组
    （D6 §1.3：「0 攻击 / 0 防御」边界）；边界组按迭代序单独收集
    （未命中拒收会使 groups 下标与迭代下标错位，不能切片取）。
    """
    groups: list[GroupResult] = []
    boundary: list[GroupResult] = []
    i = 0
    while len(groups) < count and i < MAX_ITER:
        attrs = _draw_attrs(rng, params, lck_max=lck_max, guard_prob=guard_prob)
        is_boundary = bool(boundary_every) and i % boundary_every == 0
        if is_boundary:
            attrs.update(atk=0.0, elem_atk=0.0, con=0.0)
        attrs["rng_val"] = rng_sampler(rng, params, i)
        group = _hit_group(rng, params, attrs)
        i += 1
        if group is None:
            continue
        groups.append(group)
        if is_boundary:
            boundary.append(group)
    assert i <= MAX_ITER, "随机组收集超过护栏上限（公式参数回归？）"
    assert len(groups) == count
    return groups, boundary

# ---------------------------------------------------------------------------
# 性质用例（PRP-1~8 / TC-PRP-01~05；每条固定 seed 随机 1000 组，PRP-2）
# ---------------------------------------------------------------------------

def test_invariant1_min_damage_ge_1(
    seeded_rng: Callable[..., Random], formula_params: DamageFormulaParams
) -> None:
    """不变量①（PRP-3 / TC-PRP-02）：1000 组命中 total_damage ≥ 1 且命中侧通道 ≥ 1。

    依据：【规则】L309「伤害 ≥1」；【1a】§3-B L298-299（最低伤害恒 ≥1，无 0 伤害）。
    含 D6 §1.3 边界组：0 攻击/0 元素攻击/0 体质（通道下限 1、防御系数 1.0 无除零）、
    乱数闭区间端点 0.9/1.1（rng 全区间抽样每 50 组强制）。守卫/格挡/魔攻随机扰动
    不破坏下界（total_damage 末段 max(1, floor) 兜底）。
    """
    rng = seeded_rng(offset=1)
    groups, boundary = _collect_groups(
        rng,
        formula_params,
        N_GROUPS,
        lck_max=50000.0,
        guard_prob=0.3,
        rng_sampler=_sample_rng_full,
        boundary_every=100,
    )
    for group in groups:
        assert group.ch_phys >= 1, f"物理通道 <1: {group}"
        assert group.ch_elem >= 1, f"元素通道 <1: {group}"
        assert group.total >= 1, f"总伤害 <1: {group}"
    # 0 攻击/0 元素/0 体质边界组（每 100 次迭代强制一组）确实产生 → 通道恰为下限 1
    assert boundary, "边界组缺失（循环结构回归？）"
    for group in boundary:
        assert group.ch_phys == 1 and group.ch_elem == 1

def test_invariant2_noncrit_closed_interval(
    seeded_rng: Callable[..., Random], formula_params: DamageFormulaParams
) -> None:
    """不变量②（PRP-4 / TC-PRP-03）：1000 组非会心 total_damage ∈ [floor(基础×0.95),
    floor(基础×1.05)] 闭区间。

    依据：【规则】L309「不会心时在 [0.95,1.05]×基础 区间」；【1a】M9 L188-193。
    非会心 = crit 判定 low 档（PRP-4 原文）；基础 = 同输入无乱数、无格挡、无防御指令的
    通道和（ch_phys + ch_elem，通道内已含 low 档倍率与防御系数）。乱数抽样域取断言带
    [0.95,1.05]（闭端点每 100 组复现；【偏离 D6】注记见文件头）。末尾追加乱数闭区间
    端点 0.9/1.1 显式组：断言真实带 [floor(基础×rng[0]), floor(基础×rng[1])]
    （【1a】§3-E L320 端点合法）。
    """
    rng = seeded_rng(offset=2)
    params = formula_params
    groups: list[GroupResult] = []
    i = 0
    while len(groups) < N_GROUPS and i < MAX_ITER:
        attrs = _draw_attrs(rng, params, lck_max=1000.0, guard_prob=0.0)
        attrs["rng_val"] = _sample_rng_band(rng, i)
        group = _hit_group(rng, params, attrs)
        i += 1
        if group is None or group.tier != "low" or group.blocked_eff:
            continue  # 过滤：未命中 / 会心（high/mid）/ 格挡生效 均不入区间断言
        groups.append(group)
    assert i <= MAX_ITER, "非会心组收集超过护栏上限（公式参数回归？）"
    assert len(groups) == N_GROUPS

    for group in groups:
        assert group.tier == "low" and not group.blocked_eff
        lo = int(group.base * BAND_LO)  # floor(基础×0.95)
        hi = int(group.base * BAND_HI)  # floor(基础×1.05)
        assert (
            lo <= group.total <= hi
        ), f"非会心 total 越出 [floor(基础×0.95), floor(基础×1.05)]: {group}"

    # 乱数闭区间端点 0.9/1.1 显式边界组（D6 §1.3 / 【1a】§3-E L320）：真实带断言
    for endpoint in (params.rng[0], params.rng[1]):
        found = None
        j = 0
        while found is None and j < MAX_ITER:
            attrs = _draw_attrs(rng, params, lck_max=1000.0, guard_prob=0.0)
            attrs["rng_val"] = endpoint
            group = _hit_group(rng, params, attrs)
            j += 1
            if group is None or group.tier != "low" or group.blocked_eff:
                continue
            found = group
        assert found is not None, f"乱数端点 {endpoint} 边界组收集失败"
        lo = int(found.base * params.rng[0])
        hi = int(found.base * params.rng[1])
        assert lo <= found.total <= hi, (
            f"乱数端点 {endpoint} 越出真实带 [floor(基础×rng[0]), floor(基础×rng[1])]: {found}"
        )

def test_invariant3_crit_rate_and_tier_bounds(
    seeded_rng: Callable[..., Random], formula_params: DamageFormulaParams
) -> None:
    """不变量③（PRP-5 / TC-PRP-04）：1000 组累计 crit_prob（cap 后）恒 ≤ 0.95；
    会心档位倍率 ∈ [1.3, 2.35]（low 1.3 ~ high+超会心 Lv3 2.35）。

    依据：【规则】L309「会心率 ≤95%」；【1a】§1.4/§1.5 L119-137。
    含幸运极端组（D6 §1.3 / §3-E L321）：幸运 0 → P=0 → 恒低级会心 1.3；幸运极高
    （1e6）→ P 截断到 cap（95%）。档位倍率带由公式参数（crit.tiers + crit_mult_up）
    导出，F-FIX 默认下恰为 [1.3, 2.35]（PRP-7：不硬编码公式参数常量）。
    """
    rng = seeded_rng(offset=3)
    params = formula_params
    cap_max = 95.0  # 契约断言带上限（D6 PRP-5/TC-PRP-04 常数：会心率 ≤95%）
    low_tier_min = params.crit.tiers.low
    high_tier_max = params.crit.tiers.high + params.crit.crit_mult_up.boost(3)
    assert low_tier_min <= high_tier_max, "档位倍率带退化（公式参数回归？）"

    for i in range(N_GROUPS):
        lck = rng.uniform(0.0, 50000.0)
        extreme_zero = False
        extreme_huge = False
        if i % 100 == 0:
            lck = 0.0  # 幸运 0 → P=0（D6 §1.3）；取非斩击类型保 P=0 无加成
            extreme_zero = True
        elif i % 100 == 50:
            lck = 1_000_000.0  # 幸运极高 → P cap 95%（D6 §1.3）
            extreme_huge = True
        attack_type = rng.choice(
            ("thrust", "blunt", "magic")
            if extreme_zero
            else ("slash", "thrust", "blunt", "magic")
        )
        slash = (
            params.type_affinity.slash_crit
            if attack_type == "slash" and params.type_affinity.enabled
            else 0.0
        )
        p_eff = crit_prob(
            lck,
            p_coef=params.crit.p_coef,
            crit_bonus=0.0,
            cap=params.crit.cap,
            slash_crit=slash,
        )
        # 累计 1000 组恒 ≤95%（cap 后），且不超出公式参数 cap（PRP-5）
        assert p_eff <= cap_max / 100.0, f"crit_prob 超 95%: lck={lck} P={p_eff}"
        assert p_eff <= params.crit.cap / 100.0, f"crit_prob 超参数 cap: P={p_eff}"
        # 档位倍率 ∈ [low, high+超会心 Lv3]（默认参数下 = [1.3, 2.35]）
        super_crit = rng.randint(0, 3)
        tier, mult = crit_roll(
            rng.random(),
            lck,
            p_coef=params.crit.p_coef,
            tiers=params.crit.tiers,
            tier_p=params.crit.tier_p,
            super_crit_level=super_crit,
            p_override=p_eff,
        )
        assert (
            low_tier_min <= mult <= high_tier_max
        ), f"档位倍率越出 [1.3, 2.35]: tier={tier} mult={mult} lck={lck}"
        # 幸运 0（无斩击加成）→ P=0 → 恒低级档；倍率 = 1.3 + 超会心加成（【1a】§3-E L321）
        if extreme_zero:
            assert p_eff == 0.0, f"幸运 0 P 应为 0: {p_eff}"
            assert tier == "low", f"幸运 0 应为恒低级会心: tier={tier} lck={lck}"
            assert mult == pytest.approx(
                params.crit.tiers.low + params.crit.crit_mult_up.boost(super_crit)
            )
        # 幸运极高 → P 恰为参数 cap（cap>0 时截断生效）
        if extreme_huge:
            assert p_eff == pytest.approx(params.crit.cap / 100.0)

def test_prp8_deterministic_regression(
    seeded_rng: Callable[..., Random], formula_params: DamageFormulaParams
) -> None:
    """PRP-8 / TC-PRP-05 确定性回归：同 seed 连续两次运行 → 输出逐位一致。

    依据：【规则】L331；D6 PRP-8（固定种子无抖动，对齐 run_all_tests --fast 抽样
    仍可复现）。经 §2.5 派生种子形 seeded_rng(offset=N) 取两个状态相同的新实例，
    跑同一性质管线 300 组，断言 (通道/档位/倍率/P/总伤害) 元组逐位一致。
    """
    sig_a = _property_signature(seeded_rng(offset=8), formula_params, count=300)
    sig_b = _property_signature(seeded_rng(offset=8), formula_params, count=300)
    assert len(sig_a) == len(sig_b) == 300
    assert sig_a == sig_b, "同 seed 两次运行输出不一致（确定性回归失败）"

def _property_signature(
    rng: Random,
    params: DamageFormulaParams,
    *,
    count: int,
) -> Tuple[GroupResult, ...]:
    """PRP-8 签名生成器：与不变量①同构的 300 组命中管线输出（随机消费形状一致）。"""
    groups, _ = _collect_groups(
        rng,
        params,
        count,
        lck_max=50000.0,
        guard_prob=0.0,
        rng_sampler=_sample_rng_full,
    )
    return tuple(groups)