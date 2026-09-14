#!/usr/bin/env python3
"""模板表片段合并器（消息模板重构战役工具 · 批收口用）。

用法：
  python scripts/tpl_merge_fragments.py frag1.json [frag2.json ...] [--table PATH] [--dry-run]

行为：
- 读片段文件（{"rail": "...", "templates": {key: text}, "prose_keys": {key: reason},
"overwrite_keys": [key...], "removed_keys": [key...]}）；
- 把 templates 依次并入目标表 templates（重复 key 且值不同 → 报错退出，防误合并）；
  例外：key 列在片段 `overwrite_keys`（**改值片段**：如 HUD v2 行动行整句化）→ 覆盖并记数；
- `removed_keys`：从表中删除该死键（**被替代键**，如 battle_action_hint）——删除前打印原值；
- prose_keys 并入 meta.prose_keys（重复且不同 → 报错）；
- 合并后跑结构自检：宽度扫描（复用 check_template_width.scan，0 FAIL 门禁）；
- 写回表（indent=2，ensure_ascii=False），并打印汇总。

退出码：0=成功；1=合并冲突/校验失败；2=文件或表不可读。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
DEFAULT_TABLE = REPO / "qbot_rpg" / "core" / "templates" / "template_table.json"
_WIDTH = REPO / "scripts" / "check_template_width.py"
_spec = importlib.util.spec_from_file_location("check_template_width_mod", _WIDTH)
_cw = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_cw)  # type: ignore[union-attr]


def load_fragment(path: Path) -> Dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("templates"), dict):
        raise ValueError(f"片段结构非法（缺 templates）：{path}")
    return doc


def merge(table_path: Path, frag_paths: List[Path], dry_run: bool = False) -> int:
    doc = json.loads(table_path.read_text(encoding="utf-8"))
    templates = doc.setdefault("templates", {})
    meta = doc.setdefault("meta", {})
    prose = meta.setdefault("prose_keys", {})
    added: List[str] = []
    overwritten: List[str] = []
    removed: List[str] = []
    for fp in frag_paths:
        frag = load_fragment(fp)
        rail = str(frag.get("rail") or fp.name)
        overwrite = {str(k) for k in (frag.get("overwrite_keys") or ())}
        for key, text in frag["templates"].items():
            if not isinstance(text, str):
                print(f"[ERR] {rail}: {key} 非字符串值")
                return 1
            if key in templates:
                if templates[key] == text:
                    continue  # 幂等：重复合并同值 = 无害
                if key in overwrite:
                    templates[key] = text       # 改值片段：显式声明覆盖
                    overwritten.append(f"{rail}:{key}")
                    continue
                print(f"[ERR] {rail}: key 冲突且值不同：{key}")
                print(f"   旧: {templates[key]!r}")
                print(f"   新: {text!r}")
                return 1
            templates[key] = text
            added.append(f"{rail}:{key}")
        for key in (frag.get("removed_keys") or ()):
            k = str(key)
            if k in templates:
                print(f"[del] {rail}: 删除被替代键 {k}（原值 {templates[k]!r}）")
                templates.pop(k)
                removed.append(f"{rail}:{k}")
        for key, reason in (frag.get("prose_keys") or {}).items():
            if key in prose and prose[key] != reason:
                print(f"[ERR] {rail}: prose_keys 冲突：{key}")
                return 1
            if key not in prose:
                prose[key] = reason
                print(f"[prose+] {key}: {reason}")
    # 宽度自检（对「合并后内容」校验：先写临时文件再扫描，防扫到旧表）
    tmp = table_path.with_suffix(".mergecheck.json")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        fails, warns = _cw.scan(tmp)
    finally:
        tmp.unlink()
    print(f"[merge] 新增 {len(added)} / 覆盖 {len(overwritten)} / 删除 {len(removed)}"
          f" / 冲突 0 / 宽度 FAIL {len(fails)} / WARN {len(warns)}")
    if fails:
        for rec in fails[:20]:
            print(f"[FAIL] {rec['key']} L{rec['line_no']} {rec['half']}/28 {rec['line']!r}")
        return 1
    if dry_run:
        print("[dry-run] 未写盘")
        return 0
    table_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[merge] 已写回：{table_path}（表内 {len(templates)} 条）")
    return 0


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="模板表片段合并器")
    ap.add_argument("fragments", nargs="+", help="片段 JSON 路径（按顺序合并）")
    ap.add_argument("--table", default=str(DEFAULT_TABLE), help="目标表路径")
    ap.add_argument("--dry-run", action="store_true", help="不写盘，仅校验")
    args = ap.parse_args(argv)
    table = Path(args.table)
    if not table.exists():
        print(f"[merge] 表不存在：{table}")
        return 2
    frags = [Path(p) for p in args.fragments]
    for fp in frags:
        if not fp.exists():
            print(f"[merge] 片段不存在：{fp}")
            return 2
    try:
        return merge(table, frags, dry_run=args.dry_run)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[merge] 失败：{exc}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
