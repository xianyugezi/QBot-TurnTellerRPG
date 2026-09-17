"""编辑器重写批B · 迁移等价性门禁（veinborn/test_demo 迁移前 ↔ 迁移后 diff=0）。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C。

本用例**调用** `scripts/compare_field_meta_migration.py`：它用 `git worktree` 检出基线
（批29 重定；批28 已把空壳键 `transfer_allowed` 从框架侧删除，批29 用户拍板后再把内容包
`veinborn` 的两处残留——`enhance.json` 数据键 + `field_meta.json` 展示名——**一并清理**，
使 `enhance.settings` 的展示子字段不再出现该键；此后基线树与当前树**逐字段 diff=0**，
**删除项 = 0、无既有 label/help/group 严格键改动**），在基线树与当前树各跑一遍
`scripts/editor_readonly_snapshot.py`（模块树 / 条目列表 / 条目详情 / 条目索引 / 引用候选 /
包列表），递归对拍并输出差异报告。

批15 语义化定稿（对拍口径，实现见 `compare_snapshots` / `_diff`）：
  ① **删除任一项 → 红**（hard）；② **任一值变化 → 红**（hard），唯一例外是派生展示键
  `control` / `widget` / `block_layout` / `number_step`（呈现层推导，删除它们仍红）；
  ③ **新增项 → 允许**（soft），但必须显式打印「新增 N 项（功能演化）」且逐条列出；
  ④ **迁移相关字段严格相等**：`label` / `help` / `group` 与模块声明（`module_labels` /
  `module_tree` → `modules.modules`、`index.modules[].label`、`entries/*.label`、
  `detail/*.module_label`）逐字段严格断言，**新增 / 删除 / 改值全红**。

`test_gate_semantics_*` 是**自证测试**：人为造删除 / 值变化 → 必须红；造新增 → 必须绿。
无 git / 无基线 ref 的环境自动跳过集成对拍（`compare_snapshots` 自证测试不依赖 git）。
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "compare_field_meta_migration.py"
BASELINE_REF = "4b9d82d"
CONTENT = REPO / "content"


def _load_gate() -> Any:
    """按路径加载门禁脚本（scripts/ 不是包，不能 import）。"""
    spec = importlib.util.spec_from_file_location("compare_field_meta_migration", SCRIPT)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _descriptor(**over: Any) -> Dict[str, Any]:
    """一个最小字段描述符（对拍用的合成样本；不写死任何真实模块/字段名）。"""
    d: Dict[str, Any] = {"key": "f", "label": "字段", "help": "说明", "group": "默认",
                         "control": "objform", "widget": "obj", "type": "obj"}
    d.update(over)
    return d


def _snap(fields: List[Dict[str, Any]], **module_over: Any) -> Dict[str, Any]:
    body: Dict[str, Any] = {"fields": fields, "module_label": "模块"}
    body.update(module_over)
    return {"p": {"detail/m": body}}


def _run(before: Dict[str, Any], after: Dict[str, Any]) -> Tuple[List[str], List[str]]:
    return _load_gate().compare_snapshots(before, after, ["p"], cap=1000)


# ---------------------------------------------------------------------------
# 自证：删除 / 值变化 → 红；新增 → 绿（且必须列出）
# ---------------------------------------------------------------------------
def test_gate_semantics_deletion_is_red() -> None:
    before = _snap([_descriptor(), _descriptor(key="g", label="另一个")])
    after = _snap([_descriptor(key="g", label="另一个")])
    hard, soft = _run(before, after)
    assert hard, "删除字段必须判红"
    assert any("仅迁移前有（删除）" in h for h in hard)


def test_gate_semantics_value_change_is_red() -> None:
    before = _snap([_descriptor()])
    after = _snap([_descriptor(label="改了")])
    hard, _ = _run(before, after)
    assert hard, "既有值变化必须判红"
    assert any(".label:" in h for h in hard)


def test_gate_semantics_addition_is_green_and_listed() -> None:
    before = _snap([_descriptor()])
    after = _snap([_descriptor(), _descriptor(key="g", label="新字段")])
    hard, soft = _run(before, after)
    assert not hard, "新增字段必须判绿"
    assert any("仅迁移后有（新增）" in s for s in soft), "新增必须逐条列出（不得静默）"


def test_gate_semantics_strict_label_addition_is_red() -> None:
    """口径 ④：迁移相关字段 `label` 在基线缺失、当前补上 → 也算红（严格断言）。"""
    before = _snap([{k: v for k, v in _descriptor().items() if k != "label"}])
    after = _snap([_descriptor()])
    hard, _ = _run(before, after)
    assert hard and any(".label:" in h and "严格断言" in h for h in hard)


def test_gate_semantics_strict_module_decl_change_is_red() -> None:
    """口径 ④：模块声明（module_labels / module_tree → modules.modules）严格相等。"""
    before = {"p": {"modules": {"modules": [{"module": "a", "label": "甲"}]}}}
    after = {"p": {"modules": {"modules": [{"module": "a", "label": "乙"}]}}}
    hard, _ = _run(before, after)
    assert hard, "模块显示名变化必须判红"


def test_gate_semantics_derived_control_change_is_green_but_deletion_is_red() -> None:
    """派生展示键（control）值变化记 soft（呈现层）；**删除**它仍判红。"""
    before = _snap([_descriptor()])
    changed = _snap([_descriptor(control="kvtable")])
    hard, soft = _run(before, changed)
    assert not hard, "control 值变化属呈现层，应记 soft"
    assert any("派生展示键" in s for s in soft)
    dropped = _snap([{k: v for k, v in _descriptor().items() if k != "control"}])
    hard2, _ = _run(before, dropped)
    assert hard2 and any(".control:" in h and "删除" in h for h in hard2)



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
    # 口径 ③：新增项必须显式计入输出（不得静默）。
    assert "新增 " in proc.stdout and "项（功能演化" in proc.stdout, proc.stdout[-2000:]
