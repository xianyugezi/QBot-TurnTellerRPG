#!/usr/bin/env python3
"""G0 架构检查脚本（细化_3a §六 验收 TC-01 ~ TC-04 / 铁律 R1-R3 / D-03）。

纯 ast 静态扫描，**不 import 任何 qbot_rpg 模块** —— 零依赖可运行（脱离 NoneBot / fastapi）。
检查项（对齐细化_3a §六 覆盖矩阵 ①/②）：

  TC-01   ast 全仓扫描 qbot_rpg/{core,world,storage,content,data} 全部 .py（递归），
          断言 import 图无任何 nonebot（Import/ImportFrom 节点；含 importlib 动态加载）→ R1
  TC-02   全仓扫描 import nonebot 的文件集合，仅允许 qbot_rpg/commands/ 内 → R2
  TC-03   qbot_rpg 全包 import 图分析：
            · core/world/storage/content/data 之间无环（Kahn 拓扑）
            · commands/web 不被任何层 import
            · 依赖方向符合 §1.4 矩阵（web→{content,core,storage,data} 等，反向即违规）→ R3 / D-05
  TC-04   data/ 五类（Player/BattleSnapshot/StatusInstance/ItemInstance/WorldState）
          各定义一次（全仓唯一）且 dataclass(frozen=True) → D-03 / U1

退出码：全部通过 → 打印 ARCH-OK，exit 0；任一失败 → 打印违规清单，exit 1。
用法：python scripts/check_architecture.py [--path 仓库根]   （默认取脚本所在目录的父目录 = 仓库根）
"""
from __future__ import annotations

import argparse
import ast
import os
import sys
from typing import Dict, Iterator, List, Optional, Sequence, Set, Tuple

# 零 NoneBot 五层（TC-01 扫描范围；web 属平台无关但不在此 5 层扫描集，见细化_3a TC-01）
ZERO_NB_LAYERS: Tuple[str, ...] = ("core", "world", "storage", "content", "data")
# 依赖方向矩阵（细化_3a §1.4 / §2.2）：layer -> 允许依赖的 qbot_rpg 层
ALLOWED_DEP: Dict[str, Set[str]] = {
    "commands": {"core", "world", "storage", "content", "data"},
    "web": {"content", "core", "storage", "data"},
    "core": {"data", "content", "world", "storage"},
    "world": {"data", "storage", "content"},
    "storage": {"data"},
    "content": {"data"},
    "engine": {"data"},  # M3 时间/天气引擎（纯逻辑层；仅允许依赖 data）
    "data": set(),
    "root": set(),  # qbot_rpg/__init__.py 包元信息；不参与方向约束（M0 无业务 import）
}
# TC-04 五类（细化_3a §3.2 / D-03）
REQUIRED_TYPES: Tuple[str, ...] = (
    "Player", "BattleSnapshot", "StatusInstance", "ItemInstance", "WorldState",
)

_OK = True


def _is_falsy_constant(node: ast.AST) -> bool:
    """字面量假值（False/0/''/None）——`if False:` 死分支判定。"""
    return isinstance(node, ast.Constant) and not bool(node.value)


def _is_truthy_constant(node: ast.AST) -> bool:
    """字面量真值（True/非 0 数/非空串）。"""
    return isinstance(node, ast.Constant) and bool(node.value)


def walk_live(tree: ast.AST) -> Iterator[ast.AST]:
    """遍历 AST，跳过**字面量常假分支**的死代码（`if False: import x` 不产生真实依赖边）。

    - test 为常假常量 → 只走 orelse；常真常量 → 只走 body；否则两分支都要。
    用于 import 图 / nonebot 扫描 / 类定义归属，保证静态扫描与真实运行时一致。
    """
    stack: List[ast.AST] = [tree]
    while stack:
        node = stack.pop()
        yield node
        children: List[ast.AST]
        if isinstance(node, ast.If):
            if _is_falsy_constant(node.test):
                children = list(node.orelse)
            elif _is_truthy_constant(node.test):
                children = list(node.body)
            else:
                children = list(ast.iter_child_nodes(node))
        else:
            children = list(ast.iter_child_nodes(node))
        stack.extend(reversed(children))


def _fail(msg: str) -> None:
    global _OK
    _OK = False
    print(f"  ✗ {msg}")


def iter_qbot_py_files(repo_root: str) -> List[str]:
    """qbot_rpg/ 下全部 .py（递归，跳过 __pycache__/.venv）。"""
    pkg = os.path.join(repo_root, "qbot_rpg")
    out: List[str] = []
    for dirpath, dirnames, filenames in os.walk(pkg):
        dirnames[:] = [d for d in dirnames if d not in ("__pycache__",)]
        for fn in filenames:
            if fn.endswith(".py"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def layer_of(path: str) -> str:
    """文件所属层：qbot_rpg/<layer>/... → layer；qbot_rpg/__init__.py → root。"""
    parts = os.path.relpath(path).split(os.sep)
    for i, p in enumerate(parts):
        if p == "qbot_rpg":
            return parts[i + 1] if i + 1 < len(parts) else "root"
    return "unknown"


def _importlib_dynamic(tree: ast.Module, file: str) -> List[Tuple[str, str]]:
    """检测 importlib.import_module / __import__ 动态加载 nonebot（TC-01 强调 importlib）。"""
    hits: List[Tuple[str, str]] = []

    def _arg_str(node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        return None

    for node in walk_live(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            target_names: Optional[Tuple[str, ...]] = None
            if isinstance(fn, ast.Attribute) and isinstance(fn.value, ast.Name) and fn.value.id == "importlib" and fn.attr == "import_module":
                target_names = ("importlib.import_module",)
            elif isinstance(fn, ast.Name) and fn.id == "__import__":
                target_names = ("__import__",)
            if target_names is not None and node.args:
                name = _arg_str(node.args[0])
                if name and name == "nonebot" or (name and name.startswith("nonebot.")):
                    hits.append((file, f"{target_names[0]}('{name}') (2-arg/_dynamic)"))
    return hits


def find_nonebot_imports(tree: ast.Module, file: str) -> List[Tuple[str, str, int]]:
    """返回实际 import nonebot 的 (文件, 描述, 行号) 列表（Import/ImportFrom 节点 + 动态加载）。

    遍历**活代码**（walk_live 跳过 `if False:` / `if TYPE_CHECKING:` 类死分支），
    与运行时行为一致 —— 死分支里的 import 不构成真实 nonebot 依赖（R1/R2 口径）。

    P1-1（架构复查）：ImportFrom 节点同时检查 `node.module` 与符号名——
    `from nonebot import on_command` 的 module 才是 "nonebot"，只比对 alias.name
    会漏检这一契约明文点名的形态（NoneBot 插件最惯用写法）。
    """
    hits: List[Tuple[str, str, int]] = []
    for node in walk_live(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name
                if mod == "nonebot" or mod.startswith("nonebot."):
                    hits.append((file, f"import {mod}", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod == "nonebot" or mod.startswith("nonebot."):
                names = ", ".join(a.name for a in node.names)
                hits.append((file, f"from {mod} import {names}", node.lineno))
    for f, desc in _importlib_dynamic(tree, file):
        hits.append((f, desc, 0))
    return hits


def check_tc01(root: str, files: List[str]) -> None:
    """TC-01：零 NoneBot 五层无一 nonebot import（R1）。"""
    print("TC-01  零 NoneBot 五层（core/world/storage/content/data）无 nonebot import（R1）")
    violations: List[str] = []
    for file in files:
        layer = layer_of(file)
        if layer not in ZERO_NB_LAYERS:
            continue
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            violations.append(f"{file} 语法错误: {exc}")
            continue
        for _, desc, lineno in find_nonebot_imports(tree, file):
            violations.append(f"{file}:{lineno}  {desc}")
    if violations:
        for v in violations:
            _fail(f"TC-01 命中：{v}")
    else:
        print("  ✓ 通过（未发现任何 nonebot import 节点）")


def check_tc02(root: str, files: List[str]) -> None:
    """TC-02：全仓 nonebot import 仅允许 qbot_rpg/commands/ 内（R2）。"""
    print("TC-02  全仓 nonebot import 仅允许 qbot_rpg/commands/ 内（R2）")
    commands_dir = os.path.join(root, "qbot_rpg", "commands")
    offenders: List[str] = []
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            _fail(f"TC-02 语法错误：{file}: {exc}")
            continue
        hits = find_nonebot_imports(tree, file)
        for hit_file, desc, lineno in hits:
            if not os.path.dirname(hit_file).startswith(commands_dir):
                offenders.append(f"{hit_file}:{lineno}  {desc}")
    if offenders:
        for o in offenders:
            _fail(f"TC-02 越界（非 commands/）：{o}")
    else:
        print("  ✓ 通过（nonebot import 集合为空或全部位于 commands/ 内）")


# ---------------------------------------------------------------------------
# import 图解析（TC-03）
# ---------------------------------------------------------------------------
def _resolve_module(parts: Sequence[str], repo_root: str) -> Optional[str]:
    """把 qbot_rpg 模块路径点组件解析为磁盘上**真实存在**的 .py 文件；不存在 → None。

    - parts == ["qbot_rpg"]                             → qbot_rpg/__init__.py
    - parts == ["qbot_rpg", "data", "types"]            → 先 data/types.py，再 data/types/__init__.py
    - 没有任何真实文件命中 → None（**不发明兜底路径**，避免伪造依赖边/伪环）
    """
    if not parts or parts[0] != "qbot_rpg":
        return None
    pkg_root = os.path.join(repo_root, "qbot_rpg")
    if len(parts) == 1:
        return os.path.join(pkg_root, "__init__.py")
    rel = os.path.join(*parts[1:])
    for cand in (
        os.path.join(pkg_root, rel + ".py"),
        os.path.join(pkg_root, rel, "__init__.py"),
    ):
        if os.path.isfile(cand):
            return cand
    return None


def _resolve_submodule(module_parts: Sequence[str], name: str, repo_root: str) -> Optional[str]:
    """``from 模块 import name`` 时，name 若为真实子模块（如 from qbot_rpg.data import player）→ 边；否则 None。"""
    if not name or name == "*":
        return None
    return _resolve_module(list(module_parts) + [name], repo_root)


def collect_import_edges(tree: ast.Module, file: str, repo_root: str) -> List[str]:
    """返回该文件 import 的 intra-qbot_rpg 目标文件路径列表（含相对 import 解析）。"""
    pkg_depth = file.replace(repo_root, "").lstrip(os.sep).split(os.sep)
    cur_pkg = pkg_depth[:-1]  # 文件所在包（不含文件名）
    # 例如 qbot_rpg/core/player_attributes.py → ["qbot_rpg","core"]
    edges: List[str] = []
    for node in walk_live(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                t = _resolve_module(alias.name.split("."), repo_root)
                if t and t != file:
                    edges.append(t)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if not node.module:
                    continue
                module_parts: List[str] = node.module.split(".")
                base = _resolve_module(module_parts, repo_root)
                if base and base != file:
                    edges.append(base)
                # from X import name：name 若为真实子模块（from qbot_rpg.data import player）→ 加边
                for al in node.names:
                    sub = _resolve_submodule(module_parts, al.name, repo_root)
                    if sub and sub != file:
                        edges.append(sub)
            else:
                # 相对 import：node.level 往上跳；node.module 为同层子模块名（可为 None）
                up = node.level
                base_pkg = cur_pkg[: len(cur_pkg) - (up if up < len(cur_pkg) else len(cur_pkg))]
                if not base_pkg:
                    continue
                sub = node.module or ""
                cand_parts = base_pkg + ([sub] if sub else [])
                base = _resolve_module(cand_parts, repo_root)
                if base and base != file:
                    edges.append(base)
                if sub:
                    for al in node.names:
                        subb = _resolve_module(base_pkg + [sub, al.name], repo_root)
                        if subb and subb != file:
                            edges.append(subb)
    return list(dict.fromkeys(edges))  # 去重保序


def check_tc03(root: str, files: List[str]) -> None:
    """TC-03：import 图——依赖方向 + 无环 + commands/web 不被依赖（R3 / D-05）。"""
    print("TC-03  import 图：依赖方向矩阵 + 无环 + commands/web 不被依赖（R3/D-05）")
    by_file: Dict[str, Tuple[str, List[str]]] = {}  # file -> (layer, targets)
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError as exc:
            _fail(f"TC-03 语法错误：{file}: {exc}")
            continue
        by_file[file] = (layer_of(file), collect_import_edges(tree, file, root))

    layer_violations: List[str] = []
    for src, (slayer, targets) in by_file.items():
        for tgt in targets:
            tlayer = layer_of(tgt)
            if tlayer == slayer:
                continue  # 同层内部模块互引合法（§1.4 矩阵只约束跨层方向）
            if tlayer in ("commands", "web"):
                layer_violations.append(
                    f"{os.path.relpath(src)} → {os.path.relpath(tgt)}："
                    f"commands/web 被依赖（TC-03 禁止）"
                )
            else:
                allowed = ALLOWED_DEP.get(slayer)
                if allowed is not None and tlayer not in allowed:
                    layer_violations.append(
                        f"{os.path.relpath(src)}[{slayer}] → {os.path.relpath(tgt)}[{tlayer}]："
                        f"违反依赖矩阵 §1.4（{slayer} 允许: {allowed}）"
                    )

    # 有向环检测：Kahn 拓扑（文件级全图；涉零五层+root+commands/web 一并判断）
    indeg: Dict[str, int] = {f: 0 for f in files if f in by_file}
    adj: Dict[str, List[str]] = {f: [] for f in files if f in by_file}
    for src, (_, targets) in by_file.items():
        for tgt in targets:
            if tgt in adj:
                adj[src].append(tgt)
                indeg[tgt] += 1
    queue = [f for f, d in indeg.items() if d == 0]
    order: List[str] = []
    while queue:
        f = queue.pop()
        order.append(f)
        for nxt in adj.get(f, []):
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    cycled = [f for f, d in indeg.items() if d > 0]

    if layer_violations:
        for v in layer_violations:
            _fail(f"TC-03 依赖方向：{v}")
    elif cycled:
        _fail(f"TC-03 循环 import（拓扑剩余 {len(cycled)} 个节点，含环）: "
              + ", ".join(os.path.relpath(f) for f in sorted(cycled)))
    else:
        print(f"  ✓ 通过（{len(by_file)} 文件拓扑序合法、方向矩阵全绿、commands/web 无人依赖）")


def check_tc04(root: str, files: List[str]) -> None:
    """TC-04：五类各定义一次（全仓唯一）且 dataclass(frozen=True)（D-03 / U1）。"""
    print("TC-04  data/ 五类各定义一次且 frozen=True（D-03/U1）")
    found: Dict[str, List[Tuple[str, int, bool]]] = {n: [] for n in REQUIRED_TYPES}
    for file in files:
        try:
            tree = ast.parse(open(file, "r", encoding="utf-8").read(), filename=file)
        except SyntaxError:
            continue
        for node in walk_live(tree):
            if isinstance(node, ast.ClassDef) and node.name in REQUIRED_TYPES:
                frozen = False
                for dec in node.decorator_list:
                    if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Name) and dec.func.id == "dataclass":
                        for kw in dec.keywords:
                            if kw.arg == "frozen" and (isinstance(kw.value, ast.Constant) and kw.value.value is True):
                                frozen = True
                found[node.name].append((file, node.lineno, frozen))
    problems: List[str] = []
    for name in REQUIRED_TYPES:
        defs = found[name]
        in_data = [d for d in defs if layer_of(d[0]) == "data"]
        outside = [d for d in defs if layer_of(d[0]) != "data"]
        if len(defs) == 0:
            problems.append(f"{name}：未定义（data/ 必须定义一次）")
        elif len(defs) > 1:
            problems.append(f"{name}：定义 {len(defs)} 次（应唯一）: "
                            + ", ".join(f"{os.path.relpath(d[0])}:{d[1]}" for d in defs))
        elif len(in_data) != 1:
            problems.append(f"{name}：定义不在 data/ 层（{os.path.relpath(in_data[0][0]) if (in_data or outside) else '无'}）")
        elif not in_data[0][2]:
            problems.append(f"{name}：data/{os.path.relpath(in_data[0][0])}:{in_data[0][1]} 缺 dataclass(frozen=True)")
        elif outside:
            problems.append(f"{name}：data/ 之外重复定义 -> {', '.join(os.path.relpath(o[0]) for o in outside)}")
    if problems:
        for p in problems:
            _fail(f"TC-04 命中：{p}")
    else:
        print("  ✓ 通过（Player/BattleSnapshot/StatusInstance/ItemInstance/WorldState 各一次 + frozen）")


def main(argv: Optional[Sequence[str]] = None) -> int:
    global _OK
    parser = argparse.ArgumentParser(description="G0 架构检查（细化_3a TC-01~04）")
    parser.add_argument(
        "--path", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        help="仓库根目录（默认脚本父目录）",
    )
    args = parser.parse_args(argv)
    root = os.path.abspath(args.path)
    if not os.path.isdir(os.path.join(root, "qbot_rpg")):
        print(f"✗ 无效仓库根（无 qbot_rpg/）: {root}")
        return 2

    _OK = True
    files = iter_qbot_py_files(root)
    print(f"ARCH 扫描 {len(files)} 个 .py（{root}）")
    check_tc01(root, files)
    check_tc02(root, files)
    check_tc03(root, files)
    check_tc04(root, files)

    if _OK:
        print("ARCH-OK  TC-01/TC-02/TC-03/TC-04 全部通过（细化_3a 分层契约满足）")
        return 0
    print("ARCH-FAIL 存在违规，详见上方清单（质量门禁红）")
    return 1


if __name__ == "__main__":
    sys.exit(main())
