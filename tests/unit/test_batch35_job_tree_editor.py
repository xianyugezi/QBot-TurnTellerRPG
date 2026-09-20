"""批35 · 编辑器职业树（【进阶职业卡片】§6.12-12）：后端接口 + 最小展示 + 纯 JS 逻辑。

覆盖：
  · 后端 `api.job_tree`：按 ModuleMeta.kind 定位 jobs/skills（不写死模块名），
    输出「从哪些职业进阶 / 下级职业 / 继承什么」；
  · HTTP 入口 `/api/pack/{pack}/job-tree`（FastAPI TestClient + 临时内容根）；
  · 前端入口：按钮 + 复用 `.mp-*` 公共弹层 + 只读；
  · 纯 JS `EditorJobTree.treeText`（node 下执行标记块）；
  · 页脚批次串 =「批36 · 采集/挖掘」。

只写 tmp_path 的临时内容根；绝不触碰仓库 content/（批19.1 防污染门禁）。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from editor_host import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from qbot_rpg.web import api  # noqa: E402

NODE = shutil.which("node")
HTML = Path(api.repo_root()) / "qbot_rpg" / "web" / "static" / "index.html"
BATCH_NOTE = "批61 · 深炼金口径B"
STALE_BATCH = "批36 · 采集/挖掘"


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


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _pack(tmp_path: Path) -> Path:
    root = tmp_path / "content"
    pkg = root / "pack_jt"
    pkg.mkdir(parents=True)
    _write(pkg / "manifest.json", {
        "name": "JT", "version": "1", "schema_version": 1,
        "modules": ["jobs", "skills"]})
    _write(pkg / "jobs.json", [
        {"id": "job_a", "name": "甲职"},
        {"id": "job_b", "name": "乙职",
         "advance": {"from": "job_a", "level": 5},
         "inherit": {"from": "job_a"}},
        {"id": "job_c", "name": "丙职", "inherit": {"from": "job_b"}},
        {"id": "job_x", "name": "独立职"},
    ])
    _write(pkg / "skills.json", [
        {"id": "a_pass", "name": "甲被动", "type": "passive", "job_restrict": ["job_a"]},
        {"id": "b_act", "name": "乙主动", "type": "active", "job_restrict": ["job_b"]},
        {"id": "common", "name": "通用", "type": "active"},
    ])
    return root


# ---------------------------------------------------------------------------
# A. 后端 api.job_tree
# ---------------------------------------------------------------------------
def test_api_job_tree(tmp_path: Path) -> None:
    root = _pack(tmp_path)
    tree = api.job_tree("pack_jt", root=root)
    assert tree["job_module"] == "jobs" and tree["skill_module"] == "skills"
    by_id = {j["id"]: j for j in tree["jobs"]}
    assert tree["count"] == 4
    assert by_id["job_b"]["parent"] == "job_a"
    assert by_id["job_b"]["parent_name"] == "甲职"
    assert by_id["job_b"]["advanced_jobs"] == [{"id": "job_c", "name": "丙职"}]
    assert [s["id"] for s in by_id["job_b"]["inherited_skills"]] == ["a_pass"]
    # 传递继承：丙 ← 乙 ← 甲，继承甲/乙的职业专属技能
    assert [s["id"] for s in by_id["job_c"]["inherited_skills"]] == ["a_pass", "b_act"]
    assert by_id["job_c"]["ancestors"] == ["job_b", "job_a"]
    # 独立职业不继承、无下级
    assert by_id["job_x"]["parent"] is None
    assert by_id["job_x"]["inherited_skills"] == []
    assert by_id["job_x"]["advanced_jobs"] == []
    # 下级的反向索引：甲职下挂乙职
    assert by_id["job_a"]["advanced_jobs"] == [{"id": "job_b", "name": "乙职"}]


def test_api_job_tree_without_jobs_module(tmp_path: Path) -> None:
    root = tmp_path / "content"
    pkg = root / "pack_empty"
    pkg.mkdir(parents=True)
    _write(pkg / "manifest.json", {"name": "E", "version": "1",
                                   "schema_version": 1, "modules": []})
    tree = api.job_tree("pack_empty", root=root)
    assert tree["jobs"] == [] and tree["count"] == 0
    assert tree["job_module"] == ""


# ---------------------------------------------------------------------------
# B. HTTP 入口
# ---------------------------------------------------------------------------
@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    root = _pack(tmp_path)
    with TestClient(create_app(pack="pack_jt", root=str(root), role="gm")) as c:
        yield c


def test_endpoint_job_tree(client: TestClient) -> None:
    r = client.get("/api/pack/pack_jt/job-tree")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["count"] == 4
    assert body["job_module"] == "jobs"


# ---------------------------------------------------------------------------
# C. 前端入口 + 页脚
# ---------------------------------------------------------------------------
def test_html_job_tree_entry_and_modal() -> None:
    html = _html()
    block = re.search(r'<button[^>]*id="btn-job-tree".*?</button>', html, re.S)
    assert block is not None and "进阶继承树" in block.group(0)
    assert 'type="button"' in block.group(0)
    panel = re.search(r'<div id="jobtreepanel".*?</div>\n</div>', html, re.S)
    assert panel is not None, "找不到 jobtreepanel 面板块"
    body = panel.group(0)
    assert 'class="mp-overlay" data-modal="jobtreepanel"' in body
    assert 'role="dialog"' in body and 'aria-modal="true"' in body
    assert "data-modal-close" in body
    assert 'modalBind("jobtreepanel"' in html
    assert 'modalOpen("jobtreepanel", el("btn-job-tree"))' in html


def test_html_job_tree_wiring() -> None:
    html = _html()
    assert "/job-tree" in html, "前端应调用 /api/pack/<包>/job-tree"
    assert "function openJobTree(" in html and "function renderJobTree(" in html
    assert 'el("btn-job-tree").disabled = !state.pack || state.busy' in html
    assert "EditorJobTree.treeText" in html


def test_footer_batch_string_is_current() -> None:
    html = _html()
    assert BATCH_NOTE in html
    assert STALE_BATCH not in html
    assert "批40 · 实例uid与随机流" not in html
    comp = re.search(r'<div class="panel-ft">(.*?)</div>', html, re.S)
    assert comp is not None and BATCH_NOTE in comp.group(1)
    assert "批50 · 特效轴地基" not in html
    assert "批49 · 测试 flake 根治" not in html


# ---------------------------------------------------------------------------
# D. 纯 JS 逻辑（node 执行标记块）
# ---------------------------------------------------------------------------
def test_node_editor_jobtree_pure_logic() -> None:
    harness = (
        "var J = module.exports;\n"
        "var out = {};\n"
        "out.canOpen = [J.canOpen('p'), J.canOpen('')];\n"
        "out.empty = J.treeText({jobs: []});\n"
        "out.text = J.treeText({jobs: ["
        "{id:'job_b', name:'乙职', parent:'job_a', parent_name:'甲职',"
        " advanced_jobs:[{id:'job_c', name:'丙职'}],"
        " inherited_skills:[{id:'a_pass', name:'甲被动'}]},"
        "{id:'job_x', name:'独立职', parent:null, advanced_jobs:[], inherited_skills:[]}"
        "]});\n"
        "console.log(JSON.stringify(out));\n"
    )
    out = _run_node(_marked("EDITOR_JOBTREE") + "\n" + harness)
    assert out["canOpen"] == [True, False]
    assert "没有进阶节点" in out["empty"]
    assert "乙职（job_b）" in out["text"]
    assert "进阶自：甲职" in out["text"]
    assert "下级节点：丙职" in out["text"]
    assert "继承内容：甲被动" in out["text"]
    assert "（无进阶来源）" in out["text"]
    assert "继承内容：—" in out["text"]
