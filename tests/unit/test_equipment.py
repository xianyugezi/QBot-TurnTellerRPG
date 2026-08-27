"""装备引擎单测（M6 批次1·路A · qbot_rpg/core/equipment.py）——TC-EQP-01~06 全量 + 规则补充。

依据：细化_M6_三引擎与基础指令（D1）§三（EQP-01~EQP-12 / TC-EQP-01~TC-EQP-06）；
【框架】L815-830（部位定义/装备校验链「占用集合→互斥→数量→穿上」）、L1535-1537（互斥环
加载期拦截/运行期人话拒绝）、L187-192（战斗中不可插拔）；【4b】EQP-R01~R08；【3b】TC-07
（卸装即时重算）。

测试风格对齐 tests/unit/test_basic_commands.py：纯 pytest、零 NoneBot、断言具体行为。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from qbot_rpg.core.equipment import (
    DEFAULT_SLOT_NAMES,
    DEFAULT_SLOT_ORDER,
    EquipmentEngine,
    validate_slot_exclusions,
)
from qbot_rpg.core.player_attributes import calc_all_final_attributes
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import EquipmentSlot, PlayerAttributes


def _item(item_id, name, slot, stats_bonus=None, bound=False):
    return ItemInstance(
        item_id=item_id, name=name, count=1, quality="normal", bound=bound,
        stack_max=1, slot=slot, stats_bonus=dict(stats_bonus or {}),
    )


def make_eq_player(inventory=None, equipment=None, attributes=None, in_battle=False):
    """构造 EquipmentEngine 消费的玩家状态 dict（可变）。"""
    return {
        "inventory": list(inventory or []),
        "equipment": dict(equipment or {}),
        "attributes": attributes or PlayerAttributes(
            base={"str": 15.0, "hp": 100.0, "mp": 30.0}
        ),
        "in_battle": in_battle,
    }


def _final_str(player):
    """最终 str（三层管线出口，EQP-07 全链重算消费方）。"""
    return calc_all_final_attributes(player["attributes"])["str"]


# ---------------------------------------------------------------------------
# TC-EQP-01 部位匹配穿戴（EQP-02）
# ---------------------------------------------------------------------------
def test_tc_eqp_01_slot_match():
    """TC-EQP-01：铁剑(type=weapon) → weapon 槽成功；尝试穿入不匹配槽 → 拒绝「这个位置穿不上」。"""
    eng = EquipmentEngine(slots={
        "weapon": {"name": "武器", "max": 1},
        "armor_body": {"name": "身体", "max": 1},
    })
    sword = _item("iron_sword", "铁剑", slot="weapon", stats_bonus={"str": 5.0})
    mail = _item("chain_mail", "秘银甲", slot="armor_body", stats_bonus={"def": 8.0})
    player = make_eq_player(inventory=[sword, mail])

    r_ok = eng.equip(player, sword, "weapon")
    assert r_ok["ok"] is True and r_ok["slot"] == "weapon"
    assert player["equipment"]["weapon"].item_id == "iron_sword"

    # 秘银甲(type=armor_body) 尝试穿入 weapon 槽 → 拒绝
    r_bad = eng.equip(player, mail, "weapon")
    assert r_bad["ok"] is False and r_bad["reason"] == "slot_mismatch"
    assert r_bad["message"] == "这个位置穿不上"
    # 铁剑尝试穿入 armor_body 槽 → 同样拒绝
    r_bad2 = eng.equip(player, sword, "armor_body")
    assert r_bad2["ok"] is False and r_bad2["reason"] == "slot_mismatch"
    assert player["equipment"].get("armor_body") is None


# ---------------------------------------------------------------------------
# TC-EQP-02 互斥拦截（EQP-03）
# ---------------------------------------------------------------------------
def test_tc_eqp_02_mutual_exclusion():
    """TC-EQP-02：slots 配 mutual_exclusions=[[weapon,shield]]；已穿武器 → equip 盾牌 拒绝，原装备保留。"""
    eng = EquipmentEngine(
        slots={"weapon": {"name": "武器", "max": 1}, "shield": {"name": "盾牌", "max": 1}},
        mutual_exclusions=[["weapon", "shield"]],
    )
    sword = _item("iron_sword", "铁剑", slot="weapon")
    shield = _item("shield", "盾牌", slot="shield")
    player = make_eq_player(inventory=[sword, shield])

    assert eng.equip(player, sword, "weapon")["ok"] is True

    r = eng.equip(player, shield, "shield")
    assert r["ok"] is False and r["reason"] == "mutual_exclusion"
    assert "互斥" in r["message"]
    # 原装备保留
    assert set(player["equipment"].keys()) == {"weapon"}
    assert player["equipment"]["weapon"].item_id == "iron_sword"


# ---------------------------------------------------------------------------
# TC-EQP-03 后装覆盖（EQP-04）
# ---------------------------------------------------------------------------
def test_tc_eqp_03_cover_replacement():
    """TC-EQP-03：身槽已穿 秘银甲A → equip 秘银甲B → 身槽=B；A 自动回背包；equip_snapshot 按 B 重算。"""
    eng = EquipmentEngine(slots={"armor_body": {"name": "身体", "max": 1}})
    mail_a = _item("mail_a", "秘银甲A", slot="armor_body", stats_bonus={"def": 5.0})
    mail_b = _item("mail_b", "秘银甲B", slot="armor_body", stats_bonus={"def": 8.0})
    player = make_eq_player(inventory=[mail_a, mail_b])

    assert eng.equip(player, mail_a, "armor_body")["ok"] is True
    assert eng.aggregate_bonus(player)["flat"].get("def") == 5.0

    r = eng.equip(player, mail_b, "armor_body")
    assert r["ok"] is True and r["replaced"] == "mail_a"
    assert player["equipment"]["armor_body"].item_id == "mail_b"   # 身槽=B
    # A 自动回背包（equipment 键被替换即回包；两行仍留背包，slot=可装备类型保留）
    row_a = next(x for x in player["inventory"] if x.item_id == "mail_a")
    row_b = next(x for x in player["inventory"] if x.item_id == "mail_b")
    assert row_a.slot == "armor_body" and row_b.slot == "armor_body"
    # equip_snapshot 按 B 重算（同层聚合仅 B）
    assert eng.aggregate_bonus(player)["flat"].get("def") == 8.0


# ---------------------------------------------------------------------------
# TC-EQP-04 unequip 回包（EQP-05/EQP-07）
# ---------------------------------------------------------------------------
def test_tc_eqp_04_unequip():
    """TC-EQP-04：已穿铁剑（力量 15→20）→ unequip weapon → 力量回 15；snapshot flat 清空；背包有铁剑行。"""
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    sword = _item("iron_sword", "铁剑", slot="weapon", stats_bonus={"str": 5.0})
    player = make_eq_player(
        inventory=[sword],
        equipment={"weapon": EquipmentSlot(item_id="iron_sword", name="铁剑")},
    )

    eng.aggregate_bonus(player)      # 装配/加载层进入时应用穿戴加成（EQP-06 刷新）
    assert _final_str(player) == 20  # 白值 15 + 加成 flat 5
    assert eng.aggregate_bonus(player)["flat"] == {"str": 5.0}

    r = eng.unequip(player, "weapon")
    assert r["ok"] is True and r["item_id"] == "iron_sword"
    assert player["equipment"] == {}                          # 槽位清空
    assert eng.aggregate_bonus(player)["flat"] == {}          # 移除该件聚合
    assert _final_str(player) == 15                           # 力量回 15
    # 背包出现铁剑行（slot=可装备类型保留）
    rows = [x for x in player["inventory"] if x.item_id == "iron_sword"]
    assert rows and rows[0].slot == "weapon"

    # 空槽卸下 → 拒绝（EQP-E3）
    r2 = eng.unequip(player, "weapon")
    assert r2["ok"] is False and r2["reason"] == "empty_slot"
    assert r2["message"] == "该槽位没有装备"


# ---------------------------------------------------------------------------
# TC-EQP-05 aggregate 聚合重算（EQP-06/EQP-07）
# ---------------------------------------------------------------------------
def test_tc_eqp_05_aggregate():
    """TC-EQP-05：铁剑 {str:+5} + 戒指 {str:+3} → flat.str=8（同层求和）；面板力量=15+8=23。"""
    eng = EquipmentEngine(slots={
        "weapon": {"name": "武器", "max": 1},
        "accessory": {"name": "饰品", "max": 2},
    })
    sword = _item("iron_sword", "铁剑", slot="weapon", stats_bonus={"str": 5.0})
    ring = _item("ring", "戒指", slot="accessory", stats_bonus={"str": 3.0})
    player = make_eq_player(inventory=[sword, ring])

    assert eng.equip(player, sword, "weapon")["ok"] is True
    assert eng.equip(player, ring, "accessory")["ok"] is True

    snapshot = eng.aggregate_bonus(player)
    assert snapshot["flat"] == {"str": 8.0}                    # 同层求和
    assert snapshot["pct"] == {}
    assert _final_str(player) == 23                            # 15+8=23
    # 加成层落点（equip_snapshot 语义 = attributes.bonus）
    assert player["attributes"].bonus["flat"] == {"str": 8.0}


# ---------------------------------------------------------------------------
# TC-EQP-06 互斥环加载拦截 + 战斗内拒绝（EQP-08/EQP-09）
# ---------------------------------------------------------------------------
def test_tc_eqp_06_cycle_block_and_battle_reject():
    """TC-EQP-06：互斥成环 → 加载期红色拦截；战斗中 equip → 拒绝「战斗中不可更换装备」。"""
    # 互斥环加载期拦截（EQP-08）：weapon↔shield↔offhand 成环 → ValueError
    with pytest.raises(ValueError):
        validate_slot_exclusions([
            ["weapon", "shield"], ["shield", "offhand"], ["offhand", "weapon"],
        ])
    # 自环同样成环
    with pytest.raises(ValueError):
        validate_slot_exclusions([["weapon", "weapon"]])
    # 单个两人组（框架 5.1 示例）→ 合法，不拦
    validate_slot_exclusions([["weapon", "shield"]])

    # 运行期：战斗中穿/脱拒绝（EQP-09，战前换装）
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    sword = _item("iron_sword", "铁剑", slot="weapon")
    player = make_eq_player(inventory=[sword], in_battle=True)

    r = eng.equip(player, sword, "weapon")
    assert r["ok"] is False and r["reason"] == "in_battle"
    assert r["message"] == "战斗中不可更换装备（战前换装）"
    assert player["equipment"] == {}

    r2 = eng.unequip(player, "weapon")
    assert r2["ok"] is False and r2["reason"] == "in_battle"


# ---------------------------------------------------------------------------
# 补充：equip_search 预留 / 未知槽 / 物品缺失 / pct 钩子 / 配置注入
# ---------------------------------------------------------------------------
def test_supplement_eqp_10_equip_search():
    """EQP-10：equip_search 登记签名返回空结果（检索细节待 M-y 编辑器接管）。"""
    eng = EquipmentEngine()
    r = eng.equip_search("sword", encode=True)
    assert r["ok"] is True and r["results"] == []
    assert r["registered"] is True and r["encode"] is True


def test_supplement_unknown_slot_and_item_missing():
    """EQP-E1/EQP 未知槽与背包缺失：均拒绝并人话提示。"""
    eng = EquipmentEngine()  # 缺省六部位（工程补白 3）
    assert set(DEFAULT_SLOT_NAMES) == set(DEFAULT_SLOT_ORDER)
    sword = _item("iron_sword", "铁剑", slot="weapon")
    player = make_eq_player(inventory=[sword])

    r = eng.equip(player, sword, "no_such_slot")
    assert r["ok"] is False and r["reason"] == "unknown_slot"

    ghost = _item("ghost", "幽灵剑", slot="weapon")
    r2 = eng.equip(player, ghost, "weapon")
    assert r2["ok"] is False and r2["reason"] == "item_not_found"


def test_supplement_eqp_11_aggregate_pct_hook():
    """EQP-11/EQP-06 补充：实例快照携带 stats_pct（钩子）→ 聚合进加成层 pct；装备层不写 temp。"""
    @dataclass(frozen=True)
    class PctItem(ItemInstance):
        stats_pct: Optional[dict] = None  # noqa: E501

    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    sword = PctItem(
        "iron_sword", "铁剑", 1, "normal", False, stack_max=1, slot="weapon",
        stats_bonus={"str": 5.0}, stats_pct={"str": 0.05},
    )
    player = make_eq_player(inventory=[sword])

    assert eng.equip(player, sword, "weapon")["ok"] is True
    snapshot = eng.aggregate_bonus(player)
    assert snapshot["flat"] == {"str": 5.0}
    assert snapshot["pct"] == {"str": 0.05}
    # 装备层只进加成层，temp 层不被装备引擎改写（EQP-11）
    assert player["attributes"].temp == {"pct": {}, "flat": {}}


def test_supplement_slots_json_wrapper_shape():
    """配置注入：slots.json 包装形态 {"slots", "mutual_exclusions"} 直接可用（EQP-17/F-17）。"""
    eng = EquipmentEngine({
        "slots": {
            "weapon": {"name": "武器", "max": 1},
            "shield": {"name": "盾牌", "max": 1},
        },
        "mutual_exclusions": [["weapon", "shield"]],
    })
    sword = _item("iron_sword", "铁剑", slot="weapon")
    shield = _item("shield", "盾牌", slot="shield")
    player = make_eq_player(inventory=[sword, shield])

    assert eng.equip(player, sword, "weapon")["ok"] is True
    assert eng.equip(player, shield, "shield")["reason"] == "mutual_exclusion"


def test_regress_p1_1_aggregate_takes_one_of_duplicate_id():
    """P1-1 回归（M6 批1A 审查）：同 item_id 两件（词条不同）并存、只穿一件 →
    aggregate_bonus 只取该件词条，不把未穿戴行词条翻倍计入加成层。"""
    eng = EquipmentEngine(slots={"weapon": {"name": "武器", "max": 1}})
    sword_a = _item("iron_sword", "铁剑", slot="weapon", stats_bonus={"str": 5.0})
    sword_b = _item("iron_sword", "铁剑", slot="weapon", stats_bonus={"str": 7.0})
    player = make_eq_player(inventory=[sword_a, sword_b])

    assert eng.equip(player, sword_a, "weapon")["ok"] is True
    snapshot = eng.aggregate_bonus(player)
    assert snapshot["flat"] == {"str": 5.0}
    assert snapshot["pct"] == {}
    assert player["attributes"].bonus["flat"] == {"str": 5.0}
