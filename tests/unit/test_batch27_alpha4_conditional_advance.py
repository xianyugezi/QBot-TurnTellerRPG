"""批27 · α4：技能按条件进阶（CakeGame 装备附加Re《核心配置》:180）。

**现状核查结论（本批拍板）**：α4 的"同一技能槽按条件分支 → 换形态（进阶技能）"
已由**既有派生链（skill_chains `steps` + `mode:"replace"`）**等价覆盖——
`core/combo.py::_resolve_derivation` 路径 c：释放 `from`（基础技）时求
`condition`，命中且 `count<max_combo` → 自动替换为 `to`（进阶技）后再走结算；
条件不命中 → 仍释放基础技。**故本批不新增任何 skills 字段/平行机制**，只给
既有机制的用法示例 + 证据（避免与 `chain_refs`/`skill_chains`/`level.growth`
重复；`level.growth` 是数值升级、不是条件分支）。

用法（内容包口径，零新增字段）：
  skills.json
    {"id":"base","name":"基础式","type":"active","kind":"damage","power":100,
     "chain_refs":["evolve"]}
    {"id":"adv","name":"进阶式","type":"active","kind":"damage","power":200}
  skill_chains.json
    {"id":"evolve","name":"条件演化","trigger_skill":"base","max_combo":1,
     "max_combo_behavior":"reset",
     "steps":[{"from":"base","to":"adv","mode":"replace",
               "condition":{"target_hp_pct":{"max":50}}}]}
  → 敌方生命 ≤50% 时放「基础式」实际结算「进阶式」；否则结算「基础式」。

覆盖：
  - 引擎消费（状态级）：条件命中 → combo_result.form_id == 进阶技（伤害同源升高）；
    条件不命中 → 基础技（零改写，逐字段一致）；
  - 与既有派生链/变体共存不打架：多链各自独立解析；
  - 回归：无链技能 / 无 condition 步骤 → 行为与现状一致。

测试只建临时对象，绝不写真实内容包。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping

from qbot_rpg.core.battle import BattleEngine

# V-7 校验口径：测试技能库带一个 basic 占位（本文件不跑内容校验，仅保持一致）。
_BASIC = {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
          "power": 100}


def _engine(defs: Dict[str, Any], *, enemy_hp: int, enemy_max_hp: int = 100) -> BattleEngine:
    eng = BattleEngine(defs=defs, config={"combo_enforce_mp": False})
    eng.start(
        {"hp": 500, "max_hp": 500, "mp": 100, "max_mp": 100,
         "atk": 100, "def": 0, "spr": 0, "spd": 10, "foc": 500, "con": 0,
         "lck": 0, "int": 0, "name": "玩家"},
        {"hp": enemy_hp, "max_hp": enemy_max_hp, "mp": 0, "max_mp": 0,
         "atk": 0, "def": 0, "spr": 0, "spd": 1, "foc": 0, "con": 0,
         "lck": 0, "int": 0, "name": "桩"},
        random_seed=7,
    )
    return eng


def _evolution_defs() -> Dict[str, Any]:
    """基础技 + 条件进阶技 + 一条 replace 派生链（纯配置，零新字段）。"""
    return {
        "base": {"id": "base", "name": "基础式", "type": "active", "kind": "damage",
                 "power": 100, "chain_refs": ["evolve"]},
        "adv": {"id": "adv", "name": "进阶式", "type": "active", "kind": "damage",
                "power": 400},
        "evolve": {
            "id": "evolve", "name": "条件演化", "trigger_skill": "base",
            "max_combo": 1, "max_combo_behavior": "reset",
            "steps": [{"from": "base", "to": "adv", "mode": "replace",
                       "condition": {"target_hp_pct": {"max": 50}}}],
        },
    }


# ---------------------------------------------------------------------------
# 引擎消费：条件命中 → 释放进阶技；条件不命中 → 释放基础技
# ---------------------------------------------------------------------------
def test_a4_condition_met_releases_advanced_form() -> None:
    """残血目标（≤50%）→ 基础式释放时自动替换为进阶式（贴 release 证据）。"""
    eng = _engine(_evolution_defs(), enemy_hp=40)
    out = eng.do_action("player", {"type": "skill", "skill_id": "base"})
    assert out.ok is True, out
    assert isinstance(out.combo_result, Mapping), out.combo_result
    assert out.combo_result.get("form_id") == "adv", out.combo_result
    assert out.combo_result.get("derived") is True, out.combo_result
    # 数值级同源证据：进阶技 power 400（基础 100），伤害显著更高（同种子对照）。
    eng_base = _engine(_evolution_defs(), enemy_hp=100)  # 满血 → 不命中
    out_base = eng_base.do_action("player", {"type": "skill", "skill_id": "base"})
    assert out.final_damage > out_base.final_damage, (out.final_damage, out_base.final_damage)


def test_a4_condition_unmet_releases_base_form() -> None:
    """满血目标（>50%）→ 条件不命中，仍释放基础式（combo_result 不出现 form 改写）。"""
    eng = _engine(_evolution_defs(), enemy_hp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "base"})
    assert out.ok is True, out
    assert not (out.combo_result or {}).get("form_id"), out.combo_result


def test_a4_boundary_is_inclusive() -> None:
    """条件边界含端点（target_hp_pct ≤50 时 50% 命中）——进阶形态在边界同样生效。"""
    eng = _engine(_evolution_defs(), enemy_hp=50, enemy_max_hp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "base"})
    assert (out.combo_result or {}).get("form_id") == "adv", out.combo_result


def test_a4_demoted_form_still_reachable_by_condition_inverse() -> None:
    """退阶口径：条件取反（not）→ 满血走基础式、残血走进阶式可同链表达（不新造字段）。

    说明：既有语义中"释放 to 而条件不足"会整体被拒（1c2 定稿），故"退阶"用
    `from` 侧条件取反表达，而非直接施放 to——本用例给出该口径的可用写法。
    """
    defs = _evolution_defs()
    defs["evolve"]["steps"] = [{
        "from": "base", "to": "adv", "mode": "replace",
        "condition": {"not": {"target_hp_pct": {"max": 50}}},
    }]
    hi = _engine(defs, enemy_hp=90)
    lo = _engine(defs, enemy_hp=30)
    out_hi = hi.do_action("player", {"type": "skill", "skill_id": "base"})
    out_lo = lo.do_action("player", {"type": "skill", "skill_id": "base"})
    assert (out_hi.combo_result or {}).get("form_id") == "adv", out_hi.combo_result
    assert not (out_lo.combo_result or {}).get("form_id"), out_lo.combo_result


# ---------------------------------------------------------------------------
# 与既有派生链/变体共存不打架
# ---------------------------------------------------------------------------
def test_a4_two_chains_are_independent() -> None:
    """两条 replace 派生链并存：各自按自己的 from/条件解析，互不串链。"""
    defs = _evolution_defs()
    defs["other"] = {"id": "other", "name": "另一式", "type": "active",
                     "kind": "damage", "power": 100}
    defs["other_adv"] = {"id": "other_adv", "name": "另一进阶", "type": "active",
                         "kind": "damage", "power": 400}
    defs["other_chain"] = {
        "id": "other_chain", "name": "另一链", "trigger_skill": "other",
        "max_combo": 1, "max_combo_behavior": "reset",
        "steps": [{"from": "other", "to": "other_adv", "mode": "replace",
                   "condition": {"target_hp_pct": {"max": 90}}}],
    }
    eng = _engine(defs, enemy_hp=85)  # other 条件命中、base 条件不命中
    out_base = eng.do_action("player", {"type": "skill", "skill_id": "base"})
    assert not (out_base.combo_result or {}).get("form_id"), out_base.combo_result
    eng2 = _engine(defs, enemy_hp=85)
    out_other = eng2.do_action("player", {"type": "skill", "skill_id": "other"})
    assert (out_other.combo_result or {}).get("form_id") == "other_adv", out_other.combo_result


def test_a4_regression_without_chain_identical() -> None:
    """无链技能（不带 chain_refs、不参与任何 steps）→ 与现状逐字段一致。"""
    defs = {k: v for k, v in _evolution_defs().items() if k != "evolve"}
    defs["plain"] = {"id": "plain", "name": "纯技", "type": "active",
                     "kind": "damage", "power": 100}
    a = _engine(defs, enemy_hp=40)
    b = _engine(defs, enemy_hp=40)
    oa = a.do_action("player", {"type": "skill", "skill_id": "plain"})
    ob = b.do_action("player", {"type": "skill", "skill_id": "plain"})
    assert oa.ok and ob.ok
    assert not (oa.combo_result or {}).get("form_id")
    assert (oa.final_damage, oa.target_hp) == (ob.final_damage, ob.target_hp)


def test_a4_regression_step_without_condition_keeps_base_behavior() -> None:
    """无 condition 的 replace 步 = 恒可用（1c2 §1.2 字段 10）——既有语义不变。"""
    defs = _evolution_defs()
    defs["evolve"]["steps"] = [{"from": "base", "to": "adv", "mode": "replace"}]
    eng = _engine(defs, enemy_hp=100)
    out = eng.do_action("player", {"type": "skill", "skill_id": "base"})
    assert (out.combo_result or {}).get("form_id") == "adv", out.combo_result
