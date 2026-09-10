"""编辑器宿主脚本（scripts/editor_host.py）。

文件名：scripts/editor_host.py
创建时间：2026-09-11
作者：Hermes（编辑器恢复随附——补齐 M12 遗留的「宿主缺位」：launcher_hint.py
      从未落地，M12/M12.5 期间宿主以临时脚本运行，本脚本把宿主固化为通用入口）

功能描述：
  启动 Web 内容编辑器的本地宿主（FastAPI create_app + uvicorn），浏览器打开
  http://<host>:<port>/ 即可编辑指定内容包。

用法：
  .venv/bin/python scripts/editor_host.py                          # 默认 content/veinborn @ 127.0.0.1:8080
  .venv/bin/python scripts/editor_host.py --pack content/test_demo --port 8090
  .venv/bin/python scripts/editor_host.py --host 0.0.0.0           # 公网（建议反代 + HTTPS）

参数：
  --pack  内容包目录（相对仓库根或绝对路径；缺省 env QBotRPG_PACK_DIR → content/veinborn）
  --host  监听地址（默认 127.0.0.1；AU-01 公网默认关）
  --port  端口（默认 8080，对齐 M12 UX 架构方案）
  --owner 机主身份键（编辑器登录 qq_id；缺省 env QBotRPG_EDITOR_OWNER → "owner"）

登录流程：浏览器首次访问 → 引导设置密码（AU-02：≥8 位含字母数字）→ 登录；
密码/会话为内存态（重启宿主需重新登录，对齐 M12 语义）。

铁律：零 NoneBot import；web → content/core/storage/data 正向依赖。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import List, Optional

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


def _parse_args(argv: List[str]) -> argparse.Namespace:
    """命令行参数解析。"""
    ap = argparse.ArgumentParser(
        description="QBot RPG 内容编辑器宿主（FastAPI + uvicorn）")
    ap.add_argument("--pack", default=os.environ.get("QBotRPG_PACK_DIR", ""),
                    help="内容包目录（缺省 env QBotRPG_PACK_DIR → content/veinborn）")
    ap.add_argument("--host", default="127.0.0.1",
                    help="监听地址（默认 127.0.0.1，公网请加反代）")
    ap.add_argument("--port", type=int, default=8080, help="端口（默认 8080）")
    ap.add_argument("--owner", default=os.environ.get("QBotRPG_EDITOR_OWNER", "owner"),
                    help="机主身份键（编辑器登录 qq_id）")
    return ap.parse_args(argv)


def _resolve_pack_dir(raw: str) -> Path:
    """内容包目录解析（相对 → 仓库根；缺省 → content/veinborn）。"""
    if not raw:
        return _REPO / "content" / "veinborn"
    p = Path(raw).expanduser()
    if not p.is_absolute():
        p = _REPO / p
    return p


def main(argv: Optional[List[str]] = None) -> int:
    """宿主入口：加载内容包 → 构造 state → create_app → uvicorn.run。"""
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    pack_dir = _resolve_pack_dir(args.pack)
    if not (pack_dir / "manifest.json").exists():
        print(f"[editor_host] 内容包无效（缺 manifest.json）：{pack_dir}")
        return 2

    from qbot_rpg.content.audit_store import AuditStore
    from qbot_rpg.content.editor_registry import load_editor_registry
    from qbot_rpg.content.loader import load_pack
    from qbot_rpg.content.permission_store import PermissionStore
    from qbot_rpg.web.api import create_app
    from qbot_rpg.web.auth import AuthStore

    pack = asyncio.run(load_pack(pack_dir))
    state = SimpleNamespace(
        auth_store=AuthStore(args.owner),
        registry=pack.registry,
        content_dir=pack_dir,
        editor=load_editor_registry(pack.registry),
        permission_store=PermissionStore(),
        audit_store=AuditStore(),
    )
    app = create_app(state)

    import uvicorn

    print(f"[editor_host] 内容包：{pack_dir}")
    print(f"[editor_host] 打开：http://{args.host}:{args.port}/"
          f"（首次访问引导设密；机主身份键 = {args.owner}）")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
