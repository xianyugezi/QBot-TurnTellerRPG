"""批34 · 宿主 HTTP 入口：模块级 CSV 导出 / 导入（FastAPI TestClient + 临时内容根）。

只写 tmp_path 的临时内容根；绝不触碰仓库 content/（批19.1 防污染门禁）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Iterator

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from editor_host import create_app  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta  # noqa: E402
from qbot_rpg.web import api  # noqa: E402

META = FieldMetaTable(modules={
    "alpha": ModuleMeta(entry_type="list", id_field="id", kind="alpha", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "note": FieldMeta(type="str", label="备注"),
        "effect": FieldMeta(type="ref", ref_target="effect", label="效果"),
    }),
    "effect": ModuleMeta(entry_type="list", id_field="id", kind="effect", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
    }),
    "beta": ModuleMeta(entry_type="map", id_field="id", kind="beta",
                       value_meta=FieldMeta(type="obj", children={
                           "name": FieldMeta(type="str", label="名称"),
                       })),
})


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(api, "_META_TABLE", META)
    root = tmp_path / "content"
    pkg = root / "pack_csv"
    pkg.mkdir(parents=True)
    _write(pkg / "manifest.json", {
        "name": "C", "version": "1", "schema_version": 1,
        "modules": ["alpha", "effect", "beta"]})
    _write(pkg / "alpha.json", [{"id": "a1", "name": "甲", "note": "=cmd|calc"}])
    _write(pkg / "effect.json", [{"id": "e1", "name": "效果一"}])
    _write(pkg / "beta.json", {"b1": {"name": "一"}})
    return root


@pytest.fixture()
def owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    root = _root(tmp_path, monkeypatch)
    with TestClient(create_app(pack="pack_csv", root=str(root), role="owner")) as c:
        yield c


@pytest.fixture()
def gm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    root = _root(tmp_path, monkeypatch)
    with TestClient(create_app(pack="pack_csv", root=str(root), role="gm")) as c:
        yield c


def test_export_csv_endpoint_downloads_bom_utf8(owner: TestClient) -> None:
    r = owner.get("/api/pack/pack_csv/module/alpha/export_csv")
    assert r.status_code == 200
    assert r.content.startswith("\ufeff".encode("utf-8"))
    assert "标识(id)" in r.text
    assert "'=cmd|calc" in r.text, "危险文本必须被中和"
    assert r.headers["content-disposition"].startswith("attachment;")
    assert r.headers["x-csv-filename"] == "pack_csv-alpha.csv"


def test_export_csv_endpoint_is_read_only(owner: TestClient, tmp_path: Path) -> None:
    # 通过同一个 app 的 content_root 找到包文件并核对未被改动
    before = None
    for p in tmp_path.rglob("alpha.json"):
        before = p.read_bytes()
    owner.get("/api/pack/pack_csv/module/alpha/export_csv")
    for p in tmp_path.rglob("alpha.json"):
        assert p.read_bytes() == before
    assert not any(p.name == "alpha.json.bak" for p in tmp_path.rglob("*"))


def test_import_csv_endpoint_appends_in_row_order(owner: TestClient, tmp_path: Path) -> None:
    body = "标识(id),名称(name)\nz1,一\nz2,二\n".encode("utf-8")
    r = owner.post("/api/pack/pack_csv/module/alpha/import_csv"
                   "?mode=append&on_conflict=skip", content=body)
    assert r.status_code == 200
    res = r.json()
    assert res["ok"] is True and res["summary"]["success"] == 2
    for p in tmp_path.rglob("alpha.json"):
        data = json.loads(p.read_text(encoding="utf-8"))
        assert [e["id"] for e in data] == ["a1", "z1", "z2"]
        assert p.with_suffix(".json.bak").exists(), "导入前应自动备份"


def test_import_csv_endpoint_missing_ref_rejects_whole_batch(owner: TestClient,
                                                             tmp_path: Path) -> None:
    before = next(tmp_path.rglob("alpha.json")).read_bytes()
    body = "标识(id),名称(name),效果(effect)\nz1,一,e1\nz2,二,e_missing\n".encode("utf-8")
    r = owner.post("/api/pack/pack_csv/module/alpha/import_csv", content=body)
    assert r.status_code == 200
    res = r.json()
    assert res["ok"] is False
    errs = [e for e in res["errors"] if e["code"] == "csv_ref_missing"]
    assert errs and errs[0]["line"] == 3 and errs[0]["missing"] == "e_missing"
    # 整批拒绝：文件未动、未生成备份
    assert next(tmp_path.rglob("alpha.json")).read_bytes() == before
    assert not any(p.name == "alpha.json.bak" for p in tmp_path.rglob("*"))


def test_import_csv_gm_role_forbidden(gm: TestClient) -> None:
    r = gm.post("/api/pack/pack_csv/module/alpha/import_csv",
                content="标识(id)\nz1\n".encode("utf-8"))
    assert r.status_code == 403
    assert r.json()["kind"] == "Forbidden"


def test_export_csv_unknown_module_rejected(owner: TestClient) -> None:
    r = owner.get("/api/pack/pack_csv/module/nope/export_csv")
    assert r.status_code == 404
