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
    from qbot_rpg.web import csv_ops  # noqa: E402  （批34：通用 CSV 导入导出）
    from qbot_rpg.content import pack_transfer  # noqa: E402  （导入体积上限的单一出处）
    from qbot_rpg.assembly import editor_aliases  # noqa: E402  （批19 #7：别名视图在装配层）

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

    # 批32 C1（框架 §6.12-08）：全包条目级「未使用」标记——一次算完，前端一次取。
    @app.get("/api/pack/{pack_id}/unused")
    def api_pack_unused(pack_id: str):  # type: ignore[no-untyped-def]
        return api.pack_unused(pack_id, root=content_root)

    # 批35（框架 §6.12-12）：进阶继承树只读接口（job 树：从哪些 job 进阶 + 继承什么）。
    @app.get("/api/pack/{pack_id}/job-tree")
    def api_job_tree(pack_id: str):  # type: ignore[no-untyped-def]
        return api.job_tree(pack_id, root=content_root)

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
            root=content_root, role=app.state.role,
            # 批21 · C：改 ID 有引用时需界面确认（confirm=true）才写入。
            confirm=bool(body.get("confirm")))

    # 批32 B1（框架 §6.12-06）：框架关键模板只读 → 「复制为包覆盖」生成包内覆盖条目。
    @app.post("/api/pack/{pack_id}/entry/{module}/{entry_id}/copy_override")
    def api_copy_override(pack_id: str, module: str, entry_id: str):  # type: ignore[no-untyped-def]
        return editor_ops.copy_framework_override(
            pack_id, module, entry_id, root=content_root, role=app.state.role)

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
        data = api.module_catalog(pack_id, root=content_root)
        # 批19 #7：别名视图在装配层组装（web 读取层不得依赖 commands/assembly），注入响应。
        data["aliases"] = editor_aliases.list_aliases(
            api._pack_dir(pack_id, content_root))
        return data

    # 批19 #7：指令别名视图（框架内置 ∪ 包声明）
    @app.get("/api/pack/{pack_id}/aliases")
    def api_aliases(pack_id: str):  # type: ignore[no-untyped-def]
        return editor_aliases.list_aliases(api._pack_dir(pack_id, content_root))

    @app.post("/api/pack/{pack_id}/module/{module}/toggle")
    def api_toggle_module(pack_id: str, module: str,
                          payload: Optional[Dict[str, Any]] = Body(default=None)):  # type: ignore[no-untyped-def]
        body = payload or {}
        return editor_ops.set_module_enabled(
            pack_id, module, bool(body.get("enabled")),
            root=content_root, role=app.state.role)

    @app.post("/api/pack/{pack_id}/module-preset/{preset_id}/apply")
    def api_apply_module_preset(pack_id: str, preset_id: str):  # type: ignore[no-untyped-def]
        """批65 · 一键应用「推荐组合」：累加启用 + 依赖闭包 + 单次备份（可一键回退）。"""
        return editor_ops.apply_module_preset(
            pack_id, preset_id, root=content_root, role=app.state.role)

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

    # -------- 批34 通用 CSV：模块级导出 / 导入（框架 §6.7/§6.11/§6.12-05/§6.12-20） --------
    @app.get("/api/pack/{pack_id}/module/{module}/export_csv")
    def api_export_csv(pack_id: str, module: str):  # type: ignore[no-untyped-def]
        """导出该模块 → 浏览器下载 CSV（UTF-8 带 BOM）。只读；GM 只读身份也允许。"""
        res = csv_ops.export_csv(pack_id, module, root=content_root)
        if not res.get("ok"):
            raise api.BadRequest(str(res.get("message") or "CSV 导出失败。"))
        filename = str(res["filename"])
        return Response(
            content=str(res["text"]), media_type="text/csv; charset=utf-8",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-CSV-Filename": filename,
            })

    @app.post("/api/pack/{pack_id}/module/{module}/import_csv")
    async def api_import_csv(pack_id: str, module: str, request: Request,
                             mode: str = "append", position: int = 0,
                             on_conflict: str = "skip"):  # type: ignore[no-untyped-def]
        """导入模块 CSV（请求体 = 文件原始字节；UTF-8 / GBK 自动识别）。

        逐行引用校验 → 默认整批拒绝（零写入零备份）；冲突默认跳过（可显式覆盖）；
        写盘走既有「校验 → 备份 → 原子写 → 回读复核 / 回退」链路。
        GM 只读身份 → 403（`editor_ops.require_edit`）。
        """
        body = await request.body()
        return csv_ops.import_csv(
            pack_id, module, body, mode=mode, position=position,
            on_conflict=on_conflict, root=content_root, role=app.state.role)

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
