"""M8 炼金数据层 · 路 0A：recipe/traits/proficiency 数据模型 + 专项校验器测试。

文件名：test_alchemy_models.py
创建时间：2026-08-29
作者：Hermes 子agent-0A（并发同仓：仅新建本文件 + qbot_rpg/content/alchemy_models.py）

依据：docs/m8_contract_数据与校验.md §一（recipe 字段表 1.1 + kind=upgrade 四实例 1.2）、
§二（traits 字段表 2.1 + JSON 样例 2.2）、§三（proficiency 字段表 3.1）、§六 6.2（校验器规则清单
REC-01~16 / TRT-01~09 / PRF-01~10，级别：红拦=error / 黄=warning）。
测试目标：qbot_rpg.content.alchemy_models.{validate_recipes, validate_traits, validate_proficiency}
+ RecipeDef/TraitDef/ProficiencyDef + ALCHEMY_ELEMENTS/QUALITY_TIERS 常量。

测试口径（对齐 test_shop_models.py）：
  - 三个 validate 均为 (modules, report) 纯函数；report 鸭子类型（本文件 _Report 收集器；
    另含真实 validator._Checker 收口兼容测试）。
  - 断言级别：errors=红拦拦截 / warnings=黄提示不拦 / notes=信息级降级提示。
  - 每条规则至少正例+负例；红拦规则断言 errors、黄规则断言 warnings。
  - 契约 §二 2.2 JSON 样例整体零红拦零黄冒烟。
  - ALCHEMY_ELEMENTS 8 元素键集与 damage.DEFAULT_ELEMENTS 一致（只读比对字面量，不 import core）；
    QUALITY_TIERS 键集 common/uncommon/rare/legendary 边界（拍板②）。
"""
from __future__ import annotations

from typing import Mapping, cast

from qbot_rpg.content.alchemy_models import (
    ALCHEMY_ELEMENTS,
    DEFAULT_JOB_RANK_LEVELS,
    DEFAULT_TIER_NAMES,
    EVOLVE_SOURCES,
    EXP_SOURCE_KEYS,
    QUALITY_TIER_NAMES,
    QUALITY_TIERS,
    RECIPE_KINDS,
    RECIPE_LEVEL_MAX,
    RECIPE_LEVEL_MIN,
    RECIPE_SLOTS_MAX,
    RECIPE_SLOTS_MIN,
    RECIPE_TRAITS_INHERIT_MAX,
    RECIPE_TRAITS_INHERIT_MIN,
    RESERVED_ID_CHARS,
    TITLE_SOURCES,
    TRAIT_RARITIES,
    TRAIT_SOURCES,
    ProficiencyDef,
    RecipeDef,
    TraitDef,
    validate_proficiency,
    validate_recipes,
    validate_traits,
)
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import _Checker

# core/damage.DEFAULT_ELEMENTS 键集（只读比对字面量，G0 单向依赖禁止 import core）
_DAMAGE_ELEMENT_KEYS = ("earth", "fire", "water", "wind", "thunder", "crystal", "moon", "void")


# ---------------------------------------------------------------------------
# 收集器 / 夹具辅助
# ---------------------------------------------------------------------------
class _Report:
    """validate_* 收集器（鸭子类型：error/warning/note 与 _Checker._err/_warn/_note 一致）。"""

    def __init__(self) -> None:
        self.errors: list = []
        self.warnings: list = []
        self.notes: list = []

    def error(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.errors.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def warning(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.warnings.append({"module": module, "field": field, "kind": kind, "detail": detail})

    def note(self, module: str, field: str, kind: str, **detail: object) -> None:
        self.notes.append({"module": module, "field": field, "kind": kind, "detail": detail})


def _base_modules() -> dict:
    """标准模块上下文：items / effects / jobs 引用靶齐全（零降级 note 的合法包）。"""
    return {
        "items": [
            {"id": "herb"}, {"id": "water"}, {"id": "iron_ore"},
            {"id": "attack_orb_common"}, {"id": "attack_orb_uncommon"},
            {"id": "recipe_a"}, {"id": "recipe_b"}, {"id": "recipe_c"},
            {"id": "trait_fire_1"}, {"id": "trait_fire_2"}, {"id": "trait_fire_3"},
            {"id": "catalyst_ash", "type": "触媒"},
        ],
        "effects": [
            {"id": "element_modifier"}, {"id": "damage"}, {"id": "heal"},
            {"id": "stat_modifier"}, {"id": "dot"}, {"id": "control"},
            {"id": "element_boost"},
        ],
        "jobs": [{"id": "alchemy"}],
    }


def _legal_recipes() -> list:
    """合法全量配方（三类 kind + §1.2 四 upgrade 实例 + 进化线/组合合成/element_req/catalyst，
    零红拦零黄零降级 note）。"""
    return [
        {  # craft：材料合成（合成层标准版）
            "id": "potion_craft", "name": "初级药水", "kind": "craft", "level": 1,
            "materials": [{"id": "herb", "count": 2}, {"id": "water", "count": 1}],
            "cost": {"coins": 10, "gem": 0}, "slots": 4, "traits_inherit": 1,
            "effects": ["damage"],
        },
        {  # combine：素材合成（锻造 3:1 同源）
            "id": "iron_combine", "name": "铁锭合成", "kind": "combine", "level": 5,
            "materials": [{"id": "iron_ore", "count": 3}], "cost": {"coins": 20},
        },
        {  # upgrade 珠三合一升阶（§1.2：3×同档同 ID 珠，cost.gem=10，output 珠+1 阶 count=1）
            "id": "orb_upgrade", "name": "攻击珠升阶", "kind": "upgrade", "level": 10,
            "inputs": [{"item": "attack_orb_common", "count": 3}],
            "output": {"item": "attack_orb_uncommon", "count": 1},
            "cost": {"coins": 0, "gem": 10},
        },
        {  # upgrade 配方合成（§1.2：两配方已学，cost.gem=5）
            "id": "recipe_synth", "name": "配方合成", "kind": "upgrade", "level": 25,
            "inputs": [{"item": "recipe_a", "count": 1}, {"item": "recipe_b", "count": 1}],
            "output": {"item": "recipe_c", "count": 1},
            "cost": {"gem": 5},
        },
        {  # upgrade 特性合成（§1.2：2 同系特性，cost.gem=20）
            "id": "trait_synth", "name": "特性合成", "kind": "upgrade", "level": 40,
            "inputs": [{"item": "trait_fire_1", "count": 1}, {"item": "trait_fire_2", "count": 1}],
            "output": {"item": "trait_fire_3", "count": 1},
            "cost": {"gem": 20},
        },
        {  # craft 深度配方 + 进化线 + element_req + catalyst + combine_from（全机制字段）
            "id": "flame_bomb", "name": "火焰弹", "kind": "craft", "level": 35,
            "materials": [{"id": "herb", "count": 2}], "cost": {"coins": 50},
            "slots": 6, "traits_inherit": 2, "synth_allowed": True, "master_only": False,
            "effects": [{"type": "element_boost", "element": "fire", "value": 15}],
            "element_req": {"fire": [{"阈值": 30, "效果": "element_boost"}]},
            "catalyst": ["catalyst_ash"],
            "combine_from": ["potion_craft", "iron_combine"],
            "evolve_to": {"id": "hellfire_bomb",
                          "condition": {"count": 5, "source": "炼金产出"}},
            "pp_budget": 5,
        },
        {  # 进化链第二环（无环）
            "id": "hellfire_bomb", "name": "地狱火弹", "kind": "craft", "level": 45,
            "materials": [{"id": "herb", "count": 3}], "cost": {"coins": 80},
            "evolve_to": {"id": "doom_bomb", "condition": {"count": 3, "source": "炼金产出"}},
        },
        {  # 进化链末环（无 evolve_to）
            "id": "doom_bomb", "name": "灭世爆弹", "kind": "craft", "level": 55,
            "materials": [{"id": "herb", "count": 4}], "cost": {"coins": 120},
        },
    ]


def _legal_traits() -> list:
    """合法全量特性（含契约 §二 2.2 JSON 样例 + rarity=super 金色 + 互斥组成员，零红拦零黄）。"""
    return [
        {  # §2.2 JSON 样例（原样）
            "id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal",
            "effects": [{"type": "element_modifier", "element": "fire", "value": 15}],
            "group": "fire_boost", "repeatable": False, "source": "素材",
        },
        {  # 普通特性（字符串效果 ID + 互斥组同组成员）
            "id": "trait_atk_up", "name": "攻击+15%", "rarity": "normal",
            "effects": ["stat_modifier"], "group": "atk_boost", "source": "素材",
        },
        {  # super 金色超特性（第 4 位独占 gold_slot_exclusive）
            "id": "trait_gold", "name": "金色超特性", "rarity": "super",
            "effects": ["element_boost"], "source": "金色素材", "gold_slot_exclusive": True,
        },
        {  # 成品特性（全物入料 → 按携带特性原样入池）
            "id": "trait_item_drop", "name": "成品淬炼", "rarity": "normal",
            "effects": ["heal"], "source": "成品",
        },
    ]


def _legal_proficiency() -> list:
    """合法全量职业熟练度配置（7 级默认名 + 成长曲线 + 三来源 + SP 面板 + energy + job_tier_map +
    titles，零红拦零黄；jobs 模块存在且 id=alchemy 命中 → 零降级 note）。"""
    return [
        {
            "id": "alchemy",
            "tier_names": list(DEFAULT_TIER_NAMES),
            "job_rank_levels": list(DEFAULT_JOB_RANK_LEVELS),
            "exp_sources": {"craft": 1.0, "gather": 1.0, "combat": 1.0},
            "sp_per_level": 1,
            "sp_panel": [
                {"id": "quality_cap_10", "name": "品质上限+10", "cost": 1,
                 "repeatable": True, "max_repeat": 5},
                {"id": "trait_slot_1", "name": "特性位+1", "cost": 1,
                 "repeatable": True, "max_repeat": 3},
            ],
            "energy": {"enabled": False, "max_by_tier": [5, 8, 10, 12, 15, 18, 20],
                       "regen_sec": 1800},
            "job_tier_map": {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20],
                             "专家": [21, 30], "大师": [31, 40], "宗师": [41, 50],
                             "王": [51, None]},
            "titles": [
                {"id": "alchemy_master", "name": "炼金大师", "icon": "⚗️",
                 "source": "contest", "desc": "品评会冠军"},
            ],
        },
    ]


def _check_recipes(recipes: object, **extra_modules: object) -> _Report:
    """跑 validate_recipes；默认带齐全引用靶模块（items/effects/jobs）。"""
    modules: dict = _base_modules()
    modules["recipe"] = recipes
    modules.update(extra_modules)
    rep = _Report()
    validate_recipes(modules, rep)
    return rep


def _check_traits(traits: object, **extra_modules: object) -> _Report:
    modules: dict = _base_modules()
    modules["traits"] = traits
    modules.update(extra_modules)
    rep = _Report()
    validate_traits(modules, rep)
    return rep


def _check_profs(profs: object, **extra_modules: object) -> _Report:
    modules: dict = _base_modules()
    modules["proficiency"] = profs
    modules.update(extra_modules)
    rep = _Report()
    validate_proficiency(modules, rep)
    return rep


def _errs(rep: _Report, rule: str | None = None) -> list:
    return [e for e in rep.errors if rule is None or e["detail"].get("rule") == rule]


def _warns(rep: _Report, rule: str | None = None) -> list:
    return [w for w in rep.warnings if rule is None or w["detail"].get("rule") == rule]


def _notes(rep: _Report, rule: str | None = None) -> list:
    return [n for n in rep.notes if rule is None or n["detail"].get("rule") == rule]


def _recipe_by_id(recipes: list, rid: str) -> dict:
    for r in recipes:
        if r.get("id") == rid:
            return r
    raise AssertionError(f"recipe 缺少 {rid}")


def _trait_by_id(traits: list, tid: str) -> dict:
    for t in traits:
        if t.get("id") == tid:
            return t
    raise AssertionError(f"trait 缺少 {tid}")


# ---------------------------------------------------------------------------
# 常量注册表：8 元素键集 / 品质档键集 / 枚举
# ---------------------------------------------------------------------------
def test_alchemy_elements_keys_match_damage() -> None:
    """【工程补白】1：ALCHEMY_ELEMENTS 键集与 damage.DEFAULT_ELEMENTS 一致（不 import core）。"""
    assert tuple(ALCHEMY_ELEMENTS) == _DAMAGE_ELEMENT_KEYS
    assert set(ALCHEMY_ELEMENTS) == set(_DAMAGE_ELEMENT_KEYS)
    assert ALCHEMY_ELEMENTS["fire"] == "火"
    assert ALCHEMY_ELEMENTS["void"] == "无"
    assert len(ALCHEMY_ELEMENTS) == 8


def test_quality_tiers_keys_boundary() -> None:
    """拍板②：品质档键集只允许 common/uncommon/rare/legendary 四键（无 fine/优秀/稀有 旧名）。"""
    assert QUALITY_TIERS == ("common", "uncommon", "rare", "legendary")
    assert set(QUALITY_TIERS) == {"common", "uncommon", "rare", "legendary"}
    assert QUALITY_TIER_NAMES["common"] == "普通"
    assert QUALITY_TIER_NAMES["legendary"] == "传说"
    assert "fine" not in QUALITY_TIERS


def test_enum_constants() -> None:
    """三类 kind / 特性 rarity / 特性 source / exp_sources / titles source / evolve source 枚举。"""
    assert set(RECIPE_KINDS) == {"craft", "combine", "upgrade"}
    assert set(TRAIT_RARITIES) == {"normal", "super"}
    assert set(TRAIT_SOURCES) == {"素材", "成品", "金色素材"}
    assert set(EXP_SOURCE_KEYS) == {"craft", "gather", "combat"}
    assert set(TITLE_SOURCES) == {"king", "contest", "achievement", "custom"}
    assert set(EVOLVE_SOURCES) == {"炼金产出", "合成产出"}
    assert RECIPE_LEVEL_MIN == 1 and RECIPE_LEVEL_MAX == 99
    assert RECIPE_SLOTS_MIN == 2 and RECIPE_SLOTS_MAX == 10
    assert RECIPE_TRAITS_INHERIT_MIN == 1 and RECIPE_TRAITS_INHERIT_MAX == 3
    assert RESERVED_ID_CHARS == ("*", ",", "=", "+")


# ---------------------------------------------------------------------------
# 合法全量 schema 零红拦 + 访问器 + _Checker 收口兼容
# ---------------------------------------------------------------------------
def test_legal_recipes_full_green() -> None:
    """合法全量配方（三类 kind + §1.2 四 upgrade 实例 + 进化线/element_req/catalyst/combine_from）
    → 零红拦零黄零降级 note。"""
    rep = _check_recipes(_legal_recipes())
    assert not rep.errors, f"合法 recipe 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 recipe 应为零黄提示：{rep.warnings}"
    assert not rep.notes, f"引用靶齐全应零降级 note：{rep.notes}"


def test_legal_recipes_checker_integration() -> None:
    """收口兼容：validate_recipes 直传真实 validator._Checker（鸭子路径）零红拦零黄。"""
    modules = _base_modules()
    modules["recipe"] = _legal_recipes()
    checker = _Checker(modules, default_field_meta_table())
    validate_recipes(modules, checker)
    assert not checker.errors, f"直传 _Checker 应零红拦：{checker.errors}"
    assert not checker.warnings, f"直传 _Checker 应零黄：{checker.warnings}"


def test_legal_traits_full_green_and_contract_sample() -> None:
    """合法全量特性 + 契约 §二 2.2 JSON 样例整体零红拦零黄（冒烟）。"""
    rep = _check_traits(_legal_traits())
    assert not rep.errors, f"合法 traits 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 traits 应为零黄提示：{rep.warnings}"
    # §2.2 样例单独冒烟
    sample = {
        "id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal",
        "effects": [{"type": "element_modifier", "element": "fire", "value": 15}],
        "group": "fire_boost", "repeatable": False, "source": "素材",
    }
    rep2 = _check_traits([sample])
    assert not rep2.errors, f"§2.2 样例不应有红拦：{rep2.errors}"
    assert not rep2.warnings, f"§2.2 样例应为零黄提示：{rep2.warnings}"


def test_legal_traits_checker_integration() -> None:
    """收口兼容：validate_traits 直传真实 validator._Checker 零红拦零黄。"""
    modules = _base_modules()
    modules["traits"] = _legal_traits()
    checker = _Checker(modules, default_field_meta_table())
    validate_traits(modules, checker)
    assert not checker.errors
    assert not checker.warnings


def test_legal_proficiency_full_green() -> None:
    """合法全量职业熟练度 → 零红拦零黄（jobs 存在且 id=alchemy 命中 → 零降级 note）。"""
    rep = _check_profs(_legal_proficiency())
    assert not rep.errors, f"合法 proficiency 不应有红拦：{rep.errors}"
    assert not rep.warnings, f"合法 proficiency 应为零黄提示：{rep.warnings}"
    assert not rep.notes, f"jobs 命中应零降级 note：{rep.notes}"


def test_legal_proficiency_checker_integration() -> None:
    """收口兼容：validate_proficiency 直传真实 validator._Checker 零红拦零黄。"""
    modules = _base_modules()
    modules["proficiency"] = _legal_proficiency()
    checker = _Checker(modules, default_field_meta_table())
    validate_proficiency(modules, checker)
    assert not checker.errors
    assert not checker.warnings


# ---------------------------------------------------------------------------
# Def 访问器
# ---------------------------------------------------------------------------
def _recipe_def(entry: Mapping[str, object]) -> RecipeDef:
    return cast(RecipeDef, RecipeDef.from_entry(entry))


def _trait_def(entry: Mapping[str, object]) -> TraitDef:
    return cast(TraitDef, TraitDef.from_entry(entry))


def _prof_def(entry: Mapping[str, object]) -> ProficiencyDef:
    return cast(ProficiencyDef, ProficiencyDef.from_entry(entry))


def test_recipe_def_accessors() -> None:
    """RecipeDef 访问器：三类 kind + materials/inputs/output/cost/evolve_to 等。"""
    d = _recipe_def(_recipe_by_id(_legal_recipes(), "flame_bomb"))
    assert d.id == "flame_bomb"
    assert d.name == "火焰弹"
    assert d.recipe_kind == "craft"
    assert d.level == 35
    assert d.synth_allowed is True
    assert d.master_only is False
    assert d.cost.get("coins") == 50
    assert d.cost_value("coins") == 50
    assert d.slots == 6
    assert d.traits_inherit == 2
    assert d.effects == ("element_boost",)          # 对象 type 双形态
    assert d.catalyst == ("catalyst_ash",)
    assert d.combine_from == ("potion_craft", "iron_combine")
    assert d.evolve_to_id == "hellfire_bomb"
    assert d.evolve_to_condition.get("count") == 5
    assert d.evolve_to_condition.get("source") == "炼金产出"
    assert d.pp_budget == 5
    assert d.element_req.get("fire") is not None

    up = _recipe_def(_recipe_by_id(_legal_recipes(), "orb_upgrade"))
    assert up.recipe_kind == "upgrade"
    assert up.inputs[0]["item"] == "attack_orb_common"
    assert up.output_item == "attack_orb_uncommon"
    assert up.output_count == 1
    assert up.cost_value("gem") == 10
    assert up.materials == ()                         # upgrade 无 materials

    cb = _recipe_def(_recipe_by_id(_legal_recipes(), "iron_combine"))
    assert cb.recipe_kind == "combine"
    assert cb.materials[0]["id"] == "iron_ore"
    assert cb.cost_value("coins") == 20

    # 缺省：未配字段 → None（访问器不伪造默认值，兜底归校验/引擎侧）
    base = _recipe_def({"id": "x", "name": "缺省测试", "kind": "craft"})
    assert base.level is None
    assert base.synth_allowed is None
    assert base.slots is None
    assert base.traits_inherit is None
    assert base.effects == ()
    assert base.evolve_to == {}
    assert base.evolve_to_id is None


def test_trait_def_accessors() -> None:
    """TraitDef 访问器：rarity/effects/group/repeatable/source/gold_slot_exclusive。"""
    d = _trait_def(_trait_by_id(_legal_traits(), "trait_burn_boost"))
    assert d.id == "trait_burn_boost"
    assert d.name == "灼烧强化"
    assert d.rarity == "normal"
    assert d.effects == ("element_modifier",)        # 对象 type 双形态
    assert d.group == "fire_boost"
    assert d.repeatable is False
    assert d.source == "素材"
    assert d.gold_slot_exclusive is None

    g = _trait_def(_trait_by_id(_legal_traits(), "trait_gold"))
    assert g.rarity == "super"
    assert g.gold_slot_exclusive is True
    assert g.source == "金色素材"

    base = _trait_def({"id": "x", "name": "特性"})
    assert base.rarity is None
    assert base.repeatable is None
    assert base.effects == ()


def test_proficiency_def_accessors() -> None:
    """ProficiencyDef 访问器：tier_names/job_rank_levels/exp_sources/sp_per_level/sp_panel/
    energy/job_tier_map/titles。"""
    d = _prof_def(_legal_proficiency()[0])
    assert d.id == "alchemy"
    assert d.tier_names == DEFAULT_TIER_NAMES
    assert d.job_rank_levels == DEFAULT_JOB_RANK_LEVELS
    assert d.exp_sources.get("craft") == 1.0
    assert d.sp_per_level == 1
    assert d.sp_panel[0]["id"] == "quality_cap_10"
    assert d.energy_enabled is False
    assert d.energy_max_by_tier == (5, 8, 10, 12, 15, 18, 20)
    assert d.energy_regen_sec == 1800
    jtm = cast(Mapping[str, object], d.job_tier_map)
    assert jtm.get("见习") == [1, 5]
    assert d.titles[0]["source"] == "contest"

    base = _prof_def({"id": "x"})
    assert base.tier_names == ()
    assert base.job_rank_levels == ()
    assert base.exp_sources == {}
    assert base.sp_per_level is None
    assert base.sp_panel == ()
    assert base.energy_enabled is None
    assert base.job_tier_map is None
    assert base.titles == ()


# ---------------------------------------------------------------------------
# validate_recipes：REC-01 ~ REC-16（红拦=errors / 黄=warnings）
# ---------------------------------------------------------------------------
def test_rec01_kind_enum() -> None:
    """REC-01：kind ∉ {craft,combine,upgrade} / 缺失 → 红拦；三类合法。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["kind"] = "smelt"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-01")) == 1
    recipes = [_legal_recipes()[0]]
    del recipes[0]["kind"]
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-01")) == 1
    for kind in RECIPE_KINDS:
        recipes = [_legal_recipes()[0]]
        recipes[0]["kind"] = kind
        rep = _check_recipes(recipes)
        assert not _errs(rep, "REC-01"), f"{kind} 应合法"


def test_rec02_level_range() -> None:
    """REC-02：level 越界 / 非整数 → 红拦；[1,99] 合法。"""
    for bad in (0, 100, -5, "5", 3.5, True):
        recipes = [_legal_recipes()[0]]
        recipes[0]["level"] = bad
        rep = _check_recipes(recipes)
        assert len(_errs(rep, "REC-02")) == 1, f"level={bad!r} 应红拦"
    recipes = [_legal_recipes()[0]]
    recipes[0]["level"] = 50
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-02")


def test_rec03_materials_refs_and_count() -> None:
    """REC-03：materials id 引用不存在 / count<1 / 非整数 → 红拦；items 模块缺失 → 降级 note。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["materials"][0]["id"] = "no_such_item"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-03")) == 1
    for bad_count in (0, -1, 1.5, "2", True):
        recipes = [_legal_recipes()[0]]
        recipes[0]["materials"][0]["count"] = bad_count
        rep = _check_recipes(recipes)
        assert len(_errs(rep, "REC-03")) == 1, f"count={bad_count!r} 应红拦"
    # items 模块缺失 → 引用存在性不硬拦，降级 note（【工程补白】4）
    recipes = [_legal_recipes()[0]]
    recipes[0]["materials"][0]["id"] = "ghost_item"
    rep = _check_recipes(recipes, items=None)
    assert not _errs(rep, "REC-03")
    assert len(_notes(rep, "REC-03")) == 1


def test_rec04_cost_non_negative() -> None:
    """REC-04：cost.coins/gem 负数或非整数 → 红拦；gem 可缺省=0。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["cost"]["coins"] = -1
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-04")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["cost"]["gem"] = -3
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-04")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["cost"]["coins"] = "cheap"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-04")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["cost"] = "50"  # cost 非对象
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-04")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["cost"] = {"coins": 10}  # gem 缺省=0 合法
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-04")


def test_rec05_element_req() -> None:
    """REC-05：element_req 元素不在 8 注册表 / 阈值<0 / 效果引用不存在 → 红拦。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["element_req"] = {"shadow": [{"阈值": 30, "效果": "element_boost"}]}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-05")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["element_req"] = {"fire": [{"阈值": -1, "效果": "element_boost"}]}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-05")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["element_req"] = {"fire": [{"阈值": 30, "效果": "no_such_effect"}]}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-05")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["element_req"] = "fire:30"  # 非对象
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-05")) == 1
    # 合法：8 元素之一 + 阈值≥0 + 效果引用存在
    recipes = [_legal_recipes()[0]]
    recipes[0]["element_req"] = {"void": [{"阈值": 0, "效果": "heal"}]}
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-05")


def test_rec06_effects_ref() -> None:
    """REC-06：effects 引用不存在 → 红拦；字符串/对象 type 双形态；effects 缺失 → note。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["effects"] = ["ghost_effect"]
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-06")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["effects"] = [{"type": "ghost_type", "value": 1}]
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-06")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["effects"] = "damage"  # 非数组
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-06")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["effects"] = ["ghost_effect"]
    rep = _check_recipes(recipes, effects=None)
    assert not _errs(rep, "REC-06")
    assert len(_notes(rep, "REC-06")) == 1


def test_rec07_catalyst() -> None:
    """REC-07：catalyst 引用 items 不存在 → 红拦；存在但 type≠触媒 → 黄提示（批5B 口径）。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["catalyst"] = ["ghost_catalyst"]
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-07")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["catalyst"] = ["herb"]  # herb 存在但 type≠触媒
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-07")
    assert len(_warns(rep, "REC-07")) == 1
    # 合法触媒
    recipes = [_legal_recipes()[0]]
    recipes[0]["catalyst"] = ["catalyst_ash"]
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-07")
    assert not _warns(rep, "REC-07")


def test_rec08_combine_from() -> None:
    """REC-08：combine_from 引用 recipe 不存在 → 红拦；合法引用 → 零红拦。"""
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["combine_from"] = ["ghost_recipe"]
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-08")) == 1
    recipes = _legal_recipes()
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-08")


def test_rec09_evolve_to() -> None:
    """REC-09：evolve_to.id 引用不存在 / condition.count<1 / source 枚举非法 → 红拦。"""
    recipes = _legal_recipes()
    ev = {"id": "ghost", "condition": {"count": 1, "source": "炼金产出"}}
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = ev
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-09")) == 1
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = {
        "id": "hellfire_bomb", "condition": {"count": 0, "source": "炼金产出"}}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-09")) == 1
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = {
        "id": "hellfire_bomb", "condition": {"count": 5, "source": "synthesis_bad"}}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-09")) == 1
    # evolve_to 非对象 → 红拦
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = "hellfire"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-09")) == 1
    # 合法
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = {
        "id": "hellfire_bomb", "condition": {"count": 5, "source": "合成产出"}}
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-09")


def test_rec10_evolve_cycle() -> None:
    """REC-10：进化线成环（A→B→A 与自环 A→A）→ 红拦；无环链 → 零红拦。"""
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "doom_bomb")["evolve_to"] = {
        "id": "flame_bomb", "condition": {"count": 1, "source": "炼金产出"}}
    rep = _check_recipes(recipes)  # flame_bomb→hellfire→doom→flame_bomb 成环
    assert len(_errs(rep, "REC-10")) == 1
    cycle = _errs(rep, "REC-10")[0]["detail"].get("cycle")
    assert isinstance(cycle, list) and cycle[0] == cycle[-1]  # 环路径首尾相接
    # 自环
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "flame_bomb")["evolve_to"] = {
        "id": "flame_bomb", "condition": {"count": 1, "source": "炼金产出"}}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-10")) == 1
    # 无环链（合法）
    recipes = _legal_recipes()
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-10")


def test_rec11_upgrade_schema() -> None:
    """REC-11：upgrade inputs/output 引用不存在、output.count≠1、upgrade 写 materials、
    craft/combine 写 inputs/output → 红拦。"""
    recipes = [_legal_recipes()[2]]  # orb_upgrade
    recipes[0]["inputs"][0]["item"] = "ghost_orb"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    recipes = [_legal_recipes()[2]]
    recipes[0]["output"]["item"] = "ghost_out"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    recipes = [_legal_recipes()[2]]
    recipes[0]["output"]["count"] = 2
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    recipes = [_legal_recipes()[2]]
    recipes[0]["materials"] = [{"id": "herb", "count": 1}]  # upgrade 写 materials → 互斥红拦
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    recipes = [_legal_recipes()[0]]
    recipes[0]["inputs"] = [{"item": "herb", "count": 1}]  # craft 写 inputs → 互斥红拦
    recipes[0]["output"] = {"item": "water", "count": 1}
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    recipes = [_legal_recipes()[2]]
    recipes[0]["output"] = None  # upgrade 缺 output
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-11")) == 1
    # 合法 upgrade
    recipes = [_legal_recipes()[2]]
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-11")


def test_rec12_traits_inherit_range() -> None:
    """REC-12：traits_inherit ∉ 1-3 → 黄提示；1-3 合法零提示。"""
    for bad in (0, 4, -1, "2", True):
        recipes = [_legal_recipes()[0]]
        recipes[0]["traits_inherit"] = bad
        rep = _check_recipes(recipes)
        assert len(_warns(rep, "REC-12")) == 1, f"traits_inherit={bad!r} 应黄提示"
        assert not rep.errors, "黄规则不产生红拦"
    for good in (1, 2, 3):
        recipes = [_legal_recipes()[0]]
        recipes[0]["traits_inherit"] = good
        rep = _check_recipes(recipes)
        assert not _warns(rep, "REC-12")


def test_rec13_slots_range() -> None:
    """REC-13：slots ∉ 2-10 → 黄提示；2-10 合法零提示。"""
    for bad in (1, 11, 0, "4", True):
        recipes = [_legal_recipes()[0]]
        recipes[0]["slots"] = bad
        rep = _check_recipes(recipes)
        assert len(_warns(rep, "REC-13")) == 1, f"slots={bad!r} 应黄提示"
        assert not rep.errors
    for good in (2, 4, 10):
        recipes = [_legal_recipes()[0]]
        recipes[0]["slots"] = good
        rep = _check_recipes(recipes)
        assert not _warns(rep, "REC-13")


def test_rec14_synth_allowed() -> None:
    """REC-14：synth_allowed 非布尔 → 黄提示；false/true 均合法零黄
    （【收口裁决 2026-08-29】false 为深度配方正确默认值，不再对默认值发警告）。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["synth_allowed"] = "yes"
    rep = _check_recipes(recipes)
    assert len(_warns(rep, "REC-14")) == 1
    assert not rep.errors
    recipes = [_legal_recipes()[0]]
    recipes[0]["synth_allowed"] = False
    rep = _check_recipes(recipes)
    assert not _warns(rep, "REC-14"), "深度配方默认 false 应零黄（收口裁决）"
    assert not rep.errors
    recipes = [_legal_recipes()[0]]
    recipes[0]["synth_allowed"] = True
    rep = _check_recipes(recipes)
    assert not _warns(rep, "REC-14")


def test_rec15_master_only() -> None:
    """REC-15：master_only 非布尔 → 黄提示；True/False 合法。"""
    recipes = [_legal_recipes()[0]]
    recipes[0]["master_only"] = 1
    rep = _check_recipes(recipes)
    assert len(_warns(rep, "REC-15")) == 1
    assert not rep.errors
    recipes = [_legal_recipes()[0]]
    recipes[0]["master_only"] = True
    rep = _check_recipes(recipes)
    assert not _warns(rep, "REC-15")


def test_rec16_id_reserved_chars() -> None:
    """REC-16：id 禁保留字符 `* , = +` 与空格 → 红拦；正常 id 合法。"""
    for bad in ("a*b", "a,b", "a=b", "a+b", "a b", "a\tb"):
        recipes = [_legal_recipes()[0]]
        recipes[0]["id"] = bad
        rep = _check_recipes(recipes)
        assert len(_errs(rep, "REC-16")) == 1, f"id={bad!r} 应红拦"
    recipes = [_legal_recipes()[0]]
    recipes[0]["id"] = "flame_bomb_2"
    rep = _check_recipes(recipes)
    assert not _errs(rep, "REC-16")


def test_recipe_id_duplicate() -> None:
    """配方 id 重复 → 红拦（recipe_lib 全局唯一）。"""
    recipes = _legal_recipes()
    _recipe_by_id(recipes, "hellfire_bomb")["id"] = "flame_bomb"
    rep = _check_recipes(recipes)
    assert len(_errs(rep, "REC-01")) == 1  # 重复 id 以 REC-01 唯一性表达


# ---------------------------------------------------------------------------
# validate_traits：TRT-01 ~ TRT-09
# ---------------------------------------------------------------------------
def test_trt01_id_reserved_chars() -> None:
    """TRT-01：特性 id 禁保留字符/空格 → 红拦；id 重复 → 红拦。"""
    for bad in ("a*b", "a,b", "a=b", "a+b", "a b"):
        traits = [_legal_traits()[0]]
        traits[0]["id"] = bad
        rep = _check_traits(traits)
        assert len(_errs(rep, "TRT-01")) == 1, f"id={bad!r} 应红拦"
    traits = _legal_traits()
    _trait_by_id(traits, "trait_atk_up")["id"] = "trait_burn_boost"
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-01")) == 1


def test_trt02_rarity_enum() -> None:
    """TRT-02：rarity ∉ {normal,super} → 红拦；两值合法。"""
    traits = [_legal_traits()[0]]
    traits[0]["rarity"] = "epic"
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-02")) == 1
    for good in TRAIT_RARITIES:
        traits = [_legal_traits()[0]]
        traits[0]["rarity"] = good
        rep = _check_traits(traits)
        assert not _errs(rep, "TRT-02")


def test_trt03_effects_ref() -> None:
    """TRT-03：effects 必填 + 引用不存在 → 红拦；effects 模块缺失 → 降级 note。"""
    traits = [_legal_traits()[0]]
    traits[0]["effects"] = ["ghost_effect"]
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-03")) == 1
    traits = [_legal_traits()[0]]
    del traits[0]["effects"]
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-03")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["effects"] = ["ghost_effect"]
    rep = _check_traits(traits, effects=None)
    assert not _errs(rep, "TRT-03")
    assert len(_notes(rep, "TRT-03")) == 1


def test_trt04_group_structure() -> None:
    """TRT-04：group 为 list（多组登记）/非字符串/==自身 id（自引用）→ 红拦；合法零红拦。"""
    traits = [_legal_traits()[0]]
    traits[0]["group"] = ["fire_boost", "atk_boost"]   # 同特性登记进多个互斥组
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-04")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["group"] = ""                            # 空字符串
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-04")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["group"] = "trait_burn_boost"            # 组内自引用
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-04")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["group"] = 123                           # 非字符串
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-04")) == 1
    # 合法：同组多名成员（互斥语义）零红拦
    traits = [_legal_traits()[0], _legal_traits()[1]]
    traits[1]["group"] = "fire_boost"
    rep = _check_traits(traits)
    assert not _errs(rep, "TRT-04")


def test_trt05_repeatable_bool() -> None:
    """TRT-05：repeatable 非布尔 → 黄提示；true/false 合法。"""
    traits = [_legal_traits()[0]]
    traits[0]["repeatable"] = "yes"
    rep = _check_traits(traits)
    assert len(_warns(rep, "TRT-05")) == 1
    assert not rep.errors
    traits = [_legal_traits()[0]]
    traits[0]["repeatable"] = True
    rep = _check_traits(traits)
    assert not _warns(rep, "TRT-05")


def test_trt06_source_enum() -> None:
    """TRT-06：source ∉ {素材,成品,金色素材} → 红拦；三值合法。"""
    traits = [_legal_traits()[0]]
    traits[0]["source"] = "史诗"
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-06")) == 1
    for good in TRAIT_SOURCES:
        traits = [_legal_traits()[0]]
        traits[0]["source"] = good
        rep = _check_traits(traits)
        assert not _errs(rep, "TRT-06")


def test_trt07_name_nonempty() -> None:
    """TRT-07：name 缺失/空/纯空白 → 红拦；合法 name 零红拦。"""
    traits = [_legal_traits()[0]]
    del traits[0]["name"]
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-07")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["name"] = ""
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-07")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["name"] = "   "
    rep = _check_traits(traits)
    assert len(_errs(rep, "TRT-07")) == 1
    traits = [_legal_traits()[0]]
    traits[0]["name"] = "灼烧强化"
    rep = _check_traits(traits)
    assert not _errs(rep, "TRT-07")


def test_trt08_snapshot_redundant_name() -> None:
    """TRT-08：name 缺失或 name==id → 黄提示（快照/存档冗余 ID+名称，STO-05）；显式 name 零提示。"""
    traits = [_legal_traits()[0]]
    traits[0]["name"] = traits[0]["id"]                # name==id
    rep = _check_traits(traits)
    assert len(_warns(rep, "TRT-08")) == 1
    assert not _errs(rep, "TRT-07")                    # name 非空，不红拦
    traits = [_legal_traits()[0]]
    del traits[0]["name"]
    rep = _check_traits(traits)
    assert len(_warns(rep, "TRT-08")) == 1             # 与 TRT-07 红拦并存
    # 显式 name（≠id）→ 零提示
    traits = [_legal_traits()[0]]
    rep = _check_traits(traits)
    assert not _warns(rep, "TRT-08")


def test_trt09_gold_slot_exclusive() -> None:
    """TRT-09：gold_slot_exclusive 非布尔 → 黄提示；True/False 合法。"""
    traits = [_legal_traits()[2]]
    traits[0]["gold_slot_exclusive"] = "yes"
    rep = _check_traits(traits)
    assert len(_warns(rep, "TRT-09")) == 1
    assert not rep.errors
    traits = [_legal_traits()[2]]
    traits[0]["gold_slot_exclusive"] = True
    rep = _check_traits(traits)
    assert not _warns(rep, "TRT-09")


# ---------------------------------------------------------------------------
# validate_proficiency：PRF-01 ~ PRF-10
# ---------------------------------------------------------------------------
def test_prf01_jobs_ref() -> None:
    """PRF-01：jobs 模块存在且 id 不存在 → 红拦；id 命中 → 零记录；jobs 缺失 → 降级 note。"""
    profs = _legal_proficiency()
    profs[0]["id"] = "no_such_job"
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-01")) == 1
    # jobs 模块缺失 → 降级 note（【工程补白】3：M13 未落地，不误拦合法包）
    profs = _legal_proficiency()
    profs[0]["id"] = "future_job"
    rep = _check_profs(profs, jobs=None)
    assert not _errs(rep, "PRF-01")
    assert len(_notes(rep, "PRF-01")) == 1
    # 合法：jobs 存在且 id 命中
    rep = _check_profs(_legal_proficiency())
    assert not _errs(rep, "PRF-01")
    assert not _notes(rep, "PRF-01")


def test_prf02_tier_names() -> None:
    """PRF-02：tier_names 长度<2 / 与 job_rank_levels 长度不一致 → 红拦；合法零红拦。"""
    profs = _legal_proficiency()
    profs[0]["tier_names"] = ["见习"]
    profs[0]["job_rank_levels"] = [0]                # 长度 1（与 tier_names 一致）→ 仅长度<2 红拦
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-02")) == 1
    profs = _legal_proficiency()
    profs[0]["job_rank_levels"] = [0, 100, 300]        # 3 档 vs 7 称号
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-02")) == 1
    profs = _legal_proficiency()
    del profs[0]["tier_names"]
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-02")) == 1
    rep = _check_profs(_legal_proficiency())
    assert not _errs(rep, "PRF-02")


def test_prf03_job_rank_levels_monotonic() -> None:
    """PRF-03：job_rank_levels 首项≠0 / 非单调递增 / 非整数 → 红拦；合法零红拦。"""
    profs = _legal_proficiency()
    profs[0]["job_rank_levels"] = [100, 300, 700, 1500, 3000, 6000, 9000]   # 首项≠0
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-03")) == 1
    profs = _legal_proficiency()
    profs[0]["job_rank_levels"] = [0, 100, 100, 700, 1500, 3000, 6000]      # 不单调
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-03")) == 1
    profs = _legal_proficiency()
    profs[0]["job_rank_levels"] = [0, "100", 300, 700, 1500, 3000, 6000]    # 非整数
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-03")) == 1
    profs = _legal_proficiency()
    profs[0]["job_rank_levels"] = [0, -5, 300, 700, 1500, 3000, 6000]       # 负数
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-03")) == 1
    rep = _check_profs(_legal_proficiency())
    assert not _errs(rep, "PRF-03")


def test_prf04_exp_sources() -> None:
    """PRF-04：exp_sources 子键 ∉ {craft,gather,combat} / 值<0 → 红拦；合法零红拦。"""
    profs = _legal_proficiency()
    profs[0]["exp_sources"]["fishing"] = 1.0
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-04")) == 1
    profs = _legal_proficiency()
    profs[0]["exp_sources"]["craft"] = -0.5
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-04")) == 1
    profs = _legal_proficiency()
    profs[0]["exp_sources"] = "craft:1"                 # 非对象
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-04")) == 1
    rep = _check_profs(_legal_proficiency())
    assert not _errs(rep, "PRF-04")


def test_prf05_sp_per_level() -> None:
    """PRF-05：sp_per_level 非负整数；负数 → 红拦。"""
    profs = _legal_proficiency()
    profs[0]["sp_per_level"] = -1
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-05")) == 1
    profs = _legal_proficiency()
    profs[0]["sp_per_level"] = 2
    rep = _check_profs(profs)
    assert not _errs(rep, "PRF-05")


def test_prf06_sp_panel() -> None:
    """PRF-06：sp_panel id 重复 / cost<1 / repeatable 非布尔 / max_repeat<1 → 黄提示。"""
    profs = _legal_proficiency()
    profs[0]["sp_panel"].append(dict(profs[0]["sp_panel"][0]))   # id 重复
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-06")) == 1
    assert not rep.errors
    profs = _legal_proficiency()
    profs[0]["sp_panel"][0]["cost"] = 0
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-06")) == 1
    profs = _legal_proficiency()
    profs[0]["sp_panel"][0]["repeatable"] = "yes"
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-06")) == 1
    profs = _legal_proficiency()
    profs[0]["sp_panel"][0]["max_repeat"] = 0
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-06")) == 1
    rep = _check_profs(_legal_proficiency())
    assert not _warns(rep, "PRF-06")


def test_prf07_energy() -> None:
    """PRF-07：energy.enabled 非布尔 / enabled 时 max_by_tier 长度不一致 / regen_sec<0 → 黄提示。"""
    profs = _legal_proficiency()
    profs[0]["energy"]["enabled"] = "yes"
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-07")) == 1
    assert not rep.errors
    profs = _legal_proficiency()
    profs[0]["energy"] = {"enabled": True, "max_by_tier": [5, 8], "regen_sec": 1800}  # 长度 2≠7
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-07")) == 1
    profs = _legal_proficiency()
    profs[0]["energy"] = {"enabled": True, "max_by_tier": [5] * 7, "regen_sec": -1}
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-07")) == 1
    rep = _check_profs(_legal_proficiency())
    assert not _warns(rep, "PRF-07")


def test_prf08_job_tier_map() -> None:
    """PRF-08：job_tier_map 称号不在 tier_names / 区间非法/非单调 → 红拦；默认继承跳过。"""
    profs = _legal_proficiency()
    profs[0]["job_tier_map"]["皇帝"] = [51, 60]         # 称号不在 tier_names
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-08")) == 1
    profs = _legal_proficiency()
    profs[0]["job_tier_map"]["见习"] = "1-5"            # 区间格式非法
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-08")) == 1
    profs = _legal_proficiency()
    profs[0]["job_tier_map"]["正式"] = [3, 10]          # 与见习[1,5] 重叠 → 非单调
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-08")) == 1
    profs = _legal_proficiency()
    profs[0]["job_tier_map"]["见习"] = [10, 5]          # hi<lo
    rep = _check_profs(profs)
    assert len(_errs(rep, "PRF-08")) == 1
    # 默认 "settings"（字符串）→ 跳过校验
    profs = _legal_proficiency()
    profs[0]["job_tier_map"] = "settings"
    rep = _check_profs(profs)
    assert not _errs(rep, "PRF-08")
    rep = _check_profs(_legal_proficiency())
    assert not _errs(rep, "PRF-08")


def test_prf09_titles_source_enum() -> None:
    """PRF-09：titles source ∉ {king,contest,achievement,custom} → 黄提示；四枚举合法。"""
    profs = _legal_proficiency()
    profs[0]["titles"][0]["source"] = "boss"
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-09")) == 1
    assert not rep.errors
    for good in TITLE_SOURCES:
        profs = _legal_proficiency()
        profs[0]["titles"][0]["source"] = good
        rep = _check_profs(profs)
        assert not _warns(rep, "PRF-09"), f"source={good} 应合法"


def test_prf10_king_auto_generated() -> None:
    """PRF-10：手写 source=king 条目 → 黄提示（王称号自动生成，id=职业 ID，TTL-03）。"""
    profs = _legal_proficiency()
    profs[0]["titles"].append({"id": "alchemy", "name": "炼金王", "icon": "👑",
                               "source": "king", "desc": "图鉴全亮"})
    rep = _check_profs(profs)
    assert len(_warns(rep, "PRF-10")) == 1
    assert not rep.errors
    rep = _check_profs(_legal_proficiency())
    assert not _warns(rep, "PRF-10")
