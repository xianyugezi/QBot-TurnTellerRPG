"""M9 锻造·套装档位激活结算测试（tests/unit/test_forge_set_skills.py）。

文件名：test_forge_set_skills.py
创建时间：2026-09-14
作者：dsh（用户拍板 2026-09-14「套装档位这个功能要做」：补 ACT-01~06 执行 + /套装
  单套明细渲染；只做激活结算 + 指令渲染，编辑器套装页见 2c2d §1.6 另批）

依据：docs/细化/细化_2c2d_锻造套装与客制.md §1.2（SET/SK）/ §1.3（ACT-01~06）/
  §1.4（VAR-01~03）/ §1.5（/套装 渲染样例）。
覆盖矩阵：
  A resolve_set_skills：0/1/2/3/4/5/6 件边界（4 件=3 件档）/ 多技能并行 / 同技能多档
    取高不叠加 / α/β 混穿归族 / 自定义 set_piece_counts / tracker 优先 / 装配集回退 /
    非 Mapping 兜底 / 配置档位集合归一
  B recompute/sync：写回 set_tracker+set_skills / 无装配源不空写 / 战斗内冻结
  C skill_slots_battle：套装技能并入可用技能集（含 level / 去重 / 技能表 type 尊重）
  D /套装 明细渲染：行结构（档位/穿戴/缺件/αβ 对照）/ 精确-前缀-歧义-未命中 / 缺 β
    不渲染对照 / 无参全量兼容

铁律：零 NoneBot import；纯函数确定性；不写定时器/睡眠调用；不引入随机；不改真实内容包。
"""
from __future__ import annotations

from typing import Dict, List, Mapping, Optional

from qbot_rpg.commands.forge_commands import cmd_sets
from qbot_rpg.core.forge_set_skills import (
    SET_SKILLS_KEY,
    SET_TRACKER_KEY,
    equipped_piece_ids,
    family_piece_counts,
    group_families,
    is_set_frozen,
    recompute_set_tracker,
    resolve_piece_counts,
    resolve_set_skills,
    set_tracker_of,
    sync_set_skills,
)
from qbot_rpg.core.forge_sets import parse_sets

# ---------------------------------------------------------------------------
# 夹具辅助（α 节点 1 孔 / β 节点 3 孔；节点名带部位，供渲染断言）
# ---------------------------------------------------------------------------
_ALPHA_PARTS = [
    ("armor_head", "n_head_a", "龙骑盔", None),
    ("armor_body", "n_body_a", "龙骑铠", "n_head_a"),
    ("armor_hand", "n_hand_a", "龙骑腕", "n_body_a"),
    ("armor_leg", "n_leg_a", "龙骑腿", "n_hand_a"),
    ("armor_foot", "n_foot_a", "龙骑靴", "n_leg_a"),
]
_BETA_PARTS = [
    ("armor_head", "n_head_b", "龙骑盔β", None),
    ("armor_body", "n_body_b", "龙骑铠β", "n_head_b"),
    ("armor_hand", "n_hand_b", "龙骑腕β", "n_body_b"),
    ("armor_leg", "n_leg_b", "龙骑腿β", "n_hand_b"),
    ("armor_foot", "n_foot_b", "龙骑靴β", "n_leg_b"),
]


def _node(t: str, nid: str, name: str, parent: Optional[str], slots: int) -> Dict[str, object]:
    node: Dict[str, object] = {
        "id": nid, "name": name, "type": t, "level": 1, "parent": parent,
        "materials": [{"item": "m_ore", "count": 5}], "item": "it_%s" % nid,
        "final": True,
    }
    if slots:
        node["slots"] = [{"level": 1} for _ in range(slots)]
    return node


def _trees() -> List[Dict[str, object]]:
    out: List[Dict[str, object]] = []
    for parts, slots in ((_ALPHA_PARTS, 1), (_BETA_PARTS, 3)):
        for t, nid, name, parent in parts:
            node = _node(t, nid, name, parent, slots)
            out.append({"id": "tree_%s_%d" % (t, slots), "name": t, "type": t,
                        "roots": [nid], "nodes": [node]})
    return out


def _tiers() -> List[Dict[str, object]]:
    return [
        {"piece_count": 2, "skill": "dragon_guard", "level": 1, "effect_ref": "r"},
        {"piece_count": 3, "skill": "dragon_guard", "level": 2, "effect_ref": "r"},
        {"piece_count": 5, "skill": "dragon_guard", "level": 3, "effect_ref": "r"},
    ]


def _alpha(**over: object) -> Dict[str, object]:
    base: Dict[str, object] = {
        "id": "set_dk", "name": "龙骑士套装", "variant": "alpha",
        "pieces": [p[1] for p in _ALPHA_PARTS], "skills": _tiers(),
    }
    base.update(over)
    return base


def _beta(**over: object) -> Dict[str, object]:
    base: Dict[str, object] = {
        "id": "set_dk", "name": "龙骑士套装β", "variant": "beta",
        "pieces": [p[1] for p in _BETA_PARTS], "skills": _tiers(),
    }
    base.update(over)
    return base


def _sets(records: Optional[List[Dict[str, object]]] = None) -> list:
    raw = records if records is not None else [_alpha(), _beta()]
    return parse_sets({"forge": {"trees": _trees(), "sets": raw}})


def _items() -> Dict[str, object]:
    return {"m_ore": {"id": "m_ore", "name": "秘银"}}


def _skills() -> Dict[str, object]:
    return {"dragon_guard": {"id": "dragon_guard", "name": "龙之加护", "type": "passive"}}


class _Parsed:
    def __init__(self, *args: str) -> None:
        self.args = list(args)


def _ctx(player: Optional[Mapping[str, object]] = None, records: Optional[list] = None,
         settings: Optional[Mapping[str, object]] = None) -> Dict[str, object]:
    forge: Dict[str, object] = {"schema_version": "1.0", "trees": _trees(),
                                "sets": records if records is not None else [_alpha(), _beta()]}
    ctx: Dict[str, object] = {
        "forge": forge, "items": _items(), "skills": _skills(),
        "settings": settings if settings is not None else {},
        "player": dict(player) if player is not None else {},
    }
    return ctx


# ---------------------------------------------------------------------------
# A resolve_set_skills / 件数口径
# ---------------------------------------------------------------------------
def test_piece_count_boundaries_0_to_6() -> None:
    """边界：0/1 件不激活；2→Lv1、3→Lv2、4→Lv2（无 4 档）、5→Lv3、6→Lv3（不叠）。"""
    sets = _sets()
    pieces = [p[1] for p in _ALPHA_PARTS]
    expected = {0: {}, 1: {}, 2: {"dragon_guard": 1}, 3: {"dragon_guard": 2},
                4: {"dragon_guard": 2}, 5: {"dragon_guard": 3}, 6: {"dragon_guard": 3}}
    for n in range(7):
        got = resolve_set_skills({"equipped": pieces[:n]}, sets)
        assert got == expected[n], (n, got)


def test_multi_skill_parallel() -> None:
    """ACT-04：同套装多技能各自判定并行生效（3 件 → a Lv2 / b Lv1）。"""
    skills = [
        {"piece_count": 2, "skill": "a", "level": 1},
        {"piece_count": 3, "skill": "a", "level": 2},
        {"piece_count": 2, "skill": "b", "level": 1},
        {"piece_count": 5, "skill": "b", "level": 2},
    ]
    sets = _sets([_alpha(skills=skills)])
    got = resolve_set_skills({"equipped": [p[1] for p in _ALPHA_PARTS][:3]}, sets)
    assert got == {"a": 2, "b": 1}


def test_same_skill_highest_tier_only() -> None:
    """ACT-04：同一 skill 多档命中只取最高档（5 件 → Lv3，不出现多值/叠加）。"""
    sets = _sets()
    got = resolve_set_skills({"equipped": [p[1] for p in _ALPHA_PARTS]}, sets)
    assert got == {"dragon_guard": 3}
    assert isinstance(got["dragon_guard"], int)


def test_alpha_beta_mixed_family_count() -> None:
    """VAR-03：α 头 + β 身 + β 手 → 归族 3 件 → Lv2（混穿不拆族）。"""
    sets = _sets()
    got = resolve_set_skills({"equipped": ["n_head_a", "n_body_b", "n_hand_b"]}, sets)
    assert got == {"dragon_guard": 2}


def test_custom_piece_counts_enable_four_tier() -> None:
    """配置化：档位集合含 4 时 4 件档生效；缺省 {2,3,5} 时 4 件档忽略（仍 3 件档）。"""
    skills = [
        {"piece_count": 2, "skill": "a", "level": 1},
        {"piece_count": 3, "skill": "a", "level": 2},
        {"piece_count": 4, "skill": "a", "level": 3},
    ]
    sets = _sets([_alpha(skills=skills)])
    player = {"equipped": [p[1] for p in _ALPHA_PARTS][:4]}
    assert resolve_set_skills(player, sets) == {"a": 2}  # 缺省档位集合：4 档非法忽略
    assert resolve_set_skills(player, sets, piece_counts=[2, 3, 4]) == {"a": 3}
    # modules Mapping（settings.forge.set_piece_counts）同口径
    assert resolve_set_skills(player, sets, piece_counts={
        "settings": {"forge": {"set_piece_counts": [2, 3, 4]}}}) == {"a": 3}


def test_resolve_piece_counts_normalization() -> None:
    """档位集合归一：None→{2,3,5}；配置 Mapping 委托；序列清洗；非法→缺省。"""
    assert resolve_piece_counts() == (2, 3, 5)
    assert resolve_piece_counts([3, 2, 3, 5, 0, -1, True]) == (2, 3, 5)
    assert resolve_piece_counts({"settings": {"forge": {"set_piece_counts": [2, 4]}}}) == (2, 4)
    assert resolve_piece_counts("junk") == (2, 3, 5)  # type: ignore[arg-type]


def test_set_tracker_source_first() -> None:
    """ACT-01：set_tracker 优先于装配节点集（tracker=5 → Lv3）。"""
    sets = _sets()
    got = resolve_set_skills({"set_tracker": {"set_dk": 5}, "equipped": []}, sets)
    assert got == {"dragon_guard": 3}
    assert family_piece_counts({"set_tracker": {"set_dk": 5}}, sets) == {"set_dk": 5}


def test_equipped_fallback_without_tracker() -> None:
    """无 set_tracker → 回退装配节点集 ∩ 族 pieces（α/β 并集合并）。"""
    sets = _sets()
    assert family_piece_counts({"equipped": ["n_head_a", "n_body_a"]}, sets) == {"set_dk": 2}
    assert resolve_set_skills({"equipped": ["n_head_a", "n_body_a"]}, sets) == {"dragon_guard": 1}


def test_non_mapping_player_fallback() -> None:
    """非 Mapping player → 空件数 / 空技能（确定性兜底，不抛异常）。"""
    sets = _sets()
    for player in (None, 42, "x", ["n_head_a"]):
        assert family_piece_counts(player, sets) == {"set_dk": 0}
        assert resolve_set_skills(player, sets) == {}
    assert equipped_piece_ids("junk") == set()
    assert set_tracker_of(None) == {}


def test_empty_sets_no_activation() -> None:
    """无 sets / raw dict 双形态：空集 → {}；raw dict 记录也可判定。"""
    assert resolve_set_skills({"set_tracker": {"set_dk": 5}}, []) == {}
    got = resolve_set_skills({"set_tracker": {"set_dk": 3}}, [_alpha()])
    assert got == {"dragon_guard": 2}
    assert list(group_families([_alpha(), _beta()])) == ["set_dk"]


# ---------------------------------------------------------------------------
# B recompute / sync / 战斗冻结（ACT-05）
# ---------------------------------------------------------------------------
def test_recompute_writes_tracker() -> None:
    """ACT-05：装配节点集非空 → 重算写回 set_tracker（族级并集计数）。"""
    sets = _sets()
    player: Dict[str, object] = {"equipped": ["n_head_a", "n_body_a"]}
    out = recompute_set_tracker(player, sets)
    assert out == {"set_dk": 2}
    assert player[SET_TRACKER_KEY] == {"set_dk": 2}


def test_recompute_preserves_when_no_equipped_source() -> None:
    """P-6：无装配节点信息源（tracker-only）→ 保留既有 set_tracker，不空写。"""
    sets = _sets()
    player: Dict[str, object] = {"set_tracker": {"set_dk": 3}}
    assert recompute_set_tracker(player, sets) == {"set_dk": 3}
    assert player[SET_TRACKER_KEY] == {"set_dk": 3}


def test_sync_writes_skills_key() -> None:
    """sync_set_skills：写 set_tracker + set_skills（生效接入键），返回技能等级表。"""
    sets = _sets()
    player: Dict[str, object] = {"equipped": ["n_head_a", "n_body_a", "n_hand_a"]}
    got = sync_set_skills(player, sets)
    assert got == {"dragon_guard": 2}
    assert player[SET_SKILLS_KEY] == {"dragon_guard": 2}
    assert player[SET_TRACKER_KEY] == {"set_dk": 3}


def test_battle_freeze_keeps_tracker_and_levels() -> None:
    """ACT-05 冻结点：in_battle=True → 不重算（即使装配集变化），等级沿用冻结前。"""
    sets = _sets()
    player: Dict[str, object] = {
        "set_tracker": {"set_dk": 3}, "equipped": ["n_head_a"], "in_battle": True,
    }
    assert is_set_frozen(player) is True
    assert recompute_set_tracker(player, sets) == {"set_dk": 3}
    assert player[SET_TRACKER_KEY] == {"set_dk": 3}  # 未被 1 件装配覆盖
    assert sync_set_skills(player, sets) == {"dragon_guard": 2}


def test_act05_equipment_helper_writes_state() -> None:
    """ACT-05 接线：穿戴槽位 item_id → 节点 id → 重算写 tracker + set_skills + ctx。"""
    from qbot_rpg.commands.basic_commands import (
        _equipped_node_ids_from_equipment,
        _sync_set_activation,
    )

    ctx = _ctx(records=[_alpha(), _beta()])
    player: Dict[str, object] = {
        "equipment": {"armor_head": {"item_id": "it_n_head_a"},
                      "armor_body": {"item_id": "it_n_body_a"}},
        "inventory": [], "attributes": {},
    }
    assert _equipped_node_ids_from_equipment(ctx, player) == ["n_head_a", "n_body_a"]
    _sync_set_activation(ctx, player)
    assert player[SET_TRACKER_KEY] == {"set_dk": 2}
    assert player[SET_SKILLS_KEY] == {"dragon_guard": 1}
    assert ctx[SET_SKILLS_KEY] == {"dragon_guard": 1}
    assert ctx[SET_TRACKER_KEY] == {"set_dk": 2}


def test_act05_equipment_helper_battle_frozen() -> None:
    """ACT-05 接线 + 冻结：战斗内即使重算入口被调，也保持冻结前 tracker/等级。"""
    from qbot_rpg.commands.basic_commands import _sync_set_activation

    ctx = _ctx(records=[_alpha(), _beta()])
    player: Dict[str, object] = {
        "set_tracker": {"set_dk": 3}, "in_battle": True,
        "equipment": {"armor_head": {"item_id": "it_n_head_a"}},
        "inventory": [], "attributes": {},
    }
    _sync_set_activation(ctx, player)
    assert player[SET_TRACKER_KEY] == {"set_dk": 3}
    assert player[SET_SKILLS_KEY] == {"dragon_guard": 2}


# ---------------------------------------------------------------------------
# C skill_slots_battle：套装技能进可用技能集（等级正确）
# ---------------------------------------------------------------------------
def test_set_skills_enter_available_skill_set() -> None:
    """生效接入：ctx["set_skills"] 经 skill_slots_battle 并入可用技能集（含 level）。"""
    from qbot_rpg.core.skill_slots_battle import (
        available_skills,
        battle_equipped_skills,
        equipped_slot_kind,
        set_skill_levels,
        set_skill_rows,
    )

    ctx: Dict[str, object] = {
        "skill_slots_state": {"slots": [{"slot": "basic", "skill_id": "basic_attack"}]},
        "set_skills": {"dragon_guard": 2},
        "skills": {"basic_attack": {"name": "普攻"}, "dragon_guard": {"name": "龙之加护"}},
    }
    rows = set_skill_rows({"dragon_guard": 2})
    assert rows == [{"slot": "passive", "skill_id": "dragon_guard", "level": 2}]
    assert set_skill_levels(ctx) == {"dragon_guard": 2}
    assert "dragon_guard" in available_skills(ctx)
    assert equipped_slot_kind(ctx, "dragon_guard") == "passive"
    assert set(battle_equipped_skills(ctx).keys()) == {"basic_attack", "dragon_guard"}


def test_set_skills_available_and_type_respected() -> None:
    """技能表 type=active → 套装技能作行动位可施放；无 type → passive 缺省。"""
    from qbot_rpg.core.skill_slots_battle import available_skills, is_slot_equipped

    active_ctx: Dict[str, object] = {
        "skill_slots_state": {"slots": []}, "set_skills": {"dragon_guard": 3},
        "skills": {"dragon_guard": {"name": "龙之加护", "type": "active"}},
    }
    assert "dragon_guard" in available_skills(active_ctx)
    assert is_slot_equipped(active_ctx, "dragon_guard") is True
    passive_ctx: Dict[str, object] = {
        "skill_slots_state": {"slots": []}, "set_skills": {"dragon_guard": 3}, "skills": {},
    }
    assert is_slot_equipped(passive_ctx, "dragon_guard") is False  # passive 不占行动位


def test_set_skills_dedupe_assembly_row_priority() -> None:
    """同 skill 已在装配快照内 → 不重复追加（装配行优先）。"""
    from qbot_rpg.core.skill_slots_battle import with_set_skills

    merged = with_set_skills(
        {"slots": [{"slot": "active", "skill_id": "dragon_guard"}]},
        {"dragon_guard": 3},
    )
    assert merged["slots"] == [{"slot": "active", "skill_id": "dragon_guard"}]


# ---------------------------------------------------------------------------
# D /套装 明细渲染（§1.5）
# ---------------------------------------------------------------------------
def test_cmd_sets_detail_full_render() -> None:
    """明细渲染：名称（α）/ 部位 / 档位 / 穿戴 2/5 + 生效 / 缺件 / αβ 孔位对照。"""
    ctx = _ctx(player={"set_tracker": {"set_dk": 2}})
    out = cmd_sets(_Parsed("龙骑士套装"), ctx)
    lines = out.split("\n")
    assert lines[0] == "龙骑士套装（α）｜技能 多 · 孔 少"
    assert lines[1] == "部位：头·龙骑盔 / 身·龙骑铠 / 手·龙骑腕 / 腿·龙骑腿 / 脚·龙骑靴"
    assert "套装技能：龙之加护 Lv1（2件） / Lv2（3件） / Lv3（5件）" in lines
    assert "穿戴：2/5 头 ✅ · 身 ✅ → 龙之加护 Lv1 生效中" in lines
    assert "缺件：" in lines[4] and "手（可锻造：龙骑腕 ← 龙骑铠 + 秘银×5）" in lines[4]
    assert lines[5].startswith("α/β 对照：") and "β 版孔位" in lines[5]


def test_cmd_sets_detail_no_beta_record_skips_compare() -> None:
    """缺 β 记录 → 不渲染 α/β 对照行（§1.5）。"""
    ctx = _ctx(player={"equipped": ["n_head_a", "n_body_a"]}, records=[_alpha()])
    out = cmd_sets(_Parsed("龙骑士套装"), ctx)
    assert "α/β 对照" not in out
    assert "穿戴：2/5" in out


def test_cmd_sets_prefix_and_ambiguous_and_not_found() -> None:
    """匹配：唯一前缀命中明细；多族前缀 → 歧义列表；未命中 → 既有 forge_not_found。"""
    ctx = _ctx(records=[
        _alpha(),
        _beta(),
        {"id": "set_other", "name": "龙鳞套装", "variant": "alpha",
         "pieces": ["n_head_a"], "skills": [{"piece_count": 2, "skill": "x", "level": 1}]},
    ])
    out_prefix = cmd_sets(_Parsed("龙鳞"), ctx)
    assert out_prefix.startswith("龙鳞套装（α）")
    out_amb = cmd_sets(_Parsed("龙"), ctx)
    assert "匹配到多个套装" in out_amb
    out_miss = cmd_sets(_Parsed("不存在"), ctx)
    assert out_miss.startswith("❌ 未找到「不存在」")


def test_cmd_sets_no_arg_full_list_compat() -> None:
    """无参仍返回全量列表（兼容既有 =set_lookup 逐套行）。"""
    ctx = _ctx(player={"equipped": ["n_head_a", "n_body_a"]})
    out = cmd_sets(_Parsed(), ctx)
    assert out.startswith("1. ")
    assert "龙骑士套装（2/5 件）" in out
    assert "✅" in out  # 族级 ≥2 ready


def test_cmd_sets_ctx_level_tracker_overlay() -> None:
    """装配层把 set_tracker 挂 ctx 顶层（_ps_init）→ cmd 仍读到（_set_player_view 叠加）。"""
    ctx = _ctx(player={})
    ctx["set_tracker"] = {"set_dk": 2}
    out = cmd_sets(_Parsed("龙骑士套装"), ctx)
    assert "穿戴：2/5" in out and "Lv1 生效中" in out
