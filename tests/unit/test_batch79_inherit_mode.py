"""批79 · X18 销项验收：职业继承 `inherit.mode`（append/replace）+ `replace` 映射。

用户 2026-09-23 裁决（四问 Q1~Q4 回填，见 `docs/进阶职业继承_设计口径.md` §5）：
  ① 继承粒度 = 保持**传递闭包**（不改）；② `skills` 白名单 = 保持（空=全部）；
  ③ 新增 `mode`：`append`（默认=现状）/ `replace`（按 `replace` 映射替换继承技能）；
  ④ 技能等级继承 = **不做**（技能无等级维度，另立设计）。

本批形态：
    jobs[].inherit = {
        "from":    <职业 id → jobs>,        # 母职（批35，必填）
        "skills":  [<技能 id → skills>],     # 可选白名单（批35）
        "mode":    "append" | "replace",     # 批79；缺省/未知 = append
        "replace": {<母职技能id>: <本职业技能id>},  # 批79；空/缺省 = 等价 append
    }

覆盖：
  A. 引擎：append（未配置/显式/未知）与现状逐字段一致；replace 生效且未声明者照旧继承；
     replace 空/键未继承 = 等价 append；rearrange_job_slots 装配级验证。
  B. 校验：mode 未知 → 黄提示 Y-23（不硬拦）；replace 悬空 id 两侧 → 红拦 R-4；
     replace 非对象 → 泛型 R-1；合法 → 无红无黄。
  C. 编辑器可见：两表元数据登记（中文名/说明 ≤60 字）+ entry_detail 描述符
     （mode=select+enum_options；replace=kvtable）+ 前端按 enum_options 渲染下拉。

只建临时对象 / 临时内容根，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.content.field_meta import JOBS_SUBGROUP_LABELS, default_field_meta_table
from qbot_rpg.content.job_models import jobs_fields
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.job_slots import (
    INHERIT_MODES,
    inherited_skill_ids,
    rearrange_job_slots,
)
from qbot_rpg.core.skill_slots import assemble_slots
from qbot_rpg.web import api

# ---------------------------------------------------------------------------
# 夹具（合成职业/技能名，不写死任何真实内容包业务名）
# ---------------------------------------------------------------------------
_CHILD_JOBS = ["child", "child_a", "child_r", "child_re", "child_u", "child_rn"]
_SKILLS: List[Dict[str, Any]] = [
    {"id": "base_hit", "name": "基础击", "type": "basic"},
    {"id": "parent_guard", "name": "母职护盾", "type": "passive",
     "job_restrict": ["parent"]},
    {"id": "parent_strike", "name": "母职斩", "type": "active",
     "job_restrict": ["parent"]},
    {"id": "child_burst", "name": "进阶爆发", "type": "active",
     "job_restrict": list(_CHILD_JOBS)},
    {"id": "child_veil", "name": "进阶帷幕", "type": "passive",
     "job_restrict": list(_CHILD_JOBS)},
    {"id": "common_buff", "name": "通用增益", "type": "passive"},
]


def _jobs() -> Dict[str, Dict[str, Any]]:
    return {
        "parent": {"id": "parent", "name": "母职"},
        # 未配置 mode（现状路径）
        "child": {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent"}},
        # 显式 append
        "child_a": {"id": "child_a", "name": "进阶职-追加",
                    "inherit": {"from": "parent", "mode": "append"}},
        # replace：把母职护盾换成进阶帷幕
        "child_r": {"id": "child_r", "name": "进阶职-替换",
                    "inherit": {"from": "parent", "mode": "replace",
                                "replace": {"parent_guard": "child_veil"}}},
        # replace 空映射 → 等价 append
        "child_re": {"id": "child_re", "name": "进阶职-替换空",
                     "inherit": {"from": "parent", "mode": "replace",
                                 "replace": {}}},
        # 未知 mode → 引擎按 append（校验器黄提示）
        "child_u": {"id": "child_u", "name": "进阶职-未知",
                    "inherit": {"from": "parent", "mode": "weird"}},
        # replace 键不在继承集（child_burst 是本职业技能）→ 不生效
        "child_rn": {"id": "child_rn", "name": "进阶职-替换无关",
                     "inherit": {"from": "parent", "mode": "replace",
                                 "replace": {"child_burst": "common_buff"}}},
        "indep": {"id": "indep", "name": "独立职"},
    }


def _skills_list() -> List[Dict[str, Any]]:
    return [dict(s) for s in _SKILLS]


def _snapshot_ids(job_id: str) -> List[str]:
    ctx = {"skills": {s["id"]: s for s in _SKILLS}, "jobs": _jobs()}
    snap = rearrange_job_slots(ctx, job_id)
    return [s["skill_id"] for s in snap["slots"]]


# ===========================================================================
# A. 引擎
# ===========================================================================
def test_a1_inherit_modes_constant() -> None:
    assert INHERIT_MODES == ("append", "replace")


def test_a2_append_unconfigured_and_unknown_are_identical() -> None:
    """未配置 / 显式 append / 未知 mode（引擎安全默认）→ 继承集逐字段一致。"""
    jobs = _jobs()
    skills = _skills_list()
    base = inherited_skill_ids("child", jobs, skills)
    assert base == ("parent_guard", "parent_strike")
    assert inherited_skill_ids("child_a", jobs, skills) == base
    assert inherited_skill_ids("child_u", jobs, skills) == base


def test_a3_replace_effective_and_undeclared_still_inherited() -> None:
    """replace 生效：被替换的继承技能不在，替代技能在；**未声明**的照旧继承。"""
    got = inherited_skill_ids("child_r", _jobs(), _skills_list())
    assert "parent_guard" not in got, "被替换的继承技能不应在"
    assert "child_veil" in got, "替代技能应在"
    assert "parent_strike" in got, "未声明的继承技能照旧继承"
    assert got == ("parent_strike", "child_veil")


def test_a4_replace_empty_or_unrelated_key_equals_append() -> None:
    """replace 空映射 / 键未落在继承集 → 等价 append（逐字段一致）。"""
    jobs = _jobs()
    skills = _skills_list()
    base = inherited_skill_ids("child", jobs, skills)
    assert inherited_skill_ids("child_re", jobs, skills) == base
    assert inherited_skill_ids("child_rn", jobs, skills) == base


def test_a5_rearrange_slots_assembly_replace_vs_append() -> None:
    """装配级：replace 后母职护盾不在槽中、替代被动在；append 仍在。"""
    append_ids = _snapshot_ids("child")
    assert "parent_guard" in append_ids and "parent_strike" in append_ids
    repl_ids = _snapshot_ids("child_r")
    assert "parent_guard" not in repl_ids
    assert "child_veil" in repl_ids and "parent_strike" in repl_ids
    assert "child_burst" in repl_ids and "common_buff" in repl_ids


def test_a6_replace_only_touches_inherited_skills() -> None:
    """替换只影响继承来的技能：本职业自身技能与全局可见集不受影响。"""
    jobs = _jobs()
    skills = _skills_list()
    # child_burst 是本职业技能，不在继承集 → 替换项不生效
    assert inherited_skill_ids("child_rn", jobs, skills) == \
        inherited_skill_ids("child", jobs, skills)
    # 技能库条目本身不被改写（纯函数，无副作用）
    assert [s["id"] for s in skills] == [s["id"] for s in _SKILLS]
    assert skills[1]["job_restrict"] == ["parent"]


def test_a7_zero_behaviour_change_vs_assemble_baseline() -> None:
    """不带 inherit 的职业：rearrange 结果 == 直接 assemble_slots（现状路径）逐字段。"""
    skills = [
        {"id": "own_basic", "type": "basic", "job_restrict": ["solo"]},
        {"id": "own_act1", "type": "active", "job_restrict": ["solo"]},
        {"id": "own_pass", "type": "passive", "job_restrict": ["solo"]},
    ]
    ctx = {"skills": {s["id"]: s for s in skills},
           "jobs": {"solo": {"id": "solo", "name": "独"}}}
    got = rearrange_job_slots(ctx, "solo")
    want = assemble_slots(skills, {"job_id": "solo"})
    assert got == want


def test_a8_transitive_replace_declared_on_target() -> None:
    """传递闭包 + 目标职业 replace：可替换任意祖辈继承来的技能。"""
    jobs = {
        "a": {"id": "a"},
        "b": {"id": "b", "inherit": {"from": "a"}},
        "c": {"id": "c", "inherit": {"from": "b", "mode": "replace",
                                     "replace": {"s_a": "s_own"}}},
    }
    skills = [
        {"id": "s_a", "type": "active", "job_restrict": ["a"]},
        {"id": "s_b", "type": "passive", "job_restrict": ["b"]},
        {"id": "s_own", "type": "passive", "job_restrict": ["c"]},
    ]
    assert inherited_skill_ids("c", jobs, skills) == ("s_b", "s_own")
    # 母职 b 自身不受 c 的目标职业 replace 影响
    assert inherited_skill_ids("b", jobs, skills) == ("s_a",)


# ===========================================================================
# B. 校验
# ===========================================================================
def _errs(report: Any, needle: str) -> List[Any]:
    return [e for e in report.errors if needle in e.field]


def _warns(report: Any, needle: str) -> List[Any]:
    return [w for w in report.warnings if needle in w.field]


def test_b1_unknown_mode_yellow_not_red() -> None:
    """未知 mode → 黄提示 Y-23（不硬拦）。"""
    report = check_pack({
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "mode": "weird"}}],
    })
    assert not _errs(report, "inherit.mode"), "未知 mode 不应红拦"
    hits = _warns(report, "inherit.mode")
    assert hits and hits[0].kind == "Y-23"
    assert hits[0].detail.get("rule") == "inherit_mode_unknown"


def test_b2_replace_dangling_key_red() -> None:
    report = check_pack({
        "skills": [{"id": "s_ok", "name": "好"}],
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "mode": "replace",
                              "replace": {"ghost_src": "s_ok"}}}],
    })
    hits = [e for e in _errs(report, "inherit.replace")
            if e.kind == "R-4" and e.detail.get("role") == "key"]
    assert hits and hits[0].detail.get("ref") == "ghost_src"
    assert hits[0].detail.get("ref_target") == "skill"


def test_b3_replace_dangling_value_red() -> None:
    report = check_pack({
        "skills": [{"id": "s_ok", "name": "好"}],
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "mode": "replace",
                              "replace": {"s_ok": "ghost_dst"}}}],
    })
    hits = [e for e in _errs(report, "inherit.replace")
            if e.kind == "R-4" and e.detail.get("role") == "value"]
    assert hits and hits[0].detail.get("ref") == "ghost_dst"


def test_b4_replace_not_object_red() -> None:
    report = check_pack({
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "replace": "oops"}}],
    })
    hits = _errs(report, "inherit.replace")
    assert hits and hits[0].kind == "R-1"


def test_b5_valid_mode_replace_no_red_no_yellow() -> None:
    report = check_pack({
        "skills": [{"id": "s_a", "name": "甲"}, {"id": "s_b", "name": "乙"}],
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职",
                  "inherit": {"from": "parent", "skills": ["s_a"],
                              "mode": "replace", "replace": {"s_a": "s_b"}}}],
    })
    assert not _errs(report, "inherit")
    assert not _warns(report, "inherit"), "合法 mode/replace 不应有黄提示"


def test_b6_absent_inherit_and_append_no_new_red() -> None:
    """既有数据（不带 inherit / 只用 append）：校验零新增红黄。"""
    report = check_pack({
        "jobs": [{"id": "parent", "name": "母职"},
                 {"id": "child", "name": "进阶职"},
                 {"id": "child2", "name": "进阶职2",
                  "inherit": {"from": "parent", "mode": "append"}}],
    })
    assert not _errs(report, "inherit")
    assert not _warns(report, "inherit")


# ===========================================================================
# C. 编辑器可见
# ===========================================================================
def test_c1_two_tables_registered() -> None:
    tbl = default_field_meta_table()
    m = tbl.module("jobs")
    assert m is not None
    kids = m.fields["inherit"].children or {}
    assert set(kids) == {"from", "skills", "mode", "replace"}
    assert kids["mode"].type == "str"
    assert set(kids["mode"].enum_options) == {"append", "replace"}
    assert kids["replace"].type == "obj"
    assert m.field_subgroups.get("inherit") == "inherit"
    assert m.subgroup_labels.get("inherit") == JOBS_SUBGROUP_LABELS["inherit"]
    jm = jobs_fields()["inherit"].children
    assert set(jm) == {"from", "skills", "mode", "replace"}
    for k in ("mode", "replace"):
        assert kids[k].label and kids[k].help, f"inherit.{k} 缺中文名/说明"
        assert len(kids[k].help) <= 60, f"inherit.{k} help 超 60 字"


def _make_pack(root: Path) -> None:
    pkg = root / "pack79"
    pkg.mkdir(parents=True)
    (pkg / "manifest.json").write_text(json.dumps(
        {"name": "pack79", "version": "1", "schema_version": 1,
         "modules": ["jobs", "skills"]}, ensure_ascii=False), encoding="utf-8")
    (pkg / "jobs.json").write_text(json.dumps([
        {"id": "parent", "name": "母职"},
        {"id": "child", "name": "进阶职",
         "inherit": {"from": "parent", "mode": "replace",
                     "replace": {"s_a": "s_b"}}},
    ], ensure_ascii=False), encoding="utf-8")
    (pkg / "skills.json").write_text(json.dumps([
        {"id": "s_a", "name": "甲技"}, {"id": "s_b", "name": "乙技"},
    ], ensure_ascii=False), encoding="utf-8")


def test_c2_entry_detail_descriptor(tmp_path: Path) -> None:
    _make_pack(tmp_path)
    detail = api.entry_detail("pack79", "jobs", "child", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "inherit")
    assert f["present"] is True
    kids = {c["key"]: c for c in (f.get("children") or [])}
    assert set(kids) == {"from", "skills", "mode", "replace"}
    assert kids["mode"]["control"] == "select"
    assert kids["mode"]["enum_options"] == ["append", "replace"]
    assert kids["mode"]["label"] == "继承模式"
    assert kids["replace"]["control"] == "kvtable"
    assert kids["replace"]["label"] == "继承技能替换"
    assert kids["mode"]["help"] and kids["replace"]["help"]


def test_c3_frontend_renders_enum_options_select() -> None:
    """前端对象内 select 控件按 enum_options 渲染（DOM 机制证据；不比对整句文案）。"""
    html = (Path(api.repo_root()) / "qbot_rpg" / "web" / "static" / "index.html"
            ).read_text(encoding="utf-8")
    assert "enum_options" in html
    assert 'case "select"' in html
