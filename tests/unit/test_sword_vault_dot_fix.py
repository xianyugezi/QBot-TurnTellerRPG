"""御剑·腾空闪避回馈 + dot 破位 单测（2026-09-09 原稿修复）。

铁律：零 NoneBot import；纯逻辑断言；确定性随机。直接 build_pack 仓库 veinborn
内容包（与 e2e test_m13_fullchain 同风格）。
"""
import copy
from pathlib import Path

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.combo import ComboEngine

_PACK = Path("content/veinborn")


def _load_pack():
    pack, _ = build_pack(_PACK)
    assert pack.report.ok, f"veinborn 应零红拦：{pack.report.errors}"
    raw = pack.registry.modules_raw
    skills = {s["id"]: s for s in raw["skills"]}
    actions = {a["id"]: a for a in raw["action"]}
    chains = {c["id"]: c for c in raw.get("skill_chains", [])}
    all_defs = {**skills, **actions}
    for tbl in ("effects", "marks", "statuses"):
        for e in raw.get(tbl, []):
            all_defs.setdefault(e["id"], e)
    ce = ComboEngine(defs={**all_defs, **chains},
                     resolver=lambda i, k: chains.get(i) if k == "skill_chain" else all_defs.get(i))
    return raw, all_defs, ce


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


def _mk_enemy(et, st, parts=None):
    m = {"id": et["id"], "hp": 20000, "max_hp": 20000, "mp": 0, "atk": int(st.get("str", 10)),
         "dfn": int(st.get("con", 10)), "mag": 0, "spd": 0, "foc": 0, "lck": 0,
         "con": int(st.get("con", 10)), "agi": 0, "name": et["name"]}
    if parts:
        m["parts"] = parts
    return m


def test_sw_vault_dodge_feedback():
    """腾空原版：sw_vault 挂腾空姿态（air+status）；怪攻击 roll miss → 闪避回馈 +30 剑势。"""
    raw, all_defs, ce = _load_pack()
    et = next(e for e in raw["enemies"] if e["id"] == "gravel_tortoise")
    st = et.get("stats") or {}
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.9] * 800)  # type: ignore[assignment]  高值 → 怪命中 roll miss
    player = {"max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60, "foc": 10,
              "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10, "elem_atk": 0,
              "name": "P", "spd": 10, "mag": 10, "proficiency": {"alchemy": {"level": 4, "exp": 0}}}
    eng.start(player, _mk_enemy(et, st, et.get("parts")), random_seed=7)
    snap = eng._snap

    def aura():
        return next((x["count"] for x in snap["marks_state"].get("player", [])
                     if x["mark_id"] == "sword_aura"), 0)

    eng.player_act({"type": "skill", "skill_id": "sw_vault"})
    assert any(s.get("status_id") == "sw_vault_air"
               for s in snap.get("status_state", {}).get("player", [])), "腾空姿态未挂"
    a0 = aura()
    # 15（腾空斩灌注）+ 30（完整轮内怪攻击 miss 已触发首次闪避回馈）
    assert a0 == 45, f"腾空后剑势应 45（15+首轮闪避回馈 30）got {a0}"
    eng.player_act({"type": "guard"})
    assert aura() == a0 + 30, "再次被攻击 miss 应闪避回馈 +30 剑势"


def test_dot_part_break_per_tick():
    """二阶残响 dot：每跳对目标未破部位造成破坏值（part_break_per_tick）。"""
    raw, all_defs, ce = _load_pack()
    et = next(e for e in raw["enemies"] if e["id"] == "gravel_tortoise")
    st = et.get("stats") or {}
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR([0.1] * 800)  # type: ignore[assignment]
    player = {"max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60, "foc": 10,
              "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10, "elem_atk": 0,
              "name": "P", "spd": 10, "mag": 10, "proficiency": {"alchemy": {"level": 4, "exp": 0}}}
    eng.start(player, _mk_enemy(et, st, et.get("parts")), random_seed=7)
    snap = eng._snap
    snap["enemy"].setdefault("dot_pool", {})["sw_omni_dot"] = {
        "status_id": "sw_omni_dot", "value": 60, "tick": "turn_end", "turns": 2,
        "source": "player", "part_break_per_tick": 5}
    before = copy.deepcopy(snap.get("parts_state") or {})
    eng.player_act({"type": "skill", "skill_id": "sw_slash"})
    after = snap.get("parts_state") or {}
    for pid, pst in after.items():
        inc = float(pst.get("break_value", 0)) - float((before.get(pid) or {}).get("break_value", 0))
        assert inc >= 5.0, f"dot tick 后 {pid} 破坏值应含 dot 每跳 5，实际增量 {inc}"
