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
from types import SimpleNamespace
from typing import Any, Dict, List

from qbot_rpg.commands.job_commands import cmd_job
from qbot_rpg.content.field_meta import JOBS_SUBGROUP_LABELS, default_field_meta_table
from qbot_rpg.content.job_models import jobs_fields
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.job_slots import (
    inherited_skill_ids,
    rearrange_job_slots,
    resolve_inherit_chain,
)
from qbot_rpg.core.skill_slots import assemble_slots, job_visible
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
    assert set(kids) == {"from", "skills", "mode", "replace"}
    assert kids["from"].type == "ref" and kids["from"].ref_target == "job"
    assert kids["from"].required is True
    assert kids["skills"].type == "list"
    assert kids["skills"].element is not None
    assert kids["skills"].element.ref_target == "skill"
    assert kids["mode"].type == "str"
    assert set(kids["mode"].enum_options) == {"append", "replace"}
    assert kids["replace"].type == "obj"
    assert kids["replace"].editor == "kvtable"
    for k in ("from", "skills", "mode", "replace"):
        assert kids[k].label and kids[k].help, f"inherit.{k} 缺中文名/说明"
        assert len(kids[k].help) <= 60, f"inherit.{k} help 超 60 字"
    assert m.field_subgroups.get("inherit") == "inherit"
    assert m.subgroup_labels.get("inherit") == JOBS_SUBGROUP_LABELS["inherit"]


def test_a2_job_models_registered() -> None:
    fields = jobs_fields()
    assert "inherit" in fields
    kids = fields["inherit"].children
    assert set(kids) == {"from", "skills", "mode", "replace"}
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
    assert set(kids) == {"from", "skills", "mode", "replace"}
    assert kids["from"]["label"] == "继承来源职业"
    assert kids["skills"]["label"] == "继承技能白名单"
    assert kids["mode"]["label"] == "继承模式"
    assert kids["mode"]["control"] == "select"
    assert kids["mode"]["enum_options"] == ["append", "replace"]
    assert kids["replace"]["label"] == "继承技能替换"
    assert kids["replace"]["control"] == "kvtable"


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


# ---------------------------------------------------------------------------
# C. 引擎：继承解析纯函数 + 装配
# ---------------------------------------------------------------------------
def test_c1_chain_single_and_transitive() -> None:
    jobs = {
        "a": {"id": "a"},
        "b": {"id": "b", "inherit": {"from": "a"}},
        "c": {"id": "c", "inherit": {"from": "b"}},
        "indep": {"id": "indep"},
    }
    assert resolve_inherit_chain("child", jobs) == ()
    assert resolve_inherit_chain("indep", jobs) == ()
    assert resolve_inherit_chain("b", jobs) == ("a",)
    assert resolve_inherit_chain("c", jobs) == ("b", "a")  # 传递闭包（职业树）
    assert resolve_inherit_chain(None, jobs) == ()
    assert resolve_inherit_chain("c", None) == ()


def test_c2_chain_cycle_and_dangling_safe() -> None:
    cyclic = {"a": {"id": "a", "inherit": {"from": "b"}},
              "b": {"id": "b", "inherit": {"from": "a"}}}
    assert resolve_inherit_chain("a", cyclic) == ("b",)  # 环安全：不无限递归
    dangling = {"a": {"id": "a", "inherit": {"from": "ghost"}}}
    assert resolve_inherit_chain("a", dangling) == ()  # 悬空 → 停链（校验器 R-4 负责红拦）


def test_c3_inherited_skill_ids_all_and_whitelist() -> None:
    jobs = _jobs()
    skills = list(_SKILLS.values())
    # 不带白名单：继承母职全部职业专属技能；通用技能不算继承；进阶职自身不算
    got = inherited_skill_ids("child", jobs, skills)
    assert set(got) == {"parent_guard", "parent_strike"}
    # 白名单：只继承列出的
    jobs2 = _jobs(child={"id": "child", "name": "进阶职",
                         "inherit": {"from": "parent", "skills": ["parent_strike"]}})
    assert inherited_skill_ids("child", jobs2, skills) == ("parent_strike",)
    # 独立职业不继承
    assert inherited_skill_ids("independent", jobs, skills) == ()
    # 链上无 inherit / 空技能表 → 空
    assert inherited_skill_ids("child", jobs, []) == ()
    assert inherited_skill_ids("child", {}, skills) == ()


def test_c4_inherited_ids_dedup_library_order() -> None:
    jobs = {"a": {"id": "a"},
            "b": {"id": "b", "inherit": {"from": "a"}},
            "c": {"id": "c", "inherit": {"from": "b"}}}
    skills = [
        {"id": "s_b", "type": "active", "job_restrict": ["b"]},
        {"id": "s_a", "type": "passive", "job_restrict": ["a"]},
        {"id": "s_a", "type": "passive", "job_restrict": ["a"]},  # 重复 → 去重
    ]
    assert inherited_skill_ids("c", jobs, skills) == ("s_b", "s_a")


def test_c5_job_visible_inherited_extension() -> None:
    def _sk(sid: str, restrict: Any = ()) -> Any:
        return SimpleNamespace(id=sid, type="active",
                               job_restrict=tuple(restrict), job_form=None)

    skill = _sk("p_pass", ["parent"])
    assert not job_visible(skill, "child")
    assert job_visible(skill, "child", ["p_pass"])
    assert job_visible(skill, "parent")
    # 通用技能与 job_id 缺失口径不受影响
    assert job_visible(_sk("x"), "child", [])
    assert job_visible(skill, None, [])


def test_c6_assemble_slots_inherits_slots() -> None:
    skills = list(_SKILLS.values())
    snap = assemble_slots(skills, {"job_id": "child", "inherited_skill_ids": [
        "parent_guard", "parent_strike"]})
    ids = [s["skill_id"] for s in snap["slots"]]
    assert "parent_guard" in ids and "parent_strike" in ids
    assert "child_burst" in ids
    # 继承来的 basic（母职 basic）不抢本职业 basic 槽
    snap2 = assemble_slots(
        [{"id": "p_basic", "type": "basic", "job_restrict": ["parent"]},
         {"id": "c_basic", "type": "basic", "job_restrict": ["child"]}],
        {"job_id": "child", "inherited_skill_ids": ["p_basic"]})
    assert snap2["slots"][0]["skill_id"] == "c_basic"


def test_c7_rearrange_job_slots_wires_inheritance() -> None:
    ctx = {"skills": dict(_SKILLS), "jobs": _jobs()}
    snap = rearrange_job_slots(ctx, "child")
    ids = [s["skill_id"] for s in snap["slots"]]
    assert "parent_guard" in ids and "parent_strike" in ids and "child_burst" in ids
    # 独立职业不继承
    indep = rearrange_job_slots(ctx, "independent")
    ids2 = [s["skill_id"] for s in indep["slots"]]
    assert "parent_guard" not in ids2 and "parent_strike" not in ids2
    # 母职自身结果不变
    parent = rearrange_job_slots(ctx, "parent")
    ids3 = [s["skill_id"] for s in parent["slots"]]
    assert ids3 == ["base_hit", "parent_strike", "parent_guard", "common_buff"]


# ---------------------------------------------------------------------------
# D. 回归对拍：不带 inherit → 与现状逐字段一致
# ---------------------------------------------------------------------------
def _skills_with_own_job(job_id: str) -> List[Dict[str, Any]]:
    return [
        {"id": "own_basic", "type": "basic", "job_restrict": [job_id]},
        {"id": "own_act1", "type": "active", "job_restrict": [job_id]},
        {"id": "own_act2", "type": "active"},
        {"id": "own_pass", "type": "passive", "job_restrict": [job_id]},
        {"id": "own_trig", "type": "trigger", "job_restrict": [job_id]},
        {"id": "other_pass", "type": "passive", "job_restrict": ["someone_else"]},
    ]


def test_d1_no_inherit_matches_assemble_slots_baseline() -> None:
    """不带 inherit 的职业：rearrange 结果 == 直接 assemble_slots（现状路径）逐字段。"""
    for job_id in ("solo", "plain"):
        jobs = {job_id: {"id": job_id, "name": job_id}}
        skills = _skills_with_own_job(job_id)
        ctx = {"skills": {s["id"]: s for s in skills}, "jobs": jobs,
               "active_order": ["own_act2", "own_act1"]}
        got = rearrange_job_slots(ctx, job_id)
        want = assemble_slots(list(ctx["skills"].values()),
                              {"job_id": job_id, "active_order": ["own_act2", "own_act1"]})
        assert got == want


def test_d2_job_visible_backward_compatible() -> None:
    """job_visible 两参 == 三参空集（后向兼容：矩阵全覆盖）。"""
    def _sk(sid: str, restrict: Any = ()) -> Any:
        return SimpleNamespace(id=sid, type="active",
                               job_restrict=tuple(restrict), job_form=None)

    mat = [_sk("a"), _sk("b", ["x"]), _sk("c", ["y", "z"])]
    for s in mat:
        for jid in (None, "x", "y", "z", "w"):
            assert job_visible(s, jid) == job_visible(s, jid, ())


def test_d3_rearrange_no_inherit_ignores_jobs_table() -> None:
    """即使 ctx 带 jobs 表，缺 inherit 的职业也不注入 inherit 集（输出与无 jobs 表一致）。"""
    skills = _skills_with_own_job("solo")
    no_jobs = rearrange_job_slots({"skills": {s["id"]: s for s in skills}}, "solo")
    with_jobs = rearrange_job_slots(
        {"skills": {s["id"]: s for s in skills},
         "jobs": {"solo": {"id": "solo", "name": "独"}}}, "solo")
    assert no_jobs == with_jobs


# ---------------------------------------------------------------------------
# E. 端到端：临时内容根 A→B 继承 + 前置不满足被拒
# ---------------------------------------------------------------------------
def _write_pack(root: Path) -> None:
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": "pack_e2e_b35", "version": "1", "schema_version": 1,
         "modules": ["jobs", "skills"]}, ensure_ascii=False), encoding="utf-8")
    (root / "jobs.json").write_text(json.dumps([
        {"id": "job_a", "name": "甲职"},
        {"id": "job_b", "name": "乙职",
         "advance": {"from": "job_a", "level": 5},
         "inherit": {"from": "job_a"}},
    ], ensure_ascii=False), encoding="utf-8")
    (root / "skills.json").write_text(json.dumps([
        {"id": "a_basic", "name": "甲普攻", "type": "basic", "job_restrict": ["job_a"]},
        {"id": "a_pass", "name": "甲被动", "type": "passive", "job_restrict": ["job_a"]},
        {"id": "b_basic", "name": "乙普攻", "type": "basic", "job_restrict": ["job_b"]},
        {"id": "b_act", "name": "乙主动", "type": "active", "job_restrict": ["job_b"]},
        {"id": "common", "name": "通用", "type": "active"},
    ], ensure_ascii=False), encoding="utf-8")


def _parsed(arg: str) -> Any:
    return SimpleNamespace(error=None, args=[arg], raw=f"/转职 {arg}", command="转职")


def test_e1_e2e_inherit_and_gate(tmp_path: Path) -> None:
    from qbot_rpg.content.loader import build_pack

    _write_pack(tmp_path / "pack_e2e_b35")
    pack, _ = build_pack(tmp_path / "pack_e2e_b35")
    jobs = {e["id"]: dict(e) for e in pack.modules["jobs"]}
    skills = {e["id"]: dict(e) for e in pack.modules["skills"]}

    # 前置不满足（等级不足）→ 被拒；技能位不落档、job_id 不变
    bad = {"player": {"job_id": "job_a", "level": 3, "persistent_state": {}},
           "jobs": jobs, "skills": skills}
    out = cmd_job(_parsed("乙职"), bad)
    assert "5" in out and "❌" in out, out
    assert bad["player"]["job_id"] == "job_a"
    assert "skill_slots" not in bad
    assert "skill_slots" not in bad["player"]["persistent_state"]

    # 前置满足 → 转职；技能位含继承来的甲职技能 + 乙职自身技能
    good = {"player": {"job_id": "job_a", "level": 5, "persistent_state": {}},
            "jobs": jobs, "skills": skills}
    ok = cmd_job(_parsed("乙职"), good)
    assert ok.startswith("✅"), ok
    assert good["player"]["job_id"] == "job_b"
    snap = good["skill_slots"]
    ids = [s["skill_id"] for s in snap["slots"]]
    assert "a_pass" in ids, f"应继承甲职被动，实际 {ids}"
    assert "b_act" in ids and "common" in ids
    assert snap["slots"][0] == {"slot": "basic", "skill_id": "b_basic"}  # 本职业 basic 优先
    # 落档：persistent_state["skill_slots"] 与 ctx 一致
    ps = good["player"]["persistent_state"]
    assert ps["skill_slots"]["active_order"] == snap["active_order"]

