"""批47 · 符文 43-B 单测：1 阶数值落键空间 + 跨装备类型差异生效 + 互斥 + 副手失活 + 回归。

依据：`/root/deliverables/符文系统_实现口径.md` §〇 结论 6/8 + §三 3.1/3.2 + §五 43-B；
原案 `打造系统_原案_20260919.md` §9；`docs/深度打造_决策记录.md` H1/H2。

覆盖：
  A. 求值层（core/runes.py）：default+覆盖差异解析、键白名单、数值清洗、多符文合并；
  B. 落面板/战斗：aggregate_bonus 符文段 → attributes.bonus flat/pct → 战斗桥 combatant；
     装 → 数值变、卸 → 复原、总闸关 → 零贡献；
  C. 跨装备类型：同符文在 weapon / armor_body 数值不同；未声明类型回落 default；
  D. 互斥：同孔位珠/符文双向拦截（一槽一物，共用孔位数组）；
  E. 副手失活：副手折算件符文不生效（经 jewel.active_rune_sockets 继承）；主手不受影响；
  F. 回归对拍：无符文 / 无该新路径时聚合与既有实现逐字段一致。

纪律：测试只构造内存数据（不写任何真实内容包）；不写死内容包业务名。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.jewel import JewelSystem
from qbot_rpg.core.player_attributes import PlayerAttributes, calc_all_final_attributes
from qbot_rpg.core.pvp import _combatant_of
from qbot_rpg.core.runes import rune_stats_of, sum_rune_stats
from qbot_rpg.data.gear_stats import GEAR_NUMERIC_KEYS
from qbot_rpg.data.item import ItemInstance

SLOTS: Dict[str, Any] = {
    "weapon": {"name": "武器", "max": 1},
    "armor_body": {"name": "躯干", "max": 1},
    "offhand": {"name": "副手", "max": 1, "role": "offhand"},
}
OFFHAND_ON: Dict[str, Any] = {"enabled": True, "single_hand_scale": 0.5}

# 同符文跨装备类型差异表：default 兜底 + weapon 覆盖（stats 整块覆盖）
RUNE_ATK: Dict[str, Any] = {
    "id": "r_atk", "name": "灼刃", "tier": 1, "family": "burn",
    "by_equip_type": {
        "default": {"stats": {"atk": 6, "hp_pct": 5}},
        "weapon": {"stats": {"atk": 9}},
    },
}
RUNES = {RUNE_ATK["id"]: RUNE_ATK}
ITEMS: Dict[str, Any] = {
    "sword": {"id": "sword", "type": "weapon"},
    "vest": {"id": "vest", "type": "armor_body"},
}


def _jewel(*, enabled: bool = True) -> JewelSystem:
    return JewelSystem(settings={"deep_craft": {"enabled": enabled}})


def _engine(*, runes: Any = RUNES, items: Any = ITEMS, jewel: Any = None,
            offhand: Any = None) -> EquipmentEngine:
    return EquipmentEngine(
        slots=SLOTS, offhand=offhand, runes=runes, items=items,
        jewel=jewel if jewel is not None else _jewel())


def _row(item_id: str, slot: str) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                        bound=False, stack_max=1, slot=slot)


def _player(item_id: str, slot: str, socket_row: Optional[list] = None,
            base: Optional[Dict[str, float]] = None) -> Tuple[Dict[str, Any], ItemInstance]:
    row = _row(item_id, slot)
    attrs = PlayerAttributes(base=dict(base or {"atk": 10, "hp": 100}))
    p: Dict[str, Any] = {
        "inventory": [row],
        "equipment": {slot: {"item_id": item_id, "uid": row.uid}},
        "attributes": attrs,
        "persistent_state": {"rune_sockets": {}},
        "level": 1,
    }
    if socket_row is not None:
        p["persistent_state"]["rune_sockets"][row.uid] = list(socket_row)
    return p, row


# ===========================================================================
# A. 求值层（core/runes.py）：差异解析唯一发生处 + 键白名单 + 数值清洗
# ===========================================================================
def test_rune_stats_of_default_plus_type_override() -> None:
    """R2：命中类型条目顶层浅覆盖 default（stats 整块替换）；未命中/None → default。"""
    assert rune_stats_of(RUNE_ATK, "weapon") == {"atk": 9.0}          # 覆盖整块（hp_pct 不带）
    assert rune_stats_of(RUNE_ATK, "armor_body") == {"atk": 6.0, "hp_pct": 5.0}
    assert rune_stats_of(RUNE_ATK, None) == {"atk": 6.0, "hp_pct": 5.0}
    assert rune_stats_of(RUNE_ATK, "") == {"atk": 6.0, "hp_pct": 5.0}


def test_rune_stats_of_drops_unknown_placeholder_and_non_numeric() -> None:
    """键白名单（唯一源 GEAR_NUMERIC_KEYS）+ 数值清洗：自造键/占位键/布尔/0 一律丢弃。"""
    rune = {"id": "r", "tier": 1, "by_equip_type": {"default": {"stats": {
        "atk": 6, "bogus": 99, "cooldown_reduction_pct": 5,
        "hp": 0, "mp": True, "dfn": "8", "foc": None,
    }}}}
    got = rune_stats_of(rune, "weapon")
    assert got == {"atk": 6.0, "dfn": 8.0}, got
    assert all(k in GEAR_NUMERIC_KEYS for k in got)


def test_sum_rune_stats_merges_and_skips_empty_slots() -> None:
    """多枚激活符文同键加算；空槽（None/空串）/查无定义 → 跳过（纯函数）。"""
    other = {"id": "r2", "tier": 1, "family": "f",
             "by_equip_type": {"default": {"stats": {"atk": 4, "hp": 10}}}}
    reg = {RUNE_ATK["id"]: RUNE_ATK, "r2": other}
    assert sum_rune_stats(["r_atk", None, "", "r2", "nope"], reg, "weapon") == {
        "atk": 13.0, "hp": 10.0}
    assert sum_rune_stats([], reg, "weapon") == {}
    assert sum_rune_stats(None, reg, "weapon") == {}
    assert sum_rune_stats(["r_atk"], None, "weapon") == {}
    # 非定义元素（runes 表给非 Mapping 值）→ 防御跳过
    assert sum_rune_stats(["r_atk"], {"r_atk": 5}, "weapon") == {}


# ===========================================================================
# B. 落面板 / 战斗（aggregate_bonus 符文段为唯一收口）
# ===========================================================================
def test_aggregate_bonus_applies_tier1_rune_numeric_before_after() -> None:
    """装 1 阶符文 → flat 数值真的变；卸下（清空行）→ 复原（前后数值对照）。"""
    eng = _engine()
    p, row = _player("sword", "weapon", socket_row=[None, None, None])
    before = eng.aggregate_bonus(p)
    assert before == {"flat": {}, "pct": {}}, before
    p["persistent_state"]["rune_sockets"][row.uid] = ["r_atk", None, None]
    after = eng.aggregate_bonus(p)
    assert after == {"flat": {"atk": 9.0}, "pct": {}}, after
    assert p["attributes"].bonus["flat"]["atk"] == 9.0
    # 卸下（孔位清空）→ 与装前逐字段一致
    p["persistent_state"]["rune_sockets"][row.uid] = [None, None, None]
    assert eng.aggregate_bonus(p) == before


def test_rune_pct_routes_into_pct_layer() -> None:
    """PCT 键（hp_pct）走 pct 拆层（与既有 route_bonus_into 同规则），不进 flat。"""
    eng = _engine()
    p, row = _player("vest", "armor_body", socket_row=["r_atk", None, None])
    snap = eng.aggregate_bonus(p)
    assert snap["flat"] == {"atk": 6.0}, snap
    assert snap["pct"] == {"hp": 5.0}, snap
    # hp 是 resource 型（ADR-02：resource_pct 缺省关，pct 不乘）→ 显式开才见 pct 效果
    final = calc_all_final_attributes(p["attributes"], resource_pct=True)
    assert final["hp"] == 105.0 and final["atk"] == 16.0, final


def test_pvp_combat_bridge_sees_rune_flat_bonus() -> None:
    """战斗数值真的变：符文 flat → attributes.bonus.flat → pvp combatant atk。"""
    eng = _engine()
    p, row = _player("sword", "weapon", socket_row=[None, None, None], base={"atk": 10})
    base_atk = _combatant_of(p)["atk"]
    p["persistent_state"]["rune_sockets"][row.uid] = ["r_atk", None, None]
    eng.aggregate_bonus(p)
    assert _combatant_of(p)["atk"] == base_atk + 9


def test_switch_closed_gives_zero_contribution() -> None:
    """总闸（settings.deep_craft.enabled）关闭 → 符文段零贡献（即便行仍存在）。"""
    eng = _engine(jewel=_jewel(enabled=False))
    p, row = _player("sword", "weapon", socket_row=["r_atk", None, None])
    assert eng.aggregate_bonus(p) == {"flat": {}, "pct": {}}


def test_missing_data_source_is_zero_contribution() -> None:
    """缺 runes/items/jewel / uid → 零贡献（防御降级，不抛）。"""
    p, row = _player("sword", "weapon", socket_row=["r_atk", None, None])
    assert _engine(runes=None).aggregate_bonus(p) == {"flat": {}, "pct": {}}
    no_jewel = EquipmentEngine(slots=SLOTS, runes=RUNES, items=ITEMS)
    assert no_jewel.aggregate_bonus(p) == {"flat": {}, "pct": {}}
    # 无 uid 的旧档穿戴行 → 找不到符文行 → 零贡献
    p2, _r2 = _player("sword", "weapon")
    p2["equipment"]["weapon"] = {"item_id": "sword", "uid": ""}
    assert _engine().aggregate_bonus(p2) == {"flat": {}, "pct": {}}


# ===========================================================================
# C. 跨装备类型差异（类型键 = items.type）
# ===========================================================================
def test_same_rune_differs_across_two_equip_types() -> None:
    """同符文装 weapon（覆盖）vs armor_body（default）→ 面板数值不同。"""
    eng = _engine()
    pw, _rw = _player("sword", "weapon", socket_row=["r_atk", None, None])
    pb, _rb = _player("vest", "armor_body", socket_row=["r_atk", None, None])
    sw, sb = eng.aggregate_bonus(pw), eng.aggregate_bonus(pb)
    assert sw["flat"] == {"atk": 9.0}
    assert sb["flat"] == {"atk": 6.0}
    assert sw["flat"]["atk"] != sb["flat"]["atk"]
    assert sb["pct"] == {"hp": 5.0} and sw["pct"] == {}


def test_undeclared_type_falls_back_to_default() -> None:
    """未声明该类型的覆盖 → 回落 default（贴证据：items.type 非覆盖键）。"""
    eng = _engine()
    p, _row = _player("vest", "armor_body", socket_row=["r_atk", None, None])
    assert eng._equip_type_of("vest") == "armor_body"          # 类型键来自 items.type
    assert eng.aggregate_bonus(p) == {"flat": {"atk": 6.0}, "pct": {"hp": 5.0}}
    # 未知 type（items 表未声明该 type 的覆盖）→ 同样回落 default
    eng2 = _engine(items={"vest": {"id": "vest", "type": "armor_leg"}})
    assert eng2.aggregate_bonus(p) == {"flat": {"atk": 6.0}, "pct": {"hp": 5.0}}


# ===========================================================================
# D. 互斥（与既有装饰珠共用孔位；一槽一物）
# ===========================================================================
JEWEL_ITEMS = {"gem_ruby": {"id": "gem_ruby", "name": "红宝石", "type": "装饰珠",
                            "quality": "common"}}
SOCKET_DEFS = {"sword": [{"slot_level": 3}, {"slot_level": 3}]}


def _mount_ctx() -> Tuple[Dict[str, Any], Dict[str, int], Dict[str, Any]]:
    inv = {"gem_ruby": 2, "r_atk": 2}
    p = {"equipment": {"weapon": {"item_id": "sword", "uid": "uA"}}}
    ctx: Dict[str, Any] = {
        "items": dict(JEWEL_ITEMS), "runes": dict(RUNES), "slot_defs": SOCKET_DEFS,
        "equipment": {"sword": {"jewels": {}}}, "rune_sockets": {}, "player": p,
        "inventory": inv,
        "count_item": lambda i: int(inv.get(str(i), 0)),
        "remove_item": lambda i, c=1: (
            inv.get(str(i), 0) >= int(c)
            and (inv.__setitem__(str(i), inv[str(i)] - int(c)) or True)),
        "add_item": lambda i, c=1, b=True: (
            inv.__setitem__(str(i), inv.get(str(i), 0) + int(c)) or True),
    }
    js = JewelSystem(settings={"deep_craft": {"enabled": True}})
    return ctx, inv, {"js": js}


def test_mutual_exclusion_rune_then_jewel_blocked() -> None:
    """先装符文 → 同孔位装珠被拦（对向互斥；reason=slot_full）。"""
    ctx, _inv, h = _mount_ctx()
    assert h["js"].mount_rune(ctx, "r_atk", "sword", "uA", 0)["ok"] is True
    res = h["js"].mount(ctx, "gem_ruby", "sword", 0, "p1")
    assert res["ok"] is False and res["reason"] == "slot_full"
    assert "符文" in res["message"]
    # 空孔位仍可正常装珠（未误伤）
    assert h["js"].mount(ctx, "gem_ruby", "sword", 1, "p1")["ok"] is True


def test_mutual_exclusion_jewel_then_rune_blocked() -> None:
    """先装珠 → 同孔位装符文被拦（既有批46 方向；回归）。"""
    ctx, _inv, h = _mount_ctx()
    assert h["js"].mount(ctx, "gem_ruby", "sword", 0, "p1")["ok"] is True
    res = h["js"].mount_rune(ctx, "r_atk", "sword", "uA", 0)
    assert res["ok"] is False and res["reason"] == "slot_full"


def test_jewel_mount_without_worn_uid_not_blocked() -> None:
    """解析不到穿戴 uid（旧档/简化 ctx）→ 不误拦（既有珠行为逐字段一致）。"""
    ctx, _inv, h = _mount_ctx()
    ctx["player"] = {}                       # 无已穿戴行 → _worn_uid 空
    assert h["js"]._worn_uid(ctx, "sword") == ""
    assert h["js"].mount(ctx, "gem_ruby", "sword", 0, "p1")["ok"] is True


# ===========================================================================
# E. 副手失活（经 jewel.active_rune_sockets 继承）
# ===========================================================================
def test_offhand_penalized_rune_inactive_main_hand_unaffected() -> None:
    """主手件挪作副手 → 符文不生效（空）；同符文在主手槽 → 生效。"""
    eng = _engine(offhand=OFFHAND_ON)
    # 主手：武器穿 weapon 槽 → 符文生效
    p_main, r_main = _player("sword", "weapon", socket_row=["r_atk", None, None])
    assert eng.aggregate_bonus(p_main) == {"flat": {"atk": 9.0}, "pct": {}}
    # 副手：同一件实例穿 offhand 槽（role=offhand，件自身 slot=weapon）→ 折算失活
    p_off, r_off = _player("sword", "weapon", socket_row=["r_atk", None, None])
    p_off["equipment"] = {"offhand": {"item_id": "sword", "uid": r_off.uid}}
    assert eng.penalized_slots(p_off) == frozenset({"offhand"})
    assert eng.aggregate_bonus(p_off) == {"flat": {}, "pct": {}}
    # 直接验证 jewel 闸门对该路径生效（同源判定点）
    ctx = eng._rune_ctx(p_off)
    assert eng._jewel.active_rune_sockets(ctx, "sword", r_off.uid) == []


# ===========================================================================
# F. 回归对拍（无符文 / 无该路径时逐字段一致）
# ===========================================================================
def test_no_runes_field_by_field_regression() -> None:
    """装了符文数据源但无符文行 → 与「无 runes/jewel」引擎逐字段一致（对拍）。"""
    plain = EquipmentEngine(slots=SLOTS)
    wired = _engine()
    cases: List[Tuple[str, str, Optional[list]]] = [
        ("sword", "weapon", None), ("sword", "weapon", [None, None, None]),
        ("vest", "armor_body", None), ("vest", "armor_body", [None, None, None]),
    ]
    for item_id, slot, sockets in cases:
        p_plain, _ = _player(item_id, slot, socket_row=sockets)
        p_wired, _ = _player(item_id, slot, socket_row=sockets)
        assert plain.aggregate_bonus(p_plain) == wired.aggregate_bonus(p_wired), (item_id, sockets)


def test_jewel_mount_unmount_regression_with_empty_rune_bucket() -> None:
    """符文容器存在（空）时，既有装饰珠 mount/unmount 逐字段一致（回归对拍）。"""
    ctx, inv, h = _mount_ctx()
    res = h["js"].mount(ctx, "gem_ruby", "sword", 0, "p1")
    assert res == {
        "ok": True, "message": "✅ 红宝石 已镶嵌到 sword 槽位1（普通档，绑定 p1）",
        "jewel_id": "gem_ruby", "quality": "common", "stack_key": "gem_ruby|common|",
        "slot_index": 0, "equip_id": "sword", "slot_level": 3, "bound_to": "p1",
    }, res
    un = h["js"].unmount(ctx, "sword", 0, "p1")
    assert un["ok"] is True and inv["gem_ruby"] == 2


# ===========================================================================
# G. 指令壳适配路径（装配注入形态：runes/items/jewel 经 ctx 生效）
# ===========================================================================
def test_equip_adapter_applies_rune_from_ctx_sources() -> None:
    """/装备 适配路径：runes/items/jewel 注入 → 穿上即得符文数值（生产接线形态）。"""
    from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter

    row = _row("sword", "weapon")
    player: Dict[str, Any] = {
        "inventory": [row], "equipment": {}, "attributes": PlayerAttributes(base={"atk": 10}),
        "persistent_state": {"rune_sockets": {row.uid: ["r_atk", None, None]}},
    }
    ctx: Dict[str, Any] = {"player": player, "slots": SLOTS, "runes": dict(RUNES),
                           "items": dict(ITEMS), "equipment_offhand": dict(OFFHAND_ON)}
    adapter = EquipmentEngineAdapter(
        slots=SLOTS, runes=dict(RUNES), items=dict(ITEMS), jewel=_jewel())
    res = adapter.equip_wear(1, ctx)
    assert res["ok"] is True, res
    assert player["attributes"].bonus["flat"]["atk"] == 9.0
    assert _combatant_of(player)["atk"] == 19


# ===========================================================================
# H. 校验器 / 键空间门禁（1 阶符文数值键必须命中 GEAR_NUMERIC_KEYS）
# ===========================================================================
def _rules(report: Any, bucket: str = "errors") -> List[Any]:
    return [e.detail.get("rule") for e in getattr(report, bucket)]


def _pack(runes: List[Any]) -> Dict[str, Any]:
    return {
        "manifest": {"name": "t", "version": "1.0", "schema_version": 1,
                     "author": "t", "modules": ["items", "runes"]},
        "items": [{"id": "sword", "type": "weapon"}],
        "runes": runes,
    }


def test_validator_accepts_every_registered_numeric_key() -> None:
    """1 阶符文 stats 全键取 GEAR_NUMERIC_KEYS（唯一源）→ 零红拦（键空间闭合）。"""
    one = {"id": "r1", "tier": 1, "family": "f",
           "by_equip_type": {"default": {"stats": {k: 1 for k in GEAR_NUMERIC_KEYS}}}}
    assert check_pack(_pack([one]), default_field_meta_table()).count_errors == 0


def test_validator_rejects_unregistered_stat_key() -> None:
    """自造键（未在 data/gear_stats.py 注册）→ 红拦（防键空间漂移）。"""
    bad = {"id": "r1", "tier": 1, "family": "f",
           "by_equip_type": {"default": {"stats": {"atk": 6, "not_a_registered_key": 1}}}}
    rep = check_pack(_pack([bad]), default_field_meta_table())
    assert "stat_key_unknown" in _rules(rep)
