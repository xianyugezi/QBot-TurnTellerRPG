"""编辑器重写批1 · 只读元数据读取层测试。

覆盖任务书要求：模块层级读取 / 字段分组兜底 / 条目列表 / 只读字段类型映射 / 包切换，
外加「编辑器框架不含包业务名」的通用性护栏。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qbot_rpg.web import api

CONTENT = Path(api.repo_root()) / "content"


# ---------------------------------------------------------------------------
# 内容包发现 / 包切换
# ---------------------------------------------------------------------------
def test_list_packs_preferred_default() -> None:
    data = api.list_packs(root=CONTENT, preferred="test_demo")
    ids = [p["id"] for p in data["packs"]]
    assert "veinborn" in ids and "test_demo" in ids
    assert data["default"] == "test_demo"
    assert all(p["module_count"] > 0 and p["name"] for p in data["packs"])


def test_pack_switch_changes_modules_and_entries() -> None:
    v = api.list_modules("veinborn", root=CONTENT)
    t = api.list_modules("test_demo", root=CONTENT)
    vmods = {m["module"] for m in v["modules"]}
    tmods = {m["module"] for m in t["modules"]}
    assert "achievements" in tmods and "achievements" not in vmods
    assert "proficiency" in vmods and "proficiency" in tmods
    ve = api.list_entries("veinborn", "skills", root=CONTENT)
    te = api.list_entries("test_demo", "skills", root=CONTENT)
    assert ve["count"] != te["count"]
    assert {e["id"] for e in ve["entries"]} != {e["id"] for e in te["entries"]}


# ---------------------------------------------------------------------------
# 模块层级（父子）读取
# ---------------------------------------------------------------------------
def test_module_tree_declared_hierarchy() -> None:
    data = api.list_modules("veinborn", root=CONTENT)
    assert data["flat"] is False
    tops = {m["module"]: m for m in data["modules"]}
    assert "items" in tops and "equipment" not in tops  # 子项不并列出现在顶层
    kids = {c["module"]: c for c in tops["items"]["children"]}
    assert "equipment" in kids
    assert kids["equipment"]["label"] == "装备"  # 显示名来自包声明
    assert tops["items"]["count"] == tops["items"]["own_count"] + kids["equipment"]["count"]


def test_module_tree_flat_fallback_when_pack_silent() -> None:
    data = api.list_modules("demo_full", root=CONTENT)
    assert data["flat"] is True
    tops = [m["module"] for m in data["modules"]]
    assert "items" in tops and "equipment" in tops
    assert all(not m["children"] for m in data["modules"])


def test_module_tree_alias_and_label_override(tmp_path: Path) -> None:
    pkg = tmp_path / "pack_x"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "X", "version": "1", "schema_version": 1,
        "modules": ["b", "a"],
        "module_labels": {"a": "甲"},
        "module_groups": {"b": {"label": "乙父", "children": ["a"]}},
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "a.json").write_text("[]", encoding="utf-8")
    (pkg / "b.json").write_text("[]", encoding="utf-8")
    data = api.list_modules("pack_x", root=tmp_path)
    assert data["flat"] is False
    assert [m["module"] for m in data["modules"]] == ["b"]
    assert data["modules"][0]["label"] == "乙父"
    child = data["modules"][0]["children"][0]
    assert child["module"] == "a" and child["label"] == "甲"


def test_module_tree_bad_reference_is_tolerated(tmp_path: Path) -> None:
    pkg = tmp_path / "pack_y"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "Y", "version": "1", "schema_version": 1, "modules": ["a"],
        "module_tree": [{"module": "a", "children": ["ghost", "a"]}],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "a.json").write_text("[]", encoding="utf-8")
    data = api.list_modules("pack_y", root=tmp_path)
    assert [m["module"] for m in data["modules"]] == ["a"]
    assert data["notes"]  # 未声明模块/自环被记录，而不是崩


# ---------------------------------------------------------------------------
# 字段分组（声明 + 兜底）
# ---------------------------------------------------------------------------
def test_skills_groups_declared_in_metadata() -> None:
    meta = api.field_meta_table().module("skills")
    assert meta is not None
    assert meta.group_order == ("基本", "数值", "效果列表", "文本")
    assert meta.field_groups["effects"] == "效果列表"
    assert meta.field_groups["brief"] == "文本"


def test_skills_entry_yields_four_groups() -> None:
    d = api.entry_detail("veinborn", "skills", "rb_slash", root=CONTENT)
    assert [g["name"] for g in d["groups"]] == ["基本", "数值", "效果列表", "文本"]
    assert d["group_count"] == 4
    assert sum(g["count"] for g in d["groups"]) == d["field_count"]
    # 未登记字段（真实内容里有、fields 表里没有）仍按模块分组表落进「文本」
    brief = next(f for f in d["fields"] if f["key"] == "brief")
    assert brief["group"] == "文本" and brief["present"] is True


def test_group_default_fallback_for_module_without_declaration() -> None:
    meta = api.field_meta_table().module("effects")
    assert meta is not None and not meta.field_groups
    d = api.entry_detail("veinborn", "effects", "guard_up", root=CONTENT)
    assert d["group_count"] == 1
    assert d["groups"][0]["name"] == api.DEFAULT_GROUP


def test_group_resolution_priority_per_field_then_module_then_default() -> None:
    meta = api.field_meta_table().module("skills")
    assert meta is not None
    # 模块分组表覆盖未登记键 → 不落兜底组
    assert api._resolve_group("brief", None, meta) == "文本"
    # 模块无声明 → 兜底组
    assert api._resolve_group("whatever", None, api.field_meta_table().module("effects")) \
        == api.DEFAULT_GROUP


# ---------------------------------------------------------------------------
# 条目列表（id + 名称）
# ---------------------------------------------------------------------------
def test_entry_list_ids_and_names() -> None:
    data = api.list_entries("veinborn", "items", root=CONTENT)
    assert data["entry_type"] == "list"
    assert data["count"] == len(data["entries"]) > 0
    assert set(data["entries"][0]) == {"id", "name"}
    first = data["entries"][0]
    detail = api.entry_detail("veinborn", "items", first["id"], root=CONTENT)
    assert detail["id"] == first["id"] and detail["name"] == first["name"]


def test_entry_list_object_module_uses_metadata_labels() -> None:
    data = api.list_entries("veinborn", "settings", root=CONTENT)
    assert data["entry_type"] == "object"
    by_id = {e["id"]: e["name"] for e in data["entries"]}
    assert by_id["default_map"] == "默认地图"  # 段名来自字段元数据 label


def test_entry_list_map_module_keys_are_entries() -> None:
    data = api.list_entries("veinborn", "stats", root=CONTENT)
    assert data["entry_type"] == "map"
    ids = {e["id"] for e in data["entries"]}
    assert {"hp", "mp", "atk", "dfn"} <= ids
    detail = api.entry_detail("veinborn", "stats", "hp", root=CONTENT)
    assert detail["name"] == "生命" and detail["field_count"] > 0


# ---------------------------------------------------------------------------
# 字段类型 → 只读形态
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("ftype,widget", [
    ("str", "text"), ("text", "text"),
    ("int", "number"), ("float", "number"), ("number", "number"),
    ("bool", "bool"), ("enum", "enum"), ("ref", "ref"),
    ("list", "list"), ("obj", "obj"), ("map", "map"), ("formula", "formula"),
    ("unknown_type", "text"),
])
def test_readonly_form_mapping(ftype: str, widget: str) -> None:
    assert api.readonly_form(ftype) == widget


def test_real_entries_cover_readonly_forms() -> None:
    cases = [
        ("items", "pulse_potion", "name", "text"),
        ("items", "pulse_potion", "price", "number"),
        ("skills", "rb_slash", "armor", "bool"),
        ("marks", "surge_mark", "polarity", "enum"),
        ("effects", "guard_up", "require_status", "ref"),
        ("items", "barrow_core", "elements", "obj"),
    ]
    for mod, eid, key, widget in cases:
        d = api.entry_detail("veinborn", mod, eid, root=CONTENT)
        f = next(x for x in d["fields"] if x["key"] == key)
        assert f["widget"] == widget, f"{mod}/{eid}.{key} → {f['widget']}"
    formula = api.entry_detail("veinborn", "formula", "damage_base", root=CONTENT)
    assert formula["fields"][0]["widget"] == "formula"


def test_list_field_is_readonly_table_with_resolved_refs() -> None:
    d = api.entry_detail("veinborn", "items", "pulse_potion", root=CONTENT)
    f = next(x for x in d["fields"] if x["key"] == "effects")
    assert f["widget"] == "list"
    assert f["columns"][0]["widget"] == "ref"
    assert f["row_count"] == len(f["value"]) == 1
    assert f["rows"][0]["value"].endswith("（heal_small）")  # 引用显示目标名称


def test_unregistered_keys_are_inferred_not_dropped(tmp_path: Path) -> None:
    pkg = tmp_path / "pack_z"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "Z", "version": "1", "schema_version": 1, "modules": ["loose"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "loose.json").write_text(json.dumps(
        [{"id": "x", "label": "X", "n": 3, "on": True, "kids": [{"a": 1}], "deep": {"k": "v"}}],
        ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_z", "loose", "x", root=tmp_path)
    widgets = {f["key"]: f["widget"] for f in d["fields"]}
    assert widgets["label"] == "text" and widgets["n"] == "number"
    assert widgets["on"] == "bool" and widgets["kids"] == "list"
    assert widgets["deep"] == "map"
    assert d["group_count"] == 1


# ---------------------------------------------------------------------------
# 错误与路径安全
# ---------------------------------------------------------------------------
def test_errors_and_path_safety() -> None:
    with pytest.raises(api.NotFound):
        api.list_modules("no_such_pack", root=CONTENT)
    with pytest.raises(api.BadRequest):
        api.list_modules("../etc", root=CONTENT)
    with pytest.raises(api.NotFound):
        api.list_entries("veinborn", "not_a_module", root=CONTENT)
    with pytest.raises(api.NotFound):
        api.entry_detail("veinborn", "skills", "no_such_entry", root=CONTENT)


# ---------------------------------------------------------------------------
# 通用性护栏：编辑器框架不得写死任何内容包的模块名 / 业务字段名
# ---------------------------------------------------------------------------
def test_editor_framework_has_no_pack_business_names() -> None:
    root = Path(api.repo_root())
    targets = [
        root / "qbot_rpg" / "web" / "api.py",
        root / "qbot_rpg" / "web" / "__init__.py",
        root / "qbot_rpg" / "web" / "static" / "index.html",
        root / "scripts" / "editor_host.py",
    ]
    banned = ["veinborn", "test_demo", "equipment", "技能", "物品", "装备", "怪物", "职业"]
    for path in targets:
        text = path.read_text(encoding="utf-8")
        for word in banned:
            assert word not in text, f"{path} 写死了包业务名：{word}"


def test_frontend_is_single_file_zero_cdn() -> None:
    html = (Path(api.repo_root()) / "qbot_rpg" / "web" / "static" / "index.html") \
        .read_text(encoding="utf-8")
    assert "http://" not in html and "https://" not in html
    assert "<script src=" not in html and "@import url(" not in html  # 无外部脚本/样式
    assert "tokens.css" in html  # 本地引用样式令牌


def test_manifest_optional_keys_do_not_break_loader() -> None:
    from qbot_rpg.content.loader import build_pack

    for pack in ("veinborn", "test_demo"):
        built, _changed = build_pack(CONTENT / pack, api.field_meta_table(), None, 1)
        assert built.report.ok
