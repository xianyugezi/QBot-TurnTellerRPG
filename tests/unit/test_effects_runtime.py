"""效果系统运行时自测（M1 战斗核心 · 细化_1b 验收 B/C/D 组 + I7 + L0 + battle 接线）。

依据：细化_1b_效果系统契约 §2（拦截链 8 阶段）/§4（四模型 S/D/R/I）/§5（验收用例）
+ 定稿 §3.4/§4.1/§6.1-6.4/§7 + 细化_1d_印记系统契约 §3.2/§4.2。

断言组：B-1..B-9（拦截链）、C-1/C-3/C-6/C-9/C-10（四模型）、D-1/D-2/D-3/D-5（免疫）、
I7（免死约束）、L0（mark_add/mark_remove/heal/proc/interrupt）、battle.py 接线。
"""
import warnings

import pytest

from qbot_rpg.core.battle import BattleEngine
from qbot_rpg.core.effects import (
    DamageCtx,
    DamagePipeline,
    EffectRuntime,
    execute_action,
    execute_proc_action,
    tick_turn_end,
)


# ---------------- 建造与工具 ----------------


def base_defenses():
    return {
        "mitigation": [],
        "shield": {"value": 0, "remaining": 0, "turns": 0, "max": 0},
        "reflect": {"value": 0, "pct": True, "active": False},
        "absorb": {"value": 0, "pct": True, "record": 0, "active": False},
        "fatal_immune": {"count": 0, "max": 0},
        "non_fatal_immune": {"active": False, "count": 0},
        "guts": {"count": 0, "max": 0},
        "immune": {"status": False, "damage": False, "interrupt": False, "all": False, "block_debuff": True},
        "mount": {"remaining": 0},
    }


def base_snapshot(enemy_hp=1000):
    dp, de = base_defenses(), base_defenses()  # 每侧独立防御行（防共享引用串扰）
    return {
        "session_type": "battle",
        "turn": 1,
        "player": {"max_hp": 1000, "hp": 1000, "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "name": "p", "defenses": dp},
        "enemy": {"max_hp": 1000, "hp": enemy_hp, "atk": 100, "dfn": 50, "mag": 50, "spd": 50, "name": "e", "defenses": de},
        "status_state": {"player": [], "enemy": []},
        "marks_state": {"player": [], "enemy": []},
        "resist_table": {"player": {}, "enemy": {}},
        "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}}, "enemy": {"per_turn": {}, "per_battle": {}}},
        "effect_cooldowns": {"player": {}, "enemy": {}},
        "formula_state": {},
    }


@pytest.fixture
def ctx(seeded_rng):
    """DamageCtx 工厂（D6 SED-4 迁移③：缺省 rng 经 seeded_rng() 注入，禁内联 random.Random(N)）。"""
    def _ctx(snap, raw, atype="skill", attacker="player", target="enemy", **vars_):
        v = dict(vars_)
        v.setdefault("rng", seeded_rng())
        return DamageCtx(raw_damage=raw, attack_type=atype, attacker=attacker, target=target,
                         snapshot=snap, variables=v)
    return _ctx


class _Def:
    """最小 Def 桩（镜像 frozen Def：id/name/raw，registry 直连测试）。"""

    def __init__(self, raw):
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def sdef(id_, name, frame="single", value=1, cat="weak", **kw):
    raw = {"id": id_, "name": name, "class": "status", "category": cat,
           "stack_frame": frame, "actions": [{"type": "none", "value": value}]}
    raw.update(kw)
    return _Def(raw)


def edef(id_, type_, value=None, **kw):
    raw = {"id": id_, "name": id_, "class": "effect", "type": type_}
    if value is not None:
        raw["value"] = value
    raw.update(kw)
    return _Def(raw)


def mdef(id_, polarity="positive", max_stack=3, duration="battle"):
    raw = {"id": id_, "name": id_, "icon": "x", "type": "mark", "max_stack": max_stack,
           "appliable_to": ["self", "enemy"], "polarity": polarity, "duration": duration}
    return _Def(raw)


def eff_rt(**defs):
    return EffectRuntime(defs=defs)


class AlwaysZero:
    def random(self):
        return 0.0


class AlwaysHigh:
    def random(self):
        return 0.9


pipe = DamagePipeline()


# ---------------- B 组 · 伤害拦截链 8 阶段（细化_1b §5 B-1..B-9） ----------------


def test_b1_mitigation_10pct(ctx):
    snap = base_snapshot()
    snap["enemy"]["defenses"]["mitigation"] = [{"value": 10, "scope": "all"}]
    r = pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    assert r.final_damage == 90 and r.target_hp == 910


def test_b2_shield_first(ctx):
    snap = base_snapshot()
    snap["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    r = pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    assert r.final_damage == 70 and r.target_hp == 930
    assert snap["enemy"]["defenses"]["shield"]["remaining"] == 0


def test_b3_reflect_and_no_rereflect(ctx, seeded_rng):
    snap = base_snapshot()
    snap["enemy"]["defenses"]["reflect"] = {"value": 20, "pct": True, "active": True}
    r = pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    refl = [e for e in r.side_effects if e["type"] == "reflect"]
    assert len(refl) == 1 and refl[0]["damage"] == 20 and refl[0]["target"] == "player"
    snap2 = base_snapshot()
    snap2["player"]["defenses"]["reflect"] = {"value": 30, "pct": True, "active": True}
    sub = DamageCtx(raw_damage=20, attack_type="basic", attacker="enemy", target="player",
                    snapshot=snap2, variables={"is_reflect_damage": True, "rng": seeded_rng()})
    r2 = pipe.damage_pipeline(sub, EffectRuntime())
    assert not [e for e in r2.side_effects if e["type"] == "reflect"]


def test_b4_absorb_record_and_heal_at_turn_end(ctx):
    snap = base_snapshot()
    snap["enemy"]["defenses"]["absorb"] = {"value": 50, "pct": True, "record": 0, "active": True}
    snap["enemy"]["defenses"]["shield"] = {"value": 40, "remaining": 40, "turns": 2, "max": 40}
    pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    assert snap["enemy"]["defenses"]["absorb"]["record"] == 100  # 盾挡的伤害也计入（定稿 §3.3）
    log = tick_turn_end(snap, EffectRuntime())
    heal = [e for e in log if e["type"] == "absorb_heal"]
    assert len(heal) == 1 and heal[0]["heal"] == 50 and snap["enemy"]["hp"] == 990


def test_b5_fatal_immune_full_exemption(ctx):
    snap = base_snapshot(enemy_hp=500)
    snap["enemy"]["defenses"]["fatal_immune"] = {"count": 1, "max": 1}
    rt = EffectRuntime()
    r = pipe.damage_pipeline(ctx(snap, 999), rt)
    assert r.final_damage == 0 and r.target_hp == 500
    assert rt.trigger_counts("enemy", "fatal_immune")[1] == 1


def test_b6_guts_locks_hp_1(ctx):
    snap = base_snapshot(enemy_hp=100)
    snap["enemy"]["defenses"]["guts"] = {"count": 1, "max": 1}
    r = pipe.damage_pipeline(ctx(snap, 999), EffectRuntime())
    assert r.target_hp == 1 and snap["enemy"]["hp"] == 1
    assert snap["enemy"]["defenses"]["guts"]["count"] == 0


def test_b7_death_check(ctx):
    snap = base_snapshot(enemy_hp=40)
    r = pipe.damage_pipeline(ctx(snap, 50), EffectRuntime())
    assert r.target_hp == 0
    assert any(e["type"] == "death" for e in r.side_effects)


def test_b8_fatal_immune_before_guts(ctx):
    snap = base_snapshot(enemy_hp=100)
    snap["enemy"]["defenses"]["fatal_immune"] = {"count": 1, "max": 1}
    snap["enemy"]["defenses"]["guts"] = {"count": 1, "max": 1}
    r = pipe.damage_pipeline(ctx(snap, 999), EffectRuntime())
    assert r.final_damage == 0 and snap["enemy"]["defenses"]["guts"]["count"] == 1


def test_b9_abnormal_order_warns():
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        DamagePipeline(order=("death_check", "apply_damage", "mitigation", "shield", "reflect",
                              "absorb", "fatal_immune", "guts"))
    assert any("异常顺序" in str(x.message) for x in w)


# ---------------- C 组 · 四模型判定（细化_1b §5 C-1/C-3/C-6/C-9/C-10） ----------------


def test_c1_single_high_covers_low():
    rt = eff_rt(atk_low=sdef("atk_low", "降攻低", frame="single", value=1),
                atk_high=sdef("atk_high", "降攻高", frame="single", value=2))
    rt.apply_status("atk_low", "enemy", source="a", attacker="player", force=True)
    res = rt.apply_status("atk_high", "enemy", source="a", attacker="player", force=True)
    assert res.applied and rt.find_status("enemy", "atk_high") is not None


def test_c3_stack_to_max_stack():
    rt = eff_rt(st=sdef("st", "叠层", frame="stack", max_stack=3))
    for src in ("a", "b", "c", "d"):  # S5 同来源同侧只保留一个 → 叠层需不同来源
        rt.apply_status("st", "enemy", source=src, attacker="player", force=True)
    inst = rt.find_status("enemy", "st")
    assert inst is not None and inst["stacks"] == 3


def test_c6_halve_sequence():
    rt = eff_rt(poison=sdef("poison", "中毒", decay="halve", value=20, duration={"turns": 5, "charges": 0}))
    rt.apply_status("poison", "enemy", source="a", attacker="player", force=True)
    seq = []
    for _ in range(4):
        rt.decay_carrier("enemy")
        seq.append(rt.find_status("enemy", "poison")["value"])
    assert seq == [10, 5, 2, 1]


def test_c9_dual_duration_dimensions():
    rt = eff_rt(c=sdef("c", "次数限", duration={"turns": 0, "charges": 10}))
    rt.apply_status("c", "enemy", source="a", attacker="player", force=True)
    for _ in range(10):
        rt.tick_trigger("enemy", "c")
    assert rt.find_status("enemy", "c") is None  # 回合0+次数10 → 触发10次消失

    rt = eff_rt(t=sdef("t", "回合限", duration={"turns": 10, "charges": 0}))
    rt.apply_status("t", "enemy", source="a", attacker="player", force=True)
    for _ in range(5):
        rt.tick_trigger("enemy", "t")  # 次数0 → 触发不扣
    still = rt.find_status("enemy", "t")
    for _ in range(10):
        rt.tick_turns("enemy")
    assert still is not None and rt.find_status("enemy", "t") is None  # 回合10 → 回合末10次后消失

    rt = eff_rt(e=sdef("e", "永续", duration={"turns": -1, "charges": 0}))
    rt.apply_status("e", "enemy", source="a", attacker="player", force=True)
    rt.clear_safe_zone("enemy")
    assert rt.find_status("enemy", "e") is not None  # -1 维永不被清


def test_c10_hit_rate_and_resist():
    rt = eff_rt(weak=sdef("weak", "虚弱", hit_rate=100))
    rt.apply_status("weak", "enemy", source="a", attacker="player",
                    ctx=DamageCtx(0, "skill", "player", "enemy", {}, {"rng": AlwaysZero()}))
    assert rt.find_status("enemy", "weak") is not None  # hit100 必中
    rt.add_resist("enemy", "weak", 50)
    res = rt.apply_status("weak", "enemy", source="b", attacker="player",
                          ctx=DamageCtx(0, "skill", "player", "enemy", {}, {"rng": AlwaysHigh()}))
    assert res.reason == "miss"  # 目标耐性 50 → 命中率 50%，roll 0.9 miss


# ---------------- D 组 · 免疫矩阵（细化_1b §5 D-1/D-2/D-3/D-5） ----------------


def test_d1_status_immune_blocks_debuff_not_damage(ctx):
    rt = eff_rt(barrier=sdef("barrier", "魔法屏障", immune_vs="status", cat="strengthen"),
                curse=sdef("curse", "恶咒", cat="weak"))
    rt.apply_status("barrier", "enemy", source="a", attacker="player", force=True)
    res = rt.apply_status("curse", "enemy", source="a", attacker="player",
                          ctx=DamageCtx(0, "skill", "player", "enemy", {}, {"rng": AlwaysZero()}))
    assert res.reason == "immune_status"
    snap = base_snapshot()
    snap["enemy"]["status_state"] = rt.status_state["enemy"]  # type: ignore[assignment]
    snap["enemy"]["defenses"]["immune"] = {"status": True, "damage": False, "interrupt": False, "all": False, "block_debuff": True}
    r = pipe.damage_pipeline(ctx(snap, 50), EffectRuntime())
    assert r.final_damage == 50  # 状态免疫不挡伤害（I1）


def test_d2_shield_does_not_block_debuff():
    rt = eff_rt(curse2=sdef("curse2", "恶咒", cat="weak"))
    snap = base_snapshot()
    snap["enemy"]["defenses"]["shield"] = {"value": 30, "remaining": 30, "turns": 2, "max": 30}
    rt.apply_status("curse2", "enemy", source="a", attacker="player", force=True)
    assert rt.find_status("enemy", "curse2") is not None  # 护盾只挡伤害不挡 debuff（I8）


def test_d3_armor_blocks_interrupt(ctx):
    snap = base_snapshot()
    snap["enemy"]["defenses"]["immune"] = {"status": False, "damage": False, "interrupt": True, "all": False, "block_debuff": True}
    res = execute_action({"type": "interrupt", "target": "enemy"}, ctx(snap, 0), EffectRuntime())
    assert not res.ok
    assert any(e["type"] == "interrupt_blocked" for e in res.side_effects)


def test_d5_consumable_immunity():
    rt = eff_rt(guard=sdef("guard", "消耗盾", immune_vs="status", immune_uses=2, cat="strengthen"),
                dd=sdef("dd", "弱化", cat="weak"))
    rt.apply_status("guard", "enemy", source="a", attacker="player", force=True)
    for _ in range(2):
        r = rt.apply_status("dd", "enemy", source="a", attacker="player",
                            ctx=DamageCtx(0, "skill", "player", "enemy", {}, {"rng": AlwaysZero()}))
        assert r.reason == "immune_status"
    assert rt.find_status("enemy", "guard") is None  # 免疫 2 次后消失（I6）


# ---------------- I7 免死约束（细化_1b §4.4 I7 / 定稿 §6.4 H1） ----------------


def test_i7_fatal_guard_limits():
    rt = eff_rt(fatal_immune=edef("fatal_immune", "fatal_immune"),
                guts=edef("guts", "guts"), guts2=edef("guts2", "guts"), guts3=edef("guts3", "guts"))
    w = rt.validate_fatal_guard(["fatal_immune", "guts", "guts2", "guts3"])
    assert any("超上限" in m for m in w)
    w2 = rt.validate_fatal_guard(["fatal_immune", "guts"])
    assert any("互斥" in m for m in w2)


# ---------------- L0 动作执行器（细化_1b §3 / 细化_1d §4） ----------------


def test_l0_mark_add_to_cap(ctx):
    rt = eff_rt(fire_mark=mdef("fire_mark", polarity="positive", max_stack=3))
    snap = base_snapshot()
    for _ in range(4):
        execute_action({"type": "mark_add", "target": "enemy", "mark": "fire_mark", "count": 1}, ctx(snap, 0), rt)
    marks = rt.marks("enemy")
    assert len(marks) == 1 and marks[0]["count"] == 3  # 印记定稿 §4.1：到顶不再涨


def test_l0_mark_remove_saturation(ctx):
    rt = EffectRuntime()
    rt.marks_state = {"player": [], "enemy": [
        {"mark_id": "curse_mark", "name": "诅咒印", "count": 2, "applier": "enemy", "polarity": "negative"},
        {"mark_id": "fire_mark", "name": "火印", "count": 1, "applier": "player", "polarity": "positive"},
    ]}
    snap = base_snapshot()
    snap["marks_state"] = rt.marks_state
    execute_action({"type": "mark_remove", "marks_on": "enemy", "polarity": "positive", "count": 3}, ctx(snap, 0), rt)
    seen = rt.marks("enemy")
    assert "fire_mark" not in [m["mark_id"] for m in seen] and len(seen) == 1  # 饱和减法（D-03）


def test_l0_heal_caps_at_max(ctx):
    snap = base_snapshot(enemy_hp=0)
    execute_action({"type": "heal", "target": "enemy", "value": 5000}, ctx(snap, 0), EffectRuntime())
    assert snap["enemy"]["hp"] == 1000  # 回复封顶 max_hp


def test_l0_proc_per_turn_limit(ctx):
    rtp = EffectRuntime()
    snap = base_snapshot()
    proc = {"id": "p1", "type": "proc", "trigger": "on_attack", "chance": {"mode": "-1", "value": -1},
            "cooldown": 0, "actions": [{"type": "heal", "target": "player", "value": 5}], "chain_depth": 3}
    okc = 0
    for _ in range(12):
        if execute_proc_action(proc, ctx(snap, 0), rtp).ok:
            okc += 1
    assert okc == 10  # 每回合上限 10（E-8）


def test_l0_interrupt_clears_combo(ctx):
    snap = base_snapshot()
    snap["combo_state"] = {"enemy": {"count": 3}}
    res = execute_action({"type": "interrupt", "target": "enemy"}, ctx(snap, 0), EffectRuntime())
    assert res.ok and snap["combo_state"]["enemy"].get("interrupted") is True


# ---------------- battle.py 接线（拦截链接线历史教训） ----------------


def test_battle_engine_resolve_damage_wiring():
    eng = BattleEngine()
    snap = base_snapshot()
    snap["enemy"]["defenses"]["mitigation"] = [{"value": 10, "scope": "all"}]
    res = eng.resolve_damage("player", "enemy", 100, "basic", snapshot=snap)
    assert res.final_damage == 90 and res.target_hp == 910
