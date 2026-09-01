"""M13 批12 路12B · 6c 资源轴新增校验 V6~V11 单测
（tests/unit/test_resource_axis_validator_v611.py）。

覆盖细化_6c §五（497 行 v1.0）：
  - V6 注册结构（红拦）：数值型 max ≥ 0；子池型 pools 非空/池名 ∈ 元素注册表/
    max_per_pool ≥ 1/pool_icons 键 = pools 完整集合；
  - V7 键空间与层数型隔离（红拦）：any 键仅子池型技能合法；同技能 any 与
    具名键互斥（K3）；层数型资源（marks 型）出现于 energy 键 → 红拦；
  - V8 组合表校验（黄提示）：combo 行元素 ∈ 轴 pools；kind 枚举；power 0-400；
    行数 ≤ C(|pools|+1,2)；可达性 RE（每组合 ≥1 获取路径）；
  - V9 季节组校验（红拦）：season 四枚举；每季 ≤5/非空；通用组 ≥1；
    season_element 键 = 四季完整四枚 + 值 ∈ 元素注册表；
  - V10 互译表登记（红拦）：condition 引用 [季节:X] 需已登记（框架四季已登记，
    只查自定义季节）；
  - V11 事件枚举登记（红拦）：proc/effect trigger ∈ 事件枚举登记表；
    trigger_limit 非负。

测试目标：qbot_rpg.content.resource_axis_validator.{validate_resource_axes,
validate_skill_energy, validate_season_groups, DEFAULT_ELEMENTS, COMBO_KINDS,
COMBO_POWER_MAX, SEASONS, SEASON_GROUP_MAX, TRANSLATED_SEASONS,
SEASON_EVENTS_MIRROR, PROC_TRIGGER_EVENTS}。

测试口径（对齐 test_skill_validator.py）：
  - validate_* 为 (modules, report) 纯函数；report 鸭子类型收集器
    （error/warning 与 _Checker._err/_warn 一致）；
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, Set

from qbot_rpg.content.resource_axis_validator import (
    COMBO_KINDS,
    COMBO_POWER_MAX,
    DEFAULT_ELEMENTS,
    PROC_TRIGGER_EVENTS,
    SEASONS,
    SEASON_EVENTS_MIRROR,
    SEASON_GROUP_MAX,
    TRANSLATED_SEASONS,
    validate_resource_axes,
    validate_season_groups,
    validate_skill_energy,
)


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_* 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _stats(**axes: Any) -> Dict[str, Any]:
    """stats 模块（rage 数值型 + element_energy 子池型默认注册）。"""
    base: Dict[str, Any] = {
        "rage": {"name": "怒气", "type": "rage", "base": 0, "max": 100,
                 "reset": "battle", "display": "status_line", "icon": "💢"},
        "element_energy": {"name": "元素能量", "type": "element_energy", "base": 0,
                           "max_per_pool": 3, "pools": ["fire", "water", "wind"],
                           "pool_icons": {"fire": "🔥", "water": "💧", "wind": "🌪"},
                           "display": "pool_line", "icon": "✨"},
    }
    base.update(axes)
    return base


def _skill(**over: Any) -> Dict[str, Any]:
    """一条技能条目（合法最小形态 + 全引用靶命中）。"""
    s: Dict[str, Any] = {
        "id": "flame_strike", "name": "烈焰斩", "type": "active", "kind": "damage",
        "power": 100, "effects": [{"effect": "flame_burst", "overrides": {"power": 50}}],
        "trigger_limit": {"per_round": 10, "per_battle": 99},
    }
    s.setdefault("season", "spring")
    s.update(over)
    return s


def _modules(skills: list, **extra: Any) -> Dict[str, Any]:
    """校验器 modules（skills + stats + 引用靶模块缺省全配）。"""
    m: Dict[str, Any] = {
        "skills": skills,
        "stats": _stats(),
        "marks": [{"id": "fire_mark", "name": "火印", "max": 5}],
        "formula": {"elements": {"earth": "地", "fire": "火", "water": "水", "wind": "风"}},
    }
    m.update(extra)
    return m


def _run_energy(modules: Mapping[str, object]) -> _Report:
    """跑 validate_skill_energy，返回收集器。"""
    report = _Report()
    validate_skill_energy(modules, report)
    return report


def _grouped_skills(*extras: Mapping[str, Any]) -> list:
    """四季各 1 技 + 通用 1 技 + 附加技能（V9 组规模全满足，供零红拦场景）。

    general 技能须显式 season=None（_skill 默认 season=spring 会误入春组）。
    """
    skills: list = [_skill(id=f"season_{s}", season=s) for s in SEASONS]
    skills.append(_skill(id="general_skill", season=None))
    skills.extend(extras)
    return skills


def _rules(report: _Report, level: str) -> Set[str]:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


def _no_red(report: _Report) -> None:
    assert report.errors == [], f"应红拦零命中，got {report.errors}"


# ---------------------------------------------------------------------------
# V6 注册结构（红拦）
# ---------------------------------------------------------------------------
def test_v6_numeric_axis_max_negative_red() -> None:
    """数值型 max 负值 → V6 红拦（V6-1）。"""
    report = _Report()
    validate_resource_axes({"stats": _stats(rage={"type": "rage", "max": -5})}, report)
    assert "axis_max_negative" in _rules(report, "errors"), f"got {report.errors}"


def test_v6_pool_element_unregistered_red() -> None:
    """子池型池名 ∈ 元素注册表（V6-2）：ice 未注册 → 红拦。"""
    report = _Report()
    validate_resource_axes(
        {"stats": _stats(element_energy={"type": "element_energy",
                                         "pools": ["fire", "ice"],
                                         "max_per_pool": 3,
                                         "pool_icons": {"fire": "🔥", "ice": "❄"}})},
        report)
    assert "pool_element_unregistered" in _rules(report, "errors"), f"got {report.errors}"
    assert report.errors[0]["detail"]["pool"] == "ice"

def test_v6_max_per_pool_lt_one_red() -> None:
    """子池型 max_per_pool < 1 → V6 红拦（V6-3）。"""
    report = _Report()
    validate_resource_axes(
        {"stats": _stats(element_energy={"type": "element_energy",
                                         "pools": ["fire"], "max_per_pool": 0})},
        report)
    assert "max_per_pool_lt_one" in _rules(report, "errors"), f"got {report.errors}"


def test_v6_pool_icons_missing_keys_red() -> None:
    """子池型 pool_icons 键缺 wind → V6 红拦（V6-4，TC-18⑥）。"""
    report = _Report()
    validate_resource_axes(
        {"stats": _stats(element_energy={"type": "element_energy",
                                         "pools": ["fire", "water", "wind"],
                                         "max_per_pool": 3,
                                         "pool_icons": {"fire": "🔥", "water": "💧"}})},
        report)
    assert "pool_icons_missing_keys" in _rules(report, "errors"), f"got {report.errors}"
    assert report.errors[0]["detail"]["missing"] == ["wind"]


def test_v6_ok_axes_zero_red() -> None:
    """合法两型注册段 → V6 红拦零命中（正例）。"""
    report = _Report()
    validate_resource_axes({"stats": _stats()}, report)
    _no_red(report)


# ---------------------------------------------------------------------------
# V7 键空间与层数型隔离（红拦）
# ---------------------------------------------------------------------------
def test_v7_any_on_numeric_axis_red() -> None:
    """any 键用于数值型技能（rage）→ V7 红拦（TC-18①）。"""
    report = _run_energy(_modules([_skill(energy_cost={"rage": 100, "any": 2})]))
    assert "any_named_mutex" in _rules(report, "errors"), f"got {report.errors}"
    assert "any_on_numeric_axis" in _rules(report, "errors"), f"got {report.errors}"


def test_v7_any_named_mutex_red() -> None:
    """子池型技能 any 与具名键互斥（K3）→ V7 红拦。"""
    report = _run_energy(_modules([_skill(energy_cost={"any": 2, "fire": 1})]))
    assert "any_named_mutex" in _rules(report, "errors"), f"got {report.errors}"


def test_v7_mark_in_energy_key_red() -> None:
    """层数型资源（marks 型）出现于 energy 键 → V7 红拦。"""
    report = _run_energy(_modules([_skill(energy_gain={"fire_mark": 1})]))
    assert "mark_in_energy_key" in _rules(report, "errors"), f"got {report.errors}"


def test_v7_any_on_pooled_ok() -> None:
    """子池型 any 键（{any: 2}）→ 通过（V7 正例）。"""
    report = _run_energy(_modules(_grouped_skills(
        _skill(energy_cost={"any": 2}), )))
    _no_red(report)


# ---------------------------------------------------------------------------
# V8 组合表（黄提示不拦截）
# ---------------------------------------------------------------------------
def _combo_skill(**over: Any) -> Dict[str, Any]:
    """带 combo_table 的合法技能（轴=element_energy，行全合法 + 有产出技）。"""
    s = _skill(
        energy_cost={"element_energy": {"any": 2}},
        combo_table=[
            {"combo": ["fire", "fire"], "name": "烈焰爆破", "kind": "damage",
             "power": 300, "element": "fire"},
        ],
    )
    s.update(over)
    return s


def _producer(**over: Any) -> Dict[str, Any]:
    """产能量技（energy_gain 途径，RE-2 统计靶；缺省产出三池）。"""
    s = _skill(
        id="producer",
        energy_gain={"element_energy": {"fire": 1, "water": 1, "wind": 1}},
    )
    s.update(over)
    return s


def test_v8_combo_element_unregistered_warn() -> None:
    """组合行元素 earth 不在轴 pools → V8 黄提示（TC-18②）。"""
    report = _run_energy(_modules([
        _producer(),
        _combo_skill(combo_table=[
            {"combo": ["earth", "earth"], "kind": "damage", "power": 100}]),
    ]))
    assert "combo_element_unregistered" in _rules(report, "warnings"), \
        f"got {report.warnings}"


def test_v8_combo_kind_invalid_warn() -> None:
    """行 kind=explode 枚举外 → V8 黄提示（TC-18③）。"""
    report = _run_energy(_modules(_grouped_skills(
        _producer(),
        _combo_skill(combo_table=[
            {"combo": ["fire", "fire"], "kind": "explode", "power": 100}]), )))
    assert "combo_kind_invalid" in _rules(report, "warnings"), f"got {report.warnings}"
    assert report.errors == [], f"V8 黄提示不应红拦，got {report.errors}"


def test_v8_combo_power_over_400_warn() -> None:
    """行 power 500 超 0-400 → V8 黄提示（幻觉审查_6c ≤400 口径）。"""
    report = _run_energy(_modules([
        _producer(),
        _combo_skill(combo_table=[
            {"combo": ["fire", "fire"], "kind": "damage", "power": 500}]),
    ]))
    assert "combo_power_out_of_range" in _rules(report, "warnings"), \
        f"got {report.warnings}"
    assert report.warnings[0]["detail"]["power"] == 500


def test_v8_combo_rows_over_limit_warn() -> None:
    """组合行数 7 行（3 池上限 6）→ V8 黄提示（TC-18④）。"""
    rows = [{"combo": ["fire", "water"], "kind": "damage", "power": 100}] * 7
    report = _run_energy(_modules([_producer(), _combo_skill(combo_table=rows)]))
    assert "combo_rows_over_limit" in _rules(report, "warnings"), \
        f"got {report.warnings}"
    assert report.warnings[0]["detail"]["limit"] == 6


def test_v8_combo_unreachable_warn() -> None:
    """组合池无获取路径（删 water 产出）→ V8 黄提示（TC-16② / RE-1~4）。"""
    skills = [
        _producer(energy_gain={"element_energy": {"fire": 1, "wind": 1}}),
        _combo_skill(combo_table=[
            {"combo": ["fire", "water"], "kind": "damage", "power": 100}]),
    ]
    report = _run_energy(_modules(skills))
    assert "combo_unreachable" in _rules(report, "warnings"), f"got {report.warnings}"
    assert report.warnings[0]["detail"]["pools"] == ["water"]


def test_v8_ok_combo_zero_warn() -> None:
    """全合法组合表（含产出技）→ V8 黄提示零命中（正例）。"""
    report = _run_energy(_modules([_producer(), _combo_skill()]))
    assert report.warnings == [], f"应黄提示零命中，got {report.warnings}"


# ---------------------------------------------------------------------------
# V9 季节组（红拦）
# ---------------------------------------------------------------------------
def test_v9_season_enum_invalid_red() -> None:
    """season 拼写错（sumer）→ V9 红拦（TC-19①）。"""
    report = _run_energy(_modules([_skill(season="sumer")]))
    assert "season_enum_invalid" in _rules(report, "errors"), f"got {report.errors}"


def test_v9_season_group_over_cap_red() -> None:
    """夏组 6 技 → V9 红拦（TC-19②：≤5）。"""
    skills = [_skill(id=f"s{i}", season="summer") for i in range(6)]
    skills.append(_skill(id="general_skill", season=None))
    report = _run_energy(_modules(skills))
    assert "season_group_over_cap" in _rules(report, "errors"), f"got {report.errors}"
    over = [e for e in report.errors
            if e["detail"].get("rule") == "season_group_over_cap"
            and e["detail"].get("season") == "summer"]
    assert over, f"应命中夏组超上限，got {report.errors}"


def test_v9_general_group_empty_red() -> None:
    """通用组 0 技（全部带 season）→ V9 红拦（TC-19③：普攻兜底必在）。"""
    skills = [_skill(id=f"s{i}", season=s) for i, s in enumerate(SEASONS)]
    report = _run_energy(_modules(skills))
    assert "general_group_empty" in _rules(report, "errors"), f"got {report.errors}"


def test_v9_season_element_missing_keys_red() -> None:
    """season_element 缺 autumn 键 → V9 红拦（TC-19④）。"""
    report = _run_energy(_modules([_skill(season_element={
        "spring": "wind", "summer": "fire", "winter": "water"})]))
    assert "season_element_missing_keys" in _rules(report, "errors"), \
        f"got {report.errors}"
    assert report.errors[0]["detail"]["missing"] == ["autumn"]


def test_v9_season_element_bad_element_red() -> None:
    """season_element 值 ice 未注册 → V9 红拦（值 ∈ 元素注册表）。"""
    report = _run_energy(_modules([_skill(season_element={
        "spring": "ice", "summer": "fire", "autumn": "earth", "winter": "water"})]))
    assert "season_element_bad_element" in _rules(report, "errors"), \
        f"got {report.errors}"


def test_v9_ok_season_groups_zero_red() -> None:
    """四季各 1 技 + 通用 1 技 → V9 红拦零命中（正例）。"""
    report = _run_energy(_modules(_grouped_skills()))
    _no_red(report)


# ---------------------------------------------------------------------------
# V10 互译表登记（红拦）
# ---------------------------------------------------------------------------
def test_v10_season_cond_unregistered_red() -> None:
    """condition [季节:梅雨季] 未登记互译表 → V10 红拦（TC-19⑤；只查自定义季节）。

    框架四季键（spring/summer/autumn/winter）视为已登记（condition_engine
    L164），自定义季节（梅雨季）未登记 → 红拦。
    """
    report = _run_energy(_modules(_grouped_skills(
        _skill(condition={"var": "season", "op": "eq", "param": "梅雨季"}), )))
    assert "season_cond_unregistered" in _rules(report, "errors"), f"got {report.errors}"
    assert report.errors[0]["detail"]["season"] == "梅雨季"


def test_v10_registered_season_cond_ok() -> None:
    """框架四季键 [季节:spring] → 通过（condition_engine L164 已登记）。"""
    report = _run_energy(_modules(_grouped_skills(
        _skill(condition={"var": "season", "op": "eq", "param": "spring"}), )))
    _no_red(report)


def test_v10_effects_condition_unregistered_red() -> None:
    """效果内嵌 condition [季节:X] 未登记 → V10 红拦（消费点 2 效果侧）。"""
    report = _run_energy(_modules(_grouped_skills(
        _skill(effects=[
            {"effect": "buff", "condition": {"var": "season", "op": "eq",
                                             "param": "梅雨季"}}]), )))
    assert "season_cond_unregistered" in _rules(report, "errors"), f"got {report.errors}"
    assert report.errors[0]["detail"]["season"] == "梅雨季"


# ---------------------------------------------------------------------------
# V11 事件枚举登记（红拦）
# ---------------------------------------------------------------------------
def test_v11_trigger_event_unregistered_red() -> None:
    """proc trigger=on_bogus 未登记事件枚举 → V11 红拦。"""
    report = _run_energy(_modules(_grouped_skills(
        _skill(effects=[{"type": "proc", "trigger": "on_bogus", "actions": []}]), )))
    assert "trigger_event_unregistered" in _rules(report, "errors"), \
        f"got {report.errors}"
    assert report.errors[0]["detail"]["trigger"] == "on_bogus"


def test_v11_registered_triggers_ok() -> None:
    """已登记事件（on_turn_start/on_hit/on_season_change）→ 通过。"""
    for trig in PROC_TRIGGER_EVENTS:
        report = _run_energy(_modules(_grouped_skills(
            _skill(effects=[{"type": "proc", "trigger": trig, "actions": []}]), )))
        _no_red(report)


def test_v11_trigger_limit_negative_red() -> None:
    """trigger_limit 负值 → V11 红拦（上限字段合法）。"""
    report = _run_energy(_modules(_grouped_skills(
        _skill(trigger_limit={"per_round": -1, "per_battle": 99}), )))
    assert "trigger_limit_negative" in _rules(report, "errors"), f"got {report.errors}"


# ---------------------------------------------------------------------------
# 常量 / 收集器形态 / 入口一致性
# ---------------------------------------------------------------------------
def test_constants_sync_with_contract() -> None:
    """V6~V11 常量与细化_6c 契约口径一致。"""
    assert DEFAULT_ELEMENTS == (
        "earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void",
    )
    assert COMBO_KINDS == ("damage", "utility", "heal", "control")
    assert COMBO_POWER_MAX == 400.0
    assert SEASONS == ("spring", "summer", "autumn", "winter")
    assert SEASON_GROUP_MAX == 5
    assert TRANSLATED_SEASONS == SEASONS
    assert SEASON_EVENTS_MIRROR == ("on_season_change",)
    assert "on_season_change" in PROC_TRIGGER_EVENTS


def test_validate_season_groups_entry_alias() -> None:
    """validate_season_groups 与 validate_skill_energy 同源（V9~V11 收口）。"""
    report = _Report()
    validate_season_groups(_modules([_skill(season="bogus")]), report)
    assert "season_enum_invalid" in _rules(report, "errors"), f"got {report.errors}"


def test_report_dict_form() -> None:
    """收集器 dict 形态：{\"errors\":[],\"warnings\":[]}。"""
    modules = _modules([_skill(season="bogus")])
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_skill_energy(modules, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["rule"] == "season_enum_invalid"


def test_skills_module_missing_skipped() -> None:
    """skills 模块缺失 → 跳过不报错（对齐既有校验器「模块未接线默认放行」）。"""
    report = _Report()
    validate_skill_energy({"stats": _stats()}, report)
    assert report.errors == [] and report.warnings == []
