"""HarvestEngine 种植收获引擎单测（M8 批10·路10A · qbot_rpg/core/alchemy_harvest.py）。

文件：tests/unit/test_alchemy_harvest.py
创建：2026-08-29
作者：Hermes 子agent-10A
功能：HarvestEngine 纯函数直测（对齐 test_synthesis/test_gem_wallet 模式）——种植（GU-60/61 +
  F-21）/ 定时收获（品质 ≥ 种子品质、种子继承特性按职业继承项）/ 温室（大师解锁复制素材耗
  宝石+金币 滚雪球）/ 地块存档（player.farm_plots dict）。每条正例 + 反例。

依据：
  - docs/m8_contract_指令契约.md §20（/种植 /收获：GU-60/61、F-21、M-21）
  - /root/docs_archive/RPG框架项目/炼金系统设计定稿.md L381/L392/L402/L442-448
  - /root/docs_archive/RPG框架项目/职业熟练度与生活系统设计定稿.md L56-58/L92-96/L155
  - docs/细化/细化_2c5c_种植品评代工.md 一（FARM-01~10）+ 验收 TC-01~08
  - docs/细化/细化_2c4e_品质与特性.md（INH-14/STO-06）

覆盖矩阵（每条正例 + 反例，断言精确数值/档位/消息/存档）：
  GU-60   正式（tier 1）种植成功；见习（tier 0）种植/收获拒绝 level_insufficient
  GU-61a  种子不存在拒绝 seed_not_found；无 seed 标记物品拒绝 seed_not_found；
          背包无种子拒绝 seed_missing
  GU-61b  地块满拒绝 no_free_plot；指定地块占用拒绝 plot_occupied；地块序号非法拒绝
  F-21    种植写地块 {seed, planted_at, harvest_at=now+harvest_sec}；消息「已种植〈种子〉，
          4 小时后可收获」（M5 纯文本零 emoji）；/收获 无参收全部成熟地块
  FARM-02 harvest_sec 默认 14400 可配（7200 → 2 小时）；单种子 harvest_sec 覆盖
  FARM-03 种子继承特性：正式 1 项 / 精通 2 项；超出丢弃并提示（dropped + message 段）
  FARM-04 收获品质 ≥ 种子品质（quality_floor 保底；seed:true 形态取种子自身 quality）
  FARM-06/07 温室：大师（tier 4）前拒绝；大师后复制素材 → 素材入包滚雪球
  FARM-08 温室消耗 宝石 10 + 金币 1000（ARB-00 分账 gem_balance/coins_balance）；
          消耗不足拒绝 currency_shortfall
  FARM-10 地块存档 player.farm_plots dict；plots_of 查看；收获后地块清空；重载保留
  工程补白  H-1 seed 两形态（true / {output,quality_floor,traits,harvest_sec,count}）
           H-6 消耗 1 颗种子 / H-7 入包 bound=False / H-9 纯文本无 emoji / 原子回滚

测试风格对齐 tests/unit/test_gem_wallet.py：纯 pytest、零 NoneBot；ctx 顶层即玩家状态
（items/traits/currencies/inventory），settings 构造器注入。
"""
from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

from qbot_rpg.core.alchemy_harvest import (
    DEFAULT_GREENHOUSE_COPY_COST,
    DEFAULT_HARVEST_SEC,
    DEFAULT_PLOTS_MAX,
    DEFAULT_TRAIT_INHERIT,
    HarvestEngine,
)
from qbot_rpg.core.quality import QualitySystem

# ---------------------------------------------------------------------------
# 夹具
# ---------------------------------------------------------------------------

ITEMS: Dict[str, Mapping[str, Any]] = {
    # 收获表形态种子（H-1：seed: {output, quality_floor, traits}）
    "tomato_seed": {
        "id": "tomato_seed", "name": "番茄种子", "type": "种子", "price": 20,
        "seed": {"output": "tomato", "quality_floor": 40,
                 "traits": ["trait_sweet", "trait_fresh"]},
    },
    "tomato": {"id": "tomato", "name": "番茄", "type": "material", "price": 10},
    # 简单形态种子（H-1：seed: true，收获=种子自身，品质/特性取种子字段）
    "fire_herb_seed": {
        "id": "fire_herb_seed", "name": "火焰草种子", "type": "种子", "price": 50,
        "seed": True, "quality": 50, "traits": ["trait_burn_boost"],
    },
    # 单种子时长覆盖 + 产出量（H-1/FARM-02）
    "iron_seed": {
        "id": "iron_seed", "name": "铁矿种子", "type": "种子", "price": 30,
        "seed": {"output": "iron_ore", "quality_floor": "common", "count": 2,
                 "harvest_sec": 7200},
    },
    "iron_ore": {"id": "iron_ore", "name": "铁矿", "type": "material", "price": 15},
    # 非种子素材（GU-61a 反例）
    "herb": {"id": "herb", "name": "草药", "type": "material", "price": 5},
}

TRAITS: Dict[str, Mapping[str, Any]] = {
    "trait_sweet": {"id": "trait_sweet", "name": "甘甜", "rarity": "normal"},
    "trait_fresh": {"id": "trait_fresh", "name": "鲜嫩", "rarity": "normal"},
    "trait_burn_boost": {"id": "trait_burn_boost", "name": "灼烧强化", "rarity": "normal"},
}

DEFAULT_SETTINGS: Dict[str, Any] = {
    "alchemy": {
        "farming": {
            "enabled": True,
            "harvest_sec": DEFAULT_HARVEST_SEC,
            "plots_max": DEFAULT_PLOTS_MAX,
            "trait_inherit": dict(DEFAULT_TRAIT_INHERIT),
            "greenhouse": {
                "unlock_tier": "大师",
                "copy_cost": dict(DEFAULT_GREENHOUSE_COPY_COST),
            },
        },
    },
}


def _engine(settings: Optional[Mapping[str, Any]] = None,
            quality: Optional[QualitySystem] = None) -> HarvestEngine:
    """构造引擎：settings/quality 构造器注入（单源）；缺省走 DEFAULT_SETTINGS。"""
    return HarvestEngine(
        settings=settings if settings is not None else DEFAULT_SETTINGS,
        quality=quality,
    )


def _player(tier: int = 1) -> MutableMapping[str, Any]:
    """玩家状态 dict（炼金职业档位 tier 0~6，对齐 proficiency node level 口径）。"""
    return {"qid": "u1", "name": "阿伟",
            "proficiency": {"alchemy": {"level": tier}}}


def make_ctx(**over: Any) -> MutableMapping[str, Any]:
    """全字段种植 ctx（每场景新造避免互污染）。"""
    base: Dict[str, Any] = {
        "qid": "u1",
        "currencies": {"coins": 2000, "gem": 20},
        "inventory": {"tomato_seed": 3, "fire_herb_seed": 2, "iron_seed": 1},
        "items": ITEMS,
        "traits": TRAITS,
    }
    base.update(over)
    return base


# ---------------------------------------------------------------------------
# GU-60 职业 ≥ 正式（种植解锁，熟练度 L56）
# ---------------------------------------------------------------------------
def test_tc29_formal_player_plant_ok() -> None:
    """TC-29 正例：正式玩家 /种植 番茄种子 → 地块占用、harvest_at=now+14400、消耗 1 种子。"""
    eng = _engine()
    player = _player(tier=1)
    ctx = make_ctx()
    now = 1_750_000_000
    r = eng.plant(player, ctx, "tomato_seed", now=now)
    assert r["ok"] is True
    assert r["reason"] is None
    assert r["seed_id"] == "tomato_seed"
    assert r["seed_name"] == "番茄种子"
    assert r["plot_index"] == 1
    assert r["planted_at"] == now
    assert r["harvest_at"] == now + DEFAULT_HARVEST_SEC
    # M-21 纯文本（M5 无 emoji）+ 4 小时提示
    assert r["message"] == "已种植〈番茄种子〉，4 小时后可收获"
    assert "🌱" not in r["message"]
    # 地块存档（F-21 数据落点 + FARM-10）
    assert player["farm_plots"][1] == {
        "seed": "tomato_seed", "planted_at": now, "harvest_at": now + DEFAULT_HARVEST_SEC,
    }
    # 消耗 1 颗种子（FARM-01/H-6）
    assert ctx["inventory"]["tomato_seed"] == 2


def test_tc29_formal_required_rejected() -> None:
    """GU-60 反例：见习（tier 0）/种植 与 /收获 → 拒绝 level_insufficient。"""
    eng = _engine()
    p_plant = _player(tier=0)
    r1 = eng.plant(p_plant, make_ctx(), "tomato_seed", now=100)
    assert r1["ok"] is False
    assert r1["reason"] == "level_insufficient"
    assert "正式" in r1["message"]
    p_harvest = _player(tier=0)
    r2 = eng.harvest(p_harvest, make_ctx(), now=100)
    assert r2["ok"] is False
    assert r2["reason"] == "level_insufficient"


def test_plant_seed_not_found_rejected() -> None:
    """GU-61a 反例：种子不存在 / 物品无 seed 标记 → seed_not_found。"""
    eng = _engine()
    # 注册表查无
    r1 = eng.plant(_player(), make_ctx(), "no_such_seed", now=100)
    assert r1["ok"] is False and r1["reason"] == "seed_not_found"
    # 存在但无 seed 标记（GU-61 种子存在且带 seed 标记）
    r2 = eng.plant(_player(), make_ctx(), "herb", now=100)
    assert r2["ok"] is False and r2["reason"] == "seed_not_found"
    assert "seed" in r2["message"]


def test_plant_seed_missing_inventory_rejected() -> None:
    """GU-61/H-6 反例：背包无种子道具 → seed_missing 拒绝（不扣、不占地块）。"""
    eng = _engine()
    r = eng.plant(_player(), make_ctx(inventory={}), "tomato_seed", now=100)
    assert r["ok"] is False and r["reason"] == "seed_missing"
    assert "背包中没有" in r["message"]
    assert "farm_plots" not in _player()  # 玩家未被写入地块


# ---------------------------------------------------------------------------
# GU-61b 空闲地块（FARM-01 地块满拒绝）
# ---------------------------------------------------------------------------
def test_tc29_no_free_plot_rejected() -> None:
    """GU-61b 反例：3 地块种满 → 第 4 次 /种植 拒绝 no_free_plot。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx(inventory={"tomato_seed": 10})
    for i in range(1, DEFAULT_PLOTS_MAX + 1):
        r = eng.plant(player, ctx, "tomato_seed", now=100 * i)
        assert r["ok"] is True and r["plot_index"] == i
    r = eng.plant(player, ctx, "tomato_seed", now=999)
    assert r["ok"] is False and r["reason"] == "no_free_plot"
    assert f"上限 {DEFAULT_PLOTS_MAX}" in r["message"]
    # 第 4 块地未被占用（地块数仍 = 3）
    assert len(player["farm_plots"]) == DEFAULT_PLOTS_MAX


def test_plant_plot_index_specific() -> None:
    """GU-61b 指定地块：占用 plot_occupied / 非法序号 plot_index_invalid / 指定空位成功。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx(inventory={"tomato_seed": 10})
    # 非法序号
    r = eng.plant(player, ctx, "tomato_seed", now=100, plot_index=0)
    assert r["ok"] is False and r["reason"] == "plot_index_invalid"
    r = eng.plant(player, ctx, "tomato_seed", now=100, plot_index=99)
    assert r["ok"] is False and r["reason"] == "plot_index_invalid"
    # 指定空位 2
    r = eng.plant(player, ctx, "tomato_seed", now=100, plot_index=2)
    assert r["ok"] is True and r["plot_index"] == 2
    # 占用后再指定 → 拒绝
    r = eng.plant(player, ctx, "tomato_seed", now=200, plot_index=2)
    assert r["ok"] is False and r["reason"] == "plot_occupied"


# ---------------------------------------------------------------------------
# F-21 定时收获（FARM-02/03/04/06/10）
# ---------------------------------------------------------------------------
def test_tc29_harvest_before_mature_rejected() -> None:
    """TC-29 正例前半：种植后未到 harvest_at → /收获 拒绝 no_mature（未成熟）。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx()
    now = 1_750_000_000
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + 100)
    assert r["ok"] is False and r["reason"] == "no_mature"
    assert "未成熟" in r["message"]
    # 地块仍在（未误清空）
    assert len(player["farm_plots"]) == 1


def test_tc29_harvest_ok_quality_floor_and_traits() -> None:
    """TC-29 正例：到点收获 → 品质 ≥ 种子品质 40（精良）+ 继承特性（正式 1 项）+ 地块清空。"""
    eng = _engine()
    player = _player(tier=1)  # 正式：特性继承 1 项（FARM-03/INH-14）
    ctx = make_ctx()
    now = 1_750_000_000
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)
    assert r["ok"] is True
    h = r["harvested"][0]
    assert h["plot_index"] == 1
    assert h["output"] == "tomato" and h["output_name"] == "番茄"
    assert h["count"] == 1
    assert h["quality_score"] == 40          # = quality_floor（FARM-04：收获品质 ≥ 种子品质）
    assert h["quality_tier"] == "uncommon"
    assert h["quality_label"] == "精良"       # STO-06 品质文字档
    assert h["traits"] == ["trait_sweet"]     # 正式继承 1 项
    assert h["trait_names"] == ["甘甜"]
    assert h["dropped"] == ["trait_fresh"]    # 超出丢弃（FARM-03）
    assert "收获〈番茄〉×1（品质 精良·继承特性：甘甜）" in r["message"]
    assert "超出继承上限丢弃：鲜嫩" in r["message"]   # FARM-03 提示
    assert "🌾" not in r["message"]            # M5 纯文本
    # 入包 + 地块清空（FARM-06/F-21）
    assert ctx["inventory"]["tomato"] == 1
    assert player["farm_plots"] == {}


def test_tc29_harvest_all_mature_plots_aggregated() -> None:
    """F-21 正例：/收获 无参收全部成熟地块，多地块折叠单条消息（RATE-05）。"""
    eng = _engine()
    player = _player(tier=3)  # 专家：特性继承 3 项
    ctx = make_ctx(inventory={"tomato_seed": 10, "fire_herb_seed": 2})
    now = 1_750_000_000
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    assert eng.plant(player, ctx, "fire_herb_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)
    assert r["ok"] is True
    assert len(r["harvested"]) == 2
    names = [h["output_name"] for h in r["harvested"]]
    assert names == ["番茄", "火焰草种子"]  # fire_herb_seed 简单形态：收获=种子自身
    assert ctx["inventory"]["tomato"] == 1
    # fire_herb_seed：2 持有 -1 种植消耗 +1 收获入包 = 2（简单形态产出=种子自身）
    assert ctx["inventory"]["fire_herb_seed"] == 2
    assert player["farm_plots"] == {}


def test_harvest_no_plots_rejected() -> None:
    """F-21 反例：无任何种植地块 → /收获 拒绝 no_plots。"""
    eng = _engine()
    r = eng.harvest(_player(), make_ctx(), now=100)
    assert r["ok"] is False and r["reason"] == "no_plots"
    assert "还没有种植" in r["message"]


def test_harvest_sec_configurable() -> None:
    """FARM-02 正例：harvest_sec=7200 → 新种 2 小时可收；单种子 harvest_sec 覆盖全局。"""
    settings = {"alchemy": {"farming": {"enabled": True, "harvest_sec": 7200}}}
    eng = _engine(settings=settings)
    player = _player()
    ctx = make_ctx(inventory={"tomato_seed": 5, "iron_seed": 1})
    now = 1_750_000_000
    # 全局 7200 → 番茄种子 2 小时
    r1 = eng.plant(player, ctx, "tomato_seed", now=now)
    assert r1["harvest_at"] == now + 7200
    assert r1["message"] == "已种植〈番茄种子〉，2 小时后可收获"
    # 单种子覆盖 7200 == 全局，取 iron_seed 也 7200（覆盖值生效）
    r2 = eng.plant(player, ctx, "iron_seed", now=now)
    assert r2["harvest_at"] == now + 7200
    # 已种地块不受改配影响（FARM-02 按种植时配置结算）：改配后旧地块 harvest_at 不变
    assert player["farm_plots"][r1["plot_index"]]["harvest_at"] == now + 7200


def test_harvest_seed_per_output_count() -> None:
    """H-1/FARM-05 正例：seed 收获表 count=2 → 收获产出 ×2（M-21 ×N）。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx(inventory={"iron_seed": 1})
    now = 1_750_000_000
    assert eng.plant(player, ctx, "iron_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + 7200)
    assert r["ok"] is True
    h = r["harvested"][0]
    assert h["output"] == "iron_ore" and h["count"] == 2
    assert h["quality_label"] == "普通"  # quality_floor "common"
    assert ctx["inventory"]["iron_ore"] == 2
    assert "收获〈铁矿〉×2（品质 普通）" in r["message"]


def test_trait_cap_by_tier() -> None:
    """FARM-03/INH-14 正例：正式 1 项 / 精通 2 项继承；见习 0（种植已拦）；超专家取专家 3。"""
    eng = _engine()
    # 精通（tier 2）→ 继承 2 项（种子 2 特性全继承，无丢弃）
    player2 = _player(tier=2)
    ctx2 = make_ctx()
    now = 100
    assert eng.plant(player2, ctx2, "tomato_seed", now=now)["ok"] is True
    r2 = eng.harvest(player2, ctx2, now=now + DEFAULT_HARVEST_SEC)
    h2 = r2["harvested"][0]
    assert h2["traits"] == ["trait_sweet", "trait_fresh"]
    assert h2["dropped"] == []
    assert "继承特性：甘甜、鲜嫩" in r2["message"]
    # 专家（tier 3）→ 继承 3 项（种子仅 2 项，全继承）
    player3 = _player(tier=3)
    ctx3 = make_ctx()
    assert eng.plant(player3, ctx3, "tomato_seed", now=now)["ok"] is True
    r3 = eng.harvest(player3, ctx3, now=now + DEFAULT_HARVEST_SEC)
    assert r3["harvested"][0]["traits"] == ["trait_sweet", "trait_fresh"]


def test_simple_seed_form_quality_from_seed() -> None:
    """H-1/H-2 正例：seed:true 简单形态 → 收获=种子自身、品质取种子 quality、特性取种子 traits。"""
    eng = _engine()
    player = _player(tier=1)
    ctx = make_ctx()
    now = 100
    assert eng.plant(player, ctx, "fire_herb_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)
    h = r["harvested"][0]
    assert h["output"] == "fire_herb_seed"
    assert h["quality_score"] == 50
    assert h["quality_label"] == "精良"  # 50 → uncommon
    assert h["traits"] == ["trait_burn_boost"]
    assert h["trait_names"] == ["灼烧强化"]
    assert ctx["inventory"]["fire_herb_seed"] == 2  # 已种 1 消耗 → 2-1=1 + 收获 1 = 2


# ---------------------------------------------------------------------------
# 温室（FARM-07/08：大师解锁 · 复制素材 · 耗宝石/金币）
# ---------------------------------------------------------------------------
def test_tc29_greenhouse_master_required() -> None:
    """FARM-07 反例：大师前（专家 tier 3）/温室 → 拒绝 level_insufficient。"""
    eng = _engine()
    r = eng.greenhouse(_player(tier=3), make_ctx(), "tomato_seed", now=100)
    assert r["ok"] is False and r["reason"] == "level_insufficient"
    assert "大师" in r["message"]


def test_tc29_greenhouse_copy_ok() -> None:
    """TC-29 正例：大师 /温室 复制番茄 → 素材入包滚雪球 + 扣宝石 10 + 金币 1000（分账）。"""
    eng = _engine()
    player = _player(tier=4)  # 大师
    ctx = make_ctx(currencies={"coins": 2000, "gem": 20}, inventory={})
    r = eng.greenhouse(player, ctx, "tomato_seed", now=100)
    assert r["ok"] is True
    assert r["material_id"] == "tomato" and r["material_name"] == "番茄"
    assert r["gem_cost"] == 10 and r["coins_cost"] == 1000
    assert r["gem_balance"] == 10 and r["coins_balance"] == 1000  # ARB-00 分账
    assert ctx["currencies"]["gem"] == 10 and ctx["currencies"]["coins"] == 1000
    assert ctx["inventory"]["tomato"] == 1  # 素材入包（滚雪球可再投复制/合成）
    assert r["message"] == "温室复制〈番茄〉×1（消耗 宝石 10 + 金币 1000）"


def test_tc29_greenhouse_insufficient_rejected() -> None:
    """FARM-08 反例：宝石/金币不足 → currency_shortfall，不扣不产。"""
    eng = _engine()
    # 宝石不足（默认需 10）
    ctx1 = make_ctx(currencies={"coins": 2000, "gem": 5}, inventory={})
    r1 = eng.greenhouse(_player(tier=4), ctx1, "tomato_seed", now=100)
    assert r1["ok"] is False and r1["reason"] == "currency_shortfall"
    assert "宝石 10" in r1["message"]
    assert ctx1["currencies"]["gem"] == 5 and "tomato" not in ctx1["inventory"]
    # 金币不足（默认需 1000）
    ctx2 = make_ctx(currencies={"coins": 500, "gem": 20}, inventory={})
    r2 = eng.greenhouse(_player(tier=4), ctx2, "tomato_seed", now=100)
    assert r2["ok"] is False and r2["reason"] == "currency_shortfall"
    assert "金币 1000" in r2["message"]
    assert ctx2["currencies"]["coins"] == 500


def test_greenhouse_not_seed_rejected() -> None:
    """FARM-07 反例：/温室 复制非种子素材 → seed_not_found（须为带 seed 标记种子）。"""
    eng = _engine()
    r = eng.greenhouse(_player(tier=4), make_ctx(), "herb", now=100)
    assert r["ok"] is False and r["reason"] == "seed_not_found"


# ---------------------------------------------------------------------------
# FARM-10 地块存档（player.farm_plots dict / plots_of 查看 / 重载保留）
# ---------------------------------------------------------------------------
def test_tc29_plots_archive() -> None:
    """FARM-10 正例：多地块存档 dict + plots_of 查看（按序号升序，字段完整）。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx(inventory={"tomato_seed": 5, "fire_herb_seed": 2})
    now = 1_750_000_000
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    assert eng.plant(player, ctx, "fire_herb_seed", now=now + 60)["ok"] is True
    plots = eng.plots_of(player)
    assert [p["plot_index"] for p in plots] == [1, 2]
    assert plots[0]["seed_id"] == "tomato_seed"
    assert plots[0]["planted_at"] == now
    assert plots[0]["harvest_at"] == now + DEFAULT_HARVEST_SEC
    assert plots[1]["seed_id"] == "fire_herb_seed"
    # 存档落点 = player.farm_plots（定稿 L402 / H-4）
    assert set(player["farm_plots"].keys()) == {1, 2}


def test_plots_archive_after_harvest_cleared() -> None:
    """FARM-10 正例：收获后地块清空 → plots_of 返回空列表。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx()
    now = 100
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    assert eng.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)["ok"] is True
    assert eng.plots_of(player) == []


def test_plots_survive_reload() -> None:
    """FARM-10 正例：重载（新引擎实例读同一存档 dict）→ 地块完整保留、倒计时按 harvest_at 重算。"""
    eng1 = _engine()
    player = _player()
    ctx = make_ctx()
    now = 1_750_000_000
    assert eng1.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    # 新引擎实例 = 重载后（存档 dict 保留在 player 上）
    eng2 = _engine()
    plots = eng2.plots_of(player)
    assert plots[0]["seed_id"] == "tomato_seed"
    assert plots[0]["harvest_at"] == now + DEFAULT_HARVEST_SEC
    # 重载后到点仍可收（按 harvest_at 判定，不重置）
    r = eng2.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)
    assert r["ok"] is True and r["harvested"][0]["output"] == "tomato"


# ---------------------------------------------------------------------------
# 模块开关（FARM：四件套可独立开关）
# ---------------------------------------------------------------------------
def test_farming_module_disabled() -> None:
    """FARM 反例：farming.enabled=false → 种植/收获/温室全部拒绝 mode_off。"""
    eng = _engine(settings={"alchemy": {"farming": {"enabled": False}}})
    assert eng.plant(_player(), make_ctx(), "tomato_seed", now=100)["ok"] is False
    assert eng.harvest(_player(), make_ctx(), now=100)["ok"] is False
    assert eng.greenhouse(_player(tier=4), make_ctx(), "tomato_seed", now=100)["ok"] is False


# ---------------------------------------------------------------------------
# 工程补白：H-7 入包失败原子回滚 / 消息零 emoji
# ---------------------------------------------------------------------------
def test_harvest_add_item_failure_rollback() -> None:
    """H-7/原子反例：收获入包失败（add_item 返回 False）→ 整批回滚、地块不误清空。"""
    eng = _engine()
    player = _player()
    ctx = make_ctx(inventory={"tomato_seed": 1}, items=ITEMS, traits=TRAITS)

    def _bad_add(*_a: Any, **_k: Any) -> bool:
        return False

    ctx["add_item"] = _bad_add
    ctx["count_item"] = lambda _i: 1
    ctx["remove_item"] = lambda _i, _c: True
    now = 100
    assert eng.plant(player, ctx, "tomato_seed", now=now)["ok"] is True
    r = eng.harvest(player, ctx, now=now + DEFAULT_HARVEST_SEC)
    assert r["ok"] is False and r["reason"] == "add_item_failed"
    # 地块保留（未误清空，未误入包）
    assert len(player["farm_plots"]) == 1


def test_messages_plain_text_no_emoji() -> None:
    """H-9/M5 正例：引擎全部消息零 emoji（含拒绝场景）。

    仅检查 emoji 字符范围（U+1F000-1FAFF / U+2600-27BF / VS16 / ZWJ，对齐
    tests/unit/test_emoji_discipline.py 口径）；中文等 CJK 字符不在此范围。
    """
    import re

    _EMOJI = re.compile(
        r"[\U0001F000-\U0001FAFF]"
        r"|[\U00002600-\U000027BF]"
        r"|\ufe0f"
        r"|\u200d"
    )
    eng = _engine()
    samples = [
        eng.plant(_player(), make_ctx(), "tomato_seed", now=100)["message"],
        eng.harvest(_player(), make_ctx(), now=100)["message"],
        eng.plant(_player(tier=0), make_ctx(), "tomato_seed", now=100)["message"],
    ]
    player = _player()
    ctx = make_ctx()
    assert eng.plant(player, ctx, "tomato_seed", now=100)["ok"] is True
    samples.append(eng.harvest(player, ctx, now=100 + DEFAULT_HARVEST_SEC)["message"])
    samples.append(eng.greenhouse(_player(tier=4), make_ctx(), "tomato_seed", now=100)["message"])
    for msg in samples:
        assert not _EMOJI.search(msg), f"消息含 emoji/装饰符号: {msg!r}"
