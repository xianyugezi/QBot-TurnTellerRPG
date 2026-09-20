"""批57 · 淬炼（temper）与精粹经济（essence）的**键空间与默认值唯一源**。

文件：qbot_rpg/data/temper_stats.py
定位：data 层纯数据模块（零 import、零 IO——同 `data/gear_stats.py`）；
  content 层（`content/enhance_models.py` / `content/forge_settings.py` 的字段表与默认值）
  与 core 层（`core/temper.py` / `core/decompose.py` 的纯引擎）**共用本文件一份默认值**，
  避免「默认值抄两份必漂移」。G0 依赖矩阵：content→{data}、core→{data} 均合法，
  故默认值落 data 层而非 content/core。

依据：
  - `/root/deliverables/淬炼与分解回收_实现口径.md` §2.3（淬炼参数表）/ §3.1（精粹产出公式）
    / §3.4（经济风险与闸门）/ §4.6（反解平衡点）/ §5 D 组（待裁决建议默认）。
  - `/root/deliverables/打造系统_原案_20260919.md` §10（淬炼）/ §14（回收率待定）
    / §12（精粹来自分解）。
  - `docs/深度打造_决策记录.md` §二 **N5**（回收率口径）+ §三 补充 1 + §十五 D 组
    （**D1 百分点口径**、**全部可配**）。
  - 主 agent 本批两处数值裁定：① 84:1 失衡 → 产出侧用报告公式、消耗侧按 §4.6 反解平衡点
    约 **1593 精粹/点**；② `β^色序` 闸门无效 → β 降为「品质越高单件回收价值越高」的**正向**
    系数（默认 1.2），真闸门 = **淬炼投入不可逆 + 分解返还随淬炼量衰减**（`refund_decay`）。

【口径与数值依据（全部可配，不写死）】
  * `cost_per_point.essence = 1593` 依据：报告 §4.6 反解——「分解 95 件白装（V=100600，
    k1=0.35/k2=0.50）↔ 满淬 5 件（总上限 210 点/件）」的平衡方程
    `95 × V·k1·k2 = 5 × 210 × p` → `p = 1672475 / 1050 ≈ 1593`。取 1593 使
    **典型循环产出/消耗 ≈ 1.00×**（原 p=1 时 1593×，即报告 C-6 的 84:1～1593× 失衡）。
    该校准锚点是「打造 100 件 → 分解 95 件 → 精粹 → 满淬 5 件」，非全局最优平衡。
  * `beta = 1.2`（正向）依据：主 agent 裁定 C-7——原 β=0.6 的衰减只作用在**不会被分解**的
    高色序件上，对精粹供给无效；本批 β 只作「品质越高单件回收价值越高」的正向系数，
    闸门职责交给「不可逆 + 返还衰减」。白装（色序 0）`β⁰=1` → 上述 1593 平衡点不受影响。
  * `temper_refund = 800` / `refund_decay = 0.5` 依据：报告 §3.4A 证明 `temper_refund`
    **必须 < `cost_per_point.essence`**（否则精粹侧可无限套利）；800 ≈ 50%×1593，
    再乘随投入比例衰减的 `decay^frac` → 实际每点返还率随淬炼量**单调下降**
    （满淬时 400 ≈ 25%×1593），从机制上堵死「淬炼→分解→再淬炼」循环。
  * 全部键可被内容包 `enhance.json → temper` / `settings.forge → essence_rate` 覆盖。

【缺省零变化】`temper.enabled = False`、`essence_rate.enabled = False` → 引擎不消费本段，
  与批57 引入前逐字段一致（对拍见测试 A 组）。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Tuple

__all__ = [
    "DEFAULT_TEMPER",
    "DEFAULT_ESSENCE_RATE",
    "TEMPER_VALUE_TYPES",
    "TEMPER_ROUNDINGS",
    "ESSENCE_V_BASES",
    "ESSENCE_SCOPES",
    "normalize_temper_config",
    "normalize_essence_config",
]

#: 淬炼数值类型（报告 §2.3 value_type）：flat = 白值加算；pct = 百分点（走 `_pct` 分层）。
TEMPER_VALUE_TYPES: Tuple[str, ...] = ("flat", "pct")

#: 取整口径（报告 §3.1C rounding）：对齐既有 `gem_wallet.py` 的 floor 风格，但**整体只取整一次**。
TEMPER_ROUNDINGS: Tuple[str, ...] = ("floor", "round", "ceil")

#: 投入价值 V 的口径（报告 §3.1B）：蓝图节点固定材料价值（V1）/ 物品定义 price /
#: 固定常量 / 按装备等级线性。缺省 V1（node_materials）——报告建议、且当前可算。
ESSENCE_V_BASES: Tuple[str, ...] = ("node_materials", "item_price", "fixed", "level_scaled")

#: 分解对象范围（报告 §3.4 G2）：仅打造装备 / 所有装备。仅打造 = 防「商店廉价装刷精粹」。
ESSENCE_SCOPES: Tuple[str, ...] = ("crafted_equipment", "all_equipment")

# ---------------------------------------------------------------------------
# 淬炼默认配置（enhance.json → temper 段的默认值；内容包可逐键覆盖）
# ---------------------------------------------------------------------------
DEFAULT_TEMPER: Dict[str, Any] = {
    # 启用开关（缺省 False = 与现状逐字段一致；报告 §2.3 / 决策记录「缺省=现状」）
    "enabled": False,
    # ---- 上限（报告 §2.1 R1/R3/R4；原案 §10「根据装备等级获得淬炼上限值」）----
    # 总值上限 = 装备等级 × cap_per_level（乘性公式，可配系数；报告 T-A4）
    "cap_per_level": 6,
    # 显式绝对值覆盖（优先于乘性公式）；None = 走公式
    "total_cap": None,
    # 逐级覆盖表 {等级: 上限}（优先于公式、低于 total_cap 绝对值）
    "total_cap_by_level": {},
    # 单项上限比例（相对总值；报告 D7 建议 0.5）——=1.0 会让「规划空间」归零
    "per_stat_cap_ratio": 0.5,
    # 逐属性单项上限覆盖 {属性键: 上限}
    "per_stat_cap": {},
    # 可淬炼属性（空 = 该实例现有属性键 ∩ GEAR_NUMERIC_KEYS；仍空则回退 GEAR_FLAT_KEYS）
    "allowed_stats": [],
    # ---- 数值（报告 §2.3；每点加值口径为本批工程补白）----
    "value_type": "flat",
    "value_per_point": 1.0,
    # ---- 消耗（报告 §2.3；`cost_per_point.essence` 见文件头反解依据）----
    "cost_per_point": {"essence": 1593, "currency": 0},
    # 递增系数（报告 §3.4 G4 软闸门）：实际每点 = base × (1 + growth × 已投总点 / 总值上限)
    "cost_growth": 0.0,
    # 属性权重（报告 §2.3「让攻/防便宜、会心/穿透贵」）：**消耗**乘子（缺省全 1.0）
    "stat_weight": {},
    # 单次投入点数（报告 §2.3；>1 只是省指令，不改经济）
    "points_per_action": 1,
    # 实例无装备等级时的兜底等级（0 = 上限 0 = 不可淬炼，安全缺省）
    "default_level": 0,
    # 可重置不返还（决策记录 §5 D2 建议默认：(a) 可重置不返还）——可改
    "reset_allowed": True,
}

# ---------------------------------------------------------------------------
# 精粹产出默认配置（settings.forge → essence_rate 段的默认值）
# ---------------------------------------------------------------------------
DEFAULT_ESSENCE_RATE: Dict[str, Any] = {
    # 启用开关（缺省 False = 不启用精粹 → 与现状逐字段一致）
    "enabled": False,
    # 投入价值 V 口径（缺省 V1 = 蓝图节点固定材料价值；报告 §3.1B）
    "v_basis": "node_materials",
    "v_fixed": 0.0,          # v_basis="fixed" 时的常量
    "v_per_level": 0.0,      # v_basis="level_scaled" 时的每级价值
    # 材料价值基准系数 k1 / 图纸档基准系数 k2（决策记录 N5 区间中值）
    "k1": 0.35,
    "k2": 0.50,
    # 图纸档 → k2 覆盖（可配；空 = 统一用 k2）。键为内容包声明的图纸档 id。
    "grade_of": {},
    # 色序正向系数（主 agent C-7 裁定：品质越高单件回收价值越高；**不再承担闸门职责**）
    "beta": 1.2,
    # 色序映射覆盖（{品质色 id: 序}）；空 = 按 settings.deep_craft.quality_colors 声明顺序
    "color_order": {},
    # 取整（整体一次 floor/round/ceil）
    "rounding": "floor",
    # 淬炼返还（报告 §3.4 G6 / §5 D6）：**绝对**每点返还精粹，必须 < cost_per_point.essence；
    # 默认 800 ≈ 50%×1593。0 = 严格单向（报告建议值，可改回）。
    "temper_refund": 800,
    # 返还衰减系数（主 agent ② 裁定，本批真闸门）：每点实际返还 = temper_refund × decay^frac
    # （frac = 已投点 / 总值上限）→ 随淬炼量单调下降，堵死「淬炼→分解→再淬炼」。
    "refund_decay": 0.5,
    # 分解对象范围（报告 §3.4 G2）：仅打造装备（缺省）——防「商店/掉落廉价装刷精粹」。
    "scope": "crafted_equipment",
    # 单件产出上限（报告 §3.4 G5 软闸门；None = 不设）
    "cap_per_item": None,
    # 精粹货币键（报告 §5 D4 建议 = 货币载体）：须登记进内容包 `settings.currencies`，
    # 否则入账被拒（复刻 gem_wallet 的「货币键空间硬前置」）。
    "essence_currency": "essence",
}


# ---------------------------------------------------------------------------
# 配置归一（纯函数；data 层持有，使 content 字段表/默认值与 core 引擎**共用一份逻辑**，
# 满足 G0 依赖矩阵 content→{data} / core→{data}——content 不得 import core）
# ---------------------------------------------------------------------------
def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _num(v: Any) -> Any:
    return float(v) if _is_num(v) else None


def _as_int(v: Any) -> Any:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):  # pragma: no cover
        return None
    if f != int(f):
        return None
    return int(f)


def _deep_merge(defaults: Mapping[str, Any], raw: Any) -> Dict[str, Any]:
    """浅-深一层合并：dict 值深合并，其余显式覆盖（不改 raw）。"""
    out: Dict[str, Any] = {}
    for k, dv in defaults.items():
        rv = raw.get(k) if isinstance(raw, Mapping) else None
        if isinstance(dv, Mapping) and isinstance(rv, Mapping):
            merged = dict(dv)
            for kk, vv in rv.items():
                merged[str(kk)] = vv
            out[k] = merged
        elif rv is not None:
            out[k] = rv
        else:
            out[k] = dict(dv) if isinstance(dv, Mapping) else dv
    return out


def normalize_temper_config(raw: Any) -> Dict[str, Any]:
    """`enhance.json → temper` raw → 归一配置（缺键补默认、非法值回退，纯函数）。

    出参：与 `DEFAULT_TEMPER` 同构的 dict。raw 非 Mapping → 全默认。
    """
    cfg = _deep_merge(DEFAULT_TEMPER, raw)
    cfg["enabled"] = bool(raw.get("enabled")) if isinstance(raw, Mapping) else False
    cfg["reset_allowed"] = (
        bool(raw.get("reset_allowed"))
        if isinstance(raw, Mapping) and isinstance(raw.get("reset_allowed"), bool)
        else True
    )
    for k in ("cap_per_level", "default_level"):
        if _as_int(cfg.get(k)) is None or int(cfg[k]) < 0:
            cfg[k] = DEFAULT_TEMPER[k]
    tc = cfg.get("total_cap")
    if tc is not None and (_as_int(tc) is None or int(tc) < 0):
        cfg["total_cap"] = None
    ratio = _num(cfg.get("per_stat_cap_ratio"))
    if ratio is None or ratio < 0 or ratio > 1:
        ratio = float(DEFAULT_TEMPER["per_stat_cap_ratio"])
    cfg["per_stat_cap_ratio"] = ratio
    vtype = str(cfg.get("value_type") or "flat")
    cfg["value_type"] = vtype if vtype in TEMPER_VALUE_TYPES else "flat"
    vpp = _num(cfg.get("value_per_point"))
    cfg["value_per_point"] = float(vpp) if vpp is not None else 1.0
    cpp = cfg.get("cost_per_point")
    if not isinstance(cpp, Mapping):
        cpp = dict(DEFAULT_TEMPER["cost_per_point"])
    cfg["cost_per_point"] = {
        "essence": max(0, _as_int(cpp.get("essence")) or 0),
        "currency": max(0, _as_int(cpp.get("currency")) or 0),
    }
    growth = _num(cfg.get("cost_growth"))
    cfg["cost_growth"] = max(0.0, growth) if growth is not None else 0.0
    ppa = _as_int(cfg.get("points_per_action"))
    cfg["points_per_action"] = max(1, ppa) if ppa is not None else 1
    for k in ("total_cap_by_level", "per_stat_cap", "stat_weight"):
        if not isinstance(cfg.get(k), Mapping):
            cfg[k] = {}
    if not isinstance(cfg.get("allowed_stats"), (list, tuple)):
        cfg["allowed_stats"] = []
    return cfg


def normalize_essence_config(raw: Any) -> Dict[str, Any]:
    """`settings.forge → essence_rate` raw → 归一配置（缺键补默认、非法值回退）。"""
    cfg = _deep_merge(DEFAULT_ESSENCE_RATE, raw)
    cfg["enabled"] = bool(raw.get("enabled")) if isinstance(raw, Mapping) else False
    vb = str(cfg.get("v_basis") or "node_materials")
    cfg["v_basis"] = vb if vb in ESSENCE_V_BASES else "node_materials"
    for k in ("k1", "k2", "beta", "v_fixed", "v_per_level", "refund_decay"):
        v = _num(cfg.get(k))
        if v is None or v < 0:
            cfg[k] = DEFAULT_ESSENCE_RATE[k]
        else:
            cfg[k] = float(v)
    cfg["temper_refund"] = max(0, _as_int(cfg.get("temper_refund")) or 0)
    rnd = str(cfg.get("rounding") or "floor")
    cfg["rounding"] = rnd if rnd in TEMPER_ROUNDINGS else "floor"
    sc = str(cfg.get("scope") or "crafted_equipment")
    cfg["scope"] = sc if sc in ESSENCE_SCOPES else "crafted_equipment"
    cap = cfg.get("cap_per_item")
    cfg["cap_per_item"] = None if cap is None else max(0, _as_int(cap) or 0)
    cur = cfg.get("essence_currency")
    cfg["essence_currency"] = str(cur) if isinstance(cur, str) and cur else "essence"
    for k in ("grade_of", "color_order"):
        if not isinstance(cfg.get(k), Mapping):
            cfg[k] = {}
    return cfg
