"""编辑器重写批19 · 段 F：条目级层级（用户 #8，本批最大件）。

用户原话：「炼金、任务板、锻造之类应该归入**生活**栏，却出现在**基础**栏里。环境事件、
时间天气应该像行动那样归在**地图**下。」

机制（**通用、包声明驱动、不写死任何名称**）：包 `field_meta.json` 顶层 `entry_tree`
声明「把某模块内的段/条目挂到另一个父节点之下」——左栏层级从「模块级」扩展到「条目级」。

声明形态（写进 `docs/编辑器重写_需求与约束.md` §〇·补九）：
    "entry_tree": [
      {"parent": "<父节点>",
       "sections": [{"from": "<来源模块>", "id": "<条目 id>"}, …],
       "keep_top_level": false}
    ]
  · 父节点 = 本包 manifest 声明的模块，或 entry_merge 的虚拟聚合视图；
  · 默认 **移走**（来源模块条目列表不再列出；计数/检索改归父节点）；
  · `keep_top_level: true` 或父节点是虚拟视图 = **显示挂载**（保留原位，纯展示，不进计数）。

覆盖：A 声明解析；B 移走语义 + 三处计数自洽；C 显示挂载；D 端到端写盘+回退（写回来源模块）；
E veinborn 实测左栏结构；F 回归（不声明的包行为不变）；G 前端契约 + 自检脚本。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content import field_meta_pack as pack_meta
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"


def _write_pack(root: Path, tree: Any = None) -> Path:
    pkg = root / "p"
    pkg.mkdir(exist_ok=True)
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P", "version": "1", "schema_version": 1,
        "modules": ["src", "dst"]}), encoding="utf-8")
    (pkg / "src.json").write_text(json.dumps(
        {"aaa": {"name": "甲"}, "bbb": {"name": "乙"}, "ccc": {"name": "丙"}}),
        encoding="utf-8")
    (pkg / "dst.json").write_text(json.dumps({"zzz": {"name": "己"}}), encoding="utf-8")
    decl: Dict[str, Any] = {"schema_version": 1}
    if tree is not None:
        decl["entry_tree"] = tree
    (pkg / "field_meta.json").write_text(json.dumps(decl, ensure_ascii=False),
                                         encoding="utf-8")
    return pkg


def _node(pack: str, mod: str, root: Path) -> Dict[str, Any]:
    mods = api.list_modules(pack, root=root)
    for n in mods["modules"]:
        if n["module"] == mod:
            return n
    raise AssertionError(mod)


def _idx(pack: str, mod: str, root: Path) -> Dict[str, Any]:
    return next(m for m in api.entry_index(pack, root=root)["modules"] if m["module"] == mod)


# =====================================================================================
# A · 声明解析（严格形态；简写；非法报错）
# =====================================================================================
def test_entry_tree_registered_top_level_key() -> None:
    assert "entry_tree" in pack_meta.TOP_LEVEL_KEYS


def test_entry_tree_parse_full_and_shorthand() -> None:
    d = pack_meta.parse_field_meta({"schema_version": 1, "entry_tree": [
        {"parent": "life", "keep_top_level": True,
         "sections": [{"from": "settings", "id": "alchemy"}, "settings.forge"]},
    ]}, "p")
    assert d.entry_tree[0]["parent"] == "life"
    assert d.entry_tree[0]["keep_top_level"] is True
    assert d.entry_tree[0]["sections"] == (
        {"from": "settings", "id": "alchemy"}, {"from": "settings", "id": "forge"})
    assert pack_meta.parse_field_meta({"schema_version": 1}, "p").entry_tree == ()


@pytest.mark.parametrize("bad", [
    "notalist",
    [{"sections": [{"from": "a", "id": "b"}]}],                       # 缺 parent
    [{"parent": "p", "sections": []}],                                # sections 空
    [{"parent": "p", "sections": [{"from": "a"}]}],                   # 缺 id
    [{"parent": "p", "sections": [{"from": "a", "id": "b", "x": 1}]}],  # 未知键
    [{"parent": "p", "sections": [{"from": "a", "id": "b"}], "z": 1}],  # 未知键
    [{"parent": "p", "keep_top_level": "yes",
      "sections": [{"from": "a", "id": "b"}]}],                       # 非布尔
    [{"parent": "p", "sections": [{"from": "a", "id": "b"}, {"from": "a", "id": "b"}]}],
])
def test_entry_tree_illegal_forms_raise(bad: Any) -> None:
    with pytest.raises(pack_meta.PackFieldMetaError):
        pack_meta.parse_field_meta({"schema_version": 1, "entry_tree": bad}, "p")


# =====================================================================================
# B · 移走语义 + 三处计数自洽
# =====================================================================================
def test_move_semantics_and_counts_consistent(tmp_path: Path) -> None:
    _write_pack(tmp_path, [{"parent": "dst", "sections": [
        {"from": "src", "id": "aaa"}, {"from": "src", "id": "bbb"}]}])
    src_ids = [e["id"] for e in api.list_entries("p", "src", root=tmp_path)["entries"]]
    assert src_ids == ["ccc"]                       # 被移走的段不在原处
    src_node = _node("p", "src", tmp_path)
    assert src_node["own_count"] == 1 and src_node["moved_out_ids"] == ["aaa", "bbb"]
    assert [x["id"] for x in src_node["mounted"]] == []

    le = api.list_entries("p", "dst", root=tmp_path)
    assert le["count"] == 3 and le["mounted_count"] == 2
    moved = {e["id"]: e.get("mounted_from") for e in le["entries"]}
    assert moved["aaa"] == "src" and moved["bbb"] == "src" and moved["zzz"] is None
    dst_node = _node("p", "dst", tmp_path)
    assert dst_node["own_count"] == 3
    assert sorted(x["id"] for x in dst_node["mounted"]) == ["aaa", "bbb"]
    # 三处自洽：左栏 own_count = 条目列表 count = 全局索引 count
    assert dst_node["own_count"] == le["count"] == _idx("p", "dst", tmp_path)["count"]
    assert src_node["own_count"] == _idx("p", "src", tmp_path)["count"] == 1
    # 总数不变（只是改归父节点）
    idx = api.entry_index("p", root=tmp_path)
    assert idx["total"] == sum(m["count"] for m in idx["modules"]) == 4


def test_entry_tree_ignores_dangling_and_undeclared(tmp_path: Path) -> None:
    _write_pack(tmp_path, [
        {"parent": "ghost", "sections": [{"from": "src", "id": "aaa"}]},
        {"parent": "dst", "sections": [{"from": "nope", "id": "x"},
                                       {"from": "src", "id": "missing"},
                                       {"from": "src", "id": "aaa"}]},
    ])
    mods = api.list_modules("p", root=tmp_path)
    assert any("ghost" in n for n in mods["notes"])
    # 只 aaa 有效挂载；missing/nope/ghost 被忽略
    le = api.list_entries("p", "dst", root=tmp_path)
    assert [e["id"] for e in le["entries"] if e.get("mounted_from")] == ["aaa"]


# =====================================================================================
# C · 显示挂载（keep_top_level）与虚拟视图父节点
# =====================================================================================
def test_keep_top_level_display_mount(tmp_path: Path) -> None:
    _write_pack(tmp_path, [{"parent": "dst", "keep_top_level": True,
                            "sections": [{"from": "src", "id": "aaa"}]}])
    assert [e["id"] for e in api.list_entries("p", "src", root=tmp_path)["entries"]] \
        == ["aaa", "bbb", "ccc"]
    le = api.list_entries("p", "dst", root=tmp_path)
    assert le["count"] == 1 and le["mounted_count"] == 0
    assert [s["module"] for s in le["mounted_sections"]] == ["src"]
    assert [e["id"] for e in le["mounted_sections"][0]["entries"]] == ["aaa"]
    assert _node("p", "src", tmp_path)["own_count"] == 3
    assert _node("p", "dst", tmp_path)["own_count"] == 1


def test_virtual_view_parent_is_display_only(tmp_path: Path) -> None:
    _write_pack(tmp_path, [{"parent": "life", "sections": [
        {"from": "src", "id": "aaa"}]}])
    pkg = tmp_path / "p"
    decl = json.loads((pkg / "field_meta.json").read_text(encoding="utf-8"))
    decl["entry_merge"] = {"life": ["src", "dst"]}
    (pkg / "field_meta.json").write_text(json.dumps(decl), encoding="utf-8")
    mods = api.list_modules("p", root=tmp_path)
    view = next(v for v in mods["views"] if v["module"] == "life")
    assert [x["id"] for x in view["mounted"]] == ["aaa"]
    # 虚拟视图父节点 → 显示挂载：来源仍列出、计数不双计
    assert [e["id"] for e in api.list_entries("p", "src", root=tmp_path)["entries"]] \
        == ["aaa", "bbb", "ccc"]
    assert view["total_count"] == view["merged_count"]


# =====================================================================================
# D · 端到端：编辑挂载条目 → 写回来源模块文件 → 回退逐字节复原
# =====================================================================================
@pytest.fixture()
def veinborn_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def test_edit_mounted_section_writes_back_to_source(veinborn_copy: Path) -> None:
    sf = veinborn_copy / "veinborn" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    # settings.alchemy 被 entry_tree 挂到「生活」视图下；编辑仍写回 settings.json
    res = editor_ops.save_entry("veinborn", "settings", "alchemy",
                                {"farming": {"enabled": True, "plots_max": 9}},
                                root=veinborn_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["alchemy"]["farming"]["plots_max"] == 9
    assert set(after) == set(json.loads(before))

    # 挂载视图左栏仍可见该条目（在父节点下），且路由回 settings
    mods = api.list_modules("veinborn", root=veinborn_copy)
    life = next(v for v in mods["views"] if v["module"] == "life")
    hit = next(x for x in life["mounted"] if x["id"] == "alchemy")
    assert hit["from"] == "settings"

    rb = editor_ops.rollback_module("veinborn", "settings", root=veinborn_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == before


# =====================================================================================
# E · veinborn 实测：左栏层级结构
# =====================================================================================
def test_veinborn_left_tree_structure() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    # 生活视图：炼金 / 委托板 / 锻造 挂到「生活」下（显示挂载）
    life = next(v for v in mods["views"] if v["module"] == "life")
    assert {x["id"] for x in life["mounted"]} == {"alchemy", "quest_board", "forge"}
    # 地图：环境事件 / 时间天气 移入地图下（不再出现在「基础」）
    maps = _node("veinborn", "maps", CONTENT)
    assert {x["id"] for x in maps["mounted"]} == {"env_event", "time_cycle"}
    assert maps["own_count"] == maps["count"]
    settings = _node("veinborn", "settings", CONTENT)
    assert set(settings["moved_out_ids"]) == {"env_event", "time_cycle"}
    settings_ids = {e["id"] for e in api.list_entries(
        "veinborn", "settings", root=CONTENT)["entries"]}
    assert "env_event" not in settings_ids and "time_cycle" not in settings_ids
    # 地图条目列表里确实含这两条，且标出来源模块
    maps_entries = api.list_entries("veinborn", "maps", root=CONTENT)["entries"]
    mounted = {e["id"]: e.get("mounted_from") for e in maps_entries if e.get("mounted_from")}
    assert mounted == {"env_event": "settings", "time_cycle": "settings"}
    # 三处计数自洽
    assert maps["own_count"] == api.list_entries("veinborn", "maps", root=CONTENT)["count"] \
        == _idx("veinborn", "maps", CONTENT)["count"]


# =====================================================================================
# F · 回归：不声明 entry_tree 的包行为与现状一致
# =====================================================================================
def test_no_entry_tree_is_unchanged(tmp_path: Path) -> None:
    _write_pack(tmp_path, None)
    assert [e["id"] for e in api.list_entries("p", "src", root=tmp_path)["entries"]] \
        == ["aaa", "bbb", "ccc"]
    assert api.list_entries("p", "src", root=tmp_path)["moved_out_ids"] == []
    src = _node("p", "src", tmp_path)
    assert src["mounted"] == [] and src["mounted_count"] == 0
    assert "entry_tree" not in json.loads(
        (tmp_path / "p" / "field_meta.json").read_text(encoding="utf-8"))


def test_existing_packs_without_declaration_all_clean() -> None:
    """真实包里只有 veinborn 声明 entry_tree；其余包挂载面为空。"""
    for pack in ("demo_blank", "demo_full", "test_demo"):
        mods = api.list_modules(pack, root=CONTENT)
        for m in mods["modules"]:
            assert m["mounted"] == [] and m["moved_out_ids"] == [], (pack, m["module"])


# =====================================================================================
# G · 前端契约 + 一号原则自检
# =====================================================================================
def test_frontend_entry_tree_contract() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("appendMountedLeaves", "selectMountedEntry", "mounted_from",
                  "mounted_sections", "移入自", "挂载自", "e.mounted_from"):
        assert token in html, token


def test_selfcheck_still_passes() -> None:
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    import editor_visibility_selfcheck as selfcheck
    for pack in ("demo_blank", "veinborn"):
        r = selfcheck.check_pack(pack, CONTENT)
        assert r["errors"] == [], (pack, r["errors"])
    rows = [selfcheck.check_pack(p, CONTENT) for p in ("demo_blank", "veinborn")]
    _lines, errors = selfcheck._segment_diff(rows)
    assert errors == [], errors


def test_footer_batch_string_is_batch20() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "批27 · α组（技能侧）" in html
    assert "批18 · 预设细化与效果扩展" not in html
