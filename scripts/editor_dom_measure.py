#!/usr/bin/env python3
"""编辑器 DOM 量测（批15 验收工具 · 真浏览器）。

用途：用**真实 Chromium（Playwright）**打开编辑器，对指定模块/条目量测右栏
（`#p-body.panel-body`）的 `clientHeight` / `scrollHeight` 与「首屏可见字段数」，
用于 #8 页面化（折叠前 vs 折叠后）、#9 表格化（表格 vs 旧表单）等的**修前/修后对照**。

设计：
  · 真浏览器 + 真编辑器宿主（`scripts/editor_host.py`），量的是真实布局，不是估算；
  · 内容根用**临时副本**（`--content-root` 传原目录时自动复制到 tmp），绝不动真包；
  · 通过页面内公开函数 `selectModule/selectEntry` 驱动，量测时把折叠块「全展开」再
    量一次 → `scrollHeight_all_expanded` 即「修前（不折叠）」对照；
  · 只读量测，不点保存、不写盘（写盘/回退由 pytest 用例覆盖）。

用法：
  <venv>/bin/python scripts/editor_dom_measure.py --pack veinborn \
      --case settings:battle --case settings:slot_defs --case items:<id> --json out.json

  · 依赖 playwright（未安装时给出人话退出码 2，不静默）。
  · `--case module:entry`；entry 为空时取该模块第一个条目。
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


_MEASURE_JS = r"""
() => {
  const body = document.getElementById('p-body');
  const br = body.getBoundingClientRect();
  const rows = Array.from(body.querySelectorAll('.row[data-field]'));
  const vis = rows.filter(el => {
    const r = el.getBoundingClientRect();
    return r.height > 0 && r.top < br.bottom && r.bottom > br.top;
  });
  const panes = Array.from(body.querySelectorAll('.gpane'));
  const visiblePanes = panes.filter(p => !p.hidden);
  const active = visiblePanes.length ? visiblePanes[0] : null;
  let activeTotal = 0, activeCollapsed = 0;
  if (active) {
    activeTotal = active.querySelectorAll('.row[data-field]').length;
    active.querySelectorAll('.subblk .sbbody[hidden]').forEach(b => {
      activeCollapsed += b.querySelectorAll('.row[data-field]').length;
    });
  }
  const subtabs = Array.from(body.querySelectorAll('.gtabs2 .gtab2'));
  const subpanes = Array.from(body.querySelectorAll('.gpane2'));
  const activeSub = active
    ? (Array.from(active.querySelectorAll('.gpane2')).find(p => !p.hidden) || null) : null;
  const blocks = Array.from(body.querySelectorAll('.subblk'));
  const kv = Array.from(body.querySelectorAll('.kvtable tbody tr'));
  const kvVis = kv.filter(el => {
    const r = el.getBoundingClientRect();
    return r.height > 0 && r.top < br.bottom && r.bottom > br.top;
  });
  return {
    clientHeight: body.clientHeight,
    scrollHeight: body.scrollHeight,
    totalRows: rows.length,
    visibleRows: vis.length,
    kvRows: kv.length,
    kvVisibleRows: kvVis.length,
    hasKvTable: body.querySelectorAll('.kvtable').length > 0,
    activePane: active ? active.getAttribute('data-g') : null,
    activeTotal: activeTotal,
    activeCollapsed: activeCollapsed,
    activeMain: activeTotal - activeCollapsed,
    // 批20 C：二级页签（子分组）——声明了子分组的模块一次只看一个子页
    subTabs: subtabs.length,
    subPanes: subpanes.length,
    subTabLabels: subtabs.map(t => (t.textContent || '').trim().slice(0, 24)),
    activeSubTotal: activeSub ? activeSub.querySelectorAll('.row[data-field]').length : 0,
    activeSubVisible: (function () {
      if (!activeSub) { return 0; }
      let n = 0;
      activeSub.querySelectorAll('.row[data-field]').forEach(el => {
        const r = el.getBoundingClientRect();
        if (r.height > 0 && r.top < br.bottom && r.bottom > br.top) { n += 1; }
      });
      return n;
    })(),
    blocks: blocks.map(b => {
      const bd = b.querySelector('.sbbody');
      return {
        name: b.getAttribute('data-sb'),
        collapsed: !!(bd && bd.hidden),
        rows: b.querySelectorAll('.row[data-field]').length,
      };
    }),
  };
}
"""

_EXPAND_ALL_JS = r"""
() => {
  // 「修前（不分区 / 全展开）」对照：展开折叠子块 + 显示全部二级子页（= 旧的一条长滚动）。
  document.querySelectorAll('#p-body .subblk .sbbody').forEach(b => { b.hidden = false; });
  document.querySelectorAll('#p-body .gpane2').forEach(b => { b.hidden = false; });
  document.querySelectorAll('#p-body .gtab').forEach((t, i) => {
    if (i === 0) { t.click(); }
  });
  return true;
}
"""


def _measure_case(page: Any, module: str, entry: str) -> Dict[str, Any]:
    # 先切模块并等「默认选中」稳定（loadEntries 的默认 selectEntry 未 await，直接并发会竞态），
    # 再显式选目标条目，最后等详情确实停在目标 id 上。
    page.evaluate("async (m) => { await selectModule(m); }", module)
    page.wait_for_function("(m) => state.module === m", arg=module, timeout=15000)
    try:
        page.wait_for_function(
            "() => state.entry && state.detail && state.detail.id === state.entry",
            timeout=15000)
    except Exception:  # noqa: BLE001 - 诊断后原样抛出
        diag = page.evaluate(
            "() => JSON.stringify({pack: state.pack, module: state.module, "
            "entry: state.entry, entries: (state.entries || []).length, "
            "detail: state.detail && state.detail.id, "
            "views: (state.views || []).length, "
            "mods: (state.modules || []).length, "
            "title: (document.getElementById('p-title') || {}).textContent})")
        print(f"[dom-measure] 等待详情超时：{diag}", file=sys.stderr)
        raise
    if entry:
        page.evaluate(
            "async ([m, e]) => { await selectEntry(e, m); }", [module, entry])
        try:
            page.wait_for_function(
                "(e) => state.entry === e && state.detail && state.detail.id === e",
                arg=entry, timeout=15000)
        except Exception:  # noqa: BLE001 - 诊断后原样抛出
            diag = page.evaluate(
                "() => JSON.stringify({module: state.module, entry: state.entry, "
                "entryModule: state.entryModule, "
                "detail: state.detail && state.detail.id, "
                "ids: (state.entries || []).map(function (x) { return x.id; }).slice(0, 20), "
                "title: (document.getElementById('p-title') || {}).textContent})")
            print(f"[dom-measure] 等待目标条目超时：{diag}", file=sys.stderr)
            raise
    page.wait_for_selector("#p-body .row[data-field]", timeout=15000)
    page.wait_for_timeout(150)
    after = page.evaluate(_MEASURE_JS)
    page.evaluate(_EXPAND_ALL_JS)          # 折叠前（全展开）对照
    page.wait_for_timeout(150)
    before = page.evaluate(_MEASURE_JS)
    return {"module": module, "entry": entry or "(first)",
            "after": after, "before_expanded": before}


def run(repo: Path, content_root: Path, pack: str, cases: List[str],
        port: int, out: Optional[Path], host_python: Optional[str] = None) -> Dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        print(f"[dom-measure] 缺少 playwright（{exc}）；请先安装：pip install playwright "
              f"&& playwright install chromium", file=sys.stderr)
        raise SystemExit(2)

    tmp = Path(tempfile.mkdtemp(prefix="editor-dom-"))
    pack_dir = tmp / pack
    try:
        shutil.copytree(content_root / pack, pack_dir)
    except OSError as exc:
        print(f"[dom-measure] 复制内容包失败：{exc}", file=sys.stderr)
        raise SystemExit(2)

    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo)
    proc = subprocess.Popen(
        [host_python or sys.executable, str(repo / "scripts" / "editor_host.py"),
         "--pack", pack, "--content-root", str(tmp), "--port", str(port),
         "--host", "127.0.0.1"],
        cwd=str(repo), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        _wait_http(f"http://127.0.0.1:{port}/api/session")
        result: Dict[str, Any] = {"pack": pack, "repo": str(repo), "cases": []}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.on("dialog", lambda d: d.accept())   # 离开确认等原生弹窗：自动确认
            page.goto(f"http://127.0.0.1:{port}/", wait_until="load")
            page.wait_for_function("() => !!(state && state.pack)", timeout=15000)
            page.wait_for_function(
                "() => !!(state.module && state.detail)", timeout=20000)
            for spec in cases:
                mod, _, ent = spec.partition(":")
                result["cases"].append(_measure_case(page, mod, ent))
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="编辑器右栏 DOM 量测（批15 验收）")
    ap.add_argument("--repo", default=str(_REPO_ROOT))
    ap.add_argument("--content-root", default=None,
                    help="内容目录（缺省用仓库 content/）")
    ap.add_argument("--pack", required=True)
    ap.add_argument("--case", action="append", default=[],
                    help="module[:entry]，可重复")
    ap.add_argument("--host-python", default=sys.executable,
                    help="跑 editor_host.py 的解释器（须能 import qbot_rpg；"
                         "本机 playwright 与仓库 venv 不同解释器时用它）")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--json", default=None, help="结果写入的 JSON 路径")
    args = ap.parse_args(argv)
    repo = Path(args.repo).resolve()
    content_root = Path(args.content_root).resolve() if args.content_root else repo / "content"
    cases = args.case or ["settings:battle"]
    port = args.port or _free_port()
    out = Path(args.json).resolve() if args.json else None
    result = run(repo, content_root, args.pack, cases, port, out,
                 host_python=args.host_python)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
