"""编辑器重写批4 · 列表型与引用型字段（可增删行表格 + 引用选择器）。

覆盖任务书：
  · 列表列 = 元素字段元数据（element/children）；无元数据按值推断；列名走「中文名 + 原始键」；
  · 新增行按元素元数据 default 初始化；行尾删除 + 「+ 添加一行」；
  · 列表改动只写草稿（node 执行纯 JS EditorList 验证增/删/改与未保存计数联动）；
  · 引用字段（ref）与引用列表（元素为 ref 的 list）两种形态；可搜索候选、显示名称；
    值不在候选内 → 黄提示（EditorRef.status warn），不红拦编辑；
  · 嵌套值（列表/对象/引用多选）走批2 保存链：草稿 → 校验 → 原子写 + 备份 + 回退。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

META = FieldMetaTable(modules={
    "widgets": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "owner": FieldMeta(type="ref", ref_target="widgets", label="归属"),
        # 标量元素列表（元素无 label → 列名用兜底「值」）
        "tags": FieldMeta(type="list", label="标签", element=FieldMeta(type="str")),
        # 引用元素列表（多选形态 reflist）
        "members": FieldMeta(type="list", label="成员",
                             element=FieldMeta(type="ref", ref_target="widgets")),
        # 对象元素列表（列 = children 元数据；default 用于新行初始化）
        "steps": FieldMeta(type="list", label="步骤", element=FieldMeta(type="obj", children={
            "kind": FieldMeta(type="enum", enum=("a", "b"), label="类别"),
            "amt": FieldMeta(type="int", default=3, range_min=0, range_max=10, label="数量"),
            "ref": FieldMeta(type="ref", ref_target="widgets", label="指向"),
        })),
        # 无元素元数据（列按值推断）
        "loose": FieldMeta(type="list", label="自由行"),
        # 元素声明为 obj 但未声明子字段（列只能按值推断；无值则不出列）
        "blobs": FieldMeta(type="list", label="未声明子字段的对象列表",
                            element=FieldMeta(type="obj")),
    }),
})

ORIGINAL = [
    {
        "id": "a", "name": "甲", "owner": "a",
        "tags": ["x", "y"],
        "members": ["a", "b"],
        "steps": [{"kind": "a", "amt": 1, "ref": "a"}],
        "loose": [{"p": 1, "q": "z"}],
        "blobs": [{"k": 1}],
    },
    {"id": "b", "name": "乙", "owner": "b"},
    {
        "id": "c", "name": "丙",
        "steps": [{"kind": "b", "amt": 2, "ref": "b"}],
    },
]


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """自建通用内容包（tmp_path）并注入本测试的字段元数据表（编辑器零业务依赖）。"""
    pkg = tmp_path / "pack_l"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "L", "version": "1", "schema_version": 1, "modules": ["widgets"],
    }, ensure_ascii=False), encoding="utf-8")
    _write(pkg / "widgets.json", ORIGINAL)
    monkeypatch.setattr(api, "_META_TABLE", META)
    return tmp_path


def _detail(root: Path, entry_id: str = "a") -> Dict[str, Any]:
    return api.entry_detail("pack_l", "widgets", entry_id, root=root)


def _fields(root: Path, entry_id: str = "a") -> Dict[str, Dict[str, Any]]:
    return {f["key"]: f for f in _detail(root, entry_id)["fields"]}


def _save(root: Path, entry_id: str, patch: Dict[str, Any],
          role: str = "owner") -> Dict[str, Any]:
    return editor_ops.save_entry("pack_l", "widgets", entry_id, patch,
                                 root=root, role=role, meta=META)


def _validate(root: Path, entry_id: str, patch: Dict[str, Any]) -> Dict[str, Any]:
    return editor_ops.validate_entry("pack_l", "widgets", entry_id, patch,
                                     root=root, meta=META)


# =====================================================================================
# 一、列表列的元数据来源（element/children 优先；无元数据按值推断）
# =====================================================================================
def test_list_control_by_element_kind() -> None:
    assert api.list_control(FieldMeta(type="list", element=FieldMeta(type="str"))) == "listtable"
    assert api.list_control(FieldMeta(type="list", element=FieldMeta(type="obj"))) == "listtable"
    assert api.list_control(FieldMeta(type="list",
                                      element=FieldMeta(type="ref"))) == "reflist"
    assert api.list_control(FieldMeta(type="list")) == "listtable"
    assert api.list_control(None) == "listtable"


def test_list_descriptor_control_and_scalar_flag(pack_root: Path) -> None:
    f = _fields(pack_root)
    assert f["steps"]["control"] == "listtable" and f["steps"]["scalar_element"] is False
    assert f["tags"]["control"] == "listtable" and f["tags"]["scalar_element"] is True
    assert f["members"]["control"] == "reflist" and f["members"]["scalar_element"] is True
    # 引用多选的候选目标来自元素元数据（不是外层 list 字段的 ref_target）
    assert f["members"]["ref_target"] == "widgets"
    # 无元素元数据：按实际行形态推断（对象行 → 非标量）
    assert f["loose"]["control"] == "listtable" and f["loose"]["scalar_element"] is False
    # 全部 list 本批可编辑
    assert all(f[k]["editable"] is True for k in ("steps", "tags", "members", "loose"))


def test_object_element_columns_come_from_children_metadata(pack_root: Path) -> None:
    cols = _fields(pack_root)["steps"]["columns"]
    assert [c["key"] for c in cols] == ["kind", "amt", "ref"]
    by = {c["key"]: c for c in cols}
    assert by["kind"]["label"] == "类别" and by["kind"]["type"] == "enum"
    assert by["kind"]["control"] == "select" and by["kind"]["enum"] == ["a", "b"]
    assert by["amt"]["label"] == "数量" and by["amt"]["control"] == "number"
    assert by["amt"]["default"] == 3
    assert by["ref"]["type"] == "ref" and by["ref"]["control"] == "ref"
    assert by["ref"]["ref_target"] == "widgets"


def test_scalar_element_yields_single_value_column(pack_root: Path) -> None:
    cols = _fields(pack_root)["tags"]["columns"]
    assert len(cols) == 1
    assert cols[0]["key"] == "value" and cols[0]["type"] == "str"
    assert cols[0]["control"] == "text"


def test_columns_without_metadata_inferred_from_values(pack_root: Path) -> None:
    cols = {c["key"]: c for c in _fields(pack_root)["loose"]["columns"]}
    assert set(cols) == {"p", "q"}          # 列按实际行的键推断（现状兜底）
    # 批4.6 补：无元数据列也按实际值推断控件（p=1 数值 → number；q="z" 文本 → text）
    assert cols["p"]["control"] == "number" and cols["q"]["control"] == "text"
    assert cols["p"]["type"] == "int" and cols["q"]["type"] == "str"
    assert cols["p"]["help_card"]["type"] == "数值（整数）"
    assert cols["q"]["help_card"]["type"] == "文本"


def test_row_default_from_element_metadata(pack_root: Path) -> None:
    f = _fields(pack_root)
    # obj 元素：仅把声明了 default 的子字段写进新行（未声明的保持「未填」）
    assert f["steps"]["row_default"] == {"amt": 3}
    # 标量元素未声明 default / 无元数据 → 无默认（前端按空值处理）
    assert f["tags"]["row_default"] is None
    assert f["loose"]["row_default"] is None


def test_obj_element_without_declared_children_columns(pack_root: Path) -> None:
    # 有数据行 → 列按值推断（现状兜底）
    assert [c["key"] for c in _fields(pack_root, "a")["blobs"]["columns"]] == ["k"]
    # 无数据行且未声明子字段 → 不出列（前端提示补元数据），不臆造 value 键
    f = _fields(pack_root, "b")["blobs"]
    assert f["control"] == "listtable" and f["columns"] == []


# =====================================================================================
# 二、引用值存在性：非法 → 黄提示数据（ref_valid / invalid_refs / invalid_cells）
# =====================================================================================
def test_scalar_ref_validity_flags(pack_root: Path) -> None:
    # 基线数据全部合法 → ref_valid=True
    assert _fields(pack_root, "a")["owner"]["ref_valid"] is True
    # 把某条目的标量引用改成一个不存在的目标（只读重画，用于标记测试）
    data = _read(pack_root / "pack_l" / "widgets.json")
    data[1]["owner"] = "ghost"
    _write(pack_root / "pack_l" / "widgets.json", data)
    api._read_json_cached.cache_clear()  # 同一 mtime 刻度内改写：显式失效读取缓存
    # b 的 owner 指向不存在的目标 → 前端据此标黄（保存校验仍由现有校验器决定）
    assert _fields(pack_root, "b")["owner"]["ref_valid"] is False


def test_ref_list_and_cells_invalid_marks(pack_root: Path) -> None:
    data = _read(pack_root / "pack_l" / "widgets.json")
    data[0]["members"] = ["a", "ghost"]                 # 引用列表内的非法值
    data[2]["steps"][0]["ref"] = "ghost"                # 对象行内引用子字段非法
    _write(pack_root / "pack_l" / "widgets.json", data)
    f = _fields(pack_root, "a")
    assert f["members"]["invalid_refs"] == ["ghost"]
    c = _fields(pack_root, "c")["steps"]["invalid_cells"]
    assert c == [{"row": 0, "key": "ref", "value": "ghost"}]


# =====================================================================================
# 三、纯 JS：可增删行表格 / 引用选择器（node 直接执行标记块）
# =====================================================================================
def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    m = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert m, f"index.html 缺少标记块 {begin} … {end}"
    return m.group(1)


_NODE_HARNESS = r"""
const L = require(process.argv[1]);
const R = require(process.argv[2]);
const D = require(process.argv[3]);
const out = {};
// ---- 可增删行表格 ----
let rows = L.addRow([], {amt: 3}, false);          // obj 元素：default 初始化新行
out.addObj = rows;
out.setObj = L.setCell(rows, 0, "amt", 7, false);   // 行内改值
out.delObj = L.delRow(L.addRow(rows, {amt: 3}, false), 0);
out.delOutOfRange = L.delRow(rows, 9);
out.addScalarNone = L.addRow([], null, true);       // 标量元素无 default → 空串
out.setScalar = L.setCell(["x"], 0, "value", "y", true);
out.cellScalar = L.cellValue("v", "value", true);
out.cellObj = L.cellValue({k: 1}, "k", false);
// ---- 草稿联动（批2 未保存计数）----
const base = [{"kind": "a", "amt": 1}];
const draft = D.newDraft();
const added = L.addRow(base, {amt: 3}, false);
D.set(draft, "steps", added, base);
out.draftCountAfterAdd = D.count(draft);
out.draftDirty = D.dirty(draft);
out.draftPatch = D.patch(draft);
D.set(draft, "steps", base, base);                  // 删回原值 → 撤销
out.draftCountRevert = D.count(draft);
const draft2 = D.newDraft();
D.set(draft2, "steps", L.delRow(base, 0), base);    // 删行入草稿
out.draftDel = D.patch(draft2);
// ---- 引用选择器 ----
out.addRef = R.addRef(["a"], "b");
out.addRefDup = R.addRef(["a"], "a");
out.delRef = R.delRef(["a", "b"], "a");
out.statusIn = R.status("a", [{id: "a", name: "甲"}], true);
out.statusMissing = R.status("ghost", [{id: "a", name: "甲"}], true);
out.statusNoTarget = R.status("a", [], false);
out.statusLoading = R.status("a", [], undefined);
out.filter = R.filter([{id: "aa", name: "甲"}, {id: "bb", name: "乙"}], "乙");
out.label = R.label("a", [{id: "a", name: "甲"}]);
out.labelUnknown = R.label("zz", [{id: "a", name: "甲"}]);
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 列表/引用语义执行")
def test_list_and_ref_js_semantics(tmp_path: Path) -> None:
    list_src = tmp_path / "list.js"
    list_src.write_text(_marked_block("/* EDITOR_LIST_BEGIN */", "/* EDITOR_LIST_END */"),
                        encoding="utf-8")
    ref_src = tmp_path / "ref.js"
    ref_src.write_text(_marked_block("/* EDITOR_REF_BEGIN */", "/* EDITOR_REF_END */"),
                       encoding="utf-8")
    draft_src = tmp_path / "draft.js"
    draft_src.write_text(_marked_block("/* EDITOR_DRAFT_BEGIN */", "/* EDITOR_DRAFT_END */"),
                         encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _NODE_HARNESS, str(list_src), str(ref_src), str(draft_src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)

    # 增行（默认值初始化）/ 改值 / 删行
    assert out["addObj"] == [{"amt": 3}]
    assert out["setObj"] == [{"amt": 7}]
    assert out["delObj"] == [{"amt": 3}]             # [x,x] 删首行 → [x]
    assert out["delOutOfRange"] == [{"amt": 3}]      # 越界删除不改动
    assert out["addScalarNone"] == [""]
    assert out["setScalar"] == ["y"]
    assert out["cellScalar"] == "v" and out["cellObj"] == 1
    # 改动进草稿、未保存计数联动、改回原值即撤销
    assert out["draftCountAfterAdd"] == 1 and out["draftDirty"] is True
    assert out["draftPatch"] == {"steps": [{"kind": "a", "amt": 1}, {"amt": 3}]}
    assert out["draftCountRevert"] == 0
    assert out["draftDel"] == {"steps": []}
    # 引用多选：去重加入 / 按标识移除 / 黄提示
    assert out["addRef"] == ["a", "b"] and out["addRefDup"] == ["a"]
    assert out["delRef"] == ["b"]
    assert out["statusIn"] == {"warn": False, "text": ""}
    assert out["statusMissing"]["warn"] is True and "不存在" in out["statusMissing"]["text"]
    assert out["statusNoTarget"]["warn"] is True
    assert out["statusLoading"]["warn"] is False
    assert out["filter"] == [{"id": "bb", "name": "乙"}]
    assert out["label"] == "甲（a）" and out["labelUnknown"] == "zz"


def test_frontend_list_and_ref_wiring() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ('case "listtable"', 'case "reflist"', "function listTableEdit",
                  "function refListEdit", "EditorList.addRow", "EditorList.delRow",
                  "EditorList.setCell", "EditorRef.addRef", "EditorRef.delRef",
                  "EditorRef.status", 'data-ladd', 'data-ldel', 'data-refpick',
                  'data-refdel', "function refCandidateList", "function bindListSections"):
        assert token in html, token
    # 终端极简风组件样式（03 引用字段选择器 / 04 可增删行表格）
    for cls in (".ldel", ".ladd", ".ltable-edit", ".refsel", ".refvals", ".refval",
                ".rf-list", ".rf-it", ".refwarn"):
        assert cls in html, cls
    # 空列表空态
    assert "（空列表）" in html
    # 元素未声明子字段且无行可推断 → 如实提示（不臆造列名）
    assert "该列表元素的字段未在内容包元数据中声明" in html


def test_new_frontend_blocks_have_no_business_field_names() -> None:
    """批4 纯 JS 逻辑同样保持通用：不出现任何内容包模块名/业务字段名。"""
    banned = ["veinborn", "test_demo", "equipment", "技能", "物品", "装备", "怪物", "职业"]
    for begin, end in (("/* EDITOR_LIST_BEGIN */", "/* EDITOR_LIST_END */"),
                       ("/* EDITOR_REF_BEGIN */", "/* EDITOR_REF_END */")):
        block = _marked_block(begin, end)
        for word in banned:
            assert word not in block, (begin, word)


# =====================================================================================
# 四、嵌套值保存链：列表/引用多选 → 校验 → 原子写 + 备份 + 回退
# =====================================================================================
def test_save_list_add_row_writes_and_backs_up(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    bak = pack_root / "pack_l" / "widgets.json.bak"
    original = _read(path)
    new_steps = original[0]["steps"] + [{"kind": "b", "amt": 7, "ref": "a"}]
    res = _save(pack_root, "a", {"steps": new_steps})
    assert res["ok"] is True and res["written"] == ["widgets"]
    assert res["changed_fields"] == ["steps"]
    after = _read(path)
    assert after[0]["steps"] == new_steps
    assert after[1] == original[1] and after[2] == original[2]  # 其它条目原样
    assert _read(bak) == original                               # 备份 = 写盘前
    assert not list((pack_root / "pack_l").glob("*.tmp"))


def test_save_list_rollback_restores(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    original = _read(path)
    _save(pack_root, "a", {"steps": original[0]["steps"] + [{"kind": "a", "amt": 9, "ref": "a"}]})
    assert len(_read(path)[0]["steps"]) == 2
    rb = editor_ops.rollback_module("pack_l", "widgets", root=pack_root, role="owner", meta=META)
    assert rb["ok"] is True and rb["rolled_back"] is True
    assert _read(path) == original


def test_save_ref_list_multi_select(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    res = _save(pack_root, "a", {"members": ["c", "b", "a"]})
    assert res["ok"] is True
    assert _read(path)[0]["members"] == ["c", "b", "a"]
    assert _read(pack_root / "pack_l" / "widgets.json.bak")[0]["members"] == ["a", "b"]


def test_save_nested_cell_change(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    steps = [{"kind": "a", "amt": 6, "ref": "a"}]
    res = _save(pack_root, "a", {"steps": steps})
    assert res["ok"] is True
    assert _read(path)[0]["steps"] == steps


def test_invalid_ref_nested_is_reported_and_not_written(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    before = path.read_bytes()
    res = _validate(pack_root, "a", {"members": ["a", "ghost"]})
    assert res["ok"] is False and res["level"] == "red"
    assert any(e["code"] == "R-4" for e in res["errors"])
    # 红拦不落盘、不生成备份
    assert path.read_bytes() == before
    assert not (pack_root / "pack_l" / "widgets.json.bak").exists()


def test_nested_type_error_is_red(pack_root: Path) -> None:
    res = _validate(pack_root, "a", {"steps": [{"kind": "a", "amt": "不是数字", "ref": "a"}]})
    assert res["ok"] is False
    # 嵌套路径也能定位到字段中文名（人话提示）
    assert any(e["field_label"] == "步骤" for e in res["errors"])


def test_nested_save_red_does_not_write(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    before = path.read_bytes()
    res = _save(pack_root, "a", {"steps": [{"kind": "a", "amt": "x", "ref": "a"}]})
    assert res["ok"] is False and res["written"] == []
    assert path.read_bytes() == before


def test_nested_readonly_role_refused(pack_root: Path) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    before = path.read_bytes()
    with pytest.raises(api.Forbidden):
        _save(pack_root, "a", {"steps": []}, role="gm")
    assert path.read_bytes() == before


def test_nested_write_failure_rolls_back(pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = pack_root / "pack_l" / "widgets.json"
    original = _read(path)
    monkeypatch.setattr(editor_ops, "_verify_after_write",
                        lambda *a, **k: [{"level": "red", "code": "verify_failed",
                                          "message": "模拟复核失败"}])
    res = _save(pack_root, "a", {"members": ["a", "b"]})
    assert res["ok"] is False and res["rolled_back"] is True
    assert _read(path) == original


def test_nested_save_rejects_unknown_top_field(pack_root: Path) -> None:
    with pytest.raises(api.BadRequest):
        _save(pack_root, "a", {"no_such_field": [1, 2]})
    assert _read(pack_root / "pack_l" / "widgets.json") == ORIGINAL


def test_atomic_store_roundtrip_keeps_nested_shape(pack_root: Path) -> None:
    """原子写不改变嵌套结构（列表内对象键序/类型原样保留）。"""
    path = pack_root / "pack_l" / "widgets.json"
    res = atomic_store.backup_modules(pack_root / "pack_l", ["widgets"])
    assert res["ok"] is True
    new = _read(path)
    new[0]["steps"] = [{"kind": "b", "amt": 2, "ref": "a"}]
    written = atomic_store.write_modules(pack_root / "pack_l", {"widgets": new})
    assert written["ok"] is True
    assert _read(path)[0]["steps"] == [{"kind": "b", "amt": 2, "ref": "a"}]
