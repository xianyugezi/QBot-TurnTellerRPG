"""批22 · A1/A2：物品/装备「职业限制 job_restrict」与「使用等级 use_level」。

覆盖（§三 A1/A2 + §六 自证 1）：
  - 元数据登记（items + equipment，含 element ref_target="job"）+ 编辑器接口可见；
  - 校验：引用缺失 → 红（泛型 R-4）；use_level 非法值口径（非整数红 / 负数红 / 0 黄）；
  - 引擎消费：不满足职业/等级 → 被阻止（贴提示原文）；满足 → 正常穿戴；
  - 回归：不带新字段时穿戴行为逐字段一致。

测试只建临时内容根 / 临时包，绝不写真实内容包。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from qbot_rpg.commands.basic_commands import EquipmentEngineAdapter
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.validator import check_pack
from qbot_rpg.data.item import ItemInstance
from qbot_rpg.data.player import PlayerAttributes
from qbot_rpg.web import api


# ---------------------------------------------------------------------------
# 公共构造
# ---------------------------------------------------------------------------
def _item_row(item_id: str, name: str, slot: str) -> ItemInstance:
    return ItemInstance(item_id=item_id, name=name, count=1, quality="normal",
                        bound=False, slot=slot)


def _ctx(inventory, items, *, job_id: str, level: int = 1, slots=None):
    player = {
        "inventory": list(inventory),
        "equipment": {},
        "attributes": PlayerAttributes(base={"hp": 100.0, "mp": 30.0, "str": 15.0, "con": 10.0}),
        "in_battle": False,
        "job_id": job_id,
        "level": level,
    }
    engine = EquipmentEngineAdapter(slots=slots or {"weapon": {"name": "武器", "max": 1}})
    return {"player": player, "items": dict(items), "job_id": job_id, "level": level,
            "equip_engine": engine}


def _temp_pack(tmp_path: Path, pack_id: str, modules: Mapping[str, Any]) -> Path:
    root = tmp_path / pack_id
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps(
        {"name": pack_id, "version": "1", "schema_version": 1, "modules": list(modules)},
        ensure_ascii=False), encoding="utf-8")
    for name, data in modules.items():
        (root / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return root


# ---------------------------------------------------------------------------
# A1 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a1_metadata_registered_items_and_equipment() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("job_restrict")
        assert fm is not None, f"{mod} 缺 job_restrict 登记"
        assert fm.type == "list"
        assert fm.element is not None and fm.element.type == "ref"
        assert fm.element.ref_target == "job"      # 引用注册表 kind（jobs L2322 kind="job"）
        assert fm.label, f"{mod}.job_restrict 缺中文名"
        assert tbl.module(mod).field_groups.get("job_restrict") == "base"


def test_a1_editor_visible(tmp_path: Path) -> None:
    _temp_pack(tmp_path, "pack_a1", {
        "equipment": [{"id": "sword", "name": "剑", "slot": "weapon",
                       "job_restrict": ["warrior"]}],
    })
    detail = api.entry_detail("pack_a1", "equipment", "sword", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "job_restrict")
    assert f["present"] is True
    assert f["type"] == "list"
    assert f["label"] == "职业限制"


# ---------------------------------------------------------------------------
# A1 校验：引用目标 ∈ jobs（缺失 → 红 R-4）
# ---------------------------------------------------------------------------
def test_a1_validator_missing_job_red() -> None:
    report = check_pack({
        "jobs": [{"id": "warrior", "name": "战士"}],
        "equipment": [{"id": "sword", "name": "剑", "slot": "weapon",
                       "job_restrict": ["ghost_job"]}],
    })
    hits = [e for e in report.errors if e.kind == "R-4" and "job_restrict" in e.field]
    assert hits, [e for e in report.errors]
    assert hits[0].detail.get("ref") == "ghost_job"
    assert hits[0].detail.get("ref_target") == "job"


def test_a1_validator_known_job_ok() -> None:
    report = check_pack({
        "jobs": [{"id": "warrior", "name": "战士"}],
        "equipment": [{"id": "sword", "name": "剑", "slot": "weapon",
                       "job_restrict": ["warrior"]}],
    })
    assert not [e for e in report.errors if "job_restrict" in e.field]


# ---------------------------------------------------------------------------
# A1 引擎消费：不满足 → 阻止；满足 → 正常穿戴（修前/修后对照）
# ---------------------------------------------------------------------------
DEFS = {"sword": {"id": "sword", "name": "剑", "slot": "weapon", "job_restrict": ["warrior"]}}


def test_a1_engine_blocks_other_job() -> None:
    """修前：无门禁 → 穿成功；修后：职业不符 → 被阻止（贴提示原文）。"""
    ctx = _ctx([_item_row("sword", "剑", "weapon")], DEFS, job_id="mage")
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is False
    assert r["message"] == "❌ 职业不符：需要 warrior，当前 mage"
    assert ctx["player"]["equipment"] == {}  # 未穿上


def test_a1_engine_allows_matching_job() -> None:
    ctx = _ctx([_item_row("sword", "剑", "weapon")], DEFS, job_id="warrior")
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is True
    assert ctx["player"]["equipment"]["weapon"].item_id == "sword"


def test_a1_regression_no_field_behaves_identically() -> None:
    """回归：物品不带 job_restrict → 任何职业均可穿戴（与既有逐字段一致）。"""
    generic = {"sword": {"id": "sword", "name": "剑", "slot": "weapon"}}
    for job in ("mage", "warrior", ""):
        ctx = _ctx([_item_row("sword", "剑", "weapon")], generic, job_id=job)
        r = ctx["equip_engine"].equip_wear(1, ctx)
        assert r["ok"] is True, (job, r)


# ---------------------------------------------------------------------------
# A1 端到端：临时内容根建包 → 校验 + 编辑器 + 引擎
# ---------------------------------------------------------------------------
def test_a1_e2e_temp_content_root(tmp_path: Path) -> None:
    root = _temp_pack(tmp_path, "pack_e2e_a1", {
        "jobs": [{"id": "warrior", "name": "战士"}],
        "equipment": [{"id": "axe", "name": "战斧", "slot": "weapon",
                       "job_restrict": ["warrior"]}],
    })
    from qbot_rpg.content.loader import build_pack

    pack, _changed = build_pack(root)          # 合法包：不抛
    assert pack is not None
    # 非法引用 → 红拦（PackLoadError）
    _temp_pack(tmp_path, "pack_e2e_a1_bad", {
        "jobs": [{"id": "warrior", "name": "战士"}],
        "equipment": [{"id": "axe", "name": "战斧", "slot": "weapon",
                       "job_restrict": ["ghost"]}],
    })
    from qbot_rpg.content.loader import PackLoadError

    try:
        build_pack(tmp_path / "pack_e2e_a1_bad")
    except PackLoadError:
        pass
    else:  # pragma: no cover
        raise AssertionError("非法职业引用必须红拦")


# ---------------------------------------------------------------------------
# A2 元数据登记 + 编辑器可见
# ---------------------------------------------------------------------------
def test_a2_metadata_registered_items_and_equipment() -> None:
    tbl = default_field_meta_table()
    for mod in ("items", "equipment"):
        fm = tbl.module(mod).fields.get("use_level")
        assert fm is not None, f"{mod} 缺 use_level 登记"
        assert fm.type == "int"
        assert fm.range_min == 1 and fm.range_max == 999
        assert fm.label and fm.unit == "级"
        assert tbl.module(mod).field_groups.get("use_level") == "base"


def test_a2_editor_visible(tmp_path: Path) -> None:
    _temp_pack(tmp_path, "pack_a2", {
        "equipment": [{"id": "sword", "name": "剑", "slot": "weapon", "use_level": 10}],
    })
    detail = api.entry_detail("pack_a2", "equipment", "sword", root=tmp_path)
    f = next(x for x in detail["fields"] if x["key"] == "use_level")
    assert f["present"] is True and f["type"] == "int"


# ---------------------------------------------------------------------------
# A2 校验：非法值口径（0/负数 → 红；缺失/合法 → 无）
# ---------------------------------------------------------------------------
def test_a2_validator_zero_hard_red() -> None:
    report = check_pack({"equipment": [{"id": "s", "name": "剑", "use_level": 0}]})
    hits = [e for e in report.errors if e.kind == "IV-1" and "use_level" in e.field]
    assert hits and hits[0].detail.get("minimum") == 1


def test_a2_validator_negative_red() -> None:
    report = check_pack({"equipment": [{"id": "s", "name": "剑", "use_level": -3}]})
    assert [e for e in report.errors if e.kind == "IV-1"]      # 专项
    assert [e for e in report.errors if e.kind == "R-2"]       # 泛型负数（双红，门禁更严）


def test_a2_validator_valid_and_missing_ok() -> None:
    report = check_pack({"equipment": [
        {"id": "s", "name": "剑", "use_level": 5},
        {"id": "t", "name": "盾"},
    ]})
    assert not [e for e in report.errors if "use_level" in e.field]


def test_a2_validator_non_int_red_via_generic() -> None:
    report = check_pack({"equipment": [{"id": "s", "name": "剑", "use_level": "10"}]})
    assert [e for e in report.errors if e.kind == "R-1" and "use_level" in e.field]
    assert not [e for e in report.errors if e.kind == "IV-1"]  # 不重复报


# ---------------------------------------------------------------------------
# A2 引擎消费：等级不足 → 阻止（贴提示原文）；达标 → 正常穿戴
# ---------------------------------------------------------------------------
def test_a2_engine_blocks_low_level() -> None:
    defs = {"sword": {"id": "sword", "name": "剑", "slot": "weapon", "use_level": 5}}
    ctx = _ctx([_item_row("sword", "剑", "weapon")], defs, job_id="warrior", level=3)
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is False
    assert r["message"] == "❌ 等级不足：需要 5 级，当前 3 级"
    assert ctx["player"]["equipment"] == {}


def test_a2_engine_allows_enough_level() -> None:
    defs = {"sword": {"id": "sword", "name": "剑", "slot": "weapon", "use_level": 5}}
    ctx = _ctx([_item_row("sword", "剑", "weapon")], defs, job_id="warrior", level=5)
    r = ctx["equip_engine"].equip_wear(1, ctx)
    assert r["ok"] is True and ctx["player"]["equipment"]["weapon"].item_id == "sword"


def test_a2_two_judgements_independent() -> None:
    """A1 与 A2 两条独立判定：职业命中但等级不足 → 报等级；两者都不满足 → 先报职业。"""
    defs = {"sword": {"id": "sword", "name": "剑", "slot": "weapon",
                      "job_restrict": ["warrior"], "use_level": 5}}
    c1 = _ctx([_item_row("sword", "剑", "weapon")], defs, job_id="warrior", level=1)
    assert c1["equip_engine"].equip_wear(1, c1)["message"] == "❌ 等级不足：需要 5 级，当前 1 级"
    c2 = _ctx([_item_row("sword", "剑", "weapon")], defs, job_id="mage", level=1)
    assert c2["equip_engine"].equip_wear(1, c2)["message"] == "❌ 职业不符：需要 warrior，当前 mage"


def test_a2_regression_no_field_behaves_identically() -> None:
    generic = {"sword": {"id": "sword", "name": "剑", "slot": "weapon"}}
    for lv in (1, 10, 99):
        ctx = _ctx([_item_row("sword", "剑", "weapon")], generic, job_id="warrior", level=lv)
        assert ctx["equip_engine"].equip_wear(1, ctx)["ok"] is True
