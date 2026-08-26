"""全仓渲染输出 emoji 纪律扫描（M5-10 · 用户拍板「不用 emoji」）。

依据：m5_shared_contract §4.1——除 ✅/❌ 功能性标记 + 排版符号（| → × / 「」【】）外，
渲染输出不含任何 emoji 字符；数据型功能图标一律降级纯文本。
本测试扫描 qbot_rpg/ 下所有 .py 的字符串字面量（ast 解析，跳过 docstring 与注释），
断言无非白名单 emoji。豁免名单（description 性/非渲染字符串）在 WHITELIST 登记。
"""
from __future__ import annotations

import ast
import re
import pathlib

# 非白名单 emoji 判定（U+1F000+ 补充符号 / U+2600-27BF 杂项符号 / 区域指示 / VS16 / ZWJ）
# 排除功能性标记 ✅(U+2705) ❌(U+274C)
_EMOJI = re.compile(
    r"[\U0001F000-\U0001FAFF]"
    r"|[\U00002600-\U000027BF]"
    r"|[\U0001F1E6-\U0001F1FF]"
    r"|\ufe0f"
    r"|\u200d"
)
_ALLOWED = {"\u2705", "\u274c"}  # ✅ ❌

# 豁免名单（文件:子串）：描述性/刻意保留的非渲染字符串；每项需注明理由
WHITELIST: dict[str, list[str]] = {
    # strip_icon_emoji 的 emoji 字符范围定义（检测/剥离代码本身，非渲染输出；data/emoji_sanitize.py 为 M5-10 迁移后的实现位置）
    "data/emoji_sanitize.py": ["⌀-⏿⬀-⯿🀀-🫿☀-✄✆-❋❍-➿"],
}

REPO = pathlib.Path(__file__).resolve().parents[2] / "qbot_rpg"


def _iter_strings(tree: ast.AST):
    """遍历所有字符串字面量，正确跳过 docstring（容器首语句的 Expr(Constant(str))）。"""
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            first = node.body[0] if node.body else None
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                docstring_nodes.add(id(first.value))
    for node in ast.walk(tree):
        if id(node) in docstring_nodes:
            continue
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node, node.value
        elif isinstance(node, ast.JoinedStr):
            for part in node.values:
                if isinstance(part, ast.Constant) and isinstance(part.value, str):
                    yield part, part.value


def _violations():
    out = []
    for py in sorted(REPO.rglob("*.py")):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node, value in _iter_strings(tree):
            for ch in set(value):
                if ch in _ALLOWED:
                    continue
                if _EMOJI.match(ch):
                    # 豁免名单检查
                    rel = str(py.relative_to(REPO))
                    whitelisted = any(
                        sub in value for sub in WHITELIST.get(rel, [])
                    )
                    if not whitelisted:
                        out.append((rel, node.lineno, ch, value[:60]))
    return out


def test_no_emoji_in_render_strings():
    """全仓渲染字符串零非白名单 emoji（M5 裁决「不用 emoji」）。"""
    viol = _violations()
    assert not viol, f"发现 {len(viol)} 处非白名单 emoji：\n" + "\n".join(
        f"  {f}:L{l} [{c}] {v}" for f, l, c, v in viol[:20]
    )


def test_fixtures_no_emoji_icon():
    """内容包 fixture 的 icon 字段值不含 emoji（数据型功能图标降级纯文本）。"""
    import json
    fixtures = REPO.parent / "tests" / "fixtures" / "packs" / "legal"
    bad = []
    for f in fixtures.rglob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        text = json.dumps(data, ensure_ascii=False)
        for ch in set(text):
            if ch in _ALLOWED:
                continue
            if _EMOJI.match(ch):
                bad.append((str(f.relative_to(fixtures)), ch))
    assert not bad, f"fixture 含 emoji icon：{bad[:10]}"
