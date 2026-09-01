"""6a 技能库校验器装配单测（tests/unit/test_skill_validator_wiring.py · M13 批2 路2C）。

覆盖：
  - validator._check_module 对 skills 模块分派 validate_skills（红拦收集）
  - 合法 skills 条目 → 零红拦
  - build_pack 全链路：test_demo 含 skills 模块加载成功（零红拦）
  - field_meta 模块登记 + loader 映射 + manifest 声明一致性

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性。
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict


from qbot_rpg.content.field_meta import _module_table, default_field_meta_table
from qbot_rpg.content.loader import _KIND_FOR_MODULE, build_pack
from qbot_rpg.content.validator import _Checker

REPO = Path(__file__).resolve().parents[2]


# ---------------------------------------------------------------------------
# validator 分派
# ---------------------------------------------------------------------------
def test_check_module_dispatches_skills() -> None:
    """_check_module 对 skills 模块分派 validate_skills（坏条目 → 红拦收集）。"""
    modules: Dict[str, object] = {
        "skills": [
            {"id": "x", "name": "坏技能", "type": "active", "kind": "damage",
             "effects": [{"effect": "ghost_missing"}]},
        ],
        "effects": [{"id": "real_eff"}],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("skills")
    rules = {e.detail.get("rule", "") for e in checker.errors}
    assert "V1_effect_ref" in rules, f"V-1 红拦应被收集，got {rules}"


def test_check_module_legal_skills_zero_red() -> None:
    """合法 skills 条目 → _check_module 零红拦。"""
    modules: Dict[str, object] = {
        "skills": [
            {"id": "basic_attack", "name": "普攻", "type": "basic", "kind": "damage",
             "power": 100, "effects": [{"effect": "real_eff"}]},
            {"id": "active_1", "name": "技能", "type": "active", "kind": "damage",
             "power": 120, "effects": [{"effect": "real_eff"}]},
        ],
        "effects": [{"id": "real_eff"}],
    }
    meta = default_field_meta_table()
    checker = _Checker(modules, meta)
    checker._check_module("skills")
    assert checker.errors == [], f"合法 skills 应零红拦，got {checker.errors}"


# ---------------------------------------------------------------------------
# 登记一致性
# ---------------------------------------------------------------------------
def test_field_meta_skills_module_registered() -> None:
    """field_meta 已登记 skills ModuleMeta（kind=skill/namespace=skill_lib）。"""
    meta = _module_table()
    assert "skills" in meta, "field_meta 缺 skills 模块登记"
    assert meta["skills"].kind == "skill"
    assert meta["skills"].namespace == "skill_lib"


def test_loader_kind_mapping_skills() -> None:
    """loader._KIND_FOR_MODULE 含 skills:skill。"""
    assert _KIND_FOR_MODULE.get("skills") == "skill", "loader 缺 skills 映射"


def test_manifest_declares_skills() -> None:
    """test_demo/manifest.json 声明 skills 模块。"""
    manifest = _load_manifest()
    assert "skills" in manifest["modules"], "manifest 未声明 skills"


def _load_manifest() -> dict:
    import json

    p = REPO / "content" / "test_demo" / "manifest.json"
    return json.loads(p.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# build_pack 全链路（test_demo 真实加载）
# ---------------------------------------------------------------------------
def test_build_pack_test_demo_loads_skills() -> None:
    """build_pack 加载 test_demo：skills 模块存在且零红拦。"""
    pack, _changed = build_pack(REPO / "content" / "test_demo")
    assert pack is not None
    # skills 模块被 registry 索引（kind=skill → all_ids("skill") 非空）
    assert len(pack.registry.all_ids("skill")) >= 4, \
        f"skills 应至少 4 条，got {pack.registry.all_ids('skill')}"
    # 零红拦由 build_pack 成功本身证明（红拦会抛 PackLoadError）
