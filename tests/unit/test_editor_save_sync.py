"""M12.5 全量测试抓 P0 回归：list 保存后内存数据源同步（_save_pipeline）。

缺陷：_save_pipeline 写盘成功后未把 entries 合并回 reg.modules_raw → 列表/
搜索仍显示旧快照，且后续基于旧内存的再保存会覆盖磁盘新值（丢改）。
本测试断言：POST /pages/{page} 新建 → 内存 modules_raw 立即可见新条目；
PUT 更新 → 内存值 = 新值（与磁盘一致）。

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
        {"page_id": "skill", "title": "技能", "module_file": "skills.json",
         "meta_source": "meta/skill", "enabled": True},
    ],
}


def _make_registry() -> Registry:
    return Registry(pack_id="test_pack", generation=1, tables={}, names={},
                    modules_raw={"editor": _EDITOR_RAW, "skills": [
                        {"id": "slash", "name": "脊斩"},
                    ]})


def _setup(tmp_path: Path) -> tuple[TestClient, str, Registry]:
    auth = AuthStore(owner_qq_id="o1", gm_qq_ids=set())
    auth.setup_password("o1", "pass1234")
    reg = _make_registry()
    state = SimpleNamespace(auth_store=auth, registry=reg,
                            content_dir=tmp_path, editor=None,
                            permission_store=None, audit_store=None)
    c = TestClient(create_app(state))
    r = c.post("/api/auth/login", json={"qq_id": "o1", "password": "pass1234"})
    token = r.json()["data"]["token"]
    return c, token, reg


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_create_updates_memory_registry(tmp_path: Path) -> None:
    """POST 新建 → 内存 modules_raw 立即可见新条目（非仅磁盘）。"""
    c, token, reg = _setup(tmp_path)
    r = c.post("/api/pages/skill", json={"name": "新技能"},
               headers=_auth(token))
    assert r.status_code == 200, r.text
    new_id = r.json()["data"]["item"]["id"]
    # 内存同步断言（缺陷回归：修复前内存无此条目 → 列表搜不到）
    mem = reg.modules_raw["skills"]
    assert any(e.get("id") == new_id for e in mem), "内存 modules_raw 缺新条目"
    # 搜索端点立即可见
    r2 = c.get(f"/api/pages/skill?q={new_id}", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.json()["data"]["total"] >= 1


def test_update_syncs_memory_registry(tmp_path: Path) -> None:
    """PUT 更新 → 内存 modules_raw 值 = 新值（防旧内存覆盖丢改）。"""
    c, token, reg = _setup(tmp_path)
    r = c.put("/api/pages/skill/slash", json={"name": "脊斩改"},
              headers=_auth(token))
    assert r.status_code == 200, r.text
    mem = reg.modules_raw["skills"]
    hit = next(e for e in mem if e.get("id") == "slash")
    assert hit["name"] == "脊斩改", "内存 modules_raw 未同步新值"
    # 再次保存基于新内存不丢改
    r2 = c.put("/api/pages/skill/slash", json={"name": "脊斩改2"},
               headers=_auth(token))
    assert r2.status_code == 200
    mem2 = reg.modules_raw["skills"]
    assert next(e for e in mem2 if e.get("id") == "slash")["name"] == "脊斩改2"


def test_extension_page_create_not_404(tmp_path: Path) -> None:
    """扩展页（editor.json 登记非六页）create/update 非 404（P1 回归）。

    缺陷：_save_pipeline 原查 PAGE_MODULE 六页常量 → items/effects 等扩展页
    create/update 全 404；改走 page_module_of 动态解析后应 200。
    """
    c, token, reg = _setup(tmp_path)
    # 给 editor 页表加 items 登记 + items 模块数据
    reg.modules_raw["editor"]["pages"].append(
        {"page_id": "items", "title": "物品", "module_file": "items.json",
         "meta_source": "meta/items", "enabled": True})
    reg.modules_raw["items"] = [{"id": "potion", "name": "药水", "type": "consumable"}]
    # create
    r = c.post("/api/pages/items", json={"name": "新物品", "type": "material"},
               headers=_auth(token))
    assert r.status_code == 200, r.text
    new_id = r.json()["data"]["item"]["id"]
    assert new_id.startswith("items_"), f"ID 应 items_ 前缀：{new_id}"
    # update
    r2 = c.put(f"/api/pages/items/{new_id}", json={"name": "新物品改"},
               headers=_auth(token))
    assert r2.status_code == 200, r2.text
    assert r2.json()["data"]["item"]["name"] == "新物品改"
