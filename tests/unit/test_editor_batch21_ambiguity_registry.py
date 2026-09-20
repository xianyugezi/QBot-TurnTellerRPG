"""编辑器批21 · E 段：**矛盾与待裁决登记正式化**（CakeGame 纪律「只登记不裁决」）。

依据：用户 2026-09-16 拍板落地《CakeGame 规范_对照参考笔记》§二 可借鉴项 E。
本用例断言「固定小节存在 + 登记项 ≥ N 且每条有状态」（不必逐条断言），
并断言点名的散落项已归入（审计 §五 U1–U7 / #9 公式未登记键 / 采集挖掘 / slots↔slot_defs /
怪物触发枚举双源），以及台账互链与页脚批次串同步。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
REGISTRY = REPO / "docs" / "矛盾与待裁决登记.md"
LEDGER = REPO / "docs" / "编辑器修改意见0915_台账与方案.md"
INDEX = REPO / "qbot_rpg" / "web" / "static" / "index.html"

BATCH_NOTE = "批70 · 登记失效清账"
STATUS_PREFIXES = ("待实测", "待用户裁决", "已裁决-", "已实现-")
MIN_ITEMS = 20


def _rows(text: str) -> list[tuple[str, str]]:
    """解析登记表行：`| <编号> | … | <状态> |` → [(编号, 状态)]。"""
    out: list[tuple[str, str]] = []
    for line in text.splitlines():
        m = re.match(r"^\|\s*([UX]\d+)\s*\|(.+)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip().strip("*").strip() for c in m.group(2).split("|")]
        out.append((m.group(1), cells[-1]))
    return out


def test_registry_file_and_section_exist() -> None:
    assert REGISTRY.is_file(), "应新建 docs/矛盾与待裁决登记.md"
    text = REGISTRY.read_text(encoding="utf-8")
    assert "矛盾与待裁决登记" in text
    assert "## 一、登记表" in text
    # 固定小节四要素：编号 / 争点 / 双方证据 / 状态
    for token in ("一句话争点", "双方证据", "状态", "只登记，不裁决"):
        assert token in text, token


def test_registry_has_enough_items_each_with_status() -> None:
    rows = _rows(REGISTRY.read_text(encoding="utf-8"))
    assert len(rows) >= MIN_ITEMS, f"登记项应 ≥ {MIN_ITEMS}，实际 {len(rows)}"
    ids = {rid for rid, _ in rows}
    assert len(ids) == len(rows), "编号不得重复"
    for rid, status in rows:
        assert status.startswith(STATUS_PREFIXES), f"{rid} 状态非法：{status!r}"
    # 审计 §五 U1–U7 至少全在（点名归入，不得遗漏）
    assert {f"U{i}" for i in range(1, 8)} <= ids


def test_registry_includes_named_scattered_items() -> None:
    text = REGISTRY.read_text(encoding="utf-8")
    # #9 公式未登记键 → X1
    assert "X1" in text and "公式未登记" in text
    # 采集 / 挖掘 归属：批36 · X2 引擎已实现（争点原句 + 已实现状态 + 口径文档）
    assert "采集" in text and "挖掘" in text and "引擎未实现" in text
    assert "已实现-批36" in text and "docs/采集挖掘_实现口径.md" in text
    # slots ↔ settings.slot_defs 重叠
    assert "slots" in text and "settings.slot_defs" in text
    # 怪物触发类型枚举双源
    assert "怪物触发" in text and "枚举双源" in text
    # 来源清单（grep 汇总）
    assert "来源清单" in text


def test_ledger_links_registry_and_has_batch_section() -> None:
    ledger = LEDGER.read_text(encoding="utf-8")
    assert "docs/矛盾与待裁决登记.md" in ledger
    assert "## 十三、批21" in ledger


def test_footer_batch_note_synced() -> None:
    html = INDEX.read_text(encoding="utf-8")
    assert BATCH_NOTE in html
    m = re.search(r'<div class="panel-ft"><span>(.*?)</span>', html)
    assert m and m.group(1) == BATCH_NOTE, m and m.group(1)
    assert "批49 · 测试 flake 根治" not in html
    # 批40 页脚：上一批串（批39 · 合成公用层）不得残留
    assert "批40 · 实例uid与随机流" not in html
    assert "批36 · 采集/挖掘" not in html
    assert "批37 · 战后恢复" not in html
