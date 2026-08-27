"""M6 内容包冒烟固化测试（D4 SMK-01/TC-SMK-01~03）。

调用 scripts/e2e_m6_smoke.py（核心函数 run_smoke / 子进程两种形态），断言：
1. 子进程 exit 0 且输出含「M6 内容包冒烟全绿」
2. run_smoke 返回 green=True + failed=0
3. 确定性重放（同 seed/now 两跑摘要逐字一致）
4. 零 NoneBot import（SMK-02 静态扫描）

依据：细化_M6_内容包冒烟（D4）§一 SMK-01~05 + TC-SMK-01~03；
对齐 tests/unit/test_e2e_m4_smoke.py 形态。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SMOKE = REPO / "scripts" / "e2e_m6_smoke.py"
MIN_TOTAL_ASSERTIONS = 25  # 四步断言 + validator 矩阵断言数下限（当前 28）


def _import_script():
    spec = importlib.util.spec_from_file_location("e2e_m6_smoke", SMOKE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_smoke_subprocess_exit0_and_green_line() -> None:
    """子进程跑冒烟：exit 0 且输出含全绿行（TC-SMK-01）。"""
    r = subprocess.run(
        [sys.executable, str(SMOKE)], capture_output=True, text=True, timeout=120, cwd=REPO
    )
    assert r.returncode == 0, f"冒烟子进程非零退出：{r.stderr[-500:]}"
    assert "M6 内容包冒烟全绿" in r.stdout, f"未输出全绿行：{r.stdout[-300:]}"


def test_run_smoke_green_and_deterministic() -> None:
    """run_smoke 全绿 + 确定性重放（TC-SMK-03）。"""
    mod = _import_script()
    a = mod.run_smoke()
    b = mod.run_smoke()
    assert a["green"] is True, f"冒烟失败：{a.get('failures')}"
    assert int(a.get("failed", 0)) == 0, f"存在失败断言：{a.get('failures')}"
    assert a == b, "确定性重放不一致（同参两次 run_smoke 摘要须逐字一致）"


def test_smoke_assertion_count_floor() -> None:
    """断言数下限（D4 SMK-05：分路径断言计数）。"""
    mod = _import_script()
    a = mod.run_smoke()
    total = int(a["passed"]) + int(a["failed"])
    assert total >= MIN_TOTAL_ASSERTIONS, f"断言数 {total} 低于下限 {MIN_TOTAL_ASSERTIONS}"


def test_smoke_zero_nonebot_import() -> None:
    """零 NoneBot 铁律（SMK-02 / TC-SMK-02：ast 扫描 import 语句无 nonebot）。"""
    import ast

    tree = ast.parse(SMOKE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "nonebot" in node.module:
            raise AssertionError(f"冒烟脚本引入 NoneBot：{node.module}")
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "nonebot" or alias.name.startswith("nonebot"):
                    raise AssertionError(f"冒烟脚本引入 NoneBot：{alias.name}")
