# -*- coding: utf-8 -*-
"""云海单机 web 壳（九期批次 236 · G6 部署交付）。

单文件本地游玩壳：标准库 http.server + qbot_rpg_bridge.assemble.build_app_deps
（适配基线 #8「单机壳 web 主形态：core 零 NoneBot，runner.run_command(event,deps)
纯函数入口」）——GET / 返回单页 UI（指令输入＋战报 feed＋八段前缀染色），
POST /cmd 把玩家消息交 run_command 并回传回复文本。

启动（交付 zip 三步部署主形态）：
    python scripts/web_shell.py                     # 缺省 content/cloudsea 包
    QBotRPG_PACK_DIR=content/demo_full python scripts/web_shell.py
    python scripts/web_shell.py --pack content/cloudsea --db data/cloudsea_web.db --port 8010

红线：零引擎改动（只消费 run_command/build_app_deps 既有入口）；零 NoneBot；
零第三方依赖（标准库 asyncio/http.server/json）。
"""
from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from qbot_rpg_bridge.assemble import build_app_deps  # noqa: E402
from qbot_rpg.assembly import runner as R  # noqa: E402

# ---------------------------------------------------------------- 八段前缀染色（215 战报八段终案展示面）
_LINE_CLASS = [
    ("R7", "seg-head"), ("⚔️", "seg-act"), ("🎯", "seg-act"), ("💥", "seg-dmg"),
    ("🎁", "seg-loot"), ("⚠️", "seg-warn"), ("▸", "seg-hint"), ("📜", "seg-head"),
    ("─", "seg-sep"), ("🤖", "seg-warn"), ("⏳", "seg-warn"), ("🧭", "seg-head"),
    ("🌅", "seg-head"), ("🔍", "seg-head"), ("🧭", "seg-head"), ("⚗️", "seg-act"),
]

PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<title>云海猎团 · 单机壳</title>
<style>
 body{background:#0e1420;color:#d8e2f0;font-family:Consolas,'Microsoft YaHei',monospace;
      max-width:860px;margin:24px auto;padding:0 12px}
 h1{font-size:20px;color:#7fc4ff} #feed{white-space:pre-wrap;line-height:1.55;
      background:#131b2b;border:1px solid #26334d;border-radius:8px;padding:14px;min-height:320px}
 .seg-head{color:#7fc4ff}.seg-act{color:#ffd479}.seg-dmg{color:#ff8f8f}
 .seg-loot{color:#a8e6a1}.seg-warn{color:#ffb36b}.seg-hint{color:#9aa8bd}.seg-sep{color:#3a4a66}
 #bar{display:flex;gap:8px;margin-top:10px}
 #cmd{flex:1;background:#0a0f18;color:#d8e2f0;border:1px solid #26334d;border-radius:6px;
      padding:9px;font-size:15px}
 button{background:#2a5aa8;color:#fff;border:0;border-radius:6px;padding:9px 18px;cursor:pointer}
 .hint{color:#71809a;font-size:12px;margin-top:8px}
</style></head><body>
<h1>云海猎团 Cloudsea Hunting Corps · 单机壳（九期 236）</h1>
<div id="feed">港务系统在线。发 `帮助` 或 `注册` 开始；`局面` 看战况。</div>
<div id="bar"><input id="cmd" placeholder="输入指令，如：注册 / 攻击 / 港 档 / 晨报"
      autofocus><button onclick="send()">发送</button></div>
<div class="hint"> Enter 发送 ｜ 上下文见 docs/cloudsea/ ｜ 引擎：QBot-TurnTellerRPG + content/cloudsea </div>
<script>
const feed=document.getElementById('feed'),cmd=document.getElementById('cmd');
function cls(t){for(const[p,c] of %s) if(t.startsWith(p)) return c; return '';}
function add(t){const d=document.createElement('div');d.className=cls(t);d.textContent=t;feed.appendChild(d);}
async function send(){const m=cmd.value.trim();if(!m)return;add('＞ '+m);cmd.value='';
 try{const r=await fetch('/cmd',{method:'POST',headers:{'Content-Type':'application/json'},
   body:JSON.stringify({message:m})});const j=await r.json();
 (j.reply||'(无回复/静默)').split('\\n').forEach(add);}
 catch(e){add('[壳层异常] '+e);}}
cmd.addEventListener('keydown',e=>{if(e.key==='Enter')send();});
</script></body></html>"""


class Shell:
    """单机壳状态：deps 一次性装配；多用户本地共用（user_id 按输入区分）。"""

    def __init__(self, pack_dir: str, db_path: str) -> None:
        self.pack_dir = pack_dir
        self.db_path = db_path
        self.deps = None  # bootstrap 后注入

    async def setup(self) -> None:
        self.deps = await build_app_deps(pack_dir=self.pack_dir, db_path=self.db_path)

    async def handle(self, message: str, user_id: str) -> str:
        ev = {"group_id": "local", "user_id": user_id, "message": message,
              "message_id": str(uuid.uuid4()), "channel": "group", "group_name": "单机壳"}
        try:
            return await asyncio.wait_for(R.run_command(ev, self.deps), timeout=60)
        except Exception as e:  # noqa: BLE001 —— 壳层兜底（引擎内已有 TPL-12 兜底）
            return "[壳层异常 {}] {}".format(type(e).__name__, e)


SHELL: Shell = None  # type: ignore[assignment]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a) -> None:  # noqa: N802 —— 静默访问日志
        pass

    def _json(self, obj: dict, code: int = 200) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.startswith("/cmd"):
            self._json({"reply": ""})
            return
        page = PAGE % json.dumps(_LINE_CLASS, ensure_ascii=False)
        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        if not self.path.startswith("/cmd"):
            self._json({"error": "not found"}, 404)
            return
        n = int(self.headers.get("Content-Length") or 0)
        req = json.loads(self.rfile.read(n).decode("utf-8") or "{}")
        msg = str(req.get("message") or "").strip()
        uid = str(req.get("user_id") or "player_local")
        if not msg:
            self._json({"reply": ""})
            return
        loop = asyncio.get_event_loop()
        reply = loop.run_until_complete(SHELL.handle(msg, uid))
        self._json({"reply": reply or "(无回复/静默)"})


def main() -> None:
    global SHELL
    ap = argparse.ArgumentParser(description="云海猎团单机壳（236）")
    ap.add_argument("--pack", default=str(Path(__file__).resolve().parent.parent / "content" / "cloudsea"))
    ap.add_argument("--db", default=str(Path(__file__).resolve().parent.parent / "data" / "cloudsea_web.db"))
    ap.add_argument("--port", type=int, default=8010)
    args = ap.parse_args()
    SHELL = Shell(args.pack, args.db)
    asyncio.get_event_loop().run_until_complete(SHELL.setup())
    print("云海单机壳：http://127.0.0.1:{}/  （pack={}）".format(args.port, args.pack))
    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
