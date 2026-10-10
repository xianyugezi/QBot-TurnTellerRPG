#!/usr/bin/env python3
"""文档一致性门禁（scripts/check_docs_consistency.py）——**只查硬事实，不查内容**。

背景（2026-10-10 · 日研 10-07 族 3「文档漂移小闭环」）：外部只读研究/AI 开工反复被
**过时文档**带偏（实例：README 曾写「web 编辑器已于 2026-09-13 移除」、细化文档份数
三处互异 72/76/87、索引 74 条链接 100% 悬空）。本脚本把这三类可机械验证的事实变成门禁。

检查项（三项，全部为确定性判定）：
  D-01  份数声明一致：README 目录树与《细化规划总索引》声明的份数 == 磁盘实测份数
  D-02  索引链接可达：《docs/细化规划总索引.md》内所有相对 `*.md` 链接目标存在
  D-03  归档索引齐全：`docs/审查/审计与方案/INDEX.md` 表格列出的文件都存在

**不检查**：文档内容是否正确 / 文档是否过时（内容判断交人工与审查流程）；
不新增任何声明文件——只说「你写下的数字与路径，与磁盘是否一致」。

退出码：0 = 全部一致；1 = 有不一致（逐条打印）；2 = 仓库路径不可读。
用法：python scripts/check_docs_consistency.py [--path 仓库根]
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Tuple

# 份数声明口径：README 声明的目录 -> (目录名, 文件名 glob, 说明)
README_COUNT_RULES: Tuple[Tuple[str, str, str], ...] = (
    (r"细化/\s+实现契约 (\d+) 份", "细化", "*.md"),
    (r"规划/\s+实现规划 (\d+) 份", "规划", "*.md"),
    (r"审查/\s+幻觉审查 (\d+)", "审查", "幻觉审查*.md"),
    (r"审查/\s+幻觉审查 \d+ \+ 覆盖审计 (\d+)", "审查", "覆盖审计*.md"),
    (r"审查报告/\s+里程碑复查报告 (\d+) 份", "审查报告", "*.md"),
    (r"实现依据：`docs/细化/`（(\d+) 份契约）", "细化", "*.md"),
)
INDEX_COUNT_RULE = r"共 (\d+) 份"


def _count(root: Path, dirname: str, pattern: str) -> int:
    return len(list((root / "docs" / dirname).rglob(pattern)))


def check_counts(root: Path, problems: List[str]) -> int:
    """D-01：README 与索引声明的份数 vs 磁盘实测。返回检查项数。"""
    readme = root / "README.md"
    index = root / "docs" / "细化规划总索引.md"
    n = 0
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for pattern, dirname, glob in README_COUNT_RULES:
            for m in re.finditer(pattern, text):
                declared = int(m.group(1))
                actual = _count(root, dirname, glob)
                n += 1
                if declared != actual:
                    problems.append(
                        f"D-01 README 声明 docs/{dirname}（{glob}）= {declared} 份，"
                        f"磁盘实测 {actual} 份（声明串：{m.group(0)[:48]!r}）")
    else:
        problems.append("D-01 缺 README.md")
    if index.is_file():
        text = index.read_text(encoding="utf-8")
        for m in re.finditer(INDEX_COUNT_RULE, text):
            declared = int(m.group(1))
            actual = _count(root, "细化", "*.md")
            n += 1
            if declared != actual:
                problems.append(
                    f"D-01 索引声明「共 {declared} 份」，磁盘实测 docs/细化/*.md = {actual} 份")
    else:
        problems.append("D-01 缺 docs/细化规划总索引.md")
    return n


def check_index_links(root: Path, problems: List[str]) -> int:
    """D-02：索引内相对 md 链接目标存在。返回链接数。"""
    index = root / "docs" / "细化规划总索引.md"
    if not index.is_file():
        problems.append("D-02 缺 docs/细化规划总索引.md")
        return 0
    links = sorted(set(re.findall(r"\]\(([^)#]+\.md)\)", index.read_text(encoding="utf-8"))))
    for link in links:
        if not (index.parent / link).exists():
            problems.append(f"D-02 索引链接悬空：{link}（相对 {index.parent.relative_to(root)}）")
    return len(links)


def check_scheme_index(root: Path, problems: List[str]) -> int:
    """D-03：审计与方案 INDEX 表格列出的文件存在。返回条目数。"""
    ix = root / "docs" / "审查" / "审计与方案" / "INDEX.md"
    if not ix.is_file():
        problems.append("D-03 缺 docs/审查/审计与方案/INDEX.md")
        return 0
    rows = re.findall(r"^\|\s*`([^`]+)`", ix.read_text(encoding="utf-8"), re.M)
    for row in rows:
        if not (ix.parent / row).exists():
            problems.append(f"D-03 INDEX 列出但文件不存在：{row}")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="文档一致性门禁（硬事实三项）")
    ap.add_argument("--path", default="", help="仓库根（默认 = 脚本所在目录的父目录）")
    args = ap.parse_args()
    root = Path(args.path).resolve() if args.path else Path(__file__).resolve().parent.parent
    if not (root / "docs").is_dir():
        print(f"仓库路径不可读：{root}")
        return 2

    problems: List[str] = []
    n_count = check_counts(root, problems)
    n_links = check_index_links(root, problems)
    n_rows = check_scheme_index(root, problems)

    print("文档一致性门禁（scripts/check_docs_consistency.py）")
    print(f"  仓库：{root}")
    print(f"  D-01 份数声明：{n_count} 处比对")
    print(f"  D-02 索引链接：{n_links} 条")
    print(f"  D-03 归档索引：{n_rows} 条")
    if problems:
        print(f"\n发现 {len(problems)} 处不一致：")
        for p in problems:
            print(f"  - {p}")
        print("\n提示：改数字/改链接即可（口径 = 磁盘实测；改完重跑本脚本）。")
        return 1
    print("\n一致：声明的份数与链接全部与磁盘相符。DOCS-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
