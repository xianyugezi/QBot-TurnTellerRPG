"""编辑器重写批B · 迁移等价性门禁（veinborn/test_demo 迁移前 ↔ 迁移后 diff=0）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C。

本用例**调用** `scripts/compare_field_meta_migration.py`：它用 `git worktree` 检出基线
`f7d9c25`（批14 重定；`46baff3` 因对象子字段 `readonly→objform` 与 `slot` 展示层下拉
而产生与迁移无关的硬差异），在基线树与当前树各跑一遍 `scripts/editor_readonly_snapshot.py`（模块树 /
条目列表 / 条目详情 / 条目索引 / 引用候选 / 包列表），递归对拍并输出差异报告。
**既有键的修改/删除 = 0** 才算通过——这是本批「展示元数据下放」不改行为的硬门禁。

增量容忍（2026-09-14，settings.battle.min_damage 实装）：后续批次**新增**字段属合法
演进，只报告、不计入差异；门禁仍抓「既有字段被改/被删」（列表逐 key 对齐）。

无 git / 无基线 ref 的环境自动跳过（脚本仍可手工执行）。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compare_field_meta_migration.py"
BASELINE_REF = "f7d9c25"
CONTENT = REPO / "content"


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, text=True)


def _have_baseline() -> bool:
    if not (REPO / ".git").exists():
        return False
    if _git("rev-parse", "--git-dir").returncode != 0:
        return False
    return _git("rev-parse", "--verify", f"{BASELINE_REF}^{{commit}}").returncode == 0


def _pack_dirs(root: Path) -> set:
    """内容根下含 manifest.json 的包目录名（动态发现，不写死任何包名）。"""
    if not root.is_dir():
        return set()
    return {d.name for d in root.iterdir()
            if d.is_dir() and (d / "manifest.json").is_file()}


def _sync_new_packs_to(baseline_root: Path) -> None:
    """把当前 content/ 里基线没有的包原样补进基线树。

    批D 起 content/ 会新增探针包；`list_packs`（全包名册）因此合法地多一项，而本门禁是
    **逐包**等价性。补进基线后两侧名册一致，`veinborn`/`test_demo` 的逐字段仍须 0 差异
    （口径不放松）。不写死新包名——按「当前有、基线没有」动态发现。
    """
    base_content = baseline_root / "content"
    for name in sorted(_pack_dirs(CONTENT) - _pack_dirs(base_content)):
        shutil.copytree(CONTENT / name, base_content / name)


def test_field_meta_migration_is_behaviour_preserving() -> None:
    """对拍迁移前后编辑器只读接口：逐字段 diff 必须为 0。"""
    if not _have_baseline():
        pytest.skip(
            "无 git 工作树或基线 ref，跳过对拍"
            "（可用 scripts/compare_field_meta_migration.py 手工跑）")
    with tempfile.TemporaryDirectory(prefix="packmeta-mig-") as tmp:
        wt = Path(tmp) / "repo"
        add = _git("worktree", "add", "--detach", str(wt), BASELINE_REF)
        assert add.returncode == 0, add.stderr
        try:
            _sync_new_packs_to(wt)
            proc = subprocess.run(
                [sys.executable, str(SCRIPT), "--baseline-ref", BASELINE_REF,
                 "--baseline-root", str(wt)],
                cwd=str(REPO), capture_output=True, text=True, timeout=600,
            )
        finally:
            _git("worktree", "remove", "--force", str(wt))
    assert proc.returncode == 0, (
        "批B 迁移对拍存在差异（应 0）：\n" + proc.stdout[-4000:] + "\n" + proc.stderr[-2000:])
    assert "差异条数：0" in proc.stdout, proc.stdout[-4000:]
