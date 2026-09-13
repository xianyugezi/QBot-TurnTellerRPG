"""编辑器重写批2 · 控件映射测试（全类型覆盖 + 集中一处 + 通用性护栏）。

覆盖任务书「可编辑控件：按 FieldMeta.type 渲染编辑控件」与不变量「映射集中一处」：
  · str/int/float/number/bool/enum/ref → 可编辑控件；list/obj/map → 本批只读；
  · multiline 声明/长文本启发式 → textarea；
  · 描述符（entry_detail）逐字段携带 control/editable（前端只认 control）；
  · editor_ops.py 等编辑器代码不得出现任何内容包业务名（换包零改动）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api

CONTENT = Path(api.repo_root()) / "content"

# FieldMeta.type → 期望编辑控件（唯一映射的口径断言）
EXPECTED_CONTROL = {
    "str": "text",
    "text": "text",
    "int": "number",
    "float": "number",
    "number": "number",
    "bool": "bool",
    "enum": "select",
    "ref": "ref",
    "list": "readonly",
    "obj": "readonly",
    "map": "readonly",
    "formula": "text",
}


def test_all_types_map_to_control_and_editability() -> None:
    for ftype, control in EXPECTED_CONTROL.items():
        form = api.editable_form(ftype)
        assert form["control"] == control, ftype
        assert form["editable"] is (control != "readonly"), ftype


def test_multiline_only_affects_text() -> None:
    assert api.control_of("text", multiline=True) == "textarea"
    assert api.editable_form("str", multiline=True)["control"] == "textarea"
    # 非文本形态不接受 multiline 影响
    assert api.control_of("number", multiline=True) == "number"
    assert api.control_of("list", multiline=True) == "readonly"


def test_unknown_type_falls_back_to_text() -> None:
    assert api.editable_form("no_such_type")["control"] == "text"
    assert api.readonly_form(None) == "text"


def test_readonly_form_unchanged_from_batch1() -> None:
    """批1 只读映射保持兼容（既有测试依赖）。"""
    assert api.readonly_form("str") == "text"
    assert api.readonly_form("ref") == "ref"
    assert api.readonly_form("list") == "list"
    assert api.readonly_form("obj") == "obj"
    assert api.readonly_form("map") == "map"


def _widgets_table() -> FieldMetaTable:
    return FieldMetaTable(modules={
        "widgets": ModuleMeta(entry_type="list", fields={
            "s": FieldMeta(type="str", label="文本"),
            "n": FieldMeta(type="int", label="数字"),
            "f": FieldMeta(type="float", label="小数字"),
            "b": FieldMeta(type="bool", label="开关"),
            "e": FieldMeta(type="enum", enum=("x", "y"), label="类别"),
            "r": FieldMeta(type="ref", ref_target="widgets", label="归属"),
            "l": FieldMeta(type="list", label="列表"),
            "o": FieldMeta(type="obj", children={"k": FieldMeta(type="str")}, label="对象"),
            "m": FieldMeta(type="map", label="映射"),
            "t": FieldMeta(type="str", multiline=True, label="长文本"),
        }),
    })


@pytest.fixture()
def widgets_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pkg = tmp_path / "pack_w"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "W", "version": "1", "schema_version": 1, "modules": ["widgets"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "widgets.json").write_text(json.dumps([{
        "id": "a", "name": "甲", "s": "v", "n": 1, "f": 1.5, "b": True, "e": "x",
        "r": "a", "l": [{"x": 1}], "o": {"k": "v"}, "m": {"k": "v"},
        "t": "很长的文本" * 30,
    }], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(api, "_META_TABLE", _widgets_table())
    return tmp_path


def test_entry_detail_control_per_field(widgets_pack: Path) -> None:
    d = api.entry_detail("pack_w", "widgets", "a", root=widgets_pack)
    controls = {f["key"]: f["control"] for f in d["fields"]}
    assert controls["s"] == "text"
    assert controls["n"] == "number" and controls["f"] == "number"
    assert controls["b"] == "bool"
    assert controls["e"] == "select"
    assert controls["r"] == "ref"
    assert controls["l"] == "readonly" and controls["o"] == "readonly"
    assert controls["m"] == "readonly"
    assert controls["t"] == "textarea"  # 元数据 multiline 声明


def test_entry_detail_editable_flag_and_ref_target(widgets_pack: Path) -> None:
    d = api.entry_detail("pack_w", "widgets", "a", root=widgets_pack)
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["s"]["editable"] is True and by_key["e"]["editable"] is True
    assert by_key["l"]["editable"] is False
    assert by_key["r"]["ref_target"] == "widgets"
    assert by_key["e"]["enum"] == ["x", "y"]


def test_real_pack_declared_multiline_renders_textarea() -> None:
    """真实内容包中「详情」类字段由元数据声明 multiline → 编辑控件 textarea（非启发式）。"""
    meta = api.field_meta_table().module("skills")
    detail_meta = meta.fields["detail"]
    assert detail_meta.multiline is True
    eid = api.list_entries("test_demo", "skills", root=CONTENT)["entries"][0]["id"]
    d = api.entry_detail("test_demo", "skills", eid, root=CONTENT)
    field = next(f for f in d["fields"] if f["key"] == "detail")
    assert field["control"] == "textarea" and field["editable"] is True


def test_long_text_heuristic_gives_textarea(tmp_path: Path) -> None:
    pkg = tmp_path / "pack_h"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "H", "version": "1", "schema_version": 1, "modules": ["loose"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "loose.json").write_text(json.dumps([
        {"id": "x", "note": "一" * 120, "short": "ok"},
    ], ensure_ascii=False), encoding="utf-8")
    d = api.entry_detail("pack_h", "loose", "x", root=tmp_path)
    by_key = {f["key"]: f for f in d["fields"]}
    assert by_key["note"]["control"] == "textarea"  # 长文本启发式兜底
    assert by_key["short"]["control"] == "text"


def test_ref_options_carry_display_names(widgets_pack: Path) -> None:
    out = api.ref_options("pack_w", "widgets", root=widgets_pack)
    assert out["known"] is True
    assert {o["id"] for o in out["options"]} == {"a"}
    assert out["options"][0]["name"] == "甲"


def test_ref_options_unknown_target_marks_unknown(widgets_pack: Path) -> None:
    out = api.ref_options("pack_w", "no_such_kind", root=widgets_pack)
    assert out["known"] is False and out["options"] == []


# ---------------------------------------------------------------------------
# 通用性护栏：编辑器写入层不得写死任何内容包的模块名 / 业务字段名
# ---------------------------------------------------------------------------
def test_editor_ops_has_no_pack_business_names() -> None:
    root = Path(api.repo_root())
    path = root / "qbot_rpg" / "web" / "editor_ops.py"
    banned = ["veinborn", "test_demo", "equipment", "技能", "物品", "装备", "怪物", "职业"]
    text = path.read_text(encoding="utf-8")
    for word in banned:
        assert word not in text, f"{path} 写死了包业务名：{word}"


def test_widget_mapping_is_single_point() -> None:
    """类型→控件映射只在 api.py 集中实现；前端按后端 control 渲染，不复制类型表。"""
    root = Path(api.repo_root())
    html = (root / "qbot_rpg" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "switch (f.control)" in html  # 前端只认 control
    for control in ("text", "textarea", "number", "bool", "select", "ref"):
        assert 'case "%s"' % control in html, control
    ops = (root / "qbot_rpg" / "web" / "editor_ops.py").read_text(encoding="utf-8")
    assert "_EDIT_BY_WIDGET" not in ops and "_WIDGET_BY_TYPE" not in ops
