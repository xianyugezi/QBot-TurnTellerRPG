"""批25 · I1：成就计入总数 `counted`（CakeGame `成就系统.md:88` `AddTrue`）。

设计口径（本批拍板，写进报告）：
  · `counted` bool（缺省 true）：**完成度统计的分母只计 counted=true 的成就**
    （隐藏/彩蛋成就不拉低「全成就」进度），分子与分母同口径（避免 >100%）；
  · `counted=false` 的成就**照常可达成、照常发奖**——只影响完成度，不影响玩法；
  · 与 `hidden`（是否隐藏）**正交**：隐藏 ≠ 不计入（他们也是独立两列）。

覆盖：元数据登记 + 编辑器可见 / 校验 / 引擎完成度（数值级）/ 达成发奖 / 指令壳列表头 / 回归。
"""
from __future__ import annotations

import json
from pathlib import Path

from qbot_rpg.commands.achievement_commands import cmd_achievements
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.achievements import achievement_progress, check_achievements
from qbot_rpg.web import api


def _ctx(cfg: dict, unlocked=None, **extra) -> dict:
    ctx = {
        "achievements": {k: dict(v) for k, v in cfg.items()},
        "achievement_state": {"unlocked": dict(unlocked or {}), "repeat_count": {}},
        "today": "2026-09-16",
        "level": 10,
        "inventory": {},
        "currencies": {"coins": 0},
        "settings": {"currencies": [{"id": "coins"}, {"id": "diamond"}]},
        "ledger": set(),
        "tx_id": None,
    }
    ctx.update(extra)
    return ctx


class _P:
    def __init__(self, *args: str):
        self.args = tuple(args)
        self.error = None
        self.fragment = ""


# ---------------------------------------------------------------------------
# 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_i1_metadata_registered() -> None:
    fm = default_field_meta_table().module("achievements").fields.get("counted")
    assert fm is not None, "achievements 缺 counted 登记"
    assert fm.type == "bool"
    assert fm.label == "计入总数"
    assert fm.help, "counted 缺中文说明"
    # 与 hidden 正交：两个键都在
    assert "hidden" in default_field_meta_table().module("achievements").fields


def test_i1_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_i1"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_i1", "version": "1", "schema_version": 1, "modules": ["achievements"]},
        ensure_ascii=False), encoding="utf-8")
    (root / "achievements.json").write_text(json.dumps([{
        "id": "ach_egg", "name": "彩蛋", "desc": "", "counted": False,
        "conditions": [{"var": "level", "op": "ge", "value": 1}],
    }], ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_i1", "achievements", "ach_egg", root=tmp_path)
    f = next(x for x in d["fields"] if x["key"] == "counted")
    assert f["present"] is True
    assert f["type"] == "bool"
    assert f["label"] == "计入总数"


# ---------------------------------------------------------------------------
# 校验：非 bool → R-1 红；true/false/缺省不红
# ---------------------------------------------------------------------------
def test_i1_validator_non_bool_red() -> None:
    report = check_pack({"achievements": [
        {"id": "a1", "name": "一", "counted": "no",
         "conditions": [{"var": "level", "op": "ge", "value": 1}]}]})
    assert [e for e in report.errors if e.kind == "R-1" and "counted" in e.field]


def test_i1_validator_bool_and_missing_ok() -> None:
    report = check_pack({"achievements": [
        {"id": "a1", "name": "一", "counted": True,
         "conditions": [{"var": "level", "op": "ge", "value": 1}]},
        {"id": "a2", "name": "二", "counted": False,
         "conditions": [{"var": "level", "op": "ge", "value": 1}]},
        {"id": "a3", "name": "三",
         "conditions": [{"var": "level", "op": "ge", "value": 1}]}]})
    assert not [e for e in report.errors if "counted" in e.field], report.errors


# ---------------------------------------------------------------------------
# 引擎消费：完成度分母只计 counted=true（数值级）
# ---------------------------------------------------------------------------
def test_i1_progress_excludes_uncounted() -> None:
    cfg = {
        "a1": {"id": "a1", "name": "一", "conditions": [{"var": "level", "op": "ge", "value": 1}]},
        "a2": {"id": "a2", "name": "二", "conditions": [{"var": "level", "op": "ge", "value": 99}]},
        "egg": {"id": "egg", "name": "彩蛋", "counted": False,
                "conditions": [{"var": "level", "op": "ge", "value": 99}]},
    }
    ctx = _ctx(cfg, unlocked={"a1": "2026-09-16", "egg": "2026-09-16"})
    prog = achievement_progress(ctx)
    # 分母 = 2（a1/a2；egg 的 counted=false 不计）而非 3；分子 = 1（egg 已达成但不计）
    assert prog == {"done": 1, "total": 2, "uncounted": 1}, prog


def test_i1_progress_all_counted_default() -> None:
    cfg = {
        "a1": {"id": "a1", "name": "一", "conditions": []},
        "a2": {"id": "a2", "name": "二", "conditions": []},
    }
    ctx = _ctx(cfg, unlocked={"a1": "2026-09-16"})
    assert achievement_progress(ctx) == {"done": 1, "total": 2, "uncounted": 0}


def test_i1_uncounted_still_achievable_and_grants() -> None:
    """counted=false 照常可达成、照常发奖（只是不参与完成度）。"""
    cfg = {"egg": {"id": "egg", "name": "彩蛋", "counted": False,
                   "conditions": [{"var": "level", "op": "ge", "value": 1}],
                   "reward": [{"coins": 7}]}}
    ctx = _ctx(cfg)
    r = check_achievements(ctx)
    assert [g["id"] for g in r["granted"]] == ["egg"], r
    assert ctx["currencies"]["coins"] == 7
    assert ctx["achievement_state"]["unlocked"]["egg"] == "2026-09-16"


# ---------------------------------------------------------------------------
# 指令壳：列表头完成度按 counted 过滤；分页仍按可见条目数
# ---------------------------------------------------------------------------
def test_i1_command_header_uses_counted_denominator() -> None:
    cfg = {
        "a1": {"id": "a1", "name": "成就一",
               "conditions": [{"var": "level", "op": "ge", "value": 1}]},
        "a2": {"id": "a2", "name": "成就二",
               "conditions": [{"var": "level", "op": "ge", "value": 99}]},
        "egg": {"id": "egg", "name": "彩蛋", "counted": False,
                "conditions": [{"var": "level", "op": "ge", "value": 99}]},
    }
    ctx = _ctx(cfg, unlocked={"a1": "2026-09-16"})
    out = cmd_achievements(_P(), ctx)
    assert "已达成 1/2" in out, out
    assert "彩蛋" in out  # 仍显示（不因不计入而隐藏）


def test_i1_command_pagination_uses_all_visible_entries() -> None:
    cfg = {}
    for i in range(7):
        cfg[f"a{i}"] = {"id": f"a{i}", "name": f"成就{i}",
                        "counted": i < 6,  # 最后一条不计入
                        "conditions": [{"var": "level", "op": "ge", "value": 1}]}
    ctx = _ctx(cfg)
    out = cmd_achievements(_P("2"), ctx)
    # 分页：7 条可见 / 5 条每页 → 2 页；完成度分母 = 6
    assert "第 2/2 页" in out, out
    assert "已达成 0/6" in out, out


# ---------------------------------------------------------------------------
# 回归：不带 counted → 分母含全部（与既有逐字段一致）
# ---------------------------------------------------------------------------
def test_i1_regression_without_field_identical() -> None:
    cfg = {
        "a1": {"id": "a1", "name": "一", "conditions": []},
        "a2": {"id": "a2", "name": "二", "conditions": []},
        "a3": {"id": "a3", "name": "三", "conditions": []},
    }
    ctx = _ctx(cfg, unlocked={"a1": "2026-09-16"})
    out = cmd_achievements(_P(), ctx)
    assert "已达成 1/3" in out, out
