"""编辑器重写批6 · 新增/删除条目 + ID 生成 + 检索（docs/编辑器重写_实现方案.md §四 批6）。

覆盖任务书三件事 + 一致性：
  A. **新增条目（模块级）**：建议 ID（元数据规则优先，否则名称 slug / 前缀+序号）+
     即时唯一性（同模块/同命名空间重复 → 红）+ 其余字段按元数据 default 初始化 +
     落盘复用批2 链路（校验 → 备份 → 原子写 → 回读/回退）。
  B. **删除条目**：二次确认数据面（谁引用了它 → 人话）+ 删除前自动备份 + 被引用黄提示
     （默认不拦）+ 只读身份拒绝。
  C. **检索**：当前模块按名称/ID 过滤；跨模块全局检索（结果按模块分组、点击跳转）；
     纯前端本地过滤（node 实测 EditorEntry）。
  D. **通用性**：全部规则/默认值/引用来自元数据；编辑器代码不写死任何业务模块/字段名。

全部写盘发生在 tmp_path（绝不触碰仓库 content/ 下任何包）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterator

import pytest

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _fn_src(name: str, next_name: str) -> str:
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end].rstrip()
    # 函数之间的注释横幅（// --- / /* */）不算函数体：从尾部起剔除空行与注释行
    lines = src.split("\n")
    while lines:
        tail = lines[-1].strip()
        if tail == "" or tail.startswith("//") or tail.startswith("/*") \
                or tail.startswith("*") or tail.endswith("*/"):
            lines.pop()
            continue
        break
    src = "\n".join(lines)
    assert src.endswith("}"), (name, src[-40:])
    return src


def _js_block(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


# =====================================================================================
# 通用元数据（本测试自建；编辑器元数据驱动，不依赖任何具体内容包）
# =====================================================================================
META = FieldMetaTable(
    modules={
        "widgets": ModuleMeta(entry_type="list", kind="widget", namespace="widget_lib", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
            "count": FieldMeta(type="int", default=5, range_min=0, range_max=5, label="数量"),
            "kind": FieldMeta(type="enum", enum=("x", "y"), label="类别"),
            "next": FieldMeta(type="ref", ref_target="widget", label="后继"),
        }),
        # 与 widgets 同命名空间（kind 不同）：跨模块 ID 唯一性由命名空间约束
        "wparts": ModuleMeta(entry_type="list", kind="wpart", namespace="widget_lib", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
        }),
        "others": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "owner": FieldMeta(type="ref", ref_target="widget", label="归属"),
            "count": FieldMeta(type="int", label="数量"),
        }),
        "stats": ModuleMeta(entry_type="map", kind="stat", value_meta=FieldMeta(
            type="obj", children={
                "name": FieldMeta(type="str", label="名称"),
                "base": FieldMeta(type="int", default=1, label="基准"),
            })),
    },
    namespaces={"widget_lib": ("widgets", "wparts")},
)

WIDGETS = [
    {"id": "a", "name": "甲", "count": 3, "kind": "x"},
    {"id": "b", "name": "乙"},
]
OTHERS = [{"id": "o1", "owner": "a"}, {"id": "o2"}]


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """自建通用内容包（tmp_path）+ 注入本测试的字段元数据表。"""
    pkg = tmp_path / "pack_u"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "U", "version": "1", "schema_version": 1,
        "modules": ["widgets", "wparts", "others", "stats"],
    })
    _write(pkg / "widgets.json", WIDGETS)
    _write(pkg / "wparts.json", [{"id": "p1", "name": "部件"}])
    _write(pkg / "others.json", OTHERS)
    _write(pkg / "stats.json", {"hp": {"name": "生命", "base": 10}})
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    return tmp_path


# =====================================================================================
# A. 元数据维度 + ID 生成规则
# =====================================================================================
def test_module_meta_new_dimensions_are_tail_defaults() -> None:
    mm = ModuleMeta()
    assert mm.id_rule == "" and mm.id_prefix == ""


def test_slugify_only_ascii_no_pinyin() -> None:
    assert api.slugify("Sword Aura") == "sword_aura"
    assert api.slugify("abc-123 / DEF") == "abc_123_def"
    assert api.slugify("御剑·突") == ""       # 中文取不出 slug：不臆造拼音
    assert api.slugify(None) == ""


def test_suggest_entry_id_auto_and_declared_rules() -> None:
    mm = META.module("widgets")
    assert api.suggest_entry_id("widgets", mm, "Sword Aura", set()) == "sword_aura"
    assert api.suggest_entry_id("widgets", mm, "御剑", set()) == "widget_1"   # 前缀=kind
    assert api.suggest_entry_id("widgets", mm, "御剑", {"widget_1", "widget_2"}) == "widget_3"
    # 重复 slug → 追加序号
    assert api.suggest_entry_id("widgets", mm, "Sword Aura", {"sword_aura"}) == "sword_aura_2"
    # 声明 prefix_seq → 一律前缀+序号（即使名称能出 slug）
    seq = ModuleMeta(entry_type="list", id_rule="prefix_seq", id_prefix="fx")
    assert api.suggest_entry_id("m", seq, "Sword Aura", set()) == "fx_1"
    # 声明 slug → 名称优先；取不出 slug 仍回退序号
    slug = ModuleMeta(entry_type="list", id_rule="slug", id_prefix="fx")
    assert api.suggest_entry_id("m", slug, "Sword Aura", set()) == "sword_aura"
    assert api.suggest_entry_id("m", slug, "御剑", set()) == "fx_1"


def test_id_rule_spec_declared_vs_auto() -> None:
    auto = api.id_rule_spec("widgets", META.module("widgets"))
    assert auto["rule"] == api.ID_RULE_AUTO and auto["declared"] is False
    assert auto["prefix"] == "widget"
    dec = api.id_rule_spec("m", ModuleMeta(id_rule="slug", id_prefix="FX"))
    assert dec["rule"] == "slug" and dec["declared"] is True
    assert dec["prefix"] == "fx"   # 前缀 slug 归一
    # 不认识的规则 → 自动（不臆造行为）
    bad = api.id_rule_spec("m", ModuleMeta(id_rule="nope"))
    assert bad["rule"] == api.ID_RULE_AUTO


# =====================================================================================
# B. 新增条目：新建界面数据 + 即时唯一性 + 落盘
# =====================================================================================
def test_new_entry_detail_defaults_and_id_separate(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_u", "widgets", root=pack_root, name="Sword Aura")
    assert d["is_new"] is True and d["suggested_id"] == "sword_aura"
    assert d["id_field"] == "id" and d["id_field_label"] == "标识"
    # ID 单独渲染：字段网格里不重复出 id
    assert all(f["key"] != "id" for f in d["fields"])
    keys = [f["key"] for f in d["fields"]]
    assert keys[0] == "name"
    # 元数据 default 初始化：count 默认 5 → present=True / value=5
    count = next(f for f in d["fields"] if f["key"] == "count")
    assert count["present"] is True and count["value"] == 5
    assert d["field_count"] == len(d["fields"]) and d["group_count"] >= 1
    assert d["id_hint"] and "互相引用" in d["id_hint"]
    assert d["id_rule"]["rule"] == api.ID_RULE_AUTO
    # 引用字段在新建表单里同样是引用控件（值非法 → 前端黄提示、不红拦）
    nxt = next(f for f in d["fields"] if f["key"] == "next")
    assert nxt["control"] == "ref" and nxt["ref_target"] == "widget"
    assert nxt["ref_valid"] is True


def test_new_entry_detail_chinese_name_falls_back_to_seq(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_u", "widgets", root=pack_root, name="御剑")
    assert d["suggested_id"] == "widget_1"


def test_check_entry_id_paths(pack_root: Path) -> None:
    ok_ = api.check_entry_id("pack_u", "widgets", "brand_new", root=pack_root)
    assert ok_["ok"] and ok_["status"] == "ok"
    empty = api.check_entry_id("pack_u", "widgets", "  ", root=pack_root)
    assert not empty["ok"] and empty["level"] == "red"
    bad = api.check_entry_id("pack_u", "widgets", "a b/c", root=pack_root)
    assert not bad["ok"]
    dup = api.check_entry_id("pack_u", "widgets", "a", root=pack_root)
    assert not dup["ok"] and dup["conflicts"][0]["module"] == "widgets"
    # 同命名空间兄弟模块重复 → 红（校验器 R-5 口径一致）
    ns = api.check_entry_id("pack_u", "widgets", "p1", root=pack_root)
    assert not ns["ok"] and ns["conflicts"][0]["module"] == "wparts"
    assert ns["how_to_fix"]


def test_create_entry_writes_defaults_and_backup(pack_root: Path) -> None:
    res = editor_ops.create_entry("pack_u", "widgets", "sword_aura",
                                  {"name": "新剑"}, root=pack_root, role="owner", meta=META)
    assert res["ok"] is True and res["written"] == ["widgets"]
    assert res["backup"]["exists"] is True
    data = _read(pack_root / "pack_u" / "widgets.json")
    new = next(e for e in data if e["id"] == "sword_aura")
    assert new["name"] == "新剑" and new["count"] == 5   # 默认值初始化
    assert _read(pack_root / "pack_u" / "widgets.json.bak") == WIDGETS  # 备份=写前那一份
    assert not (pack_root / "pack_u" / "widgets.json.tmp").exists()


def test_create_entry_duplicate_is_red_and_no_write(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    res = editor_ops.create_entry("pack_u", "widgets", "a", {}, root=pack_root,
                                  role="owner", meta=META)
    assert res["ok"] is False and res["level"] == "red"
    assert res["errors"][0]["code"] == "id_invalid"
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before
    assert not (pack_root / "pack_u" / "widgets.json.bak").exists()


def test_create_entry_validation_red_blocks_write(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    res = editor_ops.create_entry("pack_u", "widgets", "zzz", {"kind": "not_in_enum"},
                                  root=pack_root, role="owner", meta=META)
    assert res["ok"] is False and res["level"] == "red" and res["written"] == []
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


def test_create_entry_unknown_field_rejected(pack_root: Path) -> None:
    with pytest.raises(api.BadRequest):
        editor_ops.create_entry("pack_u", "widgets", "zzz", {"no_such": 1},
                                root=pack_root, role="owner", meta=META)
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS


def test_create_entry_readonly_forbidden(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    with pytest.raises(api.Forbidden):
        editor_ops.create_entry("pack_u", "widgets", "zzz", {}, root=pack_root,
                                role="gm", meta=META)
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


def test_create_entry_rollback_restores(pack_root: Path) -> None:
    editor_ops.create_entry("pack_u", "widgets", "sword_aura", {}, root=pack_root,
                            role="owner", meta=META)
    res = editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    assert res["ok"] is True
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS


def test_create_entry_map_module(pack_root: Path) -> None:
    res = editor_ops.create_entry("pack_u", "stats", "mp", {"name": "法力"},
                                  root=pack_root, role="owner", meta=META)
    assert res["ok"] is True and res["written"] == ["stats"]
    stats = _read(pack_root / "pack_u" / "stats.json")
    assert stats["mp"] == {"name": "法力", "base": 1}   # 默认值 base=1
    assert stats["hp"]["base"] == 10


# =====================================================================================
# C. 删除条目：被引用扫描（人话）+ 默认不拦 + 备份/回退
# =====================================================================================
def test_reference_scan_finds_typed_refs(pack_root: Path) -> None:
    refs = api.reference_scan("pack_u", "widgets", "a", root=pack_root, meta=META)
    assert len(refs) == 1
    r = refs[0]
    assert r["module"] == "others" and r["entry_id"] == "o1"
    assert r["field"] == "owner" and r["field_label"] == "归属"
    assert r["module_label"] and r["entry_name"]


def test_reference_scan_empty_for_unreferenced(pack_root: Path) -> None:
    assert api.reference_scan("pack_u", "widgets", "b", root=pack_root, meta=META) == []


def test_delete_entry_referenced_is_yellow_not_blocked(pack_root: Path) -> None:
    res = editor_ops.delete_entry("pack_u", "widgets", "a", root=pack_root,
                                  role="owner", meta=META)
    assert res["ok"] is True and res["level"] == "yellow"
    assert res["referrers"] and res["referrers"][0]["entry_id"] == "o1"
    assert any(w["code"] == "entry_referenced" for w in res["warnings"])
    assert res["backup"]["exists"] is True
    data = _read(pack_root / "pack_u" / "widgets.json")
    assert [e["id"] for e in data] == ["b"]
    # 引用者条目原样保留（悬空引用由黄提示告知，不自动改别人的数据）
    assert _read(pack_root / "pack_u" / "others.json") == OTHERS
    assert _read(pack_root / "pack_u" / "widgets.json.bak") == WIDGETS


def test_delete_entry_then_rollback_restores(pack_root: Path) -> None:
    editor_ops.delete_entry("pack_u", "widgets", "a", root=pack_root, role="owner", meta=META)
    res = editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    assert res["ok"] is True
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS


def test_delete_entry_unreferenced_is_ok(pack_root: Path) -> None:
    res = editor_ops.delete_entry("pack_u", "widgets", "b", root=pack_root,
                                  role="owner", meta=META)
    assert res["ok"] is True and res["level"] == "ok" and res["referrers"] == []


def test_delete_entry_readonly_forbidden(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    with pytest.raises(api.Forbidden):
        editor_ops.delete_entry("pack_u", "widgets", "a", root=pack_root, role="gm", meta=META)
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


def test_delete_entry_missing_is_not_found(pack_root: Path) -> None:
    with pytest.raises(api.NotFound):
        editor_ops.delete_entry("pack_u", "widgets", "ghost", root=pack_root,
                                role="owner", meta=META)


def test_delete_entry_blocking_red_does_not_write(
        pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """非「指向被删条目的引用缺失」的红拦仍必须阻断删除（零落盘）。"""
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()

    def _fake_check(modules: Any, meta: Any = None) -> Any:
        return SimpleNamespace(ok=False, warnings=[], errors=[
            SimpleNamespace(module="widgets", field="widgets.0.name", kind="R-1", detail={})])

    monkeypatch.setattr(editor_ops, "check_pack", _fake_check)
    res = editor_ops.delete_entry("pack_u", "widgets", "a", root=pack_root,
                                  role="owner", meta=META)
    assert res["ok"] is False and res["level"] == "red"
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before
    assert not (pack_root / "pack_u" / "widgets.json.bak").exists()


def test_delete_entry_write_failure_no_fake_success(
        pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    monkeypatch.setattr(atomic_store, "write_modules",
                        lambda *a, **k: {"ok": False, "errors": [
                            {"level": "red", "code": "write_failed", "message": "模拟失败"}]})
    res = editor_ops.delete_entry("pack_u", "widgets", "a", root=pack_root,
                                  role="owner", meta=META)
    assert res["ok"] is False and "写入失败" in res["message"]
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


# =====================================================================================
# D. 检索：全包索引（跨模块）
# =====================================================================================
def test_entry_index_groups_by_module(pack_root: Path) -> None:
    idx = api.entry_index("pack_u", root=pack_root)
    by = {m["module"]: m for m in idx["modules"]}
    assert set(by) == {"widgets", "wparts", "others", "stats"}
    assert by["widgets"]["count"] == 2 and by["widgets"]["entries"][0]["name"] == "甲"
    assert by["widgets"]["namespace"] == "widget_lib"
    assert by["stats"]["entry_type"] == "map"
    assert idx["total"] == 2 + 1 + 2 + 1
    assert idx["meta_source"]


def test_suggest_id_endpoint_data(pack_root: Path) -> None:
    out = api.suggest_id("pack_u", "widgets", root=pack_root, name="Sword Aura")
    assert out["suggested_id"] == "sword_aura" and out["id_hint"]
    out2 = api.suggest_id("pack_u", "widgets", root=pack_root, name="Sword Aura")
    assert out2["suggested_id"] == "sword_aura"   # 只读，不落盘、不占用


# =====================================================================================
# E. 前端：EditorEntry 纯逻辑（node 实测）
# =====================================================================================
_ENTRY_HARNESS = r"""
var module = { exports: {} };
__ENTRY_SRC__
var EditorEntry = module.exports;
var index = {
  modules: [
    { module: "widgets", label: "组件", namespace: "widget_lib",
      entries: [{ id: "a", name: "甲" }, { id: "sword_aura", name: "Sword Aura" },
                { id: "w9", name: "丙" }] },
    { module: "wparts", label: "部件", namespace: "widget_lib",
      entries: [{ id: "p1", name: "部件" }, { id: "w1", name: "Sword Part" }] },
    { module: "others", label: "其他", namespace: "others",
      entries: [{ id: "o1", name: "归属者" }] }
  ]
};
var out = {};
out.filterEmpty = EditorEntry.filterEntries([{ id: "a", name: "甲" }], "");
out.filterName = EditorEntry.filterEntries(index.modules[0].entries, "sword");
out.filterId = EditorEntry.filterEntries(index.modules[0].entries, "p1");
out.filterIdHit = EditorEntry.filterEntries(index.modules[0].entries, "w9")
  .map(function (e) { return e.id; });
out.filterNameHit = EditorEntry.filterEntries(index.modules[0].entries, "丙")
  .map(function (e) { return e.id; });
out.search = EditorEntry.searchIndex(index, "部").map(function (g) {
  return { module: g.module, ids: g.entries.map(function (e) { return e.id; }) };
});
out.searchMulti = EditorEntry.searchIndex(index, "sword").map(function (g) {
  return { module: g.module, ids: g.entries.map(function (e) { return e.id; }) };
});
out.searchByName = EditorEntry.searchIndex(index, "归属").map(function (g) { return g.module; });
out.searchEmpty = EditorEntry.searchIndex(index, "  ");
out.count = EditorEntry.searchCount(EditorEntry.searchIndex(index, "sword"));
out.idOk = EditorEntry.idStatus("fresh", "widgets", index);
out.idDup = EditorEntry.idStatus("sword_aura", "widgets", index);
out.idNs = EditorEntry.idStatus("p1", "widgets", index);
out.idOther = EditorEntry.idStatus("o1", "widgets", index);
out.idEmpty = EditorEntry.idStatus("  ", "widgets", index);
out.idBad = EditorEntry.idStatus("a b/c", "widgets", index);
out.ruleAuto = EditorEntry.ruleText("", "widget");
out.ruleSeq = EditorEntry.ruleText("prefix_seq", "widget");
out.refText = EditorEntry.referrerText({ module_label: "其他", module: "others",
  entry_name: "归属者", entry_id: "o1", field_label: "归属", field: "owner" });
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def entry_js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批6 前端语义执行")
    script = tmp_path_factory.mktemp("b6js") / "entry.js"
    script.write_text(_ENTRY_HARNESS.replace("__ENTRY_SRC__", _js_block("EDITOR_ENTRY")),
                      encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True, check=False)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_js_filter_current_module_by_name_and_id(entry_js: Dict[str, Any]) -> None:
    assert [e["id"] for e in entry_js["filterEmpty"]] == ["a"]
    assert [e["id"] for e in entry_js["filterName"]] == ["sword_aura"]
    assert entry_js["filterId"] == []          # p1 不在 widgets
    assert entry_js["filterIdHit"] == ["w9"]   # 按 ID 命中
    assert entry_js["filterNameHit"] == ["w9"]  # 按名称命中


def test_js_global_search_grouped_by_module(entry_js: Dict[str, Any]) -> None:
    assert entry_js["search"] == [{"module": "wparts", "ids": ["p1"]}]
    # 跨模块：同一关键词命中两个模块 → 分组顺序按索引模块顺序
    assert entry_js["searchMulti"] == [{"module": "widgets", "ids": ["sword_aura"]},
                                       {"module": "wparts", "ids": ["w1"]}]
    assert entry_js["searchByName"] == ["others"]
    assert entry_js["searchEmpty"] == []
    assert entry_js["count"] == 2


def test_js_id_status_instant_uniqueness(entry_js: Dict[str, Any]) -> None:
    assert entry_js["idOk"]["ok"] is True
    assert entry_js["idDup"]["ok"] is False and "占用" in entry_js["idDup"]["message"]
    # 同命名空间兄弟模块（wparts）重复 → 红
    assert entry_js["idNs"]["ok"] is False and entry_js["idNs"]["level"] == "red"
    # 不同命名空间同名 → 不冲突
    assert entry_js["idOther"]["ok"] is True
    assert entry_js["idEmpty"]["ok"] is False
    assert entry_js["idBad"]["ok"] is False


def test_js_human_wording(entry_js: Dict[str, Any]) -> None:
    assert "slug" in entry_js["ruleAuto"] and "widget" in entry_js["ruleAuto"]
    assert "widget_1" in entry_js["ruleSeq"]
    assert entry_js["refText"] == "其他「归属者」的「归属」引用了它"


# =====================================================================================
# F. 前端接线 + 通用性护栏
# =====================================================================================
def test_frontend_new_and_delete_wiring() -> None:
    html = _html()
    for token in ("function openNewEntry", "function renderNewEntry", "function createEntry",
                  "function bindNewIdent", "function updateNewIdStatus", "function deleteEntry",
                  "function loadEntryIndex", "function refreshAfterMutation",
                  "function renderGlobalResults", "EDITOR_ENTRY_BEGIN", "EDITOR_ENTRY_END"):
        assert token in html, token
    assert 'id="btn-new"' in html and "+ 新建条目" in html
    assert 'id="btn-delete"' in html and "删除条目" in html
    assert 'id="new-id"' in html and "按名称生成" in html
    assert 'id="gfilter"' in html
    # 中栏本地过滤作用域写清（当前模块 + 名称/ID）
    assert "过滤当前模块（按名称/ID）" in html
    # 二次确认人话：删哪个 / 不可撤销 / 可回退
    dele = _fn_src("deleteEntry", "selectEntry")
    assert "不可撤销" in dele and "回退到上一份备份" in dele and "window.confirm" in dele
    assert "EditorEntry.referrerText" in dele
    # 新建：即时唯一性 + 提示语（ID 区渲染在 newIdentHtml；字段网格在 renderNewEntry）
    newf = _fn_src("newIdentHtml", "renderNewEntry")
    patch = _fn_src("renderNewEntry", "bindNewIdent")
    assert "EditorEntry.ruleText" in newf and "id_hint" in newf
    assert "EditorDraft.newDraft()" in patch


def test_frontend_readonly_disables_new_and_delete() -> None:
    md = _fn_src("markDirty", "discardDraft")
    assert 'el("btn-new").disabled' in md and 'el("btn-delete").disabled' in md
    assert "state.editable" in md
    # 只读身份下新建入口直接拒绝（不依赖按钮置灰）
    op = _fn_src("openNewEntry", "newIdentHtml")
    assert "只读预览" in op


def test_frontend_new_draft_isolated_from_main_draft() -> None:
    # 新建态用独立草稿（state.newDraft），退出/保存后主草稿指针还原
    dd = _fn_src("discardDraft", "canLeave")
    assert "state.newDraft" in dd and "MAIN_CTX.draft = draft" in dd
    rd = _fn_src("renderDetail", "assocPaneHtml")
    assert "MAIN_CTX.draft = draft" in rd and "state.newEntry = null" in rd


def test_frontend_mutation_result_survives_reselection() -> None:
    """新建/删除结果（含被引用者黄提示）切选后仍展示：refreshAfterMutation 回填 keepResult。"""
    ref = _fn_src("refreshAfterMutation", "openNewEntry")
    assert "keepResult" in ref and "state.result = keepResult" in ref
    assert "renderResult(keepResult)" in ref
    create = _fn_src("createEntry", "deleteEntry")
    dele = _fn_src("deleteEntry", "selectEntry")
    assert "refreshAfterMutation(eid, res)" in create
    assert "refreshAfterMutation(null, res)" in dele
    # 删空模块时仍要有结果容器，否则黄提示无处显示
    entries = _fn_src("loadEntries", "renderEntries")
    assert 'id="result"' in entries


def test_frontend_css_tokens_for_batch6() -> None:
    html = _html()
    for token in (".newid", ".gsec", ".newbtn", ".nid-st.red", ".item .idtag"):
        assert token in html, token


def test_framework_files_have_no_pack_business_names() -> None:
    """批6 新增的编辑器逻辑不得写死任何内容包模块名/字段名（元数据声明除外）。"""
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "editor_ops.py",
                 REPO / "qbot_rpg" / "web" / "static" / "index.html",
                 REPO / "qbot_rpg" / "content" / "models.py",
                 REPO / "scripts" / "editor_host.py"):
        text = path.read_text(encoding="utf-8")
        for word in ("veinborn", "test_demo"):
            assert word not in text, f"{path} 写死：{word}"


def test_gridwork_new_functions_have_no_business_literals() -> None:
    """新增函数体内不得出现具体业务模块名/字段名（通用性护栏；CSS 类名如 .item 不算）。"""
    banned = ('"skills"', '"items"', '"enemies"', '"equipment"', '"quest"',
              "'skills'", "'items'", "'enemies'")
    for name, nxt in (("openNewEntry", "newIdentHtml"), ("createEntry", "deleteEntry"),
                      ("renderNewEntry", "bindNewIdent"), ("deleteEntry", "selectEntry"),
                      ("renderGlobalResults", "loadEntryIndex")):
        body = _fn_src(name, nxt)
        for word in banned:
            assert word not in body, (name, word)


# =====================================================================================
# G. HTTP 端点（宿主）：entry-index / new / suggest_id / id_check / create / refs / delete
# =====================================================================================
_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _http_pack(tmp_path: Path) -> Path:
    pkg = tmp_path / "http_pack"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "H", "version": "1", "schema_version": 1,
        "modules": ["widgets", "wparts", "others", "stats"],
    })
    _write(pkg / "widgets.json", WIDGETS)
    _write(pkg / "wparts.json", [{"id": "p1"}])
    _write(pkg / "others.json", OTHERS)
    _write(pkg / "stats.json", {"hp": {"name": "生命", "base": 10}})
    return tmp_path


@pytest.fixture()
def http_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    import qbot_rpg.content.validator as validator_mod
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    monkeypatch.setattr(validator_mod, "default_field_meta_table", lambda: META)
    from editor_host import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(pack="http_pack", root=str(_http_pack(tmp_path)),
                               role="owner")) as client:
        yield client


def test_http_entry_index_and_new_and_suggest(http_client: Any) -> None:
    idx = http_client.get("/api/pack/http_pack/entry-index").json()
    assert idx["total"] == 6
    new = http_client.get("/api/pack/http_pack/module/widgets/new?name=Sword%20Aura").json()
    assert new["suggested_id"] == "sword_aura" and new["is_new"] is True
    assert all(f["key"] != "id" for f in new["fields"])
    sug = http_client.get("/api/pack/http_pack/module/widgets/suggest_id?name=Sword%20Aura").json()
    assert sug["suggested_id"] == "sword_aura"


def test_http_id_check_and_create_and_refs_and_delete(http_client: Any, tmp_path: Path) -> None:
    pk = tmp_path / "http_pack"
    chk = http_client.post("/api/pack/http_pack/module/widgets/id_check",
                           json={"entry_id": "a"}).json()
    assert chk["ok"] is False and chk["status"] == "red"
    ok = http_client.post("/api/pack/http_pack/module/widgets/id_check",
                          json={"entry_id": "sword_aura"}).json()
    assert ok["ok"] is True

    created = http_client.post("/api/pack/http_pack/module/widgets/entry",
                               json={"entry_id": "sword_aura", "patch": {"name": "新剑"}}).json()
    assert created["ok"] is True and created["written"] == ["widgets"]
    assert any(e["id"] == "sword_aura" for e in _read(pk / "widgets.json"))

    refs = http_client.get("/api/pack/http_pack/entry/widgets/a/refs").json()
    assert refs["referrers"][0]["entry_id"] == "o1"

    deleted = http_client.post("/api/pack/http_pack/entry/widgets/a/delete", json={}).json()
    assert deleted["ok"] is True and deleted["referrers"]
    assert not any(e["id"] == "a" for e in _read(pk / "widgets.json"))


def test_http_create_delete_readonly_forbidden(http_client: Any, tmp_path: Path) -> None:
    pk = tmp_path / "http_pack"
    http_client.post("/api/session/role", json={"role": "gm"})
    before = (pk / "widgets.json").read_bytes()
    r1 = http_client.post("/api/pack/http_pack/module/widgets/entry",
                          json={"entry_id": "zzz", "patch": {}})
    assert r1.status_code == 403 and r1.json()["kind"] == "Forbidden"
    r2 = http_client.post("/api/pack/http_pack/entry/widgets/a/delete", json={})
    assert r2.status_code == 403
    assert (pk / "widgets.json").read_bytes() == before


def test_http_id_check_missing_module_is_404(http_client: Any) -> None:
    r = http_client.post("/api/pack/http_pack/module/nope/id_check", json={"entry_id": "x"})
    assert r.status_code == 404
