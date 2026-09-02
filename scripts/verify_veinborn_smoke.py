#!/usr/bin/env python3
"""veinborn 精简验证包冒烟 v3：G1/G2 修复后全链验证。

验证项（全部引擎级实测）：
  1. build_pack 零红拦
  2. 困斗蓄能：完整轮 end_turn 后 enemy surge_mark +1
  3. 机动泄压：rb_leap 移除 surge_mark（mark_remove 修好）
  4. 部位破坏全链：rb_core_strike 累积 120 → 派生破技 → core_broken 挂上
     + consume_marks 消耗破坏值清零（G2）
  5. 宣泄配置齐备（enemy_mark min:6 + trigger_cooldown）

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
    """build_pack + 装配（registry 给事件分派；defs raw dict 给 combo）。"""
    pack, _ = build_pack(VEINBORN)
    raw = pack.registry.modules_raw
    skills_map = {s["id"]: s for s in raw["skills"]}
    actions_map = {a["id"]: a for a in raw["action"]}
    all_defs = {**skills_map, **actions_map}
    chains_map = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_with_chains = {**all_defs, **chains_map}

    def _resolver(id_: str, kind: str):
        if kind == "skill_chain":
            return chains_map.get(id_)
        return all_defs.get(id_)

    ce = ComboEngine(defs=all_with_chains, resolver=_resolver)
    return pack, raw, all_with_chains, ce


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

    print("\n== 2. 困斗蓄能（完整轮 end_turn +1）==")
    eng.do_action("player", {"type": "skill", "skill_id": "rb_slash"})
    eng.enemy_act({"type": "skill", "skill_id": "bb_slam"})
    eng.end_turn()
    st = eng.battle_state()
    surge = marks_on(st, "enemy", "surge_mark")
    print(f"  round1 end: surge={surge}")
    check("轮末困斗≥1（蓄能）", surge >= 1, f"surge={surge}")

    print("\n== 3. 机动泄压（rb_leap 移除困斗）==")
    eng.do_action("player", {"type": "skill", "skill_id": "rb_leap"})
    st_mid = eng.battle_state()
    surge_mid = marks_on(st_mid, "enemy", "surge_mark")
    print(f"  rb_leap 后: surge={surge} -> {surge_mid}")
    check("机动牌泄压 -1", surge_mid < surge, f"surge {surge}->{surge_mid}")
    eng.enemy_act({"type": "skill", "skill_id": "bb_slam"})
    eng.end_turn()

    print("\n== 4. 部位破坏全链（贯核击→满120→派生破技→core_broken+消耗清零）==")
    for i in range(6):
        eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
        if eng.finished:
            break
        eng.enemy_act({"type": "skill", "skill_id": "bb_slam"})
        eng.end_turn()
    st = eng.battle_state()
    bv = marks_on(st, "enemy", "break_vein_core")
    print(f"  6 发后破坏值: {bv}")
    check("破坏值累积到 120", bv >= 120, f"bv={bv}")
    # 第 7 发派生破技（G1 结算 + G2 消耗）
    out = eng.do_action("player", {"type": "skill", "skill_id": "rb_core_strike"})
    st = eng.battle_state()
    cb = marks_on(st, "enemy", "core_broken")
    bv2 = marks_on(st, "enemy", "break_vein_core")
    print(f"  第7发: ok={out.ok} msg={out.message[:60]} | 破坏值 {bv}->{bv2} cb={cb}")
    check("破技派生挂 core_broken", cb >= 1, f"cb={cb}")
    check("破技消耗破坏值清零（G2）", bv2 == 0, f"bv={bv}->{bv2}")

    print("\n== 5. 宣泄/部位技配置齐备 ==")
    sa = enemy_def.get("special_actions", [])
    check("宣泄 special 存在（enemy_mark min:6）",
          any(s.get("trigger", {}).get("type") == "enemy_mark"
              and s.get("trigger", {}).get("mark") == "surge_mark"
              for s in sa))
    check("宣泄 trigger_cooldown 防连发",
          any(s.get("id") == "vb_unleash" and s.get("trigger_cooldown") for s in sa))

    print("\n== 汇总 ==")
    print(f"PASS {len(PASS)} / {len(PASS) + len(FAIL)}")
    for f in FAIL:
        print(f"  FAILED: {f}")
    return 0 if not FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
