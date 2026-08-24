"""M1 战斗核心 · 伤害公式模块（细化_1a 十乘区 + O1 怪物防御率【工程补白·待策划裁决】默认 1.0）。

本模块实现《细化_1a_伤害公式数值》的伤害公式纯函数层，供战斗引擎（批2
battle.py + core/effects.DamagePipeline）import。零 NoneBot import（细化_3a R1）。

设计要点：
  - **10 乘区 + 1 开放项**（细化_1a §0.3 清单）：M1 基础攻击值 / M2 攻击倍率 /
    M3 弱点倍率 / M4 会心倍率 / M5 会心频率 / M6 防御减伤 / M7 格挡减半 /
    M8 防御指令 / M9 乱数 / M10 武器类型倍率（预留不挂链）；**O1 怪物防御率【工程补白】——
    工程默认 1.0 不参与乘法**（细化_1a §1.11 L27/L32 出现但无算法、formula.json 无字段；
    细化原文「待策划裁决，实现前必须裁决」——1.0 为工程暂定默认，登记 R-09 待策划拍板，
    正式裁决后需更新）。“乘区数=10”按细化_1a §0.3。
  - **判定顺序写死**（细化_1a §0.1 / 数值层 L16）：命中→会心→格挡→双通道
    （物理/元素独立 floor 后相加）→防御率→伤害拦截链→扣血。本模块覆盖到
    “拦截链前”即 raw_damage；拦截链由调用方注入 ``pipeline``（批2 battle.py 注入
    core/effects.DamagePipeline——P1-1 收敛后由 battle 层直连 effects，不经本模块）。
  - **概率输出统一为小数（fraction）口径**【权威战斗口径】：hit/crit/block/defense
    均返回 [0,1]/-[0,1] 的小数（如 0.05 = 5%）。这与 core/player_attributes.py
    的 3b 派生属性口径（返回百分数值，如 5.0 = 5%，hit.k 默认 1）不同——
    1a 战斗数值层口径（hit.k=0.2，细化_1a §2.1 数值表）为战斗权威口径，
    本模块独立实现参数化版本，**不修改 core/player_attributes.py**。
  - **cap 型参数沿用 formula.json 百分数值**（crit.cap=95 / block.cap=40，
    细化_1a §2.1），函数内部 ÷100 转小数；**加成类参数沿用 formula.json 小数值**
    （type_affinity.slash_crit=0.05 / crit_bonus，细化_1a §2.1），与输出同单位。
    该“混合单位”忠实映射 formula.json 原始数据（§5.1 结构本身即此口径）。
  - **随机外部注入**：本层所有随机数（乱数 rng、会心判定 r、格挡判定布尔）均由
    调用方注入，保证固定种子可复现（细化_1a §4 验收约定“固定种子随机数输入”）。
  - **运行期护栏**（细化_1a §3 三级护栏：clamp 优先 / max(1) 兜底 / 负值按 0）：
    负属性输入按 0 处理；任何乘区结果不允许为负；最低伤害恒 ≥1（数值层 L26/L34）。

乘区→函数映射（细化_1a §1）：
  M1/M2/M3/M4/M6-物理  → channel_phys（参数显式传入，纯函数）
  M3/M4/M6-元素        → channel_elem
  M5 会心频率          → crit_prob / crit_roll（含 M4 倍率）
  M6 防御              → defense_factor / effective_con / pierce_pct / elem_factor
  M7 格挡              → block_rate + total_damage 内减半
  M8 防御指令 / M9 乱数 → total_damage
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

__all__ = [
    # 参数载体（formula.json 段级映射，frozen）
    "CritTiers",
    "CritMultUp",
    "HitParams",
    "CritParams",
    "BlockParams",
    "DefenseParams",
    "WeaknessParams",
    "TypeAffinityParams",
    "DerivedParams",
    "DamageFormulaParams",
    # 纯函数
    "hit_rate",
    "crit_prob",
    "crit_roll",
    "apply_derived_cap",
    "block_rate",
    "defense_factor",
    "pierce_pct",
    "effective_con",
    "elem_factor",
    "channel_phys",
    "channel_elem",
    "total_damage",
]

# 8 元素注册表（细化_1a §1.1 / 数值层 L220-221，formula.json elements 段默认值）。
DEFAULT_ELEMENTS: Mapping[str, str] = {
    "earth": "地",
    "fire": "火",
    "water": "水",
    "wind": "风",
    "thunder": "雷",
    "crystal": "晶",
    "moon": "月",
    "void": "无",
}

# O1 怪物防御率【工程补白·待策划裁决】：默认 1.0，不参与乘法（细化_1a §1.11 L27/L32 无算法；
# 细化原文「待策划裁决，实现前必须裁决，禁止自行猜测接入」——登记 R-09）。
O1_MONSTER_DEF_RATE: float = 1.0


# ---------------------------------------------------------------------------
# formula.json 段级参数载体（细化_1a §2.1 字段表默认值）
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CritTiers:
    """会心三档倍率（细化_1a §1.4 / 数值层 L191 formula.json ``crit.tiers``）。"""

    high: float = 2.2
    mid: float = 1.7
    low: float = 1.3


@dataclass(frozen=True)
class CritMultUp:
    """超会心 Lv1-3 各档加成（细化_1a §1.4 / 数值层 L193 ``crit.crit_mult_up``）。

    语义：倍率 = 基础档 + 0.05 × 超会心等级，Lv1/2/3 = +0.05/+0.10/+0.15。
    """

    lv1: float = 0.05
    lv2: float = 0.10
    lv3: float = 0.15

    def boost(self, level: int) -> float:
        """超会心 level（0 起）对应三档加法常数；level>3 取 Lv3（0.15）封顶。"""
        if level <= 0:
            return 0.0
        if level >= 3:
            return self.lv3
        return {1: self.lv1, 2: self.lv2}[level]


@dataclass(frozen=True)
class HitParams:
    """命中率参数（细化_1a §1 命中 / 数值层 L21、L185-186 ``hit`` 段）。

    - k:       K_hit，默认 1.0（2026-08-24 用户拍板统一：3b §5.2 派生口径与
               1a 战斗口径同用 K=1，消除跨文档冲突；数值层 L185「防同级挫败」
               注释的口径由 formula.json 可配覆盖）
    - cap_min/cap_max: clamp 门槛 10% / 95%（数值层 L21）
    """

    k: float = 1.0
    cap_min: float = 10.0
    cap_max: float = 95.0


@dataclass(frozen=True)
class CritParams:
    """会心参数（细化_1a §1.4/§1.5 / 数值层 L188-193 ``crit`` 段）。

    - p_coef: P = √幸运 × p_coef ÷ 100（幸运 100 → P=0.05 小数 = 5%）
    - cap:    P 封顶 95（百分数值 → 上限 0.95）
    - tiers:  三档倍率 2.2/1.7/1.3
    - tier_p: 档位阈值倍数 [1, 3]：r≤P×1 高级 / r≤P×3 中级
    - crit_mult_up: 超会心 Lv1-3 加成
    """

    p_coef: float = 0.5
    cap: float = 95.0
    tiers: CritTiers = field(default_factory=CritTiers)
    tier_p: Tuple[int, int] = (1, 3)
    crit_mult_up: CritMultUp = field(default_factory=CritMultUp)


@dataclass(frozen=True)
class BlockParams:
    """格挡参数（细化_1a §1.7 / 数值层 L195-198 ``block`` 段）。

    - k/cap:            格挡率 min(cap%, 专注/(专注+k))，k=150 / cap=40
    - magic_ignores:    魔攻击无视格挡（数值层 L25/L197）
    - halve_after_block: 格挡成功总伤害 ×0.5（数值层 L25/L198；组队多段预留）
    """

    k: float = 150.0
    cap: float = 40.0
    magic_ignores: bool = True
    halve_after_block: bool = True


@dataclass(frozen=True)
class DefenseParams:
    """防御减伤参数（细化_1a §1.6 / 数值层 L200-203 ``defense`` 段）。

    - mode:  减伤模式，默认 "ratio"（除算；框架减法被覆盖）——本模块仅实现 ratio
    - k:     除算常数 K_def=100（防御系数 = K/(有效体质+K)，数值层 L29）
    - pierce_types: 打类型内置破防 {blunt: 0.2}（数值层 L30/L203）
    """

    mode: str = "ratio"
    k: float = 100.0
    pierce_types: Mapping[str, float] = field(
        default_factory=lambda: {"blunt": 0.2}
    )


@dataclass(frozen=True)
class WeaknessParams:
    """弱点倍率（细化_1a §1.3 / 数值层 L205-208 ``weakness`` 段）。

    type_mult（类型弱点，物理通道）/ element_mult（元素弱点，元素通道）均 ×1.3。
    """

    type_mult: float = 1.3
    element_mult: float = 1.3


@dataclass(frozen=True)
class TypeAffinityParams:
    """攻击类型倾向（细化_1a §1.6/§1.5 + 数值层 L212-218 ``type_affinity`` 段）。

    - enabled:            总开关（数值层 L94）
    - blunt_pierce:       打类型内置破防 0.2
    - thrust_hit:         突击类型命中 +0.05
    - slash_crit:         斩击类型会心 +0.05
    - magic_ignore_block: 魔类型无视格挡 true（双源见细化_1a §5-③：以 block 为准引用）
    """

    enabled: bool = True
    blunt_pierce: float = 0.2
    thrust_hit: float = 0.05
    slash_crit: float = 0.05
    magic_ignore_block: bool = True


@dataclass(frozen=True)
class DerivedParams:
    """派生参数（细化_1a §1.2 / 数值层 L228-230 ``derived`` 段）。

    max_total_mult: 派生累计倍率封顶 1.5（L129/L229）；本模块不累加派生链，
    由战斗引擎对派生链求和并在此封顶后再入 ``channel_phys/elem``（细化_1a §4-T32）。
    """

    max_total_mult: float = 1.5


@dataclass(frozen=True)
class DamageFormulaParams:
    """formula.json 全段参数载体（细化_1a §2.1 字段表默认值）。

    battle.py（批2）构造一份实例后，把各段字段显式传入纯函数（本模块函数
    不接受裸 dict 参数）。
    """

    base_attack_mult: float = 1.0  # 全局攻击倍率基线 M2（数值层 L179）
    rng: Tuple[float, float] = (0.9, 1.1)  # M9 乱数闭区间（数值层 L180）
    hit: HitParams = field(default_factory=HitParams)
    crit: CritParams = field(default_factory=CritParams)
    block: BlockParams = field(default_factory=BlockParams)
    defense: DefenseParams = field(default_factory=DefenseParams)
    weakness: WeaknessParams = field(default_factory=WeaknessParams)
    type_affinity: TypeAffinityParams = field(default_factory=TypeAffinityParams)
    derived: DerivedParams = field(default_factory=DerivedParams)
    # 元素注册表（细化_1a §1.1 / 数值层 L220-221）；键固定不可枚举，引用存在校验 L258
    elements: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ELEMENTS))
    # O1 怪物防御率（细化_1a §1.11 待策划裁决；工程默认 1.0 不参与乘法（登记 R-09，正式裁决后更新））
    monster_def_rate: float = O1_MONSTER_DEF_RATE


# P1-1 修复：DamageContext dataclass 与 DamagePipeline 类型别名已删除——
# 总伤害只输出 (raw, blocked)，拦截链由 battle 层直连 core/effects.DamagePipeline
# （见 total_damage docstring，dsh M1-批1 P1-1：原 pipeline 挂钩接口不兼容即死代码）。


def apply_derived_cap(current_mult: float, *, max_total_mult: float = 1.5) -> float:
    """派生累计倍率封顶（细化_1a §1.2/M2 + T32；数值层 L129/L229：派生累计 ≤1.5×）。

    P1-7 修复：派生累计封顶原先仅定义参数（max_total_mult）无引擎消费路径——
    本纯函数由批2 连段引擎在累计倍率超限时调用（min(累计, 封顶) 后再入通道）；
    负值按 0（运行期护栏）。
    """
    return min(max(0.0, float(current_mult)), max(0.0, float(max_total_mult)))

# ---------------------------------------------------------------------------
# ⑤ 会心频率（M5）
# ---------------------------------------------------------------------------

def crit_prob(
    lck: float,
    *,
    p_coef: float = 0.5,
    crit_bonus: float = 0.0,
    cap: float = 95.0,
    slash_crit: float = 0.0,
) -> float:
    """会心判定概率（小数，[0, cap/100]）。

    依据：细化_1a §1.5 / 数值层 L23/L189-190。

    formula = min(cap/100, √幸运 × p_coef ÷ 100 + crit_bonus + slash_crit)
      - √幸运 × p_coef ÷ 100：属性驱动基础（幸运 100 → 0.05 = 5%）
      - crit_bonus：装备/技能/效果会心加成（小数；效果系统挂载，3b §5.1 同源）
      - slash_crit：斩击类型会心加成（type_affinity.slash_crit=0.05，数值层 L92/L216）
      - cap：formula.json 百分数值（默认 95 → 上限 0.95）；P 判定前统一
        min(P, cap) 含斩击加成后（细化_1a §5-⑦ 采纳）
    负数幸运按 0（细化_1a §3-C：负值运行期按 0）。
    """
    if lck < 0.0:
        lck = 0.0
    p = math.sqrt(lck) * p_coef / 100.0 + crit_bonus + slash_crit
    # cap=0 = 不限（对齐 3b §5.1 L217「cap 0 不封顶」，否则 0 会被 min 钳成 0%）
    if cap and cap > 0.0:
        p = min(p, cap / 100.0)
    return p


def crit_roll(
    r: float,
    lck: float,
    *,
    p_coef: float = 0.5,
    tiers: Optional[CritTiers] = None,
    tier_p: Tuple[int, int] = (1, 3),
    super_crit_level: int = 0,
    p_override: Optional[float] = None,  # G1：注入有效 P（类型加成+cap 判定前）；None=内部 √幸运
) -> Tuple[str, float]:
    """会心档位判定，返回 (档位 id, 倍率小数)。

    依据：细化_1a §1.4/§1.5 / 数值层 L23-24/L191-193。

    P = √幸运 × p_coef ÷ 100（小数）；判定顺序写死，先高级再中级其余低级：
      - r ≤ P × tier_p[0]（=P，默认）→ "high"（含等号，数值层 L23/L192）
      - r ≤ P × tier_p[1]（=3P，默认）→ "mid"（含等号）
      - r > 3P → "low"
    r 与 P 同单位（小数 / r∈[0,1]），由调用方注入（固定种子可复现）。
    超会心：三档均 + 0.05 × level（level 1/2/3 → +0.05/0.10/0.15，细化_1a §1.4/L193）。
    物理+元素通道共用一次本判定（数值层 L24）。
    """
    if lck < 0.0:
        lck = 0.0
    if tiers is None:
        tiers = CritTiers()
    # G1 定稿对照修复：p_override 允许注入「已算好的有效 P」（含 type_affinity.slash_crit
    # 加成 + cap 95，cap 应用在判定前——细化_1a §5-⑦/数值层 L92/L216）；缺省按内部 √幸运。
    p = p_override if p_override is not None else (math.sqrt(lck) * p_coef / 100.0)
    t1, t3 = max(1, int(tier_p[0])), max(1, int(tier_p[1]))
    boost = CritMultUp().boost(int(super_crit_level))
    if r <= p * t1:
        return ("high", tiers.high + boost)
    if r <= p * t3:
        return ("mid", tiers.mid + boost)
    return ("low", tiers.low + boost)


# ---------------------------------------------------------------------------
# ① 命中率（细化_1a §1 命中 / 数值层 L21-22/L185-186）
# ---------------------------------------------------------------------------

def hit_rate(
    focus: float,
    enemy_spd: float,
    *,
    k: float = 1.0,
    cap_min: float = 10.0,
    cap_max: float = 95.0,
) -> float:
    """命中率（小数，[cap_min/100, cap_max/100]）。

    依据：细化_1a §1 命中 / 数值层 L21-22/L185-186。

    formula = clamp(专注 / (专注 + K_hit × 对方敏捷), 10%, 95%)
      特例先于 clamp（细化_1a §3-E / 3b §5.2 L83-84）：
        - 对方敏捷 ≤ 0 → 1.0（100%），含“双方都为 0”的 0/0 兜底
        - 专注 ≤ 0（且敌敏 > 0）→ 按 0 → clamp 到 cap_min（10%）
    K_hit 默认 1.0（2026-08-24 用户拍板统一 3b/1a 口径，消除跨文档冲突；
    可经 formula.json hit.k 覆盖）。返回值小数：focus/enemy 同级 50/50 → 0.5。
    """
    if enemy_spd <= 0.0:
        return 1.0
    if focus < 0.0:
        focus = 0.0
    ratio = focus / (focus + k * enemy_spd)
    return max(cap_min / 100.0, min(cap_max / 100.0, ratio))


# ---------------------------------------------------------------------------
# ③ 格挡率（M7）
# ---------------------------------------------------------------------------

def block_rate(foc: float, *, k: float = 150.0, cap: float = 40.0) -> float:
    """格挡率（小数，[0, cap/100]）。

    依据：细化_1a §1.7 / 数值层 L25/L196。

    formula = min(cap/100, 专注 / (专注 + k))；k=150 / cap=40 → 上限 0.40。
    专注 → ∞ 时逼近 40% 封顶不超（细化_1a §3-E）。
    """
    if foc < 0.0:
        foc = 0.0
    return min(cap / 100.0, foc / (foc + k))


# ---------------------------------------------------------------------------
# ⑥ 防御减伤（M6）
# ---------------------------------------------------------------------------

def defense_factor(eff_con: float, *, k: float = 100.0) -> float:
    """防御系数（小数，(0, 1]）。

    依据：细化_1a §1.6/§3-A / 数值层 L29。

    formula = K / (有效体质 + K)，K=100；有效体质 0 → 1.0（不减免不增伤、无除零），
    恒 ∈ (0,1]。负数按 0（细化_1a §3-C）。mode 仅实现 "ratio"（数值层 L201，
    框架减法被覆盖，不在本模块范围内）。
    """
    if eff_con < 0.0:
        eff_con = 0.0
    return k / (eff_con + k)


def pierce_pct(attack_type: Optional[str], *, blunt_pierce: float = 0.2) -> float:
    """攻击类型内置破防率（小数）。

    依据：细化_1a §1.6/§4-T17 / 数值层 L30/L90/L203。

    打类型（blunt）→ blunt_pierce（默认 0.2）；其余类型 → 0.0。
    调用方按 type_affinity.enabled 门控（关闭时传 blunt_pierce=0，细化_1a §3 type_affinity）。
    """
    if attack_type == "blunt":
        return blunt_pierce
    return 0.0


def effective_con(con: float, pierce: float) -> float:
    """有效体质 = 体质 × (1 − 破防%)（数值层 L30）。

    依据：细化_1a §1.6 / 数值层 L30。pierce 为该攻击的总破防率（打类型内置 +
    破防类效果，数值层 L324；effects_link.pierce_cap=0.6 由效果层约束）。
    """
    if con < 0.0:
        con = 0.0
    return con * (1.0 - min(1.0, max(0.0, pierce)))


def elem_factor(elem_res: float, *, k: float = 100.0) -> float:
    """元素减伤系数（小数，(0, 1]）。

    依据：细化_1a §1.6/§4-T18 / 数值层 L33。

    formula = K / (元素抗性 + K)，K=100；抗性 0 → 1.0，抗性 100 → 0.5。
    """
    if elem_res < 0.0:
        elem_res = 0.0
    return k / (elem_res + k)


# ---------------------------------------------------------------------------
# ④⑤ 双通道（M1/M2/M3/M4/M6 + O1 怪物防御率）
# ---------------------------------------------------------------------------

def channel_phys(
    attack_value: float,
    skill_mult: float,
    weakness_mult: float,
    crit_mult: float,
    defense_factor: float,
    monster_def_rate: float = O1_MONSTER_DEF_RATE,
) -> int:
    """物理通道 = max(1, floor(攻击值 × 技能倍率 × 类型克制 × 会心倍率 × 防御系数 × 怪物防御率))。

    依据：细化_1a §0.2/§1.1-1.4/§1.6/§1.11；数值层 L26-30。

    - attack_value：M1 首因子（斩/打/突取力量、魔取智力，数值层 L28）
    - skill_mult：M2 技能倍率（普攻 1.0；派生累计 ≤ derived.max_total_mult 由引擎封顶，L129）
    - weakness_mult：M3 类型弱点（无弱点 = 1.0，怪物配置制，L102）
    - crit_mult：M4 会心倍率（crit_roll 输出；双通道共用一次判定，L24）
    - defense_factor：M6 防御系数（defense_factor() 输出）
    - monster_def_rate：O1 怪物防御率（【工程补白·待策划裁决】默认 1.0 不参与乘法，§1.11）
    通道末 floor 一次（数值层 L38，deep_floor=false）；下限 1，无 0 伤害（数值层 L26）。
    """
    if attack_value < 0.0:
        attack_value = 0.0
    raw = (
        attack_value
        * max(0.0, skill_mult)
        * max(0.0, weakness_mult)
        * max(0.0, crit_mult)
        * max(0.0, defense_factor)
        * max(0.0, monster_def_rate)
    )
    return max(1, math.floor(raw))


def channel_elem(
    elem_attack: float,
    elem_skill_mult: float,
    elem_weakness_mult: float,
    crit_mult: float,
    elem_factor: float,
    monster_def_rate: float = O1_MONSTER_DEF_RATE,
) -> int:
    """元素通道 = max(1, floor(装备元素攻击 × 技能元素倍率 × 元素弱点 × 会心倍率 × 元素减伤系数 × 怪物防御率))。

    依据：细化_1a §0.2/§1.1/§1.3/§1.4/§1.6/§1.11；数值层 L31-33。

    - elem_attack：M1 元素首因子（装备元素攻击 flat——定稿 L31 元素通道首因子；无元素 = 0）
    - elem_skill_mult：M2 技能元素倍率
    - elem_weakness_mult：M3 元素弱点（怪物 8 元素弱点表，L103）
    - crit_mult：M4 会心倍率（与物理通道共用同一次判定，L24）
    - elem_factor：M6 元素减伤系数（elem_factor() 输出，L33）
    通道末 floor 一次（L38）；下限 1（L31）。
    """
    if elem_attack < 0.0:
        elem_attack = 0.0
    raw = (
        elem_attack
        * max(0.0, elem_skill_mult)
        * max(0.0, elem_weakness_mult)
        * max(0.0, crit_mult)
        * max(0.0, elem_factor)
        * max(0.0, monster_def_rate)
    )
    return max(1, math.floor(raw))


# ---------------------------------------------------------------------------
# ⑥ 总伤害（M7 格挡减半 / M8 防御指令 / M9 乱数）+ 拦截链接线
# ---------------------------------------------------------------------------

def total_damage(
    ch_phys: int,
    ch_elem: int,
    *,
    rng: float = 1.0,
    blocked: bool = False,
    magic: bool = False,
    guard: bool = False,
    magic_ignores_block: bool = True,
    halve_after_block: bool = True,
) -> Tuple[int, bool]:
    """总伤害（拦截链前）求值，返回 (raw_damage, blocked)。

    依据：细化_1a §0.2/§1.7-1.9；数值层 L34-35。

    计算顺序（写死，细化_1a §0.1）：
       双通道和 = ch_phys + ch_elem（各自已独立 floor，数值层 L16/L38）
       → 格挡减半：blocked 且非（魔攻击且 magic_ignores_block，数值层 L25/L197）时
                  若 halve_after_block 则 ×0.5（L25/L198）
       → 防御指令 ×0.5（guard 生效，L34）
       → 乱数 ×rng（M9 闭区间 [0.9,1.1]，一次判定双通道共用，L35）
       → max(1, floor(...))（L34，最低伤害恒 ≥1）

    拦截链接线（P1-1 收敛）：本函数只算「拦截链前」总伤害（纯公式层）。
    伤害拦截链 8 阶段由战斗层直连 core/effects.DamagePipeline（battle.resolve_damage
    拿 raw 后构造 effects.DamageCtx → damage_pipeline），不在此函数注入——
    原 pipeline 参数与 effects.DamageCtx 接口不兼容（类型/签名/返回三者均异），
    属死代码，已删除（dsh M1-批1 审查 P1-1）。

    返回的 blocked 为“格挡实际生效”标记（魔攻击被无视时为 False，对齐
    数值层 §8.1 记录字段 blocked:false 语义）。
    """
    blocked_eff = bool(blocked) and not (bool(magic) and bool(magic_ignores_block))
    value = float(max(0, int(ch_phys)) + max(0, int(ch_elem)))
    if blocked_eff and halve_after_block:
        value *= 0.5
    if guard:
        value *= 0.5
    value *= rng
    raw = max(1, math.floor(value))
    return raw, blocked_eff
