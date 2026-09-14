#!/usr/bin/env python3
"""探针包构建/校验入口（E3 样本 · ``content/<pack>/scripts/build.py``）。

约定（框架只认入口，不规定内部结构）：

    python scripts/run_pack_build.py --pack zz_probe_ext --check

``--check`` = **只校验、不写盘**：校验本包 ``manifest.json`` / 数据模块 JSON /
``commands.json`` 声明与 handler 齐备，并复用框架整包校验（若可导入）→ 打印摘要；
退出码 ``0`` = 通过，``1`` = 有问题（人话列出）。

本样本没有「生成阶段」（探针包数据即最终产物），故默认与 ``--check`` 同为只读校验。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Sequence, Set, Tuple

#: 本包根目录（scripts/ 的上一级）；不依赖运行时参数。
PACK_ROOT = Path(__file__).resolve().parents[1]


def _read_json(path: Path) -> Tuple[Any, Optional[str]]:
    """读 JSON：成功 → (数据, None)；失败 → (None, 人话错误)。"""
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except (OSError, ValueError) as exc:
        return None, f"{path.name} 读取/解析失败：{type(exc).__name__}: {exc}"


def _declared_functions(path: Path) -> Set[str]:
    """静态取 ``ext/commands.py`` 的顶层函数名（不执行包代码）。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: Set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
    return names


def check() -> int:
    """只读校验本包数据 + 打印摘要；返回退出码（0 通过 / 1 有问题）。"""
    problems: List[str] = []
    print(f"[build] 包目录：{PACK_ROOT}")

    # ① manifest.json
    manifest, err = _read_json(PACK_ROOT / "manifest.json")
    if err:
        problems.append(err)
        manifest = {}
    if not isinstance(manifest, dict):
        problems.append("manifest.json 顶层必须是对象")
        manifest = {}
    modules = manifest.get("modules")
    if not isinstance(modules, list):
        problems.append("manifest.modules 必须是数组")
        modules = []
    print(
        f"[build] manifest：name={manifest.get('name')!r} "
        f"version={manifest.get('version')!r} modules={len(modules)}"
    )

    # ② 声明的数据模块文件（合法 JSON）
    ok_modules = 0
    for name in modules:
        _body, module_err = _read_json(PACK_ROOT / f"{name}.json")
        if module_err:
            problems.append(module_err)
        else:
            ok_modules += 1
    print(f"[build] 数据模块：{ok_modules}/{len(modules)} 个文件为合法 JSON")

    # ③ commands.json 声明 ↔ ext/commands.py handler 齐备
    decl, decl_err = _read_json(PACK_ROOT / "commands.json")
    if decl_err:
        problems.append(decl_err)
        decl = {}
    commands = decl.get("commands", []) if isinstance(decl, dict) else []
    if not isinstance(commands, list):
        problems.append("commands.json.commands 必须是数组")
        commands = []
    impl = PACK_ROOT / "ext" / "commands.py"
    funcs: Set[str] = set()
    if impl.is_file():
        try:
            funcs = _declared_functions(impl)
        except (OSError, SyntaxError) as exc:
            problems.append(f"ext/commands.py 无法解析：{type(exc).__name__}: {exc}")
    missing = [
        str(c.get("handler")) for c in commands
        if not isinstance(c, dict) or c.get("handler") not in funcs
    ]
    if missing:
        problems.append(f"ext/commands.py 缺少 handler：{sorted(set(missing))}")
    handler_state = "齐备" if not missing else "缺失"
    print(f"[build] commands.json：{len(commands)} 条声明，handler {handler_state}")

    # ④ 复用框架整包校验（可选：经 scripts/run_pack_build.py 运行时可用）
    try:
        from qbot_rpg.testing import validate_pack_data
    except Exception:  # noqa: BLE001 —— 无框架环境时降级为本地结构校验
        validate_pack_data = None  # type: ignore[assignment]
    if validate_pack_data is not None:
        validation = validate_pack_data(PACK_ROOT)
        print(f"[build] 框架整包校验：{validation.summary}")
        problems.extend(f"整包校验：{line}" for line in validation.errors)
        for line in validation.warnings:
            print(f"[build] 黄提示：{line}")
    else:
        print("[build] 框架整包校验：跳过（qbot_rpg 不可导入；请经 run_pack_build.py 运行）")

    if problems:
        print(f"[build] ✗ 校验未通过：{len(problems)} 个问题")
        for item in problems:
            print(f"  - {item}")
        return 1
    print("[build] ✓ 校验通过（只读；未写盘）")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI 入口：``--check`` = 只校验不写盘（本样本默认即校验）。"""
    parser = argparse.ArgumentParser(
        prog="build.py",
        description="探针包构建入口（E3 样本；--check 只校验不写盘）",
    )
    parser.add_argument("--check", action="store_true", help="只校验不写盘")
    args = parser.parse_args(sys.argv[1:] if argv is None else list(argv))
    if not args.check:
        print("[build] 提示：本包无生成阶段，默认即只读校验（等价 --check）")
    return check()


if __name__ == "__main__":
    raise SystemExit(main())
