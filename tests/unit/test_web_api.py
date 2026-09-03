"""Web 编辑器 API 冒烟测试（tests/unit/test_web_api.py · M12 批3 路3C）。

依据：docs/细化/细化_5a_编辑器契约.md §6（15 端点 L160-189：认证 4 / 元数据
引用 2 / 六页 CRUD+校验 6 / 热重载+数据包 3；统一包络 L183）+ m12_启动包
批3 路3C（web/api.py 总装）。

覆盖：
  - setup → login → me 全链（Bearer token）
  - 未认证访问 401
  - /api/meta/{page} 字段元数据（skill 页）
  - /api/refs/{target} 引用候选（monster → enemies 表）
  - /api/pages/{page} 列表/新建/validate
  - /api/packs 数据包信息
  - create_app 缺 fastapi → RuntimeError（不测，装了 fastapi）
  - iter_routes 枚举路由数 ≥15

铁律：零 NoneBot import；纯 pytest；TestClient（starlette）；state 假装配
      （假 registry + 真 AuthStore + tmp_path content_dir）；无 emoji。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from qbot_rpg.content.registry import Registry
from qbot_rpg.web.api import create_app, iter_routes
from qbot_rpg.web.auth import AuthStore

# =============================================================================
# 假装配（state）
# =============================================================================
def make_registry() -> Registry:
    """假 registry：enemies/maps 模块数据（CRUD 列表读 modules_raw）。"""
    return Registry(
        pack_id="test_pack",
        generation=1,
        tables={},
        names={},
        modules_raw={
            "enemies": [{"id": "gust_wolf", "name": "风狼", "hp": 90, "atk": 12}],
            "maps": [{"id": "forest", "name": "风语森林",
                      "monsters": [{"enemy": "gust_wolf"}]}],
            "skills": [{"id": "slash", "name": "脊斩"}],
            "jobs": [{"id": "ridge_blade", "name": "脊剑士"}],
            "quest": [{"id": "q1", "name": "讨伐风狼"}],
            "shop": [{"id": "s1", "name": "杂货店"}],
            "items": [{"id": "potion", "name": "药水"}],
        },
        # manifest 缺省 None（测试不构造真 Manifest——packs 端点 data.active 空）
    )


def make_state(tmp_path: Path) -> SimpleNamespace:
    """state：真 AuthStore + 假 registry + tmp content_dir。"""
    auth = AuthStore(owner_qq_id="owner1", gm_qq_ids={"gm1"})
    auth.setup_password("owner1", "pass1234")
    return SimpleNamespace(
        auth_store=auth,
        registry=make_registry(),
        content_dir=tmp_path,
        editor=None,
        permission_store=None,
        audit_store=None,
    )


def make_client(state: SimpleNamespace) -> TestClient:
    """TestClient 构造。"""
    return TestClient(create_app(state))


def owner_token(client: TestClient) -> str:
    """登录拿 owner token。"""
    r = client.post("/api/auth/login", json={"qq_id": "owner1", "password": "pass1234"})
    assert r.status_code == 200
    return r.json()["data"]["token"]


def auth_h(token: str) -> dict:
    """Bearer header。"""
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 认证全链
# =============================================================================
def test_setup_login_me_flow(tmp_path: Path) -> None:
    """setup 已设 → login 发 token → me 返回 owner。"""
    state = make_state(tmp_path)  # setup 已在 make_state
    client = make_client(state)
    # 重复 setup → 409
    r = client.post("/api/auth/setup", json={"qq_id": "owner1", "password": "x"})
    assert r.status_code == 409
    # login
    r = client.post("/api/auth/login", json={"qq_id": "owner1", "password": "pass1234"})
    assert r.status_code == 200
    token = r.json()["data"]["token"]
    # me
    r = client.get("/api/auth/me", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["user"]["role"] == "owner"
    # logout → me 401
    client.post("/api/auth/logout", headers=auth_h(token))
    r = client.get("/api/auth/me", headers=auth_h(token))
    assert r.status_code == 401


def test_unauthorized_401(tmp_path: Path) -> None:
    """未认证访问受保护端点 → 401。"""
    client = make_client(make_state(tmp_path))
    for method, path in [("get", "/api/auth/me"),
                         ("get", "/api/pages/monster"),
                         ("get", "/api/packs")]:
        r = getattr(client, method)(path)
        assert r.status_code == 401, f"{method} {path} 应 401"


def test_login_wrong_password_401(tmp_path: Path) -> None:
    """错误密码 → 401。"""
    client = make_client(make_state(tmp_path))
    r = client.post("/api/auth/login", json={"qq_id": "owner1", "password": "wrong"})
    assert r.status_code == 401


# =============================================================================
# 元数据 + 引用
# =============================================================================
def test_meta_page_skill(tmp_path: Path) -> None:
    """/api/meta/skill → 字段元数据（skill 页有 fields）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/meta/skill", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["page"] == "skill"


def test_meta_unknown_404(tmp_path: Path) -> None:
    """未知页 meta → 404。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/meta/ghost_page", headers=auth_h(token))
    assert r.status_code == 404


def test_refs_monster(tmp_path: Path) -> None:
    """/api/refs/monster → enemies 表候选（gust_wolf/风狼）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/refs/monster", headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert any(i["id"] == "gust_wolf" and i["name"] == "风狼" for i in items)


# =============================================================================
# 六页 CRUD
# =============================================================================
def test_pages_list(tmp_path: Path) -> None:
    """/api/pages/monster → 列表（风狼）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/pages/monster", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["total"] == 1
    assert r.json()["data"]["items"][0]["id"] == "gust_wolf"


def test_pages_create_writes_file(tmp_path: Path) -> None:
    """POST /api/pages/monster 新建 → 原子写盘落 tmp content_dir。"""
    state = make_state(tmp_path)
    client = make_client(state)
    token = owner_token(client)
    r = client.post("/api/pages/monster", headers=auth_h(token),
                    json={"name": "新怪", "hp": 50})
    assert r.status_code == 200
    item = r.json()["data"]["item"]
    assert item["id"] == "monster_0001"
    # 文件落盘（enemies.json 含新怪）
    f = tmp_path / "enemies.json"
    assert f.exists()
    import json
    data = json.loads(f.read_text(encoding="utf-8"))
    assert any(e["id"] == "monster_0001" for e in data)


def test_pages_validate_red(tmp_path: Path) -> None:
    """POST /api/pages/monster/validate 负 hp → red 清单。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.post("/api/pages/monster/validate", headers=auth_h(token),
                    json={"id": "x", "name": "怪", "hp": -5})
    assert r.status_code == 200
    red = r.json()["data"]["red"]
    assert any(e["level"] == "red" and e["code"] == "negative" for e in red)


def test_pages_get_and_delete(tmp_path: Path) -> None:
    """GET 详情 + DELETE 级联（写盘移除）。"""
    state = make_state(tmp_path)
    client = make_client(state)
    token = owner_token(client)
    r = client.get("/api/pages/monster/gust_wolf", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["item"]["name"] == "风狼"
    # delete
    r = client.delete("/api/pages/monster/gust_wolf", headers=auth_h(token))
    assert r.status_code == 200
    f = tmp_path / "enemies.json"
    import json
    data = json.loads(f.read_text(encoding="utf-8"))
    assert all(e["id"] != "gust_wolf" for e in data)


# =============================================================================
# 热重载 + 数据包
# =============================================================================
def test_packs_info(tmp_path: Path) -> None:
    """/api/packs → 数据包信息（registry 无 manifest → active 空但端点 200）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/packs", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert "active" in data
    assert "generation" in data


def test_reload_endpoint(tmp_path: Path) -> None:
    """POST /api/reload → 200（registry 精简数据过不了 check_pack → 回退 ok False
    但端点不崩——SV-07 语义）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.post("/api/reload", headers=auth_h(token))
    assert r.status_code == 200
    body = r.json()
    assert "ok" in body


def test_iter_routes_15(tmp_path: Path) -> None:
    """iter_routes 枚举 15 端点（method+path 组合数；同 path 多 method 各计）。"""
    routes = iter_routes(create_app(make_state(tmp_path)))
    api_eps = [r for r in routes if r["path"].startswith("/api")]
    # 15 端点 = auth 4 + meta/refs 2 + pages CRUD/validate 6 + reload/packs 3
    assert len(api_eps) >= 15
    # 关键路径存在（同 path 多 method 合并成集合后核对）
    paths = {r["path"] for r in api_eps}
    for expect in ("/api/auth/setup", "/api/auth/login", "/api/auth/me",
                   "/api/auth/logout", "/api/meta/{page}", "/api/refs/{target}",
                   "/api/pages/{page}", "/api/pages/{page}/{item_id}",
                   "/api/pages/{page}/validate", "/api/reload",
                   "/api/packs", "/api/packs/active"):
        assert expect in paths, f"缺少路由 {expect}"
