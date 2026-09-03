"""M10 钓鱼数据层 · 路 0C：fishing.json 专项校验器测试（V1-V6 + W1）。

文件名：test_fishing_models.py
创建时间：2026-08-31
作者：Hermes 子agent-0C（M10 钓鱼实现组路0C：并发同仓，仅新建本文件 +
qbot_rpg/content/fishing_models.py，独占 loader.py/field_meta.py 登记行）

依据：docs/m10_shared_contract.md §三（校验器 V1-V4 硬+W1 黄，V5/V6 扩展）+
docs/细化/细化_2c1a_鱼种数据与冠级.md §五（校验器规则表）/ §六（验收
TC-18~22b：V1-V4 各有独立失败用例 + W1 黄不阻断 + V5/V6 扩展 + legal 零红）。
测试目标：qbot_rpg.content.fishing_models.{validate_fishing, fishing_module_meta,
fishing_settings_meta, FishDef, KingEventDef}。

测试口径（对齐 test_forge_models.py / test_dungeon_schema.py）：
  - validate_fishing 为 (modules, report) 纯函数；report 鸭子类型（_Report 收集器 +
    dict {"errors","warnings"} 形态 + 真实 validator._Checker 收口兼容测试）。
  - 断言级别：errors=红拦（加载失败）/ warnings=黄提示（不阻断）。
  - 夹具基准行 = 共享契约 §二 基准行（silver_carp 银鳞鲤，全字段）。
  - legal 包零红：读 tests/fixtures/packs/legal/ 现有 settings.json + maps.json
    （fishing.json 由路0B 并行新建，本路零共享文件——若已落盘则一并加载，否则
    以契约基准行构造 legal 形态，保证零红断言确定性）。

铁律：零 NoneBot import；纯函数确定性；零定时器/零睡眠（不引入实时计时调用）；
不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Mapping, cast

from qbot_rpg.content.fishing_models import (
    FISH_MODES,
    FishDef,
    KingEventDef,
    fishing_module_meta,
    fishing_settings_meta,
    validate_fishing,
)
from qbot_rpg.content.validator import _Checker

PACKS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "packs"
LEGAL_DIR = PACKS_DIR / "legal"


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_fishing 收集器（鸭子类型：error/warning 与 _Checker._err/_warn 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _legal_fish() -> list:
    """合法鱼种池：基准行 silver_carp（共享契约 §二）+ 一条无 king 的普通鱼。

    spots 引用 test_demo 现有采集点 id（gp_moon_grass 等）——maps 模块存在含
    gather_points 时零红（V6 引用存在）；legal maps 无 gather_points 时宽松跳过。
    """
    return [
        {
            "id": "silver_carp", "name": "银鳞鲤", "rarity": "normal",
            "size_min": 10.0, "size_max": 60.0, "weight_min": 0.3, "weight_max": 5.0,
            "seasons": ["spring", "summer", "autumn"],
            "periods": ["dawn", "noon", "dusk"],
            "hours": ["00:00-24:00"],
            "spots": ["gp_moon_grass"],
            "preferred_bait": ["饵_蚯蚓"],
            "codex_text": {"desc": "鳞片泛银光的鲤，黄昏时最活跃。", "unit": "cm-kg",
                           "best_mask": "{name} · 最大 {best_size}cm/{best_weight}kg"},
            "king": None,
        },
        {
            "id": "river_loach", "name": "河泥鳅", "rarity": "rare",
            "size_min": 5.0, "size_max": 20.0, "weight_min": 0.1, "weight_max": 0.8,
            "seasons": [], "periods": [],
            "hours": ["06:00-18:00"],
            "spots": ["gp_star_iron", "gp_ghost_moss"],
            "preferred_bait": [],
            "codex_text": None,
            "king": None,
        },
    ]


def _legal_settings() -> dict:
    """合法 settings 模块（含 fishing 段：full 模式 + 5 档饵 + 合法阈值）。"""
    return {
        "fishing": {
            "mode": "full",
            "bait_ids": ["饵_蚯蚓", "饵_红虫", "饵_米粒", "饵_螺肉", "饵_虾仁"],
            "bait_bonus": {"rare": 8, "gold": 2},
            "rod_full_bonus": {"rare": 4, "gold": 2},
            "crown_thresholds": {"reverse": 5, "silver": 85, "gold": 95},
            "wait_sec": {"min": 300, "max": 900},
            "daily_limit": 20,
            "energy": {"enabled": False},
            "king_event": {"enabled": True, "window_daily": 2, "chance": 0.3},
        }
    }


def _legal_maps() -> list:
    """合法 maps 模块（含 gather_points 采集点 id：gp_moon_grass 等）。"""
    return [
        {"id": "gloom_forest", "name": "幽光林地", "gather_points": [
            {"id": "gp_moon_grass", "item": "moon_grass", "rarity": "normal"}]},
        {"id": "abandoned_mine", "name": "废弃矿坑", "gather_points": [
            {"id": "gp_star_iron", "item": "star_iron", "rarity": "rare"}]},
        {"id": "hidden_grove", "name": "秘境林", "gather_points": [
            {"id": "gp_ghost_moss", "item": "ghost_moss", "rarity": "rare"}]},
    ]


def _legal_modules(**overrides) -> dict:
    """标准模块上下文：完整合法包（fishing + settings + maps）。零红零黄冒烟基准。"""
    modules: Dict[str, object] = {
        "fishing": {"schema_version": "1.0", "species": _legal_fish(), "king": []},
        "settings": _legal_settings(),
        "maps": _legal_maps(),
    }
    modules.update(overrides)
    return modules


def _run(modules: Mapping[str, object]) -> _Report:
    """跑 validate_fishing，返回收集器。"""
    report = _Report()
    validate_fishing(modules, report)
    return report


def _rules(report: _Report, level: str) -> set:
    """收集指定级别（errors/warnings）的 rule 名集合。"""
    return {e["detail"].get("rule") for e in getattr(report, level)}


# ---------------------------------------------------------------------------
# 合法冒烟 / Def 类 / meta 工厂
# ---------------------------------------------------------------------------
def test_tc01_legal_full_zero_red_zero_yellow() -> None:
    """合法全量包（fishing+settings+maps）零红零黄（TC-01 基准）。"""
    report = _run(_legal_modules())
    assert report.errors == [], f"合法包应零红，got {report.errors}"
    assert report.warnings == [], f"合法包应零黄，got {report.warnings}"


def test_def_accessors() -> None:
    """FishDef/KingEventDef 访问器冒烟（共享契约 §二 F-01~F-14 / 细化 §三 K-01~K-07）。"""
    fish = cast(FishDef, FishDef.from_entry(_legal_fish()[0]))
    assert fish.id == "silver_carp"
    assert fish.name == "银鳞鲤"
    assert fish.rarity == "normal"
    assert fish.size_min == 10.0 and fish.size_max == 60.0
    assert fish.weight_min == 0.3 and fish.weight_max == 5.0
    assert fish.seasons == ("spring", "summer", "autumn")
    assert fish.periods == ("dawn", "noon", "dusk")
    assert fish.hours == ("00:00-24:00",)
    assert fish.spots == ("gp_moon_grass",)
    assert fish.preferred_bait == ("饵_蚯蚓",)
    assert fish.codex_text.get("unit") == "cm-kg"
    assert fish.king is None

    king = cast(KingEventDef, KingEventDef.from_entry(
        {"id": "king_carp", "species_id": "silver_carp", "enemy_id": "boss_king_carp",
         "hint": "金闪", "window_daily": 2, "chance": 0.3, "enabled": True}))
    assert king.id == "king_carp"
    assert king.species_id == "silver_carp"
    assert king.enemy_id == "boss_king_carp"
    assert king.hint == "金闪"
    assert king.window_daily == 2
    assert king.chance == 0.3
    assert king.enabled is True


def test_fishing_module_meta_entry_type_object() -> None:
    """fishing_module_meta()：entry_type=object（fishing.json 顶层 obj 非 list）。

    M12.5 批3 路3B：fields=FISHING_TOP_FIELD_DEFS 三段宽容器（schema_version 精确
    str + species/king 宽 list 容器 soft_label）——编辑器 obj 表单段头数据源；
    species/king 行深结构由 validate_fishing 专项 + fish_card_schema 双全权。
    """
    meta = fishing_module_meta()
    assert meta.entry_type == "object", "fishing 顶层是 obj 非 list → entry_type=object"
    assert meta.kind == "fish"
    # 三段宽容器字段表注入（对齐 forge FORGE_EDITOR_TOP_FIELDS 口径）
    assert set(meta.fields) == {"schema_version", "species", "king"}
    assert meta.fields["schema_version"].type == "str"
    for seg in ("species", "king"):
        fmeta = meta.fields[seg]
        assert fmeta.type == "list" and fmeta.element is not None
        # element children={} 即宽容器语义（行深结构归专项/服务层全权）
        assert fmeta.element.type == "obj" and fmeta.element.children == {}
    assert all(x.label for x in meta.fields.values()), "三段字段 label 应全中文非空"


def test_fishing_settings_meta() -> None:
    """fishing_settings_meta()：type=obj + 9 键 children（共享契约 §一）。"""
    meta = fishing_settings_meta()
    assert meta.type == "obj"
    assert set(meta.children.keys()) == {
        "mode", "bait_ids", "bait_bonus", "rod_full_bonus", "crown_thresholds",
        "wait_sec", "daily_limit", "energy", "king_event",
    }
    assert meta.children["mode"].type == "str"
    assert meta.children["bait_ids"].type == "list"


# ---------------------------------------------------------------------------
# F 校验器（细化 2c1a §六 TC-18 ~ TC-22b）
# ---------------------------------------------------------------------------
def test_tc18_v1_size_range_reversed() -> None:
    """TC-18 V1：size_min=60 > size_max=10 → 红拦，报字段路径 fishing.species.{i}.size_min。"""
    fish = dict(_legal_fish()[0], size_min=60.0, size_max=10.0)
    report = _run(_legal_modules(fishing={"species": [fish]}))
    assert report.errors, "V1 区间倒置应红拦"
    hits = [e for e in report.errors if e["detail"].get("rule") == "size_range_reversed"]
    assert hits, f"应含 size_range_reversed：{report.errors}"
    assert hits[0]["field"] == "fishing.species.0.size_min"
    assert hits[0]["kind"] == "V1"


def test_tc18b_v1_weight_range_reversed() -> None:
    """TC-18 V1（weight 同理）：weight_min > weight_max → 红拦，报 weight_min 路径。"""
    fish = dict(_legal_fish()[0], weight_min=9.0, weight_max=1.0)
    report = _run(_legal_modules(fishing={"species": [fish]}))
    hits = [e for e in report.errors if e["detail"].get("rule") == "weight_range_reversed"]
    assert hits, f"应含 weight_range_reversed：{report.errors}"
    assert hits[0]["field"] == "fishing.species.0.weight_min"
    assert hits[0]["kind"] == "V1"


def test_tc19_v2_crown_thresholds_out_of_order() -> None:
    """TC-19 V2：阈值乱序 reverse=95/silver=85/gold=5 → 红拦（须 0<r<s<g<100）。"""
    settings = _legal_settings()
    settings["fishing"]["crown_thresholds"] = {"reverse": 95, "silver": 85, "gold": 5}
    report = _run(_legal_modules(settings=settings))
    hits = [e for e in report.errors if e["detail"].get("rule") == "crown_thresholds_order"]
    assert hits, f"V2 应红拦乱序阈值：{report.errors}"
    assert hits[0]["field"] == "settings.fishing.crown_thresholds"
    assert hits[0]["kind"] == "V2"


def test_tc20_v3_bait_ref_missing() -> None:
    """TC-20 V3 正向：preferred_bait:["饵_不存在"] → 红拦，报缺失引用 id。"""
    fish = dict(_legal_fish()[0], preferred_bait=["饵_不存在"])
    report = _run(_legal_modules(fishing={"species": [fish]}))
    hits = [e for e in report.errors if e["detail"].get("rule") == "bait_ref_missing"]
    assert hits, f"V3 应红拦缺失饵引用：{report.errors}"
    assert hits[0]["field"] == "fishing.species.0.preferred_bait.0"
    assert hits[0]["detail"].get("ref") == "饵_不存在"
    assert hits[0]["kind"] == "V3"


def test_tc20b_v3_recipe_fish_target_missing() -> None:
    """TC-20 V3 反向：recipe 行含 fish_target 指向不存在的鱼种 → 红拦。"""
    modules = _legal_modules(recipe=[{"id": "rcp_worm", "fish_target": "ghost_fish"}])
    report = _run(modules)
    hits = [e for e in report.errors if e["detail"].get("rule") == "fish_target_missing"]
    assert hits, f"V3 反向应红拦缺失鱼种：{report.errors}"
    assert hits[0]["field"] == "recipe.0.fish_target"
    assert hits[0]["detail"].get("ref") == "ghost_fish"
    assert hits[0]["kind"] == "V3"


def test_tc20c_v3_recipe_no_fish_target_skipped() -> None:
    """V3 反向宽松：recipe.json 无 fish_target 语义（test_demo 现状）→ 跳过不误报。"""
    modules = _legal_modules(recipe=[{"id": "rcp_fire_crystal"}, {"id": "rcp_flame_bomb"}])
    report = _run(modules)
    assert report.errors == [], f"无 fish_target 语义应零红，got {report.errors}"


def test_tc21_v4_mode_bogus_hard_error() -> None:
    """TC-21 V4：mode:"bogus" 非法枚举 → 硬红拦（非静默 fallback）。"""
    settings = _legal_settings()
    settings["fishing"]["mode"] = "bogus"
    report = _run(_legal_modules(settings=settings))
    hits = [e for e in report.errors if e["detail"].get("rule") == "mode_invalid"]
    assert hits, f"V4 非枚举应硬红拦：{report.errors}"
    assert hits[0]["field"] == "settings.fishing.mode"
    assert hits[0]["kind"] == "V4"
    assert hits[0]["detail"].get("value") == "bogus"


def test_tc21b_v4_full_simple_off_pass() -> None:
    """V4：full/simple/off 三值均通过（枚举白名单）。"""
    for mode in FISH_MODES:
        settings = _legal_settings()
        settings["fishing"]["mode"] = mode
        report = _run(_legal_modules(settings=settings))
        assert not any(e["detail"].get("rule") == "mode_invalid" for e in report.errors), \
            f"mode={mode} 应通过 V4"


def test_tc22_w1_simple_king_warns_not_block() -> None:
    """TC-22 W1：mode:"simple" 且 king 表非空 → V1-V6 仍过 + W1 黄提示「simple 不生效」不阻断。"""
    settings = _legal_settings()
    settings["fishing"]["mode"] = "simple"
    modules = _legal_modules(settings=settings, fishing={
        "schema_version": "1.0",
        "species": _legal_fish(),
        "king": [{"id": "king_carp", "species_id": "silver_carp",
                  "enemy_id": "boss_king_carp"}],
    })
    report = _run(modules)
    assert report.errors == [], f"W1 黄不应阻断，got {report.errors}"
    hits = [w for w in report.warnings if w["detail"].get("rule") == "simple_king_ignored"]
    assert hits, f"应含 W1 黄提示：{report.warnings}"
    assert hits[0]["kind"] == "W1"
    assert "不生效" in str(hits[0]["detail"].get("note", ""))


def test_tc22b_v5_duplicate_id() -> None:
    """TC-22b V5：鱼种 id 重复 → 红拦。"""
    fish = _legal_fish()
    dup = dict(fish[0], id="silver_carp", name="银鳞鲤二号")
    report = _run(_legal_modules(fishing={"species": fish + [dup]}))
    hits = [e for e in report.errors if e["detail"].get("rule") == "fish_id_duplicate"]
    assert hits, f"V5 重复 id 应红拦：{report.errors}"
    assert hits[0]["field"] == "fishing.species.2.id"  # fish 2 条 + dup 1 条 → 索引 2
    assert hits[0]["kind"] == "V5"


def test_tc22b2_v5_empty_species() -> None:
    """TC-22b V5 扩展：species 空数组（防空池）→ 红拦。"""
    report = _run(_legal_modules(fishing={"species": []}))
    hits = [e for e in report.errors if e["detail"].get("rule") == "species_empty"]
    assert hits, f"species 空数组应 V5 红拦（防空池）：{report.errors}"
    assert hits[0]["field"] == "fishing.species"
    assert hits[0]["kind"] == "V5"


def test_tc22b3_v5_king_species_missing() -> None:
    """V5 扩展：king[].species_id 指向不存在鱼种 → 红拦。"""
    modules = _legal_modules(fishing={
        "schema_version": "1.0",
        "species": _legal_fish(),
        "king": [{"id": "king_ghost", "species_id": "ghost_fish"}],
    })
    report = _run(modules)
    hits = [e for e in report.errors if e["detail"].get("rule") == "king_species_missing"]
    assert hits, f"king species_id 缺失应红拦：{report.errors}"
    assert hits[0]["field"] == "fishing.king.0.species_id"
    assert hits[0]["kind"] == "V5"


def test_tc22b4_v6_enum_invalid() -> None:
    """TC-22b V6：rarity/seasons/periods 枚举非法成员 + hours 格式不符 → 红拦。"""
    fish = dict(_legal_fish()[0],
                rarity="epic", seasons=["summer", "rainy"], periods=["dawn", "afternoon"],
                hours=["bogus-noon"])
    report = _run(_legal_modules(fishing={"species": [fish]}))
    rules = _rules(report, "errors")
    assert "rarity_invalid" in rules, f"rarity 非法应红拦：{report.errors}"
    assert "season_invalid" in rules, f"season 非法应红拦：{report.errors}"
    assert "period_invalid" in rules, f"period 非法应红拦：{report.errors}"
    assert "hours_format" in rules, f"hours 格式不符应红拦：{report.errors}"


def test_tc22b5_v6_spots_empty_and_ref_missing() -> None:
    """TC-22b V6：spots 空数组红拦；引用不存在采集点红拦（maps 含 gather_points 时）。"""
    # spots 空数组 → 红拦
    fish_empty = dict(_legal_fish()[0], spots=[])
    report = _run(_legal_modules(fishing={"species": [fish_empty]}))
    hits = [e for e in report.errors if e["detail"].get("rule") == "spots_empty"]
    assert hits, f"spots 空应 V6 红拦：{report.errors}"
    assert hits[0]["field"] == "fishing.species.0.spots"
    assert hits[0]["kind"] == "V6"
    # 引用不存在采集点 → 红拦（maps 模块含 gather_points）
    fish_bad = dict(_legal_fish()[0], spots=["gp_nonexistent"])
    report2 = _run(_legal_modules(fishing={"species": [fish_bad]}))
    hits2 = [e for e in report2.errors if e["detail"].get("rule") == "spot_ref_missing"]
    assert hits2, f"spot 引用缺失应红拦：{report2.errors}"
    assert hits2[0]["field"] == "fishing.species.0.spots.0"
    assert hits2[0]["detail"].get("ref") == "gp_nonexistent"
    assert hits2[0]["kind"] == "V6"


def test_v6_spots_ref_loose_when_maps_no_gather() -> None:
    """V6 spots 宽松引用：maps 模块无任何 gather_points（legal 现状）→ 跳过不误拦。"""
    maps_no_gp = [{"id": "rubble_field", "name": "碎石旷野"}]
    report = _run(_legal_modules(maps=maps_no_gp))
    assert report.errors == [], f"maps 无采集点应宽松跳过，got {report.errors}"


# ---------------------------------------------------------------------------
# 收集器三形态 / legal 包 / 登记一致性
# ---------------------------------------------------------------------------
def test_report_dict_form() -> None:
    """收集器 dict 形态：{"errors":[],"warnings":[]}（_emit 兜底）。"""
    fish = dict(_legal_fish()[0], size_min=60.0, size_max=10.0)  # 造 V1 红
    modules = _legal_modules(fishing={"species": [fish]})
    report: Dict[str, list] = {"errors": [], "warnings": []}
    validate_fishing(modules, report)
    assert report["errors"], "dict 形态应收集 errors"
    assert report["errors"][0]["args"][0] == "fishing"  # module
    assert report["errors"][0]["args"][2] == "V1"


def test_report_checker_form() -> None:
    """真实 validator._Checker 收口兼容（_err/_warn 回落）。"""
    fish = dict(_legal_fish()[0], size_min=60.0, size_max=10.0)  # 造 V1 红
    modules = _legal_modules(fishing={"species": [fish]})
    checker = _Checker(modules, _default_meta())
    validate_fishing(modules, checker)
    assert any(e.kind == "V1" for e in checker.errors), "_Checker 应收集 V1"
    # W1 黄 → checker.warnings
    settings = _legal_settings()
    settings["fishing"]["mode"] = "off"
    modules_w = _legal_modules(settings=settings, fishing={
        "species": _legal_fish(), "king": [{"id": "kc", "species_id": "silver_carp"}]})
    checker_w = _Checker(modules_w, _default_meta())
    validate_fishing(modules_w, checker_w)
    assert any(w.kind == "W1" for w in checker_w.warnings), "_Checker 应收集 W1 黄"


def _default_meta():
    """缺省 field_meta 表（fishing 已登记 entry_type=object 空表，专项全权）。"""
    from qbot_rpg.content.field_meta import default_field_meta_table
    return default_field_meta_table()


def test_legal_pack_zero_red() -> None:
    """legal 包红拦零命中：读 legal 现有 settings.json + maps.json（fishing.json 由路0B
    新建，若已落盘一并加载），validate_fishing 红拦零命中。"""
    settings = json.loads((LEGAL_DIR / "settings.json").read_text(encoding="utf-8"))
    maps = json.loads((LEGAL_DIR / "maps.json").read_text(encoding="utf-8"))
    fishing_path = LEGAL_DIR / "fishing.json"
    if fishing_path.exists():
        fishing = json.loads(fishing_path.read_text(encoding="utf-8"))
    else:
        # 路0B 未落盘：以契约 §二 基准行构造 legal 形态（零共享文件原则，本路只读）
        fishing = {"schema_version": "1.0", "species": _legal_fish(), "king": []}
    modules: Dict[str, object] = {
        "fishing": fishing,
        "settings": settings,
        "maps": maps,
    }
    report = _run(modules)
    assert report.errors == [], f"legal 包应红拦零命中，got {report.errors}"


def test_register_consistency_loader_subset_meta() -> None:
    """loader ⊆ field_meta 登记一致（check_register_table_consistency 零缺口）。"""
    from qbot_rpg.content.loader import check_register_table_consistency
    missing = check_register_table_consistency()
    assert missing == [], f"loader 登记应 ⊆ field_meta：{missing}"
