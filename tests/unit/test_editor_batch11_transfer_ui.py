"""编辑器重写批11 · 内容包导出/导入前端（📦 面板 + EditorTransfer 纯逻辑 + 页脚批次）。

覆盖任务书要求：
  · 顶栏给「导出此包 / 导入包」入口（非技术用户可发现：按钮文案直说 + 悬停说明）；
  · 面板复用批10 公共弹层组件（`.mp-*` + `EditorModal`，不另写一套）；
  · 导入失败给人话结果（成功 / 失败原因 / 新包已出现）；冲突给改名 / 覆盖选择；
  · GM 只读身份：导入入口禁用 + 说明，导出仍可用（后端另有 require_edit 403）；
  · 页脚批次串 = 「批11 · 内容包导出/导入」（旧批次字串不得残留）。

纯 JS 断言在 node 下执行 `EDITOR_TRANSFER` 标记块；不触碰任何内容包、不写盘。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict

from qbot_rpg.web import api

NODE = shutil.which("node")
REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
BATCH_NOTE = "批34 · 通用 CSV"
STALE_BATCH = "批11 · 内容包导出/导入"


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _marked(name: str) -> str:
    m = re.search(r"/\* " + name + r"_BEGIN \*/(.*?)/\* " + name + r"_END \*/",
                  _html(), re.S)
    assert m is not None, name
    return m.group(1)


def _run_node(script: str) -> Dict[str, Any]:
    assert NODE, "node 不可用"
    proc = subprocess.run([NODE, "-e", script], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _transfer_panel_html() -> str:
    m = re.search(r'<div id="transferpanel".*?>\n(.*?)\n</div>\n\n<script>',
                  _html(), re.S)
    assert m is not None, "找不到 transferpanel 面板块"
    return m.group(0)


# =====================================================================================
# A. 顶栏入口（可发现性）
# =====================================================================================
def test_topbar_transfer_entry_is_discoverable() -> None:
    html = _html()
    assert 'id="btn-transfer"' in html
    block = re.search(r'<button[^>]*id="btn-transfer".*?</button>', html, re.S)
    assert block is not None
    body = block.group(0)
    title = next((ln for ln in html.splitlines()
                  if "分享内容包" in ln and "title=" in ln), "")
    assert "aria-haspopup=\"dialog\"" in body
    assert 'aria-label="导出或导入内容包"' in body
    assert "📦" in body or "导出" in body
    assert title, "入口按钮必须有一句人话说明（怎么分享 / 发给别人）"
    assert "导出" in title and "导入" in title


# =====================================================================================
# B. 面板：复用公共弹层组件 + 两个入口 + 人话结果区
# =====================================================================================
def test_panel_uses_shared_modal_component() -> None:
    html = _html()
    panel = _transfer_panel_html()
    assert 'class="mp-overlay" data-modal="transferpanel"' in panel
    assert 'role="dialog"' in panel and 'aria-modal="true"' in panel
    assert "data-modal-close" in panel
    assert 'modalBind("transferpanel"' in html
    assert 'modalOpen("transferpanel", el("btn-transfer"))' in html
    # 共用 EditorModal 的实现（不新写开/关）
    assert "function modalOpen(" in html and "function modalClose(" in html


def test_panel_has_export_and_import_entries() -> None:
    html = _html()
    assert "导出此包" in html and "导入包" in html
    assert 'id="tf-export"' in html and 'id="tf-import"' in html
    assert 'id="tf-file"' in html and 'accept=".ttrpack,.zip,application/zip"' in html
    assert 'id="tf-import-result"' in html      # 人话结果区（成功/失败/冲突）
    assert 'id="tf-file-note"' in html
    assert 'id="tf-ro-note"' in html            # GM 只读说明
    # 导入按钮初始禁用（未选文件 / 只读身份都不能点）
    assert re.search(r'id="tf-import"[^>]*disabled', html), "导入按钮应默认禁用"


def test_panel_explains_conflict_and_backup() -> None:
    html = _html()
    panel = _transfer_panel_html()
    assert "换个名字" in panel and "覆盖" in panel
    assert ".ttrpack_backups" in html, "覆盖前自动备份要写在人话说明里"
    assert "不会写入" in panel or "不会留下半成品" in panel


def test_gm_readonly_disables_import_but_keeps_export() -> None:
    html = _html()
    # 只读身份：导入禁用（canImport 依赖 state.editable），导出不依赖 editable
    assert "EditorTransfer.canImport(state.editable" in html
    assert 'el("tf-export").disabled = !state.pack || TRANSFER.busy' in html
    assert '只读预览，不能导入' in html


def test_frontend_wiring_export_import() -> None:
    html = _html()
    assert '"/api/pack/" + enc(state.pack) + "/export"' in html
    assert '"/api/pack/import"' in html
    assert "on_conflict=" in html and "new_id=" in html
    assert "function doExportPack(" in html and "function doImportPack(" in html
    assert "function refreshAfterImport(" in html
    assert "URL.createObjectURL" in html and "a.download" in html
    assert 'data-tf-act="rename"' in html or 'data-tf-act' in html
    assert "function renderTransferPanel(" in html


# =====================================================================================
# C. EditorTransfer 纯逻辑（node 执行）
# =====================================================================================
def test_node_editor_transfer_pure_logic() -> None:
    harness = (
        "var T = module.exports;\n"
        "var out = {};\n"
        "out.canImport = [T.canImport(true,true), T.canImport(false,true)," \
        " T.canImport(true,false)];\n"
        "out.disp = [T.dispFilename('attachment; filename=\"p-20260914.ttrpack\"'),\n"
        "  T.dispFilename(\"attachment; filename*=UTF-8''%E5%8C%85.ttrpack\")," \
        " T.dispFilename(\"\")];\n"
        "out.fallback = T.fallbackName('pack_a', new Date(2026,8,14));\n"
        "out.conflict = T.conflictHtml('a<b&\"');\n"
        "out.ok = T.importOutcome({ok:true,message:'已导入。'});\n"
        "out.conflictRes = T.importOutcome({conflict:true,pack_id:'p'});\n"
        "out.red = T.importOutcome({ok:false,message:'导入失败：'," \
        "errors:[{message:'坏文件',how_to_fix:'重新导出'}]});\n"
        "out.exOk = T.exportOutcome({ok:true,message:'已导出。'});\n"
        "out.exRed = T.exportOutcome({ok:false,message:'导出失败。'});\n"
        "console.log(JSON.stringify(out));\n"
    )
    out = _run_node(_marked("EDITOR_TRANSFER") + "\n" + harness)
    assert out["canImport"] == [True, False, False]
    assert out["disp"][0] == "p-20260914.ttrpack"
    assert out["disp"][1] == "包.ttrpack"
    assert out["disp"][2] == ""
    assert out["fallback"] == "pack_a-20260914.ttrpack"
    assert 'data-tf-act="rename"' in out["conflict"]
    assert 'data-tf-act="overwrite"' in out["conflict"]
    assert "a&lt;b&amp;&quot;" in out["conflict"], "冲突按钮里的包名必须转义"
    assert out["ok"]["level"] == "ok"
    assert out["conflictRes"]["level"] == "yellow"
    assert out["red"]["level"] == "red" and "重新导出" in out["red"]["text"]
    assert out["exOk"]["level"] == "ok" and out["exRed"]["level"] == "red"


# =====================================================================================
# D. 页脚批次串 + 通用性护栏
# =====================================================================================
def test_footer_batch_string_is_current() -> None:
    html = _html()
    assert BATCH_NOTE in html
    assert STALE_BATCH not in html
    assert "批9 · 配色切换" not in html
    comp = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert comp is not None and BATCH_NOTE in comp.group(1)


def test_transfer_ui_has_no_pack_business_names() -> None:
    block = _marked("EDITOR_TRANSFER") + _transfer_panel_html()
    for forbidden in ("veinborn", "demo_full", "demo_blank", "zz_probe", "skills", "equipment"):
        assert forbidden not in block, f"分享面板不得写死 {forbidden!r}"
