"""批45 · 装备占比校准 —— 面板预算 / 怪物数值倍率参数化（唯一落点）。

依据：`docs/深度打造_决策记录.md` **§三 补充 1**（用户 2026-09-19 拍板 + 主 agent 执行口径）。
上游模型：`docs/veinborn_阶段一_数值模型_1-35_v2.md:32`（面板 = 白值 7 : 装备 8 : buff 5）。
对照口径：`docs/审查参考/战斗数值层设计定稿.md`（三档推演：无buff下限 / 半buff中值 / 满buff上限）。

本模块提供「读时参数化」，不改任何落档数值：

- **面板预算**（`settings.panel_budget`）：
  `white : equip : buff` 为设计预算份；**装备面板倍率** `equip_stat_mult` 乘在装备这一份上。
  装备预算占比 = `equip×equip_stat_mult / (white + equip×equip_stat_mult + buff)`。
  现状 `7:8:5` → 装备 40%；校准 `equip_stat_mult = 2.25` → `7:18:5` → 装备 **60%**、
  面板总功率 ×1.5。
  白值份与 buff 份**冻结**（白值/buff 绝对数值不动）。

- **装备面板轴**（`PANEL_AXIS_KEYS`）：`equip_stat_mult` 只作用于面板轴 `atk/dfn/hp` 的装备加成
  （flat 与对应 pct 词条）。**不作用于** `crit / earplug / super_crit_lv / elem_crit_lv`
  等战斗直读词条（`data.gear_stats.GEAR_COMBAT_KEYS`）与其余属性 ——
  故暴击/命中/格挡参数逐字段不变（决策记录：不得改暴击参数）。

- **怪物数值倍率**（`settings.monster_scaling`）：
  `hp_mult / atk_mult` 按面板总功率比例（+50%）同步；`con` 因防御系数 `K/(con+K)` 非线性，
  按「斩杀回合不变式」做**仿射补偿** `con' = (con+K)×def_factor − K`（`K = def_k`），
  使中值档斩杀回合逐只不变；`def_factor=1.0` = 现状（不动防御）。

缺省 / 未配置 / 非映射 → 全部 1.0，与本批引入前**逐字段一致**（回归零影响）。
本模块属 core 层：零 NoneBot import、零 content import、纯函数、类型标注完整。

- **特效强度预算**（`settings.effect_budget`，批55 · 特效强度预算；设计
  `docs/特效强度预算_设计.md` §二方案 B + §三推荐）：
  面板三轴（`PANEL_AXIS_KEYS`）只覆盖 `atk/dfn/hp`，特效轴（`data.gear_stats.GEAR_EFFECT_KEYS`
  + COMBAT 档的吸血/免伤）**不进 60% 装备占比校准**，会抬高真实战力而不进 `equip_share`。
  本段提供**另立上限**（不改任何战斗数值）：等价权表 `EFFECT_AXIS_WEIGHTS`（坐标表，
  `等效% = 轴值 / 校准点 × 校准等效%`）→ 聚合器 `effect_equiv` → 按档位 `cap_equiv_pct ×
  tier_mult[tier]` 判超限 → `gate_mode`（off/warn/red）决定**拒绝/黄提示/静默**；
  外加 A1 度量 `effective_equip_share`（只报数不改数，与 `equip_share` 并列）。
  **每轴上下钳**仍由 `settings.effect_axes`（批50/52）承担。缺省整段不存在 → `enabled=false`
  → 聚合器返回 0、gate 静默 → 与引入前**逐字段一致**。

- **怪物特效补偿**（`settings.monster_scaling.effect_hp_mult / effect_atk_mult`，方案 C 备用）：
  缺省 **1.0 = 现状**；给「特效渗透率接近 100% / 出现失控 build」时留一条改回 1.0 即回滚的
  应急杠杆，本批**不配置即不存在**。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from qbot_rpg.data.gear_stats import (
    DEFAULT_EFFECT_BUDGET,
    EFFECT_AGGREGATES,
    EFFECT_AXIS_WEIGHTS,
    EFFECT_BUDGET_KEY,
    EFFECT_GATE_MODES,
    EFFECT_UNKNOWN_MODES,
    PANEL_AXIS_STEMS,
    check_effect_budget,
    effect_cap_pct,
    effect_equiv,
    effect_values_of,
    normalize_effect_budget,
)

__all__ = [
    "PANEL_BUDGET_KEY",
    "MONSTER_SCALING_KEY",
    "EFFECT_BUDGET_KEY",
    "DEFAULT_PANEL_BUDGET",
    "DEFAULT_MONSTER_SCALING",
    "DEFAULT_EFFECT_BUDGET",
    "EFFECT_AXIS_WEIGHTS",
    "EFFECT_GATE_MODES",
    "EFFECT_UNKNOWN_MODES",
    "EFFECT_AGGREGATES",
    "PANEL_AXIS_KEYS",
    "DEFAULT_DEF_K",
    "normalize_panel_budget",
    "normalize_monster_scaling",
    "normalize_effect_budget",
    "equip_share",
    "effective_equip_share",
    "effect_values_of",
    "effect_equiv",
    "effect_cap_pct",
    "check_effect_budget",
    "scale_panel_bonus",
    "scale_monster_con",
]

#: `settings` 下的配置键（包声明驱动；缺省不注入 = 现状）。
PANEL_BUDGET_KEY = "panel_budget"
MONSTER_SCALING_KEY = "monster_scaling"

#: 面板轴（装备倍率作用键；7:8:5 预算的数值轴）。
#: 批50：唯一源上移到 `data/gear_stats.PANEL_AXIS_STEMS`（data 层）——使 content 层校验器
#: 能红拦「特效轴键名撞面板轴 stem」**而不必** content→core 反向依赖；本处保持同名导出，
#: 值与语义不变（`core/panel_budget.PANEL_AXIS_KEYS` 仍是既有调用方的唯一入口）。
PANEL_AXIS_KEYS: Tuple[str, ...] = tuple(PANEL_AXIS_STEMS)

#: 防御系数 K 缺省（`docs/审查参考/战斗数值层设计定稿.md` §5.1 defense.k = 100）。
DEFAULT_DEF_K: float = 100.0

DEFAULT_PANEL_BUDGET: Dict[str, float] = {
    "white": 7.0,
    "equip": 8.0,
    "buff": 5.0,
    "equip_stat_mult": 1.0,
}

DEFAULT_MONSTER_SCALING: Dict[str, float] = {
    "hp_mult": 1.0,
    "atk_mult": 1.0,
    "def_factor": 1.0,
    "def_k": DEFAULT_DEF_K,
    # 批55 · 方案 C 备用杠杆（缺省 1.0 = 现状；不配置即不存在）。
    "effect_hp_mult": 1.0,
    "effect_atk_mult": 1.0,
}

#: 批55 · 特效强度预算（`settings.effect_budget`）：常量与纯函数**唯一源在
#: `data/gear_stats`**（content 校验器需读本段，架构矩阵 `content → {data}` 禁 content→core；
#: 对齐批50 把 `PANEL_AXIS_STEMS` 落 data 层的同一取舍）。本模块**再导出**同名符号
#: （`EFFECT_BUDGET_KEY` / `EFFECT_AXIS_WEIGHTS` / `DEFAULT_EFFECT_BUDGET` /
#: `normalize_effect_budget` / `effect_values_of` / `effect_equiv` / `effect_cap_pct` /
#: `check_effect_budget`），使 core/commands 调用方入口不变；另在本层给出
#: `effective_equip_share`（A1 度量，需读 `panel_budget` 面板份）。


def _as_mapping(cfg: Any) -> Mapping[str, Any]:
    return cfg if isinstance(cfg, Mapping) else {}


def _num(cfg: Mapping[str, Any], key: str, default: float) -> float:
    v = cfg.get(key, default)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return float(default)
    fv = float(v)
    if fv < 0.0:
        return float(default)
    return fv


def normalize_panel_budget(cfg: Any) -> Dict[str, float]:
    """`settings.panel_budget` → 数值字典（缺省/非法回落；份 ≥0，倍率 ≥0）。

    非映射/缺键 → 缺省现状（1.0）→ 引擎零变化。
    """
    m = _as_mapping(cfg)
    out = dict(DEFAULT_PANEL_BUDGET)
    for key in ("white", "equip", "buff"):
        out[key] = max(0.0, _num(m, key, DEFAULT_PANEL_BUDGET[key]))
    out["equip_stat_mult"] = max(0.0, _num(
        m, "equip_stat_mult", DEFAULT_PANEL_BUDGET["equip_stat_mult"]))
    return out


def normalize_monster_scaling(cfg: Any) -> Dict[str, float]:
    """`settings.monster_scaling` → 数值字典（缺省/非法回落；倍率 ≥0）。"""
    m = _as_mapping(cfg)
    out = dict(DEFAULT_MONSTER_SCALING)
    out["hp_mult"] = max(0.0, _num(m, "hp_mult", DEFAULT_MONSTER_SCALING["hp_mult"]))
    out["atk_mult"] = max(0.0, _num(m, "atk_mult", DEFAULT_MONSTER_SCALING["atk_mult"]))
    out["def_factor"] = max(0.0, _num(
        m, "def_factor", DEFAULT_MONSTER_SCALING["def_factor"]))
    out["def_k"] = max(0.0, _num(m, "def_k", DEFAULT_MONSTER_SCALING["def_k"]))
    out["effect_hp_mult"] = max(0.0, _num(
        m, "effect_hp_mult", DEFAULT_MONSTER_SCALING["effect_hp_mult"]))
    out["effect_atk_mult"] = max(0.0, _num(
        m, "effect_atk_mult", DEFAULT_MONSTER_SCALING["effect_atk_mult"]))
    return out


def effective_equip_share(budget: Any, effect_pct: float = 0.0) -> float:
    """A1 · 度量式真实装备占比（**只报数、不改数**）：`e / (pool + u)`。

    `pool = white + equip×mult + buff`（面板总功率份）；`u = 特效综合等效% / 100 × pool`
    （`docs/特效强度预算_设计.md` §1.4：`u = (综合倍率 − 1) × pool`，`真实占比 = e/(pool+u)`）。
    `effect_pct <= 0` / 非法 → 退化为 `equip_share`（两者口径一致）。
    """
    b = normalize_panel_budget(budget)
    e = b["equip"] * b["equip_stat_mult"]
    pool = b["white"] + e + b["buff"]
    if pool <= 0.0:
        return 0.0
    pct = 0.0
    if isinstance(effect_pct, (int, float)) and not isinstance(effect_pct, bool):
        pct = max(0.0, float(effect_pct))
    denom = pool + pct / 100.0 * pool
    if denom <= 0.0:
        return 0.0
    return e / denom


def equip_share(budget: Mapping[str, Any]) -> float:
    """装备预算占比 = `equip×mult / (white + equip×mult + buff)`（分母 ≤0 → 0.0）。

    现状 7:8:5 → 0.40；校准 equip×2.25 → 18/30 = 0.60。
    """
    b = normalize_panel_budget(budget)
    e = b["equip"] * b["equip_stat_mult"]
    denom = b["white"] + e + b["buff"]
    if denom <= 0.0:
        return 0.0
    return e / denom


def scale_panel_bonus(
    flat: MutableMapping[str, float],
    pct: MutableMapping[str, float],
    mult: float,
    axis_keys: Sequence[str] = PANEL_AXIS_KEYS,
) -> None:
    """把装备面板轴加成乘以 `mult`（原地；mult == 1.0 时不触碰 → 回归零影响）。

    flat 键 = `atk/dfn/hp`；pct 键 = 去掉 `_pct` 后缀后的同名 stem。
    其余键（属性/战斗直读词条）**不动**。
    """
    if not mult or mult == 1.0:
        return
    for key in axis_keys:
        k = str(key)
        if k in flat:
            try:
                flat[k] = float(flat[k]) * float(mult)
            except (TypeError, ValueError):
                continue
        if k in pct:
            try:
                pct[k] = float(pct[k]) * float(mult)
            except (TypeError, ValueError):
                continue


def scale_monster_con(con: Any, factor: float, k: float = DEFAULT_DEF_K) -> float:
    """怪物防御（体质）仿射补偿：`con' = (con + K) × factor − K`（factor==1.0 → 原值）。

    使「防御系数 × 攻击」的比值可按斩杀回合不变式精确控制（K 非线性项补偿）。
    """
    try:
        c = float(con)
    except (TypeError, ValueError):
        c = 0.0
    if not factor or factor == 1.0:
        return c
    return max(0.0, (c + float(k)) * float(factor) - float(k))
