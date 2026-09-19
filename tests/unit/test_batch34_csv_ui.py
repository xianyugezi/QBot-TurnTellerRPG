"""批34 · 编辑器 CSV 入口 UI（按钮 + 弹层 + EditorCsv 纯逻辑）。

覆盖：
  · 模块级「导出 CSV / 导入 CSV」入口（可发现：按钮文案直说 + 悬停说明）；
  · 导入弹层复用批10 公共弹层组件（`.mp-*` + `EditorModal`）；
  · 行序（追加 / 插入位置）与冲突（跳过 / 覆盖）两组选择；
  · GM 只读：导入禁用、导出可用；
  · 结果给人话摘要（成功/跳过/失败 + 明细）；
  · 页脚批次串 = 「批34 · 通用 CSV」。

纯 JS 断言在 node 下执行 `EDITOR_CSV` 标记块；不触碰任何内容包、不写盘。
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
BATCH_NOTE = "批45 · 装备占比校准"
STALE_BATCH = "批34 · 通用 CSV"


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


def _csv_panel_html() -> str:
    m = re.search(r'<div id="csvpanel".*?</div>\n</div>', _html(), re.S)
    assert m is not None, "找不到 csvpanel 面板块"
    return m.group(0)


# =====================================================================================
# A. 模块级入口（可发现性）
# =====================================================================================
def test_module_level_csv_buttons_are_discoverable() -> None:
    html = _html()
    for bid in ("btn-csv-export", "btn-csv-import"):
        block = re.search(r'<button[^>]*id="' + bid + r'".*?</button>', html, re.S)
        assert block is not None, bid
        body = block.group(0)
        assert "title=" in body and "CSV" in body
        assert 'type="button"' in body
    assert 'id="btn-csv-export"' in html and 'id="btn-csv-import"' in html
    # 两个入口挨着「+ 新建条目」（模块级动作区）
    seg = html[html.index('id="btn-new"'):html.index('id="btn-csv-import"')]
    assert "btn-csv-export" in seg


def test_export_button_only_needs_module_import_needs_edit() -> None:
    html = _html()
    assert 'el("btn-csv-export").disabled = !state.module || state.busy' in html
    assert 'el("btn-csv-import").disabled = !state.module || !state.editable || state.busy' in html


# =====================================================================================
# B. 导入弹层：复用公共组件 + 行序/冲突选择 + 人话结果
# =====================================================================================
def test_panel_uses_shared_modal_component() -> None:
    html = _html()
    panel = _csv_panel_html()
    assert 'class="mp-overlay" data-modal="csvpanel"' in panel
    assert 'role="dialog"' in panel and 'aria-modal="true"' in panel
    assert "data-modal-close" in panel
    assert 'modalBind("csvpanel"' in html
    assert 'modalOpen("csvpanel", el("btn-csv-import"))' in html


def test_panel_offers_row_order_and_conflict_choices() -> None:
    panel = _csv_panel_html()
    assert 'name="csv-mode"' in panel and 'value="append"' in panel and 'value="insert"' in panel
    assert 'id="csv-position"' in panel
    assert ('name="csv-conflict"' in panel and 'value="skip"' in panel
            and 'value="overwrite"' in panel)
    assert "跳过" in panel and "覆盖" in panel and "追加" in panel
    assert 'id="csv-result"' in panel          # 人话结果区
    assert 'id="csv-ro-note"' in panel         # GM 只读说明
    assert re.search(r'id="csv-run"[^>]*disabled', panel), "导入按钮应默认禁用"


def test_frontend_wiring_endpoints_and_encoding() -> None:
    html = _html()
    assert "/module/" + '" + enc(mod) + "' + "/export_csv" in html
    assert "/module/" + '" + enc(mod) + "' + "/import_csv?" in html
    assert "on_conflict=" in html and "mode=" in html and "position=" in html
    assert "function doExportCsv(" in html and "function doImportCsv(" in html
    assert "arrayBuffer()" in html, "导入按原始字节上传，才能自动识别 GBK"
    assert "loadEntries()" in html
    assert "GBK" in html


# =====================================================================================
# C. EditorCsv 纯逻辑（node 执行）
# =====================================================================================
def test_node_editor_csv_pure_logic() -> None:
    harness = (
        "var C = module.exports;\n"
        "var out = {};\n"
        "out.canExport = [C.canExport('alpha'), C.canExport('')];\n"
        "out.canImport = [C.canImport(true,'alpha',true), C.canImport(false,'alpha',true),"
        " C.canImport(true,'alpha',false), C.canImport(true,'',true)];\n"
        "out.ok = C.summary({ok:true,level:'ok',summary:{success:2,skipped:1,failed:0,total:3},"
        "message:'导入完成。'});\n"
        "out.yellow = C.summary({ok:true,level:'yellow',summary:{success:1,skipped:1,"
        "failed:0,total:2}});\n"
        "out.red = C.summary({ok:false,summary:{success:0,skipped:0,failed:1,total:1},"
        "message:'导入失败。'});\n"
        "out.details = C.detailsText({summary:{success:1,skipped:1,failed:1,total:3},"
        "errors:[{message:'第 2 行：坏'}],skipped:[{line:3,entry_id:'a1'}],notes:['提示']});\n"
        "out.file = C.fileName('alpha');\n"
        "out.esc = C.esc('a<b&\"');\n"
        "console.log(JSON.stringify(out));\n"
    )
    out = _run_node(_marked("EDITOR_CSV") + "\n" + harness)
    assert out["canExport"] == [True, False]
    assert out["canImport"] == [True, False, False, False]
    assert out["ok"]["level"] == "ok" and "成功 2 条" in out["ok"]["text"]
    assert out["ok"]["text"].count("跳过 1 条")
    assert out["yellow"]["level"] == "yellow"
    assert out["red"]["level"] == "red"
    assert "第 2 行：坏" in out["details"] and "id「a1」" in out["details"]
    assert "提示" in out["details"]
    assert out["file"] == "alpha.csv"
    assert out["esc"] == "a&lt;b&amp;&quot;"


# =====================================================================================
# D. 页脚批次串 + 通用性护栏
# =====================================================================================
def test_footer_batch_string_is_current() -> None:
    html = _html()
    assert BATCH_NOTE in html
    assert STALE_BATCH not in html
    comp = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert comp is not None and BATCH_NOTE in comp.group(1)


def test_csv_ui_has_no_pack_business_names() -> None:
    block = _marked("EDITOR_CSV") + _csv_panel_html()
    for forbidden in ("veinborn", "demo_full", "demo_blank", "zz_probe"):
        assert forbidden not in block, f"CSV 面板不得写死 {forbidden!r}"
