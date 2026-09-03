"""M12.5 批4 · obj/map 形态读写端点单测（settings/forge/fishing 整对象 +
stats/formula 键值表）。

依据：m125_启动包 §2.3/§2.4（map 型页=键值编辑器 + formula 校验；obj 型页=
段表单——非 list 条目形态）+ 批4 后端 pages_crud.module_shape/get_whole_module/
update_whole_module/get_map_key/put_map_key/delete_map_key + api /pages/{page}/
whole + /pages/{page}/map/{key} 端点。写盘走原子写盘（tmp content_dir）。

铁律：零 NoneBot import；纯 pytest；TestClient；无 emoji；ruff E501 零豁免。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from qbot_rpg.content.registry import Registry
from qbot_rpg.web.api import create_app
from qbot_rpg.web.auth import AuthStore

_EDITOR_RAW = {
    "schema_version": 1,
    "pages": [
        {"page_id": "settings", "title": "世界设置", "module_file": "settings.json",
         "meta_source": "meta/settings", "enabled": True, "page_kind": "object"},
        {"page_id": "forge", "title": "锻造", "module_file": "forge.json",
         "meta_source": "meta/forge", "enabled": True, "page_kind": "object"},
        {"page_id": "stats", "title": "属性表", "module_file": "stats.json",
         "meta_source": "meta/stats", "enabled": True, "page_kind": "map"},
        {"page_id": "formula", "title": "公式", "module_file": "formula.json",
         "meta_source": "meta/formula", "enabled": True, "page_kind": "map"},
        {"page_id": "monster", "title": "怪物", "module_file": "enemies.json",
         "meta_source": "meta/monster", "enabled": True},
    ],
}
_SETTINGS_RAW = {"default_map": "start_village", "world_name": "测试世界",
                 "currencies": [{"id": "coins", "name": "金币"}]}
_FORGE_RAW = {"schema_version": "1.0", "trees": [{"id": "t1"}]}
_STATS_RAW = {"hp": {"name": "生命", "base": 100}, "mp": {"name": "魔法", "base": 50}}
_FORMULA_RAW = {"damage_base": "atk * 2", "heal_rate": "0.5"}
_ENEMIES_RAW = [{"id": "gust_wolf", "name": "风狼"}]


def _make_registry() -> Registry:
    return Registry(pack_id="test_pack", generation=1, tables={}, names={},
                    modules_raw={
                        "editor": _EDITOR_RAW,
                        "settings": _SETTINGS_RAW,
                        "forge": _FORGE_RAW,
                        "stats": _STATS_RAW,
                        "formula": _FORMULA_RAW,
                        "enemies": _ENEMIES_RAW,
                    })


def make_state(tmp_path: Path) -> SimpleNamespace:
    auth = AuthStore(owner_qq_id="owner1", gm_qq_ids={"gm1"})
    auth.setup_password("owner1", "pass1234")
    return SimpleNamespace(
        auth_store=auth,
        registry=_make_registry(),
        content_dir=tmp_path,
        editor=None,
        permission_store=None,
        audit_store=None,
    )


def _setup(tmp_path: Path) -> tuple[TestClient, str]:
    c = TestClient(create_app(make_state(tmp_path)))
    r = c.post("/api/auth/login", json={"qq_id": "owner1", "password": "pass1234"})
    assert r.status_code == 200
    return c, r.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_obj_whole_get(tmp_path: Path) -> None:
    """obj 页整模块读（settings）：data = 顶层 obj dict + shape=obj。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/pages/settings/whole", headers=_auth(token))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["shape"] == "obj"
    assert d["data"]["world_name"] == "测试世界"


def test_obj_whole_put_merges(tmp_path: Path) -> None:
    """obj 页整模块保存：合并覆盖 + 原子写盘落盘。"""
    c, token = _setup(tmp_path)
    body = {"world_name": "改名世界", "new_key": 1}
    r = c.put("/api/pages/settings/whole", json=body, headers=_auth(token))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["data"]["world_name"] == "改名世界"
    # 原键保留（合并）+ 新键加入
    assert d["data"]["default_map"] == "start_village"
    # 落盘验证（tmp content_dir settings.json）
    import json
    disk = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert disk["world_name"] == "改名世界"


def test_list_page_whole_returns_list(tmp_path: Path) -> None:
    """list 页 /whole 兼容返回（list 条目数组，shape=list）。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/pages/monster/whole", headers=_auth(token))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["shape"] == "list"
    assert isinstance(d["data"], list)


def test_list_page_whole_put_rejected(tmp_path: Path) -> None:
    """list 页整模块保存 → 422（shape_mismatch）。"""
    c, token = _setup(tmp_path)
    r = c.put("/api/pages/monster/whole", json={"x": 1}, headers=_auth(token))
    assert r.status_code == 422
    body = r.json()
    detail = body.get("detail", body)
    assert detail.get("ok") is False


def test_map_whole_get(tmp_path: Path) -> None:
    """map 页整模块读（stats）：shape=map + 键值 dict。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/pages/stats/whole", headers=_auth(token))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["shape"] == "map"
    assert "hp" in d["data"] and "mp" in d["data"]


def test_map_key_get_put_delete(tmp_path: Path) -> None:
    """map 页单键读/写/删（stats：hp → 新值 → 删除）+ 落盘。"""
    c, token = _setup(tmp_path)
    # get 单键
    r = c.get("/api/pages/stats/map/hp", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["data"]["value"]["base"] == 100
    # put 单键（覆盖）
    r = c.put("/api/pages/stats/map/hp", json={"value": {"name": "生命", "base": 999}},
              headers=_auth(token))
    assert r.status_code == 200
    # delete 单键
    r = c.delete("/api/pages/stats/map/mp", headers=_auth(token))
    assert r.status_code == 200
    # 落盘验证
    import json
    disk = json.loads((tmp_path / "stats.json").read_text(encoding="utf-8"))
    assert disk["hp"]["base"] == 999
    assert "mp" not in disk


def test_map_key_missing_404(tmp_path: Path) -> None:
    """map 页读不存在键 → 404。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/pages/formula/map/ghost", headers=_auth(token))
    assert r.status_code == 404
