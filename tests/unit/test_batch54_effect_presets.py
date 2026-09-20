"""批54 · 框架特效预设集 + 结算/奖励轴核查 验收测试。

口径：
  · `特效整理设计_2_框架预设包.md` §1（预设词条集）/ §2（成套预设）/ §4（速览）；
  · `特效整理设计_3_落点与分期.md` §1.2 F5（L-1 `reward_mult{scope}`）/ §1.5（预设体系形状）；
  · `特效整理设计_1_修正轴全集.md` §3 P1 第 16 项（X43 奖励倍率）；
  · 批50/52/53 已登记的 15 条特效轴（`data.gear_stats.EFFECT_AXIS_SPECS`）。

覆盖：
  A. 预设声明**可枚举**：形状齐备 / id 唯一 / help 忌长文 / 档位三档。
  B. 预设声明**可校验**：引用轴存在（`引用轴不存在`）、取值在轴范围内（**越界红拦**）、
     id 重复、defaults 取 normal 档。
  C. **同族两方向**：同 `conflict_group` 的两条预设共用同一条轴、方向相反、取值异号。
  D. **复用既有 entry_presets**：`items` 六种逐字段不变；`equipment` 走同一
     `merge_entry_presets`（框架默认 ∪ 包覆盖 ∪ 包关闭）。
  E. **编辑器可见**：`new_entry_detail` 列出预设（中文名 + 一句话 help）、选中后主区字段与
     默认值齐备、其余字段仍可编辑（一号原则）。
  F. **落进产物实例**：临时内容根上按预设新建 → 装备 def 带轴值 → `extract_bonus` →
     `route_bonus_into` → `combatant_updates` 桥接链路。
  G. **零变化**：不启用预设 → 逐轴 0.0（框架预设不泄漏）；`items` 六种预设不变。
  H. **结算/奖励轴核查结论**（如实报告，不硬造）：`reward_mult{scope}` 无唯一收口 → 不登记。

纪律：测试只写**临时目录**（`tmp_path`），不碰任何真实内容包；不写死内容包业务名/数值平衡。
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import effect_presets as fx
from qbot_rpg.content import entry_presets as entry_presets_mod
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.data.gear_stats import (
    GEAR_EFFECT_KEYS,
    combatant_updates,
    extract_bonus,
    route_bonus_into,
)
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
for _p in (str(REPO), str(REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

TABLE = default_field_meta_table()
MODULE = fx.EFFECT_PRESET_MODULE

# 期望的「同族两方向」族（设计 §1 明确给出两端）——(family, axis, conflict_group)
TWO_WAY_FAMILIES = (
    ("damage_taken", "damage_taken_pct", "damage_taken"),
    ("healing_received", "healing_received_pct", "healing_received"),
    ("crit_damage", "crit_damage_pct", "crit_damage"),
    ("cooldown", "cooldown_pct", "cooldown"),
    ("stack_gain", "stack_gain_pct", "stack_gain"),
    ("stack_cap", "stack_cap_delta", "stack_cap"),
    ("status_resist", "status_resist_pct", "status_resist"),
    ("status_duration_taken", "status_duration_taken_pct", "status_duration_taken"),
    ("resource_cost", "resource_cost_pct", "resource_cost"),
    ("action_bar", "action_bar_shift", "action_bar"),
)


@pytest.fixture()
def temp_pack(tmp_path: Path) -> Path:
    """临时内容根：一个只声明 `equipment` 模块的最小包（不碰真实内容包）。"""
    root = tmp_path / "content"
    pack = root / "tp"
    pack.mkdir(parents=True)
    (pack / "manifest.json").write_text(json.dumps({
        "name": "临时包", "version": "1", "schema_version": 1, "modules": [MODULE],
    }, ensure_ascii=False), encoding="utf-8")
    (pack / "equipment.json").write_text("[]", encoding="utf-8")
    return root


def _preset(pid: str) -> Dict[str, Any]:
    hit = fx.find_effect_preset(pid)
    assert hit is not None, pid
    return dict(hit)


# ===========================================================================
# A · 预设声明可枚举（形状齐备）
# ===========================================================================
def test_preset_table_enumerable_and_shaped() -> None:
    rows = fx.framework_effect_presets()
    assert rows, "框架特效预设集不得为空"
    ids = [str(p["id"]) for p in rows]
    assert len(ids) == len(set(ids)), "预设 id 必须唯一"
    for p in rows:
        assert p["label"] and p["help"]
        assert len(str(p["help"])) <= fx.MAX_HELP_LEN, f"{p['id']} help 忌长文"
        assert p["slot"] in fx.PRESET_SLOTS
        assert p["direction"] in fx.PRESET_DIRECTIONS
        assert p["family"] and p["conflict_group"]
        assert p["axis"] and p["stack"] in ("add", "mult")
        assert set(p["tiers"]) == set(fx.PRESET_TIERS), f"{p['id']} 须三档齐备"
        assert p["axis"] in p["fields"]
        assert p["defaults"] == {p["axis"]: p["tiers"][fx.DEFAULT_TIER]}


def test_preset_errors_clean_and_key_errors_clean() -> None:
    assert fx.effect_preset_errors(table=TABLE) == []
    assert entry_presets_mod.framework_preset_key_errors(TABLE) == []


# ===========================================================================
# B · 预设声明可校验（越界红拦 / 引用轴存在）
# ===========================================================================
def _synthetic(**over: Any) -> Dict[str, Any]:
    """基于一条真预设派生的合成条目（用于注入非法值，不改框架表）。"""
    base = dict(fx.framework_effect_presets()[0])
    base["tiers"] = dict(base["tiers"])
    base.update(over)
    if "axis" in over or "tiers" in over:
        base["defaults"] = {base["axis"]: base["tiers"][fx.DEFAULT_TIER]}
    return base


def test_unknown_axis_is_red() -> None:
    bad = _synthetic(axis="no_such_axis", fields=("name", "no_such_axis"),
                     defaults={"no_such_axis": 1})
    errs = fx.effect_preset_errors([bad], table=TABLE)
    assert any("引用轴不存在" in e for e in errs), errs


def test_out_of_range_tier_is_red() -> None:
    bad = _synthetic(id="bad_range", axis="healing_received_pct",
                     tiers={"normal": 15, "advanced": 30, "rare": 99999},
                     fields=("name", "healing_received_pct"),
                     defaults={"healing_received_pct": 15})
    errs = fx.effect_preset_errors([bad], table=TABLE)
    assert any("越界" in e for e in errs), errs


def test_duplicate_id_and_default_tier_mismatch_are_red() -> None:
    a = _synthetic()
    b = _synthetic()
    assert any("id 重复" in e for e in fx.effect_preset_errors([a, b], table=TABLE))
    c = _synthetic(id="mismatch", defaults={a["axis"]: 999})
    assert any("未取 normal 档" in e for e in fx.effect_preset_errors([c], table=TABLE))


def test_valid_synthetic_preset_passes() -> None:
    good = _synthetic(id="ok_copy")
    assert fx.effect_preset_errors([good], table=TABLE) == []


# ===========================================================================
# C · 同族两方向（一条轴两个方向，同组互斥）
# ===========================================================================
@pytest.mark.parametrize("family,axis,group", TWO_WAY_FAMILIES)
def test_two_way_family_shares_axis_and_opposes(family: str, axis: str,
                                                group: str) -> None:
    rows = [p for p in fx.framework_effect_presets() if p["family"] == family]
    dirs = {str(p["direction"]) for p in rows}
    assert dirs == {"up", "down"}, f"{family} 须两方向齐备：{dirs}"
    assert {str(p["axis"]) for p in rows} == {axis}, family
    assert {str(p["conflict_group"]) for p in rows} == {group}, family
    up = [p for p in rows if p["direction"] == "up"]
    down = [p for p in rows if p["direction"] == "down"]
    assert all(float(p["tiers"]["normal"]) > 0 for p in up), family
    assert all(float(p["tiers"]["normal"]) < 0 for p in down), family


def test_healing_pair_is_the_canonical_example() -> None:
    """任务书范例：重伤 = `healing_received_pct: -15` / 强疗 = 同轴 `+15`。"""
    down = _preset("armor_heal_down")
    up = _preset("armor_heal_up")
    assert down["axis"] == up["axis"] == "healing_received_pct"
    assert down["tiers"]["normal"] == -15
    assert up["tiers"]["normal"] == 15
    assert down["conflict_group"] == up["conflict_group"]


# ===========================================================================
# D · 复用既有 entry_presets 机制（不新造一套）
# ===========================================================================
def test_items_six_presets_unchanged() -> None:
    assert [p["id"] for p in entry_presets_mod.framework_presets("items")] == [
        "material", "currency_pouch", "potion", "gift_box", "equipment", "skill_book"]
    assert entry_presets_mod.framework_presets("things") == ()
    assert entry_presets_mod.merge_entry_presets("things") == ()


def test_equipment_presets_come_from_effect_table() -> None:
    got = [p["id"] for p in entry_presets_mod.framework_presets(MODULE)]
    assert got == [p["id"] for p in fx.effect_presets_for(MODULE)]
    assert got, "equipment 模块应能选到框架特效预设"


def test_merge_override_and_disable_reuse_same_mechanism() -> None:
    pid = fx.framework_effect_presets()[0]["id"]
    pack = [{"id": pid, "label": "包改名", "help": "包口径",
             "fields": ("name",), "defaults": {}, "id_prefix": "pack"}]
    merged = entry_presets_mod.merge_entry_presets(MODULE, pack)
    hit = [p for p in merged if p["id"] == pid]
    assert len(hit) == 1 and hit[0]["label"] == "包改名"
    off = entry_presets_mod.merge_entry_presets(MODULE, (), disabled=(pid,))
    assert pid not in [p["id"] for p in off]


def test_entry_preset_projection_carries_metadata() -> None:
    entry = fx.entry_presets_for(MODULE)[0]
    for key in ("id", "label", "help", "fields", "defaults", "id_prefix", "id_width"):
        assert key in entry
    for key in ("axis", "slot", "family", "direction", "stack", "conflict_group", "tiers"):
        assert key in entry


# ===========================================================================
# E · 编辑器可见（中文名 + 一句话 help；选中后主区/折叠区）
# ===========================================================================
def test_editor_lists_effect_presets_with_labels(temp_pack: Path) -> None:
    d = api.new_entry_detail("tp", MODULE, root=temp_pack, name="x")
    got = {p["id"]: p for p in d["presets"]}
    for p in fx.framework_effect_presets():
        assert p["id"] in got, p["id"]
        assert got[p["id"]]["label"] == p["label"]
        assert got[p["id"]]["help"] == p["help"]
        assert len(got[p["id"]]["help"]) <= fx.MAX_HELP_LEN
        assert got[p["id"]]["field_count"] == len(p["fields"])
    # 不选预设 = 现状：全部字段主区、无折叠区
    assert d["preset"] == "" and d["other_fields"] == []


def test_editor_selected_preset_fields_and_defaults(temp_pack: Path) -> None:
    p = _preset("armor_heal_up")
    d = api.new_entry_detail("tp", MODULE, root=temp_pack, name="x",
                             preset=str(p["id"]))
    assert [f["key"] for f in d["fields"]] == list(p["fields"])
    values = {f["key"]: f["value"] for f in d["fields"]}
    assert values["healing_received_pct"] == 15
    assert d["preset_missing_fields"] == []
    # 一号原则：未包含的字段进「其他字段」且仍可编辑
    assert d["other_fields"] and all(f["editable"] for f in d["other_fields"])


def test_editor_preset_id_prefix(temp_pack: Path) -> None:
    out = api.suggest_id("tp", MODULE, root=temp_pack, name="x", preset="armor_heal_up")
    assert out["suggested_id"] == "heal_001"


def test_http_equipment_presets_visible_and_land(temp_pack: Path) -> None:
    """HTTP 链路：预设可选（中文名 + help 齐备）；POST 创建按预设落档。"""
    from fastapi.testclient import TestClient

    from editor_host import create_app

    with TestClient(create_app(pack="tp", root=str(temp_pack), role="owner")) as client:
        got = client.get("/api/pack/tp/module/equipment/new").json()
        by_id = {p["id"]: p for p in got["presets"]}
        assert by_id["armor_heal_up"]["label"] == "强疗"
        assert by_id["armor_heal_down"]["label"] == "重伤"
        assert by_id["armor_heal_up"]["help"]
        got2 = client.get("/api/pack/tp/module/equipment/new",
                          params={"preset": "armor_heal_up"}).json()
        assert "healing_received_pct" in [f["key"] for f in got2["fields"]]
        r = client.post("/api/pack/tp/module/equipment/entry",
                        json={"entry_id": "eq_009", "patch": {"name": "甲"},
                              "preset": "armor_heal_up"}).json()
        assert r["ok"] is True, r
        defs = json.loads((temp_pack / "tp" / "equipment.json").read_text(encoding="utf-8"))
        assert defs[0]["healing_received_pct"] == 15


# ===========================================================================
# F · 落进产物实例（def → 聚合 → 战斗桥）
# ===========================================================================
def test_preset_lands_in_item_def_and_battle_bridge(temp_pack: Path) -> None:
    p = _preset("armor_taken_down")
    env = editor_ops.create_entry("tp", MODULE, "eq_001", {"name": "试甲"},
                                  root=temp_pack, preset=str(p["id"]))
    assert env["ok"] is True, env
    defs = json.loads((temp_pack / "tp" / "equipment.json").read_text(encoding="utf-8"))
    row = [d for d in defs if d["id"] == "eq_001"][0]
    assert row["damage_taken_pct"] == -8
    bonus = extract_bonus(row)
    assert bonus == {"damage_taken_pct": -8.0}
    flat: Dict[str, float] = {}
    pct: Dict[str, float] = {}
    route_bonus_into(bonus, flat, pct)
    assert flat["damage_taken_pct"] == -8.0 and pct == {}
    assert combatant_updates(flat, pct) == {"damage_taken_pct": -8.0}


def test_preset_create_then_rollback_restores(temp_pack: Path) -> None:
    pack_dir = temp_pack / "tp"
    before = (pack_dir / "equipment.json").read_bytes()
    env = editor_ops.create_entry("tp", MODULE, "eq_001", {"name": "试甲"},
                                  root=temp_pack, preset="weapon_cd_haste")
    assert env["ok"] is True, env
    rb = editor_ops.rollback_module("tp", MODULE, root=temp_pack)
    assert rb.get("ok") is True, rb
    assert (pack_dir / "equipment.json").read_bytes() == before


# ===========================================================================
# G · 零变化（不启用预设 → 框架预设不泄漏）
# ===========================================================================
def test_no_preset_creation_keeps_zero_axes(temp_pack: Path) -> None:
    env = editor_ops.create_entry("tp", MODULE, "eq_000", {"name": "素甲"}, root=temp_pack)
    assert env["ok"] is True, env
    defs = json.loads((temp_pack / "tp" / "equipment.json").read_text(encoding="utf-8"))
    row = [d for d in defs if d["id"] == "eq_000"][0]
    # 不启用预设 → 每条特效轴都是恒等 0.0（与批50 起的既有缺省一致，无预设值泄漏）
    for axis in GEAR_EFFECT_KEYS:
        assert row.get(axis, 0.0) == 0.0, axis
    assert extract_bonus(row) == {}


# ===========================================================================
# H · 结算/奖励轴核查结论（如实报告，不硬造）
# ===========================================================================
def test_reward_axis_not_registered_no_single_consumer() -> None:
    """批54 核查：`reward_mult{scope}` 无**可复用的唯一消费点** → 不登记（如实报告）。

    证据（三处分散，且标量口径被非战斗系统共用）：
      · `core/reward.dispatch_reward`（`_SCALAR_KEYS = coins/gem/exp/rep`）是
        任务/签到/NPC/钓鱼/成就/PvP **共用**发放器 → 在此加装备倍率会外溢到非战斗奖励；
      · `core/battle_reward.settle_battle_rewards` 中 **exp 走 `LevelUpEngine.gain_exp`**，
        与币的 `dispatch_reward` 路径**不是同一点**；
      · 掉率在 `core/battle_reward.roll_death_drops` 的 `chance` roll。
    验收红线「一条轴多 scope，勿造三键」：框架扁平数值键空间无法在不造多键 /
    不新造对象型轴形状的前提下承载 scope → 本批**只报告，不登记、不接线**。
    """
    from qbot_rpg.core import battle_reward, reward

    assert set(reward._SCALAR_KEYS) >= {"coins", "gem", "exp", "rep"}
    assert not [k for k in GEAR_EFFECT_KEYS if any(
        t in k for t in ("reward", "loot", "drop", "exp_gain", "coin"))]
    assert not [p for p in fx.framework_effect_presets()
                if any(t in str(p["axis"]) for t in ("reward", "loot", "drop"))]
    settle_src = inspect.getsource(battle_reward.settle_battle_rewards)
    assert "gain_exp" in settle_src and "dispatch_reward" in settle_src
    assert "roll_death_drops" in settle_src
