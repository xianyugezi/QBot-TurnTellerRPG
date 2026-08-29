"""升级合成引擎单测（M8 批2·路2B · qbot_rpg/core/upgrade.py）——kind=upgrade 通用执行器。

文件：tests/unit/test_upgrade.py
创建：2026-08-29
作者：Hermes 子agent-2B
功能：UpgradeEngine 升级合成引擎单测——resolve_upgrade_recipe 解析；珠三合一升阶（3×同档同
      ID+宝石10→档+1 成功；混档/不同 ID→拒绝；禁跳级）；成品合成（原子：缺材料/缺宝石→全拒
      差异；成功产出）；配方合成（组合命中→永久解锁+扣宝石；未命中→拒绝；重复→already 提示
      不重复扣）；特性合成（同系成功/异系拒绝/宝石不足/group 互斥冲突拒绝）。每实例正反例。

依据：docs/m8_batch_plan.md 批2 路2B + docs/m8_contract_指令契约.md §9/§12/§13（F-09/F-12/
      F-13/ATO-05）+ docs/细化/细化_2c4e_品质与特性.md TSC-15~18 + docs/m8_contract_核心机制.md
      §六 6.3（BATCH 原子性）+ 拍板③（珠升阶无职业硬门槛）。

测试风格对齐 tests/unit/test_quality.py / test_reward.py：纯 pytest、零 NoneBot、构造 ctx 直测
（items/currencies/count_item/remove_item/add_item/traits/target_traits/upgrade_unlocks hook
模式），断言具体数值/状态/消息。

覆盖矩阵（每条正例 + 负例）：
  R1  resolve_upgrade_recipe：4 实例 subtype 推断 + 配置归一 + 非 upgrade → None
  J1  珠三合一升阶正例：3×同档同 ID+宝石10 → 档+1 产出（联动 quality）
  J2  珠混档/不同 ID → 拒绝（输入形态 / input_ids 失配）
  J3  珠禁跳级：common×3 → rare 产出 → 拒绝 skip_tier
  J4  珠宝石不足 / 珠数量不足 → 全拒+差异，零副作用
  P1  成品合成正例：两成品+材料+宝石10 → 更强成品（原子提交）
  P2  成品合成缺材料 / 缺宝石 → 全拒+差异，零副作用（原子全拒）
  P3  成品合成 add_item hook 失败 → 回滚零副作用（U-A1）
  F1  配方合成正例：组合命中 → 永久解锁新配方 + 扣宝石5
  F2  配方合成未命中（无组合无 output）→ 拒绝「没有已知组合」
  F3  配方合成两配方未全学 → 拒绝
  F4  配方合成重复（已解锁）→ already 提示不重复扣宝石（ATO-05 幂等）
  F5  组合表 list 形态归一（U-C1）+ 缺省 gem 费率 / settings 覆盖
  T1  特性合成正例：两同系特性+宝石20+材料 → 更高位特性落位（原两特性被消耗）
  T2  特性合成异系 → 拒绝
  T3  特性合成宝石不足 → 拒绝
  T4  特性合成产出与成品已带同组冲突（互斥组）→ 拒绝（F-13 落位复核）
  T5  特性合成产出 repeatable → 同组可共存不冲突
"""

from __future__ import annotations

from qbot_rpg.core.upgrade import (
    DEFAULT_GEM_COST,
    UpgradeEngine,
)

# ---------------------------------------------------------------------------
# 注册表 / 组合表 / 配方条目（对齐 content/test_demo 形态）
# ---------------------------------------------------------------------------

# 物品注册表：珠带 quality（U-J1 ① 档位联动）/ 成品 / 材料
ITEMS = {
    "jewel_burn_common": {"id": "jewel_burn_common", "name": "灼烧珠·普通", "quality": "common"},
    "jewel_burn_uncommon": {
        "id": "jewel_burn_uncommon", "name": "灼烧珠·精良", "quality": "uncommon",
    },
    "jewel_burn_rare": {"id": "jewel_burn_rare", "name": "灼烧珠·史诗", "quality": "rare"},
    "flame_bomb_plus": {"id": "flame_bomb_plus", "name": "烈焰弹·改", "quality": "rare"},
    "ash_core": {"id": "ash_core", "name": "灰烬核心"},
    "doomsday_bomb": {"id": "doomsday_bomb", "name": "灭世爆弹"},
    "alch_ember_crystal": {"id": "alch_ember_crystal", "name": "火晶石"},
    "alch_fire_essence": {"id": "alch_fire_essence", "name": "火之精粹"},
}

# 特性注册表（traits.json 语义：group/repeatable，U-T4）
TRAITS = {
    "trait_burn_boost": {
        "id": "trait_burn_boost", "name": "灼烧强化", "group": "fire_boost", "repeatable": False,
    },
    "trait_fire_15": {
        "id": "trait_fire_15", "name": "灼烧强化·精", "group": "fire_boost", "repeatable": False,
    },
    "trait_fire_25": {
        "id": "trait_fire_25", "name": "灼烧强化·大师", "group": "fire_boost", "repeatable": False,
    },
    "trait_poison_boost": {
        "id": "trait_poison_boost", "name": "剧毒强化", "group": "venom_boost", "repeatable": False,
    },
    "trait_heal_boost": {
        "id": "trait_heal_boost", "name": "回复强化", "group": "heal_boost", "repeatable": True,
    },
    "trait_heal_mp": {
        "id": "trait_heal_mp", "name": "魔力流转", "group": "heal_boost", "repeatable": True,
    },
    "trait_heal_plus": {
        "id": "trait_heal_plus", "name": "回复强化·精", "group": "heal_boost", "repeatable": True,
    },
    "trait_heal_super": {
        "id": "trait_heal_super", "name": "回复强化·大师",
        "group": "heal_boost", "repeatable": True,
    },
}

# 组合表（配方合成 F-12 / 特性合成 U-T3）：frozenset(2 id)→{output, condition}
COMBOS = {
    frozenset(("rcp_flame_bomb", "rcp_flame_bomb_plus")): {
        "output": "rcp_flame_bomb_master", "condition": None,
    },
    frozenset(("trait_burn_boost", "trait_fire_15")): {
        "output": "trait_fire_25", "condition": {"same_family": "fire_boost"},
    },
}

# 配方条目（批0 recipe.json kind=upgrade 形态）
RCP_JEWEL = {
    "id": "rcp_upgrade_jewel_burn1", "name": "灼烧珠升阶·精良", "kind": "upgrade",
    "inputs": [{"item": "jewel_burn_common", "count": 3}],
    "output": {"item": "jewel_burn_uncommon", "count": 1},
    "cost": {"coins": 0, "gem": 10},
}
RCP_JEWEL_MIX = {  # 混档：两输入条目不同珠 ID（显式 subtype 强制按珠升阶校验）
    "id": "rcp_upgrade_jewel_mix", "name": "灼烧珠升阶·混档(错误)", "kind": "upgrade",
    "subtype": "jewel_upgrade",
    "inputs": [
        {"item": "jewel_burn_common", "count": 2},
        {"item": "jewel_burn_uncommon", "count": 1},
    ],
    "output": {"item": "jewel_burn_rare", "count": 1},
    "cost": {"coins": 0, "gem": 10},
}
RCP_JEWEL_SKIP = {  # 禁跳级：common×3 → rare 产出（跳档）
    "id": "rcp_upgrade_jewel_skip", "name": "灼烧珠升阶·史诗(禁跳)", "kind": "upgrade",
    "inputs": [{"item": "jewel_burn_common", "count": 3}],
    "output": {"item": "jewel_burn_rare", "count": 1},
    "cost": {"coins": 0, "gem": 10},
}
RCP_PRODUCT = {
    "id": "rcp_upgrade_final_bomb", "name": "灭世爆弹合成", "kind": "upgrade",
    "inputs": [{"item": "flame_bomb_plus", "count": 2}, {"item": "ash_core", "count": 1}],
    "output": {"item": "doomsday_bomb", "count": 1},
    "cost": {"coins": 0, "gem": 10},
}
RCP_FORMULA = {
    "id": "rcp_upgrade_formula_merge", "name": "配方合成·焰之奥义", "kind": "upgrade",
    "combine_from": ["rcp_flame_bomb", "rcp_flame_bomb_plus"],
    "inputs": [
        {"item": "alch_fire_essence", "count": 1},
        {"item": "alch_ember_crystal", "count": 2},
    ],
    "output": {"item": "rcp_flame_bomb_master", "count": 1},
    "cost": {"coins": 0, "gem": 5},
}
RCP_FORMULA_NOCOMBO = {  # 未命中组合且无 output 兜底
    "id": "rcp_upgrade_formula_x", "name": "配方合成·未知", "kind": "upgrade",
    "combine_from": ["rcp_a", "rcp_b"],
    "inputs": [],
    "output": None,
    "cost": {"coins": 0, "gem": 5},
}
RCP_TRAIT = {
    "id": "rcp_upgrade_trait_merge", "name": "特性合成·灼烧奥义", "kind": "upgrade",
    "inputs": [
        {"item": "alch_ember_crystal", "count": 1},
        {"item": "alch_fire_essence", "count": 1},
    ],
    "output": {"item": "trait_fire_25", "count": 1},
    "cost": {"coins": 0, "gem": 20},
    "condition": {"same_family": "fire_boost"},
}
RCP_TRAIT_HEAL = {  # repeatable 系特性合成（产出可共存）
    "id": "rcp_upgrade_trait_heal", "name": "特性合成·回复奥义", "kind": "upgrade",
    "inputs": [{"item": "alch_ember_crystal", "count": 1}],
    "output": {"item": "trait_heal_plus", "count": 1},
    "cost": {"coins": 0, "gem": 20},
}


def make_ctx(
    inventory=None, currencies=None, target_traits=None, unlocks=None, **overrides
) -> dict:
    """默认 ctx：物品/特性注册表 + 背包 dict + hook（count/remove/add）+ 货币 + 解锁表。

    hook 就地改背包 dict（与 ctx["inventory"] 同引用），支持引擎进程内回滚断言。
    """
    inv = dict(inventory or {})

    def count_item(item_id: str) -> int:
        return int(inv.get(item_id, 0) or 0)

    def remove_item(item_id: str, count: int) -> bool:
        cur = int(inv.get(item_id, 0) or 0)
        if cur < count:
            return False
        inv[item_id] = cur - count
        return True

    def add_item(item_id: str, count: int, bound: bool) -> bool:
        inv[item_id] = int(inv.get(item_id, 0) or 0) + count
        return True

    ctx = {
        "items": dict(ITEMS),
        "inventory": inv,
        "count_item": count_item,
        "remove_item": remove_item,
        "add_item": add_item,
        "currencies": dict(currencies or {"coins": 0, "gem": 0}),
        "traits": dict(TRAITS),
        "upgrade_unlocks": dict(unlocks or {}),
        **overrides,
    }
    if target_traits is not None:
        ctx["target_traits"] = list(target_traits)
    return ctx


# ---------------------------------------------------------------------------
# R1  resolve_upgrade_recipe：子类型推断 + 配置归一
# ---------------------------------------------------------------------------
def test_r1_resolve_jewel_recipe() -> None:
    """R1 正例：珠升阶条目 → subtype=jewel_upgrade，inputs/cost/output 归一。"""
    eng = UpgradeEngine()
    cfg = eng.resolve_upgrade_recipe(RCP_JEWEL)
    assert cfg is not None
    assert cfg["kind"] == "upgrade"
    assert cfg["subtype"] == "jewel_upgrade"
    assert cfg["inputs"] == [{"item": "jewel_burn_common", "count": 3}]
    assert cfg["cost"] == {"coins": 0, "gem": 10}
    assert cfg["output"] == {"item": "jewel_burn_uncommon", "count": 1}
    assert cfg["combine_from"] == []


def test_r1_resolve_product_recipe() -> None:
    """R1 正例：成品合成条目 → subtype=product_merge。"""
    cfg = UpgradeEngine().resolve_upgrade_recipe(RCP_PRODUCT)
    assert cfg is not None and cfg["subtype"] == "product_merge"


def test_r1_resolve_formula_recipe() -> None:
    """R1 正例：combine_from 存在 → subtype=formula_merge，combine_from 保留。"""
    cfg = UpgradeEngine().resolve_upgrade_recipe(RCP_FORMULA)
    assert cfg is not None and cfg["subtype"] == "formula_merge"
    assert cfg["combine_from"] == ["rcp_flame_bomb", "rcp_flame_bomb_plus"]


def test_r1_resolve_trait_recipe() -> None:
    """R1 正例：gem=特性合成费率(20) → subtype=trait_merge，condition 保留。"""
    cfg = UpgradeEngine().resolve_upgrade_recipe(RCP_TRAIT)
    assert cfg is not None and cfg["subtype"] == "trait_merge"
    assert cfg["condition"] == {"same_family": "fire_boost"}


def test_r1_resolve_non_upgrade_returns_none() -> None:
    """R1 负例：kind=craft / 非 Mapping → None（防御）。"""
    eng = UpgradeEngine()
    assert eng.resolve_upgrade_recipe({"id": "x", "kind": "craft"}) is None
    assert eng.resolve_upgrade_recipe(None) is None
    assert eng.resolve_upgrade_recipe("not a mapping") is None


def test_r1_subtype_explicit_override() -> None:
    """R1 补充：显式 subtype 字段优先于结构推断（U-S1）。"""
    cfg = UpgradeEngine().resolve_upgrade_recipe({**RCP_PRODUCT, "subtype": "trait_merge"})
    assert cfg is not None and cfg["subtype"] == "trait_merge"


# ---------------------------------------------------------------------------
# J  珠三合一升阶（3×同档同 ID+宝石10→+1 阶；禁跳级；拍板③ 无职业硬门槛）
# ---------------------------------------------------------------------------
def test_j1_jewel_upgrade_success() -> None:
    """J1 正例：3×灼烧珠·普通+宝石10 → 灼烧珠·精良×1（档+1，联动 quality）。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 3},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_JEWEL)
    assert r["ok"] is True
    assert r["produced"] == {"item": "jewel_burn_uncommon", "count": 1}
    assert ctx["inventory"]["jewel_burn_common"] == 0  # 3 珠消耗
    assert ctx["inventory"]["jewel_burn_uncommon"] == 1  # 产出 1
    assert ctx["currencies"]["gem"] == 0  # 宝石 10 扣减
    assert "合成成功" in r["message"]


def test_j1_jewel_tier_linkage_via_quality() -> None:
    """J1 正例：档位联动 = 输入档序号+1（quality.tier_index/index_to_tier 换算，U-J1 ①）。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_uncommon": 3},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, {
        "id": "rcp_upgrade_jewel_burn2", "name": "灼烧珠升阶·史诗", "kind": "upgrade",
        "inputs": [{"item": "jewel_burn_uncommon", "count": 3}],
        "output": {"item": "jewel_burn_rare", "count": 1},
        "cost": {"coins": 0, "gem": 10},
    })
    assert r["ok"] is True
    assert ctx["inventory"]["jewel_burn_rare"] == 1
    assert ctx["inventory"]["jewel_burn_uncommon"] == 0


def test_j2_jewel_mixed_tier_rejected() -> None:
    """J2 负例：混档（两输入条目不同珠 ID）→ 拒绝 jewel_input_shape，零副作用。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 2, "jewel_burn_uncommon": 1},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_JEWEL_MIX)
    assert r["ok"] is False and r["reason"] == "jewel_input_shape"
    assert ctx["inventory"] == {"jewel_burn_common": 2, "jewel_burn_uncommon": 1}
    assert ctx["currencies"]["gem"] == 10  # 未扣


def test_j2_jewel_input_ids_mismatch_rejected() -> None:
    """J2 负例：input_ids 含不同 ID 珠 → 拒绝 jewel_input_mismatch（U-J2 防御）。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 3, "jewel_burn_uncommon": 1},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(
        ctx, RCP_JEWEL,
        input_ids=["jewel_burn_common", "jewel_burn_common", "jewel_burn_uncommon"],
    )
    assert r["ok"] is False and r["reason"] == "jewel_input_mismatch"


def test_j3_jewel_skip_tier_rejected() -> None:
    """J3 负例：禁跳级——common×3 直接产出 rare（跨档）→ 拒绝 jewel_skip_tier。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 3},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_JEWEL_SKIP)
    assert r["ok"] is False and r["reason"] == "jewel_skip_tier"
    assert ctx["inventory"]["jewel_burn_common"] == 3  # 零副作用
    assert ctx["currencies"]["gem"] == 10


def test_j4_jewel_insufficient_gem_rejected() -> None:
    """J4 负例：宝石不足 → 拒绝 cost_insufficient + 差异提示，零副作用。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 3},
        currencies={"coins": 0, "gem": 5},
    )
    r = eng.execute(ctx, RCP_JEWEL)
    assert r["ok"] is False and r["reason"] == "cost_insufficient"
    assert "宝石" in r["message"]  # 差异提示
    assert ctx["inventory"]["jewel_burn_common"] == 3


def test_j4_jewel_insufficient_inputs_rejected() -> None:
    """J4 负例：珠数量不足（仅 2 个）→ 拒绝 inputs_insufficient + 差异提示。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"jewel_burn_common": 2},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_JEWEL)
    assert r["ok"] is False and r["reason"] == "inputs_insufficient"
    assert "缺少" in r["message"]


def test_j5_jewel_no_job_gate() -> None:
    """J5 拍板③：引擎不设职业硬门槛——无任何职业/等级字段参与珠升阶判定（准入靠槽级 SOCK-02）。"""
    cfg = UpgradeEngine().resolve_upgrade_recipe(RCP_JEWEL)
    assert cfg is not None
    assert "level" not in cfg  # 引擎不消费 level（职业门槛归指令壳）
    # 引擎执行不涉及 proficiency/job 字段，直接成功
    ctx = make_ctx(inventory={"jewel_burn_common": 3}, currencies={"coins": 0, "gem": 10})
    r = UpgradeEngine().execute(ctx, RCP_JEWEL)
    assert r["ok"] is True


# ---------------------------------------------------------------------------
# P  成品合成（两成品+材料+宝石10→更强成品；原子提交 F-09）
# ---------------------------------------------------------------------------
def test_p1_product_merge_success() -> None:
    """P1 正例：2×烈焰弹·改+灰烬核心+宝石10 → 灭世爆弹×1（原子扣减+产出）。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"flame_bomb_plus": 2, "ash_core": 1},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_PRODUCT)
    assert r["ok"] is True
    assert r["produced"] == {"item": "doomsday_bomb", "count": 1}
    assert r["consumed"]["inputs"] == [
        {"item": "flame_bomb_plus", "count": 2}, {"item": "ash_core", "count": 1},
    ]
    assert ctx["inventory"]["flame_bomb_plus"] == 0
    assert ctx["inventory"]["ash_core"] == 0
    assert ctx["inventory"]["doomsday_bomb"] == 1
    assert ctx["currencies"]["gem"] == 0
    assert r["message"] == "✅ 灭世爆弹 合成成功（消耗 宝石×10）"  # M-09


def test_p2_product_missing_material_all_rejected() -> None:
    """P2 负例：缺材料（灰烬核心缺失）→ 全拒 + 差异提示，输入/宝石零扣（原子全拒）。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"flame_bomb_plus": 2},
        currencies={"coins": 0, "gem": 10},
    )
    r = eng.execute(ctx, RCP_PRODUCT)
    assert r["ok"] is False and r["reason"] == "inputs_insufficient"
    assert "灰烬核心" in r["message"]
    assert ctx["inventory"]["flame_bomb_plus"] == 2  # 未扣
    assert ctx["currencies"]["gem"] == 10  # 未扣


def test_p2_product_missing_gem_all_rejected() -> None:
    """P2 负例：缺宝石 → 拒绝 cost_insufficient + 差异提示，零副作用。"""
    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"flame_bomb_plus": 2, "ash_core": 1},
        currencies={"coins": 0, "gem": 5},
    )
    r = eng.execute(ctx, RCP_PRODUCT)
    assert r["ok"] is False and r["reason"] == "cost_insufficient"
    assert "宝石" in r["message"]
    assert ctx["inventory"]["flame_bomb_plus"] == 2
    assert ctx["currencies"]["gem"] == 5


def test_p3_product_add_hook_failure_rollback() -> None:
    """P3 工程补白 U-A1：add_item hook 失败 → 拒绝 add_item_failed + 回滚零副作用。"""
    def broken_add(item_id, count, bound):  # noqa: ANN001,ANN002,ANN003
        return False

    eng = UpgradeEngine()
    ctx = make_ctx(
        inventory={"flame_bomb_plus": 2, "ash_core": 1},
        currencies={"coins": 0, "gem": 10},
        add_item=broken_add,
    )
    r = eng.execute(ctx, RCP_PRODUCT)
    assert r["ok"] is False and r["reason"] == "add_item_failed"
    assert ctx["currencies"]["gem"] == 10  # 货币回滚
    assert ctx["inventory"]["flame_bomb_plus"] == 2  # 背包回滚（输入未扣）
    assert ctx["inventory"]["ash_core"] == 1


def test_p4_execute_non_upgrade_rejected() -> None:
    """P4 负例：非 kind=upgrade 配方 → 拒绝 not_upgrade（通用执行器入口校验）。"""
    eng = UpgradeEngine()
    r = eng.execute(make_ctx(), {"id": "x", "kind": "craft"})
    assert r["ok"] is False and r["reason"] == "not_upgrade"


# ---------------------------------------------------------------------------
# F  配方合成（两已学配方+宝石5→永久解锁；组合表 F-12；ATO-05 幂等）
# ---------------------------------------------------------------------------
def test_f1_formula_merge_unlock_success() -> None:
    """F1 正例：两已学配方组合命中 → 永久解锁新配方 + 扣宝石5。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        currencies={"coins": 0, "gem": 5},
        unlocks={
            "rcp_flame_bomb": {"source": "evolve"},
            "rcp_flame_bomb_plus": {"source": "evolve"},
        },
    )
    r = eng.execute(ctx, RCP_FORMULA)
    assert r["ok"] is True and r["produced"] == {"recipe": "rcp_flame_bomb_master"}
    assert ctx["currencies"]["gem"] == 0  # 宝石 5 扣减
    assert ctx["upgrade_unlocks"]["rcp_flame_bomb_master"]["source"] == "formula_merge"  # 永久解锁
    assert "解锁新配方" in r["message"]


def test_f2_formula_no_combo_rejected() -> None:
    """F2 负例：组合未命中且无 output 兜底 → 拒绝 formula_no_combo「没有已知组合」，不扣宝石。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        currencies={"coins": 0, "gem": 5},
        unlocks={"rcp_a": {"source": "evolve"}, "rcp_b": {"source": "evolve"}},
    )
    r = eng.execute(ctx, RCP_FORMULA_NOCOMBO)
    assert r["ok"] is False and r["reason"] == "formula_no_combo"
    assert "没有已知组合" in r["message"]
    assert ctx["currencies"]["gem"] == 5  # 未扣


def test_f3_formula_not_learned_rejected() -> None:
    """F3 负例：两配方未全部习得（GU-38）→ 拒绝 formula_not_learned。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        currencies={"coins": 0, "gem": 5},
        unlocks={"rcp_flame_bomb": {"source": "evolve"}},  # 缺 rcp_flame_bomb_plus
    )
    r = eng.execute(ctx, RCP_FORMULA)
    assert r["ok"] is False and r["reason"] == "formula_not_learned"
    assert ctx["currencies"]["gem"] == 5


def test_f4_formula_already_unlocked_no_rededuct() -> None:
    """F4 正例：重复合成（已解锁）→ already 提示，不重复扣宝石（ATO-05 幂等）。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        currencies={"coins": 0, "gem": 5},
        unlocks={
            "rcp_flame_bomb": {"source": "evolve"},
            "rcp_flame_bomb_plus": {"source": "evolve"},
            "rcp_flame_bomb_master": {"source": "formula_merge"},  # 已解锁
        },
    )
    r = eng.execute(ctx, RCP_FORMULA)
    assert r["ok"] is True and r["already"] is True
    assert "已解锁" in r["message"]
    assert ctx["currencies"]["gem"] == 5  # 宝石未扣（幂等）


def test_f5_combo_list_normalization() -> None:
    """F5 补充：组合表 list 形态归一（U-C1 [{a,b,output,condition},...]）同样命中。"""
    combos_list = [
        {
            "a": "rcp_flame_bomb", "b": "rcp_flame_bomb_plus",
            "output": "rcp_flame_bomb_master", "condition": None,
        },
    ]
    eng = UpgradeEngine(combos=combos_list)
    ctx = make_ctx(
        currencies={"coins": 0, "gem": 5},
        unlocks={
            "rcp_flame_bomb": {"source": "evolve"},
            "rcp_flame_bomb_plus": {"source": "evolve"},
        },
    )
    r = eng.execute(ctx, RCP_FORMULA)
    assert r["ok"] is True and r["produced"] == {"recipe": "rcp_flame_bomb_master"}


def test_f5_default_gem_fees_and_settings_override() -> None:
    """F5 补充：缺省 gem 费率（珠升阶10/成品合成10/配方合成5/特性合成20）+ settings 覆盖。"""
    eng = UpgradeEngine()
    assert eng._gem_cost("gem.珠升阶") == DEFAULT_GEM_COST["gem.珠升阶"] == 10
    assert eng._gem_cost("gem.成品合成") == 10
    assert eng._gem_cost("gem.配方合成") == 5
    assert eng._gem_cost("gem.特性合成") == 20
    eng2 = UpgradeEngine(settings={"gem.珠升阶": 15})
    assert eng2._gem_cost("gem.珠升阶") == 15
    # settings 覆盖费率影响子类型推断（U-S1）：gem=15 单输入×3 → jewel_upgrade
    cfg = eng2.resolve_upgrade_recipe({**RCP_JEWEL, "cost": {"coins": 0, "gem": 15}})
    assert cfg is not None and cfg["subtype"] == "jewel_upgrade"


# ---------------------------------------------------------------------------
# T  特性合成（两同系特性+宝石20+材料→更高位特性；F-13 / TSC-15~18）
# ---------------------------------------------------------------------------
def test_t1_trait_merge_success() -> None:
    """T1 正例：两同系特性（灼烧强化+灼烧强化·精）+宝石20+材料 → 灼烧强化·大师落位，
    原两特性消耗（TSC-17）。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1, "alch_fire_essence": 1},
        currencies={"coins": 0, "gem": 20},
        target_traits=["trait_burn_boost", "trait_fire_15"],
    )
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_burn_boost", "trait_fire_15"])
    assert r["ok"] is True
    assert r["produced"] == {"trait": "trait_fire_25"}
    assert ctx["currencies"]["gem"] == 0  # 宝石 20 扣减
    assert ctx["inventory"]["alch_ember_crystal"] == 0  # 材料消耗
    assert ctx["inventory"]["alch_fire_essence"] == 0
    assert ctx["target_traits"] == ["trait_fire_25"]  # 原两特性被消耗，产出落位
    assert "更高位特性" in r["message"]


def test_t1_trait_merge_recipe_output_fallback() -> None:
    """T1 补充：无组合命中时兜底 recipe output 字段（U-T3），同系按 condition.same_family。"""
    eng = UpgradeEngine()  # combos 空
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1, "alch_fire_essence": 1},
        currencies={"coins": 0, "gem": 20},
        target_traits=["trait_burn_boost", "trait_fire_15"],
    )
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_burn_boost", "trait_fire_15"])
    assert r["ok"] is True
    assert r["produced"] == {"trait": "trait_fire_25"}


def test_t2_trait_hetero_family_rejected() -> None:
    """T2 负例：异系（火系×毒系）→ 拒绝 trait_not_same_family（GU-42 非同系拒绝）。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1, "alch_fire_essence": 1},
        currencies={"coins": 0, "gem": 20},
        target_traits=[],
    )
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_fire_15", "trait_poison_boost"])
    assert r["ok"] is False and r["reason"] == "trait_not_same_family"
    assert ctx["currencies"]["gem"] == 20  # 未扣


def test_t2_trait_wrong_input_count_rejected() -> None:
    """T2 负例：输入特性数 ≠ 2 → 拒绝 trait_input_shape。"""
    eng = UpgradeEngine()
    ctx = make_ctx(currencies={"coins": 0, "gem": 20})
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_fire_15"])
    assert r["ok"] is False and r["reason"] == "trait_input_shape"


def test_t3_trait_insufficient_gem_rejected() -> None:
    """T3 负例：宝石不足（宝石 10 < 20）→ 拒绝 cost_insufficient，零副作用。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1, "alch_fire_essence": 1},
        currencies={"coins": 0, "gem": 10},
        target_traits=["trait_burn_boost", "trait_fire_15"],
    )
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_burn_boost", "trait_fire_15"])
    assert r["ok"] is False and r["reason"] == "cost_insufficient"
    assert ctx["inventory"]["alch_ember_crystal"] == 1
    assert ctx["target_traits"] == ["trait_burn_boost", "trait_fire_15"]  # 未动


def test_t4_trait_group_conflict_rejected() -> None:
    """T4 负例：产出特性（灼烧强化·大师）与成品已带同组特性冲突（互斥组 non-repeatable）→ 拒绝。"""
    eng = UpgradeEngine(combos=COMBOS)
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1, "alch_fire_essence": 1},
        currencies={"coins": 0, "gem": 20},
        target_traits=["trait_fire_25"],  # 成品已带同组（fire_boost）非 repeatable 特性
    )
    r = eng.execute(ctx, RCP_TRAIT, input_ids=["trait_burn_boost", "trait_fire_15"])
    assert r["ok"] is False and r["reason"] == "trait_group_conflict"
    assert "互斥组" in r["message"]
    assert ctx["currencies"]["gem"] == 20  # 未扣


def test_t5_trait_repeatable_no_conflict() -> None:
    """T5 正例：产出特性 repeatable → 与成品已带同组特性（未被消耗）可共存，
    不冲突（F-13 落位复核通过）。"""
    eng = UpgradeEngine()  # 无组合 → 兜底 recipe output（trait_heal_plus，repeatable）
    ctx = make_ctx(
        inventory={"alch_ember_crystal": 1},
        currencies={"coins": 0, "gem": 20},
        target_traits=["trait_heal_super"],  # 同组 heal_boost，repeatable=true，非本次消耗
    )
    r = eng.execute(ctx, RCP_TRAIT_HEAL, input_ids=["trait_heal_boost", "trait_heal_mp"])
    assert r["ok"] is True
    assert ctx["target_traits"] == ["trait_heal_super", "trait_heal_plus"]  # 共存落位
    assert ctx["currencies"]["gem"] == 0
