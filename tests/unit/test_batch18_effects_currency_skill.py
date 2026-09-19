"""批18 · 两类新效果能力（段 B）：`gain_currency` / `learn_skill`。

覆盖任务书（通用、不写死内容包业务名）：
  · 校验器：两新类型的必填/范围/引用存在性（红拦口径与依据见 validator `_check_effects_18`）；
  · 引擎消费（commands/use_commands 背包内「使用」）：
    - `gain_currency`：固定金额（min==max）给钱准确；随机区间多次落 `[min,max]` 且确实变化
      （注入确定性 RNG，不 flaky）；缺 `amount_max` = 固定；min>max / 负数 / 两者都缺 → 校验红；
      使用后玩家档案货币真的增加（贴数值）；
    - `learn_skill`：授予成功（技能进装配槽 + 等级正确）；重复使用幂等；引用缺失红拦；
  · 编辑器：两个新类型在 effects.type 下拉可选（enum_options）、新字段可见可填、
    真写盘可保存（editor_ops）；
  · 端到端：temp 包造货币袋/技能书 → 使用 → 数值/装配变化 → 回退逐字节复原。
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from qbot_rpg.commands.parsers import parse_command
from qbot_rpg.commands.use_commands import cmd_use
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"

FROZEN_KEYS = ("id", "name", "type", "power", "duration",
               "currency", "amount_min", "amount_max", "skill", "level")


# ---------------------------------------------------------------------------
# 通用：无内容包业务名的效果/物品/上下文工厂
# ---------------------------------------------------------------------------
def _fake_item(item_id: str, name: str, slot: str = "") -> Any:
    return SimpleNamespace(
        item_id=item_id, name=name, slot=slot, acquired_at="2026-09-16 12:00:00")


def make_ctx(item_def: Dict[str, Any], effect_def: Dict[str, Any], **over: Any) -> dict:
    """单物品/单效果的已注册 ctx（注入假背包引擎；货币桶初始 0）。"""
    base: Dict[str, Any] = {
        "registered": True,
        "player": {
            "name": "测试勇士", "level": 1, "job_id": "warrior", "hp": 30,
            "inventory": [], "equipment": {}, "currencies": {},
            "attributes": {"base": {"hp": 100.0, "mp": 30.0}},
        },
        "items": {str(item_def["id"]): item_def},
        "effect_table": {str(effect_def["id"]): effect_def},
        "settings": {"currencies": [{"id": "coins", "name": "金币", "cap": 0}]},
        "equip_engine": SimpleNamespace(
            _sorted_inventory=lambda p: [
                _fake_item(str(item_def["id"]), str(item_def.get("name") or ""))],
            equip_wear=lambda idx, ctx: {"ok": True, "message": "✅"},
        ),
        "inventory_engine": SimpleNamespace(
            remove_item=lambda p, item_id, count=1, uid="": {"ok": True}),
    }
    base.update(over)
    return base


def _use(ctx: dict) -> str:
    return cmd_use(parse_command("/使用 1"), ctx)


# ---------------------------------------------------------------------------
# 一、校验器：必填 / 范围 / 引用存在性（分级依据见 validator docstring）
# ---------------------------------------------------------------------------
def _effect_errors(effects: List[Dict[str, Any]], **mods: Any) -> List[Tuple[str, str, dict]]:
    modules: Dict[str, Any] = {"effects": effects}
    modules.update(mods)
    report = check_pack(modules)
    return [(e.kind, e.field, dict(e.detail)) for e in report.errors
            if str(e.field).startswith("effects.")]


SETTINGS = {"currencies": [{"id": "coins", "name": "金币"}]}


def test_validator_gain_currency_fixed_and_missing_max_ok() -> None:
    fixed = [{"id": "e1", "type": "gain_currency", "currency": "coins",
              "amount_min": 5, "amount_max": 5}]
    assert _effect_errors(fixed, settings=SETTINGS) == []
    # 缺 amount_max → 视为等于 amount_min（合法，不报错）
    only_min = [{"id": "e1", "type": "gain_currency", "currency": "coins", "amount_min": 5}]
    assert _effect_errors(only_min, settings=SETTINGS) == []
    only_max = [{"id": "e1", "type": "gain_currency", "currency": "coins", "amount_max": 7}]
    assert _effect_errors(only_max, settings=SETTINGS) == []


def test_validator_gain_currency_both_amounts_missing_is_red() -> None:
    got = _effect_errors([{"id": "e1", "type": "gain_currency", "currency": "coins"}],
                         settings=SETTINGS)
    assert got and got[0][0] == "R-5"
    assert got[0][2]["rule"] == "gain_currency_amount_missing"


def test_validator_gain_currency_missing_currency_is_red() -> None:
    got = _effect_errors([{"id": "e1", "type": "gain_currency", "amount_min": 5}],
                         settings=SETTINGS)
    assert got and got[0][0] == "R-5" and got[0][2]["rule"] == "required_missing"


def test_validator_gain_currency_unknown_currency_is_red() -> None:
    got = _effect_errors([{"id": "e1", "type": "gain_currency", "currency": "gem",
                           "amount_min": 5}], settings=SETTINGS)
    assert got and got[0][0] == "R-4" and got[0][2]["rule"] == "currency_ref_missing"


def test_validator_gain_currency_range_inverted_is_red() -> None:
    got = _effect_errors([{"id": "e1", "type": "gain_currency", "currency": "coins",
                           "amount_min": 9, "amount_max": 5}], settings=SETTINGS)
    assert got and got[0][0] == "R-5" and got[0][2]["rule"] == "dead_range"


def test_validator_gain_currency_negative_is_red() -> None:
    got = _effect_errors([{"id": "e1", "type": "gain_currency", "currency": "coins",
                           "amount_min": -3, "amount_max": 5}], settings=SETTINGS)
    assert got and got[0][0] == "R-2" and got[0][2]["rule"] == "negative"


def test_validator_learn_skill_reference_and_level() -> None:
    skills = [{"id": "basic_attack", "name": "普攻", "type": "basic"},
              {"id": "power_strike", "name": "强击", "type": "active"}]
    ok = [{"id": "e1", "type": "learn_skill", "skill": "power_strike", "level": 3}]
    got = [(k, f, d) for k, f, d in _effect_errors(ok, skills=skills)
           if not f.startswith("skills")]
    assert got == []
    # 引用不存在 → 红拦（泛型 ref R-4）
    bad = [{"id": "e1", "type": "learn_skill", "skill": "no_such_skill"}]
    got = [(k, f, d) for k, f, d in _effect_errors(bad, skills=skills)
           if not f.startswith("skills")]
    assert got and got[0][0] == "R-4" and got[0][2]["rule"] == "ref_missing"
    # 缺 skill → 红拦（类型相关必填）
    got = [(k, f, d) for k, f, d in _effect_errors(
        [{"id": "e1", "type": "learn_skill"}], skills=skills) if not f.startswith("skills")]
    assert got and got[0][0] == "R-5" and got[0][2]["rule"] == "required_missing"
    # level 0 → 红拦；level 缺省/≥1 → 合法
    got = [(k, f, d) for k, f, d in _effect_errors(
        [{"id": "e1", "type": "learn_skill", "skill": "power_strike", "level": 0}],
        skills=skills) if not f.startswith("skills")]
    assert got and got[0][0] == "R-1" and got[0][2]["rule"] == "skill_level_invalid"
    assert [k for k, f, _d in _effect_errors(
        [{"id": "e1", "type": "learn_skill", "skill": "power_strike"}], skills=skills)
        if not f.startswith("skills")] == []
    # 负数 → 红拦（泛型 R-2）
    got = [(k, f, d) for k, f, d in _effect_errors(
        [{"id": "e1", "type": "learn_skill", "skill": "power_strike", "level": -1}],
        skills=skills) if not f.startswith("skills")]
    assert got and got[0][0] == "R-2" and got[0][2]["rule"] == "negative"


# ---------------------------------------------------------------------------
# 二、引擎消费：gain_currency
# ---------------------------------------------------------------------------
def _pouch(effect: Dict[str, Any], **over: Any) -> Tuple[dict, dict]:
    item = {"id": "pouch_x", "name": "测试钱袋", "type": "currency",
            "usable": True, "effects": [effect["id"]]}
    item.update(over)
    return item, effect


def test_gain_currency_fixed_amount_exact() -> None:
    item, eff = _pouch({"id": "fx", "name": "固定", "type": "gain_currency",
                        "currency": "coins", "amount_min": 120, "amount_max": 120})
    ctx = make_ctx(item, eff)
    out = _use(ctx)
    assert "获得" in out and "120" in out
    assert ctx["player"]["currencies"] == {"coins": 120}


def test_gain_currency_missing_max_is_fixed_and_rng_untouched() -> None:
    item, eff = _pouch({"id": "fx", "name": "固定", "type": "gain_currency",
                        "currency": "coins", "amount_min": 42})
    ctx = make_ctx(item, eff)
    rng = random.Random(2026)
    ctx["rng"] = rng
    before = rng.getstate()
    _use(ctx)
    assert ctx["player"]["currencies"] == {"coins": 42}
    # min==max（或只给 min）→ 不消耗随机数（同一状态 ⇒ 无随机源介入）
    assert rng.getstate() == before


def test_gain_currency_random_range_in_bounds_and_varies() -> None:
    item, eff = _pouch({"id": "rnd", "name": "随机", "type": "gain_currency",
                        "currency": "coins", "amount_min": 10, "amount_max": 20})
    amounts: List[int] = []
    rng = random.Random(2026)  # 同一确定性 RNG 实例贯穿多轮（种子固定，非 flaky）
    for _ in range(40):
        ctx = make_ctx(item, eff)
        ctx["rng"] = rng
        _use(ctx)
        amounts.append(ctx["player"]["currencies"]["coins"])
    assert all(10 <= a <= 20 for a in amounts), amounts
    assert len(set(amounts)) > 1, "随机区间应确实变化（种子固定，非 flaky）"


def test_gain_currency_uses_injected_rng_single_source() -> None:
    """注入的 ctx["rng"] 即唯一随机源：同种子 → 同序列（不引入新随机源）。"""
    item, eff = _pouch({"id": "rnd", "name": "随机", "type": "gain_currency",
                        "currency": "coins", "amount_min": 1, "amount_max": 100})
    seq_a, seq_b = [], []
    for seq in (seq_a, seq_b):
        rng = random.Random(7)
        for _ in range(5):
            ctx = make_ctx(item, eff)
            ctx["rng"] = rng  # 同一实例跨多次使用，序列连续
            _use(ctx)
            seq.append(ctx["player"]["currencies"]["coins"])
    assert seq_a == seq_b


def test_gain_currency_zero_amount_no_bucket_write() -> None:
    item, eff = _pouch({"id": "zero", "name": "零", "type": "gain_currency",
                        "currency": "coins", "amount_min": 0, "amount_max": 0})
    ctx = make_ctx(item, eff)
    out = _use(ctx)
    # 0 金额 → 不写货币桶（避免无意义入账）；但仍算「可使用的消耗品」（已扣物品，不报不可用）
    assert ctx["player"]["currencies"] == {}
    assert "使用成功" in out and "0" in out


def test_gain_currency_negative_amount_runtime_skipped() -> None:
    """运行期非法区间（负数）→ 该效果不生效、不崩（校验层红拦是主防线）。"""
    item, eff = _pouch({"id": "bad", "name": "坏", "type": "gain_currency",
                        "currency": "coins", "amount_min": -5, "amount_max": 5})
    ctx = make_ctx(item, eff)
    out = _use(ctx)
    assert ctx["player"]["currencies"] == {}
    assert out  # 有兜底文案，不抛异常


# ---------------------------------------------------------------------------
# 三、引擎消费：learn_skill
# ---------------------------------------------------------------------------
def _skill_book(effect: Dict[str, Any], **over: Any) -> Tuple[dict, dict]:
    item = {"id": "book_x", "name": "测试技能书", "type": "skill_book",
            "usable": True, "effects": [effect["id"]]}
    item.update(over)
    return item, effect


SKILLS = {"power_strike": {"id": "power_strike", "name": "强击", "type": "active"},
          "stone_guard": {"id": "stone_guard", "name": "石守", "type": "passive"}}


def test_learn_skill_grants_with_level() -> None:
    item, eff = _skill_book({"id": "ls", "name": "学技", "type": "learn_skill",
                             "skill": "power_strike", "level": 3})
    ctx = make_ctx(item, eff, skills=SKILLS)
    out = _use(ctx)
    assert "学会技能" in out and "power_strike" in out and "Lv3" in out
    snap = ctx["player"]["persistent_state"]["skill_slots"]
    rows = [r for r in snap["slots"] if r.get("skill_id") == "power_strike"]
    assert len(rows) == 1 and rows[0]["level"] == 3 and rows[0]["slot"] == "active"
    assert "power_strike" in snap["active_order"]


def test_learn_skill_default_level_one_and_passive_slot() -> None:
    item, eff = _skill_book({"id": "ls", "name": "学技", "type": "learn_skill",
                             "skill": "stone_guard"})
    ctx = make_ctx(item, eff, skills=SKILLS)
    _use(ctx)
    snap = ctx["player"]["persistent_state"]["skill_slots"]
    rows = [r for r in snap["slots"] if r.get("skill_id") == "stone_guard"]
    assert rows and rows[0]["level"] == 1 and rows[0]["slot"] == "passive"
    assert any(r.get("skill_id") == "stone_guard" for r in snap["passive"])


def test_learn_skill_repeat_is_idempotent() -> None:
    item, eff = _skill_book({"id": "ls", "name": "学技", "type": "learn_skill",
                             "skill": "power_strike", "level": 2})
    ctx = make_ctx(item, eff, skills=SKILLS)
    first = _use(ctx)
    second = _use(ctx)
    assert "学会技能" in first
    assert "已学会" in second
    snap = ctx["player"]["persistent_state"]["skill_slots"]
    rows = [r for r in snap["slots"] if r.get("skill_id") == "power_strike"]
    assert len(rows) == 1, "重复使用不得重复授予"
    assert snap["active_order"].count("power_strike") == 1


def test_learn_skill_does_not_downgrade_existing_level() -> None:
    """已学会（高等级）→ 再用低等级书：幂等，不改既有等级。"""
    item, eff = _skill_book({"id": "ls", "name": "学技", "type": "learn_skill",
                             "skill": "power_strike", "level": 5})
    ctx = make_ctx(item, eff, skills=SKILLS)
    _use(ctx)
    item2, eff2 = _skill_book({"id": "ls2", "name": "学技", "type": "learn_skill",
                               "skill": "power_strike", "level": 1})
    ctx["items"] = {str(item2["id"]): item2}
    ctx["effect_table"] = {str(eff2["id"]): eff2}
    ctx["equip_engine"] = SimpleNamespace(
        _sorted_inventory=lambda p: [_fake_item("book_x2", "测试技能书")],
        equip_wear=lambda idx, ctx: {"ok": True, "message": "✅"})
    _use(ctx)
    snap = ctx["player"]["persistent_state"]["skill_slots"]
    rows = [r for r in snap["slots"] if r.get("skill_id") == "power_strike"]
    assert len(rows) == 1 and rows[0]["level"] == 5


# ---------------------------------------------------------------------------
# 四、编辑器：新类型可选 / 新字段可见可填
# ---------------------------------------------------------------------------
def _effects_descriptor() -> Dict[str, Any]:
    d = api.entry_detail("veinborn", "effects", "guard_up")
    return {str(f["key"]): f for f in d["fields"]}


def test_editor_effect_type_dropdown_contains_new_types() -> None:
    f = _effects_descriptor()
    t = f["type"]
    assert t["type"] == "str" and t["enum"] == []       # 校验口径不变（开放词汇）
    assert t["control"] == "select"                      # 展示层下拉
    assert "gain_currency" in t["enum_options"]
    assert "learn_skill" in t["enum_options"]
    # 常见既有类型也保留在候选里
    for word in ("damage", "heal", "mark_add"):
        assert word in t["enum_options"]


def test_editor_new_effect_fields_visible_and_editable() -> None:
    f = _effects_descriptor()
    for key in ("currency", "amount_min", "amount_max", "skill", "level"):
        assert key in f, f"effects 元数据缺字段 {key}"
        assert f[key]["present"] is False            # 未配置态也可填（一号原则）
        assert f[key]["editable"] is True
        assert f[key]["help"]                        # 有中文说明
    assert f["currency"]["ref_target"] == "settings.currencies"  # 货币下拉候选来源
    assert f["skill"]["ref_target"] == "skill"                    # 技能下拉候选来源
    assert f["amount_min"]["type"] == "int" and f["amount_max"]["type"] == "int"
    assert f["level"]["type"] == "int"


def test_editor_effects_keys_registered() -> None:
    known = {str(k) for k in default_field_meta_table().module("effects").fields}
    for key in FROZEN_KEYS:
        assert key in known


# ---------------------------------------------------------------------------
# 五、端到端：真写盘 → 使用 → 数值/装配变化 → 回退逐字节复原
# ---------------------------------------------------------------------------
@pytest.fixture()
def temp_root(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    root.mkdir()
    shutil.copytree(CONTENT / "demo_blank", root / "blank")
    shutil.copytree(CONTENT / "test_demo", root / "demo")
    return root


def _ctx_from_pack(pack_dir: Path, item_id: str, rng: Any = None) -> dict:
    def _load(name: str, default: Any) -> Any:
        p = pack_dir / name
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default
    items = {str(e["id"]): e for e in _load("items.json", [])}
    effects = {str(e["id"]): e for e in _load("effects.json", [])}
    skills = {str(e["id"]): e for e in _load("skills.json", [])}
    settings = _load("settings.json", {})
    ctx: Dict[str, Any] = {
        "registered": True,
        "player": {"name": "测试", "level": 1, "job_id": "warrior", "hp": 50,
                   "inventory": [], "equipment": {}, "currencies": {},
                   "persistent_state": {}},
        "items": items, "effect_table": effects, "skills": skills, "settings": settings,
        "equip_engine": SimpleNamespace(
            _sorted_inventory=lambda p: [_fake_item(item_id, str(
                (items.get(item_id) or {}).get("name") or ""))],
            equip_wear=lambda idx, ctx: {"ok": True, "message": "✅"}),
        "inventory_engine": SimpleNamespace(
            remove_item=lambda p, i, count=1, uid="": {"ok": True}),
    }
    if rng is not None:
        ctx["rng"] = rng
    return ctx


def _count_currency(ctx: dict, key: str) -> int:
    return int((ctx["player"].get("currencies") or {}).get(key, 0))


def test_e2e_currency_pouch_write_use_rollback(temp_root: Path) -> None:
    pack_dir = temp_root / "blank"
    items_before = (pack_dir / "items.json").read_bytes()
    effects_before = (pack_dir / "effects.json").read_bytes()
    # ① 造效果 + 货币袋物品（真写盘，走编辑器保存链路）
    e1 = editor_ops.create_entry(
        "blank", "effects", "gain_coins_fixed",
        {"name": "固定金币", "type": "gain_currency", "currency": "coins",
         "amount_min": 120, "amount_max": 120}, root=temp_root)
    assert e1["ok"] is True, e1.get("errors")
    e2 = editor_ops.create_entry(
        "blank", "items", "coin_pouch_test",
        {"name": "测试钱袋", "type": "currency", "usable": True,
         "effects": ["gain_coins_fixed"]}, root=temp_root)
    assert e2["ok"] is True, e2.get("errors")
    written_effect = json.loads((pack_dir / "effects.json").read_text(encoding="utf-8"))[-1]
    assert written_effect["type"] == "gain_currency"
    assert written_effect["amount_min"] == 120 and written_effect["amount_max"] == 120
    # ② 使用 → 货币增加（贴前后数值）
    ctx = _ctx_from_pack(pack_dir, "coin_pouch_test")
    before = _count_currency(ctx, "coins")
    out = _use(ctx)
    after = _count_currency(ctx, "coins")
    assert out and "使用成功" in out
    assert (before, after) == (0, 120), (before, after)
    # ③ 回退复原（逐字节）
    rb1 = editor_ops.rollback_module("blank", "items", root=temp_root)
    rb2 = editor_ops.rollback_module("blank", "effects", root=temp_root)
    assert rb1.get("ok") is True and rb2.get("ok") is True
    assert (pack_dir / "items.json").read_bytes() == items_before
    assert (pack_dir / "effects.json").read_bytes() == effects_before


def test_e2e_skill_book_write_use_rollback(temp_root: Path) -> None:
    pack_dir = temp_root / "demo"
    items_before = (pack_dir / "items.json").read_bytes()
    effects_before = (pack_dir / "effects.json").read_bytes()
    e1 = editor_ops.create_entry(
        "demo", "effects", "learn_strike_3",
        {"name": "学强击", "type": "learn_skill", "skill": "power_strike", "level": 3},
        root=temp_root)
    assert e1["ok"] is True, e1.get("errors")
    e2 = editor_ops.create_entry(
        "demo", "items", "book_strike_test",
        {"name": "测试技能书", "type": "skill_book", "usable": True,
         "effects": ["learn_strike_3"]}, root=temp_root)
    assert e2["ok"] is True, e2.get("errors")
    ctx = _ctx_from_pack(pack_dir, "book_strike_test")
    out = _use(ctx)
    assert "学会技能" in out and "Lv3" in out
    snap = ctx["player"]["persistent_state"]["skill_slots"]
    rows = [r for r in snap["slots"] if r.get("skill_id") == "power_strike"]
    assert len(rows) == 1 and rows[0]["level"] == 3
    _use(ctx)  # 重复使用幂等
    snap2 = ctx["player"]["persistent_state"]["skill_slots"]
    assert len([r for r in snap2["slots"] if r.get("skill_id") == "power_strike"]) == 1
    rb1 = editor_ops.rollback_module("demo", "items", root=temp_root)
    rb2 = editor_ops.rollback_module("demo", "effects", root=temp_root)
    assert rb1.get("ok") is True and rb2.get("ok") is True
    assert (pack_dir / "items.json").read_bytes() == items_before
    assert (pack_dir / "effects.json").read_bytes() == effects_before
