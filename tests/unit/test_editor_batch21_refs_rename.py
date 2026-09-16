"""编辑器批21 · C 段：改 ID / 改键 / 删除前的**引用检查接线**（用户 2026-09-16 拍板）。

依据：CakeGame 教训「落库后禁止改名——改名 = 全引用方连锁断链」；我们已有引用扫描
（`/api/pack/{pack}/entry/{module}/{entry_id}/refs`），批21 把它接到改 ID / 删除流程：

  · 改 ID（`ModuleMeta.id_field`）→ 保存前调既有 `api.reference_scan`，结构化返回
    `refs` / `ref_count` / `breaking`；有引用且未确认 → 不写入（`needs_confirmation`）；
    确认后照常保存，**不自动改写引用方**（旧名悬空由后续校验如实报 R-4）。
  · 删除 → 沿用既有引用者列表，**强化呈现**（汇总：前若干条 + 总数 + 「删除后失效」）。
  · 通用：不写死模块名 / 字段名；无引用时行为与现状一致（回归断言）。

全部写盘只发生在 tmp_path（自建通用包），绝不触碰仓库 content/（批19.1 防污染门禁）。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

META = FieldMetaTable(modules={
    "widgets": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
        "owner": FieldMeta(type="ref", ref_target="widgets", label="归属"),
    }),
    "others": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "owner": FieldMeta(type="ref", ref_target="widgets", label="归属"),
    }),
})

WIDGETS = [
    {"id": "s1", "name": "甲", "owner": "s1"},
    {"id": "s2", "name": "乙"},
]
OTHERS = [{"id": "o1", "owner": "s1"}]


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def pack_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """自建通用包（tmp_path）+ 注入通用字段元数据表。"""
    pkg = tmp_path / "pack_u"
    pkg.mkdir()
    _write(pkg / "manifest.json", {
        "name": "U", "version": "1", "schema_version": 1,
        "modules": ["widgets", "others"],
    })
    _write(pkg / "widgets.json", WIDGETS)
    _write(pkg / "others.json", OTHERS)
    monkeypatch.setattr(api, "_META_TABLE", META)
    return tmp_path


# =====================================================================================
# 1. 改 ID 前调既有引用扫描 → 结构化 refs / ref_count / breaking
# =====================================================================================
def test_validate_rename_with_refs_returns_structured_refs(pack_root: Path) -> None:
    res = editor_ops.validate_entry("pack_u", "widgets", "s1", {"id": "s9"},
                                    root=pack_root, meta=META)
    assert res["rename"] == {"id_field": "id", "from": "s1", "to": "s9"}
    assert res["breaking"] is True
    assert res["ref_count"] == len(res["refs"]) == 2
    assert res["needs_confirmation"] is True
    # 引用方清单含模块 / 条目 / 字段（自己的自引用也算）
    got = {(r["module"], r["entry_id"], r["field"]) for r in res["refs"]}
    assert ("others", "o1", "owner") in got
    assert ("widgets", "s1", "owner") in got
    # 有引用时不静默：汇总黄提示 + 逐条引用者
    codes = [w["code"] for w in res["warnings"]]
    assert "entry_referenced_summary" in codes
    assert "entry_referenced" in codes
    summary = next(w for w in res["warnings"] if w["code"] == "entry_referenced_summary")
    assert summary["ref_count"] == 2 and "改名会断链" in summary["message"]


def test_save_rename_with_refs_requires_confirmation_and_writes_nothing(pack_root: Path) -> None:
    pkg = pack_root / "pack_u"
    before = (pkg / "widgets.json").read_bytes()
    res = editor_ops.save_entry("pack_u", "widgets", "s1", {"id": "s9"},
                                root=pack_root, meta=META)
    assert res["ok"] is False
    assert res["breaking"] is True and res["needs_confirmation"] is True
    assert res["ref_count"] == 2 and res["errors"] == []
    assert "确认" in res["message"]
    # 未确认 → 一个字节都没写、也没备份
    assert (pkg / "widgets.json").read_bytes() == before
    assert not (pkg / "widgets.json.bak").exists()


def test_save_rename_confirmed_writes_and_keeps_referrer_old_name(pack_root: Path) -> None:
    pkg = pack_root / "pack_u"
    res = editor_ops.save_entry("pack_u", "widgets", "s1", {"id": "s9"},
                                root=pack_root, meta=META, confirm=True)
    assert res["ok"] is True and res["breaking"] is True
    assert res["needs_confirmation"] is False
    assert [e["id"] for e in _read(pkg / "widgets.json")] == ["s9", "s2"]
    # 不自动改写引用方：others.o1.owner 仍是旧名 s1
    assert _read(pkg / "others.json")[0]["owner"] == "s1"
    assert (pkg / "widgets.json.bak").exists()


def test_rename_then_validation_reports_dangling_reference(pack_root: Path) -> None:
    """端到端：被引用的条目改名 → 引用方保持旧名 → 校验如实报「引用目标不存在」（R-4）。"""
    pkg = pack_root / "pack_u"
    assert editor_ops.save_entry("pack_u", "widgets", "s1", {"id": "s9"},
                                 root=pack_root, meta=META, confirm=True)["ok"]
    assert _read(pkg / "others.json")[0]["owner"] == "s1"
    # 对引用方做一次无害校验（补丁 = 原值）→ 校验器如实报 R-4 引用缺失
    res = editor_ops.validate_entry("pack_u", "others", "o1", {"owner": "s1"},
                                    root=pack_root, meta=META)
    assert res["ok"] is False
    r4 = [e for e in res["errors"] if e["code"] == "R-4"]
    assert r4, res["errors"]
    # 人话三段式：why = 「这里指向的『s1』在内容里找不到（它应该指向：widgets）」
    assert any("s1" in str(e.get("why")) and "找不到" in str(e.get("why")) for e in r4)
    assert all(e["rule"] == "ref_missing" for e in r4)


# =====================================================================================
# 2. 无引用时行为与现状一致（回归断言）
# =====================================================================================
def test_rename_without_refs_is_unchanged(pack_root: Path) -> None:
    res = editor_ops.validate_entry("pack_u", "widgets", "s2", {"id": "s8"},
                                    root=pack_root, meta=META)
    assert res["rename"] == {"id_field": "id", "from": "s2", "to": "s8"}
    assert res["breaking"] is False and res["ref_count"] == 0 and res["refs"] == []
    assert res["needs_confirmation"] is False
    assert res["ok"] is True
    saved = editor_ops.save_entry("pack_u", "widgets", "s2", {"id": "s8"},
                                  root=pack_root, meta=META)
    assert saved["ok"] is True and saved["breaking"] is False


def test_non_identity_patch_reports_no_rename(pack_root: Path) -> None:
    res = editor_ops.validate_entry("pack_u", "widgets", "s2", {"name": "改个名"},
                                    root=pack_root, meta=META)
    assert res["rename"] is None
    assert res["refs"] == [] and res["ref_count"] == 0
    assert res["breaking"] is False and res["needs_confirmation"] is False


# =====================================================================================
# 3. 删除：强化呈现（前若干条 + 总数 + 「删除后这些引用会失效」）
# =====================================================================================
def test_delete_reference_summary_lists_total_and_consequence(pack_root: Path) -> None:
    res = editor_ops.delete_entry("pack_u", "widgets", "s1", root=pack_root, meta=META)
    assert res["ok"] is True
    assert len(res["referrers"]) == 2
    summary = next(w for w in res["warnings"] if w["code"] == "entry_referenced_summary")
    assert summary["ref_count"] == 2
    assert "删除后这些引用会失效" in summary["message"]
    assert "2 处引用" in summary["message"]
    # 逐条引用者仍在（既有行为不丢）
    assert any(w["code"] == "entry_referenced" for w in res["warnings"])


def test_delete_unreferenced_unchanged(pack_root: Path) -> None:
    res = editor_ops.delete_entry("pack_u", "widgets", "s2", root=pack_root, meta=META)
    assert res["ok"] is True and res["referrers"] == []
    assert not any(w["code"] == "entry_referenced_summary" for w in res["warnings"])


# =====================================================================================
# 4. 前端契约：确认弹窗文案 + needs_confirmation 分支
# =====================================================================================
def test_frontend_rename_confirm_wiring() -> None:
    html = (Path(__file__).resolve().parents[2]
            / "qbot_rpg" / "web" / "static" / "index.html").read_text(encoding="utf-8")
    assert "renameConfirmText" in html
    assert "res.needs_confirmation" in html
    assert "confirm: true" in html
    assert "引用方不会被自动改写" in html


# =====================================================================================
# 5. 宿主路由：save body 透传 confirm
# =====================================================================================
def test_host_save_route_passes_confirm() -> None:
    host = (Path(__file__).resolve().parents[2] / "scripts" / "editor_host.py").read_text(
        encoding="utf-8")
    assert 'confirm=bool(body.get("confirm"))' in host


# =====================================================================================
# 6. 通用性：不写死模块名 / 字段名（换个模块名 + 换个 ID 字段名照常工作）
# =====================================================================================
def test_rename_detection_is_generic(tmp_path: Path,
                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """条目身份字段来自 `ModuleMeta.id_field`（此处非 `id`），模块名也换一个 → 机制照常。"""
    meta = FieldMetaTable(modules={
        "zork": ModuleMeta(entry_type="list", id_field="code", fields={
            "code": FieldMeta(type="str", required=True, label="编码"),
            "peer": FieldMeta(type="ref", ref_target="zork", label="同伴"),
        }),
    })
    pkg = tmp_path / "pack_g"
    pkg.mkdir()
    _write(pkg / "manifest.json", {"name": "G", "version": "1", "schema_version": 1,
                                   "modules": ["zork"]})
    _write(pkg / "zork.json", [{"code": "x1"}, {"code": "x2", "peer": "x1"}])
    monkeypatch.setattr(api, "_META_TABLE", meta)

    res = editor_ops.validate_entry("pack_g", "zork", "x1", {"code": "x9"},
                                    root=tmp_path, meta=meta)
    assert res["rename"] == {"id_field": "code", "from": "x1", "to": "x9"}
    assert res["breaking"] is True and res["ref_count"] == 1
    saved = editor_ops.save_entry("pack_g", "zork", "x1", {"code": "x9"},
                                  root=tmp_path, meta=meta, confirm=True)
    assert saved["ok"] is True
    assert _read(pkg / "zork.json")[1]["peer"] == "x1"  # 引用方未被改写
