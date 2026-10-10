r"""只读探针：AST 扫描事件派发调用 ↔ 现有正则扫描器对拍（E-20261009-01）。

目的：判定 tests/unit/test_batch84_event_dispatch_status.py 的正则扫描器
（`_dispatch_(?:status_)?event\(\s*["']([a-z_]+)["']`）是否存在真实漏检。
只读，不改任何生产代码。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

# 仓库根由脚本位置反推（docs/审查/审计与方案/<本文件> → parents[3]），不硬编码绝对路径
REPO = Path(__file__).resolve().parents[3]
QBOT = REPO / "qbot_rpg"

REGEX = re.compile(r"_dispatch_(?:status_)?event\(\s*[\"']([a-z_]+)[\"']")
TARGET_FUNCS = {"_dispatch_event", "_dispatch_status_event"}

regex_hits: dict[str, set[str]] = {}
ast_hits: dict[str, set[str]] = {}
ast_dynamic: list[str] = []          # 调用点存在但首参不是字符串字面量 → 正则盲区候选
ast_calls_total = 0
parse_errors: list[str] = []
target_defs: list[str] = []

for path in sorted(QBOT.rglob("*.py")):
    text = path.read_text(encoding="utf-8")
    rel = str(path.relative_to(REPO))
    for name in REGEX.findall(text):
        regex_hits.setdefault(name, set()).add(rel)

    try:
        tree = ast.parse(text, filename=rel)
    except SyntaxError as exc:  # pragma: no cover
        parse_errors.append(f"{rel}: {exc}")
        continue

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name in TARGET_FUNCS:
            target_defs.append(f"{rel}:{node.lineno} {node.name}")
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        attr = fn.attr if isinstance(fn, ast.Attribute) else (
            fn.id if isinstance(fn, ast.Name) else None)
        if attr not in TARGET_FUNCS:
            continue
        ast_calls_total += 1
        arg0 = node.args[0] if node.args else None
        if isinstance(arg0, ast.Constant) and isinstance(arg0.value, str):
            ast_hits.setdefault(arg0.value, set()).add(f"{rel}:{node.lineno}")
        elif isinstance(arg0, ast.Name):
            ast_dynamic.append(f"{rel}:{node.lineno} 变量={arg0.id}")
        elif isinstance(arg0, ast.JoinedStr):
            ast_dynamic.append(f"{rel}:{node.lineno} f-string")
        elif arg0 is None:
            ast_dynamic.append(f"{rel}:{node.lineno} 无实参")
        else:
            ast_dynamic.append(f"{rel}:{node.lineno} 其他={ast.dump(arg0)[:60]}")

print(f"AST 调用点（_dispatch_event/_dispatch_status_event 全部）: {ast_calls_total}")
print(f"AST 字面量事件名: {len(ast_hits)} 个 -> {sorted(ast_hits)}")
print(f"正则扫描事件名:   {len(regex_hits)} 个 -> {sorted(regex_hits)}")
print()
only_ast = set(ast_hits) - set(regex_hits)
only_regex = set(regex_hits) - set(ast_hits)
print(f"仅 AST 命中（正则漏检）: {sorted(only_ast) or '无'}")
print(f"仅 正则命中（AST 漏检/解析外）: {sorted(only_regex) or '无'}")
print()
print(f"动态/非字面量首参调用点（正则天然盲区）: {len(ast_dynamic)}")
for row in ast_dynamic:
    print("   ", row)
print()
print(f"被调函数定义处: {len(target_defs)}")
for row in target_defs:
    print("   ", row)
if parse_errors:
    print("解析失败:", parse_errors)

# 与唯一源表对拍（模拟 test_batch84 的断言口径）
# 用 AST 解析 event_points.py 取「声明态」，**不 import 仓库模块**——探针零依赖、可独立运行
declared_live: set[str] = set()
declared_phase2: set[str] = set()
table_tree = ast.parse((QBOT / "data" / "event_points.py").read_text(encoding="utf-8"))
for node in ast.walk(table_tree):
    if not isinstance(node, ast.Call) or getattr(node.func, "id", None) != "EventPoint":
        continue
    if not node.args or not isinstance(node.args[0], ast.Constant):
        continue
    name = node.args[0].value
    second = node.args[1] if len(node.args) > 1 else None
    flag = second.value if isinstance(second, ast.Constant) else None
    if not isinstance(name, str):
        continue
    (declared_live if flag else declared_phase2).add(name)

print()
print(f"表 declared_live   == 正则 actual ? {declared_live == set(regex_hits)}")
print(f"表 declared_live   == AST  actual ? {declared_live == set(ast_hits)}")
print(f"表 declared_phase2 与两者交集: regex={sorted(declared_phase2 & set(regex_hits)) or '空'}"
      f"  ast={sorted(declared_phase2 & set(ast_hits)) or '空'}")
