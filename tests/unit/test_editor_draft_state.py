"""编辑器重写批2 · 草稿态测试。

草稿在**前端**（改动不立即落盘）。本测试两条腿：
  ① node 直接执行 index.html 内联的纯 JS 草稿模块（标记块抽取），验证真语义：
     未保存计数 / 改回原值即撤销 / 取消清空 / null 与 undefined 区分；
  ② 前端契约断言：草稿接线、离开守卫、保存/取消按钮、各控件渲染分支。
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
HTML = Path(api.repo_root()) / "qbot_rpg" / "web" / "static" / "index.html"

_NODE_HARNESS = r"""
const D = require(process.argv[1]);
const out = {};
let d = D.newDraft();
D.set(d, "a", 1, 0);            // 真改动
D.set(d, "b", "x", "x");        // 与基准相同 → 不算改动
D.set(d, "c", true, false);     // 真改动
out.countAfterSet = D.count(d);
out.keysAfterSet = D.keys(d).sort();
out.dirty = D.dirty(d);
D.set(d, "a", 0, 0);            // 改回基准 → 计数回退
out.countAfterRevert = D.count(d);
out.patch = D.patch(d);
out.nullVsUndefined = (function () {
  const x = D.newDraft(); D.set(x, "n", null, undefined); return D.count(x);
})();
D.discard(d);
out.countAfterDiscard = D.count(d);
out.dirtyAfterDiscard = D.dirty(d);
out.deepEqual = D.deepSame([1, 2], [1, 2]) && !D.deepSame([1, 2], [2, 1]);
process.stdout.write(JSON.stringify(out));
"""


def _draft_source() -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(r"/\* EDITOR_DRAFT_BEGIN \*/(.*?)/\* EDITOR_DRAFT_END \*/", html, re.S)
    assert match, "index.html 缺少草稿模块标记块（EDITOR_DRAFT_BEGIN/END）"
    return match.group(1)


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 草稿语义执行")
def test_draft_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "draft.js"
    src.write_text(_draft_source(), encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _NODE_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out: Dict[str, Any] = json.loads(proc.stdout)
    assert out["countAfterSet"] == 2            # b 未改动不计入
    assert out["keysAfterSet"] == ["a", "c"]
    assert out["dirty"] is True
    assert out["countAfterRevert"] == 1         # 改回原值 → 撤销该项
    assert out["patch"] == {"c": True}
    assert out["nullVsUndefined"] == 1          # 删字段(null) 与 未填(undefined) 不同
    assert out["countAfterDiscard"] == 0
    assert out["dirtyAfterDiscard"] is False
    assert out["deepEqual"] is True


def test_frontend_draft_machinery_wired() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("未保存改动", "EditorDraft.newDraft", "EditorDraft.set", "EditorDraft.count",
                  "EditorDraft.discard", "EditorDraft.dirty", "function discardDraft",
                  "function canLeave", "btn-save", "btn-cancel", "btn-validate"):
        assert token in html, token


def test_frontend_blocks_switch_with_unsaved_changes() -> None:
    html = HTML.read_text(encoding="utf-8")
    # 条目/模块/包切换与关窗都要过草稿守卫（不得静默丢失）
    assert html.count("if (!canLeave())") >= 3
    assert "项未保存改动；离开将丢弃这些改动" in html
    assert "beforeunload" in html


def test_frontend_renders_every_edit_control() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "switch (f.control)" in html
    for control in ("text", "textarea", "number", "bool", "select", "ref"):
        assert 'case "%s"' % control in html, control
    assert "本批只读展示" in html  # 列表/对象等只读形态在界面上有明确标注


def test_frontend_cancel_button_restores_base() -> None:
    html = HTML.read_text(encoding="utf-8")
    # 取消 = 清空草稿 + 清本机草稿（批32 D1：用户明确放弃）+ 重画条目（回到落盘值）
    assert "discardDraft(); clearLocalDraft(); reloadDetail();" in html
