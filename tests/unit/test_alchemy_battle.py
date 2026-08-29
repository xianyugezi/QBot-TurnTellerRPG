"""战斗即时调合引擎单测（M8 批9·路A · qbot_rpg/core/alchemy_battle.py）。

文件：tests/unit/test_alchemy_battle.py
创建：2026-08-29
作者：Hermes 子agent（批9 路A）
功能：BattleAlchemyEngine 引擎单测——守卫（战斗中/大师/能量/限次）/携带素材全拒差异/
      一步出结果（auto_use=true 当场结算 use_fn 被调 / false 入包）/同场第 2 次拒绝/
      新场次清零/冷却强度公式/原子扣减（材料+宝石+回滚）。ctx 直测（items/recipe 注册表 +
      count_item/remove_item/add_item hook + currencies + player + battle_snapshot dict），
      零 IO 零 NoneBot。

依据：docs/m8_contract_战斗资源.md §三（BA-01~11；BA-02 落点顶层键/BA-06 冷却+携带素材+
      能量/BA-07 auto_use 可配/BA-08 一步出结果原子扣减/BA-10 强度公式）+ docs/m8_contract_
      指令契约.md §16（GU-50~54/F-17/M-17 限次拒绝模板）+ §九（ATO-01 全量原子校验）。
规则出处以引擎模块注释为准（BA/GU/F/ATO 编号 + 定稿/契约行号）。

覆盖矩阵（每条正例 + 反例，断言精确字段）：
  TC-24  战斗中+大师+素材+能量 → 一步出结果：auto_use=true 当场结算（use_fn 被调、outcome
         携带、battle_alchemy_used 自增、材料原子扣减、落点回写 battle_snapshot 顶层键）；
         auto_use=false 入包（use_fn 不被调、produced 入包记录、计数仍自增）
  TC-25  同场第 2 次拒绝（per_battle_limit=1：instant_eligible 与 resolve 双拦截、材料零变更）；
         新场次清零（新 battle_snapshot dict → read_used=0 → 可再调合）
  反例   非战斗拒绝（not_in_battle）；非大师拒绝（tier_too_low）；素材不足全拒+差异短清单、
         背包零变更、无产出；能量不足（energy_enabled=true 时 energy）；上下文/配方非法
  强度   冷却强度公式（cooldown_of 默认 3/配方覆盖/输出覆盖；intensity=技能×(1+0.4×冷却数)
         可配系数）
  原子   材料+宝石扣减；宝石不足全拒差异；remove_item 失败回滚零变更；auto_use=true 未注入
         use_fn → 入包不丢产出（E-A7）
  落点   read_used/write_used 顶层键读写（BA-02）；resolve 经 ctx["battle_snapshot"] 自回写、
         battle_alchemy_used=None 时回落快照读取（E-A1）
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

import pytest

from qbot_rpg.core.alchemy_battle import (
    BATTLE_ALCHEMY_USED_KEY,
    BattleAlchemyEngine,
)

# ---------------------------------------------------------------------------
# 测试数据（items/recipe 注册表，对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------


def _items() -> Dict[str, dict]:
    """测试物品注册表（战斗即时调合产出/素材）。"""
    return {
        "ember_crystal": {"id": "ember_crystal", "name": "火晶石", "type": "material",
                          "price": 40},
        "moon_grass": {"id": "moon_grass", "name": "月光草", "type": "material",
                       "price": 40},
        "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable",
                       "quality": "common", "traits": ["trait_burn_boost"],
                       "base_effects": {"damage": 50}, "effects": ["burn_dot"]},
    }


def _recipes() -> Dict[str, dict]:
    """测试配方注册表（材料 + 产出 + 冷却 + 技能基准 + 可选宝石成本）。"""
    return {
        "r_flame_bomb": {
            "id": "r_flame_bomb", "name": "火焰弹配方", "kind": "craft", "level": 5,
            "master_only": False,
            "materials": [{"id": "ember_crystal", "count": 1},
                          {"id": "moon_grass", "count": 2}],
            "output": {"item": "flame_bomb", "count": 1},
            "cost": {"coins": 0, "gem": 0},
            "cooldown": 3,  # BA-06 炸弹 3 回合冷却
            "skill": 50,    # BA-10 强度公式「技能」基准
        },
        "r_gem": {
            "id": "r_gem", "name": "宝石即时调合", "kind": "craft", "level": 5,
            "master_only": False,
            "materials": [{"id": "ember_crystal", "count": 1},
                          {"id": "moon_grass", "count": 2}],
            "output": {"item": "flame_bomb", "count": 1},
            "cost": {"coins": 0, "gem": 5},  # BA-08/E-A4 宝石原子扣减
            "cooldown": 2,
        },
    }


def _settings(*, energy_enabled: bool = False, auto_use: Optional[bool] = None,
              per_battle_limit: Optional[int] = None,
              intensity_coef: Optional[float] = None,
              master_tier: Optional[str] = None) -> Dict[str, Any]:
    """settings dict（alchemy 段：能量开关/战斗即时调合/战斗道具强度公式）。"""
    ba: Dict[str, Any] = {
        "auto_use": True if auto_use is None else auto_use,
        "per_battle_limit": 1 if per_battle_limit is None else per_battle_limit,
    }
    if master_tier is not None:
        ba["master_tier"] = master_tier
    alch: Dict[str, Any] = {"energy_enabled": energy_enabled, "战斗即时调合": ba}
    if intensity_coef is not None:
        alch["战斗道具"] = {"强度公式": intensity_coef}
    return {"alchemy": alch}


def _player(level: int = 4, *, energy_current: Optional[int] = None) -> Dict[str, Any]:
    """玩家状态 dict（proficiency.alchemy.level；level=4=大师档位索引，GU-51/E-A9）。

    能量：energy_current 提供时挂 persistent_state（last_regen_ts=0 → 懒补格到上限；
    能量不足用例用 last_regen_ts 超前 → 时钟回拨不补格）。
    """
    p: Dict[str, Any] = {"proficiency": {"alchemy": {"level": level, "exp": 0}}}
    if energy_current is not None:
        p["persistent_state"] = {"energy_current": energy_current,
                                 "energy_last_regen_ts": 0}
    return p


def _player_energy_empty() -> Dict[str, Any]:
    """能量 0 格玩家（last_regen_ts 超前 → 时钟回拨不补格，保持 0 格）。"""
    return {"proficiency": {"alchemy": {"level": 4, "exp": 0}},
            "persistent_state": {"energy_current": 0, "energy_last_regen_ts": 10 ** 12}}


# ---------------------------------------------------------------------------
# ctx 直测夹具：inventory + count_item/remove_item/add_item hook + currencies/player/
# battle_snapshot
# ---------------------------------------------------------------------------


def _make_remove(inv: Dict[str, int]) -> Callable[..., dict]:
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


def _make_add(produced_list: List[dict]) -> Callable[..., dict]:
    """add_item hook：记录入包条目（quality/traits 透传）并追加到 produced_list。"""
    def add(item_id: str, count: int, bound: bool, *, quality: Optional[str] = None,
            traits: tuple = ()) -> dict:
        produced_list.append({
            "item_id": item_id, "count": count, "bound": bound,
            "quality": quality, "traits": tuple(traits),
        })
        return {"ok": True, "added": count}
    return add


def _ctx(inventory: Optional[Dict[str, int]] = None, *,
         player: Optional[dict] = None,
         currencies: Optional[Dict[str, int]] = None,
         battle_snapshot: Optional[dict] = None) -> tuple:
    """构造即时调合 ctx；返回 (ctx, produced_list)（produced_list 记录 add_item 入包）。

    注意：inventory 直接复用调用方 dict（不复制）——hook 就地改写调用方可见，便于断言
    原子扣减/回滚（对齐 test_alchemy_settle._ctx 语义）。
    """
    inv: Dict[str, int] = inventory if inventory is not None else {}
    produced_list: List[dict] = []
    ctx: Dict[str, Any] = {
        "items": _items(),
        "recipe": _recipes(),
        "inventory": inv,
        "currencies": currencies if currencies is not None else {"coins": 100, "gem": 10},
        "count_item": lambda iid: int(inv.get(iid, 0)),
        "remove_item": _make_remove(inv),
        "add_item": _make_add(produced_list),
    }
    if player is not None:
        ctx["player"] = player
    if battle_snapshot is not None:
        ctx["battle_snapshot"] = battle_snapshot
    return ctx, produced_list


def _make_use_fn(calls: List[tuple]) -> Callable[..., dict]:
    """use_fn 回调（BA-07 道具行动入口鸭子；记录调用并返回 outcome）。"""
    def use_fn(item_id: str, count: int, produced: dict) -> dict:
        calls.append((item_id, count, produced))
        return {"ok": True, "message": "造成 110 伤害", "damage": 110}
    return use_fn


# ---------------------------------------------------------------------------
# TC-24：战斗中+大师+素材+能量 → 一步出结果（auto_use=true 当场结算 / false 入包）
# ---------------------------------------------------------------------------


def test_tc24_auto_use_true_resolve_one_step() -> None:
    """TC-24：auto_use=true（默认）→ use_fn 被调当场结算 + 原子扣减 + 计数自增 + 落点回写。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    inv = {"ember_crystal": 3, "moon_grass": 5}
    cur = {"coins": 100, "gem": 10}
    snap = {"turn": 1, "ai_state": {}}
    ctx, produced = _ctx(inv, player=player, currencies=cur, battle_snapshot=snap)
    calls: List[tuple] = []
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0,
                    use_fn=_make_use_fn(calls))

    assert r["ok"] is True
    assert r["auto_use"] is True and r["auto_used"] is True
    assert r["message"] == "火焰弹 ×1 已即时调合并自动使用"
    assert len(calls) == 1 and calls[0][0] == "flame_bomb" and calls[0][1] == 1
    assert r["outcome"] == {"ok": True, "message": "造成 110 伤害", "damage": 110}
    # 产出实例（BA-08 ItemInstance 形态：quality/traits 取物品 def，E-A3）
    assert r["produced"]["item_id"] == "flame_bomb"
    assert r["produced"]["name"] == "火焰弹"
    assert r["produced"]["count"] == 1
    assert r["produced"]["quality"] == "common" and r["produced"]["tier"] == "common"
    assert r["produced"]["traits"] == ["trait_burn_boost"]
    assert r["produced"]["effects"] == {"damage": 50}
    # 计数自增（GU-54）+ 落点回写（E-A1：ctx["battle_snapshot"] 顶层键）
    assert r["battle_alchemy_used"] == 1
    assert snap[BATTLE_ALCHEMY_USED_KEY] == 1
    # 原子扣减（BA-08）：材料已扣、宝石未动（cost.gem=0）
    assert inv == {"ember_crystal": 2, "moon_grass": 3}
    assert cur["gem"] == 10
    # auto_use=true 当场使用 → 不入包（produced 仅记录 use_fn 传入，无 add_item）
    assert produced == []


def test_tc24_auto_use_false_into_pack() -> None:
    """TC-24 反分支：auto_use=false → use_fn 不被调、产出入包、计数仍自增。"""
    eng = BattleAlchemyEngine(settings=_settings(auto_use=False))
    player = _player(level=4)
    inv = {"ember_crystal": 1, "moon_grass": 2}
    ctx, produced = _ctx(inv, player=player)
    calls: List[tuple] = []
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0,
                    use_fn=_make_use_fn(calls))

    assert r["ok"] is True
    assert r["auto_use"] is False and r["auto_used"] is False
    assert r["message"] == "火焰弹 ×1 已即时调合入包（auto_use 关闭或未自动使用）"
    assert len(calls) == 0  # use_fn 不被调（BA-07）
    assert produced == [{"item_id": "flame_bomb", "count": 1, "bound": True,
                         "quality": "common", "traits": ("trait_burn_boost",)}]
    assert r["battle_alchemy_used"] == 1  # 本场计数仍自增（限次衔接）
    assert r["outcome"] is None


def test_tc24_guard_eligible_full_pass() -> None:
    """TC-24 前置：战斗中+大师+能量（关）→ instant_eligible 全过。"""
    eng = BattleAlchemyEngine(settings=_settings())
    g = eng.instant_eligible(_player(level=4), "alchemy", in_battle=True,
                             battle_alchemy_used=0)
    assert g["ok"] is True
    assert g["battle_alchemy_used"] == 0 and g["per_battle_limit"] == 1


# ---------------------------------------------------------------------------
# TC-25：同场第 2 次拒绝（per_battle_limit=1）/ 新场次清零
# ---------------------------------------------------------------------------


def test_tc25_second_use_rejected() -> None:
    """TC-25：同场第 2 次（battle_alchemy_used=1 ≥ limit=1）→ 双入口拒绝 + 材料零变更。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    inv = {"ember_crystal": 3, "moon_grass": 5}
    ctx, produced = _ctx(inv, player=player)
    recipe = _recipes()["r_flame_bomb"]

    # instant_eligible（GU-54）与 resolve（ATO-01 幂等衔接）双拦截
    g = eng.instant_eligible(player, "alchemy", in_battle=True, battle_alchemy_used=1)
    assert g["ok"] is False and g["reason"] == "already_used"
    assert g["message"] == "本场战斗已使用过即时调合（限 1 次/场）"
    r = eng.resolve(ctx, recipe, battle_alchemy_used=1, use_fn=_make_use_fn([]))
    assert r["ok"] is False and r["reason"] == "already_used"
    # 拒绝 → 材料零变更、无产出（原子）
    assert inv == {"ember_crystal": 3, "moon_grass": 5}
    assert produced == []


def test_tc25_new_battle_snapshot_cleared() -> None:
    """TC-25：新场次（新 battle_snapshot dict → read_used=0）→ 可再调合、计数从 0 起。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    # 旧场次已用 1 次（快照顶层键），新场次快照不含该键（战斗结束清零，BA-02）
    snap_old = {"turn": 1}
    eng.write_used(snap_old, 1)
    snap_new = {"turn": 9}
    assert eng.read_used(snap_new) == 0  # 新场次清零
    ctx, _ = _ctx({"ember_crystal": 3, "moon_grass": 5}, player=player,
                  battle_snapshot=snap_new)
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0)
    assert r["ok"] is True and r["battle_alchemy_used"] == 1
    assert snap_new[BATTLE_ALCHEMY_USED_KEY] == 1
    assert snap_old[BATTLE_ALCHEMY_USED_KEY] == 1  # 旧场次不清（各场独立）


def test_tc25_per_battle_limit_configurable() -> None:
    """TC-25 可配：per_battle_limit=2 → 第 3 次才拒绝。"""
    eng = BattleAlchemyEngine(settings=_settings(per_battle_limit=2))
    player = _player(level=4)
    ctx, _ = _ctx({"ember_crystal": 3, "moon_grass": 5}, player=player)
    recipe = _recipes()["r_flame_bomb"]
    r1 = eng.resolve(ctx, recipe, battle_alchemy_used=0)
    r2 = eng.resolve(ctx, recipe, battle_alchemy_used=1)
    r3 = eng.resolve(ctx, recipe, battle_alchemy_used=2)
    assert r1["ok"] is True and r2["ok"] is True
    assert r3["ok"] is False and r3["reason"] == "already_used"
    g = eng.instant_eligible(player, "alchemy", in_battle=True, battle_alchemy_used=1)
    assert g["ok"] is True and g["per_battle_limit"] == 2


# ---------------------------------------------------------------------------
# 守卫反例（GU-50/51/52）
# ---------------------------------------------------------------------------


def test_guard_not_in_battle() -> None:
    """GU-50：非战斗拒绝（not_in_battle）。"""
    eng = BattleAlchemyEngine(settings=_settings())
    g = eng.instant_eligible(_player(level=4), "alchemy", in_battle=False,
                             battle_alchemy_used=0)
    assert g["ok"] is False and g["reason"] == "not_in_battle"


def test_guard_tier_too_low() -> None:
    """GU-51：非大师拒绝（tier_too_low）；大师通过。"""
    eng = BattleAlchemyEngine(settings=_settings())
    g = eng.instant_eligible(_player(level=3), "alchemy", in_battle=True,
                             battle_alchemy_used=0)
    assert g["ok"] is False and g["reason"] == "tier_too_low"
    g2 = eng.instant_eligible(_player(level=4), "alchemy", in_battle=True,
                              battle_alchemy_used=0)
    assert g2["ok"] is True


def test_guard_energy_insufficient_when_enabled() -> None:
    """GU-52：energy_enabled=true 且能量 0 格 → 拒绝（energy）；材料零变更。"""
    eng = BattleAlchemyEngine(settings=_settings(energy_enabled=True))
    player = _player_energy_empty()
    inv = {"ember_crystal": 1, "moon_grass": 2}
    ctx, produced = _ctx(inv, player=player)
    g = eng.instant_eligible(player, "alchemy", in_battle=True, battle_alchemy_used=0)
    assert g["ok"] is False and g["reason"] == "energy"
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0)
    assert r["ok"] is False and r["reason"] == "energy"
    assert inv == {"ember_crystal": 1, "moon_grass": 2}
    assert produced == []


def test_energy_consumed_when_enabled() -> None:
    """GU-52 正例：enabled 时 resolve 扣 1 格能量（懒补格到上限 15 - 1 = 14）。"""
    eng = BattleAlchemyEngine(settings=_settings(energy_enabled=True))
    player = _player(level=4, energy_current=3)
    ctx, _ = _ctx({"ember_crystal": 1, "moon_grass": 2}, player=player)
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0)
    assert r["ok"] is True
    assert player["persistent_state"]["energy_current"] == 14  # 15(大师上限) - 1


def test_energy_disabled_bypass() -> None:
    """R-08/GU-52：能量默认关 → consume_energy 直通（bypassed），不写不扣。"""
    eng = BattleAlchemyEngine(settings=_settings(energy_enabled=False))
    player = _player(level=4, energy_current=3)
    en = eng.consume_energy(player, {})
    assert en["ok"] is True and en["bypassed"] is True
    assert player["persistent_state"]["energy_current"] == 3  # 直通不扣
    assert eng.energy_enabled() is False


# ---------------------------------------------------------------------------
# 携带素材（GU-53）与原子校验（ATO-01）
# ---------------------------------------------------------------------------


def test_carry_ok_success() -> None:
    """GU-53 正例：素材充足 → {ok:True, materials:[{item_id,count}]}。"""
    eng = BattleAlchemyEngine(settings=_settings())
    ctx, _ = _ctx({"ember_crystal": 3, "moon_grass": 5})
    ck = eng.carry_ok(ctx, _recipes()["r_flame_bomb"])
    assert ck["ok"] is True
    assert ck["materials"] == [{"item_id": "ember_crystal", "count": 1},
                               {"item_id": "moon_grass", "count": 2}]


def test_materials_insufficient_all_or_nothing() -> None:
    """GU-53/ATO-01：素材不足 → 全拒+差异清单、背包零变更、无产出。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    inv = {"ember_crystal": 0, "moon_grass": 1}
    ctx, produced = _ctx(inv, player=player)
    recipe = _recipes()["r_flame_bomb"]
    ck = eng.carry_ok(ctx, recipe)
    assert ck["ok"] is False and ck["reason"] == "materials_insufficient"
    shortfall = {s["item_id"]: s for s in ck["shortfall"]}
    assert shortfall["ember_crystal"]["diff"] == 1
    assert shortfall["ember_crystal"]["name"] == "火晶石"
    assert shortfall["ember_crystal"]["have"] == 0
    assert shortfall["moon_grass"]["diff"] == 1
    # resolve 同拒（全量原子校验，ATO-01）
    r = eng.resolve(ctx, recipe, battle_alchemy_used=0)
    assert r["ok"] is False and r["reason"] == "materials_insufficient"
    assert {s["item_id"]: s["diff"] for s in r["shortfall"]} == {
        "ember_crystal": 1, "moon_grass": 1}
    assert inv == {"ember_crystal": 0, "moon_grass": 1}
    assert produced == []


# ---------------------------------------------------------------------------
# 宝石原子扣减（BA-08/E-A4）
# ---------------------------------------------------------------------------


def test_gem_cost_deducted_atomically() -> None:
    """BA-08/E-A4：cost.gem=5 → 材料+宝石同步原子扣减。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    inv = {"ember_crystal": 1, "moon_grass": 2}
    cur = {"coins": 100, "gem": 7}
    ctx, produced = _ctx(inv, player=player, currencies=cur)
    calls: List[tuple] = []
    r = eng.resolve(ctx, _recipes()["r_gem"], battle_alchemy_used=0,
                    use_fn=_make_use_fn(calls))
    assert r["ok"] is True
    assert cur["gem"] == 2  # 7 - 5
    assert inv == {}  # 1-1 与 2-2 归零后 pop
    assert len(calls) == 1  # auto_use=true 当场使用
    assert produced == []  # 当场使用 → 不入包


def test_gem_insufficient_all_or_nothing() -> None:
    """ATO-01/E-A4：宝石不足 → 全拒+差异、材料与宝石零变更。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    inv = {"ember_crystal": 1, "moon_grass": 2}
    cur = {"coins": 100, "gem": 3}  # 需 5
    ctx, produced = _ctx(inv, player=player, currencies=cur)
    r = eng.resolve(ctx, _recipes()["r_gem"], battle_alchemy_used=0)
    assert r["ok"] is False and r["reason"] == "materials_insufficient"
    shortfall = {s["item_id"]: s for s in r["shortfall"]}
    assert "gem" in shortfall and shortfall["gem"]["diff"] == 2
    assert inv == {"ember_crystal": 1, "moon_grass": 2}
    assert cur["gem"] == 3
    assert produced == []


def test_atomic_rollback_on_remove_failure() -> None:
    """E-A8/ATO-01：材料扣减中途失败 → 回滚零变更（含能量回滚）。"""
    eng = BattleAlchemyEngine(settings=_settings(energy_enabled=True))
    player = _player(level=4, energy_current=3)
    inv = {"ember_crystal": 1, "moon_grass": 2}
    ctx, produced = _ctx(inv, player=player)
    orig_remove = ctx["remove_item"]

    def flaky_remove(item_id: str, count: int) -> dict:
        if item_id == "moon_grass":
            return {"ok": False, "reason": "not_enough"}
        return orig_remove(item_id, count)

    ctx["remove_item"] = flaky_remove
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0)
    assert r["ok"] is False and r["reason"] == "materials_remove_failed"
    # 回滚后 ctx["inventory"] 恢复快照（_restore 重挂快照副本，E-A8）；已扣材料/能量均还原
    assert ctx["inventory"] == {"ember_crystal": 1, "moon_grass": 2}
    assert player["persistent_state"]["energy_current"] == 3
    assert produced == []


def test_auto_use_true_without_use_fn_keeps_item() -> None:
    """E-A7：auto_use=true 但未注入 use_fn → 入包不丢产出。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    ctx, produced = _ctx({"ember_crystal": 1, "moon_grass": 2}, player=player)
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=0,
                    use_fn=None)
    assert r["ok"] is True and r["auto_use"] is True and r["auto_used"] is False
    assert r["outcome"] is None
    assert produced and produced[0]["item_id"] == "flame_bomb"  # 入包
    assert r["message"] == "火焰弹 ×1 已即时调合入包（auto_use 关闭或未自动使用）"


# ---------------------------------------------------------------------------
# 冷却 / 强度公式（BA-06 / BA-10）
# ---------------------------------------------------------------------------


def test_cooldown_of_formula() -> None:
    """BA-06：cooldown_of 默认 3（炸弹）/ 配方 cooldown / 配方 output.cooldown。"""
    eng = BattleAlchemyEngine(settings=_settings())
    rec = _recipes()["r_flame_bomb"]
    assert eng.cooldown_of(rec) == 3  # 配方 cooldown=3
    # 无 cooldown 字段 → 默认 3
    rec_no_cd = {k: v for k, v in rec.items() if k != "cooldown"}
    assert eng.cooldown_of(rec_no_cd) == 3
    # 配方无 → output.cooldown 兜底
    rec_out = dict(rec_no_cd)
    rec_out["output"] = {"item": "flame_bomb", "count": 1, "cooldown": 5}
    assert eng.cooldown_of(rec_out) == 5
    # 非法 → 默认 3
    assert eng.cooldown_of({"cooldown": "abc"}) == 3


def test_intensity_formula() -> None:
    """BA-10：强度 = 技能 × (1 + 0.4 × 冷却数)，系数可配。"""
    eng = BattleAlchemyEngine(settings=_settings(intensity_coef=0.4))
    rec = _recipes()["r_flame_bomb"]  # skill=50, cooldown=3
    assert eng.intensity(rec, cooldown=3) == pytest.approx(50 * (1 + 0.4 * 3))  # 110.0
    assert eng.intensity(rec, cooldown=2) == pytest.approx(50 * (1 + 0.4 * 2))  # 90.0
    # 技能缺省 1.0
    rec_no_skill = {k: v for k, v in rec.items() if k not in ("skill", "power")}
    assert eng.intensity(rec_no_skill, cooldown=3) == pytest.approx(1 * (1 + 0.4 * 3))
    # 系数可配（settings 战斗道具.强度公式）
    eng2 = BattleAlchemyEngine(settings=_settings(intensity_coef=0.5))
    assert eng2.intensity(rec, cooldown=3) == pytest.approx(50 * (1 + 0.5 * 3))  # 125.0
    # resolve 透传冷却与强度
    ctx, _ = _ctx({"ember_crystal": 1, "moon_grass": 2}, player=_player(level=4))
    r = eng.resolve(ctx, rec, battle_alchemy_used=0)
    assert r["cooldown"] == 3 and r["intensity"] == pytest.approx(110.0)


# ---------------------------------------------------------------------------
# 落点 helper（BA-02/BA-03/E-A1）与防御
# ---------------------------------------------------------------------------


def test_read_write_used_helpers() -> None:
    """BA-02：read_used/write_used 读写战斗快照顶层键；缺失/非法 → 0。"""
    eng = BattleAlchemyEngine(settings=_settings())
    snap = {"turn": 1, "ai_state": {}}
    assert eng.read_used(snap) == 0
    eng.write_used(snap, 1)
    assert snap[BATTLE_ALCHEMY_USED_KEY] == 1
    assert eng.read_used(snap) == 1
    assert eng.read_used({}) == 0
    assert eng.read_used(None) == 0
    # 非可变 dict（MappingProxy/冻结）→ 忽略写入不抛
    import types
    frozen = types.MappingProxyType({"turn": 1})
    eng.write_used(frozen, 1)
    assert eng.read_used(frozen) == 0


def test_resolve_used_fallback_from_snapshot() -> None:
    """E-A1：battle_alchemy_used=None → 回落 ctx["battle_snapshot"] 读取。"""
    eng = BattleAlchemyEngine(settings=_settings())
    player = _player(level=4)
    ctx, produced = _ctx({"ember_crystal": 1, "moon_grass": 2}, player=player,
                         battle_snapshot={BATTLE_ALCHEMY_USED_KEY: 1, "turn": 3})
    r = eng.resolve(ctx, _recipes()["r_flame_bomb"], battle_alchemy_used=None)
    assert r["ok"] is False and r["reason"] == "already_used"  # 快照已用 1 次
    assert produced == []


def test_invalid_ctx_and_recipe_defensive() -> None:
    """防御：上下文/配方非法 → 拒绝 dict（不抛异常）。"""
    eng = BattleAlchemyEngine(settings=_settings())
    recipe = _recipes()["r_flame_bomb"]
    assert eng.resolve(None, recipe, battle_alchemy_used=0)["reason"] == "invalid_ctx"
    ctx, _ = _ctx({"ember_crystal": 1, "moon_grass": 2}, player=_player(level=4))
    assert eng.resolve(ctx, None, battle_alchemy_used=0)["reason"] == "recipe_invalid"
    assert eng.carry_ok(ctx, None)["reason"] == "recipe_invalid"
    assert eng.carry_ok(None, recipe)["reason"] == "invalid_ctx"
