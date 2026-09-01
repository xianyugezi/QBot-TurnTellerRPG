"""M13 批3 路3B：6a test_demo 技能库示例（细化_6a §1.2/§1.4/§5/⑥）fixture 单测。

覆盖：
  - 四类时机齐备（basic ≥1 / active ≥3 / passive ≥1 / trigger ≥1，§1.4）
  - 全字段形态覆盖（F01-F24：mp_cost/cooldown/tag/armor/interrupt/chain_refs/
    job_restrict/consume_marks/hits/trigger_limit/desc/hit_mod/crit_mod/block_mode）
  - effects 双形态（引用 {effect,overrides} / 原子动作 {type,...}，§1.3-f2）
  - 魔法穿透裁决样例（pierce{target:def|spr}，§5.2/TC-19/TC-22）
  - 引用有效性（effects/marks 引用 ∈ 各自表；V-1/V-3 零红拦）
  - build_pack 全链路零红拦 + registry 登记

铁律：零 NoneBot import；零定时器/零睡眠；纯函数确定性；不 git commit。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from qbot_rpg.content.loader import build_pack

REPO = Path(__file__).resolve().parents[2]
DEMO = REPO / "content" / "test_demo"

# 契约 §1.4 四类时机（F08）
SKILL_TYPES = ("basic", "active", "passive", "trigger")
# 契约 §1.2-B F11 tag 六枚举
SKILL_TAGS = {"none", "combo", "combo_preserve", "combo_push", "interrupt", "armor"}
# 契约 §5.2 pierce target 枚举
PIERCE_TARGETS = {"def", "spr"}


def _load(name: str) -> Any:
    return json.loads((DEMO / name).read_text(encoding="utf-8"))


def _skills() -> List[Dict[str, Any]]:
    return _load("skills.json")


def _effects_ids() -> set:
    return {e["id"] for e in _load("effects.json")}


# ---------------------------------------------------------------------------
# 1. 四类时机齐备（§1.4）
# ---------------------------------------------------------------------------
def test_four_types_all_present() -> None:
    """四类时机各 ≥1：basic ≥1 / active ≥3 / passive ≥1 / trigger ≥1。"""
    skills = _skills()
    by_type: Dict[str, int] = {}
    for s in skills:
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
    assert by_type.get("basic", 0) >= 1, "缺 basic"
    assert by_type.get("active", 0) >= 3, "缺 active（需 ≥3）"
    assert by_type.get("passive", 0) >= 1, "缺 passive"
    assert by_type.get("trigger", 0) >= 1, "缺 trigger"
    assert set(by_type) <= set(SKILL_TYPES), f"非法 type：{set(by_type) - set(SKILL_TYPES)}"


def test_basic_skill_is_mp_free_no_cooldown() -> None:
    """basic=0 MP/0 冷却（契约 [L62]：basic 不消耗、无冷却）。"""
    basic = next(s for s in _skills() if s["type"] == "basic")
    assert basic["mp_cost"] == 0
    assert basic["cooldown"] == 0


# ---------------------------------------------------------------------------
# 2. 字段形态覆盖（§1.2 F01-F24）
# ---------------------------------------------------------------------------
def test_field_shape_mp_cost_cooldown_variants() -> None:
    """mp_cost/cooldown 形态：active 非零成本 + basic 零值并存。"""
    active = [s for s in _skills() if s["type"] == "active"]
    assert any(s["mp_cost"] > 0 for s in active), "active 应含 mp_cost>0 样例"
    assert any(s["cooldown"] > 0 for s in active), "active 应含 cooldown>0 样例"
    for s in _skills():
        assert isinstance(s["mp_cost"], (int, float)) and s["mp_cost"] >= 0
        assert isinstance(s["cooldown"], (int, float)) and s["cooldown"] >= 0


def test_field_shape_tag_variants() -> None:
    """tag 六枚举形态：库内出现至少 4 种不同 tag。"""
    tags = {s["tag"] for s in _skills()}
    assert len(tags) >= 4, f"tag 形态覆盖不足：{sorted(tags)}"
    assert tags <= SKILL_TAGS


def test_field_shape_armor_interrupt_bools() -> None:
    """armor/interrupt 布尔形态：true/false 两态都有样例。"""
    armor = [s["armor"] for s in _skills()]
    interrupt = [s["interrupt"] for s in _skills()]
    assert any(armor) and not all(armor), "armor 应同时有 true/false 样例"
    assert any(interrupt) and not all(interrupt), "interrupt 应同时有 true/false 样例"


def test_field_shape_chain_refs_consume_marks_job() -> None:
    """chain_refs/job_restrict 空列表形态 + job_form null + level 对象/空形态。"""
    for s in _skills():
        assert s["chain_refs"] == [], "test_demo 无 skill_chains 表，chain_refs 必须为空（V-2）"
        assert s["job_restrict"] == [], "test_demo 无 jobs 表，job_restrict 必须为空（V-5）"
        assert s["job_form"] is None
    levels = [s["level"] for s in _skills() if s["level"] is not None]
    assert levels, "应至少 1 条技能带 level 升级对象（F18 形态）"


def test_field_shape_consume_marks_and_hits() -> None:
    """consume_marks 非空样例（F15）+ hits 多段样例 hits=3（F19，TC-03）。"""
    consumers = [s for s in _skills() if s["consume_marks"]]
    assert len(consumers) >= 2, "应至少 2 条技能消耗印记（F15 形态）"
    for s in consumers:
        for mark_id, count in s["consume_marks"].items():
            assert isinstance(count, int) and count >= 1, f"{s['id']} 消耗 {mark_id} 需正整数"
    multi = [s for s in _skills() if s["hits"] > 1]
    assert multi, "应至少 1 条 hits>1 多段技能（F19）"
    for s in _skills():
        assert isinstance(s["hits"], int) and s["hits"] >= 1


def test_field_shape_trigger_limit_and_desc_mods() -> None:
    """trigger_limit 收紧样例（F20）+ desc/hit_mod/crit_mod/block_mode 形态（F21-F24）。"""
    limited = [
        s for s in _skills()
        if s["type"] == "trigger"
        and s["trigger_limit"] != {"per_round": 10, "per_battle": 99}
    ]
    assert limited, "trigger 应含收紧 trigger_limit 样例（F20 技能级覆盖）"
    for s in _skills():
        assert s["desc"], f"{s['id']} desc 非空（F21）"
        assert isinstance(s["hit_mod"], (int, float)) and s["hit_mod"] > 0, "hit_mod >0（F22）"
        assert isinstance(s["crit_mod"], (int, float)) and s["crit_mod"] > 0, "crit_mod >0（F23）"
        assert s["block_mode"] in {"auto", "normal", "ignore"}, "block_mode 三枚举（F24）"
    assert any(s["hit_mod"] != 1.0 for s in _skills()), "应含 hit_mod≠1.0 样例"
    assert any(s["crit_mod"] != 1.0 for s in _skills()), "应含 crit_mod≠1.0 样例"
    assert any(s["block_mode"] != "auto" for s in _skills()), "应含 block_mode≠auto 样例"


def test_skill_entry_all_24_fields_present() -> None:
    """每条技能条目携带契约 24 字段（F01-F24）——fixture 全配不靠默认值兜底。"""
    contract_fields = {
        "id", "name", "kind", "power", "attack_type", "element", "effects",
        "type", "mp_cost", "cooldown", "tag", "armor", "interrupt",
        "chain_refs", "consume_marks", "job_restrict", "job_form", "level",
        "hits", "trigger_limit", "desc", "hit_mod", "crit_mod", "block_mode",
    }
    for s in _skills():
        missing = contract_fields - set(s)
        assert not missing, f"{s['id']} 缺字段：{sorted(missing)}"


def test_effects_dual_form_present() -> None:
    """effects 双形态（§1.3-f2）：对象引用 {effect,overrides} 与原子动作 {type,...} 均有样例。"""
    ref_form = any(any("effect" in e for e in s["effects"]) for s in _skills())
    atomic_form = any(any("type" in e for e in s["effects"]) for s in _skills())
    assert ref_form, "缺效果引用形态（{effect,...}）"
    assert atomic_form, "缺原子动作形态（{type,...}）"
    overrides = any(
        any(isinstance(e, dict) and "overrides" in e for e in s["effects"])
        for s in _skills()
    )
    assert overrides, "缺 overrides 覆盖样例（§1.3-f2 示例 {power:50}）"


# ---------------------------------------------------------------------------
# 3. 引用有效性（V-1/V-3/V-4）
# ---------------------------------------------------------------------------
def test_all_effect_refs_exist() -> None:
    """effects[].effect ∈ effects.json id（V-1 红拦口径：表内引用零悬空）。"""
    ids = _effects_ids()
    for s in _skills():
        for e in s["effects"]:
            if "effect" in e:
                assert e["effect"] in ids, f"{s['id']} 引用不存在效果 {e['effect']}"


def test_all_consume_marks_exist_within_max() -> None:
    """consume_marks 键 ∈ marks.json 且值 ≤ max_stack（V-3 红拦口径）。"""
    marks = {m["id"]: m for m in _load("marks.json")}
    for s in _skills():
        for mark_id, count in s["consume_marks"].items():
            assert mark_id in marks, f"{s['id']} 引用不存在印记 {mark_id}"
            assert count <= marks[mark_id]["max_stack"], (
                f"{s['id']} 消耗 {mark_id}×{count} 超上限 {marks[mark_id]['max_stack']}"
            )


def test_all_elements_in_registry() -> None:
    """element ∈ 8 元素注册表（V-4）：覆盖注册表子集 ≥3 种。"""
    from qbot_rpg.content.skill_models import SKILL_ELEMENTS

    for s in _skills():
        if s["element"] is not None:
            assert s["element"] in SKILL_ELEMENTS, f"{s['id']} element {s['element']} 未注册（V-4）"
    used = {s["element"] for s in _skills() if s["element"]}
    assert len(used) >= 3, f"元素形态覆盖不足：{sorted(used)}"


# ---------------------------------------------------------------------------
# 4. 魔法穿透裁决样例（§5 / TC-19 / TC-22 / TC-20）
# ---------------------------------------------------------------------------
def _pierce_entries() -> List[tuple]:
    out = []
    for s in _skills():
        for e in s["effects"]:
            if isinstance(e, dict) and e.get("type") == "pierce":
                out.append((s["id"], s, e))
    return out


def test_pierce_samples_both_targets() -> None:
    """pierce{target:def}（物理穿透）+ pierce{target:spr}（魔法穿透）各至少 1 样例（§5.2）。"""
    pierces = _pierce_entries()
    assert pierces, "缺 pierce 原子动作样例（契约 §5.2）"
    targets = {e["target"] for _, _, e in pierces}
    assert targets == PIERCE_TARGETS, f"pierce target 应覆盖 def+spr：{sorted(targets)}"
    for _, _, e in pierces:
        assert e["target"] in PIERCE_TARGETS
        assert isinstance(e.get("pct"), (int, float)) and 0 <= e["pct"] <= 100


def test_magic_pierce_skill_is_magic_attack() -> None:
    """魔法穿透样例（pierce{target:spr}）落在 magic 且带 element 的技能（TC-19/TC-22）。"""
    hit = False
    for _, s, e in _pierce_entries():
        if e.get("target") == "spr":
            assert s["attack_type"] == "magic", f"{s['id']} spr 穿透需 magic 攻击（V-12 对位）"
            assert s["element"] is not None, f"{s['id']} 魔法穿透需带 element"
            hit = True
    assert hit, "缺 pierce target=spr 样例"


def test_physical_pierce_skill_is_physical_attack() -> None:
    """物理穿透样例（pierce{target:def}）落在物理 attack_type（V-12 对位）。"""
    hit = False
    for _, s, e in _pierce_entries():
        if e.get("target") == "def":
            assert s["attack_type"] in {"slash", "blunt", "pierce"}, (
                f"{s['id']} def 穿透需物理攻击（V-12 对位）"
            )
            hit = True
    assert hit, "缺 pierce target=def 样例"


# ---------------------------------------------------------------------------
# 5. build_pack 全链路（零红拦 + registry 登记）
# ---------------------------------------------------------------------------
def test_build_pack_zero_red_and_registry_count() -> None:
    """build_pack 加载 test_demo 零红拦，skill 注册数 = skills.json 条目数。"""
    pack, _ = build_pack(DEMO)
    assert pack.report.count_errors == 0, f"不应红拦：{pack.report.errors}"
    n = len(_skills())
    assert len(pack.registry.all_ids("skill")) == n, (
        f"registry 应登记 {n} 条技能，got {len(pack.registry.all_ids('skill'))}"
    )


def test_registry_resolves_every_skill() -> None:
    """registry.resolve 逐条命中（kind=skill）。"""
    pack, _ = build_pack(DEMO)
    for s in _skills():
        assert pack.registry.resolve(s["id"], "skill") is not None, (
            f"技能 {s['id']} 未注册进 skill 表"
        )
