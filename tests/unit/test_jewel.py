"""JewelSystem 珠系统引擎单测（M8 批7-1·路A · qbot_rpg/core/jewel.py）。

文件：tests/unit/test_jewel.py
创建：2026-08-29
作者：Hermes 子agent（M8 批7-1·路A）
功能：JewelSystem 纯函数直测（对齐 test_gem_wallet/test_quality 模式）——槽级→珠档映射、
  镶嵌/无损拆珠、战斗中不可插拔、同名递减表驱动、战斗触发上限、堆叠键；珠升阶链
  （TC-01~06）复用 UpgradeEngine._exec_jewel（批2 执行器）实测语义。

依据：
  - docs/细化/细化_2c4c_珠与合成指令.md：
      TC-20 镶嵌成功（2 级槽装精良 / 1 级槽装普通）
      TC-21 槽级不足拒绝（2 级槽装传说）+ 3 级槽可装
      TC-22 拆珠无损返还原档原特性
      TC-23 战斗中拒绝插拔
      TC-24 同名递减（1 颗 100%/2 颗×50%/3 颗×25%/4 颗不叠加）+ 触发上限 3
      TC-01~06 珠升阶链（3×同档同 ID+宝石10→+1 阶 / 禁跳级 / 混档混 ID 拒绝 /
               宝石不足拒绝 / 无职业硬门槛）
      BEL-15 堆叠键=ID+品质档+特性集（键变分堆）
  - 工程补白 J-1~J-8（ctx["slot_defs"] / ctx["equipment"] / ctx["battle_snapshot"] /
    hook 签名 / 战斗标记 / 槽级判定）

覆盖矩阵（每条正例 + 反例，断言精确数值/档位/消息/reason）：
  TC-20  镶嵌成功：2 级槽装精良 + 1 级槽装普通；珠扣包、槽位写入快照含 stack_key
  TC-21  槽级不足：2 级槽装传说 → slot_too_low；3 级槽装传说 → 成功
  TC-22  拆珠无损：返还原档/原特性/原堆叠键、槽位空闲可再嵌、不影响其它槽珠
  TC-23  战斗中拒绝：mount/unmount → in_battle；can_toggle_in_battle False；
         非战斗 True（战前换珠）
  TC-24  同名递减：1→1.0 / 2→0.5 / 3→0.25 / 4→0.0（不叠加）；触发上限 3；
         第 4 次触发拒绝 trigger_limit；按珠 ID 独立计数；无递减配置恒 1.0
  TC-01~06  珠升阶链（UpgradeEngine.execute）：3×同档同 ID+宝石10→+1 阶 base_effects
         数值不变 / 全链路逐级 10 宝石 / 禁跳级 jewel_skip_tier / 混档·混 ID
         inputs_insufficient / 宝石不足 cost_insufficient / 无职业硬门槛可执行
  BEL-15  stack_key：同键可堆叠（同集不同序同键）、键变分堆（ID/档/特性任一变化）
  工程补白  J-3 record_trigger 计数/上限/无战斗快照；trigger_remaining

测试风格对齐 tests/unit/test_gem_wallet.py：纯 pytest、零 NoneBot、断言具体数值/档位/
reason；ctx 顶层即玩家状态（items/slot_defs/equipment/inventory/currencies），settings
构造器注入。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.jewel import (
    DEFAULT_TRIGGER_LIMIT,
    REASON_EQUIP_NOT_FOUND,
    REASON_IN_BATTLE,
    REASON_JEWEL_NOT_FOUND,
    REASON_NO_BATTLE_SNAPSHOT,
    REASON_SLOT_EMPTY,
    REASON_SLOT_FULL,
    REASON_SLOT_NOT_FOUND,
    REASON_SLOT_TOO_LOW,
    REASON_TRIGGER_LIMIT,
    JewelSystem,
)
from qbot_rpg.core.quality import QualitySystem
from qbot_rpg.core.upgrade import UpgradeEngine

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

# 装饰珠物品定义（BEL-05：type=装饰珠；quality=品质档；base_effects=固定数值；
# traits=炼金珠独有，BEL-06；升阶链四档 base_effects 数值不变 —— TC-01 断言基准）
ITEMS: Dict[str, Mapping[str, Any]] = {
    # 攻击珠升阶链四档（base_effects 恒 {atk:3}：TC-01「原数值不变」数据口径）
    "jewel_atk_common": {"id": "jewel_atk_common", "name": "攻击珠·普通", "type": "装饰珠",
                         "quality": "common", "base_effects": {"atk": 3}, "traits": []},
    "jewel_atk_uncommon": {"id": "jewel_atk_uncommon", "name": "攻击珠·精良", "type": "装饰珠",
                           "quality": "uncommon", "base_effects": {"atk": 3}, "traits": []},
    "jewel_atk_rare": {"id": "jewel_atk_rare", "name": "攻击珠·史诗", "type": "装饰珠",
                       "quality": "rare", "base_effects": {"atk": 3}, "traits": []},
    "jewel_atk_legendary": {"id": "jewel_atk_legendary", "name": "攻击珠·传说", "type": "装饰珠",
                            "quality": "legendary", "base_effects": {"atk": 3}, "traits": []},
    # 同档不同 ID（TC-04 混 ID 拒绝用）
    "jewel_def_common": {"id": "jewel_def_common", "name": "防御珠·普通", "type": "装饰珠",
                         "quality": "common", "base_effects": {"def": 3}, "traits": []},
    # 炼金珠（精良 + 继承特性，BEL-06/07：traits 炼金珠独有）——拆珠无损原特性断言基准
    "jewel_atk_trait": {"id": "jewel_atk_trait", "name": "灼烧珠·精良", "type": "装饰珠",
                        "quality": "uncommon", "base_effects": {"atk": 4},
                        "traits": ["trait_burn_boost", "trait_fire_15"]},
    # 传说珠（TC-21：须 3 级槽）
    "jewel_void_legendary": {"id": "jewel_void_legendary", "name": "虚无珠·传说",
                             "type": "装饰珠", "quality": "legendary",
                             "base_effects": {"atk": 8}, "traits": []},
    # 装备（items 注册表提供显示名）
    "short_sword": {"id": "short_sword", "name": "短剑", "type": "weapon"},
    "sword": {"id": "sword", "name": "长剑", "type": "weapon"},
    "legend_sword": {"id": "legend_sword", "name": "传说之剑", "type": "weapon"},
}

# 珠插槽定义（J-1：slots.json 珠插槽条目归一映射；槽位 0 起）
SLOT_DEFS: Dict[str, list] = {
    "short_sword": [{"slot_level": 1}],            # 1 级槽：只装普通（TC-20）
    "sword": [{"slot_level": 2}, {"slot_level": 2}],  # 2 级槽：精良及以下（TC-20/21）
    "legend_sword": [{"slot_level": 3}, {"slot_level": 3}],  # 3 级槽：全部含传说（TC-21）
}

# settings.alchemy 段（BEL-10/BEL-11：gem_diminish 表 + 战斗道具.珠触发上限）
ALCHEMY_CFG: Dict[str, Any] = {
    "gem_diminish": [{"n": 2, "mult": 0.5}, {"n": 3, "mult": 0.25}],
    "战斗道具": {"强度公式": "技能×(1+0.4×冷却数)", "珠触发上限": 3},
    "gem.珠升阶": 10,
}

# UpgradeEngine settings（批2：settings.alchemy 段，gem 费率键直接读）
UPGRADE_SETTINGS: Dict[str, Any] = {"gem.珠升阶": 10}

# JewelSystem settings（settings 顶层含 alchemy 段——settings.alchemy.gem_diminish /
# settings.alchemy.战斗道具.珠触发上限，对齐 gem_wallet 构造注入单源）
JS_SETTINGS: Dict[str, Any] = {"alchemy": ALCHEMY_CFG}

# 珠升阶 recipe（kind=upgrade 配置实例，BEL-12/CMB-01）
RECIPE_COMMON: Dict[str, Any] = {
    "id": "upgrade_bead_uncommon", "kind": "upgrade", "name": "珠三合一升阶（普通→精良）",
    "inputs": [{"item": "jewel_atk_common", "count": 3}],
    "cost": {"gem": 10}, "output": {"item": "jewel_atk_uncommon", "count": 1},
}
RECIPE_UNCOMMON: Dict[str, Any] = {
    "id": "upgrade_bead_rare", "kind": "upgrade", "name": "珠三合一升阶（精良→史诗）",
    "inputs": [{"item": "jewel_atk_uncommon", "count": 3}],
    "cost": {"gem": 10}, "output": {"item": "jewel_atk_rare", "count": 1},
}
RECIPE_RARE: Dict[str, Any] = {
    "id": "upgrade_bead_legendary", "kind": "upgrade", "name": "珠三合一升阶（史诗→传说）",
    "inputs": [{"item": "jewel_atk_rare", "count": 3}],
    "cost": {"gem": 10}, "output": {"item": "jewel_atk_legendary", "count": 1},
}
# 禁跳级 recipe（TC-03：普通→史诗 越级 → jewel_skip_tier）
RECIPE_SKIP: Dict[str, Any] = {
    "id": "upgrade_bead_skip", "kind": "upgrade", "name": "禁跳级（普通→史诗）",
    "inputs": [{"item": "jewel_atk_common", "count": 3}],
    "cost": {"gem": 10}, "output": {"item": "jewel_atk_rare", "count": 1},
}


def make_ctx(
    held: Optional[Mapping[str, int]] = None,
    gem: int = 100,
    *,
    in_battle: bool = False,
    battle_snapshot: Optional[MutableMapping] = None,
) -> Dict[str, Any]:
    """构造测试 ctx（J-4/J-5：inventory + hooks + in_battle 标记）。

    add_item(item_id, count, bound=默认 True)：返还未绑定标记；remove_item 扣减；
    count_item 查询——供 mount/unmount/UpgradeEngine 共用。
    """
    inv: Dict[str, int] = dict(held) if held else {}
    equipment: Dict[str, Any] = {
        "short_sword": {"jewels": {}},
        "sword": {"jewels": {}},
        "legend_sword": {"jewels": {}},
    }

    def add_item(item_id: Any, count: int = 1, bound: bool = True) -> bool:
        inv[str(item_id)] = inv.get(str(item_id), 0) + int(count)
        return True

    def remove_item(item_id: Any, count: int = 1) -> bool:
        key = str(item_id)
        if inv.get(key, 0) < int(count):
            return False
        inv[key] -= int(count)
        return True

    def count_item(item_id: Any) -> int:
        return inv.get(str(item_id), 0)

    ctx: Dict[str, Any] = {
        "items": ITEMS,
        "slot_defs": SLOT_DEFS,
        "inventory": inv,
        "equipment": equipment,
        "currencies": {"coins": 100, "gem": gem},
        "add_item": add_item,
        "remove_item": remove_item,
        "count_item": count_item,
    }
    if in_battle:
        ctx["in_battle"] = True
    if battle_snapshot is not None:
        ctx["battle_snapshot"] = battle_snapshot
    return ctx


# ---------------------------------------------------------------------------
# TC-20 镶嵌成功（SOCK-02：槽级≥珠档；1 级槽=普通 / 2 级槽=精良及以下）
# ---------------------------------------------------------------------------
def test_tc20_mount_success_2level_slot_uncommon() -> None:
    """TC-20 正例：长剑（2 级槽）镶 精良珠 → 成功。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_uncommon": 1, "jewel_atk_common": 1})
    out = js.mount(ctx, "jewel_atk_uncommon", "sword", 0, "P001")
    assert out["ok"] is True
    assert out["quality"] == "uncommon"
    assert out["slot_index"] == 0
    assert out["slot_level"] == 2
    assert out["bound_to"] == "P001"
    # 珠扣包 + 槽位写入快照（J-2，含 stack_key）
    assert ctx["inventory"]["jewel_atk_uncommon"] == 0
    snap = ctx["equipment"]["sword"]["jewels"][0]
    assert snap["jewel_id"] == "jewel_atk_uncommon"
    assert snap["quality"] == "uncommon"
    assert snap["traits"] == []
    assert snap["bound"] is True
    assert snap["bound_to"] == "P001"
    assert snap["stack_key"] == js.stack_key("jewel_atk_uncommon", "uncommon", [])


def test_tc20_mount_success_1level_slot_common() -> None:
    """TC-20 正例：短剑（1 级槽）镶 普通珠 → 成功（BEL-03：1 级=只普通）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 1})
    out = js.mount(ctx, "jewel_atk_common", "short_sword", 0, "P002")
    assert out["ok"] is True
    assert out["quality"] == "common"
    assert out["slot_level"] == 1
    assert ctx["inventory"]["jewel_atk_common"] == 0
    assert "jewel_atk_common" in ctx["equipment"]["short_sword"]["jewels"][0]["jewel_id"]


def test_tc20_slot_accepts_mapping() -> None:
    """BEL-03 映射逐档核验：1 级=普通；2 级=精良及以下；3 级=全部（含传说）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    assert js.slot_accepts(1, "common") is True
    assert js.slot_accepts(1, "uncommon") is False
    assert js.slot_accepts(1, "rare") is False
    assert js.slot_accepts(1, "legendary") is False
    assert js.slot_accepts(2, "common") is True
    assert js.slot_accepts(2, "uncommon") is True
    assert js.slot_accepts(2, "rare") is False
    assert js.slot_accepts(2, "legendary") is False
    assert js.slot_accepts(3, "common") is True
    assert js.slot_accepts(3, "uncommon") is True
    assert js.slot_accepts(3, "rare") is True
    assert js.slot_accepts(3, "legendary") is True
    # 非法槽级防御（J-7）
    assert js.slot_accepts(0, "common") is False
    assert js.slot_accepts(-1, "common") is False


# ---------------------------------------------------------------------------
# TC-21 槽级不足拒绝（SOCK-02 门票：槽级≥珠档；传说珠必须 3 级槽）
# ---------------------------------------------------------------------------
def test_tc21_mount_legendary_rejected_on_2level_slot() -> None:
    """TC-21 反例：长剑仅 2 级槽 → 传说珠 → slot_too_low。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_legendary": 1})
    out = js.mount(ctx, "jewel_atk_legendary", "sword", 0, "P003")
    assert out["ok"] is False
    assert out["reason"] == REASON_SLOT_TOO_LOW
    assert out["quality"] == "legendary"
    # 珠未被消耗、槽位未写入
    assert ctx["inventory"]["jewel_atk_legendary"] == 1
    assert ctx["equipment"]["sword"]["jewels"] == {}


def test_tc21_mount_legendary_success_on_3level_slot() -> None:
    """TC-21 正例：3 级槽装备 → 传说珠可嵌（BEL-03：3 级=全部）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_void_legendary": 1})
    out = js.mount(ctx, "jewel_void_legendary", "legend_sword", 0, "P004")
    assert out["ok"] is True
    assert out["quality"] == "legendary"
    assert ctx["equipment"]["legend_sword"]["jewels"][0]["quality"] == "legendary"


def test_tc21_mount_reject_reasons() -> None:
    """SOCK-02 各拒绝支路：珠不存在 / 槽位越界 / 槽满 / 装备无珠插槽。"""
    js = JewelSystem(settings=JS_SETTINGS)
    # 珠定义缺失 → jewel_not_found
    ctx = make_ctx()
    out = js.mount(ctx, "jewel_missing", "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_JEWEL_NOT_FOUND
    # 背包未持有 → jewel_not_found
    ctx = make_ctx()
    out = js.mount(ctx, "jewel_atk_common", "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_JEWEL_NOT_FOUND
    # 装备无珠插槽登记 → equip_not_found
    ctx = make_ctx({"jewel_atk_common": 1})
    out = js.mount(ctx, "jewel_atk_common", "no_such_equip", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_EQUIP_NOT_FOUND
    # 槽位越界 → slot_not_found
    ctx = make_ctx({"jewel_atk_common": 1})
    out = js.mount(ctx, "jewel_atk_common", "sword", 99, "P")
    assert out["ok"] is False and out["reason"] == REASON_SLOT_NOT_FOUND
    # 槽位已占用 → slot_full（先镶一颗再镶第二颗到同槽）
    ctx = make_ctx({"jewel_atk_common": 2})
    assert js.mount(ctx, "jewel_atk_common", "sword", 1, "P")["ok"] is True
    out = js.mount(ctx, "jewel_atk_common", "sword", 1, "P")
    assert out["ok"] is False and out["reason"] == REASON_SLOT_FULL


# ---------------------------------------------------------------------------
# TC-22 拆珠无损（SOCK-03：原档/原特性/原堆叠键返还，槽位空闲可再嵌）
# ---------------------------------------------------------------------------
def test_tc22_unmount_lossless_original_tier_and_traits() -> None:
    """TC-22 正例：拆下炼金珠 → 原档原特性返还，槽位空闲可再嵌。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_trait": 1})
    assert js.mount(ctx, "jewel_atk_trait", "sword", 0, "P005")["ok"] is True
    assert ctx["inventory"]["jewel_atk_trait"] == 0
    out = js.unmount(ctx, "sword", 0, "P005")
    assert out["ok"] is True
    # 原档原特性原堆叠键（无损，SOCK-03）
    assert out["quality"] == "uncommon"
    assert out["traits"] == ["trait_burn_boost", "trait_fire_15"]
    expected_key = js.stack_key("jewel_atk_trait", "uncommon",
                                ["trait_burn_boost", "trait_fire_15"])
    assert out["stack_key"] == expected_key
    # 珠返还背包（保留堆叠键 → 同键可堆叠回原堆）
    assert ctx["inventory"]["jewel_atk_trait"] == 1
    # 槽位空闲可再嵌
    assert ctx["equipment"]["sword"]["jewels"] == {}
    re = js.mount(ctx, "jewel_atk_trait", "sword", 0, "P005")
    assert re["ok"] is True and re["stack_key"] == expected_key


def test_tc22_unmount_keeps_other_slots() -> None:
    """TC-22：拆一槽不影响其它槽珠（多槽装备）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 1, "jewel_atk_uncommon": 1})
    assert js.mount(ctx, "jewel_atk_common", "sword", 0, "P")["ok"] is True
    assert js.mount(ctx, "jewel_atk_uncommon", "sword", 1, "P")["ok"] is True
    assert js.unmount(ctx, "sword", 0, "P")["ok"] is True
    assert 0 not in ctx["equipment"]["sword"]["jewels"]
    assert ctx["equipment"]["sword"]["jewels"][1]["jewel_id"] == "jewel_atk_uncommon"


def test_tc22_unmount_reject_reasons() -> None:
    """SOCK-03 反例：空槽 / 无装备 / 槽位非法。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 1})
    # 空槽 → slot_empty
    out = js.unmount(ctx, "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_SLOT_EMPTY
    # 无装备珠插槽桶 → equip_not_found
    out = js.unmount(ctx, "no_such_equip", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_EQUIP_NOT_FOUND
    # 槽位非法 → slot_not_found
    out = js.unmount(ctx, "sword", -1, "P")
    assert out["ok"] is False and out["reason"] == REASON_SLOT_NOT_FOUND


# ---------------------------------------------------------------------------
# TC-23 战斗中拒绝插拔（SOCK-05/BEL-09：战前换珠=核心策略）
# ---------------------------------------------------------------------------
def test_tc23_mount_and_unmount_rejected_in_battle() -> None:
    """TC-23 反例：战斗中 /镶嵌 /拆珠 → in_battle 拒绝。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 1}, in_battle=True)
    out = js.mount(ctx, "jewel_atk_common", "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_IN_BATTLE
    assert ctx["inventory"]["jewel_atk_common"] == 1  # 珠未被消耗
    out = js.unmount(ctx, "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_IN_BATTLE


def test_tc23_can_toggle_in_battle() -> None:
    """SOCK-05：战斗中不可插拔 → False；非战斗可插拔 → True（战前更换生效下一场）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    assert js.can_toggle_in_battle(make_ctx(in_battle=True)) is False
    assert js.can_toggle_in_battle(make_ctx(in_battle=False)) is True
    assert js.can_toggle_in_battle(make_ctx()) is True


def test_tc23_battle_prechange_then_battle() -> None:
    """TC-23 正例：战前更换 → 生效于下一场战斗（战前可插拔，进入战斗后配置锁定）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 1})
    assert js.mount(ctx, "jewel_atk_common", "short_sword", 0, "P")["ok"] is True
    ctx["in_battle"] = True
    assert js.can_toggle_in_battle(ctx) is False
    out = js.mount(ctx, "jewel_atk_common", "sword", 0, "P")
    assert out["ok"] is False and out["reason"] == REASON_IN_BATTLE


# ---------------------------------------------------------------------------
# TC-24 同名递减 + 触发上限（BEL-10/BEL-11）
# ---------------------------------------------------------------------------
def test_tc24_diminish_table() -> None:
    """TC-24 同名递减：1 颗 100% / 2 颗×50% / 3 颗×25% / 4 颗及以上不叠加。"""
    js = JewelSystem(settings=JS_SETTINGS)
    assert js.diminish_mult(1) == 1.0
    assert js.diminish_mult(2) == 0.5
    assert js.diminish_mult(3) == 0.25
    assert js.diminish_mult(4) == 0.0
    assert js.diminish_mult(5) == 0.0
    assert js.diminish_mult(0) == 1.0  # 非法 count 归一第 1 颗


def test_tc24_diminish_configurable_off() -> None:
    """BEL-10：gem_diminish 配 0/空 → 无递减恒 1.0。"""
    cfgs: list = [{}, {"gem_diminish": 0}, {"gem_diminish": None}, {"gem_diminish": []}]
    for cfg in cfgs:
        js = JewelSystem(settings={"alchemy": cfg})
        assert js.diminish_mult(2) == 1.0
        assert js.diminish_mult(3) == 1.0
        assert js.diminish_mult(9) == 1.0


def test_tc24_diminish_custom_table() -> None:
    """BEL-10：表驱动可配（命中/超出最大档不叠加）。"""
    js = JewelSystem(settings={"alchemy": {"gem_diminish": [{"n": 2, "mult": 0.6}]}})
    assert js.diminish_mult(1) == 1.0
    assert js.diminish_mult(2) == 0.6
    assert js.diminish_mult(3) == 0.0  # 超出表最大档 → 无该档 → 不叠加
    assert js.diminish_mult(4) == 0.0  # 第 4 颗及以上不叠加


def test_tc24_trigger_limit_default() -> None:
    """BEL-11：触发上限默认 3（settings 未配/缺省）。"""
    assert JewelSystem(settings=ALCHEMY_CFG).trigger_limit() == 3
    assert JewelSystem().trigger_limit() == DEFAULT_TRIGGER_LIMIT == 3
    assert JewelSystem(settings={"alchemy": {"战斗道具": {}}}).trigger_limit() == 3


def test_tc24_trigger_limit_configurable() -> None:
    """BEL-11：settings.alchemy.战斗道具.珠触发上限 可配。"""
    js = JewelSystem(settings={"alchemy": {"战斗道具": {"珠触发上限": 5}}})
    assert js.trigger_limit() == 5


def test_tc24_trigger_count_up_to_limit() -> None:
    """BEL-11/TC-24：第 1~3 次触发成功，第 4 次同珠 ID → trigger_limit 拒绝（不触发）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    snap: MutableMapping[str, Any] = {}
    ctx = make_ctx(battle_snapshot=snap)
    for i in range(1, 4):
        out = js.record_trigger(ctx, "jewel_atk_common")
        assert out["ok"] is True
        assert out["count"] == i
        assert out["remaining"] == 3 - i
    out = js.record_trigger(ctx, "jewel_atk_common")
    assert out["ok"] is False
    assert out["reason"] == REASON_TRIGGER_LIMIT
    assert out["count"] == 3
    assert snap["jewel_triggers"]["jewel_atk_common"] == 3
    # trigger_remaining 0
    assert js.trigger_remaining(ctx, "jewel_atk_common") == 0


def test_tc24_trigger_count_per_jewel_id() -> None:
    """BEL-11：按珠 ID 独立计数（不同珠 ID 互不影响）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx(battle_snapshot={})
    assert js.record_trigger(ctx, "jewel_atk_common")["ok"] is True
    assert js.record_trigger(ctx, "jewel_def_common")["ok"] is True
    assert js.record_trigger(ctx, "jewel_atk_common")["ok"] is True
    assert js.trigger_remaining(ctx, "jewel_atk_common") == 1
    assert js.trigger_remaining(ctx, "jewel_def_common") == 2


def test_tc24_trigger_no_battle_snapshot() -> None:
    """BEL-11/J-3：无战斗快照 → 计数无法落账（供批9 判断接线前置）。"""
    js = JewelSystem(settings=JS_SETTINGS)
    ctx = make_ctx()  # 无 battle_snapshot
    out = js.record_trigger(ctx, "jewel_atk_common")
    assert out["ok"] is False and out["reason"] == REASON_NO_BATTLE_SNAPSHOT
    assert js.trigger_remaining(ctx, "jewel_atk_common") == 0


# ---------------------------------------------------------------------------
# BEL-15 堆叠键（ID+品质档+特性集；同键可堆叠、键变分堆）
# ---------------------------------------------------------------------------
def test_stack_key_same_key_stackable() -> None:
    """BEL-15 正例：同 ID 同档同特性集（不同顺序）→ 同键可堆叠。"""
    js = JewelSystem()
    k1 = js.stack_key("jewel_atk_trait", "uncommon", ["trait_fire_15", "trait_burn_boost"])
    k2 = js.stack_key("jewel_atk_trait", "uncommon", ["trait_burn_boost", "trait_fire_15"])
    assert k1 == k2
    assert k1 == "jewel_atk_trait|uncommon|trait_burn_boost,trait_fire_15"


def test_stack_key_split_on_any_change() -> None:
    """BEL-15 反例：ID/品质档/特性集任一变化 → 键变分堆。"""
    js = JewelSystem()
    base = js.stack_key("jewel_atk_common", "common", [])
    assert js.stack_key("jewel_def_common", "common", []) != base          # 不同 ID
    assert js.stack_key("jewel_atk_common", "uncommon", []) != base        # 不同档（升阶）
    assert js.stack_key("jewel_atk_common", "common", ["trait_x"]) != base  # 不同特性集
    # 升阶使品质档变化 → 堆叠键变更（EDGE-01/BEL-15）
    assert js.stack_key("jewel_atk_common", "common", []) != \
        js.stack_key("jewel_atk_uncommon", "uncommon", [])


# ---------------------------------------------------------------------------
# TC-01~06 珠升阶链（复用 UpgradeEngine._exec_jewel 语义）
# ---------------------------------------------------------------------------
def test_tc01_upgrade_3_common_to_uncommon() -> None:
    """TC-01：3×普通 + 宝石10 → 精良×1，base_effects 数值不变，宝石 -10。"""
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 3}, gem=50)
    out = eng.execute(ctx, RECIPE_COMMON)
    assert out["ok"] is True
    assert out["produced"] == {"item": "jewel_atk_uncommon", "count": 1}
    # 输入 3 颗扣除 + 产出 1 颗入包 + 宝石 -10（原子提交 U-A1）
    assert ctx["inventory"]["jewel_atk_common"] == 0
    assert ctx["inventory"]["jewel_atk_uncommon"] == 1
    assert ctx["currencies"]["gem"] == 40
    # base_effects 数值不变（升阶原数值不变，BEL-12/TC-01）
    assert ITEMS["jewel_atk_common"]["base_effects"] == {"atk": 3}
    assert ITEMS["jewel_atk_uncommon"]["base_effects"] == {"atk": 3}


def test_tc02_full_chain_to_legendary() -> None:
    """TC-02 全链路：3×普通 → 精良 → 3×精良 → 史诗 → 3×史诗 → 传说，每级 10 宝石。"""
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    # 每级用独立背包（链路语义：产出档 +1，逐级相邻，每级 gem.珠升阶=10）
    cases = [
        (RECIPE_COMMON, "jewel_atk_common", "jewel_atk_uncommon"),
        (RECIPE_UNCOMMON, "jewel_atk_uncommon", "jewel_atk_rare"),
        (RECIPE_RARE, "jewel_atk_rare", "jewel_atk_legendary"),
    ]
    for recipe, src, dst in cases:
        ctx = make_ctx({src: 3}, gem=30)
        out = eng.execute(ctx, recipe)
        assert out["ok"] is True, out
        assert out["produced"]["item"] == dst
        assert ctx["currencies"]["gem"] == 20  # 每级 10 宝石
        assert ctx["inventory"][src] == 0
        assert ctx["inventory"][dst] == 1
    # 终点=传说（BEL-13：链末项；传说之上无 recipe → 内容包无更高档 → 指令壳拒绝）
    q = QualitySystem()
    assert q.index_to_tier(q.tier_index("legendary") + 1) == "legendary"


def test_tc03_skip_tier_rejected() -> None:
    """TC-03 反例（禁跳级）：普通→史诗 越级 → jewel_skip_tier（档位链连续，BEL-13）。"""
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 3}, gem=50)
    out = eng.execute(ctx, RECIPE_SKIP)
    assert out["ok"] is False
    assert out["reason"] == "jewel_skip_tier"
    # 珠与宝石均不消耗
    assert ctx["inventory"]["jewel_atk_common"] == 3
    assert ctx["currencies"]["gem"] == 50


def test_tc04_mixed_tier_or_id_rejected() -> None:
    """TC-04 反例（混档/混 ID）：普通×2+精良×1 → 拒；攻击珠×2+防御珠×1 → 拒。"""
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    # 混档：3 颗须同档（普通仅 2 颗 → 不足 3 颗普通 → inputs_insufficient）
    ctx = make_ctx({"jewel_atk_common": 2, "jewel_atk_uncommon": 1}, gem=50)
    out = eng.execute(ctx, RECIPE_COMMON)
    assert out["ok"] is False
    assert out["reason"] == "inputs_insufficient"
    assert ctx["currencies"]["gem"] == 50
    # 混 ID：同档不同 ID（普通攻击珠仅 2 颗 + 防御珠 1 颗 → 攻击珠不足 3 → 拒）
    ctx = make_ctx({"jewel_atk_common": 2, "jewel_def_common": 1}, gem=50)
    out = eng.execute(ctx, RECIPE_COMMON)
    assert out["ok"] is False
    assert out["reason"] == "inputs_insufficient"
    assert ctx["currencies"]["gem"] == 50


def test_tc05_gem_insufficient_rejected() -> None:
    """TC-05 反例（宝石不足）：宝石 5/10 → cost_insufficient，珠与宝石均不消耗。"""
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 3}, gem=5)
    out = eng.execute(ctx, RECIPE_COMMON)
    assert out["ok"] is False
    assert out["reason"] == "cost_insufficient"
    assert ctx["inventory"]["jewel_atk_common"] == 3
    assert ctx["currencies"]["gem"] == 5


def test_tc06_no_class_gate_upgrade_executable() -> None:
    """TC-06：无职业硬门槛——任意炼金职业（含见习）→ /珠升阶 可执行。

    引擎不设职业/称号参数（拍板③：升阶准入靠槽级 SOCK-02）；构造不传任何职业信息
    → 材料足即可执行；传说珠须 3 级槽由 slot_accepts 保证（TC-21 已覆盖）。
    """
    eng = UpgradeEngine(settings=UPGRADE_SETTINGS)
    ctx = make_ctx({"jewel_atk_common": 3}, gem=20)
    out = eng.execute(ctx, RECIPE_COMMON)
    assert out["ok"] is True
    assert ctx["inventory"]["jewel_atk_uncommon"] == 1
    # 传说珠须 3 级槽（EDGE-01 联动：升阶后档位上升 → 槽级准入同步收紧）
    js = JewelSystem(settings=JS_SETTINGS)
    assert js.slot_accepts(2, "legendary") is False
    assert js.slot_accepts(3, "legendary") is True


# ---------------------------------------------------------------------------
# 边界防御（工程补白 J-*）
# ---------------------------------------------------------------------------
def test_jewel_tier_of_default_common() -> None:
    """BEL-02 缺省：珠定义无品质章 → common；档位键/序号/品质分多样解析。"""
    js = JewelSystem()
    assert js.jewel_tier_of(None) == "common"
    assert js.jewel_tier_of({}) == "common"
    assert js.jewel_tier_of({"id": "x", "type": "装饰珠"}) == "common"
    assert js.jewel_tier_of({"quality": "rare"}) == "rare"
    assert js.jewel_tier_of({"quality": 72}) == "rare"          # 品质分 → 档位
    assert js.jewel_tier_of({"quality": {"score": 85}}) == "legendary"
    assert js.jewel_tier_of({"tier": 1}) == "uncommon"          # 档位序号
