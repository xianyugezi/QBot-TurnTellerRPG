#!/usr/bin/env python3
"""批B 等价性门禁：对 veinborn/test_demo 做「迁移前（基线）↔ 迁移后」只读接口逐字段对拍。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C——
「迁移前后接口对拍 diff=0（键集合、label、help、group、module_tree 逐项比对）」。

做法：
  1. 用 `git worktree` 检出基线（默认 `995e91b`），在基线树里跑
     `scripts/editor_readonly_snapshot.py`（`qbot_rpg` 走 PYTHONPATH 指向基线）；
  2. 在当前工作树跑同一脚本；
  3. 递归对拍两份 JSON，输出差异报告；**0 差异 → 退出码 0**，否则 1。

用法（仓库根执行）：

    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py
    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py \
        --baseline-root /path/to/baseline
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).resolve().with_name("editor_readonly_snapshot.py")
DEFAULT_PACKS = ("veinborn", "test_demo")
DEFAULT_BASELINE_REF = "995e91b"


def _env(root: Path) -> dict:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("PYTHONSAFEPATH", None)
    return env


def _snapshot(root: Path, packs: List[str]) -> Any:
    proc = subprocess.run(
        [sys.executable, str(SNAPSHOT), *packs],
        cwd=str(root), env=_env(root), capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"快照执行失败（{root}）：\n{proc.stderr}")
    return json.loads(proc.stdout)


class _Baseline:
    def __init__(self, root: Optional[Path], ref: str) -> None:
        self._tmp: Optional[Path] = None
        if root is not None:
            self.root = root
        else:
            import importlib.util
            import tempfile
            spec = importlib.util.spec_from_file_location(
                "migrate_pack_field_meta", SNAPSHOT.with_name("migrate_pack_field_meta.py"))
            mig = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
            spec.loader.exec_module(mig)  # type: ignore[union-attr]
            self._mig = mig
            self._tmp = Path(tempfile.mkdtemp(prefix="packmeta-cmp-"))
            wt = self._tmp / "repo"
            subprocess.run(["git", "worktree", "add", "--detach", str(wt), ref],
                           cwd=str(REPO_ROOT), check=True, capture_output=True, text=True)
            self.root = wt

    def close(self) -> None:
        if self._tmp is not None:
            subprocess.run(["git", "worktree", "remove", "--force", str(self.root)],
                           cwd=str(REPO_ROOT), capture_output=True, text=True)
            try:
                self._tmp.rmdir()
            except OSError:
                pass


def _diff(a: Any, b: Any, path: str, out: List[str], cap: int = 200) -> None:
    if len(out) >= cap:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for key in sorted(set(a) | set(b)):
            if key not in a:
                out.append(f"{path}.{key}: 仅迁移后有")
            elif key not in b:
                out.append(f"{path}.{key}: 仅迁移前有")
            else:
                _diff(a[key], b[key], f"{path}.{key}", out, cap)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 数组长度 {len(b)} → {len(a)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", out, cap)
        return
    if a != b:
        out.append(f"{path}: {b!r} → {a!r}")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="批B 迁移前后只读接口对拍")
    parser.add_argument("--pack", action="append", dest="packs")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--baseline-root", default=None)
    parser.add_argument("--max-diffs", type=int, default=200)
    args = parser.parse_args(argv)
    packs = args.packs or list(DEFAULT_PACKS)

    baseline = _Baseline(Path(args.baseline_root) if args.baseline_root else None,
                         args.baseline_ref)
    try:
        before = _snapshot(baseline.root, packs)
        after = _snapshot(REPO_ROOT, packs)
    finally:
        baseline.close()

    diffs: List[str] = []
    for pack in packs:
        _diff(after.get(pack), before.get(pack), pack, diffs, args.max_diffs)

    print("批B 等价性对拍（迁移前 ↔ 迁移后）")
    print(f"  基线：{args.baseline_root or args.baseline_ref} · 包：{', '.join(packs)}")
    print(f"  差异条数：{len(diffs)}")
    for line in diffs:
        print("   -", line)
    if diffs:
        print("对拍失败：存在差异")
        return 1
    print("对拍通过：diff = 0（键集合 / label / help / group / module_tree 逐字段一致）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
