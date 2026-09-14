#!/usr/bin/env python3
"""CTB 重写专用门禁脚本（scripts/verify_ctb.py）—— Agent 6 · 契约守卫。

设计口径：**基线比对，不要求绝对零告警**——CTB 重写期业务代码持续变动，
强行要求 ruff/mypy 归零会阻断重写；改为「对照 Phase 0 基线快照，只允许减少
不允许新增」。

检查项（4 组）：
  G-LINT-RUFF   ruff check .  对比 `qa_ctb_baseline_ruff.txt`（基线 66）
  G-LINT-MYPY   mypy qbot_rpg  对比 `qa_ctb_baseline_mypy.txt`（基线 32；实测 24，良性下降）
  G-CTB-TEST    跑 CTB 契约测试 + 调度器独立测试（tests/ctb/** + tests/unit/test_ctb_scheduler.py）
  G0-ARCH       python scripts/check_architecture.py（须输出 ARCH-OK）

如何比对：
  - ruff/mypy 输出按「(文件:行:列) → 错误码」指纹化，取**集合差**：
      · 基线有而当前无 → 已修复（允许，计入减少）
      · 当前有而基线无 → **新增**（FAIL，列出明细）
  - 计数仅作辅助展示；判定以**集合新增**为准（防「数量持平但换了位置」的假绿）。

用法：
  python scripts/verify_ctb.py               # 全部检查
  python scripts/verify_ctb.py --lint        # 仅静态基线比对
  python scripts/verify_ctb.py --tests       # 仅 CTB 测试
  python scripts/verify_ctb.py --arch        # 仅 G0 架构
  python scripts/verify_ctb.py --update-baseline  # 重新生成基线快照（人工确认后使用）

退出码：0 = 全部 PASS；1 = 任一 FAIL；2 = 参数错误 / 工具缺失。
硬约束：本脚本只读业务代码，不修改 `qbot_rpg/`；仅 `--update-baseline` 写基线文件。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple

REPO = Path(__file__).resolve().parent.parent
VENV_BIN = REPO / ".venv" / "bin"
PY = VENV_BIN / "python"
RUFF = VENV_BIN / "ruff"
MYPY = VENV_BIN / "mypy"

RUFF_BASELINE = REPO / "qa_ctb_baseline_ruff.txt"
MYPY_BASELINE = REPO / "qa_ctb_baseline_mypy.txt"

#: CTB 契约测试与调度器独立测试路径
CTB_TEST_PATHS: Tuple[str, ...] = (
    "tests/ctb",
    "tests/unit/test_ctb_scheduler.py",
)

# ruff concise 行：  path:line:col: CODE message
_RUFF_CONCISE_RE = re.compile(r"^(?P<loc>[^\s:][^:]*:\d+:\d+):\s*(?P<code>[A-Z]+\d+)\b")
# ruff full 格式：首行 `CODE message`，次行 `  --> path:line:col`
_RUFF_FULL_CODE_RE = re.compile(r"^(?P<code>[A-Z]+\d+)\s+\S")
_RUFF_FULL_LOC_RE = re.compile(r"^\s*-->\s*(?P<loc>[^\s:][^:]*:\d+:\d+)")
# mypy 行： path:line: error: message  [code]
_MYPY_RE = re.compile(
    r"^(?P<loc>[^\s:][^:]*:\d+):\s*error:\s*(?P<msg>.*?)(?:\s*\[(?P<code>[^\]]+)\])?$"
)
_RUFF_TOTAL_RE = re.compile(r"Found (\d+) errors?")
_MYPY_TOTAL_RE = re.compile(r"Found (\d+) errors?")


# ---------------------------------------------------------------------------
# 结果容器
# ---------------------------------------------------------------------------
@dataclass
class StepResult:
    """单个门禁步骤的结果。"""

    name: str
    passed: bool
    detail: str = ""
    added: List[str] = field(default_factory=list)
    removed: List[str] = field(default_factory=list)
    counts: Dict[str, int] = field(default_factory=dict)


def _run(cmd: Sequence[str], timeout: int = 1200) -> Tuple[int, str]:
    """运行子进程并合并 stdout/stderr（工具缺失 → 抛 FileNotFoundError）。"""
    proc = subprocess.run(
        list(cmd),
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _require_tool(path: Path) -> None:
    """确认工具存在（否则 exit 2，避免误判为 PASS）。"""
    if not path.exists():
        print(f"[FATAL] 未找到工具：{path}", file=sys.stderr)
        sys.exit(2)


# ---------------------------------------------------------------------------
# 指纹化
# ---------------------------------------------------------------------------
def _fingerprint_ruff(output: str) -> Set[str]:
    """ruff 输出 → {loc|code} 指纹集合（同时兼容 concise 与 full 两种格式）。

    基线快照 `qa_ctb_baseline_ruff.txt` 为 **full** 格式（`CODE msg` + `  --> loc`）；
    本脚本当前 run 亦用 full 输出，故解析时按「代码行 → 下一条 `-->` 位置行」配对。
    同时保留 concise 解析分支，容忍两种格式混用（防未来格式切换造成假绿）。
    """
    fps: Set[str] = set()
    pending_code: Optional[str] = None
    for line in output.splitlines():
        stripped = line.strip()
        # concise 分支
        mc = _RUFF_CONCISE_RE.match(stripped)
        if mc:
            fps.add(f"{mc.group('loc')}|{mc.group('code')}")
            pending_code = None
            continue
        # full 分支：代码行
        mcode = _RUFF_FULL_CODE_RE.match(stripped)
        if mcode:
            pending_code = mcode.group("code")
            continue
        # full 分支：位置行
        mloc = _RUFF_FULL_LOC_RE.match(line)
        if mloc and pending_code:
            fps.add(f"{mloc.group('loc')}|{pending_code}")
            pending_code = None
    return fps


def _fingerprint_mypy(output: str) -> Set[str]:
    """mypy 输出 → {loc|code} 指纹集合（忽略消息文案漂移）。"""
    fps: Set[str] = set()
    for line in output.splitlines():
        m = _MYPY_RE.match(line.strip())
        if m:
            code = m.group("code") or "no-code"
            fps.add(f"{m.group('loc')}|{code}")
    return fps


def _parse_total(output: str, pattern: re.Pattern) -> Optional[int]:
    """从工具尾部汇总行取 error 总数（无 → None）。"""
    totals = pattern.findall(output)
    return int(totals[-1]) if totals else None


def _read_baseline(path: Path) -> str:
    """读基线快照（不存在 → 空串，视作空基线）。"""
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# 步骤 1/2：静态门禁（基线比对）
# ---------------------------------------------------------------------------
def check_ruff(baseline_text: str) -> StepResult:
    """ruff 基线比对：只允许减少，不允许新增。"""
    if not RUFF.exists():
        return StepResult("G-LINT-RUFF", False, f"ruff 不在 {RUFF}（PATH 外）")
    code, out = _run([str(RUFF), "check", ".", "--output-format=full"])
    cur = _fingerprint_ruff(out)
    base = _fingerprint_ruff(baseline_text)
    added = sorted(cur - base)
    removed = sorted(base - cur)
    cur_total = _parse_total(out, _RUFF_TOTAL_RE)
    base_total = _parse_total(baseline_text, _RUFF_TOTAL_RE)
    passed = not added
    detail = (
        f"当前 {cur_total if cur_total is not None else len(cur)} / "
        f"基线 {base_total if base_total is not None else len(base)}"
        f"；新增 {len(added)} 已修复 {len(removed)}（exit={code}）"
    )
    return StepResult(
        "G-LINT-RUFF", passed, detail, added, removed,
        {"current": cur_total or len(cur), "baseline": base_total or len(base)},
    )


def check_mypy(baseline_text: str) -> StepResult:
    """mypy 基线比对：只允许减少，不允许新增。"""
    if not MYPY.exists():
        return StepResult("G-LINT-MYPY", False, f"mypy 不在 {MYPY}")
    code, out = _run([str(MYPY), "qbot_rpg"])
    cur = _fingerprint_mypy(out)
    base = _fingerprint_mypy(baseline_text)
    added = sorted(cur - base)
    removed = sorted(base - cur)
    cur_total = _parse_total(out, _MYPY_TOTAL_RE)
    base_total = _parse_total(baseline_text, _MYPY_TOTAL_RE)
    passed = not added
    detail = (
        f"当前 {cur_total if cur_total is not None else len(cur)} / "
        f"基线 {base_total if base_total is not None else len(base)}"
        f"；新增 {len(added)} 已修复 {len(removed)}（exit={code}）"
    )
    return StepResult(
        "G-LINT-MYPY", passed, detail, added, removed,
        {"current": cur_total or len(cur), "baseline": base_total or len(base)},
    )


# ---------------------------------------------------------------------------
# 步骤 3：CTB 测试
# ---------------------------------------------------------------------------
def check_ctb_tests() -> StepResult:
    """跑 CTB 契约测试 + 调度器独立测试（xfail 不计失败，xpass 允许）。"""
    if not PY.exists():
        return StepResult("G-CTB-TEST", False, f"python 不在 {PY}")
    cmd = [str(PY), "-m", "pytest", *CTB_TEST_PATHS, "-q", "--no-header", "-p", "no:cacheprovider"]
    code, out = _run(cmd)
    passed = code == 0
    summary = ""
    for line in reversed(out.splitlines()):
        if "passed" in line or "failed" in line or "error" in line:
            summary = line.strip()
            break
    return StepResult("G-CTB-TEST", passed, summary or f"exit={code}")


# ---------------------------------------------------------------------------
# 步骤 4：G0 架构
# ---------------------------------------------------------------------------
def check_arch() -> StepResult:
    """G0 架构门禁：须输出 ARCH-OK。"""
    if not PY.exists():
        return StepResult("G0-ARCH", False, f"python 不在 {PY}")
    code, out = _run([str(PY), "scripts/check_architecture.py"])
    passed = code == 0 and "ARCH-OK" in out
    tail = ""
    for line in reversed(out.splitlines()):
        if "ARCH-OK" in line or "违规" in line or "FAIL" in line:
            tail = line.strip()
            break
    return StepResult("G0-ARCH", passed, tail or f"exit={code}")


# ---------------------------------------------------------------------------
# 主流程
# ---------------------------------------------------------------------------
def _print_result(r: StepResult) -> None:
    """打印单步结果（含新增明细）。"""
    flag = "PASS" if r.passed else "FAIL"
    print(f"[{flag}] {r.name}  {r.detail}")
    if r.added:
        print(f"       ── 新增告警 {len(r.added)} 条（基线比对不允许新增）：")
        for fp in r.added[:30]:
            print(f"         + {fp}")
        if len(r.added) > 30:
            print(f"         ...（其余 {len(r.added) - 30} 条省略）")
    if r.removed and len(r.removed) <= 10:
        for fp in r.removed:
            print(f"         - {fp}（已修复）")


def main(argv: Optional[Sequence[str]] = None) -> int:
    """入口：解析参数 → 跑选定门禁 → 打印摘要 → 返回退出码。"""
    parser = argparse.ArgumentParser(description="CTB 重写门禁（基线比对）")
    parser.add_argument("--lint", action="store_true", help="仅 ruff/mypy 基线比对")
    parser.add_argument("--tests", action="store_true", help="仅 CTB 测试")
    parser.add_argument("--arch", action="store_true", help="仅 G0 架构门禁")
    parser.add_argument("--update-baseline", action="store_true",
                        help="重新生成基线快照（qa_ctb_baseline_*.txt）")
    args = parser.parse_args(argv)

    _require_tool(PY)

    # 基线更新模式
    if args.update_baseline:
        return _update_baseline()

    # 未指定 → 全部
    run_all = not (args.lint or args.tests or args.arch)

    results: List[StepResult] = []

    if run_all or args.lint:
        results.append(check_ruff(_read_baseline(RUFF_BASELINE)))
        results.append(check_mypy(_read_baseline(MYPY_BASELINE)))
    if run_all or args.tests:
        results.append(check_ctb_tests())
    if run_all or args.arch:
        results.append(check_arch())

    print("=" * 68)
    print("CTB 门禁 · scripts/verify_ctb.py")
    print("=" * 68)
    for r in results:
        _print_result(r)

    failed = [r for r in results if not r.passed]
    print("-" * 68)
    if failed:
        print(f"RESULT: FAIL（{len(failed)}/{len(results)} 项未通过）")
        for r in failed:
            print(f"  ✗ {r.name}: {r.detail}")
        return 1
    print(f"RESULT: PASS（{len(results)}/{len(results)} 项通过）")
    return 0


def _update_baseline() -> int:
    """重新生成基线快照（人工确认后使用）。"""
    if not RUFF.exists() or not MYPY.exists():
        print("[FATAL] ruff/mypy 缺失，无法更新基线", file=sys.stderr)
        return 2
    _, ruff_out = _run([str(RUFF), "check", ".", "--output-format=full"])
    _, mypy_out = _run([str(MYPY), "qbot_rpg"])
    RUFF_BASELINE.write_text(ruff_out, encoding="utf-8")
    MYPY_BASELINE.write_text(mypy_out, encoding="utf-8")
    print(f"[OK] 已更新基线：{RUFF_BASELINE.name} / {MYPY_BASELINE.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
