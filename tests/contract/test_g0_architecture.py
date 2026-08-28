"""G0 架构前置契约（细化_3a#TC-01~03 + 细化_5d#G0/TC-5d-33）。

- 端到端：以 subprocess 跑 scripts/check_architecture.py，断言 exit 0 + ARCH-OK
- 纯函数：复用 check_architecture 的遍历/分层函数做静态断言（零 NoneBot / 依赖方向）
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import TESTS_DIR  # type: ignore[import-not-found]

REPO_ROOT = TESTS_DIR.parent

# ---- import check_architecture 纯函数（scripts 不在包内，走 sys.path 插入）----
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import check_architecture as arch # type: ignore[import-not-found]  # noqa: E402


def test_g0_subprocess_exit0():
    """TC-5d-33 / G0：G0 架构检查脚本全绿。"""
    r = subprocess.run(
        [sys.executable, "scripts/check_architecture.py", "--path", "."],
        cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=60,
    )
    assert r.returncode == 0, f"G0 失败:\n{r.stdout}\n{r.stderr}"
    assert "ARCH-OK" in r.stdout


def test_core_layers_zero_nonebot():
    """R1/TC-01：core/world/storage/content/data 五层零 nonebot import。"""
    files = arch.iter_qbot_py_files(str(REPO_ROOT))
    zero = {"core", "world", "storage", "content", "data"}
    violations = []
    for f in files:
        if arch.layer_of(f) not in zero:
            continue
        tree = ast.parse(open(f, "r", encoding="utf-8").read(), filename=f)
        for _, desc, lineno in arch.find_nonebot_imports(tree, f):
            violations.append(f"{f}:{lineno} {desc}")
    assert not violations, violations


def test_nonebot_only_in_commands():
    """R2/TC-02：全仓 import nonebot 仅允许 qbot_rpg/commands/ 内。"""
    files = arch.iter_qbot_py_files(str(REPO_ROOT))
    cmds = os.path.join(str(REPO_ROOT), "qbot_rpg", "commands")
    offenders = []
    for f in files:
        tree = ast.parse(open(f, "r", encoding="utf-8").read(), filename=f)
        for hit_file, desc, lineno in arch.find_nonebot_imports(tree, f):
            if not os.path.dirname(hit_file).startswith(cmds):
                offenders.append(f"{hit_file}:{lineno} {desc}")
    assert not offenders, offenders


def test_find_nonebot_imports_catches_from_import():
    """P1-1（架构复查）：find_nonebot_imports 必须命中 `from nonebot import X` / 
    `from nonebot.adapters.onebot.v11 import Bot`（ImportFrom 形态，契约 R1 点名形态）。

    旧实现只比对 alias.name，漏检 node.module=="nonebot" 的 ImportFrom——门禁静默放行。
    """
    cases = [
        ("import nonebot", "import nonebot"),
        ("import nonebot.adapters", "import nonebot.adapters"),
        ("from nonebot import on_command", "from nonebot import on_command"),
        ("from nonebot.adapters.onebot.v11 import Bot, Message",
         "from nonebot.adapters.onebot.v11 import Bot, Message"),
    ]
    for src, expected_desc in cases:
        tree = ast.parse(src, filename="<test>")
        hits = arch.find_nonebot_imports(tree, "fake.py")
        assert any(desc == expected_desc for _, desc, _ in hits), \
            f"漏检 {src!r}：hits={hits}"


def test_commands_web_not_depended():
    """R3/D-05：commands/web 不被任何 qbot_rpg 模块 import（最外壳）。"""
    dep_edges = set()
    files = arch.iter_qbot_py_files(str(REPO_ROOT))
    for f in files:
        tree = ast.parse(open(f, "r", encoding="utf-8").read(), filename=f)
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                parts = node.module.split(".")
                if parts and parts[0] == "qbot_rpg" and len(parts) >= 2:
                    dep_edges.add((arch.layer_of(f), parts[1]))
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = (alias.name or "").split(".")
                    if parts and parts[0] == "qbot_rpg" and len(parts) >= 2:
                        dep_edges.add((arch.layer_of(f), parts[1]))
    for src, dst in dep_edges:
        if src == dst:
            continue  # 同层内部模块互引合法（§1.4 矩阵只约束跨层方向）
        if src == "assembly":
            continue  # 装配层接线 commands 豁免（与 check_architecture.py 同口径）
        assert dst not in ("commands", "web"), f"{src} -> {dst} 反向依赖外部壳层"
