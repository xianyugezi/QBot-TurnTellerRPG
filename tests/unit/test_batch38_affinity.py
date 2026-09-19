"""批38 · ④ 相性通用层单测（纯函数互动/主副判定/池查询/引用校验/编辑器可见）。

依据：`docs/深度打造_决策记录.md` §三 补充 2（通用机制、非打造私有、深炼金共用）；
`打造系统_原案_20260919.md` §8/§12（材料相性词缀；互动冲突/增幅/反转；按投入顺序；
主=最高副=第二；通用池+专属池；联动覆盖专属池；无相性 → 词条抽不出）。

测试只构造内存配置/模块映射，不写真实内容包。
"""
from __future__ import annotations

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.affinity import (
    accumulate_affinity,
    normalize_affinity_config,
    rank_affinities,
    resolve_affinity_effect,
    resolve_available_entries,
)

# 通用测试配置（相性 id/池 id 均为测试用假名，非内容包业务名）
CFG = {
    "affinities": [
        {"id": "a_x", "name": "X", "exclusive_pool": "p_x"},
        {"id": "a_y", "name": "Y", "exclusive_pool": "p_y"},
    ],
    "affinity_pools": [
        {"id": "p_common", "kind": "common",
         "entries": [{"stat": "s_common", "weight": 10}]},
        {"id": "p_x", "kind": "exclusive",
         "entries": [{"stat": "s_x", "weight": 5, "requires_affinity": "a_x"},
                     {"stat": "s_any", "weight": 3}]},
        {"id": "p_y", "kind": "exclusive",
         "entries": [{"stat": "s_y", "requires_affinity": "a_y"}]},
        {"id": "p_link", "kind": "linkage",
         "entries": [{"stat": "s_link", "requires_affinity": "a_x"}]},
    ],
    "affinity_linkage": [{"main": "a_x", "sub": "a_y", "override_pool": "p_link"}],
    "affinity_reactions": [
        {"kind": "conflict", "pair": ["a_x", "a_y"], "value": 3},
        {"kind": "amplify", "pair": ["a_x", "a_y"], "value": 2},
        {"kind": "reverse", "from": "a_y", "to": "a_x", "value": 1.0},
    ],
}

_REACT = {k: v for k, v in CFG.items() if k == "affinity_reactions"}


# ===========================================================================
# A. 材料互动：冲突 / 增幅 / 反转（纯函数）
# ===========================================================================
def test_accumulate_conflict_reduces_both() -> None:
    out = accumulate_affinity([{"a_x": 10}, {"a_y": 10}],
                              [{"kind": "conflict", "pair": ["a_x", "a_y"], "value": 3}])
    assert out == {"a_x": 7.0, "a_y": 7.0}


def test_accumulate_amplify_increases_both() -> None:
    out = accumulate_affinity([{"a_x": 10}, {"a_y": 10}],
                              [{"kind": "amplify", "pair": ["a_x", "a_y"], "value": 2}])
    assert out == {"a_x": 12.0, "a_y": 12.0}


def test_accumulate_reverse_moves_accumulated_value() -> None:
    """反转：材料携带 from 时，把已累计的 from 转成 to（比例/全额）。"""
    out = accumulate_affinity([{"a_x": 4}, {"a_y": 10}],
                              [{"kind": "reverse", "from": "a_y", "to": "a_x", "value": 1.0}])
    # 第一次 a_y 投入尚无累计 a_y → 不转；随后 a_y 10 入池
    assert out == {"a_x": 4.0, "a_y": 10.0}


def test_accumulate_settlement_order_is_investment_order() -> None:
    """结算顺序 = 材料投入顺序：反转下换序 → 不同结果（纯函数、可测）。"""
    rev = [{"kind": "reverse", "from": "a_y", "to": "a_x", "value": 1.0}]
    out1 = accumulate_affinity([{"a_y": 10}, {"a_y": 5}], rev)
    out2 = accumulate_affinity([{"a_y": 5}, {"a_y": 10}], rev)
    assert out1 == {"a_x": 10.0, "a_y": 5.0}
    assert out2 == {"a_x": 5.0, "a_y": 10.0}
    assert out1 != out2


def test_accumulate_never_negative_and_does_not_mutate_inputs() -> None:
    contribs = [{"a_x": 1}, {"a_y": 10}]
    rules = [{"kind": "conflict", "pair": ["a_x", "a_y"], "value": 999}]
    snapshot = [dict(c) for c in contribs]
    out = accumulate_affinity(contribs, rules)
    assert out["a_x"] == 0.0 and out["a_y"] == 0.0  # 负值截零
    assert contribs == snapshot
    # 同参同值（确定性）
    assert accumulate_affinity(contribs, rules) == out


# ===========================================================================
# B. 主/副相性判定
# ===========================================================================
def test_rank_main_sub_and_deterministic_tie_break() -> None:
    order = CFG["affinities"]
    r = rank_affinities({"a_x": 3, "a_y": 9}, order)
    assert (r["main"], r["sub"]) == ("a_y", "a_x")
    # 并列 → 按声明顺序（a_x 先声明 → 主）
    tie = rank_affinities({"a_x": 5, "a_y": 5}, order)
    assert tie["main"] == "a_x" and tie["sub"] == "a_y"
    assert rank_affinities({}, order)["main"] is None
    assert rank_affinities({"a_x": 0})["main"] is None  # ≤0 不算入


# ===========================================================================
# C. 池查询单一接口（无相性 → 抽不出）
# ===========================================================================
def test_resolve_entries_common_union_exclusive() -> None:
    cfg = normalize_affinity_config(CFG)
    stats = [e["stat"] for e in resolve_available_entries(cfg, "a_x")]
    assert stats == ["s_common", "s_x", "s_any"]
    # 无相性 → 仅通用池，要求相性的词条抽不出
    assert [e["stat"] for e in resolve_available_entries(cfg)] == ["s_common"]


def test_resolve_entries_linkage_overrides_exclusive() -> None:
    cfg = normalize_affinity_config(CFG)
    stats = [e["stat"] for e in resolve_available_entries(cfg, "a_x", "a_y")]
    # 联动命中 → 专属池被 override_pool 覆盖：s_x/s_any 消失，只留通用 + s_link
    assert stats == ["s_common", "s_link"]


def test_resolve_entries_level_filter_and_pool_trace() -> None:
    cfg = normalize_affinity_config({
        "affinities": [{"id": "a_x", "exclusive_pool": "p_x"}],
        "affinity_pools": [{"id": "p_x", "kind": "exclusive",
                            "entries": [{"stat": "s_hi", "min_level": 10,
                                         "requires_affinity": "a_x"}]}],
    })
    assert resolve_available_entries(cfg, "a_x", level=9) == []
    got = resolve_available_entries(cfg, "a_x", level=10)
    assert got and got[0]["stat"] == "s_hi" and got[0]["_pool"] == "p_x"


def test_resolve_entries_accepts_raw_settings_and_is_pure() -> None:
    raw = dict(CFG)
    before = repr(raw)
    out = resolve_available_entries(raw, "a_x")
    assert [e["stat"] for e in out] == ["s_common", "s_x", "s_any"]
    assert repr(raw) == before  # 不修改入参
    assert out == resolve_available_entries(raw, "a_x")  # 确定性


# ===========================================================================
# D. 深度炼金接入点（稳定 API，本批不消费）
# ===========================================================================
def test_resolve_affinity_effect_lookup_order() -> None:
    table = {"a_x|a_y": "specific", "a_x": "generic"}
    assert resolve_affinity_effect(table, "a_x", "a_y") == "specific"
    assert resolve_affinity_effect(table, "a_x", None) == "generic"
    assert resolve_affinity_effect(table, "a_y") is None
    assert resolve_affinity_effect(None, "a_x") is None


# ===========================================================================
# E. 编辑器可见 + 引用校验
# ===========================================================================
def test_editor_metadata_exposes_affinity_sections() -> None:
    table = default_field_meta_table()
    settings_meta = table.module("settings")
    assert settings_meta is not None
    for key, label in (("affinities", "相性定义"), ("affinity_pools", "相性词条池"),
                       ("affinity_linkage", "相性联动"),
                       ("affinity_reactions", "材料相性互动")):
        fm = settings_meta.fields[key]
        assert fm.type == "list" and fm.label == label and fm.help
    # 材料/图纸相性声明（items∪equipment）
    for mod in ("items", "equipment"):
        mmeta = table.module(mod)
        assert mmeta is not None
        aff = mmeta.fields["affinities"]
        assert aff.label == "相性" and aff.help


def _errs(mods: dict) -> list:
    return [(e.field, e.detail.get("rule")) for e in check_pack(mods).errors]


def test_validator_affinity_refs_and_enums() -> None:
    good = {"settings": dict(CFG)}
    assert _errs(good) == []
    # 专属池引用缺失
    bad_pool = {"settings": {"affinities": [{"id": "a_x", "exclusive_pool": "nope"}]}}
    assert ("settings.affinities.0.exclusive_pool", "pool_ref_missing") in _errs(bad_pool)
    # 池 kind 非法
    bad_kind = {"settings": {"affinity_pools": [{"id": "p1", "kind": "weird"}]}}
    assert any(r == "enum_invalid" for _, r in _errs(bad_kind))
    # 词条 requires_affinity 引用缺失
    bad_req = {"settings": {"affinity_pools": [{"id": "p1", "kind": "exclusive",
                                                "entries": [{"requires_affinity": "ghost"}]}]}}
    assert any(r == "affinity_ref_missing" for _, r in _errs(bad_req))
    # 联动引用缺失
    bad_link = {"settings": {"affinities": [{"id": "a_x"}],
                             "affinity_linkage": [{"main": "a_x", "sub": "ghost"}]}}
    assert any(r == "affinity_ref_missing" for _, r in _errs(bad_link))
    # 互动 kind 非法 + pair 引用缺失
    bad_react = {"settings": {"affinities": [{"id": "a_x"}],
                              "affinity_reactions": [{"kind": "nope"}]}}
    assert any(r == "enum_invalid" for _, r in _errs(bad_react))
    bad_pair = {"settings": {"affinities": [{"id": "a_x"}],
                             "affinity_reactions": [
                                 {"kind": "conflict", "pair": ["a_x", "ghost"], "value": 1}]}}
    assert any(r == "affinity_ref_missing" for _, r in _errs(bad_pair))
    bad_rev = {"settings": {"affinities": [{"id": "a_x"}],
                            "affinity_reactions": [{"kind": "reverse", "from": "a_x"}]}}
    assert any(r == "required_missing" for _, r in _errs(bad_rev))


def test_validator_material_affinity_keys_must_be_declared() -> None:
    ok = {"settings": {"affinities": [{"id": "a_x"}]},
          "items": [{"id": "m1", "name": "m1", "type": "材料", "affinities": {"a_x": 3}}]}
    assert _errs(ok) == []
    bad = {"settings": {"affinities": [{"id": "a_x"}]},
           "items": [{"id": "m1", "name": "m1", "type": "材料", "affinities": {"ghost": 3}}]}
    assert any(r == "affinity_ref_missing" for _, r in _errs(bad))


def test_validator_duplicate_affinity_id_red() -> None:
    dup = {"settings": {"affinities": [{"id": "a_x"}, {"id": "a_x"}]}}
    assert any(r == "duplicate_id" for _, r in _errs(dup))
