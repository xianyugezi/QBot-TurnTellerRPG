"""M12.5 批2 路2C · /api/refs/{target} 引用芯片端点契约单测（引用控件后端契约完备）。

依据：docs/m125_启动包.md（批2 路2C：审计点 24——editor.html ref_target 仅渲染
提示文本未调 /api/refs/{target}，端点零使用；本路做后端契约完备 + 测试，前端
批4 才接）。契约（api.py refs_target docstring）：
  data.target = 请求原串（前端回显）
  data.kind   = target 归一后的 kind（小写原样，表键/别名键）
  data.items  = [{id, name}]（module 原始 list 顺序）
  data.total  = len(items)

覆盖：
  - field_meta ref_target 全集（递归扫描各模块 fields 的 ref_target 值，含
    element/children 嵌套）逐一请求 → 200 + items 数组 + total + kind 归一
  - 表键直查覆盖全部已登记模块（list 数据源即引用候选池）
  - 未知 kind → 200 空 items（total 0，不 404）
  - kind 大小写归一（Monster/SKILL 等大写串 → 小写解析，items 照常返回）

铁律：零 NoneBot import；纯 pytest；TestClient（starlette）；state 假装配
      （假 registry + 真 AuthStore + tmp_path content_dir）；无 emoji；
      ruff E501 零豁免（行宽 ≤100）；只读 field_meta（禁改动，并行隔离）。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from starlette.testclient import TestClient

from qbot_rpg.content.field_meta import default_field_meta_table
from qbot_rpg.content.registry import Registry
from qbot_rpg.web.api import create_app

# =============================================================================
# 假装配（state）：registry 带全模块元数据原始数据（引用候选池）
# =============================================================================
# field_meta 已登记模块键全集（引用芯片的候选池来源；模块数据按 kind 放行）
_ALL_MODULE_KEYS = (
    "achievements", "action", "ai", "checkin", "conditional", "dungeon", "editor",
    "effects", "enemies", "env_event", "equipment", "fishing", "forge", "formula",
    "hidden", "items", "jobs", "log_card", "manifest", "maps", "marks", "npc",
    "proficiency", "quest", "recipe", "settings", "shop", "skill_chains", "skills",
    "slots", "stats", "statuses", "traits",
)


def _collect_ref_targets(fmeta: object, acc: set[str]) -> None:
    """递归收集 FieldMeta 的 ref_target（含 element 嵌套与 obj children）。"""
    if fmeta is None:
        return
    rt = getattr(fmeta, "ref_target", None)
    if rt:
        acc.add(str(rt))
    _collect_ref_targets(getattr(fmeta, "element", None), acc)
    children = getattr(fmeta, "children", None)
    if children:
        for child in children.values():
            _collect_ref_targets(child, acc)


def ref_target_kinds() -> list[str]:
    """field_meta 全模块 fields 的 ref_target 值全集（排序，防顺序抖动）。"""
    table = default_field_meta_table()
    acc: set[str] = set()
    for mm in (getattr(table, "modules", None) or {}).values():
        for fmeta in (getattr(mm, "fields", None) or {}).values():
            _collect_ref_targets(fmeta, acc)
    return sorted(acc)


def _raw_for(key: str, *, as_list: bool) -> list[dict[str, str]] | dict[str, object]:
    """模块原始数据：list 模块 → 两条目 [{id, name}]；map/object → dict 形态。

    对齐真实内容包（stats/formula/settings 等 map/object 模块 modules_raw 为
    dict——refs 只收 list，此类模块本就不是引用候选池，items 恒空）。
    """
    if not as_list:
        return {"_meta": {"note": f"{key} map/object 形态"}}
    return [{"id": f"{key}_1", "name": f"{key} 名1"},
            {"id": f"{key}_2", "name": f"{key} 名2"}]


# field_meta 中 entry_type=list 的模块键（引用候选池来源；map/object 非池）
_LIST_MODULE_KEYS = (
    "achievements", "action", "ai", "checkin", "dungeon", "effects", "enemies",
    "equipment", "hidden", "items", "jobs", "maps", "marks", "npc", "proficiency",
    "quest", "recipe", "shop", "skill_chains", "skills", "slots", "statuses",
    "traits",
)


def _make_registry() -> Registry:
    """假 registry：modules_raw 覆盖 field_meta 全部表键（每模块 2 条目）。"""
    raw: dict[str, object] = {}
    for key in _ALL_MODULE_KEYS:
        raw[key] = _raw_for(key, as_list=key in _LIST_MODULE_KEYS)
    return Registry(pack_id="test_pack", generation=1, tables={}, names={},
                    modules_raw=raw)


def make_state(tmp_path: Path) -> SimpleNamespace:
    """state：真 AuthStore + 假 registry（全表键模块原始数据）+ tmp content_dir。"""
    from qbot_rpg.web.auth import AuthStore
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
# refs_target：契约字段 + ref_target 全集覆盖 + 未知 kind + 大小写归一
# =============================================================================
def test_refs_contract_shape(tmp_path: Path) -> None:
    """契约四键：target 原串回显 + kind 小写归一 + items 数组 + total 一致。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/refs/enemies", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["target"] == "enemies"          # 请求原串回显
    assert data["kind"] == "enemies"            # 表键直查 → 归一 kind = 表键
    assert isinstance(data["items"], list)
    assert data["total"] == len(data["items"])  # total = items 长度
    assert data["total"] == 2
    ids = [i["id"] for i in data["items"]]
    assert "enemies_1" in ids and "enemies_2" in ids
    for i in data["items"]:
        assert "id" in i and "name" in i       # items 条目含 id/name 稳定键


def test_refs_all_ref_target_kinds_resolve(tmp_path: Path) -> None:
    """field_meta ref_target 全集逐一请求 → 200 + items 数组 + total 整数。

    ref_target 值即"语义 kind"（别名表键或表键）：表键直查命中或别名行
    命中均须解析到模块原始数据（宁全勿漏——审计点 24 引用控件渲染依赖）。
    """
    kinds = ref_target_kinds()
    assert kinds, "ref_target 全集不应为空（field_meta 有 ref 字段）"
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    for kind in kinds:
        r = client.get(f"/api/refs/{kind}", headers=auth_h(token))
        assert r.status_code == 200, f"refs/{kind} 应 200：{r.text[:200]}"
        data = r.json()["data"]
        assert data["kind"] == kind, f"refs/{kind} kind 应归一为 {kind}"
        assert isinstance(data["items"], list), f"refs/{kind} items 应为数组"
        assert isinstance(data["total"], int), f"refs/{kind} total 应为整数"
        assert data["total"] == len(data["items"])
        assert data["total"] >= 1, f"refs/{kind} 应解析到候选（宁全勿漏）"


def test_refs_all_table_keys_resolve(tmp_path: Path) -> None:
    """field_meta 全部已登记模块键直查：list 模块 → 200 有候选；map/object 不 404。

    map/object 形态模块（stats/formula/settings 等）表键可解析但原始数据非
    list → items 空（引用控件候选池只面向 list 条目；空态语义见
    test_refs_unknown_kind_empty_200）。
    """
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    for key in _LIST_MODULE_KEYS:
        r = client.get(f"/api/refs/{key}", headers=auth_h(token))
        assert r.status_code == 200, f"refs/{key} 应 200（表键直查）"
        data = r.json()["data"]
        assert data["kind"] == key
        assert data["total"] == len(data["items"]) == 2
    for key in set(_ALL_MODULE_KEYS) - set(_LIST_MODULE_KEYS):
        r = client.get(f"/api/refs/{key}", headers=auth_h(token))
        assert r.status_code == 200, f"refs/{key} 应 200（map/object 表键可解析）"
        assert r.json()["data"]["total"] == 0


def test_refs_unknown_kind_empty_200(tmp_path: Path) -> None:
    """未知 kind → 200 + 空 items + total 0（不 404，前端引用控件空态）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/refs/not_a_kind", headers=auth_h(token))
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["items"] == []
    assert data["total"] == 0
    assert data["kind"] == "not_a_kind"
    # 表键解析命中但模块原始数据非 list（stats map 表）→ 空 items 不 404
    r = client.get("/api/refs/stats", headers=auth_h(token))
    assert r.status_code == 200
    assert r.json()["data"]["items"] == []
    assert r.json()["data"]["total"] == 0


def test_refs_kind_case_normalized(tmp_path: Path) -> None:
    """大小写归一：大写/混合大小写 target → 小写解析（表键/别名键均生效）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    cases = [
        ("Enemies", "enemies"),     # 表键大写
        ("MONSTER", "monster"),     # 别名键大写（monster → enemies 表）
        ("Skill", "skill"),         # 别名键混合大小写
        ("Skill_Or_Any", "skill_or_any"),  # 宽松 kind 混合大小写
    ]
    for target, kind in cases:
        r = client.get(f"/api/refs/{target}", headers=auth_h(token))
        assert r.status_code == 200, f"refs/{target} 应 200"
        data = r.json()["data"]
        assert data["kind"] == kind, f"refs/{target} kind 应归一 {kind}"
        assert data["items"], f"refs/{target} 大小写归一后应命中候选"
        assert data["total"] == len(data["items"]) >= 1


def test_refs_items_id_name_stable_keys(tmp_path: Path) -> None:
    """items 条目契约：id/name 字符串键存在（引用控件渲染所需稳定键）。"""
    client = make_client(make_state(tmp_path))
    token = owner_token(client)
    r = client.get("/api/refs/items", headers=auth_h(token))
    assert r.status_code == 200
    items = r.json()["data"]["items"]
    assert items, "items 表应有候选"
    assert set(items[0].keys()) == {"id", "name"}, "条目键应恰为 id/name"
