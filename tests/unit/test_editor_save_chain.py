"""编辑器重写批2 · 保存链路测试。

覆盖任务书「校验（红拦不落盘 / 黄提示可保存）+ 落盘（原子写 + 备份 + 回退）+ 权限位只读拒绝写入」：
  · 全部真实写盘都发生在 tmp_path（绝不触碰仓库 content/ 下任何包）；
  · 字段元数据用本测试自建的通用表注入（编辑器是元数据驱动，不依赖任何具体内容包）；
  · list / map / object 三种模块形态各覆盖编辑落盘；
  · 失败路径（红拦 / 备份失败 / 写盘失败 / 复核失败）一律不得假成功。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterator

import pytest

from qbot_rpg.content import atomic_store
from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

META = FieldMetaTable(modules={
    "widgets": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "count": FieldMeta(type="int", range_min=0, range_max=5, label="数量"),
        "ratio": FieldMeta(type="float", label="比值"),
        "flag": FieldMeta(type="bool", label="开关"),
        "kind": FieldMeta(type="enum", enum=("x", "y"), label="类别"),
        "owner": FieldMeta(type="ref", ref_target="widgets", label="归属"),
    }),
    "others": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "count": FieldMeta(type="int", range_min=0, range_max=5, label="数量"),
    }),
    "stats": ModuleMeta(entry_type="map", value_meta=FieldMeta(type="obj", children={
        "name": FieldMeta(type="str", label="名称"),
        "base": FieldMeta(type="int", range_min=0, range_max=100, label="基准"),
    })),
    "settings": ModuleMeta(entry_type="object", fields={
        "enabled": FieldMeta(type="bool", label="启用"),
    }),
})

WIDGETS_ORIGINAL = [
    {"id": "a", "name": "甲", "count": 3, "ratio": 1.5, "flag": True, "kind": "x", "owner": "a"},
    {"id": "b", "name": "乙", "count": 1},
]


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """自建通用内容包（tmp_path）+ 注入本测试的字段元数据表。"""
    pkg = tmp_path / "pack_u"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "U", "version": "1", "schema_version": 1,
        "modules": ["widgets", "others", "stats", "settings"],
    }, ensure_ascii=False), encoding="utf-8")
    _write(pkg / "widgets.json", WIDGETS_ORIGINAL)
    _write(pkg / "others.json", [{"id": "z", "count": 999}])  # 预置黄提示（与 widgets 无关）
    _write(pkg / "stats.json", {"hp": {"name": "生命", "base": 10}})
    _write(pkg / "settings.json", {"enabled": True})
    monkeypatch.setattr(api, "_META_TABLE", META)
    return tmp_path


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _save(root: Path, entry_id: str, patch: Dict[str, Any], *, module: str = "widgets",
          role: str = "owner") -> Dict[str, Any]:
    return editor_ops.save_entry("pack_u", module, entry_id, patch,
                                 root=root, role=role, meta=META)


def _validate(root: Path, entry_id: str, patch: Dict[str, Any], *, module: str = "widgets"
              ) -> Dict[str, Any]:
    return editor_ops.validate_entry("pack_u", module, entry_id, patch, root=root, meta=META)


# =====================================================================================
# 校验：红拦不落盘 / 黄提示可保存 / 只显示相关提示
# =====================================================================================
def test_validate_red_blocks_without_writing(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    res = _validate(pack_root, "a", {"count": "不是数字"})
    assert res["ok"] is False and res["level"] == "red"
    assert res["errors"], "红拦必须带人话错误"
    err = res["errors"][0]
    assert err["field_label"] == "数量" and err["entry_id"] == "a"
    assert err["how_to_fix"]
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before  # 零落盘
    assert not (pack_root / "pack_u" / "widgets.json.bak").exists()        # 无备份


def test_validate_yellow_marks_but_passes(pack_root: Path) -> None:
    res = _validate(pack_root, "a", {"count": 999})
    assert res["ok"] is True and res["level"] == "yellow"
    assert res["warnings"] and res["warnings"][0]["field_key"] == "count"


def test_validate_scopes_warnings_to_changed_entry(pack_root: Path) -> None:
    # others 模块自身带着黄提示；编辑 widgets 时不应把它算进本次结果
    res = _validate(pack_root, "a", {"count": 4})
    assert res["ok"] is True
    assert all(w["module"] == "widgets" for w in res["warnings"]), res["warnings"]


def test_validate_bad_reference_is_red(pack_root: Path) -> None:
    res = _validate(pack_root, "a", {"owner": "ghost"})
    assert res["ok"] is False
    assert any(e["code"] == "R-4" for e in res["errors"])


# =====================================================================================
# 保存：红拦不落盘 / 正常写盘 + 备份 / 黄提示可保存
# =====================================================================================
def test_save_red_does_not_write_or_backup(pack_root: Path) -> None:
    path = pack_root / "pack_u" / "widgets.json"
    before = path.read_bytes()
    res = _save(pack_root, "a", {"count": "不是数字"})
    assert res["ok"] is False and res["written"] == [] and res["backup"] is None
    assert path.read_bytes() == before
    assert not (pack_root / "pack_u" / "widgets.json.bak").exists()


def test_save_writes_content_and_backup(pack_root: Path) -> None:
    path = pack_root / "pack_u" / "widgets.json"
    bak = pack_root / "pack_u" / "widgets.json.bak"
    original = _read(path)
    res = _save(pack_root, "a", {"count": 4, "name": "甲改"})
    assert res["ok"] is True and res["written"] == ["widgets"]
    assert sorted(res["changed_fields"]) == ["count", "name"]
    assert res["backup"]["exists"] is True and res["backup"]["path"] == "widgets.json.bak"
    after = _read(path)
    assert after[0]["count"] == 4 and after[0]["name"] == "甲改"
    assert after[1] == original[1], "未改动的条目必须原样保留"
    assert _read(bak) == original, "备份必须是写盘前的那一份"
    assert res["level"] == "ok" and not (pack_root / "pack_u" / "widgets.json.tmp").exists()


def test_save_yellow_is_allowed_and_marked(pack_root: Path) -> None:
    res = _save(pack_root, "a", {"count": 999})
    assert res["ok"] is True and res["level"] == "yellow"
    assert res["warnings"]
    assert _read(pack_root / "pack_u" / "widgets.json")[0]["count"] == 999


def test_save_null_removes_field(pack_root: Path) -> None:
    res = _save(pack_root, "a", {"ratio": None})
    assert res["ok"] is True
    assert "ratio" not in _read(pack_root / "pack_u" / "widgets.json")[0]


def test_save_rejects_unknown_field(pack_root: Path) -> None:
    with pytest.raises(api.BadRequest):
        _save(pack_root, "a", {"no_such_field": 1})
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS_ORIGINAL


def test_save_map_module(pack_root: Path) -> None:
    res = _save(pack_root, "hp", {"base": 42}, module="stats")
    assert res["ok"] is True and res["written"] == ["stats"]
    assert _read(pack_root / "pack_u" / "stats.json")["hp"]["base"] == 42
    assert _read(pack_root / "pack_u" / "stats.json.bak")["hp"]["base"] == 10


def test_save_object_module_scalar(pack_root: Path) -> None:
    res = _save(pack_root, "enabled", {"enabled": False}, module="settings")
    assert res["ok"] is True
    assert _read(pack_root / "pack_u" / "settings.json")["enabled"] is False


# =====================================================================================
# 回退：从 .bak 恢复
# =====================================================================================
def test_rollback_restores_previous_backup(pack_root: Path) -> None:
    _save(pack_root, "a", {"count": 4})
    assert _read(pack_root / "pack_u" / "widgets.json")[0]["count"] == 4
    res = editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    assert res["ok"] is True and res["rolled_back"] is True
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS_ORIGINAL


def test_rollback_without_backup_reports_no_backup(pack_root: Path) -> None:
    res = editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    assert res["ok"] is False
    assert res["errors"][0]["code"] == "no_backup"


def test_rollback_keeps_backup_reusable(pack_root: Path) -> None:
    _save(pack_root, "a", {"count": 4})
    editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    again = editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="owner", meta=META)
    assert again["ok"] is True


def test_module_backup_status(pack_root: Path) -> None:
    st = editor_ops.module_backup("pack_u", "widgets", root=pack_root)
    assert st["exists"] is False and st["path"] == "widgets.json.bak"
    _save(pack_root, "a", {"count": 4})
    st2 = editor_ops.module_backup("pack_u", "widgets", root=pack_root)
    assert st2["exists"] is True and st2["size"] > 0


# =====================================================================================
# 权限位：只读身份拒绝写入（后端强制，不依赖前端）
# =====================================================================================
def test_normalize_role() -> None:
    assert editor_ops.normalize_role("owner") == "owner"
    assert editor_ops.normalize_role("admin") == "owner"
    assert editor_ops.normalize_role("manager") == "gm"
    assert editor_ops.normalize_role("GM") == "gm"
    assert editor_ops.normalize_role("weird") == "gm"   # 未知身份安全失败为只读
    assert editor_ops.normalize_role(None) == "gm"


def test_readonly_role_refuses_save(pack_root: Path) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()
    with pytest.raises(api.Forbidden):
        _save(pack_root, "a", {"count": 4}, role="gm")
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before
    assert not (pack_root / "pack_u" / "widgets.json.bak").exists()


def test_readonly_role_refuses_rollback(pack_root: Path) -> None:
    _save(pack_root, "a", {"count": 4})
    after = (pack_root / "pack_u" / "widgets.json").read_bytes()
    with pytest.raises(api.Forbidden):
        editor_ops.rollback_module("pack_u", "widgets", root=pack_root, role="gm", meta=META)
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == after


# =====================================================================================
# 失败路径：绝不假成功
# =====================================================================================
def test_write_failure_reports_no_fake_success(
        pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()

    def _fail(*a: Any, **k: Any) -> Dict[str, Any]:
        return {"ok": False, "errors": [
            {"level": "red", "code": "write_failed", "message": "模拟写盘失败"}]}

    monkeypatch.setattr(atomic_store, "write_modules", _fail)
    res = _save(pack_root, "a", {"count": 4})
    assert res["ok"] is False and res["written"] == []
    assert "写入失败" in res["message"]
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


def test_backup_failure_cancels_write(pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = (pack_root / "pack_u" / "widgets.json").read_bytes()

    def _fail(*a: Any, **k: Any) -> Dict[str, Any]:
        return {"ok": False, "errors": [
            {"level": "red", "code": "backup_failed", "message": "模拟备份失败"}]}

    monkeypatch.setattr(atomic_store, "backup_modules", _fail)
    res = _save(pack_root, "a", {"count": 4})
    assert res["ok"] is False and "备份失败" in res["message"]
    assert (pack_root / "pack_u" / "widgets.json").read_bytes() == before


def test_verify_failure_auto_rolls_back(pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(editor_ops, "_verify_after_write",
                        lambda *a, **k: [{"level": "red", "code": "verify_failed",
                                          "message": "模拟复核失败"}])
    res = _save(pack_root, "a", {"count": 4})
    assert res["ok"] is False and res["rolled_back"] is True
    assert _read(pack_root / "pack_u" / "widgets.json") == WIDGETS_ORIGINAL


def test_atomic_write_leaves_no_tmp_files(pack_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(atomic_store, "write_modules",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _save(pack_root, "a", {"count": 4})
    leftovers = list((pack_root / "pack_u").glob("*.tmp"))
    assert leftovers == []


# =====================================================================================
# HTTP 端点（宿主）：session / validate / save / backup / rollback / refs / 403
# =====================================================================================
_REPO = Path(__file__).resolve().parents[2]
for _p in (str(_REPO), str(_REPO / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _http_pack(tmp_path: Path) -> Path:
    """HTTP 用例用「注册在缺省元数据表里」的通用示例模块（tmp 内容根，绝不碰仓库内容包）。"""
    pkg = tmp_path / "http_pack"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "H", "version": "1", "schema_version": 1, "modules": ["stats"],
    }, ensure_ascii=False), encoding="utf-8")
    _write(pkg / "stats.json", {"hp": {"name": "生命", "base": 10}})
    return tmp_path


@pytest.fixture()
def http_client(tmp_path: Path) -> Iterator[Any]:
    from editor_host import create_app
    from fastapi.testclient import TestClient

    with TestClient(create_app(pack="http_pack", root=str(_http_pack(tmp_path)),
                               role="owner")) as client:
        yield client


def test_http_session_and_role_switch(http_client: Any) -> None:
    body = http_client.get("/api/session").json()
    assert body["editable"] is True and body["role"] == "owner"
    bad = http_client.post("/api/session/role", json={"role": "nope"})
    assert bad.status_code == 400
    assert http_client.post("/api/session/role", json={"role": "gm"}).json()["editable"] is False


def test_http_validate_save_backup_rollback(http_client: Any, tmp_path: Path) -> None:
    pk = tmp_path / "http_pack"
    url = "/api/pack/http_pack/entry/stats/hp"
    red = http_client.post(url + "/validate", json={"patch": {"base": "abc"}}).json()
    assert red["ok"] is False and red["errors"]
    assert _read(pk / "stats.json")["hp"]["base"] == 10
    saved = http_client.post(url + "/save", json={"patch": {"base": 42}}).json()
    assert saved["ok"] is True and saved["backup"]["exists"] is True
    assert _read(pk / "stats.json")["hp"]["base"] == 42
    assert _read(pk / "stats.json.bak")["hp"]["base"] == 10
    assert http_client.get("/api/pack/http_pack/module/stats/backup").json()["exists"] is True
    rolled = http_client.post("/api/pack/http_pack/module/stats/rollback", json={}).json()
    assert rolled["ok"] is True and rolled["rolled_back"] is True
    assert _read(pk / "stats.json")["hp"]["base"] == 10


def test_http_readonly_role_rejects_write(http_client: Any, tmp_path: Path) -> None:
    http_client.post("/api/session/role", json={"role": "gm"})
    pk = tmp_path / "http_pack"
    before = (pk / "stats.json").read_bytes()
    denied = http_client.post("/api/pack/http_pack/entry/stats/hp/save",
                              json={"patch": {"base": 99}})
    assert denied.status_code == 403 and denied.json()["kind"] == "Forbidden"
    assert (pk / "stats.json").read_bytes() == before
    rolled = http_client.post("/api/pack/http_pack/module/stats/rollback", json={})
    assert rolled.status_code == 403


def test_http_refs_endpoint(http_client: Any) -> None:
    out = http_client.get("/api/pack/http_pack/refs/stat").json()
    assert out["known"] is True
    assert any(o["id"] == "hp" and o["name"] == "生命" for o in out["options"])


def test_http_validate_on_missing_entry_is_404(http_client: Any) -> None:
    r = http_client.post("/api/pack/http_pack/entry/stats/ghost/validate", json={"patch": {}})
    assert r.status_code == 404
