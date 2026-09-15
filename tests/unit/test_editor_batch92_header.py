"""编辑器重写批9.2 · 顶栏与栏头文字排布修复（用户 2026-09-14 报的显示 bug）。

覆盖任务书要求：
  A. **标题只留产品名**：`.brand` = `内容编辑器`（保留 ▚ 标记与强调色），不含 `:: <批次>`；
     `<title>` 同样不带批次；批次串**只在页脚**出现（唯一出处）。
  B. **三栏栏头两层**：标题层（`.hd-t .ttl` 不参与收缩）+ 说明层（`.hd-n`：
     `min-width:0` + `overflow:hidden` + `text-overflow:ellipsis`）——来源/计数/副标题
     不再与标题抢同一行把栏头压成一团；V6「计数含子项」信息保留在第二层。
  C. **顶栏窄窗口不出现半个字符**：`.from`（manifest.json）空间不足时**整段隐藏**
     （`display:none`），不截成单字；`.pkgsel select` 省略号 + 悬停 title 全文。
  D. **纯逻辑**：`hdrNote` 文本与 title 同源（node 执行）。

纯 JS 断言在 node 下执行 index.html 内联标记块；无 node 时跳过。
不触碰仓库 content/；不写盘。
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

# 页脚批次串 = 批次信息的唯一出处（批13 起）；旧批次字串不得残留。
BATCH_NOTE = "批18 · 预设细化与效果扩展"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _css_rule(selector: str) -> str:
    """取某条 CSS 规则体（选择器本身可含逗号，按字面匹配最后一个 `{...}`）。"""
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", _html())
    assert m is not None, f"找不到 CSS 规则：{selector}"
    return m.group(1)


def _marked(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/", _html(), re.S)
    assert m is not None, name
    return m.group(1)


# =====================================================================================
# A. 标题只留产品名；批次只在页脚
# =====================================================================================
def test_brand_is_product_name_only() -> None:
    html = _html()
    # .brand 是单行标记；直接取这一行，避免 `(.*?)</span>` 跨到后面顶栏控件。
    line = next((ln for ln in html.splitlines() if 'class="brand"' in ln), None)
    assert line is not None, "找不到 .brand 标记"
    assert "内容编辑器" in line
    assert 'class="mark"' in line and "▚" in line      # 保留 ▚ 与强调色标记
    assert "::" not in line, "标题不得再混入 `:: <批次>`"
    assert "配色" not in line and "批" not in line
    # 文档标题同样只留产品名
    t = re.search(r"<title>(.*?)</title>", html, re.S)
    assert t is not None and t.group(1).strip() == "内容编辑器"


def test_footer_is_sole_batch_source() -> None:
    html = _html()
    # 页面可见文本里批次串只出现一次，且在页脚 .panel-ft 里（HTML 注释不算可见文本）
    visible = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    assert visible.count(BATCH_NOTE) == 1
    ft = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert ft is not None and BATCH_NOTE in ft.group(1)
    # 页脚里的旧批次字样不得残留（全文档残留由 test_editor_batch4_ux 守）
    for stale in ("批11 · 内容包导出/导入", "批10 · 配色按钮化 + 自定义背景图",
                  "批6 · 新增/删除条目 + 检索",
                  "批5.2 · 视觉细则清零", "批3 · 分区页签"):
        assert stale not in ft.group(1), stale


# =====================================================================================
# B. 三栏栏头两层 + 说明省略号 + 标题不被压缩
# =====================================================================================
def test_header_note_has_ellipsis_and_min_width_zero() -> None:
    body = _css_rule(".hd-n")
    assert "min-width: 0" in body
    assert "overflow: hidden" in body
    assert "text-overflow: ellipsis" in body
    assert "white-space: nowrap" in body


def test_header_title_layer_never_shrinks() -> None:
    body = _css_rule(".hd-t .ttl")
    assert "flex: 0 0 auto" in body, "标题层必须固定不收缩，字形不被压缩"
    assert "white-space: nowrap" in body


def test_three_column_headers_are_two_layer() -> None:
    html = _html()
    # 统一两层：纵向 flex（标题一行 + 说明一行），三栏一致
    unified = _css_rule(".col-hd, .list-hd, .panel-hd")
    assert "flex-direction: column" in unified
    assert "min-width: 0" in unified
    # 三栏标记：每栏都有标题层 + 说明层
    def has_layers(box: str, note: str) -> bool:
        pat = r'<div class="' + box + r'">\s*<div class="hd-t">.*?<div class="' + note + r'"'
        return re.search(pat, html, re.S) is not None

    assert has_layers("col-hd", "hd-n src")
    assert has_layers("list-hd", "hd-n list-count")
    assert has_layers("panel-hd", "hd-n panel-sub")
    # 标题节点都带 .ttl（固定不收缩）
    assert 'class="list-title ttl"' in html
    assert 'class="panel-title ttl"' in html


def test_v6_count_scope_kept_in_second_layer() -> None:
    html = _html()
    # 信息保留
    assert "计数含子项" in html
    # 且走栏头第二层说明出口（文本 + title 同源），不再与标题同行渲染
    assert 'setHdrNote("mod-src"' in html
    assert 'setHdrNote("list-count"' in html
    assert 'setHdrNote("p-sub"' in html
    assert '.col-hd .src' not in html     # 旧的「同行右贴」形态已移除


# =====================================================================================
# C. 顶栏窄窗口：.from 整段隐藏 + select 省略号
# =====================================================================================
def test_from_has_whole_hide_rule() -> None:
    html = _html()
    m = re.search(r"@media \(max-width: 1100px\)\s*\{(.*?)\}", html, re.S)
    assert m is not None, "缺少 .from 整段隐藏的媒体查询"
    assert ".pkgsel .from" in m.group(1)
    assert "display: none" in m.group(1), ".from 必须整段隐藏，不得截成单字"


def test_pack_select_uses_ellipsis_and_title() -> None:
    body = _css_rule(".pkgsel select")
    assert "text-overflow: ellipsis" in body
    assert "min-width: 0" in body
    # 省略时的全文由 title 兜底（select + .pkgsel 容器都挂）
    assert "sel.title = title" in _html()
    assert "box.title = title" in _html()
    # 品牌固定不收缩（配合 .from 整段隐藏，顶栏不再出现孤立/半截字符）
    brand = _css_rule(".brand")
    assert "flex: 0 0 auto" in brand


# =====================================================================================
# D. 纯逻辑（node 执行 hdrNote）
# =====================================================================================
_JS_HARNESS = r"""
const fs = require("fs");
eval(fs.readFileSync(process.argv[2], "utf8"));
const out = {};
out.text = hdrNote("manifest.modules · 16");
out.blank = hdrNote("");
out.nil = hdrNote(null);
out.zero = hdrNote(0);
process.stdout.write(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def js(tmp_path_factory: pytest.TempPathFactory) -> Dict[str, Any]:
    if NODE is None:
        pytest.skip("本机无 node，跳过批9.2 栏头纯逻辑执行")
    harness = tmp_path_factory.mktemp("batch92") / "hdr.js"
    harness.write_text(_marked("EDITOR_HDR_NOTE"), encoding="utf-8")
    script = tmp_path_factory.mktemp("batch92") / "run.js"
    script.write_text(_JS_HARNESS, encoding="utf-8")
    proc = subprocess.run([NODE, str(script), str(harness)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_hdr_note_text_and_title_same_source(js: Dict[str, Any]) -> None:
    assert js["text"] == {"text": "manifest.modules · 16", "title": "manifest.modules · 16"}
    assert js["blank"] == {"text": "", "title": ""}
    assert js["nil"] == {"text": "", "title": ""}
    assert js["zero"] == {"text": "0", "title": "0"}
