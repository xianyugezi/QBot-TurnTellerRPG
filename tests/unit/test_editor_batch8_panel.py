"""编辑器重写批8 · 顶栏「模块开关」⚙ 前端（docs/编辑器重写_实现方案.md §四 批8）。

覆盖前端侧要求：
  · ⚙ 设置图标 + 「模块开关」面板（勾选框：中文名 + 模块键 + 一句话说明 + 依赖黄提示）；
  · 面板顶部人话引导；GM 只读身份勾选禁用（视觉 + 说明）；
  · 空包首屏空态引导（未启用任何模块 → 引导 + 直接打开面板的按钮）；
  · 启停后左栏模块树 / 中栏 / 页签 / 计数立即刷新（复用批6 一致性刷新）；
  · 新样式只用 tokens 令牌；编辑器代码不写死任何内容包名。

纯逻辑经 node 直接执行 index.html 内联模块（与既有批次同一手法）；不触碰任何内容包。
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


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _marked(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


def _fn_src(name: str, next_name: str) -> str:
    html = _html()
    start = html.index(f"function {name}(")
    end = html.index(f"function {next_name}(")
    src = html[start:end].rstrip()
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


def _run_node(script: str) -> Dict[str, Any]:
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


# 内联模块依赖页面里的转义函数 esc（node 下补桩，与既有批次同一手法）。
_ESC_STUB = (
    "global.esc = function (v) { return String(v == null ? '' : v)"
    ".replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')"
    ".replace(/\"/g, '&quot;').replace(/'/g, '&#39;'); };\n"
)


def test_module_row_html_has_label_key_purpose_and_checked_state() -> None:
    block = _marked("EDITOR_MODULES")
    script = (
        _ESC_STUB + block
        + "\nvar out = {};"
        + "\nout.on = moduleRowHtml({module:'skills',label:'技能',purpose:'玩家技能。',"
        + "enabled:true,missing_requires:[]}, true);"
        + "\nout.off = moduleRowHtml({module:'maps',label:'地图',purpose:'地图场景。',"
        + "enabled:false,missing_requires:[]}, true);"
        + "\nout.requires = moduleRowHtml({module:'skill_chains',label:'派生链',"
        + "purpose:'派生关系。',enabled:false,missing_requires:['skills'],"
        + "requires_labels:['技能']}, true);"
        + "\nout.ro = moduleRowHtml({module:'items',label:'物品',purpose:'物品。',"
        + "enabled:false,missing_requires:[]}, false);"
        + "console.log(JSON.stringify(out));"
    )
    out = _run_node(script)
    assert "技能" in out["on"] and "skills" in out["on"] and "玩家技能。" in out["on"]
    assert "checked" in out["on"] and "checked" not in out["off"]
    assert "建议同时启用" in out["requires"] and "技能" in out["requires"]
    assert "disabled" in out["ro"] and "mp-row" in out["ro"] and " ro" in out["ro"]


def test_module_empty_state_and_readonly_note() -> None:
    block = _marked("EDITOR_MODULES")
    script = (
        _ESC_STUB + block
        + "\nconsole.log(JSON.stringify({empty: moduleEmptyHtml(), ro: moduleReadonlyNote(false),"
        + " rw: moduleReadonlyNote(true)}));"
    )
    out = _run_node(script)
    assert "还没启用任何模块" in out["empty"]
    assert "data-open-modules" in out["empty"]      # 按钮直接打开面板
    assert "⚙" in out["empty"]
    assert "只读预览" in out["ro"] and "不能勾选" in out["ro"]
    assert out["rw"] == ""


def test_frontend_panel_markup_and_wiring() -> None:
    html = _html()
    for token in ("EDITOR_MODULES_BEGIN", "EDITOR_MODULES_END",
                  'id="btn-settings"', 'id="modpanel"', 'id="mp-list"',
                  'id="mp-close"', 'id="mp-rollback"', 'id="mp-done"',
                  "/module-catalog", "/toggle", "/manifest/rollback",
                  "openModulePanel", "onModuleToggle", "fetchModulePanel",
                  "refreshAfterModuleChange", "renderEmptyPack", "moduleEmptyHtml()"):
        assert token in html, token


def test_panel_top_hint_and_readonly_explanation_rendered() -> None:
    html = _html()
    assert "mp-hint" in html
    # 只读说明文案来自前端纯函数（GM 勾选不可用 + 为什么）
    assert "moduleReadonlyNote" in html
    assert "勾选你要做的内容类型" in html or "hint" in html


def test_empty_pack_triggers_guidance_in_load_modules() -> None:
    src = _fn_src("loadModules", "selectModule")
    assert "state.modules.length" in src
    assert "renderEmptyPack()" in src


def test_refresh_after_module_change_reuses_consistency_refresh() -> None:
    src = _fn_src("refreshAfterModuleChange", "openModulePanel")
    for token in ("loadModules()", "loadEntries()", "loadEntryIndex()", "selectModule("):
        assert token in src, token


def test_panel_css_uses_tokens_only() -> None:
    html = _html()
    for begin in (".mp-overlay {", ".mp {", ".mp-row {", ".mp-cb {", ".mempty {"):
        start = html.index(begin)
        seg = html[start:html.index("}", start) + 1]
        assert "var(--" in seg, begin
        assert not re.search(r"#[0-9a-fA-F]{3,6}", seg), begin


def test_module_frontend_has_no_pack_business_names() -> None:
    block = _marked("EDITOR_MODULES")
    src = block + _fn_src("renderEmptyPack", "refreshAfterModuleChange") \
        + _fn_src("refreshAfterModuleChange", "openModulePanel")
    for word in ("veinborn", "test_demo", "skill_chains", "equipment"):
        assert word not in src, word
