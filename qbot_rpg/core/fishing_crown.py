"""M10 批3·路3B：冠级百分位生成与六档判定（qbot_rpg/core/fishing_crown.py）。

文件名：qbot_rpg/core/fishing_crown.py
创建时间：2026-08-31
作者：Hermes 子agent-3B（M10 钓鱼实现组批3·路3B：冠级六档 T11）

功能描述：
  - gen_size_weight(species, rng) -> dict：每次出鱼独立生成 size_pct / weight_pct
    （∈[0,100) 均匀分布，注入 rng）+ 线性插值 size / weight：
        size   = size_min   + (size_max   - size_min)   × (size_pct   / 100)
        weight = weight_min + (weight_max - weight_min) × (weight_pct / 100)
    边界：size_pct=0 → size_min；size_pct=99.99... 趋近 size_max（百分位不封 100）。
  - crown_of(size_pct, weight_pct, thresholds) -> str：六档判定——阈值参数化
    （reverse / silver / gold，默认 5/85/95，从 fishing_cfg 读）；判定顺序写死：
        逆金冠 → 大金冠 → 金冠 → 大银冠 → 银冠 → 普通
    逆金冠仅 size_pct < r 且 weight_pct < r（严格小于）；混合极端（如 size≥g 且
    weight<r）按金冠显示；银冠/金冠级判定用 >=（含边界）。

依据：
  - docs/细化/细化_2c1a_鱼种数据与冠级.md §二（2.1 百分位生成+线性插值 L98-109 /
    2.2 六档判定表 L111-122 / 2.3 判定顺序写死 L124-135 / 2.4 纯收藏 L137-141）
    + §六 TC-05~09 / TC-09b
  - docs/m10_shared_contract.md §一（crown_thresholds 默认 {reverse:5, silver:85,
    gold:95}，V2 序校验 0 < reverse < silver < gold < 100 归路0C）/ §五 铁律
  - 定稿 §2 冠级体系（L27-44）+ §四 冠级概率（L95）
  - docs/m10_接口摸底.md §九（rng 注入 ctx["rng"]、确定性、零定时器）
模式参考：
  - qbot_rpg/core/fishing_roll.py（批2 路2C：_resolve_rng 注入三态 + _weighted_pick
    确定性选一；fishing_cfg 三态容错）
  - qbot_rpg/core/fishing_settings.py（批0 路0A：fishing_cfg(ctx_or_settings)
    三态读段归一——本模块直接复用，零重写）

【工程补白】（契约/细化未显式定义处的实现口径，显式标注供审查）：
  C-1  入参形态：gen_size_weight 收 FishDef（批0 路0C 访问器 size_min/size_max/
       weight_min/weight_max）或任意 Mapping（含 size_min 等四键）双形态，容错
       读取（对齐 fishing._to_fishdef 防御口径）；缺键 → 默认 0 区间（size=0、
       weight=0 不炸，数据合法性由校验器 V1 硬拦）。
  C-2  rng 注入三态：参数 rng 优先 → ctx["rng"] → 兜底 random 模块（对齐
       fishing._resolve_rng / fishing_roll._resolve_rng 惯例）；测试一律注入固定
       种子 rng，生产装配层注入 ctx["rng"]。
  C-3  阈值入参三态：crown_of 的 thresholds 为显式 dict（测试直传）/ None /
       ctx（含 settings 或 fishing_cfg 键）→ 全部经 fishing_cfg 归一读段；缺省
       默认 {reverse:5, silver:85, gold:95}。crown_of 本体纯函数零 IO。
  C-4  输出中文档位名常量 CROWN_LABELS / CROWN_ORDER 供批4 图鉴冠级标注复用
       （best_crown 存档用英文键，见 2c1a §4.1 G-04）。
  C-5  size/weight 数值保留 4 位小数（1e-4 精度，批量结算浮点稳定）。
  C-6  阈值防御性归一：非数字/非正/乱序 → 回落默认三键（运行时兜底不炸；序
       校验 V2 归路0C 校验器硬拦，本模块只做读取容错）。

铁律：本文件零 NoneBot import、纯函数确定性、零 IO、零定时器/零睡眠调用、
      平台无关；docstring 不含计时器函数字面量（M43 探针，用「零定时器/零睡眠」
      措辞）；无 emoji。
"""

from __future__ import annotations

import random
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.content.fishing_models import FishDef
from qbot_rpg.core.fishing_settings import fishing_cfg

# =====================================================================================
# 常量：冠级六档（细化 §2.2 六档判定表 + 定稿 §2 L27-44）
# =====================================================================================

# 六档英文键（图鉴 best_crown 存档键，细化 §4.1 G-04；判定顺序即 CROWN_ORDER 序）
CROWN_REVERSE = "reverse"      # 逆金冠
CROWN_BIG_GOLD = "big_gold"    # 大金冠
CROWN_GOLD = "gold"            # 金冠
CROWN_BIG_SILVER = "big_silver"  # 大银冠
CROWN_SILVER = "silver"        # 银冠
CROWN_NORMAL = "normal"        # 普通

# 判定顺序（写死，不可配置——细化 §2.3 L124-135；顺序语义严格按序短路）
CROWN_ORDER: tuple = (
    CROWN_REVERSE,
    CROWN_BIG_GOLD,
    CROWN_GOLD,
    CROWN_BIG_SILVER,
    CROWN_SILVER,
    CROWN_NORMAL,
)

# 中文档位名（批4 图鉴冠级标注/结算文案复用；best_crown 存档用英文键）
CROWN_LABELS: Dict[str, str] = {
    CROWN_REVERSE: "逆金冠",
    CROWN_BIG_GOLD: "大金冠",
    CROWN_GOLD: "金冠",
    CROWN_BIG_SILVER: "大银冠",
    CROWN_SILVER: "银冠",
    CROWN_NORMAL: "普通",
}

# 默认阈值（细化 §2.1 L109 + 定稿 L75：reverse=5 / silver=85 / gold=95）
DEFAULT_CROWN_THRESHOLDS: Dict[str, int] = {
    "reverse": 5,
    "silver": 85,
    "gold": 95,
}

# 数值插值结果小数位（【工程补白 C-5】）
_SIZE_WEIGHT_ROUND = 4


# =====================================================================================
# 工具：数字/区间容错读取（对齐 fishing_models _num 防御口径）
# =====================================================================================
def _num(v: object) -> Optional[float]:
    """数字判定（int/float，排除 bool）；非数字 → None。"""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    return None


def _interval_of(species: object) -> Dict[str, float]:
    """从 FishDef / Mapping 读取四区间键（【工程补白 C-1】双形态容错）。

    返回 {size_min, size_max, weight_min, weight_max}；缺键/非数字 → 0（不炸，
    数据合法性由校验器 V1 硬拦）。
    """
    if isinstance(species, FishDef):
        vals = {
            "size_min": species.size_min,
            "size_max": species.size_max,
            "weight_min": species.weight_min,
            "weight_max": species.weight_max,
        }
    elif isinstance(species, Mapping):
        vals = {
            "size_min": species.get("size_min"),
            "size_max": species.get("size_max"),
            "weight_min": species.get("weight_min"),
            "weight_max": species.get("weight_max"),
        }
    else:
        vals = {}
    out: Dict[str, float] = {}
    for key in ("size_min", "size_max", "weight_min", "weight_max"):
        n = _num(vals.get(key))
        out[key] = n if n is not None else 0.0
    return out


# =====================================================================================
# 阈值读取（crown_of 阈值参数化；fishing_cfg 三态归一，C-3）
# =====================================================================================
def _thresholds_of(thresholds: object) -> Dict[str, int]:
    """阈值解析：显式 dict → 校验覆盖 → 回落默认三键（【工程补白 C-3/C-6】）。

    - thresholds 为 dict（含 reverse/silver/gold 键）→ 逐键读，非数字/非正回落
      默认；乱序不修正（V2 序校验归路0C 校验器）。
    - thresholds 为 ctx（含 settings / fishing_cfg 键）→ 经 fishing_cfg 归一读段。
    - None / 其它 → 默认 {reverse:5, silver:85, gold:95}。
    """
    raw: Mapping[str, object] = {}
    if isinstance(thresholds, Mapping):
        # ctx 形态（settings 全量 / fishing_cfg 段 / ctx 含 fishing 键）→ 归一读段
        if "settings" in thresholds or "fishing" in thresholds:
            cfg = fishing_cfg(thresholds)
            ct = cfg.get("crown_thresholds")
            if isinstance(ct, Mapping):
                raw = ct
        elif "fishing_cfg" in thresholds:
            # ctx 含 fishing_cfg 键：fishing_cfg 已归一为段形态（直接取 crown_thresholds）
            fcfg = thresholds["fishing_cfg"]
            if isinstance(fcfg, Mapping):
                ct = fcfg.get("crown_thresholds")
                if isinstance(ct, Mapping):
                    raw = ct
        elif all(k in thresholds for k in ("reverse", "silver", "gold")):
            raw = thresholds
    out: Dict[str, int] = dict(DEFAULT_CROWN_THRESHOLDS)
    for key in ("reverse", "silver", "gold"):
        v = raw.get(key)
        if isinstance(v, bool):
            continue
        if isinstance(v, (int, float)) and float(v) > 0:
            out[key] = int(v)
    return out


# =====================================================================================
# gen_size_weight：百分位生成 + 线性插值（细化 §2.1 L98-109，每次出鱼独立生成）
# =====================================================================================
def gen_size_weight(
    species: object,
    rng: Any = None,
    ctx: Optional[Mapping[str, Any]] = None,
) -> Dict[str, float]:
    """生成一次出鱼的尺寸/重量（百分位均匀 + 线性插值，确定性）。

    入参：
      species —— FishDef（批0 路0C 访问器）或 Mapping（含 size_min/size_max/
                 weight_min/weight_max 四键，【工程补白 C-1】双形态容错）。
      rng     —— 注入 rng（Random 实例，种子 42/2026）；None → ctx["rng"] →
                 random 模块兜底（【工程补白 C-2】，禁裸 random 破坏确定性）。
      ctx     —— 可选上下文（含 "rng" 键；None 可省略，测试直传 rng）。
    出参：
      {
        "size_pct": float,   # ∈[0,100) 均匀分布
        "weight_pct": float, # ∈[0,100) 均匀分布
        "size": float,       # 线性插值（4 位小数，C-5）
        "weight": float,     # 线性插值（4 位小数，C-5）
      }
    公式（细化 §2.1 L104-106）：
      size   = size_min   + (size_max   - size_min)   × (size_pct   / 100)
      weight = weight_min + (weight_max - weight_min) × (weight_pct / 100)
    边界：size_pct=0 → size_min；size_pct 趋近 100 → 趋近 size_max（不封 100）。

    确定性：同 seed 同 species 同调用序 → 恒同结果（每次出鱼独立生成两个百分位，
    不跨调用共享状态；TC-06/确定性重放）。
    """
    r = rng
    if r is None:
        r = ctx.get("rng") if isinstance(ctx, Mapping) else None
    if r is None:
        r = random  # 兜底 random 模块（对齐 fishing._resolve_rng 惯例）
    iv = _interval_of(species)
    size_pct = float(r.random()) * 100.0
    weight_pct = float(r.random()) * 100.0
    size = iv["size_min"] + (iv["size_max"] - iv["size_min"]) * (size_pct / 100.0)
    weight = iv["weight_min"] + (iv["weight_max"] - iv["weight_min"]) * (weight_pct / 100.0)
    return {
        "size_pct": size_pct,
        "weight_pct": weight_pct,
        "size": round(size, _SIZE_WEIGHT_ROUND),
        "weight": round(weight, _SIZE_WEIGHT_ROUND),
    }


# =====================================================================================
# crown_of：六档判定（阈值参数化 · 判定顺序写死 · 纯函数零 IO）
# =====================================================================================
def crown_of(
    size_pct: object,
    weight_pct: object,
    thresholds: Optional[Dict[str, int]] = None,
) -> str:
    """六档判定（细化 §2.2 判定表 + §2.3 顺序写死）。

    入参：
      size_pct   —— 大小百分位（0~100 开区间语义，理论 ∈[0,100)）。
      weight_pct —— 重量百分位。
      thresholds —— 阈值参数化（{reverse, silver, gold}，默认 5/85/95）：
                    ① 显式 dict（测试直传，如 {reverse:10, silver:80, gold:90}）；
                    ② ctx（含 settings / fishing_cfg / fishing 键）→ fishing_cfg
                       归一读段；③ None → 默认（【工程补白 C-3】）。
    出参：六档之一 "reverse"/"big_gold"/"gold"/"big_silver"/"silver"/"normal"
      （中文名见 CROWN_LABELS）。

    判定顺序（写死，严格按序短路——细化 §2.3 L124-135）：
      1. 逆金冠：仅 size_pct < r 且 weight_pct < r（严格小于；混合极端如 size≥g
         且 weight<r 不判逆金冠，继续下行）。
      2. 大金冠：size_pct ≥ g 且 weight_pct ≥ g。
      3. 金冠：size_pct ≥ g 或 weight_pct ≥ g（单边达金冠级；含一边 ≥g 一边 <r
         的混合极端按金冠显示）。
      4. 大银冠：size_pct ≥ s 且 weight_pct ≥ s（双达银冠级、未达金冠级）。
      5. 银冠：size_pct ≥ s 或 weight_pct ≥ s（单边达银冠级）。
      6. 普通：其余。
    边界语义（细化 §2.3 L135）：==5 非逆金冠（严格 <）；==85 达银冠级（>=）；
      ==95 达金冠级（>=）。纯函数零 IO 零定时器/零睡眠（铁律）。

    确定性：纯函数，同入参 → 恒同结果（TC-05~09/09b 全覆盖）。
    """
    s_raw = _num(size_pct)
    w_raw = _num(weight_pct)
    s = s_raw if s_raw is not None else 0.0
    w = w_raw if w_raw is not None else 0.0
    t = _thresholds_of(thresholds)
    r = float(t["reverse"])
    s_ = float(t["silver"])
    g = float(t["gold"])

    # 1. 逆金冠：双 < r（严格小于；混合极端不判逆金冠，TC-07/09）
    if s < r and w < r:
        return CROWN_REVERSE
    # 2. 大金冠：双 ≥ g（TC-08/09b）
    if s >= g and w >= g:
        return CROWN_BIG_GOLD
    # 3. 金冠：单边 ≥ g（含混合极端 size≥g 且 weight<r，TC-09）
    if s >= g or w >= g:
        return CROWN_GOLD
    # 4. 大银冠：双 ≥ s（未达金冠级）
    if s >= s_ and w >= s_:
        return CROWN_BIG_SILVER
    # 5. 银冠：单边 ≥ s（TC-08）
    if s >= s_ or w >= s_:
        return CROWN_SILVER
    # 6. 普通：其余
    return CROWN_NORMAL


__all__ = [
    # 常量
    "CROWN_REVERSE", "CROWN_BIG_GOLD", "CROWN_GOLD",
    "CROWN_BIG_SILVER", "CROWN_SILVER", "CROWN_NORMAL",
    "CROWN_ORDER", "CROWN_LABELS", "DEFAULT_CROWN_THRESHOLDS",
    # 生成与判定
    "gen_size_weight",
    "crown_of",
]
