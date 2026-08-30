"""M9 锻造·批2·路2C：素材死锁扫描报告测试（tests/unit/test_forge_deadlock.py）。

文件名：tests/unit/test_forge_deadlock.py
创建时间：2026-08-30
作者：Hermes 子agent-2C（M9 锻造实现组批2·路2C：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_deadlock.py；不改动批0/批1 已有文件与 fixtures）

依据：docs/细化/细化_2c2c_锻造素材经济.md §四（DEAD-01~07）+ §五 D 验收 TC-18~22
  + docs/m9_shared_contract.md §六 W4 / §三 S-02 / §八 items/settings 扩展。
测试目标：qbot_rpg.core.forge_deadlock.{deadlock_report, deadlock_scan_ok,
  deadlock_hint, build_comb_synth_map, resolve_comb_synth_map}。

验收对齐（细化_2c2c §五 D）：
  - TC-18：稀有素材途径计数——途径≥2 达标（掉落+3:1）/ 仅 1 途径（仅 BOSS 掉落无
    combine）→ W 级死锁风险提示（不拦截），deadlock_scan_ok False 但报告可输出。
  - TC-19：3:1 合成映射表覆盖 → 途径数 +1；关开关（synth_ratio_3to1=false）→ 途径数
    −1 并触发同款提示。
  - TC-20：分解回收（DEAD-03）属 /分解 引擎（批外），本模块不消费 decompose_rate——
    仅断言 settings decompose_rate 键不参与途径计数（保持纯死锁扫描职责边界）。
  - TC-21：商店限购不单一依赖——商店限购条目仍计入 shop 途径，但普通素材不可仅靠
    商店单一来源（≥3 途径保底）；稀有素材 3:1 合成兜底（途径计数通过）。
  - TC-22：全素材闭环扫描（forge + loot/shop/recipe combine + 采集/种植）——每个被
    forge 引用的素材 id：有 ≥1 产出途径且 ≥1 消耗出口（被 forge 引用即消耗出口）；
    无孤儿素材、无不可达素材；报告输出途径数明细。

测试口径（对齐 test_forge_cascade.py / test_forge_tree.py）：
  - 合成小 fixtures（纯 dict 深拷贝），不依赖真实文件；另用 content/test_demo 真实
    数据跑一次端到端（deep-copy 隔离，不改写文件）。
  - 铁律：纯函数确定性——入参不被改写（断言深等）；零 NoneBot；不写定时器/睡眠调用。

【工程补白 · 注记】
  - 档位判定（F-2）：素材行 tier 覆写 rare > items material_tier rare > normal。
  - combine 来源仅 settings.synth_ratio_3to1=true 时计（S-02 / TC-19/TC-11）。
  - 孤儿（F-3）：source_count==0 → 不可达素材，gap=True 且 orphan=True（TC-22）。
"""

from __future__ import annotations

import copy
import json
import os
from typing import Dict, List, Mapping

from qbot_rpg.core.forge_deadlock import (
    THRESHOLD_NORMAL,
    THRESHOLD_RARE,
    build_comb_synth_map,
    deadlock_hint,
    deadlock_report,
    deadlock_scan_ok,
    resolve_comb_synth_map,
)

# ---------------------------------------------------------------------------
# 合成 fixtures（纯 dict 深拷贝；不改写）
# ---------------------------------------------------------------------------


def _forge(
    materials: List[Dict[str, object]],
    *,
    synth_ratio_3to1: object = True,
) -> Dict[str, object]:
    """forge raw：单树单节点，materials 行透传；settings 段可配开关。"""
    return {
        "schema_version": "1.0",
        "trees": [
            {
                "id": "tree_test",
                "name": "测试树",
                "type": "weapon",
                "roots": ["node_test"],
                "nodes": [
                    {
                        "id": "node_test",
                        "name": "测试装备",
                        "item": "test_gear",
                        "type": "weapon",
                        "level": 1,
                        "parent": None,
                        "branch": [],
                        "materials": copy.deepcopy(materials),
                        "rarity": "normal",
                        "final": True,
                    }
                ],
            }
        ],
        "settings": {
            "forge_fee": "节点等级×10",
            "synth_ratio_3to1": synth_ratio_3to1,
            "straight_forge": True,
            "decompose_rate": {"正式": 0.4},
            "exp_per_forge": "节点等级×2",
            "sets_enabled": True,
            "augments_enabled": True,
        },
    }


def _items(entries: List[Dict[str, object]]) -> List[Dict[str, object]]:
    return copy.deepcopy(entries)


def _enemies(drops: Dict[str, List[Dict[str, object]]]) -> List[Dict[str, object]]:
    return [{"id": "mon_1", "name": "测试怪", "tier": "normal", "drops": copy.deepcopy(drops)}]


def _shop(sold: List[str], *, limit: bool = False) -> List[Dict[str, object]]:
    rows: List[Dict[str, object]] = []
    for item_id in sold:
        row: Dict[str, object] = {"item": item_id, "price": 10, "stock": 5}
        if limit:
            row["limit"] = 2  # 限购（TC-07/TC-21：限购不影响商店途径存在性）
        rows.append(row)
    return [{"id": "shop_test", "name": "测试商店", "items": rows}]


def _recipe_combine(in_id: str, out_id: str) -> List[Dict[str, object]]:
    return [
        {
            "id": "rcp_combine_test",
            "name": "测试三合一",
            "kind": "combine",
            "materials": [{"id": in_id, "count": 3}],
            "output": {"item": out_id, "count": 1},
        }
    ]


def _maps_gather(item_id: str) -> List[Dict[str, object]]:
    return [{"id": "map_test", "name": "测试地图", "gather_points": [{"item": item_id}]}]


def _items_with_seed(seed_item_id: str, output_id: str) -> List[Dict[str, object]]:
    return [
        {"id": seed_item_id, "name": "种子", "type": "seed", "seed": {"output": output_id}},
        {"id": output_id, "name": output_id, "type": "material", "material_tier": "normal"},
    ]


def _material(item_id: str, tier: str = "normal") -> Dict[str, object]:
    return {"id": item_id, "name": item_id, "type": "material", "material_tier": tier}


def _report_item(report: object, item_id: str) -> Dict[str, object]:
    items = report["items"] if isinstance(report, Mapping) else []
    for it in items:
        if isinstance(it, Mapping) and it.get("item_id") == item_id:
            return dict(it)
    raise KeyError(item_id)


def _items_of(report: object) -> List[Mapping[str, object]]:
    """report['items'] → 条目列表（类型收窄，供迭代）。"""
    items = report["items"] if isinstance(report, Mapping) else []
    return [it for it in items if isinstance(it, Mapping)]


def _srcs(it: Mapping[str, object]) -> set:
    """条目 sources 字段 → set（类型收窄）。"""
    v = it.get("sources")
    return set(v) if isinstance(v, (list, tuple)) else set()


# ---------------------------------------------------------------------------
# TC-18：稀有素材途径计数（DEAD-04 分级保底下限）
# ---------------------------------------------------------------------------


def test_tc18_rare_two_paths_pass() -> None:
    """TC-18 甲：稀有素材途径=2（掉落 + 3:1）→ 达标（无 gap）。"""
    modules = {
        "forge": _forge([{"item": "rare_a", "count": 1}]),
        "items": _items([_material("rare_a", "rare")]),
        "enemies": _enemies({"battle": [{"item": "rare_a", "chance": 50}],
                             "special": [], "death": []}),
        "recipe": _recipe_combine("common_x", "rare_a"),
        "shop": _shop([]),
    }
    modules = copy.deepcopy(modules)
    snapshot = copy.deepcopy(modules)
    report = deadlock_report(modules)
    assert modules == snapshot, "deadlock_report 不得改写入参"

    it = _report_item(report, "rare_a")
    assert it["tier"] == "rare"
    assert it["threshold"] == THRESHOLD_RARE
    assert it["source_count"] == 2, f"掉落+3:1 应计 2 途径，got {it['sources']}"
    assert _srcs(it) == {"drop", "combine"}
    assert it["gap"] is False
    assert report["ok"] is True
    assert deadlock_scan_ok(report) is True
    assert deadlock_hint("rare_a", report) == "", "达标素材无缺口建议"


def test_tc18_rare_one_path_gap() -> None:
    """TC-18 乙：稀有素材途径=1（仅 BOSS 掉落且无 combine）→ W 级死锁风险（不拦截）。"""
    modules = {
        "forge": _forge([{"item": "rare_b", "count": 1}]),
        "items": _items([_material("rare_b", "rare")]),
        "enemies": _enemies({"battle": [{"item": "rare_b", "chance": 100}],
                             "special": [], "death": []}),
        "recipe": [],  # 无 combine 映射
        "shop": _shop([]),
    }
    report = deadlock_report(modules)
    it = _report_item(report, "rare_b")
    assert it["source_count"] == 1
    assert it["gap"] is True
    assert it["orphan"] is False  # 有 1 途径，非孤儿
    assert report["ok"] is False
    # W 级不拦截：scan_ok False 仅提示
    assert deadlock_scan_ok(report) is False
    hint = deadlock_hint("rare_b", report)
    assert "建议补" in hint and "3:1 合成" in hint, hint


# ---------------------------------------------------------------------------
# TC-19：3:1 合成映射 → 途径数 ±1（开关影响）
# ---------------------------------------------------------------------------


def test_tc19_combine_map_adds_path_and_switch_removes() -> None:
    """TC-19：comb_synth_map 覆盖 → 途径数 +1；关开关 → 途径数 −1 并触发提示。"""
    base = {
        "forge": _forge([{"item": "rare_c", "count": 1}]),
        "items": _items([_material("rare_c", "rare")]),
        "enemies": _enemies({"battle": [{"item": "rare_c", "chance": 60}],
                             "special": [], "death": []}),
        "recipe": _recipe_combine("common_z", "rare_c"),
        "shop": _shop([]),
    }
    # 开关开：掉落 + 3:1 = 2 途径 → 达标
    on = deadlock_report(copy.deepcopy(base))
    it_on = _report_item(on, "rare_c")
    assert it_on["source_count"] == 2
    assert "combine" in _srcs(it_on)
    assert it_on["gap"] is False
    assert deadlock_scan_ok(on) is True

    # 关开关（synth_ratio_3to1=false）：combine 途径 −1 → 仅掉落 1 途径 → 死锁提示
    off_cfg = copy.deepcopy(base)
    off_cfg["forge"] = _forge([{"item": "rare_c", "count": 1}], synth_ratio_3to1=False)
    off = deadlock_report(off_cfg)
    it_off = _report_item(off, "rare_c")
    assert it_off["source_count"] == 1
    assert "combine" not in _srcs(it_off)
    assert it_off["gap"] is True
    assert deadlock_scan_ok(off) is False
    hint = deadlock_hint("rare_c", off)
    assert "3:1 合成" in hint, hint


def test_tc19_combine_map_via_build() -> None:
    """build_comb_synth_map / resolve_comb_synth_map：kind=combine → 普通 id → 稀有 id。"""
    recipe = _recipe_combine("ore", "star_iron")
    cmap = build_comb_synth_map(recipe)
    assert cmap == {"ore": "star_iron"}
    # resolve_comb_synth_map：兄弟模块未落盘 → 本地 recipe 兜底
    resolved = resolve_comb_synth_map({"recipe": recipe})
    assert resolved == {"ore": "star_iron"}
    # 非 combine 实例不计
    assert build_comb_synth_map([{"id": "x", "kind": "craft", "output": {"item": "y"}}]) == {}


# ---------------------------------------------------------------------------
# TC-20：分解回收（DEAD-03）职责边界——本模块不消费 decompose_rate
# ---------------------------------------------------------------------------


def test_tc20_decompose_rate_not_a_source() -> None:
    """TC-20：decompose_rate 属 /分解 引擎（批外），不参与死锁途径计数。"""
    modules: Dict[str, object] = {
        "forge": _forge([{"item": "rare_d", "count": 1}]),
        "items": _items([_material("rare_d", "rare")]),
        "enemies": _enemies({"battle": [{"item": "rare_d", "chance": 100}],
                             "special": [], "death": []}),
        "recipe": [],
        "shop": _shop([]),
    }
    # settings decompose_rate 显式存在，但不应作为途径来源
    forge_v = modules["forge"]
    settings_v = forge_v.get("settings") if isinstance(forge_v, Mapping) else None
    if isinstance(settings_v, dict):
        settings_v["decompose_rate"] = {"正式": 0.4, "王": 0.65}
    report = deadlock_report(modules)
    it = _report_item(report, "rare_d")
    assert it["source_count"] == 1, "decompose_rate 不应计入途径（分解回收由 /分解 引擎消费）"


# ---------------------------------------------------------------------------
# TC-21：商店限购不单一依赖（≥3 途径保底 / 稀有 3:1 兜底）
# ---------------------------------------------------------------------------


def test_tc21_shop_limit_still_counts_but_not_sole() -> None:
    """TC-21：商店限购条目仍计入 shop 途径；但普通素材不可仅靠商店单一来源。"""
    # 普通素材：仅商店限购 1 途径 → 低于下限 3 → gap（不单一依赖商店）
    only_shop = {
        "forge": _forge([{"item": "ore", "count": 1}]),
        "items": _items([_material("ore", "normal")]),
        "enemies": _enemies({"battle": [], "special": [], "death": []}),
        "recipe": [],
        "shop": _shop(["ore"], limit=True),  # 限购 2
    }
    r1 = deadlock_report(only_shop)
    it1 = _report_item(r1, "ore")
    assert "shop" in _srcs(it1)  # 限购不抹掉商店途径
    assert it1["source_count"] == 1
    assert it1["gap"] is True  # 单一来源不足保底
    assert deadlock_scan_ok(r1) is False

    # 普通素材：商店 + 掉落 + 采集 = 3 途径 → 达标（≥3 途径保底，TC-21）
    full = {
        "forge": _forge([{"item": "ore", "count": 1}]),
        "items": _items([_material("ore", "normal")]),
        "enemies": _enemies({"battle": [{"item": "ore", "chance": 40}],
                             "special": [], "death": []}),
        "recipe": [],
        "shop": _shop(["ore"], limit=True),
        "maps": _maps_gather("ore"),
    }
    r2 = deadlock_report(full)
    it2 = _report_item(r2, "ore")
    assert it2["source_count"] == 3
    assert _srcs(it2) == {"shop", "drop", "gather"}
    assert it2["gap"] is False
    assert deadlock_scan_ok(r2) is True


def test_tc21_rare_combine_fallback() -> None:
    """TC-21：商店限购售罄 + 掉落怪时段外 → 稀有素材 3:1 合成兜底（途径计数通过）。"""
    modules = {
        "forge": _forge([{"item": "rare_e", "count": 1}]),
        "items": _items([_material("rare_e", "rare")]),
        "enemies": _enemies({"battle": [{"item": "rare_e", "chance": 10}],
                             "special": [], "death": []}),
        "recipe": _recipe_combine("common_w", "rare_e"),
        "shop": _shop([]),  # 商店不售稀有（TC-07）
    }
    report = deadlock_report(modules)
    it = _report_item(report, "rare_e")
    assert it["source_count"] == 2  # 掉落 + 3:1
    assert it["gap"] is False
    assert deadlock_scan_ok(report) is True


# ---------------------------------------------------------------------------
# TC-22：全素材闭环扫描（无孤儿 / 无不可达 / 途径数明细）
# ---------------------------------------------------------------------------


def test_tc22_closed_loop_no_orphan() -> None:
    """TC-22：每个被 forge 引用素材都有产出途径且被消耗（无孤儿、无不可达）。"""
    modules = {
        "forge": _forge([
            {"item": "ore", "count": 3},
            {"item": "rare_f", "count": 2},
        ]),
        "items": _items([
            _material("ore", "normal"),
            _material("rare_f", "rare"),
        ]),
        "enemies": _enemies({
            "battle": [{"item": "ore", "chance": 40}],
            "special": [],
            "death": [{"item": "rare_f", "chance": 100}],
        }),
        "recipe": _recipe_combine("ore", "rare_f"),
        "shop": _shop(["ore"]),
        "maps": _maps_gather("ore"),
    }
    report = deadlock_report(modules)
    entries = _items_of(report)
    ids = {it["item_id"] for it in entries}
    assert ids == {"ore", "rare_f"}
    assert all(it["orphan"] is False for it in entries), \
        "全部素材应有 ≥1 产出途径（无孤儿）"
    # 途径数明细
    ore = _report_item(report, "ore")
    assert ore["source_count"] == 3  # 掉落 + 商店 + 采集
    rare_f = _report_item(report, "rare_f")
    assert rare_f["source_count"] == 2  # 掉落 + 3:1
    assert report["ok"] is True
    assert deadlock_scan_ok(report) is True


def test_tc22_orphan_detected() -> None:
    """TC-22 负例：被 forge 引用但全表无产出途径 → 孤儿（orphan=True，gap=True）。"""
    modules = {
        "forge": _forge([{"item": "ghost_ore", "count": 1}]),
        "items": _items([_material("ghost_ore", "normal")]),
        "enemies": _enemies({"battle": [], "special": [], "death": []}),
        "recipe": [],
        "shop": _shop([]),
        "maps": [],
    }
    report = deadlock_report(modules)
    it = _report_item(report, "ghost_ore")
    assert it["source_count"] == 0
    assert it["orphan"] is True
    assert it["gap"] is True
    assert deadlock_scan_ok(report) is False


# ---------------------------------------------------------------------------
# 档位仲裁 / 名称 / 阈值边界 / 空输入确定性
# ---------------------------------------------------------------------------


def test_tier_row_override_wins() -> None:
    """M-03 双源仲裁：素材行 tier=rare 覆写 items material_tier=normal → rare。"""
    modules = {
        "forge": _forge([{"item": "rare_g", "count": 1, "tier": "rare"}]),
        "items": _items([_material("rare_g", "normal")]),
        "enemies": _enemies({"battle": [{"item": "rare_g", "chance": 100}],
                             "special": [], "death": []}),
        "recipe": _recipe_combine("common_v", "rare_g"),
        "shop": _shop([]),
    }
    report = deadlock_report(modules)
    it = _report_item(report, "rare_g")
    assert it["tier"] == "rare"
    assert it["threshold"] == THRESHOLD_RARE


def test_normal_threshold_three() -> None:
    """普通素材下限 3：3 途径达标 / 2 途径 gap。"""
    def _mk() -> Dict[str, object]:
        return {
            "forge": _forge([{"item": "ore", "count": 1}]),
            "items": _items([_material("ore", "normal")]),
            "enemies": _enemies({"battle": [{"item": "ore", "chance": 40}],
                                 "special": [], "death": []}),
            "recipe": _recipe_combine("x", "y"),
            "shop": _shop(["ore"]),
            "maps": _maps_gather("ore"),
        }

    report = deadlock_report(_mk())
    it = _report_item(report, "ore")
    assert it["source_count"] == 3
    assert it["threshold"] == THRESHOLD_NORMAL
    assert it["gap"] is False

    # 缺采集 → 2 途径 → gap
    mod2 = _mk()
    mod2["maps"] = []
    r2 = deadlock_report(mod2)
    it2 = _report_item(r2, "ore")
    assert it2["source_count"] == 2
    assert it2["gap"] is True


def test_empty_modules_and_empty_forge() -> None:
    """空模块/空 forge：确定性兜底——无素材需求 → ok=True 无 items。"""
    assert deadlock_report({}) == {"items": [], "ok": True}
    assert deadlock_scan_ok({"items": []}) is True
    assert deadlock_hint("nope", {"items": []}) == ""
    # forge 存在但无节点素材
    forge_only = {"forge": {"trees": []}, "items": []}
    report = deadlock_report(forge_only)
    assert report["items"] == []
    assert report["ok"] is True


# ---------------------------------------------------------------------------
# 真实数据端到端（content/test_demo；深拷贝隔离，不改写文件）
# ---------------------------------------------------------------------------

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_json(rel: str) -> object:
    with open(os.path.join(_REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def test_real_test_demo_scan() -> None:
    """content/test_demo 真实数据端到端：全素材扫描 + 明细 + 确定性。"""
    modules = {
        "forge": _load_json("content/test_demo/forge.json"),
        "items": _load_json("content/test_demo/items.json"),
        "shop": _load_json("content/test_demo/shop.json"),
        "recipe": _load_json("content/test_demo/recipe.json"),
        "enemies": _load_json("content/test_demo/enemies.json"),
        "maps": _load_json("content/test_demo/maps.json"),
    }
    snapshot = copy.deepcopy(modules)
    report = deadlock_report(modules)
    assert modules == snapshot, "不得改写入参"

    items = _items_of(report)
    ids = {it["item_id"] for it in items}
    # 火龙鳞（稀有，items material_tier=rare）应被扫描出且途径计数确定
    assert "fire_dragon_scale" in ids
    fds = _report_item(report, "fire_dragon_scale")
    assert fds["tier"] == "rare"
    assert fds["threshold"] == THRESHOLD_RARE
    # 矿石（普通，items material_tier=normal）应被扫描出
    ore = _report_item(report, "ore")
    assert ore["tier"] == "normal"
    assert ore["threshold"] == THRESHOLD_NORMAL
    # 报告确定性：重复调用结果一致
    report2 = deadlock_report(copy.deepcopy(modules))
    assert report == report2
    # ok 与 scan_ok 一致（从 items 重算）
    assert report["ok"] == deadlock_scan_ok(report)
