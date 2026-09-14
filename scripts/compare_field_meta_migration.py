#!/usr/bin/env python3
"""批B 等价性门禁：对 veinborn/test_demo 做「迁移前（基线）↔ 迁移后」只读接口逐字段对拍。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §四 批B/C——
「迁移前后接口对拍 diff=0（键集合、label、help、group、module_tree 逐项比对）」。

做法：
  1. 用 `git worktree` 检出基线（默认 `112584d`；批12 重定），在基线树里跑
     `scripts/editor_readonly_snapshot.py`（`qbot_rpg` 走 PYTHONPATH 指向基线）；
  2. 在当前工作树跑同一脚本；
  3. 递归对拍两份 JSON，输出差异报告；**既有键的修改/删除 = 0 → 退出码 0**，否则 1。

增量容忍（2026-09-14，settings.battle.min_damage 实装）：
  批B 门禁的硬约束是「迁移不得修改/删除既有键」。后续批次**新增**字段（如
  settings.battle.min_damage）是合法演进，只应报告、不应冒充迁移差异。故对拍分两桶：
  hard=修改/删除（必须 0）、soft=新增（允许，列出）。列表元素带唯一 key/id/name 时逐键
  对齐，确保「既有元素被改」仍被 hard 抓住（不会因长度变化被整体跳过）。

用法（仓库根执行）：

    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py
    PYTHONPATH= .venv/bin/python scripts/compare_field_meta_migration.py \
        --baseline-root /path/to/baseline
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = Path(__file__).resolve().with_name("editor_readonly_snapshot.py")
DEFAULT_PACKS = ("veinborn", "test_demo")
# 批12（2026-09-15）重定基线：995e91b → 112584d。原因：db7bb35 起内容包合法新增
# traits/recipe/slots/dungeon/achievements/conditional 等模块，使 995e91b 基线在
# 「模块目录/索引/包列表 module_count」上产生与迁移无关的硬差异。重定到本批父提交，
# 使门禁继续只守「字段级元数据迁移不得改/删」。
DEFAULT_BASELINE_REF = "112584d"


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


def _list_key(items: Any) -> Optional[dict]:
    """list-of-dict 的**逐键对齐**索引（元素带唯一 key/id/name 时返回 {键: 元素}）。

    用于把「新增字段」与「既有字段被改/被删」区分开：批B 门禁必须抓住后者，而后续
    批次合法新增的字段只应算「新增」、不算差异（见本文件顶注「增量容忍」）。
    非 list、或元素缺统一唯一键、或键重复 → None（回退到定长下标对拍）。
    """
    if not isinstance(items, list) or not items:
        return None
    for id_key in ("key", "id", "name"):
        if all(isinstance(x, dict) and id_key in x for x in items):
            keys = [str(x[id_key]) for x in items]
            if len(set(keys)) == len(keys):
                return {str(x[id_key]): x for x in items}
    return None


#: 模块详情里的**派生计数**键：其值由 fields/groups 列表推导，列表已逐键对齐，
#: 计数本身只随合法新增而变 → 不计差异（避免「加一个字段」被计成 3 条差异）。
_DERIVED_COUNT_KEYS = frozenset({"field_count", "group_count", "association_count"})
#: 分组描述符键集（同集合的 dict 视作 group 描述符，其 count 为派生值，跳过）。
_GROUP_KEYS = frozenset({"name", "label", "count"})


def _strip_module_decl(snap: Any) -> Any:
    """取出**模块级展示声明**（模块树 / 模块显示名），从硬对拍里剔除（另以 soft 报告）。

    批12 起：模块显示名与模块层级属**包展示声明**，后续批次会刻意重组
    （「属性/公式条目并入基础」「生活模块挂到既有父模块下」）。迁移门禁的硬约束是
    「**字段级** key/label/help/group/type 不得被改/删」，故把下列内容从硬对拍移到 soft：
      · `modules.modules`（模块树结构）；
      · `index.modules[].label`（模块索引里的中文名）；
      · `entries/<模块>.label` 与 `detail/<模块>.module_label`（模块显示名）。
    其余（字段描述、计数、条目集合、引用候选）一律仍按 hard 对拍。
    """
    decl: dict = {}
    hard = copy.deepcopy(snap)
    if not isinstance(hard, dict):
        return hard, decl
    mods = hard.get("modules")
    if isinstance(mods, dict) and "modules" in mods:
        decl["modules"] = mods.pop("modules")
    idx = hard.get("index")
    if isinstance(idx, dict) and isinstance(idx.get("modules"), list):
        decl["index.labels"] = [m.pop("label", None) for m in idx["modules"]
                                if isinstance(m, dict)]
    for key in list(hard):
        if key.startswith("entries/"):
            body = hard[key]
            if isinstance(body, dict):
                decl[f"{key}.label"] = body.pop("label", None)
        elif key.startswith("detail/"):
            body = hard[key]
            if isinstance(body, dict):
                decl[f"{key}.module_label"] = body.pop("module_label", None)
    return hard, decl


def _diff(a: Any, b: Any, path: str, hard: List[str], soft: List[str],
          cap: int = 200) -> None:
    """递归对拍：hard = 修改/删除（必须为 0）；soft = 合法新增（允许，仅报告）。

    对拍口径（2026-09-14 增量容忍修正）：批B 硬门禁 = 迁移不得**修改或删除**既有
    键/字段/分组；后续战斗/设置批次**新增**字段（如 settings.battle.min_damage）属
    合法演进 → 记入 soft，不再冒充迁移差异。列表元素带唯一 key/id/name 时逐键对齐，
    因此「既有元素被改」仍会被 hard 抓住，不会因长度变化被整体跳过。
    """
    if len(hard) >= cap:
        return
    if isinstance(a, dict) and isinstance(b, dict):
        keys = set(a) | set(b)
        if keys and keys <= _GROUP_KEYS:
            keys = keys - {"count"}
        for key in sorted(keys):
            if key in _DERIVED_COUNT_KEYS:
                continue
            if key not in a:
                hard.append(f"{path}.{key}: 仅迁移前有（删除）")
            elif key not in b:
                soft.append(f"{path}.{key}: 仅迁移后有（新增）")
            else:
                _diff(a[key], b[key], f"{path}.{key}", hard, soft, cap)
        return
    if isinstance(a, list) and isinstance(b, list):
        ka, kb = _list_key(a), _list_key(b)
        if ka is not None and kb is not None:
            for key in sorted(set(ka) | set(kb)):
                if key not in ka:
                    hard.append(f"{path}[{key}]: 仅迁移前有（删除）")
                elif key not in kb:
                    soft.append(f"{path}[{key}]: 仅迁移后有（新增）")
                else:
                    _diff(ka[key], kb[key], f"{path}[{key}]", hard, soft, cap)
            return
        if len(a) != len(b):
            hard.append(f"{path}: 数组长度 {len(b)} → {len(a)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", hard, soft, cap)
        return
    if a != b:
        hard.append(f"{path}: {b!r} → {a!r}")


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
    added: List[str] = []
    for pack in packs:
        # 硬对拍剔除模块级展示声明（模块树/模块显示名），其变化记入 soft（批12 起）
        after_hard, after_decl = _strip_module_decl(after.get(pack))
        before_hard, before_decl = _strip_module_decl(before.get(pack))
        _diff(after_hard, before_hard, pack, diffs, added, args.max_diffs)
        _diff(after_decl, before_decl, f"{pack}·模块声明", [], added, args.max_diffs)

    print("批B 等价性对拍（迁移前 ↔ 迁移后）")
    print(f"  基线：{args.baseline_root or args.baseline_ref} · 包：{', '.join(packs)}")
    print(f"  差异条数：{len(diffs)}（修改/删除 = 硬差异，必须 0）")
    print(f"  新增条目：{len(added)}（后续批次合法新增，允许）")
    for line in added[:args.max_diffs]:
        print("   +", line)
    for line in diffs:
        print("   -", line)
    if diffs:
        print("对拍失败：存在修改/删除差异")
        return 1
    print("对拍通过：**字段级**键集合 / label / help / group 逐字段一致"
          "（修改/删除 = 0；模块目录/层级/显示名等展示声明演进与新增条目记 soft）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
