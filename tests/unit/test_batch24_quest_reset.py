"""批24 · G1：任务重置周期（并入 `daily`；CakeGame `Config_Task.ResetTime/ResetType`；§三 G1）。

设计口径（本批拍板，写进报告）：
  · **并入现有 `daily`，不新开平行字段**（原报告建议）：`daily` 值形态扩为
    bool | {count, unit} | {reset:{count, unit}}；
  · `daily=true` 兼容 ≡ `{count:1, unit:"日"}`（旧包零破坏）；
  · `count=-1` = 永不重置（沿用他们口径）；其余正整数 = 每 N 个周期重置；
  · `unit` ∈ RESET_UNITS（年/季/月/周/日/时/分/秒，游戏内既有日历术语）；
  · 引擎落点 = 任务可接取性判定（`core.quest._is_acceptable` / `quest_accept`）：完成后
    周期到点 → 视为未完成可再接；完成时刻落 `ctx["quest_completed_at"]`（随快照回滚）；
  · 日/周走 dayroll 日界/周界，月/季/年走自然月，时/分/秒按秒差（接既有重置口径）。

覆盖：
  - 元数据登记（daily 子字段 count/unit/reset）+ 编辑器接口可见；
  - 校验：枚举非法 R-1 / count 0 与非 -1 负数 R-2 / 非整数 R-2 / 坏形态 R-1；bool 兼容不红；
  - 引擎消费（时间注入）：周期到点后可再接取；同周期内不可；daily:true ≡ 1 日；
    -1 永不重置；多种单位；完成时刻落档；
  - 回归：不带 daily → 完成后永久完成（行为与现状逐字段一致）。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.models import RESET_UNITS
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core import quest as Q
from qbot_rpg.web import api

_BASE_TS = 1_700_000_000
_DAY = 86400


def _ctx(now: int, daily: Any = None) -> Dict[str, Any]:
    q: Dict[str, Any] = {"id": "q_reset", "name": "周期任务", "repeatable": False,
                         "conditions": []}
    if daily is not None:
        q["daily"] = daily
    return {
        "quests": {"q_reset": q},
        "quest_active": {}, "quest_completed": [], "quest_daily": {},
        "inventory": {}, "now": now, "settings": {},
    }


def _complete(now: int, daily: Any) -> Dict[str, Any]:
    ctx = _ctx(now, daily)
    assert Q.quest_accept("q_reset", ctx)["ok"] is True
    assert Q.quest_complete("q_reset", ctx)["ok"] is True
    return ctx


def _carry(ctx: Dict[str, Any], now: int, daily: Any) -> Dict[str, Any]:
    out = _ctx(now, daily)
    out["quest_completed"] = list(ctx["quest_completed"])
    out["quest_completed_at"] = dict(ctx.get("quest_completed_at") or {})
    return out


# ---------------------------------------------------------------------------
# G1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_g1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("quest").fields.get("daily")
    assert fm is not None
    assert set(fm.children) >= {"count", "unit", "reset"}
    assert fm.children["unit"].enum == RESET_UNITS
    assert fm.children["count"].type == "int" and fm.children["count"].allow_negative is True


def test_g1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_g1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_g1", "version": "1", "schema_version": 1, "modules": ["quest"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "quest.json").write_text(json.dumps(
        [{"id": "q_weekly", "name": "周常", "daily": {"count": 1, "unit": "周"},
          "conditions": []}], ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_g1", "quest", "q_weekly", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "daily")
    kids = {c["key"]: c for c in f["children"]}
    assert {"count", "unit"} <= set(kids)
    assert kids["unit"]["enum"] and "周" in kids["unit"]["enum"]


# ---------------------------------------------------------------------------
# G1 校验
# ---------------------------------------------------------------------------
def test_g1_validator_bad_unit_red() -> None:
    r = check_pack({"quest": [{"id": "q", "name": "Q",
                               "daily": {"count": 1, "unit": "周x"}}]})
    assert [e for e in r.errors if e.kind == "R-1" and e.field.endswith("daily.unit")]


def test_g1_validator_count_range_red() -> None:
    for bad in (0, -2):
        r = check_pack({"quest": [{"id": "q", "name": "Q",
                                   "daily": {"count": bad, "unit": "日"}}]})
        assert [e for e in r.errors if e.kind == "R-2" and "count" in e.field], bad
    r = check_pack({"quest": [{"id": "q", "name": "Q",
                               "daily": {"count": "3", "unit": "日"}}]})
    assert [e for e in r.errors if e.kind == "R-2" and "count" in e.field]


def test_g1_validator_bool_compat_ok() -> None:
    for ok in (True, False, None):
        quest = {"id": "q", "name": "Q"}
        if ok is not None:
            quest["daily"] = ok
        r = check_pack({"quest": [quest]})
        assert not [e for e in r.errors if "daily" in e.field], ok


def test_g1_validator_valid_objects_ok() -> None:
    for ok in ({"count": 1, "unit": "周"}, {"count": -1, "unit": "日"},
               {"reset": {"count": 2, "unit": "月"}}):
        r = check_pack({"quest": [{"id": "q", "name": "Q", "daily": ok}]})
        assert not [e for e in r.errors if "daily" in e.field], ok


def test_g1_validator_bad_shape_red() -> None:
    r = check_pack({"quest": [{"id": "q", "name": "Q", "daily": "yes"}]})
    assert [e for e in r.errors if e.kind == "R-1" and e.field.endswith("daily")]


# ---------------------------------------------------------------------------
# G1 引擎消费：时间注入（周期到点 ⇄ 可再接取）
# ---------------------------------------------------------------------------
def test_g1_daily_period_resets_after_one_day() -> None:
    daily = {"count": 1, "unit": "日"}
    done = _complete(_BASE_TS, daily)
    same = _carry(done, _BASE_TS, daily)
    assert Q.quest_accept("q_reset", same)["reason"] == "already_completed"
    later = _carry(done, _BASE_TS + _DAY, daily)
    assert Q.quest_accept("q_reset", later)["ok"] is True


def test_g1_legacy_daily_true_equals_one_day() -> None:
    done = _complete(_BASE_TS, True)
    rec = done["quest_completed_at"]["q_reset"]
    assert isinstance(rec, dict) and "day" in rec
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS, True))["reason"] == "already_completed"
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + _DAY, True))["ok"] is True


def test_g1_weekly_period() -> None:
    daily = {"count": 1, "unit": "周"}
    done = _complete(_BASE_TS, daily)
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 2 * _DAY, daily))["ok"] is False
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 8 * _DAY, daily))["ok"] is True


def test_g1_hour_period() -> None:
    daily = {"count": 2, "unit": "时"}
    done = _complete(_BASE_TS, daily)
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 3600, daily))["ok"] is False
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 7200, daily))["ok"] is True


def test_g1_month_period() -> None:
    daily = {"count": 1, "unit": "月"}
    done = _complete(_BASE_TS, daily)
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 20 * _DAY, daily))["ok"] is False
    assert Q.quest_accept("q_reset", _carry(done, _BASE_TS + 31 * _DAY, daily))["ok"] is True


def test_g1_never_reset() -> None:
    daily = {"count": -1, "unit": "日"}
    done = _complete(_BASE_TS, daily)
    assert done.get("quest_completed_at") is None, "-1 永不重置 → 不落完成时刻"
    after = _carry(done, _BASE_TS + 365 * _DAY, daily)
    assert Q.quest_accept("q_reset", after)["reason"] == "already_completed"


def test_g1_board_hides_until_reset() -> None:
    daily = {"count": 1, "unit": "日"}
    done = _complete(_BASE_TS, daily)
    same = _carry(done, _BASE_TS, daily)
    board = Q.quest_board(same)
    ids = [r["quest_id"] for s in board["sections"] for r in s["rows"]]
    assert "q_reset" not in ids, "同周期内已完成 → 不上可接板"
    later = _carry(done, _BASE_TS + _DAY, daily)
    board2 = Q.quest_board(later)
    ids2 = [r["quest_id"] for s in board2["sections"] for r in s["rows"]]
    assert "q_reset" in ids2, "周期到点 → 重回可接板"


# ---------------------------------------------------------------------------
# G1 回归：不带 daily → 完成后永久完成（行为与现状一致）
# ---------------------------------------------------------------------------
def test_g1_regression_without_field_permanent() -> None:
    done = _complete(_BASE_TS, None)
    assert "q_reset" not in (done.get("quest_completed_at") or {})
    after = _carry(done, _BASE_TS + 3650 * _DAY, None)
    assert Q.quest_accept("q_reset", after)["reason"] == "already_completed"


# ---------------------------------------------------------------------------
# G1 端到端：临时内容根建包 → 加载 → 周期到点可再接
# ---------------------------------------------------------------------------
def test_g1_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_g1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_g1", "version": "1", "schema_version": 1,
         "modules": ["quest"]}, ensure_ascii=False), encoding="utf-8")
    (root / "quest.json").write_text(json.dumps(
        [{"id": "q_reset", "name": "周期任务", "repeatable": False, "conditions": [],
          "daily": {"count": 1, "unit": "日"}}], ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    quests = {q["id"]: q for q in pack.modules["quest"]}
    ctx = _ctx(_BASE_TS)
    ctx["quests"] = quests
    assert Q.quest_accept("q_reset", ctx)["ok"] is True
    assert Q.quest_complete("q_reset", ctx)["ok"] is True
    later = _ctx(_BASE_TS + _DAY)
    later["quests"] = quests
    later["quest_completed"] = list(ctx["quest_completed"])
    later["quest_completed_at"] = dict(ctx["quest_completed_at"])
    assert Q.quest_accept("q_reset", later)["ok"] is True
