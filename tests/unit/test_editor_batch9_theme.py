"""编辑器重写批9 · 配色切换（主题）（docs/编辑器重写_实现方案.md §四 批9）。

覆盖任务书要求：
  A. **三套主题令牌完整**：`:root` = 暗色（默认，数值不变）；
     `html[data-theme="light"]` / `html[data-theme="contrast"]` **只覆盖颜色类令牌**，
     与 :root 的颜色令牌集合**逐一相等（不漏键、不多键）**；尺寸/字号/行高/间距/
     圆角/边框宽度/字体栈等令牌绝不出现在主题块里（继承 :root）。
  B. **切换纯逻辑（node 可执行）**：`EditorTheme` 的 isTheme/normalize/systemTheme/
     resolveInitialTheme/applyTheme 语义。
  C. **持久化键与初值回退**：键 `qbot.editor.theme`；显式选择写 localStorage；
     无存储 → 跟随系统 `prefers-color-scheme`（light → 浅色，否则暗色）；
     非法存储值不生效（仍跟随系统）。
  D. **data-theme 属性设置与还原**：`<head>` 引导脚本在首次绘制前按存储/系统设置
     `<html data-theme>`；`applyTheme` 非法值回退暗色；连续切换正确覆盖属性。
  E. **无障碍**：高对比主题下红/黄提示与禁用态**不单靠色相**（双线/虚线/点线 + 符号）；
     正文与警示色对底色对比度 ≥ WCAG AA 4.5:1（暗色/浅色/高对比三套都验）。
  F. **样式不得硬写色值**：`index.html` 的 `<style>` 段颜色一律 `var(--…)`
     （正则扫 hex/rgb/hsl 零命中）；设计侧 tokens.css 与编辑器实现**同源同值**。

不触碰任何内容包；不写盘（node 断言文件写 tmp_path）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Tuple

import pytest

from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
TOKENS = REPO / "qbot_rpg" / "web" / "static" / "tokens.css"
DESIGN_DIR = Path("/root/editor_design")
DESIGN_TOKENS = DESIGN_DIR / "tokens.css"
DESIGN_COMPONENTS = DESIGN_DIR / "components.html"

THEME_SELECTORS = (":root", 'html[data-theme="light"]', 'html[data-theme="contrast"]')
COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", re.I)
# 只用于「正文 / 警示」对比度的令牌（装饰性弱文字 --text-4/5/6 不做 AA 要求）。
AA_TOKENS = ("text", "text-strong", "text-value", "text-btn", "text-2", "text-3",
             "accent", "ok", "warn", "danger", "info")


# ---------------------------------------------------------------------------
# 通用读取 / 解析
# ---------------------------------------------------------------------------
def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _tokens_css() -> str:
    return TOKENS.read_text(encoding="utf-8")


def _marked(begin: str, end: str) -> str:
    m = re.search(re.escape(begin) + r"(.*?)" + re.escape(end), _html(), re.S)
    assert m is not None, f"index.html 缺少标记块 {begin} … {end}"
    return m.group(1)


def _fn_body(name: str) -> str:
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


def _blocks(css: str) -> Dict[str, str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    return {m.group(1).strip(): m.group(2)
            for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css)}


def _decls(body: str) -> Dict[str, str]:
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"--([a-z0-9-]+)\s*:\s*([^;]+);", body)}


def _color_tokens(decls: Dict[str, str]) -> Dict[str, str]:
    return {k: v for k, v in decls.items() if COLOR_RE.search(v)}


def _rgb(hx: str) -> Tuple[float, float, float]:
    h = hx.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))  # type: ignore[return-value]


def _lum(hx: str) -> float:
    def lin(c: float) -> float:
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = _rgb(hx)
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _lum(fg), _lum(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def _theme_table() -> Dict[str, Dict[str, str]]:
    blocks = _blocks(_tokens_css())
    return {sel: _decls(blocks[sel]) for sel in THEME_SELECTORS}


def _run_node(script: str) -> Dict[str, Any]:
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# =====================================================================================
# A. 三套主题令牌完整（本批验收重点：不得漏键）
# =====================================================================================
def test_root_default_is_dark_and_unchanged() -> None:
    root = _theme_table()[":root"]
    assert root["bg"] == "#0a0a0a" and root["accent"] == "#9ad48c"
    assert root["text"] == "#d2d2d2" and root["surface"] == "#151515"
    # 批9 新增的两个浮层颜色令牌（原先硬写在 index.html 里）
    assert COLOR_RE.search(root["shadow"]) and COLOR_RE.search(root["overlay"])


def test_three_themes_cover_the_same_color_tokens_exactly() -> None:
    """主题块与 :root 的颜色令牌集合必须逐一相等：不漏键、不多键、不掺尺寸令牌。"""
    table = _theme_table()
    root_color = set(_color_tokens(table[":root"]))
    assert len(root_color) >= 30, sorted(root_color)
    for sel in ('html[data-theme="light"]', 'html[data-theme="contrast"]'):
        decls = table[sel]
        color = _color_tokens(decls)
        missing = sorted(root_color - set(color))
        extra = sorted(set(decls) - root_color)
        assert not missing, f"{sel} 漏颜色令牌：{missing}"
        assert not extra, f"{sel} 多declared/非颜色令牌：{extra}"
        # 主题块里每个值都必须是颜色字面量（不得指向别的 var 绕开覆盖）
        for k, v in color.items():
            assert COLOR_RE.search(v), (sel, k, v)


def test_theme_blocks_never_override_size_or_font_tokens() -> None:
    """尺寸/字号/行高/间距/圆角/边框宽度/字体栈令牌只允许在 :root 里定义。"""
    blocks = _blocks(_tokens_css())
    root = _decls(blocks[":root"])
    dim_tokens = set(root) - set(_color_tokens(root))
    assert "fs-12" in dim_tokens and "sp-6" in dim_tokens and "font-mono" in dim_tokens
    assert "focus-offset" in dim_tokens and "radius" in dim_tokens and "bw-accent" in dim_tokens
    for sel in ('html[data-theme="light"]', 'html[data-theme="contrast"]'):
        assert not (set(_decls(blocks[sel])) & dim_tokens), sel


def test_theme_switch_is_pure_token_layer() -> None:
    """三套主题改的只是颜色取值，版式令牌在三套下同值（抽查若干）。"""
    table = _theme_table()
    blocks = _blocks(_tokens_css())
    only_root = {k: v for k, v in _decls(blocks[":root"]).items()
                 if k not in table[":root"]}
    assert only_root == {}  # 所有 :root 令牌都在解析结果里（解析完整）
    for sel in ('html[data-theme="light"]', 'html[data-theme="contrast"]'):
        assert set(table[sel]) == set(_color_tokens(table[":root"]))
    # 非颜色令牌在三套下同值 = 只存在于 :root，无覆盖
    assert "fs-12" not in table['html[data-theme="light"]']


# =====================================================================================
# B. 切换纯逻辑（node 可执行）
# =====================================================================================
@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过切换纯逻辑执行")
def test_theme_module_switching_pure_logic() -> None:
    block = _marked("/* EDITOR_THEME_BEGIN */", "/* EDITOR_THEME_END */")
    script = (
        "var T = module.exports;\n"
        "var out = {};\n"
        "out.themes = T.THEMES;\n"
        "out.default = T.DEFAULT_THEME;\n"
        "out.isTheme = [T.isTheme('dark'), T.isTheme('light'), T.isTheme('contrast'),"
        " T.isTheme('sepia'), T.isTheme(null)];\n"
        "out.normalize = [T.normalize('light'), T.normalize('zzz'), T.normalize(undefined)];\n"
        "out.system = [T.systemTheme(true), T.systemTheme(false)];\n"
        "out.initial = [T.resolveInitialTheme(null, false), T.resolveInitialTheme(null, true),"
        " T.resolveInitialTheme('contrast', false), T.resolveInitialTheme('sepia', true)];\n"
        "out.labels = T.CHOICES.map(function (c) { return c.label; });\n"
        "out.hints = T.CHOICES.map(function (c) { return !!c.hint; });\n"
        "out.labelOf = [T.labelOf('dark'), T.labelOf('light'), T.labelOf('contrast'),"
        " T.labelOf('x')];\n"
        "console.log(JSON.stringify(out));"
    )
    # 内联块走 UMD：node 下把工厂结果放进 module.exports；拼在 block 之后读取。
    out = _run_node(block + "\n" + script)
    assert out["themes"] == ["dark", "light", "contrast"]
    assert out["default"] == "dark"
    assert out["isTheme"] == [True, True, True, False, False]
    assert out["normalize"] == ["light", "dark", "dark"]
    assert out["system"] == ["light", "dark"]
    # 无存储 → 跟随系统；有存储 → 用存储；非法存储 → 丢弃、跟随系统
    assert out["initial"] == ["dark", "light", "contrast", "light"]
    assert out["labels"] == ["暗色", "浅色", "高对比"]
    assert out["hints"] == [True, True, True]
    assert out["labelOf"] == ["暗色", "浅色", "高对比", "暗色"]


# =====================================================================================
# C. 持久化键与初值回退（无存储 → 跟随系统）
# =====================================================================================
@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过持久化执行")
def test_theme_persistence_key_and_system_fallback() -> None:
    block = _marked("/* EDITOR_THEME_BEGIN */", "/* EDITOR_THEME_END */")
    script = (
        "var T = module.exports;\n"
        "function fakeStore() { this.m = {}; }\n"
        "fakeStore.prototype.getItem = function (k) {"
        " return Object.prototype.hasOwnProperty.call(this.m, k) ? this.m[k] : null; };\n"
        "fakeStore.prototype.setItem = function (k, v) { this.m[k] = String(v); };\n"
        "fakeStore.prototype.removeItem = function (k) { delete this.m[k]; };\n"
        "var s = new fakeStore();\n"
        "var out = { key: T.STORE_KEY };\n"
        "out.fresh = T.loadTheme(s, false);\n"          # 无存储 → 暗色
        "out.freshLight = T.loadTheme(s, true);\n"      # 无存储 + 系统浅色 → 浅色
        "out.saved = T.saveTheme(s, 'contrast');\n"
        "out.raw = s.getItem(T.STORE_KEY);\n"
        "out.loaded = T.loadTheme(s, true);\n"          # 有存储 → 存储优先于系统
        "out.has = T.hasStored(s);\n"
        "out.savedBad = T.saveTheme(s, 'sepia');\n"     # 非法值归一为默认暗色后写入
        "out.rawBad = s.getItem(T.STORE_KEY);\n"
        "out.cleared = T.clearTheme(s);\n"
        "out.afterClear = T.loadTheme(s, true);\n"      # 清掉 → 重新跟随系统
        "var broken = { getItem: function () { throw new Error('x'); },"
        " setItem: function () { throw new Error('x'); } };\n"
        "out.brokenLoad = T.loadTheme(broken, true);\n"
        "out.brokenSave = T.saveTheme(broken, 'light');\n"
        "out.brokenHas = T.hasStored(broken);\n"
        "console.log(JSON.stringify(out));"
    )
    out = _run_node(block + "\n" + script)
    assert out["key"] == "qbot.editor.theme"
    assert out["fresh"] == "dark" and out["freshLight"] == "light"
    assert out["saved"] is True and out["raw"] == "contrast"
    assert out["loaded"] == "contrast" and out["has"] is True
    assert out["savedBad"] is True and out["rawBad"] == "dark"
    assert out["cleared"] is True and out["afterClear"] == "light"
    # localStorage 抛异常（隐私模式）也不崩：读回退系统、写返回 False
    assert out["brokenLoad"] == "light" and out["brokenSave"] is False
    assert out["brokenHas"] is False


# =====================================================================================
# D. data-theme 属性设置与还原
# =====================================================================================
@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过 data-theme 执行")
def test_apply_theme_sets_and_restores_attribute() -> None:
    block = _marked("/* EDITOR_THEME_BEGIN */", "/* EDITOR_THEME_END */")
    script = (
        "var T = module.exports;\n"
        "function E() { this.a = {}; }\n"
        "E.prototype.setAttribute = function (k, v) { this.a[k] = String(v); };\n"
        "E.prototype.getAttribute = function (k) {"
        " return Object.prototype.hasOwnProperty.call(this.a, k) ? this.a[k] : null; };\n"
        "function apply(el, t) { return T.applyTheme(el, t); }\n"
        "var el = new E();\n"
        "el.setAttribute('data-theme', 'dark');\n"
        "var out = { before: el.getAttribute('data-theme') };\n"
        "out.retLight = apply(el, 'light'); out.light = el.getAttribute('data-theme');\n"
        "out.retContrast = apply(el, 'contrast'); out.contrast = el.getAttribute('data-theme');\n"
        "out.retBad = apply(el, 'sepia'); out.bad = el.getAttribute('data-theme');\n"
        "out.retDark = apply(el, 'dark'); out.restored = el.getAttribute('data-theme');\n"
        "out.nullEl = T.applyTheme(null, 'light');\n"
        "console.log(JSON.stringify(out));"
    )
    out = _run_node(block + "\n" + script)
    assert out["before"] == "dark"
    assert out["retLight"] == "light" and out["light"] == "light"
    assert out["retContrast"] == "contrast" and out["contrast"] == "contrast"
    assert out["retBad"] == "dark" and out["bad"] == "dark"   # 非法值回退默认并写回属性
    assert out["retDark"] == "dark" and out["restored"] == "dark"
    assert out["nullEl"] == "light"                            # 无 DOM 也不崩


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过 <head> 引导执行")
def test_head_bootstrap_sets_data_theme_before_paint(tmp_path: Path) -> None:
    """`<head>` 引导：首次绘制前按「存储优先，无存储跟随系统」设置 data-theme。"""
    m = re.search(r'<link rel="stylesheet" href="/static/tokens.css">\s*<script>(.*?)</script>',
                  _html(), re.S)
    assert m is not None, "index.html <head> 缺少配色引导脚本"
    head_src = m.group(1)
    script_file = tmp_path / "theme_head.js"
    script_file.write_text(head_src, encoding="utf-8")
    harness = tmp_path / "run_head.js"
    harness.write_text(
        "var fs = require('fs'), vm = require('vm');\n"
        "var src = fs.readFileSync(process.argv[2], 'utf8');\n"
        "function run(light, stored) {\n"
        "  var ctx = { console: console };\n"
        "  ctx.window = { matchMedia: function () {"
        " return { matches: light, addEventListener: function () {} }; },\n"
        "    localStorage: { getItem: function (k) {"
        " return k === 'qbot.editor.theme' ? stored : null; } } };\n"
        "  ctx.document = { documentElement: { _a: {},\n"
        "    setAttribute: function (k, v) { this._a[k] = v; },\n"
        "    getAttribute: function (k) {"
        " return this._a[k] === undefined ? null : this._a[k]; } } };\n"
        "  vm.createContext(ctx);\n"
        "  vm.runInContext(src, ctx);\n"
        "  return ctx.document.documentElement._a['data-theme'];\n"
        "}\n"
        "console.log(JSON.stringify({ dark: run(false, null), light: run(true, null),\n"
        "  stored: run(false, 'contrast'), storedLight: run(true, 'light'),\n"
        "  bogus: run(true, 'sepia') }));\n",
        encoding="utf-8")
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, str(harness), str(script_file)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["dark"] == "dark"        # 无存储 + 系统暗 → 暗色
    assert out["light"] == "light"      # 无存储 + 系统浅 → 浅色（首次跟随系统）
    assert out["stored"] == "contrast"  # 有存储 → 存储优先
    assert out["storedLight"] == "light"
    assert out["bogus"] == "light"      # 非法存储 → 丢弃、跟随系统


def test_head_bootstrap_theme_names_match_module() -> None:
    """引导脚本与纯逻辑模块对「键 + 三套主题名」口径一致（防加第四套时漏改一处）。"""
    module = _marked("/* EDITOR_THEME_BEGIN */", "/* EDITOR_THEME_END */")
    m = re.search(r'<link rel="stylesheet" href="/static/tokens.css">\s*<script>(.*?)</script>',
                  _html(), re.S)
    assert m is not None
    head_tail = m.group(1).split("/* EDITOR_THEME_END */")[-1]
    assert "EditorTheme.loadTheme" in head_tail and "EditorTheme.applyTheme" in head_tail
    for name in ("dark", "light", "contrast"):
        assert f'"{name}"' in module, (name, "纯逻辑模块缺少主题名")
    assert "qbot.editor.theme" in module and "prefers-color-scheme" in head_tail


# =====================================================================================
# E. 覆盖完整性：高对比用形状辨识 + 三套主题 AA 对比度
# =====================================================================================
def test_contrast_theme_distinguishes_states_without_hue() -> None:
    html = _html()
    # 红/黄提示：双线 vs 虚线 + 方块/三角符号；禁用态：点线 + 降透明度
    assert 'html[data-theme="contrast"] .vbox.red' in html
    assert "double var(--danger)" in html
    assert 'html[data-theme="contrast"] .vbox.warn' in html
    assert "dashed var(--warn)" in html
    assert 'html[data-theme="contrast"] .vbox.red .vhead::before' in html
    assert 'html[data-theme="contrast"] .vbox.warn .vhead::before' in html
    assert 'html[data-theme="contrast"] .btn:disabled' in html and "dotted" in html
    assert "\\25a0" in html and "\\25b2" in html      # ■ / ▲ 符号
    # 形状之外，两色本身在 token 层就是不同值
    contrast = _theme_table()['html[data-theme="contrast"]']
    assert contrast["warn"] != contrast["danger"]


def test_all_three_themes_meet_wcag_aa_for_body_and_alerts() -> None:
    table = _theme_table()
    for sel in THEME_SELECTORS:
        d = table[sel]
        bg = d["bg"]
        for key in AA_TOKENS:
            assert COLOR_RE.match(d[key]), (sel, key, d[key])
            ratio = _contrast(d[key], bg)
            assert ratio >= 4.5, f"{sel} {key}={d[key]} on {bg} 对比度 {ratio:.2f} < 4.5"


# =====================================================================================
# F. 硬写色值静态断言 + 设计侧同源同值
# =====================================================================================
def test_index_style_has_no_hardcoded_colors() -> None:
    """`<style>` 段颜色必须走令牌：hex / rgb / hsl 字面量零命中（transparent 允许）。"""
    html = _html()
    style = html[html.index("<style>") + len("<style>"):html.index("</style>")]
    hits = COLOR_RE.findall(style)
    assert hits == [], f"style 段出现硬写色值：{hits}"
    assert "--overlay" in style and "--shadow" in style
    assert "tokens.css" in html


def test_repo_and_design_tokens_are_identical() -> None:
    if not DESIGN_TOKENS.exists():
        pytest.skip("设计侧 /root/editor_design 不在本机")
    assert DESIGN_TOKENS.read_text(encoding="utf-8") == _tokens_css()


def test_design_components_inlines_same_tokens() -> None:
    if not DESIGN_COMPONENTS.exists():
        pytest.skip("设计侧 /root/editor_design 不在本机")
    html = DESIGN_COMPONENTS.read_text(encoding="utf-8")
    bar = "/* ============================================================"
    start = bar + "\n   蚀脉猎师 · 内容编辑器 — 设计令牌（tokens.css）"
    end = bar + "\n   第二部分"
    i, j = html.index(start), html.index(end, html.index(start))
    inlined = html[i:j].strip()
    assert inlined == _tokens_css().strip(), "components.html 内联令牌与 tokens.css 不同步"


# =====================================================================================
# G. 前端接线 + 无障碍 + 通用性
# =====================================================================================
def test_frontend_theme_control_markup_and_aria() -> None:
    """批10：批9 的三个按钮按用户要求收进「🎨 配色」按钮 + 面板内单选列表。

    本用例只改「交互形态」断言；三套主题的令牌/切换/持久化/AA 断言全部照旧（见上）。
    """
    html = _html()
    for token in ('id="btn-theme"', 'aria-haspopup="dialog"', "🎨 配色",
                  'id="themepanel"', 'id="tp-list"', 'role="radiogroup"',
                  'aria-label="配色主题（单选）"', "themeChoiceHtml",
                  'name="theme-choice"', "EditorTheme.CHOICES", 'data-theme-choice'):
        assert token in html, token
    # 三套主题的人话名仍在（来自 EditorTheme.CHOICES；暗色 / 浅色 / 高对比）
    for label in ("暗色", "浅色", "高对比"):
        assert label in html, label
    # 键盘可达：原生 button/radio Tab 可达；焦点环走 --focus（面板与顶栏共用）
    assert ".btn:focus-visible" in html and "var(--focus)" in html
    assert "modalFocusables" in html
    # 顶栏配色不再是与「配色：暗色/浅色/高对比」并列的按钮组
    assert 'id="theme-seg"' not in html and ".themeseg" not in html


def test_frontend_theme_wiring_is_live_and_keeps_draft() -> None:
    html = _html()
    for token in ("initTheme()", "function setTheme(", "function renderThemeSeg(",
                  "function initTheme(", "EditorTheme.applyTheme", "EditorTheme.saveTheme",
                  "EditorTheme.hasStored", "prefers-color-scheme", "data-theme-choice",
                  "renderThemeSeg();"):
        assert token in html, token
    # 换肤只改 data-theme + 按钮态：绝不触碰草稿/未保存改动（立即生效且不丢草稿）
    body = _fn_body("setTheme")
    for forbidden in ("discardDraft", "reloadDetail", "loadEntries", "loadModules",
                      "draft", "state.entry", "location.reload"):
        assert forbidden not in body, forbidden
    init = _fn_body("initTheme")
    assert "EditorTheme.hasStored" in init    # 用户显式选过 → 不跟随系统


def test_footer_batch_string_is_current() -> None:
    html = _html()
    assert "批59 · 特效小尾巴" in html
    assert "批49 · 测试 flake 根治" not in html
    assert "批13.1 · 段入口" not in html
    assert "批11 · 内容包导出/导入" not in html
    assert "批9 · 配色切换" not in html
    assert "批6 · 新增/删除条目 + 检索" not in html
    assert "批3 分区页签" not in html
    assert "三套配色（暗色/浅色/高对比）" in html


def test_theme_code_has_no_pack_business_names() -> None:
    module = _marked("/* EDITOR_THEME_BEGIN */", "/* EDITOR_THEME_END */")
    src = module + _fn_body("setTheme") + _fn_body("renderThemeSeg") + _fn_body("initTheme")
    for word in ("veinborn", "test_demo", "skill_chains", "equipment", "怪物", "装备"):
        assert word not in src, word
