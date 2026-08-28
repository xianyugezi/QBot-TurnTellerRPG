#!/usr/bin/env python3
"""通用检查入口（scripts/check_all.py）——项目所有检查工具的统一下发点。

用途：一条命令复查项目状态（长期保留的通用设定，不随里程碑清理）。

集成现有检查工具（只调用不重复实现）：
  - scripts/run_all_tests.py      全量回归（M0~M7 门禁 + 覆盖率 ≥80% + 静态门禁 + 全量 pytest）
  - scripts/check_architecture.py G0 架构分层门禁（TC-01~04）
  - scripts/check_m7_content.py  内容包校验器（隐藏要素可达性 / 条件键白名单 / 模板占位符）
  - scripts/verify/verify_mN.py  各里程碑门禁（N=0~7）

用法：
  python scripts/check_all.py             # 快速检查：静态+架构+内容包+单测（默认）
  python scripts/check_all.py --full      # 全量回归（含里程碑门禁+覆盖率，慢 ~5 分钟）
  python scripts/check_all.py --arch      # 仅架构门禁
  python scripts/check_all.py --lint      # 仅 ruff/mypy 静态
  python scripts/check_all.py --content   # 仅内容包校验
  python scripts/check_all.py --unit      # 仅单元测试（tests/unit）
  python scripts/check_all.py --verify 7  # 仅里程碑门禁（N=0~7）
  python scripts/check_all.py --fast      # 冒烟模式（性质用例抽样 + 跳过覆盖率，配 --full 用）
  python scripts/check_all.py --skip-lint # 跳过静态门禁（run_all_tests 逃生口，配 --full 用）
  可组合：python scripts/check_all.py --lint --arch --content

输出：控制台统一摘要 + docs/verify/check_report.md（时间戳归档，供复查）。
退出码：0 = 全部通过；1 = 有失败；2 = 参数错误。

约定（通用设定）：
  - 本脚本 + scripts/verify/* + run_all_tests.py + check_*.py 为**长期保留**检查工具，
    不随里程碑清理；新里程碑门禁按 verify_mN.py 模式追加，自动被 --full 纳入。
  - 快速复查（日常）：python scripts/check_all.py
  - 完整验收（里程碑收尾）：python scripts/check_all.py --full
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = REPO / ".venv" / "bin" / "python"
REPORT = REPO / "docs" / "verify" / "check_report.md"

_NOW = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
_RESULTS: list[dict] = []


def _run(name: str, args: list, timeout: int = 900) -> bool:
    """运行一个检查子进程，记录结果。"""
    cmd = [str(PY), *args]
    print(f"\n[{name}] 运行：python {' '.join(args)}")
    try:
        r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=timeout)
        ok = r.returncode == 0
        tail = "\n".join((r.stdout or "").splitlines()[-3:]).strip()
        print(f"  → {'✅ 通过' if ok else '❌ 失败'}")
        if tail:
            print(f"    {tail}")
        _RESULTS.append({"name": name, "ok": ok, "tail": tail})
        return ok
    except subprocess.TimeoutExpired:
        print(f"  → ❌ 超时（>{timeout}s）")
        _RESULTS.append({"name": name, "ok": False, "tail": "超时"})
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  → ❌ {type(e).__name__}: {e}")
        _RESULTS.append({"name": name, "ok": False, "tail": str(e)})
        return False


def _lint() -> bool:
    ok = True
    for tool in ("ruff", "mypy"):
        r = subprocess.run([str(REPO / ".venv" / "bin" / tool), "check", "."] if tool == "ruff"
                           else [str(REPO / ".venv" / "bin" / tool), "."],
                           cwd=str(REPO), capture_output=True, text=True, timeout=300)
        passed = r.returncode == 0
        print(f"\n[{tool}] 全仓 {'✅ 通过' if passed else '❌ 失败'}")
        if not passed:
            print("    " + "\n    ".join(
                (r.stdout + r.stderr).splitlines()[-4:]))
        _RESULTS.append({"name": f"{tool} 全仓", "ok": passed, "tail": ""})
        ok = ok and passed
    return ok


def _pytest_unit() -> bool:
    r = subprocess.run([str(PY), "-m", "pytest", "tests/unit", "-rN", "--disable-warnings"],
                       cwd=str(REPO), capture_output=True, text=True, timeout=600)
    passed = r.returncode == 0
    tail = (r.stdout or "").splitlines()[-1:] 
    print(f"\n[单元测试] tests/unit {'✅ 通过' if passed else '❌ 失败'}")
    if tail:
        print(f"    {tail[0]}")
    _RESULTS.append({"name": "单元测试 tests/unit", "ok": passed, "tail": ""})
    return passed


def main() -> int:
    ap = argparse.ArgumentParser(description="项目通用检查入口（长期保留）")
    ap.add_argument("--full", action="store_true",
                    help="全量回归（里程碑门禁+覆盖率，慢）")
    ap.add_argument("--lint", action="store_true", help="仅 ruff/mypy 静态检查")
    ap.add_argument("--arch", action="store_true", help="仅架构门禁")
    ap.add_argument("--content", action="store_true", help="仅内容包校验（check_m7_content）")
    ap.add_argument("--unit", action="store_true", help="仅单元测试")
    ap.add_argument("--verify", type=str, default="", help="仅里程碑门禁（0~7，如 --verify 7）")
    ap.add_argument("--fast", action="store_true", help="冒烟模式（抽样+跳过覆盖率，配 --full）")
    ap.add_argument("--skip-lint", action="store_true", help="跳过静态门禁（run_all_tests 逃生口）")
    args = ap.parse_args()

    print("=" * 60)
    print(f"通用检查入口 check_all.py · {_NOW}")
    print("=" * 60)

    if args.full:
        extra = []
        if args.fast:
            extra.append("--fast")
        if args.skip_lint:
            extra.append("--skip-lint")
        _run("全量回归 run_all_tests", ["scripts/run_all_tests.py", *extra])
    else:
        # 无参默认：静态 + 架构 + 内容包 + 单测
        picks = [args.lint, args.arch, args.content, args.unit]
        if not any(picks):
            picks = [True, True, True, True]  # 默认快速检查
        if picks[0]:
            _lint()
        if picks[1]:
            _run("架构门禁 check_architecture", ["scripts/check_architecture.py"])
        if picks[2]:
            _run("内容包校验 check_m7_content", ["scripts/check_m7_content.py"])
        if picks[3]:
            _pytest_unit()
        if args.verify:
            n = args.verify
            _run(f"里程碑门禁 verify_m{n}", [f"scripts/verify/verify_m{n}.py"], timeout=900)

    ok_count = sum(1 for r in _RESULTS if r["ok"])
    total = len(_RESULTS)
    print("\n" + "=" * 60)
    print(f"检查汇总：{ok_count}/{total} 通过")
    for r in _RESULTS:
        print(f"  {'✅' if r['ok'] else '❌'} {r['name']}")
    print("=" * 60)

    # 归档检查报告（供复查）
    try:
        lines = [
            "# 检查报告（check_all.py 归档）",
            "",
            f"> 运行时间：{_NOW}；命令：python scripts/check_all.py"
            + (" --full" if args.full else "") + f"；结论：{ok_count}/{total} 通过",
            "",
            "| 检查项 | 结论 |",
            "|---|---|",
        ]
        for r in _RESULTS:
            lines.append(f"| {r['name']} | {'✅ 通过' if r['ok'] else '❌ 失败'} |")
        lines.append("")
        REPORT.parent.mkdir(parents=True, exist_ok=True)
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print("报告已归档：docs/verify/check_report.md")
    except Exception as e:  # noqa: BLE001
        print(f"报告写入失败：{e}")

    return 0 if ok_count == total else 1


if __name__ == "__main__":
    sys.exit(main())
