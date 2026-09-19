"""编辑器重写批14 · #6 装备槽位可编辑 + 联动（用户原话：装备槽位无法编辑，如果在装备页面
进行编辑，不会同步更新出新增加的部位）。

三条：
  ① `settings.slot_defs`（部位表）可编辑（依赖 #4 的对象子字段可编辑）：新增/删除/改部位；
  ② 联动刷新：部位表变更后，物品/装备条目里「部位」引用字段的候选**立即**反映新部位
     （引用选择器下拉 / ID 唯一性 / 候选人选），不得刷新页面或重启；
  ③ 反向：删掉某部位后，已引用它的数据**如实提示**（引用者列表，黄提示不硬拦）；
  ④ 一致性：条目详情字段数 ↔ 引用候选 ↔ 名义索引三处口径自洽。

覆盖：
  A. slot_defs 对象子字段可编 + 新增/删除部位写盘 → 回退逐字节复原；
  B. 引用候选联动（同一进程/会话内，无需刷新）：新增后候选含新部位，删除后不含；
  C. 删部位 → 引用者黄提示（列出引用者；不阻断保存）；
  D. 一致性：条目详情 / 引用候选 / 命名空间索引三处口径；
  E. 前端契约：保存后清引用候选缓存（invalidateRefCache）+ 动态键空间增删控件。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, Dict

import pytest

from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"

SLOT_TARGET = "settings.slot_defs"


@pytest.fixture()
def pack_copy(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


def _slot_ids(root: Path) -> set:
    return set(json.loads((root / "veinborn" / "settings.json").read_text(
        encoding="utf-8"))["slot_defs"])


def _ref_ids(pack: str, root: Path) -> set:
    r = api.ref_options(pack, SLOT_TARGET, root=root)
    assert r["known"] is True
    return {o["id"] for o in r["options"]}


# =====================================================================================
# A · 部位表可编 + 新增/删除写盘 → 回退
# =====================================================================================
def test_slot_defs_subfields_editable() -> None:
    # 批15 #9：slot_defs（键 → 小结构）改为整条目「键值表格」——列 = 子结构字段（name/max），
    # 行 = 各部位；仍可增删/改名（动态键空间），写盘链路不变。
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    assert d["whole_table"] is True and d["open_keys"] is False
    field = d["fields"][0]
    assert field["control"] == "kvtable" and field["editable"] is True
    kv = field["kv_table"]
    assert kv["mode"] == "obj"
    # 批38 ③：部位定义登记 role（部位角色，main/offhand 下拉）+ 中文名 → 表格列扩一列
    assert [c["key"] for c in kv["columns"]] == ["name", "max", "role"]
    assert kv["open_keys"] is True   # 动态键空间：键可改、行可增删
    rows = {r["key"]: r for r in kv["rows"]}
    assert rows["weapon"]["cells"] == {"name": "武器", "max": 1}
    assert [c["control"] for c in kv["columns"]] == ["text", "number", "select"]
    assert kv["columns"][2]["enum"] == ["main", "offhand"]


def test_add_slot_writes_and_rolls_back(pack_copy: Path) -> None:
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"belt": {"name": "腰带", "max": 2}},
                                root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["slot_defs"]["belt"] == {"name": "腰带", "max": 2}
    assert _slot_ids(pack_copy) == set(json.loads(before_text)["slot_defs"]) | {"belt"}
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == before_text


def test_change_existing_slot_name_writes(pack_copy: Path) -> None:
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"weapon": {"name": "主手", "max": 1}},
                                root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after = json.loads(sf.read_text(encoding="utf-8"))
    assert after["slot_defs"]["weapon"]["name"] == "主手"
    assert set(after["slot_defs"]) == set(json.loads(before_text)["slot_defs"])
    editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert sf.read_text(encoding="utf-8") == before_text


def test_delete_slot_writes_and_rolls_back(pack_copy: Path) -> None:
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"accessory": None}, root=pack_copy, role="owner")
    assert res["ok"] is True, res
    assert "accessory" not in _slot_ids(pack_copy)
    rb = editor_ops.rollback_module("veinborn", "settings", root=pack_copy, role="owner")
    assert rb["ok"] is True, rb
    assert sf.read_text(encoding="utf-8") == before_text


# =====================================================================================
# B · 引用候选联动（同一进程内，无需刷新/重启）
# =====================================================================================
def test_ref_candidates_reflect_new_slot_immediately(pack_copy: Path) -> None:
    before = _ref_ids("veinborn", pack_copy)
    assert "belt" not in before
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"belt": {"name": "腰带", "max": 1}},
                                root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after = _ref_ids("veinborn", pack_copy)
    assert after == before | {"belt"}


def test_ref_candidates_drop_deleted_slot_immediately(pack_copy: Path) -> None:
    before = _ref_ids("veinborn", pack_copy)
    assert "accessory" in before
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"accessory": None}, root=pack_copy, role="owner")
    assert res["ok"] is True, res
    after = _ref_ids("veinborn", pack_copy)
    assert after == before - {"accessory"}


def test_slot_ref_field_rendered_as_picker() -> None:
    """物品/装备条目的「部位」字段：展示层按下拉候选渲染（type 仍 str，判定不变）。"""
    d = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    assert d["whole_table"] is True and d["fields"][0]["control"] == "kvtable"
    le = api.list_entries("veinborn", "items", root=CONTENT)
    eid = le["entries"][0]["id"]
    detail = api.entry_detail("veinborn", "items", eid, root=CONTENT)
    slot = {f["key"]: f for f in detail["fields"]}["slot"]
    assert slot["control"] == "ref"
    assert slot["ref_target"] == SLOT_TARGET
    assert slot["type"] == "str"  # 校验口径不变（只是控件换下拉）


# =====================================================================================
# C · 删部位 → 引用者黄提示（不硬拦）
# =====================================================================================
def test_delete_slot_reports_referrers_yellow_not_blocking(pack_copy: Path) -> None:
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"weapon": None}, root=pack_copy, role="owner")
    assert res["ok"] is True and res["level"] == "yellow", res
    warn = next(w for w in res["warnings"] if w["code"] == "orphan_ref_after_key_removed")
    assert warn["removed_keys"] == ["weapon"]
    assert warn["referrers"], "应列出引用被删部位的条目"
    assert all(h["value"] == "weapon" for h in warn["referrers"])
    assert "weapon" in warn["message"]
    # 黄提示附带「怎么办」，且不阻断保存（文件已写）
    assert warn["how_to_fix"]


def test_delete_unreferenced_slot_no_noise(pack_copy: Path) -> None:
    """删一个没人引用的新部位 → 不产生引用者提示（不噪音）。"""
    editor_ops.save_entry("veinborn", "settings", "slot_defs",
                          {"temp_slot": {"name": "临时", "max": 1}},
                          root=pack_copy, role="owner")
    res = editor_ops.save_entry("veinborn", "settings", "slot_defs",
                                {"temp_slot": None}, root=pack_copy, role="owner")
    assert res["ok"] is True
    assert not [w for w in res["warnings"] if w["code"] == "orphan_ref_after_key_removed"]


def test_validate_reports_referrers_without_writing(pack_copy: Path) -> None:
    sf = pack_copy / "veinborn" / "settings.json"
    before_text = sf.read_text(encoding="utf-8")
    res = editor_ops.validate_entry("veinborn", "settings", "slot_defs",
                                    {"weapon": None}, root=pack_copy, role="owner")
    assert res["ok"] is True and res["level"] == "yellow"
    assert any(w["code"] == "orphan_ref_after_key_removed" for w in res["warnings"])
    assert sf.read_text(encoding="utf-8") == before_text


# =====================================================================================
# D · 一致性：条目详情 ↔ 引用候选 ↔ 命名空间索引
# =====================================================================================
def test_slot_counts_consistent_across_views() -> None:
    detail = api.entry_detail("veinborn", "settings", "slot_defs", root=CONTENT)
    # 批15 #9：整条目键值表格 → 部位键在表格行（columns 来自子结构，rows 来自数据）
    kv = detail["fields"][0]["kv_table"]
    slot_keys = {r["key"] for r in kv["rows"]}
    assert detail["field_count"] == 1 and kv["row_count"] == len(slot_keys)
    assert _ref_ids("veinborn", CONTENT) == slot_keys
    # 命名空间索引（引用候选唯一来源）与方法同源
    idx = api._PackView(CONTENT / "veinborn",
                        api._manifest(CONTENT / "veinborn")).name_index()
    assert set(idx[SLOT_TARGET]) == slot_keys
    # 左栏计数 = 条目列表 = 全局索引（settings 模块级口径，批13.1 既立，本批不变）
    mods = api.list_modules("veinborn", root=CONTENT)

    def _node(nodes: list, mid: str) -> Dict[str, Any]:
        for n in nodes:
            if n["module"] == mid:
                return n
            hit = _node(n.get("children") or [], mid)
            if hit:
                return hit
        return {}

    node = _node(mods["modules"], "settings")
    le = api.list_entries("veinborn", "settings", root=CONTENT)
    idx_settings = next(m for m in api.entry_index("veinborn", root=CONTENT)["modules"]
                        if m["module"] == "settings")
    assert node["own_count"] == le["count"] == idx_settings["count"]


def test_slot_keys_unique_in_candidates() -> None:
    ids = [o["id"] for o in api.ref_options("veinborn", SLOT_TARGET, root=CONTENT)["options"]]
    assert len(ids) == len(set(ids))


# =====================================================================================
# E · 前端契约：保存后清引用缓存 + 动态键空间增删控件
# =====================================================================================
def test_frontend_invalidates_ref_cache_after_save() -> None:
    html = HTML.read_text(encoding="utf-8")
    assert "function invalidateRefCache()" in html
    assert "state.refCache = {}" in html
    # 保存与回退成功路径都要失效缓存（同一会话内候选立即联动）
    assert html.count("invalidateRefCache();") >= 2
    for token in ("data-openadd", "data-keydel", "open_keys", "data-oroot"):
        assert token in html, token
