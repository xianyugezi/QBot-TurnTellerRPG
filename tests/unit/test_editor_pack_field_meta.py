"""编辑器重写批A · 数据包展示元数据「读取层」测试。

依据：`docs/编辑器重写_数据包展示元数据下放方案.md`
  · §三 目标结构：包内 `field_meta.json`（纯 JSON，schema_version = 1）；
  · §四 批A：新增「读包声明 → 与框架 field_meta.py 表合并（包声明优先）」通用入口；
    只加读取层，**不改变现有行为**（对拍 diff = 0）；
  · §二 优先级：`field_labels`/`field_help`/`group_labels` 覆盖框架同键值；
    `module_labels`/`module_tree` 以 field_meta.json 优先于 manifest。

覆盖：包声明生效 / 优先级 / 未声明零变化 / 非法形态报错 / 未知顶层键报错 /
schema_version 校验；外加 veinborn 与 test_demo 的「启用读取层前后」接口对拍。

全程只读真实内容包：需要包声明的用例一律把包拷进 tmp_path 再写文件。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.content import field_meta_pack as fmp
from qbot_rpg.web import api

CONTENT = Path(api.repo_root()) / "content"
PACKS = ("veinborn", "test_demo")


# ---------------------------------------------------------------------------
# 工具：临时包拷贝 / 声明写入 / 接口快照
# ---------------------------------------------------------------------------
def _copy_pack(tmp_path: Path, pack: str = "test_demo") -> Path:
    dst = tmp_path / pack
    shutil.copytree(CONTENT / pack, dst)
    return dst


def _write_decl(pack_dir: Path, decl: object) -> Path:
    path = pack_dir / fmp.FIELD_META_FILENAME
    path.write_text(json.dumps(decl, ensure_ascii=False), encoding="utf-8")
    return path


def _all_modules(nodes: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for n in nodes:
        out.append(str(n["module"]))
        out.extend(_all_modules(n.get("children", [])))
    return out


def _snapshot(pack: str, root: Path) -> Dict[str, Any]:
    """六个只读入口的输出快照（模块树 / 条目列表 / 条目详情 / 条目索引 / 引用候选 / 包列表）。"""
    mods = api.list_modules(pack, root=root)
    declared = _all_modules(mods["modules"])
    snap: Dict[str, Any] = {
        "list_packs": api.list_packs(root=root),
        "modules": mods,
        "index": api.entry_index(pack, root=root),
    }
    for mod in declared:
        entries = api.list_entries(pack, mod, root=root)
        snap[f"entries/{mod}"] = entries
        if entries["entries"]:
            snap[f"detail/{mod}"] = api.entry_detail(
                pack, mod, entries["entries"][0]["id"], root=root)
    pack_dir = api._pack_dir(pack, root)
    index = api._PackView(pack_dir, api._manifest(pack_dir)).name_index()
    for target in sorted(index)[:3]:
        snap[f"refs/{target}"] = api.ref_options(pack, target, root=root)
    return snap


# =====================================================================================
# A. 未声明零变化 + 回归对拍（veinborn / test_demo）
# =====================================================================================
@pytest.mark.parametrize("pack", PACKS)
def test_real_packs_have_no_declaration(pack: str) -> None:
    assert not (CONTENT / pack / fmp.FIELD_META_FILENAME).exists()
    assert api._pack_meta_table(CONTENT / pack) is api.field_meta_table()


@pytest.mark.parametrize("pack", PACKS)
def test_read_layer_disabled_output_identical(pack: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """启用读取层 vs 关闭读取层（模拟批A之前）：无包声明 → 接口输出逐字节一致。"""
    enabled = _snapshot(pack, CONTENT)
    monkeypatch.setattr(api, "_pack_meta_table", lambda _pack_dir: api.field_meta_table())
    monkeypatch.setattr(api, "_pack_declaration", lambda _pack_dir: None)
    disabled = _snapshot(pack, CONTENT)
    assert enabled == disabled


def test_declaration_actually_changes_output_guard(tmp_path: Path) -> None:
    """反向对照：加了包声明后输出确实变化（证明上面的对拍不是空转）。"""
    pack_dir = _copy_pack(tmp_path)
    baseline = _snapshot("test_demo", pack_dir.parent)
    _write_decl(pack_dir, {"schema_version": 1, "module_labels": {"skills": "技能库X"}})
    changed = _snapshot("test_demo", pack_dir.parent)
    assert baseline != changed


# =====================================================================================
# B. 包声明生效 / 优先级
# =====================================================================================
def test_module_tree_and_labels_declaration_wins_over_manifest(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    baseline = api.list_modules("test_demo", root=pack_dir.parent)
    assert baseline["flat"] is False  # 现状：manifest 声明了层级
    _write_decl(pack_dir, {
        "schema_version": 1,
        "module_labels": {"skills": "技能库X"},
        "module_tree": [],  # 整体替换 manifest 的层级声明 → 平铺
    })
    data = api.list_modules("test_demo", root=pack_dir.parent)
    assert data["flat"] is True
    labels = {m["module"]: m["label"] for m in data["modules"]}
    assert labels["skills"] == "技能库X"
    assert "equipment" in labels  # 平铺后子模块并列出现


def test_field_labels_help_group_labels_override_with_fallback(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    entries = api.list_entries("test_demo", "skills", root=pack_dir.parent)
    eid = entries["entries"][0]["id"]
    before = api.entry_detail("test_demo", "skills", eid, root=pack_dir.parent)
    before_by_key = {f["key"]: f for f in before["fields"]}
    assert before_by_key["power"]["label"] == "威力"
    assert {g["name"]: g["label"] for g in before["groups"]}["数值"] == "数值"

    _write_decl(pack_dir, {
        "schema_version": 1,
        "field_labels": {"skills": {"power": "威力X"}},
        "field_help": {"skills": {"power": "说明X"}},
        "group_labels": {"skills": {"数值": "数值X"}},
    })
    after = api.entry_detail("test_demo", "skills", eid, root=pack_dir.parent)
    after_by_key = {f["key"]: f for f in after["fields"]}
    assert after_by_key["power"]["label"] == "威力X"
    assert after_by_key["power"]["help"] == "说明X"
    # 未声明键保持框架现状（label/help 不被清空）
    assert after_by_key["name"]["label"] == before_by_key["name"]["label"]
    groups = {g["name"]: g["label"] for g in after["groups"]}
    assert groups["数值"] == "数值X"
    assert groups["基本"] == "基本"  # 未声明组保持框架现状


def test_declared_unknown_field_becomes_soft_display(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    _write_decl(pack_dir, {
        "schema_version": 1,
        "field_labels": {"skills": {"zz_probe_field": "探针字段"}},
        "field_help": {"skills": {"zz_probe_field": "包专属新字段的说明。"}},
    })
    entries = api.list_entries("test_demo", "skills", root=pack_dir.parent)
    detail = api.entry_detail(
        "test_demo", "skills", entries["entries"][0]["id"], root=pack_dir.parent)
    probe = {f["key"]: f for f in detail["fields"]}.get("zz_probe_field")
    assert probe is not None
    assert probe["label"] == "探针字段"
    assert probe["help"] == "包专属新字段的说明。"
    # 纯展示字段：数据里没有 → present=False；渲染形态仍完整（不崩）
    assert probe["present"] is False
    assert probe["control"]


def test_map_module_value_meta_labels_override(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    base = api.field_meta_table().module("stats")
    assert base is not None and base.value_meta is not None
    assert base.value_meta.children["name"].label == "名称"
    _write_decl(pack_dir, {
        "schema_version": 1,
        "field_labels": {"stats": {"name": "属性名X"}},
    })
    table = api._pack_meta_table(pack_dir)
    stat = table.module("stats")
    assert stat is not None and stat.value_meta is not None
    assert stat.value_meta.children["name"].label == "属性名X"


def test_module_absent_from_framework_still_infers_entry_type(tmp_path: Path) -> None:
    """框架未登记、但 manifest 已声明的模块（用现场包实测的 templates）：只加展示，不换形态。"""
    pack_dir = _copy_pack(tmp_path)
    before = api.list_entries("test_demo", "templates", root=pack_dir.parent)
    _write_decl(pack_dir, {
        "schema_version": 1,
        "field_labels": {"templates": {"zz_probe": "探针"}},
    })
    after = api.list_entries("test_demo", "templates", root=pack_dir.parent)
    assert after["entry_type"] == before["entry_type"]
    assert after["count"] == before["count"]
    assert after["entries"] == before["entries"]


# =====================================================================================
# C. 严格解析：非法形态 / 未知顶层键 / schema_version
# =====================================================================================
@pytest.mark.parametrize("decl, need", [
    ({"schema_version": 1, "unknown_key": 1}, "unknown_key"),
    ({"module_labels": {"a": "b"}}, "schema_version"),
    ({"schema_version": "1"}, "schema_version"),
    ({"schema_version": True}, "schema_version"),
    ({"schema_version": 2}, "schema_version"),
    ({"schema_version": 1, "module_labels": []}, "module_labels"),
    ({"schema_version": 1, "module_labels": {"a": ""}}, "module_labels"),
    ({"schema_version": 1, "module_tree": 5}, "module_tree"),
    ({"schema_version": 1, "module_tree": [123]}, "module_tree"),
    ({"schema_version": 1, "module_tree": [{"label": "无 module"}]}, "module_tree"),
    ({"schema_version": 1, "field_labels": {"skills": "x"}}, "field_labels"),
    ({"schema_version": 1, "field_help": {"skills": []}}, "field_help"),
    ({"schema_version": 1, "group_labels": []}, "group_labels"),
    ({"schema_version": 1, "group_labels": {"skills": {"base": 1}}}, "group_labels"),
    ([1, 2], "顶层"),
])
def test_invalid_declaration_reports_human_error(
        tmp_path: Path, decl: object, need: str) -> None:
    pack_dir = _copy_pack(tmp_path)
    _write_decl(pack_dir, decl)
    with pytest.raises(api.EditorError) as excinfo:
        api.list_modules("test_demo", root=pack_dir.parent)
    msg = str(excinfo.value)
    assert "test_demo" in msg          # 指出包名
    assert "field_meta.json" in msg    # 指出文件
    assert need in msg                 # 指出哪个键/哪一层错


def test_load_field_meta_none_when_absent(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    assert fmp.load_field_meta(pack_dir) is None


def test_parse_normalizes_and_merge_is_pure() -> None:
    base = api.field_meta_table()
    before_label = base.module("skills").fields["power"].label  # type: ignore[union-attr]
    decl = fmp.parse_field_meta({
        "schema_version": 1,
        "module_labels": {"skills": "技能库X"},
        "field_labels": {"skills": {"power": "威力X"}},
    }, "probe")
    merged = fmp.merge_field_meta_table(base, decl)
    assert merged.module("skills").fields["power"].label == "威力X"  # type: ignore[union-attr]
    # base 未被改动（纯函数）
    assert base.module("skills").fields["power"].label == before_label  # type: ignore[union-attr]
    assert merged.module("skills") is not base.module("skills")


def test_merge_cache_invalidated_on_rewrite(tmp_path: Path) -> None:
    pack_dir = _copy_pack(tmp_path)
    _write_decl(pack_dir, {"schema_version": 1, "field_labels": {"skills": {"power": "第一版"}}})
    first = api._pack_meta_table(pack_dir).module("skills")
    assert first is not None and first.fields["power"].label == "第一版"
    _write_decl(pack_dir, {
        "schema_version": 1,
        "field_labels": {"skills": {"power": "第二版更长的标签"}}})
    second = api._pack_meta_table(pack_dir).module("skills")
    assert second is not None and second.fields["power"].label == "第二版更长的标签"


def test_real_content_packs_untouched() -> None:
    """只读护栏：跑完全部用例后真实内容包里不出现 field_meta.json。"""
    for pack in PACKS:
        assert not (CONTENT / pack / fmp.FIELD_META_FILENAME).exists()
