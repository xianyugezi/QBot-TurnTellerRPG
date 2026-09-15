"""编辑器重写批16 · #11 条目预设（新建按模板）测试。

覆盖任务书要求（通用，不写死模块名/字段名）：
  · 包声明 `entry_presets`：`{id,label,help,fields,defaults,id_prefix,id_width}`；
  · 新建流程：选预设 → 只显示预设关心字段（其余进「其他字段」折叠区，**仍可编辑**）；
    `defaults` 生效；**不选预设 = 现状**（回归断言）；
  · 一号原则兼顾：预设只收窄显示面，其余字段仍在（不永久隐藏）；
  · 任何模块可配预设；无声明模块行为不变；
  · 端到端：带预设新建 → 真写盘（含 defaults）→ 回退（逐字节复原）；
  · 前端纯逻辑（node）+ 真 Chromium DOM：预设栏 / 其他字段折叠区 / 默认值。
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
NODE = shutil.which("node")

META = FieldMetaTable(
    modules={
        "things": ModuleMeta(entry_type="list", fields={
            "id": FieldMeta(type="str", required=True, label="标识"),
            "name": FieldMeta(type="str", label="名称"),
            "desc": FieldMeta(type="str", label="说明"),
            "type": FieldMeta(type="str", default="misc", label="类型"),
            "power": FieldMeta(type="int", default=1, label="威力"),
        }),
    },
)

PRESETS = {
    "schema_version": 1,
    "id_prefix": {"things": "mat"},
    "entry_presets": {"things": [
        {"id": "material", "label": "材料", "help": "只填名字和说明",
         "fields": ["name", "desc"], "defaults": {"type": "material"},
         "id_prefix": "ore", "id_width": 2},
        {"id": "weapon", "label": "武器", "fields": ["name", "power"],
         "defaults": {"type": "weapon"}},
    ]},
}


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    pkg = tmp_path / "pack_p"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "P", "version": "1", "schema_version": 1, "modules": ["things"],
    })
    _write(pkg / "things.json", [{"id": "mat_001", "name": "旧", "type": "material"}])
    _write(pkg / "field_meta.json", PRESETS)
    monkeypatch.setattr(api, "_META_TABLE", META)
    monkeypatch.setattr(api, "default_field_meta_table", lambda: META)
    monkeypatch.setattr(api, "_MERGED_TABLES", {})
    return tmp_path


# ---------------------------------------------------------------------------
# 一、包声明严格解析
# ---------------------------------------------------------------------------
def test_parse_entry_presets_shape() -> None:
    decl = pack_meta.parse_field_meta(PRESETS, "pk")
    item = decl.entry_presets["things"][0]
    assert item["id"] == "material" and item["label"] == "材料"
    assert item["fields"] == ("name", "desc") and item["defaults"] == {"type": "material"}
    assert item["id_prefix"] == "ore" and item["id_width"] == 2
    assert decl.id_prefix["things"] == "mat" and decl.id_width == {}


def test_parse_id_prefix_and_width_maps() -> None:
    decl = pack_meta.parse_field_meta(
        {"schema_version": 1, "id_prefix": {"m": "mat"}, "id_width": {"m": 4}}, "pk")
    assert decl.id_prefix == {"m": "mat"} and decl.id_width == {"m": 4}
    with pytest.raises(pack_meta.PackFieldMetaError):
        pack_meta.parse_field_meta(
            {"schema_version": 1, "id_prefix": {"m": ""}}, "pk")
    with pytest.raises(pack_meta.PackFieldMetaError):
        pack_meta.parse_field_meta(
            {"schema_version": 1, "id_width": {"m": True}}, "pk")


@pytest.mark.parametrize("bad", [
    {"schema_version": 1, "entry_presets": {"m": []}},                       # 空数组
    {"schema_version": 1, "entry_presets": {"m": [{"id": "a"}]}},            # 缺 label
    {"schema_version": 1, "entry_presets": {"m": [{"id": "a", "label": "l", "fields": []}]}},
    {"schema_version": 1, "entry_presets": {"m": [{"id": "a", "label": "l",
                                                   "fields": ["x"], "bogus": 1}]}},
    {"schema_version": 1, "entry_presets": {"m": [
        {"id": "a", "label": "l", "fields": ["x"]},
        {"id": "a", "label": "l2", "fields": ["y"]}]}},                       # 预设 id 重复
    {"schema_version": 1, "id_width": {"m": 0}},
    {"schema_version": 1, "id_width": {"m": 99}},
])
def test_parse_entry_presets_rejects_bad_shape(bad: Dict[str, Any]) -> None:
    with pytest.raises(pack_meta.PackFieldMetaError):
        pack_meta.parse_field_meta(bad, "pk")


# ---------------------------------------------------------------------------
# 二、新建界面：选预设 → 收窄显示面 + defaults；不选预设 = 现状
# ---------------------------------------------------------------------------
def test_no_preset_is_regression(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_p", "things", root=pack_root, name="x")
    assert d["preset"] == ""
    assert [p["id"] for p in d["presets"]] == ["material", "weapon"]
    assert d["other_fields"] == [] and d["other_field_count"] == 0
    # 不作拆分：字段 = 全部可初始化字段（与修前一致）
    assert [f["key"] for f in d["fields"]] == ["name", "desc", "type", "power"]
    assert d["field_count"] == len(d["fields"]) == 4


def test_preset_narrows_fields_and_keeps_others_editable(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_p", "things", root=pack_root, name="x",
                             preset="material")
    assert d["preset"] == "material" and d["preset_help"] == "只填名字和说明"
    # 主区 = 预设关心字段；其余进「其他字段」（不永久隐藏）
    assert [f["key"] for f in d["fields"]] == ["name", "desc"]
    assert [f["key"] for f in d["other_fields"]] == ["type", "power"]
    assert d["field_count"] == 4 and d["preset_field_count"] == 2
    # 其他字段仍可编辑（非只读控件）
    assert all(f["editable"] for f in d["other_fields"])
    # defaults 生效：type=material（它虽不在主区，但值已初始化）
    type_f = next(f for f in d["other_fields"] if f["key"] == "type")
    assert type_f["present"] is True and type_f["value"] == "material"


def test_preset_defaults_override_metadata_default(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_p", "things", root=pack_root, name="x",
                             preset="material")
    power = next(f for f in d["other_fields"] if f["key"] == "power")
    assert power["value"] == 1                 # 未被预设覆盖 → 元数据默认
    type_f = next(f for f in d["other_fields"] if f["key"] == "type")
    assert type_f["value"] == "material"       # 预设覆盖元数据默认 "misc"


def test_preset_prefix_and_id(pack_root: Path) -> None:
    d = api.new_entry_detail("pack_p", "things", root=pack_root, name="新",
                             preset="material")
    # 预设自己的 id_prefix=ore / id_width=2（覆盖包级 id_prefix=mat / width=3）
    assert d["suggested_id"] == "ore_01"
    assert d["id_rule"]["prefix"] == "ore" and d["id_rule"]["width"] == 2


def test_no_preset_uses_pack_prefix_not_preset_prefix(pack_root: Path) -> None:
    # 不选预设 → 包级 id_prefix=mat（宽 3）；预设自己的 ore/2 只在选中该预设时生效
    assert api.suggest_id("pack_p", "things", root=pack_root, name="x")["suggested_id"] \
        == "mat_002"


def test_preset_declares_unknown_field_is_reported(pack_root: Path) -> None:
    _write(pack_root / "pack_p" / "field_meta.json", {
        "schema_version": 1,
        "entry_presets": {"things": [
            {"id": "bad", "label": "坏", "fields": ["name", "nope"]},
        ]},
    })
    d = api.new_entry_detail("pack_p", "things", root=pack_root, name="x", preset="bad")
    assert d["preset_missing_fields"] == ["nope"]
    assert [f["key"] for f in d["fields"]] == ["name"]


# ---------------------------------------------------------------------------
# 三、端到端：带预设新建 → 真写盘 → 回退逐字节复原
# ---------------------------------------------------------------------------
def test_create_with_preset_writes_defaults_then_rollback(pack_root: Path) -> None:
    pack_dir = pack_root / "pack_p"
    before = (pack_dir / "things.json").read_bytes()
    env = editor_ops.create_entry(
        "pack_p", "things", "mat_002",
        {"name": "新条目", "desc": "说明"},
        root=pack_root, meta=META, preset="material")
    assert env["ok"] is True, env
    written = json.loads((pack_dir / "things.json").read_text(encoding="utf-8"))
    assert len(written) == 2
    new = written[1]
    # defaults 生效（服务端按预设叠加，不依赖前端提交该键）+ patch 生效
    # defaults：预设 type=material 覆盖元数据默认 misc；power 无预设覆盖 → 元数据默认 1
    assert new == {"id": "mat_002", "name": "新条目", "desc": "说明",
                   "type": "material", "power": 1}
    # 既有条目一动不动
    assert written[0] == {"id": "mat_001", "name": "旧", "type": "material"}
    # 回退 → 逐字节复原
    rb = editor_ops.rollback_module("pack_p", "things", root=pack_root, meta=META)
    assert rb.get("ok") is True, rb
    assert (pack_dir / "things.json").read_bytes() == before


def test_create_without_preset_is_regression(pack_root: Path) -> None:
    pack_dir = pack_root / "pack_p"
    env = editor_ops.create_entry(
        "pack_p", "things", "things_001", {"name": "无预设"},
        root=pack_root, meta=META)
    assert env["ok"] is True, env
    written = json.loads((pack_dir / "things.json").read_text(encoding="utf-8"))
    # 无预设 → 只用元数据默认（type=misc / power=1），不注入预设 defaults
    assert written[1] == {"id": "things_001", "name": "无预设", "type": "misc", "power": 1}


# ---------------------------------------------------------------------------
# 四、前端：预设栏 / 其他字段折叠区（node 纯逻辑）
# ---------------------------------------------------------------------------
def _fn_src(name: str, next_name: str) -> str:
    html = HTML.read_text(encoding="utf-8")
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    return html[start:end].rstrip()


_JS_HARNESS = r"""
var esc = function (s) { return String(s == null ? "" : s); };
var fieldRow = function (f) { return '<ROW key="' + f.key + '"/>'; };
__SRC__
process.stdout.write(JSON.stringify({
  none: newPresetHtml({ presets: [] }),
  bar: newPresetHtml({ presets: [
    { id: "material", label: "材料", help: "只填名字和说明", field_count: 2 },
    { id: "weapon", label: "武器", help: "", field_count: 2 }], preset: "material" }),
  pick: newPresetHtml({ presets: [
    { id: "material", label: "材料", help: "h", field_count: 2 }], preset: "" }),
  other: otherFieldsHtml([{ key: "type" }, { key: "power" }]),
  otherEmpty: otherFieldsHtml([])
}));
"""


def test_js_preset_bar_and_other_fields(tmp_path: Path) -> None:
    if NODE is None:
        pytest.skip("本机无 node，跳过前端纯逻辑执行")
    src = _fn_src("newPresetHtml", "otherFieldsHtml") + "\n" \
        + _fn_src("otherFieldsHtml", "renderNewEntry")
    script = tmp_path / "preset.js"
    script.write_text(_JS_HARNESS.replace("__SRC__", src), encoding="utf-8")
    proc = subprocess.run([NODE, str(script)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["none"] == "" and out["otherEmpty"] == ""       # 无声明 → 不渲染
    assert 'id="new-preset"' in out["bar"] and 'value="material" selected' in out["bar"]
    assert "只填名字和说明" in out["bar"]
    assert 'value="" selected' not in out["bar"]                # 命中的预设被选中
    assert 'selected' not in out["pick"]                          # 未选 → 默认项（首个）
    assert "其他字段" in out["other"] and out["other"].count("<ROW") == 2
    assert "hidden" in out["other"]                             # 默认折叠（点开展开）


def test_frontend_wires_preset_and_other_fields() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "otherFieldsHtml(otherFields)" in html          # 其他字段真的渲染进面板
    assert "(d.fields || []).concat(otherFields)" in html  # 折叠区字段也进字段索引
    assert "bindSubBlocks();" in html
    assert 'id="new-preset"' in html and "newPresetHtml(d)" in html
    assert 'preset=body.get("preset")' in (
        REPO / "scripts" / "editor_host.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# 五、真 Chromium DOM：预设栏 / 只显示预设字段 / 其他字段折叠且可编辑 / defaults
# ---------------------------------------------------------------------------
def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last: Any = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - 轮询探活
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"编辑器宿主未就绪：{url}（{last}）")


def _playwright_ready() -> bool:
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001 - 无浏览器内核 → 跳过量测
        return False


PW_READY = _playwright_ready()

_MEASURE_JS = r"""
() => {
  const body = document.getElementById('p-body');
  const sel = document.getElementById('new-preset');
  const main = Array.from(body.querySelectorAll('.gpane:not([hidden]) .row[data-field]'))
    .map(r => r.dataset.field);
  const other = body.querySelector('.subblk[data-sb="__other__"]');
  const ob = other ? other.querySelector('.sbbody') : null;
  const otherKeys = other
    ? Array.from(other.querySelectorAll('.row[data-field]')).map(r => r.dataset.field) : [];
  const disabled = other
    ? Array.from(other.querySelectorAll('input,select,textarea'))
        .filter(e => e.disabled).length
    : -1;
  const payload = state.newEntry || {};
  const of = payload.other_fields || [];
  const pow = of.filter(f => f.key === 'power')[0];
  return {
    hasSel: !!sel, sel: sel ? sel.value : null,
    main: main, otherKeys: otherKeys,
    otherCollapsed: ob ? !!ob.hidden : null, otherDisabled: disabled,
    powerValue: pow ? pow.value : null, preset: payload.preset || '',
    otherCount: of.length, fields: (payload.fields || []).map(f => f.key)
  };
}
"""


@pytest.mark.skipif(not PW_READY, reason="本机无 playwright/chromium，跳过 DOM 量测")
def test_dom_preset_new_entry_fields(tmp_path: Path) -> None:
    pack = "demo_full"
    root = tmp_path / "content"
    root.mkdir()
    shutil.copytree(CONTENT / pack, root / pack)

    # 动态发现字段键（不写死业务字段）：取前两个作预设关心字段
    d0 = api.new_entry_detail(pack, "effects", root=root)
    all_keys = [f["key"] for f in d0["fields"]]
    pfields = all_keys[:2]
    _write(root / pack / "field_meta.json", {
        "schema_version": 1,
        "entry_presets": {"effects": [
            {"id": "quick", "label": "快速", "help": "只填前两个字段",
             "fields": pfields, "defaults": {"power": 42}},
        ]},
    })

    port = _free_port()
    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO)
    proc = subprocess.Popen(
        [sys.executable, str(REPO / "scripts" / "editor_host.py"),
         "--pack", pack, "--content-root", str(root), "--port", str(port),
         "--host", "127.0.0.1"],
        cwd=str(REPO), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/api/session")
        from playwright.sync_api import sync_playwright  # noqa: PLC0415
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("dialog", lambda dlg: dlg.accept())
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_function("() => !!(state && state.pack)", timeout=15000)
            page.evaluate("async (m) => { await selectModule(m); }", "effects")
            page.wait_for_function("() => state.module === 'effects'", timeout=15000)
            # 不选预设 = 现状：全部字段在主区，无「其他字段」块
            page.evaluate("async () => { await openNewEntry(); }")
            page.wait_for_function("() => !!(state.newEntry)", timeout=15000)
            no = page.evaluate(_MEASURE_JS)
            # 选预设 → 主区收窄 + 其他字段折叠
            page.select_option("#new-preset", "quick")
            page.wait_for_function("() => (state.newEntry || {}).preset === 'quick'",
                                   timeout=15000)
            withp = page.evaluate(_MEASURE_JS)
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    # 无预设回归
    assert no["hasSel"] is True and no["sel"] == ""
    assert no["otherCount"] == 0 and no["otherKeys"] == []
    assert list(no["fields"]) == all_keys
    # 选预设：只显示预设字段；其余进「其他字段」折叠区且**可编辑**
    assert withp["sel"] == "quick" and withp["preset"] == "quick"
    assert list(withp["fields"]) == pfields
    assert set(withp["otherKeys"]) == set(all_keys) - set(pfields)
    assert withp["otherCount"] == len(all_keys) - len(pfields)
    assert withp["otherCollapsed"] is True
    assert withp["otherDisabled"] == 0          # 折叠区控件不是 disabled → 可编辑
    assert withp["powerValue"] == 42            # 预设 defaults 生效
    assert withp["main"] and set(withp["main"]) <= set(pfields)
