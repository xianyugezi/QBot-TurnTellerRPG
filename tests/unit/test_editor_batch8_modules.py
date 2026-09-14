"""编辑器重写批8 · 顶栏「模块开关」⚙（docs/编辑器重写_实现方案.md §四 批8）。

覆盖任务书要求：
  A. **模块目录来源与优先级**：可启用清单来自**框架通用目录**（空白包也有完整候选），
     不是从当前包已有声明反推；中文名**包声明优先**（field_meta.json / manifest / 树节点），
     未声明才用框架通用默认名；包自定义模块仍会出现。
  B. **启用落盘**：写入 `manifest.modules` + 按 entry_type 创建最小骨架
     （list → []；map/object → {}）；校验 → 原子写 → 自动备份 → 回退（批2 同一链路）。
  C. **停用**：只移除声明、保留数据文件；停用被引用模块只黄提示、不硬拦。
  D. **依赖黄提示**：缺前置模块时启用 → 「建议同时启用」，不硬拦。
  E. **权限**：GM 只读身份写入被 `Forbidden` 拒绝（零文件改动）。
  F. **通用性**：目录/编辑器代码不写死任何真实内容包名或业务字段名。

全部写盘发生在 tmp_path 的包拷贝（绝不触碰仓库 content/ 下任何包）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.content.module_catalog import CATALOG_BY_MODULE, FRAMEWORK_MODULE_CATALOG
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CATALOG_SRC = REPO / "qbot_rpg" / "content" / "module_catalog.py"


def _write(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """空白包（无任何模块声明）+ 一个最小包：都写 tmp_path，真实 content/ 只读。"""
    blank = tmp_path / "blank_pack"
    blank.mkdir()
    _write(blank / "manifest.json",
           {"name": "空白", "version": "1", "schema_version": 1, "modules": []})
    base = tmp_path / "base_pack"
    base.mkdir()
    _write(base / "manifest.json",
           {"name": "基础", "version": "1", "schema_version": 1, "modules": ["items"]})
    _write(base / "items.json", [])
    return tmp_path


# =====================================================================================
# A. 模块目录来源与优先级
# =====================================================================================
def test_catalog_blank_pack_has_framework_candidates(root: Path) -> None:
    cat = api.module_catalog("blank_pack", root=root)
    assert cat["total"] == len(FRAMEWORK_MODULE_CATALOG)
    assert cat["enabled_count"] == 0
    rows = {r["module"]: r for r in cat["modules"]}
    assert "skills" in rows and "maps" in rows and "stats" in rows
    assert rows["skills"]["enabled"] is False
    assert rows["skills"]["label"] == "技能"          # 框架通用默认名
    assert rows["skills"]["label_source"] == "framework"
    assert "技能" in rows["skills"]["purpose"] or rows["skills"]["purpose"]
    assert "勾选" in cat["hint"] and "不会出现在左侧" in cat["hint"]


def test_catalog_entry_type_from_framework(root: Path) -> None:
    rows = {r["module"]: r for r in api.module_catalog("blank_pack", root=root)["modules"]}
    assert rows["skills"]["entry_type"] == "list"
    assert rows["stats"]["entry_type"] == "map"
    assert rows["settings"]["entry_type"] == "object"


def test_catalog_pack_label_wins_over_framework_default(root: Path) -> None:
    pkg = root / "label_pack"
    pkg.mkdir()
    _write(pkg / "manifest.json",
           {"name": "L", "version": "1", "schema_version": 1, "modules": ["skills"],
            "module_labels": {"skills": "旧占位名"}})
    _write(pkg / "skills.json", [])
    _write(pkg / "field_meta.json",
           {"schema_version": 1, "module_labels": {"skills": "招式"}})
    rows = {r["module"]: r for r in api.module_catalog("label_pack", root=root)["modules"]}
    assert rows["skills"]["label"] == "招式"          # field_meta.json 优先于 manifest
    assert rows["skills"]["label_source"] == "pack"


def test_catalog_includes_pack_custom_module(root: Path) -> None:
    pkg = root / "custom_pack"
    pkg.mkdir()
    _write(pkg / "manifest.json",
           {"name": "C", "version": "1", "schema_version": 1,
            "modules": ["items", "zz_custom"], "module_labels": {"zz_custom": "自定模块"}})
    _write(pkg / "items.json", [])
    _write(pkg / "zz_custom.json", [])
    rows = {r["module"]: r for r in api.module_catalog("custom_pack", root=root)["modules"]}
    assert rows["zz_custom"]["label"] == "自定模块"
    assert rows["zz_custom"]["in_catalog"] is False
    assert rows["zz_custom"]["enabled"] is True


def test_catalog_missing_requires_is_reported(root: Path) -> None:
    rows = {r["module"]: r for r in api.module_catalog("blank_pack", root=root)["modules"]}
    assert rows["skill_chains"]["requires"] == ["skills"]
    assert rows["skill_chains"]["missing_requires"] == ["skills"]
    assert rows["skill_chains"]["requires_labels"] == ["技能"]
    assert rows["equipment"]["requires"] == ["items"]


# =====================================================================================
# B. 启用：manifest + 骨架 + 备份
# =====================================================================================
def test_enable_list_module_writes_manifest_and_skeleton(root: Path) -> None:
    pkg = root / "blank_pack"
    res = editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    assert res["ok"] is True and res["level"] in ("ok", "yellow")
    assert _read(pkg / "manifest.json")["modules"] == ["skills"]
    assert _read(pkg / "skills.json") == []           # list → []
    assert (pkg / "manifest.json.bak").is_file()      # 自动备份
    # 启用后左栏模块树 / 计数立即可见（只读层数据源 = manifest）
    mods = api.list_modules("blank_pack", root=root)
    assert [(m["module"], m["count"]) for m in mods["modules"]] == [("skills", 0)]


def test_enable_map_and_object_modules_skeleton_shape(root: Path) -> None:
    pkg = root / "blank_pack"
    assert editor_ops.set_module_enabled("blank_pack", "stats", True, root=root)["ok"]
    assert editor_ops.set_module_enabled("blank_pack", "settings", True, root=root)["ok"]
    assert _read(pkg / "stats.json") == {}            # map → {}
    assert _read(pkg / "settings.json") == {}         # object → {}


def test_enable_does_not_overwrite_existing_data(root: Path) -> None:
    pkg = root / "base_pack"
    data = [{"id": "s1", "type": "basic"}]
    _write(pkg / "skills.json", data)
    res = editor_ops.set_module_enabled("base_pack", "skills", True, root=root)
    assert res["ok"] is True
    assert _read(pkg / "skills.json") == data


def test_enable_idempotent(root: Path) -> None:
    editor_ops.set_module_enabled("base_pack", "items", True, root=root)
    res = editor_ops.set_module_enabled("base_pack", "items", True, root=root)
    assert res["ok"] is True and "已是启用状态" in res["message"]


# =====================================================================================
# C. 停用：只移除声明、保留文件（包含被引用时只黄提示）
# =====================================================================================
def test_disable_removes_declaration_keeps_file(root: Path) -> None:
    pkg = root / "blank_pack"
    editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    res = editor_ops.set_module_enabled("blank_pack", "skills", False, root=root)
    assert res["ok"] is True
    assert "保留" in res["message"]
    assert "skills" not in _read(pkg / "manifest.json")["modules"]
    assert (pkg / "skills.json").is_file()            # 数据文件保留
    # 重新勾选即可恢复
    again = editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    assert again["ok"] is True
    assert "skills" in _read(pkg / "manifest.json")["modules"]


# 自定义元数据：refmod 引用 mainmod 的条目，用于验证「停用被引用模块不硬拦」。
META = FieldMetaTable(modules={
    "mainmod": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "name": FieldMeta(type="str", label="名称"),
    }),
    "refmod": ModuleMeta(entry_type="list", fields={
        "id": FieldMeta(type="str", required=True, label="标识"),
        "target": FieldMeta(type="ref", ref_target="mainmod", label="目标"),
    }),
})


def test_disable_referenced_module_is_yellow_not_blocked(root: Path) -> None:
    pkg = root / "ref_pack"
    pkg.mkdir()
    _write(pkg / "manifest.json",
           {"name": "R", "version": "1", "schema_version": 1, "modules": ["mainmod", "refmod"]})
    _write(pkg / "mainmod.json", [{"id": "m1", "name": "甲"}])
    _write(pkg / "refmod.json", [{"id": "r1", "target": "m1"}])
    res = editor_ops.set_module_enabled("ref_pack", "mainmod", False, root=root, meta=META)
    assert res["ok"] is True
    assert any("放行" in w.get("message", "") for w in res["warnings"])
    assert "mainmod" not in _read(pkg / "manifest.json")["modules"]
    assert (pkg / "mainmod.json").is_file()


# =====================================================================================
# D. 依赖黄提示（不硬拦）
# =====================================================================================
def test_enable_without_prerequisite_is_yellow_only(root: Path) -> None:
    res = editor_ops.set_module_enabled("blank_pack", "equipment", True, root=root)
    assert res["ok"] is True
    msgs = [w.get("message", "") for w in res["warnings"]]
    assert any("建议同时" in m and "物品" in m for m in msgs)
    assert "equipment" in _read(root / "blank_pack" / "manifest.json")["modules"]


def test_disable_prerequisite_warns_dependents(root: Path) -> None:
    editor_ops.set_module_enabled("blank_pack", "items", True, root=root)
    editor_ops.set_module_enabled("blank_pack", "equipment", True, root=root)
    res = editor_ops.set_module_enabled("blank_pack", "items", False, root=root)
    assert res["ok"] is True
    assert any("依赖" in w.get("message", "") for w in res["warnings"])


# =====================================================================================
# E. 权限与非法输入
# =====================================================================================
def test_gm_readonly_is_forbidden_and_writes_nothing(root: Path) -> None:
    pkg = root / "blank_pack"
    before = (pkg / "manifest.json").read_bytes()
    with pytest.raises(api.Forbidden):
        editor_ops.set_module_enabled("blank_pack", "skills", True, root=root, role="gm")
    assert (pkg / "manifest.json").read_bytes() == before
    assert not (pkg / "skills.json").exists()


def test_unknown_module_is_bad_request(root: Path) -> None:
    with pytest.raises(api.BadRequest):
        editor_ops.set_module_enabled("blank_pack", "no_such_module", True, root=root)


def test_unreadable_existing_data_is_human_error(root: Path) -> None:
    pkg = root / "blank_pack"
    (pkg / "skills.json").write_text("{ bad json", encoding="utf-8")
    with pytest.raises(api.EditorError):
        editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)


# =====================================================================================
# F. manifest 回退（批2 链路）
# =====================================================================================
def test_rollback_module_config_restores_manifest_and_keeps_files(root: Path) -> None:
    pkg = root / "blank_pack"
    editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    editor_ops.set_module_enabled("blank_pack", "skills", False, root=root)
    assert "skills" not in _read(pkg / "manifest.json")["modules"]
    res = editor_ops.rollback_module_config("blank_pack", root=root)
    assert res["ok"] is True and res["rolled_back"] is True
    assert "skills" in _read(pkg / "manifest.json")["modules"]
    assert (pkg / "skills.json").is_file()            # 数据文件始终保留


def test_module_config_backup_status(root: Path) -> None:
    pkg = root / "blank_pack"
    assert editor_ops.module_config_backup("blank_pack", root=root)["exists"] is False
    editor_ops.set_module_enabled("blank_pack", "skills", True, root=root)
    status = editor_ops.module_config_backup("blank_pack", root=root)
    assert status["exists"] is True and status["path"] == "manifest.json.bak"
    assert (pkg / "manifest.json.bak").is_file()


def test_rollback_without_backup_is_red(root: Path) -> None:
    res = editor_ops.rollback_module_config("blank_pack", root=root)
    assert res["ok"] is False and res["level"] == "red"


# =====================================================================================
# G. 通用性护栏
# =====================================================================================
def test_catalog_source_has_no_real_pack_names() -> None:
    src = CATALOG_SRC.read_text(encoding="utf-8")
    for word in ("veinborn", "test_demo"):
        assert word not in src, word


def test_editor_code_has_no_pack_names() -> None:
    for path in (REPO / "qbot_rpg" / "web" / "api.py",
                 REPO / "qbot_rpg" / "web" / "editor_ops.py",
                 REPO / "scripts" / "editor_host.py"):
        text = path.read_text(encoding="utf-8")
        for word in ("veinborn", "test_demo"):
            assert word not in text, f"{path} 写死：{word}"


def test_catalog_ignores_pack_specific_business_fields() -> None:
    """目录条目只声明模块种类/中文名/用途，不含任何内容包专属业务字段。"""
    for entry in FRAMEWORK_MODULE_CATALOG:
        assert isinstance(entry.module, str) and entry.module
        assert isinstance(entry.label, str) and entry.label
        assert isinstance(entry.purpose, str) and entry.purpose
        assert entry.entry_type in ("list", "map", "object")
        for req in entry.requires:
            assert req in CATALOG_BY_MODULE, req


# =====================================================================================
# H. 宿主端点
# =====================================================================================
def _client(root: Path, pack: str = "blank_pack", role: str = "owner"):
    _REPO = str(REPO)
    if _REPO not in sys.path:
        sys.path.insert(0, _REPO)
    if str(REPO / "scripts") not in sys.path:
        sys.path.insert(0, str(REPO / "scripts"))
    from editor_host import create_app  # noqa: E402
    from fastapi.testclient import TestClient  # noqa: E402
    return TestClient(create_app(pack=pack, root=str(root), role=role))


def test_host_module_catalog_and_toggle(root: Path) -> None:
    with _client(root) as client:
        cat = client.get("/api/pack/blank_pack/module-catalog").json()
        assert cat["enabled_count"] == 0 and any(r["module"] == "skills" for r in cat["modules"])
        res = client.post("/api/pack/blank_pack/module/skills/toggle",
                          json={"enabled": True}).json()
        assert res["ok"] is True
        assert "skills" in _read(root / "blank_pack" / "manifest.json")["modules"]
        bak = client.get("/api/pack/blank_pack/manifest/backup").json()
        assert bak["exists"] is True
        rolled = client.post("/api/pack/blank_pack/manifest/rollback").json()
        assert rolled["ok"] is True
        assert "skills" not in _read(root / "blank_pack" / "manifest.json")["modules"]


def test_host_toggle_forbidden_for_gm(root: Path) -> None:
    with _client(root, role="gm") as client:
        r = client.post("/api/pack/blank_pack/module/skills/toggle", json={"enabled": True})
        assert r.status_code == 403
        assert not (root / "blank_pack" / "skills.json").exists()
