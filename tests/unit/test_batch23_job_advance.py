"""批23 · C1：转职前置三件套合并为一个 `advance` 子对象（CakeGame Config_Occupation
TransferDemand/TransferLevel/FormerOccupation；§三 C1）。

形态（**不开三个顶层字段**）：
    jobs[].advance = {
        "from":  <职业 id → jobs>,   # 当前必须正处于该职业
        "level": <int ≥ 1>,          # 转职等级门槛
        "items": [<物品 id → items>],# 转职须持有的物品（全部）
    }
三项均可选，缺省 = 无该条件。**既有职业数据不带 advance → 行为与现状一致**。

覆盖：
  - 元数据登记（jobs.advance obj + 三子字段；from/items 走 ref → 泛型 R-4 硬拦）
    + 编辑器接口可见（子字段 present / label）；
  - 校验：from 引用缺失 → R-4 红；items 元素引用缺失 → R-4 红；level 非整数 R-1、
    负数 R-2、0 → Y-1 黄提示；合法/缺省 → 无红；
  - 引擎消费：转职判定逐项校验，不满足给人话（要求值 vs 当前值）；
  - 回归对拍：不带 advance / advance 为空对象 → 转职行为与现状逐字段一致。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Mapping, Optional

from qbot_rpg.commands.job_commands import _advance_block, cmd_job
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api


# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------
def _jobs(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "warrior": {"name": "战士"},
        "mage": {"name": "法师"},
        "blade_master": {"name": "剑豪",
                         "advance": {"from": "warrior", "level": 5, "items": ["proof"]}},
        "plain": {"name": "无门槛职业"},
    }
    d.update(over)
    return d


_ITEMS = {"proof": {"id": "proof", "name": "转职证明"}}


def _ctx(job_id: str, level: int, items: Optional[Mapping[str, int]] = None,
         jobs: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    inv = [{"item_id": k, "count": v} for k, v in (items or {}).items()]
    return {
        "player": {"job_id": job_id, "level": level, "inventory": inv},
        "jobs": jobs if jobs is not None else _jobs(),
        "items": _ITEMS,
    }


def _parsed(arg: str) -> Any:
    return SimpleNamespace(error=None, args=[arg], raw=f"/转职 {arg}", command="转职")


# ---------------------------------------------------------------------------
# C1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_c1_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("jobs").fields.get("advance")
    assert fm is not None, "jobs 缺 advance 登记"
    assert fm.type == "obj"
    kids = fm.children or {}
    assert set(kids) == {"from", "level", "items"}
    assert kids["from"].type == "ref" and kids["from"].ref_target == "job"
    assert kids["level"].type == "int" and kids["level"].range_min == 1
    assert kids["items"].type == "list"
    assert kids["items"].element is not None
    assert kids["items"].element.ref_target == "item"
    for k in ("from", "level", "items"):
        assert kids[k].label and kids[k].help, f"advance.{k} 缺中文名/说明"
    assert tbl.module("jobs").field_subgroups.get("advance") == "advance"
    assert tbl.module("jobs").subgroup_labels.get("advance") == "转职前置"


def test_c1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_c1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_c1", "version": "1", "schema_version": 1,
         "modules": ["jobs"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "blade_master", "name": "剑豪",
         "advance": {"from": "warrior", "level": 5, "items": ["proof"]}}],
        ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_c1", "jobs", "blade_master", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "advance")
    assert f["present"] is True
    assert f["type"] == "obj"
    kids = {c["key"]: c for c in (f.get("children") or [])}
    assert set(kids) == {"from", "level", "items"}
    assert kids["level"]["label"] == "转职等级门槛"
    assert kids["items"]["label"] == "转职需求物品"


# ---------------------------------------------------------------------------
# C1 校验：引用缺失红拦 / 值域
# ---------------------------------------------------------------------------
def test_c1_validator_from_missing_red() -> None:
    report = check_pack({
        "jobs": [{"id": "bm", "name": "剑豪", "advance": {"from": "ghost_job"}}],
    })
    hits = [e for e in report.errors if e.kind == "R-4" and "advance.from" in e.field]
    assert hits and hits[0].detail.get("ref") == "ghost_job"
    assert hits[0].detail.get("ref_target") == "job"


def test_c1_validator_items_missing_red() -> None:
    report = check_pack({
        "jobs": [{"id": "w", "name": "战士"}, {"id": "bm", "name": "剑豪",
                 "advance": {"items": ["ghost_item"]}}],
    })
    hits = [e for e in report.errors if e.kind == "R-4" and "advance.items" in e.field]
    assert hits and hits[0].detail.get("ref") == "ghost_item"
    assert hits[0].detail.get("ref_target") == "item"


def test_c1_validator_level_domains() -> None:
    # 非整数 → R-1；负数 → R-2；0 → Y-1 黄提示；合法 → 无红
    bad = check_pack({"jobs": [{"id": "a", "name": "甲", "advance": {"level": "5"}}]})
    assert [e for e in bad.errors if e.kind == "R-1" and "advance.level" in e.field]
    neg = check_pack({"jobs": [{"id": "a", "name": "甲", "advance": {"level": -1}}]})
    assert [e for e in neg.errors if e.kind == "R-2" and "advance.level" in e.field]
    zero = check_pack({"jobs": [{"id": "a", "name": "甲", "advance": {"level": 0}}]})
    assert [w for w in zero.warnings if w.kind == "Y-1" and "advance.level" in w.field]
    ok = check_pack({"jobs": [{"id": "a", "name": "甲",
                               "advance": {"from": "a", "level": 3, "items": []}}]})
    assert not [e for e in ok.errors if "advance" in e.field]


def test_c1_validator_valid_refs_ok() -> None:
    report = check_pack({
        "items": [{"id": "proof", "name": "转职证明"}],
        "jobs": [{"id": "warrior", "name": "战士"},
                 {"id": "bm", "name": "剑豪",
                  "advance": {"from": "warrior", "level": 5, "items": ["proof"]}}],
    })
    assert not [e for e in report.errors if "advance" in e.field]


# ---------------------------------------------------------------------------
# C1 引擎消费：逐项校验 + 人话提示（要求值 vs 当前值）
# ---------------------------------------------------------------------------
def test_c1_engine_from_mismatch() -> None:
    assert cmd_job(_parsed("剑豪"), _ctx("mage", 9, {"proof": 1})) == (
        "❌ 转职前置不满足：需要当前职业为「战士」\n当前职业：法师")


def test_c1_engine_level_too_low() -> None:
    assert cmd_job(_parsed("剑豪"), _ctx("warrior", 3, {"proof": 1})) == (
        "❌ 转职前置不满足：需要达到 5 级\n当前等级：3 级")


def test_c1_engine_item_missing() -> None:
    assert cmd_job(_parsed("剑豪"), _ctx("warrior", 9, {})) == (
        "❌ 转职前置不满足：需要持有「转职证明」\n当前数量 0 / 需要 1")


def test_c1_engine_satisfied_switches() -> None:
    ctx = _ctx("warrior", 5, {"proof": 1})
    out = cmd_job(_parsed("剑豪"), ctx)
    assert out == "✅ 转职成功\n当前职业：剑豪", out
    assert ctx["player"]["job_id"] == "blade_master"
    assert ctx["job_id"] == "blade_master"


def test_c1_engine_item_count_forms() -> None:
    """持有数量三形态：ItemInstance 序列 / {id: 数量} 映射 / count_item 钩子。"""
    c1 = _ctx("warrior", 5, {"proof": 1})
    assert cmd_job(_parsed("剑豪"), c1).startswith("✅")
    c2 = _ctx("warrior", 5, {})
    c2["inventory"] = {"proof": 2}
    assert cmd_job(_parsed("剑豪"), c2).startswith("✅")
    c3 = _ctx("warrior", 5, {})
    c3["count_item"] = lambda iid: 1
    assert cmd_job(_parsed("剑豪"), c3).startswith("✅")


def test_c1_engine_only_first_unsatisfied_reported() -> None:
    """逐项短路：from 优先于 level/items（提示缺的第一项）。"""
    block = _advance_block(_ctx("mage", 1, {}), _jobs()["blade_master"])
    assert "原职业" in block or "当前职业" in block


# ---------------------------------------------------------------------------
# C1 回归对拍：不带 advance / advance 空对象 → 与现状逐字段一致
# ---------------------------------------------------------------------------
def test_c1_regression_no_advance_identical() -> None:
    for job_name in ("无门槛职业", "战士"):
        ctx = _ctx("warrior", 1, {})
        out = cmd_job(_parsed(job_name), ctx)
        assert out == f"✅ 转职成功\n当前职业：{job_name}", out
        assert ctx["player"]["job_id"] == ("plain" if job_name == "无门槛职业" else "warrior")


def test_c1_regression_empty_advance_is_noop() -> None:
    jobs = _jobs(empty={"name": "空前置", "advance": {}})
    ctx = _ctx("mage", 1, {}, jobs=jobs)
    assert _advance_block(ctx, jobs["empty"]) == ""
    assert cmd_job(_parsed("空前置"), ctx) == "✅ 转职成功\n当前职业：空前置"


def test_c1_regression_gate_pure_no_mutation() -> None:
    """门禁是纯校验：不满足时不得改写 player / 不落档。"""
    ctx = _ctx("warrior", 3, {})
    before = json.dumps(ctx["player"], sort_keys=True, ensure_ascii=False)
    cmd_job(_parsed("剑豪"), ctx)
    assert json.dumps(ctx["player"], sort_keys=True, ensure_ascii=False) == before
    assert "job_id" not in ctx


# ---------------------------------------------------------------------------
# C1 端到端：临时内容根建包 → 加载 → 转职判定（不满足被拒 / 满足放行）
# ---------------------------------------------------------------------------
def test_c1_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_c1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_c1", "version": "1", "schema_version": 1,
         "modules": ["jobs", "items"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "warrior", "name": "战士"},
        {"id": "blade_master", "name": "剑豪",
         "advance": {"from": "warrior", "level": 5, "items": ["proof"]}}],
        ensure_ascii=False), encoding="utf-8")
    (root / "items.json").write_text(json.dumps([
        {"id": "proof", "name": "转职证明"}], ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    jobs = {e["id"]: dict(e) for e in pack.modules["jobs"]}
    items = {e["id"]: dict(e) for e in pack.modules["items"]}

    bad = _ctx("warrior", 3, {"proof": 1}, jobs=jobs)
    bad["items"] = items
    assert cmd_job(_parsed("剑豪"), bad) == (
        "❌ 转职前置不满足：需要达到 5 级\n当前等级：3 级")

    good = _ctx("warrior", 5, {"proof": 1}, jobs=jobs)
    good["items"] = items
    assert cmd_job(_parsed("剑豪"), good).startswith("✅")
    assert good["player"]["job_id"] == "blade_master"
