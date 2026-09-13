"""编辑器重写批5.1 · 列表「块状换行」布局回归（用户点名：派生步骤表加一层换行）。

用户原话（2026-09-13）：
  「把这类表格之类的加一层换行吧，放到连段步骤这个类目标题底下，不然那里空了一大块，
    一方面是不好看，另一方面是浪费空间」

覆盖：
  A. **元数据判定依据（后端）**：列表列描述新增 `nested`（控件形态是 condition / maptable /
     readonly / listtable 之一 → 该列承载嵌套结构），字段级新增 `block_layout`（任一列 nested）。
     判定只依据控件形态，不认任何业务字段名；元数据缺失时按实际值形态推断（沿用批4.6 口径）。
  B. **块状布局结构（前端）**：块首行 = 标量列横向排布；嵌套字段换行后各自成块、占满容器宽度；
     增删步骤、行内编辑、引用候选、条件/键值编辑器接线全部保留（[data-ladd]/[data-ldel]/
     [data-lcell]/[data-condcell]/[data-mapcell]）。
  C. **纯标量列表不回退**：actions 这类全标量列表仍用可增删行表格（表格能力不丢）。
  D. **通用性**：真实包扫描（veinborn + test_demo 全部模块）block_layout 与列 nested 恒一致；
     合成包用任意字段名照样触发块布局；块布局渲染函数不含任何业务字段名。

写盘/内容包只读；不触碰仓库 content/。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

# 后端/前端都不得出现的「内容包业务字段名」白名单反面（通用性护栏）。
BANNED_BUSINESS = (
    "steps", "variant_override", "trigger_skill", "consume_marks", "post_state",
    "skill_chains", "veinborn", "test_demo",
)
# 控件形态里的「嵌套结构」词汇（这是通用映射产物，允许出现在框架里）。
NESTED_CONTROLS = ("condition", "maptable", "readonly", "listtable")
SCALAR_CONTROLS = ("text", "textarea", "number", "bool", "select", "ref")


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    """截取 index.html 里两个函数之间的整段源码（含函数体，供 node 直接 eval）。"""
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end]
    # 两函数之间可能夹注释/空行：截到最后一个 '}'，只保留函数体。
    return src[: src.rindex("}") + 1]


def _flat_modules(pack: str) -> List[str]:
    out: List[str] = []

    def walk(items: List[Dict[str, Any]]) -> None:
        for m in items:
            out.append(m["module"])
            walk(m.get("children", []))

    walk(api.list_modules(pack, root=CONTENT)["modules"])
    return out


# =====================================================================================
# A. 元数据判定依据（后端）
# =====================================================================================
def test_nested_control_vocabulary_is_control_based() -> None:
    """嵌套判定只是「控件形态」的函数：嵌套控件 True、标量控件 False。"""
    for c in NESTED_CONTROLS:
        assert api.is_nested_control(c) is True, c
    for c in SCALAR_CONTROLS + ("", None):
        assert api.is_nested_control(c) is False, c


def test_column_carries_nested_flag() -> None:
    """列描述带 nested：对象 → True（readonly）、条件编辑器 → True、标量表 → False。"""
    assert api._column("k", FieldMeta(type="obj"))["nested"] is True
    assert api._column("k", FieldMeta(type="map"))["nested"] is True
    assert api._column("k", FieldMeta(type="str", editor="condition"))["nested"] is True
    assert api._column("k", FieldMeta(type="obj", editor="maptable"))["nested"] is True
    # 嵌套列表也是嵌套结构（元素是标量列表 / 引用列表都算）
    assert api._column("k", FieldMeta(type="list", element=FieldMeta(type="str")))["nested"] is True
    assert api._column("k", FieldMeta(type="int"))["nested"] is False
    assert api._column("k", FieldMeta(type="str"))["nested"] is False


def _list_field(pack: str, mod: str, entry: str, key: str) -> Dict[str, Any]:
    detail = api.entry_detail(pack, mod, entry, root=CONTENT)
    by = {f["key"]: f for f in detail["fields"]}
    assert key in by, (pack, mod, entry, key)
    return by[key]


def test_real_steps_descriptor_uses_block_layout() -> None:
    """派生连段步骤：7 个标量列 + 2 个嵌套列（触发条件 / 数值覆盖）→ 块状布局。"""
    chain = next(c for c in api.list_entries("veinborn", "skill_chains",
                                             root=CONTENT)["entries"]
                 if c["id"] == "chain_ridge_combo")
    f = _list_field("veinborn", "skill_chains", chain["id"], "steps")
    assert f["widget"] == "list" and f["control"] == "listtable"
    assert f["block_layout"] is True
    scalars = [c["key"] for c in f["columns"] if not c["nested"]]
    nests = [c["key"] for c in f["columns"] if c["nested"]]
    assert scalars == ["from", "to", "tag", "priority", "mode", "armor", "consume"]
    assert nests == ["condition", "variant_override"]
    # 嵌套列的控制形态就是判定的依据（不是字段名）
    by = {c["key"]: c for c in f["columns"]}
    assert by["condition"]["control"] == "condition"
    assert by["variant_override"]["control"] == "maptable"


def test_scalar_only_list_keeps_table_layout() -> None:
    """怪物 actions（全标量 6 列）不触发块布局 → 仍用可增删行表格。"""
    enemy = api.list_entries("veinborn", "enemies", root=CONTENT)["entries"][0]
    f = _list_field("veinborn", "enemies", enemy["id"], "actions")
    assert f["block_layout"] is False
    assert all(not c["nested"] for c in f["columns"])
    # 嵌套 readonly 对象（trigger / post_state）→ 块布局
    sp = _list_field("veinborn", "enemies", enemy["id"], "special_actions")
    assert sp["block_layout"] is True
    by = {c["key"]: c for c in sp["columns"]}
    assert by["trigger"]["nested"] is True and by["trigger"]["control"] == "readonly"
    assert by["post_state"]["nested"] is True
    # 嵌套列表（chains[].actions）→ 也判嵌套
    ch = _list_field("veinborn", "enemies", enemy["id"], "chains")
    byc = {c["key"]: c for c in ch["columns"]}
    assert byc["actions"]["nested"] is True and byc["actions"]["control"] == "listtable"


def test_all_real_list_fields_flag_matches_columns() -> None:
    """全包扫描：任何模块任何列表字段，block_layout 恒等于「存在 nested 列」。"""
    total = block = flat = 0
    for pack in ("veinborn", "test_demo"):
        for mod in _flat_modules(pack):
            for e in api.list_entries(pack, mod, root=CONTENT)["entries"][:2]:
                detail = api.entry_detail(pack, mod, e["id"], root=CONTENT)
                for f in detail["fields"]:
                    if f.get("widget") != "list":
                        continue
                    total += 1
                    expect = any(bool(c.get("nested")) for c in f.get("columns", []))
                    assert f.get("block_layout") == expect, (pack, mod, e["id"], f["key"])
                    if expect:
                        block += 1
                    else:
                        flat += 1
    # 断言不是空跑：两类都在真实包里出现过
    assert total > 100 and block > 0 and flat > 0, (total, block, flat)


def test_block_layout_is_generic_metadata_driven(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """合成包（任意模块/字段名）：含嵌套子字段的列表照样出 block_layout → 零业务硬编码。"""
    table = FieldMetaTable(modules={
        "zed": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "mix": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "caption": FieldMeta(type="str", label="标注"),
                "amount": FieldMeta(type="int", label="数量"),
                "rules": FieldMeta(type="obj", children={}, editor="condition",
                                   soft_label=True, label="规则"),
                "params": FieldMeta(type="obj", children={}, editor="maptable",
                                    soft_label=True, label="参数"),
                "nested_rows": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                    "k": FieldMeta(type="str"), "v": FieldMeta(type="int"),
                }), label="嵌套行"),
            })),
            "plain": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "a": FieldMeta(type="str"), "b": FieldMeta(type="int"),
            })),
        }),
    })
    pkg = tmp_path / "pack_blk"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "BLK", "version": "1", "schema_version": 1, "modules": ["zed"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "zed.json").write_text(json.dumps([{
        "id": "z1",
        "mix": [{"caption": "甲", "amount": 1, "rules": {"count": {"eq": 2}},
                 "params": {"hp": 3}, "nested_rows": [{"k": "x", "v": 1}]}],
        "plain": [{"a": "p", "b": 2}],
    }], ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(api, "_META_TABLE", table)

    detail = api.entry_detail("pack_blk", "zed", "z1", root=tmp_path)
    by = {f["key"]: f for f in detail["fields"]}
    mix = by["mix"]
    assert mix["block_layout"] is True
    assert [c["key"] for c in mix["columns"] if c["nested"]] \
        == ["rules", "params", "nested_rows"]
    assert [c["key"] for c in mix["columns"] if not c["nested"]] == ["caption", "amount"]
    assert by["plain"]["block_layout"] is False


def test_missing_type_metadata_falls_back_to_value_shape(tmp_path: Path,
                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    """类型未登记（soft 纯展示子字段）→ 按实际值形态推断：值是对象 → readonly → 块布局。"""
    table = FieldMetaTable(modules={
        "zed": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True),
            "rows": FieldMeta(type="list", element=FieldMeta(type="obj", children={
                "payload": FieldMeta(type="", soft_label=True, label="载荷"),
            })),
        }),
    })
    pkg = tmp_path / "pack_shape"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "S", "version": "1", "schema_version": 1, "modules": ["zed"],
    }, ensure_ascii=False), encoding="utf-8")
    (pkg / "zed.json").write_text(json.dumps(
        [{"id": "z1", "rows": [{"payload": {"a": 1}}]}], ensure_ascii=False),
        encoding="utf-8")
    monkeypatch.setattr(api, "_META_TABLE", table)

    d = api.entry_detail("pack_shape", "zed", "z1", root=tmp_path)
    f = {x["key"]: x for x in d["fields"]}["rows"]
    assert f["columns"][0]["key"] == "payload"
    assert f["columns"][0]["nested"] is True     # 值是对象 → readonly → 嵌套
    assert f["block_layout"] is True


# =====================================================================================
# B/C. 前端块状布局：node 执行真实 listTableBody / listBlockBody / listTable
# =====================================================================================
_JS_HARNESS = r"""
const fs = require("fs");
global.currentFieldValue = function (f) { return f.value; };
global.esc = function (v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
global.EMPTY_TEXT = "（空）";
global.typeZh = function (t) { return t || "文本"; };
global.fieldLabelHtml = function (label, key) {
  var l = label == null ? "" : String(label);
  var k = key == null ? "" : String(key);
  if (k && l && l !== k) { return esc(l) + ' <span class="fkey">' + esc(k) + "</span>"; }
  return esc(l || k);
};
global.helpTriggerHtml = function (f, inner) { return inner; };
global.selectOptions = function (value, options, placeholder) {
  return '<option value="">' + placeholder + "</option>";
};
global.EditorList = {
  cellValue: function (row, colKey, scalar) {
    if (scalar) { return colKey === "value" ? row : undefined; }
    return (row !== null && typeof row === "object") ? row[colKey] : undefined;
  }
};
global.EditorCondition = { parse: function () { return []; } };
global.EditorMap = { rows: function () { return []; } };
global.condBodyHtml = function () { return '<div class="cond-stub"></div>'; };
global.mapBodyHtml = function () { return '<div class="map-stub"></div>'; };
eval(fs.readFileSync(process.argv[2], "utf8"));

function col(key, label, type, control, nested) {
  return { key: key, label: label, type: type, control: control, nested: !!nested,
           ref_target: control === "ref" ? "thing" : "", enum: [] };
}
var stepsCols = [
  col("from", "源技能", "ref", "ref"),
  col("to", "目标技能", "ref", "ref"),
  col("tag", "标签", "str", "text"),
  col("condition", "触发条件", "obj", "condition", true),
  col("priority", "优先级", "int", "number"),
  col("mode", "模式", "str", "text"),
  col("armor", "霸体", "bool", "bool"),
  col("consume", "消耗", "int", "number"),
  col("variant_override", "数值覆盖", "obj", "maptable", true)
];
var stepRow = { from: "sa", to: "sb", tag: "t", condition: { count: 3 }, priority: 2,
                mode: "m", armor: true, consume: 5, variant_override: { hp: 3 } };
out.steps = listTableBody({ key: "K", label: "连段步骤", block_layout: true,
  scalar_element: false, value: [stepRow], columns: stepsCols });
out.steps2 = listTableBody({ key: "K", block_layout: true, scalar_element: false,
  value: [stepRow, stepRow], columns: stepsCols });
out.empty = listTableBody({ key: "K", block_layout: true, scalar_element: false,
  value: [], columns: stepsCols });

var flatCols = [
  col("action", "行动", "ref", "ref"), col("probability", "概率", "number", "number"),
  col("weight", "权重", "number", "number"), col("note", "备注", "str", "text")
];
out.flat = listTableBody({ key: "K", block_layout: false, scalar_element: false,
  value: [{ action: "a", probability: 1, weight: 2, note: "n" }], columns: flatCols });

var spCols = [
  col("id", "标识", "str", "text"), col("action", "行动", "ref", "ref"),
  col("trigger", "触发条件", "obj", "readonly", true),
  col("once", "仅触发一次", "bool", "bool"),
  col("post_state", "触发后状态", "obj", "readonly", true)
];
out.special = listTableBody({ key: "K", block_layout: true, scalar_element: false,
  value: [{ id: "i", action: "a", trigger: { type: "x" }, once: false,
            post_state: { state: "s" } }], columns: spCols });

// 只读视图（gm 预览）：同一判定 → 块布局；纯标量 → 表格
out.roBlock = listTable({ widget: "list", block_layout: true, row_count: 1,
  value: [stepRow], columns: stepsCols, rows: [{ from: "sa", to: "sb", tag: "t",
    condition: '{"count":3}', priority: "2", mode: "m", armor: "是", consume: "5",
    variant_override: '{"hp":3}' }] });
out.roFlat = listTable({ widget: "list", block_layout: false, row_count: 1,
  value: [{ a: 1 }], columns: flatCols, rows: [{ action: "a", probability: "1",
    weight: "2", note: "n" }] });
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, str]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批5.1 前端块布局执行")
    src = _fn_src("listTableBody", "readCellValue")
    src += "\n" + _fn_src("listTable", "kvTable")
    harness = tmp_path_factory.mktemp("batch51") / "blocks.js"
    harness.write_text(src, encoding="utf-8")
    script = tmp_path_factory.mktemp("batch51") / "run.js"
    script.write_text("var out = {};\n" + _JS_HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(harness)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_js_block_head_lists_scalars_and_nests_full_width(js: Dict[str, str]) -> None:
    out = js["steps"]
    assert '<div class="lblocks">' in out and 'class="lblock"' in out
    assert '<div class="lb-head">' in out and '<div class="lb-scalars">' in out
    # 标量列在块首行；嵌套字段在 .lb-nest-b 里各自成块
    head = out[out.index('class="lb-head"'):out.index('class="lb-nests"')]
    for k in ("from", "to", "tag", "priority", "mode", "armor", "consume"):
        assert 'data-lscalar="' + k + '"' in head, k
    assert 'data-condcell' not in head and 'data-mapcell' not in head
    assert out.count('class="lb-nest"') == 2
    assert 'data-lnest="condition"' in out and 'data-lnest="variant_override"' in out
    assert '<div class="lb-nest-b"><div class="cond-edit"' in out
    assert '<div class="lb-nest-b"><div class="map-edit"' in out
    # 不再是 9 列宽表 → 不再有横向滚动的表格（V14 根因消除）
    assert "ltable-edit" not in out and "ltable-scroll" not in out


def test_js_block_keeps_row_edit_hooks(js: Dict[str, str]) -> None:
    out = js["steps"]
    assert 'data-ladd="K"' in out
    assert 'data-ldel="0"' in out
    # 标量单元格仍按行号/列键进草稿；嵌套条件/键值仍是原接线
    assert 'data-lcell="K" data-lrow="0" data-lcol="from"' in out
    assert 'data-condcell="K" data-condrow="0" data-condcol="condition"' in out
    assert 'data-mapcell="K" data-maprow="0" data-mapcol="variant_override"' in out
    # 多行 → 多块，删除按钮各自带行号
    multi = js["steps2"]
    assert multi.count('class="lblock"') == 2
    assert 'data-ldel="1"' in multi
    # 空列表仍能加第一行；不渲染空块容器
    assert 'data-ladd="K"' in js["empty"]
    assert 'class="lblocks"' not in js["empty"]
    assert "（空列表）暂无数据行" in js["empty"]


def test_js_nested_readonly_and_ref_width_classes(js: Dict[str, str]) -> None:
    out = js["special"]
    assert out.count('class="lb-nest"') == 2
    assert "ro-cell" in out
    # 引用列给宽档、数字/布尔给窄档（V12 下拉文本不再被裁）
    assert 'class="lb-scalar ref"' in js["steps"]
    assert 'class="lb-scalar num"' in js["steps"]
    assert 'class="lb-scalar bool"' in js["steps"]


def test_js_scalar_only_list_still_renders_table(js: Dict[str, str]) -> None:
    out = js["flat"]
    assert "ltable-edit" in out and "ltable-scroll" in out
    assert '<th class="op">操作</th>' in out
    assert 'data-lcell="K"' in out and 'data-ldel="0"' in out and 'data-ladd="K"' in out
    assert "lblocks" not in out


def test_js_readonly_view_follows_same_rule(js: Dict[str, str]) -> None:
    ro = js["roBlock"]
    assert '<div class="lblocks">' in ro and "ltable-ro" not in ro
    assert ro.count('class="lb-nest"') == 2
    assert "lb-nest-b" in ro
    flat = js["roFlat"]
    assert "ltable-ro" in flat and "lblocks" not in flat


# =====================================================================================
# D. 结构 / 通用性 / 样式护栏
# =====================================================================================
def test_block_renderers_do_not_branch_on_business_keys() -> None:
    """块布局渲染只依据 control→nested / block_layout，不出现任何业务字段名。"""
    src = "\n".join([
        _fn_src("listBlockBody", "listBlockHtml"),
        _fn_src("listBlockHtml", "scalarCssClass"),
        _fn_src("scalarCssClass", "listCell"),
        _fn_src("listBlockTable", "roCellText"),
    ])
    for name in BANNED_BUSINESS:
        assert f'"{name}"' not in src, name
    # 不按字段键分支（只按 nested / control 这类通用维度）
    assert "key ===" not in src and "key===" not in src


def test_frontend_block_dispatch_is_nested_flag_driven() -> None:
    body = _fn_src("listTableBody", "listTableEdit")
    assert "f.block_layout" in body and ".nested" in body
    assert "listBlockBody(f, rows, cols, scalar)" in body
    table = _fn_src("listTable", "kvTable")
    assert "listBlockTable(f, cols)" in table
    # 表格路径未被删除（纯标量列表仍可用）
    assert "ltable-scroll" in table and "ltable-ro" in table


def test_block_layout_css_uses_tokens_and_fills_width() -> None:
    html = _html()
    blocks = re.search(r"\.lblocks\s*\{([^}]*)\}", html)
    assert blocks and "flex-direction: column" in blocks.group(1)
    block = re.search(r"\.lblock\s*\{([^}]*)\}", html)
    assert block and "var(--bw-accent) solid var(--line-accent-dash)" in block.group(1)
    scalars = re.search(r"\.lb-scalars\s*\{([^}]*)\}", html)
    assert scalars and "flex-wrap: wrap" in scalars.group(1)
    nest_b = re.search(r"\.lb-nest-b\s*\{([^}]*)\}", html)
    assert nest_b and "width: 100%" in nest_b.group(1)
    # 嵌套块里的表格/只读块占满容器：不再有 260px 上限造成的右侧空白
    assert ".lb-nest-b .ro-cell { max-width: none; }" in html
    assert (".lb-nest-b .ltable-scroll, .lb-nest-b .ltable-edit, "
            ".lb-nest-b .ltable-ro { width: 100%; }") in html
    assert ".lb-scalar.ref { flex: 2 1 230px; }" in html
    # 细滚动条令牌仍在（放不下时兜底，非首屏主路径）
    assert "var(--sb-size)" in html and "var(--sb-thumb)" in html
    # 不再靠 max-content 定宽
    assert "width: max-content" not in html


def test_block_functions_have_no_pack_business_names() -> None:
    """块布局相关函数不得写死任何内容包模块名/字段名（元数据声明除外）。"""
    src = "\n".join([
        _fn_src("listBlockBody", "listBlockHtml"),
        _fn_src("listBlockHtml", "scalarCssClass"),
        _fn_src("scalarCssClass", "listCell"),
        _fn_src("listBlockTable", "roCellText"),
    ])
    for word in ("veinborn", "test_demo"):
        assert word not in src, word
