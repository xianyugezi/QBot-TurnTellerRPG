"""玩家属性三层计算管线（细化_3b_玩家属性三层 / 细化_3a_架构分层契约）。

职责（对齐细化_3b §2 计算管线写死五步 + §5 派生属性）：
  1. ``calc_final_attr``             —— 单属性五步管线（白值→基础合计→加成后→临时→最终，出口唯一取整）
  2. ``calc_all_final_attributes``   —— 对 ``PlayerAttributes``（细化_3b §4.4 运行时键空间）逐属性跑管线
  3. 派生属性（只读、不回写属性层，ADR-03）。
     - 会心率 crit_rate（§5.1，公式 L41-45）
     - 会心三档 crit_roll（§5.1，公式 L49-63，P = √最终幸运÷2）
     - 命中率 hit_rate（§5.2，公式 L81-85）
     - 格挡率 block_rate（§5.3，公式 L90-92）
     - 物理/魔法减伤 phys_reduce / mag_reduce（§5.4，L20/L32、L21/L31）
     - 元素减伤率 elem_reduce（§5.4，L126-127）
  4. 条件加成依赖图环检测（§3.2 校验器 / TC-05：A→B→A 或 X→X 自环 → 红色拦截）。

关键约束（写死，任何配置不得破坏）：
  - 百分比只乘一次：加成层 pct 的乘数 = 基础合计（白值+flat）；临时层 pct 的乘数 = 加成后属性
    （§2.1 伪代码 step2/step3，L147/L149）。
  - 条件加成只按【基础合计】触发，产出在管线最后一步以纯加法进入最终属性，
    永不进入任何乘算基准（§3.1 三重锁，L146/L148/L150）。
  - 取整时机唯一：管线内部保留浮点，仅出口 floor（ADR-04，TC-01/TC-17）。
  - resource 型（hp/mp）默认不吃百分比（ADR-02 / TC-18），``resource_pct``=True 可配开启。

本文件属 core 层：零 NoneBot import（3a R1）；类型标注完整（3a §3.1）；
领域类型 PlayerAttributes 唯一落点 data/（3a D-03），此处仅 import 不重复定义。
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set

from qbot_rpg.data.player import PlayerAttributes
from qbot_rpg.data.types import StatKey as AttrID  # stats.json 顶层键 = 属性 ID（细化_3b §4.1）

# 2026-08-24 M0 复查收敛：派生属性的唯一参数化实现在 core/damage（1a 战斗口径，
# 常数经 formula.json 可配），本文件派生函数 = 3b 语义薄封装（% 对外口径），
# 全部委托 damage 版，消除「同名异构双套实现」。
from qbot_rpg.core.damage import (
    block_rate as damage_block_rate,
    crit_prob as damage_crit_prob,
    crit_roll as damage_crit_roll,
    defense_factor as damage_defense_factor,
    elem_factor as damage_elem_factor,
    hit_rate as damage_hit_rate,
)

__all__ = [
    "ConditionalRule",
    "ConditionalRuleCycleError",
    "validate_conditional_rules",
    "calc_final_attr",
    "calc_all_final_attributes",
    "crit_rate",
    "crit_roll",
    "hit_rate",
    "block_rate",
    "phys_reduce",
    "mag_reduce",
    "elem_reduce",
]

# resource 型预置键（细化_3b §4.2：hp/mp type=resource；ADR-02 默认不吃百分比）。
_DEFAULT_RESOURCE_ATTRS: Set[str] = {"hp", "mp"}
# 九预置 combat 键（细化_3b §4.2 / L198-206）。
_DEFAULT_COMBAT_ATTRS: Set[str] = {"str", "int", "con", "spr", "foc", "agi", "lck"}


class ConditionalRuleCycleError(ValueError):
    """条件加成依赖环（细化_3b §3.2 / TC-05）：source/target 依赖图存在环（含自环 X→X）。

    该异常表示配置非法 — 由 loader/validator 捕获翻译为人话（3a R4 领域异常语义），
    该内容包红色拦截拒绝加载，不进入结算。
    """


@dataclass(frozen=True)
class ConditionalRule:
    """条件加成规则（细化_3b §3.2 字段级 schema）。

    - source:    触发属性 X —— 基准取该属性的【基础合计】（白值+加成 flat，L148）
    - target:    产出属性 Y —— flat 加算进最终属性（L150 末项）
    - per_point: 每点 X 产出 Y 的量
    - rule_id:   规则唯一 ID（注册表约束，L220；可选）
    """

    source: str
    target: str
    per_point: float
    rule_id: Optional[str] = None


def validate_conditional_rules(
    rules: Sequence[ConditionalRule],
) -> None:
    """条件加成依赖图环检测（细化_3b §3.2 / TC-05）。

    构建 source → target 有向图，DFS 三色找环；命中 any 环（A→B→A，或 X→X 自环）
    抛 :class:`ConditionalRuleCycleError`（红色拦截）。无环则正常返回。

    注意：规则 target 不作为其他规则的 source 时天然无环（链式 str→int、int→con 合法，
    TC-10 各按自身基础合计触发、互不引用对方产出）。
    """
    graph: Dict[str, List[str]] = {}
    for rule in rules:
        if not isinstance(rule.source, str) or not isinstance(rule.target, str):
            raise TypeError(f"条件加成规则 source/target 必须为属性 ID 字符串: {rule!r}")
        graph.setdefault(rule.source, []).append(rule.target)

    # 三色标记：0=未访问(WHITE) 1=在栈(GRAY) 2=已结束(BLACK)
    WHITE, GRAY, BLACK = 0, 1, 2
    color: Dict[str, int] = {}
    path: List[str] = []

    def _dfs(node: str) -> None:
        """DFS 遇 GRAY（当前路径上）即命中环，抛 ConditionalRuleCycleError。"""
        color[node] = GRAY
        path.append(node)
        for nxt in graph.get(node, ()):
            c = color.get(nxt, WHITE)
            if c == GRAY:  # 命中环：nxt 已在当前 DFS 栈中
                idx = path.index(nxt)
                cycle: List[str] = path[idx:] + [nxt]
                raise ConditionalRuleCycleError(
                    "条件加成依赖环 → 红色拦截：" + "->".join(cycle)
                    + "（细化_3b TC-05 / §3.2；每点 X→Y 必须无环，防无限叠乘）"
                )
            if c == WHITE:
                _dfs(nxt)
        path.pop()
        color[node] = BLACK

    for node in graph:
        if color.get(node, WHITE) == WHITE:
            _dfs(node)


def _pipestep(
    white: float,
    flat_bonus: float,
    pct_bonus: float,
    temp_pct: float,
    temp_flat: float,
    cond: float,
    apply_pct: bool,
) -> float:
    """共享五步管线（细化_3b §2.1 伪代码；调用方保证 white 已算好）。

    - ① 基础合计 base_total = white + flat_bonus            （L146）
    - ② 加成后属性 boosted   = base_total × (1 + pct/100)    （L147，pct 只乘一次）
    - ④ 战斗临时 temp_term   = boosted × (1 + temp_pct/100)  （L149，基于加成后属性）
    - ③ 最终属性             = temp_term + cond + temp_flat   （L150 + ADR-01）
    返回浮点（未取整）；取整由出口唯一执行（ADR-04）。
    apply_pct=False 表示 resource 型默认不吃百分比（ADR-02）——此时跳过两步 pct 乘算。
    """
    base_total = white + flat_bonus
    if apply_pct:
        boosted = base_total * (1.0 + pct_bonus / 100.0)
        temp_term = boosted * (1.0 + temp_pct / 100.0)
    else:
        boosted = base_total
        temp_term = base_total
    return temp_term + cond + temp_flat


def calc_final_attr(
    attr_id: str,
    base: float,
    growth: float,
    level: int,
    free_points: float,
    flat_bonus: float,
    pct_bonus: float,
    temp_flat: float,
    temp_pct: float,
    cond_rule: Optional[Callable[[float], float]] = None,
    pct_enabled: bool = True,
) -> int:
    """单属性三层管线（细化_3b §2.1 五步伪代码），返回 floor 后的最终属性整数。

    参数（与 §2.1 伪代码一一对应）：
      - base / growth / level / free_points：白值层① = base + growth×(lv-1) + 自由加点（L136/L168）
      - flat_bonus：② 加成层数值（装备 L111 + 战斗外药剂 L156 + 元素攻击力 L112）
      - pct_bonus：② 加成层百分比，单位 %（10 = +10%）（L147）
      - temp_pct：④ 临时层百分比，单位 %（战斗 buff / 战斗内药剂，L149）
      - temp_flat：③ 临时层 flat（ADR-01 扩展，L139 战斗内固定值语义）
      - cond_rule：③ 条件加成函数——入参为【基础合计】（白值+flat），返回产出 flat（L148/L150）
      - pct_enabled：False 时百分比两步整体跳过（resource 型默认，ADR-02/TC-18）

    约束验证点：
      - 百分比只乘一次：pct_bonus 与 temp_pct 各只作用一次，不递归（§2.1 / TC-02 / TC-08）
      - 条件加成只按基础合计触发，产出不进任何乘算（§3.1 / TC-04 / TC-09）
      - 仅出口 floor 一次（ADR-04）
    """
    white = base + growth * (level - 1) + free_points
    if base < 0 or growth < 0 or free_points < 0:
        # 3b §4.2/TC-17：负数 → 黄提示 + 运行期按 0 兜底（不把负值代入白值放大）
        if base < 0:
            base = 0.0
        if growth < 0:
            growth = 0.0
        if free_points < 0:
            free_points = 0.0
        white = base + growth * (level - 1) + free_points
    base_total = white + flat_bonus
    cond = cond_rule(base_total) if cond_rule is not None else 0.0
    raw = _pipestep(
        white=white,
        flat_bonus=flat_bonus,
        pct_bonus=pct_bonus,
        temp_pct=temp_pct,
        temp_flat=temp_flat,
        cond=cond,
        apply_pct=pct_enabled,
    )
    return int(math.floor(raw))


def calc_all_final_attributes(
    attributes: PlayerAttributes,
    conditional_rules: Sequence[ConditionalRule] = (),
    resource_pct: bool = False,
    attr_types: Optional[Mapping[str, str]] = None,
) -> Dict[str, int]:
    """对 ``PlayerAttributes``（细化_3b §4.4 三子层键空间）逐属性跑管线，返回 attr_id → int。

    - 覆盖集合 = PlayerAttributes 各层 dict 键的并集（base/flat/pct/temp/cond）。
    - 条件加成：本函数按 ``conditional_rules`` 计算——每条规则按其 source 的
      【基础合计】（白值+flat）触发，产出 = per_point × source 基础合计，flat 加进
      target 的最终属性（§3.1 / TC-09 / TC-10）；不提供规则时退化为 attributes.cond
      已存产出（快照恢复场景，§4.4 cond 入战斗快照）。
    - 依赖图环检测先行：任何环 → ``ConditionalRuleCycleError``（TC-05）。
    - ``resource_pct``：content 包配置（ADR-02）；``attr_types``：attr_id → 
      "resource"|"combat"，缺省按九预置（hp/mp=resource，其余 combat，§4.2）。
    - 派生属性不在本函数（只读，见 crit_rate 等；ADR-03）。
    """
    if conditional_rules:
        validate_conditional_rules(conditional_rules)

    if attr_types is None:
        attr_types = {k: "resource" for k in _DEFAULT_RESOURCE_ATTRS} | {
            k: "combat" for k in _DEFAULT_COMBAT_ATTRS
        }
    base_map: Mapping[str, float] = attributes.base
    flat_map: Mapping[str, float] = attributes.flat_bonus()
    pct_map: Mapping[str, float] = attributes.pct_bonus()
    temp_pct_map: Mapping[str, float] = attributes.temp_pct()
    temp_flat_map: Mapping[str, float] = attributes.temp_flat()

    # 全部涉事属性键（并集）
    keys: List[str] = sorted(
        set(base_map) | set(flat_map) | set(pct_map)
        | set(temp_pct_map) | set(temp_flat_map) | set(attributes.cond)
    )

    # 各属性的基础合计（条件触发基准：白值 + 加成 flat，L146/L148）
    base_total_of: Dict[str, float] = {
        k: base_map.get(k, 0.0) + flat_map.get(k, 0.0) for k in keys
    }

    # 条件加成产出：per_point × source 基础合计（§3.1；不进入任何乘算基准）
    if conditional_rules:
        cond_out: Dict[str, float] = {}
        for rule in conditional_rules:
            contrib = rule.per_point * base_total_of.get(rule.source, 0.0)
            cond_out[rule.target] = cond_out.get(rule.target, 0.0) + contrib
    else:
        cond_out = dict(attributes.cond)

    result: Dict[str, int] = {}
    for k in keys:
        attr_type = attr_types.get(k, "combat")
        apply_pct = (attr_type != "resource") or resource_pct
        white = base_map.get(k, 0.0)          # base 即工厂已算好的白值（§4.4：base=base+growth×lv+加点）
        raw = _pipestep(
            white=white,
            flat_bonus=flat_map.get(k, 0.0),
            pct_bonus=pct_map.get(k, 0.0),
            temp_pct=temp_pct_map.get(k, 0.0),
            temp_flat=temp_flat_map.get(k, 0.0),
            cond=cond_out.get(k, 0.0),
            apply_pct=apply_pct,
        )
        result[k] = int(math.floor(raw))
    return result


# ---------------------------------------------------------------------------
# 派生属性（细化_3b §5）——只读计算，不进入三层管线、永不回写属性层（ADR-03）
# ---------------------------------------------------------------------------

def crit_rate(
    final_luck: float,
    crit_bonus: float = 0.0,
    cap: float = 95.0,
) -> float:
    """会心率 %（细化_3b §5.1 / L41-45）。

    formula = min(cap, √最终幸运 × 0.5 + crit_bonus)
      - √幸运×0.5%：属性驱动基础（借绮谭必杀率口径）
      - crit_bonus：装备/技能/效果提供的会心加成（效果系统挂载）
      - cap 默认 95%，cap=0 = 不限（L217）
    返回值即为百分比数值（幸运 100 → 5.0，即 5%）。双通道共用一次会心判定（L44）。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.crit_prob（1a 参数化版，
    p_coef=0.5 即 ×0.5 口径），本函数为 3b 语义薄封装（% 对外口径）。
    crit_bonus 为百分数（3.0=3%），委托时 ÷100 转 damage 版小数口径。
    """
    return damage_crit_prob(final_luck, p_coef=0.5,
                            crit_bonus=crit_bonus / 100.0, cap=cap) * 100.0


def crit_roll(
    final_luck: float,
    random_roll: float,
    super_crit_level: int = 0,
) -> float:
    """会心倍率三档（细化_3b §5.1 / L49-63）。

    P = √最终幸运 ÷ 2；随机数 r = 1~100：
      - r ≤ P        → 高级会心：2.2 + 0.05×超会心等级
      - r ≤ P×3      → 中级会心：1.7 + 0.05×超会心等级
      - r > P×3      → 低级会心：1.3 + 0.05×超会心等级
    判定严格按「先高级再中级其余低级」顺序（L52-54 区间嵌套，避免重叠歧义）。
    超会心 Lv1-3 各档 +0.05×等级（效果系统 crit_mult_up 提供，L66）。
    示例（L65）：幸运 100 → P=5 → 高级 5% / 中级 10% / 低级 85%。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.crit_roll（1a 参数化版，
    随机数域 [0,1]、返回 (档位, 倍率)），本函数为 3b 语义薄封装（r 域 1~100 → /100，
    取倍率返回）。超会心等级经 damage 版 +0.05×level 三档齐加。
    """
    _tier, mult = damage_crit_roll(
        random_roll / 100.0,
        final_luck,
        p_coef=0.5,
        super_crit_level=super_crit_level,
    )
    return float(mult)


def hit_rate(
    final_focus: float,
    enemy_spd: float,
    k: float = 1.0,
) -> float:
    """命中率 %（细化_3b §5.2 / L81-85）。

    clamp(final_focus / (final_focus + K × 最终对方敏捷), 10%, 95%)，"%”。
    特例先于 clamp（L83/L84）：
      - 对方敏捷 ≤ 0 → 100%（L83）
      - 双方都为 0 → 100%（0/0 兜底，L84）
    K 可配，默认 1（L82；2026-08-24 用户拍板统一 3b/1a 同口径 K=1）。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.hit_rate（参数化版，
    K 经 formula.json hit.k 可配），本函数为 3b 语义薄封装（% 对外口径）。
    """
    return damage_hit_rate(final_focus, enemy_spd, k=k,
                           cap_min=10.0, cap_max=95.0) * 100.0


def block_rate(final_focus: float, k: float = 150.0, cap: float = 40.0) -> float:
    """格挡率 %（细化_3b §5.3 / L90-92）。

    min(40%, 最终专注 / (最终专注 + 150))。格挡 = 会心后最终伤害减半（L91）。
    （当回合格挡率减半、1v1 单次不消费等为战斗状态机职责，见细化_1g / M1。）

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.block_rate（参数化版，
    k/cap 经 formula.json 可配），本函数为 3b 语义薄封装（% 对外口径）。
    """
    return damage_block_rate(final_focus, k=k, cap=cap) * 100.0


def phys_reduce(final_con: float, k: float = 100.0) -> float:
    """物理减伤 %（细化_3b §5.4 / L20 / L31-32）。

    final_con / (final_con + K)，K=100 可配；无悬崖无封顶。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.defense_factor
    （系数 = K/(体质+K)，减伤率 = 1 − 系数），本函数为 3b 语义薄封装（% 对外口径）。
    """
    return (1.0 - damage_defense_factor(final_con, k=k)) * 100.0


def mag_reduce(final_spr: float, k: float = 100.0) -> float:
    """魔法减伤 %（细化_3b §5.4 / L21 / L31）。与物理同构除算，K=100 可配。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.defense_factor
    （系数 = K/(精神+K)，减伤率 = 1 − 系数），本函数为 3b 语义薄封装（% 对外口径）。
    """
    return (1.0 - damage_defense_factor(final_spr, k=k)) * 100.0


def elem_reduce(elem_res: float, k: float = 100.0) -> float:
    """元素减伤率 %（细化_3b §5.4 / L126-127）。

    elem_res / (elem_res + 100)；elem_res 来自装备词条（加成层 flat 口径），
    默认 0（即无元素减伤）。

    2026-08-24 M0 复查收敛：唯一实现在 core/damage.elem_factor
    （系数 = K/(抗性+K)，减伤率 = 1 − 系数），本函数为 3b 语义薄封装（% 对外口径）。
    """
    return (1.0 - damage_elem_factor(elem_res, k=k)) * 100.0
