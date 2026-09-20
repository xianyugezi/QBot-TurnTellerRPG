#!/usr/bin/env python3
"""批57 · 经济循环推演与不可套利证据（复跑脚本；只读、纯函数、无 IO 副作用）。

用途：把主 agent 点名的两处数值问题的**证据**一次性打印出来——
  ① 84:1 失衡：产出侧用报告 §3.1 公式 `V × k1 × k2 × β^色序`，消耗侧按报告 §4.6
     反解平衡点 ≈1593 精粹/点；本脚本给「打造 N 件 → 分解 95 件 → 精粹 → 满淬 5 件」的
     典型循环推演表，证明产出/消耗 ≈ 1.00×（不再是 84:1 / 1593×）。
  ② β^色序 闸门无效：β 降为正向系数（默认 1.2）；真闸门 = 淬炼不可逆 + 返还随淬炼量
     衰减。本脚本给 N 轮「淬炼→分解→再淬炼」循环模拟，证明余额单调递减、无套利。

复跑：
    python3 scripts/batch57_cycle_sim.py
    python3 scripts/batch57_cycle_sim.py --json
口径依据：`/root/deliverables/淬炼与分解回收_实现口径.md` §4.2~§4.6；
          主 agent 本批两处裁定；`data/temper_stats.py` 默认值。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent if (_HERE.parent / "qbot_rpg").exists() else _HERE
sys.path.insert(0, str(_REPO))

from qbot_rpg.core.temper import (  # noqa: E402
    essence_base,
    normalize_essence_config,
    normalize_temper_config,
    simulate_cycle,
    temper_refund,
    total_cap_of,
    typical_cycle,
)

# 报告 §4.1/§4.2 实测场景（合成常量；不读任何内容包）
V_GRAD = 100600.0          # 毕业武器节点材料价值
# （king_night_crown×15@5000 + abyss_lord_core×8@3200 = 100,600）
LEVEL = 35                 # 装备等级（level_cap=35）
CAP_PER_LEVEL = 6          # 总上限 = 35 × 6 = 210
K1, K2, BETA = 0.35, 0.50, 1.2
COST_PER_POINT = 1593      # 报告 §4.6 反解平衡点
DECOMPOSE = 95             # 每 100 件里分解 95 件
TEMPER = 5                 # 保留 5 件满淬
MATERIAL_RATE = 0.65       # 生产等级王档材料回收率（既有 gem_wallet 口径）

_EC = {"enabled": True, "k1": K1, "k2": K2, "beta": BETA,
       "temper_refund": 800, "refund_decay": 0.5}
_TC = {"enabled": True, "cap_per_level": CAP_PER_LEVEL,
       "cost_per_point": {"essence": COST_PER_POINT}}
_COLORS = ["白", "绿", "蓝", "紫", "橙", "红"]


def _old_ratio(p: int) -> Dict[str, Any]:
    """报告 §4.5 的「通胀风险区」：同一产出下不同 per-point 消耗的产出/消耗比。"""
    produced = essence_base(V_GRAD, 0, normalize_essence_config(_EC)) * DECOMPOSE
    consumed = TEMPER * total_cap_of(LEVEL, normalize_temper_config(_TC)) * p
    return {"p": p, "produced": produced, "consumed": consumed,
            "ratio": (produced / consumed) if consumed else None}


def build() -> Dict[str, Any]:
    ec = normalize_essence_config(_EC)
    tc = normalize_temper_config(_TC)
    cap = total_cap_of(LEVEL, tc)
    cyc = typical_cycle(value=V_GRAD, level=LEVEL, decompose_count=DECOMPOSE,
                        temper_count=TEMPER, cfg_temper=_TC, cfg_essence=_EC)

    color_rows: List[Dict[str, Any]] = []
    for i, c in enumerate(_COLORS):
        per = essence_base(V_GRAD, i, ec)
        color_rows.append({"color": c, "order": i, "beta_pow": round(BETA ** i, 4),
                           "per_item": per, "x95": per * DECOMPOSE})

    sim = simulate_cycle(rounds=20, value=V_GRAD, level=LEVEL,
                         decompose_per_round=1, temper_per_round=1,
                         start_essence=1_000_000, cfg_temper=_TC, cfg_essence=_EC)
    rounds = [{"round": r["round"], "in": r["essence_in"], "out": r["essence_out"],
               "delta": r["delta"], "balance": r["balance"]} for r in sim["rows"]]

    refund_rows: List[Dict[str, Any]] = []
    for frac in (0.25, 0.5, 0.75, 1.0):
        pts = int(round(cap * frac))
        rf = temper_refund(pts, cap, ec)
        refund_rows.append({
            "frac": frac, "points": pts, "refund": rf, "cost": pts * COST_PER_POINT,
            "per_point": round(rf / pts, 2),
            "ratio": round(rf / (pts * COST_PER_POINT), 4),
        })

    return {
        "assumptions": {"V": V_GRAD, "level": LEVEL, "cap": cap, "k1": K1, "k2": K2,
                        "beta": BETA, "cost_per_point": COST_PER_POINT,
                        "material_rate": MATERIAL_RATE},
        "typical_cycle": {k: (round(v, 4) if isinstance(v, float) else v)
                          for k, v in cyc.items()},
        "old_ratios": [_old_ratio(p) for p in (1, 10, 84, 956, 1593, 1600)],
        "color_table": color_rows,
        "refund_curve": refund_rows,
        "loop_sim": {"cap": cap, "cost_full": sim["cost_full"],
                     "refund_full": sim["refund_full"],
                     "per_round_delta": sim["per_round_delta"],
                     "monotonic_decrease": sim["monotonic_decrease"],
                     "balance_start": sim["balance_start"],
                     "balance_end": sim["balance_end"], "rounds": rounds},
        "no_arbitrage": {
            "material_side_convergence": round(1 / (1 - MATERIAL_RATE), 3),
            "q1_delta_negative": sim["per_round_delta"] < 0,
            "q2_refund_rate_decreasing": all(
                refund_rows[i]["ratio"] < refund_rows[i - 1]["ratio"]
                for i in range(1, len(refund_rows))),
        },
    }


def render(data: Dict[str, Any]) -> str:
    a = data["assumptions"]
    c = data["typical_cycle"]
    L: List[str] = []
    L.append("=" * 78)
    L.append("批57 · 经济循环推演与不可套利证据（报告 §4 + 主 agent ①/②）")
    L.append("=" * 78)
    L.append(f"假设：V={a['V']:.0f} 装备等级={a['level']} 总上限={a['cap']} "
             f"k1={a['k1']} k2={a['k2']} β={a['beta']} 每点精粹={a['cost_per_point']}")
    L.append("")
    L.append("【问题① · 84:1 失衡 → 两侧同时定】")
    L.append(f"  单件白装精粹产出 = floor(V×k1×k2) = {c['per_item_essence']}")
    L.append(f"  典型循环：分解 {c['decompose_count']} 件 ↔ 满淬 {c['temper_count']} 件"
             f"（每件 {c['cap']} 点）")
    L.append(f"  产出 = {c['produced']}　消耗 = {c['consumed']}　"
             f"产出/消耗 = {c['ratio']:.4f}×　反解平衡点 p = {c['balance_point_p']:.2f}")
    L.append("  对照（报告 §4.5 通胀风险区；同样产出、不同每点消耗 p）：")
    for r in data["old_ratios"]:
        flag = "🟢 平衡" if r["p"] == 1593 else ("🔴 极端通胀" if r["ratio"] and r["ratio"] > 100
                                             else ("🟠 通胀" if r["ratio"] and r["ratio"] > 1
                                                   else "🔵 短缺"))
        L.append(f"    p={r['p']:<5} 产出/消耗={r['ratio']:>10.3f}×  {flag}")
    L.append("")
    L.append("【问题② · β^色序 闸门无效 → 真闸门】")
    L.append("  β 降为正向系数（品质越高单件回收价值越高，默认 β=1.2）：")
    for r in data["color_table"]:
        L.append(f"    {r['color']}(序{r['order']}) β^i={r['beta_pow']:<7} "
                 f"单件={r['per_item']:<7} ×95件={r['x95']}")
    L.append("  真闸门 = 不可逆 + 返还随淬炼量衰减（每点返还率单调下降）：")
    for r in data["refund_curve"]:
        L.append(f"    投入 {int(r['frac']*100):>3}% ({r['points']:>3}点) "
                 f"返还={r['refund']:<7} 每点={r['per_point']:<7} "
                 f"返还/消耗={r['ratio']:.4f}")
    L.append("")
    L.append("【循环模拟 · 20 轮「分解 → 满淬 → 再分解」（起始 1,000,000 精粹）】")
    sim = data["loop_sim"]
    L.append(f"  每轮净变化 = {sim['per_round_delta']}（<0 = 每轮净损）　"
             f"余额单调递减 = {sim['monotonic_decrease']}")
    L.append(f"  {'轮':>3} {'入':>10} {'出':>10} {'净':>10} {'余额':>12}")
    for r in sim["rounds"]:
        L.append(f"  {r['round']:>3} {r['in']:>10} {r['out']:>10} "
                 f"{r['delta']:>10} {r['balance']:>12}")
    na = data["no_arbitrage"]
    L.append("")
    L.append("【结论】")
    L.append(f"  · 不再 84:1：典型循环产出/消耗 = {c['ratio']:.4f}×（p=1 时才是 "
             f"{data['old_ratios'][0]['ratio']:.0f}×）")
    L.append(f"  · 无无限套利：每轮净变化 {sim['per_round_delta']} < 0、余额单调递减；"
             f"材料侧每循环净损 ≥{int((1-MATERIAL_RATE)*100)}%"
             f"（收敛级数 {na['material_side_convergence']}）")
    L.append(f"  · 返还率随投入单调下降 = {na['q2_refund_rate_decreasing']}")
    L.append("=" * 78)
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="批57 经济循环推演（只读复跑）")
    ap.add_argument("--json", action="store_true", help="输出 JSON（供对拍/存档）")
    args = ap.parse_args()
    data = build()
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
