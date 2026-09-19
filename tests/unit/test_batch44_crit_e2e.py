"""批44 · 投入概率暴击端到端（临时内容根）：彩档图纸暴击可达品质 10，不暴击达不到。

依据：`docs/深度打造_决策记录.md` §七（「投入概率暴击」解彩档 q10 可达性；建议值
铜 15% / 银 10% / 金 7% / 彩 5%，倍率 ×2）；`打造_材料表与图纸表_草案v2.md` §3/§4.4。

口径（与草案 §4.4 手算对齐）：
  · 彩图纸 band 27–35、主槽 ore；4 种红色材料（品阶基数 ×10 相对表 = 110），
    件数 2/2/1/1 × 同相性 ×1.5 × 件数边际 1.75/1.75/1/1 × 种类奖励 1.03³
    → **常规上限 QE ≈ 991.65 < 1080（品质 9，达不到 10）**；
  · 暴击 ×2 → 1983.3，`exp_cap=last_threshold` 封顶 1080 → **品质 10**。

纪律：内容包写在 pytest tmp_path（不写仓库真实 content/）；随机源 = 玩家级随机流
（批40，本测试注入确定性 RNG：0.0 强制暴击 / 0.999 强制不暴击）；文案走模板表。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.commands.deep_craft_commands import DEEP_CRAFT_CMD, cmd_deep_craft
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.loader import build_pack
from qbot_rpg.content.validator import check_pack
from qbot_rpg.core.templates import DEFAULT_TEMPLATES

TIER_MAP = {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99]}

BP_NAME = "图纸·彩冠"
OUT_NAME = "试炼冠"

# 草案 §3.2 形状：逐档概率（彩 5%）+ 倍率 ×2 + exp_cap=last_threshold。
CRIT_PARAMS: Dict[str, Any] = {
    "enabled": True,
    "grades": ["彩"],
    "chance_by_grade": {"彩": 0.05},
    "chance_default": 0.05,
    "mult_by_grade": {"彩": 2.0},
    "mult_default": 1.0,
    "additive_exp": 0.0,
    "applies_to": "quality_exp",
    "affects_quality_level": True,
    "rolls_per_craft": 1,
    "exp_cap": "last_threshold",
}


class _FakeRng:
    """确定性单值随机源：0.0 → 强制暴击；0.999 → 强制不暴击。"""

    def __init__(self, value: float) -> None:
        self.value = value
        self.calls = 0

    def random(self) -> float:
        self.calls += 1
        return self.value


def _write_pack(tmp: Path) -> Path:
    """临时内容根：一个包，声明 settings / items / recipe（含 quality_exp_crit）。"""
    pack = tmp / "critpack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps({
        "name": "批44 临时暴击包", "version": "1.0.0", "schema_version": 1,
        "author": "batch44-test", "modules": ["settings", "items", "recipe"],
    }, ensure_ascii=False), encoding="utf-8")

    settings = {
        "alchemy": {"mode": "simple", "job_tier_map": TIER_MAP},
        "slot_defs": {"weapon": {"name": "武器", "max": 1}},
        "affinities": [{"id": "frost", "name": "霜"}],
        "deep_craft": {
            "enabled": True,
            "craft_rules": {
                "material_level_weight": {"main": 0.6, "free": 0.4},
                "quality_exp_crit": dict(CRIT_PARAMS),
            },
            # 品阶基数 = 相对表 ×10（草案 §0.1 A2；阈值仍取框架默认，末项 1080）
            "quality_exp_by_color": {"白": 10, "绿": 16, "蓝": 26,
                                     "紫": 42, "橙": 70, "红": 110},
            "quality_colors": [{"id": "白"}, {"id": "绿"}, {"id": "蓝"},
                               {"id": "紫"}, {"id": "橙"}, {"id": "红"}],
            "blueprint_grades": [{"id": "彩", "name": "彩图", "level_offset": 3,
                                  "cost_cap": 8600}],
        },
    }
    frosted = {str(k): 1.0 for k in ("frost",)}
    items = [
        {"id": "bp_crown", "name": BP_NAME, "type": "图纸",
         "blueprint_output": "crit_crown", "blueprint_slot": "weapon",
         "blueprint_grade": "彩", "blueprint_recipe": "r_crit",
         "blueprint_level_band": {"min": 27, "max": 35},
         "blueprint_material_slots": [
             {"role": "main", "item": "ore_main", "count": 1},
             {"role": "free", "tag": "ore", "count": 1}],
         "affinities": dict(frosted)},
        {"id": "ore_main", "name": "主矿", "material_level": 30,
         "material_quality": "红", "craft_cost": 100, "material_tags": ["ore"],
         "affinities": dict(frosted)},
        {"id": "ore_free", "name": "副矿", "material_level": 30,
         "material_quality": "红", "craft_cost": 100, "material_tags": ["ore"],
         "affinities": dict(frosted)},
        {"id": "crys_free", "name": "晶料", "material_level": 30,
         "material_quality": "红", "craft_cost": 100, "material_tags": ["gem"],
         "affinities": dict(frosted)},
        {"id": "bone_free", "name": "骨料", "material_level": 30,
         "material_quality": "红", "craft_cost": 100, "material_tags": ["bone"],
         "affinities": dict(frosted)},
        {"id": "crit_crown", "name": OUT_NAME, "slot": "weapon"},
    ]
    equipment: List[Dict[str, Any]] = []
    recipe = [{"id": "r_crit", "name": "冠基合成", "kind": "craft", "level": 1,
               "synth_allowed": True, "master_only": False,
               "materials": [{"id": "ore_main", "count": 1}],
               "output": {"item": "crit_crown", "count": 1},
               "cost": {"coins": 0, "gem": 0}}]
    for name, data in (("settings", settings), ("items", items),
                       ("equipment", equipment), ("recipe", recipe)):
        (pack / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return pack


def _ctx_from_pack(pack: Any, rng: Any) -> Dict[str, Any]:
    """临时包 modules → 指令 ctx（含背包/模板/注入的玩家级 rng）。"""
    mods = pack.modules
    items: Dict[str, Any] = {}
    for entry in mods.get("items") or []:
        if isinstance(entry, dict) and entry.get("id"):
            items[str(entry["id"])] = entry
    for entry in mods.get("equipment") or []:
        if isinstance(entry, dict) and entry.get("id"):
            items.setdefault(str(entry["id"]), entry)
    recipes: Dict[str, Any] = {}
    for entry in mods.get("recipe") or []:
        if isinstance(entry, dict) and entry.get("id"):
            recipes[str(entry["id"])] = entry

    inv: Dict[str, int] = {"bp_crown": 1, "ore_main": 30, "ore_free": 30,
                           "crys_free": 30, "bone_free": 30}
    instances: List[Any] = []

    def _count(iid: str) -> int:
        return int(inv.get(iid, 0))

    def _remove(iid: str, n: int) -> bool:
        if int(inv.get(iid, 0)) < int(n):
            return False
        inv[iid] = int(inv.get(iid, 0)) - int(n)
        return True

    return {
        "settings": mods.get("settings") or {},
        "items": items,
        "recipe": recipes,
        "inventory": inv,
        "inventory_instances": instances,
        "currencies": {"coins": 0, "gem": 0},
        "proficiency": {"crafter": {"level": 0, "exp": 0, "sp_earned": 0,
                                    "sp_used": 0, "unlocks": {}}},
        "count_item": _count,
        "remove_item": _remove,
        "learned_blueprints": {},
        "rng": rng,
        "templates": dict(DEFAULT_TEMPLATES),
    }


def _parsed(*args: str) -> ParsedCommand:
    return ParsedCommand(f"/{DEEP_CRAFT_CMD} " + " ".join(args),
                         command=DEEP_CRAFT_CMD, args=list(args))


def _craft(tmp_path: Path, value: float) -> Dict[str, Any]:
    """学图纸 → 投料打造（4 种红料 2/2/1/1）→ 返回 {msg, inst, snap, ctx}。"""
    pack, _changed = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack, _FakeRng(value))
    assert "已学会" in cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    msg = cmd_deep_craft(_parsed(BP_NAME, "主矿*2", "副矿*2", "晶料*1", "骨料*1"), ctx)
    return {"msg": msg, "inst": ctx["inventory_instances"][-1],
            "snap": ctx["deep_craft_last"], "ctx": ctx}


# ---------------------------------------------------------------------------
# 端到端：两条路径
# ---------------------------------------------------------------------------
def test_temp_pack_declares_valid_crit_params(tmp_path: Path) -> None:
    """临时包声明的 quality_exp_crit 通过校验器（0 相关 error）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    rep = check_pack(pack.modules, default_field_meta_table())
    assert not [e for e in rep.errors if "quality_exp_crit" in e.field], \
        [(e.field, e.kind, e.detail) for e in rep.errors if "quality_exp_crit" in e.field]


def test_crit_reaches_quality_10_and_miss_does_not(tmp_path: Path) -> None:
    """彩档：暴击 → 品质 10；不暴击 → 品质 9（常规上限 ≈991.65 < 1080）。"""
    hit = _craft(tmp_path / "hit", 0.0)
    miss = _craft(tmp_path / "miss", 0.999)

    # ---- 暴击路径 ----
    assert "打造成功" in hit["msg"]
    assert "品质经验暴击" in hit["msg"], hit["msg"]
    assert "×2" in hit["msg"], hit["msg"]
    assert hit["snap"]["crit"] is True
    assert hit["snap"]["crit_mult"] == 2.0
    assert hit["snap"]["quality_exp_base"] == pytest.approx(991.65, rel=1e-6)
    assert hit["snap"]["quality_exp"] == 1080.0                 # ×2 后封顶到阈值末项
    assert hit["snap"]["quality_level"] == 10
    assert hit["inst"]["quality_level"] == 10
    assert hit["inst"]["item_id"] == "crit_crown"

    # ---- 不暴击路径 ----
    assert "打造成功" in miss["msg"]
    assert "品质经验暴击" not in miss["msg"], miss["msg"]
    assert miss["snap"]["crit"] is False
    assert miss["snap"]["quality_exp"] == pytest.approx(991.65, rel=1e-6)
    assert miss["snap"]["quality_level"] == 9
    assert miss["inst"]["quality_level"] == 9                   # 达不到品质 10
    assert miss["snap"]["quality_level"] < 10


def test_crit_message_goes_through_template_table(tmp_path: Path) -> None:
    """暴击提示**走模板表**（注入覆盖 `deep_craft_crit_gain` → 输出随之变化）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack, _FakeRng(0.0))
    ctx["templates"] = {**ctx["templates"],
                        "deep_craft_crit_gain": "CRIT[{crit}]"}
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    msg = cmd_deep_craft(_parsed(BP_NAME, "主矿*2", "副矿*2", "晶料*1", "骨料*1"), ctx)
    assert "CRIT[2]" in msg and "品质经验暴击" not in msg


def test_no_crit_branch_output_has_no_extra_line(tmp_path: Path) -> None:
    """不暴击：成功文案**不追加**暴击行（既有输出形态零变化）。"""
    miss = _craft(tmp_path, 0.999)
    assert miss["msg"].count("\n") == 4                 # deep_craft_ok 原样 5 行
    assert not miss["msg"].endswith("暴击！本次 ×2")
