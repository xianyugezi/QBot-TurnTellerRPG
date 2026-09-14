#!/usr/bin/env python3
"""编辑器只读接口快照（批B 对拍用）。

对一组内容包调用编辑器**只读**入口（模块树 / 条目列表 / 条目详情 / 条目索引 / 引用候选 /
包列表），输出确定性 JSON；供 `scripts/compare_field_meta_migration.py` 在
「基线 995e91b」与「当前工作树」之间逐字节对拍。

用法（脚本自身可从任意树运行；`qbot_rpg` 用 PYTHONPATH 指向目标树）：

    PYTHONPATH= .venv/bin/python scripts/editor_readonly_snapshot.py veinborn test_demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List


def _all_modules(nodes: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for n in nodes:
        out.append(str(n["module"]))
        out.extend(_all_modules(n.get("children", [])))
    return out


def snapshot(pack: str, root: Path) -> Dict[str, Any]:
    """六个只读入口的输出快照（对拍口径与批A 单测一致）。"""
    from qbot_rpg.web import api

    mods = api.list_modules(pack, root=root)
    declared = _all_modules(mods["modules"])
    snap: Dict[str, Any] = {
        "list_packs": api.list_packs(root=root),
        "modules": mods,
        "index": api.entry_index(pack, root=root),
    }
    for mod in declared:
        entries = api.list_entries(pack, mod, root=root)
        snap[f"entries/{mod}"] = entries
        if entries["entries"]:
            snap[f"detail/{mod}"] = api.entry_detail(
                pack, mod, entries["entries"][0]["id"], root=root)
    pack_dir = api._pack_dir(pack, root)
    index = api._PackView(pack_dir, api._manifest(pack_dir)).name_index()
    for target in sorted(index)[:3]:
        snap[f"refs/{target}"] = api.ref_options(pack, target, root=root)
    return snap


def snapshot_all(packs: List[str], root: Path | None = None) -> Dict[str, Any]:
    from qbot_rpg.web import api

    base = root if root is not None else Path(api.repo_root()) / "content"
    return {pack: snapshot(pack, base) for pack in packs}


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="编辑器只读接口快照")
    parser.add_argument("packs", nargs="+", help="内容包名")
    args = parser.parse_args(argv)
    data = snapshot_all(args.packs)
    sys.stdout.write(json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
