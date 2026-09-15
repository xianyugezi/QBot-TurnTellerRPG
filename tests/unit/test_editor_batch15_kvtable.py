"""编辑器重写批15 · #9 属性/配置表格化（键值表格 kvtable）测试。

覆盖任务书要求（通用，不写死模块名/字段名）：
  · 「键 → 标量值 / 小结构」的密集映射 → 键值表格渲染（紧凑行高、行内编辑、表头、增删行）；
  · 动态键空间可增删行/改键；固定 schema 的对象保持 objform（不摊平成表）；
  · 类型化单元格（文本/数字/布尔/引用）由列元数据 + 值形态给出；
  · 未配置项也显示（一号原则）——map 模块给「全表」入口，一把看全所有键；
  · 写盘 + 回退逐字节复原；既有列表表格/块状换行断言不回归；
  · DOM 实测（真 Chromium）：同一模块修前（基线 objform/逐条）vs 修后（键值表格）对照。
"""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content.models import FieldMeta, ModuleMeta
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
# 批15 基线（任务书基线 = main 最新 e15da93）：用于量测「表格化前」的对照
BASELINE_REF = "e15da93"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def _have_baseline() -> bool:
    if not (REPO / ".git").exists():
        return False
    return _git("rev-parse", "--verify", f"{BASELINE_REF}^{{commit}}").returncode == 0


def _marked_block(begin: str, end: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), html, re.S)
    assert match, f"index.html 缺少标记块 {begin} … {end}"
    return match.group(1)


def _pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


# ---------------------------------------------------------------------------
# 一、通用判定与字段/行模型
# ---------------------------------------------------------------------------
def test_dense_map_detection_is_shape_driven() -> None:
    assert api._is_dense_map({"a": 1, "b": 2})
    assert api._is_dense_map({"a": "x", "b": True})
    assert api._is_dense_map({"a": {"name": "甲", "max": 1}, "b": {"name": "乙"}})
    assert not api._is_dense_map({"a": [1, 2], "b": 3})          # 含列表 → 宽容器
    assert not api._is_dense_map({"a": 1})                        # 单键太小，保持现状
    assert not api._is_dense_map({"1": 10, "2": 20})              # 曲线形态另走曲线控件
    assert not api._is_dense_map({"a": {"x": {"deep": 1}}, "b": 2})  # 嵌套过深


def test_slot_defs_renders_whole_kvtable() -> None:
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    assert d["whole_table"] is True and d["open_keys"] is False
    f = d["fields"][0]
    assert f["control"] == "kvtable" and f["editable"] is True
    kv = f["kv_table"]
    assert kv["mode"] == "obj" and kv["row_count"] == 8
    assert {r["key"] for r in kv["rows"]} == set(
        json.loads((CONTENT / "veinborn" / "settings.json").read_text(
            encoding="utf-8"))["slot_defs"])


def test_scalar_map_renders_kvtable() -> None:
    """键 → 标量：单列「值」，控件按值形态推断。"""
    fm = FieldMeta(type="obj")
    d = api._descriptor("m", fm, {"a": 1, "b": 2.5, "c": "x"}, True,
                        ModuleMeta(entry_type="list"), api._PackView(
                            CONTENT / "veinborn", api._manifest(CONTENT / "veinborn")), 0)
    assert d["control"] == "kvtable"
    assert d["kv_table"]["mode"] == "scalar"
    assert [c["control"] for c in d["kv_table"]["columns"]] == ["number"]
    assert d["kv_table"]["rows"][0]["value"] == 1


def test_fixed_schema_object_stays_objform() -> None:
    """登记了 children 的固定 schema 对象 → 仍 objform（不摊平成表，既有布局不回归）。"""
    d = api.entry_detail("veinborn", "settings", "death_penalty", root=CONTENT)
    dp = {f["key"]: f for f in d["fields"]}["drop_exp"]
    assert dp["control"] == "objform"
    assert {c["key"] for c in dp["children"]} == {"enabled", "percent"}


def test_map_module_exposes_whole_table_entry_and_all_keys() -> None:
    """一号原则：map 模块给「全表」入口；未配置项也在一张表里看得见（不因包没配而消失）。"""
    le = api.list_entries("veinborn", "stats", root=CONTENT)
    assert le["table_entry"] and le["table_entry"]["id"] == api.TABLE_ENTRY_ID
    # 全表入口不计入条目计数（三处口径不变）
    assert le["count"] == len(le["entries"])
    assert all(e["id"] != api.TABLE_ENTRY_ID for e in le["entries"])
    d = api.entry_detail("veinborn", "stats", api.TABLE_ENTRY_ID, root=CONTENT)
    assert d["table_entry"] is True and d["whole_table"] is True
    kv = d["fields"][0]["kv_table"]
    assert kv["row_count"] == le["count"]
    assert {r["key"] for r in kv["rows"]} == {e["id"] for e in le["entries"]}
    # 类型化单元格：name 文本 / base 数字 / boolean 列按列元数据给控件
    cols = {c["key"]: c for c in kv["columns"]}
    assert cols["name"]["control"] == "text"
    assert cols["base"]["control"] == "number"


def test_unconfigured_map_field_still_visible() -> None:
    """一号原则：框架登记的 map 字段即使包未配置也显示（kvtable 空表可新增）。"""
    # 用一个未配置的包：demo_blank 的 settings 段仍按框架登记显示
    d = api.entry_detail("demo_blank", "settings", "slot_defs", root=CONTENT)
    keys = {f["key"] for f in d["fields"]}
    assert "slot_defs" in keys


def test_kv_table_spec_omits_absent_cells() -> None:
    """缺失子键不进 cells（保存不写 null），display 为空串。"""
    view = api._PackView(CONTENT / "veinborn", api._manifest(CONTENT / "veinborn"))
    spec = api._kv_table_spec({"a": {"name": "甲"}, "b": {"name": "乙", "max": 2}},
                              FieldMeta(type="obj"), view)
    rows = {r["key"]: r for r in spec["rows"]}
    assert rows["a"]["cells"] == {"name": "甲"}
    assert rows["b"]["cells"]["max"] == 2


# ---------------------------------------------------------------------------
# 二、写盘 + 回退（真写盘；临时内容根）
# ---------------------------------------------------------------------------
def test_whole_table_write_and_rollback(tmp_path: Path) -> None:
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=pack)
    kv = d["fields"][0]["kv_table"]
    newmap = {r["key"]: dict(r["cells"]) for r in kv["rows"]}
    newmap["belt"] = {"name": "腰带", "max": 2}
    del newmap["head"]
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"slot_defs": newmap}, root=pack, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))["slot_defs"]
    assert after["belt"] == {"name": "腰带", "max": 2} and "head" not in after
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack, role="owner")
    assert rb["ok"] is True
    assert sf.read_text(encoding="utf-8") == before


def test_map_module_table_write_and_rollback(tmp_path: Path) -> None:
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "stats.json"
    before = sf.read_text(encoding="utf-8")
    d = api.entry_detail("veinborn", "stats", api.TABLE_ENTRY_ID, root=pack)
    kv = d["fields"][0]["kv_table"]
    newmap = {r["key"]: dict(r["cells"]) for r in kv["rows"]}
    newmap["hp"]["base"] = 555
    res = editor_ops.save_entry("veinborn", "stats", api.TABLE_ENTRY_ID,
                                {api.TABLE_ENTRY_ID: newmap}, root=pack, role="owner")
    assert res["ok"] is True, res
    assert json.loads(sf.read_text(encoding="utf-8"))["hp"]["base"] == 555
    rb = editor_ops.rollback_module("veinborn", "stats", root=pack, role="owner")
    assert rb["ok"] is True
    assert sf.read_text(encoding="utf-8") == before


def test_absolutely_no_null_written_for_absent_cells(tmp_path: Path) -> None:
    """保存前后：可选子键「缺失仍是缺失」（不会被表格补成 null）。"""
    pack = _pack_copy(tmp_path)
    sf = pack / "veinborn" / "stats.json"
    d = api.entry_detail("veinborn", "stats", api.TABLE_ENTRY_ID, root=pack)
    kv = d["fields"][0]["kv_table"]
    newmap = {r["key"]: dict(r["cells"]) for r in kv["rows"]}
    newmap["hp"]["base"] = 401
    res = editor_ops.save_entry("veinborn", "stats", api.TABLE_ENTRY_ID,
                                {api.TABLE_ENTRY_ID: newmap}, root=pack, role="owner")
    assert res["ok"] is True, res
    hp = json.loads(sf.read_text(encoding="utf-8"))["hp"]
    assert hp["base"] == 401
    assert "min" not in hp and "display" not in hp  # 没被补 null
    assert "growth" not in json.loads(sf.read_text(encoding="utf-8"))["mp"]


# ---------------------------------------------------------------------------
# 三、前端纯逻辑（node 执行 EditorKv）+ 接线/布局不回归
# ---------------------------------------------------------------------------
_KV_HARNESS = r"""
const K = require(process.argv[1]);
const out = {};
const rows = K.rows({ a: { name: "甲", max: 1 }, b: { name: "乙" } }, true);
out.keys = rows.map(function (r) { return r.key; });
out.aCells = Object.assign({}, rows[0].cells);
K.setCell(rows, 1, "max", 3, true);
out.bMax = K.cellValue(rows, 1, "max");
K.setCell(rows, 0, "name", null, true);       // 清空 = 删子键（不写 null）
out.aNameGone = !("name" in rows[0].cells);
K.setKey(rows, 0, "aa");
const v = K.value(rows, true);
out.valueKeys = Object.keys(v);
out.valueA = v["aa"];
K.addRow(rows, true);
out.afterAdd = rows.length;
K.delRow(rows, 0);
out.afterDel = rows.length;
const srows = K.rows({ x: 1, y: 2 }, false);
K.setCell(srows, 0, "value", null, false);
out.scalarValue = K.value(srows, false);
process.stdout.write(JSON.stringify(out));
"""


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 键值表格语义执行")
def test_editor_kv_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "kv.js"
    src.write_text(_marked_block("/* EDITOR_KV_BEGIN */", "/* EDITOR_KV_END */"),
                   encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _KV_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)
    assert out["keys"] == ["a", "b"]
    assert out["aCells"] == {"name": "甲", "max": 1}
    assert out["bMax"] == 3
    assert out["aNameGone"] is True
    assert out["valueKeys"] == ["aa", "b"]
    assert out["valueA"] == {"max": 1}
    assert out["afterAdd"] == 3 and out["afterDel"] == 2
    assert out["scalarValue"] == {"y": 2}   # 清空标量值 = 删该键（不写 null）


def test_frontend_kvtable_wiring_and_no_layout_regression() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "EditorKv" in html and "function kvTableBody(" in html
    assert "function bindKvSections(" in html and "bindKvSections(el(\"p-body\"));" in html
    for token in ("data-kvkey", "data-kvcell", "data-kvadd", "data-kvdel"):
        assert token in html, token
    assert 'case "kvtable"' in html
    # 与既有列表表格/块状布局并存，不回归（断言仍在）
    for token in ("listTableBody", "listBlockBody", "EDITOR_LIST_BEGIN", "EDITOR_KV_BEGIN"):
        assert token in html, token
    # 表头用既有 helpTriggerHtml（说明气泡仍可用）+ 中文列名
    body = re.search(r"function kvTableBody\(.*?\n\}", html, re.S)
    assert body and "helpTriggerHtml" in body.group(0)
    assert "EditorBlocks" in html and ".subblk" in html


# ---------------------------------------------------------------------------
# 四、DOM 实测（真 Chromium）：修前（基线）vs 修后（键值表格）
# ---------------------------------------------------------------------------
def _playwright_ready() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
        with sync_playwright() as p:
            browser = p.chromium.launch()
            browser.close()
        return True
    except Exception:  # noqa: BLE001
        return False


PW_READY = _playwright_ready()


def _measure(repo: Path, content_root: Path, cases, out: Path) -> Dict[str, Any]:
    cmd = [sys.executable, str(REPO / "scripts" / "editor_dom_measure.py"),
           "--repo", str(repo), "--content-root", str(content_root),
           "--pack", "veinborn", "--json", str(out)]
    for case in cases:
        cmd += ["--case", case]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-2000:]
    return json.loads(out.read_text(encoding="utf-8"))


@pytest.mark.skipif(not PW_READY, reason="本机无 playwright/chromium，跳过 DOM 量测")
@pytest.mark.skipif(not _have_baseline(), reason="无基线 ref，跳过修前量测")
def test_dom_kvtable_more_compact_than_baseline(tmp_path: Path) -> None:
    cur = _measure(REPO, CONTENT, ["settings:slot_defs", "stats:" + api.TABLE_ENTRY_ID],
                   tmp_path / "cur.json")
    with _BaselineWorktree(tmp_path) as wt:
        base = _measure(wt, wt / "content", ["settings:slot_defs", "stats:hp"],
                        tmp_path / "base.json")
    cur_slot = cur["cases"][0]["after"]
    base_slot = base["cases"][0]["after"]
    # 修后：键值表格，8 个部位全部首屏可见；修前：objform 逐个块（更高、需滚动）
    assert cur_slot["hasKvTable"] is True and cur_slot["kvRows"] == 8
    assert cur_slot["kvVisibleRows"] == 8
    assert base_slot["hasKvTable"] is False
    assert cur_slot["scrollHeight"] < base_slot["scrollHeight"]
    # stats 全表：10 条属性一张表、全部首屏可见（每屏项数 10）
    cur_stats = cur["cases"][1]["after"]
    assert cur_stats["hasKvTable"] is True and cur_stats["kvRows"] >= 10
    assert cur_stats["kvVisibleRows"] == cur_stats["kvRows"]


class _BaselineWorktree:
    """临时 git worktree（基线树），退出时移除。"""
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.wt = tmp_path / "baseline"

    def __enter__(self) -> Path:
        add = _git("worktree", "add", "--detach", str(self.wt), BASELINE_REF)
        assert add.returncode == 0, add.stderr
        return self.wt

    def __exit__(self, *exc: Any) -> None:
        _git("worktree", "remove", "--force", str(self.wt))
