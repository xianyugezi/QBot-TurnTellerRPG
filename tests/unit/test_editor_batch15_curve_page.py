"""编辑器重写批15 · #2 经验曲线 + 三段合并页测试。

用户原话（批15 #2）：「默认地图、等级上限、经验曲线合并为一栏，经验曲线默认显示经验公式，
双击可以打开/编辑查看具体各个等级的经验需求，并在这个页面顶部增加一个启用/禁用公式的选项。」

覆盖任务书要求（通用机制，不写死模块名/字段名/段名）：
  · 合并页来自**包声明** `segment_pages`（同一栏呈现多段；数据文件/段 id/校验路径不动）；
    中栏一条页行、右栏同栏多子块（每段一个折叠子块，一次看全）；
  · 曲线控件识别「整数序号 → 数值」的映射（形状驱动，不认 `exp_curve` 字段名）：
    默认 = 公式/摘要视图（不铺开全部等级）；双击 → 明细表（可编辑、可增删行）；
  · 顶部「启用/禁用公式」开关（数据键 `use_formula`，**缺省 true = 行为与现状一致**）；
    关闭后明细显式值为准；**单一来源**：两者互不自动改写（公式启用时明细只读）；
  · 三态：缺省 / 关 / 开；写盘 + 回退逐字节复原；不动开关时读取行为与修前一致；
  · 前端纯逻辑（node 执行 EditorCurve）+ 接线 / 既有布局（列表表格 / 块状 / kvtable）不回归。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta_pack
from qbot_rpg.content.models import FieldMeta
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


def _pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def _page() -> Dict[str, Any]:
    """当前包声明里的第一个合并页（动态发现，不写死页 id / 段名）。"""
    pages = api.list_entries("veinborn", "settings", root=CONTENT)["pages"]
    assert pages, "包声明 segment_pages 未生效：settings 模块没有合并页"
    return pages[0]


# ---------------------------------------------------------------------------
# 一、合并页（包声明驱动，不写死段名）
# ---------------------------------------------------------------------------
def test_page_lists_declared_segments_and_marks_briefs() -> None:
    page = _page()
    assert page["segments"], "合并页必须声明至少一个段"
    le = api.list_entries("veinborn", "settings", root=CONTENT)
    marked = {e["id"]: e.get("page") for e in le["entries"] if e["id"] in page["segments"]}
    assert marked and all(v == page["id"] for v in marked.values()), marked
    # 段条目仍在 entries 里（计数/索引不变——页面只是展示层聚合）
    assert all(e["id"] != page["id"] for e in le["entries"])
    assert le["count"] == len(le["entries"])


def test_page_detail_presents_all_segments_in_one_column() -> None:
    page = _page()
    d = api.entry_detail("veinborn", "settings", page["id"], root=CONTENT)
    assert d["page"] is True and d["page_id"] == page["id"]
    assert d["page_segments"] == list(page["segments"])
    # 同栏：一个分组 + 每段一个子块（一次看全，全部展开）
    assert [f["key"] for f in d["fields"]] == list(page["segments"])
    assert len(d["groups"]) == 1 and d["groups"][0]["name"] == page["label"]
    blocks = d["blocks"][page["label"]]
    assert [b["name"] for b in blocks] == [f["subgroup"] for f in d["fields"]]
    assert all(b["collapsed"] is False for b in blocks), "合并页子块全部展开（一次看全三段）"
    # 每段的字段描述仍按各自类型出（text / number / curve 各一）——段呈现不串味
    controls = {f["key"]: f["control"] for f in d["fields"]}
    assert len(set(controls.values())) >= 2


def test_segment_pages_declaration_is_shape_validated_and_filtered(tmp_path: Path) -> None:
    """包声明形态校验（不写死模块/段名）：合法通过；非法键/重复页 id → 报错；悬空段被过滤。"""
    ok = {"mod_a": [{"id": "p1", "label": "页", "segments": ["s1", "s2"], "help": "h"}]}
    parsed = field_meta_pack.parse_field_meta(
        {"schema_version": field_meta_pack.SCHEMA_VERSION, "segment_pages": ok}, "synth")
    assert parsed.segment_pages["mod_a"][0]["segments"] == ("s1", "s2")
    bad_unknown = {"mod_a": [{"id": "p1", "label": "页", "segments": ["s1"], "x": 1}]}
    with pytest.raises(field_meta_pack.PackFieldMetaError):
        field_meta_pack.parse_field_meta(
            {"schema_version": field_meta_pack.SCHEMA_VERSION,
             "segment_pages": bad_unknown}, "synth")
    dup = {"mod_a": [{"id": "p1", "label": "页", "segments": ["s1"]},
                     {"id": "p1", "label": "页2", "segments": ["s2"]}]}
    with pytest.raises(field_meta_pack.PackFieldMetaError):
        field_meta_pack.parse_field_meta(
            {"schema_version": field_meta_pack.SCHEMA_VERSION, "segment_pages": dup}, "synth")
    # 声明里不存在的段被过滤（不产生悬空段）：真包副本里塞一个假段名
    pack = _pack_copy(tmp_path)
    fmp = pack / "veinborn" / "field_meta.json"
    raw = json.loads(fmp.read_text(encoding="utf-8"))
    mod = next(iter(raw["segment_pages"]))
    raw["segment_pages"][mod][0]["segments"].append("no_such_segment_xyz")
    fmp.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    pages = api.list_entries("veinborn", mod, root=pack)["pages"]
    assert pages and all("no_such_segment_xyz" not in p["segments"] for p in pages)


def test_page_write_and_rollback(tmp_path: Path) -> None:
    """合并页写盘：段补丁按键写回同一对象；回退逐字节复原。"""
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    page = _page()
    seg = page["segments"][0]
    data = json.loads(before)
    res = editor_ops.save_entry("veinborn", "settings", page["id"],
                                {seg: data[seg]}, root=pack, role="owner")
    assert res["ok"] is True, res
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack, role="owner")
    assert rb["ok"] is True
    assert sf.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 二、曲线控件三态 + 缺省 + 单一来源
# ---------------------------------------------------------------------------
def _curve_field(pack: Path = CONTENT) -> Dict[str, Any]:
    d = api.entry_detail("veinborn", "settings", "exp_curve", root=pack)
    return d["fields"][0]


def test_curve_detection_is_shape_driven() -> None:
    assert api._is_curve_value({"1": 10, "2": 20, "35": 43050})
    assert api._is_curve_value({"1": 10, "2": 20, "use_formula": False})
    assert api._is_curve_value({"1": 10, "2": 20, "formula": "n*n"})
    assert not api._is_curve_value({"a": 1, "b": 2})            # 键非整数序号
    assert not api._is_curve_value({"1": 10})                  # 单点太小
    assert not api._is_curve_value({"1": "x", "2": "y"})       # 值非数字
    assert not api._is_curve_value({"1": True, "2": False})    # bool 不算数字


def test_curve_default_is_formula_summary_not_expanded() -> None:
    """缺省态 = 公式/摘要视图：35 级不铺开，detail_editable=False（单一来源）。"""
    f = _curve_field()
    assert f["control"] == "curve" and f["widget"] == "curve"
    c = f["curve"]
    assert c["use_formula"] is True, "缺省 true = 行为与现状一致"
    assert c["detail_editable"] is False
    assert c["count"] == 35 and len(c["entries"]) == 35
    assert [p["level"] for p in c["entries"]] == list(range(1, 36)), "明细按等级升序"
    assert "共 35 级" in c["summary"]
    assert c["note"], "单一来源提示必须随控件下发"


def test_curve_spec_default_flag_true_when_absent_and_no_mutation() -> None:
    view = api._PackView(CONTENT / "veinborn", api._manifest(CONTENT / "veinborn"))
    value = {"1": 100, "2": 480}
    snapshot = json.dumps(value, sort_keys=True)
    spec = api._curve_spec(value, FieldMeta(type="obj"), view)
    assert spec["use_formula"] is True and spec["detail_editable"] is False
    assert json.dumps(value, sort_keys=True) == snapshot, "读取不得改动原值（不隐式写 use_formula）"
    off = dict(value, use_formula=False)
    spec2 = api._curve_spec(off, FieldMeta(type="obj"), view)
    assert spec2["use_formula"] is False and spec2["detail_editable"] is True


def test_curve_toggle_off_edit_level_write_and_rollback(tmp_path: Path) -> None:
    """三态端到端（缺省 → 关）：改某一级经验 → 真写盘 → 回退逐字节复原。"""
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    raw = json.loads(before)["exp_curve"]
    # 缺省：无 use_formula 键，控件按「公式为准」
    assert "use_formula" not in raw
    assert _curve_field(pack)["curve"]["use_formula"] is True
    off = dict(raw, use_formula=False)
    off["1"] = 111
    res = editor_ops.save_entry("veinborn", "settings", "exp_curve",
                                {"exp_curve": off}, root=pack, role="owner")
    assert res["ok"] is True, res
    written = json.loads(sf.read_text(encoding="utf-8"))["exp_curve"]
    assert written["use_formula"] is False and written["1"] == 111
    # 关闭后明细可编（单一来源：以明细显式值为准）
    assert _curve_field(pack)["curve"]["detail_editable"] is True
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack, role="owner")
    assert rb["ok"] is True
    assert sf.read_text(encoding="utf-8") == before


def test_curve_toggle_on_keeps_explicit_detail(tmp_path: Path) -> None:
    """三态端到端（关 → 开）：重新打开公式只改开关，**不重算明细**（单一来源，互不自动改写）。"""
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    on = dict(json.loads(before)["exp_curve"], use_formula=True)
    on["1"] = 111
    res = editor_ops.save_entry("veinborn", "settings", "exp_curve",
                                {"exp_curve": on}, root=pack, role="owner")
    assert res["ok"] is True, res
    reread = json.loads(sf.read_text(encoding="utf-8"))["exp_curve"]
    assert reread["use_formula"] is True and reread["1"] == 111, "开关不重算明细"
    f = _curve_field(pack)["curve"]
    assert f["use_formula"] is True and f["detail_editable"] is False
    assert any(p["level"] == 1 and p["value"] == 111 for p in f["entries"])
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack, role="owner")
    assert rb["ok"] is True
    assert sf.read_text(encoding="utf-8") == before


def test_curve_untouched_switch_behaviour_unchanged(tmp_path: Path) -> None:
    """负向：不动开关时，读取行为与修前一致——无 use_formula 键、不改文件、以公式为准。"""
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    d = api.entry_detail("veinborn", "settings", "exp_curve", root=pack)
    c = d["fields"][0]["curve"]
    assert c["use_formula"] is True and c["detail_editable"] is False
    assert "use_formula" not in json.loads(sf.read_text(encoding="utf-8"))["exp_curve"]
    assert sf.read_text(encoding="utf-8") == before, "只读接口不得写盘"


def test_curve_single_source_note_present_backend_and_frontend() -> None:
    f = _curve_field()
    note = f["curve"]["note"]
    assert "单一来源" in note and "明细" in note
    html = HTML.read_text(encoding="utf-8")
    assert "单一来源" in html, "界面必须写明谁覆盖谁"


# ---------------------------------------------------------------------------
# 三、前端纯逻辑（node 执行 EditorCurve）+ 接线 / 布局不回归
# ---------------------------------------------------------------------------
_CURVE_HARNESS = r"""
const C = require(process.argv[1]);
const out = {};
const v = { "1": 100, "2": 480, "3": 810 };
const st = C.fromValue(v, "use_formula", "formula");
out.flagDefault = st.useFormula;                  // 缺省 true
out.levels = st.points.map(function (p) { return p.level; });
C.toggle(st);
out.flagOff = st.useFormula;
C.setPoint(st, 0, 111);
C.addPoint(st);
out.afterAdd = st.points.length;
C.delPoint(st, 0);
out.afterDel = st.points.length;
const back = C.toValue(st, "use_formula", "formula");
out.valueFlag = back["use_formula"];
out.hasFormulaKey = Object.prototype.hasOwnProperty.call(back, "formula");
C.setLevel(st, 0, "9");
out.sortedLast = st.points[st.points.length - 1].level;   // 重排后仍是升序
const s2 = C.fromValue({ "1": 5, "2": 6, formula: "n" }, "use_formula", "formula");
out.formula = s2.formula;
out.summary = C.summary(s2);
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 曲线语义执行")
def test_editor_curve_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "curve.js"
    src.write_text(_marked_block("/* EDITOR_CURVE_BEGIN */", "/* EDITOR_CURVE_END */"),
                   encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _CURVE_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)
    assert out["flagDefault"] is True and out["flagOff"] is False
    assert out["levels"] == [1, 2, 3]
    assert out["afterAdd"] == 4 and out["afterDel"] == 3
    assert out["valueFlag"] is False
    assert out["hasFormulaKey"] is False, "未声明公式时不写 formula 键"
    assert out["sortedLast"] == 9
    assert out["formula"] == "n" and "共 2 级" in out["summary"]


def test_frontend_curve_page_wiring_and_no_layout_regression() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("EditorCurve", "function curveBodyHtml(", "function bindCurveSections(",
                  'case "curve"', "data-curveflag", "data-curveval", "data-curveadd",
                  "data-curvedel", "dblclick", "CURVE_OPEN", "EDITOR_CURVE_BEGIN"):
        assert token in html, token
    assert 'bindCurveSections(el("p-body"));' in html
    # 页行：中栏一条 + 段收进页行（跳转落到页上）
    for token in ("pageitem", "state.pages", "function pageOfEntry("):
        assert token in html, token
    # 既有布局/控件不回归（块状换行、列表表格、kvtable、说明气泡、主题/字号仍在）
    for token in ("listTableBody", "listBlockBody", "EDITOR_LIST_BEGIN", "EDITOR_KV_BEGIN",
                  "EditorBlocks", ".subblk", "helpTriggerHtml", "kvTableBody"):
        assert token in html, token


def test_footer_batch_note_current_and_stale_note_absent() -> None:
    """页脚批次串 →「批62 · 深炼金口径C与淬炼指令」；旧批次串不得残留。"""
    html = HTML.read_text(encoding="utf-8")
    m = re.search(r'<div class="panel-ft"><span>(.*?)</span></div>', html)
    assert m and m.group(1) == "批62 · 深炼金口径C与淬炼指令", m and m.group(1)
    assert "批55 · 特效强度预算" not in html
    assert "批50 · 特效轴地基" not in html
    assert "批49 · 测试 flake 根治" not in html
    assert "批47 · 符文数值与类型差异" not in html
    assert "批46 · 符文地基" not in html
    assert "批45 · 装备占比校准" not in html
    assert "批44 · 投入暴击" not in html
    assert "批40 · 实例uid与随机流" not in html
    assert "批14 · 可编辑性与提示" not in html
    assert "批37 · 战后恢复" not in html
