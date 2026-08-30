"""M9 锻造·批7·路7A：套装结构服务单元测试（tests/unit/test_forge_sets.py）。

文件名：test_forge_sets.py
创建时间：2026-08-30
作者：Hermes 子agent-7A（M9 锻造实现组批7·路7A：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_sets.py；不改动批0 既有文件、fixtures）

依据：docs/细化/细化_2c2d_锻造套装与客制.md（§一 SET-01~08/SK-01~04、§1.3 ACT-01~06、
  §1.4 VAR-01~03、§五 校验器 V1~V8/W1~W4）+ docs/m9_shared_contract.md（§四 Set、
  §六 2c2d 校验）+ qbot_rpg/content/forge_models.py（批0 Def/validate_forge 复用）。
测试目标：qbot_rpg.core.forge_sets 四服务（parse_sets / validate_sets / set_lookup /
  set_effects_contract）全方法 + 真实 test_demo forge.json 兼容。

覆盖矩阵：
  A parse 双形态：alpha 全字段 / beta 引用 variant（继承同族 alpha skills，VAR-01）/
    无 sets 段→空集 / beta 无同族 alpha→交 V3 / 真实 test_demo（空 sets）
  B validate：V1 集合查重 / V2 件数范围 / V3 技能引用存在（红拦）；委托批0 V2 节点引用；
    合法零错；W1 件数不足建议 / W2 技能描述缺 / W3 无套装数 / W4 同族单记录（黄）
  C set_lookup：ready 判定（2 件可激活/1 件不可）、VAR-03 混穿族级合并、set_tracker 源、
    空装配兜底、raw dict sets 双形态
  D 契约展开：skill_id/触发段/占位描述/接线描述/非法 set 兜底

铁律：零 NoneBot import；纯函数确定性；不写定时器/睡眠调用；不引入随机。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Mapping, cast

from qbot_rpg.core.forge_sets import (
    FULL_SET_PIECES,
    MIN_ACTIVATE_PIECES,
    parse_sets,
    set_effects_contract,
    set_lookup,
    validate_sets,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"

# ---------------------------------------------------------------------------
# 夹具辅助
# ---------------------------------------------------------------------------
def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _armor_tree(node_type: str, node_id: str, slots: List[int] | None = None) -> Dict[str, object]:
    """最小合法防具树（批0 V1/V6/V7/V11/V12 可过：1 节点、final、item、materials、level1）。"""
    node: Dict[str, object] = {
        "id": node_id, "name": node_id, "type": node_type, "level": 1,
        "parent": None, "materials": [{"item": "m_ore", "count": 1}],
        "item": "it_%s" % node_id, "final": True,
    }
    if slots:
        node["slots"] = [{"level": s} for s in slots]
    return {"id": "tree_%s" % node_type, "name": node_type, "type": node_type,
            "roots": [node_id], "nodes": [node]}


def _five_armor_trees() -> List[Dict[str, object]]:
    """五部位树（n_<part>_a 每部位一个节点），供套装件引用存在（V2 委托批0 通过）。"""
    parts = [("armor_head", "n_head_a"), ("armor_body", "n_body_a"),
             ("armor_hand", "n_hand_a"), ("armor_leg", "n_leg_a"),
             ("armor_foot", "n_foot_a")]
    return [_armor_tree(t, nid) for t, nid in parts]


def _alpha_set(**over: object) -> Dict[str, object]:
    """合法 alpha 套装（5 件 + 2/3/5 三档 + effect_ref 接线，无 W1~W4/无红拦）。"""
    base: Dict[str, object] = {
        "id": "set_dk", "name": "龙骑士套装", "variant": "alpha",
        "pieces": ["n_head_a", "n_body_a", "n_hand_a", "n_leg_a", "n_foot_a"],
        "skills": [
            {"piece_count": 2, "skill": "dragon_guard", "level": 1, "effect_ref": "ref_guard"},
            {"piece_count": 3, "skill": "dragon_guard", "level": 2, "effect_ref": "ref_guard"},
            {"piece_count": 5, "skill": "dragon_guard", "level": 3, "effect_ref": "ref_guard"},
        ],
        "desc": "龙之加护寄宿的勇者之铠", "enabled": True, "codex_group": "set_dk",
    }
    base.update(over)
    return base


def _beta_set(**over: object) -> Dict[str, object]:
    """合法 beta 套装（引用 alpha 档位——缺 skills 由 parse_sets 继承；F-1/VAR-01）。"""
    base: Dict[str, object] = {
        "id": "set_dk", "name": "龙骑士套装β", "variant": "beta",
        "pieces": ["n_head_a", "n_body_a", "n_hand_a", "n_leg_a", "n_foot_a"],
    }
    base.update(over)
    return base


def _modules(sets: List[Dict[str, object]] | None = None, *,
             trees: List[Dict[str, object]] | None = None,
             settings: Mapping[str, object] | None = None) -> Dict[str, object]:
    """构造 modules dict（forge 顶层 obj；trees 缺省=五部位防具树）。"""
    forge: Dict[str, object] = {"schema_version": "1.0"}
    if trees is not None:
        forge["trees"] = trees
    else:
        forge["trees"] = _five_armor_trees()
    forge["sets"] = sets if sets is not None else []
    if settings is not None:
        forge["settings"] = settings
    return {"forge": forge}


# ---------------------------------------------------------------------------
# A parse 双形态
# ---------------------------------------------------------------------------
def test_parse_alpha_full_field() -> None:
    """正例：alpha 全字段解析 → 批0 ForgeSet（SET-01~08 各访问器可读）。"""
    parsed = parse_sets(_modules([_alpha_set()]))
    assert len(parsed) == 1
    s = parsed[0]
    assert s.id == "set_dk"
    assert s.name == "龙骑士套装"
    assert s.variant == "alpha"
    assert s.pieces == ("n_head_a", "n_body_a", "n_hand_a", "n_leg_a", "n_foot_a")
    assert len(s.skill_defs()) == 3
    assert s.skill_defs()[0].piece_count == 2
    assert s.skill_defs()[0].level == 1
    assert s.desc == "龙之加护寄宿的勇者之铠"
    assert s.enabled is True
    assert s.codex_group == "set_dk"


def test_parse_beta_inherits_alpha_skills() -> None:
    """正例：beta 缺 skills → 继承同族 alpha 档位（VAR-01 档位共享），raw 附追溯键。"""
    parsed = parse_sets(_modules([_alpha_set(), _beta_set()]))
    assert len(parsed) == 2
    beta = parsed[1]
    assert beta.variant == "beta"
    assert len(beta.skill_defs()) == 3
    assert [sk.piece_count for sk in beta.skill_defs()] == [2, 3, 5]
    assert beta.raw.get("_skills_inherited_from") == "set_dk:alpha"
    # alpha 不受影响
    assert parsed[0].raw.get("_skills_inherited_from") is None


def test_parse_no_sets_returns_empty() -> None:
    """正例：无 sets 段（缺失）/空段 → []（合法空集，不报错）。"""
    assert parse_sets(_modules(None)) == []
    assert parse_sets(_modules([])) == []
    assert parse_sets({"forge": {"schema_version": "1.0"}}) == []
    assert parse_sets({}) == []
    assert parse_sets({"forge": "not-a-map"}) == []


def test_parse_beta_without_alpha_keeps_missing() -> None:
    """正例：beta 无同族 alpha → skills 保持缺省（交 validate V3 红拦，防隐式空档）。"""
    parsed = parse_sets(_modules([_beta_set()]))
    assert len(parsed) == 1
    assert parsed[0].variant == "beta"
    assert parsed[0].skill_defs() == ()


def test_parse_real_test_demo_forge() -> None:
    """正例：真实 test_demo forge.json（sets 空段）→ [] 兼容。"""
    forge = cast(Mapping, _load_json(_FORGE_JSON))
    assert parse_sets({"forge": forge}) == []


# ---------------------------------------------------------------------------
# B validate：V1~V3 红拦 + W1~W4 黄 + 委托批0
# ---------------------------------------------------------------------------
def _rules(result: Mapping[str, object], key: str) -> List[str]:
    return [str(e.get("rule")) for e in cast(List[Mapping[str, object]], result[key])]


def test_validate_ok_clean() -> None:
    """正例：合法 α/β 双记录（5 件 + 档位 + effect_ref）→ ok=True，零红零黄。"""
    res = validate_sets(_modules([_alpha_set(), _beta_set()]))
    assert res["ok"] is True
    assert res["sets_count"] == 2
    assert res["families"] == ["set_dk"]
    assert res["errors"] == []
    assert res["warnings"] == []


def test_validate_v1_duplicate_combo() -> None:
    """负例 V1：同族同 variant 重复（(id,variant) 组合查重）→ 硬错误。"""
    res = validate_sets(_modules([_alpha_set(), _alpha_set()]))
    assert res["ok"] is False
    assert "set_variant_duplicate" in _rules(res, "errors")
    v1 = [e for e in cast(List[Dict[str, object]], res["errors"])
          if e.get("rule") == "set_variant_duplicate"]
    assert v1 and v1[0]["level"] == "V1"


def test_validate_v2_pieces_too_many() -> None:
    """负例 V2：件数范围——pieces 超 5 项 → 硬错误。"""
    bad = _alpha_set(pieces=["n_head_a", "n_body_a", "n_hand_a", "n_leg_a", "n_foot_a", "n_extra"])
    res = validate_sets(_modules([bad]))
    assert res["ok"] is False
    assert "set_pieces_too_many" in _rules(res, "errors")


def test_validate_v2_pieces_required() -> None:
    """负例 V2：pieces 空/缺失 → 硬错误。"""
    res = validate_sets(_modules([_alpha_set(pieces=[])]))
    assert res["ok"] is False
    assert "set_pieces_required" in _rules(res, "errors")


def test_validate_v3_skills_required() -> None:
    """负例 V3：技能引用——skills 空 → 硬错误。"""
    res = validate_sets(_modules([_alpha_set(skills=[])]))
    assert res["ok"] is False
    assert "set_skills_required" in _rules(res, "errors")


def test_validate_v3_skill_id_empty() -> None:
    """负例 V3：技能引用——skill id 空 → 硬错误。"""
    bad_skills = [{"piece_count": 2, "skill": "", "level": 1}]
    res = validate_sets(_modules([_alpha_set(skills=bad_skills)]))
    assert res["ok"] is False
    assert "set_skill_id_required" in _rules(res, "errors")


def test_validate_v3_piece_count_invalid() -> None:
    """负例 V3：piece_count ∉ {2,3,5} → 硬错误。"""
    bad_skills = [{"piece_count": 4, "skill": "dragon_guard", "level": 1}]
    res = validate_sets(_modules([_alpha_set(skills=bad_skills)]))
    assert res["ok"] is False
    assert "set_skill_piece_count_invalid" in _rules(res, "errors")


def test_validate_v3_level_invalid() -> None:
    """负例 V3：level ∉ {1,2,3}（默认封顶 3）→ 硬错误。"""
    bad_skills = [{"piece_count": 2, "skill": "dragon_guard", "level": 0}]
    res = validate_sets(_modules([_alpha_set(skills=bad_skills)]))
    assert res["ok"] is False
    assert "set_skill_level_invalid" in _rules(res, "errors")


def test_validate_delegates_batch0_piece_missing() -> None:
    """负例：委托批0 V2——pieces 引用 forge 树未定义节点 → 硬错误（source=batch0）。"""
    bad = _alpha_set(pieces=["n_head_a", "n_body_a", "n_ghost_a", "n_leg_a", "n_foot_a"])
    res = validate_sets(_modules([bad]))
    assert res["ok"] is False
    assert "set_piece_missing" in _rules(res, "errors")
    missing = [e for e in cast(List[Dict[str, object]], res["errors"])
               if e.get("rule") == "set_piece_missing"]
    assert missing and missing[0]["source"] == "batch0"
    # 批0 field 为索引式定位（forge.sets.0.pieces.2 = 第 3 件 n_ghost_a）
    assert str(missing[0]["field"]) == "forge.sets.0.pieces.2"


def test_validate_structure_fallback_without_trees() -> None:
    """负例：forge 无 trees 键（批0 短路）→ 本路纯结构 V1~V3 兜底仍可验（source=route7a）。"""
    # forge 顶层无 trees：批0 validate_forge 直接 return（trees 非 list 短路），
    # sets 校验不执行 → 本路 _check_structure_v 兜底报 V1 查重
    modules = {"forge": {"sets": [_alpha_set(), _alpha_set()]}}
    res = validate_sets(modules)
    assert res["ok"] is False
    dup = [e for e in cast(List[Dict[str, object]], res["errors"])
           if e.get("rule") == "set_variant_duplicate"]
    assert dup and dup[0]["source"] == "route7a"


def test_validate_w1_pieces_under_5() -> None:
    """黄 W1：件数不足建议——pieces 3 件无法达成 5 件满配档 → 黄不拦。"""
    bad = _alpha_set(pieces=["n_head_a", "n_body_a", "n_hand_a"])
    res = validate_sets(_modules([bad]))
    assert res["ok"] is True
    assert "set_pieces_under_5" in _rules(res, "warnings")
    w1 = [w for w in cast(List[Dict[str, object]], res["warnings"])
          if w.get("rule") == "set_pieces_under_5"]
    assert w1 and w1[0]["level"] == "W1"


def test_validate_w2_effect_ref_missing() -> None:
    """黄 W2：技能描述缺——effect_ref 空=占位技能（SK-04）→ 黄不拦；接线非空 → 无 W2。"""
    no_effect = _alpha_set(skills=[
        {"piece_count": 2, "skill": "dragon_guard", "level": 1},
        {"piece_count": 3, "skill": "dragon_guard", "level": 2},
        {"piece_count": 5, "skill": "dragon_guard", "level": 3},
    ])
    res = validate_sets(_modules([no_effect]))
    assert res["ok"] is True
    assert "set_skill_effect_ref_missing" in _rules(res, "warnings")
    # 全接线 → 无 W2（test_validate_ok_clean 已断言零黄）


def test_validate_w3_sets_empty() -> None:
    """黄 W3：无套装数——sets 空段且 sets_enabled=true → 配置意图存疑黄；关掉则不提示。"""
    res = validate_sets(_modules([]))
    assert res["ok"] is True
    assert "sets_empty" in _rules(res, "warnings")
    res_off = validate_sets(_modules([], settings={"sets_enabled": False}))
    assert "sets_empty" not in _rules(res_off, "warnings")


def test_validate_w4_single_variant_family() -> None:
    """黄 W4：同族单记录——仅 alpha 缺 β 对照 → 黄；α/β 齐 → 无 W4。"""
    res = validate_sets(_modules([_alpha_set()]))
    assert res["ok"] is True
    assert "set_family_single_variant" in _rules(res, "warnings")
    w4 = [w for w in cast(List[Dict[str, object]], res["warnings"])
          if w.get("rule") == "set_family_single_variant"]
    assert w4 and w4[0]["level"] == "W4"
    res_full = validate_sets(_modules([_alpha_set(), _beta_set()]))
    assert "set_family_single_variant" not in _rules(res_full, "warnings")


def test_validate_forward_to_report() -> None:
    """正例：传入 report 收集器（dict 形态）→ 结果同步追加（对齐批0 收集器形态）。"""
    report: Dict[str, List[object]] = {"errors": [], "warnings": [], "notes": []}
    validate_sets(_modules([_alpha_set()]), report=report)
    assert any(isinstance(e, Mapping) and e.get("args", (None, None, None))[1]
               .startswith("forge.sets") for e in report["warnings"])


# ---------------------------------------------------------------------------
# C set_lookup：玩家当前装配可激活套装查询
# ---------------------------------------------------------------------------
def test_lookup_ready_two_pieces() -> None:
    """正例：穿 2 件（头+身）→ pieces_have=2，ready=True（ACT-02 最低 2 件激活档）。"""
    sets = parse_sets(_modules([_alpha_set(), _beta_set()]))
    got = set_lookup({"equipped": ["n_head_a", "n_body_a"]}, sets)
    alpha = [g for g in got if g["variant"] == "alpha"][0]
    assert alpha["set_id"] == "set_dk"
    assert alpha["family_id"] == "set_dk"
    assert alpha["pieces_have"] == 2
    assert alpha["pieces_total"] == FULL_SET_PIECES
    assert alpha["ready"] is True
    assert MIN_ACTIVATE_PIECES == 2


def test_lookup_not_ready_one_piece() -> None:
    """负例：穿 1 件 → pieces_have=1，ready=False（不足 2 件不激活）。"""
    sets = parse_sets(_modules([_alpha_set()]))
    got = set_lookup({"equipped": ["n_head_a"]}, sets)
    assert got[0]["pieces_have"] == 1
    assert got[0]["ready"] is False


def test_lookup_mixed_alpha_beta_variant3() -> None:
    """正例 VAR-03：α 头 + β 身 混穿 → 族级合并件数 2，ready=True（混穿不拆族）。"""
    beta = _beta_set(pieces=["n_head_a", "n_body_a"])
    sets = parse_sets(_modules([_alpha_set(), beta]))
    got = set_lookup({"equipped": ["n_head_a", "n_body_a"]}, sets)
    by_variant = {g["variant"]: g for g in got}
    # α 记录 pieces_have=2（α 的 5 件里穿 2）；β 记录 pieces_have=2（β 的 2 件全穿）
    assert by_variant["alpha"]["pieces_have"] == 2
    assert by_variant["beta"]["pieces_have"] == 2
    # 族级合并（VAR-03：α 头+β 身 同族计数）→ 两条记录族级都 ready
    assert by_variant["alpha"]["family_pieces_have"] == 2
    assert by_variant["beta"]["ready"] is True


def test_lookup_uses_set_tracker() -> None:
    """正例：player 带 set_tracker（4b EQP-03，族 id→件数）→ 直接取件数。"""
    sets = parse_sets(_modules([_alpha_set()]))
    got = set_lookup({"set_tracker": {"set_dk": 5}, "equipped": []}, sets)
    assert got[0]["pieces_have"] == 5
    assert got[0]["ready"] is True


def test_lookup_empty_player() -> None:
    """负例：无装配/非 Mapping player → 全 pieces_have=0，ready=False（确定性兜底）。"""
    sets = parse_sets(_modules([_alpha_set()]))
    for player in ({}, {"equipped": None}, "not-a-map", None, {"equipped": [42]}):
        got = set_lookup(player, sets)
        assert got[0]["pieces_have"] == 0
        assert got[0]["ready"] is False


def test_lookup_raw_dict_sets() -> None:
    """正例：sets 传 raw dict 列表（非 ForgeSet）也可查询（F-6 双形态归一）。"""
    got = set_lookup({"equipped": ["n_head_a", "n_body_a"]}, [_alpha_set()])
    assert got[0]["ready"] is True


# ---------------------------------------------------------------------------
# D set_effects_contract：套装技能契约
# ---------------------------------------------------------------------------
def test_contract_expand() -> None:
    """正例：SetSkill 契约展开——skill_id/触发段/等级/件数逐条可读。"""
    parsed = parse_sets(_modules([_alpha_set()]))
    c = set_effects_contract(parsed[0])
    assert c["ok"] is True
    assert c["set_id"] == "set_dk"
    assert c["family_id"] == "set_dk"
    assert c["variant"] == "alpha"
    assert c["codex_group"] == "set_dk"
    assert c["enabled"] is True
    assert c["pieces_total"] == 5
    skills = cast(List[Dict[str, object]], c["skills"])
    assert len(skills) == 3
    first = skills[0]
    assert first["skill_id"] == "dragon_guard"
    assert first["piece_count"] == 2
    assert first["level"] == 1
    assert first["effect_ref"] == "ref_guard"
    assert first["trigger"] == "穿 2 件激活 dragon_guard Lv1"
    assert first["desc"] == "效果接线：ref_guard"


def test_contract_placeholder_desc() -> None:
    """正例：effect_ref 空 → 占位技能描述（SK-04 只显示不结算）。"""
    no_effect = _alpha_set(skills=[
        {"piece_count": 2, "skill": "dragon_guard", "level": 1},
    ])
    c = set_effects_contract(no_effect)
    skills = cast(List[Dict[str, object]], c["skills"])
    assert skills[0]["desc"] == "占位技能（仅登记，只显示不结算）"


def test_contract_raw_dict_input() -> None:
    """正例：raw dict 输入（非 ForgeSet）→ 契约展开（F-6 双形态）。"""
    c = set_effects_contract(_alpha_set())
    assert c["ok"] is True
    assert c["name"] == "龙骑士套装"


def test_contract_invalid_set() -> None:
    """负例：非法 set 输入 → ok=False 兜底（不抛异常）。"""
    for bad in (None, 42, "set", {"no_id": 1}):
        c = set_effects_contract(bad)
        assert c["ok"] is False
        assert c["skills"] == []
