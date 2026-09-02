"""veinborn 实机测试接口 v2（纯 asyncio 单循环，修复 aiosqlite 循环绑定崩溃）。

用法：python scripts/veinborn_test_api.py [--port 8123] [--db /tmp/rpg_veinborn_api.db]
GET  /health                     → 存活
POST /cmd   {"qid","text"}       → {"ok","reply","sent"}
POST /reset                      → 清 DB
POST /lookup {"qid"}             → 玩家 session/存档状态

零外部依赖（asyncio.start_server 手写 HTTP 极简）；单事件循环常驻，
deps 绑定主循环（aiosqlite 连接不跨循环）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
os.environ.setdefault("QBotRPG_PACK_DIR", str(REPO / "content" / "veinborn"))

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

_deps = None
_db_path = "/tmp/rpg_veinborn_api.db"
_loop = None


async def _ensure_deps():
    global _deps, _loop
    if _deps is None:
        _loop = asyncio.get_running_loop()
        _deps = await build_app_deps(db_path=_db_path)
    return _deps


async def handle_cmd(qid: str, text: str) -> dict:
    deps = await _ensure_deps()
    sd = getattr(deps, "sender", None)
    if sd is not None and hasattr(sd, "_delivered"):
        try:
            sd._delivered.clear()
        except Exception:
            pass
    ev = {
        "group_id": "g_test_api", "user_id": qid, "qq_id": qid,
        "message": text, "message_id": str(uuid.uuid4()),
        "channel": "group", "group_name": "测试接口群",
    }
    try:
        reply = await asyncio.wait_for(R.run_command(ev, deps), timeout=30)
    except asyncio.TimeoutError:
        reply = "[超时 30s]"
    except Exception as exc:  # noqa: BLE001
        reply = f"[异常 {type(exc).__name__}] {exc}"
    sent: list = []
    if sd is not None and hasattr(sd, "delivered"):
        sent = [str(x) for x in sd.delivered if str(x or "").strip()]
        try:
            sd._delivered.clear()
        except Exception:
            pass
    return {"ok": True, "reply": reply or "", "sent": sent}


async def handle_lookup(qid: str) -> dict:
    import sqlite3

    try:
        con = sqlite3.connect(_db_path)
        sessions = con.execute(
            "SELECT session_type, version FROM sessions WHERE player_qid=?", (qid,)
        ).fetchall()
        players = con.execute(
            "SELECT player_qid, name, level FROM players WHERE player_qid=?", (qid,)
        ).fetchall()
        con.close()
        return {"ok": True, "sessions": [{"type": r[0], "version": r[1]} for r in sessions],
                "players": [{"qid": r[0], "name": r[1], "level": r[2]} for r in players]}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


# ---- 极简 HTTP（asyncio） ----
async def _read_body(reader: asyncio.StreamReader, headers: dict) -> bytes:
    ln = int(headers.get("content-length", "0") or 0)
    return await reader.readexactly(ln) if ln else b""


async def _write_json(writer: asyncio.StreamWriter, code: int, data: dict) -> None:
    body = json.dumps(data, ensure_ascii=False).encode()
    resp = (
        f"HTTP/1.1 {code} {'OK' if code == 200 else 'ERR'}\r\n"
        f"Content-Type: application/json; charset=utf-8\r\n"
        f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n"
    ).encode() + body
    writer.write(resp)
    try:
        await writer.drain()
    except Exception:
        pass
    writer.close()


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        req_line = await asyncio.wait_for(reader.readline(), timeout=10)
        if not req_line:
            writer.close()
            return
        method, path, _ver = req_line.decode(errors="replace").strip().split(" ", 2)
        headers: dict = {}
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=10)
            if line in (b"\r\n", b"\n", b""):
                break
            k, _, v = line.decode(errors="replace").partition(":")
            headers[k.strip().lower()] = v.strip()
        body_raw = await _read_body(reader, headers)

        if method == "GET" and path.startswith("/health"):
            await _write_json(writer, 200, {"ok": True, "db": _db_path})
        elif method == "POST" and path.startswith("/cmd"):
            body = json.loads(body_raw.decode() or "{}")
            qid = str(body.get("qid") or "u_api")
            text = str(body.get("text") or "")
            if not text.strip():
                await _write_json(writer, 400, {"ok": False, "error": "text required"})
            else:
                result = await handle_cmd(qid, text)
                await _write_json(writer, 200, result)
        elif method == "POST" and path.startswith("/reset"):
            global _deps
            _deps = None
            try:
                os.remove(_db_path)
            except FileNotFoundError:
                pass
            await _write_json(writer, 200, {"ok": True, "reset": True})
        elif method == "POST" and path.startswith("/lookup"):
            body = json.loads(body_raw.decode() or "{}")
            result = await handle_lookup(str(body.get("qid") or "u_api"))
            await _write_json(writer, 200, result)
        else:
            await _write_json(writer, 404, {"ok": False, "error": "not found"})
    except Exception as exc:  # noqa: BLE001
        try:
            await _write_json(writer, 500, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
        except Exception:
            writer.close()


async def main() -> None:
    global _db_path
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--db", default="/tmp/rpg_veinborn_api.db")
    args = ap.parse_args()
    _db_path = args.db
    # 预装配（绑定主循环）
    await _ensure_deps()
    srv = await asyncio.start_server(_handle, "127.0.0.1", args.port)
    print(f"veinborn test API v2 on http://127.0.0.1:{args.port} (db={_db_path})", flush=True)
    async with srv:
        await srv.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
