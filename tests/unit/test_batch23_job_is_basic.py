"""批23 · C2：基础/初始职业标记 `is_basic`（CakeGame Config_Occupation.Basics；§三 C2）。

现状核查（本批报告结论）：
  · 我们**没有**「多起始职业选择」——注册流程只由 `default_job` 兜底链**自动**取一个
    缺省职业：`settings.default_job_id → 首个 recommended_newbie → jobs 首条`。
  · 因此 `is_basic` 不引入新的选择 UX（系统级改造，超出本批）；本批给它最小真实消费：
    兜底链在「推荐」之后取**首个 is_basic**（`is_basic` = 「有资格作为初始职业」，
    与「推荐」分工），并在职业列表标注「（初始）」。既有包不带该字段 → 行为不变。

覆盖：
  - 元数据登记（jobs，bool，中文 label/help，base 子分组）+ 编辑器接口可见；
  - 校验：非 bool → 泛型 R-1 红；true/false/缺省 → 无红；
  - 引擎消费：default_job 兜底链取首个 is_basic（修前/修后对照）；推荐/default_job_id
    优先级更高；回归：不带 is_basic 逐字段一致；
  - 展示消费：职业列表「（初始）」标注。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.commands.job_commands import _job_list_render
from qbot_rpg.commands.register_commands import default_job
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api


# ---------------------------------------------------------------------------
# C2 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_c2_metadata_registered() -> None:
    tbl = default_field_meta_table()
    fm = tbl.module("jobs").fields.get("is_basic")
    assert fm is not None, "jobs 缺 is_basic 登记"
    assert fm.type == "bool"
    assert fm.label and fm.help
    assert tbl.module("jobs").field_subgroups.get("is_basic") == "base"


def test_c2_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_c2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_c2", "version": "1", "schema_version": 1,
         "modules": ["jobs"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "warrior", "name": "战士", "is_basic": True}],
        ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_c2", "jobs", "warrior", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "is_basic")
    assert f["present"] is True
    assert f["type"] == "bool"
    assert f["label"] == "基础/初始职业"


# ---------------------------------------------------------------------------
# C2 校验：仅布尔
# ---------------------------------------------------------------------------
def test_c2_validator_bool_domain() -> None:
    bad = check_pack({"jobs": [{"id": "a", "name": "甲", "is_basic": "true"}]})
    assert [e for e in bad.errors if e.kind == "R-1" and "is_basic" in e.field]
    ok = check_pack({"jobs": [
        {"id": "a", "name": "甲", "is_basic": True},
        {"id": "b", "name": "乙", "is_basic": False},
        {"id": "c", "name": "丙"},
    ]})
    assert not [e for e in ok.errors if "is_basic" in e.field]


# ---------------------------------------------------------------------------
# C2 引擎消费：default_job 兜底链
# ---------------------------------------------------------------------------
def test_c2_default_job_prefers_basic() -> None:
    """修前：无推荐/无 default → jobs 首条（甲）；修后：取首个 is_basic（乙）。"""
    ctx: Dict[str, Any] = {"jobs": {
        "a": {"name": "甲"},
        "b": {"name": "乙", "is_basic": True},
    }}
    assert default_job(ctx)["id"] == "b"  # 首个 is_basic


def test_c2_default_job_id_wins() -> None:
    ctx: Dict[str, Any] = {
        "settings": {"default_job_id": "a"},
        "jobs": {"a": {"name": "甲"}, "b": {"name": "乙", "is_basic": True}},
    }
    assert default_job(ctx)["id"] == "a"


def test_c2_recommended_newbie_wins_over_basic() -> None:
    ctx: Dict[str, Any] = {"jobs": {
        "a": {"name": "甲", "is_basic": True},
        "b": {"name": "乙", "recommended_newbie": True},
    }}
    assert default_job(ctx)["id"] == "b"  # 推荐优先于初始（既有语义不翻转）


def test_c2_regression_without_field_identical() -> None:
    """回归：不带 is_basic → 兜底链与现状逐字段一致（首个推荐 → jobs 首条）。"""
    ctx1: Dict[str, Any] = {"jobs": {"a": {"name": "甲"}, "b": {"name": "乙"}}}
    assert default_job(ctx1)["id"] == "a"          # jobs 首条（现状）
    ctx2: Dict[str, Any] = {"jobs": {
        "a": {"name": "甲"},
        "b": {"name": "乙", "recommended_newbie": True},
    }}
    assert default_job(ctx2)["id"] == "b"          # 首个推荐（现状）
    # 空 jobs → None（现状）
    assert default_job({"jobs": {}}) is None


# ---------------------------------------------------------------------------
# C2 展示消费：职业列表「（初始）」标注
# ---------------------------------------------------------------------------
def test_c2_job_list_marks_basic() -> None:
    ctx: Dict[str, Any] = {"jobs": {
        "a": {"name": "甲", "is_basic": True},
        "b": {"name": "乙"},
        "c": {"name": "丙", "recommended_newbie": True},
    }}
    out = _job_list_render(ctx, 1)
    assert "1. 甲（初始）" in out
    assert "2. 乙\n" in out and "乙（" not in out  # 非初始/非推荐无角标
    assert "3. 丙（推荐）" in out


# ---------------------------------------------------------------------------
# C2 端到端：临时内容根建包 → 加载 → 缺省职业取 is_basic
# ---------------------------------------------------------------------------
def test_c2_e2e_temp_content_root(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    root = tmp_path / "pack_e2e_c2"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_c2", "version": "1", "schema_version": 1,
         "modules": ["jobs"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "warrior", "name": "战士"},
        {"id": "novice", "name": "新手", "is_basic": True}],
        ensure_ascii=False), encoding="utf-8")
    pack, _changed = build_pack(root)
    jobs = {e["id"]: dict(e) for e in pack.modules["jobs"]}
    assert default_job({"jobs": jobs})["id"] == "novice"
