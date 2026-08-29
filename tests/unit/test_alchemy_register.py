"""AlchemyRegister 单测（M8 批7-1·路B）——细化_2c4c TC-07~11 引擎可承载部分。

文件名：tests/unit/test_alchemy_register.py
创建时间：2026-08-29
作者：Hermes 子agent-7B（并发同仓：仅新建本文件 + qbot_rpg/core/alchemy_register.py）
功能描述：qbot_rpg.core.alchemy_register.AlchemyRegister 纯函数直测（对齐 test_synthesis /
  test_gem_wallet 模式）：未登记拒绝/登记后可复制（TC-07）、复制消耗 ⌊cost.coins×20%⌋ 宝石+材料×10
  标准版产出（TC-08）、登记炼金品质成品拒绝/标准珠可复制（TC-09）、材料/宝石不足全拒差异（TC-10）、
  数量超限提示不拦仍执行（TC-11/拍板⑤）、原子性快照-回滚（ATO-02）、登记快照冻结换包同 ID 保留
  （DUP-06）、复制费率/额外消耗可配（DUP-03/拍板④，嵌套+扁平键双形态）。

依据：
  - docs/细化/细化_2c4c_珠与合成指令.md：DUP-01~06 + 验收 TC-07~11。
  - docs/m8_contract_指令契约.md §11 /登记 /复制（GU-34~36/F-11/M-11/P-11）+ §3.4（max_qty 拍板⑤）
    + ATO-01/02/07。
  - qbot_rpg/core/alchemy_register.py 工程补白 AR-1~AR-9（登记表落点/成本快照冻结/标准版判定口径/
    额外消耗键/双形态配置/入包 bound/不产经验不耗能/登记需配方/数量截断）。

【工程补白 · 注记】
  - ctx 顶层即玩家状态（currencies/inventory/registered），settings 走引擎构造器注入（单源，AR-5）——
    本文件夹具与实现一致。
  - 复制费基准 = 只算配方 cost.coins × 费率向下取整（拍板④）：mana_potion cost.coins=30 →
    每份宝石 ⌊30×0.2⌋=6；flame_bomb cost.coins=200 → ⌊200×0.2⌋=40；bead_std cost.coins=150 → 30。
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_register import (
    DEFAULT_MAX_QTY,
    REASON_MATERIALS,
    REASON_STANDARD_ONLY,
    REASON_UNREGISTERED,
    AlchemyRegister,
)

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    # 标准版成品（无 quality/traits，LAY-04a）——TC-07/08
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    # 炼金品质成品（品质 72·精良 + traits）——TC-09 拒绝
    "flame_bomb": {
        "id": "flame_bomb", "name": "火焰弹", "type": "consumable",
        "quality": 72, "traits": ["trait_burn_boost"],
    },
    # 标准珠（quality 固定 + base_effects、无 traits）——TC-09 可复制（DUP-04）
    "bead_std": {
        "id": "bead_std", "name": "攻击珠·标准", "type": "装饰珠",
        "quality": "common", "base_effects": {"atk": 3},
    },
    # 炼金珠（quality + traits）——TC-09 拒绝
    "bead_alch": {
        "id": "bead_alch", "name": "攻击珠·炼金", "type": "装饰珠",
        "quality": "uncommon", "base_effects": {"atk": 4}, "traits": ["trait_fire_15"],
    },
    # 无配方物品（AR-8：登记缺配方 → 拒）
    "ghost_moss": {"id": "ghost_moss", "name": "幽灵苔", "type": "material"},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    # 魔力药水：cost.coins=30 → 复制费 ⌊30×20%⌋=6 宝石/份（TC-08 基准）
    "rcp_mana_potion": {
        "id": "rcp_mana_potion", "name": "魔力药水配方", "kind": "craft",
        "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2}],
        "output": {"item": "mana_potion", "count": 1},
        "cost": {"coins": 30, "gem": 0},
    },
    # 火焰弹（炼金产出，非标准版）：cost.coins=200 → 40 宝石/份
    "rcp_flame_bomb": {
        "id": "rcp_flame_bomb", "name": "火焰弹配方", "kind": "craft",
        "materials": [{"id": "water_crystal", "count": 3}],
        "output": {"item": "flame_bomb", "count": 1},
        "cost": {"coins": 200, "gem": 0},
    },
    # 标准攻击珠：cost.coins=150 → ⌊150×20%⌋=30 宝石/份
    "rcp_bead_std": {
        "id": "rcp_bead_std", "name": "标准攻击珠配方", "kind": "craft",
        "materials": [{"id": "water_crystal", "count": 2}],
        "output": {"item": "bead_std", "count": 1},
        "cost": {"coins": 150, "gem": 0},
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "max_qty": DEFAULT_MAX_QTY,
        # 嵌套 dict 形态（对齐细化 2c3 schema）：复制费率 + 可配额外消耗
        "gem": {"复制": 0.2, "复制额外": 0},
    },
}


def _engine(settings: Optional[Mapping[str, Any]] = None) -> AlchemyRegister:
    """构造引擎：settings 构造器注入（单源，AR-5）；缺省走 DEFAULT_SETTINGS。"""
    return AlchemyRegister(
        settings=settings if settings is not None else DEFAULT_SETTINGS
    )


def make_ctx(**over: Any) -> MutableMapping[str, Any]:
    """全字段复制 ctx（core/alchemy_register.py 工程补白 1 契约；每场景新造避免互污染）。"""
    base: Dict[str, Any] = {
        "qid": "u1",
        "name": "阿伟",
        "currencies": {"coins": 1000, "gem": 500},
        "inventory": {"water_crystal": 50, "herb": 20},
        "items": ITEMS,
        "recipe": RECIPES,
    }
    base.update(over)
    return base


def _registered_mana_player() -> MutableMapping[str, Any]:
    """已登记魔力药水的满料玩家（登记表 + 材料/宝石充足）。"""
    ctx = make_ctx()
    res = _engine().register(ctx, "mana_potion")
    assert res["ok"] is True
    return ctx


# ---------------------------------------------------------------------------
# is_copyable 标准版判定（DUP-04 / TC-09 / AR-3）
# ---------------------------------------------------------------------------
def test_is_copyable_standard_vs_alchemy() -> None:
    """标准版可复制：标准成品/标准珠 → True；炼金成品/炼金珠（带 traits）→ False；非 Mapping → False。"""  # noqa: E501
    eng = _engine()
    assert eng.is_copyable(ITEMS["mana_potion"]) is True    # 标准成品（无品质章无特性）
    # 标准珠（quality+base_effects 无 traits）可复制
    assert eng.is_copyable(ITEMS["bead_std"]) is True
    assert eng.is_copyable(ITEMS["flame_bomb"]) is False    # 炼金品质成品（quality 72 + traits）
    assert eng.is_copyable(ITEMS["bead_alch"]) is False     # 炼金珠（quality + traits）
    assert eng.is_copyable("mana_potion") is False          # 非 Mapping 防御
    assert eng.is_copyable(None) is False


# ---------------------------------------------------------------------------
# TC-07 未登记拒绝 / 登记后可复制（DUP-02）
# ---------------------------------------------------------------------------
def test_tc07_unregistered_reject_then_register_copy() -> None:
    """/复制 未登记 魔力药水 → 拒「未登记复制」；/登记 → ✅；此后 /复制 可执行。"""
    eng = _engine()
    ctx = make_ctx()
    # 未登记 → 拒绝
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is False
    assert res["reason"] == REASON_UNREGISTERED
    assert "未登记复制" in res["message"]
    assert "先 /登记" in res["message"]
    assert res["produced"] is None
    assert ctx["inventory"].get("mana_potion", 0) == 0  # 零副作用
    assert ctx["currencies"]["gem"] == 500
    # /登记 → 成功，登记表写入
    reg = eng.register(ctx, "mana_potion")
    assert reg["ok"] is True
    assert "已登记" in reg["message"]
    assert "换包同 ID 保留" in reg["message"]
    assert ctx["registered"]["mana_potion"]["item_id"] == "mana_potion"
    # 登记后可复制
    res2 = eng.copy(ctx, "mana_potion", 1)
    assert res2["ok"] is True
    assert ctx["inventory"]["mana_potion"] == 1


def test_is_registered_flag() -> None:
    """is_registered：登记前 False、登记后 True；未登记表/非法 id 防御。"""
    eng = _engine()
    ctx = make_ctx()
    assert eng.is_registered(ctx, "mana_potion") is False
    eng.register(ctx, "mana_potion")
    assert eng.is_registered(ctx, "mana_potion") is True
    assert eng.is_registered(ctx, "flame_bomb") is False  # 未登记
    assert eng.is_registered(ctx, "") is False            # 非法 id
    assert eng.is_registered(make_ctx(), "mana_potion") is False  # 无登记表


# ---------------------------------------------------------------------------
# TC-08 复制消耗 ⌊cost.coins×20%⌋ 宝石 + 材料×10 → 标准版×10 入包（DUP-03/DUP-04）
# ---------------------------------------------------------------------------
def test_tc08_copy_cost_floor_20pct_and_materials_x10() -> None:
    """copy_cost(配方) → {gem:⌊30×20%⌋=6, materials 全量, extra 0}；/复制 ×10 → 宝石 -60、
    材料×10、标准版魔力药水×10 入包（无品质浮动/无特性）。"""
    eng = _engine()
    # copy_cost 单份基准（拍板④：只算 cost.coins 向下取整）
    cc = eng.copy_cost(RECIPES["rcp_mana_potion"])
    assert cc["gem"] == 6                       # ⌊30 × 0.2⌋
    assert cc["materials"] == [
        {"id": "water_crystal", "count": 5}, {"id": "herb", "count": 2},
    ]
    assert cc["extra"] == {"gem": 0}
    # 登记 + 复制 ×10
    ctx = make_ctx()
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 10)
    assert res["ok"] is True
    assert res["produced"] == {"item_id": "mana_potion", "name": "魔力药水", "count": 10}
    assert res["cost"]["gem"] == 60              # 6 × 10
    assert res["cost"]["materials"] == [
        {"id": "water_crystal", "count": 50}, {"id": "herb", "count": 20},
    ]
    # 标准版入包：只加数量，无 quality/traits 字段（LAY-04a）
    assert ctx["inventory"]["mana_potion"] == 10
    assert ctx["currencies"]["gem"] == 500 - 60
    assert ctx["inventory"]["water_crystal"] == 0
    assert ctx["inventory"]["herb"] == 0
    # M-11 消息格式：宝石先行
    assert "✅ 魔力药水 ×10 复制完成" in res["message"]
    assert "宝石×60" in res["message"]
    assert "水结晶×50" in res["message"]


# ---------------------------------------------------------------------------
# DUP-03 复制费率/额外消耗可配（拍板④；AR-4/AR-5 双形态）
# ---------------------------------------------------------------------------
def test_copy_rate_and_extra_configurable() -> None:
    """复制费率可配（gem.复制=0.25 → ⌊30×0.25⌋=7）；额外消耗可配（复制额外=3）并入原子校验。"""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["alchemy"]["gem"]["复制"] = 0.25
    settings["alchemy"]["gem"]["复制额外"] = 3
    eng = _engine(settings=settings)
    cc = eng.copy_cost(RECIPES["rcp_mana_potion"])
    assert cc["gem"] == 7        # ⌊30 × 0.25⌋
    assert cc["extra"] == {"gem": 3}
    # 登记 → 复制 ×1：宝石 = (7+3)×1 = 10
    ctx = make_ctx()
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is True
    assert res["cost"]["gem"] == 10
    assert ctx["currencies"]["gem"] == 500 - 10
    # 额外消耗不足 → 全拒差异（宝石缺额计入）
    ctx2 = make_ctx(currencies={"coins": 1000, "gem": 9})
    assert eng.register(ctx2, "mana_potion")["ok"] is True
    res2 = eng.copy(ctx2, "mana_potion", 1)
    assert res2["ok"] is False
    assert res2["reason"] == REASON_MATERIALS
    assert "宝石 1" in res2["message"]          # 需 10 持 9 → 差 1
    assert ctx2["inventory"].get("mana_potion", 0) == 0


def test_flat_key_config_shape() -> None:
    """AR-5 扁平键形态（test_demo "gem.复制"/"gem.复制额外"）同样生效（扁平覆盖嵌套）。"""
    settings: Dict[str, Any] = {
        "alchemy": {
            "max_qty": DEFAULT_MAX_QTY,
            "gem": {"复制": 0.5},          # 嵌套 0.5
            "gem.复制": 0.2,                # 扁平 0.2 覆盖
            "gem.复制额外": 2,              # 扁平额外
        },
    }
    eng = _engine(settings=settings)
    cc = eng.copy_cost(RECIPES["rcp_mana_potion"])
    assert cc["gem"] == 6        # 取扁平 0.2 → ⌊30×0.2⌋
    assert cc["extra"] == {"gem": 2}


# ---------------------------------------------------------------------------
# TC-09 登记炼金品质成品拒绝（仅标准版）/ 标准珠可复制（DUP-04）
# ---------------------------------------------------------------------------
def test_tc09_register_alchemy_item_rejected_standard_bead_ok() -> None:
    """/登记 炼金品质成品（品质 72·精良火焰弹）→ 拒 standard_only；标准珠登记+复制 → 成功。"""
    eng = _engine()
    ctx = make_ctx()
    # 炼金成品（quality+traits）→ 登记拒绝
    res = eng.register(ctx, "flame_bomb")
    assert res["ok"] is False
    assert res["reason"] == REASON_STANDARD_ONLY
    assert "仅标准版可登记复制" in res["message"]
    assert "火焰弹" in res["message"]
    assert "flame_bomb" not in ctx.get("registered", {})
    # 炼金珠（quality+traits）→ 登记拒绝
    assert eng.register(ctx, "bead_alch")["ok"] is False
    # 标准珠（quality+base_effects、无 traits）→ 登记+复制成功
    assert eng.register(ctx, "bead_std")["ok"] is True
    res2 = eng.copy(ctx, "bead_std", 2)
    assert res2["ok"] is True
    assert res2["produced"]["count"] == 2
    assert ctx["inventory"]["bead_std"] == 2
    assert ctx["currencies"]["gem"] == 500 - 30 * 2  # ⌊150×0.2⌋=30/份


# ---------------------------------------------------------------------------
# TC-10 材料或宝石不足 → 全拒差异（DUP-05 原子校验）
# ---------------------------------------------------------------------------
def test_tc10_material_shortfall_all_reject_diff() -> None:
    """/复制 缺 水结晶×1 → 全拒；提示「缺 水结晶×1 + 宝石 6」；零副作用。"""
    eng = _engine()
    ctx = make_ctx(inventory={"water_crystal": 4, "herb": 20})  # 需 5 持 4
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is False
    assert res["reason"] == REASON_MATERIALS
    # 材料缺额优先提示；宝石充足时不并列（差异只列不足项，TC-10 全拒口径）
    assert "缺 水结晶×1" in res["message"]
    assert res["produced"] is None
    # 全拒：零副作用
    assert ctx["inventory"]["water_crystal"] == 4
    assert ctx["currencies"]["gem"] == 500
    assert ctx["inventory"].get("mana_potion", 0) == 0


def test_tc10_material_and_gem_shortfall_both_in_diff() -> None:
    """/复制 材料+宝石同时不足 → 差异同时列「缺 水结晶×1 + 宝石 1」（TC-10 全拒差异原文形态）。"""
    eng = _engine()
    ctx = make_ctx(currencies={"coins": 1000, "gem": 5},
                   inventory={"water_crystal": 4, "herb": 20})
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is False
    assert res["reason"] == REASON_MATERIALS
    assert "缺 水结晶×1 + 宝石 1" in res["message"]


def test_tc10_gem_shortfall_all_reject_diff() -> None:
    """/复制 宝石不足 → 全拒；提示「缺 宝石 N」；材料不扣、不入包。"""
    eng = _engine()
    ctx = make_ctx(currencies={"coins": 1000, "gem": 5})  # 需 6 持 5
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is False
    assert res["reason"] == REASON_MATERIALS
    assert "宝石 1" in res["message"]
    assert ctx["currencies"]["gem"] == 5
    assert ctx["inventory"]["water_crystal"] == 50  # 材料不扣
    assert ctx["inventory"].get("mana_potion", 0) == 0


# ---------------------------------------------------------------------------
# TC-11 数量超限提示不拦仍执行（DUP-05 / 拍板⑤ / AR-9）
# ---------------------------------------------------------------------------
def test_tc11_qty_cap_hint_not_block_executes() -> None:
    """max_qty=3：请求 10 → 提示「最多一次使用 3 个」不拦、按 3 截断执行成功。"""
    settings = copy.deepcopy(DEFAULT_SETTINGS)
    settings["alchemy"]["max_qty"] = 3
    eng = _engine(settings=settings)
    ctx = make_ctx()  # 材料够 3 份（水 50/草 20 均 ≥ 3×）
    assert eng.register(ctx, "mana_potion")["ok"] is True
    res = eng.copy(ctx, "mana_potion", 10)
    assert res["ok"] is True
    assert res["produced"]["count"] == 3
    assert res["advisory"] == "最多一次使用 3 个"
    assert "最多一次使用 3 个" in res["message"]
    assert res["cost"]["gem"] == 18               # 6 × 3
    assert ctx["currencies"]["gem"] == 500 - 18
    assert ctx["inventory"]["mana_potion"] == 3
    # 材料不足且超限 → 全拒 + 提示（截断后差异口径）
    ctx2 = make_ctx(inventory={"water_crystal": 8, "herb": 20})  # 3 份需 15，持 8
    assert eng.register(ctx2, "mana_potion")["ok"] is True
    res2 = eng.copy(ctx2, "mana_potion", 10)
    assert res2["ok"] is False
    assert res2["reason"] == REASON_MATERIALS
    assert res2["advisory"] == "最多一次使用 3 个"
    assert "缺 水结晶×7" in res2["message"]      # 3 份需 15，持 8 → 差 7
    assert ctx2["inventory"]["water_crystal"] == 8


# ---------------------------------------------------------------------------
# 原子性：快照-回滚（DUP-05 / ATO-02 单事务）
# ---------------------------------------------------------------------------
def test_atomicity_rollback_on_add_failure() -> None:
    """入包 hook 失败 → 事务回滚：宝石恢复、材料/入包零残留、消息「已回滚」。"""
    eng = _engine()
    ctx = _registered_mana_player()
    ctx["add_item"] = lambda _i, _c, _b: False  # 入包通道 hook 存在但失败
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is False
    assert res["reason"] == "item_add_failed"
    assert "已回滚" in res["message"]
    assert ctx["currencies"]["gem"] == 500       # 已扣的 6 宝石回滚
    assert ctx["inventory"]["water_crystal"] == 50
    assert ctx["inventory"]["herb"] == 20
    assert ctx["inventory"].get("mana_potion", 0) == 0


def test_atomicity_rollback_on_remove_failure() -> None:
    """/复制 ×2 第二材料扣除失败（hook 对 herb 返回 False）→ 全量回滚，无部分扣减。"""
    eng = _engine()
    ctx = _registered_mana_player()
    # 扣减 hook：herb 拒绝 → 中途失败触发回滚
    ctx["remove_item"] = lambda i, _c: i != "herb"
    res = eng.copy(ctx, "mana_potion", 2)
    assert res["ok"] is False
    assert res["reason"] == "material_remove_failed"
    assert "已回滚" in res["message"]
    assert ctx["currencies"]["gem"] == 500       # 已扣的 12 宝石回滚
    assert ctx["inventory"]["water_crystal"] == 50
    assert ctx["inventory"]["herb"] == 20
    assert ctx["inventory"].get("mana_potion", 0) == 0


# ---------------------------------------------------------------------------
# DUP-06 登记快照冻结 / 换包同 ID 保留
# ---------------------------------------------------------------------------
def test_dup06_snapshot_frozen_across_pack_change() -> None:
    """登记后配方 cost.coins 改大 → /复制 仍按登记快照（6 宝石/份）结算，换包同 ID 保留。"""
    eng = _engine()
    ctx = make_ctx()
    assert eng.register(ctx, "mana_potion")["ok"] is True
    # 模拟换包：配方成本大幅上调（成本快照冻结，不重算）
    ctx["recipe"]["rcp_mana_potion"]["cost"]["coins"] = 9999
    res = eng.copy(ctx, "mana_potion", 1)
    assert res["ok"] is True
    assert res["cost"]["gem"] == 6               # 仍按登记时 ⌊30×20%⌋
    assert ctx["currencies"]["gem"] == 500 - 6


def test_register_overwrite_refreshes_snapshot() -> None:
    """重复 /登记 同 ID → 覆盖成本快照（登记表仍单条目，DUP-06 按 ID 保留）。"""
    eng = _engine()
    ctx = make_ctx()
    assert eng.register(ctx, "mana_potion")["ok"] is True
    ctx["recipe"]["rcp_mana_potion"]["cost"]["coins"] = 100  # 改配方后重登记
    res = eng.register(ctx, "mana_potion")
    assert res["ok"] is True
    assert len(ctx["registered"]) == 1
    assert ctx["registered"]["mana_potion"]["cost_snapshot"]["gem"] == 20  # ⌊100×20%⌋


# ---------------------------------------------------------------------------
# 边界：登记缺配方（AR-8）/ 非法数量 / 未找到物品
# ---------------------------------------------------------------------------
def test_register_requires_recipe() -> None:
    """无产出配方的物品（幽灵苔）→ 登记拒 recipe_not_found（无法冻结成本快照）。"""
    eng = _engine()
    ctx = make_ctx()
    res = eng.register(ctx, "ghost_moss")
    assert res["ok"] is False
    assert res["reason"] == "recipe_not_found"
    assert "配方" in res["message"]
    assert "ghost_moss" not in ctx.get("registered", {})


def test_invalid_count_and_item_reject() -> None:
    """count 非正整数 / 物品不存在 → 拒绝且零副作用。"""
    eng = _engine()
    ctx = _registered_mana_player()
    res = eng.copy(ctx, "mana_potion", 0)
    assert res["ok"] is False
    assert res["reason"] == "invalid_count"
    assert ctx["inventory"]["water_crystal"] == 50
    res2 = eng.copy(ctx, "mana_potion", -3)
    assert res2["ok"] is False
    assert res2["reason"] == "invalid_count"
    res3 = eng.copy(ctx, "ghost_moss", 1)   # 未登记 + 无登记表条目
    assert res3["ok"] is False
    assert res3["reason"] == REASON_UNREGISTERED
    res4 = eng.copy(ctx, "no_such_item", 1)
    assert res4["ok"] is False
    assert res4["reason"] == "item_not_found"
    res5 = eng.register(ctx, "")
    assert res5["ok"] is False
    assert res5["reason"] == "invalid_item"
