"""批32 · D1：保存失败兜底（框架 §6.12-22）——编辑器侧浏览器本地草稿。

定稿原文（`docs/审查参考/RPG回合制框架设计文档.md` L1173-1177）：
  · 自动保存失败 → 弹「保存失败，请检查磁盘空间」，绝不静默丢数据；
  · 失败时本地暂存（浏览器 localStorage），恢复后补写。

本批最小实现（与服务端既有 `.pending` 互补）：
  · 纯前端：编辑中改动（`markDirty` 末尾）写入 `localStorage`（**不上传服务器、不写内容包文件**）；
  · 重开页面检测到草稿 → 横条提示「恢复 / 丢弃」；恢复把草稿值灌回表单并记为未提交改动；
  · 保存成功 → 清除；保存失败（请求异常）→ 保留并如实提示；
  · 开关（`qbot.editor.autosave`）关闭 → 完全不动作（行为与现状一致）。

测试只写临时对象（node 直接执行纯 JS 模块）；不触碰真实内容包。
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

_NODE_HARNESS = r"""
const D = require(process.argv[1]);
function mk() {
  const m = {};
  return { getItem: k => (k in m ? m[k] : null), setItem: (k, v) => { m[k] = String(v); },
           removeItem: k => { delete m[k]; }, dump: () => m };
}
const out = {};
out.defaultEnabled = D.enabled(mk());                 // 缺省 = 开
const off = mk(); D.setEnabled(off, false); out.disabled = D.enabled(off);
out.buildNullNoPatch = D.build({ pack: "p", module: "m", entry: "e", patch: {} });
out.buildNullNoEntry = D.build({ pack: "p", module: "m", patch: { a: 1 } });

// 保存失败 / 页面崩溃：草稿仍在 → 重开可恢复
const s = mk();
const p = D.build({ pack: "p", module: "m", entry: "e1", name: "铁剑",
                    patch: { atk: 99 }, at: new Date().toISOString() });
out.saved = D.save(s, p);
out.reloadedCount = D.load(s, Date.now()).count;
out.reloadedValue = D.load(s, Date.now()).patch.atk;
out.describe = D.describe(p);

// 正常保存成功 → 清除
D.clear(s);
out.afterClear = D.load(s, Date.now());

// 过期（> TTL）→ 自动清理
const s2 = mk();
D.save(s2, D.build({ pack: "p", module: "m", entry: "e", patch: { a: 1 },
                     at: "2000-01-01T00:00:00Z" }));
out.expired = D.load(s2, Date.now());
out.expiredCleared = s2.dump()[D.KEY] === undefined;

// 坏数据 → 安全清理，不抛
const s3 = mk(); s3.setItem(D.KEY, "not json");
out.malformed = D.load(s3);
out.malformedCleared = s3.dump()[D.KEY] === undefined;

// 开关关闭：不写（save 仍可被调用，但前端 autosave 已在 enabled 处短路）
const s4 = mk(); D.setEnabled(s4, false);
out.disabledNoAutosave = D.enabled(s4) === false;
process.stdout.write(JSON.stringify(out));
"""


def _module_source() -> str:
    html = HTML.read_text(encoding="utf-8")
    match = re.search(r"/\* EDITOR_LOCAL_DRAFT_BEGIN \*/(.*?)/\* EDITOR_LOCAL_DRAFT_END \*/",
                      html, re.S)
    assert match, "index.html 缺少本地草稿模块标记块（EDITOR_LOCAL_DRAFT_BEGIN/END）"
    return match.group(1)


@pytest.mark.skipif(NODE is None, reason="本机无 node，跳过纯 JS 本地草稿语义执行")
def test_local_draft_js_semantics(tmp_path: Path) -> None:
    src = tmp_path / "localdraft.js"
    src.write_text(_module_source(), encoding="utf-8")
    proc = subprocess.run([NODE, "-e", _NODE_HARNESS, str(src)],
                          capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["defaultEnabled"] is True
    assert out["disabled"] is False
    assert out["buildNullNoPatch"] is None
    assert out["buildNullNoEntry"] is None
    assert out["saved"] is True
    assert out["reloadedCount"] == 1 and out["reloadedValue"] == 99
    assert "铁剑" in out["describe"] and "1 项未提交改动" in out["describe"]
    assert out["afterClear"] is None                     # 正常保存 → 草稿清除
    assert out["expired"] is None and out["expiredCleared"] is True
    assert out["malformed"] is None and out["malformedCleared"] is True
    assert out["disabledNoAutosave"] is True


def test_frontend_local_draft_wiring() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("EDITOR_LOCAL_DRAFT_BEGIN", "EditorLocalDraft", "autosaveLocalDraft",
                  "clearLocalDraft", "checkLocalDraft", "restoreLocalDraft",
                  "initAutosaveToggle", "btn-autosave", "draft-restore",
                  "qbot.editor.autosave", "已保存在本机浏览器"):
        assert token in html, token


def test_save_failure_message_keeps_draft() -> None:
    """保存失败分支：不静默丢数据，提示草稿在本机；且不改变既有成功/回退分支。"""
    html = HTML.read_text(encoding="utf-8")
    assert "未提交改动已保存在本机浏览器，刷新后可恢复" in html
    # 保存成功分支清草稿（在既有 discard 之后、reloadDetail 之前）
    idx_ok = html.index("clearLocalDraft();")
    idx_discard = html.index("EditorDraft.discard(ctx.draft);", idx_ok - 4000)
    assert idx_discard < idx_ok
