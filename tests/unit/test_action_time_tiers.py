"""批⑥ 验收：行动时间分档（C10 浮动值）+ 霸体代价（C12）内容面 + 判定链自证。

口径（怪猎对照研究 C10/C12，2026-09-12 批⑥）：
  - **不写死**：每个动作的行动恢复值逐条配置（`recovery` 键），围绕设计参考标准
    浮动（轻 ~400 / 中 ~700 / 重 ~1100 行动条；速度 10 时 ×10 换算）；本测试只做
    结构性断言 + 锚点抽查，不做全表锁定。
  - 霸体标签技能（C12）：伤害 ×0.8、行动时间 +100 条（recovery +10）；
    vs_dash 描述写霸体但标记缺失 → 补齐 armor=true。
"""

from __future__ import annotations

import json
from pathlib import Path

PACK = Path(__file__).resolve().parents[2] / "content" / "veinborn"


def _load(name):
    return json.loads((PACK / name).read_text(encoding="utf-8"))


def _by(rows):
    return {r["id"]: r for r in rows}


def test_all_actions_have_floating_recovery():
    """全部可行动条目各自带 recovery（占位组除外）——「不写死」的结构前提。"""
    skills = _load("skills.json")
    combat = [s for s in skills if s["id"] not in ("mastery_skills", "dial_skills")]
    assert len(combat) == 158
    for s in combat:
        assert isinstance(s.get("recovery"), (int, float)), s["id"]
    for a in _load("action.json"):
        assert isinstance(a.get("recovery"), (int, float)), a["id"]


def test_recovery_floats_around_reference_bands():
    """浮动性：档内多样（非统一值）；范围围绕参考标准。"""
    vals = [s["recovery"] for s in _load("skills.json") if "recovery" in s]
    assert 34 <= min(vals) and max(vals) <= 135
    light = [v for v in vals if v <= 46]
    mid = [v for v in vals if 60 <= v <= 77]
    heavy = [v for v in vals if v >= 100]
    assert len(set(light)) >= 5 and len(set(mid)) >= 5 and len(set(heavy)) >= 5
    assert len(light) >= 40 and len(mid) >= 30 and len(heavy) >= 25


def test_basic_attacks_in_light_band():
    """10 职业普攻（basic 槽技能）统一进轻档。"""
    basics = [s for s in _load("skills.json") if s.get("type") == "basic"]
    assert len(basics) == 10
    for s in basics:
        assert 34 <= s["recovery"] <= 46, (s["id"], s["recovery"])


def test_c12_armor_cost_spot_checks():
    """霸体代价抽查：伤害 ×0.8、恢复 = 档位值 +10；文本对齐。"""
    by = _by(_load("skills.json"))
    for sid, p, r in [
        ("va_form_shot", 160, 78), ("vc_form_finisher", 336, 130),
        ("rb_spine_breaker", 240, 114), ("po_foreclose", 320, 126),
        ("vb_tail_breaker", 144, 76),
    ]:
        assert by[sid]["power"] == p and by[sid]["recovery"] == r, sid
        assert by[sid]["armor"] is True
    assert by["vs_dash"]["armor"] is True and by["vs_dash"]["recovery"] == 46
    assert "X2" not in by["vg_rip"]["desc"] and "X2" not in by["vg_iron_gate"]["desc"]


def test_recovery_resolves_via_engine_rule():
    """引擎口径：技能 def 的 recovery 键经 recovery_for 解析（同 _action_recovery）。"""
    from qbot_rpg.core.ctb_rules import CtbRuleConfig, recovery_for

    by = _by(_load("skills.json"))
    action = {"type": "skill", "skill_id": "vg_key", "recovery": by["vg_key"]["recovery"]}
    assert recovery_for(action, CtbRuleConfig()) == float(by["vg_key"]["recovery"])
