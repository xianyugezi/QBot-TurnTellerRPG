#!/usr/bin/env python3
"""veinborn 精简验证包冒烟 v2：正确装配（raw dict 表，绕开 BaseDef 坑）。

验证项：
  1. build_pack 零红拦
  2. 敌方行动自挂困斗（bb_slam effects surge_gain）
  3. 机动牌泄压（rb_leap mark_remove surge_mark）
  4. 部位破坏链：rb_core_strike ×6 → 满 120 → 派生破脉核 → core_broken
  5. 专精配置齐备

铁律：零 NoneBot import；纯函数确定性。
用法：.venv/bin/python scripts/verify_veinborn_smoke.py
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from qbot_rpg.content.loader import build_pack  # noqa: E402
from qbot_rpg.core.battle import BattleEngine  # noqa: E402
from qbot_rpg.core.combo import ComboEngine  # noqa: E402

VEINBORN = REPO / "content" / "veinborn"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        PASS.append(name)
        print(f"  ✅ {name}")
    else:
        FAIL.append(name)
        print(f"  ❌ {name} {detail}")


def marks_on(state: Dict[str, Any], side: str, mark: str) -> int:
    ms = (state.get("marks_state") or {}).get(side) or {}
    total = 0
    for m in ms:
        if m.get("mark_id") == mark or m.get("id") == mark:
            total += int(m.get("count") or m.get("stacks") or 0)
    return total


def build() -> tuple:
    """build_pack + 装配 raw dict 表（绕开 registry.resolve BaseDef 坑）。"""
    pack, _ = build_pack(VEINBORN)
    raw = pack.registry.modules_raw
    skills_map = {s["id"]: s for s in raw["skills"]}
    actions_map = {a["id"]: a for a in raw["action"]}
    all_defs = {**skills_map, **actions_map}
    chains_map = {c["id"]: c for c in raw.get("skill_chains", [])}
    # 自定义 combo resolver：查 raw dict 表（绕 registry.resolve BaseDef 坑）；
    # skill_chain kind 查链表
    def _resolver(id_: str, kind: str):
        if kind == "skill_chain":
            return chains_map.get(id_)
        return all_defs.get(id_)
    ce = ComboEngine(resolver=_resolver)
    return pack, raw, all_defs, ce


def main() -> int:
    print("== 1. build_pack 零红拦 ==")
    pack, raw, all_defs, ce = build()
    check("pack.report.ok", pack.report.ok, f"errors={[str(e) for e in pack.report.errors][:3]}")

    player = {
        "hp": 800, "max_hp": 800, "mp": 50, "max_mp": 50,
        "atk": 50, "def": 30, "spr": 20, "spd": 12, "name": "脊剑士",
    }
    enemy_def = next(e for e in raw["enemies"] if e["id"] == "gravelcrown")
    enemy = {
        "hp": enemy_def["stats"]["hp"], "max_hp": enemy_def["stats"]["hp"],
        "mp": 100, "max_mp": 100,
        "atk": 40, "def": 20, "spr": 15, "spd": 8, "name": enemy_def["name"],
    }

    eng = BattleEngine(defs=all_defs, registry=pack.registry, combo_engine=ce)
    eng.start(player, enemy, random_seed=42)

    print("\n== 2. 敌方 bb_slam 自挂困斗（蓄能）==")
    out = eng.enemy_act({"type": "skill", "skill_id": "bb_slam"})
    st = eng.battle_state()
    surge = marks_on(st, "enemy", "surge_mark")
    print(f"  bb_slam ok={out.ok}, surge={surge}")
    check("敌方行动后困斗≥1", surge >= 1, f"surge={surge}")

    print("\n== 3. 机动牌泄压 ==")
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_leap"})
    st = eng.battle_state()
    surge2 = marks_on(st, "enemy", "surge_mark")
    print(f"  rb_leap ok={out.ok}, surge: {surge} -> {surge2}")
    check("机动牌移除困斗", surge2 < surge, f"surge {surge}->{surge2}")

    print("\n== 4. 部位破坏链（贯核击 → 满 120 → 破脉核）==")
    eng.end_turn()
    for i in range(8):
        out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
        print(f"  core_strike #{i+1}: ok={out.ok} | {out.message[:60]}")
        if eng.finished:
            break
        eng.enemy_act({"type": "skill", "skill_id": "bb_slam"})
        eng.end_turn()
    st = eng.battle_state()
    bv = marks_on(st, "enemy", "break_vein_core")
    cb = marks_on(st, "enemy", "core_broken")
    print(f"  破坏值={bv}, core_broken={cb}")
    check("破坏值累积到 120", bv >= 120, f"bv={bv}")
    check("破脉核链派生（core_broken 出现）", cb >= 1, f"cb={cb}")

    print("\n== 5. 专精配置齐备 ==")
    skills_map = {s["id"]: s for s in raw["skills"]}
    check("focus 轴注册", raw["stats"].get("focus", {}).get("max") == 6)
    check("rb_mastery 耗 4 聚焦",
          skills_map["rb_mastery"].get("energy_cost", {}).get("focus") == 4)
    check("形态技能挂 inexhaustible_form",
          skills_map["rb_form_strike"].get("job_form") == "inexhaustible_form")
    chains = {c["id"] for c in raw.get("skill_chains", [])}
    check("部位破坏链齐备",
          {"chain_core_break", "chain_tail_break", "chain_ridge_combo"} <= chains)

    print("\n== 汇总 ==")
    print(f"PASS {len(PASS)} / {len(PASS) + len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
