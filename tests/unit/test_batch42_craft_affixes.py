"""批42 · C 节：属性 / 套装词条随机抽取 + 相性池（核心单测）。

依据：`docs/深度打造_决策记录.md` §二 N1~N6、§三 补充 2、§六；
`打造系统_原案_20260919.md` §3/§4/§8/§11/§12。

覆盖：
  · **固定项照抄**：固定属性 / 固定套装词条按图纸声明逐字一致；
  · **条数边界**：`{0,0}` → 0 条、`{2,2}` → 2 条（图纸声明优先，缺省回落 craft_rules）；
  · **相性池命中**：主相性专属池词条可抽；候选带 `_pool` 追溯；
  · **无相性抽不出**：无相性 → `requires_affinity` 词条全部抽不出（负向断言，原案 §12）；
  · **联动覆盖**：main+sub 命中 `affinity_linkage` → 主专属池被 override_pool 覆盖；
  · **副相性参与**：要求 = {main, sub} 的词条在主专属池中可抽（子集语义）；
  · **被动相性变更**：`affinity_variants` 经 `resolve_affinity_effect` 确定性替换；
  · **确定性**：同注入 rng 同结果；质量抽取不被词条抽取影响（批41 对拍）；
  · **校验器 / 字段元数据**：池词条载荷键类型、`blueprint_passive` trait 引用、
    `blueprint_random_set_affix_pool` 池引用；新键编辑器可见。

纪律：**不写任何真实内容包**——相性 id / 池 id / 词条键全为测试自造；随机注入确定性 rng。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional

from qbot_rpg.content.deep_craft_settings import read_deep_craft_settings
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.deep_craft import plan_affixes, plan_craft, resolve_main_sub

# 测试自造相性 / 池 / 词条 id（非任何真实内容包）
A_MAIN = "aff_main"
A_SUB = "aff_sub"
A_OTHER = "aff_other"
P_MAIN = "pool_main"
P_SUB = "pool_sub"
P_LINK = "pool_link"
SET_FIXED = "set_fixed"
SET_RANDOM = "set_random"
PASSIVE_BASE = "passive_base"
PASSIVE_VARIANT = "passive_variant"


class _FakeRng:
    """确定性单值随机源（返回预置 [0,1)）。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.value


def _settings(
    *,
    main_pool: Optional[List[Dict[str, Any]]] = None,
    sub_pool: Optional[List[Dict[str, Any]]] = None,
    link_pool: Optional[List[Dict[str, Any]]] = None,
    linkage: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    pools: List[Dict[str, Any]] = []
    if main_pool is not None:
        pools.append({"id": P_MAIN, "kind": "exclusive", "entries": main_pool})
    if sub_pool is not None:
        pools.append({"id": P_SUB, "kind": "exclusive", "entries": sub_pool})
    if link_pool is not None:
        pools.append({"id": P_LINK, "kind": "linkage", "entries": link_pool})
    return {
        "affinities": [
            {"id": A_MAIN, "exclusive_pool": P_MAIN},
            {"id": A_SUB, "exclusive_pool": P_SUB},
            {"id": A_OTHER, "exclusive_pool": P_SUB},
        ],
        "affinity_pools": pools,
        "affinity_linkage": linkage or [],
        "affinity_reactions": [],
    }


def _mdef(level: int = 15, quality: str = "蓝", cost: int = 10,
          affinities: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    return {"material_level": level, "material_quality": quality, "craft_cost": cost,
            "affinities": affinities or {}}


def _blueprint(**over: Any) -> Dict[str, Any]:
    bp: Dict[str, Any] = {
        "id": "bp1", "name": "测试图纸",
        "blueprint_output": "gear_out", "blueprint_slot": "weapon",
        "blueprint_grade": "铜",
        "blueprint_level_band": {"min": 2, "max": 35},
        "blueprint_material_slots": [{"role": "main", "item": "m_main", "count": 1}],
        "blueprint_fixed_stats": [{"stat": "atk", "value": 10}],
        "affinities": {A_MAIN: 1.0},
    }
    bp.update(over)
    return bp


def _plan_affixes(
    bp: Optional[Dict[str, Any]] = None,
    *,
    settings: Optional[Dict[str, Any]] = None,
    materials: Optional[List[Dict[str, Any]]] = None,
    defs: Optional[Dict[str, Any]] = None,
    rng: Any = None,
    config: Optional[Dict[str, Any]] = None,
    trait_defs: Optional[Dict[str, Any]] = None,
    level: int = 15,
) -> Dict[str, Any]:
    return plan_affixes(
        blueprint=bp or _blueprint(),
        materials=materials if materials is not None else [_mdef(affinities={A_MAIN: 3.0})],
        config=config or read_deep_craft_settings({}),
        rng=rng if rng is not None else random.Random(3),
        affinity_config=settings if settings is not None else _settings(
            main_pool=[{"stat": "fire", "value": 7, "weight": 1,
                        "requires_affinity": A_MAIN}]),
        level=level,
        trait_defs=trait_defs,
    )


# ---------------------------------------------------------------------------
# 1) 固定项照抄（原案 §3/§4）
# ---------------------------------------------------------------------------
def test_fixed_stats_copied_verbatim() -> None:
    """固定属性按图纸声明**照抄**（键/值逐字一致，不加不改）。"""
    bp = _blueprint(blueprint_fixed_stats=[
        {"stat": "atk", "value": 12.5, "value_rule": "ignored_for_now"},
        {"stat": "crit", "value": -3},
    ])
    got = _plan_affixes(bp)
    assert got["fixed_stats"] == {"atk": 12.5, "crit": -3.0}
    assert got["stats_bonus"]["atk"] == 12.5


def test_fixed_set_affix_copied_verbatim() -> None:
    """固定套装词条按 `blueprint_fixed_set_affix` 照抄（原案 §4）。"""
    got = _plan_affixes(_blueprint(blueprint_fixed_set_affix=SET_FIXED))
    assert got["fixed_set_affixes"] == [SET_FIXED]
    assert got["set_affixes"][0] == SET_FIXED


# ---------------------------------------------------------------------------
# 2) 条数边界（图纸声明 0~2，可配；缺省回落 craft_rules）
# ---------------------------------------------------------------------------
def test_count_boundary_zero_and_two() -> None:
    """`blueprint_random_stat_count` = {0,0} → 0 条；{2,2} → 2 条。"""
    pool = [
        {"stat": "s1", "value": 1, "weight": 1, "requires_affinity": A_MAIN},
        {"stat": "s2", "value": 2, "weight": 1, "requires_affinity": A_MAIN},
        {"stat": "s3", "value": 3, "weight": 1, "requires_affinity": A_MAIN},
    ]
    settings = _settings(main_pool=pool)
    zero = _plan_affixes(_blueprint(blueprint_random_stat_count={"min": 0, "max": 0}),
                         settings=settings, rng=random.Random(1))
    two = _plan_affixes(_blueprint(blueprint_random_stat_count={"min": 2, "max": 2}),
                        settings=settings, rng=random.Random(1))
    assert zero["random_stats"] == []
    assert len(two["random_stats"]) == 2
    # 同池不重复（同载荷键去重）
    assert len({r["stat"] for r in two["random_stats"]}) == 2


def test_count_falls_back_to_craft_rules_default() -> None:
    """图纸未声明条数 → 回落 `craft_rules.random_stat_count`（包声明默认）。"""
    cfg = read_deep_craft_settings({"deep_craft": {"craft_rules": {
        "random_stat_count": {"min": 2, "max": 2}}}})
    pool = [{"stat": f"s{i}", "value": i, "weight": 1, "requires_affinity": A_MAIN}
            for i in range(3)]
    got = _plan_affixes(_blueprint(), settings=_settings(main_pool=pool),
                        config=cfg, rng=random.Random(2))
    assert len(got["random_stats"]) == 2


def test_count_candidates_shortfall_does_not_pad() -> None:
    """候选不足声明条数 → 实际条数 = min(声明, 候选)，**不补空**。"""
    pool = [{"stat": "only", "value": 1, "weight": 1, "requires_affinity": A_MAIN}]
    got = _plan_affixes(
        _blueprint(blueprint_random_stat_count={"min": 2, "max": 2}),
        settings=_settings(main_pool=pool), rng=random.Random(1))
    assert [r["stat"] for r in got["random_stats"]] == ["only"]


# ---------------------------------------------------------------------------
# 3) 相性池：主相性命中 / 无相性抽不出 / 副相性参与 / 联动覆盖
# ---------------------------------------------------------------------------
def test_main_affinity_pool_entries_are_drawn() -> None:
    """主相性专属池的词条被抽中，且带 `_pool` 追溯（池查询唯一入口的返回值）。"""
    pool = [
        {"stat": "fire_a", "value": 5, "weight": 1, "requires_affinity": A_MAIN},
        {"stat": "fire_b", "value": 6, "weight": 1, "requires_affinity": A_MAIN},
    ]
    got = _plan_affixes(
        _blueprint(blueprint_random_stat_count={"min": 2, "max": 2}),
        settings=_settings(main_pool=pool), rng=random.Random(5))
    assert {r["stat"] for r in got["random_stats"]} == {"fire_a", "fire_b"}
    assert all(r["pool"] == P_MAIN for r in got["random_stats"])
    assert got["stat_pool_size"] == 2


def test_no_affinity_cannot_draw_affinity_required_entries() -> None:
    """**无对应相性 → 该类词条抽不出来**（原案 §12；负向断言）。"""
    pool = [{"stat": "fire_a", "value": 5, "weight": 1, "requires_affinity": A_MAIN}]
    settings = _settings(main_pool=pool)
    # 图纸与材料都无相性 → main/sub 均 None
    bp = _blueprint(blueprint_fixed_stats=[], affinities={},
                    blueprint_random_stat_count={"min": 2, "max": 2})
    got = _plan_affixes(bp, settings=settings,
                        materials=[_mdef(affinities={})], rng=random.Random(1))
    assert got["affinity"]["main"] is None and got["affinity"]["sub"] is None
    assert got["random_stats"] == []
    assert got["stat_pool_size"] == 0
    # 反证：同一池在有相性时可抽（不是池本身坏了）
    ok = _plan_affixes(bp, settings=settings,
                       materials=[_mdef(affinities={A_MAIN: 4.0})], rng=random.Random(1))
    assert [r["stat"] for r in ok["random_stats"]] == ["fire_a"]


def test_entry_without_requires_affinity_is_drawable_without_affinity() -> None:
    """无相性时，**不要求相性**的通用词条仍可抽（原案「通用池」语义；非死池）。"""
    common = {"id": "pool_common", "kind": "common",
              "entries": [{"stat": "plain", "value": 1, "weight": 1}]}
    settings = _settings()
    settings["affinity_pools"] = [common]
    bp = _blueprint(blueprint_fixed_stats=[], affinities={},
                    blueprint_random_stat_count={"min": 1, "max": 1})
    got = _plan_affixes(bp, settings=settings, materials=[_mdef(affinities={})],
                        rng=random.Random(1))
    assert [r["stat"] for r in got["random_stats"]] == ["plain"]


def test_sub_affinity_participates_via_subset_match() -> None:
    """要求 = {main, sub} 的词条在主专属池中，副相性到位时可抽（子集语义）。"""
    pool = [
        {"stat": "pair_only", "value": 9, "weight": 1,
         "requires_affinity": [A_MAIN, A_SUB]},
    ]
    settings = _settings(main_pool=pool)
    bp = _blueprint(blueprint_fixed_stats=[], affinities={A_MAIN: 1.0},
                    blueprint_random_stat_count={"min": 1, "max": 1})
    with_sub = _plan_affixes(bp, settings=settings,
                             materials=[_mdef(affinities={A_MAIN: 3.0, A_SUB: 2.0})],
                             rng=random.Random(1))
    without_sub = _plan_affixes(bp, settings=settings,
                                materials=[_mdef(affinities={A_MAIN: 3.0})],
                                rng=random.Random(1))
    assert with_sub["affinity"]["sub"] == A_SUB
    assert [r["stat"] for r in with_sub["random_stats"]] == ["pair_only"]
    assert without_sub["random_stats"] == []      # 副相性缺失 → 抽不出


def test_linkage_overrides_exclusive_pool() -> None:
    """main+sub 命中联动 → 主专属池被 override_pool **覆盖**（原案 §8/§12）。"""
    settings = _settings(
        main_pool=[{"stat": "exclusive_only", "value": 1, "weight": 1,
                    "requires_affinity": A_MAIN}],
        link_pool=[{"stat": "linkage_only", "value": 99, "weight": 1,
                    "requires_affinity": [A_MAIN, A_SUB]}],
        linkage=[{"main": A_MAIN, "sub": A_SUB, "override_pool": P_LINK}],
    )
    bp = _blueprint(blueprint_fixed_stats=[], affinities={A_MAIN: 1.0},
                    blueprint_random_stat_count={"min": 2, "max": 2})
    got = _plan_affixes(
        bp, settings=settings,
        materials=[_mdef(affinities={A_MAIN: 3.0, A_SUB: 2.0})], rng=random.Random(4))
    assert got["affinity"]["main"] == A_MAIN and got["affinity"]["sub"] == A_SUB
    assert [r["stat"] for r in got["random_stats"]] == ["linkage_only"]
    assert got["random_stats"][0]["pool"] == P_LINK
    # 副相性缺失 → 联动不命中 → 回到主专属池
    no_link = _plan_affixes(
        bp, settings=settings,
        materials=[_mdef(affinities={A_MAIN: 3.0})], rng=random.Random(4))
    assert [r["stat"] for r in no_link["random_stats"]] == ["exclusive_only"]


# ---------------------------------------------------------------------------
# 4) 随机套装词条（0~2）+ 固定项不重复
# ---------------------------------------------------------------------------
def test_random_set_affixes_from_pool_and_exclude_fixed() -> None:
    """随机套装词条从池抽；**不复抽**固定套装词条，并去重。"""
    pool = [
        {"set_affix": SET_FIXED, "weight": 1, "requires_affinity": A_MAIN},
        {"set_affix": SET_RANDOM, "weight": 1, "requires_affinity": A_MAIN},
        {"set_affix": "set_third", "weight": 1, "requires_affinity": A_MAIN},
    ]
    bp = _blueprint(blueprint_fixed_set_affix=SET_FIXED,
                    blueprint_random_set_affix_count={"min": 2, "max": 2})
    got = _plan_affixes(bp, settings=_settings(main_pool=pool), rng=random.Random(1))
    assert got["fixed_set_affixes"] == [SET_FIXED]
    assert SET_FIXED not in got["random_set_affixes"]     # 固定项被排除
    assert len(got["random_set_affixes"]) == 2
    assert len(set(got["set_affixes"])) == len(got["set_affixes"])


def test_random_set_affix_pool_field_narrows_candidates() -> None:
    """`blueprint_random_set_affix_pool` 声明 → 在已解析候选中按池 id 收窄。"""
    settings = _settings(
        main_pool=[{"set_affix": "from_main", "weight": 1, "requires_affinity": A_MAIN}],
        sub_pool=[{"set_affix": "from_sub", "weight": 1, "requires_affinity": A_SUB}],
    )
    bp = _blueprint(blueprint_fixed_stats=[], affinities={A_MAIN: 1.0},
                    blueprint_random_set_affix_pool=P_SUB,
                    blueprint_random_set_affix_count={"min": 1, "max": 1})
    # 主专属池内没有 set_affix 命中声明池 → 抽不出（声明池需可达）
    got = _plan_affixes(bp, settings=settings,
                        materials=[_mdef(affinities={A_MAIN: 3.0})], rng=random.Random(1))
    assert got["set_affix_pool_size"] == 0 and got["random_set_affixes"] == []
    # 去掉收窄 → 主专属池可抽
    bp2 = _blueprint(blueprint_fixed_stats=[], affinities={A_MAIN: 1.0},
                     blueprint_random_set_affix_count={"min": 1, "max": 1})
    got2 = _plan_affixes(bp2, settings=settings,
                         materials=[_mdef(affinities={A_MAIN: 3.0})], rng=random.Random(1))
    assert got2["random_set_affixes"] == ["from_main"]


# ---------------------------------------------------------------------------
# 5) 主/副判定与被动相性变更（原案 §8/§11）
# ---------------------------------------------------------------------------
def test_rank_tie_broken_by_declaration_order() -> None:
    """主/副并列 → 按内容包 `affinities[]` 声明顺序破平（确定性）。"""
    materials = [_mdef(affinities={A_MAIN: 5.0, A_SUB: 5.0})]
    # 无 order → id 升序（测试自造 id：aff_main < aff_sub）
    default_rank = resolve_main_sub(_blueprint(affinities={}), materials)
    assert default_rank["main"] == A_MAIN and default_rank["sub"] == A_SUB
    # 有 order → 声明序（aff_sub 先声明 → 主）
    ordered = resolve_main_sub(
        _blueprint(affinities={}), materials,
        affinity_order=[{"id": A_SUB}, {"id": A_MAIN}])
    assert ordered["main"] == A_SUB and ordered["sub"] == A_MAIN


def test_passive_affinity_variant_resolved() -> None:
    """`affinity_variants` 经 `resolve_affinity_effect` 确定性替换（原案 §11）。"""
    traits = {PASSIVE_BASE: {"affinity_variants": {f"{A_MAIN}|{A_SUB}": PASSIVE_VARIANT,
                                                   A_MAIN: "passive_main_only"}}}
    bp = _blueprint(blueprint_passive=PASSIVE_BASE)
    settings = _settings(main_pool=[])
    got = _plan_affixes(bp, settings=settings,
                        materials=[_mdef(affinities={A_MAIN: 3.0, A_SUB: 2.0})],
                        trait_defs=traits, rng=random.Random(1))
    assert got["passives"] == [PASSIVE_VARIANT]     # main|sub 优先
    only_main = _plan_affixes(bp, settings=settings,
                              materials=[_mdef(affinities={A_MAIN: 3.0})],
                              trait_defs=traits, rng=random.Random(1))
    assert only_main["passives"] == ["passive_main_only"]


def test_passive_without_variant_kept_verbatim() -> None:
    """无 `affinity_variants` 的被动原样保留（「部分可变更」的不可变那一半）。"""
    got = _plan_affixes(_blueprint(blueprint_passive=PASSIVE_BASE),
                        trait_defs={PASSIVE_BASE: {"effects": []}}, rng=random.Random(1))
    assert got["passives"] == [PASSIVE_BASE]


# ---------------------------------------------------------------------------
# 6) 确定性（同 rng 同结果）+ 质量抽取不受影响（批41 对拍）
# ---------------------------------------------------------------------------
def test_same_rng_same_result() -> None:
    """注入确定性 rng → 同种子同结果（随机属性 + 套装词条 + 被动）。"""
    pool = [{"stat": f"s{i}", "value": i, "weight": 1, "requires_affinity": A_MAIN}
            for i in range(4)]
    pool += [{"set_affix": f"set{i}", "weight": 1, "requires_affinity": A_MAIN}
             for i in range(4)]
    settings = _settings(main_pool=pool)
    bp = _blueprint(blueprint_fixed_set_affix=SET_FIXED,
                    blueprint_random_stat_count={"min": 2, "max": 2},
                    blueprint_random_set_affix_count={"min": 1, "max": 2})
    a = _plan_affixes(bp, settings=settings, rng=random.Random(20260919))
    b = _plan_affixes(bp, settings=settings, rng=random.Random(20260919))
    assert a["random_stats"] == b["random_stats"]
    assert a["set_affixes"] == b["set_affixes"]
    assert a["stats_bonus"] == b["stats_bonus"]


def test_quality_draw_not_disturbed_by_affix_planning() -> None:
    """词条抽取放在 quality 之后 → **同种子 quality 结果不变**（批41 回归对拍）。"""
    defs = {"m_main": _mdef(15, "紫", 30, affinities={A_MAIN: 2.0})}
    mats = [{"id": "m_main", "count": 2}]
    cfg = read_deep_craft_settings({})
    bp = _blueprint(blueprint_random_stat_count={"min": 2, "max": 2})
    settings = _settings(main_pool=[{"stat": f"s{i}", "value": i, "weight": 1,
                                     "requires_affinity": A_MAIN} for i in range(3)])
    plain = plan_craft(blueprint=bp, config=cfg, materials=mats, material_defs=defs,
                       learned=True, rng=random.Random(77))
    with_aff = plan_craft(blueprint=bp, config=cfg, materials=mats, material_defs=defs,
                          learned=True, rng=random.Random(77), affinity_config=settings)
    assert plain["quality"] == with_aff["quality"]
    assert plain["color_row"] == with_aff["color_row"]


# ---------------------------------------------------------------------------
# 7) plan_craft 集成：新字段随成功计划返回
# ---------------------------------------------------------------------------
def test_plan_craft_returns_affix_plan() -> None:
    pool = [{"stat": "s1", "value": 5, "weight": 1, "requires_affinity": A_MAIN},
            {"set_affix": SET_RANDOM, "weight": 1, "requires_affinity": A_MAIN}]
    bp = _blueprint(blueprint_random_stat_count={"min": 1, "max": 1},
                    blueprint_random_set_affix_count={"min": 1, "max": 1})
    plan = plan_craft(blueprint=bp, config=read_deep_craft_settings({}),
                      materials=[{"id": "m_main", "count": 1}],
                      material_defs={"m_main": _mdef(15, "蓝", 10, {A_MAIN: 3.0})},
                      learned=True, rng=random.Random(9),
                      affinity_config=_settings(main_pool=pool))
    assert plan["ok"] is True
    assert plan["affinity"]["main"] == A_MAIN
    assert plan["stats_bonus"]["atk"] == 10.0       # 固定项仍在
    assert [r["stat"] for r in plan["random_stats"]] == ["s1"]
    assert plan["set_affixes"] == [SET_RANDOM]


# ---------------------------------------------------------------------------
# 8) 校验器 + 字段元数据
# ---------------------------------------------------------------------------
def _check(modules: Dict[str, Any]) -> Any:
    return check_pack(modules, default_field_meta_table())


def _pack_modules(items: List[Dict[str, Any]], **settings_over: Any) -> Dict[str, Any]:
    settings: Dict[str, Any] = {
        "deep_craft": {"enabled": True},
        "slot_defs": {"weapon": {}},
        "affinities": [{"id": A_MAIN, "exclusive_pool": P_MAIN}],
        "affinity_pools": [{"id": P_MAIN, "kind": "exclusive",
                            "entries": [{"stat": "s", "value": 1, "weight": 1,
                                         "requires_affinity": A_MAIN}]}],
    }
    settings.update(settings_over)
    return {"settings": settings, "items": items,
            "traits": [{"id": PASSIVE_BASE, "name": "被动", "effects": []}]}


def test_validator_rejects_bad_pool_entry_and_refs() -> None:
    """门禁更严：池词条载荷键类型 / 被动 trait 引用 / 随机套装词条池引用。"""
    mods = _pack_modules([
        {"id": "bp_bad", "name": "图", "blueprint_output": "g1",
         "blueprint_slot": "weapon", "blueprint_grade": "铜",
         "blueprint_passive": "不存在的被动",
         "blueprint_random_set_affix_pool": "不存在的池"},
        {"id": "g1", "name": "装备"},
    ])
    mods["settings"]["affinity_pools"][0]["entries"] = [
        {"stat": "", "weight": -1, "value": "x"}]
    rep = _check(mods)
    rules = {e.detail.get("rule") for e in rep.errors}
    assert "trait_ref_missing" in rules
    assert "pool_ref_missing" in rules
    assert "type" in rules and "range" in rules

    ok = _pack_modules([
        {"id": "bp_ok", "name": "图", "blueprint_output": "g1",
         "blueprint_slot": "weapon", "blueprint_passive": PASSIVE_BASE,
         "blueprint_random_set_affix_pool": P_MAIN},
        {"id": "g1", "name": "装备"},
    ])
    rep2 = _check(ok)
    assert not [e for e in rep2.errors if e.module == "items"], \
        [(e.field, e.detail) for e in rep2.errors]


def test_pool_entry_payload_keys_are_editor_visible() -> None:
    """新增池词条载荷键（`value` / `set_affix`）编辑器可见（中文名）。"""
    table = default_field_meta_table()
    settings = table.module("settings")
    assert settings is not None
    entries = settings.fields["affinity_pools"].element.children["entries"]
    entry = entries.element
    assert entry is not None
    for key in ("stat", "set_affix", "value", "weight", "requires_affinity",
                "effect_ref"):
        assert key in entry.children, f"池词条缺字段元数据：{key}"
        assert entry.children[key].label, f"{key} 缺中文名"
