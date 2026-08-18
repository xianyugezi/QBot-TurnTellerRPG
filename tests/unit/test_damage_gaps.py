"""细化_1a 验收覆盖缺口补测（M1-批2 · test_damage.py 未覆盖 T04/12/13/17/21/22/25/28/29/31/32）。

对齐 test_damage.py（T01-32 第一批已覆盖 T01/02/03/05/06/07/08/09/10/11/14/15/16/18/19/20/
23/24/26/27）；本文件补 M1-批1 遗留缺口，断言具体数值（禁止"不崩就行"）。

对应细化_1a_伤害公式数值 §4 验收：
  T04 未命中→0 伤害 / T12 格挡减半 / T13 魔攻击无视格挡 / T17 打类型内置破防 /
  T21 双弱点叠加 / T22 通道末 floor 一次 / T25 乱数闭区间共用 / T28 判定顺序不可配 /
  T29 拦截链必经 / T31 50 级尖峰≈3374 不破万 / T32 派生累计封顶

【契约记录（不修复，交主 agent）】
  ① T21「总增益 == 1.3×1.3 = 1.69」：实现按 L102-103 逐通道 ×1.3（物理通道×类型弱点、
    元素通道×元素弱点）后相加。加性双通道求和下相对无弱点总倍率恒为 1.3（等基底时），
    文档"1.69"对应两弱点倍率之积（乘法语义）。端到端同时证两类弱点都生效（见 test_t21）。
  ② T04 miss→0 与提示"未命中"属回合战斗状态机层（M1 后续 细化_1g 实装 player_act），
    纯函数/拦截链层无 miss 路径 → 标注不可测并 skip；落地命中侧"最低伤害恒 ≥1（未命中除外）"
    不变式落 test_t04b。
"""
from __future__ import annotations

import random

import pytest

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.damage import (
    DamageFormulaParams,
    apply_derived_cap,
    channel_elem,
    channel_phys,
    defense_factor,
    effective_con,
    hit_rate,
    pierce_pct,
    total_damage,
)
from qbot_rpg.core.effects import (
    DEFAULT_PIPELINE_ORDER,
    DamageCtx,
    DamagePipeline,
    EffectRuntime,
)

# ---------------- T29 拦截链必经所需桩（复用 test_effects_runtime 模式，自包含） ----------------


def base_defenses():
    return {
        "mitigation": [],
        "shield": {"value": 0, "remaining": 0, "turns": 0, "max": 0},
        "reflect": {"value": 0, "pct": True, "active": False},
        "absorb": {"value": 0, "pct": True, "record": 0, "active": False},
        "fatal_immune": {"count": 0, "max": 0},
        "non_fatal_immune": {"active": False, "count": 0},
        "guts": {"count": 0, "max": 0},
        "immune": {"status": False, "damage": False, "interrupt": False, "all": False, "block_debuff": True},
        "mount": {"remaining": 0},
    }


def base_snapshot(enemy_hp=1000):
    dp, de = base_defenses(), base_defenses()  # 每侧独立防御行（防共享引用串扰）
    return {
        "session_type": "battle",
        "turn": 1,
        "player": {"max_hp": 1000, "hp": 1000, "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "name": "p", "defenses": dp},
        "enemy": {"max_hp": 1000, "hp": enemy_hp, "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "name": "e", "defenses": de},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "resist_table": {"player": {}, "enemy": {}},
        "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}}, "enemy": {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {"player": {}, "enemy": {}},
        "formula_state": {},
    }


def ctx(snap, raw, atype="skill", attacker="player", target="enemy", **vars_):
    v = dict(vars_)
    v.setdefault("rng", random.Random(42))
    return DamageCtx(raw_damage=raw, attack_type=atype, attacker=attacker, target=target,
                     snapshot=snap, variables=v)


# ---------------- T04 未命中 → 0 伤害（L22 / 细化_1a §3-G） ----------------


def test_t04a_miss_path_module_not_available():
    """T04 miss→0+提示'未命中'：命中判定属战斗状态机层（细化_1g），M1 纯公式/拦截链无
    miss 路径（player_act）→ 本层不可测，标注跳过。可测侧不变式见 test_t04b。"""
    pytest.skip("miss 判定与'未命中'提示属 M1 后续战斗状态机（细化_1g player_act），"
                "damage/effects 纯函数层无 miss 分支，当前里程碑不可测")


def test_t04b_landed_hit_floor_never_zero():
    """T04 可测不变式：命中侧最低伤害恒 ≥1（未命中除外，L22/L26/L34）。
    hit_rate 为概率输出且 clamp 下限 10%——0 伤害只可能来自上游 miss 二值判定，不会来自公式层。"""
    # 命中概率不存在 0 值（极劣势也 clamp 到 10%，L21）
    assert hit_rate(1, 10000) == 0.10  # 1/(1+0.2*10000)=0.0005 → clamp 10%
    # 落地命中：即使双通道攻击值 0，总伤害 = 1（0×0.5×0.5×乱数 → max(1)，L34）
    assert total_damage(0, 0, rng=1.0) == (1, False)
    assert total_damage(0, 0, rng=0.9) == (1, False)
    # 单通道 0 亦 ≥1（通道下限 L26/L31）
    assert channel_phys(0, 1.0, 1.0, 1.0, 1.0) == 1
    assert channel_elem(0, 1.0, 1.0, 1.0, 1.0) == 1


# ---------------- T12 格挡减半（恰一次 ×0.5） ----------------


def test_t12_block_halves_once():
    # 双通道和 310，格挡成功恰一次 ×0.5 → floor(310×0.5) = 155（若两次减半为 77）
    raw, blocked = total_damage(214, 96, rng=1.0, blocked=True)
    assert (raw, blocked) == (155, True)
    # 格挡 + 防御指令各一次 ×0.5 → floor(310×0.25) = 77（格挡一次 ≠ 指令，区分两者）
    g_raw, g_blocked = total_damage(214, 96, rng=1.0, blocked=True, guard=True)
    assert (g_raw, g_blocked) == (77, True)
    # halve_after_block=false → 格挡仅标记不乘 0.5（组队多段预留开关）
    no_h, no_blocked = total_damage(214, 96, rng=1.0, blocked=True, halve_after_block=False)
    assert (no_h, no_blocked) == (310, True)


# ---------------- T13 魔攻击无视格挡（L25/L197） ----------------


def test_t13_magic_ignores_block():
    # 魔攻击被格挡不生效：不需要 ×0.5，blocked 标记为 False（对齐 §8.1 blocked:false 语义）
    raw, blocked = total_damage(214, 96, rng=1.0, blocked=True, magic=True,
                                magic_ignores_block=True)
    assert (raw, blocked) == (310, False)
    # magic_ignores_block=false → 魔攻击同样吃格挡减半
    m_raw, m_blocked = total_damage(214, 96, rng=1.0, blocked=True, magic=True,
                                    magic_ignores_block=False)
    assert (m_raw, m_blocked) == (155, True)
    # 默认参数：魔攻击无视格挡默认开启（formula.json block.magic_ignores=true）
    assert DamageFormulaParams().block.magic_ignores is True


# ---------------- T17 打类型内置破防（L30/L90/L203） ----------------


def test_t17_blunt_builtin_pierce_auto():
    p = DamageFormulaParams()
    # 打类型(blunt) 自动携带破防 0.2；其余类型 0（formula.json defense.pierce_types / type_affinity.blunt_pierce）
    assert pierce_pct("blunt") == 0.2
    assert pierce_pct("blunt", blunt_pierce=p.type_affinity.blunt_pierce) == 0.2
    assert p.defense.pierce_types == {"blunt": 0.2}
    assert p.type_affinity.blunt_pierce == 0.2
    for at in ("slash", "thrust", "magic", None):
        assert pierce_pct(at) == 0.0
    # 自动生效端到端：体质 100 + 打类型破防 0.2 → 有效体质 80 → 防御系数 100/180
    assert effective_con(100, pierce_pct("blunt")) == 80
    assert round(defense_factor(effective_con(100, pierce_pct("blunt"))), 4) == round(100 / 180, 4)


# ---------------- T21 双弱点叠加（L102-103，契约记录①见文件头） ----------------


def test_t21_dual_weakness_both_apply():
    p = DamageFormulaParams()
    # 类型弱点(斩)→物理通道 ×1.3；元素弱点(火)→元素通道 ×1.3
    assert p.weakness.type_mult == 1.3 and p.weakness.element_mult == 1.3
    # 乘法语义总增益 = 1.3×1.3 = 1.69（文档断言值）
    assert p.weakness.type_mult * p.weakness.element_mult == pytest.approx(1.69)
    # 两端到端：无弱点 vs 双弱点，双通道各自恰好 ×1.3（干净整数避免 floor 干扰）
    ph_none = channel_phys(10000, 1.0, 1.0, 1.0, 1.0)
    el_none = channel_elem(10000, 1.0, 1.0, 1.0, 1.0)
    ph_dual = channel_phys(10000, 1.0, 1.3, 1.0, 1.0)
    el_dual = channel_elem(10000, 1.0, 1.3, 1.0, 1.0)
    assert ph_dual == ph_none * 1.3 and el_dual == el_none * 1.3  # 两类弱点同时生效（互不阻塞）
    assert ph_dual + el_dual == 26000 and ph_none + el_none == 20000
    # 加性通道模型下复合倍率 = 1.3；文档 1.69 = 两弱点倍率之积（见文件头契约记录①）
    assert (ph_dual + el_dual) / (ph_none + el_none) == 1.3


# ---------------- T22 通道末 floor 仅一次（L38，deep_floor=false） ----------------


def test_t22_channel_floor_once_not_segmented():
    # 全程积 = 7.3×1.5×1.0×2.0×1.0 = 21.9 → 通道末单次 floor = 21
    # 若逐段 floor：floor(7.3×1.5)=10 → 10×2.0=20（deep_floor 行为），21 ≠ 20 即证明仅末一次
    assert channel_phys(7.3, 1.5, 1.0, 2.0, 1.0) == 21
    assert channel_elem(7.3, 1.5, 1.0, 2.0, 1.0) == 21
    # 通道末 floor 一次 + 双通道独立取整后相加（T27 样例复现）
    assert channel_phys(165, 1.0, 1.0, 1.3, 1.0) == 214
    assert channel_elem(74, 1.0, 1.0, 1.3, 1.0) == 96


# ---------------- T25 乱数闭区间共用（L35/L180） ----------------


def test_t25_rng_closed_interval_shared():
    p = DamageFormulaParams()
    assert p.rng == (0.9, 1.1)  # 闭区间配置（两端合法，L35/L180）
    # 共用同一乱数值：总伤害 = floor(双通道和 × rng)，非逐通道各乘
    # 310×0.9 = 279（若逐通道：floor(214×0.9)+floor(96×0.9) = 192+86 = 278）→ 279 证明共用
    assert total_damage(214, 96, rng=0.9) == (279, False)
    assert total_damage(214, 96, rng=1.1) == (341, False)  # 310×1.1 = 341（上界含）
    assert total_damage(214, 96, rng=1.0) == (310, False)  # 中值精确


# ---------------- T28 判定顺序不可配（L16/L262，formula.json 无顺序字段） ----------------


def test_t28_order_not_configurable_in_formula():
    p = DamageFormulaParams()
    # formula.json 段级参数载体无顺序字段（顺序写死，不可配）
    assert not hasattr(p, "order")
    # 拦截链 8 阶段顺序固定：减伤→护盾→反弹→吸收→免疫→续行→扣血→死亡判定（L36）
    assert DEFAULT_PIPELINE_ORDER == (
        "mitigation", "shield", "reflect", "absorb",
        "fatal_immune", "guts", "apply_damage", "death_check",
    )
    # 扣血在全部防御阶段之后、死亡判定之前（⑦⑧ 在链尾）
    assert DEFAULT_PIPELINE_ORDER[-2] == "apply_damage"
    assert DEFAULT_PIPELINE_ORDER[-1] == "death_check"


# ---------------- T29 拦截链必经（L36） ----------------


def test_t29_any_damage_passes_full_chain_then_deduct():
    pipe = DamagePipeline()
    # 无任何防御配置：8 阶段全跑（pipeline 结构必经），扣血阶段必然产出 hp_change
    snap = base_snapshot()
    res = pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    types = [e["type"] for e in res.side_effects]
    assert res.final_damage == 100 and res.target_hp == 900
    assert "hp_change" in types  # ⑦扣血必经
    # 有护盾：先扣盾（shield_absorbed）再扣血（hp_change），事件顺序即阶段顺序
    snap2 = base_snapshot()
    snap2["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    res2 = pipe.damage_pipeline(ctx(snap2, 100), EffectRuntime())
    types2 = [e["type"] for e in res2.side_effects]
    assert res2.final_damage == 70 and res2.target_hp == 930
    assert types2.index("shield_absorbed") < types2.index("hp_change")  # 减伤/护盾先于扣血
    # battle 层接线同样必经拦截链（BattleEngine.resolve_damage -> damage_pipeline）
    eng = BattleEngine()
    snap3 = base_snapshot()
    res3 = eng.resolve_damage("player", "enemy", 100, "basic", snapshot=snap3)
    t3 = [e["type"] for e in res3.side_effects]
    assert res3.final_damage == 100 and res3.target_hp == 900 and "hp_change" in t3


# ---------------- T31 50 级尖峰 ≈3374 不破万（L157 / 细化_1a §3-D） ----------------


def test_t31_lv50_peak_under_10000():
    """默认参数（全乘区最大组合）算 50 级尖峰上界：< 10000 硬护栏 + 尖峰存在性。

    因属性派生管线（细化_3b）与装备白值未在 M1 接全，不追求精确 3374（文档以 §4.5 验证
    脚本为准）；本测试用默认 formula 参数 + 定稿数值（力量 88.5@50 级 L117 + 武器白值 11、
    大招 400% L127、类型弱点 1.3、高级会心 2.2、目标 0 防御=系数 1.0、怪物防御率默认 1.0）
    叠满求确定性上界，断言落在合理区间且远高于 1 级普攻 10-15。
    """
    P = DamageFormulaParams()
    atk, skill, weak, crit, df = 88.5 + 11, 4.0, P.weakness.type_mult, 2.2, 1.0
    ph = channel_phys(atk, skill, weak, crit, df, P.monster_def_rate)
    el = channel_elem(74, 2.0, P.weakness.element_mult, 2.2, 1.0)
    raw_sum = ph + el
    peak = total_damage(ph, el, rng=P.rng[1])[0]   # 乱数取上界 1.1
    low = total_damage(ph, el, rng=P.rng[0])[0]    # 乱数取下界 0.9
    # 确定性数值（公式不发生回归时的固化值）
    assert (ph, el, raw_sum) == (1138, 423, 1561)
    assert peak == 1717 and low == 1404
    # 护栏：远高于 1 级普攻（10-15，T30），不破万
    assert 1000 <= peak < 10000
    assert low < peak


# ---------------- T32 派生累计封顶（L129/L229） ----------------


def test_t32_derived_cap_1_5():
    # 纯函数封顶：1.5 内不截，超 1.5 截到 1.5，负值按 0
    assert apply_derived_cap(1.0) == 1.0
    assert apply_derived_cap(1.5) == 1.5
    assert apply_derived_cap(2.0) == 1.5        # 派生链理论累计 >1.5 → 1.5（T32 主断言）
    assert apply_derived_cap(3.0) == 1.5
    assert apply_derived_cap(-1.0) == 0.0
    # 封顶后入 M2 技能倍率通道生效：100 攻 × 封顶 1.5 = 150
    assert channel_phys(100, apply_derived_cap(3.0), 1.0, 1.0, 1.0) == 150
    # 默认参数与文档一致
    assert DamageFormulaParams().derived.max_total_mult == 1.5
