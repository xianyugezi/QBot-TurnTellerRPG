"""批42 · C 节端到端（临时内容根）：`/精造` 产出**固定+随机属性 + 套装词条 + 相性 + 被动**。

依据：`docs/深度打造_决策记录.md` §三 补充 2、§六；`打造系统_原案_20260919.md`
§3/§4/§8/§11/§12；`/root/deliverables/装备被动_实现口径.md` §二/§三。

覆盖：
  · 临时内容包（settings 相性四段 + items 图纸/材料 + traits 被动 + recipe）→ 学会图纸 →
    `/精造` 投料 → 产物实例：固定属性照抄 / 随机属性走**联动覆盖池** / 固定+随机套装词条 /
    相性（主/副）冻进实例 / 被动相性变体求值；贴产物 JSON 摘要 + 背包前后；
  · **无相性 → 抽不出**（同一相性池，负向断言）；
  · **同 id 两件实例随机内容互不污染**（uid 锚定；多次打造随机结果不同）；
  · 确定性：同种子 → 同随机内容；
  · `ItemInstance` 构造点透传：`storage.repository._item_from_dict` 往返保留新字段。

纪律：内容包只写 `pytest tmp_path`（不写仓库真实 content/）；随机源 = 注入确定性 Random。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.commands.deep_craft_commands import DEEP_CRAFT_CMD, cmd_deep_craft
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.templates import DEFAULT_TEMPLATES
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.storage.repository import _item_from_dict

TIER_MAP = {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99]}

A_MAIN = "测试火"
A_SUB = "测试冰"
P_MAIN = "池火"
P_SUB = "池冰"
P_LINK = "池联动"
BP_NAME = "图纸·相性试剑"
BP_PLAIN_NAME = "图纸·无相性试剑"
MAIN_NAME = "火矿"
FREE_NAME = "冰矿"
PLAIN_NAME = "素矿"
OUT_NAME = "相性试炼剑"


def _write_pack(tmp: Path) -> Path:
    """临时内容根：一个包（settings / items / recipe / traits）。"""
    pack = tmp / "affixpack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps({
        "name": "批42 临时相性打造包", "version": "1.0.0", "schema_version": 1,
        "author": "batch42-test",
        "modules": ["settings", "items", "recipe", "traits"],
    }, ensure_ascii=False), encoding="utf-8")

    def stat(name: str, value: float) -> Dict[str, Any]:
        return {"stat": name, "value": value, "weight": 1, "requires_affinity": A_MAIN}

    settings = {
        "alchemy": {"mode": "simple", "job_tier_map": TIER_MAP},
        "slot_defs": {"weapon": {"name": "武器", "max": 1}},
        "deep_craft": {
            "enabled": True,
            "craft_rules": {"quality_level_thresholds": [0] * 10,
                            "material_level_weight": {"main": 0.6, "free": 0.4}},
            "quality_colors": [{"id": "白"}, {"id": "绿"}, {"id": "蓝"},
                               {"id": "紫"}, {"id": "橙"}, {"id": "红"}],
            "blueprint_grades": [{"id": "彩", "name": "彩图", "level_offset": 3,
                                  "cost_cap": 86000}],
        },
        "affinities": [{"id": A_MAIN, "name": "火", "exclusive_pool": P_MAIN},
                       {"id": A_SUB, "name": "冰", "exclusive_pool": P_SUB}],
        "affinity_pools": [
            {"id": P_MAIN, "kind": "exclusive", "entries": [
                stat("专火攻", 70),
                {"set_affix": "套·烈焰", "weight": 1, "requires_affinity": A_MAIN}]},
            {"id": P_SUB, "kind": "exclusive", "entries": [
                {"stat": "专冰攻", "value": 80, "weight": 1,
                 "requires_affinity": A_SUB}]},
            # 联动池：可被抽中本身即「main+sub 命中联动」的证据（原案 §8 特殊池覆盖专属池）
            {"id": P_LINK, "kind": "linkage", "entries": [
                {"stat": "联动甲", "value": 91, "weight": 1},
                {"stat": "联动乙", "value": 92, "weight": 1},
                {"stat": "联动丙", "value": 93, "weight": 1},
                {"set_affix": "套·联动甲", "weight": 1},
                {"set_affix": "套·联动乙", "weight": 1},
                {"set_affix": "套·联动丙", "weight": 1}]},
        ],
        "affinity_linkage": [{"main": A_MAIN, "sub": A_SUB, "override_pool": P_LINK}],
    }
    items = [
        {"id": "bp_sword", "name": BP_NAME, "type": "图纸",
         "blueprint_output": "crafted_sword", "blueprint_slot": "weapon",
         "blueprint_grade": "彩", "blueprint_recipe": "r_craft",
         "blueprint_level_band": {"min": 27, "max": 35},
         "blueprint_material_slots": [
             {"role": "main", "item": "ore_main", "count": 1},
             {"role": "free", "tag": "ore", "count": 1}],
         "blueprint_fixed_stats": [{"stat": "基础攻", "value": 20}],
         "blueprint_random_stat_count": {"min": 2, "max": 2},
         "blueprint_fixed_set_affix": "套·核心",
         "blueprint_random_set_affix_count": {"min": 1, "max": 2},
         "blueprint_passive": "被动·基底",
         "affinities": {A_MAIN: 10.0}},
        {"id": "bp_fire_only", "name": "图纸·单火试剑", "type": "图纸",
         "blueprint_output": "crafted_sword", "blueprint_slot": "weapon",
         "blueprint_grade": "彩", "blueprint_recipe": "r_craft",
         "blueprint_level_band": {"min": 27, "max": 35},
         "blueprint_material_slots": [{"role": "main", "item": "ore_main", "count": 1}],
         "blueprint_fixed_stats": [{"stat": "基础攻", "value": 20}],
         "blueprint_random_stat_count": {"min": 1, "max": 1},
         "blueprint_random_set_affix_count": {"min": 1, "max": 1},
         "affinities": {A_MAIN: 10.0}},
        {"id": "bp_plain", "name": BP_PLAIN_NAME, "type": "图纸",
         "blueprint_output": "crafted_sword", "blueprint_slot": "weapon",
         "blueprint_grade": "彩", "blueprint_recipe": "r_plain",
         "blueprint_level_band": {"min": 27, "max": 35},
         "blueprint_material_slots": [{"role": "main", "item": "ore_plain", "count": 1}],
         "blueprint_fixed_stats": [{"stat": "基础攻", "value": 20}],
         "blueprint_random_stat_count": {"min": 2, "max": 2},
         "blueprint_random_set_affix_count": {"min": 2, "max": 2}},
        {"id": "ore_main", "name": MAIN_NAME, "material_level": 35,
         "material_quality": "蓝", "craft_cost": 100, "material_tags": ["ore"]},
        {"id": "ore_free", "name": FREE_NAME, "material_level": 35,
         "material_quality": "蓝", "craft_cost": 100, "material_tags": ["ore"],
         "affinities": {A_SUB: 2.0}},
        {"id": "ore_plain", "name": PLAIN_NAME, "material_level": 35,
         "material_quality": "蓝", "craft_cost": 100},
        {"id": "crafted_sword", "name": OUT_NAME, "slot": "weapon"},
    ]
    recipe = [{"id": "r_craft", "name": "剑基合成", "kind": "craft", "level": 1,
               "synth_allowed": True, "master_only": False,
               "materials": [{"id": "ore_main", "count": 1}],
               "output": {"item": "crafted_sword", "count": 1},
               "cost": {"coins": 0, "gem": 0}},
              {"id": "r_plain", "name": "素剑基合成", "kind": "craft", "level": 1,
               "synth_allowed": True, "master_only": False,
               "materials": [{"id": "ore_plain", "count": 1}],
               "output": {"item": "crafted_sword", "count": 1},
               "cost": {"coins": 0, "gem": 0}}]
    traits = [
        {"id": "被动·基底", "name": "基底被动", "effects": [],
         "affinity_variants": {f"{A_MAIN}|{A_SUB}": "被动·联动",
                               A_MAIN: "被动·火"}},
        {"id": "被动·联动", "name": "联动被动", "effects": []},
        {"id": "被动·火", "name": "火被动", "effects": []},
    ]
    for name, data in (("settings", settings), ("items", items),
                       ("recipe", recipe), ("traits", traits)):
        (pack / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return pack


def _ctx_from_pack(pack: Any, seed: int = 20260919) -> Dict[str, Any]:
    """临时包 modules → 指令 ctx（背包 / 相性 / traits / 玩家级 rng）。"""
    import random as _random

    mods = pack.modules
    items: Dict[str, Any] = {}
    for entry in mods.get("items") or []:
        if isinstance(entry, dict) and entry.get("id"):
            items.setdefault(str(entry["id"]), entry)
    for entry in mods.get("equipment") or []:
        if isinstance(entry, dict) and entry.get("id"):
            items.setdefault(str(entry["id"]), entry)
    recipes: Dict[str, Any] = {}
    for entry in mods.get("recipe") or []:
        if isinstance(entry, dict) and entry.get("id"):
            recipes[str(entry["id"])] = entry
    traits: Dict[str, Any] = {}
    for entry in mods.get("traits") or []:
        if isinstance(entry, dict) and entry.get("id"):
            traits[str(entry["id"])] = entry

    inv: Dict[str, int] = {"bp_sword": 1, "bp_plain": 1, "bp_fire_only": 1,
                           "ore_main": 40, "ore_free": 40, "ore_plain": 40}
    instances: List[Any] = []

    def _count(iid: str) -> int:
        return int(inv.get(iid, 0))

    def _remove(iid: str, n: int) -> bool:
        if int(inv.get(iid, 0)) < int(n):
            return False
        inv[iid] = int(inv.get(iid, 0)) - int(n)
        return True

    ctx = {
        "settings": mods.get("settings") or {},
        "items": items,
        "recipe": recipes,
        "traits": traits,
        "inventory": inv,
        "inventory_instances": instances,
        "currencies": {"coins": 0, "gem": 0},
        "proficiency": {"crafter": {"level": 0, "exp": 0, "sp_earned": 0,
                                    "sp_used": 0, "unlocks": {}}},
        "count_item": _count,
        "remove_item": _remove,
        "learned_blueprints": {},
        "rng": _random.Random(seed),
        "templates": dict(DEFAULT_TEMPLATES),
    }
    return ctx


def _parsed(*args: str) -> ParsedCommand:
    return ParsedCommand(f"/{DEEP_CRAFT_CMD} " + " ".join(args),
                         command=DEEP_CRAFT_CMD, args=list(args))


def _learn_and_craft(tmp: Path, *materials: str, seed: int = 20260919,
                     blueprint: str = BP_NAME) -> Any:
    pack, _ = build_pack(_write_pack(tmp), None, None, 1)
    ctx = _ctx_from_pack(pack, seed)
    cmd_deep_craft(_parsed("学习", blueprint), ctx)
    msg = cmd_deep_craft(_parsed(blueprint, *materials), ctx)
    return ctx, msg


# ---------------------------------------------------------------------------
# 1) 端到端：固定+随机属性 + 套装词条 + 相性 + 被动
# ---------------------------------------------------------------------------
def test_end_to_end_affix_craft(tmp_path: Path) -> None:
    """`/精造` 产出带固定/随机属性 + 套装词条 + 相性 + 被动的装备（贴前后）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    assert ctx["inventory"]["bp_sword"] == 0

    inv_before = dict(ctx["inventory"])
    msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
    assert "打造成功" in msg

    assert ctx["inventory"]["ore_main"] == inv_before["ore_main"] - 1
    assert ctx["inventory"]["ore_free"] == inv_before["ore_free"] - 1
    inst = ctx["inventory_instances"][-1]

    snap = ctx["deep_craft_last"]
    # 相性：图纸 火 10 + 材料 冰 2 → 主火/副冰 → 联动覆盖专属池
    assert inst["affinities"] == {A_MAIN: 10.0, A_SUB: 2.0}
    # 固定属性照抄 + 随机属性（联动池三条中抽 2；provenance 见快照）
    assert inst["stats_bonus"]["基础攻"] == 20.0
    assert len(snap["random_stats"]) == 2
    assert {r["stat"] for r in snap["random_stats"]} <= {"联动甲", "联动乙", "联动丙"}
    assert all(r["pool"] == P_LINK for r in snap["random_stats"])
    # 套装词条：固定照抄 + 随机（联动池）
    assert inst["set_affixes"][0] == "套·核心"
    assert len(inst["set_affixes"]) in (2, 3)
    assert all(s.startswith("套·联动") for s in inst["set_affixes"][1:])
    # 被动相性变体：主|副 命中 → 联动被动
    assert inst["passives"] == ["被动·联动"]
    # uid 锚定
    assert len(inst["uid"]) == 32

    assert snap["affinity_main"] == A_MAIN and snap["affinity_sub"] == A_SUB
    assert snap["uid"] == inst["uid"] and snap["passives"] == ["被动·联动"]

    # 贴产物 JSON 摘要（报告证据）
    print("PRODUCT_JSON:", json.dumps({
        "stats_bonus": inst["stats_bonus"],
        "random_stats": snap["random_stats"],
        "set_affixes": inst["set_affixes"],
        "passives": inst["passives"],
        "affinities": inst["affinities"],
        "quality": inst["quality"],
    }, ensure_ascii=False))


def test_end_to_end_no_affinity_cannot_draw(tmp_path: Path) -> None:
    """**无相性 → 抽不出**：同一相性池下，无相性图纸产出 0 随机词条（负向断言）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_PLAIN_NAME), ctx)
    msg = cmd_deep_craft(_parsed(BP_PLAIN_NAME, f"{PLAIN_NAME}*1"), ctx)
    assert "打造成功" in msg
    inst = ctx["inventory_instances"][-1]
    assert inst["affinities"] == {}
    assert ctx["deep_craft_last"]["random_stats"] == []
    assert inst["set_affixes"] == []
    assert inst["passives"] == []
    assert inst["stats_bonus"] == {"基础攻": 20.0}      # 固定项仍照抄


def test_end_to_end_main_exclusive_pool_without_linkage(tmp_path: Path) -> None:
    """副相性缺失 → 联动不命中 → 随机词条来自**主相性专属池**（非联动池）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    bp_id = "bp_fire_only"
    cmd_deep_craft(_parsed("学习", "图纸·单火试剑"), ctx)
    msg = cmd_deep_craft(_parsed(bp_id, f"{MAIN_NAME}*1"), ctx)
    assert "打造成功" in msg
    inst = ctx["inventory_instances"][-1]
    snap = ctx["deep_craft_last"]
    assert inst["affinities"] == {A_MAIN: 10.0}
    assert [r["stat"] for r in snap["random_stats"]] == ["专火攻"]
    assert snap["random_stats"][0]["pool"] == P_MAIN
    assert inst["set_affixes"] == ["套·烈焰"]


# ---------------------------------------------------------------------------
# 2) 同 id 两件互不污染（uid 锚定）+ 连续两次结果不同
# ---------------------------------------------------------------------------
def test_two_instances_do_not_cross_pollute(tmp_path: Path) -> None:
    """同图纸连续打造：uid 唯一 + 随机内容随玩家级随机流变化 + 实例互不污染。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)

    results: List[Any] = []
    snaps: List[Any] = []
    for _ in range(12):
        cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
        results.append(ctx["inventory_instances"][-1])
        snaps.append(dict(ctx["deep_craft_last"]))

    uids = [r["uid"] for r in results]
    assert len(set(uids)) == len(uids)
    # 随机属性组合确实不同（联动池三条抽 2 → C(3,2)=3 种；多抽必出不同）
    combos = {tuple(sorted(r["stat"] for r in s["random_stats"])) for s in snaps}
    assert len(combos) >= 2
    # 每件实例是独立对象（互不污染）
    first, second = results[0], results[1]
    assert first["stats_bonus"] is not second["stats_bonus"]
    first["stats_bonus"]["污染测试"] = 1.0
    assert "污染测试" not in second["stats_bonus"]


def test_same_seed_same_result(tmp_path: Path) -> None:
    """注入同种子 → 两套全新 ctx 的产物随机内容一致（确定性）。"""
    c1, _ = _learn_and_craft(tmp_path, f"{MAIN_NAME}*1", f"{FREE_NAME}*1", seed=7)
    c2, _ = _learn_and_craft(tmp_path, f"{MAIN_NAME}*1", f"{FREE_NAME}*1", seed=7)
    i1, i2 = c1["inventory_instances"][-1], c2["inventory_instances"][-1]
    assert c1["deep_craft_last"]["random_stats"] == c2["deep_craft_last"]["random_stats"]
    assert i1["set_affixes"] == i2["set_affixes"]
    assert i1["passives"] == i2["passives"]
    assert i1["stats_bonus"] == i2["stats_bonus"]


# ---------------------------------------------------------------------------
# 3) 文案模板（新增占位符走模板表，非硬编码）
# ---------------------------------------------------------------------------
def test_message_template_carries_affinity_summary(tmp_path: Path) -> None:
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    ctx["templates"] = {**ctx["templates"],
                        "deep_craft_ok": "OK[{name}|{main}|{sub}|{affixes}]"}
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
    assert msg.startswith("OK[") and A_MAIN in msg and A_SUB in msg
    assert "套·核心" in msg


# ---------------------------------------------------------------------------
# 4) ItemInstance 构造点透传：JSON 往返保留新字段（repository._item_from_dict）
# ---------------------------------------------------------------------------
def test_item_from_dict_preserves_new_fields() -> None:
    """`storage.repository._item_from_dict` 逐字段读回相性 / 套装词条 / 被动（不丢）。"""
    row = {
        "item_id": "crafted_sword", "name": OUT_NAME, "count": 1, "quality": "紫",
        "bound": False, "stack_max": 1, "slot": "weapon",
        "stats_bonus": {"基础攻": 20.0, "联动甲": 91.0},
        "traits": [], "enhance_level": 0, "uid": "u" * 32,
        "affinities": {A_MAIN: 10.0, A_SUB: 2.0},
        "set_affixes": ["套·核心", "套·联动甲"],
        "passives": ["被动·联动"],
    }
    inst = _item_from_dict(row)
    assert isinstance(inst, ItemInstance)
    assert inst.affinities == {A_MAIN: 10.0, A_SUB: 2.0}
    assert inst.set_affixes == ("套·核心", "套·联动甲")
    assert inst.passives == ("被动·联动",)
    assert inst.uid == "u" * 32
    # 缺省（普通物品行）→ 空值，零影响
    plain = _item_from_dict({"item_id": "x", "name": "x", "count": 1,
                             "quality": "normal", "bound": False})
    assert plain.affinities == {} and plain.set_affixes == () and plain.passives == ()
