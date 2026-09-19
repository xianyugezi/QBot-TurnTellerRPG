"""编辑器重写批13 · 能力可见性（一号原则落地：编辑器 = 框架的编辑器）。

依据：
  · `docs/编辑器修改意见0915_台账与方案.md` §〇·补 一号原则（**最高依据**）；
  · `docs/能力缺漏审计_四方对照.md` ①-1/①-4/①-5/①-6 + U1/U2/U5/U6/U7；
  · 本批四块：A 左栏 = 框架能力集 ∪ 包声明；B 补模块目录条目；C 补字段登记；
    D「生活」聚合视图（entry_merge 虚拟视图）。

覆盖：
  A. `list_modules` 新增 views / available；`modules ∪ views ∪ available ⊇ 框架目录全集`；
     未启用候选条目数如实；`entry_index.available` 扩展全局检索，但 modules/total 口径不变；
     已启用模块行为与计数回归不变（entry_merge / keep_top_level / 层级声明仍生效）。
  B. `FRAMEWORK_MODULE_CATALOG` 新增 farming/contest/assistant/quest_board/codex/gathering/
     templates；gathering 批13 标「未实现」→ **批36 · X2 引擎实装后翻转为可启用**；
     time_cycle 依 U2 不新增一级模块。
  C. 13 条 settings 字段登记 + templates 模块（map）+ formula 公式段字段 +
     maps.gather_points/weather_pool/monsters 时间天气键（**只加展示层，不改校验语义**）。
  D. 「生活」视图：entry_merge 目标未在 manifest 声明 → 虚拟聚合视图；
     批12 的 jobs 挂靠取消；不新增数据文件。
  自检. 空白包 vs 功能齐全包：模块/字段显示集一致（scripts/editor_visibility_selfcheck.py）。
  前端. EDITOR_CAPABILITY 纯逻辑 + renderModules 接线 + EditorEntry 检索含 available。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Set

import pytest

from qbot_rpg.content.module_catalog import CATALOG_BY_MODULE, FRAMEWORK_MODULE_CATALOG
from qbot_rpg.web import api, editor_ops

NODE = shutil.which("node")
REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
API_PY = REPO / "qbot_rpg" / "web" / "api.py"

CATALOG: Set[str] = {e.module for e in FRAMEWORK_MODULE_CATALOG}

sys.path.insert(0, str(REPO / "scripts"))
import editor_visibility_selfcheck as selfcheck  # noqa: E402


def _html() -> str:
    return HTML.read_text(encoding="utf-8")


def _marked(name: str) -> str:
    m = re.search(r"/\* %s_BEGIN \*/(.*?)/\* %s_END \*/" % (name, name), _html(), re.S)
    assert m, f"index.html 缺少 EDITOR_{name} 标记块"
    return m.group(1)


def _run_node(source: str) -> Any:
    proc = subprocess.run([NODE, "-e", source], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def _tree_modules(nodes: object) -> Set[str]:
    out: Set[str] = set()
    for n in nodes if isinstance(nodes, list) else []:
        out.add(str(n.get("module")))
        out |= _tree_modules(n.get("children"))
    return out


def _shown(mods: Dict[str, Any]) -> Set[str]:
    shown = _tree_modules(mods.get("modules"))
    shown |= {str(v["module"]) for v in mods.get("views") or []}
    shown |= {str(a["module"]) for a in mods.get("available") or []}
    return shown


# =====================================================================================
# A · 左栏 = 框架能力集 ∪ 包声明
# =====================================================================================
@pytest.mark.parametrize("pack", ["demo_blank", "veinborn"])
def test_left_panel_union_covers_framework_catalog(pack: str) -> None:
    mods = api.list_modules(pack, root=CONTENT)
    assert CATALOG <= _shown(mods), f"{pack} 左栏未覆盖框架目录：{sorted(CATALOG - _shown(mods))}"


def test_demo_blank_shows_framework_capabilities_as_unenabled() -> None:
    """几乎空白的包：左栏给出框架能力全集（未启用态），不是空白。"""
    mods = api.list_modules("demo_blank", root=CONTENT)
    declared = _tree_modules(mods["modules"])
    assert mods["available_count"] == len(mods["available"])
    assert {a["module"] for a in mods["available"]} == CATALOG - declared
    for row in mods["available"]:
        assert row["enabled"] is False and row["in_catalog"] is True
        assert row["count"] == 0 and row["own_count"] == 0 and row["total_count"] == 0
        assert row["available"] is True and row["merged_into"] is None


def test_available_count_reflects_retained_data(tmp_path: Path) -> None:
    """停用但保留数据文件 → 未启用候选条目数如实（非 0）。"""
    pkg = tmp_path / "p_keep"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "K", "version": "1", "schema_version": 1, "modules": ["items"]}),
        encoding="utf-8")
    (pkg / "items.json").write_text("[]", encoding="utf-8")
    (pkg / "fishing.json").write_text(json.dumps([{"id": "a"}, {"id": "b"}]),
                                      encoding="utf-8")
    mods = api.list_modules("p_keep", root=tmp_path)
    fish = next(a for a in mods["available"] if a["module"] == "fishing")
    assert fish["count"] == 2


def test_no_duplicate_module_across_three_sections() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    mods_set = _tree_modules(mods["modules"])
    views = {v["module"] for v in mods["views"]}
    avail = {a["module"] for a in mods["available"]}
    assert not (mods_set & views) and not (mods_set & avail) and not (views & avail)
    # 已启用/视图节点 enabled=True；未启用候选 enabled=False（前端 capsState 依据）。
    for n in mods["modules"]:
        assert n["enabled"] is True
    for a in mods["available"]:
        assert a["enabled"] is False


def test_enabled_behaviour_regression_unchanged() -> None:
    """回归：已启用模块计数 / 条目 / settings 聚合仍与批12 口径一致。"""
    mods = api.list_modules("veinborn", root=CONTENT)
    settings = next(m for m in mods["modules"] if m["module"] == "settings")
    assert settings["label"] == "基础"
    assert [m["module"] for m in settings["merged"]] == ["stats", "formula"]
    assert settings["total_count"] == settings["count"] + settings["merged_count"]
    # 已启用模块条目列表仍正常
    assert api.list_entries("veinborn", "skills", root=CONTENT)["count"] > 0


def test_entry_index_available_extends_search_but_not_total(tmp_path: Path) -> None:
    pkg = tmp_path / "p_idx"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "I", "version": "1", "schema_version": 1, "modules": ["items"]}),
        encoding="utf-8")
    (pkg / "items.json").write_text(json.dumps([{"id": "x", "name": "甲"}]),
                                    encoding="utf-8")
    (pkg / "fishing.json").write_text(json.dumps([{"id": "fish_1", "name": "锦鲤"}]),
                                      encoding="utf-8")
    idx = api.entry_index("p_idx", root=tmp_path)
    assert idx["total"] == 1                       # total 只算声明模块（口径不变）
    assert {m["module"] for m in idx["modules"]} == {"items"}
    fish = next(a for a in idx["available"] if a["module"] == "fishing")
    assert fish["count"] == 1 and fish["entries"][0]["name"] == "锦鲤"


# =====================================================================================
# B · 框架模块目录条目
# =====================================================================================
def test_catalog_has_framework_systems_entries() -> None:
    for mod in ("farming", "contest", "assistant", "quest_board", "codex",
                "templates", "gathering"):
        assert mod in CATALOG_BY_MODULE, mod
        e = CATALOG_BY_MODULE[mod]
        assert e.label and e.purpose and e.entry_type in ("list", "map", "object")


def test_time_cycle_is_not_a_first_level_module_by_u2() -> None:
    """U2：时间天气按定稿挂「通用设置」卡片，**不**新增一级模块。"""
    assert "time_cycle" not in CATALOG_BY_MODULE
    fields = api.default_field_meta_table().module("settings").fields
    assert "time_cycle" in fields


def test_gathering_is_marked_unimplemented_and_not_enableable(tmp_path: Path) -> None:
    """B（批36 · X2 更新）：gathering 引擎已实装 → implemented=True 且可启用。

    批13 原断言为「未实现 / 不可启用」；批36 采集/挖掘引擎落地后本断言同步翻转为
    「已实现 / 可启用」。写盘验收走 tmp 内容根（批19.1 防污染门禁：绝不触碰仓库 content/）。
    """
    assert CATALOG_BY_MODULE["gathering"].implemented is True
    assert api.is_enableable_module("gathering") is True
    # 在临时内容根启用（真实包零改动）
    root = tmp_path / "content"
    shutil.copytree(CONTENT / "demo_blank", root / "demo_blank")
    env = editor_ops.set_module_enabled("demo_blank", "gathering", True, root=root)
    assert env.get("errors") == [], env
    manifest = json.loads(
        (root / "demo_blank" / "manifest.json").read_text(encoding="utf-8"))
    assert "gathering" in (manifest.get("modules") or [])
    # object 骨架 = {}
    assert (root / "demo_blank" / "gathering.json").read_text(
        encoding="utf-8").strip() == "{}"


def test_module_catalog_rows_expose_implemented_and_settings_section() -> None:
    rows = {r["module"]: r for r in api.module_catalog("demo_blank", root=CONTENT)["modules"]}
    assert rows["gathering"]["implemented"] is True   # 批36 · X2：引擎已实装
    assert rows["farming"]["implemented"] is True
    assert rows["farming"]["settings_section"] == "settings.alchemy.farming"
    assert rows["templates"]["settings_section"] == ""


def test_gathering_visible_in_left_panel_as_unimplemented() -> None:
    """B（批36 · X2 更新）：左栏候选里 gathering 仍在，且不再是「未实现」态。"""
    mods = api.list_modules("demo_blank", root=CONTENT)
    g = next(a for a in mods["available"] if a["module"] == "gathering")
    assert g["implemented"] is True


# =====================================================================================
# C · 字段登记（13 条 + templates + formula + maps）
# =====================================================================================
SETTINGS_KEYS = (
    "time_cycle", "message_prefix", "pvp", "codex", "event_log_cap", "event_log_capacity",
    "command_mode", "require_at", "at_text", "attr_types", "conditional_rules", "imprints",
    "shortcut_max", "default_job_id", "max_dialog_depth", "resource_pct",
)


def test_settings_fields_registered() -> None:
    fields = api.default_field_meta_table().module("settings").fields
    for key in SETTINGS_KEYS:
        assert key in fields, key


def test_command_mode_enum_and_default_job_ref() -> None:
    fields = api.default_field_meta_table().module("settings").fields
    cm = fields["command_mode"]
    assert cm.type == "enum" and set(cm.enum) == {
        "global_shortcut", "combat_shortcut", "prefix_only"}
    dj = fields["default_job_id"]
    assert dj.type == "ref" and dj.ref_target == "jobs"


def test_time_cycle_subfield_shape() -> None:
    tc = api.default_field_meta_table().module("settings").fields["time_cycle"]
    assert tc.type == "obj"
    assert {"enabled", "season", "period", "weather", "broadcast", "combat"} <= set(tc.children)
    assert tc.children["season"].children["season_days"].type == "int"


def test_templates_module_registered_as_map() -> None:
    mmeta = api.default_field_meta_table().module("templates")
    assert mmeta is not None and mmeta.entry_type == "map"
    assert mmeta.value_meta is not None and mmeta.value_meta.type == "str"
    # 批19 #4：条目列表 = 包覆盖键 ∪ 框架全量模板表键（全量展示，一号原则）。
    le = api.list_entries("veinborn", "templates", root=CONTENT)
    assert le["entry_type"] == "map"
    assert le["key_source"] == "templates"
    assert le["count"] == le["covered_count"] + le["framework_default_count"]
    assert le["framework_default_count"] > 0 and le["covered_count"] == 2
    d = api.entry_detail("veinborn", "templates", "register_success_next", root=CONTENT)
    assert d["fields"][0]["control"] == "textarea"


def test_manifest_templates_now_registered() -> None:
    from qbot_rpg.content.loader import check_manifest_modules_registered
    manifest = json.loads((CONTENT / "veinborn" / "manifest.json").read_text(encoding="utf-8"))
    assert check_manifest_modules_registered(manifest["modules"]) == []


def test_formula_section_fields_registered() -> None:
    fields = api.default_field_meta_table().module("formula").fields
    for key in ("damage", "hit", "crit", "block", "defense", "weakness", "elements", "luck",
                "derived", "power", "effects_link", "death_check", "stats_collector"):
        assert key in fields, key
    assert fields["hit"].children["k"].range_min == 0.05
    assert set(fields["death_check"].children["mutual_kill_result"].enum) == {
        "draw", "player_loss"}


def test_formula_section_renders_for_pack_that_defines_it(tmp_path: Path) -> None:
    pkg = tmp_path / "p_formula"
    pkg.mkdir()
    (pkg / "manifest.json").write_text(json.dumps({
        "name": "F", "version": "1", "schema_version": 1, "modules": ["formula"]}),
        encoding="utf-8")
    (pkg / "formula.json").write_text(json.dumps({
        "hit": {"k": 0.2, "cap_min": 10, "cap_max": 95}}), encoding="utf-8")
    d = api.entry_detail("p_formula", "formula", "hit", root=tmp_path)
    assert [f["key"] for f in d["fields"]] == ["k", "cap_min", "cap_max"]


def test_maps_gather_points_and_weather_fields_registered() -> None:
    maps = api.default_field_meta_table().module("maps").fields
    assert maps["weather_pool"].type == "list"
    gp = maps["gather_points"].element.children
    assert {"id", "item", "rarity", "rate", "name", "weather_mods"} <= set(gp)
    assert {"weather", "rate_mult", "rarity_shift"} <= set(gp["weather_mods"].element.children)
    monsters = maps["monsters"].element.children
    assert {"active_time", "seasons", "periods", "weather_weights"} <= set(monsters)


def test_gather_points_columns_rendered() -> None:
    maps_data = json.loads((CONTENT / "veinborn" / "maps.json").read_text(encoding="utf-8"))
    mid = maps_data[0]["id"]
    d = api.entry_detail("veinborn", "maps", mid, root=CONTENT)
    gp = next(f for f in d["fields"] if f["key"] == "gather_points")
    cols = {c["key"] for c in gp["columns"]}
    assert {"id", "item", "rarity", "rate", "name", "weather_mods"} <= cols


# =====================================================================================
# D · 「生活」聚合视图（entry_merge 虚拟视图）
# =====================================================================================
def test_life_view_is_virtual_and_has_no_data_file() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    assert next(v for v in mods["views"] if v["module"] == "life")["label"] == "生活"
    assert "life" not in {a["module"] for a in mods["available"]}
    assert not (CONTENT / "veinborn" / "life.json").exists()


def test_life_view_aggregates_real_life_modules() -> None:
    le = api.list_entries("veinborn", "life", root=CONTENT)
    assert [s["module"] for s in le["merge_sections"]] == [
        "proficiency", "enhance", "forge", "recipe"]
    assert le["total_count"] == sum(s["count"] for s in le["merge_sections"])


def test_batch12_jobs_parenting_cancelled() -> None:
    mods = api.list_modules("veinborn", root=CONTENT)
    jobs = next(m for m in mods["modules"] if m["module"] == "jobs")
    assert jobs["children"] == []


# =====================================================================================
# 自检 · 一号原则（空白包 vs 功能齐全包）
# =====================================================================================
@pytest.mark.parametrize("pack", ["demo_blank", "veinborn"])
def test_selfcheck_visibility_consistency(pack: str) -> None:
    r = selfcheck.check_pack(pack, CONTENT)
    assert r["errors"] == [], r["errors"]
    assert r["covered"] == len(selfcheck.CATALOG)


# =====================================================================================
# 前端 · 左栏渲染 / 一键启用 / 检索覆盖
# =====================================================================================
def test_capability_pure_logic() -> None:
    if NODE is None:
        pytest.skip("本机无 node")
    js = _marked("EDITOR_CAPABILITY")
    out = _run_node(js + "\nconsole.log(JSON.stringify({"
                    "a: capsState({implemented:false}),"
                    "b: capsState({available:true}),"
                    "c: capsState({enabled:true}),"
                    "ta: capsTag({available:true}), tb: capsTag({implemented:false}),"
                    "ea: capsEnableable({available:true}),"
                    "eb: capsEnableable({enabled:true}),"
                    "g: indexGroups({modules:[{module:'a'}],available:[{module:'b'}]})"
                    ".map(function(x){return x.module;})}));")
    assert out["a"] == "unimplemented" and out["b"] == "available" and out["c"] == "enabled"
    assert out["ta"] == "未启用" and out["tb"] == "未实现"
    assert out["ea"] is True and out["eb"] is False
    assert out["g"] == ["a", "b"]


def test_editor_entry_search_covers_available() -> None:
    if NODE is None:
        pytest.skip("本机无 node")
    js = _marked("EDITOR_ENTRY")
    harness = (
        "var module = {exports:{}};\n" + js
        + "\nvar EditorEntry = module.exports;\n"
        + "var index = {modules:[{module:'items',label:'物品',namespace:'item_lib',"
        "entries:[{id:'x',name:'甲'}]}],available:[{module:'fishing',label:'钓鱼',"
        "namespace:'fish_lib',entries:[{id:'fish_1',name:'锦鲤'}]},"
        "{module:'extra',label:'额外',namespace:'item_lib',"
        "entries:[{id:'dup',name:'重复'}]}]};\n"
        "console.log(JSON.stringify({"
        "search: EditorEntry.searchIndex(index,'鲤').map(function(g){return g.module;}),"
        "idDup: EditorEntry.idStatus('dup','items',index)}));"
    )
    proc = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["search"] == ["fishing"]
    # 未启用模块（保留数据）的同命名空间 ID 也参与唯一性判定
    assert out["idDup"]["ok"] is False


def test_render_modules_wiring() -> None:
    html = _html()
    for token in ("enableAvailableModule", "state.views", "state.available",
                  "mod-sep", "capsTag(", "dataset.available", "未启用 · 框架能力"):
        assert token in html, token
    assert "EditorMerge.visibleModules(state.modules)" in html
    # 一键启用复用 ⚙ 面板写入链路
    assert '"/module/" + enc(mod) + "/toggle"' in html


def test_capability_css_present() -> None:
    html = _html()
    for token in (".mod.view", ".mod.off", ".mod-sep", ".mod.unimplemented"):
        assert token in html, token
