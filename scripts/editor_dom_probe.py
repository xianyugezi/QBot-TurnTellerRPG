#!/usr/bin/env python3
"""编辑器 DOM 探针（批20 验收工具 · 真浏览器）。

用途（两段，均用真 Chromium 打开真编辑器宿主，量的是真实布局 / 真实 DOM）：

  · `--mode nested`（批20 A）：对象内嵌「数组 / 映射」控件是否真的在 DOM 里、是否真的可编
    （改动是否进 `MAIN_CTX.draft.changes`）——把「无法编辑」的修前根因（只读 JSON 块）钉死。
  · `--mode groups`（批20 C）：右栏 `#p-body.panel-body` 的 `clientHeight` / `scrollHeight`、
    首屏可见字段数、二级页签数与当前子页可见字段数；中栏 `#rows` 的分组小节数、折叠态与
    可见条目数。给出「修前（无分组声明 / 全展开）vs 修后（分区 / 分组折叠）」对照。

设计：
  · 真浏览器 + 真编辑器宿主（`scripts/editor_host.py`）；内容根用**临时副本**，绝不动真包；
  · 宿主解释器可用 `--host-python` 指定（本机可能存在「装了 playwright 的解释器」与
    「能 import qbot_rpg 的解释器」不是同一个的情况，例如 python3.8 有 playwright、
    仓库 venv 是 3.11）；缺省用当前解释器；
  · 只读探针：只改前端草稿，不点保存、不写盘（写盘 / 回退由 pytest 用例覆盖）。

用法：
  <有 playwright 的 python> scripts/editor_dom_probe.py --repo <repo> --pack veinborn \
      --module enemies --entry <id> --mode nested --json out.json
  <有 playwright 的 python> scripts/editor_dom_probe.py --repo <repo> --pack veinborn \
      --module effects --mode groups --json out.json [--host-python <repo python>]
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait_http(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last: Optional[Exception] = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return
        except Exception as exc:  # noqa: BLE001 - 轮询探活
            last = exc
        time.sleep(0.2)
    raise RuntimeError(f"编辑器宿主未就绪：{url}（{last}）")


# ---------------------------------------------------------------------------
# 页面内脚本（纯读取 / 只改前端草稿）
# ---------------------------------------------------------------------------
_NESTED_JS = r"""
() => {
  const body = document.getElementById('p-body');
  const fields = {};
  Array.from(body.querySelectorAll('.row[data-field]')).forEach(row => {
    const key = row.getAttribute('data-field');
    const opaths = Array.from(row.querySelectorAll('[data-opath]')).map(e => ({
      opath: e.dataset.opath || '', tag: e.tagName, type: e.type || '',
      value: (e.value === undefined ? e.textContent : e.value),
      control: e.className,
    }));
    const kvcell = Array.from(row.querySelectorAll('[data-kvcell]')).map(e => ({
      tag: e.tagName, type: e.type || '', value: (e.value === undefined ? '' : e.value),
    }));
    const kvkey = Array.from(row.querySelectorAll('.kvkey input')).map(e => e.value);
    fields[key] = {
      objlist: row.querySelectorAll('.objlist').length,
      objkv: row.querySelectorAll('.objkv').length,
      kvtable: row.querySelectorAll('table.kvtable').length,
      objform: row.querySelectorAll('.objform').length,
      opaths: opaths, kvcell: kvcell, kvkey: kvkey,
    };
  });
  return {fields: fields};
}
"""

_EDIT_JS = r"""
(spec) => {
  const body = document.getElementById('p-body');
  const row = body.querySelector('.row[data-field="' + spec.field + '"]');
  if (!row) { return {ok: false, why: 'no row ' + spec.field}; }
  let el = null;
  if (spec.kind === 'opath') {
    el = Array.from(row.querySelectorAll('[data-opath]'))
      .find(e => e.dataset.opath === spec.locator);
  } else if (spec.kind === 'kvcell') {
    const keyInp = Array.from(row.querySelectorAll('.kvkey input'))
      .find(e => e.value === spec.locator);
    if (keyInp) { el = keyInp.closest('tr').querySelector('[data-kvcell]'); }
  } else if (spec.kind === 'okvc') {
    el = row.querySelector('[data-okvc="' + spec.locator + '"]');
  }
  if (!el) { return {ok: false, why: 'no control ' + spec.kind + ':' + spec.locator}; }
  const before = el.value;
  el.value = spec.value;
  el.dispatchEvent(new Event(el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input',
                             {bubbles: true}));
  return {ok: true, tag: el.tagName, before: before, after: el.value};
}
"""

_GROUPS_JS = r"""
() => {
  const body = document.getElementById('p-body');
  const br = body.getBoundingClientRect();
  const rows = Array.from(body.querySelectorAll('.row[data-field]'));
  const vis = rows.filter(el => {
    const r = el.getBoundingClientRect();
    return r.height > 0 && r.top < br.bottom && r.bottom > br.top;
  });
  const panes = Array.from(body.querySelectorAll('.gpane'));
  const active = panes.find(p => !p.hidden) || null;
  let activeTotal = 0, activeCollapsed = 0, activeVisible = 0;
  if (active) {
    activeTotal = active.querySelectorAll('.row[data-field]').length;
    active.querySelectorAll('.subblk .sbbody[hidden]').forEach(b => {
      activeCollapsed += b.querySelectorAll('.row[data-field]').length;
    });
    active.querySelectorAll('.row[data-field]').forEach(el => {
      const r = el.getBoundingClientRect();
      if (r.height > 0 && r.top < br.bottom && r.bottom > br.top) { activeVisible += 1; }
    });
  }
  const subtabs = Array.from(body.querySelectorAll('.gtabs2 .gtab2'));
  const subpanes = Array.from(body.querySelectorAll('.gpane2'));
  const activeSub = subpanes.find(p => !p.hidden) || null;
  const rowsBox = document.getElementById('rows');
  const groups = Array.from(rowsBox ? rowsBox.querySelectorAll('.lgrp') : []);
  const gitems = Array.from(rowsBox ? rowsBox.querySelectorAll('.item') : []);
  const gvis = gitems.filter(el => {
    const r = el.getBoundingClientRect();
    const rb = rowsBox.getBoundingClientRect();
    return r.height > 0 && r.top < rb.bottom && r.bottom > rb.top;
  });
  const opts = Array.from(rowsBox ? rowsBox.querySelectorAll('.gtab, .lgrp-head, .gsec') : [])
    .map(e => (e.textContent || '').trim().slice(0, 40));
  return {
    clientHeight: body.clientHeight,
    scrollHeight: body.scrollHeight,
    totalRows: rows.length,
    visibleRows: vis.length,
    groupTabs: body.querySelectorAll('.gtabs .gtab').length,
    subTabs: subtabs.length,
    subTabLabels: subtabs.map(t => (t.textContent || '').trim().slice(0, 24)),
    subPanes: subpanes.length,
    activeSubTotal: activeSub ? activeSub.querySelectorAll('.row[data-field]').length : 0,
    activePane: active ? active.getAttribute('data-g') : null,
    activeTotal: activeTotal,
    activeCollapsed: activeCollapsed,
    activeVisible: activeVisible,
    listGroups: groups.length,
    listGroupCollapsed: groups.filter(g => {
      const b = g.querySelector('.lgrp-body');
      return !!(b && b.hidden);
    }).length,
    listItems: gitems.length,
    listVisibleItems: gvis.length,
    listHeadings: opts,
  };
}
"""

_EXPAND_ALL_JS = r"""
() => {
  document.querySelectorAll('#p-body .subblk .sbbody').forEach(b => { b.hidden = false; });
  document.querySelectorAll('#p-body .gtabs .gtab')
    .forEach((t, i) => { if (i === 0) { t.click(); } });
  return true;
}
"""

_EXPAND_LIST_JS = r"""
() => {
  document.querySelectorAll('#rows .lgrp-body[hidden]').forEach(b => { b.hidden = false; });
  return true;
}
"""


def _select(page: Any, module: str, entry: str) -> None:
    page.evaluate("async (m) => { await selectModule(m); }", module)
    page.wait_for_function("(m) => state.module === m", arg=module, timeout=20000)
    try:
        page.wait_for_function(
            "() => state.entry && state.detail && state.detail.id === state.entry",
            timeout=20000)
    except Exception:  # noqa: BLE001
        diag = page.evaluate(
            "() => JSON.stringify({module: state.module, entry: state.entry, "
            "entries: (state.entries || []).length})")
        print(f"[dom-probe] 等待默认详情超时：{diag}", file=sys.stderr)
        raise
    if entry:
        page.evaluate("async ([m, e]) => { await selectEntry(e, m); }", [module, entry])
        page.wait_for_function(
            "(e) => state.entry === e && state.detail && state.detail.id === e",
            arg=entry, timeout=20000)
    page.wait_for_selector("#p-body .row[data-field]", timeout=20000)
    page.wait_for_timeout(150)


def run(repo: Path, content_root: Path, pack: str, module: str, entry: str,
        mode: str, edits: List[Dict[str, str]], port: int, host_python: str,
        out: Optional[Path]) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        print(f"[dom-probe] 缺少 playwright（{exc}）；请先安装：pip install playwright "
              f"&& playwright install chromium", file=sys.stderr)
        raise SystemExit(2)

    tmp = Path(tempfile.mkdtemp(prefix="editor-dom-probe-"))
    try:
        shutil.copytree(content_root / pack, tmp / pack)
    except OSError as exc:
        print(f"[dom-probe] 复制内容包失败：{exc}", file=sys.stderr)
        raise SystemExit(2)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo)
    proc = subprocess.Popen(
        [host_python, str(repo / "scripts" / "editor_host.py"),
         "--pack", pack, "--content-root", str(tmp), "--port", str(port),
         "--host", "127.0.0.1"],
        cwd=str(repo), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/api/session")
        result: Dict[str, Any] = {"pack": pack, "module": module, "entry": entry or "(first)",
                                  "mode": mode}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("dialog", lambda d: d.accept())
            errors: List[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console",
                    lambda m: errors.append("console:" + m.text) if m.type == "error" else None)
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_function("() => !!(state && state.pack)", timeout=20000)
            page.wait_for_function("() => !!(state.module && state.detail)", timeout=30000)
            _select(page, module, entry)
            if mode == "nested":
                result["before"] = page.evaluate(_NESTED_JS)
                result["edits"] = []
                for spec in edits:
                    result["edits"].append(page.evaluate(_EDIT_JS, spec))
                page.wait_for_timeout(150)
                result["draftAfter"] = page.evaluate(
                    "() => JSON.parse(JSON.stringify((MAIN_CTX.draft || {}).changes || {}))")
                result["after"] = page.evaluate(_NESTED_JS)
            else:
                result["after"] = page.evaluate(_GROUPS_JS)
                page.evaluate(_EXPAND_ALL_JS)
                page.evaluate(_EXPAND_LIST_JS)
                page.wait_for_timeout(150)
                result["before_expanded"] = page.evaluate(_GROUPS_JS)
            result["pageErrors"] = errors
            browser.close()
        if out:
            out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)


def _parse_edit(text: str) -> Dict[str, str]:
    """`field|kind:locator|value` → {field, kind, locator, value}（kind ∈ opath/kvcell/okvc）。"""
    parts = text.split("|")
    if len(parts) < 3:
        raise SystemExit(f"--edit 形态非法（应为 field|kind:locator|value）：{text!r}")
    kind, _, locator = parts[1].partition(":")
    return {"field": parts[0], "kind": kind, "locator": locator, "value": "|".join(parts[2:])}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="编辑器 DOM 探针（批20 A / C 验收）")
    ap.add_argument("--repo", default=str(_REPO_ROOT))
    ap.add_argument("--content-root", default=None, help="内容目录（缺省用仓库 content/）")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--module", required=True)
    ap.add_argument("--entry", default="", help="条目 id（缺省用该模块第一个条目）")
    ap.add_argument("--mode", choices=("nested", "groups"), default="nested")
    ap.add_argument("--edit", action="append", default=[],
                    help="field|kind:locator|value（kind ∈ opath/kvcell/okvc），可重复")
    ap.add_argument("--host-python", default=sys.executable,
                    help="跑 editor_host.py 的解释器（须能 import qbot_rpg）")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--json", default=None, help="结果写入的 JSON 路径")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    content_root = Path(args.content_root).resolve() if args.content_root else repo / "content"
    port = args.port or _free_port()
    out = Path(args.json).resolve() if args.json else None
    result = run(repo, content_root, args.pack, args.module, args.entry, args.mode,
                 [_parse_edit(x) for x in args.edit], port, args.host_python, out)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
