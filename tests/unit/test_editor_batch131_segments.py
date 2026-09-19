"""编辑器重写批13.1 · 段入口（一号原则续：框架登记了就要有入口）。

背景（批13 只做了一半）：settings 段的**字段登记**已做（`field_meta.py` 有 time_cycle 等），
但 `GET /api/pack/{pack}/module/settings/entries` 仍只列包数据已有的键 →
time_cycle / message_prefix / pvp / codex / shortcut_max 等「框架已登记、代码已消费」的段
在两个包里都看不到（字段登记了，却没有入口让作者看见/填写）。

本批机制（**不写死任何模块名/段名**）：
  · 对象型（entry_type=object）模块的条目列表 = 包数据已有键 ∪ 框架登记的顶层段；
  · 未配置段以「未配置态」出现（可点开、可填写、可保存），不因缺数据而消失；
  · 左栏计数 / 条目列表 / 全局检索三处同一口径（`_entry_rows` 单点）；
  · 保存未配置段正常走既有校验 / 原子写 / 备份 / 回退；
  · map 等其它形态模块无「段」概念 → 行为与现状一致（回归）。

覆盖：
  A. 段集合可见性（demo_blank vs veinborn 差集只体现「是否已配置」）；
  B. 计数口径自洽（左栏 = 条目列表 = 全局检索）；
  C. 未配置段详情可渲染（字段全 present=False、分组自洽）；
  D. 未配置段写盘 → 回退复原（原始 JSON 证据）；
  E. 通用性 / 回归（map 模块与无登记模块不变；未声明模块仍 404）；
  F. 校验如实红拦（登记了类型校验的对象段，非法值必须红拦且零落盘；range 按既有 Y-1 黄提示）；
  G. 自检脚本覆盖段入口 + 页脚批次串 = 当前批次（批14 起由本用例末尾断言）。
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.content.models import FieldMeta, FieldMetaTable, ModuleMeta
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

sys.path.insert(0, str(REPO / "scripts"))
import editor_visibility_selfcheck as selfcheck  # noqa: E402

SETTINGS_FIELDS = set(api.default_field_meta_table().module("settings").fields)


def _seg_ids(le: Dict[str, Any]) -> set:
    return {e["id"] for e in le["entries"]}


def _mounted_from(pack: str, module: str) -> set:
    """批19 #8：从 `module` 被 entry_tree 挂到父节点的段 id（仍属「入口可见」）。"""
    mods = api.list_modules(pack, root=CONTENT)
    out: set = set()

    def walk(nodes: list) -> None:
        for n in nodes or []:
            for item in n.get("mounted") or []:
                if item.get("from") == module:
                    out.add(item["id"])
            walk(n.get("children") or [])

    walk(mods["modules"])
    for v in mods.get("views") or []:
        for item in v.get("mounted") or []:
            if item.get("from") == module:
                out.add(item["id"])
    return out


def _visible_seg_ids(pack: str, module: str) -> set:
    """模块条目列表 ∪ 从该模块挂出去的段（批19 #8 后「段入口可见」的统一口径）。"""
    return _seg_ids(api.list_entries(pack, module, root=CONTENT)) | _mounted_from(pack, module)


# =====================================================================================
# A · 段集合可见性（一号原则：框架登记段必须在列，且跨包一致）
# =====================================================================================
@pytest.mark.parametrize("pack", ["demo_blank", "veinborn"])
def test_object_module_entries_cover_registered_segments(pack: str) -> None:
    le = api.list_entries(pack, "settings", root=CONTENT)
    # 批19 #8：被 entry_tree 挂到父节点的段仍属「入口可见」（在父节点下）。
    assert SETTINGS_FIELDS <= _visible_seg_ids(pack, "settings"), \
        sorted(SETTINGS_FIELDS - _visible_seg_ids(pack, "settings"))
    assert le["count"] == le["configured_count"] + le["unconfigured_count"]
    assert le["count"] == len(le["entries"])
    assert le["unconfigured_count"] == len(
        [e for e in le["entries"] if e.get("unconfigured")])


def test_demo_blank_and_veinborn_segment_sets_equal() -> None:
    """最空白包与功能齐全包：段集合一致，差异只在「是否已配置」。"""
    blank = api.list_entries("demo_blank", "settings", root=CONTENT)
    full = api.list_entries("veinborn", "settings", root=CONTENT)
    assert _visible_seg_ids("demo_blank", "settings") == _visible_seg_ids("veinborn", "settings")
    assert blank["unconfigured_count"] > 0 and full["unconfigured_count"] > 0
    # 空白包未配置段 ⊇ 功能包未配置段（功能包多出来的都是已配置段）
    blank_unc = {e["id"] for e in blank["entries"] if e.get("unconfigured")}
    full_unc = {e["id"] for e in full["entries"] if e.get("unconfigured")}
    assert full_unc <= blank_unc
    # 功能包「已配置」的段，在空白包里要么已配置、要么以未配置态在场（不会消失）
    assert set(e["id"] for e in full["entries"]) <= _visible_seg_ids("demo_blank", "settings")


def test_registered_but_absent_segment_present_unconfigured() -> None:
    """批13 审计点名的段：两个包都必须看得到（未配置态，或在父节点下挂载可见）。"""
    for pack in ("demo_blank", "veinborn"):
        le = api.list_entries(pack, "settings", root=CONTENT)
        by_id = {e["id"]: e for e in le["entries"]}
        mounted = _mounted_from(pack, "settings")
        for key in ("time_cycle", "message_prefix", "pvp", "codex", "shortcut_max"):
            assert key in by_id or key in mounted, (pack, key)
            if key in by_id:
                assert by_id[key]["unconfigured"] is True, (pack, key)


# =====================================================================================
# B · 计数口径自洽：左栏 = 条目列表 = 全局检索
# =====================================================================================
@pytest.mark.parametrize("pack", ["demo_blank", "veinborn"])
def test_counts_consistent_across_views(pack: str) -> None:
    mods = api.list_modules(pack, root=CONTENT)

    def _node(nodes: list, mid: str) -> Dict[str, Any]:
        for n in nodes:
            if n["module"] == mid:
                return n
            hit = _node(n.get("children") or [], mid)
            if hit:
                return hit
        return {}

    settings_node = _node(mods["modules"], "settings")
    le = api.list_entries(pack, "settings", root=CONTENT)
    idx = api.entry_index(pack, root=CONTENT)
    idx_settings = next(m for m in idx["modules"] if m["module"] == "settings")
    assert settings_node["own_count"] == le["count"] == idx_settings["count"]
    assert idx_settings["unconfigured_count"] == le["unconfigured_count"]
    assert settings_node["total_count"] == settings_node["count"] + settings_node["merged_count"]


# =====================================================================================
# C · 未配置段详情可渲染（present=False；分组计数自洽）
# =====================================================================================
def test_unconfigured_segment_detail_renders_all_registered_children() -> None:
    d = api.entry_detail("demo_blank", "settings", "time_cycle", root=CONTENT)
    assert d["unconfigured"] is True
    keys = [f["key"] for f in d["fields"]]
    assert {"enabled", "season", "period", "weather", "broadcast", "combat"} <= set(keys)
    assert all(f["present"] is False for f in d["fields"])
    assert d["field_count"] == len(d["fields"])
    assert sum(g["count"] for g in d["groups"]) == d["field_count"]


@pytest.mark.parametrize("eid", ["shortcut_max", "imprints", "default_job_id", "attr_types"])
def test_unconfigured_scalar_and_wide_segments_have_a_field(eid: str) -> None:
    d = api.entry_detail("demo_blank", "settings", eid, root=CONTENT)
    assert d["unconfigured"] is True
    assert d["field_count"] >= 1
    assert all(f["present"] is False for f in d["fields"])


def test_configured_segment_not_marked_unconfigured() -> None:
    d = api.entry_detail("veinborn", "settings", "battle", root=CONTENT)
    assert d["unconfigured"] is False


# =====================================================================================
# D · 未配置段写盘 → 回退复原（原始 JSON 证据）
# =====================================================================================
@pytest.fixture()
def blank_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "demo_blank", tmp_path / "blank")
    return tmp_path


def test_unconfigured_object_segment_write_then_rollback(blank_copy: Path) -> None:
    sf = blank_copy / "blank" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    patch = {"enabled": False, "season": {"season_days": 5}}
    res = editor_ops.save_entry("blank", "settings", "time_cycle", patch,
                                root=blank_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["time_cycle"] == {"enabled": False, "season": {"season_days": 5}}
    assert set(after) == set(json.loads(before)) | {"time_cycle"}

    rb = editor_ops.rollback_module("blank", "settings", root=blank_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == before


def test_unconfigured_scalar_segment_writes_raw_value(blank_copy: Path) -> None:
    sf = blank_copy / "blank" / "settings.json"
    before = sf.read_text(encoding="utf-8")
    res = editor_ops.save_entry("blank", "settings", "shortcut_max", {"shortcut_max": 33},
                                root=blank_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["shortcut_max"] == 33 and isinstance(after["shortcut_max"], int)
    editor_ops.rollback_module("blank", "settings", root=blank_copy, role="owner")
    assert sf.read_text(encoding="utf-8") == before


def test_saved_segment_then_listed_as_configured(blank_copy: Path) -> None:
    res = editor_ops.save_entry("blank", "settings", "pvp",
                                {"enabled": True, "level_gate": 10},
                                root=blank_copy, role="owner")
    assert res["ok"] is True, res
    le = api.list_entries("blank", "settings", root=blank_copy)
    by_id = {e["id"]: e for e in le["entries"]}
    assert "pvp" in by_id and not by_id["pvp"].get("unconfigured")
    assert le["configured_count"] == 3
    # 批25：settings 框架登记段 +5（register_gift/register_level/command_gates/
    # rate_limit/message_chunk_len）→ 未配置 32 + 5 = 37
    # 批32 A1：settings 再 +1（pack_protection）→ 38；批37 战后恢复段 → +1 = 39
    # 批38：副手开关 equipment_offhand + 相性四段（affinities/affinity_pools/
    # affinity_linkage/affinity_reactions）→ +5 = 44
    # 批39：打造路径开关 deep_craft → +1 = 45
    # 批45：面板预算 panel_budget + 怪物数值倍率 monster_scaling → +2 = 47
    # 批46：符文孔位 rune_sockets → +1 = 48
    # 批50：特效轴声明 effect_axes → +1 = 49
    assert le["unconfigured_count"] == 49


# =====================================================================================
# E · 通用性 / 回归（不写死模块名；map 模块与无登记模块不变）
# =====================================================================================
def test_mechanism_is_generic_object_module(tmp_path: Path) -> None:
    """任意 object 模块只要登记顶层字段即享有；map 模块不套用（无「段」概念）。"""
    pkg = tmp_path / "p"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P", "version": "1", "schema_version": 1,
        "modules": ["obj_mod", "map_mod"]}), encoding="utf-8")
    (pkg / "obj_mod.json").write_text(json.dumps({"alpha": 1}), encoding="utf-8")
    (pkg / "map_mod.json").write_text(json.dumps({"k1": {"base": 1}}), encoding="utf-8")
    meta = FieldMetaTable(modules={
        "obj_mod": ModuleMeta(entry_type="object", fields={
            "alpha": FieldMeta(type="int", label="甲"),
            "beta": FieldMeta(type="int", label="乙"),
            "gamma": FieldMeta(type="str", label="丙"),
        }),
        "map_mod": ModuleMeta(entry_type="map", fields={
            "registered_but_absent": FieldMeta(type="int", label="不该出现的段"),
        }),
    })
    # 用注入元数据直接验 `_entry_rows` 口径（list_entries 走包合并表，此处验机制本身）
    rows = api._entry_rows({"alpha": 1}, meta.module("obj_mod"))
    assert [r[0] for r in rows] == ["alpha", "beta", "gamma"]
    assert [r[2] is api._UNCONFIGURED for r in rows] == [False, True, True]
    # map 模块：登记字段不是条目键 → 不新增条目
    mrows = api._entry_rows({"k1": {"base": 1}}, meta.module("map_mod"))
    assert [r[0] for r in mrows] == ["k1"]


def test_object_module_with_single_registered_field_gets_entry() -> None:
    """conditional（object，数据为 {}，仅登记 1 段）→ 该段以未配置态在场（通用机制生效）。"""
    le = api.list_entries("veinborn", "conditional", root=CONTENT)
    assert le["count"] == 1 and le["configured_count"] == 0
    assert le["unconfigured_count"] == 1
    assert le["entries"][0]["id"] == "conditional"
    assert le["entries"][0]["unconfigured"] is True


def test_map_module_entries_unchanged() -> None:
    """回归：map 模块（stats/formula/templates）条目集不因本批变化。"""
    stats = api.list_entries("veinborn", "stats", root=CONTENT)
    data = json.loads((CONTENT / "veinborn" / "stats.json").read_text(encoding="utf-8"))
    assert _seg_ids(stats) == set(data)
    assert stats["unconfigured_count"] == 0


def test_undeclared_module_still_not_found() -> None:
    with pytest.raises(api.NotFound):
        api.list_entries("demo_blank", "manifest", root=CONTENT)


# =====================================================================================
# F · 校验如实红拦（登记了范围校验的段：越界红拦 + 零落盘）
# =====================================================================================
def test_registered_segment_red_blocks_on_type_error(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    """登记了类型校验的未配置段：非法值红拦 + 零落盘；合法值正常写入。"""
    pkg = tmp_path / "p2"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "P2", "version": "1", "schema_version": 1, "modules": ["cfg"]}),
        encoding="utf-8")
    (pkg / "cfg.json").write_text("{}", encoding="utf-8")
    meta = FieldMetaTable(modules={
        "cfg": ModuleMeta(entry_type="object", fields={
            "limit": FieldMeta(type="int", range_min=0, range_max=10, label="上限"),
        }),
    })
    # 注入合成元数据表（与既有 test_editor_save_chain 同一手法：entry_slot 也读该表）。
    monkeypatch.setattr(api, "_META_TABLE", meta)
    bad = editor_ops.save_entry("p2", "cfg", "limit", {"limit": "不是数字"},
                                root=tmp_path, role="owner", meta=meta)
    assert bad["ok"] is False and bad["level"] == "red"
    assert (pkg / "cfg.json").read_text(encoding="utf-8") == "{}"
    good = editor_ops.save_entry("p2", "cfg", "limit", {"limit": 5},
                                 root=tmp_path, role="owner", meta=meta)
    assert good["ok"] is True, good
    assert json.loads((pkg / "cfg.json").read_text(encoding="utf-8"))["limit"] == 5


# =====================================================================================
# G · 自检脚本覆盖段入口 + 页脚批次串
# =====================================================================================
@pytest.mark.parametrize("pack", ["demo_blank", "veinborn"])
def test_selfcheck_covers_segment_entries(pack: str) -> None:
    r = selfcheck.check_pack(pack, CONTENT)
    assert r["errors"] == [], r["errors"]
    assert r["segments_checked"] >= len(SETTINGS_FIELDS)
    assert "settings" in r["segments"]
    seg = r["segments"]["settings"]
    assert SETTINGS_FIELDS <= set(seg["ids"])
    assert len(seg["configured"]) == api.list_entries(
        pack, "settings", root=CONTENT)["configured_count"]


def test_selfcheck_segment_diff_only_config_status() -> None:
    rows = [selfcheck.check_pack(p, CONTENT) for p in ("demo_blank", "veinborn")]
    lines, errors = selfcheck._segment_diff(rows)
    assert errors == [], errors
    assert any("settings" in ln and "段集合差 无" in ln for ln in lines)


def test_selfcheck_segment_diff_tolerates_pack_specific_key() -> None:
    """包自有数据键（框架未登记的段，如 zz_probe_ext 的 `ext`）属合法增补，不判差异。"""
    rows = [selfcheck.check_pack(p, CONTENT) for p in ("demo_blank", "zz_probe_ext")]
    lines, errors = selfcheck._segment_diff(rows)
    assert errors == [], errors
    extras = {e for r in rows
              for e in r["segments"].get("settings", {}).get("extra", [])}
    assert "ext" in extras
    assert any("包自有数据键" in ln for ln in lines)


def test_footer_batch_string_is_current() -> None:
    """页脚批次串随批推进更新（旧批次串不得残留）。"""
    html = HTML.read_text(encoding="utf-8")
    assert "批53 · 时序与资源轴" in html
    assert "批49 · 测试 flake 根治" not in html
    assert "批48 · 符文特殊效果" not in html
    assert "批13.1 · 段入口" not in html
    assert "批13 · 能力可见性" not in html


def test_frontend_exposes_unconfigured_marker() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("未配置 · 框架支持", "个框架段未配置", "e.unconfigured", "d.unconfigured"):
        assert token in html, token
