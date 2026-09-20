"""批58 · 示例包 `content/zz_craft_demo` 只读回归（真机宿主 + 引擎断言）。

定位：示例包本身是**内容**（不是测试夹具）。本用例遵守批58 纪律——
  · **只读**真实示例包（一个字节都不写；不 copytree 到仓库其它位置）；
  · 玩家存档用**内存库**（`pack_app` 缺省），随机/相性判定用**固定注入种子**或**确定性路径**；
  · 断言示例包「红拦 0」+ 关键数据形状 + 相性正/负 + 打造/分解/淬炼真机链路（确定性部分）。

依据：`/root/deliverables/打造_材料表与图纸表_草案v2.md`（24 材料 / 6 图纸 / 逐档手算）+
`深炼金相性_玩法口径_可开工版.md` §七 + 批54 `content/effect_presets.py` + 批57 `core/temper.py`；
实现说明 `docs/深度打造_实现说明.md` §二十。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.assembly.testing_support import pack_app, send_command, validate_pack_data
from qbot_rpg.content.deep_craft_settings import read_deep_craft_settings
from qbot_rpg.content.enhance_models import parse_enhance_settings
from qbot_rpg.core.affinity import normalize_affinity_config, resolve_available_entries
from qbot_rpg.core.deep_craft import plan_affixes
from qbot_rpg.core.temper import (
    materialize_temper,
    normalize_temper_config,
    plan_temper,
    total_cap_of,
)
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import Player

REPO = Path(__file__).resolve().parents[2]
PACK = REPO / "content" / "zz_craft_demo"
QID = "58001"
BP_NAME = "见习脉铁剑图纸"
CRAFT_A = "风脊晶壳*4 脉晶碎片*4 苔脉草*4 骸骨灰*3"

_MATS = [
    "pulse_candy", "mossvein_herb", "vein_shard", "ridge_ore", "bone_ash",
    "wind_ridge_shell", "frost_marrow", "lunar_eclipse_stone", "ember_slag",
    "crystal_mane", "mire_root", "nightsong_wing", "eroded_plate", "glacier_core",
    "moonwell_dew", "verdant_amber", "cinder_heart", "frostbound_crown",
    "abyss_lord_core", "everfrost_shell", "night_king_crown", "tideheart_pearl",
    "starfall_ingot", "eclipse_sovereign",
]


def _read(name: str) -> Any:
    return json.loads((PACK / name).read_text(encoding="utf-8"))


def _mk_player() -> Player:
    inv = [ItemInstance(item_id=m, name=m, count=30, quality="normal", bound=False)
           for m in _MATS]
    inv.append(ItemInstance(item_id="bp_apprentice_vein_blade", name=BP_NAME, count=2,
                            quality="normal", bound=False))
    return Player(
        qid=QID, name="示例匠", job_id="warrior", level=35, hp=999, mp=999,
        currencies={"coins": 0, "gem": 0, "essence": 200000},
        inventory=tuple(inv),
        persistent_state={
            "proficiency": {
                "forging": {"level": 0, "exp": 0, "sp_earned": 0, "sp_used": 0,
                            "unlocks": {}},
                "alchemy": {"level": 60, "exp": 0, "sp_earned": 0, "sp_used": 0,
                            "unlocks": {}},
            },
            "learned_blueprints": {},
        },
    )


# ---------------------------------------------------------------------------
# A. 整包校验 + 数据形状（只读）
# ---------------------------------------------------------------------------
def test_pack_validates_red_and_yellow_zero() -> None:
    """示例包跑既有校验器：红拦 0 / 黄提示 0。"""
    report = validate_pack_data(PACK)
    assert report.ok, report.errors
    assert report.errors == ()
    assert report.warnings == ()


def test_pack_data_shape() -> None:
    """24 材料（每档 6）+ 6 图纸（铜2/银2/金1/彩1）+ 4 相性 + 3 类互动 + 特效预设示例。"""
    items = _read("items.json")
    mats = [e for e in items if e.get("type") == "material"]
    bps = [e for e in items if e.get("type") == "blueprint"]
    assert len(mats) == 24
    assert len(bps) == 6
    # 每档 6 种（按草案 §七 A-9 档位）
    def _band(lv: int) -> str:
        return "copper" if lv <= 8 else "silver" if lv <= 16 else (
            "gold" if lv <= 26 else "rainbow")
    counts: Dict[str, int] = {}
    for m in mats:
        counts[_band(int(m["material_level"]))] = counts.get(_band(
            int(m["material_level"])), 0) + 1
    assert counts == {"copper": 6, "silver": 6, "gold": 6, "rainbow": 6}
    grades: Dict[str, int] = {}
    for b in bps:
        grades[str(b["blueprint_grade"])] = grades.get(str(b["blueprint_grade"]), 0) + 1
    assert grades == {"copper": 2, "silver": 2, "gold": 1, "rainbow": 1}
    settings = _read("settings.json")
    assert len(settings["affinities"]) == 4
    kinds = sorted({r["kind"] for r in settings["affinity_reactions"]})
    assert kinds == ["amplify", "conflict", "reverse"]


def test_effect_preset_terms_are_named_tier_values() -> None:
    """示例装备词条 ≥8 条且含双方向对（会心 ± / 受疗 ±）——取值 = 批54 normal 档。"""
    from qbot_rpg.content.effect_presets import find_effect_preset

    items = _read("items.json")
    used: List = []
    for e in items:
        if e.get("type") == "weapon" or e.get("type", "").startswith("armor"):
            for axis in ("damage_dealt_pct", "crit_damage_pct", "healing_received_pct",
                         "resource_cost_pct", "action_bar_shift", "status_resist_pct",
                         "status_chance_pct", "stack_gain_pct"):
                if axis in e:
                    used.append((axis, e[axis]))
    assert len(used) >= 8
    # 会心：+10（会心锋刃）与 −10（钝锋）——同族两方向
    assert ("crit_damage_pct", 10) in used and ("crit_damage_pct", -10) in used
    # 受疗：+15（强疗）与 −15（重伤）
    assert ("healing_received_pct", 15) in used and ("healing_received_pct", -15) in used
    # 取值确为批54 预设 normal 档（不臆造）
    assert find_effect_preset("weapon_crit_up")["tiers"]["normal"] == 10
    assert find_effect_preset("weapon_crit_down")["tiers"]["normal"] == -10
    assert find_effect_preset("armor_heal_up")["tiers"]["normal"] == 15
    assert find_effect_preset("armor_heal_down")["tiers"]["normal"] == -15


# ---------------------------------------------------------------------------
# B. 相性：正/负断言（引擎层，固定种子）
# ---------------------------------------------------------------------------
def test_affinity_negative_no_affinity_cannot_draw_required_entries() -> None:
    """无相性投入 → `requires_affinity` 词条抽不出（负向断言）。"""
    settings = _read("settings.json")
    entries = resolve_available_entries(normalize_affinity_config(settings), None, None)
    assert entries, "通用池仍应可查"
    assert not [e for e in entries if e.get("requires_affinity")]
    assert not [e for e in entries if e.get("_pool") == "pool_lunar"]
    plan = plan_affixes(
        blueprint={"blueprint_random_stat_count": {"min": 2, "max": 2},
                   "blueprint_random_set_affix_count": {"min": 0, "max": 0}},
        materials=[], config=read_deep_craft_settings(settings),
        rng=random.Random(7), affinity_config=settings,
        affinity_reactions=settings.get("affinity_reactions") or (), level=5)
    pools = {r["pool"] for r in plan["random_stats"]}
    assert pools <= {"pool_common"}


def test_affinity_positive_linkage_pool_and_variant() -> None:
    """主=月华 副=霜晶 → 联动池覆盖专属池（可抽到联动条目）。"""
    settings = _read("settings.json")
    plan = plan_affixes(
        blueprint={"affinities": {"lunar": 10, "frost": 5},
                   "blueprint_random_stat_count": {"min": 2, "max": 2},
                   "blueprint_random_set_affix_count": {"min": 1, "max": 1},
                   "blueprint_random_set_affix_pool": "pool_link_lunar_frost"},
        materials=[{"affinities": {"lunar": 20}, "quality": "紫", "count": 1}],
        config=read_deep_craft_settings(settings), rng=random.Random(11),
        affinity_config=settings,
        affinity_reactions=settings.get("affinity_reactions") or (), level=12)
    assert plan["affinity"]["main"] == "lunar"
    assert plan["affinity"]["sub"] == "frost"
    assert plan["random_set_affixes"] == ["set_eclipse_sovereign"]


# ---------------------------------------------------------------------------
# C. 真机链路：学习 → 打造 → 分解 → 淬炼（确定性断言）
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_full_host_craft_decompose_temper() -> None:
    """`/精造` 学习 → 投料打造（产出 uid 实例）→ `/分解 <uid>` → `core/temper` 淬炼。"""
    async with pack_app(PACK) as deps:
        repo = deps.repo
        await repo.save_player(_mk_player())

        learn = await send_command(deps, f"/精造 学习 {BP_NAME}", user_id=QID)
        assert "已学会" in learn

        crafted: List[Any] = []
        for _ in range(2):
            msg = await send_command(deps, f"/精造 {BP_NAME} {CRAFT_A}", user_id=QID)
            assert "打造成功" in msg, msg
            player = await repo.load_player(QID)
            crafted.append(tuple(player.inventory)[-1])
        assert crafted[0].item_id == "maifeng_blade_a_mid"
        assert crafted[0].uid and crafted[1].uid
        assert crafted[0].uid != crafted[1].uid
        # 固定项照抄（确定性）
        assert crafted[0].stats_bonus["atk"] == 12.0
        assert crafted[0].stats_bonus["damage_dealt_pct"] == 10.0
        assert crafted[0].stats_bonus["crit_damage_pct"] == 10.0
        assert crafted[0].required_level == 5
        assert crafted[0].affinities  # 相性结算值冻进实例
        assert crafted[0].set_affixes  # 固定套装词条照抄

        # 分解（uid 路径）→ 精粹 + 材料
        p_before = await repo.load_player(QID)
        ess_before = int(p_before.currencies.get("essence", 0))
        dec = await send_command(deps, f"/分解 {crafted[0].uid}", user_id=QID)
        assert "分解" in dec, dec
        p_after = await repo.load_player(QID)
        assert int(p_after.currencies.get("essence", 0)) > ess_before
        held = {r.item_id: r.count for r in tuple(p_after.inventory)}
        assert held.get("vein_shard", 0) >= 1  # 材料回收（0.65 档回收率）

        # 淬炼（批57 引擎；配置 = 示例包 enhance.temper）
        tcfg = normalize_temper_config(
            parse_enhance_settings(deps.registry.modules_raw.get("enhance"))["temper"])
        assert tcfg["enabled"] is True
        target = crafted[1]
        cap = total_cap_of(target.required_level, tcfg)
        assert cap == target.required_level * 6
        plan = plan_temper(target.stats_bonus, target.temper_alloc, "atk", 1,
                           level=target.required_level, cfg=tcfg, essence_balance=10 ** 9)
        assert plan["ok"], plan
        materialized = materialize_temper(target.stats_bonus, target.temper_alloc,
                                          plan["new_alloc"], tcfg)
        assert materialized["atk"] == target.stats_bonus["atk"] + 1
        over = plan_temper(target.stats_bonus, {}, "atk", cap,
                           level=target.required_level, cfg=tcfg, essence_balance=10 ** 9)
        assert over["ok"] is False and over["reason"] == "per_stat_cap"
        poor = plan_temper(target.stats_bonus, {}, "atk", 1,
                           level=target.required_level, cfg=tcfg, essence_balance=0)
        assert poor["ok"] is False and poor["reason"] == "not_enough_essence"
