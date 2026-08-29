"""GemWallet 宝石货币引擎单测（M8 批6·路6B · qbot_rpg/core/gem_wallet.py）。

文件：tests/unit/test_gem_wallet.py
创建：2026-08-29
作者：Hermes 子agent-6B
功能：GemWallet 纯函数直测（对齐 test_synthesis/test_quality 模式）——/分解 计算（材料×回收率
  向下取整 + 宝石平铺基础值拍板① + count 累加 + 两段式消息数据）、标准版拒绝（LAY-05）、回收率
  随档位（正式0.4/大师0.55/王0.65）、宝石基础值（普通1/精良3/史诗8/传说20）、grant_gem 统一入账、
  配置可配（decompose_rate / gem.分解 / decompose_formula / standard_decompose_half）。

依据：
  - docs/m8_batch_plan.md §批6 路6B（宝石货币 / /分解 仅炼金/深度产出、标准版默认不可分解、
    材料×回收率向下取整、宝石平铺基础值拍板①、两段式消息、分解公式可配置）
  - docs/m8_contract_战斗资源.md 一（GEM-02/03/06/13/14/15/16；回收率 0.4~0.65 档位、平铺
    普通1/精良3/史诗8/传说20 不乘回收率、两段式消息对齐 L248「火晶石×2 + 宝石×5」）
  - docs/m8_contract_数据与校验.md §五 L205/L208（decompose_rate 6 档、gem.分解、
    gem.decompose_formula "flat"|"rate"）
  - docs/细化/细化_2c4b_宝石货币经济.md DEC-01~06 + 验收 TC-19~22 / TC-01
  - docs/细化/细化_2c4c_珠与合成指令.md DEC-01~05（标准版不可分解默认最严、回收减半内容包可配）

覆盖矩阵（每条正例 + 反例，断言精确数值/档位/消息）：
  TC-19  回收率随档位 正式0.4/精通0.45/专家0.5/大师0.55/宗师0.6/王0.65、见习0.0（DEC-02/05）
  TC-20  材料×回收率向下取整（水结晶×3+草药×2 @0.5 → 1+1；0.x 归 0 不进列表）（DEC-02）
  TC-01/21/22  宝石平铺基础值 普通1/精良3/史诗8/传说20 不乘回收率（拍板①/DEC-03）
  LAY-05 标准版拒绝（无 quality / 有 quality 无 traits / 非炼金产出 → standard_not_decomposable）
  count  分解件数累加（材料×n、宝石×n）+ 非法 count 归一
  GEM-02/03  grant_gem 入账（累加/余额/缺桶/数额非法/键空间硬前置 unknown_currency）
  配置可配  decompose_rate 覆盖 / gem.分解 覆盖 / decompose_formula="rate" / 缺档回落默认
  GEM-15 两段式消息数据（material_seg + gem_seg + message 分行，对齐 L248）
  工程补白  GW-1 is_decomposable 判定 / GW-3 品质章多样 / GW-4 未知档位宝石 0 /
           GW-8 标准版回收减半 alternative / GW-10 item 分解表优先 / GW-12 decompose 纯计算

测试风格对齐 tests/unit/test_quality.py / test_synthesis.py：纯 pytest、零 NoneBot、
断言具体数值/档位/消息；ctx 顶层即玩家状态（items/recipe/currencies），settings 构造器注入。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.gem_wallet import (
    DEFAULT_DECOMPOSE_RATES,
    DEFAULT_GEM_FLAT_BASE,
    REASON_STANDARD_NOT_DECOMPOSABLE,
    GemWallet,
)
from qbot_rpg.core.quality import QualitySystem

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    # 材料
    "water_crystal": {"id": "water_crystal", "name": "水结晶", "type": "material"},
    "herb": {"id": "herb", "name": "草药", "type": "material"},
    "star_iron": {"id": "star_iron", "name": "星铁矿石", "type": "material"},
    "fire_crystal": {"id": "fire_crystal", "name": "火晶石", "type": "material"},
    # 炼金成品（带品质章 + 特性 → 可分解）
    "flame_bomb": {"id": "flame_bomb", "name": "火焰弹", "type": "consumable", "quality": "common",
                   "traits": ["trait_burn_boost"], "usable": True},
    "flame_bomb_uncommon": {"id": "flame_bomb_uncommon", "name": "烈焰弹·改", "type": "consumable",
                            "quality": "uncommon", "traits": ["trait_fire_15"], "usable": True},
    "flame_bomb_rare": {"id": "flame_bomb_rare", "name": "炼狱爆弹·极", "type": "consumable",
                        "quality": "rare", "traits": ["trait_fire_25"], "usable": True},
    "doomsday_bomb": {"id": "doomsday_bomb", "name": "灭世爆弹", "type": "consumable",
                      "quality": "legendary", "traits": ["trait_fire_25"], "usable": True},
    "flame_bomb_low": {"id": "flame_bomb_low", "name": "微型爆弹", "type": "consumable",
                       "quality": "common", "traits": ["trait_burn_boost"], "usable": True},
    # 标准版（无品质 → 不可分解，LAY-05）
    "mana_potion": {"id": "mana_potion", "name": "魔力药水", "type": "consumable"},
    # GW-1 负例：有品质无特性（标准版）
    "flame_bomb_plain": {"id": "flame_bomb_plain", "name": "火焰弹·无特性", "type": "consumable",
                         "quality": "common"},
    # GW-1 负例：有特性无品质
    "trait_only_item": {"id": "trait_only_item", "name": "特性残留物", "type": "material",
                        "traits": ["trait_burn_boost"]},
    # 装饰珠（炼金珠，quality+traits → 可分解）
    "jewel_burn_rare": {"id": "jewel_burn_rare", "name": "灼烧珠·史诗", "type": "装饰珠",
                        "quality": "rare", "base_effects": {"atk": 6}, "traits": ["trait_fire_25"]},
    # GW-10：item 分解表优先（无对应配方）
    "flame_bomb_own_table": {
        "id": "flame_bomb_own_table", "name": "火焰弹·自表", "type": "consumable",
        "quality": "rare", "traits": ["trait_fire_15"],
        "decompose": {"materials": [{"id": "fire_crystal", "count": 6}]},
    },
    # GW-3：品质章多样形态
    "score_item": {"id": "score_item", "name": "品质分成品", "type": "consumable", "quality": 85,
                   "traits": ["trait_fire_25"]},
    "tier_map_item": {"id": "tier_map_item", "name": "档位映射成品", "type": "consumable",
                      "quality": {"tier": "rare"}, "traits": ["trait_fire_15"]},
    "score_map_item": {"id": "score_map_item", "name": "品质分映射成品", "type": "consumable",
                       "quality": {"score": 70}, "traits": ["trait_fire_15"]},
    # GW-4：未知档位 → 宝石 0
    "unknown_quality_item": {"id": "unknown_quality_item", "name": "异质成品", "type": "consumable",
                             "quality": "purple", "traits": ["trait_fire_15"]},
}

RECIPES: Dict[str, Mapping[str, Any]] = {
    # 火焰弹 材料 水结晶×3 + 草药×2（对齐 2c4b TC-20 算例）
    "rcp_flame_bomb": {
        "id": "rcp_flame_bomb", "name": "火焰弹配方", "kind": "craft", "level": 3,
        "materials": [{"id": "water_crystal", "count": 3}, {"id": "herb", "count": 2}],
        "output": {"item": "flame_bomb", "count": 1},
    },
    "rcp_flame_bomb_uncommon": {
        "id": "rcp_flame_bomb_uncommon", "name": "烈焰弹配方", "kind": "craft",
        "level": 10, "materials": [{"id": "water_crystal", "count": 5}],
        "output": {"item": "flame_bomb_uncommon", "count": 1},
    },
    "rcp_flame_bomb_rare": {
        "id": "rcp_flame_bomb_rare", "name": "炼狱爆弹配方", "kind": "craft",
        "level": 31,
        "materials": [{"id": "water_crystal", "count": 5}, {"id": "herb", "count": 3}],
        "output": {"item": "flame_bomb_rare", "count": 1},
    },
    "rcp_doomsday": {"id": "rcp_doomsday", "name": "灭世配方", "kind": "craft", "level": 61,
                     "materials": [{"id": "fire_crystal", "count": 4}],
                     "output": {"item": "doomsday_bomb", "count": 1}},
    "rcp_flame_bomb_low": {
        "id": "rcp_flame_bomb_low", "name": "微型爆弹配方", "kind": "craft", "level": 6,
        "materials": [{"id": "star_iron", "count": 1}],
        "output": {"item": "flame_bomb_low", "count": 1},
    },
    "rcp_mana_potion": {
        "id": "rcp_mana_potion", "name": "魔力药水配方", "kind": "craft", "level": 3,
        "materials": [{"id": "water_crystal", "count": 4}],
        "output": {"item": "mana_potion", "count": 1},
    },
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "currencies": [
        {"id": "coins", "name": "金币"}, {"id": "diamond", "name": "钻石"},
        {"id": "gem", "name": "宝石"},
    ],
    "alchemy": {
        "decompose_rate": dict(DEFAULT_DECOMPOSE_RATES),
        "gem": {
            "分解": dict(DEFAULT_GEM_FLAT_BASE),
            "decompose_formula": "flat",
        },
    },
}


def _wallet(settings: Optional[Mapping[str, Any]] = None,
            quality: Optional[QualitySystem] = None) -> GemWallet:
    """构造引擎：settings/quality 构造器注入（单源）；缺省走 DEFAULT_SETTINGS。"""
    return GemWallet(
        settings=settings if settings is not None else DEFAULT_SETTINGS,
        quality=quality,
    )


def make_ctx(**over: Any) -> MutableMapping[str, Any]:
    """全字段分解 ctx（每场景新造避免互污染）。"""
    base: Dict[str, Any] = {
        "qid": "u1",
        "name": "阿伟",
        "currencies": {"coins": 1000, "gem": 0},
        "inventory": {},
        "items": ITEMS,
        "recipe": RECIPES,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# TC-19 回收率随档位（DEC-02/05，GW-5）
# ---------------------------------------------------------------------------
def test_tc19_decompose_rate_by_tier() -> None:
    """TC-19 正例：六档回收率 0.4/0.45/0.5/0.55/0.6/0.65 精确；见习恒 0.0。"""
    w = _wallet()
    assert w.decompose_rate(1) == 0.4   # 正式
    assert w.decompose_rate(2) == 0.45  # 精通
    assert w.decompose_rate(3) == 0.5   # 专家
    assert w.decompose_rate(4) == 0.55  # 大师
    assert w.decompose_rate(5) == 0.6   # 宗师
    assert w.decompose_rate(6) == 0.65  # 王
    assert w.decompose_rate(0) == 0.0   # 见习无分解（2c4c DEC-01）


def test_tc19_decompose_rate_defensive_clamp() -> None:
    """TC-19 反例：越界档位裁剪到 [0,6]、非法值回落 0（防御，GW-5）。"""
    w = _wallet()
    assert w.decompose_rate(-1) == 0.0
    assert w.decompose_rate(99) == 0.65  # 王封顶
    bad: Any = "4"
    assert w.decompose_rate(bad) == 0.55  # 数字串归一


def test_tc19_rate_applied_to_materials() -> None:
    """TC-19 正例：同一成品跨档分解，材料返还随档位跳变（4×0.4→1、4×0.65→2）。"""
    w = _wallet()
    ctx = make_ctx()
    r1 = w.decompose(ctx, ITEMS["doomsday_bomb"], job_tier_index=1)
    r6 = w.decompose(ctx, ITEMS["doomsday_bomb"], job_tier_index=6)
    assert r1["materials"] == [("fire_crystal", "火晶石", 1)]  # ⌊4×0.4⌋=1
    assert r6["materials"] == [("fire_crystal", "火晶石", 2)]  # ⌊4×0.65⌋=2
    assert r1["decompose_rate"] == 0.4
    assert r6["decompose_rate"] == 0.65


# ---------------------------------------------------------------------------
# TC-20 材料×回收率向下取整（DEC-02，GW-2）
# ---------------------------------------------------------------------------
def test_tc20_materials_floor_per_id() -> None:
    """TC-20 正例：水结晶×3+草药×2 @0.5 → 1+1（逐 id 向下取整，不足 1 归 0）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["flame_bomb"], job_tier_index=3)  # 专家 0.5
    assert r["ok"] is True
    assert r["materials"] == [("water_crystal", "水结晶", 1), ("herb", "草药", 1)]
    assert r["gem"] == 1  # 普通 1（拍板①）


def test_tc20_zero_recovery_excluded() -> None:
    """TC-20 反例：材料×0.4 不足 1 → 归 0，不进返回列表（材料返还为空，宝石仍发）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["flame_bomb_low"], job_tier_index=1)  # 正式 0.4
    assert r["ok"] is True
    assert r["materials"] == []  # ⌊1×0.4⌋=0 → 归 0
    assert r["gem"] == 1  # 宝石不依赖材料表（GEM-15 平铺）


# ---------------------------------------------------------------------------
# TC-01/21/22 宝石平铺基础值（拍板①，DEC-03）
# ---------------------------------------------------------------------------
def test_gem_flat_base_four_tiers() -> None:
    """拍板① 正例：普通1/精良3/史诗8/传说20 平铺基础值精确。"""
    w = _wallet()
    assert w.gem_base_value("common") == 1
    assert w.gem_base_value("uncommon") == 3
    assert w.gem_base_value("rare") == 8
    assert w.gem_base_value("legendary") == 20


def test_gem_not_multiplied_by_rate() -> None:
    """拍板① 正例：宝石不乘回收率——传说成品王档 0.65 仍发 20（非 13）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["doomsday_bomb"], job_tier_index=6)  # 王 0.65
    assert r["ok"] is True
    assert r["gem"] == 20  # 平铺，不乘 0.65


def test_gem_base_value_unknown_tier_zero() -> None:
    """拍板① 反例：未知档位/非法值 → 0（不凭空发宝石，防御）。"""
    w = _wallet()
    assert w.gem_base_value("purple") == 0
    assert w.gem_base_value("") == 0
    bad: Any = 123
    assert w.gem_base_value(bad) == 0


# ---------------------------------------------------------------------------
# LAY-05 / 2c4c DEC-02 标准版拒绝
# ---------------------------------------------------------------------------
def test_standard_version_rejected() -> None:
    """LAY-05 正例：标准版（无品质章）→ 拒绝 standard_not_decomposable。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["mana_potion"], job_tier_index=6)
    assert r["ok"] is False
    assert r["reason"] == REASON_STANDARD_NOT_DECOMPOSABLE
    assert "标准版" in r["message"]


def test_quality_without_traits_rejected() -> None:
    """GW-1 负例：有品质无特性（品质固定=标准版）→ 拒绝。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["flame_bomb_plain"], job_tier_index=6)
    assert r["ok"] is False
    assert r["reason"] == REASON_STANDARD_NOT_DECOMPOSABLE


def test_trait_only_rejected() -> None:
    """GW-1 负例：有特性无品质 → 拒绝（非炼金/深度产出）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["trait_only_item"], job_tier_index=6)
    assert r["ok"] is False
    assert r["reason"] == REASON_STANDARD_NOT_DECOMPOSABLE


def test_invalid_item_def_rejected() -> None:
    """反例：item_def 非 Mapping → invalid_item。"""
    w = _wallet()
    assert w.decompose(make_ctx(), None, job_tier_index=6)["reason"] == "invalid_item"
    assert w.decompose(make_ctx(), "notamap", job_tier_index=6)["reason"] == "invalid_item"


def test_decomposable_item_accepted() -> None:
    """正例对照：炼金成品（quality+traits）→ ok True；炼金珠同样可分解。"""
    w = _wallet()
    ctx = make_ctx()
    assert w.decompose(ctx, ITEMS["flame_bomb"], job_tier_index=3)["ok"] is True
    r = w.decompose(ctx, ITEMS["jewel_burn_rare"], job_tier_index=3)
    assert r["ok"] is True
    assert r["gem"] == 8  # 史诗 8


# ---------------------------------------------------------------------------
# count 累加（GEM-15，GW-2）
# ---------------------------------------------------------------------------
def test_decompose_count_accumulation() -> None:
    """正例：分解 3 件 → 材料×3、宝石×3（20×3=60）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["doomsday_bomb"], count=3, job_tier_index=6)
    assert r["ok"] is True
    assert r["count"] == 3
    assert r["gem"] == 60  # 20×3 平铺累加
    assert r["materials"] == [("fire_crystal", "火晶石", 7)]  # ⌊4×3×0.65⌋=7


def test_decompose_count_invalid_normalized() -> None:
    """反例：count 非正整数归一为 1；数字串归一。"""
    w = _wallet()
    assert w.decompose(make_ctx(), ITEMS["flame_bomb"], count=0, job_tier_index=3)["count"] == 1
    assert w.decompose(make_ctx(), ITEMS["flame_bomb"], count=-3, job_tier_index=3)["count"] == 1
    bad: Any = "2"
    assert w.decompose(make_ctx(), ITEMS["flame_bomb"], count=bad, job_tier_index=3)["count"] == 2


# ---------------------------------------------------------------------------
# GEM-02/03 grant_gem 统一入账
# ---------------------------------------------------------------------------
def test_grant_gem_accrual() -> None:
    """GEM-02 正例：currencies["gem"] 就地累加 + balance 精确。"""
    w = _wallet()
    ctx = make_ctx()
    r1 = w.grant_gem(ctx, 5)
    assert r1["ok"] is True
    assert r1["balance"] == 5
    assert ctx["currencies"]["gem"] == 5
    r2 = w.grant_gem(ctx, 3)
    assert r2["balance"] == 8
    assert ctx["currencies"]["gem"] == 8


def test_grant_gem_invalid_amount() -> None:
    """GEM-02 反例：负数/非整数 → invalid_amount，不写桶。"""
    w = _wallet()
    ctx = make_ctx()
    assert w.grant_gem(ctx, -1)["reason"] == "invalid_amount"
    bad: Any = "x"
    assert w.grant_gem(ctx, bad)["reason"] == "invalid_amount"
    assert ctx["currencies"]["gem"] == 0


def test_grant_gem_missing_bucket() -> None:
    """GEM-02 反例：货币表缺失 → missing_bucket。"""
    w = _wallet()
    assert w.grant_gem({}, 5)["reason"] == "missing_bucket"


def test_grant_gem_unknown_currency() -> None:
    """GEM-03 正例（硬前置）：gem 未登记 settings.currencies → unknown_currency 不发。"""
    w = _wallet(settings={"alchemy": {}})
    assert w.grant_gem(make_ctx(), 5)["reason"] == "unknown_currency"
    # 缺省键空间 coins/diamond（对齐 reward.DEFAULT_CURRENCY_IDS）
    w_default = GemWallet()
    assert w_default.grant_gem(make_ctx(), 5)["reason"] == "unknown_currency"


def test_grant_gem_keeps_zero_balance() -> None:
    """GEM-02 正例：空入账 amount=0 → ok True，余额不变。"""
    w = _wallet()
    ctx = make_ctx()
    r = w.grant_gem(ctx, 0)
    assert r["ok"] is True
    assert ctx["currencies"]["gem"] == 0


# ---------------------------------------------------------------------------
# 配置可配（decompose_rate / gem.分解 / decompose_formula / standard_decompose_half）
# ---------------------------------------------------------------------------
def test_config_decompose_rate_override_and_fallback() -> None:
    """正例：decompose_rate 覆盖王→0.7，未配档位回落默认（正式仍 0.4）。"""
    w = _wallet(settings={"alchemy": {"decompose_rate": {"王": 0.7}}})
    assert w.decompose_rate(6) == 0.7
    assert w.decompose_rate(1) == 0.4  # 缺档回落默认


def test_config_gem_flat_base_override() -> None:
    """正例：gem.分解 覆盖全档（rare 16）；反例：部分覆盖缺档回落默认。"""
    full = _wallet(settings={"alchemy": {"gem": {
        "分解": {"common": 2, "uncommon": 4, "rare": 16, "legendary": 40},
    }}})
    assert full.gem_base_value("rare") == 16
    r = full.decompose(make_ctx(), ITEMS["flame_bomb_rare"], job_tier_index=3)
    assert r["gem"] == 16

    partial = _wallet(settings={"alchemy": {"gem": {"分解": {"rare": 9}}}})
    assert partial.gem_base_value("rare") == 9
    assert partial.gem_base_value("legendary") == 20  # 缺档回落默认


def test_config_decompose_formula_rate() -> None:
    """拍板① 正例：decompose_formula="rate" → ⌊基础值×回收率⌋×count（20×0.65→13）。"""
    w = _wallet(settings={"alchemy": {"gem": {"decompose_formula": "rate"}}})
    r = w.decompose(make_ctx(), ITEMS["doomsday_bomb"], job_tier_index=6)
    assert r["ok"] is True
    assert r["gem"] == 13  # ⌊20×0.65⌋=13
    # 反例：非法公式值回落 flat（20 平铺）
    w_bad = _wallet(settings={"alchemy": {"gem": {"decompose_formula": "bogus"}}})
    r_bad = w_bad.decompose(make_ctx(), ITEMS["doomsday_bomb"], job_tier_index=6)
    assert r_bad["gem"] == 20


def test_config_standard_decompose_half_alternative() -> None:
    """GW-8 正例：standard_decompose_half=True → 标准版可分解：材料×rate/2、宝石恒 0。"""
    w = _wallet(settings={"alchemy": {"standard_decompose_half": True}})
    r = w.decompose(make_ctx(), ITEMS["mana_potion"], job_tier_index=6)
    assert r["ok"] is True
    assert r["standard_half"] is True
    assert r["gem"] == 0  # 标准版无品质章 → 宝石 0
    assert r["materials"] == [("water_crystal", "水结晶", 1)]  # ⌊4×0.65/2⌋=1
    # 反例：缺省 False → 标准版仍拒绝（默认最严，2c4c DEC-02）
    assert _wallet().decompose(make_ctx(), ITEMS["mana_potion"], job_tier_index=6)["ok"] is False


# ---------------------------------------------------------------------------
# GEM-15 两段式消息数据（对齐 L248「火晶石×2 + 宝石×5」）
# ---------------------------------------------------------------------------
def test_two_segment_message_data() -> None:
    """GEM-15 正例：精良成品分解 → material_seg + gem_seg + message 分行，档位标签精确。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["flame_bomb_uncommon"], job_tier_index=3)  # 专家 0.5
    assert r["ok"] is True
    assert r["quality_tier"] == "uncommon"
    assert r["quality_label"] == "精良"
    assert r["gem"] == 3
    assert r["materials"] == [("water_crystal", "水结晶", 2)]  # ⌊5×0.5⌋=2
    assert r["material_seg"] == "水结晶×2"   # 材料回收段
    assert r["gem_seg"] == "宝石×3"          # 宝石段
    assert r["message"] == "分解返还：水结晶×2\n宝石×3"  # 两段分行（GEM-15）


def test_two_segment_message_zero_gem() -> None:
    """GEM-15 反例：未知品质档 → 宝石 0（quality_unknown 标注），消息宝石段 ×0。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["unknown_quality_item"], job_tier_index=3)
    assert r["ok"] is True
    assert r["gem"] == 0
    assert r["quality_unknown"] is True
    assert r["quality_tier"] is None
    assert r["gem_seg"] == "宝石×0"


# ---------------------------------------------------------------------------
# 工程补白（GW-1/3/4/10/12）
# ---------------------------------------------------------------------------
def test_gw1_is_decomposable() -> None:
    """GW-1：quality+traits → 可分解；缺品质/缺特性/非映射 → 不可分解。"""
    w = _wallet()
    assert w.is_decomposable(ITEMS["flame_bomb"]) is True
    assert w.is_decomposable(ITEMS["jewel_burn_rare"]) is True
    assert w.is_decomposable(ITEMS["mana_potion"]) is False       # 无品质
    assert w.is_decomposable(ITEMS["flame_bomb_plain"]) is False  # 有品质无特性
    assert w.is_decomposable(ITEMS["trait_only_item"]) is False   # 有特性无品质
    assert w.is_decomposable(None) is False
    assert w.is_decomposable("str") is False


def test_gw3_quality_stamp_forms() -> None:
    """GW-3：品质章 = 档位串/int 品质分/{tier|score} 映射 全部解析到档位与宝石。"""
    w = _wallet()
    ctx = make_ctx()
    assert w.decompose(ctx, ITEMS["score_item"], job_tier_index=6)["gem"] == 20      # 85→legendary
    assert w.decompose(ctx, ITEMS["tier_map_item"], job_tier_index=3)["gem"] == 8    # {tier:rare}
    assert w.decompose(ctx, ITEMS["score_map_item"],
                       job_tier_index=3)["gem"] == 8  # {score:70}→rare


def test_gw10_item_decompose_table_priority() -> None:
    """GW-10：item 自带 decompose 表优先于配方查找（6×0.5→3 火晶石，无配方仍可算）。"""
    w = _wallet()
    r = w.decompose(make_ctx(), ITEMS["flame_bomb_own_table"], job_tier_index=3)
    assert r["ok"] is True
    assert r["materials"] == [("fire_crystal", "火晶石", 3)]
    assert r["gem"] == 8  # rare 平铺


def test_gw12_decompose_is_pure_computation() -> None:
    """GW-12：decompose 纯计算——不删物品、不入包、不入账（原子落账归指令壳）。"""
    w = _wallet()
    ctx = make_ctx()
    before = {"currencies": dict(ctx["currencies"]), "inventory": dict(ctx["inventory"])}
    r = w.decompose(ctx, ITEMS["doomsday_bomb"], count=2, job_tier_index=6)
    assert r["ok"] is True
    assert ctx["currencies"] == before["currencies"]  # gem 未入账
    assert ctx["inventory"] == before["inventory"]   # 物品未扣/材料未返


def test_quality_system_injection() -> None:
    """正例：构造器注入自定义 QualitySystem（3 档）兜底档位判定不抛异常。"""
    qs = QualitySystem(quality_tiers={
        "common": [0, 39], "uncommon": [40, 79], "rare": [80, 100],
    })
    w = _wallet(quality=qs)
    assert w.decompose(make_ctx(), ITEMS["score_item"],
                       job_tier_index=6)["gem"] == 8  # 85→rare(3档)
