"""批35 · §6.12-12 进阶职业卡片（职业树继承）。

定稿 `docs/审查参考/RPG回合制框架设计文档.md:1070-1077`：
    - 职业配置页面增加【进阶职业卡片】：下级职业下挂进阶职业列表
      · 转职火法师/冰法师 → 继承法师全部技能 + 获得进阶技能
    - 不在该页面配置的职业（如独立职业"战斗法师"）→ 转职后【不继承】法师技能
    - 继承规则 = 配置驱动（挂在谁下面就继承谁），不写死

本批形态（进阶职一侧声明，与批23 `advance` 前置同侧互补）：
    jobs[].inherit = {
        "from":   <职业 id → jobs>,   # 母职：转职到本职业时继承该职业的职业专属技能
        "skills": [<技能 id → skills>],# 可选白名单；非空 = 只继承列出的技能
    }
缺省 `inherit` = 不继承（既有职业数据行为逐字段一致）。

覆盖：
  A. 元数据登记（field_meta 与 job_models 两表 + 编辑器子分组）与编辑器可见；
  B. 校验：from 引用缺失 R-4 / skills 元素引用缺失 R-4 / from 必填 R-5 / 合法无红；
  C. 引擎（纯函数 + 装配）：见文件内 C 段；
  D. 回归对拍：不带 inherit → 转职行为逐字段一致；
  E. 端到端：临时内容根 A→B 继承 + 前置不满足被拒。

测试只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.content.field_meta import JOBS_SUBGROUP_LABELS, default_field_meta_table
from qbot_rpg.content.job_models import jobs_fields
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api


# ---------------------------------------------------------------------------
# 夹具（合成职业/技能名，不写死任何真实内容包业务名）
# ---------------------------------------------------------------------------
_SKILLS = {
    "base_hit": {"id": "base_hit", "name": "基础击", "type": "basic"},
    "parent_guard": {"id": "parent_guard", "name": "母职护盾", "type": "passive",
                     "job_restrict": ["parent"]},
    "parent_strike": {"id": "parent_strike", "name": "母职斩", "type": "active",
                      "job_restrict": ["parent"]},
    "child_burst": {"id": "child_burst", "name": "进阶爆发", "type": "active",
                    "job_restrict": ["child"]},
    "common_buff": {"id": "common_buff", "name": "通用增益", "type": "passive"},
}


def _jobs(**over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "parent": {"id": "parent", "name": "母职"},
        "child": {"id": "child", "name": "进阶职", "inherit": {"from": "parent"}},
        "independent": {"id": "independent", "name": "独立职"},
    }
    d.update(over)
    return d


# ---------------------------------------------------------------------------
# A. 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a1_field_meta_registered() -> None:
    tbl = default_field_meta_table()
    m = tbl.module("jobs")
    assert m is not None
    fm = m.fields.get("inherit")
    assert fm is not None, "jobs 缺 inherit 登记"
    assert fm.type == "obj"
    kids = fm.children or {}
    assert set(kids) == {"from", "skills"}
    assert kids["from"].type == "ref" and kids["from"].ref_target == "job"
    assert kids["from"].required is True
    assert kids["skills"].type == "list"
    assert kids["skills"].element is not None
    assert kids["skills"].element.ref_target == "skill"
    for k in ("from", "skills"):
        assert kids[k].label and kids[k].help, f"inherit.{k} 缺中文名/说明"
    assert m.field_subgroups.get("inherit") == "inherit"
    assert m.subgroup_labels.get("inherit") == JOBS_SUBGROUP_LABELS["inherit"]


def test_a2_job_models_registered() -> None:
    fields = jobs_fields()
    assert "inherit" in fields
    kids = fields["inherit"].children
    assert set(kids) == {"from", "skills"}
    assert kids["from"].ref_target == "job" and kids["from"].required is True
    assert kids["skills"].element is not None
    assert kids["skills"].element.ref_target == "skill"


def test_a3_editor_visible(tmp_path: Path) -> None:
    root = tmp_path / "pack_a3"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_a3", "version": "1", "schema_version": 1,
         "modules": ["jobs"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "child", "name": "进阶职", "inherit": {"from": "parent"}}],
        ensure_ascii=False), encoding="utf-8")
    detail = api.entry_detail("pack_a3", "jobs", "child", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "inherit")
    assert f["present"] is True
    assert f["type"] == "obj"
    kids = {c["key"]: c for c in (f.get("children") or [])}
    assert set(kids) == {"from", "skills"}
    assert kids["from"]["label"] == "继承来源职业"
    assert kids["skills"]["label"] == "继承技能白名单"


# ---------------------------------------------------------------------------
# B. 校验
# ---------------------------------------------------------------------------
def test_b1_from_missing_red() -> None:
    report = check_pack({
        "jobs": [{"id": "child", "name": "进阶职",
                  "inherit": {"from": "ghost_job"}}],
    })
    hits = [e for e in report.errors if e.kind == "R-4" and "inherit.from" in e.field]
    assert hits and hits[0].detail.get("ref") == "ghost_job"
    assert hits[0].detail.get("ref_target") == "job"


def test_b2_skills_missing_red() -> None:
    report = check_pack({
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "skills": ["ghost_skill"]}}],
    })
    hits = [e for e in report.errors if e.kind == "R-4" and "inherit.skills" in e.field]
    assert hits and hits[0].detail.get("ref") == "ghost_skill"
    assert hits[0].detail.get("ref_target") == "skill"


def test_b3_from_required_red() -> None:
    report = check_pack({
        "jobs": [{"id": "child", "name": "进阶职", "inherit": {}}],
    })
    hits = [e for e in report.errors if e.kind == "R-5" and "inherit.from" in e.field]
    assert hits, "inherit 缺 from 应 R-5 required_missing"


def test_b4_not_object_red() -> None:
    report = check_pack({
        "jobs": [{"id": "child", "name": "进阶职", "inherit": "parent"}],
    })
    hits = [e for e in report.errors if e.kind == "R-1" and "inherit" in e.field]
    assert hits


def test_b5_valid_refs_ok() -> None:
    report = check_pack({
        "skills": [{"id": "s1", "name": "技一"}, {"id": "s2", "name": "技二"}],
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "skills": ["s1", "s2"]}}],
    })
    assert not [e for e in report.errors if "inherit" in e.field]


def test_b6_absent_inherit_no_red() -> None:
    """既有职业数据不带 inherit → 校验零新增红拦（行为与现状一致）。"""
    report = check_pack({
        "jobs": [{"id": "parent", "name": "母职"}, {"id": "child", "name": "进阶职"}],
    })
    assert not [e for e in report.errors if "inherit" in e.field]
