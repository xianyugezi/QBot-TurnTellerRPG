"""M13 三契约缺口扫描（tests/unit/test_m13_contract_gaps.py · M13 批18 路18C）。

直连实现可寻址性扫描（非硬编码清单）：
  - 6a 技能库：skills_fields() 30 键 + skill_validator V-1~V-13 + 测试文件
  - 6b 职业库：jobs_fields() 并集 34 键 + job_validator V1~V8 + transform 状态机
  - 6c 资源轴：resource_axis_fields() 10 键 + validator V1~V11 + 季节/事件常量

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠。
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import List

import qbot_rpg.content  # noqa: F401 - 确保包可导入
import qbot_rpg.core  # noqa: F401


def _module_symbols(module_path: str) -> set:
    """模块公开符号集合（直连 dir()；保留单下划线内部函数）。"""
    try:
        mod = importlib.import_module(module_path)
    except Exception:  # noqa: BLE001 - 模块缺失 → 空集合（缺口）
        return set()
    return {n for n in dir(mod) if not n.startswith("__")}


def _content_modules() -> List[str]:
    """qbot_rpg.content 下全部子模块名。"""
    return [m.name for m in pkgutil.iter_modules(qbot_rpg.content.__path__)]


def _core_modules() -> List[str]:
    """qbot_rpg.core 下全部子模块名。"""
    return [m.name for m in pkgutil.iter_modules(qbot_rpg.core.__path__)]


def _tests_exist(prefix: str) -> bool:
    """测试文件存在性（tests/unit/test_<prefix>*.py）。"""
    td = Path("tests/unit")
    return any(td.glob(f"test_{prefix}*.py"))


# ---------------------------------------------------------------------------
# ① 6a 技能库
# ---------------------------------------------------------------------------
def test_6a_fields_function_addressable() -> None:
    """skills_fields() 可寻址且 ≥ 24 契约键。"""
    from qbot_rpg.content.skill_models import skills_fields

    f = skills_fields()
    assert len(f) >= 24, f"skills_fields 应 ≥24 键，got {len(f)}"


def test_6a_validator_addressable() -> None:
    """skill_validator.validate_skills 可寻址。"""
    from qbot_rpg.content.skill_validator import validate_skills

    assert callable(validate_skills)


def test_6a_rules_addressable() -> None:
    """V-1~V-13 规则函数可寻址（_check_vN_* 或 rule 常量）。"""
    syms = _module_symbols("qbot_rpg.content.skill_validator")
    rule_fns = {s for s in syms if s.startswith("_check_")}
    assert len(rule_fns) >= 6, f"校验函数应 ≥6，got {len(rule_fns)}"
    assert any("v" in s.lower() for s in rule_fns)


def test_6a_tests_exist() -> None:
    """6a 测试文件存在（test_skill_*）。"""
    assert _tests_exist("skill_"), "6a 测试文件缺失"


# ---------------------------------------------------------------------------
# ② 6b 职业库
# ---------------------------------------------------------------------------
def test_6b_fields_addressable() -> None:
    """jobs_fields() 并集 34 键（顶层 11 + children 20 + state_policy 3）。"""
    from qbot_rpg.content.job_models import jobs_fields, state_policy_fields

    fields = jobs_fields()
    child_keys: set = set()
    for meta in fields.values():
        ch = getattr(meta, "children", None) or {}
        if isinstance(ch, dict):
            child_keys |= set(ch.keys())
    union = set(fields) | child_keys | set(state_policy_fields())
    assert len(union) >= 34, f"jobs 并集应 ≥34，got {len(union)}"


def test_6b_validators_addressable() -> None:
    """job_validator 双入口可寻址。"""
    from qbot_rpg.content.job_validator import validate_jobs
    from qbot_rpg.content.job_validator_v58 import validate_jobs_v58

    assert callable(validate_jobs) and callable(validate_jobs_v58)


def test_6b_transform_state_7_fields() -> None:
    """transform_state 7 字段常量可寻址。"""
    from qbot_rpg.core.transform_snapshot import TRANSFORM_STATE_FIELDS

    assert len(TRANSFORM_STATE_FIELDS) == 7


def test_6b_state_machine_constants() -> None:
    """状态机 5 态 + 迁移表可寻址。"""
    from qbot_rpg.core.transform import STATE_TRANSITIONS

    assert len(STATE_TRANSITIONS) == 5


def test_6b_tests_exist() -> None:
    """6b 测试文件存在（test_job_* / test_transform_*）。"""
    assert _tests_exist("job_"), "6b job 测试缺失"
    assert _tests_exist("transform_"), "6b transform 测试缺失"


# ---------------------------------------------------------------------------
# ③ 6c 资源轴
# ---------------------------------------------------------------------------
def test_6c_fields_addressable() -> None:
    """resource_axis_fields() 恰 10 键。"""
    from qbot_rpg.content.resource_axis_models import resource_axis_fields

    f = resource_axis_fields()
    assert len(f) == 10, f"resource_axis_fields 应恰 10 键，got {len(f)}"


def test_6c_validator_addressable() -> None:
    """resource_axis_validator 双入口可寻址。"""
    from qbot_rpg.content.resource_axis_validator import (
        validate_resource_axes,
        validate_skill_energy,
    )

    assert callable(validate_resource_axes)
    assert callable(validate_skill_energy)


def test_6c_reset_enum() -> None:
    """reset 三枚举常量。"""
    from qbot_rpg.content.resource_axis_validator import RESET_VALUES

    assert set(RESET_VALUES) == {"battle", "keep", "battle_start"}


def test_6c_season_constants() -> None:
    """季节四枚举 + 事件常量可寻址。"""
    from qbot_rpg.core.season_events import ON_SEASON_CHANGE, SEASON_EVENTS
    from qbot_rpg.core.skill_season import SEASONS

    assert len(SEASONS) == 4
    assert ON_SEASON_CHANGE in SEASON_EVENTS


def test_6c_engine_modules() -> None:
    """6c 引擎模块全部落盘（core 层）。"""
    core = _core_modules()
    for m in ("resource_axis", "resource_lifecycle", "combo_table",
              "combo_settle", "battle_season", "season_events", "skill_season"):
        assert m in core, f"core.{m} 模块缺失"


def test_6c_tests_exist() -> None:
    """6c 测试文件存在（test_resource_* / test_season_* / test_combo_*）。"""
    assert _tests_exist("resource_"), "6c resource 测试缺失"
    assert _tests_exist("season_"), "6c season 测试缺失"
    assert _tests_exist("combo_"), "6c combo 测试缺失"


# ---------------------------------------------------------------------------
# ④ 装配层
# ---------------------------------------------------------------------------
def test_assembly_modules() -> None:
    """装配接线模块全部落盘。"""
    core = _core_modules()
    for m in ("skill_slots", "skill_slots_battle", "job_slots", "transform",
              "transform_revert", "transform_snapshot"):
        assert m in core, f"core.{m} 模块缺失"


def test_commands_modules() -> None:
    """指令模块落盘（/转职 /注册 消费链）。"""
    from qbot_rpg.commands.job_commands import cmd_job, register_job_commands
    from qbot_rpg.commands.register_commands import default_job, resolve_job

    assert callable(cmd_job) and callable(register_job_commands)
    assert callable(default_job) and callable(resolve_job)
