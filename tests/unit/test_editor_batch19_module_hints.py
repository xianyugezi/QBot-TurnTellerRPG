"""编辑器重写批19 · 段 E：特性 / 装备槽 用途与重叠提示（用户 #5 相关点）。

用户反馈 #5 的相关点：`settings.slot_defs`（8 部位）与 `slots` 模块**功能重叠**。
本批在「特性」「装备槽」模块页显示：
  · 用途说明（取 `module_catalog` 的 purpose 一句话）；
  · 「当前包未使用」态（模块有目录能力、当前包数据为空）；
  · `slots` ↔ `settings.slot_defs` 的**黄提示**（不硬拦）：建议归口一处 + 各自定位说明。
机制为**目录声明驱动**（`ModuleCatalogEntry.overlap_with/overlap_note`），不写死模块名。
"""

from __future__ import annotations

from pathlib import Path

from qbot_rpg.content.module_catalog import CATALOG_BY_MODULE
from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


# =====================================================================================
# A · 用途 + 未使用态
# =====================================================================================
def test_traits_and_slots_pages_show_purpose() -> None:
    for mod in ("traits", "slots"):
        le = api.list_entries("veinborn", mod, root=CONTENT)
        assert le["purpose"] == CATALOG_BY_MODULE[mod].purpose
        assert le["purpose"], mod


def test_empty_modules_marked_unused() -> None:
    le_slots = api.list_entries("veinborn", "slots", root=CONTENT)
    assert le_slots["unused"] is True
    # 有数据的模块不是「未使用」
    assert api.list_entries("veinborn", "items", root=CONTENT)["unused"] is False
    # 左栏节点同口径
    nodes = {m["module"]: m for m in api.list_modules("veinborn", root=CONTENT)["modules"]}
    assert nodes["slots"]["unused"] is True and nodes["slots"]["purpose"]
    assert nodes["items"]["unused"] is False


# =====================================================================================
# B · 功能重叠黄提示（声明驱动，不硬拦）
# =====================================================================================
def test_slots_overlap_hint_names_the_other_location() -> None:
    le = api.list_entries("veinborn", "slots", root=CONTENT)
    hits = le["overlap_hints"]
    assert len(hits) == 1
    h = hits[0]
    assert h["level"] == "yellow" and h["code"] == "module_overlap"
    assert h["target"] == "settings.slot_defs"
    assert h["target_present"] is True          # 另一处确实有数据（实测 veinborn 8 部位）
    assert "归口" in h["message"] and "不阻断" in h["message"]


def test_traits_has_no_overlap_hint() -> None:
    assert api.list_entries("veinborn", "traits", root=CONTENT)["overlap_hints"] == []


def test_overlap_declaration_from_catalog_not_code() -> None:
    """重叠声明在目录（框架元数据），不在读取层写死——换包/换模块零改动。"""
    e = CATALOG_BY_MODULE["slots"]
    assert e.overlap_with == "settings.slot_defs" and e.overlap_note
    cat = api.module_catalog("veinborn", root=CONTENT)
    row = next(r for r in cat["modules"] if r["module"] == "slots")
    assert row["overlap_with"] == "settings.slot_defs" and row["overlap_note"]


def test_overlap_absent_when_declaration_absent_but_note_generic() -> None:
    """未声明重叠的模块 → 空列表（不噪音）；目录未知模块 → 空。"""
    assert api.list_entries("veinborn", "items", root=CONTENT)["overlap_hints"] == []


# =====================================================================================
# C · 前端契约
# =====================================================================================
def test_frontend_renders_module_hints() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("list-hint", "renderListHints", "当前包未使用", "lh-ov",
                  "d.overlap_hints", "d.purpose"):
        assert token in html, token
