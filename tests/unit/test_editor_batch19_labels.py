"""编辑器重写批19 · 段 B：未启用/新启用模块的中文名与字段完整（用户 #6）。

用户反馈 #6：新启用一个框架模块后，左栏/中栏/字段区仍出现**裸英文模块键**——因为
模块显示名只回落「包声明 → 模块键」，漏了框架目录 `module_catalog` 的中文默认名。

本批口径（一号原则）：
  · 模块名回落链 = 包声明（manifest/field_meta/module_tree）→ 框架目录 label → 模块键；
  · 字段中文名 = 包声明 → 框架登记字段元数据（`field_meta.py`）→ 键名 +
    「元数据未登记」标注（既有口径，本批不放松）；
  · 通用、不写死模块名：机制只认 `module_catalog` 目录与包声明。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from qbot_rpg.content.module_catalog import FRAMEWORK_MODULE_CATALOG
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

CATALOG = {e.module: e for e in FRAMEWORK_MODULE_CATALOG}
# 目录里 label 与模块键不同的（= 有中文名，正是回落要用的那批）
CHINESE = {m: e.label for m, e in CATALOG.items() if e.label and e.label != m}


@pytest.fixture()
def blank(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "demo_blank", tmp_path / "blank")
    return tmp_path


# =====================================================================================
# A · 目录全集都有中文默认名（回落链的兜底非空）
# =====================================================================================
def test_catalog_labels_are_chinese_and_nonempty() -> None:
    assert CHINESE, "框架目录没有任何中文默认名"
    for mod, label in CHINESE.items():
        assert label and label != mod


def test_enabled_module_label_falls_back_to_catalog(blank: Path) -> None:
    """每启用一个目录模块 → 左栏/中栏/索引的模块名都不得是裸英文键。"""
    enabled = [m for m in CHINESE if api.is_enableable_module(m)]
    assert enabled
    for mod in enabled:
        res = editor_ops.set_module_enabled("blank", mod, True, root=blank, role="owner")
        assert res["ok"] is True, (mod, res)

    mods = api.list_modules("blank", root=blank)
    nodes = {m["module"]: m for m in mods["modules"]}
    idx = {m["module"]: m for m in api.entry_index("blank", root=blank)["modules"]}
    for mod in enabled:
        assert mod in nodes, mod
        want = CHINESE[mod]
        assert nodes[mod]["label"] == want, (mod, nodes[mod]["label"])
        assert idx[mod]["label"] == want
        le = api.list_entries("blank", mod, root=blank)
        assert le["label"] == want, (mod, le["label"])


def test_fishing_fields_have_chinese_labels(blank: Path) -> None:
    """点名的 fishing：模块名「钓鱼」、顶层框架字段全有中文名（不得裸英文键）。"""
    editor_ops.set_module_enabled("blank", "fishing", True, root=blank, role="owner")
    nodes = {m["module"]: m for m in api.list_modules("blank", root=blank)["modules"]}
    assert nodes["fishing"]["label"] == "钓鱼"
    le = api.list_entries("blank", "fishing", root=blank)
    assert le["label"] == "钓鱼"
    names = {e["id"]: e["name"] for e in le["entries"]}
    for seg in ("schema_version", "species", "king"):
        assert names[seg] != seg, (seg, names)
    d = api.entry_detail("blank", "fishing", "species", root=blank)
    assert d["module_label"] == "钓鱼"
    assert d["fields"] and all(f["label"] != f["key"] for f in d["fields"])


# =====================================================================================
# B · 包声明优先（回落链不抢包的中文名）
# =====================================================================================
def test_pack_declared_label_wins_over_catalog(blank: Path) -> None:
    pack_dir = blank / "blank"
    decl = pack_dir / "field_meta.json"
    raw = {"schema_version": 1, "module_labels": {"fishing": "垂钓（包名）"}}
    import json
    decl.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    editor_ops.set_module_enabled("blank", "fishing", True, root=blank, role="owner")
    nodes = {m["module"]: m for m in api.list_modules("blank", root=blank)["modules"]}
    assert nodes["fishing"]["label"] == "垂钓（包名）"


# =====================================================================================
# C · 负向：目录没有、包也没声明的模块 → 仍回落模块键（不臆造中文名）
# =====================================================================================
def test_unknown_module_still_falls_back_to_key(tmp_path: Path) -> None:
    pkg = tmp_path / "p"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(
        '{"name":"P","version":"1","schema_version":1,"modules":["zz_custom"]}',
        encoding="utf-8")
    (pkg / "zz_custom.json").write_text("[]", encoding="utf-8")
    nodes = {m["module"]: m for m in api.list_modules("p", root=tmp_path)["modules"]}
    assert nodes["zz_custom"]["label"] == "zz_custom"


def test_frontend_unaffected_contract_still_present() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "未启用 · 框架能力" in html
