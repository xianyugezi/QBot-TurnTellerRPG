#!/usr/bin/env python3
"""消息模板宽度校验器（手机QQ 14 全角封顶 · 2026-09-12 实机标定）。

规则来源：docs/消息模板重构/00_方案与规范_v1.md §三。
- 宽度单位 = 半角当量（全角字符/宽字符 = 2、其余 = 1）；单行安全预算 B = 28（14 全角）。
  实机标定（2026-09-12）：14 全角完全显示、15 全角折行。
- 结构化行：静态部分宽度 > B → FAIL；把占位符按估算宽补上后 > B → WARN（需人工核大数值场景）。
- 豁免：meta.prose_keys 登记的 key 整条跳过；行内含 meta.prose_placeholders 占位符的行跳过
  （介绍类文本允许自然折行）。

用法：
  .venv/bin/python scripts/check_template_width.py                 # 校验仓库默认表
  .venv/bin/python scripts/check_template_width.py --table <path>  # 校验指定表文件
  .venv/bin/python scripts/check_template_width.py --quiet         # 只出汇总

退出码：0 = 通过（可能含 WARN）；1 = 存在 FAIL；2 = 表不可读/结构非法。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import Any, Dict, List, Tuple

# 单行安全预算（半角当量）：14 全角（2026-09-12 用户实机标定：「14字」完全显示、「15字」折行）
BUDGET_HALF = 28

# 占位符估算宽（半角当量）：仅用于 WARN 提示；未列出的按 DEFAULT_ESTIMATE。
DEFAULT_ESTIMATE = 6
PLACEHOLDER_ESTIMATES: Dict[str, int] = {
    "name": 8, "item": 8, "target": 8, "job": 8, "skill": 8, "title": 8,
    "damage": 7, "gold": 7, "coins": 7, "exp": 8, "level": 3, "count": 4,
    "amount": 6, "hp": 10, "mp": 10, "cur": 8, "max": 8, "index": 4,
    "seq": 4, "num": 4, "qty": 4, "time": 10, "location": 8,
    "base": 4, "bonus": 4, "temp": 4,
}

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z0-9_]+)\}")
_HALF_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]")

DEFAULT_TABLE = (
    Path(__file__).resolve().parents[1] / "qbot_rpg" / "core" / "templates" / "template_table.json"
)


def char_half_width(ch: str) -> int:
    """单字符半角当量：宽/全角（W/F/A）=2，其余=1。"""
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F", "A") else 1


def text_half_width(s: str) -> int:
    """字符串半角当量（换行符不计）。"""
    return sum(char_half_width(ch) for ch in s if ch != "\n")


def _placeholder_est(name: str) -> int:
    return PLACEHOLDER_ESTIMATES.get(name, DEFAULT_ESTIMATE)


def load_table(path: Path) -> Dict[str, Any]:
    doc = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("templates"), dict):
        raise ValueError(f"表结构非法（缺 templates dict）：{path}")
    return doc


def scan(path: Path) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """校验表文件，返回 (fails, warns)。

    fails: 静态宽 > B 的结构化行；warns: 计入占位符估算后 > B 的行（人工核）。
    每条 = {key, line_no, half, line, reason}。
    """
    doc = load_table(path)
    meta_raw = doc.get("meta")
    meta: Dict[str, Any] = meta_raw if isinstance(meta_raw, dict) else {}
    prose_keys = set(meta.get("prose_keys") or {})
    prose_phs = set(meta.get("prose_placeholders") or [])
    fails: List[Dict[str, Any]] = []
    warns: List[Dict[str, Any]] = []
    for key, text in doc["templates"].items():
        if not isinstance(text, str) or key in prose_keys:
            continue
        for i, line in enumerate(text.split("\n"), start=1):
            if not line.strip():
                continue
            phs = _PLACEHOLDER_RE.findall(line)
            if any(p in prose_phs for p in phs):
                continue  # 介绍类行（内嵌描述文本）豁免
            static = _PLACEHOLDER_RE.sub("", line)
            w_static = text_half_width(static)
            w_est = w_static + sum(_placeholder_est(p) for p in phs)
            rec = {"key": key, "line_no": i, "half": w_static,
                   "half_est": w_est, "line": line}
            if w_static > BUDGET_HALF:
                fails.append(rec)
            elif phs and w_est > BUDGET_HALF:
                warns.append(rec)
    return fails, warns


def main(argv: List[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="消息模板宽度校验（手机QQ 14 全角封顶）")
    ap.add_argument("--table", default=str(DEFAULT_TABLE), help="模板表 JSON 路径")
    ap.add_argument("--quiet", action="store_true", help="只输出汇总")
    args = ap.parse_args(argv)
    path = Path(args.table)
    if not path.exists():
        print(f"[check_template_width] 表文件不存在：{path}")
        return 2
    try:
        fails, warns = scan(path)
    except (json.JSONDecodeError, ValueError) as exc:
        print(f"[check_template_width] 表不可读：{exc}")
        return 2
    total = len(load_table(path)["templates"])
    if not args.quiet:
        for rec in fails[:50]:
            print(
                f"[FAIL] {rec['key']} L{rec['line_no']} "
                f"静态 {rec['half']}/28半角：{rec['line']!r}"
            )
        for rec in warns[:50]:
            print(
                f"[WARN] {rec['key']} L{rec['line_no']} "
                f"估算 {rec['half_est']}/28半角：{rec['line']!r}"
            )
    print(
        f"[check_template_width] 表内 {total} 条：FAIL {len(fails)} / WARN {len(warns)} "
        f"（预算 {BUDGET_HALF} 半角=14 全角）"
    )
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
