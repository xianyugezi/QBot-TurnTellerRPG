"""珠与合成指令壳单测（M8 批7-2 · qbot_rpg/commands/alchemy_commands.py 的 8 指令）。

文件：tests/unit/test_combine_commands.py
创建：2026-08-29
作者：Hermes 子agent（M8 批7-2·单路独占 commands/alchemy_commands.py）
功能：直测 async 指令处理器（真实引擎消费：JewelSystem / UpgradeEngine / AlchemyRegister，
  无会话依赖——本批指令均无会话）：
  /镶嵌 /拆珠（SOCK-02/03/04/05：槽级≥珠档、无损拆珠、战斗中不可插拔，通用无职业门槛）、
  /珠升阶（BEL-12/13/14：3×同档同 ID+宝石10→+1 阶、禁跳级、混档混 ID 拒绝、宝石不足、
    无职业硬门槛 拍板③）、
  /成品合成 /配方合成 /特性合成（CMB-02~06：宗师/专家/宗师 门槛、组合表匹配、两配方已学、
    已解锁幂等 ATO-05、非同系拒绝）、
  /登记 /复制（DUP-01~06：未登记拒绝、登记后量产标准版、非标准版登记拒绝、原子校验全拒差异、
    数量超限提示不拦 拍板⑤）。

依据：docs/细化/细化_2c4c_珠与合成指令.md（BEL/DUP/CMB/SOCK 族 + TC-01~23 验收用例）。
测试风格对齐 tests/unit/test_confirm_commands.py（parse_command 直调 + 全字段 ctx + hook 注入）+
  tests/unit/test_jewel.py（ctx 顶层即玩家状态 + slot_defs/equipment + add/remove/count hook）。
覆盖矩阵（每条正反例，断言精确文本/数值/背包/槽位/登记表）：
  TC-01  珠升阶成功（3×同档+宝石10→+1 阶，base_effects 原数值不变）
  TC-03  禁跳级拒绝（普通→史诗 recipe → jewel_skip_tier 透传）；3×传说链终点拒绝
  TC-04  混档（普通×2+精良×1）/混 ID（攻击×2+防御×1）→ 材料不足全拒零消耗
  TC-05  宝石不足 → 资源不足全拒，珠与宝石均不消耗
  TC-06  见习（level 0）/无 proficiency 节点 → 珠升阶可执行（无职业硬门槛 拍板③）
  TC-07  未登记复制 → 「未登记复制」；/登记 → 登记表落点；登记后可复制
  TC-08  复制消耗（⌊cost.coins×20%⌋=20 宝石/份 + 材料×N）+ 标准版产出
  TC-09  登记炼金成品（带 traits）→ 非标准版拒绝；已登记标准珠可复制
  TC-10  材料/宝石不足 → 全拒差异（缺 水结晶×48 / 缺 宝石 190），零消耗
  TC-11  数量超限（max_qty=5 请求 10）→ 「最多一次使用 5 个」提示不拦、按上限截断执行
  TC-12  成品合成成功（宗师，两成品+材料+宝石10 → 灭世爆弹）
  TC-13  精通 → 等级不足；宗师但宝石<10 → 资源不足，输入成品不消耗
  TC-14  配方合成成功（专家，组合表命中解锁新配方）+ 已解锁幂等（ATO-05 不重复扣宝石）
  TC-15  两配方未全部习得 → 拒绝，零消耗
  TC-16  正式/精通 → 等级不足；专家 → 门槛过（进引擎资源校验）
  TC-17  特性合成成功（宗师，两同系特性+宝石20+材料 → 更高位特性）
  TC-18  非同系特性 → 拒绝，零消耗
  TC-19  专家 → 特性合成等级不足拒绝
  TC-20  镶嵌成功（2 级槽装精良 / 1 级槽装普通）
  TC-21  槽级不足拒绝（2 级槽装传说）+ 3 级槽可嵌
  TC-22  拆珠无损（原档原特性返还、槽位空闲可再嵌、不影响其它槽珠）
  TC-23  战斗中 /镶嵌 /拆珠 → 拒绝（SOCK-05/BEL-09）
  装配  register_alchemy_commands 注册 8 指令 + ctx 注入 handler
"""
from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.commands.alchemy_commands import (
    ABANDON_CMD,
    ALCHEMY_CMD,
    CONFIRM_CMD,
    COPY_CMD,
    DECOMPOSE_CMD,
    FEED_CMD,
    FORMULA_MERGE_CMD,
    INHERIT_CMD,
    INHERIT_SUPER_CMD,
    JEWEL_UP_CMD,
    MOUNT_CMD,
    PRODUCT_MERGE_CMD,
    REGISTER_CMD,
    RESUME_CMD,
    SYNTH_CMD,
    TRAIT_MERGE_CMD,
    UNMOUNT_CMD,
    cmd_copy,
    cmd_formula_merge,
    cmd_jewel_up,
    cmd_mount,
    cmd_product_merge,
    cmd_register,
    cmd_trait_merge,
    cmd_unmount,
    register_alchemy_commands,
)
from qbot_rpg.commands.parsers import DEFAULT_WHITELIST, parse_command
from qbot_rpg.commands.router import Router

# 8 指令白名单（镶嵌/拆珠 已在 DEFAULT_WHITELIST；珠升阶/成品合成/配方合成/特性合成/登记/复制
# 由批11 路11A 装配补齐——本测试注入同款，对齐 test_confirm_commands 口径）
W = DEFAULT_WHITELIST | {
    "镶嵌", "拆珠", "珠升阶", "成品合成", "配方合成", "特性合成", "登记", "复制",
}


# ---------------------------------------------------------------------------
# 夹具：items/traits/recipe/slot_defs/settings（对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------

# 物品注册表（BEL-05：装饰珠 type=「装饰珠」+ quality + base_effects；复制标准版无 traits）
ITEMS: Dict[str, Mapping[str, Any]] = {
    # 攻击珠升阶链四档（BEL-12：base_effects 原数值不变 —— TC-01 断言基准）
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
    # 装备（items 注册表提供显示名 + slot_defs 珠插槽）
    "sword": {"id": "sword", "name": "长剑", "type": "weapon"},
    "short_sword": {"id": "short_sword", "name": "短剑", "type": "weapon"},
    "legend_sword": {"id": "legend_sword", "name": "传说之剑", "type": "weapon"},
    # 成品合成（CMB-02：两成品+材料+宝石10 → 更强成品）
    "flame_bomb_plus": {"id": "flame_bomb_plus", "name": "烈焰弹·改", "type": "consumable",
                        "quality": "uncommon"},
    "doomsday_bomb": {"id": "doomsday_bomb", "name": "灭世爆弹", "type": "consumable",
                      "quality": "legendary"},
    "ash_core": {"id": "ash_core", "name": "灰烬核心", "type": "material"},
    # 特性合成材料（CMB-04）
    "alch_ember_crystal": {"id": "alch_ember_crystal", "name": "火晶石", "type": "material"},
    "alch_fire_essence": {"id": "alch_fire_essence", "name": "火之精华", "type": "material"},
    # 复制（DUP：标准版无 traits/quality 可复制；炼金成品带 traits 不可复制）
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "alch_advanced_potion": {"id": "alch_advanced_potion", "name": "精良火焰弹",
                             "type": "consumable", "quality": "uncommon",
                             "traits": ["trait_fire_15"]},   # 非标准版（TC-09）
    # 配方合成产出（CMB-03：组合表预置新配方）
    "flame_bomb_master": {"id": "flame_bomb_master", "name": "炼狱爆弹·极",
                          "type": "consumable", "quality": "rare"},
}

# 特性注册表（CMB-04：group=同系判定键；super=金色超特性）
TRAITS: Dict[str, Mapping[str, Any]] = {
    "trait_fire_15": {"id": "trait_fire_15", "name": "灼烧强化·精", "rarity": "super",
                      "group": "fire_boost", "repeatable": False},
    "trait_fire_25": {"id": "trait_fire_25", "name": "灼烧强化·大师", "rarity": "super",
                      "group": "fire_boost", "repeatable": False},
    "trait_fire_35": {"id": "trait_fire_35", "name": "灼烧强化·宗师", "rarity": "super",
                      "group": "fire_boost", "repeatable": False},
    "trait_poison_15": {"id": "trait_poison_15", "name": "剧毒强化·精", "rarity": "super",
                        "group": "venom_boost", "repeatable": False},   # 异系（TC-18）
}

# 配方注册表（kind=upgrade 四类配置实例 + 基础 craft 配方）
RECIPES: Dict[str, Mapping[str, Any]] = {
    # 珠升阶链（BEL-12/13：相邻档位逐级；单输入 count=3 且 gem=10 → jewel_upgrade，U-S1）
    "rcp_up_jewel1": {"id": "rcp_up_jewel1", "kind": "upgrade", "name": "珠三合一升阶（普通→精良）",
                      "inputs": [{"item": "jewel_atk_common", "count": 3}],
                      "cost": {"gem": 10}, "output": {"item": "jewel_atk_uncommon", "count": 1}},
    "rcp_up_jewel2": {"id": "rcp_up_jewel2", "kind": "upgrade", "name": "珠三合一升阶（精良→史诗）",
                      "inputs": [{"item": "jewel_atk_uncommon", "count": 3}],
                      "cost": {"gem": 10}, "output": {"item": "jewel_atk_rare", "count": 1}},
    "rcp_up_jewel3": {"id": "rcp_up_jewel3", "kind": "upgrade", "name": "珠三合一升阶（史诗→传说）",
                      "inputs": [{"item": "jewel_atk_rare", "count": 3}],
                      "cost": {"gem": 10}, "output": {"item": "jewel_atk_legendary", "count": 1}},
    # 成品合成（CMB-02：两成品+材料+宝石10 → 更强成品，两输入 → product_merge，U-S1）
    "rcp_product": {"id": "rcp_product", "kind": "upgrade", "name": "灭世爆弹合成",
                    "inputs": [{"item": "flame_bomb_plus", "count": 2},
                               {"item": "ash_core", "count": 1}],
                    "cost": {"gem": 10}, "output": {"item": "doomsday_bomb", "count": 1}},
    # 配方合成（CMB-03：combine_from 两已学配方 → 新配方解锁；combine_from → formula_merge，U-S1）
    "rcp_formula": {"id": "rcp_formula", "kind": "upgrade", "name": "配方合成·焰之奥义",
                    "combine_from": ["rcp_flame", "rcp_flame_plus"],
                    "cost": {"gem": 5}, "output": {"item": "flame_bomb_master", "count": 1}},
    # 特性合成（CMB-04：两同系特性经 input_ids 传入；gem=20 → trait_merge，U-S1）
    "rcp_trait": {"id": "rcp_trait", "kind": "upgrade", "name": "特性合成·灼烧奥义",
                  "inputs": [{"item": "alch_ember_crystal", "count": 1},
                             {"item": "alch_fire_essence", "count": 1}],
                  "cost": {"gem": 20}, "output": {"item": "trait_fire_35", "count": 1}},
    # 基础 craft 配方（已学表引用 + 配方合成输入 + 复制登记成本基准）
    "rcp_flame": {"id": "rcp_flame", "name": "火焰弹配方", "kind": "craft", "level": 5,
                  "materials": [{"id": "alch_ember_crystal", "count": 1}],
                  "cost": {"coins": 200}, "output": {"item": "flame_bomb", "count": 1}},
    "rcp_flame_plus": {"id": "rcp_flame_plus", "name": "烈焰弹·改配方", "kind": "craft", "level": 8,
                       "materials": [{"id": "alch_fire_essence", "count": 1},
                                     {"id": "ash_core", "count": 1}],
                       "cost": {"coins": 350}, "output": {"item": "flame_bomb_plus", "count": 1}},
    # 复制登记成本基准（DUP-03：⌊cost.coins×20%⌋ = ⌊100×0.2⌋ = 20 宝石/份，拍板④）
    "rcp_mana": {"id": "rcp_mana", "name": "魔力药水配方", "kind": "craft", "level": 1,
                 "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
                 "cost": {"coins": 100}, "output": {"item": "mana_potion", "count": 1}},
    # TC-09：炼金成品登记拒绝（成本基准配方存在，但物品带 traits → 非标准版）
    "rcp_advanced": {"id": "rcp_advanced", "name": "精良火焰弹配方", "kind": "craft", "level": 10,
                     "materials": [{"id": "alch_ember_crystal", "count": 2}],
                     "cost": {"coins": 300},
                     "output": {"item": "alch_advanced_potion", "count": 1}},
    # TC-09 正例：标准珠复制（标准珠 quality+base_effects 无 traits → 可登记复制）
    "rcp_bead": {"id": "rcp_bead", "name": "标准珠配方", "kind": "craft", "level": 1,
                 "materials": [{"id": "ash_core", "count": 1}],
                 "cost": {"coins": 100}, "output": {"item": "jewel_atk_common", "count": 1}},
}

# 珠插槽定义（SOCK-01/J-1：slots.json 珠插槽条目归一映射；槽位 0 起）
SLOT_DEFS: Dict[str, list] = {
    "short_sword": [{"slot_level": 1}],                 # 1 级槽：只装普通（TC-20）
    "sword": [{"slot_level": 2}, {"slot_level": 2}],    # 2 级槽：精良及以下（TC-20/21）
    "legend_sword": [{"slot_level": 3}, {"slot_level": 3}],  # 3 级槽：全部含传说（TC-21）
}

# settings.alchemy 段（UpgradeEngine 扁平 gem 费率 + AlchemyRegister 复制费率 + JewelSystem 珠表）
SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "mode": "full",
        "max_qty": 2147483647,                # 拍板⑤（TC-11 测试用 max_qty 覆盖）
        "gem_diminish": [{"n": 2, "mult": 0.5}, {"n": 3, "mult": 0.25}],  # BEL-10
        "战斗道具": {"强度公式": "技能×(1+0.4×冷却数)", "珠触发上限": 3},      # BEL-11
        "gem.珠升阶": 10,                     # BEL-12/L230
        "gem.成品合成": 10,                   # CMB-02/L226
        "gem.配方合成": 5,                    # CMB-03/L227
        "gem.特性合成": 20,                   # CMB-04/L229
        "gem.复制": 0.2,                      # DUP-03/L419（拍板④）
        "gem.复制额外": 0,                    # DUP-03 可配额外消耗（AR-4）
    },
}


def _alchemy_node(level: int = 5) -> dict:
    """炼金职业节点（level=档位索引 0~6，对齐 proficiency dict；专家3 大师4 宗师5）。"""
    return {"level": level, "exp": 0, "sp_earned": 0, "sp_used": 0, "unlocks": {}}


def _equipment() -> Dict[str, dict]:
    """装备珠插槽桶（J-2：ctx["equipment"][equip_id]["jewels"] = {slot_index: 快照}）。"""
    return {"sword": {"jewels": {}}, "short_sword": {"jewels": {}},
            "legend_sword": {"jewels": {}}}


def make_ctx(
    *,
    level: int = 5,
    gem: int = 500,
    held: Optional[Mapping[str, int]] = None,
    in_battle: bool = False,
    recipes: Optional[Mapping[str, Any]] = None,
    max_qty: int = 2147483647,
    **over: Any,
) -> MutableMapping[str, Any]:
    """构造全字段珠/合成/复制 ctx（hook 注入 add_item/remove_item/count_item 就地改写背包）。

    每场景新造避免互污染；recipes 可覆盖（TC-03 禁跳级 recipe 单独注册）；max_qty 可配
    （TC-11 超限提示不拦）。
    """
    inv: Dict[str, int] = dict(held) if held else {}

    def add_item(item_id: Any, count: int = 1, bound: bool = False) -> bool:
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

    settings = copy.deepcopy(SETTINGS)
    settings["alchemy"]["max_qty"] = max_qty
    base: MutableMapping[str, Any] = {
        "qid": "u1",
        "proficiency": {"alchemy": _alchemy_node(level)},
        "currencies": {"coins": 1000, "gem": gem},
        "inventory": inv,
        "items": ITEMS,
        "traits": TRAITS,
        "recipe": recipes if recipes is not None else RECIPES,
        "slot_defs": SLOT_DEFS,
        "equipment": _equipment(),
        "settings": settings,
        "add_item": add_item,
        "remove_item": remove_item,
        "count_item": count_item,
    }
    if in_battle:
        base["in_battle"] = True
    base.update(over)
    return base


async def _register_mana(ctx: MutableMapping[str, Any]) -> None:
    """预登记魔力药水（TC-07~11 前置：登记表落 ctx["registered"]，成本快照冻结）。"""
    out = await cmd_register(parse_command("/登记 魔力药水", whitelist=W), ctx)
    assert "已登记 魔力药水" in out


# ---------------------------------------------------------------------------
# TC-01~06 珠升阶链（BEL-12/13/14，无职业硬门槛 拍板③）
# ---------------------------------------------------------------------------
async def test_tc01_jewel_up_success() -> None:
    """TC-01 正例：3×攻击珠·普通 + 宝石10 → 精良攻击珠×1，base_effects 原数值不变，宝石 -10。"""
    ctx = make_ctx(level=0, gem=100, held={"jewel_atk_common": 3})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx)
    assert "攻击珠·精良" in out and "合成成功" in out
    assert ctx["inventory"]["jewel_atk_common"] == 0
    assert ctx["inventory"]["jewel_atk_uncommon"] == 1
    assert ctx["currencies"]["gem"] == 90
    # BEL-12「原数值不变」：升阶后 base_effects 恒 atk:3（档位上升、数值不变）
    assert ITEMS["jewel_atk_uncommon"]["base_effects"] == {"atk": 3}


async def test_tc03_jewel_up_skip_tier_rejected() -> None:
    """TC-03 反例：组合表预置「普通→史诗」越级 → 禁跳级拒绝（jewel_skip_tier 透传），零消耗。"""
    skip = {"id": "rcp_up_skip", "kind": "upgrade", "name": "禁跳级（普通→史诗）",
            "inputs": [{"item": "jewel_atk_common", "count": 3}],
            "cost": {"gem": 10}, "output": {"item": "jewel_atk_rare", "count": 1}}
    ctx = make_ctx(level=0, gem=100, held={"jewel_atk_common": 3},
                   recipes={"rcp_up_skip": skip})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx)
    assert "禁跳级" in out
    assert ctx["inventory"]["jewel_atk_common"] == 3   # 珠零消耗
    assert ctx["currencies"]["gem"] == 100             # 宝石零消耗


async def test_tc03_jewel_up_legendary_endpoint_rejected() -> None:
    """TC-03 反例：3×传说 → 链终点无可再升 → 未找到升阶配方拒绝。"""
    ctx = make_ctx(level=0, gem=100, held={"jewel_atk_legendary": 3})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·传说", whitelist=W), ctx)
    assert "未找到" in out and "珠升阶配方" in out
    assert ctx["inventory"]["jewel_atk_legendary"] == 3


async def test_tc04_jewel_up_mixed_tier_or_id_rejected() -> None:
    """TC-04 反例：混档（普通×2+精良×1）/混 ID（攻击×2+防御×1）→ 须 3×同档同 ID → 材料不足全拒。"""
    ctx = make_ctx(level=0, gem=100,
                   held={"jewel_atk_common": 2, "jewel_atk_uncommon": 1})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx)
    assert "材料不足" in out
    assert ctx["inventory"]["jewel_atk_common"] == 2
    assert ctx["currencies"]["gem"] == 100
    # 混 ID：同档不同 ID（BEL-14 须同 ID）
    ctx2 = make_ctx(level=0, gem=100,
                    held={"jewel_atk_common": 2, "jewel_def_common": 1})
    out2 = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx2)
    assert "材料不足" in out2
    assert ctx2["inventory"]["jewel_atk_common"] == 2


async def test_tc05_jewel_up_gem_insufficient_rejected() -> None:
    """TC-05 反例：宝石 5/10 → 资源不足全拒（错误模板「宝石不足」口径），珠与宝石均不消耗。"""
    ctx = make_ctx(level=0, gem=5, held={"jewel_atk_common": 3})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx)
    assert "资源不足" in out and "宝石" in out
    assert ctx["inventory"]["jewel_atk_common"] == 3
    assert ctx["currencies"]["gem"] == 5


async def test_tc06_jewel_up_no_professional_gate() -> None:
    """TC-06 正例：见习（level 0）→ 珠升阶可执行（拍板③：无职业硬门槛，准入靠槽级 SOCK-02）。"""
    ctx = make_ctx(level=0, gem=100, held={"jewel_atk_common": 3})
    out = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx)
    assert "合成成功" in out
    assert ctx["currencies"]["gem"] == 90
    # 无 proficiency 节点（等级兜底 0）同样可执行
    ctx2 = make_ctx(gem=100, held={"jewel_atk_common": 3})
    del ctx2["proficiency"]
    out2 = await cmd_jewel_up(parse_command("/珠升阶 攻击珠·普通", whitelist=W), ctx2)
    assert "合成成功" in out2


# ---------------------------------------------------------------------------
# TC-07~11 复制（DUP-01~06，大师门槛）
# ---------------------------------------------------------------------------
async def test_tc07_copy_unregistered_reject_then_register() -> None:
    """TC-07：未登记 /复制 → 「未登记复制」拒绝；/登记 → 登记表落点；登记后可复制。"""
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 50, "herb": 20})
    out = await cmd_copy(parse_command("/复制 魔力药水", whitelist=W), ctx)
    assert "未登记复制" in out
    r = await cmd_register(parse_command("/登记 魔力药水", whitelist=W), ctx)
    assert "已登记 魔力药水" in r
    assert "mana_potion" in ctx["registered"]        # DUP-06 登记表持久化落点
    assert ctx["registered"]["mana_potion"]["item_id"] == "mana_potion"
    assert ctx["registered"]["mana_potion"]["cost_snapshot"]["gem"] == 20  # ⌊100×20%⌋
    out2 = await cmd_copy(parse_command("/复制 魔力药水", whitelist=W), ctx)
    assert "魔力药水 ×1 复制完成" in out2


async def test_tc08_copy_consume_and_standard_output() -> None:
    """TC-08：/复制 魔力药水*10 → 消耗 ⌊cost.coins×20%⌋=20 宝石/份 + 材料×10 → 标准版×10 入包。"""
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 50, "herb": 20})
    await _register_mana(ctx)
    out = await cmd_copy(parse_command("/复制 魔力药水*10", whitelist=W), ctx)
    assert "魔力药水 ×10 复制完成" in out
    assert ctx["currencies"]["gem"] == 500 - 20 * 10       # 宝石 ×200（拍板④）
    assert ctx["inventory"]["water_crystal"] == 0          # 水结晶 ×50
    assert ctx["inventory"]["herb"] == 0                   # 草药 ×20
    assert ctx["inventory"]["mana_potion"] == 10           # 标准版量产


async def test_tc09_register_alchemy_product_rejected() -> None:
    """TC-09：/登记 炼金成品（带 traits 品质浮动）→ 非标准版拒绝；已登记标准珠 → 复制成功。"""
    ctx = make_ctx(level=4, gem=500)
    out = await cmd_register(parse_command("/登记 精良火焰弹", whitelist=W), ctx)
    assert "非标准版" in out
    assert "alch_advanced_potion" not in ctx.get("registered", {})
    # 标准珠（quality+base_effects 无 traits）→ 可登记 + 可复制（DUP-04 标准版量产）
    ctx2 = make_ctx(level=4, gem=500, held={"ash_core": 5})
    r = await cmd_register(parse_command("/登记 攻击珠·普通", whitelist=W), ctx2)
    assert "已登记 攻击珠·普通" in r
    out2 = await cmd_copy(parse_command("/复制 攻击珠·普通", whitelist=W), ctx2)
    assert "攻击珠·普通 ×1 复制完成" in out2
    assert ctx2["inventory"]["jewel_atk_common"] == 1


async def test_tc10_copy_materials_gem_shortfall_all_rejected() -> None:
    """TC-10：材料缺 水结晶×5 或 宝石不足 → 全拒差异（「缺水结晶×48」/「缺宝石 190」），零消耗。"""
    # 材料不足：水结晶 2/50 → 全拒 + 差异
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 2, "herb": 20})
    await _register_mana(ctx)
    out = await cmd_copy(parse_command("/复制 魔力药水*10", whitelist=W), ctx)
    assert "材料不足" in out and "缺" in out and "水结晶" in out
    assert ctx["currencies"]["gem"] == 500                     # 宝石零消耗
    assert ctx["inventory"].get("mana_potion", 0) == 0         # 零产出
    # 宝石不足：宝石 10/200 → 全拒 + 差异
    ctx2 = make_ctx(level=4, gem=10, held={"water_crystal": 50, "herb": 20})
    await _register_mana(ctx2)
    out2 = await cmd_copy(parse_command("/复制 魔力药水*10", whitelist=W), ctx2)
    assert "材料不足" in out2 and "宝石" in out2
    assert ctx2["inventory"]["water_crystal"] == 50           # 材料零消耗


async def test_tc11_copy_over_limit_advisory_not_block() -> None:
    """TC-11：数量超限（max_qty=5 请求 10）→ 「最多一次使用 5 个」提示不拦（拍板⑤）、截断执行。"""
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 50, "herb": 20}, max_qty=5)
    await _register_mana(ctx)
    out = await cmd_copy(parse_command("/复制 魔力药水*10", whitelist=W), ctx)
    assert "最多一次使用 5 个" in out
    assert "魔力药水 ×5 复制完成" in out          # 截断执行量 = 上限
    assert ctx["inventory"]["mana_potion"] == 5
    assert ctx["currencies"]["gem"] == 500 - 20 * 5   # 按 5 份消耗


# ---------------------------------------------------------------------------
# TC-12~19 成品/配方/特性合成（CMB-02~06）
# ---------------------------------------------------------------------------
async def test_tc12_product_merge_success() -> None:
    """TC-12 正例：宗师 + /成品合成 烈焰弹·改 烈焰弹·改 → 灭世爆弹，宝石 -10 + 材料扣除。"""
    ctx = make_ctx(level=5, gem=100, held={"flame_bomb_plus": 2, "ash_core": 1})
    out = await cmd_product_merge(
        parse_command("/成品合成 烈焰弹·改 烈焰弹·改", whitelist=W), ctx
    )
    assert "灭世爆弹" in out and "合成成功" in out
    assert ctx["currencies"]["gem"] == 90
    assert ctx["inventory"]["flame_bomb_plus"] == 0
    assert ctx["inventory"]["ash_core"] == 0
    assert ctx["inventory"]["doomsday_bomb"] == 1


async def test_tc13_product_merge_level_or_gem_rejected() -> None:
    """TC-13 反例：精通 → 等级不足；宗师但宝石<10 → 资源不足，输入成品不消耗。"""
    ctx = make_ctx(level=2, gem=100, held={"flame_bomb_plus": 2, "ash_core": 1})
    out = await cmd_product_merge(
        parse_command("/成品合成 烈焰弹·改 烈焰弹·改", whitelist=W), ctx
    )
    assert out == "❌ 等级不足"
    ctx2 = make_ctx(level=5, gem=5, held={"flame_bomb_plus": 2, "ash_core": 1})
    out2 = await cmd_product_merge(
        parse_command("/成品合成 烈焰弹·改 烈焰弹·改", whitelist=W), ctx2
    )
    assert "资源不足" in out2 and "宝石" in out2
    assert ctx2["inventory"]["flame_bomb_plus"] == 2      # 输入成品零消耗
    assert ctx2["inventory"]["ash_core"] == 1
    assert ctx2["currencies"]["gem"] == 5


async def test_tc14_formula_merge_success_and_idempotent() -> None:
    """TC-14 正例：专家 + 两配方已学 → 组合表命中解锁新配方，宝石 -5；已解锁幂等 ATO-05。"""
    ctx = make_ctx(level=3, gem=100, upgrade_unlocks={
        "rcp_flame": {"source": "craft"}, "rcp_flame_plus": {"source": "craft"}})
    out = await cmd_formula_merge(
        parse_command("/配方合成 火焰弹配方 烈焰弹·改配方", whitelist=W), ctx
    )
    assert "解锁新配方" in out and "flame_bomb_master" in out
    assert ctx["currencies"]["gem"] == 95
    assert "flame_bomb_master" in ctx["upgrade_unlocks"]   # 组合表预置新配方点亮
    # ATO-05 幂等：已解锁 → 提示已解锁，不重复扣宝石
    out2 = await cmd_formula_merge(
        parse_command("/配方合成 火焰弹配方 烈焰弹·改配方", whitelist=W), ctx
    )
    assert "已解锁" in out2 and "无需重复合成" in out2
    assert ctx["currencies"]["gem"] == 95                  # 宝石不重复扣


async def test_tc15_formula_merge_unlearned_rejected() -> None:
    """TC-15 反例：两配方未全部习得（其一不在 upgrade_unlocks）→ 拒绝，零消耗。"""
    ctx = make_ctx(level=3, gem=100, upgrade_unlocks={"rcp_flame": {"source": "craft"}})
    out = await cmd_formula_merge(
        parse_command("/配方合成 火焰弹配方 烈焰弹·改配方", whitelist=W), ctx
    )
    assert "未全部习得" in out and "rcp_flame_plus" in out
    assert ctx["currencies"]["gem"] == 100                 # 零消耗


async def test_tc16_formula_merge_expert_gate() -> None:
    """TC-16：正式/精通 → 等级不足拒绝；专家 → 门槛过（进引擎资源校验）。"""
    ctx = make_ctx(level=1, gem=100, upgrade_unlocks={
        "rcp_flame": {}, "rcp_flame_plus": {}})
    out = await cmd_formula_merge(
        parse_command("/配方合成 火焰弹配方 烈焰弹·改配方", whitelist=W), ctx
    )
    assert out == "❌ 等级不足"
    ctx2 = make_ctx(level=3, gem=0, upgrade_unlocks={
        "rcp_flame": {}, "rcp_flame_plus": {}})
    out2 = await cmd_formula_merge(
        parse_command("/配方合成 火焰弹配方 烈焰弹·改配方", whitelist=W), ctx2
    )
    assert out2 != "❌ 等级不足"                           # 门槛已过
    assert "资源不足" in out2                              # 引擎宝石校验拦截


async def test_tc17_trait_merge_success() -> None:
    """TC-17 正例：宗师 + 两同系特性 → 更高位特性（灼烧强化·宗师），宝石 -20 + 材料扣除。"""
    ctx = make_ctx(level=5, gem=100, held={"alch_ember_crystal": 1, "alch_fire_essence": 1})
    out = await cmd_trait_merge(
        parse_command("/特性合成 灼烧强化·精 灼烧强化·大师", whitelist=W), ctx
    )
    assert "灼烧强化·宗师" in out and "更高位特性" in out   # 产出 = trait_fire_35
    assert ctx["currencies"]["gem"] == 80
    assert ctx["inventory"]["alch_ember_crystal"] == 0
    assert ctx["inventory"]["alch_fire_essence"] == 0


async def test_tc18_trait_merge_different_family_rejected() -> None:
    """TC-18 反例：非同系特性（fire_boost + venom_boost）→ 拒绝（GU-42 透传），零消耗。"""
    ctx = make_ctx(level=5, gem=100, held={"alch_ember_crystal": 1, "alch_fire_essence": 1})
    out = await cmd_trait_merge(
        parse_command("/特性合成 灼烧强化·精 剧毒强化·精", whitelist=W), ctx
    )
    assert "非同系" in out
    assert ctx["currencies"]["gem"] == 100
    assert ctx["inventory"]["alch_ember_crystal"] == 1


async def test_tc19_trait_merge_expert_rejected() -> None:
    """TC-19 反例：专家 → 特性合成等级不足拒绝（宗师解锁 CMB-04）。"""
    ctx = make_ctx(level=3, gem=100, held={"alch_ember_crystal": 1, "alch_fire_essence": 1})
    out = await cmd_trait_merge(
        parse_command("/特性合成 灼烧强化·精 灼烧强化·大师", whitelist=W), ctx
    )
    assert out == "❌ 等级不足"


# ---------------------------------------------------------------------------
# TC-20~23 镶嵌 / 拆珠（SOCK-02/03/05，通用无职业门槛）
# ---------------------------------------------------------------------------
async def test_tc20_mount_success() -> None:
    """TC-20 正例：长剑（2 级槽）镶 精良珠 / 短剑（1 级槽）镶 普通珠 → 成功（槽级≥珠档）。"""
    ctx = make_ctx(level=0, held={"jewel_atk_uncommon": 1})
    out = await cmd_mount(parse_command("/镶嵌 攻击珠·精良 长剑", whitelist=W), ctx)
    assert "已镶嵌" in out
    assert ctx["inventory"]["jewel_atk_uncommon"] == 0
    snap = ctx["equipment"]["sword"]["jewels"][0]
    assert snap["jewel_id"] == "jewel_atk_uncommon"
    assert snap["quality"] == "uncommon"
    assert snap["slot_level"] == 2
    assert snap["bound_to"] == "u1"                        # SOCK-04 珠随装备绑定角色
    # 1 级槽装普通（BEL-03：1 级=只普通）
    ctx2 = make_ctx(level=0, held={"jewel_atk_common": 1})
    out2 = await cmd_mount(parse_command("/镶嵌 攻击珠·普通 短剑", whitelist=W), ctx2)
    assert "已镶嵌" in out2
    assert ctx2["equipment"]["short_sword"]["jewels"][0]["jewel_id"] == "jewel_atk_common"


async def test_tc21_mount_slot_too_low_rejected() -> None:
    """TC-21 反例：长剑仅 2 级槽 → 传说珠槽级不足拒绝（需 3 级槽）；3 级槽装备可嵌。"""
    ctx = make_ctx(level=0, held={"jewel_atk_legendary": 1})
    out = await cmd_mount(parse_command("/镶嵌 攻击珠·传说 长剑", whitelist=W), ctx)
    assert "槽级不足" in out
    assert ctx["inventory"]["jewel_atk_legendary"] == 1    # 珠未被消耗
    assert ctx["equipment"]["sword"]["jewels"] == {}       # 槽位未写入
    # 3 级槽（传说之剑）→ 传说珠可嵌（BEL-03：3 级=全部）
    ctx2 = make_ctx(level=0, held={"jewel_atk_legendary": 1})
    out2 = await cmd_mount(parse_command("/镶嵌 攻击珠·传说 传说之剑", whitelist=W), ctx2)
    assert "已镶嵌" in out2
    assert ctx2["equipment"]["legend_sword"]["jewels"][0]["quality"] == "legendary"


async def test_tc22_unmount_lossless() -> None:
    """TC-22 正例：/拆珠 长剑 1 → 珠无损返还（原档原特性），槽位空闲可再嵌、不影响其它槽珠。"""
    ctx = make_ctx(level=0, held={"jewel_atk_uncommon": 1})
    await cmd_mount(parse_command("/镶嵌 攻击珠·精良 长剑", whitelist=W), ctx)
    assert ctx["inventory"]["jewel_atk_uncommon"] == 0
    out = await cmd_unmount(parse_command("/拆珠 长剑 1", whitelist=W), ctx)
    assert "无损拆下" in out
    assert ctx["inventory"]["jewel_atk_uncommon"] == 1     # 原档原特性返还
    assert ctx["equipment"]["sword"]["jewels"] == {}       # 槽位空闲可再嵌
    # 多槽装备：拆 1 号槽不影响 2 号槽珠（SOCK-03）
    ctx2 = make_ctx(level=0, held={"jewel_atk_uncommon": 1, "jewel_atk_common": 1})
    await cmd_mount(parse_command("/镶嵌 攻击珠·精良 长剑", whitelist=W), ctx2)   # slot0
    await cmd_mount(parse_command("/镶嵌 攻击珠·普通 长剑", whitelist=W), ctx2)   # slot1
    await cmd_unmount(parse_command("/拆珠 长剑 1", whitelist=W), ctx2)            # 拆 slot0
    assert 0 not in ctx2["equipment"]["sword"]["jewels"]
    assert ctx2["equipment"]["sword"]["jewels"][1]["jewel_id"] == "jewel_atk_common"


async def test_tc23_mount_unmount_rejected_in_battle() -> None:
    """TC-23 反例：战斗中 /镶嵌 /拆珠 → 拒绝（SOCK-05/BEL-09 战斗中不可插拔），珠零消耗。"""
    ctx = make_ctx(level=0, held={"jewel_atk_common": 1}, in_battle=True)
    out = await cmd_mount(parse_command("/镶嵌 攻击珠·普通 长剑", whitelist=W), ctx)
    assert "战斗中不可插拔" in out
    assert ctx["inventory"]["jewel_atk_common"] == 1
    out2 = await cmd_unmount(parse_command("/拆珠 长剑 1", whitelist=W), ctx)
    assert "战斗中不可插拔" in out2


# ---------------------------------------------------------------------------
# 防御 / 缺参 TPL-12 / 数量兜底
# ---------------------------------------------------------------------------
async def test_missing_arg_tpl12() -> None:
    """负例：各指令缺参 → TPL-12（指令不正确）。"""
    ctx = make_ctx()
    for cmd, handler in (
        (MOUNT_CMD, cmd_mount), (UNMOUNT_CMD, cmd_unmount), (JEWEL_UP_CMD, cmd_jewel_up),
        (PRODUCT_MERGE_CMD, cmd_product_merge), (FORMULA_MERGE_CMD, cmd_formula_merge),
        (TRAIT_MERGE_CMD, cmd_trait_merge), (REGISTER_CMD, cmd_register), (COPY_CMD, cmd_copy),
    ):
        out = await handler(parse_command(f"/{cmd}", whitelist=W), ctx)
        assert "指令不正确" in out, (cmd, out)


async def test_mount_jewel_not_found() -> None:
    """负例：/镶嵌 非装饰珠 → 装饰珠不存在；/镶嵌 装备不存在 → 装备不存在。"""
    ctx = make_ctx(level=0, held={})
    out = await cmd_mount(parse_command("/镶嵌 烈焰弹·改 长剑", whitelist=W), ctx)
    assert "装饰珠不存在" in out
    ctx2 = make_ctx(level=0, held={"jewel_atk_common": 1})
    out2 = await cmd_mount(parse_command("/镶嵌 攻击珠·普通 不存在之剑", whitelist=W), ctx2)
    assert "装备不存在" in out2


async def test_copy_qty_fallback_parse() -> None:
    """P-11 数量兜底：解析器未结构化 qty 时回落 args[0] 内 `*N`（_copy_qty 口径）。"""
    parsed = parse_command("/复制 魔力药水*3", whitelist=W)
    parsed.qty = None                                     # 模拟解析器未登记 quantity_commands
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 50, "herb": 20})
    await _register_mana(ctx)
    out = await cmd_copy(parsed, ctx)
    assert "魔力药水 ×3 复制完成" in out
    assert ctx["inventory"]["mana_potion"] == 3


# ---------------------------------------------------------------------------
# 装配：register_alchemy_commands 注册 8 指令 + ctx 注入 handler
# ---------------------------------------------------------------------------
async def test_register_combine_commands() -> None:
    """装配：注册 镶嵌/拆珠/珠升阶/成品合成/配方合成/特性合成/登记/复制 8 条 CommandSpec。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: dict(make_ctx()))
    for name in (MOUNT_CMD, UNMOUNT_CMD, JEWEL_UP_CMD, PRODUCT_MERGE_CMD,
                 FORMULA_MERGE_CMD, TRAIT_MERGE_CMD, REGISTER_CMD, COPY_CMD):
        assert router.has(name), name
        spec = router.get(name)
        assert spec is not None and spec.whitelisted, name
    # 既有指令不因本批追加而丢失
    for name in (SYNTH_CMD, ALCHEMY_CMD, FEED_CMD, INHERIT_CMD, INHERIT_SUPER_CMD,
                 CONFIRM_CMD, ABANDON_CMD, RESUME_CMD, DECOMPOSE_CMD):
        assert router.has(name), name


async def test_register_copy_handler_injectable_ctx() -> None:
    """装配：/复制 handler 支持 k.get("ctx") 注入（async 处理器 await 执行，runner 口径）。"""
    router = Router()
    register_alchemy_commands(router, make_context=lambda p: {})
    spec = router.get(COPY_CMD)
    assert spec is not None and spec.handler is not None
    ctx = make_ctx(level=4, gem=500, held={"water_crystal": 50, "herb": 20})
    await _register_mana(ctx)
    out = await spec.handler(parse_command("/复制 魔力药水*2", whitelist=W), ctx=ctx)
    assert "魔力药水 ×2 复制完成" in out
