"""批57 · 装备淬炼引擎（temper）+ 精粹经济（essence）——**纯函数、可独立测**。

文件：qbot_rpg/core/temper.py
定位：对齐 `core/gem_wallet.py` / `core/enhance_affix.py` 的「core 纯引擎」风格——
  零 NoneBot import、零 IO、无全局 random、配置经参数注入；core→{data} 合法。

职责（报告 C-1/C-2/C-3/C-6/C-7 + 决策记录 §十五 D 组）：
  1. **配置归一**：`normalize_temper_config` / `normalize_essence_config`——内容包 raw 段
     深合并到 `data/temper_stats` 的默认值（缺键补默认、非法值回退，纯函数不改 raw）。
  2. **上限**：`total_cap_of` / `per_stat_cap_of` / `allowed_stats_of` / `cap_state`——
     装备等级（`ItemInstance.required_level`）× `cap_per_level`，逐级/绝对值/单项覆盖可配。
  3. **消耗**：`temper_cost`——每点精粹（默认 1593，报告 §4.6 反解平衡点）× 属性权重 ×
     递增系数；货币为第二道闸（可配）。
  4. **淬炼结算计划**：`plan_temper`（纯校验 + 新分配 + 消耗，不落账）；`can_temper`。
  5. **物化**：`materialize_temper`——把分配**增量物化**进既有 `stats_bonus`
     （复用面板聚合/战斗桥/展示零改动）。**幂等口径（报告 §5 D9 = (a)）**：
     以 `temper_alloc` 为唯一事实源，写回 = `旧值 + (新分配值 − 旧分配值)`；
     分配存于实例 → 重放同一操作时 `new==old` → 增量为 0（不双计）。
  6. **分账**：`enhance_level`（强化）与 `temper_alloc`（淬炼）**分开存**——
     本引擎不读写 `enhance_level`，既有强化链路不受影响（对拍见测试 B 组）。
  7. **精粹产出**：`essence_base`（`V × k1 × k2 × β^色序`）/ `temper_refund`（随淬炼量衰减）/
     `essence_for_instance`（产出 = 基础 + 返还）。
  8. **经济推演**：`simulate_cycle` / `typical_cycle`——证明不再是 84:1、且不存在无限套利。

【缺省零变化】两段 `enabled=False` → 本模块全部函数只读配置、不改任何状态；
  引擎调用方在 `enabled=False` 时直接返回「未启用」，逐字段与批57 前一致。

【内容包业务名纪律】本模块不出现任何内容包/物品/属性业务名；属性键经
  `data/gear_stats` 复用，色序经调用方传入的 `quality_colors` 声明顺序派生。
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from qbot_rpg.data.gear_stats import GEAR_FLAT_KEYS, GEAR_NUMERIC_KEYS
from qbot_rpg.data.temper_stats import (
    DEFAULT_TEMPER,
    TEMPER_ROUNDINGS,
    normalize_essence_config,
    normalize_temper_config,
)

__all__ = [
    "normalize_temper_config",
    "normalize_essence_config",
    "resolve_equipment_level",
    "total_cap_of",
    "per_stat_cap_of",
    "allowed_stats_of",
    "value_per_point_of",
    "alloc_total",
    "cap_state",
    "can_temper",
    "temper_cost",
    "plan_temper",
    "reset_alloc",
    "materialize_temper",
    "essence_color_order",
    "essence_base",
    "temper_refund",
    "essence_for_instance",
    "simulate_cycle",
    "typical_cycle",
]


# ---------------------------------------------------------------------------
# 基础工具（排除 bool——bool 是 int 子类）
# ---------------------------------------------------------------------------
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: Any) -> Optional[float]:
    if _is_num(v):
        return float(v)
    return None


def _as_int(v: Any) -> Optional[int]:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):  # pragma: no cover
        return None
    if f != int(f):
        return None
    return int(f)


def _apply_rounding(raw: float, mode: Any) -> int:
    """整体取整一次（报告 §3.1D：不要逐材料/逐项 floor）。"""
    m = str(mode or "floor")
    if m not in TEMPER_ROUNDINGS:
        m = "floor"
    if m == "ceil":
        return int(math.ceil(raw))
    if m == "round":
        return int(math.floor(raw + 0.5))
    return int(math.floor(raw))


def _norm_t(cfg: Any) -> Dict[str, Any]:
    """temper 段归一（None → 全默认）。"""
    return normalize_temper_config(cfg)


def _norm_e(cfg: Any) -> Dict[str, Any]:
    """essence_rate 段归一（None → 全默认）。"""
    return normalize_essence_config(cfg)


# ---------------------------------------------------------------------------
# 上限
# ---------------------------------------------------------------------------
def resolve_equipment_level(instance_or_level: Any, cfg: Mapping[str, Any]) -> int:
    """解析「装备等级」输入（原案 §10 R1）。

    入参 instance_or_level：int（直接给等级）或带 `required_level` 的实例（ItemInstance/dict）。
    出参：非负 int——实例等级缺失/≤0 → 配置兜底 `default_level`（缺省 0 = 不可淬炼）。
    """
    lv: Optional[int] = None
    if isinstance(instance_or_level, int) and not isinstance(instance_or_level, bool):
        lv = instance_or_level
    elif isinstance(instance_or_level, Mapping):
        lv = _as_int(instance_or_level.get("required_level"))
    elif instance_or_level is not None:
        lv = _as_int(getattr(instance_or_level, "required_level", None))
    if lv is None or lv <= 0:
        lv = _as_int(cfg.get("default_level")) or 0
    return max(0, lv)


def total_cap_of(level: Any, cfg: Mapping[str, Any]) -> int:
    """总淬炼上限（原案 §10 R1/R3）。

    优先级：`total_cap`（显式绝对值）→ `total_cap_by_level[等级]` → `等级 × cap_per_level`。
    """
    explicit = _as_int(cfg.get("total_cap"))
    if explicit is not None and explicit >= 0:
        return explicit
    by_level = cfg.get("total_cap_by_level")
    if isinstance(by_level, Mapping):
        hit = _as_int(by_level.get(str(level))) if by_level.get(str(level)) is not None else None
        if hit is not None and hit >= 0:
            return hit
        hit = _as_int(by_level.get(level)) if not isinstance(level, str) else None
        if hit is not None and hit >= 0:
            return hit
    lv = _as_int(level) or 0
    per = _as_int(cfg.get("cap_per_level")) or 0
    return max(0, lv) * max(0, per)


def per_stat_cap_of(stat: str, total_cap: int, cfg: Mapping[str, Any]) -> int:
    """单项淬炼上限（原案 §10 R4）：逐属性覆盖优先，否则 `floor(总值 × ratio)`。"""
    override = cfg.get("per_stat_cap")
    if isinstance(override, Mapping):
        hit = _as_int(override.get(stat)) if override.get(stat) is not None else None
        if hit is not None and hit >= 0:
            return hit
    ratio = _num(cfg.get("per_stat_cap_ratio"))
    if ratio is None:
        ratio = 0.5
    return int(math.floor(max(0, total_cap) * ratio))


def allowed_stats_of(stats_bonus: Any, cfg: Mapping[str, Any]) -> Tuple[str, ...]:
    """可淬炼属性清单（原案 §10 R2/R5）。

    口径（报告 §2.1 澄清）：`allowed_stats` 显式声明优先（过滤到 `GEAR_NUMERIC_KEYS`）；
    空 → 该实例**已有属性键** ∩ `GEAR_NUMERIC_KEYS`；仍空 → 回退 `GEAR_FLAT_KEYS`。
    """
    declared = cfg.get("allowed_stats")
    if isinstance(declared, (list, tuple)) and declared:
        return tuple(str(k) for k in declared if str(k) in GEAR_NUMERIC_KEYS)
    keys: List[str] = []
    if isinstance(stats_bonus, Mapping):
        for k in stats_bonus.keys():
            sk = str(k)
            if sk in GEAR_NUMERIC_KEYS and sk not in keys:
                keys.append(sk)
    if keys:
        return tuple(keys)
    return tuple(GEAR_FLAT_KEYS)


def value_per_point_of(stat: str, cfg: Mapping[str, Any]) -> float:
    """每点属性增量（flat 白值 / pct 百分点；本批工程补白：默认 1.0）。"""
    return float(cfg.get("value_per_point") or 1.0)


def alloc_total(alloc: Any) -> int:
    """分配表总点数（`temper_alloc` 的求和；容错非 int/负数归 0）。"""
    if not isinstance(alloc, Mapping):
        return 0
    total = 0
    for v in alloc.values():
        i = _as_int(v)
        if i is not None and i > 0:
            total += i
    return total


def cap_state(alloc: Any, level: Any, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """当前分配的上限状态（只读；供指令/展示/测试复用同一口径）。"""
    cap = total_cap_of(level, cfg)
    used = alloc_total(alloc)
    per: Dict[str, Dict[str, int]] = {}
    if isinstance(alloc, Mapping):
        for k, v in alloc.items():
            sk = str(k)
            i = _as_int(v) or 0
            pc = per_stat_cap_of(sk, cap, cfg)
            per[sk] = {"used": max(0, i), "cap": pc, "remaining": max(0, pc - max(0, i))}
    return {
        "level": _as_int(level) or 0,
        "total_cap": cap,
        "total_used": used,
        "total_remaining": max(0, cap - used),
        "per_stat": per,
    }


# ---------------------------------------------------------------------------
# 消耗 / 计划
# ---------------------------------------------------------------------------
def temper_cost(stat: str, current_total: int, total_cap: int, points: int,
                cfg: Mapping[str, Any]) -> Dict[str, int]:
    """本次淬炼消耗（报告 §2.3）：逐点累加，含递增系数与属性权重。

    `cost_per_point.essence/currency` × `stat_weight[stat]` × `(1 + cost_growth × 已投点/上限)`。
    取整：逐点向上取整后求和（确定性；缺省 cost_growth=0 → 恰好 = base × points）。
    """
    cpp = cfg.get("cost_per_point")
    if not isinstance(cpp, Mapping):
        cpp = DEFAULT_TEMPER["cost_per_point"]
    base_e = max(0, _as_int(cpp.get("essence")) or 0)
    base_c = max(0, _as_int(cpp.get("currency")) or 0)
    weight_map = cfg.get("stat_weight")
    weight = float(weight_map.get(stat, 1.0)) if isinstance(weight_map, Mapping) else 1.0
    if weight < 0:
        weight = 0.0
    growth = _num(cfg.get("cost_growth")) or 0.0
    cap = max(1, int(total_cap))
    n = max(0, int(points))
    start = max(0, int(current_total))
    essence = 0
    currency = 0
    for i in range(start, start + n):
        factor = 1.0 + growth * (i / cap)
        essence += int(math.ceil(base_e * weight * factor))
        currency += int(math.ceil(base_c * weight * factor))
    return {"essence": essence, "currency": currency}


def can_temper(stats_bonus: Any, alloc: Any, stat: str, points: int, *,
               level: Any, cfg: Mapping[str, Any],
               essence_balance: Optional[int] = None) -> Dict[str, Any]:
    """淬炼可行性校验（纯函数；报告 §2.3 V8/V9/V10/V11 的引擎侧对应）。

    出参：{ok, reason?, message?, cost, cap}。reason ∈
      disabled / stat_not_allowed / invalid_points / per_stat_cap / total_cap / not_enough_essence。
    """
    if not cfg.get("enabled"):
        return {"ok": False, "reason": "disabled", "message": "淬炼未启用"}
    n = _as_int(points)
    if n is None or n < 1:
        return {"ok": False, "reason": "invalid_points", "message": "淬炼点数须为正整数"}
    if str(stat) not in allowed_stats_of(stats_bonus, cfg):
        return {"ok": False, "reason": "stat_not_allowed",
                "message": f"属性「{stat}」不可淬炼"}
    cap = total_cap_of(level, cfg)
    used = alloc_total(alloc)
    pcap = per_stat_cap_of(str(stat), cap, cfg)
    cur = (_as_int(alloc.get(str(stat))) or 0) if isinstance(alloc, Mapping) else 0
    if cur < 0:
        cur = 0
    if cur + n > pcap:
        return {"ok": False, "reason": "per_stat_cap",
                "message": f"单项上限 {pcap}（已投 {cur}，本次 +{n}）",
                "cap": {"per_stat": pcap, "used": cur}}
    if used + n > cap:
        return {"ok": False, "reason": "total_cap",
                "message": f"总上限 {cap}（已投 {used}，本次 +{n}）",
                "cap": {"total": cap, "used": used}}
    cost = temper_cost(str(stat), used, cap, n, cfg)
    if essence_balance is not None:
        try:
            bal = int(essence_balance)
        except (TypeError, ValueError):
            bal = 0
        if bal < cost["essence"]:
            return {"ok": False, "reason": "not_enough_essence",
                    "message": f"精粹不足（需 {cost['essence']}，持有 {bal}）", "cost": cost}
    return {"ok": True, "reason": None, "stat": str(stat), "points": n,
            "cost": cost, "cap": {"total": cap, "used": used, "per_stat": pcap}}


def plan_temper(stats_bonus: Any, alloc: Any, stat: str, points: int, *,
                level: Any, cfg: Mapping[str, Any],
                essence_balance: Optional[int] = None) -> Dict[str, Any]:
    """淬炼计划（纯函数）：校验 → 新分配 → 属性增量 → 消耗。**不落账**。

    出参（ok）：{ok, stat, points, new_alloc, new_total, delta, cost, cap}。
    """
    chk = can_temper(stats_bonus, alloc, stat, points, level=level, cfg=cfg,
                     essence_balance=essence_balance)
    if not chk.get("ok"):
        return chk
    n = int(chk["points"])
    cur = (_as_int(alloc.get(str(stat))) or 0) if isinstance(alloc, Mapping) else 0
    if cur < 0:
        cur = 0
    new_alloc: Dict[str, int] = {}
    if isinstance(alloc, Mapping):
        for k, v in alloc.items():
            i = _as_int(v)
            if i is not None and i > 0:
                new_alloc[str(k)] = i
    new_alloc[str(stat)] = cur + n
    vpp = value_per_point_of(str(stat), cfg)
    delta = float(vpp) * n
    return {
        "ok": True, "reason": None, "stat": str(stat), "points": n,
        "new_alloc": new_alloc, "new_total": alloc_total(new_alloc),
        "delta": delta, "cost": chk["cost"], "cap": chk["cap"],
    }


def reset_alloc(alloc: Any, cfg: Mapping[str, Any]) -> Dict[str, Any]:
    """重置淬炼分配（决策记录 §5 D2 建议：**可重置不返还**）。

    出参 {ok, reason?, new_alloc}：`reset_allowed=False` → 拒绝；否则清空分配、
    **不返还任何精粹**（返还口径见 `temper_refund`，仅作用于分解，不在重置）。
    """
    if not cfg.get("enabled"):
        return {"ok": False, "reason": "disabled", "message": "淬炼未启用", "new_alloc": {}}
    if not cfg.get("reset_allowed", True):
        return {"ok": False, "reason": "reset_forbidden", "message": "该配置不允许重置",
                "new_alloc": dict(alloc) if isinstance(alloc, Mapping) else {}}
    return {"ok": True, "reason": None, "new_alloc": {}, "refund": 0}


def materialize_temper(stats_bonus: Any, old_alloc: Any, new_alloc: Any,
                       cfg: Mapping[str, Any]) -> Dict[str, float]:
    """把淬炼分配**幂等**物化进 `stats_bonus`（报告 §2.2C/§5 D9(a)）。

    口径：`新值 = 旧值 + (value(new_alloc[stat]) − value(old_alloc[stat]))`，
    其中 `value(a) = a × value_per_point`。以 `temper_alloc` 为唯一事实源 →
    重放同一操作（old==new）时增量为 0，不双计；只有分配真正变化才改 `stats_bonus`。

    入参 stats_bonus/old_alloc/new_alloc：Mapping（实例当前值 / 变更前分配 / 变更后分配）。
    出参：新的 `stats_bonus` dict（不原地改入参）。**不改 `enhance_level`**（分账）。
    """
    sb: Dict[str, float] = {}
    if isinstance(stats_bonus, Mapping):
        for k, v in stats_bonus.items():
            n = _num(v)
            sb[str(k)] = float(n) if n is not None else 0.0
    vpp = float(cfg.get("value_per_point") or 1.0)
    keys = set()
    if isinstance(old_alloc, Mapping):
        keys |= {str(k) for k in old_alloc.keys()}
    if isinstance(new_alloc, Mapping):
        keys |= {str(k) for k in new_alloc.keys()}
    for stat in keys:
        a_old = (_as_int(old_alloc.get(stat)) or 0) if isinstance(old_alloc, Mapping) else 0
        a_new = (_as_int(new_alloc.get(stat)) or 0) if isinstance(new_alloc, Mapping) else 0
        if a_old < 0:
            a_old = 0
        if a_new < 0:
            a_new = 0
        if a_old == a_new:
            continue  # 幂等：分配未变的属性完全不触碰
        d_old = a_old * vpp
        d_new = a_new * vpp
        base = float(sb.get(stat, 0.0) or 0.0)
        sb[stat] = base + (d_new - d_old)
    return sb


# ---------------------------------------------------------------------------
# 精粹产出（报告 §3.1 / §3.4；主 agent ①/② 裁定）
# ---------------------------------------------------------------------------
def essence_color_order(quality: Any, cfg: Mapping[str, Any],
                        declared_colors: Optional[Sequence[Any]] = None) -> int:
    """品质 → 色序（报告 §3.1 color_order；缺省按内容包 `quality_colors` 声明顺序派生）。

    优先级：`essence_rate.color_order[品质]` 显式覆盖 → `declared_colors`（内容包品质颜色
    列表顺序）下标 → 0（未知品质按最低色序）。
    """
    q = str(quality) if quality is not None else ""
    override = cfg.get("color_order")
    if isinstance(override, Mapping) and override.get(q) is not None:
        i = _as_int(override.get(q))
        if i is not None and i >= 0:
            return i
    if declared_colors:
        for idx, c in enumerate(declared_colors):
            cid = c.get("id") if isinstance(c, Mapping) else c
            if str(cid) == q:
                return idx
    return 0


def essence_base(value: Any, color_index: Any, cfg: Mapping[str, Any],
                 grade: Any = None) -> int:
    """精粹基础产出（报告 §3.1A，**主 agent ① 采用本公式**）：

        `产出 = round(投入价值 V × k1 × k2' × β^色序)`（整体取整一次）

    `k2'` = `grade_of[图纸档]`（命中）否则 `k2`。β 为**正向**系数（缺省 1.2）。
    """
    v = _num(value)
    if v is None or v <= 0:
        return 0
    k1 = _num(cfg.get("k1")) or 0.0
    k2 = _num(cfg.get("k2")) or 0.0
    grade_of = cfg.get("grade_of")
    if grade is not None and isinstance(grade_of, Mapping) and grade_of.get(str(grade)) is not None:
        gk = _num(grade_of.get(str(grade)))
        if gk is not None:
            k2 = gk
    beta = _num(cfg.get("beta"))
    if beta is None or beta < 0:
        beta = 1.0
    ci = _as_int(color_index) or 0
    if ci < 0:
        ci = 0
    raw = v * k1 * k2 * (beta ** ci)
    out = _apply_rounding(raw, cfg.get("rounding"))
    cap = cfg.get("cap_per_item")
    ci_cap = _as_int(cap)
    if ci_cap is not None and ci_cap >= 0 and out > ci_cap:
        out = ci_cap
    return max(0, out)


def temper_refund(points: Any, total_cap: Any, cfg: Mapping[str, Any]) -> int:
    """淬炼返还（报告 §3.4A/G6 + **主 agent ② 真闸门**）：

        每点实际返还率 = `temper_refund × refund_decay^(已投点/总上限)`
        返还 = floor(已投点 × 每点实际返还率)

    随淬炼量**单调下降**；且 `temper_refund < cost_per_point.essence` ⇒ 每轮
    「淬炼→分解」净损 → 不可套利（数值证据见 `simulate_cycle` / 测试 D/E 组）。
    """
    p = _as_int(points) or 0
    if p <= 0:
        return 0
    per_point = _as_int(cfg.get("temper_refund")) or 0
    if per_point <= 0:
        return 0
    decay = _num(cfg.get("refund_decay"))
    if decay is None or decay < 0:
        decay = 0.0
    if decay > 1.0:
        decay = 1.0
    cap = _as_int(total_cap) or 0
    frac = (p / cap) if cap > 0 else 0.0
    eff = per_point * (decay ** frac)
    return max(0, _apply_rounding(p * eff, cfg.get("rounding")))


def essence_for_instance(*, value: Any, quality: Any, grade: Any = None,
                         temper_points: Any = 0, total_cap: Any = 0,
                         cfg: Mapping[str, Any],
                         declared_colors: Optional[Sequence[Any]] = None) -> Dict[str, int]:
    """单件分解精粹产出 = 基础产出 + 淬炼返还（报告 §3.1A 完整式）。

    出参 {base, refund, total}（全部非负 int）。
    """
    ci = essence_color_order(quality, cfg, declared_colors)
    base = essence_base(value, ci, cfg, grade)
    refund = temper_refund(temper_points, total_cap, cfg)
    return {"base": base, "refund": refund, "total": base + refund, "color_index": ci}


# ---------------------------------------------------------------------------
# 经济推演（报告 §4；主 agent ①/② 必给证据）
# ---------------------------------------------------------------------------
def typical_cycle(*, value: Any, k_ratio_note: bool = True, decompose_count: int = 95,
                  temper_count: int = 5, color_index: int = 0,
                  level: int = 35, cfg_temper: Optional[Mapping[str, Any]] = None,
                  cfg_essence: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    """「典型玩家经济循环」推演：打造 N 件 → 分解 95 件 → 精粹 → 满淬 5 件。

    口径（报告 §4.1/§4.4/§4.6）：分解 95 件（白装 V=毕业武器）↔ 满淬 5 件（总上限
    210 点/件，等级 35 × 6）。出参给出**产出/消耗比**——按 1593 默认应为 ≈ 1.00×
    （报告 p=1 时为 1593×；其反解即 `cost_per_point.essence`），证明不再是 84:1。
    """
    tc = _norm_t(cfg_temper)
    ec = _norm_e(cfg_essence)
    cap = total_cap_of(level, tc)
    per_item = essence_base(value, color_index, ec, None)
    produced = per_item * max(0, int(decompose_count))
    unit = (tc.get("cost_per_point") or {}).get("essence") or 0
    consumed = max(0, int(temper_count)) * cap * int(unit)
    ratio = (produced / consumed) if consumed > 0 else None
    return {
        "value": float(value or 0),
        "cap": cap,
        "per_item_essence": per_item,
        "decompose_count": int(decompose_count),
        "produced": produced,
        "temper_count": int(temper_count),
        "cost_per_point": int(unit),
        "consumed": consumed,
        "ratio": ratio,
        "balance_point_p": (
            (produced / (max(0, int(temper_count)) * cap))
            if cap > 0 and temper_count > 0 else None
        ),
    }


def simulate_cycle(*, rounds: int = 20, value: Any = 0.0, color_index: int = 0,
                   level: int = 35,
                   decompose_per_round: int = 1, temper_per_round: int = 1,
                   cfg_temper: Optional[Mapping[str, Any]] = None,
                   cfg_essence: Optional[Mapping[str, Any]] = None,
                   start_essence: int = 0) -> Dict[str, Any]:
    """N 轮「分解 → 淬炼 → 再分解」循环模拟（**纯函数、可复现**；主 agent ② 必给证据）。

    每轮：分解 `decompose_per_round` 件**新**件得基础精粹 B；对 `temper_per_round` 件
    满淬（消耗 C = 上限 × 每点）；再分解这些已淬件（得 B + 返还 R）。净变化
    `delta = m·B + k·(B + R) − k·C`。默认基线下 `delta < 0` 且 R 的**每点返还率随投入下降**
    → 余额单调递减、无套利。出参含逐轮明细（供测试/报告贴数值）。
    """
    tc = _norm_t(cfg_temper)
    ec = _norm_e(cfg_essence)
    cap = total_cap_of(level, tc)
    unit = int((tc.get("cost_per_point") or {}).get("essence") or 0)
    base = essence_base(value, color_index, ec, None)
    refund_full = temper_refund(cap, cap, ec)
    cost_full = cap * unit
    m = max(0, int(decompose_per_round))
    k = max(0, int(temper_per_round))
    balance = int(start_essence)
    rows: List[Dict[str, Any]] = []
    for r in range(1, max(0, int(rounds)) + 1):
        essence_in = m * base + k * (base + refund_full)
        essence_out = k * cost_full
        delta = essence_in - essence_out
        balance += delta
        rows.append({
            "round": r,
            "essence_in": essence_in,
            "essence_out": essence_out,
            "delta": delta,
            "balance": balance,
            "refund_full": refund_full,
            "cost_full": cost_full,
        })
    # 每点返还率随投入比例下降（真闸门证据）：满淬/半淬/25% 三档
    rp = []
    for frac in (0.25, 0.5, 1.0):
        p = int(round(cap * frac))
        rr = temper_refund(p, cap, ec)
        rp.append({
            "frac": frac, "points": p, "refund": rr,
            "cost": p * unit,
            "per_point": (rr / p) if p > 0 else 0.0,
            "ratio": (rr / (p * unit)) if p > 0 and unit > 0 else 0.0,
        })
    return {
        "cap": cap, "cost_per_point": unit, "base_per_item": base,
        "refund_full": refund_full, "cost_full": cost_full,
        "per_round_delta": (m * base + k * (base + refund_full)) - k * cost_full,
        "balance_start": int(start_essence), "balance_end": balance,
        "monotonic_decrease": all(rows[i]["balance"] < rows[i - 1]["balance"]
                                  for i in range(1, len(rows))) if len(rows) > 1 else True,
        "rows": rows, "refund_curve": rp,
    }
