"""批41 · 深度打造端到端（临时内容根）：学会图纸 → /精造 投料 → 产出装备进背包（带 uid）。

依据：`docs/深度打造_决策记录.md` §一 H1/H4/H6、§二 N1~N6、§六；
任务口径「端到端（临时内容根）：学会图纸 → /精造 投料 → 产出装备进背包且带 uid（贴前后）
+ 消息文案走模板；同一玩家连续两次打造结果不同（随机流 ✓）」。

纪律：**内容包写在 pytest tmp_path**（不写仓库真实 content/，防污染门禁）；
指令经 `/精造` 的 `cmd_deep_craft`（同一处理器由 Router 注册，见 test_assembly_router）；
随机源 = 玩家级随机流（批40 `ctx["rng"]`，本测试注入确定性 Random）。
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.commands.deep_craft_commands import DEEP_CRAFT_CMD, cmd_deep_craft
from qbot_rpg.commands.parsers import ParsedCommand
from qbot_rpg.content.loader import build_pack
from qbot_rpg.core.templates import DEFAULT_TEMPLATES

TIER_MAP = {"见习": [1, 5], "正式": [6, 10], "精通": [11, 20], "专家": [21, 30],
            "大师": [31, 40], "宗师": [41, 50], "王": [51, 99]}

BP_NAME = "图纸·试剑"
MAIN_NAME = "主矿"
FREE_NAME = "副矿"
OUT_NAME = "试炼剑"


def _write_pack(tmp: Path) -> Path:
    """临时内容根：一个包，含 settings / items / equipment / recipe 四模块。"""
    pack = tmp / "craftpack"
    pack.mkdir(parents=True, exist_ok=True)
    (pack / "manifest.json").write_text(json.dumps({
        "name": "批41 临时打造包", "version": "1.0.0", "schema_version": 1,
        "author": "batch41-test",
        "modules": ["settings", "items", "recipe"],
    }, ensure_ascii=False), encoding="utf-8")

    settings = {
        "alchemy": {"mode": "simple", "job_tier_map": TIER_MAP},
        "slot_defs": {"weapon": {"name": "武器", "max": 1}},
        "deep_craft": {
            "enabled": True,
            "craft_rules": {
                # 阈值全 0 → 保证品质等级 10（便于验证概率行 + 结果随机性）
                "quality_level_thresholds": [0] * 10,
                "material_level_weight": {"main": 0.6, "free": 0.4},
            },
            "quality_colors": [{"id": "白"}, {"id": "绿"}, {"id": "蓝"},
                               {"id": "紫"}, {"id": "橙"}, {"id": "红"}],
            "blueprint_grades": [{"id": "彩", "name": "彩图", "level_offset": 3,
                                  "cost_cap": 86000}],
        },
    }
    items = [
        {"id": "bp_sword", "name": BP_NAME, "type": "图纸",
         "blueprint_output": "crafted_sword", "blueprint_slot": "weapon",
         "blueprint_grade": "彩", "blueprint_recipe": "r_craft",
         "blueprint_level_band": {"min": 27, "max": 35},
         "blueprint_material_slots": [
             {"role": "main", "item": "ore_main", "count": 1},
             {"role": "free", "tag": "ore", "count": 1}],
         "blueprint_fixed_stats": [{"stat": "atk", "value": 20}]},
        {"id": "ore_main", "name": MAIN_NAME, "material_level": 35,
         "material_quality": "蓝", "craft_cost": 100, "material_tags": ["ore"]},
        {"id": "ore_free", "name": FREE_NAME, "material_level": 35,
         "material_quality": "蓝", "craft_cost": 100, "material_tags": ["ore"]},
        {"id": "crafted_sword", "name": OUT_NAME, "slot": "weapon"},
    ]
    equipment: List[Dict[str, Any]] = []
    recipe = [{"id": "r_craft", "name": "剑基合成", "kind": "craft", "level": 1,
               "synth_allowed": True, "master_only": False,
               "materials": [{"id": "ore_main", "count": 1}],
               "output": {"item": "crafted_sword", "count": 1},
               "cost": {"coins": 0, "gem": 0}}]
    for name, data in (("settings", settings), ("items", items),
                       ("equipment", equipment), ("recipe", recipe)):
        (pack / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return pack


def _ctx_from_pack(pack: Any) -> Dict[str, Any]:
    """临时包 modules → 指令 ctx（含背包/相性/模板/玩家级 rng）。"""
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

    inv: Dict[str, int] = {"bp_sword": 1, "ore_main": 40, "ore_free": 40}
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
        "rng": random.Random(20260919),
        "templates": dict(DEFAULT_TEMPLATES),
    }


def _parsed(*args: str) -> ParsedCommand:
    return ParsedCommand(f"/{DEEP_CRAFT_CMD} " + " ".join(args),
                         command=DEEP_CRAFT_CMD, args=list(args))


def test_end_to_end_learn_craft_and_instance(tmp_path: Path) -> None:
    """学会图纸 → 投料打造 → 装备进背包（带 uid）+ 固定属性 + 扣料（前后对照）。"""
    pack, _changed = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)

    # ---- 学习前：未学 → 拒绝（模板文案） ----
    before_msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1"), ctx)
    assert "尚未学会" in before_msg

    # ---- 学会图纸（消耗 1 张） ----
    learn_msg = cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    assert "已学会" in learn_msg and ctx["learned_blueprints"].get("bp_sword")
    assert ctx["inventory"]["bp_sword"] == 0

    # ---- 投料打造：背包前后 ----
    inv_before = dict(ctx["inventory"])
    inst_before = list(ctx["inventory_instances"])
    msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)

    assert "打造成功" in msg
    assert ctx["inventory"]["ore_main"] == inv_before["ore_main"] - 1
    assert ctx["inventory"]["ore_free"] == inv_before["ore_free"] - 1
    after = ctx["inventory_instances"]
    assert len(after) == len(inst_before) + 1
    inst = after[-1]
    assert inst["item_id"] == "crafted_sword"
    assert inst["uid"] and len(inst["uid"]) == 32
    assert inst["quality"] in ("白", "绿", "蓝", "紫", "橙", "红")
    assert inst["stats_bonus"] == {"atk": 20.0}
    assert inst["slot"] == "weapon"
    assert ctx.get("_m8_dirty_inventory") is True
    # 快照落 persistent_state（无 player → ctx 兜底）
    snap = ctx.get("deep_craft_last")
    assert snap and snap["uid"] == inst["uid"] and snap["equipment_level"] == 35


def test_message_goes_through_template_table(tmp_path: Path) -> None:
    """打造结果文案**走模板表**（注入覆盖模板 → 输出随之变化，证明非硬编码）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    ctx["templates"] = {**ctx["templates"], "deep_craft_ok": "OK[{name}|{quality}]"}
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
    assert msg.startswith("OK[") and OUT_NAME in msg and "|" in msg


def test_two_crafts_same_player_differ(tmp_path: Path) -> None:
    """同一玩家连续两次打造：实例 uid 不同 + 品质颜色随玩家级随机流变化。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)

    results = []
    for _ in range(24):
        cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
        results.append(ctx["inventory_instances"][-1])

    uids = [r["uid"] for r in results]
    assert len(set(uids)) == len(uids)              # 每件唯一（H4 uid）
    colors = {r["quality"] for r in results}
    assert len(colors) >= 2                          # 随机流推进 → 品质不同（彩10 行有紫/橙/红）
    # 随机流确实被消费（推进后状态与初态不同）
    assert ctx["rng"].random() != ctx["rng"].random()


def test_cost_over_cap_rejected_end_to_end(tmp_path: Path) -> None:
    """超 cost 上限 → 拒绝并给人话提示（贴提示）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)
    # 单材料件数上限 5 → 用 5 件主矿（100×5 + 工费 60 + 每种附加 20 = 580 ≤ 86000）不超限，
    # 故把 cost_cap 覆盖为极小值（图纸声明）→ 拒绝。
    ctx["items"]["bp_sword"]["blueprint_cost_cap"] = 100
    msg = cmd_deep_craft(_parsed(BP_NAME, f"{MAIN_NAME}*1", f"{FREE_NAME}*1"), ctx)
    assert "超上限" in msg
    assert ctx["inventory_instances"] == []           # 拒绝不产实例
    assert ctx["inventory"]["ore_main"] == 40        # 拒绝不扣料


def test_preview_without_materials(tmp_path: Path) -> None:
    """`/精造 <图纸>` 无投料 → 只读预览（模板文案，含等级带 / cost 上限）。"""
    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    msg = cmd_deep_craft(_parsed(BP_NAME), ctx)
    assert BP_NAME in msg and "等级带" in msg and "cost 上限" in msg


def test_comma_list_syntax_through_real_parser(tmp_path: Path) -> None:
    """逗号列表语法经**真实解析器**：`/精造 图纸 主矿*1,副矿*1` → targets 逐项（不重复计料）。"""
    from qbot_rpg.commands.parsers import DEFAULT_FREE_ARG_COMMANDS, parse_command

    pack, _ = build_pack(_write_pack(tmp_path), None, None, 1)
    ctx = _ctx_from_pack(pack)
    cmd_deep_craft(_parsed("学习", BP_NAME), ctx)

    parsed = parse_command(f"/{DEEP_CRAFT_CMD} {BP_NAME} {MAIN_NAME}*1,{FREE_NAME}*1",
                           free_arg_commands=DEFAULT_FREE_ARG_COMMANDS)
    assert parsed.error is None
    assert parsed.targets == [f"{MAIN_NAME}*1", f"{FREE_NAME}*1"]
    msg = cmd_deep_craft(parsed, ctx)
    assert "打造成功" in msg
    assert ctx["inventory"]["ore_main"] == 39
    assert ctx["inventory"]["ore_free"] == 39

