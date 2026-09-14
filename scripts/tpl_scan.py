#!/usr/bin/env python3
"""模板分区扫描器（消息模板重构战役工具）。

用途：生成任务书/分路所需的清单——分区 key、现文案、占位符、引用点、死键候选、超宽统计。

用法：
  python scripts/tpl_scan.py                      # 全分区总览（key 数 / 超宽数）
  python scripts/tpl_scan.py --part enhance_tpl   # 某分区逐键明细（现文案/占位符/引用/死键候选）
  python scripts/tpl_scan.py --keys enhance_at_max,enhance_roll_line   # 跨分区指定键明细
  python scripts/tpl_scan.py --out /tmp/scan.txt  # 输出到文件

说明：
- 引用点扫描排除 qbot_rpg/core/templates/（分区自身定义不算引用）；死键候选仅按「全仓零引用」粗筛，
  仍需复核动态 key 构造（tpl_of(ctx, f"...") / 变量拼接）与测试引用。
- 超宽口径与 check_template_width.py 一致：全角/宽/模糊=2、其余=1（半角当量），预算 28。
"""
from __future__ import annotations

import argparse
import ast
import os
import re
from pathlib import Path
from typing import Dict, List

import unicodedata

REPO = Path(__file__).resolve().parents[1]
TDIR = REPO / "qbot_rpg" / "core" / "templates"
BUDGET_HALF = 28


def half(s: str) -> int:
    return sum(
        2 if unicodedata.east_asian_width(c) in ("W", "F", "A") else 1 for c in s if c != "\n"
    )


def load_partitions() -> Dict[str, Dict[str, str]]:
    """{分区名: {key: 文本}}"""
    out: Dict[str, Dict[str, str]] = {}
    for p in sorted(TDIR.glob("*_tpl.py")):
        src = p.read_text(encoding="utf-8")
        tree = ast.parse(src)
        best: Dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                d: Dict[str, str] = {}
                for k, v in zip(node.keys, node.values):
                    if (
                        isinstance(k, ast.Constant)
                        and isinstance(k.value, str)
                        and isinstance(v, ast.Constant)
                        and isinstance(v.value, str)
                    ):
                        d[k.value] = v.value
                    else:
                        d = {}
                        break
                if len(d) > len(best):
                    best = d
        if best:
            out[p.stem] = best
    return out


def repo_texts() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for root, dirs, files in os.walk(REPO):
        if any(x in root for x in (".git", ".venv", "__pycache__", "core/templates")):
            continue
        for fn in files:
            if fn.endswith(".py"):
                p = Path(root) / fn
                try:
                    out[str(p.relative_to(REPO))] = p.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    pass
    return out


def refs_of(key: str, texts: Dict[str, str]) -> List[str]:
    return [rel for rel, t in texts.items() if key in t]


def fmt_key(key: str, text: str, refs: List[str]) -> List[str]:
    ph = sorted(set(re.findall(r"\{([a-zA-Z0-9_]+)\}", text)))
    dead = not refs
    tag = "  【死键候选：全仓零引用】" if dead else ""
    lines = [f"{key}  (占位符: {'、'.join(ph) if ph else '无'}){tag}"]
    for ln in text.split("\n"):
        lines.append(f"    现: {ln}   [宽 {half(ln)}/28]")
    if refs:
        lines.append(f"    引用: {', '.join(refs[:4])}" + (" …" if len(refs) > 4 else ""))
    return lines


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--part", help="分区名（如 enhance_tpl）")
    ap.add_argument("--keys", help="逗号分隔的 key 列表（跨分区）")
    ap.add_argument("--out", help="输出文件（默认打印到 stdout）")
    args = ap.parse_args()

    parts = load_partitions()
    texts = repo_texts()
    chunks: List[str] = []

    if args.part:
        name = args.part[:-3] if args.part.endswith(".py") else args.part
        d = parts.get(name)
        if d is None:
            print(f"未找到分区 {name}；可选：{', '.join(sorted(parts))}")
            return 2
        long_cnt = sum(1 for v in d.values() if any(half(ln) > BUDGET_HALF for ln in v.split("\n")))
        chunks.append(f"==== {name}: {len(d)} 键 / 超宽 {long_cnt} 条 ====")
        for k, v in d.items():
            chunks.extend(fmt_key(k, v, refs_of(k, texts)))
    elif args.keys:
        want = [k.strip() for k in args.keys.split(",") if k.strip()]
        allmap = {k: (p, v) for p, d in parts.items() for k, v in d.items()}
        for k in want:
            if k not in allmap:
                chunks.append(f"{k}  【未在分区中找到】")
                continue
            parts_name, v = allmap[k]
            chunks.append(f"[{parts_name}]")
            chunks.extend(fmt_key(k, v, refs_of(k, texts)))
    else:
        for name, d in sorted(parts.items()):
            long_cnt = sum(
                1 for v in d.values() if any(half(ln) > BUDGET_HALF for ln in v.split("\n"))
            )
            chunks.append(f"{name}: {len(d)} 键 / 超宽 {long_cnt}")

    report = "\n".join(chunks)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")
        print(f"已写出 {args.out}（{len(report)} chars）")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
