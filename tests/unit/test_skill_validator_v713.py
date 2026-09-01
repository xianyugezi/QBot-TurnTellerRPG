"""6a 技能库专项校验器 V-7~V-13 单测（tests/unit/test_skill_validator_v713.py · M13 批2 路2B）。

覆盖细化_6a 契约 §5 校验 V-7~V-13：
  - V-7 普攻每职业恰 1（库级红拦）
  - V-8 冷却非负（红拦）
  - V-9 MP 非负（红拦）
  - V-10 库内唯一（红拦）
  - V-11 字段登记（红拦）
  - V-12 kind 推断（黄提示）
  - V-13 基础门禁（枚举 + 数值域红拦）

测试目标：qbot_rpg.content.skill_validator.validate_skills
铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

from typing import Dict, List, Mapping

from qbot_rpg.content.skill_validator import validate_skills


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    def __init__(self) -> None:
        self.errors: List[Dict[str, object]] = []
        self.warnings: List[Dict[str, object]] = []

    def error(self, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"field": field, "kind": kind, "detail": detail})

    def warning(self, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"field": field, "kind": kind, "detail": detail})

    def _err(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.error(field, kind, **detail)

    def _warn(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warning(field, kind, **detail)


def _rules(report: _Report, level: str) -> set:
    return {e["detail"].get("rule", "") for e in getattr(report, level)}


def _ok_skill(**over: object) -> dict:
    s: Dict[str, object] = {
        "id": "power_strike",
        "name": "强力打击",
        "type": "active",
        "kind": "damage",
        "power": 150,
        "attack_type": "slash",
        "element": "fire",
        "effects": [{"effect": "flame_burst"}],
        "mp_cost": 10,
        "cooldown": 2,
        "tag": "none",
        "hits": 1,
    }
    s.update(over)
    return s


def _basic_skill(**over: object) -> dict:
    s: Dict[str, object] = {
        "id": "basic_attack",
        "name": "普攻",
        "type": "basic",
        "kind": "damage",
        "power": 100,
        "effects": [{"effect": "flame_burst"}],
    }
    s.update(over)
    return s


def _effects_table() -> list:
    return [{"id": "flame_burst", "name": "烈焰爆发"}, {"id": "heal_light", "name": "治疗术"}]


def _jobs_table() -> list:
    return [{"id": "warrior", "name": "战士"}, {"id": "mage", "name": "法师"}]


def _modules(skills: List[dict], **extra: object) -> dict:
    m: Dict[str, object] = {
        "skills": skills,
        "effects": _effects_table(),
        "jobs": _jobs_table(),
    }
    m.update(extra)
    return m


def _run(modules: Mapping[str, object]) -> _Report:
    report = _Report()
    validate_skills(modules, report)
    return report


# ---------------------------------------------------------------------------
# V-7 普攻每职业恰 1（库级红拦）
# ---------------------------------------------------------------------------
def test_v7_no_basic_hard_block() -> None:
    """技能库无 basic → 红拦（V-7）。"""
    report = _run(_modules([_ok_skill()]))
    assert "no_basic_attack" in _rules(report, "errors"), f"无普攻应红拦，got {report.errors}"


def test_v7_basic_each_job_exactly_one_ok() -> None:
    """全局 basic 1 条 → 所有职业恰 1（V-7 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill()]))
    assert report.errors == [], f"全局 basic 应零红拦，got {report.errors}"


def test_v7_job_specific_basic_counted() -> None:
    """战士专属 basic + 全局 basic → 战士 2 个 → 红拦（V-7 反例）。"""
    report = _run(_modules([
        _basic_skill(),  # 全局 → warrior+mage 各 +1
        _basic_skill(id="basic_warrior", job_restrict=["warrior"]),  # warrior +1
        _ok_skill(),
    ]))
    assert "job_multiple_basic" in _rules(report, "errors"), \
        f"战士可见 2 个 basic 应红拦，got {report.errors}"


def test_v7_job_with_zero_basic_hard_block() -> None:
    """jobs 表有职业但无 basic 覆盖 → 红拦（V-7：每职业恰 1）。"""
    report = _run(_modules([
        _basic_skill(job_restrict=["warrior"]),
        _ok_skill(),
    ]))
    # warrior 有专属 basic=1；mage 无任何 basic → mage 0 → 红拦
    assert "job_zero_basic" in _rules(report, "errors"), \
        f"mage 可见 0 个 basic 应红拦，got {report.errors}"


def test_v7_global_basic_multiple_hard_block() -> None:
    """无 job_restrict 的 basic 多于 1 → 红拦（V-7）。"""
    report = _run(_modules([
        _basic_skill(),
        _basic_skill(id="basic_attack2"),
        _ok_skill(),
    ]))
    assert "global_basic_multiple" in _rules(report, "errors"), \
        f"全局 basic 2 条应红拦，got {report.errors}"


# ---------------------------------------------------------------------------
# V-8 冷却非负 / V-9 MP 非负
# ---------------------------------------------------------------------------
def test_v8_cooldown_negative_hard_block() -> None:
    """cooldown=-1 → 红拦（V-8）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(cooldown=-1)]))
    assert "cooldown_negative" in _rules(report, "errors"), \
        f"冷却负数应红拦，got {report.errors}"


def test_v8_cooldown_zero_ok() -> None:
    """cooldown=0 → 通过（V-8 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(cooldown=0)]))
    assert "cooldown_negative" not in _rules(report, "errors")


def test_v9_mp_cost_negative_hard_block() -> None:
    """mp_cost=-1 → 红拦（V-9）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(mp_cost=-1)]))
    assert "mp_cost_negative" in _rules(report, "errors"), \
        f"MP 负数应红拦，got {report.errors}"


def test_v9_mp_cost_zero_ok() -> None:
    """mp_cost=0 → 通过（V-9 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(mp_cost=0)]))
    assert "mp_cost_negative" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V-10 库内唯一
# ---------------------------------------------------------------------------
def test_v10_duplicate_id_hard_block() -> None:
    """两条同 id → 红拦（V-10）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(id="basic_attack")]))
    assert "skill_id_duplicate" in _rules(report, "errors"), \
        f"重复 id 应红拦，got {report.errors}"


def test_v10_unique_ids_ok() -> None:
    """id 全唯一 → 通过（V-10 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill()]))
    assert "skill_id_duplicate" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V-11 字段登记
# ---------------------------------------------------------------------------
def test_v11_unregistered_field_hard_block() -> None:
    """条目含未登记字段（如 bogus_field）→ 红拦（V-11）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(bogus_field=1)]))
    assert "skill_field_unregistered" in _rules(report, "errors"), \
        f"未登记字段应红拦，got {report.errors}"


def test_v11_all_registered_fields_ok() -> None:
    """条目字段全在 skills_fields 24 键内 → 通过（V-11 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill()]))
    assert "skill_field_unregistered" not in _rules(report, "errors")


# ---------------------------------------------------------------------------
# V-12 kind 推断
# ---------------------------------------------------------------------------
def test_v12_kind_missing_inferred_heal() -> None:
    """kind 缺省 + effects 含 heal 原子动作 → 黄提示 kind_inferred（V-12）。"""
    report = _run(_modules([
        _basic_skill(), _ok_skill(kind=None, effects=[{"type": "heal", "power": 50}])
    ]))
    assert "kind_inferred" in _rules(report, "warnings"), \
        f"kind 推断应发黄提示，got {report.warnings}"
    assert report.errors == [], f"V-12 黄提示不应红拦，got {report.errors}"


def test_v12_kind_explicit_no_warning() -> None:
    """kind 显式 → 不推断不发提示（V-12 正例）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(kind="damage")]))
    assert "kind_inferred" not in _rules(report, "warnings")
    assert "kind_not_inferred" not in _rules(report, "warnings")


# ---------------------------------------------------------------------------
# V-13 基础门禁
# ---------------------------------------------------------------------------
def test_v13_kind_enum_invalid_hard_block() -> None:
    """kind=bogus → 红拦（V-13 枚举）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(kind="bogus")]))
    assert "skill_kind_enum_invalid" in _rules(report, "errors"), \
        f"kind 非法应红拦，got {report.errors}"


def test_v13_type_enum_invalid_hard_block() -> None:
    """type=bogus → 红拦（V-13 枚举）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(type="bogus")]))
    assert "skill_type_enum_invalid" in _rules(report, "errors"), \
        f"type 非法应红拦，got {report.errors}"


def test_v13_power_out_of_range_hard_block() -> None:
    """power=9999 → 红拦（V-13 数值域）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(power=9999)]))
    assert "power_out_of_range" in _rules(report, "errors"), \
        f"power 越界应红拦，got {report.errors}"


def test_v13_attack_type_chinese_old_value_ok() -> None:
    """attack_type 中文旧值（斩/打/突/魔）→ 读兼容放行（V-13 P-4）。"""
    report = _run(_modules([_basic_skill(), _ok_skill(attack_type="斩")]))
    assert "skill_attack_type_invalid" not in _rules(report, "errors"), \
        f"中文旧值应放行，got {report.errors}"


def test_v13_legal_skill_zero_red() -> None:
    """全合法技能 → 红拦零命中。"""
    report = _run(_modules([_basic_skill(), _ok_skill()]))
    assert report.errors == [], f"合法技能应零红拦，got {report.errors}"
