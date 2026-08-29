"""调合会话核心引擎单测（M8 批4A·路1 · qbot_rpg/core/alchemy_core.py）。

文件：tests/unit/test_alchemy_core.py
创建：2026-08-29
作者：Hermes 子agent-4A-1
功能：AlchemyCore 引擎单测——会话快照/连锁段数/追加/无会话/槽位/数量解析/刻度缺额/全物入料/
      触媒（方向修饰·注册制·非触媒拒绝）/PP 预算/特性池 source 分类/确认复核/面板悬念分级。

依据：docs/细化/细化_2c4f_投料触媒与能量条.md（FEED-01~10 / CAT-01~06 / TC-01~20）+
      docs/m8_contract_核心机制.md（§五 TSC / §六 FEED / §七 快照 / §四 QLT-11~13）+
      docs/m8_contract_数据与校验.md（§一 recipe / §二 traits / §四 items / §五 settings）。
规则出处以模块内注释为准（FEED/CAT/TSC/QLT 编号 + 定稿/细化行号）。

覆盖矩阵（每条正例 + 负例，断言精确数值/字段）：
  TC-01/07 连锁段数（6 同属性→5 段→效果等级5；2 段→1 级；0 段→0 级；超界钳制 A-1）
  TC-02     追加重算（append 追加链 → 连锁/刻度/池全量重算）
  TC-03     无会话（引擎不判会话状态，但 apply_feed 无快照拒绝 no_snapshot）
  TC-04     槽位上限（∑count ≤ recipe.slots，投满再投 → slots_overflow）
  TC-06     数量解析（条目 {item,count}：count 展开链位；持有不足全拒+差异 shortfall）
  TC-08     刻度未达标缺额（element_req 多档阶梯：met/levels_missing/shortfall）
  TC-09     全物入料（专家=index3 可投成品；非专家 → expert_required）
  TC-15~20  触媒（方向修饰 CAT-02 / 注册制提示 CAT-03 / 非触媒拒绝 CAT-05 /
            等级不足由指令壳判 TC-19 / 确认全量复核含触媒 TC-20）
  TSC-14    PP 预算（pp_budget / pp_cost_of normal=1·super=2 / can_afford_pp 会话内累计）
  INH-01~04 特性池 source 分类（素材→普通池 / 金色素材→超特性池 / 成品(专家)→原样入池 / ✨→觉醒池）
  FEED-10   确认全量复核（材料不足拒绝+差异）
  FEED-07   面板悬念分级（精通=引导语 vs 大师=精确阈值「火 4/5」；精通前隐藏）

测试风格对齐 tests/unit/test_quality.py / test_alchemy_session.py：纯 pytest、零 NoneBot、
断言精确 dict 字段；ctx 直测（items/traits/recipe 注册表 + count_item 计数，零 IO）。
"""

from __future__ import annotations

from typing import Any, Dict

from qbot_rpg.core.alchemy_core import (
    EXPERT_TIER_INDEX,
    MASTER_TIER_INDEX,
    PROFICIENT_TIER_INDEX,
    AlchemyCore,
)

# ---------------------------------------------------------------------------
# ctx 直测夹具：items/traits/recipe 注册表（id→def）+ inventory + count_item
# ---------------------------------------------------------------------------


def _items() -> Dict[str, dict]:
    """测试物品注册表（对齐 content/test_demo/items.json 形态：elements/traits/type/quality）。"""
    return {
        "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material",
                         "rarity": "普通", "elements": {"fire": 4},
                         "traits": ["trait_burn_boost"]},
        "spark": {"id": "spark", "name": "火花", "type": "material",
                  "elements": {"fire": 1}, "traits": []},
        "ice_crystal": {"id": "ice_crystal", "name": "冰晶石", "type": "material",
                        "elements": {"water": 4}, "traits": ["trait_mp_flow"]},
        "herb": {"id": "herb", "name": "草药", "type": "material", "traits": []},
        "fire_essence": {"id": "fire_essence", "name": "火之精华", "type": "material",
                         "rarity": "金色", "elements": {"fire": 6},
                         "traits": ["trait_fire_15"]},
        "gold_material": {"id": "gold_material", "name": "稀有火晶", "type": "material",
                          "rarity": "金色", "elements": {"fire": 3},
                          "traits": ["trait_fire_25"]},
        "awaken_mat": {"id": "awaken_mat", "name": "觉醒之尘", "type": "material",
                       "awaken": True, "elements": {"moon": 3},
                       "traits": ["trait_awaken_skill"]},
        # 成品/装备（全物入料 FEED-09/TC-09）
        "old_bomb": {"id": "old_bomb", "name": "旧爆弹", "type": "consumable",
                     "quality": "common", "elements": {"fire": 2},
                     "traits": ["trait_burn_boost"]},
        "old_potion": {"id": "old_potion", "name": "旧药水", "type": "consumable",
                       "quality": "uncommon", "elements": {"water": 2},
                       "traits": ["trait_heal_boost"]},  # source=成品 特性
        "old_armor": {"id": "old_armor", "name": "旧护甲", "type": "armor",
                      "quality": "rare"},  # 无 elements → 折算兜底 A-5
        # 触媒（type=触媒，CAT-05）
        "catalyst_fire": {"id": "catalyst_fire", "name": "爆裂壶", "type": "触媒",
                          "elements": {"fire": 5}},
        "catalyst_water": {"id": "catalyst_water", "name": "凝霜壶", "type": "触媒",
                           "elements": {"water": 5}},
        "catalyst_noelem": {"id": "catalyst_noelem", "name": "无向壶", "type": "触媒"},
        # 非触媒（TC-18 触媒无效）
        "herb_pack": {"id": "herb_pack", "name": "草药", "type": "material"},
    }


def _traits() -> Dict[str, dict]:
    """测试特性注册表（traits.json 7 字段：rarity/source/name）。"""
    return {
        "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化",
                             "rarity": "normal", "source": "素材"},
        "trait_fire_15": {"id": "trait_fire_15", "name": "灼烧强化·精",
                          "rarity": "super", "source": "金色素材"},
        "trait_fire_25": {"id": "trait_fire_25", "name": "灼烧强化·大师",
                          "rarity": "super", "source": "金色素材"},
        "trait_heal_boost": {"id": "trait_heal_boost", "name": "回复强化",
                             "rarity": "normal", "source": "成品"},
        "trait_mp_flow": {"id": "trait_mp_flow", "name": "魔力流转",
                          "rarity": "normal", "source": "素材"},
        "trait_awaken_skill": {"id": "trait_awaken_skill", "name": "觉醒之力",
                               "rarity": "normal", "source": "素材"},
    }


def _recipes() -> Dict[str, dict]:
    """测试配方注册表（recipe.json：slots/element_req/pp_budget/traits_inherit）。"""
    return {
        "r_flame": {"id": "r_flame", "name": "火焰弹", "slots": 5, "pp_budget": 5,
                    "traits_inherit": 2,
                    "element_req": {"fire": [
                        {"threshold": 5, "effect": "burn_dot"},
                        {"threshold": 8, "effect": "big_burn"},
                    ]}},
        "r_deep": {"id": "r_deep", "name": "星辉淬炼", "slots": 6, "pp_budget": 8,
                   "traits_inherit": 3,
                   "element_req": {"void": [{"threshold": 4, "effect": "shield"}]}},
    }


def _ctx(inv: Dict[str, int] | None = None) -> Dict[str, Any]:
    """构造 ctx（items/traits/recipe 注册表 + count_item 计数 + inventory dict）。"""
    inventory = inv if inv is not None else {}
    return {
        "items": _items(),
        "traits": _traits(),
        "recipe": _recipes(),
        "inventory": inventory,
        "count_item": lambda item_id: int(inventory.get(item_id, 0)),
    }


def _engine() -> AlchemyCore:
    """默认引擎（缺省 settings 兜底：chain_map 1:1…6:6 / pp_cost normal=1·super=2）。"""
    return AlchemyCore()


# 纯函数直测用：手工构造材料记录（对齐 _resolve_material 输出形态）
def _rec(item_id: str, count: int = 1, elements: Dict[str, int] | None = None,
         *, is_finished: bool = False, traits: list | None = None,
         quality: str | None = None, awaken: bool = False) -> dict:
    elems = elements if elements is not None else {"fire": 4}
    main = max(elems, key=lambda e: (elems[e], -1)) if elems else None
    return {
        "item": item_id, "count": count, "name": item_id,
        "elements": elems, "main_element": main,
        "traits": traits if traits is not None else [],
        "rarity": "普通", "quality": quality,
        "awaken": awaken, "is_finished": is_finished,
    }


# ---------------------------------------------------------------------------
# TC-01/07 连锁段数（FEED-06/L153，A-1）
# ---------------------------------------------------------------------------
def test_tc07_six_same_element_segments_five() -> None:
    """TC-07 正例：连续 6 个同属性材料 → 连锁 5 段 → 效果等级 5（chain_map 1:1…6:6）。"""
    core = _engine()
    mats = [_rec("fire_crystal") for _ in range(6)]
    out = core.compute_chain(mats)
    assert out["segments"] == 5
    assert out["pairs"] == 5
    assert out["effect_level"] == 5  # chain_map[5]=5


def test_tc01_two_same_element_one_segment_level1() -> None:
    """TC-01 正例：2 个同属性 → 1 段 → 效果等级 1。"""
    core = _engine()
    out = core.compute_chain([_rec("fire_crystal"), _rec("fire_crystal")])
    assert out["segments"] == 1
    assert out["effect_level"] == 1


def test_tc01_mixed_elements_segments() -> None:
    """TC-01 正例：火火水 → 1 段（首对同、次对不同）；首尾同属性相邻照计（A-1）。"""
    core = _engine()
    out = core.compute_chain([
        _rec("fire_crystal"), _rec("fire_crystal"), _rec("ice_crystal", elements={"water": 4}),
    ])
    assert out["segments"] == 1
    # 尾对相邻同属性照计（A-1）：水 火 火 → 1 段（末对计）
    out2 = core.compute_chain([
        _rec("ice_crystal", elements={"water": 4}), _rec("fire_crystal"), _rec("fire_crystal"),
    ])
    assert out2["segments"] == 1
    # 火 火 水 火 → 仅首对同 → 1 段（火水、水火 均异）
    out3 = core.compute_chain([
        _rec("fire_crystal"), _rec("fire_crystal"), _rec("ice_crystal", elements={"water": 4}),
        _rec("fire_crystal"),
    ])
    assert out3["segments"] == 1


def test_tc01_zero_segment_no_effect() -> None:
    """TC-01 负例：0 段（全异属性）→ 效果等级 0（无效果等级，A-1）。"""
    core = _engine()
    out = core.compute_chain([
        _rec("fire_crystal"), _rec("ice_crystal", elements={"water": 4}),
    ])
    assert out["segments"] == 0
    assert out["effect_level"] == 0


def test_tc01_count_expands_chain_positions() -> None:
    """TC-06 连锁单位口径（A-1）：火晶石*3 → 3 个链位 → 内部 2 段。"""
    core = _engine()
    out = core.compute_chain([_rec("fire_crystal", count=3)])
    assert out["segments"] == 2
    assert out["pairs"] == 2


def test_tc07_segments_over_map_clamped() -> None:
    """【工程补白 A-1】段数超 chain_map 上限（7 段 > 6）→ 钳制到最高配置等级 6。"""
    core = _engine()
    out = core.compute_chain([_rec("fire_crystal") for _ in range(8)])
    assert out["segments"] == 7
    assert out["effect_level"] == 6  # 钳制


def test_chain_map_configurable() -> None:
    """FEED-06 可配：settings.alchemy.chain_map 自定义映射生效。"""
    core = AlchemyCore(settings={"alchemy": {"chain_map": {1: 2, 2: 4, 5: 10}}})
    out = core.compute_chain([_rec("fire_crystal") for _ in range(6)])
    assert out["segments"] == 5
    assert out["effect_level"] == 10  # 5 段 → 10 级


# ---------------------------------------------------------------------------
# 会话快照（§7.1 STO-03 形态）
# ---------------------------------------------------------------------------
def test_new_snapshot_shape_and_version() -> None:
    """新会话快照形态：recipe_id/materials/chain/element_scores/pool/catalyst/pp/step/version=1。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], catalyst=None, job_tier="专家")
    assert snap["recipe_id"] == "r_flame"
    assert snap["materials"] == []
    assert snap["chain"]["segments"] == 0
    assert snap["element_scores"] == {}
    assert snap["pool"] == {"normal": [], "gold": [], "awaken": []}
    assert snap["catalyst"] is None
    assert snap["pp"] == {"used": 0, "budget": 5}  # r_flame pp_budget=5
    assert snap["step"] == "feed"
    assert core.snapshot_version(snap) == 1
    assert snap["job_tier_index"] == EXPERT_TIER_INDEX  # 专家=3


def test_new_snapshot_job_tier_index_variants() -> None:
    """job_tier 归一：int / str 称号 / 英文 / None → 档位索引。"""
    core = _engine()
    r = _recipes()["r_flame"]
    assert core.new_snapshot(r, job_tier=2)["job_tier_index"] == PROFICIENT_TIER_INDEX
    assert core.new_snapshot(r, job_tier="大师")["job_tier_index"] == MASTER_TIER_INDEX
    assert core.new_snapshot(r, job_tier="expert")["job_tier_index"] == EXPERT_TIER_INDEX
    assert core.new_snapshot(r, job_tier=None)["job_tier_index"] == 0  # 见习兜底


# ---------------------------------------------------------------------------
# TC-03 无会话（apply_feed 无快照拒绝；引擎不判会话状态——状态机批3 已落地）
# ---------------------------------------------------------------------------
def test_tc03_feed_without_snapshot_rejected() -> None:
    """TC-03 负例：无快照（None）调 apply_feed → no_snapshot 拒绝。"""
    core = _engine()
    out = core.apply_feed(None, [{"item": "fire_crystal"}], _ctx({"fire_crystal": 5}))
    assert out["ok"] is False
    assert out["reason"] == "no_snapshot"


def test_tc03_invalid_materials_rejected() -> None:
    """投料参数非法（非列表）→ invalid_materials（防御降级，不抛异常）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"])
    out = core.apply_feed(snap, "not-a-list", _ctx())  # type: ignore[arg-type]
    assert out["ok"] is False
    assert out["reason"] == "invalid_materials"


# ---------------------------------------------------------------------------
# TC-04 槽位上限（FEED-04/TC-04，A-6：∑count ≤ recipe.slots）
# ---------------------------------------------------------------------------
def test_tc04_slots_overflow_rejected() -> None:
    """TC-04 负例：r_flame slots=5，投 6 单位 → slots_overflow 拒绝「投料超槽位」。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    inv = {f"fire_crystal{i}": 1 for i in range(6)}
    ctx = _ctx(inv)
    ctx["items"] = dict(ctx["items"])
    for i in range(6):
        ctx["items"][f"fire_crystal{i}"] = dict(_items()["fire_crystal"])
    mats = [{"item": f"fire_crystal{i}"} for i in range(6)]
    out = core.apply_feed(snap, mats, ctx)
    assert out["ok"] is False
    assert out["reason"] == "slots_overflow"
    assert out["slots"] == 5
    assert out["units"] == 6


def test_tc04_slots_exact_fill_ok() -> None:
    """TC-04 正例：正好 5 单位（≤slots）→ 通过。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    inv = {f"fire_crystal{i}": 1 for i in range(5)}
    ctx = _ctx(inv)
    ctx["items"] = dict(ctx["items"])
    for i in range(5):
        ctx["items"][f"fire_crystal{i}"] = dict(_items()["fire_crystal"])
    mats = [{"item": f"fire_crystal{i}"} for i in range(5)]
    out = core.apply_feed(snap, mats, ctx)
    assert out["ok"] is True
    assert out["snap"]["materials"] and len(out["snap"]["materials"]) == 5


def test_tc04_count_occupies_slots() -> None:
    """A-6 负例：火晶石*3 + 火晶石*2 + 火晶石*1 = 6 单位 > slots 5 → 超槽位（count 占多槽）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(
        snap,
        [{"item": "fire_crystal", "count": 3},
         {"item": "fire_crystal", "count": 2},
         {"item": "fire_crystal", "count": 1}],
        _ctx({"fire_crystal": 6}),
    )
    assert out["ok"] is False
    assert out["reason"] == "slots_overflow"


# ---------------------------------------------------------------------------
# TC-06 数量解析（FEED-05/TC-06：条目 {item,count}；持有不足全拒+差异）
# ---------------------------------------------------------------------------
def test_tc06_count_parsed_and_chain_recomputed() -> None:
    """TC-06 正例：火晶石*2 + 冰晶石 → 解析生效（2 个链位），持有足够 → 通过。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(
        snap,
        [{"item": "fire_crystal", "count": 2}, {"item": "ice_crystal"}],
        _ctx({"fire_crystal": 2, "ice_crystal": 1}),
    )
    assert out["ok"] is True
    assert out["chain"]["segments"] == 1  # [火,火,冰] → 1 段
    assert out["snap"]["materials"][0]["count"] == 2


def test_tc06_insufficient_holdings_all_rejected() -> None:
    """TC-06/TC-11 负例：材料不足 → 全拒 + 差异 shortfall（原子口径，不部分入料）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(
        snap,
        [{"item": "fire_crystal", "count": 2}, {"item": "ice_crystal"}],
        _ctx({"fire_crystal": 1, "ice_crystal": 1}),  # 火晶石缺 1
    )
    assert out["ok"] is False
    assert out["reason"] == "materials_insufficient"
    assert out["shortfall"] == [{"item": "fire_crystal", "count": 2, "have": 1}]


def test_feed_unknown_item_rejected() -> None:
    """材料不存在（REC-03 引用硬拦语义）→ item_not_found。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(snap, [{"item": "ghost_item"}], _ctx({}))
    assert out["ok"] is False
    assert out["reason"] == "item_not_found"


# ---------------------------------------------------------------------------
# TC-02 追加重算（FEED-02/TC-02：append 追加 → 全链重算）
# ---------------------------------------------------------------------------
def test_tc02_append_recomputes_chain_scores_pool() -> None:
    """TC-02 正例：先投 火晶石,火花 → append 冰晶石 → 追加后全链重算（连锁/刻度）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    first = core.apply_feed(
        snap, [{"item": "fire_crystal"}, {"item": "spark"}],
        _ctx({"fire_crystal": 1, "spark": 1, "ice_crystal": 1}),
    )
    assert first["ok"] is True
    assert first["chain"]["segments"] == 1  # [火,火] → 1 段
    assert first["snap"]["version"] == 2

    second = core.apply_feed(
        first["snap"], [{"item": "ice_crystal"}],
        _ctx({"fire_crystal": 1, "spark": 1, "ice_crystal": 1}), append=True,
    )
    assert second["ok"] is True
    assert len(second["snap"]["materials"]) == 3  # 追加保留原链
    assert second["chain"]["segments"] == 1  # [火,火,冰] → 仍 1 段
    # 刻度：火 4+1 + 冰 4 = {fire:5, water:4}（追加后全量重算）
    assert second["element_scores"]["fire"] == 5
    assert second["element_scores"]["water"] == 4
    assert second["snap"]["version"] == 3  # §7.1 行4 version 递增


def test_tc02_append_holds_chain_bonus_flag() -> None:
    """FEED-08 连锁 ≥3 段 → chain_bonus=True（连锁奖励候选触发）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(
        snap,
        [{"item": "fire_crystal"}, {"item": "fire_crystal"}, {"item": "fire_crystal"}],
        _ctx({"fire_crystal": 3}),
    )
    assert out["ok"] is True
    assert out["chain"]["segments"] == 2
    assert out["chain_bonus"] is False  # 2 段 < 3
    out2 = core.apply_feed(
        out["snap"], [{"item": "fire_crystal"}],
        _ctx({"fire_crystal": 4}), append=True,
    )
    assert out2["chain"]["segments"] == 3
    assert out2["chain_bonus"] is True


# ---------------------------------------------------------------------------
# TC-08 属性刻度缺额（FEED-07/QLT-11，多档阶梯）
# ---------------------------------------------------------------------------
def test_tc08_scale_shortfall_reported() -> None:
    """TC-08 正例：火 4 < 阈值5 → met=False、shortfall=1、levels_missing=2（5/8 两档）。"""
    core = _engine()
    req = core.check_element_req(_recipes()["r_flame"], {"fire": 4})
    st = req["fire"]
    assert st["met"] is False
    assert st["score"] == 4
    assert st["shortfall"] == 1  # 距 5
    assert st["levels_missing"] == 2
    assert st["met_effect"] is None


def test_tc08_scale_met_partial_tier() -> None:
    """TC-08 正例：火 6 ≥ 阈值5 < 8 → met=True（burn_dot 显现）、仍差 1 档（levels_missing=1）。"""
    core = _engine()
    req = core.check_element_req(_recipes()["r_flame"], {"fire": 6})
    st = req["fire"]
    assert st["met"] is True
    assert st["met_effect"] == "burn_dot"
    assert st["levels_missing"] == 1
    assert st["shortfall"] == 0


def test_tc08_scale_missing_element_defaults_zero() -> None:
    """TC-08 负例：元素未投 → score=0、shortfall=整档（火系差 5 点）。"""
    core = _engine()
    req = core.check_element_req(_recipes()["r_flame"], {})
    st = req["fire"]
    assert st["score"] == 0
    assert st["shortfall"] == 5
    assert st["met"] is False


# ---------------------------------------------------------------------------
# TC-09 全物入料（FEED-09/L218：专家=档位索引3 起成品/装备可入料）
# ---------------------------------------------------------------------------
def test_tc09_expert_feed_finished_ok() -> None:
    """TC-09 正例：专家（index=3）投成品 old_bomb → 成功；成品 source 特性入池（INH-04）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(snap, [{"item": "old_bomb"}], _ctx({"old_bomb": 1}))
    assert out["ok"] is True
    assert out["snap"]["materials"][0]["is_finished"] is True
    assert out["element_scores"].get("fire") == 2  # 成品元素原样累计（A-5①）
    # 成品 source 特性原样入普通池（INH-04）
    assert ("trait_burn_boost", "灼烧强化", 1) in out["pool"]["normal"]


def test_tc09_non_expert_finished_rejected() -> None:
    """TC-09 负例：精通（index=2，未达专家）投成品 → expert_required 拒绝。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="精通")
    out = core.apply_feed(snap, [{"item": "old_bomb"}], _ctx({"old_bomb": 1}))
    assert out["ok"] is False
    assert out["reason"] == "expert_required"
    assert out["items"] == ["old_bomb"]


def test_tc09_raw_material_always_feedable() -> None:
    """TC-09 负例边界：非专家投原材料（type=material）→ 正常（全物入料只限成品/装备）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="见习")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}], _ctx({"fire_crystal": 1}))
    assert out["ok"] is True


def test_tc09_finished_without_elements_quality_fallback() -> None:
    """【工程补白 A-5④】无 elements 的成品（old_armor rare）→ 折算归「无」桶（rare=3）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_deep"], job_tier="专家")
    out = core.apply_feed(snap, [{"item": "old_armor"}], _ctx({"old_armor": 1}))
    assert out["ok"] is True
    assert out["element_scores"].get("void") == 3  # rare → 3


def test_tc09_finished_source_trait_in_pool_expert_only() -> None:
    """TC-09/INH-04 正例：专家投 source=成品 特性的成品 → 该特性原样入普通池。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(snap, [{"item": "old_potion"}], _ctx({"old_potion": 1}))
    assert out["ok"] is True
    assert ("trait_heal_boost", "回复强化", 1) in out["pool"]["normal"]


# ---------------------------------------------------------------------------
# TC-15~20 触媒（CAT-01~06 / 任务书：等级不足由指令壳判——引擎管 type 校验）
# ---------------------------------------------------------------------------
def test_tc15_catalyst_resolve_valid() -> None:
    """TC-15 正例：type=触媒 且注册 → ok、registered=True、返回触媒 def（方向修饰用）。"""
    core = _engine()
    out = core.catalyst_resolve("catalyst_fire", _ctx())
    assert out["ok"] is True
    assert out["registered"] is True
    assert out["catalyst"]["type"] == "触媒"
    assert out["catalyst"]["elements"]["fire"] == 5


def test_tc17_unregistered_catalyst_hint_only() -> None:
    """TC-17 正例：未注册触媒 → 仅提示不阻断（CAT-03 注册制），catalyst=None。"""
    core = _engine()
    out = core.catalyst_resolve("未注册壶", _ctx())
    assert out["ok"] is True  # 不阻断
    assert out["registered"] is False
    assert out["catalyst"] is None
    assert "未注册" in out["message"]


def test_tc18_non_catalyst_rejected() -> None:
    """TC-18 负例：非 type=触媒（草药）→ 「触媒无效」拒绝（CAT-05/L344）。"""
    core = _engine()
    out = core.catalyst_resolve("herb_pack", _ctx())
    assert out["ok"] is False
    assert out["registered"] is True
    assert "触媒无效" in out["message"]


def test_tc19_unlock_tier_is_shell_concern() -> None:
    """TC-19：引擎只做 type 校验，不判解锁等级（等级不足由指令壳判——任务书分界）。"""
    core = _engine()
    # 即使玩家仅见习，引擎对合法触媒仍返回 ok（等级门槛属壳层 CAT-01 R-07）
    out = core.catalyst_resolve("catalyst_fire", _ctx())
    assert out["ok"] is True
    assert out["registered"] is True


def test_tc20_verify_snapshot_catalyst_included() -> None:
    """TC-20 正例：确认全量复核含触媒（FEED-10/L179/CAT-04）——触媒移走 → 拒绝+差异。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], catalyst="catalyst_fire", job_tier="专家")
    # 材料投料成功
    fed = core.apply_feed(snap, [{"item": "fire_crystal"}],
                          _ctx({"fire_crystal": 1, "catalyst_fire": 1}))
    assert fed["ok"] is True
    # 全量复核：材料与触媒都在背包 → ok
    ok = core.verify_snapshot(_ctx({"fire_crystal": 1, "catalyst_fire": 1}), fed["snap"])
    assert ok["ok"] is True
    # 触媒被移走（catalyst_fire 0）→ 拒绝 + 差异
    bad = core.verify_snapshot(_ctx({"fire_crystal": 1}), fed["snap"])
    assert bad["ok"] is False
    assert bad["shortfall"] == [{"item": "catalyst_fire", "count": 1, "have": 0}]


def test_tc20_verify_snapshot_material_removed() -> None:
    """TC-20 负例：确认时材料被移走 → 拒绝 + 差异（防过期快照）。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    fed = core.apply_feed(snap, [{"item": "fire_crystal"}, {"item": "spark"}],
                          _ctx({"fire_crystal": 1, "spark": 1}))
    assert fed["ok"] is True
    bad = core.verify_snapshot(_ctx({"fire_crystal": 0, "spark": 1}), fed["snap"])
    assert bad["ok"] is False
    assert bad["shortfall"] == [{"item": "fire_crystal", "count": 1, "have": 0}]


def test_tc20_verify_snapshot_no_snapshot() -> None:
    """TC-20 负例：无快照复核 → no_snapshot。"""
    core = _engine()
    out = core.verify_snapshot(_ctx({}), None)
    assert out["ok"] is False
    assert out["reason"] == "no_snapshot"


# ---------------------------------------------------------------------------
# TC-16 触媒方向修饰（CAT-02/L153：连锁/刻度按触媒改变后的新属性）
# ---------------------------------------------------------------------------
def test_tc16_catalyst_changes_chain_segments() -> None:
    """TC-16 正例：无触媒 [冰,无属性] → 0 段；触媒=爆裂壶(fire) → 全链火 → 1 段（段数变化）。"""
    core = _engine()
    cat = core.catalyst_resolve("catalyst_fire", _ctx())["catalyst"]
    mats = [_rec("ice_crystal", elements={"water": 4}), _rec("herb", elements={})]
    assert core.compute_chain(mats)["segments"] == 0
    assert core.compute_chain(mats, cat)["segments"] == 1  # 方向修饰后全火


def test_tc16_catalyst_direction_modifies_scores() -> None:
    """TC-16 正例：触媒方向修饰刻度——火晶石(火4)+火花(火1) 带凝霜壶(water) → 全计水桶。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1, "spark": 1})
    cat = core.catalyst_resolve("catalyst_water", ctx)["catalyst"]
    recs = [_rec("fire_crystal"), _rec("spark", elements={"fire": 1})]
    plain = core.compute_element_scores(recs, ctx)
    assert plain.get("fire") == 5 and "water" not in plain
    mod = core.compute_element_scores(recs, ctx, cat)
    assert mod.get("water") == 5  # 火 4+1 → 水桶（按新属性 CAT-02）
    assert "fire" not in mod


def test_tc16_catalyst_via_apply_feed() -> None:
    """TC-16 集成：会话带触媒（new_snapshot catalyst=爆裂壶）→ apply_feed 重算按新属性。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1, "spark": 1, "catalyst_fire": 1})
    snap = core.new_snapshot(_recipes()["r_flame"], catalyst="catalyst_fire", job_tier="专家")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}, {"item": "spark"}], ctx)
    assert out["ok"] is True
    # 触媒 fire 方向：火晶石火4+火花火1 → 火 5（元素桶不变，但材料判定全为火）
    assert out["element_scores"].get("fire") == 5
    assert out["chain"]["segments"] == 1


def test_catalyst_without_elements_no_direction() -> None:
    """【工程补白 A-3】触媒无 elements（无向壶）→ 注册制通过但方向不修饰。"""
    core = _engine()
    ctx = _ctx({"ice_crystal": 1})
    out = core.catalyst_resolve("catalyst_noelem", ctx)
    assert out["ok"] is True
    assert out["registered"] is True
    cat = out["catalyst"]
    mats = [_rec("ice_crystal", elements={"water": 4})]
    # 无向壶无主元素 → 材料仍按自身属性判定（水），1 个材料 0 段
    assert core.compute_chain(mats, cat)["segments"] == 0
    assert core.compute_element_scores(mats, ctx, cat).get("water") == 4


# ---------------------------------------------------------------------------
# TSC-14 PP 预算（pp_budget / pp_cost_of / can_afford_pp 会话内累计）
# ---------------------------------------------------------------------------
def test_pp_budget_from_recipe() -> None:
    """TSC-14 正例：配方卡 PP 预算 = recipe.pp_budget（r_flame=5）；缺省 0。"""
    core = _engine()
    assert core.pp_budget(_recipes()["r_flame"]) == 5
    assert core.pp_budget({"id": "no_pp"}) == 0


def test_pp_cost_of_rarity_based() -> None:
    """TSC-14 正例：super=2 / normal=1（rarity 是 PP 计价唯一依据）；settings 可配。"""
    core = _engine()
    assert core.pp_cost_of({"rarity": "normal"}) == 1
    assert core.pp_cost_of({"rarity": "super"}) == 2
    custom = AlchemyCore(settings={"alchemy": {"pp_cost": {"normal": 3, "super": 7}}})
    assert custom.pp_cost_of({"rarity": "normal"}) == 3
    assert custom.pp_cost_of({"rarity": "super"}) == 7


def test_can_afford_pp_session_accumulated() -> None:
    """TSC-14 正例：会话内 PP 累计（used+super ≤ budget）；不足 → False；无快照 → False。"""
    core = _engine()
    snap = core.new_snapshot(_recipes()["r_flame"])  # budget 5
    super_trait = {"rarity": "super"}  # cost 2
    assert core.can_afford_pp(snap, super_trait) is True  # 0+2 ≤ 5
    snap["pp"] = {"used": 3, "budget": 5}
    assert core.can_afford_pp(snap, super_trait) is True  # 3+2=5 ≤ 5
    snap["pp"] = {"used": 4, "budget": 5}
    assert core.can_afford_pp(snap, super_trait) is False  # 4+2=6 > 5
    assert core.can_afford_pp(None, super_trait) is False


# ---------------------------------------------------------------------------
# 特性候选池 source 分类（FEED-08/INH-01~04/TSC-13/A-7）
# ---------------------------------------------------------------------------
def test_pool_source_classification() -> None:
    """FEED-08/TSC-13 正例：素材→普通池、金色素材→超特性池、✨→觉醒池、全局去重。"""
    core = _engine()
    mats = [
        _rec("fire_crystal", traits=["trait_burn_boost"]),        # 素材 → 普通
        _rec("gold_material", traits=["trait_fire_25"]),          # 金色素材 → 超特性池
        _rec("awaken_mat", traits=["trait_awaken_skill"], awaken=True),  # ✨ → 觉醒池
    ]
    pool = core.build_feature_pool(mats, _ctx({}), job_tier_index=EXPERT_TIER_INDEX)
    assert pool["normal"] == [("trait_burn_boost", "灼烧强化", 1)]
    assert pool["gold"] == [("trait_fire_25", "灼烧强化·大师", 2)]  # super PP2
    assert pool["awaken"] == [("trait_awaken_skill", "觉醒之力", 1)]


def test_pool_super_pp2_gold() -> None:
    """TSC-13/14 正例：金色素材 source=金色素材 → 超特性池，super PP2。"""
    core = _engine()
    mats = [_rec("fire_essence", traits=["trait_fire_15"])]
    pool = core.build_feature_pool(mats, _ctx({}), job_tier_index=EXPERT_TIER_INDEX)
    assert pool["gold"] == [("trait_fire_15", "灼烧强化·精", 2)]


def test_pool_finished_source_needs_expert() -> None:
    """TC-09/INH-04 防御：非专家（index<3）时成品 source 特性不入池。"""
    core = _engine()
    mats = [_rec("old_potion", traits=["trait_heal_boost"], is_finished=True)]
    pool = core.build_feature_pool(mats, _ctx({}), job_tier_index=PROFICIENT_TIER_INDEX)
    assert pool["normal"] == []
    pool2 = core.build_feature_pool(mats, _ctx({}), job_tier_index=EXPERT_TIER_INDEX)
    assert pool2["normal"] == [("trait_heal_boost", "回复强化", 1)]


def test_pool_unknown_trait_skipped() -> None:
    """STO-05 负例：特性 ID 引用失效 → 跳过不报错。"""
    core = _engine()
    mats = [_rec("fire_crystal", traits=["trait_ghost"])]
    pool = core.build_feature_pool(mats, _ctx({}), job_tier_index=0)
    assert pool == {"normal": [], "gold": [], "awaken": []}


# ---------------------------------------------------------------------------
# FEED-07 面板悬念分级（STO-08/QLT-13，A-8：精通=引导语 vs 大师=精确阈值）
# ---------------------------------------------------------------------------
def _fed_flame_snap(core: AlchemyCore, ctx: Dict[str, Any]) -> dict:
    """投 火晶石+火花（火 4+1=5）→ 快照（r_flame 阈值 5/8）。"""
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="专家")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}, {"item": "spark"}], ctx)
    assert out["ok"] is True
    return out["snap"]


def test_panel_guide_text_for_proficient() -> None:
    """FEED-07/STO-08 正例：精通（index=2）→ 引导语「火系还差一点，试试多投火系材料？」。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1, "spark": 1})
    snap = _fed_flame_snap(core, ctx)
    panel = core.assemble_panel(snap, ctx, job_tier_index=PROFICIENT_TIER_INDEX)
    assert panel["scale_suspense"] == 1
    st = panel["element_req_status"]["fire"]
    assert st["met"] is True  # 5 ≥ 5
    assert st["display"] == "火系达标"


def test_panel_guide_text_unmet() -> None:
    """FEED-07 正例：精通且未达标 → 引导语提示多投火系材料。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1})
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="精通")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}], ctx)  # 火 4 < 5
    assert out["ok"] is True
    panel = core.assemble_panel(out["snap"], ctx, job_tier_index=PROFICIENT_TIER_INDEX)
    assert panel["scale_suspense"] == 1
    assert panel["element_req_status"]["fire"]["display"] == "火系还差一点，试试多投火系材料？"


def test_panel_precise_threshold_for_master() -> None:
    """FEED-07/STO-08 正例：大师（index=4）→ 精确阈值「火 4/5」（未达标）与「火 5/5 达标」。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1})
    snap = core.new_snapshot(_recipes()["r_flame"], job_tier="大师")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}], ctx)  # 火 4 < 5
    assert out["ok"] is True
    panel = core.assemble_panel(out["snap"], ctx, job_tier_index=MASTER_TIER_INDEX)
    assert panel["scale_suspense"] == 2
    assert panel["element_req_status"]["fire"]["display"] == "火 4/5"

    # 再投火花 → 火 5 ≥ 5 → 达标显示 met 阈值 5/5
    ctx2 = _ctx({"fire_crystal": 1, "spark": 1})
    snap2 = _fed_flame_snap(core, ctx2)
    panel2 = core.assemble_panel(snap2, ctx2, job_tier_index=MASTER_TIER_INDEX)
    assert panel2["element_req_status"]["fire"]["display"] == "火 5/5 达标"


def test_panel_scale_hidden_below_proficient() -> None:
    """QLT-13/A-8 负例：精通前（index=1 正式）→ 刻度效果不显现（display=None）。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1, "spark": 1})
    snap = _fed_flame_snap(core, ctx)
    panel = core.assemble_panel(snap, ctx, job_tier_index=1)
    assert panel["scale_suspense"] == 0
    assert panel["element_req_status"]["fire"]["display"] is None


def test_panel_structure_fields() -> None:
    """面板结构：材料/连锁/特性位/PP/触媒/步骤/版本 全字段。"""
    core = _engine()
    ctx = _ctx({"fire_crystal": 1, "spark": 1})
    snap = core.new_snapshot(_recipes()["r_flame"], catalyst="catalyst_fire", job_tier="专家")
    out = core.apply_feed(snap, [{"item": "fire_crystal"}, {"item": "spark"}],
                          _ctx({"fire_crystal": 1, "spark": 1, "catalyst_fire": 1}))
    assert out["ok"] is True
    panel = core.assemble_panel(out["snap"], ctx, job_tier_index=EXPERT_TIER_INDEX)
    assert panel["ok"] is True
    assert panel["recipe_id"] == "r_flame"
    assert panel["recipe_name"] == "火焰弹"
    assert len(panel["materials"]) == 2
    assert panel["chain"]["segments"] == 1
    assert panel["pp"] == {"used": 0, "budget": 5}
    assert panel["traits_inherit"] == 2
    assert panel["catalyst"] == "catalyst_fire"
    assert panel["step"] == "feed"
    assert panel["version"] == 2
    assert panel["pool"] == {"normal": [("trait_burn_boost", "灼烧强化", 1)],
                             "gold": [], "awaken": []}


def test_panel_no_snapshot_defensive() -> None:
    """面板防御：无快照 → ok=False no_snapshot。"""
    core = _engine()
    panel = core.assemble_panel(None, _ctx({}), job_tier_index=0)
    assert panel["ok"] is False
    assert panel["reason"] == "no_snapshot"
