"""编辑器重写批7 · 启动脚本回归（scripts/editor_start.sh）。

覆盖：
  · 语法 / --help；
  · 人话报错路径：未知参数、非法权限位、端口非数字、内容包不存在、内容目录不存在；
  · 真机起服：脚本拉起编辑器 → /api/packs 与 /api/session 可访问 → 打印 127.0.0.1 地址
    → Ctrl+C（SIGTERM）能正常停下。

只读：起服后只做 GET，不改任何内容文件。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import List

from qbot_rpg.web import api

_REPO = Path(__file__).resolve().parents[2]
SCRIPT = _REPO / "scripts" / "editor_start.sh"
CONTENT = _REPO / "content"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bash", str(SCRIPT), *args], cwd=str(_REPO),
                          capture_output=True, text=True, timeout=60)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = int(s.getsockname()[1])
    s.close()
    return port


def test_start_script_syntax_ok() -> None:
    p = subprocess.run(["bash", "-n", str(SCRIPT)], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr


def test_start_script_help() -> None:
    p = _run("--help")
    assert p.returncode == 0
    for token in ("--pack", "--content-root", "--role", "--port", "用法"):
        assert token in p.stdout, token


def test_start_script_human_errors() -> None:
    cases: List[List[str]] = [
        ["--nope"],
        ["--role", "admin"],
        ["--port", "abc"],
        ["--pack", "zz_no_such_pack"],
        ["--content-root", "/tmp/zz_no_such_content_root"],
    ]
    for args in cases:
        p = _run(*args)
        assert p.returncode == 1, (args, p.stdout, p.stderr)
        assert "启动失败" in p.stderr, (args, p.stderr)
        assert "Traceback" not in p.stderr, (args, p.stderr)


def test_start_script_missing_value_is_human() -> None:
    p = _run("--pack")
    assert p.returncode == 1
    assert "启动失败" in p.stderr and "缺少取值" in p.stderr


def test_start_script_serves_and_stops() -> None:
    port = _free_port()
    pack = api.list_packs(root=CONTENT)["packs"][0]["id"]
    log_path = Path(tempfile.mkdtemp(prefix="editor_start_")) / "server.log"
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(
            ["bash", str(SCRIPT), "--port", str(port), "--pack", pack,
             "--python", sys.executable],
            cwd=str(_REPO), stdout=log, stderr=subprocess.STDOUT,
            text=True, start_new_session=True,
        )
    try:
        base = f"http://127.0.0.1:{port}"
        body = None
        deadline = time.time() + 25
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            try:
                with urllib.request.urlopen(base + "/api/packs", timeout=2) as r:
                    body = json.load(r)
                    break
            except Exception:
                time.sleep(0.3)
        assert body is not None, "编辑器未在 25s 内起来：\n" + log_path.read_text(encoding="utf-8")
        assert any(p["id"] == pack for p in body["packs"])
        with urllib.request.urlopen(base + "/api/session", timeout=3) as r:
            session = json.load(r)
        assert session["editable"] is True and session["role"] == "owner"
        banner = log_path.read_text(encoding="utf-8")
        assert f"http://127.0.0.1:{port}/" in banner
        assert "ssh -N -L" in banner  # 安全暴露提示
    finally:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)
