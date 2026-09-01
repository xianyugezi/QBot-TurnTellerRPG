"""M13 批4 路4C：job_lib 命名空间 + field_meta 登记验收。

依据：
  - docs/细化/细化_6b_职业库与变换引擎.md §1.1~1.4（jobs.json 顶层 11 字段 /
    growth 9 字段 / transform 段 11 字段 / state_policy 3 字段）、§五（V1~V8 校验）
  - docs/m13_6b摸底.md ⑧（field_meta 无 jobs 模块 / NAMESPACES 无 job_lib /
    loader _KIND_FOR_MODULE 无 jobs → 本路闭合）
  - docs/m13_启动包.md 批4 路4C（NAMESPACES["job_lib"]=("jobs",) + ModuleMeta(jobs)
    + loader _KIND_FOR_MODULE jobs:job + manifest 声明，沿用批1 路1C skill_lib 同款模式）

覆盖：命名空间登记 / 模块登记（顶层 11 + growth 9 + transform 11 + state_policy 3 =
39 契约字段）/ loader 映射 / 注册表一致性 / manifest 声明 / test_demo 加载零红拦 /
泛型校验行为（difficulty 软标注、transform 段必填、state_policy 枚举红拦）。

零 NoneBot；本文件不含 time.sleep 字面量（铁律）。
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

# 细化_6b §1.1~1.4：39 配置字段 = 顶层 11 + growth 9 + transform 段 11 + state_policy 3
JOB_TOP_11 = {
    "id", "name", "difficulty", "playstyle", "recommended_newbie",
    "resource_axes", "mechanic_tags", "weapon_types", "growth", "transform", "description",
}
GROWTH_9 = {"str", "int", "con", "spr", "foc", "agi", "lck", "hp", "mp"}
TRANSFORM_11 = {
    "transform_skill", "transform_to", "duration", "turns", "revert", "cooldown",
    "dispel_reverts", "state_policy", "skill_set", "equip_restrict", "derive_chains",
}
STATE_POLICY_3 = {"combo", "marks", "buff"}


def _jobs_meta():
    table = default_field_meta_table()
    meta = table.module("jobs")
    assert meta is not None, "jobs 模块未登记 field_meta 模块表"
    return meta


# -------------------------------------------------------------------------------------
# 1. 命名空间登记
# -------------------------------------------------------------------------------------
def test_namespace_job_lib_registered() -> None:
    """NAMESPACES 含 job_lib → ("jobs",)（启动包批4 路4C）。"""
    assert "job_lib" in NAMESPACES
    assert NAMESPACES["job_lib"] == ("jobs",)


def test_job_lib_namespace_isolated_from_skill_and_action_lib() -> None:
    """jobs 不并入 skill_lib/action_lib——职业 ID 为存档引用键 + 快照冗余键（细化_6b §1.1 字段 1），
    独立 ID 空间（V1 校验引职业库 ID 空间，跨库重名不影响引用解析）。"""
    assert "jobs" not in NAMESPACES["skill_lib"]
    assert "jobs" not in NAMESPACES["action_lib"]
    assert "jobs" not in NAMESPACES["chain_lib"]
    assert NAMESPACES["job_lib"] == ("jobs",)


def test_namespace_of_jobs_is_job_lib() -> None:
    """FieldMetaTable.namespace_of("jobs") → job_lib（跨模块 ID 唯一作用域）。"""
    table = default_field_meta_table()
    assert table.namespace_of("jobs") == "job_lib"


def test_namespaces_table_carries_job_lib() -> None:
    """default_field_meta_table().namespaces 携带 job_lib（表与常量一致）。"""
    table = default_field_meta_table()
    assert table.namespaces["job_lib"] == ("jobs",)


# -------------------------------------------------------------------------------------
# 2. 模块登记（ModuleMeta jobs）
# -------------------------------------------------------------------------------------
def test_jobs_module_meta_registered() -> None:
    """ModuleMeta(jobs)：entry_type=list、kind=job、namespace=job_lib。"""
    meta = _jobs_meta()
    assert meta.entry_type == "list"
    assert meta.kind == "job"
    assert meta.namespace == "job_lib"
    assert meta.id_field == "id"


def test_jobs_fields_cover_11_top_level_contract_fields() -> None:
    """细化_6b §1.1 顶层 11 字段全登记（字段计数核对 L134：11+9+11+3=39）。"""
    registered = set(_jobs_meta().fields.keys())
    assert JOB_TOP_11 <= registered, f"契约顶层字段缺失：{sorted(JOB_TOP_11 - registered)}"
    assert len(JOB_TOP_11) == 11


def test_jobs_transform_children_cover_11_contract_fields() -> None:
    """细化_6b §1.3 transform 段 11 字段全登记（含 §1.4 state_policy 3 子键）。"""
    children = _jobs_meta().fields["transform"].children
    assert TRANSFORM_11 <= set(children.keys()), (
        f"transform 段字段缺失：{sorted(TRANSFORM_11 - set(children.keys()))}"
    )
    assert len(TRANSFORM_11) == 11
    sp = children["state_policy"].children
    assert set(sp.keys()) == STATE_POLICY_3, f"state_policy 应恰 3 键：{sorted(sp.keys())}"


def test_jobs_growth_children_cover_9_contract_fields() -> None:
    """细化_6b §1.2 growth 九属性全登记（缺省 0 不设 required）。"""
    children = _jobs_meta().fields["growth"].children
    assert set(children.keys()) == GROWTH_9
    for key in GROWTH_9:
        assert children[key].type == "number"
        assert children[key].required is False


def test_jobs_39_contract_field_count() -> None:
    """细化_6b 字段计数核对（L134）：39 配置字段 = jobs 侧 34（顶层 11 + growth 9 +
    transform 11 + state_policy 3）+ 技能/链侧挂点 5（§1.5/§1.6 字段 35-39，归属
    skills.json/skill_chains.json 非 jobs.json）。本表登记 jobs 侧 34 字段；挂点 5
    字段中 job_form/job_restrict 已随 6a 技能库 skills_fields 登记（F16/F17），
    revert_form/derive_only/job_scope 由 6a 路收口（细化_6b 附·未定稿依赖 1/3，
    当前未登记属预期缺口——见下方挂点断言）。"""
    meta = _jobs_meta()
    registered = set(meta.fields.keys())
    count = (
        len(JOB_TOP_11 & registered)
        + len(GROWTH_9 & set(meta.fields["growth"].children.keys()))
        + len(TRANSFORM_11 & set(meta.fields["transform"].children.keys()))
        + len(
            STATE_POLICY_3
            & set(meta.fields["transform"].children["state_policy"].children.keys())
        )
    )
    assert count == 34, f"jobs 侧 34 契约字段核对失败：{count}"
    # 挂点 5 字段（§1.5 字段 35-38 + §1.6 字段 39）：job_form/job_restrict 已随 6a
    # 登记于 skills_fields（F16/F17）；revert_form/derive_only/job_scope 归 6a 路收口
    # （细化_6b 附·未定稿依赖 1/3）——当前未登记属预期缺口，非本路（4C 登记 jobs 侧）职责。
    skills_meta = default_field_meta_table().module("skills")
    assert skills_meta is not None
    sf = skills_meta.fields
    assert "job_form" in sf and "job_restrict" in sf, "6a skills_fields 应已登记 F16/F17"
    assert "revert_form" not in sf and "derive_only" not in sf, (
        "revert_form/derive_only 归 6a 路收口（当前未登记属预期缺口）"
    )
    chains_meta = default_field_meta_table().module("skill_chains")
    assert chains_meta is not None
    assert "job_scope" not in chains_meta.fields, (
        "job_scope 归 6a 路收口（当前未登记属预期缺口）"
    )


def test_jobs_top_level_required_fields() -> None:
    """细化_6b §1.1 必填字段登记口径：id 必填（F_ID）；name/difficulty/playstyle/
    recommended_newbie 的必填判定归 4B 专项（对齐 skills_fields 宽松口径——模块内
    必填缺失 R-5 由专项校验器全权，防泛型误拦既有内容包）；transform 段为可选挂点。"""
    f = _jobs_meta().fields
    assert f["id"].required is True
    # 专项全权字段保持宽松登记（不设 required），契约必填性由 4B validate_jobs 判定
    for key in ("name", "difficulty", "playstyle", "recommended_newbie"):
        assert f[key].required is False, f"{key} 必填判定应归 4B 专项（宽松登记）"
    assert f["transform"].required is False
    assert f["description"].required is False


def test_jobs_difficulty_soft_label() -> None:
    """细化_6b §1.1 字段 3：difficulty 软标注——只建议不拦截（soft_label 永不红拦，Y-5）。"""
    assert _jobs_meta().fields["difficulty"].soft_label is True


def test_jobs_transform_nested_required_fields() -> None:
    """细化_6b §1.3 必填 7 字段（21/22/23/25/26/28/29）登记在 transform 子对象 required。"""
    children = _jobs_meta().fields["transform"].children
    for key in ("transform_skill", "transform_to", "duration", "revert",
                "cooldown", "state_policy", "skill_set"):
        assert children[key].required is True, f"transform.{key} 应为必填"
    # 条件必填（duration=turns）与可空字段不设 required（判定归 4B 专项）
    for key in ("turns", "dispel_reverts", "equip_restrict", "derive_chains"):
        assert children[key].required is False, f"transform.{key} 不应设 required"


def test_jobs_duration_enum_and_state_policy_enums() -> None:
    """细化_6b §1.3 字段 23 duration ∈ {turns, battle}；§1.4 state_policy 三键 ∈ {clear, keep}
    （枚举外值 → 泛型 R-1 红拦，V4/V5 判定基底；默认值随契约 L113-115）。"""
    children = _jobs_meta().fields["transform"].children
    assert children["duration"].enum == ("turns", "battle")
    sp = children["state_policy"].children
    assert sp["combo"].enum == ("clear", "keep") and sp["combo"].default == "clear"
    assert sp["marks"].enum == ("keep", "clear") and sp["marks"].default == "keep"
    assert sp["buff"].enum == ("keep", "clear") and sp["buff"].default == "keep"


def test_jobs_recommended_newbie_bool_and_growth_number_ranges() -> None:
    """字段类型口径抽查：recommended_newbie=bool；growth 九键 number 区间 [0,10]
    （白值增量口径）。"""
    f = _jobs_meta().fields
    assert f["recommended_newbie"].type == "bool"
    assert f["playstyle"].type == "str"
    assert f["resource_axes"].type == "list"
    for key in GROWTH_9:
        assert f["growth"].children[key].range_min == 0


# -------------------------------------------------------------------------------------
# 3. loader 映射
# -------------------------------------------------------------------------------------
def test_loader_kind_for_module_jobs() -> None:
    """loader _KIND_FOR_MODULE["jobs"] == "job"（摸底⑧ 缺口闭合，kind 对齐 ModuleMeta）。"""
    assert _KIND_FOR_MODULE.get("jobs") == "job"


def test_jobs_not_in_fixed_register_order() -> None:
    """jobs 不入固定优先序——依赖的 effects/statuses/marks/action 固定序先注册，
    jobs 由 _ordered_declared 按声明顺序兜底（对齐 skills 口径）。"""
    assert "jobs" not in FIXED_REGISTER_ORDER
    assert "effects" in FIXED_REGISTER_ORDER
    assert "action" in FIXED_REGISTER_ORDER


def test_loader_jobs_kind_matches_field_meta_jobs_kind() -> None:
    """loader kind 与 field_meta ModuleMeta kind 对齐（同一注册表 kind="job"）。"""
    assert _KIND_FOR_MODULE["jobs"] == _jobs_meta().kind


# -------------------------------------------------------------------------------------
# 4. 注册表一致性（loader ⊆ field_meta；manifest 声明 ⊆ field_meta）
# -------------------------------------------------------------------------------------
def test_register_table_consistency_zero_gap_with_jobs() -> None:
    """check_register_table_consistency 零缺口（FIXED_REGISTER_ORDER ∪
    _KIND_FOR_MODULE ⊆ 模块表）。"""
    missing = check_register_table_consistency()
    assert missing == [], f"loader 登记应 ⊆ field_meta：{missing}"


def test_manifest_jobs_declared_registered() -> None:
    """test_demo manifest 声明的 jobs ∈ field_meta 模块表（WIR-13 对照第二部分）。"""
    manifest_path = REPO / "content" / "test_demo" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "jobs" in manifest["modules"], "test_demo manifest 应声明 jobs 模块"
    missing = [
        m for m in check_manifest_modules_registered(manifest["modules"]) if m != "templates"
    ]
    assert missing == [], f"manifest 声明模块应 ⊆ field_meta（templates 常驻豁免）：{missing}"


# -------------------------------------------------------------------------------------
# 5. 泛型校验行为（登记表驱动，V1~V8 深校验归 4B 专项）
# -------------------------------------------------------------------------------------
def _write_pack(tmp_path: Path, modules: dict) -> Path:
    manifest = {
        "name": "t", "version": "1.0.0", "schema_version": 1,
        "author": "t", "modules": list(modules.keys()),
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    for name, data in modules.items():
        (tmp_path / f"{name}.json").write_text(json.dumps(data), encoding="utf-8")
    return tmp_path


def test_jobs_legal_entry_loads_green(tmp_path: Path) -> None:
    """合法职业条目（含完整 transform 段）加载零红拦。"""
    from qbot_rpg.content.loader import build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战输出",
            "recommended_newbie": True,
            "resource_axes": ["mp"],
            "growth": {"str": 2.0, "con": 1.5},
            "transform": {
                "transform_skill": "berserk", "transform_to": "berserker_form",
                "duration": "turns", "turns": 4, "revert": True, "cooldown": 5,
                "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        }],
    })
    pack, _ = build_pack(pack_dir)
    assert pack.report.ok, f"合法职业不应红拦：{pack.report.errors}"


def test_jobs_transform_required_missing_red_blocks(tmp_path: Path) -> None:
    """transform 段缺必填子字段（transform_skill）→ 泛型 R-5 required_missing 红拦（V2 基底）。"""
    from qbot_rpg.content.loader import PackLoadError, build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战", "recommended_newbie": True,
            "transform": {
                "transform_to": "berserker_form", "duration": "turns",
                "revert": True, "cooldown": 5,
                "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        }],
    })
    with pytest.raises(PackLoadError) as ei:
        build_pack(pack_dir)
    assert any(
        e.kind == "R-5" and e.detail.get("rule") == "required_missing"
        and e.detail.get("name") == "transform_skill"
        for e in ei.value.errors
    ), (
        f"应红拦 transform.transform_skill 缺失："
        f"{[(e.kind, dict(e.detail)) for e in ei.value.errors]}"
    )


def test_jobs_state_policy_enum_out_of_range_red_blocks(tmp_path: Path) -> None:
    """state_policy.combo="shuffle"（枚举外值）→ 泛型 R-1 enum 红拦（V5 判定基底）。"""
    from qbot_rpg.content.loader import PackLoadError, build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战", "recommended_newbie": True,
            "transform": {
                "transform_skill": "berserk", "transform_to": "berserker_form",
                "duration": "turns", "revert": True, "cooldown": 5,
                "state_policy": {"combo": "shuffle", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        }],
    })
    with pytest.raises(PackLoadError) as ei:
        build_pack(pack_dir)
    assert any(
        e.kind == "R-1" and e.detail.get("rule") == "enum"
        and e.detail.get("got") == "shuffle"
        for e in ei.value.errors
    ), f"应红拦 state_policy.combo=shuffle：{[(e.kind, dict(e.detail)) for e in ei.value.errors]}"


def test_jobs_difficulty_soft_label_never_red_blocks(tmp_path: Path) -> None:
    """difficulty="expert"（契约枚举外值但软标注）→ 零红拦（只建议不拦截，Y-5）。"""
    from qbot_rpg.content.loader import build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "expert", "playstyle": "近战", "recommended_newbie": True,
        }],
    })
    pack, _ = build_pack(pack_dir)
    assert pack.report.ok, f"difficulty 软标注不应红拦：{pack.report.errors}"


def test_jobs_battle_revert_dead_config_not_red_blocked_by_generic(tmp_path: Path) -> None:
    """V4 矛盾（duration=battle + revert=true）深判定归 4B 专项全权——泛型登记表
    不重复红拦（专项 V4 落盘前该包可加载，属既有 6b 摸底⑧ 缺口范围，非本路回归）。
    本路保证的泛型兜底：duration/state_policy 枚举外值 → R-1 红拦（见下方两用例）。"""
    from qbot_rpg.content.loader import build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战", "recommended_newbie": True,
            "transform": {
                "transform_skill": "berserk", "transform_to": "berserker_form",
                "duration": "battle", "revert": True, "cooldown": 5,
                "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        }],
    })
    pack, _ = build_pack(pack_dir)
    assert pack.report.ok, (
        f"V4 矛盾深判定未接线前应可加载（专项全权，非泛型责任）：{pack.report.errors}"
    )


def test_jobs_battle_revert_dead_config_red_blocks_via_duration_enum(tmp_path: Path) -> None:
    """V4 矛盾另一判定基底：duration 枚举外值（"forever"）→ 泛型 R-1 enum 红拦
    （泛型不误伤、不重复红拦——矛盾深判定由 4B 专项全权，本表仅兜底枚举值域）。"""
    from qbot_rpg.content.loader import PackLoadError, build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战", "recommended_newbie": True,
            "transform": {
                "transform_skill": "berserk", "transform_to": "berserker_form",
                "duration": "forever", "revert": True, "cooldown": 5,
                "state_policy": {"combo": "clear", "marks": "keep", "buff": "keep"},
                "skill_set": "transform_skills",
            },
        }],
    })
    with pytest.raises(PackLoadError) as ei:
        build_pack(pack_dir)
    assert any(
        e.kind == "R-1" and e.detail.get("rule") == "enum"
        and e.detail.get("got") == "forever"
        for e in ei.value.errors
    ), f"应红拦 duration=forever：{[(e.kind, dict(e.detail)) for e in ei.value.errors]}"


def test_jobs_growth_unknown_keys_passthrough(tmp_path: Path) -> None:
    """growth 未知子键（x_ 前缀）→ §2.3 默认放行不误拦（对齐既有模块口径）。"""
    from qbot_rpg.content.loader import build_pack

    pack_dir = _write_pack(tmp_path, {
        "jobs": [{
            "id": "warrior", "name": "战士",
            "difficulty": "simple", "playstyle": "近战", "recommended_newbie": True,
            "growth": {"x_future_growth": 99},
        }],
    })
    pack, _ = build_pack(pack_dir)
    assert pack.report.ok, f"未知子键应放行：{pack.report.errors}"


# -------------------------------------------------------------------------------------
# 6. test_demo 端到端：加载零红拦 + registry 挂载
# -------------------------------------------------------------------------------------
def test_test_demo_pack_loads_green_with_jobs_declared() -> None:
    """test_demo 声明 jobs 后加载零红拦；jobs.json 未落盘 → Y-6 黄提示继续（不红拦）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    assert pack.report.ok, f"test_demo 不应红拦：{pack.report.errors}"
    assert pack.report.count_errors == 0
    assert "jobs" in pack.manifest.modules


def test_test_demo_jobs_y6_warning_when_file_missing() -> None:
    """jobs.json 缺失 → Y-6 黄提示（声明但缺失软放行，细化_3e §1.2），非红拦。"""
    from qbot_rpg.content.loader import build_pack

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


def test_test_demo_registry_job_kind_resolves_after_load() -> None:
    """jobs.json 存在且声明 → 注册进 registry kind="job"（ctx 注入 jobs 表走该 kind，批5 接线）。"""
    from qbot_rpg.content.loader import build_pack

    pack, _ = build_pack(REPO / "content" / "test_demo")
    jobs_raw = pack.modules.get("jobs")
    if jobs_raw is None:
        pytest.skip("jobs.json 未落盘（路4A/4B 未交付），跳过 registry 断言")
    if isinstance(jobs_raw, list):
        for entry in jobs_raw:
            if isinstance(entry, dict) and entry.get("id"):
                assert pack.registry.resolve(str(entry["id"]), "job") is not None, (
                    f"职业 {entry.get('id')} 应注册进 kind=job"
                )
