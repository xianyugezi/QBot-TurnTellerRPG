"""6b 职业库专项校验器单测（tests/unit/test_job_validator.py · M13 批5 路5A）。

覆盖细化_6b 契约（§五 V1~V4 红拦 + ⑥ TC-18 坏包断言 ①~⑤ 与 ⑨ 修复后重载）：
  - V1 字段结构（红拦）：jobs 条目顶层字段 ∈ jobs_fields 34 键（含 transform
    段 11 子键 + state_policy 3 子键）；缺 id/name 红拦；transform 非对象/
    未知子键红拦；growth 未知子键黄提示不拦截
  - V2 成长率合法（红拦）：growth 九键数值 ∈ [0, 合理上限]（hp/mp ≤1000、
    其余七键 ≤100）；非数值/负值/超上限红拦；缺省/缺 growth 合法
  - V3 资源轴引用（红拦）：resource_axes 每个值 ∈ stats.json 注册段
    （map 形态查键 / list 形态查条目 id）；stats 缺表宽松放行（6c 批8 才落）；
    引用缺失/非 list/非字符串红拦
  - V4 transform 段合法（红拦）：七必填键缺失红拦；duration 枚举外值红拦；
    duration=battle + revert=true 矛盾红拦（D-04 仲裁）；turns 条件必填
    （duration=turns 时缺失/≤0 红拦）；cooldown 负值红拦；state_policy
    非对象/三键枚举外值红拦（V5 判定基底先行收口）
  - ⑥ TC-18：① transform_to 不存在 → V1 红拦（V1 判定基底：transform_to
    未登记）② transform_skill 非本职业技能 → V2 红拦（归属校验归路5B）
    ③ transform_to 自指/双职业互指环 → V3 红拦（形态环归路5B）
    ④ battle+revert=true → V4 红拦 ⑤ state_policy.combo="shuffle" → V5 红拦
    （枚举判定本文件 V4 段先行收口，rule 名对齐路5B）⑨ 修复后重载通过

测试目标：qbot_rpg.content.job_validator.{validate_jobs, GROWTH_LIMITS,
TRANSFORM_REQUIRED_KEYS}。

测试口径（对齐 test_skill_validator.py）：
  - validate_jobs 为 (modules, report) 纯函数；report 鸭子类型（_Report
    收集器 + dict {"errors","warnings"} 形态 + 真实 validator._Checker 收口
    兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。
  - 合法夹具只含契约登记键（34 键空间内），引用靶全配。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Dict, Mapping, Set

from qbot_rpg.content.job_models import GROWTH_KEYS, STATE_POLICY_VALUES
from qbot_rpg.content.job_validator import (
    GROWTH_LIMITS,
    TRANSFORM_REQUIRED_KEYS,
    validate_jobs,
)


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_jobs 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _ok_transform(**over: object) -> dict:
    """一条合法 transform 段（细化_6b §1.3 狂战士完整段 L281-297 形态；全键齐）。"""
    t = {
        "transform_skill": "berserk",
        "transform_to": "berserker_form",
        "duration": "turns",
        "turns": 4,
        "revert": True,
        "cooldown": 5,
        "dispel_reverts": True,
        "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
        "skill_set": "transform_skills",
        "equip_restrict": [],
        "derive_chains": [],
    }
    t.update(over)
    return t


def _ok_job(**over: object) -> dict:
    """一条合法职业（细化_6b §1.1 顶层 11 键 + growth 九键 + transform 段全配）。"""
    j = {
        "id": "berserker",
        "name": "狂战士",
        "difficulty": "complex",
        "playstyle": "以操作换生存",
        "recommended_newbie": False,
        "resource_axes": ["mp", "rage"],
        "mechanic_tags": ["transform"],
        "weapon_types": ["great_sword"],
        "growth": {
            "str": 2.2, "int": 0.5, "con": 1.5, "spr": 0.5, "foc": 1.0,
            "agi": 1.0, "lck": 0.5, "hp": 1.5, "mp": 1.0,
        },
        "transform": _ok_transform(),
        "description": "怒满变身的狂战士",
    }
    j.update(over)
    return j


def _stats_map() -> dict:
    """stats.json map 形态（field_meta entry_type="map"，键 = 属性 ID，细化_3b §4.1）。"""
    return {"hp": {}, "mp": {}, "str": {}, "rage": {}, "combo": {}, "mark": {}}


def _stats_list() -> list:
    """stats.json list 形态（内容包手写统计侧，条目 id 键空间）。"""
    return [{"id": "hp"}, {"id": "mp"}, {"id": "rage"}]


def _modules(jobs: list, stats: object = None) -> dict:
    """校验器 modules（jobs 键 + stats 引用靶；缺省全配 map 形态）。"""
    m: Dict[str, object] = {"jobs": jobs}
    if stats is not None:
        m["stats"] = stats
    else:
        m["stats"] = _stats_map()
    return m


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_jobs，返回收集器。"""
    report = _Report()
    validate_jobs(modules, report)
    return report


def _rules(report: _Report, level: str) -> Set[str]:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


def _no_red(report: _Report) -> None:
    assert report.errors == [], f"应红拦零命中，got {report.errors}"


# ---------------------------------------------------------------------------
# V1 字段结构（红拦）
# ---------------------------------------------------------------------------
def test_v1_legal_job_zero_red() -> None:
    """全 34 键空间内合法职业 → 红拦零命中（V1 正例 + 三铁律②）。"""
    report = _run(_modules([_ok_job()]))
    _no_red(report)
    assert "V1_top_field_unregistered" not in _rules(report, "errors")
    assert "V1_required_missing" not in _rules(report, "errors")


def test_v1_unknown_top_field_hard_block() -> None:
    """顶层未登记字段 → 红拦（V1 反例：字段须在 jobs_fields 34 键内）。"""
    report = _run(_modules([_ok_job(burst_gauge=100)]))
    assert "V1_top_field_unregistered" in _rules(report, "errors"), \
        f"顶层未登记字段应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["field_name"] == "burst_gauge"


def test_v1_missing_id_name_hard_block() -> None:
    """缺 id / 缺 name → 各红拦一条（V1 反例：§1.1 #1/#2 必填，name 不兜底）。"""
    report = _run(_modules([_ok_job(id=None, name=None)]))
    assert "V1_required_missing" in _rules(report, "errors"), \
        f"缺必填字段应红拦，got {report.errors}"
    missing = {e["detail"]["field_name"] for e in report.errors
               if e["detail"].get("rule") == "V1_required_missing"}
    assert missing == {"id", "name"}, f"缺 id/name 应各红拦一条，got {missing}"


def test_v1_transform_not_object_hard_block() -> None:
    """transform 存在但非对象 → 红拦（V1 反例：§1.1 #10 形态为对象）。"""
    report = _run(_modules([_ok_job(transform="berserk_mode")]))
    assert "V1_transform_not_object" in _rules(report, "errors"), \
        f"transform 非对象应红拦，got {report.errors}"


def test_v1_transform_unknown_subfield_hard_block() -> None:
    """transform 段未登记子键 → 红拦（V1 反例：须在 transform_fields 11 键内）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(extra_mode=True))]))
    assert "V1_transform_field_unregistered" in _rules(report, "errors"), \
        f"transform 段未登记子键应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["field_name"] == "extra_mode"


def test_v1_growth_unknown_key_warning_only() -> None:
    """growth 内未知子键 → 黄提示不拦截（V1 软标注口径，消费侧忽略）。"""
    report = _run(_modules([_ok_job(growth={"str": 2.0, "luck": 9.9})]))
    assert report.errors == [], f"growth 未知键不应红拦，got {report.errors}"
    assert "V1_growth_unregistered_key" in _rules(report, "warnings"), \
        f"growth 未知键应黄提示，got {report.warnings}"


def test_v1_jobs_not_list_hard_block() -> None:
    """jobs 顶层非数组 → 红拦（细化_6b §1 文件形态数组）。"""
    report = _run({"jobs": {"id": "solo"}, "stats": _stats_map()})
    assert "V1_jobs_not_list" in _rules(report, "errors"), \
        f"jobs 非数组应红拦，got {report.errors}"


def test_v1_jobs_module_missing_skipped() -> None:
    """jobs 模块缺失 → 跳过不报错（对齐既有校验器「模块未接线默认放行」惯例）。"""
    report = _run({})
    assert report.errors == [] and report.warnings == []


# ---------------------------------------------------------------------------
# V2 成长率合法（红拦）
# ---------------------------------------------------------------------------
def test_v2_growth_legal_bounds() -> None:
    """成长率边界值（0 与上限）→ 通过；缺 growth / 缺子键 → 通过（V2 正例）。"""
    report = _run(_modules([_ok_job(growth={"hp": 0, "mp": 1000, "str": 100, "agi": 0})]))
    _no_red(report)
    report2 = _run(_modules([_ok_job(growth=None)]))
    _no_red(report2)
    report3 = _run(_modules([_ok_job(growth={"str": 2.0})]))
    _no_red(report3)


def test_v2_growth_not_number_hard_block() -> None:
    """成长率非数值（字符串/bool）→ 红拦（V2 反例：须纯数值）。"""
    for bad in ("2.0", True):
        report = _run(_modules([_ok_job(growth={"str": bad})]))
        assert "V2_growth_not_number" in _rules(report, "errors"), \
            f"成长率 {bad!r} 应红拦，got {report.errors}"


def test_v2_growth_negative_hard_block() -> None:
    """成长率负值 → 红拦（V2 反例：∈ [0, 上限]）。"""
    report = _run(_modules([_ok_job(growth={"str": -0.5})]))
    assert "V2_growth_negative" in _rules(report, "errors"), \
        f"负成长率应红拦，got {report.errors}"


def test_v2_growth_out_of_range_hard_block() -> None:
    """成长率超上限 → 红拦（hp/mp ≤1000、其余七键 ≤100，V2 反例）。"""
    report = _run(_modules([_ok_job(growth={"hp": 2000, "str": 500})]))
    assert "V2_growth_out_of_range" in _rules(report, "errors"), \
        f"超上限成长率应红拦，got {report.errors}"
    over = [e for e in report.errors if e["detail"].get("rule") == "V2_growth_out_of_range"]
    assert {e["detail"]["growth_key"] for e in over} == {"hp", "str"}, \
        f"hp 与 str 超上限应各红拦一条，got {over}"
    by_key = {e["detail"]["growth_key"]: e["detail"]["limit"] for e in over}
    assert by_key["hp"] == GROWTH_LIMITS["hp"][1] == 1000.0
    assert by_key["str"] == GROWTH_LIMITS["str"][1] == 100.0
    assert len(over) == 2


def test_v2_growth_limits_constant_contract() -> None:
    """GROWTH_LIMITS 与契约九键对齐（hp/mp ≤1000、其余 ≤100，任务规格字面）。"""
    assert set(GROWTH_LIMITS.keys()) == set(GROWTH_KEYS)
    for key, (lo, hi) in GROWTH_LIMITS.items():
        assert lo == 0.0
        if key in ("hp", "mp"):
            assert hi == 1000.0
        else:
            assert hi == 100.0


# ---------------------------------------------------------------------------
# V3 资源轴引用（红拦）
# ---------------------------------------------------------------------------
def test_v3_axis_ref_exists() -> None:
    """resource_axes ∈ stats 注册键 → 通过（V3 正例：map 形态查键）。"""
    report = _run(_modules([_ok_job()]))
    _no_red(report)
    assert "V3_axis_ref" not in _rules(report, "errors")


def test_v3_axis_ref_missing_hard_block() -> None:
    """resource_axes 引用不存在的资源轴 → 红拦（V3 反例：stats 存在则严格查）。"""
    report = _run(_modules([_ok_job(resource_axes=["mp", "ghost_axis"])]))
    assert "V3_axis_ref" in _rules(report, "errors"), \
        f"未注册资源轴应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["axis_ref"] == "ghost_axis"


def test_v3_stats_missing_loose_pass() -> None:
    """stats 模块缺失 → 宽松放行零红零黄（工程补白 P-3：6c 批8 才落注册表）。"""
    report = _run({"jobs": [_ok_job(resource_axes=["mp", "ghost_axis"])]})
    _no_red(report)
    assert report.warnings == []


def test_v3_stats_list_form() -> None:
    """stats list 形态 → 查条目 id（V3 正例 + 反例混合）。"""
    report = _run({"jobs": [_ok_job(resource_axes=["mp", "rage"])], "stats": _stats_list()})
    _no_red(report)
    bad = _run({"jobs": [_ok_job(resource_axes=["rage", "ghost"])], "stats": _stats_list()})
    assert "V3_axis_ref" in _rules(bad, "errors"), \
        f"list 形态未注册轴应红拦，got {bad.errors}"


def test_v3_axes_not_list_hard_block() -> None:
    """resource_axes 非数组 → 红拦（V3 反例：§1.1 #6 string[]）。"""
    report = _run(_modules([_ok_job(resource_axes="mp")]))
    assert "V3_axes_not_list" in _rules(report, "errors"), \
        f"resource_axes 非数组应红拦，got {report.errors}"


# ---------------------------------------------------------------------------
# V4 transform 段合法（红拦）
# ---------------------------------------------------------------------------
def test_v4_transform_legal_and_absent() -> None:
    """全键齐合法 transform / transform 缺省 → 通过（V4 正例：缺省=无形态切换职业）。"""
    report = _run(_modules([_ok_job()]))
    _no_red(report)
    report2 = _run(_modules([_ok_job(transform=None)]))
    _no_red(report2)


def test_v4_required_keys_missing_hard_block() -> None:
    """transform 段缺失必填键 → 逐键红拦（V4 反例：§1.3 七必填）。"""
    t = _ok_transform()
    t.pop("cooldown")
    t.pop("skill_set")
    report = _run(_modules([_ok_job(transform=t)]))
    assert "V4_required_missing" in _rules(report, "errors"), \
        f"缺必填键应红拦，got {report.errors}"
    missing = {e["detail"]["field_name"] for e in report.errors
               if e["detail"].get("rule") == "V4_required_missing"}
    assert missing == {"cooldown", "skill_set"}
    assert set(TRANSFORM_REQUIRED_KEYS) == {
        "transform_skill", "transform_to", "duration", "revert",
        "cooldown", "state_policy", "skill_set",
    }


def test_v4_battle_revert_conflict_hard_block() -> None:
    """duration=battle 配 revert=true → 红拦（TC-18 ④ / V4 反例：D-04 仲裁）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(
        duration="battle", revert=True, turns=None))]))
    assert "V4_battle_revert_conflict" in _rules(report, "errors"), \
        f"battle+revert=true 矛盾应红拦，got {report.errors}"
    assert "V4_turns_required" not in _rules(report, "errors"), \
        "battle 模式 turns 非条件必填，不应额外红拦"


def test_v4_battle_no_revert_legal() -> None:
    """duration=battle 配 revert=false → 通过（V4 正例：整场不还原合法）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(
        duration="battle", revert=False, turns=None))]))
    _no_red(report)


def test_v4_turns_required_when_duration_turns() -> None:
    """duration=turns 时 turns 缺失/≤0 → 红拦（V4 反例：§1.3 #24 条件必填）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(turns=None))]))
    assert "V4_turns_required" in _rules(report, "errors"), \
        f"turns 缺失应红拦，got {report.errors}"
    report2 = _run(_modules([_ok_job(transform=_ok_transform(turns=0))]))
    assert "V4_turns_positive" in _rules(report2, "errors"), \
        f"turns=0 应红拦，got {report2.errors}"


def test_v4_cooldown_negative_hard_block() -> None:
    """cooldown 负值 → 红拦（V4 反例：§1.3 #26 ≥0）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(cooldown=-1))]))
    assert "V4_cooldown_negative" in _rules(report, "errors"), \
        f"cooldown 负值应红拦，got {report.errors}"


def test_v4_duration_enum_invalid_hard_block() -> None:
    """duration 枚举外值 → 红拦（V4 反例：§1.3 #23 turns|battle）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(duration="forever"))]))
    assert "V4_duration_enum" in _rules(report, "errors"), \
        f"duration 枚举外值应红拦，got {report.errors}"
    assert "V4_battle_revert_conflict" not in _rules(report, "errors"), \
        "枚举外值不叠加矛盾红拦（P-7 防双报）"


def test_v4_state_policy_enum_hard_block() -> None:
    """state_policy 三键枚举外值 → 红拦（TC-18 ⑤ / V5 判定基底先行收口）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(
        state_policy={"combo": "shuffle", "marks": "keep", "buff": "keep"}))]))
    assert "V4_state_policy_enum" in _rules(report, "errors"), \
        f"state_policy.combo=shuffle 应红拦，got {report.errors}"
    assert report.errors[0]["detail"]["policy_key"] == "combo"
    assert report.errors[0]["detail"]["value"] == "shuffle"
    assert set(STATE_POLICY_VALUES) == {"clear", "keep"}


def test_v4_state_policy_not_object_hard_block() -> None:
    """state_policy 非对象 → 红拦（V4 反例：§1.4 三键子对象）。"""
    report = _run(_modules([_ok_job(transform=_ok_transform(state_policy="keep"))]))
    assert "V4_state_policy_not_object" in _rules(report, "errors"), \
        f"state_policy 非对象应红拦，got {report.errors}"


# ---------------------------------------------------------------------------
# 混合 / 收集器形态 / 登记一致性
# ---------------------------------------------------------------------------
def test_mixed_v1_v4_all_rules() -> None:
    """V1~V4 同时命中：红拦 4 类互不干扰（混合反例）。"""
    jobs = [_ok_job(
        burst_gauge=100,                        # V1 顶层未知键
        growth={"str": -1.0},                   # V2 负成长率
        resource_axes=["mp", "ghost_axis"],     # V3 引用缺失
        transform=_ok_transform(duration="battle", revert=True, turns=None),  # V4 矛盾
    )]
    report = _run(_modules(jobs))
    rules_err = _rules(report, "errors")
    for rule in ("V1_top_field_unregistered", "V2_growth_negative",
                 "V3_axis_ref", "V4_battle_revert_conflict"):
        assert rule in rules_err, f"{rule} 应红拦，got {report.errors}"


def test_report_dict_form() -> None:
    """收集器 dict 形态：{"errors":[],"warnings":[]}（_emit 兜底）。"""
    modules = _modules([_ok_job(resource_axes=["mp", "ghost_axis"])])
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_jobs(modules, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["rule"] == "V3_axis_ref"


def test_report_checker_form() -> None:
    """真实 validator._Checker 收口兼容（_err/_warn 回落；module 恒为 jobs）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    from qbot_rpg.content.validator import _Checker

    modules = _modules([_ok_job(resource_axes=["mp", "ghost_axis"])])
    checker = _Checker(modules, default_field_meta_table())
    validate_jobs(modules, checker)
    assert any("V3_axis_ref" in str(e.detail) for e in checker.errors), \
        "_Checker 应收集 V3 红拦"
    assert all(e.module == "jobs" for e in checker.errors), \
        "收集记录 module 应为 jobs"
