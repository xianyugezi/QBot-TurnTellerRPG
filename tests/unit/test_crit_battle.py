"""会心深化（E19/E20/E21）战斗层集成测试——2026-09-12 批⑤实装。

口径（docs/veinborn_战斗规则增补_怪猎对照研究_20260911.md §E）：
  - **E19 负会心**：combatant `crit_bonus` 可为负 → 会心率 P 为负 → 负率内
    （min(100%, −P)）判「负会心」×0.75（`negative_crit`，公式层已单测）；
  - **E20 条件会心**：combatant `crit_bonus_cond` 映射 {back/low_hp/first: 百分数}
    ——背面（方位联动）/低血（阈值 `crit_cond_low_hp` 可配）/首击（本场首次命中，
    命中即消耗）；
  - **E21 属性会心**：元素通道默认不吃会心（×1.0）；天赋 `elem_crit_lv` Lv1-3 →
    ×(1 + elem_crit_step×Lv)（缺省步进 0.05）。
  - 渲染：负会心档 → 「（会心·负阶 ×0.75）」（非低档，默认渲染）。

铁律：零 NoneBot import；确定性（_QR 固定序列）；真跑断言。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.battle_config import resolve_battle_settings
from qbot_rpg.core.combo import ComboEngine
from qbot_rpg.core.message_format.battle_render import _render_crit_block_note


class _QR:
    def __init__(self, seq):
        self.seq = list(seq)
        self.i = 0

    def random(self):
        v = self.seq[self.i % len(self.seq)]
        self.i += 1
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


# 玩家 spd=50（首拍 t=200）；怪 spd=20、敌方 foc/agi=0（命中/格挡判定退化为恒中）。
_PLAYER = {
    "max_hp": 900, "hp": 900, "max_mp": 30, "mp": 30, "atk": 50, "dfn": 60,
    "foc": 10, "agi": 10, "spr": 10, "con": 10, "str": 50, "int": 10, "lck": 10,
    "elem_atk": 0, "name": "P", "spd": 50, "mag": 10,
}


def _fresh(*, player=None, rng=None, config=None):
    raw, all_defs, ce = _pack()
    et = next(e for e in raw["enemies"] if e["id"] == "ridge_cub")
    mob = {
        "id": et["id"], "hp": 3000, "max_hp": 3000, "mp": 0,
        "atk": 10, "dfn": 10, "mag": 0, "spd": 20, "foc": 0, "lck": 0,
        "con": 10, "agi": 0, "name": et["name"],
    }
    eng = BattleEngine(defs=all_defs, combo_engine=ce, enemy_def=et)
    eng._rng = _QR(rng or [0.5] * 400)  # type: ignore[assignment]
    eng.start(dict(player or _PLAYER), mob, random_seed=7, config=config)
    return eng


def _hit(eng, **extra):
    """直驱一次玩家普攻（含可选 action 扩展键），返回 ActionOutcome。"""
    action = {"type": "normal", "mult": 1.0}
    action.update(extra)
    return eng.do_action("player", action)


def _last_damage(eng, actor="player"):
    """该 actor 最近一次行动流水的伤害段（ch_phys/ch_elem）。"""
    for e in reversed(eng._snap.get("action_record") or []):
        if e.get("actor") == actor:
            return e.get("damage") or {}
    raise AssertionError("无行动流水")


def _player_outcome(report):
    for o in report.outcomes:
        if getattr(o, "actor", "") == "player":
            return o
    raise AssertionError("无玩家 outcome")


def _set_side(eng, side):
    cp = eng._snap.setdefault("combat_position", {})
    ent = cp.setdefault("player", {"relative_to": "enemy"})
    ent["side"] = side


# =====================================================================================
# 1. E19：crit_bonus 通道（含负值）
# =====================================================================================


def test_crit_bonus_raises_tier():
    """combatant crit_bonus=+100% → P 满贯 → 恒定高阶（缺省同 roll 为低阶）。"""
    eng0 = _fresh(rng=[0.5] * 400)
    assert _hit(eng0).crit == "low"
    p = dict(_PLAYER)
    p["crit_bonus"] = 100
    eng1 = _fresh(player=p, rng=[0.5] * 400)
    assert _hit(eng1).crit == "high"


def test_negative_crit_battle_path():
    """combatant crit_bonus=−50% → 负率内（r=0.3 ≤ 0.434）判负会心；伤害低于同 roll 低阶。"""
    p = dict(_PLAYER)
    p["crit_bonus"] = -50
    eng_neg = _fresh(player=p, rng=[0.3] * 400)
    out_neg = _hit(eng_neg)
    assert out_neg.crit == "negative", f"got {out_neg.crit}"
    eng_low = _fresh(rng=[0.3] * 400)
    out_low = _hit(eng_low)
    assert out_low.crit == "low"
    assert out_neg.final_damage < out_low.final_damage, "负会心应低于低阶会心伤害"


# =====================================================================================
# 2. E20：条件型会心（back / low_hp / first）
# =====================================================================================


def test_cond_back_bonus():
    """背面条件（方位联动）：背后出手吃 +50%，正面同 roll 不吃。"""
    p = dict(_PLAYER)
    p["crit_bonus_cond"] = {"back": 50}
    eng_back = _fresh(player=p, rng=[0.3] * 400)
    _set_side(eng_back, "back")
    assert _hit(eng_back).crit == "high"
    eng_front = _fresh(player=p, rng=[0.3] * 400)
    assert _hit(eng_front).crit == "low"


def test_cond_low_hp_threshold_config():
    """低血条件：阈值 `crit_cond_low_hp` 可配（缺省 0.3；500/900=55.6% 默认不吃）。"""
    p = dict(_PLAYER)
    p["hp"] = 500
    p["crit_bonus_cond"] = {"low_hp": 40}
    eng_def = _fresh(player=p, rng=[0.3] * 400)
    assert _hit(eng_def).crit == "low", "默认阈值 0.3 下 55.6% 不应触发"
    eng_cfg = _fresh(player=p, rng=[0.3] * 400, config={"crit_cond_low_hp": 0.8})
    assert _hit(eng_cfg).crit == "high", "阈值 0.8 下应触发"
    # 管道：settings["battle"] 段白名单
    assert resolve_battle_settings({"battle": {"crit_cond_low_hp": 0.8}}) == \
        {"crit_cond_low_hp": 0.8}
    for bad in (0.0, 2.0, "x", True):
        assert resolve_battle_settings({"battle": {"crit_cond_low_hp": bad}}) == {}


def test_cond_first_consumed_after_first_hit():
    """首击条件：本场首次命中吃 +40%，命中即消耗（第二击同 roll 不吃）。"""
    p = dict(_PLAYER)
    p["crit_bonus_cond"] = {"first": 40}
    eng = _fresh(player=p, rng=[0.3] * 400)
    o1 = _player_outcome(eng.player_act({"type": "normal"}))
    assert o1.crit == "high", f"首击应吃加成，got {o1.crit}"
    o2 = _player_outcome(eng.player_act({"type": "normal"}))
    assert o2.crit == "low", f"第二击应已消耗，got {o2.crit}"


# =====================================================================================
# 3. E21：属性会心（默认不吃 / 天赋步进）
# =====================================================================================


def test_elem_default_ignores_crit():
    """元素通道默认不吃会心：高阶 vs 低阶对照下 ch_elem 相同、ch_phys 高者更高。"""
    p = dict(_PLAYER)
    p["elem_atk"] = 100
    eng_low = _fresh(player=p, rng=[0.5] * 400)
    _hit(eng_low, elem_mult=1.0)
    rec_low = _last_damage(eng_low)
    p2 = dict(p)
    p2["crit_bonus"] = 100
    eng_high = _fresh(player=p2, rng=[0.5] * 400)
    _hit(eng_high, elem_mult=1.0)
    rec_high = _last_damage(eng_high)
    assert rec_low["ch_elem"] == rec_high["ch_elem"] == 100, "元素不应吃会心"
    assert rec_high["ch_phys"] > rec_low["ch_phys"], "物理照常吃会心"


def test_elem_crit_talent_step():
    """属性会心天赋 Lv3 → 元素 ×(1+0.05×3)（缺省步进）。"""
    p = dict(_PLAYER)
    p["elem_atk"] = 100
    eng0 = _fresh(player=p, rng=[0.5] * 400)
    _hit(eng0, elem_mult=1.0)
    base = _last_damage(eng0)["ch_elem"]
    p3 = dict(p)
    p3["elem_crit_lv"] = 3
    eng3 = _fresh(player=p3, rng=[0.5] * 400)
    _hit(eng3, elem_mult=1.0)
    got = _last_damage(eng3)["ch_elem"]
    expected = int(100 * (1.0 + 0.05 * 3))
    assert got == expected, f"期望 {expected}（floor 100×1.15），got {got}"
    assert base == 100


# =====================================================================================
# 4. 渲染：负会心档
# =====================================================================================


def test_render_negative_tier_note():
    """负会心档 → 「（会心·负阶 ×0.75）」（非低档，默认渲染）。"""
    out = SimpleNamespace(crit="negative", blocked=False, backstab=False)
    assert _render_crit_block_note(out) == "（会心·负阶 ×0.75）"
    low = SimpleNamespace(crit="low", blocked=False, backstab=False)
    assert _render_crit_block_note(low) == "", "低档缺省仍省略"
