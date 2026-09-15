#!/usr/bin/env python3
"""一号原则自检 · 能力可见性（编辑器批13）。

判据（`docs/编辑器修改意见0915_台账与方案.md` §〇·补）：
**编辑器是框架的编辑器**——同一框架元数据下，用一个「几乎空白」的包打开编辑器，
模块 / 字段的**显示集合**应与功能齐全的包一致（差异仅体现在「有没有值 / 是否启用」）。

本脚本只读，逐包断言两件事（不写任何文件）：
  ① **模块显示集**：左栏（`list_modules` 的 modules ∪ views ∪ available）覆盖框架目录全集；
  ② **字段显示集**：对框架已登记的每个模块，包合并后的字段表 ⊇ 框架字段表（包声明只增不减）；
  ③ **段入口可见性**（批13.1）：对象型模块的**条目列表** ⊇ 框架登记的顶层段——包数据没有的
     段以「未配置态」出现，不得因缺数据而消失；多个包的段集合取差集（应只有「是否已配置」差别）。

用法：
  python scripts/editor_visibility_selfcheck.py              # 默认比对 demo_blank / veinborn
  python scripts/editor_visibility_selfcheck.py --packs demo_blank test_demo
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from qbot_rpg.content.module_catalog import FRAMEWORK_MODULE_CATALOG  # noqa: E402
from qbot_rpg.web import api  # noqa: E402

CATALOG: Set[str] = {e.module for e in FRAMEWORK_MODULE_CATALOG}


def _tree_modules(nodes: object) -> Set[str]:
    out: Set[str] = set()
    for n in nodes if isinstance(nodes, list) else []:
        if isinstance(n, dict):
            out.add(str(n.get("module")))
            out |= _tree_modules(n.get("children"))
    return out


def check_pack(pack: str, root: Path) -> Dict[str, Any]:
    """单包自检：模块显示集 / 字段显示集；返回结构化结果（不抛，记 errors）。"""
    res: Dict[str, Any] = {"pack": pack, "errors": [], "enabled": 0, "views": 0, "available": 0,
                           "covered": 0, "fields_checked": 0, "segments_checked": 0,
                           "segments": {}}
    try:
        mods = api.list_modules(pack, root=root)
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"list_modules 异常：{type(exc).__name__}: {exc}")
        return res
    shown = _tree_modules(mods.get("modules"))
    shown |= {str(v.get("module")) for v in mods.get("views") or []}
    shown |= {str(a.get("module")) for a in mods.get("available") or []}
    missing = sorted(CATALOG - shown)
    if missing:
        res["errors"].append(f"左栏未显示框架能力：{missing}")
    res["enabled"] = len(_tree_modules(mods.get("modules")))
    res["views"] = len(mods.get("views") or [])
    res["available"] = len(mods.get("available") or [])
    res["covered"] = len(shown & CATALOG)

    # 字段显示集：框架登记字段必须仍在包合并表里（包声明只增不减）
    try:
        pack_dir = api._pack_dir(pack, root)
        table = api._pack_meta_table(pack_dir)
        framework = api.default_field_meta_table()
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"字段表读取异常：{type(exc).__name__}: {exc}")
        return res
    for module, base in framework.modules.items():
        merged = table.module(module)
        if merged is None:
            res["errors"].append(f"模块 {module} 在包合并表里丢失")
            continue
        missing_keys = sorted(set(base.fields) - set(merged.fields))
        if missing_keys:
            res["errors"].append(f"模块 {module} 字段被包声明删减：{missing_keys}")
        res["fields_checked"] += len(base.fields)

    # 段入口可见性（批13.1）：对象型模块的条目列表必须覆盖框架登记的全部顶层段。
    # 未在本包声明 / 非对象型模块 → 跳过（换包行为与现状一致，不误报）。
    for module, base in framework.modules.items():
        if base.entry_type != "object":
            continue
        try:
            le = api.list_entries(pack, module, root=root)
        except Exception:  # noqa: BLE001 （未声明的对象模块 → 本包无从显示，跳过）
            continue
        entries = [e for e in (le.get("entries") or []) if isinstance(e, dict)]
        ids = [str(e.get("id")) for e in entries]
        missing = sorted(set(base.fields) - set(ids))
        if missing:
            res["errors"].append(f"段入口缺失：模块 {module} 条目列表未含框架段 {missing}")
        res["segments"][module] = {
            "ids": ids,
            "configured": [str(e.get("id")) for e in entries if not e.get("unconfigured")],
            "unconfigured": [str(e.get("id")) for e in entries if e.get("unconfigured")],
        }
        res["segments_checked"] += len(base.fields)
    return res


def _print_table(rows: List[Dict[str, Any]]) -> None:
    head = ("包名", "已启用", "视图", "未启用", "覆盖框架/全集", "字段校验", "段校验", "结果")
    printed = []
    for r in rows:
        printed.append((r["pack"], str(r["enabled"]), str(r["views"]), str(r["available"]),
                        f"{r['covered']}/{len(CATALOG)}", str(r["fields_checked"]),
                        str(r["segments_checked"]),
                        "PASS" if not r["errors"] else "FAIL"))
    widths = [max(len(head[i]), *(len(p[i]) for p in printed)) if printed else len(head[i])
              for i in range(len(head))]
    print("  ".join(h.center(widths[i]) for i, h in enumerate(head)))
    print("-" * len("  ".join(h.center(widths[i]) for i, h in enumerate(head))))
    for p in printed:
        print("  ".join(c.ljust(widths[i]) for i, c in enumerate(p)))


def _segment_diff(rows: List[Dict[str, Any]]) -> List[str]:
    """跨包段集合差集：输出人话行 + 返回差集型错误（应只有「是否已配置」差别）。

    段集合（对象型模块的条目 id 集）是「框架登记段 ∪ 包数据键」，同一框架下**必须一致**；
    各包之间只允许「已配置 / 未配置」的差别（即同一个 id 在一包有值、在另一包是空槽）。
    """
    lines: List[str] = []
    errors: List[str] = []
    present = [r for r in rows if r.get("segments")]
    all_mods: Set[str] = set()
    for r in present:
        all_mods |= set(r["segments"])
    for module in sorted(all_mods):
        packs = [r for r in present if module in r["segments"]]
        if len(packs) < 2:
            continue
        ref = packs[0]
        ref_ids = set(ref["segments"][module]["ids"])
        for r in packs[1:]:
            ids = set(r["segments"][module]["ids"])
            diff = sorted(ref_ids ^ ids)
            ca = len(ref["segments"][module]["configured"])
            ua = len(ref["segments"][module]["unconfigured"])
            cb = len(r["segments"][module]["configured"])
            ub = len(r["segments"][module]["unconfigured"])
            lines.append(
                f"  {module}: 段集合差 {diff if diff else '无'}；"
                f"{ref['pack']} 已配置 {ca} / 未配置 {ua}，"
                f"{r['pack']} 已配置 {cb} / 未配置 {ub}")
            if diff:
                errors.append(
                    f"段集合跨包不一致：{module}（{ref['pack']} vs {r['pack']}）差 {diff}")
    return lines, errors


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="编辑器一号原则自检（能力可见性）")
    parser.add_argument("--packs", nargs="*", default=["demo_blank", "veinborn"],
                        help="要比对的内容包（默认 demo_blank / veinborn）")
    parser.add_argument("--content-root", default=None, help="内容根目录（缺省 <仓库>/content）")
    args = parser.parse_args(argv)
    root = Path(args.content_root) if args.content_root else _REPO / "content"
    print("一号原则自检 · 能力可见性（空包 vs 功能齐全包）")
    rows = [check_pack(p, root) for p in args.packs]
    _print_table(rows)
    # 批13.1：段集合差集（同一框架下各包段集合应一致，差异只在「是否已配置」）。
    diff_lines, diff_errors = _segment_diff(rows)
    if diff_lines:
        print("\n段集合差集（应只有「是否已配置」的差别）：")
        for line in diff_lines:
            print(line)
    failed = [r for r in rows if r["errors"]]
    for r in failed:
        print(f"\n[FAIL] {r['pack']}：")
        for e in r["errors"]:
            print(f"  - {e}")
    for e in diff_errors:
        print(f"\n[FAIL] {e}")
    ok = not failed and not diff_errors
    print()
    print("一号原则自检：" + ("全部 PASS（空白包与功能包显示集一致）" if ok
                              else f"{len(failed)} 个包 FAIL / {len(diff_errors)} 项跨包差集 FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
