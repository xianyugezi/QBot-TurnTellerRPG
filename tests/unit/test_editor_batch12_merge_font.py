"""编辑器重写批12 · 结构声明类（#1 条目聚合 / #12 生活模块层级 / #3 货币下拉 / #13 字号三档）。

覆盖：
  A. **#1 entry_merge（条目聚合展示）**：包声明形态（简写/完整、严格报错）；
     编辑器读取层通用聚合（被并入模块 `merged_into`、目标模块 `merged`/`total_count`、
     `list_entries.merge_sections` 按来源分小节）；**编辑/保存路由回来源模块**（真写盘 +
     回退）；**不声明 entry_merge 的包行为与现状一致**（回归）。
  B. **#12 生活模块层级**：veinborn 把生活/生产模块挂到包内既有父模块下（不凭空造模块）；
     层级生效且计数自洽。
  C. **#3 死亡惩罚货币下拉**：`drop_currency[].currency` 元数据声明展示层引用
     （`options_ref`），候选来自 `settings.currencies` 的 id；字段 type/校验语义不变。
  D. **#13 字号三档**：EditorFont 纯逻辑（node 执行）+ 三档 `--fs-*` 令牌齐备 +
     面板接线 + 只改 data-fs（与 data-theme 正交）。
  E. **通用性**：编辑器读取层不写死任何业务模块名（entry_merge 全部来自包声明）。

写盘只发生在 tmp_path（仓库 content/ 一个字节都不动）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
FIELD_META_PY = REPO / "qbot_rpg" / "content" / "field_meta.py"
API_PY = REPO / "qbot_rpg" / "web" / "api.py"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _marked(name: str) -> str:
    html = _html()
    m = re.search(r"/\* EDITOR_%s_BEGIN \*/(.*?)/\* EDITOR_%s_END \*/" % (name, name),
                  html, re.S)
    assert m, f"index.html 缺少 EDITOR_{name} 标记块"
    return m.group(1)


def _run_node(source: str) -> Any:
    proc = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


# =====================================================================================
# A0 · 包声明形态（entry_merge 解析）
# =====================================================================================
def _decl(raw: Dict[str, Any]) -> pack_meta.PackFieldMeta:
    return pack_meta.parse_field_meta({"schema_version": 1, **raw}, "pack_x")


def test_entry_merge_shorthand_and_full_form_parse() -> None:
    d = _decl({"entry_merge": {"base": ["stats", "formula"]}})
    assert d.entry_merge == {"base": {"sources": ("stats", "formula"),
                                      "keep_top_level": ()}}
    d2 = _decl({"entry_merge": {"base": {"sources": ["a"], "keep_top_level": ["a"]}}})
    assert d2.entry_merge["base"]["keep_top_level"] == ("a",)
    # 不声明 → 空表（旧包完全不变）
    assert _decl({}).entry_merge == {}


@pytest.mark.parametrize("bad", [
    {"base": "stats"},                                   # 值应为数组/对象
    {"base": ["stats", "stats"]},                        # 元素重复
    {"base": [""]},                                       # 空串
    {"base": {"sources": ["x"], "keep_top_level": ["y"]}},  # keep 不在 sources
    {"base": {"sources": ["base"]}},                     # 目标并入自身
    {"base": {"sources": ["x"], "extra": 1}},            # 未知键
    {"base": {"keep_top_level": []}},                    # 缺 sources
])
def test_entry_merge_illegal_forms_raise(bad: Dict[str, Any]) -> None:
    with pytest.raises(pack_meta.PackFieldMetaError):
        _decl({"entry_merge": bad})


def test_entry_merge_is_registered_top_level_key() -> None:
    assert "entry_merge" in pack_meta.TOP_LEVEL_KEYS


# =====================================================================================
# A1 · 编辑器读取层通用聚合
# =====================================================================================
def _write(path: Path, body: object) -> None:
    path.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")


def _make_pack(root: Path, name: str, *, merge: bool) -> Path:
    pkg = root / name
    pkg.mkdir()
    manifest: Dict[str, Any] = {
        "name": name, "version": "1", "schema_version": 1,
        "modules": ["zz_base", "zz_stats", "zz_formula"],
    }
    if merge:
        manifest["module_tree"] = []
    _write(pkg / "manifest.json", manifest)
    _write(pkg / "zz_base.json", {"alpha": {"name": "甲"}, "beta": {"name": "乙"}})
    _write(pkg / "zz_stats.json", {"hp": {"name": "生命", "base": 10},
                                   "mp": {"name": "法力", "base": 5}})
    _write(pkg / "zz_formula.json", {"f1": {"expr": "a+b"}})
    if merge:
        _write(pkg / "field_meta.json", {
            "schema_version": 1,
            "module_labels": {"zz_base": "基础", "zz_stats": "属性", "zz_formula": "公式"},
            "entry_merge": {"zz_base": ["zz_stats", "zz_formula"]},
        })
    return pkg


def _node_of(mods: Dict[str, Any], mid: str) -> Dict[str, Any]:
    found: Dict[str, Any] = {}

    def walk(nodes: Any) -> None:
        for n in nodes or []:
            if n.get("module") == mid:
                found.update(n)
            walk(n.get("children"))

    walk(mods["modules"])
    return found


def test_entry_merge_marks_sources_and_totals(tmp_path: Path) -> None:
    root = tmp_path
    _make_pack(root, "p_merged", merge=True)
    mods = api.list_modules("p_merged", root=root)
    base = _node_of(mods, "zz_base")
    assert base["label"] == "基础"
    assert [m["module"] for m in base["merged"]] == ["zz_stats", "zz_formula"]
    assert base["merged_count"] == 3 and base["total_count"] == 5   # 2 own + 3 并入
    assert base["count"] == 2 and base["own_count"] == 2            # verify 口径不变
    stats = _node_of(mods, "zz_stats")
    formula = _node_of(mods, "zz_formula")
    assert stats["merged_into"] == "zz_base" and stats["keep_top_level"] is False
    assert formula["merged_into"] == "zz_base"


def test_entry_merge_sections_grouped_by_source(tmp_path: Path) -> None:
    root = tmp_path
    _make_pack(root, "p_merged", merge=True)
    le = api.list_entries("p_merged", "zz_base", root=root)
    assert le["count"] == 2 and le["total_count"] == 5 and le["merged_count"] == 3
    assert [s["module"] for s in le["merge_sections"]] == ["zz_stats", "zz_formula"]
    assert [s["label"] for s in le["merge_sections"]] == ["属性", "公式"]
    assert le["merge_sections"][0]["entries"][0] == {"id": "hp", "name": "生命"}
    # 直接请求被并入模块 → 仍返回它自己的条目（数据/模块 id 不变），无聚合小节
    own = api.list_entries("p_merged", "zz_stats", root=root)
    assert own["count"] == 2 and own["merge_sections"] == []


def test_empty_pack_without_entry_merge_is_unchanged(tmp_path: Path) -> None:
    """回归：不声明 entry_merge 的包 → 无 merged/merged_into，口径 == 现状。"""
    root = tmp_path
    _make_pack(root, "p_plain", merge=False)
    mods = api.list_modules("p_plain", root=root)
    base = _node_of(mods, "zz_base")
    assert base["merged"] == [] and base["merged_count"] == 0
    assert base["total_count"] == base["count"] == base["own_count"] == 2
    for mid in ("zz_stats", "zz_formula"):
        n = _node_of(mods, mid)
        assert n["merged_into"] is None and n["keep_top_level"] is False
    le = api.list_entries("p_plain", "zz_base", root=root)
    assert le["merge_sections"] == [] and le["total_count"] == le["count"] == 2


def test_entry_merge_unknown_modules_are_ignored_with_note(tmp_path: Path) -> None:
    root = tmp_path
    pkg = _make_pack(root, "p_bad", merge=False)
    _write(pkg / "field_meta.json", {
        "schema_version": 1,
        "entry_merge": {"zz_base": ["ghost"], "not_declared": ["zz_stats"]},
    })
    mods = api.list_modules("p_bad", root=root)
    assert _node_of(mods, "zz_base")["merged"] == []
    notes = " ".join(mods["notes"])
    assert "ghost" in notes and "not_declared" in notes


# =====================================================================================
# A2 · 真写盘：改并入条目 → 写回其所属模块 → 回退
# =====================================================================================
def test_merged_entry_saves_to_own_module_and_rolls_back(tmp_path: Path) -> None:
    root = tmp_path
    shutil.copytree(CONTENT / "veinborn", root / "veinborn")
    stats_file = root / "veinborn" / "stats.json"
    settings_file = root / "veinborn" / "settings.json"
    settings_before = settings_file.read_text(encoding="utf-8")

    assert json.loads(stats_file.read_text(encoding="utf-8"))["hp"]["base"] == 400
    res = editor_ops.save_entry("veinborn", "stats", "hp", {"base": 999}, root=root)
    assert res["ok"] is True, res
    # 真写盘：写进 stats.json（其所属模块），settings.json 一字未动
    assert json.loads(stats_file.read_text(encoding="utf-8"))["hp"]["base"] == 999
    assert settings_file.read_text(encoding="utf-8") == settings_before

    rb = editor_ops.rollback_module("veinborn", "stats", root=root)
    assert rb["ok"] is True, rb
    assert json.loads(stats_file.read_text(encoding="utf-8"))["hp"]["base"] == 400


def test_veinborn_entry_merge_declaration_and_label() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    settings = _node_of(mods, "settings")
    assert settings["label"] == "基础"
    assert [m["module"] for m in settings["merged"]] == ["stats", "formula"]
    assert settings["total_count"] == settings["count"] + settings["merged_count"]
    assert _node_of(mods, "stats")["merged_into"] == "settings"


# =====================================================================================
# B · #12 生活归口（批13 D 起：改由 entry_merge 虚拟聚合视图承载，不再挂 jobs 下）
# =====================================================================================
def test_veinborn_life_modules_aggregated_into_life_view() -> None:
    """批13 D：#12 定案——真正的「生活」归口（entry_merge 虚拟视图），不再挂「职业」下。"""
    mods = api.list_modules("veinborn", root=CONTENT)
    jobs = _node_of(mods, "jobs")
    assert [c["module"] for c in jobs["children"]] == []   # 批12 的 jobs 挂靠已取消
    views = {v["module"]: v for v in mods["views"]}
    assert "life" in views and views["life"]["label"] == "生活"
    assert [m["module"] for m in views["life"]["merged"]] == [
        "proficiency", "enhance", "forge", "recipe"]
    # 四个生活模块被并入视图 → 左栏默认不再单列（前端按 merged_into 判定）
    for child in ("proficiency", "enhance", "forge", "recipe"):
        assert _node_of(mods, child)["merged_into"] == "life"


def test_life_view_entries_grouped_by_source() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    view = next(v for v in mods["views"] if v["module"] == "life")
    assert view["count"] == 0 and view["total_count"] == view["merged_count"]
    le = api.list_entries("veinborn", "life", root=CONTENT)
    assert le["count"] == 0 and le["total_count"] == view["total_count"]
    assert [s["module"] for s in le["merge_sections"]] == [
        "proficiency", "enhance", "forge", "recipe"]


def test_life_modules_have_chinese_labels() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    for mid, label in (("proficiency", "熟练度"), ("enhance", "强化"),
                       ("forge", "锻造"), ("recipe", "配方")):
        assert _node_of(mods, mid)["label"] == label


# =====================================================================================
# C · #3 死亡惩罚货币下拉（展示层引用，候选来自 currencies）
# =====================================================================================
def test_currency_field_declares_options_ref_but_keeps_type_str() -> None:
    from qbot_rpg.content.field_meta import default_field_meta_table
    table = default_field_meta_table()
    settings = table.module("settings")
    assert settings is not None
    dp = settings.fields["death_penalty"]
    currency = dp.children["drop_currency"].element.children["currency"]
    assert currency.options_ref == "settings.currencies" and currency.ref_target is None
    assert currency.type == "str"          # 校验口径不变（存在性仍由专项钩子 R-4 判）


def test_currency_column_renders_ref_with_candidates() -> None:
    det = api.entry_detail("veinborn", "settings", "death_penalty", root=CONTENT)
    dc = next(f for f in det["fields"] if f["key"] == "drop_currency")
    cols = {c["key"]: c for c in dc["columns"]}
    assert cols["currency"]["widget"] == "ref" and cols["currency"]["control"] == "ref"
    assert cols["currency"]["ref_target"] == "settings.currencies"
    opts = api.ref_options("veinborn", "settings.currencies", root=CONTENT)
    assert opts["known"] is True
    assert {o["id"] for o in opts["options"]} == {"coins", "zuanshi"}


def test_selected_currency_is_marked_valid() -> None:
    """选了 currencies 里存在的货币 → 引用校验为真（编辑器不标黄）。"""
    view = api._PackView(CONTENT / "veinborn", api._manifest(CONTENT / "veinborn"))
    assert api._ref_valid(view, "settings.currencies", "coins") is True
    assert api._ref_valid(view, "settings.currencies", "nope") is False


def test_framework_guardrail_no_business_module_names_in_web() -> None:
    """entry_merge / options_ref 机制全在读取层通用实现：web 层不得出现业务模块名。"""
    src = API_PY.read_text(encoding="utf-8")
    # 注意：`formula` 是框架字段类型名（type/widget），不算业务模块名，故不列。
    for name in ("stats", "currencies", "death_penalty", "proficiency",
                 "enhance", "forge", "recipe", "settings"):
        assert f'"{name}"' not in src, f"api.py 写死了业务名：{name}"


# =====================================================================================
# D · #13 字号三档
# =====================================================================================
def _font_js() -> str:
    return _marked("FONT")


def test_font_module_pure_logic() -> None:
    js = _font_js()
    harness = """
    var F = module.exports;
    var out = {};
    out.default = F.normalize(undefined) + "/" + F.normalize("bogus") + "/" + F.normalize("large");
    out.sizes = F.SIZES.join(",");
    out.labels = F.SIZES.map(F.labelOf).join("");
    function Store() { this.m = {}; }
    Store.prototype.getItem = function (k) { return this.m[k] === undefined ? null : this.m[k]; };
    Store.prototype.setItem = function (k, v) { this.m[k] = String(v); };
    Store.prototype.removeItem = function (k) { delete this.m[k]; };
    var s = new Store();
    out.loadDefault = F.loadSize(s);
    F.saveSize(s, "medium");
    out.saved = s.getItem(F.STORE_KEY) + "/" + F.loadSize(s);
    out.hasStored = F.hasStored(s);
    F.clearSize(s);
    out.afterClear = F.loadSize(s) + "/" + F.hasStored(s);
    var el = { attrs: {}, setAttribute: function (k, v) { this.attrs[k] = String(v); } };
    out.applied = F.applySize(el, "large") + "/" + el.attrs["data-fs"];
    out.themeUntouched = el.attrs["data-theme"] === undefined;
    console.log(JSON.stringify(out));
    """
    proc = subprocess.run([NODE, "-e", "var module={exports:{}};\n" + js + "\n" + harness],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["default"] == "small/small/large"
    assert out["sizes"] == "small,medium,large"
    assert out["labels"] == "小中大"
    assert out["loadDefault"] == "small" and out["saved"] == "medium/medium"
    assert out["hasStored"] is True and out["afterClear"] == "small/false"
    assert out["applied"] == "large/large" and out["themeUntouched"] is True


def test_font_tokens_complete_in_all_three_scales() -> None:
    html = _html()
    names = {"--fs-10", "--fs-11", "--fs-12", "--fs-13", "--fs-14", "--fs-16"}
    for scale in ("small", "medium", "large"):
        m = re.search(r'html\[data-fs="%s"\]\s*\{([^}]*)\}' % scale, html)
        assert m, f"缺少 html[data-fs={scale}] 字号档"
        body = m.group(1)
        for tok in names:
            assert re.search(re.escape(tok) + r"\s*:", body), f"{scale} 档缺令牌 {tok}"
    # 只覆盖字号：三档块里不得出现间距 / 行高 / 颜色令牌
    for scale in ("small", "medium", "large"):
        body = re.search(r'html\[data-fs="%s"\]\s*\{([^}]*)\}' % scale, html).group(1)
        assert "--sp-" not in body and "--lh-" not in body and "--bg" not in body


def test_font_panel_and_wiring() -> None:
    html = _html()
    assert 'id="fs-list"' in html and 'id="fs-sec"' in html
    assert html.count('id="fs-list" role="radiogroup"') == 1
    assert "EditorFont.applySize" in html and "EditorFont.saveSize" in html
    assert "qbot.editor.font" in html
    assert "initFont()" in html
    # 顶栏按钮 title 同时说明字号
    assert "字号" in html
    # 与主题正交：applySize 只设 data-fs，不设 data-theme
    font_src = _marked("FONT")
    fn = font_src[font_src.index("function applySize("):font_src.index("function labelOf(")]
    assert 'setAttribute("data-fs"' in fn and "data-theme" not in fn


def test_batch_footer_note_is_current() -> None:
    html = _html()
    m = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert m and "批40 · 实例uid与随机流" in m.group(1)
    assert "批12 · 结构/并入/字号" not in html
