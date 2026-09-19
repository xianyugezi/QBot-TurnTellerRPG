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
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Sequence, Tuple

from qbot_rpg.data.gear_stats import PANEL_AXIS_STEMS

__all__ = [
    "PANEL_BUDGET_KEY",
    "MONSTER_SCALING_KEY",
    "DEFAULT_PANEL_BUDGET",
    "DEFAULT_MONSTER_SCALING",
    "PANEL_AXIS_KEYS",
    "DEFAULT_DEF_K",
    "normalize_panel_budget",
    "normalize_monster_scaling",
    "equip_share",
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
}


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
    return out


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
