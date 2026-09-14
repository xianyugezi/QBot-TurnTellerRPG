"""编辑器重写批4 · 实机 UX 修复回归（空列表可加行 / 表头中文名与不缩写 /
单元格统一控件外观与空值占位 / 列宽与横向滚动）。

四个问题的验收点：
  1. **空列表也出「+ 添加一行」**：无论元素子字段元数据是否声明（columns 是否为空），
     空列表必须能新建第一行；无列时空态文案与实际控件一致；已建的空对象行仍可删除。
  2. **表头「中文名 + 原始键」**：列表列名走元数据 label；嵌套子字段（actions /
     special_actions / chains 的子字段与孙字段）在 field_meta 里补展示层中文名，
     只加 label、不动校验语义。表头不被挤成缩写：最小列宽 + 横向滚动。
  3. **单元格统一控件外观**：可编辑单元格走 tokens.css 的 .cin/.cta（边框/底色/聚焦态）；
     只读单元格也给统一的有框只读外观；空值统一用 EMPTY_TEXT 占位（V3 口径）。
  4. **列宽策略**：.rows2/.row 用 minmax(0, 1fr) 防止内容撑破等宽双列；列表表格在
     自己的 .ltable-scroll 容器里横向滚动（细滚动条令牌），不贴边、不裁切。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta as fm_mod
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    """截取 index.html 里两个函数之间的整段源码（含函数体，供 node 直接 eval）。"""
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end].rstrip()
    assert src.endswith("}"), (name, src[-40:])
    return src


# ---------------------------------------------------------------------------
# 纯 JS 执行：listTableBody / listCell 的真实渲染结果
# ---------------------------------------------------------------------------
_JS_HARNESS = r"""
const fs = require("fs");
global.esc = function (v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
global.EMPTY_TEXT = "（空）";
global.INPUT_EMPTY = "未填写";
global.typeZh = function (t) { return t || "文本"; };
global.fieldLabelHtml = function (label, key) {
  var l = label == null ? "" : String(label);
  var k = key == null ? "" : String(key);
  if (k && l && l !== k) { return esc(l) + ' <span class="fkey">' + esc(k) + "</span>"; }
  return esc(l || k);
};
// V11：表头标签改走 headerLabelHtml（键名缩为 tooltip）；本批只验证控件，原样透传标签文本。
global.headerLabelHtml = function (label, key) {
  var l = label == null ? "" : String(label);
  var k = key == null ? "" : String(key);
  return esc(l || k);
};
global.currentFieldValue = function (f) { return f.value; };
global.selectOptions = function (value, options, placeholder) {
  return '<option value="">' + placeholder + "</option>";
};
global.EditorList = {
  cellValue: function (row, colKey, scalar) {
    if (scalar) { return colKey === "value" ? row : undefined; }
    return (row !== null && typeof row === "object") ? row[colKey] : undefined;
  }
};
global.fieldBody = function () { return "BODY"; };
global.fieldHint = function () { return ""; };
// 批4.6：字段标签外层多了说明气泡触发器（helpTriggerHtml）；本批只验证标签/控件，
// 故此处原样透传（说明气泡的悬停/点击行为由 tests/unit/test_editor_batch46_help.py 覆盖）。
global.helpTriggerHtml = function (f, inner) { return inner; };
eval(fs.readFileSync(process.argv[1], "utf8"));
const out = {};
// ---- 问题1：空列表 / 无列列表都要出「+ 添加一行」，已建空行可删 ----
out.emptyNoCols = listTableBody({ key: "x", value: [], columns: [], scalar_element: false });
out.emptyWithCols = listTableBody({
  key: "x", value: [],
  columns: [{ key: "a", label: "甲", type: "str", control: "text" }], scalar_element: false
});
out.rowsNoCols = listTableBody({ key: "x", value: [{}], columns: [], scalar_element: false });
out.rowsWithCols = listTableBody({
  key: "x", value: [{ a: "v" }],
  columns: [{ key: "a", label: "甲", type: "str", control: "text" }], scalar_element: false
});
// ---- 问题3：单元格控件外观 / 空值占位 ----
out.textEmpty = listCell({ key: "x" }, { a: "" }, { key: "a", control: "text" }, 0, false);
out.textVal = listCell({ key: "x" }, { a: "v" }, { key: "a", control: "text" }, 0, false);
out.numEmpty = listCell({ key: "x" }, { a: null }, { key: "a", control: "number" }, 0, false);
out.selectEmpty = listCell(
  { key: "x" }, { a: "" }, { key: "a", control: "select", enum: [] }, 0, false);
out.boolCell = listCell({ key: "x" }, { a: true }, { key: "a", control: "bool" }, 0, false);
out.roEmpty = listCell({ key: "x" }, { a: null }, { key: "a", control: "readonly" }, 0, false);
out.roVal = listCell({ key: "x" }, { a: { k: 1 } }, { key: "a", control: "readonly" }, 0, false);
out.nestedList = listCell(
  { key: "x" }, { a: [{ z: 1 }] }, { key: "a", control: "listtable" }, 0, false);
// ---- 问题4：宽字段跨列 ----
out.rowWide = fieldRow({ key: "x", label: "X", type: "list", control: "listtable", present: true });
out.rowRef = fieldRow({ key: "r", label: "R", type: "list", control: "reflist", present: true });
out.rowNarrow = fieldRow({ key: "y", label: "Y", type: "str", control: "text", present: true });
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批4 UX 前端语义执行")
    src = _fn_src("listTableBody", "listTableEdit") + "\n" + _fn_src("listCell", "readCellValue")
    src += "\n" + _fn_src("scalarCssClass", "listCell")
    src += "\n" + _fn_src("fieldRow", "fieldBody")
    harness = tmp_path_factory.mktemp("batch4ux") / "batch4_ux_harness.js"
    harness.write_text(src, encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _JS_HARNESS, str(harness)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# =====================================================================================
# 问题 1 · 空列表恒出「+ 添加一行」
# =====================================================================================
def test_empty_list_always_has_add_row_button(js: Dict[str, Any]) -> None:
    for case in ("emptyNoCols", "emptyWithCols", "rowsNoCols"):
        assert 'data-ladd="x"' in js[case], case


def test_empty_list_wording_matches_real_controls(js: Dict[str, Any]) -> None:
    # 有列空列表：空态文案承诺「+ 添加一行」→ 按钮必须在
    assert "（空列表）暂无数据行" in js["emptyWithCols"]
    assert "data-ladd" in js["emptyWithCols"]
    # 无列空列表：如实提示补元数据，但按钮同样在（不承诺不存在的控件，也不缺控件）
    assert "该列表元素的字段未在内容包元数据中声明" in js["emptyNoCols"]
    assert "（空列表）暂无数据行" in js["emptyNoCols"]
    assert "data-ladd" in js["emptyNoCols"]


def test_object_row_without_columns_is_still_deletable(js: Dict[str, Any]) -> None:
    # 无列列表新建的空对象行：至少保留「操作」列可删，避免刚建的行不可见、不可撤销
    assert "data-ldel=" in js["rowsNoCols"]
    assert "<th class=\"op\">操作</th>" in js["rowsNoCols"]


def test_empty_nocols_branch_has_no_early_return() -> None:
    """回归：`if (!cols.length)` 分支不得提前 return（否则按钮丢失）。"""
    src = _fn_src("listTableBody", "listTableEdit")
    assert "return html +" not in src
    assert src.count("return html;") == 1


# =====================================================================================
# 问题 2 · 嵌套子字段中文名 + 表头不被挤成缩写
# =====================================================================================
def test_nested_child_metadata_all_have_chinese_labels() -> None:
    groups = {
        "actions": (fm_mod.ACTION_ENTRY_CHILDREN,
                    {"action", "probability", "weight", "condition", "cooldown", "hungry"}),
        "special_actions": (fm_mod.SPECIAL_ACTION_CHILDREN,
                            {"id", "action", "trigger", "once", "priority", "trigger_cooldown",
                             "max_triggers", "post_state", "chain_ref", "desc"}),
        "special_actions.trigger": (fm_mod.SPECIAL_ACTION_TRIGGER_CHILDREN,
                                    {"type", "value", "timing", "action", "chance", "which",
                                     "side", "height"}),
        "special_actions.post_state": (fm_mod.SPECIAL_ACTION_CHILDREN["post_state"].children,
                                       {"state", "turns"}),
        "chains": (fm_mod.CHAIN_ENTRY_CHILDREN, {"id", "actions"}),
        "chains.actions": (fm_mod.CHAIN_NODE_CHILDREN, {"action", "chance", "role", "armor"}),
    }
    for where, (children, keys) in groups.items():
        assert children is not None, where
        missing = [k for k in keys if not children[k].label or children[k].label == k]
        assert not missing, (where, missing)


def test_enemy_list_columns_carry_chinese_labels() -> None:
    d = api.entry_detail("demo_full", "enemies", "rock_weasel", root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    actions = {c["key"]: c for c in by["actions"]["columns"]}
    assert actions["action"]["label"] == "行动"
    assert actions["probability"]["label"] == "概率"
    assert actions["weight"]["label"] == "权重"
    assert actions["condition"]["label"] == "条件"
    assert actions["cooldown"]["label"] == "冷却"
    assert actions["hungry"]["label"] == "饥饿值"
    special = {c["key"]: c for c in by["special_actions"]["columns"]}
    assert special["id"]["label"] == "标识"
    assert special["trigger"]["label"] == "触发条件"
    assert special["once"]["label"] == "仅触发一次"
    assert special["priority"]["label"] == "优先级"
    assert special["trigger_cooldown"]["label"] == "触发冷却"
    assert special["max_triggers"]["label"] == "最大触发次数"
    assert special["post_state"]["label"] == "触发后状态"
    assert special["chain_ref"]["label"] == "连招引用"
    assert special["desc"]["label"] == "说明"
    chains = {c["key"]: c for c in by["chains"]["columns"]}
    assert chains["id"]["label"] == "标识"
    assert chains["actions"]["label"] == "行动节点"


def test_frontend_wide_table_scroll_and_min_width() -> None:
    html = _html()
    # 容器横向滚动走细滚动条令牌
    match = re.search(r"\.ltable-scroll\s*\{([^}]*)\}", html)
    assert match, "index.html 缺少 .ltable-scroll 规则"
    rule = match.group(1)
    assert "overflow-x: auto" in rule and "max-width: 100%" in rule
    assert "var(--sb-size)" in html and "var(--sb-thumb)" in html
    # 表格按内容定列宽 + 最小列宽，不再被 fixed 压窄
    auto = re.search(r"\.ltable-edit,\s*\.ltable-ro\s*\{([^}]*)\}", html)
    assert auto and "table-layout: auto" in auto.group(1)
    # 不用 max-content：否则列恒取最长内容宽、表头换行也压不窄；宽度交给容器 + 最小列宽
    assert "width: max-content" not in html
    assert "min-width: 96px" in html
    # 表头换行而不是裁切（overflow:visible + white-space:normal）
    th = re.search(r"\.ltable-edit th\s*\{([^}]*)\}", html)
    assert th and "white-space: normal" in th.group(1) and "overflow: visible" in th.group(1)
    # 两处列表渲染都进滚动容器
    assert '<div class="ltable-scroll"><table class="ltable ltable-edit">' in html
    assert '<div class="ltable-scroll"><table class="ltable ltable-ro">' in html


def test_editable_table_rows_are_wrapped_in_scroll_container(js: Dict[str, Any]) -> None:
    out = js["rowsWithCols"]
    assert '<div class="ltable-scroll">' in out
    assert 'ltable-edit' in out
    # 中文名 + 原始键并列（fieldLabelHtml 由元数据 label 驱动）
    assert "甲" in out and "a" in out


# =====================================================================================
# 问题 3 · 单元格统一控件外观 + 空值统一占位符（V3）
# =====================================================================================
def test_text_and_number_cells_use_cin_and_empty_placeholder(js: Dict[str, Any]) -> None:
    for case in ("textEmpty", "numEmpty"):
        assert 'class="cin lcell"' in js[case], case
        assert 'placeholder="未填写"' in js[case], case
    assert 'value="v"' in js["textVal"]


def test_select_cells_use_cin_with_placeholder(js: Dict[str, Any]) -> None:
    assert 'class="cin lcell"' in js["selectEmpty"]
    assert "（未选择）" in js["selectEmpty"]


def test_bool_cell_keeps_checkbox_control(js: Dict[str, Any]) -> None:
    assert 'class="ctl-bool"' in js["boolCell"] and "checkbox" in js["boolCell"]


def test_readonly_and_nested_list_cells_are_bordered_blocks(js: Dict[str, Any]) -> None:
    assert 'class="ro-cell"' in js["roEmpty"]
    assert "（空）" in js["roEmpty"]          # 空值统一占位（V3）
    assert 'class="ro-cell"' in js["roVal"]
    # 嵌套列表单元格不在行内编辑，按只读有框块展示（不裸奔、不误写成字符串数组）
    assert 'class="ro-cell"' in js["nestedList"]
    assert "[{&quot;z&quot;:1}]" in js["nestedList"] or '{"z":1}' in js["nestedList"]


def test_frontend_ro_cell_and_cell_surface_tokens() -> None:
    html = _html()
    match = re.search(r"\.ro-cell\s*\{([^}]*)\}", html)
    assert match, "index.html 缺少 .ro-cell 规则"
    rule = match.group(1)
    assert "var(--line-soft)" in rule       # 边框
    assert "var(--surface)" in rule         # 底色
    assert "var(--text-4)" in rule          # 只读弱化字色
    assert ".ltable-edit .cin" in html and "background: var(--bg)" in html


# =====================================================================================
# 问题 4 · 列宽策略（等宽双列 + 宽字段跨列）+ 不贴边/不裁切
# =====================================================================================
def test_wide_fields_span_both_columns(js: Dict[str, Any]) -> None:
    assert 'class="row wide"' in js["rowWide"]
    assert 'class="row wide"' in js["rowRef"]
    assert 'class="row"' in js["rowNarrow"] and "row wide" not in js["rowNarrow"]


def test_frontend_grid_columns_are_shrinkable_and_equal() -> None:
    html = _html()
    rows2 = re.search(r"\.rows2\s*\{([^}]*)\}", html)
    assert rows2 and "minmax(0, 1fr) minmax(0, 1fr)" in rows2.group(1)
    row = re.search(r"\.row\s*\{([^}]*)\}", html)
    assert row and "132px minmax(0, 1fr)" in row.group(1)
    wide = re.search(r"\.rows2 > \.row\.wide\s*\{([^}]*)\}", html)
    assert wide and "grid-column: 1 / -1" in wide.group(1)


def test_frontend_op_column_has_inset_padding() -> None:
    html = _html()
    assert ".ltable-edit th.op, .ltable-edit td.op { padding-right: var(--sp-5); }" in html


def test_footer_status_bar_uses_current_batch_wording() -> None:
    html = _html()
    # 页脚标注「当前批次」（批10 起为配色按钮化 + 自定义背景图）；旧批次字串不得残留。
    assert "批10 · 配色按钮化 + 自定义背景图" in html
    assert "批9 · 配色切换" not in html
    assert "批6 · 新增/删除条目 + 检索" not in html
    assert "批5.2 · 视觉细则清零" not in html
    assert "批4.6 · 字段说明气泡" not in html
    assert "批3 · 分区页签" not in html
    # 批4 的列宽/滚动视觉仍在（本批未回退）
    assert ".ltable-scroll" in html and "data-ladd" in html
