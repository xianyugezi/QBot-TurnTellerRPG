"""批41 · 深度打造引擎（打造家族的「深度层」；纯函数、可独立测）。

文件：qbot_rpg/core/deep_craft.py
定位：**基础合成走公用层**（`core/synthesis.py` 的 `preview_base_output` /
  `base_output` / `requirements_of`，见 `docs/批39_合成公用层接口.md` 三）；本模块只做
  **深度层**计算，且全部为纯函数（同刻同参必同值；随机经**注入**的玩家级随机流
  `ctx["rng"]`（批40 H5）——本模块不读全局 random、不建第二条随机源）：

  1. `equipment_level`      —— 装备等级 = Σ(材料等级 × 占比)（完全同级 → 该级）；
  2. `quality_exp`          —— 品质经验 = Σ(品阶基数 × 相性系数 × 件数边际) × 种类奖励
                               × 互动乘子 × 全局衰减（**每次打造独立、不跨件累计**）；
  3. `quality_level_of`     —— 满经验 → 品质等级（阈值表）；
  4. `draw_quality`         —— 品质等级 → 颜色（13 行共享阶梯；图纸档决定行偏移；
                               红仅第 10 行起）；
  5. `craft_cost`           —— 总 cost = 工费 + 每种附加费 + Σ材料 cost；
  6. `plan_craft`           —— 汇总校验 + 计算，产出**纯计划**（拒绝只给 reason，
                               文案由指令层走模板表）。

依据：
  - `docs/深度打造_决策记录.md` §一 H1/H2/H6、§二 N1~N4/N6、§六（合成公用层）。
  - `打造系统_原案_20260919.md` §1/§3/§4/§5/§6/§8/§11/§12/§13。
  - `打造系统_B_数值与经验规划.md` §1.1~1.6 / §2.1~2.3 / §3.1~3.2。
  - 相性互动复用 `core/affinity.py::accumulate_affinity`（批38 通用层，唯一源）。

铁律：零 NoneBot import；core 层零 import content（配置经参数注入）；纯函数确定性；
      完整类型标注（typing 3.9 兼容）；不写内容包业务名。
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.core.affinity import (
    accumulate_affinity,
    normalize_affinity_config,
    rank_affinities,
    resolve_affinity_effect,
    resolve_available_entries,
)
from qbot_rpg.data.affinity_keys import (
    ENTRY_PAYLOAD_SET_AFFIX,
    ENTRY_PAYLOAD_STAT,
)

__all__ = [
    "equipment_level",
    "quality_exp",
    "quality_level_of",
    "draw_quality",
    "craft_cost",
    "resolve_main_sub",
    "draw_count",
    "plan_affixes",
    "resolve_passives",
    "plan_craft",
    "ROLE_MAIN",
    "ROLE_FREE",
    "REJECT_NO_BLUEPRINT",
    "REJECT_NOT_LEARNED",
    "REJECT_NO_MATERIALS",
    "REJECT_MAIN_MATERIAL",
    "REJECT_KINDS",
    "REJECT_PER_KIND",
    "REJECT_COST_OVER",
    "REJECT_COST_UNDER",
    "REJECT_LEVEL_BAND",
    "REJECT_DRAW",
]

ROLE_MAIN: str = "main"
ROLE_FREE: str = "free"

# 拒绝原因码（文案由指令层走模板表 deep_craft_<reason>；core 不含文案）
REJECT_NO_BLUEPRINT = "no_blueprint"
REJECT_NOT_LEARNED = "not_learned"
REJECT_NO_MATERIALS = "no_materials"
REJECT_MAIN_MATERIAL = "main_material"
REJECT_KINDS = "kinds"
REJECT_PER_KIND = "per_kind"
REJECT_COST_OVER = "cost_over"
REJECT_COST_UNDER = "cost_under"
REJECT_LEVEL_BAND = "level_band"
REJECT_DRAW = "draw"

_MISSING = object()


# ---------------------------------------------------------------------------
# 小工具（纯函数、防御性；非法值由校验器红拦，引擎不静默改作者数据）
# ---------------------------------------------------------------------------
def _as_map(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_num(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _as_int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _round_level(value: float, rounding: object) -> int:
    """等级取整（floor 保守 / round 四舍五入 / ceil 向上）；缺省 floor。"""
    mode = str(rounding or "floor")
    if mode == "ceil":
        return int(-(-value // 1))
    if mode == "round":
        return int(value + 0.5) if value >= 0 else -int(-value + 0.5)
    return int(value // 1)


# ---------------------------------------------------------------------------
# 1) 装备等级 = Σ(材料等级 × 占比)
# ---------------------------------------------------------------------------
def equipment_level(
    parts: Sequence[Mapping[str, Any]],
    weights: Mapping[str, Any],
    rounding: object = "floor",
) -> Optional[int]:
    """材料等级加权 → 装备等级（原案 §5）。

    入参：
      · parts：每行 `{level:int, count:int, role:"main"|"free"}`（**按投入顺序**）。
        同一 `role` 的件数均分该角色的合计占比（权重和 = main + free → 完全同级
        材料恰好得到该等级）。
      · weights：`{main: number, free: number}`（包声明 `material_level_weight`）。
      · rounding：floor / round / ceil。
    出参：装备等级 int（无有效材料 → None）。纯函数、确定性。
    """
    main_w = _as_num(_as_map(weights).get("main"))
    free_w = _as_num(_as_map(weights).get("free"))
    main_w = 0.0 if main_w is None else main_w
    free_w = 0.0 if free_w is None else free_w

    buckets: Dict[str, List[Tuple[int, int]]] = {ROLE_MAIN: [], ROLE_FREE: []}
    for row in parts:
        m = _as_map(row)
        lv = _as_int(m.get("level"))
        cnt = _as_int(m.get("count"))
        role = str(m.get("role") or ROLE_FREE)
        if lv is None or cnt is None or cnt < 1 or lv < 1:
            continue
        buckets[ROLE_MAIN if role == ROLE_MAIN else ROLE_FREE].append((lv, cnt))

    total = 0.0
    # 角色权重按**实际投入的角色**归一（缺角色的权重不分摊到另一角色）：
    #   · 只投主材料 → 主材料独占 100%（「完全同级材料 → 该级装备」对任意子集成立）；
    #   · 主/自由都投 → 按 main/free 比例分配（主材料占比大 → 拉动整件等级）。
    used_w = (main_w if buckets[ROLE_MAIN] else 0.0) + (free_w if buckets[ROLE_FREE] else 0.0)
    if used_w <= 0:
        return None
    for role, role_w in ((ROLE_MAIN, main_w), (ROLE_FREE, free_w)):
        rows = buckets[role]
        pieces = sum(c for _lv, c in rows)
        if pieces <= 0 or role_w <= 0:
            continue
        per = (role_w / used_w) / float(pieces)
        for lv, cnt in rows:
            total += float(lv) * per * float(cnt)
    if total <= 0:
        return None
    return _round_level(total, rounding)


# ---------------------------------------------------------------------------
# 2) 品质经验
# ---------------------------------------------------------------------------
def quality_exp(
    materials: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
    exp_by_color: Mapping[str, Any],
    *,
    blueprint_affinities: Mapping[str, Any] = {},
    affinity_reactions: Sequence[Any] = (),
) -> Dict[str, Any]:
    """单次打造品质经验（原案 §6/§12；**每次独立、不跨件累计**）。

    入参：
      · materials：每行 `{quality: 品质颜色id, count: 件数, same_affinity: bool}`
        （已按材料**聚合**；`same_affinity` = 该材料相性与图纸相性相交）。
      · rules：`settings.deep_craft.craft_rules`（包声明）。
      · exp_by_color：`{颜色id: 品阶基数}`。
      · blueprint_affinities：图纸相性声明（当前仅用于文档/扩展；同相性判定在
        `materials[].same_affinity` 已给出，保持本函数签名稳定）。
      · affinity_reactions：`settings.affinity_reactions`（批38 通用层）——用于
        **互动乘子**：Σ(结算后相性值) / Σ(投入相性值)，clamp 到包声明区间。
    出参：`{exp, base_sum, affinity_factor, interaction, type_factor, kinds}`。
    纯函数、确定性（互动复用 `core/affinity.accumulate_affinity`）。
    """
    r = _as_map(rules)
    decay = _as_num(r.get("slot_decay"))
    decay = 0.25 if decay is None else max(0.0, decay)
    type_bonus = _as_num(r.get("type_bonus"))
    type_bonus = 1.0 if type_bonus is None else type_bonus
    aff_bonus = _as_num(r.get("quality_exp_affinity_bonus"))
    aff_bonus = 1.0 if aff_bonus is None else aff_bonus
    global_decay = _as_num(r.get("global_decay"))
    global_decay = 1.0 if global_decay is None else max(0.0, global_decay)

    rows = [m for m in (_as_map(x) for x in materials)]
    kinds = 0
    base_sum = 0.0
    for m in rows:
        cnt = _as_int(m.get("count"))
        if cnt is None or cnt < 1:
            continue
        kinds += 1
        color = m.get("quality")
        base = _as_num(_as_map(exp_by_color).get(color))
        if base is None:
            base = 1.0
        aff = aff_bonus if m.get("same_affinity") is True else 1.0
        # 件数边际：第 j 件 × max(0, 1 − decay×j)
        effective = 0.0
        for j in range(cnt):
            marginal = 1.0 - decay * j
            if marginal <= 0:
                break
            effective += marginal
        base_sum += base * aff * effective

    type_factor = float(type_bonus) ** max(0, kinds - 1)
    interaction = _interaction_factor(rows, rules, affinity_reactions)
    exp = base_sum * type_factor * interaction * global_decay
    return {
        "exp": exp,
        "base_sum": base_sum,
        "type_factor": type_factor,
        "interaction": interaction,
        "kinds": kinds,
    }


def _interaction_factor(
    materials: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
    reactions: Sequence[Any],
) -> float:
    """材料互动 → 品质经验乘子（原案 §12：冲突互相减少 / 增幅互相增加）。

    口径（**工程补白 G-3**，原案未给幅度）：把材料相性按投入顺序交给
    `core/affinity.accumulate_affinity` 结算，取
    `Σ(结算后) / Σ(投入)`；clamp 到 craft_rules.interaction 声明的
    `[1+conflict, 1+amplify]`（缺省 [0.75, 1.15]）。反转不改变总量 → 乘子 1.0。
    """
    contributions: List[Mapping[str, Any]] = []
    raw_total = 0.0
    for m in materials:
        aff = _as_map(m.get("affinities"))
        if aff:
            contributions.append(aff)
            for v in aff.values():
                fv = _as_num(v)
                if fv is not None:
                    raw_total += fv
    if raw_total <= 0 or not reactions:
        return 1.0
    try:
        pool = accumulate_affinity(contributions, reactions)
    except Exception:  # noqa: BLE001 —— 互动异常不阻断（乘子退化为 1）
        return 1.0
    settled = sum(v for v in pool.values() if isinstance(v, (int, float)))
    if settled <= 0:
        return 1.0
    conf = _as_num(_as_map(_as_map(rules).get("interaction")).get("conflict"))
    amp = _as_num(_as_map(_as_map(rules).get("interaction")).get("amplify"))
    lo = 1.0 + (conf if conf is not None else -0.25)
    hi = 1.0 + (amp if amp is not None else 0.15)
    if lo > hi:
        lo, hi = hi, lo
    return min(max(settled / raw_total, lo), hi)


# ---------------------------------------------------------------------------
# 3) 品质等级（满经验 → +1；每次打造独立）
# ---------------------------------------------------------------------------
def quality_level_of(exp: Any, thresholds: Any) -> int:
    """品质经验 → 品质等级（原案 §6；阈值表左闭）。

    出参：等级 int（第 1 项通常为 0 → 经验 0 为 1 级）；阈值表非法/空 → 0。
    """
    fv = _as_num(exp)
    if fv is None:
        return 0
    th: List[float] = []
    for x in _as_list(thresholds):
        n = _as_num(x)
        if n is not None:
            th.append(n)
    level = 0
    for i, t in enumerate(th):
        if fv >= t:
            level = i + 1
    return level


# ---------------------------------------------------------------------------
# 4) 品质抽取（13 行共享阶梯；图纸档决定行偏移）
# ---------------------------------------------------------------------------
def draw_quality(
    rng: Any,
    table: Any,
    level: Any,
    level_offset: Any = 0,
) -> Optional[str]:
    """品质等级 → 品质颜色（概率表随机；**随机源 = 注入的玩家级随机流**）。

    入参：rng（random.Random 或同契约对象，含 `random()`/`choices` 至少其一）；
      table = `quality_draw_table`（`{ladder: {行号: {颜色: 权重}}}`）；
      level = 品质等级（1~10）；level_offset = 图纸档行偏移（铜 0 / 银 1 / 金 2 / 彩 3）。
    出参：颜色 id（缺行/无权重 → None）。确定性 = 由注入 rng 决定（可注入种子）。
    """
    lv = _as_int(level)
    off = _as_int(level_offset)
    if lv is None or lv < 1 or rng is None:
        return None
    row_no = lv + (off or 0)
    ladder = _as_map(_as_map(table).get("ladder"))
    row = _as_map(ladder.get(str(row_no)))
    if not row:
        return None
    colors: List[str] = []
    weights: List[float] = []
    for key, val in row.items():
        w = _as_num(val)
        if isinstance(key, str) and key and w is not None and w > 0:
            colors.append(key)
            weights.append(w)
    if not colors:
        return None
    total = sum(weights)
    pick = _rand_unit(rng) * total
    acc = 0.0
    for color, w in zip(colors, weights):
        acc += w
        if pick < acc:
            return color
    return colors[-1]


def _rand_unit(rng: Any) -> float:
    """注入随机源 → [0,1)（优先 `random()`；缺省失败退 0 → 取首项，确定性）。"""
    fn = getattr(rng, "random", None)
    if callable(fn):
        try:
            v = float(fn())
        except Exception:  # noqa: BLE001
            return 0.0
        return v if 0.0 <= v < 1.0 else 0.0
    return 0.0


# ---------------------------------------------------------------------------
# 5) 打造 cost（约束；仅约束不改数值）
# ---------------------------------------------------------------------------
def craft_cost(
    materials: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
) -> Dict[str, Any]:
    """总 cost = 固定工费 + 每种材料附加费 + Σ(材料 cost × 件数)。

    入参：materials 行 `{cost: number, count: int}`（每行一种材料）；rules 包声明。
    出参：`{cost, kinds, base, per_kind, material}`。
    """
    r = _as_map(rules)
    base = _as_num(r.get("cost_base"))
    per_kind = _as_num(r.get("cost_per_kind"))
    base = 0.0 if base is None else base
    per_kind = 0.0 if per_kind is None else per_kind
    kinds = 0
    material_cost = 0.0
    for m in materials:
        row = _as_map(m)
        cnt = _as_int(row.get("count"))
        if cnt is None or cnt < 1:
            continue
        kinds += 1
        c = _as_num(row.get("cost"))
        material_cost += (0.0 if c is None else c) * cnt
    return {
        "cost": base + per_kind * kinds + material_cost,
        "kinds": kinds,
        "base": base,
        "per_kind": per_kind,
        "material": material_cost,
    }


# ---------------------------------------------------------------------------
# 5b) 属性 / 套装词条 / 被动的相性池抽取（原案 §3/§4/§8/§11；批42 · C）
# ---------------------------------------------------------------------------
# 池词条行**载荷键**（框架 schema；唯一源 = `data/affinity_keys.py`，批43 收口）：
#   · `stat`       → 随机属性候选（键 = 属性键；数值取同行 `value`）
#   · `set_affix`  → 随机套装词条候选（值 = 套装词条 id）
#   · `enhance_affix` → 强化特殊词条候选（批43；键 = data/gear_stats.py 登记词条键）
# 池的构造 / 联动覆盖 / requires_affinity 过滤 **全部**由
# `affinity.resolve_available_entries` 承担（唯一入口）——本模块只在**返回值**上按载荷键
# 分流，不重算池、不本地匹配相性。
ENTRY_STAT: str = ENTRY_PAYLOAD_STAT
ENTRY_SET_AFFIX: str = ENTRY_PAYLOAD_SET_AFFIX
ENTRY_WEIGHT: str = "weight"


def _entry_payload(row: Any, key: str) -> Optional[str]:
    """池词条行 → 载荷值（非空 str 才算命中，否则 None）。"""
    v = _as_map(row).get(key)
    return v if isinstance(v, str) and v else None


def resolve_main_sub(
    blueprint: Mapping[str, Any],
    materials: Sequence[Mapping[str, Any]],
    *,
    affinity_order: Sequence[Any] = (),
    affinity_reactions: Sequence[Any] = (),
) -> Dict[str, Any]:
    """图纸 + 材料相性 → 主/副相性（原案 §8「最高=主、第二=副」）。

    入参：
      · blueprint：图纸条目（含 `affinities: {相性id: 数值}`）。
      · materials：投料归一后的材料行（**按投入顺序**；每行含 `affinities`）。
      · affinity_order：相性声明顺序（内容包 `settings.affinities[]`）——并列破平用。
      · affinity_reactions：`settings.affinity_reactions`（冲突/增幅/反转）。
    出参：`{main, sub, ranked, values}`；无正值 → main/sub 均 None。

    口径（工程补白 C-1，原案未写图纸贡献的位置）：**图纸相性作为前置贡献**，其后按材料
    投入顺序追加；结算复用 `affinity.accumulate_affinity`（唯一互动实现）。并列时由
    `affinity.rank_affinities` 按 `affinity_order`（缺省 id 升序）确定性破平。
    """
    contribs: List[Mapping[str, Any]] = []
    bp_aff = _as_map(_as_map(blueprint).get("affinities"))
    if bp_aff:
        contribs.append(bp_aff)
    for m in materials:
        aff = _as_map(_as_map(m).get("affinities"))
        if aff:
            contribs.append(aff)
    values = accumulate_affinity(contribs, affinity_reactions)
    ranked = rank_affinities(values, affinity_order)
    return {
        "main": ranked["main"],
        "sub": ranked["sub"],
        "ranked": ranked["ranked"],
        "values": values,
    }


def _count_bounds(raw: Any, fallback: Any) -> Tuple[int, int]:
    """条数声明 `{min,max}` → (lo, hi)；行缺省回落 fallback（craft_rules 默认）；
    非法/负值截 0；hi<lo 归一为 lo（不外抛，校验器红拦非法声明）。"""
    m = _as_map(raw)
    d = _as_map(fallback)
    lo = _as_int(m.get("min"))
    if lo is None:
        lo = _as_int(d.get("min"))
    hi = _as_int(m.get("max"))
    if hi is None:
        hi = _as_int(d.get("max"))
    lo = 0 if lo is None or lo < 0 else lo
    hi = lo if hi is None or hi < lo else hi
    return lo, hi


def draw_count(rng: Any, raw: Any, fallback: Any = None) -> int:
    """随机条数：包声明 `{min,max}` → 注入随机流均匀取整数。

    min==max → 恒定该值；缺省/非法 → 回落 fallback；rng 不可用 → 取 min（确定性）。
    **条数一律包声明**（图纸字段优先，缺省用 `craft_rules.random_*_count`）。
    """
    lo, hi = _count_bounds(raw, fallback)
    if hi <= lo or rng is None:
        return lo
    return lo + int(_rand_unit(rng) * float(hi - lo + 1))


def _pick_weighted(
    rng: Any,
    rows: Sequence[Mapping[str, Any]],
    payload_key: str,
    count: int,
    exclude: Sequence[str] = (),
) -> List[Mapping[str, Any]]:
    """按 `weight` 权重**不放回**抽 count 行（同一载荷键至多 1 行）。

    · 权重全 0/缺失 → 取候选首项（确定性，**不引入未声明概率**），仍逐项去重；
    · 候选不足 → 抽满候选为止（实际条数 = min(声明条数, 候选数)，不补空）；
    · exclude 内的载荷键不参与（随机套装词条不复抽固定词条）。
    """
    pool = list(rows)
    picked: List[Mapping[str, Any]] = []
    taken = {x for x in exclude if isinstance(x, str) and x}
    while len(picked) < count:
        avail = [r for r in pool if _entry_payload(r, payload_key) not in taken]
        if not avail:
            break
        weights: List[float] = []
        for r in avail:
            w = _as_num(_as_map(r).get(ENTRY_WEIGHT))
            weights.append(0.0 if w is None or w < 0 else w)
        total = sum(weights)
        if total <= 0:
            idx = 0
        else:
            pick = _rand_unit(rng) * total
            acc = 0.0
            idx = len(avail) - 1
            for i, w in enumerate(weights):
                acc += w
                if pick < acc:
                    idx = i
                    break
        row = avail[idx]
        picked.append(row)
        taken.add(str(_entry_payload(row, payload_key)))
        pool = [r for r in pool if r is not row]
    return picked


def resolve_passives(
    blueprint: Mapping[str, Any],
    trait_defs: Optional[Mapping[str, Any]],
    main: Optional[str],
    sub: Optional[str],
) -> List[str]:
    """模板固定被动 + 相性变更 → 本次实例的被动 id 序列（原案 §11；批42 · C）。

    · 图纸 `blueprint_passive`（str 或 list）→ 逐条取 `traits.json` 定义；
    · 定义带 `affinity_variants` → **确定性**替换：调 `affinity.resolve_affinity_effect`
      （`"<main>|<sub>"` 优先、退 `"<main>"`；无命中 → 保留原被动）；
    · 无 `traits` 定义/无变体 → 原被动 id 原样保留（框架不臆造）；
    · 结果按出现顺序去重。**打造时求值、冻进实例**（同模板多件可不同）。
    """
    raw = _as_map(blueprint).get("blueprint_passive")
    declared: List[str] = []
    if isinstance(raw, str):
        declared = [raw] if raw else []
    else:
        declared = [x for x in _as_list(raw) if isinstance(x, str) and x]
    defs = _as_map(trait_defs)
    out: List[str] = []
    for pid in declared:
        variants = _as_map(defs.get(pid)).get("affinity_variants")
        target = resolve_affinity_effect(variants, main, sub) if variants else None
        if not isinstance(target, str) or not target:
            target = pid
        if target not in out:
            out.append(target)
    return out


def plan_affixes(
    *,
    blueprint: Mapping[str, Any],
    materials: Sequence[Mapping[str, Any]],
    config: Mapping[str, Any],
    rng: Any = None,
    affinity_config: Any = None,
    affinity_reactions: Sequence[Any] = (),
    level: Optional[int] = None,
    trait_defs: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """单次打造的完整词条计划：**固定照抄 + 随机从相性池抽**（原案 §3/§4/§8/§11）。

    入参：
      · blueprint：图纸条目（`blueprint_fixed_stats` / `blueprint_random_stat_count` /
        `blueprint_fixed_set_affix` / `blueprint_random_set_affix_count` /
        `blueprint_random_set_affix_pool` / `blueprint_passive` / `affinities`）。
      · materials：投料归一后的材料行（按投入顺序，含 `affinities`）。
      · config：`read_deep_craft_settings` 归一配置（缺省条数取 `craft_rules`）。
      · rng：玩家级随机流（批40 H5）；缺省 → 条数取 min、抽取退化取首项。
      · affinity_config：settings（或已归一相性配置）——池查询唯一入口
        `affinity.resolve_available_entries` 的入参。
      · level：装备等级（过滤池词条 `min_level`）。
      · trait_defs：`ctx["traits"]`（被动定义表；缺省 → 被动 id 原样保留）。
    出参（全部纯数据，可 JSON）：
      `{affinity{main,sub,ranked,values}, fixed_stats, random_stats, stats_bonus,
        fixed_set_affixes, random_set_affixes, set_affixes, passives,
        random_stat_count, random_set_affix_count, stat_pool_size, set_affix_pool_size}`。

    边界口径（原案 §12「本质一个池子，没有对应相性就抽不出来」）：
      · **无相性 → 要求相性的词条抽不出**（`resolve_available_entries` 的
        `requires_affinity ⊆ {main,sub}` 过滤；通用池中不要求相性的词条仍可抽）；
      · 联动命中（main+sub）→ 主专属池被 `override_pool` 覆盖（affinity 层已实现）；
      · 候选不足声明条数 → 实际条数 = min(声明, 候选)，**不补空**；
      · 随机套装词条不复抽固定套装词条（exclude 固定项）。
    """
    bp = _as_map(blueprint)
    rules = _as_map(_as_map(config).get("craft_rules"))
    cfg = normalize_affinity_config(affinity_config)
    aff = resolve_main_sub(
        bp, materials,
        affinity_order=cfg.get("affinity_list") or (),
        affinity_reactions=affinity_reactions,
    )
    # 池查询唯一入口（通用池 ∪ 主专属池；联动命中 → 覆盖；requires_affinity 过滤）。
    entries = resolve_available_entries(cfg, aff["main"], aff["sub"], level)

    # ---- 固定项：按图纸声明**照抄**（不缩放、不改键；数值缩放规则见 §C 待裁决）----
    fixed_stats: Dict[str, float] = {}
    for row in _as_list(bp.get("blueprint_fixed_stats")):
        m = _as_map(row)
        stat = m.get("stat")
        val = _as_num(m.get("value"))
        if isinstance(stat, str) and stat and val is not None:
            fixed_stats[stat] = fixed_stats.get(stat, 0.0) + val
    fixed_sets: List[str] = []
    _fs = bp.get("blueprint_fixed_set_affix")
    if isinstance(_fs, str) and _fs:
        fixed_sets.append(_fs)

    # ---- 候选分流（只读 resolve_available_entries 的返回值，不重算池）----
    stat_rows = [e for e in entries if _entry_payload(e, ENTRY_STAT)]
    _pool_filter = bp.get("blueprint_random_set_affix_pool")
    if isinstance(_pool_filter, str) and _pool_filter:
        # 声明池 id → 在**已解析候选**中再按 `_pool` 收窄（工程补白 C-2：不外开第二条池查询；
        # 声明池不在「通用 ∪ 专属/联动」可达集内 → 无候选 = 抽不出）。
        set_rows = [e for e in entries if _entry_payload(e, ENTRY_SET_AFFIX)
                    and str(_as_map(e).get("_pool") or "") == _pool_filter]
    else:
        set_rows = [e for e in entries if _entry_payload(e, ENTRY_SET_AFFIX)]

    # ---- 条数（包声明；图纸优先，缺省回落 craft_rules）----
    want_stat = draw_count(rng, bp.get("blueprint_random_stat_count"),
                           rules.get("random_stat_count"))
    want_set = draw_count(rng, bp.get("blueprint_random_set_affix_count"),
                          rules.get("random_set_affix_count"))

    # ---- 抽取（权重、不放回、同载荷键去重）----
    picked_stats = _pick_weighted(rng, stat_rows, ENTRY_STAT, want_stat)
    picked_sets = _pick_weighted(rng, set_rows, ENTRY_SET_AFFIX, want_set, fixed_sets)

    bonus = dict(fixed_stats)
    random_stats: List[Dict[str, Any]] = []
    for row in picked_stats:
        stat = _entry_payload(row, ENTRY_STAT)
        val = _as_num(_as_map(row).get("value"))
        val = 0.0 if val is None else val
        random_stats.append({"stat": stat, "value": val,
                             "pool": str(_as_map(row).get("_pool") or "")})
        bonus[str(stat)] = bonus.get(str(stat), 0.0) + val

    random_sets = [str(_entry_payload(row, ENTRY_SET_AFFIX)) for row in picked_sets]
    set_affixes = fixed_sets + [s for s in random_sets if s not in fixed_sets]

    return {
        "affinity": aff,
        "fixed_stats": fixed_stats,
        "random_stats": random_stats,
        "stats_bonus": bonus,
        "fixed_set_affixes": fixed_sets,
        "random_set_affixes": random_sets,
        "set_affixes": set_affixes,
        "passives": resolve_passives(bp, trait_defs, aff["main"], aff["sub"]),
        "random_stat_count": want_stat,
        "random_set_affix_count": want_set,
        "stat_pool_size": len(stat_rows),
        "set_affix_pool_size": len(set_rows),
    }


# ---------------------------------------------------------------------------
# 6) 主流程计划（纯校验 + 计算；拒绝只给 reason）
# ---------------------------------------------------------------------------
def _slot_role_of(mat_id: str, mat: Mapping[str, Any], slots: Sequence[Any]) -> List[str]:
    """材料命中的槽角色集合（指定 item 或 tag 过滤；未命中 → 空）。"""
    tags = [str(t) for t in _as_list(_as_map(mat).get("material_tags"))]
    roles: List[str] = []
    for slot in slots:
        s = _as_map(slot)
        role = str(s.get("role") or ROLE_FREE)
        hit = False
        if isinstance(s.get("item"), str) and s.get("item"):
            hit = s.get("item") == mat_id
        elif isinstance(s.get("tag"), str) and s.get("tag"):
            hit = s.get("tag") in tags
        else:
            hit = role == ROLE_FREE  # 无过滤的自由槽：任意材料可填
        if hit:
            roles.append(ROLE_MAIN if role == ROLE_MAIN else ROLE_FREE)
    return roles


def plan_craft(
    *,
    blueprint: Mapping[str, Any],
    config: Mapping[str, Any],
    materials: Sequence[Mapping[str, Any]],
    material_defs: Mapping[str, Any],
    learned: bool = False,
    rng: Any = None,
    affinity_config: Any = None,
    trait_defs: Optional[Mapping[str, Any]] = None,
    affinity_reactions: Sequence[Any] = (),
) -> Dict[str, Any]:
    """深度打造主流程（纯函数）：校验 → 等级 → 品质经验 → 品质等级 → 品质抽取 → cost
    → **词条计划（固定照抄 + 随机相性池抽取 + 被动相性变体）**。

    入参：
      · blueprint：图纸条目（items 条目，含 blueprint_* 字段与 affinities）。
      · config：`read_deep_craft_settings` 的归一配置。
      · materials：投入材料 `{id, count}`（**按投入顺序**）。
      · material_defs：`{材料id: 条目}`（material_level/material_quality/craft_cost/
        affinities/material_tags/price 读取源）。
      · learned：该图纸是否已学习（true 才可打造）。
      · rng：玩家级随机流（批40 H5）；quality 抽取与随机词条用。
      · affinity_config：settings（或已归一相性配置）——相性池查询唯一入口
        `affinity.resolve_available_entries` 的入参（批42 · C）。
      · trait_defs：`ctx["traits"]`（装备被动定义表；缺省 → 被动 id 原样保留）。
      · affinity_reactions：`settings.affinity_reactions`（互动乘子/相性累计）。
    出参：`{ok, reason, level, quality_exp, quality_level, quality, color_row, cost,
      cost_cap, kinds, materials[...], main_level, affinity, fixed_stats, random_stats,
      stats_bonus, fixed_set_affixes, random_set_affixes, set_affixes, passives, ...}`；
      拒绝 `{ok: False, reason, ...}`。
    """
    rules = _as_map(config.get("craft_rules"))
    grades = _as_list(config.get("blueprint_grades"))
    table = config.get("quality_draw_table")

    bp = _as_map(blueprint)
    if not bp:
        return {"ok": False, "reason": REJECT_NO_BLUEPRINT}
    if not learned:
        return {"ok": False, "reason": REJECT_NOT_LEARNED}

    # ---- 材料归一（按投入顺序；聚合件数、命中槽角色）----
    slots = _as_list(bp.get("blueprint_material_slots"))
    defs = _as_map(material_defs)
    rows: List[Dict[str, Any]] = []
    for raw in materials:
        m = _as_map(raw)
        mid = m.get("id")
        cnt = _as_int(m.get("count"))
        if not isinstance(mid, str) or not mid or cnt is None or cnt < 1:
            continue
        mdef = _as_map(defs.get(mid))
        roles = _slot_role_of(mid, mdef, slots)
        lv = _as_int(mdef.get("material_level"))
        lv = 1 if lv is None or lv < 1 else lv
        cost = _as_num(mdef.get("craft_cost"))
        if cost is None:
            cost = _as_num(mdef.get("price")) or 0.0
        rows.append({
            "id": mid,
            "count": cnt,
            "level": lv,
            "quality": mdef.get("material_quality"),
            "cost": cost,
            "affinities": dict(_as_map(mdef.get("affinities"))),
            "roles": roles,
        })
    if not rows:
        return {"ok": False, "reason": REJECT_NO_MATERIALS}

    max_kinds = _as_int(rules.get("max_kinds"))
    max_per_kind = _as_int(rules.get("max_per_kind"))
    if max_kinds is not None and len(rows) > max_kinds:
        return {"ok": False, "reason": REJECT_KINDS, "kinds": len(rows), "limit": max_kinds}
    if max_per_kind is not None:
        for row in rows:
            if row["count"] > max_per_kind:
                return {"ok": False, "reason": REJECT_PER_KIND,
                        "item": row["id"], "count": row["count"], "limit": max_per_kind}

    # ---- 主材料槽（N2 ①）：图纸声明主材料槽时，投入里必须有材料填它 ----
    bp_roles = [str(_as_map(s).get("role") or ROLE_FREE) for s in slots]
    main_parts = [r for r in rows if ROLE_MAIN in r["roles"]]
    if ROLE_MAIN in bp_roles and not main_parts:
        return {"ok": False, "reason": REJECT_MAIN_MATERIAL}

    # ---- 等级（N2 ① 等级带）----
    level_parts = []
    for r in rows:
        role = ROLE_MAIN if (main_parts and ROLE_MAIN in r["roles"]) else ROLE_FREE
        level_parts.append({"level": r["level"], "count": r["count"], "role": role})
    lv_out = equipment_level(level_parts, rules.get("material_level_weight"),
                             rules.get("level_rounding"))
    if lv_out is None:
        return {"ok": False, "reason": REJECT_NO_MATERIALS}
    band = _as_map(bp.get("blueprint_level_band"))
    band_min = _as_int(band.get("min"))
    band_max = _as_int(band.get("max"))
    band = [band_min, band_max]
    if band_min is not None and lv_out < band_min:
        return {"ok": False, "reason": REJECT_LEVEL_BAND, "level": lv_out, "band": band}
    if band_max is not None and lv_out > band_max:
        return {"ok": False, "reason": REJECT_LEVEL_BAND, "level": lv_out, "band": band}

    # ---- 同相性判定 + 品质经验 ----
    bp_aff = {k for k in _as_map(bp.get("affinities")).keys() if isinstance(k, str) and k}
    q_parts: List[Dict[str, Any]] = []
    for r in rows:
        same = bool(bp_aff & set(r["affinities"].keys()))
        q_parts.append({"quality": r["quality"], "count": r["count"],
                        "same_affinity": same, "affinities": r["affinities"]})
    qe = quality_exp(q_parts, rules, config.get("quality_exp_by_color") or {},
                     blueprint_affinities=_as_map(bp.get("affinities")),
                     affinity_reactions=affinity_reactions)
    q_level = quality_level_of(qe["exp"], rules.get("quality_level_thresholds"))

    # ---- 品质抽取（图纸档 → 行偏移）----
    grade_id = bp.get("blueprint_grade")
    grade = next((dict(g) for g in grades if _as_map(g).get("id") == grade_id), None)
    offset = _as_int(_as_map(grade).get("level_offset")) or 0
    color = draw_quality(rng, table, q_level, offset)
    if color is None:
        return {"ok": False, "reason": REJECT_DRAW, "level": lv_out,
                "quality_level": q_level}

    # ---- cost 约束（N2 ②：上限按图纸档缩放；可被图纸覆盖）----
    cc = craft_cost([{"cost": r["cost"], "count": r["count"]} for r in rows], rules)
    cap = _as_int(bp.get("blueprint_cost_cap"))
    if cap is None or cap <= 0:
        cap = _as_int(_as_map(grade).get("cost_cap")) or 0
    floor_ratio = _as_num(rules.get("cost_floor_ratio")) or 0.0
    floor = cap * floor_ratio
    if cap > 0 and cc["cost"] > cap:
        return {"ok": False, "reason": REJECT_COST_OVER, "cost": cc["cost"], "cap": cap}
    if floor > 0 and cc["cost"] < floor:
        return {"ok": False, "reason": REJECT_COST_UNDER, "cost": cc["cost"], "floor": floor}

    # ---- 词条计划（批42 · C）：固定照抄 + 随机相性池 + 被动相性变体 ----
    # 放在 quality/cost 之后：随机流的**前几次取值语义不变**（quality 抽取仍取首个随机数），
    # 批41 既有结果对拍不受影响。异常不阻断主流程（退化为无随机词条）。
    try:
        affix_plan = plan_affixes(
            blueprint=bp, materials=rows, config=config, rng=rng,
            affinity_config=affinity_config, affinity_reactions=affinity_reactions,
            level=lv_out, trait_defs=trait_defs)
    except Exception:  # noqa: BLE001 —— 词条抽取异常不阻断主流程
        affix_plan = {}

    return {
        "ok": True,
        "reason": None,
        "lesson": None,
        "level": lv_out,
        "quality_exp": qe["exp"],
        "quality_exp_breakdown": qe,
        "quality_level": q_level,
        "quality": color,
        "grade": grade_id,
        "color_row": q_level + offset,
        "cost": cc["cost"],
        "cost_cap": cap,
        "kinds": len(rows),
        "main_level": main_parts[0]["level"] if main_parts else None,
        "materials": rows,
        # ---- 批42 · C：相性 / 固定+随机属性 / 套装词条 / 被动 ----
        "affinity": affix_plan.get("affinity") or {
            "main": None, "sub": None, "ranked": [], "values": {}},
        "fixed_stats": affix_plan.get("fixed_stats") or {},
        "random_stats": affix_plan.get("random_stats") or [],
        "stats_bonus": affix_plan.get("stats_bonus") or {},
        "fixed_set_affixes": affix_plan.get("fixed_set_affixes") or [],
        "random_set_affixes": affix_plan.get("random_set_affixes") or [],
        "set_affixes": affix_plan.get("set_affixes") or [],
        "passives": affix_plan.get("passives") or [],
        "random_stat_count": affix_plan.get("random_stat_count", 0),
        "random_set_affix_count": affix_plan.get("random_set_affix_count", 0),
    }
