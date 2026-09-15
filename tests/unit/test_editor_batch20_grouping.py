"""编辑器重写批20 · C 段：**右栏分区（二级页签）+ 中栏列表分组折叠**（用户 #1）。

用户原话：「职业、效果、状态、派生链、行动、商店、NPC、页面还是没分页。」主 agent 裁决：
**右栏分区页签 + 中间列表按分组折叠**（沿用既有「列表不翻页」口径，不引入翻页器）。

本批机制（**通用：分组来自元数据 / 包声明**，不写死任何模块名 / 字段名）：

  ① 右栏：框架元数据的**子分组**（`ModuleMeta.field_subgroups` / `subgroup_order` /
     `subgroup_labels`，包可用 `field_meta.json.subgroup_labels` 覆盖显示名）→ 出**二级页签**
     （既有 `button.gtab` 机制扩展：`.gtabs2` / `.gtab2` / `.gpane2`）；一次只看一个子页，
     字段仍在 DOM 里（hidden），不因分页消失。**没有子分组声明的模块不出现二级页签**
     （仍是既有「主块 + 折叠子块」）。
  ② 中栏：包声明 `entry_groups`（`by: field | id_prefix` + labels/other_label/collapsed）→
     本模块自身条目折成**可折叠小节**（首节默认展开，其余默认折叠，可点开/收起）；
     **不声明 = 行为与现状一致**（条目不带 `group` 键、计划为空）。

覆盖：结构（子分组块计划 / 分组计划）、跨包一致、无声明回归、自定义声明通用性、
前端契约、真 Chromium DOM 量测（≥3 个长模块的修前 vs 修后对照）。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

from qbot_rpg.web import api

REPO = Path(api.repo_root())
CONTENT = REPO / "content"
HTML = REPO / "qbot_rpg" / "web" / "static" / "index.html"
PROBE = REPO / "scripts" / "editor_dom_probe.py"

# 框架已声明子分组的长模块（一个分组 + 多子分组 → 二级页签）
SUBGROUP_MODULES = ("effects", "statuses", "skill_chains", "action", "jobs", "npc", "shop")
# 包声明了中栏分组的模块
GROUPED_MODULES = ("effects", "statuses", "skill_chains", "action", "jobs", "npc", "shop")
# DOM 量测用例（长模块；≥3 个）
DOM_CASES = ("effects", "action", "jobs", "statuses")


def _first(mod: str, pack: str = "veinborn") -> str:
    return api.list_entries(pack, mod, root=CONTENT)["entries"][0]["id"]


# =====================================================================================
# 一、右栏：子分组块计划（元数据驱动）
# =====================================================================================
def test_framework_declares_subgroups_for_long_modules() -> None:
    meta = api.default_field_meta_table()
    for mod in SUBGROUP_MODULES:
        m = meta.module(mod)
        assert m is not None and m.field_subgroups, mod
        assert m.subgroup_order, mod
        assert set(m.field_subgroups.values()) <= set(m.subgroup_order), mod
        # 显示名：框架默认（包可覆盖）
        assert set(m.subgroup_labels) >= set(m.subgroup_order), mod


@pytest.mark.parametrize("mod", SUBGROUP_MODULES)
def test_entry_blocks_are_named_subgroups(mod: str) -> None:
    """条目详情的块计划 = 命名子分组（不再是「主块 + 隐式更多字段」）；
    字段不因分页消失：块计数之和 == 字段数，且每字段恰落一块。"""
    d = api.entry_detail("veinborn", mod, _first(mod), root=CONTENT)
    blocks = [b for bs in d["blocks"].values() for b in bs]
    assert blocks, mod
    named = [b for b in blocks if b["name"]]
    assert named, mod
    assert sum(b["count"] for b in blocks) == d["field_count"]
    keys: List[str] = []
    for b in blocks:
        keys.extend(b["keys"])
    assert sorted(keys) == sorted(f["key"] for f in d["fields"])
    assert len(keys) == len(set(keys))
    # 每个字段的 subgroup 归属与计划一致
    by_key = {f["key"]: f for f in d["fields"]}
    for b in blocks:
        for k in b["keys"]:
            assert by_key[k]["subgroup"] == b["name"]


def test_subgroup_labels_default_and_pack_override() -> None:
    """显示名 = 框架默认 + 包声明覆盖（veinborn 覆盖 npc 的子分组名）。"""
    d = api.entry_detail("veinborn", "npc", _first("npc"), root=CONTENT)
    labels = {b["name"]: b["label"] for bs in d["blocks"].values() for b in bs}
    assert labels.get("base") == "标识与类型"        # 包覆盖
    d2 = api.entry_detail("veinborn", "effects", _first("effects"), root=CONTENT)
    labels2 = {b["name"]: b["label"] for bs in d2["blocks"].values() for b in bs}
    assert labels2.get("numeric") == "数值与持续"     # 框架默认


def test_modules_without_subgroups_keep_old_behaviour() -> None:
    """没有子分组声明的模块仍是既有口径（主块常驻 + 隐式「更多字段」折叠块）。"""
    d = api.entry_detail("veinborn", "settings", "battle", root=CONTENT)
    blocks = d["blocks"]["默认"]
    assert [b["name"] for b in blocks] == ["", api.AUTO_MORE_BLOCK]
    assert blocks[0]["collapsed"] is False and blocks[1]["collapsed"] is True


# =====================================================================================
# 二、中栏：条目分组计划
# =====================================================================================
@pytest.mark.parametrize("mod", GROUPED_MODULES)
def test_entry_group_plan_is_consistent(mod: str) -> None:
    le = api.list_entries("veinborn", mod, root=CONTENT)
    plan = le["entry_groups"]
    assert plan, mod
    assert plan[0]["collapsed"] is False                 # 默认展开首节
    assert all(g["collapsed"] for g in plan[1:])         # 其余默认折叠
    assert sum(g["count"] for g in plan) == le["count"]
    glabel = {g["name"]: g["label"] for g in plan}
    for e in le["entries"]:
        assert e["group"] in glabel, (mod, e)
        assert e["group_label"] == glabel[e["group"]]


def test_group_by_field_and_by_id_prefix() -> None:
    """两种分组维度：字段取值（effects.type）与 ID 前缀（statuses）。"""
    eff = api.list_entries("veinborn", "effects", root=CONTENT)
    names = {g["name"] for g in eff["entry_groups"]}
    assert "mark_add" in names and "heal" in names
    by_id = {e["id"]: e for e in eff["entries"]}
    for e in eff["entries"]:
        raw = by_id[e["id"]]
        assert raw["group"] == ("mark_add" if raw["id"].startswith("mark_add") else raw["group"])
    st = api.list_entries("veinborn", "statuses", root=CONTENT)
    for e in st["entries"]:
        assert e["group"] == e["id"].split("_")[0] or e["group"] == api.ENTRY_GROUP_OTHER


def test_group_plan_generic_no_module_names(tmp_path: Path) -> None:
    """通用性：换一个模块 + 换一个分组字段（包声明驱动）→ 计划随之改变，代码零改动。"""
    shutil.copytree(CONTENT / "veinborn", tmp_path / "veinborn")
    decl = tmp_path / "veinborn" / "field_meta.json"
    raw = json.loads(decl.read_text(encoding="utf-8"))
    raw["entry_groups"] = {"enemies": {"by": "field", "field": "tier",
                                       "labels": {"boss": "首领", "normal": "普通"}}}
    decl.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    le = api.list_entries("veinborn", "enemies", root=tmp_path)
    plan = {g["name"]: g for g in le["entry_groups"]}
    assert "boss" in plan and plan["boss"]["label"] == "首领"
    assert sum(g["count"] for g in le["entry_groups"]) == le["count"]
    assert all(e["group"] in plan for e in le["entries"])
    # 未声明的模块（effects）在该包里也没有分组计划
    assert api.list_entries("veinborn", "effects", root=tmp_path)["entry_groups"] == []


def test_no_declaration_keeps_current_behaviour() -> None:
    """不声明分组信息的模块 / 包：计划为空、条目不出现 group 键（行为与现状一致）。"""
    for mod in ("enemies", "items", "skills", "maps"):
        le = api.list_entries("veinborn", mod, root=CONTENT)
        assert le["entry_groups"] == []
        for e in le["entries"]:
            assert "group" not in e and "group_label" not in e
    blank = api.list_entries("demo_blank", "items", root=CONTENT)
    assert blank["entry_groups"] == []


def test_entry_groups_declaration_is_strict() -> None:
    from qbot_rpg.content import field_meta_pack as fp
    ok = fp.parse_field_meta({"schema_version": 1, "entry_groups": {
        "m": {"by": "id_prefix"}}}, "p")
    assert ok.entry_groups["m"]["by"] == "id_prefix"
    for bad in ({"m": {"by": "nope"}},
                {"m": {"by": "field"}},
                {"m": {"by": "id_prefix", "nope": 1}},
                {"m": {"by": "id_prefix", "labels": {"a": ""}}},
                {"m": {"by": "id_prefix", "collapsed": "yes"}}):
        with pytest.raises(fp.PackFieldMetaError):
            fp.parse_field_meta({"schema_version": 1, "entry_groups": bad}, "p")


# =====================================================================================
# 三、前端契约 + 真 Chromium DOM 量测（修前 vs 修后）
# =====================================================================================
def test_frontend_contract_for_grouping() -> None:
    html = HTML.read_text(encoding="utf-8")
    for token in ("gtabs2", "gtab2", "gpane2", "subTabPaneHtml", "bindSubTabs",
                  "BLOCK_MAIN_LABEL", "AUTO_MORE_BLOCK", "lgrp", "lgrp-head", "lgrp-body",
                  "renderGroupedItems", "bindListGroups", "entryGroups"):
        assert token in html, token


def _pw_python() -> str:
    for cand in (sys.executable, "/usr/bin/python3", shutil.which("python3") or ""):
        if not cand:
            continue
        if subprocess.run([cand, "-c", "import playwright"], capture_output=True).returncode == 0:
            return cand
    return ""


PW_PY = _pw_python()


@pytest.mark.skipif(not PW_PY or not PROBE.is_file(),
                    reason="本机无 playwright/chromium，跳过 DOM 量测")
@pytest.mark.parametrize("mod", DOM_CASES)
def test_dom_measure_grouping_reduces_first_screen(mod: str, tmp_path: Path) -> None:
    """真 Chromium：右栏 scrollHeight 修前（全展开）> 修后（≤ 可视高度）；
    二级页签 ≥2；中栏分组 ≥2、首节展开其余折叠。"""
    out = tmp_path / f"{mod}.json"
    proc = subprocess.run(
        [PW_PY, str(PROBE), "--repo", str(REPO), "--pack", "veinborn",
         "--module", mod, "--mode", "groups", "--host-python", sys.executable,
         "--json", str(out)],
        capture_output=True, text=True, timeout=300)
    assert proc.returncode == 0, proc.stderr[-3000:]
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["pageErrors"] == []
    after, before = data["after"], data["before_expanded"]
    # 右栏：修前必须滚动；修后首屏看得完（不靠滚动）
    assert before["scrollHeight"] > before["clientHeight"], (mod, before)
    assert after["scrollHeight"] <= after["clientHeight"], (mod, after)
    assert after["scrollHeight"] < before["scrollHeight"], (mod, after)
    # 二级页签：≥2 个子页；一次只显示一个；可见字段 = 当前子页里能看见的字段
    assert after["subTabs"] >= 2, (mod, after)
    assert after["subPanes"] >= after["subTabs"]
    assert after["activeSubVisible"] <= after["activeSubTotal"] < after["totalRows"]
    assert after["visibleRows"] == after["activeSubVisible"]
    # 中栏：分组小节 ≥2，首节展开、其余折叠（默认），可见条目 ≤ 首节条数
    assert after["listGroups"] >= 2, (mod, after)
    assert after["listGroupCollapsed"] == after["listGroups"] - 1, (mod, after)
    assert after["listVisibleItems"] <= after["listItems"]
    # 字段不因分页消失
    assert after["totalRows"] == before["totalRows"]
