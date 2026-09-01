"""M13 职业库专项校验器 V5~V8 单测（tests/unit/test_job_validator_v58.py · M13 批5 路5B）。

覆盖细化_6b 契约（任务口径 V5~V8 后半段）：
  - V5 技能挂点引用（红拦）：transform.transform_skill / skill_set →
    skills 表存在；transform_to → JOB_FORM 值域（须被 ≥1 技能 job_form
    引用）；skills 表缺失 → 宽松放行
  - V6 派生链作用域（红拦）：transform.derive_chains → skill_chains 表
    存在；链 job_scope 与 transform_to 一致性；skill_chains 表缺失 → 宽松
    放行；链缺 job_scope 键 → 通用链放行
  - V7 死配置（红拦）：技能 job_form / 链 job_scope 引用不存在的形态 →
    红拦；revert_form=true 技能不归属形态组（契约 V6 归属）→ 红拦；
    derive_only 技能 effects 引用不存在 → 红拦；revert_form 缺登记宽松
    放行（6a 未登记前不误拦）
  - V8 battle+revert 红拦（红拦）：transform.duration="battle" 且
    revert=true → 红拦（ADR D-04）；battle+false / turns+true 放行
  - 混合：V5+V6+V7+V8 同包多职业全量命中；合法 berserker 包（全表齐备）
    零红拦；report 三形态（_Checker 兼容 / dict / list）

测试目标：qbot_rpg.content.job_validator_v58.{validate_jobs_v58, MODULE_NAME,
V8_DURATION, X_PREFIX}。

测试口径（对齐 test_skill_validator.py / test_forge_models.py）：
  - validate_jobs_v58 为 (modules, report) 纯函数；report 鸭子类型
    （_Report 收集器 + dict {"errors","warnings"} 形态 + list 形态兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（本路全红拦，
    warnings 恒为空）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时
调用）；不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, Optional, Set

from qbot_rpg.content.job_validator_v58 import (
    MODULE_NAME,
    validate_jobs_v58,
)


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_jobs_v58 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _ok_job(**over: object) -> dict:
    """一条合法职业（含完整 transform 段，全部引用靶命中；契约 §1.1/§1.3）。"""
    j = {
        "id": "berserker",
        "name": "狂战士",
        "difficulty": "complex",
        "playstyle": "怒满变身",
        "recommended_newbie": False,
        "resource_axes": ["mp", "rage"],
        "growth": {"str": 2.2, "con": 1.2},
        "transform": {
            "transform_skill": "berserk",
            "transform_to": "berserker_form",
            "duration": "turns",
            "turns": 4,
            "revert": True,
            "cooldown": 5,
            "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
            "skill_set": "transform_skills",
            "derive_chains": ["chain_rage"],
        },
        "description": "狂战士形态",
    }
    j.update(over)
    return j


def _ok_skill(**over: object) -> dict:
    """形态组内合法技能（job_form 钉定形态；无挂点字段 → 无引用可查）。"""
    s = {
        "id": "berserk",
        "name": "狂暴",
        "kind": "status",
        "type": "active",
        "job_form": "berserker_form",
    }
    s.update(over)
    return s


def _skills_table() -> list:
    """skills 表：形态组技能 + 组外技能（组名即技能 ID，transform_skills 为 skill_set 引用靶）。"""
    return [
        {"id": "berserk", "name": "狂暴", "kind": "status", "type": "active",
         "job_form": "berserker_form"},
        {"id": "transform_skills", "name": "形态技能组", "kind": "utility", "type": "passive"},
        {"id": "slash", "name": "斩击", "kind": "damage", "type": "basic"},
    ]


def _chains_table() -> list:
    """skill_chains 表：形态专属链（job_scope=berserker_form）+ 通用链（无 job_scope）。"""
    return [
        {"id": "chain_rage", "name": "怒涛连段", "job_scope": "berserker_form", "power": 120},
        {"id": "chain_generic", "name": "通用链", "power": 100},
    ]


def _effects_table() -> list:
    return [{"id": "flame_burst", "name": "烈焰爆发"}]


def _modules(jobs: list, **extra: object) -> dict:
    """校验器 modules（jobs 键 + 引用靶模块缺省全配）。"""
    m: Dict[str, object] = {
        "jobs": jobs,
        "skills": _skills_table(),
        "skill_chains": _chains_table(),
        "effects": _effects_table(),
    }
    m.update(extra)
    return m


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_jobs_v58，返回收集器。"""
    report = _Report()
    validate_jobs_v58(modules, report)
    return report


def _rules(report: _Report, level: str) -> Set[str]:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


def _no_red(report: _Report) -> None:
    assert report.errors == [], f"应红拦零命中，got {report.errors}"


def _find_error(report: _Report, rule: str) -> Optional[Dict[str, object]]:
    """按 rule 名找错误记录（避免 errors[0] 索引假设——前面可能先收集其他错误）。"""
    for e in report.errors:
        if e["detail"].get("rule") == rule:
            return e
    return None


def _no_warn(report: _Report) -> None:
    assert report.warnings == [], f"本路全红拦无黄提示，got {report.warnings}"


# ---------------------------------------------------------------------------
# V5 技能挂点引用（transform_skill / skill_set / transform_to → JOB_FORM 值域）
# ---------------------------------------------------------------------------
def test_v5_legal_pack_no_red() -> None:
    """合法 berserker 包（全引用靶命中）→ 零红拦零黄提示（V5 正例）。"""
    report = _run(_modules([_ok_job()]))
    _no_red(report)
    _no_warn(report)


def test_v5_transform_skill_missing_red_blocks() -> None:
    """transform.transform_skill 引用不存在的技能 → 红拦（契约 V2 反例）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "transform_skill": "ghost_skill",
    })]))
    assert "V5_transform_skill_ref" in _rules(report, "errors"), \
        f"不存在的触发技能应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["skill_ref"] == "ghost_skill"


def test_v5_skill_set_missing_red_blocks() -> None:
    """transform.skill_set 引用不存在的技能组 → 红拦（契约 V8 反例）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "skill_set": "ghost_group",
    })]))
    assert "V5_skill_set_ref" in _rules(report, "errors"), \
        f"不存在的形态技能组应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["skill_set_ref"] == "ghost_group"


def test_v5_transform_to_unreferenced_red_blocks() -> None:
    """transform_to 形态无任何技能 job_form 引用 → 红拦（契约 V1 死形态反例）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "transform_to": "ghost_form",
    })]))
    assert "V5_form_unreferenced" in _rules(report, "errors"), \
        f"无 job_form 引用的死形态应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["transform_to"] == "ghost_form"


def test_v5_skills_table_missing_pass() -> None:
    """skills 表缺失 → 引用红拦全部宽松放行（P-2 缺表先例，对齐 V-5/P-1）。"""
    report = _run(_modules([_ok_job()], skills=None))
    _no_red(report)
    assert "V5_transform_skill_ref" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V6 派生链作用域（derive_chains 引用存在 + job_scope 一致性）
# ---------------------------------------------------------------------------
def test_v6_chain_ref_missing_red_blocks() -> None:
    """transform.derive_chains 引用不存在的链 → 红拦（契约 V8 反例）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "derive_chains": ["ghost_chain"],
    })]))
    assert "V6_chain_ref" in _rules(report, "errors"), \
        f"不存在的派生链应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["chain_ref"] == "ghost_chain"


def test_v6_chain_scope_mismatch_red_blocks() -> None:
    """链 job_scope 与本职业 transform_to 不一致 → 红拦（§2.3 ③ V8 反例）。"""
    report = _run(_modules([_ok_job()], skill_chains=[
        {"id": "chain_rage", "name": "怒涛连段", "job_scope": "other_form", "power": 120},
    ]))
    assert "V6_chain_scope" in _rules(report, "errors"), \
        f"链 job_scope 不一致应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["job_scope"] == "other_form"


def test_v6_chain_no_scope_pass() -> None:
    """链缺 job_scope 键（无形态作用域限制）→ 放行（P-3 通用链）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "derive_chains": ["chain_generic"],
    })]))
    _no_red(report)
    assert "V6_chain_scope" not in _rules(report, "errors")


def test_v6_chains_table_missing_pass() -> None:
    """skill_chains 表缺失 → derive_chains 引用红拦宽松放行（P-2）。"""
    report = _run(_modules([_ok_job()], skill_chains=None))
    _no_red(report)
    assert "V6_chain_ref" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V7 死配置（挂点引用不存在的形态 / revert_form 归属 / derive_only 效果引用）
# ---------------------------------------------------------------------------
def test_v7_job_form_unregistered_red_blocks() -> None:
    """技能 job_form 引用不存在的形态 → 红拦（V7 死配置反例）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "berserk", "name": "狂暴", "job_form": "ghost_form"},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    assert "V7_job_form_ref" in _rules(report, "errors"), \
        f"job_form 死引用应红拦，got {report.errors}"
    err = _find_error(report, "V7_job_form_ref")
    assert err is not None and err["detail"]["job_form"] == "ghost_form"


def test_v7_job_scope_unregistered_red_blocks() -> None:
    """链 job_scope 引用不存在的形态 → 红拦（V7 死配置反例）。"""
    report = _run(_modules([_ok_job()], skill_chains=[
        {"id": "chain_rage", "name": "怒涛连段", "job_scope": "ghost_form", "power": 120},
    ]))
    assert "V7_job_scope_ref" in _rules(report, "errors"), \
        f"链 job_scope 死引用应红拦，got {report.errors}"
    err = _find_error(report, "V7_job_scope_ref")
    assert err is not None and err["detail"]["job_scope"] == "ghost_form"


def test_v7_revert_form_skill_not_in_form_scope_red_blocks() -> None:
    """revert_form=true 技能 job_form 缺失（不归属形态组）→ 红拦（契约 V6 归属反例）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "calm", "name": "平息战意", "revert_form": True},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    assert "V7_revert_form_scope" in _rules(report, "errors"), \
        f"revert_form 不归属形态组应红拦，got {report.errors}"
    err = _find_error(report, "V7_revert_form_scope")
    assert err is not None and err["detail"]["job_form"] is None


def test_v7_revert_form_skill_in_form_scope_pass() -> None:
    """revert_form=true 且 job_form 归属形态值域 → 放行（契约 V6 正例）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "berserk", "name": "狂暴", "kind": "status", "type": "active",
         "job_form": "berserker_form"},
        {"id": "transform_skills", "name": "形态技能组", "kind": "utility", "type": "passive"},
        {"id": "calm", "name": "平息战意", "revert_form": True,
         "job_form": "berserker_form"},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    _no_red(report)
    assert "V7_revert_form_scope" not in _rules(report, "errors")


def test_v7_derive_only_effect_ref_missing_red_blocks() -> None:
    """derive_only 技能 effects 引用不存在的效果 → 红拦（V7 死配置反例，P-5）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "spin_end", "name": "大回旋·终", "derive_only": True,
         "effects": [{"effect": "ghost_blast"}]},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    assert "V7_effect_ref" in _rules(report, "errors"), \
        f"derive_only 效果死引用应红拦，got {report.errors}"
    err = _find_error(report, "V7_effect_ref")
    assert err is not None and err["detail"]["effect_ref"] == "ghost_blast"


def test_v7_derive_only_effect_x_prefix_pass() -> None:
    """derive_only 技能 effects x_ 前缀自定义效果 → 放行（对齐 V-1 [L131]）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "berserk", "name": "狂暴", "kind": "status", "type": "active",
         "job_form": "berserker_form"},
        {"id": "transform_skills", "name": "形态技能组", "kind": "utility", "type": "passive"},
        {"id": "spin_end", "name": "大回旋·终", "derive_only": True,
         "effects": [{"effect": "x_custom_burst"}]},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    _no_red(report)
    assert "V7_effect_ref" not in _rules(report, "errors")


def test_v7_hook_fields_absent_no_false_positive() -> None:
    """技能无挂点字段（无 job_form/revert_form/derive_only）→ 零红拦（P-1 缺登记宽松）。"""
    report = _run(_modules([_ok_job()], skills=[
        {"id": "berserk", "name": "狂暴", "kind": "status", "type": "active",
         "job_form": "berserker_form"},
        {"id": "transform_skills", "name": "形态技能组", "kind": "utility", "type": "passive"},
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]))
    _no_red(report)
    assert _rules(report, "errors") == set()


# ---------------------------------------------------------------------------
# V8 battle+revert 红拦（ADR D-04）
# ---------------------------------------------------------------------------
def test_v8_battle_revert_conflict_red_blocks() -> None:
    """duration=battle 且 revert=true → 红拦（契约 V4 / ADR D-04 反例）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "duration": "battle", "revert": True,
    })]))
    assert "V8_battle_revert_conflict" in _rules(report, "errors"), \
        f"battle+revert 矛盾应红拦，got {report.errors}"
    err = _find_error(report, "V8_battle_revert_conflict")
    assert err is not None and err["detail"]["duration"] == "battle"


def test_v8_battle_no_revert_pass() -> None:
    """duration=battle 且 revert=false → 放行（整场不还原合法）。"""
    report = _run(_modules([_ok_job(transform={
        **_ok_job()["transform"], "duration": "battle", "revert": False,
    })]))
    _no_red(report)
    assert "V8_battle_revert_conflict" not in _rules(report, "errors")


def test_v8_turns_revert_true_pass() -> None:
    """duration=turns 且 revert=true → 放行（回合制持续+结束后还原合法）。"""
    report = _run(_modules([_ok_job()]))
    _no_red(report)
    assert "V8_battle_revert_conflict" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# 混合 / 三形态收集器
# ---------------------------------------------------------------------------
def test_mixed_multi_job_all_rules_hit() -> None:
    """同包多职业混合坏包：V5+V6+V7+V8 全量命中（TC-18 坏包稳定拦截，防空转）。"""
    jobs = [
        _ok_job(transform={**_ok_job()["transform"],
                           "transform_skill": "ghost_skill",   # V5
                           "skill_set": "ghost_group",          # V5
                           "derive_chains": ["ghost_chain"],    # V6
                           "duration": "battle", "revert": True}),  # V8
        _ok_job(id="mage", transform={**_ok_job()["transform"],
                                      "transform_to": "mage_form"}),  # V5 死形态
    ]
    skills = [
        {"id": "calm", "name": "平息战意", "revert_form": True},      # V7 归属
        {"id": "spin_end", "name": "大回旋·终", "derive_only": True,
         "effects": [{"effect": "ghost_blast"}]},                     # V7 效果
        {"id": "slash", "name": "斩击", "type": "basic"},
    ]
    chains = [
        {"id": "chain_rage", "name": "怒涛连段", "job_scope": "ghost_form"},  # V7 链形态
        {"id": "chain_other", "name": "异形链", "job_scope": "other_form"},   # V7 链形态
    ]
    report = _run(_modules(jobs, skills=skills, skill_chains=chains))
    rules = _rules(report, "errors")
    assert {
        "V5_transform_skill_ref", "V5_skill_set_ref", "V5_form_unreferenced",
        "V6_chain_ref", "V7_revert_form_scope", "V7_effect_ref",
        "V7_job_scope_ref", "V8_battle_revert_conflict",
    } <= rules, f"混合坏包应全量红拦，got {sorted(rules)}"
    assert report.warnings == [], f"本路全红拦无黄提示，got {report.warnings}"


def test_report_dict_form() -> None:
    """dict 形态收集器（{"errors":[],"warnings":[]}）兼容。"""
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_jobs_v58(_modules([_ok_job(transform={
        **_ok_job()["transform"], "duration": "battle", "revert": True,
    })]), report)
    assert len(report["errors"]) == 1
    assert report["errors"][0]["kind"] == "V8"
    assert report["errors"][0]["field"].startswith("[0]")
    assert report["warnings"] == []


def test_report_list_form() -> None:
    """list 形态收集器（rec 直接 append）兼容。"""
    report: list = []
    validate_jobs_v58(_modules([_ok_job(transform={
        **_ok_job()["transform"], "duration": "battle", "revert": True,
    })]), report)
    assert len(report) == 1
    assert report[0]["level"] == "error"
    assert report[0]["kind"] == "V8"


def _report_checker() -> object:
    """构造一个 _Checker 形态收集器（_err/_warn 三形态之一）。

    经 qbot_rpg.content.validator 模块取私有 _Checker（不直接 import 符号，
    避免触发 validator 模块顶层初始化依赖），构造后返回实例（meta 缺省用
    default_field_meta_table，与 check_pack 同口径；本测试不跑 run()，
    仅收集 _err/_warn 记录）。
    """
    import qbot_rpg.content.validator as _validator_mod

    return _validator_mod._Checker(modules={}, meta=_validator_mod.default_field_meta_table())


def test_report_checker_form() -> None:
    """_Checker._err/_warn 形态收集器（module 恒为 "jobs"）兼容。"""
    checker = _report_checker()
    validate_jobs_v58(_modules([_ok_job(transform={
        **_ok_job()["transform"], "duration": "battle", "revert": True,
    })]), checker)
    assert len(checker.errors) == 1
    assert checker.errors[0].module == MODULE_NAME
    assert checker.errors[0].kind == "V8"


def test_jobs_missing_module_skipped() -> None:
    """modules 无 jobs 键 → 跳过（对齐既有校验器「模块未接线默认放行」惯例）。"""
    report = _run({"skills": _skills_table()})
    _no_red(report)


def test_jobs_not_list_red_blocks() -> None:
    """jobs 键非顶层数组 → 红拦（结构形态，契约 §1.1）。"""
    report = _run({"jobs": {"id": "warrior"}})
    assert "job_not_list" in _rules(report, "errors"), \
        f"jobs 非数组应红拦，got {report.errors}"


def test_job_entry_not_object_red_blocks() -> None:
    """jobs 条目非对象 → 红拦（结构形态）。"""
    report = _run(_modules(["not_a_job"]))
    assert "job_not_object" in _rules(report, "errors"), \
        f"职业条目非对象应红拦，got {report.errors}"


def test_no_transform_legit_job_no_red() -> None:
    """无 transform 段的普通职业 → 零红拦（§1.1 #10 缺省=无形态切换职业）。

    用无形态技能的表（无 job_form 引用 → 无死配置红拦）。
    """
    report = _run(_modules([{
        "id": "warrior", "name": "战士", "difficulty": "simple",
        "playstyle": "近战", "recommended_newbie": True,
        "resource_axes": ["mp"], "growth": {"str": 2.0},
    }], skills=[{"id": "slash", "name": "斩击", "type": "basic"}],
        skill_chains=[{"id": "chain_generic", "name": "通用链", "power": 100}]))
    _no_red(report)
