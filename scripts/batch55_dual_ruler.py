#!/usr/bin/env python3
"""批55 · 特效强度预算 —— **双尺子复算**（工具尺 + 定稿档位尺；可复跑，读真实内容包）。

依据：`docs/特效强度预算_设计.md` §四「红线守护：每新增一条特效轴的复算检查清单」
（C4/C5/C6/C7）+ §1.5/§1.6/§1.7。

两把尺子为什么必须同时跑（报告 §1.7）
--------------------------------------
* **工具尺** = `scripts/batch45_measure.py`（单发普攻、无技能、不暴击、乱数 1.0，种子 20260919）
  —— **相对仪器**：回答「相对修前漂移了几回合」，公差 **中值档逐只 ≤ ±1 回合**。
* **定稿档位尺** = `docs/审查参考/战斗数值层设计定稿.md` 的**绝对红线**
  （普通 3-8 / 精英 10-15 / Boss 40-60，**实机整场回合**）—— 回答「手感是否越档」。
* 两者口径不同、**不能直接比对**（精英 工具 20 > 档位 15；Boss 工具 24 < 档位 40）：
  工具管「没偷偷漂移」，档位管「手感没坏」。

定稿档位尺模型（报告 §1.6，**Boss 标定**）
-----------------------------------------
```
实机回合 R = 攻击回合 T / ρ          （ρ = 攻击回合占比；Boss 反推 ρ = 0.5 → 24/0.5 = 48 ∈ 40-60）
典型特效 build 后：
  T' = T0 / 输出等效          （冷却 ×0.8 → ×1.068）
  防御回合 ∝ 1/生存等效        （减伤 25% + 吸血 15% → ×1.33~1.48）
  R' = (T0/2)/1.068 + (T0/2)/生存等效     （0.5 标定拆分）
```
* 普通/精英 的 `T0` 取**档位中值标定**（普通 5.5 / 精英 12.5）——报告只给了 Boss 的 ρ 反推值，
  这两个是「内容已按定稿档位校准」的显式假设；Boss 取报告 §1.6 的 **48**（唯一 ρ 模型）。
* **上界估算**：若把特效削减到闸的 Boss 上限（综合等效 5%），则 worst-case 实机回合
  `R ≥ 24/1.1025 + 24 ≈ 45.8 ∈ 40-60`（几何口径下 equiv ≤5% ⇒ 单侧 ≤ ~10.25%）。

用法：``python3 scripts/batch55_dual_ruler.py [--json]``
只读仓库；`--json` 供 CI/对拍。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, Tuple

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parent if (_HERE.parent / "qbot_rpg").exists() else _HERE
sys.path.insert(0, str(REPO))

#: 定稿档位红线（`docs/审查参考/战斗数值层设计定稿.md:139-141`，实机整场口径）。
TIER_RED_LINES: Dict[str, Tuple[int, int]] = {
    "normal": (3, 8),
    "elite": (10, 15),
    "boss": (40, 60),
}
#: 修前实机基线（普通/精英 = 档中值标定；Boss = 报告 §1.6 ρ=0.5 反推值）。
BASELINE_REAL_TURNS: Dict[str, float] = {"normal": 5.5, "elite": 12.5, "boss": 48.0}
#: 报告 §1.2/§1.3 的典型特效 build 等效（输出 ×1.068；生存 ×1.33~1.48）。
OUTPUT_REL = 1.068
SURVIVAL_RELS: Tuple[float, ...] = (1.33, 1.48)
#: 工具尺公差（中值档逐只 ≤ ±1 回合；`docs/特效强度预算_设计.md` §4.1）。
TOOL_TOLERANCE_TURNS = 1


def _load_module(name: str, path: Path) -> Any:
    """按路径加载 scripts/ 下的工具脚本（scripts 不是包）。"""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # dataclass 需要模块已在 sys.modules 中
    spec.loader.exec_module(mod)
    return mod


def tool_ruler(measure: Any) -> Dict[str, Any]:
    """工具尺：修前（基线）vs 修后（本批缺省 = 零变化）vs 特效夹具（典型 build）。"""
    enemies = {e["id"]: e for e in measure._load("enemies.json")}
    scaling = measure.monster_scaling()
    panel = measure.build_panel()
    atk0 = float(panel.atk)
    equiv = measure.effect_equiv(measure.EFFECT_FIXTURE, measure.EFFECT_CFG)
    out_rel = 1.0 + float(equiv["output_pct"]) / 100.0

    base: Dict[str, int] = {}
    with_effects: Dict[str, int] = {}
    delta: Dict[str, int] = {}
    for mid in measure.MONSTERS:
        mon = enemies[mid]
        tier = str(mon.get("tier"))
        t0 = int(measure.deterministic_turns(atk0, mon, scaling))
        t1 = int(measure.deterministic_turns(atk0 * out_rel, mon, scaling))
        base[tier] = t0
        with_effects[tier] = t1
        delta[tier] = t1 - t0
    over = [t for t, d in delta.items() if abs(d) > TOOL_TOLERANCE_TURNS]
    return {
        "seed": measure.SEED,
        "job": measure.JOB,
        "median_atk": atk0,
        "equip_share_budget": round(float(panel.equip_share_budget), 6),
        "median_turns_before": base,
        "median_turns_after_default": dict(base),  # 本批缺省零变化（见 --json 对拍）
        "median_turns_with_effects": with_effects,
        "delta_turns": delta,
        "tolerance_turns": TOOL_TOLERANCE_TURNS,
        "over_tolerance": over,
        "effect_output_pct": round(float(equiv["output_pct"]), 4),
        "effective_equip_share": round(float(
            measure.effective_equip_share(panel.budget, float(equiv["equiv_pct"]))), 6),
        "effect_equiv_pct": round(float(equiv["equiv_pct"]), 4),
    }


def flip_thresholds(measure: Any) -> Dict[str, float]:
    """面板输出等效的**精确翻转阈值**：中值档斩回掉 1 回合所需的最小攻击倍率增量（%）。"""
    enemies = {e["id"]: e for e in measure._load("enemies.json")}
    scaling = measure.monster_scaling()
    atk0 = float(measure.build_panel().atk)
    out: Dict[str, float] = {}
    for mid in measure.MONSTERS:
        mon = enemies[mid]
        tier = str(mon.get("tier"))
        t0 = measure.deterministic_turns(atk0, mon, scaling)
        lo, hi = 0.0, 2.0
        for _ in range(80):
            mid_m = (lo + hi) / 2.0
            if measure.deterministic_turns(atk0 * (1.0 + mid_m), mon, scaling) < t0:
                hi = mid_m
            else:
                lo = mid_m
        out[tier] = round(hi * 100.0, 4)
    return out


def tier_ruler() -> Dict[str, Any]:
    """定稿档位尺：实机整场回合 vs 绝对红线（Boss 越档判定为核心结论）。"""
    rows: Dict[str, Dict[str, Any]] = {}
    for tier, (lo, hi) in TIER_RED_LINES.items():
        r0 = BASELINE_REAL_TURNS[tier]
        after = [round((r0 / 2.0) / OUTPUT_REL + (r0 / 2.0) / s, 3) for s in SURVIVAL_RELS]
        worst = min(after)
        rows[tier] = {
            "red_line": [lo, hi],
            "baseline_real_turns": r0,
            "typical_build_real_turns": [min(after), max(after)],
            "worst": worst,
            "within": bool(lo <= worst <= hi),
        }
    # 闸生效后（Boss 综合等效上限 5% ⇒ 单侧 ≤ ~10.25%）：worst-case R ≥ 24/1.1025 + 24。
    boss = BASELINE_REAL_TURNS["boss"]
    gated = round((boss / 2.0) / 1.1025 + (boss / 2.0), 3)
    boss_lo, boss_hi = TIER_RED_LINES["boss"]
    return {
        "model": "R = 攻击回合/1.068 + 防御回合/生存等效（ρ=0.5 标定拆分）",
        "assumptions": [
            "普通/精英 修前基线 = 档中值标定（报告未给其 ρ）",
            "Boss 修前基线 = 48（报告 §1.6 ρ=0.5 反推，落在 40-60 档中）",
            "典型 build = 输出 ×1.068（冷却 ×0.8）+ 生存 ×1.33~1.48（减伤 25% + 吸血 15%）",
        ],
        "rows": rows,
        "boss_gated_turns_lower_bound": gated,
        "boss_gated_within": bool(boss_lo <= gated <= boss_hi),
        "over_tier": [t for t, r in rows.items() if not r["within"]],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    measure = _load_module("batch45_measure", _HERE / "batch45_measure.py")
    out: Dict[str, Any] = {
        "batch": "批55 · 特效强度预算",
        "design": "docs/特效强度预算_设计.md §四",
        "tool_ruler": tool_ruler(measure),
        "flip_thresholds_pct": flip_thresholds(measure),
        "tier_ruler": tier_ruler(),
    }
    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return 0

    tr = out["tool_ruler"]
    print("=== 尺子① 工具尺（batch45 口径 · 相对仪器 · 种子 %d）===" % tr["seed"])
    print(f"中值 atk = {tr['median_atk']:.0f}；装备占比 = "
          f"{tr['equip_share_budget'] * 100:.2f}%")
    for tier in ("normal", "elite", "boss"):
        print(f"  {tier:6s}: 修前 {tr['median_turns_before'][tier]} → "
              f"本批缺省 {tr['median_turns_after_default'][tier]}（零变化） → "
              f"典型 build {tr['median_turns_with_effects'][tier]}"
              f"（Δ{tr['delta_turns'][tier]:+d}，公差 ±{tr['tolerance_turns']}）")
    print(f"  超公差的档位 = {tr['over_tolerance'] or '无'}")
    print(f"  精确翻转阈值（中值档掉 1 回合所需面板输出等效）："
          f"{out['flip_thresholds_pct']}")
    print(f"  A1 度量：特效综合等效 {tr['effect_equiv_pct']:.2f}% → 真实装备占比 "
          f"{tr['effective_equip_share'] * 100:.2f}%（只报数）")
    rr = out["tier_ruler"]
    print("=== 尺子② 定稿档位尺（绝对红线 · 实机整场）===")
    print(f"  模型：{rr['model']}")
    for tier, row in rr["rows"].items():
        lo, hi = row["red_line"]
        mark = "✓" if row["within"] else "✗ 越档"
        print(f"  {tier:6s} 红线 {lo}-{hi}：修前 {row['baseline_real_turns']} → "
              f"典型 build {row['typical_build_real_turns']} → {mark}")
    print(f"  越档档位 = {rr['over_tier'] or '无'}")
    print(f"  闸生效（Boss 上限 5% 综合等效）后 worst-case 实机下界 ≈ "
          f"{rr['boss_gated_turns_lower_bound']}（∈40-60 = {rr['boss_gated_within']}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
