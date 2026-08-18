#!/usr/bin/env python3
"""一键回归入口（细化_5d_测试体系总纲 §3，唯一官方回归入口）。

模式：
  无参           全量回归（当前仅 M0 已实现；M1~M6 标记未实现，进阶段后接入）
  --only m0      只跑 verify_m0.py（里程碑过滤）
  --only unit    只跑 unit 单测
  --fast         冒烟模式（跳过抽查/抽样收缩）
退出码 0 = 全绿。
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
PY = REPO.parent / ".venv" / "bin" / "python"
VERIFY = REPO / "verify" / "verify_m0.py"

# 里程碑 → verify 脚本（M1~M6 尚未实现，置 None 标记）
MILESTONES: dict[str, Path | None] = {
    "m0": VERIFY,
    "m1": None,  # M1 战斗核心（细化 1a/1b/1c/1d/1g）—— 后续接入
    "m2": None,  # M2 怪物体系（1e/1f/1g4）
    "m3": None,  # M3 地图副本时间（2a 系）
    "m4": None,  # M4 指令系统（2b/4f/3c/3d）
    "m5": None,  # M5 生活生产（2c 系）
    "m6": None,  # M6 数据框架（5a/5b/4c/4d/4e/6 系）
}
LAYER_PATHS = {
    "unit": ["tests/unit"],
    "contract": ["tests/contract"],
    "e2e": ["tests/contract/test_e2e_smoke.py", "tests/contract/test_3f_patch.py"],
}


def _pytest(paths: list[str], *, report: bool = False) -> int:
    # 不用 -q：该环境捕获下 -q 会吞掉 "N passed" 汇总行
    cmd = [str(PY), "-m", "pytest", "-rN", "--disable-warnings", *paths]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True)
    tail = "\n".join((r.stdout + r.stderr).splitlines()[-1:]).strip()
    if report or r.returncode != 0:
        print(f"  [{'通过' if r.returncode == 0 else '失败'}] pytest {paths} → {tail}")
    return r.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="QBot-TurnTellerRPG 一键回归")
    ap.add_argument("--only", default="", help="过滤：m0~m6 / unit / contract / e2e / datapack / fault")
    ap.add_argument("--fast", action="store_true", help="冒烟模式（抽查收缩）")
    args = ap.parse_args()

    print("=" * 62)
    print("QBot-TurnTellerRPG 一键回归（细化_5d §3）")
    print("=" * 62)

    fail = False
    only = args.only.lower() if args.only else ""

    if only in MILESTONES:
        script = MILESTONES[only]
        if script is None:
            print(f"[未实现] {only} 里程碑 verify 脚本尚未实现（后续里程碑接入）")
            return 0
        print(f"运行 {script.name} ...")
        r = subprocess.run([str(PY), str(script)], cwd=str(REPO))
        fail = r.returncode != 0
    elif only in LAYER_PATHS:
        print(f"运行 {only} 层 ...")
        fail = _pytest(LAYER_PATHS[only], report=True) != 0
    else:
        # 全量：L1~L4 + 已实现里程碑 verify（M0）+ 覆盖率提示
        print("\n[阶段 1] 金字塔单测（L1 unit / L3 contract / L4 e2e）")
        for name, paths in LAYER_PATHS.items():
            if _pytest(paths) != 0:
                fail = True
        print("\n[阶段 2] 里程碑 verify")
        for key, script in MILESTONES.items():
            if script is None:
                print(f"  [未实现] {key}（后续接入）")
                continue
            print(f"  [运行] {key} → {script.name}")
            r = subprocess.run([str(PY), str(script)], cwd=str(REPO))
            fail = fail or (r.returncode != 0)
        print("\n[阶段 3] 覆盖率核算（engine/+content/ ≥80%）：见 verify_m0 §5 估算口径")

    print("\n" + "=" * 62)
    print("回归结论：" + ("全绿（exit 0）" if not fail else "存在失败（exit 非 0）"))
    print("=" * 62)
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(main())
