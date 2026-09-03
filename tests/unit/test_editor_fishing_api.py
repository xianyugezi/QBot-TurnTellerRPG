"""M12.5 批3 路3B · 钓鱼 obj 页专属端点单测（schema/csv validate/crown/simulate）。

依据：m10_shared_contract（fishing_editor_service T19 服务层：fish_card_schema/
fish_csv_import/validate/crown_preview/simulate_catches 纯函数）+ m125_启动包 §2.4
（钓鱼表单直接复用服务层，UI 归批4）。本测试验证 web/api.py 新增 4 端点把
服务层接成 HTTP 契约（零写盘——编辑写盘仍走 obj 页 CRUD/原始 JSON）。

铁律：零 NoneBot import；纯 pytest；TestClient；无 emoji；ruff E501 零豁免。
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from qbot_rpg.content.registry import Registry
from qbot_rpg.web.api import create_app
from qbot_rpg.web.auth import AuthStore

_FISHING_RAW = {
    "schema_version": "1.0",
    "species": [{
        "id": "silver_carp", "name": "银鲤", "rarity": "common",
        "size_min": 10, "size_max": 60, "weight_min": 0.5, "weight_max": 8.0,
        "seasons": ["春", "夏", "秋", "冬"], "periods": ["全天"],
        "hours": "06:00-18:00", "spots": ["river"],
        "preferred_bait": "饵_蚯蚓", "codex_text": "常见的河鱼。", "king": False,
    }],
    "king": [],
}
_SETTINGS_RAW = {
    "fishing": {
        "mode": "full",
        "bait_ids": ["饵_蚯蚓", "饵_面团", "饵_小鱼", "饵_黄金虫"],
    },
}


def _make_registry() -> Registry:
    return Registry(pack_id="test_pack", generation=1, tables={}, names={},
                    modules_raw={"fishing": _FISHING_RAW, "settings": _SETTINGS_RAW})


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


def _token(c: TestClient) -> str:
    r = c.post("/api/auth/login", json={"qq_id": "owner1", "password": "pass1234"})
    assert r.status_code == 200
    return r.json()["data"]["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _setup(tmp_path: Path) -> tuple[TestClient, str]:
    """同一 state 的 client + owner token（AuthStore 实例互通）。"""
    c = TestClient(create_app(make_state(tmp_path)))
    return c, _token(c)


def test_fishing_schema_endpoint(tmp_path: Path) -> None:
    """GET /editor/fishing/schema → 九键字段 schema（settings.fishing 表单源）。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/editor/fishing/schema", headers=_auth(token))
    assert r.status_code == 200
    schema = r.json()["data"]["schema"]
    assert isinstance(schema, dict) and len(schema) >= 5
    for key in ("mode", "bait_ids", "crown_thresholds", "energy", "wait_sec"):
        assert key in schema, f"schema 缺 {key}"


def test_fishing_csv_validate_valid(tmp_path: Path) -> None:
    """CSV 预检：导出→导入往返（服务层同款 13 列契约）→ errors 空 + total 正确。"""
    c, token = _setup(tmp_path)
    # 用服务层导出生成合法 CSV 文本（13 列固定契约，避免手写列错）
    from qbot_rpg.editor.fishing_editor_service import fish_csv_export
    csv_text = fish_csv_export([{
        "id": "silver_carp", "name": "银鲤", "rarity": "normal",
        "size_min": 10, "size_max": 60, "weight_min": 0.5, "weight_max": 8.0,
        "seasons": ["spring", "summer"], "periods": ["dawn"],
        "hours": "06:00-18:00", "spots": ["river"],
        "preferred_bait": ["饵_蚯蚓"], "codex_text": "常见的河鱼。",
    }])
    r = c.post("/api/editor/fishing/csv/validate",
               json={"text": csv_text}, headers=_auth(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["total"] == 1
    assert data["errors"] == []


def test_fishing_csv_validate_bad_row(tmp_path: Path) -> None:
    """CSV 预检：非法行（id 重复）→ errors 非空。"""
    c, token = _setup(tmp_path)
    from qbot_rpg.editor.fishing_editor_service import fish_csv_export
    row = {
        "id": "dup_fish", "name": "鱼", "rarity": "normal",
        "size_min": 10, "size_max": 60, "weight_min": 0.5, "weight_max": 8.0,
        "seasons": ["spring"], "periods": ["dawn"], "hours": "06:00-18:00",
        "spots": ["river"], "preferred_bait": ["饵_蚯蚓"], "codex_text": "x",
    }
    csv_text = fish_csv_export([row, dict(row)])  # 两行同 id → 重复红拦
    r = c.post("/api/editor/fishing/csv/validate",
               json={"text": csv_text}, headers=_auth(token))
    assert r.status_code == 200
    assert len(r.json()["data"]["errors"]) >= 1


def test_fishing_crown_preview(tmp_path: Path) -> None:
    """冠级预览：百分位 → 档位（含中文标签）。"""
    c, token = _setup(tmp_path)
    r = c.get("/api/editor/fishing/crown_preview?size=95&weight=95",
              headers=_auth(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["crown"] in ("reverse", "big_gold", "gold", "big_silver",
                             "silver", "normal")
    assert isinstance(data["label"], str) and data["label"]
    assert data["pct_size"] == 95.0


def test_fishing_simulate_deterministic(tmp_path: Path) -> None:
    """图鉴模拟：种子化确定性（同 seed 两次结果一致）+ 分布键。"""
    c, token = _setup(tmp_path)
    body = {"species": _FISHING_RAW["species"], "n": 200, "seed": 42}
    r1 = c.post("/api/editor/fishing/simulate", json=body, headers=_auth(token))
    r2 = c.post("/api/editor/fishing/simulate", json=body, headers=_auth(token))
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["data"] == r2.json()["data"], "同 seed 应确定性一致"
    assert "distribution" in r1.json()["data"] or "total" in r1.json()["data"]


def test_fishing_simulate_missing_species(tmp_path: Path) -> None:
    """图鉴模拟缺 species → 422（detail 内 ok:false）。"""
    c, token = _setup(tmp_path)
    r = c.post("/api/editor/fishing/simulate", json={}, headers=_auth(token))
    assert r.status_code == 422
    body = r.json()
    detail = body.get("detail", body)  # FastAPI HTTPException detail 包裹
    assert detail.get("ok") is False
