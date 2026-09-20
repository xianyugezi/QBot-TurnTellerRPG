"""批53 · 时序 / 资源 / 结算轴接线验收测试（P0 冷却 · 状态概率 · 层数 · P1 行动条/资源）。

口径：
  · `特效整理设计_1_修正轴全集.md` X27（冷却·占位键归并）/ X21（状态概率＋溢出转层）/
    X23（层数获取）/ X24（层数上限）/ X30（行动条推动）/ X34·X35（资源消耗·获取）/
    X22（状态抵抗）/ X03（会心倍率）；
  · `特效整理设计_3_落点与分期.md` §二「批 51」（旧编号 = 本批批53）；
  · `特效强度预算_设计.md` §四 红线守护（C1 缺省对拍 / C9 特效键不进面板轴 / C11 上下钳）；
  · 明确**排除** `action_speed` / `action_recovery`（数学互为倒数、必须二选一，待裁决 D2）。

覆盖：
  A. 冷却乘法轴 `cooldown_pct`：α3 同乘区一次缩放（双向）；旧占位键
     `cooldown_reduction_pct` 经聚合入口换算（旧键仍可用、**不双计**）；未配置零变化。
  B. 状态概率 `status_chance_pct`（+ `debuff_chance_pct` / `buff_chance_pct` 归并）
     ＋溢出转层；状态抵抗 `status_resist_pct`（攻/防两侧不合并）。
  C. 层数获取 `stack_gain_pct` ＋ 层数上限 `stack_cap_delta`（与批48 stacks 乘算对齐）。
  D. 行动条推动 `action_bar_shift`（复用 delay_actor / hasten_actor 双向原语）。
  E. 资源消耗 `resource_cost_pct` / 资源获取 `resource_gain_pct`（既有两处消费点）。
  F. 会心倍率 `crit_damage_pct`。
  G. 零变化对拍（红线 C1）：未配置任一特效轴 → 战斗结算快照逐字段一致、无特效轴键。

纪律：测试只构造内存对象（不写任何真实内容包）；匿名 id（s_*）；数值/区间全由测试内声明。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.resource_axis import RESOURCE_STATE_KEY, scale_amount_map
from qbot_rpg.core.effects import (
    STATUS_CHANCE_AXIS,
    STATUS_RESIST_AXIS,
    STACK_CAP_AXIS,
    STACK_GAIN_AXIS,
    DamageCtx,
    EffectRuntime,
    status_stat_modifier_sum,
)
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.player_attributes import PlayerAttributes
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.data.gear_stats import (
    EFFECT_AXES_KEY,
    EFFECT_LEGACY_ALIASES,
    GEAR_EFFECT_KEYS,
    combatant_updates,
    route_bonus_into,
    route_legacy_aliases_into_flat,
)
from qbot_rpg.data.item import ItemInstance

BP = "player"
BN = "enemy"

PLAYER = {"max_hp": 500, "hp": 500, "max_mp": 100, "mp": 100, "atk": 100, "dfn": 0,
          "mag": 50, "spd": 50, "foc": 100, "con": 0, "str": 100, "int": 80, "agi": 50,
          "spr": 0, "lck": 50, "elem_atk": 0, "name": "P"}
ENEMY = {"max_hp": 400000, "hp": 400000, "max_mp": 0, "mp": 0, "atk": 0, "dfn": 0,
         "mag": 0, "spd": 40, "foc": 0, "con": 0, "str": 0, "int": 0, "agi": 40,
         "spr": 0, "lck": 0, "elem_atk": 0, "name": "E"}


class _QueueRNG:
    """确定性随机源（命中/会心/格挡/乱数 4 判定固定序列）。"""

    def __init__(self, seq: Any) -> None:
        self.seq = list(seq)
        self.i = 0

    def random(self) -> float:
        v = self.seq[self.i]
        self.i = (self.i + 1) % len(self.seq)
        return v


# ===========================================================================
# A · 冷却乘法轴（X27 `cooldown_pct`）+ 占位旧键归并不双计
# ===========================================================================
_SKILL = {"id": "s1", "name": "火球", "tag": "combo", "power": 100, "cooldown": 10}


def _run_cd(extra: Mapping[str, Any], *, axes: Any = None, amp: Any = None) -> Dict[str, int]:
    cfg: Dict[str, Any] = {"combo_enforce_mp": True}
    if axes is not None:
        cfg[EFFECT_AXES_KEY] = axes
    if amp is not None:
        cfg["equip_skill_amp"] = amp
    eng = BattleEngine(defs={"s1": _SKILL}, config=cfg)
    eng._rng = _QueueRNG([0.5, 0.5, 0.5, 1.0])  # noqa: SLF001
    eng.start(dict(PLAYER, **dict(extra)), dict(ENEMY), random_seed=1)
    eng.do_action("player", {"type": "skill", "skill_id": "s1", "tag": "combo",
                             "mult": 1.0})
    return dict(eng._snap.get("skill_cooldowns", {}).get("player", {}))  # noqa: SLF001


def test_a1_cooldown_axis_bidirectional() -> None:
    """`+100` → 冷却 ×2（10→20）；`−50` → ×0.5（10→5）；`0` → 原值。"""
    assert _run_cd({"cooldown_pct": 0}) == {"s1": 10}
    assert _run_cd({"cooldown_pct": 100}) == {"s1": 20}
    assert _run_cd({"cooldown_pct": -50}) == {"s1": 5}


def test_a2_cooldown_axis_single_multiplier_with_alpha3() -> None:
    """与 α3 在**同一乘区**相加后一次缩放（不是两次乘）：−25 轴 + −25 α3 → ×0.5。"""
    amp = {"player": {"s1": {"cooldown": -25}}}
    assert _run_cd({"cooldown_pct": -25}, amp=amp) == {"s1": 5}
    # 若两次乘会得到 round(10×0.75×0.75)=6 —— 断言不是 6
    assert _run_cd({"cooldown_pct": -25}, amp=amp) != {"s1": 6}


def test_a3_cooldown_axis_result_never_negative() -> None:
    """下钳：轴 −9999 被声明区间钳到 −80 → ×0.2 → 2（负冷却不可达）。"""
    assert _run_cd({"cooldown_pct": -9999}) == {"s1": 2}


def test_a4_placeholder_alias_still_usable_and_not_double_counted() -> None:
    """旧占位键 `cooldown_reduction_pct` 归并证据（唯一换算处 → 不双计）。"""
    assert EFFECT_LEGACY_ALIASES["cooldown_reduction_pct"] == ("cooldown_pct", -1.0)
    # route_bonus_into 契约不变：占位键不进 flat / pct（既有测试钉死）
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into({"cooldown_reduction_pct": 30}, flat, pct)
    assert flat == {} and pct == {}
    # 唯一换算点：旧键 30 → flat["cooldown_pct"] = −30，且只写一次
    route_legacy_aliases_into_flat({"cooldown_reduction_pct": 30}, flat)
    assert flat == {"cooldown_pct": -30.0}
    assert combatant_updates(flat) == {"cooldown_pct": -30.0}
    # 新旧同轴相加（各声明一次 = 各一份贡献，不是旧键算两遍）
    flat2: Dict[str, float] = {}
    route_bonus_into({"cooldown_pct": -10}, flat2, {})
    route_legacy_aliases_into_flat({"cooldown_reduction_pct": 30}, flat2)
    assert flat2 == {"cooldown_pct": -40.0}
    assert combatant_updates(flat2) == {"cooldown_pct": -40.0}


def test_a5_placeholder_alias_end_to_end_from_item() -> None:
    """旧键端到端：带 `cooldown_reduction_pct` 的装备 → 聚合 flat → combatant → 冷却缩短。"""
    bonus = {"cooldown_reduction_pct": 30}
    row = ItemInstance(item_id="sword", name="sword", count=1, quality="normal",
                       bound=False, stack_max=1, slot="weapon", stats_bonus=dict(bonus))
    attrs = PlayerAttributes(base={"atk": 10, "hp": 100})
    player: Dict[str, Any] = {
        "qid": "p1", "name": "P", "level": 5, "hp": 500, "max_hp": 500,
        "mp": 100, "max_mp": 100,
        "inventory": [row],
        "equipment": {"weapon": {"item_id": "sword", "uid": row.uid}},
        "attributes": attrs,
    }
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    bonus_out = eng.aggregate_bonus(player)
    assert bonus_out["flat"].get("cooldown_pct") == -30.0
    assert "cooldown_reduction_pct" not in bonus_out["flat"]
    # 战斗桥 → combatant（玩家档案口径）
    assert _combatant_of(player)["cooldown_pct"] == -30


def test_a6_cooldown_range_declaration_driven() -> None:
    """上/下钳按包声明（C11）：声明 min=−10 → 轴 −80 被钳为 −10 → ×0.9 → 9。"""
    axes = {"cooldown_pct": {"min": -10, "max": 200}}
    assert _run_cd({"cooldown_pct": -80}, axes=axes) == {"s1": 9}


def test_a7_cooldown_absent_is_identical() -> None:
    """未配置轴 → 与 α3 基线逐字段一致（红线 C1）。"""
    assert _run_cd({}) == {"s1": 10}
    amp = {"player": {"s1": {"cooldown": -50}}}
    assert _run_cd({}, amp=amp) == {"s1": 5}
    assert _run_cd({"cooldown_pct": 0}, amp=amp) == {"s1": 5}


# ===========================================================================
# B · 状态概率（X21 status_chance_pct + 归并 debuff/buff_chance_pct）＋ 状态抵抗（X22）
# ===========================================================================
class _Def:
    def __init__(self, raw: Dict[str, Any]) -> None:
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def _status_def(sid: str, *, frame: str = "stack", max_stack: int = 5,
                hit_rate: int = 100) -> _Def:
    return _Def({
        "id": sid, "name": sid, "class": "status", "category": "weak",
        "stack_frame": frame, "max_stack": max_stack, "hit_rate": hit_rate,
        "duration": {"turns": 3, "charges": 0},
        "actions": [{"type": "stat_modifier", "stat": "atk", "value": 10}],
    })


def _rt(defs: Mapping[str, Any], *, axes: Any = None, resist: Any = None) -> EffectRuntime:
    return EffectRuntime(
        status_state={BP: [], BN: []},
        resist_table=resist if resist is not None else {BP: {}, BN: {}},
        defs=dict(defs),
        config=({EFFECT_AXES_KEY: axes} if axes is not None else None),
    )


def _ctx(*, bp_extra: Any = None, bn_extra: Any = None, rng: float = 0.5,
         source: str = BP, target: str = BN) -> DamageCtx:
    snap = {
        BP: {"max_hp": 1000, "hp": 1000},
        BN: {"max_hp": 1000, "hp": 1000},
    }
    snap[source] = {**snap.get(source, {}), **dict(bp_extra or {})}
    snap[target] = {**snap.get(target, {}), **dict(bn_extra or {})}
    return DamageCtx(raw_damage=0, attack_type="skill", attacker=source,
                     target=target, snapshot=snap,
                     variables={"rng": _QueueRNG([rng, rng, rng, rng])})


def _apply(rt: EffectRuntime, sid: str, ctx: DamageCtx) -> Any:
    return rt.apply_status(sid, ctx.target, source=ctx.attacker,
                           attacker=ctx.attacker, ctx=ctx)


def test_b1_status_chance_bidirectional() -> None:
    """`+100` 更易挂上 / 负向更难挂上（基准 25%）；`0` 与接线前同值。"""
    d = {"s_x": _status_def("s_x", hit_rate=25)}
    # +100 → 有效 50%：rnd 0.4 → 命中；rnd 0.6 → miss
    assert _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 100}, rng=0.4)).applied
    assert not _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 100}, rng=0.6)).applied
    # −100 → 有效 0%（必 miss，rnd 0.5）；0 → 基线 25%（rnd 0.5 miss / rnd 0.1 hit）
    assert not _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: -100}, rng=0.5)).applied
    assert not _apply(_rt(d), "s_x", _ctx(rng=0.5)).applied
    assert _apply(_rt(d), "s_x", _ctx(rng=0.1)).applied


def test_b2_status_chance_overflow_to_extra_stacks() -> None:
    """X21 溢出转层：基准 100% + （+100 / +200 / +50）→ 首层 2 / 3 / 1 层。"""
    d = {"s_x": _status_def("s_x", max_stack=5)}
    r1 = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 100}, rng=0.99))
    assert r1.applied and r1.instance["stacks"] == 2
    r2 = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 200}, rng=0.99))
    assert r2.instance["stacks"] == 3
    r3 = _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 50}, rng=0.99))
    assert r3.instance["stacks"] == 1
    # 未配置轴 → 首层 1（零变化）
    assert _apply(_rt(d), "s_x", _ctx(rng=0.99)).instance["stacks"] == 1


def test_b3_legacy_debuff_buff_chance_merge_into_status_domain() -> None:
    """归并证据：`debuff_chance_pct` / `buff_chance_pct` 经 pct 层 → 同一轴（不双计）。"""
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into({"debuff_chance_pct": 25, "buff_chance_pct": 25}, flat, pct)
    assert flat == {} and pct == {"debuff_chance": 25.0, "buff_chance": 25.0}
    # 战斗桥把两旧键各折一次进同一轴（各一份贡献 = 50，不是某键算两遍）
    assert combatant_updates(flat, pct) == {STATUS_CHANCE_AXIS: 50.0}
    # 端到端：归并后的轴值确实抬高命中概率（基准 25 + 50 → 37.5%，rnd 0.3 命中）
    d = {"s_x": _status_def("s_x", hit_rate=25)}
    assert _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 50}, rng=0.3)).applied
    assert not _apply(_rt(d), "s_x", _ctx(bp_extra={STATUS_CHANCE_AXIS: 50}, rng=0.4)).applied


def test_b4_status_resist_bidirectional_and_extends_resist_table() -> None:
    """X22：target 侧 `+50` → 抵抗 +50 点（更难挂）；`−50` → 归零（更易挂）；
    并**扩展既有 resist_table**（20 + 30 = 50）。"""
    d = {"s_x": _status_def("s_x")}
    # +50：resist 0→50 → 有效 50%，rnd 0.6 miss / rnd 0.4 hit
    assert not _apply(_rt(d), "s_x",
                      _ctx(bn_extra={STATUS_RESIST_AXIS: 50}, rng=0.6)).applied
    assert _apply(_rt(d), "s_x",
                  _ctx(bn_extra={STATUS_RESIST_AXIS: 50}, rng=0.4)).applied
    # 扩展既有 resist_table：基础 20 + 轴 30 = 50
    rt = _rt(d, resist={BP: {}, BN: {"s_x": 20}})
    assert not _apply(rt, "s_x",
                      _ctx(bn_extra={STATUS_RESIST_AXIS: 30}, rng=0.6)).applied
    # −50：resist 归零 → 恢复必中
    assert _apply(_rt(d), "s_x",
                  _ctx(bn_extra={STATUS_RESIST_AXIS: -50}, rng=0.99)).applied
    # 未配置 → 原值（rnd 0.99 必中）
    assert _apply(_rt(d), "s_x", _ctx(rng=0.99)).applied


def test_b5_attack_and_defense_sides_are_independent() -> None:
    """X21 与 X22 是攻/防两侧，**不合并**：高命中 + 高抗性可同时存在。"""
    d = {"s_x": _status_def("s_x")}
    ctx = _ctx(bp_extra={STATUS_CHANCE_AXIS: 100},
               bn_extra={STATUS_RESIST_AXIS: 50}, rng=0.7)
    # 基准 100% → 命中 ±100 = 200；抗性 +50 → 有效 100% → 命中
    assert _apply(_rt(d), "s_x", ctx).applied


# ===========================================================================
# C · 层数获取（X23）＋ 层数上限（X24），与批48 stacks 乘算对齐
# ===========================================================================
def test_c1_stack_gain_bidirectional() -> None:
    """`+100` → 每次 +2 层；`0` → +1 层；负值下钳 0 层（状态仍成立）。"""
    d = {"s_x": _status_def("s_x", max_stack=9)}
    rt = _rt(d)
    _apply(rt, "s_x", _ctx(source="p1", bp_extra={STACK_GAIN_AXIS: 100}, rng=0.99))
    inst = rt.status_instances(BN)[0]
    assert inst["stacks"] == 2
    _apply(rt, "s_x", _ctx(source="p2", bp_extra={STACK_GAIN_AXIS: 100}, rng=0.99))
    assert inst["stacks"] == 4
    # 负向：−100 → 增量 0（不涨层），但施加仍成功
    rt2 = _rt(d)
    r = _apply(rt2, "s_x", _ctx(bp_extra={STACK_GAIN_AXIS: -100}, rng=0.99))
    assert r.applied and rt2.status_instances(BN)[0]["stacks"] == 1


def test_c2_stack_cap_delta_raises_limit() -> None:
    """X24 上限加算：max_stack=1 的状态 + target 侧 +2 → 可叠到 3 层。"""
    d = {"s_x": _status_def("s_x", max_stack=1)}
    rt = _rt(d)
    for i in range(4):
        _apply(rt, "s_x", _ctx(source=f"p{i}",
                               bn_extra={STACK_CAP_AXIS: 2}, rng=0.99))
    inst = rt.status_instances(BN)[0]
    assert inst["stacks"] == 3            # 1 + 2，封顶后不再涨
    # 负向：−1 → 上限钳到 ≥1 → 保持 1 层
    rt2 = _rt(d)
    for i in range(3):
        _apply(rt2, "s_x", _ctx(source=f"q{i}",
                                bn_extra={STACK_CAP_AXIS: -1}, rng=0.99))
    assert rt2.status_instances(BN)[0]["stacks"] == 1


def test_c3_stack_axes_align_with_batch48_stacks_multiplier() -> None:
    """与批48 对齐：层数轴改的是 stacks，`status_stat_modifier_sum` 按 stacks 乘算。"""
    d = {"s_x": _status_def("s_x", max_stack=5)}
    rt = _rt(d)
    _apply(rt, "s_x", _ctx(bp_extra={STACK_GAIN_AXIS: 100}, rng=0.99))
    inst = rt.status_instances(BN)[0]
    assert inst["stacks"] == 2
    # stat_modifier atk=10 按 stacks=2 乘算 → 20
    assert status_stat_modifier_sum(rt, BN, "atk") == 20.0
    # 未配置 → stacks=1 → 10（零变化）
    rt2 = _rt(d)
    _apply(rt2, "s_x", _ctx(rng=0.99))
    assert status_stat_modifier_sum(rt2, BN, "atk") == 10.0


def _run_shift(shift: float, *, axes: Any = None) -> Any:
    """跑一次普攻并返回 (battle_time, player.next_ready, 调度器原语调用记录)。"""
    eng = BattleEngine(config=({EFFECT_AXES_KEY: axes} if axes is not None else None))
    eng._rng = _QueueRNG([0.5] * 8)  # noqa: SLF001
    p = {"max_hp": 900, "hp": 900, "atk": 100, "dfn": 50, "spd": 10,
         "foc": 50, "con": 50, "lck": 50}
    if shift:
        p["action_bar_shift"] = shift
    e = {"max_hp": 9000, "hp": 9000, "atk": 0, "dfn": 50, "spd": 8,
         "foc": 0, "con": 50, "lck": 0}
    eng.start(p, e, random_seed=1)
    calls: Any = []
    _h, _d = eng._ctb.hasten_actor, eng._ctb.delay_actor  # noqa: SLF001

    def _spy_h(a: str, b: float = 0.0) -> Any:
        calls.append(("hasten", str(a), float(b)))
        return _h(a, b)

    def _spy_d(a: str, b: float = 0.0) -> Any:
        calls.append(("delay", str(a), float(b)))
        return _d(a, b)

    eng._ctb.hasten_actor = _spy_h  # noqa: SLF001
    eng._ctb.delay_actor = _spy_d  # noqa: SLF001
    eng.player_act("normal")
    ready = float(eng._ctb.get_actor("player").next_ready)  # noqa: SLF001
    return float(eng.battle_time), ready, calls


def test_d1_action_bar_shift_bidirectional() -> None:
    """X30：正 = 提前（hasten，next_ready −N）；负 = 延后（delay，+N）；0 = 零变化。"""
    _bt0, r0, c0 = _run_shift(0)
    _btp, rp, cp = _run_shift(100)
    _btn, rn, cn = _run_shift(-100)
    assert ("hasten", BP, 100.0) in cp, cp
    assert ("delay", BP, 100.0) in cn, cn
    assert not any(c[1] == BP for c in c0), c0            # 未配置 → 不调用原语
    assert rp == r0 - 100.0
    assert rn == r0 + 100.0
    assert _btp == rp and _btn == rn                      # 收口 = 推动后的 ready


def test_d2_action_bar_shift_range_declaration_driven() -> None:
    """声明区间钳制（C11）：min/max=±50 → 越界轴值被钳后再推动。"""
    axes = {"action_bar_shift": {"min": -50, "max": 50}}
    _bt, r_hi, c_hi = _run_shift(999, axes=axes)
    _bt2, r_lo, c_lo = _run_shift(-999, axes=axes)
    assert ("hasten", BP, 50.0) in c_hi, c_hi
    assert ("delay", BP, 50.0) in c_lo, c_lo
    _bt0, r0, _ = _run_shift(0)
    assert r_hi == r0 - 50.0 and r_lo == r0 + 50.0


_RAGE_REG = {"rage": {"name": "怒气", "type": "resource", "base": 0, "max": 100}}


def _res_engine(*, cost: int = 10, gain: int = 5, state: int = 50,
                player_extra: Any = None) -> Any:
    defs = {"s1": {"id": "s1", "name": "技", "type": "active", "kind": "damage",
                   "power": 100, "energy_cost": {"rage": cost},
                   "energy_gain": {"rage": gain}}}
    eng = BattleEngine(defs=defs)
    p = {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100, "atk": 50,
         "def": 30, "spd": 10, "name": "P", **dict(player_extra or {})}
    e = {"hp": 500, "max_hp": 500, "mp": 0, "max_mp": 0, "atk": 0, "def": 0,
         "spd": 8, "name": "E"}
    eng.start(p, e, random_seed=1)
    eng._resource_registry = _RAGE_REG  # noqa: SLF001
    eng._snap["resource_state"] = {"player": {"rage": state}, "enemy": {}}  # noqa: SLF001
    out = eng.do_action("player", {"type": "skill", "skill_id": "s1"})
    return out, int(eng._snap["resource_state"]["player"]["rage"])  # noqa: SLF001


def test_e1_resource_axes_bidirectional() -> None:
    """X34/X35 双向：−50% 消耗（10→5）/ +100% 获取（5→10）；基准 = 50−10+5。"""
    out0, r0 = _res_engine()
    assert out0.ok is True and r0 == 45
    out_c, r_c = _res_engine(player_extra={"resource_cost_pct": -50})
    assert out_c.ok is True and r_c == 50            # 50 − 5 + 5
    out_g, r_g = _res_engine(player_extra={"resource_gain_pct": 100})
    assert out_g.ok is True and r_g == 50            # 50 − 10 + 10
    # 未配置 → 与基线逐字段一致
    out_n, r_n = _res_engine(player_extra={"resource_cost_pct": 0,
                                           "resource_gain_pct": 0})
    assert out_n.ok is True and r_n == r0 == 45


def test_e2_resource_cost_axis_gates_and_clamps() -> None:
    """‑100% = 零耗（下钳，不可为负）；门禁用同一缩放（不足仍被拒）。"""
    out_hi, r_hi = _res_engine(player_extra={"resource_cost_pct": -100})
    assert out_hi.ok is True and r_hi == 55          # 只加不减
    # 不足场景：起始 3，cost 10 → 被拒；cost 轴 −80% → 实际 cost 2 ≤ 3 → 放行
    out_rej, r_rej = _res_engine(state=3)
    assert out_rej.ok is False and r_rej == 3
    out_ok, r_ok = _res_engine(state=3, player_extra={"resource_cost_pct": -80})
    assert out_ok.ok is True and r_ok == 6           # 3 − 2 + 5
    # 越界轴值按声明区间钳制（min −100）→ 仍是零耗，不出现负消耗
    _out, r_cl = _res_engine(player_extra={"resource_cost_pct": -9999})
    assert r_cl == 55


def test_e3_scale_amount_map_default_identity_and_consumers() -> None:
    """唯一缩放处：`mult=1.0` 与既有归一逐字段一致；check/pay/gain 三点同源。"""
    assert scale_amount_map({"rage": 10, "hp": 0}, 1.0) == {"rage": 10, "hp": 0}
    assert scale_amount_map({"rage": 10}, 0.5) == {"rage": 5}
    assert scale_amount_map({"rage": 3}, 0.5) == {"rage": 2}      # round
    assert scale_amount_map({"rage": 10}, -1.0) == {"rage": 0}    # 下钳 0
    # 门禁与扣减同倍率（同一 ctx，先 check 后 pay）
    from qbot_rpg.core import resource_axis as ra

    ctx = {"stats": _RAGE_REG, RESOURCE_STATE_KEY: {"player": {"rage": 50}}}
    assert ra.check_cost(ctx, "rage", {"rage": 10}, mult=0.5)["ok"] is True
    ra.pay_cost(ctx, "rage", {"rage": 10}, mult=0.5)
    assert ctx[RESOURCE_STATE_KEY]["player"]["rage"] == 45
    ra.gain_energy(ctx, "rage", {"rage": 5}, mult=2.0)
    assert ctx[RESOURCE_STATE_KEY]["player"]["rage"] == 55
    # 获取轴负向：−100% → 不入账
    ra.gain_energy(ctx, "rage", {"rage": 5}, mult=0.0)
    assert ctx[RESOURCE_STATE_KEY]["player"]["rage"] == 55


def _run_crit(extra: Any, *, axes: Any = None) -> Any:
    eng = BattleEngine(config=({EFFECT_AXES_KEY: axes} if axes is not None else None))
    eng.start(dict(PLAYER, **dict(extra)), dict(ENEMY), random_seed=7)
    return eng._resolve_damage_action("player", {"type": "normal", "mult": 1.0})  # noqa: SLF001


def test_f1_crit_damage_axis_bidirectional() -> None:
    """X03：`+100` → 会心倍率 ×2；`−50` → ×0.5；`0` → 原值（终伤同向）。"""
    base = _run_crit({})
    hi = _run_crit({"crit_damage_pct": 100})
    lo = _run_crit({"crit_damage_pct": -50})
    assert base.crit_mult > 0
    assert hi.crit_mult == base.crit_mult * 2.0
    assert lo.crit_mult == base.crit_mult * 0.5
    assert hi.final_damage > base.final_damage
    assert lo.final_damage < base.final_damage
    # 未配置 / 显式 0 → 与基线逐值一致（红线 C1）
    assert _run_crit({"crit_damage_pct": 0}).final_damage == base.final_damage
    assert _run_crit({"crit_damage_pct": 0}).crit_mult == base.crit_mult


def test_f2_crit_damage_range_declaration_driven() -> None:
    """声明区间钳制（C11）：max=50 → `+9999` 被钳为 +50 → ×1.5。"""
    base = _run_crit({})
    got = _run_crit({"crit_damage_pct": 9999},
                    axes={"crit_damage_pct": {"min": -100, "max": 50}})
    assert got.crit_mult == base.crit_mult * 1.5


def test_g1_battle_snapshot_zero_change_no_axis_keys() -> None:
    """红线 C1：未配置特效轴 → 战斗结算快照逐字段一致、且不含任何特效轴键。"""
    def _snap() -> Any:
        eng = BattleEngine().start(dict(PLAYER), dict(ENEMY), random_seed=42)
        eng.player_act("normal")
        return eng.to_snapshot()

    import json
    import re

    def _normalize(text: str) -> str:
        # 快照含真实墙钟时间戳（`…T00:47:30Z` 形态）；两次 `_snap()` 若跨秒边界会假阳性失败
        # （批55 全量跑实测：`…:30Z` vs `…:29Z`）。与 uid 同属「非确定性字段」，一并归一。
        text = re.sub(r"[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}", "<uid>", text)
        return re.sub(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", "<ts>", text)

    text_a = _normalize(json.dumps(_snap(), ensure_ascii=False, sort_keys=True, default=str))
    text_b = _normalize(json.dumps(_snap(), ensure_ascii=False, sort_keys=True, default=str))
    assert text_a == text_b

    def _keys(obj: Any) -> Any:
        out = []
        if isinstance(obj, Mapping):
            for k, v in obj.items():
                out.append(str(k))
                out.extend(_keys(v))
        elif isinstance(obj, (list, tuple)):
            for v in obj:
                out.extend(_keys(v))
        return out

    keys = set(_keys(_snap()))
    assert keys and not (keys & set(GEAR_EFFECT_KEYS)), sorted(keys & set(GEAR_EFFECT_KEYS))
