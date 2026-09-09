"""防反/闪反双子机制单测（2026-09-09 用户拍板标签制：不 roll——怪行动可反标签+玩家姿态）。

- 防反：怪行动带「可防反」+ 玩家当回合防反姿态（守势 parry）→ 完全免伤 + 自动反击
- 闪反：怪行动带「可闪反」+ 玩家闪反姿态（回环/腾空 dodge）位移出范围 → 免伤（天然）+ 反击
- 失败：行动无标签 → 受伤（姿态减伤照常）+ 无反击
"""
from pathlib import Path

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.monster_ai import MonsterAI


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _pack():
    pack, _ = build_pack(Path("content/veinborn"))
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(
        defs={**all_defs, **chains},
        resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i),
    )
    return raw, all_defs, ce


_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 10, "mag": 10,
    "proficiency": {"alchemy": {"level": 4, "exp": 0}},
}


def _enemy(raw, eid):
    et = next(e for e in raw["enemies"] if e["id"] == eid)
    st = et.get("stats") or {}
    return et, {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": int(st.get("str", 10)), "dfn": int(st.get("con", 10)),
        "mag": 0, "spd": 0, "foc": 0, "lck": 0,
        "con": int(st.get("con", 10)), "agi": 0, "name": et["name"],
    }


def _fresh(raw, all_defs, ce):
    et, mob = _enemy(raw, "ridge_cub")
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7)
    eng._enemy_ai = ai
    return eng


def _fx_types(outcomes):
    out = []
    for o in outcomes:
        for x in (getattr(o, "side_effects", ()) or ()):
            out.append(str(x.get("type")))
    return out


def test_parry_guard_fully_negates_and_counter():
    """守势（防反姿态）挡可防反扑咬 → 完全免伤（hp 不减）+ parry_counter 反击伤害。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    fx = _fx_types(tr.outcomes)
    assert "parry" in fx and "parry_counter" in fx, f"防反应触发 parry/counter，got {fx}"
    assert tr.player == 900, f"防反成功应完全免伤（hp 900），got {tr.player}"
    cd = next((int(x.get("damage") or 0) for o in tr.outcomes
               for x in (getattr(o, "side_effects", ()) or ())
               if x.get("type") == "parry_counter"), 0)
    assert cd > 0, f"防反反击应造成伤害，got {cd}"


def test_dodge_circle_position_miss_counter():
    """回环（闪反姿态）→ 侧移出扑咬方位 → 够不着（免伤）+ dodge_counter 反击。"""
    raw, all_defs, ce = _pack()
    eng = _fresh(raw, all_defs, ce)
    tr = eng.player_act({"type": "skill", "skill_id": "sw_circle"})
    fx = _fx_types(tr.outcomes)
    assert "position_miss" in fx, f"回环侧移后扑咬应够不着，got {fx}"
    assert tr.player == 900, f"闪反成功应免伤，got {tr.player}"
    cd = next((int(x.get("damage") or 0) for o in tr.outcomes
               for x in (getattr(o, "side_effects", ()) or ())
               if x.get("type") == "dodge_counter"), 0)
    assert cd > 0, f"闪反反击应造成伤害，got {cd}"


def test_guard_vs_non_parryable_action_takes_damage():
    """守势挡不可防反行动 → 受伤（减伤照常）+ 无 parry 事件（用户示例语义）。"""
    raw, all_defs, ce = _pack()
    # 找无「可防反」标签的伤害行动（td_stomp 震地类）
    act = next((a for a in raw["action"]
                if a.get("intent") == "伤害" and "可防反" not in (a.get("tags") or [])), None)
    assert act is not None, "内容层应有不可防反的伤害行动"
    et, mob = _enemy(raw, "ridge_cub")
    ai = MonsterAI(enemy_def=et, action_lib=lambda i: all_defs.get(i),
                   rng=_QR([0.1] * 800))
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    eng.start(dict(_PLAYER), mob, random_seed=7)
    eng._enemy_ai = ai
    # 玩家先施守势（姿态在当回合）
    eng.player_act({"type": "skill", "skill_id": "sw_guard"})
    # 再开一局干净验证：守势当回合被不可反行动打
    eng2 = _fresh(raw, all_defs, ce)
    eng2._snap["counter_stance"] = {"type": "parry", "skill": "sw_guard_counter",
                                    "turn": int(eng2._snap.get("turn", 0))}
    out = eng2.do_action("enemy", {"type": "skill", "skill_id": act["id"]})
    fx = [str(x.get("type")) for x in (getattr(out, "side_effects", ()) or ())]
    assert "parry" not in fx, f"不可防反行动不应触发防反，got {fx}"
    assert out.target_hp < 900, "不可防反行动应造成伤害"
