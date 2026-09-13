"""编辑器重写批1 · 宿主只读 API 测试（FastAPI TestClient + 静态页约束）。

宿主在 scripts/editor_host.py（非 qbot_rpg 包内），测试显式把仓库根与 scripts/ 入路径。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from editor_host import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


@pytest.fixture(scope="module")
def client() -> Iterator[TestClient]:
    with TestClient(create_app(pack="veinborn")) as c:
        yield c


def test_api_packs(client: TestClient) -> None:
    r = client.get("/api/packs")
    assert r.status_code == 200
    body = r.json()
    assert body["default"] == "veinborn"
    assert any(p["id"] == "test_demo" for p in body["packs"])


def test_api_modules_includes_hierarchy(client: TestClient) -> None:
    body = client.get("/api/pack/veinborn/modules").json()
    items = next(m for m in body["modules"] if m["module"] == "items")
    assert [c["module"] for c in items["children"]] == ["equipment"]


def test_api_entries_then_entry(client: TestClient) -> None:
    ent = client.get("/api/pack/veinborn/module/skills/entries").json()
    assert ent["count"] > 0
    assert set(ent["entries"][0]) == {"id", "name"}
    eid = ent["entries"][0]["id"]
    det = client.get("/api/pack/veinborn/entry/skills/" + eid).json()
    assert det["id"] == eid
    assert det["field_count"] == len(det["fields"])
    assert det["group_count"] >= 1 and det["meta_source"]


def test_api_errors_are_json(client: TestClient) -> None:
    for url in ("/api/pack/veinborn/module/nope/entries",
                "/api/pack/veinborn/entry/skills/nope",
                "/api/pack/nope/modules"):
        r = client.get(url)
        assert r.status_code == 404
        assert "error" in r.json()


def test_index_and_tokens_are_served_locally(client: TestClient) -> None:
    index = client.get("/")
    assert index.status_code == 200
    css = client.get("/static/tokens.css")
    assert css.status_code == 200 and "--accent" in css.text


def test_frontend_three_columns_and_no_pager(client: TestClient) -> None:
    html = client.get("/").text
    for cls in ("col-mod", "col-list", "panel-body"):
        assert cls in html
    assert "无翻页" in html
    # 面板顶部元数据来源标注（批5.2 · V5：主信息分段 + 来源路径入 title）。
    assert "个字段" in html and "个分组" in html and "元数据来源：" in html
