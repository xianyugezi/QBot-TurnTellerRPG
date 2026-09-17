"""批32 · B1：模板只读（框架 §6.12-06）+「复制为包覆盖」（通用机制，不写死模块/键名）。

定稿原文（`docs/审查参考/RPG回合制框架设计文档.md` L1030-1034）：
  · 预置数据包带锁，不可直接修改；
  · 新建时「复制」出副本再编辑——模板永远干净。

本批语义（任务书 §2）：**被框架代码硬引用的模板键（框架关键模板）在编辑器里只读**，
并提供「复制为包覆盖」入口（把当前文本复制成包内 `templates.json` 覆盖条目，之后可自由改）。

**关键模板名单派生方式**：先核查框架里哪些模板键被代码硬引用（AST 扫 `tpl_of` 字面键
+ 模块级键常量）→ 只能覆盖约 90%（动态变量键 / 已死键无法可靠穷举）。故按任务书允许的
**最小可行方案**：以既有「框架键全集 vs 包覆盖」机制为界——**框架默认键（`_FRAMEWORK_DEFAULT`，
即框架来源里包未覆盖的键）只读；包覆盖 / 包自有键可编辑**。名单零手写、零业务键名。

测试只写临时目录（合成包 + 注入框架来源）；不触碰真实 content/。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops, framework_keys

REPO = Path(api.repo_root())
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


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
    return tmp_path


def _inject_source(monkeypatch: pytest.MonkeyPatch) -> None:
    fw: Mapping[str, Any] = {"aaa": "框架A", "bbb": "框架B", "ccc": "框架C"}
    monkeypatch.setitem(framework_keys.FRAMEWORK_KEY_SOURCES, "batch32_src",
                        lambda: (fw, {"ccc": "框架侧说明"}))
    meta = FieldMetaTable(modules={
        "lookup": ModuleMeta(entry_type="map", key_source="batch32_src",
                             value_meta=FieldMeta(type="str")),
    }, namespaces={})
    monkeypatch.setattr(api, "_META_TABLE", meta)


# ---------------------------------------------------------------------------
# 只读判定（框架默认键 → 只读；包覆盖 / 包自有键 → 可编辑）
# ---------------------------------------------------------------------------
def test_framework_default_entry_is_locked(tmp_path: Path,
                                           monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    le = api.list_entries("p", "lookup", root=tmp_path)
    assert le["framework_default_count"] == 2          # bbb/ccc（aaa 已覆盖）

    d = api.entry_detail("p", "lookup", "ccc", root=tmp_path)
    assert d["framework_default"] is True and d["framework_locked"] is True
    assert d["framework_lock_note"]
    assert d["fields"] and all(f["editable"] is False for f in d["fields"])
    assert all(f.get("framework_locked") is True for f in d["fields"])


def test_pack_covered_and_own_keys_stay_editable(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    covered = api.entry_detail("p", "lookup", "aaa", root=tmp_path)
    assert covered["framework_locked"] is False and covered["fields"][0]["editable"] is True


def test_no_key_source_behaviour_unchanged(tmp_path: Path) -> None:
    """无 key_source 的 map 模块：条目没有只读标记（行为与现状一致）。"""
    _synth_pack(tmp_path)
    d = api.entry_detail("p", "lookup", "aaa", root=tmp_path)
    assert d["framework_default"] is False and d["framework_locked"] is False
    assert d["fields"][0]["editable"] is True


# ---------------------------------------------------------------------------
# 直接编辑被拒（validate + save），文案提示「复制为包覆盖」
# ---------------------------------------------------------------------------
def test_direct_validate_locked_is_red(tmp_path: Path,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    res = editor_ops.validate_entry("p", "lookup", "bbb", {"bbb": "改"}, root=tmp_path)
    assert res["ok"] is False and res["level"] == "red"
    assert [e for e in res["errors"] if e.get("code") == "framework_locked"]
    assert "复制为包覆盖" in res["message"]


def test_direct_save_locked_rejected_no_write(tmp_path: Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    before = (tmp_path / "p" / "lookup.json").read_text(encoding="utf-8")
    res = editor_ops.save_entry("p", "lookup", "bbb", {"bbb": "改"}, root=tmp_path)
    assert res["ok"] is False and res["level"] == "red"
    assert [e for e in res["errors"] if e.get("code") == "framework_locked"]
    assert (tmp_path / "p" / "lookup.json").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 复制为包覆盖 → 生成覆盖条目 → 之后可自由编辑
# ---------------------------------------------------------------------------
def test_copy_override_then_editable(tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    data_path = tmp_path / "p" / "lookup.json"
    before = json.loads(data_path.read_text(encoding="utf-8"))

    res = editor_ops.copy_framework_override("p", "lookup", "bbb", root=tmp_path)
    assert res["ok"] is True, res
    assert res.get("copied_from_framework") is True
    after = json.loads(data_path.read_text(encoding="utf-8"))
    assert after["bbb"] == "框架B"                      # 复制的是当前框架文本
    assert set(after) == set(before) | {"bbb"}

    # 复制后 → 已覆盖（包）→ 可自由改
    d = api.entry_detail("p", "lookup", "bbb", root=tmp_path)
    assert d["framework_locked"] is False and d["fields"][0]["editable"] is True
    assert editor_ops.save_entry("p", "lookup", "bbb", {"bbb": "包内自定"},
                                 root=tmp_path)["ok"] is True
    assert json.loads(data_path.read_text(encoding="utf-8"))["bbb"] == "包内自定"


def test_copy_override_rejects_non_framework_key(tmp_path: Path,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    _synth_pack(tmp_path)
    _inject_source(monkeypatch)
    with pytest.raises(api.BadRequest):
        editor_ops.copy_framework_override("p", "lookup", "aaa", root=tmp_path)


# ---------------------------------------------------------------------------
# 前端契约
# ---------------------------------------------------------------------------
def test_frontend_lock_wiring() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("framework_locked", "framework_lock_note", "复制为包覆盖",
                  "btn-copy-override", "copy_override", "applyFrameworkLock",
                  "copyFrameworkOverride"):
        assert token in html, token
