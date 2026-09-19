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

from qbot_rpg.core.affinity import accumulate_affinity

__all__ = [
    "equipment_level",
    "quality_exp",
    "quality_level_of",
    "draw_quality",
    "craft_cost",
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
    affinity_reactions: Sequence[Any] = (),
) -> Dict[str, Any]:
    """深度打造主流程（纯函数）：校验 → 等级 → 品质经验 → 品质等级 → 品质抽取 → cost。

    入参：
      · blueprint：图纸条目（items 条目，含 blueprint_* 字段与 affinities）。
      · config：`read_deep_craft_settings` 的归一配置。
      · materials：投入材料 `{id, count}`（**按投入顺序**）。
      · material_defs：`{材料id: 条目}`（material_level/material_quality/craft_cost/
        affinities/material_tags/price 读取源）。
      · learned：该图纸是否已学习（true 才可打造）。
      · rng：玩家级随机流（批40 H5）；quality 抽取与随机属性用。
      · affinity_reactions：`settings.affinity_reactions`（互动乘子/相性累计）。
    出参：`{ok, reason, level, quality_exp, quality_level, quality, color_row, cost,
      cost_cap, kinds, materials[...], main_level}`；拒绝 `{ok: False, reason, ...}`。
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
    }
