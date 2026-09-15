"""编辑器重写批20 · B 段：**装备页聚合视图**（用户 #3「很多装备类物品在装备页面不显示，
但物品页面显示」）。

用户实测：`items.json` 165 条里 **128 条带 `slot`**（本身就是装备），而 `equipment.json`
只有 **9 条**独立装备条目 → 装备页看不到那 128 条。用户要的是「装备页 = 全部装备」。

本批机制（**通用：按条件过滤的并入**，不写死任何模块名 / 键名）：

    "entry_merge_filtered": [
      { "target": "equipment", "from": "items", "where": { "has": ["slot"] } }
    ]

  · `where` 支持「有某键」（has）与「某键等于某值」（eq），两者可组合（AND）；
  · 目标模块条目 = 自身条目 ∪ 来源模块里满足条件的条目；并入条目标注**来源**（「来自 物品」）；
  · 点开编辑 → 仍写回**来源模块**的文件与校验（items.json），目标模块文件不动；
  · **只增不减**：来源模块（items）视图与计数完全不变；
  · 不声明该机制的包 → 行为与现状一致。

计数口径（写进台账 / 契约文档）：目标模块 `count` / `own_count` / `entry_index[].count`
**均含**并入条目；`merge_filtered_count` 单列并入条数；`total_count` 不再叠加（避免双计）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

from qbot_rpg.content import field_meta_pack as fp
from qbot_rpg.web import api, editor_ops

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
PROBE = REPO / "scripts" / "editor_dom_probe.py"

TARGET, SOURCE = "equipment", "items"


def _copy_veinborn(tmp_path: Path) -> Path:
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    return tmp_path


# =====================================================================================
# 一、声明层：entry_merge_filtered 严格解析（形态）
# =====================================================================================
def _meta(**over: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {"schema_version": 1}
    base.update(over)
    return base


def test_declaration_shape_is_strict() -> None:
    ok = fp.parse_field_meta(_meta(entry_merge_filtered=[
        {"target": "equipment", "from": "items", "where": {"has": ["slot"]}},
        {"target": "a", "from": "b", "where": {"eq": {"k": 1}, "has": ["x"]}},
    ]), "p")
    assert ok.entry_merge_filtered[0]["has"] == ("slot",)
    assert ok.entry_merge_filtered[1]["eq"] == {"k": 1}
    bad_cases = [
        {"target": "a", "from": "a"},                                   # 并入自身
        {"target": "a", "from": "b", "nope": 1},                        # 未知键
        {"target": "a", "from": "b", "where": {"nope": 1}},             # where 未知键
        {"target": "a", "from": "b", "where": {"eq": {"k": {"x": 1}}}},  # eq 非标量
        {"target": "a", "from": "b", "where": {"eq": {"k": None}}},      # eq null
        {"target": "a", "from": "b"},                                   # 无条件
        {"target": "", "from": "b", "where": {"has": ["x"]}},            # 空 target
    ]
    for spec in bad_cases:
        with pytest.raises(fp.PackFieldMetaError):
            fp.parse_field_meta(_meta(entry_merge_filtered=[spec]), "p")


def test_where_conditions_has_and_eq_compose() -> None:
    """has 与 eq 可组合（AND）；只看值形态，不认字段语义。"""
    assert api._entry_matches_where({"slot": "weapon"}, ("slot",), {}) is True
    assert api._entry_matches_where({"slot": None}, ("slot",), {}) is False
    assert api._entry_matches_where({"slot": ""}, ("slot",), {}) is True   # 「有某键」口径
    assert api._entry_matches_where({"type": "weapon", "slot": "weapon"},
                                    ("slot",), {"type": "weapon"}) is True
    assert api._entry_matches_where({"type": "armor", "slot": "weapon"},
                                    ("slot",), {"type": "weapon"}) is False
    assert api._entry_matches_where("scalar", ("slot",), {}) is False


# =====================================================================================
# 二、结构：装备页 = 自身条目 ∪ 并入条目；来源标注；计数三处一致
# =====================================================================================
def test_equipment_page_includes_filtered_items() -> None:
    le = api.list_entries("veinborn", TARGET, root=CONTENT)
    sections = le["merge_filtered_sections"]
    assert sections == [{"module": SOURCE, "label": "物品", "has": ["slot"], "eq": {},
                         "count": 128}]
    assert le["merge_filtered_count"] == 128
    own = [e for e in le["entries"] if not e.get("merged_from")]
    merged = [e for e in le["entries"] if e.get("merged_from")]
    assert len(own) == 9 and len(merged) == 128
    assert le["count"] == len(le["entries"]) == 137
    assert le["total_count"] == 137               # 并入已计入 count，不双计
    for e in merged:
        assert e["merged_from"] == SOURCE
        assert e["merged_from_label"] == "物品"
        assert e["merge_filtered"] is True
    # 并入条目确实都带 slot
    raw = json.loads((CONTENT / "veinborn" / "items.json").read_text(encoding="utf-8"))
    by_id = {x["id"]: x for x in raw}
    assert all(by_id[e["id"]].get("slot") for e in merged)


def test_counts_consistent_across_three_views() -> None:
    """左栏计数 = 条目列表 count = 全局索引 count（并入条目三处同口径）。"""
    le = api.list_entries("veinborn", TARGET, root=CONTENT)
    mods = api.list_modules("veinborn", root=CONTENT)

    def find(nodes: List[Dict[str, Any]], key: str) -> Dict[str, Any]:
        for n in nodes:
            if n["module"] == key:
                return n
            hit = find(n.get("children") or [], key)
            if hit:
                return hit
        return {}

    node = find(mods["modules"], TARGET)
    assert node["own_count"] == le["count"]
    assert node["merge_filtered_count"] == le["merge_filtered_count"] == 128
    assert node["merge_filtered"][0]["module"] == SOURCE
    idx = api.entry_index("veinborn", root=CONTENT)
    em = [m for m in idx["modules"] if m["module"] == TARGET][0]
    assert em["count"] == le["count"] == 137
    assert sum(1 for e in em["entries"] if e.get("merged_from")) == 128
    assert idx["total"] == sum(m["count"] for m in idx["modules"])


# =====================================================================================
# 三、side：并入只增不减——来源模块视图不变
# =====================================================================================
def test_source_module_view_unchanged(tmp_path: Path) -> None:
    """items 视图（条目 / 计数 / 索引）在「并入」声明前后完全一致。"""
    root = _copy_veinborn(tmp_path)
    decl_path = root / "veinborn" / "field_meta.json"
    raw = json.loads(decl_path.read_text(encoding="utf-8"))
    with_decl = {
        "entries": api.list_entries("veinborn", SOURCE, root=root),
        "index": [m for m in api.entry_index("veinborn", root=root)["modules"]
                  if m["module"] == SOURCE][0],
    }
    raw.pop("entry_merge_filtered", None)
    decl_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    without_decl = {
        "entries": api.list_entries("veinborn", SOURCE, root=root),
        "index": [m for m in api.entry_index("veinborn", root=root)["modules"]
                  if m["module"] == SOURCE][0],
    }
    assert with_decl["entries"] == without_decl["entries"]
    assert with_decl["index"] == without_decl["index"]


# =====================================================================================
# 四、回归：不声明该机制的包行为与现状一致
# =====================================================================================
def test_no_declaration_behaves_as_before(tmp_path: Path) -> None:
    root = _copy_veinborn(tmp_path)
    decl_path = root / "veinborn" / "field_meta.json"
    raw = json.loads(decl_path.read_text(encoding="utf-8"))
    raw.pop("entry_merge_filtered", None)
    decl_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    le = api.list_entries("veinborn", TARGET, root=root)
    assert le["merge_filtered_count"] == 0
    assert le["merge_filtered_sections"] == []
    assert le["count"] == 9 and le["total_count"] == 9
    assert all(not e.get("merged_from") for e in le["entries"])
    mods = api.list_modules("veinborn", root=root)

    def find(nodes: List[Dict[str, Any]]) -> Dict[str, Any]:
        for n in nodes:
            if n["module"] == TARGET:
                return n
            hit = find(n.get("children") or [])
            if hit:
                return hit
        return {}

    assert find(mods["modules"])["merge_filtered_count"] == 0
    # 空包（无任何声明）同样零并入
    blank = api.list_entries("demo_blank", "items", root=CONTENT)
    assert blank["merge_filtered_count"] == 0


def test_custom_where_filters_by_value(tmp_path: Path) -> None:
    """自定义 where（has + eq）在同一机制上生效——机制不写死任何模块/键名。"""
    root = _copy_veinborn(tmp_path)
    decl_path = root / "veinborn" / "field_meta.json"
    raw = json.loads(decl_path.read_text(encoding="utf-8"))
    raw["entry_merge_filtered"] = [
        {"target": "equipment", "from": "items",
         "where": {"has": ["slot"], "eq": {"type": "weapon"}}},
    ]
    decl_path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    le = api.list_entries("veinborn", TARGET, root=root)
    merged = [e for e in le["entries"] if e.get("merged_from")]
    items = json.loads((root / "veinborn" / "items.json").read_text(encoding="utf-8"))
    by_id = {x["id"]: x for x in items}
    assert merged, "至少应命中一条武器"
    assert all(by_id[e["id"]].get("type") == "weapon" for e in merged)
    assert all(by_id[e["id"]].get("slot") for e in merged)
    assert le["merge_filtered_sections"][0]["eq"] == {"type": "weapon"}


# =====================================================================================
# 五、端到端：点开并入条目 → 改值 → 写进来源模块 → 回退
# =====================================================================================
def test_merged_entry_write_hits_source_module_then_rollback(tmp_path: Path) -> None:
    root = _copy_veinborn(tmp_path)
    items_f = root / "veinborn" / "items.json"
    eq_f = root / "veinborn" / "equipment.json"
    items_before = items_f.read_text(encoding="utf-8")
    eq_before = eq_f.read_text(encoding="utf-8")
    # 前端按 merged_from 路由 → 用来源模块 + 条目 id 走既有保存链路
    le = api.list_entries("veinborn", TARGET, root=root)
    pick = [e for e in le["entries"] if e.get("merged_from")][0]
    res = editor_ops.save_entry("veinborn", pick["merged_from"], pick["id"],
                                {"price": 12345}, root=root, role="owner")
    assert res["ok"] is True, res
    after = json.loads(items_f.read_text(encoding="utf-8"))
    assert next(x for x in after if x["id"] == pick["id"])["price"] == 12345
    assert eq_f.read_text(encoding="utf-8") == eq_before      # 目标模块文件不动
    rb = editor_ops.rollback_module("veinborn", SOURCE, root=root, role="owner")
    assert rb["ok"] is True, rb
    assert items_f.read_text(encoding="utf-8") == items_before


# =====================================================================================
# 六、前端契约 + 真 Chromium DOM / 写盘回退 E2E
# =====================================================================================
def test_frontend_contract_for_merge_filtered() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("merge_filtered_sections", "merge_filtered_count", "state.mergeFiltered",
                  "e.merged_from", "来自 ", "mergeFiltered"):
        assert token in html, token


def _pw_python() -> str:
    cands = [sys.executable, "/usr/bin/python3", shutil.which("python3") or ""]
    for cand in cands:
        if not cand:
            continue
        if subprocess.run([cand, "-c", "import playwright"], capture_output=True).returncode == 0:
            return cand
    return ""


PW_PY = _pw_python()


@pytest.mark.skipif(not PW_PY or not PROBE.is_file(),
                    reason="本机无 playwright/chromium，跳过 DOM 实测")
def test_dom_equipment_merge_view_and_write_back(tmp_path: Path) -> None:
    """真 Chromium：装备页列出并入条目（标「来自 物品」）→ 点开路由回 items →
    改值保存真写进 items.json → 回退复原（equipment.json 全程不动）。"""
    root = _copy_veinborn(tmp_path)
    items_f = root / "veinborn" / "items.json"
    eq_f = root / "veinborn" / "equipment.json"
    items_before = items_f.read_text(encoding="utf-8")
    eq_before = eq_f.read_text(encoding="utf-8")
    out = tmp_path / "probe.json"
    proc = subprocess.run(
        [PW_PY, str(PROBE), "--repo", str(REPO), "--pack", "veinborn",
         "--module", TARGET, "--mode", "merge", "--host-python", sys.executable,
         "--edit-field", "price", "--edit-value", "12345", "--rollback",
         "--in-place", "--content-root", str(root), "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["pageErrors"] == []
    assert data["list"]["total"] == 137 and data["list"]["mergedCount"] == 128
    assert any("来自 物品" in t for t in data["list"]["mergedTags"])
    assert data["list"]["pickMod"] == SOURCE        # 编辑路由回来源模块
    assert data["edit"]["entryModule"] == SOURCE
    assert data["afterSaveField"] == 12345          # 保存后真写进 items.json
    assert data["afterRollbackField"] == 540        # 回退复原
    assert items_f.read_text(encoding="utf-8") == items_before
    assert eq_f.read_text(encoding="utf-8") == eq_before
