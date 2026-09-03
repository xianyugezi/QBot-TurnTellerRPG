"""Web 编辑器外壳 API（M12 批3 路3C · 15 端点总装）。

职责（细化_3a D-05 / §2.1 + 细化_5a §6）：FastAPI 编辑器外壳——读写 content 包
（原子写盘+热重载）、认证会话、六页 CRUD+校验、数据包管理。依赖方向
web → {content, core, storage, data}，任何层不得反向依赖 web；零 NoneBot import。

15 端点（细化_5a §6.1-6.4）：
  - 认证 4：POST /api/auth/setup|login|logout、GET /api/auth/me（L160-163）
  - 元数据引用 2：GET /api/meta/{page}、GET /api/refs/{target}（§6.2）
  - 六页 CRUD+校验 6：GET/POST /api/pages/{page}、GET/PUT/DELETE
    /api/pages/{page}/{id}、POST /api/pages/{page}/validate（§6.3 L176-181）
  - 热重载+数据包 3：POST /api/reload、GET /api/packs、PUT /api/packs/active（§6.4）

统一响应包络（L183）：{ok: true, data} / {ok: false, errors: [...]}。

【工程补白 · 显式标注】
  1) fastapi 惰性 import（既有模式）：requirements 已加 fastapi/uvicorn；
     缺 fastapi 时 create_app 抛可读错误（核心层测试不触碰 web 路由）。
  2) state 注入：create_app(state) 携带 {registry, auth_store, content_dir,
     editor, permission_store, audit_store}；缺省 → 503 编辑器未装配。
  3) 写端点流程（SV-06/07）：pages_crud 产出变更 → atomic_store 原子写盘 →
     reload 校验；校验红拦不阻断保存（SV-02），返回 warnings。
  4) 认证：除 /api/auth/setup 与 /api/auth/login 外全部要求 Bearer token。
  5) >50ms 操作（文件 IO）应 asyncio.to_thread——当前端点同步实现，宿主
     uvicorn 单 worker 下文件 IO 量小可接受；大包写盘批 5 优化。

铁律：零 NoneBot import；web → content/core/storage/data 正向依赖；全中文注释。
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, MutableMapping, Optional

try:  # M12 运行时依赖（requirements 已加 fastapi/uvicorn）；缺失降级占位
    from fastapi import APIRouter, FastAPI, Header, HTTPException
    _HAS_FASTAPI = True
except ImportError:  # pragma: no cover - 核心层测试不触碰 web 路由
    FastAPI = None  # type: ignore
    APIRouter = None  # type: ignore
    Header = None  # type: ignore
    HTTPException = None  # type: ignore
    _HAS_FASTAPI = False

# 类型收窄：装饰器函数内 raise HTTPException 时它可能 None（惰性 import）。
# 统一别名标注 Any（create_app 已先判 _HAS_FASTAPI，运行期恒非 None）。
_HTTPException: Any = HTTPException
_Header: Any = Header

__all__ = ["create_app", "iter_routes", "FastAPI", "APIRouter"]

# =============================================================================
# M12.5 批1 路1B：/api/refs/{target} 引用候选别名表（审计点 17 单源；m125_启动包
# §2.1「refs 候选覆盖全部 kind」）。target 字符串小写 → 模块键（field_meta 表键 /
# Registry.modules_raw 键，二者同键——loader 按模块文件去 .json 登记同名键）。
# 解析优先：field_meta 表键命中直查（含全部已登记 list/obj 模块）→ 未命中走本
# 别名表（注册表 kind 或前端 ref_target 常见叫法：enemy→enemies、chain→
# skill_chains 等）；仍无 → None（调用方 404/空列表）。
# =============================================================================
REFS_TARGET_ALIASES: Dict[str, str] = {
    # 语义 kind（field_meta ref_target 全部集合 9 种，见下方组注释）
    "monster": "enemies",   # 前端/页面页名 monster → enemies 表
    "enemy": "enemies",
    "item": "items",
    "skill": "skills",
    # skill_or_any：宽松引用 kind（validator R-4 兼容：命中任一注册 kind 即通过）。
    # 归一为"任一技能/行动库" —— refs 候选语义最接近 skills 表（skill 字段无歧义时
    # 直查 skills 已覆盖；本行兜底保证 ref_target 全集可解析、宁全勿漏）
    "skill_or_any": "skills",
    "job": "jobs",
    "map": "maps",
    "quest": "quest",
    "shop": "shop",
    "npc": "npc",
    "effect": "effects",
    "status": "statuses",
    "mark": "marks",
    "trait": "traits",
    "action": "action",
    "recipe": "recipe",
    "equipment": "equipment",
    "slot": "slots",
    "chain": "skill_chains",
}


def _refs_module_for_target(target: str, table: Any) -> Optional[str]:
    """/api/refs/{target} target → 模块键解析（审计点 17 统一解析器）。

    口径：target 小写 → ①field_meta 表键命中直查（表键即模块键，含全部已登记
    list 模块与 C/D 类扩展）；②未命中 → REFS_TARGET_ALIASES 别名表 → 模块键；
    ③仍无 → None（调用方 404/空列表）。表对象惰性传入（fastapi 惰性 import，
    表构造可能昂贵——只在确实需要时由调用方构建）。
    """
    key = str(target).lower()
    if table is not None and getattr(table, "modules", None) is not None:
        if key in table.modules:
            return key
    return REFS_TARGET_ALIASES.get(key)


def _require_state(state: Any, name: str) -> Any:
    """取装配件；缺失抛 HTTPException 503（编辑器未装配）。"""
    if state is None or not hasattr(state, name) or getattr(state, name) is None:
        raise _HTTPException(
            status_code=503, detail={"ok": False, "errors": [{
                "level": "red", "code": "not_assembled",
                "message": f"编辑器未装配（{name} 缺失）"}]})
    return getattr(state, name)


def _bearer_token(authorization: Optional[str]) -> Optional[str]:
    """Authorization: Bearer <token> → token（缺/格式错 → None）。"""
    if not authorization:
        return None
    parts = str(authorization).split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return None


def _require_auth(state: Any, authorization: Optional[str]) -> Dict[str, Any]:
    """认证依赖：token → me 信息；未认证 401。"""
    auth = _require_state(state, "auth_store")
    token = _bearer_token(authorization)
    if not token:
        raise _HTTPException(
            status_code=401, detail={"ok": False, "errors": [{
                "level": "red", "code": "unauthorized",
                "message": "未认证（需要 Authorization: Bearer <token>）"}]})
    me = auth.me(token)
    if not me.get("ok"):
        raise _HTTPException(
            status_code=401, detail={"ok": False, "errors": [{
                "level": "red", "code": "unauthorized",
                "message": str(me.get("reason") or "登录已失效")}]})
    return me


def _me_to_user(me: Mapping[str, Any]) -> Dict[str, Any]:
    """me 信息 → 用户视图。"""
    return {
        "qq_id": str(me.get("owner_id") or ""),
        "role": str(me.get("role") or "player"),
    }


def _ctx_of(state: Any) -> MutableMapping[str, Any]:
    """CRUD ctx（modules_raw + _page_versions 长活版本簿挂 state）。"""
    reg = _require_state(state, "registry")
    if not hasattr(state, "_page_versions"):
        state._page_versions = {}
    return {
        "modules_raw": reg.modules_raw,
        "_page_versions": state._page_versions,
    }


def _save_pipeline(
    state: Any,
    page: str,
    new_item: Mapping[str, Any],
    item_id: Optional[str] = None,
    *,
    create: bool = False,
    base_version: Optional[int] = None,
) -> Dict[str, Any]:
    """CRUD 写端点统一流水线：pages_crud 变更 → atomic_store 原子写盘。"""
    reg = _require_state(state, "registry")
    content_dir = _require_state(state, "content_dir")
    from qbot_rpg.content import atomic_store
    from qbot_rpg.web import pages_crud

    ctx = _ctx_of(state)
    module = pages_crud.PAGE_MODULE.get(page)
    if module is None:
        return {"ok": False, "errors": [{
            "level": "red", "code": "not_found", "field": "page",
            "message": f"页面不存在：{page}"}]}
    if create:
        res = pages_crud.create_page_item(page, new_item, ctx)
    else:
        res = pages_crud.update_page_item(page, item_id or "", new_item,
                                          base_version, ctx)
    if not res.get("ok"):
        errs = res.get("errors") or []
        if res.get("code") == 409:
            return {"ok": False, "code": 409, "errors": errs}
        return {"ok": False, "errors": errs}
    item = res["item"]
    # 变更应用：替换同 id + 追加（写盘层）
    entries = [e for e in (reg.modules_raw.get(module) or [])
               if not (isinstance(e, Mapping)
                       and str(e.get("id") or "") == str(item.get("id") or ""))]
    entries.append(dict(item))
    wr = atomic_store.write_modules(content_dir, {module: entries})
    if not wr.get("ok"):
        return {"ok": False, "errors": wr.get("errors") or [{
            "level": "red", "code": "write_failed", "message": "写盘失败"}]}
    return {"ok": True, "data": {"item": item, "saved": True}}


def create_app(state: Optional[Any] = None) -> Any:
    """M12 实装：构造 FastAPI 应用（15 端点；D-05 编辑器外壳）。

    state：装配件容器（见模块头 state 键说明）。缺 fastapi → RuntimeError。
    """
    if not _HAS_FASTAPI or FastAPI is None or APIRouter is None:
        raise RuntimeError(
            "fastapi 未安装（M12 编辑器运行时依赖：.venv/bin/python -m pip "
            "install 'fastapi>=0.115' 'uvicorn>=0.34'）")
    app = FastAPI(title="QBot RPG 内容编辑器", docs_url=None, redoc_url=None)
    router = APIRouter(prefix="/api")

    # ---- 前端壳（M12 批4 路4B：/ → editor.html 单文件最小可用壳）----
    from pathlib import Path as _Path

    _EDITOR_HTML = _Path(__file__).parent / "static" / "editor.html"

    @app.get("/", include_in_schema=False)
    def editor_root() -> Any:
        """编辑器首页（单文件 HTML 壳）。"""
        if _EDITOR_HTML.exists():
            from fastapi.responses import FileResponse
            return FileResponse(str(_EDITOR_HTML))
        return {"ok": False, "errors": [{
            "level": "red", "code": "not_found",
            "message": "editor.html 缺失（web/static/editor.html）"}]}

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> Dict[str, Any]:
        """健康检查（宿主拉起后探测用）。"""
        return {"ok": True, "service": "qbot-editor"}

    # ---- 认证 4（§6.1）----
    @router.post("/auth/setup")
    def auth_setup(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """首次设密（仅未设置可用；弱密码 400；已设置 409）。"""
        auth = _require_state(state, "auth_store")
        owner = str((body or {}).get("qq_id") or "")
        password = str((body or {}).get("password") or "")
        if not owner or not password:
            raise _HTTPException(status_code=400, detail={"ok": False, "errors": [{
                "level": "red", "code": "missing_field",
                "message": "qq_id 与 password 必填"}]})
        r = auth.setup_password(owner, password)
        if not r.get("ok"):
            reason = str(r.get("reason") or "")
            code = 409 if reason == "already_set" else 400
            raise _HTTPException(status_code=code, detail={"ok": False, "errors": [{
                "level": "red", "code": reason,
                "message": str(r.get("message") or "设置失败")}]})
        return {"ok": True, "data": {"message": "密码已设置"}}

    @router.post("/auth/login")
    def auth_login(body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """登录（token + 过期）；失败计数 5 次锁 15 分钟（423）。"""
        auth = _require_state(state, "auth_store")
        owner = str((body or {}).get("qq_id") or "")
        password = str((body or {}).get("password") or "")
        r = auth.login(owner, password)
        if not r.get("ok"):
            reason = str(r.get("reason") or "")
            # not_setup：428（前端识别后自动转 setup 引导；区别于密码错 401）
            code = 428 if reason == "not_setup" else (423 if reason == "locked" else 401)
            detail: Dict[str, Any] = {"ok": False, "errors": [{
                "level": "red", "code": reason,
                "message": str(r.get("message") or "登录失败")}]}
            if r.get("lock_until"):
                detail["lock_until"] = r["lock_until"]
            raise _HTTPException(status_code=code, detail=detail)
        return {"ok": True, "data": {"token": r["token"],
                                     "expires_at": r.get("expires_at")}}

    @router.post("/auth/logout")
    def auth_logout(authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """登出（token 失效；幂等 200）。"""
        auth = _require_state(state, "auth_store")
        token = _bearer_token(authorization) or ""
        auth.logout(token)
        return {"ok": True, "data": {"message": "已登出"}}

    @router.get("/auth/me")
    def auth_me(authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """当前会话（机主/GM 身份）；未认证 401。"""
        me = _require_auth(state, authorization)
        return {"ok": True, "data": {"user": _me_to_user(me)}}

    # ---- 元数据引用 2（§6.2）----
    @router.get("/meta/{page}")
    def meta_page(page: str) -> Dict[str, Any]:
        """该页字段元数据（表单渲染源，P-07 唯一数据源）。"""
        editor = getattr(state, "editor", None)
        meta_src: Optional[str] = None
        page_kind: Optional[str] = None
        ep = None
        if editor is not None and hasattr(editor, "get_page"):
            ep = editor.get_page(page)
            if ep is not None:
                meta_src = ep.meta_source
                # M12.5 路1B：page_kind 透传（editor.json 登记值；缺省 None =
                # 上层按 field_meta entry_type / extends 宿主推导）
                page_kind = getattr(ep, "page_kind", None)
        from qbot_rpg.content.field_meta import default_field_meta_table
        table = default_field_meta_table()
        # M12.5 路1B：删写死 8 键 dict（审计点 16）——editor.json 登记页的
        # module_file 去 .json 后缀 = field_meta 表键（loader 同口径登记），
        # 如 npc.json→npc / skills.json→skills / settings.json→settings；
        # 页未登记（editor 无该页/未装配）→ 回退别名表解析（skill→skills、
        # monster→enemies 等）；表查无 → 404（保持现语义）
        module = ""
        if ep is not None:
            module = str(getattr(ep, "module_file", "") or "").removesuffix(".json")
        if not module:
            module = _refs_module_for_target(page, table) or ""
        mm = table.modules.get(module) if module else None
        if mm is None:
            raise _HTTPException(status_code=404, detail={"ok": False, "errors": [{
                "level": "red", "code": "not_found", "field": "page",
                "message": f"页面不存在：{page}"}]})
        fields = []
        for fname, fmeta in (mm.fields or {}).items():
            fields.append({
                "name": fname,
                "type": fmeta.type,
                "label": getattr(fmeta, "label", "") or fname,
                "required": fmeta.required,
                "ref_target": fmeta.ref_target,
                "enum": list(fmeta.enum or ()),
            })
        # page_kind 透传：显式登记值优先；缺省 None → 按 field_meta entry_type
        # 推导（entry_type=list|object|map）。meta 响应 data 增 page_kind/
        # entry_type 供前端批4 特化渲染分支使用；缺省 list（现行为默认形态）。
        eff_kind = page_kind or mm.entry_type or "list"
        return {"ok": True, "data": {"page": page, "meta_source": meta_src,
                                     "page_kind": eff_kind,
                                     "entry_type": mm.entry_type or "list",
                                     "fields": fields}}

    @router.get("/refs/{target}")
    def refs_target(target: str) -> Dict[str, Any]:
        """引用控件候选列表（动态 enum；target ∈ 怪物/物品/技能/职业/...）。

        契约（M12.5 批2 路2C 审计点 24：前端表单 ref_target → 引用控件）：
          data.target = 请求原串（前端回显）
          data.kind   = target 归一后的 kind（表键/别名键原样小写；表键直查命中
                        = 表键本身，别名命中 = 别名键，即 field_meta ref_target 全集）
          data.items  = [{id, name}]（module 原始 list 顺序）
          data.total  = len(items)
        """
        reg = _require_state(state, "registry")
        # M12.5 路1B：删写死 12 键 dict（审计点 17）——统一别名表解析：
        # field_meta 表键命中直查（含 C/D 类已登记 list 模块）→ 未命中走
        # REFS_TARGET_ALIASES 别名表（单源，模块级常量）
        from qbot_rpg.content.field_meta import default_field_meta_table
        module = _refs_module_for_target(target, default_field_meta_table())
        data = reg.modules_raw.get(module) if (module and hasattr(reg, "modules_raw")) else None
        items = []
        if isinstance(data, list):
            for e in data:
                if isinstance(e, Mapping):
                    items.append({"id": str(e.get("id") or ""),
                                  "name": str(e.get("name") or "")})
        return {"ok": True, "data": {"target": target,
                                     "kind": str(target).lower(),
                                     "items": items,
                                     "total": len(items)}}

    @router.get("/editor/pages")
    def editor_pages() -> Dict[str, Any]:
        """编辑器页清单（前端侧边栏数据源；editor_registry 页表，含启停语义）。"""
        reg = _require_state(state, "registry")
        from qbot_rpg.content.editor_registry import load_editor_registry
        editor = load_editor_registry(reg)
        pages = []
        for p in editor.pages:
            pages.append({
                "page_id": p.page_id,
                "title": p.title,
                "icon": p.icon,
                "module_file": p.module_file,
                "meta_source": p.meta_source,
                "tabs": list(p.tabs or ()),
                "enabled": bool(p.enabled),
                "extends": p.extends,
                # M12.5 路1B：透传 EditorPage 全字段（审计点 18 漏 validator 修复
                # + 扩展三字段）——id_prefix/group/page_kind 缺省 None（既有内容包
                # editor.json 未登记 → null，前端按缺省语义处理）
                "validator": p.validator,
                "id_prefix": p.id_prefix,
                "group": p.group,
                "page_kind": p.page_kind,
            })
        return {"ok": True, "data": {"pages": pages}}

    # ---- M12.5 批3 路3B：钓鱼 obj 页专属端点（复用 fishing_editor_service
    #      纯函数层，零写盘——编辑写盘仍走 obj 页 CRUD/原始 JSON）----
    @router.get("/editor/fishing/schema")
    def fishing_schema(authorization: str = _Header(default=None)) -> Dict[str, Any]:
        """钓鱼卡片表单 schema（settings.fishing 九键字段定义，T19 服务层）。"""
        _require_auth(state, authorization)
        from qbot_rpg.editor.fishing_editor_service import fish_card_schema
        return {"ok": True, "data": {"schema": fish_card_schema()}}

    @router.post("/editor/fishing/csv/validate")
    def fishing_csv_validate(body: Optional[Dict[str, Any]] = None,
                             authorization: str = _Header(default=None)) -> Dict[str, Any]:
        """鱼种 CSV 导入预检（解析 + 逐行聚合 {ok,rows,errors,warnings}）。"""
        _require_auth(state, authorization)
        from qbot_rpg.editor.fishing_editor_service import (
            fish_csv_import, fish_csv_validate as _csv_validate,
        )
        text = str((body or {}).get("text") or "")
        try:
            rows = fish_csv_import(text)
        except Exception as exc:  # noqa: BLE001 - 解析异常聚合为错误返回
            return {"ok": False, "errors": [{
                "level": "red", "code": "csv_parse_error",
                "message": f"CSV 解析失败：{exc}"}]}
        out = _csv_validate(rows)
        return {"ok": True, "data": {
            "rows": rows, "errors": out.get("errors", []),
            "warnings": out.get("warnings", []),
            "total": len(rows)}}

    @router.get("/editor/fishing/crown_preview")
    def fishing_crown_preview(size: float = 50, weight: float = 50,
                              authorization: str = _Header(default=None)) -> Dict[str, Any]:
        """冠级阈值滑条预览（百分位 → 档位 + 中文标签）。"""
        _require_auth(state, authorization)
        from qbot_rpg.editor.fishing_editor_service import crown_preview
        return {"ok": True, "data": crown_preview(size, weight)}

    @router.post("/editor/fishing/simulate")
    def fishing_simulate(body: Optional[Dict[str, Any]] = None,
                         authorization: str = _Header(default=None)) -> Dict[str, Any]:
        """图鉴模拟（种子化确定性：species 池 n 次捕捞 → 冠级分布）。"""
        _require_auth(state, authorization)
        from qbot_rpg.editor.fishing_editor_service import simulate_catches
        b = body or {}
        species = b.get("species")
        if not isinstance(species, list):
            raise _HTTPException(status_code=422, detail={"ok": False, "errors": [{
                "level": "red", "code": "missing_field", "field": "species",
                "message": "species 必填（鱼种对象数组）"}]})
        n = int(b.get("n") or 100)
        seed = b.get("seed", 42)
        return {"ok": True, "data": simulate_catches(species, n, seed=seed)}

    # ---- 六页 CRUD+校验 6（§6.3）----
    # ---- M12.5 批4：obj/map 形态读写（settings/forge/fishing 整对象 +
    #      stats/formula 键值表）----
    @router.get("/pages/{page}/whole")
    def pages_whole_get(page: str,
                        authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """obj/map 页整模块读取（data = 顶层 obj dict / map dict）。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.web import pages_crud
        ctx = {"modules_raw": reg.modules_raw}
        out = pages_crud.get_whole_module(page, ctx)
        if not out.get("ok"):
            raise _HTTPException(status_code=404, detail=out)
        return {"ok": True, "data": out}

    @router.put("/pages/{page}/whole")
    def pages_whole_put(page: str, body: Optional[Dict[str, Any]] = None,
                        authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """obj/map 页整模块保存（顶层 dict 覆盖合并 + 原子写盘）。"""
        _require_auth(state, authorization)
        content_dir = _require_state(state, "content_dir")
        from qbot_rpg.content import atomic_store
        from qbot_rpg.web import pages_crud
        ctx = _ctx_of(state)
        out = pages_crud.update_whole_module(page, dict(body or {}), ctx)
        if not out.get("ok"):
            code = out.get("code") or 422
            raise _HTTPException(status_code=code, detail=out)
        module = out["module"]
        wr = atomic_store.write_modules(content_dir, {module: out["data"]})
        if not wr.get("ok"):
            raise _HTTPException(status_code=500, detail=wr)
        return {"ok": True, "data": out}

    @router.get("/pages/{page}/map/{key}")
    def pages_map_get(page: str, key: str,
                      authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """map 页单键读取（stats/formula 键 → 值）。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.web import pages_crud
        ctx = {"modules_raw": reg.modules_raw}
        out = pages_crud.get_map_key(page, key, ctx)
        if not out.get("ok"):
            code = out.get("code") or 404
            raise _HTTPException(status_code=code, detail=out)
        return {"ok": True, "data": out}

    @router.put("/pages/{page}/map/{key}")
    def pages_map_put(page: str, key: str, body: Optional[Dict[str, Any]] = None,
                      authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """map 页单键写入（新建/覆盖 + 原子写盘）。"""
        _require_auth(state, authorization)
        content_dir = _require_state(state, "content_dir")
        from qbot_rpg.content import atomic_store
        from qbot_rpg.web import pages_crud
        ctx = _ctx_of(state)
        value = (body or {}).get("value")
        out = pages_crud.put_map_key(page, key, value, ctx)
        if not out.get("ok"):
            code = out.get("code") or 422
            raise _HTTPException(status_code=code, detail=out)
        module = out["module"]
        wr = atomic_store.write_modules(content_dir, {module: ctx["modules_raw"][module]})
        if not wr.get("ok"):
            raise _HTTPException(status_code=500, detail=wr)
        return {"ok": True, "data": out}

    @router.delete("/pages/{page}/map/{key}")
    def pages_map_delete(page: str, key: str,
                         authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """map 页单键删除 + 原子写盘。"""
        _require_auth(state, authorization)
        content_dir = _require_state(state, "content_dir")
        from qbot_rpg.content import atomic_store
        from qbot_rpg.web import pages_crud
        ctx = _ctx_of(state)
        out = pages_crud.delete_map_key(page, key, ctx)
        if not out.get("ok"):
            code = out.get("code") or 404
            raise _HTTPException(status_code=code, detail=out)
        module = pages_crud._page_info(ctx, page)["module"]
        wr = atomic_store.write_modules(content_dir, {module: ctx["modules_raw"][module]})
        if not wr.get("ok"):
            raise _HTTPException(status_code=500, detail=wr)
        return {"ok": True, "data": out}

    @router.get("/pages/{page}")
    def pages_list(page: str, page_no: int = 1, size: int = 50,
                   q: str = "", sort: str = "",
                   authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """列表：分页/搜索/排序。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.web import pages_crud
        ctx = {"modules_raw": reg.modules_raw}
        out = pages_crud.list_page_items(page, ctx, page_no=page_no,
                                         size=size, q=q, sort=sort)
        if not out.get("ok"):
            raise _HTTPException(status_code=404, detail=out)
        return {"ok": True, "data": out}

    @router.get("/pages/{page}/{item_id}")
    def pages_get(page: str, item_id: str,
                  authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """单条详情（含引用中文名）。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.web import pages_crud
        ctx = {"modules_raw": reg.modules_raw}
        out = pages_crud.get_page_item(page, item_id, ctx)
        if not out.get("ok"):
            raise _HTTPException(status_code=404, detail=out)
        return {"ok": True, "data": out}

    @router.post("/pages/{page}")
    def pages_create(page: str, body: Optional[Dict[str, Any]] = None,
                     authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """新建（ID 自动生成 类型_序号）。"""
        _require_auth(state, authorization)
        out = _save_pipeline(state, page, dict(body or {}), create=True)
        if not out.get("ok"):
            code = out.get("code") or 422
            raise _HTTPException(status_code=code, detail=out)
        return {"ok": True, "data": out.get("data", {})}

    @router.put("/pages/{page}/{item_id}")
    def pages_update(page: str, item_id: str, body: Optional[Dict[str, Any]] = None,
                     authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """更新（base_version 冲突 409）。"""
        _require_auth(state, authorization)
        bv = (body or {}).get("base_version")
        out = _save_pipeline(state, page, dict(body or {}), item_id=item_id,
                             base_version=bv)
        if not out.get("ok"):
            code = out.get("code") or 422
            raise _HTTPException(status_code=code, detail=out)
        return {"ok": True, "data": out.get("data", {})}

    @router.delete("/pages/{page}/{item_id}")
    def pages_delete(page: str, item_id: str,
                     authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """删除（级联清理）。"""
        _require_auth(state, authorization)
        content_dir = _require_state(state, "content_dir")
        from qbot_rpg.content import atomic_store
        from qbot_rpg.web import pages_crud
        ctx = _ctx_of(state)
        del_res = pages_crud.delete_page_item(page, item_id, ctx)
        if not del_res.get("ok"):
            raise _HTTPException(status_code=404, detail=del_res)
        apply_res = pages_crud.apply_delete_to_entries(page, item_id, ctx)
        if not apply_res.get("ok"):
            raise _HTTPException(status_code=404, detail=apply_res)
        # 级联模块（maps/dungeon 等被 delete_page_item 原地改过）→ 一起原子写盘
        # （UI 检查修复 2026-09-03：原实现只写当前模块 → 删怪物后 maps 残留悬空
        # 引用 → 内容包重载红拦阻断）
        module_files: Dict[str, Any] = {apply_res["module"]: apply_res["entries"]}
        for c in del_res.get("cascades", []):
            cm = c.get("module")
            if cm and cm != apply_res["module"] and cm not in module_files:
                raw_list = ctx.get("modules_raw", {}).get(cm)
                if isinstance(raw_list, list):
                    module_files[cm] = raw_list
        wr = atomic_store.write_modules(content_dir, module_files)
        if not wr.get("ok"):
            return {"ok": False, "errors": wr.get("errors") or [{
                "level": "red", "code": "write_failed", "message": "写盘失败"}]}
        return {"ok": True, "data": {"id": item_id,
                                     "cascades": del_res.get("cascades", [])}}

    @router.post("/pages/{page}/validate")
    def pages_validate(page: str, body: Optional[Dict[str, Any]] = None,
                       authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """草稿校验：红/黄清单（不落盘，200）。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.web import pages_crud
        ctx = {"modules_raw": reg.modules_raw}
        out = pages_crud.validate_page_item(page, dict(body or {}), ctx)
        if not out.get("ok"):
            raise _HTTPException(status_code=404, detail=out)
        return {"ok": True, "data": {"red": out.get("red", []),
                                     "yellow": out.get("yellow", [])}}

    # ---- 热重载 + 数据包 3（§6.4）----
    @router.post("/reload")
    def api_reload(authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """手动热重载（对应 QQ /重载）；成功换新/失败回退旧快照。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        from qbot_rpg.content import atomic_store
        try:
            out = atomic_store.reload_and_rollback(reg, reg.modules_raw)
        except Exception as exc:  # noqa: BLE001 - 重载异常不崩
            return {"ok": False, "errors": [{
                "level": "red", "code": "reload_failed",
                "message": f"热重载异常：{exc}"}]}
        return {"ok": bool(getattr(out, "ok", False)),
                "data": {"generation": getattr(reg, "generation", None),
                         "restored": bool(getattr(out, "restored", False)),
                         "note": getattr(out, "note", "")}}

    @router.get("/packs")
    def packs_list(authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """数据包管理：全部内容包 + 启用状态。"""
        _require_auth(state, authorization)
        reg = _require_state(state, "registry")
        info = {
            # pack_id 在 Registry.pack_id（目录名）；manifest 只含 name/version——
            # UI 检查修复 2026-09-03：原读 manifest.pack_id 恒 null
            "pack_id": getattr(reg, "pack_id", None) or "",
            "version": getattr(reg.manifest, "version", None) if reg.manifest else None,
            "name": getattr(reg.manifest, "name", None) if reg.manifest else None,
        }
        return {"ok": True, "data": {"active": info,
                                     "generation": getattr(reg, "generation", None)}}

    @router.put("/packs/active")
    def packs_active(body: Optional[Dict[str, Any]] = None,
                     authorization: Optional[str] = _Header(default=None)) -> Dict[str, Any]:
        """切换启用数据包（插件只能启用一个；切换即时生效——装配层职责，占位）。"""
        _require_auth(state, authorization)
        pack_id = str((body or {}).get("pack_id") or "")
        if not pack_id:
            raise _HTTPException(status_code=422, detail={"ok": False, "errors": [{
                "level": "red", "code": "missing_field", "field": "pack_id",
                "message": "pack_id 必填"}]})
        return {"ok": True, "data": {"requested_pack": pack_id,
                                     "note": "切换由宿主装配层执行（批 5）"}}

    app.include_router(router)
    return app


def iter_routes(app: Any) -> Any:
    """M12 实装：遍历注册路由（供插件入口拉起子进程后健康检查/日志）。"""
    routes = []
    for r in getattr(app, "routes", []):
        methods = ",".join(sorted(getattr(r, "methods", []) or []))
        routes.append({"path": getattr(r, "path", ""), "methods": methods})
    return routes
