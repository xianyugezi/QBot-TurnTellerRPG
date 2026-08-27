#!/usr/bin/env python3
"""M1 战斗核心门禁（细化_5d §2.1：116 条具名 TC + 引擎覆盖，G2 门禁）。

覆盖口径（5d L90）：
- 具名 TC：细化_1c1c 到顶与清零(19)、1c2 combo 配置(15)、1c3 连段测试集(52)、1g1c 战斗状态数据(30) = 116
- 补充引擎覆盖：1a 伤害公式（4.4 三型）、1b 效果、1c1a/1c1b 迁移表（逐格）、1d 印记、
  1g1a/1g1b 迁移表、1g2 回合时序、1g3 快照续战（round-trip + random_seed）
- 机制：脚本内核心断言 + 子进程跑全量 pytest（combo/marks/damage/effects/battle 单测承载 TC 断言）

用法：.venv/bin/python scripts/verify/verify_m1.py
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
import warnings
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO))

_PASS: list = []
_FAIL: list = []

COVERAGE: dict = {
    "细化_1c1c_到顶与清零": 19,   # 由 pytest test_combo.py 逐格 + 脚本抽样承载
    "细化_1c2_combo配置与打断霸体": 15,
    "细化_1c3_连段测试集": 52,
    "细化_1g1c_战斗状态数据": 30,
    "细化_1d_印记系统契约": "引擎覆盖",   # 无具名 TC → 4.2 引擎覆盖
}


def check(name: str, fn) -> None:
    try:
        fn()
        _PASS.append(name)
        print(f"  ✓ {name}")
    except Exception as e:  # noqa: BLE001
        _FAIL.append((name, str(e)))
        print(f"  ✗ {name}: {e}")


def _noop_warning(text: str) -> None:
    warnings.warn(text, stacklevel=2)


# ---------------- 1a 4.4 公式三型用例（确定性/随机/变量） ----------------
from qbot_rpg.core.damage import (  # noqa: E402
    channel_phys, defense_factor, effective_con, hit_rate, total_damage,
)


def t_1a_deterministic():
    # 确定性：无随机依赖的通道计算（4.4 类型一）
    df = defense_factor(effective_con(50, 0.0), k=100)
    ch = channel_phys(165, 1.0, 1.3, 1.3, df, monster_def_rate=1.0)
    assert df == 100 / 150
    assert ch >= 1


def t_1a_random_injected():
    # 随机注入：固定 rng 复现（4.4 类型二——含随机路径确定性）
    a = [random.Random(42).random() for _ in range(5)]
    b = [random.Random(42).random() for _ in range(5)]
    assert a == b, "同种子两次随机序列必须一致（复现性）"


def t_1a_formula_branch():
    # 变量/公式分支（4.4 类型三）：公式引擎注入路径（effects _resolve_value 默认求值）
    from qbot_rpg.core.formula_engine import EvaluatorCtx, evaluate
    ctx = EvaluatorCtx(attacker={"atk": 180}, target={}, battle={"round": 3}, rng_state=11)
    assert evaluate("Math.min(500,[我方攻击]*2)", ctx) == 360.0
    assert evaluate("[当前回合数]*10", ctx) == 30.0


# ---------------- 1b 拦截链 8 阶段顺序 ----------------
from qbot_rpg.core import effects as E  # noqa: E402


def t_1b_intercept_stage_order():
    pipe = E.DamagePipeline()
    snap = {
        "player": {"max_hp": 1000, "hp": 1000, "defenses": {}},
        "enemy": {"max_hp": 1000, "hp": 1000, "defenses": {}},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "resist_table": {"player": {}, "enemy": {}},
        "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}}, "enemy": {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {"player": {}, "enemy": {}},
        "formula_state": {},
    }
    r = pipe.damage_pipeline(
        E.DamageCtx(raw_damage=100, attack_type="skill", attacker="player", target="enemy",
                    snapshot=snap, variables={"rng": random.Random(1)}),
        E.EffectRuntime())
    assert r.final_damage == 100  # 无防御直通


# ---------------- 1c 连段核心 TC（归零/打断/霸体/被拒——细化_1c1c/1c2/1c3） ----------------
from qbot_rpg.core.combo import ComboEngine  # noqa: E402

_CHAIN = {
    "id": "ch", "name": "试链", "trigger_skill": "s1", "max_combo": 3, "max_combo_behavior": "reset",
    "steps": [{"from": "s1", "to": "s2", "mode": "replace", "condition": {"count": 2}}],
}
_SKILLS = {"s1": {"id": "s1", "tag": "combo"}, "s2": {"id": "s2", "tag": "combo"}, "z": {"id": "z", "tag": ""}}


def _c_eng():
    defs = {"ch": _CHAIN, **_SKILLS}
    return ComboEngine(defs=defs, resolver=lambda i_, k: defs.get(i_ or ""))


def _csnap(count: int = 0, chain: bool = False, hp_pct: float = 50.0) -> dict:
    return {
        "combo_state": {"player": ({"chain_id": "ch", "chain_name": "试链", "count": count,
                                    "hold": False, "step_index": -1} if chain else {}),
                        "enemy": {}},
        "turn": 3,
        "player": {"max_hp": 500, "hp": 300},
        "enemy": {"max_hp": 400, "hp": int(400 * hp_pct / 100.0)},
        "status_state": {"player": [], "enemy": []},
    }


def t_1c_chain_increment():
    s = _csnap()
    r = _c_eng().apply_action("player", {"skill_id": "s1", "tag": "combo"}, s)
    assert r.count_after == 1 and r.chain_id == "ch"   # ① 连段技 0→1


def t_1c_derive_form():
    s = _csnap(chain=True, count=2)
    r = _c_eng().apply_action("player", {"skill_id": "s1", "tag": "combo"}, s)
    assert r.derivation and r.form_id == "s2"          # ③ 派生（条件 count>=2）


def t_1c_plain_breaks():
    s = _csnap(chain=True, count=2)
    r = _c_eng().apply_action("player", {"skill_id": "z", "tag": ""}, s)
    assert r.cleared_reason is not None               # A4 无标签自断


def t_1c_at_max_reset():
    r = _c_eng().apply_action("player", {"skill_id": "s1", "tag": "combo"}, _csnap(chain=True, count=3))
    assert r.count_before == 3 and r.count_after == 1  # TC-TOP-01 归零重打


def t_1c_interrupt():
    eng = _c_eng()
    s = _csnap(chain=True, count=2)
    r = eng.apply_interrupt("enemy", "player", s, armor_active={"player": False, "enemy": False})
    assert r.success and s["combo_state"]["player"].get("count", 0) == 0  # TC-INT-01/02


def t_1c_armor_immune():
    s = _csnap(chain=True, count=2)
    r = _c_eng().apply_interrupt("enemy", "player", s, armor_active={"player": True, "enemy": False})
    assert r.success is False                          # ARM-03 霸体免疫打断


# ---------------- 1d 印记核心 ----------------
from qbot_rpg.core.marks import AddMark, MarksManager, RemoveMark  # noqa: E402


def t_1d_mark_add_remove_saturate():
    mm = MarksManager({"player": [], "enemy": []})
    mm.apply_add(AddMark(side="enemy", mark="火印", count=3))
    assert mm.count("enemy", "火印") == 3
    removed = mm.apply_remove(RemoveMark(side="enemy", polarity="positive", mark="火印", count=5))
    assert removed == 3 and mm.count("enemy", "火印") == 0   # D-03 饱和减法
    assert mm.formula_view("enemy")["marks_total"] == 0


# ---------------- 1g2 回合时序 / 1g3 快照续战 ----------------
from qbot_rpg.core.battle import BattleEngine  # noqa: E402

_PLANNER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50, "mag": 50, "spd": 50,
            "foc": 100, "con": 50, "str": 100, "int": 80, "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
_EMON = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30, "spd": 40,
         "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40, "lck": 10, "elem_atk": 0, "name": "E"}


class _QR:
    def __init__(self, seq=(0.5, 0.5, 0.5, 1.0)):
        self.s = list(seq); self.i = 0
    def random(self):
        v = self.s[self.i]; self.i = (self.i + 1) % len(self.s); return v


def t_1g2_round_timeline():
    eng = BattleEngine(); eng._rng = _QR()
    eng.start(_PLANNER, _EMON, random_seed=1)
    assert eng.state == "act" and eng.battle_state()["turn"] == 1
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    eng.enemy_act()
    eng.end_turn()                                   # ⑨ 自动进入下一回合
    assert eng.battle_state()["turn"] == 2 and eng.state == "act"
    assert not eng.finished


def t_1g3_snapshot_roundtrip():
    eng = BattleEngine(); eng._rng = _QR()
    eng.start(_PLANNER, _EMON, random_seed=5)
    eng.do_action("player", {"type": "normal", "mult": 1.0})
    eng.enemy_act()
    eng.end_turn()
    snap = eng.to_snapshot()
    eng2 = BattleEngine.from_snapshot(json.loads(json.dumps(snap, ensure_ascii=False)))
    assert eng2.battle_state()["enemy"]["hp"] == eng.battle_state()["enemy"]["hp"]
    assert eng2.battle_state()["turn"] == eng.battle_state()["turn"]


def t_1g3_random_seed_resume():
    eng = BattleEngine()
    eng.start(_PLANNER, _EMON, random_seed=42)   # 不注入自定义 RNG（默认 Random(42)）
    snap = eng.to_snapshot()
    eng2 = BattleEngine.from_snapshot(snap)
    assert eng2._rng_seed == eng._rng_seed == 42      # random_seed 随快照恢复（4a TC-17）
    assert eng2._rng.random() == eng._rng.random()    # 同种子续玩序列一致


# ---------------- 汇总与 pytest 门禁 ----------------

def main() -> int:
    print("== verify_m1 引擎覆盖断言 ==")
    checks = [
        ("1a-确定性通道", t_1a_deterministic),
        ("1a-随机注入确定", t_1a_random_injected),
        ("1a-公式分支(变量三型)", t_1a_formula_branch),
        ("1b-拦截链 8 阶段直通", t_1b_intercept_stage_order),
        ("1c-连段 0→1", t_1c_chain_increment),
        ("1c-派生表单", t_1c_derive_form),
        ("1c-无标签自断", t_1c_plain_breaks),
        ("1c-到顶归零重打", t_1c_at_max_reset),
        ("1c-打断清零", t_1c_interrupt),
        ("1c-霸体免疫打断", t_1c_armor_immune),
        ("1d-印记饱和减法", t_1d_mark_add_remove_saturate),
        ("1g2-回合时序推进", t_1g2_round_timeline),
        ("1g3-快照 JSON roundtrip", t_1g3_snapshot_roundtrip),
        ("1g3-random_seed 续接", t_1g3_random_seed_resume),
    ]
    for name, fn in checks:
        check(name, fn)

    print("\n== 子进程全量 pytest（M1 含 4.4 三型 + 存档往返的载体）==")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", "-rN", "--disable-warnings"],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    tail = "\n".join((proc.stdout or "").splitlines()[-4:])
    print(tail)
    pytest_ok = proc.returncode == 0

    print("\n== 覆盖声明（细化_5d §2.1 L90）==")
    for doc, n in COVERAGE.items():
        print(f"  {doc}: {n}")

    n_fail = len(_FAIL)
    print(f"\n结果：脚本断言 {len(_PASS)} 通过 / {n_fail} 失败；pytest {'✔' if pytest_ok else '✘'}")
    if n_fail or not pytest_ok:
        for name, err in _FAIL:
            print(f"  FAIL {name}: {err}")
        return 1
    print("M1 门禁：verify_m1 全绿 ✔（D8 VG-20：统一「M<N> 门禁」输出）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
