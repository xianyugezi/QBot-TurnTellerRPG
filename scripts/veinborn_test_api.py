"""veinborn 实机测试接口（HTTP）：子 agent / 外部脚本调用来测真实装配链路。

用法：python scripts/veinborn_test_api.py [--port 8123] [--db /tmp/rpg_veinborn_api.db]
GET  /health                      → 存活检查
POST /cmd                         → body {"qid": "...", "text": "注册"} → run_command 完整回复
   响应: {"ok": true, "reply": "...", "sent": ["...", ...]}
   - reply = run_command 返回值（元数据）
   - sent  = BattlePipeline/sender delivered 收集的正文（bot 实际发群内容）
POST /reset                       → 清 DB（新玩家重测）
POST /lookup                      → body {"qid": "..."} → 玩家当前状态（会话/位置/战斗）

零 NoneBot import（纯内核装配，与实机同链路 build_app_deps + run_command）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

os.environ.setdefault("QBotRPG_PACK_DIR", str(REPO / "content" / "veinborn"))

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402
from qbot_rpg.commands import battle_commands as BC  # noqa: E402

_deps = None
_db_path: str = "/tmp/rpg_veinborn_api.db"

# —— pipeline 发送收集（bot 实际发群内容 = Sender.delivered）——
_orig_send = BC.BattlePipeline.send


def _spy_send(self, text, **kw):
    return _orig_send(self, text, **kw)


BC.BattlePipeline.send = _spy_send


def _json_body(scope) -> dict:
    """ASGI 请求体解析（简易）。"""
    return {}


async def handle_cmd(qid: str, text: str) -> dict:
    """单条指令：真实装配 run_command + 收集发送正文。"""
    global _deps
    if _deps is None:
        _deps = await build_app_deps(db_path=_db_path)
    ev = {
        "group_id": "g_test_api",
        "user_id": qid,
        "qq_id": qid,
        "message": text,
        "message_id": str(uuid.uuid4()),
        "channel": "group",
        "group_name": "测试接口群",
    }
    # 清 sender delivered（跨消息共享防累积）
    sd = getattr(_deps, "sender", None)
    if sd is not None and hasattr(sd, "_delivered"):
        try:
            sd._delivered.clear()
        except Exception:
            pass
    try:
        reply = await asyncio.wait_for(R.run_command(ev, _deps), timeout=30)
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


# —— 极简 HTTP（http.server 线程 + asyncio.run，够测试用）——
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音
        pass

    def _send_json(self, code: int, data: dict) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        if self.path.startswith("/health"):
            self._send_json(200, {"ok": True, "db": _db_path})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):  # noqa: N802
        try:
            ln = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(ln) if ln else b"{}"
            body = json.loads(raw.decode() or "{}")
        except Exception as exc:  # noqa: BLE001
            self._send_json(400, {"ok": False, "error": f"bad json: {exc}"})
            return
        if self.path.startswith("/cmd"):
            qid = str(body.get("qid") or "u_api")
            text = str(body.get("text") or "")
            if not text.strip():
                self._send_json(400, {"ok": False, "error": "text required"})
                return
            result = asyncio.run(handle_cmd(qid, text))
            self._send_json(200, result)
        elif self.path.startswith("/reset"):
            global _deps
            _deps = None
            try:
                os.remove(_db_path)
            except FileNotFoundError:
                pass
            self._send_json(200, {"ok": True, "reset": True})
        elif self.path.startswith("/lookup"):
            qid = str(body.get("qid") or "u_api")
            import sqlite3

            try:
                con = sqlite3.connect(_db_path)
                rows = con.execute(
                    "SELECT session_type, version FROM sessions WHERE player_qid=?",
                    (qid,),
                ).fetchall()
                pl = con.execute("SELECT player_qid, name, level FROM players WHERE qid=?", (qid,)).fetchall()
                con.close()
                self._send_json(200, {
                    "ok": True,
                    "sessions": [{"type": r[0], "version": r[1]} for r in rows],
                    "players": [{"qid": r[0], "name": r[1], "level": r[2]} for r in pl],
                })
            except Exception as exc:  # noqa: BLE001
                self._send_json(500, {"ok": False, "error": str(exc)})
        else:
            self._send_json(404, {"ok": False, "error": "not found"})


def main() -> None:
    global _db_path
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8123)
    ap.add_argument("--db", default="/tmp/rpg_veinborn_api.db")
    args = ap.parse_args()
    _db_path = args.db
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"veinborn test API on http://127.0.0.1:{args.port} (db={_db_path})", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
