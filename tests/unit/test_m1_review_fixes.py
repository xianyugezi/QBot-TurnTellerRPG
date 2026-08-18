"""M1-批1 dsh 审查修复回归（审查_M1_batch1_20260818.md）。

- P0-1：S1/S5 覆盖规则（反向「先强后弱」→ covered_low，不再恒覆盖）
- P1-5：R3 resist_gain 统一出口（S5-renewed/S1-replaced/stack 分支也生效）
- P1-4：chance mode="lucky" 幸运修正（细化 A-3）
- P0-2：L0 公式框默认注入 formula_engine（F-1/F-3 接线）
- P1-7：派生累计封顶 apply_derived_cap（T32）
- G-1：快照五块 roundtrip（to_dict/from_dict）
- P1-8：三个重复修正器 helper 已删除（不应再可导入）
"""
from __future__ import annotations

import random
import warnings

import pytest

from qbot_rpg.core import effects as E
from qbot_rpg.core.damage import apply_derived_cap


# ---------------- P0-1：S1/S5 覆盖规则（反向用例） ----------------
def _rt(**defs):
    return E.EffectRuntime(defs=defs)


def _sdef(id_, name, frame="single", value=1, cat="weak", **kw):
    raw = {"id": id_, "name": name, "class": "status", "category": cat,
           "stack_frame": frame, "actions": [{"type": "none", "value": value}]}
    raw.update(kw)
    return E._Def(raw) if hasattr(E, "_Def") else None


# 用 test_effects_runtime 同款桩：为避免依赖私有 _Def，改为 registry-free 直传 defs 映射
class _Def:
    def __init__(self, raw):
        self.id = raw["id"]
        self.name = raw.get("name", raw["id"])
        self.raw = raw


def sdef(id_, name, frame="single", value=1, cat="weak", **kw):
    raw = {"id": id_, "name": name, "class": "status", "category": cat,
           "stack_frame": frame, "actions": [{"type": "none", "value": value}]}
    raw.update(kw)
    return _Def(raw)


def ctx_with(snap):
    return E.DamageCtx(raw_damage=0, attack_type="skill", attacker="player", target="enemy",
                       snapshot=snap, variables={"rng": random.Random(42)})


def base_snap():
    return {"player": {"hp": 1000, "max_hp": 1000, "defenses": {}},
            "enemy": {"hp": 1000, "max_hp": 1000, "defenses": {}},
            "status_state": {"player": [], "enemy": []},
            "marks_state": {"player": [], "enemy": []},
            "resist_table": {"player": {}, "enemy": {}},
            "effect_triggers": {"player": {"per_turn": {}, "per_battle": {}}, "enemy": {"per_turn": {}, "per_battle": {}}},
            "effect_cooldowns": {"player": {}, "enemy": {}}}


def test_p01_s5_strong_after_weak_renew():
    """S5 同来源：新≥既有（等强也覆盖重置持续）→ renewed；覆盖规则不失效。"""
    rt = _rt(weak=sdef("weak", "降攻", value=10))
    c = ctx_with(base_snap())
    assert rt.apply_status("weak", "enemy", source="a1", ctx=c, force=True).applied is True   # value 10
    r = rt.apply_status("weak", "enemy", source="a1", ctx=c, force=True)   # 等强 10>=10 → renewed 重置
    assert r.applied is True and r.reason == "renewed"
    assert rt.status_instances("enemy")[0]["value"] == 10


def test_p01_s5_weak_after_strong_covered():
    """S5 同来源反向：既有强 30，新弱 10 → covered_low 不覆盖（P0-1 修复核心）。"""
    rt = _rt(weak=sdef("weak", "降攻", value=10))
    c = ctx_with(base_snap())
    assert rt.apply_status("weak", "enemy", source="a1", ctx=c, force=True).applied is True
    rt.status_instances("enemy")[0]["value"] = 30   # 模拟既有更强（衰减前满值）
    r = rt.apply_status("weak", "enemy", source="a1", ctx=c, force=True)   # 弱新 10 < 30
    assert r.applied is False and r.reason == "covered_low"
    assert rt.status_instances("enemy")[0]["value"] == 30  # 既有强状态保留（原恒覆盖 bug 会变 10）


def test_p01_s1_weak_after_strong_covered():
    """S1 single：既有强 30，新弱 10（异源）→ covered_low（P0-1 修复核心）。"""
    rt = E.EffectRuntime(defs={"weak": sdef("weak", "降攻", value=10)})
    c = ctx_with(base_snap())
    assert rt.apply_status("weak", "enemy", source="a1", ctx=c, force=True).applied is True
    rt.status_instances("enemy")[0]["value"] = 30   # 既有更强
    r = rt.apply_status("weak", "enemy", source="a2", ctx=c, force=True)   # 异源 single：10<30
    assert r.applied is False and r.reason == "covered_low"
    assert rt.status_instances("enemy")[0]["value"] == 30


# ---------------- P1-5：R3 resist_gain 统一出口 ----------------
def test_p15_r3_resist_on_s1_replaced():
    """R3：开启后 S1 重盖成功路径也施加抗性（越挂越难），同一 runtime 累计。"""
    rt = E.EffectRuntime(defs={"weak": sdef("weak", "降攻", value=30, resist_gain=True)},
                         config={"resist_gain_enabled": True, "resist_gain_step": 10})
    c = ctx_with(base_snap())
    assert rt.apply_status("weak", "enemy", source="a1", ctx=c).applied is True
    # 异源 single 等强重盖（28>=28）→ replaced 成功 → 抗性再 +10
    assert rt.apply_status("weak", "enemy", source="a2", ctx=c).applied is True
    assert rt.resist("enemy", "weak") >= 20  # 两次施加成功各 +10


# ---------------- P1-4：chance mode="lucky" ----------------
def test_p14_chance_lucky_mode():
    """A-3：mode=lucky, value=20，我方幸运 100 / 对方 36 →（√100−√36+20）%=30%。"""
    c = ctx_with(base_snap())
    rolls = []
    for i in range(200):
        c.variables["rng"] = random.Random(i)
        rolls.append(E._chance_roll({"mode": "lucky", "value": 20}, c, attacker_luck=100, target_luck=36))
    assert any(rolls) and not all(rolls), "lucky 应产生 30% 附近的混合结果"
    assert abs(sum(1 for x in rolls if x) / 200 - 0.30) < 0.15


# ---------------- P0-2：L0 公式框默认注入 formula_engine ----------------
def test_p02_formula_value_uses_engine():
    """公式框 value="[我方攻击]*2"（攻击 180）→ 360（F-1 接线，不再恒 0）。"""
    rt = E.EffectRuntime()
    snap = base_snap()
    snap["player"]["atk"] = 180
    c = ctx_with(snap)
    c.variables["attacker"] = {"atk": 180}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = E._resolve_value("[我方攻击]*2", 180, c)
    assert v == 360, v


def test_p02_formula_blacklist_zero():
    """公式框含 eval → 黑名单兜底 0 + 不崩（F-2/F-3）。"""
    rt = E.EffectRuntime()
    c = ctx_with(base_snap())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        v = E._resolve_value("eval(1)+5", 100, c)
    assert v == 0, v


# ---------------- P1-7：派生累计封顶（T32） ----------------
def test_p17_derived_cap():
    assert apply_derived_cap(1.0) == 1.0
    assert apply_derived_cap(2.0) == 1.5        # 超 1.5 封顶（T32）
    assert apply_derived_cap(0.5, max_total_mult=1.5) == 0.5
    assert apply_derived_cap(-1) == 0.0          # 负值按 0


# ---------------- G-1：快照五块 roundtrip ----------------
def test_g1_effect_runtime_roundtrip():
    rt = E.EffectRuntime(defs={"weak": sdef("weak", "降攻", value=10)})
    c = ctx_with(base_snap())
    rt.apply_status("weak", "enemy", source="a1", ctx=c)
    blob = rt.to_dict()
    rt2 = E.EffectRuntime.from_dict(blob)
    assert rt2.to_dict() == blob
    assert len(rt2.status_instances("enemy")) == 1
    assert rt2.status_instances("enemy")[0]["status_id"] == "weak"


# ---------------- P1-8：重复 helper 已删除 ----------------
def test_p18_dup_helpers_removed():
    # 三个独立修正器 helper 是 execute_action 内联的双份实现 → 删除；改用单测内联验证
    for name in ("apply_lifesteal", "apply_pierce", "apply_mitigation"):
        assert not hasattr(E, name), f"{name} 不应再存在（重复实现已删）"
    # effects.DamagePipeline 类是拦截链核心（合法）；damage.DamageContext 已删（P1-1）
    from qbot_rpg.core import damage as D
    assert not hasattr(D, "DamageContext"), "damage.DamageContext 已删"
