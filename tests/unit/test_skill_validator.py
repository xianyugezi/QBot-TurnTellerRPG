"""6a 技能库专项校验器单测（tests/unit/test_skill_validator.py · M13 批2 路2A）。

覆盖细化_6a 契约：
  - §3.1 V-1 效果引用存在（红拦）/ V-2 派生链引用存在（红拦）/ V-3 印记引用
    与消耗值域（红拦）/ V-4 元素 ∈ 8 元素注册表（红拦）/ V-5 职业引用存在
    （红拦，jobs 缺表宽松放行）/ V-6 派生倍率累计 >1.5×（黄提示不拦截）
  - ⑥ TC-11（V-6 1.8× 黄提示）/ TC-14（V-1 红拦）/ TC-15（V-2 红拦）/
    TC-16（V-3 红拦）/ TC-17（V-5 红拦）

测试目标：qbot_rpg.content.skill_validator.{validate_skills, ELEMENT_VALUES,
V6_RATIO_LIMIT, X_PREFIX}。

测试口径（对齐 test_skill_action_models.py / test_fishing_models.py）：
  - validate_skills 为 (modules, report) 纯函数；report 鸭子类型（_Report
    收集器 + dict {"errors","warnings"} 形态 + 真实 validator._Checker 收口
    兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, Set

from qbot_rpg.content.skill_validator import (
    ELEMENT_VALUES,
    V6_RATIO_LIMIT,
    validate_skills,
)
from qbot_rpg.content.skill_models import SKILL_ELEMENTS


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_skills 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _ok_skill(**over: object) -> dict:
    """一条合法技能（契约 §1.2 最小形态 + 全引用靶命中）。"""
    s = {
        "id": "flame_strike",
        "name": "烈焰斩",
        "kind": "damage",
        "power": 100,
        "attack_type": "slash",
        "element": "fire",
        "effects": [{"effect": "flame_burst", "overrides": {"power": 50}}],
        "type": "active",
        "mp_cost": 10,
        "cooldown": 1,
        "chain_refs": ["flame_combo"],
        "consume_marks": {"fire_mark": 1},
        "job_restrict": ["warrior"],
    }
    s.update(over)
    return s


def _effects_table() -> list:
    return [{"id": "flame_burst", "name": "烈焰爆发"}, {"id": "heal_light", "name": "治疗术"}]


def _chains_table() -> list:
    return [
        {"id": "flame_combo", "power": 120},
        {"id": "flame_mastery", "power": 150, "chain_refs": ["flame_combo"]},
    ]


def _marks_table() -> list:
    return [{"id": "fire_mark", "name": "火印", "max": 5}]


def _jobs_table() -> list:
    return [{"id": "warrior", "name": "战士"}, {"id": "mage", "name": "法师"}]


def _modules(skills: list, **extra: object) -> dict:
    """校验器 modules（skills 键 + 引用靶模块缺省全配）。

    V-7 要求 basic 每职业恰 1：注入一条全局 basic（无 job_restrict → 计入所有职业）。
    """
    m: Dict[str, object] = {
        "skills": skills + [
            {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
             "power": 100, "effects": [{"effect": "flame_burst"}]},
        ],
        "effects": _effects_table(),
        "skill_chains": _chains_table(),
        "marks": _marks_table(),
        "jobs": _jobs_table(),
    }
    m.update(extra)
    return m


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_skills，返回收集器。"""
    report = _Report()
    validate_skills(modules, report)
    return report


def _rules(report: _Report, level: str) -> Set[str]:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


def _no_red(report: _Report) -> None:
    assert report.errors == [], f"应红拦零命中，got {report.errors}"


# ---------------------------------------------------------------------------
# V-1 效果引用存在（TC-14）
# ---------------------------------------------------------------------------
def test_v1_effect_ref_exists() -> None:
    """effects[].effect ∈ effects 表 → 通过（V-1 正例）。"""
    report = _run(_modules([_ok_skill()]))
    _no_red(report)
    assert "V1_effect_ref" not in _rules(report, "errors")


def test_v1_effect_ref_missing_hard_block() -> None:
    """effects 引用不存在的效果 ID → 红拦（TC-14 / V-1 反例）。"""
    report = _run(_modules([_ok_skill(effects=[{"effect": "ghost_blast"}])]))
    assert "V1_effect_ref" in _rules(report, "errors"), \
        f"不存在的效果引用应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["effect_ref"] == "ghost_blast"


def test_v1_atomic_action_and_x_prefix_pass() -> None:
    """type 原子动作（L0 词汇表）与 x_ 前缀自定义效果 → 放行（契约 [L131]）。"""
    effects = [
        {"type": "mark_add", "target": "self", "mark": "fire_mark", "count": 1},
        {"effect": "x_custom_burst"},
    ]
    report = _run(_modules([_ok_skill(effects=effects)]))
    _no_red(report)
    assert "V1_effect_ref" not in _rules(report, "errors")


def test_v1_effects_table_missing_hard_block() -> None:
    """effects 表缺失 → 引用按不存在红拦（_check_action_ref 先例）。"""
    report = _run(_modules([_ok_skill()], effects=None))
    assert "V1_effect_ref" in _rules(report, "errors"), \
        f"effects 表缺失应红拦引用，got {report.errors}"


# ---------------------------------------------------------------------------
# V-2 派生链引用存在（TC-15 红拦部分）
# ---------------------------------------------------------------------------
def test_v2_chain_ref_exists() -> None:
    """chain_refs ∈ skill_chains 表 → 通过（V-2 正例）。"""
    report = _run(_modules([_ok_skill()]))
    _no_red(report)
    assert "V2_chain_ref" not in _rules(report, "errors")


def test_v2_chain_ref_missing_hard_block() -> None:
    """chain_refs 指向不存在的链 → 红拦（TC-15 红拦部分 / V-2 反例）。"""
    report = _run(_modules([_ok_skill(chain_refs=["ghost_chain"])]))
    assert "V2_chain_ref" in _rules(report, "errors"), \
        f"不存在的派生链引用应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["chain_ref"] == "ghost_chain"


def test_v2_chain_refs_table_missing_hard_block() -> None:
    """skill_chains 表缺失 → 引用按不存在红拦。"""
    report = _run(_modules([_ok_skill()], skill_chains=None))
    assert "V2_chain_ref" in _rules(report, "errors"), \
        f"skill_chains 表缺失应红拦引用，got {report.errors}"


# ---------------------------------------------------------------------------
# V-3 印记引用存在 + 消耗值域（TC-16）
# ---------------------------------------------------------------------------
def test_v3_mark_ref_exists() -> None:
    """consume_marks 键 ∈ marks 表 → 通过（V-3 正例）。"""
    report = _run(_modules([_ok_skill()]))
    _no_red(report)
    assert "V3_mark_ref" not in _rules(report, "errors")
    assert "V3_mark_count" not in _rules(report, "errors")


def test_v3_mark_ref_missing_hard_block() -> None:
    """consume_marks 键不在 marks 表 → 红拦（TC-16 / V-3 反例）。"""
    report = _run(_modules([_ok_skill(consume_marks={"ghost_mark": 1})]))
    assert "V3_mark_ref" in _rules(report, "errors"), \
        f"不存在的印记引用应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["mark_ref"] == "ghost_mark"


def test_v3_mark_count_over_cap_hard_block() -> None:
    """印记消耗值超上限 → 红拦（TC-16 值超上限 / V-3 反例）。"""
    report = _run(_modules([_ok_skill(consume_marks={"fire_mark": 9})]))
    assert "V3_mark_count" in _rules(report, "errors"), \
        f"消耗超上限应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["mark_max"] == 5.0


def test_v3_mark_count_zero_hard_block() -> None:
    """印记消耗 0/负值 → 红拦（V-3 值域 ≥1）。"""
    for bad in (0, -1):
        report = _run(_modules([_ok_skill(consume_marks={"fire_mark": bad})]))
        assert "V3_mark_count" in _rules(report, "errors"), \
            f"消耗 {bad} 应红拦，got {report.errors}"


# ---------------------------------------------------------------------------
# V-4 元素 ∈ 8 元素注册表（TC-10 技能侧）
# ---------------------------------------------------------------------------
def test_v4_element_registry() -> None:
    """element 注册表内通过；注册表外红拦（V-4 正反例）。"""
    for el in ELEMENT_VALUES:
        report = _run(_modules([_ok_skill(element=el)]))
        assert "V4_element" not in _rules(report, "errors"), \
            f"element={el} 应通过，got {report.errors}"
    bad = _run(_modules([_ok_skill(element="ice")]))
    assert "V4_element" in _rules(bad, "errors"), \
        f"未注册元素应红拦，got {bad.errors}"
    assert bad.errors[0]["detail"]["element"] == "ice"


def test_v4_element_null_allowed() -> None:
    """element null/缺省 → 通过（F06 默认 null=按武器元素）。"""
    report = _run(_modules([_ok_skill(element=None)]))
    _no_red(report)


def test_v4_element_registry_constant_sync() -> None:
    """ELEMENT_VALUES 与 skill_models.SKILL_ELEMENTS 同源（8 元素注册表单点）。"""
    assert ELEMENT_VALUES == SKILL_ELEMENTS
    assert set(ELEMENT_VALUES) == {
        "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
    }


# ---------------------------------------------------------------------------
# V-5 职业引用存在（TC-17）
# ---------------------------------------------------------------------------
def test_v5_job_restrict_exists() -> None:
    """job_restrict ∈ jobs 表 → 通过（V-5 正例）。"""
    report = _run(_modules([_ok_skill()]))
    _no_red(report)
    assert "V5_job_ref" not in _rules(report, "errors")


def test_v5_job_restrict_missing_hard_block() -> None:
    """job_restrict 引用不存在的职业 → 红拦（TC-17 / V-5 反例）。"""
    report = _run(_modules([_ok_skill(job_restrict=["ghost_job"])]))
    assert "V5_job_ref" in _rules(report, "errors"), \
        f"不存在的职业引用应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["job_ref"] == "ghost_job"


def test_v5_jobs_table_missing_loose_pass() -> None:
    """jobs 表缺失 → 宽松放行（工程补白 P-1：jobs 模块批4 才落）。"""
    report = _run(_modules([_ok_skill()], jobs=None))
    _no_red(report)
    assert "V5_job_ref" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V-6 派生倍率累计（TC-11）
# ---------------------------------------------------------------------------
def test_v6_ratio_within_limit() -> None:
    """派生累计 ≤1.5× → 无黄提示（V-6 正例：100×1.2=1.2×）。"""
    report = _run(_modules([_ok_skill()]))
    assert "V6_ratio_high" not in _rules(report, "warnings"), \
        f"1.2× 不应触发黄提示，got {report.warnings}"


def test_v6_ratio_over_limit_warning() -> None:
    """派生累计 >1.5× → 黄提示不拦截（TC-11：200×1.2=2.4×）。"""
    report = _run(_modules([_ok_skill(power=200)]))
    assert report.errors == [], f"V-6 黄提示不应红拦，got {report.errors}"
    assert "V6_ratio_high" in _rules(report, "warnings"), \
        f"2.4× 应发黄提示，got {report.warnings}"
    assert report.warnings[0]["detail"]["cumulative"] > V6_RATIO_LIMIT


def test_v6_ratio_nested_chain_accumulate() -> None:
    """多级链累计（150×1.2=1.8×）→ 黄提示（TC-11 1.8× 口径）。"""
    report = _run(_modules([_ok_skill(chain_refs=["flame_mastery"])]))
    assert report.errors == [], f"V-6 黄提示不应红拦，got {report.errors}"
    assert "V6_ratio_high" in _rules(report, "warnings"), \
        f"1.8× 应发黄提示，got {report.warnings}"
    assert abs(report.warnings[0]["detail"]["cumulative"] - 1.8) < 1e-6


def test_v6_ratio_cycle_safe() -> None:
    """链成环（A→B→A）→ 不炸、累计有限（visited 防环）。"""
    chains = [
        {"id": "loop_a", "power": 200, "chain_refs": ["loop_b"]},
        {"id": "loop_b", "power": 200, "chain_refs": ["loop_a"]},
    ]
    report = _run(_modules([_ok_skill(chain_refs=["loop_a"])], skill_chains=chains))
    assert report.errors == []
    assert "V6_ratio_high" in _rules(report, "warnings"), \
        f"成环链累计应发黄提示（2.0×2.0=4.0×），got {report.warnings}"


# ---------------------------------------------------------------------------
# 混合 / 收集器形态 / 登记一致性
# ---------------------------------------------------------------------------
def test_mixed_all_six_rules() -> None:
    """V-1~V-6 同时命中：红拦 5 类 + 黄提示 1 类互不干扰。"""
    skills = [
        _ok_skill(
            effects=[{"effect": "ghost_blast"}],        # V-1 红
            chain_refs=["ghost_chain"],                 # V-2 红
            consume_marks={"ghost_mark": 1},            # V-3 红
            element="ice",                              # V-4 红
            job_restrict=["ghost_job"],                 # V-5 红
            power=300,                                  # V-6 黄（3.0×1.2=3.6×）
        )
    ]
    report = _run(_modules(skills))
    rules_err = _rules(report, "errors")
    for rule in ("V1_effect_ref", "V2_chain_ref", "V3_mark_ref", "V4_element", "V5_job_ref"):
        assert rule in rules_err, f"{rule} 应红拦，got {report.errors}"
    assert "V6_ratio_high" in _rules(report, "warnings"), \
        f"V-6 应黄提示，got {report.warnings}"
    assert report.errors and report.warnings


def test_legal_skill_zero_red() -> None:
    """全引用命中 + 全字段合法技能 → 红拦零命中（三铁律② 兜底）。"""
    report = _run(_modules([_ok_skill()]))
    _no_red(report)


def test_skills_module_missing_skipped() -> None:
    """skills 模块缺失 → 跳过不报错（对齐既有校验器「模块未接线默认放行」惯例）。"""
    report = _run({})
    assert report.errors == [] and report.warnings == []


def test_skills_not_list_structure_error() -> None:
    """skills 顶层非数组 → 红拦（契约 §1.1 文件形态数组）。"""
    report = _run({"skills": {"id": "solo"}, "effects": _effects_table()})
    assert "skill_not_list" in _rules(report, "errors"), \
        f"skills 非数组应红拦，got {report.errors}"


def test_report_dict_form() -> None:
    """收集器 dict 形态：{\"errors\":[],\"warnings\":[]}（_emit 兜底）。"""
    modules = _modules([_ok_skill(effects=[{"effect": "ghost_blast"}])])
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_skills(modules, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["rule"] == "V1_effect_ref"


def test_report_checker_form() -> None:
    """真实 validator._Checker 收口兼容（_err/_warn 回落）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.validator import _Checker

    checker = _Checker(_modules([_ok_skill(effects=[{"effect": "ghost_blast"}])]),
                       default_field_meta_table())
    validate_skills(_modules([_ok_skill(effects=[{"effect": "ghost_blast"}])]), checker)
    assert any("V1_effect_ref" in str(e.detail) for e in checker.errors), \
        "_Checker 应收集 V-1 红拦"
    assert all(e.module == "skills" for e in checker.errors), \
        "收集记录 module 应为 skills"
