"""编辑器重写批5.2 · 视觉细则清零（V1–V6 / V9–V11）。

逐条覆盖（docs/编辑器重写_需求与约束.md §五）：

  V1 字段网格：提示不再常驻撑行——`hint`/只读视图说明收进批4.6 说明卡；
     字段行不渲染行内提示，行高一致。
  V2 顶栏：包名/版本被省略时给 `title` 全文；窄屏先舍品牌字样，可收缩项省略号、
     身份切换固定宽。
  V3 字段控件：空值口径拆两类——输入类统一占位符「未填写」，只读/列表类统一 EMPTY_TEXT。
  V4 工具栏：无备份时「回退」真禁用（`rollbackDisabled` 唯一出口 + tokens `.btn:disabled`），
     切模块/空模块/只读身份/请求中都不沿用上一份可用外观。
  V5 元数据横幅：主信息分段一行，来源路径省略号 + `title` 全文，窄屏不折三行。
  V6 计数口径：左栏模块计数含子项时标注「（含子项）」+ 悬停明细；叶子模块口径一致。
  V9 列表区块副标题：模块/字段统一「中文（键）」，不再裸露原始键（含空态）。
  V10 列表引用列：引用列加宽档 + 下拉框预留箭头区 + chip/下拉 `title` 全文。
  V11 列表表头：只留「中文 + 类型」，键名缩为悬停 tooltip（不再折三行）。

纯 JS 断言在 node 下执行 index.html 内联标记块/函数；无 node 时跳过。
不触碰仓库 content/；不写盘。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content.models import FieldMeta
from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end]
    # 两函数之间可能夹注释/空行：截到最后一个 '}'，只保留函数体。
    return src[: src.rindex("}") + 1]


def _marked(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


# =====================================================================================
# A. 后端（V1 说明卡携带 hint；V9 关联分区字段中文名）
# =====================================================================================
def test_help_card_carries_inline_hint() -> None:
    """V1：`_hint` 文案并入 help_card（行内提示不再常驻）。"""
    fm = FieldMeta(type="int", required=True, range_min=0, range_max=9, default=3)
    card = api.help_card("k", fm)
    assert card["hint"]
    for token in ("必填", "建议范围 0~9", "默认 3"):
        assert token in card["hint"], token
    # 完全未登记也要给提示（如实标注）
    assert api.help_card("ghost", None)["hint"]


def test_entry_descriptor_help_card_has_hint() -> None:
    d = api.entry_detail("veinborn", "skills", "rb_slash", root=CONTENT)
    by = {f["key"]: f for f in d["fields"]}
    assert by["name"]["help_card"].get("hint") is not None
    assert "hint" in by["name"]["help_card"]


def test_association_section_carries_chinese_field_labels() -> None:
    """V9：关联分区副标题/空态用「中文（键）」——中文名来自字段元数据。"""
    d = api.entry_detail("veinborn", "skills", "rb_slash", root=CONTENT)
    secs = {a["field"]: a for a in d["associations"]}
    trig = secs["trigger_skill"]
    assert trig["module"] == "skill_chains" and trig["module_label"]
    assert trig["field_label"] == "触发技能"
    assert trig["local_field_label"] == "标识"
    nested = secs["steps[].to"]
    assert nested["field_label"] == "目标技能"       # 列表通配路径也能解析到中文名
    # 合成包：字段无中文名时如实留空，前端回退原始键（不凭空造词）
    assert api._path_field_label(None, "x") == ""
    assert api._path_field_label(api.field_meta_table().module("skills"), "") == ""


# =====================================================================================
# B. 纯 JS（node 执行真实函数）
# =====================================================================================
_JS_HARNESS = r"""
const fs = require("fs");
global.esc = function (v) {
  return String(v == null ? "" : v)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
};
global.INPUT_EMPTY = "未填写";
global.EMPTY_TEXT = "（空）";
global.typeZh = function (t) { return t || "文本"; };
global.currentFieldValue = function (f) { return f.value; };
global.selectHtml = function (key, value, options, placeholder) {
  return "SEL[" + key + "][" + placeholder + "]";
};
global.listTableEdit = function () { return "LT"; };
global.refListEdit = function () { return "RL"; };
global.condFieldInner = function () { return "C"; };
global.mapFieldInner = function () { return "M"; };
global.selectOptions = function (value, options, placeholder) {
  return '<option value="">' + placeholder + "</option>";
};
global.EditorList = {
  cellValue: function (row, colKey) {
    return (row !== null && typeof row === "object") ? row[colKey] : undefined;
  }
};
global.condBodyHtml = function () { return "CD"; };
global.mapBodyHtml = function () { return "MD"; };
global.EditorRef = {
  status: function (id, opts, known) {
    return id === "ghost" ? { warn: true, text: "目标不存在" } : { warn: false, text: "" };
  },
  label: function (id) { return id + "（" + id + " 名）"; }
};
global.el = function () { return null; };
eval(fs.readFileSync(process.argv[2], "utf8"));
const out = {};

// V1：说明卡行（hint / 只读视图说明）
out.linesHint = helpLines({ key: "k", label: "K", type: "数字", scale: "不适用（非数值字段）",
  range: "未标注", default: "无默认值", required: true, enum: [], ref_target: null,
  help: "", hint: "必填；默认 3" });
out.linesView = helpLines({ key: "k", label: "K", type: "对象", scale: "不适用（非数值字段）",
  range: "未标注", default: "无默认值", required: false, enum: [], ref_target: null,
  help: "", view_note: "本批只读展示（编辑见后续批次）" });
const cardH = { key: "k", label: "K", type: "文本", hint: "必填", view_note: "只读" };
helpTriggerHtml({ key: "k", label: "K", help_card: cardH }, "K");
out.trigCard = HELP_CARDS[Object.keys(HELP_CARDS)[0]];
out.trigRegisteredSame = HELP_CARDS[Object.keys(HELP_CARDS)[0]] === cardH;

// V2：包名文本 / title 全文
out.packText = packOptionText({ id: "veinbo", name: "蚀脉", version: "2.1", module_count: 14 });
out.packTitle = packOptionTitle({ id: "veinbo", name: "蚀脉", version: "2.1", module_count: 14 });
out.packNoVersion = packOptionTitle({ id: "p", name: "P", module_count: 3 });

// V3：输入控件统一占位符；只读仍走 EMPTY_TEXT
out.textEmpty = editControl({ key: "a", control: "text", value: "" });
out.numEmpty = editControl({ key: "a", control: "number", value: null });
out.taEmpty = editControl({ key: "a", control: "textarea", value: "" });
out.textFilled = editControl({ key: "a", control: "text", value: "v" });
out.select = editControl({ key: "a", control: "select", enum: [], value: "" });
out.bool = editControl({ key: "a", control: "bool", value: true });
out.cellText = listCell({ key: "x" }, { a: "" }, { key: "a", control: "text" }, 0, false);
out.cellNum = listCell({ key: "x" }, { a: null }, { key: "a", control: "number" }, 0, false);
out.cellRef = listCell({ key: "x" }, { a: "r1" },
  { key: "a", control: "ref", ref_target: "t" }, 0, false);
out.roCell = listCell({ key: "x" }, { a: null }, { key: "a", control: "readonly" }, 0, false);

// V4：回退可用性唯一判定
out.rbNoBackup = rollbackDisabled(null, true, false);
out.rbNoExists = rollbackDisabled({ exists: false }, true, false);
out.rbHas = rollbackDisabled({ exists: true }, true, false);
out.rbBusy = rollbackDisabled({ exists: true }, true, true);
out.rbReadonly = rollbackDisabled({ exists: true }, false, false);

// V6：计数口径
out.cntParent = moduleCountLabel({ count: 104, own_count: 26, children: [{ module: "action" }] });
out.cntParentNoKids = moduleCountLabel({ count: 104, own_count: 26, children: [] });
out.cntLeaf = moduleCountLabel({ count: 14, own_count: 14, children: [] });

// V9：中文（键）
out.lk = labeledKey("特殊行动", "special_actions");
out.lkSame = labeledKey("x", "x");
out.lkNoLabel = labeledKey("", "ghost");

// V10：chip title 全文
out.chip = refValChips(["a"], [{ id: "a", name: "甲" }], true);
out.chipWarn = refValChips(["ghost"], [], true);
out.chipEmpty = refValChips([], [], true);

// V11：表头只留中文 + 悬停全文
out.head = headerLabelHtml("特殊行动", "special_actions");
out.headNoLabel = headerLabelHtml("", "ghost");
out.headSame = headerLabelHtml("x", "x");
out.tableHead = listTableBody({ key: "K", block_layout: false, scalar_element: false,
  value: [{ special_actions: "a" }],
  columns: [{ key: "special_actions", label: "特殊行动", type: "ref", control: "ref",
              ref_target: "t", nested: false }] });
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批5.2 前端视觉执行")
    src = "\n".join([
        _marked("EDITOR_HEADER_LABEL"),
        _marked("EDITOR_LABELED_KEY"),
        _marked("EDITOR_COUNT_LABEL"),
        _marked("EDITOR_TOPBAR_LABEL"),
        _marked("EDITOR_ROLLBACK"),
        _marked("EDITOR_HELP"),
        _fn_src("editControl", "selectOptions"),
        _fn_src("scalarCssClass", "listCell"),
        _fn_src("listCell", "readCellValue"),
        _fn_src("refValChips", "refCandidateList"),
        _fn_src("listTableBody", "listTableEdit"),
    ])
    harness = tmp_path_factory.mktemp("batch52") / "visual.js"
    harness.write_text(src, encoding="utf-8")
    script = tmp_path_factory.mktemp("batch52") / "run.js"
    script.write_text(_JS_HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(harness)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# ---------------------------------------------------------------------------
# V1 · 提示进说明卡，行内不再常驻
# ---------------------------------------------------------------------------
def test_v1_help_card_lines_include_hint_and_view_note(js: Dict[str, Any]) -> None:
    hint_keys = [r["k"] for r in js["linesHint"]]
    assert "提示" in hint_keys and "说明" not in hint_keys
    view_keys = [r["k"] for r in js["linesView"]]
    assert "当前视图" in view_keys
    # 触发器注册的卡片保留 hint / view_note（说明卡内容完整）
    assert js["trigRegisteredSame"] is True
    assert js["trigCard"]["hint"] == "必填" and js["trigCard"]["view_note"] == "只读"


def test_v1_field_row_has_no_inline_hint() -> None:
    html = _html()
    row = _fn_src("fieldRow", "fieldBody")
    assert "fieldHint" not in row and "hintBits" not in row
    assert 'class="hint"' not in html
    assert ".hint {" not in html
    # 只读说明改由 view_note 进说明卡
    assert "view_note" in row


# ---------------------------------------------------------------------------
# V2 · 顶栏 title 全文 + 宽度分配
# ---------------------------------------------------------------------------
def test_v2_pack_text_and_title(js: Dict[str, Any]) -> None:
    assert js["packText"] == "蚀脉  (veinbo · 14 模块)"
    assert "蚀脉（veinbo）" in js["packTitle"]
    assert "版本 2.1" in js["packTitle"] and "14 个模块" in js["packTitle"]
    # 无版本时不凭空出现「版本」
    assert "版本" not in js["packNoVersion"]


def test_v2_frontend_sets_title_and_allocates_width() -> None:
    html = _html()
    assert "function syncPackTitle()" in html
    assert "sel.title = title" in html and "box.title = title" in html
    assert "o.title = packOptionTitle(p)" in html
    # 身份切换固定宽、包名可收缩（省略号 + title）
    rolesel = re.search(r"^\.rolesel\s*\{([^}]*)\}", html, re.M)
    assert rolesel and "flex: 0 0 auto" in rolesel.group(1)
    assert "@media (max-width: 760px)" in html and ".brand { display: none; }" in html


# ---------------------------------------------------------------------------
# V3 · 空值口径
# ---------------------------------------------------------------------------
def test_v3_input_controls_use_unified_placeholder(js: Dict[str, Any]) -> None:
    for case in ("textEmpty", "numEmpty", "taEmpty", "cellText", "cellNum"):
        assert 'placeholder="未填写"' in js[case], case
    # 有值时值照常渲染（占位符只在空值时可见）
    assert 'value="v"' in js["textFilled"]
    # 下拉/布尔不是空值占位符（各自语义保留）
    assert js["select"].startswith("SEL[") and "（未选择）" in js["select"]
    assert "checkbox" in js["bool"]
    # 只读/列表空值仍统一 EMPTY_TEXT
    assert "（空）" in js["roCell"]


def test_v3_empty_literal_single_source() -> None:
    html = _html()
    assert html.count("（空）") == 1
    assert html.count("未填写") == 1
    assert 'var INPUT_EMPTY = "未填写";' in html
    assert "var EMPTY_TEXT = " in html


# ---------------------------------------------------------------------------
# V4 · 回退真禁用
# ---------------------------------------------------------------------------
def test_v4_rollback_disabled_truth_table(js: Dict[str, Any]) -> None:
    assert js["rbNoBackup"] is True and js["rbNoExists"] is True
    assert js["rbBusy"] is True and js["rbReadonly"] is True
    assert js["rbHas"] is False


def test_v4_frontend_and_css_wiring() -> None:
    html = _html()
    assert "function rollbackDisabled(backup, editable, busy)" in html
    assert "function refreshRollbackButton()" in html
    # 唯一出口：备份回读 / 忙碌 / 切模块 / 空模块 / 身份切换都经过它
    assert html.count("refreshRollbackButton()") >= 5
    assert "state.backup = null;" in html
    # tokens 禁用视觉（灰边灰字），危险按钮悬停不覆盖
    assert ".btn.danger:disabled, .btn.danger:disabled:hover" in html
    assert "var(--text-disabled)" in html and "var(--line)" in html


# ---------------------------------------------------------------------------
# V5 · 元数据横幅分段
# ---------------------------------------------------------------------------
def test_v5_meta_banner_segmented_with_source_tooltip() -> None:
    html = _html()
    meta = re.search(r"\.meta\s*\{([^}]*)\}", html)
    assert meta and "flex-wrap: nowrap" in meta.group(1) and "overflow: hidden" in meta.group(1)
    src = re.search(r"\.meta\s+\.src\s*\{([^}]*)\}", html)
    assert src and "text-overflow: ellipsis" in src.group(1) and "min-width: 0" in src.group(1)
    detail = html[html.index("function renderDetail("):html.index("function assocPaneHtml(")]
    assert "个字段" in detail and "个分组" in detail
    assert 'title="元数据来源：' in detail
    assert "本页字段由内容包元数据生成" not in detail


# ---------------------------------------------------------------------------
# V6 · 计数口径
# ---------------------------------------------------------------------------
def test_v6_module_count_label_scope(js: Dict[str, Any]) -> None:
    parent = js["cntParent"]
    assert parent["text"] == "104（含子项）"
    assert "本模块 26" in parent["title"] and "子项 78" in parent["title"]
    # 声明了子项但 own==count（退化）也按含子项标注
    assert js["cntParentNoKids"]["text"] == "104（含子项）"
    leaf = js["cntLeaf"]
    assert leaf["text"] == "14" and "含子项" not in leaf["text"]
    assert "本模块条目数" in leaf["title"]


def test_v6_frontend_renders_label_and_header_note() -> None:
    html = _html()
    render = html[html.index("function renderModules()"):html.index("function loadModules()")]
    assert "moduleCountLabel(n)" in render
    assert "cl.title" in render and "cl.text" in render
    assert "计数含子项" in html


# ---------------------------------------------------------------------------
# V9 · 区块副标题「中文（键）」
# ---------------------------------------------------------------------------
def test_v9_labeled_key(js: Dict[str, Any]) -> None:
    assert js["lk"] == "特殊行动（special_actions）"
    assert js["lkSame"] == "x" and js["lkNoLabel"] == "ghost"


def test_v9_assoc_pane_uses_labeled_key() -> None:
    pane = _fn_src("assocPaneHtml", "bindAssocSections")
    assert "labeledKey(a.module_label, a.module)" in pane
    assert "labeledKey(a.field_label, a.field)" in pane
    assert "labeledKey(a.local_field_label, a.local_field)" in pane
    # 旧裸键渲染不得残留
    assert 'esc(a.module_label) + " · 保存写入"' not in pane
    assert 'esc(a.field) + " 指向本条目"' not in pane


# ---------------------------------------------------------------------------
# V10 · 引用列 / chip 不裁字
# ---------------------------------------------------------------------------
def test_v10_ref_chip_and_select_title(js: Dict[str, Any]) -> None:
    assert 'title="a（a 名）"' in js["chip"]
    assert "目标不存在" in js["chipWarn"]
    assert "（未选择任何引用）" in js["chipEmpty"]


def test_v10_ref_width_arrow_and_title_css() -> None:
    html = _html()
    assert "function refSelectTitle(sel, target)" in html
    # 下拉框右侧预留箭头区（箭头不遮字）
    sel_rule = re.search(r"select\.cin\s*\{([^}]*)\}", html)
    assert sel_rule and "padding: 1px var(--sp-9) 1px var(--sp-2);" in sel_rule.group(1)
    # 引用列加宽档（编辑 + 只读）
    assert ".ltable-edit th.ref, .ltable-ro th.ref { min-width: 170px; }" in html
    # chip 省略号 + 全文 title
    mono = re.search(r"\.refval\s+\.mono2\s*\{([^}]*)\}", html)
    assert mono and "text-overflow: ellipsis" in mono.group(1)
    # 引用单元格 / 表头带上按控件形态的宽度档
    body = _fn_src("listTableBody", "listTableEdit")
    assert "scalarCssClass(c.control)" in body


# ---------------------------------------------------------------------------
# V11 · 表头只留中文 + 类型，键名入 tooltip
# ---------------------------------------------------------------------------
def test_v11_header_label(js: Dict[str, Any]) -> None:
    head = js["head"]
    assert "特殊行动" in head and "special_actions" not in head.split("title=")[0]
    assert 'title="特殊行动（special_actions）"' in head
    assert js["headNoLabel"] == '<span class="hkey" title="ghost">ghost</span>'
    assert 'title="x"' in js["headSame"]


def test_v11_table_header_has_no_visible_key(js: Dict[str, Any]) -> None:
    out = js["tableHead"]
    assert '<th class="ref">' in out
    assert "特殊行动" in out and 'title="特殊行动（special_actions）"' in out
    # 可见表头不含裸键（键只在 title 里）
    th = out[out.index("<th"):out.index("</th>") + 5]
    assert "special_actions" not in th.replace('title="特殊行动（special_actions）"', "")


def test_v11_frontend_uses_header_label_in_all_list_headers() -> None:
    html = _html()
    # 表格表头 + 块状布局标签都改走 headerLabelHtml（列表区块统一口径）
    assert html.count("headerLabelHtml(") >= 6
    # 主表单行/对象子字段仍用 fieldLabelHtml（中文 + 弱化键名）
    assert "fieldLabelHtml(f.label, f.key)" in html


# =====================================================================================
# C. 通用性护栏：新逻辑不写死业务字段名/包名
# =====================================================================================
def test_batch52_functions_have_no_business_names() -> None:
    src = "\n".join([
        _marked("EDITOR_HEADER_LABEL"), _marked("EDITOR_LABELED_KEY"),
        _marked("EDITOR_COUNT_LABEL"), _marked("EDITOR_TOPBAR_LABEL"),
        _marked("EDITOR_ROLLBACK"),
        _fn_src("fieldRow", "fieldBody"),
        _fn_src("refValChips", "refCandidateList"),
        _fn_src("refSelectTitle", "markRefWarn"),
    ])
    for word in ("veinborn", "test_demo", "skill_chains", "special_actions",
                 "equipment", "怪物", "装备", "职业"):
        assert word not in src, word


def test_changed_files_use_tokens_only() -> None:
    """改动的视觉只用 tokens 令牌：不得出现硬写色值（#rrggbb）。"""
    html = _html()
    for begin, end in ((".meta {", "}"), (".meta .src {", "}"),
                       (".refval {", "}"), (".refval .mono2 {", "}"),
                       (".btn.danger:disabled, .btn.danger:disabled:hover {", "}")):
        start = html.index(begin)
        seg = html[start:html.index(end, start) + 1]
        assert "var(--" in seg, begin
        assert not re.search(r"#[0-9a-fA-F]{3,6}", seg), begin
