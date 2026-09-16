"""编辑器重写批10 · 配色按钮化 + 自定义背景图（透明度可调）+ V15/V16。

覆盖任务书要求：
  A. **配色按钮化**：顶栏三个配色按钮 → 一个「🎨 配色」按钮（与 ⚙ 模块同款位置/交互）；
     点开面板内**三套主题单选列表**（当前选中态 + 一句说明）；选择立即生效 + 持久化。
  B. **公共弹层组件**：⚙ 模块（#modpanel）与 🎨 配色（#themepanel）**共用同一套**
     `.mp-*` 样式与 `EditorModal` 实现（打开/关闭/焦点回还/Esc/Tab 环/点遮罩关闭/筛选）。
  C. **V15**：面板列表细滚动条（沿用 --sb-* 令牌）+ 关键词筛选框。
  D. **V16**：面板居中 + 轻量遮罩（点遮罩关闭）。
  E. **自定义背景图**：本地文件（FileReader → dataURL）与图片 URL 两种来源；
     `background-image` cover + fixed；内容与背景之间**主题底色兜底层**（--bg-scrim）；
     透明度滑块 0–100%（实时 + 持久化 + clamp）；清除按钮；小预览；
     非图片/超大文件/坏 URL 人话兜底，不影响编辑器使用。
  F. **存储：浏览器本地**（localStorage 首选，图片过大 IndexedDB 兜底；绝不上传服务器，
     不写任何内容包文件）；键名 `qbot.editor.bg.image` / `qbot.editor.bg.opacity` 与回退。
  G. 无障碍：面板 `role="dialog"` / `aria-modal`、`Esc` 关闭、焦点回触发按钮、滑块 `aria-valuenow`。

纯 JS 断言在 node 下执行 index.html 内联标记块/函数体；不触碰任何内容包、不写盘。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
TOKENS = REPO / "qbot_rpg" / "web" / "static" / "tokens.css"

BATCH_NOTE = "批24 · 字段扩展（地图/副本/任务）"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _tokens_css() -> str:
    return TOKENS.read_text(encoding="utf-8")


def _marked(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


def _fn(name: str) -> str:
    """按花括号配对取出函数体（本文件只用于无嵌套字符串花括号的小函数）。"""
    html = _html()
    start = html.index("function " + name + "(")
    i = html.index("{", start)
    depth = 0
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[start:j + 1]
    raise AssertionError(name)


def _run_node(script: str) -> Dict[str, Any]:
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


_ESC_STUB = (
    "global.esc = function (v) { return String(v == null ? '' : v)"
    ".replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')"
    ".replace(/\"/g, '&quot;').replace(/'/g, '&#39;'); };\n"
)


# =====================================================================================
# A. 配色按钮化：一个触发按钮 + 面板内单选列表（立即生效 + 持久化）
# =====================================================================================
def test_topbar_has_single_theme_button_not_button_group() -> None:
    html = _html()
    assert 'id="btn-theme"' in html
    assert 'aria-haspopup="dialog"' in html
    assert "🎨 配色" in html
    # 批9 的三个按钮组已按用户要求收进面板：顶栏不再有 theme-seg / .themeseg
    assert 'id="theme-seg"' not in html
    assert ".themeseg" not in html
    assert 'aria-pressed' not in html


def test_theme_panel_is_radio_list_with_hints() -> None:
    html = _html()
    assert 'id="themepanel"' in html
    assert 'role="radiogroup"' in html and 'id="tp-list"' in html
    # 单选列表由 themeChoiceHtml 生成，三套主题各带一句说明（CHOICES.hint）
    src = _fn("themeChoiceHtml")
    for token in ('type="radio"', 'name="theme-choice"', "data-theme-choice",
                  "data-modal-row", "当前", "可选", "c.hint"):
        assert token in src, token
    panel = _fn("renderThemePanel")
    assert "EditorTheme.CHOICES" in panel and "themeChoiceHtml" in panel


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过主题单选纯逻辑")
def test_theme_radio_selection_applies_and_persists() -> None:
    module = _marked("EDITOR_THEME")
    fns = (_ESC_STUB + "var EditorTheme = module.exports;\n"
           # 批12 · #13：renderThemeSeg 的按钮 title 会带当前字号 —— 单测桩补 EditorFont
           + "var EditorFont = { labelOf: function () { return '小'; } };\n"
           + _fn("themeStore") + "\n" + _fn("themeChoiceHtml") + "\n"
           + _fn("syncThemeChoices") + "\n" + _fn("renderThemeSeg") + "\n"
           + _fn("setTheme") + "\n" + _fn("initTheme") + "\n")
    harness = r"""
var out = {};
out.html = themeChoiceHtml({theme:'light', label:'浅色', hint:'浅底深字'}, 'light');
out.htmlOff = themeChoiceHtml({theme:'dark', label:'暗色', hint:'默认'}, 'light');

function Store() { this.m = {}; }
Store.prototype.getItem = function (k) {
  return Object.prototype.hasOwnProperty.call(this.m, k) ? this.m[k] : null; };
Store.prototype.setItem = function (k, v) { this.m[k] = String(v); };

var store = new Store();
global.window = { localStorage: store };
global.state = { theme: 'dark', fontSize: 'small' };

// 面板单选行（当前选中态更新走 syncThemeChoices）
function Radio(theme) { this.dataset = { themeChoice: theme }; this.checked = false; }
Radio.prototype.closest = function () { return this.row; };
function Row(theme) { this.st = { textContent: '' }; this.checked = false; this.theme = theme; }
Row.prototype.querySelector = function (sel) { return sel === '.st' ? this.st : null; };
function List(radios) { this.radios = radios; }
List.prototype.querySelectorAll = function () { return this.radios; };
List.prototype.addEventListener = function () {};
function Btn() { this.attrs = {}; }
Btn.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
var radios = [new Radio('dark'), new Radio('light'), new Radio('contrast')];
radios.forEach(function (r) { r.row = new Row(r.dataset.themeChoice); });
global.ELEMENTS = {};
global.el = function (id) {
  if (id === 'tp-list') { return new List(radios); }
  if (id === 'btn-theme') { return (global.ELEMENTS.btn = global.ELEMENTS.btn || new Btn()); }
  if (id === 'vtag') { return (global.ELEMENTS.vtag = global.ELEMENTS.vtag || new Btn()); }
  return null;
};
global.document = { documentElement: { _a: {},
  setAttribute: function (k, v) { this._a[k] = String(v); },
  getAttribute: function (k) { return this._a[k] === undefined ? null : this._a[k]; } } };
document.documentElement.setAttribute('data-theme', 'dark');

window.matchMedia = undefined;
initTheme();                                  // 从 <html data-theme> 读回
out.initial = global.state.theme;

setTheme('contrast', true);                   // 立即生效 + 持久化
out.after = global.state.theme;
out.stored = store.getItem(EditorTheme.STORE_KEY);
out.attr = document.documentElement.getAttribute('data-theme');
out.checked = radios.map(function (r) { return r.dataset.themeChoice + ':' + r.checked; });
out.status = radios.map(function (r) { return r.row.st.textContent; });
console.log(JSON.stringify(out));
"""
    out = _run_node(module + "\n" + fns + harness)
    assert 'data-theme-choice="light"' in out["html"] and "checked" in out["html"]
    assert "checked" not in out["htmlOff"]
    assert "浅底深字" in out["html"] and "当前" in out["html"]
    assert out["initial"] == "dark"
    assert out["after"] == "contrast"
    assert out["stored"] == "contrast"          # 单选 → 写 localStorage（键 qbot.editor.theme）
    assert out["attr"] == "contrast"            # 立即生效：只改 data-theme
    assert out["checked"] == ["dark:false", "light:false", "contrast:true"]
    assert out["status"] == ["可选", "可选", "当前"]


def test_setTheme_keeps_draft_and_only_touches_theme() -> None:
    body = _fn("setTheme")
    for forbidden in ("discardDraft", "reloadDetail", "loadEntries", "loadModules",
                      "draft", "state.entry", "location.reload"):
        assert forbidden not in body, forbidden
    init = _fn("initTheme")
    assert "EditorTheme.hasStored" in init and "data-theme-choice" in init


# =====================================================================================
# B/C/D. 公共弹层组件 + V15 细滚动条/筛选 + V16 居中/遮罩
# =====================================================================================
def test_both_panels_share_the_same_modal_component() -> None:
    html = _html()
    # 三个面板都是同一套 .mp-overlay/.mp 结构，且都带 data-modal
    # （批10 起 ⚙/🎨 共用；批11 的 📦 导出/导入沿用同一组件，不另写一套）
    assert html.count('class="mp-overlay" data-modal=') == 3
    assert 'data-modal="modpanel"' in html and 'data-modal="themepanel"' in html
    assert 'data-modal="transferpanel"' in html
    for token in ('id="modpanel"', 'id="themepanel"', 'id="transferpanel"'):
        assert token in html
    # 共用关闭按钮（data-modal-close）与共用列表/底栏 class
    assert html.count("data-modal-close") >= 6
    assert html.count('class="mp-list"') == 3
    assert html.count('class="mp-hd"') == 3
    assert html.count('class="mp-ft"') == 3
    # 两个面板都走同一个 EditorModal 实现 + 注册/绑定
    for fn in ("modalOpen", "modalClose", "modalActive", "modalEsc", "modalTrap",
               "modalFocusables", "modalOverlayClick", "modalFilter", "modalBind"):
        assert "function " + fn + "(" in html, fn
    assert 'modalOpen("modpanel", el("btn-settings"))' in html
    assert 'modalOpen("themepanel", el("btn-theme"))' in html
    assert 'modalBind("modpanel"' in html and 'modalBind("themepanel"' in html
    assert 'modalBind("transferpanel"' in html
    assert "modalEsc(e)" in html and "modalTrap(e)" in html


def test_v15_thin_scrollbar_and_keyword_filter() -> None:
    html = _html()
    css = _html()
    # 细滚动条：.mp-list 沿用 --sb-* 令牌（与左/中栏一致）
    m = re.search(r"\.mp-list::-webkit-scrollbar[^{]*\{([^}]*)\}", css)
    assert m and "var(--sb-size)" in m.group(1)
    m2 = re.search(r"\.mp-list::-webkit-scrollbar-thumb[^{]*\{([^}]*)\}", css)
    assert m2 and "var(--sb-thumb)" in m2.group(1) and "var(--radius-sb)" in m2.group(1)
    # 关键词筛选框 + 共用筛选实现（命中行真隐藏）
    assert 'id="mp-search"' in html and "data-modal-search" in html
    assert "function modalFilter(" in html
    assert ".mp-row[hidden] { display: none; }" in html
    bind = _fn("modalBind")
    assert "modalFilter(" in bind and "searchInput" in bind


def test_v16_centered_panel_with_light_overlay() -> None:
    html = _html()
    body = re.search(r"\.mp-overlay\s*\{([^}]*)\}", html).group(1)  # type: ignore[union-attr]
    assert "align-items: center" in body
    assert "justify-content: center" in body
    assert "var(--overlay)" in body
    # 点遮罩关闭：overlay 的点击走共用 modalOverlayClick
    assert "function modalOverlayClick(" in html
    assert "e.target === modalEl(id)" in html
    # 遮罩是颜色令牌，三套主题都给值（由 batch9 集合相等断言守，这里点名）
    assert "--overlay" in _tokens_css()


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过弹层纯逻辑")
def test_modal_open_close_esc_focus_and_filter() -> None:
    block = _marked("EDITOR_MODAL")
    harness = r"""
var out = {};
function El(id, kids) {
  this.id = id; this.hidden = true; this.dataset = {}; this.kids = kids || [];
  this.listeners = {}; this.attrs = {}; this.focused = false;
}
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return this.kids; };
El.prototype.addEventListener = function (t, fn) {
  (this.listeners[t] = this.listeners[t] || []).push(fn); };
El.prototype.focus = function () { this.focused = true; global.document.activeElement = this; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };

var trigger = new El('trigger');
var btnA = new El('a'), btnB = new El('b');
var root = new El('modpanel', [btnA, btnB]);
global.ELEMENTS = { modpanel: root };
global.el = function (id) { return global.ELEMENTS[id] || null; };
global.document = { activeElement: trigger };

out.openRet = modalOpen('modpanel', trigger);
out.opened = modalIsOpen('modpanel');
out.focusFirst = btnA.focused;
out.active = modalActive();
out.escOther = modalEsc({ key: 'x' });
out.esc = modalEsc({ key: 'Escape' });
out.closed = !modalIsOpen('modpanel');
out.focusBack = trigger.focused;

// 点遮罩：只有 target === 根节点才关
modalOpen('modpanel', trigger);
out.overlayInner = modalOverlayClick({ target: btnA }, 'modpanel');
out.stillOpen = modalIsOpen('modpanel');
out.overlaySelf = modalOverlayClick({ target: root }, 'modpanel');
out.nowClosed = !modalIsOpen('modpanel');

// 筛选：按可见文本（含说明）不区分大小写过滤，命中行真隐藏
function Row(text) { this.textContent = text; this.hidden = false; }
function Host(rows) { this.rows = rows; }
Host.prototype.querySelectorAll = function () { return this.rows; };
var rows = [new Row('技能 skills 玩家技能'), new Row('地图 maps 地图场景'), new Row('物品 items')];
var host = new Host(rows);
out.shownNone = modalFilter(host, '', '[data-modal-row]');
out.shown = modalFilter(host, ' 技能 ', '[data-modal-row]');
out.hidden = rows.map(function (r) { return r.hidden; });

// Tab 焦点环：末个 Tab 回第一个，首个 Shift+Tab 回末个
modalOpen('modpanel', trigger);
document.activeElement = btnB;
var e1 = { key: 'Tab', shiftKey: false, preventDefault: function () { this.pd = true; } };
out.trapLast = modalTrap(e1); out.trapFocused = document.activeElement === btnA;
document.activeElement = btnA;
var e2 = { key: 'Tab', shiftKey: true, preventDefault: function () { this.pd = true; } };
out.trapFirst = modalTrap(e2); out.trapBack = document.activeElement === btnB;
console.log(JSON.stringify(out));
"""
    out = _run_node(block + "\n" + harness)
    assert out["openRet"] is True and out["opened"] is True
    assert out["focusFirst"] is True and out["active"] == "modpanel"
    assert out["escOther"] is False and out["esc"] is True and out["closed"] is True
    assert out["focusBack"] is True                       # 焦点回到触发按钮
    assert out["overlayInner"] is False and out["stillOpen"] is True
    assert out["overlaySelf"] is True and out["nowClosed"] is True   # 点遮罩关闭
    assert out["shownNone"] == 3
    assert out["shown"] == 1 and out["hidden"] == [False, True, True]
    assert out["trapLast"] is True and out["trapFocused"] is True
    assert out["trapFirst"] is True and out["trapBack"] is True


def test_modal_aria_and_keyboard_reachability() -> None:
    html = _html()
    assert html.count('role="dialog"') == 3
    assert html.count('aria-modal="true"') == 3
    assert "Esc 关闭" in html or "modalEsc" in html
    assert "data-modal-close" in html
    # 顶栏触发按钮键盘可达（原生 button），面板内焦点环走 --focus
    assert "var(--focus-offset) var(--focus)" in html


# =====================================================================================
# E/F. 自定义背景图：来源、应用方式、兜底层、透明度、清除、预览、兜底
# =====================================================================================
def test_background_layers_and_theme_backing_exist() -> None:
    html = _html()
    # 页面底层图片层：cover + fixed
    img = re.search(r"\.bgimg\s*\{([^}]*)\}", html).group(1)  # type: ignore[union-attr]
    assert "background-size: cover" in img
    assert "background-attachment: fixed" in img
    assert "position: fixed" in img
    assert 'id="bgimg"' in html and 'id="bgbase"' in html
    # **内容与背景之间的主题底色兜底层**（静态断言）：background: var(--bg-scrim)
    base = re.search(r"\.bgbase\s*\{([^}]*)\}", html).group(1)  # type: ignore[union-attr]
    assert "background: var(--bg-scrim)" in base
    assert "z-index: -1" in base and "z-index: -2" in img
    # 三套主题都定义 --bg-scrim（底色兜底层随主题换色）
    css = re.sub(r"/\*.*?\*/", "", _tokens_css(), flags=re.S)
    for sel in (":root", 'html[data-theme="light"]', 'html[data-theme="contrast"]'):
        start = css.index(sel)
        block = css[start:css.index("}", start)]
        assert "--bg-scrim" in block, sel
    # 内容层不透明遮掩：.app 在上层
    app = re.search(r"\.app\s*\{([^}]*)\}", html).group(1)  # type: ignore[union-attr]
    assert "z-index: 0" in app


def test_background_controls_sources_opacity_preview_and_clear() -> None:
    html = _html()
    for token in ('id="bg-file"', 'accept="image/*"', 'id="bg-url"', 'id="bg-url-apply"',
                  'id="bg-op"', 'type="range"', 'min="0"', 'max="100"', 'step="1"',
                  'aria-valuenow="60"', 'aria-valuemin="0"', 'aria-valuemax="100"',
                  'id="bg-clear"', 'id="bg-prev-img"', 'id="bg-prev-note"', 'id="bg-msg"'):
        assert token in html, token
    # 本地文件走 FileReader → dataURL；URL 走 Image 探针（拉不到给人话，不写坏状态）
    file_fn = _fn("bgOnFile")
    assert "FileReader" in file_fn and "readAsDataURL" in file_fn and "fileError" in file_fn
    url_fn = _fn("bgOnUrl")
    assert "new Image()" in url_fn and "onerror" in url_fn and "拉不到图片" in url_fn
    # 滑块实时生效 + aria-valuenow 同步 + 持久化
    init = _fn("initBg")
    assert "EditorBg.saveOpacity" in init and "aria-valuenow" in init
    assert "bgApply()" in init
    # 清除按钮
    assert "bgDoClear" in html and "bgDoClear" in _fn("initBg")


def test_background_is_local_only_and_never_writes_content_packs() -> None:
    block = _marked("EDITOR_BG") + _marked("EDITOR_MODAL")
    bg_fns = "".join(_fn(n) for n in ("bgOnFile", "bgOnUrl", "bgCommit", "bgDoClear", "initBg"))
    src = block + bg_fns
    # 不上传服务器：无 fetch/XHR/POST、无内容包路径
    for forbidden in ("fetch(", "XMLHttpRequest", "api(", "/api/", "content/", "POST"):
        assert forbidden not in src, forbidden
    # 说明文案明确「不上传服务器」
    assert "不上传服务器" in _html() or "不上传" in _html()
    # 存储键名固定（localStorage 首选）
    assert '"qbot.editor.bg.image"' in block or "'qbot.editor.bg.image'" in block
    assert "qbot.editor.bg.opacity" in block
    assert "indexedDB" in _html() or "IndexedDB" in _html()


# =====================================================================================
# F. 背景图纯逻辑（node 执行 EditorBg）：clamp / 键名 / 回退 / 兜底分支
# =====================================================================================
@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过背景图纯逻辑")
def test_bg_module_clamp_keys_and_fallbacks() -> None:
    block = _marked("EDITOR_BG")
    harness = r"""
var B = module.exports;
function Store() { this.m = {}; this.throwQuota = false; }
Store.prototype.getItem = function (k) {
  return Object.prototype.hasOwnProperty.call(this.m, k) ? this.m[k] : null; };
Store.prototype.setItem = function (k, v) {
  if (this.throwQuota) { throw new Error('QuotaExceededError'); } this.m[k] = String(v); };
Store.prototype.removeItem = function (k) { delete this.m[k]; };

var out = {};
out.keys = [B.IMAGE_KEY, B.OPACITY_KEY];
out.defaultOpacity = B.DEFAULT_OPACITY;
out.clamp = [B.clampOpacity(-1), B.clampOpacity(0), B.clampOpacity(33.4), B.clampOpacity(100),
             B.clampOpacity(101), B.clampOpacity('nope'), B.clampOpacity(null),
             B.clampOpacity('55')];
out.classify = [B.classify(null), B.classify('data:image/png;base64,AAA'),
                B.classify('https://img/a.png'), B.classify('javascript:alert(1)')];
out.fileErr = [B.fileError({name:'a.txt', type:'text/plain', size:10}),
               B.fileError({name:'huge.png', type:'image/png', size:9 * 1024 * 1024}),
               B.fileError(null),
               B.fileError({name:'ok.png', type:'image/png', size:1000})];
out.urlErr = [B.urlError(''), B.urlError('ftp://x/a.png'), B.urlError('https://x/a.png')];
out.sizeText = [B.sizeText(2048), B.sizeText(9 * 1024 * 1024)];
console.log(JSON.stringify(out));
"""
    out = _run_node(block + "\n" + harness)
    assert out["keys"] == ["qbot.editor.bg.image", "qbot.editor.bg.opacity"]
    assert out["defaultOpacity"] == 60
    assert out["clamp"] == [0, 0, 33, 100, 100, 60, 60, 55]
    assert out["classify"] == ["none", "data", "http", "invalid"]
    assert out["fileErr"][0] and "不是图片" in out["fileErr"][0]
    assert out["fileErr"][1] and "超过单张" in out["fileErr"][1]
    assert out["fileErr"][2] and "没有选到文件" in out["fileErr"][2]
    assert out["fileErr"][3] == ""
    assert out["urlErr"][0] and "请先填写" in out["urlErr"][0]
    assert out["urlErr"][1] and "http 或 https" in out["urlErr"][1]
    assert out["urlErr"][2] == ""
    assert out["sizeText"] == ["2KB", "9MB"]


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过背景图存储回退")
def test_bg_save_load_clear_and_indexeddb_fallback() -> None:
    block = _marked("EDITOR_BG")
    harness = r"""
var B = module.exports;
function Store() { this.m = {}; this.throwQuota = false; }
Store.prototype.getItem = function (k) {
  return Object.prototype.hasOwnProperty.call(this.m, k) ? this.m[k] : null; };
Store.prototype.setItem = function (k, v) {
  if (this.throwQuota) { throw new Error('QuotaExceededError'); } this.m[k] = String(v); };
Store.prototype.removeItem = function (k) { delete this.m[k]; };

var s = new Store();
var out = {};
out.empty = B.loadLocal(s);
out.badStored = (function () {
  var q = new Store(); q.m[B.IMAGE_KEY] = 'javascript:bad'; q.m[B.OPACITY_KEY] = '999';
  var r = B.loadLocal(q);
  return [r.image, r.opacity, r.source];
})();
Promise.resolve()
  .then(function () {
    return B.save(s, null, { image: 'data:image/png;base64,AAAA', opacity: 120 }); })
  .then(function (r) {
    out.saveLocal = r;
    out.raw = [s.getItem(B.IMAGE_KEY), s.getItem(B.OPACITY_KEY)];
    out.load = B.loadLocal(s);
    return B.save(s, null, { image: null, opacity: -3 });
  })
  .then(function (r) {
    out.saveRemoved = r;
    out.rawRemoved = s.getItem(B.IMAGE_KEY);
    var q = new Store(); q.throwQuota = true;
    var idb = { saved: null, put: function (v) { idb.saved = v; return Promise.resolve('ok'); } };
    return B.save(q, idb, { image: 'data:image/png;base64,ZZZZ', opacity: 50 })
      .then(function (r2) {
        out.saveIdb = r2; out.idbSaved = idb.saved;
        return B.save(q, null, { image: 'data:image/png;base64,ZZZZ', opacity: 50 });
      })
      .then(function (r3) { out.saveNoIdb = r3; });
  })
  .then(function () {
    // IndexedDB 兜底读：适配器有 get → 返回图片；没有 → null 不崩
    var idb2 = { get: function () { return Promise.resolve('data:image/png;base64,IIII'); } };
    return B.idbGet(idb2).then(function (v) { out.idbGet = v; });
  })
  .then(function () {
    return B.idbGet(null).then(function (v) { out.idbGetNull = v; });
  })
  .then(function () {
    var s2 = new Store(); s2.m[B.IMAGE_KEY] = 'x'; s2.m[B.OPACITY_KEY] = '20';
    var idb3 = { del: function () { idb3.deleted = true; return Promise.resolve(); } };
    return B.clear(s2, idb3).then(function (r) {
      out.clear = r; out.left = [s2.getItem(B.IMAGE_KEY), s2.getItem(B.OPACITY_KEY)];
      out.idbDeleted = !!idb3.deleted;
    });
  })
  .then(function () {
    out.saveOpacity = [B.saveOpacity(s, 250), B.saveOpacity(s, '40'), B.saveOpacity(s, '-5')];
    console.log(JSON.stringify(out));
  });
"""
    out = _run_node(block + "\n" + harness)
    assert out["empty"] == {"image": None, "opacity": 60, "source": "none"}
    # 坏存储值：非法图片丢弃、透明度 clamp
    assert out["badStored"] == [None, 100, "none"]
    assert out["saveLocal"]["ok"] is True and out["saveLocal"]["where"] == "local"
    assert out["saveLocal"]["opacity"] == 100
    assert out["raw"] == ["data:image/png;base64,AAAA", "100"]
    assert out["load"] == {"image": "data:image/png;base64,AAAA", "opacity": 100, "source": "data"}
    assert out["saveRemoved"]["ok"] is True and out["rawRemoved"] is None
    # 配额超限 → IndexedDB 兜底
    assert out["saveIdb"]["ok"] is True and out["saveIdb"]["where"] == "indexeddb"
    assert out["idbSaved"] == "data:image/png;base64,ZZZZ"
    # 配额超限且无 IndexedDB → 人话提示，不崩
    assert out["saveNoIdb"]["ok"] is False and out["saveNoIdb"]["where"] == "none"
    assert "图片太大" in out["saveNoIdb"]["reason"]
    assert out["idbGet"] == "data:image/png;base64,IIII" and out["idbGetNull"] is None
    assert out["clear"] == {"ok": True} and out["left"] == [None, None]
    assert out["idbDeleted"] is True
    assert out["saveOpacity"][0]["opacity"] == 100
    assert out["saveOpacity"][1]["opacity"] == 40
    assert out["saveOpacity"][2]["opacity"] == 0


# =====================================================================================
# G. 页脚批次串 + 通用性护栏
# =====================================================================================
def test_footer_batch_string_is_current() -> None:
    html = _html()
    assert BATCH_NOTE in html
    assert "批14 · 可编辑性与提示" not in html
    assert "批13.1 · 段入口" not in html
    assert "批11 · 内容包导出/导入" not in html
    assert "批9 · 配色切换" not in html
    assert "批6 · 新增/删除条目 + 检索" not in html
    assert "批5.2 · 视觉细则清零" not in html
    assert "批3 · 分区页签" not in html
    # 产品名不含批次（批9.2 约束不回退）
    comp = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert comp is not None and "批23" in comp.group(1)


def test_batch10_frontend_has_no_pack_business_names() -> None:
    src = (_marked("EDITOR_MODAL") + _marked("EDITOR_BG")
           + "".join(_fn(n) for n in ("themeChoiceHtml", "syncThemeChoices",
                                      "renderThemeSeg", "setTheme", "initTheme",
                                      "renderThemePanel", "bgApply", "bgOnFile",
                                      "bgOnUrl", "bgCommit", "bgDoClear", "initBg")))
    for word in ("veinborn", "test_demo", "skill_chains", "equipment", "怪物", "装备"):
        assert word not in src, word


def test_theme_panel_section_uses_tokens_only() -> None:
    html = _html()
    for begin in (".mp-sec {", ".mp-search {", ".mp-tools {", ".bg-url {", ".bg-prev {"):
        start = html.index(begin)
        seg = html[start:html.index("}", start) + 1]
        assert "var(--" in seg, begin
        assert not re.search(r"#[0-9a-fA-F]{3,6}", seg), begin


def test_theme_list_not_shrunk_by_panel_maxheight() -> None:
    """批10 补（实测 bug）：配色列表 3 项曾被面板 84vh 限高挤压成只显 1 项。

    断言：配色列表不许作为可收缩 flex 子项（flex:0 0 auto + 无 max-height），
    面板在矮视口下靠自身滚动兜底。
    """
    html = _html()
    assert "#tp-list { flex: 0 0 auto; max-height: none; }" in html
    assert ".mp { overflow: auto; }" in html
