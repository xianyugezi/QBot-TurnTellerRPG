#!/usr/bin/env python3
"""内容编辑器宿主（编辑器重写批3 · 分区页签）。

职责：只做 HTTP 宿主 —— 起 FastAPI/uvicorn、托管静态页、把 `qbot_rpg/web/api.py`
（只读元数据层）与 `qbot_rpg/web/editor_ops.py`（编辑保存层）暴露为 JSON API。
**零 NoneBot import**，业务逻辑一律在 web 层。

用法：
  python scripts/editor_host.py [--pack <包名>] [--role owner|gm]
                                [--host 127.0.0.1] [--port 8090]
                                [--content-root <内容目录>]

  · 默认 127.0.0.1:8090（仅本机；公网默认关，隧道/反代另配）。
  · --pack 只决定前端默认选中哪个内容包；不传则取内容目录下第一个（不写死任何包名）。
  · --role 表达权限位（沿用「机主可编辑 / GM 只读预览」语义）：owner 可编辑、gm 只读；
    批2 不做登录页，顶栏开关可在运行期切换（`/api/session/role`）。
  · 落盘一律经 editor_ops → atomic_store：写前校验 + 自动备份 .bak + 原子写 + 回退。

铁律：本文件是脚本（非 qbot_rpg 包内），只被人工/部署调用；web 层不被任何层 import。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import uvicorn
from fastapi import Body, FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_path() -> None:
    """让 `python scripts/editor_host.py`（sys.path[0]=scripts/）也能 import qbot_rpg。"""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


def create_app(pack: Optional[str] = None, root: Optional[str] = None,
               role: str = "owner") -> FastAPI:
    """构建宿主 app（供 `main()` 与测试复用）。role: owner（可编辑）/ gm（只读预览）。"""
    _ensure_repo_on_path()
    from qbot_rpg.web import api  # noqa: E402  （路径注入后导入，避免 E402）
    from qbot_rpg.web import editor_ops  # noqa: E402
    from qbot_rpg.content import pack_transfer  # noqa: E402  （导入体积上限的单一出处）

    static_dir = Path(api.__file__).resolve().parent / "static"
    content_root = str(root) if root else str(api.content_root())
    _ROLE_INPUTS = {editor_ops.ROLE_OWNER, editor_ops.ROLE_GM, "admin", "manager"}
    app = FastAPI(
        title="QBot-TurnTellerRPG 内容编辑器（批3 · 分区页签）",
        docs_url=None,
        redoc_url=None,
    )
    app.state.role = editor_ops.normalize_role(role)
    app.state.content_root = content_root

    @app.exception_handler(api.EditorError)
    async def _editor_error(_request, exc):  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=getattr(exc, "status_code", 500),
            content={"ok": False, "error": str(exc), "kind": type(exc).__name__},
        )

    # -------- 权限位（机主可编辑 / GM 只读预览；批2 不做登录页） --------
    @app.get("/api/session")
    def api_session():  # type: ignore[no-untyped-def]
        return editor_ops.session_info(app.state.role)

    @app.post("/api/session/role")
    def api_set_role(payload: Optional[Dict[str, Any]] = Body(default=None)):
        body = payload or {}
        raw = str(body.get("role") or "").strip().lower()
        if raw not in _ROLE_INPUTS:
            raise api.BadRequest(f"未知身份：{body.get('role')!r}")
        app.state.role = editor_ops.normalize_role(raw)
        return editor_ops.session_info(app.state.role)

    # -------- 只读元数据（批1） --------
    @app.get("/api/packs")
    def api_packs():  # type: ignore[no-untyped-def]
        return api.list_packs(root=content_root, preferred=pack)

    @app.get("/api/pack/{pack_id}/modules")
    def api_modules(pack_id: str):  # type: ignore[no-untyped-def]
        return api.list_modules(pack_id, root=content_root)

    @app.get("/api/pack/{pack_id}/module/{module}/entries")
    def api_entries(pack_id: str, module: str):  # type: ignore[no-untyped-def]
        return api.list_entries(pack_id, module, root=content_root)

    @app.get("/api/pack/{pack_id}/entry/{module}/{entry_id}")
    def api_entry(pack_id: str, module: str, entry_id: str):  # type: ignore[no-untyped-def]
        return api.entry_detail(pack_id, module, entry_id, root=content_root)

    @app.get("/api/pack/{pack_id}/refs/{target}")
    def api_refs(pack_id: str, target: str, q: Optional[str] = None):  # type: ignore[no-untyped-def]
        return api.ref_options(pack_id, target, root=content_root, query=q)

    # -------- 批6 只读：全包条目索引（全局检索）/ 新建界面 / 建议 ID / 被引用扫描 --------
    @app.get("/api/pack/{pack_id}/entry-index")
    def api_entry_index(pack_id: str):  # type: ignore[no-untyped-def]
        return api.entry_index(pack_id, root=content_root)

    @app.get("/api/pack/{pack_id}/module/{module}/new")
    def api_new_entry(pack_id: str, module: str, name: Optional[str] = None,  # type: ignore[no-untyped-def]
                      preset: Optional[str] = None):
        return api.new_entry_detail(pack_id, module, root=content_root, name=name,
                                    preset=preset)

    @app.get("/api/pack/{pack_id}/module/{module}/suggest_id")
    def api_suggest_id(pack_id: str, module: str, name: Optional[str] = None,  # type: ignore[no-untyped-def]
                       mode: Optional[str] = None, preset: Optional[str] = None):
        return api.suggest_id(pack_id, module, root=content_root, name=name,
                              mode=mode, preset=preset)

    @app.get("/api/pack/{pack_id}/entry/{module}/{entry_id}/refs")
    def api_entry_refs(pack_id: str, module: str, entry_id: str):  # type: ignore[no-untyped-def]
        return {"pack": pack_id, "module": module, "entry_id": entry_id,
                "referrers": api.reference_scan(pack_id, module, entry_id, root=content_root)}

    # -------- 校验 / 保存 / 回退（批2） --------
    @app.post("/api/pack/{pack_id}/entry/{module}/{entry_id}/validate")
    def api_validate(pack_id: str, module: str, entry_id: str,
                     payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return editor_ops.validate_entry(
            pack_id, module, entry_id, body.get("patch") or {},
            root=content_root, role=app.state.role)

    @app.post("/api/pack/{pack_id}/entry/{module}/{entry_id}/save")
    def api_save(pack_id: str, module: str, entry_id: str,
                 payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return editor_ops.save_entry(
            pack_id, module, entry_id, body.get("patch") or {},
            root=content_root, role=app.state.role)

    # -------- 批6 写入：新增条目 / 删除条目 / ID 即时校验 --------
    @app.post("/api/pack/{pack_id}/module/{module}/entry")
    def api_create_entry(pack_id: str, module: str,
                         payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return editor_ops.create_entry(
            pack_id, module, body.get("entry_id"), body.get("patch") or {},
            root=content_root, role=app.state.role, preset=body.get("preset"))

    @app.post("/api/pack/{pack_id}/module/{module}/id_check")
    def api_check_id(pack_id: str, module: str,
                     payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return api.check_entry_id(pack_id, module, body.get("entry_id"), root=content_root)

    @app.post("/api/pack/{pack_id}/entry/{module}/{entry_id}/delete")
    def api_delete_entry(pack_id: str, module: str, entry_id: str):  # type: ignore[no-untyped-def]
        return editor_ops.delete_entry(
            pack_id, module, entry_id, root=content_root, role=app.state.role)

    @app.get("/api/pack/{pack_id}/module/{module}/backup")
    def api_backup(pack_id: str, module: str):  # type: ignore[no-untyped-def]
        return editor_ops.module_backup(pack_id, module, root=content_root)

    @app.post("/api/pack/{pack_id}/module/{module}/rollback")
    def api_rollback(pack_id: str, module: str):  # type: ignore[no-untyped-def]
        return editor_ops.rollback_module(
            pack_id, module, root=content_root, role=app.state.role)

    # -------- 批8 模块开关：可启用清单 / 启用停用 / manifest 回退 --------
    @app.get("/api/pack/{pack_id}/module-catalog")
    def api_module_catalog(pack_id: str):  # type: ignore[no-untyped-def]
        return api.module_catalog(pack_id, root=content_root)

    @app.post("/api/pack/{pack_id}/module/{module}/toggle")
    def api_toggle_module(pack_id: str, module: str,
                          payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return editor_ops.set_module_enabled(
            pack_id, module, bool(body.get("enabled")),
            root=content_root, role=app.state.role)

    @app.get("/api/pack/{pack_id}/manifest/backup")
    def api_manifest_backup(pack_id: str):  # type: ignore[no-untyped-def]
        return editor_ops.module_config_backup(pack_id, root=content_root)

    @app.post("/api/pack/{pack_id}/manifest/rollback")
    def api_manifest_rollback(pack_id: str):  # type: ignore[no-untyped-def]
        return editor_ops.rollback_module_config(
            pack_id, root=content_root, role=app.state.role)

    # -------- 批11 内容包导出 / 导入（分享给别的作者） --------
    @app.get("/api/pack/{pack_id}/export")
    def api_export_pack(pack_id: str):  # type: ignore[no-untyped-def]
        """导出此包 → 浏览器下载 `.ttrpack`（只读；GM 只读身份也允许）。"""
        res = editor_ops.export_pack(pack_id, root=content_root)
        if not res.get("ok"):
            raise api.BadRequest(str(res.get("message") or "导出失败。"))
        filename = str(res["filename"])
        return Response(
            content=res["data"], media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Pack-Filename": filename,
            })

    @app.post("/api/pack/import")
    async def api_import_pack(request: Request, on_conflict: str = "",
                              new_id: str = ""):  # type: ignore[no-untyped-def]
        """导入分享来的 `.ttrpack`（请求体 = 文件原始字节；无需 multipart 依赖）。

        校验顺序与安全防护全在 `qbot_rpg/content/pack_transfer.py`：zip 结构安全 →
        export_meta/manifest 合法 → 内容校验器（红拦不落盘）→ 包 id 冲突（改名 / 覆盖且先备份）。
        GM 只读身份 → 403（`editor_ops.require_edit`）。
        """
        # 先按 Content-Length 挡超大请求（避免把超大文件读进内存）
        raw_len = request.headers.get("content-length") or ""
        if raw_len.isdigit() and int(raw_len) > pack_transfer.DEFAULT_LIMITS.max_archive_bytes:
            raise api.BadRequest(
                "导入文件超过体积上限（上限 "
                f"{pack_transfer.DEFAULT_LIMITS.max_archive_bytes // (1024 * 1024)} MB）。")
        body = await request.body()
        return editor_ops.import_pack(
            body, root=content_root, role=app.state.role,
            on_conflict=str(on_conflict or ""), new_id=(new_id or None))

    @app.get("/")
    def index():  # type: ignore[no-untyped-def]
        return FileResponse(str(static_dir / "index.html"))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="内容编辑器宿主（批3 · 分区页签）")
    parser.add_argument("--pack", default=None, help="默认内容包（缺省取内容目录下第一个）")
    parser.add_argument("--role", default="owner", choices=["owner", "gm"],
                        help="权限位：owner 可编辑（默认）/ gm 只读预览")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8090, help="监听端口（默认 8090）")
    parser.add_argument("--content-root", default=None,
                        help="内容包根目录（缺省 <仓库根>/content）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    app = create_app(pack=args.pack, root=args.content_root, role=args.role)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
