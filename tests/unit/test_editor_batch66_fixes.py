"""批67 · 批66「新用户 8 卡点」修复的回归测试（锁住修复，防回归）。

依据：`/root/deliverables/编辑器_新用户走查.md`（8 卡点复现步骤）+ 批66 提交
（`git log --grep='批66'`）。逐条对应：

  卡点1（阻断） 编辑态改 ID 接 id_check + 保存硬拦 + 可行动错误   → §1
  卡点2（烦人） 启用模块 / 应用推荐组合后自动选中 → state.module  → §2
  卡点3（烦人） 残缺包切包显式报错 + 不残留上一个包数据          → §3
  卡点4（烦人） key 字段 help 全部 ≤60 字（清 Markdown / 英文键） → §4
  卡点5（锦上添花） 必填字段可见标记 + required/aria-required    → §5
  卡点6（锦上添花） 保存/创建成功给一次显式状态位反馈            → §6
  卡点7（锦上添花） 推荐组合存在（批65 已覆盖，此处只核对不重复）→ §7
  卡点8（锦上添花） 中栏空态两种情形可区分                       → §8

断言纪律（并行批会改文案/UI）：只测「机制与行为 / DOM 结构 / 状态位」，
不比对任何一句中文提示的逐字原文；所有写盘落在 tmp_path 临时包，绝不触碰仓库
`content/` 下任何真实内容包。前端行为用 node 执行 index.html 内联函数（不起浏览器）。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Mapping

import pytest

from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
# 反向验证/离线性需要时可指向 index.html 的副本（默认仍是仓库真身，见测试报告）。
HTML = Path(os.environ.get("QBOT_EDITOR_INDEX_HTML")
            or (REPO / "qbot_rpg" / "web" / "static" / "index.html"))
NODE = shutil.which("node")


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _make_pack(root: Path, pack: str, modules: List[str],
               files: Mapping[str, Any] | None = None) -> Path:
    """在临时根下建一个最小内容包（写盘只在 tmp_path，绝不碰仓库 content/）。"""
    pkg = root / pack
    pkg.mkdir(parents=True)
    _write(pkg / "manifest.json",
           {"name": pack, "version": "1", "schema_version": 1, "modules": list(modules)})
    for name, data in (files or {}).items():
        _write(pkg / name, data)
    return pkg


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


# =====================================================================================
# §1 · 卡点1（阻断）：编辑态改 ID 接 id_check + 保存硬拦 + 可行动错误
# =====================================================================================
def test_card1_id_check_rejects_bad_id_with_actionable_red(tmp_path: Path) -> None:
    """id_check 对非法 ID 返回 ok=false / red / how_to_fix 非空（修复所复用的同一校验）。"""
    _make_pack(tmp_path, "p1", ["items"], {"items.json": [{"id": "item_001", "name": "剑"}]})
    res = api.check_entry_id("p1", "items", "Bad ID!", root=tmp_path)
    assert res["ok"] is False
    assert res["level"] == "red"
    assert str(res.get("how_to_fix") or "").strip()


def test_card1_validate_blocks_bad_rename_with_actionable_error(tmp_path: Path) -> None:
    """保存前校验：非法 ID 改名 → 红拦，错误条目含 how_to_fix（可行动）。"""
    _make_pack(tmp_path, "p1", ["items"], {"items.json": [{"id": "item_001", "name": "剑"}]})
    env = editor_ops.validate_entry("p1", "items", "item_001", {"id": "Bad ID!"}, root=tmp_path)
    assert env["ok"] is False and env["level"] == "red"
    assert env["errors"] and all(str(e.get("how_to_fix") or "").strip() for e in env["errors"])


def test_card1_save_bad_id_blocked_with_zero_write(tmp_path: Path) -> None:
    """硬拦核心：非法 ID 的保存请求被拒，items.json 逐字节不变，且零备份残留。"""
    pkg = _make_pack(tmp_path, "p1", ["items"],
                     {"items.json": [{"id": "item_001", "name": "剑"}]})
    target = pkg / "items.json"
    before = target.read_bytes()
    before_files = sorted(p.name for p in pkg.iterdir())
    env = editor_ops.save_entry("p1", "items", "item_001", {"id": "Bad ID!"}, root=tmp_path)
    assert env["ok"] is False and env["level"] == "red"
    assert env["errors"] and env["errors"][0].get("code") == "id_invalid"
    assert str(env["errors"][0].get("how_to_fix") or "").strip()
    assert target.read_bytes() == before                       # 写盘不变
    assert sorted(p.name for p in pkg.iterdir()) == before_files  # 零备份/临时文件
    assert _read(target) == [{"id": "item_001", "name": "剑"}]


def test_card1_entry_detail_exposes_id_field(tmp_path: Path) -> None:
    """编辑面板据 id_field 定位身份字段（接线前提）。"""
    _make_pack(tmp_path, "p1", ["items"], {"items.json": [{"id": "item_001", "name": "剑"}]})
    d = api.entry_detail("p1", "items", "item_001", root=tmp_path)
    assert d.get("id_field")


def test_card1_frontend_edit_id_check_wired_and_hard_block() -> None:
    """index.html：idCheck 状态 + 编辑态 id_check 接线 + 保存按钮硬拦谓词存在。"""
    import re
    html = _html()
    for token in ("idCheck", "function editIdBlocked(", "function bindEditIdent(",
                  "function refreshEditIdCheck(", "/id_check"):
        assert token in html, token
    # 保存按钮的禁用判定必须并入 editIdBlocked()（硬拦：非法 ID 置灰保存）。
    assert re.search(r'btn-save"\)\.disabled[^;]*editIdBlocked\(\)', html), \
        "保存按钮禁用判定未接 editIdBlocked()"


# =====================================================================================
# §0 · 前端行为执行台（node 执行 index.html 内联函数；不起浏览器、不写盘）
# =====================================================================================
def _fn_src(name: str) -> str:
    """从 index.html 截取 `function name(` 到下一个顶层 `function ` 的源码。

    按函数名切片（不写死相邻函数名/顺序），并行批调整函数顺序也不影响。
    """
    html = _html()
    start = html.index("function %s(" % name)
    nxt = html.find("\nfunction ", start + 1)
    assert nxt != -1, name
    return html[start:nxt]


_FRONTEND_FNS = ("findModule", "selectModule", "refreshAfterModuleChange",
                 "moduleEnabled", "renderListHints", "fieldRow", "editControl",
                 "newIdentHtml", "flashSaved", "savedFlashText", "clearPackView",
                 "packLoadFailed", "loadPackView")

# 统一桩：DOM（el 返回可断言对象）、网络（loadModules/loadEntries 可注入成败）、
# markDirty（记录调用时 state.module —— 卡点2 的时序回归就靠它抓）。
_DOM_RUNNER = r"""
const fs = require("fs");
const out = {};
const els = {};
const timers = [];
const dirtyCalls = [];
function mkEl(id) {
  return { id: id, textContent: "", innerHTML: "", className: "", value: "",
    hidden: false, title: "", disabled: false, dataset: {}, style: {},
    classList: { add: function () {}, remove: function () {}, toggle: function () {} },
    querySelector: function () { return null; },
    querySelectorAll: function () { return []; },
    addEventListener: function () {}, setAttribute: function () {},
    closest: function () { return null; }, appendChild: function () {} };
}
global.el = function (id) { if (!els[id]) { els[id] = mkEl(id); } return els[id]; };
global.esc = function (v) { return String(v == null ? "" : v); };
global.INPUT_EMPTY = "未填写";
global.typeZh = function (t) { return t || "文本"; };
global.helpTriggerHtml = function (trig, label) { return "TRIG[" + label + "]"; };
global.fieldLabelHtml = function (label, key) { return String(label || key || ""); };
global.fieldBody = function (f) { return "BODY[" + f.key + "]"; };
global.currentFieldValue = function (f) { return f.value; };
global.selectHtml = function () { return "SEL"; };
global.listTableEdit = function () { return "LT"; };
global.refListEdit = function () { return "RL"; };
global.objFormEdit = function () { return "OBJ"; };
global.condFieldInner = function () { return "C"; };
global.mapFieldInner = function () { return "M"; };
global.kvTableEdit = function () { return "KV"; };
global.curveEdit = function () { return "CV"; };
global.EditorEntry = { ruleText: function () { return "RULE"; } };
global.canLeave = function () { return true; };
global.renderModules = function () {};
global.setHdrNote = function () {};
global.refreshRollbackButton = function () {};
global.helpHideDom = function () {};
global.renderGlobalResults = function () {};
global.markDirty = function () {
  dirtyCalls.push(global.state ? global.state.module : "__no_state__");
};
global.discardDraft = function () { global.markDirty(); };
global.loadEntries = function () { return Promise.resolve(); };
global.__loadModulesImpl = function () { return Promise.resolve(); };
global.__loadEntryIndexImpl = function () { return Promise.resolve(); };
global.loadModules = function () { return global.__loadModulesImpl(); };
global.loadEntryIndex = function () { return global.__loadEntryIndexImpl(); };
global.setTimeout = function (fn, ms) { timers.push(ms); return 1; };
global.clearTimeout = function () {};

eval(fs.readFileSync(process.argv[2], "utf8"));

(async function () {
  // 卡点2-A：启用/应用组合后应选中 preferred，而非回落第一个模块。
  state = { module: null, modules: [{ module: "aaa" }, { module: "items" }], views: [],
    entries: [], entryIndex: null, listLabel: "", backup: null, mergeSections: [],
    mountedSections: [], entryGroups: [], unusedPack: null, unusedByMod: {},
    refCache: {}, refKnown: {}, refQuery: {}, gquery: "", detail: null, tabs: [],
    forms: {}, pendingDrafts: {} };
  await refreshAfterModuleChange("items");
  out.prefStateModule = state.module;

  // 卡点2-B：selectModule 切换后必须再刷一次（discardDraft 的 markDirty 看的是旧模块）。
  state = { module: null, modules: [{ module: "items" }], views: [], entries: [],
    backup: null, mergeSections: [], mountedSections: [], gquery: "" };
  dirtyCalls.length = 0;
  selectModule("items");
  out.selectModuleState = state.module;
  out.selectModuleDirtyLast = dirtyCalls[dirtyCalls.length - 1];
  out.selectModuleDirtySawModule = dirtyCalls.indexOf("items") >= 0;

  // 卡点3-前端：读包失败必须清空三栏 + 给可行动横幅（不残留上一个包的数据）。
  state = { modules: [{ module: "old", count: 5 }], views: [{ module: "oldv" }],
    available: ["x"], module: "old", entry: "e1", entryModule: "old",
    entries: [{ id: "e1" }], entryIndex: { old: 1 }, listLabel: "上次",
    backup: { exists: true }, mergeSections: [1], mountedSections: [1],
    entryGroups: [1], unusedPack: "old", unusedByMod: { old: {} },
    refCache: { a: 1 }, refKnown: { a: 1 }, refQuery: { a: 1 }, gquery: "q",
    detail: { x: 1 }, tabs: [1], forms: { a: 1 }, pendingDrafts: { a: 1 } };
  packLoadFailed({ message: "读取内容包失败（注入）",
    how_to_fix: "测试注入：修好 quest.json 后重新选择该包" });
  out.clearedModules = state.modules.length;
  out.clearedViews = state.views.length;
  out.clearedModule = state.module;
  out.clearedEntries = state.entries.length;
  out.clearedIndex = state.entryIndex;
  out.clearedDetail = state.detail;
  out.clearedRefCache = Object.keys(state.refCache).length;
  out.clearedUnusedPack = state.unusedPack;
  out.packHint = el("list-hint").innerHTML;
  out.packHintHidden = el("list-hint").hidden;
  out.packPBody = el("p-body").innerHTML;

  // loadPackView：任一读包请求失败 → 走同一条清空 + 报错链路。
  state = { modules: [{ module: "old" }], views: [], available: [], module: "old",
    entry: null, entryModule: null, entries: [{ id: "e" }], entryIndex: {},
    listLabel: "", backup: null, mergeSections: [], mountedSections: [],
    entryGroups: [], unusedPack: null, unusedByMod: {}, refCache: {},
    refKnown: {}, refQuery: {}, gquery: "", detail: null, tabs: [], forms: {},
    pendingDrafts: {} };
  global.__loadModulesImpl = function () {
    return Promise.reject({ message: "注入读包失败", how_to_fix: "注入修法" });
  };
  await loadPackView();
  out.catchClearedModules = state.modules.length;
  out.catchClearedModule = state.module;
  out.catchPBody = el("p-body").innerHTML;

  process.stdout.write(JSON.stringify(out));
})();
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批67 前端行为回归")
    snippet = "\n\n".join(_fn_src(n) for n in _FRONTEND_FNS)
    d = tmp_path_factory.mktemp("batch67")
    harness = d / "snippet.js"
    harness.write_text(snippet, encoding="utf-8")
    runner = d / "run.js"
    runner.write_text(_DOM_RUNNER, encoding="utf-8")
    proc = subprocess.run([NODE, str(runner), str(harness)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# =====================================================================================
# §2 · 卡点2（烦人）：启用模块 / 应用推荐组合后自动选中该模块（state.module 被设置）
# =====================================================================================
def test_card2_apply_preset_selects_preferred_not_first(js: Dict[str, Any]) -> None:
    """有 preferred 时必须选中它——修前 refreshAfterModuleChange 回落第一个模块。"""
    assert js["prefStateModule"] == "items"


def test_card2_select_module_refreshes_after_state_is_set(js: Dict[str, Any]) -> None:
    """按钮刷新（markDirty）必须在 state.module 已切换之后发生——修前只看得到旧模块。"""
    assert js["selectModuleState"] == "items"
    assert js["selectModuleDirtyLast"] == "items"
    assert js["selectModuleDirtySawModule"] is True


def test_card2_frontend_enable_paths_pass_preferred() -> None:
    """三条启用链路（一键启用 / 勾选 toggle / 推荐组合）都要把目标模块传给刷新函数。"""
    html = _html()
    assert "refreshAfterModuleChange(mod)" in html        # 左栏一键启用
    assert "refreshAfterModuleChange(prefMod)" in html    # 应用推荐组合
    assert "res.enabled" in html and "prefMod" in html


# =====================================================================================
# §3 · 卡点3（烦人）：残缺包切包显式报错 + 不残留上一个包数据
# =====================================================================================
def _make_broken_pack(root: Path, pack: str = "broken") -> Path:
    """声明了模块但 quest.json 为空文件（走查复现场景）。"""
    pkg = root / pack
    pkg.mkdir()
    _write(pkg / "manifest.json", {"name": "残缺", "version": "1", "schema_version": 1,
                                   "modules": ["items", "quest"]})
    (pkg / "items.json").write_text("[]", encoding="utf-8")
    (pkg / "quest.json").write_text("", encoding="utf-8")   # 坏 JSON：空文件
    return pkg


def test_card3_broken_pack_raises_actionable_error_naming_file(tmp_path: Path) -> None:
    """声明模块的文件空/坏 → EditorError 点名文件 + how_to_fix；不泄露绝对路径/Python 异常。"""
    _make_pack(tmp_path, "good", ["items"], {"items.json": [{"id": "it1", "name": "甲"}]})
    _make_broken_pack(tmp_path)
    api.list_modules("good", root=tmp_path)      # 先读好包，再切残缺包（复现切包顺序）
    with pytest.raises(api.EditorError) as ei:
        api.list_modules("broken", root=tmp_path)
    msg = str(ei.value)
    assert "quest.json" in msg
    assert str(tmp_path) not in msg              # 不泄露服务器绝对路径
    assert "Expecting value" not in msg and "Traceback" not in msg
    assert str(getattr(ei.value, "how_to_fix", "") or "").strip()


def test_card3_entry_index_also_fails_explicitly(tmp_path: Path) -> None:
    """条目索引是另一条读包链路，坏包同样必须显式抛错（不能静默 0 条）。"""
    _make_broken_pack(tmp_path)
    with pytest.raises(api.EditorError) as ei:
        api.entry_index("broken", root=tmp_path)
    assert "quest.json" in str(ei.value)
    assert str(getattr(ei.value, "how_to_fix", "") or "").strip()


def _client(root: Path, pack: str, role: str = "owner") -> Any:
    import sys
    if str(REPO) not in sys.path:
        sys.path.insert(0, str(REPO))
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from editor_host import create_app  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    return TestClient(create_app(pack=pack, root=str(root), role=role))


def test_card3_host_error_json_carries_how_to_fix(tmp_path: Path) -> None:
    """宿主错误包络：既保留 error/kind，又带 how_to_fix；文案不含绝对路径。"""
    _make_broken_pack(tmp_path)
    with _client(tmp_path, "broken") as client:
        r = client.get("/api/pack/broken/modules")
    assert r.status_code == 500
    body = r.json()
    assert body.get("ok") is False and body.get("error") and body.get("kind")
    assert str(body.get("how_to_fix") or "").strip()
    assert str(tmp_path) not in json.dumps(body, ensure_ascii=False)


def test_card3_frontend_pack_load_failure_clears_all_panes(js: Dict[str, Any]) -> None:
    """前端：读包失败 → 清空左/中/右三栏状态 + 可行动横幅（不残留上一个包数据）。"""
    assert js["clearedModules"] == 0
    assert js["clearedViews"] == 0
    assert js["clearedModule"] is None
    assert js["clearedEntries"] == 0
    assert js["clearedIndex"] is None
    assert js["clearedDetail"] is None
    assert js["clearedRefCache"] == 0
    assert js["clearedUnusedPack"] is None
    assert js["packHint"] and js["packHintHidden"] is False
    assert "测试注入" in js["packPBody"]          # 「怎么办」进了横幅


def test_card3_frontend_load_pack_view_catches_and_reports(js: Dict[str, Any]) -> None:
    """读包 Promise 任一失败 → 统一走失败链路（不是静默不 catch）。"""
    assert js["catchClearedModules"] == 0
    assert js["catchClearedModule"] is None
    assert "注入读包失败" in js["catchPBody"]


def test_card3_frontend_three_read_chains_route_through_load_pack_view() -> None:
    """换包 / 导入后刷新 / 启动三条读包链路统一走 loadPackView。"""
    html = _html()
    assert "function loadPackView(" in html
    assert "function clearPackView(" in html and "function packLoadFailed(" in html
    assert html.count("loadPackView()") >= 3
