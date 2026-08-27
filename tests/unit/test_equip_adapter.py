"""装备引擎适配层单测（M6 批次1·路B · basic_commands.EquipmentEngineAdapter / EQP-12）。

依据：细化_M6_三引擎与基础指令（D1）§三 TC-EQP-01~05（部位匹配/互斥/后装覆盖/卸下回包/
聚合重算）+ EQP-12（/装备 命令从 FakeEquipEngine 替身换真实 EquipmentEngine 适配层）。

测试风格对齐 tests/unit/test_basic_commands.py：纯 pytest、零 NoneBot、断言具体输出字符串。
适配器经 equip_wear(index, ctx) / equip_remove(slot_id, ctx) 消费接口驱动（与命令壳一致）。
"""

from __future__ import annotations

import pytest

from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, PlayerAttributes

BANNED_EMOJI = set("🔥🟢💥⚔️🛡️✨⭐🌟🎉🎊💎🏆❤️💖⚠️🚫📜🗡️🛒🧪⏰📅➡️🔹🔸▸")


def _item(item_id, name, slot, stats_bonus=None, bound=False):
    return ItemInstance(
        item_id=item_id, name=name, count=1, quality="normal", bound=bound,
        stack_max=1, slot=slot, stats_bonus=dict(stats_bonus or {}),
    )


def make_eq_ctx(inventory=None, equipment=None, attributes=None, in_battle=False, **adapter_kw):
    """适配器消费 ctx：ctx["player"] 可变 dict（对齐引擎契约）+ equip_engine 注入。"""
    player = {
        "inventory": list(inventory or []),
        "equipment": dict(equipment or {}),
        "attributes": attributes or PlayerAttributes(
            base={"hp": 100.0, "mp": 30.0, "str": 15.0, "con": 10.0}
        ),
        "in_battle": in_battle,
    }
    engine = EquipmentEngineAdapter(**adapter_kw)
    return {"player": player, "equip_engine": engine}


def _final_str(ctx):
    return calc_all_final_attributes(ctx["player"]["attributes"])["str"]


def _worn(ctx, slot):
    eq = ctx["player"]["equipment"]
    return eq.get(slot)


# ---------------------------------------------------------------------------
# TC-EQP-01 部位匹配穿戴（经适配器 equip_wear，槽位取 ItemInstance.slot）
# ---------------------------------------------------------------------------

def test_eqp_01_adapter_slot_match_wear():
    """TC-EQP-01：背包 铁剑(slot=weapon)、秘银甲(slot=armor_body)；equip_wear 铁剑 → ✅ 已装备。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon", {"str": 5.0}),
                   _item("chain_mail", "秘银甲", "armor_body", {"def": 8.0})],
        slots={"weapon": {"name": "武器", "max": 1}, "armor_body": {"name": "身体", "max": 1}},
    )
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is True
    assert "✅ 已装备：铁剑" in r["message"]
    assert _worn(ctx, "weapon").item_id == "iron_sword"
    # 力量 15 → 20（加成 flat 5 生效）
    assert _final_str(ctx) == 20


def test_eqp_01_adapter_mismatch_rejected():
    """EQP-E1：铁剑尝试穿入不匹配槽（适配器按 item.slot 定槽，无法硬塞）——
    背包第 2 件是 armor_body 甲，equip_wear 不会错配；验证穿甲进武器槽语义 = 拒绝。"""
    ctx = make_eq_ctx(
        inventory=[_item("chain_mail", "秘银甲", "armor_body", {"def": 8.0})],
        slots={"weapon": {"name": "武器", "max": 1}, "armor_body": {"name": "身体", "max": 1}},
    )
    # 适配器：目标槽 = item.slot（armor_body），不出现「穿不上」；模拟直接调引擎错配 → 拒绝
    r = ctx["equip_engine"]._engine.equip(ctx["player"], ctx["player"]["inventory"][0], "weapon")
    assert r["ok"] is False and r["reason"] == "slot_mismatch"
    assert r["message"] == "这个位置穿不上"


# ---------------------------------------------------------------------------
# TC-EQP-02 互斥拦截
# ---------------------------------------------------------------------------

def test_eqp_02_adapter_mutual_exclusion():
    """TC-EQP-02：slots 配 mutual_exclusions=[[weapon,shield]]；已穿武器 → 穿盾拒绝，原装备保留。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon"),
                   _item("shield", "盾牌", "shield")],
        slots={"weapon": {"name": "武器", "max": 1}, "shield": {"name": "盾牌", "max": 1}},
        mutual_exclusions=[["weapon", "shield"]],
    )
    assert ctx["equip_engine"].equip_wear(1, ctx)["ok"] is True       # 穿武器
    r = ctx["equip_engine"].equip_wear(2, ctx)                        # 穿盾 → 互斥拒绝
    assert r["ok"] is False
    assert "互斥" in r["message"] and r["message"].startswith("❌")
    assert set(ctx["player"]["equipment"].keys()) == {"weapon"}       # 原装备保留


# ---------------------------------------------------------------------------
# TC-EQP-03 后装覆盖
# ---------------------------------------------------------------------------

def test_eqp_03_adapter_cover_replacement():
    """TC-EQP-03：身槽已穿 秘银甲A → 穿 秘银甲B → 身槽=B；A 回包（背包行保留）；聚合按 B 重算。"""
    ctx = make_eq_ctx(
        inventory=[_item("mail_a", "秘银甲A", "armor_body", {"def": 5.0}),
                   _item("mail_b", "秘银甲B", "armor_body", {"def": 8.0})],
        slots={"armor_body": {"name": "身体", "max": 1}},
    )
    assert ctx["equip_engine"].equip_wear(1, ctx)["ok"] is True
    r = ctx["equip_engine"].equip_wear(2, ctx)
    assert r["ok"] is True
    assert "秘银甲B" in r["message"] and "已替换" in r["message"]
    assert _worn(ctx, "armor_body").item_id == "mail_b"
    # 两件仍在背包（A 回包 = equipment 键替换；背包行 slot=可装备类型保留，EQP-04/B-3）
    assert len(ctx["player"]["inventory"]) == 2


# ---------------------------------------------------------------------------
# TC-EQP-04 unequip 回包
# ---------------------------------------------------------------------------

def test_eqp_04_adapter_unequip():
    """TC-EQP-04：已穿铁剑（力量 15→20）→ equip_remove weapon → 力量回 15；背包有铁剑行。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon", {"str": 5.0})],
        equipment={"weapon": EquipmentSlot(item_id="iron_sword", name="铁剑")},
        slots={"weapon": {"name": "武器", "max": 1}},
    )
    # 装配/加载层进入时应用穿戴加成
    ctx["equip_engine"]._engine.aggregate_bonus(ctx["player"])
    assert _final_str(ctx) == 20
    r = ctx["equip_engine"].equip_remove("weapon", ctx)
    assert r["ok"] is True
    assert "✅ 已卸下：铁剑" in r["message"]
    assert ctx["player"]["equipment"] == {}
    assert _final_str(ctx) == 15                                # 力量回 15（卸装即时重算）
    rows = [x for x in ctx["player"]["inventory"] if x.item_id == "iron_sword"]
    assert rows and rows[0].slot == "weapon"


def test_eqp_04_adapter_empty_slot_rejected():
    """EQP-E3：空槽卸下 → ❌ 该槽位没有装备。"""
    ctx = make_eq_ctx(slots={"weapon": {"name": "武器", "max": 1}})
    r = ctx["equip_engine"].equip_remove("weapon", ctx)
    assert r["ok"] is False
    assert "该槽位没有装备" in r["message"]


# ---------------------------------------------------------------------------
# TC-EQP-05 aggregate 聚合重算（经适配器穿两件）
# ---------------------------------------------------------------------------

def test_eqp_05_adapter_aggregate():
    """TC-EQP-05：铁剑 {str:+5} + 戒指 {str:+3} → 聚合 flat.str=8；面板力量=15+8=23。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon", {"str": 5.0}),
                   _item("ring", "戒指", "accessory", {"str": 3.0})],
        slots={"weapon": {"name": "武器", "max": 1}, "accessory": {"name": "饰品", "max": 2}},
    )
    assert ctx["equip_engine"].equip_wear(1, ctx)["ok"] is True
    assert ctx["equip_engine"].equip_wear(2, ctx)["ok"] is True
    assert ctx["player"]["attributes"].bonus["flat"] == {"str": 8.0}   # 同层求和
    assert _final_str(ctx) == 23


# ---------------------------------------------------------------------------
# 边界：玩家缺失 / 战斗内 / emoji 纪律
# ---------------------------------------------------------------------------

def test_eqp_adapter_player_missing():
    """适配器兜底：ctx 无 player → 提示先 /注册。"""
    eng = EquipmentEngineAdapter()
    r = eng.equip_wear(1, {})
    assert r["ok"] is False and "注册" in r["message"]


def test_eqp_adapter_in_battle_rejected():
    """EQP-09：战斗中穿/脱 → ❌ 战斗中不可更换装备（战前换装）。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon")],
        in_battle=True,
        slots={"weapon": {"name": "武器", "max": 1}},
    )
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is False
    assert "战斗中不可更换装备" in r["message"]


def test_eqp_adapter_no_decorative_emoji():
    """M5 裁决：适配层渲染仅 ✅/❌，无装饰 emoji。"""
    ctx = make_eq_ctx(
        inventory=[_item("iron_sword", "铁剑", "weapon")],
        slots={"weapon": {"name": "武器", "max": 1}},
    )
    out = ctx["equip_engine"].equip_wear(1, ctx)["message"]
    out += ctx["equip_engine"].equip_remove("weapon", ctx)["message"]
    assert not any(ch in BANNED_EMOJI for ch in out)
