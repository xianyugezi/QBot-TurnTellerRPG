"""M9 锻造·批7·路7B：客制结构/校验/次数表/资格判定单元测试（tests/unit/test_forge_augments.py）。

文件名：test_forge_augments.py
创建时间：2026-08-30
作者：Hermes 子agent-7B（M9 锻造实现组批7·路7B：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_augments.py；不改动批0 forge_models.py / 批3 forge_sp.py）

依据：docs/细化/细化_2c2d_锻造套装与客制.md §二（AUG-01~12/LIM-01~03/GU-A1~A4/
  §五 V4~V8/W2/W3/§3.1 宗师 41-50）+ docs/m9_shared_contract.md §五/§六。
测试目标：qbot_rpg.core.forge_augments.{parse_augments, validate_augments,
  limit_by_rarity, augment_eligible, AUGMENT_MASTER_LEVEL_MIN}。

覆盖矩阵：
  A parse 结构：合法 4 项（numeric×3 + slot×1）kind/访问器齐备；缺 augments 段 → 空；
    list 形态 → 解析；非 Mapping 行跳过；augments 为非法形态 → 空
  B validate 正例：合法包 → ok=True、errors/warnings 空、present=True
  C validate V4 负例：kind 非法（stat/element）/ numeric 缺 stat_key / slot 缺 slot_level
  D validate V5 负例：cost item items 缺失 / 龙脉石类非 rare
  E validate V6 负例：quality=整数 / final_only 非 legendary / times<1 / 同 quality>2 行
  F validate V7+V16 黄：final_tier 非终盘黄 / augmentable 非最终武器黄
  G validate V8 黄：全段 disabled 且 augments_enabled=true → 配置意图存疑黄
  H validate W2 黄：trace 追溯行 → 已砍不生效黄；W3 黄：settings 关但数据存在
  I limit_by_rarity 次数表：table {epic:3, legendary:2} / final_only {legendary:1} /
    rows 视图齐备；缺段 → 空；非法行跳过
  J augment_eligible 资格：全过 ok / SP 未解锁 / 宗师不足（40）/ 非最终武器 /
    品质不合格（normal）/ player None / weapon None

铁律：零 NoneBot import；纯函数确定性；零定时器探针合规；不引入随机。
"""
from __future__ import annotations

from typing import Any, Dict, List

from qbot_rpg.core.forge_augments import (
    AUGMENT_MASTER_LEVEL_MIN,
    AUGMENT_RARITY_QUALITIES,
    AUGMENT_SP_PANEL_ID,
    augment_eligible,
    limit_by_rarity,
    parse_augments,
    validate_augments,
)
from qbot_rpg.core.forge_tree import FORGE_JOB_ID


# ---------------------------------------------------------------------------
# 夹具：合法基准包（武器树 1 根 final 武器 + items 引用靶 + 合法客制段）
# ---------------------------------------------------------------------------
def _legal_augments() -> Dict[str, Any]:
    """合法客制段（4 项 + 次数表；2c2d V4/V5/V6 正例；cost 龙脉石类 rare）。"""
    return {
        "augments": [
            {"id": "aug_atk", "name": "攻击", "kind": "numeric", "effect": "atk+5",
             "stat_key": "atk", "value": {"flat": 5},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_crit", "name": "会心", "kind": "numeric", "effect": "crit+10%",
             "stat_key": "crit", "value": {"pct": 0.10},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_def", "name": "防御", "kind": "numeric", "effect": "def+10",
             "stat_key": "def", "value": {"flat": 10},
             "cost": [{"item": "dragonite", "count": 1}], "repeatable": True,
             "max_repeat": 3},
            {"id": "aug_slot", "name": "孔位", "kind": "slot", "effect": "开1孔",
             "slot_level": 1, "cost": [{"item": "dragonite", "count": 2}],
             "repeatable": False, "max_repeat": 1},
        ],
        "limit_by_rarity": [
            {"quality": "epic", "times": 3, "final_only": False},
            {"quality": "legendary", "times": 2, "final_only": False},
            {"quality": "legendary", "times": 1, "final_only": True},
        ],
    }


def _legal_items() -> list:
    """items 引用靶（装备 + 材料两档，客制消耗龙脉石类 rare）。"""
    return [
        {"id": "flame_king_sword", "name": "炎王剑", "type": "weapon",
         "quality": "legendary"},
        {"id": "iron_sword", "name": "铁剑", "type": "weapon", "quality": "normal"},
        {"id": "iron_ore", "name": "铁矿石", "type": "material",
         "material_tier": "normal", "source": "采集点"},
        {"id": "fire_dragon_scale", "name": "火龙鳞", "type": "material",
         "material_tier": "rare", "source": "火龙掉落"},
        {"id": "dragonite", "name": "龙脉石", "type": "material",
         "material_tier": "rare", "source": "BOSS 掉落"},
    ]


def _modules(
    augments: Any = None,
    nodes: Any = None,
    augments_enabled: bool = True,
    include_augments: bool = True,
) -> Dict[str, Any]:
    """标准模块上下文（零红零黄基准：final 武器单节点 + 合法客制段）。

    augments：覆盖客制段（None → 合法包）；nodes：覆盖武器树节点；augments_enabled：
    settings 客制开关；include_augments=False → 整体去掉 augments 键（缺段合法）。
    """
    base_nodes = [
        {"id": "node_flame_king_sword", "name": "炎王剑", "item": "flame_king_sword",
         "type": "weapon", "level": 7, "parent": None,
         "materials": [{"item": "fire_dragon_scale", "count": 3}],
         "rarity": "legendary", "final": True, "augmentable": True},
    ]
    forge: Dict[str, Any] = {
        "schema_version": "1.0",
        "trees": [{
            "id": "tree_weapon", "name": "武器树", "type": "weapon",
            "roots": ["node_flame_king_sword"],
            "nodes": list(nodes) if nodes is not None else base_nodes,
        }],
        "settings": {
            "forge_fee": "节点等级×10", "synth_ratio_3to1": True,
            "straight_forge": True, "decompose_rate": {"正式": 0.4},
            "exp_per_forge": "节点等级×2", "sets_enabled": True,
            "augments_enabled": augments_enabled,
        },
    }
    if include_augments:
        forge["augments"] = augments if augments is not None else _legal_augments()
    return {"forge": forge, "items": _legal_items()}


def _rules(result: Dict[str, Any], bucket: str = "errors") -> List[str]:
    """收集指定桶内的 rule 键列表（去重保序）。"""
    return [e["rule"] for e in result.get(bucket, [])]


def _kinds(result: Dict[str, Any], bucket: str = "errors") -> List[str]:
    """收集指定桶内的 kind（2c2d-Vx/Wx）键列表。"""
    return [e["kind"] for e in result.get(bucket, [])]


# ---------------------------------------------------------------------------
# 玩家 / 武器夹具（augment_eligible）
# ---------------------------------------------------------------------------
def _player(level: int = AUGMENT_MASTER_LEVEL_MIN,
            sp_unlocked: bool = True,
            unlocks: Dict[str, int] | None = None) -> Dict[str, Any]:
    """铸造职业玩家表示（等级 + SP 解锁可配；默认宗师 41 + 客制 SP 已解锁）。"""
    unlock_map = dict(unlocks) if unlocks is not None else {}
    if sp_unlocked and AUGMENT_SP_PANEL_ID not in unlock_map:
        unlock_map[AUGMENT_SP_PANEL_ID] = 1
    return {
        "proficiency": {
            FORGE_JOB_ID: {
                "level": level, "exp": 0, "sp_earned": 0, "sp_used": 0,
                "unlocks": unlock_map,
            }
        }
    }


def _final_weapon(**overrides: Any) -> Dict[str, Any]:
    """最终强化武器实例（GU-A3 通过形态；可覆写字段）。"""
    base: Dict[str, Any] = {
        "id": "flame_king_sword", "type": "weapon", "final": True,
        "augmentable": True, "rarity": "legendary",
    }
    base.update(overrides)
    return base


# ===========================================================================
# A parse 结构
# ===========================================================================
def test_parse_legal_four_rows():
    rows = parse_augments(_modules())
    assert isinstance(rows, tuple)
    assert len(rows) == 4
    kinds = [r.aug_kind for r in rows]
    assert kinds == ["numeric", "numeric", "numeric", "slot"]
    # kind 白名单两型（AUG-03 权威 numeric/slot）
    assert all(k in ("numeric", "slot") for k in kinds)
    # 访问器：stat_key / value / cost / repeatable / max_repeat / slot_level
    by_id = {r.raw.get("id"): r for r in rows}
    assert by_id["aug_atk"].stat_key == "atk"
    assert by_id["aug_atk"].value == {"flat": 5}
    assert by_id["aug_atk"].cost[0]["item"] == "dragonite"
    assert by_id["aug_atk"].repeatable is True
    assert by_id["aug_atk"].max_repeat == 3
    assert by_id["aug_slot"].slot_level == 1
    assert by_id["aug_slot"].repeatable is False
    assert by_id["aug_crit"].stat_key == "crit"


def test_parse_missing_augments_returns_empty():
    # 无 augments 段是合法配置 → 空元组
    assert parse_augments(_modules(include_augments=False)) == ()
    # forge 段缺失 / 非 Mapping
    assert parse_augments({}) == ()
    assert parse_augments({"forge": "nope"}) == ()


def test_parse_list_form_augments():
    # augments 段为 list 形态（共享契约 §五 兼容：list → augments 数组）
    rows = parse_augments(_modules([{"id": "aug_x", "kind": "numeric",
                                     "stat_key": "atk", "cost": [{"item": "dragonite",
                                                                  "count": 1}]}]))
    assert len(rows) == 1
    assert rows[0].raw["id"] == "aug_x"


def test_parse_skips_non_mapping_rows():
    rows = parse_augments(_modules([
        {"id": "aug_ok", "kind": "numeric", "stat_key": "atk",
         "cost": [{"item": "dragonite", "count": 1}]},
        "not-a-row",
        42,
    ]))
    assert len(rows) == 1
    assert rows[0].raw["id"] == "aug_ok"


def test_parse_illegal_augments_shape_returns_empty():
    assert parse_augments(_modules("not-a-mapping-or-list")) == ()
    assert parse_augments(_modules({"limit_by_rarity": []})) == ()  # 无 augments 键


# ===========================================================================
# B validate 正例
# ===========================================================================
def test_validate_legal_ok():
    result = validate_augments(_modules())
    assert result["ok"] is True
    assert result["present"] is True
    assert result["errors"] == []
    assert result["warnings"] == []
    assert result["rule_counts"] == {}


def test_validate_missing_augments_present_false():
    result = validate_augments(_modules(include_augments=False))
    assert result["ok"] is True
    assert result["present"] is False


def test_validate_forge_missing_ok():
    result = validate_augments({})
    assert result["ok"] is True
    assert result["present"] is False


# ===========================================================================
# C validate V4 负例
# ===========================================================================
def test_validate_v4_kind_invalid():
    aug = _legal_augments()
    aug["augments"][0]["kind"] = "stat"   # 任务派工单「三型」字面不合法；权威两型
    result = validate_augments(_modules(aug))
    assert result["ok"] is False
    assert "augment_kind_invalid" in _rules(result)
    assert "2c2d-V4" in _kinds(result)


def test_validate_v4_numeric_requires_stat_key():
    aug = _legal_augments()
    aug["augments"][0].pop("stat_key")
    result = validate_augments(_modules(aug))
    assert "augment_numeric_stat_key_required" in _rules(result)


def test_validate_v4_slot_requires_slot_level():
    aug = _legal_augments()
    aug["augments"][3].pop("slot_level")
    result = validate_augments(_modules(aug))
    assert "augment_slot_level_invalid" in _rules(result)


# ===========================================================================
# D validate V5 负例
# ===========================================================================
def test_validate_v5_cost_item_missing():
    aug = _legal_augments()
    aug["augments"][0]["cost"] = [{"item": "no_such_item", "count": 1}]
    result = validate_augments(_modules(aug))
    assert "augment_cost_item_missing" in _rules(result)


def test_validate_v5_cost_not_rare():
    aug = _legal_augments()
    aug["augments"][0]["cost"] = [{"item": "iron_ore", "count": 1}]  # normal
    result = validate_augments(_modules(aug))
    assert "augment_cost_not_rare" in _rules(result)


# ===========================================================================
# E validate V6 负例
# ===========================================================================
def test_validate_v6_quality_integer_rejected():
    aug = _legal_augments()
    aug["limit_by_rarity"] = [{"quality": 3, "times": 2}]  # 整数 → 禁（GRD-R02）
    result = validate_augments(_modules(aug))
    assert "limit_quality_invalid" in _rules(result)


def test_validate_v6_final_only_requires_legendary():
    aug = _legal_augments()
    aug["limit_by_rarity"] = [{"quality": "epic", "times": 2, "final_only": True}]
    result = validate_augments(_modules(aug))
    assert "limit_final_only_requires_legendary" in _rules(result)


def test_validate_v6_times_positive():
    aug = _legal_augments()
    aug["limit_by_rarity"] = [{"quality": "epic", "times": 0}]
    result = validate_augments(_modules(aug))
    assert "limit_times_invalid" in _rules(result)


def test_validate_v6_quality_max_two_rows():
    aug = _legal_augments()
    aug["limit_by_rarity"] = [
        {"quality": "legendary", "times": 2},
        {"quality": "legendary", "times": 1, "final_only": True},
        {"quality": "legendary", "times": 3},  # 第 3 行 → 超 2
    ]
    result = validate_augments(_modules(aug))
    assert "limit_quality_too_many" in _rules(result)


# ===========================================================================
# F validate V7 + V16 黄
# ===========================================================================
def test_validate_v7_final_tier_invalid_warning():
    # final_tier=true 但非 legendary → 2c2d V7 黄（final_tier_invalid）
    nodes = [
        {"id": "node_final_tier", "name": "终盘剑", "item": "flame_king_sword",
         "type": "weapon", "level": 7, "parent": None,
         "materials": [{"item": "fire_dragon_scale", "count": 3}],
         "rarity": "epic", "final": True, "final_tier": True},
    ]
    result = validate_augments(_modules(nodes=nodes))
    assert result["ok"] is True          # 黄不阻断
    assert "final_tier_invalid" in _rules(result, "warnings")
    assert "2c2d-V7" in _kinds(result, "warnings")


def test_validate_v16_augmentable_not_final_warning():
    # augmentable=true 但 final=false → 2c2a V16 黄（仅最终强化武器可客制）
    nodes = [
        {"id": "node_aug_bad", "name": "半成品", "item": "flame_king_sword",
         "type": "weapon", "level": 5, "parent": None,
         "materials": [{"item": "fire_dragon_scale", "count": 3}],
         "rarity": "fine", "final": False, "augmentable": True,
         "branch": ["node_child"]},
        {"id": "node_child", "name": "下段", "item": "iron_sword",
         "type": "weapon", "level": 6, "parent": "node_aug_bad",
         "materials": [{"item": "iron_ore", "count": 2}], "final": True},
    ]
    result = validate_augments(_modules(nodes=nodes))
    assert result["ok"] is True
    assert "augmentable_not_final_weapon" in _rules(result, "warnings")


# ===========================================================================
# G validate V8 黄
# ===========================================================================
def test_validate_v8_all_disabled_warning():
    aug = _legal_augments()
    for row in aug["augments"]:
        row["disabled"] = True
    result = validate_augments(_modules(aug))
    assert result["ok"] is True
    assert "augments_all_disabled" in _rules(result, "warnings")
    assert "2c2d-V8" in _kinds(result, "warnings")


def test_validate_v8_not_fired_when_disabled_off():
    # augments_enabled=false → V8 不提示（settings 已关，配置意图明确）
    aug = _legal_augments()
    for row in aug["augments"]:
        row["disabled"] = True
    result = validate_augments(_modules(aug, augments_enabled=False))
    assert "augments_all_disabled" not in _rules(result, "warnings")


# ===========================================================================
# H validate W2 / W3 黄
# ===========================================================================
def test_validate_w2_trace_warning():
    aug = _legal_augments()
    aug["augments"].append({
        "id": "aug_heal", "name": "回复", "kind": "numeric", "effect": "吸血5%（已砍）",
        "stat_key": "lifesteal", "disabled": True, "trace": True,
        "cost": [{"item": "dragonite", "count": 1}],
    })
    result = validate_augments(_modules(aug))
    assert result["ok"] is True
    assert "augment_trace_legacy" in _rules(result, "warnings")
    assert "2c2d-W2" in _kinds(result, "warnings")


def test_validate_w3_settings_off_but_data_warning():
    result = validate_augments(_modules(augments_enabled=False))
    assert result["ok"] is True
    assert "augments_disabled_but_data" in _rules(result, "warnings")


# ===========================================================================
# I limit_by_rarity 次数表
# ===========================================================================
def test_limit_by_rarity_table():
    res = limit_by_rarity(_modules())
    assert res["table"] == {"epic": 3, "legendary": 2}
    assert res["final_only"] == {"legendary": 1}
    assert len(res["rows"]) == 3
    assert res["rows"][0] == {"quality": "epic", "times": 3, "final_only": False,
                              "index": 0}
    assert res["rows"][2] == {"quality": "legendary", "times": 1, "final_only": True,
                              "index": 2}


def test_limit_by_rarity_missing_is_empty():
    assert limit_by_rarity(_modules(include_augments=False)) == {
        "rows": [], "table": {}, "final_only": {}}
    assert limit_by_rarity({}) == {"rows": [], "table": {}, "final_only": {}}


def test_limit_by_rarity_skips_invalid_rows():
    aug = _legal_augments()
    aug["limit_by_rarity"] = [
        {"quality": "epic", "times": 3},
        {"quality": 3, "times": 2},            # 非法 quality → 跳过
        {"quality": "legendary", "times": 0},  # times<1 → 跳过
    ]
    res = limit_by_rarity(_modules(aug))
    assert res["table"] == {"epic": 3}
    assert res["final_only"] == {}
    assert len(res["rows"]) == 1  # 仅合法行保留视图


# ===========================================================================
# J augment_eligible 资格判定
# ===========================================================================
def test_augment_eligible_all_pass():
    res = augment_eligible(_player(), _final_weapon())
    assert res["ok"] is True
    assert res["reason"] is None
    assert res["gates"] == {"sp_unlocked": True, "master_rank": True,
                            "final_weapon": True, "quality_ok": True}
    assert res["level"] == AUGMENT_MASTER_LEVEL_MIN
    assert res["need_level"] == AUGMENT_MASTER_LEVEL_MIN


def test_augment_eligible_sp_not_unlocked():
    res = augment_eligible(_player(sp_unlocked=False), _final_weapon())
    assert res["ok"] is False
    assert res["reason"] == "sp_not_unlocked"
    assert res["gates"]["sp_unlocked"] is False


def test_augment_eligible_master_rank_insufficient():
    res = augment_eligible(_player(level=40, unlocks={AUGMENT_SP_PANEL_ID: 1}),
                           _final_weapon())
    assert res["ok"] is False
    assert res["reason"] == "master_rank_insufficient"
    assert res["gates"]["master_rank"] is False


def test_augment_eligible_not_final_weapon():
    # final=false → 仅最终强化武器可客制（GU-A3）
    res = augment_eligible(_player(), _final_weapon(final=False))
    assert res["ok"] is False
    assert res["reason"] == "not_final_weapon"
    assert res["gates"]["final_weapon"] is False


def test_augment_eligible_augmentable_false():
    res = augment_eligible(_player(), _final_weapon(augmentable=False))
    assert res["reason"] == "not_final_weapon"


def test_augment_eligible_non_weapon_type():
    res = augment_eligible(_player(), _final_weapon(type="armor_head"))
    assert res["reason"] == "not_final_weapon"


def test_augment_eligible_quality_not_augmentable():
    # normal 品质不参与客制（GRD-R04）
    res = augment_eligible(_player(), _final_weapon(rarity="normal"))
    assert res["ok"] is False
    assert res["reason"] == "quality_not_augmentable"
    assert res["gates"]["quality_ok"] is False


def test_augment_eligible_quality_fine_rejected():
    assert AUGMENT_RARITY_QUALITIES == ("epic", "legendary")
    res = augment_eligible(_player(), _final_weapon(rarity="fine"))
    assert res["reason"] == "quality_not_augmentable"


def test_augment_eligible_player_none():
    res = augment_eligible(None, _final_weapon())
    assert res["ok"] is False
    assert res["reason"] == "sp_not_unlocked"
    assert res["level"] == 0


def test_augment_eligible_weapon_none():
    res = augment_eligible(_player(), None)
    assert res["ok"] is False
    assert res["reason"] == "not_final_weapon"


def test_augment_eligible_weapon_not_mapping():
    res = augment_eligible(_player(), "flame_king_sword")
    assert res["reason"] == "not_final_weapon"


def test_augment_eligible_guard_order():
    # 守卫顺序 GU-A1→A2→A3→A4：SP 未解锁优先于宗师不足
    res = augment_eligible(_player(level=10, sp_unlocked=False),
                           _final_weapon(rarity="normal"))
    assert res["reason"] == "sp_not_unlocked"
    # SP 已解锁但等级不足 → master_rank_insufficient（先于品质）
    res = augment_eligible(_player(level=10, unlocks={AUGMENT_SP_PANEL_ID: 1}),
                           _final_weapon(rarity="normal"))
    assert res["reason"] == "master_rank_insufficient"


def test_augment_eligible_pure_read_no_mutation():
    p = _player()
    w = _final_weapon()
    import copy
    p_copy = copy.deepcopy(p)
    w_copy = copy.deepcopy(w)
    augment_eligible(p, w)
    assert p == p_copy
    assert w == w_copy
