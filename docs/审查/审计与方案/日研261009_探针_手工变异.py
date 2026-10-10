"""手工变异探针（E-20261009-02 的最小实测版）——只读研究，跑完必还原。

对 4 个高价值变异点逐个「改一行 → 跑事件相关测试 → 还原（git checkout）」，
产出「测试敏感性」实测数据：哪些变异被现有关卡抓住、哪些存活（= 断言盲区）。
不引入 mutmut，不改 pyproject，不动 Python 版本要求。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

# 仓库根由脚本位置反推（docs/审查/审计与方案/<本文件> → parents[3]），不硬编码绝对路径
REPO = Path(__file__).resolve().parents[3]
PY = str(REPO / ".venv/bin/python")

PROBE_TESTS = [
    "tests/unit/test_batch84_event_dispatch_status.py",
    "tests/unit/test_batch84_status_expire_dispatch.py",
    "tests/unit/test_batch51_trigger_ownership.py",
    "tests/unit/test_event_dispatcher.py",
    "tests/unit/test_event_dispatcher_status.py",
    "tests/unit/test_batch24_advance_on_kill.py",
]

MUTANTS = [
    ("M1 登记表：turn_end 误标未接入（有派发点→dispatched=False）",
     "qbot_rpg/data/event_points.py",
     'EventPoint("turn_end", True,',
     'EventPoint("turn_end", False,'),
    ("M2 校验器：Y-24 静默死效果提示失效（elif 恒假）",
     "qbot_rpg/content/validator.py",
     "elif not EVENT_POINT_INDEX[tv].dispatched:",
     "elif False:  # MUTANT"),
    ("M3 状态过期：删掉 tick 到期的 status_lose 派发",
     "qbot_rpg/core/effects.py",
     'return _dispatch_status_event("status_lose", status_id, side, ctx, runtime)',
     "return []  # MUTANT"),
    ("M4 战斗：删掉击杀事件 on_kill 派发",
     "qbot_rpg/core/battle.py",
     'self._dispatch_event("on_kill", killer)',
     "pass  # MUTANT"),
]


def run_tests() -> tuple[bool, str]:
    proc = subprocess.run(
        [PY, "-m", "pytest", "-q", "-p", "no:cacheprovider", *PROBE_TESTS],
        cwd=REPO, capture_output=True, text=True, timeout=900,
    )
    tail = (proc.stdout or "").strip().splitlines()
    summary = tail[-1] if tail else "(no output)"
    return proc.returncode == 0, summary


def main() -> None:
    rows = []
    for label, rel, old, new in MUTANTS:
        path = REPO / rel
        original = path.read_text(encoding="utf-8")
        if original.count(old) != 1:
            rows.append((label, rel, f"跳过：锚点命中 {original.count(old)} 次（非 1）", ""))
            continue
        path.write_text(original.replace(old, new), encoding="utf-8")
        try:
            passed, summary = run_tests()
        finally:
            subprocess.run(["git", "checkout", "--", rel], cwd=REPO, check=True)
        rows.append((label, rel, "抓住（测试红）" if not passed else "存活（测试仍绿）", summary))

    print("\n=== 变异探针结果（探针集 = 6 个事件相关测试文件）===")
    for label, rel, verdict, summary in rows:
        print(f"- {label}\n    verdict: {verdict} | {summary}")

    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                           capture_output=True, text=True).stdout.strip()
    print("\n工作区状态（应为空 = 已全部还原）:", "干净" if not dirty else dirty)


if __name__ == "__main__":
    main()
