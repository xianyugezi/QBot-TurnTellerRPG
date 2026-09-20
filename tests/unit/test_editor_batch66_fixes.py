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
