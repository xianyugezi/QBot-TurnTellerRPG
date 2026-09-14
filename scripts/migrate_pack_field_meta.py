#!/usr/bin/env python3
"""批B 迁移脚本：从基线框架 `field_meta.py` 程序化导出包专属展示元数据。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md` §二/§三/§四（批B）。

做三件事（均为程序化导出，不手抄）：

1. `--gen-structure`：从基线（默认 `995e91b`）的 `*_CHILD_LABELS` 表生成
   `qbot_rpg/content/field_meta_child_structure.py`——**只保留子字段结构**（哪些键存在、
   是 obj 还是 list-of-obj），中文名/说明一律不写进框架；
2. 默认模式：把基线框架的「有效字段表」与「去掉展示文案的结构表」逐节点对拍，
   取**差异**写成 `content/<包>/field_meta.json` 的 `field_labels` / `field_help`（含嵌套）
   与 `group_labels`，并复制 manifest 的 `module_labels` / `module_tree` 做统一承载；
3. `--check`：只比对、不落盘；若磁盘内容与导出不一致 → 退出码 1（幂等门禁）。

设计要点：
  · 唯一来源 = 基线框架表（不是手写清单）；脚本不写死任何包名以外的业务键；
  · 结构仍留在框架（`field_meta_child_structure.py`），包只承载纯展示文案；
  · 输出确定性排序（模块/键均排序），可重复运行（幂等）。

用法（仓库根执行）：

    PYTHONPATH= .venv/bin/python scripts/migrate_pack_field_meta.py --gen-structure
    PYTHONPATH= .venv/bin/python scripts/migrate_pack_field_meta.py
    PYTHONPATH= .venv/bin/python scripts/migrate_pack_field_meta.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTENT = REPO_ROOT / "content"
STRUCTURE_MODULE = REPO_ROOT / "qbot_rpg" / "content" / "field_meta_child_structure.py"
DEFAULT_PACKS: Tuple[str, ...] = ("veinborn", "test_demo")
DEFAULT_BASELINE_REF = "995e91b"
SCHEMA_VERSION = 1

# 在基线代码里运行：构造 (有效字段表, 结构表, 子结构 spec)，JSON 输出到 stdout。
_BASELINE_DUMP = r'''
import dataclasses
import json
from typing import Any, Mapping

from qbot_rpg.content import field_meta as fm
from qbot_rpg.content.models import FieldMeta


def fm_to_spec(f: FieldMeta) -> Any:
    if f.type == "list" and f.element is not None and f.element.children:
        return {"__list__": {k: fm_to_spec(c) for k, c in f.element.children.items()}}
    if f.children:
        return {k: fm_to_spec(c) for k, c in f.children.items()}
    return None


def to_spec(v: Any) -> Any:
    if isinstance(v, str):
        return None
    if isinstance(v, FieldMeta):
        return fm_to_spec(v)
    if isinstance(v, Mapping):
        return {k: to_spec(s) for k, s in v.items() if k not in ("_label", "_help")}
    return None


def from_spec(s: Any) -> Any:
    if s is None:
        return ""
    if isinstance(s, Mapping):
        if "__list__" in s:
            return fm._soft_list("", {k: from_spec(v) for k, v in s["__list__"].items()})
        return {k: from_spec(v) for k, v in s.items()}
    return ""


def ser(fields: Mapping[str, FieldMeta]) -> Any:
    return {
        str(k): {
            "label": f.label,
            "help": f.help,
            "group": f.group,
            "type": f.type,
            "soft_label": bool(f.soft_label),
            "children": ser(f.children) if f.children else {},
            "element": (ser(f.element.children)
                        if (f.element is not None and f.element.children) else None),
        }
        for k, f in fields.items()
    }


def ser_module(m: Any) -> Any:
    return {
        "fields": ser(m.fields),
        "group_labels": {str(k): str(v) for k, v in m.group_labels.items()},
        "value_meta": ser(m.value_meta.children)
        if (m.value_meta is not None and m.value_meta.children) else None,
    }


# 子结构 spec（*_CHILD_LABELS 表按模块名生成）
child_spec = {}
for _name in dir(fm):
    if _name.endswith("_CHILD_LABELS"):
        child_spec[_name[: -len("_CHILD_LABELS")].lower()] = to_spec(getattr(fm, _name))

_spec_by_id = {id(getattr(fm, n)): to_spec(getattr(fm, n))
               for n in dir(fm) if n.endswith("_CHILD_LABELS")}

eff = fm.default_field_meta_table()

_orig_field = fm._decorate_field_meta
_orig_group = fm._group_declaration


def _patched_field(fields, groups, labels, child_labels=None, helps=None, child_helps=None):
    spec = _spec_by_id.get(id(child_labels), None)
    inner = from_spec(spec) if spec is not None else None
    return _orig_field(fields, groups, {}, inner, None, None)


fm._decorate_field_meta = _patched_field
fm._group_declaration = lambda defs, labels: _orig_group(defs, {})
try:
    base = fm.default_field_meta_table()
finally:
    fm._decorate_field_meta = _orig_field
    fm._group_declaration = _orig_group

out = {
    "child_spec": child_spec,
    "effective": {str(m): ser_module(eff.module(m)) for m in eff.modules},
    "structural": {str(m): ser_module(base.module(m)) for m in base.modules},
}
print(json.dumps(out, ensure_ascii=False, sort_keys=False))
'''


# -------------------------------------------------------------------------------------
# 基线解析（worktree 或显式 root）
# -------------------------------------------------------------------------------------
def _baseline_env(root: Path) -> Dict[str, str]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(root)
    env.pop("PYTHONSAFEPATH", None)
    return env


def _run_baseline_dump(root: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        [sys.executable, "-c", _BASELINE_DUMP],
        cwd=str(root), env=_baseline_env(root),
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise SystemExit(f"基线代码执行失败（{root}）：\n{proc.stderr}")
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:  # pragma: no cover - 防御
        raise SystemExit(f"基线 dump 不是合法 JSON：{exc}\n{proc.stdout[:500]}")


class _Baseline:
    """基线根目录：显式给出，或临时 worktree（用完清理）。"""

    def __init__(self, root: Optional[Path], ref: str) -> None:
        self._tmp: Optional[str] = None
        if root is not None:
            self.root = root
        else:
            self._tmp = tempfile.mkdtemp(prefix="packmeta-baseline-")
            wt = Path(self._tmp) / "repo"
            subprocess.run(
                ["git", "worktree", "add", "--detach", str(wt), ref],
                cwd=str(REPO_ROOT), check=True, capture_output=True, text=True,
            )
            self.root = wt

    def close(self) -> None:
        if self._tmp is not None:
            subprocess.run(["git", "worktree", "remove", "--force", str(self.root)],
                           cwd=str(REPO_ROOT), capture_output=True, text=True)
            self.root = Path(self.root)
            try:
                self.root.parent.rmdir()
            except OSError:
                pass
            self._tmp = None


# -------------------------------------------------------------------------------------
# 差异计算（有效表 vs 结构表）
# -------------------------------------------------------------------------------------
def _diff_node(eff: Mapping[str, Any], base: Mapping[str, Any],
               labels: Dict[str, Any], helps: Dict[str, Any],
               where: str) -> None:
    for key, ne in eff.items():
        nb = base.get(key)
        if nb is None:
            raise SystemExit(
                f"结构表缺少基线节点 {where}{key}：包声明无法表达新增结构，"
                f"请确认 field_meta_child_structure.py 与基线一致")
        sub_l: Dict[str, Any] = {}
        sub_h: Dict[str, Any] = {}
        if ne["label"] != nb["label"]:
            sub_l["_label"] = ne["label"]
        if ne["help"] != nb["help"]:
            sub_h["_help"] = ne["help"]
        if ne["children"] or nb["children"]:
            _diff_node(ne["children"], nb["children"], sub_l, sub_h, f"{where}{key}.")
        ele, bel = ne["element"], nb["element"]
        if ele is not None:
            _diff_node(ele, bel if bel is not None else {}, sub_l, sub_h, f"{where}{key}[].")
        if sub_l:
            # 只差自身中文名（无子差异）→ 压成纯字符串，包声明更贴近「键: 中文名」。
            labels[key] = sub_l["_label"] if set(sub_l) == {"_label"} else sub_l
        if sub_h:
            helps[key] = sub_h["_help"] if set(sub_h) == {"_help"} else sub_h


def _manifest(pack: str) -> Dict[str, Any]:
    return json.loads((CONTENT / pack / "manifest.json").read_text(encoding="utf-8"))


def build_pack_decl(pack: str, dump: Mapping[str, Any]) -> Dict[str, Any]:
    manifest = _manifest(pack)
    modules: List[str] = [m for m in manifest.get("modules", []) if isinstance(m, str)]
    effective = dump["effective"]
    structural = dump["structural"]
    field_labels: Dict[str, Any] = {}
    field_help: Dict[str, Any] = {}
    group_labels: Dict[str, Dict[str, str]] = {}
    for mod in modules:
        if mod not in effective:
            continue
        e = effective[mod]
        b = structural[mod]
        labels: Dict[str, Any] = {}
        helps: Dict[str, Any] = {}
        _diff_node(e["fields"], b["fields"], labels, helps, f"{mod}.")
        if e.get("value_meta") is not None:
            vl: Dict[str, Any] = {}
            vh: Dict[str, Any] = {}
            _diff_node(e["value_meta"], b.get("value_meta") or {}, vl, vh, f"{mod}[value].")
            if vl:
                labels.update(vl)
            if vh:
                helps.update(vh)
        if labels:
            field_labels[mod] = labels
        if helps:
            field_help[mod] = helps
        if e["group_labels"]:
            group_labels[mod] = dict(e["group_labels"])
    decl: Dict[str, Any] = {"schema_version": SCHEMA_VERSION}
    mod_labels = manifest.get("module_labels")
    if isinstance(mod_labels, Mapping) and mod_labels:
        decl["module_labels"] = {str(k): str(v) for k, v in sorted(mod_labels.items())}
    mod_tree = manifest.get("module_tree")
    if mod_tree:
        decl["module_tree"] = mod_tree
    decl["field_labels"] = field_labels
    decl["field_help"] = field_help
    decl["group_labels"] = group_labels
    return decl


def _json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


# -------------------------------------------------------------------------------------
# 结构模块生成
# -------------------------------------------------------------------------------------
_STRUCTURE_HEADER = '''"""包展示元数据下放（批B）自动生成：子字段**结构**声明（无任何展示文案）。

由 `scripts/migrate_pack_field_meta.py --gen-structure` 从基线框架 `field_meta.py` 的
`*_CHILD_LABELS` 表程序化导出。**请勿手改**；框架只提供结构，中文名/说明在各包的
`content/<包>/field_meta.json` 里声明。

表示法：
  · `None`              → 叶子键（存在，无子结构、无文案）；
  · `{key: ...}`        → obj 容器（子键递归）；
  · `{"__list__": {…}}` → list-of-obj 容器（元素子键递归）。
"""

# ruff: noqa: E501  （自动生成：结构 dict 的 pprint 行宽可能超限）

from __future__ import annotations

from typing import Any, Dict

# 模块名 → 子字段结构（模块名由 `*_CHILD_LABELS` 变量名小写化而来）。
CHILD_SPEC: Dict[str, Dict[str, Any]] = '''

_STRUCTURE_TAIL = '''
__all__ = ["CHILD_SPEC"]
'''


def write_structure(spec: Mapping[str, Any], check: bool) -> bool:
    import pprint
    body = pprint.pformat({str(k): spec[k] for k in sorted(spec)},
                          width=100, sort_dicts=False)
    text = _STRUCTURE_HEADER + body + "\n" + _STRUCTURE_TAIL
    if check:
        current = STRUCTURE_MODULE.read_text(encoding="utf-8") if STRUCTURE_MODULE.exists() else ""
        return current == text
    STRUCTURE_MODULE.write_text(text, encoding="utf-8")
    return True


# -------------------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------------------
def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="批B 包展示元数据下放迁移脚本")
    parser.add_argument("--pack", action="append", dest="packs",
                        help="内容包名（可重复；缺省 veinborn/test_demo）")
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF,
                        help="基线 git ref（缺省 995e91b）")
    parser.add_argument("--baseline-root", default=None,
                        help="直接指定基线仓库根（缺省用 git worktree 检出 --baseline-ref）")
    parser.add_argument("--gen-structure", action="store_true",
                        help="生成 qbot_rpg/content/field_meta_child_structure.py")
    parser.add_argument("--check", action="store_true",
                        help="只校验磁盘内容与导出是否一致（不写入；不一致退出码 1）")
    args = parser.parse_args(argv)

    packs = tuple(args.packs) if args.packs else DEFAULT_PACKS
    baseline = _Baseline(Path(args.baseline_root) if args.baseline_root else None,
                         args.baseline_ref)
    try:
        dump = _run_baseline_dump(baseline.root)
        ok = True
        if args.gen_structure:
            same = write_structure(dump["child_spec"], args.check)
            ok = ok and same
            if not args.check:
                print(f"[structure] 写入 {STRUCTURE_MODULE.relative_to(REPO_ROOT)}"
                      f"（{len(dump['child_spec'])} 个模块）")
            elif not same:
                print("[structure] 与磁盘不一致", file=sys.stderr)
        if not args.gen_structure:
            for pack in packs:
                decl = build_pack_decl(pack, dump)
                text = _json_text(decl)
                path = CONTENT / pack / "field_meta.json"
                stats = (len(decl["field_labels"]), len(decl["field_help"]),
                         len(decl["group_labels"]))
                if args.check:
                    current = path.read_text(encoding="utf-8") if path.exists() else ""
                    if current != text:
                        print(f"[{pack}] 与磁盘不一致：{path}", file=sys.stderr)
                        ok = False
                    else:
                        print(f"[{pack}] OK（模块 {stats[0]}/{stats[1]}/{stats[2]}）")
                else:
                    path.write_text(text, encoding="utf-8")
                    print(f"[{pack}] 写入 {path.relative_to(REPO_ROOT)}"
                          f"（labels {stats[0]} / help {stats[1]} / groups {stats[2]} 模块）")
        return 0 if ok else 1
    finally:
        baseline.close()


if __name__ == "__main__":
    raise SystemExit(main())
