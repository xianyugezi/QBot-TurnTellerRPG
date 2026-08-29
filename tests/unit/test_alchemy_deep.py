"""深度炼金引擎单测（M8 批8-1·路A · qbot_rpg/core/alchemy_deep.py）。

文件：tests/unit/test_alchemy_deep.py
创建：2026-08-29
作者：Hermes 子agent-8-1A
功能：DeepEngine 引擎单测——深度会话快照/进化条件+永久解锁/镶核心品质上限/加成限次/
      挑战苛刻条件判定+降级退料。ctx 直测（items/recipe 注册表 + count_item/remove_item/
      add_item hook + currencies + upgrade_unlocks），零 IO 零 NoneBot（引擎全同步纯函数）。

依据：docs/m8_contract_指令契约.md §6（GU-20~22/F-06/M-06/TC-14）、§7（GU-23~25/F-07/M-07/
      CASC-05/ATO-05/TC-15）、§8（GU-26~28/F-08/M-08/TC-16）、§15（GU-47~49/F-16/M-16/TC-23）、
      §五 ATO-05/06 + docs/m8_contract_核心机制.md（QLT-08 核心/挑战品质上限、QLT-09 加成道具、
      CASC-05 进化计数防跳）+ 细化_2c4c COR-01~03 + 细化_2c4d §16。
规则出处以引擎模块注释为准（GU/F/COR/ATO/CASC/QLT 编号 + 定稿/细化行号）。

覆盖矩阵（每条正例 + 反例，断言精确数值/字段）：
  TC-14  深度炼金（精通拒「深度未解锁」/ 大师开深度面板快照：6 槽/核心槽/进化线/challenge_alchemy）
  TC-15  进化（宗师+炼金产出 N 次 合成不计 / 未满拒绝 / 扣材料+宝石 永久解锁+幂等 ATO-05）
  TC-16  镶核心 / 加成（品质上限+20 火适配 / 核心不匹配拒 / 可换 destroy·return / 加成限 1 次）
  TC-23  挑战（连锁≥5 且刻度≥2 达标→品质上限+10 / 未达标→降级+退 50% 材料 只退一次 ATO-06）
  反例   宝石不足/材料不足零副作用、非核心/非加成、非大师/非宗师、非深度会话
  幂等   已解锁重复 /进化 零扣；挑战已结算重复零退零加

测试风格对齐 tests/unit/test_alchemy_settle.py / test_alchemy_core.py：纯 pytest（引擎全同步
纯函数，无需 async）、断言精确 dict 字段、ctx 直测零 IO。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from qbot_rpg.core.alchemy_deep import (
    EVOLVE_UNLOCK_SOURCE,
    DeepEngine,
)
from qbot_rpg.core.alchemy_session import CHALLENGE_SESSION

# ---------------------------------------------------------------------------
# 测试数据（items/recipe 注册表，对齐 content/test_demo 形态 + 核心/加成物品 D-1/D-4 标记）
# ---------------------------------------------------------------------------


def _items() -> Dict[str, dict]:
    """测试物品注册表（核心 type=="核心" / 加成 type=="加成"，工程补白 D-1/D-4 标记）。"""
    return {
        "core_fire": {"id": "core_fire", "name": "龙晶核", "type": "核心",
                      "elements": {"fire": 8}, "core": {"cap_bonus": 20}},  # COR-02 示例
        "core_water": {"id": "core_water", "name": "水灵核", "type": "核心",
                       "elements": {"water": 8}, "core": {"cap_bonus": 15}},
        "core_plain": {"id": "core_plain", "name": "通用核", "type": "核心",
                       "core": {"cap_bonus": 5}},  # 无元素（配方有刻度时视为不匹配，D-2）
        "ash_core": {"id": "ash_core", "name": "灰烬核心", "type": "material"},  # 非核心
        "boost_stone": {"id": "boost_stone", "name": "贤者之石", "type": "加成",
                        "boost": {"quality": 30}},  # QLT-09 示例 品质+30
        "boost_fire": {"id": "boost_fire", "name": "精炼贤者石", "type": "加成",
                       "boost": {"quality": 50, "element": "fire"}},  # 大幅提品质+改属性
        "boost_plain": {"id": "boost_plain", "name": "简易增幅剂", "type": "加成"},  # 回落默认 30
        "herb": {"id": "herb", "name": "草药", "type": "material"},  # 非加成
        "mat_fire": {"id": "mat_fire", "name": "火晶石", "type": "material",
                     "elements": {"fire": 4}},
        "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable",
                       "quality": "common"},
    }


def _recipes() -> Dict[str, dict]:
    """测试配方注册表（深度配方 master_only + 进化线 r_low→r_high + 无刻度深度配方）。"""
    return {
        "r_deep": {"id": "r_deep", "name": "炼狱爆弹·深度", "level": 40, "kind": "craft",
                   "master_only": True, "slots": 6, "quality_cap": 100,
                   "output": {"item": "flame_bomb", "count": 1},
                   "materials": [{"id": "mat_fire", "count": 2}],
                   "cost": {"coins": 0, "gem": 0},
                   "element_req": {"fire": [{"threshold": 5, "effect": "burn"}]}},
        "r_deep_noreq": {"id": "r_deep_noreq", "name": "无刻度深度配方", "level": 40,
                         "kind": "craft", "master_only": True, "slots": 6,
                         "output": {"item": "flame_bomb", "count": 1}},
        "r_low": {"id": "r_low", "name": "火焰弹配方", "level": 5, "kind": "craft",
                  "master_only": False, "slots": 4,
                  "output": {"item": "flame_bomb", "count": 1},
                  "materials": [{"id": "mat_fire", "count": 2}],
                  "cost": {"coins": 0, "gem": 10},  # D-7 进化宝石费 recipe.cost.gem
                  "evolve_to": {"id": "r_high", "condition": {"count": 5, "source": "炼金产出"}}},
        "r_high": {"id": "r_high", "name": "烈焰弹·改配方", "level": 8, "kind": "craft",
                   "master_only": False, "slots": 6,
                   "output": {"item": "flame_bomb", "count": 1}},
        "r_no_evolve": {"id": "r_no_evolve", "name": "无进化配方", "level": 5, "kind": "craft",
                        "master_only": False, "slots": 4,
                        "output": {"item": "flame_bomb", "count": 1}},
    }


def _settings(*, challenge: Optional[dict] = None, boost_quality: int = 30,
              replace_mode: str = "destroy") -> Dict[str, Any]:
    """settings dict（alchemy.challenge 苛刻条件配置 D-5 / boost_quality D-4 / core D-3）。"""
    return {"alchemy": {
        "challenge": challenge if challenge is not None else {
            "chain_segments": 5, "element_hits": 2, "operator": "and",
            "quality_cap_bonus": 10, "degrade_levels": 1,
        },
        "boost_quality": boost_quality,
        "core": {"replace_mode": replace_mode},
    }}


def _player(tier: int) -> Dict[str, Any]:
    """玩家 dict（档位索引直设 proficiency.alchemy.level；对齐 _tier_index 的 min(level,6)）。"""
    return {"proficiency": {"alchemy": {"level": tier}}}


# ---------------------------------------------------------------------------
# ctx 直测夹具：inventory + count_item/remove_item/add_item hook + currencies + upgrade_unlocks
# ---------------------------------------------------------------------------


def _make_remove(inv: Dict[str, int]):
    """remove_item hook：就地扣减（不足 → not_enough 拒绝），返回 {ok,...}。"""
    def remove(item_id: str, count: int) -> dict:
        have = int(inv.get(item_id, 0))
        if have < count:
            return {"ok": False, "reason": "not_enough"}
        left = have - count
        if left <= 0:
            inv.pop(item_id, None)
        else:
            inv[item_id] = left
        return {"ok": True, "removed": count}
    return remove


def _make_add(added_list: List[dict]):
    """add_item hook：记录回包条目（退料/拆回核心用）并追加到 added_list。"""
    def add(item_id: str, count: int, bound: bool) -> dict:
        added_list.append({"item_id": item_id, "count": count, "bound": bound})
        return {"ok": True, "added": count}
    return add


def _ctx(inventory: Optional[Dict[str, int]] = None, *, player: Optional[dict] = None,
         currencies: Optional[Dict[str, int]] = None,
         upgrade_unlocks: Optional[Dict[str, Any]] = None) -> tuple:
    """构造深度引擎 ctx；返回 (ctx, added_list, inv, cur, unlocks)。

    - added_list：add_item 回包记录（退料/拆回旧核心）。
    - inv / cur / unlocks：就地可变结构（断言扣料/扣宝石/解锁落点）。
    """
    inv: Dict[str, int] = dict(inventory) if inventory else {}
    cur: Dict[str, int] = dict(currencies) if currencies else {}
    unlocks: Dict[str, Any] = dict(upgrade_unlocks) if upgrade_unlocks else {}
    added_list: List[dict] = []
    ctx: Dict[str, Any] = {
        "items": _items(),
        "recipe": _recipes(),
        "inventory": inv,
        "count_item": lambda iid: int(inv.get(iid, 0)),
        "remove_item": _make_remove(inv),
        "add_item": _make_add(added_list),
        "currencies": cur,
        "upgrade_unlocks": unlocks,
    }
    if player is not None:
        ctx["player"] = player
    return ctx, added_list, inv, cur, unlocks


def _deep_snap(eng: DeepEngine, *, tier: int = 4, recipe_id: str = "r_deep", **kw: Any) -> dict:
    """构造深度会话快照（经 eng.deep_snapshot 生成 + kw 覆盖，F-06 形态）。"""
    snap = eng.deep_snapshot(_recipes()[recipe_id], job_tier_index=tier)
    for k, v in kw.items():
        snap[k] = v
    return snap


# ---------------------------------------------------------------------------
# TC-14 /深度炼金（GU-20~22/F-06；精通拒「深度未解锁」，大师开深度面板快照）
# ---------------------------------------------------------------------------


def test_tc14_deep_eligible_proficient_rejected() -> None:
    """TC-14 反例：精通（档位 2）→ 拒绝「深度未解锁」（GU-20/L25/L192）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.deep_eligible(_player(2), "alchemy", _recipes()["r_deep"])
    assert r["ok"] is False
    assert r["reason"] == "tier_too_low"
    assert r["message"] == "深度未解锁"


def test_tc14_deep_eligible_master_ok() -> None:
    """TC-14 正例：大师（档位 4）→ 解锁通过（GU-20 炼金职业 ≥ 大师）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.deep_eligible(_player(4), "alchemy", _recipes()["r_deep"])
    assert r["ok"] is True
    assert r["tier_index"] == 4


def test_tc14_deep_eligible_non_deep_recipe_rejected() -> None:
    """TC-14 反例：非 master_only 配方 → 非深度配方拒绝（F-06 深度配方标记）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.deep_eligible(_player(6), "alchemy", _recipes()["r_low"])
    assert r["ok"] is False
    assert r["reason"] == "not_deep_recipe"


def test_tc14_deep_snapshot_structure() -> None:
    """TC-14 正例：大师开深度会话 → 深度面板快照（6 槽/核心槽/进化线/challenge_alchemy 类型）。"""
    eng = DeepEngine(settings=_settings())
    snap = eng.deep_snapshot(_recipes()["r_deep"], job_tier_index=4)
    # F-06/GU-22/MUT-07：深度会话类型 challenge_alchemy
    assert snap["session_type"] == CHALLENGE_SESSION
    assert snap["slots"] == 6                        # 深度面板 6 槽（F-06，D-10）
    assert snap["core_slot"] is None                 # 核心槽初始空（COR-01）
    assert snap["core_cap"] == 0
    assert snap["buff_used"] is False
    assert snap["buff_bonus"] == 0
    assert snap["quality_cap_bonus"] == 0
    assert snap["challenge"] is False
    assert snap["challenge_refunded"] is False
    assert snap["challenge_settled"] is False
    assert snap["traits_inherit"] == 3               # 3 普通位（F-06，D-10）
    assert snap["gold_slot_exclusive"] is True       # +1 金 第 4 位独占（TSC-13）
    assert snap["quality_cap"] == 100
    assert snap["recipe_id"] == "r_deep"
    assert snap["version"] == 1
    # 无 evolve_to → 进化线 None
    assert snap["evolve_line"] is None


def test_tc14_deep_snapshot_evolve_line() -> None:
    """TC-14 正例：配方带 evolve_to → 深度快照进化线 {target_id, count, source}（F-06/7 落点）。"""
    eng = DeepEngine(settings=_settings())
    snap = eng.deep_snapshot(_recipes()["r_low"], job_tier_index=4)
    assert snap["evolve_line"] == {
        "target_id": "r_high", "count": 5, "source": "炼金产出",
    }


# ---------------------------------------------------------------------------
# TC-15 /进化（GU-23~25/F-07/CASC-05/ATO-05；宗师+炼金产出 N 次 合成不计，永久解锁+幂等）
# ---------------------------------------------------------------------------


def test_tc15_evolve_eligible_met() -> None:
    """TC-15 正例：宗师 + 低阶配方炼金产出 5 次 → {ok, count:5, need:5}（GU-23/24）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.evolve_eligible(_player(5), "alchemy", _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is True
    assert r["count"] == 5
    assert r["need"] == 5
    assert r["target_id"] == "r_high"


def test_tc15_evolve_eligible_tier_too_low() -> None:
    """TC-15 反例：大师（档位 4）→ 宗师门槛拒绝（GU-23）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.evolve_eligible(_player(4), "alchemy", _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is False
    assert r["reason"] == "tier_too_low"


def test_tc15_evolve_eligible_count_not_met() -> None:
    """TC-15 反例：宗师 + 炼金产出 4/5 → 条件不满足拒绝（GU-24）。"""
    eng = DeepEngine(settings=_settings())
    r = eng.evolve_eligible(_player(5), "alchemy", _recipes()["r_low"], {"r_low": 4})
    assert r["ok"] is False
    assert r["reason"] == "count_not_met"
    assert r["count"] == 4
    assert r["need"] == 5


def test_tc15_evolve_eligible_synth_not_counted() -> None:
    """TC-15 反例（CASC-05 进化计数防跳）：合成刷 N 次不计入 → 炼金产出 0 → 拒绝。

    produce_counts 由调用方只计炼金层产出（/合成 不计数）；本引擎按传入计数原样校验。
    """
    eng = DeepEngine(settings=_settings())
    # 模拟 /合成 刷 100 次（不计入 produce_counts）+ 炼金产出 0 → 拒绝
    r = eng.evolve_eligible(_player(5), "alchemy", _recipes()["r_low"], {"r_low": 0})
    assert r["ok"] is False
    assert r["reason"] == "count_not_met"


def test_tc15_evolve_unlock_ok() -> None:
    """TC-15 正例：宗师 + 产出满 N + 材料宝石足量 → 扣料+扣宝石 → 永久解锁下一级（F-07）。

    message「✅ 继承 2 额外槽（6 槽）」（M-07：r_low 4 槽 → r_high 6 槽）。
    """
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(
        {"mat_fire": 2}, player=_player(5), currencies={"gem": 10}
    )
    r = eng.evolve_unlock(_player(5), ctx, _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is True
    assert r["message"] == "✅ 继承 2 额外槽（6 槽）"
    assert r["unlocked"] == "r_high"
    assert r["extra_slots"] == 2
    assert r["target_slots"] == 6
    assert r["gem_cost"] == 10
    assert r["source_id"] == "r_low"
    # 扣材料+扣宝石（F-07/GU-25）
    assert inv.get("mat_fire", 0) == 0
    assert cur.get("gem", 0) == 0
    # 永久解锁写 ctx["upgrade_unlocks"]（D-8 对齐批2 U-F2 同表；特性不继承 TSC-18）
    rec = unlocks["r_high"]
    assert rec["source"] == EVOLVE_UNLOCK_SOURCE
    assert rec["gem_cost"] == 10
    assert rec["source_id"] == "r_low"
    assert rec["inherit"]["traits_inherited"] is False
    assert rec["inherit"]["extra_slots"] == 2


def test_tc15_evolve_unlock_idempotent() -> None:
    """TC-15 反例（ATO-05 幂等）：目标已解锁 → 「已解锁」不重复扣料/宝石。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(
        {"mat_fire": 2}, player=_player(5), currencies={"gem": 10},
        upgrade_unlocks={"r_high": {"source": "evolve", "gem_cost": 10}},
    )
    r = eng.evolve_unlock(_player(5), ctx, _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is False
    assert r["reason"] == "already_unlocked"
    assert r["message"] == "已解锁"
    assert r["idempotent"] is True
    # 零副作用：材料/宝石未被扣
    assert inv.get("mat_fire", 0) == 2
    assert cur.get("gem", 0) == 10
    assert len(added) == 0


def test_tc15_evolve_unlock_gem_insufficient() -> None:
    """TC-15 反例（GU-25/M-07 宝石不足）：宝石 5 < 10 → 全拒零副作用（ATO-01）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(
        {"mat_fire": 2}, player=_player(5), currencies={"gem": 5}
    )
    r = eng.evolve_unlock(_player(5), ctx, _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is False
    assert r["reason"] == "gem_insufficient"
    assert r["gem_need"] == 10
    # 零副作用：材料未扣、无解锁
    assert inv.get("mat_fire", 0) == 2
    assert cur.get("gem", 0) == 5
    assert "r_high" not in unlocks
    assert len(added) == 0


def test_tc15_evolve_unlock_materials_insufficient() -> None:
    """TC-15 反例（GU-25 材料不足）：材料 1 < 2 → 全拒+差异清单（ATO-01 全拒+差异）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(
        {"mat_fire": 1}, player=_player(5), currencies={"gem": 10}
    )
    r = eng.evolve_unlock(_player(5), ctx, _recipes()["r_low"], {"r_low": 5})
    assert r["ok"] is False
    assert r["reason"] == "materials_insufficient"
    assert r["shortfall"] == [{"item": "mat_fire", "count": 2, "have": 1}]
    # 零副作用
    assert inv.get("mat_fire", 0) == 1
    assert cur.get("gem", 0) == 10
    assert "r_high" not in unlocks


# ---------------------------------------------------------------------------
# TC-16 /镶核心 /加成（GU-26~28/F-08/COR-01~03/QLT-09；品质上限+X 属性适配/可换/加成限 1 次）
# ---------------------------------------------------------------------------


def test_tc16_mount_core_ok() -> None:
    """TC-16 正例：大师+深度会话+火核心（火刻度配方）→ 消耗入装，品质上限+20、火适配（COR-02）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_fire": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r = eng.mount_core(_player(4), snap, _items()["core_fire"], ctx)
    assert r["ok"] is True
    assert r["message"] == "✅ 品质上限+20、火适配"
    assert r["replaced"] is False
    assert r["core"]["core_id"] == "core_fire"
    assert r["core"]["cap_bonus"] == 20
    assert r["core"]["element"] == "fire"
    # 快照写入（core_slot + core_cap 对齐 SettleEngine._extra_cap②）
    s2 = r["snap"]
    assert s2["core_slot"]["core_id"] == "core_fire"
    assert s2["core_cap"] == 20
    # 核心物品当场消耗（COR-02）
    assert inv.get("core_fire", 0) == 0


def test_tc16_mount_core_mismatch() -> None:
    """TC-16 反例（GU-27 核心不匹配）：水核心 × 火刻度配方 → 拒绝「核心不匹配」，核心不消耗。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_water": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r = eng.mount_core(_player(4), snap, _items()["core_water"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "core_mismatch"
    assert r["message"] == "核心不匹配"
    assert inv.get("core_water", 0) == 1  # 未消耗


def test_tc16_mount_core_not_core_item() -> None:
    """TC-16 反例：非核心物品（type≠核心）→ 「核心不匹配」拒绝（COR-03 核心表并入效果表）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"ash_core": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r = eng.mount_core(_player(4), snap, _items()["ash_core"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "not_core_item"
    assert r["message"] == "核心不匹配"


def test_tc16_mount_core_non_master() -> None:
    """TC-16 反例（TC-26/COR-01）：专家（档位 3）→ 拒绝「核心不匹配」、核心不消耗。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_fire": 1}, player=_player(3))
    snap = _deep_snap(eng, tier=3)
    r = eng.mount_core(_player(3), snap, _items()["core_fire"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "tier_too_low"
    assert r["message"] == "核心不匹配"
    assert inv.get("core_fire", 0) == 1


def test_tc16_mount_core_no_deep_session() -> None:
    """TC-16 反例（TC-26）：非深度会话快照 → 拒绝「核心不匹配」（GU-26 深度会话中）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_fire": 1}, player=_player(4))
    plain_snap = {"recipe_id": "r_deep"}  # 非深度快照（无 core_slot/session_type）
    r = eng.mount_core(_player(4), plain_snap, _items()["core_fire"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "no_deep_session"
    assert r["message"] == "核心不匹配"
    assert inv.get("core_fire", 0) == 1


def test_tc16_mount_core_plain_core_on_req_recipe_mismatch() -> None:
    """TC-16 反例（D-2）：无元素核心 × 有刻度配方 → 不匹配（无「属性适配」可言）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_plain": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4, recipe_id="r_deep")  # fire 刻度配方
    r = eng.mount_core(_player(4), snap, _items()["core_plain"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "core_mismatch"


def test_tc16_mount_core_plain_core_on_no_req_recipe_ok() -> None:
    """TC-16 正例（D-2）：无刻度配方 → 任意核心放行（无 element_req 无约束）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"core_plain": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4, recipe_id="r_deep_noreq")
    r = eng.mount_core(_player(4), snap, _items()["core_plain"], ctx)
    assert r["ok"] is True
    assert r["core"]["cap_bonus"] == 5


def test_tc16_mount_core_swap_destroy() -> None:
    """TC-16 正例（COR-02 可换）：再镶核心 → 替换成功，旧核心随替换销毁（D-3 默认 destroy）。"""
    eng = DeepEngine(settings=_settings(replace_mode="destroy"))
    ctx, added, inv, cur, unlocks = _ctx({"core_fire": 2}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r1 = eng.mount_core(_player(4), snap, _items()["core_fire"], ctx)
    snap1 = r1["snap"]
    r2 = eng.mount_core(_player(4), snap1, _items()["core_fire"], ctx)
    assert r2["ok"] is True
    assert r2["replaced"] is True
    assert r2["core"]["core_id"] == "core_fire"
    assert inv.get("core_fire", 0) == 0          # 两颗都消耗（第 1 颗入装 + 第 2 颗替换）
    assert len(added) == 0                        # 旧核心销毁 → 无拆回


def test_tc16_mount_core_swap_return() -> None:
    """TC-16 正例（COR-02 可换 + D-3 可配）：replace_mode="return" → 旧核心无损拆回。"""
    eng = DeepEngine(settings=_settings(replace_mode="return"))
    ctx, added, inv, cur, unlocks = _ctx({"core_fire": 2}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r1 = eng.mount_core(_player(4), snap, _items()["core_fire"], ctx)
    snap1 = r1["snap"]
    r2 = eng.mount_core(_player(4), snap1, _items()["core_fire"], ctx)
    assert r2["ok"] is True
    assert r2["replaced"] is True
    # 旧核心拆回 1 颗（added_list 记录）
    assert added == [{"item_id": "core_fire", "count": 1, "bound": True}]


def test_tc16_buff_ok() -> None:
    """TC-16 正例：宗师 + 加成道具 → 品质+30（QLT-09/M-08），快照 buff_used/buff_bonus 写入。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"boost_stone": 1}, player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.buff(_player(5), snap, _items()["boost_stone"], ctx)
    assert r["ok"] is True
    assert r["message"] == "✅ 品质+30"
    assert r["buff_bonus"] == 30
    assert r["snap"]["buff_used"] is True
    assert r["snap"]["buff_bonus"] == 30
    assert inv.get("boost_stone", 0) == 0  # 道具消耗（F-08）


def test_tc16_buff_element_change() -> None:
    """TC-16 正例：加成带元素 → 大幅提品质+改属性（M-08「改属性」），快照 buff_element 写入。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"boost_fire": 1}, player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.buff(_player(5), snap, _items()["boost_fire"], ctx)
    assert r["ok"] is True
    assert r["message"] == "✅ 品质+50、火属性"
    assert r["buff_bonus"] == 50
    assert r["buff_element"] == "fire"
    assert r["snap"]["buff_element"] == "fire"


def test_tc16_buff_limit_once() -> None:
    """TC-16 反例（GU-28 限 1 次/调合）：快照 buff_used 标记已用 → 拒绝「限 1 次」，不重复扣。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"boost_stone": 2}, player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r1 = eng.buff(_player(5), snap, _items()["boost_stone"], ctx)
    snap1 = r1["snap"]
    r2 = eng.buff(_player(5), snap1, _items()["boost_stone"], ctx)
    assert r2["ok"] is False
    assert r2["reason"] == "buff_limit"
    assert r2["message"] == "限 1 次"
    assert inv.get("boost_stone", 0) == 1  # 第 2 次未消耗（第 1 次已扣 1）


def test_tc16_buff_tier_too_low() -> None:
    """TC-16 反例（GU-28）：大师（档位 4）→ 宗师门槛拒绝「等级不足」。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"boost_stone": 1}, player=_player(4))
    snap = _deep_snap(eng, tier=4)
    r = eng.buff(_player(4), snap, _items()["boost_stone"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "tier_too_low"
    assert r["message"] == "等级不足"
    assert inv.get("boost_stone", 0) == 1


def test_tc16_buff_not_boost_item() -> None:
    """TC-16 反例：非加成道具 → 拒绝（GU-28 加成道具门槛）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"herb": 1}, player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.buff(_player(5), snap, _items()["herb"], ctx)
    assert r["ok"] is False
    assert r["reason"] == "not_boost_item"


def test_tc16_buff_default_bonus() -> None:
    """TC-16 正例（D-4）：加成道具未配幅度 → 回落 settings.alchemy.boost_quality（默认 30）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx({"boost_plain": 1}, player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.buff(_player(5), snap, _items()["boost_plain"], ctx)
    assert r["ok"] is True
    assert r["buff_bonus"] == 30


# ---------------------------------------------------------------------------
# TC-23 /挑战（GU-47~49/F-16/ATO-06；连锁≥5 且刻度≥2 达标→品质上限+10；未达标→降级+退50%材料）
# ---------------------------------------------------------------------------


def test_tc23_challenge_check_met() -> None:
    """TC-23 正例：连锁 5 + 刻度 2（且）→ 达标 met=True（F-16 苛刻条件）。"""
    eng = DeepEngine(settings=_settings())
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_check(_player(5), snap, chain_segments=5, element_hits=2)
    assert r["ok"] is True
    assert r["met"] is True
    assert r["need_chain"] == 5
    assert r["need_element"] == 2
    assert r["operator"] == "and"


def test_tc23_challenge_check_chain_short() -> None:
    """TC-23 反例：连锁 4/5 → 未达标 met=False（M-16「连锁 4/5」）。"""
    eng = DeepEngine(settings=_settings())
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_check(_player(5), snap, chain_segments=4, element_hits=2)
    assert r["ok"] is True
    assert r["met"] is False
    assert r["chain_ok"] is False
    assert r["element_ok"] is True


def test_tc23_challenge_check_element_short() -> None:
    """TC-23 反例：连锁 5 但刻度 1/2 → 未达标（「且」语义，双条件全达标才可）。"""
    eng = DeepEngine(settings=_settings())
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_check(_player(5), snap, chain_segments=5, element_hits=1)
    assert r["ok"] is True
    assert r["met"] is False
    assert r["chain_ok"] is True
    assert r["element_ok"] is False


def test_tc23_challenge_check_operator_or() -> None:
    """TC-23 正例：苛刻条件可配「或」→ 连锁 5 且刻度 1 → 达标（F-16 可配且/或）。"""
    eng = DeepEngine(settings=_settings(challenge={
        "chain_segments": 5, "element_hits": 2, "operator": "or",
        "quality_cap_bonus": 10, "degrade_levels": 1,
    }))
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_check(_player(5), snap, chain_segments=5, element_hits=1)
    assert r["ok"] is True
    assert r["met"] is True
    assert r["operator"] == "or"


def test_tc23_challenge_check_tier_too_low() -> None:
    """TC-23 反例（GU-47）：大师（档位 4）→ 宗师门槛拒绝。"""
    eng = DeepEngine(settings=_settings())
    snap = _deep_snap(eng, tier=4)
    r = eng.challenge_check(_player(4), snap, chain_segments=5, element_hits=2)
    assert r["ok"] is False
    assert r["reason"] == "tier_too_low"


def test_tc23_challenge_settle_met_cap10() -> None:
    """TC-23 正例：达标 → 品质上限+10（F-16；M5 拍板渲染无 emoji，
    纯文本「挑战成功！品质上限 +10」）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_settle(
        _player(5), ctx, snap, met=True, material_paid=[{"item": "mat_fire", "count": 4}]
    )
    assert r["ok"] is True
    assert r["message"] == "挑战成功！品质上限 +10"
    assert r["quality_cap_bonus"] == 10
    assert r["cap_bonus"] == 10
    s2 = r["snap"]
    assert s2["quality_cap_bonus"] == 10
    assert s2["challenge_cap"] == 10   # QLT-08③：SettleEngine._extra_cap 消费
    assert s2["challenge_settled"] is True
    assert len(added) == 0             # 达标不退料


def test_tc23_challenge_settle_fail_degrade_refund() -> None:
    """TC-23 正例（失败路径）：未达标 → 品质降级（80→79 rare）+ 退 50% 材料（4→2 向下取整）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5, quality_score=80)
    r = eng.challenge_settle(
        _player(5), ctx, snap, met=False, material_paid=[{"item": "mat_fire", "count": 4}]
    )
    assert r["ok"] is True
    assert r["reason"] == "challenge_failed"
    assert r["message"] == "❌ 挑战失败：条件未达标，品质降级，退还 50% 材料"
    # 退 50% 材料：⌊4×0.5⌋=2（F-16 按配方各退 50% 向下取整）
    assert r["refund"] == [{"item": "mat_fire", "count": 2}]
    assert added == [{"item_id": "mat_fire", "count": 2, "bound": True}]
    # 品质降级：degrade_quality(80,1) → rare 79（QLT-10 裁剪到降档区间）
    assert r["degraded"] == {"from": 80, "to": 79, "tier": "rare", "levels": 1}
    s2 = r["snap"]
    assert s2["quality_score"] == 79
    assert s2["challenge_refunded"] is True   # ATO-06 只退一次标记
    assert s2["challenge_settled"] is True


def test_tc23_challenge_settle_refund_once() -> None:
    """TC-23 反例（ATO-06 只退一次）：重复结算 → 已结算直返，不重复退料/降级。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5, quality_score=80)
    r1 = eng.challenge_settle(
        _player(5), ctx, snap, met=False, material_paid=[{"item": "mat_fire", "count": 4}]
    )
    assert len(added) == 1
    # 第二次以已结算快照重入（重复 /确认 / 重投递，终态入 version，ATO-06/04）
    r2 = eng.challenge_settle(
        _player(5), ctx, r1["snap"], met=False, material_paid=[{"item": "mat_fire", "count": 4}]
    )
    assert r2["ok"] is True
    assert r2["idempotent"] is True
    assert r2["message"] == "挑战已结算"
    assert len(added) == 1             # 不重复退料


def test_tc23_challenge_settle_met_no_double_cap() -> None:
    """TC-23 反例（幂等防御）：达标重复结算 → 不重复叠加品质上限。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r1 = eng.challenge_settle(_player(5), ctx, snap, met=True, material_paid=[])
    r2 = eng.challenge_settle(_player(5), ctx, r1["snap"], met=True, material_paid=[])
    assert r2["ok"] is True
    assert r2["idempotent"] is True
    assert r2["snap"]["quality_cap_bonus"] == 10  # 不叠加到 20


def test_tc23_challenge_settle_material_paid_dict_form() -> None:
    """TC-23 正例：material_paid 支持 dict 形态 {item: count}（GU-49 材料×2 归一）。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_settle(_player(5), ctx, snap, met=False, material_paid={"mat_fire": 4})
    assert r["ok"] is True
    assert r["refund"] == [{"item": "mat_fire", "count": 2}]


def test_tc23_challenge_settle_no_quality_score_marker() -> None:
    """TC-23 正例（D-6）：快照无暂存品质分 → 写 challenge_degraded=True 标记供批6A 结算消费。"""
    eng = DeepEngine(settings=_settings())
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5)  # 无 quality_score
    r = eng.challenge_settle(_player(5), ctx, snap, met=False, material_paid={"mat_fire": 4})
    assert r["ok"] is True
    assert r["degraded"] is True
    assert r["snap"]["challenge_degraded"] is True
    assert r["refund"] == [{"item": "mat_fire", "count": 2}]


def test_tc23_challenge_settle_cap_configurable() -> None:
    """TC-23 正例（F-16 可配）：challenge.quality_cap_bonus 可配（如 +15）。"""
    eng = DeepEngine(settings=_settings(challenge={
        "chain_segments": 5, "element_hits": 2, "operator": "and",
        "quality_cap_bonus": 15, "degrade_levels": 1,
    }))
    ctx, added, inv, cur, unlocks = _ctx(player=_player(5))
    snap = _deep_snap(eng, tier=5)
    r = eng.challenge_settle(_player(5), ctx, snap, met=True, material_paid=[])
    assert r["ok"] is True
    assert r["message"] == "挑战成功！品质上限 +15"
    assert r["snap"]["challenge_cap"] == 15
