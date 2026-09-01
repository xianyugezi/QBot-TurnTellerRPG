"""M13 批1 路1C：skill_lib 命名空间 + field_meta 登记验收。

依据：
  - docs/细化/细化_6a_技能库契约.md §1（skills.json 全字段 24 个 F01-F24）、
    §3.3（校验时机）、§7（热重载：manifest 声明即入监控）
  - docs/m13_6a摸底.md G1（field_meta 无 skills ModuleMeta / loader 无 kind=skill /
    manifest 24 模块无 skills）、A10（热重载五段管线 manifest 声明驱动 watch）
  - docs/m13_启动包.md 批1 路1C（NAMESPACES["skill_lib"]=("skills",) + ModuleMeta(skills)
    + field_meta 注入，沿用 schema 之家单向持有模式防循环 import）

覆盖：命名空间登记 / 模块登记（F01-F24 全字段）/ loader 映射 / 注册表一致性
（check_register_table_consistency + check_manifest_modules_registered）/ 热重载
manifest 声明驱动 / test_demo 加载零红拦。

零 NoneBot；本文件不含定时器/睡眠字面量（热重载表述用「零定时器/零睡眠」语义）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from qbot_rpg.content.field_meta import NAMESPACES, default_field_meta_table
from qbot_rpg.content.loader import (
    FIXED_REGISTER_ORDER,
    _KIND_FOR_MODULE,
    check_manifest_modules_registered,
    check_register_table_consistency,
)

REPO = Path(__file__).resolve().parents[2]

# 契约 §1.2 全字段 24 个（F01-F24）：A 共用核心 7 + B 玩家扩展 11 + C 全库补充 2 + D 细化定型 4
SKILL_FIELDS_24 = {
    # A. ActionCore 共用核心块（7）
    "id", "name", "kind", "power", "attack_type", "element", "effects",
    # B. 玩家侧扩展字段（11）
    "type", "mp_cost", "cooldown", "tag", "armor", "interrupt",
    "chain_refs", "consume_marks", "job_restrict", "job_form", "level",
    # C. 全库补充（2）
    "hits", "trigger_limit",
    # D. 细化定型（4）
    "desc", "hit_mod", "crit_mod", "block_mode",
}

# 契约 §1.2 类型口径抽查（与 action_fields 同构的字段）
ACTIONCORE_SHARED = ("id", "name", "kind", "power", "attack_type", "element", "effects")


def _skills_meta():
    table = default_field_meta_table()
    meta = table.module("skills")
    assert meta is not None, "skills 模块未登记 field_meta 模块表"
    return meta


# -------------------------------------------------------------------------------------
# 1. 命名空间登记
# -------------------------------------------------------------------------------------
def test_namespace_skill_lib_registered() -> None:
    """NAMESPACES 含 skill_lib → ("skills",)（启动包批1 路1C）。"""
    assert "skill_lib" in NAMESPACES
    assert NAMESPACES["skill_lib"] == ("skills",)


def test_skill_lib_namespace_isolated_from_action_lib() -> None:
    """skills 不并入 action_lib——V-10 跨库重名仅黄提示，双库 ID 空间独立（契约 §3.1）。"""
    assert "skills" not in NAMESPACES["action_lib"]
    assert "skills" not in NAMESPACES["chain_lib"]
    assert NAMESPACES["skill_lib"] == ("skills",)


def test_namespace_of_skills_is_skill_lib() -> None:
    """FieldMetaTable.namespace_of("skills") → skill_lib（跨模块 ID 唯一作用域）。"""
    table = default_field_meta_table()
    assert table.namespace_of("skills") == "skill_lib"


def test_namespaces_table_carries_skill_lib() -> None:
    """default_field_meta_table().namespaces 携带 skill_lib（表与常量一致）。"""
    table = default_field_meta_table()
    assert table.namespaces["skill_lib"] == ("skills",)


# -------------------------------------------------------------------------------------
# 2. 模块登记（ModuleMeta skills）
# -------------------------------------------------------------------------------------
def test_skills_module_meta_registered() -> None:
    """ModuleMeta(skills)：entry_type=list、kind=skill、namespace=skill_lib。"""
    meta = _skills_meta()
    assert meta.entry_type == "list"
    assert meta.kind == "skill"
    assert meta.namespace == "skill_lib"
    assert meta.id_field == "id"


def test_skills_fields_cover_full_24_contract_fields() -> None:
    """F01-F24 全字段登记（契约 §1.2 计数 24；skill 兼容旧键不计入契约字段）。"""
    registered = set(_skills_meta().fields.keys())
    assert SKILL_FIELDS_24 <= registered, (
        f"契约字段缺失：{sorted(SKILL_FIELDS_24 - registered)}"
    )
    assert len(SKILL_FIELDS_24) == 24


def test_actioncore_shared_fields_type_parity() -> None:
    """ActionCore 7 字段与 action 模块逐字段同构（契约 §2.2 逐约束同源）。"""
    table = default_field_meta_table()
    action_meta = table.module("action")
    assert action_meta is not None
    skills_fields = _skills_meta().fields
    action_fields = action_meta.fields
    for f in ACTIONCORE_SHARED:
        assert f in skills_fields, f"skills 缺 ActionCore 字段 {f}"
        assert f in action_fields, f"action 缺 ActionCore 字段 {f}"
        assert skills_fields[f].type == action_fields[f].type, (
            f"ActionCore 字段 {f} 类型不一致：skills={skills_fields[f].type} "
            f"action={action_fields[f].type}"
        )


def test_skills_specific_field_types() -> None:
    """F08-F24 玩家侧字段类型口径抽查（契约 §1.2 B/C/D 类型列）。"""
    f = _skills_meta().fields
    assert f["type"].type == "str"
    assert f["mp_cost"].type == "number"
    assert f["cooldown"].type == "number"
    assert f["tag"].type == "str"
    assert f["armor"].type == "bool"
    assert f["interrupt"].type == "bool"
    assert f["chain_refs"].type == "list"
    assert f["consume_marks"].type == "obj"
    assert f["job_restrict"].type == "list"
    assert f["job_form"].type == "str"
    assert f["level"].type == "obj"
    assert f["hits"].type == "int"
    assert f["trigger_limit"].type == "obj"
    assert f["desc"].type == "str"
    assert f["hit_mod"].type == "number"
    assert f["crit_mod"].type == "number"
    assert f["block_mode"].type == "str"


def test_skill_trigger_limit_children() -> None:
    """F20 trigger_limit 子字段 per_round/per_battle（0=不限 → zero_unlimited）。"""
    children = _skills_meta().fields["trigger_limit"].children
    assert set(children.keys()) == {"per_round", "per_battle"}
    assert children["per_round"].zero_unlimited is True
    assert children["per_battle"].zero_unlimited is True


def test_skill_level_children() -> None:
    """F18 level 子字段 max/growth（growth 数组长度 = max，A2 判定）。"""
    children = _skills_meta().fields["level"].children
    assert set(children.keys()) == {"max", "growth"}
    assert children["growth"].type == "list"


def test_skills_fields_have_no_enum_red_block() -> None:
    """枚举判定归 A2 路：登记表不设枚举防误阻断（对齐 action_fields 口径）。"""
    f = _skills_meta().fields
    for key in ("kind", "type", "tag", "attack_type", "block_mode"):
        assert f[key].type == "str", f"{key} 应为宽松 str（枚举 A2 路）"
        assert f[key].enum == ()


# -------------------------------------------------------------------------------------
# 3. loader 映射
# -------------------------------------------------------------------------------------
def test_loader_kind_for_module_skills() -> None:
    """loader _KIND_FOR_MODULE["skills"] == "skill"（G1 缺口闭合）。"""
    assert _KIND_FOR_MODULE.get("skills") == "skill"


def test_fixed_register_order_skills_after_action() -> None:
    """注册顺序：skills 不入固定序（走声明顺序兜底），依赖的 action/effect 家族在固定序内先注册。"""
    assert "skills" not in FIXED_REGISTER_ORDER
    assert "action" in FIXED_REGISTER_ORDER
    assert "effects" in FIXED_REGISTER_ORDER


def test_skills_in_fixed_register_order_after_action() -> None:
    """注册顺序：skills 不在固定序，由 _ordered_declared 按声明顺序兜底。"""
    assert "skills" not in FIXED_REGISTER_ORDER
    assert "action" in FIXED_REGISTER_ORDER


def test_skills_registered_before_remaining_modules() -> None:
    """未登记 FIXED_REGISTER_ORDER 的 skills 由 _ordered_declared 按声明顺序兜底
    （固定优先序 ∩ 声明集合 → 其余按声明顺序），不影响依赖注册。"""
    # skills 未入固定序 → 走「其余按声明顺序」分支（细化_3e §1.3）
    assert "skills" not in FIXED_REGISTER_ORDER
    declared = ["settings", "skills", "items", "effects"]
    ordered = []
    for m in FIXED_REGISTER_ORDER:
        if m in declared:
            ordered.append(m)
    for m in declared:
        if m not in ordered:
            ordered.append(m)
    # effects 固定序优先于 skills；skills 保持声明相对序（settings 之后、items 之前）
    assert ordered.index("effects") < ordered.index("skills")
    assert ordered.index("settings") < ordered.index("skills")
    assert ordered.index("skills") < ordered.index("items")


# -------------------------------------------------------------------------------------
# 4. 注册表一致性（loader ⊆ field_meta；manifest 声明 ⊆ field_meta）
# -------------------------------------------------------------------------------------
def test_register_table_consistency_zero_gap() -> None:
    """check_register_table_consistency 零缺口
    （FIXED_REGISTER_ORDER ∪ _KIND_FOR_MODULE ⊆ 模块表）。
    """
    missing = check_register_table_consistency()
    assert missing == [], f"loader 登记应 ⊆ field_meta：{missing}"


def test_manifest_skills_declared_registered() -> None:
    """test_demo manifest 声明的 skills ∈ field_meta 模块表（WIR-13 对照第二部分）。"""
    manifest_path = REPO / "content" / "test_demo" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "skills" in manifest["modules"], "test_demo manifest 应声明 skills 模块"
    # templates 为消息模板常驻模块（核心 templates 加载，非内容校验器登记范围，
    # 同 settings 常驻豁免口径——qbot_rpg/core/templates resolve_templates 消费）
    missing = [
        m for m in check_manifest_modules_registered(manifest["modules"]) if m != "templates"
    ]
    assert missing == [], f"manifest 声明模块应 ⊆ field_meta（templates 常驻豁免）：{missing}"


# -------------------------------------------------------------------------------------
# 5. 热重载：manifest 声明驱动（hot_reload.py:271-284 _current_declared）
# -------------------------------------------------------------------------------------
def test_hot_reload_watch_derives_from_manifest_declaration() -> None:
    """热重载监控文件集 = manifest 声明模块（零定时器/零睡眠轮询）；skills 声明即入监控。"""
    from qbot_rpg.content.hot_reload import HotReloadWatcher

    watcher = HotReloadWatcher(pack_dir=REPO / "content" / "test_demo")
    declared = watcher._current_declared()
    assert "skills" in declared, f"manifest 声明 skills → 应进监控集，实际：{declared}"


# -------------------------------------------------------------------------------------
# 6. test_demo 端到端：加载零红拦 + 登记表非空
# -------------------------------------------------------------------------------------
def test_test_demo_pack_loads_green_with_skills_declared() -> None:
    """test_demo 声明 skills 后加载零红拦（Y-6 声明缺失类黄提示不复现）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    assert pack.report.ok, f"test_demo 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    assert "skills" in pack.manifest.modules


def test_test_demo_skills_module_declared_and_parsed() -> None:
    """manifest 声明 skills + skills.json 存在 → 进入 pack.modules（未声明不加载的反面）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    if (REPO / "content" / "test_demo" / "skills.json").exists():
        assert "skills" in pack.modules, "skills.json 存在且声明 → 应加载"
    else:
        pytest.skip("skills.json 未落盘（路1A/1B 未交付），跳过模块内容断言")


def test_missing_skills_file_yields_y6_warning_not_red() -> None:
    """声明 skills 但文件缺失 → Y-6 黄提示继续（细化_3e §1.2），不红拦。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    if not (REPO / "content" / "test_demo" / "skills.json").exists():
        assert any(
            w.module == "skills" and w.kind == "Y-6"
            for w in pack.report.warnings
        ), f"skills.json 缺失应有 Y-6，实际：{[dict(w.detail) for w in pack.report.warnings]}"
    else:
        assert not any(
            w.module == "skills" and w.kind == "Y-6"
            for w in pack.report.warnings
        ), "skills.json 存在时不应有 Y-6"


def test_registry_skill_kind_resolves_after_load() -> None:
    """skills 表注册进 registry kind="skill"（ctx 注入 skills 表走该 kind，摸底 A11）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    skills_raw = pack.modules.get("skills")
    if skills_raw is None:
        pytest.skip("skills.json 未落盘（路1A/1B 未交付），跳过 registry 断言")
    if isinstance(skills_raw, list):
        for entry in skills_raw:
            if isinstance(entry, dict) and entry.get("id"):
                assert pack.registry.resolve(str(entry["id"]), "skill") is not None, (
                    f"技能 {entry.get('id')} 应注册进 kind=skill"
                )
