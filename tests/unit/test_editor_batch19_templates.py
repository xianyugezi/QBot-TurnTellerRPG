"""编辑器重写批19 · 段 A：消息模板显示全量（一号原则 #4）。

用户反馈 #4：包 `templates.json` 只声明 2 条覆盖 → 编辑器「消息模板」只显示 2 条；
框架全量表 `qbot_rpg/core/templates/template_table.json` 的 800+ 键不可见。

本批机制（**通用、不写死模块名/模板键名**）：
  · `ModuleMeta.key_source` 声明「框架侧键全集来源名」→ 条目列表 = 包数据键 ∪ 来源键；
  · 包数据已有的框架键标「已覆盖（包）」；来源里包没有的补一条（`framework_default`）
    标「默认（框架）」，可直接编辑并在保存时写入包覆盖（既有校验 / 备份 / 原子写 / 回退）；
  · 来源表由 `qbot_rpg/web/framework_keys.py` 注册表提供；编辑器读取层零写死。

覆盖：A. 全量结构断言；B. 覆盖/默认标记；C. 通用性（合成模块 + 注入来源）；
D. 端到端真写盘 → 回退逐字节复原；E. 负向（无 key_source 的 map 模块行为不变）；
F. 前端契约。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Mapping

import pytest

from qbot_rpg.web import framework_keys
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _framework_template_keys() -> set:
    from qbot_rpg.core.templates import TABLE_TEMPLATES
    return {str(k) for k in TABLE_TEMPLATES}


# =====================================================================================
# A · 全量结构断言（框架全量表键 ∪ 包覆盖）
# =====================================================================================
def test_templates_entries_cover_framework_table() -> None:
    le = api.list_entries("veinborn", "templates", root=CONTENT)
    ids = {e["id"] for e in le["entries"]}
    fw = _framework_template_keys()
    assert fw <= ids, sorted(fw - ids)[:5]
    assert le["count"] == le["covered_count"] + le["framework_default_count"]
    assert le["count"] == len(le["entries"])
    assert le["covered_count"] == 2           # 包 templates.json 两条覆盖
    assert le["framework_default_count"] == len(fw) - 2


def test_templates_default_entries_flagged_and_named_by_key() -> None:
    le = api.list_entries("veinborn", "templates", root=CONTENT)
    by_id = {e["id"]: e for e in le["entries"]}
    # 包覆盖的两条 → covered，不是 framework_default
    for eid in ("register_success_next", "job_switch_success"):
        assert by_id[eid].get("covered") is True
        assert not by_id[eid].get("framework_default")
    # 一条框架有、包没有的键 → framework_default，名 = 键
    assert by_id["register_gate"].get("framework_default") is True
    assert by_id["register_gate"]["name"] == "register_gate"


def test_templates_default_entry_detail_readonly_with_note() -> None:
    """批32 B1：框架关键模板（包未覆盖的框架键）= 只读；附框架侧说明与复制入口标记。"""
    d = api.entry_detail("veinborn", "templates", "register_gate", root=CONTENT)
    assert d["framework_default"] is True and d["unconfigured"] is True
    assert d["framework_locked"] is True
    assert d["framework_lock_note"]              # 「复制为包覆盖」提示
    assert d["default_note"]              # 有框架说明用说明，无则「键 = 名称」
    assert d["field_count"] == 1
    f = d["fields"][0]
    assert f["key"] == "register_gate" and f["editable"] is False
    assert f["present"] is False


def test_templates_zero_source_regression_for_other_map_modules() -> None:
    """负向：没有 key_source 声明的 map 模块（stats）条目集仍 = 包数据键。"""
    stats = api.list_entries("veinborn", "stats", root=CONTENT)
    data = json.loads((CONTENT / "veinborn" / "stats.json").read_text(encoding="utf-8"))
    assert stats["key_source"] == ""
    assert stats["framework_default_count"] == 0
    assert {e["id"] for e in stats["entries"]} == set(data)


# =====================================================================================
# B · 通用性：合成 map 模块 + 注入来源（不写死任何真实模块名）
# =====================================================================================
def _synth_pack(tmp_path: Path) -> Path:
    pkg = tmp_path / "p"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P", "version": "1", "schema_version": 1, "modules": ["lookup"]}),
        encoding="utf-8")
    (pkg / "lookup.json").write_text(json.dumps({"aaa": "覆盖值"}), encoding="utf-8")
    (pkg / "field_meta.json").write_text(json.dumps({
        "schema_version": 1,
        "module_labels": {"lookup": "查表"},
        "field_labels": {"lookup": {"aaa": "甲键", "bbb": "乙键"}},
    }), encoding="utf-8")
    return pkg


def test_key_source_mechanism_generic(tmp_path: Path,
                                      monkeypatch: pytest.MonkeyPatch) -> None:
    """给 framework_keys 注册一个来源 → 同名 key_source 的 map 模块即享全量展示。"""
    _synth_pack(tmp_path)
    fw: Mapping[str, Any] = {"aaa": "框架A", "bbb": "框架B", "ccc": "框架C"}
    notes = {"ccc": "框架侧说明"}
    monkeypatch.setitem(
        framework_keys.FRAMEWORK_KEY_SOURCES, "probe_src",
        lambda: (fw, notes))

    # 把合成模块的元数据 key_source 指到注入来源（不改框架表，用独立表注入）。
    from qbot_rpg.content.models import FieldMetaTable, ModuleMeta
    meta = FieldMetaTable(modules={
        "lookup": ModuleMeta(entry_type="map", key_source="probe_src"),
    }, namespaces={})
    monkeypatch.setattr(api, "_META_TABLE", meta)

    le = api.list_entries("p", "lookup", root=tmp_path)
    ids = [e["id"] for e in le["entries"]]
    assert ids == ["aaa", "bbb", "ccc"]        # 包数据键在前，框架默认键按来源顺序补齐
    assert le["covered_count"] == 1 and le["framework_default_count"] == 2
    d = api.entry_detail("p", "lookup", "ccc", root=tmp_path)
    assert d["framework_default"] is True and d["default_note"] == "框架侧说明"


def test_unknown_key_source_is_safe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    from qbot_rpg.content.models import FieldMetaTable, ModuleMeta
    meta = FieldMetaTable(modules={
        "lookup": ModuleMeta(entry_type="map", key_source="不存在的来源"),
    }, namespaces={})
    monkeypatch.setattr(api, "_META_TABLE", meta)
    le = api.list_entries("p", "lookup", root=tmp_path)
    assert {e["id"] for e in le["entries"]} == {"aaa"}


# =====================================================================================
# C · 端到端：默认（框架）模板经「复制为包覆盖」真写进包 templates.json → 回退逐字节复原
# =====================================================================================
@pytest.fixture()
def veinborn_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def test_default_template_direct_save_rejected_then_copy_override(veinborn_copy: Path) -> None:
    sf = veinborn_copy / "veinborn" / "templates.json"
    before = sf.read_text(encoding="utf-8")

    # 批32 B1：直接改框架默认键 → 被拒（红拦，零文件改动）。
    denied = editor_ops.save_entry(
        "veinborn", "templates", "register_gate",
        {"register_gate": "❌ 自定义进场 {name}"},
        root=veinborn_copy, role="owner")
    assert denied["ok"] is False
    assert [e for e in denied["errors"] if e.get("code") == "framework_locked"]
    assert "复制为包覆盖" in denied["message"]
    assert sf.read_text(encoding="utf-8") == before          # 未写盘

    # 「复制为包覆盖」→ 生成包覆盖条目（内容 = 当前框架文本），走既有落盘/备份链路。
    res = editor_ops.copy_framework_override(
        "veinborn", "templates", "register_gate", root=veinborn_copy, role="owner")
    assert res["ok"] is True, res
    assert res.get("copied_from_framework") is True
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert isinstance(after["register_gate"], str) and after["register_gate"]
    assert set(after) == set(json.loads(before)) | {"register_gate"}
    after_copy = sf.read_text(encoding="utf-8")

    # 复制后该键在编辑器里由「只读框架默认」变「已覆盖（包）」→ 再改自由（既有写链路）。
    le = api.list_entries("veinborn", "templates", root=veinborn_copy)
    row = {e["id"]: e for e in le["entries"]}["register_gate"]
    assert row.get("covered") is True and not row.get("framework_default")
    d = api.entry_detail("veinborn", "templates", "register_gate", root=veinborn_copy)
    assert d["framework_locked"] is False and d["fields"][0]["editable"] is True
    again = editor_ops.save_entry(
        "veinborn", "templates", "register_gate",
        {"register_gate": "❌ 自定义进场 {name}"},
        root=veinborn_copy, role="owner")
    assert again["ok"] is True, again
    assert json.loads(sf.read_text(encoding="utf-8"))["register_gate"] == "❌ 自定义进场 {name}"

    # 回退 = 既有一份备份语义：回到上一次写入前（= 复制出的包覆盖态）。
    rb = editor_ops.rollback_module("veinborn", "templates", root=veinborn_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == after_copy


def test_default_template_empty_value_saved_as_pack_value(veinborn_copy: Path) -> None:
    """空串是合法的包覆盖值（显式置空 = 覆盖为无文案），保存后仍标「已覆盖（包）」。"""
    sf = veinborn_copy / "veinborn" / "templates.json"
    before = sf.read_text(encoding="utf-8")
    save = editor_ops.save_entry("veinborn", "templates", "job_switch_success",
                                 {"job_switch_success": ""}, root=veinborn_copy, role="owner")
    assert save["ok"] is True, save
    assert json.loads(sf.read_text(encoding="utf-8"))["job_switch_success"] == ""
    editor_ops.rollback_module("veinborn", "templates", root=veinborn_copy, role="owner")
    assert sf.read_text(encoding="utf-8") == before


# =====================================================================================
# D · 前端契约（标记 + 提示）
# =====================================================================================
def test_frontend_exposes_framework_default_markers() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("默认（框架）", "已覆盖（包）", "e.framework_default", "e.covered",
                  "d.framework_default", "d.default_note",
                  # 批32 B1：框架关键模板只读 + 「复制为包覆盖」入口
                  "d.framework_locked", "复制为包覆盖", "btn-copy-override", "copy_override"):
        assert token in html, token
