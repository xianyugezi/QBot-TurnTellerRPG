"""M9 锻造·批2·路2A：素材两档+来源+3:1 combine 单元测试（tests/unit/test_forge_material.py）。

文件名：test_forge_material.py
创建时间：2026-08-30
作者：Hermes 子agent-2A（M9 锻造实现组批2·路2A：并发同仓，仅新建本文件 +
  qbot_rpg/core/forge_material.py；不改动批0/批1 既有文件与 fixtures）

依据：docs/m9_shared_contract.md §八（items/settings 扩展：material_tier + source）+
  docs/细化/细化_2c2c_锻造素材经济.md（§2.1 TIER-01~03 两档定义判定 / §2.2 CMB-01~04
  3:1 合成扩展 / §一 SOUR-00 来源总则）+ 细化_2c2d §3.2 SP-F2（unlock_combine_3to1）+
  定稿 §5.1（两档/3:1 合成/来源提示）。
测试目标：qbot_rpg.core.forge_material.{material_tier_of, material_source,
  combine_3to1_available, combine_instances, comb_synth_map}。

覆盖矩阵：
  A 档位双源仲裁：items normal + 行 rare 覆写 → rare（TC-09 反例）；items rare + 行缺省 →
    rare（TC-08）；行+items 均缺省 → normal；非法行 tier → 回落 items 元数据
  B 来源归一三态：source_override > items.source > 兜底「来源未知」（SOUR-00 / M-04）
  C 3:1 可用性：synth_ratio_3to1=true+SP 解锁 → ok（TC-10）；开关 false → 拒（TC-11）；
    开关 true+SP 未解锁 → 拒（TC-12）；settings 三态容错（全量 dict / forge 段 /
    ForgeSettings 实例 / None）
  D combine 实例发现：真实 recipe.json 扫到 rcp_combine_3to1（3 moon_grass → 1 ghost_moss）；
    非 combine 跳过；畸形条目跳过；recipe 缺失 → []
  E comb_synth_map：普通素材 id → 稀有素材 id 登记（moon_grass → ghost_moss）；多实例合并

铁律：零 NoneBot import；纯函数确定性；零定时器探针合规（M43：docstring 不写睡眠/定时器
      字样）；不引入随机。

"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Mapping

from qbot_rpg.content.forge_models import ForgeSettings
from qbot_rpg.core.forge_material import (
    DEFAULT_MATERIAL_TIER,
    UNLOCK_COMBINE_3TO1,
    comb_synth_map,
    combine_3to1_available,
    combine_instances,
    material_source,
    material_tier_of,
)

# 仓库根 = tests/unit/test_forge_material.py 上溯两级
_REPO_ROOT = Path(__file__).resolve().parents[2]
_RECIPE_JSON = _REPO_ROOT / "content" / "test_demo" / "recipe.json"
_ITEMS_JSON = _REPO_ROOT / "content" / "test_demo" / "items.json"
_FORGE_JSON = _REPO_ROOT / "content" / "test_demo" / "forge.json"
_SETTINGS_JSON = _REPO_ROOT / "content" / "test_demo" / "settings.json"


def _load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def _items_map() -> Dict[str, Mapping[str, Any]]:
    """items.json → {id: 条目}（材料类 material_tier/source 消费靶）。"""
    raw = _load_json(_ITEMS_JSON)
    items = raw if isinstance(raw, (list, tuple)) else []
    return {e["id"]: e for e in items if isinstance(e, Mapping) and isinstance(e.get("id"), str)}


def _recipe_modules(recipes: object = None) -> Mapping[str, object]:
    """标准 modules dict（含 recipe 键；缺省真实 recipe.json）。"""
    if recipes is None:
        recipes = _load_json(_RECIPE_JSON)
    return {"recipe": recipes}


def _player(*, unlocked: bool = False) -> Dict[str, Any]:
    """铸造职业玩家表示（SP 解锁开关可配）。"""
    unlocks: Dict[str, int] = {UNLOCK_COMBINE_3TO1: 1} if unlocked else {}
    return {
        "proficiency": {
            "forge": {"level": 10, "exp": 0, "sp_earned": 3, "sp_used": 1, "unlocks": unlocks}
        }
    }


# ---------------------------------------------------------------------------
# A 档位双源仲裁（TIER-03a / M-03；TC-08/09）
# ---------------------------------------------------------------------------
def test_tier_row_override_wins_over_items_normal() -> None:
    """TC-09 反例：items 元数据 normal + 素材行显式 tier=rare → 行覆写优先 → rare。"""
    items_def = {"id": "ore", "material_tier": "normal"}
    material_row = {"item": "ore", "count": 3, "tier": "rare"}
    assert material_tier_of(items_def, material_row) == "rare"


def test_tier_items_rare_with_no_row_override() -> None:
    """TC-08 正例：items 元数据 rare + 素材行缺省 tier → 派生 rare。"""
    items_def = {"id": "fire_dragon_scale", "material_tier": "rare"}
    material_row = {"item": "fire_dragon_scale", "count": 3}
    assert material_tier_of(items_def, material_row) == "rare"


def test_tier_both_default_normal() -> None:
    """双源均缺省（行无 tier + items 无 material_tier）→ 缺省 normal（TIER-03a）。"""
    assert material_tier_of({"id": "ore"}, {"item": "ore", "count": 1}) == "normal"
    assert material_tier_of(None, None) == DEFAULT_MATERIAL_TIER == "normal"


def test_tier_invalid_row_falls_back_to_items() -> None:
    """行 tier 非法（如 'epic' 非两档枚举）→ 回落 items 元数据（V11 应拦的非法值兜底）。"""
    items_def = {"id": "ore", "material_tier": "normal"}
    material_row = {"item": "ore", "tier": "epic"}
    assert material_tier_of(items_def, material_row) == "normal"


def test_tier_real_items_entries() -> None:
    """真实 items.json：火龙鳞（rare）/ 矿石（normal）/ 幽灵苔（normal）两档落位。"""
    items = _items_map()
    assert material_tier_of(items["fire_dragon_scale"], {"item": "fire_dragon_scale"}) == "rare"
    assert material_tier_of(items["ore"], {"item": "ore"}) == "normal"
    assert material_tier_of(items["ghost_moss"], {"item": "ghost_moss"}) == "normal"


# ---------------------------------------------------------------------------
# B 来源归一三态（SOUR-00 / M-04）
# ---------------------------------------------------------------------------
def test_source_override_wins() -> None:
    """行 source_override（M-04）> items.source。"""
    items_def = {"id": "fire_dragon_scale", "source": "火龙掉落/商店"}
    material_row = {"item": "fire_dragon_scale", "source_override": "仅 BOSS 掉落"}
    assert material_source(items_def, material_row) == "仅 BOSS 掉落"


def test_source_items_fallback() -> None:
    """行无 source_override → 取 items.source。"""
    items_def = {"id": "ore", "source": "挖掘点/商店"}
    material_row = {"item": "ore"}
    assert material_source(items_def, material_row) == "挖掘点/商店"


def test_source_unknown_fallback() -> None:
    """行无覆写 + items 无来源 → 兜底「来源未知」（SOUR-00 / F-3）。"""
    assert material_source({"id": "x"}, {"item": "x"}) == "来源未知"
    assert material_source(None, None) == "来源未知"


# ---------------------------------------------------------------------------
# C 3:1 可用性（CMB-01~04 / SP-F2；TC-10/11/12）
# ---------------------------------------------------------------------------
def test_combine_available_switch_on_and_sp_unlocked() -> None:
    """TC-10 正例：synth_ratio_3to1=true + SP-F2 已解锁 → ok。"""
    settings = _load_json(_SETTINGS_JSON)  # 全量 settings（forge 段含 synth_ratio_3to1:true）
    assert isinstance(settings, Mapping)
    out = combine_3to1_available(_player(unlocked=True), settings)
    assert out == {"ok": True}


def test_combine_disabled_by_switch() -> None:
    """TC-11 反例：synth_ratio_3to1=false → 拒 synth_disabled（即便 SP 已解锁）。"""
    out = combine_3to1_available(
        _player(unlocked=True), {"forge": {"synth_ratio_3to1": False}}
    )
    assert out["ok"] is False and out["reason"] == "synth_disabled"


def test_combine_locked_by_sp() -> None:
    """TC-12 反例：开关 true + SP 未解锁（等级达标也不自动给）→ 拒 sp_locked。"""
    settings = _load_json(_SETTINGS_JSON)
    assert isinstance(settings, Mapping)
    out = combine_3to1_available(_player(unlocked=False), settings)
    assert out["ok"] is False and out["reason"] == "sp_locked"


def test_combine_settings_segment_direct() -> None:
    """settings 传 forge 段本身（含 FORGE_SETTINGS_KEYS）→ 归一正确（F-3）。"""
    out = combine_3to1_available(
        _player(unlocked=True), {"synth_ratio_3to1": True, "straight_forge": True}
    )
    assert out == {"ok": True}


def test_combine_settings_forgesettings_instance() -> None:
    """settings 传 ForgeSettings dataclass 实例 → 读其 synth_ratio_3to1。"""
    fs = ForgeSettings.from_entry({"synth_ratio_3to1": False})
    out = combine_3to1_available(_player(unlocked=True), fs)
    assert out["ok"] is False and out["reason"] == "synth_disabled"


def test_combine_settings_none_defaults_true() -> None:
    """settings=None → 开关缺省 true；SP 未解锁仍拒（CMB-04 独立判定）。"""
    out = combine_3to1_available(_player(unlocked=False), None)
    assert out["ok"] is False and out["reason"] == "sp_locked"
    assert combine_3to1_available(_player(unlocked=True), None) == {"ok": True}


def test_combine_ctx_non_mapping_locked() -> None:
    """ctx 非 Mapping / 无 proficiency → 未解锁（确定性兜底，不抛异常）。"""
    out = combine_3to1_available(None, {"forge": {"synth_ratio_3to1": True}})
    assert out["ok"] is False and out["reason"] == "sp_locked"


# ---------------------------------------------------------------------------
# D combine 实例发现（CMB-02 / m9_接口摸底 缺口1）
# ---------------------------------------------------------------------------
def test_combine_instances_real_recipe_json() -> None:
    """真实 recipe.json：扫到 rcp_combine_3to1（kind=combine，3 moon_grass → 1 ghost_moss）。"""
    insts = combine_instances(_recipe_modules())
    ids = [i["recipe_id"] for i in insts]
    assert "rcp_combine_3to1" in ids
    inst = next(i for i in insts if i["recipe_id"] == "rcp_combine_3to1")
    assert inst["kind"] == "combine"
    assert inst["inputs"] == [{"item": "moon_grass", "count": 3}]
    assert inst["output"] == {"item": "ghost_moss", "count": 1}


def test_combine_instances_skips_non_combine() -> None:
    """kind != combine（craft/upgrade）→ 不进入实例列表。"""
    recipes = [
        {"id": "r1", "kind": "craft", "materials": [{"id": "a", "count": 2}],
         "output": {"item": "b"}},
        {"id": "r2", "kind": "combine", "materials": [{"id": "x", "count": 3}],
         "output": {"item": "y"}},
        {"id": "r3", "kind": "upgrade", "materials": [{"id": "x", "count": 3}],
         "output": {"item": "y"}},
    ]
    insts = combine_instances(_recipe_modules(recipes))
    assert [i["recipe_id"] for i in insts] == ["r2"]


def test_combine_instances_skips_malformed() -> None:
    """畸形条目（无 id / 无 inputs / 无 output）跳过，不抛异常。"""
    recipes = [
        {"kind": "combine"},  # 无 id
        {"id": "m1", "kind": "combine", "materials": [], "output": {"item": "y"}},  # 无输入
        {"id": "m2", "kind": "combine", "materials": [{"id": "x", "count": 3}]},  # 无输出
        {"id": "m3", "kind": "combine", "materials": [{"id": "x", "count": 3}],
         "output": {"item": "y"}},  # 合法
        "not-a-mapping",  # 畸形条目
    ]
    insts = combine_instances(_recipe_modules(recipes))
    assert [i["recipe_id"] for i in insts] == ["m3"]


def test_combine_instances_mapping_form() -> None:
    """recipe 为 id→条目 Mapping 形态（注册表形态）→ 兼容。"""
    recipes = {
        "c1": {"id": "c1", "kind": "combine", "materials": [{"id": "p", "count": 3}],
               "output": {"item": "q"}}
    }
    insts = combine_instances(_recipe_modules(recipes))
    assert [i["recipe_id"] for i in insts] == ["c1"]


def test_combine_instances_missing_module() -> None:
    """modules 缺失 / 无 recipe 键 / recipe 非数组 → []。"""
    assert combine_instances(None) == []
    assert combine_instances({}) == []
    assert combine_instances({"recipe": "not-a-list"}) == []


# ---------------------------------------------------------------------------
# E comb_synth_map（CMB-02 登记表，供路2C 死锁扫描消费）
# ---------------------------------------------------------------------------
def test_comb_synth_map_real_recipe_json() -> None:
    """真实 recipe.json：moon_grass（普通素材 id）→ ghost_moss（输出稀有 id）登记。"""
    mapping = comb_synth_map(_recipe_modules())
    assert mapping.get("moon_grass") == "ghost_moss"


def test_comb_synth_map_multi_input_all_registered() -> None:
    """N 素材 → 1 高级素材：每个输入素材 id 均登记到同一输出 id（CMB-02）。"""
    recipes = [
        {"id": "c1", "kind": "combine",
         "materials": [{"id": "ore", "count": 3}], "output": {"item": "star_iron"}},
        {"id": "c2", "kind": "combine",
         "materials": [{"id": "herb", "count": 2}, {"id": "root", "count": 1}],
         "output": {"item": "elixir"}},
    ]
    mapping = comb_synth_map(_recipe_modules(recipes))
    assert mapping == {"ore": "star_iron", "herb": "elixir", "root": "elixir"}


def test_comb_synth_map_later_overrides_same_input() -> None:
    """同输入 id 多个实例 → 文件序后者覆盖前者（确定性）。"""
    recipes = [
        {"id": "c1", "kind": "combine",
         "materials": [{"id": "ore", "count": 3}], "output": {"item": "a"}},
        {"id": "c2", "kind": "combine",
         "materials": [{"id": "ore", "count": 3}], "output": {"item": "b"}},
    ]
    assert comb_synth_map(_recipe_modules(recipes)) == {"ore": "b"}


def test_comb_synth_map_empty_without_combine() -> None:
    """无 combine 实例 → {}（确定性）。"""
    recipes = [{"id": "r1", "kind": "craft", "materials": [{"id": "a", "count": 1}],
                "output": {"item": "b"}}]
    assert comb_synth_map(_recipe_modules(recipes)) == {}
    assert comb_synth_map(None) == {}
