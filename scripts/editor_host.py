#!/usr/bin/env python3
"""内容编辑器宿主（编辑器重写批1 · 只读骨架）。

职责：只做 HTTP 宿主 —— 起 FastAPI/uvicorn、托管静态页、把 `qbot_rpg/web/api.py`
的只读元数据读取层暴露为 JSON API。**零 NoneBot import**，业务逻辑一律在 web 层。

用法：
  python scripts/editor_host.py [--pack <包名>] [--host 127.0.0.1] [--port 8090]
                                [--content-root <内容目录>]

  · 默认 127.0.0.1:8090（仅本机；公网默认关，隧道/反代另配）。
  · --pack 只决定前端默认选中哪个内容包；不传则取内容目录下第一个（不写死任何包名）。
  · 批1 只读：不含登录/落盘/校验写回（见 docs/编辑器重写_实现方案.md §四 批次划分）。

铁律：本文件是脚本（非 qbot_rpg 包内），只被人工/部署调用；web 层不被任何层 import。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

_REPO_ROOT = Path(__file__).resolve().parent.parent


def _ensure_repo_on_path() -> None:
    """让 `python scripts/editor_host.py`（sys.path[0]=scripts/）也能 import qbot_rpg。"""
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))


def create_app(pack: Optional[str] = None, root: Optional[str] = None) -> FastAPI:
    """构建只读宿主 app（供 `main()` 与测试复用）。"""
    _ensure_repo_on_path()
    from qbot_rpg.web import api  # noqa: E402  （路径注入后导入，避免 E402）

    static_dir = Path(api.__file__).resolve().parent / "static"
    content_root = str(root) if root else str(api.content_root())
    app = FastAPI(
        title="QBot-TurnTellerRPG 内容编辑器（批1 · 只读骨架）",
        docs_url=None,
        redoc_url=None,
    )

    @app.exception_handler(api.EditorError)
    async def _editor_error(_request, exc):  # type: ignore[no-untyped-def]
        return JSONResponse(
            status_code=getattr(exc, "status_code", 500),
            content={"error": str(exc), "kind": type(exc).__name__},
        )

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

    @app.get("/")
    def index():  # type: ignore[no-untyped-def]
        return FileResponse(str(static_dir / "index.html"))

    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    return app


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="内容编辑器宿主（批1 只读骨架）")
    parser.add_argument("--pack", default=None, help="默认内容包（缺省取内容目录下第一个）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=8090, help="监听端口（默认 8090）")
    parser.add_argument("--content-root", default=None,
                        help="内容包根目录（缺省 <仓库根>/content）")
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_args(argv)
    app = create_app(pack=args.pack, root=args.content_root)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
