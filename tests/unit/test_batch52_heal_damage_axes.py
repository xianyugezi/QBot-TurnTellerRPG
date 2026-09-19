"""批52 · 治疗/承伤双向轴接线验收测试（P0 核心玩法）。

口径：
  · `特效整理设计_1_修正轴全集.md` §5-D2（X17/X16 治疗双向）/ §5-D3（X02 承伤收敛）；
  · `特效整理设计_3_落点与分期.md` §二「批 50」（旧编号 = 本批批52）；
  · `特效强度预算_设计.md` §四 红线守护（C1 缺省对拍 / C9 特效键不进面板轴 / C11 上下钳）；
  · `docs/深度打造_决策记录.md` §十八（本批）。

覆盖：
  A. 受疗轴 `healing_received_pct`（唯一收口 heal_apply）：+50 ×1.5 / −50 ×0.5 / −200 反转 /
     无轴原值 / 声明区间钳制（下界收窄 = 关反转）；
  B. 出疗轴 `healing_done_pct`：+50 ×1.5；归并旧键 `heal_amp_pct`（战斗桥别名，行为一致）；
  C. 承伤轴 `damage_taken_pct`：−25 ×0.75 / +25 ×1.25；与 `immune_dmg` 归并**不双计**；
     声明区间钳制；
  D. 零变化对拍：未配置轴 → heal 收口原值 / 承伤乘区 1.0 / 战斗结算快照逐字段一致；
     `combatant_updates(flat)` 与 `combatant_updates(flat, None)` 逐字段一致；
  E. 多源 heal 全覆盖：heal 原子 / absorb_heal / regen / lifesteal / battle.absorb_hp + 负治疗。

纪律：测试只构造内存数据（不写任何真实内容包）；匿名 id（s_*）；数值/区间全由测试内声明。
"""
from __future__ import annotations

import copy
import json
import re
from typing import Any, Dict, List, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.effects import (
    HEAL_TAKEN_STAT,
    DamageCtx,
    EffectRuntime,
    execute_action,
    heal_apply,
    tick_turn_end,
)
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    EFFECT_AXES_KEY,
    EFFECT_LEGACY_ALIASES,
    GEAR_EFFECT_KEYS,
    combatant_updates,
    effect_axis_value,
    extract_bonus,
    route_bonus_into,
)

BP = "player"
BN = "enemy"


class _Def:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def _status(sid: str, value: float) -> _Def:
    return _Def({
        "id": sid, "name": sid, "class": "status", "category": "harm",
        "stack_frame": "stack", "max_stack": 3,
        "duration": {"turns": 3, "charges": 0},
        "actions": [{"type": "stat_modifier", "stat": HEAL_TAKEN_STAT, "value": value}],
    })


def _combatant(hp: int = 400) -> Dict[str, Any]:
    return {"max_hp": 1000, "hp": hp, "max_mp": 100, "mp": 50, "atk": 100, "dfn": 50}


def _snap(hp: int = 400) -> Dict[str, Any]:
    return {
        BP: _combatant(hp), BN: _combatant(hp),
        "status_state": {BP: [], BN: []},
        "marks_state": {BP: [], BN: []},
        "resist_table": {BP: {}, BN: {}},
        "effect_triggers": {BP: {"per_turn": {}, "per_battle": {}},
                            BN: {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {BP: {}, BN: {}},
    }


def _runtime(snap: Mapping[str, Any], *, axes: Any = None,
             defs: Any = None) -> EffectRuntime:
    cfg = {EFFECT_AXES_KEY: axes} if axes is not None else None
    return EffectRuntime(status_state=snap.get("status_state"), defs=defs, config=cfg)


def _ctx(snap: Mapping[str, Any], attacker: str = BP, target: str = BN) -> DamageCtx:
    return DamageCtx(raw_damage=0, attack_type="skill", attacker=attacker,
                     target=target, snapshot=snap, variables={})


def _run_heal(snap: Mapping[str, Any], runtime: EffectRuntime,
              value: int = 100, target: str = "self") -> Any:
    return execute_action({"type": "heal", "value": value, "target": target},
                          _ctx(snap), runtime)


# ===========================================================================
# A · 受疗轴（唯一收口 heal_apply）：双向 + 负治疗反转 + 钳制
# ===========================================================================
def test_a1_heal_received_positive_amplifies() -> None:
    """`+50` → 治疗 ×1.5（收口直算 + heal 原子动作端到端）。"""
    snap = _snap()
    snap[BP]["healing_received_pct"] = 50
    rt = _runtime(snap)
    assert heal_apply(100, rt, snap, BP, source=None) == 150
    res = _run_heal(snap, rt, value=100)
    assert res.ok and snap[BP]["hp"] == 550, snap[BP]["hp"]     # 400 + 150


def test_a2_heal_received_negative_reduces() -> None:
    """`−50` → 治疗 ×0.5。"""
    snap = _snap()
    snap[BP]["healing_received_pct"] = -50
    rt = _runtime(snap)
    assert heal_apply(100, rt, snap, BP, source=None) == 50
    _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 450, snap[BP]["hp"]                # 400 + 50


def test_a3_heal_received_le_minus_100_reverses_to_damage() -> None:
    """`−100` → 治疗归零（不反向扣血）；`−200` → 反转：治疗转伤害（下界放开）。"""
    snap = _snap()
    snap[BP]["healing_received_pct"] = -100
    rt = _runtime(snap)
    assert heal_apply(100, rt, snap, BP, source=None) == 0
    _run_heal(snap, rt, value=100)
    assert snap[BP]["hp"] == 400

    snap2 = _snap()
    snap2[BP]["healing_received_pct"] = -200
    rt2 = _runtime(snap2)
    assert heal_apply(100, rt2, snap2, BP, source=None) == -100
    res = _run_heal(snap2, rt2, value=100)
    assert res.ok and snap2[BP]["hp"] == 300, snap2[BP]["hp"]   # 400 − 100
    fx = [e for e in res.side_effects if e["type"] == "heal"]
    assert fx and fx[0]["value"] == -100 and fx[0].get("reversed") is True


def test_a4_heal_received_absent_is_identity() -> None:
    """无轴 → 原值（对拍：收口与未接轴前的原值逐字段一致）。"""
    snap = _snap()
    rt = _runtime(snap)
    for v in (0, 1, 37, 100, 999):
        assert heal_apply(v, rt, snap, BP, source=None) == v
    assert heal_apply(100, None, snap, BP) == 100


def test_a5_heal_received_range_is_declaration_driven() -> None:
    """声明区间收窄下界 → `−200` 被钳到 `−100`（无反转）；上界同理。"""
    snap = _snap()
    snap[BP]["healing_received_pct"] = -200
    rt = _runtime(snap, axes={HEAL_AXIS: {"min": -100, "max": 300}})
    assert heal_apply(100, rt, snap, BP, source=None) == 0
    snap[BP]["healing_received_pct"] = 999
    rt2 = _runtime(snap, axes={HEAL_AXIS: {"min": -200, "max": 50}})
    assert heal_apply(100, rt2, snap, BP, source=None) == 150


HEAL_AXIS = "healing_received_pct"


def test_a6_heal_received_shares_single_collection_point_with_grievous() -> None:
    """唯一收口：批48 重伤状态通道与受疗轴在 `heal_apply` 内**同轴相加**（不是两次乘）。"""
    snap = _snap()
    snap[BP]["healing_received_pct"] = 50
    grie = _status("s_grievous", -40)
    rt = _runtime(snap, defs={grie.id: grie})
    assert rt.apply_status(grie.id, BP, source=BN).applied is True
    # 50 + (−40) = +10 → 110（若两次乘则为 100×1.5×0.6 = 90）
    assert heal_apply(100, rt, snap, BP, source=None) == 110


# ===========================================================================
# B · 出疗轴（healing_done_pct）＋归并 heal_amp_pct 别名
# ===========================================================================
def test_b1_heal_done_positive_amplifies() -> None:
    """`+50` → 治疗 ×1.5；受疗 × 出疗叠乘（各自独立轴）。"""
    snap = _snap()
    snap[BP]["healing_done_pct"] = 50
    rt = _runtime(snap)
    assert heal_apply(100, rt, snap, BP, source=BP) == 150
    snap[BP]["healing_received_pct"] = 50
    assert heal_apply(100, rt, snap, BP, source=BP) == 225     # 1.5 × 1.5


def test_b2_legacy_heal_amp_pct_merges_into_axis_without_second_consumer() -> None:
    """`heal_amp_pct` 归并证据：经战斗桥等价换算为 `healing_done_pct`，行为一致。"""
    assert EFFECT_LEGACY_ALIASES["heal_amp_pct"] == ("healing_done_pct", 1.0)
    # 旧链路仍在（pct 层 pct["heal_amp"]），路由结果与批51 一致
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into({"heal_amp_pct": 40}, flat, pct)
    assert flat == {} and pct == {"heal_amp": 40.0}
    # 战斗桥归并：pct 层 → 新轴（只桥接，不重复消费旧键）
    assert combatant_updates(flat, pct) == {"healing_done_pct": 40.0}
    # 玩家档案端到端：带 heal_amp_pct 的装备 → combatant 的 healing_done_pct
    player = {
        "qid": "p1", "name": "P", "level": 5, "hp": 400, "max_hp": 1000,
        "mp": 50, "max_mp": 100,
        "attributes": {"base": {"atk": 100.0, "con": 50.0},
                       "bonus": {"flat": {}, "pct": {"heal_amp": 40}},
                       "temp": {}, "cond": {}},
    }
    assert _combatant_of(player)["healing_done_pct"] == 40
    # 归并后治疗量 = ×1.4（旧键从「零消费点」变为真生效；轴本身行为一致）
    snap = _snap()
    snap[BP]["healing_done_pct"] = 40
    assert heal_apply(100, _runtime(snap), snap, BP, source=BP) == 140


def test_b3_combatant_updates_default_signature_unchanged() -> None:
    """零变化：`combatant_updates(flat)`（不传 pct）与批51 及此前逐字段一致。"""
    flat = {"atk": 3.0, "absorb_hp": 25, "immune_dmg": 10, "healing_received_pct": -30}
    assert combatant_updates(flat) == combatant_updates(flat, None)
    assert combatant_updates(flat) == {
        "absorb_hp": 25.0, "immune_dmg": 10.0, "healing_received_pct": -30.0}


# ===========================================================================
# C · 承伤轴（damage_taken_pct）＋ immune_dmg 归并不双计
# ===========================================================================
def _taken(combatant: Mapping[str, Any], *, axes: Any = None) -> float:
    eng = BattleEngine(config={EFFECT_AXES_KEY: axes} if axes is not None else None)
    eng.start({"max_hp": 500, "hp": 500, "atk": 100, "dfn": 50, "con": 50},
              dict(combatant), random_seed=1)
    return eng._damage_taken_mult(BN)[0]


def test_c1_damage_taken_bidirectional() -> None:
    """`−25` → ×0.75（减伤）；`+25` → ×1.25（易伤）；`0` → ×1.0。"""
    assert _taken({"immune_dmg": 0, "damage_taken_pct": -25}) == 0.75
    assert _taken({"damage_taken_pct": 25}) == 1.25
    assert _taken({}) == 1.0


def test_c2_immune_dmg_alias_not_double_counted() -> None:
    """归并不双计：`immune_dmg=25` 单独 = ×0.75（与批22 逐值一致）；与新轴**同轴相加**，
    绝非两次叠乘（×0.75×0.75=0.5625 即双计）。"""
    assert _taken({"immune_dmg": 25}) == 0.75
    assert _taken({"damage_taken_pct": -25}) == 0.75
    both = _taken({"immune_dmg": 25, "damage_taken_pct": -25})
    assert both == 0.5
    assert both != 0.75 * 0.75
    # 免伤旧键 [0,100] 封顶保留（负数不反向变易伤）——与批22 口径一致
    assert _taken({"immune_dmg": -5}) == 1.0
    assert _taken({"immune_dmg": 250}) == 0.0


def test_c3_damage_taken_range_is_declaration_driven() -> None:
    """上/下钳按声明区间（C11）：`−50` 在 min=−10 下被钳为 −10 → ×0.9。"""
    got = _taken({"damage_taken_pct": -50},
                 axes={"damage_taken_pct": {"min": -10, "max": 300}})
    assert got == 0.9


def test_c4_effect_axis_value_clamps_and_defaults() -> None:
    """读点钳制辅助：缺省按登记表建议区间（−100~300），非法/缺失 → 0。"""
    assert effect_axis_value({"damage_taken_pct": -999}, "damage_taken_pct") == -100.0
    assert effect_axis_value({"damage_taken_pct": 999}, "damage_taken_pct") == 300.0
    assert effect_axis_value({}, "damage_taken_pct") == 0.0
    assert effect_axis_value({"damage_taken_pct": True}, "damage_taken_pct") == 0.0


def test_c5_damage_taken_end_to_end_and_immune_equivalence() -> None:
    """战斗级证据：`−25` 受伤 ×0.75 / `+25` ×1.25；`immune_dmg=25` 与 `damage_taken_pct=−25`
    终伤逐值一致（归并等价），且两者并存时终伤 = ×0.5（同轴相加，不是 ×0.5625 叠乘）。"""
    def _run(extra: Mapping[str, Any]) -> int:
        eng = BattleEngine().start(dict(PLAYER), dict(ENEMY, **extra), random_seed=7)
        out = eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
        return out.final_damage

    base = _run({})
    assert base > 0
    assert _run({"damage_taken_pct": -25}) == int(round(base * 0.75))
    assert _run({"damage_taken_pct": 25}) == int(round(base * 1.25))
    assert _run({"damage_taken_pct": -25}) == _run({"immune_dmg": 25})
    both = _run({"damage_taken_pct": -25, "immune_dmg": 25})
    assert both == int(round(base * 0.5))
    assert both != int(round(base * 0.75 * 0.75))
    # 零变化：显式传空声明段 → 与缺省逐值一致
    eng = BattleEngine(config={EFFECT_AXES_KEY: {}}).start(
        dict(PLAYER), dict(ENEMY), random_seed=7)
    out = eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
    assert out.final_damage == base


# ===========================================================================
# D · 零变化对拍（红线 C1）
# ===========================================================================
def _recursive_keys(obj: Any) -> List[str]:
    out: List[str] = []
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            out.append(str(k))
            out.extend(_recursive_keys(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out.extend(_recursive_keys(v))
    return out


_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _stable_json(obj: Any) -> str:
    text = json.dumps(obj, ensure_ascii=False, sort_keys=True, default=str)
    return _UUID_RE.sub("<uid>", text)


PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 50,
          "mag": 50, "spd": 50, "foc": 100, "con": 50, "str": 100, "int": 80,
          "agi": 50, "spr": 50, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400, "hp": 400, "max_mp": 0, "mp": 0, "atk": 80, "dfn": 40, "mag": 30,
         "spd": 40, "foc": 50, "con": 50, "str": 80, "int": 30, "agi": 40, "spr": 40,
         "lck": 10, "elem_atk": 0, "name": "E"}


def test_d1_battle_settlement_snapshot_zero_change() -> None:
    """红线 C1：未配置特效轴 → 同种子战斗结算快照逐字段一致，且不含任何特效轴键。"""
    eng = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=42)
    eng.player_act("normal")
    snap_a = eng.to_snapshot()
    eng_b = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=42)
    eng_b.player_act("normal")
    snap_b = eng_b.to_snapshot()
    assert _stable_json(snap_a) == _stable_json(snap_b)
    keys = set(_recursive_keys(snap_a))
    assert not (keys & set(GEAR_EFFECT_KEYS)), sorted(keys & set(GEAR_EFFECT_KEYS))
    assert keys, "战斗快照为空，对拍无意义"


def test_d2_extract_bonus_effect_keys_unchanged() -> None:
    """实例化对拍：特效轴键仍走 numeric/display 档（0/布尔丢弃），未新增键。"""
    got = extract_bonus({"healing_received_pct": -50, "healing_done_pct": 25,
                         "damage_taken_pct": -25, "damage_taken_pct_zero": 0,
                         "healing_received_pct_bool": True})
    assert got == {"healing_received_pct": -50.0, "healing_done_pct": 25.0,
                   "damage_taken_pct": -25.0}


# ===========================================================================
# E · 多源 heal 全覆盖（唯一收口：heal 原子 / absorb_heal / regen / lifesteal / absorb_hp）
# ===========================================================================
def test_e1_absorb_heal_and_regen_consume_received_axis() -> None:
    """行动收尾四路回复中的 absorb_heal / regen 同样经唯一收口（受疗侧）。"""
    snap = _snap(hp=400)
    snap[BP]["healing_received_pct"] = 50
    snap[BP]["defenses"] = {
        "absorb": {"record": 200, "value": 50, "pct": True, "active": True},
        "regen": {"value": 100},
    }
    rt = _runtime(snap)
    log = tick_turn_end(snap, rt)
    kinds = {str(e.get("type")): e for e in log if e.get("side") == BP}
    # absorb: 200×50% = 100 → ×1.5 = 150；regen: 100 → ×1.5 = 150
    assert kinds["absorb_heal"]["heal"] == 150
    assert kinds["regen"]["heal"] == 150
    assert snap[BP]["hp"] == 400 + 150 + 150


def test_e2_regen_negative_axis_reverses_to_damage() -> None:
    """负治疗反转在行动收尾回复同样生效（回血变扣血，下钳 0）。"""
    snap = _snap(hp=400)
    snap[BP]["healing_received_pct"] = -200
    snap[BP]["defenses"] = {"regen": {"value": 100}, "absorb": {"active": False}}
    rt = _runtime(snap)
    log = tick_turn_end(snap, rt)
    regen = [e for e in log if e.get("type") == "regen" and e.get("side") == BP]
    assert regen and regen[0]["heal"] == -100
    assert snap[BP]["hp"] == 300


def test_e3_battle_absorb_hp_consumes_both_axes() -> None:
    """battle.absorb_hp 吸血（攻击方回血）经唯一收口：受疗 + 出疗各自生效（贴数值）。"""
    def _run(extra: Mapping[str, Any]) -> Any:
        eng = BattleEngine().start(dict(PLAYER, absorb_hp=50, **extra), dict(ENEMY),
                                   random_seed=7)
        out = eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})
        fx = [e for e in (out.side_effects or []) if e.get("type") == "absorb_hp"]
        return out.final_damage, fx

    dmg, base_fx = _run({})
    assert base_fx and base_fx[0]["heal"] == int(dmg * 0.5), base_fx      # 旧行为：50% 吸血
    _, amp_fx = _run({"healing_received_pct": 50, "healing_done_pct": 50})
    # 22 × 1.5（受疗）= 33 → × 1.5（出疗）= 50（逐轴四舍五入，与 heal_apply 同口径）
    assert amp_fx[0]["heal"] == int(round(int(round(int(dmg * 0.5) * 1.5)) * 1.5))


def test_e4_lifesteal_action_consumes_both_axes() -> None:
    """effects Lifesteal 原子动作经唯一收口（施疗方 = 受疗方 = attacker）。"""
    snap = _snap(hp=400)
    snap[BP]["healing_received_pct"] = 50
    rt = _runtime(snap)
    res = execute_action({"type": "lifesteal", "value": 20, "target": "self",
                          "damage_dealt": 200}, _ctx(snap), rt)
    assert res.ok
    # 200×20% = 40 → ×1.5（受疗）= 60
    assert snap[BP]["hp"] == 460, snap[BP]["hp"]
