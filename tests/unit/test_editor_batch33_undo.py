"""批33 · 草稿级撤销/重做（框架 §6.12-01）——纯 JS 历史栈语义 + 前端接线 + 不落盘断言。

定稿原文（`docs/审查参考/RPG回合制框架设计文档.md` L997）：
  · 全量撤销栈：每个操作可撤销（Ctrl+Z / 顶栏 ↩️ 按钮）。

本批范围 = **未保存的草稿改动**（字段 / 列表增删行 / 键值表格改键改值 / 新建表单态），
不是「已保存版本的多版本回退」（那仍由 `.bak` +「回退到上一份备份」负责；「版本快照」
已在 `docs/矛盾与待裁决登记.md` X15 登记「已裁决-不做」）。

测试只执行抽取出的纯 JS 模块（node）与静态检查 HTML 接线；不写任何内容包（批19.1 门禁）。
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from qbot_rpg.web import api

NODE = shutil.which("node")
HTML = Path(api.repo_root()) / "qbot_rpg" / "web" / "static" / "index.html"
REGISTRY = Path(api.repo_root()) / "docs" / "矛盾与待裁决登记.md"
BATCH_NOTE = "批42 · 打造属性与相性池"

_NODE_HARNESS = r"""
const H = require(process.argv[1]);
const out = {};
out.defaultLimit = H.DEFAULT_LIMIT;
out.defaultHistory = H.newHistory().limit;

// 空栈：undo/redo 均无可操作
const e = H.newHistory(50);
out.emptyUndo = H.undo(e, { s: 0 });
out.emptyRedo = H.redo(e, { s: 0 });
out.canUndoEmpty = H.canUndo(e);
out.canRedoEmpty = H.canRedo(e);

// 记一步 → 撤销 → 重做（标准快照语义）
const h = H.newHistory(50);
H.push(h, { s: 0 });           // 改动前
out.depthAfterPush = H.depth(h);
out.canUndo1 = H.canUndo(h);
out.undoVal = H.undo(h, { s: 1 }).s;
out.redoDepthAfterUndo = H.redoDepth(h);
out.redoVal = H.redo(h, { s: 1 }).s;
out.depthAfterRedo = H.depth(h);

// push 清空 redo
const h2 = H.newHistory(50);
H.push(h2, { s: 0 });
H.undo(h2, { s: 1 });
out.redoBeforePush = H.redoDepth(h2);
H.push(h2, { s: 2 });
out.redoAfterPush = H.redoDepth(h2);

// 上限：超过 limit 逐出最旧（可配、不硬编码）
const h3 = H.newHistory(3);
[0, 1, 2, 3].forEach((i) => H.push(h3, { s: i }));
out.depthAtLimit = H.depth(h3);
out.oldestDropped = H.undo(h3, { s: 9 }).s;   // 应为 3（0 已被逐出）

// setLimit 立即裁剪到新上限
const h4 = H.newHistory(50);
[0, 1, 2, 3, 4].forEach((i) => H.push(h4, { s: i }));
H.setLimit(h4, 2);
out.depthAfterSetLimit2 = H.depth(h4);
out.afterTrimUndo = H.undo(h4, { s: 9 }).s;   // 应为 4

// 非法 limit 回退缺省；clear 清空两栈
out.badLimit = H.newHistory(0).limit;
out.negLimit = H.newHistory(-5).limit;
const h5 = H.newHistory(10);
H.push(h5, { s: 0 });
H.undo(h5, { s: 1 });
H.clear(h5);
out.cleared = H.depth(h5) === 0 && H.redoDepth(h5) === 0 && !H.canUndo(h5) && !H.canRedo(h5);

process.stdout.write(JSON.stringify(out));
"""


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _module_source() -> str:
    match = re.search(r"/\* EDITOR_HISTORY_BEGIN \*/(.*?)/\* EDITOR_HISTORY_END \*/",
                      _html(), re.S)
    assert match, "index.html 缺少历史栈纯逻辑模块标记块（EDITOR_HISTORY_BEGIN/END）"
    return match.group(1)


def _fn_body(html: str, name: str) -> str:
    """粗取一个顶层函数体（从 `function name(` 到下一个顶层 `function` / 收尾）。"""
    m = re.search(r"\nfunction " + re.escape(name) + r"\([^)]*\)\s*\{", html)
    assert m, f"index.html 找不到 function {name}("
    start = m.start()
    nxt = re.search(r"\nfunction [A-Za-z_$][\w$]*\(", html[start + 1:])
    end = start + 1 + (nxt.start() if nxt else len(html) - start - 1)
    return html[start:end]


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 历史栈语义执行")
def test_history_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "history.js"
    src.write_text(_module_source(), encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _NODE_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)

    assert out["defaultLimit"] == 50
    assert out["defaultHistory"] == 50
    assert out["emptyUndo"] is None and out["emptyRedo"] is None
    assert out["canUndoEmpty"] is False and out["canRedoEmpty"] is False

    assert out["depthAfterPush"] == 1 and out["canUndo1"] is True
    assert out["undoVal"] == 0 and out["redoDepthAfterUndo"] == 1
    assert out["redoVal"] == 1 and out["depthAfterRedo"] == 1

    assert out["redoBeforePush"] == 1 and out["redoAfterPush"] == 0, "新记一步必须清空 redo"

    assert out["depthAtLimit"] == 3, "上限应裁剪到 limit 步"
    assert out["oldestDropped"] == 3, "超限应逐出最旧（最先记的 0 不在栈里）"

    assert out["depthAfterSetLimit2"] == 2
    assert out["afterTrimUndo"] == 4

    assert out["badLimit"] == 50 and out["negLimit"] == 50
    assert out["cleared"] is True


def test_toolbar_buttons_and_disabled_default() -> None:
    html = _html()
    assert 'id="btn-undo"' in html and 'id="btn-redo"' in html
    # 初始禁用态（空栈）
    m = re.search(r'<button class="btn" id="btn-undo" disabled', html)
    assert m, "撤销按钮缺省应为禁用态"
    m = re.search(r'<button class="btn" id="btn-redo" disabled', html)
    assert m, "重做按钮缺省应为禁用态"
    # 唯一可用性出口：syncHistoryButtons 按 canUndo/canRedo + busy 真禁用
    body = _fn_body(html, "syncHistoryButtons")
    assert "EditorHistory.canUndo(hist)" in body
    assert "EditorHistory.canRedo(hist)" in body
    assert "disabled" in body


def test_markdirty_commits_and_discard_resets() -> None:
    html = _html()
    mark = _fn_body(html, "markDirty")
    assert "historyCommit()" in mark, "所有草稿改动应在 markDirty 末端统一入栈"
    assert "syncHistoryButtons()" in mark
    discard = _fn_body(html, "discardDraft")
    assert "historyReset()" in discard, "取消 / 还原 / 切条目必须清栈"


def test_save_success_clears_stack() -> None:
    html = _html()
    post = _fn_body(html, "postForm")
    assert 'suffix === "/save"' in post
    assert "historyReset()" in post, "保存成功必须清栈（撤销按钮回禁用态）"
    # 保存成功分支仍走既有落盘链路（未改语义）
    assert "reloadDetail()" in post


def test_limit_is_configurable_not_hardcoded() -> None:
    html = _html()
    assert 'HIST_LIMIT_KEY' in html and '"qbot.editor.undo_limit"' in html
    body = _fn_body(html, "historyLimit")
    assert "localStorage" not in body  # 经 themeStore() 间接读，防隐私模式抛错
    assert "EditorHistory.DEFAULT_LIMIT" in body
    reset = _fn_body(html, "historyReset")
    assert "setLimit" in reset, "每次清栈应按可配上限重置栈容量"


def test_undo_redo_do_not_touch_disk() -> None:
    """撤销/重做只动内存草稿：不得出现保存/网络/落盘调用。"""
    html = _html()
    for fn in ("historyUndo", "historyRedo", "applyHistorySnapshot"):
        body = _fn_body(html, fn)
        for banned in ("postJSON", "fetch(", "/save", "reloadDetail", "runSave", "saveForm"):
            assert banned not in body, f"{fn} 不应出现 {banned}（撤销/重做不得触发写盘）"
    # 重画只走既有 renderDetail / renderNewEntry（纯渲染，无请求）
    assert "renderDetail(state.detail)" in _fn_body(html, "applyHistorySnapshot")
    assert "renderNewEntry(state.newEntry)" in _fn_body(html, "applyHistorySnapshot")


def test_new_entry_form_state_kept_across_rerender() -> None:
    html = _html()
    body = _fn_body(html, "renderNewEntry")
    assert "state.pendingNewDraft" in body, "新建表单重画应保留草稿（供撤销/重做恢复）"
    snap = _fn_body(html, "historySnapshot")
    assert "newDraft" in snap and "newId" in snap, "快照应含新建表单草稿与 ID 输入"


def test_keyboard_shortcuts_and_typing_guard() -> None:
    html = _html()
    key = _fn_body(html, "historyKey")
    assert 'e.ctrlKey' in key and "e.metaKey" in key
    assert '"z"' in key and '"y"' in key
    assert "e.shiftKey" in key
    assert "historyTypingTarget" in key and "modalActive()" in key
    guard = _fn_body(html, "historyTypingTarget")
    for tag in ("INPUT", "TEXTAREA", "SELECT"):
        assert tag in guard
    assert "isContentEditable" in guard
    # 与既有弹层快捷键同一 document 监听（沿用同一处约定）
    assert re.search(r'if \(historyKey\(e\)\) \{ e\.preventDefault\(\); \}', html)


def test_snapshot_covers_main_and_assoc_forms() -> None:
    html = _html()
    snap = _fn_body(html, "historySnapshot")
    assert "state.forms" in snap and "draft.changes" in snap
    apply_body = _fn_body(html, "applyHistorySnapshot")
    assert "pendingDrafts" in apply_body, "关联分区草稿经既有 pendingDrafts 回填"
    assert "histSuppress" in html, "重画/恢复期间不得把渲染误记为一步"


def test_footer_batch_note_synced_and_registry_item() -> None:
    html = _html()
    m = re.search(r'<div class="panel-ft"><span>(.*?)</span>', html)
    assert m and m.group(1) == BATCH_NOTE, m and m.group(1)
    text = REGISTRY.read_text(encoding="utf-8")
    assert "X15" in text and "版本快照" in text
    row = next((ln for ln in text.splitlines() if ln.startswith("| X15 |")), None)
    assert row and "已裁决-不做" in row, "X15 应登记「版本快照」= 已裁决-不做"
    assert "实现方案.md:733" in row or "实现方案.md" in row
