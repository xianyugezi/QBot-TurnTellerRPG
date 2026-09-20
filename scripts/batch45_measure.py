#!/usr/bin/env python3
"""批45 · 装备占比校准 —— 修前/修后测量（可复跑，读 content/veinborn 真实数据）。

口径与依据
----------
* 面板构成（白值:装备:buff）：`docs/veinborn_阶段一_数值模型_1-35_v2.md:32`
  （7:8:5 预算）、`docs/深度打造_决策记录.md` §三 补充 1。
* 斩杀回合：`qbot_rpg.core.damage`（战斗数值层定稿执行级公式，与 `core/battle.py`
  `_resolve_damage_action` 同源）：
      D = max(1, floor(atk × skill_mult × weak × crit × K/(eff_con+K) × mdr))
      turns = ceil(hp / D)
  确定性口径 = 单发普攻（skill_mult=1.0）、不利用弱点（weak=1.0）、不暴击
  （crit=1.0，取下限）、乱数=1.0；故只考察「攻击源 vs 有效体质」主链。
* 蒙特卡洛：固定种子 20260919，命中/会心/格挡/乱数全部按引擎公式抽样，N=20000。
* 玩家 = 35 级脊剑士（jobs.json `ridge_blade`.growth），毕业装取自真实内容
  （guji_blade_d + haozhu_* 五件 + night_king_seal）。
* buff 预算：模型「5 份」按 lv35 白值等比折算（unit = 白atk / 白值份），
  三档 = 无buff(0) / 半buff(0.5×满) / 满buff(1.0×满)。

配置读取（缺省 = 现状，回归零影响）
------------------------------------
* `settings.panel_budget = {white, equip, buff, equip_stat_mult}`；
  占比(装备) = equip×equip_stat_mult / (white + equip×equip_stat_mult + buff)。
* `settings.monster_scaling = {hp_mult, atk_mult, def_factor, def_k?}`
  （`con' = (con+K)×def_factor − K`，与引擎 `core.panel_budget.scale_monster_con` 同源）。
* 缺省/未配置 → equip_stat_mult=1.0 / 三个 mult=1.0（与本批引入前逐字段一致）。

用法：``python3 scripts/batch45_measure.py [--json] [--effects]``

* 缺省（不带 `--effects`）：输出与批45/批53 基线**逐字节一致**（特效夹具不参与计算）。
* `--effects`：追加特效强度预算夹具（典型生存 build：减伤 25% + 吸血 15% + 冷却 ×0.8）→
  A1 度量（`effect_equiv_pct` / `effective_equip_share`）+ 按档位闸（`effect_cap_pct` /
  `effect_over`）+ 特效后的输出侧斩回（`turns_det_effects`）。**不改任何面板/怪物数值**。
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Tuple

_HERE = Path(__file__).resolve().parent
REPO = _HERE.parent if (_HERE.parent / "qbot_rpg").exists() else _HERE
sys.path.insert(0, str(REPO))

from qbot_rpg.core.damage import (  # noqa: E402
    block_rate,
    crit_prob,
    crit_roll,
    defense_factor,
    hit_rate,
)
from qbot_rpg.core.equipment import EquipmentEngine  # noqa: E402
from qbot_rpg.core.panel_budget import (  # noqa: E402
    check_effect_budget,
    effect_equiv,
    effective_equip_share,
    scale_monster_con,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes  # noqa: E402
from qbot_rpg.data.gear_stats import extract_bonus  # noqa: E402
from qbot_rpg.data.item import ItemInstance  # noqa: E402
from qbot_rpg.data.player import PlayerAttributes  # noqa: E402

PACK = REPO / "content" / "veinborn"
SEED = 20260919
LEVEL = 35
JOB = "ridge_blade"

# 毕业装（真实内容 id → 槽）
GEAR: Tuple[Tuple[str, str], ...] = (
    ("guji_blade_d", "weapon"),
    ("haozhu_helm", "head"),
    ("haozhu_body", "body"),
    ("haozhu_hand", "hand"),
    ("haozhu_leg", "leg"),
    ("haozhu_foot", "foot"),
    ("night_king_seal", "accessory"),
)

# 三只代表性怪物（真实内容包数据；普通 / 精英 / Boss，同区段 D 区终局）
MONSTERS: Tuple[str, ...] = ("vein_black_bear", "black_crystal_troll", "mountain_howl_lord")

# 批55 · 特效强度预算：`--effects` 夹具（**典型生存 build**，报告 §1 「减伤 25% + 吸血 15%
# + 冷却 ×0.8」）。键/值由调用方显式给出（不是内容包数据）；缺省不传 `--effects` →
# 输出与引入前**逐字节一致**（本夹具不参与任何计算）。
EFFECT_FIXTURE: Dict[str, float] = {
    "cooldown_pct": -20.0,       # X27：×0.8 冷却
    "damage_taken_pct": -25.0,   # X02：减伤 25%（immune_dmg 25 的轴形态）
    "absorb_hp": 15.0,           # X12：吸血 15%
}
EFFECT_CFG: Dict[str, Any] = {"enabled": True}

DEFAULT_PANEL_BUDGET: Dict[str, float] = {"white": 7.0, "equip": 8.0, "buff": 5.0,
                                          "equip_stat_mult": 1.0}
DEFAULT_MONSTER_SCALING: Dict[str, float] = {"hp_mult": 1.0, "atk_mult": 1.0,
                                             "def_factor": 1.0, "def_k": 100.0}


def _load(name: str) -> Any:
    return json.loads((PACK / name).read_text(encoding="utf-8"))


def _settings() -> Mapping[str, Any]:
    return _load("settings.json")


def white_attrs() -> Dict[str, float]:
    """35 级白值（stats.json base + jobs.json 职业 growth×(lv-1)）。"""
    stats = _load("stats.json")
    jobs = {j["id"]: j for j in _load("jobs.json")}
    growth = jobs[JOB].get("growth") or {}
    out: Dict[str, float] = {}
    for key, spec in stats.items():
        if not isinstance(spec, Mapping):
            continue
        base = float(spec.get("base", 0) or 0)
        g = float(growth.get(key, 0.0) or 0.0)
        out[key] = base + g * (LEVEL - 1)
    return out


def gear_defs() -> Dict[str, Dict[str, Any]]:
    items = _load("items.json")
    return {i["id"]: i for i in items}


@dataclass
class Panel:
    white: Dict[str, float]
    equip_flat: Dict[str, float]
    equip_pct: Dict[str, float]
    buff_atk: float
    atk: float
    dfn: float
    hp: float
    equip_atk_raw: float
    equip_atk_scaled: float
    equip_stat_mult: float
    budget: Dict[str, float]

    @property
    def equip_share_budget(self) -> float:
        b = self.budget
        e = b["equip"] * b["equip_stat_mult"]
        return e / (b["white"] + e + b["buff"])


def build_panel() -> Panel:
    st = _settings()
    budget = dict(DEFAULT_PANEL_BUDGET)
    budget.update(st.get("panel_budget") or {})
    mult = float(budget.get("equip_stat_mult", 1.0) or 1.0)

    defs = gear_defs()
    inv: List[ItemInstance] = []
    for item_id, slot in GEAR:
        inv.append(ItemInstance(item_id=item_id, name=str(defs[item_id].get("name") or ""),
                                count=1, quality="normal", bound=False, stack_max=1,
                                slot=slot, stats_bonus=dict(extract_bonus(defs[item_id]))))
    attrs = PlayerAttributes(base=dict(white_attrs()))
    player: Dict[str, Any] = {"inventory": inv, "equipment": {}, "attributes": attrs}
    slots = st.get("slot_defs")
    try:
        eng = EquipmentEngine(slots=slots, panel_budget=budget)
    except TypeError:
        # 本批改动前：引擎尚无 panel_budget 形参 → 走原聚合，倍率在下方以等价口径补
        eng = EquipmentEngine(slots=slots)
    for item_id, slot in GEAR:
        row = next(x for x in inv if x.item_id == item_id)
        r = eng.equip(player, row, slot)
        assert r.get("ok"), (item_id, r)
    bonus = eng.aggregate_bonus(player)
    flat = dict(bonus.get("flat") or {})
    pct = dict(bonus.get("pct") or {})

    # 模型 buff 预算：unit = 白atk / white 份 → 满buff atk = unit × buff 份
    w = attrs.base
    unit = float(w.get("atk", 0)) / float(budget["white"])
    buff_full = unit * float(budget["buff"])
    buff_half = buff_full * 0.5

    # 等价口径（引擎未承载 panel_budget 时）：只对面板轴 atk/dfn/hp 施加倍率
    if "panel_budget" not in EquipmentEngine.__init__.__code__.co_varnames:
        for k in ("atk", "dfn", "hp"):
            if k in flat:
                flat[k] = flat[k] * mult
    equip_atk_scaled = float(flat.get("atk", 0.0))
    equip_atk_raw = equip_atk_scaled / mult if mult else equip_atk_scaled

    def final(atk_buff: float) -> Dict[str, int]:
        a = PlayerAttributes(base=dict(w))
        a.bonus["flat"] = dict(flat)
        a.bonus["pct"] = dict(pct)
        a.temp["flat"] = {"atk": atk_buff} if atk_buff else {}
        return calc_all_final_attributes(a)

    f = final(buff_half)
    return Panel(white=dict(w), equip_flat=flat, equip_pct=pct, buff_atk=buff_half,
                 atk=float(f.get("atk", 0)), dfn=float(f.get("dfn", 0)),
                 hp=float(f.get("hp", 0)), equip_atk_raw=equip_atk_raw,
                 equip_atk_scaled=equip_atk_scaled, equip_stat_mult=mult, budget=budget)


def monster_scaling() -> Dict[str, float]:
    st = _settings()
    out = dict(DEFAULT_MONSTER_SCALING)
    out.update(st.get("monster_scaling") or {})
    return {k: float(v) for k, v in out.items()}


def _scaled_con(mon: Mapping[str, Any], scaling: Mapping[str, float]) -> float:
    return scale_monster_con(mon["stats"]["con"], scaling["def_factor"],
                             scaling.get("def_k", 100.0))


def monster_row(enemies: Mapping[str, Any], mid: str) -> Dict[str, Any]:
    return enemies[mid]


def deterministic_turns(atk: float, mon: Mapping[str, Any], scaling: Mapping[str, float]) -> int:
    hp = float(mon["stats"]["hp"]) * scaling["hp_mult"]
    con = _scaled_con(mon, scaling)
    d = max(1, math.floor(atk * defense_factor(con)))
    return math.ceil(hp / d)


def mc_turns(atk: float, lck: float, foc: float, crit_bonus: float,
             mon: Mapping[str, Any], scaling: Mapping[str, float],
             rng: random.Random, n: int = 20000) -> float:
    hp0 = float(mon["stats"]["hp"]) * scaling["hp_mult"]
    con = _scaled_con(mon, scaling)
    spd = float(mon["stats"].get("agi", 10))
    mon_foc = float(mon["stats"].get("foc", 10))
    hr = hit_rate(foc, spd)
    br = block_rate(mon_foc)
    df = defense_factor(con)
    p = crit_prob(lck, crit_bonus=crit_bonus)
    total = 0
    for _ in range(n):
        hp = hp0
        turns = 0
        while hp > 0 and turns < 10000:
            turns += 1
            if rng.random() > hr:
                continue
            _, crit_mult = crit_roll(rng.random(), lck, p_override=p)
            blocked = rng.random() <= br
            rng_multi = 0.9 + rng.random() * 0.2
            raw = atk * crit_mult * df * (0.5 if blocked else 1.0) * rng_multi
            hp -= max(1, math.floor(raw))
        total += turns
    return total / n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--effects", action="store_true",
                    help="附加特效强度预算夹具（典型生存 build）：输出 effect_equiv_pct / "
                         "effective_equip_share 列与特效后斩回；缺省不带 = 与引入前逐字节一致")
    args = ap.parse_args()

    panel = build_panel()
    scaling = monster_scaling()
    enemies = {e["id"]: e for e in _load("enemies.json")}

    out: Dict[str, Any] = {
        "seed": SEED,
        "level": LEVEL,
        "job": JOB,
        "gear": [g[0] for g in GEAR],
        "panel_budget": panel.budget,
        "monster_scaling": scaling,
        "panel": {
            "white_atk": panel.white["atk"], "white_dfn": panel.white["dfn"],
            "white_hp": panel.white["hp"],
            "equip_atk_raw": panel.equip_atk_raw,
            "equip_atk_scaled": panel.equip_atk_scaled,
            "equip_stat_mult": panel.equip_stat_mult,
            "equip_dfn_scaled": panel.equip_flat.get("dfn", 0.0),
            "equip_pct": panel.equip_pct,
            "buff_atk_half": panel.buff_atk,
            "atk_median": panel.atk, "dfn_median": panel.dfn, "hp_median": panel.hp,
            "equip_share_budget": round(panel.equip_share_budget, 6),
        },
        "monsters": [],
    }

    # 批55 · A1 度量 + 特效预算闸（仅 --effects；不改任何面板/怪物数值）。
    eff_pct = 0.0
    eff_out_rel = 1.0
    eff_gate: Dict[str, Any] = {}
    if args.effects:
        eq = effect_equiv(EFFECT_FIXTURE, EFFECT_CFG)
        eff_pct = float(eq["equiv_pct"])
        eff_out_rel = 1.0 + float(eq["output_pct"]) / 100.0
        gate = check_effect_budget(EFFECT_FIXTURE, None, EFFECT_CFG)
        eff_gate = {
            "fixture": dict(EFFECT_FIXTURE),
            "equiv_pct": round(eff_pct, 4),
            "output_pct": round(float(eq["output_pct"]), 4),
            "survival_pct": round(float(eq["survival_pct"]), 4),
            "unknown": list(eq["unknown"]),
            "gate_mode": gate["gate_mode"],
            "unknown_axis": gate["unknown_axis"],
        }
        out["panel"]["effect_output_pct"] = eff_gate["output_pct"]
        out["panel"]["effect_survival_pct"] = eff_gate["survival_pct"]
        out["panel"]["effect_equiv_pct"] = eff_gate["equiv_pct"]
        out["panel"]["effective_equip_share"] = round(
            effective_equip_share(panel.budget, eff_pct), 6)
        out["effect_budget"] = eff_gate

    # 三档面板（buff 0 / 半 / 满）
    unit = float(panel.white["atk"]) / float(panel.budget["white"])
    buff_full = unit * float(panel.budget["buff"])
    tiers = {"无buff下限": 0.0, "半buff中值": panel.buff_atk, "满buff上限": buff_full}

    for mid in MONSTERS:
        mon = enemies[mid]
        rec: Dict[str, Any] = {
            "id": mid, "name": mon.get("name"), "tier": mon.get("tier"),
            "hp_raw": mon["stats"]["hp"], "con_raw": mon["stats"]["con"],
            "hp_scaled": mon["stats"]["hp"] * scaling["hp_mult"],
            "con_scaled": _scaled_con(mon, scaling),
        }
        if args.effects:
            gate_tier = check_effect_budget(EFFECT_FIXTURE, mon.get("tier"), EFFECT_CFG)
            rec["effect_cap_pct"] = round(float(gate_tier["cap_pct"]), 4)
            rec["effect_over"] = bool(gate_tier["over"])
            rec["effect_action"] = str(gate_tier["action"])
        for tier, buff in tiers.items():
            a = PlayerAttributes(base=dict(panel.white))
            a.bonus["flat"] = dict(panel.equip_flat)
            a.bonus["pct"] = dict(panel.equip_pct)
            if buff:
                a.temp["flat"] = {"atk": buff}
            f = calc_all_final_attributes(a)
            atk = float(f["atk"])
            det = deterministic_turns(atk, mon, scaling)
            mc = mc_turns(atk, float(f.get("lck", 10)), float(f.get("foc", 10)),
                          float(panel.equip_flat.get("crit", 0.0)), mon, scaling,
                          random.Random(SEED))
            d = max(1, math.floor(atk * defense_factor(_scaled_con(mon, scaling))))
            cell: Dict[str, Any] = {"atk": atk, "dmg_det": d, "turns_det": det,
                                    "turns_mc": round(mc, 3)}
            if args.effects:
                # 报告 §1.5：特效的**输出侧等效**（冷却 ×0.8）折算进攻击后重算斩回；
                # 生存侧不进本工具口径（斩回只看输出），留给定稿档位尺（scripts/batch55_*）。
                cell["turns_det_effects"] = deterministic_turns(
                    atk * eff_out_rel, mon, scaling)
                cell["turns_det_delta"] = cell["turns_det_effects"] - det
            rec[tier] = cell
        out["monsters"].append(rec)

    if args.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        p = out["panel"]
        print("=== 面板构成 ===")
        print(f"白值 atk/dfn/hp = {p['white_atk']:.0f}/{p['white_dfn']:.0f}/{p['white_hp']:.0f}")
        print(f"装备 atk raw={p['equip_atk_raw']:.2f} ×{p['equip_stat_mult']} "
              f"= {p['equip_atk_scaled']:.2f}；dfn = {p['equip_dfn_scaled']:.2f}")
        print(f"buff 半档 atk = {p['buff_atk_half']:.2f}")
        print(f"中值面板 atk = {p['atk_median']:.0f}"
              f"（dfn {p['dfn_median']:.0f} / hp {p['hp_median']:.0f}）")
        print(f"预算占比(装备) = {p['equip_share_budget'] * 100:.2f}%  "
              f"budget={out['panel_budget']}")
        if args.effects:
            print(f"特效等效 = 输出 {p['effect_output_pct']:.2f}% / "
                  f"生存 {p['effect_survival_pct']:.2f}% → 综合 "
                  f"{p['effect_equiv_pct']:.2f}%；真实装备占比 = "
                  f"{p['effective_equip_share'] * 100:.2f}%（A1，只报数）")
        print(f"怪物倍率 = {out['monster_scaling']}")
        print("=== 斩杀回合（确定性 / MC N=20000 种子 %d）===" % SEED)
        for r in out["monsters"]:
            print(f"{r['name']}（{r['tier']}） hp {r['hp_raw']}→{r['hp_scaled']:.0f} "
                  f"con {r['con_raw']}→{r['con_scaled']:.1f}")
            if args.effects:
                over = "超限" if r["effect_over"] else "合规"
                print(f"   特效闸: 档位上限 {r['effect_cap_pct']:.2f}% → {over}"
                      f"（action={r['effect_action']}）")
            for tier in tiers:
                t = r[tier]
                extra = ""
                if args.effects:
                    extra = (f" 特效后={t['turns_det_effects']}"
                             f"（Δ{t['turns_det_delta']:+d}）")
                print(f"   {tier}: atk={t['atk']:.0f} D={t['dmg_det']} "
                      f"斩回={t['turns_det']} MC={t['turns_mc']}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
