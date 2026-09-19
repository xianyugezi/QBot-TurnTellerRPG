"""批34 · 通用 CSV 编解码纯函数（`qbot_rpg/content/csv_codec.py`）。

覆盖：列头 = 元数据字段（中文名/键，未配置也出）· 列表/对象字段 JSON 编码可逆 ·
null / 空串 / 反斜杠 / 数字 / 布尔 · UTF-8 BOM · 公式注入中和可逆 · map 模块 ·
object 模块如实不支持 · 行号与认不出的列。

纯函数层：不读盘、不写内容包。
"""

from __future__ import annotations


import pytest

from qbot_rpg.content import csv_codec as cc
from qbot_rpg.content.models import FieldMeta, ModuleMeta

# 通用模块元数据（不写死任何真实内容包模块/字段）
LIST_META = ModuleMeta(entry_type="list", id_field="id", kind="widget", fields={
    "id": FieldMeta(type="str", required=True, label="标识"),
    "name": FieldMeta(type="str", label="名称"),
    "price": FieldMeta(type="number", label="价格"),
    "count": FieldMeta(type="int", label="数量"),
    "enabled": FieldMeta(type="bool", label="启用"),
    "tags": FieldMeta(type="list", element=FieldMeta(type="str"), label="标签"),
    "size": FieldMeta(type="obj", children={
        "w": FieldMeta(type="number", label="宽"),
        "h": FieldMeta(type="number", label="高"),
    }, label="尺寸"),
    "effect": FieldMeta(type="ref", ref_target="effect", label="效果"),
    "note": FieldMeta(type="str", label="备注"),
})

MAP_META = ModuleMeta(entry_type="map", id_field="id", kind="thing", value_meta=FieldMeta(
    type="obj", children={
        "name": FieldMeta(type="str", label="名称"),
        "base": FieldMeta(type="number", label="基础"),
    }))

SCALAR_MAP_META = ModuleMeta(entry_type="map", id_field="id",
                             value_meta=FieldMeta(type="str", label="文案"))

OBJECT_META = ModuleMeta(entry_type="object", fields={"a": FieldMeta(type="str")})


def _entries():
    return [
        ("w1", {"id": "w1", "name": "甲", "price": 1.5, "count": 3,
                "enabled": True, "tags": ["a", "b"],
                "size": {"w": 1, "h": 2}, "effect": "e1"}),
        ("w2", {"id": "w2", "name": "", "price": 0, "tags": [],
                "size": None, "note": None}),
    ]


# =====================================================================================
# 列头
# =====================================================================================
def test_header_is_metadata_fields_with_label_and_key() -> None:
    schema = cc.schema_for(LIST_META)
    header = schema.header_cells()
    assert header[0] == "标识(id)"
    assert "名称(name)" in header
    assert "价格(price)" in header
    # 一号原则：未配置的字段也出列
    assert "备注(note)" in header and "效果(effect)" in header
    assert header == [f"{c.label}({c.key})" if c.label and c.label != c.key else c.key
                      for c in schema.columns]


def test_header_extra_keys_use_star_prefix() -> None:
    schema = cc.schema_for(LIST_META, extra_keys=["excludes"])
    header = schema.header_cells()
    assert "*excludes" in header
    assert schema.column("excludes") is not None
    assert schema.column("excludes").json is True


def test_map_schema_key_column_and_value_children() -> None:
    schema = cc.schema_for(MAP_META)
    assert schema.value_mode == "map_obj"
    assert schema.columns[0].key == "id" and schema.columns[0].is_key
    assert [c.key for c in schema.columns] == ["id", "name", "base"]


def test_scalar_map_schema() -> None:
    schema = cc.schema_for(SCALAR_MAP_META)
    assert schema.value_mode == "map_scalar"
    assert [c.key for c in schema.columns] == ["id", "value"]


def test_object_module_is_reported_unsupported() -> None:
    with pytest.raises(cc.UnsupportedModuleError):
        cc.schema_for(OBJECT_META)


# =====================================================================================
# 往返
# =====================================================================================
def _roundtrip(schema, entries):
    text = cc.encode_csv(schema, entries)
    res = cc.decode_csv(schema, text)
    assert res.issues == []
    return text, res


def test_roundtrip_scalars_lists_objects_nulls() -> None:
    schema = cc.schema_for(LIST_META)
    entries = _entries()
    _text, res = _roundtrip(schema, entries)
    got = [(r.key, r.entry(schema)) for r in res.rows]
    assert got == entries
    # 空串保真（不被当成缺失）
    assert res.rows[1].values.get("name") == ""


def test_null_sentinel_and_literal_backslash_are_distinct() -> None:
    schema = cc.schema_for(LIST_META)
    entries = [
        ("a", {"id": "a", "note": None}),
        ("b", {"id": "b", "note": "\\N"}),
        ("c", {"id": "c", "note": "\\"}),
        ("d", {"id": "d", "note": ""}),
        ("e", {"id": "e", "note": "\\E"}),
    ]
    text, res = _roundtrip(schema, entries)
    got = [(r.key, r.entry(schema)) for r in res.rows]
    assert got == entries
    assert "\\N" in text and "\\E" in text


def test_utf8_bom_and_uniform_line_ending() -> None:
    schema = cc.schema_for(LIST_META)
    text = cc.encode_csv(schema, _entries())
    assert text.startswith(cc.CSV_BOM)
    assert "\r" not in text
    assert text.endswith("\n")


def test_json_encoding_for_list_and_obj() -> None:
    schema = cc.schema_for(LIST_META)
    text = cc.encode_csv(schema, [("w1", {"id": "w1", "tags": ["a", "b"],
                                          "size": {"w": 1, "h": 2}})])
    # csv 会按需加引号（双引号翻倍）；内容是本批文档化的 JSON 文本
    assert '""a"",""b""' in text
    assert '{""w"":1,""h"":2}' in text


def test_extra_column_roundtrip_json() -> None:
    schema = cc.schema_for(LIST_META, extra_keys=["excludes"])
    entries = [("w1", {"id": "w1", "excludes": ["x", 1, {"k": None}]})]
    _text, res = _roundtrip(schema, entries)
    assert res.rows[0].values["excludes"] == ["x", 1, {"k": None}]


def test_map_module_roundtrip() -> None:
    schema = cc.schema_for(MAP_META)
    entries = [("s1", {"name": "力", "base": 10}), ("s2", {"name": "敏", "base": 12})]
    text = cc.encode_csv(schema, entries)
    res = cc.decode_csv(schema, text)
    assert res.issues == []
    assert [(r.key, r.entry(schema)) for r in res.rows] == entries


def test_scalar_map_roundtrip() -> None:
    schema = cc.schema_for(SCALAR_MAP_META)
    entries = [("k1", "文案一"), ("k2", "=danger")]
    text = cc.encode_csv(schema, entries)
    res = cc.decode_csv(schema, text)
    assert [(r.key, r.entry(schema)) for r in res.rows] == entries


# =====================================================================================
# 公式注入中和（§6.12-20）
# =====================================================================================
@pytest.mark.parametrize("danger", ["=cmd|' /C calc'!A0", "+1+1", "-2", "@SUM(A1)"])
def test_export_neutralizes_dangerous_text(danger: str) -> None:
    schema = cc.schema_for(LIST_META)
    text = cc.encode_csv(schema, [("w1", {"id": "w1", "note": danger})])
    assert "'" + danger in text
    res = cc.decode_csv(schema, text)
    assert res.rows[0].values["note"] == danger  # 往返仍还原原文


def test_export_does_not_touch_numeric_negative() -> None:
    schema = cc.schema_for(LIST_META)
    text = cc.encode_csv(schema, [("w1", {"id": "w1", "count": -2, "price": -1.5})])
    assert "'-2" not in text
    res = cc.decode_csv(schema, text)
    assert res.rows[0].values["count"] == -2
    assert res.rows[0].values["price"] == -1.5


def test_import_neutralizes_raw_dangerous_text() -> None:
    """裸危险文本（不是我们导出的）→ 写入前中和为 `'` 前缀。"""
    schema = cc.schema_for(LIST_META)
    text = "标识(id),备注(note)\nw1,=cmd|calc\n"
    res = cc.decode_csv(schema, text)
    assert res.rows[0].values["note"] == "'=cmd|calc"


def test_import_undoes_our_own_neutralization() -> None:
    schema = cc.schema_for(LIST_META)
    text = "标识(id),备注(note)\nw1,'=cmd\n"
    res = cc.decode_csv(schema, text)
    assert res.rows[0].values["note"] == "=cmd"


def test_apostrophe_prefixed_text_is_stable() -> None:
    """内容本来就是 `'=x`（含前导单引号）也要可逆。"""
    schema = cc.schema_for(LIST_META)
    entries = [("w1", {"id": "w1", "note": "'=x"}), ("w2", {"id": "w2", "note": "''=x"})]
    text, res = _roundtrip(schema, entries)
    assert [(r.key, r.entry(schema)) for r in res.rows] == entries


# =====================================================================================
# 行号 / 认不出的列 / 单元格报错
# =====================================================================================
def test_line_numbers_start_at_two_for_first_data_row() -> None:
    schema = cc.schema_for(LIST_META)
    text = ("标识(id),名称(name)\n"
            "w1,甲\n"
            "\n"            # 空白行：跳过但占行号
            "w2,乙\n")
    res = cc.decode_csv(schema, text)
    assert [r.line for r in res.rows] == [2, 4]


def test_unknown_column_ignored_with_note() -> None:
    schema = cc.schema_for(LIST_META)
    text = "标识(id),不存在的列\nw1,hello\n"
    res = cc.decode_csv(schema, text)
    assert res.rows[0].values == {"id": "w1"}
    assert res.notes and "忽略" in res.notes[0]


def test_bad_number_is_row_issue_not_exception() -> None:
    schema = cc.schema_for(LIST_META)
    text = "标识(id),价格(price)\nw1,abc\n"
    res = cc.decode_csv(schema, text)
    assert len(res.issues) == 1 and res.issues[0].line == 2
    assert res.issues[0].field == "price"
    assert "price" not in res.rows[0].values


def test_empty_csv_raises_human_error() -> None:
    schema = cc.schema_for(LIST_META)
    with pytest.raises(cc.CsvCodecError):
        cc.decode_csv(schema, "")


def test_json_cell_parse_failure_is_row_issue() -> None:
    schema = cc.schema_for(LIST_META)
    text = '标识(id),标签(tags)\nw1,"{not json}"\n'
    res = cc.decode_csv(schema, text)
    assert res.issues and res.issues[0].field == "tags"


def test_declared_type_mismatch_is_preserved() -> None:
    """真实内容包存在「声明类型 ≠ 实际取值」（如 bool 字段写对象）——必须可逆保真。"""
    schema = cc.schema_for(LIST_META)
    entries = [
        ("m1", {"id": "m1", "enabled": {"output": "x", "count": 2}}),   # bool 列里存对象
        ("m2", {"id": "m2", "note": {"nested": [1, 2]}}),               # str 列里存对象
        ("m3", {"id": "m3", "count": "12"}),                            # int 列里存字符串
    ]
    text, res = _roundtrip(schema, entries)
    assert [(r.key, r.entry(schema)) for r in res.rows] == entries
    assert cc.CELL_JSON_MARK in text   # 文本列的类型不符走标记


def test_no_business_names_hardcoded() -> None:
    """通用性护栏：编解码文件不得出现任何真实内容包业务模块/字段名。"""
    import inspect
    src = inspect.getsource(cc)
    for banned in ("veinborn", "test_demo"):
        assert banned not in src
