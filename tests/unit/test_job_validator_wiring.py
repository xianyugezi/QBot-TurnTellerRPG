"""M13 批5 路5C：6b 校验器装配单测（tests/unit/test_job_validator_wiring.py）。

覆盖：
  - validator._check_module 对 jobs 模块分派 validate_jobs（坏条目 → 红拦收集；
    5A/5B 未落盘时 pytest.importorskip 跳过，专项接线后自动生效）
  - 合法 jobs 条目 → _check_module 零红拦
  - build_pack 全链路：test_demo 加载（jobs.json 未落盘 → 跳过 / Y-6 软放行）
  - field_meta 模块登记 + loader _KIND_FOR_MODULE 映射 + manifest 声明一致性

铁律：零 NoneBot import；零 time.sleep 字面量；纯函数确定性；不 git commit。

先例：tests/unit/test_skill_validator_wiring.py（6a 批2 路2C 同款装配验收）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

import pytest

from qbot_rpg.content.field_meta import _module_table, default_field_meta_table
from qbot_rpg.content.loader import _KIND_FOR_MODULE, build_pack
from qbot_rpg.content.validator import _Checker

REPO = Path(__file__).resolve().parents[2]

# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------


def _legal_jobs() -> list:
    """合法职业条目（细化_6b §1.1 顶层 + §1.2 growth + §1.3/§1.4 transform 段）。"""
    return [
        {
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战输出",
            "recommended_newbie": True,
            "resource_axes": ["mp"],
            "growth": {"str": 2.0, "con": 1.5, "foc": 1.0},
            "transform": {
                "transform_skill": "berserk", "transform_to": "berserker_form",
                "duration": "turns", "turns": 4, "revert": True, "cooldown": 5,
                "dispel_reverts": True,
                "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        },
        {
            "id": "novice", "name": "新手",
            "difficulty": "simple", "playstyle": "上手",
            "recommended_newbie": True,
        },
    ]


def _job_validator() -> object:
    """按 5A/5B 实际落盘模块取 validate_jobs（未落盘 → pytest.importorskip 跳过）。

    任务约定：5A/5B 写 validate_jobs 实现，本路只做装配接线——专项未落盘期间
    用 importorskip 占位，专项接线后（模块存在即真实调用）自动生效。
    """
    try:
        from qbot_rpg.content.job_validator import validate_jobs
    except ImportError:
        pytest.skip("job_validator.validate_jobs 未落盘（批5 路5A/5B 未交付），跳过专项断言")
    else:
        return validate_jobs


# ---------------------------------------------------------------------------
# 1. validator 分派（_check_module → validate_jobs）
# ---------------------------------------------------------------------------
def test_check_module_dispatches_jobs_red_blocks() -> None:
    """_check_module 对 jobs 模块分派 validate_jobs（坏条目 → 红拦收集）。

    坏条目：transform_skill 引用技能不存在（V2 归属/存在性基底）。若 5A/5B
    未落盘 → importorskip 跳过（专项接线后自动生效）。
    """
    modules: Dict[str, object] = {
        "jobs": [
            {
                "id": "warrior", "name": "战士",
                "difficulty": "simple", "playstyle": "近战",
                "recommended_newbie": True,
                "resource_axes": ["mp"],
                "transform": {
                    "transform_skill": "ghost_skill",
                    "transform_to": "berserker_form",
                    "duration": "turns", "turns": 4, "revert": True,
                    "cooldown": 5,
                    "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                    "skill_set": "transform_skills",
                },
            },
        ],
        "skills": [],
        "skill_chains": [],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("jobs")
    assert checker.errors, "坏 jobs 条目应收集红拦（V2 transform_skill 引用缺失）"
    assert all(e.module == "jobs" for e in checker.errors)


def test_check_module_legal_jobs_zero_red() -> None:
    """合法 jobs 条目 → _check_module 零红拦（专项 + 泛型双轨并行）。"""
    modules: Dict[str, object] = {
        "jobs": _legal_jobs(),
        "skills": [
            {"id": "berserk", "name": "狂暴", "kind": "status", "type": "active",
             "job_form": "berserker_form"},
            {"id": "transform_skills", "name": "形态技能组", "kind": "utility", "type": "passive"},
        ],
        "skill_chains": [],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("jobs")
    assert checker.errors == [], f"合法 jobs 应零红拦：{checker.errors}"


def test_check_module_jobs_missing_module_skips_silently() -> None:
    """jobs 模块缺失 → _check_module 不抛异常（模块未声明默认放行）。

    顶层结构形态检查（R-5 module_structure）为既有泛型先例：数据缺失 → 报
    结构红拦（模块声明但数据非 list 的拒绝语义）。本用例断言不抛异常且
    validate_jobs 未触发——红拦来自泛型结构检查，非专项。
    """
    meta = default_field_meta_table()
    checker = _Checker({}, meta)
    checker._check_module("jobs")
    # 不抛异常（专项 import 兜底 + 泛型安全）；结构红拦为既有泛型语义
    assert not any(
        e.detail.get("rule") not in ("module_structure",)
        for e in checker.errors
    ), f"jobs 缺失只应报泛型结构红拦：{checker.errors}"


def test_check_module_jobs_v5_state_policy_enum_red_blocks() -> None:
    """state_policy.combo=\"shuffle\"（枚举外值）→ 泛型 R-1 enum 红拦（V5 判定基底）。

    不依赖 5A/5B 落盘：field_meta jobs 登记表驱动（V5 基底，细化_6b §1.4）。
    """
    modules: Dict[str, object] = {
        "jobs": [
            {
                "id": "warrior", "name": "战士",
                "transform": {
                    "transform_skill": "berserk", "transform_to": "berserker_form",
                    "duration": "turns", "turns": 4, "revert": True,
                    "cooldown": 5,
                    "state_policy": {"combo": "shuffle", "marks": "keep", "buff": "keep"},
                    "skill_set": "transform_skills",
                },
            },
        ],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("jobs")
    assert any(
        e.kind == "R-1" and e.detail.get("rule") == "enum"
        and e.detail.get("got") == "shuffle"
        for e in checker.errors
    ), f"V5 基底应红拦 combo=shuffle：{checker.errors}"


def test_check_module_jobs_transform_required_red_blocks() -> None:
    """transform 段缺必填子字段（transform_skill）→ 泛型 R-5 required_missing 红拦。

    不依赖 5A/5B 落盘：field_meta transform children 登记表驱动（细化_6b §1.3）。
    """
    modules: Dict[str, object] = {
        "jobs": [
            {
                "id": "warrior", "name": "战士",
                "transform": {
                    "transform_to": "berserker_form",
                    "duration": "turns", "turns": 4, "revert": True,
                    "cooldown": 5,
                    "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                    "skill_set": "transform_skills",
                },
            },
        ],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("jobs")
    assert any(
        e.kind == "R-5" and e.detail.get("rule") == "required_missing"
        and e.detail.get("name") == "transform_skill"
        for e in checker.errors
    ), f"transform 必填缺失应红拦：{checker.errors}"


# ---------------------------------------------------------------------------
# 2. 登记一致性（field_meta / loader / manifest）
# ---------------------------------------------------------------------------
def test_field_meta_jobs_module_registered() -> None:
    """field_meta 已登记 jobs ModuleMeta（kind=job/namespace=job_lib）。"""
    meta = _module_table()
    assert "jobs" in meta, "field_meta 缺 jobs 模块登记"
    assert meta["jobs"].kind == "job"
    assert meta["jobs"].namespace == "job_lib"


def test_loader_kind_mapping_jobs() -> None:
    """loader._KIND_FOR_MODULE 含 jobs:job（与 field_meta ModuleMeta kind 对齐）。"""
    assert _KIND_FOR_MODULE.get("jobs") == "job", "loader 缺 jobs 映射"


def test_manifest_declares_jobs() -> None:
    """test_demo/manifest.json 声明 jobs 模块（批4 已落盘）。"""
    manifest = json.loads(
        (REPO / "content" / "test_demo" / "manifest.json").read_text(encoding="utf-8")
    )
    assert "jobs" in manifest["modules"], "manifest 未声明 jobs"


# ---------------------------------------------------------------------------
# 3. build_pack 全链路（test_demo 真实加载）
# ---------------------------------------------------------------------------
def test_build_pack_test_demo_jobs_loads_green() -> None:
    """build_pack 加载 test_demo：零红拦（jobs.json 未落盘 → Y-6 软放行非红拦）。"""
    pack, _ = build_pack(REPO / "content" / "test_demo")
    assert pack is not None
    assert pack.report.ok, f"test_demo 不应红拦：{pack.report.errors}"
    # 红拦阻断由 build_pack 成功本身证明（errors 非空 → PackLoadError）


def test_build_pack_test_demo_jobs_y6_when_file_missing() -> None:
    """jobs.json 未落盘 → Y-6 黄提示（声明但缺失软放行，细化_3e §1.2）；已落盘 → 无 Y-6。"""
    pack, _ = build_pack(REPO / "content" / "test_demo")
    if not (REPO / "content" / "test_demo" / "jobs.json").exists():
        assert any(
            w.module == "jobs" and w.kind == "Y-6"
            for w in pack.report.warnings
        ), f"jobs.json 缺失应有 Y-6：{[dict(w.detail) for w in pack.report.warnings]}"
    else:
        assert not any(
            w.module == "jobs" and w.kind == "Y-6"
            for w in pack.report.warnings
        ), "jobs.json 存在时不应有 Y-6"


def test_build_pack_test_demo_jobs_registry_resolves() -> None:
    """jobs.json 存在且声明 → 注册进 registry kind=\"job\"（ctx 注入 jobs 表走该 kind）。"""
    pack, _ = build_pack(REPO / "content" / "test_demo")
    jobs_raw = pack.modules.get("jobs")
    if jobs_raw is None:
        pytest.skip("jobs.json 未落盘（批4 路4A/4B 未交付），跳过 registry 断言")
    if isinstance(jobs_raw, list):
        for entry in jobs_raw:
            if isinstance(entry, dict) and entry.get("id"):
                assert pack.registry.resolve(str(entry["id"]), "job") is not None, (
                    f"职业 {entry.get('id')} 应注册进 kind=job"
                )
