#!/usr/bin/env python3
"""框架本体 mypy 存量基线门禁（scripts/check_mypy_baseline.py）· 2026-10-10 分档口径。

**口径**（用户 2026-10-10 拍板「分档」，见 `docs/verify/lint_baseline.md`）：
  · ruff 全仓 —— **必拦**（2026-10-10 已清零，新增即红）；
  · mypy **框架本体 `qbot_rpg/**`** —— **存量基线豁免 + 新增必拦**（本脚本）；
  · mypy `tests/**` + `scripts/**` —— **只告警不阻断**，债务清单归档
    `docs/verify/mypy_debt.txt`（由 `scripts/run_all_tests.py` 阶段0 写出），按批收敛。

基线坐标：`文件 × 错误码 → 计数`（`docs/verify/mypy_framework_baseline.json`）。
**为什么按「文件×码计数」而不是整文件豁免**：整文件 `ignore_errors` 会把该文件**将来**的新错误
一起放行（= 骗作者）；计数基线只放行**已登记的那几处**，任何新增/加重都会红。

退出码：0 = 无新增（可通过）；1 = 有新增长（打印明细）；2 = 无法运行 mypy / 读基线。
用法：
  python scripts/check_mypy_baseline.py            # 比对
  python scripts/check_mypy_baseline.py --update   # 重算并写回基线（存量收敛后更新）
  python scripts/check_mypy_baseline.py --list     # 只打印当前存量清单
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BASELINE = REPO / "docs" / "verify" / "mypy_framework_baseline.json"
MYPY_TARGET = "qbot_rpg"
_ERR = re.compile(r"^([^:]+\.py):(\d+): error: .*?(?:\[([a-z-]+)\])?\s*$")


def run_mypy(target: str) -> str:
    exe = REPO / ".venv" / "bin" / "mypy"
    r = subprocess.run([str(exe), target], cwd=REPO, capture_output=True, text=True, timeout=1800)
    return r.stdout + r.stderr


def collect(output: str) -> Counter[tuple[str, str]]:
    """(文件, 错误码) -> 计数。"""
    found: Counter[tuple[str, str]] = Counter()
    for line in output.splitlines():
        m = _ERR.match(line.strip())
        if m:
            found[(m.group(1), m.group(3) or "?")] += 1
    return found


def load_baseline() -> dict[tuple[str, str], int]:
    if not BASELINE.is_file():
        return {}
    data = json.loads(BASELINE.read_text(encoding="utf-8"))
    return {(k.split("::")[0], k.split("::")[1]): int(v)
            for k, v in data.get("entries", {}).items()}


def save_baseline(found: Counter[tuple[str, str]], total_errors: int) -> None:
    entries = {f"{f}::{c}": n for (f, c), n in sorted(found.items())}
    payload = {
        "note": ("框架本体 mypy 存量基线（文件::错误码 → 计数）。"
                 "由 scripts/check_mypy_baseline.py --update 生成；"
                 "放行已登记存量，任何新增/加重即红（口径见 docs/verify/lint_baseline.md）"),
        "target": MYPY_TARGET,
        "total_errors": total_errors,
        "entries": entries,
    }
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="框架本体 mypy 存量基线门禁")
    ap.add_argument("--update", action="store_true", help="重算并写回基线")
    ap.add_argument("--list", action="store_true", help="只打印当前存量清单")
    args = ap.parse_args(argv)

    output = run_mypy(MYPY_TARGET)
    if "error:" not in output and "Success" not in output:
        print("无法运行 mypy（.venv/bin/mypy 缺失或崩溃）：")
        print(output[-800:])
        return 2

    found = collect(output)
    total = sum(found.values())
    baseline = load_baseline()

    if args.update:
        save_baseline(found, total)
        print(f"基线已更新：{BASELINE.relative_to(REPO)}"
              f"（{len(found)} 个 文件×码 组合，共 {total} 处）")
        return 0

    if args.list:
        files_n = len({f for f, _ in found})
        print(f"框架本体 mypy 存量（{MYPY_TARGET}）：{total} 处 / {files_n} 文件")
        for (f, c), n in sorted(found.items(), key=lambda kv: -kv[1]):
            print(f"  {f} [{c}] ×{n}")
        return 0

    if not baseline:
        print(f"基线文件缺失或为空：{BASELINE.relative_to(REPO)}；先跑 --update 建立基线。")
        return 2

    increased = sorted(
        ((f, c, found.get((f, c), 0), n) for (f, c), n in baseline.items()
         if found.get((f, c), 0) > n))
    decreases = sorted(
        ((f, c, n, found.get((f, c), 0)) for (f, c), n in baseline.items()
         if found.get((f, c), 0) < n))

    base_total = sum(baseline.values())
    print(f"框架本体 mypy 基线门禁（{MYPY_TARGET}）：当前 {total} 处 / 基线 {base_total} 处")
    if decreases:
        print(f"  · 提示：{len(decreases)} 个组合低于基线（存量收敛，可用 --update 收紧基线）")
    if increased:
        for f, c, was, now in increased:
            print(f"  ✗ 新增/加重：{f} [{c}] {was} → {now}")
        print("\n框架本体 mypy 出现新增错误（口径：存量豁免 + 新增必拦）。")
        return 1
    print("  ✓ 通过：框架本体无新增 mypy 错误（存量已在基线登记，按批收敛）")
    return 0


if __name__ == "__main__":
    sys.exit(main())

