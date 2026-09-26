"""批84 · B2：校验器对「合法枚举但无派发点」的黄提示 Y-24 回归。

依据：`docs/Vibecoding说明书.md` §二 D（**静默死效果**）+ 批84 · B1 唯一源
`data/event_points.EVENT_POINT_TABLE`。

口径：
  · 合法枚举 + `dispatched=False` → **黄提示 Y-24**（只提示、**不红拦**、**零行为变化**）；
  · 已接时点（`dispatched=True`）→ 零红零黄；
  · 未登记时点 → 仍是既有 Y-19（两条分支互斥）；
  · 非字符串 → R-1；
  · 覆盖 `effects.<idx>.trigger` 与 `runes.<idx>.effects.<j>.trigger` 两处声明面。
"""
from __future__ import annotations

from typing import List, Tuple

from qbot_rpg.content.validator import check_pack
from qbot_rpg.data.event_points import EVENT_POINT_TABLE, undispatched_points


def _rules(rep) -> Tuple[List[str], List[str]]:
    return ([str(e.detail.get("rule")) for e in rep.errors],
            [str(w.detail.get("rule")) for w in rep.warnings])


def _effects(*triggers: str) -> dict:
    return {"effects": [{"id": f"fx{i}", "type": "special", "trigger": t,
                         "actions": []}
                        for i, t in enumerate(triggers)]}


def test_dispatched_points_silent() -> None:
    live = [p.name for p in EVENT_POINT_TABLE if p.dispatched]
    rep = check_pack(_effects(*live))
    assert _rules(rep) == ([], []), _rules(rep)


def test_undispatched_points_warn_y24_not_red() -> None:
    for trig in undispatched_points():
        rep = check_pack(_effects(trig))
        errs, warns = _rules(rep)
        assert errs == [], (trig, errs)          # **不红拦**
        assert warns == ["trigger_event_no_dispatch"], (trig, warns)
        d = rep.warnings[0].detail
        assert d.get("event") == trig
        assert "无派发点（二期）" in str(d.get("msg") or "")
        assert d.get("dispatched_key_space")
        assert trig not in d["dispatched_key_space"]   # 建议里不含它自己


def test_y19_and_y24_are_mutually_exclusive() -> None:
    # 未登记（拼错）→ Y-19，不得同时出 Y-24
    rep = check_pack(_effects("on_kil"))
    assert _rules(rep) == ([], ["trigger_event_unknown"])
    # 合法无派发 → Y-24，不得同时出 Y-19
    rep = check_pack(_effects("on_hit"))
    assert _rules(rep) == ([], ["trigger_event_no_dispatch"])


def test_non_string_still_red() -> None:
    rep = check_pack({"effects": [{"id": "a", "type": "special",
                                   "trigger": 3, "actions": []}]})
    assert _rules(rep) == (["type"], [])


def test_rune_ref_trigger_gets_y24() -> None:
    rep = check_pack({"runes": [{"id": "r", "effects": [
        {"effect": "fx", "trigger": "mark_lose"}]}]})
    warns = [str(w.detail.get("rule")) for w in rep.warnings]
    assert warns.count("trigger_event_no_dispatch") == 1
    assert rep.warnings[0].kind == "Y-24"
    assert rep.warnings[0].field == "runes.0.effects.0.trigger"


def test_absent_or_empty_trigger_silent() -> None:
    rep = check_pack({"effects": [
        {"id": "a", "type": "special", "actions": []},
        {"id": "b", "type": "special", "trigger": "", "actions": []},
    ]})
    assert _rules(rep) == ([], [])
