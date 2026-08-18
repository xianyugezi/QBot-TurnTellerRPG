"""细化_1b 验收覆盖缺口补测（M1-批2 · test_effects_runtime.py 未覆盖 C-2/C-4/C-7/C-8/D-4/D-6/E-7/G-2/G-3/G-4）。

对齐 test_effects_runtime.py 桩模式（base_snapshot/base_defenses/ctx/sdef/edef/mdef/eff_rt/
AlwaysZero/AlwaysHigh——自包含复制，不依赖测试文件间 import）。断言具体数值/状态。

对应细化_1b_效果系统契约 §5 验收：
  C-2 dual 并存相加 / C-4 level_based 叠至 max_level（默认 5）/ C-7 decrement 每次行动 -1 /
  C-8 trigger 触发时 -1 或减半（一次性型）/ D-4 弱体盾 Mount 抵消一次弱体 /
  D-6 免死超上限警告 + 互斥 + PVP 可禁用 / E-7 追击→偷取可链 + 链深 ≤3 递归不上 /
  G-2 每回合 10 / 每场 99 / 免死类 1-3 上限拦截 / G-3 装备概率表达式锁定 /
  G-4 野图 /休息 冷却-3 回春 20% 一天 3 次

【实现差异/缺陷记录】
  BUG-1（C-8 减半分支）✅已修：D4 trigger 衰减 trigger_halve 配置原先被静默忽略
  （_after_apply setdefault 不覆盖 _new_instance 硬编码 False）→ 已改直接赋值，减半生效，
  test_c8_trigger_halve 由 xfail 转正。
  G-3 / G-4：当前里程碑无装备掉落概率表达式求值器 / 无野图休息（M3 生活系统）→ skip。
"""
from __future__ import annotations

import random

import pytest

from qbot_rpg.core.effects import (
    DamageCtx,
    DamagePipeline,
    EffectRuntime,
    execute_action,
    execute_proc_action,
    tick_after_action,
    _DEFAULT_CONFIG,
)

# ---------------- 建造与工具（复制自 test_effects_runtime.py，自包含） ----------------


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


def ctx(snap, raw, atype="skill", attacker="player", target="enemy", **vars_):
    v = dict(vars_)
    v.setdefault("rng", random.Random(42))
    return DamageCtx(raw_damage=raw, attack_type=atype, attacker=attacker, target=target,
                     snapshot=snap, variables=v)


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


def eff_rt(**defs):
    return EffectRuntime(defs=defs)


class AlwaysZero:
    def random(self):
        return 0.0


class AlwaysHigh:
    def random(self):
        return 0.9


pipe = DamagePipeline()


# ---------------- C 组 · dual 并存相加（细化_1b §5 C-2 / §4.1 S2） ----------------


def test_c2_dual_coexist_and_add():
    rt = eff_rt(atk_a=sdef("atk_a", "降攻A", frame="dual", value=10),
                atk_b=sdef("atk_b", "降攻B", frame="dual", value=14))
    c = ctx(base_snapshot(), 0)
    rt.apply_status("atk_a", "enemy", source="a1", attacker="player", ctx=c, force=True)
    rt.apply_status("atk_b", "enemy", source="b1", attacker="player", ctx=c, force=True)
    vals = [i["value"] for i in rt.status_instances("enemy") if i["status_id"] in ("atk_a", "atk_b")]
    assert sorted(vals) == [10, 14]   # 异框架 dual 并存：两个实例同时存在，互不覆盖
    assert sum(vals) == 24            # 并存相加语义：降攻 A+B 影响相加
    # 同类 dual 2 槽：同 id 最多 2 实例（异源绕过 S5），第 3 次施加覆盖最弱后仍 2 槽
    rt.apply_status("atk_a", "enemy", source="a2", attacker="player", ctx=c, force=True)
    rt.apply_status("atk_a", "enemy", source="a3", attacker="player", ctx=c, force=True)
    a_inst = [i for i in rt.status_instances("enemy") if i["status_id"] == "atk_a"]
    assert len(a_inst) == 2 and all(i["value"] == 10 for i in a_inst)  # 2 槽封顶（不出现第 3 个）
    # 注：S2"盖最弱"需同 id 不同强度，公开 API 无直注路径（def 值固定于配置），此处仅证
    #     槽数封顶 + 跨 id 并存相加（上述 sum==24 已覆盖相加语义）。


# ---------------- C 组 · level_based 叠至 max_level（细化_1b §5 C-4 / §4.1 S4） ----------------


def test_c4_level_based_to_max_level():
    rt = eff_rt(ice=sdef("ice", "冰结", frame="single", value=20, level_based=True))
    c = ctx(base_snapshot(), 0)
    for i in range(5):  # 连续施加 5 次 → 等级 1..5
        r = rt.apply_status("ice", "enemy", source="s%d" % i, attacker="player", ctx=c, force=True)
        assert r.applied and r.reason == "applied"
    inst = rt.find_status("enemy", "ice")
    assert inst is not None and inst["level"] == 5 and inst["stacks"] == 1
    # 第 6 次：已达 max_level → 拒绝叠加（at_max_level），等级不回退
    r6 = rt.apply_status("ice", "enemy", source="s5", attacker="player", ctx=c, force=True)
    assert not r6.applied and r6.reason == "at_max_level"
    assert rt.find_status("enemy", "ice")["level"] == 5
    # max_level 默认 5（细化_1b §1.2 字段 6 默认 2-3 指 stack；level 默认 5 见 config.level_default_max）
    assert EffectRuntime().config["level_default_max"] == 5


# ---------------- C 组 · decrement 减防（细化_1b §5 C-7 / §4.2 D3） ----------------


def test_c7_decrement_per_action_minus_one():
    rt = eff_rt(armor=sdef("armor", "碎甲", decay="decrement", value=5,
                           duration={"turns": 5, "charges": 0}))
    rt.apply_status("armor", "enemy", source="a", attacker="player", force=True)
    assert rt.find_status("enemy", "armor")["value"] == 5
    # 携带者每次行动结算后 -1（tick_after_action → decay_carrier，H8 仅携带者衰减）
    snap = base_snapshot()
    seq = []
    for _ in range(6):
        tick_after_action(snap, rt, "enemy")
        inst = rt.find_status("enemy", "armor")
        seq.append(inst["value"] if inst is not None else "GONE")
    assert seq == [4, 3, 2, 1, "GONE", "GONE"]   # 5→4→3→2→1→0 移除
    # 携带者衰减 ≠ 双方衰减：攻击侧/敌方侧行动不受影响（仅 enemy 上有此状态）
    tick_after_action(snap, rt, "player")
    assert rt.find_status("enemy", "armor") is None and len(rt.status_instances("enemy")) == 0


# ---------------- C 组 · trigger 触发时 -1 或减半（细化_1b §5 C-8 / §4.2 D4） ----------------


def test_c8_trigger_oneshot_minus_one():
    # 一次性护盾/镜像（charges=1）：触发一次即消耗消失，且数值同时 -1
    rt = eff_rt(shield=sdef("shield", "镜盾", decay="trigger", value=5,
                            duration={"turns": 0, "charges": 1}))
    rt.apply_status("shield", "enemy", source="a", attacker="player", force=True)
    assert rt.find_status("enemy", "shield")["value"] == 5
    removed = rt.tick_trigger("enemy", "shield")
    assert removed is not None                          # 一次性型：触发即消失
    assert rt.find_status("enemy", "shield") is None
    # 多次触发型（charges=2）+ trigger_halve=False：每次触发 value -1（4→3→… → 次数尽消失）
    rt2 = eff_rt(s2=sdef("s2", "镜盾2", decay="trigger", value=4,
                         duration={"turns": 0, "charges": 2}))
    rt2.apply_status("s2", "enemy", source="a", attacker="player", force=True)
    assert rt2.find_status("enemy", "s2")["value"] == 4
    rt2.tick_trigger("enemy", "s2")          # 触发 1 次：value 4→3，charges 2→1（仍存活）
    inst = rt2.find_status("enemy", "s2")
    assert inst is not None and inst["value"] == 3
    rt2.tick_trigger("enemy", "s2")          # 触发 2 次：charges 1→0 → 消失
    assert rt2.find_status("enemy", "s2") is None  # charges 扣尽即消失


def test_c8_trigger_halve():
    # 减半型镜像（trigger_halve=True）：触发时 value 减半（40→20→10），charges=2 → 触发 2 次后消失
    # （BUG-1 已修：_after_apply 改直接赋值，trigger_halve 配置生效）
    rt = eff_rt(mirror=sdef("mirror", "镜像", decay="trigger", trigger_halve=True, value=40,
                            duration={"turns": 0, "charges": 2}))
    rt.apply_status("mirror", "enemy", source="a", attacker="player", force=True)
    seq = []
    for _ in range(3):
        rt.tick_trigger("enemy", "mirror")
        inst = rt.find_status("enemy", "mirror")
        seq.append(inst["value"] if inst is not None else "GONE")
    assert seq == [20, "GONE", "GONE"]  # spec：触发时减半 40→20，第 2 次触发 charges 尽 → 消失


# ---------------- D 组 · 弱体盾 Mount 抵消一次弱体（细化_1b §5 D-4 / §4.4 I5） ----------------


def test_d4_mount_absorbs_one_debuff():
    defs = {
        "curse": sdef("curse", "恶咒", cat="weak"),
        "seal": sdef("seal", "封锁", cat="seal"),
        "buff": sdef("buff", "增益", cat="strengthen"),
    }
    rt = eff_rt(**defs)
    snap = base_snapshot()
    snap["enemy"]["defenses"]["mount"]["remaining"] = 1   # 弱体盾 1 次
    c = ctx(snap, 0)
    # 首次弱体 → 被 Mount 抵消（immune_mount），盾剩余归 0
    r1 = rt.apply_status("curse", "enemy", source="a", attacker="player", ctx=c)
    assert not r1.applied and r1.reason == "immune_mount"
    assert snap["enemy"]["defenses"]["mount"]["remaining"] == 0
    assert rt.find_status("enemy", "curse") is None
    # 第二次弱体（或封锁类）→ 盾已消失，正常施加
    r2 = rt.apply_status("seal", "enemy", source="b", attacker="player", ctx=c)
    assert r2.applied and rt.find_status("enemy", "seal") is not None
    # Mount 只挡弱体类（weak/seal/harm），不挡增益（strengthen）
    snap2 = base_snapshot()
    snap2["enemy"]["defenses"]["mount"]["remaining"] = 1
    rt2 = eff_rt(**defs)
    r3 = rt2.apply_status("buff", "enemy", source="c", attacker="player", ctx=ctx(snap2, 0))
    assert r3.applied and rt2.find_status("enemy", "buff") is not None
    assert snap2["enemy"]["defenses"]["mount"]["remaining"] == 1  # 增益不动用弱体盾


# ---------------- D 组 · 免死超上限警告 + PVP 可禁用（细化_1b §5 D-6 / §4.4 I7） ----------------


def test_d6_fatal_guard_limits_and_pvp_disable():
    defs = {
        "fatal_immune": edef("fatal_immune", "fatal_immune"),
        "guts": edef("guts", "guts"),
        "guts2": edef("guts2", "guts"),
        "guts3": edef("guts3", "guts"),
        "guts4": edef("guts4", "guts"),
    }
    rt = EffectRuntime(defs=defs)
    # 默认 fatal_guard_max=3：4 个免死类 → 超上限警告 + 互斥提示
    w = rt.validate_fatal_guard(["fatal_immune", "guts", "guts2", "guts3"])
    assert any("超上限" in m for m in w) and any("互斥" in m for m in w)
    # 边界：恰好 3 个 → 无超上限警告，但仍互斥（致命免疫+战斗续行同配）
    w3 = rt.validate_fatal_guard(["fatal_immune", "guts", "guts2"])
    assert not any("超上限" in m for m in w3) and any("互斥" in m for m in w3)
    # 可配 fatal_guard_max=0（不限）：5 个免死类无超上限警告
    rt0 = EffectRuntime(defs=defs, config={"fatal_guard_max": 0})
    assert not any("超上限" in m for m in rt0.validate_fatal_guard(["fatal_immune", "guts", "guts2", "guts3", "guts4"]))
    # 可配 allow_dual_fatal_guard=true：致命免疫+战斗续行同配不提示互斥
    rtd = EffectRuntime(defs=defs, config={"allow_dual_fatal_guard": True})
    assert rtd.validate_fatal_guard(["fatal_immune", "guts"]) == []
    # PVP 可禁用免死类：pvp=True + pvp_fatal_disabled → 直接禁用（其余场景不触发）
    rtp = EffectRuntime(defs=defs, config={"pvp_fatal_disabled": True})
    assert "PVP 已禁用免死类效果" in rtp.validate_fatal_guard(["fatal_immune", "guts"], pvp=True)
    assert _DEFAULT_CONFIG["pvp_fatal_disabled"] is False  # 默认不禁用


# ---------------- E 组 · 追击→偷取可链 + 链深 ≤3（细化_1b §5 E-7 / §2.5 / §1.1-12） ----------------


def test_e7_proc_chain_and_depth_limit():
    snap = base_snapshot()
    c = ctx(snap, 0)
    def _proc(id_):
        return {"id": id_, "type": "proc", "trigger": "on_attack",
                "chance": {"mode": "-1", "value": -1}, "cooldown": 0, "chain_depth": 3,
                "actions": []}
    # 追击(chase) → 偷取(steal)：可链（E-7 追击触发偷取）
    steal = _proc("steal")
    steal["actions"] = [{"type": "heal", "target": "self", "value": 5}]
    chase = _proc("chase")
    chase["actions"] = [steal]
    rt = EffectRuntime()
    res = execute_proc_action(chase, c, rt)
    triggered = [e for e in res.side_effects if e["type"] == "proc_triggered"]
    assert res.ok
    assert [t["proc_id"] for t in triggered] == ["chase", "steal"]  # 追击→偷取两级链
    assert any(e["type"] == "heal" for e in res.side_effects)        # 偷取动作实际执行
    # 同类自身不触发（追击触发追击，递归）：链深 ≤3，第 4 层被 chain_depth 拦截
    loop = _proc("loop")
    loop["actions"] = [loop]  # 自身引用
    rt2 = EffectRuntime()
    res2 = execute_proc_action(loop, c, rt2)
    triggered2 = [e for e in res2.side_effects if e["type"] == "proc_triggered"]
    blocked = [e for e in res2.side_effects if e["type"] == "proc_blocked"]
    assert len(triggered2) == 3                      # 深度 0/1/2 三层触发（chain_depth=3）
    assert blocked and blocked[0]["reason"] == "chain_depth"  # 第 4 层递归被拦截，不无限循环
    assert _DEFAULT_CONFIG["chain_depth"] == 3       # 默认链深 3


# ---------------- G 组 · 触发计数上限（细化_1b §5 G-2 / §2.4，每回合 10 + 每场 99 + 免死 1-3） ----------------


def test_g2_trigger_capacity_limits():
    # 默认容量：每回合 10 / 每场 99 / 免死类 1-3（细化_1b §1.1 / I7）
    assert _DEFAULT_CONFIG["max_triggers_per_turn"] == 10
    assert _DEFAULT_CONFIG["max_triggers_per_battle"] == 99
    assert _DEFAULT_CONFIG["fatal_guard_max"] == 3
    # 机制验证（配置缩小以便快速断言）：每场 3 次上限
    rt = EffectRuntime(config={"max_triggers_per_battle": 3})
    snap = base_snapshot()
    proc = {"id": "p1", "type": "proc", "trigger": "on_attack",
            "chance": {"mode": "-1", "value": -1}, "cooldown": 0, "chain_depth": 3,
            "actions": [{"type": "heal", "target": "player", "value": 1}]}
    oks, blocked_msgs = 0, []
    for _ in range(6):
        r = execute_proc_action(proc, ctx(snap, 0), rt)
        if r.ok:
            oks += 1
        else:
            blocked_msgs.append(r.message)
    assert oks == 3 and "每场触发上限" in blocked_msgs   # 第 4 次起被每场上限拦截
    assert rt.trigger_counts("player", "p1") == (3, 3)
    # 回合翻转只重置 per_turn，不重置 per_battle（每场上限跨回合累计）
    rt.reset_turn_triggers("player")
    assert rt.trigger_counts("player", "p1") == (0, 3)
    r = execute_proc_action(proc, ctx(snap, 0), rt)
    assert not r.ok and r.message == "每场触发上限"


# ---------------- G 组 · 装备概率表达式锁定（细化_1b §5 G-3 / §2.2） ----------------


def test_g3_equip_probability_expression_not_implemented():
    """G-3「+3～6d4」装备概率表达式获得时计算并锁定、随实例持久化：M1 无装备掉落管线，
    亦无概率表达式求值器（dice 语法）→ 依赖 M2 装备/掉落系统，当前不可测。"""
    pytest.skip("G-3 依赖 M2 装备掉落管线 + 概率表达式求值器（dice），M1 无实现")


# ---------------- G 组 · 野图 /休息（细化_1b §5 G-4 / §3.1） ----------------


def test_g4_wild_rest_not_implemented():
    """G-4 野图非战斗 /休息：冷却 -3、HP/MP +20%、一天 3 次上限、战斗中不可用——
    依赖 M3 生活系统（时间引擎/休息指令/回春池），M1 战斗核心无野图状态机 → 不可测。"""
    pytest.skip("G-4 依赖 M3 生活系统（时间/休息指令/回春池），M1 无野图非战斗状态机")


# ---------------- 定稿对照修复（审查_M1_effects_定稿对照_20260818.md G3） ----------------
def test_g3_reflect_also_mitigates():
    """定稿 §3.4③ L138「按 % 减伤并反弹」：反弹 20% 承受 100 → 实伤 80 + 反弹 20 给攻击者。
    （G3 修复：原实现只反弹不减伤。）"""
    pipe = DamagePipeline()
    snap = base_snapshot()
    snap["enemy"]["defenses"]["reflect"] = {"value": 20, "pct": True, "active": True}
    r = pipe.damage_pipeline(ctx(snap, 100), EffectRuntime())
    refl = [e for e in r.side_effects if e["type"] == "reflect"]
    assert len(refl) == 1 and refl[0]["damage"] == 20
    assert r.final_damage == 80, f"反弹应同时减伤：{r.final_damage}"
