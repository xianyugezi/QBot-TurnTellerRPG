"""M12.5 批1 路1B · editor_registry/api.py 动态化单测（meta/refs/pages 端点）。

依据：docs/m125_启动包.md §2.1（meta 映射动态化 + refs 候选覆盖全部 kind +
editor.json 页表扩展）+ docs/m125_编辑器硬编码清单.md 审计点 #16/#17/#18。
覆盖：
  - meta_page：12 页全登记（含 extend 页/settings 段视图页）经 TestClient
    全解析出 fields 不 404；未知页 404 语义保持
  - meta_page：page_kind/entry_type 透传（登记值优先；缺省按 entry_type 推导）
  - refs_target：别名覆盖（monster/skill/effect/chain/dungeon）+ field_meta
    表键直查（settings/enemies）+ 未知 target 空列表不 404
  - /api/editor/pages：validator/id_prefix/group/page_kind 透传（全字段）

铁律：零 NoneBot import；纯 pytest；TestClient（starlette）；state 假装配
      （假 registry + 真 AuthStore + tmp_path content_dir）；无 emoji；
      ruff E501 零豁免（行宽 ≤100）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from qbot_rpg.content.registry import Registry
from qbot_rpg.web.api import create_app, _refs_module_for_target
from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.editor_registry import load_editor_registry

# =============================================================================
# 假装配（state）：registry 带 editor 模块 12 页全登记 + 元数据模块原始数据
# =============================================================================
_EDITOR_RAW = {
    "schema_version": 1,
    "pages": [
        {"page_id": "skill", "title": "技能", "module_file": "skills.json",
         "meta_source": "meta/skill", "enabled": True, "validator": "skill"},
        {"page_id": "job", "title": "职业", "module_file": "jobs.json",
         "meta_source": "meta/job", "enabled": True, "validator": "job"},
        {"page_id": "monster", "title": "怪物", "module_file": "enemies.json",
         "meta_source": "meta/monster", "enabled": True, "validator": "monster"},
        {"page_id": "map", "title": "地图", "module_file": "maps.json",
         "meta_source": "meta/map", "enabled": True, "validator": "map"},
        {"page_id": "quest", "title": "任务", "module_file": "quest.json",
         "meta_source": "meta/quest", "enabled": True, "validator": "quest"},
        {"page_id": "shop", "title": "商店", "module_file": "shop.json",
         "meta_source": "meta/shop", "enabled": True, "validator": "shop"},
        {"page_id": "npc", "title": "NPC", "module_file": "npc.json",
         "meta_source": "meta/npc", "enabled": True, "validator": "npc"},
        {"page_id": "checkin", "title": "签到", "module_file": "checkin.json",
         "meta_source": "meta/checkin", "enabled": True, "validator": "checkin"},
        {"page_id": "ai", "title": "AI", "module_file": "enemies.json",
         "meta_source": "meta/ai", "enabled": True, "validator": "ai",
         "extends": "monster"},
        {"page_id": "hidden", "title": "隐藏要素", "module_file": "maps.json",
         "meta_source": "meta/hidden", "enabled": True, "validator": "hidden"},
        {"page_id": "env_event", "title": "环境事件", "module_file": "settings.json",
         "meta_source": "meta/env_event", "enabled": True, "validator": "env_event",
         "group": "世界", "page_kind": "object"},
        {"page_id": "log_card", "title": "日志卡片", "module_file": "settings.json",
         "meta_source": "meta/log_card", "enabled": True, "validator": "log_card",
         "group": "世界", "page_kind": "view"},
    ],
}

_META_MODULES_RAW = {
    "skills": [{"id": "slash", "name": "脊斩"}],
    "jobs": [{"id": "ridge_blade", "name": "脊剑士"}],
    "enemies": [{"id": "gust_wolf", "name": "风狼"}],
    "maps": [{"id": "forest", "name": "风语森林"}],
    "quest": [{"id": "q1", "name": "讨伐风狼"}],
    "shop": [{"id": "s1", "name": "杂货店"}],
    "npc": [{"id": "elder", "name": "长老"}],
    "checkin": [{"id": "c1", "name": "七日签到"}],
    "settings": [{"id": "world", "name": "世界"}],
    "items": [{"id": "potion", "name": "药水"}],
    "effects": [{"id": "heal", "name": "治疗"}],
    "statuses": [{"id": "burn", "name": "灼烧"}],
    "marks": [{"id": "m1", "name": "印记"}],
    "traits": [{"id": "t1", "name": "词条"}],
    "action": [{"id": "a1", "name": "行动"}],
    "recipe": [{"id": "r1", "name": "配方"}],
    "equipment": [{"id": "e1", "name": "装备"}],
    "slots": [{"id": "s1", "name": "槽位"}],
    "skill_chains": [{"id": "sc1", "name": "技能链"}],
    "dungeon": [{"id": "d1", "name": "副本"}],
    "achievements": [{"id": "ac1", "name": "成就"}],
}


def _make_registry() -> Registry:
    """假 registry：editor 12 页登记 + 21 元数据模块原始数据。"""
    return Registry(pack_id="test_pack", generation=1, tables={}, names={},
                    modules_raw=dict({"editor": _EDITOR_RAW}, **_META_MODULES_RAW))


def make_state(tmp_path: Path) -> SimpleNamespace:
    """state：editor=EditorRegistry（12 页）+ 假 registry + tmp content_dir。"""
    from qbot_rpg.web.auth import AuthStore
    auth = AuthStore(owner_qq_id="owner1", gm_qq_ids={"gm1"})
    auth.setup_password("owner1", "pass1234")
    return SimpleNamespace(
        auth_store=auth,
        registry=_make_registry(),
        content_dir=tmp_path,
        editor=load_editor_registry(_make_registry()),
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
# meta_page：全登记页解析（审计点 16：删 8 键写死 dict 后 12 页零 404）
# =============================================================================
def test_meta_all_registered_pages_resolve_fields(tmp_path: Path) -> None:
    """12 页全登记（六页 + npc/checkin/ai/hidden/env_event/log_card）→ 全 200 有 fields。

    module_file 去 .json → field_meta 表键：skills.json→skills、enemies.json→
    enemies（ai 共享宿主表）、settings.json→settings（env_event/log_card 段
    视图共享 settings 表——表键存在即可解析出字段；段级裁剪归批4 前端）。
    """
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    for pid in ("skill", "job", "monster", "map", "quest", "shop",
                "npc", "checkin", "ai", "hidden", "env_event", "log_card"):
        r = client.get(f"/api/meta/{pid}", headers=auth_h(token))
        assert r.status_code == 200, f"meta/{pid} 应 200：{r.text[:200]}"
        data = r.json()["data"]
        assert data["page"] == pid
        assert "fields" in data


def test_meta_unknown_page_404(tmp_path: Path) -> None:
    """未登记页（无装配 editor 且非六页兜底/表键）→ 404（现语义保持）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/meta/ghost_page", headers=auth_h(token))
    assert r.status_code == 404


def test_meta_page_kind_and_entry_type_passthrough(tmp_path: Path) -> None:
    """meta 响应透传 page_kind（登记值优先）+ entry_type（field_meta 表）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    # env_event 登记 page_kind=object → 透传 object（settings 表 entry_type=object）
    r = client.get("/api/meta/env_event", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["page_kind"] == "object"
    assert data["entry_type"] == "object"
    # log_card 登记 page_kind=view → 透传 view（表 entry_type=object 保留透传）
    r = client.get("/api/meta/log_card", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["page_kind"] == "view"
    assert data["entry_type"] == "object"
    # monster 未登记 page_kind → 缺省按 entry_type 推导 = list（现行为默认形态）
    r = client.get("/api/meta/monster", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["page_kind"] == "list"
    assert data["entry_type"] == "list"


def test_meta_editor_absent_falls_back_default_pages(tmp_path: Path) -> None:
    """state.editor=None（旧装配未跑注册表）→ 六页兜底语义仍解析（向后兼容）。"""
    from qbot_rpg.web.auth import AuthStore
    auth = AuthStore(owner_qq_id="owner1", gm_qq_ids={"gm1"})
    auth.setup_password("owner1", "pass1234")
    state = SimpleNamespace(
        auth_store=auth,
        registry=_make_registry(),
        content_dir=tmp_path,
        editor=None,  # 旧装配：未注入 editor
        permission_store=None,
        audit_store=None,
    )
    client = make_client(state)
    token = owner_token(client)
    for pid in ("skill", "monster", "quest"):
        r = client.get(f"/api/meta/{pid}", headers=auth_h(token))
        assert r.status_code == 200, f"meta/{pid} 应 200（兜底六页回退）"
        assert "fields" in r.json()["data"]
    # 未知页仍 404
    r = client.get("/api/meta/ghost_page", headers=auth_h(token))
    assert r.status_code == 404


# =============================================================================
# refs_target：统一别名表（审计点 17：删 12 键写死 dict，别名表单源覆盖）
# =============================================================================
def test_refs_alias_and_table_key_targets(tmp_path: Path) -> None:
    """refs target：别名（monster→enemies）+ 表键直查（settings/enemies/checkin）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    # 别名 monster → enemies 表（旧 12 键 dict 覆盖行为）
    r = client.get("/api/refs/monster", headers=auth_h(token))
    assert r.status_code == 200
    assert any(i["id"] == "gust_wolf" for i in r.json()["data"]["items"])
    # 表键直查：settings 表键在 field_meta 表（登记即直查，不需别名行）
    r = client.get("/api/refs/settings", headers=auth_h(token))
    assert r.status_code == 200
    assert any(i["id"] == "world" for i in r.json()["data"]["items"])
    # 表键直查：checkin（field_meta 已登记模块键，旧 dict 不含但仍可查）
    r = client.get("/api/refs/checkin", headers=auth_h(token))
    assert r.status_code == 200
    assert any(i["id"] == "c1" for i in r.json()["data"]["items"])


def test_refs_extended_aliases_all_kinds(tmp_path: Path) -> None:
    """别名表覆盖全部已登记 list 模块（含 D 类）：skill/effect/chain/dungeon 等。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    cases = {
        "skill": "slash",      # skill → skills
        "effect": "heal",      # effect → effects
        "status": "burn",      # status → statuses
        "mark": "m1",          # mark → marks
        "trait": "t1",         # trait → traits
        "action": "a1",        # action → action
        "recipe": "r1",        # recipe → recipe
        "equipment": "e1",     # equipment → equipment
        "slot": "s1",          # slot → slots
        "chain": "sc1",        # chain → skill_chains
        "dungeon": "d1",       # dungeon → dungeon（表键直查，C 类）
        "achievements": "ac1",  # achievements → achievements（表键直查，D 类）
    }
    for target, expected_id in cases.items():
        r = client.get(f"/api/refs/{target}", headers=auth_h(token))
        assert r.status_code == 200, f"refs/{target} 应 200"
        ids = [i["id"] for i in r.json()["data"]["items"]]
        assert expected_id in ids, f"refs/{target} 应含 {expected_id}"


def test_refs_unknown_target_empty_list(tmp_path: Path) -> None:
    """未知 target（非表键非别名）→ 200 空列表（端点不 404，现语义）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/refs/not_a_kind", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []


def test_refs_resolver_pure_function() -> None:
    """解析器纯函数：别名/表键/未知三分支（不经 HTTP，直测模块级函数）。"""
    table = default_field_meta_table()
    assert _refs_module_for_target("monster", table) == "enemies"
    assert _refs_module_for_target("enemy", table) == "enemies"
    assert _refs_module_for_target("skill", table) == "skills"
    assert _refs_module_for_target("chain", table) == "skill_chains"
    assert _refs_module_for_target("settings", table) == "settings"  # 表键直查
    assert _refs_module_for_target("dungeon", table) == "dungeon"  # 表键直查（C 类）
    assert _refs_module_for_target("not_a_kind", table) is None
    # 大写 target 小写归一
    assert _refs_module_for_target("Monster", table) == "enemies"


# =============================================================================
# /api/editor/pages：全字段透传（审计点 18：补 validator/id_prefix/group/page_kind）
# =============================================================================
def test_editor_pages_full_field_passthrough(tmp_path: Path) -> None:
    """/api/editor/pages 每页含 11 键：原 8 键 + validator + 扩展 3 字段。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/editor/pages", headers=auth_h(token))
    assert r.status_code == 200
    pages = r.json()["data"]["pages"]
    assert len(pages) == 12
    by_id = {p["page_id"]: p for p in pages}
    skill = by_id["skill"]
    for key in ("page_id", "title", "icon", "module_file", "meta_source",
                "tabs", "enabled", "extends", "validator", "id_prefix",
                "group", "page_kind"):
        assert key in skill, f"editor/pages 缺键 {key}"
    assert skill["validator"] == "skill"  # 审计点 18：validator 透传
    assert skill["id_prefix"] is None and skill["group"] is None
    assert skill["page_kind"] is None  # 未登记 → null
    # 登记值透传：env_event 组/形态 / log_card view
    env = by_id["env_event"]
    assert env["group"] == "世界" and env["page_kind"] == "object"
    card = by_id["log_card"]
    assert card["group"] == "世界" and card["page_kind"] == "view"
    mon = by_id["monster"]
    assert mon["extends"] is None and mon["validator"] == "monster"
    # ai extends 透传
    assert by_id["ai"]["extends"] == "monster"


def test_editor_pages_static_construction_passthrough(tmp_path: Path) -> None:
    """静态数据源场景：registry 直填 editor 行（含扩展字段）→ 端点透传全字段。

    说明：/api/editor/pages 恒从 state.registry 重建注册表（load_editor_registry），
    state.editor 注入仅供 meta_page 等消费——此处用 registry 直填 editor 模块
    模拟「静态/直构」数据源（等价 EditorPage 直构后落 registry）。
    """
    from qbot_rpg.web.auth import AuthStore
    auth = AuthStore(owner_qq_id="owner1", gm_qq_ids={"gm1"})
    auth.setup_password("owner1", "pass1234")
    static_registry = Registry(pack_id="static_pack", modules_raw={
        "editor": {"schema_version": 1, "pages": [
            {"page_id": "skill", "title": "技能", "module_file": "skills.json",
             "meta_source": "meta/skill", "validator": "skill",
             "id_prefix": "sk", "group": "战斗", "page_kind": "list"},
        ]},
        "skills": [{"id": "slash", "name": "脊斩"}],
    })
    state = SimpleNamespace(
        auth_store=auth,
        registry=static_registry,
        content_dir=tmp_path,
        editor=load_editor_registry(static_registry),
        permission_store=None,
        audit_store=None,
    )
    client = make_client(state)
    token = owner_token(client)
    r = client.get("/api/editor/pages", headers=auth_h(token))
    assert r.status_code == 200
    pages = r.json()["data"]["pages"]
    assert len(pages) == 1
    page = pages[0]
    assert page["id_prefix"] == "sk"
    assert page["group"] == "战斗"
    assert page["page_kind"] == "list"
    assert page["validator"] == "skill"
    # meta 端点按 module_file 解析：skills.json → skills 表键 → 200
    r = client.get("/api/meta/skill", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["page_kind"] == "list"
