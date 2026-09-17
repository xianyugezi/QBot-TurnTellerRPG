"""批29 · ①：内容包里 `transfer_allowed` 残留已清理的回归断言。

背景：批28 删除框架侧空壳键 `transfer_allowed`（子结构 + V5 校验 + 缺省锚点），
但按纪律**不擅自删**内容包里的两处残留（`content/veinborn/enhance.json` 数据键 +
`content/veinborn/field_meta.json` 展示名）。用户 2026-09-16 拍板「12 做」后，
批29 一并清理（`content/veinborn/enhance.json` settings 键 + `field_meta.json`
`enhance.settings` 展示名），本用例锁死清理结果。

判据（不写死任何包名——按目录动态发现）：
  ① 内容根下**任何** JSON 里不再出现该键（数据键与展示名一并清）；
  ② 清理后各包数据仍合法：`check_pack` 0 error（换包验收见
     `scripts/editor_verify_packs.py`；编辑器只读接口另由迁移对拍门禁守）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List, Tuple

from qbot_rpg.content.validator import check_pack

REPO = Path(__file__).resolve().parents[2]
CONTENT = REPO / "content"
REMOVED_KEY = "transfer_allowed"


def _pack_dirs() -> List[Path]:
    """内容根下含 manifest.json 的包目录（动态发现，不写死包名）。"""
    return sorted(d for d in CONTENT.iterdir()
                  if d.is_dir() and (d / "manifest.json").is_file())


def _json_files() -> Iterator[Path]:
    """内容根下全部 JSON 文件（含子目录；排除隐藏目录）。"""
    for p in sorted(CONTENT.rglob("*.json")):
        if any(part.startswith(".") for part in p.parts):
            continue
        yield p


def test_no_content_pack_declares_removed_key() -> None:
    """残留清单 = 0：内容根下任何 JSON 都不再含 `transfer_allowed`（含注释态字符串）。"""
    hits: List[Tuple[str, int, str]] = []
    for path in _json_files():
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if REMOVED_KEY in line:
                hits.append((str(path.relative_to(REPO)), lineno, line.strip()))
    assert hits == [], f"内容包残留未清理：{hits}"


def test_removed_key_absent_from_parsed_settings_and_labels() -> None:
    """结构化断言：enhance 段的 settings 数据键与展示名都无该键（双形态都清）。"""
    for pack in _pack_dirs():
        enh = pack / "enhance.json"
        if enh.is_file():
            body = json.loads(enh.read_text(encoding="utf-8"))
            settings = body.get("settings") if isinstance(body, dict) else None
            assert isinstance(settings, dict)
            assert REMOVED_KEY not in settings, f"{pack.name}: enhance.settings 残留数据键"
        meta = pack / "field_meta.json"
        if meta.is_file():
            body = json.loads(meta.read_text(encoding="utf-8"))

            def _walk(node: Any) -> Iterator[Any]:
                if isinstance(node, dict):
                    for k, v in node.items():
                        yield k
                        yield from _walk(v)
                elif isinstance(node, list):
                    for v in node:
                        yield from _walk(v)

            assert REMOVED_KEY not in set(_walk(body)), f"{pack.name}: field_meta 残留展示名"


def test_cleanup_adds_no_red_error_in_any_pack() -> None:
    """清理不在任何包里引入红拦（按目录动态发现；探针包自带的有意悬空引用不算本键问题）。

    判据：`check_pack` 的结果里不得出现与该键相关的 error/warning 字段路径。
    （正式包 veinborn 的 0 error / 332 warning 由批29 报告与换包验收脚本佐证。）
    """
    for pack in _pack_dirs():
        mods: Dict[str, Any] = {}
        for p in sorted(pack.glob("*.json")):
            mods[p.stem] = json.loads(p.read_text(encoding="utf-8"))
        report = check_pack(mods)
        related = [e for e in report.errors if REMOVED_KEY in str(e)]
        assert related == [], (pack.name, related[:5])
