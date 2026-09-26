"""批46 · 符文地基（43-A）单测：数据模型 / 校验 / 镶嵌落档 / 3 合 1 / 回归对拍 / 副手继承。

依据：`/root/deliverables/符文系统_实现口径.md` §〇 结论速览 1/3/4/5 + §二 数据模型 +
§五 43-A；原案 `打造系统_原案_20260919.md` §9；`docs/深度打造_决策记录.md` H1/H2。

覆盖：
  A. 数据模型：三阶独立刻度（不读 quality）、by_equip_type default+覆盖、缺省孔位、3 合 1 纯函数；
  B. 校验器：阶枚举红拦 / default 缺红拦 / stats 自造键红拦 / effects 悬空引用红拦 /
     family 必填 / 未知类型黄提示 / default+覆盖解析；
  C. 镶嵌落档：随实例走（装配/卸下/重登）、迁移幂等无损、新库直具备、6 处构造点静态审计；
  D. 3 合 1：3×同阶同 id → +1 阶、禁跳级、原子（失败零副作用）；
  E. 回归：既有装饰珠镶嵌逐字段对拍（加 rune_sockets 前后一致）、副手失活对符文同样生效。

纪律：测试只构造内存数据 / 读仓库既有内容包（只读），不写任何真实内容包。
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any, Dict, List, Optional

import qbot_rpg
from qbot_rpg.assembly.context import AssemblyDeps, make_context
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import build_pack, check_manifest_modules_registered
from qbot_rpg.content.module_catalog import catalog_entry
from qbot_rpg.content.registry import Registry
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.equipment import EquipmentEngine
from qbot_rpg.core.jewel import JewelSystem
from qbot_rpg.core.player_attributes import PlayerAttributes
from qbot_rpg.core.runes import (
    DEFAULT_SOCKET_COUNT,
    RUNE_TIERS,
    by_equip_type_of,
    next_rune_tier,
    resolve_rune_upgrade,
    rune_tier_of,
    socket_count_of,
)
from qbot_rpg.core.upgrade import UpgradeEngine
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, Player
from qbot_rpg.storage.connection import Database
from qbot_rpg.storage.migrations import backfill_rune_sockets
from qbot_rpg.storage.repository import Repository

CONTENT = Path(qbot_rpg.__file__).parent.parent / "content"
SLOTS: Dict[str, Any] = {
    "weapon": {"name": "武器", "max": 1},
    "offhand": {"name": "副手", "max": 1, "role": "offhand"},
}
OFFHAND_ON: Dict[str, Any] = {"enabled": True, "single_hand_scale": 0.5}


# ---------------------------------------------------------------------------
# 构造器（内存数据；不写内容包）
# ---------------------------------------------------------------------------
def _rune(rune_id: str, tier: int, family: str = "burn", **over: Any) -> Dict[str, Any]:
    d: Dict[str, Any] = {
        "id": rune_id, "name": rune_id, "tier": tier, "family": family,
        "by_equip_type": {"default": {"stats": {"atk": 6}}},
    }
    d.update(over)
    return d


def _pack_modules(runes: List[Any], *, items: Optional[List[Any]] = None,
                  effects: Optional[List[Any]] = None) -> Dict[str, Any]:
    return {
        "manifest": {"name": "t", "version": "1.0", "schema_version": 1,
                     "author": "t", "modules": ["items", "effects", "runes"]},
        "items": items if items is not None else [{"id": "sword", "type": "weapon"}],
        "effects": effects if effects is not None else [{"id": "eff_x", "type": "control"}],
        "runes": runes,
    }


def _rules(report: Any, bucket: str = "errors") -> List[Any]:
    return [e.detail.get("rule") for e in getattr(report, bucket)]


def _item(item_id: str, slot: str, **kw: Any) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=item_id, count=1, quality="normal",
                        bound=False, stack_max=1, slot=slot, **kw)


def _player(rows: List[Any], equipment: Dict[str, Any], ps: Optional[Dict[str, Any]] = None
            ) -> Dict[str, Any]:
    return {"inventory": list(rows), "equipment": dict(equipment),
            "attributes": PlayerAttributes(), "persistent_state": dict(ps or {})}


def _mount_ctx(runes: Optional[Dict[str, Any]] = None, held: Optional[Dict[str, int]] = None,
               equipment: Optional[Dict[str, Any]] = None,
               socket_defs: Optional[Dict[str, Any]] = None) -> Any:
    inv: Dict[str, int] = dict(held if held is not None else {"r1": 3})

    def count_item(i: Any) -> int:
        return int(inv.get(str(i), 0))

    def remove_item(i: Any, c: int = 1) -> bool:
        key = str(i)
        if inv.get(key, 0) < int(c):
            return False
        inv[key] -= int(c)
        return True

    def add_item(i: Any, c: int = 1, bound: bool = True) -> bool:
        inv[str(i)] = inv.get(str(i), 0) + int(c)
        return True

    ctx: Dict[str, Any] = {
        "runes": dict(runes or {}), "items": {}, "inventory": inv,
        "equipment": dict(equipment or {}), "rune_sockets": {},
        "count_item": count_item, "remove_item": remove_item, "add_item": add_item,
    }
    if socket_defs is not None:
        ctx["slot_defs"] = socket_defs
    return ctx, inv


# ===========================================================================
# A. 数据模型（三阶独立刻度 / default+覆盖 / 缺省孔位 / 3 合 1 纯函数）
# ===========================================================================
def test_rune_tier_is_independent_scale_ignores_quality() -> None:
    """三阶独立刻度：只读 tier；quality 四档一律忽略（H2 正交）。"""
    assert RUNE_TIERS == (1, 2, 3)
    assert rune_tier_of({"tier": 2, "quality": "legendary"}) == 2
    assert rune_tier_of({"quality": "legendary"}) is None
    for bad in (0, 4, -1, "x", 2.5, True, None):
        assert rune_tier_of({"tier": bad}) is None, bad


def test_next_rune_tier_chain_end() -> None:
    assert next_rune_tier(1) == 2 and next_rune_tier(2) == 3 and next_rune_tier(3) is None


def test_by_equip_type_default_plus_override() -> None:
    """R2：default 兜底 + 类型覆盖（顶层浅覆盖：stats 整块覆盖）；未命中 → default。"""
    rune = {"id": "r", "tier": 1, "by_equip_type": {
        "default": {"stats": {"atk": 6, "hp": 4}},
        "weapon": {"stats": {"atk": 9}},
        "armor_body": {"stats": {"dfn": 8}},
    }}
    assert by_equip_type_of(rune, "weapon")["stats"] == {"atk": 9}            # 整块覆盖
    assert by_equip_type_of(rune, "armor_body")["stats"] == {"dfn": 8}
    assert by_equip_type_of(rune, "armor_head")["stats"] == {"atk": 6, "hp": 4}  # 未命中→default
    assert by_equip_type_of(rune, None)["stats"] == {"atk": 6, "hp": 4}
    # 覆盖条目未写 stats → 沿用 default.stats（浅覆盖只替换出现的键）
    rune2 = {"id": "r", "tier": 2, "by_equip_type": {
        "default": {"stats": {"atk": 6}}, "weapon": {"effects": [{"effect": "eff_x"}]}}}
    assert by_equip_type_of(rune2, "weapon") == {
        "stats": {"atk": 6}, "effects": [{"effect": "eff_x"}]}
    assert by_equip_type_of({"id": "x", "tier": 1}, "weapon") == {}


def test_socket_count_is_configurable_not_hardcoded() -> None:
    """R-4：缺省孔位可配（1-3）；非法/越界回落默认 3。"""
    assert DEFAULT_SOCKET_COUNT == 3
    assert socket_count_of(None) == 3
    assert socket_count_of({"default_count": 2}) == 2
    assert socket_count_of({"default_count": 1}) == 1
    for bad in (0, 4, -1, "x", True, None):
        assert socket_count_of({"default_count": bad}) == 3, bad


def test_resolve_rune_upgrade_pure_function() -> None:
    """R-3 纯函数：3×同阶 → +1 阶（必成）；件数不足 / 满阶 / 跳级一律拒绝。"""
    r1, r3 = _rune("r1", 1), _rune("r3", 3)
    ok = resolve_rune_upgrade(r1, 3)
    assert ok["ok"] and (ok["tier_in"], ok["tier_out"], ok["count"]) == (1, 2, 3)
    assert resolve_rune_upgrade(r1, 2)["reason"] == "rune_input_count"
    assert resolve_rune_upgrade(r3, 3)["reason"] == "rune_max_tier"
    assert resolve_rune_upgrade(r1, 3, output_tier=3)["reason"] == "rune_skip_tier"
    assert resolve_rune_upgrade({"id": "x"}, 3)["reason"] == "rune_tier_missing"


# ===========================================================================
# B. 校验器（RUNE-01~07）
# ===========================================================================
def test_validator_accepts_wellformed_rune_pack() -> None:
    mods = _pack_modules([_rune("r1", 1, effects=[{"effect": "eff_x", "overrides": {"v": 1}}])])
    assert check_pack(mods, default_field_meta_table()).count_errors == 0


def test_validator_rejects_tier_enum_range() -> None:
    mods = _pack_modules([_rune("r1", 4)])
    rep = check_pack(mods, default_field_meta_table())
    assert "tier_invalid" in _rules(rep)


def test_validator_rejects_missing_default_and_family_and_unknown_stat() -> None:
    rune = {"id": "r1", "tier": 1,
            "by_equip_type": {"weapon": {"stats": {"atk": 9, "bogus": 1}}}}
    rep = check_pack(_pack_modules([rune]), default_field_meta_table())
    rules = _rules(rep)
    assert "family_required" in rules
    assert "by_equip_type_default_missing" in rules
    assert "stat_key_unknown" in rules


def test_validator_tier1_requires_default_stats() -> None:
    rune = {"id": "r1", "tier": 1, "family": "f", "by_equip_type": {"default": {}}}
    rep = check_pack(_pack_modules([rune]), default_field_meta_table())
    assert "tier1_stats_required" in _rules(rep)


def test_validator_rejects_dangling_effect_reference() -> None:
    rune = _rune("r2", 2, effects=[{"effect": "nope"}])
    rep = check_pack(_pack_modules([rune]), default_field_meta_table())
    assert "effect_ref_missing" in _rules(rep)


def test_validator_unknown_equip_type_is_yellow_not_red() -> None:
    rune = {"id": "r1", "tier": 1, "family": "f",
            "by_equip_type": {"default": {"stats": {"atk": 6}},
                              "bogus_type": {"stats": {"atk": 7}}}}
    rep = check_pack(_pack_modules([rune]), default_field_meta_table())
    assert "equip_type_unknown" in _rules(rep, "warnings")
    assert "equip_type_unknown" not in _rules(rep, "errors")


def test_shipped_veinborn_runes_module_registered_and_green() -> None:
    """换包/模块登记：veinborn runes 模块被 field_meta 认领 + 整包零红拦。"""
    pack, _ = build_pack(CONTENT / "veinborn", None, None, 1)
    assert pack.report.count_errors == 0, pack.report.errors
    assert check_manifest_modules_registered(pack.manifest.modules) == []
    assert "runes" in default_field_meta_table().modules
    assert catalog_entry("runes") is not None
    assert "rune_sockets" in default_field_meta_table().modules["settings"].fields


# ===========================================================================
# C. 镶嵌落档（随实例走 / 迁移幂等无损 / 新库直具备 / 6 构造点）
# ===========================================================================
def test_mount_unmount_and_active_read_engine() -> None:
    """引擎级：镶嵌写 uid 容器、拆卸无损返还、激活读取同源。"""
    runes = {"r1": _rune("r1", 1)}
    ctx, inv = _mount_ctx(runes=runes)
    js = JewelSystem(settings={"deep_craft": {"enabled": True},
                               "rune_sockets": {"default_count": 3}})
    res = js.mount_rune(ctx, "r1", "sword", "uidA", 1, player="p1")
    assert res["ok"] and res["tier"] == 1 and inv["r1"] == 2
    assert ctx["rune_sockets"]["uidA"] == [None, "r1", None]   # 缺省三孔全开
    assert js.active_rune_sockets(ctx, "sword", "uidA") == [None, "r1", None]
    un = js.unmount_rune(ctx, "sword", "uidA", 1)
    assert un["ok"] and inv["r1"] == 3 and ctx["rune_sockets"]["uidA"] == [None, None, None]


def test_mount_requires_deep_craft_switch_default_closed() -> None:
    """默认关闭（挂 settings.deep_craft）→ 镶嵌/拆卸全拒（开关关闭零行为）。"""
    ctx, _ = _mount_ctx(runes={"r1": _rune("r1", 1)})
    js = JewelSystem(settings={})
    assert js.mount_rune(ctx, "r1", "sword", "uidA")["reason"] == "runes_disabled"
    assert js.unmount_rune(ctx, "sword", "uidA")["reason"] == "runes_disabled"


def test_mount_shares_socket_array_with_jewel_and_is_mutually_exclusive() -> None:
    """与装饰珠共用同一孔位数组：珠占用槽 → 符文拒绝（一槽一物、互斥）；登记数组优先。"""
    ctx, _ = _mount_ctx(runes={"r1": _rune("r1", 1)},
                        equipment={"sword": {"jewels": {1: {"jewel_id": "g"}}}},
                        socket_defs={"sword": [{"slot_level": 1}, {"slot_level": 1}]})
    js = JewelSystem(settings={"deep_craft": {"enabled": True}})
    assert js.mount_rune(ctx, "r1", "sword", "uidA", 0)["ok"] is True
    assert js.mount_rune(ctx, "r1", "sword", "uidA", 1)["reason"] == "slot_full"  # 珠占用
    assert js.mount_rune(ctx, "r1", "sword", "uidA", 2)["reason"] == "slot_not_found"


def test_rune_state_follows_instance_uid_across_equip_and_unequip() -> None:
    """状态随实例走：装配 → 卸下后背包行/槽身份仍是同 uid（否则符文状态成孤儿）。"""
    row = _item("sword", "weapon")
    p = _player([row], {}, ps={"rune_sockets": {row.uid: ["r1", None, None]}})
    eng = EquipmentEngine(slots=SLOTS)
    assert eng.equip(p, row, "weapon")["ok"] is True
    assert p["equipment"]["weapon"].uid == row.uid
    # 卸下：即使原背包行被移除，新建行也回指原 uid（equipment.py 卸装路径 uid 透传）
    p["inventory"].clear()
    assert eng.unequip(p, "weapon")["ok"] is True
    uids = [str(getattr(r, "uid", "") or (r.get("uid") if isinstance(r, dict) else ""))
            for r in p["inventory"]]
    assert row.uid in uids, uids
    assert p["persistent_state"]["rune_sockets"][row.uid] == ["r1", None, None]


async def test_rune_state_survives_save_and_reload() -> None:
    """重登（存档往返）：符文状态按 uid 原样读回，槽 uid 与背包行 uid 一致。"""
    row = _item("sword", "weapon")
    player = Player(
        qid="10086", name="符文", inventory=(row,),
        equipment={"weapon": EquipmentSlot(item_id="sword", name="sword", uid=row.uid)},
        achievement_state=(),
        persistent_state={"rune_sockets": {row.uid: ["r1", None, None]}},
    )
    repo = Repository(Database(":memory:"))
    try:
        await repo.save_player(player)
        back = await repo.load_player("10086")
        assert back is not None
        assert back.inventory[0].uid == row.uid
        assert back.equipment["weapon"].uid == row.uid
        assert back.persistent_state["rune_sockets"] == {row.uid: ["r1", None, None]}
    finally:
        await repo.close()


def test_backfill_rune_sockets_idempotent_and_lossless() -> None:
    """旧档幂等补：缺 → 补空 dict；已有 → 零改动；无损只加不删。"""
    ps: Dict[str, Any] = {"location": "town", "rng_state": [1, 2]}
    out, changed = backfill_rune_sockets(ps)
    assert changed == 1 and out["rune_sockets"] == {}
    assert out["location"] == "town" and out["rng_state"] == [1, 2]
    out2, changed2 = backfill_rune_sockets(out)
    assert changed2 == 0 and out2 is out
    keep = {"rune_sockets": {"u": ["r"]}}
    out3, changed3 = backfill_rune_sockets(keep)
    assert changed3 == 0 and out3["rune_sockets"] == {"u": ["r"]}
    assert backfill_rune_sockets(None) == (None, 0)
    assert backfill_rune_sockets(["x"]) == (["x"], 0)


class _Repo:
    def __init__(self, player: Optional[Player]) -> None:
        self._p = player

    async def load_player(self, qid: str) -> Any:
        return self._p if self._p is not None and self._p.qid == str(qid) else None


class _World:
    def get_map(self, map_id: str) -> Any:
        return None

    def monster_pool(self, map_id: str) -> list:
        return []

    def get_npcs(self, map_id: str) -> list:
        return []


class _Sess:
    def get_active(self, qid: str) -> Any:
        return None


async def _ctx_of(player: Player) -> Dict[str, Any]:
    deps = AssemblyDeps(
        repo=_Repo(player), game_world=_World(),
        registry=Registry(pack_id="t", generation=1, tables={}, names={}, modules_raw={}),
        settings={}, session_mgr=_Sess(),
    )
    event = {"group_id": "1", "user_id": player.qid, "message": "/状态", "channel": "qq"}
    return await make_context(event, deps)


async def test_new_player_directly_has_rune_sockets_container() -> None:
    """新库直具备：新建玩家（persistent_state 无该键）→ 装配即挂回空容器并落 ps。"""
    player = Player(qid="10001", name="新", achievement_state=(), persistent_state={})
    ctx = await _ctx_of(player)
    assert ctx["rune_sockets"] == {}
    assert player.persistent_state["rune_sockets"] == {}
    assert ctx["rune_sockets"] is player.persistent_state["rune_sockets"]  # 写 ctx 即落档


async def test_old_save_backfilled_idempotently_in_context() -> None:
    """旧档幂等补：已有符文状态零改动；无键补空；重复装配不重建（同引用）。"""
    uid = "fixed-uid"
    old = Player(qid="10002", name="旧", achievement_state=(),
                 persistent_state={"rune_sockets": {uid: ["r1", None, None]}})
    ctx = await _ctx_of(old)
    assert ctx["rune_sockets"] == {uid: ["r1", None, None]}
    again = await _ctx_of(old)
    assert again["rune_sockets"] is old.persistent_state["rune_sockets"]


def test_item_instance_construction_sites_audit() -> None:
    """`ItemInstance` 构造点静态审计：uid 透传（漏一处即丢）。

    批83 · N2/N3/N5 收敛后：写路径两条内联归一（runner / basic_commands）不再各自
    构造 `ItemInstance`，改调公共函数 `data/item.py::item_instance_from_mapping`
    （该函数内**单点**构造并透传 uid）→ 静态构造点数 6 → 5。
    """
    root = Path(qbot_rpg.__file__).parent
    sites: List[Any] = []
    for f in sorted(root.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "ItemInstance":
                kw = {k.arg for k in node.keywords}
                sites.append((f.relative_to(root).as_posix(), node.lineno, "uid" in kw))
    assert len(sites) == 5, sites
    no_uid = {(p, ln) for p, ln, u in sites if not u}
    # 两个合法落点：全新购买实例（__post_init__ 补新 uid）+ 旧实例无字段的 TypeError 兜底
    assert {p for p, _ in no_uid} == {"commands/shop_tx.py", "core/equipment.py"}, no_uid
    assert all(p != "storage/repository.py" or u for p, _l, u in sites)  # 读档必须透传
    # 公共归一函数（写路径唯一构造点）必须透传 uid
    assert all(p != "data/item.py" or u for p, _l, u in sites), sites


# ===========================================================================
# D. 3 合 1（必成 / 禁跳级 / 原子）
# ===========================================================================
def _upgrade_ctx(held: Optional[Dict[str, int]] = None, gem: int = 10) -> Any:
    inv = dict(held or {"r1": 3})

    def count_item(i: Any) -> int:
        return int(inv.get(str(i), 0))

    def remove_item(i: Any, c: int) -> bool:
        key = str(i)
        if inv.get(key, 0) < int(c):
            return False
        inv[key] -= int(c)
        return True

    def add_item(i: Any, c: int, bound: bool) -> bool:
        inv[str(i)] = inv.get(str(i), 0) + int(c)
        return True

    cur = {"coins": 0, "gem": gem}
    ctx = {"runes": {"r1": _rune("r1", 1), "r2": _rune("r2", 2), "r3": _rune("r3", 3)},
           "items": {}, "inventory": inv, "count_item": count_item,
           "remove_item": remove_item, "add_item": add_item, "currencies": cur}
    return ctx, inv, cur


def _rune_recipe(inp: str, out: str, **over: Any) -> Dict[str, Any]:
    d = {"kind": "upgrade", "subtype": "rune_upgrade", "id": "rcp",
         "inputs": [{"item": inp, "count": 3}], "output": {"item": out, "count": 1},
         "cost": {"gem": 10}}
    d.update(over)
    return d


def test_rune_3in1_upgrades_same_tier_by_one() -> None:
    eng = UpgradeEngine(settings={})
    ctx, inv, cur = _upgrade_ctx()
    res = eng.execute(ctx, _rune_recipe("r1", "r2"))
    assert res["ok"] and (res["tier_in"], res["tier_out"]) == (1, 2)
    assert inv == {"r1": 0, "r2": 1} and cur["gem"] == 0


def test_rune_3in1_rejects_skip_tier() -> None:
    eng = UpgradeEngine(settings={})
    ctx, inv, cur = _upgrade_ctx()
    res = eng.execute(ctx, _rune_recipe("r1", "r3"))
    assert res["ok"] is False and res["reason"] == "rune_skip_tier"
    assert inv == {"r1": 3} and cur["gem"] == 10          # 零副作用
    ctx3, _inv3, _c3 = _upgrade_ctx(held={"r3": 3})
    assert eng.execute(ctx3, _rune_recipe("r3", "r2"))["reason"] == "rune_max_tier"


def test_rune_3in1_atomic_on_insufficient_inputs_or_cost() -> None:
    """原子：输入/资源不足 → 全拒零副作用（不留半成品）。"""
    eng = UpgradeEngine(settings={})
    ctx, inv, cur = _upgrade_ctx(held={"r1": 2})
    assert eng.execute(ctx, _rune_recipe("r1", "r2"))["reason"] == "inputs_insufficient"
    assert inv == {"r1": 2} and cur["gem"] == 10
    ctx, inv, cur = _upgrade_ctx(gem=0)
    assert eng.execute(ctx, _rune_recipe("r1", "r2"))["reason"] == "cost_insufficient"
    assert inv == {"r1": 3} and cur["gem"] == 0
    assert eng.execute(ctx, _rune_recipe("r1", "r2"),
                       input_ids=["not_r1"])["reason"] == "rune_input_mismatch"


def test_rune_3in1_output_tier_explicit_fallback() -> None:
    """产出端可显式声明阶位（Q8 未裁决：产出可另立条目，不在 runes 注册表）。"""
    eng = UpgradeEngine(settings={})
    ctx, inv, _ = _upgrade_ctx()
    ok = eng.execute(ctx, _rune_recipe("r1", "brand_new_2", rune_tier=2))
    assert ok["ok"] and inv["brand_new_2"] == 1
    ctx, inv, _ = _upgrade_ctx()
    assert eng.execute(ctx, _rune_recipe("r1", "brand_new_3", rune_tier=3))["reason"] \
        == "rune_skip_tier"


# ===========================================================================
# E. 回归对拍（既有装饰珠逐字段一致）+ 副手失活继承
# ===========================================================================
JEWEL_ITEMS = {"gem_ruby": {"id": "gem_ruby", "name": "红宝石", "type": "装饰珠",
                            "quality": "common"}}
JEWEL_DEFS = {"sword": [{"slot_level": 3}, {"slot_level": 3}]}


def _jewel_ctx() -> Any:
    inv = {"gem_ruby": 2}
    ctx: Dict[str, Any] = {
        "items": JEWEL_ITEMS, "slot_defs": JEWEL_DEFS, "inventory": inv,
        "equipment": {"sword": {"jewels": {}}},
        "count_item": lambda i: int(inv.get(str(i), 0)),
        "remove_item": lambda i, c=1: (inv.get(str(i), 0) >= int(c)
                                       and (inv.__setitem__(str(i), inv[str(i)] - int(c))
                                            or True)),
        "add_item": lambda i, c=1, b=True: (inv.__setitem__(str(i), inv.get(str(i), 0) + int(c))
                                            or True),
    }
    return ctx, inv


def test_jewel_mount_unmount_field_by_field_regression() -> None:
    """既有装饰珠镶嵌逐字段对拍（rune_sockets 存在与否结果完全一致）。"""
    js = JewelSystem(settings={})
    for extra in ({}, {"rune_sockets": {}}, {"rune_sockets": {"u": ["r1", None]}}):
        ctx, inv = _jewel_ctx()
        ctx.update(extra)
        res = js.mount(ctx, "gem_ruby", "sword", 0, "p1")
        assert res == {
            "ok": True, "message": "✅ 红宝石 已镶嵌到 sword 槽位1（普通档，绑定 p1）",
            "jewel_id": "gem_ruby", "quality": "common", "stack_key": "gem_ruby|common|",
            "slot_index": 0, "equip_id": "sword", "slot_level": 3, "bound_to": "p1",
        }, extra
        assert ctx["equipment"]["sword"]["jewels"][0]["jewel_id"] == "gem_ruby"
        un = js.unmount(ctx, "sword", 0, "p1")
        assert un == {
            "ok": True,
            "message": "✅ 已从 sword 槽位1 无损拆下 红宝石（原档原特性返还背包）",
            "jewel_id": "gem_ruby", "quality": "common", "traits": [],
            "stack_key": "gem_ruby|common|", "slot_index": 0, "equip_id": "sword",
            "bound_to": "p1",
        }, extra
        assert inv == {"gem_ruby": 2}


def test_jewel_slot_accepts_and_tier_unaffected() -> None:
    """槽级门票/档位解析（珠专属）不变：符文新代码不触碰 slot_accepts。"""
    js = JewelSystem(settings={})
    assert js.slot_accepts(1, "common") and not js.slot_accepts(1, "rare")
    assert js.slot_accepts(3, "legendary")


def test_rune_sockets_deactivated_on_penalized_offhand() -> None:
    """副手失活对符文同样生效（同源判定点 offhand_inactive；开关关 → 与定义一致）。"""
    row = _item("sword", "weapon")
    p = _player([row], {"offhand": {"item_id": "sword"}},
                ps={"rune_sockets": {row.uid: ["r1", None, None]}})
    js = JewelSystem(settings={})
    base = {"player": p, "slots": {"slots": SLOTS},
            "rune_sockets": p["persistent_state"]["rune_sockets"]}
    on = dict(base, equipment_offhand=dict(OFFHAND_ON))
    assert js.offhand_inactive(on, "sword") is True
    assert js.active_rune_sockets(on, "sword", row.uid) == []
    assert js.active_rune_sockets(base, "sword", row.uid) == ["r1", None, None]
