"""编辑器重写批B · 迁移等价性门禁（veinborn/test_demo 迁移前 ↔ 迁移后 diff=0）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C。

本用例**调用** `scripts/compare_field_meta_migration.py`：它用 `git worktree` 检出基线
`995e91b`，在基线树与当前树各跑一遍 `scripts/editor_readonly_snapshot.py`（模块树 /
条目列表 / 条目详情 / 条目索引 / 引用候选 / 包列表），递归对拍并输出差异报告。
0 差异才算通过——这是本批「展示元数据下放」不改行为的硬门禁。

无 git / 无基线 ref 的环境自动跳过（脚本仍可手工执行）。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compare_field_meta_migration.py"
BASELINE_REF = "995e91b"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def _have_baseline() -> bool:
    if not (REPO / ".git").exists():
        return False
    if _git("rev-parse", "--git-dir").returncode != 0:
        return False
    return _git("rev-parse", "--verify", f"{BASELINE_REF}^{{commit}}").returncode == 0


def test_field_meta_migration_is_behaviour_preserving() -> None:
    """对拍迁移前后编辑器只读接口：逐字段 diff 必须为 0。"""
    if not _have_baseline():
        pytest.skip(
            "无 git 工作树或基线 ref，跳过对拍"
            "（可用 scripts/compare_field_meta_migration.py 手工跑）")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--baseline-ref", BASELINE_REF],
        cwd=str(REPO), capture_output=True, text=True, timeout=600,
    )
    assert proc.returncode == 0, (
        "批B 迁移对拍存在差异（应 0）：\n" + proc.stdout[-4000:] + "\n" + proc.stderr[-2000:])
    assert "差异条数：0" in proc.stdout, proc.stdout[-4000:]
